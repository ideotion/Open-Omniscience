"""Row 465 (the field report's Q3, Q8 and Q11): what a feed's last passes did, and how far apart one host's requests were.

``feed_fetch_state.recent_outcomes`` keeps, per feed, the last ``OUTCOME_PASSES`` checked passes as counts only (how the feed
answered, how its entries ended); source-samples sums it per row and per class. ``spacing_stats`` measures the politeness the
fetcher actually applied, per pass, into ``collect_perf``'s summary. No network: every fetcher here is stubbed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from src.database.models import FeedFetchState, Source
from src.database.session import SessionLocal, init_db
from src.ingest import FetchError, FetchResult, RobotsDisallowed, outcome_history, spacing_stats
from src.ingest import pipeline as P
from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL
from src.ingest.outcome_history import ENTRY_OUTCOMES, FEED_OUTCOMES, OUTCOME_PASSES

# ---------------------------------------------------------------- the counter itself


def _pass(feed: str, **counts: int) -> list[int]:
    return [FEED_OUTCOMES.index(feed), *(counts.get(k, 0) for k in ENTRY_OUTCOMES)]


def test_the_window_keeps_the_newest_passes_only():
    raw = None
    for i in range(OUTCOME_PASSES + 3):
        raw = outcome_history.appended(raw, "read", outcome_history.entry_counts({"stored": i}))
    passes = outcome_history.parse(raw)
    assert len(passes) == OUTCOME_PASSES
    assert [p[1] for p in passes] == list(range(3, OUTCOME_PASSES + 3)), "oldest first, the first three dropped"


@pytest.mark.parametrize("raw", [
    "", "x", "{}", "[1]", "[[99" + ",0" * len(ENTRY_OUTCOMES) + "]]", "[[0" + ",-1" * len(ENTRY_OUTCOMES) + "]]",
    "[[0" + ",true" * len(ENTRY_OUTCOMES) + "]]", "[[0,1]]", json.dumps([_pass("read")] * (OUTCOME_PASSES + 1)),
    "[" + "0," * 2000 + "0]", 42, None,
])
def test_a_value_this_version_did_not_write_is_unreadable_never_zero(raw):
    assert outcome_history.parse(raw) is None
    assert outcome_history.summary(raw) is None and outcome_history.main_outcome(raw) is None
    again = outcome_history.parse(outcome_history.appended(raw, "not_modified"))
    assert again == [_pass("not_modified")], "an unreadable value starts again empty"


def test_entry_counts_read_the_tally_s_reasons():
    tally = {"stored": 2, "duplicate": 3, "non_article": 1, "extract_failed": 1, "fetch_failed": 6, "ff:http_403": 2,
             "ff:http_4xx": 1, "ff:http_5xx": 1, "ff:offline": 1, "ff:dns": 1, "blocked_robots": 1, "robots_unavailable": 1,
             "stopped_unwalked": 4, "crawl_delay_deferred": 2, "errors": 1, "entries": 99}
    got = dict(zip(ENTRY_OUTCOMES, outcome_history.entry_counts(tally), strict=True))
    assert got == {"stored": 2, "duplicate": 3, "non_article": 1, "extract_failed": 1, "http_4xx": 3, "http_5xx": 1,
                   "http_none": 1, "robots": 2, "deferred": 2, "store_error": 1}


def test_summary_and_main_outcome():
    raw = outcome_history.appended(None, "read", outcome_history.entry_counts({"duplicate": 5, "stored": 1}))
    raw = outcome_history.appended(raw, "http_5xx")
    cols = outcome_history.summary_columns()
    s = dict(zip(cols, outcome_history.summary(raw), strict=True))
    assert s["passes"] == 2 and s["feed_read"] == 1 and s["feed_http_5xx"] == 1 and s["duplicate"] == 5 and s["stored"] == 1
    assert outcome_history.main_outcome(raw) == "duplicate"
    assert outcome_history.main_outcome(outcome_history.appended(None, "robots")) == "feed:robots"


def test_the_stored_text_stays_small():
    raw = None
    for _ in range(OUTCOME_PASSES):
        raw = outcome_history.appended(raw, "read", [99_999_999] * len(ENTRY_OUTCOMES))
    assert len(raw) <= outcome_history.MAX_TEXT and outcome_history.parse(raw) is not None


# ---------------------------------------------------------------- what the pipeline records

_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>a</title><link>https://feed.example/a</link></item>
<item><title>b</title><link>https://feed.example/b</link></item>
</channel></rss>"""


def _result(status: int, content: str = _RSS) -> FetchResult:
    return FetchResult(requested_url="https://feed.example/rss", final_url="https://feed.example/rss", status_code=status,
                       content=content if status == 200 else "", content_type="application/rss+xml",
                       fetched_at=datetime.now(UTC))


