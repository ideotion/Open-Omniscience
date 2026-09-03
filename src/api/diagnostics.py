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
import logging
import os
import pathlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics.families import build_families
from src.api.heavy import guarded_read
from src.database.maintenance import StatementTimeout, deadline_expired, statement_deadline
from src.database.models import (
    Article,
    Keyword,
    KeywordMention,
    KeywordSuperGroup,
    Source,
)
from src.database.read_snapshot import read_only_db
from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job
from src.utils.export_envelope import app_version, envelope

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])
_LOG = logging.getLogger("api.diagnostics")

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
            art_src: dict[int, int] = {
                aid: sid
                for aid, sid in db.execute(text("SELECT id, source_id FROM articles")).fetchall()
            }
            src_articles: dict[int, int] = {
                sid: n
                for sid, n in db.execute(
                    text("SELECT source_id, COUNT(*) FROM articles GROUP BY source_id")
                ).fetchall()
            }

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
            stored_lang: dict[int, str | None] = {
                kid: lang
                for kid, lang in db.execute(text("SELECT id, language FROM keywords")).fetchall()
            }

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
                src_names = {
                    sid: name
                    for sid, name in db.execute(
                        text(f"SELECT id, name FROM sources WHERE id IN ({marks})")  # nosec B608 - interpolant is a joined list of int()-cast ids built in this function, never input
                    ).fetchall()
                }
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


def _world_discovery_worker(ctx, *, countries=None, per_spec_limit=None, restart=False):
    from src.catalog.discover_job import run_world_discovery

    return run_world_discovery(
        ctx, countries=countries, per_spec_limit=per_spec_limit, restart=restart
    )


_WORLD_DISCOVERY_JOB = register_job(
    BackgroundJob(
        "discover-world-sources",
        "Discovering worldwide sources (Wikidata)",
        _world_discovery_worker,
        is_writer=True,
        cancellable=True,  # the worker checks ctx.stopping between countries
    )
)


@router.post("/discover-world")
def discover_world_sources(
    countries: str | None = Query(
        None, description="optional comma-separated ISO-2 codes; omit for ALL countries"
    ),
    per_spec_limit: int | None = Query(None, ge=1, le=5000),
    restart: bool = Query(False, description="ignore the saved cursor and re-run everything"),
) -> JSONResponse:
    """Discover new sources from Wikidata for EVERY country (or the listed ones) as a
    BACKGROUND JOB — the whole-world automation of ``/discover-sources`` (which stays
    bounded to 12 countries per synchronous call). One country at a time through the
    guarded transport; every insert is a DISABLED row for review (never auto-scraped);
    progress persists per country, so cancel / airplane / crash all RESUME instead of
    re-querying the world. Cancellable from the task manager; 409 under airplane mode."""
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise HTTPException(status_code=409, detail="network refused: airplane mode is engaged")
    codes = None
    if countries:
        from src.catalog.countries import ISO_3166_1_ALPHA2

        codes = [c.strip().lower() for c in countries.split(",") if c.strip()]
        bad = [c for c in codes if c not in ISO_3166_1_ALPHA2]
        if not codes or bad:
            raise HTTPException(
                status_code=400,
                detail=f"countries must be ISO-2 codes, e.g. ke,ng,br (unrecognised: {bad})",
            )
    try:
        return JSONResponse(
            {
                "started": True,
                "job": _WORLD_DISCOVERY_JOB.start(
                    countries=codes, per_spec_limit=per_spec_limit, restart=restart
                ),
            }
        )
    except RuntimeError:
        return JSONResponse({"started": False, "job": _WORLD_DISCOVERY_JOB.status()})


@router.get("/discover-world/status")
def discover_world_status() -> JSONResponse:
    """Live status of the world discovery job + the persisted cursor (countries done /
    added totals survive restarts, so the panel can show resume state while idle)."""
    from src.catalog.discover_job import load_state

    st = load_state()
    return JSONResponse(
        {
            **_WORLD_DISCOVERY_JOB.status(),
            "cursor": {
                "countries_done": len(st.get("done", [])),
                "added_total": st.get("added_total", 0),
                "completed_at": st.get("completed_at"),
                "updated_at": st.get("updated_at"),
            },
        }
    )


@router.post("/discover-world/cancel")
def discover_world_cancel() -> JSONResponse:
    """Ask the world discovery job to stop at the next country boundary (progress is
    saved — starting it again resumes). Also reachable via the task manager's cancel."""
    _WORLD_DISCOVERY_JOB.cancel()
    return JSONResponse(_WORLD_DISCOVERY_JOB.status())


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


class PerceptionEvalLiveBody(BaseModel):
    model: str | None = Field(
        default=None,
        description="an installed model tag; defaults to the active backend's default model",
    )


@router.post("/perception-eval-live")
def perception_eval_live(body: PerceptionEvalLiveBody) -> JSONResponse:
    """B6 (2026-07-24 Session B): run the S6.5 perception harness against the
    ACTIVE model (whichever backend is resolved -- vLLM on a GPU machine,
    Ollama otherwise) over REAL generate() calls -- the gate that must pass
    BEFORE any who/where/when extraction feature ships. Bounded (one call per
    gold-set case, small by design) and synchronous, mirroring ``/ir-eval``'s
    own "bounded read-only eval, not a job" posture. Persists a dated JSON
    artifact (served via ``/perception-eval-live/last``) so the maintainer can
    download the gate evidence. Loopback inference is airplane-safe, same as
    every other local-model diagnostic here."""
    from src.ai_layer.perception_job import run_and_persist_perception_eval

    out = run_and_persist_perception_eval(model=body.model)
    return JSONResponse(out)


@router.get("/perception-eval-live/last")
def perception_eval_live_last() -> JSONResponse:
    """A JSON SUMMARY of the newest saved live perception-eval run (read-only;
    never runs an eval). Returns ``{available:false}`` honestly when none has
    been run."""
    from src.ai_layer.perception_job import last_perception_eval_live_report

    return JSONResponse(last_perception_eval_live_report())


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


@router.get("/merge")
def merge_diag(
    download: bool = Query(False),
    probe: bool = Query(True),
) -> JSONResponse:
    """Where a merge's time and memory go — measured on THIS machine, not inferred.

    Five blocks, each degrading on its own: the engine's compile-time temp-storage
    default (the fact that made every plaintext probe measure the opposite of
    production); this corpus's real average article size and the window the merge
    therefore derives; which SQL statement was in flight, SAMPLED from the capped
    beat ring; exact per-statement seconds from any pre-2026-08-06 journal that
    still carries per-statement records; and a bounded synthetic INSERT..SELECT at
    this corpus's real row size, timed with temp storage in RAM and on disk.

    ``probe=0`` skips only the synthetic benchmark (~50 MB written to a swept temp
    directory under the data dir, deleted in a finally). Everything else is
    read-only: no live-corpus write, no network, no score."""
    from src.monitoring.merge_diag import merge_diagnostics

    log = merge_diagnostics(probe=probe)
    headers = {}
    if download:
        fname = f"oo-merge-diag-{datetime.now().strftime('%Y%m%d')}.json"
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


def _run_journal_raw() -> dict:
    from src.backup.runlog import raw_runs

    return raw_runs()


@router.get("/run-timeline")
def run_timeline(max_runs: int = Query(4, ge=1, le=20)) -> dict:
    """WHERE THE TIME WENT in each recent run -- stages, unaccounted time, and stalls.

    The run journal already recorded everything needed to explain the 2026-08-03 field
    import; extracting it took an afternoon of hand-arithmetic. That import read as
    "3h30 for 650 MB, aborted". The journal's own numbers say otherwise: eighteen
    stages in 118.6 s with the corpus committed and safe, then 2 h 20 m frozen at
    exactly article 9,000 with four worker processes measurably BUSY. Slow and hung
    are different faults needing opposite responses, and nobody should have to do
    arithmetic to tell them apart.

    Read-only over the journal files. Says "a counter did not advance", never "stuck":
    a phase that publishes no counter is not examined at all, because "not moving"
    cannot honestly be said of it.
    """
    from src.monitoring.run_timeline import latest_run_timeline

    return latest_run_timeline(max_runs=max_runs)


@router.get("/run-journal")
def run_journal(download: bool = Query(False), limit: int = Query(20, ge=1, le=200)) -> JSONResponse:
    """Import/export RUN JOURNALS — the crash-surviving record of what each run was
    doing while it ran.

    Field night 2026-07-31: a 686,896-article import sat on one progress line for
    seven hours, and answering "stuck or slow?" took manual ``ps`` sampling. When it
    was killed there was no report at all, because every number the import path
    produces is written once, at the end, on the success path. This reads the sink
    that fixes that: per-run milestones (stage begin/end, knobs, merge steps, resume
    state, errors) plus a heartbeat carrying CPU-time deltas for the parent AND its
    pool children, memory, swap, disk-free, WAL size and write-gate state.

    Read-only; an install that has never imported returns an empty list, which is a
    real answer and not an error. ``download=1`` returns a dated attachment."""
    from src.backup.runlog import list_runs, summarise

    runs = list_runs()[:limit]
    detail: list[dict] = []
    for r in runs:
        try:
            detail.append(summarise(r["run_id"]))
        except Exception as exc:  # noqa: BLE001 - one unreadable journal never hides the rest
            detail.append({"run_id": r.get("run_id"), "unreadable": f"{type(exc).__name__}"})
    payload = {
        "runs": runs,
        "detail": detail,
        "note": (
            "A run with no run_end was killed, OR had its journal disabled mid-run "
            "(e.g. a full disk). Those two are not distinguishable from the files alone, "
            "so neither is asserted."
        ),
    }
    headers = {}
    if download:
        fname = f"oo-run-journal-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(payload, headers=headers)


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


@router.get("/bulletin-language")
def bulletin_language(download: bool = Query(False)) -> JSONResponse:
    """Would a bulletin read in the operator's language, and does it say what the record knows?

    Per locale: how many of the sentences this app writes have a translation, which
    have none (verbatim, so the report IS the worklist), and which have a broken
    frame. Beside it, the render-integrity checks that need the same double render —
    determinism, unresolved frame holes, and every section, article title and
    reference number in the record found in the document.

    Measured on the newest PERSISTED edition when there is one, and on a synthetic
    record when there is not; the report says which, because coverage over a
    synthetic record is a statement about the renderer and coverage over a real one
    is a statement about a corpus. Read-only: it renders an existing record, so no
    DB write, no model and no network are involved."""
    from src.monitoring.bulletin_language import bulletin_language_report, stored_prose

    out = bulletin_language_report()
    # The prose the computing modules WRITE INTO a record: a single edition cannot
    # exhibit all of it (a period with no alert carries no alert caveat), so the
    # worklist would look complete while half the possible sentences had no entry.
    out["stored_prose"] = {
        "bulletin": stored_prose(),
        "card_producers": stored_prose(packages=("briefing",)),
        "note": (
            "Harvested from source, not from this edition: these are the sentences the "
            "computing modules can store in a record and the renderer prints verbatim. A "
            "candidate set rather than an exact total — it can miss a sentence composed at "
            "runtime from two halves, and it can include a method string that belongs to a "
            "selftest payload and never reaches a document."
        ),
    }
    headers = {}
    if download:
        fname = f"oo-bulletin-language-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(out, headers=headers)


@router.get("/bulletin-language-selftest")
def bulletin_language_selftest() -> dict:
    """Prove the translation layer's four properties, with no DB, catalog or model.

    English is identity, a missing translation falls back AND is reported, a frame
    whose holes were changed is refused rather than printed, and an entry copied
    from the English is not counted as coverage. Runs anywhere the app runs."""
    from src.monitoring.bulletin_language import run_bulletin_language_selftest

    return run_bulletin_language_selftest()


@router.get("/lemma-preview")
def lemma_preview(
    top_n: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """S5.4: what lemmatization (OO_FAMILY_LEMMA, ON by default since 2026-07-18) MERGES
    among the top keywords — the precision-review instrument surfaced in the Diagnostics
    panel so the maintainer eyeballs the candidate conflations (and notes a wrong one for
    the _MISLEMMA_DENYLIST, or opts out entirely with OO_FAMILY_LEMMA=0). Read-only, no
    score; honest 'unavailable' when the optional simplemma is absent."""
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
    level proposal are browser-gated; this endpoint is the inspectable table.)

    The three SETTING-backed knobs (``collect_parallelism``, ``qualification_per_pass``,
    ``llm_keep_alive``) report their LIVE persisted value (source ``"override"``) rather than the
    profile-table suggestion, since nothing today rewrites the persisted setting on a profile
    switch — the persisted value is always what's genuinely in effect (2026-07-26 hardware
    diagnostics: a field export showed this diagnostic reporting a stale/wrong effective
    ``collect_parallelism`` for exactly this reason)."""
    from src.config.power_profiles import live_setting_overrides, power_profile_report

    report = power_profile_report(active_profile=profile, overrides=live_setting_overrides())
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


@router.get("/criteria-calibration")
def criteria_calibration(
    download: bool = Query(False),
    top_n: int = Query(100, ge=1, le=1000),
    prose_gate_limit: int = Query(2000, ge=1, le=20000),
    prose_gate_after_id: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """S3.1 (2026-07-23 field-feedback workflow) — the TEMPORARY criteria-calibration report:
    the top ``top_n`` disregarded/would-be-disregarded articles under the CURRENT
    extraction-validity criteria, with per-article detail (id, title, url, source, word
    count, function-word density, sentence-punctuation density, which criterion fired) plus
    per-criterion/per-source/per-language aggregates — a REPORT over the existing detectors
    (``classify_non_article`` + the prose gate), never new judging.

    Iterative loop: review these specimens, adjust the criteria if needed (propose → review
    → apply), re-export. No retroactive quarantine executes against real data until this
    report has been reviewed and the criteria agreed (0.3 gate row 5). Bounded: at most
    ``top_n`` article rows decrypted for detail + one bounded, resumable prose-gate batch
    (``prose_gate_limit``, chunked via ``prose_gate_after_id``). Plain ``def`` → threadpool.
    ``download=1`` returns a dated attachment."""
    from src.analytics.criteria_calibration import calibration_report

    report = calibration_report(
        db, top_n=top_n, prose_gate_limit=prose_gate_limit, prose_gate_after_id=prose_gate_after_id,
    )
    headers = {}
    if download:
        fname = f"oo-criteria-calibration-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
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


def _leads_quality_budget_s() -> float:
    """How long the Leads producer pass inside this member may run
    (``OO_LEADS_QUALITY_BUDGET_S``).

    DELIBERATELY BELOW ``_all_diag_db_member_deadline_s()`` (300 s), and that ordering
    is the fix rather than an implementation detail. The statement deadline wrapped
    around this member DOES fire -- and ``run_all``'s per-producer ``except Exception``
    catches it, logs "producer failed", and continues, once per producer, which is how
    an export sat 69 minutes on a member that was nominally bounded. Expiring first
    means the loop stops itself with a ``break`` nothing can intercept, and the
    statement deadline stays where it belongs: the backstop for a single runaway query.
    """
    import math

    try:
        v = float(os.environ.get("OO_LEADS_QUALITY_BUDGET_S", "240"))
    except ValueError:
        return 240.0
    return v if math.isfinite(v) and v > 0 else 240.0


@router.get("/leads-quality")
def leads_quality(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """S6.1 (Leads-calibration, 2026-07-18): export the CURRENT Home Leads feed as a
    bounded, real-facts report -- producer, key, bucket, n, independent sources, the
    card's own disclosed signal fields verbatim, and the major-floor fact. The
    maintainer re-runs this on the live corpus and sends it back, exactly like the
    keyword-log measurement loop. Read-only; runs the SAME run_all() pass Home uses,
    writes nothing. With ``download=1`` it returns as a dated attachment."""
    from src.analytics.leads_quality import leads_quality_report

    report = leads_quality_report(db, budget_s=_leads_quality_budget_s())
    headers = {}
    if download:
        fname = f"oo-leads-quality-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


# --------------------------------------------------------------------------- #
#  CARD-SYSTEM AUDIT — the deep per-card fact bundle (src/briefing/card_audit.py).
#
#  The THIRD tier beside /home-cards (click plumbing) and /leads-quality (feed
#  composition), which both stay exactly as they are. This one carries, per card:
#  the trigger arithmetic RE-EVALUATED, the article_ids resolved against the live
#  corpus, independence via the existing near-dup/shared-origin primitives, the
#  non-fabrication checks, keyword facts, provenance mix, cross-card overlaps and
#  the disclosed ordering facts -- PLUS an inventory row for EVERY registered
#  producer distinguishing ok / no-signal / ERROR, the three states run_all
#  collapses into one indistinguishable empty list.
#
#  Two surfaces, deliberately: the GET below is SUMMARY depth (no article content,
#  bounded, guarded+deadlined) and is the all-diagnostics bundle member; the deep
#  standard/full-depth run is a cancellable BackgroundJob, because reading article
#  content through the SQLCipher codec must never sit on the request thread.
# --------------------------------------------------------------------------- #


@router.get("/card-audit")
def card_audit(
    depth: str = Query("summary", pattern="^(summary|standard|full)$"),
    determinism: bool = Query(True),
    download: bool = Query(False),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Deep card-system audit at SUMMARY depth — the validate-and-optimize instrument
    for the card/Lead system, built to be re-run each round and diffed against the
    previous export.

    Reports, per card: the ``trigger`` arithmetic recomputed (a row that cannot be
    mechanically checked says so with its reason, and is never counted as a pass),
    the ``article_ids`` resolved against the live corpus, independence (distinct
    sources · near-identical copies · shared origins, via the existing primitives),
    the non-fabrication checks, keyword facts, provenance mix and the disclosed
    ordering facts. PLUS an inventory row for EVERY registered producer stating
    ``ok`` / ``no-signal`` / ``error`` — so a producer that crashes on every run is
    no longer indistinguishable from a quiet one.

    Read-only; writes nothing. Counts are exact and uncapped — every bounded list
    states its exact total beside it. ``depth`` above ``summary`` carries article
    CONTENT and is better run as the background job (``POST /card-audit/run``), which
    is why this endpoint's own default is ``summary``."""
    from src.briefing.card_audit import audit_report_env_defaults, card_audit_report

    bounds = audit_report_env_defaults()
    budget = bounds.pop("determinism_budget_s", None)

    def _compute() -> dict:
        return card_audit_report(
            db,
            depth=depth,
            determinism=determinism,
            # Dimension 6 is ON by default here too. The bundle member cannot afford an
            # unbounded second producer pass, so it carries a MEASURED budget: if the
            # first pass already exceeded it the report says {"ran": false, "skipped":
            # "budget"} with both numbers -- an honest, visible skip, never a silent
            # default-off (OO_CARD_AUDIT_DETERMINISM_BUDGET_S raises it).
            determinism_budget_s=budget,
            **bounds,
        )

    report = guarded_read(db, "card-audit", _compute)
    headers = {}
    if download:
        fname = f"oo-card-audit-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/card-audit/preflight")
