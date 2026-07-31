"""
The audit-to-audit differ — the third instrument of the card improvement loop.

Continuous improvement (maintainer-ruled 2026-07-31): improve -> audit -> improve
-> audit. The determinism check and per-run persistence were already built inside
card_audit.py; this covers the piece that was missing — comparing two saved runs.

The tests below deliberately attack the DIRECTIONS the classifier could get wrong,
because a differ that calls a regression an improvement is worse than no differ.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.briefing.card_audit_diff import (
    CHANGED,
    IMPROVED,
    NOT_COMPARABLE,
    NOT_MEASURABLE,
    REGRESSED,
    UNCHANGED,
    card_audit_metrics,
    classify_metric,
    diff_card_audit_metrics,
    diff_card_audit_reports,
    run_card_audit_diff_selftest,
)


def _report(**over) -> dict:
    """A card-audit report carrying the fields the projection reads."""
    return {
        "generated_at": over.pop("generated_at", "2026-01-01T00:00:00+00:00"),
        "depth": "summary",
        "producer_inventory": {
            "errored": [{"name": f"p{i}"} for i in range(over.pop("errored", 0))],
            "total": over.pop("total", 12),
            "silent": [],
        },
        "validation_summary": {
            "cards_surfaced": over.pop("cards_surfaced", 5),
            "cards_suppressed": over.pop("cards_suppressed", 0),
            "determinism": {"stable": over.pop("stable", True)},
            "arithmetic": {
                "failed_n": over.pop("failed_n", 0),
                "not_checkable_n": over.pop("not_checkable_n", 0),
                "reproduced_n": over.pop("reproduced_n", 3),
                "cards_without_trigger": over.pop("cards_without_trigger", 0),
            },
            "non_fabrication": {
                "method_missing_n": over.pop("method_missing_n", 0),
                "caveat_missing_n": 0,
                "cards_with_banned_key_matches": over.pop("banned", 0),
            },
            "corpus_fidelity": {
                "cards_without_article_ids": 0,
                "cards_with_missing_articles": over.pop("missing_articles", 0),
                "cards_with_quarantined_articles": over.pop("quarantined", 0),
                "cards_where_n_mismatches_ids": 0,
            },
        },
    }


def _row(diff: dict, mid: str) -> dict:
    return next(r for r in diff["metrics"] if r["id"] == mid)


# -- the classifier's directions -------------------------------------------- #


@pytest.mark.parametrize(
    ("mid", "kw", "old", "new", "expected"),
    [
        ("P1", "errored", 3, 0, IMPROVED),
        ("P1", "errored", 0, 3, REGRESSED),
        ("A1", "failed_n", 5, 1, IMPROVED),
        ("A1", "failed_n", 1, 5, REGRESSED),
        ("A3", "reproduced_n", 2, 8, IMPROVED),   # up-metric: more is better
        ("A3", "reproduced_n", 8, 2, REGRESSED),
        ("N3", "banned", 2, 0, IMPROVED),
        ("C2", "missing_articles", 0, 4, REGRESSED),
        ("C3", "quarantined", 7, 7, UNCHANGED),
    ],
)
def test_direction_of_goodness_is_respected(mid, kw, old, new, expected):
    d = diff_card_audit_reports(_report(**{kw: old}), _report(**{kw: new}))
    assert _row(d, mid)["classification"] == expected, _row(d, mid)


def test_a_count_with_no_goodness_direction_is_never_an_improvement():
    """More cards surfaced is not better, and neither is fewer.

    Calling either one an improvement would be a fabricated judgement.
    """
    for old, new in ((5, 40), (40, 5)):
        d = diff_card_audit_reports(_report(cards_surfaced=old), _report(cards_surfaced=new))
        row = _row(d, "F1")
        assert row["classification"] == CHANGED, row
        assert row["direction"] is None


# -- the honesty rails ------------------------------------------------------- #


def test_an_unrun_determinism_check_is_not_measurable_never_stable():
    """card_audit sets stable=None when the check was skipped by its budget.

    That None must survive as not-measurable; reading it as 'fine' would report an
    unrun check as a stable feed, which the audit's own note forbids.
    """
    d = diff_card_audit_reports(_report(stable=True), _report(stable=None))
    assert _row(d, "D1")["classification"] == NOT_MEASURABLE
    assert _row(d, "D1")["new_value"] is None


def test_instability_reads_as_a_regression():
    d = diff_card_audit_reports(_report(stable=True), _report(stable=False))
    assert _row(d, "D1")["classification"] == REGRESSED


def test_an_unreported_number_is_not_read_as_zero():
    """A missing block must not become a zero-to-zero 'unchanged' pass."""
    stripped = _report()
    del stripped["validation_summary"]["arithmetic"]
    d = diff_card_audit_reports(stripped, _report(failed_n=0))
    row = _row(d, "A1")
    assert row["old_value"] is None
    assert row["classification"] == NOT_MEASURABLE
    assert row["classification"] != UNCHANGED


def test_a_metric_only_one_side_knows_is_reported_not_dropped():
    a, b = card_audit_metrics(_report()), card_audit_metrics(_report())
    b["metrics"].append({"id": "ZZ", "name": "other build", "direction": "down", "value": 1})
    d = diff_card_audit_metrics(a, b)
    zz = [r for r in d["metrics"] if r["id"] == "ZZ"]
    assert zz and zz[0]["classification"] == NOT_COMPARABLE
    assert "note" in zz[0]


def test_booleans_are_not_counted_as_numbers():
    """bool is an int subclass — a True would otherwise classify as the number 1."""
    r = _report()
    r["validation_summary"]["arithmetic"]["failed_n"] = True
    assert card_audit_metrics(r)["metrics"][3]["value"] is None


def test_classify_metric_handles_absent_rows():
    assert classify_metric(None, {"value": 1, "direction": "down"}) == NOT_COMPARABLE
    assert classify_metric({"value": 1, "direction": "down"}, None) == NOT_COMPARABLE


# -- payload shape ----------------------------------------------------------- #


def test_no_blended_verdict_and_no_score_shaped_key():
    d = diff_card_audit_reports(_report(), _report())
    flat = json.dumps(d).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat
    assert "counts" in d and isinstance(d["counts"], dict)  # a listing, not a blend
    assert d["method"] and d["caveat"]


def test_caveat_states_that_ingest_moves_numbers_on_its_own():
    """Two audits of a live corpus differ for reasons that are not the fix."""
    d = diff_card_audit_reports(_report(), _report())
    assert "ingest" in d["caveat"].lower()


def test_diff_latest_degrades_with_a_reason_when_there_is_nothing_to_compare(monkeypatch):
    """A fresh install has fewer than two saved runs — normal, not an error."""
    monkeypatch.setattr("src.briefing.card_audit_diff.list_card_audit_reports", lambda: ["a.json"])
    out = __import__(
        "src.briefing.card_audit_diff", fromlist=["diff_latest_card_audits"]
    ).diff_latest_card_audits()
    assert out["available"] is False
    assert "two are needed" in out["reason"]


# -- the registered harness -------------------------------------------------- #


def test_selftest_passes_and_is_registered_in_the_recursive_loop():
    out = run_card_audit_diff_selftest()
    assert out["failed"] == 0, [c for c in out["cases"] if not c["passed"]]
    assert out["total"] >= 9

    from src.monitoring.recursive_loop import LOOP_SELFTESTS

    assert any(
        mod == "src.briefing.card_audit_diff" and fn == "run_card_audit_diff_selftest"
        for _, mod, fn in LOOP_SELFTESTS
    ), "the differ's selftest must be registered so the loop cannot silently lapse"
