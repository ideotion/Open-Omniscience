"""Group-level (cross-language ring) honest statistics — GROUPS amendment §C, 2026-07-18.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The sibling supergroups brief's S1 resolution primitive (member keyword-ids ->
windowed series/rate via the existing rollup + trending grammar) serves BOTH
levels of the keyword hierarchy: a GROUP (an equivalence ring in the internal
model — "ring" stays the internal name per the naming-sweep ruling; it
disappears only from user-visible text, per
``AUTONOMOUS_SESSION_BRIEF_2026-07-18_GROUPS_LAYER_AMENDMENT.md`` §A) is simply
a smaller member set — one per-language term instead of a super-group's
families+rings. This module is the group-level counterpart of
``supergroup_stats.py``, REUSING its generic keyword-id-set primitives
(``_per_id_mentions``, ``_language_breakdown``, ``_distinct_source_count``,
``group_rate``, ``daily_series``) rather than duplicating them — the brief's
own words: "the same primitive, one level down".

The disclosure is ADAPTED to this level: a super-group's headline risk is one
MEMBER dominating the total (a plain family vs. a covering ring, or one family
vs. another); a group's is one LANGUAGE dominating it ("ru carries 61% of this
group") — the honest equivalent one level down, fed by the same
``language_breakdown`` mechanism the app already surfaces on a merged ring row
(``equivalence.merge_equivalents`` / ``queries.trending``).

Member resolution mirrors ``queries.ring_country_split`` exactly (the
established, already-shipped ring resolver): a keyword's normalized_term must
match a declared member term AND its own stored language must match that
member's declared language (``equivalence.ring_of``) — never a fabricated
cross-language merge. This is simpler than the super-group resolver
(``resolve_member_keyword_ids``) because a ring has no family/canonical-key
matching to layer on top.

Counts and ratios only. NO composite score (the no-score key-walkers must pass
on every payload this module returns).
"""

from __future__ import annotations

from datetime import date

from src.analytics.supergroup_stats import (
    _chunks,
    _distinct_source_count,
    _language_breakdown,
    _per_id_mentions,
    daily_series,
    group_rate,
)

GROUP_STATS_METHOD = (
    "Every declared member (language:term) of the group is resolved to its Keyword "
    "row via the SAME language-qualified match ring_country_split uses — a keyword's "
    "own stored language must match the member's declared language, never a "
    "fabricated cross-language merge. Mentions/sources/languages read the "
    "denormalised keyword_mentions columns only (no content decrypt). The "
    "recent-vs-baseline rate is the same disclosed ratio as trending keywords and "
    "super-groups, never a significance test."
)

GROUP_STATS_CAVEAT = (
    "Counts and ratios only, no composite score. A group's headline total can be "
    "dominated by one LANGUAGE (see 'dominance') — the honest equivalent of a "
    "super-group's member dominance, one level down. Keywords with no stored "
    "language are excluded (conservative), never guessed."
)


def resolve_group_keyword_ids(db, ring_id: str) -> set[int]:
    """A group's (ring's) DISTINCT keyword ids.

    Language-qualified — the SAME resolver ``queries.ring_country_split`` uses:
    fetch every Keyword whose normalized_term is one of the ring's declared member
    terms, then keep only the ones whose OWN stored language actually matches that
    member's declared language (``equivalence.ring_of``). A term that happens to
    collide with another ring/language is never fabricated into this group."""
    from src.analytics import equivalence
    from src.database.models import Keyword

    ring = equivalence.ring_meta(ring_id)
    if ring is None:
        return set()
    member_terms = {term for _lang, term in ring.members}
    if not member_terms:
        return set()
    ids: set[int] = set()
    for chunk in _chunks(list(member_terms)):
        rows = (
            db.query(Keyword.id, Keyword.language, Keyword.normalized_term)
            .filter(Keyword.normalized_term.in_(chunk))
            .all()
        )
        for kid, lang, norm in rows:
            if equivalence.ring_of(lang, norm) == ring_id:
                ids.add(int(kid))
    return ids


def group_stats(
    db,
    ring_id: str,
    *,
    window_days: int = 7,
    baseline_days: int = 30,
    series_days: int = 30,
    today: date | None = None,
) -> dict:
    """The full honest stat payload for ONE group (a cross-language ring), §C.

    Returns ``{ring_id, found, label, group_total: {mentions, distinct_keywords},
    dominance: {language, mentions, share} | None, rate: {...}, series: [...],
    distinct_sources: n, languages: {...}, method, caveat}``. An unknown ring id
    degrades to ``found: False`` with a caveat, never a traceback; a ring with zero
    resolvable members degrades to zeros with ``dominance: None`` — never a
    fabricated dominance or divide-by-zero."""
    from src.analytics.equivalence import ring_meta

    ring = ring_meta(ring_id)
    if ring is None:
        return {"ring_id": ring_id, "found": False, "caveat": "No such equivalence ring."}

    ids = resolve_group_keyword_ids(db, ring_id)
    per_id_mentions = _per_id_mentions(db, ids)
    group_mentions = sum(per_id_mentions.values())
    breakdown = _language_breakdown(db, ids, per_id_mentions)

    dominance = None
    if group_mentions > 0 and breakdown:
        top_lang = max(breakdown, key=lambda k: breakdown[k])
        top_val = breakdown[top_lang]
        dominance = {
            "language": top_lang,
            "mentions": top_val,
            "share": round(top_val / group_mentions, 4),
        }

    return {
        "ring_id": ring_id,
        "found": True,
        "label": ring.label,
        "group_total": {"mentions": group_mentions, "distinct_keywords": len(ids)},
        "dominance": dominance,
        "rate": group_rate(
            db, ids, window_days=window_days, baseline_days=baseline_days, today=today
        ),
        "series": daily_series(db, ids, days=series_days, today=today),
        "distinct_sources": _distinct_source_count(db, ids),
        "languages": breakdown,
        "method": GROUP_STATS_METHOD,
        "caveat": GROUP_STATS_CAVEAT,
    }
