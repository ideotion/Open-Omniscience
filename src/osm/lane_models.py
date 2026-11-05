"""The OSM lane's own tables in ``osm.db`` (Q811 = b, Q810, Q813, Q825).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q811 = b: «SQLite for everything». Q825 = a: «Same answers as the Wikipedia lane (Q719, Q720)»
-- ``osm.db`` beside the corpus, linked by ids, encrypted with the same passphrase. Both are
the substrate's, not this module's: these tables live on ``LaneBase`` and reach ``osm.db``
ONLY through ``src.versioned.store.create_schema`` (``_lane_specific_models("osm")``), which
opens the file through the ONE keyed factory. A lane file gets its own tables and no other
lane's.

TEN TABLES (the fourth and fifth S05-04 S4's, the sixth and seventh S5's, the eighth and ninth S6's, the last S06-01 S1's), two
full-text indexes and one R*Tree (``src/osm/view.py``).

* ``osm_objects`` -- one row per kept object of an ingested country: identity (type + id),
  the source's ``version`` and ``timestamp``, what it is (``kind``, the primary tag), where it
  is (a representative point; a way's vertices in ``geom``), the curated columns
  (``src/osm/tags.py``), the four family columns, and the blob. A relation's ``geom`` and point
  are NULL: its shape is its members', and a NULL here is a GAP, never a (0, 0).
* ``osm_countries`` -- one row per country cut from an extract: what file it came from, the
  file's size and vintage, which reader ran, how long it took, what it kept, the blob measured
  both ways (Q810's note), and whether it finished. A country whose ingest did not finish says
  ``failed`` and every reader below refuses it rather than counting a partial country.
* ``osm_tag_changes`` -- Q813 = a's MODEL: key added / removed / modified, with the diff's
  timestamp and the object's ``version``. EMPTY in 0.5; the daily apply fills it in 0.6 (S06-01 S2,
  plus R428's ``country_alpha3`` and ``object_event``).
* ``osm_history_changes`` -- the PRIOR (Q814 = b): the same key-level shape, read out of the
  full-history planet for one country, plus the object-level events (``created``, ``deleted``,
  ``restored``) whose ``key`` is NULL. A table of its own rather than rows in
  ``osm_tag_changes``, because S06-01 states the planet's prior SEPARATELY from the window 0.6
  tracks, and one table read two ways is how the two come to be blended.
* ``osm_history_cuts`` -- one row per country cut from the history file, with what was
  measured: the file, its size and vintage, the reader, the seconds, the counts, the gap.
* ``osm_admin1_splits`` -- analytic 1 per admin-1 region (Q815 · 1), one row per country: the
  counts per region of row E's published outlines, and the two things they were computed FROM
  (the country's ingest and the outline file's vintage), so a split that no longer matches
  either reads as stale instead of as current.
* ``osm_search_indexes`` -- one row per country whose names and addresses are in the two
  full-text indexes (``osm_names``, ``osm_addresses``; ``src/osm/places.py`` creates them,
  because a virtual table is not a mapped model), with what was indexed and from which ingest.
* ``osm_diff_runs`` -- one row per daily change file applied to a country (S06-01 S1): its
  sequence number, its own timestamp, what was fetched and how long it took, what it did to the
  objects. The MEASURED cost of a daily update lives here, one measurement per day.

WHY ``osm_objects`` IS BUILT FROM A ``Table`` AND NOT CLASS ATTRIBUTES. Its curated columns are
generated from ``tags.SCALAR_KEYS`` -- one list, read by the splitter, the joiner and the
schema -- because three hand-kept copies of an 80-entry list would drift, and the copy that
drifts silently puts a tag in the blob that the column list promises is a column.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.osm.tags import FAMILIES, SCALAR_KEYS, column_name
from src.versioned.models import LaneBase, LaneUTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


_STRUCTURAL: list[Column[Any]] = [
    Column("id", Integer, primary_key=True),
    #: ``n`` | ``w`` | ``r`` -- OSM's own three types.
    Column("osm_type", String(1), nullable=False),
    Column("osm_id", BigInteger, nullable=False),
    Column("version", Integer, nullable=True),
    Column("timestamp", LaneUTCDateTime(), nullable=True),
    #: ISO 3166-1 alpha-3 (Q312 = a: alpha-3 from birth).
    Column("country_alpha3", String(3), nullable=False),
    Column("kind", String(12), nullable=False),
    Column("notable", Boolean, nullable=False, default=False),
    Column("primary_key", String(32), nullable=True),
    Column("primary_value", Text, nullable=True),
    Column("lat", Float, nullable=True),
    Column("lon", Float, nullable=True),
    #: A way's vertices, ``geometry.encode_coords``. NULL for a node (its point is its shape)
    #: and for a relation (a gap, stated).
    Column("geom", LargeBinary, nullable=True),
    Column("node_count", Integer, nullable=True),
    #: A relation's members as compact JSON ``[[type, ref, role], ...]``.
    Column("members", Text, nullable=True),
]
_FAMILY_COLUMNS: list[Column[Any]] = [Column(col, Text, nullable=True) for col in FAMILIES.values()]
_SCALAR_COLUMNS: list[Column[Any]] = [Column(column_name(k), Text, nullable=True) for k in SCALAR_KEYS]
#: Every tag the curated columns and families do not hold, as compact JSON. NULL when empty.
_BLOB: Column[Any] = Column("other_tags", Text, nullable=True)

osm_objects_table = Table(
    "osm_objects",
    LaneBase.metadata,
    *_STRUCTURAL,
    *_FAMILY_COLUMNS,
    *_SCALAR_COLUMNS,
    _BLOB,
    UniqueConstraint("osm_type", "osm_id", name="uq_osm_objects_type_id"),
    Index("ix_osm_objects_country_kind", "country_alpha3", "kind"),
    Index("ix_osm_objects_primary", "primary_key", "primary_value"),
    Index("ix_osm_objects_addr", "country_alpha3", column_name("addr:street"), column_name("addr:city")),
)


class OsmObject(LaneBase):
    """One kept object. Columns are ``osm_objects_table``'s; see the module docstring."""

    __table__ = osm_objects_table


class OsmCountry(LaneBase):
    """One country cut from an extract, and the measurements of that cut."""

    __tablename__ = "osm_countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpha2: Mapped[str] = mapped_column(String(2), nullable=False)
    alpha3: Mapped[str] = mapped_column(String(3), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The border relation the cut used.
    relation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: ``ingesting`` | ``complete`` | ``failed``.
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ingesting")
    #: Basename only: a full path would record where the operator keeps their files.
    extract_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    extract_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: The extract's replication timestamp: its VINTAGE (Q828). NULL = the file does not say.
    extract_vintage: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)
    #: ``pyosmium`` | ``python``.
    reader: Mapped[str | None] = mapped_column(String(16), nullable=True)
    started_at: Mapped[datetime] = mapped_column(LaneUTCDateTime(), nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)
    #: Wall-clock seconds of the whole cut, the row's measurement (S05-04 S4).
    ingest_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: ``{"poi": n, "road": n, ...}`` plus the passes' own counts. JSON.
    counts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The blob measured both ways (Q810's note): ``{"q810": bytes, "extended": bytes, "objects": n}``.
    blob_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The border as assembled: rings, vertices, segments that could not be closed, bbox.
    border_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Why a failed cut failed, in the reader's words.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The extract's replication SEQUENCE NUMBER (its header's ``osmosis_replication_sequence_number``): the
    #: place in the mirror's daily change files the extract was cut at, so the first update asks for the
    #: next one. NULL = the file does not say, and no update can start from it (S06-01 S1).
    extract_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: The border the cut used, as ``geometry.encode_rings``: kept so a daily update can place an object
    #: without reading the extract again. NULL on a country cut before this was kept (re-cut it).
    border_rings: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    #: The newest daily change file applied to this country's objects, and that file's own timestamp.
    #: NULL = none applied since the cut. Written in the SAME transaction as the object changes, so
    #: "which sequence are the objects at" has one answer.
    diff_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    diff_timestamp: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)


def country_basis(country: OsmCountry | None) -> str | None:
    """What a derived table (search index, map index, admin-1 split) was built FROM, as a comparable string.

    The cut's finish time, plus the daily change file the objects stand at when one has been applied: an
    update changes the objects without a new cut, and a table counted before it must read as stale, not
    as current. A country with no update keeps the exact string it always had, so nothing built before
    this existed reads as stale for it.
    """
    if country is None or country.finished_at is None:
        return None
    base = country.finished_at.isoformat()
    return base if country.diff_sequence is None else f"{base}+diff{country.diff_sequence}"


class OsmTagChange(LaneBase):
    """Q813 = a: one tag-level change, written by the daily apply (``src/osm/apply.py``, S06-01 S2).

    R428 added the last two columns, both NULLABLE and added to an existing lane file by the additive path: a deleted object has
    no ``osm_objects`` row left to name its country from, and the table had no way to say that an object appeared or disappeared.
    """

    __tablename__ = "osm_tag_changes"
    __table_args__ = (Index("ix_osm_tag_changes_object", "osm_type", "osm_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    osm_type: Mapped[str] = mapped_column(String(1), nullable=False)
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``added`` | ``removed`` | ``modified``.
    change: Mapped[str] = mapped_column(String(8), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The diff's own timestamp, never the time it was applied here.
    diff_timestamp: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)
    #: The object's ``version`` after the change.
    object_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(LaneUTCDateTime(), nullable=False, default=_utcnow)
    #: The country whose object it was when the change was applied (R428). NULL = a row written before this existed.
    country_alpha3: Mapped[str | None] = mapped_column(String(3), nullable=True)
    #: NULL = an ordinary key change on an object the lane held. ``created`` = the object entered the lane with this file's
    #: ``create``; ``deleted`` = the file deleted it (one ``removed`` row per key it held); ``left_class`` = the file's tags no longer
    #: qualify, so the lane dropped it (R428).
    object_event: Mapped[str | None] = mapped_column(String(10), nullable=True)


#: ``osm_tag_changes.object_event``.
OBJECT_EVENTS = ("created", "deleted", "left_class")

#: ``osm_history_changes.change``: the key-level three, then the object-level three.
HISTORY_CHANGES = ("added", "removed", "modified", "created", "deleted", "restored")


class OsmHistoryChange(LaneBase):
    """One change in the full-history planet's past for an object of a cut country (Q814 = b).

    A key-level row (``key`` set) is Q813's shape; an object-level row (``key`` NULL) says the
    object was created, deleted or restored at that version. ``version_timestamp`` is the
    VERSION's own time in the file, never the time the cut ran.
    """

    __tablename__ = "osm_history_changes"
    __table_args__ = (
        Index("ix_osm_history_country_key", "country_alpha3", "key"),
        Index("ix_osm_history_object", "osm_type", "osm_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_alpha3: Mapped[str] = mapped_column(String(3), nullable=False)
    osm_type: Mapped[str] = mapped_column(String(1), nullable=False)
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_timestamp: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)
    #: One of :data:`HISTORY_CHANGES`.
    change: Mapped[str] = mapped_column(String(8), nullable=False)
    #: NULL on an object-level row.
    key: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)


class OsmHistoryCut(LaneBase):
    """One country cut from the full-history planet, and the measurements of that cut."""

    __tablename__ = "osm_history_cuts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpha3: Mapped[str] = mapped_column(String(3), nullable=False, unique=True)
    #: ``ingesting`` | ``complete`` | ``failed``, as ``osm_countries``.
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ingesting")
    #: Basename only, as ``osm_countries.extract_name``.
    history_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    history_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: The history file's replication timestamp: how recent its last version is.
    history_vintage: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)
    reader: Mapped[str | None] = mapped_column(String(16), nullable=True)
    started_at: Mapped[datetime] = mapped_column(LaneUTCDateTime(), nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)
    #: Wall-clock seconds of the whole history cut: the row's measurement (S05-04 S4).
    ingest_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Objects, versions and rows per change, plus each pass's own counts. JSON.
    counts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The oldest and newest version timestamp read, ISO. JSON.
    span_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OsmDiffRun(LaneBase):
    """One daily change file applied to one country: what it was, what it cost, what it did (S06-01 S1).

    ``sequence`` and ``diff_timestamp`` are the MIRROR's (the file's number, and the time its state file
    gives it), never the time it was applied here (``applied_at``). The byte and second columns are
    MEASURED where the work happened; a cell this build did not measure is NULL, never 0.
    """

    __tablename__ = "osm_diff_runs"
    # NOT unique: a country cut again from another extract can apply the same file number onto a different baseline, and that is a
    # second run of it, not a collision (``applied_at`` orders them).
    __table_args__ = (Index("ix_osm_diff_runs_country_sequence", "alpha3", "sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpha3: Mapped[str] = mapped_column(String(3), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    diff_timestamp: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)
    applied_at: Mapped[datetime] = mapped_column(LaneUTCDateTime(), nullable=False, default=_utcnow)
    #: Compressed bytes fetched for the change file (the response body, as it crossed the wire).
    bytes_fetched: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fetch_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    apply_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: What the file did, by counter name (``DiffCounts``). JSON.
    counts_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class OsmAdmin1Split(LaneBase):
    """Analytic 1 per admin-1 region for one country, and what it was computed from."""

    __tablename__ = "osm_admin1_splits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpha3: Mapped[str] = mapped_column(String(3), nullable=False, unique=True)
    #: ``counting`` while it runs, then ``complete`` or ``failed``.
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="counting")
    #: The country's ``finished_at`` the split was counted from: a re-ingest makes it stale.
    basis_ingest: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The outline file's vintage and source: a rebuilt file makes it stale too.
    outline_vintage: Mapped[str | None] = mapped_column(Text, nullable=True)
    outline_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(LaneUTCDateTime(), nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime(), nullable=True)
    seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: ``{region_key: {"n": int, "present": {key: int}}}``.
    regions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Places inside the country's border but inside no published region outline.
    outside: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Places with no point of their own (a relation): counted, never placed.
    no_point: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OsmSearchIndex(LaneBase):
    """One country's rows in the name and address indexes, and the ingest they were built from."""

    __tablename__ = "osm_search_indexes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpha3: Mapped[str] = mapped_column(String(3), nullable=False, unique=True)
    basis_ingest: Mapped[str | None] = mapped_column(Text, nullable=True)
    names: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    addresses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Addresses on an object with no point of its own (a relation): counted, never located.
    addresses_no_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    built_at: Mapped[datetime] = mapped_column(LaneUTCDateTime(), nullable=False, default=_utcnow)
    seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class OsmViewIndex(LaneBase):
    """One country's rows in the map's R*Tree (``src/osm/view.py``), and the ingest they came from."""

    __tablename__ = "osm_view_indexes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpha3: Mapped[str] = mapped_column(String(3), nullable=False, unique=True)
    basis_ingest: Mapped[str | None] = mapped_column(Text, nullable=True)
    rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Objects with neither a shape nor a point (a relation): counted, never drawn.
    no_box: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    built_at: Mapped[datetime] = mapped_column(LaneUTCDateTime(), nullable=False, default=_utcnow)
    seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class OsmViewCell(LaneBase):
    """The map's cluster pyramid (``src/osm/view.py``): objects per grid cell, per zoom level.

    Level ``L`` cuts the globe into cells ``360 / 2**L`` degrees on a side; ``cx`` counts from
    180 degrees west and ``cy`` from the south pole. ``slat`` / ``slon`` are sums, so a cluster
    is drawn at the mean of what it counts, never at the cell's centre.
    """

    __tablename__ = "osm_view_cells"
    __table_args__ = (Index("ix_osm_view_cells_lookup", "level", "cy", "cx"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpha3: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    cx: Mapped[int] = mapped_column(Integer, nullable=False)
    cy: Mapped[int] = mapped_column(Integer, nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    slat: Mapped[float] = mapped_column(Float, nullable=False)
    slon: Mapped[float] = mapped_column(Float, nullable=False)


OSM_LANE_MODELS: tuple[type[LaneBase], ...] = (
    OsmObject,
    OsmCountry,
    OsmTagChange,
    OsmHistoryChange,
    OsmHistoryCut,
    OsmAdmin1Split,
    OsmSearchIndex,
    OsmViewIndex,
    OsmViewCell,
    OsmDiffRun,
)


def table_width() -> int:
    """Columns in ``osm_objects``, measured from the table rather than counted by eye."""
    return len(osm_objects_table.columns)
