"""Command-line interface: ``lostyle list|copy|rename|replace|diff|map|purge|sync|audit``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from . import __version__
from .collect import list_styles
from .copier import StyleNotFoundError, copy_styles
from .diff import diff_styles
from .mapping import apply_mapping, load_mapping
from .package import OdfError, OdfPackage
from .rename import AmbiguousStyleError, rename_style
from .replace import replace_style
from .sync import BATCH_ERRORS, SyncResult, audit_documents, find_documents, sync_documents
from .usage import purge_unused, style_usage, unused_styles


def _cmd_list(args: argparse.Namespace) -> int:
    pkg = OdfPackage.open(args.document)
    entries = list_styles(pkg, args.family, include_automatic=args.automatic)
    usage = style_usage(pkg) if args.usage else {}
    unused = set(unused_styles(pkg)) if args.unused else None
    for e in sorted(entries, key=lambda e: e.ref):
        if unused is not None and e.ref not in unused:
            continue
        display = f"  ({e.display_name})" if e.display_name != e.ref.name else ""
        auto = "  [automatic]" if e.ref.automatic else ""
        count = f"{usage.get(e.ref, 0):5}  " if args.usage else ""
        print(f"{count}{e.ref.kind:<16} {e.ref.name}{display}{auto}")
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


def _cmd_rename(args: argparse.Namespace) -> int:
    result = rename_style(args.document, args.old, args.new, family=args.family, output=args.output)
    print(result)
    return 0


def _cmd_replace(args: argparse.Namespace) -> int:
    result = replace_style(
        args.document,
        args.old,
        args.replacement,
        family=args.family,
        keep=args.keep,
        output=args.output,
    )
    print(result)
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    diff = diff_styles(args.a, args.b, families=args.family)
    print(diff.format(args.a, args.b))
    return 1 if args.exit_code and diff else 0


def _for_each_document(
    paths: Sequence[str], output: str | None, action: Callable[[Path, str | None], object]
) -> int:
    """Run ``action`` on every document under ``paths``; report errors and go on."""
    documents = find_documents(paths)
    if output is not None and len(documents) != 1:
        raise ValueError("--output needs exactly one document")
    failed = 0
    for path in documents:
        try:
            result = action(path, output)
        except BATCH_ERRORS as exc:
            print(f"{path}: error: {exc}", file=sys.stderr)
            failed += 1
            continue
        text = str(result)
        print(f"{path}: {text}" if "\n" not in text else f"{path}:\n{text}")
    return 1 if failed else 0


def _cmd_map(args: argparse.Namespace) -> int:
    mapping = load_mapping(args.map)
    return _for_each_document(
        args.documents, args.output, lambda path, out: apply_mapping(path, mapping, output=out)
    )


def _cmd_purge(args: argparse.Namespace) -> int:
    keep = OdfPackage.open(args.keep) if args.keep else None
    return _for_each_document(
        args.documents,
        args.output,
        lambda path, out: purge_unused(path, keep=keep, families=args.family, output=out),
    )


def _cmd_sync(args: argparse.Namespace) -> int:
    mapping = load_mapping(args.map) if args.map else None

    def report(result: SyncResult) -> None:
        print(result.summary(), file=sys.stderr if result.error else sys.stdout)
        if args.verbose and (details := result.details()):
            print(details)

    results = sync_documents(
        args.template,
        args.paths,
        mapping=mapping,
        purge=args.purge,
        dry_run=args.dry_run,
        on_result=report,
    )
    failed = sum(r.error is not None for r in results)
    skipped = sum(r.skipped is not None for r in results)
    changed = sum(r.changed and r.error is None for r in results)
    unchanged = len(results) - failed - skipped - changed
    verb = "would be updated" if args.dry_run else "updated"
    print(
        f"{len(results)} document(s): {changed} {verb}, {unchanged} up to date, "
        f"{skipped} skipped, {failed} failed"
    )
    return 1 if failed else 0


def _cmd_audit(args: argparse.Namespace) -> int:
    mapping = load_mapping(args.map) if args.map else None
    audit = audit_documents(args.template, args.paths, mapping=mapping)
    print(audit.format(verbose=args.verbose))
    return 1 if args.exit_code and audit else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lostyle", description="Copy styles between LibreOffice/OpenDocument files."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list the styles of a document")
    p_list.add_argument("document")
    p_list.add_argument(
        "-f", "--family", action="append", help="only this family/kind (repeatable)"
    )
    p_list.add_argument("--automatic", action="store_true", help="include automatic styles")
    p_list.add_argument(
        "--usage", action="store_true", help="show how many references each style has"
    )
    p_list.add_argument(
        "--unused", action="store_true", help="only styles nothing uses (what purge deletes)"
    )
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

    p_rename = sub.add_parser("rename", help="rename a style and update all references to it")
    p_rename.add_argument("document")
    p_rename.add_argument("old", help="current name (internal or display name)")
    p_rename.add_argument("new", help="new display name, e.g. 'Corporate Box'")
    p_rename.add_argument("-f", "--family", help="family/kind, if OLD exists in several")
    p_rename.add_argument("-o", "--output", help="write result here instead of modifying DOCUMENT")
    p_rename.set_defaults(func=_cmd_rename)

    p_replace = sub.add_parser(
        "replace", help="make everything use one style instead of others (merge duplicates)"
    )
    p_replace.add_argument("document")
    p_replace.add_argument("old", nargs="+", help="style(s) to replace and delete")
    p_replace.add_argument(
        "--with", dest="replacement", required=True, help="the style to use instead"
    )
    p_replace.add_argument("-f", "--family", help="family/kind, if the name is ambiguous")
    p_replace.add_argument("--keep", action="store_true", help="keep the replaced styles")
    p_replace.add_argument("-o", "--output", help="write result here instead of modifying DOCUMENT")
    p_replace.set_defaults(func=_cmd_replace)

    p_diff = sub.add_parser("diff", help="compare the style names of two documents")
    p_diff.add_argument("a")
    p_diff.add_argument("b")
    p_diff.add_argument(
        "-f", "--family", action="append", help="only this family/kind (repeatable)"
    )
    p_diff.add_argument(
        "--exit-code", action="store_true", help="exit with 1 if the documents differ"
    )
    p_diff.set_defaults(func=_cmd_diff)

    p_map = sub.add_parser("map", help="move documents from old style names to new ones")
    p_map.add_argument("documents", nargs="+", metavar="PATH", help="documents or directories")
    p_map.add_argument("--map", required=True, help="mapping file (TOML)")
    p_map.add_argument("-o", "--output", help="write result here (single document only)")
    p_map.set_defaults(func=_cmd_map)

    p_purge = sub.add_parser("purge", help="delete styles nothing uses")
    p_purge.add_argument("documents", nargs="+", metavar="PATH", help="documents or directories")
    p_purge.add_argument("--keep", metavar="TEMPLATE", help="keep every style this document has")
    p_purge.add_argument(
        "-f", "--family", action="append", help="only this family/kind (repeatable)"
    )
    p_purge.add_argument("-o", "--output", help="write result here (single document only)")
    p_purge.set_defaults(func=_cmd_purge)

    p_sync = sub.add_parser(
        "sync", help="update documents with a template's styles (map, copy, clean up)"
    )
    p_sync.add_argument("template")
    p_sync.add_argument("paths", nargs="+", metavar="PATH", help="documents or directories")
    p_sync.add_argument("--map", help="mapping file (TOML) of old -> new style names")
    p_sync.add_argument(
        "--purge", action="store_true", help="also delete unused styles not in the template"
    )
    p_sync.add_argument("--dry-run", action="store_true", help="report only, save nothing")
    p_sync.add_argument("-v", "--verbose", action="store_true", help="show what changed")
    p_sync.set_defaults(func=_cmd_sync)

    p_audit = sub.add_parser(
        "audit", help="list styles documents use that the template doesn't have"
    )
    p_audit.add_argument("template")
    p_audit.add_argument("paths", nargs="+", metavar="PATH", help="documents or directories")
    p_audit.add_argument("--map", help="apply this mapping file (in memory) first")
    p_audit.add_argument("-v", "--verbose", action="store_true", help="list the documents")
    p_audit.add_argument(
        "--exit-code", action="store_true", help="exit with 1 if any such style is used"
    )
    p_audit.set_defaults(func=_cmd_audit)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except (OdfError, StyleNotFoundError, AmbiguousStyleError, ValueError, OSError) as exc:
        print(f"lostyle: error: {exc}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
