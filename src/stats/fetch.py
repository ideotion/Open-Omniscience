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

import csv
import io
import logging
import re
from datetime import UTC, datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode, urljoin

from src.ingest import DEFAULT_USER_AGENT, kill_switch_active
from src.ingest.fetch_verdict import NETWORK_REFUSED
from src.safety.fetcher import RedirectRefused, guarded_session
from src.stats.gistemp import GistempParse
from src.stats.owid_climate import CATALOG as OWID_CLIMATE_CATALOG
from src.stats.owid_climate import OwidParse
from src.stats.sdmx import (
    StatFigure,
    parse_csv,
    parse_jsonstat,
    parse_sdmx_json,
    parse_worldbank,
)

# Dated provenance: the documented public JSON / SDMX-JSON endpoints as of
# STATS_API_AS_OF. Verify-on-use — do NOT fabricate exotic endpoints; if a host
# moves its API, re-confirm against its published docs and bump the date.
logger = logging.getLogger(__name__)

STATS_API_AS_OF = "2026-06"
WORLDBANK_API_BASE = "https://api.worldbank.org/v2"
EUROSTAT_API_BASE = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
)
# Our World in Data per-chart "Full data (CSV)" export. Each grapher chart exposes a
# tidy CSV at {base}/{slug}.csv (Entity,Code,Year,<metric>). Documented OWID data-API
# params: csvType=full (all entities/years), useColumnShortNames=true (stable machine
# column names). Verify-on-use — a wrong slug/param fails LOUDLY (HTTP error / no rows),
# never a fabricated figure; re-confirm against OWID's published data API if it moves.
OWID_GRAPHER_BASE = "https://ourworldindata.org/grapher"
# NASA GISS GISTEMP v4 table data: one CSV per region (GLB / NH / SH), anomalies in degC
# against 1951-1980. NOT verified against a live download (the build sandbox cannot reach
# the host): a wrong path or shape fails LOUDLY (HTTP error / looks_unrecognised).
GISTEMP_BASE = "https://data.giss.nasa.gov/gistemp/tabledata_v4"
# OWID's bulk CSVs live in its public GitHub data repos (owid/co2-data, owid/energy-data); the
# path is pinned to the owid organisation, and the file name comes from the curated catalog.
OWID_BULK_BASE = "https://raw.githubusercontent.com/owid"
OWID_BULK_REPOS = {"co2": "co2-data", "energy": "energy-data"}
OWID_FIRST_YEAR = 1750  # the earliest year in the CO2 table
OWID_AREAS_ALLOWANCE = 400  # countries plus aggregates, generous (about 250 today)
OWID_ROW_CHARS_ALLOWANCE = 2000  # a wide row, generous (about 600 to 1,500 characters today)
# The body bound is DERIVED from the table's own shape, not a fixed number (see gistemp_max_chars).
GISTEMP_FIRST_YEAR = 1880
GISTEMP_LINE_ALLOWANCE = 200  # chars per row; a real row is about 120
GISTEMP_HEADER_ALLOWANCE = 4096  # title, blank and header lines, with slack

# Body bounds for the four fetchers that used to read without limit. Each is DERIVED from the table's shape (rows x a generous per-row
# allowance + header slack), like the climate bounds below, and grows with the calendar or the request, never a fixed cap to remember.
WORLDBANK_OBSERVATION_ALLOWANCE = 1000  # chars per observation object; a real one is about 250
WORLDBANK_META_ALLOWANCE = 4096  # the page-meta object, with slack
# Eurostat's synchronous dissemination API documents a limit of 50,000 values per query (a larger selection is refused or deferred); the
# figure is PROVISIONAL (documented, not verified against a live response from this sandbox): if it moves, the bound moves with it here.
EUROSTAT_VALUES_PER_QUERY = 50_000
EUROSTAT_CELL_ALLOWANCE = 300  # chars per value, its status flag and its index entries; a real cell is about 25
EUROSTAT_HEADER_ALLOWANCE = 2_000_000  # dimension labels and categories, with slack
OWID_GRAPHER_ROW_CHARS_ALLOWANCE = 200  # Entity,Code,Year,value; a real row is about 50
JSONSTAT_DEFAULT_MAX_CELLS = 500_000  # PxWeb instances cap a query at roughly 100,000 to 800,000 cells; a caller with a bigger table passes max_cells
JSONSTAT_CELL_ALLOWANCE = 40  # chars per value in the flat ``value`` array; a real one is about 8
JSONSTAT_HEADER_ALLOWANCE = 2_000_000  # dimension labels and categories, with slack

