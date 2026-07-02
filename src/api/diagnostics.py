"""
Diagnostics log: shareable, on-demand syntheses of back-end state.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer↔developer feedback channel (CLAUDE.md ruling 2026-06-10): the
corpus is private and local by design, so improving data-shaped behaviour
(keyword grouping first) needs an export the operator can *choose* to share.
Precedent: ``data/source_preflight.jsonl`` plays this role for sources.

Honesty constraints (FUTURE_DEVELOPMENTS design):
- generated ON DEMAND only — nothing is written or sent automatically;
- carries date, app version and corpus size so the reader knows the context;
- synthesizes, never editorialises: counts and structures, no scores;
- bounded (the same discipline as every other scan) and says so when capped.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics.families import build_families
from src.database.maintenance import StatementTimeout, statement_deadline
from src.database.models import (
    Article,
    Keyword,
    KeywordSuperGroup,
    Source,
)
from src.database.session import get_db
from src.utils.export_envelope import envelope

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

# Bounded scan — PER LANGUAGE (maintainer-ruled 2026-06-11): a single global
# mentions-ranked cap structurally anglicised the export (English keywords
# crowded out every other language, excluding them from the equivalence/family
# analysis). Each keyword counts against the quota of its DOMINANT signature
# language, so French/German/… vocabularies are exported in full alongside
# English. Bounded per language, biased against none.
_MAX_KEYWORDS_PER_LANG = 5000

# Stopword-candidate digest (maintainer 2026-06-18, "full authority on the logging
# process"): the recursive-improvement loop is "grow the not-a-keyword list", and
# the analyst (me) needs, per language, the terms that LOOK like function words but
# aren't stoplisted yet — NOT a 24 MB dump of 245k keywords. A function word is
# SHORT, FREQUENT and UBIQUITOUS (spread across many articles), so it lives at the
# TOP by frequency (well within the per-language survivor set) — the cap never hides
# it. This compact, whole-corpus-relevant digest is computed FROM the survivors the
# export already built (zero extra DB cost), prioritised by the languages that have
# NO stoplist yet (where the wins are).
_SW_CAND_PER_LANG = 60     # top candidates surfaced per language
_SW_CAND_MAX_LEN = 14      # function words are short; longer terms are content
_SW_CAND_MIN_ARTICLES = 5  # needs real spread (ubiquity) to look like a function word

# Ring-candidate digest: the inverse worklist — the highest-spread CONCEPTS not yet
# in any cross-language ring, per language, to drive the corpus-driven ring
# expansion (generate_wikidata_rings.py --from-log) and to measure coverage.
_RING_CAND_PER_LANG = 60     # top gap concepts surfaced per language
_RING_CAND_MIN_ARTICLES = 3  # enough spread to be worth a Wikidata QID resolution


def _stopword_candidates(survivors, meta, dom_lang, is_hidden) -> dict:
    """Per dominant-language, the highest article-SPREAD short single-token TERMS that
    are NOT yet stoplisted — the shape of a function word. Ranked by distinct-article
    spread; no score. Languages with no stoplist (no_stoplist/unsegmented) come first."""
    from src.analytics.managed import language_status

    by_lang: dict[str, list[dict]] = {}
    for kid, m, a, _first, _last in survivors:
        term, norm, lang, is_ent, _ent = meta.get(kid, ("?", "?", None, False, None))
        if is_ent or not norm or " " in norm:
            continue  # single-token TERMS only (entities + n-grams aren't function words)
        if len(norm) > _SW_CAND_MAX_LEN or int(a) < _SW_CAND_MIN_ARTICLES:
            continue
        if is_hidden(norm):
            continue  # already stoplisted / excluded — not a candidate
        dom = dom_lang.get(kid) or lang or "?"
        by_lang.setdefault(dom, []).append(
            {"term": term, "normalized": norm, "mentions": int(m), "articles": int(a), "len": len(norm)}
        )
    out: dict[str, dict] = {}
    for dom, items in by_lang.items():
        items.sort(key=lambda x: (-x["articles"], -x["mentions"]))
        out[dom] = {
            "status": language_status(dom),
            "total": len(items),
            "candidates": items[:_SW_CAND_PER_LANG],
        }
    priority = sorted(
        (d for d, v in out.items() if v["status"] in ("no_stoplist", "unsegmented")),
        key=lambda d: -out[d]["total"],
    )
    # Surface unmanaged-language buckets first (the worklist), each densest-first.
    ordered = dict(sorted(out.items(), key=lambda kv: (kv[1]["status"] not in ("no_stoplist", "unsegmented"), -kv[1]["total"])))
    return {
        "method": (
            "Per dominant-signature language, short single-token TERMS (<= "
            f"{_SW_CAND_MAX_LEN} chars, >= {_SW_CAND_MIN_ARTICLES} distinct articles) NOT "
            "yet stoplisted, ranked by article spread — the shape of a function word. "
            "Candidates to REVIEW before adding to a stoplist; no score, no inference."
        ),
        "priority_languages": priority,
        "by_language": ordered,
    }


def _ring_candidates(survivors, meta, dom_lang, is_hidden) -> dict:
    """Per dominant-signature language, the highest article-SPREAD TERMS that are
    NOT yet in any cross-language RING — the ring GAP, the worklist for the
    corpus-driven expansion ``generate_wikidata_rings.py --from-log``.

    Two optimisations over blindly taking the top-N keywords: (1) it EXCLUDES terms
    already in a ring, so a generation pass resolves NEW concepts instead of
    re-resolving the ones we already have; (2) it surfaces EVERY language (not just
    English), so a concept prominent only in ar/zh/ru is seedable too (the
    de-US-centring fix — the generator can search Wikidata in that language).
    Also reports ``translation_coverage`` (ring-covered / gated terms) — the
    self-check metric, in the same log the maintainer already exports.

    Concepts come from non-entity TERMS (acronym entities resolve ambiguously on
    Wikidata — exactly the homograph garbage vetting had to drop). Multi-word terms
    are KEPT (a concept can be "climate change" / "supply chain"), unlike the
    single-token stopword candidates. No score, no inference."""
    from src.analytics import equivalence

    by_lang: dict[str, list[dict]] = {}
    gated: dict[str, int] = {}
    covered: dict[str, int] = {}
    for kid, m, a, _first, _last in survivors:
        term, norm, lang, is_ent, _ent = meta.get(kid, ("?", "?", None, False, None))
        if is_ent or not norm:
            continue
        if int(a) < _RING_CAND_MIN_ARTICLES or is_hidden(norm):
            continue
        eff = dom_lang.get(kid) or lang or "?"
        gated[eff] = gated.get(eff, 0) + 1
        if equivalence.ring_of(eff, norm) is not None:
            covered[eff] = covered.get(eff, 0) + 1
            continue  # already a ring member — counts toward coverage, not a gap
        by_lang.setdefault(eff, []).append(
            {"term": term, "normalized": norm, "mentions": int(m), "articles": int(a)}
        )
    out: dict[str, dict] = {}
    for lang, items in by_lang.items():
        items.sort(key=lambda x: (-x["articles"], -x["mentions"]))
        g = gated.get(lang, 0)
        c = covered.get(lang, 0)
        out[lang] = {
            "gap_total": len(items),
            "ring_covered": c,
            "coverage": round(c / g, 4) if g else 0.0,
            "candidates": items[:_RING_CAND_PER_LANG],
        }
    # LOWEST-coverage languages first (where ring-building helps most), then by gap size.
    ordered = dict(sorted(out.items(), key=lambda kv: (kv[1]["coverage"], -kv[1]["gap_total"])))
    tot_g = sum(gated.values())
    tot_c = sum(covered.values())
    return {
        "method": (
            "Per dominant-signature language, non-entity TERMS with >= "
            f"{_RING_CAND_MIN_ARTICLES} distinct articles NOT yet in any cross-language "
            "ring, ranked by article spread — the ring GAP for "
            "generate_wikidata_rings.py --from-log. translation_coverage = "
            "ring-covered / gated terms (the self-check metric). Candidates to RESOLVE "
            "via a Wikidata QID; multi-word concepts kept; no score, no inference."
        ),
        "translation_coverage": round(tot_c / tot_g, 4) if tot_g else 0.0,
        "gated_terms": tot_g,
        "by_language": ordered,
    }


def _in_batches(ids: list[int], size: int = 800):
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


# Digest mode keeps the same bounded aggregates but ships only the top-N
# most-mentioned keywords instead of the full per-keyword list, so the file is
# small enough to actually ingest in the maintainer->dev channel (field-test
# 2026-06-15 Item Z: a full log measured ~60 MB and was unusable in the very
# channel it exists for). The aggregates ARE the analysis; the long tail is not.
_DIGEST_SAMPLE = 100

# Hard ceiling for the per-language ZIP export (?format=zip). The single-file log
# grew to ~20 MB live (137k keywords), so the shareable archive is capped: it
# splits per language and zips (JSON compresses ~8x, so the archive is normally a
# few MB), and as a guarantee, if the compressed archive ever exceeds this it
# drops the lowest-mention keywords PER LANGUAGE (equal-fair — a global mentions
# cut would re-anglicise the export) and records the omission. Env-tunable.
def _keyword_zip_max_bytes() -> int:
    # Default 9 MB so a shared archive stays UNDER the common 10 MB attachment limit
    # (raised 2026-07-01: the maintainer could not send a log). With the families cap
    # below, a 727k-keyword corpus is ~8 MB with EVERY keyword — no trimming needed;
    # a larger corpus trims its lowest-mention tail (per language, recorded) to fit.
    try:
        mb = float(os.environ.get("OO_KEYWORD_LOG_MAX_MB", "9"))
    except ValueError:
        mb = 9.0
    # Floor at 256 B (not 1 MB) only to forbid a zero/negative cap; realistic
    # callers set MB-scale values. The small floor keeps the trim path testable.
    return max(256, int(mb * 1024 * 1024))


def _keyword_zip_families_cap() -> int:
    """Top-N families to embed in summary.json (0 = keep all — the old behaviour).

    The full per-keyword family dump is ~150 MB on a large corpus (708k families in the
    2026-07-01 log), REDUNDANT with keywords/<lang>.json, and UNUSED by
    analyze_keyword_log.py (it reassembles keywords from the shards). It was also why the
    byte cap never held: the trim loop shrinks the shards, never summary.json. So only the
    top families (by mentions) are kept for a human glance; the tail is derivable from the
    shards. Override with OO_KEYWORD_LOG_FAMILIES.
    """
    try:
        return max(0, int(os.environ.get("OO_KEYWORD_LOG_FAMILIES", "1000")))
    except ValueError:
        return 1000


def _safe_lang_filename(lang: str) -> str:
    """A filesystem/zip-safe stem for a language code ('?' -> 'unknown')."""
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in (lang or ""))
    return safe or "unknown"


def _group_entries_by_language(survivors, entry_fn, dom_lang, stored_lang) -> dict:
    """Group built per-keyword entries by dominant language, preserving the
    mentions-desc order of ``survivors`` (so a later byte-cap trims the tail)."""
    by_lang: dict[str, list[dict]] = {}
    for s in survivors:
        kid = s[0]
        dom = dom_lang.get(kid) or stored_lang.get(kid) or "?"
        by_lang.setdefault(dom, []).append(entry_fn(s))
    return by_lang


def _keyword_zip(
    *,
    corpus: dict,
    method: str,
    families: list,
    overrides: dict,
    supergroups: list,
    per_source_concentration: list,
    suspects_total: int,
    suspects_capped: bool,
    entries_by_lang: dict,
    stopword_candidates: dict,
    ring_candidates: dict,
    page_info: dict | None = None,
) -> Response:
    """Build the per-language keyword-log ZIP, guaranteed under the byte cap.

    Members: ``summary.json`` (the corpus-wide aggregates — families, super-groups,
    per-source concentration — the SAME data the single-file log carries minus the
    keyword list), ``keywords/<lang>.json`` (each language's keywords, same
    per-keyword fields), and ``manifest.json`` (what's inside + any omissions). The
    split mirrors the per-language export quota; JSON compresses ~8x so the archive
    is normally a few MB. If the compressed archive still exceeds the cap (only on a
    very large corpus) the lowest-mention keywords are dropped PER LANGUAGE
    (equal-fair) and recorded — never a silent or anglicising cut."""
    import io
    import zipfile

    # Cap the families dump (sorted by mentions desc): the full 700k-family tail is
    # redundant with the shards + unused by the analyzer + the reason the byte cap never
    # held. Keep the top-N for a human glance; record the omission honestly.
    _fam_cap = _keyword_zip_families_cap()
    _families_shown = families[:_fam_cap] if _fam_cap and len(families) > _fam_cap else families
    summary_payload = {
        "corpus": corpus,
        "method": method,
        "families": _families_shown,
        "families_provenance": {
            "shown": len(_families_shown),
            "total": len(families),
            "omitted": len(families) - len(_families_shown),
            "sorted_by": "mentions (desc)",
            "note": (
                "Only the top families are embedded here (the full per-keyword family dump "
                "is large, redundant with keywords/<lang>.json, and unused by "
                "analyze_keyword_log.py). Set OO_KEYWORD_LOG_FAMILIES=0 to embed all."
            ),
        },
        "overrides": [
            {"normalized_term": term, **data} for term, data in sorted(overrides.items())
        ],
        "supergroups": supergroups,
        "stopword_candidates": stopword_candidates,
        "ring_candidates": ring_candidates,
        "per_source_concentration": {
            "suspects": per_source_concentration,
            "suspects_total": suspects_total,
            "list_capped_at_200": suspects_capped,
            "thresholds": {
                "min_articles_with_keyword": 10,
                "min_source_articles": 10,
                "min_share_of_keyword": 0.9,
                "min_share_of_source": 0.25,
            },
        },
    }
    max_bytes = _keyword_zip_max_bytes()

    def _build(by_lang: dict, omitted: dict) -> bytes:
        total_kw = sum(len(v) for v in by_lang.values())
        summary_doc = envelope(
            kind="keyword-diagnostics",
            query={"format": "zip"},
            count=total_kw,
            payload=summary_payload,
        )
        langs_meta = [
            {"code": lang, "keywords": len(by_lang[lang]), "omitted_to_fit": omitted.get(lang, 0)}
            for lang in sorted(by_lang)
        ]
        manifest = {
            "export_schema": "oo-export-1",
            "kind": "keyword-diagnostics-archive",
            "app_version": summary_doc.get("app_version"),
            "generated_at": summary_doc.get("generated_at"),
            "corpus": corpus,
            "languages": sorted(langs_meta, key=lambda m: -m["keywords"]),
            "keywords_in_archive": total_kw,
            "keywords_omitted_to_fit": sum(omitted.values()),
            "max_bytes": max_bytes,
            # Paging: per_lang/page/pages_total/has_more let the caller export the
            # WHOLE corpus across several files when one page would exceed the cap.
            **(page_info or {}),
            "note": (
                "Per-language split of the keyword diagnostics log, zipped to keep the "
                "shared file under 10 MB (fits a typical attachment limit). Read "
                "summary.json for the corpus-wide aggregates (top families, super-groups, "
                "per-source concentration; families_provenance records the family cap) "
                "and keywords/<lang>.json for each language's "
                "keywords (same per-keyword fields as the single-file log). "
                "scripts/analyze_keyword_log.py reads this .zip directly. "
                "keywords_omitted_to_fit > 0 means the lowest-mention keywords per "
                "language were dropped to fit max_bytes — never silently; see the "
                "per-language counts."
            ),
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for lang in sorted(by_lang):
                ents = by_lang[lang]
                z.writestr(
                    f"keywords/{_safe_lang_filename(lang)}.json",
                    json.dumps(
                        {"language": lang, "count": len(ents), "keywords": ents},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            z.writestr(
                "summary.json",
                json.dumps(summary_doc, ensure_ascii=False, separators=(",", ":")),
            )
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return buf.getvalue()

    omitted: dict[str, int] = {}
    data = _build(entries_by_lang, omitted)
    guard = 0
    while len(data) > max_bytes and guard < 8:
        guard += 1
        ratio = max_bytes / len(data) * 0.9
        for lang, ents in list(entries_by_lang.items()):
            keep = max(1, int(len(ents) * ratio))
            if keep < len(ents):
                omitted[lang] = omitted.get(lang, 0) + (len(ents) - keep)
                entries_by_lang[lang] = ents[:keep]
        data = _build(entries_by_lang, omitted)

    fname = f"oo-keyword-log-{datetime.now().strftime('%Y%m%d')}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _export_deadline_seconds() -> float:
    """Deadline for THIS on-demand, streamed, full-corpus diagnostic export.

    The interactive ``OO_STATEMENT_TIMEOUT_S`` (60s) guard is the WRONG mechanism
    here: the keyword log is a DELIBERATE full-corpus crunch the operator
    explicitly requests and streams to disk, not a latency-sensitive page read.
    At field scale (≈940k mentions / 336k keywords, encrypted, 2-core VM) the
    full ``keyword_mentions`` scans legitimately run past 60s, so the interactive
    deadline ABORTED the export with a 503 -- i.e. the cap was bounding the
    data-crunching, which the maintainer's keyword policy forbids ("a cap may
    bound a REPORT, never the crunching").

    So the export gets its OWN budget: ``OO_KEYWORD_EXPORT_TIMEOUT_S``, default
    0 = no deadline. The download still streams (progress is visible) and the
    single-writer WAL keeps writers unblocked during the long read. Set a
    positive number of seconds to re-impose a ceiling.
    """
    try:
        return float(os.environ.get("OO_KEYWORD_EXPORT_TIMEOUT_S", "0"))
    except ValueError:
        return 0.0


@router.get("/keywords")
def keyword_log(
    db: Session = Depends(get_db),
    digest: bool = Query(
        False,
        description=(
            "Digest mode: ship the bounded aggregates (families, per-source "
            "concentration, totals) + a top-N keyword sample instead of the full "
            "per-keyword list, for a small, ingestible file (Item Z). The default "
            "(full) stream is byte-for-byte unchanged."
        ),
    ),
    fmt: str = Query(
        "json",
        alias="format",
        description=(
            "'json' (default — the full single-file stream, byte-for-byte unchanged) "
            "or 'zip' — a per-language split archive kept UNDER 10 MB (summary.json "
            "+ keywords/<lang>.json + manifest.json), so it fits a typical attachment "
            "limit. The recommended share format: every keyword, no huge single blob."
        ),
    ),
    per_lang: int = Query(
        _MAX_KEYWORDS_PER_LANG,
        ge=1,
        le=1_000_000,
        description=(
            "ZIP only: how many keywords PER dominant language to export (default "
            f"{_MAX_KEYWORDS_PER_LANG}). Raise it to export far more — even the whole "
            "corpus — in one archive (the <10 MB byte cap still applies and, "
            "if hit, trims the lowest-mention keywords per language and records it). "
            "Combine with `page` to walk through everything in digestible chunks."
        ),
    ),
    page: int = Query(
        1,
        ge=1,
        description=(
            "ZIP only: 1-indexed page through the per-language keyword list (page N = "
            "keywords ranked [(N-1)*per_lang : N*per_lang] by mentions). The manifest "
            "reports pages_total + has_more so the full set can be exported across "
            "several files."
        ),
    ),
) -> Response:
    """The keyword diagnostics log: every gathered keyword (bounded, mentions-desc)
    with its counts, plus the computed families, the user's merge/split overrides
    and the super-groups — exactly the structures the grouping logic works on.

    ``digest=1`` keeps every bounded aggregate but replaces the (potentially
    tens-of-MB) per-keyword list with a top-``_DIGEST_SAMPLE`` sample by mentions
    plus an honest ``keywords_digest`` provenance block (shown/total/omitted) so a
    digest is never mistaken for a complete log. The default path is untouched.

    Performance batch 2026-06-12 (failed live at 228k keywords): the per-language
    cap now bounds the WORK, not just the output — totals scan the covering
    index as plain tuples, the dominant language is computed in SQL, and the
    full language signatures / keyword metadata are fetched only for the
    keywords that survive the quota. The body is STREAMED, so memory stays
    bounded and the download starts immediately. Same envelope, same fields,
    same cap semantics as before (contract-tested).
    """
    try:
        with statement_deadline(db, seconds=_export_deadline_seconds()):
            # Article -> language, ONCE, via the covering index (verified plan:
            # idx_article_country_language) — joining mentions to articles in
            # SQL would drag article rows through the SQLCipher codec for every
            # batch (measured 26 s of the 32 s encrypted-profile wall time).
            art_lang: dict[int, str] = {
                aid: (lang or "?")
                for aid, lang in db.execute(text("SELECT id, language FROM articles"))
            }

            # Article -> source, the same codec-free way (covering index on
            # source_id), for the per-source concentration diagnostic below.
            art_src: dict[int, int] = dict(
                db.execute(text("SELECT id, source_id FROM articles")).fetchall()
            )
            src_articles: dict[int, int] = dict(
                db.execute(
                    text("SELECT source_id, COUNT(*) FROM articles GROUP BY source_id")
                ).fetchall()
            )

            # Dominant signature language per keyword from ONE index-only scan
            # of (keyword_id, article_id), ordered so each keyword's counts can
            # be reduced and freed as the scan passes it. Ties: language asc
            # (matching the previous argmax over language-asc grouped rows).
            # The SAME pass measures per-source concentration: a keyword whose
            # articles sit ≥90% in one source, covering ≥25% of that source's
            # articles (≥10 articles) is a boilerplate/navigation-text suspect
            # (field report #4: Swedish "alla artiklar" ×118) — FLAGGED with
            # real counts, never auto-hidden; the operator decides.
            dom_lang: dict[int, str] = {}
            suspects: list[dict] = []
            _cur_kid: int | None = None
            _counts: dict[str, int] = {}
            _srcs: dict[int, int] = {}

            def _finalize(kid: int | None, counts: dict[str, int], srcs: dict[int, int]) -> None:
                if kid is None or not counts:
                    return
                dom_lang[kid] = min(counts, key=lambda lg: (-counts[lg], lg))
                n_articles = sum(srcs.values())
                if n_articles >= 10:
                    top_src, top_n = max(srcs.items(), key=lambda kv: kv[1])
                    src_total = src_articles.get(top_src, 0)
                    if src_total >= 10 and top_n / n_articles >= 0.9 and top_n / src_total >= 0.25:
                        suspects.append(
                            {
                                "keyword_id": kid,
                                "source_id": top_src,
                                "articles_with_keyword": n_articles,
                                "in_this_source": top_n,
                                "source_article_total": src_total,
                                "share_of_keyword": round(top_n / n_articles, 3),
                                "share_of_source": round(top_n / src_total, 3),
                            }
                        )

            for kid, aid in db.execute(
                text("SELECT keyword_id, article_id FROM keyword_mentions ORDER BY keyword_id")
            ):
                if kid != _cur_kid:
                    _finalize(_cur_kid, _counts, _srcs)
                    _cur_kid, _counts, _srcs = kid, {}, {}
                lg = art_lang.get(aid, "?")
                _counts[lg] = _counts.get(lg, 0) + 1
                sid = art_src.get(aid)
                if sid is not None:
                    _srcs[sid] = _srcs.get(sid, 0) + 1
            _finalize(_cur_kid, _counts, _srcs)

            # The DETECTION is unbounded: every keyword × source pair in the
            # corpus is evaluated (inside the same full mention scan). Only the
            # LIST PRINTED in this report is bounded — strongest-first, with
            # the true total disclosed — so the file stays reviewable while no
            # magnitude is ever hidden (the maintainer's anti-capping rule:
            # caps may bound a REPORT, never the data crunching).
            suspects.sort(key=lambda s: (-s["share_of_source"], -s["in_this_source"]))
            suspects_total = len(suspects)
            suspects_capped = suspects_total > 200
            suspects = suspects[:200]

            # Stored-language fallback for keywords with no mentions (kept from
            # the previous contract: they export with zero counts, quota applies).
            stored_lang: dict[int, str | None] = dict(
                db.execute(text("SELECT id, language FROM keywords")).fetchall()
            )

            # Totals, mentions-desc — an index-only scan of ix_mention_covering,
            # iterated as tuples; the quota decides survivors ON THE FLY, so the
            # 228k-keyword aggregation never materialises as ORM objects.
            # Page-aware per-language quota. The JSON path keeps the classic top-
            # _MAX_KEYWORDS_PER_LANG cap (lo=0); the ZIP path can raise per_lang and
            # page through the WHOLE corpus in digestible chunks (maintainer 2026-06-21:
            # "export more keywords — there were 200k+"). per_lang_seen tracks the total
            # ranked position per language (for paging + pages_total/has_more).
            eff_per_lang = per_lang if fmt == "zip" else _MAX_KEYWORDS_PER_LANG
            lo = (page - 1) * eff_per_lang if fmt == "zip" else 0
            hi = lo + eff_per_lang
            per_lang_seen: dict[str, int] = {}
            per_lang_taken: dict[str, int] = {}
            capped_langs: set[str] = set()
            survivors: list[tuple[int, int, int, str | None, str | None]] = []
            seen: set[int] = set()
            totals_sql = text(
                "SELECT keyword_id, COALESCE(SUM(count), 0) AS m,"
                " COUNT(DISTINCT article_id) AS a,"
                " MIN(observed_on) AS first_seen, MAX(observed_on) AS last_seen"
                " FROM keyword_mentions GROUP BY keyword_id"
                " ORDER BY m DESC, keyword_id ASC"
            )
            for kid, m, a, first, last in db.execute(totals_sql):
                seen.add(kid)
                dom = dom_lang.get(kid) or stored_lang.get(kid) or "?"
                idx = per_lang_seen.get(dom, 0)
                per_lang_seen[dom] = idx + 1
                if idx < lo:
                    continue
                if idx >= hi:
                    capped_langs.add(dom)
                    continue
                per_lang_taken[dom] = per_lang_taken.get(dom, 0) + 1
                survivors.append((kid, int(m), int(a), first, last))
            for kid in sorted(set(stored_lang) - seen):  # zero-mention keywords
                dom = stored_lang.get(kid) or "?"
                idx = per_lang_seen.get(dom, 0)
                per_lang_seen[dom] = idx + 1
                if idx < lo:
                    continue
                if idx >= hi:
                    capped_langs.add(dom)
                    continue
                per_lang_taken[dom] = per_lang_taken.get(dom, 0) + 1
                survivors.append((kid, 0, 0, None, None))

            survivor_ids = [s[0] for s in survivors]
            # Metadata + full language signatures for SURVIVORS only.
            meta: dict[int, tuple] = {}
            lang_sig: dict[int, dict[str, int]] = {}
            for batch in _in_batches(survivor_ids):
                marks = ",".join(str(int(i)) for i in batch)
                for kid, term, norm, lang, is_ent, ent_type in db.execute(
                    text(
                        "SELECT id, term, normalized_term, language, is_entity,"  # nosec B608 - interpolant is a joined list of int()-cast ids built in this function, never input
                        f" entity_type FROM keywords WHERE id IN ({marks})"
                    )
                ):
                    meta[kid] = (term, norm, lang, bool(is_ent), ent_type)
                # Full signatures via index-only probes + the art_lang map —
                # mention rows are unique per (keyword, article), so each row
                # contributes exactly one distinct article to its language.
                for kid, aid in db.execute(
                    text(
                        "SELECT keyword_id, article_id FROM keyword_mentions"  # nosec B608 - interpolant is a joined list of int()-cast ids built in this function, never input
                        f" WHERE keyword_id IN ({marks})"
                    )
                ):
                    sig = lang_sig.setdefault(kid, {})
                    lg = art_lang.get(aid, "?")
                    sig[lg] = sig.get(lg, 0) + 1

            # Names for the concentration suspects (small, bounded set) — the
            # section is readable on its own: terms + source names + counts.
            suspect_kids = {s["keyword_id"] for s in suspects} - set(meta)
            for batch in _in_batches(sorted(suspect_kids)):
                marks = ",".join(str(int(i)) for i in batch)
                for kid, term, norm, lang, is_ent, ent_type in db.execute(
                    text(
                        "SELECT id, term, normalized_term, language, is_entity,"  # nosec B608 - interpolant is a joined list of int()-cast ids built in this function, never input
                        f" entity_type FROM keywords WHERE id IN ({marks})"
                    )
                ):
                    meta[kid] = (term, norm, lang, bool(is_ent), ent_type)
            src_names: dict[int, str] = {}
            sids = sorted({s["source_id"] for s in suspects})
            if sids:
                marks = ",".join(str(int(i)) for i in sids)
                src_names = dict(
                    db.execute(
                        text(f"SELECT id, name FROM sources WHERE id IN ({marks})")  # nosec B608 - interpolant is a joined list of int()-cast ids built in this function, never input
                    ).fetchall()
                )
            per_source_concentration = [
                {
                    "term": meta.get(s["keyword_id"], ("?",))[0],
                    "source": src_names.get(s["source_id"], f"#{s['source_id']}"),
                    **{k: v for k, v in s.items() if k not in ("keyword_id", "source_id")},
                }
                for s in suspects
            ]

            corpus = {
                "articles": int(db.query(func.count(Article.id)).scalar() or 0),
                "sources": int(db.query(func.count(Source.id)).scalar() or 0),
                "keywords_total": len(stored_lang),
                "keywords_exported": len(survivors),
                "exported_per_language": per_lang_taken,
                "capped_languages": sorted(capped_langs),
            }
            overrides = q.load_overrides(db)
            supergroups = [
                {
                    "name": sg.name,
                    "members": sorted(m.normalized_term for m in sg.members),
                }
                for sg in db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
            ]
    except StatementTimeout as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # The stoplist verdict is part of the diagnosis: leaked function words the
    # operator hid are exactly what grouping fixes need to see — flag, not omit.
    is_hidden = q._hidden_predicate()

    def _entry(s: tuple) -> dict:
        kid, m, a, first, last = s
        term, norm, lang, is_ent, ent_type = meta.get(kid, ("?", "?", None, False, None))
        dom = dom_lang.get(kid)
        return {
            "term": term,
            "normalized": norm,
            "kind": (ent_type or "entity") if is_ent else "term",
            "language": lang,
            "mentions": m,
            "articles": a,
            "first_seen": str(first) if first else None,
            "last_seen": str(last) if last else None,
            "hidden": bool(is_hidden(norm)),
            "language_signature": lang_sig.get(kid, {}),
            # Attribution noise flag (field report #4: de-tagged English text):
            # the stored language disagrees with the signature's dominant one.
            # Evidence, not a correction — both values stay visible above.
            "language_mismatch": bool(dom is not None and dom != (lang or "?")),
        }

    fam_items = []
    for s in survivors:
        kw = _entry(s)
        if not kw["hidden"]:
            fam_items.append(
                {
                    "term": kw["term"],
                    "normalized": kw["normalized"],
                    "kind": kw["kind"],
                    "mentions": kw["mentions"],
                    "articles": kw["articles"],
                }
            )
    families = [f.to_dict() for f in build_families(fam_items, overrides)]

    # Compact per-language stopword-candidate digest (reuses the survivors already
    # built — zero extra DB cost) for the recursive "grow the not-a-keyword list" loop.
    stopword_candidates = _stopword_candidates(survivors, meta, dom_lang, is_hidden)
    # Compact ring-GAP digest (same survivors — zero extra DB cost) for the
    # corpus-driven ring expansion + the translation-coverage self-check.
    ring_candidates = _ring_candidates(survivors, meta, dom_lang, is_hidden)

    method = (
        f"All gathered keywords (top {_MAX_KEYWORDS_PER_LANG} PER dominant signature "
        "language — a global cap would anglicise the export) with real "
        "counts; language_signature = distinct articles per ARTICLE language "
        "(the trans-language disambiguation evidence); language_mismatch flags a "
        "stored language that disagrees with the signature's dominant one "
        "(attribution-noise evidence, never a correction); families computed by the "
        "live grouping logic incl. the user's merge/split overrides; super-groups "
        "as curated. per_source_concentration lists boilerplate SUSPECTS — a "
        "keyword whose articles sit ≥90% in one source, covering ≥25% of that "
        "source's articles (both sides ≥10 articles), strongest first, capped at "
        "200 — flagged with real counts, never auto-hidden. No scores, no inference."
    )

    digest_note = (
        f" DIGEST MODE: the per-keyword list is the top {_DIGEST_SAMPLE} keywords by "
        "mentions; keywords_digest reports how many were omitted. Re-request without "
        "digest=1 for the complete per-keyword log."
    )

    def _stream():
        head = envelope(
            kind="keyword-diagnostics",
            query={"digest": True} if digest else {},
            count=len(survivors),
            payload=None,
        )
        del head["data"]
        yield json.dumps(head, separators=(",", ":"))[:-1] + ', "data": {'
        yield '"corpus": ' + json.dumps(corpus, separators=(",", ":"))
        yield ', "method": ' + json.dumps(
            method + (digest_note if digest else ""), separators=(",", ":")
        )
        if digest:
            # Top-N by mentions (s[1]); ties keep scan order. The aggregates below
            # are unchanged — they ARE the analysis; only the long tail is dropped.
            sample = sorted(survivors, key=lambda s: s[1], reverse=True)[:_DIGEST_SAMPLE]
            yield ', "keywords": [' + ",".join(
                json.dumps(_entry(s), separators=(",", ":")) for s in sample
            ) + "]"
            yield ', "keywords_digest": ' + json.dumps(
                {
                    "sample": True,
                    "shown": len(sample),
                    "total": len(survivors),
                    "omitted": len(survivors) - len(sample),
                    "sort": "mentions desc",
                },
                separators=(",", ":"),
            )
        else:
            yield ', "keywords": ['
            for i in range(0, len(survivors), 1000):
                chunk = survivors[i : i + 1000]
                prefix = "" if i == 0 else ","
                yield prefix + ",".join(
                    json.dumps(_entry(s), separators=(",", ":")) for s in chunk
                )
            yield "]"
        yield ', "families": ' + json.dumps(families, separators=(",", ":"))
        yield ', "overrides": ' + json.dumps(
            [{"normalized_term": term, **data} for term, data in sorted(overrides.items())],
            separators=(",", ":"),
        )
        yield ', "supergroups": ' + json.dumps(supergroups, separators=(",", ":"))
        yield ', "stopword_candidates": ' + json.dumps(
            stopword_candidates, separators=(",", ":")
        )
        yield ', "ring_candidates": ' + json.dumps(
            ring_candidates, separators=(",", ":")
        )
        yield ', "per_source_concentration": ' + json.dumps(
            {
                "suspects": per_source_concentration,
                "suspects_total": suspects_total,
                "list_capped_at_200": suspects_capped,
                "thresholds": {
                    "min_articles_with_keyword": 10,
                    "min_source_articles": 10,
                    "min_share_of_keyword": 0.9,
                    "min_share_of_source": 0.25,
                },
            },
            separators=(",", ":"),
        )
        yield "}}"

    if fmt == "zip":
        # Paging facts so the caller can walk the WHOLE corpus across files.
        pages_total = max(
            (-(-t // eff_per_lang) for t in per_lang_seen.values()), default=1
        )
        page_info = {
            "page": page,
            "per_lang": eff_per_lang,
            "pages_total": pages_total,
            "has_more": any(t > hi for t in per_lang_seen.values()),
            "keywords_total_corpus": sum(per_lang_seen.values()),
        }
        return _keyword_zip(
            corpus=corpus,
            method=method,
            families=families,
            overrides=overrides,
            supergroups=supergroups,
            per_source_concentration=per_source_concentration,
            suspects_total=suspects_total,
            suspects_capped=suspects_capped,
            entries_by_lang=_group_entries_by_language(
                survivors, _entry, dom_lang, stored_lang
            ),
            stopword_candidates=stopword_candidates,
            ring_candidates=ring_candidates,
            page_info=page_info,
        )

    kind_tag = "digest" if digest else "log"
    fname = f"oo-keyword-{kind_tag}-{datetime.now().strftime('%Y%m%d')}.json"
    return StreamingResponse(
        _stream(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/keyword-selftest")
def keyword_selftest(download: bool = Query(False)) -> JSONResponse:
    """Run the keyword pre-selection challenge harness (Who vs WHO + language tweaks).

    A curated golden-case self-test over the REAL extractor / families / equivalence /
    baseline — no DB, no network, no score. Returns an exportable log (oo-selftest-1)
    the maintainer can run and send back for the next optimization round. With
    ``download=1`` it comes back as a dated attachment."""
    from src.analytics.selftest import run_keyword_selftest

    log = run_keyword_selftest()
    headers = {}
    if download:
        fname = f"oo-keyword-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.post("/enrich-sources")
def enrich_sources(db: Session = Depends(get_db)) -> JSONResponse:
    """Enrich source metadata from the LOCAL corpus (deduced topic tags).

    Zero-network: deduces each source's topics from the keywords it actually
    publishes (keyword_tags axis="topic") and unions them into ``Source.tags`` --
    additive, never overwrites a curated tag, idempotent. This is the same pass the
    scheduler runs automatically (freshness-gated); the button forces it now. The
    networked Wikidata ``source_type`` pass is a SEPARATE, consented action (it
    egresses to Wikidata over clearnet)."""
    from src.analytics.source_topics import apply_source_topics

    result = apply_source_topics(db)
    return JSONResponse({"mode": "corpus", **result})


@router.post("/enrich-source-types")
def enrich_source_types(
    limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db)
) -> JSONResponse:
    """Fill ``Source.source_type`` from Wikidata — the NETWORKED enrichment pass.

    Egresses to Wikidata over clearnet (through the guarded factory: kill switch +
    proxy), so the frontend gates it with the one network consent. Refuses up front
    with a clean 409 while airplane mode is engaged (never a traceback). Bounded per
    call (``limit``) since each source costs two lookups; click again to continue."""
    from src.catalog.wikidata_apply import apply_source_types

    try:
        result = apply_source_types(db, limit=limit)
    except RuntimeError as exc:  # the kill-switch up-front refusal
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"mode": "wikidata", **result})


@router.post("/discover-sources")
def discover_sources_endpoint(
    countries: str = Query(..., description="comma-separated ISO-2 country codes, e.g. ke,ng,br"),
    per_spec_limit: int = Query(200, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """DISCOVER new sources from Wikidata for the given countries (enabled:false).

    Adds NEW sources (news orgs / institutions with an official website) as DISABLED
    rows for review -- never enables or scrapes anything on its own. Networked: 409
    under airplane mode, egresses through the guarded factory. Bounded to a handful of
    countries per call (each queries several media types); pick UNDER-REPRESENTED
    countries to keep the catalogue's coverage balanced."""
    codes = [c.strip().lower() for c in countries.split(",") if c.strip()]
    if not codes or not all(len(c) == 2 and c.isalpha() for c in codes):
        raise HTTPException(status_code=400, detail="countries must be ISO-2 codes, e.g. ke,ng,br")
    if len(codes) > 12:
        raise HTTPException(status_code=400, detail="at most 12 countries per call (be polite)")
    from src.catalog.discover import discover_sources

    try:
        result = discover_sources(db, codes, per_spec_limit=per_spec_limit)
    except RuntimeError as exc:  # the kill-switch up-front refusal
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"mode": "discovery", **result})


