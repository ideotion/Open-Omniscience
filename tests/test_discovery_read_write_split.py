"""The A2 fix (2026-09-11): discovery's expensive scan must run OUTSIDE the
single-writer gate, and a scan that is truncated by its wall-clock budget must
say so honestly rather than presenting a floor as a complete total.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field evidence (2026-09-11 bundle): pass-tail phase `discovery` measured 1,590,907 ms
(26.5 min); the single-writer gate measured busy_share 0.7936, max_hold_s 1329.21; a
single SAVEPOINT statement clocked 664,207 ms. S2.4 (2026-09-02) correctly fixed
SQLITE_BUSY_SNAPSHOT by holding the gate from before the first read, but that also
serialised every OTHER writer in the process behind citation_channel's whole-corpus
ArticleLink scan (1.3M+ distinct pairs on the field corpus) -- the gate itself became
the bottleneck it was meant to police.

Two properties pinned here, NEITHER by timing (this repo's ledger explicitly records
that a timing assertion on a shared CI box is a flaky test):

  1. The citation scan genuinely runs without the write gate held -- proven
     structurally by recording gate ownership from INSIDE the scan itself (a
     monkeypatched hook), so this fails loudly against the OLD (S2.4) shape, where
     the gate was held from before the first read.
  2. A scan cut short by its wall-clock budget reports `complete: False` with a
     stated reason, and every per-candidate count in that case is labelled a FLOOR
     (`distinct_citing_articles_at_least`), never presented under the complete-scan
     key (`distinct_citing_articles`) as if it were the true total.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source
from src.database.writer import write_gate


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


def _seed_citations(s, domain: str, n_articles: int) -> None:
    tag = uuid.uuid4().hex[:8]
    src = Source(name=f"D {tag}", domain=f"d-{tag}.example", language="en")
    s.add(src)
    s.flush()
    for i in range(n_articles):
        a = Article(
            url=f"https://d-{tag}.example/{i}",
            canonical_url=f"https://d-{tag}.example/{i}",
            source_id=src.id,
            title=f"Citing {i}",
            content="x " * 50,
            language="en",
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        s.add(a)
        s.flush()
        s.add(
            ArticleLink(
                article_id=a.id,
                url=f"https://{domain}/story-{i}",
                normalized_url=f"https://{domain}/story-{i}",
                link_type="external",
            )
        )
    s.commit()


# --------------------------------------------------------------------------- #
# Requirement 2: the gate must NOT be held while the citation scan runs.
# --------------------------------------------------------------------------- #


def test_run_discovery_does_not_hold_the_gate_during_the_citation_scan(db, monkeypatch):
    """Structural/observable, not timing. `registrable_domain` is called once per row
    scanned by citation_candidates (the DECIDE phase) -- a spy on it records whether
    the calling thread holds the write gate at that moment. This must fail loudly
    against the pre-fix (S2.4) shape, where the gate was acquired BEFORE the scan:
    every recorded call would then show the gate held."""
    import src.catalog.normalize as normalize_mod
    from src.discovery import channels as channels_mod

    domain = f"scan-probe-{uuid.uuid4().hex[:6]}.example"
    _seed_citations(db, domain, 4)  # >= the citation-channel minimum

    held_during_scan: list[bool] = []
    real_registrable_domain = normalize_mod.registrable_domain

    def _spy(url):
        # registrable_domain is ALSO called (with a bare domain, no scheme) by
        # is_disqualified_domain inside _add_candidate during the small, legitimately
        # GATED per-candidate apply step -- restrict this spy to the SCAN's own calls
        # (always a real URL with a scheme) so it does not conflate the two call sites.
        if isinstance(url, str) and "://" in url:
            held_during_scan.append(write_gate.held_by_current_thread())
        return real_registrable_domain(url)

    monkeypatch.setattr(normalize_mod, "registrable_domain", _spy)

    out = channels_mod.run_discovery(db, per_run=10)

    assert out.get("error") != "discovery_rolled_back", out
    assert held_during_scan, "the spy never ran -- the scan didn't happen, this test proves nothing"
    assert not any(held_during_scan), (
        "the write gate was held while the citation scan ran: "
        f"{held_during_scan.count(True)}/{len(held_during_scan)} calls saw it held"
    )
    # sanity: discovery still found the seeded domain (the fix must not disable it)
    assert domain in out["citation"]


def test_apply_source_topics_does_not_hold_the_gate_during_derive(monkeypatch):
    """The sibling property for source_topics.py (Part 3): derive_source_topics (the
    corpus-wide GROUP BY) must run before the write gate is taken. A spy wraps the
    module-level `derive_source_topics` name (the way `source_topic_candidates`
    calls it) and records gate ownership at call time -- this fails loudly against
    the pre-fix shape, where the gate was held from before this call."""
    from src.analytics import source_topics as st_mod
    from src.database.models import Keyword, KeywordMention, KeywordTag

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        src = Source(name="Src", domain="src.test", language="en")
        s.add(src)
        s.flush()
        kw = Keyword(term="election", normalized_term="election", language="en")
        s.add(kw)
        s.flush()
        s.add(KeywordTag(keyword_id=kw.id, axis="topic", tag="politics", source="baseline"))
        for i in range(6):
            a = Article(
                url=f"https://src.test/{i}",
                canonical_url=f"https://src.test/{i}",
                source_id=src.id,
                title="T",
                content="election",
                hash=f"h{i}",
                language="en",
            )
            s.add(a)
            s.flush()
            s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1, source_id=src.id))
        s.commit()

        held_during_derive: list[bool] = []
        real_derive = st_mod.derive_source_topics

        def _spy(session, **kwargs):
            held_during_derive.append(write_gate.held_by_current_thread())
            return real_derive(session, **kwargs)

        monkeypatch.setattr(st_mod, "derive_source_topics", _spy)

        result = st_mod.apply_source_topics(s, min_articles=5)

        assert result["sources_updated"] == 1
        assert held_during_derive, "the spy never ran -- the derive step didn't happen, this test proves nothing"
        assert not any(held_during_derive), (
            "the write gate was held while derive_source_topics (the corpus-wide scan) ran"
        )
    finally:
        s.close()
        engine.dispose()


# --------------------------------------------------------------------------- #
# Requirement 3: an honest partial-scan report.
# --------------------------------------------------------------------------- #


def test_partial_citation_scan_reports_incomplete_with_a_reason(db, monkeypatch):
    """A tiny effective budget cuts the scan short mid-way (deterministic via a fake
    monotonic clock, NEVER real timing): `complete` is False, a reason is stated, and
    the rows-scanned count is less than the true total -- proving it really is a
    floor, not the true count."""
    from src.discovery.channels import citation_candidates

    domain = f"partial-{uuid.uuid4().hex[:6]}.example"
    total_citations = 8
    _seed_citations(db, domain, total_citations)  # 8 distinct citing articles

    calls = {"n": 0}

    def fake_monotonic():
        calls["n"] += 1
        # call #1 computes the deadline; calls #2-#5 (four row-checks) stay within
        # budget; call #6 onward blows past it -- lets exactly 5 of the 8 rows be
        # scanned before the cutoff, so the scan is genuinely, provably partial.
        return 0.0 if calls["n"] <= 5 else 1_000_000.0

    monkeypatch.setattr("time.monotonic", fake_monotonic)

    result = citation_candidates(db, cap=10, budget_s=1.0)

    assert result["complete"] is False
    assert result["reason"], "an incomplete scan must state why"
    assert "budget" in result["reason"].lower()
    assert 0 < result["rows_scanned"] < total_citations, (
        f"expected a genuine partial scan (some but not all of {total_citations} rows), "
        f"got rows_scanned={result['rows_scanned']}"
    )

    assert result["decisions"], "not enough rows were scanned to produce a decision"
    for d in result["decisions"]:
        ev = d["evidence"]
        assert "distinct_citing_articles" not in ev, (
            "a partial scan must never use the complete-scan count key"
        )
        assert "distinct_citing_articles_at_least" in ev, "the count must be labelled as a floor"
        assert ev["distinct_citing_articles_at_least"] < total_citations, (
            "the floor must genuinely be less than the true total, or this test proves nothing"
        )
        assert "rows_scanned" in ev
        assert "partial" in ev["reason"].lower() or "floor" in ev["reason"].lower()


def test_complete_citation_scan_uses_the_definite_count_key(db):
    """Negative control: when the scan finishes within budget, the ordinary
    (non-floor) evidence key is used -- the floor-labelling above is conditional on
    genuine incompleteness, not always-on."""
    from src.discovery.channels import citation_candidates

    domain = f"complete-{uuid.uuid4().hex[:6]}.example"
    _seed_citations(db, domain, 4)

    result = citation_candidates(db, cap=10, budget_s=30.0)  # ample budget

    assert result["complete"] is True
    assert result["reason"] is None
    decisions = [d for d in result["decisions"] if d["domain"] == domain]
    assert len(decisions) == 1
    ev = decisions[0]["evidence"]
    assert ev["distinct_citing_articles"] == 4
    assert "distinct_citing_articles_at_least" not in ev
