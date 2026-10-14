"""Verify the frozen GUI binary without launching a window.

A console-less PyInstaller build detaches from the shell and opens a window, so
its exit code cannot be read by running it — that would hang the job. This
checks the things that actually break in practice:

  * the file exists and is a real executable of plausible size
  * on Windows it is a PE image, on the others an ELF or Mach-O
  * it is large enough to contain the Tcl/Tk runtime the GUI needs

Usage:  python .github/check_gui_binary.py <path> [runner_os]
"""
from __future__ import annotations

import sys
from pathlib import Path

MAGIC = {
    b"MZ": "Windows PE",
    b"\x7fELF": "Linux ELF",
    b"\xfe\xed\xfa\xce": "macOS Mach-O (32-bit)",
    b"\xce\xfa\xed\xfe": "macOS Mach-O (64-bit)",
    b"\xcf\xfa\xed\xfe": "macOS Mach-O (64-bit, LE)",
    b"\xca\xfe\xba\xbe": "macOS Mach-O universal",
}

MIN_GUI_BYTES = 3_000_000


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    path = Path(sys.argv[1])
    expected_os = sys.argv[2] if len(sys.argv) > 2 else ""

    if not path.is_file():
        print(f"FAIL: GUI binary missing: {path}")
        parent = path.parent
        if parent.is_dir():
            print("  dist contains:")
            for p in sorted(parent.iterdir()):
                print("   ", p.name, p.stat().st_size)
        return 1

    size = path.stat().st_size
    print(f"binary: {path.name}  {size:,} bytes")

    head = path.read_bytes()[:4]
    kind = next((v for k, v in MAGIC.items() if head.startswith(k)), None)
    if kind is None:
        print(f"FAIL: not a recognised executable (magic {head!r})")
        return 1
    print(f"format: {kind}")

    if size < MIN_GUI_BYTES:
        print(f"FAIL: {size:,} bytes is too small for a GUI build - "
              f"the Tcl/Tk runtime is probably missing")
        return 1

    if expected_os == "Windows" and not head.startswith(b"MZ"):
        print(f"FAIL: expected a Windows PE image, got {kind}")
        return 1
    if expected_os == "Linux" and not head.startswith(b"\x7fELF"):
        print(f"FAIL: expected an ELF image, got {kind}")
        return 1
    if expected_os == "macOS" and kind is None:
        print("FAIL: expected a Mach-O image")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
