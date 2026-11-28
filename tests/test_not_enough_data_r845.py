"""R845 (row 452): no verdict until a source has at least 5 stored articles and its newest article,
by the article's OWN published date, is at most 180 days old.

Until then the attempt is ``not_enough_data``, logged like ``no_evidence``: ``Source.status`` and
``enabled`` untouched, the ladder neither advanced nor reset, the re-verification clock unmoved. The
fetch date never counts and an undated article never makes a source recent; the summary says how many
of the sources it names have no dated article at all.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from src.analytics import source_audit as sa
from src.catalog import qualification as q
from src.database.models import Article, Base, Source, SourceQualificationAttempt
from tests._app_engine import app_sqlite_engine

NOW = datetime(2026, 11, 28, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_recheck_once(monkeypatch):
    # R850's one-time choice is pinned on its own; nothing here is disqualified by link density.
    monkeypatch.setattr(q, "_recheck_once_owed", lambda: False)


@pytest.fixture()
def db():
    engine = app_sqlite_engine(":memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


_N = [0]


def _source(db, domain, *, status=q.STATUS_UNQUALIFIED, enabled=None):
    s = Source(name=domain, domain=domain, status=status, enabled=enabled)
    db.add(s)
    db.commit()
    return s


def _articles(db, source, n, *, days_old=None, quarantined=False):
    """``n`` stored articles; published ``days_old`` days before NOW, or undated when it is None."""
    for _ in range(n):
        _N[0] += 1
        url = f"https://{source.domain}/{_N[0]}"
        published = None if days_old is None else (NOW - timedelta(days=days_old)).replace(tzinfo=None)
        db.add(Article(url=url, canonical_url=url, source_id=source.id, content="body text " * 20,
                       hash=f"r845-{_N[0]}", published_at=published, quarantined=quarantined))
    db.commit()


def _attempt(db, source, verdict, *, days_ago):
    db.add(SourceQualificationAttempt(source_id=source.id, verdict=verdict, criteria_version="t",
                                      attempted_at=(NOW - timedelta(days=days_ago)).replace(tzinfo=None)))
    db.commit()


def _frozen():
    return {"min_articles": 1, "cohort_cut": None, "cohort": {"baselines": {}, "lang_short_cut": {}},
            "token": "t", "articles": 0, "sources": 0, "furniture_df": None}


@pytest.fixture()
def judge_clean(monkeypatch):
    """Every source with stored articles reads as clean, so the gate alone decides what is judged."""
    def scoped(session, ids, frozen, **_kw):
        have = {int(sid) for (sid,) in session.query(Article.source_id).filter(Article.source_id.in_(ids)).distinct()}
        return {sid: {"article_count": 1} for sid in have}

    monkeypatch.setattr(sa, "scoped_metrics", scoped)
    monkeypatch.setattr(sa, "flag_criteria", lambda per, **_kw: {})


def _pass(db, **kw):
    return q.run_qualification_pass(db, None, now=NOW, cohort_provider=_frozen, **kw)


# ---- the gate itself --------------------------------------------------------------------------


def test_five_recent_articles_are_enough_and_four_are_not(db):
    four, five = _source(db, "four.example"), _source(db, "five.example")
    _articles(db, four, 4, days_old=3)
    _articles(db, five, 5, days_old=3)
    short = q.evidence_shortfall(db, [four.id, five.id], now=NOW)
    assert set(short) == {four.id}
    assert short[four.id]["articles"] == 4 and short[four.id]["dated"] == 4


def test_a_newest_article_older_than_180_days_is_not_recent(db):
    old, edge = _source(db, "old.example"), _source(db, "edge.example")
    _articles(db, old, 9, days_old=181)
    _articles(db, edge, 9, days_old=180)
    assert set(q.evidence_shortfall(db, [old.id, edge.id], now=NOW)) == {old.id}


def test_undated_articles_never_make_a_source_recent(db):
    undated = _source(db, "undated.example")
    _articles(db, undated, 20)
    got = q.evidence_shortfall(db, [undated.id], now=NOW)[undated.id]
    assert got == {"articles": 20, "dated": 0, "newest": None}


def test_one_recent_dated_article_among_undated_ones_is_enough(db):
    mixed = _source(db, "mixed.example")
    _articles(db, mixed, 6)
    _articles(db, mixed, 1, days_old=10)
    assert q.evidence_shortfall(db, [mixed.id], now=NOW) == {}


def test_a_date_after_now_is_no_date(db):
    future = _source(db, "future.example")
    _articles(db, future, 6, days_old=-30)
    assert q.evidence_shortfall(db, [future.id], now=NOW)[future.id]["dated"] == 0


def test_quarantined_articles_do_not_count(db):
    s = _source(db, "q.example")
    _articles(db, s, 4, days_old=2)
    _articles(db, s, 5, days_old=2, quarantined=True)
    assert q.evidence_shortfall(db, [s.id], now=NOW)[s.id]["articles"] == 4


def test_the_gate_writes_nothing(db):
    s = _source(db, "w.example")
    _articles(db, s, 2, days_old=1)
    before = db.query(SourceQualificationAttempt).count()
    q.evidence_shortfall(db, [s.id], now=NOW)
    assert not db.new and not db.dirty and db.query(SourceQualificationAttempt).count() == before


# ---- the pass -----------------------------------------------------------------------------------


def test_a_thin_candidate_gets_no_verdict_and_keeps_everything(db, judge_clean):
    thin, ready = _source(db, "thin.example", enabled=False), _source(db, "ready.example", enabled=False)
    _articles(db, thin, 3, days_old=1)
    _articles(db, ready, 5, days_old=1)
    out = _pass(db, per_pass=5, recheck_per_pass=0)
    assert out["not_enough_data"] == 1 and out["not_enough_data_undated"] == 0
    db.refresh(thin)
    db.refresh(ready)
    assert thin.status == q.STATUS_UNQUALIFIED and thin.enabled is False and thin.qualified_at is None
    assert ready.status == q.STATUS_QUALIFIED and ready.enabled is True, "the control: a verdict would flip it"
    verdicts = [a.verdict for a in db.query(SourceQualificationAttempt).filter_by(source_id=thin.id)]
    assert verdicts == [q.VERDICT_NOT_ENOUGH_DATA]


def test_the_pass_counts_the_sources_with_no_dated_article(db, judge_clean):
    a, b = _source(db, "a.example"), _source(db, "b.example")
    _articles(db, a, 8)
    _articles(db, b, 2, days_old=5)
    out = _pass(db, per_pass=5, recheck_per_pass=0)
    assert out["not_enough_data"] == 2 and out["not_enough_data_undated"] == 1


def test_a_stale_qualified_source_stays_qualified_and_its_clock_does_not_move(db, judge_clean):
    stamped = (NOW - timedelta(days=200)).replace(tzinfo=None)
    s = _source(db, "stale.example", status=q.STATUS_QUALIFIED, enabled=True)
    s.qualified_at = stamped
    s.qualification_criteria_version = "oo-source-qualification-3"
    db.commit()
    _attempt(db, s, q.STATUS_QUALIFIED, days_ago=200)
    _articles(db, s, 30, days_old=200)
    assert [x.id for x in q.select_due_qualified(db, now=NOW, limit=5)] == [s.id]
    out = _pass(db, per_pass=0, recheck_per_pass=2)
    assert out["not_enough_data"] == 1
    db.refresh(s)
    assert s.status == q.STATUS_QUALIFIED and s.enabled is True
    assert s.qualified_at == stamped and s.qualification_criteria_version == "oo-source-qualification-3"
    # the clock is the old judgement still ...
    clock = db.query(q._last_clock_subquery(db)).filter_by(source_id=s.id).one().last_at
    assert clock == stamped
    # ... so it stays due, but is not tried again until EVIDENCE_RETRY_DAYS have passed
    assert q.select_due_qualified(db, now=NOW + timedelta(days=1), limit=5) == []
    later = NOW + timedelta(days=q.EVIDENCE_RETRY_DAYS + 1)
    assert [x.id for x in q.select_due_qualified(db, now=later, limit=5)] == [s.id]


def test_a_disqualified_source_keeps_its_ladder_place(db, judge_clean):
    s = _source(db, "dq.example", status=q.STATUS_DISQUALIFIED, enabled=True)
    _attempt(db, s, q.STATUS_DISQUALIFIED, days_ago=70)
    _attempt(db, s, q.STATUS_DISQUALIFIED, days_ago=40)  # second rung: due 2 months after this one
    _articles(db, s, 2, days_old=1)
    later = NOW + timedelta(days=25)
    assert [x.id for x in q.select_due_disqualified(db, now=later, limit=5)] == [s.id]
    q.run_qualification_pass(db, None, now=later, cohort_provider=_frozen, per_pass=0, recheck_per_pass=2)
    db.refresh(s)
    assert s.status == q.STATUS_DISQUALIFIED and s.enabled is True
    assert q.consecutive_disqualifications(db, s.id) == 2, "the ladder neither advanced nor reset"
    assert q.select_due_disqualified(db, now=later + timedelta(days=1), limit=5) == []
    retry = later + timedelta(days=q.EVIDENCE_RETRY_DAYS + 1)
    assert [x.id for x in q.select_due_disqualified(db, now=retry, limit=5)] == [s.id], "due again on its old clock"


def test_the_ladder_skips_the_verdict_like_no_evidence():
    v = [q.VERDICT_NOT_ENOUGH_DATA, q.STATUS_DISQUALIFIED, q.VERDICT_NOT_ENOUGH_DATA, q.STATUS_DISQUALIFIED]
    assert q.consecutive_disqualifications_from_verdicts(v) == 2
    assert q.VERDICT_NOT_ENOUGH_DATA not in q.JUDGING_VERDICTS and q.VERDICT_NOT_ENOUGH_DATA not in q.CLOCK_VERDICTS


def test_thin_candidates_never_starve_a_fresh_one(db, judge_clean):
    stuck = [_source(db, f"stuck{i}.example") for i in range(3)]
    for s in stuck:
        _articles(db, s, 1, days_old=1)
    _pass(db, per_pass=3, recheck_per_pass=0)
    fresh = _source(db, "fresh.example")
    _articles(db, fresh, 5, days_old=1)
    _pass(db, per_pass=1, recheck_per_pass=0)
    db.refresh(fresh)
    assert fresh.status == q.STATUS_QUALIFIED


def test_the_version_names_the_gate():
    assert q.CRITERIA_VERSION == "oo-source-qualification-5"
    assert (q.EVIDENCE_MIN_ARTICLES, q.EVIDENCE_RECENT_DAYS) == (5, 180)


# ---- what the user sees -------------------------------------------------------------------------


def test_the_sources_panel_shows_the_latest_attempt_beside_the_status(db):
    from src.discovery.source_trail import _latest_attempt_note

    s = _source(db, "panel.example", status=q.STATUS_QUALIFIED, enabled=True)
    _attempt(db, s, q.STATUS_QUALIFIED, days_ago=100)
    assert _latest_attempt_note(db, s) is None
    _attempt(db, s, q.VERDICT_NOT_ENOUGH_DATA, days_ago=1)
    assert _latest_attempt_note(db, s) == "not_enough_data"
    _attempt(db, s, q.STATUS_QUALIFIED, days_ago=0)
    assert _latest_attempt_note(db, s) is None


_STRINGS = (
    "not enough data yet",
    "Fewer than 5 articles, or none in the last 180 days: no pass or fail is given until there are.",
    "{n} source with not enough data yet",
    "{n} sources with not enough data yet",
    "{n} source with not enough data yet (it has no dated articles)",
    "{n} sources with not enough data yet ({m} of them have no dated articles)",
)


def test_every_string_is_in_every_language_and_used():
    for f in sorted((ROOT / "src/static/locales").glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for key in _STRINGS:
            assert data.get(key), (f.name, key)
            for var in ("{n}", "{m}"):
                if var in key and f.stem != "ar" and f.stem != "ru":
                    assert var in data[key], (f.name, key, var)
    js = (ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    src_js = (ROOT / "src/static/app-sources.js").read_text(encoding="utf-8")
    assert all(k in js for k in _STRINGS[2:]) and all(k in src_js for k in _STRINGS[:2])
    assert "_qualNotEnough(r.not_enough_data, r.not_enough_data_undated)" in js
    assert 'prov.qualification_latest_attempt === "not_enough_data"' in src_js

