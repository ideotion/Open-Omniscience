"""
Stratified collection ordering: TRUE per-pass randomness, fair by LANGUAGE + TAG.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled 2026-06-17 (supersedes the per-country round-robin for the default
pass): every collection pass visits sources in a freshly-randomized order that is
stratified so neither a language nor a source-tag is over-represented by having more
sources. round_robin_interleave (country) is retained as a utility + its own tests.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

from src.scheduler.runner import stratified_interleave


def _s(i, lang, tags):
    return SimpleNamespace(id=i, language=lang, tags=tags, country=None)


def test_nothing_dropped_and_empty():
    assert stratified_interleave([]) == []
    src = [_s(1, "en", "news"), _s(2, None, None), _s(3, "fr", "sport,news")]
    out = stratified_interleave(src, rng=random.Random(0))
    assert sorted(s.id for s in out) == [1, 2, 3]  # no source ever dropped


def test_fair_first_round_across_languages():
    # en has many sources, fr/unknown few. The FIRST round must give one source per
    # language — volume must not let a source-rich language dominate the pass.
    src = [_s(i, "en", "news") for i in range(1, 6)] + [_s(10, "fr", "news"), _s(11, None, None)]
    out = stratified_interleave(src, rng=random.Random(3))
    langs = {(s.language or "·unknown") for s in out[:3]}
    assert langs == {"en", "fr", "·unknown"}, out


def test_tag_fairness_within_a_language():
    # one language, a tag-heavy "news" + a small "sport": the first two picks rotate
    # the two tags (a topic is not buried by having more sources).
    src = [_s(i, "en", "news") for i in range(1, 6)] + [_s(20, "en", "sport"), _s(21, "en", "sport")]
    out = stratified_interleave(src, rng=random.Random(5))
    assert {s.tags.split(",")[0] for s in out[:2]} == {"news", "sport"}, out


def test_true_randomness_across_passes():
    # Same sources, different rng -> different order (true randomness, not a fixed
    # rotation), and never a dropped/duplicated source.
    src = [_s(i, "en", "news") for i in range(40)]
    a = [s.id for s in stratified_interleave(src, rng=random.Random(1))]
    b = [s.id for s in stratified_interleave(src, rng=random.Random(2))]
    assert a != b
    assert sorted(a) == sorted(b) == list(range(40))
