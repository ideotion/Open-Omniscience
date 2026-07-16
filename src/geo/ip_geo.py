"""
Offline IP geolocation (data-architecture Slice 6b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maps a captured server IP (Slice 6a) to an approximate location, **fully offline, no
live API ever**. Two levels:

  * COUNTRY level — a dated CC-licensed range table bundled in-repo
    (``src/geo/data/dbip_country_lite.csv[.gz]``), built by ``scripts/build_ip_geo.py``.
    The chosen source is **DB-IP IP-to-Country Lite (CC BY 4.0)** — rows of
    ``start_ip,end_ip,country_code`` (ISO 3166-1 alpha-2). Attribution is mandatory and
    is carried in :data:`ATTRIBUTION` + surfaced by the map layer.
  * CITY level — too large to bundle, so it is a ONE-TIME consented download into
    ``data_dir()/ip_geo/`` (like a wiki dump / model), never fetched at boot. When a city
    DB is present it is preferred; otherwise we fall back to the country level.

Honesty rules (binding, maintainer ruling 2026-06-19):
  * **Zero network at lookup time** — :func:`lookup` only reads local files (a test
    proves no socket is opened). The geo DB is bundled / downloaded by an explicit
    action, never on the lookup path or at boot.
  * **Never fabricate a location.** An unknown IP, a missing DB, or a Tor-"unavailable"
    IP returns ``level="unavailable"`` with a reason — never a guessed coordinate.
  * The location is the SERVER's neighbourhood (often a CDN edge / anycast) — NOT proof
    of the publisher's origin. The caveat travels with every result and is shown by 6c.
  * **Re-geolocation is a new vintage**, never an overwrite: every result carries
    ``db_vintage`` so a later lookup against a fresher DB is distinguishable.

DATA: the country table IS bundled (``data/dbip_country_lite.csv.gz``, ~4.4 MB,
701k IPv4+IPv6 ranges, vintage :data:`IP_GEO_AS_OF`). The official db-ip.com download is
network-blocked in the sandbox (403), so it is sourced from the DB-IP CC BY 4.0 mirror in
``sapics/ip-location-db`` (identical ``start,end,CC`` format); ``scripts/build_ip_geo.py``
refreshes it from either source. The freshness test pins the vintage within a sane window.
``OO_IP_GEO_DB`` / ``OO_IP_GEO_CITY_DB`` override the paths (an env path that does not exist
disables the bundled table — used to test the honest no-DB state).
"""

from __future__ import annotations

import bisect
import csv
import gzip
import ipaddress
import logging
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

_LOG = logging.getLogger(__name__)

# When the bundled COUNTRY table was last refreshed. "unbundled" until the maintainer
# runs scripts/build_ip_geo.py on a networked machine (the freshness test then asserts a
# real YYYY-MM within a sane window). DB-IP refreshes monthly.
IP_GEO_AS_OF = "2026-07"

# Mandatory CC BY 4.0 attribution for the bundled country table.
ATTRIBUTION = "IP geolocation by DB-IP (https://db-ip.com) — CC BY 4.0"

_BUNDLED_COUNTRY = Path(__file__).with_name("data") / "dbip_country_lite.csv"


def _country_db_path() -> Path | None:
    """The country range table path: env override, then the bundled file, else None."""
    override = os.getenv("OO_IP_GEO_DB")
    if override:
        p = Path(override)
        return p if p.exists() else None
    for cand in (_BUNDLED_COUNTRY, _BUNDLED_COUNTRY.with_suffix(".csv.gz")):
        if cand.exists():
            return cand
    return None


def _city_db_path() -> Path | None:
    """The optional CITY table (downloaded on demand into data_dir, never at boot)."""
    override = os.getenv("OO_IP_GEO_CITY_DB")
    if override:
        p = Path(override)
        return p if p.exists() else None
    try:
        from src.paths import data_dir

        for name in ("dbip_city_lite.csv", "dbip_city_lite.csv.gz"):
            cand = Path(data_dir()) / "ip_geo" / name
            if cand.exists():
                return cand
    except Exception:  # noqa: BLE001 - data_dir unavailable in some contexts
        pass
    return None


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(
        path, encoding="utf-8"
    )


