"""Round-trip results through a real LibreOffice to check that it accepts the copied styles."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import make_odf
from test_copier import SRC_AUTO, SRC_FONTS, SRC_MASTERS, SRC_STYLES, attr, one, styles_root

from lostyle import copy_styles

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
