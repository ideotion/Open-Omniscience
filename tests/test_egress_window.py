"""The AI-install egress window: what it permits, and everything it must NOT.

Operator, 2026-08-01: install Ollama/vLLM without starting the collector --
"divulging your IP to ollama and vllm is not the same as divulging it to all
scrapped sources". The mechanism keeps the kill switch ENGAGED and exempts only
the AI-install gates, so "the collector stays silent" is structural rather than a
convention nobody is enforcing.

The NEGATIVE SPACE is the point of this file. A test that merely proves the
install works would pass just as happily against a version that had quietly
opened the whole network, which is the failure the operator asked us to avoid --
so most of what follows asserts what is still REFUSED while a window is open.
"""

from __future__ import annotations

import socket
import threading

import pytest

import src.ingest.airplane as ap
from src.ingest import (
    activate_kill_switch,
    clear_kill_switch,
    kill_switch_active,
)
from src.ingest import egress_window as ew
from src.ingest.airplane import (
    AirplaneModeError,
    install_airplane_socket_guard,
    uninstall_airplane_socket_guard,
)


class _Reached(Exception):
    """Raised BY THE SPY standing in for a real socket call.

    Its presence proves the real call was reached; its absence proves it was not.
    Asserting only "some exception was raised" would not distinguish a refusal
    from a connection that actually happened and then failed.
    """


@pytest.fixture(autouse=True)
def _clean_window():
    ew._reset_for_tests()
    clear_kill_switch()
    yield
    ew._reset_for_tests()
    clear_kill_switch()


@pytest.fixture
def guard():
    """The guard installed over spies, so we can see whether the REAL call ran."""
    saved = (
        ap._orig_getaddrinfo,
        ap._orig_create_connection,
        ap._orig_connect,
        ap._orig_connect_ex,
        ap._orig_tunnel,
        ap._orig_socks_connect,
    )
    reached: list[str] = []
    mine = threading.get_ident()

    # THREAD-SCOPED, because the guard it spies on is PROCESS-wide (2026-08-02).
    # These spies replace the real socket calls for every thread in the interpreter,
    # so a background thread belonging to some other test's app -- a scheduler left
    # running by a `TestClient(app)` lifespan, say -- lands its own loopback connect
    # in this list and shifts every index. That is exactly what the macOS portability
    # lane caught: `['connect', 'getaddrinfo', 'getaddrinfo', 'getaddrinfo']` where
    # the test itself had made only the three getaddrinfo calls. Recording only the
    # calling thread's calls makes the assertion measure what THIS test did, and
    # keeps it strict -- a stray call from the test's own thread still shows up.
    def _note(name):
        if threading.get_ident() == mine:
            reached.append(name)

    def spy(name):
        def _f(*a, **k):
            _note(name)
            raise _Reached(name)

        return _f

    ap._orig_getaddrinfo = spy("getaddrinfo")  # type: ignore[assignment]
    ap._orig_create_connection = spy("create_connection")  # type: ignore[assignment]
    ap._orig_connect = lambda self, address: _note("connect")  # type: ignore[assignment]
    ap._orig_connect_ex = lambda self, address: _note("connect_ex")  # type: ignore[assignment]
    ap._orig_tunnel = spy("tunnel")  # type: ignore[assignment]
    if ap._orig_socks_connect is not None:
        ap._orig_socks_connect = spy("socks_connect")  # type: ignore[assignment]
    install_airplane_socket_guard()
    clear_kill_switch()
    try:
        yield reached
    finally:
        clear_kill_switch()
        (
            ap._orig_getaddrinfo,
            ap._orig_create_connection,
            ap._orig_connect,
            ap._orig_connect_ex,
            ap._orig_tunnel,
            ap._orig_socks_connect,
        ) = saved
        uninstall_airplane_socket_guard()


# --------------------------------------------------------------------------- #
# 1. Airplane mode's ORDINARY guarantee is unchanged when no window is open.
# --------------------------------------------------------------------------- #
def test_with_no_window_airplane_still_refuses_before_any_real_socket_call(guard):
    """The pre-existing guarantee, re-pinned HERE so a regression in it shows up
    as a failure of this feature and not only of its own file."""
    activate_kill_switch()
    with pytest.raises(AirplaneModeError):
        socket.getaddrinfo("example.com", 443)
    assert guard == [], "the real getaddrinfo must never be reached under airplane mode"


