import os
import sys
import unicodedata

import pytest
from conftest import stub

from gdocout import inventory
from gdocout.model import IGNORED, NO_FORMAT, NOT_ON_DISK, PENDING, UNREADABLE, Entry


def by_rel(inv):
    return {e.rel: e for e in inv.entries}


def test_walk_classifies_everything(tmp_path):
    stub(tmp_path / "a/Doc.gdoc", "1abcdefghijk")
    stub(tmp_path / "a/Sheet.gsheet", "1abcdefghijl")
    stub(tmp_path / "a/Deck.gslides", "1abcdefghijm")
    stub(tmp_path / "a/Survey.gform", "1abcdefghijn")
    stub(tmp_path / "a/Map.gmap", "1abcdefghijo")
    (tmp_path / "a/Broken.gdoc").write_text("nope")
    (tmp_path / "a/photo.jpg").write_bytes(b"\xff\xd8 jpeg")
    (tmp_path / "a/track.gpx").write_text("<gpx/>")  # a .gXX extension that isn't Google's
    (tmp_path / "a/data.gz").write_bytes(b"\x1f\x8b")
    (tmp_path / ".DS_Store").write_bytes(b"x")
    (tmp_path / "a/~$Report.docx").write_bytes(b"x")
    (tmp_path / "empty").mkdir()
    inv = inventory.walk(tmp_path)
    e = by_rel(inv)
    assert (e["a/Doc.gdoc"].kind, e["a/Doc.gdoc"].status, e["a/Doc.gdoc"].gid) == ("document", PENDING, "1abcdefghijk")
    assert e["a/Sheet.gsheet"].kind == "spreadsheet" and e["a/Deck.gslides"].kind == "presentation"
    assert e["a/Map.gmap"].kind == "map" and e["a/Map.gmap"].status == PENDING
    assert (e["a/Survey.gform"].kind, e["a/Survey.gform"].status) == ("form", NO_FORMAT)
    assert e["a/Broken.gdoc"].status == UNREADABLE
    for plain in ("a/photo.jpg", "a/track.gpx", "a/data.gz"):
        assert (e[plain].kind, e[plain].status) == ("file", PENDING), plain
    assert e[".DS_Store"].status == IGNORED and e["a/~$Report.docx"].status == IGNORED
    assert set(inv.dirs) == {"a", "empty"}


def test_unknown_google_stub_type_is_recognised(tmp_path):
    stub(tmp_path / "Thing.gvid", "1abcdefghijk")
    e = by_rel(inventory.walk(tmp_path))["Thing.gvid"]
    assert (e.kind, e.status) == ("unknown", NO_FORMAT)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_links_are_not_followed(tmp_path):
    (tmp_path / "real.txt").write_text("x")
    os.symlink(tmp_path / "real.txt", tmp_path / "link.txt")
    os.symlink(tmp_path, tmp_path / "loop")
    e = by_rel(inventory.walk(tmp_path))
    assert e["link.txt"].status == IGNORED and e["loop"].status == IGNORED


def test_placeholders_are_never_opened(tmp_path, monkeypatch):
    stub(tmp_path / "Doc.gdoc", "1abcdefghijk")
    (tmp_path / "big.mov").write_bytes(b"x")
    monkeypatch.setattr(inventory, "is_placeholder", lambda st: True)
    opened = []
    real_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda *a, **k: (opened.append(a[0]) if str(tmp_path) in str(a[0]) else None) or real_open(*a, **k),
    )
    e = by_rel(inventory.walk(tmp_path))
    assert e["Doc.gdoc"].status == NOT_ON_DISK and e["Doc.gdoc"].kind == "document"
    assert e["big.mov"].status == NOT_ON_DISK
    assert not opened


def test_placeholder_flags():
    class St:
        st_flags = inventory.SF_DATALESS
    assert inventory.is_placeholder(St())

    class Win:
        st_flags = 0
        st_file_attributes = 0x400000
    assert inventory.is_placeholder(Win())


def E(rel, kind="file", status=PENDING):
    base, ext = inventory.split_ext(rel.rsplit("/", 1)[-1])
    return Entry(rel, kind, ext.lower(), status=status)


def test_converted_name_never_overwrites_a_real_file():
    entries = [E("r/Report.docx.gdoc", "document"), E("r/Report.docx")]
    inventory.allocate(entries, ["r"], flat=False, formats={})
    assert entries[1].out_rel == "r/Report.docx" and not entries[1].renamed
    assert entries[0].out_rel == "r/Report (from Google Docs).docx" and entries[0].renamed


def test_family_extension_is_not_doubled():
    entries = [E("Notes.docx.gdoc", "document"), E("Budget.gsheet", "spreadsheet"), E("v2.final.gdoc", "document")]
    inventory.allocate(entries, [], flat=False, formats={})
    assert [e.out_rel for e in entries] == ["Notes.docx", "Budget.xlsx", "v2.final.docx"]


def test_names_compare_like_a_case_insensitive_disk():
    nfc = unicodedata.normalize("NFC", "Caf\u00e9.txt")
    upper = "CAF\u00c9.TXT"
    nfd = unicodedata.normalize("NFD", "caf\u00e9.txt")  # the form macOS hands out
    entries = [E(nfc), E(upper), E(nfd)]
    inventory.allocate(entries, [], flat=False, formats={})
    # one keeps its name, the others are numbered; names are handed out in sorted order
    assert entries[1].out_rel == upper
    assert entries[0].out_rel == "Caf\u00e9 (2).txt"
    assert unicodedata.normalize("NFC", entries[2].out_rel) == "caf\u00e9 (3).txt"


def test_flat_mode_numbers_clashes():
    entries = [E("a/Untitled.gdoc", "document"), E("b/Untitled.gdoc", "document"), E("c/Untitled.gdoc", "document")]
    inventory.allocate(entries, ["a", "b", "c"], flat=True, formats={})
    assert sorted(e.out_rel for e in entries) == [
        "Untitled (2).docx", "Untitled (from Google Docs).docx", "Untitled.docx"]
    assert all("/" not in e.out_rel for e in entries)


def test_report_name_is_reserved():
    entries = [E("gdocout-report.html")]
    inventory.allocate(entries, [], flat=False, formats={})
    assert entries[0].out_rel == "gdocout-report (2).html"


def test_names_from_an_earlier_run_stay_put():
    old = E("Doc.gdoc", "document")
    old.out_rel = "Doc.docx"
    new = E("Doc.docx")
    inventory.allocate([old, new], [], flat=False, formats={}, taken_before=["Doc.docx"])
    assert old.out_rel == "Doc.docx" and new.out_rel == "Doc (2).docx"


def test_folder_names_are_reserved_in_mirror_mode():
    entries = [E("x/Plans.gdoc", "document")]
    inventory.allocate(entries, ["x", "x/Plans.docx"], flat=False, formats={})
    assert entries[0].out_rel == "x/Plans (from Google Docs).docx"


def test_format_choice():
    entries = [E("Doc.gdoc", "document"), E("Sheet.gsheet", "spreadsheet")]
    inventory.allocate(entries, [], flat=False, formats={"document": "pdf"})
    assert [e.out_rel for e in entries] == ["Doc.pdf", "Sheet.xlsx"]
