"""Indexing the styles of a document and computing dependency closures."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from lxml import etree

from .ns import decode_style_name, prefixed
from .package import OdfPackage
from .refs import (
    MASTER_PAGE,
    StyleRef,
    display_name_attr,
    element_kind,
    element_name,
    iter_refs,
)

# (container, holds automatic styles)
_CONTAINERS = [
    ("office:font-face-decls", False),
    ("office:styles", False),
    ("office:automatic-styles", True),
    ("office:master-styles", False),
]


@dataclass(frozen=True)
class StyleEntry:
    ref: StyleRef
    element: etree._Element

    @property
    def display_name(self) -> str:
        return self.element.get(display_name_attr(self.element)) or decode_style_name(self.ref.name)


@dataclass(frozen=True)
class MissingRef:
    """A reference from ``source`` (via attribute ``attr``) to a style that does not exist."""

    source: StyleRef
    attr: str
    value: str

    def __str__(self) -> str:
        return f"{self.source} -> {self.attr}={self.value!r}"


class StyleIndex:
    """All named style-like elements of a document's styles part."""

    def __init__(self, pkg: OdfPackage) -> None:
        self.pkg = pkg
        self.entries: dict[StyleRef, StyleEntry] = {}
        for container_name, automatic in _CONTAINERS:
            container = pkg.container(container_name)
            if container is None:
                continue
            for el in container.iterchildren(tag=etree.Element):
                kind = element_kind(el)
                name = element_name(el)
                if kind and name:
                    ref = StyleRef(kind, name, automatic)
                    self.entries.setdefault(ref, StyleEntry(ref, el))

    def __contains__(self, ref: object) -> bool:
        return ref in self.entries

    def __getitem__(self, ref: StyleRef) -> StyleEntry:
        return self.entries[ref]

    def get(self, ref: StyleRef) -> StyleEntry | None:
        return self.entries.get(ref)

    def resolve(self, kinds: Iterable[str], name: str, prefer_automatic: bool) -> StyleRef | None:
        order = (True, False) if prefer_automatic else (False, True)
        for kind in kinds:
            for automatic in order:
                ref = StyleRef(kind, name, automatic)
                if ref in self.entries:
                    return ref
        return None

    def find(
        self, name: str, kinds: Iterable[str] | None = None, automatic: bool = False
    ) -> list[StyleRef]:
        """Find styles by internal name, display name or decoded name."""
        wanted = set(kinds) if kinds is not None else None
        candidates = [
            e
            for e in self.entries.values()
            if e.ref.automatic == automatic and (wanted is None or e.ref.kind in wanted)
        ]
        exact = [e.ref for e in candidates if e.ref.name == name]
        if exact:
            return exact
        return [
            e.ref for e in candidates if name in (e.display_name, decode_style_name(e.ref.name))
        ]

    def styles(
        self, kinds: Iterable[str] | None = None, include_automatic: bool = False
    ) -> list[StyleEntry]:
        wanted = set(kinds) if kinds is not None else None
        return [
            e
            for e in self.entries.values()
            if (include_automatic or not e.ref.automatic)
            and (wanted is None or e.ref.kind in wanted)
        ]

    def references(self, ref: StyleRef) -> list[tuple[str, str, StyleRef | None]]:
        """Return ``(attr, value, resolved ref or None)`` for every reference made by ``ref``."""
        prefer_auto = uses_automatic_styles(ref)
        return [
            (r.attr, r.value, self.resolve(r.kinds, r.value, prefer_auto))
            for r in iter_refs(self.entries[ref].element, ref.kind)
        ]


def uses_automatic_styles(ref: StyleRef) -> bool:
    """Whether references from this style resolve to automatic styles first."""
    return ref.automatic or ref.kind == MASTER_PAGE


@dataclass
class Closure:
    order: list[StyleRef] = field(default_factory=list)  # dependencies before dependents
    missing: list[MissingRef] = field(default_factory=list)


def resolve_closure(
    index: StyleIndex,
    roots: Iterable[StyleRef],
    *,
    include_dependencies: bool = True,
    follow: Callable[[StyleRef], bool] = lambda ref: True,
) -> Closure:
    """Collect ``roots`` and (optionally) everything they reference, transitively.

    ``follow(ref)`` decides whether the dependencies of ``ref`` are explored.
    References from a root to styles not in ``index`` are reported as missing.
    """
    closure = Closure()
    visited: set[StyleRef] = set()

    def visit(ref: StyleRef) -> None:
        if ref in visited:
            return
        visited.add(ref)
        if include_dependencies and follow(ref):
            for attr, value, target in index.references(ref):
                if target is None:
                    closure.missing.append(MissingRef(ref, prefixed(attr), value))
                elif target != ref:
                    visit(target)
        closure.order.append(ref)

    for root in roots:
        visit(root)
    return closure


def list_styles(
    pkg: OdfPackage, kinds: Iterable[str] | None = None, include_automatic: bool = False
) -> list[StyleEntry]:
    """List the styles of a document, optionally filtered by kind/family."""
    return StyleIndex(pkg).styles(kinds, include_automatic)
