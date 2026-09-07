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

import heapq
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

SCHEMA = "oo-non-article-scan-1"
_SAMPLE_PER_REASON = 20  # a bounded id sample per reason so the operator can spot-check
_PROSE_GATE_LIMIT = 2000  # bounded per-call content-decrypt cap for the opt-in prose-gate subpass

# The prose gate's two candidate POPULATIONS. Both are "bodies the >=100-word guard KEEPS";
# they differ in which of those bodies get decrypted, and the difference is the whole reason
# this parameter exists.
#
#   "all"          every >=100-word body, walked by id. What the gate would fire on in a
#                  DEFAULT quarantine run -- so it measures that run's blast radius.
#   "index_pages"  only those whose URL is ALSO listing-shaped (``classify_index_page``) --
#                  the ``index_pages_above_guard`` population, 1.12% of the 2026-08-23
#                  release-scale corpus (451 articles). This is the population the article
#                  clean-up is actually about (0.3 gate row 5's Tier B), and it is small
#                  enough to FINISH, where walking every long body by id is ~20 paginated
#                  calls over articles nobody has a question about.
#
# Neither is a superset judgement of the other: a scope is a statement about WHAT WAS
# MEASURED, and the report says which one it walked rather than leaving a reader to assume.
PROSE_GATE_SCOPES = ("all", "index_pages")


