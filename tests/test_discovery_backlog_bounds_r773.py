"""World discovery waits for the candidates nobody has checked, and judging takes the likeliest first (R773 (2), (4); row 249).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 11-14 field press held 25,281 discovered sources, every one with 0 articles: discovery added a country's finds in one
go, two countries a pass, while qualification judged five candidates a pass. These pin the bounds that make discovery
wait (a global one that pauses the ride-along and resumes it by itself, a per-country one that passes a country over),
that nothing is ever deleted, the order in which the line is judged, and the measured pace the time estimate is built on.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.backlog import discovery_gate, judging_pace, unjudged_backlog, unjudged_by_country
from src.catalog.discover_job import advance_world_discovery, load_state
from src.catalog.qualification import select_unqualified
from src.database.models import Base, Source, SourceQualificationAttempt


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def scope(db):
    @contextmanager
    def _scope():
        yield db
        db.commit()

    return _scope


def _add(db, n, *, country, prefix, status="unqualified", rss=None, enabled=False):
    for i in range(n):
        db.add(Source(name=f"{prefix}{i}", domain=f"{prefix}{i}.example", country=country, status=status,
                      enabled=enabled, rss_url=rss))
    db.commit()


def _rq(calls):
    def run_query(cc, type_qids):
        calls.append(cc)
        return {"results": {"bindings": [
            {"itemLabel": {"value": f"New {cc}"}, "website": {"value": f"https://new-{cc}.example/"}}]}}
    return run_query


def _advance(scope, tmp_path, calls, **kw):
    """One ride-along pass over the real world list (sorted ISO codes: ad, ae, af, ...), two countries a pass."""
    return advance_world_discovery(per_pass=2, run_query=_rq(calls), session_factory=scope,
                                   state_path=tmp_path / "wd.json", sleep_s=0, **kw)


def _asked(calls):
    """The countries asked, in order (each country is asked once per query spec)."""
    return list(dict.fromkeys(calls))


def test_the_ride_along_pauses_at_the_global_bound_and_resumes_by_itself_below_it(db, scope, tmp_path):
    _add(db, 5, country="fr", prefix="c")
    calls: list[str] = []
    paused = _advance(scope, tmp_path, calls, backlog_bound=5)
    assert paused["skipped"] == "backlog" and paused["backlog"] == 5 and paused["bound"] == 5
    assert calls == [], "a paused ride-along asks Wikidata nothing"
    assert not load_state(tmp_path / "wd.json").get("done"), "and moves no cursor"
    assert unjudged_backlog(db) == 5, "nothing is deleted"

    # Judging one candidate brings the line below the bound: the next pass runs, with no click.
    db.query(Source).filter_by(domain="c0.example").update({"status": "qualified"})
    db.commit()
    resumed = _advance(scope, tmp_path, calls, backlog_bound=5)
    assert "skipped" not in resumed and _asked(calls) == ["ad", "ae"]
    assert db.query(Source).filter(Source.domain.like("c%.example")).count() == 5


def test_a_bound_of_zero_switches_it_off(db, scope, tmp_path):
    _add(db, 50, country="ad", prefix="c")
    calls: list[str] = []
    res = _advance(scope, tmp_path, calls, backlog_bound=0, country_backlog_bound=0)
    assert "skipped" not in res and "held_countries" not in res and _asked(calls) == ["ad", "ae"]


def test_a_country_at_its_own_bound_is_passed_over_and_asked_again_once_it_drains(db, scope, tmp_path):
    _add(db, 3, country="ad", prefix="k")
    calls: list[str] = []
    res = _advance(scope, tmp_path, calls, backlog_bound=100, country_backlog_bound=3)
    assert res["held_countries"] == ["ad"]
    assert _asked(calls) == ["ae", "af"], "the held country does not use one of the pass's two slots"
    assert "ad" not in load_state(tmp_path / "wd.json")["done"], "a held country is never marked done"

    db.query(Source).filter_by(domain="k0.example").update({"status": "disqualified"})
    db.commit()
    calls.clear()
    again = _advance(scope, tmp_path, calls, backlog_bound=100, country_backlog_bound=3)
    assert "held_countries" not in again and _asked(calls)[0] == "ad"


def test_the_gate_names_the_held_countries_largest_first(db):
    _add(db, 4, country="jp", prefix="j")
    _add(db, 6, country="fr", prefix="f")
    _add(db, 1, country="ke", prefix="k")
    _add(db, 9, country=None, prefix="x")
    g = discovery_gate(db, bound=100, country_bound=4)
    assert g == {"paused": False, "backlog": 20, "bound": 100, "country_bound": 4,
                 "held_countries": [{"country": "fr", "unjudged": 6}, {"country": "jp", "unjudged": 4}],
                 "tried_without_evidence": 0}
    assert unjudged_by_country(db) == {"fr": 6, "jp": 4, "ke": 1}


def test_the_line_is_judged_untried_first_then_known_feed_then_country_gaps(db):
    _add(db, 2, country="fr", prefix="fr-ok", status="qualified", enabled=True)  # France is already collected
    _add(db, 1, country="fr", prefix="fr-new")
    _add(db, 1, country="ke", prefix="ke-new")                                  # Kenya has nothing collected
    _add(db, 1, country=None, prefix="nowhere")
    _add(db, 1, country="fr", prefix="fr-feed", rss="https://fr-feed0.example/rss")
    _add(db, 1, country="ke", prefix="ke-tried", rss="https://ke-tried0.example/rss")
    tried = db.query(Source).filter_by(domain="ke-tried0.example").one()
    # a no-evidence attempt is logged with a non-judging verdict (it sends the source behind the untried ones)
    db.add(SourceQualificationAttempt(source_id=tried.id, attempted_at=datetime.now(UTC), verdict="no_evidence",
                                      criteria_version="t"))
    db.commit()
    order = [s.domain for s in select_unqualified(db, limit=10)]
    assert order == ["fr-feed0.example", "ke-new0.example", "fr-new0.example", "nowhere0.example", "ke-tried0.example"]


def test_the_pace_is_measured_from_first_verdicts_and_gives_no_date_without_one(db):
    now = datetime(2026, 11, 21, 12, tzinfo=UTC)
    none = judging_pace(db, backlog=100, now=now)
    assert none["judged"] == 0 and none["eta_days"] is None
    _add(db, 3, country="fr", prefix="s", status="qualified")
    ids = [s.id for s in db.query(Source).all()]
    for sid in ids[:2]:  # first verdicts inside the window
        db.add(SourceQualificationAttempt(source_id=sid, attempted_at=now - timedelta(days=1), verdict="qualified",
                                          criteria_version="t"))
    # a re-check of an old verdict is not a departure from the line
    db.add(SourceQualificationAttempt(source_id=ids[2], attempted_at=now - timedelta(days=30), verdict="disqualified",
                                      criteria_version="t"))
    db.add(SourceQualificationAttempt(source_id=ids[2], attempted_at=now - timedelta(days=1), verdict="qualified",
                                      criteria_version="t"))
    db.commit()
    p = judging_pace(db, backlog=7, now=now)
    assert p["judged"] == 2 and p["per_day"] == pytest.approx(2 / 7, abs=0.05) and p["eta_days"] == pytest.approx(24.5)


def test_a_candidate_a_trial_already_reached_never_holds_discovery(db):
    """Security read 2 (S3): a site tried that gave nothing to judge stays unchecked and is tried again later by the
    ladder; counting it would let a run of silent sites hold discovery for good and make the estimate promise a drain
    judging cannot deliver. It is counted on its own line instead, and no row is deleted."""
    _add(db, 3, country="fr", prefix="new")
    _add(db, 2, country="fr", prefix="silent")
    for s in db.query(Source).filter(Source.name.like("silent%")).all():
        db.add(SourceQualificationAttempt(source_id=s.id, attempted_at=datetime.now(UTC), verdict="no_evidence",
                                          criteria_version="t"))
    db.commit()
    assert unjudged_backlog(db) == 3
    assert unjudged_by_country(db) == {"fr": 3}
    g = discovery_gate(db, bound=4, country_bound=3)
    assert g["paused"] is False and g["backlog"] == 3 and g["tried_without_evidence"] == 2
    assert g["held_countries"] == [{"country": "fr", "unjudged": 3}]
    assert discovery_gate(db, bound=3, country_bound=0)["paused"] is True
    assert db.query(Source).count() == 5


def test_the_pace_counts_first_checks_and_divides_by_the_days_the_records_cover(db):
    """Security read 2 (S3, N1): leaving the backlog is a source's FIRST attempt, whatever its verdict; and an install
    whose records are two days old divides by two, never by the seven-day window, so the rate is not understated."""
    now = datetime(2026, 11, 21, 12, tzinfo=UTC)
    _add(db, 4, country="fr", prefix="s")
    ids = [s.id for s in db.query(Source).all()]
    for sid, verdict in zip(ids, ("qualified", "disqualified", "no_evidence", "no_evidence"), strict=True):
        db.add(SourceQualificationAttempt(source_id=sid, attempted_at=now - timedelta(days=2), verdict=verdict,
                                          criteria_version="t"))
    db.commit()
    p = judging_pace(db, backlog=10, now=now)
    assert p["judged"] == 4 and p["per_day"] == pytest.approx(2.0) and p["eta_days"] == pytest.approx(5.0)
    young = judging_pace(db, backlog=10, now=now - timedelta(days=2) + timedelta(hours=3))
    assert young["per_day"] == pytest.approx(4.0), "never divided by less than one day"
