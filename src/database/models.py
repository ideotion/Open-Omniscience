"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""
Database Models for Open Omniscience

This module defines the SQLAlchemy models for the database. **SQLite is the
supported backend.** A PostgreSQL URL is honoured at the engine layer, but
full-text search (FTS5), the single-writer gate, and maintenance/PRAGMA tuning
are SQLite-only -- search would error on PostgreSQL because the FTS table is
never created there (a PostgreSQL FTS path is possible future server work, not a
supported deployment today).
Includes tables for sources and articles, with relationships and indexes.

Author: Ideotion
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, backref, mapped_column, relationship

# Engine, session lifecycle, and the FastAPI dependency live in session.py and
# have NO import-time side effects (no create_all, no monitoring thread). They are
# re-exported here because much existing code does
# `from src.database.models import get_session` (and Session/SessionLocal) etc.
# noqa: F401 on each -- these are intentional backward-compat re-exports, not
# unused imports; without it `ruff --fix` strips them and breaks importers.
from src.database.session import (  # noqa: E402
    Session,  # noqa: F401
    SessionLocal,  # noqa: F401
    engine,
    get_session,
    init_db,
)

# =============================================================================
# Compressed Text Type for SQLAlchemy
# =============================================================================


class CompressedText(TypeDecorator):
    """
    SQLAlchemy type decorator for storing compressed text.

    This type automatically compresses text data before storing it in the database
    and decompresses it when retrieving. This is particularly useful for large text
    fields like article content, where compression can significantly reduce storage
    requirements.

    Usage:
        class Article(Base):
            content: Mapped[str | None] = mapped_column(CompressedText)
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the CompressedText type.

        Args:
            *args: Positional arguments passed to TypeDecorator.
            **kwargs: Keyword arguments passed to TypeDecorator.
        """
        super().__init__(*args, **kwargs)
        # Import here to avoid circular imports
        from src.utils.compression import database_compressor

        self.compressor = database_compressor

    def process_bind_param(self, value: str | bytes | None, dialect: Any) -> bytes | None:
        """
        Process the value before storing in the database.

        Args:
            value: The value to compress.
            dialect: The database dialect.

        Returns:
            Compressed value as bytes, or None.
        """
        if value is None:
            return None

        if isinstance(value, bytes):
            value = value.decode("utf-8")

        # Compress the text
        return self.compressor.compress_text_for_storage(value)

    def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
        """
        Process the value after retrieving from the database.

        Args:
            value: The compressed value from the database.
            dialect: The database dialect.

        Returns:
            Decompressed value as string, or None.
        """
        if value is None:
            return None

        # Decompress the text
        return self.compressor.decompress_text_from_storage(value)

    def copy(self, *args: Any, **kwargs: Any) -> "CompressedText":
        """Create a copy of this type."""
        return CompressedText(*args, **kwargs)


# =============================================================================
# Compressed JSON Type for SQLAlchemy
# =============================================================================


class CompressedJSON(TypeDecorator):
    """
    SQLAlchemy type decorator for storing compressed JSON data.

    This type automatically serializes Python objects to JSON, compresses them,
    and stores them in the database. When retrieving, it decompresses and deserializes
    the JSON back to Python objects.

    Usage:
        class Article(Base):
            metadata: Mapped[Any | None] = mapped_column(CompressedJSON)
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the CompressedJSON type."""
        super().__init__(*args, **kwargs)
        import json

        from src.utils.compression import database_compressor

        self.json = json
        self.compressor = database_compressor

    def process_bind_param(self, value: Any, dialect: Any) -> bytes | None:
        """
        Process the value before storing in the database.

        Args:
            value: The Python object to serialize and compress.
            dialect: The database dialect.

        Returns:
            Compressed JSON as bytes, or None.
        """
        if value is None:
            return None

        # Serialize to JSON
        json_str = self.json.dumps(value, ensure_ascii=False, default=str)

        # Compress the JSON string
        return self.compressor.compress_text_for_storage(json_str)

    def process_result_value(self, value: bytes | None, dialect: Any) -> Any:
        """
        Process the value after retrieving from the database.

        Args:
            value: The compressed JSON from the database.
            dialect: The database dialect.

        Returns:
            Deserialized Python object, or None.
        """
        if value is None:
            return None

        # Decompress the JSON string
        json_str = self.compressor.decompress_text_from_storage(value)

        # Deserialize from JSON
        return self.json.loads(json_str)

    def copy(self, *args: Any, **kwargs: Any) -> "CompressedJSON":
        """Create a copy of this type."""
        return CompressedJSON(*args, **kwargs)


# =============================================================================
# Database Configuration Utilities
# =============================================================================

# Base class for declarative models (SQLAlchemy 2.0 style: a real class, so
# mypy can type every model -- the dynamic declarative_base() was opaque to it).
class Base(DeclarativeBase):
    pass


# Association table for many-to-many relationship between Source and SourceGroup
source_group_association = Table(
    "source_group_association",
    Base.metadata,
    Column("source_id", Integer, ForeignKey("sources.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("source_groups.id"), primary_key=True),
    Column("added_at", DateTime, default=lambda: datetime.now(UTC)),
    # Indexes for performance
    Index("idx_source_group_source_id", "source_id"),
    Index("idx_source_group_group_id", "group_id"),
)


class SourceGroup(Base):
    """
    Represents a group of sources for organizational purposes.

    Groups allow users to categorize and manage sources in bulk.
    Sources can belong to multiple groups.

    Attributes:
        id: Primary key.
        name: Name of the group (e.g., "Technology News", "Financial Sources").
        description: Description of the group's purpose.
        color: Color code for UI display (e.g., "#FF5733").
        is_tag_based: Whether this group is automatically populated based on source tags.
        tag_pattern: Tag pattern for auto-population (e.g., "technology,tech").
        priority: Default priority for sources in this group.
        rate_limit_ms: Default rate limit for sources in this group.
        enabled: Whether sources in this group are enabled by default.
        created_at: Timestamp when the group was created.
        updated_at: Timestamp when the group was last updated.
        sources: Relationship to Source model (many-to-many).
    """

    __tablename__ = "source_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(20), default="#666666")
    is_tag_based: Mapped[bool | None] = mapped_column(Boolean, default=False)
    tag_pattern: Mapped[str | None] = mapped_column(String(500))  # Comma-separated tags for auto-population
    priority: Mapped[int | None] = mapped_column(Integer, default=2)
    rate_limit_ms: Mapped[int | None] = mapped_column(Integer, default=2000)
    enabled: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Many-to-many relationship with sources
    sources = relationship(
        "Source", secondary=source_group_association, back_populates="groups", lazy="dynamic"
    )

    def __repr__(self):
        return f"<SourceGroup(name='{self.name}', id={self.id})>"


class SourceMetadata(Base):
    """
    Additional metadata for sources.

    This table stores extended information about sources that doesn't
    fit in the main Source table, such as geographic and language data,
    robots.txt information, and other metadata.

    Attributes:
        id: Primary key.
        source_id: Foreign key to Source (one-to-one relationship).
        language: Primary language of the source (e.g., "en", "fr", "en-US").
        country: Country code where the source is based (ISO 3166-1 alpha-2).
        region: Region or state (for country-specific sources).
        city: City where the source is based.
        timezone: Timezone of the source (e.g., "America/New_York").
        robots_txt_url: URL to the source's robots.txt file.
        robots_allowed: Whether scraping is allowed according to robots.txt.
        crawl_delay: Crawl delay specified in robots.txt (in seconds).
        sitemap_url: URL to the source's sitemap.xml.
        favicon_url: URL to the source's favicon.
        logo_url: URL to the source's logo.
        contact_email: Contact email for the source.
        social_twitter: Twitter handle of the source.
        social_facebook: Facebook page URL.
        social_linkedin: LinkedIn page URL.
        alexa_rank: Alexa rank of the domain (if available).
        last_checked: Timestamp when metadata was last verified.
        notes: Additional notes about the source.
        source: Relationship to Source model.
    """

    __tablename__ = "source_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False, unique=True)

    # Geographic and language metadata
    language: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    timezone: Mapped[str | None] = mapped_column(String(50))

    # Robots.txt and crawling metadata
    robots_txt_url: Mapped[str | None] = mapped_column(String(500))
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean, default=True)
    crawl_delay: Mapped[int | None] = mapped_column(Integer)  # In seconds
    sitemap_url: Mapped[str | None] = mapped_column(String(500))

    # Branding and contact
    favicon_url: Mapped[str | None] = mapped_column(String(500))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    contact_email: Mapped[str | None] = mapped_column(String(255))

    # Social media
    social_twitter: Mapped[str | None] = mapped_column(String(255))
    social_facebook: Mapped[str | None] = mapped_column(String(500))
    social_linkedin: Mapped[str | None] = mapped_column(String(500))

    # Popularity and ranking
    alexa_rank: Mapped[int | None] = mapped_column(Integer)

    # Timestamps and notes
    last_checked: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    # Relationship to source
    source = relationship("Source", back_populates="source_metadata", uselist=False)

    # Indexes for performance
    __table_args__ = (
        Index("idx_metadata_source_id", "source_id", unique=True),
        Index("idx_metadata_country", "country"),
        Index("idx_metadata_language", "language"),
        Index("idx_metadata_robots_allowed", "robots_allowed"),
    )

    def __repr__(self):
        return f"<SourceMetadata(source_id={self.source_id}, language='{self.language}', country='{self.country}')>"


class Source(Base):
    """
    Represents a news source.

    Attributes:
        id: Primary key.
        name: Name of the source (e.g., "BBC News").
        domain: Domain of the source (e.g., "bbc.com").
        rss_url: URL of the RSS feed, if available.
        rate_limit_ms: Delay between requests in milliseconds.
        enabled: Whether the source is active for scraping.
        priority: Priority level (1 = high, 3 = low).
        tags: Comma-separated list of tags.
        reliability_score: Reliability score (1-10, 10 = most reliable).
        language: Primary language of the source (ISO 639-1 code).
        region: Geographic region (e.g., "global", "europe", "asia").
        country: Country code (ISO 3166-1 alpha-2).
        source_type: Type of source (e.g., "news", "financial", "scientific").
        update_frequency: How often source updates (in minutes).
        cacheability: Whether responses can be cached.
        articles: Relationship to Article model.
        status: Qualification lifecycle state -- see the class-level note below.
    """

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    rss_url: Mapped[str | None] = mapped_column(String(500))
    rate_limit_ms: Mapped[int | None] = mapped_column(Integer, default=2000)
    enabled: Mapped[bool | None] = mapped_column(Boolean, default=True)
    priority: Mapped[int | None] = mapped_column(Integer, default=2)
    tags: Mapped[str | None] = mapped_column(String(500))  # Comma-separated tags

    # Enhanced metadata fields
    # No default: an unrated source has NO reliability figure (the old
    # default=5 asserted "medium" for every unrated source — fabricated data;
    # audit 06 remediation). Operator/catalog-set metadata only, never computed.
    reliability_score: Mapped[int | None] = mapped_column(Integer)  # 1-10 scale, operator-set
    # No default: an unknown language is honestly NULL, never silently "en"
    # (audit 06 remediation; the keyword export's language_mismatch evidence
    # exposed exactly this class of attribution noise).
    language: Mapped[str | None] = mapped_column(String(10))  # ISO 639-1 code
    region: Mapped[str | None] = mapped_column(String(50), default="global")
    # No default: a country is set from the catalog, the ccTLD, or the user —
    # never assumed. (The old default="US" fabricated a US bias; 0.09 fix.)
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2, lowercase
    source_type: Mapped[str | None] = mapped_column(String(50), default="news")  # news, financial, scientific, etc.
    update_frequency: Mapped[int | None] = mapped_column(Integer, default=60)  # minutes
    cacheability: Mapped[bool | None] = mapped_column(Boolean, default=True)
    # Maintained per-source article counter (S6, 2026-07-14). Nullable: NULL = "never
    # reconciled" -> read surfaces fall back to a live COUNT(*) on the indexed
    # Article.source_id (idx_article_source_id), so the count is never WRONG, only
    # sometimes computed live. reconcile_source_counters() recomputes it (a whole-table
    # GROUP BY -- cheap, sources are few) and stamps counter_reconciled_at so the honesty
    # envelope discloses exact (fresh) vs estimated (stale). NOT maintained in
    # index_article (which RE-indexes existing articles -> incrementing there would
    # double-count); membership changes on create/delete/reconcile only.
    article_count: Mapped[int | None] = mapped_column(Integer)
    counter_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Qualification lifecycle (0.3 CLOSE GATE ruling, 2026-07-19/20): the ADMISSION GATE
    # -- only a QUALIFIED source feeds regular collection (select_sources). ``status`` is
    # one of exactly unqualified|qualified|disqualified (never a "candidate"/"trial"
    # status -- trial is the PROCESS, not a persisted state). NOT NULL DEFAULT
    # 'unqualified' so every self-healed/legacy row is honestly gated, never silently
    # admitted. ``qualified_at`` + ``qualification_criteria_version`` are the STAMP
    # ("qualified by Open Omniscience on DATE", judged by criteria version N) -- both are
    # cleared (NULL) whenever the source is not currently qualified, so a stale stamp
    # never survives a later disqualification. This states WHAT was checked --
    # extraction validity, via src.analytics.source_audit's reused criteria -- NEVER a
    # quality score (see src.catalog.qualification; the no-score/ranking/rating/grade
    # invariant applies here too). The per-attempt HISTORY (append-only, the vintage
    # convention -- never overwritten) lives in SourceQualificationAttempt, not here.
    # server_default="unqualified" (same precedent as mention_count/article_count
    # above): a NOT NULL column needs a DB-level default too, not just the Python-side
    # ORM default, or any raw-SQL INSERT that omits the column (e.g. backup/merge.py's
    # tracked-column copy) hits a NOT NULL constraint violation.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unqualified", server_default="unqualified"
    )
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime)
    qualification_criteria_version: Mapped[str | None] = mapped_column(String(40))

    # Relationship to articles
    articles = relationship("Article", back_populates="source", cascade="all, delete-orphan")

    # Many-to-many relationship with groups
    groups = relationship(
        "SourceGroup", secondary=source_group_association, back_populates="sources", lazy="dynamic"
    )

    # One-to-one relationship with metadata
    source_metadata = relationship(
        "SourceMetadata", back_populates="source", uselist=False, cascade="all, delete-orphan"
    )

    # Indexes for performance
    __table_args__ = (
        Index("idx_source_domain", "domain", unique=True),
        Index("idx_source_enabled", "enabled"),
        Index("idx_source_priority", "priority"),
        Index("idx_source_reliability", "reliability_score"),
        Index("idx_source_language", "language"),
        Index("idx_source_region", "region"),
        Index("idx_source_country", "country"),
        Index("idx_source_type", "source_type"),
        Index("idx_source_status", "status"),
    )

    def __repr__(self):
        return f"<Source(name='{self.name}', domain='{self.domain}')>"


