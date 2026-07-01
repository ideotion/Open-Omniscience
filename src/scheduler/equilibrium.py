"""Optional per-language cadence lever — steer the corpus mix toward a
USER-DEFINED target by re-checking over-represented languages LESS OFTEN, while
never excluding a source.

DEFAULT OFF. With an empty target (the default) every function is an identity /
no-op and collection is exactly the pure random per-tag rotation. This exists so
the operator can *opt in* to nudge the output mix once the source base is
diversified — it is a cadence multiplier, never a filter that drops a source.

Two guarantees make it honest:
  * NON-EXCLUSION — an over-represented language's source is only *deferred* to a
    later pass with probability (1 − pace); the continuous rotation revisits it.
  * A HARD FRESHNESS FLOOR — a source not fetched within ``cap_seconds`` (mirrors
    the de-churn backoff cap) is ALWAYS kept, so equilibrium can never let a
    source go stale past the cap. First reaches are never slowed (a never-fetched
    source is always kept): only the RE-CHECK cadence of already-covered,
    over-represented languages is paced.

No score anywhere — ``pace`` is a transparent cadence multiplier in [floor, 1].
The target is whatever the operator sets; the bundled ``PRESETS`` are optional,
dated, cited SUGGESTIONS (one measure of a contested quantity), never applied by
default and never the app's own opinion.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.models import Article

DEFAULT_FLOOR = 0.2
# A source not fetched within this window is always kept (never starved). Mirrors
# src.ingest.pipeline.BACKOFF_CAP_S (~6 h) so equilibrium and de-churn agree on
# the maximum staleness a feed may reach.
DEFAULT_CAP_SECONDS = 6 * 3600

# Optional STARTING POINTS the operator may adopt — NOT applied by default and
# NOT the app's judgement. Each is ONE dated measure of a contested quantity;
# shares are approximate and meant to be edited. (Reviewed 2026-07; adjust on
# the operator's own machine.)
#   web_content    ≈ share of web *content* by language (W3Techs-style): keeps
#                    English near half — the most literal "digital-content reality".
#   online_population ≈ share of internet *users* by language: more Global-South-
#                    weighted; aligns with the de-US-centring stance.
PRESETS: dict[str, dict[str, float]] = {
    "web_content": {
        "en": 0.49, "es": 0.06, "de": 0.06, "ja": 0.05, "fr": 0.045, "pt": 0.038,
        "ru": 0.035, "it": 0.027, "nl": 0.02, "pl": 0.017, "tr": 0.017, "fa": 0.014,
        "zh": 0.014, "ar": 0.013, "vi": 0.011, "ko": 0.008, "id": 0.007, "hi": 0.006,
    },
    "online_population": {
        "en": 0.253, "zh": 0.194, "es": 0.079, "ar": 0.052, "pt": 0.041, "id": 0.039,
        "fr": 0.036, "ja": 0.029, "ru": 0.029, "de": 0.021, "ko": 0.02, "hi": 0.019,
        "tr": 0.018, "it": 0.016, "vi": 0.013, "fa": 0.012, "bn": 0.011, "th": 0.01,
    },
}


def normalize_target(target: dict[str, float] | None) -> dict[str, float]:
    """A {lang: weight} map (weights need not sum to 1) → {lang: share} over the
    positive weights, summing to 1. Returns {} (= OFF) when nothing is positive.
    """
    clean: dict[str, float] = {}
    for k, v in (target or {}).items():
        try:
            w = float(v)
        except (TypeError, ValueError):
            continue
        key = str(k).strip().lower()
        if key and w > 0:
            clean[key] = clean.get(key, 0.0) + w
    total = sum(clean.values())
    if total <= 0:
        return {}
    return {k: w / total for k, w in clean.items()}


def language_pace(
    corpus_shares: dict[str, float],
    target_shares: dict[str, float] | None,
    *,
    floor: float = DEFAULT_FLOOR,
) -> dict[str, float]:
    """Per-language cadence multiplier in [floor, 1].

    1.0 = full cadence (a language at/under its target, or untargeted); < 1.0 =
    re-check less often (over-represented), scaled by how far over target it is
    and clamped at ``floor`` so it never fully stops. Empty target → {} (OFF).
    """
    target = normalize_target(target_shares)
    if not target:
        return {}
    floor = max(0.0, min(1.0, floor))
    pace: dict[str, float] = {}
    for lang, tshare in target.items():
        cshare = corpus_shares.get(lang, 0.0)
        if cshare <= tshare or cshare <= 0:
            pace[lang] = 1.0
        else:
            pace[lang] = max(floor, min(1.0, tshare / cshare))
    return pace


def corpus_language_shares(session: Session) -> dict[str, float]:
    """{lang: fraction} of stored articles by language (NULL → 'unknown')."""
    rows = (
        session.query(Article.language, func.count(Article.id))
        .group_by(Article.language)
        .all()
    )
    total = sum(n for _, n in rows)
    if not total:
        return {}
    out: dict[str, float] = {}
    for lang, n in rows:
        key = (lang or "unknown").strip().lower() or "unknown"
        out[key] = out.get(key, 0.0) + n / total
    return out


def equilibrium_filter(
    sources: list,
    *,
    pace: dict[str, float],
    fetch_state: dict,
    now: datetime | None = None,
    cap_seconds: int = DEFAULT_CAP_SECONDS,
    rng: random.Random | None = None,
) -> tuple[list, int]:
    """Defer over-represented languages' RE-CHECKS to later passes (never drop).

    Returns ``(kept, deferred_count)``. Empty ``pace`` → identity (OFF). A source
    is kept unconditionally when its language is at/under target, when it has
    never been fetched (first reach), or when its last fetch is older than the
    cap (the hard freshness floor). Otherwise it is kept with probability =
    ``pace[lang]`` and deferred to a later pass with probability (1 − pace).
    """
    if not pace:
        return list(sources), 0
    chooser = rng or random
    now = now or datetime.now(UTC)
    cap = timedelta(seconds=cap_seconds)
    kept: list = []
    deferred = 0
    for s in sources:
        lang = (getattr(s, "language", None) or "unknown").strip().lower() or "unknown"
        p = pace.get(lang, 1.0)
        if p >= 1.0:
            kept.append(s)
            continue
        st = fetch_state.get(getattr(s, "id", None))
        checked = getattr(st, "last_checked_at", None) if st else None
        if checked is not None and checked.tzinfo is None:
            checked = checked.replace(tzinfo=UTC)
        # Hard floor: never starve — a never-fetched or cap-stale source is kept.
        if checked is None or (now - checked) > cap:
            kept.append(s)
            continue
        if chooser.random() < p:
            kept.append(s)
        else:
            deferred += 1
    return kept, deferred
