"""The record of a run that RAISED says how far its pass had got.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A run that raises has no ``result``, so its line in ``scheduler_runs.jsonl`` carried the error's class and nothing else:
all 30 recent runs in each field bundle of 2026-10-16 were pool timeouts, and none said whether the pass had got through
40 sources or 4,000. ``run_scrape_once`` notes its counters as it ends and ``_do_run`` copies them into the errored
record as ``pass_counts``. These tests drive the real pass and the real ``_do_run``, with the per-source work replaced.
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from src.database.models import Source
from src.ingest import EthicalFetcher
from src.scheduler import runner
from src.scheduler.runner import BackgroundScheduler
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


class _EmptyFeedSession:
    def __init__(self):
        self.headers: dict = {}
        self.proxies: dict = {}

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None, stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        return _Resp(text=_EMPTY_RSS, ct="application/rss+xml", url=url)


@pytest.fixture
def reports(monkeypatch, tmp_path):
    """The run reports ``_do_run`` writes, with the pass tail's own steps (hygiene, custody repayment) out of the way."""
    import src.scheduler.hygiene as hygiene

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    out: list[dict] = []
    monkeypatch.setattr("src.scheduler.runlog.record_run", out.append)
    monkeypatch.setattr(hygiene, "run_pass_hygiene", lambda: None)
    monkeypatch.setattr(runner, "_drain_owed_custody", lambda: None)
    return out


def _seed(n: int) -> str:
    """``n`` qualified feed sources under a tag of their own; the tag selects them."""
    from src.database.session import init_db, session_scope

    init_db()
    word = "rec" + uuid.uuid4().hex[:6]
    with session_scope() as s:
        for i in range(n):
            s.add(Source(
                name=f"R{i}", domain=f"{word}-{i}.example", rss_url=f"https://{word}-{i}.example/feed.xml",
                enabled=True, status="qualified", language="en", tags=word,
            ))
    return word


@pytest.fixture
def tag():
    """Five sources."""
    return _seed(5)


@pytest.fixture
def many_tag():
    """Twenty sources."""
    return _seed(20)


def _pass(tag: str, parallelism: int):
    from src.database.session import SessionLocal

    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_EmptyFeedSession())  # type: ignore[arg-type]
    settings = SchedulerSettings(collect_parallelism=parallelism, select_tags=[tag])
    sel = SessionLocal()
    try:
        return runner.run_scrape_once(sel, fetcher, settings)
    finally:
        sel.close()


def _scheduler(run_once) -> BackgroundScheduler:
    return BackgroundScheduler(run_once_fn=run_once, settings_provider=lambda: SchedulerSettings(continuous=False))


def _fails_after(monkeypatch, ok_sources: int, exc: Exception):
    """``_process_source`` stores 2 articles for each of the first ``ok_sources`` calls, then raises ``exc``."""
    calls = {"n": 0}

    def fake(source, *, session, fetcher):
        calls["n"] += 1
        if calls["n"] > ok_sources:
            raise exc
        return {"stored": 2}, 1, 1

    monkeypatch.setattr(runner, "_process_source", fake)


def test_a_pass_that_fails_part_way_says_how_far_it_got(reports, tag, monkeypatch):
    """Sequential pass, so the order is the call order: three sources processed (2 articles each), the fourth raises."""
    _fails_after(monkeypatch, 3, RuntimeError("boom"))
    _scheduler(lambda: _pass(tag, 1))._do_run()
    (rec,) = reports
    assert rec["ok"] is False and rec["error"] == "RuntimeError"
    assert rec["pass_counts"] == {
        "articles_stored": 6,
        "basis": "pass_raised",
        "sources_processed": 3,
        "sources_total": 5,
    }


def test_a_pool_timeout_from_a_worker_is_recorded_with_the_pass_counts(reports, tag, monkeypatch):
    """The field shape: a pool pass whose workers raise sqlalchemy's TimeoutError. The record names the class and the
    work list; nothing was read before the failure, and that is a count (0), not an unknown."""
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    def fake(source, *, session, fetcher):
        raise PoolTimeout("QueuePool limit of size 20 overflow 0 reached, connection timed out")

    monkeypatch.setattr(runner, "_process_source", fake)
    _scheduler(lambda: _pass(tag, 4))._do_run()
    (rec,) = reports
    assert rec["error"] == "TimeoutError"
    assert rec["pass_counts"]["basis"] == "pass_raised"
    assert rec["pass_counts"]["sources_total"] == 5
    assert rec["pass_counts"]["sources_processed"] == 0 and rec["pass_counts"]["articles_stored"] == 0


