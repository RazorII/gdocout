import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest
from conftest import stub

from gdocout import cli, gui


def argv(**form):
    base = {"source": "/src", "dest": "/dst"}
    base.update(form)
    return gui.form_to_argv(base)


def test_defaults_are_a_plain_copy():
    assert argv() == ["copy", "/src", "--dest", "/dst"]


def test_layout_formats_and_pdf():
    assert "--format" not in argv(google={"document": {"include": True, "formats": "docx"}})  # defaults aren't spelled out
    a = argv(flat=True, google={"document": {"include": True, "formats": "docx,pdf"}}, pdf="only")
    assert a[:4] == ["copy", "/src", "--dest", "/dst"]
    assert "--flat" in a and ["--format", "document=docx,pdf"] == a[a.index("--format"):a.index("--format") + 2]
    assert a[-2:] == ["--pdf", "only"]


def test_unticked_google_kinds_are_skipped():
    a = argv(google={k: {"include": k == "document"} for k in gui.FORMAT_KINDS})
    assert a[a.index("--skip") + 1] == "google-sheets,google-slides,google-drawings,google-maps"


def test_no_google_at_all():
    assert "--no-convert" in argv(google={k: {"include": False} for k in gui.FORMAT_KINDS})


def test_only_ticked_file_types_keeps_google_files():
    a = argv(files_mode="only", file_types=["pdf", "images"], file_types_other=".heic, video")
    only = a[a.index("--only") + 1].split(",")
    assert only[:4] == ["pdf", "images", ".heic", "video"]
    assert "google-docs" in only and "google-forms" in only


def test_except_and_none():
    a = argv(files_mode="except", file_types=["video"])
    assert a[a.index("--skip") + 1] == "video"
    assert "--no-copy" in argv(files_mode="none")


def test_rules_and_advanced():
    a = argv(include="Work/\n\n*budget*", exclude="Photos/", limit=20, recheck=True, links=False, max_workers=4)
    assert a.count("--include") == 2 and a.count("--exclude") == 1
    assert ["--limit", "20"] == a[a.index("--limit"):a.index("--limit") + 2]
    assert "--recheck" in a and "--no-links" in a and ["--max-workers", "4"] == a[a.index("--max-workers"):][:2]


def test_every_form_is_a_valid_command():
    a = argv(flat=True, files_mode="only", file_types=["pdf"], include="Work/", pdf="also")
    opts = cli.options_from_args(cli.build_parser().parse_args(a))
    assert opts.flat and opts.selection.only[0] == "pdf" and opts.formats["document"] == ["docx", "pdf"]


def test_missing_choices_are_explained():
    with pytest.raises(gui.FormError, match="folder to copy"):
        gui.form_to_argv({"dest": "/d"})
    with pytest.raises(gui.FormError, match="where the copy goes"):
        gui.form_to_argv({"source": "/s"})
    with pytest.raises(gui.FormError, match="Tick at least one"):
        argv(files_mode="only")


def test_command_line_quotes_paths():
    line = gui.command_line(["copy", "/My Drive", "--dest", "/a b"])
    assert line.startswith("gdocout copy") and ("'/My Drive'" in line or '"/My Drive"' in line)


@pytest.fixture
def server(tmp_path):
    token = "secret-token"
    port_ref = [0]
    job, stop = gui.Job(), threading.Event()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gui.make_handler(token, port_ref, job, stop))
    port_ref[0] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port_ref[0], token
    srv.shutdown()