def _to_int(ip_str: str):
    """(version, int) for an IP string, or None if it is not a valid address."""
    try:
        addr = ipaddress.ip_address(ip_str.strip())
        return addr.version, int(addr)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _country_ranges(path_str: str) -> dict[int, tuple[list[int], list[int], list[str]]]:
    """Parse the country CSV into per-version (ends, starts, ccs) arrays sorted by end,
    for an O(log n) bisect lookup. Cached by path. Bad rows are skipped (never crash)."""
    by_ver: dict[int, list[tuple[int, int, str]]] = {4: [], 6: []}
    path = Path(path_str)
    with _open_text(path) as fh:
        for row in csv.reader(fh):
            if len(row) < 3:
                continue
            lo, hi = _to_int(row[0]), _to_int(row[1])
            cc = (row[2] or "").strip().lower()
            if not lo or not hi or lo[0] != hi[0] or len(cc) != 2:
                continue
            by_ver[lo[0]].append((hi[1], lo[1], cc))  # (end, start, cc)
    out: dict[int, tuple[list[int], list[int], list[str]]] = {}
    for ver, rows in by_ver.items():
        rows.sort()
        out[ver] = ([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
    return out


def _country_for(ip_str: str) -> str | None:
    path = _country_db_path()
    parsed = _to_int(ip_str)
    if not path or not parsed:
        return None
    ver, val = parsed
    ends, starts, ccs = _country_ranges(str(path)).get(ver, ([], [], []))
    i = bisect.bisect_left(ends, val)  # first range whose end >= ip
    if i < len(ends) and starts[i] <= val <= ends[i]:
        return ccs[i]
    return None


def _city_for(ip_str: str) -> dict | None:
    """City-level lat/lon straight from a present city DB (dbip-city-lite layout:
    start,end,continent,country,state,city,lat,lon). None if no city DB / no hit."""
    path = _city_db_path()
    parsed = _to_int(ip_str)
    if not path or not parsed:
        return None
    ver, val = parsed
    try:
        with _open_text(path) as fh:
            for row in csv.reader(fh):
                if len(row) < 8:
                    continue
                lo, hi = _to_int(row[0]), _to_int(row[1])
                if not lo or not hi or lo[0] != ver:
                    continue
                if lo[1] <= val <= hi[1]:
                    try:
                        return {
                            "country": (row[3] or "").strip().lower() or None,
                            "lat": float(row[6]),
                            "lon": float(row[7]),
                            "place": (row[5] or "").strip() or None,
                        }
                    except (ValueError, IndexError):
                        return None
    except OSError:
        return None
    return None


def db_vintage() -> str:
    return IP_GEO_AS_OF


def lookup(ip: str | None) -> dict:
    """Geolocate a server IP OFFLINE. Returns a dict with a stated ``level``:

      * ``"city"``        — a city DB was present and matched (lat/lon from it);
      * ``"country"``     — country resolved; coordinates are a country stand-in point;
      * ``"unavailable"`` — no DB / unknown IP / no IP (with a ``reason``).

    Always carries ``db_vintage`` and ``attribution`` and NEVER a fabricated coordinate.
    """
    base = {
        "ip": ip,
        "country": None,
        "lat": None,
        "lon": None,
        "level": "unavailable",
        "db_vintage": IP_GEO_AS_OF,
        "attribution": ATTRIBUTION,
        "caveat": (
            "Approximate server location (often a CDN edge / anycast), not proof of the "
            "publisher's origin; dated offline DB; unavailable over Tor."
        ),
    }
    if not ip:
        return {**base, "reason": "no IP captured"}
    if _to_int(ip) is None:
        return {**base, "reason": "not a valid IP"}

    # Prefer the city DB when present (lat/lon straight from it).
    city = _city_for(ip)
    if city and city.get("lat") is not None:
        return {**base, "country": city.get("country"), "lat": city["lat"],
                "lon": city["lon"], "level": "city", "place": city.get("place")}

    cc = _country_for(ip)
    if not cc:
        reason = "no geo DB bundled" if _country_db_path() is None else "IP not in DB"
        return {**base, "reason": reason}

    # Country resolved -> a country stand-in coordinate from the gazetteer (approximate).
    lat = lon = None
    try:
        from src.timemap.geocode import geocode

        pt = geocode(country=cc)
        if pt:
            lat, lon = pt.get("lat"), pt.get("lon")
    except Exception:  # noqa: BLE001 - coords are a bonus; the country is the fact
        pass
    return {**base, "country": cc, "lat": lat, "lon": lon, "level": "country"}


def freshness() -> dict:
    """Report whether a real country DB is bundled and how old its vintage is."""
    path = _country_db_path()
    bundled = path is not None and IP_GEO_AS_OF != "unbundled"
    out = {"bundled": bundled, "as_of": IP_GEO_AS_OF, "path": str(path) if path else None}
    if bundled:
        try:
            y, m = (int(x) for x in IP_GEO_AS_OF.split("-")[:2])
            age_months = (date.today().year - y) * 12 + (date.today().month - m)
            out["age_months"] = age_months
        except (ValueError, IndexError):
            out["age_months"] = None
    return out