class FeedFetchState(Base):
    """Per-feed HTTP conditional-GET validators (ETag / Last-Modified).

    Lets an unchanged RSS/Atom feed be answered with a cheap ``304 Not Modified``
    instead of being re-downloaded and re-parsed every collection pass (field log
    2026-06-13: ~93% of feed items were duplicates at 1-minute intervals — the
    feeds had not changed). One row per source feed.

    A SEPARATE table rather than columns on ``sources`` on purpose: ``create_all``
    materialises a missing TABLE on every existing database at boot, so there is
    no ADD COLUMN migration to run and no 'no such column' risk in the collection
    hot path (the project self-heals indexes but not columns). Validators are
    opaque HTTP tokens, stored verbatim and sent back verbatim — never parsed.

    De-churn backoff (field log finding F, 2026-06-13): some servers IGNORE the
    conditional headers and return a full 200 every pass even when nothing
    changed (~93% duplicate rate at 1-minute intervals). ``consecutive_unchanged``
    counts passes that fetched a 200 yet yielded ZERO new articles, and
    ``skip_until`` records a CAPPED, TEMPORARY, SELF-RESETTING UTC deadline before
    which the collect loop skips re-checking this feed. This is a transport
    de-churn, NEVER an exclusion: the cap guarantees the feed is always re-checked
    within :data:`src.ingest.pipeline.BACKOFF_CAP_S` (~6 h), and ANY new article,
    a 304 (the server says unchanged honestly), or a fetch error resets the
    counter and clears ``skip_until``. Stored (not hidden) so the task manager /
    diagnostics can surface "backed off until T".
    """

    __tablename__ = "feed_fetch_state"

    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    etag: Mapped[str | None] = mapped_column(String(512))  # opaque If-None-Match token
    last_modified: Mapped[str | None] = mapped_column(String(128))  # opaque If-Modified-Since
    last_status: Mapped[int | None] = mapped_column(Integer)  # last feed HTTP status seen
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    # De-churn backoff: consecutive 200-but-no-new-articles passes, and the
    # capped UTC deadline before which the feed is skipped (NULL = no backoff).
    consecutive_unchanged: Mapped[int | None] = mapped_column(Integer)
    skip_until: Mapped[datetime | None] = mapped_column(DateTime)

    def __repr__(self):
        return f"<FeedFetchState(source_id={self.source_id}, status={self.last_status})>"


class SourceQualificationAttempt(Base):
    """One row per qualification/re-qualification ATTEMPT (append-only -- the vintage
    convention, matching StatFigure/law-document versioning: a re-attempt is a NEW row,
    never an overwrite of the last one). This is the system of record the re-
    qualification ladder reads: the most recent row's ``attempted_at`` is "last attempt",
    and the run of trailing ``disqualified`` verdicts (newest-first) is the ladder
    position (see src.catalog.qualification.consecutive_disqualifications).

    A SEPARATE table rather than columns on ``sources``, for the same reason as
    FeedFetchState: create_all materialises a missing table on every existing database
    at boot, so a brand-new table needs no ALTER-COLUMN self-heal (the qualification
    STAMP columns on Source do -- see ensure_source_qualification_columns).

    ``verdict`` is categorical (qualified|disqualified) -- never a score. ``criteria_version``
    records which version of src.analytics.source_audit's criteria judged this attempt,
    so a later criteria change is visible in the history rather than silently reinterpreted.
    """

    __tablename__ = "source_qualification_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    attempted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)  # qualified | disqualified
    criteria_version: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        Index("idx_qual_attempt_source_time", "source_id", "attempted_at"),
    )

    def __repr__(self):
        return (
            f"<SourceQualificationAttempt(source_id={self.source_id}, "
            f"verdict={self.verdict!r}, attempted_at={self.attempted_at})>"
        )


class Article(Base):
    """
    Represents a scraped article.

    Attributes:
        id: Primary key.
        url: Original URL of the article.
        canonical_url: Canonicalized URL (for duplicate detection).
        source_id: Foreign key to Source.
        title: Title of the article.
        content: Full text content of the article.
        published_at: Publication date/time (ISO format).
        language: Language code (e.g., "en", "fr").
        hash: SHA-256 hash of the content (for duplicate detection).
        created_at: Timestamp when the article was ingested.
        region: Geographic region detected from content.
        country: Country code detected from content.
        author: Author of the article.
        source: Relationship to Source model.
    """

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Compressed version of content for storage optimization
    compressed_content: Mapped[bytes | None] = mapped_column(LargeBinary)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    language: Mapped[str | None] = mapped_column(String(10))  # AUTHORITATIVE (source/extractor); NULL when untagged
    # SECONDARY / DEDUCED language (field §2.6, maintainer ruling Q3): set ONLY when
    # `language` is absent, by offline confidence-gated detection (src/analytics/
    # langdetect.py). Never overwrites the authoritative `language`; used as the
    # extraction + keyword-analytic fallback so a foreign untagged article gets the
    # right stoplist. NULL when truly unknown (the detector never guesses).
    detected_language: Mapped[str | None] = mapped_column(String(10))
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)  # SHA-256 hash length is 64
    # K1/K2 identity seams (data-architecture Slice 5). Additive, never reformat `hash`:
    #   * content_multihash -- the SELF-DESCRIBING content hash ("sha2-256:<hex>"),
    #     alongside the bare-hex dedup `hash`, so a future hash-algorithm change is
    #     unambiguous per-article (src/utils/url_utils.content_multihash).
    #   * canon_version -- which canonicalization produced `canonical_url`
    #     (src/utils/url_utils.CANON_VERSION), so a corpus spanning a canonicaliser
    #     change knows which rule made each canonical_url.
    # Both are stamped FORWARD on every insert path by the before_insert listener below
    # and backfilled for existing rows (migration + boot self-heal). Nullable: an
    # article whose hash is not a 64-hex SHA-256 leaves content_multihash NULL rather
    # than fabricating an algorithm label.
    content_multihash: Mapped[str | None] = mapped_column(String(80))
    canon_version: Mapped[str | None] = mapped_column(String(16))
    # Source IP provenance (data-architecture Slice 6a). The server IP we connected to
    # at fetch -- OUR VANTAGE POINT, usually a CDN edge / anycast, NOT proof of the
    # publisher's true origin. Captured only on a DIRECT clearnet connection; over a
    # SOCKS proxy / Tor the socket reaches the proxy, not the server, so server_ip is
    # NULL and server_ip_reason states why (never a guessed IP). ip_observed_at is when
    # we looked. Geolocated offline + mapped (6b/6c) with the caveats visible.
    server_ip: Mapped[str | None] = mapped_column(String(45))  # IPv6-max length
    ip_observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    server_ip_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=lambda: datetime.now(UTC))

    # Enhanced metadata fields
    region: Mapped[str | None] = mapped_column(String(50))  # Geographic region
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2 country code
    author: Mapped[str | None] = mapped_column(String(255))  # Article author
    word_count: Mapped[int | None] = mapped_column(Integer)  # Number of words in the article
    reading_time: Mapped[int | None] = mapped_column(Integer)  # Estimated reading time in minutes

    # Content analysis fields
    sentiment_score: Mapped[float | None] = mapped_column(Float)  # Sentiment analysis score (-1 to 1)
    sentiment_label: Mapped[str | None] = mapped_column(String(20))  # Sentiment label (positive, negative, neutral)

    # QUARANTINE (S3.2, 2026-07-23 field-feedback workflow -- the NAV-SOUP SPECIMEN ruling's row-5
    # execution scope, maintainer sign-off A2/A3). A REVERSIBLE stamp, never a delete: quarantined
    # rows, their keywords, and their provenance stay fully intact -- un-quarantining restores full
    # visibility exactly as it was. Additive + nullable: an article created before this column
    # existed simply has quarantined=NULL ("never judged" -- the same honest-NULL convention as
    # server_ip above), treated identically to quarantined=False by every reader (see
    # `Article.quarantined.isnot(True)`, the one condition every quarantine-aware query uses).
    # quarantine_reason/quarantine_criteria_version mirror src.ingest.non_article.NonArticleVerdict's
    # own (signal, reason) shape + src.analytics.criteria_calibration.CRITERIA_VERSION, so a stamp
    # records EXACTLY which criteria generation flagged it and why -- never a bare boolean with no
    # explanation.
    quarantined: Mapped[bool | None] = mapped_column(Boolean, default=False)
    quarantine_reason: Mapped[str | None] = mapped_column(String(255))
    quarantine_criteria_version: Mapped[str | None] = mapped_column(String(40))
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationship to source
    source = relationship("Source", back_populates="articles")

    # Indexes for performance
    __table_args__ = (
        # Index for faster duplicate detection
        Index("idx_article_hash", "hash", unique=True),
        # Index for faster URL lookups
        Index("idx_article_canonical_url", "canonical_url"),
        # Index for faster source-based queries
        Index("idx_article_source_id", "source_id"),
        # NB: there is deliberately NO B-tree index on `content`. Full-text search
        # goes through the FTS5 virtual table (src/database/fts.py); a B-tree over
        # the full article body is never used by any query yet cost ~224 MB on a
        # 50k-article DB (63% of the file) and slowed every insert (finding PERF-02,
        # measured in scripts/benchmark_audit.py). Dropped via migration f1a2b3c4d5e6.
        # Index for faster language queries
        Index("idx_article_language", "language"),
        # Index for faster region queries
        Index("idx_article_region", "region"),
        # Index for faster country queries
        Index("idx_article_country", "country"),
        # Index for faster author queries
        Index("idx_article_author", "author"),
        # Index for faster date-based queries
        Index("idx_article_published_at", "published_at"),
        Index("idx_article_created_at", "created_at"),
        # Composite indexes for common query patterns
        Index("idx_article_source_published", "source_id", "published_at"),
        Index("idx_article_language_region", "language", "region"),
        Index("idx_article_country_language", "country", "language"),
        # Index for content length (word_count)
        Index("idx_article_word_count", "word_count"),
        # Index for sentiment analysis
        Index("idx_article_sentiment", "sentiment_score"),
        # Index for the quarantine exclusion (S3.2) -- every search/browse query filters on it
        Index("idx_article_quarantined", "quarantined"),
        # Covering index for the per-source-country GROUP BY behind /api/insights/
        # map-coverage (queries.source_country_counts): SELECT sources.country,
        # count(articles.id), avg(articles.sentiment_score), count(articles.sentiment_score)
        # JOIN sources GROUP BY sources.country. EXPLAIN QUERY PLAN (9.2, PR #740/#744
        # remediation field-diagnostics #728) confirmed the existing idx_article_source_id
        # is only a plain SEARCH (not COVERING) for this query -- SQLite finds matching
        # rows by source_id but still fetches the full table row to read sentiment_score,
        # dragging every ~35 KB article row through the SQLCipher codec (the same
        # column-order perf trap the ix_article_observed/ix_mention_covering indexes
        # already fixed elsewhere). With this covering index the plan becomes a pure
        # index-only SEARCH; measured 447 ms -> 38 ms on a 300k-article synthetic
        # PLAINTEXT store (the encrypted live corpus wins proportionally more, per the
        # documented codec cost). Mirrored in migration 04c029205aa8 (alembic-managed
        # DBs) and src/database/maintenance.py HOT_INDEXES (existing installs that don't
        # run `make migrate`).
        Index("idx_article_source_sentiment", "source_id", "sentiment_score"),
    )

    @property
    def is_compressed(self) -> bool:
        """Check if content is stored in compressed format."""
        return self.compressed_content is not None

    def compress_content(self) -> None:
        """Compress the content and store in compressed_content field."""
        if self.content and not self.compressed_content:
            from src.utils.compression import database_compressor

            self.compressed_content = database_compressor.compress_text_for_storage(self.content)

    def decompress_content(self) -> str:
        """Decompress the content from compressed_content field."""
        if self.compressed_content:
            from src.utils.compression import database_compressor

            return database_compressor.decompress_text_from_storage(self.compressed_content)
        return self.content or ""

    def get_content(self) -> str:
        """Get the content, decompressing if necessary."""
        if self.compressed_content:
            return self.decompress_content()
        return self.content or ""

    def set_content(self, content: str) -> None:
        """Set the content, optionally compressing it."""
        self.content = content
        # Clear compressed content to force recompression
        self.compressed_content = None

    def __repr__(self):
        title = (self.title or "")[:50]
        return f"<Article(id={self.id}, title='{title}...', source_id={self.source_id})>"


