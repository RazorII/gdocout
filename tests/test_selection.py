import pytest

from gdocout.model import Entry
from gdocout.selection import Selection, parse_types, read_list, type_matches


def F(rel):
    ext = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel.rsplit("/", 1)[-1] else ""
    return Entry(rel, "file", ext)


def G(rel, kind):
    return Entry(rel, kind, ".g")


def test_parse_types_accepts_aliases_and_extensions():
    assert parse_types(["pdf, photos", ".HEIC;docs"]) == ["pdf", "images", ".heic", "google-docs"]


def test_parse_types_refuses_unknown_words():
    with pytest.raises(ValueError, match="unknown type"):
        parse_types(["spreadshets"])


@pytest.mark.parametrize("entry,word,expected", [
    (F("a.PDF"), "pdf", True),
    (F("a.docx"), "documents", True),
    (G("a.gdoc", "document"), "documents", True),  # a category covers the matching Google files
    (G("a.gdoc", "document"), "google-docs", True),
    (G("a.gsheet", "spreadsheet"), "google-docs", False),
    (G("a.gform", "form"), "google", True),
    (F("a.heic"), ".heic", True),
    (G("a.gdoc", "document"), ".gdoc", False),
    (F("a.xyz"), "other", True),
    (F("a.jpg"), "other", False),
])
def test_type_matches(entry, word, expected):
    assert type_matches(entry, word) is expected


def test_patterns_folders_and_names():
    sel = Selection(exclude=["Photos/", "*.tmp"])
    assert sel.why_left_out(F("Photos/2019/a.jpg"))
    assert sel.why_left_out(F("x/notes.TMP"))
    assert sel.why_left_out(F("PhotosOld/a.jpg")) is None
    assert Selection(include=["work/"]).why_left_out(F("Work/plan.docx")) is None
    assert Selection(include=["*budget*"]).why_left_out(F("Home/Budget 2024.xlsx")) is None
    assert Selection(include=["*budget*"]).why_left_out(F("Home/plan.xlsx"))


def test_only_and_skip():
    only = Selection(only=["pdf", "google-docs"])
    assert only.why_left_out(F("a.pdf")) is None and only.why_left_out(G("b.gdoc", "document")) is None
    assert only.why_left_out(F("c.jpg")) and only.why_left_out(G("d.gsheet", "spreadsheet"))
    skip = Selection(skip=["video"])
    assert skip.why_left_out(F("a.mov")) and skip.why_left_out(F("b.pdf")) is None


def test_copy_and_convert_switches():
    assert Selection(copy=False).why_left_out(F("a.pdf"))
    assert Selection(copy=False).why_left_out(G("a.gdoc", "document")) is None
    assert Selection(convert=False).why_left_out(G("a.gdoc", "document"))


def test_files_from_list(tmp_path):
    lst = tmp_path / "list.txt"
    lst.write_text("# wanted\n./Work/Plan.gdoc\nPhotos/\n")
    sel = Selection(files=read_list(lst))
    assert sel.why_left_out(G("Work/Plan.gdoc", "document")) is None
    assert sel.why_left_out(F("Photos/2019/a.jpg")) is None
    assert sel.why_left_out(F("Work/Other.pdf"))


def test_inactive_selection_is_everything():
    assert not Selection().active and Selection().as_text() == "everything"
