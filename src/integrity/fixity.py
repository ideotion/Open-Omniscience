"""Local fixity audit — reliable-memory turned inward (audit-07 finding B2).

The project's deepest stated intention is a memory that cannot be silently
rewritten. This is that promise checked against the *local* store: re-hash each
stored article body with the canonical content hash and compare it to the hash
recorded at ingest. A mismatch means the stored content no longer hashes to its
recorded value — evidence of tampering or bit-rot in the corpus — surfaced
**loudly**, with the offending ids, never hidden behind a "health" number.

Honesty by construction:
- **No score.** The result is a *count* of mismatches plus the exact offending
  rows (stored vs recomputed hash); there is no composite "integrity" number.
- **Stated limits.** The dedup content hash normalises whitespace, so a
  whitespace-ONLY edit is not detectable here — said plainly in the caveat.
- **Never silently "ok".** Articles with empty content or no stored hash have
  nothing to verify; they are counted in their own buckets, not folded into the
  verified-ok tally.
- **Bounded.** A window (offset/limit) is checked so a huge corpus cannot hang
  the request; ``total_articles`` is reported so the operator can page through.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.models import Article
from src.utils.url_utils import generate_content_hash

_METHOD = (
    "Re-hash each article body with the canonical content hash "
    "(whitespace-normalised SHA-256, the same function used at ingest) and compare "
    "to the stored hash. A mismatch = the stored content no longer hashes to its "
    "recorded value (tampering or bit-rot in the local store), surfaced loudly with "
    "the offending ids. No score — a count and the exact rows."
)
_CAVEAT = (
    "Whitespace-only edits are NOT detectable (the content hash normalises "
    "whitespace by construction of the dedup function). Articles with empty content "
    "or no stored hash have nothing to verify and are counted separately, never "
    "treated as verified-ok. A bounded window (offset/limit) is checked; page "
    "through total_articles to cover the whole corpus."
)


def audit_fixity(db: Session, *, limit: int = 2000, offset: int = 0) -> dict:
    """Re-hash a window of the corpus and report any fixity mismatch.

    Returns a JSON-able dict: totals, the verified/mismatched/skipped buckets, the
    exact mismatching rows (article_id, url, stored_hash, recomputed_hash), and the
    method + caveat. Read-only; no score.
    """
    total = int(db.query(func.count(Article.id)).scalar() or 0)
    rows = (
        db.query(Article.id, Article.url, Article.hash, Article.content)
        .order_by(Article.id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    checked = 0
    skipped_no_content = 0
    skipped_no_stored_hash = 0
    mismatches: list[dict] = []
    for aid, url, stored, content in rows:
        if not content:
            skipped_no_content += 1
            continue
        if not stored:
            skipped_no_stored_hash += 1
            continue
        checked += 1
        recomputed = generate_content_hash(content)
        if recomputed != stored:
            mismatches.append(
                {
                    "article_id": aid,
                    "url": url,
                    "stored_hash": stored,
                    "recomputed_hash": recomputed,
                }
            )

    return {
        "total_articles": total,
        "window": {"offset": offset, "limit": limit, "returned": len(rows)},
        "checked": checked,
        "verified_ok": checked - len(mismatches),
        "mismatched": len(mismatches),
        "skipped_no_content": skipped_no_content,
        "skipped_no_stored_hash": skipped_no_stored_hash,
        "mismatches": mismatches,
        "method": _METHOD,
        "caveat": _CAVEAT,
    }
