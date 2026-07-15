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

import contextlib
import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
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
from src.database.read_snapshot import read_only_db
from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job
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
    # Field finding C: this heavy two-scan export contended with the live scrape. Run it
    # on a DEDICATED read-only (query_only) WAL-snapshot connection so it can never take
    # the write gate or stall a writer, never occupies a shared-pool slot for the whole
    # streamed scan, and reads one consistent snapshot (src.database.read_snapshot).
    db: Session = Depends(read_only_db),
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
            # S7: the per-keyword totals a SECOND full GROUP BY scan used to recompute now come
            # from the ONE scan below (byte-identical), keyed kid -> (mentions, articles,
            # first_seen, last_seen).
            totals: dict[int, tuple[int, int, str | None, str | None]] = {}
            _cur_kid: int | None = None
            _counts: dict[str, int] = {}
            _srcs: dict[int, int] = {}
            _m = 0
            _a = 0
            _first: str | None = None
            _last: str | None = None

            def _finalize(kid, counts, srcs, m, a, first, last) -> None:
                if kid is None or not counts:
                    return
                totals[kid] = (m, a, first, last)
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

            for kid, aid, cnt, obs in db.execute(
                text(
                    "SELECT keyword_id, article_id, count, observed_on"
                    " FROM keyword_mentions ORDER BY keyword_id"
                )
            ):
                if kid != _cur_kid:
                    _finalize(_cur_kid, _counts, _srcs, _m, _a, _first, _last)
                    _cur_kid, _counts, _srcs = kid, {}, {}
                    _m, _a, _first, _last = 0, 0, None, None
                lg = art_lang.get(aid, "?")
                _counts[lg] = _counts.get(lg, 0) + 1
                sid = art_src.get(aid)
                if sid is not None:
                    _srcs[sid] = _srcs.get(sid, 0) + 1
                # S7: the per-keyword totals (mentions / distinct articles / first-last
                # observed) accumulate in THIS pass. A row is unique per (keyword, article)
                # under the covering index, so a per-keyword row count == COUNT(DISTINCT
                # article_id); MIN/MAX(observed_on) ignore NULL exactly as SQL does.
                _m += cnt or 0
                _a += 1
                if obs is not None:
                    if _first is None or obs < _first:
                        _first = obs
                    if _last is None or obs > _last:
                        _last = obs
            _finalize(_cur_kid, _counts, _srcs, _m, _a, _first, _last)

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

            # Totals, mentions-desc — from the ONE mention scan above (no second
            # GROUP BY scan); the quota decides survivors ON THE FLY, so the
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
            # S7: iterate the totals gathered by the ONE scan above, sorted mentions-desc
            # then keyword_id-asc — byte-identical to the retired
            # ``GROUP BY keyword_id ORDER BY m DESC, keyword_id ASC`` second full scan.
            for kid, (m, a, first, last) in sorted(
                totals.items(), key=lambda kv: (-kv[1][0], kv[0])
            ):
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


def _enrich_source_types_worker(ctx, *, limit: int) -> dict:
    """The Wikidata source-type enrichment, off the request thread (field test Item 8 P1).
    Opaque to progress (apply_source_types loops internally); cancel is soft — it takes
    effect when the bounded ``limit`` pass returns. Its own write_lock keeps the gate
    window bounded to the final commit."""
    from src.catalog.wikidata_apply import apply_source_types
    from src.database.session import session_scope

    with session_scope() as db:
        return apply_source_types(db, limit=limit)


_ENRICH_JOB = register_job(
    BackgroundJob(
        "enrich-source-types", "Enriching source types (Wikidata)", _enrich_source_types_worker,
        is_writer=True,
    )
)


@router.post("/enrich-source-types")
def enrich_source_types(limit: int = Query(200, ge=1, le=2000)) -> JSONResponse:
    """Fill ``Source.source_type`` from Wikidata — the NETWORKED enrichment pass, run as a
    BACKGROUND JOB so it no longer freezes the app for ~8 min (field test 2026-07-08,
    Item 8 P1). Egresses to Wikidata over clearnet (through the guarded factory: kill switch
    + proxy), so the frontend gates it with the one network consent. Refuses up front with a
    clean 409 while airplane mode is engaged. Bounded per call (``limit``) since each source
    costs two lookups; click again to continue. Poll ``/enrich-source-types/status`` or the
    task manager for progress."""
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise HTTPException(status_code=409, detail="network refused: airplane mode is engaged")
    try:
        return JSONResponse({"mode": "wikidata", "started": True, "job": _ENRICH_JOB.start(limit=limit)})
    except RuntimeError:
        return JSONResponse({"mode": "wikidata", "started": False, "job": _ENRICH_JOB.status()})


@router.get("/enrich-source-types/status")
def enrich_source_types_status() -> JSONResponse:
    """Live status of the background Wikidata source-type enrichment."""
    return JSONResponse(_ENRICH_JOB.status())


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


@router.get("/perception-eval-selftest")
def perception_eval_selftest(download: bool = Query(False)) -> JSONResponse:
    """S6.5: run the LLM-perception (who/where/when) eval-harness self-test — the GATE for the
    perception track (harness before any extraction feature, the ruled order). Proves the
    scoring MECHANISM (precision/recall/HALLUCINATION-rate per stratum vs a synthetic gold set;
    place string vs coordinate scored separately; de-US-centring split) on a hand-computed
    fixture — deterministic, no model, no network, no score. A real model is measured against
    the rule-based baseline via evaluate_perception() before it is trusted; this verifies the
    harness is correct so that measurement can be. ``download=1`` returns a dated attachment."""
    from src.analytics.perception_eval import run_perception_eval_selftest

    log = run_perception_eval_selftest()
    headers = {}
    if download:
        fname = f"oo-perception-eval-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/keyword-triage-selftest")
def keyword_triage_selftest(download: bool = Query(False)) -> JSONResponse:
    """§8: run the LLM keyword-triage self-test — the measure-before-trust GATE before any real
    triage run. Proves the MECHANISM (the constrained-verdict parser · echo-back validation ·
    canaries · Ollama-timing pass-through · the bench metrics reported ALONE) on a deterministic
    STUB — no model, no network, no score, and NEVER the trusted keyword index (triage is
    EXPORT-ONLY JSONL). The real batch + the 7-model bench are operator-run on the Ollama rig
    (§8.3: a CPU-only box understates the real rig); this verifies the harness is correct so
    that measurement can be trusted. ``download=1`` returns a dated attachment."""
    from src.ai_layer.triage import run_triage_selftest

    log = run_triage_selftest()
    headers = {}
    if download:
        fname = f"oo-keyword-triage-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/recursive-loop")
