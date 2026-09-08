"""The NOAA CPC ONI parser — and the negative space, which is where its honesty lives.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The fixtures below are HAND-BUILT to mirror the published ``oni.ascii.txt`` shape. They are
NOT real CPC data and are never presented as such: this session had no network (the CPC host
answers CONNECT 403 through the sandbox proxy, with pypi.org at 200 as the control), so the
format is documented rather than verified, and the operator's first real fetch is what
confirms it.

The recorded #590 lesson governs the shape of this file: a parser's skeptic must attack the
NEGATIVE space — the should-be-empty, should-be-refused, should-be-a-gap inputs — because a
suite that only checks that good rows parse passes straight over every fabrication. So each
positive claim below has its refusal twin.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from src.stats.oni import (
    AGENCY,
    REF_AREA,
    SEASONS,
    SERIES_ANOM,
    SERIES_TOTAL,
    parse_oni,
    season_months,
)

VINTAGE = "2026-09-07T00:00:00Z"

GOOD = """SEAS YR   TOTAL ANOM
DJF  1950 24.72 -1.53
JFM  1950 25.17 -1.34
NDJ  1997 28.93  2.40
"""


def _by(res, series):
    return [f for f in res.figures if f.series_id == series]


# ------------------------------------------------------------------------ the happy path


def test_a_well_formed_table_yields_two_series_per_row():
    res = parse_oni(GOOD, extracted_at=VINTAGE)
    assert res.rows_read == 3
    assert len(res.figures) == 6
    assert len(_by(res, SERIES_ANOM)) == 3
    assert len(_by(res, SERIES_TOTAL)) == 3
    # The header carries exactly four fields, so it survives the arity check and is
    # refused one step later, on the season token -- the more precise of the two reasons.
    assert [r["reason"] for r in res.refused] == ["not a CPC season label"], (
        "the header line must be refused, not silently absorbed"
    )
    assert res.refused[0]["text"].startswith("SEAS")


def test_the_values_and_provenance_are_carried_verbatim():
    res = parse_oni(GOOD, extracted_at=VINTAGE)
    anom = {f.time_period: f.value for f in _by(res, SERIES_ANOM)}
    assert anom == {"1950-DJF": -1.53, "1950-JFM": -1.34, "1997-NDJ": 2.40}
    one = _by(res, SERIES_ANOM)[0]
    assert one.agency == AGENCY
    assert one.ref_area == REF_AREA
    assert one.unit == "degC"
    assert one.extracted_at == VINTAGE
    assert "Niño 3.4" in one.methodology_ref


def test_the_two_series_are_never_blended_into_one():
    """An SST and an anomaly against a moving 30-year base are different quantities; one
    series id would invite a consumer to compare or average them."""
    res = parse_oni(GOOD, extracted_at=VINTAGE)
    assert SERIES_ANOM != SERIES_TOTAL
    djf = {f.series_id: f.value for f in res.figures if f.time_period == "1950-DJF"}
    assert djf == {SERIES_TOTAL: 24.72, SERIES_ANOM: -1.53}


def test_the_period_label_is_published_never_converted_to_a_date():
    """Converting "DJF 1950" to a date silently picks one of three months and bakes an
    off-by-one-year into the two seasons that straddle the year end."""
    res = parse_oni(GOOD, extracted_at=VINTAGE)
    assert all("-" in f.time_period and f.time_period.split("-")[1] in SEASONS
               for f in res.figures)


def test_the_parser_reads_no_clock_so_the_vintage_is_the_callers():
    a = parse_oni(GOOD, extracted_at="2020-01-01T00:00:00Z")
    b = parse_oni(GOOD, extracted_at="2026-09-07T00:00:00Z")
    assert {f.extracted_at for f in a.figures} == {"2020-01-01T00:00:00Z"}
    assert {f.extracted_at for f in b.figures} == {"2026-09-07T00:00:00Z"}
    # ... and everything else about the two parses is identical: a re-parse of the same
    # bytes must not drift, or a "revision" would be manufactured by the reader.
    assert [f.value for f in a.figures] == [f.value for f in b.figures]


# ----------------------------------------------------------------- gaps, never fabrications


@pytest.mark.parametrize("sentinel", ["-99.9", "-999.9", "-9.99", "-99.99", "-999"])
def test_a_missing_sentinel_becomes_a_gap_and_the_row_is_still_emitted(sentinel):
    """Read literally, a -99.9 °C anomaly is the most extreme cooling ever recorded.

    The row is still emitted, because a published gap is data — dropping it would make the
    series look continuous across a hole.
    """
    res = parse_oni(f"DJF 1950 24.72 {sentinel}\n", extracted_at=VINTAGE)
    assert res.rows_read == 1
    anom = _by(res, SERIES_ANOM)[0]
    assert anom.value is None, "a missing sentinel was published as a measurement"
    assert _by(res, SERIES_TOTAL)[0].value == 24.72, "the sibling cell must survive"


def test_a_negative_value_that_is_NOT_a_sentinel_is_kept():
    """The over-eager twin: a filter tuned to catch -99.9 must not eat a real -9.9, and a
    sentinel check on a prefix would. Real ONI anomalies are routinely negative."""
    res = parse_oni("DJF 1950 24.72 -9.9\n", extracted_at=VINTAGE)
    assert _by(res, SERIES_ANOM)[0].value == -9.9


def test_a_non_numeric_cell_is_REFUSED_not_turned_into_a_gap():
    """A gap and a parse failure are different facts: a gap says the producer published
    nothing, a failure says we could not read what they published. Folding the second into
    the first launders a broken parse into an observation."""
    res = parse_oni("DJF 1950 24.72 n/a\n", extracted_at=VINTAGE)
    assert res.figures == []
    assert res.rows_read == 0
    assert res.refused[0]["reason"] == "non-numeric value"


# ------------------------------------------------------------------- the refusals, counted


@pytest.mark.parametrize(
    "line,reason",
    [
        ("XXX 1950 24.72 -1.53", "not a CPC season label"),
        ("DJF abcd 24.72 -1.53", "year is not an integer"),
        ("DJF 1234 24.72 -1.53", "year out of range"),
        ("DJF 1950 24.72", "expected 4 fields"),
        ("DJF 1950 24.72 -1.53 extra", "expected 4 fields"),
    ],
)
def test_a_malformed_line_is_refused_with_its_reason(line, reason):
    res = parse_oni(line + "\n", extracted_at=VINTAGE)
    assert res.figures == []
    assert res.refused[0]["reason"] == reason
    assert res.refused[0]["line"] == "1"


def test_a_year_out_of_range_cannot_be_smuggled_in_by_a_shifted_column():
    """A column-shifted line would otherwise land a temperature in the year field. The
    finite range is what stops "24" becoming a year and the line being accepted."""
    assert parse_oni("DJF 24 1950 -1.53\n", extracted_at=VINTAGE).figures == []


def test_empty_and_whitespace_input_yield_nothing_and_claim_nothing():
    for text in ("", "\n", "   \n\t\n"):
        res = parse_oni(text, extracted_at=VINTAGE)
        assert res.figures == []
        assert res.refused == []
        assert res.looks_unrecognised is False, "empty input is not a wrong file"


def test_an_html_error_page_reads_as_UNRECOGNISED_not_as_an_empty_series():
    """THE test this parser's error handling exists for.

    If a fetch is handed a 404 page, a parser that silently skips unparseable lines
    returns [] — indistinguishable from "the file is empty". The refusals make it loud.
    """
    html = "<html><head><title>404 Not Found</title></head>\n<body>Not here</body></html>\n"
    res = parse_oni(html, extracted_at=VINTAGE)
    assert res.figures == []
    assert res.rows_read == 0
    assert res.refused, "an HTML page produced no refusals at all"
    assert res.looks_unrecognised is True


def test_a_real_table_is_NOT_flagged_unrecognised_despite_its_header():
    """The negative twin: `looks_unrecognised` must not fire on the header line every
    valid file starts with, or it would condemn every real fetch."""
    res = parse_oni(GOOD, extracted_at=VINTAGE)
    assert res.refused, "the header is refused"
    assert res.looks_unrecognised is False


# ---------------------------------------------------------------- the season span helper


def test_a_djf_season_starts_in_the_PREVIOUS_december():
    """The published year belongs to the season's LAST month. Getting this wrong is a
    silent off-by-one-year on exactly two of the twelve seasons, which is why it has its
    own helper and its own test rather than living inline."""
    assert season_months("DJF", 1950) == ((1949, 12), (1950, 1), (1950, 2))


def test_an_ndj_season_runs_into_the_FOLLOWING_january():
    assert season_months("NDJ", 1997) == ((1997, 11), (1997, 12), (1998, 1))


def test_a_mid_year_season_stays_inside_its_own_year():
    assert season_months("JJA", 2000) == ((2000, 6), (2000, 7), (2000, 8))


def test_every_declared_season_resolves_to_three_consecutive_months():
    for s in SEASONS:
        months = season_months(s, 2000)
        assert len(months) == 3
        # pairwise, not zip(xs, xs[1:]): the two lists differ in length by design, so
        # a strict zip is wrong here and a non-strict one just silences the check.
        for (y1, m1), (y2, m2) in pairwise(months):
            expected = (y1 + 1, 1) if m1 == 12 else (y1, m1 + 1)
            assert (y2, m2) == expected, f"{s}: {months} is not three consecutive months"


def test_an_unknown_season_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        season_months("XXX", 2000)


# ------------------------------------------------------------------------ no score, ever


def test_no_figure_carries_a_score_shaped_field():
    banned = ("score", "rating", "ranking", "grade")
    for f in parse_oni(GOOD, extracted_at=VINTAGE).figures:
        for key in f.to_dict():
            assert not any(b in key.lower() for b in banned), key


def test_the_parser_imports_no_network_library():
    """PURE by construction, and asserted on the module's own imports rather than on a
    comment promising it — the socket-importer ratchet's discipline, one module over."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "stats" / "oni.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not (names & {"requests", "httpx", "socket", "urllib", "http"}), names


