"""A Stop is never a market feed's failure, in the background pass or in the import-all route (R377; the shape of R320 and of #1601).

``import_due_feeds`` (the scheduler's markets pass) and ``POST /api/markets/feeds/import-all`` ran every feed through ``import_feed`` and counted whatever came back that
was not "imported" as ``failed``. ``import_feed`` already classifies a failure under an engaged switch as the ``offline`` verdict (nothing was asked of the host), but the
two callers then counted that verdict as the feed's failure and walked every feed after it through a refusal as well, so one Stop became N failures in the tally and in
the per-feed results. A Stop inside a request arrives as the raw requests error (no sentence match recognises it, R298), so the decision reads the verdict ``import_feed``
reached after the failed check. The tests drive the REAL ``import_feed`` with a fetcher that engages the switch and fails as the transport does.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytest.importorskip("feedparser", reason="the markets pipeline imports the ingest pipeline (feedparser)")

from src.api import markets
from src.database.models import Base
from src.ingest import activate_kill_switch, clear_kill_switch
from src.markets import pipeline
from src.markets.feed_catalog import Feed

# The shape a Stop inside a proxied request really takes: requests' wrapper around the socket guard's error, nowhere near our refusal sentence at the start.
RAW_STOP = "request error for https://f.example/f3.csv: ('Connection aborted.', AirplaneModeError('network kill switch engaged'))"
CSV = "date,value\n2026-06-01,1.5\n2026-06-02,1.6\n"
TODAY = date(2026, 6, 17)
_REAL_SLEEP = _time.sleep  # captured at import, before any fixture can patch it


@dataclass
class _Result:
    content: str
    final_url: str = "https://f.example/x.csv"


class _Fetcher:
    """Answers the CSV; the ``stop_at``-th call engages the Stop and fails as the transport does (``fail`` is raised instead, with the switch engaged only when set)."""

    def __init__(self, *, stop_at: int | None = None, fail: Exception | None = None, stop_error: Exception | None = None):
        self.urls: list[str] = []
        self.stop_at = stop_at
        self.fail = fail
        self.stop_error = stop_error

    def fetch(self, url, *, require_html=True):
        self.urls.append(url)
        if self.stop_at is not None and len(self.urls) == self.stop_at:
            activate_kill_switch()
            raise self.stop_error or RuntimeError(RAW_STOP)
        if self.fail is not None:
            raise self.fail
        return _Result(content=CSV)


def _feeds(n: int = 5) -> list[Feed]:
    return [
        Feed(key=f"f{i}", name=f"F{i}", symbol=f"S{i}", category="metals", url=f"https://f.example/f{i}.csv", currency="USD", unit="t", market="m")
        for i in range(1, n + 1)
    ]


def _sess():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    import src.markets.csv_feeds as csv_feeds

    # the feed-level retry pause is not what these tests are about; scoped to csv_feeds' own name, never the shared ``time`` module (R376)
    monkeypatch.setattr(csv_feeds, "time", SimpleNamespace(sleep=lambda s: None))
    yield
    clear_kill_switch()


@pytest.fixture
def catalog(monkeypatch):
    feeds = _feeds()
    monkeypatch.setattr("src.markets.feed_catalog.load_feeds", lambda path=None: feeds)
    monkeypatch.setattr("src.markets.feed_catalog.load_index_feeds", lambda path=None: [])
    monkeypatch.setattr("src.markets.feed_catalog.feeds_for_category", lambda category=None: feeds)
    return feeds


# ---- the scheduler's markets pass -------------------------------------------------------------------------------------------------------------------------------


def test_pass_a_stop_inside_a_feed_ends_the_pass_and_is_no_failure(catalog):
    f = _Fetcher(stop_at=3)
    tally = pipeline.import_due_feeds(_sess(), fetcher=f, now=TODAY)
    assert len(f.urls) == 3, "the pass must end at the feed the Stop cut, not walk the other two through refusals"
    assert tally == {"checked": 2, "imported": 2, "fresh": 0, "failed": 0}, "the cut feed and the unasked ones are neither checked nor failed"


def test_pass_a_stop_engaged_before_the_pass_asks_no_feed(catalog):
    activate_kill_switch()
    f = _Fetcher()
    tally = pipeline.import_due_feeds(_sess(), fetcher=f, now=TODAY)
    assert f.urls == []
    assert tally == {"checked": 0, "imported": 0, "fresh": 0, "failed": 0}


def test_pass_an_ordinary_failure_is_still_counted_and_the_pass_goes_on(catalog):
    f = _Fetcher(fail=RuntimeError("blocked"))
    tally = pipeline.import_due_feeds(_sess(), fetcher=f, now=TODAY)
    assert len(f.urls) >= 5, "an ordinary failure never ends the pass"
    assert tally["failed"] == 5 and tally["imported"] == 0 and tally["checked"] == 5


def test_pass_the_hosts_own_answer_is_still_the_hosts_when_the_stop_lands_with_it(catalog):
    """A 404 is a status line the host really sent; a Stop cuts connections and cannot produce one. It stays that feed's failure, and the pass ends at the next look."""
    f = _Fetcher(stop_at=2, stop_error=RuntimeError("http 404 for https://f.example/f2.csv"))
    tally = pipeline.import_due_feeds(_sess(), fetcher=f, now=TODAY)
    assert len(f.urls) == 2
    assert tally == {"checked": 2, "imported": 1, "fresh": 0, "failed": 1}


