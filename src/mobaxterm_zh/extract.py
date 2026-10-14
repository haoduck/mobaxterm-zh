"""Find every user-visible string in a MobaXterm build and record where it
lives, so it can be rewritten in place.

Two storage classes exist in a Delphi executable:

1.  **DFM form resources** (.rsrc, RT_RCDATA). A property is

        <name-length byte><name><value tag><value>

    and a string value is either a 1-byte-length short string (tags 6/7) or a
    4-byte-length long string (tag 12). We look for the byte pattern of a
    known display property name followed by such a value. This is deliberately
    a pattern scan rather than a full DFM walk: a complete walk must understand
    every TValueType, and this build embeds LZMA-compressed skin blobs inside
    properties, which is where a strict walker stalls. The strings we want are
    self-identifying, so scanning for them is both simpler and more robust.

2.  **Runtime AnsiString constants**, in the code image. Delphi lays these out
    as

        ff ff ff ff  <length:4 LE>  <chars...>  00

    A full structural DFM parse is not needed to find these either.

Every located string carries its byte offset and its exact original length.
That length is the budget a replacement must fit inside, because both formats
encode it in the stream.
"""
from __future__ import annotations

import re
import struct
from dataclasses import asdict, dataclass

from .pe import PEImage

# Properties whose value a user actually reads on screen.
DISPLAY_PROPS = (
    "Caption", "Text", "Hint", "Title", "ToolTip", "Message", "Label",
    "PlaceholderText", "Header", "BalloonText", "Description", "Lines",
    "Items", "Values", "Strings",
)

# Delphi TValueType values used for string payloads.
_TAG_SHORT = (6, 7)   # vaString, vaIdent  -> 1-byte length
_TAG_LONG = (12,)     # vaLString           -> 4-byte length
_TAG_UTF8 = (20,)     # vaUTF8String        -> 4-byte length, UTF-8 bytes

_PRINTABLE = set(range(32, 127)) | {9, 10, 13}
_IDENT_RE = re.compile(rb"^[A-Za-z_][A-Za-z0-9_.]*$")
_CJK_RE = re.compile(r"[一-鿿]")


@dataclass(frozen=True)
class StringSite:
    """One translatable string occurrence inside the binary."""

    text: str
    offset: int
    length: int          # exact original byte length = the budget
    kind: str            # "dfm_short" | "dfm_long" | "dfm_utf8" | "ansi_const"
    form: str            # owning DFM form class, or "" for code constants
    prop: str            # property name that carried it
    length_offset: int   # where the length field lives (for patching/verify)
    length_width: int    # 1 or 4

    def to_json(self) -> dict:
        return asdict(self)


class ExtractionError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _is_display_text(text: str, prop: str) -> bool:
    """Filter out component names, numbers and other non-UI values."""
    if prop not in ("Caption", "Title", "Hint", "ToolTip", "Label", "Message",
                    "PlaceholderText", "Header", "BalloonText"):
        return False
    return bool(text.strip())


def _is_prose(text: str, prop: str) -> bool:
    if _is_display_text(text, prop):
        return True
    if len(text) < 3:
        return False
    if re.fullmatch(r"[A-Za-z0-9_.]+", text) and len(text) < 12:
        return False
    return " " in text or bool(_CJK_RE.search(text))


# --------------------------------------------------------------------------
# form index
# --------------------------------------------------------------------------
def _form_index(data: bytes, rsrc_lo: int, rsrc_hi: int) -> list[tuple[int, str, str]]:
    """Map each TPF0 header offset to (class, object name)."""
    out = []
    for m in re.finditer(b"TPF0", data[rsrc_lo:rsrc_hi]):
        base = rsrc_lo + m.start()
        try:
            o = base + 4
            n = data[o]
            cls = data[o + 1:o + 1 + n].decode("latin1")
            o += 1 + n
            n2 = data[o]
            nm = data[o + 1:o + 1 + n2].decode("latin1")
        except Exception:
            continue
        out.append((base, cls, nm))
    out.sort()
    return out


def _owner(forms: list[tuple[int, str, str]], offset: int) -> tuple[str, str]:
    lo, hi, best = 0, len(forms) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if forms[mid][0] <= offset:
            best = forms[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return (best[1], best[2]) if best else ("?", "?")


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def extract(data: bytes, *, include_ansi_constants: bool = True
            ) -> list[StringSite]:
    """Return every translatable string site in ``data``, deduplicated by
    offset and sorted by offset."""
    image = PEImage.parse(data)
    rsrc_lo, rsrc_hi = image.section_span(".rsrc")  # type: ignore[misc]
    forms = _form_index(data, rsrc_lo, rsrc_hi)

    sites: dict[int, StringSite] = {}

    # -- DFM property values -------------------------------------------
    for prop in DISPLAY_PROPS:
        key = bytes([len(prop)]) + prop.encode("ascii")
        cursor = rsrc_lo
        while True:
            i = data.find(key, cursor, rsrc_hi)
            if i < 0:
                break
            cursor = i + 1
            o = i + len(key)
            if o >= rsrc_hi:
                continue
            tag = data[o]
            o += 1

            if tag in _TAG_SHORT:
                if o >= rsrc_hi:
                    continue
                n = data[o]
                doff = o + 1
                kind = "dfm_short"
            elif tag in _TAG_LONG or tag in _TAG_UTF8:
                if o + 4 > rsrc_hi:
                    continue
                n = struct.unpack_from("<i", data, o)[0]
                if n <= 0 or n > 4096:
                    continue
                doff = o + 4
                kind = "dfm_utf8" if tag in _TAG_UTF8 else "dfm_long"
            else:
                continue

            if n == 0 or doff + n > rsrc_hi or doff in sites:
                continue
            raw = data[doff:doff + n]

            if kind == "dfm_utf8":
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if not re.search(r"[A-Za-z一-鿿]", text):
                    continue
                # A UTF-8 field cannot hold GBK bytes; leave it for a UTF-8
                # glossary rather than writing mojibake into it.
                length_width = 4
            else:
                if not all(b in _PRINTABLE for b in raw):
                    continue
                text = raw.decode("latin1")
                length_width = 1

            if not text.strip() or not _is_prose(text, prop):
                continue
            cls, nm = _owner(forms, doff)
            sites[doff] = StringSite(
                text=text, offset=doff, length=n, kind=kind, form=cls,
                prop=prop, length_offset=doff - length_width,
                length_width=length_width,
            )

    # -- runtime AnsiString constants ---------------------------------
    if include_ansi_constants:
        for m in re.finditer(rb"\xff\xff\xff\xff(....)", data):
            n = struct.unpack("<I", m.group(1))[0]
            if n == 0 or n > 200:
                continue
            toff = m.end()
            tend = toff + n
            if tend + 1 > len(data) or data[tend:tend + 1] != b"\x00":
                continue
            raw = data[toff:tend]
            if not all(32 <= b < 127 for b in raw):
                continue
            text = raw.decode("latin1")
            if not text.strip() or toff in sites:
                continue
            sites[toff] = StringSite(
                text=text, offset=toff, length=n, kind="ansi_const", form="",
                prop="", length_offset=toff - 4, length_width=4,
            )

    return [sites[k] for k in sorted(sites)]