class _Script:
    def __init__(self, script):
        self._script = list(script)

    def fetch(self, url, *a, **k):
        step = self._script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


@pytest.fixture()
def db():
    init_db()
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _source(db) -> Source:
    src = Source(name=f"F {uuid.uuid4().hex[:6]}", domain=f"f-{uuid.uuid4().hex[:6]}.example",
                 rss_url="https://feed.example/rss", language="en", enabled=True, status="qualified")
    db.add(src)
    db.commit()
    return src


def _passes(db, src) -> list[list[int]] | None:
    db.expire_all()
    st = db.get(FeedFetchState, src.id)
    return None if st is None else outcome_history.parse(st.recent_outcomes)


def test_a_read_feed_records_how_its_entries_ended(db):
    src = _source(db)
    P.ingest_source(db, src, fetcher=_Script([_result(200), FetchError("HTTP 404 for https://feed.example/a"),
                                              FetchError("connection failed: reset")]))
    db.commit()
    (p,) = _passes(db, src)
    got = dict(zip(ENTRY_OUTCOMES, p[1:], strict=True))
    assert FEED_OUTCOMES[p[0]] == "read" and got["http_4xx"] == 1 and got["http_none"] == 1 and got["stored"] == 0, got


def test_a_304_a_failed_feed_and_a_robots_refusal_are_passes(db):
    src = _source(db)
    P.ingest_source(db, src, fetcher=_Script([_result(304)]))
    db.commit()
    P.ingest_source(db, src, fetcher=_Script([FetchError("HTTP 503 for https://feed.example/rss")]))
    db.commit()
    P.ingest_source(db, src, fetcher=_Script([RobotsDisallowed("robots.txt disallows https://feed.example/rss")]))
    db.commit()
    assert [FEED_OUTCOMES[p[0]] for p in _passes(db, src)] == ["not_modified", "http_5xx", "robots"]


def test_a_feed_the_kill_switch_refused_was_not_asked_and_is_not_a_pass(db):
    src = _source(db)
    P.ingest_source(db, src, fetcher=_Script([_result(304)]))
    db.commit()
    P.ingest_source(db, src, fetcher=_Script([FetchError(f"{KILL_SWITCH_REFUSAL}: https://feed.example/rss")]))
    db.commit()
    assert [FEED_OUTCOMES[p[0]] for p in _passes(db, src)] == ["not_modified"]


def test_the_export_carries_no_address_or_text(db):
    src = _source(db)
    P.ingest_source(db, src, fetcher=_Script([_result(200), FetchError("HTTP 404 for https://feed.example/a"),
                                              FetchError("HTTP 410 for https://feed.example/b")]))
    db.commit()
    db.expire_all()
    raw = db.get(FeedFetchState, src.id).recent_outcomes
    assert "feed.example" not in raw and "HTTP" not in raw and set(raw) <= set("[],0123456789")


# ---------------------------------------------------------------- the spacing actually applied


def test_spacing_counts_gaps_per_host_and_never_names_one():
    spacing_stats.reset()
    spacing_stats.record("a.example", gap_s=None, waited_s=0.0, interval_s=1.0)
    spacing_stats.record("a.example", gap_s=1.5, waited_s=0.4, interval_s=1.0)
    spacing_stats.record("a.example", gap_s=40.0, waited_s=0.0, interval_s=1.0)
    spacing_stats.record("b.example", gap_s=None, waited_s=0.0, interval_s=1.0)
    spacing_stats.record("b.example", gap_s=0.2, waited_s=0.0, interval_s=1.0)
    spacing_stats.record_deferred()
    snap = spacing_stats.snapshot()
    assert snap["requests"] == 5 and snap["first_contact"] == 2 and snap["hosts_with_a_gap"] == 2
    bins = dict(zip(snap["bins_s"], snap["gaps"], strict=True))
    assert bins["<1"] == 1 and bins["1-2"] == 1 and bins["30-60"] == 1 and sum(snap["gaps"]) == 3
    per_host = dict(zip(snap["bins_s"], snap["host_min_gap"], strict=True))
    assert per_host["<1"] == 1 and per_host["1-2"] == 1 and sum(snap["host_min_gap"]) == 2
    assert snap["below_interval"] == 1 and snap["deferred"] == 1 and snap["waited"] == 1 and snap["wait_max_s"] == 0.4
    assert "example" not in json.dumps(snap)
    spacing_stats.reset()
    assert spacing_stats.snapshot()["requests"] == 0


