"""Whole runs against a fake Google: every outcome, pacing, resume and the safety checks."""

import json
import zipfile

import pytest
from conftest import stub

from gdocout import fetch, run
from gdocout.pacing import Pacer
from gdocout.selection import Selection


def fast_pacer(**kw):
    args = dict(start=2, maximum=4, ramp_every=2, first_pause=0.05, max_pause=0.2, give_up_after=3, min_gap=0, sleep_cap=0.01)
    args.update(kw)
    return Pacer(**args)


def options(src, dest, fake, **kw):
    return run.Options(source=src, dest=dest, http=fetch.Http(timeout=10, rewrite=fake.rewrite),
                       pacer=kw.pop("pacer", fast_pacer()), retry_wait=0, say=lambda m: None, **kw)


@pytest.fixture
def library(tmp_path):
    src = tmp_path / "Drive"
    stub(src / "Work/Plan.gdoc", "okdoc1aaaaaa")
    stub(src / "Work/Budget.gsheet", "oksheet1aaaa")
    stub(src / "Work/Deck.gslides", "okslides1aaa")
    stub(src / "Work/Locked.gdoc", "dloff1aaaaaa")
    stub(src / "Work/Secret.gdoc", "private1aaaa")
    stub(src / "Old/Deleted.gdoc", "gone1aaaaaaa")
    stub(src / "Old/Survey.gform", "form1aaaaaaa")
    stub(src / "Old/Places.gmap", "map1aaaaaaaa")
    stub(src / "Old/Report.docx.gdoc", "okdoc2aaaaaa")
    (src / "Old/Report.docx").write_bytes(b"a real Word file")
    (src / "photo.jpg").write_bytes(b"\xff\xd8" + b"x" * 5000)
    (src / "Empty").mkdir()
    (src / ".DS_Store").write_bytes(b"x")
    return src


