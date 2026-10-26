"""/api/insights/status: the two whole-index scans run in the background, carried for ten times their cost (audit 0.5.0, A-002).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The route used to be keyed on ``PRAGMA data_version``, which changes on every commit by any connection, so during a collection pass
(a commit per batch) every 6 s poll was a miss and ran ``count(distinct article_id)`` and ``count(id)`` over the whole mention index
on the request thread, with no deadline. It now goes through ``served_cache``: the totals answer at once, the two scans run once, in
the background, under a statement deadline, and a finished pair is carried for ten times its measured duration.

Every "no scan" assertion is scoped by THREAD where the claim is about the request thread, because the background refresher does
issue the scans, on its own thread, which is the point. The clock-dependent cases move BOTH clocks (the served cache's and the
scans') and move the cache's change probe: with nothing written ``served_cache`` re-stamps a stale entry as verified and starts no
refresh, so a test that only advances time would pass for the wrong reason.
"""

from __future__ import annotations

import threading
import time
import types
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.api import insights, served_cache
from src.database.maintenance import MemoryShort, StatementTimeout
from src.database.models import Article, Base, Source
from src.database.session import SessionLocal, engine, init_db


def setup_module(_module):
    init_db()


class _Clock:
    """Both clocks the route depends on, moved together: the served cache's ``time.time`` and the scans' epoch + monotonic."""

    def __init__(self, monkeypatch) -> None:
        self.now = time.time()
        self.step = 0.0  # added to the monotonic reading on every call, so a scan's measured duration is exactly `step`
        self._mono = 0.0
        monkeypatch.setattr(served_cache, "time", types.SimpleNamespace(time=lambda: self.now))
        monkeypatch.setattr(insights, "_status_now_s", lambda: self.now)
        monkeypatch.setattr(insights, "_status_clock", self._tick)

    def _tick(self) -> float:
        self._mono += self.step
        return self._mono

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Capture:
    """Records statements that read the mention index; ``thread`` restricts it to one thread."""

    def __init__(self, thread: int | None = None) -> None:
        self.statements: list[str] = []
        self._thread = thread

    def __enter__(self):
        @event.listens_for(engine, "before_cursor_execute")
        def _on(conn, cursor, statement, params, ctx, many):  # noqa: ANN001
            if "keyword_mentions" in statement and (self._thread is None or threading.get_ident() == self._thread):
                self.statements.append(statement.split("FROM")[0][:60])

        self._listener = _on
        return self

    def __exit__(self, *exc):
        event.remove(engine, "before_cursor_execute", self._listener)
        return False


def _poll() -> dict:
    s = SessionLocal()
    try:
        return insights.insights_status(s)
    finally:
        s.close()


