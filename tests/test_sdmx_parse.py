"""
Offline tests for the official-statistics parser core (``src/stats/sdmx.py``).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure-data tests — small inline fixtures shaped like real World Bank API v2 JSON and
SDMX-JSON 2.1 "data message" responses (Eurostat/IMF). They assert the honesty rules of
Group N: a published gap → ``value=None`` (never dropped, never a fabricated 0); the
``extracted_at`` vintage is recorded verbatim per parse; comparability fields surface
only when the response exposes them; and NO figure ever carries a composite score.
"""

from __future__ import annotations

import re

from src.briefing.card import assert_no_score_fields
from src.stats.sdmx import StatFigure, parse_sdmx_json, parse_worldbank

_SCORE_RE = re.compile(r"score|credibility|reliability|quality|trust", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Fixtures (inline — World Bank API v2 JSON: [page_meta, [observations]]).
# --------------------------------------------------------------------------- #
def _worldbank_payload() -> list:
    page_meta = {"page": 1, "pages": 1, "per_page": 50, "total": 2}
    observations = [
        {
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
            "country": {"id": "FR", "value": "France"},
            "countryiso3code": "FRA",
            "date": "2021",
            "value": 2957879759277.0,
            "unit": "",
            "obs_status": "",
            "decimal": 0,
        },
        {
            # A PUBLISHED GAP — the cell exists but the value is null.
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
            "country": {"id": "FR", "value": "France"},
            "countryiso3code": "FRA",
            "date": "2020",
            "value": None,
            "unit": "",
            "obs_status": "",
            "decimal": 0,
        },
    ]
    return [page_meta, observations]


# --------------------------------------------------------------------------- #
# Fixtures (inline — SDMX-JSON 2.1 data message, Eurostat-shaped).
# 2 series dimensions (geo, na_item) + an ADJUSTMENT + a UNIT dim, 1 time dim.
# --------------------------------------------------------------------------- #
def _sdmx_payload_with_attrs() -> dict:
    return {
        "data": {
            "structure": {
                "dimensions": {
                    "series": [
                        {
                            "id": "geo",
                            "values": [{"id": "FR", "name": "France"},
                                       {"id": "DE", "name": "Germany"}],
                        },
                        {
                            "id": "na_item",
                            "values": [{"id": "B1GQ", "name": "Gross domestic product"}],
                        },
                        {
                            "id": "s_adj",
                            "values": [{"id": "SA", "name": "Seasonally adjusted"}],
                        },
                        {
                            "id": "unit",
                            "values": [{"id": "CP_MEUR",
                                        "name": "Current prices, million euro"}],
                        },
                    ],
                    "observation": [
                        {
                            "id": "TIME_PERIOD",
                            "values": [{"id": "2021-Q1", "name": "2021-Q1"},
                                       {"id": "2021-Q2", "name": "2021-Q2"}],
                        }
                    ],
                },
            },
            "dataSets": [
                {
                    "series": {
                        # FR, B1GQ, SA, CP_MEUR
                        "0:0:0:0": {
                            "observations": {
                                "0": [600000.0],   # 2021-Q1
                                "1": [610000.0],   # 2021-Q2
                            }
                        },
                        # DE, B1GQ, SA, CP_MEUR — with one GAP (null obs cell).
                        "1:0:0:0": {
                            "observations": {
                                "0": [850000.0],   # 2021-Q1
                                "1": [None],       # 2021-Q2 — published gap
                            }
                        },
                    }
                }
            ],
        }
    }


def _sdmx_payload_no_attrs() -> dict:
    """A minimal SDMX message with NO unit/adjustment dimensions — those fields must be
    None (never guessed)."""
    return {
        "data": {
            "structure": {
                "dimensions": {
                    "series": [
                        {"id": "ref_area", "values": [{"id": "EA19", "name": "Euro area"}]},
                        {"id": "indicator", "values": [{"id": "PRC_HICP", "name": "HICP"}]},
                    ],
                    "observation": [
                        {"id": "time", "values": [{"id": "2022-03"}]}
                    ],
                },
            },
            "dataSets": [
                {"series": {"0:0": {"observations": {"0": [109.4]}}}}
            ],
        }
    }


# --------------------------------------------------------------------------- #
# World Bank
# --------------------------------------------------------------------------- #
def test_worldbank_two_observations_one_gap() -> None:
    figs = parse_worldbank(_worldbank_payload(), agency="worldbank",
                           extracted_at="2026-06-16T12:00:00Z")
    assert len(figs) == 2

    first, gap = figs
    assert first.agency == "worldbank"
    assert first.series_id == "NY.GDP.MKTP.CD"
    assert first.ref_area == "FRA"  # countryiso3code preferred
    assert first.time_period == "2021"
    assert first.value == 2957879759277.0
    assert first.extracted_at == "2026-06-16T12:00:00Z"

    # The published gap: cell present, value None — NOT dropped, NOT fabricated to 0.
    assert gap.time_period == "2020"
    assert gap.value is None
    assert gap.extracted_at == "2026-06-16T12:00:00Z"

    # No comparability fields in this shape → all None (never guessed).
    for f in figs:
        assert f.methodology_ref is None
        assert f.adjustment is None
        assert f.base_year is None


def test_worldbank_falls_back_to_country_id_when_iso3_missing() -> None:
    payload = [
        {"page": 1},
        [
            {
                "indicator": {"id": "SP.POP.TOTL"},
                "country": {"id": "BR", "value": "Brazil"},
                # no countryiso3code → fall back to country.id
                "date": "2019",
                "value": 211049527.0,
            }
        ],
    ]
    figs = parse_worldbank(payload, agency="worldbank", extracted_at="2026-06-16T12:00:00Z")
    assert len(figs) == 1
    assert figs[0].ref_area == "BR"
    assert figs[0].series_id == "SP.POP.TOTL"


# --------------------------------------------------------------------------- #
# SDMX-JSON
# --------------------------------------------------------------------------- #
def test_sdmx_resolves_dims_and_keeps_gap_with_attrs() -> None:
    figs = parse_sdmx_json(_sdmx_payload_with_attrs(), agency="eurostat",
                           extracted_at="2026-06-16T12:00:00Z")
    # 2 series × 2 observations = 4 figures (gap included).
    assert len(figs) == 4

    by_key = {(f.ref_area, f.time_period): f for f in figs}
    assert set(by_key) == {("FR", "2021-Q1"), ("FR", "2021-Q2"),
                           ("DE", "2021-Q1"), ("DE", "2021-Q2")}

    fr_q1 = by_key[("FR", "2021-Q1")]
    assert fr_q1.agency == "eurostat"
    assert fr_q1.series_id == "B1GQ"          # resolved from the na_item series dim
    assert fr_q1.time_period == "2021-Q1"     # resolved from the TIME_PERIOD obs dim
    assert fr_q1.value == 600000.0
    assert fr_q1.adjustment == "SA"           # surfaced from s_adj dim
    assert fr_q1.unit == "Current prices, million euro"  # unit dim NAME
    assert fr_q1.extracted_at == "2026-06-16T12:00:00Z"

    de_q2 = by_key[("DE", "2021-Q2")]
    assert de_q2.value is None                # published gap kept, not dropped/zeroed
    assert de_q2.adjustment == "SA"           # provenance still attached to the gap row


def test_sdmx_absent_attrs_stay_none() -> None:
    figs = parse_sdmx_json(_sdmx_payload_no_attrs(), agency="eurostat",
                           extracted_at="2026-06-16T12:00:00Z")
    assert len(figs) == 1
    fig = figs[0]
    assert fig.ref_area == "EA19"
    assert fig.series_id == "PRC_HICP"
    assert fig.time_period == "2022-03"
    assert fig.value == 109.4
    # No UNIT / ADJUSTMENT / base-year dimension → these MUST be None (never guessed).
    assert fig.unit is None
    assert fig.adjustment is None
    assert fig.base_year is None
    assert fig.methodology_ref is None


def test_sdmx_base_year_only_when_label_states_it() -> None:
    payload = {
        "data": {
            "structure": {
                "dimensions": {
                    "series": [
                        {"id": "geo", "values": [{"id": "FR", "name": "France"}]},
                        {"id": "indicator", "values": [{"id": "PROD", "name": "Production"}]},
                        {"id": "unit",
                         "values": [{"id": "I15", "name": "Index, 2015=100"}]},
                    ],
                    "observation": [{"id": "time", "values": [{"id": "2023"}]}],
                },
            },
            "dataSets": [{"series": {"0:0:0": {"observations": {"0": [104.2]}}}}],
        }
    }
    figs = parse_sdmx_json(payload, agency="eurostat", extracted_at="2026-06-16T12:00:00Z")
    assert len(figs) == 1
    assert figs[0].base_year == "2015"  # literally stated in the unit label
    assert figs[0].unit == "Index, 2015=100"


# --------------------------------------------------------------------------- #
# Honesty: no composite score on ANY figure.
# --------------------------------------------------------------------------- #
def test_statfigure_dataclass_declares_no_score_field() -> None:
    # assert_no_score_fields operates on a dataclass class (dataclasses.fields(cls)).
    # It raises CardSchemaError if any field implies a composite score — must pass clean.
    assert_no_score_fields(StatFigure)


def test_no_figure_to_dict_carries_a_score_key() -> None:
    figs = (
        parse_worldbank(_worldbank_payload(), agency="worldbank",
                        extracted_at="2026-06-16T12:00:00Z")
        + parse_sdmx_json(_sdmx_payload_with_attrs(), agency="eurostat",
                          extracted_at="2026-06-16T12:00:00Z")
    )
    assert figs  # sanity: we actually produced figures to check
    for f in figs:
        d = f.to_dict()
        for key in d:
            assert not _SCORE_RE.search(key), f"forbidden score-like key: {key!r}"


# --------------------------------------------------------------------------- #
# Vintage: extracted_at is caller-stamped, never overwritten.
# --------------------------------------------------------------------------- #
def test_vintage_is_caller_stamped_per_parse_worldbank() -> None:
    payload = _worldbank_payload()
    v1 = parse_worldbank(payload, agency="worldbank", extracted_at="2026-01-01T00:00:00Z")
    v2 = parse_worldbank(payload, agency="worldbank", extracted_at="2026-06-16T12:00:00Z")
    assert [f.extracted_at for f in v1] == ["2026-01-01T00:00:00Z"] * len(v1)
    assert [f.extracted_at for f in v2] == ["2026-06-16T12:00:00Z"] * len(v2)
    # Same payload, two vintages — never overwritten.
    assert v1[0].extracted_at != v2[0].extracted_at
    # The observed values themselves are identical across vintages.
    assert [f.value for f in v1] == [f.value for f in v2]


def test_vintage_is_caller_stamped_per_parse_sdmx() -> None:
    payload = _sdmx_payload_with_attrs()
    v1 = parse_sdmx_json(payload, agency="eurostat", extracted_at="2026-01-01T00:00:00Z")
    v2 = parse_sdmx_json(payload, agency="eurostat", extracted_at="2026-06-16T12:00:00Z")
    assert all(f.extracted_at == "2026-01-01T00:00:00Z" for f in v1)
    assert all(f.extracted_at == "2026-06-16T12:00:00Z" for f in v2)
    assert v1[0].extracted_at != v2[0].extracted_at


# --------------------------------------------------------------------------- #
#  The real page-1 shape, read off the live API on 2026-08-07
# --------------------------------------------------------------------------- #


def _obs(cid, iso3, name, year, value):
    """One observation in the exact shape the live response returns."""
    return {
        "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
        "country": {"id": cid, "value": name},
        "countryiso3code": iso3,
        "date": str(year),
        "value": value,
        "unit": "", "obs_status": "", "decimal": 0,
    }


def test_contiguous_per_economy_blocks_do_not_collapse_to_one_area():
    """A networked pass warned that fixing pagination could turn a '15 -> 1' collapse
    into '265 -> 1', if something downstream keyed rows without the economy.

    Page 1 is NOT interleaved: it is contiguous blocks of 66 rows, one economy each,
    years descending with gaps present as null rows. This drives that exact shape and
    asserts every economy survives as its own ref_area -- the parser is not the collapse.
    """
    payload = [
        {"page": 1, "pages": 18, "per_page": 1000, "total": 17490,
         "sourceid": "2", "lastupdated": "2026-07-13"},
        [
            *(_obs("ZH", "AFE", "Africa Eastern and Southern", y, 1.0) for y in (2025, 2024, 2023)),
            *(_obs("ZI", "AFW", "Africa Western and Central", y, 2.0) for y in (2025, 2024, 2023)),
            *(_obs("1A", "ARB", "Arab World", y, 3.0) for y in (2025, 2024, 2023)),
        ],
    ]
    figs = parse_worldbank(payload, agency="worldbank", extracted_at="2026-08-07T00:00:00Z")
    assert len({f.ref_area for f in figs}) == 3, "each block must keep its own area"
    assert {f.ref_area for f in figs} == {"AFE", "AFW", "ARB"}
    assert len(figs) == 9


def test_an_aggregate_row_carries_its_own_alpha3_not_an_empty_code():
    """The brief assumed `countryiso3code` is empty for aggregates. It is not -- verified
    2026-08-07 -- so nothing in an indicator response distinguishes a country from an
    aggregate, and any ingest inferring that from an empty code classifies every
    aggregate as a country. This pins the real shape so the assumption cannot creep back.
    """
    payload = [{"page": 1, "pages": 1, "per_page": 50, "total": 1},
               [_obs("ZH", "AFE", "Africa Eastern and Southern", 2023, 1.0)]]
    fig = parse_worldbank(payload, agency="worldbank", extracted_at="2026-08-07T00:00:00Z")[0]
    assert fig.ref_area == "AFE", "the aggregate's own alpha-3, not '' and not 'ZH'"


def test_a_missing_year_is_a_null_row_not_an_absent_one():
    """Each block is a full 66 rows; a year with no observation is present with
    `value: null`. Treating row count as coverage would therefore overcount every time."""
    payload = [{"page": 1, "pages": 1, "per_page": 50, "total": 2},
               [_obs("FR", "FRA", "France", 2023, 3.0e12), _obs("FR", "FRA", "France", 2022, None)]]
    figs = parse_worldbank(payload, agency="worldbank", extracted_at="2026-08-07T00:00:00Z")
    assert len(figs) == 2
    assert [f.value for f in figs] == [3.0e12, None], "a gap is stored as None, never 0"


# --------------------------------------------------------------------------- #
# SDMX-JSON: an unmapped message must read as a GAP, never as anonymous rows.
#
# Found by following up the 2026-08-13 internet session's correction that "SDMX-JSON 2.1"
# names a version that does not exist. Chasing which contract the parser really implements
# turned up something worse than a wrong docstring.
# --------------------------------------------------------------------------- #


def _obs_dims(*dims: dict) -> dict:
    """A data message whose observation dimensions are `dims` and whose series map is flat."""
    return {
        "data": {
            "structure": {"dimensions": {"series": [], "observation": list(dims)}},
            "dataSets": [{"series": {"": {"observations": {"0:0": [42.0]}}}}],
        }
    }


def test_an_unmapped_message_shape_yields_no_rows_rather_than_a_value_with_no_identity():
    """The defect: a 2.0 message carries `data.structures` as a plural ARRAY, which this
    parser does not read, so every dimension resolved to nothing — and the row was appended
    anyway with `ref_area or ""`. The result was a REAL number (2.957e12) with no country,
    no indicator and no year: not a gap, not zero, but a figure no reader could tell was
    wrong. Dropping it is the only honest answer available without a fetched 2.0 body."""
    v20 = {
        "data": {
            "structures": [
                {
                    "dimensions": {
                        "series": [{"id": "REF_AREA", "values": [{"id": "FR"}]}],
                        "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2021"}]}],
                    }
                }
            ],
            "dataSets": [{"series": {"0": {"observations": {"0": [2957000000000.0]}}}}],
        }
    }
    assert parse_sdmx_json(v20, agency="oecd", extracted_at="2026-08-13") == []


