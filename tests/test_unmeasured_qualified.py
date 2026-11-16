"""R728 C: never-measured qualified sources are judged offline from their stored articles.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The field test (2026-11-14, report 5.3) found 6,411 curated sources and 0 measured on every instance.
These sources now take the re-check slots the due queues leave unused, inside the same budget, and no
request is made for them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.catalog import qualification as q
from src.database.models import Article, Base, Source, SourceQualificationAttempt

_BODY = "Real article text with enough words to read as an article. " * 20
_N = 0


@pytest.fixture
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, autoflush=False)


def _curated(s, domain: str, n_articles: int, *, enabled: bool = True) -> int:
    global _N
    src = Source(name=domain, domain=domain, enabled=enabled, status=q.STATUS_QUALIFIED,
                 qualified_at=datetime(2026, 11, 1), qualification_criteria_version=q.CURATED_CRITERIA_VERSION)
    s.add(src)
    s.commit()
    s.add(SourceQualificationAttempt(source_id=src.id, attempted_at=datetime(2026, 11, 1),
                                     verdict=q.VERDICT_CURATED, criteria_version=q.CURATED_CRITERIA_VERSION))
    for _ in range(n_articles):
        _N += 1
        url = f"https://{domain}/a/{_N}"
        s.add(Article(url=url, canonical_url=url, source_id=src.id, content=_BODY, hash=f"u{_N}",
                      word_count=200, language="en", title=f"Title {_N}", fetched_host=domain))
    s.commit()
    return int(src.id)


def _verdicts(s, sid):
    return [v for (v,) in s.query(SourceQualificationAttempt.verdict).filter_by(source_id=sid)
            .order_by(SourceQualificationAttempt.id)]


def test_pool_takes_only_enabled_never_judged_sources_with_enough_stored_pages(Session):
    with Session() as s:
        ok = _curated(s, "a.example.org", 12)
        _curated(s, "few.example.org", 5)
        _curated(s, "off.example.org", 12, enabled=False)
        judged = _curated(s, "judged.example.org", 12)
        s.add(SourceQualificationAttempt(source_id=judged, attempted_at=datetime(2026, 11, 2),
                                         verdict=q.STATUS_QUALIFIED, criteria_version=q.CRITERIA_VERSION))
        s.commit()
        assert [int(x.id) for x in q.select_unmeasured_qualified(s, limit=10)] == [ok]
        assert q.select_unmeasured_qualified(s, limit=0) == []


def test_judged_offline_inside_the_recheck_budget(Session, monkeypatch):
    tried: list[int] = []
    monkeypatch.setattr(q, "trial_fetch", lambda session, source, fetcher: tried.append(int(source.id)))
    with Session() as s:
        sid = _curated(s, "b.example.org", 12)
        out = q.run_qualification_pass(s, object(), per_pass=0, recheck_per_pass=2,
                                       now=datetime.now(UTC))
        assert out.get("unmeasured_judged") == 1, out
        assert tried == []  # no request made for it
        assert _verdicts(s, sid)[-1] in q.JUDGING_VERDICTS
        # Judged once, it leaves the pool.
        assert q.select_unmeasured_qualified(s, limit=10) == []


def test_off_means_off(Session, monkeypatch):
    monkeypatch.setattr(q, "trial_fetch", lambda *a, **k: None)
    with Session() as s:
        sid = _curated(s, "c.example.org", 12)
        out = q.run_qualification_pass(s, object(), per_pass=1, recheck_per_pass=0,
                                       now=datetime.now(UTC))
        assert out.get("unmeasured_judged", 0) == 0
        assert _verdicts(s, sid) == [q.VERDICT_CURATED]


def test_sources_with_too_few_pages_never_block_the_pool(Session):
    # The livelock a Python filter after the LIMIT had: low ids with few pages, tied on the curated stamp.
    with Session() as s:
        for i in range(10):
            _curated(s, f"thin{i}.example.org", 3)
        ok = _curated(s, "rich.example.org", 12)
        assert [int(x.id) for x in q.select_unmeasured_qualified(s, limit=1)] == [ok]
        assert q.select_unmeasured_qualified(s, limit=1, exclude={ok}) == []


def test_offline_ones_are_judged_even_when_the_trial_budget_is_spent(Session, monkeypatch):
    monkeypatch.setattr(q, "trial_fetch", lambda *a, **k: None)
    monkeypatch.setattr(q, "_TRIAL_FETCH_BUDGET_S", -1.0)
    with Session() as s:
        s.add(Source(name="new", domain="new.example.org", enabled=True, status=q.STATUS_UNQUALIFIED))
        s.add(Source(name="new2", domain="new2.example.org", enabled=True, status=q.STATUS_UNQUALIFIED))
        s.commit()
        sid = _curated(s, "d.example.org", 12)
        # Two trial candidates and a spent budget: the second trial is deferred, the offline one is not.
        out = q.run_qualification_pass(s, object(), per_pass=2, recheck_per_pass=2, now=datetime.now(UTC))
        assert out.get("deferred") == 1, out
        assert out.get("unmeasured_judged") == 1, out
        assert _verdicts(s, sid)[-1] in q.JUDGING_VERDICTS
