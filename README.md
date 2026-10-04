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

Families/kinds: `graphic`, `paragraph`, `text`, `list`, `table`, `table-cell`,
`table-column`, `table-row`, `drawing-page`, `presentation`, `number`,
`master-page`, `page-layout`, `gradient`, `hatch`, `marker`, `stroke-dash`,
`fill-image`, `opacity`, `font-face`, `default`, ….

## CLI

```
lostyle list template.odg -f graphic
lostyle copy template.odg drawing.odg -s "Fancy Box"
lostyle copy template.odg drawing.odg -f master-page --on-conflict rename -o out.odg
```

Options of `copy`: `-f/--family` and `-s/--style` (repeatable), `-o/--output`,
`--on-conflict overwrite|skip|rename`, `--no-deps`, `--defaults`.

Note: LibreOffice stores styles under an encoded form of their display name
(`Fancy Box` → `Fancy_20_Box`); both forms are accepted.

## Development

```
uv sync
uv run pytest        # LibreOffice round-trip tests run when `soffice` is installed
uv run ruff check . && uv run mypy
```