# ----------------------------------------------------- episode derivation (the CPC rule)


def _series(*vals, year=1997, start=0):
    """A synthetic ONI run: one anomaly per consecutive season from `start`."""
    from src.stats.oni import SEASONS

    lines = []
    y, i = year, start
    for v in vals:
        lines.append(f"{SEASONS[i]} {y} 28.00 {v}" if v is not None
                     else f"{SEASONS[i]} {y} 28.00 -99.9")
        i += 1
        if i == len(SEASONS):
            i, y = 0, y + 1
    return parse_oni("\n".join(lines) + "\n", extracted_at=VINTAGE).figures


def test_a_run_of_five_seasons_at_or_above_the_threshold_is_an_episode():
    from src.stats.oni import episodes_from_oni

    eps = episodes_from_oni(_series(0.5, 0.9, 1.4, 1.8, 1.2))
    assert len(eps) == 1
    assert eps[0]["seasons"] == 5
    assert eps[0]["peak_oni"] == 1.8
    assert eps[0]["intensity"] == "strong"


def test_a_run_of_FOUR_seasons_is_not_an_episode_and_is_not_reported_as_a_shorter_one():
    """The CPC definition is the definition; softening it here would make the bundled
    table's comparison meaningless."""
    from src.stats.oni import episodes_from_oni

    assert episodes_from_oni(_series(0.9, 1.4, 1.8, 1.2)) == []


