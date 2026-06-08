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
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

DEFAULT_USER_AGENT = (
    "OpenOmniscienceBot/0.0.6 (+https://github.com/ideotion/Open-Omniscience; "
    "ethical research crawler)"
)


@dataclass
class FetchResult:
    """A successfully fetched HTML page with provenance."""

    requested_url: str
    final_url: str            # after redirects
    status_code: int
    content: str              # decoded HTML
    content_type: str
    fetched_at: datetime


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
# Bound on redirects followed (each hop is re-validated against the SSRF guard).
_MAX_REDIRECTS = 5


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address an external fetch should never reach (SSRF, CWE-918).

    Blocks loopback, RFC1918/ULA private, link-local (incl. 169.254.169.254 cloud
    metadata), reserved, multicast and the unspecified address.
    """
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
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
    ):
        self.user_agent = user_agent
        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self.proxy = proxy or None
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        # Protected fetch (Theme 2): route through the user's proxy (e.g. Tor at
        # socks5://127.0.0.1:9050). We *use* the proxy and verify it is set; we do NOT
        # guarantee anonymity — the user must run and trust the proxy. SOCKS proxies need
        # the optional [safety] extra (PySocks); HTTP/HTTPS proxies work out of the box.
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}
        self._max_redirects = _MAX_REDIRECTS
        # host -> (decision_parser_or_None, expiry). None == "do not fetch this host".
        self._robots: dict[str, tuple[RobotFileParser | None, float]] = {}
        self._last_request: dict[str, float] = {}
        # sleep is indirected so tests can run without real delays.
        self._sleep = time.sleep
        self._now = time.monotonic

    @property
    def _real_session(self) -> bool:
        """Network-level guards (DNS-resolution SSRF check, streamed size cap) apply only
        to the real requests session; an injected stub/double controls its own returns, so
        only the cheap literal-IP block runs for it. Computed at call time because tests may
        swap ``.session`` after construction."""
        return isinstance(self.session, requests.Session)

    # -- public API -------------------------------------------------------- #

    def fetch(self, url: str, *, require_html: bool = True) -> FetchResult:
        """Fetch ``url`` ethically. Raises a ``FetchError`` subclass on any refusal.

        ``require_html`` rejects non-HTML responses (used for article pages). Set it
        False to fetch feeds (RSS/Atom XML) through the same robots/rate-limit path.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise FetchFailed(f"unsupported or malformed URL: {url!r}")

        self._guard_target(parsed.hostname)  # SSRF: never reach internal addresses

        host_key = f"{parsed.scheme}://{parsed.netloc}"

        if self.respect_robots:
            self._enforce_robots(url, host_key, parsed)

        self._respect_rate_limit(parsed.netloc, host_key)

        try:
            response, final_url = self._http_get(url)
        except requests.RequestException as exc:
            raise FetchFailed(f"request error for {url}: {exc}") from exc
        finally:
            self._last_request[parsed.netloc] = self._now()

        if response.status_code != 200:
            raise FetchFailed(f"HTTP {response.status_code} for {url}")

        content_type = response.headers.get("Content-Type", "")
        if require_html and "html" not in content_type.lower():
            raise FetchFailed(f"non-HTML content ({content_type!r}) for {url}")

        content = self._read_body(response, url)

        return FetchResult(
            requested_url=url,
            final_url=final_url,
            status_code=response.status_code,
            content=content,
            content_type=content_type,
            fetched_at=datetime.now(UTC),
        )

    # -- SSRF guard + bounded redirects + size-capped body ----------------- #

    def _guard_target(self, host: str | None) -> None:
        """Refuse to fetch internal/non-public targets (SSRF, CWE-918).

        Applies only to the real requests session — an injected stub/double performs no
        real network I/O, so there is nothing to guard (and tests may legitimately use
        loopback stand-in hosts). For a real fetch, literal IPs are checked and hostnames
        are resolved + checked (rejecting a name that resolves to a private/loopback/
        link-local address — defeating DNS-rebinding-to-internal).
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
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise FetchFailed(f"cannot resolve host {host!r}: {exc}") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if _is_blocked_ip(ip):
                raise BlockedTarget(f"{host} resolves to a non-public address ({ip})")

    def _http_get(self, url: str):
        """GET with manual, bounded redirects, re-validating every hop (SSRF)."""
        current = url
        for _ in range(self._max_redirects + 1):
            kwargs = {"timeout": self.timeout, "allow_redirects": False}
            if self._real_session:
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

    def _read_body(self, response, url: str) -> str:
        """Decode the body, enforcing ``max_bytes`` *before* materialising it (DoS).

        A declared Content-Length over the cap is rejected up front; for the real
        (streamed) session the body is read incrementally and aborted once the
        decompressed size exceeds the cap (defeats gzip/decompression bombs).
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
            encoding = getattr(response, "encoding", None) or getattr(response, "apparent_encoding", None) or "utf-8"
            try:
                return raw.decode(encoding, errors="replace")
            except (LookupError, TypeError):
                return raw.decode("utf-8", errors="replace")
        # Injected (test) session: not streamed; check the already-materialised body.
        if response.content and len(response.content) > self.max_bytes:
            raise FetchFailed(f"response exceeds {self.max_bytes} bytes for {url}")
        return response.text

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
        decision: RobotFileParser | None
        try:
            resp = self.session.get(robots_url, timeout=self.timeout, allow_redirects=True)
            status = resp.status_code
            if status == 200:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                decision = rp
            elif status in (404, 410):
                # No robots.txt -> everything allowed (standard behaviour).
                rp = RobotFileParser()
                rp.parse([])
                decision = rp
            elif status in (401, 403):
                # Access to robots is restricted -> treat the whole site as off-limits.
                decision = None
            else:
                # 5xx / unexpected -> cannot determine -> fail closed.
                decision = None
        except requests.RequestException:
            decision = None  # network/timeout -> fail closed

        self._robots[host_key] = (decision, self._now() + _ROBOTS_TTL)
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
