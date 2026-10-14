"""Rewrite string payloads in place, byte-exactly.

The contract that makes this safe: **every replacement must occupy exactly the
same number of bytes as the original.** Both storage formats encode the length
in the stream, so changing it would shift everything after it.

When the Chinese text is shorter than the original, the remainder is padded
with spaces (0x20). Trailing spaces are invisible on a label, and they keep the
length field honest. When the Chinese text is *longer*, the replacement is
refused and reported - it is never truncated, because a truncated label reads
as a bug.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .extract import StringSite


class PatchError(RuntimeError):
    pass


@dataclass
class PatchReport:
    written: int = 0
    padded: int = 0
    refused_too_long: int = 0
    refused_wrong_encoding: int = 0
    refused_wrong_field: int = 0
    refused_utf8_target: int = 0
    no_translation: int = 0
    bytes_changed: int = 0
    problems: list[tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["problems"] = self.problems[:50]
        return d


def encode_for(site: StringSite, text: str, encoding: str) -> bytes:
    """Encode ``text`` for ``site``'s storage format, or raise ValueError."""
    if site.kind == "dfm_utf8":
        return text.encode("utf-8")
    return text.encode(encoding)


def patch(data: bytearray, sites, table: dict[str, str], *,
          encoding: str = "gbk", dry_run: bool = False) -> PatchReport:
    """Apply ``table`` to ``data`` at the offsets described by ``sites``.

    ``table`` maps the original English string to its replacement. Returns a
    report describing what happened, including every refusal.
    """
    report = PatchReport()
    written_offsets: set[int] = set()

    for site in sites:
        if site.offset in written_offsets:
            continue
        repl = table.get(site.text)
        if repl is None or repl == "" or repl.strip() == site.text.strip():
            report.no_translation += 1
            continue

        # A vaUTF8String field holds UTF-8 bytes. Writing GBK there would
        # produce mojibake, so it is refused and flagged.
        if site.kind == "dfm_utf8" and encoding.lower() not in ("utf-8", "utf8"):
            report.refused_utf8_target += 1
            report.problems.append(
                (site.text[:60], "目标字段是 UTF-8 编码，需要 UTF-8 词表"))
            continue

        try:
            payload = encode_for(site, repl, encoding)
        except UnicodeEncodeError:
            report.refused_wrong_encoding += 1
            report.problems.append(
                (site.text[:60], f"译文无法用 {encoding} 编码表示"))
            continue

        if len(payload) > site.length:
            report.refused_too_long += 1
            report.problems.append((
                site.text[:60],
                f"需要 {len(payload)} 字节，但该位置只有 {site.length} 字节"))
            continue

        # Refuse if the stream no longer matches what we indexed - never write
        # blindly against a stale offset.
        current = bytes(data[site.offset:site.offset + site.length])
        try:
            if site.kind == "dfm_utf8":
                current_text = current.decode("utf-8")
            else:
                current_text = current.decode("latin1")
        except UnicodeDecodeError:
            report.refused_wrong_field += 1
            continue
        if current_text != site.text:
            report.refused_wrong_field += 1
            report.problems.append((site.text[:60], "二进制文件已变动，偏移失效"))
            continue

        if len(payload) < site.length:
            payload = payload + b" " * (site.length - len(payload))
            report.padded += 1

        if not dry_run:
            data[site.offset:site.offset + site.length] = payload
        written_offsets.add(site.offset)
        report.written += 1
        report.bytes_changed += sum(
            1 for a, b in zip(current, payload) if a != b
        )

    return report
