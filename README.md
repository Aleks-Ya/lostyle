# lostyle

Manage the styles of LibreOffice / OpenDocument files from the command line. It
supports Draw (`.odg`), Writer (`.odt`), Calc (`.ods`), Impress (`.odp`), their
templates (`.otg`, …) and their flat XML variants (`.fodg`, …). It works directly
on the ODF XML and only depends on `lxml`; LibreOffice doesn't need to be
installed or running.

What it does:

- copies styles from one document into another;
- renames a style;
- merges duplicate styles into one;
- compares the styles of two documents;
- finds and deletes unused styles;
- keeps a whole folder of documents in line with a template.

## Installation

```
pip install lostyle          # or: uv tool install lostyle
lostyle --help
uvx lostyle --help           # run once, without installing
```

From a source checkout: `uv tool install .` (or `pip install .`).

## Commands

```
lostyle list    DOC [-f FAMILY] [--automatic] [--usage | --unused]
lostyle copy    SOURCE TARGET [-s STYLE] [-f FAMILY] [--on-conflict overwrite|skip|rename]
                [--no-deps] [--defaults] [-o OUT]
lostyle rename  DOC OLD NEW [-f FAMILY] [-o OUT]
lostyle replace DOC OLD [OLD ...] --with NEW [-f FAMILY] [--keep] [-o OUT]
lostyle diff    A B [-f FAMILY] [--exit-code]
lostyle purge   PATH... [--keep TEMPLATE] [-f FAMILY] [-o OUT]
lostyle map     PATH... --map styles.toml [-o OUT]
lostyle audit   TEMPLATE PATH... [--map styles.toml] [-v] [--exit-code]
lostyle sync    TEMPLATE PATH... [--map styles.toml] [--purge] [--dry-run] [-v]
```

- **Style names.** Styles can be named by their display name (`Fancy Box`) or by
  the encoded internal name LibreOffice stores (`Fancy_20_Box`).
- **Families.** `-f` takes a family or kind: `graphic`, `paragraph`, `text`,
  `list`, `table`, `table-cell`, `table-column`, `table-row`, `drawing-page`,
  `presentation`, `number`, `master-page`, `page-layout`, `gradient`, `hatch`,
  `marker`, `stroke-dash`, `fill-image`, `opacity`, `font-face`, `default`, ….
  It is repeatable where the synopsis allows several.
- **Where results are written.** Commands that change a document save it in
  place unless `-o` is given.
- **Several documents.** `purge`, `map`, `audit` and `sync` accept several
  documents and directories, which are searched recursively. An error in one
  document is reported and the others are still processed; the exit code is 1 if
  any failed.

### list

Lists a document's styles with their display names:

- `--automatic` includes automatic styles;
- `--usage` shows how many references each style has;
- `--unused` shows only what `purge` would delete.

### copy

```
lostyle copy template.odg drawing.odg -s "Fancy Box"
lostyle copy template.odg drawing.odg -f master-page --on-conflict rename -o out.odg
```

Copies the selected styles, or all of them, together with what they depend on:

- parent and next styles;
- gradients, hatches, markers (arrowheads) and dash patterns;
- fill images (embedded pictures) and font declarations;
- number formats and list styles;
- page layouts and master-page backgrounds.

When a style already exists in the target, it is overwritten by default.
`--on-conflict skip` keeps the target's version, and `rename` copies it under a
new name such as `Fancy Box (1)`.

The target's automatic styles are never overwritten. `--no-deps` copies only the
selected styles, and `--defaults` also copies default styles. Copying the same
styles again changes nothing.

### rename

```
lostyle rename drawing.odg "Fancy Box" "Corporate Box"
```

Every reference to the style is updated: parent and next styles, master pages,
and the shapes, paragraphs and cells in the document. If another style already
has the new name, nothing is changed.

Renaming an Impress master page also renames its `<master>-title`,
`<master>-outline1`, … presentation styles, which LibreOffice links to the master
page by name.

