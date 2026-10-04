"""Which styles a document uses, and deleting the ones it doesn't."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field

from lxml import etree

from .collect import StyleIndex, resolve_closure
from .copier import Source, _as_package
from .ns import q
from .package import CONTENT_XML, MANIFEST_XML, STYLES_XML, OdfPackage
from .refs import (
    DEFAULT,
    MASTER_PAGE,
    OUTLINE,
    PRESENTATION_PAGE_LAYOUT,
    StyleRef,
    element_kind,
    element_name,
    iter_file_refs,
)
from .rename import _STYLES_CONTAINERS, _linked_presentation_styles, _resolved_refs

# Kinds that are used implicitly and never deleted.
_NEVER_PURGED = {DEFAULT, OUTLINE, PRESENTATION_PAGE_LAYOUT}

Keep = Source | Iterable[StyleRef] | None


@dataclass
class PurgeResult:
    deleted: list[StyleRef] = field(default_factory=list)
    files: list[str] = field(default_factory=list)  # embedded pictures no longer used

    def __str__(self) -> str:
        if not self.deleted:
            return "nothing to purge"
        files = f" and {len(self.files)} embedded file(s)" if self.files else ""
        lines = [f"deleted {len(self.deleted)} unused style(s){files}"]
        lines.extend(f"  {r}" for r in self.deleted)
        lines.extend(f"  {f}" for f in self.files)
        return "\n".join(lines)


def style_usage(document: Source) -> dict[StyleRef, int]:
    """Count the references to each (non-automatic) style, from anywhere in the document.

    References from styles that are themselves unused count too; see ``unused_styles``
    for what is actually unused.
    """
    pkg = _as_package(document)
    index = StyleIndex(pkg)
    counts = dict.fromkeys(sorted(e.ref for e in index.styles()), 0)
    for _, target, _, _ in _resolved_refs(pkg, index):
        if target is not None and target in counts:
            counts[target] += 1
    return counts


def unused_styles(
    document: Source,
    *,
    keep: Keep = None,
    families: Iterable[str] | None = None,
    automatic_only: bool = False,
) -> list[StyleRef]:
    """Styles that nothing in use reaches: what ``purge_unused`` would delete."""
    pkg = _as_package(document)
    return _unused(pkg, StyleIndex(pkg), keep, families, automatic_only)


def purge_unused(
    document: Source,
    *,
    keep: Keep = None,
    families: Iterable[str] | None = None,
    automatic_only: bool = False,
    output: str | os.PathLike[str] | None = None,
) -> PurgeResult:
    """Delete styles that nothing in the document uses, directly or indirectly.

    A style is used when the drawing/text/sheets, a used master page or another used
    style refers to it. Default styles are never deleted.

    Args:
        document: Path of the document, or an open ``OdfPackage``.
        keep: Styles to keep even if unused (and what they depend on): a document such
            as the template the styles come from, or a list of ``StyleRef``.
        families: Only delete styles of these families/kinds.
        automatic_only: Only delete unused automatic styles of the styles part, e.g. the
            ones a replaced master page leaves behind.
        output: Where to save the result. If omitted, a document given as a path is
            saved in place; one given as ``OdfPackage`` is left unsaved.

    Embedded pictures that only deleted styles used are removed as well.
    """
    pkg = _as_package(document)
    index = StyleIndex(pkg)
    result = PurgeResult(_unused(pkg, index, keep, families, automatic_only))
    pictures: set[str] = set()
    for ref in result.deleted:
        el = index[ref].element
        pictures.update(path for _, path in iter_file_refs(el))
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    if result.deleted:
        pkg.mark_styles_modified()
        result.files = [
            path
            for path in sorted(pictures)
            if pkg.has_file(path) and not _file_referenced(pkg, path)
        ]
        for path in result.files:
            pkg.remove_file(path)

    if output is not None:
        pkg.save(output)
    elif not isinstance(document, OdfPackage) and result.deleted:
        pkg.save()
    return result


def _unused(
    pkg: OdfPackage,
    index: StyleIndex,
    keep: Keep,
    families: Iterable[str] | None,
    automatic_only: bool,
) -> list[StyleRef]:
    reached = _reachable(pkg, index, _keep_refs(index, keep))
    wanted = set(families) if families is not None else None
    return sorted(
        ref
        for ref in index.entries
        if ref not in reached
        and ref.kind not in _NEVER_PURGED
        and (wanted is None or ref.kind in wanted)
        and (ref.automatic or not automatic_only)
    )


def _keep_refs(index: StyleIndex, keep: Keep) -> list[StyleRef]:
    if keep is None:
        return []
    if isinstance(keep, (str, os.PathLike, OdfPackage)):
        names = {(e.ref.kind, e.ref.name) for e in StyleIndex(_as_package(keep)).styles()}
    else:
        names = {(r.kind, r.name) for r in keep}
    return [ref for kind, name in sorted(names) if (ref := StyleRef(kind, name)) in index]


def _reachable(pkg: OdfPackage, index: StyleIndex, keep: Iterable[StyleRef]) -> set[StyleRef]:
    """Styles used by the document's content, its used master pages, or ``keep``."""
    roots = list(keep)
    roots.extend(e.ref for e in index.styles(_NEVER_PURGED))
    for _, target, referrer, _ in _resolved_refs(pkg, index):
        # a content-part target that is automatic lives in content.xml, not in the index
        if referrer is None and target is not None and (pkg.flat or not target.automatic):
            roots.append(target)
    # Be conservative about references this library doesn't model (Writer's notes
    # configuration, index templates, ...): a name mentioned outside style definitions
    # keeps the style of that name.
    mentioned = _mentioned_names(pkg)
    roots.extend(ref for ref in index.entries if not ref.automatic and ref.name in mentioned)

    reached = set(resolve_closure(index, roots).order)
    # Impress links presentation styles to their master page by name only
    masters = [m for m in reached if m.kind == MASTER_PAGE]
    linked = [r for m in masters for r, _ in _linked_presentation_styles(index, m)]
    reached.update(resolve_closure(index, linked).order)
    return reached


def _mentioned_names(pkg: OdfPackage) -> set[str]:
    """Values of ``*name(s)`` attributes outside style definitions."""
    names: set[str] = set()

    def collect(el: etree._Element) -> None:
        for node in el.iter(tag=etree.Element):
            for attr, value in node.attrib.items():
                if str(attr).endswith(("name", "names")):
                    names.update(str(value).split())

    styles_root = pkg.styles_root
    for container_name in _STYLES_CONTAINERS:
        container = styles_root.find(q(container_name))
        if container is None:
            continue
        for child in container.iterchildren(tag=etree.Element):
            if not (element_kind(child) and element_name(child)):
                collect(child)
    content_root = pkg.content_root
    if content_root is None:
        return names
    if content_root is not styles_root:
        auto = content_root.find(q("office:automatic-styles"))
        if auto is not None:
            collect(auto)
    body = content_root.find(q("office:body"))
    if body is not None:
        collect(body)
    return names


def _file_referenced(pkg: OdfPackage, path: str) -> bool:
    """Whether any XML of the package still mentions the embedded file ``path``."""
    roots = [pkg.styles_root]
    if (content := pkg.content_root) is not None and content is not pkg.styles_root:
        roots.append(content)
    for root in roots:
        for node in root.iter(tag=etree.Element):
            if any(path in str(v) for v in node.attrib.values()):
                return True
    needle = path.encode()
    return any(
        needle in pkg.read_file(name)
        for name in pkg.file_names()
        if name.endswith(".xml") and name not in (STYLES_XML, CONTENT_XML, MANIFEST_XML)
    )
