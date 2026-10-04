# lostyle

Copy styles from one LibreOffice / OpenDocument file into another — Draw (`.odg`),
Writer (`.odt`), Calc (`.ods`), Impress (`.odp`) and their flat XML variants
(`.fodg`, …). Works directly on the ODF XML (only depends on `lxml`); LibreOffice
does not need to be installed or running.

Copied styles bring their dependencies along: parent and next styles, gradients,
hatches, markers (arrowheads), dash patterns, fill images (embedded pictures),
font declarations, number formats, list styles, page layouts and master-page
backgrounds. The target's own automatic styles are never overwritten.

## Python API

```python
from lostyle import copy_styles, copy_all_styles, list_styles, OdfPackage

# one style (by internal or display name) plus everything it needs
report = copy_styles("template.odg", "drawing.odg", names=["Fancy Box"])

# all graphic styles and master pages, keep existing ones, write to a new file
report = copy_styles(
    "template.odg",
    "drawing.odg",
    families=["graphic", "master-page"],
    on_conflict="skip",  # "overwrite" (default) | "skip" | "rename"
    output="drawing-styled.odg",
)
print(report.summary())

# everything, including default styles
copy_all_styles("template.odt", "letter.odt")

for entry in list_styles(OdfPackage.open("template.odg"), ["graphic"]):
    print(entry.ref.name, entry.display_name)
```

### Renaming a style

```python
from lostyle import rename_style

result = rename_style("drawing.odg", "Fancy Box", "Corporate Box")
print(result)  # graphic:Fancy_20_Box -> Corporate_20_Box (Corporate Box), 3 reference(s) updated
```

Every reference is updated: parent/next styles, master pages, and shapes,
paragraphs and cells in the document body. The new name is stored the way
LibreOffice stores it (display name `Corporate Box`, internal name
`Corporate_20_Box`). Pass `family=` when the name exists in several families.
If another style already uses the new name, `StyleNameConflictError` is raised
and nothing is changed. Renaming an Impress master page also renames its
`<master>-title`, `<master>-outline1`, … presentation styles, which LibreOffice
links to the master page by name.

Families/kinds: `graphic`, `paragraph`, `text`, `list`, `table`, `table-cell`,
`table-column`, `table-row`, `drawing-page`, `presentation`, `number`,
`master-page`, `page-layout`, `gradient`, `hatch`, `marker`, `stroke-dash`,
`fill-image`, `opacity`, `font-face`, `default`, ….

## CLI

```
lostyle list template.odg -f graphic
lostyle copy template.odg drawing.odg -s "Fancy Box"
lostyle copy template.odg drawing.odg -f master-page --on-conflict rename -o out.odg
lostyle rename drawing.odg "Fancy Box" "Corporate Box" [-f graphic] [-o out.odg]
lostyle replace drawing.odg "Box 2" "Box copy" --with Box [--keep] [-o out.odg]
lostyle diff template.odg drawing.odg [-f graphic] [--exit-code]
```

Options of `copy`: `-f/--family` and `-s/--style` (repeatable), `-o/--output`,
`--on-conflict overwrite|skip|rename`, `--no-deps`, `--defaults`.

### Merging duplicate styles

```python
from lostyle import replace_style

replace_style("drawing.odg", ["Box 2", "Box copy"], "Box")
```

Everything that used `Box 2` or `Box copy` (shapes, paragraphs, cells, child
styles, master pages) now uses `Box`, and the duplicates are deleted
(`keep=True` keeps them). If a replaced style is an ancestor of the
replacement, the inheritance chain is re-linked so no style inherits from
itself. Fonts can be replaced too (`replace_style(doc, "Arial", "Liberation Sans")`).
Replacing an Impress master page also switches its `<master>-*` presentation
styles to the replacement master's ones.

### Comparing styles

`lostyle diff A B` lists, grouped by family/kind, the styles that exist only in
A (`-`) or only in B (`+`), and counts those in both. Styles are matched by kind
and internal name; their contents are not compared, and automatic styles are
ignored. With `--exit-code` it exits with 1 when the documents differ.

```
--- template.odg
+++ drawing.odg
graphic
  - Fancy_20_Box  (Fancy Box)
  + Corporate_20_Box  (Corporate Box)
1 only in template.odg, 1 only in drawing.odg, 36 in both
```

Note: LibreOffice stores styles under an encoded form of their display name
(`Fancy Box` → `Fancy_20_Box`); both forms are accepted.

## Development

```
uv sync
uv run pytest        # LibreOffice round-trip tests run when `soffice` is installed
uv run ruff check . && uv run mypy
```
