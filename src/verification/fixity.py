"""
Local fixity audit -- "reliable memory turned inward".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A LOCAL, read-only integrity check: re-hash every stored article's content with
the *same* function its ingest path used at capture time (the scraper's
``src.utils.url_utils.generate_content_hash``, or the law/Wikipedia/statistics
and hazard writers' own formulas -- see ``HASH_KINDS``), and compare the
recomputed digest against the ``Article.hash`` column recorded when the row was
first stored.

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

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import Article, Source
from src.utils.url_utils import generate_content_hash

# THE HASH KINDS (FIX-1, field round 2026-09-24). Four ingest paths write
# ``Article.hash``, with three different formulas -- and the audit used to re-hash
# every row with the scraper's, so it reported 22 % and 29 % of two field corpora as
# "mismatched": every hazard row and every law page, none of them altered. The
# ingest hashes are dedup keys and are left alone; the AUDIT learns each writer's
# formula instead.
#
#   normalised  -- the scrape pipeline: generate_content_hash (whitespace-normalised
#                  SHA-256), the only kind that existed when this audit was written;
#   raw         -- law, Wikipedia and official statistics: SHA-256 of the text as
#                  stored (src/law/corpus.py, src/wiki/corpus.py,
#                  src/stats/series_corpus.py);
#   url+content -- hazards: SHA-256 of "<url>\n<body>", so two events with identical
#                  prose cannot collide on the hash's unique index (src/hazards/ingest.py).
HASH_KINDS: dict[str, Callable[[str, str], str]] = {
    "normalised": lambda url, content: generate_content_hash(content),
    "raw": lambda url, content: hashlib.sha256(content.encode()).hexdigest(),
    "url+content": lambda url, content: hashlib.sha256(f"{url}\n{content}".encode()).hexdigest(),
}


def expected_hash_kind(url: str | None, domain: str | None, source_type: str | None) -> str:
    """Which writer's formula a row SHOULD hash under, from where it came from: the
    synthetic ``*.local`` domains the non-web writers mint for themselves (and the
    ``hazard://`` / ``statistics://`` URL schemes), and the Wikipedia edition domains.
    A scraped page is ``normalised``."""
    u = (url or "").lower()
    d = (domain or "").lower()
    st = (source_type or "").lower()
    if u.startswith("hazard://") or st == "hazard" or (d.startswith("hazard.") and d.endswith(".local")):
        return "url+content"
    if (u.startswith("statistics://") or st in ("legal", "statistics")
            or (d.endswith(".local") and (d.startswith("law.") or d.startswith("statistics.")))
            or d.endswith(".wikipedia.org")):
        return "raw"
    return "normalised"


# A human-readable, exact description of what this audit compares. Surfaced in the
# response so the UI (and any export) can state the method verbatim -- honesty by
# construction. If a hashing function ever changes, this string must change too.
METHOD = (
    "Re-hash each stored Article.content with the formula of the ingest path that wrote "
    "it -- 'normalised' (the scraper's generate_content_hash: whitespace-normalised "
    "SHA-256), 'raw' (SHA-256 of the text as stored: law, Wikipedia, statistics) or "
    "'url+content' (SHA-256 of url, newline, body: hazards), chosen from the row's source "
    "-- and compare to the Article.hash recorded at capture time. A row that matches only "
    "under ANOTHER writer's formula is counted apart (matched_other_kind), never as a "
    "mismatch: that is a misclassified writer, not altered content. A mismatch means the "
    "stored content matches its capture-time hash under no known formula; nothing is "
    "auto-fixed."
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
    matched_other_kind = 0
    by_kind: dict[str, int] = dict.fromkeys(HASH_KINDS, 0)
    other_kind_examples: list[dict] = []
    mismatches: list[dict] = []

    # Only the columns we need -- avoid dragging compressed_content etc. through the
    # SQLCipher codec. ``content`` is required for the recompute; the source's domain
    # and type say which writer's formula applies (an outer join: a row whose source
    # is gone is still audited, under the scraper's formula).
    stmt = (
        select(
            Article.id,
            Article.url,
            Article.title,
            Article.content,
            Article.hash,
            Source.domain,
            Source.source_type,
        )
        .outerjoin(Source, Source.id == Article.source_id)
        .order_by(Article.id)
    )

    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)

    # Stream in batches so a large corpus is never fully materialised in memory.
    for row in session.execute(stmt.execution_options(yield_per=_BATCH)):
        checked += 1
        art_id, url, title, content, stored, domain, source_type = row
        kind = expected_hash_kind(url, domain, source_type)
        text = content or ""

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
                    "computed_hash": HASH_KINDS[kind](url or "", text),
                    "hash_kind": kind,
                    "reason": "no stored hash recorded for this row",
                }
            )
            continue

        computed = HASH_KINDS[kind](url or "", text)
        if computed == stored_hash:
            ok += 1
            by_kind[kind] += 1
            continue
        # Not under its expected writer's formula: try the others before calling it a
        # mismatch. A match there is a MISCLASSIFIED writer (a scraped page on a
        # Wikipedia domain, say), which is named and counted -- a preimage under a
        # second formula is not something altered content can produce.
        other = next((k for k, fn in HASH_KINDS.items() if k != kind and fn(url or "", text) == stored_hash), None)
        if other is not None:
            ok += 1
            matched_other_kind += 1
            by_kind[other] += 1
            if len(other_kind_examples) < 20:
                other_kind_examples.append({"id": art_id, "url": url, "expected_kind": kind, "matched_kind": other})
            continue
        mismatched += 1
        mismatches.append(
            {
                "id": art_id,
                "url": url,
                "title": title,
                "stored_hash": stored_hash,
                "computed_hash": computed,
                "hash_kind": kind,
                "reason": "stored content matches its capture-time hash under no known ingest formula",
            }
        )

    return {
        "checked": checked,
        "ok": ok,
        "mismatched": mismatched,
        "missing_hash": missing_hash,
        "by_hash_kind": by_kind,
        "matched_other_kind": matched_other_kind,
        "matched_other_kind_examples": other_kind_examples,
        "mismatches": mismatches,
        "method": METHOD,
        "computed_at": datetime.now(UTC).isoformat(),
    }
