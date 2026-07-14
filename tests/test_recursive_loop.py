"""
Recursive-improvement loop self-inventory (planning §6).

Proves the loop's mechanism-proof GATES are all-green, and — non-vacuously — that a broken or
raising gate is reported LOUDLY (importable:false / passed:false + error), never a fabricated
green. Plus the membership CONTRACT that the all-diagnostics aggregator carries the recursive-
loop instruments (the guard that did not exist before, so no future edit silently drops one).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

from src.monitoring.recursive_loop import LOOP_SELFTESTS, recursive_loop_report


def test_all_loop_gates_are_green_on_this_tree():
    r = recursive_loop_report()
    assert r["schema"] == "oo-recursive-loop-1"
    assert r["summary"]["total"] == len(LOOP_SELFTESTS)
    assert r["summary"]["all_green"] is True, [i for i in r["instruments"] if not i["passed"]]
    # the §8 triage self-test is one of the wired gates.
    names = {i["name"] for i in r["instruments"]}
    assert "keyword-triage-selftest" in names


def _discover_selftest_harnesses() -> dict[str, str]:
    """Every module-level ``run_*_selftest`` defined under src/ (fn_name -> file). The TREE is
    the source of truth for the registry — a hand-list would be the same lapse one level up."""
    import re

    found: dict[str, str] = {}
    for path in Path("src").rglob("*.py"):
        for m in re.finditer(r"^def (run_[a-z0-9_]+_selftest)\b", path.read_text(encoding="utf-8"), re.M):
            found[m.group(1)] = str(path)
    return found


def test_every_selftest_harness_in_the_tree_is_registered():
    """R5 ENFORCEMENT (2026-07-14): the registry had silently lapsed 8 times. Discover every
    ``run_*_selftest`` in the tree and assert each is a LOOP_SELFTESTS gate — so a new
    measurement harness can never ship un-inventoried again. (Prove-it-fails check: add a dummy
    ``def run_x_selftest`` to any src file and this test goes red until it is registered.)"""
    registered = {fn for _n, _m, fn in LOOP_SELFTESTS}
    found = _discover_selftest_harnesses()
    unregistered = {fn: file for fn, file in found.items() if fn not in registered}
    assert not unregistered, f"run_*_selftest harnesses NOT registered in LOOP_SELFTESTS: {unregistered}"
    # and no dead registration: every registered gate has a real harness in the tree.
    dead = registered - set(found)
    assert not dead, f"LOOP_SELFTESTS gates with no run_*_selftest in the tree: {dead}"


def test_registry_module_paths_import_and_expose_their_callable():
    """Each (module, fn) in the registry must actually resolve — a typo'd path would degrade the
    gate to importable:false forever without this."""
    import importlib

    for name, module_path, fn_name in LOOP_SELFTESTS:
        mod = importlib.import_module(module_path)
        assert callable(getattr(mod, fn_name)), f"{name}: {module_path}.{fn_name} is not callable"


def test_report_degrades_loudly_on_a_broken_or_raising_gate():
    # non-vacuous: an un-importable module and an importable-but-raising callable must be
    # reported with their error, never a fabricated pass.
    reg = (
        ("good", "src.ai_layer.triage", "run_triage_selftest"),  # imports + passes
        ("bad-module", "src.nonexistent.module", "x"),           # import error
        ("raiser", "json", "loads"),                             # imports; json.loads() -> TypeError
    )
    r = recursive_loop_report(reg)
    by = {i["name"]: i for i in r["instruments"]}
    assert by["good"]["importable"] is True and by["good"]["passed"] is True
    assert by["bad-module"]["importable"] is False and by["bad-module"]["error"]
    assert by["bad-module"]["passed"] is None
    assert by["raiser"]["importable"] is True and by["raiser"]["passed"] is False
    assert by["raiser"]["error"]
    assert r["summary"] == {"total": 3, "importable": 2, "passed": 1, "failed": 1, "all_green": False}


def test_run_false_probes_importability_without_running():
    r = recursive_loop_report(run=False)
    assert all(i["importable"] for i in r["instruments"])
    assert all(i["passed"] is None for i in r["instruments"])  # not run -> no verdict


def test_no_score_field():
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade"))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(recursive_loop_report())


def test_aggregator_carries_the_recursive_loop_instruments():
    # MEMBERSHIP CONTRACT (source-inspected, no app import): _all_diagnostics_members must carry
    # the recursive-loop instruments, so a future edit can never silently drop one.
    src = Path("src/api/diagnostics.py").read_text(encoding="utf-8")
    start = src.index("def _all_diagnostics_members")
    end = src.index("def _all_diagnostics_manifest", start)
    body = src[start:end]
    for member in ("article-length.json", "keyword-growth.json", "recursive-loop.json"):
        assert f'"{member}"' in body, f"{member} dropped from the all-diagnostics aggregator"