def test_pass_a_stop_inside_the_only_feed_is_no_failure_by_the_except_branch_alone(monkeypatch, caplog):
    """The except branch: ``import_feed`` raising out of the loop body with the switch engaged (a store error) is the Stop's, so a one-feed pass ends there. The failure is
    still logged and the session still rolled back (a failed transaction must not reach the lane's next step); only the count and the failure tally are the Stop's."""
    one = _feeds(1)
    monkeypatch.setattr("src.markets.feed_catalog.load_feeds", lambda path=None: one)
    monkeypatch.setattr("src.markets.feed_catalog.load_index_feeds", lambda path=None: [])
    calls: list[str] = []

    def _raises(session, **kw):
        calls.append(kw["symbol"])
        activate_kill_switch()
        raise RuntimeError("store error")

    monkeypatch.setattr("src.markets.csv_feeds.import_feed", _raises)
    s = _sess()
    rolled: list[bool] = []
    real = s.rollback
    monkeypatch.setattr(s, "rollback", lambda: (rolled.append(True), real())[1])
    with caplog.at_level("WARNING"):
        tally = pipeline.import_due_feeds(s, fetcher=_Fetcher(), now=TODAY)
    assert calls == ["S1"]
    assert tally == {"checked": 0, "imported": 0, "fresh": 0, "failed": 0}
    assert rolled == [True], "the session is rolled back before the pass ends"
    assert "market feed f1 raised during a Stop" in caplog.text, "a real exception during a Stop is logged, and not labelled a failure"
    assert "import failed" not in caplog.text


# ---- the import-all route -----------------------------------------------------------------------------------------------------------------------------------


def _import_all(db, **kw):
    return markets.import_all_feeds(db=db, **kw)


@pytest.fixture
def route_fetcher(monkeypatch):
    holder: dict = {}
    monkeypatch.setattr(markets, "following_fetcher", lambda *a, **k: holder["f"])
    return holder


def test_route_a_stop_inside_a_feed_ends_the_batch_and_names_what_was_not_asked(catalog, route_fetcher):
    route_fetcher["f"] = f = _Fetcher(stop_at=3)
    out = _import_all(_sess())
    assert len(f.urls) == 3
    assert out["failed"] == 0, "a Stop is not the feed's failure"
    assert out["feeds"] == 2 and [r["key"] for r in out["results"]] == ["f1", "f2"], "only the completed checks are results"
    assert out["skipped_offline"] == 3, "the cut feed and the two after it: not asked, and the response says so"
    assert out["retryable_failed_keys"] == []


def test_route_a_stop_engaged_before_the_batch_asks_no_feed(catalog, route_fetcher):
    activate_kill_switch()
    route_fetcher["f"] = f = _Fetcher()
    out = _import_all(_sess())
    assert f.urls == []
    assert out["feeds"] == 0 and out["failed"] == 0 and out["results"] == []
    assert out["skipped_offline"] == 5


def test_route_an_ordinary_failure_is_counted_and_there_is_no_skipped_offline_key(catalog, route_fetcher):
    route_fetcher["f"] = f = _Fetcher(fail=RuntimeError("blocked"))
    out = _import_all(_sess())
    assert len(f.urls) >= 5
    assert out["failed"] == 5 and out["feeds"] == 5
    assert "skipped_offline" not in out, "present ONLY when the kill switch caused it (the verify_due_feeds idiom)"


def test_route_a_keys_restricted_batch_counts_only_the_feeds_it_was_asked_to_run(catalog, route_fetcher):
    route_fetcher["f"] = _Fetcher(stop_at=1)
    out = _import_all(_sess(), keys="f2,f4")
    assert out["skipped_offline"] == 2 and out["failed"] == 0 and out["feeds"] == 0


def test_route_the_hosts_own_answer_is_still_the_hosts_when_the_stop_lands_with_it(catalog, route_fetcher):
    """A 404 is a status line the host really sent; a Stop cuts connections and cannot produce one. It stays that feed's failure and result, and the batch ends at the next look."""
    route_fetcher["f"] = f = _Fetcher(stop_at=2, stop_error=RuntimeError("http 404 for https://f.example/f2.csv"))
    out = _import_all(_sess())
    assert len(f.urls) == 2
    assert out["failed"] == 1 and [r["key"] for r in out["results"]] == ["f1", "f2"]
    assert out["results"][1]["verdict"] == "dead-series"
    assert out["skipped_offline"] == 3, "the three after it were not asked"


def test_route_a_stop_inside_the_only_feed_is_no_failure_by_the_except_branch_alone(catalog, route_fetcher, monkeypatch, caplog):
    """The except branch: ``import_feed`` raising out of the loop body with the switch engaged (a store error) is the Stop's, so a one-feed batch ends there."""

    def _raises(session, **kw):
        activate_kill_switch()
        raise RuntimeError("store error")

    route_fetcher["f"] = _Fetcher()
    monkeypatch.setattr("src.markets.csv_feeds.import_feed", _raises)
    with caplog.at_level("WARNING"):
        out = _import_all(_sess(), keys="f1")
    assert out["failed"] == 0 and out["results"] == [] and out["skipped_offline"] == 1
    assert "market feed f1 raised during a Stop" in caplog.text, "the route logs it too, as the pass does"


def test_the_retry_pause_patch_is_scoped_to_csv_feeds_and_never_the_shared_time_module():
    """R376's class: a process-wide patch of a shared module is a defect in a test. The autouse fixture replaces the NAME ``time`` inside ``csv_feeds`` only; the real
    ``time.sleep`` every other module and thread reads stays the real one for the whole test."""
    import src.markets.csv_feeds as csv_feeds

    assert _time.sleep is _REAL_SLEEP, "the shared time module must not be patched"
    assert csv_feeds.time is not _time and csv_feeds.time.sleep(1.5) is None, "csv_feeds' own name is what carries the stub"
