"""Super-group honest statistics (supergroups brief S1, 2026-07-18).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's live-corpus export of Insights -> Groups (super-groups) found the
scaffold healthy but its totals BROKEN: a generic homograph-prone member (the plain
term "data") accounted for 85% of the "Artificial intelligence" group's headline
total while the total itself said nothing about it (row 1); the SAME underlying
keyword can be a plain FAMILY member AND separately covered by a RING member in the
SAME group, so summing every member's own total double-counts it (row 3); a member
(a ring like "logic") can legitimately sit in more than one group (Mathematics AND
Philosophy) with no disclosure that the totals overlap (row 2).

This module is the ONE primitive every super-group statistic reads: resolve a
group's members to their DISTINCT (deduped) keyword-id set FIRST, then compute
every stat from that set — never by summing per-member totals that might share
ids. Every payload MANDATORILY carries the two disclosures (dominance + cross-group
overlap) the field export proved are load-bearing, not optional decoration.

Perf discipline (the SQLCipher codec-order lesson): every query here reads only
``keyword_mentions``' small denormalised columns (keyword_id / count / observed_on /
source_id) or the ``keywords`` table's own small columns (id / normalized_term /
language) — never a keyword_mentions -> articles join, never the article content.

Counts and ratios only. NO composite score (the no-score key-walkers must pass on
every payload this module returns).
"""

from __future__ import annotations

from datetime import date, timedelta

_IN_CHUNK = 600


def _chunks(seq: list, size: int = _IN_CHUNK):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def resolve_member_keyword_ids(
    db, member_rows: list[tuple[str, str | None]]
) -> dict[str, set[int]]:
    """member_key (``normalized_term``, the ring id for a ring member) -> the
    DISTINCT keyword ids it resolves to.

    A FAMILY member (``ring_id`` is ``None``) matches its own normalized term AND
    its morphological family (via ``canonical_key`` — plural/possessive variants);
    a RING member matches every one of the ring's cross-language terms (the
    super-ring model). Small-column queries only (id + normalized_term), never
    ``keyword_mentions``.
    """
    from src.analytics.equivalence import ring_meta
    from src.analytics.families import canonical_key
    from src.database.models import Keyword

    term_to_keys: dict[str, set[str]] = {}
    canon_to_keys: dict[str, set[str]] = {}
    out: dict[str, set[int]] = {k: set() for k, _ in member_rows}
    for norm_key, ring_id in member_rows:
        if ring_id:
            meta = ring_meta(ring_id)
            for _lang, term in meta.members if meta else ():
                term_to_keys.setdefault(term, set()).add(norm_key)
        else:
            term_to_keys.setdefault(norm_key, set()).add(norm_key)
            canon_to_keys.setdefault(canonical_key(norm_key), set()).add(norm_key)

    if term_to_keys:
        for chunk in _chunks(list(term_to_keys)):
            for kid, norm in (
                db.query(Keyword.id, Keyword.normalized_term)
                .filter(Keyword.normalized_term.in_(chunk))
                .all()
            ):
                for key in term_to_keys.get(norm, ()):
                    out[key].add(int(kid))
    if canon_to_keys:
        # A family's morphological variants (country<->countries): canonical_key is a
        # Python function, not a column, so this scan is unavoidable -- but only over
        # the small (id, normalized_term) columns, never mentions/content.
        for kid, norm in db.query(Keyword.id, Keyword.normalized_term).all():
            keys = canon_to_keys.get(canonical_key(norm))
            if keys:
                for key in keys:
                    out[key].add(int(kid))
    return out


def distinct_ids(member_id_sets: dict[str, set[int]]) -> set[int]:
    """The DEDUPED union of every member's keyword ids -- a group's TRUE
    denominator (row 3): a keyword covered by two members in the SAME group
    counts once, never twice."""
    out: set[int] = set()
    for ids in member_id_sets.values():
        out |= ids
    return out


def member_overlaps(member_id_sets: dict[str, set[int]]) -> dict[str, list[str]]:
    """member_key -> the OTHER member keys in the SAME group sharing >= 1 keyword id
    (the within-group double-counting disclosure, row 3)."""
    keys = list(member_id_sets)
    pairs: dict[str, set[str]] = {k: set() for k in keys}
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if member_id_sets[a] & member_id_sets[b]:
                pairs[a].add(b)
                pairs[b].add(a)
    return {k: sorted(v) for k, v in pairs.items()}


def cross_group_membership(
    groups: list[tuple[str, list[tuple[str, str | None]]]],
) -> dict[tuple[str, str | None], list[str]]:
    """(normalized_term, ring_id) -> the super-group NAMES that carry this exact
    member row, for every member that appears in MORE THAN ONE group (row 2: the
    "logic" ring legitimately sitting in both Mathematics and Philosophy). Pure,
    no DB -- just the scaffold's own membership rows. ``groups`` is
    ``[(group_name, [(normalized_term, ring_id), ...]), ...]``."""
    by_member: dict[tuple[str, str | None], list[str]] = {}
    for name, members in groups:
        for norm, ring_id in members:
            by_member.setdefault((norm, ring_id), []).append(name)
    return {k: v for k, v in by_member.items() if len(v) > 1}