@event.listens_for(Article, "before_insert")
def _stamp_article_identity(mapper, connection, target: "Article") -> None:
    """Stamp the K1/K2 identity seams on EVERY insert path (Slice 5).

    A model-level hook (not per-call-site) so pipeline, crawl, email, wiki and any
    future ingest path all populate them — drift-proof. It only fills a value the
    caller left empty; it NEVER reformats ``hash`` and never fabricates a label:
    ``content_multihash`` is set only when ``hash`` is a 64-hex SHA-256 digest (which
    every ingest path produces via ``generate_content_hash``), else left NULL.
    """
    from src.utils.url_utils import CANON_VERSION, CONTENT_HASH_ALGO

    if not target.content_multihash and target.hash and len(target.hash) == 64:
        target.content_multihash = f"{CONTENT_HASH_ALGO}:{target.hash}"
    if not target.canon_version:
        target.canon_version = CANON_VERSION


# Keyword and Category Models for Keyword Extraction

# Association table for many-to-many relationship between Article and Keyword
article_keyword_association = Table(
    "article_keyword_association",
    Base.metadata,
    Column("article_id", Integer, ForeignKey("articles.id"), primary_key=True),
    Column("keyword_id", Integer, ForeignKey("keywords.id"), primary_key=True),
    Column("frequency", Integer, default=1),
    Column("position", Integer),
    Column("relevance_score", Float, default=0.0),
    Column("created_at", DateTime, default=lambda: datetime.now(UTC)),
    # Indexes for performance
    Index("idx_article_keyword_article_id", "article_id"),
    Index("idx_article_keyword_keyword_id", "keyword_id"),
)


class KeywordCategory(Base):
    """
    Represents a category for classifying keywords.

    Attributes:
        id: Primary key.
        name: Name of the category (e.g., "Politics", "Technology").
        description: Description of the category.
        parent_id: Foreign key to parent category (for hierarchical categories).
        color: Color code for UI display.
        is_active: Whether the category is active.
        created_at: Timestamp when the category was created.
        updated_at: Timestamp when the category was last updated.
        keywords: Relationship to Keyword model.
    """

    __tablename__ = "keyword_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("keyword_categories.id"))
    color: Mapped[str | None] = mapped_column(String(20), default="#666666")
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Self-referential relationship for hierarchical categories
    parent = relationship("KeywordCategory", remote_side=[id], back_populates="children")
    children = relationship("KeywordCategory", back_populates="parent")

    # One-to-many relationship with keywords
    keywords = relationship("Keyword", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<KeywordCategory(name='{self.name}', id={self.id})>"


class Keyword(Base):
    """
    Represents a keyword extracted from articles.

    Attributes:
        id: Primary key.
        term: The keyword term (normalized).
        normalized_term: Fully normalized term (lowercase, stemmed, etc.).
        language: Language code (e.g., "en", "fr").
        frequency: Total frequency across all articles.
        category_id: Foreign key to KeywordCategory.
        is_ngram: Whether this is an n-gram (multi-word keyword).
        ngram_size: Size of n-gram (1 for unigram, 2 for bigram, etc.).
        is_entity: Whether this keyword is a named entity.
        entity_type: Type of entity (person, organization, location, etc.).
        relevance_score: Overall relevance score.
        created_at: Timestamp when the keyword was first extracted.
        updated_at: Timestamp when the keyword was last updated.
        category: Relationship to KeywordCategory model.
        articles: Relationship to Article model (many-to-many).
    """

    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_term: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str | None] = mapped_column(String(10))  # honest NULL when unknown (audit 06)
    frequency: Mapped[int | None] = mapped_column(Integer, default=0)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("keyword_categories.id"))
    is_ngram: Mapped[bool | None] = mapped_column(Boolean, default=False)
    ngram_size: Mapped[int | None] = mapped_column(Integer, default=1)
    is_entity: Mapped[bool | None] = mapped_column(Boolean, default=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    relevance_score: Mapped[float | None] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Provenance: which extractor labelled this term (e.g. "baseline", "spacy",
    # "llm:<model>"). An entity type is a *labelled-by-X assertion*, never ground
    # truth -- this records the X (PRODUCT_SYNTHESIS §8).
    extractor: Mapped[str | None] = mapped_column(String(40))

    # Denormalised corpus-wide counters maintained AT INDEX TIME (the one
    # src/analytics/store.py chokepoint), so the hot keyword aggregations
    # (top_terms, super-groups) read an indexed counter instead of joining +
    # GROUP BY-ing the 800k+-row keyword_mentions table -- the structural cold-cost
    # win of the perf workstream (field report 2026-06-18: a GROUP BY of every
    # keyword over every mention dragged whole article pages through the SQLCipher
    # codec). These are HONEST COUNTS, never a score:
    #   * mention_count = SUM of the per-article occurrence counts (total mentions);
    #   * article_count = DISTINCT articles mentioning the keyword. There is exactly
    #     ONE KeywordMention row per (keyword, article) -- the unique
    #     (keyword_id, article_id) index -- so article_count is also the row count,
    #     which is why re-indexing one article moves it by at most +/-1 (the
    #     incremental maintenance is drift-proof and O(article), never a corpus scan).
    # server_default="0" backfills existing rows when the column is self-healed in
    # (an ALTER TABLE ADD COLUMN that is NOT NULL needs a default); the boot self-heal
    # and the migration then populate the real values from the live mentions. The
    # backfill is the authoritative repair; tests assert counter == the live GROUP BY
    # after ingest AND re-index.
    mention_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    article_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # When the counters above were last RECONCILED -- recomputed exactly from the
    # live mentions and proven equal to the canonical GROUP BY -- by the bounded
    # background reconcile (src/analytics/store.reconcile_keyword_counters). NULL =
    # never reconciled (the counters are still maintained incrementally + correct by
    # construction, but UNVERIFIED). The honesty envelope reads this: counters served
    # via the hot endpoints are disclosed `exact` when this watermark is fresh and
    # `estimated` when it is NULL or stale -- the cascade-delete drift (ondelete=CASCADE
    # bypasses the ORM maintenance hook, so a rare delete can drift a counter) is then
    # NEVER silently wrong, only honestly "estimated" until the next reconcile repairs
    # it. A disclosure of freshness, never a score.
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    # Relationships
    category = relationship("KeywordCategory", back_populates="keywords")
    articles = relationship("Article", secondary=article_keyword_association, lazy="dynamic")

    # Indexes for performance
    __table_args__ = (
        Index("idx_keyword_term", "term"),
        Index("idx_keyword_normalized_term", "normalized_term"),
        Index("idx_keyword_language", "language"),
        Index("idx_keyword_category_id", "category_id"),
        Index("idx_keyword_frequency", "frequency"),
        Index("idx_keyword_is_ngram", "is_ngram"),
        Index("idx_keyword_is_entity", "is_entity"),
        # Ordered scan for the corpus-wide top-N by mentions (top_terms, the hot
        # Home grouped view) -- an index-only ORDER BY mention_count DESC LIMIT,
        # no keyword_mentions join. Mirrored in the boot self-heal + migration.
        Index("idx_keyword_mention_count", "mention_count"),
    )

    def __repr__(self):
        return f"<Keyword(term='{self.term}', frequency={self.frequency})>"


class ArticleKeyword(Base):
    """
    Represents the relationship between an article and a keyword with additional metadata.

    This model stores information about how a keyword appears in a specific article,
    including frequency, position, and relevance score.

    Attributes:
        article_id: Foreign key to Article.
        keyword_id: Foreign key to Keyword.
        frequency: Number of times the keyword appears in the article.
        first_position: Position of first occurrence.
        last_position: Position of last occurrence.
        relevance_score: Relevance score for this keyword in this article.
        created_at: Timestamp when the relationship was created.
    """

    __tablename__ = "article_keywords"

    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id"), primary_key=True)
    keyword_id: Mapped[int] = mapped_column(Integer, ForeignKey("keywords.id"), primary_key=True)
    frequency: Mapped[int | None] = mapped_column(Integer, default=1)
    first_position: Mapped[int | None] = mapped_column(Integer)
    last_position: Mapped[int | None] = mapped_column(Integer)
    relevance_score: Mapped[float | None] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self):
        return f"<ArticleKeyword(article_id={self.article_id}, keyword_id={self.keyword_id}, frequency={self.frequency})>"


# Link Tracking Models for Source/Link Tracking System


class LinkClassificationRule(Base):
    """
    Represents a rule for classifying links.

    Attributes:
        id: Primary key.
        rule_name: Name of the classification rule.
        pattern: URL pattern to match (regex).
        classification_type: Type of classification (source, reference, ad, social, navigation, other).
        priority: Priority of the rule (higher = applied first).
        is_active: Whether the rule is active.
        created_at: Timestamp when the rule was created.
        updated_at: Timestamp when the rule was last updated.
    """

    __tablename__ = "link_classification_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    classification_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # source, reference, ad, social, navigation, other
    priority: Mapped[int | None] = mapped_column(Integer, default=1)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Indexes for performance
    __table_args__ = (
        Index("idx_link_classification_rule_name", "rule_name", unique=True),
        Index("idx_link_classification_type", "classification_type"),
        Index("idx_link_classification_priority", "priority"),
        Index("idx_link_classification_active", "is_active"),
    )

    def __repr__(self):
        return f"<LinkClassificationRule(rule_name='{self.rule_name}', classification_type='{self.classification_type}')>"


class ExternalSource(Base):
    """
    Represents an external source (website, publication, etc.) that is referenced in articles.

    Attributes:
        id: Primary key.
        domain: Domain of the source (e.g., "nytimes.com").
        name: Name of the source (e.g., "The New York Times").
        url: Base URL of the source.
        source_type: Type of source (news, blog, academic, government, etc.).
        credibility_score: Credibility score (0-100).
        political_bias: Political bias score (-100 to 100, left to right).
        country: Country code (ISO 3166-1 alpha-2).
        language: Primary language code (ISO 639-1).
        description: Description of the source.
        founded_year: Year the source was founded.
        alexa_rank: Alexa rank of the domain.
        social_media_followers: Number of social media followers.
        is_verified: Whether the source has been verified.
        last_verified_at: Timestamp when the source was last verified.
        created_at: Timestamp when the source was first added.
        updated_at: Timestamp when the source was last updated.
        source_articles: Relationship to SourceArticle model.
        links: Relationship to ArticleLink model.
    """

    __tablename__ = "external_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[str | None] = mapped_column(
        String(50), default="unknown"
    )  # news, blog, academic, government, social, etc.
    # No default: an unmeasured source has NO score (the old default=50.0 asserted
    # "medium credibility" for every unknown — fabricated data; audit 0.0.9). The
    # link-analysis API exposes counts only, never this field.
    credibility_score: Mapped[float | None] = mapped_column(Float)  # 0-100, unused today
    # No default: an unmeasured bias is NULL — default 0.0 asserted "centrist"
    # for every unknown (same fabrication class as credibility; audit 06).
    political_bias: Mapped[float | None] = mapped_column(Float)  # -100 (left) to 100 (right)
    country: Mapped[str | None] = mapped_column(String(2))
    language: Mapped[str | None] = mapped_column(String(10))  # honest NULL when unknown (audit 06)
    description: Mapped[str | None] = mapped_column(Text)
    founded_year: Mapped[int | None] = mapped_column(Integer)
    alexa_rank: Mapped[int | None] = mapped_column(Integer)
    social_media_followers: Mapped[int | None] = mapped_column(Integer)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, default=False)
    # Discovery provenance (Q4a): which offline channel first RESOLVED this domain into the
    # registry -- "citation" | "wikipedia" | "catalog". This ends the table's dormancy: cited/
    # discovered domains now resolve to external_source rows WITH provenance (the funnel's
    # resolution table). Descriptive, never a score; first-writer-wins (a later channel never
    # overwrites the first provenance). NULL for a pre-existing row.
    discovered_via: Mapped[str | None] = mapped_column(String(60))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    source_articles = relationship(
        "SourceArticle", back_populates="external_source", cascade="all, delete-orphan"
    )
    links = relationship(
        "ArticleLink", back_populates="external_source", cascade="all, delete-orphan"
    )

    # Indexes for performance
    __table_args__ = (
        Index("idx_external_source_domain", "domain", unique=True),
        Index("idx_external_source_name", "name"),
        Index("idx_external_source_type", "source_type"),
        Index("idx_external_source_credibility", "credibility_score"),
        Index("idx_external_source_country", "country"),
        Index("idx_external_source_verified", "is_verified"),
    )

    def __repr__(self):
        return f"<ExternalSource(name='{self.name}', domain='{self.domain}', credibility={self.credibility_score})>"


