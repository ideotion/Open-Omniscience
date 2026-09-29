"""Which objects the lane keeps, the curated columns, and the one JSON blob (Q809, Q810, Q817).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IS KEPT (Q809 = b: «Also roads and buildings»). Five kinds, decided from the tags alone,
first match wins:

* ``admin``    -- ``boundary=administrative``;
* ``place``    -- ``place=*`` (cities, towns, villages...);
* ``poi``      -- a place with metadata: any of :data:`POI_KEYS`, or any object carrying
                  ``wikidata`` / ``wikipedia``;
* ``building`` -- ``building=*``;
* ``road``     -- a WAY with ``highway=*`` (a ``highway=`` node is a signal or a stop, not a
                  road; it is kept only when a POI key also says what it is).

Everything else in the extract (land use, water, power lines, untagged vertices...) is not
kept, and :data:`NOT_KEPT` is the sentence the API returns saying so. ``notable`` marks what
Q817 says becomes an Article: admin areas, ``place=*``, and anything carrying ``wikidata`` /
``wikipedia``.

THE COLUMNS (Q810 = a, and its NOTE «yes, but extend the list of columns to minimize the JSON
blob»). :data:`Q810_KEYS` is the ruling's list verbatim; :data:`EXTENDED_KEYS` is what this
slice adds to shrink the blob, chosen as the tags that recur on the five kinds above (from
OSM's own tag documentation, FROM MEMORY rather than a taginfo count: the operator's first
ingest MEASURES the blob both ways and records it, :func:`blob_bytes`). Four of the ruling's
entries are FAMILIES (``name:*``, ``contact:*``, ``payment:*``, ``disused:*``); each is one
JSON column keyed by the suffix, so ``name:fr`` is ``names["fr"]``. ``addr:*`` is the
exception: its common keys are real columns, because the local geocoder (Q820) queries them.

NO TAG IS LOST. :func:`split_tags` puts every tag in exactly one place -- a column, a family or
the blob -- and :func:`join_tags` is its exact inverse; ``tests/test_osm_tags.py`` round-trips
random tag sets through both. An EMPTY value (``opening_hours=``) is stored as the empty string,
never as NULL: NULL means the tag is absent, and the two are different facts.

THE COLUMN CEILING (the Q1140 note). ``osm_objects`` has :func:`table_width` columns. SQLite
refuses a table wider than 2,000 (measured: ``tests/test_osm_tags.py`` builds a
2,001-column table and reads the refusal); PostgreSQL's limit is 1,600 (FROM MEMORY, the figure
its documentation gives -- not measurable here). The same test fails if the table passes 400,
so widening it past that is an argued change, not a drift.
"""

from __future__ import annotations

import json

KINDS = ("admin", "place", "poi", "building", "road")

#: The tags that make an object a place with metadata. Order is the ``primary`` tag's priority.
POI_KEYS: tuple[str, ...] = (
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "office",
    "craft",
    "healthcare",
    "historic",
    "emergency",
    "club",
    "public_transport",
    "aeroway",
)

NOT_KEPT = (
    "Kept: administrative areas, place=*, places with metadata (amenity, shop, tourism, leisure, "
    "office, craft, healthcare, historic, emergency, club, public_transport, aeroway, or any object "
    "carrying wikidata/wikipedia), buildings, and roads. Not kept: land use, natural features, "
    "water, power lines and every untagged object."
)

#: Q810's list, verbatim, with its four families marked by the trailing ``:*``.
Q810_KEYS: tuple[str, ...] = (
    "name",
    "name:*",
    "brand",
    "brand:wikidata",
    "operator",
    "opening_hours",
    "website",
    "contact:*",
    "phone",
    "email",
    "addr:*",
    "wikidata",
    "wikipedia",
    "cuisine",
    "level",
    "check_date",
    "disused:*",
    "wheelchair",
    "payment:*",
)

#: The ``addr:*`` keys that are real columns (the geocoder's input). Other ``addr:*`` go to the blob.
ADDR_KEYS: tuple[str, ...] = (
    "addr:housenumber",
    "addr:street",
    "addr:place",
    "addr:postcode",
    "addr:city",
    "addr:country",
    "addr:unit",
    "addr:suburb",
    "addr:district",
    "addr:state",
    "addr:province",
)

