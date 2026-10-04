from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from helpers import make_odf
from test_copier import attr, find, one, styles_root
from test_rename import content_root

from lostyle import AmbiguousStyleError, StyleNotFoundError, StyleRef, replace_style
from lostyle.cli import main

STYLES = """
<style:style style:name="standard" style:family="graphic"/>
<style:style style:name="Box" style:family="graphic" style:parent-style-name="standard"/>
<style:style style:name="Box_20_2" style:display-name="Box 2" style:family="graphic" style:parent-style-name="standard"/>
<style:style style:name="Box_20_copy" style:display-name="Box copy" style:family="graphic"/>
<style:style style:name="Child" style:family="graphic" style:parent-style-name="Box_20_2"/>
"""
AUTO = (
    '<style:style style:name="gr1" style:family="graphic" style:parent-style-name="Box_20_copy"/>'
)
MASTERS = """<style:master-page style:name="Default">
<draw:custom-shape draw:style-name="Box_20_2"/><draw:rect draw:style-name="gr1"/></style:master-page>"""
CONTENT_AUTO = (
    '<style:style style:name="gr2" style:family="graphic" style:parent-style-name="Box_20_2"/>'
)
BODY = """<office:drawing><draw:page draw:name="p" draw:master-page-name="Default">
<draw:custom-shape draw:style-name="Box_20_2"/>
<draw:frame draw:style-name="gr2"/>
<draw:rect draw:class-names="Box_20_copy standard"/>
</draw:page></office:drawing>"""


def make_doc(path: Path, styles: str = STYLES, flat: bool = False) -> Path:
    return make_odf(
        path,
        styles=styles,
        auto_styles=AUTO,
        masters=MASTERS,
        content_auto_styles=CONTENT_AUTO,
        body=BODY,
        flat=flat,
    )


def graphic_names(path: Path) -> set[str]:
    return {
        attr(e, "style:name") or ""
        for e in find(styles_root(path), "//office:styles/style:style[@style:family='graphic']")
    }