class SourceArticle(Base):
    """
    Represents an article from an external source that is referenced in our articles.

    Attributes:
        id: Primary key.
        source_id: Foreign key to ExternalSource.
        url: URL of the source article.
        title: Title of the source article.
        published_at: Publication date of the source article.
        author: Author of the source article.
        summary: Summary/description of the source article.
        content_hash: SHA-256 hash of the source article content.
        word_count: Number of words in the source article.
        sentiment_score: Sentiment score of the source article.
        is_accessible: Whether the source article is still accessible.
        last_accessed_at: Timestamp when the source article was last accessed.
        created_at: Timestamp when the source article was first added.
        updated_at: Timestamp when the source article was last updated.
        source: Relationship to ExternalSource model.
        article_links: Relationship to ArticleLink model.
    """

    __tablename__ = "source_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_sources.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    author: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256 hash
    word_count: Mapped[int | None] = mapped_column(Integer)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    is_accessible: Mapped[bool | None] = mapped_column(Boolean, default=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    external_source = relationship("ExternalSource", back_populates="source_articles")
    article_links = relationship(
        "ArticleLink", back_populates="source_article", cascade="all, delete-orphan"
    )

    # Indexes for performance
    __table_args__ = (
        Index("idx_source_article_source_id", "source_id"),
        Index("idx_source_article_url", "url", unique=True),
        Index("idx_source_article_published", "published_at"),
        Index("idx_source_article_hash", "content_hash", unique=True),
        Index("idx_source_article_accessible", "is_accessible"),
    )

    def __repr__(self):
        return f"<SourceArticle(title='{self.title[:50] if self.title else 'Untitled'}...', source_id={self.source_id})>"


class ArticleLink(Base):
    """
    Represents a link found in an article, with classification and relationship tracking.

    Attributes:
        id: Primary key.
        article_id: Foreign key to Article.
        url: The URL of the link.
        normalized_url: Normalized URL (for duplicate detection).
        link_text: The text of the link (anchor text).
        position: Position of the link in the article (character offset).
        link_type: Type of link (internal, external, image, etc.).
        classification: Classification of the link (source, reference, ad, social, navigation, other).
        external_source_id: Foreign key to ExternalSource (if identified).
        source_article_id: Foreign key to SourceArticle (if the link points to a known article).
        is_followable: Whether the link should be followed for scraping.
        is_working: Whether the link is still working (not 404).
        last_checked_at: Timestamp when the link was last checked.
        redirect_url: Final URL after following redirects.
        http_status: HTTP status code of the link.
        created_at: Timestamp when the link was first extracted.
        updated_at: Timestamp when the link was last updated.
        article: Relationship to Article model.
        external_source: Relationship to ExternalSource model.
        source_article: Relationship to SourceArticle model.
    """

    __tablename__ = "article_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    link_text: Mapped[str | None] = mapped_column(String(500))
    position: Mapped[int | None] = mapped_column(Integer)
    link_type: Mapped[str | None] = mapped_column(
        String(50), default="external"
    )  # internal, external, image, script, stylesheet, etc.
    classification: Mapped[str | None] = mapped_column(
        String(50), default="other"
    )  # source, reference, ad, social, navigation, other
    external_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("external_sources.id"))
    source_article_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("source_articles.id"))
    is_followable: Mapped[bool | None] = mapped_column(Boolean, default=True)
    is_working: Mapped[bool | None] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    redirect_url: Mapped[str | None] = mapped_column(String(1000))
    http_status: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    article = relationship("Article", back_populates="links")
    external_source = relationship("ExternalSource", back_populates="links")
    source_article = relationship("SourceArticle", back_populates="article_links")

    # Indexes for performance
    __table_args__ = (
        Index("idx_article_link_article_id", "article_id"),
        Index("idx_article_link_url", "url"),
        Index("idx_article_link_normalized_url", "normalized_url"),
        Index("idx_article_link_classification", "classification"),
        Index("idx_article_link_source_id", "external_source_id"),
        Index("idx_article_link_source_article_id", "source_article_id"),
        Index("idx_article_link_working", "is_working"),
        Index("idx_article_link_type", "link_type"),
    )

    def __repr__(self):
        return f"<ArticleLink(url='{self.url[:50]}...', classification='{self.classification}', article_id={self.article_id})>"


class ArticleMentionedDate(Base):
    """A calendar date *mentioned in* an article's text — an extracted, human-confirmable tag.

    Provenance-first and honest about status: each row is a ``candidate`` produced by the
    high-precision extractor (with the matched ``snippet`` and a ``confidence``), which the
    user can ``confirm`` or ``reject``. The date is *when the story refers to*, not when the
    article was published — so a 2024 piece on the 1945 bombing carries a 1945 tag.
    """

    __tablename__ = "article_mentioned_dates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ondelete=CASCADE is defense-in-depth: the ORM relationship already cascades on
    # session.delete(), this also covers any future bulk/raw delete of an article.
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    mentioned_on: Mapped[date] = mapped_column(Date, nullable=False)  # normalized; month precision -> day 1
    precision: Mapped[str] = mapped_column(String(10), nullable=False, default="day")  # 'day' | 'month'
    snippet: Mapped[str | None] = mapped_column(String(300))  # provenance: the matched text
    confidence: Mapped[float | None] = mapped_column(Float)  # extractor confidence in [0, 1]
    extractor: Mapped[str | None] = mapped_column(String(40), default="dateextract")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="candidate")  # candidate|confirmed|rejected
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    article = relationship("Article", back_populates="mentioned_dates")

    __table_args__ = (
        Index("ix_amd_article_id", "article_id"),
        Index("ix_amd_mentioned_on", "mentioned_on"),
        Index("ix_amd_status", "status"),
        UniqueConstraint("article_id", "mentioned_on", "precision", name="uq_amd_article_date"),
    )

    def __repr__(self):
        return (
            f"<ArticleMentionedDate(article_id={self.article_id}, "
            f"on={self.mentioned_on}, precision='{self.precision}', status='{self.status}')>"
        )


