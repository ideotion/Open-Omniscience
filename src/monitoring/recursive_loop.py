"""
Recursive-improvement loop — the diagnostics SELF-INVENTORY (planning §6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

§6.2's recursive-improvement loop is: code → run the app → observe (the app's OWN diagnostics
endpoints) → fix → re-run → PR. "The instruments improve, which improves the loop." Before the
loop can trust what those instruments report, the instruments themselves must be correct — so
the loop's own mechanism-proof GATES (the deterministic self-tests that ship beside each
harness) need to be all-green.

This module is that one read-only check: it imports + runs each self-test GATE and reports, per
gate, ``{importable, passed, error}`` — a counts-only snapshot the recursive-improvement agent
(or the maintainer) reads to know the measurement instruments are trustworthy before acting on
any diagnostic number. Degrade LOUDLY: an un-importable module or a raising self-test is reported
with its error, never a fabricated green. No score.

The GATES here are the cheap, deterministic, no-DB / no-network mechanism proofs — the
``run_*_selftest`` harness that ships beside each measurement instrument (keyword, IR-eval,
perception-eval, keyword-triage, conjunction, leads, non-article, power-profile, search-timing,
skeleton, source-audit, tor-throughput). Running them all is fast, so this can ride the
all-diagnostics bundle. It is DISTINCT from the aggregator (``diagnostics._all_diagnostics_
members``), which bundles the heavier data reports; this meta-gate answers "are the loop's own
correctness checks green?".
"""

from __future__ import annotations

import importlib

# The recursive-improvement loop's mechanism-proof GATES: (name, module, callable). Each callable
# runs a deterministic self-test (no DB, no network) and returns a log dict. Add a gate here the
# moment a new measurement harness ships, so the loop's self-inventory covers it — and
# ``tests/test_recursive_loop.py`` ENFORCES that (it discovers every ``run_*_selftest`` in the tree
# and fails if one is unregistered), so this list can never silently lapse again (R5, 2026-07-14:
# it had lapsed 8 times).
LOOP_SELFTESTS: tuple[tuple[str, str, str], ...] = (
    ("keyword-selftest", "src.analytics.selftest", "run_keyword_selftest"),
    ("ir-eval-selftest", "src.analytics.ir_eval", "run_ir_eval_selftest"),
    ("perception-eval-selftest", "src.analytics.perception_eval", "run_perception_eval_selftest"),
    ("keyword-triage-selftest", "src.ai_layer.triage", "run_triage_selftest"),
    ("source-tags-selftest", "src.ai_layer.source_tags", "run_source_tags_selftest"),
    ("conjunction-selftest", "src.analytics.conjunction", "run_conjunction_selftest"),
    ("leads-selftest", "src.briefing.leads", "run_leads_selftest"),
    ("non-article-selftest", "src.ingest.non_article", "run_non_article_selftest"),
    ("power-profile-selftest", "src.config.power_profiles", "run_power_profile_selftest"),
    ("search-timing-selftest", "src.monitoring.search_timing", "run_search_timing_selftest"),
    ("skeleton-selftest", "src.analytics.skeleton", "run_skeleton_selftest"),
    ("source-audit-selftest", "src.analytics.source_audit", "run_source_audit_selftest"),
    ("tor-throughput-selftest", "src.ingest.tor_throughput", "run_tor_throughput_selftest"),
    ("kpi-selftest", "src.monitoring.kpi", "run_kpi_selftest"),
    ("prose-gate-selftest", "src.services.prose_gate", "run_prose_gate_selftest"),
    (
        "qualification-assist-selftest",
        "src.ai_layer.qualification_assist",
        "run_qualification_assist_selftest",
    ),
)


def _selftest_passed(log) -> bool | None:
    """Normalize the pass verdict across the self-test log shapes: a top-level ``passed`` bool
    (ir/perception/triage) or a ``summary.failed == 0`` (keyword). None = shape not recognized
    (reported honestly, never assumed passing)."""
    if not isinstance(log, dict):
        return None
    if isinstance(log.get("passed"), bool):
        return log["passed"]
    summ = log.get("summary")
    if isinstance(summ, dict) and isinstance(summ.get("failed"), int):
        return summ["failed"] == 0
    return None


def recursive_loop_report(
    registry: tuple[tuple[str, str, str], ...] | None = None, *, run: bool = True
) -> dict:
    """Import (and, when ``run``, execute) each loop self-test GATE; report per-gate
    ``{importable, passed, error, schema}`` + a counts-only summary. Read-only, deterministic,
    no DB / no network. Degrades loudly — an import error or a raising self-test is reported
    with its error string and ``passed`` stays None/False, never a fabricated green."""
    reg = LOOP_SELFTESTS if registry is None else registry
    instruments: list[dict] = []
    for name, module_path, fn_name in reg:
        row: dict = {"name": name, "importable": False, "passed": None, "error": None, "schema": None}
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, fn_name)
            row["importable"] = True
        except Exception as exc:  # noqa: BLE001 - an un-importable gate degrades, never raises
            row["error"] = f"{type(exc).__name__}: {exc}"
            instruments.append(row)
            continue
        if run:
            try:
                log = fn()
                row["schema"] = log.get("schema") if isinstance(log, dict) else None
                row["passed"] = _selftest_passed(log)
            except Exception as exc:  # noqa: BLE001 - a raising self-test degrades, never raises
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["passed"] = False
        instruments.append(row)

    importable = sum(1 for r in instruments if r["importable"])
    passed = sum(1 for r in instruments if r["passed"] is True)
    failed = sum(1 for r in instruments if r["passed"] is False)
    return {
        "schema": "oo-recursive-loop-1",
        "instruments": instruments,
        "summary": {
            "total": len(instruments),
            "importable": importable,
            "passed": passed,
            "failed": failed,
            "all_green": (passed == len(instruments)) if instruments else False,
        },
        "method": (
            "imports + runs each recursive-improvement loop GATE (the deterministic self-test "
            "beside each measurement harness) and reports per-gate importable/passed/error. "
            "Counts only, no score."
        ),
        "caveat": (
            "This checks that the loop's OWN correctness gates are green — not that the corpus "
            "is healthy (the data reports do that). An un-importable or raising gate is reported "
            "with its error, never a fabricated pass. §6's ui_walk (screenshot/console walk) and "
            "the AppVM runner are browser/VM-gated and are NOT part of this in-process check."
        ),
    }
