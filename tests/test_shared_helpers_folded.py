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
    for name in (
        "walk_no_score",
        "median_ms",
        "coerce_bool",
        "snapshot_or_unavailable",
        "import_owns_the_machine",
        "rss_mb",
        "read_jsonl_tail",
        "tri_state",
    ):
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
    # MODULE-LEVEL imports only: importing the module must cost nothing. Two helpers import psutil / the
    # scheduler INSIDE the call, exactly as the copies they replaced did (and best-effort around it).
    for n in tree.body:
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    assert mods <= {"__future__", "json", "os", "pathlib", "statistics", "time", "collections", "typing"}, mods


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
    """Compares ORIGIN and BEHAVIOUR, never function identity: another test may reload ``src.paths`` (or replace it in
    ``sys.modules``), after which ``paths.diagnostics_dir`` is a different object from the one a module imported earlier
    (seen in a full sharded run, R497). The origin is read off the function itself (``__module__`` / ``__name__``)."""
    from src.api.diagnostics import bundle
    from src.briefing import card_audit
    from src.monitoring import p0_validation

    fns = (bundle._all_diagnostics_dir, card_audit._report_dir, p0_validation._report_dir)
    # The fold itself: the old names ARE the shared function, so a re-added private body cannot hide.
    for fn in fns:
        assert (fn.__module__, fn.__name__) == ("src.paths", "diagnostics_dir"), fn
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    got = [fn() for fn in fns]
    assert got[0] == got[1] == got[2]
    # ... under the data dir that the function's OWN module resolves (robust to a reload or a memoised data_dir)
    assert got[0] == fns[0].__globals__["data_dir"]() / "diagnostics"
    assert got[0].is_dir()


# ---------------------------------------------------------------------------------------------
# the second fold (R494): pairs that only differed in a docstring, a constant or a file name
# ---------------------------------------------------------------------------------------------
#: file -> the private defs it no longer carries (other files may still define the same name, so
#: the global scan above cannot pin these)
SECOND_FOLD = {
    "ingest/import_job.py": ("_import_owns_the_machine",),
    "analytics/quarantine_job.py": ("_import_owns_the_machine",),
    "monitoring/release_run.py": ("_rss_mb",),
    "testing/collect_soak.py": ("_rss_mb",),
}


@pytest.mark.parametrize(("rel", "names"), sorted(SECOND_FOLD.items()))
def test_the_second_fold_left_no_private_copy_in_these_files(rel, names):
    tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    assert not defined & set(names), (rel, defined & set(names))


def test_the_old_names_are_the_shared_functions():
    from src.analytics import quarantine_job
    from src.ingest import import_job
    from src.monitoring import release_run
    from src.testing import collect_soak

    # By origin, not identity: a reload elsewhere in a sharded run makes the objects differ (R497).
    for fn, name in (
        (import_job._import_owns_the_machine, "import_owns_the_machine"),
        (quarantine_job._import_owns_the_machine, "import_owns_the_machine"),
        (release_run._rss_mb, "rss_mb"),
        (collect_soak._rss_mb, "rss_mb"),
    ):
        assert (fn.__module__, fn.__name__) == ("src.shared", name), fn


def test_import_owns_the_machine_is_false_when_the_scheduler_cannot_be_read(monkeypatch):
    import src.scheduler.runner as runner

    monkeypatch.setattr(runner, "exclusive_window_open", lambda: True)
    assert shared.import_owns_the_machine() is True

    def boom():
        raise RuntimeError("unreadable")

    monkeypatch.setattr(runner, "exclusive_window_open", boom)
    assert shared.import_owns_the_machine() is False


def test_rss_mb_is_a_one_decimal_figure_or_none():
    v = shared.rss_mb()
    assert v is None or (isinstance(v, float) and v > 0 and round(v, 1) == v)


def test_rss_mb_divides_by_one_mebibyte(monkeypatch):
    """The divisor is the one thing the two copies spelled differently (a ``_MIB`` constant)."""
    fake = types.ModuleType("psutil")
    fake.Process = lambda: types.SimpleNamespace(memory_info=lambda: types.SimpleNamespace(rss=5 * 1024 * 1024))
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake)
    assert shared.rss_mb() == 5.0
    monkeypatch.setitem(__import__("sys").modules, "psutil", None)  # psutil missing -> None, not a guess
    assert shared.rss_mb() is None


def test_read_jsonl_tail(tmp_path):
    p = tmp_path / "log.jsonl"
    assert shared.read_jsonl_tail(p, 10) == []  # missing file
    p.write_text('{"n": 1}\nnot json\n{"n": 3}\n{"n": 4}\n', encoding="utf-8")
    assert shared.read_jsonl_tail(p, 10) == [{"n": 1}, {"n": 3}, {"n": 4}]  # the torn line is skipped
    assert shared.read_jsonl_tail(p, 2) == [{"n": 3}, {"n": 4}]  # the last two LINES, then parsed
    assert shared.read_jsonl_tail(p, 3) == [{"n": 3}, {"n": 4}]  # a skipped line still uses up a slot
    assert shared.read_jsonl_tail(p, 0) == [{"n": 1}, {"n": 3}, {"n": 4}]  # [-0:] is everything: unchanged from the copies


def test_each_recent_results_keeps_its_own_default_and_log():
    import inspect

    from src.monitoring import feed_preflight, field_test

    assert inspect.signature(field_test.recent_results).parameters["limit"].default == 500
    assert inspect.signature(feed_preflight.recent_results).parameters["limit"].default == 1000


def test_each_recent_results_reads_its_own_log(tmp_path, monkeypatch):
    from src.monitoring import feed_preflight, field_test

    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text('{"w": "a"}\n', encoding="utf-8")
    b.write_text('{"w": "b"}\n', encoding="utf-8")
    monkeypatch.setattr(field_test, "_log_path", lambda: a)
    monkeypatch.setattr(feed_preflight, "_log_path", lambda: b)
    assert field_test.recent_results() == [{"w": "a"}]
    assert feed_preflight.recent_results() == [{"w": "b"}]


@pytest.mark.parametrize(("value", "want"), [("1", "forced-on"), ("0", "forced-off"), ("", "auto"), ("yes", "auto"), (None, "auto")])
def test_tri_state_and_the_two_serves_keep_their_own_variable(monkeypatch, value, want):
    from src.analytics import map_serve, rollup_serve

    for var, fn in (("OO_COLUMNAR_MAP_SERVE", map_serve.serve_mode), ("OO_COLUMNAR_SERVE", rollup_serve.serve_mode)):
        other = "OO_COLUMNAR_SERVE" if var == "OO_COLUMNAR_MAP_SERVE" else "OO_COLUMNAR_MAP_SERVE"
        monkeypatch.delenv(other, raising=False)
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)
        assert fn() == want, var
        assert shared.tri_state(var) == want
    # one variable never decides the other serve
    monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "0")
    monkeypatch.delenv("OO_COLUMNAR_SERVE", raising=False)
    assert rollup_serve.serve_mode() == "auto"
    # ... and the reverse direction
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "0")
    monkeypatch.delenv("OO_COLUMNAR_MAP_SERVE", raising=False)
    assert map_serve.serve_mode() == "auto"
