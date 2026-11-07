"""Apply a country's daily change files to ``osm.db`` and re-baseline when they cannot be had (S06-01 S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q812 = a: the country is kept current from Geofabrik's daily change files for its extract; when the file it needs is older than the
mirror keeps, the extract is cut again and the app SAYS SO. This module is the engine. It owns no schedule, no route and no page
(S5 and the job layer wire those), and it touches the network only through the :class:`~src.osm.replication.DiffSource` it is handed.

WHAT A DAY DOES, AND WHAT IT REFUSES TO GUESS.

* The country's position is where its OBJECTS stand: ``OsmCountry.diff_sequence`` once a file has been applied, the extract's own
  header sequence before. It is written in the SAME transaction as the object changes, so a file is applied wholly or not at all and
  "which sequence are the objects at" has one answer. The substrate's cursor (``versioned_cursors``) follows it, and any hole in the
  stream is PUBLISHED as a gap (``versioned_gaps``), never healed.
* Only the kept classes are applied (``tags.classify``). An object of another class is dropped and counted; a stored object whose
  tags no longer qualify is deleted and counted as having left its class.
* A node is placed by its own position against the country's border (kept on the country's row at the cut). A way is placed by the mean of
  its vertices, as at the cut, and its vertices come from the file's own nodes or from stored node rows. A way whose vertices
  cannot ALL be found is never placed from the ones that can: a new one is counted as ``ways_not_placed``, a stored one keeps its
  old shape with its new tags and is counted as ``geometry_kept``. (The cut keeps a location for every node; the update does not,
  and the counts say how often that mattered.)
* A change file that is OLDER than what is stored (a lower ``version``) never overwrites it.
* The border is the one the cut used. A change to the country's own border relation is applied as a row change; the rings are not
  recomputed, which is a stated limit until the next cut.
* TAG-LEVEL ROWS (S06-01 S2, R428). Each object the file really changes writes one ``osm_tag_changes`` row per key added / removed /
  modified, stamped with THE FILE'S OWN timestamp and the object's ``version``, in the same transaction as the object. What it refuses:
  an object that was never in the kept classes, in another country, older than the stored row, or outside the border writes none; a modify of an
  object the lane did not hold writes none (its old tags are unknown, so every key would read "added": counted ``tags_unknown_before``);
  a change that leaves the tags as they were (a moved node, a re-drawn way) writes none and is counted ``tags_unchanged``; a missing
  ``version`` is stored NULL and counted ``version_absent``; an object that moved out of the border writes none (the world did not change).
  A delete writes a ``removed`` row for every key the object held (``object_event='deleted'``), a stored object whose new tags no longer
  qualify writes its real key changes (``'left_class'``), and a ``create`` writes every key as ``added`` (``'created'``).

THE DERIVED TABLES. The search and map indexes and the admin-1 split are built from the objects. A day that changed any object
clears the indexes in the same transaction (they read "not indexed" until rebuilt) and moves the country's basis
(``lane_models.country_basis``), so a split counted before it reads as stale; the run then rebuilds the two indexes once. Rebuilding
whole is the simple, correct choice and its cost is part of the measurement (S5), not a hidden one.

THE NETWORK. Never imported here: the fetch is the source's. ``tests/test_osm_apply.py`` runs a whole update with the airplane
socket guard armed and counts zero resolutions.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, cast

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from src.monitoring.secret_scrub import log_failure, record_text
from src.osm import tags as T
from src.osm.changes import OscChange, parse_osc, tag_changes
from src.osm.geometry import (
    Border,
    decode_coords,
    decode_rings,
    encode_coords,
    representative_point,
)
from src.osm.ingest import _clear_derived, build_row, country_codes
from src.osm.replication import (
    KILL_SWITCH_TEXT,
    DiffNotFound,
    DiffRefused,
    DiffSource,
    DiffUnavailable,
    ReplicationError,
    ReplicationState,
    parse_state,
    plan_updates,
    region_of,
)
from src.versioned.lanes import CHUNK_SIZE

_LOG = logging.getLogger("osm.apply")

#: Tag rows held in memory before they are written (the transaction is still the file's one).
TAG_ROW_BATCH = 5000

#: The substrate feed one country's daily change files are recorded under.
FEED_PREFIX = "osm-daily:"


def feed_name(alpha3: str) -> str:
    return f"{FEED_PREFIX}{alpha3}"


@dataclass
class DiffCounts:
    """What one change file did, by name. Counters only: no verdict, and a number this build did not measure is absent, never 0."""

    #: Objects in the file, by kind of object. (Untagged nodes are way vertices; they are counted here and nowhere else.)
    nodes: int = 0
    ways: int = 0
    relations: int = 0
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    #: A stored object deleted because its tags no longer qualify (``left_class``) or because it moved out of the border (``left_country``).
    left_class: int = 0
    left_country: int = 0
    #: Dropped: tagged objects of a class the lane does not keep.
    other_class: int = 0
    #: Dropped: a kept-class node whose position is outside the border / a way or relation not in the country.
    outside_country: int = 0
    #: A node (or its position) the file gives no coordinates for.
    unreadable_position: int = 0
    ways_not_placed: int = 0
    geometry_kept: int = 0
    #: Kept-class relations that no stored member places in the country.
    relations_not_placed: int = 0
    #: A change whose ``version`` is below the stored object's: ignored, never applied over a newer row.
    older_than_stored: int = 0
    #: A change to an object another country's cut holds (the file covers the whole region): not this country's, left alone.
    other_country: int = 0
    #: Tag rows written (S2), the objects that wrote none for a stated reason (the tags did not change, or the lane did not hold the
    #: object before the file so its old tags are unknown), and the objects whose rows say a NULL ``version`` because the file gave none.
    tag_rows: int = 0
    tags_unchanged: int = 0
    tags_unknown_before: int = 0
    version_absent: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)

    def changed(self) -> int:
        return self.inserted + self.updated + self.deleted


@dataclass
class UpdateReport:
    """What :func:`update_country` did. ``outcome`` is exactly one of the strings below, and ``reason`` is the code's sentence for it."""

    alpha3: str
    outcome: str = "current"
    reason: str | None = None
    #: Where the objects stood before and after, as sequence numbers (None = the country had no position).
    from_sequence: int | None = None
    to_sequence: int | None = None
    #: The mirror's newest sequence when it was read, and the files still owed when the run stopped.
    mirror_sequence: int | None = None
    owed_remaining: int | None = None
    diffs: list[dict] = field(default_factory=list)
    search_index: dict | None = None
    view_index: dict | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


