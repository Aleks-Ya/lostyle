"""Moving documents from old style names to new ones, driven by a mapping file.

A mapping file is TOML: one table per family/kind, mapping each new name to the old
names it replaces::

    [graphic]
    "Line: Association" = ["Line: Assosiation", "Assosiation line"]
    "Page: part splitter" = "Page part splitter"

    [master-page]
    SchematizationTemplate = ["SchematizationTemplate_2"]
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .collect import StyleIndex
from .copier import Source, _as_package
from .package import OdfPackage
from .refs import _TAG_KINDS, DEFAULT
from .rename import _NOT_RENAMEABLE, RenameResult, rename_style
from .replace import ReplaceResult, replace_style

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

StyleMapping = dict[str, dict[str, list[str]]]  # kind -> new name -> old names

_FAMILIES = {"paragraph", "text", "section", "ruby", "table", "table-column", "table-row",
             "table-cell", "chart", "graphic", "presentation", "drawing-page",
             "control"}  # fmt: skip
KINDS = frozenset(_FAMILIES | set(_TAG_KINDS.values())) - {DEFAULT}


@dataclass
class MappingResult:
    changes: list[RenameResult | ReplaceResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.changes)

    def __str__(self) -> str:
        lines = [str(c) for c in self.changes] or ["nothing to map"]
        lines.extend(f"warning: {w}" for w in self.warnings)
        return "\n".join(lines)


def load_mapping(path: str | os.PathLike[str]) -> StyleMapping:
    """Read a mapping file (see the module docstring for the format)."""
    with open(path, "rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return parse_mapping(data, str(path))


def parse_mapping(data: Mapping[str, Any], source: str = "mapping") -> StyleMapping:
    """Validate a ``{kind: {new: old | [old, ...]}}`` structure."""
    result: StyleMapping = {}
    for kind, entries in data.items():
        if kind not in KINDS:
            raise ValueError(f"{source}: unknown style family/kind {kind!r}")
        if not isinstance(entries, Mapping):
            raise ValueError(f"{source}: [{kind}] must be a table of new = [old names]")
        table: dict[str, list[str]] = {}
        seen: dict[str, str] = {}
        for new, olds in entries.items():
            old_list = [olds] if isinstance(olds, str) else olds
            if not isinstance(old_list, list) or not all(isinstance(o, str) for o in old_list):
                raise ValueError(f"{source}: [{kind}] {new!r} must map to a name or list of names")
            for old in old_list:
                if old == new:
                    raise ValueError(f"{source}: [{kind}] {new!r} maps to itself")
                if old in seen:
                    raise ValueError(
                        f"{source}: [{kind}] {old!r} maps to both {seen[old]!r} and {new!r}"
                    )
                seen[old] = new
            table[new] = list(old_list)
        if chained := sorted(set(seen) & set(table)):
            raise ValueError(f"{source}: [{kind}] {chained[0]!r} is both a new and an old name")
        result[kind] = table
    return result


def apply_mapping(
    document: Source,
    mapping: StyleMapping,
    *,
    output: str | os.PathLike[str] | None = None,
) -> MappingResult:
    """Move a document from old style names to new ones.

    For each ``new: [old, ...]`` entry, the old styles the document has are merged into
    ``new`` (``replace_style``) when it exists; otherwise the first one is renamed to
    ``new`` and the others are merged into it. Old names the document doesn't have are
    ignored. Names are matched like elsewhere: internal, display or decoded name.

    Args:
        document: Path of the document, or an open ``OdfPackage``.
        mapping: As returned by ``load_mapping`` / ``parse_mapping``.
        output: Where to save the result. If omitted, a document given as a path is
            saved in place (only if something changed); one given as ``OdfPackage``
            is left unsaved.
    """
    pkg = _as_package(document)
    result = MappingResult()
    for kind, entries in mapping.items():
        for new, olds in entries.items():
            index = StyleIndex(pkg)
            targets = index.find(new, [kind])
            found = (r for old in olds for r in index.find(old, [kind]) if r not in targets)
            present = list(dict.fromkeys(r.name for r in found))
            if not present:
                continue
            if targets:
                result.changes.append(replace_style(pkg, present, targets[0].name, family=kind))
            elif kind in _NOT_RENAMEABLE:
                result.warnings.append(
                    f"{kind} {new!r} does not exist; {', '.join(present)} left as is"
                )
            else:
                result.changes.append(rename_style(pkg, present[0], new, family=kind))
                if present[1:]:
                    result.changes.append(replace_style(pkg, present[1:], new, family=kind))

    if output is not None:
        pkg.save(output)
    elif not isinstance(document, OdfPackage) and result:
        pkg.save()
    return result
