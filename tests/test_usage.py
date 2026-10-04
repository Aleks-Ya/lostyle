from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from helpers import make_odf
from test_copier import PNG, attr, find, one, styles_root

from lostyle import StyleRef, purge_unused, style_usage, unused_styles
from lostyle.cli import main

STYLES = """
<style:default-style style:family="graphic"/>
<draw:gradient draw:name="G1"/>
<draw:gradient draw:name="G2"/>
<draw:gradient draw:name="G3"/>
<draw:marker draw:name="M1" svg:viewBox="0 0 1 1" svg:d="M0 0"/>
<draw:fill-image draw:name="Pic" xlink:href="Pictures/p.png" xlink:type="simple"/>
<style:style style:name="standard" style:family="graphic"/>
<style:style style:name="Used" style:family="graphic" style:parent-style-name="standard">
  <style:graphic-properties draw:fill-gradient-name="G1" draw:marker-end="M1"/></style:style>
<style:style style:name="Unused" style:family="graphic" style:parent-style-name="Used">
  <style:graphic-properties draw:fill-gradient-name="G2" draw:fill-image-name="Pic"/></style:style>
<style:style style:name="Cite" style:family="text"/>
<text:notes-configuration text:note-class="footnote" text:citation-style-name="Cite"/>
"""
AUTO = """
<style:page-layout style:name="PM0"/>
<style:page-layout style:name="PM1"/>
<style:style style:name="gr9" style:family="graphic" style:parent-style-name="Used"/>
"""
MASTERS = """
<style:master-page style:name="Main" style:page-layout-name="PM0"/>
<style:master-page style:name="Spare" style:page-layout-name="PM1"><draw:rect draw:style-name="gr9"/></style:master-page>
"""
BODY = """<office:drawing><draw:page draw:name="p" draw:master-page-name="Main">
<draw:rect draw:style-name="gr1"/><draw:rect draw:style-name="Used"/>
<draw:frame><draw:image xlink:href="Pictures/body.png"/></draw:frame>
</draw:page></office:drawing>"""

UNUSED = [
    StyleRef("fill-image", "Pic"),
    StyleRef("gradient", "G2"),
    StyleRef("gradient", "G3"),
    StyleRef("graphic", "Unused"),
    StyleRef("graphic", "gr9", automatic=True),
    StyleRef("master-page", "Spare"),
    StyleRef("page-layout", "PM1", automatic=True),
]


def make_doc(path: Path, flat: bool = False) -> Path:
    return make_odf(
        path,
        styles=STYLES,
        auto_styles=AUTO,
        masters=MASTERS,
        content_auto_styles='<style:style style:name="gr1" style:family="graphic" style:parent-style-name="Used"/>',
        body=BODY,
        files=None if flat else {"Pictures/p.png": PNG, "Pictures/body.png": PNG},
        flat=flat,
    )


def test_style_usage_counts_all_references(tmp_path: Path) -> None:
    usage = style_usage(make_doc(tmp_path / "doc.odg"))
    # Unused's parent, gr9's parent (styles.xml), gr1's parent (content.xml), body shape
    assert usage[StyleRef("graphic", "Used")] == 4
    assert usage[StyleRef("graphic", "Unused")] == 0
    assert usage[StyleRef("gradient", "G2")] == 1  # from an unused style, still counted
    assert usage[StyleRef("gradient", "G3")] == 0
    assert not any(ref.automatic for ref in usage)


@pytest.mark.parametrize("flat", [False, True])
def test_unused_styles(tmp_path: Path, flat: bool) -> None:
    doc = make_doc(tmp_path / ("doc.fodg" if flat else "doc.odg"), flat=flat)
    assert unused_styles(doc) == UNUSED


def test_purge_deletes_unused_styles_and_their_pictures(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    result = purge_unused(doc)
    assert result.deleted == UNUSED
    assert result.files == ["Pictures/p.png"]
    root = styles_root(doc)
    assert {attr(e, "style:name") for e in find(root, "//style:style")} == {
        "standard",
        "Used",
        "Cite",  # only mentioned by Writer's notes configuration
    }
    assert [attr(e, "draw:name") for e in find(root, "//draw:gradient")] == ["G1"]
    one(root, "//draw:marker[@draw:name='M1']")
    one(root, "//style:default-style")
    with zipfile.ZipFile(doc) as zf:
        names = zf.namelist()
        manifest = zf.read("META-INF/manifest.xml").decode()
    assert "Pictures/p.png" not in names
    assert "Pictures/p.png" not in manifest
    assert "Pictures/body.png" in names
    assert "deleted 7 unused style(s) and 1 embedded file(s)" in str(result)
    assert purge_unused(doc).deleted == []


def test_keep_preserves_styles_and_their_dependencies(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    template = make_odf(
        tmp_path / "template.odg",
        styles='<style:style style:name="Unused" style:family="graphic"/>',
    )
    result = purge_unused(doc, keep=template)
    assert StyleRef("graphic", "Unused") not in result.deleted
    assert StyleRef("gradient", "G2") not in result.deleted
    assert StyleRef("fill-image", "Pic") not in result.deleted
    assert result.files == []

    keep = [StyleRef("gradient", "G3"), StyleRef("graphic", "not in the document")]
    assert StyleRef("gradient", "G3") not in unused_styles(make_doc(tmp_path / "b.odg"), keep=keep)


def test_automatic_only_and_families(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    assert unused_styles(doc, automatic_only=True) == [
        StyleRef("graphic", "gr9", automatic=True),
        StyleRef("page-layout", "PM1", automatic=True),
    ]
    assert unused_styles(doc, families=["gradient"]) == [
        StyleRef("gradient", "G2"),
        StyleRef("gradient", "G3"),
    ]


def test_nothing_to_purge_leaves_file_untouched(tmp_path: Path) -> None:
    doc = make_odf(tmp_path / "doc.odg")
    before = doc.read_bytes()
    result = purge_unused(doc)
    assert str(result) == "nothing to purge"
    assert doc.read_bytes() == before


def test_impress_master_keeps_its_presentation_styles(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.odp",
        doc_type="presentation",
        styles="""
<style:style style:name="Main-outline1" style:family="presentation"/>
<style:style style:name="Main-outline2" style:family="presentation" style:parent-style-name="Main-outline1"/>
<style:style style:name="Spare-title" style:family="presentation"/>
""",
        masters='<style:master-page style:name="Main"/><style:master-page style:name="Spare"/>',
        body='<office:presentation><draw:page draw:name="p" draw:master-page-name="Main"/></office:presentation>',
    )
    assert unused_styles(doc) == [
        StyleRef("master-page", "Spare"),
        StyleRef("presentation", "Spare-title"),
    ]


def test_cli_list_usage_and_purge(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    assert main(["list", str(doc), "-f", "graphic", "--usage"]) == 0
    assert "    4  graphic          Used\n" in capsys.readouterr().out
    assert main(["list", str(doc), "--unused", "--automatic"]) == 0
    out = capsys.readouterr().out
    assert "graphic          Unused\n" in out
    assert "gr9  [automatic]" in out
    assert "Used\n" not in out.replace("Unused\n", "")

    out_doc = tmp_path / "out.odg"
    assert main(["purge", str(doc), "-f", "gradient", "-o", str(out_doc)]) == 0
    assert "deleted 2 unused style(s)" in capsys.readouterr().out
    assert len(find(styles_root(out_doc), "//draw:gradient")) == 1
    assert main(["purge", str(doc), str(out_doc), "-o", str(tmp_path / "x.odg")]) == 1
    assert "exactly one document" in capsys.readouterr().err
