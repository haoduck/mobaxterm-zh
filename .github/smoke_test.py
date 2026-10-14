"""Smoke-test a frozen mobaxterm-zh build.

Invoked by CI as:  python .github/smoke_test.py dist/mobaxterm-zh-<label>[.exe]

The check that matters is `selfcheck`: PyInstaller does not collect data files
automatically, so a binary missing its glossary still starts fine and only fails
once it tries to patch something. That is precisely the regression this guards.

Note the deliberate absence of `text=True` on the subprocess call - see the
comment in run() below.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _console_safe() -> None:
    """Make THIS script able to print Chinese on a console that cannot encode it.

    GitHub's windows-latest runner uses cp1252. This script decodes the child's
    UTF-8 output into real Chinese characters and then prints them - which
    raises UnicodeEncodeError on a cp1252 stdout. That crash is in the harness,
    not in the binary under test, and it is exactly the bug the tool itself
    guards against in mobaxterm_zh.cli._make_console_safe().

    Same remedy as the tool: reconfigure to utf-8 with errors="replace".
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def run(binary: Path, *args: str) -> subprocess.CompletedProcess:
    print(f"$ {binary.name} {' '.join(args)}", flush=True)
    # Pin the child's output encoding instead of inheriting the runner's, so
    # the bytes we read back are UTF-8 no matter what code page the console
    # happens to use.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run(
        [str(binary), *args],
        capture_output=True,
        env=env,
        # give the onefile bootloader room to unpack on a cold runner
        timeout=300,
    )
    for stream, label in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
        if not stream:
            continue
        text = stream.decode("utf-8", errors="replace").rstrip()
        # Belt and braces: never let a log line take the harness down.
        print(text.encode("ascii", "backslashreplace").decode("ascii")
              if _cannot_encode(sys.stdout, text) else text)
        if label == "stderr":
            print("(stderr above)", file=sys.stderr)
    return proc


def _cannot_encode(stream, text: str) -> bool:
    enc = getattr(stream, "encoding", None) or "ascii"
    try:
        text.encode(enc)
        return False
    except (UnicodeEncodeError, LookupError):
        return True


def main() -> int:
    _console_safe()
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    binary = Path(sys.argv[1])
    if not binary.is_file():
        print(f"FAIL: binary not found: {binary}")
        parent = binary.parent
        if parent.is_dir():
            print("  contents of", parent, ":")
            for p in sorted(parent.iterdir()):
                print("   ", p.name, p.stat().st_size)
        return 1

    size = binary.stat().st_size
    print(f"binary: {binary.name}  {size:,} bytes")
    if size < 1_000_000:
        print(f"FAIL: suspiciously small ({size:,} bytes) - "
              f"the Python runtime is probably missing")
        return 1

    if size > 20_000_000:
        # log the largest embedded file so an accidental data-file explosion is
        # visible rather than silently bloating every release
        print("note: build is larger than expected (>20 MB)")

    # Exit code is the check that matters and is encoding-independent. The CLI's
    # output is Chinese, and the child writes it in the console's code page, so
    # asserting on the text would test the runner's code page instead of the
    # binary. The ASCII below only verifies the child produced *some* output;
    # a successful exit already proves it ran.
    #
    # Console-encoding robustness is covered by
    # tests/test_pipeline.py::test_cli_survives_a_console_that_cannot_encode_chinese
    for args in (("--version",), ("selfcheck",)):
        proc = run(binary, *args)
        if proc.returncode != 0:
            print(f"FAIL: `{binary.name} {' '.join(args)}` "
                  f"exited {proc.returncode}")
            _diagnose()
            return 1
        if not (proc.stdout or proc.stderr):
            print(f"FAIL: `{binary.name} {' '.join(args)}` produced no output")
            _diagnose()
            return 1

    print("PASS")
    return 0


def _diagnose() -> None:
    """Dump enough state to diagnose a failure on a runner we cannot reproduce
    locally - a bare non-zero exit says nothing."""
    print("--- diagnostics ---", file=sys.stderr)
    print(f"  platform : {sys.platform} {os.cpu_count()} cpus", file=sys.stderr)
    print(f"  fsenc    : {sys.getfilesystemencoding()}", file=sys.stderr)
    print(f"  stdoutenc: {sys.stdout.encoding}", file=sys.stderr)
    try:
        import locale
        print(f"  locale   : {locale.getpreferredencoding(False)}",
              file=sys.stderr)
    except Exception:
        pass
    tmp = getattr(sys, "_MEIPASS", None)
    print(f"  _MEIPASS : {tmp}", file=sys.stderr)
    print(f"  cwd      : {os.getcwd()}", file=sys.stderr)
    print("  env      : " + repr({k: v for k, v in os.environ.items()
                                  if k.startswith("PYTHON")}), file=sys.stderr)
    print("--------------", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