# Generous default timeout: a fetch may egress over Tor, which is slow — a tight
# timeout would spuriously fail honest requests. Seconds.
DEFAULT_TIMEOUT_S = 30.0

# A getter takes a URL and returns a requests-like response (``.json()`` /
# ``.raise_for_status()`` / ``.status_code``). Injectable so tests need no socket.
Getter = Callable[[str], Any]


def _now_iso() -> str:
    """The vintage marker: current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def worldbank_url(
    indicator: str, country: str = "all", *, per_page: int = 1000, page: int = 1
) -> str:
    """Build a World Bank API v2 JSON URL for ``indicator`` over ``country``.

    Shape: ``{base}/country/{country}/indicator/{indicator}?format=json&per_page=N``,
    plus ``&page=N`` for any page past the first (page 1 is the server's default, so it
    is omitted — that keeps a single-page fetch's URL byte-identical to the pre-pagination
    one, which matters because the URL is also the Tor circuit-isolation token).
    Path segments are URL-encoded defensively. An empty indicator is a programming
    error, not a fetchable request → ``ValueError``.
    """
    if not indicator or not indicator.strip():
        raise ValueError("worldbank_url: indicator must be a non-empty string")
    ind = quote(indicator.strip(), safe="")
    ctry = quote((country or "all").strip(), safe=";")  # ";" separates countries in one request; the directory pin refuses a %-escape
    url = (
        f"{WORLDBANK_API_BASE}/country/{ctry}/indicator/{ind}"
        f"?format=json&per_page={int(per_page)}"
    )
    if int(page) > 1:
        url += f"&page={int(page)}"
    return url


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


def owid_grapher_url(slug: str) -> str:
    """Build the Our World in Data per-chart "Full data (CSV)" URL for ``slug``.

    Shape: ``{base}/{slug}.csv?v=1&csvType=full&useColumnShortNames=true`` — the
    documented OWID data-API export (all entities/years, stable short column names). An
    empty slug is a programming error, not a fetchable request → ``ValueError``.
    """
    if not slug or not slug.strip():
        raise ValueError("owid_grapher_url: slug must be a non-empty string")
    s = quote(slug.strip().strip("/"), safe="")
    return f"{OWID_GRAPHER_BASE}/{s}.csv?v=1&csvType=full&useColumnShortNames=true"


# OWID grapher CSVs are tidy: Entity, Code, Year, <one metric column>. These three are
# the KEY columns (who / which / when); the remaining column is the observation.
_OWID_KEY_COLS = ("entity", "code", "year")


def _owid_value_column(text: str) -> str:
    """Auto-detect the single observation column of a tidy OWID grapher CSV.

    Returns the one header column that is NOT a key column (Entity/Code/Year,
    case-insensitive). Raises ``ValueError`` LOUDLY when zero or several remain — the
    caller must then pass ``value_col`` explicitly (we never guess among many). Uses the
    csv reader so a quoted column name containing a comma is handled correctly.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError("owid: empty CSV (no header row)") from exc
    cols = [c.lstrip("\ufeff").strip() for c in header]
    data = [c for c in cols if c.lower() not in _OWID_KEY_COLS]
    if len(data) == 1:
        return data[0]
    raise ValueError(
        f"owid: cannot auto-detect the value column among {cols!r}; pass value_col explicitly"
    )


# Each climate fetcher's session may talk only to its own host AND, on a host that serves many tenants, only to its own directories:
# a redirect hop anywhere else is refused (guarded_session(allowed_hosts=..., allowed_path_prefixes=...)). The consent popup's
# "climate" lane names all the climate hosts.
GISTEMP_HOSTS = ("data.giss.nasa.gov",)
GISTEMP_PATHS = ("/gistemp/tabledata_v4/",)
OWID_HOSTS = ("raw.githubusercontent.com",)
OWID_PATHS = ("/owid/co2-data/", "/owid/energy-data/")  # raw.githubusercontent.com serves EVERY repository: the directory is the pin
USGS_HOSTS = ("earthquake.usgs.gov",)
USGS_PATHS = ("/fdsnws/event/1/",)
# The official-statistics fetchers. World Bank and Eurostat pin their documented API directories; the OWID grapher pins its chart
# directory. JSON-stat has NO list: the caller supplies an arbitrary publisher URL, so only its body is bounded.
WORLDBANK_HOSTS = ("api.worldbank.org",)
WORLDBANK_PATHS = ("/v2/",)
EUROSTAT_HOSTS = ("ec.europa.eu",)  # a multi-tenant host: the directory is the pin
EUROSTAT_PATHS = ("/eurostat/api/dissemination/statistics/1.0/data/",)
OWID_GRAPHER_HOSTS = ("ourworldindata.org",)
OWID_GRAPHER_PATHS = ("/grapher/",)
_UTF8_MAX_BYTES_PER_CHAR = 4
_READ_CHUNK = 64 * 1024


