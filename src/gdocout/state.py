"""The run's memory, kept in the destination so a stopped run continues where it left off.

One SQLite file, DEST/.gdocout/state.db. Only the main thread writes to it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import Dict, Iterable, Optional

from .model import Entry

COLUMNS = [f.name for f in fields(Entry)]
JSON_COLUMNS = {"facts", "warnings", "extra"}


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        cols = ", ".join(f"{c} TEXT" if c not in ("size", "attempts") else f"{c} INTEGER" for c in COLUMNS if c != "rel")
        self.db.execute(f"CREATE TABLE IF NOT EXISTS files (rel TEXT PRIMARY KEY, {cols})")
        self.db.commit()

    def get(self, key: str) -> Optional[str]:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: object) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value) if not isinstance(value, str) else value))

    def load(self) -> Dict[str, Entry]:
        out: Dict[str, Entry] = {}
        for row in self.db.execute(f"SELECT {', '.join(COLUMNS)} FROM files"):
            data = dict(zip(COLUMNS, row))
            for c in JSON_COLUMNS:
                data[c] = json.loads(data[c]) if data[c] else ([] if c == "warnings" else {})
            for c, conv in (("size", int), ("attempts", int), ("mtime", float), ("seconds", float)):
                data[c] = conv(data[c] or 0)
            data["out_size"] = int(data["out_size"]) if data["out_size"] not in (None, "", "None") else None
            data["renamed"] = data["renamed"] in ("1", 1, "True", True)
            out[data["rel"]] = Entry(**data)
        return out

    def save(self, entries: Iterable[Entry]) -> None:
        rows = []
        for e in entries:
            row = []
            for c in COLUMNS:
                v = getattr(e, c)
                if c in JSON_COLUMNS:
                    v = json.dumps(v, ensure_ascii=False)
                elif c == "renamed":
                    v = "1" if v else "0"
                elif v is not None and c not in ("size", "attempts"):
                    v = str(v)
                row.append(v)
            rows.append(row)
        marks = ", ".join("?" for _ in COLUMNS)
        self.db.executemany(f"INSERT OR REPLACE INTO files ({', '.join(COLUMNS)}) VALUES ({marks})", rows)

    def commit(self) -> None:
        self.db.commit()

    def close(self) -> None:
        self.db.commit()
        self.db.close()
