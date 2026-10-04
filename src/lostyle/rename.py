"""Renaming a style inside a document and updating every reference to it."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from lxml import etree

from .collect import StyleIndex
from .copier import Source, StyleNotFoundError, _as_package
from .ns import decode_style_name, encode_style_name, q
from .package import OdfPackage
from .refs import (
    DEFAULT,
    FONT_FACE,
    MASTER_PAGE,
    Reference,
    StyleRef,
    display_name_attr,
    element_kind,
    element_name,
    iter_refs,
    name_attr,
)

_NOT_RENAMEABLE = {DEFAULT, FONT_FACE}
_STYLES_CONTAINERS = [
    "office:font-face-decls",
    "office:styles",
    "office:automatic-styles",
    "office:master-styles",
]

Resolver = Callable[[tuple[str, ...], str], StyleRef | None]


class AmbiguousStyleError(LookupError):
    """The style name exists in several families; a family must be given."""


class StyleNameConflictError(ValueError):
    """Another style of the same kind already uses the new name."""


@dataclass
class RenameResult:
    ref: StyleRef
    new_name: str
    display_name: str
    references: int = 0
    linked: dict[StyleRef, str] = field(default_factory=dict)  # renamed along with ``ref``

    def __str__(self) -> str:
        lines = [f"{self.ref} -> {self.new_name} ({self.display_name}), "
                 f"{self.references} reference(s) updated"]  # fmt: skip
        lines.extend(f"  also renamed {r} -> {n}" for r, n in self.linked.items())
        return "\n".join(lines)


def _automatic_names(container: etree._Element | None) -> set[tuple[str, str]]:
    if container is None:
        return set()
    return {
        (kind, name)
        for el in container.iterchildren(tag=etree.Element)
        if (kind := element_kind(el)) and (name := element_name(el))
    }


def _matching_refs(
    pkg: OdfPackage, index: StyleIndex, ref: StyleRef
) -> Iterator[tuple[Reference, bool]]:
    """Yield ``(reference, in_content_part)`` for every reference that resolves to ``ref``."""

    def scan(
        el: etree._Element, resolve: Resolver, in_content: bool
    ) -> Iterator[tuple[Reference, bool]]:
        for r in iter_refs(el, element_kind(el) or ""):
            if r.value == ref.name and ref.kind in r.kinds and resolve(r.kinds, r.value) == ref:
                yield r, in_content

    styles_root = pkg.styles_root
    content_root = pkg.content_root
    flat = content_root is styles_root

    # styles part: references from automatic styles and master pages see automatic styles first
    for name in _STYLES_CONTAINERS:
        container = styles_root.find(q(name))
        if container is None:
            continue
        prefer_auto = name in ("office:automatic-styles", "office:master-styles")

        def resolve_styles(
            kinds: tuple[str, ...], value: str, p: bool = prefer_auto
        ) -> StyleRef | None:
            return index.resolve(kinds, value, p)

        for child in container.iterchildren(tag=etree.Element):
            yield from scan(child, resolve_styles, flat)

    if content_root is None:
        return
    # content part: its own automatic styles shadow common styles of the same name
    content_auto_container = content_root.find(q("office:automatic-styles"))
    content_auto = _automatic_names(content_auto_container)

    def resolve_content(kinds: tuple[str, ...], value: str) -> StyleRef | None:
        for kind in kinds:
            if (kind, value) in content_auto:
                return StyleRef(kind, value, True)
            if (common := StyleRef(kind, value)) in index:
                return common
        return None

    if not flat and content_auto_container is not None:
        for child in content_auto_container.iterchildren(tag=etree.Element):
            yield from scan(child, resolve_content, True)
    body = content_root.find(q("office:body"))
    if body is not None:
        yield from scan(body, resolve_content, True)


def rename_style(
    document: Source,
    old: str,
    new: str,
    *,
    family: str | None = None,
    output: str | os.PathLike[str] | None = None,
) -> RenameResult:
    """Rename a style and update every reference to it within the document.

    Args:
        document: Path of the document, or an open ``OdfPackage``.
        old: Current name of the style (internal, display or decoded name).
        new: New display name. The internal name is derived from it the way
            LibreOffice does (``Corporate Box`` -> ``Corporate_20_Box``).
        family: Family/kind of the style; required when ``old`` exists in
            several families.
        output: Where to save the result. If omitted, a document given as a path
            is saved in place; one given as ``OdfPackage`` is left unsaved.

    Raises:
        StyleNotFoundError: ``old`` does not exist.
        AmbiguousStyleError: ``old`` exists in several families and ``family`` is not given.
        StyleNameConflictError: another style of the same kind already uses ``new``.

    Renaming an Impress master page also renames its presentation styles
    (``<master>-title``, ``<master>-outline1``, ...), which LibreOffice links to
    the master page by name; they are listed in ``RenameResult.linked``.
        ValueError: ``new`` is empty, or the style cannot be renamed (default styles,
            font declarations).
    """
    if not new.strip():
        raise ValueError("new style name must not be empty")
    pkg = _as_package(document)
    index = StyleIndex(pkg)

    found = index.find(old, [family] if family else None)
    if not found:
        where = f" in family {family!r}" if family else ""
        raise StyleNotFoundError(f"style {old!r} not found{where}")
    if len(found) > 1:
        kinds = ", ".join(sorted(r.kind for r in found))
        raise AmbiguousStyleError(
            f"style {old!r} exists in several families ({kinds}); give a family"
        )
    ref = found[0]
    if ref.kind in _NOT_RENAMEABLE:
        raise ValueError(f"{ref.kind} styles cannot be renamed")

    new_name = encode_style_name(new)
    renames = [(ref, new_name, new)]
    if ref.kind == MASTER_PAGE:
        # Impress links presentation styles to their master page by name prefix
        # ("Default-title", "Default-outline1", ...); LibreOffice replaces them with
        # fresh defaults if they don't follow the master page's name.
        prefix = f"{ref.name}-"
        for entry in index.styles(["presentation"]):
            if entry.ref.name.startswith(prefix):
                suffix = entry.ref.name[len(prefix) :]
                display = f"{new}-{decode_style_name(suffix)}"
                renames.append((entry.ref, f"{new_name}-{suffix}", display))

    renamed = {r for r, _, _ in renames}
    for r, name, display in renames:
        _check_free(pkg, index, r, name, display, renamed)

    matches = [(r, name, m) for r, name, _ in renames for m in _matching_refs(pkg, index, r)]
    for r, name, display in renames:
        _set_name(index[r].element, r.name, name, display)
    for _, name, (m, _) in matches:
        m.replace(name)

    result = RenameResult(ref, new_name, new, references=len(matches))
    result.linked = {r: name for r, name, _ in renames[1:]}
    pkg.mark_styles_modified()
    if any(in_content for _, _, (_, in_content) in matches):
        pkg.mark_content_modified()

    if output is not None:
        pkg.save(output)
    elif not isinstance(document, OdfPackage):
        pkg.save()
    return result


def _check_free(
    pkg: OdfPackage,
    index: StyleIndex,
    ref: StyleRef,
    new_name: str,
    display: str,
    renamed: set[StyleRef],
) -> None:
    """Raise if another style of the same kind already uses ``new_name`` or ``display``."""
    for other in index.styles([ref.kind], include_automatic=True):
        if other.ref in renamed:
            continue
        if other.ref.name == new_name or (
            not other.ref.automatic and other.display_name == display
        ):
            raise StyleNameConflictError(f"a {ref.kind} style named {display!r} already exists")
    for container in pkg.automatic_style_containers():
        if (ref.kind, new_name) in _automatic_names(container):
            raise StyleNameConflictError(
                f"an automatic {ref.kind} style named {new_name!r} already exists"
            )


def _set_name(el: etree._Element, old_name: str, new_name: str, display: str) -> None:
    el.set(name_attr(el), new_name)
    display_attr = display_name_attr(el)
    if display != new_name:
        el.set(display_attr, display)
    elif display_attr in el.attrib:
        del el.attrib[display_attr]
    # list styles embedded in presentation styles carry the style's name
    for nested in el.iter(q("text:list-style")):
        if nested.get(q("style:name")) == old_name:
            nested.set(q("style:name"), new_name)
