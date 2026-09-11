"""
Stratified collection ordering: TRUE per-pass randomness, fair by LANGUAGE + TAG.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled 2026-06-17 (supersedes the per-country round-robin for the default
pass): every collection pass visits sources in a freshly-randomized order that is
stratified so neither a language nor a source-tag is over-represented by having more
sources. round_robin_interleave (country) is retained as a utility + its own tests.

AMENDED 2026-09-10 (maintainer: "randomize language as well as tag selection smartly so
that both languages and tags are selected equally but in a random order"). The strict
round-robin gave EXACT equality per round and, with it, a FIXED PHASE: a language holding
one source could only be represented in round 1, so those sources led every pass on every
machine. The draw below keeps the equal RATE (uniform among the live languages at every
step, then uniform among that language's live tags) and randomises the phase. What is
pinned here is therefore the RATE and the non-pinning, not an exact per-round count --
seeded RNGs keep every assertion deterministic.
"""

from __future__ import annotations

import random
from collections import Counter
from types import SimpleNamespace

from src.scheduler.runner import stratified_interleave


def _s(i, lang, tags):
    return SimpleNamespace(id=i, language=lang, tags=tags, country=None)


def test_nothing_dropped_and_empty():
    assert stratified_interleave([]) == []
    src = [_s(1, "en", "news"), _s(2, None, None), _s(3, "fr", "sport,news")]
    out = stratified_interleave(src, rng=random.Random(0))
    assert sorted(s.id for s in out) == [1, 2, 3]  # no source ever dropped


def test_every_live_language_is_drawn_at_the_same_rate_whatever_its_size():
    # en holds 50 sources, fr and the unknown bucket one each. Volume must not buy a
    # language more turns: each of the three is equally likely to supply the NEXT source.
    src = [_s(i, "en", "news") for i in range(50)] + [_s(90, "fr", "news"), _s(91, None, None)]
    first = Counter(
        stratified_interleave(list(src), rng=random.Random(k))[0].language or "·unknown"
        for k in range(400)
    )
    assert set(first) == {"en", "fr", "·unknown"}
    for lang, n in first.items():
        assert 0.25 <= n / 400 <= 0.42, f"{lang} drawn {n}/400, expected about a third"


def test_every_live_tag_is_drawn_at_the_same_rate_within_a_language():
    # One language; "news" holds 50 sources and "sport" one. A topic is not buried by
    # having fewer sources: within the language the two tags are drawn equally often.
    src = [_s(i, "en", "news") for i in range(50)] + [_s(90, "en", "sport")]
    first = Counter(
        stratified_interleave(list(src), rng=random.Random(k))[0].tags.split(",")[0]
        for k in range(400)
    )
    assert set(first) == {"news", "sport"}
    assert 0.40 <= first["sport"] / 400 <= 0.60, first


def test_no_source_is_pinned_to_the_head_of_every_pass():
    """The 2026-09-10 regression this amendment fixes. Under the round-robin, the first
    round held exactly one source per language, so the ten single-source languages below
    filled the first ten slots of EVERY pass on EVERY instance (measured on the real
    catalogue: 21 such sources, and two blank instances shared 33 % of their first 100).
    With the draw, no source leads reliably."""
    singles = [_s(100 + i, f"lang{i}", "news") for i in range(10)]
    src = singles + [_s(i, "en", "news") for i in range(200)]
    heads = [
        {s.id for s in stratified_interleave(list(src), rng=random.Random(k))[:11]}
        for k in range(60)
    ]
    always = set.intersection(*heads)
    assert len(always) <= 1, f"{len(always)} sources lead every pass (was 10 under the round-robin)"
    # ... and the rare-language sources are still served EARLY (equal rate, not equal
    # share): each one reaches the first 11 in most passes, just not in all of them.
    reach = [sum(1 for h in heads if s.id in h) / len(heads) for s in singles]
    assert all(0.3 <= r < 1.0 for r in reach), reach


def test_a_seeded_pass_is_reproducible_and_an_unseeded_one_is_not():
    src = [_s(i, "en" if i % 3 else "fr", "news" if i % 2 else "sport") for i in range(60)]
    a = [s.id for s in stratified_interleave(list(src), rng=random.Random(11))]
    b = [s.id for s in stratified_interleave(list(src), rng=random.Random(11))]
    assert a == b  # the injected rng is the only source of order: tests stay deterministic
    c = [s.id for s in stratified_interleave(list(src), rng=random.Random(12))]
    assert a != c


def test_true_randomness_across_passes():
    # Same sources, different rng -> different order (true randomness, not a fixed
    # rotation), and never a dropped/duplicated source.
    src = [_s(i, "en", "news") for i in range(40)]
    a = [s.id for s in stratified_interleave(src, rng=random.Random(1))]
    b = [s.id for s in stratified_interleave(src, rng=random.Random(2))]
    assert a != b
    assert sorted(a) == sorted(b) == list(range(40))


def test_a_source_rich_language_never_dominates_the_head():
    # The property the 2026-06-17 ruling exists for, unchanged by the amendment: English
    # is 200 of 209 sources here but must not be 200/209 of the head.
    src = [_s(i, "en", "news") for i in range(200)] + [_s(300 + i, f"l{i}", "news") for i in range(9)]
    head = Counter(
        s.language
        for k in range(20)
        for s in stratified_interleave(list(src), rng=random.Random(500 + k))[:10]
    )
    assert head["en"] / (20 * 10) < 0.25, head  # ~1/10 of the turns, not 96 % of them
