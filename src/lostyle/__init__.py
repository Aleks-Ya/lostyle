"""Copy styles between LibreOffice / OpenDocument files."""

from .collect import MissingRef, StyleEntry, StyleIndex, list_styles
from .copier import CopyReport, OnConflict, StyleNotFoundError, copy_all_styles, copy_styles
from .package import OdfError, OdfPackage
from .refs import StyleRef

__all__ = [
    "CopyReport",
    "MissingRef",
    "OdfError",
    "OdfPackage",
    "OnConflict",
    "StyleEntry",
    "StyleIndex",
    "StyleNotFoundError",
    "StyleRef",
    "copy_all_styles",
    "copy_styles",
    "list_styles",
]
