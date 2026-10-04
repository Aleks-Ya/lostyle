"""Builders for minimal OpenDocument test files."""

from __future__ import annotations

import zipfile
from pathlib import Path

NSDECL = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'office:version="1.3"'
)

MIMETYPES = {
    "graphics": "application/vnd.oasis.opendocument.graphics",
    "text": "application/vnd.oasis.opendocument.text",
    "spreadsheet": "application/vnd.oasis.opendocument.spreadsheet",
    "presentation": "application/vnd.oasis.opendocument.presentation",
}


def make_odf(
    path: Path,
    *,
    fonts: str = "",
    styles: str = "",
    auto_styles: str = "",
    masters: str = "",
    content_auto_styles: str = "",
    body: str = "<office:drawing/>",
    doc_type: str = "graphics",
    files: dict[str, bytes] | None = None,
    flat: bool = False,
) -> Path:
    """Write a minimal zipped or flat ODF document."""
    parts = (
        f"<office:font-face-decls>{fonts}</office:font-face-decls>"
        f"<office:styles>{styles}</office:styles>"
        f"<office:automatic-styles>{auto_styles}</office:automatic-styles>"
        f"<office:master-styles>{masters}</office:master-styles>"
    )
    if flat:
        path.write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document {NSDECL} '
            f'office:mimetype="{MIMETYPES[doc_type]}">'
            f"{parts.replace('</office:automatic-styles>', content_auto_styles + '</office:automatic-styles>')}"
            f"<office:body>{body}</office:body></office:document>",
            encoding="utf-8",
        )
        return path
    files = files or {}
    manifest_entries = "".join(
        f'<manifest:file-entry manifest:full-path="{name}" manifest:media-type="image/png"/>'
        for name in files
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype"), MIMETYPES[doc_type], compress_type=zipfile.ZIP_STORED
        )
        zf.writestr(
            "content.xml",
            f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {NSDECL}>'
            f"<office:automatic-styles>{content_auto_styles}</office:automatic-styles>"
            f"<office:body>{body}</office:body></office:document-content>",
        )
        zf.writestr(
            "styles.xml",
            f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-styles {NSDECL}>'
            f"{parts}</office:document-styles>",
        )
        zf.writestr(
            "META-INF/manifest.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest:manifest '
            'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
            'manifest:version="1.3">'
            f'<manifest:file-entry manifest:full-path="/" '
            f'manifest:media-type="{MIMETYPES[doc_type]}"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
            f"{manifest_entries}</manifest:manifest>",
        )
        for name, data in files.items():
            zf.writestr(name, data)
    return path
