"""
Leads 2.0 — the ordering / floor / clustering / lifecycle cores (planning §2).

The briefing "Card" spine is mature and honesty-clean (``_trigger`` evidence, ``article_ids``,
``n``, ``key``, ``signal``/``method``/``caveat``). §2's elaborations — a disclosed ORDER, a
major-lead FLOOR, story-cluster STACKING, and a lifecycle DIFF — are unbuilt. This module ships
their PURE cores (no DB, no network, over ``Card`` objects), so they are fully testable and the
browser-gated Settings→Leads subtab / evidence-chip row can plug into them later.

Binding honesty rule (§2): importance is the user reading the chips aided by a DISCLOSED
ordering — NEVER a composite score. So ``order_key`` is a lexicographic TUPLE over real facts
(independent sources → magnitude tier → recency), not a blended number, and ``explain_order``
says exactly why a lead ranks where it does. ``is_major`` returns a threshold FACT string, never
a verdict. Nothing here emits a ``*score*`` key.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.briefing.card import Card
from src.signals.near_dup import _connected_components

# Default floors for a "major" lead (OPERATOR-GATED: tune on real field data before shipping).
DEFAULT_MAJOR_FLOORS: dict[str, int] = {"min_n": 50, "min_sources": 5}
# Magnitude tiers for the ordering (coarse buckets so trivial n differences don't reorder leads).
_MAGNITUDE_THRESHOLDS = (10, 50, 200)


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize to naive-UTC so aware/naive datetimes can be compared without a TypeError."""
    if dt.tzinfo is not None:
        return dt.astimezone(tz=None).replace(tzinfo=None)
    return dt