#: Added by this slice under Q810's note, to shrink the blob. Each recurs on at least one kind.
EXTENDED_KEYS: tuple[str, ...] = (
    # what the object is
    *POI_KEYS,
    "place",
    "boundary",
    "admin_level",
    "highway",
    "building",
    "sport",
    "religion",
    "denomination",
    "brand:wikipedia",
    "operator:wikidata",
    "operator:type",
    "network",
    "ref",
    # names beyond the family
    "official_name",
    "alt_name",
    "old_name",
    "short_name",
    "loc_name",
    "int_name",
    # places
    "population",
    "capital",
    "is_in",
    "ISO3166-1",
    "ISO3166-1:alpha2",
    "ISO3166-2",
    "border_type",
    "type",
    # places with metadata
    "description",
    "internet_access",
    "takeaway",
    "delivery",
    "outdoor_seating",
    "drive_through",
    "smoking",
    "fee",
    "capacity",
    "diet:vegetarian",
    "start_date",
    "email:verified",
    "fax",
    "url",
    "image",
    "wikimedia_commons",
    "heritage",
    "ele",
    # buildings
    "building:levels",
    "building:material",
    "building:use",
    "roof:shape",
    "roof:levels",
    "height",
    # roads
    "surface",
    "oneway",
    "maxspeed",
    "lanes",
    "lit",
    "sidewalk",
    "service",
    "access",
    "foot",
    "bicycle",
    "motor_vehicle",
    "bridge",
    "tunnel",
    "layer",
    "junction",
    "width",
    "smoothness",
    "tracktype",
    "cycleway",
    "parking:lane",
    # provenance on the object itself
    "source",
    "note",
    "fixme",
)

#: The four families: tag prefix -> JSON column.
FAMILIES: dict[str, str] = {
    "name:": "names",
    "contact:": "contact",
    "payment:": "payment",
    "disused:": "disused",
}


def column_name(key: str) -> str:
    """A tag key as a column name: ``building:levels`` -> ``t_building_levels``.

    The ``t_`` prefix keeps a tag from ever colliding with a structural column (``id``,
    ``version``, ``type``...).
    """
    return "t_" + key.replace(":", "_").replace("-", "_").lower()


def _scalar_keys(extended: bool) -> tuple[str, ...]:
    base = [k for k in Q810_KEYS if not k.endswith(":*")] + list(ADDR_KEYS)
    if extended:
        base += [k for k in EXTENDED_KEYS if k not in base]
    seen: dict[str, None] = {}
    for k in base:
        seen.setdefault(k, None)
    return tuple(seen)


#: The curated scalar columns the table carries, in order.
SCALAR_KEYS: tuple[str, ...] = _scalar_keys(extended=True)
_SCALAR_SET = frozenset(SCALAR_KEYS)
_Q810_SCALAR_SET = frozenset(_scalar_keys(extended=False))


def classify(tags: dict[str, str], *, is_way: bool) -> tuple[str | None, str | None, str | None, bool]:
    """``(kind, primary_key, primary_value, notable)``; ``kind`` is None for an object not kept."""
    if not tags:
        return None, None, None, False
    notable = bool(tags.get("wikidata") or tags.get("wikipedia"))
    if tags.get("boundary") == "administrative":
        return "admin", "boundary", "administrative", True
    if "place" in tags:
        return "place", "place", tags["place"], True
    for k in POI_KEYS:
        if k in tags:
            return "poi", k, tags[k], notable
    if "building" in tags:
        return "building", "building", tags["building"], notable
    if is_way and "highway" in tags:
        return "road", "highway", tags["highway"], notable
    if notable:
        return "poi", None, None, True
    return None, None, None, False


def split_tags(tags: dict[str, str], *, extended: bool = True) -> tuple[dict[str, str], dict[str, dict[str, str]], dict[str, str]]:
    """``(scalars by tag key, families by column, blob)`` -- every tag in exactly one of them."""
    scalars_set = _SCALAR_SET if extended else _Q810_SCALAR_SET
    scalars: dict[str, str] = {}
    families: dict[str, dict[str, str]] = {}
    blob: dict[str, str] = {}
    for k, v in tags.items():
        if k in scalars_set:
            scalars[k] = v
            continue
        for prefix, col in FAMILIES.items():
            if k.startswith(prefix):
                families.setdefault(col, {})[k[len(prefix) :]] = v
                break
        else:
            blob[k] = v
    return scalars, families, blob


def join_tags(scalars: dict[str, str], families: dict[str, dict[str, str]], blob: dict[str, str]) -> dict[str, str]:
    """The inverse of :func:`split_tags`."""
    out = dict(blob)
    out.update(scalars)
    by_col = {col: prefix for prefix, col in FAMILIES.items()}
    for col, members in families.items():
        prefix = by_col[col]
        for suffix, v in members.items():
            out[prefix + suffix] = v
    return out


def dumps(obj: dict) -> str | None:
    """Compact, key-sorted JSON; ``None`` for an empty mapping (nothing to store)."""
    if not obj:
        return None
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def blob_bytes(tags: dict[str, str], *, extended: bool) -> int:
    """Bytes the blob would hold for this tag set under the chosen column list (Q810's note)."""
    _s, _f, blob = split_tags(tags, extended=extended)
    text = dumps(blob)
    return len(text.encode("utf-8")) if text else 0
