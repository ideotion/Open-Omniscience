"""The lane tables — SQLite, in the lane's OWN database file, on their OWN metadata.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1007 = b: **SQLite for everything**; DuckDB is not used for the lane tables (the
columnar store's future is Q1009, still PENDING on a ⛔ question, and 0.5's
business either way).

WHY A SEPARATE ``DeclarativeBase``, AND WHY IT IS NOT A STYLE CHOICE. The corpus
has exactly one declarative base (``src/database/models.py:Base``) and
``migrations/env.py`` sets ``target_metadata = Base.metadata``. Hanging the lane
tables off that base would do two wrong things at once, both silently: ``alembic
check`` would demand migrations for tables that do not belong to the corpus schema,
and ``init_db``'s ``Base.metadata.create_all(engine)`` would CREATE THEM IN
``corpus.db`` — the exact bloat Q719 = a exists to prevent, arriving through the
boot path rather than through a lane. ``LaneBase`` keeps the two schemas unable to
touch each other by construction.

HOW A LANE FILE GETS ITS SCHEMA. ``store.create_schema`` calls
``LaneBase.metadata.create_all`` against the lane engine. There is deliberately NO
alembic history for lane files in 0.4: these tables are born here, so there is
nothing to migrate, and inventing a second migration root before there is a second
version is how a project acquires two of something it needs one of. ``schema_version``
on ``LaneMeta`` is the seam a 0.5 migration reads; it is written at creation and
never guessed.

CROSS-FILE LINKS ARE IDS, NOT FOREIGN KEYS — AND SQLITE CANNOT MAKE THEM ANYTHING
ELSE. A revision that became an Article carries ``article_id``, which names a row in
``corpus.db``. SQLite has no cross-database foreign keys (``PRAGMA foreign_keys``
constrains one schema), so that column is a plain integer with NO referential
integrity behind it, and this docstring says so rather than leaving a reader to
infer it from the absence of a ``ForeignKey``. ``integrity.check_article_links``
is the check that stands in for the constraint; it reports dangling links as a
COUNT and a sample, and it can only ever be a point-in-time reading.

POSTGRES COLUMN LIMITS (the Q1140 NOTE, a *design note*: "as PostgreSQL has column
limitations SQLite doesn't have, we should anticipate this in our current work").
The widest table here carries **15** columns (``versioned_revisions``; measured
from ``__table__.columns``, not counted by eye). Nothing in this schema widens with
the data — a lane that tracks a million pages grows ROWS — so the parity aspiration
costs this package nothing, and the guard in ``tests/test_versioned_models.py``
re-measures it rather than trusting this sentence, so a later slice that widens a
table has to argue the ceiling up.

NO SCORES. There is no column whose name contains ``score``/``rating``/``ranking``/
``grade`` anywhere in this schema, and the same test walks the column names to keep
it that way. The lane stores what a source SAID and when; it forms no opinion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """Timezone-aware UTC now.

    A naive ``datetime.utcnow()`` is what makes two timestamps in one row
    incomparable later; every column here is tz-aware from birth.
    """
    return datetime.now(UTC)


class LaneCompressedText(TypeDecorator):
    """Compressed text, through the app's ONE compressor.

    THIS IS NOT A SECOND MECHANISM, and the distinction is worth stating because
    the ledger's standing rule is that two implementations of one thing drift.
    ``src.database.models.CompressedText`` is the corpus's decorator and this is
    the lane's; BOTH delegate to the same ``src.utils.compression.database_compressor``
    singleton, so the bytes on disk are produced by one implementation with one
    algorithm choice. What is duplicated is six lines of SQLAlchemy plumbing, and
    ``tests/test_versioned_models.py`` asserts the two decorators hold the SAME
    compressor object so a future divergence reddens by name.

    WHY NOT JUST IMPORT THE CORPUS DECORATOR: ``src/database/models.py`` imports
    ``src.database.session`` at module scope (models.py:69), which builds the corpus
    engine. Importing it here would make the lane SCHEMA unimportable without the
    corpus engine — and the whole point of ``LaneBase`` is that the two schemas do
    not depend on each other.
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from src.utils.compression import database_compressor

        self.compressor = database_compressor

    def process_bind_param(self, value: str | bytes | None, dialect: Any) -> bytes | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return self.compressor.compress_text_for_storage(value)

    def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return self.compressor.decompress_text_from_storage(value)

    def copy(self, *args: Any, **kwargs: Any) -> LaneCompressedText:
        return LaneCompressedText(*args, **kwargs)


