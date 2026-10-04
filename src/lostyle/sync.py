"""Bringing many documents in line with a template: ``sync`` and ``audit``."""

from __future__ import annotations

import os
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path

from lxml import etree

from .collect import StyleIndex
from .copier import CopyReport, Source, _as_package, copy_all_styles
from .mapping import MappingResult, StyleMapping, apply_mapping
from .package import OdfError, OdfPackage
from .refs import DEFAULT, StyleRef
from .usage import PurgeResult, _reachable, purge_unused

DOCUMENT_SUFFIXES = frozenset(
    f".{prefix}{letter}" for prefix in ("od", "ot", "fod") for letter in "gtsp"
)
# Errors that make one document fail without stopping a batch.
BATCH_ERRORS = (OdfError, LookupError, ValueError, OSError, zipfile.BadZipFile, etree.LxmlError)


def find_documents(paths: Iterable[str | os.PathLike[str]]) -> list[Path]:
    """Expand directories (recursively) into the OpenDocument files they contain.

    Files given explicitly are kept as they are; hidden files (such as LibreOffice
    lock files) are skipped when searching directories.
    """
    found: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            found.extend(
                sorted(
                    f
                    for f in p.rglob("*")
                    if f.suffix.lower() in DOCUMENT_SUFFIXES
                    and not any(part.startswith(".") for part in f.relative_to(p).parts)
                    and f.is_file()
                )
            )
        else:
            found.append(p)
    return list(dict.fromkeys(found))


def document_class(pkg: OdfPackage) -> str:
    """The media type without ``-template``: templates match their documents."""
    return pkg.mimetype.removesuffix("-template")


def _same_file(a: Path | None, b: Path) -> bool:
    try:
        return a is not None and a.exists() and a.samefile(b)
    except OSError:
        return False


@dataclass
class SyncResult:
    path: Path
    mapping: MappingResult | None = None
    copy: CopyReport | None = None
    purge: PurgeResult | None = None
    skipped: str | None = None
    error: str | None = None

    @property
    def changed(self) -> bool:
        copied = self.copy is not None and bool(
            self.copy.copied or self.copy.overwritten or self.copy.renamed
        )
        purged = self.purge is not None and bool(self.purge.deleted)
        return bool(self.mapping) or copied or purged

    def summary(self) -> str:
        if self.error is not None:
            return f"{self.path}: error: {self.error}"
        if self.skipped is not None:
            return f"{self.path}: skipped ({self.skipped})"
        parts = []
        if self.mapping:
            parts.append(f"{len(self.mapping.changes)} old name(s) mapped")
        if self.copy is not None:
            if self.copy.overwritten:
                parts.append(f"{len(self.copy.overwritten)} updated")
            if self.copy.copied:
                parts.append(f"{len(self.copy.copied)} added")
        if self.purge is not None and self.purge.deleted:
            parts.append(f"{len(self.purge.deleted)} unused deleted")
        return f"{self.path}: {', '.join(parts) if parts else 'up to date'}"

    def details(self) -> str:
        """Mapping changes, warnings and deleted styles, indented."""
        lines: list[str] = []
        if self.mapping is not None and (self.mapping or self.mapping.warnings):
            lines.extend(str(self.mapping).splitlines())
        if self.copy is not None:
            lines.extend(f"warning: {w}" for w in self.copy.warnings)
            lines.extend(f"unresolved: {m}" for m in self.copy.unresolved)
        if self.purge is not None and self.purge.deleted:
            lines.extend(str(self.purge).splitlines())
        return "\n".join(f"    {line}" for line in lines)


