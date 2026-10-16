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
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import requests
from urllib3.util import parse_url

from src.ingest import DEFAULT_USER_AGENT, BlockedTarget, EthicalFetcher, kill_switch_active
from src.monitoring.secret_scrub import record_text
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


#: The refusal when the stored transport choice could not be READ (a locked, damaged or vanished store): the user's setting is
#: unknown, not absent, so nothing is sent until it reads again. Not "no proxy is configured": the store is the problem.
READ_FAILED_REFUSAL = (
    "the stored safety settings could not be read, so this request was refused instead of being sent directly "
    "(nothing leaves until they can be read again)"
)


class RedirectRefused(requests.exceptions.RequestException):
    """A request, or one hop of a redirect chain, aimed somewhere a session with a host list may not go.

    A ``RequestException`` so every caller that already handles "this request failed" handles it, and NOT a ``ConnectionError``: nothing
    was sent, and a retry sends the same refused request again. ``reason`` is one of the fixed sentences below, never the URL or the
    host: the address comes from a server's ``Location`` header (the text of whoever answered), so it is not echoed into a log line,
    a record or a message."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"request refused: {reason}")
        self.reason = reason


#: What a fetch through a guarded session raises when it fails for a reason of its own (as opposed to a refusal): a ``requests`` failure
#: (a server error, a dropped connection, a timeout, a redirect loop) or the ``ValueError`` that ``requests`` and urllib3 raise for an
#: address or a ``Location`` they cannot read. The refusals (:class:`RedirectRefused`, :class:`TransportUnavailable`, :class:`NetworkBlocked`)
#: are named before this tuple wherever it is caught.
FETCH_FAILURES: tuple[type[BaseException], ...] = (requests.exceptions.RequestException, ValueError)


def failure_words(exc: BaseException) -> str:
    """The only words of a failed fetch that may reach a response, a log line or a record: ``HTTP <status>`` for an HTTP error answer,
    otherwise the exception's CLASS NAME, never its text. The text of a ``requests`` failure quotes the address it was fetching, query
    included, and a signed storage URL carries its signature there."""
    response = getattr(exc, "response", None) if isinstance(exc, requests.exceptions.HTTPError) else None
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        return f"HTTP {status}"
    return type(exc).__name__


def _listable(entry: str) -> bool:
    """Whether ``entry`` is a host name or a leading-dot suffix a list may hold: lower-case ASCII labels (letters, digits, hyphens
    inside a label), at least two of them (a single label is a whole TLD, or no domain at all), no empty label (so no trailing dot and
    no double dot) and a last label that is not all digits (an address is not a name). It does NOT consult the public suffix list, so
    ``.co.uk`` passes: the lists are constants a reader approves, not input."""
    body = entry[1:] if entry.startswith(".") else entry
    labels = body.split(".")
    return (
        entry == entry.lower()
        and len(labels) >= 2
        and not labels[-1].isdigit()
        and all(
            label and not label.startswith("-") and not label.endswith("-") and all(c.isascii() and (c.isalnum() or c == "-") for c in label)
            for label in labels
        )
    )


def _checked_hosts(allowed: Iterable[str] | None) -> tuple[str, ...] | None:
    """A host list as the session stores it, or ``None`` for no policy. Each entry is a host (``ores.wikimedia.org``) or a leading-dot
    suffix (``.wikipedia.org``: any host UNDER it, never the bare domain). A malformed entry is a programming error and raises
    (:func:`_listable`), as does an empty list, which would refuse every request (say ``None`` for a session that follows no list), and a
    bare string, which would otherwise be read as one entry per character."""
    if allowed is None:
        return None
    if isinstance(allowed, str):
        raise TypeError("a host list is a sequence of hosts, not one string")
    hosts = tuple(allowed)
    if not hosts:
        raise ValueError("an empty host list would refuse every request; pass None for a session with no list")
    for entry in hosts:
        if not _listable(entry):
            raise ValueError(f"not a host or a leading-dot suffix: {entry!r}")
    return hosts


def _host_listed(host: str, allowed: tuple[str, ...]) -> bool:
    for entry in allowed:
        if entry.startswith("."):
            if host.endswith(entry) and len(host) > len(entry):  # any host UNDER the domain: not the domain, not an empty label
                return True
        elif host == entry:
            return True
    return False


def refuse_unlisted_host(url: str, allowed: tuple[str, ...]) -> None:
    """Raise :class:`RedirectRefused` unless ``url`` is an https URL to a listed host, on port 443, with no user name.

    The URL is read BOTH ways it can be read, and each reading has to pass: by ``urllib3`` (``parse_url``) and by ``urlparse``.
    ``requests`` 2.32.2 and later makes the connection to the host ``urlparse`` reads (``adapters._urllib3_request_context``) and the
    older releases ``pyproject`` still allows to the one ``urllib3`` reads, so a list compared with only one of them would be a list
    for whichever client version it was written against. ``EthicalFetcher._refuse_parser_mismatch`` runs first and refuses outright a
    URL the two read differently (a backslash or whitespace in the authority, a ``%`` in the host, two readings of one name), which
    also names the cause. The scheme, user-information, port and host comparisons below do not rely on that call staying in place; the
    refusals of a ``%`` in the host and of a host that cannot be IDNA-encoded do, and exist only there. A user name or password, a port other
    than 443 and a scheme other than https are refused too: no endpoint a session with a list talks to redirects there, so a hop that
    does is not one of its own. ``allowed`` holds hosts and leading-dot suffixes (:func:`_checked_hosts`)."""
    try:
        EthicalFetcher._refuse_parser_mismatch(url)
    except BlockedTarget as exc:
        raise RedirectRefused(str(exc)) from None  # a fixed sentence of that function, never the URL
    by_urllib3 = parse_url(url)
    try:
        by_urlparse = urlparse(url)
        urlparse_host, urlparse_port = by_urlparse.hostname or "", by_urlparse.port
    except ValueError:
        raise RedirectRefused("the URL cannot be read") from None
    if (by_urllib3.scheme or "").lower() != "https" or by_urlparse.scheme.lower() != "https":
        raise RedirectRefused("the scheme is not https")
    if by_urllib3.auth or "@" in by_urlparse.netloc:
        raise RedirectRefused("the URL carries a user name or a password")
    if by_urllib3.port not in (None, 443) or urlparse_port not in (None, 443):
        raise RedirectRefused("the URL names a port other than 443")
    # Both readings are lower-case already (urllib3 lower-cases; urlparse's ``hostname`` does too).
    if not (_host_listed(by_urllib3.host or "", allowed) and _host_listed(urlparse_host, allowed)):
        raise RedirectRefused("the host is not one this client talks to")


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
    #: The hosts this session may talk to (:func:`_checked_hosts`), or ``None`` for no list, which is every session built without
    #: one. Checked in :meth:`send`, the method ``requests`` itself calls for the first request AND for each redirect hop
    #: (``resolve_redirects`` calls ``self.send``, not ``self.request``), so a hop to another host is refused before it is sent.
    #: (:meth:`request`'s own checks run once, on the first URL: ``requests`` carries the per-request proxy mapping onto each hop, and
    #: the airplane socket guard stands under both, but nothing there looks at WHERE a hop goes.)
    allowed_hosts: tuple[str, ...] | None = None

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

    def send(self, request, **kwargs) -> requests.Response:  # type: ignore[override]
        if self.allowed_hosts is not None:
            refuse_unlisted_host(request.url or "", self.allowed_hosts)
        return super().send(request, **kwargs)

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
    if getattr(settings, "read_failed", False):
        return None, (), READ_FAILED_REFUSAL
    # ``getattr``: a stand-in settings object without the field has no pool, which is
    # the reading that cannot widen what a session reaches.
    pool = tuple(getattr(settings, "http_proxies", None) or ())
    if pool:
        try:
            validate_socks_pool(list(pool))
        except ValueError as exc:
            return None, (), record_text(exc)
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
    if getattr(settings, "read_failed", False):
        return {"kind": "unknown", "reason": "unreadable"}  # the UI's own "settings could not be read" line
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
    allowed_hosts: Iterable[str] | None = None,
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

    ``allowed_hosts`` gives the session a list of the hosts it may talk to (hosts and
    leading-dot suffixes, :func:`_checked_hosts`): a request, or a redirect hop, to any
    other host is refused with :class:`RedirectRefused` before it is sent. Omitted -- the
    default, and every existing caller -- the session follows no list, as before.
    """
    return _session_for(
        load_settings(),
        user_agent=user_agent,
        isolation_token=isolation_token,
        egress_purpose=egress_purpose,
        allowed_hosts=allowed_hosts,
    )


