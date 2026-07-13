"""
Conjunction Lens — deep keyword analytics over N keywords (planning §1).

Single-SEED analytics (associations / trend / corpus_keywords) are mature, and the set-algebra
SUBSTRATE already exists but is PRIVATE to ``layered_graph``: ``queries._article_set`` (the
DISTINCT article-id union over N terms) and ``queries._overlap_edges`` (pairwise intersection
cardinality). There is no public N-keyword surface. This module promotes that substrate to a
public, tested, honest set-algebra core and adds the derived lenses §1 asks for:

  * ``corpus_algebra`` — intersection / union / difference over N keywords → the combined
    article-id set (which seeds the whole existing analysis surface via ``_resolve_corpus`` /
    ``openAnalysisForIds`` for free). The set expression IS the transparent corpus label.
  * ``per_article_intensity`` — a GROUP BY (article) over the conjunction: which articles pack
    the most of the N terms (counts only).
  * ``conditional_trend`` — the conjunction set's discussion volume over time (mention dates
    within the set), reusing the ``trend`` bucketer.
  * ``vocabulary_contrast`` — PURE: the per-term article-spread DELTA between two corpora, each
    side's n shown (a count difference, never a verdict).
  * ``near_match_expression`` — PURE: the FTS5 ``NEAR(...)`` MATCH string emission (the pure half
    of §1's NEAR support; executing it against a real FTS index is operator-gated).

Honesty by construction: co-occurrence in your corpus, never causation; contrast/silence are
count differences with n, never verdicts; NO composite score. The N-keyword picker UI and
wiring the result into the analysis window are BROWSER-GATED; perf at 974k-keyword / 5 TB scale
is OPERATOR-GATED.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func

from src.analytics.queries import (
    Keyword,
    KeywordMention,
    _bucket_key,
    _normalize,
)
from src.database.fts import _HAS_WORD_CHAR, _quote

ALGEBRA_OPS = ("intersection", "union", "difference")


def _dedup_normalized(terms: list[str]) -> list[tuple[str, str]]:
    """(raw, normalized) pairs, first-wins on a normalized collision, empties dropped."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for t in terms:
        n = _normalize(t)
        if n and n not in seen:
            seen.add(n)
            out.append((t, n))
    return out


def corpus_algebra(
    session, terms: list[str], *, op: str = "intersection", cap: int = 4000
) -> dict:
    """Set algebra over N keywords → the combined article-id set.

    ``intersection`` = articles mentioning ALL terms; ``union`` = ANY; ``difference`` = the FIRST
    term minus the union of the rest. The result ``article_ids`` seeds the analysis window via
    ``_resolve_corpus`` for free.

    CORRECTNESS: all three ops are computed from ONE consistent scan of per-article matched-term
    sets over the candidate union (rows grouped by article_id, so every article kept carries its
    COMPLETE matched set). Independently capping each term's set — the naive approach — would let a
    truncated intersection DROP a true member or a truncated difference INCLUDE a false one; this
    scan can never do either. When the scan hits ``cap`` DISTINCT articles it stops and flags
    ``bounded``/``result_bounded``: the result is then a true SUBSET of the answer (it may miss
    members — a bounded intersection can even look empty when the true one is not), NEVER a set
    with a fabricated member. Per-term ``n`` is the EXACT uncapped corpus-wide article count.

    Raises ``ValueError`` on an unknown op (fail loud). Counts only — no score."""
    if op not in ALGEBRA_OPS:
        raise ValueError(f"unknown op {op!r}; expected one of {ALGEBRA_OPS}")
    pairs = _dedup_normalized(terms)
    if not pairs:
        return {
            "op": op,
            "terms": [],
            "article_ids": [],
            "n_combined": 0,
            "n_terms": 0,
            "bounded": False,
            "result_bounded": False,
            "method": "No resolvable keyword given.",
            "caveat": "Counts only, never a score.",
        }
    normalized = [n for _raw, n in pairs]
    first = normalized[0]

    # One consistent scan: (article_id, matched normalized_term) pairs over the candidate union,
    # ordered by article_id so all rows for one article are contiguous. Accumulate the COMPLETE
    # matched-term set per article; stop at `cap` distinct articles (bounded). Because we break
    # only at a NEW-article boundary, every article kept has its full matched set — never partial.
    per_article: dict[int, set[str]] = {}
    bounded = False
    rows = (
        session.query(KeywordMention.article_id, Keyword.normalized_term)
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
        .filter(Keyword.normalized_term.in_(normalized))
        .distinct()
        .order_by(KeywordMention.article_id)
        .all()
    )
    for aid, term in rows:
        if aid not in per_article:
            if len(per_article) >= cap:
                bounded = True
                break
            per_article[aid] = set()
        per_article[aid].add(term)

    nterms = len(normalized)
    if op == "union":
        combined = set(per_article)
    elif op == "intersection":
        combined = {a for a, ts in per_article.items() if len(ts) == nterms}
    else:  # difference: matched set is exactly {first} — first present, none of the rest.
        combined = {a for a, ts in per_article.items() if ts == {first}}

    # Exact, UNCAPPED per-term corpus-wide article count (no truncation → not an upper bound).
    per_term_n: dict[str, int] = {}
    for n in normalized:
        cnt = (
            session.query(func.count(func.distinct(KeywordMention.article_id)))
            .join(Keyword, Keyword.id == KeywordMention.keyword_id)
            .filter(Keyword.normalized_term == n)
            .scalar()
        )
        per_term_n[n] = int(cnt or 0)

    caveat = "Co-occurrence in your corpus, never causation. Counts only, no score."
    if bounded:
        caveat += (
            f" Bounded: the candidate scan was capped at {cap} articles, so the result is a "
            f"SUBSET of the true {op} (it may miss members — a bounded intersection can look empty "
            "when the true one is not). Never a fabricated member."
        )
    return {
        "op": op,
        "terms": [{"term": raw, "normalized": n, "n": per_term_n[n]} for raw, n in pairs],
        "article_ids": sorted(combined),
        "n_combined": len(combined),
        "n_terms": nterms,
        "bounded": bounded,
        "result_bounded": bounded,  # when True the set may be incomplete (a subset), never wrong.
        "method": (
            f"Article-id set {op} over the keyword index, computed from one consistent per-article "
            "matched-term scan: intersection = all N terms present, union = any, difference = the "
            "first term and none of the rest. The set expression is the corpus label; the ids open "
            "the analysis window unchanged."
        ),
        "caveat": caveat,
    }