#: ``outcome`` values. ``applied``: at least one file applied and nothing stopped the run early. ``current``: the mirror had nothing newer.
#: ``rebaseline_needed``: the next file owed is not available, so the extract has to be cut again (this module cuts it in
#: :func:`rebaseline`; the download is the caller's, under its consent). ``refused``: a gate stopped it, named in ``reason``.
#: ``superseded``: the country was cut or updated by something else mid-run, so the file was not applied. ``unavailable``: the network or the mirror failed. ``stopped``: the budget the caller gave ran out. ``failed``: a change file would
#: not parse (the transaction was rolled back). ``not-ready``: this country cannot be updated as it is (see ``reason``).
OUTCOMES = (
    "current", "applied", "rebaseline_needed", "refused", "unavailable", "stopped", "failed", "not-ready", "mirror-unreadable", "superseded",
)


class _Superseded(Exception):
    """The country's position is not the one this file follows (see ``update_country``)."""


# --------------------------------------------------------------------------- #
#  applying one change file
# --------------------------------------------------------------------------- #
def _chunks(ids: list[int]):
    for i in range(0, len(ids), CHUNK_SIZE):
        yield ids[i : i + CHUNK_SIZE]


class _Ctx:
    """What one file's apply reads: the country, its border, and the table."""

    def __init__(self, s: Session, alpha3: str, border: Border, relation_id: int | None, diff_timestamp: datetime | None = None) -> None:
        from src.osm.lane_models import osm_objects_table

        self.s = s
        self.alpha3 = alpha3
        self.border = border
        self.relation_id = relation_id
        self.t = osm_objects_table
        self._tag_columns = [
            osm_objects_table.c[name] for name in (*(T.column_name(k) for k in T.SCALAR_KEYS), *T.FAMILIES.values(), "other_tags")
        ]
        #: Positions, in the file, of the nodes its kept-class ways name (pass 1).
        self.locs: dict[int, tuple[float, float]] = {}
        #: The file's own timestamp (the tag rows' ``diff_timestamp``) and the rows waiting to be written.
        self.diff_timestamp = diff_timestamp
        self.pending: list[dict] = []

    def stored(self, osm_type: str, osm_id: int):
        t = self.t
        return self.s.execute(
            select(t.c.id, t.c.version, t.c.country_alpha3).where(t.c.osm_type == osm_type, t.c.osm_id == osm_id)
        ).first()

    def stored_tags(self, row_id: int) -> dict[str, str]:
        # Only the tag columns: a way's vertices and a relation's members can be kilobytes, and they are not read here.
        row = self.s.execute(select(*self._tag_columns).where(self.t.c.id == row_id)).mappings().first()
        return T.tags_of(row) if row is not None else {}

    def record_tags(self, c: OscChange, stored, new: dict[str, str] | None, counts: DiffCounts, *, event: str | None = None) -> None:
        """The tag rows for ONE object about to change (call BEFORE the stored row is written or deleted: the old tags are read from it).

        ``new`` is the tags after the file (None for a delete). ``event`` is the object-level fact when this change is one; a ``create`` of
        an object the lane did not hold is ``created`` whatever the caller says.
        """
        if stored is None:
            if c.action != "create":
                counts.tags_unknown_before += 1
                return
            old: dict[str, str] = {}
            event = "created"
        else:
            old = self.stored_tags(stored.id)
        changes = tag_changes(old, new)
        if not changes:
            counts.tags_unchanged += 1
            return
        if c.version is None:
            counts.version_absent += 1
        for ch in changes:
            self.pending.append(
                {
                    "osm_type": c.osm_type, "osm_id": c.osm_id, "key": ch.key, "change": ch.change, "old_value": ch.old_value,
                    "new_value": ch.new_value, "diff_timestamp": self.diff_timestamp, "object_version": c.version,
                    "country_alpha3": self.alpha3, "object_event": event,
                }
            )
        counts.tag_rows += len(changes)
        if len(self.pending) >= TAG_ROW_BATCH:
            self.flush_tags()

    def flush_tags(self) -> None:
        from src.osm.lane_models import OsmTagChange

        if self.pending:
            self.s.execute(insert(OsmTagChange), self.pending)
            self.pending = []

    def stored_points(self, ids: list[int]) -> dict[int, tuple[float, float]]:
        # A position is a fact about the world, not about who holds the row, so a neighbour's stored node is a vertex like any other.
        t = self.t
        out: dict[int, tuple[float, float]] = {}
        for chunk in _chunks(ids):
            for oid, lat, lon in self.s.execute(
                select(t.c.osm_id, t.c.lat, t.c.lon).where(t.c.osm_type == "n", t.c.osm_id.in_(chunk))
            ):
                if lat is not None and lon is not None:
                    out[oid] = (lat, lon)
        return out

    def any_stored_member(self, members) -> bool:
        t = self.t
        for kind in ("n", "w"):
            ids = [ref for typ, ref, _role in members if typ == kind]
            for chunk in _chunks(ids):
                if self.s.execute(select(t.c.id).where(t.c.country_alpha3 == self.alpha3, t.c.osm_type == kind, t.c.osm_id.in_(chunk)).limit(1)).first():
                    return True
        return False

    def resolve(self, refs: tuple[int, ...]) -> list[tuple[float, float]] | None:
        """Every vertex's position, or None when ANY cannot be found (the file's nodes first, then the stored ones)."""
        if not refs:
            return None
        missing = [r for r in dict.fromkeys(refs) if r not in self.locs]
        found = self.stored_points(missing) if missing else {}
        pts = []
        for r in refs:
            p = self.locs.get(r) or found.get(r)
            if p is None:
                return None
            pts.append(p)
        return pts


