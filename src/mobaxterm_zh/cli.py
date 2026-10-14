"""命令行接口：extract / patch / verify / report。

所有面向用户的输出均为简体中文。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .extract import extract
from .glossary import GlossaryError, audit, coverage, load
from .pe import PEImage, PEError
from .report import bilingual, worklist


def _die(msg: str) -> int:
    print(f"错误：{msg}", file=sys.stderr)
    return 2


def cmd_inspect(args: argparse.Namespace) -> int:
    data = Path(args.exe).read_bytes()
    try:
        img = PEImage.parse(data)
    except PEError as exc:
        return _die(str(exc))
    span = img.section_span(".rsrc")
    print(f"文件            ：{args.exe}")
    print(f"大小            ：{len(data):,} 字节")
    print(f"映像基址        ：0x{img.image_base:X}")
    print(f"节表            ：{', '.join(img.section_names)}")
    print(f".rsrc 段        ："
          f"{'0x%X..0x%X' % span if span else '不存在'}")
    signed = "有（汉化会使其失效）" if img.cert_size else "无"
    print(f"数字签名        ：{signed}")
    sites = extract(data, include_ansi_constants=not args.no_ansi)
    uniq = {s.text for s in sites}
    print(f"检出字符串      ：{len(sites)} 处 / {len(uniq)} 条唯一文本")
    kinds = {}
    for s in sites:
        kinds[s.kind] = kinds.get(s.kind, 0) + 1
    names = {
        "dfm_short": "窗体短字符串",
        "dfm_long": "窗体长字符串",
        "dfm_utf8": "窗体 UTF-8 字符串",
        "ansi_const": "运行期常量",
    }
    for k, v in sorted(kinds.items()):
        print(f"  {names.get(k, k):<12} {v}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    data = Path(args.exe).read_bytes()
    sites = extract(data, include_ansi_constants=not args.no_ansi)
    payload = [s.to_json() for s in sites]
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已导出 {len(sites)} 处字符串 -> {args.out}")

    if args.worklist:
        table = {}
        if Path(args.worklist).exists():
            table = load(args.worklist)
        Path(args.worklist).write_text(
            worklist(sites, table), encoding="utf-8")
        print(f"译文工作清单 -> {args.worklist}")
    return 0


def cmd_glossary(args: argparse.Namespace) -> int:
    table = load(args.table)
    data = Path(args.exe).read_bytes()
    sites = extract(data, include_ansi_constants=True)
    a = audit(table, sites, encoding=args.encoding)
    print(a.summary())
    cov = coverage(a.usable, sites)
    print()
    print(f"唯一文本        ：{cov['unique_strings']}")
    print(f"  已汉化        ：{cov['unique_translated']}")
    print(f"界面实例        ：{cov['instances']}")
    print(f"  已汉化        ：{cov['instances_translated']}")
    if args.out:
        Path(args.out).write_text(bilingual(sites, a), encoding="utf-8")
        print(f"\n中英对照表 -> {args.out}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    """启动图形界面。放在函数内 import，这样无图形环境下 --help 等命令不受影响。"""
    from .gui import main as gui_main
    return gui_main(args.exe or None)


def cmd_patch(args: argparse.Namespace) -> int:
    from .pipeline import run_patch
    src = Path(args.exe)
    out = Path(args.out) if args.out else None
    outcome = run_patch(
        src, out, table_path=args.table, encoding=args.encoding,
        dry_run=args.dry_run, verbose=args.verbose)

    if not outcome.ok and outcome.verification is None:
        # 读取/解析/写入阶段就失败了，没有报告可打印
        print(f"错误：{outcome.message}", file=sys.stderr)
        return 2

    for line in outcome.report_lines():
        print(line)

    if args.dry_run:
        return 0
    if not outcome.ok:
        print("\n警告：校验未通过，请勿使用该文件", file=sys.stderr)
        return 1
    return 0


def cmd_selfcheck(args: argparse.Namespace) -> int:
    """确认内置词表可读（打包后自检用）。"""
    try:
        table = load(args.table)
    except GlossaryError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    where = "内置" if not args.table else args.table
    print(f"词表条目        ：{len(table)}")
    print(f"来源            ：{where}")
    for k in list(table)[:3]:
        print(f"  {k!r:<24} -> {table[k]!r}")
    print("自检通过")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    original = Path(args.original).read_bytes()
    patched = Path(args.patched).read_bytes()
    sites = extract(original, include_ansi_constants=True)
    res = verify(original, patched, sites)
    print(res.summary())
    return 0 if res.ok else 1


def _make_console_safe() -> None:
    """避免控制台无法编码中文时崩溃。

    本工具会输出简体中文。在编码不了的控制台上（英文区域设置的 Windows
    常见为 cp1252），Python 会在第一个中文字符处抛出 UnicodeEncodeError，
    程序还没开始干活就死了。

    把输出流改成 utf-8 + errors="replace" 之后，无法表示的字符降级显示，
    程序照常运行；能显示中文的控制台（cp936、cp65001）行为不变。

    这里同时设置 PYTHONIOENCODING，避免调用方又把更窄的编码塞回来。
    """
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


class _ZHParser(argparse.ArgumentParser):
    """把 argparse 自身的报错信息也汉化。

    其余输出（子命令名、选项名）保持英文：它们要出现在命令行里，是用户
    实际敲进去的内容，翻译成中文会让文档和示例对不上。
    """

    def error(self, message: str):
        message = (message
                   .replace("argument 命令: ", "")
                   .replace("invalid choice:", "无效的子命令：")
                   .replace("choose from", "可用子命令：")
                   .replace("is required", "为必填项")
                   .replace("unrecognized arguments:", "无法识别的参数：")
                   .replace("expected one argument", "需要一个参数")
                   .replace("ambiguous option:", "有歧义的选项：")
                   .replace("Error: ", "错误："))
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: 错误：{message}\n")


class _ZHFormatter(argparse.RawDescriptionHelpFormatter):
    """argparse 的段落标题与 usage 引导语默认是英文，这里一并汉化。"""

    def add_usage(self, usage, actions, groups, prefix=None):
        if prefix is None:
            prefix = "用法："
        super().add_usage(usage, actions, groups, prefix)

    def start_section(self, heading):
        heading = {
            "positional arguments": "位置参数",
            "options": "可选参数",
            "optional arguments": "可选参数",
        }.get(heading, heading)
        super().start_section(heading)


def _add_parser(sub, name, **kw):
    """子解析器不会继承父级的 formatter_class，必须逐个指定。

    解析器类（_ZHParser）会由 add_subparsers 自动继承，无需显式传入 ——
    Python 3.10 没有 parser_class 这个参数。
    """
    kw.setdefault("formatter_class", _ZHFormatter)
    sp = sub.add_parser(name, **kw)
    for a in sp._actions:
        if a.dest == "help" and a.option_strings == ["-h", "--help"]:
            a.help = "显示此帮助信息并退出"
    return sp


def build_parser() -> argparse.ArgumentParser:
    p = _ZHParser(
        prog="mobaxterm-zh",
        description="将官方原版 MobaXterm 汉化为简体中文。",
        formatter_class=_ZHFormatter,
    )
    p.add_argument("--version", action="version",
                   version=f"mobaxterm-zh {__version__}",
                   help="显示版本号并退出")
    # argparse auto-adds -h/--help; re-declaring it raises a conflict error, so
    # amend the existing action's help text in place instead.
    for a in p._actions:
        if a.dest == "help" and a.option_strings == ["-h", "--help"]:
            a.help = "显示此帮助信息并退出"
    sub = p.add_subparsers(dest="cmd", required=True, metavar="命令",
                            title="子命令")

    def add_encoding(sp):
        sp.add_argument("--encoding", default="gbk",
                        metavar="编码",
                        help="译文的编码方式（默认：gbk）")

    sp = _add_parser(sub, "inspect", help="查看可执行文件的基本信息",
                     description="查看 MobaXterm 可执行文件的结构与字符串统计。")
    sp.add_argument("exe", help="待查看的 MobaXterm 可执行文件")
    sp.add_argument("--no-ansi", action="store_true",
                    help="跳过运行期字符串常量")
    sp.set_defaults(func=cmd_inspect)

    sp = _add_parser(sub, "extract", help="导出全部可翻译字符串",
                     description="导出可执行文件中所有可翻译的界面字符串。")
    sp.add_argument("exe", help="待处理的 MobaXterm 可执行文件")
    sp.add_argument("-o", "--out", default="strings.json", metavar="文件",
                    help="输出文件路径（默认：strings.json）")
    sp.add_argument("--worklist", metavar="文件",
                    help="同时生成译文工作清单")
    sp.add_argument("--no-ansi", action="store_true",
                    help="跳过运行期字符串常量")
    sp.set_defaults(func=cmd_extract)

    sp = _add_parser(sub, "glossary", help="审查词表对某个版本的覆盖率",
                     description="检查词表在指定版本中的可用比例。")
    sp.add_argument("exe", help="待处理的 MobaXterm 可执行文件")
    sp.add_argument("--table", metavar="文件",
                    help="词表 JSON（默认：内置简体中文词表）")
    sp.add_argument("-o", "--out", metavar="文件",
                    help="输出中英对照表（markdown）")
    add_encoding(sp)
    sp.set_defaults(func=cmd_glossary)

    sp = _add_parser(sub, "gui", help="启动图形界面",
                     description="打开简易窗口：选择文件（或拖入）后执行汉化。")
    sp.add_argument("exe", nargs="?",
                    help="可选：启动时预填的源文件路径")
    sp.set_defaults(func=cmd_gui)

    sp = _add_parser(sub, "patch", help="生成汉化后的可执行文件",
                     description="把界面字符串替换为中文，生成同尺寸的新文件。")
    sp.add_argument("exe", help="官方原版 MobaXterm 可执行文件")
    sp.add_argument("-o", "--out", metavar="文件",
                    help="输出路径（默认：<原名>_zh.exe）")
    sp.add_argument("--table", metavar="文件",
                    help="词表 JSON（默认：内置简体中文词表）")
    sp.add_argument("--dry-run", action="store_true",
                    help="只报告将要改动的内容，不写入文件")
    sp.add_argument("--no-ansi", action="store_true",
                    help="不修改运行期字符串常量")
    sp.add_argument("--verbose", action="store_true",
                    help="列出每一条被拒绝的译文")
    add_encoding(sp)
    sp.set_defaults(func=cmd_patch)

    sp = _add_parser(sub, "selfcheck",
                      help="确认内置词表可读（用于校验打包产物）",
                      description="读取内置词表并打印前几条，确认打包完整。")
    sp.add_argument("--table", metavar="文件", help="改为检查指定的词表")
    sp.set_defaults(func=cmd_selfcheck)

    sp = _add_parser(sub, "verify", help="独立复核汉化结果",
                     description="重新读取产物，确认改动只落在字符串内部。")
    sp.add_argument("original", help="原始可执行文件")
    sp.add_argument("patched", help="汉化后的可执行文件")
    sp.set_defaults(func=cmd_verify)
    return p


def main(argv: list[str] | None = None) -> int:
    _make_console_safe()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        return _die(f"{exc}")
    except BrokenPipeError:
        # 例如 `mobaxterm-zh patch ... | head` 会提前关闭管道。
        # 必须排在 OSError 之前：BrokenPipeError 是 OSError 的子类。
        return 0
    except OSError as exc:
        return _die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
