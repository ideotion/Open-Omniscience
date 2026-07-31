"""
The card catalog, its safe ranges, and the per-producer switch (PR-7).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Rulings 1/2/3 (2026-07-31): every family accessible and tweakable, ``overtold``
wired end to end as the pattern, and every tunable carrying a documented safe
range that is STATED rather than silently applied.

The honesty fence is the part worth testing hardest. A tunable an operator can
drag below the point where the underlying test still means something would let
them manufacture a signal out of noise — so the floors are asserted directly,
in both directions: the clamp holds, AND it says why.
"""

from __future__ import annotations

import pytest

from src.briefing import catalog as C
from src.briefing.card import BUCKETS, BUCKET_LABELS


# --------------------------------------------------------------------------- #
#  Completeness: the catalog must describe the app that exists
# --------------------------------------------------------------------------- #
def test_every_registered_producer_is_catalogued():
    """A producer missing from the catalog is invisible in Settings — the user
    could never switch it off. Pinned against the REGISTRY rather than a count,
    so adding a producer without cataloguing it fails here."""
    from src.briefing.producers import _DEFAULT_PRODUCERS
    from src.briefing.recipes import RECIPE_PRODUCERS

    registered = {n for n, _ in _DEFAULT_PRODUCERS} | {n for n, _ in RECIPE_PRODUCERS}
    catalogued = {s.name for s in C.CARD_CATALOG}
    assert registered - catalogued == set(), "producers missing from the catalog"
    assert catalogued - registered == set(), "catalog lists producers that do not exist"


def test_all_eight_families_are_present_and_ordered():
    """Ruling 1: all 8 families accessible. The order mirrors card.BUCKETS so
    Settings and Home agree on how the families are arranged."""
    assert set(C.FAMILY_ORDER) == set(BUCKETS)
    assert C.FAMILY_ORDER == BUCKETS
    families = [f for f, specs in C.by_family() if specs]
    assert len(families) == 8, families
    for family in families:
        assert family in BUCKET_LABELS, f"{family} has no display label"


def test_every_producer_has_a_family_label_and_description():
    for spec in C.CARD_CATALOG:
        assert spec.family in BUCKETS, f"{spec.name}: unknown family {spec.family!r}"
        assert spec.label and not spec.label.endswith("."), spec.name
        assert spec.description.endswith("."), f"{spec.name}: description reads as a sentence"
        assert spec.name not in spec.label.lower(), (
            f"{spec.name}: the label should be human, not the identifier"
        )


def test_the_overtold_family_is_wired_end_to_end():
    """Ruling 2: overtold FIRST, as the reusable pattern — so every one of its
    producers must actually carry tunables, not just appear in the list."""
    overtold = [s for s in C.CARD_CATALOG if s.family == "overtold"]
    assert len(overtold) == 4
    for spec in overtold:
        assert spec.tunables, f"{spec.name} is in the reference family but has no tunables"
        assert any(t.key == "max_cards" for t in spec.tunables)


# --------------------------------------------------------------------------- #
#  The safe ranges themselves
# --------------------------------------------------------------------------- #
def test_every_tunable_is_internally_consistent():
    for spec in C.CARD_CATALOG:
        for t in spec.tunables:
            assert t.lo <= t.default <= t.hi, f"{spec.name}.{t.key}: default outside its range"
            assert t.lo < t.hi, f"{spec.name}.{t.key}: empty range"
            assert t.impact, f"{spec.name}.{t.key}: a tunable with no stated impact"
            assert t.kind in ("int", "float")


def test_a_floor_that_prevents_a_fabricated_signal_states_its_reason():
    """Ruling 3: never a silent clamp. A bound that exists to stop an
    underpowered claim must SAY so — an unexplained limit reads as arbitrary,
    and an operator cannot weigh a restriction whose reason is hidden."""
    # the statistical floor
    z = next(t for t in C.spec_for("flooded_topic").tunables if t.key == "z_min")
    assert z.lo == pytest.approx(1.96), "the p<0.05 critical value is the floor"
    assert "1.96" in z.floor_reason and "p<0.05" in z.floor_reason
    # every distinct-sources floor
    for name in ("echo_chamber", "source_laundering", "copypasta"):
        t = next(x for x in C.spec_for(name).tunables if x.key == "min_sources")
        assert t.lo >= 2, f"{name}: one source cannot corroborate itself"
        assert t.floor_reason, f"{name}: the floor must say why it is there"


def test_the_operator_may_always_tighten_but_never_loosen_past_the_floor():
    """The asymmetry that makes the fence honest: stricter is unbounded (up to
    hi), looser stops at the point the evidence stops supporting the claim."""
    for name in ("echo_chamber", "source_laundering", "flooded_topic", "copypasta"):
        for t in C.spec_for(name).tunables:
            stricter, _ = C.clamp_settings(name, {t.key: t.hi})
            assert stricter[t.key] == pytest.approx(t.hi), f"{name}.{t.key} may be tightened"
            loose, notes = C.clamp_settings(name, {t.key: t.lo - 1})
            assert loose[t.key] == pytest.approx(t.lo), f"{name}.{t.key} must stop at its floor"
            assert notes, f"{name}.{t.key}: the clamp must be reported, never silent"