def _delete(ctx: _Ctx, row_id: int) -> None:
    ctx.s.execute(delete(ctx.t).where(ctx.t.c.id == row_id))


def _write(ctx: _Ctx, c: OscChange, stored, row: dict, counts: DiffCounts, *, keep_shape: bool = False) -> None:
    if stored is None:
        ctx.s.execute(insert(ctx.t), row)
        counts.inserted += 1
        return
    values = {k: v for k, v in row.items() if k not in ("osm_type", "osm_id")}
    if keep_shape:
        for k in ("lat", "lon", "geom", "node_count"):
            values.pop(k, None)
    ctx.s.execute(update(ctx.t).where(ctx.t.c.id == stored.id).values(**values))
    counts.updated += 1


def _skip(ctx: _Ctx, stored, c: OscChange, counts: DiffCounts) -> bool:
    """True when this change is not to be applied: the row is another country's, or the change is older than the row (a delete included)."""
    if stored is not None and stored.country_alpha3 != ctx.alpha3:
        counts.other_country += 1
        return True
    if stored is not None and stored.version is not None and c.version is not None and c.version < stored.version:
        counts.older_than_stored += 1
        return True
    return False


def _apply_node(ctx: _Ctx, c: OscChange, counts: DiffCounts) -> None:
    stored = ctx.stored("n", c.osm_id)
    if _skip(ctx, stored, c, counts):
        return
    if c.action == "delete":
        if stored is not None:
            ctx.record_tags(c, stored, None, counts, event="deleted")
            _delete(ctx, stored.id)
            counts.deleted += 1
        return
    kind, pkey, pval, notable = T.classify(c.tags, is_way=False)
    if c.lat is None or c.lon is None:
        counts.unreadable_position += 1
        return
    inside = ctx.border.contains(c.lat, c.lon)
    if kind is None or not inside:
        if stored is not None:
            if kind is None:  # its tags stopped qualifying: a real tag change. (Out of the border instead: the world did not change, no row.)
                ctx.record_tags(c, stored, c.tags, counts, event="left_class")
            _delete(ctx, stored.id)
            counts.deleted += 1
            counts.left_class += 1 if kind is None else 0
            counts.left_country += 0 if kind is None else 1
        elif kind is not None:
            counts.outside_country += 1
        elif c.tags:
            counts.other_class += 1
        return
    row = build_row(
        "n", c.osm_id, c.version, c.timestamp, c.tags,
        kind=kind, pkey=pkey, pval=pval, notable=notable, alpha3=ctx.alpha3, lat=c.lat, lon=c.lon, geom=None, node_count=None, members=None,
    )
    ctx.record_tags(c, stored, c.tags, counts)
    _write(ctx, c, stored, row, counts)


