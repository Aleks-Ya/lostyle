# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```
uv sync                                   # create .venv with dev deps
uv run pytest                             # all tests
uv run pytest tests/test_copier.py::test_rename_copies_under_new_names   # single test
uv run ruff check . && uv run ruff format .
uv run mypy                               # strict, src/ only
uv run lostyle --help                     # CLI (list / copy / rename / diff)
```

`tests/test_libreoffice.py` runs real LibreOffice (`soffice --headless --convert-to`) with an isolated profile and is skipped when `soffice` is absent. Tests import helpers as top-level modules (`from helpers import make_odf`), relying on pytest's default rootdir/prepend import mode — there is no `conftest.py` or `tests/__init__.py`.

## Architecture

`lostyle` copies styles between OpenDocument files by editing the ODF XML directly (zipfile + lxml only; no UNO, and odfdo was deliberately not used). Pipeline for copying: **package → index → closure → copy**; renaming reuses the index and reference table.

- `package.py` — `OdfPackage` holds a zipped package as raw entries, parsing `styles.xml` / `content.xml` / `manifest.xml` lazily; only parts marked modified are re-serialized on save (`mimetype` first, stored; signature file dropped once modified; atomic replace). A flat document (`.fodg` etc.) is a single tree that serves as both `styles_root` and `content_root`, and cannot hold embedded files.
- `refs.py` — the domain model. A style is identified by `StyleRef(kind, name, automatic)`, where `kind` is the `style:family` for `style:style` or a fixed kind for other elements (`list`, `number`, `gradient`, `marker`, `master-page`, `page-layout`, `font-face`, `default`, …). `_FIXED_REFS` and `_ref_kinds` are the table of which attributes reference which kinds; some are context-dependent (`draw:style-name` on a master page → `drawing-page`, otherwise `graphic`; `text:style-name` / `table:style-name` depend on the element tag). Multi-valued attributes (`draw:class-names`) yield one `Reference` per name; always rewrite through `Reference.replace`. **Supporting a new kind of reference usually means editing only this table** (it serves both copy and rename).
- `collect.py` — `StyleIndex` indexes only the *styles part* (font-face-decls, office:styles, styles.xml automatic-styles, master-styles), never content.xml automatic styles. Reference resolution prefers automatic styles when the referrer is automatic or a master page (`uses_automatic_styles`). `resolve_closure` does a DFS emitting dependencies before dependents, with a `follow` predicate to prune.
- `copier.py` — `_Copier` decides per ref (`copy`/`overwrite`/`skip`/`rename`), plans final names, deep-copies elements, rewrites references inside copies via the rename map, copies `Pictures/*` (reusing identical bytes, renaming on collision; base64-embedding into flat targets), and inserts into the right container. Rules that are easy to break:
  - Automatic styles are never overwritten: on a name clash (checked against both styles.xml and content.xml automatic styles) they are always renamed.
  - Existing font-faces are always kept; `rename` on default styles degrades to skip.
  - With `skip`, a skipped style's dependencies are not traversed.
  - After copying, the target is re-indexed and dangling references are reported in `CopyReport.unresolved` (not raised).
  - A target passed as a path is saved in place; one passed as `OdfPackage` is left unsaved unless `output` is given.
- `rename.py` — `rename_style` renames one non-automatic style in place. It scans every style container of styles.xml plus content.xml's automatic styles and `office:body` with `iter_refs`, and rewrites only references that *resolve* to the renamed style (content.xml automatic styles shadow common styles of the same name). All conflict checks run and all matches are collected before anything is modified. Renaming a master page also renames the `<master>-*` presentation styles: LibreOffice links them by name prefix and otherwise silently replaces them with defaults (verified by LO round-trip). `encode_style_name` (`ns.py`) reproduces LO's encoding: every `_` and `:` and any non-XML-name character becomes `_<hex>_`.
- `diff.py` — `diff_styles` compares two documents' non-automatic styles by `(kind, internal name)` only (no content comparison, by design); `StyleDiff.format` renders the CLI text.

LibreOffice rewrites internal style names to an encoded display name on save (`Fancy Box` → `Fancy_20_Box`, decoded by `ns.decode_style_name`); `StyleIndex.find` matches internal, display and decoded names, so tests against LO-generated files should select styles by display name. When asserting LO round-trips, avoid marker properties LO overrides (e.g. `fo:color` is ignored when `style:use-window-font-color="true"`).
