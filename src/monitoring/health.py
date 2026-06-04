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
    BLOCKED = "blocked"   # robots disallows / can't confirm -> we won't probe further
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
        return SourceHealth(getattr(source, "id", None), source.name, url,
                            HealthStatus.UP, round(latency, 1), now)
    except (RobotsDisallowed, RobotsUnavailable) as exc:
        return SourceHealth(getattr(source, "id", None), source.name, url,
                            HealthStatus.BLOCKED, None, now, detail=str(exc))
    except FetchError as exc:
        latency = (time.monotonic() - started) * 1000.0
        return SourceHealth(getattr(source, "id", None), source.name, url,
                            HealthStatus.DOWN, round(latency, 1), now, detail=str(exc))
