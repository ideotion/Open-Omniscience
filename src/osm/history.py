"""Cut one country's PAST out of the full-history planet into ``osm.db`` (S05-04 S4, Q814 = b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q814 = b: the lane's history depth is the full-history planet, ONE planet-wide file from
``planet.openstreetmap.org`` (Geofabrik's per-region history extracts sit behind an OSM login,
which Q910's reasoning treats as key-gated). This module reads it for a country ALREADY cut
from its continent extract (``src/osm/ingest.py``) and writes that country's past as rows: the
PRIOR that 0.6's trend surfaces state separately from the window they track (S06-01 S3).

WHAT A ROW IS. Q813's key-level shape -- ``added`` / ``removed`` / ``modified``, with the
version's own timestamp and number -- plus the object-level events ``created`` (the first
version in the file), ``deleted`` (a version whose ``visible`` flag is false) and ``restored``
(visible again after a deletion). An object's first version reads as every key ``added``: that
IS when the key was adopted. A deletion reads as ``deleted`` plus every key ``removed``, so the
tags an object had at any date are the rows up to that date, and nothing else.

WHICH OBJECTS ARE THE COUNTRY'S (the design point, stated because it has a cost):

* a NODE counts when ANY tagged, visible version of it lay inside the country's CURRENT border
  -- the same border the extract cut used, built again from the same extract. A café moved in
  from outside counts, with its whole history; a node only ever outside never does. This needs
  one pass over the file's tagged nodes (pyosmium drops the untagged ones in C++ first).
* a WAY or RELATION counts when the current cut kept it (``osm_objects``). A way or relation
  deleted before the extract's date is in no current cut, so it is NOT in the prior: which
  country it was in needs its nodes' past locations, and indexing those for the whole planet's
  history is a cost this slice does not pay. That gap is :data:`GAP`, shown wherever the prior
  is, and ``tests/test_osm_history.py`` pins a deleted way's absence as its negative space.

THE BORDER IS TODAY'S. A node inside the border the country had in 2012 and outside today's is
not counted, and one inside today's border is counted for dates before the border moved. Said in
:data:`METHOD`.

MEASURED, NEVER ESTIMATED. ``osm_history_cuts`` records the file, its size and vintage, the
reader, the wall-clock seconds, and the counts: the row's artifact for 0.5 gate row D. Redacted
versions (OSM removed some for licence reasons in 2012) leave chains that start after version 1
or skip a number; both are COUNTED, never smoothed over.

THE NETWORK IS NEVER TOUCHED. Both files are already on disk; the download is the existing
``/api/geo/downloads`` job under the one online consent. Nothing here reaches an export,
bulletin or evidence ZIP while Q823 (ODbL) is unanswered: ``tests/test_osm_lane_seam.py``.
"""

from __future__ import annotations

import json
import logging
import time
from array import array
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.osm.changes import tag_changes
from src.osm.geometry import Border
from src.osm.pbf import Header, Node, Relation, Way
from src.osm.reader import Extract, open_extract

_LOG = logging.getLogger("osm.history")

#: Rows per INSERT batch and per commit, as the extract cut.
BATCH = 5_000

#: The header feature a history file declares. A file without it is refused by name: read as
#: history, a current extract would record every object as created on its last edit's date.
HISTORY_FEATURE = "HistoricalInformation"

METHOD = (
    "Read from the full-history planet for the objects of one country: every node with a tagged "
    "version inside today's border, and every way and relation the country's current cut kept. "
    "Each version is compared with the one before it; the first version adds every key."
)
GAP = (
    "Ways and relations deleted before the extract's date are not in this history: which "
    "country they were in needs their nodes' past locations, which this cut does not index. "
    "The border is today's, for every date."
)


class HistoryError(ValueError):
    """A history cut that cannot start: no current cut to follow, or not a history file."""


