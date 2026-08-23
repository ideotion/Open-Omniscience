"""Tests for the deep card-system audit (src/briefing/card_audit.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE CENTRAL TEST HERE is ``test_producer_inventory_separates_error_from_no_signal``:
``registry.run_all`` catches a producer exception, logs a warning and contributes
``[]`` -- exactly what a producer with legitimately NO SIGNAL contributes. In the two
pre-existing card diagnostics those two states are indistinguishable, so a producer
crashing on every run for a month looks identical to a quiet one. Closing that gap is
the reason this module exists, so it is pinned first and hardest.

The pure dimensions (arithmetic, non-fabrication, the dedup belt) are tested WITHOUT a
DB -- they are pure functions over Card objects -- which is also why they run in any
environment.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from src.briefing.card import Card
from src.briefing.card_audit import (
    DEPTHS,
    SCHEMA,
    ProducerOutcome,
    apply_dedup_belt,
    check_math_row,
    check_trigger,
    non_fabrication_checks,
    observe_producers,
    walk_banned_keys,
)


def _card(**kw) -> Card:
    base = dict(
        type="rising",
        title="t",
        summary="s",
        bucket="rising",
        method="m",
        caveat="c",
        key="k",
    )
    base.update(kw)
    return Card(**base)


# --------------------------------------------------------------------------- #
#  Dimension 5 -- NEGATIVE SPACE. The reason this module exists.
# --------------------------------------------------------------------------- #


@pytest.fixture
def clean_registry():
    """Swap the process-global producer registry for the duration of a test."""
    from src.briefing import registry

    saved = list(registry._REGISTRY)
    registry._REGISTRY = []
    try:
        yield registry
    finally:
        registry._REGISTRY = saved


def test_producer_inventory_separates_error_from_no_signal(clean_registry):
    """THE POINT OF THE WHOLE DIAGNOSTIC.

    A producer that RAISES and a producer that returns [] are indistinguishable in
    run_all (both contribute []) and therefore in every other card diagnostic. Here
    they must land in different states, and the erroring one must carry its actual
    exception type + message -- otherwise a permanently-broken producer stays
    invisible, which is precisely the 'absent reads as passed' defect this closes.
    """

    def boom(_session):
        raise ValueError("this producer is broken")

    def quiet(_session):
        return []

    def healthy(_session):
        return [_card(key="alive")]

    clean_registry.register("boom", boom)
    clean_registry.register("quiet", quiet)
    clean_registry.register("healthy", healthy)

    outcomes = {o.name: o for o in observe_producers(object())}
    assert set(outcomes) == {"boom", "quiet", "healthy"}

    # The erroring producer is NOT reported as "no signal".
    assert outcomes["boom"].outcome == "error"
    assert outcomes["boom"].error_type == "ValueError"
    assert "this producer is broken" in (outcomes["boom"].error_message or "")
    assert outcomes["boom"].cards_proposed == 0

    # The quiet producer is NOT reported as an error.
    assert outcomes["quiet"].outcome == "no-signal"
    assert outcomes["quiet"].error_type is None
    assert outcomes["quiet"].cards_proposed == 0

    # And a working producer is distinct from both.
    assert outcomes["healthy"].outcome == "ok"
    assert outcomes["healthy"].cards_proposed == 1

    # The three states must be genuinely different values -- a regression that merged
    # any two of them would still satisfy per-field checks above if they collapsed.
    assert len({outcomes[n].outcome for n in ("boom", "quiet", "healthy")}) == 3


def test_one_failing_producer_never_aborts_the_pass(clean_registry):
    """run_all's isolation contract must hold in the observer too: a producer that
    raises must not stop later producers from being observed."""

    def boom(_session):
        raise RuntimeError("nope")

    clean_registry.register("boom", boom)
    clean_registry.register("after", lambda _s: [_card(key="after")])

    outcomes = {o.name: o for o in observe_producers(object())}
    assert outcomes["boom"].outcome == "error"
    assert outcomes["after"].outcome == "ok"


def test_the_observer_enters_the_wal_guard_at_the_same_scope_run_all_does(
    clean_registry, monkeypatch
):
    """The scope of ``_wal_guard`` is part of what this observer MIRRORS, not an
    implementation detail — and it is the half a "same isolation contract" docstring
    cannot pin by itself.

    Entering the guard is what runs ``_drain_pending``, i.e. what closes whatever scan
    the PREVIOUS producer left mid-flight. ``run_all_bounded`` enters it once per
    producer for exactly that reason (PR-D / W1 finding #1). An observer that entered
    it once for the WHOLE loop would still surface the same cards, still isolate the
    same exceptions, and still pass every other test in this file — while every
    ``elapsed_s`` it reports measured a different pinning regime than production runs
    under. A diagnostic quietly describing code that is not the code is worse than no
    diagnostic.

    BEHAVIOURAL ON PURPOSE. A source grep for ``with _wal_guard`` inside the loop is
    satisfied by the comment above that line, which is precisely the text a future
    session needs to read before deciding the scope was arbitrary.
    """
    from src.briefing import registry as REG

    entries: list[int] = []
    real = REG._wal_guard

    @contextmanager
    def _counting(session):
        entries.append(1)
        with real(session):
            yield

    monkeypatch.setattr(REG, "_wal_guard", _counting)

    clean_registry.register("a", lambda _s: [_card(key="a")])
    clean_registry.register("b", lambda _s: [_card(key="b")])
    clean_registry.register("c", lambda _s: [_card(key="c")])

    observe_producers(object())
    assert sum(entries) == 3, (
        "the guard must be entered once PER PRODUCER; a single entry for the whole "
        "loop leaves each producer's dangling scan pinned across its successors"
    )


def test_observer_surfaced_set_matches_run_all_exactly(clean_registry):
    """The observer must not change WHICH cards the feed surfaces -- it only records
    how each producer got there. run_all itself is never modified; this pins that the
    parallel path stays equivalent (same identities, same order, same dedup belt)."""
    clean_registry.register("a", lambda _s: [_card(key="x"), _card(key="y")])
    clean_registry.register("b", lambda _s: [_card(key="x")])  # exact (type, key) twin
    clean_registry.register("c", lambda _s: [_card(key="z")])

    from src.briefing.registry import run_all

    expected = [(c.type, c.key) for c in run_all(object())]
    surfaced, _suppressed = apply_dedup_belt(observe_producers(object()))
    assert [(c.type, c.key) for _p, c in surfaced] == expected


def test_dedup_belt_reports_suppressed_cards_with_what_they_collided_with(clean_registry):
    """A card dropped by the cross-producer (type, key) belt was genuinely PROPOSED and
    is invisible everywhere else -- it must be reported, with its collision partner."""
    clean_registry.register("first", lambda _s: [_card(key="dup", title="kept")])
    clean_registry.register("second", lambda _s: [_card(key="dup", title="dropped")])

    surfaced, suppressed = apply_dedup_belt(observe_producers(object()))
    assert len(surfaced) == 1
    assert surfaced[0][1].title == "kept"
    assert len(suppressed) == 1
    assert suppressed[0]["producer"] == "second"
    assert suppressed[0]["collided_with"]["producer"] == "first"


def test_non_card_items_are_counted_not_silently_dropped(clean_registry):
    """run_all drops non-Card items silently; the observer counts them, so a producer
    returning the wrong shape is visible rather than looking like partial success."""
    clean_registry.register("mixed", lambda _s: [_card(key="ok"), "not a card", None])
    outcomes = {o.name: o for o in observe_producers(object())}
    assert outcomes["mixed"].cards_proposed == 1
    assert outcomes["mixed"].non_card_items == 2


# --------------------------------------------------------------------------- #
#  Dimension 1 -- ARITHMETIC (pure)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [
        ("(42 ÷ 7) ÷ (30 ÷ 30) = ×6.0", True),
        ("(42 ÷ 7) ÷ (30 ÷ 30) = ×6", True),  # rounded display still reproduces
        ("121 ÷ 300 = 40%", True),  # percent form, rounded
        ("10 + 5 = 15", True),
    ],
)
def test_real_arithmetic_reproduces(value, expected):
    row = check_math_row({"label": "l", "value": value})
    assert row["checkable"] is True
    assert row["reproduced"] is expected


def test_wrong_arithmetic_is_reported_as_not_reproduced():
    """A card whose math does NOT support its claim must fail loudly, not pass."""
    row = check_math_row({"label": "l", "value": "121 ÷ 300 = 90%"})
    assert row["checkable"] is True
    assert row["reproduced"] is False
    assert row["delta"] > row["tolerance"]


@pytest.mark.parametrize(
    "value",
    [
        "+150",  # a bare quantity
        "✓",  # a flag
        "25% – 60%",  # a range
        "> 7",  # a threshold
        "5 · 2 ✓",  # "·" is a SEPARATOR here, not multiplication -- never guess
    ],
)
def test_unverifiable_rows_say_so_and_are_never_counted_as_a_pass(value):
    """NEGATIVE SPACE: a row that cannot be mechanically recomputed must report
    checkable:false WITH a reason -- never a silent pass. 'reproduced' must be absent
    entirely, so no caller can read an unverified row as verified."""
    row = check_math_row({"label": "l", "value": value})
    assert row["checkable"] is False
    assert row["reason"]
    assert "reproduced" not in row


def test_division_by_zero_is_not_checkable_rather_than_crashing():
    row = check_math_row({"label": "l", "value": "5 ÷ 0 = 3"})
    assert row["checkable"] is False
    assert "reproduced" not in row


@pytest.mark.parametrize(
    "hostile",
    [
        '__import__("os").system("echo pwned") = 1',
        "open('/etc/passwd').read() = 1",
        "(1).__class__.__bases__ = 1",
        "9" * 400 + " = 1",  # absurd literal
    ],
)
def test_hostile_math_values_can_never_execute_anything(hostile):
    """The evaluator is AST-whitelisted and gated by a character allowlist, so a
    malformed or hostile math row can only ever be reported not-checkable."""
    row = check_math_row({"label": "l", "value": hostile})
    assert row["checkable"] is False


def test_malformed_math_rows_degrade_instead_of_raising():
    for bad in (None, "a string", 42, [], {"label": "x"}):
        row = check_math_row(bad)
        assert row["checkable"] is False
        assert row["reason"]


def test_check_trigger_counts_checkable_and_unverifiable_separately():
    trig = {
        "plain": "p",
        "math": [
            {"label": "a", "value": "10 ÷ 2 = 5"},  # checkable, reproduces
            {"label": "b", "value": "10 ÷ 2 = 9"},  # checkable, fails
            {"label": "c", "value": "✓"},  # not checkable
        ],
    }
    out = check_trigger(trig)
    assert out["present"] is True
    assert out["rows_total"] == 3
    assert out["checkable_n"] == 2
    assert out["not_checkable_n"] == 1
    assert out["reproduced_n"] == 1
    assert out["failed_n"] == 1
    # An unverifiable row must never inflate the reproduced count.
    assert out["reproduced_n"] + out["failed_n"] == out["checkable_n"]


def test_absent_trigger_is_reported_as_absent_not_as_a_pass():
    out = check_trigger(None)
    assert out["present"] is False
    assert out["reproduced_n"] == 0
    assert out["checkable_n"] == 0
    assert out["note"]


# --------------------------------------------------------------------------- #
#  Dimension 4 -- NON-FABRICATION (pure)
# --------------------------------------------------------------------------- #


def test_banned_key_walk_flags_keys_but_not_values():
    """KEYS are walked. A banned fragment appearing as a VALUE is the convention the
    producers already follow ({"metric": "share_zscore"}) and must NOT be flagged --
    flagging it would make the check cry wolf on correct code."""
    found = walk_banned_keys(
        {"trust_score": 1, "nested": [{"metric": "share_zscore", "value": 2}]}
    )
    paths = {f["path"] for f in found}
    assert "trust_score" in paths
    assert not any("metric" in p for p in paths)


def test_banned_key_walk_reports_path_for_review():
    found = walk_banned_keys({"a": {"b": {"quality_grade": 1}}})
    assert found and found[0]["path"] == "a.b.quality_grade"


def test_missing_method_or_caveat_is_reported():
    ok = non_fabrication_checks(_card().to_dict())
    assert ok["method_present"] and ok["caveat_present"] and ok["passes"]

    bad = _card().to_dict()
    bad["method"] = "  "
    out = non_fabrication_checks(bad)
    assert out["method_present"] is False
    assert out["passes"] is False


def test_absent_n_is_distinguishable_from_a_malformed_n():
    """A whole-corpus card legitimately has no n; that is a DIFFERENT fact from a card
    whose n is the wrong type. Merging them would hide a real defect."""
    absent = non_fabrication_checks(_card(n=None).to_dict())
    assert absent["n_state"] == "absent"

    present = non_fabrication_checks(_card(n=12).to_dict())
    assert present["n_state"] == "present"

    malformed = _card().to_dict()
    malformed["n"] = "twelve"
    assert non_fabrication_checks(malformed)["n_state"] == "malformed"


# --------------------------------------------------------------------------- #
#  Contract / honesty guards
# --------------------------------------------------------------------------- #


def test_status_tallies_are_objects_never_dict_keys():
    """A status VALUE may legitimately contain a banned fragment ('degraded' contains
    'grade') while a KEY may not -- so per-status tallies must be a list of objects.
    This pins the shape so a future refactor to a dict cannot silently reintroduce it."""
    from src.briefing.card_audit import _tally

    out = _tally(["ok", "degraded", "ok"], "outcome")
    assert isinstance(out, list)
    assert {"outcome": "ok", "n": 2} in out
    assert {"outcome": "degraded", "n": 1} in out
    # The banned fragment rides as a VALUE and is therefore not flagged.
    assert walk_banned_keys(out) == []


def test_scaffolding_emits_no_score_shaped_keys():
    """The audit's OWN keys must be clean, independent of what a producer emits."""
    trig = check_trigger({"plain": "p", "math": [{"label": "a", "value": "4 ÷ 2 = 2"}]})
    assert walk_banned_keys(trig) == []
    assert walk_banned_keys(non_fabrication_checks(_card().to_dict())["banned_key_matches"]) == []
    assert walk_banned_keys(ProducerOutcome(name="p", outcome="ok").to_dict()) == []


def test_depths_and_schema_are_stable_identifiers():
    assert SCHEMA == "oo-card-audit-1"
    assert DEPTHS == ("summary", "standard", "full")


def test_report_refuses_an_unknown_depth():
    from src.briefing.card_audit import card_audit_report

    with pytest.raises(ValueError, match="depth must be one of"):
        card_audit_report(object(), depth="everything")


def test_summary_depth_notice_states_no_content_and_deeper_states_content():
    """The payload must tell the operator what the file contains before they share it."""
    from src.briefing.card_audit import _content_notice

    assert _content_notice("summary")["contains_article_content"] is False
    for deep in ("standard", "full"):
        notice = _content_notice(deep)
        assert notice["contains_article_content"] is True
        assert "CONTAINS CORPUS CONTENT" in notice["statement"]


# --------------------------------------------------------------------------- #
#  Non-finite floats -- the field defect that silently killed this whole member.
# --------------------------------------------------------------------------- #


def test_non_finite_values_are_nulled_and_named_so_the_report_survives():
    """An inf anywhere in a producer's payload must not cost the whole 112s report.

    The operator's 2026-08-08 bundle carried ``card-audit.json.error.txt`` reading
    "Out of range float values are not JSON compliant: -inf" -- the member had been
    dead since at least 2026-08-06. Surviving is half the fix; NAMING the field is
    the other half, or the repair becomes the hiding place for the producer bug.
    """
    import json

    from src.briefing.card_audit import _sanitise_non_finite

    out = _sanitise_non_finite(
        {
            "cards": [{"trigger": {"ratio": float("-inf")}, "title": "t"}],
            "summary": {"mean": float("inf"), "nan": float("nan"), "real": 1.5},
        }
    )

    # It serialises AT ALL -- json.dumps(allow_nan=False) is what FastAPI's
    # JSONResponse uses, and is exactly what was raising in the field.
    json.dumps(out, allow_nan=False)

    assert out["cards"][0]["trigger"]["ratio"] is None
    assert out["summary"]["mean"] is None
    assert out["summary"]["nan"] is None
    assert out["summary"]["real"] == 1.5  # a real measurement is untouched
    assert out["non_finite"]["n"] == 3
    assert set(out["non_finite"]["fields"]) == {
        "cards[0].trigger.ratio",
        "summary.mean",
        "summary.nan",
    }


def test_a_clean_report_gains_no_non_finite_block():
    """The negative-space twin: an honest report must not sprout a defect marker."""
    from src.briefing.card_audit import _sanitise_non_finite

    out = _sanitise_non_finite({"summary": {"n": 3, "rate": 0.5}, "cards": [{"k": None}]})
    assert "non_finite" not in out
    assert out == {"summary": {"n": 3, "rate": 0.5}, "cards": [{"k": None}]}


def test_naming_is_bounded_but_the_count_stays_exact():
    """Naming thousands of paths would bloat the member this exists to save."""
    from src.briefing.card_audit import _NON_FINITE_NAME_LIMIT, _sanitise_non_finite

    n = _NON_FINITE_NAME_LIMIT + 17
    out = _sanitise_non_finite({"rows": [{"v": float("inf")} for _ in range(n)]})
    assert out["non_finite"]["n"] == n  # exact, never capped
    assert len(out["non_finite"]["fields"]) == _NON_FINITE_NAME_LIMIT
    assert out["non_finite"]["named_truncated"] == 17
