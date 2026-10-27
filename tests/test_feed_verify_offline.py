"""Feed verification in airplane mode checks NOTHING and says so (invariant #14e's corollary; coordinator ruling R296, a clear defect found by
the read of ``tests/test_consent_coverage.py``).

Before, ``verify_feed`` read the kill switch's refusal as the HOST being unreachable: it stored an ``unreachable`` verdict, recorded a ladder
attempt (a healthy feed then waited a month per rung), the batch endpoint skipped it for good (it selects feeds with NO verdict), and the
"Check" button toasted a green "Checked.". Now a refusal by the kill switch returns ``{"status": "skipped_offline"}`` and records nothing, so the
feed stays exactly as eligible as it was; every other failure keeps its old behaviour. The tests run the REAL refusal (kill switch engaged, a
transport that fails the test if a socket is reached), then pin the other direction: an ordinary failure still stores ``unreachable``.

The JS half (``feedAction``) is driven in ``feed_verify_offline_node_test.js``; this file is its pytest driver.
"""

from __future__ import annotations

import contextlib
import pathlib
import subprocess

import pytest

from src.events import feeds as F
from src.ingest import (
    EthicalFetcher,
    FetchFailed,
    activate_kill_switch,
    clear_kill_switch,
    kill_switch_active,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FEED = "wph-hol-ad"
_H = {"Sec-Fetch-Site": "same-origin", "Referer": "http://127.0.0.1/", "Origin": "http://127.0.0.1"}


class _NoSocket:
    def get(self, *a, **kw):
        raise AssertionError("a socket was reached while the kill switch was engaged")

    head = post = request = get

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


@contextlib.contextmanager
def airplane_mode():
    was = kill_switch_active()
    activate_kill_switch()
    try:
        yield
    finally:
        (activate_kill_switch if was else clear_kill_switch)()


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def _fetcher() -> EthicalFetcher:
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_NoSocket())


class _Failing:
    def fetch(self, url, **_kw):
        raise FetchFailed("HTTP 503 for " + url)


def test_a_refusal_by_the_kill_switch_records_no_verdict_and_no_attempt():
    with airplane_mode():
        out = F.verify_feed(_fetcher(), _FEED)
    assert out["status"] == "skipped_offline" and "kill switch" in out["error"]
    assert F.load_verdicts() == {}, "no verdict about a host nobody asked"
    assert F.load_attempts() == {}, (
        "no ladder attempt: the feed must not wait a month for the person's own setting"
    )


def test_the_refused_feed_is_still_first_in_line():
    ids = [f["id"] for fam in F.load_families() for f in fam["feeds"]]
    with airplane_mode():
        F.verify_feed(_fetcher(), _FEED)
    picked = F.select_feeds_to_verify(
        ids, F.load_attempts(), now=F.datetime.now(F.UTC), limit=len(ids)
    )
    assert picked == ids, (
        "the whole directory is still unchecked, in catalogue order, the refused feed included"
    )


def test_an_ordinary_failure_still_stores_unreachable_and_an_attempt():
    out = F.verify_feed(_Failing(), _FEED)
    assert out["status"] == "unreachable" and "503" in out["error"]
    assert F.load_verdicts()[_FEED]["status"] == "unreachable"
    assert F.load_attempts()[_FEED][-1]["status"] == "unreachable"


def test_the_phrase_inside_a_real_failure_is_still_that_feeds_failure():
    """Control: a server's own words that happen to contain the kill switch's sentence are NOT the person's airplane mode."""

    class _Quotes:
        def fetch(self, url, **_kw):
            raise FetchFailed(
                "HTTP 503 for " + url + " (server said: network kill switch is active)"
            )

    out = F.verify_feed(_Quotes(), _FEED)
    assert out["status"] == "unreachable"
    assert F.load_verdicts()[_FEED]["status"] == "unreachable" and F.load_attempts()[_FEED]


def test_the_progressive_verifier_counts_refusals_apart_and_records_nothing():
    with airplane_mode():
        out = F.verify_due_feeds(_fetcher(), batch=3)
    assert (
        out["skipped_offline"] == 3
        and out["checked"] == 0
        and out["ok"] == 0
        and out["failed"] == 0
    )
    assert F.load_attempts() == {} and F.load_verdicts() == {}
    quiet = F.verify_due_feeds(_Failing(), batch=2)
    assert "skipped_offline" not in quiet and quiet["failed"] == 2 and quiet["checked"] == 2, (
        "absent unless the kill switch caused it"
    )


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_the_single_endpoint_names_the_refusal_at_the_top_level(client):
    with airplane_mode():
        body = client.post(f"/api/events/feeds/{_FEED}/verify", headers=_H).json()
    assert body["skipped_offline"] == 1 and body["verdict"]["status"] == "skipped_offline"
    assert F.load_verdicts() == {} and F.load_attempts() == {}


def test_the_batch_endpoint_counts_refusals_and_leaves_every_feed_unchecked(client):
    total = sum(len(f["feeds"]) for f in F.load_families())
    with airplane_mode():
        body = client.post("/api/events/feeds/verify-batch?limit=4", headers=_H).json()
    assert (
        body["skipped_offline"] == 4
        and body["checked"] == 0
        and body["ok"] == 0
        and body["verdicts"] == {}
    )
    assert body["remaining_unchecked"] == total, "nothing was checked, so nothing left the backlog"
    assert F.load_verdicts() == {}
    with airplane_mode():
        again = client.post("/api/events/feeds/verify-batch?limit=4", headers=_H).json()
    assert again["skipped_offline"] == 4, (
        "the same four feeds are picked again: a refusal never moves a feed out of the backlog"
    )


def test_the_check_button_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "feed_verify_offline_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "feed_verify_offline_node_test.js: OK" in proc.stdout


def test_the_socket_guards_refusal_as_requests_really_wraps_it_is_recognised_whole(monkeypatch):
    """Drift pin (found by the read of this change): the text is built by the REAL ``AirplaneModeError`` through REAL requests/urllib3, for a
    realistic directory URL, so it is longer than the 300 characters a record keeps. Classifying the cut text read it as a host failure."""
    import requests
    import urllib3.util.connection as uc

    from src.ingest.airplane import AirplaneModeError

    def refuse(*_a, **_k):
        raise AirplaneModeError(
            "airplane mode is engaged: refusing a network connection to 'worldpublicholiday.com'. No packet leaves the machine while offline"
        )

    monkeypatch.setattr(uc, "create_connection", refuse)
    url = F.feed_by_id(_FEED)[1]["url"]
    with pytest.raises(requests.RequestException) as caught:
        requests.get(url, timeout=2)
    wrapped = f"request error for {url}: {caught.value}"
    assert len(wrapped) > 300  # the premise: a cut at 300 would lose the sentence

    class _Wrapped:
        def fetch(self, _url, **_kw):
            raise FetchFailed(wrapped)

    out = F.verify_feed(_Wrapped(), _FEED)
    assert out["status"] == "skipped_offline"
    assert len(out["error"]) <= 300
    assert F.load_verdicts() == {} and F.load_attempts() == {}
