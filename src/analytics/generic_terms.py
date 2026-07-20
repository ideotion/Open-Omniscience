"""Generic-term / publishing-furniture DF-ubiquity gate (Leads-calibration S1.2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A candidate keyword/topic is GENERIC (attribution boilerplate, or a common word that
merely tracks total collection volume) when it is carried by an implausibly large SHARE
of the sources active, in its OWN language, over the producer's own window -- a fact no
POS tagger is needed to see. This is the SAME measure ``src.analytics.engine_report``'s
``_generic_terms`` review-worklist already surfaces (document-frequency ubiquity),
computed here INLINE as a live GATE for candidate producers (flooded_topic,
story_propagation) rather than only as an offline review worklist. The trusted keyword
index is untouched by this module -- it gates which terms may become HOME LEADS, never
deletes or hides a keyword anywhere else (the anti-capping ruling stands).

Calibrated against the 2026-07-18 field export: "data"/"media"/"social" (English,
ubiquitous across nearly every active source) and "vir"/"lani" (Slovenian attribution-
line / temporal-deictic furniture, ubiquitous across active Slovenian sources) must gate
out; a genuine event term concentrated in a minority of sources must not.
"""

from __future__ import annotations

# The share of same-language active sources a term must be carried by before it is
# treated as generic/furniture rather than a real topic. Calibrated conservatively (a
# genuine major event a large minority of sources cover should still survive); tune with
# evidence from further exports, never speculatively.
GENERIC_TERM_MIN_SHARE = 0.40

# Below this many same-language active sources, ubiquity cannot be honestly measured
# (a single-source cohort is either 0% or 100% by construction) -- an unmeasurable
# cohort never gates a term (silence, not a fabricated verdict).
GENERIC_TERM_MIN_COHORT = 3


def generic_term_share(n_sources_with_term: int, n_active_sources_same_lang: int) -> float:
    """Share of same-language active sources carrying a term. 0.0 when there is no
    measurable cohort -- callers must check the cohort size separately before trusting
    a low share as "not generic" (see :func:`is_generic_by_df_ubiquity`)."""
    if n_active_sources_same_lang <= 0:
        return 0.0
    return n_sources_with_term / n_active_sources_same_lang


def is_generic_by_df_ubiquity(
    n_sources_with_term: int,
    n_active_sources_same_lang: int,
    *,
    min_share: float = GENERIC_TERM_MIN_SHARE,
    min_cohort: int = GENERIC_TERM_MIN_COHORT,
) -> bool:
    """True when a term is carried by >= ``min_share`` of the same-language sources
    active in the window -- boilerplate/attribution furniture or a corpus-volume
    tracker, not a real topic. Requires a measurable cohort (>= ``min_cohort`` active
    same-language sources); an unmeasurably small cohort never gates."""
    if n_active_sources_same_lang < min_cohort:
        return False
    return generic_term_share(n_sources_with_term, n_active_sources_same_lang) >= min_share
