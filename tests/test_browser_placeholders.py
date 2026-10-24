"""The signed-in browser pass and asking Google Drive for placeholders, without a real browser or Drive."""

import os
import threading
import time

import pytest
from conftest import make_docx, stub

from gdocout import browser, fetch, inventory, placeholders, run
from gdocout.pacing import Pacer


def fast_pacer():
    return Pacer(start=2, maximum=4, ramp_every=2, first_pause=0.05, max_pause=0.2, give_up_after=3, min_gap=0, sleep_cap=0.01)


class FakeBrowser:
    """Signed in to an account that can open some files: those it 'downloads' into the folder, like a browser would."""

    def __init__(self, folder, can_open=("private",)):
        self.folder, self.can_open, self.urls = folder, can_open, []

    def __call__(self, url, background):
        self.urls.append(url)
        if any(f"/d/{p}" in url for p in self.can_open):
            name = "Title from Google.docx" if "format=docx" in url else "Title from Google.pdf"
            body = make_docx("signed in") if "format=docx" in url else b"%PDF-1.4\n%%EOF\n"

            def land():
                time.sleep(0.2)
                part = self.folder / (name + ".crdownload")
                part.write_bytes(body[:10])  # still downloading…
                time.sleep(0.3)
                part.write_bytes(body)  # finished: the browser renames it to its real name
                part.rename(self.folder / name)

            threading.Thread(target=land, daemon=True).start()


def opts(src, dest, fake_google, fb, dl, **kw):
    return run.Options(source=src, dest=dest, http=fetch.Http(timeout=10, rewrite=fake_google.rewrite), pacer=fast_pacer(),
                       retry_wait=0, say=lambda m: None, browser="default", downloads=dl, browser_timeout=3, opener=fb, **kw)


def stub_with_account(path, file_id, account="owner@example.com"):
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"doc_id": file_id, "resource_key": "", "email": account}))


def test_refused_files_come_through_the_signed_in_browser(tmp_path, fake_google):
    src, dl, dest = tmp_path / "Drive", tmp_path / "Downloads", tmp_path / "Copy"
    dl.mkdir()
    stub_with_account(src / "Mine.gdoc", "private1aaaa")
    stub(src / "Open.gdoc", "okdoc1aaaaaa")
    fb = FakeBrowser(dl)
    res = run.copy_library(opts(src, dest, fake_google, fb, dl, formats={"document": ["docx", "pdf"]}))
    assert res.summary["counts"] == {"converted": 2}
    assert (dest / "Mine.docx").exists() and (dest / "Mine.pdf").exists()
    assert not list(dl.iterdir())  # moved out of the downloads folder, nothing left behind
    assert fb.urls and all("authuser=owner@example.com" in u for u in fb.urls)
    assert not (dest / "Mine (Google Docs link).html").exists()


def test_browser_without_access_stops_early_and_says_why(tmp_path, fake_google):
    src, dl, dest = tmp_path / "Drive", tmp_path / "Downloads", tmp_path / "Copy"
    dl.mkdir()
    for i in range(5):
        stub(src / f"Locked{i}.gdoc", f"private{i}aaaaaaa")
    said = []
    fb = FakeBrowser(dl, can_open=())
    o = opts(src, dest, fake_google, fb, dl)
    o.browser_timeout, o.say = 0.8, said.append
    res = run.copy_library(o)
    assert res.summary["counts"] == {"not_shared": 5}
    assert len(fb.urls) == 3  # gave up after three in a row, instead of opening five tabs
    assert any("Sign in to Google there" in m for m in said)


def test_wait_for_download_ignores_partial_and_other_files(tmp_path):
    (tmp_path / "old.docx").write_bytes(b"x")
    before = browser.snapshot(tmp_path)
    (tmp_path / "new.docx.crdownload").write_bytes(b"x")
    (tmp_path / "photo.jpg").write_bytes(b"x")
    assert browser.wait_for_download(tmp_path, before, {".docx"}, timeout=1.2, poll=0.2) is None
    (tmp_path / "Report.docx").write_bytes(b"xyz")
    assert browser.wait_for_download(tmp_path, before, {".docx"}, timeout=2, poll=0.2).name == "Report.docx"


def test_unknown_browser_is_refused():
    with pytest.raises(browser.BrowserError, match="unknown browser"):
        browser.open_url("https://x", "netscape")


def test_placeholders_are_fetched_then_copied(tmp_path, fake_google, monkeypatch):
    src, dest = tmp_path / "Drive", tmp_path / "Copy"
    src.mkdir()
    (src / "far.pdf").write_bytes(b"P" * 777)  # 777 bytes = a placeholder, for this test
    stub(src / "Doc.gdoc", "okdoc1aaaaaa")
    marked = {str(src / "far.pdf")}
    real_lstat = os.lstat

    def is_ph(st):
        return st.st_size == 777 and bool(marked)

    monkeypatch.setattr(inventory, "is_placeholder", is_ph)
    monkeypatch.setattr(placeholders, "fetch_one", lambda path, size: (marked.discard(str(path)) or True, ""))
    o = run.Options(source=src, dest=dest, http=fetch.Http(timeout=10, rewrite=fake_google.rewrite), pacer=fast_pacer(),
                    retry_wait=0, say=lambda m: None)
    assert run.copy_library(o).summary["counts"]["not_on_disk"] == 1
    marked.add(str(src / "far.pdf"))
    o.fetch_placeholders = True
    res = run.copy_library(o)
    assert res.summary["counts"] == {"converted": 1, "copied": 1}
    assert (dest / "far.pdf").read_bytes() == b"P" * 777
    del real_lstat


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs a named pipe")
def test_a_read_that_never_returns_is_killed(tmp_path, monkeypatch):
    pipe = tmp_path / "stuck"
    os.mkfifo(pipe)  # opening it for reading blocks forever, like a placeholder nobody delivers
    monkeypatch.setattr(placeholders, "time_limit", lambda size: 1.0)
    t = time.monotonic()
    ok, why = placeholders.fetch_one(pipe, 0)
    assert not ok and "didn't deliver it" in why and time.monotonic() - t < 10


def test_time_limits_grow_with_size():
    assert placeholders.time_limit(0) == 60 and placeholders.time_limit(10**12) == 3600
