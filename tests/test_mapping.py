from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from helpers import make_odf
from test_copier import attr, find, one, styles_root
from test_rename import content_root

from lostyle import RenameResult, ReplaceResult, apply_mapping, load_mapping, parse_mapping
from lostyle.cli import main

STYLES = """
<style:style style:name="Box" style:family="graphic"/>
<style:style style:name="Box_20_2" style:display-name="Box 2" style:family="graphic"/>
<style:style style:name="Old_20_line" style:display-name="Old line" style:family="graphic"/>
<style:style style:name="Older_20_line" style:display-name="Older line" style:family="graphic"/>
<style:style style:name="Box" style:family="paragraph"/>
"""
BODY = """<office:drawing><draw:page draw:name="p">
<draw:rect draw:style-name="Box_20_2"/>
<draw:line draw:style-name="Old_20_line"/>
<draw:line draw:style-name="Older_20_line"/>
</draw:page></office:drawing>"""

MAPPING = {
    "graphic": {
        "Box": ["Box 2", "Not in this document"],
        "Line: Association": ["Old line", "Older line"],
        "Unrelated": "Missing",
    }
}


def make_doc(path: Path) -> Path:
    return make_odf(path, styles=STYLES, body=BODY)


def graphic_names(path: Path) -> list[str]:
    root = styles_root(path)
    return sorted(
        attr(e, "style:name") or "" for e in find(root, "//style:style[@style:family='graphic']")
    )


def test_merges_into_existing_and_renames_missing_targets(tmp_path: Path) -> None:
    doc = make_doc(tmp_path / "doc.odg")
    result = apply_mapping(doc, parse_mapping(MAPPING))

    replace_box, rename_line, merge_line = result.changes
    assert isinstance(replace_box, ReplaceResult)
    assert [r.name for r in replace_box.replaced] == ["Box_20_2"]
    assert isinstance(rename_line, RenameResult)
    assert rename_line.new_name == "Line_3a__20_Association"
    assert isinstance(merge_line, ReplaceResult)
    assert [r.name for r in merge_line.replaced] == ["Older_20_line"]
    assert not result.warnings

    assert graphic_names(doc) == ["Box", "Line_3a__20_Association"]
    one(styles_root(doc), "//style:style[@style:family='paragraph'][@style:name='Box']")
    shapes = find(content_root(doc), "//draw:page/*")
    assert [attr(s, "draw:style-name") for s in shapes] == [
        "Box",
        "Line_3a__20_Association",
        "Line_3a__20_Association",
    ]


def test_nothing_to_map_leaves_file_untouched(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.odg", styles='<style:style style:name="Box" style:family="graphic"/>'
    )
    before = doc.read_bytes()
    result = apply_mapping(doc, parse_mapping(MAPPING))
    assert not result
    assert str(result) == "nothing to map"
    assert doc.read_bytes() == before


def test_font_face_target_must_exist(tmp_path: Path) -> None:
    doc = make_odf(
        tmp_path / "doc.odg",
        fonts='<style:font-face style:name="Arial" svg:font-family="Arial"/>',
    )
    result = apply_mapping(doc, parse_mapping({"font-face": {"Liberation Sans": ["Arial"]}}))
    assert not result
    assert result.warnings == ["font-face 'Liberation Sans' does not exist; Arial left as is"]


def test_load_mapping(tmp_path: Path) -> None:
    path = tmp_path / "styles.toml"
    path.write_text(
        '[graphic]\n"Line: Association" = ["Old line", "Older line"]\nBox = "Box 2"\n'
        "[master-page]\nMain = []\n",
        encoding="utf-8",
    )
    assert load_mapping(path) == {
        "graphic": {"Line: Association": ["Old line", "Older line"], "Box": ["Box 2"]},
        "master-page": {"Main": []},
    }
    path.write_text("[graphic\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"styles\.toml"):
        load_mapping(path)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"grafic": {"A": ["B"]}}, "unknown style family/kind 'grafic'"),
        ({"default": {"A": ["B"]}}, "unknown"),
        ({"graphic": ["A"]}, "must be a table"),
        ({"graphic": {"A": 1}}, "must map to a name or list"),
        ({"graphic": {"A": ["A"]}}, "maps to itself"),
        ({"graphic": {"A": ["C"], "B": ["C"]}}, "'C' maps to both 'A' and 'B'"),
        ({"graphic": {"A": ["B"], "B": ["C"]}}, "'B' is both a new and an old name"),
    ],
)
def test_parse_mapping_errors(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_mapping(data)


def test_cli_map(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mapping = tmp_path / "styles.toml"
    mapping.write_text('[graphic]\nBox = ["Box 2"]\n', encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    a = make_doc(docs / "a.odg")
    b = make_odf(docs / "b.odg")
    (docs / "broken.odg").write_text("not a document")

    assert main(["map", str(docs), "--map", str(mapping)]) == 1
    captured = capsys.readouterr()
    assert (
        f"{a}: graphic: Box_20_2 -> Box; 1 reference(s) updated; 1 style(s) deleted" in captured.out
    )
    assert f"{b}: nothing to map" in captured.out
    assert "broken.odg: error:" in captured.err
    assert "Box_20_2" not in graphic_names(a)
