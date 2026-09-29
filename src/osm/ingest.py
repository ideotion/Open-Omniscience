"""Cut one country out of an extract into ``osm.db`` -- the lane's extract pass (S05-04 S1-S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE PASSES, in order, each over the whole extract (the reader decides how cheaply):

1. **the border relation** -- ``boundary=administrative``, ``admin_level=2``, and
   ``ISO3166-1:alpha2`` (or ``ISO3166-1``) equal to the country. None found is a refusal
   (:class:`BorderError`) naming the country and the file, never an empty country.
2. **its ways** -- the node ids of the relation's ``outer`` / ``inner`` members.
3. **their nodes** -- coordinates, stitched into closed rings (``geometry.Border``).
4. **the main pass**, in file order: every node inside the border's bounding box has its
   location stored (the ways need them); a TAGGED node the lane keeps and the border contains
   becomes a row; a tagged way the lane keeps becomes a row when the mean of its vertices is
   inside; a tagged relation the lane keeps becomes a row when one of its members already did.

A ROW IS WRITTEN ONLY FOR A KEPT OBJECT (``tags.classify``). An untagged object never becomes a
row, so "no row" means "not kept" and never "kept with nothing".

RE-INGEST REPLACES. A country already in ``osm.db`` is deleted and cut again, inside the same
run: the country row is marked ``ingesting`` first and ``complete`` only at the end, so a run
that dies half-way leaves ``ingesting`` (or ``failed``, when the exception was caught) and
every reader refuses it rather than counting a partial country as a small one.

MEASURED, NEVER ESTIMATED (S05-04 §6). The country row records the extract's size and vintage,
the reader, wall-clock seconds, counts per kind, the border as assembled, and the blob in bytes
under Q810's list and under the extended one (the note's measurement). The reference VM's run
fills them; the fixture proves they are filled.

THE NETWORK IS NEVER TOUCHED. The extract is a file already on disk; ``tests/test_osm_ingest.py``
runs this module with the airplane socket guard armed and counts zero resolutions.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.osm import tags as T
from src.osm.geometry import Border, BorderError, encode_coords, representative_point, stitch
from src.osm.pbf import Node, Relation, Way
from src.osm.reader import Extract, open_extract

_LOG = logging.getLogger("osm.ingest")

#: Rows per INSERT batch and per commit. A commit per batch keeps the WAL bounded on a
#: country of tens of millions of rows.
BATCH = 5_000

#: ISO 3166-1 reserves ZZ for private use; the fixture's country. Its alpha-3 twin ``ZZZ`` is
#: the law fixture's. Mapped here, by name, because ``catalog.countries`` rightly refuses it.
_PRIVATE_USE = {"ZZ": "ZZZ"}


def country_codes(code: str) -> tuple[str, str]:
    """``(alpha2, alpha3)`` for an alpha-2 or alpha-3 code, or a ``ValueError`` naming it."""
    from src.catalog.countries import ISO3_TO_ISO2, to_iso3

    c = (code or "").strip().upper()
    if c in _PRIVATE_USE:
        return c, _PRIVATE_USE[c]
    if c in _PRIVATE_USE.values():
        return next(k for k, v in _PRIVATE_USE.items() if v == c), c
    a3 = to_iso3(c)
    if not a3:
        raise ValueError(f"{code!r} is not an ISO 3166-1 country code")
    a2 = ISO3_TO_ISO2.get(a3.lower(), "").upper()
    if not a2:
        raise ValueError(f"{code!r} has no alpha-2 twin")
    return a2, a3


@dataclass
class IngestReport:
    alpha2: str
    alpha3: str
    reader: str
    status: str = "ingesting"
    counts: dict[str, int] = field(default_factory=dict)
    blob: dict[str, int] = field(default_factory=dict)
    border: dict = field(default_factory=dict)
    seconds: float | None = None
    error: str | None = None
    name: str | None = None
    #: What the name and address indexes took from this cut (S5), or None if not built.
    search_index: dict | None = None
    view_index: dict | None = None

    def to_dict(self) -> dict:
        return {
            "alpha2": self.alpha2,
            "alpha3": self.alpha3,
            "reader": self.reader,
            "status": self.status,
            "counts": self.counts,
            "blob": self.blob,
            "border": self.border,
            "seconds": self.seconds,
            "error": self.error,
            "name": self.name,
            "search_index": self.search_index,
            "view_index": self.view_index,
        }


def _is_country_relation(rel: Relation, alpha2: str) -> bool:
    t = rel.tags
    if t.get("boundary") != "administrative" or t.get("admin_level") != "2":
        return False
    code = (t.get("ISO3166-1:alpha2") or t.get("ISO3166-1") or "").upper()
    return code == alpha2


def build_border(extract: Extract, alpha2: str) -> tuple[Relation, Border, dict]:
    """Passes 1-3: the country's relation and its assembled border."""
    rels = [r for r in extract.relations() if _is_country_relation(r, alpha2)]
    if not rels:
        raise BorderError(
            f"{extract.path.name} carries no admin_level=2 boundary relation tagged "
            f"ISO3166-1:alpha2={alpha2}; this extract does not contain that country"
        )
    rel = min(rels, key=lambda r: r.id)  # several is a data error; the lowest id is deterministic
    way_ids = {m.ref for m in rel.members if m.type == "w" and m.role in ("outer", "inner", "")}
    ways = {w.id: w.refs for w in extract.ways_by_id(way_ids)}
    node_ids = {n for refs in ways.values() for n in refs}
    coords = {n.id: (n.lat, n.lon) for n in extract.nodes_by_id(node_ids)}
    rings_ids, dropped = stitch(ways[w] for w in sorted(ways))
    rings: list[list[tuple[float, float]]] = []
    missing = 0
    for ring in rings_ids:
        pts = [coords[n] for n in ring if n in coords]
        if len(pts) != len(ring):
            missing += 1
            continue
        rings.append(pts)
    if not rings:
        raise BorderError(
            f"the {alpha2} border relation {rel.id} in {extract.path.name} could not be closed "
            f"into a ring ({len(way_ids)} member ways, {len(ways)} found, {dropped} left open)"
        )
    border = Border(rings)
    facts = {
        "relation_id": rel.id,
        "relations_found": len(rels),
        "member_ways": len(way_ids),
        "ways_found": len(ways),
        "rings": len(rings),
        "segments_left_open": dropped,
        "rings_missing_nodes": missing,
        "vertices": border.vertices,
        "bbox": list(border.bbox),
    }
    return rel, border, facts


