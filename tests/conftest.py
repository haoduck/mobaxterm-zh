"""Synthetic fixtures so the tests never touch a real 16 MB executable."""
from __future__ import annotations

import struct


def be32(v: int) -> bytes:
    return struct.pack("<I", v)


def make_pe(*, resource_blob: bytes = b"", code_blob: bytes = b"",
            certificate: bytes = b"") -> bytes:
    """Build a minimal but structurally valid PE32+ image.

    Layout: DOS header + stub, PE headers, .rsrc section (resource blob at its
    start, then 8 bytes of resource directory), .text section (code blob).
    """
    FILE_ALIGN = 0x200
    SECT_ALIGN = 0x1000
    rsrc_rva = 0x1000
    text_rva = 0x2000

    rsrc_raw = 0x200
    text_raw = rsrc_raw + ((len(resource_blob) + 16 + FILE_ALIGN - 1)
                           // FILE_ALIGN) * FILE_ALIGN

    n_sections = 2
    opt_size = 240  # PE32+ with 16 data directories
    headers_raw = 0x200

    # ---- DOS header
    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)  # e_lfanew -> PE right after

    # ---- PE signature + COFF header
    coff = bytearray(20)
    struct.pack_into("<H", coff, 0, 0x8664)      # Machine: x64
    struct.pack_into("<H", coff, 16, opt_size)   # SizeOfOptionalHeader
    struct.pack_into("<H", coff, 2, n_sections)

    # ---- Optional header (PE32+)
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x20B)        # Magic PE32+
    struct.pack_into("<Q", opt, 24, 0x140000000)  # ImageBase
    struct.pack_into("<I", opt, 32, SECT_ALIGN)   # SectionAlignment
    struct.pack_into("<I", opt, 36, FILE_ALIGN)   # FileAlignment
    struct.pack_into("<H", opt, 68, n_sections)   # NumberOfSections
    struct.pack_into("<H", opt, 70, 240)          # SizeOfOptionalHeader

    # data directory 2 = resource table (RVA), 4 = certificate (file offset)
    dd = 112
    struct.pack_into("<I", opt, dd + 2 * 8, rsrc_rva)
    struct.pack_into("<I", opt, dd + 2 * 8 + 4, len(resource_blob) + 16)
    if certificate:
        cert_off = text_raw + ((len(code_blob) + FILE_ALIGN - 1)
                               // FILE_ALIGN) * FILE_ALIGN
        struct.pack_into("<I", opt, dd + 4 * 8, cert_off)
        struct.pack_into("<I", opt, dd + 4 * 8 + 4, len(certificate))

    # ---- section table
    secs = bytearray()
    # .rsrc
    s = bytearray(40)
    s[0:6] = b".rsrc\x00"
    struct.pack_into("<I", s, 8, len(resource_blob) + 16)   # VirtualSize
    struct.pack_into("<I", s, 12, rsrc_rva)
    struct.pack_into("<I", s, 16, len(resource_blob) + 16)  # SizeOfRawData
    struct.pack_into("<I", s, 20, rsrc_raw)
    secs += s
    # .text
    s = bytearray(40)
    s[0:6] = b".text\x00"
    struct.pack_into("<I", s, 8, len(code_blob))
    struct.pack_into("<I", s, 12, text_rva)
    struct.pack_into("<I", s, 16, len(code_blob))
    struct.pack_into("<I", s, 20, text_raw)
    secs += s

    head = bytes(dos) + b"PE\x00\x00" + bytes(coff) + bytes(opt) + bytes(secs)
    head = head.ljust(headers_raw, b"\x00")

    rsrc = (resource_blob + b"\x00" * 8).ljust(
        rsrc_raw + len(resource_blob) + 16, b"\x00")
    text = code_blob.ljust(text_raw + len(code_blob), b"\x00")

    img = bytearray(head + rsrc + text)
    if certificate:
        cert_raw = cert_off
        img = img.ljust(cert_raw, b"\x00") + certificate
    return bytes(img)


def dfm_form(class_name: str, object_name: str) -> bytes:
    """A TPF0 header followed by a class name and object name."""
    out = bytearray(b"TPF0")
    out.append(len(class_name))
    out += class_name.encode("latin1")
    out.append(len(object_name))
    out += object_name.encode("latin1")
    return bytes(out)


def dfm_short(prop: str, text: str) -> bytes:
    """<len><prop><tag 6><len><text>"""
    p = prop.encode("latin1")
    t = text.encode("latin1")
    return (bytes([len(p)]) + p + b"\x06" + bytes([len(t)]) + t)


def dfm_long(prop: str, text: str) -> bytes:
    """<len><prop><tag 12><4-byte len><text>"""
    p = prop.encode("latin1")
    t = text.encode("latin1")
    return bytes([len(p)]) + p + b"\x0c" + be32(len(t)) + t


def ansi_const(text: str) -> bytes:
    """ff ff ff ff <4-byte len><text>00"""
    t = text.encode("latin1")
    return b"\xff\xff\xff\xff" + be32(len(t)) + t + b"\x00"
