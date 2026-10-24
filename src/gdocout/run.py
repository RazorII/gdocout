"""Copy a whole offline Google Drive folder: inventory, copy, export, report.

Stages
1. Inventory (offline): every file gets a fate and a destination name.
2. Copy: ordinary files are streamed to the destination and checked by SHA-256.
3. Export: Google files are downloaded in their offline format, paced (pacing.py),
   validated (validate.py), and classified when Google refuses (fetch.py).
4. Report: a self-contained HTML page with every file, plus a short summary.

The state file in DEST/.gdocout makes every stage resumable: a run that stops
(Ctrl-C, a closed laptop, Google saying no for too long) continues where it left
off the next time the same command runs.
"""

from __future__ import annotations

import errno
import hashlib
import html
import json
import os
import queue
import random
import shutil
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import __version__, fetch, google, inventory, report
from .inventory import REPORT_NAME, STATE_DIR
from .model import (
    COPIED, DONE, DOWNLOAD_OFF, EXPLAIN, FAILED, IGNORED, LABELS, NO_FORMAT, NOT_ON_DISK, NOT_SHARED, PENDING,
    RECHECK, SOURCE_GONE, UNREADABLE, Entry,
)
from .pacing import OK, THROTTLE, TRANSIENT, Pacer
from .state import State

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_THROTTLED = 5
EXIT_INTERRUPTED = 130

ATTENTION = ["download_off", "not_shared", "not_found", "no_offline_format", "not_on_disk", "unreadable", "failed", "pending", "source_gone"]
EXPORTS_PER_MINUTE = 140  # measured 2026-10-24 end to end on 200 files, slow start included (8 at once peaks near 220)


class RunError(Exception):
    """A problem with the request itself (paths, a mismatched earlier run). Exit code 2."""


@dataclass
class Options:
    source: Path
    dest: Path
    flat: bool = False
    formats: Dict[str, str] = field(default_factory=dict)
    limit: Optional[int] = None  # export at most this many Google files this run
    google_only: bool = False  # skip copying ordinary files this run
    max_workers: int = 8
    start_workers: int = 2
    recheck: bool = False  # ask Google again about files that were refused before
    links: bool = True  # leave a small .html link page where a Google file couldn't be saved
    retries: int = 3
    retry_wait: float = 1.0  # scales the jittered wait before retrying a network error; tests use 0
    http: Optional[fetch.Http] = None
    pacer: Optional[Pacer] = None
    say: Callable[[str], None] = lambda m: print(m, file=sys.stderr, flush=True)
    progress_every: float = 0.0  # seconds between progress lines; 0 = 5 s on a terminal, 30 s otherwise


@dataclass
class RunResult:
    code: int
    summary: Dict[str, object]


def check_paths(source: Path, dest: Path) -> tuple:
    src = source.expanduser().resolve()
    dst = dest.expanduser().resolve()
    if not src.is_dir():
        raise RunError(f"{source} isn't a folder.")
    if dst == src or src in dst.parents:
        raise RunError("The destination can't be inside the folder being copied. Choose a folder somewhere else.")
    if dst in src.parents:
        raise RunError("The destination can't contain the folder being copied. Choose a separate, empty folder.")
    if dst.exists() and not dst.is_dir():
        raise RunError(f"{dest} exists and isn't a folder.")
    state_db = dst / STATE_DIR / "state.db"
    if dst.exists() and not state_db.exists():
        others = [p.name for p in dst.iterdir() if p.name not in (".DS_Store", "desktop.ini", "Thumbs.db")]
        if others:
            raise RunError(
                f"{dest} isn't empty. Choose an empty folder (gdocout creates it if it doesn't exist), "
                "or a folder gdocout copied into before, to continue that run."
            )
    return src, dst


