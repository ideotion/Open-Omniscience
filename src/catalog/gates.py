"""The two quality gates, declared once so one panel can show both honestly.

WHY ONE MODULE FOR TWO GATES. They are independent passes over the same articles and,
until 2026-08-03, neither knew the other existed (verified both directions: the source-side
modules held no ``quarantined`` reference and the article-side modules held no
``Source.status`` reference):

===========  ======================================  =====================================
             Article gate                            Source gate
===========  ======================================  =====================================
Question     is this ITEM an article at all?         is this SOURCE's extraction valid?
Where        ``non_article`` + ``prose_gate``        ``source_audit`` + ``derive_status``
Verdict      ``Article.quarantined`` (reversible)    ``Source.status`` (categorical)
===========  ======================================  =====================================

They belong in one panel for a stronger reason than tidiness: **the source gate's inputs
ARE article-level measurements**, so an article the article gate has already condemned was
still counting toward its source's verdict. Two gates that share an input and disagree
about it is exactly what a single panel makes visible and two panels hide. (That filter is
fixed in ``source_quality``; this module is where the operator can see both gates' terms
side by side and tune them.)

THE TWO HARD FENCES, inherited verbatim from the Leads catalogue's own rules:

1. **A tunable may make a gate STRICTER without limit; it may never let a gate claim more
   than the evidence supports.** Concretely: ``min_pathology_articles`` has no "0" and
   ``ladder_cap_months`` has no "never" -- the cap is what GUARANTEES a disqualified source
   is re-checked, so it may be shortened and not removed.
2. **No tunable may turn a soft criterion into a disqualifier.** ``derive_status`` caps the
   style-ambiguous criteria at ``watch``, and that cap is load-bearing and NOT exposed here.
   Making it configurable is a maintainer ruling, not a settings row.

Every row carries a ``unit`` and an ``impact``, because an unlabelled number is the thing
the 2026-08-03 amendment exists to remove -- and several carry a ``floor_reason``, because
a bound whose reason is hidden reads as an arbitrary restriction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.briefing.catalog import Tunable

# --------------------------------------------------------------------------- #
#  Gate 1 — "Is this an article?"  (the per-ITEM gate; verdict = quarantined)
# --------------------------------------------------------------------------- #
ARTICLE_GATE_TUNABLES: tuple[Tunable, ...] = (
    Tunable(
        key="article_min_words", label="Keep as an article above", default=100,
        lo=20, hi=1000, kind="int", unit="words",
        impact="Above this an item is KEPT as an article whatever its URL looks like. "
               "Raising it lets the URL rules judge longer pages; lowering it protects "
               "more short pages from ever being examined.",
        floor_reason="Below ~20 words there is not enough text for any of the prose "
                     "measures to mean anything, so the item would be judged on its URL alone.",
    ),
    Tunable(
        key="wall_max_words", label="Consent/paywall wall below", default=40,
        lo=10, hi=200, kind="int", unit="words",
        impact="A body this small is chrome-sized, so the boilerplate-phrase match is "
               "allowed to fire. Above it, the same phrase in a real article is ignored.",
    ),
    Tunable(
        key="prose_density_low", label="Not prose below", default=0.12,
        lo=0.02, hi=0.35, kind="float", unit="share of tokens that are function words (0–1)",
        impact="Real prose runs around 0.40 in any supported language; nav soup runs "
               "around 0.05. Raising this condemns more pages as non-prose.",
        floor_reason="This is the language-agnostic prose signal: it works because "
                     "function words are frequent in every language's real sentences, "
                     "which is also why a very low bar stops discriminating at all.",
    ),
    Tunable(
        key="prose_punct_low", label="Not prose below", default=0.01,
        lo=0.001, hi=0.1, kind="float", unit="sentence marks per token",
        impact="A list of headlines has almost no sentence punctuation; an article has "
               "one mark every few dozen tokens. Both this AND the density bar must fail "
               "before an item is condemned.",
    ),
    Tunable(
        key="prose_min_tokens", label="Unmeasurable below", default=20,
        lo=5, hi=200, kind="int", unit="tokens",
        impact="Below this the prose measures are not computed at all and the item is "
               "KEPT — an unmeasurable item is never condemned on a guess.",
        floor_reason="Refusing to measure is the safe direction here: a fabricated "
                     "'not prose' verdict on a handful of tokens would quarantine real "
                     "articles, and the count is too small to carry a share.",
    ),
)

# --------------------------------------------------------------------------- #
#  Gate 2 — "Is this source's extraction valid?"  (verdict = Source.status)
# --------------------------------------------------------------------------- #
SOURCE_GATE_TUNABLES: tuple[Tunable, ...] = (
    Tunable(
        key="qualification_per_pass", label="Sources to judge each collection pass",
        default=5, lo=0, hi=100, kind="int", unit="sources per pass",
        impact="0 turns qualification OFF: candidates stay unqualified and are never "
               "auto-admitted. Nothing is deleted and no existing verdict changes.",
    ),
    Tunable(
        key="min_source_articles", label="Too few articles to judge below", default=20,
        lo=5, hi=200, kind="int", unit="articles",
        impact="A source below this is REPORTED but not judged. Lowering it judges "
               "sources on thinner evidence.",
        floor_reason="Below about 5 articles a 'rate' is one article, not a signature — "
                     "the number would be noise wearing a percentage sign.",
    ),
    Tunable(
        key="source_cohort_floor", label="No baseline below", default=8,
        lo=5, hi=50, kind="int", unit="sources in the same language",
        impact="The soft criteria are cohort-relative, so below this there is no usable "
               "baseline and they stay honestly unflaggable.",
        floor_reason="A cohort this thin cannot produce a percentile that means anything; "
                     "the honest result is no verdict rather than a confident one.",
    ),
    Tunable(
        key="tail_p", label="Cohort tail begins at", default=90,
        lo=80, hi=99, kind="int", unit="percentile",
        impact="LOWERING THIS WIDENS THE TAIL MECHANICALLY — it does not find more bad "
               "sources. By definition ~10% of any cohort sits beyond p90, whatever its "
               "quality, so the flag COUNT is a percentile definition and not a measurement.",
    ),
    Tunable(
        key="pathology_abs_floor", label="Broken extraction at or above", default=0.5,
        lo=0.05, hi=1.0, kind="float", unit="share of the source's articles (0–1)",
        impact="THE ONLY criterion that can DISQUALIFY a source. Changing it changes what "
               "'broken' means. On the 2026-08-03 field corpus no source anywhere reached "
               "it — the strongest signal was 0.211 — so today it is a rare-catastrophe "
               "detector rather than an everyday gate.",
        floor_reason="It is an ABSOLUTE bar on purpose: it must catch a broken source even "
                     "when its whole language cohort is degrading, which is precisely the "
                     "case a cohort-relative tail cannot see.",
    ),
    Tunable(
        key="min_pathology_articles", label="No signature below", default=5,
        lo=2, hi=50, kind="int", unit="articles",
        impact="The raw-count guard beneath the rate. A rate cannot tell 1-in-1,992 from "
               "600-in-1,200, and on the field corpus every 'failing' verdict was the "
               "former.",
        floor_reason="No zero: with a count of 0 or 1 there is no signature to see, only "
                     "an article — and a clean cohort's p90 is exactly 0, so the tail test "
                     "would turn any single article into a verdict.",
    ),
    Tunable(
        key="trial_max_items", label="Articles fetched per trial", default=5,
        lo=1, hi=20, kind="int", unit="articles",
        impact="Each item is a real network fetch against the source, so this is the "
               "bandwidth cost of judging one candidate.",
    ),
    Tunable(
        key="ladder_cap_months", label="Re-check a disqualified source at most every",
        default=6, lo=1, hi=24, kind="int", unit="months",
        impact="The backoff ladder runs 1 → 2 → 4 → capped, resetting on a qualified "
               "verdict. Shorter means a fixed site is noticed sooner.",
        floor_reason="THE CAP IS THE SECOND CHANCE. It is what guarantees a disqualified "
                     "source is re-checked at all — maybe it was a bad day, maybe the site "
                     "changed — so it can be shortened and never removed.",
    ),
)

_ARTICLE_BY_KEY = {t.key: t for t in ARTICLE_GATE_TUNABLES}
_SOURCE_BY_KEY = {t.key: t for t in SOURCE_GATE_TUNABLES}
ALL_GATE_TUNABLES: tuple[Tunable, ...] = ARTICLE_GATE_TUNABLES + SOURCE_GATE_TUNABLES
_BY_KEY = {t.key: t for t in ALL_GATE_TUNABLES}


def clamp_gate_settings(values: dict) -> tuple[dict, list[dict]]:
    """Clamp ``values`` to the gates' safe ranges. Returns ``(clamped, notes)``.

    THE NOTES ARE THE POINT, exactly as in the Leads catalogue: a value outside its range
    is corrected AND reported, so the panel can say what happened. Silently rewriting a
    number the operator typed would leave them believing the gate runs at a setting it does
    not have — which is the specific behaviour the "documented safe range, never a silent
    clamp" ruling forbids.

    An unknown key, or one whose value is not a number, is DROPPED with a note rather than
    guessed at.
    """
    if not isinstance(values, dict):
        return {}, []
    out: dict = {}
    notes: list[dict] = []
    for key, raw in values.items():
        tunable = _BY_KEY.get(key)
        if tunable is None:
            notes.append({"key": key, "reason": "not a setting of either gate"})
            continue
        num = tunable.coerce(raw)
        if num is None:
            notes.append({"key": key, "reason": "not a number"})
            continue
        if num < tunable.lo:
            notes.append({
                "key": key, "given": raw, "used": tunable.lo,
                "reason": tunable.floor_reason or f"below the safe minimum of {tunable.lo}",
            })
            num = tunable.lo
        elif num > tunable.hi:
            notes.append({
                "key": key, "given": raw, "used": tunable.hi,
                "reason": f"above the safe maximum of {tunable.hi}",
            })
            num = tunable.hi
        out[key] = int(num) if tunable.kind == "int" else float(num)
    return out, notes


def tunable_payload(tunables: tuple[Tunable, ...], current: dict) -> list[dict]:
    """Render tunables for the panel, each with its live value, range, unit and reasons.

    The panel renders THIS rather than restating the vocabulary in HTML: a criterion or a
    bound described in two places drifts, and then the UI explains a gate the engine no
    longer applies.
    """
    rows: list[dict] = []
    for t in tunables:
        rows.append({
            "key": t.key,
            "label": t.label,
            "value": current.get(t.key, t.default),
            "default": t.default,
            "lo": t.lo,
            "hi": t.hi,
            "kind": t.kind,
            "unit": t.unit,
            "impact": t.impact,
            "floor_reason": t.floor_reason,
        })
    return rows
