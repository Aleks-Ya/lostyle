"""Command-line interface: ``lostyle list`` and ``lostyle copy``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .collect import list_styles
from .copier import StyleNotFoundError, copy_styles
from .package import OdfError, OdfPackage


def _cmd_list(args: argparse.Namespace) -> int:
    pkg = OdfPackage.open(args.document)
    entries = list_styles(pkg, args.family, include_automatic=args.automatic)
    for e in sorted(entries, key=lambda e: e.ref):
        display = f"  ({e.display_name})" if e.display_name != e.ref.name else ""
        auto = "  [automatic]" if e.ref.automatic else ""
        print(f"{e.ref.kind:<16} {e.ref.name}{display}{auto}")
    return 0


def _cmd_copy(args: argparse.Namespace) -> int:
    report = copy_styles(
        args.source,
        args.target,
        families=args.family,
        names=args.style,
        on_conflict=args.on_conflict,
        include_dependencies=not args.no_deps,
        include_defaults=args.defaults,
        output=args.output,
    )
    print(report.summary())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lostyle", description="Copy styles between LibreOffice/OpenDocument files."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list the styles of a document")
    p_list.add_argument("document")
    p_list.add_argument(
        "-f", "--family", action="append", help="only this family/kind (repeatable)"
    )
    p_list.add_argument("--automatic", action="store_true", help="include automatic styles")
    p_list.set_defaults(func=_cmd_list)

    p_copy = sub.add_parser("copy", help="copy styles from SOURCE into TARGET")
    p_copy.add_argument("source")
    p_copy.add_argument("target")
    p_copy.add_argument("-o", "--output", help="write result here instead of modifying TARGET")
    p_copy.add_argument(
        "-f",
        "--family",
        action="append",
        help="only styles of this family/kind, e.g. graphic, paragraph, master-page (repeatable)",
    )
    p_copy.add_argument(
        "-s", "--style", action="append", help="only the style with this name (repeatable)"
    )
    p_copy.add_argument(
        "--on-conflict",
        choices=["overwrite", "skip", "rename"],
        default="overwrite",
        help="what to do with styles that already exist in TARGET (default: overwrite)",
    )
    p_copy.add_argument(
        "--no-deps", action="store_true", help="do not copy styles the selected ones depend on"
    )
    p_copy.add_argument("--defaults", action="store_true", help="also copy default styles")
    p_copy.set_defaults(func=_cmd_copy)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except (OdfError, StyleNotFoundError, OSError) as exc:
        print(f"lostyle: error: {exc}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
