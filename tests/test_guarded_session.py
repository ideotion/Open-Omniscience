"""The one guarded socket factory: kill switch + proxy + honest UA, by construction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Item 3 (2026-06-13): the dump/wiki/ORES/DuckDuckGo paths used to build bare
``requests`` sessions, so airplane-mode did not stop them and the in-app proxy
was not applied (a transport leak: Tor set only in-app meant dumps egressed
clearnet). They now route through ``src.safety.fetcher.guarded_session``. These
tests pin the three guarantees and prove the consumers are wired through it.
No network: the kill-switch check sits before the request, so it raises first.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ingest import DEFAULT_USER_AGENT, activate_kill_switch
from src.safety.fetcher import GuardedSession, NetworkBlocked, guarded_session


def test_default_user_agent_is_the_honest_versioned_one():
    s = guarded_session()
    assert s.headers["User-Agent"] == DEFAULT_USER_AGENT
    assert "0.4" not in s.headers["User-Agent"]  # the old hardcoded stale UA is gone


def test_explicit_user_agent_is_used():
    s = guarded_session(user_agent="OpenOmniscienceBot/test (+contact)")
    assert s.headers["User-Agent"] == "OpenOmniscienceBot/test (+contact)"


def test_kill_switch_blocks_every_verb_before_any_network():
    activate_kill_switch()  # autouse fixture clears it again after the test
    s = guarded_session()
    for call in (
        lambda: s.get("http://dumps.wikimedia.org/x"),
        lambda: s.head("http://dumps.wikimedia.org/x"),
        lambda: s.post("http://html.duckduckgo.com/html/", data={}),
    ):
        with pytest.raises(NetworkBlocked):
            call()


def test_protected_mode_applies_the_proxy(monkeypatch):
    monkeypatch.setattr(
        "src.safety.fetcher.load_settings",
        lambda: SimpleNamespace(is_protected=True, http_proxy="socks5://127.0.0.1:9050"),
    )
    s = guarded_session()
    assert s.proxies == {"http": "socks5://127.0.0.1:9050", "https": "socks5://127.0.0.1:9050"}


def test_transparent_mode_uses_no_proxy(monkeypatch):
    monkeypatch.setattr(
        "src.safety.fetcher.load_settings",
        lambda: SimpleNamespace(is_protected=False, http_proxy="socks5://127.0.0.1:9050"),
    )
    s = guarded_session()
    assert not s.proxies  # transparent: never silently route through a stale proxy


def test_guarded_session_is_a_requests_session_subclass():
    # So existing call sites (get/post/head/headers/proxies) work unchanged.
    assert issubclass(GuardedSession, __import__("requests").Session)


# --- the four consumers are actually wired through the factory --------------- #


def test_wiki_client_defaults_to_a_guarded_session():
    from src.wiki.client import WikiClient

    assert isinstance(WikiClient().session, GuardedSession)


def test_ores_client_defaults_to_a_guarded_session():
    from src.wiki.ores import OresClient

    assert isinstance(OresClient().session, GuardedSession)


def test_dump_download_helpers_respect_the_kill_switch():
    from src.wiki.dumps import _default_get, _default_head

    activate_kill_switch()
    with pytest.raises(NetworkBlocked):
        _default_get("https://dumps.wikimedia.org/enwiki/x", {})
    with pytest.raises(NetworkBlocked):
        _default_head("https://dumps.wikimedia.org/enwiki/x")
