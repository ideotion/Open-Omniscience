"""Super-group honest statistics (supergroups brief S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the fix for the field export's row 1 (dominance disclosure), row 2
(cross-group overlap disclosure) and row 3 (within-group double counting):
members are resolved to a DISTINCT keyword-id set before any total is summed,
so a keyword covered by both a plain family member and a covering ring member
in the SAME group counts once, never twice -- and every payload degrades
honestly (zeros, never a fabricated number) on an empty/unresolvable group.
"""

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.supergroup_stats import (
    _distinct_source_count,
    _language_breakdown,
    _per_id_mentions,
    cross_group_membership,
    daily_series,
    distinct_ids,
    find_redundant_family_members,
    group_rate,
    member_overlaps,
    resolve_member_keyword_ids,
    supergroup_stats,
)
from src.database.models import (
    Article,
    Base,
    Keyword,
    KeywordMention,
    KeywordSuperGroup,
    KeywordSuperGroupMember,
    Source,
)

_FORBIDDEN_SCORE_SUBSTRINGS = ("score", "ranking", "rating", "grade")


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _article(s, n=1):
    src = s.query(Source).filter_by(domain="s.test").first()
    if src is None:
        src = Source(name="Src", domain="s.test")
        s.add(src)
        s.flush()
    a = Article(
        url=f"https://s.test/{n}",
        canonical_url=f"https://s.test/{n}",
        source_id=src.id,
        title="t",
        content="x",
        hash=f"h{n}",
    )
    s.add(a)
    s.flush()
    return a


def _kw(s, term, norm, lang):
    k = Keyword(
        term=term,
        normalized_term=norm,
        language=lang,
        frequency=0,
        is_entity=False,
        mention_count=0,
        article_count=0,
    )
    s.add(k)
    s.flush()
    return k


def _mention(s, kw, article, count, observed_on=None, source_id=1):
    s.add(
        KeywordMention(
            keyword_id=kw.id,
            article_id=article.id,
            count=count,
            observed_on=observed_on or date.today(),
            source_id=source_id,
        )
    )


