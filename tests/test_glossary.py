"""Tests for the editable glossary copy in glossary/.

The repository carries a human-editable copy of the glossary. Two copies means
two places to forget, so a test asserts they stay identical - otherwise an edit
to the readable file would silently have no effect on what ships.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobaxterm_zh import glossary  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
REPO_COPY = REPO / "glossary" / "translations.zh-CN.json"
PKG_COPY = REPO / "src" / "mobaxterm_zh" / "data" / "translations.zh-CN.json"


def test_repo_copy_exists():
    assert REPO_COPY.is_file(), f"missing editable copy: {REPO_COPY}"


def test_copies_are_byte_identical():
    """An edit to the readable copy that never reaches the package directory
    would ship the old glossary, which is exactly the kind of silent drift a
    test should catch."""
    assert REPO_COPY.read_bytes() == PKG_COPY.read_bytes(), (
        "glossary/translations.zh-CN.json and the packaged copy differ.\n"
        "Run:  cp glossary/translations.zh-CN.json "
        "src/mobaxterm_zh/data/"
    )


def test_repo_copy_is_valid_json():
    data = json.loads(REPO_COPY.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert len(data) > 500


def test_every_entry_is_a_string_pair():
    data = json.loads(REPO_COPY.read_text(encoding="utf-8"))
    for k, v in data.items():
        assert isinstance(k, str) and k, "non-string or empty key"
        assert isinstance(v, str), f"value for {k!r} is not a string"
        assert v.strip(), f"empty translation for {k!r}"


def test_entries_are_gbk_encodable():
    """A translation that GBK cannot represent would be silently refused at
    patch time; catching it here keeps the failure visible."""
    data = json.loads(REPO_COPY.read_text(encoding="utf-8"))
    bad = []
    for k, v in data.items():
        try:
            v.encode("gbk")
        except UnicodeEncodeError:
            bad.append(k)
    assert not bad, f"these translations are not GBK-encodable: {bad[:5]}"


def test_glossary_readme_exists():
    assert (REPO / "glossary" / "README.md").is_file()


def test_bundled_loader_returns_the_same_data():
    """The loader used by the app must see exactly what the repo copy says."""
    loaded = glossary.load()
    from_file = json.loads(REPO_COPY.read_text(encoding="utf-8"))
    assert loaded == from_file
