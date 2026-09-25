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
import threading
from typing import Any
from urllib.parse import urlparse

import requests

from src.ingest import DEFAULT_USER_AGENT, EthicalFetcher, kill_switch_active
from src.safety.settings import GENERIC_USER_AGENT, SafetySettings, load_settings

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


class TransportUnavailable(requests.exceptions.ConnectionError):
    """Protected fetch mode is on and no usable proxy is configured, so the request is
    refused instead of being sent directly.

    A ``ConnectionError`` on purpose. Every caller already handles "the proxy did not
    answer": the wiki stream backs off and retries, a download pauses, a fetch records a
    transport error, and none of them falls back to a direct connection. This is the same
    situation one step earlier, so it takes the same road, with a message that names it.
    It is NOT a ``NetworkBlocked``: that is the operator's own airplane switch, and a
    caller that reported this as airplane mode would name the wrong cause.
    """


#: The refusal when protected mode has nothing to route through. ``save_settings``
#: refuses to store that state, but ``OO_FETCH_MODE=protected`` with no proxy variable,
#: or a hand-edited settings file, still reaches it, and it must never mean "direct".
NO_PROXY_REFUSAL = (
    "protected fetch mode is on but no proxy is configured, so this request was refused "
    "instead of being sent directly (a lane never downgrades Tor -> clearnet)"
)


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

    #: The egress-window purpose this session is allowed to ride, or ``None``.
    #:
    #: OPT-IN, and per-session by construction: a session built without naming a
    #: purpose keeps the OLD, absolute refusal, so an open window can never widen
    #: the dumps / wiki / ORES / DuckDuckGo sessions by accident. Only the two
    #: call sites that ARE the AI install (the Ollama installer's resolve + fetch)
    #: pass one.
    egress_purpose: str | None = None

    #: The operator's SOCKS pool, when protected mode uses one (C10). Each request's host
    #: is sharded onto ONE member at send time -- the mapping ``EthicalFetcher`` uses, so a
    #: host reaches the same endpoint whichever of the two paths fetches it.
    proxy_pool: tuple[str, ...] = ()
    #: The caller's stream-isolation token, layered on the sharded member per request.
    isolation_token: str | None = None
    #: The single proxy (isolation already layered on) when protected mode uses one.
    transport_proxy: str | None = None
    #: Set when protected mode has no usable proxy: every request is refused with it.
    transport_refusal: str | None = None

    def request(self, method, url, *args, **kwargs) -> requests.Response:  # type: ignore[override]
        # NOTE for anyone writing a test here: this reads the MODULE-LEVEL
        # ``kill_switch_active`` imported at the top of this file, while
        # ``egress_permitted`` re-imports it from ``src.ingest`` per call. Both
        # read the same Event in production, so they never disagree -- but
        # monkeypatching only THIS module's binding to fake airplane mode makes
        # the two disagree, and the refusal below silently stops being tested.
        # Engage the real switch (``activate_kill_switch()``) instead.
        if kill_switch_active():
            from src.ingest.egress_window import egress_permitted, socket_exemption

            if not egress_permitted(self.egress_purpose):
                raise NetworkBlocked(
                    "network kill switch is active -- collection stopped by operator"
                )
            # The kill switch is engaged and a live window covers this session's
            # purpose, so THIS request is the consented egress -- and it is the
            # only thing the socket-level airplane backstop should stand aside
            # for. Lifting it HERE rather than at the call sites is what makes the
            # two gates impossible to hold apart: a session cannot opt into the
            # app-level exemption and forget the socket one, or vice versa, and no
            # other thread is affected for even an instant.
            with socket_exemption():
                return self._send(method, url, *args, **kwargs)
        return self._send(method, url, *args, **kwargs)

    def _send(self, method, url, *args, **kwargs) -> requests.Response:
        """The transport decision, taken AFTER the kill switch: airplane mode is the
        operator's own switch and is named as that, whatever the transport would have been.
        """
        if self.transport_refusal is not None:
            raise TransportUnavailable(self.transport_refusal)
        # EXPLICIT, PER REQUEST, never only ``self.proxies``: requests folds the
        # ``HTTP(S)_PROXY`` / ``ALL_PROXY`` environment into the REQUEST's mapping and
        # lets that win over the session's (``Session.merge_environment_settings``), so a
        # system proxy variable silently replaced the operator's Tor proxy on every
        # session this module built. A per-request mapping is merged the other way: the
        # environment only fills keys it lacks. ``proxies={}`` counts as absent.
        if not kwargs.get("proxies"):
            if self.proxy_pool:
                kwargs["proxies"] = _pool_proxies(url, self.proxy_pool, self.isolation_token)
            elif self.transport_proxy:
                kwargs["proxies"] = {"http": self.transport_proxy, "https": self.transport_proxy}
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


def _pool_proxies(url: str, pool: tuple[str, ...], token: str | None) -> dict[str, str]:
    """The proxies one request to ``url`` uses under a pool: its host's sharded member,
    with the caller's stream-isolation token layered on (``_with_stream_isolation``)."""
    host = urlparse(url).hostname or ""
    member = _with_stream_isolation(shard_host_to_proxy(host, list(pool)), token)
    return {"http": member, "https": member}


def _protected_transport(settings: SafetySettings) -> tuple[str | None, tuple[str, ...], str | None]:
    """``(proxy, pool, refusal)`` for protected mode, the ONE reading both factories use.

    The pool when one is set (it takes precedence, as C10 ruled), else the single proxy,
    else a refusal. A pool with a non-SOCKS member is refused WHOLE, as ``save_settings``
    refuses to store one: "all-Tor or refused", never a per-host downgrade.

    Before 2026-09-25 ``guarded_session`` read ``http_proxy`` alone, so protected mode with
    only a pool -- a configuration ``save_settings`` accepts -- sent every session this
    module builds (the MediaWiki API and its stream, dumps, ORES, OSM downloads, official
    statistics, DuckDuckGo discovery, the AI installer) out directly while articles went
    through the pool.
    """
    # ``getattr``: a stand-in settings object without the field has no pool, which is
    # the reading that cannot widen what a session reaches.
    pool = tuple(getattr(settings, "http_proxies", None) or ())
    if pool:
        try:
            validate_socks_pool(list(pool))
        except ValueError as exc:
            return None, (), str(exc)
        return None, pool, None
    if settings.http_proxy:
        return settings.http_proxy, (), None
    return None, (), NO_PROXY_REFUSAL


def transport_summary(settings: SafetySettings) -> dict[str, Any]:
    """How a fetch through this module leaves the machine, as one token for the UI.

    ``kind`` is ``direct`` (protected mode off: any stored proxy is NOT used),
    ``proxy`` (one proxy), ``pool`` (a SOCKS pool, one member per host) or ``refused``
    (protected mode with no usable proxy: nothing is sent). S04-08's S5 (Q1014) puts
    this on every lane of the consent popup, and it is read through
    :func:`_protected_transport` -- the same reading both factories make -- so the
    popup cannot describe a transport the fetch path would not use. The popup used to
    derive it from ``http_proxy`` alone and said "fetches ride the proxy you
    configured" in transparent mode, where that proxy is ignored.

    The token carries no address of its own. A refusal's ``reason`` is a CODE
    (``no-proxy``, or ``pool-not-socks`` for a pool refused whole), never the refusal's
    text: that text comes from an exception and quotes the stored entry it refused, and
    the popup draws its own translated sentence for each kind anyway.
    """
    if not settings.is_protected:
        return {"kind": "direct"}
    _single, pool, refusal = _protected_transport(settings)
    if refusal is not None:
        return {"kind": "refused", "reason": "no-proxy" if refusal == NO_PROXY_REFUSAL else "pool-not-socks"}
    if pool:
        return {"kind": "pool", "members": len(pool)}
    return {"kind": "proxy"}


