"""Stage 1: walk the source folder offline and decide what happens to every file.

Nothing here touches the network. Placeholders (files a sync app hasn't
downloaded) are detected from file flags and never opened, because reading one
makes the sync app try to download it, which hangs or fails without a sign-in.
"""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from . import google
from .model import CONVERTED, IGNORED, NO_FORMAT, NOT_ON_DISK, PENDING, UNREADABLE, Entry

SF_DATALESS = 0x40000000  # macOS: contents live in the cloud only
WIN_PLACEHOLDER = 0x400000 | 0x40000 | 0x1000  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE

JUNK_FILES = {".ds_store", "desktop.ini", "thumbs.db", "icon\r", ".localized", ".gdocout-partial"}
JUNK_DIRS = {".tmp.drivedownload", ".tmp.driveupload", ".gdocout", ".trash", ".trashes", "$recycle.bin"}
MAYBE_STUB = re.compile(r"^\.g[a-z]{2,8}$")

REPORT_NAME = "gdocout-report.html"
STATE_DIR = ".gdocout"
RESERVED_ROOT = {REPORT_NAME, STATE_DIR}


@dataclass
class Inventory:
    entries: List[Entry] = field(default_factory=list)
    dirs: List[str] = field(default_factory=list)  # every folder, "/"-separated, for mirroring


def norm(name: str) -> str:
    """Compare names the way a case-insensitive file system does, NFC first (macOS hands out NFD)."""
    return unicodedata.normalize("NFC", name).casefold()


def is_placeholder(st: os.stat_result) -> bool:
    if getattr(st, "st_flags", 0) & SF_DATALESS:
        return True
    if getattr(st, "st_file_attributes", 0) & WIN_PLACEHOLDER:
        return True
    return False


def split_ext(name: str) -> Tuple[str, str]:
    base, ext = os.path.splitext(name)
    if not base:  # ".bashrc"
        return name, ""
    return base, ext


def walk(source: Path) -> Inventory:
    inv = Inventory()
    errors: List[Tuple[str, str]] = []

    def onerror(e: OSError):
        rel = Path(e.filename).relative_to(source).as_posix() if e.filename else "?"
        errors.append((rel, e.strerror or str(e)))

    for root, dirnames, filenames in os.walk(source, onerror=onerror, followlinks=False):
        rootp = Path(root)
        rel_root = rootp.relative_to(source).as_posix()
        rel_root = "" if rel_root == "." else rel_root
        keep = []
        for d in sorted(dirnames):
            rel = f"{rel_root}/{d}" if rel_root else d
            if d.lower() in JUNK_DIRS:
                continue
            if (rootp / d).is_symlink():
                inv.entries.append(Entry(rel, "file", "", status=IGNORED, note="a link to another folder; not followed"))
                continue
            keep.append(d)
            inv.dirs.append(rel)
        dirnames[:] = keep
        for name in sorted(filenames):
            rel = f"{rel_root}/{name}" if rel_root else name
            inv.entries.append(classify(rootp / name, rel, name))
    for rel, why in errors:
        inv.entries.append(Entry(rel, "file", "", status=UNREADABLE, note=f"couldn't open this folder ({why})"))
    return inv


def classify(path: Path, rel: str, name: str) -> Entry:
    base, ext = split_ext(name)
    ext_l = ext.lower()
    e = Entry(rel, "file", ext_l)
    try:
        st = os.lstat(path)
    except OSError as err:
        e.status, e.note = UNREADABLE, f"couldn't read it ({err.strerror})"
        return e
    e.size, e.mtime = st.st_size, st.st_mtime
    if stat.S_ISLNK(st.st_mode):
        e.status, e.note = IGNORED, "a link to another file; not followed"
        return e
    if not stat.S_ISREG(st.st_mode):
        e.status, e.note = IGNORED, "not an ordinary file"
        return e
    if name.lower() in JUNK_FILES or name.startswith("~$") or (name.startswith(".~lock.") and name.endswith("#")):
        e.status, e.note = IGNORED, "kept by the operating system or an app for itself"
        return e
    kind_name = google.STUB_EXTENSIONS.get(ext_l)
    could_be_stub = kind_name is not None or (MAYBE_STUB.match(ext_l) and st.st_size <= google.STUB_MAX_BYTES)
    if is_placeholder(st):
        e.status = NOT_ON_DISK
        if kind_name:
            e.kind = kind_name
        e.note = "only a placeholder is on this computer"
        return e
    if not could_be_stub:
        return e
    try:
        with open(path, "rb") as f:
            data = f.read(google.STUB_MAX_BYTES + 1)
    except OSError as err:
        e.status, e.note = UNREADABLE, f"couldn't read it ({err.strerror})"
        return e
    if kind_name is None and not data.lstrip().startswith(b"{"):
        return e  # an ordinary file that happens to have a .gXX extension (.gz, .gpx)
    try:
        e.gid, e.key, e.account = google.parse_stub(data)
    except google.StubError as err:
        if kind_name is None:
            return e
        e.kind = kind_name
        e.status, e.note = UNREADABLE, str(err)
        return e
    e.kind = kind_name or "unknown"
    kind = google.KINDS[e.kind]
    if not kind.default:
        e.status, e.note = NO_FORMAT, kind.why_none
    return e


