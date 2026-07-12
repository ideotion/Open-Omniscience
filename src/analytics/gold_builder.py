"""
IR gold-set BUILDER (S5.3) — make the human-judged gold set trivial to produce.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The IR eval harness (``ir_eval.py``) already has the metrics, the ``load_gold_set`` format,
``evaluate_against_corpus`` and the BM25F ``bm25f_weight_ab`` A/B — but a graded gold set is
corpus-specific and can ONLY be made by the maintainer over their OWN articles (the
measure-before-trust gate for ``OO_FAMILY_LEMMA`` and the BM25F default). This module closes
that last gap: it (a) SAMPLES real queries from the corpus (top keywords — search history is
not stored, so nothing is invented), (b) fetches the live search results to grade, and
(c) writes the EXACT ``ir_eval`` gold-set JSON, VALIDATED by round-trip through
``load_gold_set`` so a malformed set can never be saved. No score, counts only.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections import Counter
from typing import Any

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(term: str) -> str:
    s = _SLUG.sub("_", (term or "").lower()).strip("_")
    return s[:40] or "q"


def sample_queries(session, *, n_queries: int = 15, per_query: int = 10) -> dict:
    """Sample grading candidates: the top corpus keywords + their live search results.

    Never invents a query — the candidates ARE the corpus's most-mentioned keywords (search
    history is not stored). Each candidate carries up to ``per_query`` live results
    (article id + title + source + language, in search rank order) for the maintainer to
    grade 0/1/2. Read-only, counts only.
    """
    from src.analytics.queries import top_terms
    from src.database.fts import search_ids
    from src.database.models import Article, Source

    top = top_terms(session, limit=max(1, n_queries))
    out: list[dict] = []
    used_ids: set[str] = set()
    for row in (top.get("terms") or [])[: max(1, n_queries)]:
        term = (row.get("term") or "").strip()
        if not term:
            continue
        qid = _slug(term)
        base, k = qid, 2
        while qid in used_ids:  # keep ids unique even when two terms slug alike
            qid = f"{base}_{k}"
            k += 1
        used_ids.add(qid)
        ids = search_ids(session, term, limit=per_query) or []
        results: list[dict] = []
        if ids:
            rank = {aid: i for i, aid in enumerate(ids)}
            rows = (
                session.query(Article.id, Article.title, Article.language, Source.name)
                .join(Source, Source.id == Article.source_id, isouter=True)
                .filter(Article.id.in_(ids[:per_query]))
                .all()
            )
            rows.sort(key=lambda r: rank.get(r[0], 1 << 30))
            results = [
                {"article_id": r[0], "title": r[1], "language": r[2], "source": r[3]}
                for r in rows
            ]
        lang = (row.get("language") or "en")
        out.append(
            {
                "id": f"q_{qid}",
                "query": term,
                "language": lang if lang and lang != "?" else "en",
                "axis": "topic",
                "results": results,
            }
        )
    return {
        "queries": out,
        "note": (
            "Queries sampled from your top corpus keywords — search history is not stored, "
            "so nothing is invented. Grade each result 0/1/2, then Save to a server-side "
            "path; the file is the exact ir_eval gold-set format."
        ),
        "grading": "0 = irrelevant · 1 = relevant · 2 = highly relevant",
    }


def coverage(gold: list) -> dict:
    """Coverage meter over ``[GoldQuery]``: queries graded per language / axis, n stated.

    A 'graded' query is one with >=1 judgement (a query with no grades yet contributes
    nothing to evaluation and is counted separately, honestly)."""
    by_lang: Counter = Counter()
    by_axis: Counter = Counter()
    graded_q = 0
    total = 0
    for g in gold:
        n = len(g.relevances)
        total += n
        if n:
            graded_q += 1
            by_lang[g.language] += 1
            by_axis[g.axis] += 1
    return {
        "queries": len(gold),
        "graded_queries": graded_q,
        "total_judgements": total,
        "by_language": dict(by_lang),
        "by_axis": dict(by_axis),
        "note": (
            "A graded query has >=1 judgement. Pool judged docs and keep a single assessor "
            "consistent (Voorhees). Per-language / per-axis n is what the harness reports "
            "against — never one pooled average alone."
        ),
    }


def build_and_save_gold_set(path: str, queries: list[dict]) -> dict:
    """Build the EXACT ir_eval gold-set JSON from graded queries and write it, VALIDATED.

    Writes ``{"queries": [{id, query, language, axis, relevances}]}`` to the server-side
    ``path`` then round-trips it through ``load_gold_set`` — so a structurally invalid set
    (a bad grade, a duplicate id, an empty id/query) raises LOUDLY and the file that lands is
    always loadable. Returns ``{saved, coverage}``. Never a score.
    """
    from src.analytics.ir_eval import load_gold_set

    payload: dict[str, Any] = {"queries": []}
    for q in queries or []:
        rel: dict[str, int] = {}
        for doc, grade in (q.get("relevances") or {}).items():
            try:
                # keep the value as-is; load_gold_set is the SINGLE validator and raises
                # LOUDLY on a grade outside {0,1,2} (never silently drop a bad judgement).
                rel[str(doc)] = int(grade)
            except (TypeError, ValueError):
                continue  # a non-numeric grade is not a judgement — skip it
        payload["queries"].append(
            {
                "id": str(q.get("id") or "").strip(),
                "query": str(q.get("query") or "").strip(),
                "language": str(q.get("language") or "en"),
                "axis": str(q.get("axis") or "topic"),
                "relevances": rel,
            }
        )
    if not payload["queries"]:
        raise ValueError("no queries to save")

    p = pathlib.Path(path).expanduser()
    if not p.parent.is_dir():
        raise ValueError(f"directory does not exist: {p.parent}")
    # Validate a TEMP copy BEFORE replacing the target: load_gold_set raises GoldSetError on
    # any structural problem (a bad grade, a duplicate id, an empty id/query), so an invalid
    # gold set never lands at the destination — the target only ever holds a loadable file.
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        loaded = load_gold_set(tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    import os

    os.replace(tmp, p)  # atomic swap
    return {"saved": str(p), "coverage": coverage(loaded)}
