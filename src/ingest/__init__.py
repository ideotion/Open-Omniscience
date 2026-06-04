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

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

DEFAULT_USER_AGENT = (
    "OpenOmniscienceBot/0.4 (+https://github.com/ideotion/Open-Omniscience; "
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


# How long a robots.txt decision is cached, in seconds.
_ROBOTS_TTL = 3600.0


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
        session: requests.Session | None = None,
    ):
        self.user_agent = user_agent
        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        # host -> (decision_parser_or_None, expiry). None == "do not fetch this host".
        self._robots: dict[str, tuple[RobotFileParser | None, float]] = {}
        self._last_request: dict[str, float] = {}
        # sleep is indirected so tests can run without real delays.
        self._sleep = time.sleep
        self._now = time.monotonic

    # -- public API -------------------------------------------------------- #

    def fetch(self, url: str, *, require_html: bool = True) -> FetchResult:
        """Fetch ``url`` ethically. Raises a ``FetchError`` subclass on any refusal.

        ``require_html`` rejects non-HTML responses (used for article pages). Set it
        False to fetch feeds (RSS/Atom XML) through the same robots/rate-limit path.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise FetchFailed(f"unsupported or malformed URL: {url!r}")

        host_key = f"{parsed.scheme}://{parsed.netloc}"

        if self.respect_robots:
            self._enforce_robots(url, host_key, parsed)

        self._respect_rate_limit(parsed.netloc, host_key)

        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as exc:
            raise FetchFailed(f"request error for {url}: {exc}") from exc
        finally:
            self._last_request[parsed.netloc] = self._now()

        if response.status_code != 200:
            raise FetchFailed(f"HTTP {response.status_code} for {url}")

        content_type = response.headers.get("Content-Type", "")
        if require_html and "html" not in content_type.lower():
            raise FetchFailed(f"non-HTML content ({content_type!r}) for {url}")

        if response.content and len(response.content) > self.max_bytes:
            raise FetchFailed(f"response exceeds {self.max_bytes} bytes for {url}")

        return FetchResult(
            requested_url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            content=response.text,
            content_type=content_type,
            fetched_at=datetime.now(timezone.utc),
        )

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