def test_with_no_window_loopback_still_passes_through(guard):
    """Loopback inference (the local LLM) must keep working offline."""
    activate_kill_switch()
    for host in ("127.0.0.1", "localhost", "::1"):
        with pytest.raises(_Reached):
            socket.getaddrinfo(host, 11434)
    assert guard == ["getaddrinfo"] * 3


def test_guard_stays_transparent_when_online(guard):
    """A window changes nothing about the online path."""
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    with pytest.raises(_Reached):
        socket.getaddrinfo("example.com", 443)
    assert guard == ["getaddrinfo"]


# --------------------------------------------------------------------------- #
# 2. THE NEGATIVE SPACE: with a window OPEN, everything else is still refused.
# --------------------------------------------------------------------------- #
def test_a_scraped_source_fetch_is_still_refused_while_a_window_is_open():
    """THE OPERATOR'S ENTIRE ASK, stated as a test.

    EthicalFetcher is the path every scraped source travels. It reads the kill
    switch Event DIRECTLY rather than through ``kill_switch_active()``, so it
    cannot consult a window even by accident -- this asserts that structural
    property rather than trusting it.
    """
    from src.ingest import EthicalFetcher, FetchFailed

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    assert ew.any_window_open(), "precondition: the window really is open"

    fetcher = EthicalFetcher()
    with pytest.raises(FetchFailed, match="kill switch"):
        fetcher.fetch("https://news.example.com/article")
    with pytest.raises(FetchFailed, match="kill switch"):
        fetcher.declared_sitemaps("https://news.example.com/")


def test_the_generic_guarded_session_is_still_refused_while_a_window_is_open():
    """The chokepoint for dumps, wiki, ORES and DuckDuckGo.

    A session built WITHOUT naming a purpose keeps the old absolute refusal, so
    an open window cannot widen any of them.
    """
    from src.safety.fetcher import NetworkBlocked, guarded_session

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)

    session = guarded_session()
    assert session.egress_purpose is None
    with pytest.raises(NetworkBlocked):
        session.request("GET", "https://dumps.wikimedia.org/")


def test_only_the_named_purpose_is_exempted():
    """A window is scoped: a gate asking for a different purpose still refuses,
    and a caller that forgets to name one gets the old refusing behaviour."""
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)

    assert ew.egress_permitted(ew.PURPOSE_AI_INSTALL) is True
    assert ew.egress_permitted("some-other-purpose") is False
    assert ew.egress_permitted(None) is False


def test_opening_a_window_never_clears_the_kill_switch():
    """The whole safety case rests on this: ~75 call sites keep refusing because
    ``kill_switch_active()`` keeps returning True."""
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    assert kill_switch_active() is True


def test_opening_a_window_never_starts_the_collector():
    """A window must not start the scheduler, directly or as a side effect."""
    from src.scheduler.runner import get_scheduler

    activate_kill_switch()
    was_running = get_scheduler().is_running()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    assert get_scheduler().is_running() == was_running


def test_the_endpoint_that_opens_a_window_never_touches_the_scheduler():
    """Source-level guard on the route itself.

    ``POST /api/system/network`` deliberately starts the collector (the
    "Online <=> collecting" ruling). The egress-window route must never grow the
    same coupling by a later copy-paste, so its body is asserted scheduler-free.
    """
    import inspect

    from src.api import system as sysmod

    body = inspect.getsource(sysmod.set_egress_window)
    for forbidden in ("get_scheduler", "scheduler.start", "clear_kill_switch"):
        assert forbidden not in body, f"the egress-window route must not call {forbidden}"


def test_a_window_permits_only_the_ai_install_gates():
    """The five gates flip; a scraped-source fetch does not (covered above)."""
    from src.llm import installer, vllm_lifecycle

    activate_kill_switch()
    with pytest.raises(installer.InstallerUnavailable):
        installer._check_online()
    with pytest.raises(vllm_lifecycle.VllmLifecycleError):
        vllm_lifecycle._check_online()

    ew.open_window(ew.PURPOSE_AI_INSTALL)
    installer._check_online()  # must not raise
    vllm_lifecycle._check_online()  # must not raise


