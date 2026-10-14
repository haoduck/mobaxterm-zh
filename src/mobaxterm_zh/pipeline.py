"""汉化流水线：命令行与图形界面共用的核心逻辑。

把处理过程封装在这里，GUI 和 CLI 才能保证行为完全一致 —— 两条路径调用的是
同一段代码，而不是各自实现一遍。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .extract import extract
from .glossary import audit, load
from .patch import patch
from .pe import PEError
from .verify import VerifyResult, verify

DEFAULT_ENCODING = "gbk"


@dataclass
class PatchOutcome:
    """一次汉化的完整结果，供界面展示或命令行打印。"""

    ok: bool
    output_path: Path | None = None
    translated: int = 0
    padded: int = 0
    refused_too_long: int = 0
    refused_encoding: int = 0
    refused_utf8: int = 0
    refused_stale: int = 0
    untranslated: int = 0
    bytes_changed: int = 0
    strings_found: int = 0
    verification: VerifyResult | None = None
    problems: list[tuple[str, str]] = field(default_factory=list)
    message: str = ""

    def report_lines(self) -> list[str]:
        """中文报告，可直接写入界面日志或打印到终端。"""
        L = [
            f"源文件          ：{self.message}",
            f"检出字符串      ：{self.strings_found}",
            f"已写入译文      ：{self.translated}",
            f"  其中补空格对齐：{self.padded}",
            f"拒绝（超出预算）: {self.refused_too_long}",
            f"拒绝（无法编码）: {self.refused_encoding}",
            f"拒绝（偏移失效）: {self.refused_stale}",
            f"拒绝（UTF-8 字段）: {self.refused_utf8}",
            f"无译文          ：{self.untranslated}",
            f"改动字节数      ：{self.bytes_changed}",
        ]
        if self.output_path is not None:
            L.append(f"已写入          ：{self.output_path}"
                     f"（{self.output_path.stat().st_size:,} 字节）")
        if self.verification is not None:
            L.append("")
            L.append(self.verification.summary())
        return L


def default_output_path(src: Path) -> Path:
    """与命令行一致的默认输出名：<原名>_zh.exe"""
    return src.with_name(src.stem + "_zh.exe")


def run_patch(src: Path, out: Path | None = None, *,
              table_path: str | None = None,
              encoding: str = DEFAULT_ENCODING,
              dry_run: bool = False,
              verbose: bool = False) -> PatchOutcome:
    """对 ``src`` 执行一次汉化。

    不抛异常 —— 失败信息装进 ``PatchOutcome``，让界面可以直接显示而命令
    行可以打印。
    """
    src = Path(src)
    out = Path(out) if out else default_output_path(src)

    try:
        original = src.read_bytes()
    except OSError as exc:
        return PatchOutcome(ok=False, message=f"无法读取源文件：{exc}")

    try:
        sites = extract(original)
    except PEError as exc:
        return PatchOutcome(ok=False,
                            message=f"这不是有效的 Windows 可执行文件：{exc}")

    try:
        table = load(table_path)
    except Exception as exc:
        return PatchOutcome(ok=False, message=f"无法加载词表：{exc}")

    a = audit(table, sites, encoding=encoding)
    data = bytearray(original)
    report = patch(data, sites, a.usable, encoding=encoding, dry_run=dry_run)

    outcome = PatchOutcome(
        ok=True,
        translated=report.written,
        padded=report.padded,
        refused_too_long=report.refused_too_long,
        refused_encoding=report.refused_wrong_encoding,
        refused_utf8=report.refused_utf8_target,
        refused_stale=report.refused_wrong_field,
        untranslated=report.no_translation,
        bytes_changed=report.bytes_changed,
        strings_found=len(sites),
        problems=report.problems if verbose else [],
        message=f"{src}（{len(original):,} 字节）",
    )

    if dry_run:
        outcome.output_path = None
        return outcome

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(bytes(data))
    except OSError as exc:
        return PatchOutcome(ok=False, message=f"无法写入输出文件：{exc}")

    outcome.output_path = out
    outcome.verification = verify(original, out.read_bytes(), sites)
    outcome.ok = outcome.verification.ok
    return outcome
