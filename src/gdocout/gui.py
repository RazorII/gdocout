"""gdocout's window: a page in your web browser, served by gdocout itself, on this computer only.

Why a browser page: it needs nothing beyond Python, looks the same on macOS,
Windows and Linux, and Python's own GUI toolkit (tkinter) is missing from some
common Python installs (Homebrew's, for one).

Safety: the server listens on 127.0.0.1 only, every address carries a random
secret, requests must name this computer as their host, and actions need the
secret in a header too, which another web page can't send. It reads folder names
to let you choose folders, and runs exactly the copy the page describes. The
equivalent command is always shown, so anything done here can also be scripted.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import shlex
import string
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from . import __version__, cli, google as gkinds, run

FORMAT_KINDS = ("document", "spreadsheet", "presentation", "drawing", "map")
GOOGLE_WORD = {"document": "google-docs", "spreadsheet": "google-sheets", "presentation": "google-slides",
               "drawing": "google-drawings", "map": "google-maps"}


class FormError(ValueError):
    pass


def form_to_argv(form: Dict[str, object], command: str = "copy") -> List[str]:
    """Turn the page's choices into gdocout's own command-line arguments (the single source of truth)."""
    source = str(form.get("source") or "").strip()
    if not source:
        raise FormError("Choose the folder to copy first.")
    argv = [command, source]
    if command == "copy":
        dest = str(form.get("dest") or "").strip()
        if not dest:
            raise FormError("Choose where the copy goes.")
        argv += ["--dest", dest]
    if form.get("flat"):
        argv.append("--flat")

    google = form.get("google") or {}
    included_google = []
    for kind in FORMAT_KINDS:
        g = google.get(kind) or {}
        if g.get("include", True):
            included_google.append(kind)
            fmts = str(g.get("formats") or "").strip().replace(" ", "")
            if fmts and fmts != gkinds.KINDS[kind].default:  # the command names only what differs from the defaults
                argv += ["--format", f"{kind}={fmts}"]
    if form.get("pdf") in ("also", "only"):
        argv += ["--pdf", str(form["pdf"])]
    if not included_google:
        argv.append("--no-convert")
    left_out_google = [GOOGLE_WORD[k] for k in FORMAT_KINDS if k not in included_google]

    mode = form.get("files_mode") or "all"
    ticked = [t for t in (form.get("file_types") or []) if t]
    other = str(form.get("file_types_other") or "").strip()
    if other:
        ticked += [t.strip() for t in other.replace(";", ",").split(",") if t.strip()]
    if mode == "none":
        argv.append("--no-copy")
        if left_out_google:
            argv += ["--skip", ",".join(left_out_google)]
    elif mode == "only":
        if not ticked:
            raise FormError("Tick at least one file type to copy, or choose another option.")
        google_words = [GOOGLE_WORD[k] for k in included_google] + (["google-forms"] if included_google else [])
        argv += ["--only", ",".join(ticked + google_words)]
    else:
        skip = left_out_google + (ticked if mode == "except" else [])
        if skip:
            argv += ["--skip", ",".join(skip)]

    for line in str(form.get("include") or "").splitlines():
        if line.strip():
            argv += ["--include", line.strip()]
    for line in str(form.get("exclude") or "").splitlines():
        if line.strip():
            argv += ["--exclude", line.strip()]

    if command == "copy":
        if form.get("limit"):
            argv += ["--limit", str(int(form["limit"]))]
        if form.get("recheck"):
            argv.append("--recheck")
        if form.get("links") is False:
            argv.append("--no-links")
        if form.get("fetch_placeholders"):
            argv.append("--fetch-placeholders")
        if form.get("use_browser"):
            argv += ["--browser", str(form.get("browser") or "default")]
            if str(form.get("downloads") or "").strip():
                argv += ["--downloads", str(form["downloads"]).strip()]
        mw = int(form.get("max_workers") or 8)
        if mw != 8:
            argv += ["--max-workers", str(max(1, min(mw, 16)))]
    return argv


def command_line(argv: List[str]) -> str:
    if os.name == "nt":
        return "gdocout " + subprocess.list2cmdline(argv)
    return "gdocout " + " ".join(shlex.quote(a) for a in argv)


def places() -> List[Dict[str, str]]:
    """Good starting points for the folder browser, Google Drive's own folders first."""
    home = Path.home()
    out: List[Dict[str, str]] = []

    def add(label: str, path: Path) -> None:
        try:
            if path.is_dir() and not any(p["path"] == str(path) for p in out):
                out.append({"label": label, "path": str(path)})
        except OSError:
            pass

    cloud = home / "Library" / "CloudStorage"
    try:
        for d in sorted(cloud.iterdir()) if cloud.is_dir() else []:
            if d.name.startswith("GoogleDrive-"):
                who = d.name[len("GoogleDrive-"):]
                add(f"Google Drive ({who}): My Drive", d / "My Drive")
                add(f"Google Drive ({who}): Shared drives", d / "Shared drives")
                add(f"Google Drive ({who})", d)
    except OSError:
        pass
    add("Google Drive (older app)", home / "Google Drive")
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:\\")
            if (root / "My Drive").is_dir():
                add(f"Google Drive ({letter}:): My Drive", root / "My Drive")
    add("Home", home)
    for name in ("Desktop", "Documents", "Downloads"):
        add(name, home / name)
    if sys.platform == "darwin":
        try:
            for v in sorted(Path("/Volumes").iterdir()):
                if not v.name.startswith("."):
                    add(f"Disk: {v.name}", v)
        except OSError:
            pass
    elif os.name == "nt":
        for letter in string.ascii_uppercase:
            add(f"Drive {letter}:", Path(f"{letter}:\\"))
    else:
        for base in (Path("/media") / home.name, Path("/mnt")):
            try:
                for v in sorted(base.iterdir()) if base.is_dir() else []:
                    add(f"Disk: {v.name}", v)
            except OSError:
                pass
    return out


