"""Human-readable outputs: a worklist for translators and a bilingual table."""
from __future__ import annotations

from collections import defaultdict

from .extract import StringSite
from .glossary import GlossaryAudit


def worklist(sites: list[StringSite], table: dict[str, str]) -> str:
    """Every string still untranslated, cheapest-to-fix first."""
    info: dict[str, dict] = {}
    for s in sites:
        if s.kind == "dfm_utf8":
            continue
        e = info.setdefault(s.text, {"budget": 1 << 30, "forms": set(), "count": 0})
        e["budget"] = min(e["budget"], s.length)
        e["forms"].add(s.form or "(runtime)")
        e["count"] += 1

    pending = sorted(
        (t for t in info if t not in table),
        key=lambda t: (info[t]["budget"], t),
    )

    out = [
        "# MobaXterm 译文工作清单",
        "",
        f"待翻译的唯一文本：**{len(pending)}** 条",
        "",
        "「预算」是英文原文在二进制中占用的字节数。GBK 下每个汉字 2 字节，"
        "因此预算 10 最多放 5 个汉字。译文超出预算会被拒绝（保持英文），"
        "不会被截断。",
        "",
        "| 预算 | 可放汉字 | 出现次数 | 所属窗体 | 英文原文 |",
        "| ---: | ---: | ---: | --- | --- |",
    ]
    for t in pending:
        e = info[t]
        forms = ", ".join(sorted(e["forms"])[:3])
        esc = t.replace("|", "\\|").replace("\n", "\\n")
        out.append(f"| {e['budget']} | {e['budget'] // 2} | {e['count']} | "
                   f"{forms} | `{esc}` |")
    out.append("")
    return "\n".join(out)


def bilingual(sites: list[StringSite], audit: GlossaryAudit, *,
              encoding: str = "gbk") -> str:
    """The delivered glossary, grouped by owning form, plus what stayed English."""
    info: dict[str, dict] = {}
    for s in sites:
        if s.kind == "dfm_utf8":
            continue
        e = info.setdefault(s.text, {"budget": 1 << 30, "forms": [], "count": 0})
        e["budget"] = min(e["budget"], s.length)
        e["count"] += 1
        if s.form and s.form not in e["forms"]:
            e["forms"].append(s.form)

    translated = audit.usable
    out = [
        "# MobaXterm 汉化对照表",
        "",
        f"- 已汉化：**{len(translated)}** 条唯一文本",
        f"- 保持英文：**{len(set(info) - set(translated))}** 条",
        "",
        "「预算」是原文占用的字节数。GBK 中文每字 2 字节，译文超出预算则保持英文"
        "（不会被截断显示）。",
        "",
    ]

    by_form: dict[str, list] = defaultdict(list)
    for t in translated:
        by_form[info[t]["forms"][0] if info[t]["forms"] else "(runtime)"].append(t)

    for form in sorted(by_form, key=lambda f: (-len(by_form[f]), f)):
        items = sorted(by_form[form], key=lambda t: info[t]["budget"])
        out += [f"## {form}  ({len(items)} 条)", "",
                "| 预算 | 英文原文 | 中文译文 |", "| ---: | --- | --- |"]
        for t in items:
            a = t.replace("|", "\\|").replace("\n", "\\n")
            b = translated[t].replace("|", "\\|").replace("\n", "\\n")
            out.append(f"| {info[t]['budget']} | `{a}` | {b} |")
        out.append("")

    still = sorted(set(info) - set(translated), key=lambda t: info[t]["budget"])
    out += [
        "## 保持英文的条目", "",
        "三类原因：专有名词（协议/工具/字体名）、字节预算不足、"
        "Delphi 内部组件名（界面不显示）。", "",
        "| 预算 | 英文原文 |", "| ---: | --- |",
    ]
    for t in still:
        a = t.replace("|", "\\|").replace("\n", "\\n")
        out.append(f"| {info[t]['budget']} | `{a}` |")
    out.append("")
    return "\n".join(out)
