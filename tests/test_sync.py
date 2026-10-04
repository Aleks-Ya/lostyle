from __future__ import annotations

from pathlib import Path

import pytest
from helpers import make_odf
from test_copier import attr, find, one, styles_root
from test_rename import content_root

from lostyle import StyleRef, audit_documents, find_documents, parse_mapping, sync_documents
from lostyle.cli import main

TEMPLATE_STYLES = """
<style:style style:name="standard" style:family="graphic"/>
<style:style style:name="Line_3a__20_Association" style:display-name="Line: Association" style:family="graphic" style:parent-style-name="standard">
  <style:graphic-properties svg:stroke-color="#3465a4"/></style:style>
<style:style style:name="Spare" style:family="graphic" style:parent-style-name="standard"/>
"""
MASTER = """<style:master-page style:name="Main" style:page-layout-name="PM0">
<draw:rect draw:style-name="gr1"/></style:master-page>"""
TEMPLATE_AUTO = """
<style:page-layout style:name="PM0"><style:page-layout-properties fo:page-width="42cm"/></style:page-layout>
<style:style style:name="gr1" style:family="graphic" style:parent-style-name="standard"/>
"""
DOC_STYLES = """
<style:style style:name="standard" style:family="graphic"/>
<style:style style:name="Old_20_line" style:display-name="Old line" style:family="graphic">
  <style:graphic-properties svg:stroke-color="#000000"/></style:style>
<style:style style:name="Leftover" style:family="graphic"/>
"""
DOC_AUTO = """
<style:page-layout style:name="PM0"><style:page-layout-properties fo:page-width="21cm"/></style:page-layout>
<style:style style:name="gr1" style:family="graphic"/>
"""
DOC_BODY = """<office:drawing><draw:page draw:name="p" draw:master-page-name="Main">
<draw:line draw:style-name="Old_20_line"/></draw:page></office:drawing>"""
MAPPING = parse_mapping({"graphic": {"Line: Association": ["Old line"]}})


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    template = make_odf(
        tmp_path / "template.otg",
        doc_type="graphics-template",
        styles=TEMPLATE_STYLES,
        auto_styles=TEMPLATE_AUTO,
        masters=MASTER,
    )
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / ".hidden").mkdir()
    make_odf(docs / "a.odg", styles=DOC_STYLES, auto_styles=DOC_AUTO, masters=MASTER, body=DOC_BODY)
    make_odf(docs / "sub" / "b.odg")
    make_odf(docs / ".hidden" / "c.odg")
    make_odf(docs / "sheet.ods", doc_type="spreadsheet")
    (docs / "broken.odg").write_text("not a document")
    (docs / "notes.txt").write_text("not a document either")
    return template, docs


def names(path: Path, family: str = "graphic") -> set[str]:
    root = styles_root(path)
    return {
        attr(e, "style:name") or ""
        for e in find(root, f"//office:styles/style:style[@style:family='{family}']")
    }


def test_find_documents(tree: tuple[Path, Path]) -> None:
    template, docs = tree
    assert [p.relative_to(docs).as_posix() for p in find_documents([docs])] == [
        "a.odg",
        "broken.odg",
        "sheet.ods",
        "sub/b.odg",
    ]
    assert find_documents([template, docs / "a.odg", docs / "a.odg"]) == [template, docs / "a.odg"]


