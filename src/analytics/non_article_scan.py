"""
Retroactive non-article SCAN (Slice 4a, review half) — the operator's REVIEW data before a
reversible quarantine of already-stored non-articles.

The #659 ingest filter stops nav/index/tag/tool/wall pages at the door going FORWARD; the corpus
scraped BEFORE it (the field bundle estimated ~42% of stored items) still holds them. This is the
COUNT-ONLY scan that quantifies the pollution per reason so the operator can review before acting.

COUNT-ONLY, no content decrypt: it classifies each article on its stored ``url`` + ``word_count``
(the small columns, the ``article_length_report`` scan pattern) via ``classify_non_article`` with
``text=None`` — so it applies the URL-SHAPE rules only (homepage / utility / pagination / taxonomy
/ section landing). The boilerplate-WALL rule needs the body, so this is a conservative UNDERCOUNT
(it never over-flags a real article). Read-only; the reversible QUARANTINE (never a silent delete)
is the operator's separate action.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

SCHEMA = "oo-non-article-scan-1"
_SAMPLE_PER_REASON = 20  # a bounded id sample per reason so the operator can spot-check


def scan_non_article_candidates(session: Session, *, sample_per_reason: int = _SAMPLE_PER_REASON) -> dict[str, Any]:
    """Count-only retroactive scan of stored articles for URL-shaped non-articles.

    Returns per-reason counts + a bounded id sample per reason, plus the honest method/caveat. NO
    content decrypt (reads ``id``/``url``/``word_count`` only). High-precision by design — it flags
    only CLEAR URL-shaped non-articles with a thin body, never a real article (conservative)."""
    from src.database.models import Article
    from src.ingest.non_article import classify_non_article

    by_reason: Counter[str] = Counter()
    human: dict[str, str] = {}
    samples: dict[str, list[int]] = {}
    scanned = 0
    flagged = 0
    for aid, url, wc in session.query(Article.id, Article.url, Article.word_count):
        scanned += 1
        verdict = classify_non_article(url or "", word_count=wc)  # text=None -> URL-shape rules only
        if verdict is None:
            continue
        flagged += 1
        by_reason[verdict.signal] += 1
        human.setdefault(verdict.signal, verdict.reason)
        s = samples.setdefault(verdict.signal, [])
        if len(s) < sample_per_reason:
            s.append(int(aid))

    return {
        "schema": SCHEMA,
        "scanned": scanned,
        "flagged": flagged,
        "pct_flagged": round(100.0 * flagged / scanned, 2) if scanned else 0.0,
        "by_reason": [
            {"signal": sig, "reason": human.get(sig, ""), "count": cnt, "sample_ids": samples.get(sig, [])}
            for sig, cnt in by_reason.most_common()
        ],
        "method": "COUNT-ONLY (id/url/word_count, no content decrypt) — the #659 classify_non_article "
                  "URL-shape rules only (text=None). A substantial stored word_count (>=100) is kept "
                  "whatever the URL; only a thin body proceeds to the URL rules.",
        "caveat": "A conservative UNDERCOUNT: the boilerplate-WALL rule needs the body (skipped here), "
                  "so consent/paywall/error walls with a normal word_count are NOT counted. "
                  "High-precision by design — never flags a real article. Read-only; the reversible "
                  "QUARANTINE (never a silent delete) is the operator action.",
        "reversible": True,
    }


def suspected_non_article_ids(session: Session, article_ids: list[int]) -> set[int]:
    """Non-article member exclusion seam (Leads-calibration S1.4, row 10).

    Which of the given article ids are SUSPECTED non-articles — the same conservative,
    high-precision ``classify_non_article`` URL-shape check the retroactive scan uses
    (:func:`scan_non_article_candidates`), scoped to a SPECIFIC member set instead of the
    whole corpus. For cluster-building producers (space-time convergence, weather
    corroboration, recycled-claim) to exclude homepage/section/utility captures from
    their evidence MEMBERS. Never a silent drop: the caller must disclose the excluded
    count (``excluded_non_articles``) in its payload — this only returns the candidate
    set, it does not remove or quarantine anything itself (the retroactive QUARANTINE
    stays the separate, parked fix-session action). COUNT-ONLY, no content decrypt (reads
    ``id``/``url``/``word_count`` only)."""
    from src.database.models import Article
    from src.ingest.non_article import classify_non_article

    ids = sorted({int(a) for a in article_ids})
    if not ids:
        return set()
    out: set[int] = set()
    for i in range(0, len(ids), 900):  # bounded IN() (SQLite variable limit)
        chunk = ids[i : i + 900]
        for aid, url, wc in session.query(Article.id, Article.url, Article.word_count).filter(
            Article.id.in_(chunk)
        ):
            if classify_non_article(url or "", word_count=wc) is not None:
                out.add(int(aid))
    return out
