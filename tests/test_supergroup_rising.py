"""Rising super-groups: a scale-aware Leads producer (supergroups brief S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the birth constraints are load-bearing, not future fixes: a count floor
before a group even enters the test family, FDR + effect-size gating, and a rise
driven by a generic/ubiquitous member is never a Lead -- three negative-space
scenarios (flat group, generic-word-driven spike, tiny-n spike) each produce NO
card, and a genuine minority-driven rise fires.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.supergroup_rising import find_rising_supergroups
from src.database.models import (
    Article,
    Base,
    Keyword,
    KeywordMention,
    KeywordSuperGroup,
    KeywordSuperGroupMember,
    Source,
)

_TODAY = date(2026, 7, 18)
_WINDOW = 7
_BASELINE = 30
_W_START = _TODAY - timedelta(days=_WINDOW)
_B_START = _W_START - timedelta(days=_BASELINE)


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


class _Ctx:
    def __init__(self, s):
        self.s = s
        self.n = 0
        self.sources = {}

    def source(self, i, lang="en"):
        if i in self.sources:
            return self.sources[i]
        src = Source(name=f"Src{i}", domain=f"s{i}.test", language=lang)
        self.s.add(src)
        self.s.flush()
        self.sources[i] = src
        return src

    def keyword(self, term, norm, lang="en"):
        k = Keyword(
            term=term, normalized_term=norm, language=lang, frequency=0, is_entity=False,
            mention_count=0, article_count=0,
        )
        self.s.add(k)
        self.s.flush()
        return k

    def mention(self, kw, src_i, count, day, lang="en"):
        self.n += 1
        src = self.source(src_i, lang=lang)
        a = Article(
            url=f"https://{src.domain}/{self.n}", canonical_url=f"https://{src.domain}/{self.n}",
            source_id=src.id, title="t", content="x", hash=f"h{self.n}",
        )
        self.s.add(a)
        self.s.flush()
        self.s.add(
            KeywordMention(
                keyword_id=kw.id, article_id=a.id, count=count, observed_on=day, source_id=src.id
            )
        )

    def background_noise(self, *, n_sources=6, prior_count=50, recent_count=50):
        """Steady corpus-wide background activity across ``n_sources`` -- makes the
        corpus-volume denominator large + STABLE between windows (so a group's rise
        is a genuine SHARE shift, never an artifact of the corpus itself growing),
        and makes every source ACTIVE in the recent window (the ubiquity gate's
        denominator)."""
        noise = self.keyword("noise", "noise")
        for i in range(1, n_sources + 1):
            self.mention(noise, i, prior_count, _B_START + timedelta(days=1))
            self.mention(noise, i, recent_count, _W_START + timedelta(days=1))

    def supergroup(self, name, *members):
        sg = KeywordSuperGroup(name=name)
        self.s.add(sg)
        self.s.flush()
        for norm, ring_id in members:
            self.s.add(
                KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term=norm, ring_id=ring_id)
            )
        self.s.commit()
        return sg


def test_a_minority_driven_rise_fires():
    """The positive case: a member spikes from a MINORITY of active sources (well
    under the generic-ubiquity share), with a real baseline-to-recent share jump."""
    s = _sess()
    ctx = _Ctx(s)
    ctx.background_noise()
    kw = ctx.keyword("risingterm", "risingterm")
    ctx.mention(kw, 1, 1, _B_START + timedelta(days=1))
    ctx.mention(kw, 1, 1, _B_START + timedelta(days=1))  # group_prior = 2
    ctx.mention(kw, 1, 15, _W_START + timedelta(days=1))
    ctx.mention(kw, 2, 15, _W_START + timedelta(days=1))  # group_recent = 30, from 2/6 sources
    ctx.supergroup("Test Group", ("risingterm", None))
    s.commit()

    res = find_rising_supergroups(s, window_days=_WINDOW, baseline_days=_BASELINE, today=_TODAY)
    assert res["count"] == 1
    item = res["items"][0]
    assert item["name"] == "Test Group"
    assert item["z"] >= 2.5
    assert item["recent_mentions"] == 30 and item["prior_mentions"] == 2
    assert item["driven_by"] == "risingterm"
    assert item["distinct_sources"] == 2
    assert item["article_ids"]  # the exact set -> the analysis window id-seeding path
    assert isinstance(res["method"], str) and res["method"]
    assert isinstance(res["caveat"], str) and res["caveat"]


def test_a_flat_group_produces_no_card():
    """Negative space 1: a group tested (clears the count floor) but whose share is
    UNCHANGED between windows must not fire -- z stays near zero."""
    s = _sess()
    ctx = _Ctx(s)
    ctx.background_noise()
    kw = ctx.keyword("steadyterm", "steadyterm")
    for i in (1, 2, 3):
        ctx.mention(kw, i, 10, _B_START + timedelta(days=1))  # group_prior = 30
        ctx.mention(kw, i, 10, _W_START + timedelta(days=1))  # group_recent = 30, same share
    ctx.supergroup("Flat Group", ("steadyterm", None))
    s.commit()

    res = find_rising_supergroups(s, window_days=_WINDOW, baseline_days=_BASELINE, today=_TODAY)
    assert res["count"] == 0
    assert res["tested"] >= 1  # it DID enter the test family (cleared the floor)


def test_a_generic_ubiquitous_driven_spike_produces_no_card():
    """Negative space 2: a member that spikes recent mentions BUT is carried by
    (nearly) every active same-language source is publishing furniture, not a real
    theme -- never a Lead, even though the raw z-test would otherwise fire."""
    s = _sess()
    ctx = _Ctx(s)
    ctx.background_noise()  # 6 active en sources in the recent window
    kw = ctx.keyword("genericterm", "genericterm")
    ctx.mention(kw, 1, 1, _B_START + timedelta(days=1))  # group_prior = 1
    for i in range(1, 7):  # ALL 6 active sources carry it recently -> 100% ubiquity
        ctx.mention(kw, i, 5, _W_START + timedelta(days=1))  # group_recent = 30
    ctx.supergroup("Generic Group", ("genericterm", None))
    s.commit()

    res = find_rising_supergroups(s, window_days=_WINDOW, baseline_days=_BASELINE, today=_TODAY)
    assert res["count"] == 0


def test_a_tiny_n_spike_produces_no_card():
    """Negative space 3: a dramatic-looking ratio on a HANDFUL of mentions never
    even enters the test family (the count floor, no z-theater on tiny counts)."""
    s = _sess()
    ctx = _Ctx(s)
    ctx.background_noise()
    kw = ctx.keyword("tinyterm", "tinyterm")
    # group_recent well under the default min_recent_mentions=20 floor.
    ctx.mention(kw, 1, 5, _W_START + timedelta(days=1))
    ctx.supergroup("Tiny Group", ("tinyterm", None))
    s.commit()

    res = find_rising_supergroups(s, window_days=_WINDOW, baseline_days=_BASELINE, today=_TODAY)
    assert res["count"] == 0
    assert res["tested"] == 0  # never entered the test family at all


def test_no_supergroups_degrades_honestly():
    s = _sess()
    res = find_rising_supergroups(s, today=_TODAY)
    assert res == {
        "items": [], "count": 0, "tested": 0, "window_days": 7, "baseline_days": 30,
        "z_min": 2.5, "fdr_q": 0.05, "min_recent_mentions": 20,
        "method": res["method"], "caveat": res["caveat"], "reason": "no super-groups",
    }


def test_no_corpus_activity_degrades_honestly():
    s = _sess()
    ctx = _Ctx(s)
    ctx.supergroup("Empty Group", ("nothing", None))
    s.commit()
    res = find_rising_supergroups(s, today=_TODAY)
    assert res["count"] == 0
    assert res["reason"] == "no measurable corpus activity in the compared windows"
