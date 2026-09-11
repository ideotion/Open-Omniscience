"""``robots_unavailable`` was three different facts in one bucket. Now it names which.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

WHY THIS MATTERS ENOUGH TO PIN. The completed 2026-09-10 Stage A run put 7,847 of 22,045
candidates (35.6%) into ``robots_unavailable`` against 262 explicitly disallowed -- thirty to
one, at a uniform 25-53% across fourteen countries on every continent, and including hosts
that certainly do serve a robots.txt. That shape says most of the bucket is the PATH, not the
publisher. But the bucket held a refusal (401/403), a broken host (5xx) and a network failure
under one label, so none of it could be acted on -- including a decision to ban them, which
cannot be made honestly without knowing what is being banned.

FAIL-CLOSED IS UNCHANGED throughout: every case below still refuses the fetch. The cause exists
so a catalogue can stop spending an absence like a verdict.
"""

from __future__ import annotations

import json

import pytest

from src.ingest import EthicalFetcher, RobotsUnavailable, _persisted_robots_causes


class _Resp:
    def __init__(self, status: int, text: str = ""):
        self.status_code, self.text, self.content = status, text, text.encode()
        self.headers, self.url = {}, "https://ex.example/robots.txt"


def _fetcher(tmp_path, robots):
    """A fetcher whose only network is the robots.txt answer ``robots`` (a _Resp or an
    exception to raise)."""
    f = EthicalFetcher(min_interval_s=0, robots_cache_path=tmp_path / "robots.json")

    def _get(url, **kw):
        if isinstance(robots, Exception):
            raise robots
        return robots, url

    f._guarded_redirect_get = _get  # type: ignore[method-assign]
    return f


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (_Resp(403), "refused"),
        (_Resp(401), "refused"),
        (_Resp(500), "server_error"),
        (_Resp(418), "server_error"),
    ],
)
def test_each_http_answer_names_its_own_cause(tmp_path, answer, expected):
    f = _fetcher(tmp_path, answer)
    with pytest.raises(RobotsUnavailable) as ei:
        f._enforce_robots("https://ex.example/x", "https://ex.example", None)
    assert ei.value.cause == expected
    assert expected in str(ei.value)          # the message says it too, for a log reader


def test_a_network_failure_is_unreachable_not_a_refusal(tmp_path):
    import requests

    f = _fetcher(tmp_path, requests.RequestException("connection reset"))
    with pytest.raises(RobotsUnavailable) as ei:
        f._enforce_robots("https://ex.example/x", "https://ex.example", None)
    assert ei.value.cause == "unreachable"


def test_no_robots_txt_is_not_in_this_bucket_at_all(tmp_path):
    """404/410 means everything is allowed -- the standard behaviour, and the reason
    "should we treat unavailable as a green light" is a question about refusals and
    failures rather than about absence."""
    for status in (404, 410):
        f = _fetcher(tmp_path, _Resp(status))
        f._enforce_robots("https://ex.example/x", "https://ex.example", None)   # no raise


def test_the_cause_survives_the_cache_and_is_never_guessed_when_absent(tmp_path):
    """Two halves of one honesty property. A cached refusal must report the SAME cause the
    first call gave it -- otherwise attribution is right once an hour and wrong in between.
    And an entry with NO recorded cause reports "unknown" rather than a plausible default,
    because a confident wrong attribution in the pipeline's own data is worse than none."""
    f = _fetcher(tmp_path, _Resp(403))
    with pytest.raises(RobotsUnavailable) as first:
        f._enforce_robots("https://ex.example/x", "https://ex.example", None)
    assert first.value.cause == "refused"

    f._guarded_redirect_get = None  # type: ignore[method-assign]  # a second call must not refetch
    with pytest.raises(RobotsUnavailable) as cached:
        f._enforce_robots("https://ex.example/y", "https://ex.example", None)
    assert cached.value.cause == "refused"

    f._robots_cause.clear()                    # as if reloaded from a pre-cause sidecar
    with pytest.raises(RobotsUnavailable) as reloaded:
        f._enforce_robots("https://ex.example/z", "https://ex.example", None)
    assert reloaded.value.cause == "unknown"


def test_the_cause_is_persisted_and_read_back(tmp_path):
    path = tmp_path / "robots.json"
    f = _fetcher(tmp_path, _Resp(403))
    with pytest.raises(RobotsUnavailable):
        f._enforce_robots("https://ex.example/x", "https://ex.example", None)
    if path.exists():                          # persistence is opt-in; assert it when on
        assert json.loads(path.read_text())["https://ex.example"]["cause"] == "refused"
        assert _persisted_robots_causes(path)["https://ex.example"] == "refused"
    assert _persisted_robots_causes(tmp_path / "absent.json") == {}


def test_preflight_never_writes_a_permission_it_did_not_establish():
    """The finding this turn: `robots_allowed = verdict != "robots_denied"` wrote True
    whenever the verdict was "unreachable" -- asserting, in the API and in every query over
    the column, a permission derived from a robots.txt nobody read. The column is nullable
    and NULL means UNKNOWN, which is a different fact from allowed."""
    from src.monitoring import preflight

    class _Meta:
        robots_allowed = "untouched"
        crawl_delay = None
        robots_txt_url = None

    class _Src:
        id, domain, rate_limit_ms = 1, "ex.example", 2000

    class _Q:
        def filter_by(self, **kw):
            return self

        def first(self):
            return meta

    class _Session:
        def query(self, *a):
            return _Q()

        def add(self, *a):
            pass

    for state, expected in (
        ("allowed", True), ("missing", True),
        ("disallowed", False), ("blocked", False),
        ("unreachable", None), ("http_503", None), ("something-new", None),
    ):
        meta = _Meta()
        rec = {"robots": state, "verdict": "x"}
        preflight._apply_to_metadata(_Session(), _Src(), rec)
        assert meta.robots_allowed is expected, state
