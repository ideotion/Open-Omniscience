"""The preflight in airplane mode checks NOTHING, changes NOTHING and says so (invariant #14e's corollary; coordinator ruling R313, G1).

Before, ``preflight_sources`` read the kill switch's refusal as every SOURCE being unreachable: it recorded each one as ``unreachable``, OVERWROTE the
source's learned ``robots_allowed`` with NULL (a previously learned allow or deny erased by the person's own airplane mode), appended the verdicts to
``source_preflight.jsonl`` (the file ``has_run_before()`` reads, so the first-run preflight counted as DONE and never went back) and answered with
the domains under ``unreachable``. ``run_feed_preflight`` did the same with ``feed_preflight.jsonl``. Now a refusal by the kill switch stops the sweep
as ``complete: False`` with ``skipped_offline`` (present only then), writes no log, edits no metadata, and the first-run job's ``pending()`` stays
true. Every other failure keeps its old behaviour; the tests pin that too, including a REMOTE party's text that merely contains the sentence.

The tests run the REAL refusal: the kill switch engaged over a real ``EthicalFetcher`` (a real session: the SSRF guard resolves the target first and
is what meets the kill switch; no request is ever sent).
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any, cast

import pytest

from src.database.models import Source, SourceMetadata
from src.database.session import SessionLocal, init_db
from src.ingest import (
    EthicalFetcher,
    activate_kill_switch,
    clear_kill_switch,
    kill_switch_active,
)
from src.monitoring import feed_preflight, preflight


@contextlib.contextmanager
def airplane_mode():
    was = kill_switch_active()
    activate_kill_switch()
    try:
        yield
    finally:
        (activate_kill_switch if was else clear_kill_switch)()


@pytest.fixture(autouse=True)
def _isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "_log_path", lambda: tmp_path / "source_preflight.jsonl")
    monkeypatch.setattr(feed_preflight, "_log_path", lambda: tmp_path / "feed_preflight.jsonl")
    return tmp_path


def _fetcher() -> EthicalFetcher:
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0)


@pytest.fixture()
def db():
    """The shared hermetic store, with every other source disabled for the test and NOTHING committed."""
    init_db()
    session = SessionLocal()
    session.query(Source).update({Source.enabled: False})
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _mk(session, learned: bool | None = None) -> Source:
    src = Source(name="Offline probe", domain=f"probe-{uuid.uuid4().hex[:8]}.example", language="en", enabled=True)
    session.add(src)
    session.flush()
    if learned is not None:
        session.add(SourceMetadata(source_id=src.id, robots_allowed=learned))
        session.flush()
    return src


def test_a_refusal_by_the_kill_switch_marks_nothing_unreachable_writes_no_log_and_keeps_the_learned_robots(db):
    src = _mk(db, learned=False)
    with airplane_mode():
        summary = preflight.preflight_sources(db, _fetcher(), limit=5)
    assert summary["complete"] is False
    assert summary["skipped_offline"] == 1
    assert "kill switch" in summary["stopped"] and "airplane mode" in summary["stopped"]
    assert "unreachable" not in summary and "log" not in summary
    assert not preflight.has_run_before(), "an offline sweep must not stamp the first-run preflight as done"
    meta = db.query(SourceMetadata).filter_by(source_id=src.id).one()
    assert meta.robots_allowed is False, "the learned robots verdict was overwritten by the refusal"


def test_the_record_of_a_refused_source_is_skipped_offline_not_unreachable(db):
    src = _mk(db)
    with airplane_mode():
        rec = preflight._check_one(_fetcher(), src)
    assert rec["verdict"] == "skipped_offline" and rec["skipped_offline"] is True
    assert rec["reachable"] is None and rec["robots"] == "skipped_offline"


class _Refusing:
    """A fetcher whose guard raises what the network does when it cannot be reached: an ordinary failure, not our refusal."""

    user_agent = "OpenOmniscienceBot/test"
    session = None
    timeout = 5

    def __init__(self, message: str) -> None:
        self._message = message

    def _guard_target(self, host):
        raise OSError(self._message)

    _guarded_redirect_get = _guard_target


@pytest.mark.parametrize(
    "message",
    [
        "Name or service not known",
        # a REMOTE party's text that contains our sentence is not our refusal (R298: anchored to the start)
        "HTTP 502 from upstream: network kill switch is active -- collection stopped by operator",
    ],
)
def test_an_ordinary_failure_is_still_unreachable_and_still_logged(db, message):
    src = _mk(db, learned=True)
    summary = preflight.preflight_sources(db, _Refusing(message), limit=5)
    assert summary["complete"] is True and "skipped_offline" not in summary
    assert summary["unreachable"] == [src.domain]
    assert preflight.has_run_before()
    assert db.query(SourceMetadata).filter_by(source_id=src.id).one().robots_allowed is None


def test_the_feed_preflight_stops_on_the_refusal_and_logs_nothing():
    with airplane_mode():
        summary = feed_preflight.run_feed_preflight(_fetcher())
    assert summary["complete"] is False and summary["skipped_offline"] >= 1
    assert "kill switch" in summary["stopped"]
    assert not feed_preflight.has_run_before()
    assert "robots_denied" not in summary and "log" not in summary


def test_an_offline_first_run_job_leaves_the_preflight_pending(monkeypatch):
    """The headline: neither half stamps, so the next ONLINE pass still runs the first-run preflight. (The job reads through its OWN
    session, so the source it must meet is committed and removed again.)"""
    from src.database.session import session_scope
    from src.monitoring import preflight_job

    monkeypatch.setattr("src.events.feeds.verify_feed", lambda *_a, **_k: {"status": "skipped_offline"})
    init_db()
    with session_scope() as s:
        src = Source(name="Offline job probe", domain=f"job-{uuid.uuid4().hex[:8]}.example", language="en", enabled=True)
        s.add(src)
        s.flush()
        sid = src.id
    try:
        assert preflight_job.pending()

        class _Ctx:
            stopping = False

            def set_progress(self, **_kw):
                return None

        with airplane_mode():
            out = preflight_job._worker(cast(Any, _Ctx()), fetcher=_fetcher())
        assert out["sources"]["complete"] is False and out["sources"]["skipped_offline"] >= 1
        assert out["feeds"]["complete"] is False
        assert preflight_job.pending(), "the offline run stamped the first-run preflight as done"
    finally:
        with session_scope() as s:
            s.query(Source).filter_by(id=sid).delete()


def test_kick_declines_while_the_kill_switch_is_engaged(monkeypatch):
    """The entry point is gated too: no job is started to ask nobody (a declined kick logs nothing, so the next online pass runs it)."""
    from src.monitoring import preflight_job

    started: list[object] = []
    monkeypatch.setattr(preflight_job, "pending", lambda: True)
    monkeypatch.setattr(preflight_job.PREFLIGHT_JOB, "start", lambda **kw: started.append(kw))
    with airplane_mode():
        assert preflight_job.kick() is None
    assert started == []
    clear_kill_switch()
    preflight_job.kick()
    assert started, "kick must still start the job when the switch is clear"


# --- a Stop that lands DURING the last request (Export's read of #1570) -------------------------------------------------


_RAW_CUT = (
    "HTTPSConnectionPool(host='{host}', port=443): Max retries exceeded with url: /{path} (Caused by NewConnectionError("
    "'<urllib3.connection.HTTPSConnection object at 0x7f0>: Failed to establish a new connection: airplane mode is engaged: "
    "refusing a network connection to '{host}'.'))"
)


class _Resp:
    def __init__(self, status_code: int = 200, text: str = "User-agent: *\nAllow: /") -> None:
        self.status_code = status_code
        self.text = text


class _CutOnLast:
    """A fetcher whose LAST request dies the way a Stop does: the socket guard cuts it and ``requests`` raises its own error, which
    ``_guarded_redirect_get`` (not wrapped by the fetcher, unlike ``fetch()``) passes up raw and which begins ``HTTPSConnectionPool(``
    -- not our sentence, so the anchored match rightly refuses it. ``engage`` says whether the switch is engaged at that moment."""

    user_agent = "OpenOmniscienceBot/test"
    session = None
    timeout = 5

    def __init__(self, last_url: str, engage: bool) -> None:
        self._last = last_url
        self._engage = engage

    def _guard_target(self, host):
        return None

    def fetch(self, url, **_kw):
        """The market-sample path goes through ``fetch()``; the cut lands on the url named as the last one."""
        return self._guarded_redirect_get(url) and type("R", (), {"content": "x"})()

    def _guarded_redirect_get(self, url, **_kw):
        if url == self._last:
            import requests

            if self._engage:
                activate_kill_switch()
            host = url.split("/")[2]
            raise requests.ConnectionError(_RAW_CUT.format(host=host, path=url.split("/", 3)[3]))
        return _Resp(), url


def test_a_stop_that_cuts_the_last_request_of_the_source_half_is_not_a_finished_sweep(db):
    """THE EXACT CUT: the homepage ping of the final source. Before the per-check switch read this ended ``complete: True``, wrote a
    one-record log and set ``has_run_before()``."""
    src = _mk(db, learned=True)
    fetcher = _CutOnLast(f"https://{src.domain}/", engage=True)
    try:
        summary = preflight.preflight_sources(db, fetcher, limit=5)
    finally:
        clear_kill_switch()
    assert summary["complete"] is False and summary["skipped_offline"] == 1
    assert not preflight.has_run_before(), "a sweep cut by the switch stamped the first-run preflight as done"
    assert db.query(SourceMetadata).filter_by(source_id=src.id).one().robots_allowed is True


def test_the_same_raw_error_with_the_switch_clear_is_still_the_hosts_failure(db):
    """The boundary: without an engaged switch the raw requests error is an ordinary failure, filed and logged as before."""
    src = _mk(db, learned=True)
    summary = preflight.preflight_sources(db, _CutOnLast(f"https://{src.domain}/", engage=False), limit=5)
    assert summary["complete"] is True and "skipped_offline" not in summary
    assert preflight.has_run_before()


def test_a_stop_that_cuts_the_last_feed_host_leaves_the_feed_preflight_pending():
    hosts = sorted({t["host"] for t in sum(feed_preflight._feed_targets(), []) if t["host"]})
    fetcher = _CutOnLast(f"https://{hosts[-1]}/robots.txt", engage=True)
    try:
        summary = feed_preflight.run_feed_preflight(fetcher)
    finally:
        clear_kill_switch()
    assert summary["complete"] is False and summary["skipped_offline"] >= 1
    assert not feed_preflight.has_run_before()


def test_a_stop_that_cuts_the_robots_read_is_not_filed_as_the_hosts_verdict(db):
    """The robots-read guard on its own: the cut lands on robots.txt, and a homepage that would still answer must not rescue the record."""
    src = _mk(db, learned=True)
    try:
        summary = preflight.preflight_sources(db, _CutOnLast(f"https://{src.domain}/robots.txt", engage=True), limit=5)
    finally:
        clear_kill_switch()
    assert summary["complete"] is False and not preflight.has_run_before()


def _feed_fetcher_and_stub(monkeypatch, *, calendar_status: str, market_cut: bool, engage_on_calendar: bool = False):
    """Every robots read answers; the calendar sample answers ``calendar_status``; the market sample is cut when ``market_cut``."""
    market = [t for t in feed_preflight._feed_targets()[0] if t["host"]]
    fetcher = _CutOnLast(market[0]["url"] if market_cut else "never", engage=True)

    def _verify(_fetcher, _key):
        if engage_on_calendar:
            activate_kill_switch()
        return {"status": calendar_status}

    monkeypatch.setattr("src.events.feeds.verify_feed", _verify)
    return fetcher


def _distinct_hosts(targets):
    return len({t["host"] for t in targets if t["host"]})


def test_the_calendar_sample_stops_on_a_skipped_offline_verdict_and_counts_what_was_not_asked(monkeypatch):
    fetcher = _feed_fetcher_and_stub(monkeypatch, calendar_status="skipped_offline", market_cut=False)
    market, calendar = feed_preflight._feed_targets()
    summary = feed_preflight.run_feed_preflight(fetcher, sample_per_provider=1)  # one sampled feed per host: the count is known
    # cut at the FIRST calendar feed: every sampled calendar feed and every sampled market feed was not asked
    assert summary["complete"] is False
    assert summary["skipped_offline"] == _distinct_hosts(calendar) + _distinct_hosts(market)
    assert not feed_preflight.has_run_before()


def test_a_completed_calendar_answer_is_kept_even_if_the_stop_lands_right_after_it(monkeypatch):
    """Only a FAILED check is read as the switch's: a feed that really answered ``not_ical`` is saved by verify_feed and must not be
    discarded by the preflight as if nothing had been asked."""
    fetcher = _feed_fetcher_and_stub(monkeypatch, calendar_status="not_ical", market_cut=False, engage_on_calendar=True)
    try:
        summary = feed_preflight.run_feed_preflight(fetcher)
    finally:
        clear_kill_switch()
    assert summary["complete"] is True and feed_preflight.has_run_before()


def test_the_calendar_sample_discards_a_failure_that_coincides_with_a_stop(monkeypatch):
    fetcher = _feed_fetcher_and_stub(monkeypatch, calendar_status="unreachable", market_cut=False, engage_on_calendar=True)
    try:
        summary = feed_preflight.run_feed_preflight(fetcher)
    finally:
        clear_kill_switch()
    assert summary["complete"] is False and not feed_preflight.has_run_before()


def test_the_calendar_sample_keeps_an_ordinary_failure_when_the_switch_is_clear(monkeypatch):
    fetcher = _feed_fetcher_and_stub(monkeypatch, calendar_status="unreachable", market_cut=False)
    summary = feed_preflight.run_feed_preflight(fetcher)
    assert summary["complete"] is True and feed_preflight.has_run_before()


def _picked(targets, cap=3):
    """The feeds the sample takes with every robots read answering: the first ``cap`` per host, in catalogue order."""
    per_host: dict[str, int] = {}
    out = []
    for t in targets:
        if per_host.get(t["host"], 0) < cap:
            per_host[t["host"]] = per_host.get(t["host"], 0) + 1
            out.append(t)
    return out


def test_the_market_sample_stops_when_a_stop_cuts_its_fetch(monkeypatch):
    """The cut lands on the SECOND sampled market feed, so the count (the cut feed and every one after it) differs from 1 and from the
    whole sample."""
    market, _calendar = feed_preflight._feed_targets()
    picked = _picked(market)
    assert len(picked) >= 3
    fetcher = _feed_fetcher_and_stub(monkeypatch, calendar_status="ok", market_cut=False)
    fetcher._last = picked[1]["url"]
    try:
        summary = feed_preflight.run_feed_preflight(fetcher)
    finally:
        clear_kill_switch()
    assert summary["complete"] is False and summary["skipped_offline"] == len(picked) - 1
    assert not feed_preflight.has_run_before()


# --- source A checked, source B refused: A's metadata must not survive on EITHER caller ---------------------------------


def _two_committed_sources():
    """Two committed sources ahead of everything else in the shared store (priority sorts first), each with a learned ``False``."""
    from src.database.session import session_scope

    init_db()
    ids: list[int] = []
    with session_scope() as s:
        for n, prio in (("a", -2000), ("b", -1999)):
            src = Source(
                name=f"Rollback {n}", domain=f"rollback-{n}-{uuid.uuid4().hex[:6]}.example", language="en", enabled=True, priority=prio
            )
            s.add(src)
            s.flush()
            s.add(SourceMetadata(source_id=src.id, robots_allowed=False))
            ids.append(src.id)
        domains = [s.get(Source, i).domain for i in ids]  # type: ignore[union-attr]
    return ids, domains


def _drop_sources(ids):
    from src.database.session import session_scope

    with session_scope() as s:
        s.query(SourceMetadata).filter(SourceMetadata.source_id.in_(ids)).delete(synchronize_session=False)
        s.query(Source).filter(Source.id.in_(ids)).delete(synchronize_session=False)


def _learned(ids):
    from src.database.session import session_scope

    with session_scope() as s:
        return [s.query(SourceMetadata).filter_by(source_id=i).one().robots_allowed for i in ids]


def test_the_first_run_job_rolls_back_source_a_when_source_b_is_refused(monkeypatch):
    from src.monitoring import preflight_job

    # the feed half runs after the source half: keep its verify_feed from saving calendar verdicts into the shared store
    monkeypatch.setattr("src.events.feeds.verify_feed", lambda *_a, **_k: {"status": "skipped_offline"})

    ids, domains = _two_committed_sources()

    class _Ctx:
        stopping = False

        def set_progress(self, **_kw):
            return None

    try:
        try:
            out = preflight_job._worker(cast(Any, _Ctx()), fetcher=_CutOnLast(f"https://{domains[1]}/robots.txt", engage=True))
        finally:
            clear_kill_switch()
        assert out["sources"]["complete"] is False
        assert _learned(ids) == [False, False], "source A's verdict (robots allow -> True) survived the refusal of source B"
        assert not preflight.has_run_before()
    finally:
        _drop_sources(ids)


def test_the_route_rolls_back_source_a_when_source_b_is_refused(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    ids, domains = _two_committed_sources()
    fetcher = _CutOnLast(f"https://{domains[1]}/robots.txt", engage=True)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda *a, **k: fetcher)
    headers = {"Sec-Fetch-Site": "same-origin", "Referer": "http://127.0.0.1/", "Origin": "http://127.0.0.1"}
    try:
        try:
            with TestClient(app, base_url="http://127.0.0.1") as c:
                r = c.post("/api/sources/preflight?limit=2", headers=headers)
        finally:
            clear_kill_switch()
        assert r.status_code == 200 and r.json()["complete"] is False
        assert _learned(ids) == [False, False], "the route committed source A's verdict although the sweep was refused"
    finally:
        _drop_sources(ids)