def _no_score_fields(obj, path=""):
    """Recursively walk dict KEYS (not repr()) for a banned score-ish substring --
    mirrors the project's documented no-score-key-walker convention."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            assert not any(s in lk for s in _FORBIDDEN_SCORE_SUBSTRINGS), (
                f"score-like key {path}.{k}"
            )
            _no_score_fields(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _no_score_fields(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# resolve_member_keyword_ids / distinct_ids / member_overlaps


def test_resolve_member_keyword_ids_family_and_ring():
    s = _sess()
    a = _article(s)
    kw_election = _kw(s, "election", "election", "en")
    _mention(s, kw_election, a, 5)
    s.commit()

    out = resolve_member_keyword_ids(s, [("election", None)])
    assert out["election"] == {kw_election.id}


def test_distinct_ids_dedupes_a_keyword_shared_by_a_family_and_a_ring_member():
    """The row-3 scenario verbatim: group has a plain family member "ai" AND a
    ring member for the real "artificial-intelligence" ring, whose own English
    member IS "ai" -- so both members resolve to the SAME keyword id."""
    s = _sess()
    a = _article(s)
    kw_ai = _kw(s, "AI", "ai", "en")
    _mention(s, kw_ai, a, 50)
    s.commit()

    member_rows = [("ai", None), ("artificial-intelligence", "artificial-intelligence")]
    sets = resolve_member_keyword_ids(s, member_rows)
    assert sets["ai"] == {kw_ai.id}
    assert sets["artificial-intelligence"] == {kw_ai.id}  # the real overlap

    deduped = distinct_ids(sets)
    assert deduped == {kw_ai.id}  # ONE keyword, never counted as two


def test_member_overlaps_flags_the_within_group_sharing():
    s = _sess()
    a = _article(s)
    kw_ai = _kw(s, "AI", "ai", "en")
    _mention(s, kw_ai, a, 10)
    s.commit()

    sets = resolve_member_keyword_ids(
        s, [("ai", None), ("artificial-intelligence", "artificial-intelligence")]
    )
    overlaps = member_overlaps(sets)
    assert overlaps["ai"] == ["artificial-intelligence"]
    assert overlaps["artificial-intelligence"] == ["ai"]


def test_member_overlaps_empty_when_no_members_share_an_id():
    s = _sess()
    a = _article(s)
    kw_a = _kw(s, "Trump", "trump", "en")
    kw_b = _kw(s, "Biden", "biden", "en")
    _mention(s, kw_a, a, 3)
    _mention(s, kw_b, a, 3)
    s.commit()

    sets = resolve_member_keyword_ids(s, [("trump", None), ("biden", None)])
    overlaps = member_overlaps(sets)
    assert overlaps == {"trump": [], "biden": []}


def test_resolve_member_keyword_ids_unknown_ring_resolves_to_empty_not_a_crash():
    s = _sess()
    out = resolve_member_keyword_ids(s, [("not-a-real-ring", "not-a-real-ring")])
    assert out["not-a-real-ring"] == set()


# ---------------------------------------------------------------------------
# cross_group_membership (pure, no DB) -- row 2


def test_cross_group_membership_flags_a_ring_shared_by_two_groups():
    groups = [
        ("Mathematics", [("logic", "logic"), ("algebra", "algebra")]),
        ("Philosophy", [("logic", "logic"), ("ethics", "ethics")]),
    ]
    shared = cross_group_membership(groups)
    assert shared[("logic", "logic")] == ["Mathematics", "Philosophy"]
    assert ("algebra", "algebra") not in shared
    assert ("ethics", "ethics") not in shared


def test_cross_group_membership_empty_when_nothing_overlaps():
    groups = [("A", [("x", None)]), ("B", [("y", None)])]
    assert cross_group_membership(groups) == {}


# ---------------------------------------------------------------------------
# group_rate -- the disclosed recent-vs-baseline ratio + the honest floor


def test_group_rate_computes_recent_and_prior_within_their_windows():
    s = _sess()
    a1 = _article(s, 1)
    a2 = _article(s, 2)
    kw = _kw(s, "x", "x", "en")
    today = date(2026, 7, 18)
    _mention(s, kw, a1, 10, observed_on=today - timedelta(days=2))  # inside the 7d window
    _mention(s, kw, a2, 20, observed_on=today - timedelta(days=15))  # inside the 30d baseline
    s.commit()

    rate = group_rate(s, {kw.id}, window_days=7, baseline_days=30, today=today)
    assert rate["recent"] == 10
    assert rate["prior"] == 20
    assert rate["expected"] == round((20 / 30) * 7, 2)
    assert rate["growth"] == round(10 / rate["expected"], 2)


def test_group_rate_honest_floor_when_no_prior_data():
    s = _sess()
    a = _article(s)
    kw = _kw(s, "x", "x", "en")
    today = date(2026, 7, 18)
    _mention(s, kw, a, 4, observed_on=today - timedelta(days=1))
    s.commit()

    rate = group_rate(s, {kw.id}, window_days=7, baseline_days=30, today=today)
    assert rate["prior"] == 0
    assert rate["expected"] == 0.0
    assert rate["growth"] == 4.0  # the recent count itself, never a divide-by-zero


def test_group_rate_on_empty_id_set_is_all_zero():
    s = _sess()
    rate = group_rate(s, set())
    assert rate == {
        "recent": 0,
        "prior": 0,
        "expected": 0.0,
        "growth": 0.0,
        "window_days": 7,
        "baseline_days": 30,
    }


def test_group_rate_prefers_the_rollup_serve_when_available(monkeypatch):
    """The windowed machinery is reused, never rebuilt (brief §2 S1.2): when the
    opt-in rollup serve answers a window, group_rate must use it (and skip the
    live keyword_mentions scan) rather than silently ignoring it."""
    from src.analytics import rollup_serve

    s = _sess()
    kw = _kw(s, "x", "x", "en")
    s.commit()  # NOTE: no mentions rows at all -- proves the served numbers are used,
    # not a coincidental match with a live scan of an empty table.

    calls = {"recent": {kw.id: 99}, "prior": {kw.id: 9}}
    seen_windows = []

    def _fake_windowed_counts(_db, *, lo, hi):
        seen_windows.append((lo, hi))
        return calls["recent"] if len(seen_windows) == 1 else calls["prior"]

    monkeypatch.setattr(rollup_serve, "windowed_counts", _fake_windowed_counts)

    rate = group_rate(s, {kw.id}, window_days=7, baseline_days=30, today=date(2026, 7, 18))
    assert rate["recent"] == 99
    assert rate["prior"] == 9
    assert len(seen_windows) == 2  # one call per window, exactly as trending() does


def test_group_rate_falls_back_to_live_when_rollup_serve_misses(monkeypatch):
    from src.analytics import rollup_serve

    s = _sess()
    a = _article(s)
    kw = _kw(s, "x", "x", "en")
    today = date(2026, 7, 18)
    _mention(s, kw, a, 5, observed_on=today - timedelta(days=1))
    s.commit()

    monkeypatch.setattr(rollup_serve, "windowed_counts", lambda *a, **kw: None)  # every miss

    rate = group_rate(s, {kw.id}, window_days=7, baseline_days=30, today=today)
    assert rate["recent"] == 5  # the live scan still answers correctly


# ---------------------------------------------------------------------------
# daily_series -- the S1.5 sparkline substrate, deduped like the headline total


def test_daily_series_dedups_a_keyword_shared_by_two_members():
    """The chart-level analog of the row-3 fix: a day where BOTH the "ai" family
    member and the overlapping "artificial-intelligence" ring member point at the
    SAME keyword must show that keyword's mentions ONCE, not twice."""
    s = _sess()
    a = _article(s)
    kw_ai = _kw(s, "AI", "ai", "en")
    today = date(2026, 7, 18)
    _mention(s, kw_ai, a, 7, observed_on=today)
    s.commit()

    sets = resolve_member_keyword_ids(
        s, [("ai", None), ("artificial-intelligence", "artificial-intelligence")]
    )
    group_ids = distinct_ids(sets)
    series = daily_series(s, group_ids, days=7, today=today)
    assert series == [{"date": "2026-07-18", "count": 7}]  # not 14