class ArticleSourceRelationship(Base):
    """
    Represents the relationship between an article and its external sources.

    This table tracks which external sources are referenced in which articles,
    including temporal analysis (article date vs. source article date).

    Attributes:
        id: Primary key.
        article_id: Foreign key to Article.
        source_id: Foreign key to ExternalSource.
        source_article_id: Foreign key to SourceArticle (if specific article is identified).
        link_id: Foreign key to ArticleLink (the specific link that created this relationship).
        relationship_type: Type of relationship (citation, reference, source, etc.).
        time_delta_days: Difference in days between article publication and source publication.
        is_temporal_anomaly: Whether there's a temporal anomaly (article published before source).
        confidence_score: Confidence score of the relationship (0-1).
        notes: Additional notes about the relationship.
        created_at: Timestamp when the relationship was created.
        updated_at: Timestamp when the relationship was last updated.
        article: Relationship to Article model.
        external_source: Relationship to ExternalSource model.
        source_article: Relationship to SourceArticle model.
        link: Relationship to ArticleLink model.
    """

    __tablename__ = "article_source_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_sources.id"), nullable=False)
    source_article_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("source_articles.id"))
    link_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("article_links.id"))
    relationship_type: Mapped[str | None] = mapped_column(
        String(50), default="reference"
    )  # citation, reference, source, mention, etc.
    time_delta_days: Mapped[float | None] = mapped_column(Float)  # Can be negative if article published before source
    is_temporal_anomaly: Mapped[bool | None] = mapped_column(Boolean, default=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, default=0.0)  # 0-1
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    article = relationship("Article")
    external_source = relationship("ExternalSource")
    source_article = relationship("SourceArticle")
    link = relationship("ArticleLink")

    # Indexes for performance
    __table_args__ = (
        Index("idx_article_source_rel_article_id", "article_id"),
        Index("idx_article_source_rel_source_id", "source_id"),
        Index("idx_article_source_rel_source_article_id", "source_article_id"),
        Index("idx_article_source_rel_link_id", "link_id"),
        Index("idx_article_source_rel_type", "relationship_type"),
        Index("idx_article_source_rel_anomaly", "is_temporal_anomaly"),
        Index("idx_article_source_rel_confidence", "confidence_score"),
    )

    def __repr__(self):
        return f"<ArticleSourceRelationship(article_id={self.article_id}, source_id={self.source_id}, time_delta={self.time_delta_days} days)"


class SourceCredibilityRule(Base):
    """
    Represents a rule for calculating source credibility scores.

    Attributes:
        id: Primary key.
        rule_name: Name of the credibility rule.
        factor: Factor to apply (e.g., alexa_rank, social_followers, etc.).
        weight: Weight of this factor in the overall score (0-1).
        min_value: Minimum value for normalization.
        max_value: Maximum value for normalization.
        is_inverse: Whether higher values should decrease credibility (e.g., alexa rank).
        is_active: Whether the rule is active.
        created_at: Timestamp when the rule was created.
        updated_at: Timestamp when the rule was last updated.
    """

    __tablename__ = "source_credibility_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    factor: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # alexa_rank, social_followers, age, verification_status, etc.
    weight: Mapped[float | None] = mapped_column(Float, default=1.0)  # 0-1
    min_value: Mapped[float | None] = mapped_column(Float, default=0.0)
    max_value: Mapped[float | None] = mapped_column(Float, default=100.0)
    is_inverse: Mapped[bool | None] = mapped_column(
        Boolean, default=False
    )  # True for factors where higher = worse (e.g., alexa rank)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Indexes for performance
    __table_args__ = (
        Index("idx_credibility_rule_name", "rule_name", unique=True),
        Index("idx_credibility_rule_factor", "factor"),
        Index("idx_credibility_rule_active", "is_active"),
    )

    def __repr__(self):
        return f"<SourceCredibilityRule(rule_name='{self.rule_name}', factor='{self.factor}', weight={self.weight})>"


# Add relationships to existing Article model
Article.links = relationship("ArticleLink", back_populates="article", cascade="all, delete-orphan")
Article.mentioned_dates = relationship(
    "ArticleMentionedDate", back_populates="article", cascade="all, delete-orphan"
)


class ArticleAnalysis(Base):
    """A derived analytic result for an article (LLM summary, translation, ...).

    Carries provenance so no number/text is ever shown without its origin
    (PRODUCT_SYNTHESIS §8): which model produced it, with which prompt version,
    and when. This is how LLM output is stored "with provenance".
    """

    __tablename__ = "article_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)  # summary | translation | entities | ...
    result: Mapped[str] = mapped_column(Text, nullable=False)
    # provenance
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # The EXACT system prompt actually used to produce this result. Prompts are
    # operator-editable (Settings → Models), so the version alone is not enough for
    # honest provenance once a prompt is customised — we store the verbatim text used
    # at generation time. NULL only for rows written before this column existed.
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    article = relationship("Article", backref="analyses")

    def __repr__(self) -> str:
        return f"<ArticleAnalysis(article_id={self.article_id}, kind='{self.kind}', model='{self.model}')>"


class CommodityPrice(Base):
    """A single observed commodity price point (time series).

    Stored alongside articles in the unified DB so price movements can be
    correlated with news. ``currency`` and ``unit`` are recorded explicitly --
    prices are NOT silently mixed across currencies/units (see src/commodity/units.py
    for correct, tested unit conversion).
    """

    __tablename__ = "commodity_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # e.g. "Nd", "Dy"
    market: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g. "china_spot", "USGS"
    observed_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="kg")  # mass unit (kg, t, lb, ozt, ...)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)  # provenance: where it came from
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (Index("ix_commodity_symbol_date", "symbol", "observed_on"),)

    def __repr__(self) -> str:
        return f"<CommodityPrice({self.symbol} {self.observed_on} {self.price} {self.currency}/{self.unit})>"


class MarketExtractionRule(Base):
    """Per-source rule for pulling ONE structured price point off a market page.

    Market/financial pages are structured data, not prose: running the article
    extractor on them yields text, not a clean ``symbol/price`` series. So a price
    series is only produced where the operator has told us *exactly where the
    number lives* on a specific page (a CSS selector, optionally narrowed by an
    attribute and/or a capture-group regex). This is the honest source of truth the
    Markets tabs chart from -- when a rule matches nothing, ingestion records an
    explicit failure and stores NO number (PRODUCT_SYNTHESIS §3.5). Pages without a
    rule are still captured as raw articles via the normal ethical path.
    """

    __tablename__ = "market_extraction_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which Markets sub-view this instrument belongs to.
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="commodity")  # financial|stock|commodity
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # e.g. "Nd", "AAPL", "XAU"
    label: Mapped[str | None] = mapped_column(String(120))  # human name, e.g. "Neodymium spot"
    url: Mapped[str] = mapped_column(String(1000), nullable=False)  # the exact page to fetch
    selector: Mapped[str] = mapped_column(String(500), nullable=False)  # CSS selector locating the price
    attribute: Mapped[str | None] = mapped_column(String(100))  # optional: read this attr, not text
    value_regex: Mapped[str | None] = mapped_column(String(300))  # optional: capture-group regex for the number
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="kg")  # mass unit for commodities
    market: Mapped[str | None] = mapped_column(String(100))  # market label / provenance
    enabled: Mapped[bool | None] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(255))  # honest last outcome string
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    source = relationship("Source")

    __table_args__ = (
        Index("ix_market_rule_source", "source_id"),
        Index("ix_market_rule_category", "category"),
        Index("ix_market_rule_symbol", "symbol"),
    )

    def __repr__(self) -> str:
        return f"<MarketExtractionRule({self.symbol} <- {self.selector!r} @ {self.url})>"


class KeywordFamilyOverride(Base):
    """A user's manual correction to keyword-family grouping (the "user disposes" rule).

    Families (src/analytics/families.py) merge surface variants automatically, but the
    user is the final arbiter. Each row pins one normalised surface form to a
    ``family_key``: forms sharing a key are forced into one family (a manual *merge*);
    a form whose key is its own normalised term is pinned standalone (a *split* out of
    an auto-family). Overrides are authoritative over the automatic rules and fully
    reversible — deleting the row restores automatic behaviour. We store the user's
    decision, never a rewrite of the underlying keyword rows.
    """

    __tablename__ = "keyword_family_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_term: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    family_key: Mapped[str] = mapped_column(String(255), nullable=False)  # forms sharing this key = one family
    canonical_label: Mapped[str | None] = mapped_column(String(255))  # preferred display label for the family
    kind: Mapped[str | None] = mapped_column(String(40))  # cached kind for display
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (Index("ix_kwfam_family_key", "family_key"),)

    def __repr__(self) -> str:
        return f"<KeywordFamilyOverride({self.normalized_term} -> {self.family_key})>"


class KeywordSuperGroup(Base):
    """A user-named umbrella above keyword *families* (a group-of-groups).

    Where a family collapses surface variants of one entity (``Trump`` / ``Trump's`` /
    ``Donald Trump``), a super-group lets the user gather several distinct families under
    one theme for sorting, discovery and mind-map clustering — e.g. "Russia–Ukraine war"
    over {Russia, Ukraine, Putin, Zelensky, sanctions}. It is pure user curation: we
    never auto-assign without the user, and membership is by the family's canonical
    *normalized term* (the stable key), so nothing in the keyword store is rewritten.
    """

    __tablename__ = "keyword_supergroups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(String(16))  # optional UI accent (hex)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    members = relationship(
        "KeywordSuperGroupMember", back_populates="supergroup", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KeywordSuperGroup({self.name})>"


class KeywordSuperGroupMember(Base):
    """One member of a super-group — a FAMILY or a RING (the super-ring model).

    Default: a family by its canonical ``normalized_term`` (``ring_id`` NULL). When
    ``ring_id`` is set the member is a cross-language RING (concept), so the
    super-group spans languages — "rings of rings": keyword → family → ring →
    super-group. A ring member stores the ring id in BOTH ``ring_id`` (the marker +
    link) and ``normalized_term`` (so the unique (supergroup_id, normalized_term)
    key and the existing remove-by-key path keep working unchanged)."""

    __tablename__ = "keyword_supergroup_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supergroup_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("keyword_supergroups.id", ondelete="CASCADE"), nullable=False
    )
    normalized_term: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ring_id: Mapped[str | None] = mapped_column(String(64))  # set => this member is a RING (concept)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    supergroup = relationship("KeywordSuperGroup", back_populates="members")

    __table_args__ = (
        Index("ix_kwsg_member_unique", "supergroup_id", "normalized_term", unique=True),
    )

    def __repr__(self) -> str:
        kind = f"ring:{self.ring_id}" if self.ring_id else self.normalized_term
        return f"<KeywordSuperGroupMember(sg={self.supergroup_id} {kind})>"


class KeywordTag(Base):
    """A tag on a keyword along a named AXIS (Item AC, slice 1).

    Two orthogonal, optional, multi-valued axes: a semantic ``type`` (event /
    disease / technology / currency …) and a ``topic``/domain (politics / economy /
    health …). A tag is a LABELLED ASSERTION, never ground truth and never a score:
    ``source`` records who asserted it — a curated, dated BASELINE applied at index
    time, or the USER (authoritative + reversible). Nothing in the keyword store is
    rewritten; deleting a row removes the assertion. The baseline is bundled +
    local-only (configs/keyword_baseline/<lang>.yml); see src/analytics/baseline.py.
    """

    __tablename__ = "keyword_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False
    )
    axis: Mapped[str] = mapped_column(String(16), nullable=False)  # "type" | "topic"
    tag: Mapped[str] = mapped_column(String(64), nullable=False)  # "event" | "politics" | ...
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="baseline"
    )  # "baseline" (curated, dated) | "user" (authoritative)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_keyword_tags_keyword_id", "keyword_id"),
        Index("ix_keyword_tags_axis_tag", "axis", "tag"),
        UniqueConstraint("keyword_id", "axis", "tag", "source", name="uq_keyword_tag"),
    )

    def __repr__(self) -> str:
        return f"<KeywordTag(kw={self.keyword_id} {self.axis}={self.tag} [{self.source}])>"


