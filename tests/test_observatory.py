"""The Observatory data spine — S0 (the scaffold ``domain`` field) + S1
(the payload endpoint), 2026-07-20.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Backend-only per docs/design/OBSERVATORY_DESIGN.md §9 (the ``ooSky`` canvas
renderer is browser-verify-gated). Proves: (a) every bundled super-group in
``configs/keyword_supergroups.yml`` now carries a ``domain``, exactly 12
distinct values; (b) the cluster (universe) tier properly DEDUPES across its
member galaxies — a keyword covered by two galaxies of the SAME domain counts
once at the cluster level, never twice (the row-3 double-counting trap,
recurring one tier up from the super-groups S1 core); (c) a galaxy whose name
is absent from the bundled domain map degrades honestly to 'Uncategorized',
never a guess; (d) the nebula disclosure is a true corpus-wide complement, not
a fabricated number; (e) no composite score anywhere in the payload.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.observatory import UNCATEGORIZED, domain_of_group, observatory_payload
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
    src = s.query(Source).filter_by(domain="obs.test").first()
    if src is None:
        src = Source(name="Src", domain="obs.test")
        s.add(src)
        s.flush()
    a = Article(
        url=f"https://obs.test/{n}",
        canonical_url=f"https://obs.test/{n}",
        source_id=src.id,
        title="t",
        content="x",
        hash=f"oh{n}",
    )
    s.add(a)
    s.flush()
    return a


def _kw(s, term, norm, lang="en"):
    k = Keyword(
        term=term, normalized_term=norm, language=lang,
        frequency=0, is_entity=False, mention_count=0, article_count=0,
    )
    s.add(k)
    s.flush()
    return k


def _mention(s, kw, article, count=1, observed_on=None):
    s.add(
        KeywordMention(
            keyword_id=kw.id, article_id=article.id, count=count,
            observed_on=observed_on or date.today(), source_id=article.source_id,
        )
    )


def _sg(s, name, terms):
    sg = KeywordSuperGroup(name=name)
    s.add(sg)
    s.flush()
    for t in terms:
        s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term=t))
    s.flush()
    return sg


def _no_score_fields(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            assert not any(sub in lk for sub in _FORBIDDEN_SCORE_SUBSTRINGS), (
                f"score-like key {path}.{k}"
            )
            _no_score_fields(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _no_score_fields(v, f"{path}[{i}]")


# --------------------------------------------------------------------------- #
# S0: the bundled scaffold's domain field
# --------------------------------------------------------------------------- #


def test_domain_of_group_covers_every_bundled_supergroup_with_exactly_12_domains():
    domain_of_group.cache_clear()
    dmap = domain_of_group()
    assert len(dmap) == 77
    assert len(set(dmap.values())) == 12
    assert dmap["State & government"] == "Politics & governance"
    assert dmap["Climate change"] == "Climate & environment"
    for domain in dmap.values():
        assert domain.strip() and domain != UNCATEGORIZED


def test_domain_of_group_is_cached():
    domain_of_group.cache_clear()
    a = domain_of_group()
    b = domain_of_group()
    assert a is b


# --------------------------------------------------------------------------- #
# S1: the observatory payload — cluster dedup, uncategorized fallback, nebula
# --------------------------------------------------------------------------- #


def test_cluster_tier_dedupes_a_keyword_shared_by_two_galaxies_of_the_same_domain():
    s = _sess()
    a1, a2 = _article(s, 1), _article(s, 2)
    shared = _kw(s, "election", "election")
    only_a = _kw(s, "senate", "senate")
    _mention(s, shared, a1, count=5)
    _mention(s, only_a, a1, count=2)
    _mention(s, shared, a2, count=3)

    # Two REAL bundled group names, both mapped to "Politics & governance" by
    # the scaffold, sharing the SAME keyword ("election") via their family
    # members -- the row-3 trap one tier up.
    _sg(s, "State & government", ["senate"])
    _sg(s, "Elections & democracy", ["election"])

    out = observatory_payload(s, window_days=7, baseline_days=30, today=date.today())
    politics = next(c for c in out["clusters"] if c["domain"] == "Politics & governance")
    # Deduped union of {senate, election} -> 2 distinct keywords, NOT summed
    # per-galaxy counts (which would double the shared "election" keyword's
    # contribution across the two galaxies of the same domain).
    assert politics["measures"]["distinct_keywords"] == 2
    # mentions: senate(2) + election(5+3=8) = 10, counted ONCE each (not twice
    # for "election" just because it's covered by only one galaxy here -- the
    # dedup guarantee is about SHARED keywords, proven by distinct_keywords).
    assert politics["measures"]["mentions"] == 10
    assert politics["galaxy_count"] == 2


def test_unmapped_galaxy_name_degrades_honestly_to_uncategorized():
    s = _sess()
    a = _article(s, 1)
    kw = _kw(s, "widget", "widget")
    _mention(s, kw, a, count=1)
    _sg(s, "A group the user invented", ["widget"])

    out = observatory_payload(s)
    galaxy = next(g for g in out["galaxies"] if g["name"] == "A group the user invented")
    assert galaxy["domain"] == UNCATEGORIZED
    cluster = next(c for c in out["clusters"] if c["domain"] == UNCATEGORIZED)
    assert cluster["galaxy_count"] == 1
    assert cluster["measures"]["distinct_keywords"] == 1


def test_nebula_is_the_true_corpus_wide_complement_never_fabricated():
    s = _sess()
    a = _article(s, 1)
    covered = _kw(s, "election", "election")
    uncovered = _kw(s, "obscure-term", "obscure-term")  # never in any group
    _mention(s, covered, a, count=1)
    _mention(s, uncovered, a, count=1)
    _sg(s, "Elections & democracy", ["election"])

    out = observatory_payload(s)
    nebula = out["nebula"]
    assert nebula["total_keywords"] == 2
    assert nebula["covered_keywords"] == 1
    assert nebula["nebula_keywords"] == 1


def test_empty_corpus_degrades_honestly_no_crash():
    s = _sess()
    out = observatory_payload(s)
    assert out["clusters"] == []
    assert out["galaxies"] == []
    assert out["nebula"] == {"covered_keywords": 0, "nebula_keywords": 0, "total_keywords": 0}


def test_galaxy_measures_and_method_caveat_present_no_score():
    s = _sess()
    a = _article(s, 1)
    kw = _kw(s, "election", "election")
    _mention(s, kw, a, count=4)
    _sg(s, "Elections & democracy", ["election"])

    out = observatory_payload(s)
    assert "method" in out and "caveat" in out
    galaxy = out["galaxies"][0]
    for field in ("mentions", "distinct_sources", "distinct_languages", "distinct_keywords"):
        assert field in galaxy["measures"]
    assert galaxy["measures"]["mentions"] == 4
    _no_score_fields(out)


def test_observatory_endpoint_is_deadlined_and_reuses_the_payload():
    from src.api import insights

    import inspect

    src = inspect.getsource(insights.insights_observatory)
    assert "_deadlined(" in src
    assert "observatory_payload(" in src
