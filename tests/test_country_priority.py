"""Scheduler: opt-in per-country PRIORITY LADDER (orders, never excludes) + the
will_process_this_run latent-bug fix (a default cap=0 wrongly reported 0).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The interleave tests are pure (SimpleNamespace stubs + a seeded RNG). The settings/API
tests use an isolated data dir / in-memory SQLite (conftest provides both).
"""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from src.scheduler.runner import stratified_interleave


def _s(i, lang, tags, country=None):
    return SimpleNamespace(id=i, language=lang, tags=tags, country=country)


# --------------------------------------------------------------------------- #
# the priority ladder (pure interleave)


def test_country_priority_lifts_chosen_countries_first_without_excluding():
    src = [
        _s(1, "en", "news", "us"),
        _s(2, "fr", "news", "fr"),
        _s(3, "de", "news", "de"),
        _s(4, "en", "sport", "us"),
        _s(5, "es", "news", "es"),
    ]
    out = stratified_interleave(
        src, rng=random.Random(0), country_priority={"us": 5, "fr": 3}
    )
    # Nobody is dropped (ordering != exclusion).
    assert {s.id for s in out} == {1, 2, 3, 4, 5}
    order = [s.country for s in out]
    # Every us source precedes every fr source, and both precede the unlisted (weight-0)
    # countries — the bandwidth ladder decides what runs FIRST, never what runs at all.
    us_last = max(i for i, c in enumerate(order) if c == "us")
    fr_first = min(i for i, c in enumerate(order) if c == "fr")
    fr_last = max(i for i, c in enumerate(order) if c == "fr")
    other_first = min(i for i, c in enumerate(order) if c not in ("us", "fr"))
    assert us_last < fr_first and fr_last < other_first  # us before fr before the rest


def test_empty_priority_is_byte_identical_to_the_plain_interleave():
    src = [_s(i, "en" if i % 2 else "fr", "news", "us" if i % 3 else "gb") for i in range(12)]
    plain = stratified_interleave(list(src), rng=random.Random(7))
    with_none = stratified_interleave(list(src), rng=random.Random(7), country_priority=None)
    with_empty = stratified_interleave(list(src), rng=random.Random(7), country_priority={})
    assert [s.id for s in plain] == [s.id for s in with_none] == [s.id for s in with_empty]


def test_priority_is_a_stable_sort_preserving_fair_order_within_a_weight():
    # Within the SAME priority (or the unlisted weight-0 group), the fair stratified order
    # is preserved (a stable sort), so the ladder never scrambles the within-weight fairness.
    src = [_s(i, "en", f"tag{i}", "us") for i in range(6)]  # all us, all equal weight
    base = stratified_interleave(list(src), rng=random.Random(3))
    laddered = stratified_interleave(list(src), rng=random.Random(3), country_priority={"us": 9})
    assert [s.id for s in base] == [s.id for s in laddered]  # all equal weight -> unchanged


# --------------------------------------------------------------------------- #
# settings load / save round-trip


def test_settings_round_trip_and_coercion():
    from src.scheduler.settings import SchedulerSettings, load_settings, save_settings

    assert SchedulerSettings().country_priority == {}  # default OFF
    # A map with a malformed/negative entry -> cleaned to lowercased {cc: float>0}.
    save_settings({"country_priority": {"US": 5, "Fr": 2.5, "de": 0, "xx": "bad"}})
    loaded = load_settings()
    assert loaded.country_priority == {"us": 5.0, "fr": 2.5}  # 0 and non-numeric dropped
    # Turn it OFF again.
    save_settings({"country_priority": {}})
    assert load_settings().country_priority == {}


def test_settings_rejects_a_non_dict_priority():
    from src.scheduler.settings import SchedulerSettingsError, save_settings

    with pytest.raises(SchedulerSettingsError):
        save_settings({"country_priority": [1, 2, 3]})


# --------------------------------------------------------------------------- #
# the will_process_this_run latent-bug fix


def test_targets_will_process_equals_matched_when_uncapped():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.scheduler import scheduler_targets
    from src.database.models import Base, Source

    # cap=0 (unbounded) is the DEFAULT (save_settings's range validator now correctly
    # accepts 0 too, see tests/test_no_source_cap.py -- audit fix 2026-07-17); relying on
    # the default here still exercises exactly the case the old min(matched, 0)
    # mis-reported as 0.
    eng = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, future=True)()
    for i in range(3):
        db.add(Source(name=f"S{i}", domain=f"s{i}.test", rss_url=f"https://s{i}.test/rss",
                      enabled=True))
    db.commit()

    out = scheduler_targets(db=db)
    # With cap=0 (unbounded) every matched source runs — the OLD min(matched, 0) reported 0.
    assert out["will_process_this_run"] == out["matched"] == 3