def _parse_iso(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return _to_naive_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _distinct_sources(card: Card) -> int:
    """Distinct non-empty source names in the card's evidence — the independence measure the app
    uses everywhere (three articles from one outlet is one voice, not three)."""
    return len({e.get("source") for e in (card.evidence or []) if e.get("source")})


def newest_evidence_age(card: Card, *, now: datetime) -> float | None:
    """Age in days of the card's FRESHEST dated evidence (``evidence[].published_at``, ISO), or
    ``None`` when no evidence carries a date (degrade to None — never a fabricated freshness).
    Clamped ≥ 0 so a future-dated item never reads as negative age."""
    newest: datetime | None = None
    for e in card.evidence or []:
        dt = _parse_iso(e.get("published_at"))
        if dt is not None and (newest is None or dt > newest):
            newest = dt
    if newest is None:
        return None
    age_days = (_to_naive_utc(now) - newest).total_seconds() / 86400.0
    return max(0.0, age_days)


def _magnitude_bucket(n: int | None) -> int:
    """Coarse magnitude tier of the sample size (0..3), so trivial n differences don't reorder."""
    n = n or 0
    for i, thresh in enumerate(_MAGNITUDE_THRESHOLDS):
        if n < thresh:
            return i
    return len(_MAGNITUDE_THRESHOLDS)


def order_key(card: Card, *, now: datetime) -> tuple[int, int, float]:
    """The DISCLOSED lexicographic sort key (compare with ``reverse=True`` → most prominent
    first): ``(distinct independent sources, magnitude tier of n, recency)``. Recency is
    ``-age_days`` so fresher sorts earlier; a card with no dated evidence sorts LAST on that
    tiebreak (``-inf``). This is a tuple of real facts, NOT a composite score — no weighting, no
    blending; the components stay individually visible via ``explain_order``."""
    age = newest_evidence_age(card, now=now)
    recency = -age if age is not None else float("-inf")
    return (_distinct_sources(card), _magnitude_bucket(card.n), recency)


def sort_leads(cards: list[Card], *, now: datetime) -> list[Card]:
    """Stable-sort leads most-prominent-first by the disclosed ``order_key``."""
    return sorted(cards, key=lambda c: order_key(c, now=now), reverse=True)


def explain_order(card: Card, *, now: datetime) -> str:
    """The "why is this lead here?" string — the exact facts behind ``order_key``, in order."""
    sources = _distinct_sources(card)
    tier = _magnitude_bucket(card.n)
    age = newest_evidence_age(card, now=now)
    recency = f"freshest evidence {age:.1f} day(s) old" if age is not None else "no dated evidence"
    return (
        "Ranked by a disclosed order (independent sources → sample magnitude → recency), "
        f"never a score. This lead: {sources} independent source(s); n={card.n or 0} "
        f"(magnitude tier {tier}/{len(_MAGNITUDE_THRESHOLDS)}); {recency}."
    )


def is_major(card: Card, *, floors: dict[str, int] | None = None) -> dict:
    """A threshold FACT (never a judgement): does the lead clear both a sample-size AND a
    distinct-source floor? Returns the boolean plus the arithmetic string that produced it, so
    the reader sees exactly why — e.g. ``n=120 ≥ 50 AND 6 sources ≥ 5``."""
    f = {**DEFAULT_MAJOR_FLOORS, **(floors or {})}
    n = card.n or 0
    sources = _distinct_sources(card)
    n_ok = n >= f["min_n"]
    s_ok = sources >= f["min_sources"]
    return {
        "major": bool(n_ok and s_ok),
        "n": n,
        "sources": sources,
        "fact": (
            f"n={n} {'≥' if n_ok else '<'} {f['min_n']} AND "
            f"{sources} sources {'≥' if s_ok else '<'} {f['min_sources']}"
        ),
        "method": "A disclosed threshold on real counts (sample size AND distinct sources).",
        "caveat": "A threshold fact, never a judgement of importance — you read the chips.",
    }


def _exact_jaccard(a: set[int], b: set[int]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def cluster_by_article_ids(cards: list[Card], *, threshold: float = 0.5) -> dict:
    """Stack leads built from OVERLAPPING article sets (the story-cluster view). Exact Jaccard
    over each lead's ``article_ids`` (small exact sets — exact, not MinHash-estimated), edges at
    ``>= threshold``, union-find via the shared ``_connected_components`` (which returns only the
    multi-lead groups; singletons stay individual leads). A shape to read, not a merge — counts
    only, no score. Leads with no ``article_ids`` (keyword-seeded / whole-corpus) never cluster."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    labels = [str(i) for i in range(len(cards))]  # unique labels regardless of card id/key
    sets = {labels[i]: set(cards[i].article_ids or []) for i in range(len(cards))}
    nodes = set(labels)
    edges: set[tuple[str, str]] = set()
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = sets[labels[i]], sets[labels[j]]
            if a and b and _exact_jaccard(a, b) >= threshold:
                edges.add((labels[i], labels[j]))
    comps = _connected_components(nodes, edges)
    clusters = [
        [
            {
                "type": cards[int(lbl)].type,
                "key": cards[int(lbl)].key,
                "id": cards[int(lbl)].id,
                "n_articles": len(cards[int(lbl)].article_ids or []),
            }
            for lbl in sorted(comp, key=int)
        ]
        for comp in comps
    ]
    return {
        "threshold": threshold,
        "clusters": clusters,
        "n_clusters": len(clusters),
        "method": (
            "Exact Jaccard over each lead's article-id set; leads overlapping ≥ threshold are "
            "stacked (union-find). Singletons stay individual leads."
        ),
        "caveat": "Stacks leads built from overlapping articles — a shape, not a merge. No score.",
    }


def _card_identity(card: Card) -> str:
    return card.id or f"{card.type}:{card.key}"


def card_deltas(prev_cards: list[Card], new_cards: list[Card]) -> dict:
    """Lifecycle diff between two briefing runs, matched by card identity (id, else type:key):
    ``new`` (absent before), ``strengthened`` / ``weakened`` (both n & sources moved the same
    way), ``mixed`` (they moved opposite ways — stated honestly, not forced into one label),
    ``unchanged``, ``gone`` (present before, absent now). Each carries the (n, sources) delta.
    Counts only, no score."""
    prev = {_card_identity(c): c for c in prev_cards}
    new = {_card_identity(c): c for c in new_cards}
    deltas: list[dict] = []
    for ident, c in new.items():
        if ident not in prev:
            deltas.append({"id": ident, "status": "new", "n_delta": None, "sources_delta": None})
            continue
        p = prev[ident]
        n_d = (c.n or 0) - (p.n or 0)
        s_d = _distinct_sources(c) - _distinct_sources(p)
        if n_d == 0 and s_d == 0:
            status = "unchanged"
        elif n_d >= 0 and s_d >= 0:
            status = "strengthened"
        elif n_d <= 0 and s_d <= 0:
            status = "weakened"
        else:
            status = "mixed"  # n and sources moved opposite ways — never mislabelled either way.
        deltas.append({"id": ident, "status": status, "n_delta": n_d, "sources_delta": s_d})
    for ident in prev:
        if ident not in new:
            deltas.append({"id": ident, "status": "gone", "n_delta": None, "sources_delta": None})
    return {
        "deltas": deltas,
        "method": "Matched by card identity; status from the sign of the (n, sources) deltas.",
        "caveat": "Lifecycle facts (counts + deltas), never a score. 'mixed' = the two moved apart.",
    }


def _wrap_dict(d: dict) -> Any:
    """Duck-type a briefing card DICT (from ``Card.to_dict()`` / the cached briefing) as the
    object the cores read — they only touch ``evidence``/``n``/``article_ids``/``type``/``key``/
    ``id``, so no full ``Card`` reconstruction is needed."""
    from types import SimpleNamespace

    return SimpleNamespace(
        evidence=d.get("evidence") or [],
        n=d.get("n"),
        article_ids=d.get("article_ids") or [],
        type=d.get("type"),
        key=d.get("key"),
        id=d.get("id"),
    )


def assemble_leads_view(
    card_dicts: list[dict],
    *,
    now: datetime,
    sort: str = "default",
    floors: dict[str, int] | None = None,
    cluster: bool = False,
) -> dict:
    """Assemble the §2 Leads-2.0 VIEW over briefing card DICTS (the cached Home cards): per-lead
    EVIDENCE CHIPS (n · distinct independent sources · freshest-evidence age — real facts), a
    disclosed ORDER-explanation, and a major-lead threshold FACT, in the chosen order. PURE — no
    DB, no network, no score.

    ``sort='default'`` preserves the INPUT order EXACTLY (byte-identical to Home); ``'prominence'``
    reorders by the disclosed ``order_key`` (independent sources → magnitude tier → recency).
    ``cluster`` stacks leads built from overlapping article sets. Raises ``ValueError`` on a bad
    ``sort`` (fail loud)."""
    if sort not in ("default", "prominence"):
        raise ValueError("sort must be 'default' or 'prominence'")
    eff_floors = {**DEFAULT_MAJOR_FLOORS, **(floors or {})}
    pairs = [(d, _wrap_dict(d)) for d in card_dicts]
    if sort == "prominence":
        pairs = sorted(pairs, key=lambda p: order_key(p[1], now=now), reverse=True)
    leads = []
    for d, w in pairs:
        age = newest_evidence_age(w, now=now)
        leads.append(
            {
                "type": d.get("type"),
                "key": d.get("key"),
                "id": d.get("id"),
                "title": d.get("title"),
                "evidence_chips": {
                    "n": w.n or 0,
                    "distinct_sources": _distinct_sources(w),
                    "newest_age_days": round(age, 2) if age is not None else None,
                },
                "order_explain": explain_order(w, now=now),
                "major": is_major(w, floors=eff_floors),
            }
        )
    out: dict = {
        "schema": "oo-leads-view-1",
        "sort": sort,
        "floors": eff_floors,
        "count": len(leads),
        "leads": leads,
        "method": (
            "The cached briefing leads + disclosed chips (n · distinct independent sources · "
            "freshest-evidence age) / order-explanation / major-floor fact over each lead's real "
            "evidence. sort=default is byte-identical to Home; sort=prominence uses the disclosed "
            "order_key (sources → magnitude → recency), never a score."
        ),
        "caveat": (
            "Chips and ordering are disclosed facts you read — never a composite importance "
            "score. A sort changes ORDER + adds disclosure, never the data or a caveat."
        ),
    }
    if cluster:
        out["clusters"] = cluster_by_article_ids([w for _d, w in pairs])
    return out


def _walk_no_score(obj: Any) -> None:
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert not any(b in str(k).lower() for b in banned), f"score-like key: {k}"
            _walk_no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk_no_score(v)


def run_leads_selftest() -> dict:
    """Prove the §2 pure mechanism on hand-built Cards — no DB/network/score. Pins the ordering
    (more sources ranks earlier; recency breaks a tie), the major-floor fact, story clustering by
    exact Jaccard, and the lifecycle diff (incl. the honest 'mixed' case)."""
    checks: list[dict] = []
    now = datetime(2026, 7, 13)

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    def mk(key, *, n, sources, ages=(), bucket="rising", article_ids=()):
        ev = [{"source": f"src{i}", "published_at": None} for i in range(sources)]
        for i, a in enumerate(ages):
            if i < len(ev):
                ev[i]["published_at"] = (
                    datetime(2026, 7, 13) - _days(a)
                ).isoformat()
        return Card(
            type="rising", title=key, summary="s", bucket=bucket, method="m", caveat="c",
            key=key, n=n, evidence=ev, article_ids=list(article_ids),
        )

    def _days(d):
        from datetime import timedelta

        return timedelta(days=d)

    # Ordering: b has more sources → ranks before a regardless of n.
    a = mk("a", n=500, sources=2)
    b = mk("b", n=10, sources=6)
    ordered = sort_leads([a, b], now=now)
    check("more_sources_ranks_first", ordered[0].key == "b", str([c.key for c in ordered]))

    # Recency breaks a tie when sources + magnitude tier are equal.
    fresh = mk("fresh", n=60, sources=3, ages=(1,))
    stale = mk("stale", n=60, sources=3, ages=(40,))
    ordered2 = sort_leads([stale, fresh], now=now)
    check("recency_breaks_a_tie", ordered2[0].key == "fresh", str([c.key for c in ordered2]))

    # order_key is a tuple (not a scalar score), and explain_order names the facts.
    ok_tuple = isinstance(order_key(fresh, now=now), tuple)
    check("order_key_is_a_tuple_not_a_score", ok_tuple)
    check("explain_names_the_facts", "independent source" in explain_order(fresh, now=now))

    # Major floor.
    maj = is_major(mk("m", n=120, sources=6))
    check("major_true_with_fact", maj["major"] is True and "≥" in maj["fact"], maj["fact"])
    not_maj = is_major(mk("s", n=120, sources=2))
    check("major_false_when_sources_short", not_maj["major"] is False)

    # Story clustering: two leads over overlapping article sets stack; a disjoint one doesn't.
    c1 = mk("c1", n=5, sources=2, article_ids=[1, 2, 3, 4])
    c2 = mk("c2", n=5, sources=2, article_ids=[2, 3, 4, 5])  # Jaccard 3/5 = 0.6 >= 0.5
    c3 = mk("c3", n=5, sources=2, article_ids=[90, 91])       # disjoint
    cl = cluster_by_article_ids([c1, c2, c3], threshold=0.5)
    stacked = cl["clusters"][0] if cl["clusters"] else []
    check(
        "overlapping_leads_stack",
        cl["n_clusters"] == 1 and {m["key"] for m in stacked} == {"c1", "c2"},
        str(cl["clusters"]),
    )

    # Lifecycle diff incl. the honest 'mixed' case (n up, sources down).
    prev = [mk("p1", n=10, sources=3), mk("p2", n=10, sources=3)]
    new = [mk("p1", n=20, sources=5), mk("p2", n=20, sources=1)]  # p1 strengthened, p2 mixed
    diff = {d["id"]: d for d in card_deltas(prev, new)["deltas"]}
    # identity is the card id (a hash of type+key), so match on the observed statuses.
    statuses = sorted(d["status"] for d in diff.values())
    check("lifecycle_has_strengthened_and_mixed", statuses == ["mixed", "strengthened"], str(statuses))

    no_score = True
    try:
        _walk_no_score(maj)
        _walk_no_score(cl)
        _walk_no_score(card_deltas(prev, new))
    except AssertionError:
        no_score = False
    check("no_score_field", no_score)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": "oo-leads-selftest-1",
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": "Hand-built Cards through the ordering / floor / clustering / lifecycle cores.",
        "caveat": "Verifies the pure mechanism; the Settings→Leads UI is browser-gated. No score.",
    }