def recursive_loop(download: bool = Query(False)) -> JSONResponse:
    """§6: the recursive-improvement loop SELF-INVENTORY — imports + runs each of the loop's own
    mechanism-proof GATES (the keyword / IR-eval / perception / keyword-triage self-tests) and
    reports per-gate importable/passed/error, so the recursive-improvement agent (or the
    maintainer) knows the MEASUREMENT INSTRUMENTS themselves are trustworthy before acting on any
    diagnostic number ("the instruments improve, which improves the loop"). Read-only,
    deterministic, no DB / no network, no score; degrades loudly (an un-importable or raising gate
    is reported with its error, never a fabricated green). ``download=1`` returns a dated
    attachment. NOTE: §6's ui_walk (screenshot/console walk) + the AppVM runner are browser/VM-
    gated and are not part of this in-process check."""
    from src.monitoring.recursive_loop import recursive_loop_report

    log = recursive_loop_report()
    headers = {}
    if download:
        fname = f"oo-recursive-loop-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/kpi")
def kpi(download: bool = Query(False)) -> JSONResponse:
    """R1 (V1_PATHWAY §2.3): the read-only K1–K14 KPI SNAPSHOT — the V1 definition made
    mechanical so the KPI differ (scripts/kpi_diff.py) can classify improved/regressed between
    two cycles. Every metric carries a declared direction-of-goodness + target + an honest
    verdict (green / red / not-measurable-here — NEVER a fabricated pass). NO composite. This GET
    reads ONLY the cheap in-process instruments (the latency reservoir K2, the locale files K11);
    every expensive or operator/gold-set/CI-gated metric reports not-measurable-here rather than
    triggering a heavy crunch. Plain def (threadpool). ``download=1`` returns a dated attachment."""
    from src.monitoring.kpi import kpi_snapshot

    log = kpi_snapshot()
    headers = {}
    if download:
        fname = f"oo-kpi-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/search-timing")
def search_timing(download: bool = Query(False)) -> JSONResponse:
    """§4: the per-search intra-request timing aggregate — per-phase (FTS MATCH · content fetch ·
    serialization) percentiles over a bounded recent-window of instrumented searches, and the
    MEASURED dominant phase (highest p95 wall-clock = the §4 optimization target chosen by
    evidence, not theory). Read-only; degrades to an honest empty report before any search is
    instrumented (wiring instrument_search into the search endpoint on the operator's live
    encrypted corpus is the §4 CI/operator step — see search_timing.py). No composite score.
    ``download=1`` returns a dated attachment."""
    from src.monitoring.search_timing import search_timing_report

    log = search_timing_report()
    headers = {}
    if download:
        fname = f"oo-search-timing-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/search-timing-selftest")
def search_timing_selftest(download: bool = Query(False)) -> JSONResponse:
    """§4: prove the search-timing MECHANISM on a deterministic injected clock — the per-phase
    wall-clock timer, the percentile aggregate, and (the point of the instrument) that the
    dominant phase is chosen by MEASURED p95, not by insertion order. No browser, no network, no
    DB, no live corpus, no score; a regression reddens both this endpoint and CI. ``download=1``
    returns a dated attachment."""
    from src.monitoring.search_timing import run_search_timing_selftest

    log = run_search_timing_selftest()
    headers = {}
    if download:
        fname = f"oo-search-timing-selftest-{datetime.now().strftime('%Y%m%d')}.json"
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


