"""Against the real Google, on Google's own public sample files. Off unless GDOCOUT_NETWORK_TESTS=1.

These are the sample files Google's developer quickstarts use, shared "anyone
with the link". If Google ever takes one down, the test says which.
"""

import os

import pytest

from gdocout import fetch
from gdocout.model import CONVERTED, NOT_FOUND, Entry

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(os.environ.get("GDOCOUT_NETWORK_TESTS") != "1", reason="set GDOCOUT_NETWORK_TESTS=1 to talk to Google"),
]

SAMPLES = [
    ("document", "195j9eDD3ccgjQRttHhJPymLJUCOUjs-jmwTrekvdjFE", "docx", "words"),
    ("document", "195j9eDD3ccgjQRttHhJPymLJUCOUjs-jmwTrekvdjFE", "pdf", None),
    ("spreadsheet", "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms", "xlsx", "sheets"),
    ("presentation", "1EAYk18WDjIG-zp_0vLm3CsfQh_i8eXc67Jo2O9C6Vuc", "pptx", "slides"),
]


@pytest.mark.parametrize("kind,gid,fmt,fact", SAMPLES)
def test_public_samples_download(tmp_path, kind, gid, fmt, fact):
    e = Entry(f"x.{fmt}", kind, "", gid=gid, fmt=fmt)
    out = fetch.export(fetch.Http(timeout=60), e, tmp_path / f"x.{fmt}")
    assert out.status == CONVERTED, out.note
    if fact:
        assert out.facts.get(fact)


def test_made_up_id_is_not_found(tmp_path):
    e = Entry("x.docx", "document", "", gid="1zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", fmt="docx")
    out = fetch.export(fetch.Http(timeout=60), e, tmp_path / "x.docx")
    assert out.status == NOT_FOUND