def _apply_way(ctx: _Ctx, c: OscChange, counts: DiffCounts) -> None:
    stored = ctx.stored("w", c.osm_id)
    if _skip(ctx, stored, c, counts):
        return
    if c.action == "delete":
        if stored is not None:
            ctx.record_tags(c, stored, None, counts, event="deleted")
            _delete(ctx, stored.id)
            counts.deleted += 1
        return
    kind, pkey, pval, notable = T.classify(c.tags, is_way=True)
    if kind is None:
        if stored is not None:
            ctx.record_tags(c, stored, c.tags, counts, event="left_class")
            _delete(ctx, stored.id)
            counts.deleted += 1
            counts.left_class += 1
        elif c.tags:
            counts.other_class += 1
        return
    pts = ctx.resolve(c.refs)
    if pts is None:
        if stored is None:
            counts.ways_not_placed += 1
            return
        # Its vertices cannot all be found, so its shape stays what it was; the tags are the file's.
        row = build_row(
            "w", c.osm_id, c.version, c.timestamp, c.tags,
            kind=kind, pkey=pkey, pval=pval, notable=notable, alpha3=ctx.alpha3, lat=None, lon=None, geom=None, node_count=None, members=None,
        )
        ctx.record_tags(c, stored, c.tags, counts)
        _write(ctx, c, stored, row, counts, keep_shape=True)
        counts.geometry_kept += 1
        return
    rp = representative_point(pts)
    if rp is None or not ctx.border.contains(*rp):
        if stored is not None:
            _delete(ctx, stored.id)
            counts.deleted += 1
            counts.left_country += 1
        else:
            counts.outside_country += 1
        return
    row = build_row(
        "w", c.osm_id, c.version, c.timestamp, c.tags,
        kind=kind, pkey=pkey, pval=pval, notable=notable, alpha3=ctx.alpha3,
        lat=rp[0], lon=rp[1], geom=encode_coords(pts), node_count=len(pts), members=None,
    )
    ctx.record_tags(c, stored, c.tags, counts)
    _write(ctx, c, stored, row, counts)