def _per_id_mentions(
    db, keyword_ids, lo: date | None = None, hi: date | None = None
) -> dict[int, int]:
    """Per-keyword-id summed mention COUNT, optionally windowed on observed_on.
    Reads only the denormalised keyword_mentions.count -- no article decrypt."""
    from sqlalchemy import func

    from src.database.models import KeywordMention

    out: dict[int, int] = {}
    ids = sorted(keyword_ids)
    if not ids:
        return out
    for chunk in _chunks(ids):
        q = db.query(
            KeywordMention.keyword_id, func.coalesce(func.sum(KeywordMention.count), 0)
        ).filter(KeywordMention.keyword_id.in_(chunk))
        if lo is not None:
            q = q.filter(KeywordMention.observed_on >= lo)
        if hi is not None:
            q = q.filter(KeywordMention.observed_on < hi)
        for kid, total in q.group_by(KeywordMention.keyword_id).all():
            out[int(kid)] = int(total or 0)
    return out


def _distinct_source_count(db, keyword_ids) -> int:
    from src.database.models import KeywordMention

    ids = sorted(keyword_ids)
    if not ids:
        return 0
    seen: set[int] = set()
    for chunk in _chunks(ids):
        for (sid,) in (
            db.query(KeywordMention.source_id)
            .filter(KeywordMention.keyword_id.in_(chunk), KeywordMention.source_id.isnot(None))
            .distinct()
        ):
            seen.add(int(sid))
    return len(seen)


def _language_breakdown(db, keyword_ids, per_id_mentions: dict[int, int]) -> dict[str, int]:
    """Language -> summed mentions, for the group's distinct id set. A keyword's
    OWN stored language (the same field the app already treats as authoritative
    for a single keyword); unknown-language mentions are honestly bucketed '?'."""
    from src.database.models import Keyword

    ids = sorted(keyword_ids)
    out: dict[str, int] = {}
    if not ids:
        return out
    for chunk in _chunks(ids):
        for kid, lang in db.query(Keyword.id, Keyword.language).filter(Keyword.id.in_(chunk)):
            lg = (lang or "").strip().lower() or "?"
            out[lg] = out.get(lg, 0) + per_id_mentions.get(int(kid), 0)
    return out


def _windowed_sum(db, keyword_ids, lo: date, hi: date) -> int:
    """The summed mention count over ``keyword_ids`` for the half-open window
    ``[lo, hi)``. Prefers the opt-in ``keyword_daily`` rollup serve (the SAME
    windowed machinery ``queries.trending`` uses — never rebuilt here), which
    returns a whole-corpus per-keyword dict we subset to the ids we need;
    falls back to a direct denormalised ``keyword_mentions`` scan on ANY miss
    (not opted in, not built yet, a bind mismatch, or any error)."""
    if keyword_ids:
        from src.analytics import rollup_serve

        served = rollup_serve.windowed_counts(db, lo=lo, hi=hi - timedelta(days=1))
        if served is not None:
            return sum(served.get(kid, 0) for kid in keyword_ids)
    return sum(_per_id_mentions(db, keyword_ids, lo, hi).values())


def daily_series(db, keyword_ids, *, days: int, today: date | None = None) -> list[dict]:
    """Daily mention-count series (``[{"date", "count"}]``) for a group's DISTINCT
    keyword-id set over the last ``days`` days -- the S1.5 sparkline substrate.

    Summed over the SAME deduped id set ``group_total``/``group_rate`` use (never a
    per-member sum of each member's own series, which would reintroduce the row-3
    double count at the chart level while the headline number stays honest). Days
    with zero mentions are omitted (no interpolation), matching the existing
    ``trend``/``_window_daily_series`` convention. Small-column keyword_mentions
    scan only, bounded by ``days`` and the group's own (typically small) id set."""
    from sqlalchemy import func

    from src.database.models import KeywordMention

    ids = sorted(keyword_ids)
    if not ids:
        return []
    today = today or date.today()
    lo = today - timedelta(days=days)
    agg: dict[str, int] = {}
    for chunk in _chunks(ids):
        rows = (
            db.query(
                KeywordMention.observed_on, func.coalesce(func.sum(KeywordMention.count), 0)
            )
            .filter(KeywordMention.keyword_id.in_(chunk), KeywordMention.observed_on >= lo)
            .group_by(KeywordMention.observed_on)
            .all()
        )
        for d, c in rows:
            key = d.isoformat() if hasattr(d, "isoformat") else str(d)
            agg[key] = agg.get(key, 0) + int(c or 0)
    return [{"date": d, "count": c} for d, c in sorted(agg.items())]