def guarded_session(
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    isolation_token: str | None = None,
    egress_purpose: str | None = None,
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

    ``egress_purpose`` opts THIS session into an operator-consented egress window
    (``src.ingest.egress_window``). Omitted -- the default, and every existing
    caller -- the session refuses under the kill switch exactly as before.
    """
    s = GuardedSession()
    s.egress_purpose = egress_purpose
    s.headers["User-Agent"] = user_agent
    settings = load_settings()
    if not settings.is_protected:
        return s
    proxy, pool, refusal = _protected_transport(settings)
    if refusal is not None:
        s.transport_refusal = refusal
    elif pool:
        # Each request shards its own host (``GuardedSession._send``). ``s.proxies`` is
        # set for anything that reads it; it is a pool member, never what decides.
        s.proxy_pool = pool
        s.isolation_token = isolation_token
        first = _with_stream_isolation(pool[0], isolation_token)
        s.proxies = {"http": first, "https": first}
    elif proxy:
        proxy = _with_stream_isolation(proxy, isolation_token)
        s.transport_proxy = proxy
        s.proxies = {"http": proxy, "https": proxy}
    return s


def make_fetcher(**overrides) -> EthicalFetcher:
    """Build an EthicalFetcher per the current safety settings.

    ``overrides`` (e.g. ``session=...`` for tests) pass straight through.

    C10: when the operator has configured a proxy POOL (``http_proxies``,
    protected mode only), it takes precedence over the single ``http_proxy`` --
    each host shards onto ONE pool member (``EthicalFetcher`` does the actual
    per-fetch sharding, since it needs the per-URL host). ``save_settings``
    already refuses a pool containing a non-SOCKS entry; ``_protected_transport``
    refuses one again here, by name, and ``EthicalFetcher`` re-validates at
    construction (the pool may be an older/hand-edited persisted file that
    predates that validation).

    Protected mode with no proxy at all raises :class:`TransportUnavailable`
    rather than returning a fetcher that would connect directly.
    """
    return _fetcher_for(load_settings(), **overrides)


def _fetcher_for(s: SafetySettings, **overrides) -> EthicalFetcher:
    """``make_fetcher`` for a settings object already read, so ``following_fetcher`` builds
    from the same reading it keys its cache on."""
    user_agent = GENERIC_USER_AGENT if s.is_protected else DEFAULT_USER_AGENT
    proxy: str | None = None
    proxy_pool: list[str] | None = None
    if s.is_protected:
        single, pool, refusal = _protected_transport(s)
        if refusal is not None:
            # Refused at construction, by name: an EthicalFetcher with no proxy would
            # fetch directly, and the caller (a pass, an endpoint) surfaces the message.
            raise TransportUnavailable(refusal)
        proxy_pool = list(pool) or None
        proxy = single
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
    # The wall-clock bound on one body read (a tarpit refusal); the class default is ten
    # timeouts and never under two minutes, so only an operator who wants otherwise sets it.
    if os.getenv("OO_FETCH_BODY_DEADLINE"):
        params["body_deadline_s"] = float(os.environ["OO_FETCH_BODY_DEADLINE"])
    params.update(overrides)
    return EthicalFetcher(**params)


# --------------------------------------------------------------------------- #
# A long-lived fetcher that follows the transport setting
# --------------------------------------------------------------------------- #
_FOLLOWING_LOCK = threading.Lock()
_FOLLOWING: dict[str, tuple[tuple[Any, ...], EthicalFetcher]] = {}


def _transport_key(s: SafetySettings) -> tuple[Any, ...]:
    """Everything ``_fetcher_for`` reads from the settings, and nothing else."""
    return (bool(s.is_protected), s.http_proxy, tuple(getattr(s, "http_proxies", None) or ()))


def following_fetcher(owner: str) -> EthicalFetcher:
    """The long-lived fetcher for one API module, rebuilt whenever the transport changes.

    ``src.api.markets``, ``src.api.hazards`` and ``src.api.ingestion`` each built one
    ``make_fetcher()`` at IMPORT time and kept it for the life of the process. Import
    happens before the operator unlocks an encrypted store, when the stored safety
    settings cannot be read and load from the pre-migration ``safety_settings.json``
    if one survives, or as their defaults. So on an encrypted install whose protected
    mode was saved in Settings, those three fetched directly, with the bot User-Agent,
    unless an older settings file happened to carry the same choice; and on any
    install, a switch to protected mode in Settings did not reach them before a
    restart. Found 2026-09-25.

    Kept long-lived rather than built per call so the in-memory politeness state (the
    per-host last-request stamps) survives between requests. A changed transport starts
    a fresh fetcher; the robots verdicts and the Crawl-delay schedule are persisted, so
    only the in-memory stamps are lost at that moment.
    """
    s = load_settings()
    key = _transport_key(s)
    with _FOLLOWING_LOCK:
        held = _FOLLOWING.get(owner)
        if held is None or held[0] != key:
            held = (key, _fetcher_for(s))
            _FOLLOWING[owner] = held
        return held[1]