@dataclass
class HistoryReport:
    alpha2: str
    alpha3: str
    reader: str
    status: str = "ingesting"
    counts: dict[str, int] = field(default_factory=dict)
    span: dict[str, str | None] = field(default_factory=dict)
    seconds: float | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "alpha2": self.alpha2,
            "alpha3": self.alpha3,
            "reader": self.reader,
            "status": self.status,
            "counts": self.counts,
            "span": self.span,
            "seconds": self.seconds,
            "error": self.error,
            "method": METHOD,
            "gap": GAP,
        }


# --- the two readers ---------------------------------------------------------- #
class _PythonHistory:
    """The pure-Python decoder, under its size cap: the fixture, and the equivalence test."""

    name = "python"

    def __init__(self, path: Path) -> None:
        self.path = path

    def is_history(self, header: Header) -> bool:
        return HISTORY_FEATURE in header.required_features

    def tagged_nodes(self) -> Iterator[Node]:
        from src.osm import pbf

        for n in pbf.iter_elements(self.path, ways=False, relations=False):
            if isinstance(n, Node) and n.tags and n.visible:
                yield n

    def versions(self, osm_type: str, ids: Iterable[int]) -> Iterator[Node | Way | Relation]:
        from src.osm import pbf

        wanted = set(ids)
        if not wanted:
            return
        for el in pbf.iter_elements(
            self.path, nodes=osm_type == "n", ways=osm_type == "w", relations=osm_type == "r"
        ):
            if el.id in wanted:
                yield el


class _PyosmiumHistory:
    """pyosmium: the C++ filters drop what the Python side would only throw away."""

    name = "pyosmium"

    def __init__(self, path: Path) -> None:
        self.path = path

    def is_history(self, header: Header) -> bool:
        import osmium

        reader = osmium.io.Reader(str(self.path), osmium.osm.osm_entity_bits.NOTHING)
        try:
            return bool(reader.header().has_multiple_object_versions)
        finally:
            reader.close()

    def tagged_nodes(self) -> Iterator[Node]:
        import osmium

        from src.osm.reader import _node

        fp = osmium.FileProcessor(str(self.path), osmium.osm.NODE).with_filter(osmium.filter.EmptyTagFilter())
        o: Any
        for o in fp:
            if o.visible and o.location.valid():
                yield _node(o)

    def versions(self, osm_type: str, ids: Iterable[int]) -> Iterator[Node | Way | Relation]:
        import osmium

        from src.osm.reader import _node, _rel, _way

        if not isinstance(ids, (list, array)):
            ids = array("q", ids)
        if not len(ids):  # type: ignore[arg-type]
            return
        kind = {"n": osmium.osm.NODE, "w": osmium.osm.WAY, "r": osmium.osm.RELATION}[osm_type]
        fp = osmium.FileProcessor(str(self.path), kind).with_filter(osmium.filter.IdFilter(ids))
        o: Any
        for o in fp:
            if osm_type == "n":
                el: Any = _node(o) if o.visible and o.location.valid() else Node(
                    o.id, o.version or None, _stamp(o), {}, 0.0, 0.0, False
                )
            elif osm_type == "w":
                el = _way(o) if o.visible else Way(o.id, o.version or None, _stamp(o), {}, (), False)
            else:
                el = _rel(o) if o.visible else Relation(o.id, o.version or None, _stamp(o), {}, (), False)
            yield el


def _stamp(o) -> datetime | None:
    ts = o.timestamp
    return ts if ts is not None and ts.timestamp() > 0 else None


def _history_reader(extract: Extract) -> _PythonHistory | _PyosmiumHistory:
    """The history twin of the backend :func:`open_extract` chose (same cap, same refusal)."""
    return _PyosmiumHistory(extract.path) if extract.name == "pyosmium" else _PythonHistory(extract.path)


