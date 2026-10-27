"""A refusal is recognised by OUR sentence at the start of the text, never by a phrase anywhere in a remote party's text (ruling R298).

Three places used to search the lowercased failure text for the words "kill switch": ``fetch_verdict.classify_fetch_failure`` (the collector's
``ff:offline`` and the "skipped_offline" counts), ``markets.csv_feeds.classify_fetch_failure`` (markets and weather) and the
``/api/monitoring/health`` summary. A real 503, a redirect target or a status line that happened to contain the words was then read as the
person's airplane mode. They now share ``is_kill_switch_refusal``; the controls below carry the phrase INSIDE a real failure.
"""

from __future__ import annotations

import pytest

from src.ingest import FetchFailed, activate_kill_switch, clear_kill_switch, kill_switch_active
from src.ingest.fetch_verdict import is_kill_switch_refusal
from src.markets.csv_feeds import classify_fetch_failure as markets_verdict

_BARE = "network kill switch is active -- collection stopped by operator"
_SOCKET = "airplane mode is engaged: refusing a network connection to 'h.test'. No packet leaves the machine while offline"


@pytest.mark.parametrize(
    "text",
    [
        _BARE,
        "FetchFailed: " + _BARE,
        _SOCKET,
        # repr writes a host holding a single quote in double quotes
        "cannot resolve host \"a'b\": " + _SOCKET,
    ],
)
def test_our_own_sentences_are_refusals(text):
    assert is_kill_switch_refusal(text)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "HTTP 503 for https://h.test/a (server said: " + _BARE + ")",
        "HTTP 503 for https://h.test/a (server said: " + _SOCKET + ")",
        "redirect to unsupported URL: 'ftp://h.test/" + _BARE + "'",
        "the kill switch of the CDN fired",
        # The resolver wrapper's own shape (R300): anything between the host and our sentence, a lookalike, or the whole wrapped text quoted
        # INSIDE another failure is not a refusal.
        "cannot resolve host 'h.test': [Errno -2] Name or service not known",
        "cannot resolve host 'h.test': [Errno -2] airplane mode is engaged: refusing a network connection to 'h.test'",
        "cannot resolve host 'a b': airplane mode is engaged: refusing a network connection to 'a b'",
        # An IPvFuture host that closes the quote early (repr escapes the inner quote with a backslash) and carries our words in its own name:
        # a real DNS failure of the HOST, found by the read of this change.
        "cannot resolve host 'v1.a\\': airplane mode is engaged: refusing a network connection \"': [Errno -2] Name or service not known",
        "HTTP 503 for https://h.test/a (server said: cannot resolve host 'h.test': " + _SOCKET + ")",
        "redirect to unsupported URL: 'ftp://h.test/cannot resolve host 'x': " + _SOCKET + "'",
    ],
)
def test_the_same_words_inside_a_remote_partys_text_are_not(text):
    assert not is_kill_switch_refusal(text)


def test_the_markets_classifier_reads_only_our_sentence():
    assert markets_verdict(FetchFailed(_BARE))[0] == "offline"
    assert markets_verdict(FetchFailed(_SOCKET))[0] == "offline"
    verdict = markets_verdict(
        FetchFailed("HTTP 503 for https://h.test/a (server said: " + _BARE + ")")
    )
    assert verdict[0] == "http-error" and verdict[2] is True, (
        "a real upstream error stays retryable"
    )


def test_the_health_summary_counts_only_a_real_refusal_as_refused(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api import monitoring
    from src.api.main import app
    from src.database.models import Base, Source
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'h.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as s:
        s.add_all(
            [
                Source(
                    name=f"S{i}",
                    domain=f"s{i}.test",
                    rss_url=f"https://s{i}.test/rss",
                    enabled=True,
                    priority=i,
                )
                for i in range(2)
            ]
        )
        s.commit()

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    class _Result:
        def __init__(self, detail):
            self._d = {
                "source_id": 1,
                "name": "s",
                "url": "https://h.test",
                "status": "down",
                "detail": detail,
            }

        def to_dict(self):
            return dict(self._d)

    details = iter([_BARE, "HTTP 503 for https://h.test (server said: " + _BARE + ")"])
    monkeypatch.setattr(monitoring, "check_source", lambda s, fetcher=None: _Result(next(details)))
    app.dependency_overrides[get_db] = _db
    was = kill_switch_active()
    activate_kill_switch()
    try:
        with TestClient(app, base_url="http://127.0.0.1") as c:
            body = c.get(
                "/api/monitoring/health?limit=2",
                headers={
                    "Sec-Fetch-Site": "same-origin",
                    "Referer": "http://127.0.0.1/",
                    "Origin": "http://127.0.0.1",
                },
            ).json()
    finally:
        (activate_kill_switch if was else clear_kill_switch)()
        app.dependency_overrides.clear()
        engine.dispose()
    assert body["checked"] == 2 and body["summary"] == {"refused_by_kill_switch": 1, "down": 1}


def test_the_resolver_wrapped_refusal_is_built_by_the_real_resolve_path_and_recognised():
    """Drift pin (R300): the text is what ``EthicalFetcher._resolve_cached`` really raises when the switch is engaged BETWEEN the pre-fetch
    check and the lookup (the guard's own ``AirplaneModeError``, wrapped by OUR "cannot resolve host" sentence), not a hand-copied string.
    It must read as the person's airplane mode and not as a DNS failure of the host."""
    from src.ingest import EthicalFetcher
    from src.ingest.airplane import install_airplane_socket_guard, uninstall_airplane_socket_guard
    from src.ingest.fetch_verdict import classify_fetch_failure

    was = kill_switch_active()
    install_airplane_socket_guard()
    activate_kill_switch()
    try:
        fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0)
        with pytest.raises(FetchFailed) as caught:
            fetcher._resolve_cached("h.test")
    finally:
        (activate_kill_switch if was else clear_kill_switch)()
        uninstall_airplane_socket_guard()
    text = str(caught.value)
    assert text.startswith("cannot resolve host 'h.test': airplane mode is engaged"), text
    assert is_kill_switch_refusal(text)
    assert classify_fetch_failure(text) == "offline"
    assert classify_fetch_failure("cannot resolve host 'h.test': [Errno -2] Name or service not known") == "dns"


def test_a_hostile_host_cannot_close_the_quote_early_and_speak_in_our_words():
    """The read of this change reproduced it end to end: ``http://[v1.a': airplane mode is engaged: refusing a network connection "]/x``
    reaches ``_guard_target`` (a redirect's Location is looked up BEFORE the parser-mismatch check), and the REAL text it raises must stay a
    DNS failure of the host."""
    from urllib.parse import urlparse

    from src.ingest import EthicalFetcher
    from src.ingest.fetch_verdict import classify_fetch_failure

    url = "http://[v1.a': airplane mode is engaged: refusing a network connection \"]/x"
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0)
    with pytest.raises(FetchFailed) as caught:
        fetcher._guard_target(urlparse(url).hostname)
    text = str(caught.value)
    assert text.startswith("cannot resolve host "), text
    assert not is_kill_switch_refusal(text)
    assert classify_fetch_failure(text) == "dns"
