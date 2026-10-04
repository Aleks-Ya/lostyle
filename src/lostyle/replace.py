"""Replacing styles with another style, e.g. to merge duplicates."""

from __future__ import annotations

import copy
import os
from collections.abc import Iterable
from dataclasses import dataclass, field

from lxml import etree

from .collect import StyleIndex
from .copier import Source, _as_package
from .ns import q
from .package import OdfPackage
from .refs import DEFAULT, FONT_FACE, MASTER_PAGE, Reference, StyleRef
from .rename import _find_one, _linked_presentation_styles, _matching_refs

_PARENT = q("style:parent-style-name")


@dataclass
class ReplaceResult:
    replacement: StyleRef
    replaced: list[StyleRef]
    references: int = 0
    deleted: bool = True
    linked: dict[StyleRef, StyleRef] = field(default_factory=dict)  # Impress master styles
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        olds = ", ".join(r.name for r in self.replaced)
        count = len(self.replaced) + len(self.linked)
        action = f"{count} style(s) deleted" if self.deleted else "old styles kept"
        lines = [f"{self.replacement.kind}: {olds} -> {self.replacement.name}; "
                 f"{self.references} reference(s) updated; {action}"]  # fmt: skip
        lines.extend(f"  also replaced {o} -> {n.name}" for o, n in self.linked.items())
        lines.extend(f"warning: {w}" for w in self.warnings)
        return "\n".join(lines)


def replace_style(
    document: Source,
    old: str | Iterable[str],
    replacement: str,
    *,
    family: str | None = None,
    keep: bool = False,
    output: str | os.PathLike[str] | None = None,
) -> ReplaceResult:
    """Make everything that uses ``old`` use ``replacement`` instead, then delete ``old``.

    Args:
        document: Path of the document, or an open ``OdfPackage``.
        old: Name(s) of the style(s) to replace (internal, display or decoded name).
            They are looked up in the replacement's family.
        replacement: Name of the style to use instead.
        family: Family/kind; required when ``replacement`` exists in several families.
        keep: Keep the replaced styles in the document (unused) instead of deleting them.
        output: Where to save the result. If omitted, a document given as a path is
            saved in place; one given as ``OdfPackage`` is left unsaved.

    Raises:
        StyleNotFoundError: a style does not exist.
        AmbiguousStyleError: ``replacement`` exists in several families and ``family``
            is not given.
        ValueError: nothing to replace, a style would replace itself, or default styles
            are involved.

    Replacing an Impress master page also replaces its ``<master>-*`` presentation
    styles with the replacement master's counterparts (listed in ``ReplaceResult.linked``).
    """
    names = [old] if isinstance(old, str) else list(old)
    if not names:
        raise ValueError("no style to replace given")
    pkg = _as_package(document)
    index = StyleIndex(pkg)

    target = _find_one(index, replacement, family)
    if target.kind == DEFAULT:
        raise ValueError("default styles cannot be replaced")
    old_refs = list(dict.fromkeys(_find_one(index, name, target.kind) for name in names))
    if target in old_refs:
        raise ValueError(f"{target} cannot replace itself")

    mapping: dict[StyleRef, StyleRef] = dict.fromkeys(old_refs, target)
    result = ReplaceResult(target, old_refs, deleted=not keep)
    if target.kind == MASTER_PAGE:
        counterparts = dict((s, r) for r, s in _linked_presentation_styles(index, target))
        for old_master in old_refs:
            for linked, suffix in _linked_presentation_styles(index, old_master):
                new = counterparts.get(suffix)
                if new is None:
                    result.warnings.append(
                        f"{linked} has no counterpart '{target.name}-{suffix}'; left as is"
                    )
                elif linked not in mapping and new != linked:
                    mapping[linked] = new
                    result.linked[linked] = new

    parent_fixes = _parent_fixes(index, mapping)
    fixed_elements = {index[ref].element for ref in parent_fixes}
    matches: list[tuple[Reference, bool, StyleRef]] = [
        (m, in_content, new)
        for old_ref, new in mapping.items()
        for m, in_content in _matching_refs(pkg, index, old_ref)
        if not (m.attr == _PARENT and m.node in fixed_elements)
    ]

    for m, _, new in matches:
        m.replace(new.name)
    for ref, new_parent in parent_fixes.items():
        el = index[ref].element
        if new_parent is None:
            del el.attrib[_PARENT]
        else:
            el.set(_PARENT, new_parent.name)
    content_changed = any(in_content for _, in_content, _ in matches)
    if target.kind == FONT_FACE and content_changed:
        _sync_content_fonts(pkg, index, old_refs, target)
    if not keep:
        for ref in mapping:
            el = index[ref].element
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    result.references = len(matches) + len(parent_fixes)
    pkg.mark_styles_modified()
    if content_changed:
        pkg.mark_content_modified()
    if output is not None:
        pkg.save(output)
    elif not isinstance(document, OdfPackage):
        pkg.save()
    return result


def _parent_fixes(
    index: StyleIndex, mapping: dict[StyleRef, StyleRef]
) -> dict[StyleRef, StyleRef | None]:
    """New parents for styles that would otherwise end up inheriting from themselves.

    If a replaced style is an ancestor of its replacement, repointing the child on the
    replacement's parent chain would close a loop; that child instead inherits from the
    replaced style's nearest ancestor that is not being replaced (or from nothing).
    """

    def parent_of(ref: StyleRef) -> StyleRef | None:
        entry = index.get(ref)
        name = entry.element.get(_PARENT) if entry is not None else None
        return StyleRef(ref.kind, name) if name else None

    fixes: dict[StyleRef, StyleRef | None] = {}
    for target in set(mapping.values()):
        current: StyleRef | None = target
        seen: set[StyleRef] = set()
        while current is not None and current not in seen:
            seen.add(current)
            parent = fixes[current] if current in fixes else parent_of(current)
            if parent is not None and mapping.get(parent) == target:
                skipped: set[StyleRef] = set()
                while parent is not None and parent in mapping and parent not in skipped:
                    skipped.add(parent)
                    parent = parent_of(parent)
                fixes[current] = parent
            current = parent
    return fixes


def _sync_content_fonts(
    pkg: OdfPackage, index: StyleIndex, old_refs: list[StyleRef], target: StyleRef
) -> None:
    """content.xml declares fonts separately: swap the old declarations for the new one."""
    content = pkg.content_root
    if content is None or content is pkg.styles_root:
        return
    decls = content.find(q("office:font-face-decls"))
    if decls is None:
        return
    old_names = {r.name for r in old_refs}
    has_target = False
    for decl in list(decls.iterchildren(tag=etree.Element)):
        name = decl.get(q("style:name"))
        if name in old_names:
            decls.remove(decl)
        has_target = has_target or name == target.name
    if not has_target:
        decls.append(copy.deepcopy(index[target].element))