# --- the cut -------------------------------------------------------------------- #
def object_rows(alpha3: str, osm_type: str, versions: list[Node | Way | Relation], counts: dict[str, int]) -> list[dict]:
    """Every row one object's version chain yields, oldest first (see the module docstring)."""
    rows: list[dict] = []
    prev_tags: dict[str, str] | None = None
    alive = False
    existed = False
    last_version: int | None = None
    for i, v in enumerate(versions):
        if i == 0 and v.version not in (None, 1):
            counts["chains_starting_after_version_1"] += 1
        if last_version is not None and v.version is not None and v.version != last_version + 1:
            counts["version_gaps"] += 1
        last_version = v.version
        base = {
            "country_alpha3": alpha3,
            "osm_type": osm_type,
            "osm_id": v.id,
            "object_version": v.version,
            "version_timestamp": v.timestamp,
        }
        if v.visible:
            if not alive:
                event = "restored" if existed else "created"
                rows.append({**base, "change": event, "key": None, "old_value": None, "new_value": None})
                prev_tags = None
            for c in tag_changes(prev_tags, v.tags):
                rows.append({**base, "change": c.change, "key": c.key, "old_value": c.old_value, "new_value": c.new_value})
            prev_tags, alive, existed = dict(v.tags), True, True
        else:
            if alive:
                rows.append({**base, "change": "deleted", "key": None, "old_value": None, "new_value": None})
                for c in tag_changes(prev_tags, None):
                    rows.append({**base, "change": c.change, "key": c.key, "old_value": c.old_value, "new_value": c.new_value})
            prev_tags, alive = None, False
    return rows


def _chains(elements: Iterable[Node | Way | Relation]) -> Iterator[list[Node | Way | Relation]]:
    """Consecutive versions of one id, as a history file stores them (id, then version order)."""
    chain: list[Node | Way | Relation] = []
    for el in elements:
        if chain and el.id != chain[0].id:
            yield chain
            chain = []
        chain.append(el)
    if chain:
        yield chain