def test_a_mapped_message_still_parses_its_real_identity():
    """The negative-space twin. An over-eager refusal would delete real data while looking
    conservative, and only this direction catches it."""
    v10 = {
        "data": {
            "structure": {
                "dimensions": {
                    "series": [
                        {"id": "REF_AREA", "values": [{"id": "FR"}]},
                        {"id": "INDICATOR", "values": [{"id": "GDP"}]},
                    ],
                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2021"}]}],
                }
            },
            "dataSets": [{"series": {"0:0": {"observations": {"0": [2957000000000.0]}}}}],
        }
    }
    rows = parse_sdmx_json(v10, agency="eurostat", extracted_at="2026-08-13")
    assert [(r.ref_area, r.series_id, r.time_period, r.value) for r in rows] == [
        ("FR", "GDP", "2021", 2957000000000.0)
    ]


def test_ref_area_is_read_at_observation_level_too_for_dimensionAtObservation_all():
    """Which LEVEL a dimension sits at is decided by the request's `dimensionAtObservation`,
    not by the concept — and OECD's own documented example passes `AllDimensions`, which puts
    every dimension at observation level. Reading ref_area from the series map alone left it
    empty for a well-formed message, so this mode produced identity-less rows before the
    refusal and would produce an empty answer after it. The parser already resolved
    unit/adjustment at both levels; this is the same idiom applied to where and when."""
    msg = _obs_dims(
        {"id": "REF_AREA", "values": [{"id": "DE"}, {"id": "FR"}]},
        {"id": "TIME_PERIOD", "values": [{"id": "2020"}, {"id": "2021"}]},
    )
    msg["data"]["dataSets"][0]["series"][""]["observations"] = {"0:0": [42.0], "1:1": [43.0]}
    rows = parse_sdmx_json(msg, agency="oecd", extracted_at="2026-08-13")
    assert [(r.ref_area, r.time_period, r.value) for r in rows] == [
        ("DE", "2020", 42.0),
        ("FR", "2021", 43.0),
    ]


def test_a_value_with_a_place_but_no_period_is_refused():
    """Both halves are required. A figure needs a where AND a when; a value with only one of
    them cannot be attached to anything, so it is not a partial figure — it is not a figure."""
    msg = _obs_dims({"id": "REF_AREA", "values": [{"id": "DE"}, {"id": "IT"}]})
    assert parse_sdmx_json(msg, agency="oecd", extracted_at="2026-08-13") == []


def test_no_docstring_claims_the_nonexistent_sdmx_json_2_1_version():
    """SDMX-JSON MESSAGE-FORMAT versions are 1.0 and 2.0; 2.0/2.1/3.0 version the SDMX
    INFORMATION MODEL. "SDMX-JSON 2.1" conflates the two, so a reader could not tell which
    contract the parser implements and "written against 2.1" was unanswerable rather than
    merely wrong. Read comment-stripped-of-nothing on purpose: the correction note below is
    allowed to quote the bad string, so the guard is scoped to the parser's own docstring."""
    import inspect

    from src.stats import sdmx

    body = inspect.getdoc(sdmx.parse_sdmx_json) or ""
    assert "SDMX-JSON 2.1" not in body
    assert "SDMX-JSON 1.0" in body, "state which contract IS implemented, not merely which is not"