class LaneUTCDateTime(TypeDecorator):
    """A timestamp that comes BACK tz-aware. ``DateTime(timezone=True)`` does not.

    MEASURED, not assumed: SQLite has no timezone-aware storage type, so SQLAlchemy's
    ``timezone=True`` flag is a DECLARATION OF INTENT on this backend and nothing
    more — a value written as UTC-aware is handed back NAIVE, and the first
    comparison against an aware value raises ``TypeError: can't compare
    offset-naive and offset-aware datetimes``. That is the good case. The bad one is
    a comparison between two naive values that came from different zones, which does
    not raise and silently answers wrongly; a point-in-time read is exactly that kind
    of comparison, which is why this decorator exists rather than a fix at each site.

    IT REFUSES A NAIVE VALUE ON WRITE, by name. The tempting alternative — assume UTC
    — would put the guess in the one place nobody can later audit, and "the caller
    had a naive datetime" and "the caller had a UTC datetime" are different facts
    about someone else's data. Everything in this package produces aware values
    (``_utcnow``), so the refusal fires only on a genuine caller bug.

    WHAT THE CALLER ACTUALLY CATCHES — measured, because the answer is not the one
    the ``raise`` line suggests. A bind processor runs inside the flush, so the
    ``ValueError`` below reaches the caller WRAPPED in
    ``sqlalchemy.exc.StatementError`` (message preserved, original on ``.orig``).
    ``except ValueError`` therefore does NOT catch it. That is written down because
    a reader of this method would reasonably assume otherwise, and
    ``tests/test_versioned_revisions.py`` asserts the wrapped shape rather than the
    shape this file appears to promise.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "a versioned-lane timestamp must be timezone-aware; got a naive "
                f"{value!r}. Build it with datetime.now(UTC) or attach the source's "
                "own offset — this package will not guess a zone."
            )
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def copy(self, *args: Any, **kwargs: Any) -> LaneUTCDateTime:
        return LaneUTCDateTime(*args, **kwargs)


class LaneBase(DeclarativeBase):
    """The lane schema's own root. Never ``src.database.models.Base`` — see module docstring."""


class LaneMeta(LaneBase):
    """One row. What this file IS, written when the file is created.

    It exists so a lane file found on disk can answer, without the app's
    cooperation, which kind it holds and which schema version wrote it. A file
    that cannot answer is refused rather than opened hopefully — a wiki lane
    opened as a law lane would write rows that read as real.
    """

    __tablename__ = "lane_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)