# --------------------------------------------------------------------------- #
# 3. Loopback inference keeps working offline, window or no window.
# --------------------------------------------------------------------------- #
def test_loopback_inference_is_allowed_offline_with_no_window():
    """A pull is clearnet and must refuse; generate/list are loopback and must not."""
    from src.llm.ollama import LLMUnavailable, OllamaClient

    activate_kill_switch()
    client = OllamaClient(base_url="http://127.0.0.1:11434")
    client._check_kill_switch()  # loopback inference: allowed offline
    with pytest.raises(LLMUnavailable):
        client._check_kill_switch(clearnet=True)


def test_a_window_permits_the_model_pull_but_never_a_non_loopback_base_url():
    """The clearnet half is exempted by a window (pulling the default model IS
    the install). The non-loopback-base_url half is defense in depth against a
    misconfigured or injected client and is NEVER exempted."""
    from src.llm.ollama import LLMUnavailable, OllamaClient

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)

    OllamaClient(base_url="http://127.0.0.1:11434")._check_kill_switch(clearnet=True)

    # A non-loopback base_url cannot even be CONSTRUCTED (_require_loopback), so
    # the branch under test is defense in depth against a base_url mutated after
    # construction. Reproduce exactly that, rather than a shape the constructor
    # already makes impossible.
    remote = OllamaClient(base_url="http://127.0.0.1:11434")
    remote.base_url = "http://ollama.example.com:11434"
    with pytest.raises(LLMUnavailable):
        remote._check_kill_switch()
    with pytest.raises(LLMUnavailable):
        remote._check_kill_switch(clearnet=True)


# --------------------------------------------------------------------------- #
# 4. EVERY close path. Success, failure and cancel are one rule -- "nothing is
#    running any more" -- so each is driven through the same reap.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("outcome", ["done", "error", "cancelled"])
def test_the_window_closes_after_the_install_job_ends_however_it_ends(monkeypatch, outcome):
    """Success, FAILURE and cancel all close the window.

    The failure path is the one most likely to leak a window open, so it is
    driven explicitly rather than assumed to follow from the success path.
    """
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    monkeypatch.setattr(ew, "_idle_grace", lambda: 0.0)

    # While the job runs the window must survive the reap.
    assert ew.reap_idle(is_busy=lambda: True) is False
    assert ew.any_window_open() is True

    # The job reaches a terminal state -> nothing is running -> the window closes.
    assert ew.reap_idle(is_busy=lambda: False) is True, f"must close on {outcome}"
    assert ew.any_window_open() is False
    assert ew.egress_permitted(ew.PURPOSE_AI_INSTALL) is False


def test_a_job_registry_probe_sees_a_running_install_job(monkeypatch):
    """The default probe reads the LIVE registry, so the reap keys on reality."""
    monkeypatch.setattr(
        ew, "_default_is_busy", ew._default_is_busy
    )  # explicit: we use the real one
    monkeypatch.setattr(
        "src.jobs.background.all_job_statuses",
        lambda: [{"kind": "vllm-install", "state": "running"}],
    )
    assert ew._default_is_busy() is True

    monkeypatch.setattr(
        "src.jobs.background.all_job_statuses",
        lambda: [{"kind": "vllm-install", "state": "error"}],
    )
    # No hold, no pull queued -> not busy.
    ew._reset_for_tests()
    assert ew._default_is_busy() is False


def test_a_hold_keeps_the_window_open_for_work_that_is_not_a_job(monkeypatch):
    """The Ollama binary installer is a streaming endpoint, not a BackgroundJob."""
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    monkeypatch.setattr(ew, "_idle_grace", lambda: 0.0)

    with ew.hold():
        assert ew._default_is_busy() is True
        assert ew.reap_idle() is False
        assert ew.any_window_open() is True
    # Hold released -> the reap may now close it.
    assert ew.reap_idle() is True
    assert ew.any_window_open() is False