def _row(obj: Node | Way | Relation, *, kind, pkey, pval, notable, alpha3, lat, lon, geom, node_count, members) -> dict:
    scalars, families, blob = T.split_tags(obj.tags)
    row = {
        "osm_type": "n" if isinstance(obj, Node) else "w" if isinstance(obj, Way) else "r",
        "osm_id": obj.id,
        "version": obj.version,
        "timestamp": obj.timestamp,
        "country_alpha3": alpha3,
        "kind": kind,
        "notable": notable,
        "primary_key": pkey,
        "primary_value": pval,
        "lat": lat,
        "lon": lon,
        "geom": geom,
        "node_count": node_count,
        "members": members,
        "other_tags": T.dumps(blob),
    }
    for col in T.FAMILIES.values():
        row[col] = T.dumps(families.get(col, {}))
    for k in T.SCALAR_KEYS:
        row[T.column_name(k)] = scalars.get(k)
    return row


def ingest_country(
    extract_path: str | Path,
    country: str,
    *,
    reader: str | None = None,
    workdir: Path | None = None,
) -> IngestReport:
    """Cut ``country`` out of ``extract_path`` into ``osm.db``. Returns the recorded report.

    Creates the lane on first use (``store.create_lane``, which refuses a locked store and a
    plaintext lane beside an encrypted corpus by name).
    """
    from sqlalchemy import delete, insert

    from src.osm.lane_models import OsmCountry, osm_objects_table
    from src.paths import data_dir
    from src.versioned import store

    alpha2, alpha3 = country_codes(country)
    extract = open_extract(extract_path, reader=reader)
    report = IngestReport(alpha2=alpha2, alpha3=alpha3, reader=extract.name)
    path = Path(extract_path)
    t0 = time.monotonic()
    started = datetime.now(UTC)
    hdr = extract.header()

    store.create_lane("osm")
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none() or OsmCountry(alpha2=alpha2, alpha3=alpha3)
        row.alpha2 = alpha2
        row.status = "ingesting"
        row.extract_name = path.name
        row.extract_bytes = path.stat().st_size
        row.extract_vintage = hdr.replication_timestamp
        row.reader = extract.name
        row.started_at = started
        row.finished_at = None
        row.ingest_seconds = None
        row.error = None
        s.add(row)

    locations = extract.location_store(workdir or (data_dir() / "osm_work"))
    try:
        rel, border, facts = build_border(extract, alpha2)
        report.border = facts
        counts: dict[str, int] = dict.fromkeys(T.KINDS, 0)
        counts.update(nodes_in_bbox_tagged=0, ways_tagged=0, relations_tagged=0, ways_missing_locations=0, outside_border=0)
        blob_q810 = blob_ext = 0
        kept_nodes = _IdSet()
        kept_ways = _IdSet()
        with store.lane_session("osm") as s:
            _clear_derived(s, alpha3)
            s.execute(delete(osm_objects_table).where(osm_objects_table.c.country_alpha3 == alpha3))
        batch: list[dict] = []

        def flush() -> None:
            if batch:
                with store.lane_session("osm") as s:
                    s.execute(insert(osm_objects_table), batch)
                batch.clear()

        lat: float | None
        lon: float | None
        geom: bytes | None
        n: int | None
        members: str | None
        for obj in extract.scan(border.bbox, locations):
            is_way = isinstance(obj, Way)
            kind, pkey, pval, notable = T.classify(obj.tags, is_way=is_way)
            if isinstance(obj, Node):
                counts["nodes_in_bbox_tagged"] += 1
                if kind is None:
                    continue
                if not border.contains(obj.lat, obj.lon):
                    counts["outside_border"] += 1
                    continue
                lat, lon, geom, n, members = obj.lat, obj.lon, None, None, None
                kept_nodes.add(obj.id)
            elif isinstance(obj, Way):
                counts["ways_tagged"] += 1
                if kind is None:
                    continue
                found = [locations.get(r) for r in obj.refs]
                pts = [p for p in found if p is not None]
                if not pts or len(pts) != len(found):
                    # A way whose vertices lie (partly) outside the box, or were cut from the
                    # extract. Counted, never drawn with a hole in it.
                    counts["ways_missing_locations"] += 1
                    continue
                rp = representative_point(pts)
                if rp is None or not border.contains(*rp):
                    counts["outside_border"] += 1
                    continue
                lat, lon = rp
                geom, n, members = encode_coords(pts), len(pts), None
                kept_ways.add(obj.id)
            else:
                counts["relations_tagged"] += 1
                if kind is None:
                    continue
                if obj.id != rel.id and not any(
                    (m.type == "n" and m.ref in kept_nodes) or (m.type == "w" and m.ref in kept_ways)
                    for m in obj.members
                ):
                    counts["outside_border"] += 1
                    continue
                lat = lon = None
                geom, n = None, None
                members = json.dumps([[m.type, m.ref, m.role] for m in obj.members], separators=(",", ":"))
            counts[kind] += 1
            blob_q810 += T.blob_bytes(obj.tags, extended=False)
            blob_ext += T.blob_bytes(obj.tags, extended=True)
            batch.append(
                _row(obj, kind=kind, pkey=pkey, pval=pval, notable=notable, alpha3=alpha3,
                     lat=lat, lon=lon, geom=geom, node_count=n, members=members)
            )
            if len(batch) >= BATCH:
                flush()
        flush()
        kept = sum(counts[k] for k in T.KINDS)
        report.counts = counts
        report.blob = {"objects": kept, "q810_bytes": blob_q810, "extended_bytes": blob_ext}
        report.name = _country_name(report.border.get("relation_id"))
        report.status = "complete"
    except Exception as exc:
        report.status = "failed"
        report.error = f"{type(exc).__name__}: {exc}"
        _LOG.warning("the %s cut from %s failed: %s", alpha2, path.name, exc)
        raise
    finally:
        locations.close()
        report.seconds = round(time.monotonic() - t0, 3)
        with store.lane_session("osm") as s:
            row = s.query(OsmCountry).filter_by(alpha3=alpha3).one()
            row.status = report.status
            row.finished_at = datetime.now(UTC)
            row.ingest_seconds = report.seconds
            row.counts_json = json.dumps(report.counts, sort_keys=True)
            row.blob_json = json.dumps(report.blob, sort_keys=True)
            row.border_json = json.dumps(report.border, sort_keys=True)
            row.relation_id = report.border.get("relation_id")
            row.error = report.error
            if report.name:
                row.name = report.name
    if report.status == "complete":
        # The "Places" facet and the geocoder read an index, never the rows on a keystroke
        # (src/osm/places.py). Built from what was just written; a failure is logged and the
        # index then reads as not matching this ingest, which the Places job rebuilds.
        try:
            from src.osm.places import build_search_index

            report.search_index = build_search_index(alpha3)
        except Exception:  # noqa: BLE001 - the cut is complete; only its index is missing
            _LOG.warning("the %s search index was not built", alpha3, exc_info=True)
        # The map reads its R*Tree (src/osm/view.py, S6) the same way.
        try:
            from src.osm.view import build_view_index

            report.view_index = build_view_index(alpha3)
        except Exception:  # noqa: BLE001 - the cut is complete; only its view index is missing
            _LOG.warning("the %s view index was not built", alpha3, exc_info=True)
    return report