def test_the_fetcher_records_the_spacing_it_let_through(monkeypatch):
    from src.ingest import EthicalFetcher

    clock = [100.0]
    f = EthicalFetcher.__new__(EthicalFetcher)
    monkeypatch.setattr(f, "_now", lambda: clock[0], raising=False)
    spacing_stats.reset()
    f._note_spacing("h.example", None, 0.0, 1.0)
    f._note_spacing("h.example", 97.5, 0.0, 1.0)
    snap = spacing_stats.snapshot()
    assert snap["first_contact"] == 1 and dict(zip(snap["bins_s"], snap["gaps"], strict=True))["2-5"] == 1


def test_the_rate_limiter_records_the_gap_after_its_wait_and_a_deferral(tmp_path):
    """Through ``_respect_rate_limit`` itself: the gap is read after the politeness sleep, on the fetcher's own clock."""
    from src.ingest import CrawlDelayDeferred, EthicalFetcher
    from tests.test_crawl_delay_deferral import _fetcher

    clock = [1000.0]
    f = EthicalFetcher(robots_cache_path=tmp_path / "robots_cache.json")
    f._now = lambda: clock[0]
    f._sleep = lambda s: clock.__setitem__(0, clock[0] + s)
    spacing_stats.reset()
    f._respect_rate_limit("h.example", "https://h.example")      # first contact
    f._last_request["h.example"] = clock[0]                       # the request ends now
    clock[0] += 0.25
    f._respect_rate_limit("h.example", "https://h.example")      # waits the rest of the 1 s interval
    snap = spacing_stats.snapshot()
    assert snap["requests"] == 2 and snap["first_contact"] == 1 and snap["waited"] == 1 and snap["below_interval"] == 0
    assert dict(zip(snap["bins_s"], snap["gaps"], strict=True))["1-2"] == 1, "the gap includes the wait it slept"

    slow = _fetcher(tmp_path, delay=3600)
    slow._sleep = lambda _s: None
    slow._respect_rate_limit("slow.example", "https://slow.example")
    slow._last_request["slow.example"] = slow._now()
    with pytest.raises(CrawlDelayDeferred):
        slow._respect_rate_limit("slow.example", "https://slow.example")
    assert spacing_stats.snapshot()["deferred"] == 1


def test_a_host_past_the_cap_is_counted_not_held(monkeypatch):
    monkeypatch.setattr(spacing_stats, "HOST_CAP", 2)
    spacing_stats.reset()
    for h in ("a", "b", "c"):
        spacing_stats.record(h, gap_s=5.0, waited_s=0.0, interval_s=1.0)
    snap = spacing_stats.snapshot()
    assert snap["hosts_with_a_gap"] == 2 and snap["gaps_untracked"] == 1 and sum(snap["gaps"]) == 3


def test_a_crawl_delay_deferred_feed_is_not_a_pass(db):
    from src.ingest import CrawlDelayDeferred

    src = _source(db)
    P.ingest_source(db, src, fetcher=_Script([CrawlDelayDeferred("Crawl-delay 3600 s: not before later", netloc="feed.example",
                                                                 delay_s=3600.0, not_before=0.0)]))
    db.commit()
    assert _passes(db, src) is None, "no request was sent (Q1013 = a): nothing recorded, no row created"


def test_a_broken_statistic_never_changes_a_fetch(monkeypatch):
    from src.ingest import EthicalFetcher

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(spacing_stats, "record", boom)
    monkeypatch.setattr(spacing_stats, "record_deferred", boom)
    f = EthicalFetcher.__new__(EthicalFetcher)
    f._note_spacing("h.example", None, 0.0, 1.0)
    EthicalFetcher._note_deferred()


def test_the_pass_summary_carries_the_spacing_block(tmp_path, monkeypatch):
    from src.monitoring import collect_perf
    from src.monitoring.collect_perf import recent_samples
    from src.scheduler.bandwidth import BandwidthGovernor
    from tests.test_collect_perf_monitor import _HEALTHY_VITALS, _IDLE_WRITER, _monitor

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    collect_perf._set_latest(None)
    mon = _monitor(governor=BandwidthGovernor(mode="maximum", w_max=4), rate=300.0, vitals=_HEALTHY_VITALS,
                   writer=_IDLE_WRITER)
    mon._tick()
    spacing_stats.reset()
    spacing_stats.record("h.example", gap_s=None, waited_s=0.0, interval_s=1.0)
    spacing_stats.record("h.example", gap_s=3.0, waited_s=2.0, interval_s=1.0)
    mon._write_summary({"articles_stored": 0, "sources_processed": 1, "pages_fetched": 2})
    (row,) = [r for r in recent_samples(50) if r.get("kind") == "summary"]
    block = row["host_spacing"]
    assert block["requests"] == 2 and block["first_contact"] == 1 and "h.example" not in json.dumps(row)
