"""Write the human-readable report: one self-contained HTML page with every file.

The page carries its data as JSON and needs nothing else (no internet, no
server), so it can be opened from the destination folder on any computer or
phone. Every filename is inserted as text, never as HTML.
"""

from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path
from typing import Dict, List

from . import google
from .model import EXPLAIN, LABELS, Entry


def rows(entries: List[Entry]) -> List[Dict[str, object]]:
    out = []
    for e in sorted(entries, key=lambda e: e.rel.casefold()):
        row: Dict[str, object] = {"p": e.rel, "k": e.kind, "x": e.ext, "s": e.size, "st": e.status}
        if e.out_rel:
            row["o"] = e.out_rel
        if e.link_rel:
            row["l"] = e.link_rel
        if e.out_size is not None:
            row["os"] = e.out_size
        if e.renamed:
            row["r"] = 1
        if e.note:
            row["n"] = e.note
        if e.facts:
            row["f"] = {k: v for k, v in e.facts.items() if k != "sha256"}
            if "sha256" in e.facts:
                row["h"] = e.facts["sha256"]
        if e.warnings:
            row["w"] = e.warnings
        if e.gid:
            row["u"] = google.open_url(e.gid, e.key)
        if e.fmt:
            row["fm"] = e.fmt
        if e.mtime:
            row["m"] = int(e.mtime)
        out.append(row)
    return out


def write(path: Path, entries: List[Entry], summary: Dict[str, object]) -> Path:
    data = {
        "summary": summary,
        "labels": LABELS,
        "explain": EXPLAIN,
        "kinds": {k.name: k.label for k in google.KINDS.values()},
        "rows": rows(entries),
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    template = resources.files("gdocout").joinpath("report_template.html").read_text(encoding="utf-8")
    html = template.replace("/*__GDOCOUT_DATA__*/{}", blob)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, path)
    return path