def test_daily_series_omits_zero_days_and_respects_the_window():
    s = _sess()
    a1 = _article(s, 1)
    a2 = _article(s, 2)
    kw = _kw(s, "x", "x", "en")
    today = date(2026, 7, 18)
    _mention(s, kw, a1, 3, observed_on=today - timedelta(days=2))
    _mention(s, kw, a2, 4, observed_on=today - timedelta(days=40))  # outside a 7d window
    s.commit()

    series = daily_series(s, {kw.id}, days=7, today=today)
    assert series == [{"date": (today - timedelta(days=2)).isoformat(), "count": 3}]


def test_daily_series_empty_ids_is_empty():
    s = _sess()
    assert daily_series(s, set(), days=7) == []


# ---------------------------------------------------------------------------
# _distinct_source_count / _language_breakdown / _per_id_mentions


def test_distinct_source_count_dedupes_and_ignores_null_source():
    s = _sess()
    a1 = _article(s, 1)
    a2 = _article(s, 2)
    a3 = _article(s, 3)
    a4 = _article(s, 4)
    kw = _kw(s, "x", "x", "en")
    _mention(s, kw, a1, 1, source_id=1)
    _mention(s, kw, a2, 1, source_id=1)  # same source again
    _mention(s, kw, a3, 1, source_id=2)
    _mention(s, kw, a4, 1, source_id=None)
    s.commit()

    assert _distinct_source_count(s, {kw.id}) == 2


