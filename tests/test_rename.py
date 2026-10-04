from __future__ import annotations

from pathlib import Path

import pytest
from helpers import make_odf
from test_copier import SRC_AUTO, SRC_FONTS, SRC_MASTERS, SRC_STYLES, attr, find, one, styles_root

from lostyle import (
    AmbiguousStyleError,
    OdfPackage,
    StyleNameConflictError,
    StyleNotFoundError,
    StyleRef,
    rename_style,
)
from lostyle.cli import main
from lostyle.ns import decode_style_name, encode_style_name

BODY = """<office:drawing><draw:page draw:name="p" draw:master-page-name="Default">
<draw:custom-shape draw:style-name="Fancy"/>
<draw:frame draw:style-name="gr1"/>
<draw:rect draw:class-names="standard Fancy"/>
</draw:page></office:drawing>"""


def make_doc(path: Path, *, content_auto: str = "", flat: bool = False) -> Path:
    return make_odf(
        path,
        fonts=SRC_FONTS,
        styles=SRC_STYLES,
        auto_styles=SRC_AUTO,
        masters=SRC_MASTERS,
        content_auto_styles=content_auto
        or '<style:style style:name="gr1" style:family="graphic" style:parent-style-name="Fancy"/>',
        body=BODY,
        flat=flat,
    )


def content_root(path: Path):  # type: ignore[no-untyped-def]
    root = OdfPackage.open(path).content_root
    assert root is not None
    return root


@pytest.mark.parametrize(
    ("display", "encoded"),
    [
        # observed in LibreOffice 26.2 output
        ("Fancy Box", "Fancy_20_Box"),
        ("A (b)", "A_20__28_b_29_"),
        ("1x", "_31_x"),
        ("-lead", "_2d_lead"),
        (".lead", "_2e_lead"),
        ("_x", "_5f_x"),
        ("a_b", "a_5f_b"),
        ("a_20_b", "a_5f_20_5f_b"),
        ("a&b", "a_26_b"),
        ("a/b", "a_2f_b"),
        ("x:y", "x_3a_y"),
        ("a.b-c", "a.b-c"),
        ("Ü ber", "Ü_20_ber"),
        ("日本", "日本"),
    ],
)
def test_encode_style_name(display: str, encoded: str) -> None:
    assert encode_style_name(display) == encoded
    assert decode_style_name(encoded) == display


