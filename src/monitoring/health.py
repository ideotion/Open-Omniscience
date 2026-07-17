"""
Real source-uptime checks.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Replaces the simulated monitoring found in the audit (``await asyncio.sleep(0.1);
status = HEALTHY``, P1-8). A check here performs a REAL request through the same
ethical fetcher used for ingestion (so monitoring also respects robots.txt and
rate limits) and reports the measured outcome and latency -- never a hardcoded
"healthy".
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from src.ingest import EthicalFetcher, FetchError, RobotsDisallowed, RobotsUnavailable


class HealthStatus(str, Enum):
    UP = "up"
    DOWN = "down"
    BLOCKED = "blocked"  # robots disallows / can't confirm -> we won't probe further
    UNKNOWN = "unknown"


@dataclass
class SourceHealth:
    source_id: int | None
    name: str
    url: str
    status: HealthStatus
    latency_ms: float | None
    checked_at: datetime
    detail: str | None = None

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "url": self.url,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at.isoformat(),
            "detail": self.detail,
        }


def _probe_url(source) -> str:
    """The URL to probe: the RSS feed if present, else the domain homepage."""
    if getattr(source, "rss_url", None):
        return source.rss_url
    domain = source.domain
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"


def check_source(source, *, fetcher: EthicalFetcher) -> SourceHealth:
    """Perform one real reachability check for a source."""
    url = _probe_url(source)
    started = time.monotonic()
    now = datetime.now(UTC)
    try:
        fetcher.fetch(url, require_html=False)
        latency = (time.monotonic() - started) * 1000.0
        return SourceHealth(
            getattr(source, "id", None), source.name, url, HealthStatus.UP, round(latency, 1), now
        )
    except (RobotsDisallowed, RobotsUnavailable) as exc:
        return SourceHealth(
            getattr(source, "id", None),
            source.name,
            url,
            HealthStatus.BLOCKED,
            None,
            now,
            detail=str(exc),
        )
    except FetchError as exc:
        latency = (time.monotonic() - started) * 1000.0
        return SourceHealth(
            getattr(source, "id", None),
            source.name,
            url,
            HealthStatus.DOWN,
            round(latency, 1),
            now,
            detail=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - audit finding 2026-07-17 (L3): the caller
        # (api/monitoring.py's sources_health) runs this in a plain list comprehension
        # over every probed source with NO per-source try/except, so ANY exception type
        # this function doesn't explicitly catch aborts the WHOLE health-check batch --
        # every other source's result is lost too. Today every foreseeable I/O failure
        # path in EthicalFetcher.fetch() already wraps into a FetchError subclass, but
        # that is an IMPLICIT contract this function silently depends on; a genuinely
        # unforeseen exception (a library bug, a malformed response) must degrade this
        # ONE source's result honestly rather than take the whole batch down with it.
        latency = (time.monotonic() - started) * 1000.0
        return SourceHealth(
            getattr(source, "id", None),
            source.name,
            url,
            HealthStatus.UNKNOWN,
            round(latency, 1),
            now,
            detail=f"unexpected error: {exc}",
        )
