import json

import pytest
from conftest import stub

from gdocout import cli, fetch, report
from gdocout.model import Entry


def test_report_cannot_be_broken_by_a_filename(tmp_path):
    nasty = '</script><img src=x onerror="alert(1)">.txt'
    out = report.write(tmp_path / "r.html", [Entry(nasty, "file", ".txt", status="copied", out_rel=nasty)], {"source": "/s"})
    html = out.read_text()
    assert "</script><img" not in html
    data = html.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert json.loads(data)["rows"][0]["p"] == nasty


def test_scan_json(tmp_path, capsys):
    stub(tmp_path / "Doc.gdoc", "1abcdefghijk")
    assert cli.main(["scan", str(tmp_path), "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["to_export"] == 1 and s["google_by_kind"] == {"document": 1}


@pytest.mark.parametrize("arg,msg", [("document=xlsx", "can't be downloaded as"), ("form=pdf", "unknown kind"), ("docx", "KIND=FMT")])
def test_bad_format_choices(tmp_path, capsys, arg, msg):
    assert cli.main(["scan", str(tmp_path), "--format", arg]) == 2
    assert msg in capsys.readouterr().err


def test_copy_needs_a_destination(tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(["copy", str(tmp_path)])
    assert e.value.code == 2


def test_link_command(tmp_path, fake_google, monkeypatch, capsys):
    real_http = fetch.Http
    monkeypatch.setattr(cli.fetch, "Http", lambda: real_http(timeout=10, rewrite=fake_google.rewrite))
    code = cli.main(["link", "https://docs.google.com/document/d/okdoc9aaaaaa/edit",
                     "https://docs.google.com/document/d/dloff9aaaaaa/edit",
                     "https://drive.google.com/open?id=oksheet9aaaa", "--dest", str(tmp_path), "--json"])
    res = json.loads(capsys.readouterr().out)["results"]
    assert code == 1
    assert res[0]["status"] == "converted" and res[0]["file"].endswith(".docx")
    assert res[1]["status"] == "download_off"
    assert res[2]["status"] == "converted"  # an open?id= link: the first type that works
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".docx", ".docx"]
