"""
Ethical HTTP fetching: the single, mandatory fetch path for ingestion.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every byte the platform ingests goes through here. The guarantees (PRODUCT_SYNTHESIS
§3.4 "Ethical by construction", "Fail *closed*"):

  * robots.txt is honoured, per-host cached, and **fail-closed**: if we cannot
    positively determine that a URL is allowed (network error, timeout, 5xx, or a
    restricted 401/403 on robots.txt), we do NOT fetch it. This is the opposite of
    the old EthicalScraper, which assumed "allowed" on any error.
  * a per-host minimum request interval is enforced (honouring robots Crawl-delay
    when larger), so we never hammer a source.
  * an honest, identifying User-Agent is sent.
  * only HTML is returned for article ingestion; other content types are rejected.

There is exactly one network path and no raw-requests bypass.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from src.monitoring.activity import activity_monitor

_LOG = logging.getLogger(__name__)

try:  # Single source of truth is pyproject; never hardcode a version literal.
    _OO_VERSION = _pkg_version("open-omniscience")
except PackageNotFoundError:  # raw checkout / not installed -> honest fallback
    _OO_VERSION = "0.0.0"

# Public alias so other honest-UA builders (the wiki client, ORES, dumps) share
# the one version source instead of hardcoding a stale literal.
OO_VERSION = _OO_VERSION

DEFAULT_USER_AGENT = (
    f"OpenOmniscienceBot/{_OO_VERSION} (+https://github.com/ideotion/Open-Omniscience; "
    "ethical research crawler)"
)


@dataclass
class FetchResult:
    """A successfully fetched page with provenance.

    ``status_code`` may be 304 (Not Modified) when the caller passed
    conditional-GET headers and the resource is unchanged; in that case
    ``content`` is empty and the caller should reuse what it already has. ``etag``
    and ``last_modified`` carry the response's validators (when present) so the
    caller can persist them for the next conditional request.
    """

    requested_url: str
    final_url: str  # after redirects
    status_code: int
    content: str  # decoded HTML
    content_type: str
    fetched_at: datetime
    etag: str | None = None  # response ETag (opaque validator), if sent
    last_modified: str | None = None  # response Last-Modified, if sent
    # The server IP we actually connected to (data-architecture Slice 6a). It is OUR
    # VANTAGE POINT -- usually a CDN edge / anycast address, NOT the publisher's origin.
    # Available only on a DIRECT clearnet connection: over a SOCKS proxy / Tor the socket
    # connects to the proxy, not the server, so the real server IP is unavailable and
    # ``server_ip`` is None with a stated ``server_ip_reason`` -- never a guess.
    server_ip: str | None = None
    server_ip_reason: str | None = None  # why server_ip is None (honest, when unavailable)
    # The UNDECODED response bytes, attached ONLY when the caller passes
    # ``keep_bytes=True`` (default None ⇒ zero memory cost on the scrape hot path).
    # Needed for binary bodies (e.g. a PDF law) whose bytes are destroyed by the
    # text-decode path; already bounded by ``max_bytes``.
    raw_content: bytes | None = None


class FetchError(Exception):
    """Base class for all fetch failures (never silently swallowed)."""


class RobotsDisallowed(FetchError):
    """robots.txt explicitly disallows this URL for our user agent."""


class RobotsUnavailable(FetchError):
    """robots.txt could not be determined -> fail closed, do not fetch."""


class FetchFailed(FetchError):
    """The page itself could not be fetched, or was not usable HTML."""


class BlockedTarget(FetchFailed):
    """The URL (or a redirect of it) resolves to a non-public address (SSRF guard)."""


# How long a robots.txt decision is cached, in seconds.
_ROBOTS_TTL = 3600.0

# --------------------------------------------------------------------------- #
# A5 (2026-07-24 throughput brief, C4): persist the robots.txt verdict cache to
# a small local JSON sidecar so a cold start reuses in-TTL decisions instead of
# re-fetching robots.txt for every host. This is a SHARPER win than "across
# restarts" alone: make_fetcher() builds a brand-new EthicalFetcher (empty
# in-memory cache) once per COLLECTION PASS (see _default_run_once), so
# WITHOUT this the whole robots cache was already being thrown away every
# pass, not merely across a real app restart.
#
# Persisted as WALL-CLOCK time (time.time()), never the in-process MONOTONIC
# clock _get_robots stores internally (self._now = time.monotonic, whose
# epoch/reference point is arbitrary per process and platform) -- a raw
# monotonic value written by one process is meaningless read back by
# another. On load, the remaining TTL is recomputed from the wall-clock delta
# and re-expressed in the CURRENT instance's own monotonic frame.
# --------------------------------------------------------------------------- #
_ROBOTS_PERSIST_LOCK = threading.Lock()


def _robots_cache_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "robots_cache.json"


def _robots_persist_enabled() -> bool:
    return os.environ.get("OO_ROBOTS_CACHE_PERSIST", "1") != "0"


def _load_persisted_robots(
    path: Path, *, now_monotonic, now_wall: float | None = None
) -> dict[str, tuple[RobotFileParser | None, float]]:
    """Reconstruct ``{host_key: (RobotFileParser|None, monotonic_expiry)}`` from
    the persisted sidecar, DROPPING any entry whose wall-clock TTL has already
    lapsed -- an expired verdict must be re-fetched, never trusted stale (the
    fail-closed semantics are unchanged: a dropped/missing entry just means
    the next fetch recomputes it, exactly like a fresh process today)."""
    if not path.exists():
        return {}
    wall_now = now_wall if now_wall is not None else time.time()
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt sidecar must never break startup
        return {}
    out: dict[str, tuple[RobotFileParser | None, float]] = {}
    for host_key, entry in (raw or {}).items():
        try:
            fetched_at = float(entry["fetched_at"])
            kind = entry["kind"]
            remaining = _ROBOTS_TTL - (wall_now - fetched_at)
            if remaining <= 0:
                continue  # expired -- re-fetch, never trust stale (NEGATIVE-SPACE)
            decision: RobotFileParser | None
            if kind == "parsed":
                rp = RobotFileParser()
                rp.parse(str(entry.get("body") or "").splitlines())
                decision = rp
            elif kind == "allow_all":
                rp = RobotFileParser()
                rp.parse([])
                decision = rp
            elif kind == "disallow_all":
                decision = None
            else:
                continue  # unknown shape -- skip rather than guess
            out[host_key] = (decision, now_monotonic() + remaining)
        except Exception:  # noqa: BLE001 - one bad entry must never break the whole load
            continue
    return out


def _persist_robots_entry(path: Path, host_key: str, *, kind: str, body: str | None) -> None:
    """Best-effort: record ONE host's freshly-computed verdict in the persisted
    sidecar (read-modify-write, atomic temp+replace, lock-guarded against
    concurrent writers for different hosts). Never raises into the fetch path
    -- a write failure only means the next process/pass re-fetches this host,
    the SAME fail-closed fallback that already exists today."""
    try:
        with _ROBOTS_PERSIST_LOCK:
            raw: dict = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text("utf-8")) or {}
                except Exception:  # noqa: BLE001 - a corrupt sidecar starts fresh
                    raw = {}
            raw[host_key] = {"kind": kind, "body": body, "fetched_at": time.time()}
            # Bound the persisted file the SAME way the in-memory cache is bounded
            # (_ROBOTS_CACHE_MAX) -- oldest-fetched entries evicted first.
            if len(raw) > _ROBOTS_CACHE_MAX:
                ordered = sorted(raw.items(), key=lambda kv: kv[1].get("fetched_at", 0))
                raw = dict(ordered[-_ROBOTS_CACHE_MAX:])
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(raw), "utf-8")
            tmp.replace(path)
    except Exception:  # noqa: BLE001 - persistence is an optimisation, never required
        _LOG.debug("robots cache persistence failed for %s", host_key, exc_info=True)


def _env_cap(name: str, default: int, *, floor: int) -> int:
    """Parse a positive integer cap from the environment, defensively."""
    try:
        return max(floor, int(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        return default


# Per-pass host-cache bounds (P0.3 E1, field event 2026-07-09: a 21.6-hour
# marathon pass accumulated memory until the kernel OOM-killer fired). The
# robots cache holds a RobotFileParser (rule lists can be tens of KB for big
# sites) per host ever contacted; on a very wide crawl that grows for the whole
# pass. Bounding it costs at most a robots RE-FETCH for an evicted host (the
# fail-closed semantics are unchanged — an evicted entry is simply recomputed).
_ROBOTS_CACHE_MAX = _env_cap("OO_ROBOTS_CACHE_MAX", 4096, floor=64)
# The per-host last-request timestamps are tiny but also unbounded. POLITENESS
# WINS OVER THE BOUND: an entry is evicted only when its host was last fetched
# more than _LAST_REQUEST_SAFE_AGE_S ago (default 6 h — far beyond any plausible
# robots Crawl-delay), so eviction can never permit an early re-fetch. If every
# entry is younger than that, the map is left over-cap (a dict of floats; the
# honest trade).
_LAST_REQUEST_MAX = _env_cap("OO_HOST_STATE_MAX", 8192, floor=64)
_LAST_REQUEST_SAFE_AGE_S = 6 * 3600.0
# Bound on redirects followed (each hop is re-validated against the SSRF guard).
_MAX_REDIRECTS = 5
# HTTP statuses worth retrying (transient server-side / rate-limit signals). 4xx
# client errors are deterministic and never retried (finding BUG-02).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# --------------------------------------------------------------------------- #
# C8 (2026-07-24 throughput brief): skip local DNS resolution when the exit
# resolves + a short-TTL cache for the path that still resolves locally (A6).
# --------------------------------------------------------------------------- #
#
# _guard_target() calls socket.getaddrinfo(host) on EVERY fetch + EVERY redirect
# hop -- even when proxied, where the resolved IP is never actually used to
# connect (the proxy/exit does that). Two distinct fixes:
#
# (1) When the configured proxy scheme is REMOTE-RESOLVING (socks5h/socks4a --
#     the trailing "h"/"a" is the curl/PySocks convention meaning "the PROXY
#     resolves", as opposed to plain socks5/socks4 where WE resolve locally and
#     hand the proxy an IP), the local getaddrinfo call is skipped entirely:
#     we never learn an IP to check, so there is nothing for _guard_target to
#     validate -- egress goes straight to the proxy with the hostname, saving
#     one DNS round-trip AND closing a DNS-metadata leak to the local/ISP
#     resolver (the exit performs the lookup instead). VERIFIED AT BUILD: the
#     app's own documented example (src/safety/settings.py) was
#     "socks5://127.0.0.1:9050" -- the LOCAL-resolving scheme -- so this
#     optimisation is INERT unless the operator (or our own default/guidance)
#     actually uses the "h" variant; the settings docstring/messages are
#     updated to recommend socks5h as the more private default. A plain
#     socks5/socks4 proxy is UNCHANGED (still resolved + guarded locally,
#     byte-identical) -- skipping the guard there would be a real SSRF hole,
#     since PySocks would still hand the proxy a LOCALLY-resolved IP with no
#     guard between resolution and connection.
# (2) For every path that STILL resolves locally (no proxy, or a non-remote-
#     resolving one), a short-TTL cache avoids re-resolving the SAME host on
#     every fetch/redirect hop within one pass. The TTL is intentionally SHORT
#     (default 60s) -- long enough to save real repeat-lookup latency across a
#     burst of fetches to one host, short enough that a DNS-rebinding attack
#     gains nothing durable (the guard re-validates well within any plausible
#     attack window). Per-instance (like every other host cache here), so it
#     resets every pass along with everything else -- never persisted, no new
#     staleness surface.
_DNS_CACHE_TTL_S = float(os.getenv("OO_DNS_CACHE_TTL", "60") or "60")
_DNS_CACHE_MAX = _env_cap("OO_DNS_CACHE_MAX", 2048, floor=64)
# The curl/PySocks "remote resolve" scheme suffix: socks5h / socks4a.
_REMOTE_RESOLVE_SOCKS_SCHEMES = frozenset({"socks5h", "socks4a"})


def _is_remote_resolving_proxy(proxy_url: str | None) -> bool:
    """True when ``proxy_url``'s scheme resolves DNS AT THE PROXY/EXIT
    (``socks5h``/``socks4a``) rather than locally (``socks5``/``socks4``, any
    plain http(s) proxy, or no proxy at all). PURE string check, no I/O."""
    if not proxy_url or "://" not in proxy_url:
        return False
    scheme = proxy_url.split("://", 1)[0].lower()
    return scheme in _REMOTE_RESOLVE_SOCKS_SCHEMES

# --- Global network kill switch (a §0.5 invariant; maintainer: "Stop must be a
# kill switch"). Once set, EVERY new fetch attempt -- scheduler, manual ingest,
# crawler, markets, law, discovery -- refuses immediately. The single request
# already on the wire finishes (sockets aren't yanked mid-read), everything
# after it stops. Cleared when the operator starts collecting again.
_KILL = threading.Event()


def activate_kill_switch() -> None:
    _KILL.set()


def clear_kill_switch() -> None:
    _KILL.clear()


def kill_switch_active() -> bool:
    return _KILL.is_set()


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address an external fetch should never reach (SSRF, CWE-918).

    Blocks loopback, RFC1918/ULA private, link-local (incl. 169.254.169.254 cloud
    metadata), reserved, multicast and the unspecified address.
    """
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


