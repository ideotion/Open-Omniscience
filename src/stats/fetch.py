"""
Live fetch for official machine-readable statistics (Group N, official-statistics
ingestion — the networked layer over the merged offline parser).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the ONLY networked layer for official statistics. It fetches through the
guarded session factory (``src.safety.fetcher.guarded_session``) — so every request
honours the global network kill switch (airplane mode) and the protected-mode proxy
(Tor), and transport is NEVER silently downgraded to clearnet (a §0.5 non-negotiable).
The live fetch egresses over the user's configured transport; callers gate it behind
the ONE network-consent popup + a visible task-manager job (those live in the API
layer, a later slice).

It DELEGATES all parsing to ``src.stats.sdmx`` — no parsing logic is duplicated here.
This module only builds the documented endpoint URLs, performs the guarded GET, and
hands the decoded JSON to ``parse_worldbank`` / ``parse_sdmx_json``. It NEVER averages,
ranks, or scores anything (the parser's honesty rules carry through unchanged: a
published gap → ``value=None``, ``extracted_at`` is the caller-stamped vintage).

We do NOT apply robots logic here: these are documented public API/SDMX endpoints
that follow their OWN service etiquette (handled at the call sites), not generic
crawl robots — blanket-applying robots would wrongly block legitimate API use (see
the ``guarded_session`` docstring). The kill switch + proxy still apply to every
request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode

from src.ingest import DEFAULT_USER_AGENT, kill_switch_active
from src.safety.fetcher import guarded_session
from src.stats.sdmx import StatFigure, parse_sdmx_json, parse_worldbank

# Dated provenance: the documented public JSON / SDMX-JSON endpoints as of
# STATS_API_AS_OF. Verify-on-use — do NOT fabricate exotic endpoints; if a host
# moves its API, re-confirm against its published docs and bump the date.
STATS_API_AS_OF = "2026-06"
WORLDBANK_API_BASE = "https://api.worldbank.org/v2"
EUROSTAT_API_BASE = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
)

# Generous default timeout: a fetch may egress over Tor, which is slow — a tight
# timeout would spuriously fail honest requests. Seconds.
DEFAULT_TIMEOUT_S = 30.0

# A getter takes a URL and returns a requests-like response (``.json()`` /
# ``.raise_for_status()`` / ``.status_code``). Injectable so tests need no socket.
Getter = Callable[[str], Any]


def _now_iso() -> str:
    """The vintage marker: current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def worldbank_url(indicator: str, country: str = "all", *, per_page: int = 1000) -> str:
    """Build a World Bank API v2 JSON URL for ``indicator`` over ``country``.

    Shape: ``{base}/country/{country}/indicator/{indicator}?format=json&per_page=N``.
    Path segments are URL-encoded defensively. An empty indicator is a programming
    error, not a fetchable request → ``ValueError``.
    """
    if not indicator or not indicator.strip():
        raise ValueError("worldbank_url: indicator must be a non-empty string")
    ind = quote(indicator.strip(), safe="")
    ctry = quote((country or "all").strip(), safe="")
    return (
        f"{WORLDBANK_API_BASE}/country/{ctry}/indicator/{ind}"
        f"?format=json&per_page={int(per_page)}"
    )


def eurostat_url(dataset: str, params: dict[str, str] | None = None) -> str:
    """Build a Eurostat SDMX-JSON dissemination URL for ``dataset``.

    Shape: ``{base}/{dataset}?format=JSON`` plus any extra ``params`` (urlencoded,
    sorted for deterministic output). An empty dataset → ``ValueError``.
    """
    if not dataset or not dataset.strip():
        raise ValueError("eurostat_url: dataset must be a non-empty string")
    ds = quote(dataset.strip(), safe="")
    url = f"{EUROSTAT_API_BASE}/{ds}?format=JSON"
    if params:
        # Sorted for determinism (stable URLs across runs / circuit isolation tokens).
        url += "&" + urlencode(sorted(params.items()))
    return url


def _default_getter(url: str) -> Any:
    """The production getter: a guarded GET (kill switch + protected-mode proxy).

    A per-URL ``isolation_token`` gives each request its own Tor circuit (no-op for
    non-SOCKS / no proxy), so distinct fetches are unlinkable over Tor.
    """
    session = guarded_session(user_agent=DEFAULT_USER_AGENT, isolation_token=url)
    return session.get(url, timeout=DEFAULT_TIMEOUT_S)


def fetch_worldbank(
    indicator: str,
    country: str = "all",
    *,
    get: Getter | None = None,
    extracted_at: str | None = None,
    per_page: int = 1000,
) -> list[StatFigure]:
    """Fetch a World Bank indicator live and parse it into ``StatFigure`` rows.

    ``get`` is injectable for tests (any ``url -> response``); the default routes
    through the guarded session. ``extracted_at`` stamps the vintage (defaults to
    now). Delegates parsing to :func:`src.stats.sdmx.parse_worldbank` — no parsing
    here.
    """
    # Defense in depth: refuse UP FRONT, before any socket, so the refusal is testable
    # without a real network (the guarded session also refuses, but the up-front guard
    # covers the default path AND any injected getter).
    if kill_switch_active():
        raise RuntimeError("network refused: airplane mode is engaged")
    extracted_at = extracted_at or _now_iso()
    getter = get or _default_getter
    resp = getter(worldbank_url(indicator, country, per_page=per_page))
    resp.raise_for_status()
    payload = resp.json()
    return parse_worldbank(payload, agency="worldbank", extracted_at=extracted_at)


def fetch_eurostat(
    dataset: str,
    *,
    params: dict[str, str] | None = None,
    get: Getter | None = None,
    extracted_at: str | None = None,
    agency: str = "eurostat",
) -> list[StatFigure]:
    """Fetch a Eurostat SDMX-JSON dataset live and parse it into ``StatFigure`` rows.

    Same shape as :func:`fetch_worldbank`: the kill switch refuses up front, ``get``
    is injectable, ``extracted_at`` stamps the vintage. Delegates parsing to
    :func:`src.stats.sdmx.parse_sdmx_json` — no parsing here. ``agency`` lets the same
    SDMX path serve other SDMX-JSON producers (e.g. IMF) under their own agency code.
    """
    if kill_switch_active():
        raise RuntimeError("network refused: airplane mode is engaged")
    extracted_at = extracted_at or _now_iso()
    getter = get or _default_getter
    resp = getter(eurostat_url(dataset, params))
    resp.raise_for_status()
    payload = resp.json()
    return parse_sdmx_json(payload, agency=agency, extracted_at=extracted_at)
