"""
The keyword log/export endpoints and their bounded-export helpers.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 61-1084 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics.families import build_families
from src.database.maintenance import StatementTimeout, statement_deadline
from src.database.models import Article, KeywordSuperGroup, Source
from src.database.read_snapshot import read_only_db
from src.utils.export_envelope import envelope

from ._base import _MAX_KEYWORDS_PER_LANG, router

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


def _quantiles(values: list[int]) -> dict:
    """Min / p25 / median / p75 / p95 / max over an ALREADY-SORTED list, plus n and sum.

    Nearest-rank, no interpolation: these are counts of real things, and an interpolated
    "2.5 mentions" would be a number no keyword has. Empty input reports nulls with n=0
    rather than zeros -- "no families" and "families that all scored 0" are different
    facts (the same rule finding C5 is about).
    """
    n = len(values)
    if not n:
        return {"n": 0, "sum": 0, "min": None, "p25": None,
                "median": None, "p75": None, "p95": None, "max": None}

    def at(frac: float) -> int:
        return values[min(n - 1, max(0, int(round(frac * (n - 1)))))]

    return {
        "n": n,
        "sum": sum(values),
        "min": values[0],
        "p25": at(0.25),
        "median": at(0.50),
        "p75": at(0.75),
        "p95": at(0.95),
        "max": values[-1],
    }


def _families_summary(families: list[dict]) -> dict:
    """Facts about EVERY family, so capping the printed list costs no aggregate answer.

    The maintainer's objection to the 2026-09-11 families cap was that capping biases
    future diagnostics, and it was correct: a global top-N by mentions is the same
    mentions-ranked cut this file already records as having "structurally anglicised the
    export", and it hides `conflated_by` (a possible bad merge) preferentially, because a
    wrong merge is likelier among rare terms than famous ones.

    This is the answer to that: the printed list shrinks, the RECORD does not. Everything
    here is computed over the full list before any cap is applied, so "how long is the
    tail", "what is the mention distribution", "how many families are of kind X" and
    "which families did the lemma merge join" all stay answerable from the digest alone.
    """
    mentions = sorted(int(f.get("mentions") or 0) for f in families)
    variants = sorted(int(f.get("variants") or 0) for f in families)
    by_kind: dict[str, int] = {}
    conflated: list[dict] = []
    manual = 0
    for f in families:
        by_kind[str(f.get("kind") or "unknown")] = by_kind.get(str(f.get("kind") or "unknown"), 0) + 1
        if f.get("manual"):
            manual += 1
        if f.get("conflated_by"):
            conflated.append(
                {
                    "term": f.get("term"),
                    "normalized": f.get("normalized"),
                    "kind": f.get("kind"),
                    "mentions": f.get("mentions"),
                    "variants": f.get("variants"),
                    "conflated_by": f.get("conflated_by"),
                }
            )
    # Rarest first: the whole point is that the tail is where a bad merge hides, so the
    # ordering must not re-create the popularity bias this block exists to remove.
    conflated.sort(key=lambda c: (int(c.get("mentions") or 0), str(c.get("normalized") or "")))
    return {
        "total_families": len(families),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0]))),
        "manual_overrides": manual,
        "mentions": _quantiles(mentions),
        "variants": _quantiles(variants),
        "single_member_families": sum(1 for v in variants if v <= 1),
        # SELECTED ON THE SIGNAL, NEVER ON RANK: a conflated family is a possible bad
        # merge, so every one is listed however rare it is. Ordered rarest-first for the
        # same reason.
        "conflated": {
            "count": len(conflated),
            "families": conflated,
            "method": (
                "Every family carrying conflated_by (the lemma merge joined it), listed "
                "in full and ordered rarest-first -- selected by the signal, never by "
                "mentions, because a wrong merge is likelier among rare terms."
            ),
        },
        "method": (
            "Computed over ALL families before the print cap is applied, so the capped "
            "`families` list costs no aggregate answer about the tail. Counts only; no "
            "scores."
        ),
    }


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
        # Field diagnostics 2026-09-11 (B2): the DIGEST embedded the families dump in
        # FULL, and that is where `keyword-log-digest.json` got its 73.2 MB -- 84x the
        # next-largest archive member, ~96% of the whole bundle, and +3.4 GB of RSS on a
        # 4,093.8 MB machine whose previous session had already ended unclean at peak
        # 4158 MB. The cap this needed was already written, one path over:
        # `_keyword_zip_families_cap` caps exactly this block for the ZIP path, and its
        # own docstring records that the full 700k-family tail "was also why the byte cap
        # never held" -- the same lesson, and the digest path had never been given it.
        #
        # Reused rather than re-invented: same helper, same env override, same
        # sorted-by-mentions order, same honest omission record. A cap without the record
        # beside it would be a silent truncation, which is the defect this batch is full
        # of elsewhere.
        #
        # SCOPED TO `digest` ON PURPOSE: the non-digest single-file export is a contract
        # ("byte-for-byte unchanged", asserted by its own test), so `families` itself is
        # never mutated here -- only what this branch emits.
        if digest:
            # THE TAIL IS SUMMARISED, NOT SELECTED AWAY (maintainer's bias objection,
            # 2026-09-11). The first version of this cap simply took the top N by
            # mentions -- and that is a GLOBAL mentions-ranked cut, which is precisely
            # the shape this same file records at line 54 as having "structurally
            # anglicised the export", and which `method` (a few lines below) warns
            # against in its own words: "a global cap would anglicise the export". The
            # per-language keyword quota exists to avoid exactly that, and a global
            # families cut on top of it hands the bias straight back.
            #
            # Worse, popularity is the wrong axis for the thing most worth finding here:
            # `conflated_by` marks a family the lemma merge joined, i.e. a POSSIBLE
            # MISTAKE, and a wrong merge is likelier among rare terms than famous ones.
            # Ranking by mentions hides defects preferentially.
            #
            # So the cap no longer decides WHICH FACTS SURVIVE, only which rows are
            # printed in full:
            #   * every family is counted in `families_summary`, computed over ALL of
            #     them -- totals, per-kind counts, and the mention/variant distributions
            #     -- so no AGGREGATE question about the tail becomes unanswerable;
            #   * every conflated family is listed, selected ON THE SIGNAL rather than on
            #     popularity, so the defect-bearing subset is never rank-filtered;
            #   * the popularity sample is still there for a human glance, and is now
            #     LABELLED as unrepresentative instead of being left to look complete.
            # The full per-family record remains one endpoint away, and that export is
            # per-language fair by construction.
            _fam_cap = _keyword_zip_families_cap()
            _fam_shown = (
                families[:_fam_cap] if _fam_cap and len(families) > _fam_cap else families
            )
            yield ', "families": ' + json.dumps(_fam_shown, separators=(",", ":"))
            yield ', "families_summary": ' + json.dumps(
                _families_summary(families), separators=(",", ":")
            )
            yield ', "families_provenance": ' + json.dumps(
                {
                    "shown": len(_fam_shown),
                    "total": len(families),
                    "omitted": len(families) - len(_fam_shown),
                    "sorted_by": "mentions (desc)",
                    "sample_is_representative": False,
                    "selection_bias": (
                        "This list is the top families BY MENTIONS, which is a global "
                        "mentions-ranked cut and therefore skews English and skews "
                        "popular. Do NOT reason about the tail from it. Every family is "
                        "still counted in families_summary, and every conflated family "
                        "is listed there in full regardless of rank."
                    ),
                    "note": (
                        "Only the top families are printed in full here (the complete "
                        "per-family dump is large and is redundant with the per-language "
                        "shards). Nothing is DROPPED: the tail is summarised in "
                        "families_summary. Set OO_KEYWORD_LOG_FAMILIES=0 to print all, "
                        "or use the full keyword export, which is per-language fair."
                    ),
                },
                separators=(",", ":"),
            )
        else:
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
