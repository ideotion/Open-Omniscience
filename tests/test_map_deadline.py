"""GET /api/insights/map has a deadline, a cache keyed on the corpus epoch, and says when it is partial.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before 2026-10-16 the endpoint called ``q.map_data`` directly: no statement deadline, no cache, no rollup, so every
open of the map ran two scans of the window's mentions (neither ``country`` nor ``city`` is indexed) on a held worker.
The cost on a 12 M-mention corpus was inferred, not measured. These tests pin the three things the endpoint now does:
it is answered from a cache until the corpus epoch moves, a failure or a partial answer is replayed for the short
window instead of being rescanned, and a country list that spent the budget leaves the city list OUT and says so.

SIZE OF THE GENERATED CORPUS (the timing test): 200,000 mentions over 400 keywords, 40 countries and 160 cities, 30 days,
on a plain SQLite file. That is 1/60 of the 12 M-mention install the finding came from, so the number it prints is a
floor for that machine, not an estimate of it.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

import src.api.insights as ins
from src.analytics import queries as q
from src.database.maintenance import StatementTimeout
from src.database.models import Base, DerivedMeta, Keyword, Source

N_MENTIONS = 200_000
N_KEYWORDS = 400
N_COUNTRIES = 40
N_CITIES = 160


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    path = tmp_path_factory.mktemp("map") / "m.db"
    eng = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng, future=True)
    today = date.today()
    countries = [f"c{i:02d}" for i in range(N_COUNTRIES)]
    cities = [(f"City{i}", countries[i % N_COUNTRIES]) for i in range(N_CITIES)]
    with S() as s:
        s.add(Source(name="S", domain="x.test"))
        for k in range(1, N_KEYWORDS + 1):
            s.add(Keyword(id=k, term=f"t{k}", normalized_term=f"t{k}", language="en"))
        s.commit()
    days = [(today - timedelta(days=d)).isoformat() for d in range(30)]  # text: the driver's own date adapter is deprecated
    rows = []
    for i in range(N_MENTIONS):
        city, country = cities[i % N_CITIES]
        rows.append({"keyword_id": 1 + (i * 7) % N_KEYWORDS, "article_id": 1 + i // 4, "count": 1 + i % 3,
                     "observed_on": days[i % 30], "country": country, "city": city})
    with eng.begin() as con:
        con.execute(text("PRAGMA foreign_keys=OFF"))
        con.execute(text("INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on, country, city) "
                         "VALUES (:keyword_id, :article_id, :count, :observed_on, :country, :city)"), rows)
    return eng


@pytest.fixture
def sess(engine, monkeypatch):
    ins._read_cache._cache.clear()
    ins._degraded_cache._cache.clear()
    monkeypatch.setattr(ins, "_degraded_window_s", lambda: 30.0)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s
    ins._read_cache._cache.clear()
    ins._degraded_cache._cache.clear()


def _count_selects(engine):
    seen = []

    def _before(_c, _cur, statement, *_a):
        if statement.lstrip().upper().startswith("SELECT") and "keyword_mentions" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    return seen, lambda: event.remove(engine, "before_cursor_execute", _before)


def test_a_map_of_the_generated_corpus_is_timed_and_complete(sess):
    t0 = time.monotonic()
    out = q.map_data(sess, days=30)
    took = time.monotonic() - t0
    print(f"\nmap_data over {N_MENTIONS:,} mentions / {N_COUNTRIES} countries / {N_CITIES} cities: {took:.2f} s")
    assert len(out["countries"]) == N_COUNTRIES and len(out["cities"]) == N_CITIES and "partial" not in out
    assert took < 60, "an order of magnitude past anything this size should cost"


def test_the_second_open_is_answered_from_the_cache_without_touching_the_mentions(sess, engine):
    ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    seen, off = _count_selects(engine)
    try:
        again = ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    finally:
        off()
    assert again["cached"] is True and seen == [], "a cache hit must not scan the mentions again"
    assert "computed_at" in again and "cache_ttl_s" in again, "the cache says how old it is"


def test_a_bumped_corpus_epoch_is_a_different_map(sess, engine):
    ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    sess.merge(DerivedMeta(key="corpus_epoch", value="9"))
    sess.commit()
    seen, off = _count_selects(engine)
    try:
        out = ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    finally:
        off()
    assert out["cached"] is False and seen, "a re-index, prune or restore must not serve the old map"
    sess.merge(DerivedMeta(key="corpus_epoch", value="0"))
    sess.commit()


def test_a_changed_keyword_filter_is_a_different_entry(sess, monkeypatch, tmp_path):
    """The map hides excluded keywords; a cached map must not keep showing one the user just excluded."""
    from src.analytics import filters

    monkeypatch.setattr(filters, "_path", lambda: tmp_path / "keyword_filter.json")
    first = ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    assert ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)["cached"] is True
    shown = first["countries"][0]["top"][0]["term"] if first["countries"][0]["top"] else None
    assert shown, "the generated corpus has keywords under every country"
    filters.add_excluded(shown)
    after = ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    assert after["cached"] is False, "the filter settings are part of the key"
    assert shown not in [k["term"] for k in after["countries"][0]["top"]]


def test_different_parameters_are_different_entries(sess):
    a = ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    b = ins.insights_map(days=30, kind=None, top_per_area=2, db=sess)
    assert b["cached"] is False and len(b["countries"][0]["top"]) == 2 and len(a["countries"][0]["top"]) == 5


def test_a_deadline_failure_is_replayed_not_rescanned(sess, monkeypatch):
    calls = []

    def boom(*_a, **_k):
        calls.append(1)
        raise StatementTimeout("the read ran past its deadline")

    monkeypatch.setattr(q, "map_data", boom)
    from fastapi import HTTPException

    for _ in range(3):
        with pytest.raises(HTTPException) as exc:
            ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
        assert exc.value.status_code == 503
    assert len(calls) == 1


def test_a_country_list_that_spent_the_budget_leaves_the_cities_out_and_says_so(sess):
    out = q.map_data(sess, days=30, budget_s=1e-9)
    assert out["partial"] is True and out["skipped"] == ["cities"] and out["cities"] == []
    assert len(out["countries"]) == N_COUNTRIES, "the part that was computed is whole"
    assert "not the same as no city" in out["caveat"]
    assert "partial" not in q.map_data(sess, days=30, budget_s=None)
    assert "partial" not in q.map_data(sess, days=30, budget_s=3600.0)


def test_a_partial_map_is_replayed_marked_and_never_cached_as_a_whole_one(sess, monkeypatch):
    monkeypatch.setattr(ins, "_map_live_budget_s", lambda: 1e-9)
    first = ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    assert first["partial"] is True and first["cities_placed"] == 0
    monkeypatch.setattr(ins, "_map_live_budget_s", lambda: None)
    second = ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    assert second["partial"] is True and second["replayed"], "inside the window the partial is what is answered"
    ins._degraded_cache._cache.clear()
    third = ins.insights_map(days=30, kind=None, top_per_area=5, db=sess)
    assert "partial" not in third and len(third["cities"]) == N_CITIES, "after the window a whole map is computed"


def test_the_map_client_does_not_read_a_skipped_city_list_as_no_data():
    from tests.js_source_helper import app_js

    src = app_js()
    assert 'd.partial && (d.skipped || []).includes("cities")' in src