class EthicalFetcher:
    """Stateful fetcher enforcing robots.txt (fail-closed) + per-host rate limits.

    A ``session`` may be injected for testing (any object with a ``.get(url,
    timeout=...)`` returning a requests-like Response).
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval_s: float = 1.0,
        timeout: float = 30.0,
        max_bytes: int = 10 * 1024 * 1024,
        respect_robots: bool = True,
        proxy: str | None = None,
        session: requests.Session | None = None,
        max_retries: int = 2,
        retry_backoff_s: float = 0.5,
        robots_cache_path: Path | None = None,
    ):
        self.user_agent = user_agent
        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        # Bounded retry/backoff for transient fetch failures (finding BUG-02).
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_s = max(0.0, float(retry_backoff_s))
        self.proxy = proxy or None
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        # Size the connection pool for parallel collection: with up to ~50
        # concurrent DISTINCT hosts (per-host concurrency stays 1 via the host
        # lock), the default urllib3 pool (10) would churn host-pools and warn.
        # A generous adapter keeps warm keep-alive connections reused across a
        # pass. Real session only (an injected test stub manages its own I/O).
        if isinstance(self.session, requests.Session):
            try:
                from requests.adapters import HTTPAdapter

                pool_n = max(1, int(os.getenv("OO_HTTP_POOL", "64")))
                adapter = HTTPAdapter(pool_connections=pool_n, pool_maxsize=pool_n)
                self.session.mount("http://", adapter)
                self.session.mount("https://", adapter)
            except Exception:  # noqa: BLE001 - pool sizing is an optimisation, never required
                pass
        # Protected fetch (Theme 2): route through the user's proxy (e.g. Tor at
        # socks5://127.0.0.1:9050). We *use* the proxy and verify it is set; we do NOT
        # guarantee anonymity — the user must run and trust the proxy. SOCKS proxies need
        # the optional [safety] extra (PySocks); HTTP/HTTPS proxies work out of the box.
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}
        # Per-HOST Tor stream isolation (on by default; OO_TOR_STREAM_ISOLATION=0
        # disables). Over a SOCKS proxy, each host's requests ride their OWN Tor
        # circuit (IsolateSOCKSAuth), so no exit node or circuit observer can link
        # the user's activity across different sources — Tor Browser's "isolate by
        # first-party domain" model. A no-op for non-SOCKS/no proxy. We still never
        # claim anonymity; this only compartmentalises what the proxy already gives.
        self._stream_isolation = os.environ.get("OO_TOR_STREAM_ISOLATION", "1") != "0"
        self._max_redirects = _MAX_REDIRECTS
        # host -> (decision_parser_or_None, expiry). None == "do not fetch this host".
        self._robots: dict[str, tuple[RobotFileParser | None, float]] = {}
        self._last_request: dict[str, float] = {}
        # C8: short-TTL DNS cache for the path that still resolves locally (a
        # remote-resolving SOCKS proxy skips this entirely -- see
        # _is_remote_resolving_proxy). host -> (getaddrinfo results, expiry).
        self._dns_cache: dict[str, tuple[list, float]] = {}
        # Per-host locks: one source/host is fetched by at most ONE thread at a
        # time, so parallel collection (a bounded worker pool) is polite by
        # construction — concurrency is ACROSS hosts, never within one host's
        # rate-limit. The shared mutable state (_robots, _last_request) for a host
        # is only touched under its lock. Different hosts run in parallel.
        self._host_locks: dict[str, threading.Lock] = {}
        self._host_locks_guard = threading.Lock()
        # Serialises WRITES to ``_last_request`` against the eviction sweep
        # (skeptic finding 2026-07-09: an unsynchronised sweep could pop a
        # FRESH stamp written between its snapshot and its pop, letting the
        # next fetch of that host skip the politeness delay). Reads stay
        # lock-free (a stale read only ever sleeps MORE, never less).
        self._host_state_guard = threading.Lock()
        # sleep is indirected so tests can run without real delays.
        self._sleep = time.sleep
        self._now = time.monotonic

        # A5 (2026-07-24 throughput brief, C4): reuse in-TTL robots.txt verdicts
        # from a prior pass/process instead of starting cold every time
        # make_fetcher() builds a fresh instance (see the module-level note by
        # _ROBOTS_TTL). Injectable so tests never touch the real data_dir().
        self._robots_cache_path = robots_cache_path or _robots_cache_path()
        if _robots_persist_enabled():
            try:
                self._robots.update(
                    _load_persisted_robots(self._robots_cache_path, now_monotonic=self._now)
                )
            except Exception:  # noqa: BLE001 - a bad cache load must never break construction
                pass

    def _host_lock(self, netloc: str) -> threading.Lock:
        """Return (creating if needed) the lock that serialises fetches to ``netloc``.

        The lock map is deliberately UNBOUNDED: evicting a lock object another
        thread may already hold a reference to would let two threads fetch the
        same host concurrently (politeness is never traded for memory — a
        threading.Lock is ~100 bytes, and the fetcher is per-pass so the map
        dies with the pass; pass recycling bounds the pass).
        """
        with self._host_locks_guard:
            lock = self._host_locks.get(netloc)
            if lock is None:
                lock = threading.Lock()
                self._host_locks[netloc] = lock
            return lock

    def cache_stats(self) -> dict:
        """Sizes of the per-pass host caches (memory instrumentation, P0.3 E1).

        Read by the collection-perf monitor each tick so a marathon pass's
        accumulation is measured, not guessed. Plain lengths — cheap, no locks
        beyond the GIL (an off-by-one under concurrent mutation is fine for a
        gauge).
        """
        return {
            "robots": len(self._robots),
            "last_request": len(self._last_request),
            "host_locks": len(self._host_locks),
            "dns": len(self._dns_cache),
        }

    def declared_sitemaps(self, url: str) -> list[str]:
        """Sitemap URLs the host's own robots.txt DECLARES (``Sitemap:`` directives,
        parsed by the stdlib ``RobotFileParser`` -- the same cached decision
        ``_enforce_robots`` uses, so this costs a real robots fetch only on a cache
        miss). C7 (2026-07-24 throughput brief): the preferred discovery source,
        since it is the site's OWN authoritative pointer -- a conventional
        ``/sitemap.xml`` guess is only the fallback (see ``src.ingest.sitemap``).

        Same guards as :meth:`fetch` (this can trigger a REAL robots.txt fetch on a
        cache miss, so it must never bypass them): the kill switch is honoured
        (airplane mode refuses -- raises ``FetchFailed``, exactly like ``fetch``),
        the SSRF guard runs on the target host, and the per-host lock serialises
        against a concurrent fetch to the same host.

        Returns ``[]`` (never a guess) when robots.txt disallows/is unavailable for
        this host, or when it declares no sitemaps at all.
        """
        if _KILL.is_set():
            raise FetchFailed("network kill switch is active -- collection stopped by operator")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return []
        self._guard_target(parsed.hostname)  # SSRF: never reach internal addresses
        host_key = f"{parsed.scheme}://{parsed.netloc}"
        with self._host_lock(parsed.netloc):
            parser = self._get_robots(host_key, parsed)
        if parser is None:
            return []
        try:
            return list(parser.site_maps() or [])
        except Exception:  # noqa: BLE001 - a parser quirk must never break discovery
            return []

    def _declares_crawl_delay(self, key_or_netloc: str) -> bool:
        """True when the cached robots decision for this host declares a
        Crawl-delay (checked under both scheme keys for a bare netloc)."""
        keys = (
            (key_or_netloc,)
            if "://" in key_or_netloc
            else (f"https://{key_or_netloc}", f"http://{key_or_netloc}")
        )
        for k in keys:
            cached = self._robots.get(k)
            if cached is not None and cached[0] is not None:
                try:
                    if cached[0].crawl_delay(self.user_agent):
                        return True
                except Exception:  # noqa: BLE001 - unknowable delay: keep the entry
                    return True
        return False

    def _bound_host_caches(self) -> None:
        """Keep the per-pass host caches bounded on a very wide/long pass.

        Best-effort and defensive (a bookkeeping error must never break a
        fetch), and POLITENESS OUTRANKS THE BOUND (skeptic-hardened 2026-07-09):

        * A robots entry whose parser declares a ``Crawl-delay`` is NEVER
          evicted — an in-flight fetch between its robots check and its
          rate-limit read must always still see the declared delay. Evicting a
          delay-LESS entry is semantically neutral for pacing (the rate limit
          falls back to ``min_interval_s``, exactly what that entry yields)
          and only costs a fail-closed robots recompute on the next contact.
        * ``_last_request`` stamps are mutated ONLY under ``_host_state_guard``
          (shared with the writer in the fetch path), so eviction can never
          race a fresh stamp out of the map (the TOCTOU a skeptic reproduced);
          an entry is evicted only when older than ``_LAST_REQUEST_SAFE_AGE_S``
          AND its host declares no Crawl-delay, so a forgotten timestamp can
          never permit an impolitely early re-fetch. All-young over-cap maps
          simply stay over cap (a dict of floats — the honest trade).
        """
        try:
            if len(self._robots) > _ROBOTS_CACHE_MAX:
                items = sorted(self._robots.items(), key=lambda kv: kv[1][1])
                excess = len(items) - _ROBOTS_CACHE_MAX
                for key, (decision, _expiry) in items:
                    if excess <= 0:
                        break
                    if decision is not None:
                        try:
                            if decision.crawl_delay(self.user_agent):
                                continue  # politeness-critical: never evicted
                        except Exception:  # noqa: BLE001 - unknowable: keep it
                            continue
                    self._robots.pop(key, None)
                    excess -= 1
            if len(self._last_request) > _LAST_REQUEST_MAX:
                with self._host_state_guard:
                    now = self._now()
                    items2 = sorted(self._last_request.items(), key=lambda kv: kv[1])
                    excess = len(items2) - _LAST_REQUEST_MAX
                    for key, last in items2:
                        if excess <= 0 or (now - last) < _LAST_REQUEST_SAFE_AGE_S:
                            break  # sorted ascending: the rest are younger still
                        if self._declares_crawl_delay(key):
                            continue  # a long declared delay outlives the safe age
                        self._last_request.pop(key, None)
                        excess -= 1
        except Exception:  # noqa: BLE001 - a cache bound must never break a fetch
            pass

    @property
    def _real_session(self) -> bool:
        """Network-level guards (DNS-resolution SSRF check, streamed size cap) apply only
        to the real requests session; an injected stub/double controls its own returns, so
        only the cheap literal-IP block runs for it. Computed at call time because tests may
        swap ``.session`` after construction."""
        return isinstance(self.session, requests.Session)

    # -- public API -------------------------------------------------------- #

    def fetch(
        self,
        url: str,
        *,
        require_html: bool = True,
        extra_headers: dict[str, str] | None = None,
        keep_bytes: bool = False,
    ) -> FetchResult:
        """Fetch ``url`` ethically. Raises a ``FetchError`` subclass on any refusal.

        ``require_html`` rejects non-HTML responses (used for article pages). Set it
        False to fetch feeds (RSS/Atom XML) through the same robots/rate-limit path.

        ``extra_headers`` adds request headers (e.g. conditional-GET
        ``If-None-Match`` / ``If-Modified-Since`` for feeds). When the server
        answers ``304 Not Modified`` the returned ``FetchResult`` has
        ``status_code == 304`` and empty content — a valid, non-error result, so
        the caller can skip re-parsing an unchanged feed.

        ``keep_bytes`` additionally attaches the UNDECODED response bytes on
        ``FetchResult.raw_content`` (default off ⇒ byte-identical + no extra
        memory for every existing caller). Needed for a binary body (e.g. a PDF
        law) whose bytes the text-decode path would otherwise destroy.
        """
        if _KILL.is_set():
            raise FetchFailed("network kill switch is active -- collection stopped by operator")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise FetchFailed(f"unsupported or malformed URL: {url!r}")

        # Cheap length check per fetch; evicts only when a cap is exceeded (E1).
        self._bound_host_caches()

        self._guard_target(parsed.hostname)  # SSRF: never reach internal addresses

        host_key = f"{parsed.scheme}://{parsed.netloc}"
        # Per-host Tor circuit (computed once, from the ORIGINAL host) so the
        # robots check and every page/redirect hop for this host share it.
        iso_proxies = self._isolated_proxies(parsed.netloc)

        # Serialise everything for this host under its per-host lock: robots +
        # rate-limit + the (possibly retried) GET + body read. So a host is hit by
        # AT MOST ONE request at a time (politeness is never traded for speed, even
        # under parallel collection), while DIFFERENT hosts proceed in parallel —
        # each on its own Tor circuit. The lock releases on return/raise.
        with self._host_lock(parsed.netloc):
            return self._fetch_locked(
                url,
                host_key=host_key,
                parsed=parsed,
                require_html=require_html,
                extra_headers=extra_headers,
                iso_proxies=iso_proxies,
                keep_bytes=keep_bytes,
            )

    def _fetch_locked(
        self, url, *, host_key, parsed, require_html, extra_headers, iso_proxies,
        keep_bytes=False,
    ) -> FetchResult:
        """The per-host-serialised fetch body (caller holds the host lock)."""
        # robots.txt is checked once (not per retry): a disallow/unavailable is a
        # deliberate, non-transient refusal.
        if self.respect_robots:
            self._enforce_robots(url, host_key, parsed)

        # Bounded retry with exponential backoff for *transient* failures only
        # (network errors, 429, and 5xx) -- finding BUG-02. Deterministic refusals
        # (4xx, non-HTML, robots/SSRF) are never retried. Per-host rate limiting is
        # honoured before every attempt so retries stay polite.
        fetch_token = activity_monitor.fetch_started(url)
        try:
            attempt = 0
            while True:
                self._respect_rate_limit(parsed.netloc, host_key)
                transient: Exception | None = None
                response = final_url = None
                try:
                    response, final_url = self._http_get(
                        url, extra_headers=extra_headers, proxies=iso_proxies
                    )
                except requests.RequestException as exc:
                    transient = FetchFailed(f"request error for {url}: {exc}")
                finally:
                    with self._host_state_guard:
                        self._last_request[parsed.netloc] = self._now()

                if transient is None and response.status_code not in _RETRYABLE_STATUS:
                    break  # got a definitive (success or non-retryable) response

                if attempt >= self.max_retries:
                    if transient is not None:
                        raise transient
                    break  # out of retries: fall through to handle the status below

                attempt += 1
                self._sleep(self.retry_backoff_s * (2 ** (attempt - 1)))

            # the loop exits with either a definitive response or a raised error
            assert response is not None and final_url is not None

            # Source IP capture (Slice 6a): read the connected server IP while the
            # connection is still live (stream=True keeps it open until the body is
            # read). Clearnet only -- over Tor/proxy this is honestly unavailable.
            server_ip, server_ip_reason = self._capture_server_ip(
                response, proxied=bool(self.proxy or iso_proxies)
            )

            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")

            # 304 Not Modified: a VALID conditional-GET answer, not a failure.
            # The resource is unchanged; return an empty-bodied result carrying
            # the (echoed) validators so the caller can refresh its bookkeeping.
            if response.status_code == 304:
                if hasattr(response, "close"):
                    response.close()
                return FetchResult(
                    requested_url=url,
                    final_url=final_url,
                    status_code=304,
                    content="",
                    content_type=response.headers.get("Content-Type", ""),
                    fetched_at=datetime.now(UTC),
                    etag=etag,
                    last_modified=last_modified,
                    server_ip=server_ip,
                    server_ip_reason=server_ip_reason,
                )

            if response.status_code != 200:
                raise FetchFailed(f"HTTP {response.status_code} for {url}")

            content_type = response.headers.get("Content-Type", "")
            if require_html and "html" not in content_type.lower():
                raise FetchFailed(f"non-HTML content ({content_type!r}) for {url}")

            content, raw_body = self._read_body(
                response, url, token=fetch_token, keep_bytes=keep_bytes
            )

            return FetchResult(
                requested_url=url,
                final_url=final_url,
                status_code=response.status_code,
                content=content,
                content_type=content_type,
                fetched_at=datetime.now(UTC),
                etag=etag,
                last_modified=last_modified,
                server_ip=server_ip,
                server_ip_reason=server_ip_reason,
                raw_content=raw_body,
            )
        finally:
            activity_monitor.fetch_finished(fetch_token)

    def _capture_server_ip(
        self, response, *, proxied: bool
    ) -> tuple[str | None, str | None]:
        """The server IP we connected to (Slice 6a) + an honest reason when unavailable.

        Returns ``(ip, None)`` on a direct clearnet connection, else ``(None, reason)``.
        NEVER a guess: over a SOCKS proxy / Tor the socket connects to the PROXY, not the
        server, so the real server IP is genuinely unavailable. The captured IP is OUR
        VANTAGE POINT (usually a CDN edge / anycast), not proof of the publisher's origin.
        """
        if proxied:
            return None, "unavailable (proxy/Tor)"
        if not self._real_session:
            return None, None  # injected/test session: no real socket to read
        # Read the connected peer from the live urllib3 socket. Internals differ across
        # urllib3 versions, so try the known paths and degrade loudly (never fabricate).
        sock = None
        try:
            sock = response.raw._connection.sock  # urllib3 HTTPConnection
        except Exception:  # noqa: BLE001
            try:
                sock = response.raw._fp.fp.raw._sock  # http.client fallback
            except Exception:  # noqa: BLE001
                sock = None
        if sock is None:
            return None, "unavailable (socket not readable)"
        try:
            ip = sock.getpeername()[0]
            ipaddress.ip_address(ip)  # validate; raises on garbage
            return str(ip), None
        except Exception:  # noqa: BLE001
            return None, "unavailable (socket not readable)"

    # -- SSRF guard + bounded redirects + size-capped body ----------------- #

    def _guard_target(self, host: str | None) -> None:
        """Refuse to fetch internal/non-public targets (SSRF, CWE-918).

        Applies only to the real requests session — an injected stub/double performs no
        real network I/O, so there is nothing to guard (and tests may legitimately use
        loopback stand-in hosts). For a real fetch, literal IPs are checked and hostnames
        are resolved + checked (rejecting a name that resolves to a private/loopback/
        link-local address — defeating DNS-rebinding-to-internal).

        C8: when the configured proxy is REMOTE-RESOLVING (socks5h/socks4a), the
        hostname branch is skipped entirely — we never learn an IP to validate,
        egress goes straight to the proxy, and the exit resolves it (see the
        module-level note by ``_is_remote_resolving_proxy``). A literal IP is
        STILL checked either way (cheap, no resolution needed). Every other
        configuration (no proxy, a plain http(s) proxy, or a LOCAL-resolving
        socks5/socks4 proxy) keeps the FULL guard, byte-identical to before —
        this is the one branch that changes behaviour, and only under a
        verified remote-resolving scheme.
        """
        if not self._real_session:
            return
        if not host:
            raise FetchFailed("missing host")
        host = host.strip("[]")  # IPv6 literal brackets
        try:
            if _is_blocked_ip(ipaddress.ip_address(host)):
                raise BlockedTarget(f"refusing to fetch a non-public address: {host}")
            return  # a public IP literal
        except ValueError:
            pass  # not an IP literal -> a hostname
        if _is_remote_resolving_proxy(self.proxy):
            return  # the exit resolves; nothing for us to check
        infos = self._resolve_cached(host)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if _is_blocked_ip(ip):
                raise BlockedTarget(f"{host} resolves to a non-public address ({ip})")

    def _resolve_cached(self, host: str) -> list:
        """``socket.getaddrinfo(host, None)`` with a short-TTL cache (C8/A6) — a
        real fetch/redirect chain can hit the SAME host several times in one pass;
        this avoids re-resolving it every time. Bounded (``_DNS_CACHE_MAX``): on
        overflow the WHOLE cache is cleared rather than a sorted eviction (the TTL
        is already short, so this self-heals within ``_DNS_CACHE_TTL_S`` regardless
        — simpler than the size-sorted eviction the robots/last-request caches use,
        and correctness never depends on which entries survive)."""
        now = self._now()
        cached = self._dns_cache.get(host)
        if cached is not None and now < cached[1]:
            return cached[0]
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise FetchFailed(f"cannot resolve host {host!r}: {exc}") from exc
        if len(self._dns_cache) >= _DNS_CACHE_MAX:
            self._dns_cache.clear()
        self._dns_cache[host] = (infos, now + _DNS_CACHE_TTL_S)
        return infos

    def _isolated_proxies(self, netloc: str | None) -> dict[str, str] | None:
        """Per-HOST Tor stream-isolation proxies for ``netloc`` (or ``None`` to
        use the session's base proxy).

        Returns a ``{"http":…, "https":…}`` dict whose SOCKS URL carries a
        per-host username so Tor's ``IsolateSOCKSAuth`` builds a dedicated circuit
        for this host. A no-op (returns ``None``) when isolation is disabled,
        there is no proxy, or the proxy is not SOCKS. The page fetch and its
        robots.txt both route through this, so a host's traffic shares one circuit
        and is unlinkable to other hosts' circuits.
        """
        if not self._stream_isolation or not self.proxy or not netloc:
            return None
        # Lazy import: src.safety.fetcher imports from src.ingest, so a top-level
        # import here would be circular. The helper is pure string work.
        from src.safety.fetcher import _with_stream_isolation

        isolated = _with_stream_isolation(self.proxy, netloc)
        if isolated == self.proxy:
            return None  # non-SOCKS proxy (or creds already set): nothing to isolate
        return {"http": isolated, "https": isolated}

    def _http_get(
        self,
        url: str,
        *,
        extra_headers: dict[str, str] | None = None,
        proxies: dict[str, str] | None = None,
    ):
        """GET with manual, bounded redirects, re-validating every hop (SSRF).

        ``extra_headers`` (e.g. conditional-GET validators) are sent on each hop;
        the final resource is the one that validates them. ``proxies`` (per-host
        Tor stream isolation) overrides the session proxy for THIS fetch, keyed on
        the ORIGINAL host so every redirect hop stays on the same circuit.
        """
        return self._guarded_redirect_get(
            url, extra_headers=extra_headers, proxies=proxies, stream=True
        )

    def _guarded_redirect_get(
        self,
        url: str,
        *,
        extra_headers: dict[str, str] | None = None,
        proxies: dict[str, str] | None = None,
        stream: bool = False,
    ):
        """The ONE redirect path: follow bounded redirects manually, re-running the
        SSRF guard on EVERY hop's target (CWE-918). Returns ``(response, final_url)``.

        Both the page fetch (``_http_get``, ``stream=True``) and the robots.txt
        fetch (``_get_robots``, ``stream=False``) route through here, so a 30x
        redirect to an internal address (``127.0.0.1`` / ``169.254.169.254`` / a
        rebinding hostname) is refused on the robots path exactly as on the page
        path -- closing the prior gap where robots used ``allow_redirects=True``
        and so let its redirect chain bypass the guard.
        """
        current = url
        for _ in range(self._max_redirects + 1):
            kwargs: dict[str, Any] = {"timeout": self.timeout, "allow_redirects": False}
            if extra_headers:
                kwargs["headers"] = extra_headers
            if proxies:
                kwargs["proxies"] = proxies
            if stream and self._real_session:
                kwargs["stream"] = True
            resp = self.session.get(current, **kwargs)
            status = resp.status_code
            location = resp.headers.get("Location") if hasattr(resp, "headers") else None
            if 300 <= status < 400 and location:
                nxt = urljoin(current, location)
                p = urlparse(nxt)
                if p.scheme not in ("http", "https") or not p.netloc:
                    raise FetchFailed(f"redirect to unsupported URL: {nxt!r}")
                self._guard_target(p.hostname)  # re-validate the redirect target
                if hasattr(resp, "close"):
                    resp.close()
                current = nxt
                continue
            return resp, str(getattr(resp, "url", current) or current)
        raise FetchFailed(f"too many redirects for {url}")

    def _read_body(
        self, response, url: str, *, token: int | None = None, keep_bytes: bool = False
    ) -> tuple[str, bytes | None]:
        """Decode the body, enforcing ``max_bytes`` *before* materialising it (DoS).

        A declared Content-Length over the cap is rejected up front; for the real
        (streamed) session the body is read incrementally and aborted once the
        decompressed size exceeds the cap (defeats gzip/decompression bombs).

        Returns ``(decoded_text, raw_bytes_or_None)`` — ``raw_bytes`` is the
        undecoded body when ``keep_bytes`` is set (already bounded by
        ``max_bytes``), else None so no extra memory is held.
        """
        cl = response.headers.get("Content-Length") if hasattr(response, "headers") else None
        if cl and str(cl).isdigit() and int(cl) > self.max_bytes:
            raise FetchFailed(f"declared length {cl} exceeds {self.max_bytes} bytes for {url}")
        if self._real_session and hasattr(response, "iter_content"):
            total = 0
            chunks: list[bytes] = []
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self.max_bytes:
                    if hasattr(response, "close"):
                        response.close()
                    raise FetchFailed(f"response exceeds {self.max_bytes} bytes for {url}")
                chunks.append(chunk)
            raw = b"".join(chunks)
            activity_monitor.fetch_bytes(total, token)  # real, app-attributed download size
            # Pick a text encoding WITHOUT touching response.apparent_encoding: on a
            # streamed response the body is already consumed, so apparent_encoding
            # re-reads it and raises "content already consumed" (crashing the scrape).
            # Detect from the bytes we just collected instead. requests also defaults
            # unlabelled text/* to ISO-8859-1, which is usually wrong for modern pages,
            # so detect in that case too.
            encoding = getattr(response, "encoding", None)
            if not encoding or str(encoding).lower() in ("iso-8859-1", "latin-1"):
                try:
                    from charset_normalizer import from_bytes

                    best = from_bytes(raw).best()
                    if best and best.encoding:
                        encoding = best.encoding
                except Exception:  # noqa: BLE001 - detection is best-effort
                    pass
                encoding = encoding or "utf-8"
            kept = raw if keep_bytes else None
            try:
                return raw.decode(encoding, errors="replace"), kept
            except (LookupError, TypeError):
                return raw.decode("utf-8", errors="replace"), kept
        # Injected (test) session: not streamed; check the already-materialised body.
        if response.content and len(response.content) > self.max_bytes:
            raise FetchFailed(f"response exceeds {self.max_bytes} bytes for {url}")
        activity_monitor.fetch_bytes(len(response.content or b""), token)
        return response.text, (response.content if keep_bytes else None)

    # -- robots ------------------------------------------------------------ #

    def _enforce_robots(self, url: str, host_key: str, parsed) -> None:
        parser = self._get_robots(host_key, parsed)
        if parser is None:
            raise RobotsUnavailable(
                f"robots.txt for {host_key} could not be determined; refusing to fetch"
            )
        if not parser.can_fetch(self.user_agent, url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

    def _get_robots(self, host_key: str, parsed) -> RobotFileParser | None:
        cached = self._robots.get(host_key)
        if cached is not None and self._now() < cached[1]:
            return cached[0]

        robots_url = f"{host_key}/robots.txt"
        # Same per-host Tor circuit as the page fetch, so a host's robots.txt is
        # not leaked onto the shared base circuit (complete per-host isolation).
        iso = self._isolated_proxies(getattr(parsed, "netloc", None))
        decision: RobotFileParser | None
        # Persisted alongside `decision` (A5, C4) so a reload can reconstruct the
        # SAME parser: "parsed" carries the raw body, "allow_all"/"disallow_all"
        # need none (defaults below cover every early-return/exception path).
        persist_kind = "disallow_all"
        persist_body: str | None = None
        try:
            # Follow redirects MANUALLY through the shared guarded loop so a
            # robots.txt that 30x-redirects to an internal address is refused
            # (SSRF, CWE-918). Previously this used allow_redirects=True, which let
            # the robots redirect chain bypass the per-hop SSRF guard that the page
            # fetch always applied (finding OO-D2-001).
            resp, _robots_final = self._guarded_redirect_get(robots_url, proxies=iso)
            status = resp.status_code
            if status == 200:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                decision = rp
                persist_kind, persist_body = "parsed", resp.text
            elif status in (404, 410):
                # No robots.txt -> everything allowed (standard behaviour).
                rp = RobotFileParser()
                rp.parse([])
                decision = rp
                persist_kind = "allow_all"
            elif status in (401, 403):
                # Access to robots is restricted -> treat the whole site as off-limits.
                decision = None
            else:
                # 5xx / unexpected -> cannot determine -> fail closed.
                decision = None
        except (requests.RequestException, FetchError):
            # network/timeout, an SSRF-blocked redirect target, a redirect to an
            # unsupported scheme, or too many redirects -> cannot safely determine
            # robots -> fail closed.
            decision = None

        self._robots[host_key] = (decision, self._now() + _ROBOTS_TTL)
        if _robots_persist_enabled():
            _persist_robots_entry(
                self._robots_cache_path, host_key, kind=persist_kind, body=persist_body
            )
        return decision

    # -- rate limiting ----------------------------------------------------- #

    def _respect_rate_limit(self, netloc: str, host_key: str) -> None:
        interval = self.min_interval_s
        cached = self._robots.get(host_key)
        if cached and cached[0] is not None:
            try:
                delay = cached[0].crawl_delay(self.user_agent)
            except Exception:
                delay = None
            if delay:
                interval = max(interval, float(delay))

        last = self._last_request.get(netloc)
        if last is not None:
            elapsed = self._now() - last
            if elapsed < interval:
                self._sleep(interval - elapsed)
