"""The card audit's two counts the 2026-11-14 field test misread (open-on-main row 79).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

1. ``cards_where_n_mismatches_ids`` was 2 on two instances. Every mismatching card in the
   bundles on hand was one whose ``n`` counts something OTHER than its articles: the
   reading-diet card (n = sources, ids = up to 2000 articles), capacity (n = flagged
   sources), echo chamber and story lineage (n = sources), rising (n = mentions, ids = the
   few articles shown), the price card (n = days). The audit compared every one of them
   with the id count, so the mismatch was the audit's, not the producers'. It now compares
   only where ``n`` counts the card's own article_ids, and says what n counts everywhere.
2. "Arithmetic validation could check 1 of 65-109 math rows." Most of those rows state a
   count; there is nothing in them to recompute, and the report now counts them apart
   (``quantity_rows_n``). The rest included comparison rows with a verdict
   ("24.21 ≥ 8 × 2.14 ✓") that the audit never checked; it now re-makes the comparison and
   checks the tick against it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.briefing.card import Card
from src.briefing.card_audit import (
    N_COUNTS_BY_TYPE,
    _corpus_fidelity,
    check_math_row,
    check_trigger,
)

ROOT = Path(__file__).resolve().parents[1]


def _card(**kw) -> Card:
    base = {"type": "rising", "title": "t", "summary": "s", "bucket": "rising", "method": "m", "caveat": "c", "key": "k"}
    base.update(kw)
    return Card(**base)


def _resolved(total: int) -> dict:
    return {"total": total, "resolved_total": total, "missing_n": 0, "quarantined_n": 0}


# ------------------------------------------------------------------ n against the ids


def _card_types_with_article_ids() -> set[str]:
    """Every literal ``Card(type=...)`` in the briefing package that passes article_ids."""
    found: set[str] = set()
    for path in sorted((ROOT / "src" / "briefing").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Card"):
                continue
            kws = {k.arg: k.value for k in node.keywords if k.arg}
            ty = kws.get("type")
            if "article_ids" in kws and isinstance(ty, ast.Constant) and isinstance(ty.value, str):
                found.add(ty.value)
    return found


def test_every_card_type_that_carries_ids_declares_what_its_n_counts():
    """A new producer cannot slip back into the misleading comparison: it must say."""
    types = _card_types_with_article_ids()
    assert len(types) >= 20, "the scan stopped finding producers"
    missing = sorted(types - set(N_COUNTS_BY_TYPE))
    assert not missing, f"declare what n counts in N_COUNTS_BY_TYPE for: {missing}"


def test_the_field_cards_that_mismatched_count_another_unit():
    """The producers behind every mismatch in the field bundles, read from their code."""
    for card_type, unit in (
        ("diet_self_audit", "sources"),
        ("capacity_implausible", "sources"),
        ("echo_chamber", "sources"),
        ("rising", "mentions"),
        ("price_narrative", "days"),
    ):
        assert N_COUNTS_BY_TYPE[card_type] == unit


def test_a_sources_count_is_not_compared_with_the_article_ids():
    card = _card(type="diet_self_audit", n=3804, article_ids=list(range(1, 2001)))
    fid = _corpus_fidelity(card, _resolved(2000))
    assert fid["n_counts"] == "sources"
    assert fid["n_matches_ids"] is None
    assert fid["n_vs_ids_delta"] is None
    assert fid["n_claimed"] == 3804  # still reported, never dropped


def test_an_articles_count_is_still_compared_and_a_real_mismatch_still_shows():
    ok = _corpus_fidelity(_card(type="copypasta", n=3, article_ids=[1, 2, 3]), _resolved(3))
    assert ok["n_counts"] == "articles" and ok["n_matches_ids"] is True
    bad = _corpus_fidelity(_card(type="copypasta", n=5, article_ids=[1, 2, 3]), _resolved(3))
    assert bad["n_matches_ids"] is False
    assert bad["n_vs_ids_delta"] == 2


def test_evidence_only_ids_are_never_what_n_counts():
    """``total`` adds the evidence rows' ids; those are examples, not the counted set."""
    card = _card(type="copypasta", n=3, article_ids=[1, 2, 3])
    fid = _corpus_fidelity(card, _resolved(5))  # 2 more ids from evidence rows
    assert fid["article_ids_total"] == 5
    assert fid["card_article_ids_n"] == 3
    assert fid["n_matches_ids"] is True


def test_an_undeclared_type_is_named_not_compared():
    fid = _corpus_fidelity(_card(type="not_a_real_type", n=9, article_ids=[1]), _resolved(1))
    assert fid["n_counts"] == "undeclared"
    assert fid["n_matches_ids"] is None


# ------------------------------------------------------------------ comparison rows


@pytest.mark.parametrize(
    "value",
    ["24.21 ≥ 8 × 2.14 ✓", "3 < 10 ✓", "2.5 ≤ 1 ✗", "12.0 >= 2.0 × 5.0 ✓", "1 > 4 ✗"],
)
def test_a_true_comparison_with_its_verdict_reproduces(value):
    row = check_math_row({"label": "l", "value": value})
    assert row["row_kind"] == "comparison"
    assert row["checkable"] is True, row
    assert row["reproduced"] is True


@pytest.mark.parametrize("value", ["2.14 ≥ 8 × 2.14 ✓", "30 < 10 ✓", "24.21 ≥ 8 × 2.14 ✗"])
def test_a_verdict_the_numbers_contradict_is_a_failure(value):
    row = check_math_row({"label": "l", "value": value})
    assert row["checkable"] is True
    assert row["reproduced"] is False


def test_a_comparison_inside_the_rounding_is_not_decided_either_way():
    """17.12 against 8 × 2.14 = 17.12: the true values could sit on either side."""
    row = check_math_row({"label": "l", "value": "17.12 ≥ 8 × 2.14 ✗"})
    assert row["row_kind"] == "comparison"
    assert row["checkable"] is False
    assert "rounding" in row["reason"]
    assert "reproduced" not in row


@pytest.mark.parametrize("value", ["≥ 20 ✓", "≥ 5 ✓"])
def test_a_threshold_without_its_tested_value_is_not_checkable(value):
    row = check_math_row({"label": "l", "value": value})
    assert row["row_kind"] == "comparison"
    assert row["checkable"] is False
    assert "another row" in row["reason"]


@pytest.mark.parametrize("value", ["318219 · 4115 ✓", "✓", "1 ≥ 2 ≥ 3 ✓", "a ≥ 2 ✓", "5 ≥ 3"])
def test_rows_that_are_not_one_clean_comparison_are_never_passed(value):
    row = check_math_row({"label": "l", "value": value})
    assert row["checkable"] is False
    assert "reproduced" not in row


def test_quantity_rows_are_counted_apart_from_rows_the_check_could_not_read():
    out = check_trigger(
        {
            "plain": "p",
            "math": [
                {"label": "a", "value": "318219"},  # a quantity
                {"label": "b", "value": "1% – 2%"},  # a range: a quantity too
                {"label": "c", "value": "4787 ÷ 318219 = 2%"},  # an equation
                {"label": "d", "value": "24.21 ≥ 8 × 2.14 ✓"},  # a comparison
                {"label": "e", "value": "≥ 20 ✓"},  # a threshold on another row's value
            ],
        }
    )
    assert out["rows_total"] == 5
    assert out["checkable_n"] == 2
    assert out["reproduced_n"] == 2
    assert out["not_checkable_n"] == 3
    assert out["quantity_rows_n"] == 2
    assert [r["row_kind"] for r in out["rows"]] == [
        "quantity", "quantity", "equation", "comparison", "comparison",
    ]
