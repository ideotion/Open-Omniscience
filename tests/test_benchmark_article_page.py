"""
Diagnostics round of 2026-09-30, rank 9: the benchmark times the call a person waits on.

GET /api/articles was K2's worst interactive route on 8 of the 16 instances, and the benchmark
export had no number for it: ``fts_search`` is only the first step of a text search and nothing
timed a browse at all. The two cases added here (``search_first_page``, ``browse_first_page``)
call ``api.main._query_articles`` itself -- not a copy of its SQL, which would measure what the
query used to be after somebody rewrites it -- and keep their own runs out of the field record, so
a benchmark never turns up in ``search-timing.json`` as searches nobody made.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.config.app_settings import AppSettings
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source
from src.monitoring import benchmark, search_timing
from src.monitoring.benchmark import run_benchmark

main = pytest.importorskip("src.api.main")  # CI/venv with crypto; skips on a bare sandbox

_TEXTS = [
    "The Senate debated sanctions on Russia over the federal budget crisis.",
    "Russia responded to the sanctions while the budget debate continued.",
    "Sanctions and the budget dominated the Senate session on Russia.",
    "Climate policy entered the budget debate in the Senate today.",
]


def _corpus(*, articles: bool = True):
    engine = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    if articles:
        ex = BaselineExtractor()
        for i, t in enumerate(_TEXTS):
            a = Article(
                url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
                title="T", content=t, hash=f"h{i}", country="fr", language="en",
                published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
            )
            s.add(a)
            s.commit()
            index_article(s, a, extractor=ex)
    return s


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    search_timing._reset_for_tests()
    yield
    search_timing._reset_for_tests()


def _case(out: dict, key: str) -> dict:
    return next(r for r in out["results"] if r["case"] == key)


def test_the_first_page_is_the_page_size_the_search_tab_asks_for():
    """The Search tab sends `limit=DEFAULT_LIMIT`, the `default_result_limit` setting (50), on every
    article-list request; the route's own default of 100 is never what it loads. The benchmark
    reads the same setting, so a change of it moves the case and the number stays about the page a
    person actually waits on."""
    assert benchmark._first_page_limit() == AppSettings().default_result_limit == 50


def test_the_benchmark_asks_for_the_setting_not_a_copy_of_it(monkeypatch):
    asked: list[int] = []

    def spy(session, **kw):
        asked.append(kw["limit"])
        return [], 0

    monkeypatch.setattr(main, "_query_articles", spy)
    monkeypatch.setattr(
        "src.config.app_settings.load_settings", lambda: AppSettings(default_result_limit=25)
    )
    benchmark._article_page(_corpus(articles=False), None)
    assert asked == [25]


def test_a_settings_store_that_cannot_be_read_costs_the_case_its_page_size_not_the_benchmark(monkeypatch):
    """The page size is read while the case list is built, outside the per-case isolation: a raise
    there would have taken every case with it."""

    def broken():
        raise OSError("settings store unreadable")

    monkeypatch.setattr("src.config.app_settings.load_settings", broken)
    assert benchmark._first_page_limit() == benchmark._FIRST_PAGE_FALLBACK == AppSettings().default_result_limit
    out = run_benchmark(_corpus(), repeats=1)
    assert "page of 50" in _case(out, "browse_first_page")["note"]
    assert _case(out, "browse_first_page")["ok"] is True


def test_the_page_size_is_read_once_per_run_so_the_note_and_the_case_agree(monkeypatch):
    calls: list[int] = []

    def counting() -> int:
        calls.append(1)
        return 17

    monkeypatch.setattr(benchmark, "_first_page_limit", counting)
    asked: list[int] = []
    real = main._query_articles

    def spy(session, **kw):
        asked.append(kw["limit"])
        return real(session, **kw)

    monkeypatch.setattr(main, "_query_articles", spy)
    out = run_benchmark(_corpus(), repeats=2)
    assert len(calls) == 1, "read once, while the cases are built"
    assert set(asked) == {17} and len(asked) >= 4, asked  # two cases, two runs each
    assert "page of 17" in _case(out, "browse_first_page")["note"]


def test_the_browse_note_says_what_its_warm_figure_leaves_out():
    note = _case(run_benchmark(_corpus(), repeats=2), "browse_first_page")["note"]
    assert "warm (runs 2..N)" in note and "leaves the COUNT(*) out" in note
    # ...and does not promise it always does: a commit between runs, an expired entry, or no
    # cache / probe each make a later run pay the COUNT(*) again.
    assert "unless a commit landed between runs" in note and "pays the COUNT(*) again" in note
    import inspect

    from src.api import insights

    assert "(120 s by default)" in note and "evicted (it holds 128 entries)" in note
    assert "the data-version probe is unavailable" in note, "the probe has no off switch: it can only be unavailable"
    src = inspect.getsource(insights)
    assert 'getenv("OO_INSIGHTS_CACHE_TTL", "120")' in src and "SimpleCache(max_size=128" in src, (
        "the figures in the note are the cache's own; change them together"
    )


def test_the_case_notes_name_the_page_size_they_ran_with():
    out = run_benchmark(_corpus(), repeats=1)
    for key in ("browse_first_page", "search_first_page"):
        assert "page of 50" in _case(out, key)["note"], key
        assert "page of 100" not in _case(out, key)["note"], "the route's own default is not what ran"


def test_the_case_notes_make_no_claim_about_a_statement_deadline():
    """Nothing on this path arms one (the benchmark's session, `_query_articles`, `search_ids` and
    the cached count run without it), so a note saying a cold run 'can hit the statement deadline'
    described a failure the code cannot produce."""
    out = run_benchmark(_corpus(), repeats=1)
    for key in ("browse_first_page", "search_first_page"):
        assert "deadline" not in _case(out, key)["note"], key


def test_the_browse_is_timed_through_the_real_query_and_reports_its_page(tmp_path):
    out = run_benchmark(_corpus(), repeats=2)
    row = _case(out, "browse_first_page")
    assert row["ok"] is True
    assert row["result_size"] == len(_TEXTS), "the rows of the page, so a fast empty result is not a win"
    assert len(row["runs_ms"]) == 2 and row["cold_ms"] >= 0
    assert "THIS export" in row["note"], "cold means first in this export, not first after an unlock"
    assert "search-timing.json" in row["note"], "the per-phase split lives beside it"


def test_the_text_search_is_timed_end_to_end_for_the_busiest_keyword():
    out = run_benchmark(_corpus(), repeats=2)
    row = _case(out, "search_first_page")
    assert row["ok"] is True and row["result_size"] >= 1
    assert "first page" in row["label"].lower()
    # fts_search stays: it is the first step of this case, kept so the two can be compared
    assert _case(out, "fts_search")["case"] == "fts_search"


def test_the_benchmarks_own_runs_leave_no_trace_in_the_field_record(tmp_path):
    """The point of the suppression: the 3 text-search page calls of an export must not read as 3
    searches somebody made. Neither the in-process window nor either durable log sees them. (The
    browse case never asks for browse timing, so it leaves nothing either way; the text search is
    what the suppression holds back, and the control below shows it would otherwise be recorded.)"""
    run_benchmark(_corpus(), repeats=3)
    rep = search_timing.search_timing_report()
    assert rep["searches"] == 0 and rep["browse"]["pages"] == 0
    data = tmp_path / "data"
    assert not (data / "search_timing.jsonl").exists()
    assert not (data / "search_timing_browse.jsonl").exists()


def test_without_the_suppression_the_same_run_would_leave_searches_behind(monkeypatch):
    """The control that gives the test above its teeth: take the mute away and the export's own
    three text-search page calls turn up in the field record as searches nobody made."""
    monkeypatch.setattr(search_timing, "suppressed", contextlib.nullcontext)
    run_benchmark(_corpus(), repeats=3)
    assert search_timing.search_timing_report()["searches"] == 3


def test_a_real_search_after_the_benchmark_is_still_recorded():
    """Negative space of the suppression: it is scoped to the benchmark's own call."""
    s = _corpus()
    run_benchmark(s, repeats=1)
    main._query_articles(
        s, query="Senate", source=None, start_date=None, end_date=None, language=None,
        tags=None, limit=10, offset=0,
    )
    assert search_timing.search_timing_report()["searches"] == 1


