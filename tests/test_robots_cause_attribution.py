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


# --------------------------------------------------------------- the per-host backoff

def test_the_backoff_schedule_doubles_from_the_base_and_is_capped(monkeypatch):
    """Pure, so the schedule is asserted directly rather than inferred from timing. A
    success is the plain TTL; failures double; the cap is the guarantee that a refusing
    host is still re-asked, which is what makes this a deferral and not an exclusion."""
    from src.ingest import _ROBOTS_TTL, _robots_ttl_for

    assert _robots_ttl_for(0) == _ROBOTS_TTL          # read it -> normal cache
    assert _robots_ttl_for(1) == _ROBOTS_TTL          # first failure -> base
    assert _robots_ttl_for(2) == _ROBOTS_TTL * 2
    assert _robots_ttl_for(4) == _ROBOTS_TTL * 8
    assert _robots_ttl_for(99) == 24 * 3600.0         # capped, never unbounded
    assert _robots_ttl_for(99) == _robots_ttl_for(1000)

    monkeypatch.setenv("OO_ROBOTS_BACKOFF_CAP_S", "7200")
    assert _robots_ttl_for(99) == 7200.0
    # A cap BELOW the base would cache a failure for less time than a success, which is
    # backwards; it is floored instead of honoured.
    monkeypatch.setenv("OO_ROBOTS_BACKOFF_CAP_S", "1")
    assert _robots_ttl_for(99) == _ROBOTS_TTL


def test_repeated_failure_backs_the_host_off_and_one_success_clears_it(tmp_path):
    """The whole point, on a real fetcher: a host that keeps refusing is asked less and
    less often, and the moment it answers the counter is gone -- no lingering penalty."""
    clock = {"t": 0.0}
    answer = {"resp": _Resp(403)}
    f = EthicalFetcher(min_interval_s=0, robots_cache_path=tmp_path / "r.json")
    f._now = lambda: clock["t"]  # type: ignore[method-assign]
    f._guarded_redirect_get = lambda url, **kw: (answer["resp"], url)  # type: ignore[method-assign]

    from src.ingest import _ROBOTS_TTL

    ttls = []
    for _ in range(4):
        with pytest.raises(RobotsUnavailable):
            f._enforce_robots("https://ex.example/x", "https://ex.example", None)
        ttls.append(f._robots["https://ex.example"][1] - clock["t"])
        clock["t"] += ttls[-1] + 1          # let the entry expire, then ask again
    assert ttls == [_ROBOTS_TTL, _ROBOTS_TTL * 2, _ROBOTS_TTL * 4, _ROBOTS_TTL * 8]
    assert f._robots_fails["https://ex.example"] == 4

    answer["resp"] = _Resp(200, "User-agent: *\nAllow: /")     # the host recovers
    f._enforce_robots("https://ex.example/x", "https://ex.example", None)   # no raise
    assert "https://ex.example" not in f._robots_fails
    assert "https://ex.example" not in f._robots_cause
    assert f._robots["https://ex.example"][1] - clock["t"] == _ROBOTS_TTL   # back to normal


def test_the_backoff_survives_a_restart(tmp_path):
    """A cold start that handed a host which had refused fifty times a fresh one-hour clock
    would make the politeness measure no measure at all."""
    import os

    os.environ["OO_ROBOTS_PERSIST"] = "1"
    try:
        path = tmp_path / "r.json"
        f = EthicalFetcher(min_interval_s=0, robots_cache_path=path)
        f._guarded_redirect_get = lambda url, **kw: (_Resp(403), url)  # type: ignore[method-assign]
        for _ in range(3):
            with pytest.raises(RobotsUnavailable):
                f._enforce_robots("https://ex.example/x", "https://ex.example", None)
            f._robots.pop("https://ex.example", None)      # expire, keep the counter
        assert f._robots_fails["https://ex.example"] == 3

        reborn = EthicalFetcher(min_interval_s=0, robots_cache_path=path)
        assert reborn._robots_fails.get("https://ex.example") == 3
        assert reborn._robots_cause.get("https://ex.example") == "refused"
    finally:
        os.environ.pop("OO_ROBOTS_PERSIST", None)


def test_forget_robots_clears_decision_cause_and_counter_together(tmp_path):
    """A partial forget would re-ask the host and then back it off using failures it is no
    longer counting. Scheme-agnostic, because a caller may name either form."""
    f = EthicalFetcher(min_interval_s=0, robots_cache_path=tmp_path / "r.json")
    f._guarded_redirect_get = lambda url, **kw: (_Resp(403), url)  # type: ignore[method-assign]
    with pytest.raises(RobotsUnavailable):
        f._enforce_robots("https://ex.example/x", "https://ex.example", None)
    assert f._robots and f._robots_cause and f._robots_fails

    assert f.forget_robots("ex.example") == 1        # bare host, no scheme
    assert not f._robots and not f._robots_cause and not f._robots_fails
    assert f.forget_robots("nothing.example") == 0 and f.forget_robots("") == 0


def test_an_explicit_retry_forgets_the_backoff_it_created(tmp_path):
    """Otherwise `--retry robots_unavailable` returns the cached refusal, rewrites the same
    verdict, and looks like work while asking no host anything."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "_vcf_retry", "scripts/analysis/verify_candidate_feeds.py"
    )
    vcf = importlib.util.module_from_spec(spec)
    sys.modules["_vcf_retry"] = vcf
    spec.loader.exec_module(vcf)

    out = tmp_path / "run"
    out.mkdir()
    (out / "verified.jsonl").write_text(
        '{"domain": "a.example", "status": "rejected", "reason": "robots_unavailable"}\n'
        '{"domain": "b.example", "status": "verified", "reason": "verified"}\n',
        encoding="utf-8",
    )
    forgotten: list[str] = []
    vcf.run([], fetch=lambda *a, **k: None, out_dir=out, workers=1,
            retry_reasons={"robots_unavailable"}, forget_robots=forgotten.append)
    assert forgotten == ["a.example"]        # the retried host only, not the verified one
