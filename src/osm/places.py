"""Places from the OSM lane: the name index, the "Places" facet, an object's card, the geocoder.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S05-04 S5, for Q817 = a («Notable Places only -- admin areas, ``place=*`` (cities, towns,
villages), and any object carrying ``wikidata``/``wikipedia`` -- become Articles with a body;
every other POI stays a structured row with its own search facet ("Places")») and Q820 = a («a
local geocoder, for the countries the user ingested, disclosed ("addresses outside your OSM
countries are not located"); never an external geocoding service»).

TWO FULL-TEXT INDEXES IN ``osm.db``, built from the rows an ingest wrote, so a search reads an
index rather than scanning a country's millions of rows on every keystroke (the omnibar's own
rule): ``osm_names`` holds every named place, place with metadata and administrative area,
under its local name and each ``name:xx``; ``osm_addresses`` holds every object carrying an
``addr:street`` or ``addr:place``, with the point it can be located at. ``osm_search_indexes``
records which ingest each country's rows came from, so an index that no longer matches the
ingest says so instead of answering for data it does not hold.

THE GEOCODER NEVER GUESSES. An address matches when EVERY word typed is in one indexed
address -- the house number included, so "Fixture Road 2" does not answer with number 1, and
a street in a country the lane never read does not answer with the nearest spelling. What it
does not locate it says it did not locate, with the scope beside it: the countries read, and
the sentence Q820 requires. No request is made; nothing here can make one.

NOTHING HERE WRITES THE CORPUS, AND NOTHING HERE LEAVES THE MACHINE. Q823 (ODbL) is
unanswered: the notable places become Place rows (``src/entities/places.py``), which no backup,
export or bulletin carries; their body is composed on read, not stored as an Article
(``tests/test_osm_lane_seam.py``).
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import UTC, datetime
from typing import Any

from src.osm.tags import column_name, tags_of

_LOG = logging.getLogger("osm.places")

#: The kinds named in the "Places" facet (roads and buildings are the map's, not places).
NAME_KINDS: tuple[str, ...] = ("poi", "place", "admin")
TYPE_WORDS = {"n": "node", "w": "way", "r": "relation"}
BATCH = 5000

GEOCODER_SCOPE = "Addresses outside your OpenStreetMap countries are not located."
GEOCODER_METHOD = (
    "An address is located when every word typed appears in one address an OpenStreetMap object "
    "carries (addr:housenumber, addr:street or addr:place, addr:postcode, addr:city), in a country "
    "read into this machine. The point is that object's. Nothing is looked up anywhere else."
)
OBJECT_CAVEAT = (
    "A row of the OpenStreetMap data as it stood at the extract's date. A missing tag means "
    "OpenStreetMap does not record it, not that the place lacks it."
)

_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS osm_names USING fts5("
    "names, alpha3 UNINDEXED, object_id UNINDEXED, tokenize='unicode61 remove_diacritics 2')",
    "CREATE VIRTUAL TABLE IF NOT EXISTS osm_addresses USING fts5("
    "address, alpha3 UNINDEXED, object_id UNINDEXED, tokenize='unicode61 remove_diacritics 2')",
)


def _ensure(session) -> None:
    from sqlalchemy import text

    for ddl in _DDL:
        session.execute(text(ddl))


def _col(name: str):
    from src.osm.lane_models import osm_objects_table

    return osm_objects_table.c[column_name(name)]


def _names_text(name: str | None, names_json: str | None) -> str | None:
    """The local name and every ``name:xx``, once each, as one indexed text."""
    seen: list[str] = []
    for n in [name, *((json.loads(names_json) or {}).values() if names_json else [])]:
        n = (n or "").strip()
        if n and n not in seen:
            seen.append(n)
    return " ".join(seen) or None


def _address(hn, street, place, postcode, city) -> str | None:
    road = (street or place or "").strip()
    if not road:
        return None
    return " ".join(p for p in ((hn or "").strip(), road, (postcode or "").strip(), (city or "").strip()) if p)


def build_search_index(alpha3: str) -> dict:
    """(Re)build one complete country's rows in both indexes. Reads ``osm.db``; opens nothing else."""
    from sqlalchemy import select, text

    from src.osm.lane_models import OsmCountry, OsmSearchIndex, osm_objects_table
    from src.versioned import store

    t0 = time.monotonic()
    t = osm_objects_table
    query = select(
        t.c.id, t.c.osm_type, t.c.kind, t.c.lat, t.c.lon, _col("name"), t.c.names,
        _col("addr:housenumber"), _col("addr:street"), _col("addr:place"), _col("addr:postcode"), _col("addr:city"),
    ).where(t.c.country_alpha3 == alpha3)
    names = addresses = no_point = 0
    with store.lane_session("osm") as s:
        country = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        if country is None or country.status != "complete":
            raise ValueError("not-ingested")
        basis = country.finished_at.isoformat() if country.finished_at else None
        _ensure(s)
        s.execute(text("DELETE FROM osm_names WHERE alpha3 = :a"), {"a": alpha3})
        s.execute(text("DELETE FROM osm_addresses WHERE alpha3 = :a"), {"a": alpha3})
        nb: list[dict] = []
        ab: list[dict] = []

        def flush() -> None:
            if nb:
                s.execute(text("INSERT INTO osm_names (names, alpha3, object_id) VALUES (:t, :a, :i)"), nb)
                nb.clear()
            if ab:
                s.execute(text("INSERT INTO osm_addresses (address, alpha3, object_id) VALUES (:t, :a, :i)"), ab)
                ab.clear()

        for oid, otype, kind, lat, lon, name, names_json, hn, street, place, pc, city in s.execute(query).all():
            if kind in NAME_KINDS and not (kind == "admin" and otype != "r"):
                label = _names_text(name, names_json)
                if label:
                    nb.append({"t": label, "a": alpha3, "i": oid})
                    names += 1
            addr = _address(hn, street, place, pc, city)
            if addr:
                if lat is None or lon is None:
                    no_point += 1
                else:
                    ab.append({"t": addr, "a": alpha3, "i": oid})
                    addresses += 1
            if len(nb) + len(ab) >= BATCH:
                flush()
        flush()
        row = s.query(OsmSearchIndex).filter_by(alpha3=alpha3).one_or_none() or OsmSearchIndex(alpha3=alpha3)
        row.basis_ingest, row.names, row.addresses, row.addresses_no_point = basis, names, addresses, no_point
        row.built_at = datetime.now(UTC)
        row.seconds = round(time.monotonic() - t0, 3)
        s.add(row)
    return {"alpha3": alpha3, "names": names, "addresses": addresses, "addresses_no_point": no_point}


