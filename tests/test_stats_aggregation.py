"""Aggregating an indicator across a group refuses more than it computes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field feedback 2026-08-07, rulings 43/44/47. Most of what matters here is the NEGATIVE
space: a summed percentage, a bloc figure over the members that happened to report, a
weighted mean that quietly became unweighted because one weight was missing. Each of
those produces a plausible number, and a test that only checks the happy path passes
over every one of them — so each is driven here in both directions, because a refusal
that also fires on a legitimate input is its own fabrication.
"""

from __future__ import annotations

import pytest

from src.stats.aggregate import STRATEGIES, Member, aggregate_indicator
from src.stats.indicators import (
    AGGREGATION,
    INDICATOR_CATALOG,
    indicator_aggregation,
    indicator_ids,
    indicator_meta,
)

# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #


def _agg(code: str, members, weights=None, allow_incomplete: bool = False) -> dict:
    return aggregate_indicator(
        indicator=indicator_meta(code),
        aggregation=indicator_aggregation(code),
        members=members,
        weights=weights,
        allow_incomplete=allow_incomplete,
    )


def _walk_keys(obj) -> list[str]:
    """Every dict KEY anywhere in the payload — the no-score guard walks names."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_walk_keys(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_walk_keys(v))
    return out


# --------------------------------------------------------------------------- #
#  The declaration table
# --------------------------------------------------------------------------- #


def test_every_curated_indicator_declares_how_it_may_be_aggregated():
    """No silent default. Forgetting must be visible, not resolved to a guess."""
    missing = [code for code in indicator_ids() if code not in AGGREGATION]
    assert not missing, f"no aggregation declaration for: {missing}"
    orphan = [code for code in AGGREGATION if code not in set(indicator_ids())]
    assert not orphan, f"declaration for a code no longer in the catalog: {orphan}"


def test_an_undeclared_code_raises_rather_than_defaulting():
    """A default would decide, for whatever was forgotten, either that a percentage may
    be summed or that a real total may not be. Both reach a reader as a figure."""
    with pytest.raises(KeyError, match="aggregation declaration"):
        indicator_aggregation("NOT.A.REAL.CODE")


def test_only_true_levels_are_summable():
    """The rail itself. Anything measured as a share, rate, index or per-capita value is
    intensive, whatever its unit string happens to say."""
    extensive = {c for c in indicator_ids() if indicator_aggregation(c)["extensive"]}
    assert extensive == {
        "NY.GDP.MKTP.CD",
        "NY.GDP.MKTP.PP.CD",
        "SP.POP.TOTL",
        "SL.TLF.TOTL.IN",
    }, extensive
    # And the classification is not a unit-string heuristic in disguise: every
    # percentage-unit series must be intensive, but the reverse does not hold --
    # "years", "index" and "t/capita" are intensive too.
    for ind in INDICATOR_CATALOG:
        if ind["unit"] == "%":
            assert not indicator_aggregation(ind["id"])["extensive"], ind["id"]


def test_a_declared_denominator_names_a_series_we_actually_hold():
    for code in indicator_ids():
        a = indicator_aggregation(code)
        if a["denominator"]:
            assert a["weight_series"], (
                f"{code} declares denominator {a['denominator']!r} but no weight series "
                "resolves for it -- then the 'exact' claim can never be honoured"
            )


# --------------------------------------------------------------------------- #
#  Summing
# --------------------------------------------------------------------------- #


def test_an_intensive_indicator_refuses_to_be_summed():
    out = _agg("SP.DYN.LE00.IN", [Member("fr", 82.0), Member("de", 81.0)])
    s = out["strategies"]["sum"]
    assert "value" not in s
    assert "not a statistic at all" in s["refused"]


def test_an_extensive_indicator_sums():
    out = _agg("SP.POP.TOTL", [Member("fr", 68.0), Member("de", 84.0)])
    assert out["strategies"]["sum"]["value"] == pytest.approx(152.0)
    assert out["strategies"]["sum"]["basis"] == "exact"


def test_the_refusal_is_absent_not_a_null_value():
    """Ruling 47: refused, not offered greyed out. A None value renders as a blank cell
    and reads as 'no data', which is a different and false claim."""
    s = _agg("NE.TRD.GNFS.ZS", [Member("fr", 60.0)])["strategies"]["sum"]
    assert s.get("value", "absent") == "absent"
    assert s["refused"]


# --------------------------------------------------------------------------- #
#  Coverage
# --------------------------------------------------------------------------- #


def test_incomplete_coverage_refuses_by_default():
    out = _agg("SP.POP.TOTL", [Member("fr", 68.0), Member("de", 84.0), Member("it", None)])
    assert out["coverage"]["complete"] is False
    assert out["coverage"]["missing"] == ["it"]
    for key, res in out["strategies"].items():
        assert "value" not in res, f"{key} computed over incomplete coverage"
        assert "it" in res["refused"]


def test_the_override_computes_and_the_missing_members_ride_in_the_payload():
    """Ruling 44 is explicit that the missing members must not live only in the UI --
    the payload is what gets exported, pasted and quoted."""
    out = _agg(
        "SP.POP.TOTL",
        [Member("fr", 68.0), Member("de", 84.0), Member("it", None)],
        allow_incomplete=True,
    )
    assert out["strategies"]["sum"]["value"] == pytest.approx(152.0)
    assert out["coverage"]["missing"] == ["it"]
    assert out["coverage"]["reported"] == 2 and out["coverage"]["members"] == 3
    assert out["strategies"]["sum"]["basis"] == "approximate"
    assert "PARTIAL" in out["strategies"]["sum"]["method"]
    # Every strategy degrades, not just the total: the mean over the members that
    # reported is exact arithmetic but it is NOT the group's mean, and "exact" beside a
    # partial figure is the claim a reader would act on.
    for key in ("mean", "median"):
        assert out["strategies"][key]["basis"] == "approximate", key


def test_complete_coverage_is_not_flagged_partial():
    """The negative-space twin: an over-eager warning trains readers to ignore it."""
    out = _agg("SP.POP.TOTL", [Member("fr", 68.0), Member("de", 84.0)])
    assert out["coverage"]["complete"] is True
    assert out["coverage"]["missing"] == []
    assert "PARTIAL" not in out["strategies"]["sum"]["method"]
    assert out["strategies"]["sum"]["basis"] == "exact"


def test_no_member_reporting_is_a_gap_not_a_zero():
    out = _agg("SP.POP.TOTL", [Member("fr", None), Member("de", None)])
    for res in out["strategies"].values():
        assert "value" not in res
        assert "not a zero" in res["refused"]


# --------------------------------------------------------------------------- #
#  Weighting
# --------------------------------------------------------------------------- #


def test_a_population_weighted_per_capita_mean_IS_the_true_aggregate():
    """The identity that makes 'exact' an honest word: with the numerator reconstructed
    as value x population, the weighted mean equals total GDP over total population."""
    pop = {"fr": 68.0, "de": 84.0, "lu": 0.66}
    gdp_pc = {"fr": 44_000.0, "de": 52_000.0, "lu": 128_000.0}
    out = _agg(
        "NY.GDP.PCAP.CD",
        [Member(a, gdp_pc[a]) for a in pop],
        weights={"population": pop},
    )
    w = out["strategies"]["population_weighted"]
    expected = sum(gdp_pc[a] * pop[a] for a in pop) / sum(pop.values())
    assert w["value"] == pytest.approx(expected)
    assert w["basis"] == "exact"
    assert "true figure, not an estimate" in w["method"]
    # ...and it is genuinely different from the unweighted mean, which is the whole
    # reason both are shown: Luxembourg counts once there and barely at all here.
    assert out["strategies"]["mean"]["value"] != pytest.approx(w["value"])


def test_weighting_by_the_wrong_denominator_is_reported_as_approximate():
    """GDP-weighting a per-capita series is defined arithmetic and a different question.
    It is offered, and it says which it is."""
    out = _agg(
        "NY.GDP.PCAP.CD",
        [Member("fr", 44_000.0), Member("de", 52_000.0)],
        weights={"population": {"fr": 68.0, "de": 84.0}, "gdp": {"fr": 3.0, "de": 4.4}},
    )
    assert out["strategies"]["population_weighted"]["basis"] == "exact"
    gdpw = out["strategies"]["gdp_weighted"]
    assert gdpw["basis"] == "approximate"
    assert "APPROXIMATE" in gdpw["method"] and "per population" in gdpw["method"]


def test_unemployment_is_exact_on_labour_force_not_on_population():
    """Declared per LABOUR FORCE, and we hold that series -- so the exact weighting is
    the one a population-weighted default would have quietly got wrong."""
    out = _agg(
        "SL.UEM.TOTL.ZS",
        [Member("fr", 7.5), Member("de", 3.2)],
        weights={
            "labour_force": {"fr": 30.0, "de": 43.0},
            "population": {"fr": 68.0, "de": 84.0},
        },
    )
    assert out["strategies"]["labour_force_weighted"]["basis"] == "exact"
    assert out["strategies"]["population_weighted"]["basis"] == "approximate"


def test_a_missing_weight_refuses_and_never_falls_back_to_unweighted():
    """THE trap. Falling back answers a different question under the same label, and the
    number that comes out is perfectly plausible."""
    out = _agg(
        "NY.GDP.PCAP.CD",
        [Member("fr", 44_000.0), Member("de", 52_000.0)],
        weights={"population": {"fr": 68.0, "de": None}},
    )
    w = out["strategies"]["population_weighted"]
    assert "value" not in w
    assert "de" in w["refused"] and "unweighted" in w["refused"]
    # The unweighted mean is still offered under its OWN name -- refusing one strategy
    # must not withdraw the others.
    assert out["strategies"]["mean"]["value"] == pytest.approx(48_000.0)


def test_an_absent_weight_series_refuses_rather_than_silently_degrading():
    out = _agg("NY.GDP.PCAP.CD", [Member("fr", 44_000.0)], weights={})
    w = out["strategies"]["population_weighted"]
    assert "value" not in w
    assert "not falling back" in w["refused"].lower()


# --------------------------------------------------------------------------- #
#  The series that cannot be pooled at all
# --------------------------------------------------------------------------- #


def test_the_gini_index_refuses_every_strategy_with_the_reason():
    out = _agg("SI.POV.GINI", [Member("fr", 31.0), Member("de", 32.0), Member("za", 63.0)])
    assert set(out["strategies"]) == {key for key, _label, _weight in STRATEGIES}
    for key, res in out["strategies"].items():
        assert "value" not in res, key
        assert "BETWEEN" in res["refused"]
    assert out["default_strategy"] is None


def test_a_pooled_gini_would_have_been_biased_low_which_is_why_it_is_refused():
    """Not merely imprecise: the mean of per-country Ginis discards between-country
    inequality, so it understates in a direction the reader cannot see. This pins the
    reasoning next to the refusal so a later session does not 'enable' it."""
    reason = indicator_aggregation("SI.POV.GINI")["no_aggregate"]
    assert "biased low" in reason and "micro-data" in reason


# --------------------------------------------------------------------------- #
#  Spread, defaults, and the no-score guard
# --------------------------------------------------------------------------- #


def test_the_spread_travels_with_every_central_figure():
    out = _agg(
        "SP.DYN.LE00.IN",
        [Member("ng", 54.0), Member("sc", 74.0), Member("za", 62.0)],
        weights={"population": {"ng": 220.0, "sc": 0.1, "za": 60.0}},
    )
    sp = out["spread"]
    assert sp == {"n": 3, "min": 54.0, "max": 74.0, "min_area": "ng", "max_area": "sc"}


def test_the_default_is_a_view_not_a_winner():
    """Extensive opens on its total; intensive opens on an EXACT weighting when one
    exists, and otherwise on the plain member mean rather than an approximation dressed
    as the answer."""
    tot = _agg("SP.POP.TOTL", [Member("fr", 68.0)])
    assert tot["default_strategy"] == "sum"

    exact = _agg(
        "NY.GDP.PCAP.CD", [Member("fr", 44_000.0)], weights={"population": {"fr": 68.0}}
    )
    assert exact["default_strategy"] == "population_weighted"

    # Life expectancy has no exact weighting -- do not open on the approximation.
    approx = _agg(
        "SP.DYN.LE00.IN", [Member("fr", 82.0)], weights={"population": {"fr": 68.0}}
    )
    assert approx["strategies"]["population_weighted"]["basis"] == "approximate"
    assert approx["default_strategy"] == "mean"


def test_the_payload_names_no_score_ranking_or_grade():
    out = _agg(
        "NY.GDP.PCAP.CD",
        [Member("fr", 44_000.0), Member("de", 52_000.0)],
        weights={"population": {"fr": 68.0, "de": 84.0}},
    )
    banned = ("score", "ranking", "rating", "grade")
    bad = [k for k in _walk_keys(out) if any(b in k.lower() for b in banned)]
    assert not bad, bad


def test_a_single_member_group_is_honest_about_being_one_member():
    out = _agg("SP.POP.TOTL", [Member("fr", 68.0)])
    assert out["spread"]["n"] == 1
    assert out["spread"]["min"] == out["spread"]["max"] == 68.0
    assert out["strategies"]["mean"]["value"] == pytest.approx(68.0)


def test_an_empty_group_refuses_instead_of_returning_zero():
    out = _agg("SP.POP.TOTL", [])
    assert out["coverage"] == {"members": 0, "reported": 0, "missing": [], "complete": False}
    assert out["spread"]["n"] == 0
    for res in out["strategies"].values():
        assert "value" not in res
