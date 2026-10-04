"""OpenDocument XML namespaces and qualified-name helpers."""

from __future__ import annotations

import re
from functools import cache

NS: dict[str, str] = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "number": "urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
    "chart": "urn:oasis:names:tc:opendocument:xmlns:chart:1.0",
    "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
    "loext": "urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0",
}


@cache
def q(name: str) -> str:
    """Convert a prefixed name like ``style:name`` to Clark notation ``{uri}name``."""
    prefix, _, local = name.partition(":")
    return f"{{{NS[prefix]}}}{local}"


def prefixed(clark: str) -> str:
    """Convert Clark notation back to a prefixed name (best effort, for messages)."""
    if not clark.startswith("{"):
        return clark
    uri, _, local = clark[1:].partition("}")
    for prefix, ns_uri in NS.items():
        if ns_uri == uri:
            return f"{prefix}:{local}"
    return clark


_ENCODED_CHAR = re.compile(r"_([0-9a-fA-F]{2,6})_")


def decode_style_name(name: str) -> str:
    """Decode LibreOffice's style-name escaping, e.g. ``Heading_20_1`` -> ``Heading 1``."""
    return _ENCODED_CHAR.sub(lambda m: chr(int(m.group(1), 16)), name)