# --------------------------------------------------------------------------- #
#  clamp_settings: correct AND talkative
# --------------------------------------------------------------------------- #
def test_clamping_reports_what_it_changed():
    values, notes = C.clamp_settings("flooded_topic", {"z_min": 0.1})
    assert values["z_min"] == pytest.approx(1.96)
    assert len(notes) == 1
    note = notes[0]
    assert note["given"] == 0.1 and note["used"] == pytest.approx(1.96)
    assert note["producer"] == "flooded_topic" and note["key"] == "z_min"
    assert note["reason"], "a clamp with no reason is a silent clamp with extra steps"


def test_an_unknown_key_or_producer_is_dropped_with_a_note_never_guessed():
    values, notes = C.clamp_settings("flooded_topic", {"min_sources": 5})
    assert values == {}, "min_sources is not a setting of this producer"
    assert notes and "not a setting" in notes[0]["reason"]
    values, notes = C.clamp_settings("no_such_producer", {"x": 1})
    assert values == {} and notes


@pytest.mark.parametrize("bad", ["abc", None, [], {}, float("nan"), float("inf")])
def test_a_non_number_is_refused_not_coerced(bad):
    """Negative space: a value that is not a number must not become one. NaN and
    inf are numbers to Python and would sail past a naive float() check, then
    poison every comparison downstream."""
    values, notes = C.clamp_settings("echo_chamber", {"min_sources": bad})
    assert values == {}, f"{bad!r} must not survive as a threshold"
    assert notes and notes[0]["reason"] == "not a number"


def test_ints_stay_ints_and_floats_stay_floats():
    v, _ = C.clamp_settings("echo_chamber", {"min_sources": 4.7})
    assert isinstance(v["min_sources"], int) and v["min_sources"] == 5
    v, _ = C.clamp_settings("flooded_topic", {"min_share": 0.4})
    assert isinstance(v["min_share"], float)


# --------------------------------------------------------------------------- #
#  Defaults must not change behaviour
# --------------------------------------------------------------------------- #
def test_untouched_settings_reproduce_the_shipped_defaults():
    """The whole point of making thresholds tunable is that NOT tuning them
    changes nothing. Pinned against the analytics functions' own signatures, so
    a default that drifts apart from the code it feeds fails here."""
    import inspect

    from src.analytics.concentration import find_flooded_topics
    from src.analytics.copypasta import find_copypasta
    from src.analytics.laundering import find_source_laundering

    pairs = [
        ("flooded_topic", find_flooded_topics,
         ("recent_days", "baseline_days", "min_recent_articles", "min_share", "z_min")),
        ("copypasta", find_copypasta, ("recent_days", "k", "min_sources")),
        ("source_laundering", find_source_laundering, ("min_sources", "min_articles")),
    ]
    for name, fn, keys in pairs:
        sig = inspect.signature(fn).parameters
        defaults = C.defaults_for(name)
        for key in keys:
            assert defaults[key] == pytest.approx(sig[key].default), (
                f"{name}.{key} default drifted from {fn.__name__}'s own signature"
            )


def test_settings_for_falls_back_to_defaults_when_settings_are_unreadable(monkeypatch):
    """Fail-safe: a settings problem must never blank a Lead."""
    import src.config.app_settings as A

    monkeypatch.setattr(A, "load_settings", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert C.settings_for("echo_chamber") == C.defaults_for("echo_chamber")
    assert C.is_disabled("echo_chamber") is False, "unreadable settings must not disable a Lead"


# --------------------------------------------------------------------------- #
#  The per-producer switch (ruling 1: every family tweakable)
# --------------------------------------------------------------------------- #
def test_a_disabled_producer_is_not_run_at_all(monkeypatch):
    """Switching a Lead off must SKIP it, not run it and discard the cards --
    otherwise turning something off would still cost the pass its full scan."""
    from src.briefing import registry
    from src.briefing.card import Card

    ran: list[str] = []

    def _mk(name):
        def _producer(_session):
            ran.append(name)
            return [Card(type=name, title="t", summary="s", bucket="context",
                         method="counted", caveat="a test fixture", key=name)]
        return _producer

    monkeypatch.setattr(registry, "_REGISTRY", [("kept", _mk("kept")), ("off", _mk("off"))])
    monkeypatch.setattr(registry, "_disabled_names", lambda: frozenset({"off"}))
    cards = registry.run_all(object())
    assert ran == ["kept"], "the disabled producer must never be called"
    assert [c.type for c in cards] == ["kept"]


def test_the_legacy_recipes_disabled_key_still_switches_a_producer_off():
    """Back-compat: the widened mechanism reads the old key too, so an operator
    who switched a recipe off before this field existed keeps that choice."""
    from src.config.app_settings import AppSettings

    s = AppSettings(recipes_disabled=["promises_due"])
    assert s.cards_disabled == ["promises_due"], "the legacy key must seed the new one"