def test_full_run(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    res = run.copy_library(options(library, dest, fake_google))
    s = res.summary
    assert res.code == run.EXIT_OK and s["finished"]
    assert s["counts"] == {"converted": 5, "copied": 2, "download_off": 1, "not_shared": 1, "not_found": 1,
                           "no_offline_format": 1, "ignored": 1}
    # outputs exist, are valid, and the structure is kept
    assert zipfile.ZipFile(dest / "Work/Plan.docx").testzip() is None
    assert (dest / "Work/Budget.xlsx").exists() and (dest / "Work/Deck.pptx").exists() and (dest / "Old/Places.kmz").exists()
    assert (dest / "Old/Report.docx").read_bytes() == b"a real Word file"
    assert (dest / "Old/Report (from Google Docs).docx").exists()
    assert (dest / "photo.jpg").read_bytes() == (library / "photo.jpg").read_bytes()
    assert (dest / "Empty").is_dir()
    assert not (dest / ".DS_Store").exists()
    # link pages stand in for what couldn't be saved, and only for those
    assert (dest / "Work/Locked (Google Docs link).html").exists()
    assert (dest / "Work/Secret (Google Docs link).html").exists()
    assert "no download of a form" in (dest / "Old/Survey (Google Forms link).html").read_text(encoding="utf-8")
    assert not list(dest.rglob("Deleted*"))
    # nothing half-written is left behind
    assert not list(dest.rglob("*" + fetch.PARTIAL))
    # report, manifest, summary
    html = (dest / "gdocout-report.html").read_text(encoding="utf-8")
    assert "Work/Locked.gdoc" in html and "/*__GDOCOUT_DATA__*/" not in html
    lines = (dest / ".gdocout/files.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 12 and all(json.loads(x)["rel"] for x in lines)
    assert s["attention"]["download_off"]["examples"] == ["Work/Locked.gdoc"]
    assert s["attention"]["not_shared"]["examples"] == ["Work/Secret.gdoc"]
    # facts read from the files
    rows = {json.loads(x)["rel"]: json.loads(x) for x in lines}
    assert rows["Work/Budget.gsheet"]["facts"]["sheets"] == 3
    assert rows["Work/Deck.gslides"]["facts"]["slides"] == 2
    assert rows["photo.jpg"]["facts"]["sha256"]


def test_second_run_asks_google_nothing(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    run.copy_library(options(library, dest, fake_google))
    before = len(fake_google.hits)
    res = run.copy_library(options(library, dest, fake_google))
    assert len(fake_google.hits) == before and res.code == run.EXIT_OK
    assert sorted(p.name for p in (dest / "Old").iterdir()) == [
        "Places.kmz", "Report (from Google Docs).docx", "Report.docx", "Survey (Google Forms link).html"]


def test_recheck_asks_again_about_refusals_only(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    run.copy_library(options(library, dest, fake_google))
    before = len(fake_google.hits)
    run.copy_library(options(library, dest, fake_google, recheck=True))
    asked = {h.split("/")[4] for h in fake_google.hits[before:]}
    assert asked == {"dloff1aaaaaa", "private1aaaa", "gone1aaaaaaa"}


def test_changed_source_file_is_copied_again(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    run.copy_library(options(library, dest, fake_google))
    (library / "photo.jpg").write_bytes(b"new picture")
    run.copy_library(options(library, dest, fake_google))
    assert (dest / "photo.jpg").read_bytes() == b"new picture"


def test_flat_layout(library, tmp_path, fake_google):
    dest = tmp_path / "Flat"
    res = run.copy_library(options(library, dest, fake_google, flat=True))
    assert res.code == run.EXIT_OK
    files = sorted(p.name for p in dest.iterdir() if p.is_file())
    assert "Plan.docx" in files and "Report (from Google Docs).docx" in files and "photo.jpg" in files
    assert not [p for p in dest.iterdir() if p.is_dir() and p.name != ".gdocout"]


def test_limit_takes_a_sample(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    res = run.copy_library(options(library, dest, fake_google, limit=2, selection=Selection(copy=False)))
    s = res.summary
    assert s["this_run"].get("converted", 0) + s["this_run"].get("download_off", 0) + s["this_run"].get("not_shared", 0) \
        + s["this_run"].get("not_found", 0) == 2
    assert not s["finished"] and s["counts"]["pending"] > 0
    res = run.copy_library(options(library, dest, fake_google))
    assert res.summary["finished"]


def test_throttling_slows_down_and_still_finishes(tmp_path, fake_google):
    src = tmp_path / "Drive"
    for i in range(6):
        stub(src / f"doc{i}.gdoc", f"okdoc{i}aaaaaaa")
    fake_google.throttle_next = 3  # like Google: the connection is slowed, not one file
    res = run.copy_library(options(src, tmp_path / "Copy", fake_google))
    assert res.code == run.EXIT_OK and res.summary["counts"] == {"converted": 6}
    assert res.summary["this_run"]["pauses"] >= 1


def test_gives_up_when_google_keeps_refusing_then_resumes(tmp_path, fake_google):
    src = tmp_path / "Drive"
    for i in range(4):
        stub(src / f"doc{i}.gdoc", f"okdoc{i}aaaaaaa")
    fake_google.always_429 = True
    res = run.copy_library(options(src, tmp_path / "Copy", fake_google))
    assert res.code == run.EXIT_THROTTLED and "half an hour" in res.summary["stopped"]
    assert res.summary["counts"] == {"pending": 4}
    fake_google.always_429 = False
    res = run.copy_library(options(src, tmp_path / "Copy", fake_google))
    assert res.code == run.EXIT_OK and res.summary["counts"] == {"converted": 4}


def test_flaky_answer_is_retried(tmp_path, fake_google):
    src = tmp_path / "Drive"
    stub(src / "a.gdoc", "flaky1aaaaaaa")
    res = run.copy_library(options(src, tmp_path / "Copy", fake_google))
    assert res.summary["counts"] == {"converted": 1}


def test_403_is_not_called_download_off(tmp_path, fake_google):
    src = tmp_path / "Drive"
    stub(src / "a.gdoc", "forbid1aaaaaa")
    res = run.copy_library(options(src, tmp_path / "Copy", fake_google))
    assert res.code == run.EXIT_FAILED and res.summary["counts"] == {"failed": 1}
    row = json.loads((tmp_path / "Copy/.gdocout/files.jsonl").read_text(encoding="utf-8"))
    assert "403" in row["note"] and "Download quota exceeded" in row["note"]


def test_web_page_instead_of_a_file_is_never_kept(tmp_path, fake_google):
    src = tmp_path / "Drive"
    stub(src / "a.gdoc", "webpage1aaaaa")
    dest = tmp_path / "Copy"
    res = run.copy_library(options(src, dest, fake_google))
    assert res.summary["counts"] == {"failed": 1}
    assert not (dest / "a.docx").exists()
    row = json.loads((dest / ".gdocout/files.jsonl").read_text(encoding="utf-8"))
    assert "web page" in row["note"] and "Something odd" in row["note"]


def test_destination_must_be_empty_or_an_earlier_copy(library, tmp_path, fake_google):
    dest = tmp_path / "Busy"
    dest.mkdir()
    (dest / "keep.txt").write_text("mine")
    with pytest.raises(run.RunError, match="isn't empty"):
        run.copy_library(options(library, dest, fake_google))


def test_destination_cannot_be_inside_the_source(library, fake_google):
    with pytest.raises(run.RunError, match="inside"):
        run.copy_library(options(library, library / "copy", fake_google))


def test_layout_cannot_change_halfway(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    run.copy_library(options(library, dest, fake_google, limit=1))
    with pytest.raises(run.RunError, match="Continue it the same way"):
        run.copy_library(options(library, dest, fake_google, flat=True))


def test_another_source_cannot_reuse_a_destination(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    run.copy_library(options(library, dest, fake_google, limit=1))
    other = tmp_path / "Other"
    other.mkdir()
    with pytest.raises(run.RunError, match="different folder"):
        run.copy_library(options(other, dest, fake_google))


def test_scan_writes_nothing(library, tmp_path):
    before = sorted(p for p in tmp_path.rglob("*"))
    s = run.scan(library)
    assert sorted(p for p in tmp_path.rglob("*")) == before
    assert s["to_export"] == 8 and s["to_copy"] == 2 and s["renamed"] == 1
    assert "pending" not in s["attention"] and s["attention"]["no_offline_format"]["count"] == 1


def test_pdf_in_addition(library, tmp_path, fake_google):
    pdf = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"
    real = fake_google.answer

    def answer(path):  # the fake answers PDF requests with a PDF
        if "format=pdf" in path or path.split("?")[0].endswith("/pdf"):
            code, ctype, body = real(path.replace("format=pdf", "format=docx").replace("/export/pdf", "/export/pptx"))
            return (200, "application/pdf", pdf) if code == 200 else (code, ctype, body)
        return real(path)

    fake_google.answer = answer
    dest = tmp_path / "Copy"
    res = run.copy_library(options(library, dest, fake_google, formats={"document": ["docx", "pdf"], "spreadsheet": ["xlsx", "pdf"]}))
    assert res.code == run.EXIT_OK
    assert (dest / "Work/Plan.docx").exists() and (dest / "Work/Plan.pdf").read_bytes().startswith(b"%PDF")
    assert (dest / "Work/Budget.pdf").exists() and not (dest / "Work/Deck.pdf").exists()
    assert res.summary["extra_formats"] == {"converted": 3, "download_off": 1, "not_shared": 1, "not_found": 1}
    # a refusal isn't asked twice: one export + one view request for Locked, none for its PDF
    assert sum("dloff1aaaaaa" in h for h in fake_google.hits) == 2


def test_pdf_added_on_a_later_run_downloads_only_the_pdfs(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    run.copy_library(options(library, dest, fake_google))
    before = len(fake_google.hits)
    res = run.copy_library(options(library, dest, fake_google, formats={"document": ["docx", "pdf"]}))
    asked = fake_google.hits[before:]
    assert asked and all("format=pdf" in h for h in asked)
    assert res.summary["counts"]["converted"] == 5


def test_only_some_types(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    res = run.copy_library(options(library, dest, fake_google, selection=Selection(only=["google-docs", "images"])))
    c = res.summary["counts"]
    assert (dest / "photo.jpg").exists() and (dest / "Work/Plan.docx").exists()
    assert not (dest / "Work/Budget.xlsx").exists() and not (dest / "Old/Report.docx").exists()
    assert c["skipped"] == 5  # Budget, Deck, Places, Survey and the real Report.docx
    assert res.summary["finished"]


def test_left_out_files_keep_their_names_for_later(library, tmp_path, fake_google):
    dest = tmp_path / "Copy"
    run.copy_library(options(library, dest, fake_google, selection=Selection(copy=False)))
    assert (dest / "Old/Report (from Google Docs).docx").exists() and not (dest / "Old/Report.docx").exists()
    run.copy_library(options(library, dest, fake_google))
    assert (dest / "Old/Report.docx").read_bytes() == b"a real Word file"