def card_audit_preflight(
    depth: str = Query("standard", pattern="^(summary|standard|full)$"),
    excerpt_chars: int = Query(2000, ge=0, le=200000),
    max_articles_per_card: int = Query(40, ge=0, le=500),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Size ESTIMATE for a deep card-audit run, so the operator sees roughly how large
    a ``full`` run will be before starting it. Runs the real producer pass and sizes
    from the REAL card/article counts (exact) times measured per-row JSON costs (an
    estimate, stated as one). Cheap and read-only; never writes a report."""
    from src.briefing.card_audit import estimate_card_audit

    return JSONResponse(
        guarded_read(
            db,
            "card-audit-preflight",
            lambda: estimate_card_audit(
                db,
                depth=depth,
                excerpt_chars=excerpt_chars,
                max_articles_per_card=max_articles_per_card,
            ),
        )
    )


class CardAuditRunBody(BaseModel):
    depth: str = Field(
        "standard",
        description=(
            "summary (no article content) | standard (a bounded excerpt per article) | "
            "full (complete article content -- operator-chosen only)"
        ),
    )
    excerpt_chars: int = Field(2000, ge=0, le=200000)
    max_articles_per_card: int = Field(40, ge=0, le=500)
    max_linked_rows: int = Field(25, ge=0, le=200)
    max_coordination_articles: int = Field(60, ge=0, le=500)
    determinism: bool = Field(
        True,
        description=(
            "run the producer pass twice and diff it (dimension 6). ON by default; the "
            "deep job carries no budget, so an explicitly-requested run pays the second "
            "pass rather than skipping it."
        ),
    )


def _card_audit_worker(ctx, **kwargs) -> dict:
    from src.briefing.card_audit import card_audit_worker

    return card_audit_worker(ctx, **kwargs)


_CARD_AUDIT_JOB = register_job(
    BackgroundJob(
        "card-audit", "card-system audit (deep)", _card_audit_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/card-audit/run")
def card_audit_run(body: CardAuditRunBody) -> JSONResponse:
    """Start a DEEP card-audit run as a BACKGROUND job.

    A deep run reads article content through the SQLCipher codec, so it never sits on
    the request thread (a multi-minute synchronous handler would freeze the whole
    single-worker server). Read-only on the corpus; stops cooperatively at the next
    card boundary when cancelled. Poll ``/card-audit/status``, fetch via
    ``/card-audit/download``. An already-running job returns its status with
    ``started:false`` rather than a 409."""
    if body.depth not in ("summary", "standard", "full"):
        raise HTTPException(status_code=400, detail=f"unknown depth {body.depth!r}")
    try:
        st = _CARD_AUDIT_JOB.start(**body.model_dump())
        st["started"] = True
    except RuntimeError:
        st = _CARD_AUDIT_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/card-audit/status")
def card_audit_status() -> JSONResponse:
    """Live status of the deep card-audit job (state, progress, and when done the
    ready report filename + summary in ``result``). No score."""
    st = _CARD_AUDIT_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(st.get("state") == "done" and res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(st)


@router.post("/card-audit/cancel")
def card_audit_cancel() -> JSONResponse:
    """Ask a running deep card-audit to stop at its next safe point (between cards).
    Idempotent; no partial report is written."""
    _CARD_AUDIT_JOB.cancel()
    return JSONResponse(_CARD_AUDIT_JOB.status())


@router.get("/card-audit/download")
def card_audit_download() -> Response:
    """Serve the finished deep card-audit report. 404 until a run has completed.

    NOTE: at ``standard``/``full`` depth this file carries corpus CONTENT — the report's
    own ``content_notice`` block states exactly what it contains, so the operator knows
    before sharing it."""
    st = _CARD_AUDIT_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if st.get("state") != "done" or not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=(
                "no card-audit report is ready — start one with "
                "POST /api/diagnostics/card-audit/run"
            ),
        )
    return FileResponse(
        path, media_type="application/json",
        filename=res.get("filename") or "oo-card-audit.json",
    )


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
    # Why the collector may be running fewer workers than collect_parallelism allows:
    # the ceiling this machine demonstrated under memory pressure. Null on any box that
    # has never backed off, which is the normal state and is NOT the same as a ceiling
    # of zero. Degrades to an honest absence rather than failing the report.
    try:
        from src.scheduler.capacity import state_report as _capacity_report
        from src.scheduler.settings import load_settings as _load_sched_settings

        collection["learned_concurrency"] = _capacity_report(
            int(getattr(_load_sched_settings(), "collect_parallelism", 1) or 1)
        )
    except Exception as exc:  # noqa: BLE001 - a diagnostic never breaks on a side read
        collection["learned_concurrency"] = {"available": False, "reason": str(exc)[:160]}

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


@router.get("/llm-bench")
def llm_bench(
    repeats: int = Query(3, ge=1, le=10, description="Timed calls per prompt shape"),
) -> JSONResponse:
    """Per-call LLM latency on THIS machine, per prompt SHAPE.

    Any feature that runs the local model over many articles needs an operator setting
    for how much work to do, and the honest form of that setting is a TIME BUDGET, not
    an article count — a count means nothing without knowing what a call costs here.
    Nothing in this repo recorded per-call latency, so a budget could only be guessed.

    Times the shapes the app actually sends (a small fact bundle, one article for
    who/where/when, one article for a summary, and a 24,000-character excerpt set for a
    synthesis), each after an excluded warmup, and translates the result into calls per
    hour. Ollama reports its own durations; vLLM's OpenAI-compatible response carries
    none, so those figures are wall-clock — stated per shape, never mixed.

    LOOPBACK inference only: no egress, so it is airplane-safe and deliberately carries
    no kill-switch refusal of its own. Runs on click only and is never transmitted.
    See src/monitoring/llm_bench.py.
    """
    from src.monitoring.llm_bench import run_llm_bench

    payload = run_llm_bench(repeats=repeats)
    body = envelope(
        kind="llm-bench",
        query={"repeats": repeats},
        count=len(payload.get("shapes", [])),
        payload=payload,
    )
    fname = f"oo-llm-bench-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/llm-throughput")
def llm_throughput(
    levels: str = Query(
        "1,2,4,8,16", description="Comma-separated concurrency levels to sweep"
    ),
    calls_per_level: int = Query(12, ge=1, le=200, description="Calls issued at each level"),
    shape: str = Query("perception", description="Which prompt shape to sweep"),
) -> JSONResponse:
    """Articles per hour ACTUALLY achieved at each concurrency level, on this machine.

    Field report 2026-08-09: "I see my GPU working only 20%". The sibling `/llm-bench`
    measures one call at a time and then multiplies by the configured concurrency to get
    a rate — a multiplication nothing had ever checked, and a 20%-utilised GPU is what an
    unchecked upper bound looks like from the outside. This sweeps the levels instead and
    reports the batch rate measured at each, with GPU utilisation sampled while the work
    is happening, so the curve's bend is a measurement rather than a guess.

    Levels above the RUNNING vLLM server's `--max-num-seqs` measure queueing rather than
    concurrency (raising it takes a restart); those rows say so rather than reporting a
    plateau as though it were a finding.

    LOOPBACK inference only: no egress, so it is airplane-safe and deliberately carries
    no kill-switch refusal of its own. Runs on click only and is never transmitted.
    A plain `def` so the sweep runs in the threadpool and never freezes the one worker.
    See src/monitoring/llm_throughput.py.
    """
    from src.monitoring.llm_throughput import run_throughput_bench

    wanted: list[int] = []
    for part in (levels or "").split(","):
        part = part.strip()
        if part.isdigit() and 0 < int(part) <= 256:
            wanted.append(int(part))
    if not wanted:
        raise HTTPException(
            status_code=400,
            detail="levels must be comma-separated positive integers, each at most 256",
        )
    payload = run_throughput_bench(
        levels=tuple(sorted(set(wanted))),
        calls_per_level=calls_per_level,
        shape=shape,
    )
    body = envelope(
        kind="llm-throughput",
        query={"levels": wanted, "calls_per_level": calls_per_level, "shape": shape},
        count=len(payload.get("levels", [])),
        payload=payload,
    )
    fname = f"oo-llm-throughput-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/ai-activity")
def ai_activity(
    recent: int = Query(12, ge=1, le=100, description="Latest found items per category"),
    hours: int = Query(24, ge=1, le=720, description="Window for the stored-rows rate"),
    db: Session = Depends(get_db),
) -> dict:
    """What the background AI has actually been doing — the live details feed.

    Maintainer ask 2026-08-09: latest detected keywords and languages, totals per
    category, what is left, and articles processed per hour.

    A READER over records the sweeps already write. Three of the four append a per-batch
    JSONL record — with a start AND a finish time — while the run is in flight, next to
    detail records carrying what they found; nothing had ever parsed them, because
    `last_*_report` reads a header, a footer and a line count. Each log is read from its
    END under a byte ceiling of the reader's own, so a sweep left running for days cannot
    turn this into the whole-file read that once OOM'd the app at boot.

    TWO RATES per sweep, both real: the model's own speed (items over summed batch
    durations) and what the corpus gains (items over the elapsed span, including every
    gap where the sweep waited its turn in the coordinator's round-robin). They diverge
    by the duty cycle, and publishing either alone would mislead.

    LOCAL only: reads files and the corpus, no egress, airplane-safe.
    """
    from src.ai_layer.activity import recent_activity

    return recent_activity(session=db, recent=recent, hours=hours)


@router.get("/ai-activity-selftest")
def ai_activity_selftest() -> dict:
    """Prove the reader is bounded and the two rates really separate, on a fixture."""
    from src.ai_layer.activity import run_activity_selftest

    return run_activity_selftest()


@router.get("/llm-throughput-selftest")
def llm_throughput_selftest() -> dict:
    """Prove the concurrency sweep measures concurrency, with no model and no GPU.

    Cheap and deterministic, so it rides the all-diagnostics bundle: a bench whose own
    mechanism is unverified would report a plausible curve while running everything
    serially."""
    from src.monitoring.llm_throughput import run_throughput_selftest

    return run_throughput_selftest()


@router.get("/bulletin-preview")
def bulletin_preview(
    cadence: str = Query("weekly", description="daily | weekly | monthly | trimester | semester | yearly"),
    download: bool = Query(False),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Layer A of the Bulletin for one closed period — the deterministic record.

    The Bulletin is deterministic first: exact, uncapped counts over a half-open
    period on ``coalesce(published_at, created_at)``, quarantined articles excluded
    AND counted, with the masthead that states the lens (which sources actually
    contributed, how concentrated they were, which languages and countries, how
    many of the period's days had any ingest at all) and the disclosures that name
    what the edition cannot see. No model is involved in any figure here.

    This preview exists so the output can be READ on a real corpus before the
    persistence, narration and review surfaces are built — the sandbox-phase
    instruction that classification should fall out of observed content rather
    than be guessed up front.

    Read-only. The period ENDS at the start of today, so it covers whole days and
    re-rendering it tomorrow answers the same question.

    Gated on hardware that can practically run a local model (the feature is gated
    as a whole, not merely its narration layer); the gate reports its reason and
    the standing override reveals it. See src/bulletin/.
    """
    from src.bulletin.facts import layer_a
    from src.bulletin.gate import bulletin_available
    from src.bulletin.period import resolve_period

    gate = bulletin_available()
    if not gate["available"]:
        payload: dict = {"available": False, "gate": gate}
    else:
        try:
            period = resolve_period(cadence)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = layer_a(db, period)
        payload["available"] = True
        payload["gate"] = gate

    headers = {}
    if download:
        fname = f"oo-bulletin-{cadence}-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(payload, headers=headers)


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


# response_model=None: the handler returns a dict OR a text Response, and FastAPI
# cannot build a response model for that union. Keeping the dict return (rather than
# wrapping it in a JSONResponse) is deliberate — the bundle member calls this function
# directly, and the archive writer's dict path carries `_member_default`, so
# session-forensics.json stays byte-identical to what it was before the text sibling.
@router.get("/session-forensics", response_model=None)
def session_forensics_report(download: bool = Query(False)) -> dict | Response:
    """Session forensics (2026-07-09 field event): the data-dir inventory (per-entry
    sizes; orphaned PLAINTEXT backup staging detected loudly), the previous session's
    clean/unclean-end verdict with the collector's last RSS sample (the honest OOM
    inference), and the last unlock's own phase timings + the -wal size before open.
    Local diagnostics only — sizes and app-owned names, never file contents.

    ``download=1`` returns the same facts as a dated PLAIN-TEXT attachment (2026-08-23
    field ask). This is a deliberate exception to the 2026-07-20 button-consolidation
    ruling, whose rationale was that the ratchet guarantees the bundle carries every
    report: it does, and `session-forensics.txt` is now in it — but this is the one
    file that explains a crash, and making an operator sit through a full bundle run
    to send it is the wrong cost for that question."""
    from src.monitoring.forensics import render_text as _render
    from src.monitoring.forensics import session_forensics as _sf

    payload = _sf()
    if download:
        fname = f"oo-session-forensics-{datetime.now().strftime('%Y%m%d-%H%M')}.txt"
        return Response(
            content=_render(payload),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    return payload


def _session_forensics_text() -> Response:
    """The text rendering as a bundle member. Returns a ``Response`` so the archive
    writer's own encoder writes the bytes verbatim instead of JSON-quoting them."""
    from src.monitoring.forensics import render_text as _render

    return Response(content=_render(), media_type="text/plain; charset=utf-8")


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


@router.get("/law-coverage")
def law_coverage(
    download: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """Per-jurisdiction law-tracking coverage/freshness (S5 of the law-vertical
    brief 2026-07-17): "the maintainer's next 'is law working?' is answered by
    one JSON." Counts + verdict tallies + freshness ages, no score. THE
    COMPLETENESS PRINCIPLE: a tracked-document count is an entry point, never a
    coverage claim — see ``src.law.coverage`` for the full caveat. With
    ``download=1`` it returns as a dated attachment."""
    from src.law.coverage import law_coverage_report

    payload = law_coverage_report(db)
    body = envelope(
        kind="law-coverage",
        query={},
        count=payload.get("documents", 0),
        payload=payload,
    )
    if download:
        fname = f"oo-law-coverage-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


@router.get("/law-ingest")
def law_ingest(
    download: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """Law-ingest reliability (ruling 34c, field feedback 2026-08-07).

    The 2026-08-07 law fixes are self-healing and invisible: the strip stage re-reads a
    tracked document's baseline on its next successful poll, and the corpus sync clears a
    publication date that was really a poll date. Both are correct; neither is reported
    anywhere, so "has this actually reached all 23 documents?" had no answer -- and the
    documents most likely to be missed are the ones whose portal cannot be fetched.

    Read-only and network-free: every field comes from stored data or a bundled fixture.
    See ``src.law.ingest_report`` for why chrome residue is NOT a pre-strip detector.
    With ``download=1`` it returns as a dated attachment."""
    from src.law.ingest_report import law_ingest_report

    payload = law_ingest_report(db)
    body = envelope(
        kind="law-ingest",
        query={},
        count=payload.get("documents", 0),
        payload=payload,
    )
    if download:
        fname = f"oo-law-ingest-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


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


@router.get("/windows-locks")
def windows_locks_report(download: bool = Query(False)) -> JSONResponse:
    """Why Windows refused to replace the corpus during a restore — who holds the files.

    A Windows restore fails with ``[WinError 32]`` when anything at all has the
    database or its ``-wal`` open, because Windows will not unlink or replace an
    open file; the OS names the FILE and never the holder, which leaves an
    operator unable to tell a bug in this app from a program they could close.

    This asks that question directly and changes nothing doing it: each corpus
    file is opened for READ with sharing disabled — the same exclusivity the swap
    needs — and closed immediately; our own handles are listed; other processes
    are swept within a stated budget; and Defender's real-time state and
    exclusion paths are read. Off Windows it reports honestly that none of it
    applies rather than a clean bill of health. Read-only, zero network, no score.
    With ``download=1`` it returns as a dated attachment."""
    from src.monitoring.windows_locks import windows_lock_report

    payload = windows_lock_report()
    body = envelope(
        kind="windows-locks",
        query={},
        count=len(payload.get("files") or []),
        payload=payload,
    )
    if download:
        fname = f"oo-windows-locks-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
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


@router.get("/write-gate")
def write_gate_report() -> dict:
    """WHO is holding the single-writer gate, and who is holding a connection.

    S2.6 (2026-09-02 crash analysis). Two different pins, kept apart because they
    answer different questions and a reader who conflates them looks in the wrong
    place:

    * ``gate`` -- the WRITE window. ``holder``/``held_for_s`` name the current
      hold; ``max_hold_holder`` retains the name of the longest one after it is
      released, because a peak with no name cannot be acted on. Under FIFO
      handoff ``max_wait_s`` now measures a real hold rather than starvation.
    * ``pool`` -- checked-out CONNECTIONS, oldest first. A long-lived read
      transaction pins the WAL with the gate free the whole time, which is the
      shape the field's three-hour WAL growth had; the top row is the candidate.

    An empty ``pool`` list means nothing is checked out RIGHT NOW -- a returned
    connection is deliberately not listed, so no innocent thread is named.
    Read-only, in-memory, no statement text and no stack (the write gate's own
    watchdog captures a stack on demand, only for a hold past its threshold).
    """
    from src.database import pool_watch
    from src.database.writer import write_gate_stats

    return {
        "gate": write_gate_stats(),
        "pool": pool_watch.checked_out(),
        "method": (
            "gate counters read under the gate's own lock; pool rows recorded by "
            "SQLAlchemy checkout/checkin listeners and forgotten on checkin"
        ),
        "caveat": (
            "A point-in-time reading. An empty pool list means nothing is checked "
            "out at this instant, never that nothing ever was."
        ),
    }


@router.get("/request-latency")
def request_latency() -> dict:
    """Per-route latency percentiles + the event-loop-block watchdog events (log #2).
    The freeze family (unlock / restore / task-manager) points at itself here."""
    from src.monitoring.latency import summary as _summary

    return _summary()


@router.get("/stall-forensics")
def stall_forensics_report(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Requests that blew the stall budget, each with what the machine was doing.

    The 2026-07-21 field brief recorded a cluster of multi-hour requests and 503s on
    one afternoon and could not say why: the instruments that would have known are
    windowed, so the evidence had aged out before anyone read the export. This log
    takes the reading AT the stall -- single-writer gate, event loop, slowest
    statement -- and files the cause classes those readings support. Correlation,
    never proof: a stall none of the three can see is filed ``undetermined`` rather
    than assigned to the nearest class. In-memory and bounded; a restart empties it.
    """
    from src.monitoring.stall_forensics import report as _report

    return _report(limit=limit)


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


#: Marks a value the encoder could not serialise, IN PLACE, naming its type. Never a
#: silent ``str()`` of the object (which would write "<Query object at 0x7f…>" into a
#: report as if it were data) and never an exception that discards the whole member.
_UNSERIALISABLE = "__oo_unserialisable__"


def _member_default(obj: object) -> object:
    """``json.dumps(default=)``: replace an unserialisable value with a STATED marker.

    Field bundle 2026-08-02: ``card-audit.json`` ran for 2,396 s -- 40 minutes, 41% of
    the entire bundle's wall time -- and then raised "Object of type Query is not JSON
    serializable" at the encode step. Every byte of that work was discarded, and the
    error named the type without saying where it sat, so the next run could only
    reproduce it by spending the 40 minutes again.

    Both halves of that are fixed here: the member is still WRITTEN (one bad leaf can no
    longer destroy an expensive report), and the leaf says what it was, so the offending
    producer is identifiable from the artefact instead of by re-running it.

    Deliberately NOT ``default=str``: a stringified ORM object is indistinguishable from
    a real string field, which is the fabrication this project forbids -- a reader must
    be able to tell a value that could not be encoded from one that was.
    """
    return {
        _UNSERIALISABLE: True,
        "type": type(obj).__name__,
        "module": type(obj).__module__,
        "note": (
            "this value could not be encoded as JSON and was replaced in place; the "
            "surrounding keys locate the field that produced it"
        ),
    }


def _member_bytes(value) -> bytes:
    """Encode any diagnostics endpoint return (a plain dict, a JSONResponse, or a
    StreamingResponse) into the bytes to write into the all-diagnostics ZIP."""
    if isinstance(value, (dict, list)):
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), default=_member_default
        ).encode("utf-8")
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


def _fixity_bundle_member(db: Session) -> dict:
    """The BOUNDED fixity-audit bundle member (transversal audit 09, C2). Calls the
    real ``GET /api/integrity/fixity`` endpoint function directly (its own
    ``guarded_read`` heavy-cap/single-flight wrapping applies unchanged), capped at
    ``limit=500`` so a re-hash of every stored article never dominates the whole
    bundle's wall time. Degrades honestly (never raises into the bundle build) if the
    sibling router can't be imported for any reason."""
    try:
        from src.api.integrity import get_fixity

        return get_fixity(limit=500, db=db)
    except Exception as exc:  # noqa: BLE001 - one member's failure must not sink the bundle
        return {"available": False, "reason": _all_diag_err_str(exc)}


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
        # EVERY Query()-defaulted parameter passed EXPLICITLY: called directly (not
        # through FastAPI) the default IS the Query sentinel object, and Query(False)
        # is TRUTHY. `run_journal` proved it in the field -- limit reached a slice as a
        # Query and the member died with "slice indices must be integers". The repo
        # already had this lesson from `ai.json`; these three call sites had not
        # applied it. Anything with a Query() default belongs in the call, always.
        ("keyword-log-digest.json",
         # per_lang/page are the route's OWN declared defaults, not numbers chosen
         # here: passing anything else would silently change what this member exports.
         lambda: keyword_log(
             db=db, digest=True, fmt="json", per_lang=_MAX_KEYWORDS_PER_LANG, page=1
         )),
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
        # S2.6 (2026-09-02): the two pins, named. Point-in-time and in-memory, so
        # it is cheap and the bundle carries it beside the latency log the stalls
        # show up in.
        ("write-gate.json", lambda: write_gate_report()),
        # Cause attribution for the requests the latency log shows as stalls. Cheap:
        # an in-memory ring read, no DB work, so it needs no deadline of its own.
        ("stall-forensics.json", lambda: stall_forensics_report(limit=200)),
        ("slow-queries.json", lambda: slow_queries(explain=1, db=db)),
        ("schema-drift.json", lambda: schema_drift_report(db=db)),
        ("corpus-integrity.json", lambda: corpus_integrity_report(sample=500, full=0, db=db)),
        # transversal audit 09 (2026-07-25), C2: fold the local fixity audit in, as
        # 08's own Action Plan C2 originally asked ("fold a fixity pass into the
        # gate-row-3 diagnostics bundle rather than treating it as a separate ask").
        # A re-hash of every stored article is one of the heaviest reads (its own
        # docstring says so), so this member is BOUNDED (limit=500, matching
        # corpus-integrity's own sample bound above) -- the standalone
        # GET /api/integrity/fixity endpoint still defaults to a full-corpus audit
        # for a direct, deliberate operator run. Reuses the endpoint's OWN
        # guarded_read wrapping (single-flight/heavy-cap), the same code path a
        # direct HTTP GET would take.
        ("fixity.json", lambda: _fixity_bundle_member(db=db)),
        ("frontend-errors.json", lambda: frontend_errors(limit=500)),
        # download=False EXPLICITLY: called directly, `Query(False)` is a sentinel
        # OBJECT and truthy, which would have put the TEXT in the .json member.
        ("session-forensics.json", lambda: session_forensics_report(download=False)),
        # The SAME facts rendered for a human (2026-08-23 field ask). It rides beside
        # the JSON rather than replacing it: the JSON is what a tool reads, the text is
        # what an operator pastes into a chat when something went wrong.
        ("session-forensics.txt", lambda: _session_forensics_text()),
        # A12b: itemized footprint across ALL stores incl. the external Ollama model store.
        ("storage-footprint.json", lambda: storage_footprint_report(download=False)),
        # P1.5: per-table/per-index bytes (dbstat) — what the on-disk GB actually IS.
        ("storage-composition.json", lambda: storage_composition_report(download=False, db=db)),
        ("windows-locks.json", lambda: windows_locks_report(download=False)),
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
        # The import/export RUN JOURNAL (2026-07-31). Rides the bundle rather than the
        # backup archive on purpose: _build_backup_zip hashes members and THEN writes
        # them, and an EXPORT's own journal is appended to between those two reads --
        # over minutes, for a 17 GB set -- so every such backup would carry a member
        # its own restore rejects as "sha256 mismatch (corrupted or altered)". The
        # bundle is a read-at-one-moment snapshot, with no hash to contradict.
        ("run-journal.json", lambda: run_journal(download=False, limit=20)),
        # ...and the raw lines behind it. The summary is the answer; this is the
        # evidence, and a stall is a SHAPE across hundreds of beats (swap climbing
        # while CPU flatlines; the gate held with waiters piling up) that no summary
        # substitutes for. Bounded, with what was dropped stated.
        ("run-journal-raw.json", lambda: _run_journal_raw()),
        ("run-timeline.json", lambda: run_timeline(max_runs=4)),
        # The MERGE diagnostic (2026-08-06). Every Query()-defaulted parameter passed
        # EXPLICITLY, per the ai.json/run_journal lesson three members above: called
        # directly, a Query(True) default is the sentinel OBJECT, which is truthy, so
        # omitting `probe` would run the benchmark by accident rather than by choice.
        # It IS wanted here -- the per-row cost at the operator's real row size is the
        # number that named the 5 KB/row allocation -- so it is passed as True, on
        # purpose and visibly. ~50 MB written to a swept temp dir, deleted in a finally.
        ("merge-diag.json", lambda: merge_diag(download=False, probe=True)),
        # 2026-07-17 completeness fix (maintainer: "all diagnostics should comprise ALL
        # diagnostics"): the read-only reports + cheap deterministic selftests that had
        # accumulated OUTSIDE the bundle since the #645 membership pass. Deliberate
        # exclusions are now DOCUMENTED in the manifest's "excluded" block instead of
        # silent, and test_repo_invariants ratchets every future GET endpoint into
        # either the bundle or that block.
        ("source-audit.json", lambda: source_audit(download=False, with_furniture=True, db=db)),
        ("non-article-scan.json", lambda: non_article_scan(download=False, db=db)),
        # S3.1 (2026-07-23 field-feedback workflow): the TEMPORARY criteria-calibration
        # report. A smaller prose_gate_limit than the endpoint's own default (500 vs 2000)
        # keeps this bundle member's content-decrypt bounded — the standalone endpoint
        # still defaults fuller for a direct diagnostic run.
        ("criteria-calibration.json", lambda: criteria_calibration(
            download=False, top_n=100, prose_gate_limit=500, prose_gate_after_id=0, db=db,
        )),
        ("lemma-preview.json", lambda: lemma_preview(top_n=500, db=db)),
        # The bulletin's own language coverage + the render-integrity checks. Renders a
        # persisted record (or the synthetic sample when there is none), so it costs no
        # query and works on a fresh install.
        ("bulletin-language.json", lambda: bulletin_language(download=False)),
        ("bulletin-language-selftest.json", lambda: bulletin_language_selftest()),
        ("power-profile.json", lambda: power_profile(profile="optimized", download=False)),
        ("data-dir-persistence.json", lambda: data_dir_persistence_report()),
        ("ir-eval-selftest.json", lambda: ir_eval_selftest(download=False)),
        ("perception-eval-selftest.json", lambda: perception_eval_selftest(download=False)),
        ("keyword-triage-selftest.json", lambda: keyword_triage_selftest(download=False)),
        # Section 8 real run (2026-07-20 ruling): the last saved keyword-triage JSONL run,
        # summarised (read-only; never RUNS a triage -- that is its own background job).
        ("keyword-triage-run.json", lambda: keyword_triage_last()),
        # The reviewable PROPOSAL built from that run: junk verdicts grouped per language,
        # with the evidence and what was held back. Cheap (a streamed log read + one
        # indexed term lookup), read-only, and it applies nothing -- the artifact a human
        # judges before any stoplist ever changes. Query() default passed EXPLICITLY.
        ("keyword-triage-proposal.json", lambda: keyword_triage_proposal(download=False, db=db)),
        # The sibling LLM source-tag-assignment run: selftest + last saved summary.
        ("source-tags-selftest.json", lambda: source_tags_selftest(download=False)),
        ("source-tags-run.json", lambda: source_tags_last()),
        # B6 (2026-07-24 Session B): the last saved LIVE perception-eval-against-model
        # run (read-only; never RUNS an eval -- that is a POST, /perception-eval-live).
        ("perception-eval-live.json", lambda: perception_eval_live_last()),
        # B6.2/B6.3: the last saved who/where/when EXTRACTION sweep summary (read-only;
        # never RUNS a sweep -- that is its own background job, /perception-extract/run).
        ("perception-extract-run.json", lambda: perception_extract_last()),
        # The last saved side-by-side TRANSLATION comparison (read-only; never runs a
        # probe -- that is a POST). Carries corpus excerpts, and the payload says so.
        # E-S2 (2026-08-01): the newest COMPARATIVE model-bench artifact, summarised
        # (every metric, without the hundreds of per-term answers per pair). Read-only
        # -- running the bench is a heavy operator job, never a bundle member.
        ("model-bench.json", lambda: model_bench_last(full=False)),
        # The one-button AI check (maintainer 2026-08-09): the last run's report, so a
        # debug bundle carries what this machine measured about its own model rather
        # than sending somebody to run five diagnostics by hand. Read-only -- RUNNING it
        # is a background job of its own, never a bundle member.
        ("ai-check.json", lambda: ai_check_last()),
        # What the bench COULD cover on this machine. Read-only, and pointedly WITHOUT
        # the endpoint's `wake`: a bundle reports what it can see and starts nothing.
        # It answers the first question every one of the 10 August field reports raised
        # — "why is this bench so short" — without the reader having to run anything.
        # B7.1: the whole dual-backend AI stack snapshot -- backend/hardware facts,
        # active model, context settings, and every AI job's last saved summary.
        # Called DIRECTLY, so both arguments are passed explicitly: a FastAPI default
        # (Depends/Query) is only resolved when FastAPI itself calls the function, and
        # Query(False) is a truthy object — a bare ai_diagnostics() here would take the
        # measure_corpus branch and hand article_length_report a Depends sentinel. The
        # file's own convention for a db-taking member (leads_quality below) is the fix.
        ("ai.json", lambda: ai_diagnostics(measure_corpus=False, db=db)),
        # B7.2: the qualification-assist self-test + the newest saved proposals run
        # (across every source ever checked -- read-only, never runs a new check).
        ("qualification-assist-selftest.json", lambda: qualification_assist_selftest(download=False)),
        ("qualification-assist-run.json", lambda: qualification_assist_last(source_id=None)),
        ("search-timing-selftest.json", lambda: search_timing_selftest(download=False)),
        ("power-profile-selftest.json", lambda: power_profile_selftest(download=False)),
        ("source-audit-selftest.json", lambda: source_audit_selftest(download=False)),
        # The concurrency sweep's own MECHANISM (2026-08-09). The sweep itself is an
        # operator action needing a live model; this proves it really runs concurrently
        # -- a bench that silently ran serially would still publish a plausible curve.
        ("llm-throughput-selftest.json", llm_throughput_selftest),
        # What the background AI has been doing lately, read from the sweeps' own
        # logs (2026-08-09). Bounded tail reads, so a long-running sweep cannot make
        # this member grow without limit.
        ("ai-activity.json", lambda: ai_activity(recent=12, hours=24, db=db)),
        ("ai-activity-selftest.json", ai_activity_selftest),
        # S5 (law-vertical brief 2026-07-17): per-jurisdiction law-tracking coverage/
        # freshness — "is law working?" answered by one JSON, in the bundle by default.
        ("law-coverage.json", lambda: law_coverage(download=False, db=db)),
        # Ruling 34c (2026-08-07): did the law fixes actually reach the data? The strip
        # re-read and the poll-date clear both heal quietly on a document's next
        # successful poll, so an unreachable portal never heals and nothing said so.
        ("law-ingest.json", lambda: law_ingest(download=False, db=db)),
        # S6.1 (Leads-calibration, 2026-07-18): the CURRENT Home Leads feed as a
        # bounded, real-facts report — the measurement loop for the card system.
        ("leads-quality.json", lambda: leads_quality(download=False, db=db)),
        # The DEEP card-system audit at SUMMARY depth (no article content): the
        # per-card trigger arithmetic recomputed, corpus fidelity, independence,
        # non-fabrication checks, and — the reason it exists — an inventory row for
        # EVERY registered producer distinguishing ok / no-signal / ERROR, so a
        # producer crashing on every run stops being indistinguishable from a quiet
        # one. Bounded via audit_report_env_defaults(); the content-carrying
        # standard/full depths are the separate background job, never this member.
        ("card-audit.json",
         lambda: card_audit(depth="summary", determinism=True, download=False, db=db)),
        # Bulletin Layer A (2026-08-01), weekly: the deterministic period record. It
        # rides the bundle because its masthead IS corpus-health evidence — sources
        # that actually contributed, days with any ingest, language and country
        # spread, and the disclosures naming what no window can see. Weekly, so the
        # scan stays bounded; a long-cadence edition is a deliberate operator run.
        # On hardware below the gate this member is a stated refusal, not a figure.
        ("bulletin-weekly.json", lambda: bulletin_preview(cadence="weekly", download=False, db=db)),
    ]



def _all_diag_db_member_deadline_s() -> float:
    """Per-member statement deadline (SQL VM opcode interrupt) for a DB-touching
    all-diagnostics member, ``OO_ALL_DIAG_DB_MEMBER_DEADLINE_S`` (generous default -- a
    diagnostics run is not a UI request). Clamped finite/positive so a bad env value can
    never overflow ``Thread.join`` downstream nor emit a non-finite, JSON-invalid budget
    (the same S8-lesson clamp as the debug-bundle budget)."""
    import math

    try:
        v = float(os.environ.get("OO_ALL_DIAG_DB_MEMBER_DEADLINE_S", "300"))
    except ValueError:
        return 300.0
    if not math.isfinite(v) or v <= 0:
        return 300.0
    return min(v, 3600.0)


def _all_diag_nondb_member_deadline_s() -> float:
    """Per-member wall-clock budget for a NON-DB all-diagnostics member run on a daemon
    thread, ``OO_ALL_DIAG_NONDB_MEMBER_DEADLINE_S`` (same generous default + clamp)."""
    import math

    try:
        v = float(os.environ.get("OO_ALL_DIAG_NONDB_MEMBER_DEADLINE_S", "300"))
    except ValueError:
        return 300.0
    if not math.isfinite(v) or v <= 0:
        return 300.0
    return min(v, 3600.0)


def _member_touches_db(fn) -> bool:
    """True if this member's thunk closes over a ``db`` free variable -- i.e. it reads
    the shared DB connection. Determined from the ACTUAL closure (``fn.__code__``), never
    a hand-maintained allow-list that could silently drift from ``_all_diagnostics_members``
    as members are added. The S8 house lesson: a DB-touching member must run INLINE, never
    on a worker thread sharing the connection (pysqlite/sqlcipher serialise statements --
    a second thread BLOCKS, it does not error -- and a SQLAlchemy Session is not
    thread-safe), so this is the dispatch key for the deadline strategy below."""
    code = getattr(fn, "__code__", None)
    return code is not None and "db" in code.co_freevars


def _rss_peak_kb() -> int | None:
    """Process PEAK resident-set size in KB -- ``ru_maxrss``, one syscall, no dependency.
    Linux reports KB already; macOS reports bytes, normalized here.

    This is a HIGH-WATER MARK that NEVER FALLS, which is why S6.2 stopped using it as the
    per-member delta: after the first big member the process peak is already set, so every
    later member's "delta" is 0 whatever it really allocated. It is kept, under its own
    name, because it answers a different and still-useful question -- did THIS member push
    the process past everything it had ever done. None (never fabricated) where unreadable."""
    try:
        import resource
        import sys as _sys

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss / 1024) if _sys.platform == "darwin" else int(rss)
    except Exception:  # noqa: BLE001 - best-effort instrumentation, never fatal
        return None


class _RssProbe:
    """CURRENT resident-set size in KB -- rises AND falls, so a delta across a member
    measures that member (S6.2).

    RESOLVED ONCE, before anything is measured, because the instrument perturbs what it
    reads. The 2026-09-03 portability measurement ran each candidate five times on one
    workload: ``/proc`` and ONE HOISTED ``psutil.Process`` both reported 31.9 MB freed,
    5/5, agreeing to the hundredth of a MB, while a fresh ``psutil.Process()`` per read
    reported 0 MB and a forking ``ps -o rss=`` reported -0.1 MB -- the fork prevents the
    allocator returning the pages, so those two would have made an honest release read as
    "the trim freed nothing" on every platform they answered on.

    Order: ``merge_diag._rss_current_mb`` (``/proc/self/statm``, Linux, no dependency and
    no fork -- REUSED rather than re-implemented), then one hoisted ``psutil.Process``
    where ``/proc`` is absent, then nothing. ``basis`` NAMES which instrument answered, so
    a platform where no current reading exists says so instead of having a high-water
    figure published under the current-RSS name.
    """

    def __init__(self) -> None:
        self._proc = None
        self.basis = "unavailable"
        try:
            from src.monitoring.merge_diag import _rss_current_mb

            if _rss_current_mb() is not None:
                self.basis = "proc"
                return
        except Exception:  # noqa: BLE001 - an absent /proc is a platform fact
            pass
        try:
            import psutil

            proc = psutil.Process()
            proc.memory_info()  # prove it reads before claiming the basis
            self._proc = proc
            self.basis = "psutil"
        except Exception:  # noqa: BLE001 - absent psutil is a platform fact, not a failure
            self._proc = None

    def kb(self) -> int | None:
        """The current reading in KB, or None -- never a fabricated 0."""
        try:
            if self.basis == "proc":
                from src.monitoring.merge_diag import _rss_current_mb

                mb = _rss_current_mb()
            elif self.basis == "psutil" and self._proc is not None:
                mb = self._proc.memory_info().rss / 1024.0 / 1024.0
            else:
                return None
        except Exception:  # noqa: BLE001 - a reading is best-effort, never fatal
            return None
        return None if mb is None else int(mb * 1024)


# Trim only after a member that actually moved the resident set: ``malloc_trim`` walks the
# allocator's arenas, so running it after each of ~59 members would be noise on the wall
# clock and would report a freed figure for members that allocated nothing. The threshold is
# a stated choice, not a measurement -- what IS measured is the freed amount it reports.
_ALL_DIAG_TRIM_AFTER_KB = 64 * 1024  # 64 MiB


def _trim_after_heavy_member(probe: "_RssProbe", rss_after: int | None) -> dict | None:
    """Return the allocator's arena memory to the OS between heavy members, and report what
    that actually freed (S6.2). Reuses ``hygiene._malloc_trim`` rather than writing a second
    one. ``None`` when nothing was attempted; ``freed_kb: None`` -- never 0 -- when the
    call was made but the release could not be measured."""
    try:
        from src.scheduler.hygiene import _malloc_trim
    except Exception:  # noqa: BLE001 - instrumentation is never a hard dependency
        return None
    if not _malloc_trim():
        return None
    after = probe.kb()
    freed = (rss_after - after) if (rss_after is not None and after is not None) else None
    return {"trimmed": True, "freed_kb": freed}


_ALL_DIAG_DEADLINE_SENTINEL = object()


def _run_nondb_member_bounded(fn, budget_s: float):
    """Run a NON-DB member thunk on a daemon thread under a wall-clock budget (S8: safe
    ONLY because these members never touch the shared DB connection -- they may block on a
    socket or a file read, and abandoning the thread past budget cannot corrupt anything
    shared). Returns the thunk's value, or ``_ALL_DIAG_DEADLINE_SENTINEL`` if it is still
    running past ``budget_s`` (the thread is simply abandoned -- daemon, so it never blocks
    process exit). A raised exception inside the thunk is re-raised here so the caller's
    normal per-member except-block handles it uniformly with the inline DB path."""
    import threading

    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised on the caller's side below
            box["error"] = exc

    t = threading.Thread(target=_run, name="all-diag-member", daemon=True)
    t.start()
    t.join(budget_s)
    if t.is_alive():
        return _ALL_DIAG_DEADLINE_SENTINEL
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _all_diag_err_str(exc: Exception) -> str:
    """Render a member's exception for the envelope/error-file -- even a broken ``__str__``
    must still yield a marker (S8 lesson: a failed member must never be silently lost)."""
    try:
        return str(exc)[:300]
    except Exception:  # noqa: BLE001
        return f"<{type(exc).__name__}: unrenderable>"


# RATCHET (2026-07-17) + RUNTIME COVERAGE (DIAGNOSE-THE-DIAGNOSTICS, 2026-07-20): the
# SINGLE source of truth for "every GET diagnostics route is either a bundle member or a
# documented exemption" -- shared by test_repo_invariants' CI-time ratchet (which imports
# these two dicts rather than hand-duplicating them) AND the manifest's runtime coverage
# block below, so the CI-time check and the artifact's own self-description can never
# silently diverge from each other.
_DIAG_COVERAGE_MAP: dict[str, str] = {
    "/keywords": "keyword-log-digest.json",  # digest form; full dump exempt below
    "/keyword-selftest": "keyword-selftest.json",
    "/ir-eval-selftest": "ir-eval-selftest.json",
    "/perception-eval-selftest": "perception-eval-selftest.json",
    "/perception-eval-live/last": "perception-eval-live.json",
    "/keyword-triage-selftest": "keyword-triage-selftest.json",
    "/recursive-loop": "recursive-loop.json",
    "/merge": "merge-diag.json",
    "/kpi": "kpi.json",
    "/search-timing": "search-timing.json",
    "/run-journal": "run-journal.json",
    "/run-timeline": "run-timeline.json",
    "/search-timing-selftest": "search-timing-selftest.json",
    "/lemma-preview": "lemma-preview.json",
    "/bulletin-language": "bulletin-language.json",
    "/bulletin-language-selftest": "bulletin-language-selftest.json",
    "/home-cards": "home-cards.json",
    "/keyword-engine": "keyword-engine.json",
    "/power-profile": "power-profile.json",
    "/power-profile-selftest": "power-profile-selftest.json",
    "/article-length": "article-length.json",
    "/non-article-scan": "non-article-scan.json",
    "/criteria-calibration": "criteria-calibration.json",  # S3.1 of the 2026-07-23 field-feedback workflow
    "/keyword-growth": "keyword-growth.json",
    "/source-audit": "source-audit.json",
    "/source-audit-selftest": "source-audit-selftest.json",
    "/dates": "date-extraction.json",
    "/performance": "performance.json",
    "/benchmark": "benchmark.json",
    "/network": "network.json",
    "/columnar": "columnar.json",
    "/freshness": "freshness.json",
    "/session-forensics": "session-forensics.json",
    "/data-dir-persistence": "data-dir-persistence.json",
    "/storage-footprint": "storage-footprint.json",
    "/storage-composition": "storage-composition.json",
    "/windows-locks": "windows-locks.json",
    "/frontend-errors": "frontend-errors.json",
    "/request-latency": "request-latency.json",
    "/write-gate": "write-gate.json",  # S2.6 (2026-09-02): who holds the gate / a connection
    "/stall-forensics": "stall-forensics.json",
    "/slow-queries": "slow-queries.json",
    "/schema-drift": "schema-drift.json",
    "/integrity": "corpus-integrity.json",
    "/debug-bundle": "debug-bundle.json",
    "/p0-validation/last": "p0-validation.json",
    "/law-coverage": "law-coverage.json",  # S5 of the law-vertical brief 2026-07-17
    "/law-ingest": "law-ingest.json",  # ruling 34c (field feedback 2026-08-07)
    "/leads-quality": "leads-quality.json",  # S6.1 of the Leads-calibration brief 2026-07-18
    "/card-audit": "card-audit.json",  # the DEEP card-system audit (summary depth)
    "/bulletin-preview": "bulletin-weekly.json",  # Bulletin Layer A, weekly period
    "/keyword-triage/last": "keyword-triage-run.json",
    "/keyword-triage/proposal": "keyword-triage-proposal.json",
    "/llm-throughput-selftest": "llm-throughput-selftest.json",
    "/ai-activity": "ai-activity.json",
    "/ai-activity-selftest": "ai-activity-selftest.json",
    "/source-tags-selftest": "source-tags-selftest.json",
    "/source-tags/last": "source-tags-run.json",
    "/perception-extract/last": "perception-extract-run.json",
    "/ai": "ai.json",
    "/qualification-assist-selftest": "qualification-assist-selftest.json",
    "/qualification-assist/last": "qualification-assist-run.json",
    "/model-bench/last": "model-bench.json",
    "/ai-check/last": "ai-check.json",
    # transversal audit 09 (2026-07-25), C2: /fixity is a genuine diagnostic-shaped
    # report (a local re-hash audit) that happened to live in the SIBLING
    # src/api/integrity.py router -- see _DIAG_SIBLING_FILES below, which is what
    # makes this path (and integrity.py's three functional exemptions right below)
    # visible to the scan at all.
    "/fixity": "fixity.json",
}
_DIAG_COVERAGE_EXEMPT: dict[str, str] = {
    "/source-quality": "whole-corpus decrypt ZIP export — own button (manifest 'excluded')",
    "/rollup-benchmark": "heavy operator-run benchmark (manifest 'excluded')",
    "/llm-bench": "heavy operator-run benchmark, needs a live model (manifest 'excluded')",
    "/llm-throughput": (
        "heavy operator-run concurrency sweep, needs a live model — minutes of real "
        "generation (manifest 'excluded'); its MECHANISM rides the bundle as "
        "llm-throughput-selftest.json"
    ),
    "/source-coverage-benchmark": "heavy operator-run benchmark (manifest 'excluded')",
    "/ir-eval": "needs an operator-graded gold-set file (manifest 'excluded')",
    "/gold-builder/sample": "interactive grading sampler, not a report (manifest 'excluded')",
    "/all": "the bundle itself",
    "/all-job/status": "job control", "/all-job/download": "job control",
    "/p0-validation/status": "job control", "/p0-validation/download": "job control",
    "/discover-world/status": "job control",
    "/enrich-source-types/status": "job control",
    "/keyword-triage/status": "job control", "/keyword-triage/download": "job control",
    "/source-tags/status": "job control", "/source-tags/download": "job control",
    "/perception-extract/status": "job control", "/perception-extract/download": "job control",
    "/perception-extract/gate": "job control — a live, cheap gate preview, not a static report",
    "/ai-coordinator/status": "job control — the background-AI lane's live state",
    "/model-bench/status": "job control", "/model-bench/download": "job control",
    "/ai-check/status": "job control", "/ai-check/download": "job control",
    "/model-bench/batch": (
        "the frozen bench INPUT's own summary — the RESULTS ride the bundle as "
        "model-bench.json, and that member already states the batch digest it answered"
    ),
    "/model-bench/anchors": (
        "the interactive grading sitting (and its sample), not a report — the anchors' "
        "effect is reported inside model-bench.json as anchor accuracy"
    ),
    "/model-bench/gates": (
        "a LIVE per-language gate view computed from the bench artifact, not a static "
        "report — the artifact itself (model-bench.json) is the bundle member"
    ),
    "/card-audit/status": "job control", "/card-audit/download": "job control",
    "/card-audit/preflight": (
        "a live, cheap size ESTIMATE for a deep run, not a static report — the "
        "summary-depth audit itself is the bundle member (card-audit.json)"
    ),
    # src/api/integrity.py (transversal audit 09, C2): functional source-integrity
    # API endpoints a UI feature calls directly (coordination/prominence views) —
    # not diagnostic reports, unlike their sibling /fixity above.
    "/profile": "functional source-integrity API (src/api/integrity.py), not a diagnostic report",
    "/actors": "functional source-integrity API (src/api/integrity.py), not a diagnostic report",
    "/prominence": "functional source-integrity API (src/api/integrity.py), not a diagnostic report",
}
# transversal audit 09 (2026-07-25), C2: the completeness ratchet below was found
# structurally blind to any diagnostic-shaped GET route living in a SIBLING router
# file (integrity.py's own /fixity local audit was invisible to it) -- both the
# runtime coverage report AND the CI ratchet test now scan every file named here, in
# ADDITION to this module's own source, so a future diagnostic hiding in another
# router closes the SAME class of gap in one line rather than being independently
# rediscovered. Filenames are relative to this module's own directory (src/api/).
_DIAG_SIBLING_FILES: tuple[str, ...] = ("integrity.py",)


def _diagnostics_coverage_report() -> dict:
    """Recompute the route-vs-member-vs-exemption completeness comparison AT RUN TIME
    (maintainer ruling: "ensured in the log, not just in CI") -- reads THIS module's own
    source PLUS every ``_DIAG_SIBLING_FILES`` router (never anything unlisted), the same
    technique the CI ratchet uses, against the shared ``_DIAG_COVERAGE_MAP``/
    ``_DIAG_COVERAGE_EXEMPT`` above so the two checks cannot silently diverge. Degrades to
    ``{"available": False}`` rather than ever failing the whole bundle build over an
    introspection quirk."""
    import re as _re

    try:
        src = pathlib.Path(__file__).read_text(encoding="utf-8")
        gets = set(_re.findall(r'@router\.get\("([^"]+)"', src))
        for _fname in _DIAG_SIBLING_FILES:
            gets |= set(
                _re.findall(
                    r'@router\.get\("([^"]+)"',
                    (pathlib.Path(__file__).parent / _fname).read_text(encoding="utf-8"),
                )
            )
        covered = set(_DIAG_COVERAGE_MAP)
        exempt = set(_DIAG_COVERAGE_EXEMPT)
        unclassified = sorted(gets - covered - exempt)
        stale = sorted((covered | exempt) - gets)
        members_block = src.split("def _all_diagnostics_members", 1)[1].split("def _", 1)[0]
        missing_members = sorted(
            fname for fname in _DIAG_COVERAGE_MAP.values() if f'"{fname}"' not in members_block
        )
        return {
            "available": True,
            "total_get_routes": len(gets),
            "covered_routes": len(covered),
            "exempt_routes": len(exempt),
            "unclassified": unclassified,
            "stale_classifications": stale,
            "missing_bundle_members": missing_members,
            "complete": not unclassified and not stale and not missing_members,
        }
    except Exception as exc:  # noqa: BLE001 - a coverage-recompute glitch must not sink the run
        return {"available": False, "reason": _all_diag_err_str(exc)}


def _corpus_counters_safe(db) -> dict:
    """A read-only articles/keywords/mentions snapshot for the manifest run header -- so a
    reader comparing logs across runs/machines knows what CORPUS SIZE produced each one.
    Bounded by the same DB-member statement deadline; degrades honestly if db is absent
    (the sync route's absorption-gated test path) or the read itself fails/times out."""
    if db is None:
        return {"available": False, "reason": "no database session"}
    try:
        with statement_deadline(db, _all_diag_db_member_deadline_s()):
            return {
                "available": True,
                "articles": int(db.query(func.count(Article.id)).scalar() or 0),
                "keywords": int(db.query(func.count(Keyword.id)).scalar() or 0),
                "mentions": int(db.query(func.count(KeywordMention.id)).scalar() or 0),
            }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": _all_diag_err_str(exc)}


def _schema_head_safe() -> str:
    """The migrations script directory's head revision (what the CODE expects), via
    alembic's ScriptDirectory API -- never a regex-scan, never a fabricated guess.
    'unavailable' on any failure (alembic missing, a branched/multi-head history, an
    unreadable migrations/ dir)."""
    try:
        from src.database.migrate import schema_head

        head = schema_head()
        return head if head else "unavailable"
    except Exception:  # noqa: BLE001
        return "unavailable"


def _disk_rotational_probe(target_dir) -> object:
    """Honest Linux-only probe of whether the disk backing ``target_dir`` is rotational
    (HDD) or not (SSD/NVMe), via ``/sys/block/*/queue/rotational`` -- the exact file the
    AMENDED ruling names. Resolves the SPECIFIC block device backing the directory via
    ``os.stat().st_dev`` -> ``/sys/dev/block/<major>:<minor>`` where possible (a partition
    node's queue/ lives on its parent whole-disk device); falls back to the first probed
    device in ``/sys/block/*`` if the precise resolution fails. Returns the honest string
    'unavailable' on non-Linux platforms or if sysfs is unreadable -- NEVER fabricated."""
    import sys as _sys

    if not _sys.platform.startswith("linux"):
        return "unavailable"
    try:
        st = os.stat(target_dir)
        major, minor = os.major(st.st_dev), os.minor(st.st_dev)
        node = pathlib.Path(f"/sys/dev/block/{major}:{minor}").resolve()
        for cand in (node / "queue" / "rotational", node.parent / "queue" / "rotational"):
            if cand.exists():
                val = cand.read_text(encoding="utf-8").strip()
                return "rotational" if val == "1" else "ssd/nvme"
    except Exception:  # noqa: BLE001 - fall through to the coarse scan below
        pass
    try:
        import glob as _glob

        for qpath in sorted(_glob.glob("/sys/block/*/queue/rotational")):
            dev = qpath.split("/")[3]
            if dev.startswith(("loop", "ram")):
                continue
            val = pathlib.Path(qpath).read_text(encoding="utf-8").strip()
            return "rotational" if val == "1" else "ssd/nvme"
    except Exception:  # noqa: BLE001
        pass
    return "unavailable"


def _cpu_model_safe() -> str:
    """Best-effort CPU model string, LOCAL reads only, zero network. 'unavailable' if the
    platform-specific source can't be read (never fabricated)."""
    import sys as _sys

    try:
        if _sys.platform.startswith("linux"):
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        elif _sys.platform == "darwin":
            import subprocess

            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=2,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        else:
            import platform as _platform

            proc = _platform.processor()
            if proc:
                return proc
    except Exception:  # noqa: BLE001
        pass
    return "unavailable"


def _hardware_profile() -> dict:
    """LOCAL machine facts for the manifest run header (AMENDED ruling, 2026-07-20):
    cross-machine comparison is the point (the maintainer tests across several rigs incl.
    low/cheap/old laptops), so every measurement in the log needs the hardware it was taken
    on stated alongside it. All reads are LOCAL (stdlib os/platform/shutil + the already-
    depended-on psutil); zero network calls. Every field degrades to the honest string
    'unavailable' rather than a guess; an operator-set ``OO_MACHINE_LABEL`` (optional) makes
    logs from different machines distinguishable at a glance."""
    import platform as _platform
    import shutil as _shutil

    try:
        os_name = _platform.platform()
    except Exception:  # noqa: BLE001 - degrade honestly, never guess or crash the run
        os_name = "unavailable"
    try:
        kernel = _platform.release()
    except Exception:  # noqa: BLE001
        kernel = "unavailable"
    profile: dict = {
        "os": os_name,
        "kernel": kernel,
        "cpu_model": _cpu_model_safe(),
        "machine_label": os.environ.get("OO_MACHINE_LABEL") or None,
    }
    try:
        import psutil

        profile["cpu_physical_cores"] = psutil.cpu_count(logical=False) or "unavailable"
        profile["cpu_logical_cores"] = psutil.cpu_count(logical=True) or "unavailable"
        freq = psutil.cpu_freq()
        profile["cpu_freq_mhz"] = round(freq.current, 1) if freq and freq.current else "unavailable"
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        profile["ram_total_bytes"] = int(vm.total)
        profile["swap_total_bytes"] = int(sm.total)
    except Exception:  # noqa: BLE001 - psutil unavailable/unsupported on this platform
        for k in (
            "cpu_physical_cores", "cpu_logical_cores", "cpu_freq_mhz",
            "ram_total_bytes", "swap_total_bytes",
        ):
            profile.setdefault(k, "unavailable")
    try:
        target = str(_all_diagnostics_dir())
        profile["disk_free_bytes"] = int(_shutil.disk_usage(target).free)
    except Exception:  # noqa: BLE001
        target = "."
        profile["disk_free_bytes"] = "unavailable"
    profile["disk_rotational"] = _disk_rotational_probe(target)
    return profile


def _all_diagnostics_manifest(
    results: list[dict],
    *,
    db=None,
    run_started_at: float | None = None,
    run_ended_at: float | None = None,
    exclusive: dict | None = None,
) -> dict:
    import platform
    import sys as _sys

    run_started_iso = (
        datetime.fromtimestamp(run_started_at).isoformat(timespec="seconds")
        if run_started_at else None
    )
    run_ended_iso = (
        datetime.fromtimestamp(run_ended_at).isoformat(timespec="seconds")
        if run_ended_at else None
    )
    total_wall_s = (
        round(run_ended_at - run_started_at, 3)
        if (run_started_at is not None and run_ended_at is not None) else None
    )
    slowest_members = sorted(
        (
            {"file": r["file"], "wall_s": r["wall_s"]}
            for r in results if r.get("wall_s") is not None
        ),
        key=lambda r: r["wall_s"], reverse=True,
    )[:10]

    return {
        "export_schema": "oo-export-1",
        "kind": "all-diagnostics",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": _sys.version.split()[0],
        "platform": platform.platform(),
        # RUN HEADER (DIAGNOSE-THE-DIAGNOSTICS, 2026-07-20): the 0.3 gate row-3 tie-in --
        # a failed hour-long 5M-scale run must be diagnosable FROM THE ARCHIVE ITSELF, not
        # just from having watched it live. Corpus size + app/schema version + the hardware
        # it ran on + which member ate the wall time, all in one place.
        "run": {
            "app_version": app_version(),
            "schema_head": _schema_head_safe(),
            "corpus": _corpus_counters_safe(db),
            "hardware": _hardware_profile(),
            "started_at": run_started_iso,
            "ended_at": run_ended_iso,
            "total_wall_s": total_wall_s,
            "slowest_members": slowest_members,
            "runtime_coverage": _diagnostics_coverage_report(),
            # EXCLUSIVE HOLD (S6.1, 2026-09-03): what the run actually claimed, not what
            # it wished for. `held` says the hold was taken; `paused_collection` says the
            # continuous loop was RUNNING and got signalled -- the pause is bounded and
            # best-effort, so a pass already deep in a fetch may still have been finishing
            # while this bundle ran. A degrade carries its `reason` instead. Never a bare
            # "exclusive: true", which would assert an isolation the pause cannot confirm.
            "exclusive": exclusive
            if exclusive is not None
            else {"held": False, "reason": "not requested by this caller"},
        },
        "members": results,
        # HONESTY (2026-07-17): what is deliberately NOT in this archive, and why —
        # so "all diagnostics" states its own boundary instead of implying totality.
        "excluded": [
            {
                "endpoint": "/api/diagnostics/keywords",
                "reason": "the FULL keyword corpus dump has its own sized/paged export; "
                "the bounded keyword-log DIGEST is included instead",
            },
            {
                "endpoint": "/api/diagnostics/source-quality",
                "reason": "a whole-corpus decrypt pass producing a bulky per-source "
                "text-sample ZIP — run it from its own Diagnostics button",
            },
            {
                "endpoint": "/api/diagnostics/card-audit/preflight",
                "reason": "a live size ESTIMATE for a deep card-audit run, not a static "
                "report — the SUMMARY-depth audit itself IS a bundle member "
                "(card-audit.json); the deeper depths carry article CONTENT and are "
                "an operator-chosen background job",
            },
            {
                "endpoint": "/api/diagnostics/rollup-benchmark",
                "reason": "a heavy live-vs-rollup benchmark over the real corpus — "
                "operator-run from its own button",
            },
            {
                "endpoint": "/api/diagnostics/source-coverage-benchmark",
                "reason": "same class: a heavy operator-run benchmark",
            },
            {
                "endpoint": "/api/diagnostics/model-bench/run",
                "reason": "the comparative model bench loads every roster model in turn "
                "and can run for hours — operator-run from its own button on the machine "
                "that hosts the models. Its RESULT rides the bundle as model-bench.json",
            },
            {
                "endpoint": "/api/diagnostics/ir-eval",
                "reason": "needs an operator-graded gold-set file as input",
            },
            {
                "endpoint": "/api/diagnostics/gold-builder/sample",
                "reason": "an interactive grading sampler, not a report",
            },
            {
                "endpoint": "job control/status/download endpoints",
                "reason": "p0-validation, keyword-triage and source-tags each "
                "contribute their LAST saved report/summary as a member; starting/cancelling a "
                "job or downloading its raw dated JSONL log is not a report",
            },
        ],
        "note": (
            "Every diagnostics log in one archive (the maintainer↔developer channel). "
            "Deliberate exclusions are listed in 'excluded' with reasons. "
            "Generated only on click; nothing is transmitted by the app."
        ),
    }


def _write_all_diagnostics_zip(
    members, zf, *, progress=None, should_stop=None, journal_path=None, db=None,
    exclusive=None,
) -> list[dict]:
    """Write every member (+ manifest) into the open ZipFile ``zf``; return the per-member
    results. Shared by the sync endpoint (an in-memory BytesIO) and the job (a file on disk).
    ``progress(done, total, name)`` reports live progress; ``should_stop()`` lets the job
    cancel cooperatively BETWEEN members (a single member — e.g. the benchmark — can't be
    interrupted mid-run). One failing log never aborts the bundle (a ``<name>.error.txt`` is
    written and recorded in the manifest).

    ENVELOPE (0.3 gate row 3 / DIAGNOSE-THE-DIAGNOSTICS, 2026-07-20): every member records
    ``{file, ok, outcome, started_at, wall_s, bytes, rss_basis[, error][, rss_delta_kb]
    [, rss_peak_rise_kb][, release]}`` -- ``ok`` is KEPT (True iff ``outcome == "ok"``) for
    any reader still on the old boolean.

    S6.2 (2026-09-03): ``rss_delta_kb`` was computed from ``ru_maxrss``, a process
    high-water mark that never falls, so every member after the first big one reported 0.
    It is now a CURRENT-RSS delta, the high-water rise keeps its own name
    (``rss_peak_rise_kb``), and ``rss_basis`` says which instrument answered so a platform
    with no current reading cannot be mistaken for one. After a member that actually moved
    the resident set, ``hygiene._malloc_trim`` returns the allocator's arenas to the OS and
    ``release.freed_kb`` records what that measured -- so a delta that survives a trim is a
    real retention rather than allocator noise.

    DEADLINES (S8 lesson): a member whose thunk closes over ``db`` (touches the shared
    connection) runs INLINE under a statement deadline — never threaded, because a shared
    SQLite/SQLCipher connection BLOCKS (not errors) under concurrent use and a statement
    deadline bounds only SQL VM opcodes, never the Python row-materialisation around them,
    so a DB worker could never be cleanly abandoned mid-query. A non-DB member runs on a
    daemon wall-clock-bounded thread. Either way a timeout records outcome
    ``skipped-deadline`` honestly and the bundle CONTINUES to the next member (never aborts).

    JOURNAL: when ``journal_path`` is given (the background job path only — the sync route's
    in-memory BytesIO build has no durable file to journal against), a begin/end JSON line is
    appended + fsync'd around every member, so a HARD-killed run's last ``begin`` with no
    matching ``end`` NAMES the culprit member — a diagnosis the in-memory manifest (written
    only once, at the very end) cannot offer a crashed run."""
    import time as _time

    results: list[dict] = []
    total = len(members)
    run_started_at = _time.time()
    # Left open across the whole loop (appended + fsync'd per member) and closed in the
    # `finally` below -- a `with` here would have to wrap the entire member loop AND the
    # conditional-None case, which reads worse than the explicit open/close pair below.
    journal_fp = (
        open(journal_path, "a", encoding="utf-8")  # noqa: SIM115
        if journal_path is not None else None
    )
    # S6.2: resolved ONCE, before the first member is measured -- a memory instrument
    # rebuilt per reading perturbs the very thing it reads (measured 5/5).
    _rss = _RssProbe()
    try:
        for i, (name, fn) in enumerate(members):
            if should_stop is not None and should_stop():
                break
            if progress is not None:
                progress(i, total, name)
            started_t = _time.time()
            started_iso = datetime.now().isoformat(timespec="seconds")
            if journal_fp is not None:
                try:
                    journal_fp.write(
                        json.dumps(
                            {"event": "begin", "file": name, "i": i, "total": total,
                             "started_at": started_iso}
                        ) + "\n"
                    )
                    journal_fp.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(journal_fp.fileno())
                except OSError:
                    # The journal is a diagnostic aid, not the bundle itself -- a write
                    # failure (e.g. ENOSPC on the sidecar's disk) must degrade the run to
                    # unjournaled rather than abort a hard-won hour-long bundle.
                    _LOG.warning(
                        "all-diagnostics journal write failed; disabling journal for the "
                        "rest of this run", exc_info=True
                    )
                    with contextlib.suppress(OSError):
                        journal_fp.close()
                    journal_fp = None

            rss_before = _rss.kb()
            peak_before = _rss_peak_kb()
            outcome = "ok"
            err: str | None = None
            nbytes = 0
            try:
                if db is not None and _member_touches_db(fn):
                    with statement_deadline(db, _all_diag_db_member_deadline_s()):
                        value = fn()
                        # S2.2: a member that STOPPED at the deadline and returned
                        # what it had is PARTIAL, not skipped. Recording
                        # "skipped-deadline" writes only a marker (see the branch
                        # below) and would DISCARD the payload -- home-cards' cards,
                        # card-audit's diagnoses -- which is the opposite of what an
                        # operator diagnosing a slow machine needs. Read the expiry
                        # INSIDE the block: leaving it restores the enclosing value.
                        if deadline_expired(db):
                            outcome = "partial-deadline"
                else:
                    value = _run_nondb_member_bounded(fn, _all_diag_nondb_member_deadline_s())
                    if value is _ALL_DIAG_DEADLINE_SENTINEL:
                        outcome = "skipped-deadline"
                if outcome in ("ok", "partial-deadline"):
                    payload = _member_bytes(value)
                    zf.writestr(name, payload)
                    nbytes = len(payload)
                else:
                    marker = (
                        f"member exceeded its {_all_diag_nondb_member_deadline_s():.0f}s "
                        "wall-clock deadline and was abandoned (non-DB member)"
                    ).encode()
                    zf.writestr(name + ".skipped-deadline.txt", marker)
            except StatementTimeout as exc:
                outcome = "skipped-deadline"
                zf.writestr(name + ".skipped-deadline.txt", _all_diag_err_str(exc))
            except Exception as exc:  # noqa: BLE001 - one failing member must not abort the bundle
                outcome = "error"
                err = _all_diag_err_str(exc)
                zf.writestr(name + ".error.txt", err)

            wall_s = round(_time.time() - started_t, 3)
            rss_after = _rss.kb()
            peak_after = _rss_peak_kb()
            entry: dict = {
                "file": name,
                "ok": outcome == "ok",
                "outcome": outcome,
                "started_at": started_iso,
                "wall_s": wall_s,
                "bytes": nbytes,
            }
            if err is not None:
                entry["error"] = err
            # S6.2: the delta is now CURRENT RSS, which rises and falls, so it measures
            # THIS member. ``rss_basis`` names the instrument, and the high-water rise
            # keeps its own name rather than being published as the same number under a
            # different meaning -- "did this member allocate 40 MB" and "did it push the
            # process past its all-time peak" are different questions and only one of them
            # can be answered after the first big member.
            entry["rss_basis"] = _rss.basis
            if rss_before is not None and rss_after is not None:
                entry["rss_delta_kb"] = rss_after - rss_before
            if peak_before is not None and peak_after is not None:
                entry["rss_peak_rise_kb"] = peak_after - peak_before
            if rss_before is not None and rss_after is not None \
                    and (rss_after - rss_before) >= _ALL_DIAG_TRIM_AFTER_KB:
                trim = _trim_after_heavy_member(_rss, rss_after)
                if trim is not None:
                    entry["release"] = trim
            results.append(entry)

            if journal_fp is not None:
                try:
                    journal_fp.write(
                        json.dumps(
                            {"event": "end", "file": name, "outcome": outcome, "wall_s": wall_s}
                        ) + "\n"
                    )
                    journal_fp.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(journal_fp.fileno())
                except OSError:
                    _LOG.warning(
                        "all-diagnostics journal write failed; disabling journal for the "
                        "rest of this run", exc_info=True
                    )
                    with contextlib.suppress(OSError):
                        journal_fp.close()
                    journal_fp = None
    finally:
        if journal_fp is not None:
            journal_fp.close()

    run_ended_at = _time.time()
    manifest = _all_diagnostics_manifest(
        results, db=db, run_started_at=run_started_at, run_ended_at=run_ended_at,
        exclusive=exclusive,
    )
    zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    # Fold the durable journal into the finished archive as bundle-journal.jsonl -- the
    # sidecar on disk has done its job (any hard-kill forensics happen from the sidecar
    # ITSELF, before this point is ever reached); the caller removes the sidecar file.
    if journal_path is not None and pathlib.Path(journal_path).exists():
        zf.writestr(
            "bundle-journal.jsonl", pathlib.Path(journal_path).read_text(encoding="utf-8")
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
    # S6.1: both entry points to this build take the hold, not just the job. The
    # PR-13 lesson in miniature -- a guard wired into one of two callers is the
    # gate-every-entry-point defect, and this route can run for 36+ minutes.
    with _bundle_exclusive_window() as excl, \
            zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        _write_all_diagnostics_zip(_all_diagnostics_members(db), z, db=db, exclusive=excl)
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


def _bundle_exclusive_window():
    """S6.1: hold the machine for the bundle's duration, so it never competes with a
    collection pass, the housekeeping lane or the rollup build.

    Uses ``runner.exclusive_window()`` -- the existing RE-ENTRANT, imbalance-proof
    mechanism -- rather than calling ``hold_exclusive``/``release_exclusive`` directly.
    That distinction is load-bearing, not stylistic: ``_exclusive_hold`` is a BOOLEAN, so a
    bundle started during a restore would clear the RESTORE's hold on its own release and
    put a manual "Run now" back on the machine mid-restore -- reinstating exactly the
    concurrency defect the 2026-07-24 lesson records. ``exclusive_window`` restores the flag
    to what it FOUND, so only the outermost block ever resumes.

    Yields the honest facts rather than an assumed exclusivity: ``paused_collection`` is
    ``was_paused``, i.e. whether the continuous loop was actually running and got signalled
    -- the pause is bounded and best-effort, and a pass already deep in a fetch may still be
    finishing. ``nested`` says the machine was already owned by an outer operation.

    Ruling 4 is unaffected: this changes what else may run, never which members do. Every
    member still runs.
    """
    import contextlib as _cl

    @_cl.contextmanager
    def _cm():
        try:
            from src.scheduler.runner import exclusive_window, exclusive_window_open
        except Exception:  # noqa: BLE001 - a bundle must never fail for want of the hold
            yield {"held": False, "reason": "scheduler unavailable"}
            return
        nested = False
        try:
            nested = bool(exclusive_window_open())
        except Exception:  # noqa: BLE001 - an unknown state is never claimed as ownership
            nested = False
        try:
            with exclusive_window() as was_paused:
                yield {
                    "held": True, "paused_collection": bool(was_paused), "nested": nested,
                }
        except Exception:  # noqa: BLE001 - the bundle is the evidence channel; never lose it
            _LOG.warning("all-diagnostics could not claim the machine", exc_info=True)
            yield {"held": False, "reason": "could not claim the machine"}

    return _cm()


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
    # DURABLE JOURNAL sidecar (DIAGNOSE-THE-DIAGNOSTICS, 2026-07-20): begin/end lines
    # appended + fsync'd around every member as the build runs, so a HARD kill (OOM/kill
    # -9, not a cooperative cancel) leaves this file on disk with its last `begin` unmatched
    # by an `end` -- naming the culprit member for an hour-long 5M-scale run gone wrong. On
    # a clean finish it is folded into the zip as bundle-journal.jsonl and the sidecar is
    # removed (its job is done); on a hard kill it simply survives as forensic evidence.
    journal_path = out_dir / (fname + ".journal.jsonl")
    with _bundle_exclusive_window() as excl, session_scope() as db:
        members = _all_diagnostics_members(db)

        def _progress(done, total, name):
            ctx.set_progress(done=done, total=total, detail=name)

        with zipfile.ZipFile(part_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            results = _write_all_diagnostics_zip(
                members, z, progress=_progress, should_stop=lambda: ctx.stopping,
                journal_path=journal_path, db=db, exclusive=excl,
            )
    if ctx.stopping:
        # Cancelled between members: drop the partial, never present it as a good archive.
        with contextlib.suppress(OSError):
            part_path.unlink()
        with contextlib.suppress(OSError):
            journal_path.unlink()
        return {"cancelled": True, "members": results}
    _os.replace(part_path, final_path)  # atomic publish
    with contextlib.suppress(OSError):
        journal_path.unlink()  # folded into the zip as bundle-journal.jsonl already
    # Keep only the newest archive (the channel is one-shot; old ones just consume disk).
    # Also sweep any stale ``.part``/``.journal.jsonl`` left by a PREVIOUS crashed/killed
    # run — this run's own part/journal were just renamed away/removed, and the job is
    # single-instance, so no live writer is touched (no orphaned staging accumulates
    # across hard-kills).
    for old in (
        *out_dir.glob("oo-all-diagnostics-*.zip"),
        *out_dir.glob("oo-all-diagnostics-*.zip.part"),
        *out_dir.glob("oo-all-diagnostics-*.journal.jsonl"),
    ):
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


def _newest_all_diagnostics_archive() -> pathlib.Path | None:
    """The newest FINISHED archive on disk, or None.

    ``.part`` files are excluded: one is an in-flight or abandoned build, and serving a
    truncated zip as a finished archive would be the worst possible answer for an operator
    who is already trying to diagnose something. The glob alone cannot match one (a
    ``.part`` name does not end in ``.zip``); the suffix check states the requirement
    instead of leaving it resting on that.
    """
    try:
        files = [
            p for p in _all_diagnostics_dir().glob("oo-all-diagnostics-*.zip")
            if p.suffix == ".zip" and p.is_file()
        ]
        # A file can vanish between glob and stat (the worker sweeps old archives), so the
        # key is guarded rather than allowed to raise out of a sort.
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    except OSError:
        return None


@router.get("/all-job/download")
def all_diagnostics_job_download() -> FileResponse:
    """Serve the finished background all-diagnostics archive (D2). 404 until a build has
    completed successfully (run ``/all-job`` first).

    FALLS BACK TO DISK when the in-memory job result is gone. The job object lives only as
    long as the process, while the archive it published lives in ``data_dir()/diagnostics/``
    until a later build sweeps it — so an app restart between a finished build and the click
    that claims it used to strand a multi-hour archive that was sitting right there,
    answering 404 about a file on disk. This is not hypothetical for this app: an OOM during
    a large import is precisely when the operator most needs the bundle and least likely to
    have kept the process alive.

    It NEVER falls back while a build is RUNNING. The operator asked the NEW run a question,
    and the previous run's archive cannot answer it; handing it over silently would be a
    fabricated result — the one thing a diagnostic must not produce.
    """
    st = _ALL_DIAG_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if st.get("state") == "done" and path and os.path.exists(path):
        return FileResponse(
            path, media_type="application/zip",
            filename=res.get("filename") or "oo-all-diagnostics.zip",
        )
    if st.get("state") != "running":
        on_disk = _newest_all_diagnostics_archive()
        if on_disk is not None:
            return FileResponse(
                str(on_disk), media_type="application/zip", filename=on_disk.name,
            )
    raise HTTPException(
        status_code=404,
        detail="no all-diagnostics archive is ready — start one with POST /api/diagnostics/all-job",
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




# ---------------------------------------------------------------------------
#  Real keyword-TRIAGE run (Section 8, maintainer-ruled 2026-07-20): the batch
#  runner + parser + canaries + EXPORT-ONLY JSONL already existed
#  (``src/ai_layer/triage.py``) but its only caller was its own selftest. This is
#  the REAL wiring -- a visible, abortable BackgroundJob over the live corpus,
#  driving the SAME core. Mirrors the p0-validation job surface
#  exactly. NEVER writes the trusted keyword index -- EXPORT-ONLY JSONL, per the
#  ruling. The airplane/Ollama gate split (2026-07-24 field-feedback Session A,
#  §7) landed: this runs offline too, gated only by the client's own loopback-
#  vs-clearnet check -- no blanket airplane-mode refusal here anymore.
# ---------------------------------------------------------------------------


class KeywordTriageRunBody(BaseModel):
    model: str | None = Field(
        default=None,
        description=(
            "an INSTALLED model tag on the active backend (refused if not "
            "installed); omitted or null falls back to the operator's chosen "
            "active model (Settings -> AI) -- there is no need to type a model "
            "for a routine run."
        ),
    )
    restart: bool = Field(
        default=False,
        description=(
            "discard any saved sweep cursor and start a brand-new sweep (a new "
            "dated log file); otherwise an unfinished sweep RESUMES where it left "
            "off (default)."
        ),
    )


def _keyword_triage_worker(ctx, **kwargs) -> dict:
    from src.ai_layer.triage_job import run_progressive_triage_job

    # A MANUAL sweep run is a user-initiated batch (2026-08-01 ruling 13): it
    # takes the exclusive hold so the coordinator stands down instead of
    # competing with it for the same single-generation backend. When the
    # COORDINATOR itself drives this sweep it calls the underlying function
    # directly, so it never holds against itself.
    from src.ai_layer.coordinator import user_batch_hold

    with user_batch_hold("manual keyword triage run"):
        return run_progressive_triage_job(ctx, **kwargs)


_KEYWORD_TRIAGE_JOB = register_job(
    BackgroundJob(
        "keyword-triage", "LLM keyword triage (Section 8, real run)", _keyword_triage_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/keyword-triage/run")
def keyword_triage_run(body: KeywordTriageRunBody) -> JSONResponse:
    """Start (or resume) the REAL keyword-triage PROGRESSIVE SWEEP as a BACKGROUND
    job (B5, 2026-07-24 Session B, ruled -- the numeric limit/batch-size inputs are
    GONE; this is now an ON/OFF toggle): sweep the ENTIRE head scope, in bounded
    batches, through the local model (canaries on every batch, echo-back +
    constrained-verdict validation, per ``ai_layer.triage``), appending EXPORT-ONLY
    JSONL to ``data_dir()/triage/oo-keyword-triage-<date>.jsonl``. NEVER writes the
    trusted keyword index. Loopback Ollama inference is airplane-safe (the socket
    never leaves 127.0.0.1) -- so this endpoint runs fine under airplane mode,
    gated ONLY by the client's own loopback-vs-clearnet check. ``model`` omitted
    falls back to the operator's active model (2026-07-26 field-remarks item 2 --
    ``active_model()``, the same house-wide fallback every other AI feature
    already uses); also (400) if the resolved model is not an INSTALLED tag
    (``verify_roster`` -- never substitutes a 'close' tag). A PERSISTED CURSOR
    survives a cancel, a crash, or an app restart, so re-calling this (without
    ``restart``) continues the SAME sweep instead of starting over. Poll
    ``/keyword-triage/status``; download the dated log via
    ``/keyword-triage/download``. 409-free for an already-running job: returns
    its current status with ``started:false``."""
    from src.ai_layer.triage import verify_roster
    from src.api.llm import active_model
    from src.llm.backend import get_client_with_name
    from src.llm.ollama import LLMUnavailable

    model = body.model or active_model()
    try:
        _, active_client = get_client_with_name()
        installed = active_client.list_installed()
    except LLMUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    roster = verify_roster([model], installed)
    if not roster["ok"]:
        raise HTTPException(
            status_code=400,
            detail=f"model {model!r} is not installed ({installed}); "
            "pull/serve it first, or check the active backend in Settings -> AI.",
        )
    try:
        st = _KEYWORD_TRIAGE_JOB.start(model=model, restart=body.restart)
        st["started"] = True
    except RuntimeError:
        st = _KEYWORD_TRIAGE_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/keyword-triage/status")
def keyword_triage_status() -> JSONResponse:
    """Live status of the keyword-triage job (state, per-batch progress; when done,
    the ready download filename + the run summary in ``result``). No score."""
    st = _KEYWORD_TRIAGE_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(st)


@router.post("/keyword-triage/cancel")
def keyword_triage_cancel() -> JSONResponse:
    """Ask the running keyword-triage job to stop at its next safe point (between
    batches; a batch already in flight always finishes). The partial JSONL log is
    honestly marked ``cancelled`` in its trailing summary record. Idempotent."""
    _KEYWORD_TRIAGE_JOB.cancel()
    return JSONResponse(_KEYWORD_TRIAGE_JOB.status())


@router.get("/keyword-triage/last")
def keyword_triage_last() -> JSONResponse:
    """A JSON SUMMARY of the newest saved keyword-triage run (read-only; never runs
    a triage). Returns ``{available:false}`` honestly when none has been run.
    Serves the raw JSONL from ``/keyword-triage/download`` instead."""
    from src.ai_layer.triage_job import last_keyword_triage_report

    return JSONResponse(last_keyword_triage_report())


@router.get("/keyword-triage/proposal")
def keyword_triage_proposal(
    download: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """The REVIEWABLE artifact built from a finished run: junk verdicts grouped PER
    LANGUAGE (the collision-free scoped channel), kind overrides, and the evidence behind
    each proposed term — plus an explicit account of what was held back and why.

    Read-only and model-free: it reads the saved JSONL and joins the judged terms back to
    the live keyword rows for the language the log does not carry. Nothing is applied —
    a stoplist entry hides existing mentions at query time AND stops new ones being stored
    at index time, and only the second is undoable without a full re-index, which is
    exactly why this stays a proposal a human merges."""
    from src.ai_layer.triage_proposal import build_triage_proposal

    out = build_triage_proposal(db)
    headers = {}
    if download:
        fname = f"oo-keyword-triage-proposal-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(out, headers=headers)


@router.get("/keyword-triage/download")
def keyword_triage_download() -> Response:
    """Serve the newest keyword-triage JSONL log (the ai-proposed artifact a Claude
    session verifies before anything is applied). 404 until a run has produced one."""
    st = _KEYWORD_TRIAGE_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no keyword-triage log is ready -- start one with "
            "POST /api/diagnostics/keyword-triage/run",
        )
    return FileResponse(
        path, media_type="application/x-jsonlines",
        filename=res.get("filename") or "oo-keyword-triage.jsonl",
    )


# ---------------------------------------------------------------------------
#  Real source-TAG assignment run (design entry + GO ruling, maintainer
#  2026-07-20 -- the same chassis as the keyword-triage run above): per-source
#  top-N post-stoplist terms -> loopback Ollama -> CLOSED-vocabulary tag
#  classification (``src/ai_layer/source_tags.py``). EXPORT-ONLY JSONL; NEVER
#  writes ``Source.tags`` (the honesty rail -- the apply-reviewed-batch step is
#  later, explicit, maintainer-gated work). Mirrors the keyword-triage job
#  surface above exactly.
# ---------------------------------------------------------------------------


class SourceTagsRunBody(BaseModel):
    model: str | None = Field(
        default=None,
        description=(
            "an INSTALLED model tag on the active backend (refused if not "
            "installed); omitted or null falls back to the operator's chosen "
            "active model (Settings -> AI) -- there is no need to type a model "
            "for a routine run."
        ),
    )
    restart: bool = Field(
        default=False,
        description=(
            "discard any saved sweep cursor and start a brand-new sweep (a new "
            "dated log file); otherwise an unfinished sweep RESUMES where it left "
            "off (default)."
        ),
    )


def _source_tags_worker(ctx, **kwargs) -> dict:
    from src.ai_layer.source_tags_job import run_progressive_source_tags_job

    # A MANUAL sweep run is a user-initiated batch (2026-08-01 ruling 13): it
    # takes the exclusive hold so the coordinator stands down instead of
    # competing with it for the same single-generation backend. When the
    # COORDINATOR itself drives this sweep it calls the underlying function
    # directly, so it never holds against itself.
    from src.ai_layer.coordinator import user_batch_hold

    with user_batch_hold("manual source tags run"):
        return run_progressive_source_tags_job(ctx, **kwargs)


_SOURCE_TAGS_JOB = register_job(
    BackgroundJob(
        "source-tags", "LLM source-tag assignment (real run)", _source_tags_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/source-tags/run")
def source_tags_run(body: SourceTagsRunBody) -> JSONResponse:
    """Start (or resume) the REAL source-tag-assignment PROGRESSIVE SWEEP as a
    BACKGROUND job (B5, 2026-07-24 Session B, ruled -- the numeric top-N/limit
    inputs are GONE; this is now an ON/OFF toggle): resolve the live CLOSED tag
    vocabulary from every ``Source.tags`` value in the corpus, sweep EVERY source
    with sufficient evidence in bounded pages (a source below the evidence floor
    is SKIPPED, never guessed), through the local model (canaries + echo-back +
    closed-vocabulary rejection, per ``ai_layer.source_tags``), appending
    EXPORT-ONLY JSONL to ``data_dir()/triage/oo-source-tags-<date>.jsonl``. NEVER
    writes ``Source.tags``. Loopback Ollama inference is airplane-safe -- this
    endpoint runs fine under airplane mode, gated ONLY by the client's own
    loopback-vs-clearnet check. ``model`` omitted falls back to the operator's
    active model (2026-07-26 field-remarks item 2 -- ``active_model()``, the
    same house-wide fallback every other AI feature already uses); also (400)
    if the resolved model is not an installed tag. A PERSISTED CURSOR survives
    a cancel, a crash, or an app restart, so re-calling this (without
    ``restart``) continues the SAME sweep. Poll ``/source-tags/status``;
    download via ``/source-tags/download``. 409-free for an already-running
    job."""
    from src.ai_layer.triage import verify_roster
    from src.api.llm import active_model
    from src.llm.backend import get_client_with_name
    from src.llm.ollama import LLMUnavailable

    model = body.model or active_model()
    try:
        _, active_client = get_client_with_name()
        installed = active_client.list_installed()
    except LLMUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    roster = verify_roster([model], installed)
    if not roster["ok"]:
        raise HTTPException(
            status_code=400,
            detail=f"model {model!r} is not installed ({installed}); "
            "pull/serve it first, or check the active backend in Settings -> AI.",
        )
    try:
        st = _SOURCE_TAGS_JOB.start(model=model, restart=body.restart)
        st["started"] = True
    except RuntimeError:
        st = _SOURCE_TAGS_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/source-tags/status")
def source_tags_status() -> JSONResponse:
    """Live status of the source-tags job (state, per-batch progress; when done,
    the ready download filename + the run summary in ``result``). No score."""
    st = _SOURCE_TAGS_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(st)


@router.post("/source-tags/cancel")
def source_tags_cancel() -> JSONResponse:
    """Ask the running source-tags job to stop at its next safe point (between
    batches). The partial JSONL log is honestly marked ``cancelled``. Idempotent."""
    _SOURCE_TAGS_JOB.cancel()
    return JSONResponse(_SOURCE_TAGS_JOB.status())


@router.get("/source-tags/last")
def source_tags_last() -> JSONResponse:
    """A JSON SUMMARY of the newest saved source-tags run (read-only; never runs
    one). Returns ``{available:false}`` honestly when none has been run."""
    from src.ai_layer.source_tags_job import last_source_tags_report

    return JSONResponse(last_source_tags_report())


@router.get("/source-tags/download")
def source_tags_download() -> Response:
    """Serve the newest source-tags JSONL log (the ai-proposed artifact a Claude
    session verifies -- and the ONLY place these proposed tags live; ``Source.tags``
    is never touched by this run). 404 until a run has produced one."""
    st = _SOURCE_TAGS_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no source-tags log is ready -- start one with "
            "POST /api/diagnostics/source-tags/run",
        )
    return FileResponse(
        path, media_type="application/x-jsonlines",
        filename=res.get("filename") or "oo-source-tags.jsonl",
    )


@router.get("/source-tags-selftest")
def source_tags_selftest(download: bool = Query(False)) -> JSONResponse:
    """Run the LLM source-tag-assignment self-test -- the measure-before-trust GATE
    before any real run, mirroring ``/keyword-triage-selftest`` exactly. Proves the
    closed-vocabulary parser (an out-of-vocabulary tag rejects the WHOLE line),
    echo-back, the explicit 'none' verdict, and canaries on a deterministic STUB --
    no model, no network, no score. ``download=1`` returns a dated attachment."""
    from src.ai_layer.source_tags import run_source_tags_selftest

    log = run_source_tags_selftest()
    headers = {}
    if download:
        fname = f"oo-source-tags-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


# ---------------------------------------------------------------------------
#  Who/where/when PERCEPTION EXTRACTION -- eval-gated AI-layer candidates (B6,
#  2026-07-24 Session B, the NEW ask). §6.1 (the harness-against-the-active-model
#  run) is /perception-eval-live above; this is §6.2/§6.3 -- the REAL per-article
#  extraction sweep, same progressive-toggle chassis as keyword-triage/source-tags.
#  NEVER writes the trusted rule-based tables (article_mentioned_dates/_places/
#  article_entities); a language the harness failed ships DISABLED, shown via
#  /perception-extract/gate before the toggle is ever started.
# ---------------------------------------------------------------------------


class PerceptionExtractRunBody(BaseModel):
    model: str | None = Field(
        default=None,
        description=(
            "an INSTALLED model tag on the active backend (refused if not "
            "installed); omitted or null falls back to the operator's chosen "
            "active model (Settings -> AI) -- there is no need to type a model "
            "for a routine run."
        ),
    )
    restart: bool = Field(
        default=False,
        description=(
            "discard any saved sweep cursor and start a brand-new sweep (a new "
            "dated log file); otherwise an unfinished sweep RESUMES where it left "
            "off (default)."
        ),
    )


def _perception_extract_worker(ctx, **kwargs) -> dict:
    from src.ai_layer.perception_extract_job import run_progressive_perception_extract_job

    # A MANUAL sweep run is a user-initiated batch (2026-08-01 ruling 13): it
    # takes the exclusive hold so the coordinator stands down instead of
    # competing with it for the same single-generation backend. When the
    # COORDINATOR itself drives this sweep it calls the underlying function
    # directly, so it never holds against itself.
    from src.ai_layer.coordinator import user_batch_hold

    with user_batch_hold("manual perception extract run"):
        return run_progressive_perception_extract_job(ctx, **kwargs)


_PERCEPTION_EXTRACT_JOB = register_job(
    BackgroundJob(
        "perception-extract", "Who/where/when extraction (AI-derived candidates)",
        _perception_extract_worker, is_writer=True, cancellable=True,
    )
)


@router.get("/perception-extract/gate")
def perception_extract_gate() -> JSONResponse:
    """Which languages the LAST live perception-eval run cleared for extraction, and
    why not for the rest (read-only, cheap -- computed from the saved report; never
    starts an eval or a sweep). The standing "gate bites" ruling: the toggle UI shows
    which strata are active and why, even before the toggle is ever clicked."""
    from src.ai_layer.perception_extract_job import current_language_gate

    return JSONResponse(current_language_gate())


@router.post("/perception-extract/run")
def perception_extract_run(body: PerceptionExtractRunBody) -> JSONResponse:
    """Start (or resume) the who/where/when EXTRACTION progressive sweep as a
    BACKGROUND job: every non-quarantined article, id-ascending, in bounded batches,
    through the active backend -- a language that failed the last live perception-eval
    run (``/perception-extract/gate``) is honestly SKIPPED, never attempted. Writes
    ONLY ``ai_keyword`` candidates (kinds ``ai-who``/``ai-place``/``ai-date``, labelled
    "AI-derived - unreliable"); NEVER the trusted ``article_mentioned_*``/
    ``article_entities`` tables. A PERSISTED CURSOR survives a cancel, a crash, or an
    app restart. Loopback inference is airplane-safe. ``model`` omitted falls
    back to the operator's active model (2026-07-26 field-remarks item 2 --
    ``active_model()``, the same house-wide fallback every other AI feature
    already uses); also (400) if the resolved model is not an installed tag on
    the active backend. Poll ``/perception-extract/status``; download the
    dated log via ``/perception-extract/download``. 409-free for an
    already-running job: returns its current status with ``started:false``."""
    from src.api.llm import active_model
    from src.llm.backend import get_client_with_name
    from src.llm.ollama import LLMUnavailable

    model = body.model or active_model()
    try:
        _, active_client = get_client_with_name()
        installed = active_client.list_installed()
    except LLMUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if model not in installed:
        raise HTTPException(
            status_code=400,
            detail=f"model {model!r} is not installed ({installed}); "
            "pull/serve it first, or check the active backend in Settings -> AI.",
        )
    try:
        st = _PERCEPTION_EXTRACT_JOB.start(model=model, restart=body.restart)
        st["started"] = True
    except RuntimeError:
        st = _PERCEPTION_EXTRACT_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/perception-extract/status")
def perception_extract_status() -> JSONResponse:
    """Live status of the perception-extract job (state, per-batch progress; when
    done, the ready download filename + the run summary in ``result``). No score."""
    st = _PERCEPTION_EXTRACT_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(st)


@router.post("/perception-extract/cancel")
def perception_extract_cancel() -> JSONResponse:
    """Ask the running perception-extract job to stop at its next safe point (between
    batches; a batch already in flight always finishes). Idempotent."""
    _PERCEPTION_EXTRACT_JOB.cancel()
    return JSONResponse(_PERCEPTION_EXTRACT_JOB.status())


@router.get("/perception-extract/last")
def perception_extract_last() -> JSONResponse:
    """A JSON SUMMARY of the newest saved perception-extract run (read-only; never
    runs a sweep). Returns ``{available:false}`` honestly when none has been run."""
    from src.ai_layer.perception_extract_job import last_perception_extract_report

    return JSONResponse(last_perception_extract_report())


@router.get("/perception-extract/download")
def perception_extract_download() -> Response:
    """Serve the newest perception-extract JSONL log. 404 until a run has produced
    one."""
    st = _PERCEPTION_EXTRACT_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no perception-extract log is ready -- start one with "
            "POST /api/diagnostics/perception-extract/run",
        )
    return FileResponse(
        path, media_type="application/x-jsonlines",
        filename=res.get("filename") or "oo-perception-extract.jsonl",
    )


# --------------------------------------------------------------------------- #
#  ONE BUTTON: every AI check on this machine, in order, one report.
#  Maintainer 2026-08-09, after running four of them by hand: "Can you simplify all
#  AI related diagnostics into one single button to test everything at once?"
# --------------------------------------------------------------------------- #
class AiCheckRunBody(BaseModel):
    repeats: int = Field(default=2, ge=1, le=10, description="timed calls per latency shape")
    levels: str = Field(
        default="1,2,4,8",
        description="comma-separated concurrency levels for the throughput sweep",
    )
    calls_per_level: int = Field(default=8, ge=1, le=200)
    include_perception: bool = Field(
        default=True,
        description=(
            "run the live who/where/when eval — the gate that decides which languages "
            "may store extractions. One call per gold case, so it is the slow step on a "
            "slow machine."
        ),
    )
    deep: bool = Field(
        default=False,
        description=(
            "also run the model bench: the frozen input set through the model task by "
            "task, on whichever backend is already serving. It starts, stops and "
            "switches nothing. Minutes become tens of minutes; the frozen inputs are "
            "built on first use and reused after, so runs stay comparable."
        ),
    )
    refresh_batch: bool = Field(
        default=False,
        description=(
            "re-sample the frozen bench inputs from the corpus. Changes the questions, so "
            "the run is NOT comparable with earlier ones and starts the bench from scratch."
        ),
    )


def _ai_check_worker(ctx, **kwargs) -> dict:
    from src.monitoring.ai_check import run_and_persist_ai_check

    return run_and_persist_ai_check(ctx, **kwargs)


_AI_CHECK_JOB = register_job(
    BackgroundJob(
        "ai-check", "AI checks (backend, latency, throughput, extraction gate, self-tests)",
        _ai_check_worker, is_writer=False, cancellable=True,
    )
)


@router.post("/ai-check/run")
def ai_check_run(body: AiCheckRunBody) -> JSONResponse:
    """Run every AI check this machine can do, in one background pass.

    A job rather than a synchronous call because the throughput sweep and the live eval
    take minutes on a slow machine, and a request that long would hold the one worker.
    Cancellable between steps; each step is timed and guarded, so a step that fails
    records why and the run continues rather than losing the ones that worked.

    Loopback inference only: no egress, airplane-safe, and it writes nothing to the
    corpus.

    ``deep`` adds the COMPARATIVE bench: every roster model, on every backend that
    serves it, over frozen inputs this endpoint builds on first use and reuses after
    (rebuilding per run would make each run incomparable with the last). It restarts
    vLLM between models and hands the GPU back and forth with Ollama, so it is measured
    in hours where the rest is measured in minutes — which is why it is a choice on one
    button rather than a second button. Whatever the run does NOT cover is listed in the
    report's ``not_run_here``, computed from what actually ran.
    """
    levels = tuple(
        int(x) for x in (body.levels or "").split(",") if x.strip().isdigit() and int(x) > 0
    )
    try:
        st = _AI_CHECK_JOB.start(
            repeats=body.repeats,
            levels=levels or None,
            calls_per_level=body.calls_per_level,
            include_perception=body.include_perception,
            deep=body.deep,
            refresh_batch=body.refresh_batch,
        )
    except RuntimeError as exc:
        st = _AI_CHECK_JOB.status()
        st["already_running"] = True
        st["detail"] = str(exc)
    return JSONResponse(st)


@router.get("/ai-check/status")
def ai_check_status() -> JSONResponse:
    """Live status of the AI-check run (state, which step, and the report when done)."""
    return JSONResponse(_AI_CHECK_JOB.status())


@router.post("/ai-check/cancel")
def ai_check_cancel() -> JSONResponse:
    """Stop the run at its next step boundary. The steps already measured are kept."""
    _AI_CHECK_JOB.cancel()
    return JSONResponse(_AI_CHECK_JOB.status())


@router.get("/ai-check/last")
def ai_check_last() -> JSONResponse:
    """The newest saved AI-check report (read-only; never starts a run). Honest
    ``{available:false}`` when none has been run on this machine."""
    from src.monitoring.ai_check import last_ai_check_report

    return JSONResponse(last_ai_check_report())


@router.get("/ai-check/download")
def ai_check_download() -> Response:
    """The newest AI-check report as one downloadable .json — the file to attach to a
    bug report. 404 until a run has produced one."""
    from src.monitoring.ai_check import last_ai_check_report

    out = last_ai_check_report()
    if not out.get("available"):
        raise HTTPException(
            status_code=404,
            detail=out.get("reason")
            or "no AI check has been run — start one with POST /api/diagnostics/ai-check/run",
        )
    fname = out.get("filename") or "oo-ai-check.json"
    return JSONResponse(out, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# Language -> script, for sizing the context window in CHARACTERS. Only the
# scripts src.ai_layer.context knows a chars-per-word estimate for appear here; a
# language absent from this map falls back to "latin", which is the conservative
# direction (it over-estimates characters per word, so the window is sized a little
# large rather than a little short).
_SCRIPT_OF_LANG = {
    "ru": "cyrillic", "uk": "cyrillic", "bg": "cyrillic", "sr": "cyrillic", "mk": "cyrillic",
    "el": "greek", "ar": "arabic", "fa": "arabic", "ur": "arabic", "he": "hebrew",
    "hi": "devanagari", "mr": "devanagari", "ne": "devanagari", "bn": "bengali",
    "th": "thai", "zh": "cjk", "ja": "cjk", "ko": "cjk",
}


@router.get("/ai")
def ai_diagnostics(
    measure_corpus: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """B7.1 (2026-07-24 Session B): a secret-safe, read-only snapshot of the whole
    dual-backend AI stack -- which backend is active and why (hardware detection
    facts), the active model, context/concurrency settings, and the last saved
    summary of every AI-layer background job. Never runs anything; rides the
    all-diagnostics bundle by default.

    ``measure_corpus`` (E-S4, 2026-08-01) additionally measures the article-length
    distribution so the Ollama context auto-tune can size the window to the corpus
    that actually exists. OFF by default and deliberately so: that measurement is a
    full-table pass, and a bundle member that quietly ran one would make reading the
    AI settings the most expensive click in diagnostics. Without it the auto-tune
    reports UNMEASURED and names this flag, rather than proposing a number from
    nothing."""
    from src.monitoring.ai_diagnostics import ai_diagnostics_report

    corpus = None
    if measure_corpus:
        from src.analytics.article_length import article_length_report

        report = article_length_report(db)
        by_lang = report.get("word_count_by_language") or {}
        # The dominant language's own p95, not the corpus-wide one: the window is
        # spent on characters, and a corpus-wide word figure mixes scripts whose
        # characters-per-word differ by more than the figure itself.
        top = max(by_lang.items(), key=lambda kv: (kv[1] or {}).get("n") or 0, default=None)
        if top and not (top[1] or {}).get("unsegmented"):
            corpus = {"p95_words": (top[1] or {}).get("p95"), "script": _SCRIPT_OF_LANG.get(top[0], "latin")}
    return JSONResponse(ai_diagnostics_report(corpus))


# ---------------------------------------------------------------------------
#  Qualification ASSIST -- propose-only LLM nav-soup/extraction-junk flagging
#  (B7.2, 2026-07-24 Session B, ruled "propose-only"). A bounded, SYNCHRONOUS
#  per-source run (mirrors /ir-eval's "bounded read-only eval" posture, not a
#  background job -- scoped to one source's small trial-fetch article set).
#  NEVER touches Source.status/Source.tags; composes with the qualification
#  lifecycle + the prose gate as an additional, human-reviewed signal.
# ---------------------------------------------------------------------------


class QualificationAssistBody(BaseModel):
    source_id: int = Field(..., description="the Source row to check")
    model: str | None = Field(default=None, description="defaults to the active model")
    max_articles: int = Field(default=20, ge=1, le=200)


@router.post("/qualification-assist/run")
def qualification_assist_run(body: QualificationAssistBody, db: Session = Depends(get_db)) -> JSONResponse:
    """Classify up to ``max_articles`` of ``source_id``'s STORED articles as
    genuine-article/nav-soup via the active model, and persist the dated
    PROPOSALS artifact -- a signal for the maintainer/Claude-verification loop
    to review BESIDE the auditor's own evidence, never applied automatically
    (``Source.status``/``Source.tags`` are never touched). 404 if the source
    does not exist."""
    from src.database.models import Source

    if db.get(Source, body.source_id) is None:
        raise HTTPException(status_code=404, detail=f"no source with id {body.source_id}")
    from src.ai_layer.qualification_assist import run_and_persist_qualification_assist

    out = run_and_persist_qualification_assist(
        db, body.source_id, model=body.model, max_articles=body.max_articles
    )
    return JSONResponse(out)


@router.get("/qualification-assist/last")
def qualification_assist_last(source_id: int | None = Query(None)) -> JSONResponse:
    """The newest saved qualification-assist proposals artifact -- optionally
    filtered to ONE ``source_id``. Read-only; never runs anything. Honest
    ``{available: false}`` when none exists (for that source, or at all)."""
    from src.ai_layer.qualification_assist import last_qualification_assist_report

    return JSONResponse(last_qualification_assist_report(source_id=source_id))


@router.get("/qualification-assist-selftest")
def qualification_assist_selftest(download: bool = Query(False)) -> JSONResponse:
    """Run the qualification-assist self-test -- the measure-before-trust GATE
    before any real run, mirroring ``/keyword-triage-selftest``/``/source-tags-
    selftest`` exactly. Proves the constrained one-word parser, canaries, and
    the classify-and-tally mechanism on a deterministic STUB -- no model, no
    network, no score. ``download=1`` returns a dated attachment."""
    from src.ai_layer.qualification_assist import run_qualification_assist_selftest

    log = run_qualification_assist_selftest()
    headers = {}
    if download:
        fname = f"oo-qualification-assist-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


# --------------------------------------------------------------------------- #
#  THE BACKGROUND-AI COORDINATOR (2026-08-01 field impressions, rulings 12-13)
#
#  One master switch instead of three independent sweep toggles that would
#  silently queue behind each other on a backend that serves one generation at a
#  time. The lane runs the ENABLED sweeps round-robin, each resuming from its own
#  persisted cursor, and stands down while a user-initiated batch holds the model.
# --------------------------------------------------------------------------- #
def _ai_coordinator_worker(ctx, **kwargs) -> dict:
    from src.ai_layer.coordinator import run_coordinator

    return run_coordinator(ctx, **kwargs)


_AI_COORDINATOR_JOB = register_job(
    BackgroundJob(
        "ai-coordinator", "Background AI (coordinated sweeps)", _ai_coordinator_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/ai-coordinator/run")
def ai_coordinator_run() -> JSONResponse:
    """Start the coordinated background-AI lane (the master toggle's ON action).

    Runs every sweep the operator has ENABLED in Settings, round-robin, one bounded
    batch each per turn, through whichever backend ``resolve_backend`` selects. Each
    sweep keeps its OWN persisted cursor, so this never re-does finished work and a
    cancel loses nothing. Loopback inference is airplane-safe, so this runs offline.

    Refuses (409) when no sweep is enabled -- an empty lane that reported "running"
    would be a fabricated capability. Re-calling while it runs returns the live
    status with ``started:false`` rather than erroring.

    STARTS THE BACKEND FIRST (2026-08-04 field report: "Starting the local AI
    produces 'local model hiccup'"). Nothing in this chain ever started a backend:
    the lane came up, probed, found no server, and spent its whole retry budget on a
    condition retrying cannot change. Now it asks ``activation`` to bring one up.

    The refusal is deliberately narrow, because the recorded lesson is that a health
    probe must NOT decide a retry -- a model reload, a restart and a busy server all
    answer alike, so ending a sweep on a probe would destroy the transient-retry
    guarantee. That lesson is about ENDING a run. Here we are STARTING one, and the
    two conditions are different in kind:

      * a STRUCTURAL blocker (no backend installed; weights not downloaded) is a
        filesystem fact, it will not change while the lane retries, and it is
        actionable -- so 409 with the reason, in words;
      * a backend that is starting (vLLM loading its engine for tens of seconds)
        gets the lane started anyway, which is exactly what the backoff is for.
    """
    from src.ai_layer.coordinator import enabled_members
    from src.api.llm import active_model
    from src.llm.activation import ensure_running

    members = enabled_members()
    if not members:
        raise HTTPException(
            status_code=409,
            detail="No background sweeps are enabled — switch at least one on in Settings → AI.",
        )
    act = ensure_running()
    if not (act.get("ready") or act.get("started")):
        detail = str(
            act.get("detail")
            or "No local AI backend could be started, so there is nothing to sweep with."
        )
        # The server's OWN first words, inline, when a vLLM start died on launch. A path
        # to a log file is an instruction to go and find the answer; the answer itself
        # is what turns "vLLM doesn't seem to start" into a fixable fact. Kept a STRING
        # rather than a structured field because this is a `detail=` a button renders,
        # and the frontend's error helper renders a dict as "[object Object]".
        head = str(act.get("server_log_head") or "").strip()
        if head:
            detail = f"{detail}\n\n--- the server's own first output ---\n{head}"
        raise HTTPException(status_code=409, detail=detail)

    # A backend that is UP with NOTHING TO SERVE fails every batch, and it is a likely
    # state right after a fresh install: the model store moved into the app's own
    # folder (2026-08-04 ask), so a reinstall can leave a perfectly healthy daemon
    # pointed at an empty directory. ``outage_reason()`` has nothing to say about it --
    # the backend IS reachable -- which is exactly how this reached the operator as
    # "local model hiccup", ten times over.
    #
    # Only when the probe SUCCEEDS and comes back empty. A probe that raises is not a
    # "no": refusing on an unreadable answer would be its own fabrication, and the
    # retry budget is the right instrument for a momentarily unhappy server.
    if act.get("ready"):
        try:
            from src.llm.backend import get_client

            installed = list(get_client().list_installed() or [])
        except Exception:  # noqa: BLE001 - an unreadable probe never refuses
            installed = None
        if installed is not None and not installed:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{act.get('backend')} is running but no model is downloaded yet, so "
                    "there is nothing to sweep with. Download one in Settings → AI "
                    "(retrying cannot make a model appear)."
                ),
            )
    try:
        # The backend `ensure_running` ACTUALLY brought up -- not a second, independent
        # resolution. Those two can differ (a fallback, or vLLM dying between the calls),
        # and when they do the sweep is handed the other backend's identifier: the field
        # saw an HF repo id sent to Ollama, which then correctly said it had no such
        # model while the right one was installed all along.
        st = _AI_COORDINATOR_JOB.start(model=active_model(act.get("backend")))
        st["started"] = True
    except RuntimeError:
        st = _AI_COORDINATOR_JOB.status()
        st["started"] = False
    st["members"] = [m.key for m in members]
    # What it took to get a backend serving, so the UI can say "starting vLLM on
    # <model> — the engine takes a moment" instead of a bare spinner. `ready:false`
    # here is the honest still-loading case, not a failure.
    st["activation"] = {
        "backend": act.get("backend"),
        "started": bool(act.get("started")),
        "ready": bool(act.get("ready")),
        "detail": act.get("detail"),
        # Present only when the preferred backend failed and another one took over --
        # so a GPU machine quietly serving from Ollama can still say why.
        "fell_back_from": act.get("fell_back_from"),
    }
    return JSONResponse(st)


@router.get("/ai-coordinator/status")
def ai_coordinator_status() -> JSONResponse:
    """Live status of the coordinated lane: state, turns taken, which sweeps are
    included, whether a user batch is currently holding the model, and what the
    hardware verdict says the master toggle's default should be. Counts only."""
    from src.ai_layer.coordinator import (
        coordinator_default_enabled,
        enabled_members,
        user_batch_active,
    )

    st = _AI_COORDINATOR_JOB.status()
    st["members"] = [{"key": m.key, "label": m.label} for m in enabled_members()]
    st["user_batch"] = user_batch_active()
    st["hardware_default"] = coordinator_default_enabled()
    return JSONResponse(st)


@router.post("/ai-coordinator/cancel")
def ai_coordinator_cancel() -> JSONResponse:
    """Stop the lane at its next safe point. Every sweep's cursor persists, so
    switching back on resumes rather than restarting."""
    _AI_COORDINATOR_JOB.cancel()
    return JSONResponse(_AI_COORDINATOR_JOB.status())


# --------------------------------------------------------------------------- #
#  E-S2 (2026-08-01 rulings 14-16): the COMPARATIVE model bench.
#
#  The maintainer's question -- "does the ruled default model deserve to stay the
#  default, and how do the small candidates compare?" -- is answered by a
#  measurement, not an opinion. These endpoints build the FROZEN inputs once, take
#  the ~50-keyword grading sitting once, and then run every roster model on every
#  backend that serves it over exactly those inputs. Nothing here changes the
#  active model: the bench MEASURES, the decision is the maintainer's, made on the
#  verified logs (ai-proposed -> claude-verified -> maintainer-merged).
# --------------------------------------------------------------------------- #
class ModelBenchBatchBody(BaseModel):
    target_size: int = Field(
        default=450, ge=20, le=2000,
        description="how many keywords the frozen batch carries (~400-500 is the ruled size)",
    )
    source_sample: int = Field(
        default=20, ge=1, le=200,
        description="how many sources carry the tag-assignment evidence",
    )
    scan_limit: int = Field(
        default=20000, ge=100, le=200000,
        description="how deep into the article-spread order the sample is drawn from",
    )


class ModelBenchAnchorsBody(BaseModel):
    anchors: list[dict] = Field(
        description=(
            "the grading sitting: [{term, verdict: junk|content|unsure, kind?: "
            "person|org|place|other}]. An unknown verdict/kind is REFUSED, not "
            "snapped to a near value; a term graded twice is refused rather than "
            "letting one grade silently win."
        )
    )


class ModelBenchRunBody(BaseModel):
    """What a bench run may be asked for, now that there is one model to ask about.

    The roster fields this body used to carry (``models``, ``extra_models``,
    ``backends``, ``allow_backend_switch``) went with the 2026-08-12 one-model ruling.
    They existed to choose between models and to hand the GPU around between them; the
    choice has been made, and the maintainer took the handing-around back in the same
    message. What is left is the protocol: measure THE model on whichever backend the
    operator has running, once per backend, and compare the two reports.
    """

    repeats: int = Field(default=2, ge=1, le=10, description="timed calls per latency shape")
    restart: bool = Field(
        default=False, description="ignore the saved cursor and re-measure from the start"
    )


def _model_bench_worker(ctx, **kwargs) -> dict:
    """Measure the DEFAULT model on whichever backend the operator has running.

    RULED 2026-08-12 (maintainer): *"The app has failed to manage both ollama and vllm,
    so I'll do the managing myself."* So this starts nothing, stops nothing and hands
    no model over; it measures the machine as the operator arranged it and refuses
    honestly when nothing is up.
    """
    from src.ai_layer.model_bench import run_default_model_bench

    return run_default_model_bench(ctx, **kwargs)


_MODEL_BENCH_JOB = register_job(
    BackgroundJob(
        "model-bench", "Comparative model bench (every roster model, same frozen inputs)",
        _model_bench_worker, is_writer=False, cancellable=True,
    )
)


@router.post("/model-bench/batch")
def model_bench_build_batch(
    body: ModelBenchBatchBody, db: Session = Depends(get_db)
) -> JSONResponse:
    """Build and freeze the bench inputs: a stratified keyword sample (equal
    per-language quotas, head and tail apart), the source evidence, and the corpus's
    own closed tag vocabulary. Read-only on the corpus.

    Building a fresh batch per model would make the numbers LOOK comparable while
    measuring different work, so this is done once and every run reads it back --
    each bench report carries the batch's digest, and a resume whose digest moved is
    refused rather than blending two input sets."""
    from src.ai_layer.bench_batch import collect_frozen_inputs, save_frozen_batch

    payload = collect_frozen_inputs(
        db,
        scan_limit=body.scan_limit,
        source_sample=body.source_sample,
        target_size=body.target_size,
    )
    path = save_frozen_batch(payload)
    out = {k: v for k, v in payload.items() if k not in ("keywords", "sources")}
    out["path"] = str(path)
    return JSONResponse(out)


@router.get("/model-bench/batch")
def model_bench_batch() -> JSONResponse:
    """The frozen batch's summary (strata, digest, sizes) without its rows. Honest
    ``{available:false}`` with the reason when none has been built."""
    from src.ai_layer.bench_batch import BenchArtifactError, load_frozen_batch

    try:
        payload = load_frozen_batch()
    except BenchArtifactError as exc:
        return JSONResponse({"available": False, "reason": str(exc)})
    out = {k: v for k, v in payload.items() if k not in ("keywords", "sources")}
    out["available"] = True
    return JSONResponse(out)


@router.get("/model-bench/anchors")
def model_bench_anchors(sample: int = Query(0, ge=0, le=500)) -> JSONResponse:
    """The graded anchors, or -- with ``sample=N`` -- N terms drawn FROM the frozen
    batch to put in front of the maintainer for grading.

    The anchors are what turn "the models agree" into "the models are right", and
    they are drawn from the batch precisely so every graded term is one the models
    are actually asked about."""
    from src.ai_layer.bench_batch import BenchArtifactError, anchor_candidates, load_anchors

    if sample:
        from src.ai_layer.bench_batch import load_frozen_batch

        try:
            batch = load_frozen_batch()
        except BenchArtifactError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse({"candidates": anchor_candidates(batch, sample)})
    existing = load_anchors()
    if not existing:
        return JSONResponse(
            {
                "available": False,
                "note": (
                    "no anchors have been graded yet -- anchor accuracy will report as "
                    "UNMEASURED, which is what it is. Ask for ?sample=50 to start a sitting."
                ),
            }
        )
    existing["available"] = True
    return JSONResponse(existing)


@router.post("/model-bench/anchors")
def model_bench_save_anchors(body: ModelBenchAnchorsBody) -> JSONResponse:
    """Persist a grading sitting. Graded ONCE, reused across every model and every
    future run. 400 (loudly) on a malformed grade rather than repairing it."""
    from src.ai_layer.bench_batch import BenchArtifactError, build_anchors, save_anchors

    try:
        payload = build_anchors(body.anchors)
    except BenchArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["path"] = str(save_anchors(payload))
    return JSONResponse(payload)


@router.post("/model-bench/run")
def model_bench_run(body: ModelBenchRunBody) -> JSONResponse:
    """Start (or resume) the model bench as a cancellable background job.

    Measures the DEFAULT model on whichever backend is already serving, and manages
    nothing. Resumable: a cancelled or crashed run keeps what it finished. It never
    changes the active model and never downloads weights. 409 while the frozen batch is
    missing -- the tasks have nothing to ask about without it."""
    from src.ai_layer.bench_batch import BenchArtifactError, load_frozen_batch

    try:
        load_frozen_batch()
    except BenchArtifactError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        st = _MODEL_BENCH_JOB.start(
            repeats=body.repeats,
            restart=body.restart,
        )
        st["started"] = True
    except RuntimeError:
        st = _MODEL_BENCH_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/model-bench/status")
def model_bench_status() -> JSONResponse:
    """Progress: which (model, backend) pair is being measured, and on which task."""
    return JSONResponse(_MODEL_BENCH_JOB.status())


@router.post("/model-bench/cancel")
def model_bench_cancel() -> JSONResponse:
    """Stop at the next safe point. Finished pairs are kept; the next run resumes."""
    _MODEL_BENCH_JOB.cancel()
    return JSONResponse(_MODEL_BENCH_JOB.status())


@router.get("/model-bench/last")
def model_bench_last(full: bool = Query(False)) -> JSONResponse:
    """The newest saved bench artifact, SUMMARISED by default (every metric, without
    the hundreds of per-term answers per pair). ``full=1`` returns the raw artifact --
    the per-term answers are what a verification session re-judges."""
    from src.ai_layer.model_bench import last_model_bench_report

    return JSONResponse(last_model_bench_report(summary=not full))


@router.get("/model-bench/download")
def model_bench_download() -> Response:
    """Serve the newest bench artifact whole -- the ONE log the maintainer uploads
    for the verification chain. 404 until a run has produced one."""
    from src.ai_layer.bench_batch import bench_dir

    files = sorted(bench_dir().glob("oo-model-bench-*.json"))
    if not files:
        raise HTTPException(
            status_code=404,
            detail="no model-bench artifact yet -- start one with "
            "POST /api/diagnostics/model-bench/run",
        )
    return FileResponse(files[-1], media_type="application/json", filename=files[-1].name)


@router.get("/model-bench/gates")
def model_bench_gates(model: str | None = Query(None)) -> JSONResponse:
    """The per-language task gates the newest bench artifact supports (read-only).

    Two shapes, and the difference is the point rather than an implementation
    detail. Triage and source tags know an item's language BEFORE the call, so their
    gates LICENSE: an unmeasured language refuses, because running there would be
    unmeasured work. Language detection does not know the language before the call --
    that is the question -- so its gate is a VETO on the ANSWER: only a label the
    bench measured this model getting wrong more often than right is refused, and a
    label the gold set never covered is stored exactly as it always was. Refusing
    those would disable detection for languages nobody tested rather than for
    languages that failed.

    WIRED TODAY: the langdetect veto (it STORES a label, so a measured-wrong answer
    has to be stopped). The triage and source-tag gates are computed and shown but
    not yet applied at selection -- both sweeps are EXPORT-ONLY JSONL reviewed by the
    verification chain, so an unreliable verdict there is already caught by a human
    before it becomes an artifact.
    """
    from src.ai_layer.task_gates import (
        GATED_TASKS,
        MIN_ANSWER_PRECISION,
        MIN_FORMAT_VALIDITY,
        MIN_OBSERVATIONS,
        current_task_gate,
    )

    return JSONResponse(
        {
            "gates": {task: current_task_gate(task, model=model) for task in GATED_TASKS},
            "wired": ["langdetect"],
            "floors": {
                "min_format_validity": MIN_FORMAT_VALIDITY,
                "min_answer_precision": MIN_ANSWER_PRECISION,
                "min_observations": MIN_OBSERVATIONS,
            },
            "method": (
                "Read from the newest comparative-bench artifact. Triage/source-tag gates "
                "license (unmeasured refuses); the langdetect gate vetoes (only a measured "
                "failure refuses). Tri-state throughout: cleared / failed / unmeasured, "
                "never collapsed into each other."
            ),
            "caveat": (
                "The floors are JUDGEMENTS, written in src/ai_layer/task_gates.py so the "
                "first real bench run can revise them on evidence. They are deliberately "
                "low: the gold sets are small, and a stricter floor would be a number "
                "nobody measured. Empty gates mean no bench has run — not that everything "
                "passed."
            ),
        }
    )
