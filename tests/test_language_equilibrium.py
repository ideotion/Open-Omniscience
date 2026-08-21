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
from tests.js_source_helper import app_js

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
    app = app_js()
    assert "/api/scheduler/equilibrium" in app and "_renderEquilibrium(" in app, (
        "the Coverage subtab must surface the equilibrium state (read-only)"
    )


# --- ONE bucket key on both sides of the comparison -------------------------- #
#
# Article.language is stored RAW from trafilatura's <html lang> read, so most
# major outlets arrive region-tagged. Bucketing on .strip().lower() split English
# across en / en-us / en_us and compared a FRAGMENT of it against the whole
# target, silently under-correcting the lever.

def test_region_subtags_are_one_language_not_three(db):
    """The bug, at the corpus end: en / en-US / EN_us are English."""
    src = Source(name="s", domain="s.example", enabled=True)
    db.add(src)
    db.flush()
    for i, lang in enumerate(["en", "en-US", "EN_us", "en-GB", "fr", "fr-CA"]):
        _article(db, src.id, i, lang)
    db.commit()
    shares = EQ.corpus_language_shares(db)
    assert set(shares) == {"en", "fr"}, "region subtags must not become languages"
    assert shares["en"] == pytest.approx(4 / 6)
    assert shares["fr"] == pytest.approx(2 / 6)


def test_the_lever_paces_against_all_of_a_language_not_one_spelling(db):
    """The bug's CONSEQUENCE, which is what actually cost the operator.

    A corpus 60% English arriving as en/en-US/en_us, targeted at 30%: before this
    the lever saw only the 35% 'en' bucket and deferred English on 14.3% of passes
    where 50.0% is correct -- a 3.5x under-correction that grows with how
    region-tagged the corpus is."""
    src = Source(name="s", domain="s.example", enabled=True)
    db.add(src)
    db.flush()
    i = 0
    for lang, n in [("en", 35), ("en-US", 20), ("en_us", 5), ("fr", 25), ("de", 15)]:
        for _ in range(n):
            _article(db, src.id, i, lang)
            i += 1
    db.commit()
    shares = EQ.corpus_language_shares(db)
    assert shares["en"] == pytest.approx(0.60), "all three spellings are English"
    pace = EQ.language_pace(shares, {"en": 0.30, "fr": 0.35, "de": 0.35})
    assert pace["en"] == pytest.approx(0.50, abs=0.01), (
        "pace must be target/actual over the WHOLE language; 0.857 is the "
        "pre-fix figure computed against the 'en' spelling alone"
    )


def test_a_target_written_with_a_region_subtag_matches():
    """The other side of the comparison. Normalising only the corpus would leave an
    operator who writes 'en-US' targeting a bucket that can never exist -- and the
    bundled PRESETS are keyed on bare codes, so they could never match either."""
    assert EQ.normalize_target({"en-US": 1}) == {"en": 1.0}
    assert EQ.normalize_target({"en": 1, "en-GB": 1}) == {"en": 1.0}, "same language, summed"
    pace = EQ.language_pace({"en": 0.8}, {"en-US": 0.5, "fr": 0.5})
    assert pace["en"] == pytest.approx(0.5 / 0.8, abs=0.01)


def test_genuinely_different_languages_are_never_merged(db):
    """The negative-space twin. An over-eager key would collapse distinct languages,
    which is the same class of defect pointing the other way -- and unlike the
    original bug it would be invisible, because the shares would still sum to 1."""
    src = Source(name="s", domain="s.example", enabled=True)
    db.add(src)
    db.flush()
    # en/eo/es share a first letter; zh-Hans/zh-Hant share a language; pt/pt-BR too.
    for i, lang in enumerate(["en", "eo", "es", "et", "zh-Hans", "zh-Hant", "pt", "pt-BR"]):
        _article(db, src.id, i, lang)
    db.commit()
    shares = EQ.corpus_language_shares(db)
    assert {"en", "eo", "es", "et"} <= set(shares), "distinct languages stay distinct"
    for lang in ("en", "eo", "es", "et"):
        assert shares[lang] == pytest.approx(1 / 8)
    # ...while script subtags of ONE language merge, like region subtags do.
    assert shares["zh"] == pytest.approx(2 / 8)
    assert shares["pt"] == pytest.approx(2 / 8)


def test_unknown_stays_the_sentinel_for_absent_language(db):
    """normalize_lang returns "" for NULL/blank, which must not become a bucket
    named "" -- 'unknown' is a real, countable category the operator sees."""
    src = Source(name="s", domain="s.example", enabled=True)
    db.add(src)
    db.flush()
    for i, lang in enumerate([None, "", "   ", "en"]):
        _article(db, src.id, i, lang)
    db.commit()
    shares = EQ.corpus_language_shares(db)
    assert shares["unknown"] == pytest.approx(3 / 4)
    assert "" not in shares


def test_the_pace_actually_reaches_a_region_tagged_source(db):
    """THE THIRD KEY SPACE, and the reason a half-fix was worse than none.

    Normalising only the two sides of the SHARE comparison left equilibrium_filter --
    which is what applies the pace -- keying sources on the old `.strip().lower()`.
    A region-tagged source therefore missed pace["en"] and stayed 100% exempt, while
    the bare-spelled sources of the same language absorbed a correction that had just
    become 3.5x larger on their behalf. Measured over 20,000 passes before this was
    fixed: source "en" deferred 49.5%, source "en-US" deferred 0.0%."""
    import random
    from datetime import UTC, datetime, timedelta

    class _St:
        last_checked_at = datetime.now(UTC) - timedelta(minutes=5)   # fresh: pace applies

    class _S:
        def __init__(self, sid, lang):
            self.id, self.language = sid, lang

    sources = [_S(1, "en"), _S(2, "en-US"), _S(3, "EN_us"), _S(4, "en-GB")]
    state = {s.id: _St() for s in sources}
    kept_by_lang: dict[str, int] = {}
    passes = 4000
    rng = random.Random(1234)
    for _ in range(passes):
        kept, _deferred = EQ.equilibrium_filter(
            sources, pace={"en": 0.5}, fetch_state=state, rng=rng
        )
        for s in kept:
            kept_by_lang[s.language] = kept_by_lang.get(s.language, 0) + 1
    for lang in ("en", "en-US", "EN_us", "en-GB"):
        rate = kept_by_lang.get(lang, 0) / passes
        assert 0.44 < rate < 0.56, (
            f"{lang!r} kept {rate:.1%} of passes; pace 0.5 must reach EVERY spelling of "
            "English, or the bare-spelled sources carry the whole correction alone"
        )


def test_an_untargeted_language_is_still_never_paced(db):
    """The twin. Normalising the source key must not sweep an unrelated language into
    a target it was never in -- that would be the same defect pointing outward."""
    import random
    from datetime import UTC, datetime, timedelta

    class _St:
        last_checked_at = datetime.now(UTC) - timedelta(minutes=5)

    class _S:
        def __init__(self, sid, lang):
            self.id, self.language = sid, lang

    sources = [_S(1, "fr-CA"), _S(2, "de"), _S(3, None)]
    state = {s.id: _St() for s in sources}
    rng = random.Random(7)
    for _ in range(500):
        kept, deferred = EQ.equilibrium_filter(
            sources, pace={"en": 0.1}, fetch_state=state, rng=rng
        )
        assert deferred == 0 and len(kept) == 3, "only the targeted language may be paced"
