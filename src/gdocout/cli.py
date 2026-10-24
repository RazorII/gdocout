"""gdocout: turn Google Docs, Sheets and Slides into files you can open offline, without signing in."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__, fetch, google, report, run
from .inventory import REPORT_NAME, STATE_DIR
from .model import CONVERTED, LABELS, Entry
from .state import State

FORMAT_HELP = (
    "format for one kind of Google file, e.g. --format document=pdf. "
    "Kinds and formats: "
    + "; ".join(f"{k.name}={'|'.join(k.exports)}" for k in google.KINDS.values() if k.exports)
    + ". Defaults: Word, Excel, PowerPoint, PDF for drawings, KMZ for maps."
)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="gdocout",
        description="Turn Google Docs, Sheets and Slides into Word, Excel and PowerPoint files without signing in. "
        "Works on files shared 'anyone with the link', one link at a time or a whole offline Google Drive folder.",
    )
    p.add_argument("--version", action="version", version=f"gdocout {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    s = sub.add_parser("scan", help="look through a folder and say what a copy would do (offline, writes nothing)")
    s.add_argument("source", type=Path)
    s.add_argument("--flat", action="store_true", help="plan for all files in one folder")
    s.add_argument("--format", action="append", default=[], metavar="KIND=FMT", help=FORMAT_HELP)
    s.add_argument("--json", action="store_true")

    c = sub.add_parser("copy", help="copy a folder, converting every Google file it can; resumable")
    c.add_argument("source", type=Path, help="the offline Google Drive folder")
    c.add_argument("--dest", type=Path, required=True, help="where the copy goes: an empty folder, or one gdocout copied into before (to continue)")
    c.add_argument("--flat", action="store_true", help="put every file in one folder instead of keeping the folder structure")
    c.add_argument("--format", action="append", default=[], metavar="KIND=FMT", help=FORMAT_HELP)
    c.add_argument("--limit", type=int, metavar="N", help="download at most N Google files this run (a sample, to check sharing first)")
    c.add_argument("--google-only", action="store_true", help="skip copying ordinary files this run")
    c.add_argument("--recheck", action="store_true", help="ask Google again about files it refused before (after an owner changed sharing)")
    c.add_argument("--no-links", action="store_true", help="don't leave a link page where a Google file couldn't be saved")
    c.add_argument("--max-workers", type=int, default=8, metavar="N", help="most downloads at once (default 8; gdocout starts lower and works up)")
    c.add_argument("--json", action="store_true", help="print the summary as JSON")

    r = sub.add_parser("report", help="rebuild the HTML report of an earlier copy")
    r.add_argument("dest", type=Path)
    r.add_argument("--json", action="store_true")

    ln = sub.add_parser("link", help="download Google Docs/Sheets/Slides links as files")
    ln.add_argument("urls", nargs="+")
    ln.add_argument("--dest", type=Path, required=True, help="folder to save into")
    ln.add_argument("--format", action="append", default=[], metavar="KIND=FMT or FMT", help="e.g. pdf, or document=pdf")
    ln.add_argument("--json", action="store_true")

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return run.EXIT_USAGE
    try:
        if args.cmd == "scan":
            return _scan(args)
        if args.cmd == "copy":
            return _copy(args)
        if args.cmd == "report":
            return _report(args)
        if args.cmd == "link":
            return _link(args)
    except run.RunError as e:
        print(f"gdocout: {e}", file=sys.stderr)
        return run.EXIT_USAGE
    except _UsageError as e:
        print(f"gdocout: {e}", file=sys.stderr)
        return run.EXIT_USAGE
    return run.EXIT_USAGE


class _UsageError(Exception):
    pass


def _formats(values: List[str], allow_bare: bool = False) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for v in values:
        if "=" not in v:
            if not allow_bare:
                raise _UsageError(f"--format wants KIND=FMT, e.g. document=pdf (got {v!r})")
            for k in google.KINDS.values():
                if v in k.exports:
                    out[k.name] = v
            if not any(v in k.exports for k in google.KINDS.values()):
                raise _UsageError(f"no Google file type downloads as {v!r}")
            continue
        kind, fmt = (x.strip().lower() for x in v.split("=", 1))
        k = google.KINDS.get(kind)
        if not k or not k.exports:
            raise _UsageError(f"unknown kind {kind!r}; use one of {', '.join(n for n, x in google.KINDS.items() if x.exports)}")
        if fmt not in k.exports:
            raise _UsageError(f"{k.label} can't be downloaded as {fmt!r}; choose one of {', '.join(k.exports)}")
        out[kind] = fmt
    return out


def _scan(args) -> int:
    s = run.scan(args.source, args.flat, _formats(args.format))
    if args.json:
        print(json.dumps(s, indent=2, ensure_ascii=False))
        return 0
    print(f"{s['source']}: {s['files']} files in {s['folders']} folders")
    print(f"  {s['to_copy']} ordinary files to copy ({run._size(s['to_copy_bytes'])})")
    kinds = ", ".join(f"{n} {google.KINDS[k].label}" for k, n in sorted(s["google_by_kind"].items()))
    print(f"  {s['to_export']} Google files to download" + (f" (all Google files: {kinds})" if kinds else ""))
    print(f"  {s['estimate_note']}")
    for st, a in s["attention"].items():
        print(f"  {a['count']} {a['label'].lower()}: " + ", ".join(a["examples"][:3]) + (" …" if a["count"] > 3 else ""))
    if s["renamed"]:
        print(f"  {s['renamed']} would be renamed to avoid a clash")
    return 0


def _copy(args) -> int:
    opts = run.Options(
        source=args.source, dest=args.dest, flat=args.flat, formats=_formats(args.format),
        limit=args.limit, google_only=args.google_only, recheck=args.recheck, links=not args.no_links,
        max_workers=max(1, min(args.max_workers, 16)),
    )
    res = run.copy_library(opts)
    s = res.summary
    if args.json:
        print(json.dumps(s, indent=2, ensure_ascii=False))
    else:
        _print_summary(s)
    return res.code


def _print_summary(s: Dict[str, object]) -> None:
    counts = s["counts"]
    print()
    print("Done." if s["finished"] else ("Stopped. " + s["stopped"] if s["stopped"] else "Not finished yet: run the same command again to continue."))
    for st, label in LABELS.items():
        if counts.get(st):
            print(f"  {counts[st]:>6}  {label}")
    for st, a in s["attention"].items():
        print(f"\n{a['label']} ({a['count']}):")
        for p in a["examples"]:
            print(f"  {p}")
        if a["count"] > len(a["examples"]):
            print(f"  … and {a['count'] - len(a['examples'])} more in the report")
    print(f"\nReport: {s['report']}")


def _report(args) -> int:
    dest = args.dest.expanduser().resolve()
    db = dest / STATE_DIR / "state.db"
    if not db.exists():
        raise run.RunError(f"{args.dest} has no gdocout run in it.")
    st = State(db)
    try:
        entries = list(st.load().values())
        summary = json.loads(st.get("summary") or "{}")
    finally:
        st.close()
    out = report.write(dest / REPORT_NAME, entries, summary)
    print(json.dumps({"report": str(out), "files": len(entries)}) if args.json else f"Report: {out}")
    return 0


def _link(args) -> int:
    formats = _formats(args.format, allow_bare=True)
    dest = args.dest.expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    http = fetch.Http()
    results, code = [], 0
    for url in args.urls:
        res = _one_link(http, url, dest, formats)
        results.append(res)
        if res["status"] != CONVERTED:
            code = 1
    if args.json:
        print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"{LABELS.get(r['status'], r['status'])}: {r['url']}" + (f" → {r['file']}" if r.get("file") else "") + (f"  ({r['note']})" if r.get("note") else ""))
    return code


def _one_link(http: fetch.Http, url: str, dest: Path, formats: Dict[str, str]) -> Dict[str, object]:
    parsed = google.parse_link(url)
    if not parsed:
        return {"url": url, "status": "failed", "note": "not a Google Docs, Sheets, Slides, Drawings or My Maps link"}
    kind_name, gid, key = parsed
    kinds = [kind_name] if kind_name else ["document", "spreadsheet", "presentation"]
    last: Dict[str, object] = {}
    for kn in kinds:
        kind = google.KINDS[kn]
        if not kind.exports:
            return {"url": url, "status": "no_offline_format", "note": kind.why_none}
        fmt = formats.get(kn) or kind.default
        tmp_name = f"{gid}.{fmt}"
        e = Entry(rel=tmp_name, kind=kn, ext="", gid=gid, key=key, fmt=fmt)
        out = fetch.export(http, e, dest / (tmp_name + ".download"))
        if out.status == CONVERTED:
            final = _free_name(dest, out.filename or tmp_name, fmt)
            (dest / (tmp_name + ".download")).replace(final)
            return {"url": url, "status": CONVERTED, "kind": kind.label, "file": str(final), "facts": out.facts, "warnings": out.warnings}
        last = {"url": url, "status": out.status or "failed", "note": out.note}
        if kind_name or out.status not in ("not_found",):
            return last
    return last


def _free_name(dest: Path, name: str, fmt: str) -> Path:
    name = name.replace("/", "_").replace("\\", "_").strip() or f"download.{fmt}"
    if not name.lower().endswith("." + fmt):
        name += "." + fmt
    base, ext = name[: -len(fmt) - 1], "." + fmt
    cand, n = dest / name, 2
    while cand.exists():
        cand, n = dest / f"{base} ({n}){ext}", n + 1
    return cand


if __name__ == "__main__":
    sys.exit(main())
