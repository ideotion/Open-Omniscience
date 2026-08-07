"""Aggregating one indicator across a group of countries — several ways, side by side.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field feedback 2026-08-07, rulings 43/44/47. The ask was NOT "compute the bloc figure":
it was to offer SEVERAL strategies at once so a reader can compare them and form their
own view. That framing is doing real work, because the strategies genuinely disagree and
the disagreement is the information. An unweighted mean of life expectancy across Africa
counts Seychelles and Nigeria equally — a true statement about COUNTRIES; the
population-weighted mean is a true statement about PEOPLE; they can differ by years. A
single headline picks one silently. This module refuses to.

WHAT IT REFUSES, and why refusing beats a caveat:

* **Summing an intensive value.** Ruling 47's rail. Adding percentages produces a number
  with no referent at all, so it is not offered greyed-out with a warning — it is absent,
  with the reason in its place. ``extensive`` is DECLARED per indicator in
  ``src/stats/indicators.AGGREGATION``, never sniffed from the unit string.
* **A series that cannot be pooled at all.** Currently only the Gini index; the reason
  travels with the refusal rather than living in a comment here.
* **Incomplete coverage, by default.** A bloc figure computed over the members that
  happen to have reported is not the bloc's figure, and nothing downstream can tell the
  difference. The caller may override, and then the missing members ride IN THE PAYLOAD —
  ruling 44 is explicit that they must not live only in the UI, because the payload is
  what gets exported, pasted and quoted.
* **A weighted mean with a missing weight.** Falling back to unweighted here would answer
  a different question under the same label. It is a coverage failure and reported as one.

EXACT vs APPROXIMATE is the other half. For a per-capita series,
``Σ(value × population) / Σ(population)`` reconstructs the real numerator, so the
population-weighted mean IS the aggregate — not an estimate of it. Weight the same series
by GDP, or weight a per-live-birth series by population, and the answer is an
approximation. The engine knows which it just computed and says so per strategy, because
"weighted mean" alone does not distinguish an identity from a guess.

Every result carries the SPREAD (min / max / n, with the areas at each end). Ruling 47's
corollary: a bloc headline hiding a ten-fold range is technically true and practically
misleading, so the range is not optional decoration.

No score, no ranking, no composite: the strategies are never blended and never ordered by
preference. ``default_strategy`` names a starting VIEW, not a winner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import median as _median

__all__ = [
    "STRATEGIES",
    "Member",
    "aggregate_indicator",
]


@dataclass(frozen=True)
class Member:
    """One group member's reported value for the indicator being aggregated.

    ``value is None`` is a published GAP, never a zero — it is what makes coverage
    incomplete, and it is counted rather than dropped.
    """

    area: str
    value: float | None = None


#: key -> (label, needs_weight). Order is presentation order, NOT preference.
STRATEGIES: tuple[tuple[str, str, str | None], ...] = (
    ("sum", "Total", None),
    ("mean", "Mean of members", None),
    ("median", "Median member", None),
    ("population_weighted", "Population-weighted mean", "population"),
    ("gdp_weighted", "GDP-weighted mean", "gdp"),
    ("labour_force_weighted", "Labour-force-weighted mean", "labour_force"),
)

_MEMBERS_METHOD = (
    "Each member counts once, whatever its size — a statement about COUNTRIES, not about "
    "people."
)


def _spread(reported: Sequence[Member]) -> dict:
    """min / max / n, with the area at each end. Never a variance-free headline."""
    if not reported:
        return {"n": 0, "min": None, "max": None, "min_area": None, "max_area": None}
    lo = min(reported, key=lambda m: m.value)  # type: ignore[arg-type,return-value]
    hi = max(reported, key=lambda m: m.value)  # type: ignore[arg-type,return-value]
    return {
        "n": len(reported),
        "min": lo.value,
        "max": hi.value,
        "min_area": lo.area,
        "max_area": hi.area,
    }


def _weighted(
    reported: Sequence[Member],
    weights: Mapping[str, float | None],
) -> tuple[float | None, list[str]]:
    """``Σ(v·w)/Σ(w)``, or ``None`` naming the members whose weight is missing.

    A member that reported a VALUE but has no weight cannot be carried by this strategy.
    Dropping it silently would compute a real number over a different membership than the
    label claims, so the missing set comes back instead and the caller refuses.
    """
    missing = [m.area for m in reported if weights.get(m.area) is None]
    if missing:
        return None, sorted(missing)
    num = 0.0
    den = 0.0
    for m in reported:
        w = float(weights[m.area])  # type: ignore[arg-type]
        num += float(m.value) * w  # type: ignore[arg-type]
        den += w
    if den == 0:
        return None, []
    return num / den, []


def aggregate_indicator(
    *,
    indicator: Mapping,
    aggregation: Mapping,
    members: Sequence[Member],
    weights: Mapping[str, Mapping[str, float | None]] | None = None,
    allow_incomplete: bool = False,
) -> dict:
    """Every honest way to aggregate one indicator over one group, computed side by side.

    ``indicator`` is the catalog entry (``id`` / ``label`` / ``unit``); ``aggregation`` is
    ``indicators.indicator_aggregation(code)``; ``members`` is EVERY member of the group,
    including those with no reported value — that is what makes coverage measurable rather
    than assumed. ``weights`` maps a weight name (``population`` / ``gdp`` /
    ``labour_force``) to that series' value per area.

    Returns one entry per strategy, each carrying either a ``value`` with its ``method``
    and ``basis`` (``exact`` | ``approximate``), or a ``refused`` sentence in its place.
    Nothing here is ranked and nothing is blended.
    """
    weights = weights or {}
    unit = indicator.get("unit")
    extensive = bool(aggregation.get("extensive"))
    denominator = aggregation.get("denominator")
    no_aggregate = aggregation.get("no_aggregate")

    reported = [m for m in members if m.value is not None]
    #: The same values as concrete floats — `Member.value` is `float | None`, and every
    #: use below is inside the `reported` filter, which a type checker cannot see.
    values: list[float] = [float(m.value) for m in members if m.value is not None]
    missing_value = sorted(m.area for m in members if m.value is None)
    complete = not missing_value and bool(members)

    coverage = {
        "members": len(members),
        "reported": len(reported),
        "missing": missing_value,
        "complete": complete,
    }
    spread = _spread(reported)

    def _out(results: dict) -> dict:
        return {
            "indicator": indicator.get("id"),
            "label": indicator.get("label"),
            "unit": unit,
            "extensive": extensive,
            "denominator": denominator,
            "coverage": coverage,
            "spread": spread,
            "strategies": results,
            # A starting VIEW, not a verdict. None where nothing is computable.
            "default_strategy": _default_strategy(results, extensive),
            "caveat": (
                "Strategies are shown side by side and never blended: they answer "
                "different questions and can legitimately disagree. A mean over members "
                "weighs a small country like a large one; a weighted mean weighs people "
                "(or output) instead. Each figure states its own method."
            ),
        }

    # --- the whole-series refusals, before any arithmetic ------------------- #
    if no_aggregate:
        return _out({k: {"refused": no_aggregate} for k, _label, _w in STRATEGIES})

    if not reported:
        gap = (
            "No member reported a value for this indicator and period, so there is "
            "nothing to aggregate. This is a published gap, not a zero."
        )
        return _out({k: {"refused": gap} for k, _label, _w in STRATEGIES})

    if not complete and not allow_incomplete:
        shown = ", ".join(missing_value[:8]) + ("…" if len(missing_value) > 8 else "")
        refusal = (
            f"{len(missing_value)} of {len(members)} members did not report this "
            f"indicator for this period ({shown}). A figure over the members that "
            "happen to have reported is not the group's figure, and nothing downstream "
            "could tell the difference. Re-request with allow_incomplete to compute it "
            "anyway — the missing members travel with the result."
        )
        return _out({k: {"refused": refusal} for k, _label, _w in STRATEGIES})

    # --- the strategies ----------------------------------------------------- #
    partial = "" if complete else (
        f" PARTIAL: computed over {len(reported)} of {len(members)} members; "
        f"{len(missing_value)} did not report."
    )
    results: dict[str, dict] = {}

    for key, label, weight_name in STRATEGIES:
        if key == "sum":
            if not extensive:
                results[key] = {
                    "label": label,
                    "refused": (
                        "This indicator is intensive — a rate, share, index or "
                        "per-capita value — so its members' values do not add up to "
                        "anything. A summed percentage is not a large percentage; it is "
                        "not a statistic at all."
                    ),
                }
                continue
            results[key] = {
                "label": label,
                "value": sum(values),
                "basis": "exact" if complete else "approximate",
                "method": "The members' reported values, added." + partial,
            }
            continue

        if key == "mean":
            results[key] = {
                "label": label,
                "value": sum(values) / len(values),
                # Exact arithmetic over the members present, but under partial coverage
                # it is not the GROUP's mean -- same reason the total degrades.
                "basis": "exact" if complete else "approximate",
                "method": _MEMBERS_METHOD + partial,
            }
            continue

        if key == "median":
            results[key] = {
                "label": label,
                "value": float(_median(values)),
                "basis": "exact" if complete else "approximate",
                "method": (
                    "The middle member value; unlike the mean it is not moved by one "
                    "extreme member." + partial
                ),
            }
            continue

        # --- weighted means ------------------------------------------------- #
        if weight_name is None:  # pragma: no cover - the branches above are exhaustive
            continue
        human = weight_name.replace("_", " ")
        series = weights.get(weight_name)
        if not series:
            results[key] = {
                "label": label,
                "refused": (
                    f"The {human} series is not held for this "
                    "group and period, so this weighting cannot be computed. It is not "
                    "falling back to an unweighted mean, which would answer a different "
                    "question under the same label."
                ),
            }
            continue

        value, missing_weight = _weighted(reported, series)
        if missing_weight:
            shown = ", ".join(missing_weight[:8]) + ("…" if len(missing_weight) > 8 else "")
            results[key] = {
                "label": label,
                "refused": (
                    f"{len(missing_weight)} member(s) reported a value but have no "
                    f"{human} weight ({shown}). Dropping them "
                    "would compute over a different membership than the label claims, "
                    "and weighting them as unweighted would silently mix two methods."
                ),
            }
            continue
        if value is None:
            results[key] = {
                "label": label,
                "refused": (
                    f"The {human} weights sum to zero for this "
                    "group, so a weighted mean is undefined."
                ),
            }
            continue

        exact = denominator is not None and denominator == weight_name
        results[key] = {
            "label": label,
            "value": value,
            "basis": "exact" if (exact and complete) else "approximate",
            "method": (
                (
                    f"Sum of (value x {human}) divided by the "
                    f"summed {human}. This indicator is measured "
                    f"PER {human}, so the reconstructed numerator "
                    "is the real one and this is the group's true figure, not an estimate."
                )
                if exact
                else (
                    f"Sum of (value x {human}) divided by the "
                    f"summed {human}. APPROXIMATE: this indicator "
                    + (
                        f"is measured per {denominator.replace('_', ' ')}, not per "
                        f"{human}"
                        if denominator
                        else "is not measured per a quantity this app holds a series for"
                    )
                    + ", so the reconstructed numerator is not the real one."
                )
            )
            + partial,
        }

    return _out(results)


def _default_strategy(results: Mapping[str, Mapping], extensive: bool) -> str | None:
    """A starting VIEW — the first computable strategy in a fixed, stated order.

    Deliberately not "the best": an extensive series opens on its total because that is
    the quantity it denotes, and an intensive one opens on the weighted mean that is
    EXACT if there is one. Where nothing is exact it opens on the plain member mean rather
    than on an approximation dressed as an answer.
    """
    def ok(key: str) -> bool:
        r = results.get(key) or {}
        return "value" in r and r.get("value") is not None

    order = (
        ["sum"] if extensive else
        [k for k in ("population_weighted", "gdp_weighted", "labour_force_weighted")
         if (results.get(k) or {}).get("basis") == "exact"]
    )
    for key in [*order, "mean", "median"]:
        if ok(key):
            return key
    return None