class BodyTooLarge(ValueError):
    """A response body went past the bound its table's own shape allows. The message names the sizes, never the URL."""


def _bounded_get(session: Any, url: str, *, max_chars: int) -> Any:
    """A GET on ``session`` (a ``guarded_session`` the caller built with its own host and directory lists) that STOPS READING at
    ``max_chars`` characters' worth of bytes, instead of reading everything and measuring after.

    The bound each fetcher derives from its table's shape (``gistemp_max_chars``, ``owid_max_chars``, the USGS count) was checked after
    ``requests`` had already downloaded and decoded the whole body, so an upstream that sent an endless or oversized body grew memory
    without limit before the check ran. Here the body is read in chunks and the read is abandoned the moment it passes
    ``max_chars * 4`` bytes (a UTF-8 character is at most four bytes, so a body over that is over ``max_chars`` characters whatever it
    holds), or at once when the server DECLARES a longer ``Content-Length``. ``iter_content`` decodes a compressed body, so the bound
    holds on the decoded size and a compression bomb is stopped the same way. The bytes read are put back on the response, so
    ``.text``, ``.json()`` and ``.raise_for_status()`` behave as on any other response; an error status is not read at all (the caller's
    ``raise_for_status`` names it), and a redirect body is closed unread.

    What it does NOT bound is time: the request timeout limits each read, not the whole transfer, so a server that drips bytes just
    under the bound keeps the call waiting. That is named, not hidden.
    """
    max_bytes = max_chars * _UTF8_MAX_BYTES_PER_CHAR
    # Redirects are followed HERE, one hop at a time, never by ``requests``. Passing ``allow_redirects=False`` is NOT enough: ``Session.send``
    # still starts ``resolve_redirects`` on the first response (to fill ``_next``), and that generator reads the whole 3xx body
    # (``resp.content``) before it yields, an unbounded read of a body nobody asked for. ``get_redirect_target`` answering ``None`` makes
    # it yield nothing, so no 3xx body is read; the ``Location`` is read below. Every hop goes through ``session.get`` -> ``request`` ->
    # ``send``, so the kill switch, the host list and the directory list run on each hop exactly as on the first request.
    session.get_redirect_target = lambda _resp: None
    resp = session.get(url, timeout=DEFAULT_TIMEOUT_S, stream=True, allow_redirects=False)
    try:
        hops = 0
        while resp.is_redirect:
            hops += 1
            if hops > session.max_redirects:
                raise RedirectRefused("too many redirects")
            location = resp.headers["Location"]
            if not location.isascii():
                raise RedirectRefused("the redirect target is not plain ASCII")
            target = urljoin(resp.url, location)
            resp.close()  # unread
            resp = session.get(target, timeout=DEFAULT_TIMEOUT_S, stream=True, allow_redirects=False)
        if resp.status_code >= 400:
            resp.close()  # unread: the caller's ``raise_for_status`` names the status; an error page is not read at all
            return resp
        declared = (resp.headers.get("Content-Length") or "").strip()
        if declared.isascii() and declared.isdigit() and int(declared) > max_bytes:
            raise BodyTooLarge(f"the server declares {declared} bytes, over the {max_bytes} the table's own shape allows")
        body = bytearray()  # one copy, not a list of chunks joined into a second one
        for chunk in resp.iter_content(_READ_CHUNK):
            body += chunk
            if len(body) > max_bytes:
                raise BodyTooLarge(f"the body went past {max_bytes} bytes, the most the table's own shape allows; reading stopped")
        resp._content = bytes(body)  # what ``Response.content`` would have built; ``text`` and ``json`` read it
        resp._content_consumed = True
    except BaseException:
        resp.close()
        raise
    return resp


