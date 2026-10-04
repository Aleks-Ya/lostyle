from __future__ import annotations

from pathlib import Path

import pytest
from helpers import make_odf
from test_copier import make_dst, make_src

from lostyle import StyleRef, diff_styles, rename_style
from lostyle.cli import main


def refs(entries) -> set[tuple[str, str]]:  # type: ignore[no-untyped-def]
    return {(e.ref.kind, e.ref.name) for e in entries}


def test_only_in_each_and_common(tmp_path: Path) -> None:
    diff = diff_styles(make_src(tmp_path / "a.odg"), make_dst(tmp_path / "b.odg"))
    assert refs(diff.only_a) == {
        ("default", "graphic"),
        ("gradient", "Sunset"),
        ("marker", "Arrow"),
        ("stroke-dash", "Dots"),
        ("fill-image", "Pic"),
        ("graphic", "Textured"),
        ("font-face", "Liberation Sans"),
        ("master-page", "Default"),
    }
    assert refs(diff.only_b) == {("master-page", "Mine")}
    assert diff.common == [StyleRef("graphic", "Fancy"), StyleRef("graphic", "standard")]
    assert diff


def test_automatic_styles_are_ignored(tmp_path: Path) -> None:
    diff = diff_styles(make_src(tmp_path / "a.odg"), make_dst(tmp_path / "b.odg"))
    assert not any(e.ref.automatic for e in diff.only_a + diff.only_b)
    assert ("page-layout", "PM0") not in refs(diff.only_a)


def test_same_document_has_no_differences(tmp_path: Path) -> None:
    doc = make_src(tmp_path / "a.odg")
    diff = diff_styles(doc, doc)
    assert not diff
    assert diff.format() == f"no differences ({len(diff.common)} styles in both)"


def test_same_name_in_different_families_differs(tmp_path: Path) -> None:
    a = make_odf(
        tmp_path / "a.odg", styles='<style:style style:name="Box" style:family="graphic"/>'
    )
    b = make_odf(
        tmp_path / "b.odg", styles='<style:style style:name="Box" style:family="paragraph"/>'
    )
    diff = diff_styles(a, b)
    assert refs(diff.only_a) == {("graphic", "Box")}
    assert refs(diff.only_b) == {("paragraph", "Box")}
    assert diff.common == []


def test_family_filter(tmp_path: Path) -> None:
    diff = diff_styles(
        make_src(tmp_path / "a.odg"), make_dst(tmp_path / "b.odg"), families=["graphic"]
    )
    assert refs(diff.only_a) == {("graphic", "Textured")}
    assert diff.only_b == []


def test_diff_after_rename(tmp_path: Path) -> None:
    a = make_src(tmp_path / "a.odg")
    b = make_src(tmp_path / "b.odg")
    rename_style(b, "Fancy Box", "Corporate Box")
    diff = diff_styles(a, b, families=["graphic"])
    assert diff.format("a.odg", "b.odg").splitlines() == [
        "--- a.odg",
        "+++ b.odg",
        "graphic",
        "  - Fancy  (Fancy Box)",
        "  + Corporate_20_Box  (Corporate Box)",
        "1 only in a.odg, 1 only in b.odg, 2 in both",
    ]


def test_cli_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = make_src(tmp_path / "a.odg")
    b = make_dst(tmp_path / "b.odg")
    assert main(["diff", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "master-page\n  - Default\n  + Mine\n" in out
    assert out.rstrip().endswith(f"8 only in {a}, 1 only in {b}, 2 in both")

    assert main(["diff", str(a), str(b), "--exit-code"]) == 1
    assert main(["diff", str(a), str(a), "--exit-code"]) == 0
    assert main(["diff", str(a), str(b), "-f", "stroke-dash", "-f", "marker"]) == 0
    assert "marker\n  - Arrow\nstroke-dash\n  - Dots\n" in capsys.readouterr().out

    assert main(["diff", str(a), str(tmp_path / "missing.odg")]) == 1
    assert "error" in capsys.readouterr().err
