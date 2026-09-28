"""Point-in-time search over law versions (Q916 = a; Q905 = a; Q908 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q916 = a, verbatim: «FTS over versions with ``valid_on``, so "what did this say in 2019"
works without an Article per version.» So the index is over VERSIONS, never over corpus
articles: a law's corpus Article carries its newest text only, and minting an Article per
version would put superseded statutes into every corpus search as if they were current.

WHERE THE INDEX LIVES. In ``law.db``, beside the provisions, as a CONTENTLESS FTS5 table
(the texts already live compressed in ``corpus.db``; a second copy would triple the law
corpus) plus a small key table naming, per indexed row, the revision's minted
``lane_key``. The key is the string, not the corpus row id, for the reason
``src/law/lane_models.py`` states: a backup merge renumbers ``law_revisions``, and an
integer link would attach one version's words to another. An index row whose revision no
longer exists matches nothing, because every hit is joined back to ``corpus.db`` before it
is returned.

THE ANSWER IS "IN FORCE ON THAT DAY, AMONG THE VERSIONS THIS INSTANCE HOLDS". A hit is a
version that contains the words AND is the version ``src.law.versions.in_force_on`` places
on the asked-for day — the ONE dating rule the reader also uses, so the version a search
names is the version the reader shows for that day. A day before the earliest held version
answers "not held", never the oldest text. Each hit carries how its date was determined
(Q905's label), and the coverage says how many versions could not be searched because
their text was never stored.

THE INDEX IS DERIVED AND CATCHES UP ON READ. ``sync_index`` adds every held version with
a stored text that the key table does not name yet, bounded per call; the payload says
how many are still pending, so a partial index is reported rather than presented as the
whole.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text as sql

from src.database.models import LawDocument, LawRevision
from src.law.versions import effective_versions, in_force_on

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

#: Versions indexed per call at most; the rest are reported as pending and indexed on
#: the next read. Bounded because a read must stay a read-sized amount of work.
SYNC_BATCH = 200

#: Hits returned at most; ``matched`` counts all of them.
MAX_HITS = 100

_DDL = (
    "CREATE TABLE IF NOT EXISTS law_version_index ("
    " id INTEGER PRIMARY KEY,"
    " revision_key TEXT NOT NULL UNIQUE,"
    " indexed_at TEXT NOT NULL)",
    # Contentless: the words are matched here and read back from corpus.db. The same
    # tokenizer the article index uses, so a query behaves the same in both boxes.
    "CREATE VIRTUAL TABLE IF NOT EXISTS law_version_fts USING fts5("
    " title, body, content='', tokenize='unicode61 remove_diacritics 2')",
)

_TOKEN = re.compile(r'"[^"]+"|\S+')


def match_expression(query: str) -> str | None:
    """A safe FTS5 expression: every word or "quoted phrase" required, a trailing ``*``
    kept as a prefix. Operators are not interpreted — this box answers "which versions
    contain these words", and a stray ``NOT`` or ``(`` must not become syntax."""
    terms = []
    for tok in _TOKEN.findall(query or ""):
        prefix = tok.endswith("*") and not tok.startswith('"')
        core = tok.strip('"').rstrip("*").replace('"', " ").strip()
        if not core:
            continue
        terms.append(f'"{core}"' + ("*" if prefix else ""))
    return " ".join(terms) or None


def _words(query: str) -> list[str]:
    return [w.strip('"').rstrip("*").casefold() for w in _TOKEN.findall(query or "") if w.strip('"*')]


def snippet(text: str | None, query: str, width: int = 110) -> str:
    """A window around the first query word found in the text — computed, never stored."""
    body = " ".join((text or "").split())
    folded = body.casefold()
    at = -1
    for w in _words(query):
        at = folded.find(w)
        if at >= 0:
            break
    if at < 0:
        return body[: 2 * width] + ("…" if len(body) > 2 * width else "")
    start = max(0, at - width)
    end = min(len(body), at + width)
    return ("…" if start else "") + body[start:end] + ("…" if end < len(body) else "")


def _ensure_schema(lane: Session) -> None:
    for stmt in _DDL:
        lane.execute(sql(stmt))


def sync_index(db: Session, lane: Session, *, batch: int = SYNC_BATCH) -> dict:
    """Index held versions not indexed yet. Returns the coverage, pending included."""
    _ensure_schema(lane)
    done = {k for (k,) in lane.execute(sql("SELECT revision_key FROM law_version_index"))}
    candidates = (
        db.query(LawRevision.id, LawRevision.lane_key)
        .filter(LawRevision.full_text.isnot(None), LawRevision.lane_key.isnot(None))
        .order_by(LawRevision.id.asc())
        .all()
    )
    todo = [(rid, key) for rid, key in candidates if key not in done]
    now = datetime.now(UTC).isoformat()
    added = 0
    for rid, key in todo[:batch]:
        rev = db.get(LawRevision, rid)
        if rev is None or rev.full_text is None:
            continue
        doc = db.get(LawDocument, rev.document_id)
        row = lane.execute(
            sql("INSERT OR IGNORE INTO law_version_index(revision_key, indexed_at) VALUES (:k, :t)"),
            {"k": key, "t": now},
        )
        if not row.rowcount:
            continue  # another pass indexed it between our read and this write
        lane.execute(
            sql("INSERT INTO law_version_fts(rowid, title, body) VALUES (:r, :title, :body)"),
            {"r": row.lastrowid, "title": (doc.title if doc else "") or "", "body": rev.full_text},
        )
        added += 1
    lane.commit()
    total = db.query(LawRevision.id).count()
    # Two reasons a version cannot be searched, counted together because the reader's
    # next step is the same: its text was never stored, or it carries no minted key to
    # index it under (a row older than the key; an integer id would not survive a merge).
    without_text = (
        db.query(LawRevision.id)
        .filter((LawRevision.full_text.is_(None)) | (LawRevision.lane_key.is_(None)))
        .count()
    )
    return {
        "versions_total": total,
        "versions_searchable": len(done) + added,
        "versions_pending": max(0, len(todo) - added),
        "versions_without_text": without_text,
        "added_now": added,
    }