def _gistemp_getter(url: str) -> Any:
    session = guarded_session(
        user_agent=DEFAULT_USER_AGENT, isolation_token=url, allowed_hosts=GISTEMP_HOSTS, allowed_path_prefixes=GISTEMP_PATHS
    )
    return _bounded_get(session, url, max_chars=gistemp_max_chars())


def _owid_bulk_getter(url: str) -> Any:
    session = guarded_session(
        user_agent=DEFAULT_USER_AGENT, isolation_token=url, allowed_hosts=OWID_HOSTS, allowed_path_prefixes=OWID_PATHS
    )
    return _bounded_get(session, url, max_chars=owid_max_chars())


def _usgs_getter(max_chars: int) -> Getter:
    def getter(url: str) -> Any:
        session = guarded_session(
            user_agent=DEFAULT_USER_AGENT, isolation_token=url, allowed_hosts=USGS_HOSTS, allowed_path_prefixes=USGS_PATHS
        )
        return _bounded_get(session, url, max_chars=max_chars)

    return getter


def worldbank_max_chars(per_page: int) -> int:
    """The longest World Bank page that can still be a page of ``per_page`` observations."""
    return max(int(per_page), 1) * WORLDBANK_OBSERVATION_ALLOWANCE + WORLDBANK_META_ALLOWANCE


def eurostat_max_chars() -> int:
    """The longest Eurostat answer: the documented per-query value limit times a generous per-cell allowance, plus the labels."""
    return EUROSTAT_VALUES_PER_QUERY * EUROSTAT_CELL_ALLOWANCE + EUROSTAT_HEADER_ALLOWANCE


def owid_grapher_max_chars(now_year: int | None = None) -> int:
    """The longest OWID grapher CSV: one row per area and year from 1750 to next year, times a generous row allowance."""
    year = now_year if now_year is not None else datetime.now(UTC).year
    return (year + 1 - OWID_FIRST_YEAR + 1) * OWID_AREAS_ALLOWANCE * OWID_GRAPHER_ROW_CHARS_ALLOWANCE


def jsonstat_max_chars(max_cells: int = JSONSTAT_DEFAULT_MAX_CELLS) -> int:
    """The longest JSON-stat body for a table of at most ``max_cells`` values."""
    return max(int(max_cells), 1) * JSONSTAT_CELL_ALLOWANCE + JSONSTAT_HEADER_ALLOWANCE


def _worldbank_getter(max_chars: int) -> Getter:
    def getter(url: str) -> Any:
        session = guarded_session(
            user_agent=DEFAULT_USER_AGENT, isolation_token=url, allowed_hosts=WORLDBANK_HOSTS, allowed_path_prefixes=WORLDBANK_PATHS
        )
        return _bounded_get(session, url, max_chars=max_chars)

    return getter


def _eurostat_getter(url: str) -> Any:
    session = guarded_session(
        user_agent=DEFAULT_USER_AGENT, isolation_token=url, allowed_hosts=EUROSTAT_HOSTS, allowed_path_prefixes=EUROSTAT_PATHS
    )
    return _bounded_get(session, url, max_chars=eurostat_max_chars())


def _owid_grapher_getter(url: str) -> Any:
    session = guarded_session(
        user_agent=DEFAULT_USER_AGENT, isolation_token=url, allowed_hosts=OWID_GRAPHER_HOSTS, allowed_path_prefixes=OWID_GRAPHER_PATHS
    )
    return _bounded_get(session, url, max_chars=owid_grapher_max_chars())


def _jsonstat_getter(max_chars: int) -> Getter:
    def getter(url: str) -> Any:
        # No host or directory list: the caller names any publisher. The body bound is the protection that applies to every one.
        session = guarded_session(user_agent=DEFAULT_USER_AGENT, isolation_token=url)
        return _bounded_get(session, url, max_chars=max_chars)

    return getter


def _worldbank_page_count(payload: Any) -> int:
    """Total pages reported by a World Bank ``[page_meta, [observations]]`` payload.

    Returns 1 for anything unreadable — a bare observation list, a missing or non-numeric
    ``pages``, a meta that is not a dict. Defensive by design: the caller uses this to
    decide how many MORE requests to make, so "I could not tell" must mean "stop", never
    "keep going".
    """
    if not (isinstance(payload, list) and payload and isinstance(payload[0], dict)):
        return 1
    raw = payload[0].get("pages")
    try:
        # The API sends integers, but a string "18" is cheap to accept and a float,
        # None or "many" must not raise — int(bool) is also excluded, being nonsense here.
        pages = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    return pages if pages >= 1 else 1


