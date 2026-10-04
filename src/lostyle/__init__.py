"""Copy styles between LibreOffice / OpenDocument files."""

from .collect import MissingRef, StyleEntry, StyleIndex, list_styles
from .copier import CopyReport, OnConflict, StyleNotFoundError, copy_all_styles, copy_styles
from .package import OdfError, OdfPackage
from .refs import StyleRef
from .rename import AmbiguousStyleError, RenameResult, StyleNameConflictError, rename_style

__all__ = [
    "AmbiguousStyleError",
    "CopyReport",
    "MissingRef",
    "OdfError",
    "OdfPackage",
    "OnConflict",
    "RenameResult",
    "StyleEntry",
    "StyleIndex",
    "StyleNameConflictError",
    "StyleNotFoundError",
    "StyleRef",
    "copy_all_styles",
    "copy_styles",
    "list_styles",
    "rename_style",
]