class VersionedEntity(LaneBase):
    """The tracked thing: identity ``(kind, external_id)`` + QID.

    ``external_id`` is the SOURCE's own identifier, verbatim and opaque to this
    package — a MediaWiki ``(wiki, pageid)`` pair rendered by the adapter, a law
    document's citation, an OSM object id. Opaque is the point: the substrate never
    parses it, so an adapter can change what it means without a migration here.

    ``qid`` is the Wikidata item where one is known, and is deliberately NOT part of
    the identity: a page's QID can arrive late, change, or be absent, and an identity
    that can change is not an identity. It is an index, so the entity graph can be
    joined across lanes by concept later without the join key being load-bearing now.
    """

    __tablename__ = "versioned_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    qid: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(512))
    #: The source's own language, where it has one (a wiki edition; a law's language
    #: of publication). Raw from the source, normalised on read, per the house rule.
    language: Mapped[str | None] = mapped_column(String(16))
    #: ISO 3166-1 **alpha-3**, from birth (Q312 = a, 0.4). Never alpha-2: a column
    #: born during the alpha-3 cycle that stored alpha-2 would be a migration this
    #: project has already ruled it does not want.
    country_alpha3: Mapped[str | None] = mapped_column(String(3))
    #: "pin this page to HOT" (Q716 = a). The substrate owns the FLAG; what HOT
    #: MEANS — tiers, budgets, which text is kept — is S04-09's, and nothing here
    #: reads this column except to report it.
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: An entity the operator stopped following. Kept, not deleted: its revisions are
    #: evidence, and deleting them to express "stop watching" destroys the record.
    watching: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        LaneUTCDateTime, nullable=False, default=_utcnow
    )
    #: When this app last ASKED about the entity — not when the source last changed.
    #: Two different facts; one column each, because "we have not looked" and "nothing
    #: happened" are the pair every freshness reading gets wrong.
    last_checked_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)

    __table_args__ = (
        UniqueConstraint("external_id", name="uq_versioned_entity_external_id"),
        Index("ix_versioned_entity_qid", "qid"),
        Index("ix_versioned_entity_watching", "watching", "last_checked_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<VersionedEntity({self.external_id!r} qid={self.qid})>"


class VersionedBaseline(LaneBase):
    """The IMMUTABLE baseline: what the source said the first time we read it in full.

    One per entity, written once. Nothing in this package updates a baseline row —
    a re-read produces a REVISION, which is what makes "what changed since we started
    watching" answerable at all. ``store.py`` refuses a second baseline by name
    rather than overwriting, because an overwritten baseline is a rewritten past.
    """

    __tablename__ = "versioned_baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("versioned_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: The source's own name for this version (a MediaWiki revid, a law's version
    #: stamp). Opaque, like ``external_id``.
    revision_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    #: When the SOURCE says this version came into being, where it says so.
    revised_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Compressed transparently by ``LaneCompressedText`` — the caller reads and
    #: writes plain ``str``. ``byte_size`` below is the UNCOMPRESSED length, which
    #: is what a diff and a "how much text is this" figure are about; the disk
    #: figure the budget surface shows comes from the FILE, never from summing this.
    content: Mapped[str | None] = mapped_column(LaneCompressedText)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("entity_id", name="uq_versioned_baseline_entity"),)


class VersionedRevision(LaneBase):
    """An INGESTED version: the text we hold, and its diff against the PREVIOUS one.

    "Previous ingested" is the load-bearing phrase (Q711's shape, one lane up). A
    diff against the source's own predecessor would describe an edit this app never
    saw; a diff against the previous version WE HOLD describes the change the
    reader's corpus actually underwent, which is the only one the evidence supports.
    ``diff_from_ref`` names which version that was, so the claim is checkable.
    """

    __tablename__ = "versioned_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("versioned_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    revised_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str | None] = mapped_column(LaneCompressedText)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: The version this revision's diff was taken against. NULL means "this is the
    #: first ingested version after the baseline" — a fact, not a missing value, and
    #: the renderer says so rather than printing an empty diff.
    diff_from_ref: Mapped[str | None] = mapped_column(String(128))
    #: Counts only: added lines, removed lines, and the byte delta. No verdict about
    #: whether a change is large, important or suspicious — that is a reading, and
    #: this table stores observations.
    diff_added: Mapped[int | None] = mapped_column(Integer)
    diff_removed: Mapped[int | None] = mapped_column(Integer)
    diff_byte_delta: Mapped[int | None] = mapped_column(Integer)
    #: The unified diff itself, when one was computed. Absent when the previous
    #: version's text is no longer held — which the reader is told rather than
    #: shown as an empty diff, because "nothing changed" and "we cannot say what
    #: changed" are opposite readings of the same blank panel.
    diff_text: Mapped[str | None] = mapped_column(LaneCompressedText)
    #: HOW the diff above was obtained, as a literal token — ``unified`` |
    #: ``no-previous-text`` | ``too-large``. It exists because the three produce
    #: the same empty panel and mean different things, and because ``diff_added``/
    #: ``diff_removed`` are deliberately NULL in the last two: a line count from a
    #: cheaper comparison would be a different measurement wearing the same field
    #: name. ``diff_byte_delta`` stays exact in all three — it needs no diff.
    diff_method: Mapped[str | None] = mapped_column(String(32))
    #: The corpus Article this version became, if it became one. A CROSS-FILE id
    #: with no referential integrity behind it (see the module docstring).
    article_id: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("entity_id", "revision_ref", name="uq_versioned_revision_entity_ref"),
        # The point-in-time read is "the newest revision of this entity at or before
        # T", and the timeline view is "this entity's revisions, newest first". One
        # index serves both.
        Index("ix_versioned_revision_entity_time", "entity_id", "revised_at"),
        Index("ix_versioned_revision_article", "article_id"),
    )


class VersionedChange(LaneBase):
    """The change FEED: metadata for every change the source reported, ingested or not.

    This is the table that makes coverage honest. A lane under a budget ingests a
    fraction of what it is told about, and a store holding only the ingested
    fraction cannot distinguish "nothing changed" from "we could not afford to look"
    — so every change the feed reports gets a row here whether or not any text was
    fetched, and ``ingested_revision_id`` is NULL for the ones that were only
    counted.
    """

    __tablename__ = "versioned_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("versioned_entities.id", ondelete="CASCADE")
    )
    #: The source's own identifier for the thing that changed, stored EVEN WHEN
    #: ``entity_id`` is NULL. Two reasons, both about not losing evidence already in
    #: hand: a change reported before the operator started watching a page can be
    #: attached to that page when they do (without it the page's early history is
    #: permanently unattributable, although this lane recorded it), and "how much am
    #: I not following" can name what it counted instead of returning a bare number.
    #: Nullable because a feed may report an event with nothing to point at.
    external_id: Mapped[str | None] = mapped_column(String(512))
    #: The feed's own id for this change. UNIQUE per feed: a feed replayed after a
    #: reconnect must not double-count, and dedup on the source's own id is the only
    #: thing that survives a cursor going backwards.
    change_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    feed: Mapped[str] = mapped_column(String(64), nullable=False)
    #: edit | create | delete | move. A closed vocabulary; an unknown value from a
    #: source is stored VERBATIM and reported as unknown rather than mapped onto the
    #: nearest member, because mapping invents a fact about someone else's data.
    change_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    #: The cursor token this change was delivered at. Kept so a gap's boundaries can
    #: be named in the feed's own vocabulary rather than in ours.
    cursor_token: Mapped[str | None] = mapped_column(String(256))
    byte_delta: Mapped[int | None] = mapped_column(Integer)
    ingested_revision_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("versioned_revisions.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("feed", "change_ref", name="uq_versioned_change_feed_ref"),
        Index("ix_versioned_change_entity_time", "entity_id", "occurred_at"),
        Index("ix_versioned_change_feed_time", "feed", "recorded_at"),
        Index("ix_versioned_change_external", "external_id"),
    )


