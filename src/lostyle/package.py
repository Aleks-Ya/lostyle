"""Reading and writing OpenDocument packages (zipped ``.odg`` etc. and flat ``.fodg`` etc.)."""

from __future__ import annotations

import mimetypes
import os
import tempfile
import time
import zipfile
from pathlib import Path

from lxml import etree

from .ns import q

STYLES_XML = "styles.xml"
CONTENT_XML = "content.xml"
MANIFEST_XML = "META-INF/manifest.xml"
SIGNATURES_XML = "META-INF/documentsignatures.xml"

# Required order of the top-level children of office:document / office:document-styles.
_TOP_LEVEL_ORDER = [
    "office:meta",
    "office:settings",
    "office:scripts",
    "office:font-face-decls",
    "office:styles",
    "office:automatic-styles",
    "office:master-styles",
    "office:body",
]


class OdfError(Exception):
    """Raised for files that are not valid OpenDocument packages."""


def _parser() -> etree.XMLParser:
    return etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True)


class OdfPackage:
    """An OpenDocument file held in memory.

    Zipped packages keep every entry as raw bytes; only the XML parts that were
    accessed and marked modified are re-serialized on save. Flat (single XML)
    documents are kept as one tree that serves as both styles and content root.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.flat = False
        self.dropped_signature = False
        self._entries: dict[str, tuple[zipfile.ZipInfo, bytes]] = {}
        self._trees: dict[str, etree._Element] = {}
        self._modified: set[str] = set()
        self._flat_root: etree._Element | None = None

    # ------------------------------------------------------------------ loading
    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> OdfPackage:
        p = Path(path)
        pkg = cls(p)
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as zf:
                for info in zf.infolist():
                    pkg._entries[info.filename] = (info, zf.read(info))
            if STYLES_XML not in pkg._entries:
                raise OdfError(f"{p}: not an OpenDocument package (no {STYLES_XML})")
        else:
            try:
                root = etree.parse(str(p), _parser()).getroot()
            except etree.XMLSyntaxError as exc:
                raise OdfError(f"{p}: neither a zip package nor XML: {exc}") from exc
            if root.tag != q("office:document"):
                raise OdfError(f"{p}: XML root is not office:document")
            pkg.flat = True
            pkg._flat_root = root
        return pkg

    def _part(self, name: str) -> etree._Element:
        if name not in self._trees:
            if name not in self._entries:
                raise OdfError(f"missing package part {name}")
            self._trees[name] = etree.fromstring(self._entries[name][1], _parser())
        return self._trees[name]

    # ------------------------------------------------------------------ XML roots
    @property
    def styles_root(self) -> etree._Element:
        if self._flat_root is not None:
            return self._flat_root
        return self._part(STYLES_XML)

    @property
    def content_root(self) -> etree._Element | None:
        if self._flat_root is not None:
            return self._flat_root
        return self._part(CONTENT_XML) if CONTENT_XML in self._entries else None

    def mark_styles_modified(self) -> None:
        if not self.flat:
            self._modified.add(STYLES_XML)

    def mark_content_modified(self) -> None:
        if not self.flat and CONTENT_XML in self._entries:
            self._modified.add(CONTENT_XML)

    def container(self, name: str, *, create: bool = False) -> etree._Element | None:
        """Return a top-level container (e.g. ``office:styles``) of the styles root."""
        root = self.styles_root
        found = root.find(q(name))
        if found is not None or not create:
            return found
        new = root.makeelement(q(name))
        following = {q(n) for n in _TOP_LEVEL_ORDER[_TOP_LEVEL_ORDER.index(name) + 1 :]}
        for child in root:
            if child.tag in following:
                child.addprevious(new)
                break
        else:
            root.append(new)
        return new

    def automatic_style_containers(self) -> list[etree._Element]:
        """All ``office:automatic-styles`` elements (styles part and content part)."""
        roots = [self.styles_root]
        content = self.content_root
        if content is not None and content is not self.styles_root:
            roots.append(content)
        return [c for r in roots if (c := r.find(q("office:automatic-styles"))) is not None]

    # ------------------------------------------------------------------ embedded files
    def has_file(self, name: str) -> bool:
        return not self.flat and name in self._entries

    def read_file(self, name: str) -> bytes:
        if self.flat or name not in self._entries:
            raise OdfError(f"no embedded file {name}")
        return self._entries[name][1]

    def media_type(self, name: str) -> str:
        if not self.flat and MANIFEST_XML in self._entries:
            for entry in self._part(MANIFEST_XML).iter(q("manifest:file-entry")):
                if entry.get(q("manifest:full-path")) == name:
                    media = entry.get(q("manifest:media-type"))
                    if media:
                        return media
        return mimetypes.guess_type(name)[0] or "application/octet-stream"

    def add_file(self, name: str, data: bytes, media_type: str) -> None:
        if self.flat:
            raise OdfError("flat documents cannot hold embedded files")
        info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        self._entries[name] = (info, data)
        manifest = self._part(MANIFEST_XML)
        entry = etree.SubElement(manifest, q("manifest:file-entry"))
        entry.set(q("manifest:full-path"), name)
        entry.set(q("manifest:media-type"), media_type)
        self._modified.add(MANIFEST_XML)

    # ------------------------------------------------------------------ saving
    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        out = Path(path) if path is not None else self.path
        if out is None:
            raise ValueError("no output path given")
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            if self._flat_root is not None:
                self._flat_root.getroottree().write(
                    str(tmp), xml_declaration=True, encoding="UTF-8"
                )
            else:
                self._write_zip(tmp)
            if out.exists():
                os.chmod(tmp, out.stat().st_mode & 0o777)
            os.replace(tmp, out)
        finally:
            tmp.unlink(missing_ok=True)
        self.path = out
        return out

    def _write_zip(self, dest: Path) -> None:
        names = list(self._entries)
        if "mimetype" in names:
            names.remove("mimetype")
            names.insert(0, "mimetype")
        with zipfile.ZipFile(dest, "w") as zf:
            for name in names:
                if name == SIGNATURES_XML and self._modified:
                    # Any modification invalidates the document signature.
                    self.dropped_signature = True
                    continue
                info, data = self._entries[name]
                if name in self._modified:
                    data = etree.tostring(self._trees[name], xml_declaration=True, encoding="UTF-8")
                new_info = zipfile.ZipInfo(name, date_time=info.date_time)
                new_info.external_attr = info.external_attr
                new_info.compress_type = (
                    zipfile.ZIP_STORED if name == "mimetype" else info.compress_type
                )
                zf.writestr(new_info, data)
