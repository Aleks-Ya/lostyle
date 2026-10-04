"""Round-trip results through a real LibreOffice to check that it accepts our changes."""

from __future__ import annotations

import shutil
import subprocess
from html import escape
from pathlib import Path

import pytest
from helpers import make_odf
from test_copier import SRC_AUTO, SRC_FONTS, SRC_MASTERS, SRC_STYLES, attr, find, one, styles_root

from lostyle import OdfPackage, StyleRef, copy_styles, rename_style, replace_style
from lostyle.ns import NS, encode_style_name

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")
pytestmark = pytest.mark.skipif(SOFFICE is None, reason="LibreOffice not installed")


@pytest.fixture(scope="module")
def convert(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    profile = tmp_path_factory.mktemp("lo-profile")

    def run(src: Path, fmt: str, outdir: Path) -> Path:
        assert SOFFICE is not None
        subprocess.run(
            [SOFFICE, f"-env:UserInstallation={profile.as_uri()}", "--headless",
             "--convert-to", fmt, "--outdir", str(outdir), str(src)],
            check=True, capture_output=True, timeout=180,
        )  # fmt: skip
        out = outdir / f"{src.stem}.{fmt.split(':')[0]}"
        assert out.exists(), f"LibreOffice did not produce {out}"
        return out

    return run


def test_draw_roundtrip(tmp_path: Path, convert) -> None:  # type: ignore[no-untyped-def]
    # Let LibreOffice produce real .odg files for source and target.
    flat_dir = tmp_path / "flat"
    flat_dir.mkdir()
    page = '<draw:page draw:name="p1" draw:master-page-name="Default"/>'
    src_flat = make_odf(
        flat_dir / "src.fodg", fonts=SRC_FONTS, styles=SRC_STYLES.replace(
            '<draw:fill-image draw:name="Pic" xlink:href="Pictures/p.png" xlink:type="simple" '
            'xlink:show="embed" xlink:actuate="onLoad"/>', ""),
        auto_styles=SRC_AUTO, masters=SRC_MASTERS, body=f"<office:drawing>{page}</office:drawing>",
        flat=True,
    )  # fmt: skip
    dst_flat = make_odf(
        flat_dir / "dst.fodg",
        masters='<style:master-page style:name="Mine" style:page-layout-name="PM0"/>',
        auto_styles='<style:page-layout style:name="PM0"/>',
        body='<office:drawing><draw:page draw:name="p1" draw:master-page-name="Mine"/></office:drawing>',
        flat=True,
    )
    src = convert(src_flat, "odg", tmp_path)
    dst = convert(dst_flat, "odg", tmp_path)

    report = copy_styles(
        src, dst, names=["Fancy Box"], families=["graphic"], output=tmp_path / "out.odg"
    )
    assert not report.unresolved

    # LibreOffice must open the result and keep the copied style when saving again.
    check_dir = tmp_path / "check"
    check_dir.mkdir()
    convert(tmp_path / "out.odg", "pdf", check_dir)
    resaved = convert(tmp_path / "out.odg", "fodg", check_dir)
    root = styles_root(resaved)
    fancy = one(
        root, "//office:styles/style:style[@style:family='graphic'][@style:name='Fancy_20_Box']"
    )
    props = one(fancy, "style:graphic-properties")
    gradient = attr(props, "draw:fill-gradient-name")
    assert gradient is not None
    one(root, f"//office:styles/draw:gradient[@draw:name='{gradient}']")
    assert attr(props, "draw:marker-end") is not None


def test_draw_master_page_roundtrip(tmp_path: Path, convert) -> None:  # type: ignore[no-untyped-def]
    flat_dir = tmp_path / "flat"
    flat_dir.mkdir()
    src_flat = make_odf(
        flat_dir / "src.fodg", fonts=SRC_FONTS, styles=SRC_STYLES, auto_styles=SRC_AUTO,
        masters=SRC_MASTERS.replace('"Default"', '"Sunny"'),
        body='<office:drawing><draw:page draw:name="p1" draw:master-page-name="Sunny"/></office:drawing>',
        flat=True,
    )  # fmt: skip
    dst_flat = make_odf(
        flat_dir / "dst.fodg",
        body='<office:drawing><draw:page draw:name="p1"/></office:drawing>',
        flat=True,
    )
    src = convert(src_flat, "odg", tmp_path)
    dst = convert(dst_flat, "odg", tmp_path)

    out = tmp_path / "out.odg"
    report = copy_styles(src, dst, names=["Sunny"], families=["master-page"], output=out)
    assert not report.unresolved

    check_dir = tmp_path / "check"
    check_dir.mkdir()
    resaved = convert(out, "fodg", check_dir)
    root = styles_root(resaved)
    master = one(root, "//style:master-page[@style:name='Sunny']")
    page_style = one(root, f"//style:style[@style:name='{attr(master, 'draw:style-name')}']")
    props = one(page_style, "style:drawing-page-properties")
    assert attr(props, "draw:fill") == "gradient"


def test_rename_roundtrip(tmp_path: Path, convert) -> None:  # type: ignore[no-untyped-def]
    flat_dir = tmp_path / "flat"
    flat_dir.mkdir()
    body = (
        '<office:drawing><draw:page draw:name="p1" draw:master-page-name="Default">'
        '<draw:custom-shape draw:style-name="Fancy" svg:width="2cm" svg:height="2cm" svg:x="1cm" svg:y="1cm">'
        '<draw:enhanced-geometry draw:type="rectangle"/></draw:custom-shape>'
        "</draw:page></office:drawing>"
    )
    src_flat = make_odf(
        flat_dir / "doc.fodg", fonts=SRC_FONTS, styles=SRC_STYLES, auto_styles=SRC_AUTO,
        masters=SRC_MASTERS, body=body, flat=True,
    )  # fmt: skip
    doc = convert(src_flat, "odg", tmp_path)

    result = rename_style(doc, "Fancy Box", "Corporate Box")
    assert result.references >= 2  # master-page shape style + the shape on the page

    check_dir = tmp_path / "check"
    check_dir.mkdir()
    resaved = convert(doc, "fodg", check_dir)
    root = styles_root(resaved)
    style = one(root, "//office:styles/style:style[@style:name='Corporate_20_Box']")
    assert attr(style, "style:display-name") == "Corporate Box"
    assert not find(root, "//office:styles/style:style[@style:name='Fancy_20_Box']")
    shape = one(root, "//draw:page//draw:custom-shape")
    shape_style = attr(shape, "draw:style-name")
    # LO stores the shape's own formatting in an automatic style whose parent is ours
    if shape_style != "Corporate_20_Box":
        auto = one(root, f"//office:automatic-styles/style:style[@style:name='{shape_style}']")
        assert attr(auto, "style:parent-style-name") == "Corporate_20_Box"


ENCODING_SAMPLES = ["A (b)", "1x", "a_20_b", "a_b", "x:y", "a/b", "-lead", "Ü ber", "a.b-c", "日本"]


def test_encoding_matches_libreoffice(tmp_path: Path, convert) -> None:  # type: ignore[no-untyped-def]
    styles = "".join(
        f'<style:style style:name="s{i}" style:display-name="{escape(n)}" style:family="graphic"/>'
        for i, n in enumerate(ENCODING_SAMPLES)
    )
    flat = make_odf(tmp_path / "enc.fodg", styles=styles, flat=True,
                    body='<office:drawing><draw:page draw:name="p"/></office:drawing>')  # fmt: skip
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    root = styles_root(convert(flat, "fodg", out_dir))
    lo_names = {
        attr(e, "style:display-name") or attr(e, "style:name"): attr(e, "style:name")
        for e in find(root, "//office:styles/style:style[@style:family='graphic']")
    }
    for name in ENCODING_SAMPLES:
        assert lo_names[name] == encode_style_name(name), name


def test_rename_impress_master_page(tmp_path: Path, convert) -> None:  # type: ignore[no-untyped-def]
    flat = make_odf(
        tmp_path / "pres.fodp",
        doc_type="presentation",
        body='<office:presentation><draw:page draw:name="p1"/></office:presentation>',
        flat=True,
    )
    doc = convert(flat, "odp", tmp_path)
    # Customise the master's title style so we can tell it apart from LO's defaults.
    pkg = OdfPackage.open(doc)
    title = one(pkg.styles_root, "//style:style[@style:name='Default-title']/style:text-properties")
    title.set(f"{{{NS['fo']}}}font-size", "77pt")
    pkg.mark_styles_modified()

    result = rename_style(pkg, "Default", "Corporate Master", family="master-page", output=doc)
    assert StyleRef("presentation", "Default-title") in result.linked

    check_dir = tmp_path / "check"
    check_dir.mkdir()
    root = styles_root(convert(doc, "fodp", check_dir))
    one(root, "//style:master-page[@style:name='Corporate_20_Master']")
    pages = find(root, "//draw:page")
    assert pages
    assert all(attr(p, "draw:master-page-name") == "Corporate_20_Master" for p in pages)
    props = one(
        root, "//style:style[@style:name='Corporate_20_Master-title']/style:text-properties"
    )
    assert attr(props, "fo:font-size") == "77pt"


def test_replace_roundtrip(tmp_path: Path, convert) -> None:  # type: ignore[no-untyped-def]
    flat_dir = tmp_path / "flat"
    flat_dir.mkdir()
    styles = """
<style:style style:name="standard" style:family="graphic"/>
<style:style style:name="Box" style:family="graphic" style:parent-style-name="standard">
  <style:graphic-properties draw:fill="solid" draw:fill-color="#ff0000"/></style:style>
<style:style style:name="Box_20_2" style:display-name="Box 2" style:family="graphic" style:parent-style-name="standard">
  <style:graphic-properties draw:fill="solid" draw:fill-color="#ff0000"/></style:style>
"""
    shape = (
        '<draw:custom-shape draw:style-name="{}" svg:width="2cm" svg:height="2cm" svg:x="{}cm" '
        'svg:y="1cm"><draw:enhanced-geometry draw:type="rectangle"/></draw:custom-shape>'
    )
    body = (
        '<office:drawing><draw:page draw:name="p1" draw:master-page-name="M">'
        + shape.format("Box", 1)
        + shape.format("Box_20_2", 5)
        + "</draw:page></office:drawing>"
    )
    flat = make_odf(
        flat_dir / "doc.fodg", styles=styles, body=body, flat=True,
        auto_styles='<style:page-layout style:name="PM0"/>',
        masters='<style:master-page style:name="M" style:page-layout-name="PM0"/>',
    )  # fmt: skip
    doc = convert(flat, "odg", tmp_path)

    result = replace_style(doc, "Box 2", "Box")
    assert result.references >= 1

    check_dir = tmp_path / "check"
    check_dir.mkdir()
    root = styles_root(convert(doc, "fodg", check_dir))
    names = {attr(e, "style:name") for e in find(root, "//office:styles/style:style")}
    assert "Box" in names
    assert "Box_20_2" not in names
    shapes = find(root, "//draw:page/draw:custom-shape")
    assert len(shapes) == 2
    for s in shapes:
        style = attr(s, "draw:style-name")
        if style != "Box":  # LO keeps per-shape formatting in an automatic style
            auto = one(root, f"//office:automatic-styles/style:style[@style:name='{style}']")
            assert attr(auto, "style:parent-style-name") == "Box"