def test_a_hold_is_released_even_when_the_work_raises():
    """A failing install must not leave the window pinned open forever."""
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    with pytest.raises(RuntimeError):
        with ew.hold():
            raise RuntimeError("install blew up")
    assert ew._default_is_busy() is False


def test_the_window_closes_at_its_deadline():
    """The backstop for a window nothing ever polls."""
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL, ttl_s=1)
    assert ew.any_window_open() is True
    # Advance the clock rather than sleeping: monotonic time is the only input.
    real_now = ew._now
    try:
        ew._now = lambda: real_now() + 3600  # type: ignore[assignment]
        assert ew.any_window_open() is False
        assert ew.egress_permitted(ew.PURPOSE_AI_INSTALL) is False
    finally:
        ew._now = real_now  # type: ignore[assignment]


def test_going_offline_closes_the_window():
    """Airplane mode must mean what it says: engaging it closes any window."""
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    assert ew.any_window_open() is True
    activate_kill_switch()  # the operator taps the airplane button again
    assert ew.any_window_open() is False


def test_the_operator_can_close_the_window_by_hand():
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    assert ew.close_window() is True
    assert ew.any_window_open() is False
    assert ew.close_window() is False  # idempotent


def test_window_state_is_never_persisted():
    """A window cannot survive a process restart -- state is in memory only, and
    boot re-engages airplane before anything else runs. Asserted at the source
    level because 'we did not write a file' is not observable from the outside."""
    import inspect

    src = inspect.getsource(ew)
    # Tokens chosen to be UNAMBIGUOUS. A first draft used the bare "open(" and
    # failed against correct code -- it matched the module's own
    # ``any_window_open()``. A "must be gone" guard is only as good as the
    # specificity of what it searches for (the recorded house lesson).
    for forbidden in ("data_dir", "write_text", "write_bytes", "json.dump", "pathlib"):
        assert forbidden not in src, f"the window must not persist state ({forbidden})"


def test_a_ttl_is_always_bounded():
    """An operator override may narrow or widen the deadline but never remove it."""
    activate_kill_switch()
    st = ew.open_window(ew.PURPOSE_AI_INSTALL, ttl_s=10**9)
    assert 0 < st["seconds_remaining"] <= 24 * 3600
    st = ew.open_window(ew.PURPOSE_AI_INSTALL, ttl_s=-5)
    assert st["seconds_remaining"] >= 0


def test_an_unknown_purpose_is_refused():
    with pytest.raises(ew.EgressWindowError):
        ew.open_window("not-a-real-purpose")


def test_status_reports_the_measured_collector_state_or_an_honest_unknown(monkeypatch):
    """'Collection is stopped' must be a READ of the scheduler, never our own
    assumption -- and an unreadable scheduler must say unknown, not False."""
    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _FakeSched(False))
    assert ew.status(with_collector=True)["collector_running"] is False

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _FakeSched(True))
    assert ew.status(with_collector=True)["collector_running"] is True

    def _boom():
        raise RuntimeError("scheduler unreachable")

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", _boom)
    assert ew.status(with_collector=True)["collector_running"] is None


class _FakeSched:
    def __init__(self, running: bool) -> None:
        self._running = running

    def is_running(self) -> bool:
        return self._running


def test_no_payload_field_is_named_like_a_score():
    """The house no-score convention: walk KEYS, not repr (a caveat may legitimately
    contain the word). Note 'degraded' contains 'grade', so statuses stay values."""
    activate_kill_switch()
    payloads = [ew.open_window(ew.PURPOSE_AI_INSTALL), ew.status(with_collector=True)]
    banned = ("score", "ranking", "rating", "grade")
    for payload in payloads:
        for key in payload:
            assert not any(b in key.lower() for b in banned), key


