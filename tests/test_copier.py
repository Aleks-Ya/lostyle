from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pytest
from helpers import make_odf
from lxml import etree

from lostyle import OdfPackage, StyleNotFoundError, StyleRef, copy_all_styles, copy_styles
from lostyle.cli import main
from lostyle.ns import NS

PNG = b"\x89PNG\r\n\x1a\nfake-image-data"

SRC_FONTS = (
    '<style:font-face style:name="Liberation Sans" svg:font-family="&apos;Liberation Sans&apos;"/>'
)
SRC_STYLES = """
<style:default-style style:family="graphic"><style:graphic-properties svg:stroke-color="#3465a4"/></style:default-style>
<draw:gradient draw:name="Sunset" draw:display-name="Sunset glow" draw:style="linear" draw:start-color="#ff0000" draw:end-color="#ffff00"/>
<draw:marker draw:name="Arrow" svg:viewBox="0 0 20 30" svg:d="M10 0l-10 30h20z"/>
<draw:stroke-dash draw:name="Dots" draw:style="rect" draw:dots1="1"/>
<draw:fill-image draw:name="Pic" xlink:href="Pictures/p.png" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>
<style:style style:name="standard" style:family="graphic"><style:graphic-properties draw:fill-color="#729fcf"/></style:style>
<style:style style:name="Fancy" style:display-name="Fancy Box" style:family="graphic" style:parent-style-name="standard">
  <style:graphic-properties draw:fill="gradient" draw:fill-gradient-name="Sunset" draw:marker-end="Arrow" draw:stroke="dash" draw:stroke-dash="Dots"/>
  <style:text-properties style:font-name="Liberation Sans"/>
</style:style>
<style:style style:name="Textured" style:family="graphic" style:parent-style-name="standard">
  <style:graphic-properties draw:fill="bitmap" draw:fill-image-name="Pic"/>
</style:style>
"""
SRC_AUTO = """
<style:page-layout style:name="PM0"><style:page-layout-properties fo:page-width="21cm"/></style:page-layout>
<style:style style:name="Mdp1" style:family="drawing-page"><style:drawing-page-properties draw:fill="gradient" draw:fill-gradient-name="Sunset"/></style:style>
<style:style style:name="gr1" style:family="graphic" style:parent-style-name="Fancy"><style:graphic-properties draw:fill-color="#000000"/></style:style>
"""
SRC_MASTERS = """
<style:master-page style:name="Default" style:page-layout-name="PM0" draw:style-name="Mdp1">
  <draw:rect draw:style-name="gr1" svg:width="1cm" svg:height="1cm"/>
</style:master-page>
"""


def make_src(path: Path, flat: bool = False) -> Path:
    return make_odf(
        path,
        fonts=SRC_FONTS,
        styles=SRC_STYLES,
        auto_styles=SRC_AUTO,
        masters=SRC_MASTERS,
        files={"Pictures/p.png": PNG},
        flat=flat,
    )


def make_dst(path: Path, flat: bool = False) -> Path:
    return make_odf(
        path,
        styles="""
<style:style style:name="standard" style:family="graphic"><style:graphic-properties draw:fill-color="#ffffff"/></style:style>
<style:style style:name="Fancy" style:family="graphic"><style:graphic-properties draw:fill-color="#00ff00"/></style:style>
""",
        auto_styles="""
<style:page-layout style:name="PM0"/>
<style:style style:name="Mdp1" style:family="drawing-page"><style:drawing-page-properties draw:fill="none"/></style:style>
""",
        masters='<style:master-page style:name="Mine" style:page-layout-name="PM0" draw:style-name="Mdp1"/>',
        content_auto_styles='<style:style style:name="gr1" style:family="graphic"/>',
        flat=flat,
    )


def styles_root(path: Path) -> etree._Element:
    return OdfPackage.open(path).styles_root


def find(root: etree._Element, xpath: str) -> list[etree._Element]:
    result = root.xpath(xpath, namespaces=NS)
    assert isinstance(result, list)
    return [e for e in result if isinstance(e, etree._Element)]