def scan(source: Path, flat: bool = False, formats: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    src = source.expanduser().resolve()
    if not src.is_dir():
        raise RunError(f"{source} isn't a folder.")
    inv = inventory.walk(src)
    inventory.allocate(inv.entries, inv.dirs, flat, formats or {})
    s = inventory.summary(inv.entries)
    n = s["to_export"]
    s.update(
        version=__version__,
        source=str(src),
        folders=len(inv.dirs),
        renamed=sum(1 for e in inv.entries if e.renamed),
        estimate_minutes=round(n / EXPORTS_PER_MINUTE, 1) if n else 0,
        estimate_note=(
            f"About {max(1, round(n / EXPORTS_PER_MINUTE))} min for {n} Google files at the pace measured "
            "on 2026-10-24 (about 140 a minute including the slow start); longer for big files, "
            "or if Google slows this connection down."
        ) if n else "No Google files to download.",
        attention=_attention(inv.entries, skip=(PENDING,)),
        labels={k: LABELS[k] for k in s["by_status"]},
    )
    return s


def copy_library(opts: Options) -> RunResult:
    src, dst = check_paths(opts.source, opts.dest)
    dst.mkdir(parents=True, exist_ok=True)
    state = State(dst / STATE_DIR / "state.db")
    try:
        prev_source = state.get("source")
        if prev_source and prev_source != str(src):
            raise RunError(f"{opts.dest} holds a copy of a different folder ({prev_source}). Choose another destination.")
        prev_flat = state.get("flat")
        if prev_flat is not None and (prev_flat == "true") != opts.flat:
            raise RunError(
                f"{opts.dest} was started with {'all files in one folder' if prev_flat == 'true' else 'the folder structure kept'}. "
                "Continue it the same way, or choose a new destination."
            )
        state.set("source", str(src))
        state.set("flat", "true" if opts.flat else "false")
        state.set("version", __version__)
        if not state.get("started"):
            state.set("started", time.strftime("%Y-%m-%d %H:%M:%S"))

        run = _Run(opts, src, dst, state)
        return run.go()
    finally:
        state.close()


class _Run:
    def __init__(self, opts: Options, src: Path, dst: Path, state: State):
        self.o, self.src, self.dst, self.state = opts, src, dst, state
        self.http = opts.http or fetch.Http()
        self.pacer = opts.pacer or Pacer(start=opts.start_workers, maximum=opts.max_workers)
        self.counts: Counter = Counter()
        self.t0 = time.monotonic()
        self.export_seconds = 0.0
        self.exported = 0
        self.stopped = ""
        self.every = opts.progress_every or (5.0 if sys.stderr.isatty() else 30.0)

    # -- stages -------------------------------------------------------------
    def go(self) -> RunResult:
        o = self.o
        o.say(f"gdocout {__version__}: looking through {self.src} …")
        self._sweep_partials()
        entries = self._inventory()
        self._mirror_folders(entries)
        code = EXIT_OK
        try:
            if not o.google_only:
                self._copy_stage(entries)
            self._export_stage(entries)
        except KeyboardInterrupt:
            self.pacer.stop("interrupted")
            self.stopped = "Stopped by hand. Everything finished so far is saved; run the same command again to continue."
            code = EXIT_INTERRUPTED
        except _DiskFull as e:
            self.stopped = str(e)
            code = EXIT_FAILED
        finally:
            if o.links:
                self._write_links(entries)
            self.state.save(entries.values())
            self.state.set("finished" if not self.stopped else "stopped", time.strftime("%Y-%m-%d %H:%M:%S"))
            self.state.commit()
        if self.pacer.stopped and self.pacer.stop_reason and not self.stopped:
            self.stopped = self.pacer.stop_reason
            code = EXIT_THROTTLED
        summary = self._summary(entries)
        report.write(self.dst / REPORT_NAME, list(entries.values()), summary)
        _write_manifest(self.dst / STATE_DIR, list(entries.values()), summary)
        self.state.set("summary", summary)
        self.state.commit()
        if code == EXIT_OK and summary["counts"].get(FAILED):
            code = EXIT_FAILED
        return RunResult(code, summary)

    def _inventory(self) -> Dict[str, Entry]:
        inv = inventory.walk(self.src)
        old = self.state.load()
        new = {e.rel: e for e in inv.entries}
        merged: Dict[str, Entry] = {}
        for rel, e in new.items():
            prev = old.get(rel)
            if prev is None or not prev.out_rel:
                if prev is not None:
                    e.link_rel = prev.link_rel
                merged[rel] = e
                continue
            if e.status != PENDING:  # now a placeholder, unreadable, ignored, no format
                e.link_rel = prev.link_rel  # a link page left last time stays ours
                merged[rel] = e
                continue
            changed = (prev.size, prev.mtime, prev.gid) != (e.size, e.mtime, e.gid)
            keep = prev.status in DONE and not changed
            keep = keep or (prev.status in RECHECK and not self.o.recheck and not changed)
            if keep:
                merged[rel] = prev
            else:  # retry it, under the name it already had
                e.out_rel, e.fmt, e.renamed, e.link_rel = prev.out_rel, prev.fmt, prev.renamed, prev.link_rel
                if prev.kind != e.kind:
                    e.out_rel = ""
                merged[rel] = e
        for rel, prev in old.items():
            if rel not in new and prev.status != IGNORED:
                prev.status, prev.note = SOURCE_GONE, "It was in the folder during an earlier run, but isn't any more."
                merged[rel] = prev
        taken = [e.out_rel for e in merged.values() if e.out_rel]
        inventory.allocate(merged.values(), inv.dirs, self.o.flat, self.o.formats, taken_before=taken)
        self.dirs = inv.dirs
        self.state.save(merged.values())
        self.state.commit()
        s = inventory.summary(merged.values())
        self.o.say(
            f"{s['files']} files: {s['to_copy']} to copy ({_size(s['to_copy_bytes'])}), "
            f"{s['to_export']} Google files to download, "
            f"{sum(v for k, v in s['by_status'].items() if k in DONE)} done in an earlier run, "
            f"{sum(v for k, v in s['by_status'].items() if k not in DONE and k != PENDING)} set aside "
            "(system files, types with no offline format, placeholders, unreadable, or refused before)."
        )
        return merged

    def _mirror_folders(self, entries: Dict[str, Entry]) -> None:
        if self.o.flat:
            return
        for d in self.dirs:
            (self.dst / d).mkdir(parents=True, exist_ok=True)

    def _copy_stage(self, entries: Dict[str, Entry]) -> None:
        todo = sorted((e for e in entries.values() if not e.is_google and e.status == PENDING), key=lambda e: e.rel)
        if not todo:
            return
        total_bytes = sum(e.size for e in todo)
        self.o.say(f"Copying {len(todo)} files ({_size(total_bytes)}) …")
        done_bytes, last, last_save = 0, time.monotonic(), time.monotonic()
        for i, e in enumerate(todo, 1):
            t = time.monotonic()
            self._copy_one(e)
            e.seconds = round(time.monotonic() - t, 3)
            self.counts[e.status] += 1
            done_bytes += e.size
            now = time.monotonic()
            if now - last_save > 5:
                self.state.save(todo[max(0, i - 500):i])
                self.state.commit()
                last_save = now
            if now - last > self.every:
                self.o.say(f"copied {i}/{len(todo)} files, {_size(done_bytes)} of {_size(total_bytes)}")
                last = now
        self.state.save(todo)
        self.state.commit()

    def _copy_one(self, e: Entry) -> None:
        src = self.src / e.rel
        dst = self.dst / e.out_rel
        try:
            st = os.lstat(src)
        except FileNotFoundError:
            e.status, e.note = SOURCE_GONE, "It disappeared from the folder while gdocout was running."
            return
        except OSError as err:
            e.status, e.note = UNREADABLE, f"couldn't read it ({err.strerror})"
            return
        if inventory.is_placeholder(st):
            e.status, e.note = NOT_ON_DISK, "only a placeholder is on this computer"
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        part = dst.with_name(dst.name + fetch.PARTIAL)
        try:
            digest = _copy_hashed(src, part)
            if _sha256(part) != digest:
                raise _Mismatch()
            try:
                shutil.copystat(src, part)
            except OSError:
                pass
            os.replace(part, dst)
            e.status, e.out_size, e.note = COPIED, st.st_size, ""
            e.facts = {"sha256": digest}
        except _Mismatch:
            e.status, e.note = FAILED, "the copy's SHA-256 didn't match the original; it was not kept"
        except OSError as err:
            if err.errno == errno.ENOSPC:
                raise _DiskFull("The destination ran out of space. Free some up, then run the same command again to continue.")
            e.status, e.note = FAILED, f"couldn't copy it ({err.strerror or err})"
        finally:
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass

    def _export_stage(self, entries: Dict[str, Entry]) -> None:
        todo = sorted((e for e in entries.values() if e.is_google and e.status == PENDING), key=lambda e: e.rel)
        if self.o.limit is not None:
            todo = todo[: self.o.limit]
        if not todo:
            return
        self.o.say(f"Downloading {len(todo)} Google files, starting with {self.pacer.allowed} at once …")
        work: "queue.Queue[Entry]" = queue.Queue()
        results: "queue.Queue[tuple]" = queue.Queue()
        for e in todo:
            work.put(e)
        finished = threading.Event()

        def worker():
            while not finished.is_set():
                try:
                    e = work.get(timeout=0.2)
                except queue.Empty:
                    continue
                started = self.pacer.acquire()
                if started is None:
                    work.put(e)
                    return
                t = time.monotonic()
                try:
                    out = fetch.export(self.http, e, self.dst / e.out_rel)
                except OSError as err:
                    if err.errno == errno.ENOSPC:
                        out = fetch.Outcome(OK, FAILED, note="the destination ran out of space")
                    else:
                        out = fetch.Outcome(OK, FAILED, note=f"couldn't save it ({err.strerror or err})")
                except Exception as err:  # never lose a file's record to a surprise
                    out = fetch.Outcome(OK, FAILED, note=f"unexpected error: {err.__class__.__name__}: {err}")
                self.pacer.release(started, out.signal, out.retry_after)
                e.seconds = round(time.monotonic() - t, 3)
                if out.signal == THROTTLE:
                    work.put(e)
                    continue
                if out.signal == TRANSIENT:
                    e.attempts += 1
                    if e.attempts < self.o.retries:
                        time.sleep(self.o.retry_wait * random.uniform(1, min(30, 2 ** (e.attempts + 1))))
                        work.put(e)
                        continue
                    out = fetch.Outcome(OK, FAILED, note=f"gave up after {e.attempts} tries: {out.note}")
                results.put((e, out))

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(self.pacer.maximum)]
        for th in threads:
            th.start()
        handled, last, last_save, t0 = 0, time.monotonic(), time.monotonic(), time.monotonic()
        pending_save: List[Entry] = []
        try:
            while handled < len(todo):
                if self.pacer.stopped and all(not th.is_alive() for th in threads):
                    break
                try:
                    e, out = results.get(timeout=0.5)
                except queue.Empty:
                    out = None
                if out is not None:
                    handled += 1
                    e.status, e.note = out.status, out.note
                    e.facts, e.warnings, e.out_size = out.facts, out.warnings, out.out_size
                    if out.status != "converted":
                        e.out_size = None
                    self.counts[e.status] += 1
                    pending_save.append(e)
                now = time.monotonic()
                if pending_save and (now - last_save > 3 or len(pending_save) >= 50):
                    self.state.save(pending_save)
                    self.state.commit()
                    pending_save, last_save = [], now
                if now - last > self.every:
                    rate = handled / max(1e-9, (now - t0) / 60)
                    left = len(todo) - handled
                    eta = f", about {max(1, round(left / rate))} min left" if rate > 0 and left else ""
                    state = " (paused: Google asked to slow down)" if self.pacer.paused else ""
                    self.o.say(f"downloaded {handled}/{len(todo)} · {rate:.0f} a minute · {self.pacer.allowed} at once{state}{eta}")
                    last = now
        finally:
            finished.set()
            for th in threads:
                th.join(timeout=10)
            if pending_save:
                self.state.save(pending_save)
                self.state.commit()
            self.exported = handled
            self.export_seconds = time.monotonic() - t0

    def _sweep_partials(self) -> None:
        """Remove half-written files a crash left behind; finished files are never named like this."""
        for p in self.dst.rglob("*" + fetch.PARTIAL):
            try:
                p.unlink()
            except OSError:
                pass

    def _write_links(self, entries: Dict[str, Entry]) -> None:
        """Leave a small page, where the copy would have been, for each Google file that couldn't be saved.

        The copied folder then still shows the file, says why it's missing and links to it.
        A file that converts on a later run gets its link page removed.
        """
        taken = {inventory.norm(e.out_rel) for e in entries.values() if e.out_rel}
        taken |= {inventory.norm(e.link_rel) for e in entries.values() if e.link_rel}
        for e in sorted(entries.values(), key=lambda e: e.rel):
            if not e.is_google:
                continue
            if e.status in DONE and e.link_rel:
                try:
                    (self.dst / e.link_rel).unlink()
                except OSError:
                    pass
                e.link_rel = ""
                continue
            if e.status not in LINK_FOR or not e.gid:
                if e.link_rel and e.status not in (PENDING, FAILED):  # its fate changed; the page would mislead
                    try:
                        (self.dst / e.link_rel).unlink()
                    except OSError:
                        pass
                    e.link_rel = ""
                continue
            if not e.link_rel:
                kind = google.KINDS[e.kind]
                parent = "" if self.o.flat else e.parent
                base = inventory.google_base(e)
                n, name = 1, f"{base} ({kind.label} link).html"
                while True:
                    rel = f"{parent}/{name}" if parent else name
                    if inventory.norm(rel) not in taken and not (self.dst / rel).exists():
                        break
                    n += 1
                    name = f"{base} ({kind.label} link) ({n}).html"
                taken.add(inventory.norm(rel))
                e.link_rel = rel
            try:
                path = self.dst / e.link_rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_link_page(e), encoding="utf-8")
            except OSError:
                e.link_rel = ""

    # -- summary ------------------------------------------------------------
    def _summary(self, entries: Dict[str, Entry]) -> Dict[str, object]:
        all_entries = list(entries.values())
        counts = Counter(e.status for e in all_entries)
        st = self.pacer.stats
        rate = self.exported / (self.export_seconds / 60) if self.export_seconds > 1 else None
        return {
            "version": __version__,
            "source": str(self.src),
            "dest": str(self.dst),
            "report": str(self.dst / REPORT_NAME),
            "layout": "one folder" if self.o.flat else "folder structure kept",
            "finished": not self.stopped and not counts.get(PENDING),
            "stopped": self.stopped,
            "started": self.state.get("started"),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": len(all_entries),
            "counts": dict(counts),
            "labels": {k: LABELS[k] for k in counts},
            "this_run": {
                **{k: v for k, v in self.counts.items()},
                "seconds": round(time.monotonic() - self.t0, 1),
                "downloads_per_minute": round(rate) if rate else None,
                "most_at_once": st.peak_workers,
                "pauses": st.pauses,
                "paused_seconds": round(st.paused_seconds),
                "pace_events": st.events[-20:],
            },
            "google_by_kind": dict(Counter(e.kind for e in all_entries if e.is_google)),
            "bytes_written": sum(e.out_size or 0 for e in all_entries),
            "renamed": sum(1 for e in all_entries if e.renamed),
            "with_warnings": sum(1 for e in all_entries if e.warnings),
            "attention": _attention(all_entries),
        }


