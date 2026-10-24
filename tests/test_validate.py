import zipfile

from conftest import HTML_LOGIN, make_docx, make_kmz, make_pptx, make_xlsx

from gdocout import validate


def put(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_docx_facts(tmp_path):
    c = validate.check_file(put(tmp_path, "a.docx", make_docx("one two three")), "docx")
    assert c.ok and c.facts["words"] == 3 and c.facts["paragraphs"] == 1 and not c.warnings


def test_empty_docx_is_valid_but_warned(tmp_path):
    c = validate.check_file(put(tmp_path, "a.docx", make_docx("")), "docx")
    assert c.ok and c.warnings


def test_xlsx_lists_every_sheet(tmp_path):
    c = validate.check_file(put(tmp_path, "a.xlsx", make_xlsx(("A", "B", "C"))), "xlsx")
    assert c.ok and c.facts["sheets"] == 3 and c.facts["sheet_names"] == ["A", "B", "C"]


def test_pptx_counts_slides(tmp_path):
    c = validate.check_file(put(tmp_path, "a.pptx", make_pptx(5)), "pptx")
    assert c.ok and c.facts["slides"] == 5


def test_kmz_counts_places(tmp_path):
    c = validate.check_file(put(tmp_path, "a.kmz", make_kmz()), "kmz")
    assert c.ok and c.facts["placemarks"] == 2


def test_web_page_saved_as_docx_is_rejected(tmp_path):
    c = validate.check_file(put(tmp_path, "a.docx", HTML_LOGIN), "docx")
    assert not c.ok and "web page" in c.problem


def test_empty_file_is_rejected(tmp_path):
    assert not validate.check_file(put(tmp_path, "a.docx", b""), "docx").ok


def test_truncated_docx_is_rejected(tmp_path):
    data = make_docx()
    assert not validate.check_file(put(tmp_path, "a.docx", data[: len(data) // 2]), "docx").ok


def test_corrupted_member_fails_its_checksum(tmp_path):
    p = tmp_path / "a.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document xmlns:w='x'>" + "a" * 200 + "</w:document>")
    raw = bytearray(p.read_bytes())
    i = raw.find(b"aaaa")
    raw[i] = ord("b")
    p.write_bytes(bytes(raw))
    c = validate.check_file(p, "docx")
    assert not c.ok and "damaged" in c.problem


def test_wrong_kind_of_office_file_is_rejected(tmp_path):
    c = validate.check_file(put(tmp_path, "a.docx", make_xlsx()), "docx")
    assert not c.ok and "word/document.xml" in c.problem


def test_pdf_needs_its_end_marker(tmp_path):
    good = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"
    assert validate.check_file(put(tmp_path, "a.pdf", good), "pdf").facts == {"pages": 1}
    assert not validate.check_file(put(tmp_path, "b.pdf", good[:-7]), "pdf").ok


def test_sha256(tmp_path):
    p = put(tmp_path, "x", b"abc")
    assert validate.sha256(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
