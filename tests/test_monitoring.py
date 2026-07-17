"""
Tests for monitoring (Action Plan Phase 4): real uptime + corpus anomalies.

Proves the health check reflects a REAL request outcome (UP/DOWN/BLOCKED) -- not
the simulated 'sleep; HEALTHY' (P1-8) -- and that anomaly detection uses honest
z-scores with explicit insufficient-data behaviour.
"""

from __future__ import annotations

from datetime import date

from src.ingest import EthicalFetcher
from src.monitoring.anomaly import volume_anomalies
from src.monitoring.health import HealthStatus, check_source


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html"):
        self.status_code = status_code
        self.text = text
        self.content = text.encode()
        self.headers = {"Content-Type": content_type}
        self.url = "http://x"


class _Session:
    def __init__(self, routes):
        self.headers = {}
        self._routes = routes

    def get(self, url, timeout=None, allow_redirects=True):
        r = self._routes.get(url)
        if isinstance(r, Exception):
            raise r
        return r or _Resp(status_code=404, text="nf")


class _Src:
    def __init__(self, id, name, domain, rss_url=None):
        self.id, self.name, self.domain, self.rss_url = id, name, domain, rss_url


def _fetcher(routes):
    import requests

    sess = _Session(routes)
    # _Session.get raises requests exceptions for the error case below
    return EthicalFetcher(min_interval_s=0.0, session=sess), requests


def test_health_up():
    routes = {
        "https://up.example/robots.txt": _Resp(404, ""),
        "https://up.example": _Resp(200, "<html>ok</html>"),
    }
    f, _ = _fetcher(routes)
    h = check_source(_Src(1, "Up", "up.example"), fetcher=f)
    assert h.status is HealthStatus.UP
    assert h.latency_ms is not None


def test_health_down_on_5xx():
    routes = {
        "https://down.example/robots.txt": _Resp(404, ""),
        "https://down.example": _Resp(503, "boom"),
    }
    f, _ = _fetcher(routes)
    h = check_source(_Src(2, "Down", "down.example"), fetcher=f)
    assert h.status is HealthStatus.DOWN


def test_health_blocked_by_robots():
    routes = {
        "https://blk.example/robots.txt": _Resp(200, "User-agent: *\nDisallow: /"),
        "https://blk.example": _Resp(200, "<html>ok</html>"),
    }
    f, _ = _fetcher(routes)
    h = check_source(_Src(3, "Blk", "blk.example"), fetcher=f)
    assert h.status is HealthStatus.BLOCKED


def test_health_down_on_network_error():
    import requests

    routes = {
        "https://err.example/robots.txt": _Resp(404, ""),
        "https://err.example": requests.ConnectionError("refused"),
    }
    f, _ = _fetcher(routes)
    h = check_source(_Src(4, "Err", "err.example"), fetcher=f)
    assert h.status is HealthStatus.DOWN


def test_health_unknown_on_a_genuinely_unforeseen_exception():
    """Audit finding 2026-07-17 (L3): check_source only explicitly caught
    RobotsDisallowed/RobotsUnavailable/FetchError -- every FORESEEABLE I/O
    failure path in EthicalFetcher.fetch() wraps into one of those, but that
    was an IMPLICIT contract, and sources_health (api/monitoring.py) runs
    check_source over every probed source in a plain list comprehension with
    NO per-source try/except -- so a genuinely unexpected exception type
    would have aborted the WHOLE batch, losing every other source's result
    too. A RuntimeError is not a requests.RequestException subclass, so
    EthicalFetcher.fetch() does not wrap it -- it must still degrade to a
    per-source result, never propagate."""
    routes = {
        "https://weird.example/robots.txt": _Resp(404, ""),
        "https://weird.example": RuntimeError("a genuinely unforeseen failure"),
    }
    f, _ = _fetcher(routes)
    h = check_source(_Src(5, "Weird", "weird.example"), fetcher=f)
    assert h.status is HealthStatus.UNKNOWN
    assert "unexpected error" in (h.detail or "")


# --------------------------------------------------------------------------- #
# anomalies
# --------------------------------------------------------------------------- #


def test_anomaly_flags_spike():
    counts = {date(2026, 1, d): 2 for d in range(1, 11)}
    counts[date(2026, 1, 11)] = 50  # spike
    anomalies = volume_anomalies(counts, z_threshold=2.0)
    days = {a.day for a in anomalies}
    assert date(2026, 1, 11) in days


def test_anomaly_insufficient_days():
    assert volume_anomalies({date(2026, 1, 1): 5, date(2026, 1, 2): 6}) == []


def test_anomaly_no_variance():
    counts = {date(2026, 1, d): 3 for d in range(1, 8)}
    assert volume_anomalies(counts) == []