def _session_for(
    settings: SafetySettings,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    isolation_token: str | None = None,
    egress_purpose: str | None = None,
    allowed_hosts: Iterable[str] | None = None,
) -> GuardedSession:
    """``guarded_session`` built from the settings ``settings`` and no other read: a caller that keys a cache on a snapshot builds the
    session from that same snapshot, or a setting that flips between two reads caches a session of one transport under the key of
    the other."""
    s = GuardedSession()
    s.egress_purpose = egress_purpose
    s.allowed_hosts = _checked_hosts(allowed_hosts)  # before the early return below: the list holds in transparent mode too
    s.headers["User-Agent"] = user_agent
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
_FOLLOWING: dict[str, tuple[tuple[Any, ...], Any]] = {}


def _transport_key(s: SafetySettings) -> tuple[Any, ...]:
    """Everything ``_fetcher_for`` reads from the settings, and nothing else."""
    return (bool(s.is_protected), s.http_proxy, tuple(getattr(s, "http_proxies", None) or ()), bool(getattr(s, "read_failed", False)))


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
        if getattr(s, "read_failed", False) and held is not None:
            return held[1]  # the setting could not be read: keep the transport this was built with, never a direct one
        if held is None or held[0] != key:
            held = (key, _fetcher_for(s))
            _FOLLOWING[owner] = held
        return held[1]


def following_session(owner: str, user_agent: str, *, allowed_hosts: Iterable[str] | None = None) -> GuardedSession:
    """The long-lived guarded session of one API client, rebuilt whenever the transport changes (``following_fetcher``'s twin for the
    clients that talk to a service's API and follow its own etiquette instead of ``robots.txt``: the MediaWiki and ORES clients).

    ``guarded_session`` decides the transport once, when it is built, so a client that keeps its session keeps the transport it was
    built with: a switch to protected mode in Settings would reach it only after a restart. Build it on first use (never at import:
    it reads the settings store) and ask here for it on every request.

    ``allowed_hosts`` is the client's host list (``guarded_session``); it is part of the key, so a session built with another list is
    another session."""
    s = load_settings()
    hosts = _checked_hosts(allowed_hosts)
    key = (*_transport_key(s), hosts, user_agent)
    name = f"session/{owner}"
    with _FOLLOWING_LOCK:
        held = _FOLLOWING.get(name)
        if getattr(s, "read_failed", False) and held is not None and held[0][-1] == user_agent and held[0][-2] == hosts:
            return held[1]  # the setting could not be read: keep the transport this was built with, never a direct one
        if held is None or held[0] != key:
            held = (key, _session_for(s, user_agent=user_agent, allowed_hosts=hosts))
            _FOLLOWING[name] = held
        return held[1]
