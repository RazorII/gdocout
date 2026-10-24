"""Check that a downloaded file really is the document it claims to be.

Google answers errors with a web page, often with status 200, so a download that
"worked" proves nothing. Every export is checked in layers before it counts:

1. It isn't empty and doesn't start like a web page.
2. Its first bytes match the format (ZIP for Office and OpenDocument files and
   KMZ, `%PDF-` for PDF, the PNG signature, an `<svg` or `<kml` root).
3. For ZIP-based formats: every member's CRC checks out (`testzip`), the parts
   that make the format exist ([Content_Types].xml and the main part), and the
   main part is well-formed XML.
4. Facts are read out of it (words and pictures in a document, sheet names,
   slide count, placemarks, PDF pages) for the report. A file that is valid but
   looks empty gets a warning rather than a failure, because empty documents exist.

Copied files are checked by SHA-256: the copy's hash must equal the original's.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
KML = "{http://www.opengis.net/kml/2.2}"

MAIN_PART = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
    "odt": "content.xml",
    "ods": "content.xml",
    "odp": "content.xml",
    "epub": "META-INF/container.xml",
    "kmz": None,  # any .kml member
}
OOXML = {"docx", "xlsx", "pptx"}


@dataclass
class Check:
    ok: bool
    facts: Dict[str, object] = field(default_factory=dict)
    problem: Optional[str] = None  # why it failed
    warnings: List[str] = field(default_factory=list)


def looks_like_html(head: bytes) -> bool:
    h = head.lstrip()[:200].lower()
    return h.startswith(b"<!doctype html") or h.startswith(b"<html") or b"<html" in h[:100]


def check_file(path: Path, fmt: str) -> Check:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError as e:
        return Check(False, problem=f"couldn't read the downloaded file ({e.strerror})")
    if size == 0:
        return Check(False, problem="Google sent an empty file")
    if looks_like_html(head) and fmt not in ("html",):
        return Check(False, problem="Google sent a web page instead of the file")
    try:
        if fmt in MAIN_PART:
            return _check_zip(path, fmt)
        if fmt == "pdf":
            return _check_pdf(path, head, size)
        if fmt == "png":
            ok = head.startswith(b"\x89PNG\r\n\x1a\n")
            return Check(ok, problem=None if ok else "not a PNG image")
        if fmt in ("svg", "kml"):
            return _check_xml_root(path, fmt)
        if fmt in ("txt", "rtf", "md"):
            if fmt == "rtf" and not head.startswith(b"{\\rtf"):
                return Check(False, problem="not an RTF document")
            return Check(True, facts={"bytes": size})
    except (zipfile.BadZipFile, ET.ParseError, OSError, ValueError, EOFError) as e:
        return Check(False, problem=f"the file is damaged ({e.__class__.__name__}: {str(e)[:80]})")
    return Check(True, facts={"bytes": size}, warnings=[f"no content check exists for .{fmt} files"])


def _check_zip(path: Path, fmt: str) -> Check:
    if not zipfile.is_zipfile(path):
        return Check(False, problem=f"not a .{fmt} file (no ZIP structure)")
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad is not None:
            return Check(False, problem=f"the file is damaged ({bad} fails its checksum)")
        names = set(z.namelist())
        if fmt in OOXML and "[Content_Types].xml" not in names:
            return Check(False, problem=f"not a .{fmt} file ([Content_Types].xml is missing)")
        main = MAIN_PART[fmt]
        if fmt == "kmz":
            kmls = [n for n in names if n.lower().endswith(".kml")]
            if not kmls:
                return Check(False, problem="not a KMZ map (no .kml inside)")
            main = kmls[0]
        if main not in names:
            return Check(False, problem=f"not a .{fmt} file ({main} is missing)")
        with z.open(main) as f:
            facts, warnings = _facts(fmt, f, z, names)
    return Check(True, facts=facts, warnings=warnings)


def _facts(fmt: str, f, z: zipfile.ZipFile, names: set):
    """Parse the main part (which also proves it is well-formed) and read facts out of it."""
    facts: Dict[str, object] = {}
    warnings: List[str] = []
    if fmt == "docx":
        words = paragraphs = 0
        for _, el in ET.iterparse(f):
            if el.tag == W + "t" and el.text:
                words += len(el.text.split())
            elif el.tag == W + "p":
                paragraphs += 1
                el.clear()
        images = sum(1 for n in names if n.startswith("word/media/"))
        facts.update(words=words, paragraphs=paragraphs, images=images)
        if words == 0 and images == 0:
            warnings.append("the document has no text and no pictures")
    elif fmt == "xlsx":
        root = ET.parse(f).getroot()
        sheets = [s.get("name") for s in root.iter(S + "sheet")]
        facts.update(sheets=len(sheets), sheet_names=sheets[:50])
        if not sheets:
            warnings.append("the workbook lists no sheets")
    elif fmt == "pptx":
        root = ET.parse(f).getroot()
        slides = sum(1 for _ in root.iter(P + "sldId"))
        facts.update(slides=slides)
        if slides == 0:
            warnings.append("the presentation has no slides")
    elif fmt == "kmz":
        placemarks = sum(1 for _, el in ET.iterparse(f) if el.tag == KML + "Placemark")
        facts.update(placemarks=placemarks)
    else:  # OpenDocument, EPUB: well-formedness is the check
        for _ in ET.iterparse(f):
            pass
    return facts, warnings


def _check_pdf(path: Path, head: bytes, size: int) -> Check:
    if not head.startswith(b"%PDF-"):
        return Check(False, problem="not a PDF")
    with open(path, "rb") as f:
        f.seek(max(0, size - 2048))
        tail = f.read()
        if b"%%EOF" not in tail:
            return Check(False, problem="the PDF is cut off (no end marker)")
        f.seek(0)
        data = f.read() if size <= 200 * 1024 * 1024 else b""
    pages = len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data)) if data else None
    return Check(True, facts={"pages": pages} if pages else {})


def _check_xml_root(path: Path, fmt: str) -> Check:
    for _, el in ET.iterparse(path, events=("start",)):
        tag = el.tag.rsplit("}", 1)[-1]
        ok = tag == fmt
        return Check(ok, problem=None if ok else f"not a .{fmt} file")
    return Check(False, problem=f"not a .{fmt} file")


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()
