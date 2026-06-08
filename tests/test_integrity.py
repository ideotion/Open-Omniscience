"""
Tests for source integrity & anti-amplification (§6 C+D) — the keystone.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The acceptance from ACTION_PLAN Phase C, made concrete: a synthetic 40-puppet flood is
*surfaced and annotated by default* (never silently collapsed); the app *proposes* a
collapse; only on the user's explicit action does the flood stop dominating while a
genuine single source rises; toggling it off reproduces the raw equal counts exactly;
and a test asserts no collapse is applied without an explicit user action — plus the
source profile carries no composite score.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.integrity import collapse as collapse_mod
from src.integrity.actors import corpus_actors
from src.integrity.profile import source_profile

_FLOOD = ("The ministry announced sweeping new measures on Tuesday afternoon, declaring that "
          "the reforms would transform the sector within a year and promising that every region "
          "would benefit from the unprecedented and historic national modernisation programme.")
_ORIGINAL = ("A retired engineer in a small mountain town has spent a decade quietly restoring "
             "the abandoned water mill by hand, and this month it ground its first flour in "
             "seventy years, drawing curious neighbours who had assumed the craft was lost.")


@pytest.fixture()
def flood_corpus(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    now = datetime.now(UTC)
    # 40 puppet sources, each posting the identical flood text within a tight window.
    for i in range(40):
        src = Source(name=f"puppet{i:02d}", domain=f"puppet{i:02d}.example", country="zz")
        s.add(src)
        s.flush()
        s.add(Article(url=f"https://puppet{i:02d}.example/x", canonical_url=f"https://puppet{i:02d}.example/x",
                      source_id=src.id, title="Reforms announced", content=_FLOOD, hash=f"flood{i}",
                      language="en", published_at=now + timedelta(minutes=3 * i), created_at=now))
    # One genuine, original single source.
    indie = Source(name="mountain-gazette", domain="mountaingazette.example", country="ch")
    s.add(indie)
    s.flush()
    s.add(Article(url="https://mountaingazette.example/mill", canonical_url="https://mountaingazette.example/mill",
                  source_id=indie.id, title="The mill grinds again", content=_ORIGINAL, hash="indie1",
                  language="en", published_at=now, created_at=now))
    s.commit()
    return s


def test_flood_detected_as_one_actor(flood_corpus):
    result = corpus_actors(flood_corpus, days=7, threshold=0.6)
    assert len(result.actors) == 1
    actor = result.actors[0]
    assert len(actor.sources) == 40
    assert "mountain-gazette" not in actor.sources       # the genuine source is NOT merged
    assert hasattr(actor, "signature")


def test_default_is_equal_but_aware_no_silent_collapse(flood_corpus):
    # Nothing applied yet → prominence is the raw equal view (flood dominates, annotated).
    data = collapse_mod.story_prominence(flood_corpus, days=7)
    assert data["applied"] is False
    flood = max(data["stories"], key=lambda s: s["voices_raw"])
    indie = min(data["stories"], key=lambda s: s["voices_raw"])
    assert flood["voices_raw"] == 40                     # the flood looks like 40 voices
    assert flood["voices_collapsed"] == 40               # NOT silently collapsed
    assert indie["voices_raw"] == 1


def test_no_collapse_without_explicit_action(flood_corpus):
    assert collapse_mod.applied_signatures() == set()
    # Merely computing the status must not apply anything.
    collapse_mod.collapse_status(flood_corpus, days=7)
    assert collapse_mod.applied_signatures() == set()


def test_user_applied_collapse_stops_flood_dominating(flood_corpus):
    result = corpus_actors(flood_corpus, days=7, threshold=0.6)
    sig = result.actors[0].signature

    collapse_mod.apply_collapse(sig)                     # the user's explicit action
    data = collapse_mod.story_prominence(flood_corpus, days=7)
    assert data["applied"] is True
    flood = max(data["stories"], key=lambda s: s["voices_raw"])
    indie = next(s for s in data["stories"] if s["voices_raw"] == 1)
    # The flood now counts as ONE voice; the genuine single source is its equal, not 40x drowned.
    assert flood["voices_collapsed"] == 1
    assert indie["voices_collapsed"] == 1

    # Flagged + reversible: toggling off reproduces the raw equal counts exactly.
    collapse_mod.revert_collapse(sig)
    raw = collapse_mod.story_prominence(flood_corpus, days=7)
    assert raw["applied"] is False
    flood_raw = max(raw["stories"], key=lambda s: s["voices_raw"])
    assert flood_raw["voices_collapsed"] == flood_raw["voices_raw"] == 40


def test_collapse_status_flags_applied(flood_corpus):
    result = corpus_actors(flood_corpus, days=7, threshold=0.6)
    sig = result.actors[0].signature
    collapse_mod.apply_collapse(sig)
    status = collapse_mod.collapse_status(flood_corpus, days=7)
    assert status["applied_count"] == 1
    applied_actor = next(a for a in status["actors"] if a["signature"] == sig)
    assert applied_actor["applied"] is True
    assert applied_actor["size"] == 40                   # expandable to its 40 members


# --------------------------------------------------------------------------- #
#  Source profile — measured dimensions, NO composite score
# --------------------------------------------------------------------------- #
def test_profile_has_no_composite_score(flood_corpus):
    prof = source_profile(flood_corpus, "puppet00", days=7)
    assert prof["found"] is True
    assert prof["no_composite_score"] is True
    dims = prof["dimensions"]
    # Every dimension is measured + carries method/caveat.
    for name in ("coordination", "novelty", "output_capacity", "transparency", "track_record"):
        assert name in dims and "method" in dims[name] and "caveat" in dims[name]
    # No top-level composite "score" key anywhere in the dimension map.
    assert "score" not in dims and "trust_score" not in dims
    # A puppet is correctly seen as a coordination member with low novelty.
    assert dims["coordination"]["is_member"] is True
    assert dims["novelty"]["mean_ratio"] is not None


def test_profile_unknown_source(flood_corpus):
    assert source_profile(flood_corpus, "does-not-exist")["found"] is False