class ArticleMentionedPlace(Base):
    """A place DEDUCED from an article's text at ingest (T12, When×Where×Who).

    Lexical candidates with snippet provenance and the rule note — displayed
    as deduced, never promoted to fact. Event-place (from the text) is
    distinct from coverage origin (the source's country on mentions)."""

    __tablename__ = "article_mentioned_places"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))  # ISO-2, lowercase
    kind: Mapped[str | None] = mapped_column(String(20))  # city | country
    mentions: Mapped[int] = mapped_column(Integer, default=1)
    snippet: Mapped[str | None] = mapped_column(String(400))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(300))  # which rule decided
    extractor: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_amp_article_place", "article_id", "name", unique=True),
        Index("ix_amp_country", "country"),
    )


class ArticleEntity(Base):
    """A person or organization DEDUCED from an article's text at ingest
    (T12). The two classes are separate BY DESIGN (maintainer ruling): they
    answer different questions and anchor to space differently."""

    __tablename__ = "article_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_class: Mapped[str] = mapped_column(String(16), nullable=False)  # person | organization
    mentions: Mapped[int] = mapped_column(Integer, default=1)
    snippet: Mapped[str | None] = mapped_column(String(400))
    note: Mapped[str | None] = mapped_column(String(300))
    extractor: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_ae_article_name_class", "article_id", "name", "entity_class", unique=True),
        Index("ix_ae_class_name", "entity_class", "name"),
    )


class HazardEventDetail(Base):
    """Provider-ASSERTED event metadata for a hazard ingested as an Article
    (2026-07-24 field-feedback Session A §6, ruled: hazards ingest AS Articles).

    The TWO-CLASS discipline, the other way round from :class:`ArticleMentionedPlace`/
    :class:`ArticleEntity` (which are DEDUCED from text): magnitude/coordinates/
    severity here are exactly what the provider (USGS/GDACS) published for this
    event -- an ASSERTED fact, never inferred, never a score. One row per Article
    (the linked-layer pattern, mirroring LawRevisionSummary/ArticleAnalysis);
    ``event_id`` + ``provider`` are the provider's own dedup key (kept alongside
    the Article's canonical_url, which already encodes both, for a cheap lookup
    without parsing the URL).
    """

    __tablename__ = "hazard_event_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # "usgs" | "gdacs"
    event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(40))  # earthquake | cyclone | flood | ...
    severity: Mapped[str | None] = mapped_column(String(20))  # the PROVIDER's own tier
    magnitude: Mapped[float | None] = mapped_column(Float)  # None when the provider states none
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    place: Mapped[str | None] = mapped_column(String(300))
    event_time: Mapped[datetime | None] = mapped_column(DateTime)  # the provider's own timestamp
    source_url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    article = relationship("Article", backref=backref("hazard_detail", uselist=False))

    __table_args__ = (
        Index("ix_hazard_detail_provider_event", "provider", "event_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<HazardEventDetail(article_id={self.article_id}, provider='{self.provider}')>"


class KeywordMention(Base):
    """One article's mention of a keyword/entity, with context + denormalised facets.

    The foundation of keyword analytics. One row per (article, keyword): ``count``
    is how many times the term occurs in that article and ``first_offset`` points
    at the first occurrence so the surrounding sentence can be reconstructed from
    ``Article.content`` on read (we store offsets, not snippets, to stay lean).

    ``observed_on`` (the article's publish/ingest date), ``country`` and ``city``
    are denormalised from the article's source so trend, map and per-region
    queries are a single indexed scan instead of a multi-join. ``extractor``
    records how the keyword was found (provenance).
    """

    __tablename__ = "keyword_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(Integer, ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False)
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_offset: Mapped[int | None] = mapped_column(Integer)  # char offset in Article.content
    observed_on: Mapped[date | None] = mapped_column(Date, index=True)  # denormalised article date (for trends)
    country: Mapped[str | None] = mapped_column(String(2))  # denormalised source country (for the map)
    city: Mapped[str | None] = mapped_column(String(120))  # denormalised source city, when known
    # Denormalised source id (like observed_on/country) so per-SOURCE analytics (the
    # flood/bury concentration card #4) avoid the keyword_mentions->articles decrypt trap.
    # Populated forward at index time; a re-index fills it for an existing corpus (no heavy
    # boot backfill over millions of rows). Indexed for the GROUP BY source_id scan.
    source_id: Mapped[int | None] = mapped_column(Integer, index=True)
    extractor: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    keyword = relationship("Keyword")
    article = relationship("Article")

    __table_args__ = (
        # One mention row per article+keyword; re-indexing updates it in place.
        Index("ix_mention_keyword_article", "keyword_id", "article_id", unique=True),
        Index("ix_mention_keyword_date", "keyword_id", "observed_on"),
        Index("ix_mention_country", "country"),
        Index("ix_mention_article", "article_id"),
        # Covering index for the corpus-wide keyword aggregations (diagnostics
        # export, insights rankings): SUM(count)/COUNT(DISTINCT article_id)/
        # MIN-MAX(observed_on) GROUP BY keyword_id become index-only scans —
        # without it every mention row costs a table page read (a decrypt
        # each, under SQLCipher). Also in maintenance.HOT_INDEXES (boot
        # self-heal) and migration e2f3a4b5c6d7.
        Index("ix_mention_covering", "keyword_id", "article_id", "count", "observed_on"),
        # Covering index for the TIME-WINDOWED trending aggregation (the #1 perf
        # hotspot: /api/insights/trending-windows, polled from Home — ~20s idle /
        # ~98s under load on a 2.4M-mention corpus). `trending()._counts` runs
        # `SELECT keyword_id, SUM(count) WHERE observed_on IN [lo,hi) GROUP BY
        # keyword_id`; the keyword_id-leading covering index above can't serve an
        # observed_on RANGE, and the plain observed_on index forces a heap page
        # read (a SQLCipher decrypt) per in-range row. Leading with observed_on +
        # carrying keyword_id, count makes it an index-only ("USING COVERING
        # INDEX") range scan. Counters are corpus-wide; the per-day trend window
        # needs THIS. Also in maintenance.HOT_INDEXES + migration b4c5d6e7f8a9.
        Index("ix_mention_date_keyword", "observed_on", "keyword_id", "count"),
    )

    def __repr__(self) -> str:
        return f"<KeywordMention(kw={self.keyword_id} art={self.article_id} x{self.count})>"


class AiKeyword(Base):
    """AI-DERIVED keywords/entities — a labelled, UNRELIABLE lens, NEVER the trusted index.

    Maintainer ruling 2026-06-18 (REVERSES the earlier separate-database design): AI
    analytics live in their OWN tables in the MAIN database — not a separate file — for
    seamless UI integration + fast corpus-wide selection (a real indexed JOIN on
    ``article_id``). The integrity guarantee is preserved BY CONSTRUCTION, not by physical
    separation:
      * this is its OWN table, never the trusted ``keywords`` / ``keyword_mentions``;
      * the rule-based keyword index reads ONLY ``articles.content`` and NEVER this table
        (enforced by tests/test_ai_layer.py) — so AI output can never be confused with, or
        joined into, rule-based fact;
      * every row carries its model provenance; there is NO score column (honesty);
      * ``confirmed`` curates the lens IN PLACE — a confirmed row stays AI-derived, it never
        crosses into the trusted tables.
    Always surfaced in the UI as "AI-derived · unreliable" (the two-class convention).
    """

    __tablename__ = "ai_keyword"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # A REAL FK now (same database): referential integrity + cascade cleanup + the
    # indexed JOIN that makes corpus-wide AI-signal selection fast.
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    term: Mapped[str] = mapped_column(String(300), nullable=False)
    # The kind of AI analytic: keyword | entity | claim | dedup | perception (extensible).
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="keyword")
    language: Mapped[str | None] = mapped_column(String(16))
    # Provenance: which local model produced this, under which prompt version.
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    # Confirm-within-the-lens: default unconfirmed. A confirmed row STAYS AI-derived.
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Optional free-text evidence (e.g. the snippet the model drew the term from).
    evidence: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    article = relationship("Article")

    __table_args__ = (
        Index("ix_ai_keyword_article_kind", "article_id", "kind"),
        Index("ix_ai_keyword_term", "term"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<AiKeyword {self.kind} {self.term!r} a={self.article_id}>"


class AiCustomPrompt(Base):
    """A user-defined AI extractor — a managed-list prompt producing TYPED AI metadata
    (maintainer ask 2026-06-18). Conceptually an extension of the built-in who/where/when
    extractors: each custom prompt declares an ``output_kind`` (the metadata TYPE, e.g.
    "figure", "statute", "quote") and its results are stored as ``AiKeyword`` rows of that
    kind — the UNIFIED, prompt-related AI-metadata store, labelled "AI-derived · unreliable"
    like the rest. These rows are config/definitions (no AI output lives here); a prompt runs
    on demand and/or — per ``run_on_ingest`` — automatically at ingest. The trusted rule-based
    index is never involved.
    """

    __tablename__ = "ai_custom_prompt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    # The metadata TYPE this prompt produces (becomes the AiKeyword.kind of its results).
    output_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Per-prompt run toggle (maintainer choice "both"): also run automatically at ingest.
    run_on_ingest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<AiCustomPrompt {self.label!r} kind={self.output_kind}>"


class SourceCandidate(Base):
    """A machine-suggested source awaiting the operator's decision (RM-19, WP5).

    Discovery is transparent by construction: every candidate records WHICH
    offline channel suggested it and the evidence (as JSON text), is clearly
    distinct from curated sources, and does nothing until the operator promotes
    it -- and even promotion creates a DISABLED Source the operator must enable.
    Statuses: candidate -> promoted | dismissed.
    """

    __tablename__ = "source_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    suggested_name: Mapped[str | None] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(30), nullable=False)  # citation | catalog
    evidence: Mapped[str | None] = mapped_column(Text)  # JSON: the channel's reasoning
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="candidate")
    first_seen: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("idx_source_candidate_status", "status"),
        Index("idx_source_candidate_channel", "channel"),
    )

    def __repr__(self) -> str:
        return f"<SourceCandidate(domain={self.domain!r}, channel={self.channel!r}, status={self.status!r})>"


class WikiPage(Base):
    """A tracked Wikipedia page in one language edition (e.g. en, fr, ar).

    Editions are per-*language*, not per-country (mapped to countries only in the
    UI). We keep ONE full-text baseline snapshot per page (``baseline_text``,
    compressed) taken when tracking starts; everything after is stored as per-edit
    diffs on :class:`WikiRevision`, so cosmetic edits cost almost nothing and the
    store scales with edit activity, not article size.
    """

    __tablename__ = "wiki_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wiki: Mapped[str] = mapped_column(String(16), nullable=False)  # language edition code, e.g. "en"
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    pageid: Mapped[int | None] = mapped_column(Integer)  # MediaWiki page id
    watched: Mapped[bool | None] = mapped_column(Boolean, default=True)
    category: Mapped[str | None] = mapped_column(String(255))  # optional grouping (e.g. a watchlist name)
    baseline_revid: Mapped[int | None] = mapped_column(Integer)  # revid the baseline_text corresponds to
    baseline_text: Mapped[str | None] = mapped_column(CompressedText)  # one full snapshot; later versions = baseline + diffs
    last_revid: Mapped[int | None] = mapped_column(Integer)  # newest revid we have stored
    # The LATEST full text (maintainer-ruled 2026-06-12: the article shown is
    # always the newest version, with the change history beneath). Refreshed by
    # the tracker when new revisions land; the revid it corresponds to travels
    # with it so the UI can say exactly which version the user is reading.
    latest_text: Mapped[str | None] = mapped_column(CompressedText)
    latest_text_revid: Mapped[int | None] = mapped_column(Integer)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The wiki's own verdict on the title (live test 2026-06-10): True = the page
    # does not exist (typo / renamed / deleted) — surfaced loudly, never silent.
    missing: Mapped[bool | None] = mapped_column(Boolean)
    # The article's REAL Wikipedia categories (JSON list of strings) — fetched at
    # baseline for classification/filtering; distinct from the operator's own
    # `category` watchlist label above.
    wiki_categories: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    revisions = relationship("WikiRevision", back_populates="page", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_wikipage_wiki_title", "wiki", "title", unique=True),
        Index("ix_wikipage_watched", "watched"),
        Index("ix_wikipage_category", "category"),
    )

    def __repr__(self) -> str:
        return f"<WikiPage({self.wiki}:{self.title})>"


class WikiRevision(Base):
    """One stored edit (revision) of a tracked page: a delta, not a re-copy.

    Holds the edit's metadata (editor, comment, flags, byte delta), the **diff**
    (added/removed text, compressed) rather than the whole new article, optional
    ORES model scores (a labelled-by-ORES assertion, with provenance), and the
    honest large-edit flag + reasons computed at ingest. Any historical full text
    is reconstructable by replaying diffs from the page baseline.
    """

    __tablename__ = "wiki_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(Integer, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=False)
    revid: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revid: Mapped[int | None] = mapped_column(Integer)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    editor: Mapped[str | None] = mapped_column(String(255))
    editor_anon: Mapped[bool | None] = mapped_column(Boolean, default=False)
    comment: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int | None] = mapped_column(Integer)  # new article size in bytes
    delta_bytes: Mapped[int | None] = mapped_column(Integer)  # size - parent size (signed)
    tags: Mapped[str | None] = mapped_column(String(500))  # MediaWiki change tags, comma-separated
    minor: Mapped[bool | None] = mapped_column(Boolean, default=False)
    bot: Mapped[bool | None] = mapped_column(Boolean, default=False)
    diff: Mapped[str | None] = mapped_column(CompressedText)  # added/removed text for this edit
    # The revision's FULL TEXT (maintainer-agreed 2026-06-12, the storage
    # ruling for the living-source engine): exact, locally-materializable
    # versions — analytics can anchor to the precise text a revid had.
    # Compressed; storage grows with edit activity, and the UI SAYS so.
    full_text: Mapped[str | None] = mapped_column(CompressedText)

    # ORES (Wikimedia) model scores -- attributed, optional enrichment.
    ores_damaging: Mapped[float | None] = mapped_column(Float)
    ores_goodfaith: Mapped[float | None] = mapped_column(Float)
    ores_provenance: Mapped[str | None] = mapped_column(String(80))

    # Honest large-edit detection computed at ingest.
    flagged: Mapped[bool | None] = mapped_column(Boolean, default=False)
    flag_reasons: Mapped[str | None] = mapped_column(String(500))  # comma-separated reason codes
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    page = relationship("WikiPage", back_populates="revisions")

    __table_args__ = (
        Index("ix_wikirev_page_revid", "page_id", "revid", unique=True),
        Index("ix_wikirev_page_time", "page_id", "timestamp"),
        Index("ix_wikirev_flagged", "flagged"),
    )

    def __repr__(self) -> str:
        return f"<WikiRevision(page={self.page_id} rev={self.revid} d={self.delta_bytes})>"


