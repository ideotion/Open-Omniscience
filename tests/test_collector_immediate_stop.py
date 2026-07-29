"""An explicit stop reaches an IN-FLIGHT collection pass (field report 2026-07-29).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE BUG: ``BackgroundScheduler.stop()`` sets its event and joins with a 10 s timeout,
but ``_do_run`` had NO mid-pass stop check -- ``runner.py``'s own docstring said so.
A pass already inside a fetch therefore ran its WHOLE remaining source list to
completion. Over Tor that is easily tens of minutes, which is why importing a backup
while collecting measured 3-5x slower: ``pause_for_exclusive_operation`` returned, the
import claimed the machine, and the "paused" collector kept fetching against it.

THE FIX: the stop predicate is consulted by ``_PassWindDown.admit()``, which every
worker already calls BEFORE starting a source. So a stop lands within one source.

Two properties are load-bearing and pinned here:

  * STILL NEVER MID-FETCH -- in-flight work finishes, so per-host politeness and the
    robots contract are untouched. This is "stop admitting", not "abort".
  * NOTHING IS DROPPED -- the un-admitted remainder rides the same deferral path as a
    budget wind-down and runs FIRST next pass. Ordering, never exclusion.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Base, Source
from src.ingest import EthicalFetcher
from src.scheduler import runner
from src.scheduler.runner import run_scrape_once
from src.scheduler.settings import SchedulerSettings

_EMPTY_RSS = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'


class _Resp:
    def __init__(self, text="", ct="text/html", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self):
        pass


class _FeedSession:
    """Permissive robots + an empty RSS (mirrors tests/test_pass_recycling.py's own
    fake, so this suite exercises the same real fetch path)."""

    def __init__(self) -> None:
        self.headers: dict = {}
        self.proxies: dict = {}

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        return _Resp(text=_EMPTY_RSS, ct="application/rss+xml", url=url)


def _mem_session():
    eng = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def _seed(session, n: int, tag: str) -> list[int]:
    ids = []
    for i in range(n):
        s = Source(
            name=f"R{i}", domain=f"{tag}-{i}.example",
            rss_url=f"https://{tag}-{i}.example/feed.xml",
            enabled=True, status="qualified", language="en", tags=tag,
        )
        session.add(s)
        session.commit()
        ids.append(s.id)
    return ids


@pytest.fixture(autouse=True)
def _clean_carryover():
    runner._consume_deferred()
    yield
    runner._consume_deferred()


# --------------------------------------------------------------------------- #
#  the decider
# --------------------------------------------------------------------------- #
def test_a_requested_stop_wins_over_every_other_reason():
    stop = threading.Event()
    wd = runner._PassWindDown(budget_s=0.0, max_sources=0, now=lambda: 0.0,
                              should_stop=stop.is_set)
    assert wd.admit() is None, "not stopping yet -- admit normally"
    stop.set()
    assert wd.admit() == "stopping"
    assert wd.admit() == "stopping", "stays wound down"


def test_stopping_has_NO_forward_progress_floor():
    """A budget deliberately admits the first source even when already expired (an
    env typo must not yield zero progress forever). An explicit stop is the opposite
    situation: the operator -- or an exclusive import -- asked for no more work, so
    admitting "just one more" would be exactly wrong."""
    stop = threading.Event()
    stop.set()
    wd = runner._PassWindDown(budget_s=0.0, max_sources=0, now=lambda: 0.0,
                              should_stop=stop.is_set)
    assert wd.admit() == "stopping", "not even the first source"


def test_no_predicate_is_byte_identical_to_before():
    wd = runner._PassWindDown(budget_s=0.0, max_sources=0, now=lambda: 1e9)
    for _ in range(50):
        assert wd.admit() is None


def test_a_raising_predicate_never_wedges_a_pass():
    """Report-only machinery must never be able to halt collection."""
    def _boom() -> bool:
        raise RuntimeError("broken predicate")

    wd = runner._PassWindDown(budget_s=0.0, max_sources=0, now=lambda: 0.0, should_stop=_boom)
    assert wd.admit() is None, "a broken stop check degrades to 'keep going', never to a halt"


# --------------------------------------------------------------------------- #
#  end to end
# --------------------------------------------------------------------------- #
def test_a_stop_mid_pass_defers_the_remainder_and_drops_nothing(monkeypatch):
    """THE FIELD BUG, end to end. Stop after the first source; the rest must be
    deferred (not processed, not dropped) and must run first next pass."""
    monkeypatch.setenv("OO_PASS_BUDGET_MINUTES", "0")
    monkeypatch.setenv("OO_PASS_MAX_SOURCES", "0")
    monkeypatch.setenv("OO_COLLECT_PARALLELISM", "1")  # deterministic ordering

    session = _mem_session()
    tag = "st" + uuid.uuid4().hex[:6]
    ids = _seed(session, 5, tag)

    stop = threading.Event()
    calls = {"n": 0}

    def _should_stop() -> bool:
        # Let exactly one source through, then behave like stop() was called.
        if calls["n"] >= 1:
            stop.set()
        calls["n"] += 1
        return stop.is_set()

    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_FeedSession())
    res = run_scrape_once(
        session, fetcher, SchedulerSettings(mode="rss"), should_stop=_should_stop
    )

    assert res["sources_processed"] == 1
    assert res["deferred_next_pass"] == 4
    assert res["recycled"] == "stopping", "the reason is reported honestly, not as a budget"

    # The exactness invariant: processed + deferred covers every selected source.
    deferred = runner._consume_deferred()
    assert len(deferred) == 4 and set(deferred) < set(ids)
    session.close()


def test_without_a_stop_the_whole_pass_still_runs(monkeypatch):
    """The negative space: the new check must not wind anything down on its own."""
    monkeypatch.setenv("OO_PASS_BUDGET_MINUTES", "0")
    monkeypatch.setenv("OO_PASS_MAX_SOURCES", "0")
    session = _mem_session()
    tag = "ns" + uuid.uuid4().hex[:6]
    _seed(session, 4, tag)
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_FeedSession())

    res = run_scrape_once(
        session, fetcher, SchedulerSettings(mode="rss"), should_stop=lambda: False
    )
    assert res["sources_processed"] == 4
    assert "recycled" not in res and "deferred_next_pass" not in res
    assert runner.deferred_carryover_count() == 0
    session.close()


def test_the_scheduler_hands_its_own_stop_event_to_the_pass():
    """Wiring: without this the decider would be dead code in production. Scoped to
    _default_run_once's own body -- a whole-file search would pass on the mere
    presence of the parameter somewhere else."""
    import re
    from pathlib import Path

    src = Path(runner.__file__).read_text(encoding="utf-8")
    body = src.split("def _default_run_once(")[1]
    nxt = re.search(r"\n    (?:async )?def ", body)
    body = body[: nxt.start()] if nxt else body
    assert "run_scrape_once(session, fetcher, settings, should_stop=self._stop.is_set)" in body