# Safety valve, not an expected path. One indicator over every economy and every year is
# ~17k observations = ~18 pages at the default per_page, so tripping this means the meta
# is wrong or hostile. Bounding REQUESTS (not rows) keeps the guarantee independent of
# per_page. Hitting it logs loudly rather than returning a short answer silently.
_WORLDBANK_MAX_PAGES = 200


def fetch_worldbank(
    indicator: str,
    country: str = "all",
    *,
    get: Getter | None = None,
    extracted_at: str | None = None,
    per_page: int = 1000,
) -> list[StatFigure]:
    """Fetch a World Bank indicator live and parse it into ``StatFigure`` rows.

    PAGINATES (field feedback 2026-08-07, item 8). The World Bank returns a
    ``[page_meta, [observations]]`` envelope and caps a response at ``per_page`` rows;
    the earlier version made exactly ONE request and discarded ``page_meta`` entirely, so
    for ``country=all`` — ~266 economies × ~65 years ≈ 17k rows — roughly 94% of every
    indicator was silently missing. The stored data looked like a short, recent series
    rather than a truncated one, which is why it read as "no data" instead of as an error.

    Requests page 1, reads the reported page count, then walks pages 2..N concatenating
    observations in order. ``get`` is injectable for tests (any ``url -> response``); the
    default routes through the guarded session, which applies the kill switch, the
    protected-mode proxy and per-URL circuit isolation to EVERY page. ``extracted_at``
    stamps one vintage across all pages, so a series fetched in several requests is a
    single vintage rather than a smear. Delegates parsing to
    :func:`src.stats.sdmx.parse_worldbank` — the parser stays pure and page-unaware.
    """
    # Defense in depth: refuse UP FRONT, before any socket, so the refusal is testable
    # without a real network (the guarded session also refuses, but the up-front guard
    # covers the default path AND any injected getter).
    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    extracted_at = extracted_at or _now_iso()
    getter = get or _worldbank_getter(worldbank_max_chars(per_page))

    resp = getter(worldbank_url(indicator, country, per_page=per_page))
    resp.raise_for_status()
    payload = resp.json()
    figures = parse_worldbank(payload, agency="worldbank", extracted_at=extracted_at)

    total_pages = min(_worldbank_page_count(payload), _WORLDBANK_MAX_PAGES)
    for page in range(2, total_pages + 1):
        resp = getter(worldbank_url(indicator, country, per_page=per_page, page=page))
        resp.raise_for_status()
        rows = parse_worldbank(resp.json(), agency="worldbank", extracted_at=extracted_at)
        if not rows:
            # `pages` over-reported, or the tail is empty. Stop rather than spend the
            # remaining requests on nothing — over Tor those are expensive.
            break
        figures.extend(rows)

    if _worldbank_page_count(payload) > _WORLDBANK_MAX_PAGES:
        logger.warning(
            "worldbank %s/%s reported %s pages; stopped at the %s-page ceiling — the "
            "series is TRUNCATED, not complete",
            country,
            indicator,
            _worldbank_page_count(payload),
            _WORLDBANK_MAX_PAGES,
        )
    return figures


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
        raise RuntimeError(NETWORK_REFUSED)
    extracted_at = extracted_at or _now_iso()
    getter = get or _eurostat_getter
    resp = getter(eurostat_url(dataset, params))
    resp.raise_for_status()
    payload = resp.json()
    return parse_sdmx_json(payload, agency=agency, extracted_at=extracted_at)


