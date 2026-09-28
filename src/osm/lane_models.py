"""The OSM lane's own tables in ``osm.db`` (Q811 = b, Q810, Q813, Q825).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q811 = b: «SQLite for everything». Q825 = a: «Same answers as the Wikipedia lane (Q719, Q720)»
-- ``osm.db`` beside the corpus, linked by ids, encrypted with the same passphrase. Both are
the substrate's, not this module's: these tables live on ``LaneBase`` and reach ``osm.db``
ONLY through ``src.versioned.store.create_schema`` (``_lane_specific_models("osm")``), which
opens the file through the ONE keyed factory. A lane file gets its own tables and no other
lane's.

THREE TABLES.

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
  timestamp and the object's ``version``. Defined here and EMPTY in 0.5; the daily apply that
  fills it is 0.6 (S06-01).

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


class OsmTagChange(LaneBase):
    """Q813 = a: one tag-level change. The MODEL only; 0.6's daily apply fills it."""

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


OSM_LANE_MODELS: tuple[type[LaneBase], ...] = (OsmObject, OsmCountry, OsmTagChange)


def table_width() -> int:
    """Columns in ``osm_objects``, measured from the table rather than counted by eye."""
    return len(osm_objects_table.columns)
