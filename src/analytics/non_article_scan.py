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

PROSE-GATE subpass (NAV-SOUP SPECIMEN ruling, maintainer field specimen 2026-07-20 — the Irish
Mirror ``newsletter-preference-centre`` page stored as an Article): the URL-shape pass above can
NEVER see word-rich nav soup — ``classify_non_article``'s word-count guard keeps any body
``>= _ARTICLE_MIN_WORDS`` regardless of URL when called with ``text=None``, which is exactly this
scan's calling convention. :func:`scan_non_article_candidates` therefore takes an OPT-IN
``include_prose_gate`` flag (default OFF, so the existing cheap count-only contract is BYTE-
UNCHANGED for every current caller): when set, a SECOND, BOUNDED subpass decrypts
``Article.content`` for up to ``prose_gate_limit`` candidate bodies (>= ``_ARTICLE_MIN_WORDS``,
ordered by id after ``prose_gate_after_id``) and runs the actual prose gate
(:func:`src.services.prose_gate.prose_gate_verdict`) on them — chunked/resumable like a reindex-job
batch, never a whole-corpus decrypt in one call. Its result rides under the SEPARATE ``prose_gate``
key (own denominator: this batch, not the whole corpus) rather than being folded into the
URL-shape ``by_reason``/``pct_flagged`` — the two passes see different corpus fractions and mixing
their denominators would be a dishonest percentage. Detection only, same as the rest of this
module — nothing here removes or quarantines anything.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

SCHEMA = "oo-non-article-scan-1"
_SAMPLE_PER_REASON = 20  # a bounded id sample per reason so the operator can spot-check
_PROSE_GATE_LIMIT = 2000  # bounded per-call content-decrypt cap for the opt-in prose-gate subpass


def scan_non_article_candidates(
    session: Session,
    *,
    sample_per_reason: int = _SAMPLE_PER_REASON,
    include_prose_gate: bool = False,
    prose_gate_limit: int = _PROSE_GATE_LIMIT,
    prose_gate_after_id: int = 0,
) -> dict[str, Any]:
    """Count-only retroactive scan of stored articles for URL-shaped non-articles.

    Returns per-reason counts + a bounded id sample per reason, plus the honest method/caveat. NO
    content decrypt (reads ``id``/``url``/``word_count`` only). High-precision by design — it flags
    only CLEAR URL-shaped non-articles with a thin body, never a real article (conservative).

    ``include_prose_gate`` (default OFF, so this base contract is unchanged for every existing
    caller): also run the OPT-IN, BOUNDED PROSE-GATE subpass (NAV-SOUP SPECIMEN ruling) under the
    returned ``prose_gate`` key — see the module docstring. ``prose_gate_limit``/
    ``prose_gate_after_id`` bound/resume that subpass (chunked like a reindex-job batch)."""
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

    prose_gate: dict[str, Any] = (
        _prose_gate_subpass(session, limit=prose_gate_limit, after_id=prose_gate_after_id,
                            sample_cap=sample_per_reason)
        if include_prose_gate
        else {
            "enabled": False,
            "caveat": f"Opt-in (include_prose_gate=True): decrypts Article.content for a BOUNDED "
                      f"batch of >=100-word bodies (prose_gate_limit, default {_PROSE_GATE_LIMIT}) "
                      "to run the NAV-SOUP prose gate — the word-rich nav-soup shape the URL-shape "
                      "scan above can never see. Chunked/resumable via prose_gate_after_id, "
                      "mirroring a reindex-job batch — never a whole-corpus decrypt in one call.",
        }
    )

    return {
        "schema": SCHEMA,
        "scanned": scanned,
        "flagged": flagged,
        "pct_flagged": round(100.0 * flagged / scanned, 2) if scanned else 0.0,
        "by_reason": [
            {"signal": sig, "reason": human.get(sig, ""), "count": cnt, "sample_ids": samples.get(sig, [])}
            for sig, cnt in by_reason.most_common()
        ],
        "prose_gate": prose_gate,
        "method": "COUNT-ONLY (id/url/word_count, no content decrypt) — the #659 classify_non_article "
                  "URL-shape rules only (text=None). A substantial stored word_count (>=100) is kept "
                  "whatever the URL; only a thin body proceeds to the URL rules. The opt-in "
                  "prose_gate subpass (see its own caveat) additionally decrypts a bounded batch of "
                  "those >=100-word bodies to catch word-rich nav soup.",
        "caveat": "A conservative UNDERCOUNT: the boilerplate-WALL rule needs the body (skipped here), "
                  "so consent/paywall/error walls with a normal word_count are NOT counted. "
                  "High-precision by design — never flags a real article. Read-only; the reversible "
                  "QUARANTINE (never a silent delete) is the operator action. pct_flagged here is "
                  "over the WHOLE corpus (scanned); prose_gate's own pct is over its bounded batch "
                  "only — the two are never mixed.",
        "reversible": True,
    }


def _prose_gate_subpass(
    session: Session, *, limit: int, after_id: int, sample_cap: int,
) -> dict[str, Any]:
    """Opt-in, BOUNDED, content-DECRYPTING subpass for the PROSE GATE (NAV-SOUP SPECIMEN ruling):
    the URL-shape pass above can never see word-rich nav soup (``classify_non_article``'s
    word-count guard keeps any ``>=100``-word body regardless of URL when ``text=None``, exactly
    this scan's calling convention). Reads ``Article.content`` for up to ``limit`` candidates
    (``word_count >= _ARTICLE_MIN_WORDS``, ordered by id after ``after_id``) and runs the actual
    gate on the decrypted text — chunked/resumable like a ``ReindexJobManager`` batch (call again
    with ``after_id=last_id`` to continue), NEVER a whole-corpus decrypt in one call. Detection
    only — flags candidates via a bounded id sample; never removes/quarantines anything."""
    from src.database.models import Article
    from src.ingest.non_article import _ARTICLE_MIN_WORDS
    from src.services.prose_gate import prose_gate_verdict

    q = (
        session.query(Article.id, Article.content, Article.language, Article.detected_language)
        .filter(Article.word_count >= _ARTICLE_MIN_WORDS, Article.id > after_id)
        .order_by(Article.id)
        .limit(limit)
    )
    scanned = 0
    flagged = 0
    sample_ids: list[int] = []
    last_id = after_id
    for aid, content, lang, detected in q:
        scanned += 1
        last_id = int(aid)
        verdict = prose_gate_verdict(content or "", language=lang or detected)
        if verdict is not None:
            flagged += 1
            if len(sample_ids) < sample_cap:
                sample_ids.append(int(aid))

    return {
        "enabled": True,
        "scanned": scanned,
        "flagged": flagged,
        "pct_flagged_of_batch": round(100.0 * flagged / scanned, 2) if scanned else 0.0,
        "sample_ids": sample_ids,
        "last_id": last_id,
        "done": scanned < limit,
        "limit": limit,
        "caveat": "Denominator is THIS BATCH only (scanned/flagged here), never the whole corpus — "
                  "distinct from the URL-shape pct_flagged above. Reads Article.content (decrypt "
                  "cost) for up to `limit` >=100-word bodies ordered by id after `after_id`; call "
                  "again with prose_gate_after_id=last_id to continue (never a whole-corpus decrypt "
                  "in one call). Detection only; never removes/quarantines anything.",
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