def index_state() -> list[dict]:
    """Every complete country, with whether its index matches its ingest. ``[]`` with no lane."""
    from src.osm.lane_models import OsmCountry, OsmSearchIndex
    from src.versioned import store

    if not store.lane_exists("osm"):
        return []
    with store.lane_session("osm") as s:
        idx = {r.alpha3: r for r in s.query(OsmSearchIndex)}
        out = []
        for c in s.query(OsmCountry).filter_by(status="complete").order_by(OsmCountry.alpha3):
            basis = c.finished_at.isoformat() if c.finished_at else None
            r = idx.get(c.alpha3)
            out.append({
                "alpha3": c.alpha3, "name": c.name,
                "vintage": c.extract_vintage.isoformat() if c.extract_vintage else None,
                "indexed": bool(r and r.basis_ingest == basis),
                "names": r.names if r else None, "addresses": r.addresses if r else None,
                "addresses_no_point": r.addresses_no_point if r else None,
            })
    return out


def refresh_indexes() -> dict:
    """Build the index of every complete country whose index does not match its ingest."""
    built = {}
    for c in index_state():
        if not c["indexed"]:
            built[c["alpha3"]] = build_search_index(c["alpha3"])
    return built


# --------------------------------------------------------------------------- #
#  Search                                                                      #
# --------------------------------------------------------------------------- #


def _fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(ch))


def _tokens(q: str) -> list[str]:
    return re.findall(r"\w+", _fold(q or ""))


def _match(tokens: list[str], *, prefix_last: bool) -> str:
    """An FTS5 query: every token, quoted (so no token is read as an operator)."""
    parts = [f'"{tok}"' for tok in tokens]
    if prefix_last and parts:
        parts[-1] += "*"
    return " ".join(parts)


def _indexed(session) -> bool:
    from sqlalchemy import text

    return bool(session.execute(text("SELECT count(*) FROM sqlite_master WHERE name = 'osm_names'")).scalar())


def _object_ref(otype: str, oid: int) -> str:
    return f"{TYPE_WORDS[otype]}/{oid}"