def _idle(timeout: float = 30.0) -> None:
    """Wait for the background recompute (if any) to finish."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with served_cache._LOCK:
            running = insights._STATUS_KEY in served_cache._RECOUNT_STARTED
        if not running:
            return
        time.sleep(0.02)
    raise AssertionError("the background recompute did not finish")


def _add_article(indexed: bool = False) -> None:
    s = SessionLocal()
    try:
        src = Source(name=f"s-{uuid.uuid4().hex[:8]}", domain=f"{uuid.uuid4().hex[:8]}.test")
        s.add(src)
        s.flush()
        u = f"https://{src.domain}/{uuid.uuid4().hex[:6]}"
        a = Article(
            url=u, canonical_url=u, source_id=src.id, title="T", content="tariff steel industry policy diplomacy",
            hash=uuid.uuid4().hex[:16], language="en", word_count=5,
            published_at=datetime(2026, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        if indexed:
            from src.analytics.extract import BaselineExtractor
            from src.analytics.store import index_article

            index_article(s, a, extractor=BaselineExtractor())
            s.commit()
    finally:
        s.close()


@pytest.fixture()
def clock(monkeypatch):
    return _Clock(monkeypatch)


def test_a_cold_poll_answers_the_totals_at_once_and_runs_no_scan_on_the_request_thread():
    _add_article(indexed=True)
    with _Capture(thread=threading.get_ident()) as on_request:
        first = _poll()
        _idle()
    assert on_request.statements == [], "the request thread must never read the mention index"
    assert first["total_articles"] >= 1 and first["keywords"] >= 1, "the totals are exact now"
    assert first["indexed_articles"] is None and first["remaining"] is None and first["mentions"] is None, (
        "a scan that has not finished is not known: null, never a zero"
    )
    assert first["index_counts_state"] == "computing" and first["pending"] is True
    assert first["index_counts_reason"] and first["pending_since"], "the unknown is named, with when the count started"


def test_the_background_pass_lands_the_same_exact_counts_the_blocking_status_gives():
    _add_article(indexed=True)
    _add_article(indexed=False)
    _poll()
    _idle()
    served = _poll()
    s = SessionLocal()
    try:
        exact = q.status(s)
    finally:
        s.close()
    assert served["index_counts_state"] == "counted" and served["index_counts_computed_at"]
    for key in ("total_articles", "indexed_articles", "remaining", "keywords", "entities", "mentions"):
        assert served[key] == exact[key], key
    assert served["remaining"] >= 1
    assert not any("score" in k.lower() for k in served)


def test_a_commit_per_batch_no_longer_makes_every_poll_a_miss(monkeypatch):
    """The recorded defect: ``PRAGMA data_version`` moves on every commit, so every poll during a pass was a full recompute."""
    _poll()
    _idle()
    calls = []
    real = insights._compute_status
    monkeypatch.setattr(insights, "_compute_status", lambda db: (calls.append(1), real(db))[1])
    for _ in range(6):
        _add_article()  # a commit by another connection, the production shape
        got = _poll()
        assert got["cached"] is True
    _idle()
    assert calls == [], "six polls straddling six commits inside the interval recompute nothing"


def test_a_stale_entry_inside_the_scan_window_refreshes_the_totals_and_starts_no_scan(clock):
    clock.step = 10.0  # the scans measured 10 s, so they are carried for 100 s
    _add_article(indexed=True)
    _poll()
    _idle()
    counted = _poll()
    assert counted["index_counts_recount_after_s"] == 100, "ten times the measured duration"

    _add_article(indexed=False)  # moves the cache's probe
    clock.advance(60)  # past the 15 s interval, inside the 100 s window
    before_total = counted["total_articles"]
    with _Capture() as everywhere:
        stale = _poll()
        _idle()
        fresh = _poll()
    assert stale["cached"] is True and stale["total_articles"] == before_total, "the poll itself is answered from the entry"
    assert fresh["total_articles"] == before_total + 1, "the totals were recomputed in the background"
    assert everywhere.statements == [], "inside the window no scan starts, on any thread"
    assert fresh["index_counts_computed_at"] == counted["index_counts_computed_at"], "the carried pair keeps its own stamp"
    assert fresh["indexed_articles"] == counted["indexed_articles"] and fresh["mentions"] == counted["mentions"]


def test_the_scans_repeat_once_their_window_has_passed(clock):
    clock.step = 10.0
    _add_article(indexed=True)
    _poll()
    _idle()
    first = _poll()
    _add_article(indexed=True)
    clock.advance(101)  # past ten times the measured duration
    with _Capture() as everywhere:
        _poll()
        _idle()
    assert everywhere.statements, "after the window the scans run again, on the background thread"
    again = _poll()
    assert again["mentions"] > first["mentions"] and again["indexed_articles"] == first["indexed_articles"] + 1
    assert again["index_counts_computed_at"] != first["index_counts_computed_at"]


@pytest.mark.parametrize(
    ("exc", "kind"),
    [(StatementTimeout("over its limit"), "statement-deadline"), (MemoryShort("low on memory"), "memory-short"),
     (RuntimeError("boom"), "RuntimeError")],
)
def test_a_scan_that_cannot_finish_is_a_named_failure_held_for_its_window(monkeypatch, clock, exc, kind):
    calls = []

    def _fails(_session):
        calls.append(1)
        raise exc

    monkeypatch.setattr(q, "status_mentions", _fails)
    _poll()
    _idle()
    failed = _poll()
    assert failed["index_counts_state"] == "failed"
    assert failed["indexed_articles"] is None and failed["remaining"] is None and failed["mentions"] is None
    f = failed["index_counts_failure"]
    assert f["kind"] == kind and f["retry_after_s"] == insights._STATUS_FAILURE_WINDOW_S and f["deadline_s"] > 0
    assert failed["total_articles"] >= 0 and "keywords" in failed, "the totals are still exact"
    assert "boom" not in repr(failed) and "over its limit" not in repr(failed), "only the kind is published, never the words"
    assert len(calls) == 1

    _add_article()  # moves the probe
    clock.advance(insights._STATUS_FAILURE_WINDOW_S - 60)
    _poll()
    _idle()
    assert len(calls) == 1, "a failure inside its window is not retried"
    _add_article()
    clock.advance(120)
    _poll()
    _idle()
    assert len(calls) == 2, "when the window ends it is tried again"


def test_the_scans_are_the_only_statements_under_the_statement_deadline(monkeypatch):
    """The deadline names what it protects: each scan runs inside its own ``statement_deadline`` of the stated length."""
    seen = []
    real = insights.statement_deadline

    def _spy(session, seconds=None):
        seen.append(seconds)
        return real(session, seconds)

    monkeypatch.setattr(insights, "statement_deadline", _spy)
    _poll()
    _idle()
    assert seen == [insights._STATUS_SCAN_DEADLINE_S] * 2
    assert insights._STATUS_SCAN_DEADLINE_S == 500.0 and insights._STATUS_SCAN_DUTY_FACTOR == 10


def test_scans_made_over_one_database_are_never_carried_to_another(tmp_path):
    other = create_engine(f"sqlite:///{tmp_path / 'o.db'}", future=True)
    Base.metadata.create_all(other)
    mine = SessionLocal()
    theirs = sessionmaker(bind=other, future=True)()
    try:
        insights._remember_status_scans(mine, 0, insights._STATUS_GENERATION[0], 5, 4, 40, 1.0)
        assert insights._carried_status_scans(mine, 0) is not None
        assert insights._carried_status_scans(theirs, 0) is None, "another database never inherits the counts"
    finally:
        mine.close()
        theirs.close()
        other.dispose()


def test_counts_taken_before_the_last_write_are_recounted_when_their_window_ends_even_if_nothing_is_written_after(clock):
    """Opus read finding 1. A refresh that carries the old pair stored the entry under the probe read AFTER the latest write; with
    no write after it every later poll saw the probe unchanged, re-stamped the entry as verified and never recomputed, so counts
    taken before that write were served for ever with ``verified_current: true``."""
    clock.step = 10.0  # carried for 100 s
    _add_article(indexed=True)
    _poll()
    _idle()
    _add_article(indexed=True)  # a write inside the window; collection then stops for good
    clock.advance(20)
    _poll()
    _idle()  # the carried refresh: totals fresh, pair carried
    mid = _poll()
    assert mid["verified_current"] is False, "a carried count is never vouched for by the write probe"
    for _ in range(20):  # long past the window, with no further write
        clock.advance(200)
        _poll()
        _idle()
    late = _poll()
    s = SessionLocal()
    try:
        exact = q.status(s)
    finally:
        s.close()
    assert late["indexed_articles"] == exact["indexed_articles"] and late["mentions"] == exact["mentions"]
    assert late["remaining"] == exact["remaining"]


def test_an_invalidate_forgets_the_carried_pair_and_a_new_corpus_epoch_does_too(clock):
    """Opus read finding 2. A restore swaps the file under the one module-level engine object, so identity alone never notices."""
    from src.analytics.corpus_epoch import bump_corpus_epoch

    clock.step = 10.0
    _add_article(indexed=True)
    _poll()
    _idle()
    insights._STATUS_MEMO["indexed"] = 999_999  # stands in for the replaced corpus's count on the same engine object
    served_cache.invalidate()  # what run_restore's swap and a VACUUM do
    assert insights._STATUS_MEMO == {} and insights._STATUS_FAILURE == {}
    _poll()
    _idle()
    assert _poll()["indexed_articles"] != 999_999

    insights._STATUS_MEMO["indexed"] = 888_888
    s = SessionLocal()
    try:
        bump_corpus_epoch(s, reason="test")
        s.commit()
    finally:
        s.close()
    clock.advance(20)
    _add_article()  # moves the probe so the entry is recomputed
    _poll()
    _idle()
    assert _poll()["indexed_articles"] != 888_888, "a pair made at another epoch is not carried"


def test_scans_that_were_running_when_the_corpus_was_swapped_are_not_remembered(monkeypatch):
    """Opus read finding 2, the in-flight variant: a scan holding the old file open lands its numbers after the swap."""
    real = q.status_mentions

    def _swap_then_finish(session):
        served_cache.invalidate()  # the restore's swap happens while this scan is reading
        return real(session)

    monkeypatch.setattr(q, "status_mentions", _swap_then_finish)
    _poll()
    _idle()
    assert insights._STATUS_MEMO == {}, "the pair was counted over the file that was swapped out"
    with served_cache._LOCK:
        assert insights._STATUS_KEY not in served_cache._CACHE, "nor is the payload served as 'counted' for a TTL"
    monkeypatch.setattr(q, "status_mentions", real)
    again = _poll()  # nothing cached: the next poll starts the count over the file that is there now
    assert again["index_counts_state"] == "computing"
    _idle()
    assert _poll()["index_counts_state"] == "counted"


def test_the_generation_is_read_before_the_first_read_of_the_database(monkeypatch):
    """An invalidate between the totals read and the scans must not leave the scans looking current."""
    real = q.status_totals
    fired = []

    def _swap_after_totals(session):
        out = real(session)
        if not fired:  # only the first read, the one before the scans (the scans' own total read must not swap again)
            fired.append(1)
            served_cache.invalidate()
        return out

    monkeypatch.setattr(q, "status_totals", _swap_after_totals)
    _poll()
    _idle()
    assert insights._STATUS_MEMO == {}


def test_a_failure_does_not_freeze_the_cheap_totals(monkeypatch, clock):
    """Opus read finding 4. The failure window is the scans' retry window, not the totals': they keep refreshing meanwhile."""
    calls = []

    def _fails(_session):
        calls.append(1)
        raise StatementTimeout("over its limit")

    monkeypatch.setattr(q, "status_mentions", _fails)
    _poll()
    _idle()
    failed = _poll()
    assert failed["index_counts_state"] == "failed"
    _add_article()
    clock.advance(60)  # inside the 1,200 s window, past the 15 s interval
    _poll()
    _idle()
    later = _poll()
    assert later["total_articles"] == failed["total_articles"] + 1, "the totals refreshed inside the failure window"
    assert later["index_counts_state"] == "failed" and len(calls) == 1, "and no scan was retried"
    assert later["index_counts_failure"]["at"] == failed["index_counts_failure"]["at"]
    assert later["index_counts_failure"]["retry_after_s"] == insights._STATUS_FAILURE_WINDOW_S - 60, "the time actually left"
    clock.advance(insights._STATUS_FAILURE_WINDOW_S)  # nothing written: the window ending alone must start the retry
    _poll()
    _idle()
    assert len(calls) == 2, "the window ending is noticed on an idle store"


def test_the_route_keeps_every_field_the_page_reads():
    """FastAPI drops anything the response model does not declare, so go through the real route."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    _add_article(indexed=True)
    with TestClient(app) as client:
        first = client.get("/api/insights/status").json()
        _idle()
        second = client.get("/api/insights/status").json()
    for key in ("index_counts_state", "pending", "pending_since", "as_of", "cache_age_s", "verified_current"):
        assert key in first, key
    assert first["index_counts_state"] == "computing" and first["remaining"] is None
    assert second["index_counts_state"] == "counted" and isinstance(second["remaining"], int)
    assert second["index_counts_recount_after_s"] is not None and second["index_counts_computed_at"]