@router.get("/gold-builder/sample")
def gold_builder_sample(
    n_queries: int = Query(15, ge=1, le=60),
    per_query: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """S5.3: sample grading candidates for the IR gold-set BUILDER — the top corpus keywords
    + their live search results (never invents a query; search history is not stored). The
    maintainer grades each result 0/1/2 in the panel, then saves via /gold-builder/save."""
    from src.analytics.gold_builder import sample_queries

    return sample_queries(db, n_queries=n_queries, per_query=per_query)


class _GoldBuilderSaveBody(BaseModel):
    path: str
    queries: list[dict] = Field(default_factory=list)


@router.post("/gold-builder/save")
def gold_builder_save(body: _GoldBuilderSaveBody) -> dict:
    """S5.3: write the graded queries as the EXACT ir_eval gold-set JSON to a server-side
    path, VALIDATED by round-trip through load_gold_set (400 on a structural problem or an
    empty set — never a silent bad file). Returns the coverage meter (queries graded per
    language / axis, n). Closes the measure-before-trust loop for OO_FAMILY_LEMMA + the BM25F
    default: the graded file feeds GET /api/diagnostics/ir-eval."""
    from src.analytics.gold_builder import build_and_save_gold_set
    from src.analytics.ir_eval import GoldSetError

    try:
        return build_and_save_gold_set(body.path, body.queries)
    except (GoldSetError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/lemma-preview")
def lemma_preview(
    top_n: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """S5.4: what OPT-IN lemmatization (OO_FAMILY_LEMMA, default OFF) WOULD merge among the
    top keywords — the precision-review instrument surfaced in the Diagnostics panel so the
    maintainer eyeballs the candidate conflations (and notes a wrong one for the
    _MISLEMMA_DENYLIST) BEFORE flipping the default. Read-only, no score; honest
    'unavailable' when the optional simplemma is absent."""
    from src.analytics.engine_report import lemma_preview_report

    return lemma_preview_report(db, top_n=top_n)


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


@router.get("/power-profile")
def power_profile(
    profile: str = Query("optimized"), download: bool = Query(False)
) -> JSONResponse:
    """§7: the published power-profile knob table + the effective values for ``profile`` (Low /
    Optimized / Max). Read-only, no score. A profile changes RESOURCE SPEND only — never data
    visibility or a caveat; Optimized IS the current default (selecting it changes nothing), and
    Low/Max are PROVISIONAL until measured on the GAMMA harness. Degrades loudly on a bad profile
    name. ``download=1`` returns a dated attachment. (The active-profile CHIP + suggest-a-lower-
    level proposal are browser-gated; this endpoint is the inspectable table.)"""
    from src.config.power_profiles import power_profile_report

    report = power_profile_report(active_profile=profile)
    headers = {}
    if download:
        fname = f"oo-power-profile-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/power-profile-selftest")
def power_profile_selftest(download: bool = Query(False)) -> JSONResponse:
    """§7: prove the power-profile mechanism — Optimized is byte-identical to the current defaults,
    an explicit override wins, an unknown profile fails loud, no score leaks. Deterministic, no
    env/DB/network. ``download=1`` returns a dated attachment."""
    from src.config.power_profiles import run_power_profile_selftest

    log = run_power_profile_selftest()
    headers = {}
    if download:
        fname = f"oo-power-profile-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


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


@router.get("/non-article-scan")
def non_article_scan(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """Retroactive NON-ARTICLE scan (Slice 4a review half): per-reason counts + a bounded id sample
    of the already-stored URL-shaped non-articles (nav/index/tag/tool/section/homepage pages the
    #659 ingest filter now stops going forward). The operator's REVIEW data before a reversible
    quarantine.

    READ-ONLY, COUNT-ONLY — classifies each article on its stored url + word_count via the #659
    classifier (text=None → URL-shape rules only; Article.content is NEVER decrypted). A conservative
    UNDERCOUNT (the boilerplate-wall rule needs the body) that never flags a real article. Plain
    ``def`` → threadpool. ``download=1`` returns a dated attachment."""
    from src.analytics.non_article_scan import scan_non_article_candidates

    report = scan_non_article_candidates(db)
    headers = {}
    if download:
        fname = f"oo-non-article-scan-{datetime.now().strftime('%Y%m%d')}.json"
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


# --------------------------------------------------------------------------- #
# TEMPORARY / REMOVABLE diagnostic — Source & article quality triage bundle.
# THROWAWAY: delete this endpoint + its Settings→Diagnostics button once the
# external analyst has used the export to decide, per source, exclude/optimise/keep.
# --------------------------------------------------------------------------- #
@router.get("/source-quality")
def source_quality(
    download: bool = Query(True),
    seed: int = Query(20260713),
    db: Session = Depends(get_db),
) -> Response:
    """TEMPORARY diagnostic: ONE ZIP with everything an analyst needs to decide, per source,
    whether to EXCLUDE it (bad source) / OPTIMIZE the extractor (a mangled real article) / KEEP it
    (a genuine edge). Detects non-articles THREE independent ways (per-article keyword-stat
    outliers · a text sample from three selectors · per-source keyword fingerprints).

    READ-ONLY, EXPORT-ONLY (no writes to any table), no network, NO composite score — every flag is
    a deduced candidate with its raw value + cohort baseline + n. Plain ``def`` → runs in the
    threadpool (off the event loop); COUNT-ONLY over the whole corpus (the codec decrypts each
    article page once, the documented diagnostic cost); Article.content is decrypted ONLY for the
    bounded text heads of the SAMPLED subset. Private newsletter/mailbox bodies are gated behind
    ``OO_QUALITY_INCLUDE_NEWSLETTER_TEXT`` (default off → counts+metadata only). ``seed`` fixes the
    random-per-source control for reproducibility."""
    import io
    import zipfile

    from src.analytics.source_quality import build_quality_report_files

    include_nl = os.getenv("OO_QUALITY_INCLUDE_NEWSLETTER_TEXT", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    files = build_quality_report_files(
        db,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        seed=seed,
        include_newsletter_text=include_nl,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in files.items():
            z.writestr(name, data)
    fname = f"oo-source-quality-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/source-audit")
def source_audit(
    download: bool = Query(False),
    with_furniture: bool = Query(True),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Part-1 Phase-1 STANDING source auditor (FLAG-ONLY this session, ruling Q2a). Per-source
    extraction-VALIDITY status (healthy/watch/degraded/failing) = the categorical rollup of a LIST of
    cohort-relative criteria, each carrying its value + the same-language cohort baseline + n — NEVER
    a blended score. Audits whether a source's scrapes are usable ARTICLES (vs nav/stub/paywall/
    wrong-DOM pages), NEVER editorial merit: terse or atypical prose is legitimate variety and can
    never reach degraded/failing for it (only the furniture-repetition extraction-failure signature,
    corroborated, can).

    READ-ONLY, COUNT-ONLY — reuses the source_quality collectors, so Article.content is never
    decrypted (``with_furniture`` adds a bounded, seeded per-source keyword query). Plain ``def`` →
    threadpool (off the event loop). The ``auto_demote_candidate`` field is computed with the
    auto-demote machinery DEFAULT-OFF (so it is always False here) — this session FLAGS only; enabling
    auto-demote is a later maintainer action gated on the Phase-0 calibration, and even then fires
    only on the extraction-failure signature, never on structural style, never on an allowlisted
    source. A per-region flag-distribution self-audit rides along (the de-US-centring guardrail).
    ``OO_SOURCE_AUDIT_ALLOWLIST`` (comma-separated domains) caps a trusted atypical source at 'watch'.
    ``download=1`` returns a dated attachment."""
    from src.analytics.source_audit import audit_sources

    allow = {d.strip() for d in os.getenv("OO_SOURCE_AUDIT_ALLOWLIST", "").split(",") if d.strip()}
    report = audit_sources(db, allowlist=allow, with_furniture=with_furniture)
    headers = {}
    if download:
        fname = f"oo-source-audit-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/source-audit-selftest")
def source_audit_selftest(download: bool = Query(False)) -> JSONResponse:
    """Prove the auditor's PURE mechanism (flag_criteria / derive_status / should_auto_demote /
    region self-audit) — no DB, no network, no score. The load-bearing checks: the extraction-failure
    source is failing; an atypical-but-valid (terse-prose) source is NOT (never worse than watch);
    auto-demote is default-off and never fires on an allowlisted source; a small cohort gets no
    baseline. A regression reddens both this endpoint and CI. ``download=1`` returns a dated
    attachment."""
    from src.analytics.source_audit import run_source_audit_selftest

    log = run_source_audit_selftest()
    headers = {}
    if download:
        fname = f"oo-source-audit-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


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


@router.get("/source-coverage-benchmark")
def source_coverage_benchmark(
    repeats: int = Query(3, ge=1, le=10, description="Timing runs per read"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The per-country source-coverage rollup benchmark (D4, scaling 5A-bis): builds the
    ``source_coverage`` rollup in-memory over THIS corpus and times the per-country
    choropleth aggregation both ways — the live scan of articles+sources+mentions (the map
    read) vs reading the cached rows — reporting the speedup, a parity check (the counts
    must match exactly), and the rollup wrapped in the honesty envelope. READ-ONLY,
    in-memory (never a plaintext file), airplane-safe; generated on click only and never
    transmitted. See src/monitoring/source_coverage_benchmark.py.
    """
    from src.monitoring.source_coverage_benchmark import run_source_coverage_benchmark

    payload = run_source_coverage_benchmark(db, repeats=repeats)
    body = envelope(
        kind="source-coverage-benchmark",
        query={"repeats": repeats},
        count=len(payload.get("coverage", {}).get("value", []) or []),
        payload=payload,
    )
    fname = f"oo-source-coverage-benchmark-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
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
    from src.analytics import columnar, map_serve, rollup_serve
    from src.database.connect import get_passphrase
    from src.geo import ip_geo

    return {
        "columnar": columnar.status(get_passphrase()),
        # The in-memory windowed rollup serve — AUTOMATIC when duckdb is available; this
        # shows the mode (auto/forced) + whether it's built, so the self-tuning is visible.
        "rollup_serve": rollup_serve.status(),
        # The in-memory D4 map-coverage serve — AUTOMATIC when duckdb is available since
        # P1.11 (OO_COLUMNAR_MAP_SERVE overrides: 0 off / 1 on); shows the mode + build state.
        "map_serve": map_serve.status(),
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


# -- Recursive-augmentation logs (maintainer 2026-07-02): the app surfaces the
# diagnostics that let a developer find bugs WITHOUT the operator spotting each by eye.
# All read-only, local, no score. -------------------------------------------------- #


class _FrontendError(BaseModel):
    """A browser error the UI captured (recursive-augmentation log #1). Small,
    no-PII by contract — error text + which function/endpoint only."""

    kind: str = Field(default="error", max_length=40)
    message: str = Field(default="", max_length=500)
    source: str | None = Field(default=None, max_length=300)
    endpoint: str | None = Field(default=None, max_length=300)
    lineno: int | None = None
    ui_lang: str | None = Field(default=None, max_length=16)


@router.post("/frontend-error")
def report_frontend_error(err: _FrontendError) -> dict:
    """Receive a browser-side error (window.onerror / unhandledrejection / a failed
    fetch) into the rolling log so the "browser-unverified" debt is OBSERVABLE — a
    ``t is not defined`` or a dead click shows in the debug bundle instead of the
    operator finding it one tab at a time. Loopback-only, best-effort, throttled."""
    from src.monitoring.errorlog import note_frontend_error

    note_frontend_error(
        err.kind,
        err.message,
        source=err.source,
        endpoint=err.endpoint,
        lineno=err.lineno,
        ui_lang=err.ui_lang,
    )
    return {"ok": True}


@router.get("/session-forensics")
def session_forensics_report() -> dict:
    """Session forensics (2026-07-09 field event): the data-dir inventory (per-entry
    sizes; orphaned PLAINTEXT backup staging detected loudly), the previous session's
    clean/unclean-end verdict with the collector's last RSS sample (the honest OOM
    inference), and the last unlock's own phase timings + the -wal size before open.
    Local diagnostics only — sizes and app-owned names, never file contents."""
    from src.monitoring.forensics import session_forensics as _sf

    return _sf()


def _p0_validation_last() -> dict:
    """The newest saved P0 validation report (S1.2) — for the debug bundle / the
    all-diagnostics archive. Read-only: it NEVER runs a backup; an operator triggers
    a fresh run explicitly via POST /api/diagnostics/p0-validation. Returns an honest
    ``available:false`` stub when none has been run, never a fabricated pass."""
    from src.monitoring.p0_validation import last_p0_validation_report

    return last_p0_validation_report()


@router.get("/data-dir-persistence")
def data_dir_persistence_report() -> dict:
    """Honest assessment of whether the corpus survives a restart (A11): a RAM-backed (tmpfs)
    data folder or a Qubes disposable VM is PROVABLY volatile; everything else is 'unknown'
    (never a guess). ``at_risk`` + ``note`` drive the one-time nudge toward the opt-in
    persistent OO_DATA_DIR. Never 'stop using disposable VMs' — only how to keep the corpus."""
    from src.monitoring.forensics import data_dir_persistence as _dp

    return _dp()


@router.get("/storage-footprint")
def storage_footprint_report(download: bool = Query(False)) -> JSONResponse:
    """The COMPLETE on-disk footprint across ALL app stores, ITEMIZED per component (A12b):
    the database triple (db/-wal/-shm) + wiki_dumps + osm_regions + backup/restore staging +
    other data-folder contents + the Ollama model store (which lives OUTSIDE data_dir, so a
    data-dir-only total missed it) + a grand total. Answers "how much disk is this app using"
    in one payload. Sizes only, symlinks never followed, file contents never read; no score.
    With ``download=1`` it returns as a dated attachment."""
    from src.monitoring.forensics import storage_footprint as _sf

    payload = _sf()
    body = envelope(
        kind="storage-footprint",
        query={},
        count=len(payload.get("components") or []),
        payload=payload,
    )
    if download:
        fname = f"oo-storage-footprint-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


@router.get("/storage-composition")
def storage_composition_report(
    download: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """Per-table / per-index BYTES of the live store via SQLite dbstat (P1.5) — names
    what the on-disk gigabytes actually ARE (mentions vs articles vs FTS shadow tables vs
    indexes), complementing session forensics' file-level inventory. Read-only,
    deadline-bounded; degrades to an honest ``{available: false, reason}`` block when
    dbstat is not compiled into this SQLite/SQLCipher build — never a 500. Counts/bytes
    only, no score. With ``download=1`` it returns as a dated attachment."""
    from src.monitoring.storage import storage_composition as _sc

    payload = _sc(db)
    body = envelope(
        kind="storage-composition",
        query={},
        count=len(payload.get("tables") or []),
        payload=payload,
    )
    if download:
        fname = f"oo-storage-composition-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


@router.get("/frontend-errors")
def frontend_errors(limit: int = Query(200, ge=1, le=2000)) -> dict:
    """The captured browser errors (log #1) + the rolling-log summary counts."""
    from src.monitoring.errorlog import recent_errors
    from src.monitoring.errorlog import summary as _summary

    records = [r for r in recent_errors(limit=2000) if r.get("level") == "FRONTEND"]
    return {"errors": records[-limit:], "summary": _summary()}


@router.get("/request-latency")
def request_latency() -> dict:
    """Per-route latency percentiles + the event-loop-block watchdog events (log #2).
    The freeze family (unlock / restore / task-manager) points at itself here."""
    from src.monitoring.latency import summary as _summary

    return _summary()


@router.get("/slow-queries")
def slow_queries(explain: int = Query(1, ge=0, le=1), db: Session = Depends(get_db)) -> dict:
    """The slow-query ring buffer + aggregate, and (explain=1) an EXPLAIN QUERY PLAN
    over the heavy analytics on the live store (log #3). Shows scan-vs-index."""
    from src.monitoring.slowquery import summary as _summary

    return _summary(db if explain else None)


@router.get("/schema-drift")
def schema_drift_report(db: Session = Depends(get_db)) -> dict:
    """Live DB schema vs the models + migration head (log #4). A missing index at
    scale is a silent perf bug; this catches it in one glance."""
    from src.monitoring.schema_drift import schema_drift as _drift

    return _drift(db)


@router.get("/integrity")
def corpus_integrity_report(
    sample: int = Query(500, ge=10, le=20000),
    full: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
) -> dict:
    """Corpus-integrity / counter-drift sweep (log #5): orphan/dangling rows, maintained
    counters vs the live aggregate, FTS staleness, FK violations. Bounded + deadline-
    guarded; reports drift, never fixes it."""
    from src.monitoring.integrity import corpus_integrity as _integrity

    return _integrity(db, sample=sample, full=bool(full))


def _debug_bundle_member_budget_s() -> float:
    """Per-member wall-clock budget for the debug bundle (OO_DEBUG_BUNDLE_MEMBER_BUDGET_S,
    default 20s). A member exceeding it is recorded ``{skipped: budget}`` and abandoned, so
    one slow/hung member never stalls the whole bundle. Non-positive/non-finite/invalid ->
    20s; CAPPED to 1 h so a fat-fingered huge value can never overflow ``Thread.join()``'s
    timeout (an OverflowError there would escape the per-member guard and 500 the whole
    bundle) nor emit a non-finite, JSON-invalid ``budget_s``."""
    import math

    try:
        v = float(os.environ.get("OO_DEBUG_BUNDLE_MEMBER_BUDGET_S", "20"))
    except ValueError:
        return 20.0
    if not math.isfinite(v) or v <= 0:
        return 20.0
    return min(v, 3600.0)


@router.get("/debug-bundle")
def debug_bundle(db: Session = Depends(read_only_db)) -> JSONResponse:
    """ONE downloadable bundle with everything a developer needs to diagnose a
    live install remotely (maintainer-ruled 2026-06-10: "I'll click every
    download/scrape/refresh button and send you the log"). Sections:

    runtime · corpus shape · scheduler state + run history · every network
    verdict (sources / market feeds / calendars) · per-click import outcomes ·
    law + wiki tracking states · the rolling WARNING+ error log. Verbatim
    records, no inference; generated only on click.

    HARDENED (S8): the DB is opened READ-ONLY (a ``query_only`` WAL snapshot, so the
    bundle can never take the write gate); EVERY member is individually guarded (a
    raising member records ``{error}``, never aborts the bundle). NON-DB members (which can
    block on a loopback socket or a file read but never touch the DB) run under a per-member
    wall-clock BUDGET on a daemon thread — a member that hangs records ``{skipped: budget}``
    instead of stalling the whole export (the 100 GB field corpus made single members slow
    enough to matter). DB members run INLINE (never on a worker thread — a shared SQLite
    connection is unsafe to touch concurrently), bounded by a statement deadline inside the
    thunk so a runaway query is aborted rather than scanned to the end.
    """
    import json as _json
    import platform
    import sys as _sys
    import threading

    from src.database.maintenance import statement_deadline
    from src.events.feeds import load_imports, load_verdicts
    from src.monitoring import feed_preflight
    from src.monitoring.collect_perf import recent_samples as _collect_perf_samples
    from src.monitoring.errorlog import recent_errors
    from src.monitoring.errorlog import summary as error_log_summary
    from src.monitoring.field_test import recent_results as _field_test_results
    from src.monitoring.forensics import session_forensics as _session_forensics
    from src.monitoring.integrity import corpus_integrity as _corpus_integrity
    from src.monitoring.latency import summary as _latency_summary
    from src.monitoring.storage import storage_composition as _storage_composition
    from src.monitoring.preflight import recent_results as source_results
    from src.monitoring.schema_drift import schema_drift as _schema_drift
    from src.monitoring.slowquery import summary as _slowquery_summary
    from src.paths import data_dir as _data_dir
    from src.scheduler.runlog import recent_runs
    from src.scheduler.runner import get_scheduler

    budget = _debug_bundle_member_budget_s()

    def _err_str(exc) -> str:
        try:
            return str(exc)[:300]
        except Exception:  # noqa: BLE001 - even a broken __str__ must still yield a marker
            return f"<{type(exc).__name__}: unrenderable>"

    def _bounded(fn):
        """Run a DB thunk under a statement deadline (SQL opcode interrupt) so a runaway
        query on the shared connection is aborted instead of scanning a 100 GB table to the
        end. Only for members that do NOT already open their own deadline (avoids nesting —
        an inner deadline's ``finally`` would clear this one's progress handler)."""
        with statement_deadline(db, budget):
            return fn()

    def _member(name: str, thunk, *, threaded: bool = True):
        """Guard ONE bundle member so a failing/slow member never aborts or stalls the whole
        bundle. A raising member records ``{error}`` (even if its exception ``__str__`` is
        itself broken) either way.

        NON-DB members (``threaded=True``, the default) run in a daemon thread with a
        wall-clock BUDGET: they can block on I/O (a loopback socket, a file read) and never
        touch the shared DB connection, so abandoning one past budget as ``{skipped: budget}``
        is safe. DB members (``threaded=False``) run INLINE, because a shared SQLite
        connection can NOT be touched from a lingering worker thread — pysqlite serialises
        statements (a second thread BLOCKS, it does not error) and a SQLAlchemy Session is
        not thread-safe, and ``statement_deadline`` bounds only SQL opcodes, never the Python
        materialisation around them, so a DB worker could not be cleanly abandoned mid-query.
        DB members are instead bounded INSIDE the thunk (``_bounded`` or the member's own
        internal deadline), so they can never hang the bundle and never leave a stray
        progress handler on the connection for the next member."""
        if not threaded:
            try:
                return thunk()
            except Exception as exc:  # noqa: BLE001 - one failing member must not abort the bundle
                return {"error": _err_str(exc)}
        box: dict = {}

        def _run() -> None:
            try:
                box["value"] = thunk()
            except Exception as exc:  # noqa: BLE001 - one failing member must not abort the bundle
                box["error"] = _err_str(exc)

        t = threading.Thread(target=_run, name=f"dbg:{name}", daemon=True)
        t.start()
        t.join(budget)
        if t.is_alive():
            return {"skipped": "budget", "budget_s": budget}
        if "error" in box:
            return {"error": box["error"]}
        return box.get("value")

    # -- runtime ----------------------------------------------------------- #
    def _has(mod: str) -> bool:
        import importlib.util

        return importlib.util.find_spec(mod) is not None

    from src.database.models import CommodityPrice, LawDocument, WikiPage
    from src.ingest import kill_switch_active

    # Each member is a thunk run through _member (individual guard + budget). The DB-bound
    # ones read the shared read-only snapshot; the rest read in-memory/file state.
    # A trivial single-row read, computed INLINE + bounded (never hangs) so the threaded
    # runtime member never touches the shared DB connection from a worker thread.
    def _read_schema_rev():
        from sqlalchemy import text as _text

        try:
            return _bounded(
                lambda: db.execute(_text("SELECT version_num FROM alembic_version")).scalar()
            )
        except Exception:  # noqa: BLE001
            return None

    schema_rev = _read_schema_rev()

    def _runtime() -> dict:
        llm: dict = {"available": False}
        try:
            from src.llm.ollama import OllamaClient

            client = OllamaClient()
            if client.is_available():
                llm = {"available": True, "models": client.list_installed()}
        except Exception as exc:  # noqa: BLE001 - loopback-only, best-effort
            llm = {"available": False, "error": str(exc)[:200]}
        db_file = _data_dir() / "open_omniscience.db"
        return {
            "python": _sys.version.split()[0],
            "platform": platform.platform(),
            "schema_revision": schema_rev,
            "extras": {m: _has(m) for m in ("numpy", "scipy", "pandas", "zstandard", "lz4")},
            "llm": llm,
            "db_bytes": db_file.stat().st_size if db_file.exists() else None,
            "kill_switch": kill_switch_active(),
        }

    def _corpus() -> dict:
        return {
            "articles": int(db.query(func.count(Article.id)).scalar() or 0),
            "sources": int(db.query(func.count(Source.id)).scalar() or 0),
            "keywords": int(db.query(func.count(Keyword.id)).scalar() or 0),
            "price_points": int(db.query(func.count(CommodityPrice.id)).scalar() or 0),
        }

    def _law_docs() -> list:
        return [
            {
                "title": d.title,
                "jurisdiction": d.jurisdiction,
                "url": d.url,
                "last_status": d.last_status,
                "last_checked_at": d.last_checked_at.isoformat() if d.last_checked_at else None,
            }
            for d in db.query(LawDocument)
            .order_by(LawDocument.jurisdiction, LawDocument.title)
            .all()
        ]

    def _wiki_pages() -> list:
        return [
            {
                "wiki": p.wiki,
                "title": p.title,
                "missing": p.missing,
                "baseline": p.baseline_revid is not None,
                "last_checked_at": p.last_checked_at.isoformat() if p.last_checked_at else None,
            }
            for p in db.query(WikiPage).order_by(WikiPage.wiki, WikiPage.title).all()
        ]

    def _import_results() -> list:
        imports_path = _data_dir() / "import_results.jsonl"
        out: list = []
        if imports_path.exists():
            for ln in imports_path.read_text(encoding="utf-8").splitlines()[-50:]:
                try:
                    out.append(_json.loads(ln))
                except ValueError:
                    continue
        return out

    # The error window drives the envelope count; guarded like every other member, and the
    # count degrades to 0 if the member itself failed/skipped (never a crash on len()).
    errors_val = _member("errors", lambda: recent_errors(300))
    count = len(errors_val) if isinstance(errors_val, list) else 0

    # DB members run INLINE (threaded=False — the shared connection is unsafe on a worker
    # thread); the non-self-bounding ones are wrapped in _bounded (a statement deadline).
    # corpus_integrity/storage_composition/slow_queries open their OWN deadline internally,
    # so they are NOT wrapped (nesting would let the inner finally clear the outer handler).
    payload = {
        "runtime": _member("runtime", _runtime),
        "corpus": _member("corpus", lambda: _bounded(_corpus), threaded=False),
        "scheduler": _member(
            "scheduler",
            lambda: {"status": get_scheduler().status(), "recent_runs": recent_runs(30)},
        ),
        "network": _member(
            "network",
            lambda: {
                "sources": source_results(),
                "feeds": feed_preflight.recent_results(),
                "calendar_verdicts": load_verdicts(),
            },
        ),
        "imports": _member("imports", _import_results),
        "calendar_imports": _member(
            "calendar_imports",
            lambda: {
                k: {"events": len(v.get("events", {})), "imported_at": v.get("imported_at")}
                for k, v in load_imports().items()
            },
        ),
        "law_documents": _member("law_documents", lambda: _bounded(_law_docs), threaded=False),
        "wiki_pages": _member("wiki_pages", lambda: _bounded(_wiki_pages), threaded=False),
        # Collection-performance timeline + end-of-pass bottleneck classification
        # (download rate, in-flight fetches, writer-gate contention, CPU/memory).
        # The bandwidth governor's own log — what to read when collection is slow.
        "collect_perf": _member("collect_perf", _collect_perf_samples),
        # TEMPORARY (0.0.8 live-test cycle): automated field-test outcomes —
        # see src/monitoring/field_test.py for purpose + the OO_FIELD_TEST=0
        # opt-out. Will be removed when the cycle ends.
        "field_test": _member("field_test", _field_test_results),
        "errors": errors_val,
        # Honest metadata so a reader can tell whether the error window is CURRENT
        # (the rolling file survives reinstalls, so old-session errors can look
        # live). "*_this_session" counts are since the latest boot marker, so a
        # clean current run reads zero — the direct answer to "is the data-loss
        # happening now?" (P0-5; field test 2026-06-22).
        "error_log": _member("error_log", error_log_summary),
        # Recursive-augmentation logs #2-#5 (maintainer 2026-07-02): so the bundle the
        # operator sends carries the diagnostics that catch bugs automatically — the
        # loop-block/latency log, the slow-query log, live schema drift, and the
        # corpus-integrity/counter-drift sweep. Each is individually guarded (a failing
        # member records its own error, never aborts the bundle); the DB ones are bounded
        # by a statement deadline, request_latency by the wall-clock budget.
        "request_latency": _member("request_latency", _latency_summary),
        "slow_queries": _member(
            "slow_queries", lambda: _slowquery_summary(db), threaded=False
        ),
        "schema_drift": _member(
            "schema_drift", lambda: _bounded(lambda: _schema_drift(db)), threaded=False
        ),
        "corpus_integrity": _member(
            "corpus_integrity", lambda: _corpus_integrity(db), threaded=False
        ),
        # Session forensics (2026-07-09 field event): data-dir inventory (what IS the
        # disk usage — orphaned PLAINTEXT backup staging detected loudly), the previous
        # session's clean/unclean-end verdict (+ the collector's last RSS sample = the
        # OOM-inference flight recorder), and the last unlock's own phase timings with
        # the -wal size before open. Automates the three questions the 2026-07-09
        # root-cause needed the maintainer's terminal for.
        "session_forensics": _member("session_forensics", _session_forensics),
        # Storage composition (P1.5): per-table/per-index bytes via dbstat — names what
        # the on-disk GB actually IS (the 130-GB-in-days field event). Deadline-bounded;
        # degrades to {available:false, reason} where dbstat is not compiled in.
        "storage_composition": _member(
            "storage_composition", lambda: _storage_composition(db), threaded=False
        ),
        # P0 data-safety validation (S1.2): the LAST saved report from the push-button
        # backup/restore/unlock/collector acceptance run (read-only here — never runs a
        # backup; {available:false} until the operator runs it explicitly).
        "p0_validation": _member("p0_validation", _p0_validation_last),
        "method": (
            "Verbatim runtime facts, tracking states, network verdicts, per-click "
            "import outcomes and the rolling WARNING+ error log. Nothing inferred; "
            "exported only on the operator's click. Each member is individually guarded; "
            "a failed member shows {error}, a slow non-DB member {skipped: budget}."
        ),
    }
    body = envelope(kind="debug-bundle", query={}, count=count, payload=payload)
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


def _all_diagnostics_members(db: Session) -> list[tuple[str, object]]:
    """The ordered (filename, generator) list for the all-diagnostics archive — the SINGLE
    source of truth shared by the synchronous ``/all`` endpoint and the background job, so the
    two can never drift out of sync (the A2 contract lesson). Each generator is the same
    function its own button calls; the full keyword CORPUS dump is deliberately NOT here (it
    has its own sized/paged 'All keywords' export) — this carries the bounded log DIGEST."""
    return [
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
        # Recursive-augmentation logs #1-#5 (maintainer 2026-07-02).
        ("request-latency.json", lambda: request_latency()),
        ("slow-queries.json", lambda: slow_queries(explain=1, db=db)),
        ("schema-drift.json", lambda: schema_drift_report(db=db)),
        ("corpus-integrity.json", lambda: corpus_integrity_report(sample=500, full=0, db=db)),
        ("frontend-errors.json", lambda: frontend_errors(limit=500)),
        ("session-forensics.json", lambda: session_forensics_report()),
        # A12b: itemized footprint across ALL stores incl. the external Ollama model store.
        ("storage-footprint.json", lambda: storage_footprint_report(download=False)),
        # P1.5: per-table/per-index bytes (dbstat) — what the on-disk GB actually IS.
        ("storage-composition.json", lambda: storage_composition_report(download=False, db=db)),
        # S1.2: the last P0 data-safety validation report (read-only; never runs a backup).
        ("p0-validation.json", lambda: _p0_validation_last()),
        # §6 recursive-improvement loop instruments: the two cheap, decrypt-light DATA reports
        # that were missing from the bundle, plus the loop SELF-INVENTORY (are the loop's own
        # mechanism-proof gates green?). Kept last so a heavy corpus never delays them.
        ("article-length.json", lambda: article_length(download=False, db=db)),
        ("keyword-growth.json", lambda: keyword_growth(download=False, db=db)),
        ("recursive-loop.json", lambda: recursive_loop(download=False)),
        ("kpi.json", lambda: kpi(download=False)),
        # §4 search-instrumentation: the per-search phase-timing aggregate (empty-honest until
        # instrument_search is wired into the search endpoint on the operator's rig).
        ("search-timing.json", lambda: search_timing(download=False)),
    ]


def _all_diagnostics_manifest(results: list[dict]) -> dict:
    import platform
    import sys as _sys

    return {
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


def _write_all_diagnostics_zip(members, zf, *, progress=None, should_stop=None) -> list[dict]:
    """Write every member (+ manifest) into the open ZipFile ``zf``; return the per-member
    results. Shared by the sync endpoint (an in-memory BytesIO) and the job (a file on disk).
    ``progress(done, total, name)`` reports live progress; ``should_stop()`` lets the job
    cancel cooperatively BETWEEN members (a single member — e.g. the benchmark — can't be
    interrupted mid-run). One failing log never aborts the bundle (a ``<name>.error.txt`` is
    written and recorded in the manifest)."""
    results: list[dict] = []
    total = len(members)
    for i, (name, fn) in enumerate(members):
        if should_stop is not None and should_stop():
            break
        if progress is not None:
            progress(i, total, name)
        try:
            zf.writestr(name, _member_bytes(fn()))
            results.append({"file": name, "ok": True})
        except Exception as exc:  # noqa: BLE001 - one failing log must not abort the bundle
            zf.writestr(name + ".error.txt", str(exc))
            results.append({"file": name, "ok": False, "error": str(exc)[:300]})
    zf.writestr(
        "manifest.json", json.dumps(_all_diagnostics_manifest(results), ensure_ascii=False, indent=2)
    )
    if progress is not None:
        progress(total, total, "done")
    return results


@router.get("/all")
def all_diagnostics(db: Session = Depends(get_db)) -> Response:
    """EVERY diagnostics log in ONE archive (maintainer field report 2026-06-22:
    "there should be the option to download all diagnostics logs at once").

    A single click instead of nine. Each member is generated by the same function its
    own button calls, wrapped so one failing log never aborts the bundle (it writes a
    ``<name>.error.txt`` and records it in the manifest). The full keyword CORPUS dump
    is NOT here — it has its own sized/paged export ("All keywords") — so this carries
    the bounded keyword-log DIGEST instead. Read-only, on-demand, never transmitted.

    NOTE (D2): at scale this synchronous build measured 36+ min and held a threadpool
    thread the whole time — the ``/all-job`` route runs the SAME build as a cancellable
    background JOB writing to a server-side file. This route is KEPT (absorption-gated) so
    the existing UI never breaks during the transition."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        _write_all_diagnostics_zip(_all_diagnostics_members(db), z)
    fname = f"oo-all-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# --------------------------------------------------------------------------- #
# All-diagnostics as a background JOB (D2 / field-test Item 10, measured 36+ min).
# The build runs the SAME members off the request thread, streams the zip to a
# server-side file under data_dir()/diagnostics/, and reports per-member progress. The
# synchronous /all route above is kept during the transition (absorption-gated).
# --------------------------------------------------------------------------- #


def _all_diagnostics_dir():
    from src.paths import data_dir

    d = data_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _all_diagnostics_worker(ctx) -> dict:
    """Build the all-diagnostics archive to a server-side file (D2). Read-only; opens its own
    session so it never borrows the request's. Writes to a ``.part`` file and atomically
    renames on success, so a cancelled/failed run never leaves a half-written archive that
    the download could serve."""
    import os as _os
    import zipfile

    from src.database.session import session_scope

    out_dir = _all_diagnostics_dir()
    fname = f"oo-all-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    final_path = out_dir / fname
    part_path = out_dir / (fname + ".part")
    with session_scope() as db:
        members = _all_diagnostics_members(db)

        def _progress(done, total, name):
            ctx.set_progress(done=done, total=total, detail=name)

        with zipfile.ZipFile(part_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            results = _write_all_diagnostics_zip(
                members, z, progress=_progress, should_stop=lambda: ctx.stopping
            )
    if ctx.stopping:
        # Cancelled between members: drop the partial, never present it as a good archive.
        with contextlib.suppress(OSError):
            part_path.unlink()
        return {"cancelled": True, "members": results}
    _os.replace(part_path, final_path)  # atomic publish
    # Keep only the newest archive (the channel is one-shot; old ones just consume disk).
    # Also sweep any stale ``.part`` left by a PREVIOUS crashed/killed run — this run's own
    # part was just renamed away, and the job is single-instance, so no live writer is
    # touched (no orphaned staging accumulates across hard-kills).
    for old in (*out_dir.glob("oo-all-diagnostics-*.zip"), *out_dir.glob("oo-all-diagnostics-*.zip.part")):
        if old != final_path:
            with contextlib.suppress(OSError):
                old.unlink()
    return {
        "path": str(final_path),
        "filename": fname,
        "bytes": final_path.stat().st_size,
        "members": results,
    }


_ALL_DIAG_JOB = register_job(
    BackgroundJob(
        "all-diagnostics", "Building the all-diagnostics archive", _all_diagnostics_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/all-job")
def all_diagnostics_job_start() -> JSONResponse:
    """Start the all-diagnostics archive build as a BACKGROUND job (D2). Returns immediately;
    poll ``/all-job/status`` (or the task manager) for per-member progress, then GET
    ``/all-job/download`` for the finished file. 409-free: if one is already running, the
    current status is returned with ``started:false``."""
    try:
        return JSONResponse({"started": True, "job": _ALL_DIAG_JOB.start()})
    except RuntimeError:
        return JSONResponse({"started": False, "job": _ALL_DIAG_JOB.status()})


@router.get("/all-job/status")
def all_diagnostics_job_status() -> JSONResponse:
    """Live status of the background all-diagnostics build (state, per-member progress, and —
    when done — the ready filename/size). No score."""
    st = _ALL_DIAG_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(st.get("state") == "done" and res.get("path"))
    st["download_filename"] = res.get("filename")
    st["download_bytes"] = res.get("bytes")
    return JSONResponse(st)


@router.get("/all-job/download")
def all_diagnostics_job_download() -> FileResponse:
    """Serve the finished background all-diagnostics archive (D2). 404 until a build has
    completed successfully (run ``/all-job`` first)."""
    st = _ALL_DIAG_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if st.get("state") != "done" or not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no all-diagnostics archive is ready — start one with POST /api/diagnostics/all-job",
        )
    return FileResponse(
        path, media_type="application/zip",
        filename=res.get("filename") or "oo-all-diagnostics.zip",
    )


# --------------------------------------------------------------------------- #
# P0 DATA-SAFETY VALIDATION (S1.2) — the push-button acceptance run.
#
# The v0.2.0 tag is HELD on the maintainer's live-corpus validation of the P0
# set. This job makes that run push-button: it drives the REAL backup engine
# against the operator's live corpus, verifies it, probes a STAGED restore + a
# dry-run merge PREVIEW (the live corpus is only ever read, never committed), and
# reads the merged unlock + collector instrumentation, emitting ONE report with a
# per-check verdict against the written acceptance bars. Heavy work runs on the
# job thread; the backup owns its own writer-gate + disk preflight. is_writer=False
# (it never commits the live corpus), cancellable (the backup checks should_stop).
# --------------------------------------------------------------------------- #


class P0ValidationBody(BaseModel):
    dest_dir: str = Field(..., description="a separate, empty directory for the backup (e.g. an external drive)")
    passphrase: str = Field(..., description="the backup passphrase (encrypts the volumes; never stored/logged)")
    include_newsletters: bool = True
    measure_incremental: bool = True


def _p0_validation_worker(ctx, **kwargs) -> dict:
    """Thin wrapper so the heavy p0_validation import stays lazy (only when the job
    actually runs). Returns {path, filename, report}; the passphrase never lands in
    the returned dict (BackgroundJob does not store the worker kwargs either)."""
    from src.monitoring.p0_validation import run_p0_validation

    return run_p0_validation(ctx, **kwargs)


_P0_VALIDATION_JOB = register_job(
    BackgroundJob(
        "p0-validation", "P0 data-safety validation", _p0_validation_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/p0-validation")
def p0_validation_start(body: P0ValidationBody) -> JSONResponse:
    """Start the P0 data-safety validation as a BACKGROUND job (S1.2). Returns
    immediately; poll ``/p0-validation/status`` (or the task manager) for progress,
    then GET ``/p0-validation/download`` for the report (``?format=txt`` for the
    readable version). 409-free: if one is already running, the current status is
    returned with ``started:false``.

    Validates the destination up front (400) — it must be a separate, writable
    directory that does NOT overlap the live data dir. Local only, no network."""
    from src.monitoring.p0_validation import validate_dest_dir

    if not body.passphrase:
        raise HTTPException(status_code=400, detail="a backup passphrase is required")
    try:
        validate_dest_dir(body.dest_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        job = _P0_VALIDATION_JOB.start(
            dest_dir=body.dest_dir,
            passphrase=body.passphrase,
            include_newsletters=body.include_newsletters,
            measure_incremental=body.measure_incremental,
        )
        return JSONResponse({"started": True, "job": _p0_scrub(job)})
    except RuntimeError:
        return JSONResponse({"started": False, "job": _p0_scrub(_P0_VALIDATION_JOB.status())})


def _p0_scrub(obj):
    """Defense-in-depth: recursively redact any value under a secret-looking KEY
    (passphrase / password / secret) before a job payload leaves the process.
    BackgroundJob already never stores the worker kwargs, and the report is
    passphrase-free by construction, so this changes nothing today — it makes the
    absence of a secret a PROPERTY of the endpoint, not a convention every future
    report author must remember (so a later field named e.g. 'passphrase' cannot
    silently ride out on /status)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = k.lower() if isinstance(k, str) else ""
            out[k] = "***redacted***" if any(s in kl for s in ("passphrase", "password", "secret")) else _p0_scrub(v)
        return out
    if isinstance(obj, list):
        return [_p0_scrub(v) for v in obj]
    return obj


@router.get("/p0-validation/status")
def p0_validation_status() -> JSONResponse:
    """Live status of the P0 validation job (state, per-check progress, and — when
    done — the ready report filename + the full report in ``result``). No score. The
    payload is passphrase-free by construction; _p0_scrub is a defense-in-depth net."""
    st = _P0_VALIDATION_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(st.get("state") == "done" and res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(_p0_scrub(st))


@router.post("/p0-validation/cancel")
def p0_validation_cancel() -> JSONResponse:
    """Ask the running P0 validation to stop at its next safe point (the backup
    checks should_stop; the throwaway restore staging and any partial backup are
    cleaned up). Idempotent."""
    _P0_VALIDATION_JOB.cancel()
    return JSONResponse(_P0_VALIDATION_JOB.status())


@router.get("/p0-validation/last")
def p0_validation_last() -> JSONResponse:
    """The newest saved P0 validation report (read-only; does NOT run a backup).
    Returns ``{available:false}`` honestly when none has been run."""
    from src.monitoring.p0_validation import last_p0_validation_report

    return JSONResponse(last_p0_validation_report())


@router.get("/p0-validation/download")
def p0_validation_download(fmt: str = Query("json", alias="format")) -> Response:
    """Serve the finished P0 validation report (S1.2). ``format=json`` (default) or
    ``format=txt`` for the readable rendering. 404 until a run has completed."""
    from src.monitoring.p0_validation import render_p0_validation_text

    st = _P0_VALIDATION_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if st.get("state") != "done" or not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no P0 validation report is ready — start one with POST /api/diagnostics/p0-validation",
        )
    report = res.get("report") or {}
    if fmt == "txt":
        fname = f"oo-p0-validation-{datetime.now().strftime('%Y%m%d-%H%M')}.txt"
        return Response(
            content=render_p0_validation_text(report),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    return FileResponse(
        path, media_type="application/json",
        filename=res.get("filename") or "oo-p0-validation.json",
    )
