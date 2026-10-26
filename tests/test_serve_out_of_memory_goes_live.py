"""R194: a served query that runs out of memory is answered by the live scan; any other error keeps its empty answer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``windowed_top_terms_raw`` and ``windowed_term_counts`` swallow an engine error, count a fallback and answered ``[]`` / ``{}``; the serve
returned that empty answer, so the engine's own out-of-memory error (``OutOfMemoryException``) left Home and Insights with no top
terms and no trending, and only a counter to say why. They now answer ``None`` for that error, which the serve reads as "go live"
(``queries.top_terms`` and ``queries.trending`` both do). An ordinary error keeps the empty answer, a FATAL one still drops the
instance, and the fallback counter still counts every one of them by class name.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.analytics import columnar, queries, rollup_serve
from tests.test_rollup_build_streaming import (  # noqa: F401 - fixtures
    _break_serving,
    serve_env,
    serving,
    session,
)

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)


class OutOfMemoryException(Exception):  # noqa: N818 - the engine's own class name, which is what the serve keys on
    pass


def _counts(window=30):
    return rollup_serve.windowed_counts(None, lo=date.today() - timedelta(days=window), hi=date.today())


def test_the_two_serve_queries_answer_none_for_the_engines_out_of_memory_error_and_empty_for_any_other():
    class Boom:
        def __init__(self, exc):
            self._exc = exc

        def execute(self, *a, **k):
            raise self._exc("engine words that must not be kept")

    columnar._SERVE_FALLBACKS.clear()
    assert columnar.windowed_top_terms_raw(Boom(OutOfMemoryException)) is None
    assert columnar.windowed_term_counts(Boom(OutOfMemoryException)) is None
    assert columnar.windowed_top_terms_raw(Boom(RuntimeError)) == []
    assert columnar.windowed_term_counts(Boom(RuntimeError)) == {}
    seen = {(r["query"], r["error"]): r["count"] for r in columnar.serve_fallback_counts()["fallbacks"]}
    assert seen == {("top-terms", "OutOfMemoryException"): 1, ("term-counts", "OutOfMemoryException"): 1,
                    ("top-terms", "RuntimeError"): 1, ("term-counts", "RuntimeError"): 1}, "every one is still counted, by class name"


@pytest.mark.parametrize("which", ["rows", "counts"])
def test_a_served_query_that_runs_out_of_memory_is_answered_live_and_the_rollup_keeps_serving(serving, which):  # noqa: F811
    proxy = _break_serving("SELECT m.term" if which == "rows" else "SELECT keyword_id", words="Out of Memory Error", exc_cls=OutOfMemoryException)
    if which == "rows":
        assert rollup_serve.windowed_rows(serving, days=30) is None, "None sends the caller to the live scan"
    else:
        assert rollup_serve.windowed_counts(serving, lo=date.today() - timedelta(days=30), hi=date.today()) is None
    assert proxy.fired == 1
    assert rollup_serve._STATE["con"] is proxy, "the plain limit is not an invalid instance: the rollup stays"
    assert rollup_serve.status()["stopped"] is None
    fb = rollup_serve.status()["serve_fallbacks"]["fallbacks"]
    assert [r["error"] for r in fb] == ["OutOfMemoryException"] and fb[0]["count"] == 1


def test_top_terms_over_a_rollup_that_runs_out_of_memory_is_the_live_answer_not_an_empty_one(serving, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "0")
    live = queries.top_terms(serving, days=400, limit=5)
    assert live["terms"], "the seeded corpus (March 2026) is inside a 400-day window"
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    _break_serving("SELECT m.term", words="Out of Memory Error", exc_cls=OutOfMemoryException)
    got = queries.top_terms(serving, days=400, limit=5)
    assert got["terms"] == live["terms"], "empty before R194"


def test_an_ordinary_error_on_the_counts_keeps_the_empty_answer(serving):  # noqa: F811
    proxy = _break_serving("SELECT keyword_id", words="a plain error", exc_cls=RuntimeError)
    assert rollup_serve.windowed_counts(serving, lo=date.today() - timedelta(days=30), hi=date.today()) == {}
    assert proxy.fired == 1 and rollup_serve._STATE["con"] is proxy