def group_rate(
    db,
    keyword_ids,
    *,
    window_days: int = 7,
    baseline_days: int = 30,
    today: date | None = None,
) -> dict:
    """The recent-vs-baseline RATE for a group's distinct id set -- the SAME
    disclosed ratio the corpus-wide ``queries.trending`` grammar uses (never a
    significance test, a transparent ratio): growth = recent / expected, where
    expected = (prior / baseline_days) * window_days. A brand-new group with no
    prior reports growth as the recent count (an honest floor, not a divide-by-
    zero fabrication)."""
    today = today or date.today()
    w_start = today - timedelta(days=window_days)
    b_start = w_start - timedelta(days=baseline_days)
    hi = today + timedelta(days=1)
    recent = _windowed_sum(db, keyword_ids, w_start, hi)
    prior = _windowed_sum(db, keyword_ids, b_start, w_start)
    expected = (prior / baseline_days) * window_days if baseline_days else 0.0
    growth = recent / expected if expected >= 1 else float(recent)
    return {
        "recent": int(recent),
        "prior": int(prior),
        "expected": round(expected, 2),
        "growth": round(growth, 2),
        "window_days": window_days,
        "baseline_days": baseline_days,
    }


def supergroup_stats(
    db,
    sg,
    *,
    other_groups: list[tuple[str, list[tuple[str, str | None]]]] | None = None,
    window_days: int = 7,
    baseline_days: int = 30,
    today: date | None = None,
) -> dict:
    """The full honest stat payload for ONE super-group (S1).

    ``sg`` is a ``KeywordSuperGroup`` ORM row (its ``.members`` relationship is
    read). ``other_groups`` is the SAME ``[(name, [(normalized_term, ring_id)])]``
    shape ``cross_group_membership`` takes, over ALL groups (including this one) --
    pass it once per listing call so the O(members^2) overlap scan runs once, not
    once per group.

    Returns ``{group_total: {mentions, distinct_keywords}, dominance: {member,
    mentions, share}, rate: {...}, distinct_sources: n, languages: {...},
    cross_group_overlap: {member_key: [other group names]}, within_group_overlap:
    {member_key: [other member keys]}, method, caveat}``. A group with zero
    resolvable members degrades honestly (zeros, no fabricated dominance)."""
    member_rows = [(m.normalized_term, m.ring_id) for m in sg.members]
    member_id_sets = resolve_member_keyword_ids(db, member_rows)
    all_ids = distinct_ids(member_id_sets)

    per_id_mentions = _per_id_mentions(db, all_ids)
    group_mentions = sum(per_id_mentions.values())

    # Per-MEMBER mentions over ITS OWN (unresolved-for-overlap) id set -- used only
    # for the dominance disclosure, never summed across members for the group total
    # (that is exactly the double-counting bug this module fixes).
    member_mentions = {
        key: sum(per_id_mentions.get(kid, 0) for kid in ids)
        for key, ids in member_id_sets.items()
    }
    dominance = None
    if group_mentions > 0 and member_mentions:
        top_key = max(member_mentions, key=lambda k: member_mentions[k])
        top_val = member_mentions[top_key]
        dominance = {
            "member": top_key,
            "mentions": top_val,
            "share": round(top_val / group_mentions, 4),
        }

    overlap_within = member_overlaps(member_id_sets)
    cross = cross_group_membership(other_groups) if other_groups is not None else {}
    overlap_cross = {
        key: [n for n in cross.get((key, ring_id), []) if n != sg.name]
        for key, ring_id in member_rows
        if (key, ring_id) in cross
    }

    return {
        "group_total": {
            "mentions": group_mentions,
            "distinct_keywords": len(all_ids),
        },
        "dominance": dominance,
        "rate": group_rate(db, all_ids, window_days=window_days, baseline_days=baseline_days, today=today),
        "distinct_sources": _distinct_source_count(db, all_ids),
        "languages": _language_breakdown(db, all_ids, per_id_mentions),
        "cross_group_overlap": overlap_cross,
        "within_group_overlap": {k: v for k, v in overlap_within.items() if v},
        "method": (
            "Members resolved to their DISTINCT (deduped) keyword-id set FIRST — a "
            "keyword covered by two members of the same group (a plain family AND a "
            "covering ring) counts once, never twice. Mentions/sources/languages read "
            "the denormalised keyword_mentions columns only (no content decrypt). "
            "The recent-vs-baseline rate is the same disclosed ratio as trending "
            "keywords, never a significance test."
        ),
        "caveat": (
            "Counts and ratios only, no composite score. A group's headline total "
            "can be dominated by one member (see 'dominance') and a member can "
            "legitimately sit in more than one group (see 'cross_group_overlap') — "
            "both are disclosed, never silently summed as if exclusive."
        ),
    }
