"""``build_families`` finds containment through a token index; the families are unchanged.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The pairwise form (kept verbatim in ``tests/_families_pairwise_reference.py``) compared every
multi-token entity with every other: ~4x the time per doubling, 267 s for 16,000 of them. That
is what kept the keyword export from grouping a whole window and made it group the top 5,000 per
language instead. The token-indexed form draws the same edges, so the output must be the same
list of families in the same order with the same members. Random entity sets built from a SMALL
vocabulary (so phrases collide, nest, share tokens across kinds, carry honorifics, possessives
and junk characters) are where a missed or an extra edge would show.
"""

from __future__ import annotations

import random
import time

import pytest

from src.analytics.families import build_families
from tests._families_pairwise_reference import build_families_pairwise

TOKENS = ["trump", "donald", "paris", "hilton", "new", "york", "city", "security", "national",
          "social", "council", "iran", "israel", "united", "states", "bank", "central", "of"]
HONORIFICS = ["president", "dr", "mr", "senator", "king"]
KINDS = ["person", "org", "place", "term"]
JUNK = [":", "(", '"', "..."]


def _items(rnd: random.Random, n: int) -> list[dict]:
    out = []
    for _ in range(n):
        toks = [rnd.choice(TOKENS) for _ in range(rnd.choice([1, 1, 2, 2, 3, 3, 4, 5]))]
        if rnd.random() < 0.2:
            toks.insert(0, rnd.choice(HONORIFICS))
        if rnd.random() < 0.15:
            toks[-1] += rnd.choice(["'s", "'", "’s"])
        norm = " ".join(toks)
        term = norm.title()
        if rnd.random() < 0.1:
            term += rnd.choice(JUNK)
        out.append({
            "term": term, "normalized": norm, "kind": rnd.choice(KINDS),
            "mentions": rnd.randint(1, 50), "articles": rnd.randint(1, 20),
            "language": rnd.choice(["en", "fr", None]),
        })
    return out


def _overrides(rnd: random.Random, items: list[dict]) -> dict:
    ov = {}
    for it in rnd.sample(items, min(3, len(items))):
        key = it["normalized"]
        ov[key] = {"family_key": rnd.choice([key, "forced-family"]), "label": None, "kind": it["kind"]}
    return ov


@pytest.mark.parametrize("seed", range(40))
def test_the_token_index_draws_the_same_families_as_the_pairwise_loops(seed):
    rnd = random.Random(seed)
    items = _items(rnd, rnd.choice([30, 120, 400]))
    ov = _overrides(rnd, items) if seed % 3 == 0 else None
    want = [f.to_dict() for f in build_families_pairwise(items, ov)]
    got = [f.to_dict() for f in build_families(items, ov)]
    assert got == want


def test_the_random_sets_really_exercise_containment():
    """Without this the equality above could hold between two implementations that never merge
    anything: require nested phrases, honorific equivalence and ambiguous single tokens."""
    rnd = random.Random(1)
    items = _items(rnd, 400)
    fams = build_families(items)
    assert any(f.variant_count >= 4 for f in fams)
    assert any(len({m["normalized"] for m in f.members}) > 1 and f.kind != "term" for f in fams)
    assert len(fams) < len(items) * 0.9


def test_a_single_token_is_joined_only_when_every_clean_parent_shares_one_family():
    items = [
        {"term": "Donald Trump", "normalized": "donald trump", "kind": "person", "mentions": 9},
        {"term": "President Donald Trump", "normalized": "president donald trump",
         "kind": "person", "mentions": 4},
        {"term": "Trump", "normalized": "trump", "kind": "person", "mentions": 3},
        {"term": "National Security", "normalized": "national security", "kind": "org", "mentions": 5},
        {"term": "Social Security", "normalized": "social security", "kind": "org", "mentions": 5},
        {"term": "Security", "normalized": "security", "kind": "org", "mentions": 2},
    ]
    by_norm = {f.normalized: f for f in build_families(items)}
    assert {m["normalized"] for m in by_norm["donald trump"].members} >= {"donald trump", "trump"}
    assert "security" in by_norm  # ambiguous: stays standalone


def test_grouping_thousands_of_entities_is_no_longer_quadratic():
    """16,000 multi-token entities took 267 s pairwise (measured 2026-09-30). The bound here is
    wide enough for a slow CI runner and ~10x below what the pairwise form needed for a third of
    this many."""
    rnd = random.Random(7)
    vocab = [f"w{i}" for i in range(4000)]
    items = []
    for i in range(30_000):
        toks = [rnd.choice(vocab) for _ in range(rnd.choice([2, 3]))]
        items.append({"term": " ".join(toks), "normalized": " ".join(toks),
                      "kind": rnd.choice(["person", "org", "place"]), "mentions": i % 97 + 1})
    t0 = time.perf_counter()
    build_families(items)
    assert time.perf_counter() - t0 < 30