def test_the_header_paints_an_unknown_scan_as_unknown_under_node():
    import subprocess
    from pathlib import Path

    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "insights_status_pending_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_word_the_header_uses_for_an_unknown_scan_is_already_keyed_in_all_twelve_locales():
    """No new chrome string: the Library tile's keys are reused, so the gate for locales stays at 100 %."""
    import json
    import re
    from pathlib import Path

    locales = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in (Path(__file__).resolve().parent.parent / "src" / "static" / "locales").glob("*.json")}
    assert len(locales) == 12
    keys = [
        "counting…", "not counted",
        "Counting every keyword mention in the background since {t}; the other figures are exact now.",
        "passed its {s} s limit", "stopped because the machine was nearly out of memory",
        "Not counted: the keyword-mention count stopped ({why}) at {t}; it is tried again after {m} min.",
        "Counted at {t}; counting every keyword mention is slow, so it is repeated no more often than every {m} min.",
    ]
    for code, d in locales.items():
        for key in keys:
            assert key in d, f"{code}: {key!r}"
            assert sorted(re.findall(r"\{(\w+)\}", d[key])) == sorted(re.findall(r"\{(\w+)\}", key)), (code, key)


def test_the_background_top_up_does_not_wait_for_a_count_that_may_take_minutes():
    """Opus read finding 3. ``null > 0`` is false, so with the counts unknown (computing, or failed) the legacy-backlog top-up never
    started; it decides from the indexer's own ``never_attempted`` and needs no scan."""
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "src" / "static" / "app-insights.js").read_text(encoding="utf-8")
    assert "(s.remaining == null || s.remaining > 0) && !_indexing) autoIndexInsights()" in js
    assert "s.remaining > 0 && !_indexing" not in js
