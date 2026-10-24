"""Which files a copy includes: type, folder and name rules, and an explicit list.

Types are written the same way everywhere (command line, GUI, Claude):

- a category: documents, spreadsheets, presentations, pdf, images, video, audio,
  archives, text, ebooks, mapfiles, other. Categories also cover the matching
  Google files: "documents" includes Google Docs, "spreadsheets" Google Sheets,
  "presentations" Google Slides.
- a Google type: google (all of them), google-docs, google-sheets, google-slides,
  google-drawings, google-maps, google-forms.
- an extension, with its dot: .pdf, .heic.

Patterns match the path inside the copied folder or just the file name, without
regard to case. "*" matches anything, including "/". A pattern ending in "/" is a
folder and everything in it: "Photos/" or "Work/Old/".
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Set

from .model import Entry

CATEGORIES: Dict[str, FrozenSet[str]] = {
    "documents": frozenset({".doc", ".docx", ".odt", ".rtf", ".pages", ".dotx", ".wpd", ".docm"}),
    "spreadsheets": frozenset({".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv", ".numbers"}),
    "presentations": frozenset({".ppt", ".pptx", ".odp", ".key", ".pps", ".ppsx"}),
    "pdf": frozenset({".pdf"}),
    "images": frozenset({".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp", ".svg",
                         ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".psd", ".ai", ".avif", ".jxl"}),
    "video": frozenset({".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".webm", ".3gp", ".mts", ".mpg", ".mpeg"}),
    "audio": frozenset({".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".aiff", ".wma", ".opus", ".aif"}),
    "archives": frozenset({".zip", ".rar", ".7z", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".dmg", ".iso"}),
    "text": frozenset({".txt", ".md", ".json", ".xml", ".html", ".htm", ".css", ".js", ".py", ".log", ".yml", ".yaml", ".ini"}),
    "ebooks": frozenset({".epub", ".mobi", ".azw", ".azw3"}),
    "mapfiles": frozenset({".kml", ".kmz", ".gpx"}),
}
CATEGORY_LABELS = {
    "documents": "Documents", "spreadsheets": "Spreadsheets", "presentations": "Presentations", "pdf": "PDFs",
    "images": "Images", "video": "Video", "audio": "Audio", "archives": "Archives", "text": "Text & code",
    "ebooks": "Ebooks", "mapfiles": "Map files", "other": "Other files",
}
GOOGLE_WORDS: Dict[str, FrozenSet[str]] = {
    "google": frozenset({"document", "spreadsheet", "presentation", "drawing", "map", "form", "site", "jam", "script", "table", "unknown"}),
    "google-docs": frozenset({"document"}),
    "google-sheets": frozenset({"spreadsheet"}),
    "google-slides": frozenset({"presentation"}),
    "google-drawings": frozenset({"drawing"}),
    "google-maps": frozenset({"map"}),
    "google-forms": frozenset({"form"}),
}
CATEGORY_GOOGLE = {"documents": "document", "spreadsheets": "spreadsheet", "presentations": "presentation"}
ALIASES = {"doc": "documents", "docs": "google-docs", "sheets": "google-sheets", "slides": "google-slides",
           "pdfs": "pdf", "photos": "images", "pictures": "images", "videos": "video", "music": "audio",
           "drawings": "google-drawings", "maps": "google-maps", "forms": "google-forms"}

ALL_EXTS = frozenset().union(*CATEGORIES.values())


def category_of(ext: str) -> str:
    for name, exts in CATEGORIES.items():
        if ext in exts:
            return name
    return "other"


def parse_types(values: Iterable[str]) -> List[str]:
    """Split "pdf, images,.heic" style input into checked type words; raise ValueError on a word nobody knows."""
    out: List[str] = []
    for value in values:
        for raw in value.replace(";", ",").split(","):
            t = raw.strip().lower()
            if not t:
                continue
            t = ALIASES.get(t, t)
            if t.startswith("."):
                if len(t) < 2 or "/" in t:
                    raise ValueError(f"{raw.strip()!r} isn't an extension")
            elif t not in CATEGORIES and t not in GOOGLE_WORDS and t != "other":
                known = ", ".join(list(CATEGORIES) + ["other"] + list(GOOGLE_WORDS))
                raise ValueError(f"unknown type {raw.strip()!r}. Use one of: {known}, or an extension like .heic")
            if t not in out:
                out.append(t)
    return out


def type_matches(e: Entry, word: str) -> bool:
    if word.startswith("."):
        return not e.is_google and e.ext == word
    if word in GOOGLE_WORDS:
        return e.is_google and e.kind in GOOGLE_WORDS[word]
    if word == "other":
        return not e.is_google and e.ext not in ALL_EXTS
    if e.is_google:
        return CATEGORY_GOOGLE.get(word) == e.kind
    return e.ext in CATEGORIES[word]


def _pattern_matches(rel: str, pattern: str) -> bool:
    p = pattern.strip().replace("\\", "/").lower()
    if not p:
        return False
    if p.endswith("/"):
        p += "*"
    rel_l = rel.lower()
    return fnmatch.fnmatchcase(rel_l, p) or fnmatch.fnmatchcase(rel_l.rsplit("/", 1)[-1], p)


@dataclass
class Selection:
    only: List[str] = field(default_factory=list)  # type words; empty = everything
    skip: List[str] = field(default_factory=list)
    include: List[str] = field(default_factory=list)  # path patterns; empty = everything
    exclude: List[str] = field(default_factory=list)
    files: Optional[Set[str]] = None  # an explicit list of paths or folders, from --files-from
    copy: bool = True  # copy ordinary files
    convert: bool = True  # download Google files

    @property
    def active(self) -> bool:
        return bool(self.only or self.skip or self.include or self.exclude or self.files is not None
                    or not self.copy or not self.convert)

    def why_left_out(self, e: Entry) -> Optional[str]:
        """None when the file is in; otherwise the rule that left it out, in plain words."""
        if e.is_google and not self.convert:
            return "Google files weren't downloaded in this run"
        if not e.is_google and not self.copy:
            return "ordinary files weren't copied in this run"
        if self.files is not None and not _in_list(e.rel, self.files):
            return "not in the list of files to copy"
        for p in self.exclude:
            if _pattern_matches(e.rel, p):
                return f"left out by the rule {p!r}"
        if self.include and not any(_pattern_matches(e.rel, p) for p in self.include):
            return "doesn't match the folders or names chosen"
        for t in self.skip:
            if type_matches(e, t):
                return f"its type ({t}) was left out"
        if self.only and not any(type_matches(e, t) for t in self.only):
            return "its type wasn't among the types chosen"
        return None

    def as_text(self) -> str:
        bits = []
        if not self.copy:
            bits.append("no ordinary files")
        if not self.convert:
            bits.append("no Google files")
        if self.only:
            bits.append("only " + ", ".join(self.only))
        if self.skip:
            bits.append("not " + ", ".join(self.skip))
        if self.include:
            bits.append("only matching " + ", ".join(self.include))
        if self.exclude:
            bits.append("leaving out " + ", ".join(self.exclude))
        if self.files is not None:
            bits.append(f"only the {len(self.files)} listed paths")
        return "; ".join(bits) or "everything"


def _in_list(rel: str, wanted: Set[str]) -> bool:
    key = rel.lower()
    if key in wanted:
        return True
    parts = key.split("/")
    return any("/".join(parts[:i]) in wanted for i in range(1, len(parts)))


def read_list(path: Path) -> Set[str]:
    """A --files-from list: one path per line, relative to the source folder; folders take everything in them."""
    out: Set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().replace("\\", "/")
        if not line or line.startswith("#"):
            continue
        while line.startswith("./"):
            line = line[2:]
        out.add(line.strip("/").lower())
    return out


def census(entries: Iterable[Entry]) -> Dict[str, Dict[str, int]]:
    """What's in a folder, for choosing: Google types, categories and extensions with counts."""
    google: Dict[str, int] = {}
    cats: Dict[str, int] = {}
    exts: Dict[str, int] = {}
    for e in entries:
        if e.status == "ignored":
            continue
        if e.is_google:
            google[e.kind] = google.get(e.kind, 0) + 1
        else:
            c = category_of(e.ext)
            cats[c] = cats.get(c, 0) + 1
            key = e.ext or "(none)"
            exts[key] = exts.get(key, 0) + 1
    return {"google": google, "categories": cats, "extensions": dict(sorted(exts.items(), key=lambda kv: -kv[1]))}