class LawDocument(Base):
    """A tracked legal document (statute / gazette / IP record) from any jurisdiction.

    The world-law vertical (FUTURE_DEVELOPMENTS §5) reuses the Wikipedia change-tracking
    pattern almost wholesale: a legal document is a tracked source whose *edits are the
    data*. We keep ONE compressed baseline snapshot taken when tracking starts; every
    later change is stored as a per-revision diff on :class:`LawRevision`, so the store
    scales with amendment activity, not document size.

    A research *mirror*, never the authoritative source: ``official_url`` always links
    back to the official gazette, and ``consolidated`` records whether the text is a
    point-in-time consolidation or a raw fetch (honest about what we have).
    """

    __tablename__ = "law_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jurisdiction: Mapped[str] = mapped_column(String(8), nullable=False)  # ISO-ish code: uk, eu, fr, us, int…
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)  # the page we fetch (consolidated text)
    official_url: Mapped[str | None] = mapped_column(String(1000))  # canonical official link (may equal url)
    category: Mapped[str | None] = mapped_column(String(40), default="legislation")  # legislation|gazette|ip|case-law
    consolidated: Mapped[bool | None] = mapped_column(Boolean, default=False)  # point-in-time consolidation vs raw fetch
    watched: Mapped[bool | None] = mapped_column(Boolean, default=True)
    baseline_text: Mapped[str | None] = mapped_column(CompressedText)  # one full snapshot; later = baseline + diffs
    baseline_hash: Mapped[str | None] = mapped_column(String(64))
    # The materialised NEWEST text (mirrors WikiPage.latest_text) so the CURRENT law is shown
    # without replaying diffs; latest_text_revid points at the LawRevision it corresponds to.
    # Versioned-sources ruling: a law is an Article + a linked revision/audit trail. Additive.
    latest_text: Mapped[str | None] = mapped_column(CompressedText)
    latest_text_revid: Mapped[int | None] = mapped_column(Integer)
    last_hash: Mapped[str | None] = mapped_column(String(64))  # content hash at last successful fetch
    last_size: Mapped[int | None] = mapped_column(Integer)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(255))  # honest last outcome (ok / fetch error / …)
    # S4b (the Cambodia fix, law-vertical brief 2026-07-17): the catalog carries the
    # document's OWN ASSERTED language/country (a French-language Cambodian code, an
    # English-language India Code…), but registration used to drop it, so the corpus
    # Article got no language -> wrong stoplist, no language facet. Additive, nullable:
    # a document the catalog never states a language for stays honestly None, never
    # guessed from the jurisdiction (uk/us are English, eu is multilingual, many
    # jurisdictions are ambiguous).
    language: Mapped[str | None] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    revisions = relationship("LawRevision", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_lawdoc_jurisdiction_url", "jurisdiction", "url", unique=True),
        Index("ix_lawdoc_watched", "watched"),
        Index("ix_lawdoc_category", "category"),
    )

    def __repr__(self) -> str:
        return f"<LawDocument({self.jurisdiction}:{self.title[:40]})>"


class LawRevision(Base):
    """One observed change of a tracked legal document: a delta, not a re-copy.

    Holds the change's metadata (observed time, content hash, byte delta), the **diff**
    (added/removed text, compressed) rather than the whole new document, and the honest
    large-change flag + reasons computed at ingest (reusing the wiki flagging thresholds).
    """

    __tablename__ = "law_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("law_documents.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int | None] = mapped_column(Integer)
    delta_bytes: Mapped[int | None] = mapped_column(Integer)  # size - previous size (signed)
    diff: Mapped[str | None] = mapped_column(CompressedText)  # added/removed text for this change
    # The FULL text at this revision (mirrors WikiRevision.full_text) so ANY past version is
    # reconstructable locally, not just from a lossy capped diff. Additive, nullable.
    full_text: Mapped[str | None] = mapped_column(CompressedText)
    flagged: Mapped[bool | None] = mapped_column(Boolean, default=False)
    flag_reasons: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    document = relationship("LawDocument", back_populates="revisions")

    __table_args__ = (
        Index("ix_lawrev_doc_hash", "document_id", "content_hash", unique=True),
        Index("ix_lawrev_doc_time", "document_id", "observed_at"),
        Index("ix_lawrev_flagged", "flagged"),
    )

    def __repr__(self) -> str:
        return f"<LawRevision(doc={self.document_id} d={self.delta_bytes})>"


class LawRevisionSummary(Base):
    """An AI-generated plain-language summary of ONE law change (2026-07-24
    field-feedback Session A §3: "AI change summaries" -- ruled).

    A LINKED layer over :class:`LawRevision`, mirroring :class:`ArticleAnalysis`'s
    provenance shape exactly (model + prompt_version + the verbatim prompt_text
    used) so no AI text is ever shown without its origin. NEVER the trusted
    diff/revision record itself -- the ONE ``index_article`` corpus-keyword pass
    never reads this table. Rendered "AI-derived - unreliable" (the established
    third class); a revision may be re-summarized (a later, better prompt), so
    this is append-only like ArticleAnalysis, never an in-place overwrite.
    """

    __tablename__ = "law_revision_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("law_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    revision = relationship("LawRevision", backref="ai_summaries")

    def __repr__(self) -> str:
        return f"<LawRevisionSummary(revision_id={self.revision_id}, model='{self.model}')>"


class MergeBatch(Base):
    """One import/merge of an external backup artifact into this corpus.

    The provenance anchor for the DB-reliability mandate: every row that arrived
    via merge is traceable to the batch that brought it (see MergedRow), so
    imported material can never silently launder into first-party evidence.
    ``origin_fingerprint`` is the artifact signer's public-key id when the
    manifest was signed and verified, else "unsigned" -- verified, not trusted.
    """

    __tablename__ = "merge_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), index=True
    )
    artifact_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="oo-backup-2")
    origin_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, default="unsigned")
    app_version: Mapped[str | None] = mapped_column(String(20))  # from the manifest (legacy: None)
    alembic_rev: Mapped[str | None] = mapped_column(String(32))  # schema rev the artifact carried
    manifest_json: Mapped[str | None] = mapped_column(Text)  # the verified manifest (or synthesized stub)
    counts_json: Mapped[str | None] = mapped_column(Text)  # per-domain plan {new, duplicate, conflict}
    report_json: Mapped[str | None] = mapped_column(Text)  # post-merge verification verdicts
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="previewed")  # previewed|merged|failed

    rows = relationship("MergedRow", back_populates="batch", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<MergeBatch({self.id} {self.status} from {self.origin_fingerprint[:12]})>"


class MergedRow(Base):
    """One row written into this corpus by a merge batch (provenance of merge).

    A mapping table instead of an origin column on ~20 domain tables: no schema
    churn, one JOIN tells any surface (reader, evidence export, analytics)
    whether a row is first-party or arrived via import -- and from which batch.
    """

    __tablename__ = "merged_rows"

    batch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("merge_batches.id", ondelete="CASCADE"), primary_key=True
    )
    table_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    row_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    batch = relationship("MergeBatch", back_populates="rows")

    __table_args__ = (Index("ix_merged_rows_lookup", "table_name", "row_id"),)

    def __repr__(self) -> str:
        return f"<MergedRow(b{self.batch_id} {self.table_name}#{self.row_id})>"


