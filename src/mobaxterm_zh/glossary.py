"""Glossary loading, auditing and reporting."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .extract import StringSite

MARKUP_TOKENS = ("<br>", "<br/>", "<u>", "</u>", "<b>", "</b>", "\r\n",
                 "\n", "%s", "%d", '""', "&", "</a>", "<a ")


class GlossaryError(RuntimeError):
    pass


def markup_counts(s: str) -> dict[str, int]:
    return {m: s.count(m) for m in MARKUP_TOKENS if m in s}


@dataclass
class GlossaryAudit:
    usable: dict[str, str]
    too_long: list[tuple[str, str, int, int]]
    unencodable: list[tuple[str, str]]
    markup_loss: list[tuple[str, str]]
    not_in_binary: list[str]

    def summary(self) -> str:
        return (
            f"词表条目        ："
            f"{len(self.usable) + len(self.too_long) + len(self.unencodable)}\n"
            f"  可用          ：{len(self.usable)}\n"
            f"  超出字节预算  ：{len(self.too_long)}\n"
            f"  无法用 GBK 编码：{len(self.unencodable)}\n"
            f"  标记符号不完整：{len(self.markup_loss)}\n"
            f"  本版本中不存在：{len(self.not_in_binary)}"
        )


GLOSSARY_NAME = "translations.zh-CN.json"


def bundled_glossary_text() -> str:
    """Read the packaged glossary, whether running from source or frozen.

    ``importlib.resources`` is the correct API for an installed package, but a
    PyInstaller one-file build unpacks into a temporary directory and the
    import machinery is not always able to see data files through it. PyInstaller
    exposes that directory as ``sys._MEIPASS``; checking it explicitly is what
    keeps a frozen binary from failing where the source tree works fine.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "mobaxterm_zh" / "data" / GLOSSARY_NAME
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")

    # also look beside the executable, so a glossary can be shipped next to it
    exe_dir = Path(sys.executable).resolve().parent
    for candidate in (exe_dir / GLOSSARY_NAME,
                      exe_dir / "mobaxterm_zh" / "data" / GLOSSARY_NAME):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")

    try:
        return (resources.files("mobaxterm_zh")
                .joinpath(f"data/{GLOSSARY_NAME}")
                .read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, AttributeError) as exc:
        raise GlossaryError(
            f"未找到内置词表 {GLOSSARY_NAME!r}；可用 --table 指定一个词表文件"
            f"（{exc}）"
        ) from exc


def load(path: str | None = None) -> dict[str, str]:
    """Load a glossary from ``path``, or from the bundled Simplified Chinese one."""
    if path:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = json.loads(bundled_glossary_text())
    if not isinstance(data, dict):
        raise GlossaryError("glossary must be a JSON object of {english: chinese}")
    return {str(k): str(v) for k, v in data.items()}


def audit(table: dict[str, str], sites: list[StringSite], *,
          encoding: str = "gbk") -> GlossaryAudit:
    """Check a glossary against the strings actually present in this build.

    The budget is the SMALLEST byte length that string occupies anywhere in the
    file: one string usually appears in several forms, and the tightest slot is
    the one that decides whether the translation can be written at all.
    """
    budget: dict[str, int] = {}
    kinds: dict[str, set[str]] = {}
    for s in sites:
        if s.kind == "dfm_utf8":
            continue
        budget[s.text] = min(budget.get(s.text, 1 << 30), s.length)
        kinds.setdefault(s.text, set()).add(s.kind)

    usable: dict[str, str] = {}
    too_long, unencodable, markup_loss, absent = [], [], [], []

    for src, dst in table.items():
        if src not in budget:
            absent.append(src)
            continue
        if not dst.strip():
            continue
        try:
            need = len(dst.encode(encoding))
        except UnicodeEncodeError:
            unencodable.append((src, dst))
            continue
        cap = budget[src]
        if need > cap:
            too_long.append((src, dst, need, cap))
            continue
        if markup_counts(src) != markup_counts(dst):
            markup_loss.append((src, dst))
            continue
        usable[src] = dst

    return GlossaryAudit(usable, too_long, unencodable, markup_loss, absent)


def coverage(table: dict[str, str], sites: list[StringSite]) -> dict[str, int]:
    uniq = {s.text for s in sites if s.kind != "dfm_utf8"}
    done = uniq & set(table)
    return {
        "unique_strings": len(uniq),
        "unique_translated": len(done),
        "instances": len(sites),
        "instances_translated": sum(1 for s in sites if s.text in table),
    }