def per_article_intensity(
    session, article_ids: list[int], terms: list[str], *, limit: int = 50
) -> dict:
    """Which articles pack the most of the N terms: per article, the count of DISTINCT matched
    terms + total mentions, ordered densest-first. A GROUP BY (article) over the conjunction —
    surfaces the articles where the keywords genuinely co-occur, not just the set membership.
    Counts only, no score."""
    pairs = _dedup_normalized(terms)
    normalized = [n for _raw, n in pairs]
    if not article_ids or not normalized:
        return {"n_terms": len(normalized), "articles": [], "method": "", "caveat": ""}
    rows = (
        session.query(
            KeywordMention.article_id,
            func.count(func.distinct(Keyword.normalized_term)),
            func.sum(KeywordMention.count),
        )
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
        .filter(
            Keyword.normalized_term.in_(normalized),
            KeywordMention.article_id.in_(article_ids),
        )
        .group_by(KeywordMention.article_id)
        .order_by(
            func.count(func.distinct(Keyword.normalized_term)).desc(),
            func.sum(KeywordMention.count).desc(),
        )
        .limit(limit)
        .all()
    )
    return {
        "n_terms": len(normalized),
        "articles": [
            {"article_id": int(aid), "distinct_terms": int(dt), "mentions": int(m or 0)}
            for aid, dt, m in rows
        ],
        "method": "Per-article count of distinct matched terms + total mentions, densest first.",
        "caveat": "Counts only, never a score. Co-occurrence within an article, never causation.",
    }


def conditional_trend(session, article_ids: list[int], *, bucket: str = "week") -> dict:
    """The conjunction set's discussion volume over time — distinct articles of the set active on
    each mention date, bucketed by day/week/month (reusing the ``trend`` bucketer). Shows WHEN the
    N-keyword conjunction was discussed. Counts only, no score."""
    if not article_ids:
        return {"bucket": bucket, "points": [], "total": 0, "method": "", "caveat": ""}
    rows = (
        session.query(
            KeywordMention.observed_on,
            func.count(func.distinct(KeywordMention.article_id)),
        )
        .filter(
            KeywordMention.article_id.in_(article_ids),
            KeywordMention.observed_on.isnot(None),
        )
        .group_by(KeywordMention.observed_on)
        .all()
    )
    buckets: dict[str, int] = {}
    for d, c in rows:
        key = _bucket_key(d, bucket)
        buckets[key] = buckets.get(key, 0) + int(c or 0)
    points = [{"date": k, "count": v} for k, v in sorted(buckets.items())]
    return {
        "bucket": bucket,
        "points": points,
        "total": sum(p["count"] for p in points),
        "method": (
            "Distinct articles of the conjunction set active on each mention date, bucketed. "
            "Mention-date activity, not publication date."
        ),
        "caveat": "Counts only, never a score. Co-occurrence over time, never causation.",
    }


