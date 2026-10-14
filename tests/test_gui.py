"""Tests for the shared pipeline and the GUI layer.

The GUI is exercised headlessly: tkinter widgets are constructed in a real Tk
root when one can be created, and skipped when the environment has no display
(CI runners without X, or a locked-down Windows session).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import ansi_const, dfm_form, dfm_short, make_pe  # noqa: E402
from mobaxterm_zh import pipeline  # noqa: E402

GLOSSARY = {"Sessions": "会话", "Cancel": "取消", "Settings": "设置"}


def _write_exe(tmp_path: Path, name: str = "MobaXterm_26.5.exe") -> Path:
    blob = (
        dfm_form("TFormDemo", "FormDemo")
        + dfm_short("Caption", "Sessions")
        + dfm_short("Caption", "Settings")
    )
    code = ansi_const("Cancel")
    exe = tmp_path / name
    exe.write_bytes(make_pe(resource_blob=blob, code_blob=code))
    return exe


@pytest.fixture
def glossary_file(tmp_path: Path) -> str:
    import json
    p = tmp_path / "t.json"
    p.write_text(json.dumps(GLOSSARY, ensure_ascii=False), encoding="utf-8")
    return str(p)


# ------------------------------------------------------------- pipeline
def test_run_patch_produces_a_verified_file(tmp_path, glossary_file):
    src = _write_exe(tmp_path)
    out = tmp_path / "out.exe"
    r = pipeline.run_patch(src, out, table_path=glossary_file)
    assert r.ok
    assert out.is_file()
    assert out.stat().st_size == src.stat().st_size
    assert r.verification is not None and r.verification.ok
    assert r.translated == 3


def test_default_output_path(tmp_path):
    src = tmp_path / "MobaXterm_Personal_26.5.exe"
    out = pipeline.default_output_path(src)
    assert out.name == "MobaXterm_Personal_26.5_zh.exe"


def test_run_patch_dry_run_writes_nothing(tmp_path, glossary_file):
    src = _write_exe(tmp_path)
    out = tmp_path / "out.exe"
    r = pipeline.run_patch(src, out, table_path=glossary_file, dry_run=True)
    assert r.ok
    assert not out.exists()
    assert r.output_path is None
    assert r.translated == 3


def test_run_patch_reports_missing_source(tmp_path, glossary_file):
    r = pipeline.run_patch(tmp_path / "nope.exe", table_path=glossary_file)
    assert not r.ok
    assert "无法读取" in r.message


def test_run_patch_rejects_a_non_pe(tmp_path, glossary_file):
    bad = tmp_path / "notes.txt"
    bad.write_bytes(b"this is not an executable at all")
    r = pipeline.run_patch(bad, table_path=glossary_file)
    assert not r.ok
    assert "可执行文件" in r.message


def test_run_patch_reports_missing_glossary(tmp_path):
    src = _write_exe(tmp_path)
    r = pipeline.run_patch(src, table_path=str(tmp_path / "absent.json"))
    assert not r.ok
    assert "词表" in r.message


def test_report_lines_are_chinese(tmp_path, glossary_file):
    src = _write_exe(tmp_path)
    r = pipeline.run_patch(src, tmp_path / "o.exe", table_path=glossary_file)
    text = "\n".join(r.report_lines())
    for marker in ("源文件", "检出字符串", "已写入译文", "改动字节数"):
        assert marker in text


def test_patch_output_is_byte_exact(tmp_path, glossary_file):
    """Patching must not move anything: same length, only string bytes differ."""
    src = _write_exe(tmp_path)
    before = src.read_bytes()
    out = tmp_path / "out.exe"
    pipeline.run_patch(src, out, table_path=glossary_file)
    after = out.read_bytes()
    assert len(before) == len(after)
    diff = [i for i in range(len(before)) if before[i] != after[i]]
    assert diff, "expected the glossary to change something"
    # every changed byte must sit inside a string payload, which verify asserts
    assert pipeline.verify(before, after, pipeline.extract(before)).ok


# ------------------------------------------------------------------ gui
def _tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        return tk.Tk()
    except Exception as exc:            # no display / no session
        pytest.skip(f"no display available: {exc}")


def test_gui_module_imports_without_a_display():
    from mobaxterm_zh import gui
    assert hasattr(gui, "App")
    assert callable(gui.main)


def test_gui_dnd_flag_is_boolean():
    from mobaxterm_zh import gui
    assert isinstance(gui._HAVE_DND, bool)


def test_gui_builds_and_shows_default_output(tmp_path):
    root = _tk_root()
    try:
        from mobaxterm_zh import gui
        src = tmp_path / "MobaXterm_Personal_26.5.exe"
        src.write_bytes(b"x")
        app = gui.App(root, str(src))
        root.update_idletasks()
        assert app.src_var.get() == str(src)
        # picking a source fills in the output path automatically
        app.out_var.set("")
        app._set_source(str(src))
        assert app.out_var.get().endswith("_zh.exe")
    finally:
        root.destroy()


def test_gui_set_source_fills_output(tmp_path):
    root = _tk_root()
    try:
        from mobaxterm_zh import gui
        app = gui.App(root, None)
        src = tmp_path / "MobaXterm_26.5.exe"
        src.write_bytes(b"x")
        app.out_var.set("")
        app._set_source(str(src))
        assert app.out_var.get().endswith("_zh.exe")
    finally:
        root.destroy()


def test_gui_worker_reports_result(tmp_path, glossary_file, monkeypatch):
    root = _tk_root()
    try:
        from mobaxterm_zh import gui
        # A modal messagebox would block forever with no one to click it.
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
        monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
        monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
        monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)

        app = gui.App(root, None)
        src = _write_exe(tmp_path)
        out = tmp_path / "gui_out.exe"
        app.dry.set(False)
        app.src_var.set(str(src))
        app.out_var.set(str(out))
        app._start()

        import time
        deadline = time.time() + 60
        while app._busy and time.time() < deadline:
            root.update()
            time.sleep(0.02)
        root.update()

        assert not app._busy, "worker never finished"
        assert out.is_file()
        assert out.stat().st_size == src.stat().st_size
    finally:
        root.destroy()


def test_gui_cli_subcommand_is_registered():
    from mobaxterm_zh import cli
    parser = cli.build_parser()
    actions = parser._subparsers._group_actions
    names = set(actions[0].choices)
    assert "gui" in names
    assert "patch" in names