# --------------------------------------------------------------------------- #
# The socket backstop is THREAD-scoped, not process-wide.
#
# The first version of this feature lifted the backstop for the whole process
# while a window was open, reasoning that every real fetch path checks the kill
# switch itself. That reasoning was wrong, and the tests below are the ones that
# would have caught it: preflight reaches the network through EthicalFetcher's
# side doors (_guard_target / _guarded_redirect_get) using the fetcher's PLAIN
# requests.Session, so it met neither the kill-switch gate nor GuardedSession's.
# The backstop was its only protection, and lifting it process-wide let an
# AI-install window resolve and fetch scraped-source hosts.
# --------------------------------------------------------------------------- #
def test_preflight_never_reaches_a_source_while_a_window_is_open(guard):
    """The source-preflight sweep is the path that had NO gate of its own.

    Drives the REAL production path -- ``make_fetcher()`` + ``preflight._check_one``
    -- rather than an injected double, because a double would bypass the very
    session and side doors this is about (the house lesson: a test double injected
    via a parameter bypasses the production path).

    Uses the ``guard`` fixture's OWN spy list rather than monkeypatching
    ``ap._orig_getaddrinfo``: that global belongs to the fixture, and a
    ``monkeypatch`` over it captures the fixture's spy as its "original", so
    whichever finalizer happens to run last decides what is left behind. That is
    how the first draft of this test leaked a spy into an unrelated later test
    (``test_llm_active_model``) and turned a real socket call into a mystery
    failure 6000 tests downstream. One owner per global.
    """
    from src.monitoring import preflight
    from src.safety.fetcher import make_fetcher

    class _Src:
        id = 1
        domain = "news.example-source.test"
        priority = 1
        rate_limit_ms = 0

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    assert ew.any_window_open(), "precondition: the window really is open"

    rec = preflight._check_one(make_fetcher(), _Src())

    # Not even a DNS lookup: resolving a source hostname is itself egress -- it
    # hands the operator's resolver the list of sources they read. ``guard``
    # records every REAL socket call that was reached, so an empty list is proof
    # none was, not merely proof that no exception escaped.
    assert guard == [], f"a real socket call was reached during a window: {guard}"
    assert rec["verdict"] == "unreachable"
    assert "kill switch" in rec.get("robots_error", "")


def test_a_bare_socket_on_another_thread_is_refused_while_a_window_is_open(guard):
    """A third-party library doing its own HTTP -- the class the backstop exists for.

    ``src/custody/timestamp.py``'s OpenTimestamps submit is the live example: it
    calls the library's own client, consults no gate of ours, and was protected by
    the backstop alone. A window must not lift that for it.
    """
    import threading

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)

    result: dict = {}

    def _other_thread():
        try:
            socket.getaddrinfo("a.pool.opentimestamps.org", 443)
        except AirplaneModeError:
            result["outcome"] = "refused"
        except _Reached:  # pragma: no cover - the spy would mean the real call ran
            result["outcome"] = "REACHED THE REAL CALL"
        else:  # pragma: no cover
            result["outcome"] = "permitted"

    th = threading.Thread(target=_other_thread)
    th.start()
    th.join(timeout=5)
    assert result.get("outcome") == "refused"

    # ...and on this thread too, outside an exempted request.
    with pytest.raises(AirplaneModeError):
        socket.getaddrinfo("a.pool.opentimestamps.org", 443)


def test_the_install_session_does_reach_the_socket_while_a_window_is_open(guard):
    """The POSITIVE half: an exemption narrow enough to be safe must still work.

    Without this, "refuse everything" would pass every negative-space test above
    while quietly breaking the feature the operator asked for.
    """
    from src.safety.fetcher import guarded_session

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)

    session = guarded_session(egress_purpose=ew.PURPOSE_AI_INSTALL)
    # The spy stands in for the real resolver: reaching it proves the guard stood
    # aside for this request, which is exactly what the window is for.
    with pytest.raises(_Reached):
        session.request("GET", "https://api.github.com/repos/ollama/ollama/releases/latest")


def test_the_thread_exemption_does_not_outlive_the_request(guard):
    """The exemption is entered per-request and unwound after it, including on error."""
    from src.safety.fetcher import guarded_session

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL)
    assert ew.socket_exempt_here() is False

    session = guarded_session(egress_purpose=ew.PURPOSE_AI_INSTALL)
    with pytest.raises(_Reached):
        session.request("GET", "https://api.github.com/x")

    assert ew.socket_exempt_here() is False, "the exemption leaked past the request"
    with pytest.raises(AirplaneModeError):
        socket.getaddrinfo("api.github.com", 443)


