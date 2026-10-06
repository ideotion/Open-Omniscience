"""
Diagnostics round of 2026-09-30, rank 9: the article-list BROWSE is timed, and ``searches = 0``
becomes knowable.

``GET /api/articles`` was K2's worst interactive route on 8 of the 16 instances, and the one
thing never timed was the call a person waits on: ``_new_search_timer`` returned ``None`` for a
browse. The search-timing report also read ``searches: 0`` on sixteen of sixteen instances, and the
figure could not be believed: each export's own self-test emptied the window before the report read
it (LESSONS.md). Past that fix ``searches: 0`` still means "none since THIS process started", which
the export cannot tell from "never", so the durable logs are summarised beside it.

So each positive assertion has its negative space: a browse never enters the text aggregate (or
``searches: 0`` would stop meaning "nobody searched"), a caller that did not ask for browse timing
leaves no record, the benchmark's own runs never turn up in the field record, the diagnostics
export's own self-test never empties what the process has recorded, and every unmeasured field is
``None`` with a reason, never ``0``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source
from src.monitoring import search_timing, unlock_marker
from src.monitoring.search_timing import _FakeClock, _walk_no_score

main = pytest.importorskip("src.api.main")  # CI/venv with crypto; skips on a bare sandbox


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from src.api import insights

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    search_timing._reset_for_tests()
    unlock_marker._reset_for_tests()
    insights._read_cache.clear()  # the corpus-total cache is keyed by id(engine): never shared
    yield
    search_timing._reset_for_tests()
    unlock_marker._reset_for_tests()
    insights._read_cache.clear()


def _session():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="S", domain="x.test"))
    s.flush()
    for i, (t, c, lang) in enumerate(
        [
            ("Inflation report", "coverage of inflation and markets and trade policy", "en"),
            ("Markets update", "a longer body mentioning inflation once here today", "en"),
            ("Météo", "du soleil et de la pluie sur la région cette semaine", "fr"),
        ]
    ):
        s.add(
            Article(
                url=f"u{i}", canonical_url=f"u{i}", source_id=1, title=t, content=c,
                hash=f"h{i}", language=lang, created_at=datetime.now(UTC),
            )
        )
    s.commit()
    return s


def _q(s, query=None, *, language=None, limit=50, offset=0, **kw):
    """``time_browse`` is passed ONLY when a test passes it, so a flip of the function's own default
    is visible to every test that does not."""
    return main._query_articles(
        s, query=query, source=None, start_date=None, end_date=None, language=language,
        tags=None, limit=limit, offset=offset, **kw,
    )


def _timer(kind="text", *, ticks=(0.0, 0.010, 0.090, 0.092), wall=1010.0, meta=None):
    return search_timing.SearchPhaseTimer(
        monotonic=_FakeClock(list(ticks)), wall=lambda: wall, kind=kind, meta=meta
    )


def _record(kind="text", **meta):
    t = _timer(kind, meta=meta or None)
    t.phase("rows" if kind == "browse" else "fts")
    return t.finish()


@pytest.fixture()
def client():
    """The real app over the three-article database, so what the handler does BEFORE and AFTER the
    browse timer is observed by running it, not by reading its source."""
    from fastapi.testclient import TestClient

    from src.database.session import get_db

    seeded = _session()
    engine = seeded.get_bind()
    seeded.close()
    factory = sessionmaker(bind=engine, future=True)

    def _override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    main.app.state.limiter.reset()  # the limiter is process-wide: other modules' calls are not this one's
    main.app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(main.app) as c:
            c._engine = engine
            yield c
    finally:
        main.app.dependency_overrides.pop(get_db, None)


# --------------------------------------------------------------------------- #
# The record                                                                   #
# --------------------------------------------------------------------------- #


def test_a_record_says_what_it_timed_when_it_ended_and_how_far_from_the_unlock():
    t = _timer("browse", meta={"limit": 100, "offset": 0})
    t.phase("count_cached")
    t.phase("rows")
    rec = t.finish()
    assert rec["kind"] == "browse" and (rec["limit"], rec["offset"]) == (100, 0)
    assert [p["phase"] for p in rec["phases"]] == ["count_cached", "rows"]
    assert rec["total_ms"] == 92.0
    assert rec["at"] == datetime.fromtimestamp(1010.0, tz=UTC).isoformat(timespec="seconds")
    assert rec["started_after_unlock_s"] is None, "no unlock in this process: absent, never 0"

    unlock_marker.note_unlock_done(at=1000.0)
    t = _timer("browse")
    t.phase("count_cached")
    t.phase("rows")
    assert t.finish()["started_after_unlock_s"] == 9.9, "1010 - 0.092 s - 1000, rounded"

    unlock_marker.note_unlock_done(at=1015.0)  # the unlock finished AFTER this call began
    t = _timer("browse")
    t.phase("count_cached")
    t.phase("rows")
    assert t.finish()["started_after_unlock_s"] < 0, "signed: began before the unlock finished"


def test_a_text_search_record_keeps_its_phases_and_gains_only_the_new_fields():
    t = _timer("text")
    t.phase("fts")
    rec = t.finish()
    assert rec["kind"] == "text" and "limit" not in rec and "offset" not in rec
    assert [p["phase"] for p in rec["phases"]] == ["fts"]
    assert rec["phases"][0]["ms"] == 10.0, "the first tick pair, as before the kind existed"
    assert rec["total_ms"] == 90.0, "finish() reads the clock once more: the third tick"


def test_a_caller_scalar_can_never_override_what_the_timer_itself_says():
    t = _timer("browse", meta={"kind": "text", "total_ms": 1.0, "at": "never", "limit": 7})
    t.phase("rows")
    rec = t.finish()
    assert rec["kind"] == "browse" and rec["total_ms"] == 90.0 and rec["at"] != "never"
    assert rec["limit"] == 7, "the scalars it does not own pass through"


def test_the_browse_method_says_where_the_connection_wait_lands_and_what_is_not_in_it():
    rec = _record("browse")
    method = rec["method"]
    assert "A database connection is taken by the first statement" in method
    assert "A browse that looks nothing up first" in method
    assert "INSIDE the first phase that runs a statement" in method
    assert "the rows phase when the count was served from the cache" in method
    assert "BEFORE the clock starts" in method and "a query of field filters only" in method
    assert "the lookup itself are in no phase and not in the total either" in method
    assert "begins after the request has waited for a worker" in method
    assert "begins after" not in method.replace("It begins after the request has waited for a worker", "")


def test_the_browse_caveat_does_not_promise_the_connection_wait_is_always_in_a_phase():
    rep = search_timing.build_report([_record("browse", limit=50)])
    caveat = rep["browse"]["caveat"]
    assert "inside whichever phase first runs a statement, except on a browse that looks a filter up" in caveat
    assert "the report does not mark which browses did" in caveat, "it must not point at a per-record mark"
    method = rep["browse"]["method"]
    assert "looks that up BEFORE its clock starts" in method and "does not mark which of its browses did" in method
    assert "the wait for a database connection and the lookup itself are in no phase" in method, (
        "the aggregate's own method says what is outside the figure: the export carries no records to point at"
    )


def test_the_text_search_method_names_the_phases_a_text_record_really_has_and_what_is_not_in_it():
    """It used to say `FTS MATCH · content fetch · serialization` and `the full request wall`: no text
    record ever had those phases, and its clock starts after the handler's keyword lookup and the
    filters' lookups, so the wall is not the request's."""
    s = _session()
    _q(s, "inflation")
    rec = search_timing._snapshot()[0]
    assert rec["kind"] == "text"
    names = [p["phase"] for p in rec["phases"]]
    assert names == ["fts", "resolve", "load"], names
    method = rec["method"]
    for name in names:
        assert f"{name}:" in method, f"the method must name the phase {name!r} the record carries"
    assert "full request wall" not in method and "serialization" not in method
    assert "after the keyword the handler looks up for the per-article counts" in method
    assert "it ends before the response is built" in method


def test_the_durable_log_method_says_a_failed_cut_leaves_more_than_the_cap_behind():
    """The export is all the reader has, and a cut that fails (a full disk, a file another program holds
    open on Windows) is tried again 250 appends later, so the file can hold more than 250 over the cap."""
    method = search_timing.durable_log_summary()["method"]
    assert f"once every {search_timing._TRIM_EVERY} appends" in method
    assert "more for each cut that failed" in method and "tried again at the next one" in method


def _spied_client_browse(client, monkeypatch, params):
    """One request through the handler. Returns ``(at_start, at_phase, body)``: the checkouts the engine
    had handed out when the browse timer was created (one entry per timer made), the checkouts at each
    phase mark, and the response body -- counted from the request's own start, against the engine's
    own checkout event rather than against any text."""
    from sqlalchemy import event

    taken: list[int] = []
    event.listen(client._engine, "checkout", lambda *a: taken.append(1))
    base = len(taken)
    at_start: list[int] = []
    at_phase: dict[str, int] = {}
    real = main._new_search_timer

    def spy(*a, **kw):
        timer = real(*a, **kw)
        at_start.append(len(taken) - base)
        if timer is not None:
            mark = timer.phase

            def phase(name):
                at_phase[name] = len(taken) - base
                return mark(name)

            timer.phase = phase
        return timer

    monkeypatch.setattr(main, "_new_search_timer", spy)
    r = client.get("/api/articles", params=params)
    monkeypatch.setattr(main, "_new_search_timer", real)
    assert r.status_code == 200, r.text
    return at_start, at_phase, r.json()


def test_a_query_of_field_filters_only_looks_a_keyword_up_before_the_browse_timer_starts(client, monkeypatch):
    """Through the handler, a non-empty query -- a field-only one such as `source:S` included -- is
    resolved to a keyword (a statement) before `_query_articles` rewrites it into a browse and starts
    the timer, which is why the method text lists it with the filters that look something up first; a
    browse with no query looks nothing up first."""
    at_start, _, body = _spied_client_browse(client, monkeypatch, {"query": "source:S", "limit": 5})
    assert body["total"] == 3 and at_start[0] >= 1, "the keyword lookup took the connection first"
    at_start, _, body = _spied_client_browse(client, monkeypatch, {"limit": 5})
    assert body["total"] == 3 and at_start == [0], "no query: nothing is looked up before the clock starts"


def test_a_text_search_starts_its_clock_after_the_handlers_keyword_lookup(client, monkeypatch):
    """The text method says its clock begins after the keyword the handler looks up for the
    per-article counts; through the handler, the engine has handed out a connection by then."""
    at_start, at_phase, body = _spied_client_browse(client, monkeypatch, {"query": "inflation", "limit": 5})
    assert body["total"] == 2 and at_start[0] >= 1, "the lookup took the connection before the clock started"
    assert set(at_phase) == {"fts", "resolve", "load"}


def test_with_the_count_served_from_the_cache_the_connection_is_taken_in_the_rows_phase(client, monkeypatch):
    """The method text says the first statement takes the connection, and that for a count served from
    the cache that is the page's own: the data-version probe has a connection of its own. So the wait
    lands in `rows` then, and in the count phase when the count had to be made."""
    from src.api import insights

    # the engine's first probe pins a connection of its own (a checkout inside the count phase), so
    # this first request only shows that the wait lands in the count phase when the count is made
    _, first, _ = _spied_client_browse(client, monkeypatch, {"limit": 2})
    assert set(first) == {"count_recomputed", "rows"} and first["count_recomputed"] >= 1, first
    # the first request's session is closed with it, so the next one starts without a connection
    _, served, _ = _spied_client_browse(client, monkeypatch, {"limit": 2})
    assert set(served) == {"count_cached", "rows"}, served
    assert served["count_cached"] == 0 and served["rows"] == 1, served
    # the probe is pinned now: a count that has to be made again takes exactly the session's connection
    insights._read_cache.clear()
    _, made, _ = _spied_client_browse(client, monkeypatch, {"limit": 2})
    assert made == {"count_recomputed": 1, "rows": 1}, made


def test_the_connection_sentence_is_true_a_filter_that_looks_ids_up_takes_it_before_the_clock_starts(monkeypatch):
    """The method text says WHEN the connection is taken: by the first statement, which for a browse that
    looks nothing up is inside the timed span, and for a filter that resolves source ids first (a source,
    a source type, tags, a provenance, the advanced search's countries or regions) is before the clock
    starts -- so the wait for it is in no phase and not in the total. Pinned against the engine's own
    checkout event, not against the text."""
    from sqlalchemy import event

    from src.api.search_filters import AdvancedSearch

    def checkouts_when_the_clock_starts(**filters) -> tuple[int, int]:
        s = _session()
        taken: list[int] = []
        event.listen(s.get_bind(), "checkout", lambda *a: taken.append(1))
        seen: list[int] = []
        real = main._new_search_timer

        def spy(*a, **kw):
            seen.append(len(taken))
            return real(*a, **kw)

        monkeypatch.setattr(main, "_new_search_timer", spy)
        args = {"query": None, "source": None, "start_date": None, "end_date": None, "language": None,
                "tags": None, "limit": 2, "offset": 0, "time_browse": True, **filters}
        main._query_articles(s, **args)
        monkeypatch.setattr(main, "_new_search_timer", real)
        return seen[0], len(taken)

    started, total = checkouts_when_the_clock_starts()
    assert started == 0 and total >= 1, "unfiltered: the first statement runs inside the timed span"
    for plain in (
        {"language": "en"},
        {"start_date": "2020-01-01", "end_date": "2099-01-01"},
        {"adv": AdvancedSearch(source_ids=[1])},
        {"adv": AdvancedSearch(langs=["en"], words_min=1)},
    ):
        started, total = checkouts_when_the_clock_starts(**plain)
        assert started == 0, f"{plain}: a plain column condition looks nothing up"
    for name, value in (
        ("source_type", "news"), ("tags", "x"), ("source", "S"), ("provenance", "web"),
        ("adv", AdvancedSearch(countries=["fr"])), ("adv", AdvancedSearch(regions=["Europe"])),
    ):
        started, total = checkouts_when_the_clock_starts(**{name: value})
        assert started >= 1, f"{name}={value!r}: its lookup took the connection before the clock started"


# --------------------------------------------------------------------------- #
# The report: the browse is a sibling of the text aggregate, never inside it   #
# --------------------------------------------------------------------------- #


def test_a_browse_never_enters_the_text_aggregate_and_an_old_record_is_a_text_search():
    old_style = {"phases": [{"phase": "fts", "ms": 5.0}], "total_ms": 5.0}  # no `kind`
    browse = {"kind": "browse", "phases": [{"phase": "rows", "ms": 90.0}], "total_ms": 90.0}
    rep = search_timing.build_report([old_style, browse, dict(browse)])
    assert rep["searches"] == 1, "a browse is not a search"
    assert rep["browse"]["pages"] == 2 and "searches" not in rep["browse"]
    assert rep["browse"]["phases"]["rows"]["n"] == 2
    assert "phases" in rep and "rows" not in rep["phases"]
    assert "scope" in rep and "THIS process" in rep["scope"]


def test_an_empty_browse_aggregate_is_honest_not_zero_filled():
    rep = search_timing.build_report([])
    assert rep["browse"]["pages"] == 0
    assert rep["browse"]["dominant_phase"] is None and rep["browse"]["phases"] == {}
    assert rep["browse"]["page_sizes"] == {}


def test_the_report_carries_no_score_like_key():
    t = _timer("browse")
    t.phase("count_live")
    t.phase("rows")
    _walk_no_score(search_timing.build_report([t.finish()], search_timing.durable_log_summary()))


def test_the_browse_aggregate_says_which_page_sizes_it_mixes():
    """GET /api/articles is called with a page of 8 (Home's tag cards), 50 (the Search tab's default
    result limit, which is a setting, and the analysis list's `_AN_ART_PAGE`), 60 (the synthesis'
    candidate pool) and 1000 (Home's channel list): one p95 across them would read as the Search tab's
    alone, so the aggregate counts the browses by the page size they asked for."""
    recs = [_record("browse", limit=50)] * 5 + [_record("browse", limit=8)] * 2 + [_record("browse")]
    rep = search_timing.build_report(recs)
    assert rep["browse"]["page_sizes"] == {"50": 5, "8": 2, "no limit": 1}
    method = rep["browse"]["method"]
    assert "every call to GET /api/articles that has no text query and no explicit `ids` set" in method
    assert "a call for a fixed set of ids is not timed" in method
    # A browse is recorded after its rows are in hand (src/api/main.py, with no try/finally), so a
    # call that raised is in neither the window nor the durable log: the report says so, and says
    # where those calls are counted instead (the coordinator's check of #1292, S1).
    assert "once it has returned a page: a call that failed is not in it" in method
    assert "route latency log counts those" in method
    assert "page_sizes" in method


def test_a_call_for_a_fixed_set_of_ids_is_not_timed_and_a_plain_call_is(client):
    """The report says an `ids` call is not timed (the handler answers it before `_query_articles`,
    where the browse timer lives) and that every other call with no text query is. Run, not read."""
    r = client.get("/api/articles", params={"ids": "1,2"})
    assert r.status_code == 200 and r.json()["total"] == 2
    assert search_timing.search_timing_report()["browse"]["pages"] == 0, "an `ids` call is not a timed browse"
    r = client.get("/api/articles", params={"limit": 2})
    assert r.status_code == 200 and r.json()["total"] == 3
    rep = search_timing.search_timing_report()
    assert rep["browse"]["pages"] == 1 and rep["browse"]["page_sizes"] == {"2": 1}
    assert rep["searches"] == 0, "the browse did not become a search"


def test_page_sizes_keeps_the_most_frequent_and_sums_the_rest_under_other():
    recs = [_record("browse", limit=n) for n in range(1, 16) for _ in range(n)]
    sizes = search_timing._page_sizes(recs)
    assert len(sizes) == search_timing._PAGE_SIZES_MAX + 1 and "other" in sizes
    assert sizes["15"] == 15 and sizes["6"] == 6, "most frequent first"
    assert sum(sizes.values()) == len(recs), "nothing is lost into `other`"


# --------------------------------------------------------------------------- #
# The in-process windows: one per kind                                         #
# --------------------------------------------------------------------------- #


def test_a_flood_of_browses_never_pushes_the_text_searches_out_of_the_window():
    """Browses are far more frequent than searches. In one shared window 512 of them would evict
    every text search and `searches` would read 0 on an instance that had searched."""
    search_timing.record_search_phases(_record("text"))
    for _ in range(search_timing._RES_CAP + 50):
        search_timing.record_search_phases(_record("browse", limit=8))
    rep = search_timing.search_timing_report()
    assert rep["searches"] == 1
    assert rep["browse"]["pages"] == search_timing._RES_CAP, "its own window is bounded"
    assert search_timing._RES_CAP == 512


def test_the_text_window_is_bounded_too():
    for _ in range(search_timing._RES_CAP + 7):
        search_timing.record_search_phases(_record("text"))
    assert search_timing.search_timing_report()["searches"] == search_timing._RES_CAP


# --------------------------------------------------------------------------- #
# The self-test that runs inside every export must leave the windows alone     #
# --------------------------------------------------------------------------- #


def test_the_self_test_leaves_what_this_process_recorded_exactly_as_it_was():
    """The diagnostics export runs this self-test (inside `recursive-loop.json`) BEFORE it reads
    `search-timing.json`. It used to empty the window it was about to be read from, so `searches`
    read 0 on 16 of 16 instances whatever had been searched."""
    search_timing.record_search_phases(_record("text"))
    search_timing.record_search_phases(_record("browse"))
    search_timing.record_search_phases(_record("browse"))
    before = search_timing._snapshot()

    log = search_timing.run_search_timing_selftest()

    assert log["passed"] is True, log["checks"]
    assert search_timing._snapshot() == before, "the live windows are untouched"
    rep = search_timing.search_timing_report()
    assert (rep["searches"], rep["browse"]["pages"]) == (1, 2)


def test_the_recursive_loop_gate_for_search_timing_leaves_the_windows_alone_too():
    """The same, through the registry the export actually runs."""
    from src.monitoring.recursive_loop import recursive_loop_report

    search_timing.record_search_phases(_record("text"))
    search_timing.record_search_phases(_record("browse"))
    gate = (("search-timing-selftest", "src.monitoring.search_timing", "run_search_timing_selftest"),)
    report = recursive_loop_report(gate)
    assert report["summary"]["all_green"] is True
    rep = search_timing.search_timing_report()
    assert (rep["searches"], rep["browse"]["pages"]) == (1, 1)


def test_the_self_test_still_proves_the_window_bound_on_a_local_list():
    log = search_timing.run_search_timing_selftest()
    row = next(c for c in log["checks"] if c["check"] == "record_window_bounded")
    assert row["passed"] is True
    window: list[dict] = []
    for i in range(search_timing._RES_CAP + 5):
        search_timing._append_bounded(window, {"i": i})
    assert len(window) == search_timing._RES_CAP and window[0] == {"i": 5}, "the OLDEST are dropped"


# --------------------------------------------------------------------------- #
# The wiring in _query_articles                                                #
# --------------------------------------------------------------------------- #


def test_the_default_is_not_to_time_a_browse():
    """The AI, evidence and analysis callers browse too; only the article-list handler asks."""
    assert inspect.signature(main._query_articles).parameters["time_browse"].default is False


def test_a_browse_the_list_asked_to_time_records_count_then_rows():
    s = _session()
    articles, total = _q(s, None, time_browse=True, limit=2)
    assert total == 3 and len(articles) == 2
    rep = search_timing.search_timing_report()
    assert rep["browse"]["pages"] == 1
    assert set(rep["browse"]["phases"]) == {"count_recomputed", "rows"}, "the first count is made"
    assert rep["searches"] == 0, "the browse did not become a search"
    rec = search_timing._snapshot()[0]
    assert (rec["kind"], rec["limit"], rec["offset"]) == ("browse", 2, 0)


def test_a_browse_names_its_count_by_how_it_was_got(monkeypatch):
    """`count_cached` is the cheap case and `count_recomputed` the whole-corpus COUNT(*): a miss
    must never be filed under the cheap name, or the p95 of 'cached' counts would carry the
    recomputations."""
    from src.api import insights

    version = ["1"]
    monkeypatch.setattr(insights, "_data_version", lambda bind: version[0])
    s = _session()

    def count_phase() -> str:
        before = len(search_timing._snapshot())
        _q(s, None, time_browse=True, limit=2)
        rec = search_timing._snapshot()[before]
        return rec["phases"][0]["phase"]

    assert count_phase() == "count_recomputed", "empty cache"
    assert count_phase() == "count_cached", "same data version: served"
    version[0] = "2"  # any commit by another connection
    assert count_phase() == "count_recomputed", "the data changed: counted again"
    assert count_phase() == "count_cached"


def test_an_entry_the_cache_lost_with_no_write_since_is_counted_again_and_says_so(monkeypatch):
    """`count_recomputed` says HOW the count was got, not why: an entry that outlived its TTL, or was
    evicted, is a whole-corpus COUNT(*) although the data version never moved -- the cases a wording
    that blamed "the data had changed or the cache was off" left out."""
    import time as real_time
    import types

    from src.api import insights
    from src.utils import cache as cache_module

    monkeypatch.setattr(insights, "_data_version", lambda bind: "1")
    s = _session()

    def count_phase() -> str:
        before = len(search_timing._snapshot())
        _q(s, None, time_browse=True, limit=2)
        return search_timing._snapshot()[before]["phases"][0]["phase"]

    assert count_phase() == "count_recomputed", "the first browse since the process started"
    assert count_phase() == "count_cached"
    insights._read_cache.clear()  # an eviction (the cache holds 128 entries) or a restart of the cache
    assert count_phase() == "count_recomputed", "evicted, data version unchanged"
    assert count_phase() == "count_cached"
    ahead = insights._CACHE_TTL_S + 1
    monkeypatch.setattr(cache_module, "time", types.SimpleNamespace(time=lambda: real_time.time() + ahead))
    assert count_phase() == "count_recomputed", "the entry outlived its TTL, data version unchanged"


def test_a_browse_with_no_data_version_probe_is_counted_again_and_says_so(monkeypatch):
    from src.api import insights

    monkeypatch.setattr(insights, "_data_version", lambda bind: None)
    s = _session()
    _, total = _q(s, None, time_browse=True, limit=2)
    assert total == 3, "the live count is exact"
    assert search_timing._snapshot()[0]["phases"][0]["phase"] == "count_recomputed"


def test_a_browse_with_the_cache_off_is_counted_again_every_time_and_says_so(monkeypatch):
    """A TTL of 0 switches the cache off: ``_cached`` then returns the bare payload, with no
    ``cached`` key, and that payload is a count made just now. It must read ``count_recomputed``,
    never the cheap name, on every browse (and the total stays exact)."""
    from src.api import insights

    monkeypatch.setattr(insights, "_data_version", lambda bind: "1")
    monkeypatch.setattr(insights, "_CACHE_TTL_S", 0)
    s = _session()
    for _ in range(2):
        before = len(search_timing._snapshot())
        _, total = _q(s, None, time_browse=True, limit=2)
        assert total == 3, "the count is exact"
        assert search_timing._snapshot()[before]["phases"][0]["phase"] == "count_recomputed"


def test_a_filtered_browse_names_its_count_as_live():
    s = _session()
    _q(s, None, time_browse=True, language="en")
    assert set(search_timing.search_timing_report()["browse"]["phases"]) == {
        "count_live",
        "rows",
    }


def test_a_caller_that_did_not_ask_for_browse_timing_leaves_no_record_and_the_same_page():
    """The AI, evidence and analysis callers browse too; they must stay byte-identical."""
    s = _session()
    plain = _q(s, None)
    timed = _q(s, None, time_browse=True)
    assert [a.id for a in plain[0]] == [a.id for a in timed[0]] and plain[1] == timed[1]
    # exactly ONE record: the timed call's, none from the plain one
    assert search_timing.search_timing_report()["browse"]["pages"] == 1


def test_a_text_search_is_still_timed_without_asking():
    s = _session()
    _q(s, "inflation")
    rep = search_timing.search_timing_report()
    assert rep["searches"] == 1 and rep["browse"]["pages"] == 0
    assert search_timing._snapshot()[0]["kind"] == "text"


def test_a_query_that_is_only_field_filters_is_a_browse_and_is_timed_as_one():
    """`source:S` is a SQL field with nothing to rank, so `_query_articles` rewrites it into a
    filtered BROWSE -- which must be timed as one (count_live, rows), not as a text search."""
    s = _session()
    articles, total = _q(s, "source:S", limit=10, time_browse=True)
    assert total == 3 and len(articles) == 3, "the field filter matched the seeded source"
    rep = search_timing.search_timing_report()
    assert rep["browse"]["pages"] == 1 and rep["searches"] == 0
    assert set(rep["browse"]["phases"]) == {"count_live", "rows"}


def test_the_article_list_handler_asks_for_browse_timing(client):
    assert search_timing.search_timing_report()["browse"]["pages"] == 0
    assert client.get("/api/articles").status_code == 200
    assert search_timing.search_timing_report()["browse"]["pages"] == 1, "one call, one timed browse"


# --------------------------------------------------------------------------- #
# The durable logs: one per kind                                               #
# --------------------------------------------------------------------------- #


def _log(tmp_path, kind="text"):
    return tmp_path / "data" / search_timing._LOG_FILES[kind]


def _lines(path):
    return [ln for ln in path.read_text("utf-8").splitlines() if ln.strip()]


def test_each_kind_has_its_own_log_so_browses_cannot_push_the_searches_out_of_its_cap(tmp_path):
    search_timing.append_search_timing(_record("text"))
    for _ in range(3):
        search_timing.append_search_timing(_record("browse", limit=8))
    assert len(_lines(_log(tmp_path, "text"))) == 1
    assert len(_lines(_log(tmp_path, "browse"))) == 3
    assert json.loads(_lines(_log(tmp_path, "text"))[0])["kind"] == "text"
    assert _log(tmp_path, "text").name == "search_timing.jsonl", "the text log keeps the name it had"


def test_the_durable_log_counts_kinds_and_dates_and_owns_up_to_what_it_cannot_date(tmp_path):
    text_path, browse_path = _log(tmp_path, "text"), _log(tmp_path, "browse")
    text_path.parent.mkdir(parents=True)
    old = {"phases": [{"phase": "fts", "ms": 5.0}], "total_ms": 5.0}  # before 2026-10-01
    t = _timer("text")
    t.phase("fts")
    new_text = t.finish()
    t = _timer("browse", wall=2000.0)
    t.phase("rows")
    new_browse = t.finish()
    text_path.write_text(
        "\n".join(json.dumps(x) for x in (old, old, new_text)) + "\n{cut off", "utf-8"
    )
    browse_path.write_text(json.dumps(new_browse) + "\n", "utf-8")
    log = search_timing.durable_log_summary()
    text, browse = log["text"], log["browse"]
    assert (text["records"], browse["records"]) == (3, 1)
    assert text["undated"] == 2, "the two old lines cannot be placed in time"
    assert text["malformed"] == 1, "a line cut short is counted, not dropped"
    assert text["dated_from"] == text["dated_to"] == datetime.fromtimestamp(
        1010.0, tz=UTC
    ).isoformat(timespec="seconds")
    assert browse["dated_from"] == datetime.fromtimestamp(2000.0, tz=UTC).isoformat(timespec="seconds")
    assert (text["file"], browse["file"]) == ("search_timing.jsonl", "search_timing_browse.jsonl")
    assert log["cap_lines"] == search_timing._CAP_LINES
    assert text["reason"] is None and browse["reason"] is None


def test_a_line_whose_time_has_no_zone_is_undated_and_never_breaks_the_report(tmp_path):
    """Comparing a zone-less time with a zoned one raises TypeError; one such line must cost the
    line its date, not the whole export its report."""
    path = _log(tmp_path)
    path.parent.mkdir(parents=True)
    aware = {"kind": "text", "at": "2026-10-01T10:00:00+00:00", "phases": [], "total_ms": 1.0}
    naive = {"kind": "text", "at": "2026-10-01T09:00:00", "phases": [], "total_ms": 1.0}
    path.write_text("\n".join(json.dumps(x) for x in (aware, naive)) + "\n", "utf-8")
    text = search_timing.durable_log_summary()["text"]
    assert (text["records"], text["undated"]) == (2, 1)
    assert text["dated_from"] == text["dated_to"] == "2026-10-01T10:00:00+00:00"


def test_no_log_is_zero_records_with_a_reason_and_an_unreadable_log_is_none(tmp_path):
    none_yet = search_timing.durable_log_summary()
    for kind in ("text", "browse"):
        assert none_yet[kind]["records"] == 0 and "nothing of this kind has been logged" in none_yet[kind]["reason"]

    _log(tmp_path).mkdir(parents=True)  # a DIRECTORY where the text file should be: unreadable
    unreadable = search_timing.durable_log_summary()
    assert unreadable["text"]["records"] is None
    assert "unmeasured, not empty" in unreadable["text"]["reason"]
    assert unreadable["browse"]["records"] == 0, "the other log is its own fact"


def test_the_in_process_count_restarts_and_the_durable_one_does_not(tmp_path):
    """What the durable summary adds: after a restart `searches` reads 0 on an instance whose log
    still holds the searches people ran. (The sixteen zeros of the 2026-09-30 round had another
    cause, the export's own self-test emptying the window: the self-test tests below pin that.)"""
    search_timing.append_search_timing(_record("text"))
    search_timing.append_search_timing(_record("text"))
    search_timing._reset_for_tests()  # what a restart does to the in-process window
    rep = search_timing.search_timing_report()
    assert rep["searches"] == 0
    assert rep["durable_log"]["text"]["records"] == 2


def test_a_log_is_cut_to_its_cap_on_a_process_first_append_and_then_every_so_many(tmp_path, monkeypatch):
    """Cutting rewrites the whole file, and a browse can arrive many times a minute: cut once per
    `_TRIM_EVERY` appends (and on the first of a process, so a log never carries the growth of the
    process before it), not after every one."""
    monkeypatch.setattr(search_timing, "_CAP_LINES", 10)
    monkeypatch.setattr(search_timing, "_TRIM_EVERY", 5)
    search_timing._reset_for_tests()
    path = _log(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps({"i": i}) for i in range(40)) + "\n", "utf-8")

    sizes = []
    for _ in range(6):
        search_timing.append_search_timing(_record("text"))
        sizes.append(len(_lines(path)))
    assert sizes == [10, 11, 12, 13, 14, 10], sizes
    assert json.loads(_lines(path)[-1])["kind"] == "text", "the newest record is the one kept"


def _seeded_log(tmp_path, monkeypatch, *, cap=5, lines=8):
    monkeypatch.setattr(search_timing, "_CAP_LINES", cap)
    path = _log(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps({"seq": i}) + "\n" for i in range(lines)), "utf-8")
    search_timing._appends_since_trim["text"] = 0  # no cut of its own: the one a test calls is the one under test
    return path


def test_a_cut_keeps_the_newest_lines_and_leaves_no_part_file(tmp_path, monkeypatch):
    path = _seeded_log(tmp_path, monkeypatch)
    search_timing._trim_jsonl("text")
    assert [json.loads(ln)["seq"] for ln in _lines(path)] == [3, 4, 5, 6, 7]
    assert not path.with_name(path.name + ".part").exists()


def test_a_cut_that_fails_leaves_the_old_log_whole_and_no_part_file_behind(tmp_path, monkeypatch):
    """The cut is written beside the log and swapped in: a full disk or a crash in the middle of it
    must never leave a truncated log."""
    path = _seeded_log(tmp_path, monkeypatch)
    whole = path.read_text("utf-8")

    def disk_full(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(search_timing.os, "replace", disk_full)
    search_timing._trim_jsonl("text")
    assert path.read_text("utf-8") == whole, "the old log is untouched"
    assert not path.with_name(path.name + ".part").exists(), "the half-made copy is removed"


def test_a_cut_whose_copy_cannot_be_written_leaves_the_old_log_whole(tmp_path, monkeypatch):
    """The other place a full disk bites: the copy itself. It may be left half-written; it is removed
    (while the log's lock is still held, so it can never be another cut's copy that goes), and the log
    it was to replace is never touched."""
    import pathlib

    path = _seeded_log(tmp_path, monkeypatch)
    whole = path.read_text("utf-8")
    real_write, real_unlink = pathlib.Path.write_text, pathlib.Path.unlink
    removed: list[tuple[bool, bool]] = []  # (the log's lock was held, the half-written copy existed)

    def disk_full_midway(self, data, *a, **kw):
        if self.name.endswith(".part"):
            real_write(self, data[: len(data) // 2], "utf-8")
            raise OSError(28, "No space left on device")
        return real_write(self, data, *a, **kw)

    def unlink_noting_the_lock(self, *a, **kw):
        if self.name.endswith(".part"):
            removed.append((search_timing._FILE_LOCKS["text"].locked(), self.exists()))
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "write_text", disk_full_midway)
    monkeypatch.setattr(pathlib.Path, "unlink", unlink_noting_the_lock)
    search_timing._trim_jsonl("text")
    monkeypatch.setattr(pathlib.Path, "write_text", real_write)
    monkeypatch.setattr(pathlib.Path, "unlink", real_unlink)
    assert path.read_text("utf-8") == whole, "the old log is untouched"
    assert not path.with_name(path.name + ".part").exists(), "the half-written copy is removed"
    assert removed == [(True, True)], "the half-written copy is removed, under the lock a cut and an append take"
    search_timing._trim_jsonl("text")
    assert [json.loads(ln)["seq"] for ln in _lines(path)] == [3, 4, 5, 6, 7], "the next cut works"


def test_a_swap_a_program_holding_the_file_open_refused_is_tried_again_when_the_next_cut_is_due(
    tmp_path, monkeypatch
):
    """On Windows a file another program holds open (an antivirus scan, an editor) cannot be replaced.
    The refusal costs the log nothing but the lines appended before the next cut, which comes
    `_TRIM_EVERY` appends later, and the search whose append triggered it never sees an error."""
    monkeypatch.setattr(search_timing, "_CAP_LINES", 3)
    monkeypatch.setattr(search_timing, "_TRIM_EVERY", 2)
    search_timing._reset_for_tests()
    path = _log(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps({"seq": i}) + "\n" for i in range(6)), "utf-8")
    real_replace, refused = search_timing.os.replace, [True]

    def held_open(src, dst):
        if refused[0]:
            raise PermissionError(13, "The process cannot access the file because it is being used")
        return real_replace(src, dst)

    monkeypatch.setattr(search_timing.os, "replace", held_open)
    search_timing.append_search_timing(_record("text"))  # a process's first append: a cut is due, refused
    assert len(_lines(path)) == 7, "nothing lost, nothing cut"
    assert not path.with_name(path.name + ".part").exists()
    refused[0] = False
    search_timing.append_search_timing(_record("text"))  # one append since the cut was tried
    assert len(_lines(path)) == 8
    search_timing.append_search_timing(_record("text"))  # `_TRIM_EVERY` appends: due again, and it goes through
    assert len(_lines(path)) == 3, "the cut that was refused is made"


def test_a_cut_and_an_append_never_overlap_so_a_line_appended_meanwhile_survives(tmp_path, monkeypatch):
    """An append that lands between the cut's read and its write used to be overwritten with the lines
    the cut had already read. The append is held back until the cut is done and goes into the new log."""
    import pathlib
    import threading

    path = _seeded_log(tmp_path, monkeypatch)
    late = threading.Thread(
        target=lambda: search_timing.append_search_timing({**_record("text"), "seq": "late"})
    )
    real_read, fired = pathlib.Path.read_text, []

    def read_then_let_an_append_try(self, *a, **kw):
        text = real_read(self, *a, **kw)
        if self == path and not fired:
            fired.append(1)
            late.start()
            late.join(timeout=0.3)  # an append the cut did not exclude finishes here, and is overwritten below
        return text

    monkeypatch.setattr(pathlib.Path, "read_text", read_then_let_an_append_try)
    search_timing._trim_jsonl("text")
    monkeypatch.setattr(pathlib.Path, "read_text", real_read)
    late.join(timeout=10)
    assert not late.is_alive()
    assert [json.loads(ln)["seq"] for ln in _lines(path)] == [3, 4, 5, 6, 7, "late"]


def test_the_two_logs_are_cut_independently(tmp_path, monkeypatch):
    monkeypatch.setattr(search_timing, "_CAP_LINES", 3)
    monkeypatch.setattr(search_timing, "_TRIM_EVERY", 2)
    search_timing._reset_for_tests()
    for _ in range(5):
        search_timing.append_search_timing(_record("browse"))
    search_timing.append_search_timing(_record("text"))
    assert len(_lines(_log(tmp_path, "text"))) == 1, "five browses did not touch the text log"
    assert len(_lines(_log(tmp_path, "browse"))) <= 3 + 2 - 1


def _in_a_thread(fn):
    """Run ``fn`` on its own thread; returns ``(thread, result list)``."""
    import threading

    out: list = []
    t = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    t.start()
    return t, out


def test_a_cut_of_one_log_never_holds_up_an_append_to_the_other(tmp_path):
    """The browse log's cut is the longer of the two and runs on article-list calls: with one lock for
    both logs, every text search appending meanwhile would wait for it."""
    with search_timing._FILE_LOCKS["browse"]:  # a cut of the browse log, in progress
        t, _ = _in_a_thread(lambda: search_timing.append_search_timing(_record("text")))
        t.join(timeout=5)
        assert not t.is_alive(), "the text append waited for the browse log's lock"
    with search_timing._FILE_LOCKS["text"]:  # and the other way round
        t, _ = _in_a_thread(lambda: search_timing.append_search_timing(_record("browse", limit=2)))
        t.join(timeout=5)
        assert not t.is_alive(), "the browse append waited for the text log's lock"
    assert len(_lines(_log(tmp_path, "text"))) == 1 and len(_lines(_log(tmp_path, "browse"))) == 1


def test_the_report_reads_a_log_under_the_lock_a_cut_and_an_append_of_it_take(tmp_path, monkeypatch):
    """A read that has the file open while a cut swaps it makes the swap fail on Windows, and a read
    during an append can see half a line; it waits for the log's own lock, and only for that one."""
    path = _seeded_log(tmp_path, monkeypatch)
    with search_timing._FILE_LOCKS["text"]:  # a cut of the text log, in progress
        waiting, out = _in_a_thread(lambda: search_timing._read_log("text"))
        waiting.join(timeout=0.3)
        assert waiting.is_alive(), "the read took the file while the cut held it"
        other, other_out = _in_a_thread(lambda: search_timing._read_log("browse"))
        other.join(timeout=5)
        assert not other.is_alive(), "the browse log's read waited for the text log's lock"
    waiting.join(timeout=5)
    assert not waiting.is_alive() and out[0]["records"] == len(_lines(path)) == 8
    assert other_out[0]["records"] == 0


def test_the_benchmarks_own_runs_are_kept_out_of_the_field_record(tmp_path):
    t = _timer("browse")
    t.phase("rows")
    with search_timing.suppressed():
        search_timing.append_search_timing(t.finish())
        with search_timing.suppressed():  # nesting is harmless
            search_timing.append_search_timing(t.finish())
        search_timing.append_search_timing(t.finish())
    assert search_timing.search_timing_report()["browse"]["pages"] == 0
    assert not _log(tmp_path, "browse").exists(), "not logged either"
    search_timing.append_search_timing(t.finish())  # the block is scoped: records flow again
    assert search_timing.search_timing_report()["browse"]["pages"] == 1


def test_a_failure_inside_the_suppressed_block_does_not_leave_the_record_muted():
    """The benchmark's page query can fail for any reason (it reports the error per case and goes
    on). If the mute outlived that, every real search after it would vanish from the record with
    no sign of it."""
    t = _timer("browse")
    t.phase("rows")
    with pytest.raises(RuntimeError), search_timing.suppressed():
        raise RuntimeError("the page query failed")
    search_timing.append_search_timing(t.finish())
    assert search_timing.search_timing_report()["browse"]["pages"] == 1