def search_names(q: str, limit: int = 8) -> dict:
    """Named places in the countries read, matched by name in any language OSM gives. Bounded."""
    from sqlalchemy import select, text

    from src.osm.lane_models import osm_objects_table
    from src.versioned import store

    tokens = _tokens(q)
    empty = {"items": [], "total": 0}
    if not tokens or not store.lane_exists("osm"):
        return empty
    t = osm_objects_table
    with store.lane_session("osm") as s:
        if not _indexed(s):
            return empty
        m = _match(tokens, prefix_last=True)
        total = s.execute(text("SELECT count(*) FROM osm_names WHERE osm_names MATCH :m"), {"m": m}).scalar() or 0
        ids = [r[0] for r in s.execute(
            text("SELECT object_id FROM osm_names WHERE osm_names MATCH :m ORDER BY rank LIMIT :n"),
            {"m": m, "n": int(limit)},
        )]
        rows = {r.id: r for r in s.execute(
            select(t.c.id, t.c.osm_type, t.c.osm_id, t.c.kind, t.c.notable, t.c.primary_key,
                   t.c.primary_value, t.c.country_alpha3, _col("name")).where(t.c.id.in_(ids))
        )}
    items = []
    for i in ids:
        r = rows.get(i)
        if r is None:
            continue
        items.append({
            "object": _object_ref(r.osm_type, r.osm_id), "name": r[-1], "kind": r.kind, "notable": bool(r.notable),
            "tag": f"{r.primary_key}={r.primary_value}" if r.primary_key else None, "country": r.country_alpha3,
        })
    return {"items": items, "total": int(total)}


def parse_ref(ref: str) -> tuple[str, int]:
    """``"node/5"`` -> ``("n", 5)``. Raises ValueError for anything else."""
    kind, _sep, num = (ref or "").partition("/")
    short = {v: k for k, v in TYPE_WORDS.items()}.get(kind)
    if short is None or not num.isdigit():
        raise ValueError("an OpenStreetMap object is node/<id>, way/<id> or relation/<id>")
    return short, int(num)


def object_card(ref: str) -> dict | None:
    """One stored object, every tag rendered as metadata. None when the lane does not hold it."""
    from src.osm.lane_models import OsmCountry, OsmObject
    from src.versioned import store

    otype, oid = parse_ref(ref)
    if not store.lane_exists("osm"):
        return None
    with store.lane_session("osm") as s:
        row = s.execute(
            OsmObject.__table__.select().where(OsmObject.__table__.c.osm_type == otype, OsmObject.__table__.c.osm_id == oid)
        ).mappings().first()
        if row is None:
            return None
        country = s.query(OsmCountry).filter_by(alpha3=row["country_alpha3"]).one_or_none()
        tags = tags_of(row)
        out: dict[str, Any] = {
            "object": _object_ref(otype, oid),
            "kind": row["kind"],
            "tag": f"{row['primary_key']}={row['primary_value']}" if row["primary_key"] else None,
            "notable": bool(row["notable"]),
            "name": tags.get("name"),
            "tags": [{"key": k, "value": tags[k]} for k in sorted(tags)],
            "point": {"lat": row["lat"], "lon": row["lon"]} if row["lat"] is not None and row["lon"] is not None else None,
            "version": row["version"],
            "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
            "country": row["country_alpha3"],
            "country_name": country.name if country else None,
            "vintage": country.extract_vintage.isoformat() if country and country.extract_vintage else None,
            "caveat": OBJECT_CAVEAT,
        }
    # A notable object is also a Place (Q817): the card says where that card is.
    out["place_id"] = out["object"] if out["notable"] and out["name"] and not (row["kind"] == "admin" and otype != "r") else None
    return out


def geocode(q: str, limit: int = 5) -> dict:
    """Locate an address in the countries read, or say it was not located. Never a guess."""
    from sqlalchemy import select, text

    from src.osm.lane_models import osm_objects_table
    from src.versioned import store

    scope = [c for c in index_state() if c["indexed"]]
    base: dict[str, Any] = {
        "q": q, "scope": GEOCODER_SCOPE, "method": GEOCODER_METHOD,
        "countries": [{"alpha3": c["alpha3"], "name": c["name"], "vintage": c["vintage"]} for c in scope],
        "results": [], "total": 0,
    }
    tokens = _tokens(q)
    if not scope:
        return {**base, "status": "no-country"}
    if not tokens:
        return {**base, "status": "empty"}
    t = osm_objects_table
    with store.lane_session("osm") as s:
        m = _match(tokens, prefix_last=False)
        total = s.execute(text("SELECT count(*) FROM osm_addresses WHERE osm_addresses MATCH :m"), {"m": m}).scalar() or 0
        hits = s.execute(
            text("SELECT object_id, address FROM osm_addresses WHERE osm_addresses MATCH :m ORDER BY rank LIMIT :n"),
            {"m": m, "n": int(limit)},
        ).all()
        rows = {r.id: r for r in s.execute(
            select(t.c.id, t.c.osm_type, t.c.osm_id, t.c.lat, t.c.lon, t.c.country_alpha3, _col("name"))
            .where(t.c.id.in_([h[0] for h in hits]))
        )}
    results = []
    for oid, address in hits:
        r = rows.get(oid)
        if r is None:
            continue
        results.append({"address": address, "lat": r.lat, "lon": r.lon, "object": _object_ref(r.osm_type, r.osm_id),
                        "name": r[-1], "country": r.country_alpha3})
    return {**base, "status": "located" if results else "not-located", "results": results, "total": int(total)}