def fetch_owid(
    slug: str,
    *,
    value_col: str | None = None,
    series_id: str | None = None,
    agency: str = "owid",
    area_col: str = "Entity",
    code_col: str | None = "Code",
    time_col: str = "Year",
    unit: str | None = None,
    base_year: str | None = None,
    adjustment: str | None = None,
    get: Getter | None = None,
    extracted_at: str | None = None,
) -> list[StatFigure]:
    """Fetch an Our World in Data per-chart CSV live and parse it into ``StatFigure`` rows.

    The CSV path of the stats subsystem (unlocks ``parse_csv`` for live data). Same shape
    as the other fetchers: the kill switch refuses UP FRONT (no socket while airplane mode
    is engaged — testable with an injected getter), ``get`` is injectable, ``extracted_at``
    stamps the vintage. The TEXT response is handed to :func:`src.stats.sdmx.parse_csv` — no
    parsing here.

    ``value_col`` names the observation column; when omitted it is AUTO-DETECTED as the
    single non-key column (a tidy OWID grapher CSV has exactly one), and a CSV with several
    data columns raises LOUDLY (pass ``value_col`` explicitly — we never guess among many).
    ``series_id`` defaults to the ``slug`` (the stable chart identifier). The comparability
    fields (``unit`` / ``base_year`` / ``adjustment``) come from the CALLER's curated config,
    surfaced verbatim, never inferred — OWID CSVs carry no machine-readable unit metadata.
    """
    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    extracted_at = extracted_at or _now_iso()
    getter = get or _owid_grapher_getter
    resp = getter(owid_grapher_url(slug))
    resp.raise_for_status()
    text = resp.text
    col = value_col if (value_col and value_col.strip()) else _owid_value_column(text)
    return parse_csv(
        text,
        agency=agency,
        series_id=(series_id.strip() if series_id and series_id.strip() else slug.strip()),
        extracted_at=extracted_at,
        area_col=area_col,
        time_col=time_col,
        value_col=col,
        code_col=code_col,
        unit=unit,
        base_year=base_year,
        adjustment=adjustment,
    )


def fetch_jsonstat(
    url: str,
    *,
    agency: str,
    series_id: str | None = None,
    get: Getter | None = None,
    extracted_at: str | None = None,
    max_cells: int = JSONSTAT_DEFAULT_MAX_CELLS,
) -> list[StatFigure]:
    """Fetch a JSON-stat dataset live and parse it into ``StatFigure`` rows.

    The JSON-stat path of the stats subsystem (unlocks ``parse_jsonstat`` for live data —
    Eurostat's JSON-stat endpoint, IRENA, and PxWeb instances [Statistics Sweden/Norway/
    Finland] all serve JSON-stat). JSON-stat producers have wildly different URL schemes, so
    the CALLER supplies the documented query ``url`` verbatim — we NEVER fabricate an
    endpoint (a wrong URL fails LOUDLY: an HTTP error / a shape the parser can't read → no
    rows, never a fabricated figure). Same safety shape as the other fetchers: the kill
    switch refuses UP FRONT (no socket while airplane mode is engaged — testable with an
    injected getter), ``get`` is injectable, ``extracted_at`` stamps the vintage. The decoded
    JSON is handed to :func:`src.stats.sdmx.parse_jsonstat` — no parsing here. Pass
    ``series_id`` to pin a single-series slice for unambiguous rows (the parser's contract).

    The body is read under a bound derived from ``max_cells`` (the most values the caller's table can hold) and the read stops when it
    passes it; the host is the caller's, so there is no host list. A table past the default is fetched by passing a larger ``max_cells``.
    """
    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    u = (url or "").strip()
    if not (u.startswith("https://") or u.startswith("http://")):
        raise ValueError("fetch_jsonstat: url must be an http(s) JSON-stat endpoint")
    extracted_at = extracted_at or _now_iso()
    getter = get or _jsonstat_getter(jsonstat_max_chars(max_cells))
    resp = getter(u)
    resp.raise_for_status()
    payload = resp.json()
    return parse_jsonstat(payload, agency=agency, extracted_at=extracted_at, series_id=series_id)


def gistemp_url(region: str = "GLB") -> str:
    """The GISTEMP v4 table CSV URL for ``region`` (``GLB``, ``NH`` or ``SH``)."""
    from src.stats.gistemp import REGIONS

    if region not in REGIONS:
        raise ValueError(f"gistemp_url: region must be one of {REGIONS}, got {region!r}")
    return f"{GISTEMP_BASE}/{region}.Ts+dSST.csv"


def gistemp_max_chars(now_year: int | None = None) -> int:
    """The longest body that can still be this table.

    One row per year from 1880 to the current year plus one (the next year's row may appear
    early), times a generous per-row allowance, plus the header lines. It grows with the data
    each January instead of being a constant someone must remember to raise.
    """
    year = now_year if now_year is not None else datetime.now(UTC).year
    rows = max(year + 1 - GISTEMP_FIRST_YEAR + 1, 1)
    return rows * GISTEMP_LINE_ALLOWANCE + GISTEMP_HEADER_ALLOWANCE


