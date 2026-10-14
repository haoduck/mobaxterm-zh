"""Minimal PE reader: enough to locate the resource directory and read the
Authenticode certificate table, without pulling in a dependency.

Only the fields MobaXterm patching needs are decoded.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator


class PEError(ValueError):
    """Raised when a file is not a PE image, or the PE data is truncated."""


@dataclass(frozen=True)
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_address: int
    raw_size: int


@dataclass(frozen=True)
class ResourceEntry:
    """One leaf of the resource directory."""

    name: int
    data_rva: int
    size: int
    file_offset: int


@dataclass
class PEImage:
    data: bytes
    image_base: int
    sections: list[Section] = field(default_factory=list)
    cert_offset: int = 0
    cert_size: int = 0

    # -- construction ---------------------------------------------------
    @classmethod
    def parse(cls, data: bytes) -> "PEImage":
        if len(data) < 0x40:
            raise PEError("file too small to be a PE image")
        if data[:2] != b"MZ":
            raise PEError("missing MZ signature - not a PE file")
        pe_off = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_off + 24 > len(data) or data[pe_off:pe_off + 4] != b"PE\x00\x00":
            raise PEError("missing PE signature")

        coff = pe_off + 4
        num_sections = struct.unpack_from("<H", data, coff + 2)[0]
        opt_size = struct.unpack_from("<H", data, coff + 16)[0]
        opt = coff + 20
        magic = struct.unpack_from("<H", data, opt)[0]
        if magic == 0x20B:  # PE32+
            image_base = struct.unpack_from("<Q", data, opt + 24)[0]
            dd = opt + 112
        elif magic == 0x10B:  # PE32
            image_base = struct.unpack_from("<I", data, opt + 28)[0]
            dd = opt + 96
        else:
            raise PEError(f"unknown optional-header magic 0x{magic:04X}")

        image = cls(data=data, image_base=image_base)

        sec = opt + opt_size
        for i in range(num_sections):
            off = sec + i * 40
            if off + 40 > len(data):
                raise PEError("section table is truncated")
            name = data[off:off + 8].rstrip(b"\x00").decode("latin1")
            vsz, va, rsz, ra = struct.unpack_from("<IIII", data, off + 8)
            image.sections.append(Section(name, va, vsz, ra, rsz))

        # data directory 4 = security/certificate table (file offset, not RVA)
        if dd + 4 * 8 + 8 <= len(data):
            image.cert_offset, image.cert_size = struct.unpack_from(
                "<II", data, dd + 4 * 8
            )
        return image

    # -- lookups --------------------------------------------------------
    def rva_to_offset(self, rva: int) -> int | None:
        for s in self.sections:
            span = max(s.virtual_size, s.raw_size)
            if s.virtual_address <= rva < s.virtual_address + span:
                off = rva - s.virtual_address + s.raw_address
                if off < len(self.data):
                    return off
        return None

    @property
    def section_names(self) -> list[str]:
        return [s.name for s in self.sections]

    def section_span(self, name: str) -> tuple[int, int] | None:
        """(file_start, file_end) of a section, or None if absent."""
        for s in self.sections:
            if s.name == name:
                return s.raw_address, s.raw_address + s.raw_size
        return None

    def resource_base(self) -> int:
        """File offset of the resource section; raises if there is none."""
        span = self.section_span(".rsrc")
        if span is None:
            raise PEError("no .rsrc section - not a Delphi form resource image")
        return span[0]

    def walk_resources(self) -> Iterator[ResourceEntry]:
        """Yield every leaf data entry in the resource directory."""
        base = self.resource_base()
        seen: set[int] = set()

        def walk(rel: int, depth: int) -> Iterator[ResourceEntry]:
            if depth > 3 or rel in seen:
                return
            seen.add(rel)
            off = base + rel
            if off + 16 > len(self.data):
                return
            named, ids = struct.unpack_from("<HH", self.data, off + 12)
            for i in range(named + ids):
                eo = off + 16 + i * 8
                if eo + 8 > len(self.data):
                    return
                name, target = struct.unpack_from("<II", self.data, eo)
                if target & 0x80000000:
                    yield from walk(target & 0x7FFFFFFF, depth + 1)
                else:
                    de = base + target
                    if de + 16 > len(self.data):
                        return
                    rva, size, _codepage, _ = struct.unpack_from(
                        "<IIII", self.data, de
                    )
                    foff = self.rva_to_offset(rva)
                    if foff is not None:
                        yield ResourceEntry(name, rva, size, foff)

        yield from walk(0, 0)
