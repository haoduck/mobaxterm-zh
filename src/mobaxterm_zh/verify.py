"""Independent post-patch verification.

This deliberately re-reads the produced file from disk and re-derives the
answers, rather than trusting the patcher's own bookkeeping. The checks are the
ones that would catch a corrupted executable:

  * size unchanged - a shifted stream would have changed it
  * every changed byte lies inside a string payload we identified
  * each rewritten field still has its original length and terminator
  * PE headers, section table and resource directory are untouched
  * the certificate table is untouched (the signature is already invalid by
    design, but the blob must not be damaged)
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from .extract import StringSite
from .pe import PEImage


@dataclass
class VerifyResult:
    ok: bool
    size_same: bool
    total_changed: int
    changed_in_strings: int
    changed_outside_strings: int
    offenders_sample: list[int]
    length_fields_intact: int
    length_fields_broken: int
    headers_untouched: bool
    resource_dir_untouched: bool
    cert_table_untouched: bool
    notes: list[str]

    def summary(self) -> str:
        lines = [
            f"总体结论        ：{'通过' if self.ok else '未通过'}",
            f"文件大小未变    ：{'是' if self.size_same else '否'}",
            f"改动字节数      ：{self.total_changed}",
            f"  位于字符串内  ：{self.changed_in_strings}",
            f"  位于字符串外  ：{self.changed_outside_strings}",
            f"长度字段完好    ：{self.length_fields_intact} 条正常 / "
            f"{self.length_fields_broken} 条损坏",
            f"PE 头未改动     ：{'是' if self.headers_untouched else '否'}",
            f"资源目录未改动  ：{'是' if self.resource_dir_untouched else '否'}",
            f"签名块未改动    ：{'是' if self.cert_table_untouched else '否'}",
        ]
        if self.offenders_sample:
            lines.append(
                "  越界位置      ：" +
                ", ".join(hex(o) for o in self.offenders_sample[:12]))
        lines.extend(f"提示：{n}" for n in self.notes)
        return "\n".join(lines)


def _legal_payload_offsets(original: bytes) -> set[int]:
    """Every byte offset that belongs to some indexed string payload."""
    legal: set[int] = set()
    for m in re.finditer(rb"\xff\xff\xff\xff(....)", original):
        n = struct.unpack("<I", m.group(1))[0]
        if 0 < n <= 200:
            toff = m.end()
            if toff + n + 1 <= len(original) and original[toff + n:toff + n + 1] == b"\x00":
                legal.update(range(toff, toff + n))
    return legal


def verify(original: bytes, patched: bytes, sites: list[StringSite]) -> VerifyResult:
    notes: list[str] = []

    if len(original) != len(patched):
        return VerifyResult(
            False, False, 0, 0, 0, [], 0, 0, False, False, False,
            ["文件大小已改变，该可执行文件已损坏"],
        )

    diff = [i for i in range(len(original)) if original[i] != patched[i]]

    # Legal regions: string payloads (both formats) plus the DFM spans we found.
    legal = _legal_payload_offsets(original)
    for s in sites:
        legal.update(range(s.offset, s.offset + s.length))
    outside = [i for i in diff if i not in legal]

    # Every rewritten field must still carry the right length + terminator.
    intact = broken = 0
    for s in sites:
        before = original[s.offset:s.offset + s.length]
        after = patched[s.offset:s.offset + s.length]
        if before == after:
            continue
        width = s.length_width
        got = (patched[s.length_offset:s.length_offset + width] if width == 1
               else patched[s.length_offset:s.length_offset + 4])
        want = (original[s.length_offset:s.length_offset + width] if width == 1
                else original[s.length_offset:s.length_offset + 4])
        term_ok = True
        if s.kind == "ansi_const":
            term_ok = patched[s.offset + s.length:s.offset + s.length + 1] == b"\x00"
        if got == want and len(after) == s.length and term_ok:
            intact += 1
        else:
            broken += 1

    try:
        img_o = PEImage.parse(original)
        img_p = PEImage.parse(patched)
        # Compare the DOS stub + PE headers + section table only - i.e. up to
        # the end of the section table, not a fixed 0x1000 prefix, which in a
        # small image would overlap .rsrc and include patched payload bytes.
        pe_off = struct.unpack_from("<I", original, 0x3C)[0]
        coff = pe_off + 4
        num_sections = struct.unpack_from("<H", original, coff + 2)[0]
        opt_size = struct.unpack_from("<H", original, coff + 16)[0]
        header_end = coff + 20 + opt_size + num_sections * 40
        headers_same = (
            original[:header_end] == patched[:header_end]
            and [s.__dict__ for s in img_o.sections]
            == [s.__dict__ for s in img_p.sections]
        )
        rsrc_same = True
        span_o = img_o.section_span(".rsrc")
        span_p = img_p.section_span(".rsrc")
        if span_o and span_p:
            # Compare the resource DIRECTORY structure itself, not the payload
            # that follows it: the directory is a tree of (name, offset) pairs
            # describing where each resource lives. Comparing a fixed-size
            # prefix would wrongly flag the directory whenever form data starts
            # immediately after it (which is the case in small images).
            dir_o = [(e.name, e.data_rva, e.size, e.file_offset)
                     for e in img_o.walk_resources()]
            dir_p = [(e.name, e.data_rva, e.size, e.file_offset)
                     for e in img_p.walk_resources()]
            rsrc_same = dir_o == dir_p
        cert_same = (img_o.cert_offset == img_p.cert_offset
                     and img_o.cert_size == img_p.cert_size)
        if img_p.cert_size:
            notes.append(
                "原文件带有数字签名；汉化会使该签名失效（这是必然结果），"
                "Windows 首次运行会提示未知发布者，点「更多信息 → 仍要运行」即可")
    except Exception as exc:  # pragma: no cover - defensive
        headers_same = rsrc_same = cert_same = False
        notes.append(f"PE 结构比对失败：{exc}")

    ok = (not outside) and broken == 0 and headers_same and rsrc_same and cert_same

    return VerifyResult(
        ok=ok,
        size_same=True,
        total_changed=len(diff),
        changed_in_strings=len(diff) - len(outside),
        changed_outside_strings=len(outside),
        offenders_sample=outside[:20],
        length_fields_intact=intact,
        length_fields_broken=broken,
        headers_untouched=headers_same,
        resource_dir_untouched=rsrc_same,
        cert_table_untouched=cert_same,
        notes=notes,
    )