def sync_documents(
    template: Source,
    paths: Iterable[str | os.PathLike[str]],
    *,
    mapping: StyleMapping | None = None,
    purge: bool = False,
    dry_run: bool = False,
    on_result: Callable[[SyncResult], None] | None = None,
) -> list[SyncResult]:
    """Bring every document under ``paths`` in line with ``template``'s styles.

    Per document: copy all of the template's styles over the document's
    (``copy_all_styles``, overwriting), apply ``mapping`` (old names -> template names,
    which now all exist), then delete the unused automatic styles that replaced master
    pages leave behind, or, with ``purge``, every unused style not in the template.
    Documents of another type than the template (e.g. a spreadsheet next to drawings)
    are skipped. An error in one document is recorded in its result and the others are
    still processed.

    Args:
        template: The document (usually a template) holding the current styles.
        paths: Documents and/or directories (searched recursively).
        mapping: Old-to-new style names, see ``lostyle.mapping``.
        purge: Also delete unused styles that are not in the template.
        dry_run: Do everything in memory but save nothing.
        on_result: Called with each document's result as soon as it is done.
    """
    tpl = _as_package(template)
    tpl_class = document_class(tpl)
    keep = [e.ref for e in StyleIndex(tpl).styles()]
    results: list[SyncResult] = []
    for path in find_documents(paths):
        result = SyncResult(path)
        try:
            pkg = _open_matching(path, tpl, tpl_class, result)
            if pkg is not None:
                _update(pkg, tpl, mapping, result)
                result.purge = purge_unused(pkg, keep=keep, automatic_only=not purge)
                if result.changed and not dry_run:
                    pkg.save()
        except BATCH_ERRORS as exc:
            result.error = str(exc)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results


def _update(
    pkg: OdfPackage, tpl: OdfPackage, mapping: StyleMapping | None, result: SyncResult
) -> None:
    result.copy = copy_all_styles(tpl, pkg)
    if mapping:
        result.mapping = apply_mapping(pkg, mapping)


def _open_matching(
    path: Path, tpl: OdfPackage, tpl_class: str, result: SyncResult
) -> OdfPackage | None:
    """Open ``path`` if it is a document of the template's type, else mark it skipped."""
    if _same_file(tpl.path, path):
        result.skipped = "the template itself"
        return None
    pkg = OdfPackage.open(path)
    if document_class(pkg) != tpl_class:
        result.skipped = f"{pkg.mimetype or 'unknown type'}, template is {tpl_class}"
        return None
    return pkg


@dataclass
class AuditResult:
    """Styles that documents use but the template doesn't have, with the documents."""

    styles: dict[StyleRef, list[Path]] = field(default_factory=dict)
    display_names: dict[StyleRef, str] = field(default_factory=dict)
    documents: int = 0
    skipped: list[SyncResult] = field(default_factory=list)  # skipped or failed

    def __bool__(self) -> bool:
        return bool(self.styles)

    def format(self, verbose: bool = False) -> str:
        lines = [r.summary() for r in self.skipped]
        if not self.styles:
            lines.append(f"all styles used by {self.documents} document(s) are in the template")
            return "\n".join(lines)
        by_kind = sorted(self.styles.items(), key=lambda item: (item[0].kind, -len(item[1])))
        for kind, items in groupby(by_kind, key=lambda item: item[0].kind):
            lines.append(kind)
            for ref, docs in items:
                lines.append(f"  {len(docs):4}  {self.display_names[ref]}")
                if verbose:
                    lines.extend(f"          {d}" for d in docs)
        users = len({d for docs in self.styles.values() for d in docs})
        lines.append(
            f"{len(self.styles)} style(s) used in {users} of {self.documents} document(s) "
            "are not in the template"
        )
        return "\n".join(lines)


def audit_documents(
    template: Source,
    paths: Iterable[str | os.PathLike[str]],
    *,
    mapping: StyleMapping | None = None,
) -> AuditResult:
    """Find the styles documents would still use after ``sync_documents``, but the
    template lacks.

    These are the names still to add to the mapping (or to the template). Nothing is
    saved.
    """
    tpl = _as_package(template)
    tpl_class = document_class(tpl)
    known = {(e.ref.kind, e.ref.name) for e in StyleIndex(tpl).styles()}
    audit = AuditResult()
    for path in find_documents(paths):
        result = SyncResult(path)
        try:
            pkg = _open_matching(path, tpl, tpl_class, result)
            if pkg is not None:
                _update(pkg, tpl, mapping, result)
                index = StyleIndex(pkg)
                for ref in sorted(_reachable(pkg, index, [])):
                    if ref.automatic or ref.kind == DEFAULT or (ref.kind, ref.name) in known:
                        continue
                    audit.styles.setdefault(ref, []).append(path)
                    audit.display_names.setdefault(ref, index[ref].display_name)
                audit.documents += 1
        except BATCH_ERRORS as exc:
            result.error = str(exc)
        if result.skipped is not None or result.error is not None:
            audit.skipped.append(result)
    return audit
