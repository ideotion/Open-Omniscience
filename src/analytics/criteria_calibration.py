"""
Criteria-calibration diagnostic (S3.1, 2026-07-23 field-feedback workflow) -- TEMPORARY.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's own answer to "how do we decide what to quarantine?" (A4): an ITERATIVE
loop -- export the top disregarded/would-be-disregarded specimens under the CURRENT
extraction-validity criteria, review them by hand, adjust the criteria, re-export -- the
same propose->review->apply discipline this project already uses for stoplists. This
module is a REPORT over the existing detectors (:func:`src.analytics.non_article_scan.
scan_non_article_candidates` + :mod:`src.services.prose_gate`), never new judging: it does
NOT introduce any new rule, threshold, or verdict of its own.

Bounded by construction: the URL-shape half of the underlying scan never decrypts content
(id/url/word_count only); the prose-gate half decrypts a bounded, resumable batch
(``prose_gate_limit``, default 2000, chunked via ``prose_gate_after_id`` -- never a whole-
corpus decrypt in one call); and the per-article DETAIL fetch below is capped at ``top_n``
(default 100) article rows -- a genuinely small, calibration-sized decrypt, not a corpus
sweep. "TEMPORARY" per the brief: this diagnostic exists to calibrate the criteria, not to
run forever as a standing feature.

``CRITERIA_VERSION`` is the version stamp this report's underlying rules represent today --
bump it whenever ``classify_non_article``'s rules or ``prose_gate``'s thresholds change, so
a quarantine stamp (S3.2, once built) can record exactly which criteria generation flagged
it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

SCHEMA = "oo-criteria-calibration-1"
CRITERIA_VERSION = "nav-soup-v1"
_DEFAULT_TOP_N = 100
_DEFAULT_PROSE_GATE_LIMIT = 2000


def calibration_report(
    session: Session,
    *,
    top_n: int = _DEFAULT_TOP_N,
    prose_gate_limit: int = _DEFAULT_PROSE_GATE_LIMIT,
    prose_gate_after_id: int = 0,
) -> dict[str, Any]:
    """The top ``top_n`` disregarded/would-be-disregarded articles under the CURRENT
    criteria, with per-article detail (id, title, url, source, word count, function-word
    density, sentence-punctuation density, which criterion fired) plus aggregate counts
    per criterion / per source / per language, so the maintainer can optimize the criteria
    on real specimens before any retroactive quarantine (S3.4) executes for real.

    Reuses ``scan_non_article_candidates(..., include_prose_gate=True)`` for the actual
    detection (never re-implements a rule); this function only COLLECTS the sample ids it
    already returns, fetches their real article detail (a bounded ``top_n``-row decrypt),
    and aggregates. Never invents a row: an id that vanished between the scan and the
    detail fetch (a concurrent delete/prune) is silently skipped, never fabricated.
    """
    from src.analytics.non_article_scan import scan_non_article_candidates
    from src.database.models import Article, Source
    from src.services.prose_gate import function_word_density, sentence_punct_density

    base = scan_non_article_candidates(
        session,
        sample_per_reason=top_n,
        include_prose_gate=True,
        prose_gate_limit=prose_gate_limit,
        prose_gate_after_id=prose_gate_after_id,
    )

    # Combine the URL-shape reasons' sample ids with the prose-gate subpass's sample ids,
    # capped at top_n overall (concatenation, never a re-ranking -- this is a report over
    # what the detectors already flagged, not a new prioritisation).
    candidates: list[tuple[int, str]] = []
    seen: set[int] = set()
    for reason in base["by_reason"]:
        for aid in reason["sample_ids"]:
            if len(candidates) >= top_n:
                break
            if aid not in seen:
                candidates.append((int(aid), reason["signal"]))
                seen.add(int(aid))
        if len(candidates) >= top_n:
            break
    prose_gate = base.get("prose_gate") or {}
    for aid in prose_gate.get("sample_ids", []):
        if len(candidates) >= top_n:
            break
        if int(aid) not in seen:
            candidates.append((int(aid), "nav_soup"))
            seen.add(int(aid))

    articles: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    per_language: dict[str, int] = {}
    if candidates:
        ids = [aid for aid, _ in candidates]
        rows: dict[int, Article] = {
            a.id: a for a in session.query(Article).filter(Article.id.in_(ids)).all()
        }
        source_ids = {a.source_id for a in rows.values()}
        source_names: dict[int, str] = {
            sid: name
            for sid, name in session.query(Source.id, Source.name).filter(Source.id.in_(source_ids))
        } if source_ids else {}
        for aid, signal in candidates:
            a = rows.get(aid)
            if a is None:
                continue  # vanished since the scan (a concurrent delete/prune) -- never invent it
            lang = a.language or a.detected_language
            density, best_lang = function_word_density(a.content or "", language=lang)
            punct = sentence_punct_density(a.content or "")
            source_name = source_names.get(a.source_id) or f"source #{a.source_id}"
            articles.append({
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "source": source_name,
                "word_count": a.word_count,
                "language": lang,
                "best_matching_language": best_lang,
                "function_word_density": density,
                "sentence_punct_density": punct,
                "criterion": signal,
            })
            per_source[source_name] = per_source.get(source_name, 0) + 1
            lang_key = lang or "unknown"
            per_language[lang_key] = per_language.get(lang_key, 0) + 1

    per_criterion: dict[str, int] = {r["signal"]: r["count"] for r in base["by_reason"]}
    if prose_gate.get("enabled"):
        per_criterion["nav_soup"] = per_criterion.get("nav_soup", 0) + int(prose_gate.get("flagged", 0))

    return {
        "schema": SCHEMA,
        "criteria_version": CRITERIA_VERSION,
        "top_n": top_n,
        "collected": len(articles),
        "articles": articles,
        "aggregates": {
            "per_criterion": [
                {"criterion": k, "count": v}
                for k, v in sorted(per_criterion.items(), key=lambda kv: -kv[1])
            ],
            "per_source": [
                {"source": k, "count": v} for k, v in sorted(per_source.items(), key=lambda kv: -kv[1])
            ],
            "per_language": [
                {"language": k, "count": v} for k, v in sorted(per_language.items(), key=lambda kv: -kv[1])
            ],
        },
        "base_scan": base,
        "method": "A REPORT over the existing detectors -- classify_non_article's URL-shape rules "
        "(no content decrypt) + the opt-in prose-gate subpass (a bounded, resumable content decrypt, "
        "see base_scan.prose_gate) -- never a new rule of its own. Per-article density figures are "
        "recomputed directly here for EVERY collected specimen (whichever criterion actually fired), "
        "so the maintainer sees the same numbers regardless of which detector caught it.",
        "caveat": "TEMPORARY, for criteria calibration only -- a sample, not a full-corpus sweep. "
        "Iterative: review these specimens, adjust the criteria (propose -> review -> apply, the "
        "stoplist discipline), re-export. No retroactive quarantine executes against real data until "
        "this report has been reviewed and the criteria agreed (0.3 gate row 5). Inherits base_scan's "
        "own caveats (a conservative undercount; unsegmented zh/ja/th bodies skip the prose gate; a "
        "headline-list page deliberately escapes it by design).",
    }
