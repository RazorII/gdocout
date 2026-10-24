"""gdocout: turn Google Docs, Sheets and Slides into files you can open offline, without signing in."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__, browser, fetch, google, inventory, report, run, validate
from .inventory import REPORT_NAME, STATE_DIR
from .model import CONVERTED, LABELS, Entry
from .selection import Selection, parse_types, read_list
from .state import State

FORMAT_HELP = (
    "formats for one kind of Google file, main one first, e.g. --format document=docx,pdf. "
    "Kinds and formats: "
    + "; ".join(f"{k.name}={'|'.join(k.exports)}" for k in google.KINDS.values() if k.exports)
    + ". Defaults: Word, Excel, PowerPoint, PDF for drawings, KMZ for maps."
)
TYPES_HELP = (
    "comma-separated: a category (documents, spreadsheets, presentations, pdf, images, video, audio, archives, text, "
    "ebooks, mapfiles, other), a Google type (google, google-docs, google-sheets, google-slides, google-drawings, "
    "google-maps, google-forms) or an extension (.heic). Repeatable."
)


class UsageError(Exception):
    pass


def add_choice_options(p: argparse.ArgumentParser) -> None:
    """The options that decide what a copy contains, shared by scan, copy and the GUI."""
    p.add_argument("--flat", action="store_true", help="put every file in one folder instead of keeping the folder structure")
    p.add_argument("--format", action="append", default=[], metavar="KIND=FMT[,FMT]", help=FORMAT_HELP)
    p.add_argument("--pdf", choices=["also", "only"], help="also save a PDF of every Google Doc, Sheet, Slides file and Drawing, or save only PDFs")
    p.add_argument("--only", action="append", default=[], metavar="TYPES", help="copy only these types. " + TYPES_HELP)
    p.add_argument("--skip", action="append", default=[], metavar="TYPES", help="leave these types out. " + TYPES_HELP)
    p.add_argument("--include", action="append", default=[], metavar="PATTERN",
                   help="only files or folders matching this pattern, e.g. 'Work/' or '*budget*' (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                   help="leave out files or folders matching this pattern, e.g. 'Photos/' or '*.tmp' (repeatable)")
    p.add_argument("--files-from", type=Path, metavar="LIST", help="only the paths in this file, one per line, relative to the source; a folder takes everything in it")
    p.add_argument("--no-copy", "--google-only", dest="no_copy", action="store_true", help="don't copy ordinary files this run")
    p.add_argument("--no-convert", action="store_true", help="don't download Google files this run")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gdocout",
        description="Turn Google Docs, Sheets and Slides into Word, Excel and PowerPoint files without signing in, "
        "and copy everything else. Works on files shared 'anyone with the link': one link at a time, or a whole "
        "Google Drive saved offline.",
    )
    p.add_argument("--version", action="version", version=f"gdocout {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    s = sub.add_parser("scan", help="look through a folder and say what a copy would do (offline, writes nothing)")
    s.add_argument("source", type=Path)
    add_choice_options(s)
    s.add_argument("--json", action="store_true")

    c = sub.add_parser("copy", help="copy a folder, converting every Google file it can; resumable")
    c.add_argument("source", type=Path, help="the offline Google Drive folder")
    c.add_argument("--dest", type=Path, required=True, help="where the copy goes: an empty folder, or one gdocout copied into before (to continue)")
    add_choice_options(c)
    c.add_argument("--limit", type=int, metavar="N", help="download at most N Google files this run (a sample, to check sharing first)")
    c.add_argument("--recheck", action="store_true", help="ask Google again about files it refused before (after an owner changed sharing)")
    c.add_argument("--no-links", action="store_true", help="don't leave a link page where a Google file couldn't be saved")
    c.add_argument("--fetch-placeholders", action="store_true", help="ask Google Drive to download files that are only placeholders on this computer (Drive must be running and signed in)")
    c.add_argument("--browser", nargs="?", const="default", choices=["default", *browser.BROWSERS], help="for files that aren't shared by link: download them through your web browser, signed in to Google with an account that can open them (recommended: the account Google Drive uses). Optionally name the browser")
    c.add_argument("--downloads", type=Path, metavar="DIR", help="where that browser saves downloads (found automatically)")
    c.add_argument("--max-workers", type=int, default=8, metavar="N", help="most downloads at once (default 8; gdocout starts lower and works up)")
    c.add_argument("--json", action="store_true", help="print the summary as JSON")

    r = sub.add_parser("report", help="rebuild the HTML report of an earlier copy")
    r.add_argument("dest", type=Path)
    r.add_argument("--json", action="store_true")

    ln = sub.add_parser("link", help="download Google Docs/Sheets/Slides links as files")
    ln.add_argument("urls", nargs="+")
    ln.add_argument("--dest", type=Path, required=True, help="folder to save into")
    ln.add_argument("--format", action="append", default=[], metavar="FMT[,FMT] or KIND=FMT[,FMT]", help="e.g. pdf, docx,pdf or document=pdf")
    ln.add_argument("--pdf", choices=["also", "only"], help="also save a PDF, or only a PDF")
    ln.add_argument("--browser", nargs="?", const="default", choices=["default", *browser.BROWSERS], help="for files that aren't shared by link: download them through your web browser, signed in to Google with an account that can open them (recommended: the account Google Drive uses). Optionally name the browser")
    ln.add_argument("--account", metavar="EMAIL", default="", help="with --browser: the Google account in the browser that can open the files")
    ln.add_argument("--downloads", type=Path, metavar="DIR", help="where that browser saves downloads (found automatically)")
    ln.add_argument("--json", action="store_true")

    g = sub.add_parser("gui", help="open a window in your web browser with every option")
    g.add_argument("--port", type=int, default=0, help="local port (default: any free one)")
    g.add_argument("--no-browser", action="store_true", help="print the address instead of opening the browser")
    g.add_argument("--source", type=Path, help="open with this folder already chosen (and looked through)")
    g.add_argument("--dest", type=Path, help="open with this destination already chosen")
    g.add_argument("--no-native-picker", action="store_true", help="choose folders inside the page instead of the system's folder dialog")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    p = build_parser()
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
        if args.cmd == "gui":
            from . import gui

            return gui.serve(port=args.port, open_browser=not args.no_browser, source=args.source, dest=args.dest,
                             native_picker=not args.no_native_picker)
    except (run.RunError, UsageError) as e:
        print(f"gdocout: {e}", file=sys.stderr)
        return run.EXIT_USAGE
    return run.EXIT_USAGE


KIND_ALIASES = {"docs": "document", "doc": "document", "sheets": "spreadsheet", "slides": "presentation",
                "drawings": "drawing", "maps": "map"}


def parse_formats(values: List[str], pdf: Optional[str] = None, allow_bare: bool = False) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for v in values:
        if "=" not in v:
            if not allow_bare:
                raise UsageError(f"--format wants KIND=FMT, e.g. document=pdf (got {v!r})")
            fmts = [f.strip().lower() for f in v.split(",") if f.strip()]
            matched = False
            for k in google.KINDS.values():
                mine = [f for f in fmts if f in k.exports]
                if mine:
                    out[k.name] = mine
                    matched = True
            if not matched:
                raise UsageError(f"no Google file type downloads as {v!r}")
            continue
        kind, fmts_s = (x.strip().lower() for x in v.split("=", 1))
        kind = KIND_ALIASES.get(kind, kind)
        k = google.KINDS.get(kind)
        if not k or not k.exports:
            raise UsageError(f"unknown kind {kind!r}; use one of {', '.join(n for n, x in google.KINDS.items() if x.exports)}")
        fmts = [f.strip().lower().lstrip(".") for f in fmts_s.split(",") if f.strip()]
        bad = [f for f in fmts if f not in k.exports]
        if bad or not fmts:
            raise UsageError(f"{k.label} can't be downloaded as {', '.join(bad) or 'nothing'}; choose from {', '.join(k.exports)}")
        out[kind] = fmts
    return inventory.apply_pdf(out, pdf) if pdf else out


def selection_from_args(args) -> Selection:
    try:
        sel = Selection(
            only=parse_types(args.only), skip=parse_types(args.skip),
            include=[x for x in args.include if x.strip()], exclude=[x for x in args.exclude if x.strip()],
            copy=not args.no_copy, convert=not args.no_convert,
        )
    except ValueError as e:
        raise UsageError(str(e)) from None
    if args.files_from:
        try:
            sel.files = read_list(args.files_from)
        except OSError as e:
            raise UsageError(f"couldn't read {args.files_from}: {e.strerror}") from None
    return sel


def options_from_args(args) -> run.Options:
    return run.Options(
        source=args.source, dest=args.dest, flat=args.flat,
        formats=parse_formats(args.format, args.pdf), selection=selection_from_args(args),
        limit=args.limit, recheck=args.recheck, links=not args.no_links,
        fetch_placeholders=args.fetch_placeholders, browser=args.browser, downloads=args.downloads,
        max_workers=max(1, min(args.max_workers, 16)),
    )


def _scan(args) -> int:
    s = run.scan(args.source, args.flat, parse_formats(args.format, args.pdf), selection_from_args(args))
    if args.json:
        print(json.dumps(s, indent=2, ensure_ascii=False))
        return 0
    print(f"{s['source']}: {s['files']} files in {s['folders']} folders ({s['layout']}; {s['selection']})")
    print(f"  {s['to_copy']} ordinary files to copy ({run._size(s['to_copy_bytes'])})")
    kinds = ", ".join(f"{n} {google.KINDS[k].label}" for k, n in sorted(s["google_by_kind"].items()))
    print(f"  {s['to_export']} Google files to download" + (f" (+{s['extra_downloads']} extra formats)" if s["extra_downloads"] else "")
          + (f" (all Google files: {kinds})" if kinds else ""))
    if s["by_status"].get("skipped"):
        print(f"  {s['by_status']['skipped']} left out by the rules chosen")
    print(f"  {s['estimate_note']}")
    for st, a in s["attention"].items():
        print(f"  {a['count']} {a['label'].lower()}: " + ", ".join(a["examples"][:3]) + (" …" if a["count"] > 3 else ""))
    if s["renamed"]:
        print(f"  {s['renamed']} would be renamed to avoid a clash")
    return 0


def _copy(args) -> int:
    res = run.copy_library(options_from_args(args))
    s = res.summary
    if args.json:
        print(json.dumps(s, indent=2, ensure_ascii=False))
    else:
        print_summary(s)
    return res.code


def print_summary(s: Dict[str, object]) -> None:
    counts = s["counts"]
    print()
    print("Done." if s["finished"] else ("Stopped. " + s["stopped"] if s["stopped"] else "Not finished yet: run the same command again to continue."))
    for st, label in LABELS.items():
        if counts.get(st):
            print(f"  {counts[st]:>6}  {label}")
    extra = s.get("extra_formats") or {}
    if extra:
        print("  extra formats: " + ", ".join(f"{n} {LABELS.get(k, k).lower()}" for k, n in extra.items()))
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
    formats = parse_formats(args.format, args.pdf, allow_bare=True)
    dest = args.dest.expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    http = fetch.Http()
    results, code = [], 0
    for url in args.urls:
        for res in _one_link(http, url, dest, formats, args):
            results.append(res)
            if res["status"] != CONVERTED:
                code = 1
    if args.json:
        print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"{LABELS.get(r['status'], r['status'])}: {r['url']}" + (f" → {r['file']}" if r.get("file") else "") + (f"  ({r['note']})" if r.get("note") else ""))
    return code


def _one_link(http: fetch.Http, url: str, dest: Path, formats: Dict[str, List[str]], args=None) -> List[Dict[str, object]]:
    parsed = google.parse_link(url)
    if not parsed:
        return [{"url": url, "status": "failed", "note": "not a Google Docs, Sheets, Slides, Drawings or My Maps link"}]
    kind_name, gid, key = parsed
    kinds = [kind_name] if kind_name else ["document", "spreadsheet", "presentation"]
    last: List[Dict[str, object]] = []
    for kn in kinds:
        kind = google.KINDS[kn]
        if not kind.exports:
            return [{"url": url, "status": "no_offline_format", "note": kind.why_none}]
        out_list: List[Dict[str, object]] = []
        for fmt in inventory.wanted_formats(kind, formats):
            tmp_name = f"{gid}.{fmt}"
            e = Entry(rel=tmp_name, kind=kn, ext="", gid=gid, key=key, fmt=fmt)
            out = fetch.export(http, e, dest / (tmp_name + ".download"))
            if out.status == CONVERTED:
                final = _free_name(dest, out.filename or tmp_name, fmt)
                (dest / (tmp_name + ".download")).replace(final)
                out_list.append({"url": url, "status": CONVERTED, "kind": kind.label, "format": fmt, "file": str(final),
                                 "facts": out.facts, "warnings": out.warnings})
                continue
            if args is not None and getattr(args, "browser", None) and out.status in ("not_shared", "download_off"):
                got = _link_via_browser(kind, gid, key, fmt, dest, args)
                if got.get("status") == CONVERTED:
                    out_list.append({"url": url, "kind": kind.label, "format": fmt, **got})
                    continue
                out.note = f"{out.note} Your browser couldn't download it either: {got.get('note')}"
            out_list.append({"url": url, "status": out.status or "failed", "format": fmt, "note": out.note})
            break  # a refusal applies to every format
        if out_list and (kind_name or out_list[0]["status"] != "not_found"):
            return out_list
        last = out_list
    return last


def _link_via_browser(kind, gid: str, key: str, fmt: str, dest: Path, args) -> Dict[str, object]:
    folder = browser.downloads_folder(args.browser, args.downloads)
    url = google.as_account(google.export_url(kind, gid, fmt, key), args.account)
    before = browser.snapshot(folder)
    try:
        browser.open_url(url, args.browser)
    except browser.BrowserError as e:
        return {"status": "failed", "note": str(e)}
    got = browser.wait_for_download(folder, before, {"." + fmt}, timeout=60)
    if got is None:
        return {"status": "failed", "note": f"nothing arrived in {folder} within 60 s"}
    check = validate.check_file(got, fmt)
    if not check.ok:
        return {"status": "failed", "note": f"{got.name} isn't a valid .{fmt} ({check.problem})"}
    final = _free_name(dest, got.name, fmt)
    import shutil

    shutil.move(str(got), str(final))
    return {"status": CONVERTED, "file": str(final), "facts": check.facts, "warnings": check.warnings, "via": "browser"}


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
