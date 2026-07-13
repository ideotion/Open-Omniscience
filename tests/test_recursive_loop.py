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