@router.get("/ir-eval-selftest")
def ir_eval_selftest(download: bool = Query(False)) -> JSONResponse:
    """Run the IR retrieval-eval harness self-test (keyword-engine Phase 3).

    Proves the metric MECHANISM (nDCG/MRR/Recall/P@k + per-language aggregation + the
    conflation recall/precision deltas + the regression gate) on a hand-computed fixture —
    no DB, no network, no score. A real retrieval measurement needs a human-judged GOLD
    SET over your own corpus (graded 0/1/2), fed to evaluate_against_corpus(); this
    endpoint verifies the harness is correct so that measurement can be trusted. With
    ``download=1`` it comes back as a dated attachment."""
    from src.analytics.ir_eval import run_ir_eval_selftest

    log = run_ir_eval_selftest()
    headers = {}
    if download:
        fname = f"oo-ir-eval-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/ir-eval")
def ir_eval(
    gold_path: str = Query(..., description="server-side path to a JSON gold set"),
    weights_a: str | None = Query(None, description="BM25F (title,body) weights A, e.g. '1,1'"),
    weights_b: str | None = Query(None, description="BM25F (title,body) weights B, e.g. '4,1'"),
    k: int = Query(10, ge=1, le=100),
    download: bool = Query(False),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Run the IR retrieval-eval over a human-judged GOLD SET file (the measure-before-trust
    loop, keyword-engine P3) — the in-app path that consumes what the library + template
    (``configs/ir_eval/gold_set.example.json``) make.

    Without weights it scores the LIVE search at the current BM25F default. With BOTH
    ``weights_a`` and ``weights_b`` it A/Bs two (title,body) weight sets via
    ``conflation_delta`` (recall/precision/ndcg reported SEPARATELY, no blended score), so
    the P5.1 default can be chosen on evidence. The gold set is corpus-specific + graded
    0/1/2; ``400`` on a missing/malformed gold set or bad weights (never a silent skip).
    ``download=1`` returns a dated attachment to send back."""
    from src.analytics.ir_eval import (
        GoldSetError,
        bm25f_weight_ab,
        evaluate_against_corpus,
        load_gold_set,
    )

    def _weights(spec: str) -> tuple[float, float]:
        parts = [p.strip() for p in spec.split(",")]
        if len(parts) != 2:
            raise ValueError("weights must be 'title,body' (two numbers)")
        return (float(parts[0]), float(parts[1]))

    try:
        gold = load_gold_set(gold_path)
        if weights_a and weights_b:
            out = bm25f_weight_ab(db, gold, weights_a=_weights(weights_a),
                                  weights_b=_weights(weights_b), k=k)
        elif weights_a or weights_b:
            raise ValueError("provide BOTH weights_a and weights_b to A/B, or neither")
        else:
            out = evaluate_against_corpus(db, gold, k=k)
    except GoldSetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"bad weights: {exc}") from exc

    payload = {"kind": "ir-eval", "n_queries": len(gold), "k": k, "result": out}
    headers = {}
    if download:
        fname = f"oo-ir-eval-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(payload, headers=headers)


@router.get("/home-cards")
def home_card_diagnostics(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """Home-card (Lead) CLICK diagnostics (field report 2026-06-22): for every card the
    briefing currently produces, what clicking it loads — its EXACT corpus (article_ids,
    "hard-linked") or a fuzzy TEXT SEARCH of the card's seed term ("search-fallback").
    A search-fallback whose live count differs wildly from the card's own n means the
    click LOSES the card's corpus (the 'no hard linking' bug). Read-only, no score; with
    ``download=1`` it comes back as a dated attachment to send back for the fix loop."""
    from src.briefing.card_diagnostics import card_click_diagnostics

    log = card_click_diagnostics(db)
    headers = {}
    if download:
        fname = f"oo-home-cards-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/keyword-engine")
def keyword_engine(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """Keyword-engine efficacy + performance report.

    Composition · entity precision · cross-language TRANSLATION coverage (tracks the
    ring work) · tag coverage · per-language functional status · the self-test ·
    indicative timings (extraction + grouped-query). Bounded, read-only, NO score —
    diff two of these over time to see whether an optimization landed. With
    ``download=1`` it returns as a dated attachment."""
    from src.analytics.engine_report import keyword_engine_report

    report = keyword_engine_report(db)
    headers = {}
    if download:
        fname = f"oo-keyword-engine-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/article-length")
def article_length(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """Article-length + cited-source DISTRIBUTIONS, per content type and language
    (Home "Latest in your corpus" slice S0).

    The evidence needed to pick honest thresholds for the Home substance filter
    (min words AND min cited-sources) — no export carried this before. Counts only,
    NO score; word counts for unsegmented languages (zh/ja/th) are flagged so a
    word-gate is never applied to them blindly. With ``download=1`` it returns as a
    dated attachment to send back for calibration."""
    from src.analytics.article_length import article_length_report

    report = article_length_report(db)
    headers = {}
    if download:
        fname = f"oo-article-length-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/keyword-growth")
def keyword_growth(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """The vocabulary-growth curve: cumulative distinct keywords vs cumulative words
    added (maintainer ask 2026-06-24, at 909k keywords).

    The SHAPE diagnoses the junk fraction: a curve that bends over = the vocabulary is
    saturating (new articles reuse known words); a near-straight line (Heaps beta ~ 1) =
    new keywords are still minted for almost every word added (markup/code/unsegmented
    junk). Read DECRYPT-FREE from keyword_mentions (the denormalised observed_on +
    covering index) — no article decrypt. Counts only, NO score. With ``download=1`` it
    returns as a dated attachment to send back for the keyword-reduction loop."""
    from src.analytics.keyword_growth import keyword_growth_curve

    curve = keyword_growth_curve(db)
    headers = {}
    if download:
        fname = f"oo-keyword-growth-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(curve, headers=headers)


@router.get("/dates")
def date_extraction_log(
    db: Session = Depends(get_db),
    scan: int = Query(1500, ge=1, le=10000, description="Max articles to scan for the aggregates (recent first)."),
    sample: int = Query(60, ge=1, le=400, description="How many articles to include in the detailed sample (worst misses first)."),
    days: int | None = Query(None, ge=1, le=36500, description="Only articles published within the last N days."),
    lang: str | None = Query(None, description="Only articles whose language starts with this code (e.g. 'fr')."),
    content_chars: int = Query(1200, ge=0, le=8000, description="Per-sampled-article content excerpt budget."),
) -> JSONResponse:
    """The date-extraction diagnostics log (maintainer↔developer channel): for a
    bounded scan of articles, what the date extractor CAUGHT versus what the text
    LOOKS LIKE — so the extractor can be optimized from real corpus evidence.

    Per article it pairs the live extractor (run exactly as ingest does — the
    article's own publication date as anchor + its language) with a permissive
    recall probe (bare years, CJK 年月日 dates, numeric d/m/y, month/weekday/
    relative words). The probe deliberately OVER-matches: the date-like text it
    flags that the extractor did not turn into a tag is the material for spotting a
    missing pattern. Probe hits are CANDIDATES, never confirmed dates.

    The aggregates cover the whole scan; the per-language table (with
    ``in_month_vocab``) is the clearest signal of a vocabulary gap — a language the
    extractor has no month names for shows near-zero coverage. The detailed sample
    is sorted worst-actionable-miss first. ``stored_tags`` shows what is actually
    persisted for each sampled article, which can differ from the live extractor if
    the article was indexed before an extractor change (re-index to refresh).
    Bounded, on-demand, local; nothing is transmitted. No scores.
    """
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta, timezone

    from src.timemap import datediag, datestore

    today = _date.today()
    # First pass scans only what the aggregates need (title is re-queried for the
    # small sample), so the heavy content column is the only large read here.
    rows = db.query(
        Article.id,
        Article.language,
        Article.published_at,
        Article.created_at,
        Article.content,
    )
    if days:
        rows = rows.filter(Article.published_at >= _dt.now(timezone.utc) - timedelta(days=days))
    if lang:
        rows = rows.filter(Article.language.like(f"{lang}%"))
    rows = rows.order_by(Article.published_at.desc()).limit(scan)

    total_articles = int(db.query(func.count(Article.id)).scalar() or 0)
    scanned = with_extracted = extracted_total = datelike_no_extract = 0
    prec = {"day": 0, "month": 0}
    hist = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5+": 0}
    per_lang: dict[str, dict] = {}
    probe_kinds: dict[str, int] = {}
    # Light candidates only (id + the three sort keys) so a large scan stays
    # memory-cheap; the heavy per-article records are rebuilt for the sample alone.
    light: list[tuple] = []

    for aid, language, pub, created, content in rows.yield_per(200):
        scanned += 1
        anchor_dt = pub or created
        anchor = anchor_dt.date() if anchor_dt else None
        a = datediag.analyze_article(content, language=language, anchor=anchor, today=today)
        ne = a["n_extracted"]
        extracted_total += ne
        with_extracted += 1 if ne else 0
        for c in a["extracted"]:
            if c.get("precision") in prec:
                prec[c["precision"]] += 1
        hist["5+" if ne >= 5 else str(ne)] += 1
        for k, n in a["probe_by_kind"].items():
            probe_kinds[k] = probe_kinds.get(k, 0) + n
        if a["n_date_like"] and ne == 0:
            datelike_no_extract += 1
        bl = datediag.base_language(language)
        pl = per_lang.setdefault(
            bl,
            {
                "articles": 0,
                "with_extracted": 0,
                "extracted_total": 0,
                "date_like_total": 0,
                "in_month_vocab": bl in datediag.MONTH_VOCAB_LANGS,
            },
        )
        pl["articles"] += 1
        pl["with_extracted"] += 1 if ne else 0
        pl["extracted_total"] += ne
        pl["date_like_total"] += a["n_date_like"]
        light.append((a["actionable_gap"], a["n_date_like"], -ne, aid))

    # Worst actionable miss first (then most date-like text, then fewest extracted).
    light.sort(reverse=True)
    chosen_ids = [t[3] for t in light[:sample]]

    sample_rows: list[dict] = []
    if chosen_ids:
        by_id = {
            r.id: r
            for r in db.query(
                Article.id,
                Article.title,
                Article.language,
                Article.published_at,
                Article.created_at,
                Article.content,
            ).filter(Article.id.in_(chosen_ids))
        }
        for aid in chosen_ids:  # preserve the worst-first order
            r = by_id.get(aid)
            if r is None:
                continue
            anchor_dt = r.published_at or r.created_at
            anchor = anchor_dt.date() if anchor_dt else None
            a = datediag.analyze_article(r.content, language=r.language, anchor=anchor, today=today)
            sample_rows.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "language": r.language,
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                    "anchor": anchor.isoformat() if anchor else None,
                    "actionable_gap": a["actionable_gap"],
                    "n_extracted": a["n_extracted"],
                    "n_date_like": a["n_date_like"],
                    "extracted": a["extracted"],
                    "stored_tags": datestore.for_article(db, r.id),
                    "date_like_in_text": a["date_like_in_text"],
                    "content_excerpt": (r.content or "")[:content_chars],
                    "content_truncated": bool(r.content and len(r.content) > content_chars),
                }
            )

    per_language = {
        lg: {
            **v,
            "coverage_pct": (
                round(100.0 * v["with_extracted"] / v["articles"], 1) if v["articles"] else 0.0
            ),
        }
        for lg, v in sorted(per_lang.items(), key=lambda kv: -kv[1]["articles"])
    }

    payload = {
        "corpus": {
            "articles_total": total_articles,
            "scanned": scanned,
            "articles_with_extracted_dates": with_extracted,
            "coverage_pct": round(100.0 * with_extracted / scanned, 1) if scanned else 0.0,
            "extracted_dates_total": extracted_total,
            "precision_distribution": prec,
            "dates_per_article": hist,
            "articles_with_datelike_text_but_no_extraction": datelike_no_extract,
        },
        "per_language": per_language,
        "date_like_text_by_kind": probe_kinds,
        "sample": sample_rows,
        "method": (
            "Per article: 'extracted' = the live extractor run exactly as ingest does "
            "(the article's publication date as anchor + its language); "
            "'date_like_in_text' = a PERMISSIVE recall probe (bare years, CJK 年月日, "
            "numeric d/m/y, month/weekday/relative words) that over-matches so its "
            "difference from 'extracted' shows what the extractor missed; 'stored_tags' "
            "= what is actually persisted (can lag the extractor until a re-index). "
            "per_language coverage + in_month_vocab is the vocabulary-gap signal (a "
            "language with no month table shows near-zero coverage). Sample sorted "
            "worst-actionable-miss first (bare years excluded from 'actionable' — the "
            "extractor skips them by design). Aggregates over the whole scan; counts only."
        ),
        "caveat": (
            "The recall probe is HIGH recall, LOW precision — a hit is a candidate, not a "
            "confirmed date (a '2020' may be a quantity; a weekday may be generic). Low "
            "coverage for an out-of-vocabulary language is the expected signal, not a bug. "
            "Bounded scan/sample (says so via 'scanned' vs 'articles_total'); on-demand, "
            "local, never transmitted."
        ),
    }
    body = envelope(
        kind="date-diagnostics",
        query={"scan": scan, "sample": sample, "days": days, "lang": lang},
        count=len(sample_rows),
        payload=payload,
    )
    fname = f"oo-date-diagnostics-{_dt.now().strftime('%Y%m%d')}.json"
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/performance")
def performance_report(
    selftest: bool = True, db: Session = Depends(get_db)
) -> JSONResponse:
    """The PERFORMANCE field report (maintainer-asked 2026-06-12): one local,
    on-click JSON the operator can send back, carrying real evidence from THIS
    machine and THIS corpus — the maintainer↔developer channel pattern.

    Three evidence classes, each with its method stated:
      * passive endpoint latencies — the app's own Prometheus histograms,
        accumulated from REAL interactive use since this boot (no overhead
        added; the middleware was already measuring);
      * environment + store facts — CPUs, RAM, at-rest encryption state, page
        cache/mmap settings, file/page/freelist sizes (real PRAGMA readings);
      * an optional ACTIVE self-test — the hot read handlers timed twice,
        in-process, against the live corpus (labelled in-session: OS and page
        caches reflect real use, so these are warm-path numbers).
    Generated only on click; never transmitted anywhere by the app.
    """
    import os as _os
    import platform
    import sys as _sys
    import time as _time

    from src.api import system as _system
    from src.database.connect import locked_state
    from src.database.session import engine
    from src.paths import data_dir as _data_dir

    db_file = _data_dir() / "open_omniscience.db"

    # -- environment ------------------------------------------------------- #
    vitals = _system._process_vitals()
    try:
        import psutil as _ps

        total_ram = int(_ps.virtual_memory().total)
    except Exception:  # noqa: BLE001 - honest null, never a guess
        total_ram = None
    env = {
        "python": _sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": _os.cpu_count(),
        "total_ram_bytes": total_ram,
        "process_rss_bytes": vitals.get("rss_bytes"),
        "at_rest_state": locked_state(db_file),
        "uptime_s": round(_time.time() - _system._BOOT_TS, 1),
    }

    # -- store facts (real PRAGMA readings) --------------------------------- #
    store: dict = {"db_bytes": db_file.stat().st_size if db_file.exists() else None}
    if engine.url.get_backend_name() == "sqlite":
        with engine.connect() as conn:
            for pragma in (
                "page_size",
                "page_count",
                "freelist_count",
                "journal_mode",
                "cache_size",
                "mmap_size",
            ):
                store[pragma] = conn.execute(text(f"PRAGMA {pragma}")).scalar()
    counts = {
        "articles": int(db.query(func.count(Article.id)).scalar() or 0),
        "sources": int(db.query(func.count(Source.id)).scalar() or 0),
        "keywords": int(db.query(func.count(Keyword.id)).scalar() or 0),
        "keyword_mentions": int(
            db.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar() or 0
        ),
    }

    # Last collection pass: break its fetch_failed count down by reason, so the
    # number is diagnosable (Tor-403 reality vs a real transport/DB problem) and
    # not a raw mystery. From the scheduler's own last result; empty if no pass ran.
    from src.ingest.fetch_verdict import fetch_failed_reasons as _ff_reasons
    from src.scheduler.runner import get_scheduler as _get_scheduler

    _last = _get_scheduler().status().get("last_result") or {}
    _tally_raw = _last.get("tally")
    _last_tally: dict = _tally_raw if isinstance(_tally_raw, dict) else {}
    collection = {
        "last_pass_fetch_failed": int(_last_tally.get("fetch_failed") or 0),
        "fetch_failed_reasons": _ff_reasons(_last),
        "method": (
            "The last scrape pass's fetch failures bucketed by cause (per-reason "
            "counts sum to fetch_failed). http_403 is typically the Tor-block "
            "reality on premium news, NOT asserted as Tor. Counts only, no score."
        ),
    }

    # -- passive latencies: the app's own histograms, real use since boot --- #
    endpoint_latency: list[dict] = []
    try:
        from src.api.main import REQUEST_LATENCY

        for metric in REQUEST_LATENCY.collect():
            series: dict[tuple, dict] = {}
            for s in metric.samples:
                key = (s.labels.get("method", "?"), s.labels.get("endpoint", "?"))
                slot = series.setdefault(key, {"buckets": []})
                if s.name.endswith("_bucket"):
                    slot["buckets"].append((float(s.labels["le"]), s.value))
                elif s.name.endswith("_count"):
                    slot["count"] = s.value
                elif s.name.endswith("_sum"):
                    slot["sum_s"] = s.value
            for (method_, endpoint_), slot in series.items():
                n = slot.get("count", 0)
                if not n:
                    continue
                est = {}
                finite = sorted(b for b in slot["buckets"] if b[0] != float("inf"))
                for q_ in (0.5, 0.95):
                    target = n * q_
                    for le, cum in finite:
                        if cum >= target:
                            est[f"p{int(q_ * 100)}_le_s"] = le
                            break
                    else:
                        # The quantile sits beyond the largest finite bucket —
                        # report that bound honestly instead of a fake number.
                        if finite:
                            est[f"p{int(q_ * 100)}_gt_s"] = finite[-1][0]
                endpoint_latency.append(
                    {
                        "method": method_,
                        "endpoint": endpoint_,
                        "requests": int(n),
                        "total_s": round(slot.get("sum_s", 0.0), 3),
                        "mean_ms": round(slot.get("sum_s", 0.0) / n * 1000, 1),
                        **est,
                    }
                )
        endpoint_latency.sort(key=lambda e: -e["total_s"])
        endpoint_latency = endpoint_latency[:80]
    except Exception:  # noqa: BLE001 - the report must not fail on metrics shape
        endpoint_latency = []

    # -- active self-test: hot read handlers, timed in-process -------------- #
    selftest_rows: list[dict] = []
    if selftest:
        from src.analytics import queries as aq
        from src.api.database import country_coverage, database_stats

        def _timed(name: str, fn) -> None:
            for run in (1, 2):
                t0 = _time.perf_counter()
                try:
                    out = fn()
                    # Streamed responses: consume fully so the cost is real.
                    body_iter = getattr(out, "body_iterator", None)
                    size = None
                    if body_iter is not None and hasattr(body_iter, "__aiter__"):
                        # Starlette wraps sync generators into async iterators;
                        # this sync endpoint runs in a worker thread (no loop),
                        # so a private loop can drain the stream for real.
                        import asyncio

                        async def _drain(it) -> int:
                            total = 0
                            async for c in it:
                                total += len(c.encode("utf-8") if isinstance(c, str) else c)
                            return total

                        size = asyncio.run(_drain(body_iter))
                    elif body_iter is not None:
                        size = sum(len(c.encode("utf-8")) for c in body_iter)
                    selftest_rows.append(
                        {
                            "probe": name,
                            "run": run,
                            "ms": round((_time.perf_counter() - t0) * 1000),
                            **({"bytes": size} if size is not None else {}),
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - report failures honestly
                    selftest_rows.append(
                        {"probe": name, "run": run, "error": str(exc)[:160]}
                    )

        _timed("database_stats", lambda: database_stats(db=db))
        _timed("country_coverage", lambda: country_coverage(db=db))
        _timed("insights_top", lambda: aq.top_terms(db, limit=50))
        _timed("insights_trending", lambda: aq.trending(db))
        _timed("insights_map", lambda: aq.map_data(db))
        _timed("keyword_export_streamed", lambda: keyword_log(db=db))

    payload = {
        "environment": env,
        "store": store,
        "corpus": counts,
        "collection": collection,
        "endpoint_latency_since_boot": {
            "method": (
                "The app's own request-latency histograms (Prometheus middleware), "
                "accumulated from real use since this boot — server-side wall time "
                "per endpoint; p50/p95 are bucket upper bounds (≤), not exact "
                "quantiles. Top 80 by total time."
            ),
            "series": endpoint_latency,
        },
        "selftest": {
            "method": (
                "Hot read handlers timed in-process against the live corpus, two "
                "runs each, streamed bodies fully consumed. In-session numbers: "
                "OS/page caches reflect real use (warm path). No network involved."
            ),
            "ran": bool(selftest),
            "results": selftest_rows,
        },
    }
    body = envelope(
        kind="performance-report", query={"selftest": selftest},
        count=len(selftest_rows) + len(endpoint_latency), payload=payload,
    )
    fname = f"oo-perf-report-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/benchmark")
def benchmark_report(
    repeats: int = Query(3, ge=1, le=10, description="Runs per case (1 = cold only)"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The SCALING benchmark (maintainer-asked 2026-06-19): a repeatable, on-click
    timing of the heavy read paths against THIS corpus on THIS machine — so the
    data-architecture scaling work (denormalised keyword counters, de-N+1
    associations/graph) can be LIVE-tested, with a self-describing log to hand back.

    Each case runs ``repeats`` times (run 1 cold, runs 2..N warm) over a bounded
    query-layer function the UI already calls. The log carries the corpus size, the
    keyword-counter freshness, the columnar engine mode and host facts so a number is
    interpretable away from the machine. READ-ONLY (it does not reconcile the
    counters — it reports their current freshness), bounded, airplane-safe; generated
    only on click and never transmitted. See src/monitoring/benchmark.py.
    """
    from src.monitoring.benchmark import run_benchmark

    payload = run_benchmark(db, repeats=repeats)
    body = envelope(
        kind="scaling-benchmark",
        query={"repeats": repeats},
        count=payload.get("summary", {}).get("cases_run", 0),
        payload=payload,
    )
    fname = f"oo-benchmark-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/rollup-benchmark")
def rollup_benchmark(
    repeats: int = Query(3, ge=1, le=10, description="Timing runs per window"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The WINDOWED-aggregation rollup benchmark (scaling 5A-bis): builds the
    ``keyword_daily`` rollup in-memory over THIS corpus and times the windowed keyword
    aggregation both ways — the live mention scan (the Insights/trends freeze) vs summing
    the rollup — reporting the speedup + a parity check, so the operator can SEE how much
    the rollup helps on their own data before it is wired to the hot path or the persisted
    store is bundled. READ-ONLY, in-memory (never a plaintext file), airplane-safe;
    generated on click only and never transmitted. See src/monitoring/rollup_benchmark.py.
    """
    from src.monitoring.rollup_benchmark import run_rollup_benchmark

    payload = run_rollup_benchmark(db, repeats=repeats)
    body = envelope(
        kind="rollup-benchmark",
        query={"repeats": repeats},
        count=len(payload.get("windows", [])),
        payload=payload,
    )
    fname = f"oo-rollup-benchmark-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/network")
def network_preflight_log() -> JSONResponse:
    """The network-targets diagnostics log (maintainer↔developer channel):
    source preflight verdicts + feed/calendar preflight verdicts + the full
    calendar verdict store — everything needed to optimize the default
    install's source/feed/calendar lists from REAL verdicts."""
    from src.events.feeds import load_verdicts
    from src.monitoring import feed_preflight
    from src.monitoring.preflight import recent_results as source_results

    payload = {
        "sources": source_results(),
        "feeds": feed_preflight.recent_results(),
        "calendar_verdicts": load_verdicts(),
        "method": (
            "Verbatim verdict logs: data/source_preflight.jsonl + "
            "data/feed_preflight.jsonl + the per-feed calendar checks. "
            "Robots verdicts use the standard taxonomy (allowed/disallowed/"
            "blocked/missing/unreachable); nothing is inferred."
        ),
    }
    count = len(payload["sources"]) + len(payload["feeds"]) + len(payload["calendar_verdicts"])
    body = envelope(kind="network-preflight", query={}, count=count, payload=payload)
    fname = f"oo-network-preflight-{datetime.now().strftime('%Y%m%d')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/columnar")
def columnar_status() -> dict:
    """Observability for the derived data-architecture stores (Slice 4 + 6b).

    Honest, network-free: the COLUMNAR engine mode (``persisted`` encrypted /
    ``memory`` fallback / ``unavailable``) and the offline IP-geo DB vintage. Lets the
    maintainer SEE whether persisted-encrypted analytics are active before deciding
    whether to bundle the per-OS crypto extension that enables them. No score."""
    from src.analytics import columnar, rollup_serve
    from src.database.connect import get_passphrase
    from src.geo import ip_geo

    return {
        "columnar": columnar.status(get_passphrase()),
        # The in-memory windowed rollup serve — AUTOMATIC when duckdb is available; this
        # shows the mode (auto/forced) + whether it's built, so the self-tuning is visible.
        "rollup_serve": rollup_serve.status(),
        "ip_geo": ip_geo.freshness() | {"attribution": ip_geo.ATTRIBUTION},
        "method": (
            "Derived stores are disposable accelerators; the encrypted SQLCipher store is "
            "always the source of truth. The columnar store is encrypted-under-the-same-"
            "passphrase OR in-memory, never plaintext. Counts/state only, no score."
        ),
    }


@router.get("/freshness")
def external_freshness() -> dict:
    """Self-report the freshness of every registered external artifact (network-free).

    A production install can surface — via the existing maintainer↔dev "click & send the
    bundle" channel — exactly which bundled/pinned things are stale (the IP-geo DB, the
    model catalog, the DuckDB↔crypto-extension coupling, …). Reads the registry
    (configs/external_artifacts.yml); makes NO network call (the 'is upstream newer?'
    watch is a separate consented scheduled job). Counts/state only, no score."""
    from src.maintenance import registry as R

    return R.summary()


@router.get("/debug-bundle")
def debug_bundle(db: Session = Depends(get_db)) -> JSONResponse:
    """ONE downloadable bundle with everything a developer needs to diagnose a
    live install remotely (maintainer-ruled 2026-06-10: "I'll click every
    download/scrape/refresh button and send you the log"). Sections:

    runtime · corpus shape · scheduler state + run history · every network
    verdict (sources / market feeds / calendars) · per-click import outcomes ·
    law + wiki tracking states · the rolling WARNING+ error log. Verbatim
    records, no inference; generated only on click.
    """
    import json as _json
    import platform
    import sys as _sys

    from src.events.feeds import load_imports, load_verdicts
    from src.monitoring import feed_preflight
    from src.monitoring.collect_perf import recent_samples as _collect_perf_samples
    from src.monitoring.errorlog import recent_errors
    from src.monitoring.errorlog import summary as error_log_summary
    from src.monitoring.field_test import recent_results as _field_test_results
    from src.monitoring.preflight import recent_results as source_results
    from src.paths import data_dir as _data_dir
    from src.scheduler.runlog import recent_runs
    from src.scheduler.runner import get_scheduler

    # -- runtime ----------------------------------------------------------- #
    def _has(mod: str) -> bool:
        import importlib.util

        return importlib.util.find_spec(mod) is not None

    try:
        from sqlalchemy import text as _text

        schema_rev = db.execute(_text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001
        schema_rev = None
    llm: dict = {"available": False}
    try:
        from src.llm.ollama import OllamaClient

        client = OllamaClient()
        if client.is_available():
            llm = {"available": True, "models": client.list_installed()}
    except Exception as exc:  # noqa: BLE001 - loopback-only, best-effort
        llm = {"available": False, "error": str(exc)[:200]}
    from src.ingest import kill_switch_active

    db_file = _data_dir() / "open_omniscience.db"
    runtime = {
        "python": _sys.version.split()[0],
        "platform": platform.platform(),
        "schema_revision": schema_rev,
        "extras": {m: _has(m) for m in ("numpy", "scipy", "pandas", "zstandard", "lz4")},
        "llm": llm,
        "db_bytes": db_file.stat().st_size if db_file.exists() else None,
        "kill_switch": kill_switch_active(),
    }

    # -- corpus shape ------------------------------------------------------ #
    from src.database.models import CommodityPrice, LawDocument, WikiPage

    corpus = {
        "articles": int(db.query(func.count(Article.id)).scalar() or 0),
        "sources": int(db.query(func.count(Source.id)).scalar() or 0),
        "keywords": int(db.query(func.count(Keyword.id)).scalar() or 0),
        "price_points": int(db.query(func.count(CommodityPrice.id)).scalar() or 0),
    }

    # -- per-surface tracking states (real columns, verbatim) --------------- #
    law_docs = [
        {
            "title": d.title,
            "jurisdiction": d.jurisdiction,
            "url": d.url,
            "last_status": d.last_status,
            "last_checked_at": d.last_checked_at.isoformat() if d.last_checked_at else None,
        }
        for d in db.query(LawDocument).order_by(LawDocument.jurisdiction, LawDocument.title).all()
    ]
    wiki_pages = [
        {
            "wiki": p.wiki,
            "title": p.title,
            "missing": p.missing,
            "baseline": p.baseline_revid is not None,
            "last_checked_at": p.last_checked_at.isoformat() if p.last_checked_at else None,
        }
        for p in db.query(WikiPage).order_by(WikiPage.wiki, WikiPage.title).all()
    ]

    # -- per-click import outcomes ----------------------------------------- #
    imports_path = _data_dir() / "import_results.jsonl"
    import_results = []
    if imports_path.exists():
        for ln in imports_path.read_text(encoding="utf-8").splitlines()[-50:]:
            try:
                import_results.append(_json.loads(ln))
            except ValueError:
                continue

    _recent_errors = recent_errors(300)
    payload = {
        "runtime": runtime,
        "corpus": corpus,
        "scheduler": {"status": get_scheduler().status(), "recent_runs": recent_runs(30)},
        "network": {
            "sources": source_results(),
            "feeds": feed_preflight.recent_results(),
            "calendar_verdicts": load_verdicts(),
        },
        "imports": import_results,
        "calendar_imports": {
            k: {"events": len(v.get("events", {})), "imported_at": v.get("imported_at")}
            for k, v in load_imports().items()
        },
        "law_documents": law_docs,
        "wiki_pages": wiki_pages,
        # Collection-performance timeline + end-of-pass bottleneck classification
        # (download rate, in-flight fetches, writer-gate contention, CPU/memory).
        # The bandwidth governor's own log — what to read when collection is slow.
        "collect_perf": _collect_perf_samples(),
        # TEMPORARY (0.0.8 live-test cycle): automated field-test outcomes —
        # see src/monitoring/field_test.py for purpose + the OO_FIELD_TEST=0
        # opt-out. Will be removed when the cycle ends.
        "field_test": _field_test_results(),
        "errors": _recent_errors,
        # Honest metadata so a reader can tell whether the error window is CURRENT
        # (the rolling file survives reinstalls, so old-session errors can look
        # live). "*_this_session" counts are since the latest boot marker, so a
        # clean current run reads zero — the direct answer to "is the data-loss
        # happening now?" (P0-5; field test 2026-06-22).
        "error_log": error_log_summary(),
        "method": (
            "Verbatim runtime facts, tracking states, network verdicts, per-click "
            "import outcomes and the rolling WARNING+ error log. Nothing inferred; "
            "exported only on the operator's click."
        ),
    }
    body = envelope(kind="debug-bundle", query={}, count=len(_recent_errors), payload=payload)
    fname = f"oo-debug-bundle-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


def _member_bytes(value) -> bytes:
    """Encode any diagnostics endpoint return (a plain dict, a JSONResponse, or a
    StreamingResponse) into the bytes to write into the all-diagnostics ZIP."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body_iter = getattr(value, "body_iterator", None)
    if body_iter is not None:
        # A streamed response (the keyword log digest): drain it for real. This sync
        # handler runs in a worker thread (no running loop), so a private loop is safe
        # — the exact pattern performance_report uses to time streamed bodies.
        import asyncio

        async def _drain(it) -> bytes:
            parts: list[bytes] = []
            async for chunk in it:
                parts.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
            return b"".join(parts)

        return asyncio.run(_drain(body_iter))
    return bytes(getattr(value, "body", b""))  # JSONResponse / Response


@router.get("/all")
def all_diagnostics(db: Session = Depends(get_db)) -> Response:
    """EVERY diagnostics log in ONE archive (maintainer field report 2026-06-22:
    "there should be the option to download all diagnostics logs at once").

    A single click instead of nine. Each member is generated by the same function its
    own button calls, wrapped so one failing log never aborts the bundle (it writes a
    ``<name>.error.txt`` and records it in the manifest). The full keyword CORPUS dump
    is NOT here — it has its own sized/paged export ("All keywords") — so this carries
    the bounded keyword-log DIGEST instead. Read-only, on-demand, never transmitted."""
    import io
    import platform
    import sys as _sys
    import zipfile

    members: list[tuple[str, object]] = [
        ("debug-bundle.json", lambda: debug_bundle(db=db)),
        ("home-cards.json", lambda: home_card_diagnostics(download=False, db=db)),
        ("keyword-engine.json", lambda: keyword_engine(download=False, db=db)),
        ("keyword-selftest.json", lambda: keyword_selftest(download=False)),
        ("keyword-log-digest.json", lambda: keyword_log(db=db, digest=True, fmt="json")),
        (
            "date-extraction.json",
            lambda: date_extraction_log(
                db=db, scan=1500, sample=60, days=None, lang=None, content_chars=1200
            ),
        ),
        ("network.json", lambda: network_preflight_log()),
        ("performance.json", lambda: performance_report(selftest=True, db=db)),
        ("benchmark.json", lambda: benchmark_report(repeats=2, db=db)),
        ("columnar.json", lambda: columnar_status()),
        ("freshness.json", lambda: external_freshness()),
    ]
    results: list[dict] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, fn in members:
            try:
                z.writestr(name, _member_bytes(fn()))  # type: ignore[operator]
                results.append({"file": name, "ok": True})
            except Exception as exc:  # noqa: BLE001 - one failing log must not abort the bundle
                z.writestr(name + ".error.txt", str(exc))
                results.append({"file": name, "ok": False, "error": str(exc)[:300]})
        manifest = {
            "export_schema": "oo-export-1",
            "kind": "all-diagnostics",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "python": _sys.version.split()[0],
            "platform": platform.platform(),
            "members": results,
            "note": (
                "Every diagnostics log in one archive (the maintainer↔developer channel). "
                "The full keyword corpus dump is NOT here — it has its own sized/paged "
                "export ('All keywords'); this carries the bounded keyword-log DIGEST "
                "instead. Generated only on click; nothing is transmitted by the app."
            ),
        }
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    fname = f"oo-all-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