def scan_non_article_candidates(
    session: Session,
    *,
    sample_per_reason: int = _SAMPLE_PER_REASON,
    include_prose_gate: bool = False,
    prose_gate_limit: int = _PROSE_GATE_LIMIT,
    prose_gate_after_id: int = 0,
    prose_gate_scope: str = "all",
) -> dict[str, Any]:
    """Count-only retroactive scan of stored articles for URL-shaped non-articles.

    Returns per-reason counts + a bounded id sample per reason, plus the honest method/caveat. NO
    content decrypt (reads ``id``/``url``/``word_count`` only). High-precision by design — it flags
    only CLEAR URL-shaped non-articles with a thin body, never a real article (conservative).

    ``include_prose_gate`` (default OFF, so this base contract is unchanged for every existing
    caller): also run the OPT-IN, BOUNDED PROSE-GATE subpass (NAV-SOUP SPECIMEN ruling) under the
    returned ``prose_gate`` key — see the module docstring. ``prose_gate_limit``/
    ``prose_gate_after_id`` bound/resume that subpass (chunked like a reindex-job batch).
    ``prose_gate_scope`` (default ``"all"`` = byte-unchanged) selects WHICH >=100-word
    bodies that subpass decrypts -- see :data:`PROSE_GATE_SCOPES`."""
    from src.database.models import Article
    from src.ingest.non_article import (
        _ARTICLE_MIN_WORDS,
        classify_index_page,
        classify_non_article,
    )

    if prose_gate_scope not in PROSE_GATE_SCOPES:
        raise ValueError(f"prose_gate_scope must be one of {PROSE_GATE_SCOPES!r}")

    by_reason: Counter[str] = Counter()
    human: dict[str, str] = {}
    samples: dict[str, list[int]] = {}
    scanned = 0
    flagged = 0
    # ABOVE-GUARD listings (source-quality export 2026-08-11): the same row, the same loop, the
    # same three columns -- so this costs no extra I/O. Reported under its OWN key with its OWN
    # denominator; every key above stays byte-identical for existing callers.
    idx_by_tier: Counter[int] = Counter()
    idx_by_reason: Counter[str] = Counter()
    idx_samples: dict[str, list[int]] = {}
    # ``index_pages`` prose-gate candidates, collected in THIS loop rather than by a second
    # scan: the rows, the columns and the ``classify_index_page`` call are the ones already
    # being made, so the scope costs no extra read -- and on an encrypted store a second
    # ``(id, url, word_count)`` pass is not free, because those columns sit in rows the
    # SQLCipher codec decrypts whole.
    #
    # Bounded by CONSTRUCTION: a max-heap of at most ``prose_gate_limit`` negated ids keeps
    # the SMALLEST ids above the cursor, so the accumulator cannot grow with the corpus even
    # though the candidate population does. ``idx_above_cursor`` counts them all, which is
    # what turns "done" from a heuristic into an exact remaining.
    want_index_candidates = include_prose_gate and prose_gate_scope == "index_pages"
    idx_cand_heap: list[int] = []
    idx_above_cursor = 0
    for aid, url, wc in session.query(Article.id, Article.url, Article.word_count):
        scanned += 1
        verdict = classify_non_article(url or "", word_count=wc)  # text=None -> URL-shape rules only
        if verdict is None:
            # Kept by the body guard. If the URL is nonetheless listing-shaped, this is the
            # population the guard hides -- 8.10% of the 2026-08-11 field corpus.
            idx = classify_index_page(url or "")
            if idx is not None:
                idx_by_tier[idx.tier] += 1
                key = f"tier{idx.tier}:{idx.signal}"
                idx_by_reason[key] += 1
                human.setdefault(key, idx.reason)
                s = idx_samples.setdefault(key, [])
                if len(s) < sample_per_reason:
                    s.append(int(aid))
                # The prose gate only has anything to say about a body the guard KEPT, and
                # ``classify_index_page`` alone does not imply that (a thin body at a URL
                # shape the URL rules do not cover reaches here too). Ask explicitly.
                if (
                    want_index_candidates
                    and wc is not None
                    and wc >= _ARTICLE_MIN_WORDS
                    and int(aid) > prose_gate_after_id
                ):
                    idx_above_cursor += 1
                    if len(idx_cand_heap) < prose_gate_limit:
                        heapq.heappush(idx_cand_heap, -int(aid))
                    elif -idx_cand_heap[0] > int(aid):
                        heapq.heapreplace(idx_cand_heap, -int(aid))
            continue
        flagged += 1
        by_reason[verdict.signal] += 1
        human.setdefault(verdict.signal, verdict.reason)
        s = samples.setdefault(verdict.signal, [])
        if len(s) < sample_per_reason:
            s.append(int(aid))

    prose_gate: dict[str, Any] = (
        _prose_gate_subpass(
            session,
            limit=prose_gate_limit,
            after_id=prose_gate_after_id,
            sample_cap=sample_per_reason,
            scope=prose_gate_scope,
            candidate_ids=(sorted(-x for x in idx_cand_heap) if want_index_candidates else None),
            candidates_above_cursor=(idx_above_cursor if want_index_candidates else None),
        )
        if include_prose_gate
        else {
            "enabled": False,
            "scope": prose_gate_scope,
            "population": _population_sentence(prose_gate_scope),
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
        "index_pages_above_guard": {
            "n": sum(idx_by_tier.values()),
            "pct_of_scanned": (round(100.0 * sum(idx_by_tier.values()) / scanned, 2)
                               if scanned else 0.0),
            "tier1": idx_by_tier.get(1, 0),
            "tier2": idx_by_tier.get(2, 0),
            "by_reason": [
                {"signal": sig, "reason": human.get(sig, ""), "count": cnt,
                 "sample_ids": idx_samples.get(sig, [])}
                for sig, cnt in idx_by_reason.most_common()
            ],
            "method": "Articles the body guard KEEPS (word_count >= 100) whose URL is nonetheless "
                      "listing-shaped by this project's own rules — a section front, tag/author/"
                      "topic archive, homepage, pagination cursor, sitemap or search page whose "
                      "body is several real teasers concatenated. Same row, same loop, same three "
                      "columns as the count above: no extra read, no content decrypt. tier1 = a "
                      "real article is structurally impossible at that URL; tier2 = a listing by "
                      "convention where one could in principle live.",
            "caveat": "DETECTION ONLY and a LOWER BOUND, never a census: _SECTION_WORDS is a fixed "
                      "vocabulary, so a section front named outside it (/astrology, /obituaries) is "
                      "invisible here. These are NOT counted in flagged/pct_flagged above — that "
                      "denominator is the ingest gate's own set, and mixing them would restate one "
                      "gate's finding as the other's. Nothing is dropped or stamped by this scan; "
                      "the reversible quarantine is a separate operator action. On the 2026-08-11 "
                      "field export this population was 8.10% of an unbiased random control, of "
                      "which 36 were hand-read and 36/36 were listings.",
        },
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


def _population_sentence(scope: str) -> str:
    """What a given scope WALKED, in one sentence, for the report to carry.

    A report that names a count without naming the population it counted over is the shape
    every stale figure in this project's gate documents has taken, so the sentence rides in
    the payload rather than living only in a doc a reader may not have open."""
    if scope == "index_pages":
        return (
            "Bodies the >=100-word guard KEEPS whose URL is ALSO listing-shaped "
            "(classify_index_page) -- the index_pages_above_guard population, the one the "
            "article clean-up is about. NOT every long body."
        )
    return (
        "Every body the >=100-word guard KEEPS, walked by id -- what the nav-soup gate would "
        "fire on in a DEFAULT quarantine run. NOT scoped to listing-shaped URLs."
    )


def _prose_gate_subpass(
    session: Session,
    *,
    limit: int,
    after_id: int,
    sample_cap: int,
    scope: str = "all",
    candidate_ids: list[int] | None = None,
    candidates_above_cursor: int | None = None,
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

    base = session.query(
        Article.id, Article.content, Article.language, Article.detected_language
    )
    if scope == "index_pages":
        ids = candidate_ids or []
        rows = (
            base.filter(Article.id.in_(ids)).order_by(Article.id).all()
            if ids
            else []
        )
        # EXACT, because the caller counted every candidate above the cursor while it was
        # already walking them. ``done`` stops being the "did we fill the batch?" heuristic.
        remaining = max(0, int(candidates_above_cursor or 0) - len(ids))
    else:
        rows = (
            base.filter(Article.word_count >= _ARTICLE_MIN_WORDS, Article.id > after_id)
            .order_by(Article.id)
            .limit(limit)
            .all()
        )
        remaining = None  # filled in below, once last_id is known

    scanned = 0
    flagged = 0
    sample_ids: list[int] = []
    last_id = after_id
    for aid, content, lang, detected in rows:
        scanned += 1
        last_id = int(aid)
        verdict = prose_gate_verdict(content or "", language=lang or detected)
        if verdict is not None:
            flagged += 1
            if len(sample_ids) < sample_cap:
                sample_ids.append(int(aid))

    if remaining is None:
        # One index-only COUNT over (word_count, rowid) -- no content decrypt. Cheaper than
        # the base scan this rides on, and it is what lets a caller resuming across runs know
        # how many calls are left instead of inferring it from a full batch.
        remaining = int(
            session.query(Article.id)
            .filter(Article.word_count >= _ARTICLE_MIN_WORDS, Article.id > last_id)
            .count()
        )

    return {
        "enabled": True,
        "scope": scope,
        "population": _population_sentence(scope),
        "after_id": after_id,
        "scanned": scanned,
        "flagged": flagged,
        "pct_flagged_of_batch": round(100.0 * flagged / scanned, 2) if scanned else 0.0,
        "sample_ids": sample_ids,
        "last_id": last_id,
        "remaining": remaining,
        # Was ``scanned < limit`` -- correct in the ordinary case and wrong at the boundary
        # where a full batch happens to have exhausted the population. ``remaining`` is
        # measured, so the flag can be the fact rather than a proxy for it.
        "done": remaining == 0,
        "limit": limit,
        "caveat": "Denominator is THIS BATCH only (scanned/flagged here), never the whole corpus — "
                  "distinct from the URL-shape pct_flagged above. Reads Article.content (decrypt "
                  "cost) for up to `limit` bodies from the population named in `population`; call "
                  "again with prose_gate_after_id=last_id to continue (never a whole-corpus decrypt "
                  "in one call), or use the calibration report's `resume` to carry the cursor across "
                  "runs. `remaining` counts the population above `last_id` at read time, so a corpus "
                  "that grew or was pruned between calls moves it. Detection only; never removes/"
                  "quarantines anything.",
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