def test_sync_maps_copies_and_purges(tree: tuple[Path, Path]) -> None:
    template, docs = tree
    results = {
        r.path.name: r
        for r in sync_documents(template, [docs, template], mapping=MAPPING, purge=True)
    }

    assert results["broken.odg"].error is not None
    assert results["sheet.ods"].skipped is not None
    assert "spreadsheet" in results["sheet.ods"].summary()
    assert results["template.otg"].skipped == "the template itself"

    a = docs / "a.odg"
    assert results["a.odg"].changed
    assert names(a) == {"standard", "Line_3a__20_Association", "Spare"}  # Leftover purged
    line = one(content_root(a), "//draw:line")
    assert attr(line, "draw:style-name") == "Line_3a__20_Association"
    root = styles_root(a)
    props = one(
        root, "//style:style[@style:name='Line_3a__20_Association']/style:graphic-properties"
    )
    assert attr(props, "svg:stroke-color") == "#3465a4"
    # the template's master replaced the document's; its old automatic styles are gone
    master = one(root, "//style:master-page[@style:name='Main']")
    layout = attr(master, "style:page-layout-name")
    assert [attr(e, "style:name") for e in find(root, "//style:page-layout")] == [layout]
    width = one(root, f"//style:page-layout[@style:name='{layout}']/style:page-layout-properties")
    assert attr(width, "fo:page-width") == "42cm"
    assert len(find(root, "//office:automatic-styles/style:style")) == 1
    summary = results["a.odg"].summary()
    assert "1 old name(s) mapped" in summary
    assert "unused deleted" in summary

    b = docs / "sub" / "b.odg"
    assert names(b) == {"standard", "Line_3a__20_Association", "Spare"}

    # a second run finds nothing to do and leaves the files alone
    before = {p: p.read_bytes() for p in (a, b)}
    again = sync_documents(template, [docs], mapping=MAPPING, purge=True)
    assert not any(r.changed for r in again)
    assert {r.path.name: r.summary().split(": ", 1)[1] for r in again if r.error is None}[
        "a.odg"
    ] == "up to date"
    assert {p: p.read_bytes() for p in (a, b)} == before


def test_without_purge_only_leftover_automatic_styles_go(tree: tuple[Path, Path]) -> None:
    template, docs = tree
    sync_documents(template, [docs / "a.odg"])
    a = docs / "a.odg"
    assert names(a) == {"standard", "Line_3a__20_Association", "Spare", "Old_20_line", "Leftover"}
    assert len(find(styles_root(a), "//style:page-layout")) == 1


def test_dry_run_saves_nothing(tree: tuple[Path, Path]) -> None:
    template, docs = tree
    a = docs / "a.odg"
    before = a.read_bytes()
    [result] = sync_documents(template, [a], mapping=MAPPING, purge=True, dry_run=True)
    assert result.changed
    assert a.read_bytes() == before


def test_audit(tree: tuple[Path, Path]) -> None:
    template, docs = tree
    audit = audit_documents(template, [docs])
    assert audit.styles == {StyleRef("graphic", "Old_20_line"): [docs / "a.odg"]}  # not Leftover
    assert audit.documents == 2
    assert {r.path.name for r in audit.skipped} == {"broken.odg", "sheet.ods"}
    text = audit.format(verbose=True)
    assert "graphic\n     1  Old line\n" in text
    assert f"          {docs / 'a.odg'}\n" in text
    assert text.endswith("1 style(s) used in 1 of 2 document(s) are not in the template")

    before = (docs / "a.odg").read_bytes()
    audit = audit_documents(template, [docs / "a.odg"], mapping=MAPPING)
    assert not audit
    assert audit.format() == "all styles used by 1 document(s) are in the template"
    assert (docs / "a.odg").read_bytes() == before  # audit saves nothing


def test_cli_sync_and_audit(tree: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    template, docs = tree
    mapping = docs.parent / "styles.toml"
    mapping.write_text('[graphic]\n"Line: Association" = "Old line"\n', encoding="utf-8")

    assert main(["audit", str(template), str(docs), "--exit-code"]) == 1
    assert "Old line" in capsys.readouterr().out
    assert main(["audit", str(template), str(docs), "--map", str(mapping), "--exit-code"]) == 0
    capsys.readouterr()

    args = ["sync", str(template), str(docs), "--map", str(mapping)]
    assert main([*args, "--dry-run"]) == 1  # broken.odg
    captured = capsys.readouterr()
    assert "broken.odg: error:" in captured.err
    assert captured.out.rstrip().endswith(
        "4 document(s): 2 would be updated, 0 up to date, 1 skipped, 1 failed"
    )
    (docs / "broken.odg").unlink()
    assert main([*args, "-v", "--purge"]) == 0
    out = capsys.readouterr().out
    assert "graphic:Old_20_line -> Line_3a__20_Association" not in out  # merged, not renamed
    assert "Old_20_line -> Line_3a__20_Association;" in out
    assert "      graphic:Leftover\n" in out
    assert out.rstrip().endswith("3 document(s): 2 updated, 0 up to date, 1 skipped, 0 failed")
    assert main(args) == 0
    assert "0 updated, 2 up to date" in capsys.readouterr().out
