"""Download through the user's own web browser, for files that aren't shared by link.

When the browser is signed in to Google with an account that can open the file
(usually the same account Google Drive for desktop syncs), Google hands it the
file like any download. gdocout opens Google's download link there, waits for the
file to land in the browser's download folder, checks it, and moves it into the
copy. gdocout never sees a password or a cookie: the browser does what it always
does when you click Download.

Measured 2026-10-24 with Chrome signed in: a private Doc downloaded in about 6 s,
named after its title, and Chrome closed the tab by itself. An account without
access gets Google's "Access Denied" page in a tab that stays open, and nothing
downloads; so gdocout stops after a few failures in a row instead of opening
hundreds of such tabs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Iterable, Optional, Set

# name -> (macOS app name, Windows / Linux command)
BROWSERS = {
    "chrome": ("Google Chrome", "chrome"),
    "safari": ("Safari", None),
    "edge": ("Microsoft Edge", "msedge"),
    "brave": ("Brave Browser", "brave"),
    "firefox": ("Firefox", "firefox"),
    "arc": ("Arc", None),
}
PARTIAL = (".crdownload", ".download", ".part", ".partial", ".tmp", ".opdownload", ".gdocout-partial")


class BrowserError(Exception):
    pass


def open_url(url: str, browser: str = "default", background: bool = False) -> None:
    """Open a link in the user's browser: their default one, or the one named."""
    if browser in ("", "default", None):
        if sys.platform == "darwin" and background:
            subprocess.run(["open", "-g", url], check=False)
        elif not webbrowser.open(url, new=2):
            raise BrowserError("couldn't open the web browser")
        return
    if browser not in BROWSERS:
        raise BrowserError(f"unknown browser {browser!r}; use one of default, {', '.join(BROWSERS)}")
    app, cmd = BROWSERS[browser]
    if sys.platform == "darwin":
        r = subprocess.run(["open"] + (["-g"] if background else []) + ["-a", app, url], capture_output=True, text=True)
        if r.returncode != 0:
            raise BrowserError(f"{app} isn't installed or couldn't open")
    elif os.name == "nt":
        if not cmd:
            raise BrowserError(f"{browser} isn't available on Windows")
        subprocess.run(["cmd", "/c", "start", "", cmd, url], check=False)
    else:
        if not cmd:
            raise BrowserError(f"{browser} isn't available here")
        subprocess.Popen([cmd, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _chrome_family_dir(browser: str) -> Optional[Path]:
    """Where a Chrome-family browser's last-used profile saves downloads, if it's set somewhere special."""
    home = Path.home()
    roots = {
        "chrome": [home / "Library/Application Support/Google/Chrome", home / "AppData/Local/Google/Chrome/User Data", home / ".config/google-chrome"],
        "edge": [home / "Library/Application Support/Microsoft Edge", home / "AppData/Local/Microsoft/Edge/User Data", home / ".config/microsoft-edge"],
        "brave": [home / "Library/Application Support/BraveSoftware/Brave-Browser", home / "AppData/Local/BraveSoftware/Brave-Browser/User Data", home / ".config/BraveSoftware/Brave-Browser"],
    }.get(browser, [])
    for root in roots:
        try:
            profile = json.loads((root / "Local State").read_text(encoding="utf-8")).get("profile", {}).get("last_used") or "Default"
            prefs = json.loads((root / profile / "Preferences").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        d = prefs.get("download", {}).get("default_directory")
        if d and Path(d).is_dir():
            return Path(d)
    return None


def downloads_folder(browser: str = "default", override: Optional[Path] = None) -> Path:
    if override:
        return override.expanduser()
    special = _chrome_family_dir(browser) if browser in ("chrome", "edge", "brave") else None
    return special or Path.home() / "Downloads"


def snapshot(folder: Path) -> Set[str]:
    try:
        return set(os.listdir(folder))
    except OSError:
        return set()


def wait_for_download(folder: Path, before: Set[str], exts: Iterable[str], timeout: float, poll: float = 0.5,
                      clock=time.monotonic, sleep=time.sleep) -> Optional[Path]:
    """Wait for one new, finished file with one of these extensions to appear in the folder."""
    exts = {x.lower() for x in exts}
    deadline = clock() + timeout
    sizes = {}
    while clock() < deadline:
        for name in snapshot(folder) - before:
            if name.startswith(".") or name.lower().endswith(PARTIAL):
                continue
            if os.path.splitext(name)[1].lower() not in exts:
                continue
            path = folder / name
            try:
                if not path.is_file():
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            if size > 0 and sizes.get(name) == size:  # unchanged since the last look: the download is done
                return path
            sizes[name] = size
        sleep(poll)
    return None
