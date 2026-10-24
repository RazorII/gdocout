import json

import pytest

from gdocout import google


def stub_bytes(**kw):
    return json.dumps({"": "WARNING!", **kw}).encode()


def test_stub_with_doc_id():
    assert google.parse_stub(stub_bytes(doc_id="1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcd", resource_key="", email="a@b.com")) == (
        "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcd", "", "a@b.com")


def test_stub_keeps_resource_key():
    assert google.parse_stub(stub_bytes(doc_id="1abcdefghijk", resource_key="0-AbC_d")) == ("1abcdefghijk", "0-AbC_d", "")


def test_older_stub_with_url():
    data = stub_bytes(url="https://docs.google.com/document/d/1abcdefghijk/edit?usp=drivesdk&resourcekey=0-key", email="x")
    assert google.parse_stub(data) == ("1abcdefghijk", "0-key", "")  # "x" isn't an email address, so no account


def test_older_stub_with_resource_id():
    assert google.parse_stub(stub_bytes(resource_id="document:1abcdefghijk")) == ("1abcdefghijk", "", "")


def test_stub_with_byte_order_mark():
    assert google.parse_stub(b"\xef\xbb\xbf" + stub_bytes(doc_id="1abcdefghijk"))[0] == "1abcdefghijk"


@pytest.mark.parametrize("data", [b"not json", b"[]", stub_bytes(email="x"), stub_bytes(doc_id="../../etc/passwd")])
def test_bad_stubs_are_refused(data):
    with pytest.raises(google.StubError):
        google.parse_stub(data)


def test_odd_resource_key_is_dropped_not_sent():
    assert google.parse_stub(stub_bytes(doc_id="1abcdefghijk", resource_key="a b&c=d"))[1] == ""


@pytest.mark.parametrize("url,expected", [
    ("https://docs.google.com/document/d/1abcdefghijk/edit", ("document", "1abcdefghijk", "")),
    ("docs.google.com/spreadsheets/d/1abcdefghijk/edit#gid=0", ("spreadsheet", "1abcdefghijk", "")),
    ("https://docs.google.com/presentation/u/0/d/1abcdefghijk/view", ("presentation", "1abcdefghijk", "")),
    ("https://docs.google.com/document/d/1abcdefghijk/edit?resourcekey=0-xyz", ("document", "1abcdefghijk", "0-xyz")),
    ("https://drive.google.com/open?id=1abcdefghijk", ("", "1abcdefghijk", "")),
    ("https://drive.google.com/file/d/1abcdefghijk/view", ("", "1abcdefghijk", "")),
    ("https://www.google.com/maps/d/viewer?mid=1MapIdExample123", ("map", "1MapIdExample123", "")),
    ("https://example.com/document/d/1abcdefghijk", None),
])
def test_parse_link(url, expected):
    assert google.parse_link(url) == expected


def test_export_url_carries_the_key_both_ways():
    kind = google.KINDS["document"]
    assert google.export_url(kind, "1abc", "docx", "0-k").endswith("/document/d/1abc/export?format=docx&resourcekey=0-k")
    assert google.export_url(google.KINDS["presentation"], "1abc", "pptx", "0-k").endswith("/export/pptx?resourcekey=0-k")
    assert google.key_header("1abc", "0-k") == {"X-Goog-Drive-Resource-Keys": "1abc/0-k"}
    assert google.key_header("1abc", "") == {}


def test_every_kind_with_exports_has_a_valid_default():
    for kind in google.KINDS.values():
        if kind.exports:
            assert kind.default in kind.exports
            assert kind.view
        else:
            assert kind.default is None and kind.why_none


def test_account_is_kept_and_checked():
    assert google.parse_stub(stub_bytes(doc_id="1abcdefghijk", email="owner@example.com"))[2] == "owner@example.com"
    assert google.parse_stub(stub_bytes(doc_id="1abcdefghijk", email="x&authuser=evil"))[2] == ""


def test_as_account_adds_authuser():
    assert google.as_account("https://d/x/export?format=docx", "a@b.com") == "https://d/x/export?format=docx&authuser=a@b.com"
    assert google.as_account("https://d/x/export/pptx", "") == "https://d/x/export/pptx"
