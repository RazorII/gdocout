"""Download a Google file without signing in, and work out what Google's answer means.

What Google answers, measured 2026-10-24 on files shared "anyone with the link":

| Export link        | Its view page | Meaning                                |
|--------------------|---------------|----------------------------------------|
| 200 and the file   | -             | downloaded                             |
| 401                | 200           | viewable, but the owner turned download off |
| 401                | 401           | not shared by link                     |
| 404                | 404           | deleted, or a wrong ID                 |

So a 401 on its own can't tell "download turned off" from "private"; one extra
request to the view page settles it. No cookies are kept or sent, ever.
"""

from __future__ import annotations

import html
import os
import re
import socket
import stat
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import unquote

from . import __version__, google, validate
from .model import CONVERTED, DOWNLOAD_OFF, FAILED, NOT_FOUND, NOT_SHARED, Entry
from .pacing import OK, THROTTLE, TRANSIENT

USER_AGENT = f"gdocout/{__version__} (+https://github.com/RazorII/gdocout)"
PARTIAL = ".gdocout-partial"
CHUNK = 1 << 16


@dataclass
class Response:
    status: int = 0
    content_type: str = ""
    final_url: str = ""
    retry_after: Optional[float] = None
    head: bytes = b""  # first bytes of the body
    filename: str = ""  # from Content-Disposition
    error: str = ""  # network failure, when there's no HTTP answer at all


@dataclass
class Outcome:
    signal: str  # OK, THROTTLE or TRANSIENT, for the pacer
    status: str = ""  # an Entry status, when the file's fate is decided
    note: str = ""
    retry_after: Optional[float] = None
    facts: Dict[str, object] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    out_size: Optional[int] = None
    filename: str = ""