### replace: merging duplicate styles

```
lostyle replace drawing.odg "Box 2" "Box copy" --with Box
```

Everything that used `Box 2` or `Box copy` now uses `Box`: shapes, paragraphs,
cells, child styles and master pages. The duplicates are then deleted;
`--keep` keeps them instead.

- **Inheritance.** If a replaced style is an ancestor of the replacement, the
  inheritance chain is re-linked so that no style inherits from itself.
- **Fonts.** Fonts can be replaced too:
  `lostyle replace doc.odg Arial --with "Liberation Sans"`.
- **Impress master pages.** Replacing one also switches its `<master>-*`
  presentation styles to the replacement master's ones.

### diff

```
$ lostyle diff template.odg drawing.odg
--- template.odg
+++ drawing.odg
graphic
  - Fancy_20_Box  (Fancy Box)
  + Corporate_20_Box  (Corporate Box)
1 only in template.odg, 1 only in drawing.odg, 36 in both
```

Lists, by family, the styles that exist only in A (`-`) or only in B (`+`).

- Styles are matched by family and name; their contents aren't compared.
- Automatic styles are ignored.
- `--exit-code` exits with 1 when the documents differ.

### purge

```
lostyle purge Diagrams/ --keep templates/Schematization.otg
```

Deletes the styles nothing uses, along with embedded pictures that only those
styles used.

- **What counts as used.** A style is used when the drawing, text or sheets use
  it, or when a used master page or another used style does.
- **Always kept.** Default styles are never deleted.
- **`--keep TEMPLATE`.** Also keeps every style the template has, so the
  template's palette stays available in each document.

## Keeping many documents in line with a template

Edit the styles in one template, then push them into every document:

```
lostyle audit templates/Schematization.otg Diagrams/ --map styles.toml
lostyle sync  templates/Schematization.otg Diagrams/ --map styles.toml --purge --dry-run
lostyle sync  templates/Schematization.otg Diagrams/ --map styles.toml --purge
```

### The mapping file

The mapping file (TOML) records once, for all documents, the old names of each
template style, grouped by family:

```toml
[graphic]
"Line: Association" = ["Line: Assosiation", "Assosiation line"]
"Page: part splitter" = "Page part splitter"

[master-page]
SchematizationTemplate = ["SchematizationTemplate_2"]
```

How each entry is applied:

- Each old style a document has is merged into the new one, as `replace` does.
- When the new style doesn't exist yet, the first old style is renamed to it
  instead.
- Old names a document doesn't have are ignored.

`lostyle map` applies a mapping file on its own.

### audit

Shows what the mapping file is still missing. It lists the styles documents
would still use after a sync but that the template doesn't have, with how many
documents use each. `-v` also lists the documents.

```
$ lostyle audit templates/Schematization.otg Diagrams/ --map styles.toml
graphic
    74  Line: Assosiation
    62  Slide title
2 style(s) used in 80 of 232 document(s) are not in the template
```

Add these names to the mapping file, or the styles to the template, until
`audit` reports nothing. Nothing is saved.

### sync

For each document of the template's type, `sync`:

1. copies all of the template's styles over the document's;
2. moves old style names to the template's names, as listed in the mapping file;
3. cleans up: it deletes the automatic styles a replaced master page left behind,
   and with `--purge` also every unused style that isn't in the template.
   Template styles stay even when unused.

How it behaves:

- **Other document types are skipped.** For example, a spreadsheet among
  drawings is left alone.
- **Only changed documents are saved.** Running `sync` again on synced documents
  changes nothing.
- **`--dry-run`** reports what would change without saving anything.
- **`-v`** shows the mapped and deleted styles.

Note that master pages are copied as well, page size included. A document whose
master page has the same name as the template's, but a different page size, gets
the template's page size.

## Development

```
uv sync
uv run pytest        # LibreOffice round-trip tests run when `soffice` is installed
uv run ruff check . && uv run mypy
```