def fetch_gistemp(
    region: str = "GLB",
    *,
    get: Getter | None = None,
    extracted_at: str | None = None,
) -> GistempParse:
    """Fetch one GISTEMP v4 table live and parse it (kill switch refuses UP FRONT).

    Returns the :class:`~src.stats.gistemp.GistempParse` (figures AND refusals). A body that
    parses to nothing but refusals (an HTML error page, a renamed product) raises rather than
    returning an empty series, because an empty list and a wrong file look the same once the
    refusals are dropped.
    """
    from src.stats.gistemp import parse_gistemp

    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    extracted_at = extracted_at or _now_iso()
    getter = get or _gistemp_getter
    resp = getter(gistemp_url(region))
    resp.raise_for_status()
    bound = gistemp_max_chars()
    if len(resp.text) > bound:
        raise ValueError(f"GISTEMP {region}: the response is {len(resp.text)} characters, over the {bound} the table's own shape allows")
    parsed = parse_gistemp(resp.text, region=region, extracted_at=extracted_at)
    if parsed.looks_unrecognised:
        raise ValueError(
            f"GISTEMP {region}: the response is not the expected table "
            f"({parsed.refused_total} lines refused, none parsed)"
        )
    return parsed


# USGS ComCat via the FDSN event service. NOT verified against a live download (the build sandbox
# cannot reach the host): a wrong path or shape fails LOUDLY (HTTP error / looks_unrecognised).
USGS_QUAKES_BASE = "https://earthquake.usgs.gov/fdsnws/event/1"
# The service's own documented per-request maximum; a window that would exceed it is refused
# up front instead of being silently truncated.
USGS_QUAKES_QUERY_LIMIT = 20000
USGS_QUAKES_ROW_ALLOWANCE = 1200  # chars per CSV row; a real row is about 250-350
USGS_QUAKES_HEADER_ALLOWANCE = 4096
_USGS_COUNT_MAX_CHARS = 16  # the count response is a plain integer of at most nine digits (the regex below), plus a newline


