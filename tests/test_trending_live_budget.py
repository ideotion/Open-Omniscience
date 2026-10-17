"""/trending-windows never spends a whole statement deadline on the live scan: it stops, says so, and is not cached as whole.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-10-16, a running install whose rollup build had been stopped: 533 requests to this endpoint ran the live scan
(17 to 177 s a window on 12 M mentions), 362 of them ended in the 60 s statement deadline (503) and the median
request was the deadline itself. With ``live_budget_s`` the call reads the shortest window first,
then the longer ones, stops at the budget, leaves the windows it did not finish OUT of ``windows`` (an uncomputed window
is not an empty one) and names them in ``skipped_windows``. Without a budget nothing changes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import src.api.insights as ins
from src.analytics import queries as q
from src.database import query as dq
from src.database.derived_views import KeywordMentionRead as KM
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def sess(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'b.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, future=True)
    today = date.today()
    with S() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        for k in (1, 2, 3):
            s.add(Keyword(id=k, term=f"t{k}", normalized_term=f"t{k}", language="en"))
        s.commit()
        for aid in range(1, 41):
            s.add(Article(url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}", source_id=1, title="t",
                          content="c", hash=f"h{aid}", language="en", created_at=datetime.now(UTC)))
            s.commit()
            for k in (1, 2, 3):
                s.add(KeywordMention(keyword_id=k, article_id=aid, count=1, observed_on=today - timedelta(days=aid % 20)))
            s.commit()
        yield s


def _gc(s, **kw):
    return dq.windowed_group_counts(
        s, key=KM.keyword_id, day=KM.observed_on, rowid=KM.id, value=func_sum(), lo=date.today() - timedelta(days=10),
        hi=date.today() + timedelta(days=1), keep=lambda _k, _v: True, **kw
    )


def func_sum():
    from sqlalchemy import func

    return func.sum(KM.count)


def test_a_read_past_its_deadline_stops_before_its_next_statement(sess):
    full, groups = _gc(sess)
    assert groups == 3 and full
    with pytest.raises(dq.ReadBudgetExceeded):
        _gc(sess, deadline=0.0)  # long gone


def test_a_read_stops_between_statements_not_at_the_end(sess, monkeypatch):
    seen = []

    @event.listens_for(sess.get_bind(), "before_cursor_execute")
    def _count(_c, _cur, statement, *_a):  # noqa: ANN001
        seen.append(statement)

    _gc(sess)
    full_statements = len(seen)
    seen.clear()
    ticks = iter(range(10_000))
    monkeypatch.setattr(dq.time, "monotonic", lambda: float(next(ticks)))
    with pytest.raises(dq.ReadBudgetExceeded):
        _gc(sess, deadline=5.0)  # the 6th look at the clock is past it
    assert 0 < len(seen) < full_statements, (len(seen), full_statements)


def test_no_deadline_is_the_read_of_before(sess):
    assert _gc(sess) == _gc(sess, deadline=None)
    assert _gc(sess) == _gc(sess, deadline=10**12)  # not reached


class _Clock:
    def __init__(self, ticks):
        self.ticks = iter(ticks)
        self.now = 0.0

    def __call__(self):
        self.now = next(self.ticks, self.now)
        return self.now


def _fake_trending(raises=(), asked=None):
    def fake(session, *, window_days, baseline_days, read_deadline=None, **kw):
        if asked is not None:
            asked.append(window_days)
        if window_days in raises:
            raise dq.ReadBudgetExceeded("stop")
        return {"terms": [{"term": f"w{window_days}", "normalized": f"w{window_days}"}], "count": 1, "scanned": 1}

    return fake


def test_unbounded_is_byte_identical_to_a_budget_that_is_never_reached(sess):
    base = q.trending_windows(sess, limit=4)
    assert "partial" not in base and "skipped_windows" not in base
    assert q.trending_windows(sess, limit=4, live_budget_s=600) == base


def test_the_shortest_window_is_read_first_and_a_window_the_budget_stops_is_left_out_and_named(sess, monkeypatch):
    asked: list[int] = []
    monkeypatch.setattr(q, "trending", _fake_trending(raises=(7,), asked=asked))
    out = q.trending_windows(sess, limit=4, live_budget_s=20)
    assert asked[0] == 1, "the cheapest window goes first, so a small budget still keeps what it paid for"
    assert [w["label"] for w in out["windows"]] == ["24h", "30d"]  # the presets' own order, 7d missing
    assert out["partial"] is True and out["live_budget_s"] == 20.0
    assert out["skipped_windows"] == [{"label": "7d", "window_days": 7, "baseline_days": 30,
                                       "reason": "time-budget", "started": True}]
    assert out["caveat"].startswith("Partial:")


def test_the_partial_caveat_names_no_cause_that_can_be_false(sess):
    """A country-filtered read or a rollup miss is partial with the rollup BUILT: the caveat must not say it is not."""
    out = q.trending_windows(sess, limit=4, live_budget_s=1e-9)
    assert "not built" not in out["caveat"] and "not serving this request" in out["caveat"]


def test_once_the_budget_is_spent_the_remaining_windows_are_not_started(sess, monkeypatch):
    asked: list[int] = []
    monkeypatch.setattr(q, "trending", _fake_trending(asked=asked))
    # the clock reads: deadline setup (0), before 24h (1), before the next window (50, past the budget)
    monkeypatch.setattr(q.time, "monotonic", _Clock([0.0, 1.0, 50.0, 50.0]))
    out = q.trending_windows(sess, limit=4, live_budget_s=20)
    assert asked == [1], "no scan was started past the budget"
    assert [w["label"] for w in out["windows"]] == ["24h"]
    assert [(w["label"], w["started"]) for w in out["skipped_windows"]] == [("7d", False), ("30d", False)]


def test_a_budget_nothing_fits_in_is_an_honest_empty_partial_not_an_error(sess):
    out = q.trending_windows(sess, limit=4, live_budget_s=1e-9)
    assert out["windows"] == [] and out["partial"] is True
    assert len(out["skipped_windows"]) == 3


def test_the_budget_is_read_per_call_and_zero_turns_it_off(monkeypatch):
    monkeypatch.delenv("OO_TRENDING_LIVE_BUDGET_S", raising=False)
    assert ins._trending_live_budget_s() == 20.0
    monkeypatch.setenv("OO_TRENDING_LIVE_BUDGET_S", "7.5")
    assert ins._trending_live_budget_s() == 7.5
    monkeypatch.setenv("OO_TRENDING_LIVE_BUDGET_S", "0")
    assert ins._trending_live_budget_s() is None
    monkeypatch.setenv("OO_TRENDING_LIVE_BUDGET_S", "garbage")
    assert ins._trending_live_budget_s() == 20.0


def test_the_endpoint_passes_the_budget_and_returns_the_partial_payload_untouched(sess, monkeypatch):
    seen = {}

    def fake(session, **kw):
        seen.update(kw)
        return {"windows": [], "partial": True, "skipped_windows": [], "caveat": "Partial: x"}

    monkeypatch.setattr(ins.rm, "trending_windows", fake)
    monkeypatch.delenv("OO_TRENDING_LIVE_BUDGET_S", raising=False)
    ins._read_cache._cache.clear()
    out = ins.insights_trending_windows(country=None, kind=None, limit=4, series_top=0, target_lang=None, db=sess)
    assert seen["live_budget_s"] == 20.0
    assert out["partial"] is True and out["caveat"] == "Partial: x"
    # the warmer computes WITHOUT a budget: a full payload it caches is a hit the budget never sees
    import inspect

    assert "live_budget_s" not in inspect.getsource(ins.warm_cache)


def test_insights_says_not_computed_for_a_partial_answer_with_no_window():
    """The defect: ``windows: []`` printed "No rising keywords in this window yet.", the misreading the leave-out prevents."""
    from tests.js_source_helper import function_body, read_static

    body = function_body(read_static("app-corpus.js"), "loadTrendWindows")
    i = body.index('.join("") ||')
    tail = body[i:]
    assert "d.partial && d.caveat" in tail and "t(d.caveat)" in tail
    assert tail.index("d.partial && d.caveat") < tail.index("No rising keywords in this window yet."), \
        "the partial branch is chosen before the empty state"
