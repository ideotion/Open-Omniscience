"""Audit A-036 (R446): helpers that used to be byte-identical private copies live in ONE place.

Two halves, both needed. The BEHAVIOUR half pins what every copy did (the fold is a move, not a
change). The STRUCTURE half pins that the copies are gone: a test that only checked behaviour
would stay green the day somebody pasted a seventh ``_walk_no_score`` back in.
"""

from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

from src import paths, shared

SRC = Path(__file__).resolve().parent.parent / "src"

#: the private names that used to be defined once per file (counts at the fold: 6, 2, 2, 1+1+1)
FOLDED = ("_walk_no_score", "_median_ms", "_coerce_bool", "_all_diagnostics_dir", "_report_dir")


def _all_defs() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        # Every def anywhere in the file (nested, async, method), not only top-level ones.
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
                out.setdefault(n.name, []).append(str(p.relative_to(SRC)))
    return out


# ---------------------------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", FOLDED)
def test_the_private_copies_are_gone(name):
    defs = _all_defs()
    assert name not in defs, f"{name} is defined again in {defs.get(name)}: use the shared helper"


def test_each_shared_helper_is_defined_once():
    defs = _all_defs()
    for name in ("walk_no_score", "median_ms", "coerce_bool", "snapshot_or_unavailable"):
        assert defs.get(name) == ["shared.py"], (name, defs.get(name))
    assert defs.get("diagnostics_dir") == ["paths.py"]


def test_safe_snapshot_wrappers_delegate_instead_of_repeating_the_try():
    for rel in ("database/open_stats.py", "ingest/lock_stats.py"):
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "safe_snapshot")
        assert not any(isinstance(n, ast.Try) for n in ast.walk(fn)), rel
        assert "snapshot_or_unavailable" in ast.unparse(fn), rel


def test_shared_module_is_stdlib_only():
    """It must stay free to import from any module (no cycle, no cost): that is why it is not in src.utils."""
    tree = ast.parse((SRC / "shared.py").read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    assert mods <= {"__future__", "statistics", "time", "collections", "typing"}, mods


# ---------------------------------------------------------------------------------------------
# behaviour
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["score", "Ranking", "user_rating", "gradeX"])
def test_walk_no_score_refuses_a_score_like_key_at_any_depth(key):
    with pytest.raises(AssertionError, match="score-like key"):
        shared.walk_no_score({"a": [{"b": {key: 1}}]})


def test_walk_no_score_passes_clean_data_and_ignores_values():
    shared.walk_no_score({"a": [{"b": 1}], "c": {"d": "score"}})  # a VALUE saying score is not a key


def test_walk_no_score_raises_explicitly_so_python_O_cannot_strip_it():
    src = (SRC / "shared.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "walk_no_score")
    assert not any(isinstance(n, ast.Assert) for n in ast.walk(fn))


def test_median_ms_cold_then_warm_median_and_size(monkeypatch):
    ticks = iter([0.0, 0.010, 1.0, 1.002, 2.0, 2.004, 3.0, 3.006])
    monkeypatch.setattr(shared, "time", types.SimpleNamespace(perf_counter=lambda: next(ticks)))
    cold, warm, size = shared.median_ms(lambda: [1, 2, 3], 4)
    assert (cold, warm, size) == (10.0, 4.0, 3)


def test_median_ms_one_run_has_no_warm_runs_so_it_reports_the_only_one(monkeypatch):
    ticks = iter([0.0, 0.0125])
    monkeypatch.setattr(shared, "time", types.SimpleNamespace(perf_counter=lambda: next(ticks)))
    assert shared.median_ms(lambda: 7, 1) == (12.5, 12.5, None)


@pytest.mark.parametrize(
    ("value", "fallback", "want"),
    [
        (True, False, True),
        (False, True, False),
        (" Yes ", False, True),
        ("ON", False, True),
        ("1", False, True),
        ("true", False, True),
        ("off", True, False),
        ("", True, False),
        (1, False, False),  # not a bool, not a string: the fallback, as before
        (None, True, True),
    ],
)
def test_coerce_bool(value, fallback, want):
    assert shared.coerce_bool(value, fallback) is want


def test_snapshot_or_unavailable_names_the_class_never_the_words():
    def boom():
        raise ValueError("secret words /home/x")

    assert shared.snapshot_or_unavailable(boom) == {"unavailable": "ValueError"}
    assert shared.snapshot_or_unavailable(lambda: {"n": 0}) == {"n": 0}


def test_diagnostics_dir_is_created_under_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    d = paths.diagnostics_dir()
    assert d == tmp_path / "diagnostics" and d.is_dir()
    assert paths.diagnostics_dir() == d  # idempotent


def test_the_three_report_dirs_resolve_to_it(tmp_path, monkeypatch):
    from src.api.diagnostics import bundle
    from src.briefing import card_audit
    from src.monitoring import p0_validation

    # The fold itself: the old names ARE the shared function, so a re-added private body cannot hide.
    assert bundle._all_diagnostics_dir is paths.diagnostics_dir
    assert card_audit._report_dir is paths.diagnostics_dir
    assert p0_validation._report_dir is paths.diagnostics_dir
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    want = tmp_path / "diagnostics"
    assert bundle._all_diagnostics_dir() == want
    assert card_audit._report_dir() == want
    assert p0_validation._report_dir() == want
