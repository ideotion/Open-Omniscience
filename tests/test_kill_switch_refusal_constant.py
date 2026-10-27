"""The kill switch's refusal sentence is defined ONCE and the reader is built from it (ruling R317).

The sentence was a string literal at five raise sites in ``src/ingest/__init__.py`` and one in ``src/safety/fetcher.py``, with the reader
(``fetch_verdict._OFFLINE_RE``) and the law tracker each holding their own copy of its opening words. A rewording at one writer would have
left the readers matching a sentence nobody raises any more, and the failure would have been silent: a refusal read as the HOST's failure
(R293, R297, R298 are all that one mistake). Now ``KILL_SWITCH_REFUSAL`` is the sentence, ``KILL_SWITCH_REFUSAL_HEAD`` its opening words, every
writer says the constant, and the reader's first alternative is built from the head.

A subclass of ``FetchFailed`` was considered and refused: most callers classify STORED strings (verdict JSON, queue state, diagnostics) and the
wrapped shapes carry the sentence inside another exception's text, so the text match has to stay; this only stops the copies from drifting.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.ingest import (
    EthicalFetcher,
    FetchFailed,
    activate_kill_switch,
    clear_kill_switch,
    fetch_verdict,
    kill_switch_active,
)
from src.ingest.fetch_verdict import (
    KILL_SWITCH_REFUSAL,
    KILL_SWITCH_REFUSAL_HEAD,
    classify_fetch_failure,
    is_kill_switch_refusal,
)

_SRC = Path(__file__).resolve().parent.parent / "src"
_TAIL = "collection stopped by operator"
_DEFINITION = "src/ingest/fetch_verdict.py"
# A Stop through an HTTP proxy, as OSM measured it (R320): the request error is wrapped, not our sentence.
_PROXY_SHAPED_STOP = (
    "request error for https://h.test/a: ('Connection aborted.', AirplaneModeError(\"airplane mode is engaged: refusing a network "
    "connection to 'h.test'. No packet leaves the machine while offline\"))"
)

# What the pattern said BEFORE the head became a constant, copied here so the change is proved to be a pure refactor of the reader.
_OLD_OFFLINE_RE = re.compile(
    r"^\s*(?:[\w.]+:\s*)?(?:network kill switch is active|airplane mode is engaged: refusing a network connection)\b"
    r"|^\s*request error for \S+: .*Failed to establish a new connection: airplane mode is engaged: refusing a network connection"
    r"|^\s*cannot resolve host (?:'[^'\s\\]*'|\"[^\"\s\\]*\"): airplane mode is engaged: refusing a network connection",
    re.IGNORECASE | re.DOTALL,
)


@pytest.fixture(autouse=True)
def _switch_clear():
    was = kill_switch_active()
    clear_kill_switch()
    yield
    (activate_kill_switch if was else clear_kill_switch)()


def _string_constants(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def test_the_constants_say_what_the_sentence_always_said():
    assert KILL_SWITCH_REFUSAL == "network kill switch is active -- collection stopped by operator"
    assert KILL_SWITCH_REFUSAL.startswith(KILL_SWITCH_REFUSAL_HEAD) and KILL_SWITCH_REFUSAL_HEAD == "network kill switch is active"
    assert is_kill_switch_refusal(KILL_SWITCH_REFUSAL) and classify_fetch_failure(KILL_SWITCH_REFUSAL) == "offline"


def test_no_other_file_under_src_spells_the_sentence_out():
    """A literal copy of the sentence is where the drift would start. The AST read sees code, not the comments and docstrings that quote it."""
    holders = sorted(
        str(path.relative_to(_SRC.parent)).replace("\\", "/")
        for path in _SRC.rglob("*.py")
        if any(_TAIL in value for value in _string_constants(path))
    )
    assert holders == [_DEFINITION], f"the refusal sentence is spelled out outside its definition: {holders}"


@pytest.mark.parametrize("relative", ["src/ingest/__init__.py", "src/safety/fetcher.py", "src/law/track.py"])
def test_the_writers_and_the_law_tracker_hold_no_copy_of_the_opening_words(relative):
    spelled = [v for v in _string_constants(_SRC.parent / relative) if "kill switch is active" in v]
    assert spelled == [], f"{relative} spells the refusal's opening words out instead of saying the constant: {spelled}"


def test_every_raise_site_raises_the_constant_and_the_reader_reads_it():
    """Each writer is DRIVEN with the switch engaged (the sites are not the same code path), not matched by name."""
    from src.safety.fetcher import GuardedSession, NetworkBlocked

    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0)
    activate_kill_switch()
    raised: dict[str, BaseException] = {}
    for label, call, kind in (
        ("fetch", lambda: f.fetch("https://h.test/a"), FetchFailed),
        ("declared_sitemaps", lambda: f.declared_sitemaps("https://h.test/a"), FetchFailed),
        ("_guard_target", lambda: f._guard_target("h.test"), FetchFailed),
        ("_guarded_redirect_get", lambda: f._guarded_redirect_get("https://h.test/robots.txt"), FetchFailed),
        ("GuardedSession.request", lambda: GuardedSession().get("https://h.test/a"), NetworkBlocked),
    ):
        with pytest.raises(kind) as caught:
            call()
        raised[label] = caught.value
    for label, exc in raised.items():
        assert str(exc) == KILL_SWITCH_REFUSAL, label
        assert is_kill_switch_refusal(str(exc)) and classify_fetch_failure(str(exc)) == "offline", label


def test_the_robots_read_site_raises_the_constant_when_the_switch_cuts_the_read(tmp_path):
    """The fifth FetchFailed site (R297), reached only when the switch is set after the earlier checks passed."""
    from urllib.parse import urlparse

    import requests

    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, robots_cache_path=tmp_path / "robots.json")
    f._guard_target = lambda host: None  # type: ignore[method-assign]

    def cut_off(url, **_kw):
        activate_kill_switch()
        raise requests.ConnectionError("cut")

    f._guarded_redirect_get = cut_off  # type: ignore[method-assign]
    with pytest.raises(FetchFailed) as caught:
        f._get_robots("https://h.test", urlparse("https://h.test/a"))
    assert str(caught.value) == KILL_SWITCH_REFUSAL


def test_the_reader_is_built_from_the_head_and_accepts_exactly_what_it_accepted():
    assert re.escape(KILL_SWITCH_REFUSAL_HEAD) in fetch_verdict._OFFLINE_RE.pattern
    corpus = [
        KILL_SWITCH_REFUSAL,
        "FetchFailed: " + KILL_SWITCH_REFUSAL,
        "  " + KILL_SWITCH_REFUSAL,
        "NETWORK KILL SWITCH IS ACTIVE -- collection stopped",
        "network kill switch is active",
        "network kill switch is active (airplane mode) -- a download was refused",
        "network kill switch is activated",
        "the network kill switch is active",
        "xnetwork kill switch is active",
        "HTTP 503 for https://h.test/a (server said: " + KILL_SWITCH_REFUSAL + ")",
        "redirect to unsupported URL: 'ftp://h.test/" + KILL_SWITCH_REFUSAL + "'",
        "airplane mode is engaged: refusing a network connection to 'h.test'. No packet leaves the machine while offline",
        "request error for https://h.test/a: HTTPSConnectionPool(host='h.test'): Failed to establish a new connection: "
        "airplane mode is engaged: refusing a network connection to 'h.test'",
        "cannot resolve host 'h.test': airplane mode is engaged: refusing a network connection to 'h.test'",
        "cannot resolve host 'a b': airplane mode is engaged: refusing a network connection to 'a b'",
        "cannot resolve host 'h.test': [Errno -2] Name or service not known",
        "HTTPSConnectionPool(host='a.example', port=443): Max retries exceeded with url: /robots.txt (Caused by NewConnectionError(...))",
        _PROXY_SHAPED_STOP,
        "",
        "the kill switch of the CDN fired",
    ]
    assert len(corpus) == 20
    for text in corpus:
        assert bool(fetch_verdict._OFFLINE_RE.match(text)) == bool(_OLD_OFFLINE_RE.match(text)), text
    assert fetch_verdict._OFFLINE_RE.flags == _OLD_OFFLINE_RE.flags


def test_a_stop_through_an_http_proxy_is_not_widened_into_a_match():
    """R320: a Stop through an HTTP proxy reaches a caller as a requests error wrapping the guard's sentence in a ``ConnectionError`` tuple.
    That is the wrapped shape the start anchor (R298) exists to refuse, so the reader does NOT recognise it; the callers that can meet it
    read ``kill_switch_active()`` after each check instead. Building the first alternative from a constant must not change that."""
    assert not is_kill_switch_refusal(_PROXY_SHAPED_STOP)
    assert classify_fetch_failure(_PROXY_SHAPED_STOP) != "offline"
    assert not fetch_verdict._OFFLINE_RE.match(_PROXY_SHAPED_STOP)

