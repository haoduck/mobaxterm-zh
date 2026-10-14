"""图形界面：选择（或拖入）MobaXterm 可执行文件，执行汉化。

用 tkinter，因为它属于 Python 标准库：不需要新增依赖，Windows / Linux /
macOS 上都能运行，打包体积几乎不变。

拖放支持依赖可选的 ``tkinterdnd2``。没有装时界面照常工作，只是不能拖拽；
程序不会因为缺少它而出错。

界面上的处理逻辑不重复实现，直接调用 :mod:`mobaxterm_zh.pipeline`，与
命令行走同一条路径。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from . import __version__
from .pipeline import DEFAULT_ENCODING, default_output_path, run_patch

# 拖放是可选能力：装了 tkinterdnd2 才有，没装则退化为只能点「浏览」。
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAVE_DND = True
except ImportError:                       # pragma: no cover - 取决于环境
    TkinterDnD = tk.Tk                   # type: ignore[assignment]
    DND_FILES = None                      # type: ignore[assignment]
    _HAVE_DND = False


EXE_FILTER = [("MobaXterm 可执行文件", "*.exe"), ("所有文件", "*.*")]


class App:
    def __init__(self, root: tk.Misc, initial: str | None = None):
        self.root = root
        self.root.title(f"MobaXterm 汉化工具 v{__version__}")
        self.root.minsize(760, 540)
        self._events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._busy = False

        self._build(initial)
        self.root.after(80, self._pump)

    # ---------------------------------------------------------------- UI
    def _build(self, initial: str | None) -> None:
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self.root, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(6, weight=1)

        ttk.Label(frm, text="MobaXterm 汉化工具",
                  font=("Microsoft YaHei UI", 15, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))
        ttk.Label(
            frm,
            text="选择官方原版 MobaXterm 可执行文件，生成同尺寸的中文版本。"
                 + ("可直接把文件拖到窗口里。" if _HAVE_DND else ""),
            foreground="#555",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))

        # --- source file
        ttk.Label(frm, text="源文件：").grid(row=2, column=0, sticky="w", **pad)
        self.src_var = tk.StringVar(value=initial or "")
        self.src_entry = ttk.Entry(frm, textvariable=self.src_var)
        self.src_entry.grid(row=2, column=1, sticky="ew", **pad)
        self.src_entry.bind("<Return>", lambda _e: self._browse())
        ttk.Button(frm, text="浏览…", width=10,
                   command=self._browse).grid(row=2, column=2, **pad)

        # --- output file
        ttk.Label(frm, text="输出到：").grid(row=3, column=0, sticky="w", **pad)
        self.out_var = tk.StringVar(value="")
        self.out_entry = ttk.Entry(frm, textvariable=self.out_var)
        self.out_entry.grid(row=3, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="另存为…", width=10,
                   command=self._browse_out).grid(row=3, column=2, **pad)

        # --- advanced (collapsed into a row so the simple path stays obvious)
        adv = ttk.Frame(frm)
        adv.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        ttk.Label(adv, text="自定义词表（留空用内置）：").pack(side="left")
        self.table_var = tk.StringVar()
        self.table_entry = ttk.Entry(adv, textvariable=self.table_var, width=26)
        self.table_entry.pack(side="left")
        self.table_entry.bind("<KeyRelease>", lambda _e: self._refresh_table_hint())
        self.table_entry.bind("<FocusOut>", lambda _e: self._refresh_table_hint())
        ttk.Button(adv, text="选择…", width=8,
                   command=self._browse_table).pack(side="left", padx=4)

        ttk.Label(adv, text="编码：").pack(side="left", padx=(12, 0))
        self.enc_var = tk.StringVar(value=DEFAULT_ENCODING)
        ttk.Combobox(adv, textvariable=self.enc_var, width=8,
                     values=("gbk", "utf-8")).pack(side="left")

        # Make the default explicit - an empty field here is not "missing data",
        # it means "use the glossary that ships inside this program".
        self.table_hint = ttk.Label(
            frm,
            text="留空即使用内置词表（简体中文，1,279 条，已打包在本程序中）。"
                 "只有想自定义译文时才需要指定自己的 JSON 文件。",
            foreground="#777", wraplength=680, justify="left",
        )
        self.table_hint.grid(row=5, column=0, columnspan=3, sticky="w",
                             padx=10, pady=(0, 4))

        # --- log
        ttk.Label(frm, text="运行日志：").grid(row=6, column=0,
                                             sticky="nw", **pad)
        self.log = scrolledtext.ScrolledText(
            frm, wrap="none", height=18, font=("Consolas", 10),
            state="disabled")
        self.log.grid(row=6, column=1, columnspan=2, sticky="nsew", **pad)
        self.log.tag_configure("ok", foreground="#137333")
        self.log.tag_configure("bad", foreground="#b00020")
        self.log.tag_configure("dim", foreground="#666")

        # --- actions
        bar = ttk.Frame(frm)
        bar.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        self.dry = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="试运行（只报告，不写文件）",
                        variable=self.dry).pack(side="left")

        self.run_btn = ttk.Button(bar, text="开始汉化",
                                  command=self._start)
        self.run_btn.pack(side="right")
        ttk.Button(bar, text="打开输出目录",
                   command=self._open_dir).pack(side="right", padx=6)

        self.status = ttk.Label(bar, text="就绪", foreground="#555")
        self.status.pack(side="left", padx=12)

        if _HAVE_DND:
            for w in (frm, self.log, self.src_entry):
                try:
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:
                    pass

        self._say("请选择 MobaXterm 可执行文件后点击「开始汉化」。", "dim")

    # ------------------------------------------------------------ events
    def _say(self, text: str, tag: str = "") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_drop(self, event) -> None:
        """把拖进来的文件当作源文件。"""
        try:
            data = event.data
            paths = self.root.tk.splitlist(data)
        except Exception:
            return
        for p in paths:
            if p.lower().endswith(".exe"):
                self._set_source(p)
                self._say(f"已拖入：{p}", "dim")
                return
        if paths:
            self._say("拖入的不是 .exe 文件，已忽略。", "bad")

    def _set_source(self, path: str) -> None:
        self.src_var.set(path)
        if not self.out_var.get().strip():
            self.out_var.set(str(default_output_path(Path(path))))

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 MobaXterm 可执行文件", filetypes=EXE_FILTER)
        if path:
            self._set_source(path)

    def _browse_out(self) -> None:
        cur = self.out_var.get().strip() or self.src_var.get().strip()
        init = os.path.dirname(cur) if cur else os.getcwd()
        path = filedialog.asksaveasfilename(
            title="保存汉化后的文件", defaultextension=".exe", initialdir=init,
            initialfile=os.path.basename(cur) or "MobaXterm_zh.exe",
            filetypes=EXE_FILTER)
        if path:
            self.out_var.set(path)

    def _browse_table(self) -> None:
        path = filedialog.askopenfilename(
            title="选择词表文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if path:
            self.table_var.set(path)
            self._refresh_table_hint()

    def _refresh_table_hint(self) -> None:
        """提示文字要跟着「是否选了自定义词表」变，避免用户误以为留空是缺点。"""
        custom = self.table_var.get().strip()
        if custom:
            self.table_hint.configure(
                text=f"将使用自定义词表：{os.path.basename(custom)}"
                     f"（内置词表不再使用）",
                foreground="#8a5a00")
        else:
            self.table_hint.configure(
                text="留空即使用内置词表（简体中文，1,279 条，已打包在本程序中）。"
                     "只有想自定义译文时才需要指定自己的 JSON 文件。",
                foreground="#777")

    def _open_dir(self) -> None:
        target = self.out_var.get().strip() or self.src_var.get().strip()
        if not target:
            messagebox.showinfo("提示", "还没有可打开的路径。")
            return
        d = os.path.dirname(target)
        if not d:
            messagebox.showwarning("提示", "路径不完整，无法定位目录。")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)                      # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc))

    # -------------------------------------------------------------- work
    def _start(self) -> None:
        if self._busy:
            return
        src = self.src_var.get().strip()
        if not src:
            messagebox.showwarning("提示", "请先选择 MobaXterm 可执行文件。")
            return
        if not Path(src).is_file():
            messagebox.showerror("找不到文件", f"文件不存在：\n{src}")
            return

        out = self.out_var.get().strip()
        if not out:
            out = str(default_output_path(Path(src)))
            self.out_var.set(out)
        if not self.dry.get() and Path(out).exists():
            if not messagebox.askyesno(
                    "文件已存在", f"目标文件已存在，是否覆盖？\n\n{out}"):
                return

        self._busy = True
        self.run_btn.configure(state="disabled")
        self.status.configure(text="处理中…")
        self._say("—" * 52)
        self._say(f"开始处理：{src}")

        # Read every widget value HERE, on the main thread, and hand the worker
        # plain strings. Touching a tkinter variable from the worker thread is
        # not safe - it raises "main thread is not in main loop" - and would
        # crash the run for real users whenever the checkbox was consulted.
        dry = bool(self.dry.get())
        table = self.table_var.get().strip() or None
        encoding = self.enc_var.get().strip() or DEFAULT_ENCODING

        # Say which glossary is actually in force - the field being empty is a
        # valid choice, not a missing value.
        self._say("词表    ：" + (f"自定义 {table}" if table else "内置词表"))

        thread = threading.Thread(
            target=self._worker, args=(src, out, dry, table, encoding),
            daemon=True)
        thread.start()

    def _worker(self, src: str, out: str, dry: bool,
                table: str | None, encoding: str) -> None:
        # 后台线程：处理 16 MB 二进制要几秒，冻住界面就没法用了。
        try:
            outcome = run_patch(
                Path(src), Path(out) if not dry else None,
                table_path=table, encoding=encoding, dry_run=dry)
            for line in outcome.report_lines():
                self._events.put(("line", line))
            self._events.put(("done", (outcome, dry)))
        except Exception as exc:                       # pragma: no cover
            self._events.put(("line", f"内部错误：{exc}"))
            self._events.put(("line", traceback.format_exc()))
            self._events.put(("done", (None, dry)))

    def _pump(self) -> None:
        """把后台线程的结果搬回界面线程（tkinter 非线程安全）。"""
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "line":
                    self._say(str(payload))
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _finish(self, result) -> None:
        self._busy = False
        self.run_btn.configure(state="normal")
        if result is None:
            self.status.configure(text="失败")
            return
        outcome, dry = result
        if outcome is None:
            self.status.configure(text="失败")
            return
        if dry:
            self.status.configure(text="试运行完成")
            self._say("试运行结束，未写入任何文件。", "dim")
            return
        if outcome.ok:
            self.status.configure(text="完成")
            self._say("汉化完成。", "ok")
            messagebox.showinfo("完成", f"已生成：\n{outcome.output_path}")
        else:
            self.status.configure(text="校验未通过")
            self._say("校验未通过，请勿使用该文件。", "bad")
            messagebox.showerror(
                "校验未通过",
                "产物未通过完整性校验，请勿使用。\n详情见运行日志。")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    initial = argv[0] if argv else None

    try:
        root = TkinterDnD.Tk() if _HAVE_DND else tk.Tk()
    except tk.TclError as exc:
        # 没有图形环境（例如纯 SSH 会话里）
        print(f"错误：无法启动图形界面（{exc}）。"
              f"请改用命令行：mobaxterm-zh patch <文件>", file=sys.stderr)
        return 3

    App(root, initial)

    # 拖放库会在首次 import 时加载 Tcl 扩展，放进窗口之后可以安全初始化
    try:
        root.tk.eval("::tk::FileEvent::Configure 1")  # noqa: S307
    except tk.TclError:
        pass

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
