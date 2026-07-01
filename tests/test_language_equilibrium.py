"""Optional per-language cadence lever (src.scheduler.equilibrium + settings).

Pins the honest contract: DEFAULT OFF (empty target = identity), a cadence
multiplier never a score, and — the load-bearing guarantee — it NEVER starves a
source (never-fetched and cap-stale sources are always kept). Pure + in-memory
ORM, so it runs in the sandbox as well as CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.scheduler import equilibrium as EQ
from src.scheduler import settings as S

# --- pure: normalize_target / language_pace --------------------------------- #

def test_normalize_target_shares_and_off():
    assert EQ.normalize_target({"en": 3, "fr": 1}) == {"en": 0.75, "fr": 0.25}
    assert EQ.normalize_target({}) == {}
    assert EQ.normalize_target(None) == {}
    assert EQ.normalize_target({"en": 0, "fr": -2, "xx": "bad"}) == {}  # all invalid → OFF


def test_language_pace_over_under_and_floor():
    # Off when no target.
    assert EQ.language_pace({"en": 0.9}, {}) == {}
    # en is over target (0.8 corpus vs 0.5 target) → slowed to 0.5/0.8; fr under
    # target → full cadence 1.0; a targeted-but-absent language → 1.0.
    pace = EQ.language_pace({"en": 0.8, "fr": 0.1}, {"en": 0.5, "fr": 0.3, "ar": 0.2})
    assert pace["en"] == pytest.approx(0.5 / 0.8)
    assert pace["fr"] == 1.0 and pace["ar"] == 1.0
    # Floor clamps a hugely over-represented language.
    pace2 = EQ.language_pace({"en": 0.99}, {"en": 0.01, "ar": 0.99}, floor=0.2)
    assert pace2["en"] == 0.2  # would be ~0.01 without the floor


# --- pure: equilibrium_filter (never starves) ------------------------------- #

def _src(i, lang, checked, *, rss=True):
    st = SimpleNamespace(last_checked_at=checked) if checked is not None else None
    return SimpleNamespace(id=i, language=lang, rss_url="x" if rss else None), st


def test_filter_off_is_identity():
    srcs = [SimpleNamespace(id=1, language="en", rss_url="x")]
    kept, deferred = EQ.equilibrium_filter(srcs, pace={}, fetch_state={})
    assert kept == srcs and deferred == 0


def test_filter_never_starves_never_fetched_or_cap_stale():
    now = datetime.now(UTC)
    # en is heavily paced (0.2), but these must ALWAYS be kept:
    s_never, _ = _src(1, "en", None)  # never fetched → first reach kept
    s_stale, st_stale = _src(2, "en", now - timedelta(hours=99))  # older than cap
    state = {2: st_stale}
    kept, deferred = EQ.equilibrium_filter(
        [s_never, s_stale], pace={"en": 0.2}, fetch_state=state,
        now=now, rng=random.Random(0),
    )
    assert deferred == 0 and len(kept) == 2  # never starved


def test_filter_defers_recent_over_represented_but_keeps_others():
    now = datetime.now(UTC)
    # 40 recently-fetched en sources (pace 0.5) + 5 fr sources (pace 1.0, kept).
    en = []
    state = {}
    for i in range(40):
        s, st = _src(i, "en", now - timedelta(minutes=10))
        en.append(s)
        state[i] = st
    fr = []
    for i in range(100, 105):
        s, st = _src(i, "fr", now - timedelta(minutes=10))
        fr.append(s)
        state[i] = st
    kept, deferred = EQ.equilibrium_filter(
        en + fr, pace={"en": 0.5, "fr": 1.0}, fetch_state=state,
        now=now, rng=random.Random(1),
    )
    kept_langs = [s.language for s in kept]
    assert kept_langs.count("fr") == 5  # under-target language never deferred
    assert 0 < deferred < 40  # some en re-checks deferred, never all
    assert len(kept) + deferred == 45


# --- corpus_language_shares (real in-memory ORM) ---------------------------- #

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _article(session, src_id, i, lang):
    session.add(Article(
        url=f"https://x/{i}", canonical_url=f"https://x/{i}",
        source_id=src_id, content="body", hash=f"h{i}", language=lang,
    ))


def test_corpus_language_shares_counts_and_unknown(db):
    src = Source(name="s", domain="s.example", enabled=True)
    db.add(src)
    db.flush()
    for i in range(7):
        _article(db, src.id, i, "en")
    for i in range(10, 13):
        _article(db, src.id, i, "ar")
    _article(db, src.id, 99, None)  # NULL → 'unknown'
    db.commit()
    shares = EQ.corpus_language_shares(db)
    assert shares["en"] == pytest.approx(7 / 11)
    assert shares["ar"] == pytest.approx(3 / 11)
    assert shares["unknown"] == pytest.approx(1 / 11)


# --- settings: opt-in, validated, default OFF ------------------------------- #

def test_settings_default_off_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_settings_path", lambda: tmp_path / "sched.json")
    assert S.load_settings().language_equilibrium == {}  # default OFF
    saved = S.save_settings({"language_equilibrium": {"en": 2, "FR": 1, "bad": 0},
                             "equilibrium_floor": 0.3})
    assert saved.language_equilibrium == {"en": 2.0, "fr": 1.0}  # cleaned, lowercased
    assert saved.equilibrium_floor == 0.3
    assert S.load_settings().language_equilibrium == {"en": 2.0, "fr": 1.0}


def test_settings_reject_bad_target_and_floor(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_settings_path", lambda: tmp_path / "sched.json")
    with pytest.raises(S.SchedulerSettingsError):
        S.save_settings({"language_equilibrium": "not-a-dict"})
    with pytest.raises(S.SchedulerSettingsError):
        S.save_settings({"equilibrium_floor": 5})  # out of [0,1]


def test_presets_are_documented_suggestions_summing_near_one():
    for name, dist in EQ.PRESETS.items():
        assert dist, name
        # Top-N subsets (the long tail is honestly omitted) that normalize_target
        # renormalizes at use — so they should be a substantial, not-over-1 mass.
        assert 0.5 <= sum(dist.values()) <= 1.05, name
        assert EQ.normalize_target(dist)  # usable as a target


# --- wiring guard: opt-in, non-exclusionary, surfaced ----------------------- #

def test_lever_is_opt_in_non_exclusionary_and_wired():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    # Default OFF on a fresh settings object (byte-identical to the pure rotation).
    assert S.SchedulerSettings().language_equilibrium == {}

    runner = (root / "src/scheduler/runner.py").read_text(encoding="utf-8")
    # The scheduler applies the lever ONLY when a target is set, and fails open.
    assert "settings.language_equilibrium" in runner and "equilibrium_filter(" in runner, (
        "the pass must apply equilibrium_filter, guarded by settings.language_equilibrium"
    )
    assert "must never break a pass" in runner, "the lever must be fail-open (additive)"

    api = (root / "src/api/scheduler.py").read_text(encoding="utf-8")
    assert '"/equilibrium"' in api or "'/equilibrium'" in api, (
        "the read-only /api/scheduler/equilibrium endpoint must exist"
    )
    app_js = (root / "src/static/app.js").read_text(encoding="utf-8")
    assert "/api/scheduler/equilibrium" in app_js and "_renderEquilibrium(" in app_js, (
        "the Coverage subtab must surface the equilibrium state (read-only)"
    )
