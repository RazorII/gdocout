from gdocout import google, inventory
from gdocout.model import Entry


def E(rel, kind="file"):
    return Entry(rel, kind, "." + rel.rsplit(".", 1)[-1])


def test_wanted_formats_main_first_and_defaults():
    assert inventory.wanted_formats(google.KINDS["document"], {}) == ["docx"]
    assert inventory.wanted_formats(google.KINDS["document"], {"document": ["pdf", "docx", "pdf", "bogus"]}) == ["pdf", "docx"]


def test_pdf_also_and_only():
    also = inventory.apply_pdf({}, "also")
    assert also["document"] == ["docx", "pdf"] and also["spreadsheet"] == ["xlsx", "pdf"]
    assert also["presentation"] == ["pptx", "pdf"] and also["drawing"] == ["pdf"]
    only = inventory.apply_pdf({"document": ["odt"]}, "only")
    assert only["document"] == ["pdf"] and "map" not in only


def test_extra_formats_get_their_own_safe_names():
    entries = [E("w/Plan.gdoc", "document"), E("w/Plan.pdf")]
    inventory.allocate(entries, ["w"], flat=False, formats={"document": ["docx", "pdf"]})
    doc, real_pdf = entries
    assert doc.out_rel == "w/Plan.docx" and doc.fmt == "docx"
    assert real_pdf.out_rel == "w/Plan.pdf"
    assert doc.extra == {"pdf": {"o": "w/Plan (from Google Docs).pdf", "st": "pending"}}
