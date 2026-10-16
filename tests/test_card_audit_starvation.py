"""One slow producer cannot blind the card audit to the others.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-10-16, two bundles from a running install whose rollup was not serving: the audit's first producer, ``rising_now``
(``q.trending``, the unserved scan), ran 60.1 s, hit the statement deadline, and the other 37 producers read
``skipped-budget``. No card was audited in either bundle. The audit now runs a producer named in ``_RUN_LAST`` after the
rest (the result and the dedup belt keep registration order, which is what ``run_all`` surfaces), counts
``skipped-budget`` in the summary, and names the slowest producers.
"""

from __future__ import annotations

import pytest

from src.briefing import card_audit, registry
from src.briefing.card import Card


def _card(key="k"):
    return Card(type="rising", title="t", summary="s", bucket="rising", method="m", caveat="c", key=key)


@pytest.fixture
def spent(monkeypatch):
    """A statement budget that a producer can spend: ``spent["yes"] = True`` makes the next check read 'expired'."""
    state = {"yes": False}
    monkeypatch.setattr(registry, "_deadline_expired", lambda _session: state["yes"])
    saved = list(registry._REGISTRY)
    registry._REGISTRY = []
    try:
        yield state
    finally:
        registry._REGISTRY = saved


def _register_pass(state, *, slow_name, slow_first=True):
    def slow(_session):
        state["yes"] = True  # the whole budget gone, as a 60 s scan does
        return []

    def make(i):
        return lambda _s: [_card(key=f"c{i}")]

    others = [(f"p{i}", make(i)) for i in range(5)]
    seq = ([(slow_name, slow)] + others) if slow_first else (others[:2] + [(slow_name, slow)] + others[2:])
    for name, fn in seq:
        registry.register(name, fn)
    return [n for n, _ in seq]


def test_a_slow_rising_now_registered_first_leaves_the_other_producers_audited(spent):
    names = _register_pass(spent, slow_name="rising_now")
    out = card_audit.observe_producers(object())
    by = {o.name: o for o in out}
    assert [by[f"p{i}"].outcome for i in range(5)] == ["ok"] * 5, "every producer behind it was audited"
    assert by["rising_now"].outcome == "no-signal"
    assert [o.name for o in out] == names, "registration order is kept in the result (the dedup belt reads it)"


def test_the_dedup_belt_still_sees_registration_order(spent):
    registry.register("rising_now", lambda _s: [_card(key="same")])
    registry.register("p0", lambda _s: [_card(key="same")])
    surfaced, suppressed = card_audit.apply_dedup_belt(card_audit.observe_producers(object()))
    assert [p for p, _c in surfaced] == ["rising_now"], "the first registered producer wins the key, as in run_all"
    assert suppressed and suppressed[0]["producer"] == "p0"


def test_without_the_ordering_the_same_pass_is_blind(spent, monkeypatch):
    """The defect, reproduced: with nothing named to run last, the producers behind the slow one are all skipped."""
    monkeypatch.setattr(card_audit, "_RUN_LAST", frozenset())
    _register_pass(spent, slow_name="rising_now")
    by = {o.name: o for o in card_audit.observe_producers(object())}
    assert [by[f"p{i}"].outcome for i in range(5)] == ["skipped-budget"] * 5


def test_a_slow_producer_that_is_not_named_still_skips_the_ones_after_it_and_says_so(spent):
    _register_pass(spent, slow_name="some_other_slow_one", slow_first=False)
    out = card_audit.observe_producers(object())
    by = {o.name: o for o in out}
    assert by["p0"].outcome == by["p1"].outcome == "ok"
    assert [by[f"p{i}"].outcome for i in (2, 3, 4)] == ["skipped-budget"] * 3, "stated, never silently absent"
    inv = card_audit._producer_inventory(out)
    assert inv["skipped_budget_n"] == 3 and inv["skipped_budget"] == ["p2", "p3", "p4"]
    assert {r["outcome"]: r["n"] for r in inv["outcome_tallies"]}["skipped-budget"] == 3


def test_a_pass_with_nothing_skipped_reports_zero_not_absent(spent):
    registry.register("p0", lambda _s: [_card()])
    inv = card_audit._producer_inventory(card_audit.observe_producers(object()))
    assert inv["skipped_budget_n"] == 0 and inv["skipped_budget"] == []


def test_the_inventory_names_the_slowest_producers():
    outs = [card_audit.ProducerOutcome(name=n, outcome="ok", elapsed_s=e) for n, e in
            (("a", 0.2), ("b", 61.0), ("c", 3.0), ("d", 9.0), ("e", 0.0))]
    inv = card_audit._producer_inventory(outs)
    assert [r["producer"] for r in inv["slowest"]] == ["b", "d", "c"]


def test_the_saved_summary_keeps_the_skipped_budget_fields(tmp_path, monkeypatch):
    import json

    (tmp_path / "oo-card-audit-2026.json").write_text(json.dumps({"producer_inventory": {
        "total": 38, "skipped_budget": ["x"], "skipped_budget_n": 1, "slowest": [], "ignored_key": 1}}), encoding="utf-8")
    monkeypatch.setattr(card_audit, "_report_dir", lambda: tmp_path)
    inv = card_audit.last_card_audit_report()["producer_inventory"]
    assert inv["skipped_budget_n"] == 1 and inv["skipped_budget"] == ["x"] and "ignored_key" not in inv