def list_dir(path_s: str, hidden: bool = False) -> Dict[str, object]:
    path = Path(path_s).expanduser() if path_s else Path.home()
    try:
        path = path.resolve()
        dirs = []
        with os.scandir(path) as it:
            for d in it:
                if (not hidden and d.name.startswith(".")) or d.name in ("$RECYCLE.BIN", "System Volume Information"):
                    continue
                try:
                    if d.is_dir(follow_symlinks=False):
                        dirs.append(d.name)
                except OSError:
                    pass
        dirs.sort(key=str.casefold)
        return {"path": str(path), "parent": str(path.parent) if path.parent != path else None, "dirs": dirs}
    except PermissionError:
        return {"path": str(path), "parent": str(path.parent), "dirs": [], "error": run.permission_help(path)}
    except OSError as e:
        return {"path": str(path), "parent": str(path.parent), "dirs": [], "error": f"Can't open {path}: {e.strerror}"}


def open_in_os(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Job:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.live: Dict[str, object] = {}
        self.log: List[str] = []
        self.summary: Optional[Dict[str, object]] = None
        self.code: Optional[int] = None
        self.error = ""
        self.command = ""
        self.dest: Optional[Path] = None

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def status(self) -> Dict[str, object]:
        with self.lock:
            return {"running": self.running, "live": dict(self.live), "log": self.log[-40:], "summary": self.summary,
                    "code": self.code, "error": self.error, "command": self.command}


def start_job(job: Job, form: Dict[str, object]) -> Dict[str, object]:
    if job.running:
        raise FormError("A copy is already running.")
    argv = form_to_argv(form, "copy")
    args = cli.build_parser().parse_args(argv)
    opts = cli.options_from_args(args)
    run.check_paths(opts.source, opts.dest)  # fail now, in the page, not in the background
    job.__init__()
    job.command = command_line(argv)
    job.dest = opts.dest.expanduser().resolve()
    opts.cancel = job.cancel

    def say(msg: str) -> None:
        with job.lock:
            job.log.append(time.strftime("%H:%M:%S ") + msg)

    def progress(live: Dict[str, object]) -> None:
        with job.lock:
            job.live = live

    opts.say, opts.progress = say, progress

    def go() -> None:
        try:
            res = run.copy_library(opts)
            with job.lock:
                job.summary, job.code = res.summary, res.code
        except run.RunError as e:
            with job.lock:
                job.error, job.code = str(e), run.EXIT_USAGE
        except Exception as e:  # shown in the page rather than lost in a terminal
            with job.lock:
                job.error, job.code = f"{e.__class__.__name__}: {e}", run.EXIT_FAILED

    job.thread = threading.Thread(target=go, daemon=True)
    job.thread.start()
    return {"started": True, "command": job.command}


def scan_form(form: Dict[str, object]) -> Dict[str, object]:
    argv = form_to_argv(form, "scan")
    args = cli.build_parser().parse_args(argv)
    s = run.scan(args.source, args.flat, cli.parse_formats(args.format, args.pdf), cli.selection_from_args(args))
    return s


def make_handler(token: str, port_ref: List[int], job: Job, stop: threading.Event):
    page = resources.files("gdocout").joinpath("gui.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = f"gdocout/{__version__}"

        def log_message(self, *a):
            pass

        def _ok_host(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}")

        def _route(self) -> Optional[str]:
            u = urlparse(self.path)
            parts = u.path.split("/", 2)
            if len(parts) < 2 or not hmac.compare_digest(parts[1], token) or not self._ok_host():
                return None
            return "/" + (parts[2] if len(parts) > 2 else "")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: object, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            route = self._route()
            if route is None:
                return self._send(404, b"not found", "text/plain")
            q = parse_qs(urlparse(self.path).query)
            if route == "/":
                return self._send(200, page.replace("__GDOCOUT_VERSION__", __version__).encode("utf-8"), "text/html; charset=utf-8")
            if route == "/api/places":
                return self._json({"places": places()})
            if route == "/api/list":
                return self._json(list_dir((q.get("path") or [""])[0], (q.get("hidden") or ["0"])[0] == "1"))
            if route == "/api/status":
                return self._json(job.status())
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            route = self._route()
            if route is None or not hmac.compare_digest(self.headers.get("X-Gdocout-Token") or "", token):
                return self._send(403, b"forbidden", "text/plain")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                form = json.loads(self.rfile.read(min(n, 1 << 20)) or b"{}")
            except ValueError:
                return self._json({"error": "bad request"}, 400)
            try:
                if route == "/api/command":
                    argv = form_to_argv(form, "copy")
                    cli.build_parser().parse_args(argv)
                    return self._json({"command": command_line(argv)})
                if route == "/api/scan":
                    return self._json(scan_form(form))
                if route == "/api/start":
                    return self._json(start_job(job, form))
                if route == "/api/stop":
                    job.cancel.set()
                    return self._json({"stopping": True})
                if route == "/api/open":
                    if not job.dest:
                        return self._json({"error": "nothing to open yet"}, 400)
                    target = job.dest / "gdocout-report.html" if form.get("what") == "report" else job.dest
                    if target.exists():
                        open_in_os(target)
                    return self._json({"opened": str(target)})
                if route == "/api/quit":
                    stop.set()
                    return self._json({"bye": True})
            except (FormError, run.RunError, cli.UsageError) as e:
                return self._json({"error": str(e)}, 400)
            except SystemExit:
                return self._json({"error": "Some of the choices aren't valid."}, 400)
            return self._send(404, b"not found", "text/plain")

    return Handler


def serve(port: int = 0, open_browser: bool = True, source: Optional[Path] = None, dest: Optional[Path] = None) -> int:
    token = secrets.token_urlsafe(18)
    job, stop, port_ref = Job(), threading.Event(), [0]
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(token, port_ref, job, stop))
    server.daemon_threads = True
    port_ref[0] = server.server_address[1]
    url = f"http://127.0.0.1:{port_ref[0]}/{token}/"
    prefill = {k: str(v.expanduser().resolve()) for k, v in (("source", source), ("dest", dest)) if v}
    if prefill:
        url += "#" + urlencode(prefill)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"gdocout {__version__} is open in your browser: {url}", flush=True)
    print("Keep this window open while you use it. Press Ctrl-C (or Quit in the page) to close it.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        while not stop.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    job.cancel.set()
    if job.thread:
        job.thread.join(timeout=15)
    server.shutdown()
    return 0
