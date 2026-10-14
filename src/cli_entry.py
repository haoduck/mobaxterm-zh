"""Entry point for PyInstaller.

PyInstaller executes this file as top-level ``__main__``, where relative
imports have no parent package. Importing the CLI absolutely here keeps
``cli.py`` importable both as a module and as the frozen entry script.
"""
from mobaxterm_zh.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
