"""Copy styles between LibreOffice / OpenDocument files."""

__version__ = "0.2.0.dev0"

from .collect import MissingRef, StyleEntry, StyleIndex, list_styles
from .copier import CopyReport, OnConflict, StyleNotFoundError, copy_all_styles, copy_styles
from .diff import StyleDiff, diff_styles
from .mapping import MappingResult, StyleMapping, apply_mapping, load_mapping, parse_mapping
from .package import OdfError, OdfPackage
from .refs import StyleRef
from .rename import AmbiguousStyleError, RenameResult, StyleNameConflictError, rename_style
from .replace import ReplaceResult, replace_style
from .sync import AuditResult, SyncResult, audit_documents, find_documents, sync_documents
from .usage import PurgeResult, purge_unused, style_usage, unused_styles

__all__ = [
    "AmbiguousStyleError",
    "AuditResult",
    "CopyReport",
    "MappingResult",
    "MissingRef",
    "OdfError",
    "OdfPackage",
    "OnConflict",
    "PurgeResult",
    "RenameResult",
    "ReplaceResult",
    "StyleDiff",
    "StyleEntry",
    "StyleIndex",
    "StyleMapping",
    "StyleNameConflictError",
    "StyleNotFoundError",
    "StyleRef",
    "SyncResult",
    "apply_mapping",
    "audit_documents",
    "copy_all_styles",
    "copy_styles",
    "diff_styles",
    "find_documents",
    "list_styles",
    "load_mapping",
    "parse_mapping",
    "purge_unused",
    "rename_style",
    "replace_style",
    "style_usage",
    "sync_documents",
    "unused_styles",
]
