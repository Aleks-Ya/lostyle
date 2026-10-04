"""Copying styles from one OpenDocument file into another."""

from __future__ import annotations

import base64
import copy
import os
import posixpath
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from lxml import etree

from .collect import MissingRef, StyleIndex, resolve_closure, uses_automatic_styles
from .ns import NS, prefixed, q
from .package import OdfPackage
from .refs import (
    DEFAULT,
    FONT_FACE,
    MASTER_PAGE,
    StyleRef,
    display_name_attr,
    element_kind,
    element_name,
    iter_file_refs,
    iter_refs,
    name_attr,
)

OnConflict = Literal["overwrite", "skip", "rename"]
_Action = Literal["copy", "overwrite", "skip", "rename"]
Source = str | os.PathLike[str] | OdfPackage


class StyleNotFoundError(LookupError):
    """A requested style does not exist in the source document."""


@dataclass
class CopyReport:
    copied: list[StyleRef] = field(default_factory=list)
    overwritten: list[StyleRef] = field(default_factory=list)
    skipped: list[StyleRef] = field(default_factory=list)
    renamed: dict[StyleRef, str] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    unresolved: list[MissingRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        for title, refs in (
            ("copied", self.copied),
            ("overwritten", self.overwritten),
            ("skipped (already in target)", self.skipped),
        ):
            if refs:
                lines.append(f"{title}: {len(refs)}")
                lines.extend(f"  {r}" for r in refs)
        if self.renamed:
            lines.append(f"renamed: {len(self.renamed)}")
            lines.extend(f"  {r} -> {n}" for r, n in self.renamed.items())
        if self.files:
            lines.append(f"embedded files: {len(self.files)}")
            lines.extend(f"  {f}" for f in self.files)
        if self.unresolved:
            lines.append(f"unresolved references in target: {len(self.unresolved)}")
            lines.extend(f"  {m}" for m in self.unresolved)
        lines.extend(f"warning: {w}" for w in self.warnings)
        return "\n".join(lines) if lines else "nothing to copy"


def _container_for(ref: StyleRef) -> str:
    if ref.kind == FONT_FACE:
        return "office:font-face-decls"
    if ref.kind == MASTER_PAGE:
        return "office:master-styles"
    if ref.automatic:
        return "office:automatic-styles"
    return "office:styles"


def _as_package(doc: Source) -> OdfPackage:
    return doc if isinstance(doc, OdfPackage) else OdfPackage.open(doc)


class _Copier:
    def __init__(
        self, src: OdfPackage, dst: OdfPackage, on_conflict: OnConflict, report: CopyReport
    ) -> None:
        self.src = src
        self.dst = dst
        self.on_conflict = on_conflict
        self.report = report
        self.src_index = StyleIndex(src)
        self.dst_index = StyleIndex(dst)
        self.actions: dict[StyleRef, _Action] = {}
        self.final_names: dict[StyleRef, str] = {}
        self.file_map: dict[str, str] = {}
        self._taken: dict[tuple[str, bool], set[str]] = {}

    # ------------------------------------------------------------- planning
    def select_roots(
        self, kinds: set[str] | None, names: Iterable[str] | None, include_defaults: bool
    ) -> list[StyleRef]:
        roots: list[StyleRef] = []
        if names:
            for name in names:
                found = self.src_index.find(name, kinds)
                if not found:
                    where = f" in families {sorted(kinds)}" if kinds else ""
                    raise StyleNotFoundError(f"style {name!r} not found{where}")
                roots.extend(found)
        else:
            roots.extend(e.ref for e in self.src_index.styles(kinds) if e.ref.kind != DEFAULT)
        if include_defaults:
            roots.extend(
                e.ref
                for e in self.src_index.styles([DEFAULT])
                if kinds is None or e.ref.name in kinds
            )
        return list(dict.fromkeys(roots))

    def action(self, ref: StyleRef) -> _Action:
        if ref not in self.actions:
            self.actions[ref] = self._decide(ref)
        return self.actions[ref]

    def _decide(self, ref: StyleRef) -> _Action:
        if ref.automatic:
            # Automatic styles are private to their master page / page layout:
            # never replace the target's, pick a free name instead.
            return "rename" if ref.name in self._taken_names(ref) else "copy"
        if ref not in self.dst_index:
            return "copy"
        if ref.kind == FONT_FACE:
            return "skip"  # same font declaration name means the same font
        if self.on_conflict == "rename" and ref.kind == DEFAULT:
            return "skip"  # default styles have no name to change
        return self.on_conflict

    def _taken_names(self, ref: StyleRef) -> set[str]:
        key = (ref.kind, ref.automatic)
        if key not in self._taken:
            taken: set[str] = set()
            if ref.automatic:
                for container in self.dst.automatic_style_containers():
                    for el in container.iterchildren(tag=etree.Element):
                        if element_kind(el) == ref.kind and (name := element_name(el)):
                            taken.add(name)
            else:
                for entry in self.dst_index.styles([ref.kind]):
                    taken.update((entry.ref.name, entry.display_name))
            self._taken[key] = taken
        return self._taken[key]

    def _unique(self, base: str, taken: set[str], fmt: str) -> tuple[str, int]:
        n = 1
        while fmt.format(base=base, n=n) in taken:
            n += 1
        return fmt.format(base=base, n=n), n

    def plan_names(self, order: list[StyleRef]) -> None:
        for ref in order:
            if self.action(ref) != "rename":
                self.final_names[ref] = ref.name
                continue
            taken = self._taken_names(ref)
            new_name, _ = self._unique(ref.name, taken, "{base}_{n}")
            taken.add(new_name)
            self.final_names[ref] = new_name
            self.report.renamed[ref] = new_name

    # ------------------------------------------------------------- copying
    def copy(self, ref: StyleRef) -> StyleRef | None:
        """Copy one style into the target; return its ref in the target (None if skipped)."""
        action = self.action(ref)
        if action == "skip":
            self.report.skipped.append(ref)
            return None
        el = copy.deepcopy(self.src_index[ref].element)
        new_name = self.final_names[ref]
        if new_name != ref.name:
            el.set(name_attr(el), new_name)
            disp_attr = display_name_attr(el)
            if display := el.get(disp_attr):
                taken = self._taken_names(ref)
                new_display, _ = self._unique(display, taken, "{base} ({n})")
                taken.add(new_display)
                el.set(disp_attr, new_display)
        self._rewrite_refs(ref, el)
        self._copy_files(el)

        container = self.dst.container(_container_for(ref), create=True)
        assert container is not None
        existing = self.dst_index.get(ref) if action == "overwrite" else None
        if existing is not None:
            parent = existing.element.getparent()
            assert parent is not None
            parent.replace(existing.element, el)
            self.report.overwritten.append(ref)
        else:
            if ref.kind == DEFAULT:
                container.insert(0, el)
            else:
                container.append(el)
            self.report.copied.append(ref)
        return StyleRef(ref.kind, new_name, ref.automatic)

    def _rewrite_refs(self, ref: StyleRef, el: etree._Element) -> None:
        prefer_auto = uses_automatic_styles(ref)
        for r in iter_refs(el, ref.kind):
            target = self.src_index.resolve(r.kinds, r.value, prefer_auto)
            if target is not None and self.final_names.get(target, r.value) != r.value:
                r.node.set(r.attr, self.final_names[target])

    def _copy_files(self, el: etree._Element) -> None:
        for node, path in iter_file_refs(el):
            if not self.src.has_file(path):
                self.report.warnings.append(f"embedded file {path!r} missing in source")
                continue
            data = self.src.read_file(path)
            if self.dst.flat:
                for attr in [str(a) for a in node.attrib]:
                    if attr.startswith(f"{{{NS['xlink']}}}"):
                        del node.attrib[attr]
                binary = node.makeelement(q("office:binary-data"))
                binary.text = base64.b64encode(data).decode("ascii")
                node.insert(0, binary)
                continue
            node.set(q("xlink:href"), self._target_file(path, data))

    def _target_file(self, path: str, data: bytes) -> str:
        if path in self.file_map:
            return self.file_map[path]
        new_path = path
        stem, ext = posixpath.splitext(path)
        n = 0
        while self.dst.has_file(new_path) and self.dst.read_file(new_path) != data:
            n += 1
            new_path = f"{stem}_{n}{ext}"
        if not self.dst.has_file(new_path):
            self.dst.add_file(new_path, data, self.src.media_type(path))
            self.report.files.append(new_path)
        self.file_map[path] = new_path
        return new_path


def copy_styles(
    source: Source,
    target: Source,
    *,
    families: Iterable[str] | None = None,
    names: Iterable[str] | None = None,
    on_conflict: OnConflict = "overwrite",
    include_dependencies: bool = True,
    include_defaults: bool = False,
    output: str | os.PathLike[str] | None = None,
) -> CopyReport:
    """Copy styles from ``source`` into ``target``.

    Args:
        source: Path of the document to copy styles from, or an open ``OdfPackage``.
        target: Path of the document to copy styles into, or an open ``OdfPackage``.
        families: Only copy styles of these families/kinds (e.g. ``graphic``,
            ``paragraph``, ``table-cell``, ``master-page``, ``gradient``).
            Default: all.
        names: Only copy styles with these names (internal or display names).
            Default: all styles of the selected families.
        on_conflict: What to do when a style of the same name exists in the
            target: ``overwrite`` it, ``skip`` copying, or ``rename`` the copy.
        include_dependencies: Also copy styles the selected ones depend on
            (parents, gradients, markers, fonts, page layouts, ...).
        include_defaults: Also copy default styles (``style:default-style``).
        output: Where to save the result. If omitted, a target given as a path is
            saved in place; a target given as ``OdfPackage`` is left unsaved.
    """
    if on_conflict not in ("overwrite", "skip", "rename"):
        raise ValueError(f"invalid on_conflict: {on_conflict!r}")
    src = _as_package(source)
    dst = _as_package(target)
    report = CopyReport()
    copier = _Copier(src, dst, on_conflict, report)

    kinds = set(families) if families else None
    roots = copier.select_roots(kinds, names, include_defaults)
    closure = resolve_closure(
        copier.src_index,
        roots,
        include_dependencies=include_dependencies,
        follow=lambda ref: copier.action(ref) != "skip",
    )
    copier.plan_names(closure.order)
    inserted = [r for ref in closure.order if (r := copier.copy(ref)) is not None]

    if inserted:
        dst.mark_styles_modified()
        final_index = StyleIndex(dst)
        for ref in inserted:
            for attr, value, resolved in final_index.references(ref):
                if resolved is None:
                    report.unresolved.append(MissingRef(ref, prefixed(attr), value))

    if output is not None:
        dst.save(output)
    elif not isinstance(target, OdfPackage) and inserted:
        dst.save()
    if dst.dropped_signature:
        report.warnings.append("target's digital signature was removed (no longer valid)")
    return report


def copy_all_styles(
    source: Source,
    target: Source,
    *,
    on_conflict: OnConflict = "overwrite",
    output: str | os.PathLike[str] | None = None,
) -> CopyReport:
    """Copy every style, including default styles, from ``source`` into ``target``."""
    return copy_styles(
        source, target, on_conflict=on_conflict, include_defaults=True, output=output
    )