def test_the_exemption_alone_is_not_enough_without_a_live_window(guard):
    """Both conditions are required, so an exemption that somehow survived a close
    cannot re-open the backstop on its own."""
    activate_kill_switch()
    with ew.socket_exemption():
        assert ew.socket_exempt_here() is True
        with pytest.raises(AirplaneModeError):
            socket.getaddrinfo("pypi.org", 443)


# --------------------------------------------------------------------------- #
# "It closes on its own" must not depend on a browser polling it.
# --------------------------------------------------------------------------- #
def test_the_window_closes_itself_with_nobody_polling_it(monkeypatch):
    """The consent dialog promises the window closes once the install ends.

    Before the reaper thread, ``reap_idle`` had exactly ONE caller -- the status
    endpoint -- so that promise held only while a browser tab was open. An
    operator who started an install and walked away kept the window open to its
    full deadline. This test calls ``reap_idle`` nowhere.
    """
    import time

    monkeypatch.setattr(ew, "_reap_tick", lambda: 0.02)
    monkeypatch.setattr(ew, "_idle_grace", lambda: 0.05)

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL, ttl_s=3600)
    assert ew.any_window_open() is True

    deadline = time.monotonic() + 10.0
    while ew.any_window_open() and time.monotonic() < deadline:
        time.sleep(0.02)

    assert ew.any_window_open() is False, "the window never closed without being polled"
    assert ew.status()["seconds_remaining"] == 0


def test_the_reaper_waits_for_work_that_is_actually_running(monkeypatch):
    """The self-closing must not cut an install short."""
    import time

    monkeypatch.setattr(ew, "_reap_tick", lambda: 0.02)
    monkeypatch.setattr(ew, "_idle_grace", lambda: 0.05)

    activate_kill_switch()
    ew.open_window(ew.PURPOSE_AI_INSTALL, ttl_s=3600)
    with ew.hold():
        time.sleep(0.3)
        assert ew.any_window_open() is True, "the reaper closed a window mid-install"

    deadline = time.monotonic() + 10.0
    while ew.any_window_open() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ew.any_window_open() is False


def test_a_hold_that_is_never_released_cannot_pin_a_later_window(monkeypatch):
    """Holds belong to their own window.

    A wedged ``sh install.sh`` whose ``proc.wait()`` never returns leaves a hold
    outstanding. As a module global that pinned EVERY later window open to the
    full six-hour deadline -- silently voiding the idle close for the rest of the
    process. Scoped to the window, it dies with it.
    """
    monkeypatch.setattr(ew, "_idle_grace", lambda: 0.0)
    activate_kill_switch()

    ew.open_window(ew.PURPOSE_AI_INSTALL)
    leaked = ew.hold()
    leaked.__enter__()          # deliberately never exited
    ew.close_window()

    ew.open_window(ew.PURPOSE_AI_INSTALL)
    assert ew._default_is_busy() is False, "a stale hold still reads as work in progress"
    assert ew.reap_idle() is True, "a stale hold pinned an unrelated later window open"


def test_a_hold_taken_with_no_window_open_is_a_no_op(monkeypatch):
    """There is nothing to hold open, so it must not pin the NEXT window either."""
    monkeypatch.setattr(ew, "_idle_grace", lambda: 0.0)
    activate_kill_switch()

    with ew.hold():
        ew.open_window(ew.PURPOSE_AI_INSTALL)
        assert ew._default_is_busy() is False
        assert ew.reap_idle() is True


def test_a_job_left_running_by_a_killed_worker_does_not_wedge_the_window(monkeypatch):
    """``state`` stays "running" if a worker dies to a BaseException; ``ended_at``
    is what distinguishes that from work genuinely in flight."""
    monkeypatch.setattr(
        "src.jobs.background.all_job_statuses",
        lambda: [{"kind": "vllm-install", "state": "running", "ended_at": 123.0}],
    )
    assert ew._default_is_busy() is False

    monkeypatch.setattr(
        "src.jobs.background.all_job_statuses",
        lambda: [{"kind": "vllm-install", "state": "running", "ended_at": None}],
    )
    assert ew._default_is_busy() is True