def _attention(entries: List[Entry], examples: int = 10, skip: tuple = ()) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for status in ATTENTION:
        if status in skip:
            continue
        hits = sorted((e for e in entries if e.status == status), key=lambda e: e.rel)
        if hits:
            out[status] = {
                "label": LABELS[status],
                "count": len(hits),
                "examples": [e.rel for e in hits[:examples]],
            }
    return out


LINK_FOR = {NO_FORMAT, DOWNLOAD_OFF, NOT_SHARED}


def _link_page(e: Entry) -> str:
    kind = google.KINDS[e.kind]
    url = google.open_url(e.gid, e.key)
    name = html.escape(inventory.google_base(e))
    why = html.escape(e.note or EXPLAIN.get(e.status, ""))
    return (
        "<!doctype html>\n<meta charset=\"utf-8\">\n"
        f"<title>{name} ({html.escape(kind.label)})</title>\n"
        "<style>body{font:16px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;max-width:38em;margin:3em auto;padding:0 1em}"
        "small{color:#777}</style>\n"
        f"<h1>{name}</h1>\n"
        f"<p>This {html.escape(kind.label)} file couldn't be saved here: <b>{html.escape(LABELS[e.status].lower())}</b>.</p>\n"
        f"<p>{why}</p>\n"
        f"<p><a href=\"{html.escape(url)}\">Open it in Google</a> (needs the internet).</p>\n"
        f"<p><small>Left by gdocout {__version__} on {time.strftime('%Y-%m-%d')}, in place of the original "
        f"{html.escape(e.name)}.</small></p>\n"
    )


def _write_manifest(state_dir: Path, entries: List[Entry], summary: Dict[str, object]) -> None:
    """Machine-readable copies of the report: one JSON line per file, and the summary."""
    from dataclasses import asdict

    tmp = state_dir / "files.jsonl.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in sorted(entries, key=lambda e: e.rel):
            row = asdict(e)
            if e.gid:
                row["google_link"] = google.open_url(e.gid, e.key)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, state_dir / "files.jsonl")
    (state_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


class _Mismatch(Exception):
    pass


class _DiskFull(Exception):
    pass


def _copy_hashed(src: Path, dst: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for block in iter(lambda: fi.read(chunk), b""):
            h.update(block)
            fo.write(block)
        fo.flush()
        os.fsync(fo.fileno())
    return h.hexdigest()


def _sha256(path: Path) -> str:
    from .validate import sha256

    return sha256(path)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"