def test_rename_updates_all_references(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    result = rename_style(doc, "Fancy Box", "Corporate Box")

    assert result.ref == StyleRef("graphic", "Fancy")
    assert result.new_name == "Corporate_20_Box"
    # styles.xml gr1 parent, content.xml gr1 parent, custom-shape, class-names
    assert result.references == 4
    styles = styles_root(doc)
    style = one(styles, "//office:styles/style:style[@style:name='Corporate_20_Box']")
    assert attr(style, "style:display-name") == "Corporate Box"
    assert not find(styles, "//style:style[@style:name='Fancy']")
    auto = one(styles, "//office:automatic-styles/style:style[@style:name='gr1']")
    assert attr(auto, "style:parent-style-name") == "Corporate_20_Box"

    content = content_root(doc)
    gr1 = one(content, "//office:automatic-styles/style:style[@style:name='gr1']")
    assert attr(gr1, "style:parent-style-name") == "Corporate_20_Box"
    assert attr(one(content, "//draw:custom-shape"), "draw:style-name") == "Corporate_20_Box"
    assert attr(one(content, "//draw:frame"), "draw:style-name") == "gr1"
    assert attr(one(content, "//draw:rect"), "draw:class-names") == "standard Corporate_20_Box"


def test_same_named_automatic_style_in_content_is_not_renamed(tmp_path: Path) -> None:
    doc = make_doc(
        tmp_path / "doc.odg",
        content_auto='<style:style style:name="Fancy" style:family="graphic"/>',
    )
    result = rename_style(doc, "Fancy", "Corporate")
    assert result.references == 1  # only styles.xml gr1 parent; the body sees content's "Fancy"
    assert attr(one(content_root(doc), "//draw:rect"), "draw:class-names") == "standard Fancy"
    content = content_root(doc)
    assert attr(one(content, "//draw:custom-shape"), "draw:style-name") == "Fancy"
    one(content, "//office:automatic-styles/style:style[@style:name='Fancy']")


def test_display_name_dropped_when_equal_to_internal_name(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    result = rename_style(doc, "Fancy", "Corporate")
    style = one(styles_root(doc), "//style:style[@style:name='Corporate']")
    assert attr(style, "style:display-name") is None
    assert result.display_name == "Corporate"


def test_rename_master_page(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    result = rename_style(doc, "Default", "Corporate Master", family="master-page")
    assert result.references == 1
    one(styles_root(doc), "//style:master-page[@style:name='Corporate_20_Master']")
    page = one(content_root(doc), "//draw:page")
    assert attr(page, "draw:master-page-name") == "Corporate_20_Master"


def test_rename_gradient(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    result = rename_style(doc, "Sunset glow", "Dawn")
    assert result.references == 2  # Fancy and the master page's drawing-page style
    styles = styles_root(doc)
    gradient = one(styles, "//draw:gradient[@draw:name='Dawn']")
    assert attr(gradient, "draw:display-name") is None
    assert len(find(styles, "//*[@draw:fill-gradient-name='Dawn']")) == 2


def test_rename_paragraph_style(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.odt",
        doc_type="text",
        styles="""
<style:style style:name="Standard" style:family="paragraph"/>
<style:style style:name="Text_20_body" style:display-name="Text body" style:family="paragraph" style:parent-style-name="Standard"/>
<style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph" style:next-style-name="Text_20_body"/>
""",
        content_auto_styles='<style:style style:name="P1" style:family="paragraph" style:parent-style-name="Text_20_body"/>',
        body='<office:text><text:p text:style-name="Text_20_body">a</text:p><text:p text:style-name="P1">b</text:p></office:text>',
    )
    result = rename_style(doc, "Text body", "Body Text")
    assert result.references == 3
    heading = one(styles_root(doc), "//style:style[@style:name='Heading_20_1']")
    assert attr(heading, "style:next-style-name") == "Body_20_Text"
    content = content_root(doc)
    assert attr(find(content, "//text:p")[0], "text:style-name") == "Body_20_Text"
    p1 = one(content, "//style:style[@style:name='P1']")
    assert attr(p1, "style:parent-style-name") == "Body_20_Text"


def test_rename_cell_style(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.ods",
        doc_type="spreadsheet",
        styles='<style:style style:name="Default" style:family="table-cell"/>',
        body="""<office:spreadsheet><table:table table:name="S">
<table:table-column table:default-cell-style-name="Default"/>
<table:table-row><table:table-cell table:style-name="Default"/></table:table-row>
</table:table></office:spreadsheet>""",
    )
    result = rename_style(doc, "Default", "Base")
    assert result.references == 2
    content = content_root(doc)
    assert attr(one(content, "//table:table-column"), "table:default-cell-style-name") == "Base"
    assert attr(one(content, "//table:table-cell"), "table:style-name") == "Base"


def test_flat_document_and_output(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.fodg", flat=True)
    before = doc.read_bytes()
    out = tmp_path / "out.fodg"
    result = rename_style(doc, "Fancy", "Corporate", output=out)
    assert doc.read_bytes() == before
    assert result.references == 4
    root = styles_root(out)
    assert attr(one(root, "//draw:custom-shape"), "draw:style-name") == "Corporate"


@pytest.mark.parametrize(
    ("old", "new", "kwargs", "error"),
    [
        ("Nope", "X", {}, StyleNotFoundError),
        ("Fancy", "standard", {}, StyleNameConflictError),
        ("standard", "Fancy Box", {}, StyleNameConflictError),  # display name taken
        ("standard", "gr1", {}, StyleNameConflictError),  # automatic style name taken
        ("graphic", "X", {"family": "default"}, ValueError),
        ("Liberation Sans", "X", {}, ValueError),
        ("Fancy", "  ", {}, ValueError),
    ],
)
def test_errors_leave_document_unchanged(
    tmp_path: Path, old: str, new: str, kwargs: dict[str, str], error: type[Exception]
) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    before = doc.read_bytes()
    with pytest.raises(error):
        rename_style(doc, old, new, **kwargs)
    assert doc.read_bytes() == before


def test_ambiguous_name_needs_family(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.odg",
        styles='<style:style style:name="Box" style:family="graphic"/>'
        '<style:style style:name="Box" style:family="paragraph"/>',
    )
    with pytest.raises(AmbiguousStyleError, match="graphic, paragraph"):
        rename_style(doc, "Box", "Crate")
    result = rename_style(doc, "Box", "Crate", family="paragraph")
    assert result.ref == StyleRef("paragraph", "Box")
    root = styles_root(doc)
    one(root, "//style:style[@style:family='graphic'][@style:name='Box']")
    one(root, "//style:style[@style:family='paragraph'][@style:name='Crate']")


def test_cli_rename(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    assert main(["rename", str(doc), "Fancy Box", "Corporate Box"]) == 0
    assert "graphic:Fancy -> Corporate_20_Box (Corporate Box), 4 reference(s)" in (
        capsys.readouterr().out
    )
    assert main(["rename", str(doc), "Corporate Box", "standard"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_master_page_rename_takes_presentation_styles_along(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.odp",
        doc_type="presentation",
        styles="""
<style:style style:name="Default-title" style:family="presentation"/>
<style:style style:name="Default-outline1" style:family="presentation"/>
<style:style style:name="Default-outline2" style:family="presentation" style:parent-style-name="Default-outline1"/>
<style:style style:name="Other-title" style:family="presentation"/>
""",
        auto_styles='<style:page-layout style:name="PM1"/>',
        masters="""<style:master-page style:name="Default" style:page-layout-name="PM1">
<draw:frame presentation:style-name="Default-title" presentation:class="title"/></style:master-page>""",
        content_auto_styles='<style:style style:name="pr1" style:family="presentation" style:parent-style-name="Default-title"/>',
        body='<office:presentation><draw:page draw:name="p" draw:master-page-name="Default">'
        '<draw:frame presentation:style-name="pr1"/></draw:page></office:presentation>',
    )
    result = rename_style(doc, "Default", "Corporate Master", family="master-page")
    assert result.linked == {
        StyleRef("presentation", "Default-title"): "Corporate_20_Master-title",
        StyleRef("presentation", "Default-outline1"): "Corporate_20_Master-outline1",
        StyleRef("presentation", "Default-outline2"): "Corporate_20_Master-outline2",
    }
    # draw:page master, master-page frame, pr1 parent, outline2 parent
    assert result.references == 4
    styles = styles_root(doc)
    title = one(styles, "//style:style[@style:name='Corporate_20_Master-title']")
    assert attr(title, "style:display-name") == "Corporate Master-title"
    outline2 = one(styles, "//style:style[@style:name='Corporate_20_Master-outline2']")
    assert attr(outline2, "style:parent-style-name") == "Corporate_20_Master-outline1"
    one(styles, "//style:style[@style:name='Other-title']")
    frame = one(styles, "//style:master-page/draw:frame")
    assert attr(frame, "presentation:style-name") == "Corporate_20_Master-title"
    pr1 = one(content_root(doc), "//style:style[@style:name='pr1']")
    assert attr(pr1, "style:parent-style-name") == "Corporate_20_Master-title"
