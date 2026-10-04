"""Comparing the style names of two documents."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import groupby

from .collect import StyleEntry, StyleIndex
from .copier import Source, _as_package
from .refs import StyleRef


@dataclass
class StyleDiff:
    """Styles present only in document A, only in B, and in both (matched by kind and name)."""

    only_a: list[StyleEntry] = field(default_factory=list)
    only_b: list[StyleEntry] = field(default_factory=list)
    common: list[StyleRef] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.only_a or self.only_b)

    def format(self, name_a: str = "a", name_b: str = "b") -> str:
        """Render the diff as text, grouped by kind (``-`` only in A, ``+`` only in B)."""
        if not self:
            return f"no differences ({len(self.common)} styles in both)"
        lines = [f"--- {name_a}", f"+++ {name_b}"]
        entries: list[tuple[StyleRef, str, StyleEntry]] = [(e.ref, "-", e) for e in self.only_a]
        entries += [(e.ref, "+", e) for e in self.only_b]
        marked = sorted(
            entries,
            key=lambda item: (item[0].kind, item[1] == "+", item[0].name),
        )
        for kind, items in groupby(marked, key=lambda item: item[0].kind):
            lines.append(kind)
            for ref, sign, entry in items:
                display = f"  ({entry.display_name})" if entry.display_name != ref.name else ""
                lines.append(f"  {sign} {ref.name}{display}")
        lines.append(
            f"{len(self.only_a)} only in {name_a}, {len(self.only_b)} only in {name_b}, "
            f"{len(self.common)} in both"
        )
        return "\n".join(lines)


def diff_styles(a: Source, b: Source, *, families: Iterable[str] | None = None) -> StyleDiff:
    """Compare which (non-automatic) styles two documents have, by kind and internal name."""
    kinds = list(families) if families else None
    styles_a = {e.ref: e for e in StyleIndex(_as_package(a)).styles(kinds)}
    styles_b = {e.ref: e for e in StyleIndex(_as_package(b)).styles(kinds)}
    return StyleDiff(
        only_a=[styles_a[r] for r in sorted(styles_a.keys() - styles_b.keys())],
        only_b=[styles_b[r] for r in sorted(styles_b.keys() - styles_a.keys())],
        common=sorted(styles_a.keys() & styles_b.keys()),
    )