def test_merges_duplicates_into_one_style(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    result = replace_style(doc, ["Box 2", "Box copy"], "Box")

    assert result.replacement == StyleRef("graphic", "Box")
    assert result.replaced == [StyleRef("graphic", "Box_20_2"), StyleRef("graphic", "Box_20_copy")]
    # Child parent, styles.xml gr1 parent, master shape, content gr2 parent, body shape, class-names
    assert result.references == 6
    assert graphic_names(doc) == {"standard", "Box", "Child"}

    styles = styles_root(doc)
    assert (
        attr(one(styles, "//style:style[@style:name='Child']"), "style:parent-style-name") == "Box"
    )
    assert attr(one(styles, "//style:style[@style:name='gr1']"), "style:parent-style-name") == "Box"
    assert attr(one(styles, "//style:master-page/draw:custom-shape"), "draw:style-name") == "Box"
    content = content_root(doc)
    assert (
        attr(one(content, "//style:style[@style:name='gr2']"), "style:parent-style-name") == "Box"
    )
    assert attr(one(content, "//draw:page/draw:custom-shape"), "draw:style-name") == "Box"
    assert attr(one(content, "//draw:rect"), "draw:class-names") == "Box standard"
    assert (
        "graphic: Box_20_2, Box_20_copy -> Box; 6 reference(s) updated; 2 style(s) deleted"
        in str(result)
    )


def test_keep_leaves_old_styles(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    result = replace_style(doc, "Box 2", "Box", keep=True)
    assert not result.deleted
    assert {"Box", "Box_20_2"} <= graphic_names(doc)
    assert attr(one(content_root(doc), "//draw:page/draw:custom-shape"), "draw:style-name") == "Box"


def test_replacing_an_ancestor_of_the_replacement_avoids_cycles(tmp_path: Path) -> None:
    styles = """
<style:style style:name="standard" style:family="graphic"/>
<style:style style:name="Box" style:family="graphic" style:parent-style-name="standard"/>
<style:style style:name="Middle" style:family="graphic" style:parent-style-name="Box"/>
<style:style style:name="Box_20_2" style:display-name="Box 2" style:family="graphic" style:parent-style-name="Middle"/>
<style:style style:name="Box_20_copy" style:display-name="Box copy" style:family="graphic"/>
<style:style style:name="Child" style:family="graphic" style:parent-style-name="Box"/>
"""
    doc = make_doc(tmp_path / "doc.odg", styles=styles)
    replace_style(doc, "Box", "Box 2")
    root = styles_root(doc)
    assert (
        attr(one(root, "//style:style[@style:name='Middle']"), "style:parent-style-name")
        == "standard"
    )
    assert (
        attr(one(root, "//style:style[@style:name='Child']"), "style:parent-style-name")
        == "Box_20_2"
    )
    assert (
        attr(one(root, "//style:style[@style:name='Box_20_2']"), "style:parent-style-name")
        == "Middle"
    )


def test_cycle_fix_drops_parent_when_no_ancestor_remains(tmp_path: Path) -> None:
    styles = """
<style:style style:name="Box" style:family="graphic"/>
<style:style style:name="Box_20_2" style:display-name="Box 2" style:family="graphic" style:parent-style-name="Box"/>
<style:style style:name="Box_20_copy" style:display-name="Box copy" style:family="graphic"/>
<style:style style:name="Child" style:family="graphic" style:parent-style-name="Box_20_2"/>
"""
    doc = make_doc(tmp_path / "doc.odg", styles=styles)
    replace_style(doc, "Box", "Box 2")
    box2 = one(styles_root(doc), "//style:style[@style:name='Box_20_2']")
    assert attr(box2, "style:parent-style-name") is None


def test_paragraph_styles(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.odt",
        doc_type="text",
        styles="""
<style:style style:name="Body" style:family="paragraph"/>
<style:style style:name="Body_20_1" style:display-name="Body 1" style:family="paragraph"/>
<style:style style:name="Heading" style:family="paragraph" style:next-style-name="Body_20_1"/>
""",
        body='<office:text><text:p text:style-name="Body_20_1">x</text:p></office:text>',
    )
    result = replace_style(doc, "Body 1", "Body")
    assert result.references == 2
    heading = one(styles_root(doc), "//style:style[@style:name='Heading']")
    assert attr(heading, "style:next-style-name") == "Body"
    assert attr(one(content_root(doc), "//text:p"), "text:style-name") == "Body"


def test_font_face(tmp_path: Path) -> None:
    fonts = (
        '<style:font-face style:name="Arial" svg:font-family="Arial"/>'
        '<style:font-face style:name="Liberation Sans" svg:font-family="&apos;Liberation Sans&apos;"/>'
    )
    doc = make_odf(
        tmp_path / "doc.odg",
        fonts=fonts,
        styles='<style:style style:name="S" style:family="graphic"><style:text-properties style:font-name="Arial"/></style:style>',
        content_auto_styles='<style:style style:name="P1" style:family="paragraph"><style:text-properties style:font-name="Arial"/></style:style>',
    )
    # make_odf puts no font decls in content.xml; add the old one like LibreOffice does
    with zipfile.ZipFile(doc) as zf:
        entries = {i.filename: zf.read(i) for i in zf.infolist()}
    entries["content.xml"] = entries["content.xml"].replace(
        b"<office:automatic-styles>",
        b'<office:font-face-decls><style:font-face style:name="Arial" svg:font-family="Arial"/>'
        b"</office:font-face-decls><office:automatic-styles>",
    )
    with zipfile.ZipFile(doc, "w") as zf:
        for name, data in entries.items():
            zf.writestr(
                name, data, zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            )

    result = replace_style(doc, "Arial", "Liberation Sans")
    assert result.references == 2
    styles = styles_root(doc)
    assert not find(styles, "//style:font-face[@style:name='Arial']")
    props = one(styles, "//style:style[@style:name='S']/style:text-properties")
    assert attr(props, "style:font-name") == "Liberation Sans"
    content = content_root(doc)
    one(content, "//office:font-face-decls/style:font-face[@style:name='Liberation Sans']")
    assert not find(content, "//style:font-face[@style:name='Arial']")


def test_impress_master_page_takes_presentation_styles_along(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.odp",
        doc_type="presentation",
        styles="""
<style:style style:name="Default-title" style:family="presentation"/>
<style:style style:name="Default-notes" style:family="presentation"/>
<style:style style:name="Corp-title" style:family="presentation"/>
""",
        masters='<style:master-page style:name="Default"><draw:frame presentation:style-name="Default-title"/></style:master-page>'
        '<style:master-page style:name="Corp"><draw:frame presentation:style-name="Corp-title"/></style:master-page>',
        content_auto_styles='<style:style style:name="pr1" style:family="presentation" style:parent-style-name="Default-title"/>',
        body='<office:presentation><draw:page draw:name="p" draw:master-page-name="Default"/></office:presentation>',
    )
    result = replace_style(doc, "Default", "Corp", family="master-page")
    assert result.linked == {
        StyleRef("presentation", "Default-title"): StyleRef("presentation", "Corp-title")
    }
    assert any("Default-notes" in w for w in result.warnings)
    styles = styles_root(doc)
    assert [attr(m, "style:name") for m in find(styles, "//style:master-page")] == ["Corp"]
    assert not find(styles, "//style:style[@style:name='Default-title']")
    one(styles, "//style:style[@style:name='Default-notes']")
    content = content_root(doc)
    assert attr(one(content, "//draw:page"), "draw:master-page-name") == "Corp"
    assert (
        attr(one(content, "//style:style[@style:name='pr1']"), "style:parent-style-name")
        == "Corp-title"
    )


def test_flat_document(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.fodg", flat=True)
    result = replace_style(doc, ["Box 2", "Box copy"], "Box")
    assert result.references == 6
    assert graphic_names(doc) == {"standard", "Box", "Child"}


@pytest.mark.parametrize(
    ("old", "replacement", "kwargs", "error"),
    [
        ("Nope", "Box", {}, StyleNotFoundError),
        ("Box 2", "Nope", {}, StyleNotFoundError),
        (["Box 2", "Box"], "Box", {}, ValueError),
        ([], "Box", {}, ValueError),
        ("Box 2", "graphic", {"family": "default"}, ValueError),
        ("Box 2", "Dup", {}, AmbiguousStyleError),
    ],
)
def test_errors_leave_document_unchanged(
    tmp_path: Path,
    old: str | list[str],
    replacement: str,
    kwargs: dict[str, str],
    error: type[Exception],
) -> None:
    styles = STYLES + (
        '<style:default-style style:family="graphic"/>'
        '<style:style style:name="Dup" style:family="graphic"/>'
        '<style:style style:name="Dup" style:family="paragraph"/>'
    )
    doc = make_doc(tmp_path / "doc.odg", styles=styles)
    before = doc.read_bytes()
    with pytest.raises(error):
        replace_style(doc, old, replacement, **kwargs)
    assert doc.read_bytes() == before


def test_cli_replace(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    out = tmp_path / "out.odg"
    assert main(["replace", str(doc), "Box 2", "Box copy", "--with", "Box", "-o", str(out)]) == 0
    assert "2 style(s) deleted" in capsys.readouterr().out
    assert graphic_names(out) == {"standard", "Box", "Child"}
    assert main(["replace", str(doc), "Box 2", "--with", "Box", "--keep"]) == 0
    assert "old styles kept" in capsys.readouterr().out
    assert main(["replace", str(doc), "Nope", "--with", "Box"]) == 1
    assert "not found" in capsys.readouterr().err
