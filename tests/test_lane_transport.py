"""Each lane declares its transport, and a lane that cannot reach it WAITS with a reason.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S04-08's S5, Q1014: "each lane declares its transport in the consent hover; a lane
whose transport is unavailable waits with a named reason -- never Tor -> clearnet".

Three halves:

* the SERVER reads the transport through the fetch path's own reader
  (``transport_summary`` over ``_protected_transport``), so the popup cannot describe a
  transport the fetch path would not use. The popup used to read ``http_proxy`` alone
  and said "fetches ride the proxy you configured" in transparent mode, where that
  proxy is ignored;
* the Wikipedia stream, the one long-lived lane connection, records WHY it is failing
  and the lane status says so, instead of reading "running" while every connection is
  refused;
* the popup's sentences are driven as real code in ``net_lane_transport_node_test.js``.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from src.safety.fetcher import NO_PROXY_REFUSAL, transport_summary
from src.safety.settings import SafetySettings

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_popup_sentences_run_as_real_code() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "net_lane_transport_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --------------------------------------------------------------------------- #
#  The server's reading
# --------------------------------------------------------------------------- #
def test_transparent_mode_is_DIRECT_even_with_a_proxy_stored() -> None:
    """The recorded popup bug: a stored proxy in transparent mode is not used."""
    s = SafetySettings(fetch_mode="transparent", http_proxy="socks5h://127.0.0.1:9050",
                       http_proxies=["socks5h://127.0.0.1:9150"])
    assert transport_summary(s) == {"kind": "direct"}


def test_protected_mode_with_one_proxy() -> None:
    s = SafetySettings(fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9050")
    assert transport_summary(s) == {"kind": "proxy"}


def test_a_pool_takes_precedence_and_is_counted_never_listed() -> None:
    s = SafetySettings(fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9050",
                       http_proxies=["socks5h://127.0.0.1:9150", "socks5h://127.0.0.1:9152"])
    out = transport_summary(s)
    assert out == {"kind": "pool", "members": 2}
    assert "9150" not in repr(out), "the token carries a count, not the addresses"


def test_protected_mode_with_no_proxy_is_REFUSED_by_name() -> None:
    # Only reachable through the environment or a hand-edited file (save_settings
    # refuses it), which is exactly why the popup must say so rather than "direct".
    s = SafetySettings(fetch_mode="protected")
    assert transport_summary(s) == {"kind": "refused", "reason": NO_PROXY_REFUSAL}


def test_a_pool_with_a_clearnet_member_is_refused_WHOLE() -> None:
    s = SafetySettings(fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9050",
                       http_proxies=["socks5h://127.0.0.1:9150", "http://127.0.0.1:8118"])
    out = transport_summary(s)
    assert out["kind"] == "refused", "a pool with a non-SOCKS member fell back to the single proxy"
    assert "not a SOCKS proxy" in out["reason"]


def test_the_summary_agrees_with_the_session_the_fetch_path_builds(monkeypatch) -> None:
    """Anti-drift: the popup's token and the real session describe the same transport."""
    from src.safety import fetcher as fetcher_mod

    cases = {
        "direct": SafetySettings(fetch_mode="transparent", http_proxy="socks5h://127.0.0.1:9050"),
        "proxy": SafetySettings(fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9050"),
        "pool": SafetySettings(fetch_mode="protected",
                               http_proxies=["socks5h://127.0.0.1:9150", "socks5h://127.0.0.1:9152"]),
        "refused": SafetySettings(fetch_mode="protected"),
    }
    for kind, s in cases.items():
        assert transport_summary(s)["kind"] == kind
        monkeypatch.setattr(fetcher_mod, "load_settings", lambda s=s: s)
        if kind == "refused":
            with pytest.raises(fetcher_mod.TransportUnavailable):
                fetcher_mod.make_fetcher(settings=s)
            continue
        sess = fetcher_mod.guarded_session()
        if kind == "direct":
            assert not sess.proxies, "transparent mode built a proxied session"
        elif kind == "proxy":
            assert sess.proxies, "protected mode built a session with no proxy"


# --------------------------------------------------------------------------- #
#  The settings endpoint carries it, on read AND on write
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    for var in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(var, raising=False)
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_the_settings_endpoint_reports_the_transport_on_read_and_write(client) -> None:
    assert client.get("/api/safety/settings").json()["transport"] == {"kind": "direct"}
    put = client.put("/api/safety/settings",
                     json={"fetch_mode": "protected", "http_proxy": "socks5h://127.0.0.1:9050"})
    assert put.status_code == 200, put.text
    assert put.json()["transport"] == {"kind": "proxy"}, "the PUT answer left the transport stale"
    assert client.get("/api/safety/settings").json()["transport"] == {"kind": "proxy"}
    # Back to transparent WITH the proxy still stored: the popup must say direct.
    back = client.put("/api/safety/settings", json={"fetch_mode": "transparent"})
    assert back.json()["http_proxy"], "the proxy should still be stored"
    assert back.json()["transport"] == {"kind": "direct"}


# --------------------------------------------------------------------------- #
#  The Wikipedia stream waits with a reason
# --------------------------------------------------------------------------- #
def test_the_stream_records_WHY_it_is_failing_and_forgets_it_on_the_next_event() -> None:
    from src.safety.fetcher import TransportUnavailable
    from tests.test_wiki_stream import _body, _event_lines, _Response, _Session, _stream

    session = _Session([
        _Response([], raises=OSError("reset")),
        _Response([], raises=TransportUnavailable(NO_PROXY_REFUSAL)),
    ])
    stream = _stream(session, sleep=lambda _s: None)
    stream.run(lambda _c: None, max_connections=2)
    c = stream.counters.as_dict()
    assert c["consecutive_failures"] == 2
    assert c["last_failure"].startswith("TransportUnavailable: protected fetch mode is on"), (
        "the reason is the LATEST failure, named by its type"
    )

    session = _Session([
        _Response([], raises=TransportUnavailable(NO_PROXY_REFUSAL)),
        _Response(_event_lines(_body())),
    ])
    stream = _stream(session, sleep=lambda _s: None)
    stream.run(lambda _c: None, max_connections=2)
    assert stream.counters.consecutive_failures == 0
    assert stream.counters.last_failure is None, "a wait that ended still reports its reason"


def test_the_reason_is_bounded() -> None:
    from tests.test_wiki_stream import _Response, _Session, _stream

    session = _Session([_Response([], raises=OSError("x" * 5000))])
    stream = _stream(session, sleep=lambda _s: None)
    stream.run(lambda _c: None, max_connections=1)
    assert len(stream.counters.last_failure) == 300


def test_the_runner_hands_the_counters_through() -> None:
    from src.wiki.runner import WikiLaneRunner
    from tests.test_wiki_stream import _Response, _Session, _stream

    stream = _stream(_Session([_Response([], raises=OSError("reset"))]), sleep=lambda _s: None)
    stream.run(lambda _c: None, max_connections=1)
    runner = object.__new__(WikiLaneRunner)  # only the stream is read
    runner._stream = stream
    out = runner.stream_counters()
    assert out["consecutive_failures"] == 1 and out["last_failure"] == "OSError: reset"
    runner._stream = object()  # a stream that keeps no counters
    assert runner.stream_counters() is None


@pytest.fixture()
def live_stream():
    """A stream registered as live, through the real registry."""
    from src.wiki import stream as stream_mod

    fake = object()
    with stream_mod._LIVE_LOCK:
        stream_mod._LIVE[id(fake)] = ("en",)
    try:
        yield
    finally:
        with stream_mod._LIVE_LOCK:
            stream_mod._LIVE.pop(id(fake), None)


def _service_with(monkeypatch, stream):
    from src.wiki import service

    monkeypatch.setattr(service, "lane_service_status", lambda: {
        "streaming": True, "draining": False, "drains": 0, "last_drain": None, "stream": stream,
    })


def test_a_live_stream_whose_connections_FAIL_is_waiting_and_says_on_what(monkeypatch, live_stream):
    from src.api.scheduler import _wiki_lane_block

    why = "TransportUnavailable: " + NO_PROXY_REFUSAL
    _service_with(monkeypatch, {"consecutive_failures": 3, "last_failure": why})
    block = _wiki_lane_block()
    assert block["active"] is True, "registered is still reported as registered"
    assert block["reason"] == "transport-waiting"
    assert block["waiting_on"] == why


def test_a_connected_stream_has_nothing_to_explain(monkeypatch, live_stream):
    from src.api.scheduler import _wiki_lane_block

    # A stale last_failure beside zero failures cannot surface: the count decides.
    _service_with(monkeypatch, {"consecutive_failures": 0, "last_failure": "OSError: old"})
    block = _wiki_lane_block()
    assert block["reason"] is None
    assert block["waiting_on"] is None


def test_no_stream_is_never_waiting(monkeypatch):
    from src.api.scheduler import _wiki_lane_block

    _service_with(monkeypatch, {"consecutive_failures": 5, "last_failure": "OSError: reset"})
    block = _wiki_lane_block()
    assert block["active"] is False
    assert block["reason"] != "transport-waiting", "no live stream, so nothing is waiting"
    assert block["waiting_on"] is None


def test_the_service_reports_no_counters_without_a_runner(monkeypatch):
    from src.wiki import service

    monkeypatch.setattr(service, "_RUNNER", None)
    assert service.lane_service_status()["stream"] is None


# --------------------------------------------------------------------------- #
#  A waiting stream notices a stop, or airplane mode, within one slice
# --------------------------------------------------------------------------- #
def _long_backoff_stream(sleep):
    """A stream whose every connection fails and whose backoff is two minutes."""
    from tests.test_wiki_stream import _Response, _Session, _stream

    session = _Session([_Response([], raises=OSError("reset")) for _ in range(5)])
    stream = _stream(session, sleep=sleep)
    stream.parser.retry_ms = 120_000  # the server's own reconnection time, honoured
    return stream


def test_a_STOP_ends_a_long_backoff_within_one_slice():
    """Found by the S5 walk: one uninterrupted sleep of up to five minutes kept a stream
    registered as LIVE after the lane was stopped, so the lane read "running"."""
    from src.wiki.stream import WikiEventStream

    slept: list[float] = []
    stop = {"now": False}

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) == 3:
            stop["now"] = True

    stream = _long_backoff_stream(sleep)
    stream.run(lambda _c: None, should_stop=lambda: stop["now"])
    assert stream.counters.connections == 1, "the stop was not honoured before a reconnect"
    assert len(slept) == 3 and max(slept) <= WikiEventStream.WAIT_SLICE_S, slept
    assert sum(slept) < 120, "the backoff was waited out rather than interrupted"


def test_AIRPLANE_MODE_during_a_backoff_is_refused_by_name_within_one_slice():
    from src.ingest import activate_kill_switch, clear_kill_switch
    from src.wiki.stream import StreamStopped

    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) == 2:
            activate_kill_switch()

    clear_kill_switch()
    try:
        stream = _long_backoff_stream(sleep)
        with pytest.raises(StreamStopped, match="kill switch"):
            stream.run(lambda _c: None)
    finally:
        clear_kill_switch()
    assert len(slept) == 2, f"airplane mode was noticed after {len(slept)} slices, not one"
    assert stream.counters.connections == 1


def test_a_backoff_nobody_interrupts_is_still_waited_in_FULL():
    """Anti-vacuity: slicing must not shorten the politeness the server asked for."""
    slept: list[float] = []
    stream = _long_backoff_stream(slept.append)
    stream.run(lambda _c: None, max_connections=2)
    assert sum(slept) == pytest.approx(120.0), slept