def one(root: etree._Element, xpath: str) -> etree._Element:
    found = find(root, xpath)
    assert len(found) == 1, f"{xpath}: {len(found)} matches"
    return found[0]


def attr(el: etree._Element, name: str) -> str | None:
    prefix, local = name.split(":")
    return el.get(f"{{{NS[prefix]}}}{local}")


# ---------------------------------------------------------------- graphic styles
def test_copies_style_with_all_dependencies(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg")
    content_before = zipfile.ZipFile(dst).read("content.xml")

    report = copy_styles(src, dst, names=["Fancy"])

    root = styles_root(dst)
    one(root, "//office:styles/style:style[@style:name='Fancy']")
    one(root, "//office:styles/style:style[@style:name='standard']")
    one(root, "//office:styles/draw:gradient[@draw:name='Sunset']")
    one(root, "//office:styles/draw:marker[@draw:name='Arrow']")
    one(root, "//office:styles/draw:stroke-dash[@draw:name='Dots']")
    one(root, "//office:font-face-decls/style:font-face[@style:name='Liberation Sans']")
    assert not find(root, "//style:style[@style:name='Textured']")
    assert not find(root, "//draw:fill-image")
    assert StyleRef("graphic", "Fancy") in report.copied
    assert not report.unresolved
    # dependencies are inserted before their dependents
    assert report.copied.index(StyleRef("gradient", "Sunset")) < report.copied.index(
        StyleRef("graphic", "Fancy")
    )
    assert zipfile.ZipFile(dst).read("content.xml") == content_before


def test_lookup_by_display_name(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg")
    copy_styles(src, dst, names=["Fancy Box"], include_dependencies=False)
    one(styles_root(dst), "//style:style[@style:name='Fancy']")


def test_no_deps_reports_unresolved(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg")
    report = copy_styles(src, dst, names=["Fancy"], include_dependencies=False)
    assert report.copied == [StyleRef("graphic", "Fancy")]
    assert {m.value for m in report.unresolved} == {
        "standard",
        "Sunset",
        "Arrow",
        "Dots",
        "Liberation Sans",
    }


def test_overwrite_replaces_existing(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_dst(tmp_path / "dst.odg")
    report = copy_styles(src, dst, names=["Fancy"])
    root = styles_root(dst)
    fancy = one(root, "//office:styles/style:style[@style:name='Fancy']")
    assert attr(fancy, "style:parent-style-name") == "standard"
    assert StyleRef("graphic", "Fancy") in report.overwritten
    assert StyleRef("graphic", "standard") in report.overwritten
    std = one(root, "//office:styles/style:style[@style:name='standard']/style:graphic-properties")
    assert attr(std, "draw:fill-color") == "#729fcf"


def test_skip_keeps_existing_and_its_deps_are_not_copied(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_dst(tmp_path / "dst.odg")
    report = copy_styles(src, dst, names=["Fancy"], on_conflict="skip")
    root = styles_root(dst)
    props = one(root, "//style:style[@style:name='Fancy']/style:graphic-properties")
    assert attr(props, "draw:fill-color") == "#00ff00"
    assert report.skipped == [StyleRef("graphic", "Fancy")]
    assert not find(root, "//draw:gradient")


def test_rename_copies_under_new_names(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_dst(tmp_path / "dst.odg")
    report = copy_styles(src, dst, names=["Fancy"], on_conflict="rename")
    root = styles_root(dst)
    assert len(find(root, "//style:style[@style:family='graphic']")) == 4
    new = one(root, "//style:style[@style:name='Fancy_1']")
    assert attr(new, "style:display-name") == "Fancy Box (1)"
    assert attr(new, "style:parent-style-name") == "standard_1"
    assert report.renamed[StyleRef("graphic", "Fancy")] == "Fancy_1"
    # untouched originals
    props = one(root, "//style:style[@style:name='Fancy']/style:graphic-properties")
    assert attr(props, "draw:fill-color") == "#00ff00"


# ---------------------------------------------------------------- master pages
def test_master_page_copies_layout_and_renames_clashing_automatic_styles(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_dst(tmp_path / "dst.odg")
    report = copy_styles(src, dst, families=["master-page"])
    root = styles_root(dst)
    master = one(root, "//style:master-page[@style:name='Default']")
    one(root, "//style:master-page[@style:name='Mine']")
    # PM0 and Mdp1 already exist in the target's automatic styles -> renamed
    assert attr(master, "style:page-layout-name") == "PM0_1"
    assert attr(master, "draw:style-name") == "Mdp1_1"
    one(root, "//office:automatic-styles/style:page-layout[@style:name='PM0_1']")
    page_style = one(root, "//office:automatic-styles/style:style[@style:name='Mdp1_1']")
    assert attr(page_style[0], "draw:fill-gradient-name") == "Sunset"
    # gr1 clashes with an automatic style in content.xml
    rect = one(master, "draw:rect")
    assert attr(rect, "draw:style-name") == "gr1_1"
    gr = one(root, "//office:automatic-styles/style:style[@style:name='gr1_1']")
    assert attr(gr, "style:parent-style-name") == "Fancy"
    # the target's own automatic styles are unchanged
    old = one(root, "//office:automatic-styles/style:style[@style:name='Mdp1']")
    assert attr(old[0], "draw:fill") == "none"
    assert StyleRef("graphic", "Fancy") in report.overwritten
    assert not report.unresolved


def test_copying_again_changes_nothing(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_dst(tmp_path / "dst.odg")
    copy_all_styles(src, dst)
    before = dst.read_bytes()
    report = copy_all_styles(src, dst)
    # identical styles are not rewritten, and the master page's automatic styles
    # (renamed to PM0_1, Mdp1_1, gr1_1 the first time) are reused instead of copied again
    assert not report.copied
    assert not report.overwritten
    assert not report.renamed
    assert StyleRef("graphic", "Fancy") in report.unchanged
    assert StyleRef("page-layout", "PM0", automatic=True) in report.skipped
    assert dst.read_bytes() == before
    assert "unchanged (identical in target)" in report.summary()


# ---------------------------------------------------------------- embedded files
def test_fill_image_copies_picture_and_manifest_entry(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg", files={"Pictures/p.png": b"other image"})
    report = copy_styles(src, dst, names=["Textured"])
    with zipfile.ZipFile(dst) as zf:
        assert zf.read("Pictures/p_1.png") == PNG
        assert zf.read("Pictures/p.png") == b"other image"
        manifest = zf.read("META-INF/manifest.xml").decode()
    assert 'manifest:full-path="Pictures/p_1.png"' in manifest
    fill = one(styles_root(dst), "//draw:fill-image[@draw:name='Pic']")
    assert attr(fill, "xlink:href") == "Pictures/p_1.png"
    assert report.files == ["Pictures/p_1.png"]


def test_identical_picture_is_reused(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg", files={"Pictures/p.png": PNG})
    report = copy_styles(src, dst, names=["Textured"])
    assert report.files == []
    fill = one(styles_root(dst), "//draw:fill-image[@draw:name='Pic']")
    assert attr(fill, "xlink:href") == "Pictures/p.png"


# ---------------------------------------------------------------- flat documents
def test_zipped_to_flat_embeds_images(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.fodg", flat=True)
    copy_styles(src, dst, names=["Textured"])
    fill = one(styles_root(dst), "//draw:fill-image[@draw:name='Pic']")
    assert attr(fill, "xlink:href") is None
    binary = one(fill, "office:binary-data")
    assert base64.b64decode(binary.text or "") == PNG


def test_flat_to_zipped(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.fodg", flat=True)
    dst = make_dst(tmp_path / "dst.odg")
    report = copy_styles(src, dst, families=["master-page"], on_conflict="skip")
    root = styles_root(dst)
    one(root, "//style:master-page[@style:name='Default']")
    assert StyleRef("graphic", "Fancy") in report.skipped
    assert not report.unresolved


# ---------------------------------------------------------------- text and cells
def test_paragraph_styles_with_next_and_list_style(tmp_path: Path) -> None:
    src = make_odf(
        tmp_path / "src.odt",
        doc_type="text",
        styles="""
<style:style style:name="Standard" style:family="paragraph"/>
<style:style style:name="Text_20_body" style:display-name="Text body" style:family="paragraph" style:parent-style-name="Standard"/>
<style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph"
  style:parent-style-name="Standard" style:next-style-name="Text_20_body" style:list-style-name="Numbering_20_123"/>
<style:style style:name="Strong" style:family="text"/>
<text:list-style style:name="Numbering_20_123">
  <text:list-level-style-number text:level="1" text:style-name="Strong" style:num-format="1"/>
</text:list-style>
""",
        body="<office:text/>",
    )
    dst = make_odf(tmp_path / "dst.odt", doc_type="text", body="<office:text/>")
    report = copy_styles(src, dst, names=["Heading 1"], families=["paragraph"])
    names = {(r.kind, r.name) for r in report.copied}
    assert names == {
        ("paragraph", "Heading_20_1"),
        ("paragraph", "Standard"),
        ("paragraph", "Text_20_body"),
        ("list", "Numbering_20_123"),
        ("text", "Strong"),
    }


def test_cell_style_with_number_format(tmp_path: Path) -> None:
    src = make_odf(
        tmp_path / "src.ods",
        doc_type="spreadsheet",
        styles="""
<number:number-style style:name="N2"><number:number number:decimal-places="2"/></number:number-style>
<number:number-style style:name="N3"><number:number number:decimal-places="2"/>
  <style:map style:condition="value()&gt;=0" style:apply-style-name="N2"/></number:number-style>
<style:style style:name="Default" style:family="table-cell"/>
<style:style style:name="Positive" style:family="table-cell"/>
<style:style style:name="Money" style:family="table-cell" style:parent-style-name="Default" style:data-style-name="N3">
  <style:map style:condition="cell-content()&gt;0" style:apply-style-name="Positive"/>
</style:style>
""",
        body="<office:spreadsheet/>",
    )
    dst = make_odf(tmp_path / "dst.ods", doc_type="spreadsheet", body="<office:spreadsheet/>")
    report = copy_styles(src, dst, names=["Money"])
    assert {(r.kind, r.name) for r in report.copied} == {
        ("table-cell", "Money"),
        ("table-cell", "Default"),
        ("table-cell", "Positive"),
        ("number", "N3"),
        ("number", "N2"),
    }
    assert not report.unresolved


# ---------------------------------------------------------------- misc
def test_copy_all_styles_includes_defaults(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg")
    report = copy_all_styles(src, dst)
    root = styles_root(dst)
    one(root, "//office:styles/style:default-style[@style:family='graphic']")
    one(root, "//style:master-page[@style:name='Default']")
    assert StyleRef("default", "graphic") in report.copied
    assert not report.unresolved


def test_unknown_style_raises(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg")
    with pytest.raises(StyleNotFoundError):
        copy_styles(src, dst, names=["Nope"])


def test_output_keeps_target_and_mimetype_first(tmp_path: Path) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg")
    before = dst.read_bytes()
    out = tmp_path / "out.odg"
    copy_styles(src, dst, families=["graphic"], output=out)
    assert dst.read_bytes() == before
    with zipfile.ZipFile(out) as zf:
        first = zf.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = make_src(tmp_path / "src.odg")
    dst = make_odf(tmp_path / "dst.odg")
    assert main(["list", str(src), "-f", "graphic"]) == 0
    listed = capsys.readouterr().out
    assert "Fancy  (Fancy Box)" in listed
    assert "gradient" not in listed
    assert main(["copy", str(src), str(dst), "-s", "Fancy", "--on-conflict", "skip"]) == 0
    assert "graphic:Fancy" in capsys.readouterr().out
    assert main(["copy", str(src), str(dst), "-s", "Missing"]) == 1
    assert "not found" in capsys.readouterr().err