def _apply_relation(ctx: _Ctx, c: OscChange, counts: DiffCounts) -> None:
    stored = ctx.stored("r", c.osm_id)
    if _skip(ctx, stored, c, counts):
        return
    if c.action == "delete":
        if stored is not None:
            ctx.record_tags(c, stored, None, counts, event="deleted")
            _delete(ctx, stored.id)
            counts.deleted += 1
        return
    kind, pkey, pval, notable = T.classify(c.tags, is_way=False)
    if kind is None:
        if stored is not None:
            ctx.record_tags(c, stored, c.tags, counts, event="left_class")
            _delete(ctx, stored.id)
            counts.deleted += 1
            counts.left_class += 1
        elif c.tags:
            counts.other_class += 1
        return
    # The cut's rule: a relation is in the country when it IS the country's border relation or one of its node/way members already is.
    if not (c.osm_id == ctx.relation_id or ctx.any_stored_member(c.members)):
        if stored is not None:
            _delete(ctx, stored.id)
            counts.deleted += 1
            counts.left_country += 1
        else:
            counts.relations_not_placed += 1
        return
    row = build_row(
        "r", c.osm_id, c.version, c.timestamp, c.tags,
        kind=kind, pkey=pkey, pval=pval, notable=notable, alpha3=ctx.alpha3, lat=None, lon=None, geom=None, node_count=None,
        members=json.dumps([[m[0], m[1], m[2]] for m in c.members], separators=(",", ":")),
    )
    ctx.record_tags(c, stored, c.tags, counts)
    _write(ctx, c, stored, row, counts)


def apply_osc_file(
    s: Session, alpha3: str, border: Border, relation_id: int | None, path: Path, *, diff_timestamp: datetime | None = None
) -> DiffCounts:
    """Apply one gzipped ``.osc`` to ``alpha3``'s objects inside the caller's transaction. Raises on a file that will not parse.

    Two passes over the file: the first reads the positions of its own nodes (a new way's vertices are usually in the same day's file),
    the second applies each object in file order, holding the kept relations back until every node and way has been applied (a relation
    is placed by its members, and a member created in the same file must be stored first).
    """
    ctx = _Ctx(s, alpha3, border, relation_id, diff_timestamp)
    # Pass 1a: the vertices the file's own kept-class ways name. Pass 1b: where the file puts exactly those nodes (not "the nodes inside the
    # bounding box": a way with one vertex just outside the box is still placed, as the cut places it). Memory follows the file's way
    # vertices, never its node count.
    needed: set[int] = set()
    with gzip.open(path, "rb") as fh:
        for c in parse_osc(cast(IO[bytes], fh)):
            if c.osm_type == "w" and c.action != "delete" and c.refs and T.classify(c.tags, is_way=True)[0] is not None:
                needed.update(c.refs)
    if needed:
        with gzip.open(path, "rb") as fh:
            for c in parse_osc(cast(IO[bytes], fh)):
                if c.osm_type == "n" and c.action != "delete" and c.osm_id in needed and c.lat is not None and c.lon is not None:
                    ctx.locs[c.osm_id] = (c.lat, c.lon)
    counts = DiffCounts()
    relations: list[OscChange] = []
    with gzip.open(path, "rb") as fh:
        for c in parse_osc(cast(IO[bytes], fh)):
            if c.osm_type == "n":
                counts.nodes += 1
                _apply_node(ctx, c, counts)
            elif c.osm_type == "w":
                counts.ways += 1
                _apply_way(ctx, c, counts)
            else:
                counts.relations += 1
                relations.append(c)
    for c in relations:
        _apply_relation(ctx, c, counts)
    ctx.flush_tags()
    return counts


# --------------------------------------------------------------------------- #
#  the cursor, the gap and the run
# --------------------------------------------------------------------------- #
def _position(country) -> tuple[int | None, datetime | None]:
    """Where the country's objects stand: the last applied file, else the extract's own header."""
    if country.diff_sequence is not None:
        return country.diff_sequence, country.diff_timestamp
    return country.extract_sequence, country.extract_vintage


def _sync_cursor(s: Session, alpha3: str, country) -> None:
    """Make the substrate cursor say where the OBJECTS stand, publishing a gap if it said something else.

    The cursor can disagree with the objects when the country was cut again after the last update (a newer or an older extract). The
    objects are the authority; the stretch between the two positions was not seen as changes, so it is published as a gap whose reason is
    ``budget`` (the substrate's word for «the operator's own choice»: they re-cut instead of updating).
    """
    from src.versioned import feed as feedmod
    from src.versioned.feed import ChangeBatch, GapReport

    pos, ts = _position(country)
    if pos is None:
        return
    feed = feed_name(alpha3)
    stored = feedmod.stored_token(s, feed)
    if stored == str(pos):
        return
    if stored is None:
        feedmod.record_batch(s, ChangeBatch(feed=feed, next_token=str(pos)))
        return
    feedmod.record_batch(
        s,
        ChangeBatch(
            feed=feed,
            next_token=str(pos),
            resumed_from=stored,
            gap=GapReport(reason="budget", from_token=stored, to_token=str(pos), to_time=ts),
        ),
    )