def vocabulary_contrast(
    terms_a: list[dict],
    terms_b: list[dict],
    *,
    n_a: int,
    n_b: int,
    limit: int = 30,
) -> dict:
    """PURE. Contrast two corpora by per-term article-SPREAD (the ``corpus_keywords`` output of
    each side). For every term appearing in either side, report its article count on each side and
    the DELTA (a_articles − b_articles). A term absent from a side counts 0 there.

    This is a count difference with EACH side's n shown, never a verdict — a shape to read, not a
    score. Ordered by absolute delta (the biggest divergences first). The DB reads (two
    ``corpus_keywords`` calls) are the seam; this merge is pure and fully testable."""

    def _by_norm(rows: list[dict]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in rows:
            key = r.get("normalized") or _normalize(str(r.get("term", "")))
            if key and key not in out:  # first-wins, mirrors the corpus_keywords ordering
                out[key] = r
        return out

    a = _by_norm(terms_a)
    b = _by_norm(terms_b)
    contrasts: list[dict] = []
    for key in dict.fromkeys(list(a) + list(b)):  # union, stable order (a's first)
        ra, rb = a.get(key), b.get(key)
        aa = int((ra or {}).get("articles", 0))
        ba = int((rb or {}).get("articles", 0))
        contrasts.append(
            {
                "normalized": key,
                "term": (ra or rb or {}).get("term", key),
                "a_articles": aa,
                "b_articles": ba,
                "delta": aa - ba,
            }
        )
    contrasts.sort(key=lambda c: (-abs(c["delta"]), c["normalized"]))
    return {
        "n_a": n_a,
        "n_b": n_b,
        "contrasts": contrasts[:limit],
        "method": (
            "Per-term article spread on each side and the delta (side A − side B); a term absent "
            "from a side counts 0 there. Ordered by absolute delta."
        ),
        "caveat": (
            "A count difference with each side's n shown, never a verdict or score. Silence "
            "(delta toward zero on one side) is a shape to investigate, not proof of absence."
        ),
    }


def near_match_expression(terms: list[str], *, distance: int = 10) -> str | None:
    """PURE. Emit an FTS5 ``NEAR(...)`` MATCH string for the Conjunction Lens's "these N keywords
    within N tokens" query — e.g. ``NEAR("middle east" "oil", 10)``. Each term is FTS5-quoted (the
    canonical ``fts._quote``, so embedded quotes/punctuation are handed to the tokenizer verbatim).

    Returns ``None`` when fewer than two terms carry searchable content (NEAR needs ≥2 phrases).
    Raises ``ValueError`` on a negative distance. Executing this against a real FTS index is
    OPERATOR-GATED; the emission is pure and testable."""
    if distance < 0:
        raise ValueError("NEAR distance must be >= 0")
    phrases = [_quote(t.strip()) for t in terms if t and t.strip() and _HAS_WORD_CHAR.search(t)]
    if len(phrases) < 2:
        return None
    return f"NEAR({' '.join(phrases)}, {int(distance)})"


def _walk_no_score(obj: Any) -> None:
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert not any(b in str(k).lower() for b in banned), f"score-like key: {k}"
            _walk_no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk_no_score(v)


def run_conjunction_selftest() -> dict:
    """Prove the PURE §1 pieces (vocabulary_contrast + NEAR emission) on hand-computed fixtures —
    no DB, no network, no score. The DB set-algebra (corpus_algebra / per_article_intensity /
    conditional_trend) is covered by the pytest in-memory corpus. Returns a top-level ``passed``."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    # vocabulary_contrast: side A over-covers "election", side B over-covers "market".
    a_terms = [
        {"normalized": "election", "term": "election", "articles": 10},
        {"normalized": "market", "term": "market", "articles": 2},
    ]
    b_terms = [
        {"normalized": "election", "term": "election", "articles": 3},
        {"normalized": "market", "term": "market", "articles": 9},
    ]
    vc = vocabulary_contrast(a_terms, b_terms, n_a=12, n_b=12)
    by = {c["normalized"]: c for c in vc["contrasts"]}
    check("contrast_delta_exact", by["election"]["delta"] == 7 and by["market"]["delta"] == -7,
          str(by))
    check("contrast_shows_both_ns", by["election"]["a_articles"] == 10 and by["election"]["b_articles"] == 3)
    # biggest absolute divergence first (both are |7|, tie-break by name → election first)
    check("contrast_ordered_by_abs_delta", vc["contrasts"][0]["normalized"] == "election")
    # a term only on one side counts 0 on the other
    vc2 = vocabulary_contrast(
        [{"normalized": "drought", "term": "drought", "articles": 5}], [], n_a=5, n_b=0
    )
    check("contrast_absent_side_is_zero", vc2["contrasts"][0]["b_articles"] == 0
          and vc2["contrasts"][0]["delta"] == 5)

    # NEAR emission
    near = near_match_expression(["middle east", "oil"], distance=8)
    check("near_emits_fts5", near == 'NEAR("middle east" "oil", 8)', str(near))
    check("near_needs_two_phrases", near_match_expression(["oil"]) is None)
    check("near_drops_punctuation_only", near_match_expression(["oil", "!!!"]) is None)
    neg_ok = False
    try:
        near_match_expression(["a", "b"], distance=-1)
    except ValueError:
        neg_ok = True
    check("near_rejects_negative_distance", neg_ok)
    # embedded quotes are escaped, never syntax
    q = near_match_expression(['he said "hi"', "reply"])
    check("near_escapes_embedded_quotes", q is not None and '""hi""' in q, str(q))

    no_score = True
    try:
        _walk_no_score(vc)
    except AssertionError:
        no_score = False
    check("no_score_field", no_score)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": "oo-conjunction-selftest-1",
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": "Hand-computed asserts over the pure contrast + NEAR emission.",
        "caveat": "Verifies the pure pieces; the DB set-algebra is covered by the pytest corpus. "
        "No score.",
    }
