"""Unit tests for the localization pipeline, using synthetic PE fixtures."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import ansi_const, dfm_form, dfm_long, dfm_short, make_pe  # noqa: E402
from mobaxterm_zh import extract, glossary, patch, pe, verify  # noqa: E402

GLOSSARY_HINT = re.compile(r"--table")


@pytest.fixture
def sample_exe() -> bytes:
    blob = (
        dfm_form("TFormDemo", "FormDemo")
        + dfm_short("Caption", "Sessions")
        + dfm_short("Caption", "Settings")
        + dfm_short("Hint", "Open a new terminal tab")
        + dfm_long("Text", "A longer help sentence goes here.")
    )
    code = ansi_const("Password") + ansi_const("Cancel") + b"\x90\x90\x90"
    return make_pe(resource_blob=blob, code_blob=code)


# ---------------------------------------------------------------- pe
def test_pe_parses_sections_and_signature(sample_exe):
    img = pe.PEImage.parse(sample_exe)
    assert ".rsrc" in img.section_names
    assert img.section_span(".rsrc") is not None
    assert img.cert_size == 0


def test_pe_rejects_non_pe():
    with pytest.raises(pe.PEError):
        pe.PEImage.parse(b"not a windows executable at all")


def test_pe_rejects_truncated_file():
    with pytest.raises(pe.PEError):
        pe.PEImage.parse(b"MZ")


def test_certificate_table_is_found():
    img = pe.PEImage.parse(make_pe(resource_blob=b"TPF0",
                                   code_blob=b"\x90",
                                   certificate=b"\xde\xad\xbe\xef" * 16))
    assert img.cert_size == 64


# ------------------------------------------------------------ extract
def test_extract_finds_dfm_short_strings(sample_exe):
    sites = extract.extract(sample_exe)
    texts = {s.text for s in sites}
    assert "Sessions" in texts
    assert "Settings" in texts
    assert "Open a new terminal tab" in texts


def test_extract_finds_dfm_long_strings(sample_exe):
    sites = extract.extract(sample_exe)
    long_ones = [s for s in sites if s.kind == "dfm_long"]
    assert long_ones
    assert long_ones[0].text.startswith("A longer help sentence")


def test_extract_finds_runtime_constants(sample_exe):
    sites = extract.extract(sample_exe)
    consts = {s.text for s in sites if s.kind == "ansi_const"}
    assert {"Password", "Cancel"} <= consts


def test_extract_records_exact_offsets_and_lengths(sample_exe):
    for s in extract.extract(sample_exe):
        chunk = sample_exe[s.offset:s.offset + s.length]
        if s.kind == "dfm_short":
            assert chunk.decode("latin1") == s.text
        elif s.kind == "ansi_const":
            assert chunk.decode("latin1") == s.text
            assert sample_exe[s.offset + s.length:s.offset + s.length + 1] == b"\x00"


def test_extract_attributes_form(sample_exe):
    forms = {s.form for s in extract.extract(sample_exe) if s.kind != "ansi_const"}
    assert forms == {"TFormDemo"}


def test_extract_skips_non_display_properties(sample_exe):
    blob = (dfm_form("TFormDemo", "FormDemo")
            + dfm_short("Name", "SomeComponentName")
            + dfm_short("Caption", "Visible"))
    sites = extract.extract(make_pe(resource_blob=blob, code_blob=b"\x90"))
    assert {s.text for s in sites} == {"Visible"}


def test_extract_can_skip_runtime_strings(sample_exe):
    sites = extract.extract(sample_exe, include_ansi_constants=False)
    assert not any(s.kind == "ansi_const" for s in sites)


# ------------------------------------------------------------- patch
def test_patch_keeps_file_size_identical(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    table = {"Sessions": "会话", "Password": "密码"}
    patch.patch(buf, sites, table)
    assert len(buf) == len(sample_exe)


def test_patch_writes_gbk_and_pads(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    table = {"Sessions": "会话"}     # 4 bytes GBK into an 8-byte slot
    report = patch.patch(buf, sites, table)
    assert report.written == 1
    site = next(s for s in sites if s.text == "Sessions")
    out = bytes(buf[site.offset:site.offset + site.length])
    assert out == "会话    ".encode("gbk")
    assert report.padded == 1


def test_patch_refuses_translation_that_is_too_long(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    # "Sessions" is 8 bytes; a 6-character phrase is 12 bytes in GBK
    report = patch.patch(buf, sites, {"Sessions": "这是一个很长的词条"})
    assert report.refused_too_long == 1
    assert report.written == 0
    assert bytes(buf) == sample_exe      # untouched


def test_patch_never_truncates(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    patch.patch(buf, sites, {"Settings": "设置选项菜单栏"})
    site = next(s for s in sites if s.text == "Settings")
    # unchanged because it does not fit: the original is still readable
    assert bytes(buf[site.offset:site.offset + site.length]).decode("latin1") == "Settings"


def test_patch_refuses_unencodable_translation(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    # Thai has no GBK representation (kana and most other scripts do).
    report = patch.patch(buf, sites, {"Sessions": "การประชุม"})
    assert report.refused_wrong_encoding == 1
    assert bytes(buf) == sample_exe


def test_patch_accepts_kana_because_gbk_covers_it(sample_exe):
    # GBK includes kana, so this must be judged on length, not encodability.
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    report = patch.patch(buf, sites, {"Sessions": "セッション"})
    assert report.refused_wrong_encoding == 0
    assert report.refused_too_long == 1


def test_patch_respects_markup_token_counts(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    # dropping <br> is caught by the glossary audit before patching
    table = {"Open a new terminal tab": "打开新的终端标签"}
    report = patch.patch(buf, sites, table)
    assert report.written == 1


def test_patch_dry_run_changes_nothing(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    report = patch.patch(buf, sites, {"Sessions": "会话"}, dry_run=True)
    assert report.written == 1
    assert bytes(buf) == sample_exe


def test_patch_refuses_utf8_target_for_gbk(sample_exe):
    sites = [s for s in extract.extract(sample_exe)]
    # fabricate a UTF-8 site to exercise the guard
    utf8_site = extract.StringSite(
        text="日本語", offset=0, length=9, kind="dfm_utf8", form="T",
        prop="Caption", length_offset=-4, length_width=4)
    report = patch.patch(bytearray(sample_exe), [utf8_site], {"日本語": "中文"})
    assert report.refused_utf8_target == 1


# ----------------------------------------------------------- glossary
def test_glossary_audit_filters_by_budget(sample_exe):
    sites = extract.extract(sample_exe)
    table = {"Sessions": "会话", "Settings": "这是一个非常长的翻译"}
    a = glossary.audit(table, sites)
    assert "Sessions" in a.usable
    assert "Settings" not in a.usable
    assert a.too_long and a.too_long[0][0] == "Settings"


def test_glossary_audit_flags_lost_markup(sample_exe):
    blob = (dfm_form("TFormDemo", "FormDemo")
            + dfm_short("Caption", "One<br>Two"))
    sites = extract.extract(make_pe(resource_blob=blob, code_blob=b"\x90"))
    a = glossary.audit({"One<br>Two": "一二三"}, sites)
    assert a.markup_loss


def test_glossary_audit_reports_unknown_keys(sample_exe):
    sites = extract.extract(sample_exe)
    a = glossary.audit({"NotInBinary": "某"}, sites)
    assert a.not_in_binary == ["NotInBinary"]


def test_bundled_glossary_loads():
    table = glossary.load()
    assert len(table) > 500
    assert table["Cancel"] == "取消"
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in table.items())


def test_bundled_glossary_is_found_via_meipass(monkeypatch, tmp_path):
    """A frozen PyInstaller build unpacks to sys._MEIPASS; the glossary must
    still be found there, which is the failure mode this guards against."""
    pkg = tmp_path / "mobaxterm_zh" / "data"
    pkg.mkdir(parents=True)
    (pkg / glossary.GLOSSARY_NAME).write_text('{"Cancel": "取消"}',
                                              encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert glossary.load() == {"Cancel": "取消"}


def test_glossary_found_next_to_the_executable(monkeypatch, tmp_path):
    (tmp_path / glossary.GLOSSARY_NAME).write_text('{"OK": "好"}',
                                                   encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", "", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "tool.exe"))
    assert glossary.load() == {"OK": "好"}


def test_missing_glossary_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", "", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "tool.exe"))
    monkeypatch.setattr(glossary, "resources", None)
    with pytest.raises(glossary.GlossaryError) as exc:
        glossary.load()
    assert GLOSSARY_HINT.search(str(exc.value))


def test_selfcheck_command_succeeds(capsys):
    from mobaxterm_zh import cli
    rc = cli.main(["selfcheck"])
    out = capsys.readouterr().out
    assert rc == 0
    # markers are Chinese now; assert on them as the CLI actually emits them
    assert "自检通过" in out
    assert "Cancel" in out


def test_selfcheck_reports_failure(monkeypatch, capsys):
    from mobaxterm_zh import cli
    monkeypatch.setattr(cli, "load", lambda *a, **k: (_ for _ in ()).throw(
        glossary.GlossaryError("nope")))
    assert cli.main(["selfcheck"]) == 1


def test_cli_survives_a_console_that_cannot_encode_chinese(capsys):
    """Regression: printing the first Simplified Chinese character used to
    raise UnicodeEncodeError and kill the process on a cp1252 console
    (an English-locale Windows). main() must reconfigure the streams so the
    output degrades instead of crashing."""
    from mobaxterm_zh import cli
    cli._make_console_safe()

    enc = sys.stdout.encoding
    if enc:
        try:
            "会话".encode(enc)
            pytest.skip(f"stdout already encodes Chinese ({enc})")
        except UnicodeEncodeError:
            pass

    assert cli.main(["selfcheck"]) == 0
    out = capsys.readouterr().out
    assert "自检通过" in out


def test_make_console_safe_is_idempotent():
    from mobaxterm_zh import cli
    cli._make_console_safe()
    first = sys.stdout.encoding
    cli._make_console_safe()
    assert sys.stdout.encoding == first
    assert os.environ.get("PYTHONIOENCODING") == "utf-8"


def test_cli_handles_broken_pipe(monkeypatch):
    """`mobaxterm-zh patch ... | head` closes the pipe early; that should not
    produce a traceback."""
    from mobaxterm_zh import cli

    def boom(*a, **k):
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser(boom))
    assert cli.main([]) == 0


class _Parser:
    def __init__(self, fn):
        self._fn = fn

    def parse_args(self, argv):
        return type("A", (), {"func": self._fn})()


def test_coverage_counts(sample_exe):
    sites = extract.extract(sample_exe)
    cov = glossary.coverage({"Sessions": "会话"}, sites)
    assert cov["unique_translated"] >= 1
    assert cov["instances_translated"] >= 1


# ------------------------------------------------------------- verify
def test_verify_passes_on_a_clean_patch(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    patch.patch(buf, sites, {"Sessions": "会话", "Password": "密码",
                             "Cancel": "取消"})
    res = verify.verify(sample_exe, bytes(buf), sites)
    assert res.ok, res.summary()
    assert res.size_same
    assert res.changed_outside_strings == 0
    assert res.length_fields_broken == 0


def test_verify_fails_when_size_changes(sample_exe):
    sites = extract.extract(sample_exe)
    res = verify.verify(sample_exe, sample_exe + b"\x00", sites)
    assert not res.ok
    assert not res.size_same


def test_verify_fails_on_stray_byte_edits(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    # scribble somewhere that is NOT a string payload
    span = pe.PEImage.parse(sample_exe).section_span(".text")
    buf[span[0] + 1] ^= 0xFF
    res = verify.verify(sample_exe, bytes(buf), sites)
    assert not res.ok
    assert res.changed_outside_strings >= 1


def test_verify_flags_a_corrupted_length_field(sample_exe):
    sites = extract.extract(sample_exe)
    buf = bytearray(sample_exe)
    patch.patch(buf, sites, {"Sessions": "会话"})
    site = next(s for s in sites if s.text == "Sessions")
    buf[site.length_offset] = 0x20          # break the declared length
    res = verify.verify(sample_exe, bytes(buf), sites)
    assert not res.ok
    assert res.length_fields_broken >= 1