def _clear_derived(session, alpha3: str) -> None:
    """Drop a country's rows in every index built from ``osm_objects`` before its objects go.

    Row ids are reused by SQLite once a country's objects are deleted, so an index row left over
    from a failed or interrupted re-ingest would point at whatever object takes that id next:
    an old address shown at an unrelated point, an old cluster count on the map. A table the
    lane has not created yet has nothing to drop.
    """
    from sqlalchemy import text

    ids = "SELECT id FROM osm_objects WHERE country_alpha3 = :a"
    for stmt in (
        "DELETE FROM osm_names WHERE alpha3 = :a",
        "DELETE FROM osm_addresses WHERE alpha3 = :a",
        f"DELETE FROM osm_rtree WHERE id IN ({ids})",
        "DELETE FROM osm_view_cells WHERE alpha3 = :a",
        "DELETE FROM osm_view_indexes WHERE alpha3 = :a",
        "DELETE FROM osm_search_indexes WHERE alpha3 = :a",
    ):
        try:
            with session.begin_nested():
                session.execute(text(stmt), {"a": alpha3})
        except Exception:  # noqa: BLE001 - that index was never created on this lane
            continue


class _IdSet:
    """The ids already kept, for the relation pass. pyosmium's compact ``IdSet`` when present.

    A country's buildings and roads run to tens of millions of ids; a Python ``set`` of that
    many ints is gigabytes, pyosmium's chunked bitmap is a small fraction of it.
    """

    def __init__(self) -> None:
        try:
            import osmium.index

            self._ids = osmium.index.IdSet()
            self._py: set[int] | None = None
        except ImportError:
            self._py = set()

    def add(self, i: int) -> None:
        if self._py is not None:
            self._py.add(i)
        else:
            self._ids.set(i)

    def __contains__(self, i: int) -> bool:
        if self._py is not None:
            return i in self._py
        return bool(self._ids.get(i))


def _country_name(relation_id: int | None) -> str | None:
    """The border relation's ``name`` tag, read back from the lane rather than the file."""
    if relation_id is None:
        return None
    from src.osm.lane_models import OsmObject
    from src.versioned import store

    with store.lane_session("osm") as s:
        row = s.query(OsmObject).filter_by(osm_type="r", osm_id=relation_id).one_or_none()
        return None if row is None else getattr(row, T.column_name("name"))