def google_base(e: Entry) -> str:
    """The name a Google file's copy is built from: "Report.docx.gdoc" -> "Report"."""
    kind = google.KINDS[e.kind]
    stub_base, _ = split_ext(e.name)
    base, inner = split_ext(stub_base)
    return base if inner.lower() in kind.family else stub_base


def wanted_formats(kind: google.Kind, formats: Dict[str, List[str]]) -> List[str]:
    """The formats to save a kind in, main one first: what was asked for, or the default."""
    out: List[str] = []
    for f in formats.get(kind.name) or []:
        if f in kind.exports and f not in out:
            out.append(f)
    return out or ([kind.default] if kind.default else [])


def apply_pdf(formats: Dict[str, List[str]], mode: str) -> Dict[str, List[str]]:
    """--pdf also / only: add a PDF of every Google Doc, Sheet, Slides file and Drawing, or save only PDFs."""
    out = {k: list(v) for k, v in formats.items()}
    if mode not in ("also", "only"):
        return out
    for name in ("document", "spreadsheet", "presentation", "drawing"):
        kind = google.KINDS[name]
        if mode == "only":
            out[name] = ["pdf"]
        else:
            current = wanted_formats(kind, out)
            out[name] = current + ([] if "pdf" in current else ["pdf"])
    return out


def allocate(
    entries: Iterable[Entry],
    dirs: Iterable[str],
    flat: bool,
    formats: Dict[str, List[str]],
    taken_before: Iterable[str] = (),
) -> None:
    """Give every file a copy will produce a destination path.

    Deterministic, so a resumed run gets the same names. Paths handed out in an
    earlier run (taken_before) keep their owners. Ordinary files claim their names
    first, then each Google file's main format, then any extra formats; a Google
    file's copy that collides gets "(from Google Docs)" added, and anything still
    colliding gets " (2)", " (3)"...
    """
    taken: Dict[str, Set[str]] = {}
    entries = list(entries)

    def group(parent: str) -> Set[str]:
        return taken.setdefault("" if flat else norm(parent), set())

    group("").update(norm(n) for n in RESERVED_ROOT)
    if not flat:
        for d in dirs:
            parent, _, leaf = d.rpartition("/")
            group(parent).add(norm(leaf))
    for rel in taken_before:
        parent, _, leaf = rel.rpartition("/")
        group(parent).add(norm(leaf))

    def claim(e: Entry, candidates: List[str], base: str, ext: str) -> str:
        names = group(e.parent)
        chosen = next((c for c in candidates if norm(c) not in names), None)
        n = 2
        while chosen is None:
            c = f"{base} ({n}){ext}"
            if norm(c) not in names:
                chosen = c
            n += 1
        names.add(norm(chosen))
        return chosen if flat or not e.parent else f"{e.parent}/{chosen}"

    todo = [e for e in entries if e.status == PENDING and not e.out_rel]
    todo.sort(key=lambda e: (e.is_google, e.rel))
    for e in todo:
        if e.is_google:
            kind = google.KINDS[e.kind]
            e.fmt = (wanted_formats(kind, formats) or [""])[0]
            base, ext = google_base(e), "." + e.fmt
            candidates = [base + ext, f"{base} (from {kind.label}){ext}"]
        else:
            base, ext = split_ext(e.name)
            candidates = [e.name]
        e.out_rel = claim(e, candidates, base, ext)
        e.renamed = e.out_rel.rsplit("/", 1)[-1] != candidates[0]

    for e in sorted((e for e in entries if e.is_google and e.out_rel and e.status in (PENDING, CONVERTED)), key=lambda e: e.rel):
        kind = google.KINDS[e.kind]
        for f in wanted_formats(kind, formats):
            if f == e.fmt or f in e.extra:
                continue
            base, ext = google_base(e), "." + f
            e.extra[f] = {"o": claim(e, [base + ext, f"{base} (from {kind.label}){ext}"], base, ext), "st": PENDING}


def summary(entries: Iterable[Entry]) -> Dict[str, object]:
    from collections import Counter

    entries = list(entries)
    by_status = Counter(e.status for e in entries)
    google_kinds = Counter(e.kind for e in entries if e.is_google)
    to_copy = [e for e in entries if not e.is_google and e.status == PENDING]
    to_export = [e for e in entries if e.is_google and e.status == PENDING]
    return {
        "files": len(entries),
        "by_status": dict(by_status),
        "google_by_kind": dict(google_kinds),
        "to_copy": len(to_copy),
        "to_copy_bytes": sum(e.size for e in to_copy),
        "to_export": len(to_export),
    }