def test_the_threshold_is_inclusive_at_exactly_plus_zero_point_five():
    from src.stats.oni import episodes_from_oni

    assert len(episodes_from_oni(_series(0.5, 0.5, 0.5, 0.5, 0.5))) == 1
    assert episodes_from_oni(_series(0.49, 0.49, 0.49, 0.49, 0.49)) == []


def test_a_GAP_breaks_a_run_it_never_bridges_one():
    """An unobserved season is neither above nor below the threshold. Bridging it would
    invent an episode spanning a hole — the chart toolkit's "render gaps as gaps" rule, one
    layer down in the arithmetic."""
    from src.stats.oni import episodes_from_oni

    assert episodes_from_oni(_series(0.9, 1.4, None, 1.8, 1.2, 0.9)) == []
    # the negative twin: the SAME values with the hole filled DO make one episode, so the
    # rule is breaking on the gap and not on something else about the fixture
    assert len(episodes_from_oni(_series(0.9, 1.4, 1.6, 1.8, 1.2, 0.9))) == 1


def test_a_missing_ROW_breaks_a_run_because_list_adjacency_is_not_time_adjacency():
    """Two runs either side of an absent season are two runs. Concatenating them because
    they are neighbours in the list would join arbitrarily distant years."""
    from src.stats.oni import episodes_from_oni

    figs = _series(0.9, 1.4, 1.6) + _series(1.8, 1.2, 0.9, 0.8, 0.7, year=1999, start=0)
    eps = episodes_from_oni(figs)
    assert len(eps) == 1, "a run was joined across a two-year hole"
    assert eps[0]["start"].startswith("1999")


def test_a_sub_threshold_season_ends_the_run_and_a_later_run_is_its_own_episode():
    from src.stats.oni import episodes_from_oni

    eps = episodes_from_oni(_series(0.9, 1.4, 1.6, 1.8, 1.2, 0.1, 0.9, 1.4, 1.6, 1.8, 1.2))
    assert len(eps) == 2
    assert eps[0]["seasons"] == 5 and eps[1]["seasons"] == 5


def test_la_nina_is_the_explicit_mirror_never_inferred_from_a_sign():
    from src.stats.oni import episodes_from_oni

    cold = _series(-0.9, -1.4, -1.6, -1.8, -1.2)
    assert episodes_from_oni(cold, warm=True) == []
    eps = episodes_from_oni(cold, warm=False)
    assert len(eps) == 1 and eps[0]["peak_oni"] == -1.8
    assert eps[0]["intensity"] == "strong"


def test_an_episode_reports_published_season_labels_never_dates():
    from src.stats.oni import episodes_from_oni

    e = episodes_from_oni(_series(0.9, 1.4, 1.6, 1.8, 1.2))[0]
    assert e["start"].split("-")[1] in SEASONS
    assert e["end"].split("-")[1] in SEASONS


def test_the_intensity_label_is_derived_from_the_peak_that_travels_beside_it():
    """A LABEL for a published number, never a score: the reader can always see the value
    the bucket came from."""
    from src.stats.oni import episodes_from_oni, intensity_for

    for peak, want in ((2.4, "very strong"), (1.7, "strong"), (1.2, "moderate"), (0.7, "weak")):
        assert intensity_for(peak) == want
    assert intensity_for(0.3) is None
    e = episodes_from_oni(_series(0.9, 1.4, 1.6, 2.4, 1.2))[0]
    assert e["intensity"] == intensity_for(e["peak_oni"])