class NoRedirectToSorry(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but stop at Google's "unusual traffic" page so it reads as a throttle."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if "/sorry/" in newurl:
            raise urllib.error.HTTPError(newurl, 429, "Google rate limit page", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Http:
    def __init__(self, timeout: float = 120, rewrite: Optional[Callable[[str], str]] = None):
        self.timeout = timeout
        self.rewrite = rewrite or (lambda u: u)
        # No HTTPCookieProcessor: nothing is remembered between requests.
        self.opener = urllib.request.build_opener(NoRedirectToSorry())

    def get(self, url: str, headers: Optional[Dict[str, str]] = None, save_to: Optional[Path] = None) -> Response:
        req = urllib.request.Request(self.rewrite(url), headers={"User-Agent": USER_AGENT, **(headers or {})})
        r = Response()
        try:
            resp = self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            r.status, r.final_url = e.code, e.geturl() or url
            r.content_type = (e.headers or {}).get("Content-Type", "") if e.headers else ""
            r.retry_after = _retry_after(e.headers.get("Retry-After") if e.headers else None)
            try:
                r.head = e.read(4096)
            except Exception:
                pass
            return r
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, HTTPException, OSError) as e:
            r.error = str(getattr(e, "reason", e))[:200]
            return r
        with resp:
            r.status = resp.status
            r.final_url = resp.geturl()
            r.content_type = resp.headers.get("Content-Type", "")
            r.filename = _filename(resp.headers.get("Content-Disposition", ""))
            try:
                if save_to is None:
                    r.head = resp.read(4096)
                else:
                    with open(save_to, "wb") as f:
                        first = True
                        while True:
                            block = resp.read(CHUNK)
                            if not block:
                                break
                            if first:
                                r.head, first = block[:4096], False
                            f.write(block)
                        f.flush()
                        os.fsync(f.fileno())
            except (socket.timeout, TimeoutError, ConnectionError, HTTPException, OSError) as e:
                r.error = f"the download broke off ({str(e)[:120]})"
        return r


def unhide(path: Path) -> None:
    """Clear macOS's hidden flag on a file gdocout wrote.

    iCloud Drive's file provider has been seen to flag freshly renamed files hidden,
    which makes them vanish from Finder. A copy that can't be seen is no copy.
    """
    flags = getattr(os.stat(path), "st_flags", 0)
    if flags & getattr(stat, "UF_HIDDEN", 0):
        try:
            os.chflags(path, flags & ~stat.UF_HIDDEN)
        except OSError:
            pass


def _retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


def _filename(disposition: str) -> str:
    # attachment; filename="x.docx"; filename*=UTF-8''x%20y.docx
    star = disposition.split("filename*=")
    if len(star) > 1:
        value = star[1].split(";")[0].strip()
        if "''" in value:
            return unquote(value.split("''", 1)[1])
    plain = disposition.split("filename=")
    if len(plain) > 1:
        return plain[1].split(";")[0].strip().strip('"')
    return ""


def throttled(r: Response) -> bool:
    if r.status == 429 or "/sorry/" in r.final_url:
        return True
    head = r.head.lower()
    return r.status in (403, 503) and (b"unusual traffic" in head or b"automated queries" in head)


def page_title(head: bytes) -> str:
    """The <title> of an HTML answer, to quote Google's own words in the report."""
    m = re.search(rb"<title[^>]*>(.*?)</title>", head, re.I | re.S)
    if not m:
        return ""
    return " ".join(html.unescape(m.group(1).decode("utf-8", "replace")).split())[:120]


def export(http: Http, entry: Entry, dest: Path) -> Outcome:
    """Download one Google file to dest, validate it, and say what happened."""
    kind = google.KINDS[entry.kind]
    url = google.export_url(kind, entry.gid, entry.fmt, entry.key)
    headers = google.key_header(entry.gid, entry.key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + PARTIAL)
    try:
        r = http.get(url, headers, save_to=part)
        if r.error:
            return Outcome(TRANSIENT, note=r.error)
        if throttled(r):
            return Outcome(THROTTLE, retry_after=r.retry_after)
        if r.status >= 500:
            return Outcome(TRANSIENT, note=f"Google answered {r.status}")
        if r.status == 200 and "accounts.google." not in r.final_url:
            check = validate.check_file(part, entry.fmt)
            if not check.ok:
                title = page_title(r.head)
                note = check.problem or "the download isn't a valid file"
                return Outcome(OK, FAILED, note=note + (f" (the page said: {title})" if title else ""))
            size = part.stat().st_size
            os.replace(part, dest)
            unhide(dest)
            if entry.mtime:
                try:
                    os.utime(dest, (entry.mtime, entry.mtime))
                except OSError:
                    pass
            return Outcome(OK, CONVERTED, facts=check.facts, warnings=check.warnings, out_size=size, filename=r.filename)
        if r.status == 401 or "accounts.google." in r.final_url:
            return _why_refused(http, kind, entry)
        if r.status == 403:
            # Not the "download turned off" answer (that is a 401, measured). A 403
            # can be a temporary download limit on a busy file, so it stays retryable.
            title = page_title(r.head)
            return Outcome(OK, FAILED, note="Google refused the download (403). This can be a temporary limit "
                           "on a much-downloaded file; running gdocout again later retries it."
                           + (f" The page said: {title}" if title else ""))
        if r.status in (404, 410):
            note = "Google has no file with this ID: it was deleted, or the shortcut is wrong."
            if entry.key:
                note += " (It carries a resource key, which was sent; the owner may have reset the link.)"
            return Outcome(OK, NOT_FOUND, note=note)
        title = page_title(r.head)
        return Outcome(OK, FAILED, note=f"Google answered {r.status}" + (f": {title}" if title else ""))
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def _why_refused(http: Http, kind: google.Kind, entry: Entry) -> Outcome:
    url = google.view_url(kind, entry.gid, entry.key)
    if not url:
        return Outcome(OK, NOT_SHARED, note="Google wants a sign-in for this file.")
    v = http.get(url, google.key_header(entry.gid, entry.key))
    if v.error:
        return Outcome(TRANSIENT, note=v.error)
    if throttled(v):
        return Outcome(THROTTLE, retry_after=v.retry_after)
    if v.status == 200 and "accounts.google." not in v.final_url:
        return Outcome(
            OK, DOWNLOAD_OFF,
            note="Anyone with the link can view it, but its owner turned off downloading for viewers.",
        )
    if v.status in (401, 403) or "accounts.google." in v.final_url:
        return Outcome(OK, NOT_SHARED, note="Not shared with 'anyone with the link'; Google wants a sign-in.")
    if v.status >= 500:
        return Outcome(TRANSIENT, note=f"Google answered {v.status}")
    return Outcome(OK, NOT_SHARED, note=f"Google refused the download (401) and the view page answered {v.status}.")