def call(port, method, path, body=None, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        h["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    return r.status, r.read()


def test_page_needs_the_secret(server):
    port, token = server
    assert call(port, "GET", f"/{token}/")[0] == 200
    assert call(port, "GET", "/")[0] == 404
    assert call(port, "GET", "/wrong/")[0] == 404


def test_another_host_name_is_refused(server):
    port, token = server
    assert call(port, "GET", f"/{token}/", host="evil.example:80")[0] == 404


def test_actions_need_the_secret_header(server):
    port, token = server
    assert call(port, "POST", f"/{token}/api/command", {"source": "/s", "dest": "/d"})[0] == 403
    code, body = call(port, "POST", f"/{token}/api/command", {"source": "/s", "dest": "/d"}, {"X-Gdocout-Token": token})
    assert code == 200 and json.loads(body)["command"].startswith("gdocout copy")


def test_scan_and_folder_listing(server, tmp_path):
    port, token = server
    stub(tmp_path / "lib/Work/Doc.gdoc", "1abcdefghijk")
    (tmp_path / "lib/photo.jpg").write_bytes(b"x")
    code, body = call(port, "POST", f"/{token}/api/scan", {"source": str(tmp_path / "lib")}, {"X-Gdocout-Token": token})
    s = json.loads(body)
    assert code == 200 and s["to_export"] == 1 and s["census"]["google"] == {"document": 1}
    assert s["census"]["categories"] == {"images": 1}
    code, body = call(port, "GET", f"/{token}/api/list?path=" + str(tmp_path / "lib").replace(" ", "%20"))
    assert json.loads(body)["dirs"] == ["Work"]


def test_bad_choices_come_back_as_messages(server):
    port, token = server
    code, body = call(port, "POST", f"/{token}/api/start", {"source": "/nope", "dest": "/d"}, {"X-Gdocout-Token": token})
    assert code == 400 and "isn't a folder" in json.loads(body)["error"]


def test_native_folder_dialog_per_system(monkeypatch, tmp_path):
    monkeypatch.setattr(gui.sys, "platform", "darwin")
    cmd = gui.native_picker_command('Pick "this"', str(tmp_path))
    assert cmd[0] == "osascript" and 'choose folder with prompt "Pick \\"this\\""' in cmd[-1]
    assert gui._applescript_str(str(tmp_path)) in cmd[-1]  # the start folder, escaped as AppleScript wants
    monkeypatch.setattr(gui.sys, "platform", "linux")
    monkeypatch.setattr(gui.os, "name", "nt")
    cmd = gui.native_picker_command("It's mine")
    assert cmd[:3] == ["powershell", "-NoProfile", "-STA"] and "'It''s mine'" in cmd[-1]
    monkeypatch.setattr(gui.os, "name", "posix")
    monkeypatch.setattr(gui.shutil, "which", lambda t: "/usr/bin/zenity" if t == "zenity" else None)
    assert gui.native_picker_command("x")[:3] == ["zenity", "--file-selection", "--directory"]
    monkeypatch.setattr(gui.shutil, "which", lambda t: None)
    assert gui.native_picker_command("x") is None


class Ran:
    def __init__(self, code, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


@pytest.mark.parametrize("ran,expected", [
    (Ran(0, "/Users/someone/My Drive/\n"), {"path": "/Users/someone/My Drive"}),
    (Ran(1, "", "execution error: User canceled. (-128)"), {"cancelled": True}),
    (Ran(1, ""), {"cancelled": True}),
    (Ran(2, "", "boom"), {"unsupported": True, "error": "boom"}),
])
def test_folder_dialog_answers(monkeypatch, ran, expected):
    monkeypatch.setattr(gui, "native_picker_command", lambda title, start=None: ["fake"])
    assert gui.pick_folder("t", runner=lambda *a, **k: ran) == expected


def test_pick_can_be_turned_off(tmp_path):
    token, port_ref, job, stop = "secret-token-1234567890", [0], gui.Job(), threading.Event()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gui.make_handler(token, port_ref, job, stop, native_picker=False))
    port_ref[0] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, body = call(port_ref[0], "POST", f"/{token}/api/pick", {"title": "x"}, {"X-Gdocout-Token": token})
        assert code == 200 and json.loads(body) == {"unsupported": True}
        code, page = call(port_ref[0], "GET", f"/{token}/")
        assert b"<svg" in page and b"__GDOCOUT_ICON__" not in page and b"data:image/svg+xml," in page
        assert b"isn't connected to gdocout" in page  # the message a page opened as a file shows
    finally:
        srv.shutdown()


def test_pages_carry_the_same_icon_as_icon_svg():
    """The icon is written into both pages, so it shows even when a page is opened as a plain file."""
    from importlib import resources
    from urllib.parse import quote
    svg = resources.files("gdocout").joinpath("icon.svg").read_text(encoding="utf-8").strip()
    uri = "data:image/svg+xml," + quote(svg, safe=":/= ")
    for name in ("gui.html", "report_template.html"):
        page = resources.files("gdocout").joinpath(name).read_text(encoding="utf-8")
        assert svg in page and f'href="{uri}"' in page and "__GDOCOUT_" not in page.replace("__GDOCOUT_DATA__", "").replace("__GDOCOUT_VERSION__", ""), name


def test_icon_is_in_the_report_and_survives_a_tricky_name(tmp_path):
    from gdocout import report
    from gdocout.model import Entry
    out = report.write(tmp_path / "r.html", [Entry("__GDOCOUT_ICON__.txt", "file", ".txt", status="copied")], {})
    html = out.read_text(encoding="utf-8")
    data = html.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert json.loads(data)["rows"][0]["p"] == "__GDOCOUT_ICON__.txt" and html.count("<svg") == 1
