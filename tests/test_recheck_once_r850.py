"""R850 / R851 (row 449, amending R844): one re-check for each source that link density alone disqualified.

Nothing stored says why a source was disqualified, so the sources are CHOSEN BY RECOMPUTING the criteria, read-only, from
their stored articles with the same ``flag_criteria`` call a re-check runs. Too few stored articles to recompute is "not
determined": the source stays on its ladder. A chosen source is made due ONCE through ``select_due_disqualified``, so it is
judged in an ordinary pass (that pass's consent, transport, pacing and per-host limits; nothing while qualification is off),
and the selection itself runs inside a pass from the cohort the pass froze, once per install.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from src.analytics import source_audit as sa
from src.catalog import qualification as q
from src.database.models import Base, Source, SourceQualificationAttempt
from tests._app_engine import app_sqlite_engine

NOW = datetime(2026, 11, 28, tzinfo=UTC)
JUDGED = NOW - timedelta(days=3)          # well inside the first ladder step: not due on its own


@pytest.fixture()
def db():
    engine = app_sqlite_engine(":memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def store(monkeypatch):
    data: dict[str, dict] = {}
    import src.config.kv_store as kv

    monkeypatch.setattr(kv, "kv_get_json", lambda key: copy.deepcopy(data.get(key)))
    monkeypatch.setattr(kv, "kv_get_json_strict", lambda key: copy.deepcopy(data.get(key)))
    monkeypatch.setattr(kv, "kv_set_json", lambda key, obj: data.__setitem__(key, copy.deepcopy(obj)))
    return data


def _disqualified(db, domain):
    s = Source(name=domain, domain=domain, status=q.STATUS_DISQUALIFIED, enabled=True)
    db.add(s)
    db.commit()
    db.add(SourceQualificationAttempt(source_id=s.id, attempted_at=JUDGED, verdict=q.STATUS_DISQUALIFIED,
                                      criteria_version="oo-source-qualification-3"))
    db.commit()
    return s


def _m(sid, *, n=200, link=0.0, path=0.0, short=0.1):
    return {"domain": f"s{sid}.example", "language": "en", "region": "gb", "article_count": n, "dominant_lang": "en",
            "outlier_rate": 0.1, "pathology_rate": path, "pathology_articles": round(path * n), "link_density_rate": link,
            "link_dense_articles": round(link * n), "language_mismatch_rate": 0.0, "short_article_rate": short,
            "furniture_share": 0.1}


def _frozen():
    return {"min_articles": 1, "cohort_cut": None, "cohort": {"baselines": {}, "lang_short_cut": {}},
            "token": "t", "articles": 0, "sources": 0, "furniture_df": None}


@pytest.fixture()
def four(db, monkeypatch):
    """Four disqualified sources: link density only, pathology too, nothing flagged now, and one with 3 articles."""
    link, both, clean, thin = (_disqualified(db, d) for d in ("link.example", "both.example", "clean.example", "thin.example"))
    cohort = {1000 + i: _m(1000 + i) for i in range(40)}  # large enough that two link-dense sources stay in the tail

    def fake_scoped(session, ids, frozen, **_kw):
        per = {link.id: _m(link.id, link=0.6), both.id: _m(both.id, link=0.6, path=0.6),
               clean.id: _m(clean.id), thin.id: _m(thin.id, n=3, link=1.0)}
        return {sid: m for sid, m in {**per, **cohort}.items() if sid in ids or sid in cohort}

    real_flag = sa.flag_criteria
    monkeypatch.setattr(sa, "scoped_metrics", fake_scoped)
    # the cohort rides along so the tail has something to compare with, as it does in a real pass
    monkeypatch.setattr(sa, "flag_criteria", lambda per, **kw: real_flag({**cohort, **per}, cohort_floor=8, min_articles=20))
    return link, both, clean, thin


def test_the_selection_chooses_link_density_alone_and_counts_the_thin_as_not_determined(db, four):
    link, both, clean, thin = four
    sel = q.select_link_density_only(db, _frozen())
    assert sel["chosen"] == [link.id], "only the source whose ONLY extraction-failure criterion is link density"
    assert sel["not_determined"] == [thin.id], "too few stored articles to recompute: stays on its ladder"


def test_the_selection_writes_nothing(db, four):
    writes: list[str] = []

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _watch(conn, cursor, statement, *_a):
        if statement.lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
            writes.append(statement)

    before = [(s.id, s.status, s.enabled, s.qualified_at) for s in db.query(Source).order_by(Source.id)]
    attempts = db.query(SourceQualificationAttempt).count()
    q.select_link_density_only(db, _frozen())
    db.commit()
    assert writes == [], "no article, attempt row or stamp is written by the recompute"
    assert [(s.id, s.status, s.enabled, s.qualified_at) for s in db.query(Source).order_by(Source.id)] == before
    assert db.query(SourceQualificationAttempt).count() == attempts


def test_a_chosen_source_is_due_once_ahead_of_its_ladder_then_back_on_it(db, store, four):
    link, both, clean, thin = four
    assert q.select_due_disqualified(db, now=NOW, limit=10) == [], "nothing is due on its ladder yet"
    q.store_recheck_once(q.select_link_density_only(db, _frozen()), now=NOW)
    assert [s.id for s in q.select_due_disqualified(db, now=NOW, limit=10)] == [link.id]
    q.record_recheck_once_tries({link.id}, now=NOW)
    assert q.select_due_disqualified(db, now=NOW, limit=10) == [], "once: after its re-check it is on its ladder again"
    assert q.recheck_once_counts() == {
        "selected": True, "selection": q.RECHECK_ONCE_SELECTION, "label": "chosen by recomputing from stored articles",
        "selected_at": "2026-11-28T00:00:00", "chosen": 1, "rechecked": 1, "not_determined": 1,
    }


def test_the_same_rule_never_chooses_again_and_a_requalified_source_is_not_forced(db, store, four):
    link = four[0]
    q.store_recheck_once(q.select_link_density_only(db, _frozen()), now=NOW)
    q.record_recheck_once_tries({link.id}, now=NOW)
    stored = q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW + timedelta(days=1))
    assert stored["chosen"] == 1 and stored["rechecked"] == 1, "a stored selection by today's rule is not run again"
    # a chosen source that is no longer disqualified (re-qualified some other way) is not made due
    store[q.RECHECK_ONCE_KEY]["entries"][str(link.id)]["tried_at"] = None
    link.status = q.STATUS_QUALIFIED
    db.commit()
    assert q.pending_recheck_once(db) == []


def test_an_unreadable_selection_makes_nothing_due(db, monkeypatch, four):
    import src.config.kv_store as kv

    def boom(_key):
        raise RuntimeError("locked")

    monkeypatch.setattr(kv, "kv_get_json", boom)
    assert q.pending_recheck_once(db) == []
    assert q.select_due_disqualified(db, now=NOW, limit=10) == []


def test_a_paused_selection_stores_nothing_and_is_tried_next_pass(db, store, monkeypatch, four):
    from src.analytics import source_quality as sq

    def paused(*_a, **_kw):
        raise sq.ScanPaused("memory")

    monkeypatch.setattr(sa, "scoped_metrics", paused)
    out = q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW)
    assert out["selected"] is False and q.RECHECK_ONCE_KEY not in store


def test_the_pass_runs_the_selection_and_takes_the_chosen_first(db, store, four):
    """Through the ordinary pass: no fetcher (no network here), the cohort injected, so what is exercised is the choice and
    the scheduling. The first pass chooses; the next pass takes the chosen source although its ladder is not due."""
    link = four[0]
    first = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_frozen)
    # nothing was due, so the pass had nobody to judge and returned before freezing a cohort: the choice waits
    assert first == {"enabled": True, "evaluated": 0}
    db.add(Source(name="new.example", domain="new.example", status=q.STATUS_UNQUALIFIED, enabled=True))
    db.commit()
    second = q.run_qualification_pass(db, None, per_pass=1, recheck_per_pass=2, now=NOW, cohort_provider=_frozen)
    assert second["recheck_once"]["chosen"] == 1 and second["recheck_once"]["rechecked"] == 0
    third = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_frozen)
    assert third["evaluated"] == 1
    tried = db.query(SourceQualificationAttempt).filter(SourceQualificationAttempt.source_id == link.id).count()
    assert tried == 2, "its one re-check was judged in an ordinary pass"
    assert third["recheck_once"]["rechecked"] == 1


def test_the_real_recompute_reads_and_writes_nothing():
    """The same, with nothing faked: the real cohort freeze and the real scoped read over stored articles."""
    from tests.test_source_qualification import (
        _add_candidate_with_articles,
        _engine_session,
        _seed_healthy_en_cohort,
    )

    s = _engine_session()
    _seed_healthy_en_cohort(s)
    thin = _add_candidate_with_articles(s, domain="thin.example", status=q.STATUS_DISQUALIFIED, pathology=False)
    frozen = sa.frozen_cohort(s, min_articles=q.TRIAL_MIN_ARTICLES)
    s.commit()
    writes: list[str] = []

    @event.listens_for(s.get_bind(), "before_cursor_execute")
    def _watch(conn, cursor, statement, *_a):
        if statement.lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP"):
            writes.append(statement)

    sel = q.select_link_density_only(s, frozen)
    s.commit()
    assert writes == []
    assert sel == {"chosen": [], "not_determined": [thin.id]}, "three stored articles are too few to recompute"