def test_language_breakdown_buckets_unknown_language_honestly():
    s = _sess()
    a = _article(s)
    kw_en = _kw(s, "x", "x", "en")
    kw_none = _kw(s, "y", "y", None)
    _mention(s, kw_en, a, 7)
    _mention(s, kw_none, a, 3)
    s.commit()

    per_id = _per_id_mentions(s, {kw_en.id, kw_none.id})
    breakdown = _language_breakdown(s, {kw_en.id, kw_none.id}, per_id)
    assert breakdown["en"] == 7
    assert breakdown["?"] == 3


def test_per_id_mentions_empty_ids_is_empty():
    s = _sess()
    assert _per_id_mentions(s, set()) == {}


# ---------------------------------------------------------------------------
# supergroup_stats end-to-end


def test_supergroup_stats_dedups_the_group_total_and_discloses_dominance():
    """The headline fix, end to end: a group with a plain "ai" family member AND
    an "artificial-intelligence" ring member covering the SAME keyword must NOT
    report double the true mention count."""
    s = _sess()
    a = _article(s)
    kw_ai = _kw(s, "AI", "ai", "en")
    _mention(s, kw_ai, a, 50, observed_on=date(2020, 1, 1))  # outside any rate window
    sg = KeywordSuperGroup(name="Artificial intelligence")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="ai", ring_id=None))
    s.add(
        KeywordSuperGroupMember(
            supergroup_id=sg.id,
            normalized_term="artificial-intelligence",
            ring_id="artificial-intelligence",
        )
    )
    s.commit()
    s.refresh(sg)

    out = supergroup_stats(s, sg)
    assert out["group_total"]["mentions"] == 50  # NOT 100 (the naive double-count)
    assert out["group_total"]["distinct_keywords"] == 1
    assert out["dominance"]["mentions"] == 50
    assert out["dominance"]["share"] == 1.0
    assert out["within_group_overlap"] == {
        "ai": ["artificial-intelligence"],
        "artificial-intelligence": ["ai"],
    }
    assert out["distinct_sources"] == 1
    assert out["languages"] == {"en": 50}
    assert isinstance(out["method"], str) and out["method"]
    assert isinstance(out["caveat"], str) and out["caveat"]
    _no_score_fields(out)


def test_supergroup_stats_discloses_cross_group_overlap_via_other_groups():
    s = _sess()
    sg_math = KeywordSuperGroup(name="Mathematics")
    sg_phil = KeywordSuperGroup(name="Philosophy")
    s.add_all([sg_math, sg_phil])
    s.flush()
    s.add(
        KeywordSuperGroupMember(
            supergroup_id=sg_math.id, normalized_term="logic", ring_id="logic"
        )
    )
    s.add(
        KeywordSuperGroupMember(
            supergroup_id=sg_phil.id, normalized_term="logic", ring_id="logic"
        )
    )
    s.commit()
    s.refresh(sg_math)
    s.refresh(sg_phil)

    other_groups = [
        (g.name, [(m.normalized_term, m.ring_id) for m in g.members])
        for g in (sg_math, sg_phil)
    ]

    out_math = supergroup_stats(s, sg_math, other_groups=other_groups)
    assert out_math["cross_group_overlap"]["logic"] == ["Philosophy"]  # never itself

    out_phil = supergroup_stats(s, sg_phil, other_groups=other_groups)
    assert out_phil["cross_group_overlap"]["logic"] == ["Mathematics"]


def test_supergroup_stats_no_cross_group_overlap_when_other_groups_omitted():
    s = _sess()
    sg = KeywordSuperGroup(name="Solo")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="logic", ring_id="logic"))
    s.commit()
    s.refresh(sg)

    out = supergroup_stats(s, sg)
    assert out["cross_group_overlap"] == {}