class VersionedCursor(LaneBase):
    """Where a feed got to. One row per feed name.

    ``token`` is the feed's own resume token, opaque. ``contiguous_through`` is the
    point up to which this app believes it has seen EVERY change — which is a
    different and weaker claim than "the last token we were handed", and the two
    are separate columns because conflating them is how a gap disappears.
    """

    __tablename__ = "versioned_cursors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed: Mapped[str] = mapped_column(String(64), nullable=False)
    token: Mapped[str | None] = mapped_column(String(256))
    updated_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    contiguous_through: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)

    __table_args__ = (UniqueConstraint("feed", name="uq_versioned_cursor_feed"),)


class VersionedGap(LaneBase):
    """A stretch of a feed this app knows it did not see.

    A gap is PUBLISHED, never inferred away. ``reason`` is a closed token
    (``retention`` | ``disconnect`` | ``budget`` | ``refused``) so a reader can tell
    "the source no longer had it" from "we chose not to spend on it" — opposite
    facts that a single "missing" would merge.
    """

    __tablename__ = "versioned_gaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    from_token: Mapped[str | None] = mapped_column(String(256))
    to_token: Mapped[str | None] = mapped_column(String(256))
    from_time: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    to_time: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Set when a later pass filled the gap from another route (a per-entity
    #: re-read, an edition-level list call). Never set by guessing.
    closed_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)

    __table_args__ = (Index("ix_versioned_gap_feed_time", "feed", "detected_at"),)


class VersionedSizeSample(LaneBase):
    """The lane's OWN measured bytes over time. The growth arithmetic's only input.

    Q1006 asks Settings -> Storage for "the honest arithmetic (at your current rate
    this lane grows ~2 GB/month)". A rate needs two readings of the same quantity at
    two times, and the only quantity that is honest here is the FILE's size on disk,
    measured. Nothing extrapolates from a row count, a catalogue estimate or a
    per-item average: those are projections, and the brief's S4 says the growth line
    is absent-with-a-reason when unmeasured, never a projection.

    Samples live in the lane's own file, so a lane with no file has no samples and
    reports ABSENT — which is the correct answer rather than a zero.
    """

    __tablename__ = "versioned_size_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    measured_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    #: The lane file's size on disk at ``measured_at``, including its ``-wal`` when
    #: one exists — because that is what the operator's disk is holding.
    file_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    #: How the figure was obtained, so a reader never has to guess which files were
    #: counted. A literal token, not prose.
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="stat+wal")

    __table_args__ = (Index("ix_versioned_size_measured", "measured_at"),)


class VersionedDisclosure(LaneBase):
    """What this lane told the operator, and when they agreed to it.

    Disclosure is per KIND (the intake's design, §11), and it is stored rather than
    only rendered so that "the reader was told X" survives a locale change, a
    reinstall of the UI and a later rewording. ``text_key`` is the i18n key, never
    the rendered sentence: storing the English would make the record a claim about
    a language the operator may not read.
    """

    __tablename__ = "versioned_disclosures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text_key: Mapped[str] = mapped_column(String(256), nullable=False)
    shown_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    #: Free-form note from the caller (which surface showed it). Text, not prose for
    #: a reader: it is forensic.
    note: Mapped[str | None] = mapped_column(Text)


#: Every model in this schema, for the guards and for ``create_all``'s twin check.
LANE_MODELS: tuple[type[LaneBase], ...] = (
    LaneMeta,
    VersionedEntity,
    VersionedBaseline,
    VersionedRevision,
    VersionedChange,
    VersionedCursor,
    VersionedGap,
    VersionedSizeSample,
    VersionedDisclosure,
)