def _quakes_params(start_month: str, end_month: str, min_magnitude: float) -> dict[str, str]:
    from datetime import timedelta

    from src.stats.usgs_quakes import month_index, month_label, validate_min_magnitude

    magnitude = validate_min_magnitude(min_magnitude)
    first, last = month_index(start_month), month_index(end_month)
    if last < first:
        raise ValueError("end_month is before start_month")
    # The FDSN endtime is "on or before", so the window ends one millisecond short of the next month.
    after = month_index(month_label(last + 1))
    end = datetime(after // 12, after % 12 + 1, 1) - timedelta(milliseconds=1)
    return {
        "starttime": f"{month_label(first)}-01T00:00:00",
        "endtime": end.strftime("%Y-%m-%dT%H:%M:%S.") + f"{end.microsecond // 1000:03d}",
        "minmagnitude": f"{magnitude:.1f}",
        "eventtype": "earthquake",
    }


def usgs_quakes_count_url(start_month: str, end_month: str, min_magnitude: float) -> str:
    params = {"format": "plain", **_quakes_params(start_month, end_month, min_magnitude)}
    return f"{USGS_QUAKES_BASE}/count?{urlencode(params)}"


def usgs_quakes_query_url(start_month: str, end_month: str, min_magnitude: float) -> str:
    params = {
        "format": "csv",
        **_quakes_params(start_month, end_month, min_magnitude),
        "orderby": "time-asc",
        "limit": str(USGS_QUAKES_QUERY_LIMIT),
    }
    return f"{USGS_QUAKES_BASE}/query?{urlencode(params)}"


def fetch_usgs_quakes(
    start_month: str,
    end_month: str,
    min_magnitude: float = 5.0,
    *,
    get: Getter | None = None,
    extracted_at: str | None = None,
) -> Any:
    """Fetch the monthly earthquake counts for a window live (kill switch refuses UP FRONT).

    Two requests: the service's own COUNT first, so a window over the per-request maximum is
    refused rather than truncated, and so the body bound is derived from the data's shape
    (count x a per-row allowance) instead of a constant. The second reads the events and parses
    them. A body that parses to nothing but refusals raises.
    """
    from src.stats.usgs_quakes import parse_usgs_quakes

    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    count_url = usgs_quakes_count_url(start_month, end_month, min_magnitude)  # validates the arguments
    query_url = usgs_quakes_query_url(start_month, end_month, min_magnitude)
    extracted_at = extracted_at or _now_iso()
    count_getter = get or _usgs_getter(_USGS_COUNT_MAX_CHARS)
    resp = count_getter(count_url)
    resp.raise_for_status()
    text = resp.text.strip()
    if not re.fullmatch(r"[0-9]{1,9}", text):
        raise ValueError("USGS earthquakes: the count response is not a plain integer")
    declared = int(text)
    if declared > USGS_QUAKES_QUERY_LIMIT:
        raise ValueError(
            f"USGS earthquakes: {declared} events in {start_month}..{end_month} at M>={min_magnitude:g} is over the "
            f"{USGS_QUAKES_QUERY_LIMIT} one request returns; ask for a shorter window or a higher threshold"
        )
    bound = declared * USGS_QUAKES_ROW_ALLOWANCE + USGS_QUAKES_HEADER_ALLOWANCE
    query_getter = get or _usgs_getter(bound)  # the read stops at the bound the count just fixed
    resp = query_getter(query_url)
    resp.raise_for_status()
    if len(resp.text) > bound:
        raise ValueError(f"USGS earthquakes: the response is {len(resp.text)} characters, over the {bound} its declared {declared} events allow")
    parsed = parse_usgs_quakes(
        resp.text, start_month=start_month, end_month=end_month, min_magnitude=min_magnitude, extracted_at=extracted_at
    )
    if parsed.looks_unrecognised:
        raise ValueError(
            f"USGS earthquakes: the response is not the expected catalogue ({parsed.refused_total} lines refused, none parsed)"
        )
    parsed.declared_count = declared
    parsed_events = parsed.rows_read - parsed.excluded_non_earthquake
    if parsed_events != declared:
        raise ValueError(
            f"USGS earthquakes: the service counted {declared} events but {parsed_events} were read "
            f"({parsed.refused_total} rows refused); the catalogue changed between the two requests or the list was cut short, so no series is returned"
        )
    return parsed


def owid_max_chars(now_year: int | None = None) -> int:
    """The longest body that can still be an OWID bulk table: one row per area and year from
    1750 to next year, times a generous per-row allowance. Grows with the data each January."""
    year = now_year if now_year is not None else datetime.now(UTC).year
    return (year + 1 - OWID_FIRST_YEAR + 1) * OWID_AREAS_ALLOWANCE * OWID_ROW_CHARS_ALLOWANCE


def owid_dataset_url(dataset: str) -> str:
    """The raw-CSV URL of a curated OWID bulk dataset (``co2`` or ``energy``)."""
    if dataset not in OWID_BULK_REPOS or dataset not in OWID_CLIMATE_CATALOG:
        raise ValueError(f"owid_dataset_url: dataset must be one of {sorted(OWID_BULK_REPOS)}, got {dataset!r}")
    return f"{OWID_BULK_BASE}/{OWID_BULK_REPOS[dataset]}/master/{OWID_CLIMATE_CATALOG[dataset]['file']}"


def fetch_owid_dataset(
    dataset: str,
    *,
    get: Getter | None = None,
    extracted_at: str | None = None,
) -> OwidParse:
    """Fetch one OWID bulk CSV live and parse it (kill switch refuses UP FRONT).

    An unrecognisable body (an error page, a renamed file, no curated column) raises rather
    than returning an empty series. The body bound is derived from the data's own scale.
    """
    from src.stats.owid_climate import parse_owid

    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    extracted_at = extracted_at or _now_iso()
    getter = get or _owid_bulk_getter
    resp = getter(owid_dataset_url(dataset))
    resp.raise_for_status()
    text = resp.text
    bound = owid_max_chars()
    if len(text) > bound:
        raise ValueError(f"OWID {dataset}: the response is {len(text)} characters, over the {bound} the table's own shape allows")
    parsed = parse_owid(text, dataset=dataset, extracted_at=extracted_at)
    if parsed.looks_unrecognised or parsed.all_gap:
        raise ValueError(
            f"OWID {dataset}: the response is not the expected table "
            f"(all curated cells empty: {parsed.all_gap}, required columns found: {parsed.header_ok}, curated columns found: {len(parsed.columns_present)}, "
            f"rows read: {parsed.rows_read}, records refused: {parsed.refused_total}, lines they covered: {parsed.refused_lines})"
        )
    return parsed
