"""
Fetcher factory honouring the safety fetch-mode (transparent vs protected).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The single place that builds an :class:`~src.ingest.EthicalFetcher` from the user's safety
settings, so every ingest path (single URL, feeds, crawl, markets, law) goes through the
*same* protected/transparent decision. Protected mode routes through the user's proxy and
sends a generic User-Agent; the robots/rate-limit/SSRF guards are unchanged.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

import requests

from src.ingest import DEFAULT_USER_AGENT, EthicalFetcher, kill_switch_active
from src.safety.settings import GENERIC_USER_AGENT, load_settings

# The SOCKS proxy schemes requests[socks]/PySocks understand. Shared by the
# stream-isolation helper below and the C10 (2026-07-24 throughput brief)
# operator-run proxy POOL -- both need "is this actually a SOCKS proxy".
SOCKS_SCHEMES = ("socks5", "socks5h", "socks4", "socks4a")


def is_socks_proxy(proxy_url: str | None) -> bool:
    """PURE scheme check, no I/O. True for socks5/socks5h/socks4/socks4a."""
    if not proxy_url or "://" not in proxy_url:
        return False
    return proxy_url.split("://", 1)[0].lower() in SOCKS_SCHEMES


class NetworkBlocked(RuntimeError):
    """Raised by a guarded session when the global kill switch is engaged.

    Distinct, named, and honest: the operator turned the network off, so a new
    outbound request refuses rather than silently slipping past the switch.
    """


class GuardedSession(requests.Session):
    """A ``requests.Session`` that consults the global kill switch on EVERY verb.

    The non-EthicalFetcher network paths (Wikipedia dumps, the MediaWiki API
    client, ORES, the gated DuckDuckGo discovery) historically built their own
    bare ``requests`` sessions, so airplane-mode did NOT stop them and the
    in-app proxy was NOT applied (a transport leak: Tor set only in-app meant
    dumps egressed clearnet). Routing them through this one factory closes both
    gaps by construction -- the check sits in ``request()``, which every
    ``get``/``post``/``head`` funnels through, so it cannot be forgotten.
    """

    def request(self, method, url, *args, **kwargs) -> requests.Response:  # type: ignore[override]
        if kill_switch_active():
            raise NetworkBlocked(
                "network kill switch is active -- collection stopped by operator"
            )
        return super().request(method, url, *args, **kwargs)


def _with_stream_isolation(proxy_url: str, token: str | None) -> str:
    """For a SOCKS proxy, inject a per-stream username/password so Tor's
    ``IsolateSOCKSAuth`` (on by default) builds a SEPARATE circuit per token.

    Parallel downloads to the SAME host (e.g. several Wikipedia dumps) would
    otherwise share one Tor circuit and gain nothing; distinct SOCKS auth gives
    each its own circuit, so aggregate throughput actually multiplies over Tor.
    No-op for non-SOCKS proxies and when the caller already set credentials.
    """
    if not token or "://" not in proxy_url:
        return proxy_url
    scheme, rest = proxy_url.split("://", 1)
    if not is_socks_proxy(proxy_url):
        return proxy_url
    if "@" in rest:  # caller already chose credentials -- respect them
        return proxy_url
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", token)[:32] or "oo"
    return f"{scheme}://{safe}:{safe}@{rest}"


# --------------------------------------------------------------------------- #
# C10 (2026-07-24 throughput brief, §6b): an OPERATOR-RUN pool of SOCKS
# endpoints (e.g. several independent Tor instances on different ports/
# bridges) -- raising collect_parallelism (C9) without this hits the
# single-Tor-client ceiling first, since one Tor process serves every circuit
# regardless of how many worker threads request one. The app NEVER spawns or
# manages these processes; it only shards HOSTS across a list the operator
# already runs and trusts. "All-Tor or refused" -- never a downgrade: a single
# non-SOCKS entry would silently drop whichever hosts happen to shard onto it
# straight to clearnet, so the WHOLE pool is refused rather than partially
# honoured.
# --------------------------------------------------------------------------- #


def validate_socks_pool(proxies: list[str]) -> None:
    """Raise ``ValueError`` naming the first non-SOCKS entry -- never silently
    drop or partially apply a pool with a bad member (transport honesty)."""
    for p in proxies:
        if not is_socks_proxy(p):
            raise ValueError(
                f"proxy pool entry is not a SOCKS proxy (refused, no downgrade): {p!r}"
            )


def shard_host_to_proxy(host: str, proxies: list[str]) -> str:
    """Stable mapping of ``host`` to ONE pool member -- a host maps to the SAME
    endpoint (and, via ``_with_stream_isolation`` layered on top by the caller,
    the same dedicated circuit) for the LIFETIME of the app's configuration,
    not just one process. Uses a cryptographic hash, never Python's built-in
    ``hash()`` -- CPython randomises string hashing per process
    (``PYTHONHASHSEED``) by default, which would reshuffle every host's
    endpoint on every restart, defeating the whole point of a stable mapping.
    """
    if not proxies:
        raise ValueError("shard_host_to_proxy requires a non-empty proxy list")
    digest = hashlib.sha256(host.encode("utf-8", errors="replace")).digest()
    idx = int.from_bytes(digest[:8], "big") % len(proxies)
    return proxies[idx]


def guarded_session(
    *, user_agent: str = DEFAULT_USER_AGENT, isolation_token: str | None = None
) -> GuardedSession:
    """Build a kill-switch-aware session that honours the protected-mode proxy.

    Three guarantees, the same the EthicalFetcher gives article fetches:
      * the global kill switch refuses new requests (airplane mode is real);
      * protected mode routes through the user's proxy (e.g. Tor) -- transport
        is NEVER silently downgraded to clearnet (a §0.5 non-negotiable);
      * an explicit, honest User-Agent (callers pass the one their endpoint's
        policy requires -- e.g. Wikimedia's API mandates a descriptive bot UA,
        even over Tor, so a generic browser UA would be both dishonest and
        against policy; the DuckDuckGo HTML endpoint wants a browser UA).

    ``isolation_token`` requests a dedicated Tor circuit for this session (see
    ``_with_stream_isolation``) so parallel downloads to one host don't share a
    single slow circuit. robots/politeness for these specific API/dump endpoints
    follows each service's own etiquette (handled at the call sites), not generic
    crawl robots -- blanket-applying it would wrongly block legitimate API use.
    """
    s = GuardedSession()
    s.headers["User-Agent"] = user_agent
    settings = load_settings()
    proxy = settings.http_proxy if settings.is_protected else None
    if proxy:
        proxy = _with_stream_isolation(proxy, isolation_token)
        s.proxies = {"http": proxy, "https": proxy}
    return s


def make_fetcher(**overrides) -> EthicalFetcher:
    """Build an EthicalFetcher per the current safety settings.

    ``overrides`` (e.g. ``session=...`` for tests) pass straight through.

    C10: when the operator has configured a proxy POOL (``http_proxies``,
    protected mode only), it takes precedence over the single ``http_proxy`` --
    each host shards onto ONE pool member (``EthicalFetcher`` does the actual
    per-fetch sharding, since it needs the per-URL host). ``save_settings``
    already refuses a pool containing a non-SOCKS entry; ``EthicalFetcher``
    re-validates defensively at construction (the pool may be an older/
    hand-edited persisted file that predates that validation).
    """
    s = load_settings()
    user_agent = GENERIC_USER_AGENT if s.is_protected else DEFAULT_USER_AGENT
    proxy_pool = list(s.http_proxies) if (s.is_protected and s.http_proxies) else None
    proxy = (s.http_proxy or None) if (s.is_protected and not proxy_pool) else None
    params: dict[str, Any] = {
        "user_agent": user_agent,
        "min_interval_s": float(os.getenv("OO_FETCH_MIN_INTERVAL", "1.0")),
        "timeout": float(os.getenv("OO_FETCH_TIMEOUT", "30")),
        "proxy": proxy,
        "proxy_pool": proxy_pool,
        # Bounded retry/backoff for transient failures (finding BUG-02).
        "max_retries": int(os.getenv("OO_FETCH_MAX_RETRIES", "2")),
        "retry_backoff_s": float(os.getenv("OO_FETCH_RETRY_BACKOFF", "0.5")),
    }
    params.update(overrides)
    return EthicalFetcher(**params)