def test_a_pool_pass_counts_the_sources_that_ran_after_the_first_worker_failed(reports, many_tag, monkeypatch):
    """The case the field bundles are about, with the mix that makes the count mean something: 20 sources, 4 workers, the
    first two calls raise a pool timeout and the other 18 succeed. The first failure leaves the loop that reads the results;
    the pool's exit then waits for every queued source (it does not cancel them), so 18 ran and stored 2 articles each, and
    the second failure is a future nobody read. The record and the pass summary say 18 and 36, not 0 and 0, and the unread
    failure neither counts nor replaces the error that ended the pass."""
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from src.monitoring.collect_perf import CollectionMonitor

    lock = threading.Lock()
    calls = {"n": 0}

    def fake(source, *, session, fetcher):
        with lock:
            calls["n"] += 1
            fails = calls["n"] <= 2
        if fails:
            raise PoolTimeout("QueuePool limit of size 20 overflow 0 reached, connection timed out")
        return {"stored": 2}, 1, 1

    stopped: list[dict] = []
    real_stop = CollectionMonitor.stop

    def spy(self, result=None):
        stopped.append(dict(result or {}))
        return real_stop(self, result=result)

    monkeypatch.setattr(runner, "_process_source", fake)
    monkeypatch.setattr(CollectionMonitor, "stop", spy)
    _scheduler(lambda: _pass(many_tag, 4))._do_run()
    (rec,) = reports
    assert rec["error"] == "TimeoutError"
    assert calls["n"] == 20, "every queued source ran to its end"
    assert rec["pass_counts"] == {
        "articles_stored": 36,
        "basis": "pass_raised",
        "sources_processed": 18,
        "sources_total": 20,
    }
    assert [(r["sources_processed"], r["articles_stored"]) for r in stopped] == [(18, 36)], "the pass summary says the same"


def test_a_source_read_before_the_failure_is_counted_once_not_again_when_the_rest_are_drained(reports, many_tag, monkeypatch):
    """The drain reads only the futures the loop did not. Here the loop reads two successful sources, and only then does a third
    worker raise (it waits until the loop's progress callback has seen two), so the failure surfaces AFTER two results were
    counted. The other 17 sources finish while the pool shuts down, and are read by the drain. 19 sources processed, 38 articles;
    a drain that read every finished future again would say 21 and 42."""
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    seen_two = threading.Event()
    real_progress = runner._progress_set

    def progress(**kw):
        if kw.get("done", 0) >= 2:
            seen_two.set()
        return real_progress(**kw)

    lock = threading.Lock()
    calls = {"n": 0}

    def fake(source, *, session, fetcher):
        with lock:
            calls["n"] += 1
            mine = calls["n"]
        if mine == 3:
            assert seen_two.wait(10), "the loop never read the first two results"
            raise PoolTimeout("QueuePool limit of size 20 overflow 0 reached, connection timed out")
        return {"stored": 2}, 1, 1

    monkeypatch.setattr(runner, "_progress_set", progress)
    monkeypatch.setattr(runner, "_process_source", fake)
    _scheduler(lambda: _pass(many_tag, 4))._do_run()
    (rec,) = reports
    assert rec["error"] == "TimeoutError"
    assert calls["n"] == 20
    assert rec["pass_counts"] == {
        "articles_stored": 38,
        "basis": "pass_raised",
        "sources_processed": 19,
        "sources_total": 20,
    }


def test_a_run_that_loses_the_run_lock_does_not_wipe_the_counts_of_the_pass_that_holds_it(reports):
    """Run-now against a running pass: the second ``_do_run`` finds the lock taken and returns before it resets the slot."""
    holding = threading.Event()
    go = threading.Event()

    def run_once():
        runner._pass_counts_note(runner.COUNTS_COMPLETE, sources_total=7, sources_processed=3, articles_stored=9)
        holding.set()
        assert go.wait(5.0)
        raise ValueError("the first run fails after its pass")

    sched = _scheduler(run_once)
    first = threading.Thread(target=sched._do_run)
    first.start()
    try:
        assert holding.wait(5.0)
        sched._do_run()  # arrives while the first holds the run lock: returns at once, writes nothing
    finally:
        go.set()
        first.join(5.0)
    (rec,) = reports
    assert rec["pass_counts"] == {
        "articles_stored": 9,
        "basis": "pass_returned",
        "sources_processed": 3,
        "sources_total": 7,
    }


