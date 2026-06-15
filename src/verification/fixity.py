"""
Local fixity audit -- "reliable memory turned inward".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A LOCAL, read-only integrity check: re-hash every stored article's content with
the *same* function the ingest pipeline used at capture time
(``src.utils.url_utils.generate_content_hash`` -> whitespace-normalise then
SHA-256), and compare the recomputed digest against the ``Article.hash`` column
recorded when the row was first stored.

This is tamper / bit-rot EVIDENCE. It is the inward-facing half of the
reliable-memory pillar: the corpus is a copy outside anyone's reach, and this
proves that copy still says what it said when it was captured. A divergence means
the stored ``content`` no longer hashes to the ``hash`` written at ingest -- the
row was altered after capture (by edit, corruption, or tampering) OR the hashing
inputs changed. Either way it is surfaced LOUDLY; NOTHING is auto-fixed. The
honest method string travels with every result so the UI can state exactly what
was compared.

Design notes / honesty:
  * We recompute against the EXACT stored function so a clean corpus reports zero
    mismatches by construction. ``generate_content_hash`` normalises whitespace
    (``" ".join(content.split())``) before SHA-256, so a row that differs only in
    whitespace will NOT be flagged -- that is the dedup contract the pipeline
    chose, and we report it faithfully rather than inventing a stricter rule.
  * ``Article.hash`` is ``NOT NULL`` in the schema, but we still count any row
    whose stored hash is absent/empty under ``missing_hash`` (degrade loudly,
    never assume).
  * Streaming / bounded: rows are read with ``yield_per`` so the whole corpus is
    never materialised in memory; an optional ``limit`` bounds the work.
  * No network, no writes. Takes a Session; pure with respect to the DB.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import Article
from src.utils.url_utils import generate_content_hash

# A human-readable, exact description of what this audit compares. Surfaced in the
# response so the UI (and any export) can state the method verbatim -- honesty by
# construction. If the hashing function ever changes, this string must change too.
METHOD = (
    "Re-hash each stored Article.content with the ingest function "
    "generate_content_hash (whitespace-normalised SHA-256, hex) and compare to the "
    "Article.hash recorded at capture time. A mismatch means the stored content no "
    "longer matches its capture-time hash; nothing is auto-fixed."
)

# How many rows to pull per round-trip when streaming the corpus.
_BATCH = 500


def audit_fixity(session: Session, limit: int | None = None) -> dict:
    """Re-hash stored articles and report any divergence from the capture-time hash.

    Args:
        session: An active SQLAlchemy session (read-only use here).
        limit: Optional cap on how many articles to check (newest-id-first is not
            implied -- rows are scanned in primary-key order for determinism). A
            ``None`` or non-positive value checks the whole corpus.

    Returns:
        A dict with::

            {
              "checked":      <int>,   # rows actually examined
              "ok":           <int>,   # recomputed hash == stored hash
              "mismatched":   <int>,   # recomputed hash != stored hash
              "missing_hash": <int>,   # row stored no usable hash to compare
              "mismatches":   [ {id, url, title, stored_hash, computed_hash}, ... ],
              "method":       "<exact description>",
              "computed_at":  "<ISO-8601 UTC>",
            }

        ``ok + mismatched + missing_hash == checked``. ``mismatches`` lists every
        divergent row (id always present); it is NOT truncated, because evidence
        of tampering must never be silently hidden.
    """
    checked = 0
    ok = 0
    mismatched = 0
    missing_hash = 0
    mismatches: list[dict] = []

    # Only the columns we need -- avoid dragging compressed_content etc. through the
    # SQLCipher codec. ``content`` is required for the recompute.
    stmt = select(
        Article.id,
        Article.url,
        Article.title,
        Article.content,
        Article.hash,
    ).order_by(Article.id)

    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)

    # Stream in batches so a large corpus is never fully materialised in memory.
    for row in session.execute(stmt.execution_options(yield_per=_BATCH)):
        checked += 1
        art_id, url, title, content, stored = row

        stored_hash = (stored or "").strip()
        if not stored_hash:
            # The schema marks hash NOT NULL, but never assume -- report loudly.
            missing_hash += 1
            mismatches.append(
                {
                    "id": art_id,
                    "url": url,
                    "title": title,
                    "stored_hash": None,
                    "computed_hash": generate_content_hash(content or ""),
                    "reason": "no stored hash recorded for this row",
                }
            )
            continue

        computed = generate_content_hash(content or "")
        if computed == stored_hash:
            ok += 1
        else:
            mismatched += 1
            mismatches.append(
                {
                    "id": art_id,
                    "url": url,
                    "title": title,
                    "stored_hash": stored_hash,
                    "computed_hash": computed,
                    "reason": "stored content no longer matches its capture-time hash",
                }
            )

    return {
        "checked": checked,
        "ok": ok,
        "mismatched": mismatched,
        "missing_hash": missing_hash,
        "mismatches": mismatches,
        "method": METHOD,
        "computed_at": datetime.now(UTC).isoformat(),
    }
