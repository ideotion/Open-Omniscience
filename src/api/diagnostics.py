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
from fastapi.responses import JSONResponse, StreamingResponse
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


def _in_batches(ids: list[int], size: int = 800):
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


# Digest mode keeps the same bounded aggregates but ships only the top-N
# most-mentioned keywords instead of the full per-keyword list, so the file is
# small enough to actually ingest in the maintainer->dev channel (field-test
# 2026-06-15 Item Z: a full log measured ~60 MB and was unusable in the very
# channel it exists for). The aggregates ARE the analysis; the long tail is not.
_DIGEST_SAMPLE = 100


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
) -> StreamingResponse:
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
                taken = per_lang_taken.get(dom, 0)
                if taken >= _MAX_KEYWORDS_PER_LANG:
                    capped_langs.add(dom)
                    continue
                per_lang_taken[dom] = taken + 1
                survivors.append((kid, int(m), int(a), first, last))
            for kid in sorted(set(stored_lang) - seen):  # zero-mention keywords
                dom = stored_lang.get(kid) or "?"
                taken = per_lang_taken.get(dom, 0)
                if taken >= _MAX_KEYWORDS_PER_LANG:
                    capped_langs.add(dom)
                    continue
                per_lang_taken[dom] = taken + 1
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

    kind_tag = "digest" if digest else "log"
    fname = f"oo-keyword-{kind_tag}-{datetime.now().strftime('%Y%m%d')}.json"
    return StreamingResponse(
        _stream(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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
        "errors": recent_errors(300),
        "method": (
            "Verbatim runtime facts, tracking states, network verdicts, per-click "
            "import outcomes and the rolling WARNING+ error log. Nothing inferred; "
            "exported only on the operator's click."
        ),
    }
    body = envelope(kind="debug-bundle", query={}, count=len(payload["errors"]), payload=payload)
    fname = f"oo-debug-bundle-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )
