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

import os

from src.ingest import DEFAULT_USER_AGENT, EthicalFetcher
from src.safety.settings import GENERIC_USER_AGENT, load_settings


def make_fetcher(**overrides) -> EthicalFetcher:
    """Build an EthicalFetcher per the current safety settings.

    ``overrides`` (e.g. ``session=...`` for tests) pass straight through.
    """
    s = load_settings()
    user_agent = GENERIC_USER_AGENT if s.is_protected else DEFAULT_USER_AGENT
    proxy = s.http_proxy or None if s.is_protected else None
    params = {
        "user_agent": user_agent,
        "min_interval_s": float(os.getenv("OO_FETCH_MIN_INTERVAL", "1.0")),
        "timeout": float(os.getenv("OO_FETCH_TIMEOUT", "30")),
        "proxy": proxy,
        # Bounded retry/backoff for transient failures (finding BUG-02).
        "max_retries": int(os.getenv("OO_FETCH_MAX_RETRIES", "2")),
        "retry_backoff_s": float(os.getenv("OO_FETCH_RETRY_BACKOFF", "0.5")),
    }
    params.update(overrides)
    return EthicalFetcher(**params)