def _record_applied(s: Session, alpha3: str, region: str, seq: int, ts: datetime, byte_size: int, prior: int | None) -> None:
    from src.versioned import feed as feedmod
    from src.versioned.feed import ChangeBatch, FeedChange

    feedmod.record_batch(
        s,
        ChangeBatch(
            feed=feed_name(alpha3),
            changes=(FeedChange(change_ref=f"{region}:{seq}", change_kind="edit", occurred_at=ts, cursor_token=str(seq), byte_delta=byte_size),),
            next_token=str(seq),
            resumed_from=None if prior is None else str(prior),
        ),
    )


def _rebuild_indexes(alpha3: str, report: UpdateReport) -> None:
    """The two indexes the cut builds at its end, and the stored counts of the current places (R439), rebuilt once after the run. A failure is logged and leaves them reading as not matching (the counts, as computed)."""
    try:
        from src.osm.places import build_search_index

        report.search_index = build_search_index(alpha3)
    except Exception as exc:  # noqa: BLE001 - the update is applied; only its index is missing
        log_failure(_LOG, f"the {alpha3} search index was not rebuilt after the update", exc, level=logging.WARNING)
    try:
        from src.osm.view import build_view_index

        report.view_index = build_view_index(alpha3)
    except Exception as exc:  # noqa: BLE001 - the update is applied; only its view index is missing
        log_failure(_LOG, f"the {alpha3} view index was not rebuilt after the update", exc, level=logging.WARNING)
    # R439: the stored counts of the current places read as stale once the apply moved the country's position; rebuilt here, once per run (never fails the run).
    from src.osm.places_summary import build_quietly

    build_quietly(alpha3)