def test_supergroup_stats_degrades_honestly_on_an_empty_group():
    s = _sess()
    sg = KeywordSuperGroup(name="Empty")
    s.add(sg)
    s.commit()
    s.refresh(sg)

    out = supergroup_stats(s, sg)
    assert out["group_total"] == {"mentions": 0, "distinct_keywords": 0}
    assert out["dominance"] is None  # never a fabricated dominance on nothing
    assert out["distinct_sources"] == 0
    assert out["languages"] == {}
    assert out["cross_group_overlap"] == {}
    assert out["within_group_overlap"] == {}
    assert out["rate"]["recent"] == 0 and out["rate"]["growth"] == 0.0


def test_supergroup_stats_degrades_honestly_when_no_member_resolves_to_a_keyword():
    s = _sess()
    sg = KeywordSuperGroup(name="Ghost")
    s.add(sg)
    s.flush()
    s.add(
        KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="nonexistent-term", ring_id=None)
    )
    s.commit()
    s.refresh(sg)

    out = supergroup_stats(s, sg)
    assert out["group_total"] == {"mentions": 0, "distinct_keywords": 0}
    assert out["dominance"] is None


# ---------------------------------------------------------------------------
# find_redundant_family_members -- S4.1, a REPORT never an auto-purge


def test_find_redundant_family_members_flags_a_member_fully_covered_by_a_ring():
    """The exact field-export scenario: a plain "ai" family member whose keyword
    is ALSO covered by the "artificial-intelligence" ring in the same group."""
    s = _sess()
    a = _article(s)
    kw_ai = _kw(s, "AI", "ai", "en")
    _mention(s, kw_ai, a, 10)
    sg = KeywordSuperGroup(name="Artificial intelligence")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="ai", ring_id=None))
    s.add(
        KeywordSuperGroupMember(
            supergroup_id=sg.id, normalized_term="artificial-intelligence",
            ring_id="artificial-intelligence",
        )
    )
    s.commit()

    report = find_redundant_family_members(s)
    assert len(report) == 1
    row = report[0]
    assert row["sg_name"] == "Artificial intelligence"
    assert row["member"] == "ai"
    assert row["redundant_with_rings"] == ["artificial-intelligence"]


def test_find_redundant_family_members_never_flags_a_partially_covered_member():
    """A plain member whose keyword-id set is NOT a subset of the ring union
    (it covers something the ring doesn't) must never be flagged as redundant --
    it carries real, non-duplicated information."""
    s = _sess()
    a2 = _article(s, 2)
    kw_extra = _kw(s, "extra", "extra", "en")
    sg = KeywordSuperGroup(name="Artificial intelligence")
    s.add(sg)
    s.flush()
    _mention(s, kw_extra, a2, 5)
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="extra", ring_id=None))
    s.add(
        KeywordSuperGroupMember(
            supergroup_id=sg.id, normalized_term="artificial-intelligence",
            ring_id="artificial-intelligence",
        )
    )
    s.commit()

    assert find_redundant_family_members(s) == []


def test_find_redundant_family_members_ignores_groups_with_no_ring():
    s = _sess()
    a = _article(s)
    kw = _kw(s, "Trump", "trump", "en")
    _mention(s, kw, a, 5)
    sg = KeywordSuperGroup(name="People")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="trump", ring_id=None))
    s.commit()

    assert find_redundant_family_members(s) == []


def test_find_redundant_family_members_never_flags_an_unresolvable_member():
    """A plain member covering NO keyword at all (a dead/unresolved entry) is a
    config-lint concern, not a redundancy one -- it must never be reported here."""
    s = _sess()
    sg = KeywordSuperGroup(name="Artificial intelligence")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="nonexistent", ring_id=None))
    s.add(
        KeywordSuperGroupMember(
            supergroup_id=sg.id, normalized_term="artificial-intelligence",
            ring_id="artificial-intelligence",
        )
    )
    s.commit()

    assert find_redundant_family_members(s) == []
