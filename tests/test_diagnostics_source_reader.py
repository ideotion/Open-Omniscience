"""The diagnostics reader behaves the same before and after the J1 package split.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The reader is the first commit of the split (see ``tests/diagnostics_source.py``), and
its whole value is a property no assertion in the rest of the suite can check for
itself: that the day ``src/api/diagnostics.py`` becomes ``src/api/diagnostics/``, every
site reading it keeps seeing the SAME text and no negative assertion quietly becomes a
tautology. So the package future is exercised here, against synthetic roots, today --
years before the split lands if need be.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.diagnostics_source import diagnostics_parts, diagnostics_source

_REAL = Path(__file__).resolve().parent.parent


def _api(root: Path) -> Path:
    d = root / "src" / "api"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- today: a single module ---------------------------------------------------- #


def test_the_real_tree_reads_byte_identically_to_the_file_it_replaces():
    """Migrating a call site to the reader must be a verifiable no-op right now."""
    assert diagnostics_source() == (
        _REAL / "src" / "api" / "diagnostics.py"
    ).read_text(encoding="utf-8")


def test_the_real_tree_reports_one_part_named_for_the_module():
    assert [n for n, _ in diagnostics_parts()] == ["diagnostics.py"]


# --- tomorrow: a package -------------------------------------------------------- #


def test_a_package_is_concatenated_in_the_order_its_init_imports(tmp_path):
    pkg = _api(tmp_path) / "diagnostics"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "from .routes_b import b\nfrom .routes_a import a\n", encoding="utf-8"
    )
    (pkg / "routes_a.py").write_text("A\n", encoding="utf-8")
    (pkg / "routes_b.py").write_text("B\n", encoding="utf-8")
    assert [n for n, _ in diagnostics_parts(tmp_path)] == [
        "__init__.py", "routes_b.py", "routes_a.py"
    ], "the order must come from the package's own import lines, not from sorting"
    assert diagnostics_source(tmp_path).endswith("B\nA\n")


def test_the_from_dot_import_shape_is_read_too(tmp_path):
    pkg = _api(tmp_path) / "diagnostics"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from . import second, first\n", encoding="utf-8")
    (pkg / "first.py").write_text("F\n", encoding="utf-8")
    (pkg / "second.py").write_text("S\n", encoding="utf-8")
    assert [n for n, _ in diagnostics_parts(tmp_path)] == [
        "__init__.py", "second.py", "first.py"
    ]


def test_an_unimported_module_still_contributes_its_text(tmp_path):
    """The safety property: a forgotten import must not silently shrink the source.

    If it did, every ``assert X not in source`` covering that module would pass for
    free -- the exact vacuity the app.js split produced at 151 sites.
    """
    pkg = _api(tmp_path) / "diagnostics"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .known import k\n", encoding="utf-8")
    (pkg / "known.py").write_text("KNOWN\n", encoding="utf-8")
    (pkg / "orphan.py").write_text("ORPHAN\n", encoding="utf-8")
    src = diagnostics_source(tmp_path)
    assert "ORPHAN" in src
    assert [n for n, _ in diagnostics_parts(tmp_path)] == [
        "__init__.py", "known.py", "orphan.py"
    ]


def test_a_package_without_an_init_is_still_read_whole(tmp_path):
    pkg = _api(tmp_path) / "diagnostics"
    pkg.mkdir()
    (pkg / "b.py").write_text("B\n", encoding="utf-8")
    (pkg / "a.py").write_text("A\n", encoding="utf-8")
    assert [n for n, _ in diagnostics_parts(tmp_path)] == ["a.py", "b.py"]
    assert diagnostics_source(tmp_path) == "A\nB\n"


def test_files_are_joined_byte_exactly_without_inserting_separators(tmp_path):
    """A joiner that adds a newline shifts every offset a caller computes."""
    pkg = _api(tmp_path) / "diagnostics"
    pkg.mkdir()
    (pkg / "a.py").write_text("first", encoding="utf-8")   # deliberately no newline
    (pkg / "b.py").write_text("second", encoding="utf-8")
    assert diagnostics_source(tmp_path) == "firstsecond"


def test_a_module_beside_a_package_wins_so_a_stale_directory_cannot_shadow_it(tmp_path):
    """Mid-migration both may exist; the importable module is what the app runs."""
    api = _api(tmp_path)
    (api / "diagnostics.py").write_text("MODULE\n", encoding="utf-8")
    pkg = api / "diagnostics"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("PACKAGE\n", encoding="utf-8")
    assert diagnostics_source(tmp_path) == "MODULE\n"


# --- the refusals ---------------------------------------------------------------- #


def test_a_missing_diagnostics_raises_rather_than_returning_empty(tmp_path):
    _api(tmp_path)
    with pytest.raises(AssertionError, match="renamed or moved"):
        diagnostics_source(tmp_path)


def test_an_empty_package_raises_rather_than_returning_empty(tmp_path):
    (_api(tmp_path) / "diagnostics").mkdir()
    with pytest.raises(AssertionError, match="no .py files"):
        diagnostics_source(tmp_path)


def test_the_refusals_are_the_point_not_defensiveness():
    """Returning '' on either refusal passes every negative assertion in the suite.

    Stated as a test so the two ``raise`` lines are never softened into a fallback by
    someone tidying up: an empty string here is indistinguishable, to a caller, from a
    diagnostics module that genuinely no longer contains the thing being checked.
    """
    import re

    src = (Path(__file__).resolve().parent / "diagnostics_source.py").read_text(
        encoding="utf-8"
    )
    # A BARE `return ""` -- not `return "".join(...)`, which is the real joiner.
    assert not re.search(r'return ""\s*$', src, re.M), (
        "a bare empty-string return is the fallback this reader must never grow"
    )
    assert "raise AssertionError" in src