def ingest_history(
    history_path: str | Path,
    extract_path: str | Path,
    country: str,
    *,
    reader: str | None = None,
) -> HistoryReport:
    """Cut ``country``'s past out of ``history_path`` into ``osm.db``. Returns the recorded report.

    ``extract_path`` is the continent extract the country was cut from: its border is rebuilt
    from it, so the history follows exactly the border the current cut used.
    """
    from sqlalchemy import delete, insert, select

    from src.osm.ingest import build_border, country_codes
    from src.osm.lane_models import OsmCountry, OsmHistoryChange, OsmHistoryCut, osm_objects_table
    from src.versioned import store

    alpha2, alpha3 = country_codes(country)
    store.create_lane("osm")
    with store.lane_session("osm") as s:
        cut = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        if cut is None or cut.status != "complete":
            raise HistoryError(
                f"{alpha3} has no complete cut from its extract yet; the history follows that cut's "
                "border and objects, so cut the country first (scripts/osm_ingest.py)"
            )

    history = open_extract(history_path, reader=reader)
    hist = _history_reader(history)
    hdr = history.header()
    if not hist.is_history(hdr):
        raise HistoryError(
            f"{Path(history_path).name} is not a full-history file (its header does not declare "
            f"{HISTORY_FEATURE}); read as history, a current extract would date every object to its last edit"
        )

    report = HistoryReport(alpha2=alpha2, alpha3=alpha3, reader=hist.name)
    path = Path(history_path)
    t0 = time.monotonic()
    with store.lane_session("osm") as s:
        row = s.query(OsmHistoryCut).filter_by(alpha3=alpha3).one_or_none() or OsmHistoryCut(alpha3=alpha3)
        row.status = "ingesting"
        row.history_name = path.name
        row.history_bytes = path.stat().st_size
        row.history_vintage = hdr.replication_timestamp
        row.reader = hist.name
        row.started_at = datetime.now(UTC)
        row.finished_at = None
        row.ingest_seconds = None
        row.error = None
        s.add(row)

    counts: dict[str, int] = dict.fromkeys(
        (
            "tagged_node_versions_read", "nodes_inside", "ways_tracked", "relations_tracked",
            "objects_read", "versions_read", "tracked_not_in_file",
            "chains_starting_after_version_1", "version_gaps",
            *[f"rows_{c}" for c in ("added", "removed", "modified", "created", "deleted", "restored")],
        ),
        0,
    )
    oldest: datetime | None = None
    newest: datetime | None = None
    try:
        border: Border = build_border(open_extract(extract_path, reader=reader), alpha2)[1]
        # Pass A: the nodes whose tagged versions lay inside the border.
        node_ids: array[int] = array("q")
        for n in hist.tagged_nodes():
            counts["tagged_node_versions_read"] += 1
            # Versions of one id are consecutive, so the last id appended is the only repeat.
            if (not node_ids or node_ids[-1] != n.id) and border.contains(n.lat, n.lon):
                node_ids.append(n.id)
        counts["nodes_inside"] = len(node_ids)
        with store.lane_session("osm") as s:
            tracked = {
                t: array("q", (i for (i,) in s.execute(
                    select(osm_objects_table.c.osm_id).where(
                        osm_objects_table.c.country_alpha3 == alpha3, osm_objects_table.c.osm_type == t
                    ).order_by(osm_objects_table.c.osm_id)
                )))
                for t in ("w", "r")
            }
            s.execute(delete(OsmHistoryChange).where(OsmHistoryChange.country_alpha3 == alpha3))
        counts["ways_tracked"] = len(tracked["w"])
        counts["relations_tracked"] = len(tracked["r"])

        batch: list[dict] = []

        def flush() -> None:
            if batch:
                with store.lane_session("osm") as s:
                    s.execute(insert(OsmHistoryChange), batch)
                batch.clear()

        # Pass B: every version of those objects, one type at a time.
        for osm_type, ids in (("n", node_ids), ("w", tracked["w"]), ("r", tracked["r"])):
            seen = 0
            for chain in _chains(hist.versions(osm_type, ids)):
                seen += 1
                counts["objects_read"] += 1
                counts["versions_read"] += len(chain)
                for v in chain:
                    if v.timestamp is not None:
                        oldest = v.timestamp if oldest is None or v.timestamp < oldest else oldest
                        newest = v.timestamp if newest is None or v.timestamp > newest else newest
                for r in object_rows(alpha3, osm_type, chain, counts):
                    counts[f"rows_{r['change']}"] += 1
                    batch.append(r)
                if len(batch) >= BATCH:
                    flush()
            counts["tracked_not_in_file"] += max(0, len(ids) - seen)
        flush()
        report.status = "complete"
    except Exception as exc:
        report.status = "failed"
        report.error = f"{type(exc).__name__}: {exc}"
        _LOG.warning("the %s history cut from %s failed: %s", alpha2, path.name, exc)
        raise
    finally:
        report.counts = counts
        report.span = {
            "oldest": oldest.isoformat() if oldest else None,
            "newest": newest.isoformat() if newest else None,
        }
        report.seconds = round(time.monotonic() - t0, 3)
        with store.lane_session("osm") as s:
            row = s.query(OsmHistoryCut).filter_by(alpha3=alpha3).one()
            row.status = report.status
            row.finished_at = datetime.now(UTC)
            row.ingest_seconds = report.seconds
            row.counts_json = json.dumps(report.counts, sort_keys=True)
            row.span_json = json.dumps(report.span, sort_keys=True)
            row.error = report.error
    return report


def history_state() -> list[dict]:
    """Every history cut, as the Settings panel shows it. Reads ``osm.db`` only; ``[]`` without it."""
    from src.osm.lane_models import OsmHistoryCut
    from src.versioned import store

    if not store.lane_exists("osm"):
        return []
    out: list[dict] = []
    with store.lane_session("osm") as s:
        for r in s.query(OsmHistoryCut).order_by(OsmHistoryCut.alpha3):
            out.append(
                {
                    "alpha3": r.alpha3,
                    "status": r.status,
                    "history_name": r.history_name,
                    "history_bytes": r.history_bytes,
                    "history_vintage": r.history_vintage.isoformat() if r.history_vintage else None,
                    "reader": r.reader,
                    "ingest_seconds": r.ingest_seconds,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "counts": json.loads(r.counts_json) if r.counts_json else {},
                    "span": json.loads(r.span_json) if r.span_json else {},
                    "error": r.error,
                }
            )
    return out