def test_a_failure_after_the_pass_returned_carries_the_passes_own_counts(reports, tag, monkeypatch):
    def fake(source, *, session, fetcher):
        return {"stored": 1}, 1, 1

    monkeypatch.setattr(runner, "_process_source", fake)

    def run_once():
        _pass(tag, 1)
        raise ValueError("the pass tail failed")

    _scheduler(run_once)._do_run()
    (rec,) = reports
    assert rec["error"] == "ValueError"
    assert rec["pass_counts"] == {
        "articles_stored": 5,
        "basis": "pass_returned",
        "sources_processed": 5,
        "sources_total": 5,
    }


def test_a_failure_before_the_pass_counted_anything_says_unknown_never_zero(reports):
    def run_once():
        raise RuntimeError("no connection for the session")

    _scheduler(run_once)._do_run()
    (rec,) = reports
    counts = rec["pass_counts"]
    assert counts["basis"] == "not_reported"
    for name in ("sources_total", "sources_processed", "articles_stored"):
        assert counts[name] is None, f"{name} is unknown here, and an unknown is null, not 0"


def test_the_counts_of_one_run_never_reach_the_record_of_the_next(reports, tag, monkeypatch):
    def fake(source, *, session, fetcher):
        return {"stored": 1}, 1, 1

    monkeypatch.setattr(runner, "_process_source", fake)
    calls = {"n": 0}

    def run_once():
        calls["n"] += 1
        if calls["n"] == 1:
            _pass(tag, 1)
        raise ValueError("fails either way")

    sched = _scheduler(run_once)
    sched._do_run()
    sched._do_run()
    first, second = reports
    assert first["pass_counts"]["basis"] == "pass_returned" and first["pass_counts"]["sources_processed"] == 5
    assert second["pass_counts"]["basis"] == "not_reported", "the second run never counted: it must not show the first's"
    assert second["pass_counts"]["sources_processed"] is None


def test_a_run_that_returned_does_not_repeat_its_counts_in_the_record(reports):
    """Its ``result`` already holds them; a second copy would spend the size the errored rows need."""
    _scheduler(lambda: {"sources_processed": 3, "articles_stored": 7})._do_run()
    (rec,) = reports
    assert rec["ok"] is True and "pass_counts" not in rec


def test_the_record_holds_the_class_of_the_failure_and_none_of_its_words(reports, tag, monkeypatch):
    secret = "pa55-phrase-" + uuid.uuid4().hex
    _fails_after(monkeypatch, 1, RuntimeError(f"cannot open the store with {secret}"))
    _scheduler(lambda: _pass(tag, 1))._do_run()
    (rec,) = reports
    assert secret not in json.dumps(rec, default=str)
    assert rec["error"] == "RuntimeError"


def test_the_member_is_closed_vocabulary_and_numbers_only(reports, tag, monkeypatch):
    _fails_after(monkeypatch, 2, RuntimeError("x"))
    _scheduler(lambda: _pass(tag, 1))._do_run()
    counts = reports[0]["pass_counts"]
    assert set(counts) == {"articles_stored", "basis", "sources_processed", "sources_total"}
    assert counts["basis"] in {runner.COUNTS_COMPLETE, runner.COUNTS_PARTIAL, runner.COUNTS_UNREPORTED}
    assert all(isinstance(counts[k], int) for k in ("articles_stored", "sources_processed", "sources_total"))


def test_the_bytes_the_member_adds_to_a_row_are_what_the_comment_says(reports):
    """Measured on the REAL record: ``_do_run`` writes an errored row, once with the counts unknown (the run function never
    reported) and once with each basis and 10-digit counts. The member adds 117 bytes of JSON to a row when the counts are
    unknown and at most 136 when they are known, so the 30 rows of ``scheduler.recent_runs`` in a debug bundle grow by at
    most 4.1 KB. A field row
    measured 430-963 bytes (30 rows, 25.5 KB); the member ``debug-bundle.json`` is bounded only by the per-member cap
    (12 MB), and was 513 KB."""
    big = 9_999_999_999

    def raising(note):
        def run_once():
            if note is not None:
                runner._pass_counts_note(note, sources_total=big, sources_processed=big, articles_stored=big)
            raise RuntimeError("x")

        return run_once

    def row_bytes(report: dict) -> int:
        return len(json.dumps(report, sort_keys=True, default=str))

    _scheduler(raising(None))._do_run()
    _scheduler(raising(runner.COUNTS_PARTIAL))._do_run()
    _scheduler(raising(runner.COUNTS_COMPLETE))._do_run()
    unknown, partial, complete = reports

    def grown(report: dict) -> int:
        return row_bytes(report) - row_bytes({k: v for k, v in report.items() if k != "pass_counts"})

    # started_at/finished_at have the same length in every row, so the growth is the member alone.
    assert grown(unknown) == 117
    assert grown(partial) == 134
    assert grown(complete) == 136
    assert 30 * max(grown(r) for r in reports) <= 4_200
