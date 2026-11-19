"""The medical lane's store: what is kept from a parsed NLM file, and how (S07-01 S1; R745, R746).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R745 IS THIS MODULE'S CONTRACT. A bulk file is the TRANSPORT; a record is KEPT only when its PMID,
DOI or PMCID is in the wanted set (the ids the user's corpus cites, gathered by the caller, plus
the ids the user named in ``medical_wanted``). Everything else in the file is dropped after the
pass, so a large download stores little; the baseline is never ingested whole.

It never touches the network and never reads the corpus: the caller hands it a parsed stream and
the corpus-cited ids. That is what lets every rule here be tested against a fixture with nothing
else running.

WHAT A PASS DOES TO A KEPT RECORD.
* New (PMID, version): inserted, with the file that stated it.
* Seen before: its fields are replaced by the newer file's, because NLM re-issues a record when it
  changes it -- and if the PROVENANCE CLASS changed (journal -> retracted is the case that
  matters), a ``medical_class_changes`` row records it with the file, so the date a paper became
  retracted in this install's copy is never lost to the overwrite.
* Withdrawn (``DeleteCitation``): the row is MARKED, never removed; the corpus may cite it.

A pass that fails leaves its ``medical_files`` row ``failed`` with the error's class, and every
kept change it made is rolled back with it: one file is one transaction, so a half-applied file
never reads as applied.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.medical.lane_models import (
    WANTED_KINDS,
    MedicalClassChange,
    MedicalFile,
    MedicalPaper,
    MedicalWanted,
)
from src.medical.pubmed_xml import ParseTally, PubmedDeletion, PubmedRecord

LANE = "medical"

_PMID = re.compile(r"[1-9][0-9]{0,9}")
_PMCID = re.compile(r"PMC[1-9][0-9]{0,9}")
#: NLM's own file names: ``pubmed25n0001.xml.gz`` (baseline) or ``pubmed25n1300.xml.gz`` (update).
FILE_NAME = re.compile(r"pubmed([0-9]{2})n([0-9]{4})\.xml(\.gz)?")


def file_sequence(name: str) -> tuple[int, int]:
    """(release year, file number) of an NLM file: the order NLM published them in.

    A later file states a record as NLM holds it LATER, so an older file applied after a newer
    one (a baseline re-scanned for a newly named id, say) may add records the store lacks but may
    never overwrite or withdraw one a newer file stated. ``(-1, -1)`` for a name that is not
    NLM's (only ``record_failed_file`` stores one), so it never outranks a real file.
    """
    m = FILE_NAME.fullmatch(name or "")
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def normalise_id(kind: str, value: str) -> str:
    """One spelling per identifier, or ``ValueError`` naming what is wrong.

    A DOI is case-insensitive (DOI handbook §2.4) and is written in many URL forms; a PMCID keeps
    its ``PMC`` prefix; a PMID is digits. The same function serves the user's input and the
    corpus's citations, so the two can only ever be compared in one spelling.
    """
    if kind not in WANTED_KINDS:
        raise ValueError(f"unknown identifier kind {kind!r}; known kinds are {', '.join(WANTED_KINDS)}")
    v = (value or "").strip()
    if kind == "pmid":
        if not _PMID.fullmatch(v):
            raise ValueError("a PMID is a whole number")
        return v
    if kind == "pmcid":
        v = v.upper()
        if not v.startswith("PMC"):
            v = "PMC" + v
        if not _PMCID.fullmatch(v):
            raise ValueError("a PMCID is PMC followed by digits")
        return v
    low = v.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if low.startswith(prefix):
            low = low[len(prefix) :]
            break
    if not (low.startswith("10.") and "/" in low) or len(low) > 300 or any(c.isspace() for c in low):
        raise ValueError("a DOI starts with 10. and has a / in it")
    return low


@dataclass
class Wanted:
    """The ids a pass keeps, each already through :func:`normalise_id`."""

    pmid: set[str] = field(default_factory=set)
    doi: set[str] = field(default_factory=set)
    pmcid: set[str] = field(default_factory=set)

    def add(self, kind: str, value: str) -> None:
        getattr(self, kind).add(normalise_id(kind, value))

    def matches(self, rec: PubmedRecord) -> bool:
        if str(rec.pmid) in self.pmid:
            return True
        if rec.doi and rec.doi.lower() in self.doi:
            return True
        return bool(rec.pmcid and rec.pmcid in self.pmcid)

    def __len__(self) -> int:
        return len(self.pmid) + len(self.doi) + len(self.pmcid)


def add_wanted(session: Session, kind: str, value: str) -> str:
    """Name an id to keep. Returns its normalised form; naming it twice is not an error."""
    norm = normalise_id(kind, value)
    exists = session.execute(
        select(MedicalWanted.id).where(MedicalWanted.id_kind == kind, MedicalWanted.value == norm)
    ).first()
    if exists is None:
        session.add(MedicalWanted(id_kind=kind, value=norm))
        session.flush()
    return norm


def remove_wanted(session: Session, kind: str, value: str) -> bool:
    """Stop naming an id. The record already kept stays: removing a wish is not deleting a paper."""
    norm = normalise_id(kind, value)
    row = session.execute(
        select(MedicalWanted).where(MedicalWanted.id_kind == kind, MedicalWanted.value == norm)
    ).scalar_one_or_none()
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def user_wanted(session: Session) -> Wanted:
    out = Wanted()
    for kind, value in session.execute(select(MedicalWanted.id_kind, MedicalWanted.value)):
        getattr(out, kind).add(value)
    return out


def _now() -> datetime:
    return datetime.now(UTC)


def _fields(rec: PubmedRecord) -> dict:
    return {
        "citation_status": rec.citation_status,
        "title": rec.title,
        "vernacular_title": rec.vernacular_title,
        "abstract_json": (
            json.dumps([[s.label, s.text] for s in rec.abstract], ensure_ascii=False) if rec.abstract is not None else None
        ),
        "abstract_copyright": rec.abstract_copyright,
        "journal": (rec.journal or None) and rec.journal[:512],
        "pub_date": rec.pub_date,
        "pub_date_text": (rec.pub_date_text or None) and rec.pub_date_text[:128],
        "languages_json": json.dumps(list(rec.languages)),
        "publication_types_json": json.dumps(list(rec.publication_types), ensure_ascii=False),
        "mesh_json": json.dumps(list(rec.mesh), ensure_ascii=False),
        "keywords_json": json.dumps(list(rec.keywords), ensure_ascii=False),
        "doi": rec.doi.lower() if rec.doi else None,
        "pmcid": rec.pmcid,
        "provenance_class": rec.provenance_class,
        "notice_kind": rec.notice_kind,
        "status_links_json": json.dumps([[lk.ref_type, lk.pmid, lk.source] for lk in rec.status_links], ensure_ascii=False),
        "text_truncated": rec.text_truncated,
    }


def apply_file(
    session: Session,
    name: str,
    items: Iterable[PubmedRecord | PubmedDeletion],
    tally: ParseTally,
    wanted: Wanted,
    *,
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> dict:
    """Keep the wanted records of one parsed file, mark the withdrawals of kept ones, record the file.

    ``items`` is the parser's stream (``parse_pubmed``); ``tally`` the same tally object the parser
    is filling, read after the stream is exhausted. The caller owns the transaction: on any
    exception nothing here was committed, and the caller records the file as failed with
    :func:`record_failed_file` in a transaction of its own.
    """
    if not FILE_NAME.fullmatch(name):
        raise ValueError("not an NLM PubMed file name")
    seq = file_sequence(name)
    kept = updated = withdrawn = older_skipped = 0
    for item in items:
        if isinstance(item, PubmedDeletion):
            # The withdrawn VERSION only: a deletion of version 2 leaves version 1 as it was.
            rows = session.execute(
                select(MedicalPaper).where(
                    MedicalPaper.pmid == item.pmid,
                    MedicalPaper.version == item.version,
                    MedicalPaper.withdrawn_at.is_(None),
                )
            ).scalars()
            for gone in rows:
                if file_sequence(gone.source_file) > seq:
                    older_skipped += 1  # a newer file stated it after this withdrawal
                    continue
                gone.withdrawn_at = _now()
                gone.withdrawn_in_file = name
                withdrawn += 1
            continue
        if not wanted.matches(item):
            continue  # R745: the rest of the file is the transport, never the store.
        row = session.execute(
            select(MedicalPaper).where(MedicalPaper.pmid == item.pmid, MedicalPaper.version == item.version)
        ).scalar_one_or_none()
        values = _fields(item)
        if row is None:
            session.add(MedicalPaper(pmid=item.pmid, version=item.version, source_file=name, **values))
            # Flushed at once: the lane's sessions do not autoflush, and the same record stated
            # again later in this file, or withdrawn later in it, must find this row, not insert
            # a second one that breaks the unique key and loses the whole pass.
            session.flush()
            kept += 1
            continue
        if file_sequence(row.source_file) > seq:
            older_skipped += 1  # an older file never overwrites what a newer one stated
            continue
        if row.provenance_class != item.provenance_class:
            session.add(
                MedicalClassChange(
                    pmid=item.pmid,
                    version=item.version,
                    from_class=row.provenance_class,
                    to_class=item.provenance_class,
                    source_file=name,
                )
            )
        for key, value in values.items():
            setattr(row, key, value)
        row.source_file = name
        row.last_seen_at = _now()
        # A record a later file states again is no longer withdrawn: NLM put it back.
        row.withdrawn_at = None
        row.withdrawn_in_file = None
        updated += 1
    session.add(
        MedicalFile(
            name=name,
            size_bytes=size_bytes,
            sha256=sha256,
            finished_at=_now(),
            status="finished",
            articles_read=tally.articles,
            deletions_read=tally.deletions,
            books_skipped=tally.books_skipped,
            skipped_json=json.dumps(tally.skipped, sort_keys=True),
            kept=kept,
            updated=updated,
            withdrawn=withdrawn,
        )
    )
    session.flush()
    return {
        "file": name,
        "read": tally.articles,
        "kept": kept,
        "updated": updated,
        "withdrawn": withdrawn,
        "older_skipped": older_skipped,
    }


def record_failed_file(session: Session, name: str, exc: BaseException) -> None:
    """A pass that did not finish says so; its kept changes were rolled back with it."""
    session.add(
        MedicalFile(
            name=name if FILE_NAME.fullmatch(name) else "unnamed",
            status="failed",
            error=type(exc).__name__[:128],
            finished_at=_now(),
        )
    )
    session.flush()


def summary(session: Session) -> dict:
    """Counts per provenance class, withdrawn, and the newest finished file. Local only."""
    from sqlalchemy import func

    by_class: dict[str, int] = {
        str(k): int(n)
        for k, n in session.execute(
            select(MedicalPaper.provenance_class, func.count()).group_by(MedicalPaper.provenance_class)
        ).all()
    }
    last = session.execute(
        select(MedicalFile.name, MedicalFile.finished_at)
        .where(MedicalFile.status == "finished")
        .order_by(MedicalFile.finished_at.desc(), MedicalFile.id.desc())
        .limit(1)
    ).first()
    return {
        "papers": sum(by_class.values()),
        "by_class": {k: int(by_class.get(k, 0)) for k in ("journal", "preprint", "retracted")},
        "withdrawn": int(
            session.execute(select(func.count()).select_from(MedicalPaper).where(MedicalPaper.withdrawn_at.is_not(None))).scalar()
            or 0
        ),
        "wanted_named": int(session.execute(select(func.count()).select_from(MedicalWanted)).scalar() or 0),
        "last_file": ({"name": last[0], "finished_at": last[1].isoformat()} if last else None),
    }
