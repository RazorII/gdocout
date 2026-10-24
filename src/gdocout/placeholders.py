"""Have Google Drive download files that are only placeholders on this computer.

In Drive for desktop's "stream files" mode, a file nobody has opened is a
placeholder: its name and size are there, its contents aren't. Reading it makes
macOS ask Drive for the contents, which works while Drive is running and signed
in. The same read can wait forever when Drive isn't (a lesson from
iCloud, which uses the same macOS machinery), so every read happens in a child
process with a time limit, and a child that runs out of time is killed. The
file then simply stays "not on this computer".

This downloads; it doesn't pin. For a whole Drive, Drive's own "Available
offline" (or "Mirror files") is faster and keeps the files; this is for the
stragglers, or for when the user would rather not change Drive's settings.
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from .inventory import is_placeholder

READ_ALL = "import sys\nwith open(sys.argv[1], 'rb') as f:\n    while f.read(1 << 20):\n        pass\n"


def time_limit(size: int) -> float:
    """A minute, plus a second per MB; at most an hour."""
    return min(3600.0, 60.0 + size / 1_000_000)


def fetch_one(path: Path, size: int) -> Tuple[bool, str]:
    try:
        subprocess.run([sys.executable, "-c", READ_ALL, str(path)], timeout=time_limit(size),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    except subprocess.TimeoutExpired:
        return False, f"Google Drive didn't deliver it within {int(time_limit(size))} s. Is Drive running and signed in?"
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return False, "reading it failed: " + (err[-1] if err else f"exit {e.returncode}")
    try:
        if is_placeholder(os.lstat(path)):
            return False, "it was read, but is still only a placeholder"
    except OSError as e:
        return False, f"it disappeared ({e.strerror})"
    return True, ""


def fetch_all(items: Iterable[Tuple[Path, int]], workers: int = 4,
              fetch: Optional[Callable[[Path, int], Tuple[bool, str]]] = None) -> List[Tuple[bool, str]]:
    fetch = fetch or fetch_one
    items = list(items)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(lambda it: fetch(*it), items))
