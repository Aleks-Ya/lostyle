"""What counts as a style, how it is named, and which other styles it references."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from lxml import etree

from .ns import q

# Style "kinds". For style:style elements the kind is the style family
# (graphic, paragraph, text, table-cell, drawing-page, presentation, ...);
# other style-like elements get the kinds below.
LIST = "list"
NUMBER = "number"
OUTLINE = "outline"
GRADIENT = "gradient"
HATCH = "hatch"
FILL_IMAGE = "fill-image"
MARKER = "marker"
STROKE_DASH = "stroke-dash"
OPACITY = "opacity"
MASTER_PAGE = "master-page"
PAGE_LAYOUT = "page-layout"
FONT_FACE = "font-face"
DEFAULT = "default"  # style:default-style; the ref name is the family
PRESENTATION_PAGE_LAYOUT = "presentation-page-layout"
TABLE_TEMPLATE = "table-template"

# Kinds identified by element tag alone.
_TAG_KINDS: dict[str, str] = {
    q("text:list-style"): LIST,
    q("text:outline-style"): OUTLINE,
    q("number:number-style"): NUMBER,
    q("number:currency-style"): NUMBER,
    q("number:percentage-style"): NUMBER,
    q("number:date-style"): NUMBER,
    q("number:time-style"): NUMBER,
    q("number:boolean-style"): NUMBER,
    q("number:text-style"): NUMBER,
    q("draw:gradient"): GRADIENT,
    q("draw:hatch"): HATCH,
    q("draw:fill-image"): FILL_IMAGE,
    q("draw:marker"): MARKER,
    q("draw:stroke-dash"): STROKE_DASH,
    q("draw:opacity"): OPACITY,
    q("style:master-page"): MASTER_PAGE,
    q("style:page-layout"): PAGE_LAYOUT,
    q("style:font-face"): FONT_FACE,
    q("style:presentation-page-layout"): PRESENTATION_PAGE_LAYOUT,
    q("table:table-template"): TABLE_TEMPLATE,
}

_DRAW_RESOURCES = {q("draw:gradient"), q("draw:hatch"), q("draw:fill-image"), q("draw:marker"),
                   q("draw:stroke-dash"), q("draw:opacity")}  # fmt: skip


@dataclass(frozen=True, order=True)
class StyleRef:
    """Identifies a style-like element: its kind, internal name and whether it is automatic."""

    kind: str
    name: str
    automatic: bool = False

    def __str__(self) -> str:
        suffix = " (automatic)" if self.automatic else ""
        return f"{self.kind}:{self.name}{suffix}"


def element_kind(el: etree._Element) -> str | None:
    """Return the kind of a style-like element, or ``None`` if it is not one."""
    if el.tag == q("style:style"):
        return el.get(q("style:family"))
    if el.tag == q("style:default-style"):
        return DEFAULT
    return _TAG_KINDS.get(el.tag)


def name_attr(el: etree._Element) -> str:
    if el.tag in _DRAW_RESOURCES:
        return q("draw:name")
    if el.tag == q("table:table-template"):
        return q("table:name")
    return q("style:name")


def display_name_attr(el: etree._Element) -> str:
    return q("draw:display-name") if el.tag in _DRAW_RESOURCES else q("style:display-name")


def element_name(el: etree._Element) -> str | None:
    if el.tag == q("style:default-style"):
        return el.get(q("style:family"))
    return el.get(name_attr(el))


# ---------------------------------------------------------------- references
SAME = "<same>"  # reference to a style of the same kind as the referencing style

# Attributes whose value is always a reference to the given kinds (tried in order).
_FIXED_REFS: dict[str, tuple[str, ...]] = {
    q("style:parent-style-name"): (SAME,),
    q("style:next-style-name"): (SAME,),
    q("style:linked-style-name"): ("paragraph", "text"),
    q("loext:linked-style-name"): ("paragraph", "text"),
    q("style:apply-style-name"): (SAME,),
    q("style:list-style-name"): (LIST,),
    q("style:data-style-name"): (NUMBER,),
    q("style:percentage-data-style-name"): (NUMBER,),
    q("style:page-layout-name"): (PAGE_LAYOUT,),
    q("style:master-page-name"): (MASTER_PAGE,),
    q("style:font-name"): (FONT_FACE,),
    q("style:font-name-asian"): (FONT_FACE,),
    q("style:font-name-complex"): (FONT_FACE,),
    q("draw:fill-gradient-name"): (GRADIENT,),
    q("draw:opacity-name"): (OPACITY,),
    q("draw:fill-hatch-name"): (HATCH,),
    q("draw:fill-image-name"): (FILL_IMAGE,),
    q("draw:marker-start"): (MARKER,),
    q("draw:marker-end"): (MARKER,),
    q("draw:stroke-dash"): (STROKE_DASH,),
    q("presentation:style-name"): ("presentation",),
    q("draw:text-style-name"): ("paragraph", "text"),
    q("text:visited-style-name"): ("text",),
    q("draw:master-page-name"): (MASTER_PAGE,),
    q("table:default-cell-style-name"): ("table-cell",),
    q("text:cond-style-name"): ("paragraph",),
    q("style:register-truth-ref-style-name"): ("paragraph",),
    q("table:template-name"): (TABLE_TEMPLATE,),
    q("draw:class-names"): ("graphic",),
    q("presentation:class-names"): ("presentation",),
}

# Attributes holding a space-separated list of style names.
_LIST_ATTRS = {q("draw:class-names"), q("presentation:class-names")}

_TEXT_STYLE_BY_TAG: dict[str, tuple[str, ...]] = {
    q("text:p"): ("paragraph",),
    q("text:h"): ("paragraph",),
    q("text:list"): (LIST,),
    q("text:list-item"): (LIST,),
}

_TABLE_STYLE_BY_TAG: dict[str, tuple[str, ...]] = {
    q("table:table"): ("table",),
    q("table:table-column"): ("table-column",),
    q("table:table-row"): ("table-row",),
}

_HREF_TAGS = {q("draw:fill-image"), q("draw:image"), q("style:background-image"),
              q("text:list-level-style-image")}  # fmt: skip


def _ref_kinds(node: etree._Element, attr: str, root_kind: str) -> tuple[str, ...] | None:
    """Kinds that ``attr`` on ``node`` may reference, or ``None`` if it is not a reference."""
    kinds = _FIXED_REFS.get(attr)
    if kinds is not None:
        if attr == q("style:apply-style-name") and root_kind == NUMBER:
            return (NUMBER,)
        if attr == q("style:next-style-name") and node.tag != q("style:style"):
            return None
        return kinds
    if attr == q("draw:style-name"):
        if node.tag == q("style:master-page"):
            return ("drawing-page",)
        return ("graphic",)
    if attr == q("text:style-name"):
        return _TEXT_STYLE_BY_TAG.get(node.tag, ("text",))
    if attr == q("table:style-name"):
        return _TABLE_STYLE_BY_TAG.get(node.tag, ("table-cell",))
    return None


@dataclass(frozen=True)
class Reference:
    node: etree._Element
    attr: str
    value: str
    kinds: tuple[str, ...]
    index: int | None = None  # position within a space-separated list attribute

    def replace(self, new: str) -> None:
        """Point this reference at the style named ``new``."""
        if self.index is None:
            self.node.set(self.attr, new)
            return
        names = (self.node.get(self.attr) or "").split()
        names[self.index] = new
        self.node.set(self.attr, " ".join(names))


def iter_refs(el: etree._Element, root_kind: str) -> Iterator[Reference]:
    """Yield style references made by ``el`` and its descendants."""
    for node in el.iter(tag=etree.Element):
        for raw_attr, raw_value in node.attrib.items():
            attr, value = str(raw_attr), str(raw_value)
            if not value:
                continue
            kinds = _ref_kinds(node, attr, root_kind)
            if kinds is None:
                continue
            kinds = tuple(root_kind if k == SAME else k for k in kinds)
            if DEFAULT in kinds:
                continue
            if attr in _LIST_ATTRS:
                for i, name in enumerate(value.split()):
                    yield Reference(node, attr, name, kinds, i)
            else:
                yield Reference(node, attr, value, kinds)


def iter_file_refs(el: etree._Element) -> Iterator[tuple[etree._Element, str]]:
    """Yield ``(node, path)`` for package-internal files referenced via ``xlink:href``."""
    for node in el.iter(tag=etree.Element):
        if node.tag not in _HREF_TAGS:
            continue
        href = node.get(q("xlink:href"))
        if not href or href.startswith(("#", "/", "..")) or ":" in href:
            continue
        yield node, href.removeprefix("./")