class StatFigure(Base):
    """One observed value from an official statistical producer, with its full trail.

    Group N (official-statistics ingestion). A figure is a single (agency, series,
    area, period) observation fetched from a documented machine endpoint (World Bank
    API / SDMX-JSON) and parsed by ``src.stats.sdmx``. It carries NO score and NO
    verdict -- only the published value and the provenance needed to compare it
    honestly. The Python-level value object is ``src.stats.sdmx.StatFigure``; this is
    its durable form.

    VINTAGES are first-class (the law/wiki versioning model applied to statistics): a
    re-fetch at a later ``extracted_at`` is a NEW ROW, never an overwrite, so a
    revision is preserved as evidence. The unique key therefore includes
    ``extracted_at``. A published gap is stored with ``value=None`` (degrade loudly,
    never a fabricated 0); comparability fields (``unit`` / ``adjustment`` SA-NSA /
    ``base_year``) are stored only when the response stated them, else NULL -- so a
    later side-by-side triangulation can flag incomparable denominators instead of
    silently averaging across them. Producers are NEVER averaged.
    """

    __tablename__ = "stat_figures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency: Mapped[str] = mapped_column(String(40), nullable=False)  # "worldbank" | "eurostat" | ...
    series_id: Mapped[str] = mapped_column(String(120), nullable=False)  # indicator/dataset series id
    ref_area: Mapped[str] = mapped_column(String(24), nullable=False)  # producing/subject area as published
    time_period: Mapped[str] = mapped_column(String(24), nullable=False)  # period label as published
    value: Mapped[float | None] = mapped_column(Float, nullable=True)  # None = published gap (loud)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    methodology_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    adjustment: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "SA"/"NSA"/raw, else None
    base_year: Mapped[str | None] = mapped_column(String(24), nullable=True)  # index base period, else None
    extracted_at: Mapped[str] = mapped_column(String(40), nullable=False)  # ISO-8601 vintage marker
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        # A new vintage (extracted_at) is a new row; the same vintage of the same
        # observation is idempotent. NO score column exists, by design.
        UniqueConstraint(
            "agency", "series_id", "ref_area", "time_period", "extracted_at",
            name="uq_stat_figure_vintage",
        ),
        Index("ix_stat_figures_series", "series_id", "ref_area", "time_period"),
        Index("ix_stat_figures_agency", "agency"),
    )

    def __repr__(self) -> str:
        return (
            f"<StatFigure({self.agency}:{self.series_id} {self.ref_area} "
            f"{self.time_period}={self.value} @{self.extracted_at})>"
        )


class StatSnapshot(Base):
    """One hourly snapshot of a cheap Library-tab counter (2026-07-23 field-feedback S2).

    The Library tab's "Downloaded"/"Database" figures were live single numbers with
    no history — the maintainer asked for small evolution GRAPHS instead. Most of
    those counters (sources, keywords, Wikipedia pages/revisions tracked, law
    documents/revisions tracked) have NO existing per-hour history anywhere in the
    store, unlike ``Article.created_at`` (which lets an articles/hour graph backfill
    retroactively for free) — so this table exists to start recording one, honestly,
    from the moment recording begins.

    An EAV shape (metric, taken_at, value) mirrors this project's own vintage
    convention (:class:`StatFigure`, :class:`SourceQualificationAttempt`): APPEND-ONLY,
    never an overwrite, one row per (metric, hour). Retention is INFINITE by design
    (ruled: "I would prefer infinite retention") — nothing here ever prunes old rows;
    a bounded READ window is a query-time concern (the serving endpoint), never a
    storage-time one. ``taken_at`` is the metric's HOUR BUCKET (minutes/seconds
    zeroed), so the unique constraint below is also the natural "already snapped
    this hour" freshness gate — no separate marker file needed, unlike the
    JSON-marker convention ``maybe_cleanup_keywords``/``maybe_incremental_vacuum``
    use (those gate a HEAVY multi-step operation; this gates a handful of cheap
    ``COUNT(*)`` reads, so the table itself is the cheaper and driftproof source of
    truth for "have we already recorded this hour").
    """

    __tablename__ = "stat_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric: Mapped[str] = mapped_column(String(40), nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # the hour bucket, UTC, naive
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("metric", "taken_at", name="uq_stat_snapshot_metric_hour"),
        Index("ix_stat_snapshots_metric_time", "metric", "taken_at"),
    )

    def __repr__(self) -> str:
        return f"<StatSnapshot({self.metric}={self.value} @{self.taken_at})>"


class Watch(Base):
    """A saved local CONDITION the convergence watch engine re-evaluates (ruling
    2026-06-17 #3: "if-this-then-WATCH", ON by default).

    A watch is a saved search/condition over the corpus. The engine evaluates every
    ENABLED watch after each scrape pass (local-only, NO notifications/network/
    telemetry, NO escalation tiers): when the corpus gains enough NEW matching
    articles in the recent window, the watch FIRES — recording a ``WatchMatch`` (the
    history) and surfacing a "watch" Lead card. ``enabled`` defaults TRUE (the engine
    is on by default); the user can enable/edit/delete each watch.

    Honesty: a watch fires on a real COUNT crossing a user-set threshold (no score, no
    fabricated urgency). ``last_seen_ids`` (JSON list) lets the engine fire only on
    genuinely NEW evidence, never re-alarming on the same articles every pass.
    """

    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)  # the FTS condition
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=3)  # min matching articles to fire
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)  # recent window
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # ON by default (#3)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of last firing ids

    matches = relationship("WatchMatch", back_populates="watch", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_watches_enabled", "enabled"),)

    def __repr__(self) -> str:
        return f"<Watch({self.id} {self.name!r} q={self.query!r} {'on' if self.enabled else 'off'})>"


class WatchMatch(Base):
    """One firing of a watch — the history a user browses (ruling #3 "Watches view +
    history"). Counts only, never a score; ``article_ids`` is the exact set that fired,
    so the UI can open it in the analysis window."""

    __tablename__ = "watch_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("watches.id", ondelete="CASCADE"), nullable=False
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    n_articles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # total in window at fire
    new_articles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # new since last fire
    article_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of the firing set

    watch = relationship("Watch", back_populates="matches")

    __table_args__ = (Index("ix_watch_matches_watch", "watch_id", "matched_at"),)

    def __repr__(self) -> str:
        return f"<WatchMatch(watch={self.watch_id} n={self.n_articles} +{self.new_articles})>"


class StatSubscription(Base):
    """A TRACKED official-statistics fetch, re-run periodically to capture new VINTAGES
    (ruling 2026-06-17 #12: keep figures user-initiated AND add scheduled auto-refresh).

    Recorded when the user fetches figures, so the SAME fetch can be replayed on a
    cadence — each replay storing a new vintage (the figure store is vintage-additive,
    never an overwrite). The scheduler refreshes DUE subscriptions during its markets
    pass, freshness-gated (``interval_days``) and airplane-gated (the guarded fetch
    refuses under the kill switch). No score; this only records WHAT to re-fetch.
    """

    __tablename__ = "stat_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # "worldbank" | "eurostat"
    # World Bank: indicator (+ country). Eurostat/SDMX: dataset (+ params_json + agency).
    indicator: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(24), nullable=True)
    dataset: Mapped[str | None] = mapped_column(String(120), nullable=True)
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    agency: Mapped[str | None] = mapped_column(String(40), nullable=True)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(200), nullable=True)  # "stored N" | error text

    __table_args__ = (
        # One subscription per distinct fetch (dedupe re-records of the same fetch).
        UniqueConstraint("source", "indicator", "country", "dataset", "params_json", "agency",
                         name="uq_stat_subscription"),
        Index("ix_stat_subscriptions_enabled", "enabled"),
    )

    def __repr__(self) -> str:
        key = self.indicator or self.dataset or "?"
        return f"<StatSubscription({self.source}:{key} every {self.interval_days}d)>"


class DerivedMeta(Base):
    """A tiny canonical key->value store coordinating the DERIVED layer with the
    canonical corpus (scaling 5A-bis / D3 corpus-epoch guard).

    Today it holds ONE key: the *corpus epoch* -- a monotonic counter bumped by exactly
    the non-append mutators (re-index / prune / restore-merge). The disposable columnar
    rollup (:func:`src.analytics.columnar.refresh_keyword_daily`) compares its BUILT epoch
    to this value; a change forces a FULL rebuild instead of an incremental merge, which
    is what defeats the delete-then-reinsert double-count trap: ``index_article`` deletes
    then re-inserts an article's mentions, so an id-watermark incremental merge would keep
    the OLD contribution in the rollup AND re-add the re-inserted higher-id rows. Normal
    new-article ingest does NOT bump the epoch (else every scrape pass would full-rebuild).

    It is a COORDINATION watermark for a disposable cache, never an analytic and never a
    score. Values are stored as TEXT (the epoch as a decimal string) for a schema-neutral,
    extensible key->value shape; the typed helpers live in
    :mod:`src.analytics.corpus_epoch`.
    """

    __tablename__ = "derived_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return f"<DerivedMeta({self.key}={self.value})>"


class AppState(Base):
    """The durable ``key -> value`` home for small config/UI state (DB-reliability D1).

    Replaces the loose JSON side-files (``app_settings.json``, ``scheduler_settings.json``,
    ``custody_settings.json``, ``safety_settings.json``) and the browser-only agenda
    subscription prefs: a JSON file is not transactional, is not in the encrypted store,
    and is absent from every backup. Each row holds ONE JSON blob per namespace key (e.g.
    ``settings.app``, ``settings.scheduler``, ``agenda.prefs``); the generic read/write
    primitive is :mod:`src.config.kv_store`, and each caller owns its own parse/validate.

    Deliberately NOT merged on restore (design D1 / T10: settings are per-machine — local
    wins entirely; incoming values are shown read-only for manual adoption), so it sits in
    ``_MERGE_IGNORED`` in :mod:`src.backup.merge`. It is a config store, never an analytic
    and never a score.
    """

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(191), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return f"<AppState({self.key})>"


class EventImport(Base):
    """One imported calendar EVENT, moved off the loose ``calendar_feed_imports.json``
    side-file into the encrypted corpus DB (DB-reliability D1: durable, transactional, and
    carried by a backup instead of sitting in cleartext beside the SQLCipher store).

    STATUS (Wave 4 J — conservative slice): this is the DURABLE TABLE + a DUAL-WRITE MIRROR.
    Every save of the imports store (:func:`src.events.feeds._save_json`) also writes here
    through :mod:`src.events.event_store`, so the table is a faithful encrypted mirror at all
    times — INCLUDING after an additive restore, because the side-file UNION-merge
    (``merge_imported_store``) itself ends in that same save. The legacy JSON remains the
    READ source of truth and the merge target, so behaviour is byte-unchanged and nothing
    regresses. Promoting reads to this table + a native UNION-merge handler (and retiring the
    JSON) is the deferred D1 follow-up; until then the table is registered in
    :data:`src.backup.merge._MERGE_IGNORED` (local wins) so a restore report stays clean.

    Keyed by ``(family_key, fingerprint)`` — the same calendar-family + normalized-title|date
    identity the side-file uses. No FK (a standalone config-style table, like ``app_state``),
    counts/facts only, never a score.
    """

    __tablename__ = "event_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_key: Mapped[str] = mapped_column(String(191), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    family_name: Mapped[str | None] = mapped_column(String(300))
    family_user: Mapped[bool | None] = mapped_column(Boolean, default=False)
    imported_at: Mapped[str | None] = mapped_column(String(40))  # ISO string, family-level
    title: Mapped[str | None] = mapped_column(String(300))
    date: Mapped[str | None] = mapped_column(String(20))  # yyyy-mm-dd, date-only precision
    sources: Mapped[str | None] = mapped_column(Text)  # JSON array of feed ids (union)
    uids: Mapped[str | None] = mapped_column(Text)  # JSON array of ICS UIDs (union)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_event_imports_family_fp", "family_key", "fingerprint", unique=True),
    )

    def __repr__(self) -> str:
        return f"<EventImport({self.family_key}:{self.fingerprint})>"


# Example usage
if __name__ == "__main__":
    # Test database connection and table creation
    init_db()
    session = get_session()

    # Check if tables exist
    from sqlalchemy.inspection import inspect

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"Tables in database: {tables}")

    session.close()
    print("Database setup complete. Tables created if they didn't exist.")