def test_an_empty_corpus_still_times_the_browse_and_skips_the_term_bound_case():
    out = run_benchmark(_corpus(articles=False), repeats=1)
    keys = [r["case"] for r in out["results"]]
    assert "browse_first_page" in keys, "a browse needs no keyword"
    assert "search_first_page" not in keys, "never run on a fake term"
    row = _case(out, "browse_first_page")
    assert row["ok"] is True and row["result_size"] == 0


def test_a_failing_page_query_is_reported_per_case_and_never_aborts_the_run(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("statement exceeded its deadline")

    monkeypatch.setattr(main, "_query_articles", boom)
    out = run_benchmark(_corpus(), repeats=2)
    row = _case(out, "browse_first_page")
    assert row["ok"] is False and "deadline" in row["error"]
    assert _case(out, "search_first_page")["ok"] is False
    assert out["summary"]["cases_failed"] >= 2
    assert out["summary"]["cases_ok"] >= 1, "the other cases still ran"


def test_the_payload_still_carries_no_score_like_key():
    banned = ("trust_score", "credibility", "quality_score", "veracity", "reliability_score",
              "bias_score", "verdict")

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert str(k).lower() not in {"score", "rating", "rank", "trust"}, k
                assert not any(b in str(k).lower() for b in banned), k
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(run_benchmark(_corpus(), repeats=1))
