# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for mobaxterm-zh.

Produces two binaries from one spec: a console CLI and a windowed GUI.

Paths are resolved from the spec's own location so the build works from any
working directory.

tkinter is deliberately NOT excluded - the GUI needs it, and it ships with
Python, so it costs no extra dependency. Its Tcl/Tk data files are collected by
PyInstaller's built-in hook.

The glossary is a data file and must be listed explicitly; PyInstaller does not
collect package data on its own. mobaxterm_zh/glossary.py looks for it in
sys._MEIPASS, which is where a one-file build unpacks - both sides agree.
"""
import os
from pathlib import Path

SPEC_DIR = Path(os.path.abspath(SPECPATH))
SRC = SPEC_DIR / "src"
GLOSSARY = SRC / "mobaxterm_zh" / "data" / "translations.zh-CN.json"
CLI_ENTRY = SRC / "cli_entry.py"
GUI_ENTRY = SRC / "gui_entry.py"

for required in (CLI_ENTRY, GUI_ENTRY, GLOSSARY):
    if not required.is_file():
        raise SystemExit(
            f"mobaxterm-zh.spec: required file missing: {required}\n"
            f"  expected repo layout: <repo>/src/cli_entry.py, "
            f"<repo>/src/gui_entry.py and "
            f"<repo>/src/mobaxterm_zh/data/translations.zh-CN.json"
        )

DATAS = [(str(GLOSSARY), "mobaxterm_zh/data")]
EXCLUDES = ["unittest", "pydoc_data", "test", "lib2to3", "distutils"]

# ---- command-line build ------------------------------------------------
cli_a = Analysis(
    [str(CLI_ENTRY)],
    pathex=[str(SRC)],
    binaries=[],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES + ["tkinter", "tkinter.ttk", "tkinter.filedialog",
                         "tkinter.messagebox", "tkinter.scrolledtext"],
    noarchive=False,
)
cli_pyz = PYZ(cli_a.pure)
cli_exe = EXE(
    cli_pyz, cli_a.scripts, cli_a.binaries, cli_a.datas, [],
    name="mobaxterm-zh",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    upx_exclude=[], runtime_tmpdir=None,
    console=True, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)

# ---- windowed build ---------------------------------------------------
gui_a = Analysis(
    [str(GUI_ENTRY)],
    pathex=[str(SRC)],
    binaries=[],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # tkinter stays IN here: the GUI is built on it, and shipping the Tcl/Tk
    # runtime only adds to the download size, not to the dependency set.
    excludes=EXCLUDES,
    noarchive=False,
)
gui_pyz = PYZ(gui_a.pure)
gui_exe = EXE(
    gui_pyz, gui_a.scripts, gui_a.binaries, gui_a.datas, [],
    name="mobaxterm-zh-gui",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    upx_exclude=[], runtime_tmpdir=None,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