def update_country(
    country: str,
    source: DiffSource | None = None,
    *,
    source_for: Callable[[str], DiffSource] | None = None,
    workdir: Path | None = None,
    max_files: int | None = None,
    kill_switch=None,
    on_progress: Callable[[int, int], None] | None = None,
) -> UpdateReport:
    """Bring ``country`` up to the mirror's newest daily change file, one file at a time. Returns what happened; raises nothing a caller should plan on.

    ``source`` is the mirror to read; ``source_for(region)`` builds it once the country's own region is known (the production caller cannot
    name the region before the cut's extract is read). Exactly one of the two.

    ``max_files`` bounds the run (the budget a caller sets); a run that stops on it reports ``stopped`` with how many files are still
    owed, and it is NOT a gap: the next run continues from the position. ``kill_switch`` is a callable returning True while airplane
    mode is engaged (default: the app's own); it is checked before every request, so a switch thrown mid-run stops the next fetch.
    ``on_progress(applied, owed)`` is called once the files owed are known and after each file applied; it can never end the run (a
    callback that raises is logged and the run goes on).
    """
    from src.ingest import kill_switch_active
    from src.osm.lane_models import OsmCountry, OsmDiffRun
    from src.paths import data_dir
    from src.versioned import store

    if (source is None) == (source_for is None):
        raise TypeError("update_country takes exactly one of source and source_for")
    _alpha2, alpha3 = country_codes(country)
    report = UpdateReport(alpha3=alpha3)
    refused = kill_switch or kill_switch_active
    work = Path(workdir) if workdir is not None else data_dir() / "osm_work"

    if not store.lane_exists("osm"):
        report.outcome, report.reason = "not-ready", "no OpenStreetMap country has been cut yet"
        return report
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        if row is None or row.status != "complete":
            report.outcome, report.reason = "not-ready", "this country has no finished cut to update"
            return report
        region = region_of(row.extract_name)
        pos, pos_ts = _position(row)
        rings, relation_id = row.border_rings, row.relation_id
    if region is None:
        report.outcome, report.reason = "not-ready", "the cut's extract file is not one of the mirror's regions, so its change files are unknown"
        return report
    if pos is None:
        report.outcome, report.reason = "not-ready", "the cut's extract carries no replication sequence, so updates cannot start from it (cut it again from a current extract)"
        return report
    if rings is None:
        report.outcome, report.reason = "not-ready", "this country was cut before its border was kept, so a change cannot be placed (cut it again)"
        return report
    report.from_sequence = pos
    if source is None:
        assert source_for is not None
        source = source_for(region)

    if refused():
        report.outcome, report.reason = "refused", KILL_SWITCH_TEXT
        return report
    try:
        remote = parse_state(source.fetch_state())
    except DiffRefused as exc:
        report.outcome, report.reason = "refused", record_text(exc)
        return report
    except DiffNotFound:
        report.outcome, report.reason = "mirror-unreadable", "the mirror has no state file for this region"
        return report
    except DiffUnavailable as exc:
        report.outcome, report.reason = "unavailable", record_text(exc)
        return report
    except ReplicationError as exc:
        report.outcome, report.reason = "mirror-unreadable", record_text(exc)
        return report
    report.mirror_sequence = remote.sequence

    plan = plan_updates(applied_sequence=pos, applied_timestamp=pos_ts, remote=remote)
    if plan.action == "current":
        report.outcome, report.reason = "current", plan.reason
        report.to_sequence = pos
        return report
    if plan.action == "mirror-behind":
        report.outcome, report.reason = "mirror-unreadable", plan.reason
        return report
    if plan.action == "rebaseline":
        report.outcome, report.reason = "rebaseline_needed", plan.reason
        return report
    assert plan.first is not None and plan.last is not None

    with store.lane_session("osm") as s:
        _sync_cursor(s, alpha3, s.query(OsmCountry).filter_by(alpha3=alpha3).one())
    border = Border(decode_rings(rings))
    work.mkdir(parents=True, exist_ok=True)
    seq = plan.first
    done = 0
    owed = plan.last - plan.first + 1

    def progress() -> None:
        if on_progress is None:
            return
        try:
            on_progress(done, owed)
        except Exception as exc:  # noqa: BLE001 - a progress display must never end an update
            log_failure(_LOG, f"the {alpha3} progress callback failed", exc, level=logging.WARNING)

    progress()
    while seq <= plan.last:
        if max_files is not None and done >= max_files:
            report.outcome, report.reason = "stopped", "the budget for this run was reached"
            report.owed_remaining = plan.last - seq + 1
            break
        if refused():
            report.outcome, report.reason = "refused", KILL_SWITCH_TEXT
            report.owed_remaining = plan.last - seq + 1
            break
        dest = work / f"{alpha3}-{seq}.osc.gz"
        try:
            t0 = time.monotonic()
            state = parse_state(source.fetch_state(seq))
            if state.sequence != seq:
                raise ReplicationError("the change file's state names another sequence number")
            nbytes = source.fetch_diff(seq, dest)
            fetch_s = time.monotonic() - t0
        except DiffNotFound:
            report.outcome = "rebaseline_needed"
            report.reason = "the mirror no longer holds a change file the country still needs, so the extract has to be downloaded again"
            report.owed_remaining = plan.last - seq + 1
            break
        except DiffRefused as exc:
            report.outcome, report.reason = "refused", record_text(exc)
            report.owed_remaining = plan.last - seq + 1
            break
        except DiffUnavailable as exc:
            report.outcome, report.reason = "unavailable", record_text(exc)
            report.owed_remaining = plan.last - seq + 1
            break
        except ReplicationError as exc:
            report.outcome, report.reason = "mirror-unreadable", record_text(exc)
            report.owed_remaining = plan.last - seq + 1
            break
        try:
            t1 = time.monotonic()
            with store.lane_session("osm") as s:
                country_row = s.query(OsmCountry).filter_by(alpha3=alpha3).one()
                prior = _position(country_row)[0]
                if country_row.status != "complete" or prior != seq - 1:
                    # Cut or updated by something else since this run read its position (a re-cut, a second run): this file is not
                    # the next one owed, and applying it would put the position behind objects that are already past it.
                    raise _Superseded
                # The derived rows go BEFORE the objects change (row ids are reused once objects are deleted), in the same transaction.
                _clear_derived(s, alpha3)
                counts = apply_osc_file(s, alpha3, border, relation_id, dest, diff_timestamp=state.timestamp)
                apply_s = time.monotonic() - t1
                country_row.diff_sequence = seq
                country_row.diff_timestamp = state.timestamp
                s.add(
                    OsmDiffRun(
                        alpha3=alpha3, sequence=seq, diff_timestamp=state.timestamp, bytes_fetched=nbytes,
                        fetch_seconds=round(fetch_s, 3), apply_seconds=round(apply_s, 3), counts_json=json.dumps(counts.as_dict(), sort_keys=True),
                    )
                )
                _record_applied(s, alpha3, region, seq, state.timestamp, nbytes, prior)
        except _Superseded:
            report.outcome = "superseded"
            report.reason = "the country was cut or updated by something else while this file was being fetched, so it was not applied"
            report.owed_remaining = plan.last - seq + 1
            break
        except Exception as exc:  # noqa: BLE001 - one file that will not apply ends the run, named; its transaction was rolled back
            report.outcome, report.reason = "failed", f"change file {seq} did not apply: {record_text(exc, typed=True)}"
            report.owed_remaining = plan.last - seq + 1
            log_failure(_LOG, f"the {alpha3} change file {seq} did not apply", exc, level=logging.WARNING)
            break
        finally:
            dest.unlink(missing_ok=True)
        report.diffs.append(
            {"sequence": seq, "timestamp": state.timestamp.isoformat(), "bytes_fetched": nbytes, "fetch_seconds": round(fetch_s, 3),
             "apply_seconds": round(apply_s, 3), "counts": counts.as_dict()}
        )
        report.to_sequence = seq
        seq += 1
        done += 1
        progress()
    else:
        report.outcome = "applied" if report.diffs else report.outcome
    if report.to_sequence is None:
        report.to_sequence = pos
    if report.diffs:  # even a quiet day moved the basis, so the indexes read as not matching until rebuilt
        _rebuild_indexes(alpha3, report)
    return report


