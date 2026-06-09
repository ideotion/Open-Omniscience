"""
Tests for near-duplicate detection, coordination, and novelty (pure primitives).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Crafted fixtures with a *known* answer: a syndicated story collapses into one cluster /
actor; an independent original stays separate; a pure echo scores ~0 novelty while the
original scores ~1. No DB, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.signals import (
    NoveltyIndex,
    detect_coordination,
    jaccard_estimate,
    minhash_signature,
    near_duplicate_clusters,
    novelty_scores,
    shingles,
)

_WIRE = (
    "The central bank raised interest rates by half a point on Tuesday, citing "
    "persistent inflation and a tight labour market, and signalled more tightening "
    "could follow before the end of the year if price pressures do not ease soon."
)
_WIRE_LIGHT_REWRITE = (
    "The central bank raised interest rates by half a point on Tuesday, "
    "citing persistent inflation and a tight labour market, and signalled "
    "further tightening could follow before year end if price pressures "
    "do not ease."
)
_INDEPENDENT = (
    "Local volunteers cleared three tonnes of plastic from the estuary over the "
    "weekend, the largest community clean-up the coastal town has organised, with "
    "schools and fishing crews joining a effort that organisers hope becomes annual."
)


# --------------------------------------------------------------------------- #
#  MinHash / Jaccard
# --------------------------------------------------------------------------- #
def test_minhash_estimates_jaccard_high_for_near_dup():
    sa = minhash_signature(shingles(_WIRE), 128)
    sb = minhash_signature(shingles(_WIRE_LIGHT_REWRITE), 128)
    sc = minhash_signature(shingles(_INDEPENDENT), 128)
    # 5-word shingles: a light rewrite breaks several n-grams, so a paraphrase is
    # only moderately similar — but still clearly above an unrelated story. (Exact
    # reposts, the common syndication case, score ~1.0.)
    sim = jaccard_estimate(sa, sb)
    assert 0.35 < sim < 0.9  # near-duplicate (paraphrase)
    assert jaccard_estimate(sa, sc) < 0.15  # unrelated
    assert jaccard_estimate(sa, sa) == 1.0  # identical


def test_empty_text_has_no_shingles():
    assert shingles("") == set()
    assert jaccard_estimate(minhash_signature(set()), minhash_signature(shingles(_WIRE))) == 0.0


# --------------------------------------------------------------------------- #
#  Near-duplicate clustering — syndication collapses, originals stay apart
# --------------------------------------------------------------------------- #
def test_syndicated_story_clusters_independent_stays_separate():
    docs = {
        "outletA": _WIRE,
        "outletB": _WIRE_LIGHT_REWRITE,
        "outletC": _WIRE,  # exact repost
        "indie": _INDEPENDENT,  # genuinely different
    }
    # threshold 0.4 catches the paraphrase too (still far above the unrelated story).
    res = near_duplicate_clusters(docs, threshold=0.4)
    assert len(res.clusters) == 1
    cluster = res.clusters[0]
    assert set(cluster.members) == {"outletA", "outletB", "outletC"}
    assert "indie" not in cluster.members
    assert res.to_dict()["clusters"][0]["size"] == 3


def test_bands_rows_must_match_num_perm():
    import pytest

    with pytest.raises(ValueError):
        near_duplicate_clusters({"a": "x"}, num_perm=128, bands=10, rows=5)


# --------------------------------------------------------------------------- #
#  Coordination — a puppet flood collapses to one actor; a real original rises
# --------------------------------------------------------------------------- #
def test_coordinated_flood_collapses_to_one_actor():
    now = datetime.now(UTC)
    docs = [
        {
            "id": f"p{i}",
            "source": f"puppet{i}",
            "text": _WIRE,
            "published_at": now + timedelta(minutes=5 * i),
            "host": "cdn.flood.example",
        }
        for i in range(5)
    ]
    docs.append(
        {
            "id": "real",
            "source": "independent",
            "text": _INDEPENDENT,
            "published_at": now,
            "host": "indie.example",
        }
    )

    res = detect_coordination(docs, threshold=0.6, window_hours=24)
    assert len(res.actors) == 1
    actor = res.actors[0]
    assert set(actor.sources) == {f"puppet{i}" for i in range(5)}
    assert "independent" not in actor.sources  # the genuine source is not merged
    assert actor.shared_hosts == ["cdn.flood.example"]
    assert actor.median_span_hours is not None and actor.median_span_hours <= 24


def test_spread_out_near_dup_is_not_lockstep():
    now = datetime.now(UTC)
    docs = [
        {"id": "a", "source": "s1", "text": _WIRE, "published_at": now},
        {"id": "b", "source": "s2", "text": _WIRE, "published_at": now + timedelta(days=10)},
    ]
    res = detect_coordination(docs, threshold=0.6, window_hours=48, require_timing=True)
    assert res.actors == []  # near-dup, but 10 days apart -> not coordinated


# --------------------------------------------------------------------------- #
#  Novelty — original is novel, echo is not
# --------------------------------------------------------------------------- #
def test_first_sighting_is_novel_echo_is_not():
    idx = NoveltyIndex()
    first = idx.measure_and_add(_WIRE)
    echo = idx.measure_and_add(_WIRE)  # exact repost
    assert first.ratio == 1.0
    assert echo.ratio == 0.0
    rewrite = idx.measure_and_add(_WIRE_LIGHT_REWRITE)
    assert 0.0 < rewrite.ratio < 0.5  # mostly-seen, a little new


def test_novelty_scores_orders_matter():
    scores = novelty_scores([("orig", _WIRE), ("repost", _WIRE), ("indie", _INDEPENDENT)])
    assert scores["orig"].ratio == 1.0
    assert scores["repost"].ratio == 0.0
    assert scores["indie"].ratio == 1.0  # different corpus content -> all new


def test_novelty_empty_text_is_honest():
    r = NoveltyIndex().novelty("")
    assert r.ratio is None and r.n_shingles == 0
