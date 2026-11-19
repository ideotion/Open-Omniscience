"""The medical lane's own tables in ``medical.db`` (0.7 gate row A, brief S07-01 S1; R745, R746).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ARCHITECTURALLY SEPARATE, AS RULED (2026-07-14, V1 pathway §4.2): PubMed's records are their own
managed dataset with their own storage, never blended into news. They live in ``medical.db``
beside ``corpus.db``, through the versioned-source substrate (Q1003 = a), encrypted with the same
passphrase through the ONE keyed factory; nothing here ever reaches ``corpus.db``. These tables
reach the file ONLY through ``src.versioned.store.create_schema``
(``_lane_specific_models("medical")``), so no other lane's file gets them.

WHAT IS KEPT (R745): only the records the user's corpus cites (by PMID, DOI or PMCID) or the user
names. A bulk update file is the TRANSPORT; after the match pass the rest of it is dropped, and
the ~38 M-record baseline is never ingested whole. ``medical_wanted`` holds the ids the user
named; the corpus-cited ids are read from the corpus at match time and are never copied here.

BACKUPS (R746): ``medical.db`` is a "waiting" lane: a backup does not carry it yet, the backup
view says so, and every kept record can be fetched again from NLM.

FOUR TABLES.

* ``medical_papers`` -- one row per (PMID, version) kept: the parser's fields, the provenance
  class read from the record, the status links, and which file last stated it. A withdrawal
  (an update file's ``DeleteCitation``) is a MARK (``withdrawn_at``), never a deletion: the
  record was in PubMed and the user's corpus may cite it.
* ``medical_class_changes`` -- one row each time a kept record's provenance class changed between
  two files (journal -> retracted is the one that matters). The date a paper BECAME retracted in
  this install's copy is a fact the surface shows; overwriting the class would lose it.
* ``medical_wanted`` -- the ids the user named, with when.
* ``medical_files`` -- one row per update or baseline file processed: its name, size, hash, the
  parser's tally, what was kept, and whether the pass finished. A file whose pass did not finish
  says so, and nothing reads it as complete.

NO SCORES, NO ADVICE. No column holds a quality, trust or relevance number, and nothing here
interprets a paper. ``journal`` is "a record PubMed indexes as a journal publication": peer review
is the journal's claim, never verified here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.versioned.models import LaneBase, LaneCompressedText, LaneUTCDateTime

#: Identifier kinds a user may name, and the corpus may cite.
WANTED_KINDS = ("pmid", "doi", "pmcid")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MedicalPaper(LaneBase):
    """One kept PubMed record, at one version."""

    __tablename__ = "medical_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pmid: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    citation_status: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(Text)
    vernacular_title: Mapped[str | None] = mapped_column(Text)
    #: JSON list of ``[label, text]`` sections, compressed. NULL = the record carries no abstract (a gap).
    abstract_json: Mapped[str | None] = mapped_column(LaneCompressedText)
    abstract_copyright: Mapped[str | None] = mapped_column(Text)
    journal: Mapped[str | None] = mapped_column(String(512))
    #: As precise as the record: "2024", "2024-03" or "2024-03-05". NULL when only free text exists.
    pub_date: Mapped[str | None] = mapped_column(String(10))
    pub_date_text: Mapped[str | None] = mapped_column(String(128))
    #: JSON lists (languages, publication types, MeSH descriptors, keywords).
    languages_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    publication_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    mesh_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: Lower-cased for matching; DOIs are case-insensitive by the DOI handbook.
    doi: Mapped[str | None] = mapped_column(String(300))
    pmcid: Mapped[str | None] = mapped_column(String(16))
    #: ``journal`` | ``preprint`` | ``retracted`` (``src.medical.pubmed_xml.CLASSES``).
    provenance_class: Mapped[str] = mapped_column(String(16), nullable=False)
    notice_kind: Mapped[str | None] = mapped_column(String(32))
    #: JSON list of ``[ref_type, pmid_or_null, source_text_or_null]``.
    status_links_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    text_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: The file that last stated this record, and when this install read it.
    source_file: Mapped[str] = mapped_column(String(128), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    #: Set when an update file withdrew the PMID; the row stays, marked.
    withdrawn_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    withdrawn_in_file: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        UniqueConstraint("pmid", "version", name="uq_medical_paper_pmid_version"),
        Index("ix_medical_paper_doi", "doi"),
        Index("ix_medical_paper_pmcid", "pmcid"),
        Index("ix_medical_paper_class", "provenance_class"),
    )


class MedicalClassChange(LaneBase):
    """A kept record's provenance class changed between two files."""

    __tablename__ = "medical_class_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pmid: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    from_class: Mapped[str] = mapped_column(String(16), nullable=False)
    to_class: Mapped[str] = mapped_column(String(16), nullable=False)
    source_file: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_medical_class_change_pmid", "pmid", "version"),)


class MedicalWanted(LaneBase):
    """An identifier the user named, so its record is kept when a file carries it."""

    __tablename__ = "medical_wanted"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: One of ``WANTED_KINDS``.
    id_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Normalised by ``src.medical.store.normalise_id``.
    value: Mapped[str] = mapped_column(String(300), nullable=False)
    added_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)

    __table_args__ = (UniqueConstraint("id_kind", "value", name="uq_medical_wanted"),)


class MedicalCited(LaneBase):
    """An identifier the user's corpus cites, as the last fetch found it (R745's other half).

    Rebuilt whole by each fetch from a read-only scan of the corpus's outbound links, so it is a
    snapshot, never a history: what it holds is what the corpus cited when the last fetch ran. It
    is kept here, in the lane, so the status the UI shows (how many cited papers were found, and
    how many were not) is a read of this file alone, never a scan of the corpus.
    """

    __tablename__ = "medical_cited"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: One of ``WANTED_KINDS``.
    id_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Normalised by ``src.medical.store.normalise_id``.
    value: Mapped[str] = mapped_column(String(300), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)

    __table_args__ = (UniqueConstraint("id_kind", "value", name="uq_medical_cited"),)


class MedicalFile(LaneBase):
    """One NLM file this install processed, and what the pass kept from it."""

    __tablename__ = "medical_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: NLM's own file name (``pubmed25n1300.xml.gz``), never a path on this machine.
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(LaneUTCDateTime)
    #: ``running`` | ``finished`` | ``failed``. A failed pass names its error class in ``error``.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    error: Mapped[str | None] = mapped_column(String(128))
    articles_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deletions_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    books_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: JSON object: reason -> count, from the parser's tally.
    skipped_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    kept: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    withdrawn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Statements and deletions this file made that a NEWER file had already overtaken, so were not applied.
    older_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_medical_file_name", "name"),)


#: ``medical.db`` ONLY, exactly as ``LAW_LANE_MODELS`` go to ``law.db`` only.
MEDICAL_LANE_MODELS: tuple[type[LaneBase], ...] = (
    MedicalPaper,
    MedicalClassChange,
    MedicalWanted,
    MedicalCited,
    MedicalFile,
)