# --------------------------------------------------------------------------- #
#  re-baselining
# --------------------------------------------------------------------------- #
class RebaselineRefused(ValueError):
    """The extract offered cannot be a new baseline for the country; the text says why. Nothing was cut."""


def rebaseline(country: str, extract_path: str | Path, *, reason: str, reader: str | None = None) -> dict:
    """Cut ``country`` again from a fresh extract and PUBLISH that the change files between the old position and the new one were not applied.

    The download of the extract is the caller's (under the one online consent); this is the step after it. The extract is refused BEFORE
    the cut when it carries no replication sequence (no update could start from it) or is not newer than what is already applied
    (it would move the country backwards). After the cut, the stretch between the old and the new position is a ``retention`` gap in the
    substrate (the source's own limit is why), dated by when it was detected, and the cursor stands at the new baseline.

    Returns ``{"alpha3", "from_sequence", "to_sequence", "reason", "report"}``; ``report`` is the cut's own :class:`IngestReport` dict.
    """
    from src.osm.ingest import ingest_country
    from src.osm.lane_models import OsmCountry
    from src.osm.reader import open_extract
    from src.versioned import feed as feedmod
    from src.versioned import store
    from src.versioned.feed import ChangeBatch, GapReport

    _alpha2, alpha3 = country_codes(country)
    hdr = open_extract(extract_path, reader=reader).header()
    if hdr.replication_sequence is None:
        raise RebaselineRefused("this extract carries no replication sequence, so no update could start from it")
    old_pos: int | None = None
    old_ts: datetime | None = None
    if store.lane_exists("osm"):
        with store.lane_session("osm") as s:
            row = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
            if row is not None and row.status == "complete":
                old_pos, old_ts = _position(row)
    if old_pos is not None and hdr.replication_sequence <= old_pos:
        raise RebaselineRefused("this extract is not newer than the data already applied, so cutting it again would move the country back")
    rep = ingest_country(extract_path, alpha3, reader=reader)
    with store.lane_session("osm") as s:
        feed = feed_name(alpha3)
        stored = feedmod.stored_token(s, feed)
        new_pos = str(hdr.replication_sequence)
        gap = None
        if old_pos is not None:
            gap = GapReport(
                reason="retention", from_token=str(old_pos), to_token=new_pos, from_time=old_ts, to_time=hdr.replication_timestamp
            )
        feedmod.record_batch(s, ChangeBatch(feed=feed, next_token=new_pos, resumed_from=stored, gap=gap))
    _LOG.info("%s re-baselined from a fresh extract (%s)", alpha3, reason)
    return {
        "alpha3": alpha3,
        "from_sequence": old_pos,
        "to_sequence": hdr.replication_sequence,
        "reason": reason,
        "at": datetime.now(UTC).isoformat(),
        "report": rep.to_dict(),
    }


__all__ = [
    "OUTCOMES", "DiffCounts", "RebaselineRefused", "ReplicationState", "UpdateReport", "apply_osc_file", "decode_coords", "feed_name",
    "rebaseline", "update_country",
]
