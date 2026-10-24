"""Copy a whole offline Google Drive folder: inventory, copy, export, report.

Stages
1. Inventory (offline): every file gets a fate and a destination name; the
   selection rules (types, folders, names, a list) leave files out by choice.
2. Copy: ordinary files are streamed to the destination and checked by SHA-256.
3. Export: Google files are downloaded in their offline format(s), paced
   (pacing.py), validated (validate.py), and classified when Google refuses
   (fetch.py). Extra formats (a PDF next to the Word file) follow in a second
   pass, only for files whose main download worked.
4. Report: a self-contained HTML page with every file, plus a short summary.

The state file in DEST/.gdocout makes every stage resumable: a run that stops
(Ctrl-C, a closed laptop, Google saying no for too long, Stop in the GUI)
continues where it left off the next time the same command runs.
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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import __version__, fetch, google, inventory, report
from .inventory import REPORT_NAME, STATE_DIR
from .model import (
    CONVERTED, COPIED, DONE, DOWNLOAD_OFF, EXPLAIN, FAILED, IGNORED, LABELS, NO_FORMAT, NOT_ON_DISK, NOT_SHARED,
    PENDING, RECHECK, SKIPPED, SOURCE_GONE, UNREADABLE, Entry,
)
from .pacing import OK, THROTTLE, TRANSIENT, Pacer
from .selection import Selection, census
from .state import State

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_THROTTLED = 5
EXIT_INTERRUPTED = 130

ATTENTION = ["download_off", "not_shared", "not_found", "no_offline_format", "not_on_disk", "unreadable", "failed", "pending", "source_gone"]
EXPORTS_PER_MINUTE = 140  # measured 2026-10-24 end to end on 200 files, slow start included (8 at once peaks near 220)


class RunError(Exception):
    """A problem with the request itself (paths, permissions, a mismatched earlier run). Exit code 2."""


@dataclass
class Options:
    source: Path
    dest: Path
    flat: bool = False
    formats: Dict[str, List[str]] = field(default_factory=dict)  # kind -> formats, main one first
    selection: Selection = field(default_factory=Selection)
    limit: Optional[int] = None  # export at most this many Google files this run
    max_workers: int = 8
    start_workers: int = 2
    recheck: bool = False  # ask Google again about files that were refused before
    links: bool = True  # leave a small .html link page where a Google file couldn't be saved
    retries: int = 3
    retry_wait: float = 1.0  # scales the jittered wait before retrying a network error; tests use 0
    http: Optional[fetch.Http] = None
    pacer: Optional[Pacer] = None
    cancel: Optional[threading.Event] = None  # set it to stop the run cleanly (the GUI's Stop button)
    say: Callable[[str], None] = lambda m: print(m, file=sys.stderr, flush=True)
    progress: Optional[Callable[[Dict[str, object]], None]] = None  # live numbers, for the GUI
    progress_every: float = 0.0  # seconds between progress lines; 0 = 5 s on a terminal, 30 s otherwise


@dataclass
class RunResult:
    code: int
    summary: Dict[str, object]


def permission_help(path: Path) -> str:
    if sys.platform == "darwin":
        where = "Google Drive" if "CloudStorage" in str(path) else "this location"
        return (
            f"macOS isn't letting this app read {path}. In System Settings → Privacy & Security, allow the app that runs "
            f"gdocout (Terminal, Claude, …) to read {where}: under Files and Folders, or with Full Disk Access. "
            "Then quit and reopen that app and try again."
        )
    if os.name == "nt":
        return f"Windows refused access to {path}. Check that your account can open that folder, then try again."
    return f"Permission denied for {path}. Check that your account can read that folder, then try again."


def _readable_dir(path: Path, what: str) -> None:
    try:
        next(os.scandir(path), None)
    except PermissionError:
        raise RunError(permission_help(path)) from None
    except FileNotFoundError:
        raise RunError(f"{path} doesn't exist.") from None
    except NotADirectoryError:
        raise RunError(f"{path} isn't a folder.") from None


def check_paths(source: Path, dest: Path) -> Tuple[Path, Path]:
    src = source.expanduser().resolve()
    dst = dest.expanduser().resolve()
    if not src.is_dir():
        raise RunError(f"{source} isn't a folder.")
    _readable_dir(src, "source")
    if dst == src or src in dst.parents:
        raise RunError("The destination can't be inside the folder being copied. Choose a folder somewhere else.")
    if dst in src.parents:
        raise RunError("The destination can't contain the folder being copied. Choose a separate, empty folder.")
    if dst.exists() and not dst.is_dir():
        raise RunError(f"{dest} exists and isn't a folder.")
    state_db = dst / STATE_DIR / "state.db"
    if dst.exists() and not state_db.exists():
        try:
            others = [p.name for p in dst.iterdir() if p.name not in (".DS_Store", "desktop.ini", "Thumbs.db")]
        except PermissionError:
            raise RunError(permission_help(dst)) from None
        if others:
            raise RunError(
                f"{dest} isn't empty. Choose an empty folder (gdocout creates it if it doesn't exist), "
                "or a folder gdocout copied into before, to continue that run."
            )
    return src, dst


def _apply_selection(entries, sel: Selection) -> None:
    """Leave files out by choice. Runs after names are handed out, so a file left out
    now keeps its name for the run that includes it later."""
    if not sel.active:
        return
    for e in entries:
        if e.status in (IGNORED, SOURCE_GONE) or e.status in DONE:
            continue
        why = sel.why_left_out(e)
        if why:
            e.status, e.note = SKIPPED, why[0].upper() + why[1:] + "."


def scan(source: Path, flat: bool = False, formats: Optional[Dict[str, List[str]]] = None,
         selection: Optional[Selection] = None) -> Dict[str, object]:
    src = source.expanduser().resolve()
    if not src.is_dir():
        raise RunError(f"{source} isn't a folder.")
    _readable_dir(src, "source")
    inv = inventory.walk(src)
    what_is_there = census(inv.entries)
    inventory.allocate(inv.entries, inv.dirs, flat, formats or {})
    _apply_selection(inv.entries, selection or Selection())
    s = inventory.summary(inv.entries)
    n = s["to_export"]
    extra = sum(1 for e in inv.entries if e.status == PENDING for _ in e.extra)
    minutes = (n + extra) / EXPORTS_PER_MINUTE
    s.update(
        version=__version__,
        source=str(src),
        folders=len(inv.dirs),
        layout="one folder" if flat else "folder structure kept",
        selection=(selection or Selection()).as_text(),
        extra_downloads=extra,
        renamed=sum(1 for e in inv.entries if e.renamed and e.status == PENDING),
        estimate_minutes=round(minutes, 1),
        estimate_note=(
            f"About {max(1, round(minutes))} min for {n + extra} Google downloads at the pace measured "
            "on 2026-10-24 (about 140 a minute including the slow start); longer for big files, "
            "or if Google slows this connection down."
        ) if n + extra else "No Google files to download.",
        attention=_attention(inv.entries, skip=(PENDING,)),
        labels={k: LABELS[k] for k in s["by_status"]},
        census=what_is_there,
    )
    return s


def copy_library(opts: Options) -> RunResult:
    src, dst = check_paths(opts.source, opts.dest)
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        raise RunError(permission_help(dst)) from None
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
        return _Run(opts, src, dst, state).go()
    finally:
        state.close()


class _Run:
    def __init__(self, opts: Options, src: Path, dst: Path, state: State):
        self.o, self.src, self.dst, self.state = opts, src, dst, state
        self.http = opts.http or fetch.Http()
        self.pacer = opts.pacer or Pacer(start=opts.start_workers, maximum=opts.max_workers)
        self.cancel = opts.cancel or threading.Event()
        self.counts: Counter = Counter()
        self.extra_counts: Counter = Counter()
        self.t0 = time.monotonic()
        self.export_seconds = 0.0
        self.exported = 0
        self.stopped = ""
        self.every = opts.progress_every or (5.0 if sys.stderr.isatty() else 30.0)
        self.live: Dict[str, object] = {"stage": "looking", "done": 0, "total": 0}

    def _progress(self, **kw) -> None:
        self.live.update(kw)
        self.live["workers"] = self.pacer.allowed
        self.live["paused"] = self.pacer.paused
        if self.o.progress:
            try:
                self.o.progress(dict(self.live))
            except Exception:
                pass

    # -- stages -------------------------------------------------------------
    def go(self) -> RunResult:
        o = self.o
        o.say(f"gdocout {__version__}: looking through {self.src} …")
        self._progress(stage="looking")
        self._sweep_partials()
        entries = self._inventory()
        self._mirror_folders()
        code = EXIT_OK
        try:
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
        if self.cancel.is_set() and not self.stopped:
            self.stopped = "Stopped from the window. Everything finished so far is saved; start it again to continue."
            code = EXIT_INTERRUPTED
        if self.pacer.stopped and self.pacer.stop_reason and not self.stopped:
            self.stopped = self.pacer.stop_reason
            code = EXIT_THROTTLED
        summary = self._summary(entries)
        fetch.unhide(report.write(self.dst / REPORT_NAME, list(entries.values()), summary))
        _write_manifest(self.dst / STATE_DIR, list(entries.values()), summary)
        self.state.set("summary", summary)
        self.state.commit()
        if code == EXIT_OK and summary["counts"].get(FAILED):
            code = EXIT_FAILED
        self._progress(stage="done", code=code)
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
            else:  # do it again, under the names it already had
                e.out_rel, e.fmt, e.renamed, e.link_rel = prev.out_rel, prev.fmt, prev.renamed, prev.link_rel
                e.extra = {f: {"o": x["o"], "st": PENDING} for f, x in prev.extra.items()}
                if prev.kind != e.kind:
                    e.out_rel, e.extra = "", {}
                merged[rel] = e
        for rel, prev in old.items():
            if rel not in new and prev.status != IGNORED:
                prev.status, prev.note = SOURCE_GONE, "It was in the folder during an earlier run, but isn't any more."
                merged[rel] = prev
        taken = [e.out_rel for e in merged.values() if e.out_rel]
        taken += [x["o"] for e in merged.values() for x in e.extra.values()]
        inventory.allocate(merged.values(), inv.dirs, self.o.flat, self.o.formats, taken_before=taken)
        _apply_selection(merged.values(), self.o.selection)
        self.dirs = inv.dirs
        self.state.save(merged.values())
        self.state.commit()
        s = inventory.summary(merged.values())
        extra = sum(1 for e in merged.values() for x in e.extra.values() if x.get("st") in (PENDING, FAILED))
        self.o.say(
            f"{s['files']} files: {s['to_copy']} to copy ({_size(s['to_copy_bytes'])}), "
            f"{s['to_export']} Google files to download" + (f" (+{extra} extra formats)" if extra else "") + ", "
            f"{sum(v for k, v in s['by_status'].items() if k in DONE)} done in an earlier run, "
            f"{s['by_status'].get(SKIPPED, 0)} left out by choice, "
            f"{sum(v for k, v in s['by_status'].items() if k not in DONE and k not in (PENDING, SKIPPED))} set aside "
            "(system files, types with no offline format, placeholders, unreadable, or refused before)."
        )
        return merged

    def _mirror_folders(self) -> None:
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
            if self.cancel.is_set():
                break
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
            self._progress(stage="copying", done=i, total=len(todo), bytes_done=done_bytes, bytes_total=total_bytes)
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
            fetch.unhide(dst)
            e.status, e.out_size, e.note = COPIED, st.st_size, ""
            e.facts = {"sha256": digest}
        except _Mismatch:
            e.status, e.note = FAILED, "the copy's SHA-256 didn't match the original; it was not kept"
        except PermissionError as err:
            e.status, e.note = UNREADABLE, f"permission denied ({err.strerror}); " + permission_help(src).split(". ")[0]
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
        main = sorted((e for e in entries.values() if e.is_google and e.status == PENDING), key=lambda e: e.rel)
        if self.o.limit is not None:
            main = main[: self.o.limit]
        if main:
            self.o.say(f"Downloading {len(main)} Google files, starting with {self.pacer.allowed} at once …")
            self._download([(e, None) for e in main], "downloading")
        # Extra formats: only where the main download worked; a refusal applies to every format.
        extras: List[Tuple[Entry, str]] = []
        for e in sorted(entries.values(), key=lambda e: e.rel):
            for f, x in e.extra.items():
                if x.get("st") not in (PENDING, FAILED):
                    continue
                if e.status == CONVERTED:
                    extras.append((e, f))
                elif e.status in RECHECK or e.status in (NO_FORMAT, SKIPPED):
                    x["st"], x["n"] = e.status, "the main download was refused, so this format was too"
        if extras and not self.pacer.stopped and not self.cancel.is_set():
            self.o.say(f"Downloading {len(extras)} extra formats …")
            self._download(extras, "extra formats")

    def _download(self, items: List[Tuple[Entry, Optional[str]]], stage: str) -> None:
        work: "queue.Queue[Tuple[Entry, Optional[str]]]" = queue.Queue()
        results: "queue.Queue[tuple]" = queue.Queue()
        for it in items:
            work.put(it)
        finished = threading.Event()

        def worker():
            while not finished.is_set():
                try:
                    e, fmt = work.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self.cancel.is_set():
                    self.pacer.stop()
                started = self.pacer.acquire()
                if started is None:
                    work.put((e, fmt))
                    return
                target = e if fmt is None else replace(e, fmt=fmt)
                dest = self.dst / (e.out_rel if fmt is None else e.extra[fmt]["o"])
                t = time.monotonic()
                try:
                    out = fetch.export(self.http, target, dest)
                except OSError as err:
                    if err.errno == errno.ENOSPC:
                        out = fetch.Outcome(OK, FAILED, note="the destination ran out of space")
                    else:
                        out = fetch.Outcome(OK, FAILED, note=f"couldn't save it ({err.strerror or err})")
                except Exception as err:  # never lose a file's record to a surprise
                    out = fetch.Outcome(OK, FAILED, note=f"unexpected error: {err.__class__.__name__}: {err}")
                self.pacer.release(started, out.signal, out.retry_after)
                seconds = round(time.monotonic() - t, 3)
                if out.signal == THROTTLE:
                    work.put((e, fmt))
                    continue
                if out.signal == TRANSIENT:
                    e.attempts += 1
                    if e.attempts < self.o.retries:
                        time.sleep(self.o.retry_wait * random.uniform(1, min(30, 2 ** (e.attempts + 1))))
                        work.put((e, fmt))
                        continue
                    out = fetch.Outcome(OK, FAILED, note=f"gave up after {e.attempts} tries: {out.note}")
                results.put((e, fmt, out, seconds))

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(self.pacer.maximum)]
        for th in threads:
            th.start()
        handled, last, last_save, t0 = 0, time.monotonic(), time.monotonic(), time.monotonic()
        pending_save: List[Entry] = []
        try:
            while handled < len(items):
                if self.cancel.is_set():
                    self.pacer.stop()
                if self.pacer.stopped and all(not th.is_alive() for th in threads):
                    break
                try:
                    e, fmt, out, seconds = results.get(timeout=0.5)
                except queue.Empty:
                    out = None
                if out is not None:
                    handled += 1
                    if fmt is None:
                        e.status, e.note, e.seconds = out.status, out.note, seconds
                        e.facts, e.warnings = out.facts, out.warnings
                        e.out_size = out.out_size if out.status == CONVERTED else None
                        self.counts[e.status] += 1
                    else:
                        x = e.extra[fmt]
                        x.update(st=out.status, n=out.note, s=out.out_size if out.status == CONVERTED else None, f=out.facts)
                        if out.warnings:
                            x["w"] = out.warnings
                        self.extra_counts[out.status] += 1
                    pending_save.append(e)
                now = time.monotonic()
                if pending_save and (now - last_save > 3 or len(pending_save) >= 50):
                    self.state.save(pending_save)
                    self.state.commit()
                    pending_save, last_save = [], now
                rate = handled / max(1e-9, (now - t0) / 60)
                self._progress(stage=stage, done=handled, total=len(items), rate=round(rate))
                if now - last > self.every:
                    left = len(items) - handled
                    eta = f", about {max(1, round(left / rate))} min left" if rate > 0 and left else ""
                    state = " (paused: Google asked to slow down)" if self.pacer.paused else ""
                    self.o.say(f"{stage}: {handled}/{len(items)} · {rate:.0f} a minute · {self.pacer.allowed} at once{state}{eta}")
                    last = now
        finally:
            finished.set()
            for th in threads:
                th.join(timeout=10)
            if pending_save:
                self.state.save(pending_save)
                self.state.commit()
            self.exported += handled
            self.export_seconds += time.monotonic() - t0

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
        taken |= {inventory.norm(x["o"]) for e in entries.values() for x in e.extra.values()}
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
                if e.link_rel and e.status not in (PENDING, FAILED, SKIPPED):  # its fate changed; the page would mislead
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
                fetch.unhide(path)
            except OSError:
                e.link_rel = ""

    # -- summary ------------------------------------------------------------
    def _summary(self, entries: Dict[str, Entry]) -> Dict[str, object]:
        all_entries = list(entries.values())
        counts = Counter(e.status for e in all_entries)
        extras = Counter(x.get("st", PENDING) for e in all_entries for x in e.extra.values())
        st = self.pacer.stats
        rate = self.exported / (self.export_seconds / 60) if self.export_seconds > 1 else None
        return {
            "version": __version__,
            "source": str(self.src),
            "dest": str(self.dst),
            "report": str(self.dst / REPORT_NAME),
            "layout": "one folder" if self.o.flat else "folder structure kept",
            "formats": {k: inventory.wanted_formats(google.KINDS[k], self.o.formats)
                        for k in ("document", "spreadsheet", "presentation", "drawing", "map")},
            "selection": self.o.selection.as_text(),
            "finished": not self.stopped and not counts.get(PENDING) and not extras.get(PENDING),
            "stopped": self.stopped,
            "started": self.state.get("started"),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": len(all_entries),
            "counts": dict(counts),
            "extra_formats": dict(extras),
            "labels": {k: LABELS[k] for k in set(counts) | set(extras)},
            "this_run": {
                **{k: v for k, v in self.counts.items()},
                "extra_formats": dict(self.extra_counts),
                "seconds": round(time.monotonic() - self.t0, 1),
                "downloads_per_minute": round(rate) if rate else None,
                "most_at_once": st.peak_workers,
                "pauses": st.pauses,
                "paused_seconds": round(st.paused_seconds),
                "pace_events": st.events[-20:],
            },
            "google_by_kind": dict(Counter(e.kind for e in all_entries if e.is_google)),
            "bytes_written": sum(e.out_size or 0 for e in all_entries)
            + sum(x.get("s") or 0 for e in all_entries for x in e.extra.values()),
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
    failed_extra = sorted(f"{e.rel} (.{f})" for e in entries for f, x in e.extra.items() if x.get("st") == FAILED)
    if failed_extra:
        out["extra_failed"] = {"label": "Extra format failed", "count": len(failed_extra), "examples": failed_extra[:examples]}
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