def _siblings(db: Session, doc: LawDocument, cache: dict) -> list[dict]:
    """The other language versions of the same law this instance tracks (Q908)."""
    key = getattr(doc, "lane_key", None)
    if not key:
        return []
    if key in cache:
        return cache[key]
    out: list[dict] = []
    try:
        from src.law.model import group_for_lane_key
        from src.versioned.store import lane_session

        with lane_session("law") as lane:
            group = group_for_lane_key(lane, key)
            members = [(m.lane_key, m.language) for m in group.members] if group else []
        others = [k for k, _ in members if k != key]
        ids = {
            d.lane_key: d.id
            for d in db.query(LawDocument).filter(LawDocument.lane_key.in_(others)).all()
        } if others else {}
        out = [{"language": lang, "id": ids.get(k)} for k, lang in members if k != key]
    except Exception:  # noqa: BLE001 - the group is an addition to a hit, never its gate
        _LOG.debug("pit search: identity group unavailable for %s", doc.id, exc_info=True)
    cache[key] = out
    return out


def search(
    db: Session,
    query: str,
    *,
    on: str | None = None,
    language: str | None = None,
    limit: int = MAX_HITS,
) -> dict:
    """Versions containing the words, in force on ``on`` (``YYYY-MM-DD``) when given."""
    method = (
        "Full-text search over every version of every tracked law whose text this "
        "instance stored. With a date, a version counts only if it is the one in force "
        "on that day among the versions held here: placed by the date its source "
        "states, or by the day it was observed where the source states none."
    )
    caveat = (
        "A research mirror, not legal advice. A version published between two captures "
        "is not held, so the text in force on a day may be one this instance never saw. "
        "Scripts written without spaces between words (Chinese, Japanese) match only "
        "whole runs of text."
    )
    base = {"query": query, "on": on, "language": language, "method": method, "caveat": caveat}
    expr = match_expression(query)
    if expr is None:
        return base | {"status": "empty-query", "hits": [], "matched": 0, "documents": 0}
    from src.versioned.store import lane_exists, lane_session

    if not lane_exists("law"):
        return base | {
            "status": "no-lane",
            "reason": "No law has been tracked on this install yet, so there is nothing to search.",
            "hits": [],
            "matched": 0,
            "documents": 0,
        }
    with lane_session("law") as lane:
        coverage = sync_index(db, lane)
        keys = [
            k
            for (k,) in lane.execute(
                sql(
                    "SELECT i.revision_key FROM law_version_fts f"
                    " JOIN law_version_index i ON i.id = f.rowid"
                    " WHERE law_version_fts MATCH :q"
                ),
                {"q": expr},
            )
        ]
    if not keys:
        return base | {"status": "ok", "hits": [], "matched": 0, "documents": 0, "coverage": coverage}
    revs = db.query(LawRevision).filter(LawRevision.lane_key.in_(keys)).all()
    doc_ids = {r.document_id for r in revs}
    docs = {d.id: d for d in db.query(LawDocument).filter(LawDocument.id.in_(doc_ids)).all()}
    if language:
        docs = {i: d for i, d in docs.items() if (d.language or "").lower() == language.lower()}
    placed: dict[int, list] = {}
    for did in docs:
        rows = (
            db.query(LawRevision)
            .with_entities(
                LawRevision.id,
                LawRevision.lane_key,
                LawRevision.valid_on,
                LawRevision.valid_on_dating,
                LawRevision.observed_at,
            )
            .filter(LawRevision.document_id == did)
            .all()
        )
        placed[did] = effective_versions(rows)
    hits = []
    cache: dict = {}
    for rev in sorted(revs, key=lambda r: (r.document_id, r.id)):
        doc = docs.get(rev.document_id)
        if doc is None:
            continue
        versions = placed[rev.document_id]
        row = next((v for v in versions if v.revision_id == rev.id), None)
        if row is None:
            continue
        if on is not None:
            current = in_force_on(versions, on)
            if current is None or current.revision_id != rev.id:
                continue
        hits.append(
            {
                "document_id": doc.id,
                "title": doc.title,
                "jurisdiction": doc.jurisdiction,
                "language": doc.language,
                "version_id": rev.id,
                "valid_from": row.valid_from,
                "valid_to": row.valid_to,
                "partial": row.partial,
                "dating": row.dating,
                "current": row is versions[-1],
                "snippet": snippet(rev.full_text, query),
                "other_languages": _siblings(db, doc, cache),
                "reader_url": f"/api/law/documents/{doc.id}/view?version={rev.id}",
            }
        )
    return base | {
        "status": "ok",
        "matched": len(hits),
        "documents": len({h["document_id"] for h in hits}),
        "hits": hits[:limit],
        "truncated": len(hits) > limit,
        "coverage": coverage,
    }

