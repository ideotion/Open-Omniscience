"""Governments units, axis labels and chart geometry (2026-08-07, brief slice A3).

The maintainer's PDF export of the Governments tab showed a ten-digit GDP-PPP figure,
a bare "141.60" where the unit was the whole point, a chart gridline reading
``51167643745037.1``, a one-point series whose x-axis said ``01-01`` instead of the
year, and sparklines rendered as slivers.

None of those were data problems -- every value was correct. They were formatting and
geometry, which is why the fixes here are about how a real number is SHOWN.

The behavioural half runs the real `_govFmt` in node, extracted from the shipped file,
so a re-typed copy cannot pass while the shipped code is broken.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap

import pytest

from src.stats.indicators import INDICATOR_CATALOG
from tests.js_source_helper import css_rule, function_body, function_source, read_static

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to drive app.js logic")


def _run_js(snippet: str) -> dict:
    """Run `snippet` with the REAL formatters extracted from app.js."""
    app = read_static("app.js")
    harness = textwrap.dedent(
        """
        const window = {};   // _govFmt binds t from window.OOI18N; absent -> English
        """
    ) + "\n".join(function_source(app, n) for n in ("fmtNum", "_govCompact", "_govFmt", "_axisNum"))
    proc = subprocess.run(
        [NODE, "-e", harness + "\n" + snippet],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------- #
# Every catalog unit is formatted, and none is silently dropped
# --------------------------------------------------------------------------- #


def test_every_catalog_unit_has_an_explicit_branch():
    """A unit added to the catalog must not fall through to a naked number.

    Six of the catalog's eleven units used to hit `fmtNum(v, 2)` and lose the unit
    entirely. This is the guard that stops the twelfth from doing the same.
    """
    units = sorted({i["unit"] for i in INDICATOR_CATALOG})
    body = function_body(read_static("app.js"), "_govFmt")
    missing = [u for u in units if f'"{u}"' not in body]
    assert not missing, f"units with no branch in _govFmt: {missing}"


def test_the_specimen_values_from_the_field_export():
    """The exact numbers off the maintainer's PDF."""
    out = _run_js(
        """
        console.log(JSON.stringify({
          gdp_ppp:  _govFmt(99594884137256.80, "intl$"),
          mobile:   _govFmt(141.6, "per 100"),
          usd:      _govFmt(77000000000000, "USD"),
          people:   _govFmt(1400000000, "people"),
          pct:      _govFmt(97.7, "%"),
          life:     _govFmt(80.4, "years"),
          fertility:_govFmt(1.42, "births/woman"),
          physician:_govFmt(3.78, "per 1,000"),
          maternal: _govFmt(12.0, "per 100,000"),
          co2:      _govFmt(9.13, "t/capita"),
        }));
        """
    )
    # "100T" rather than "99.6T": _govCompact drops decimals above 1e13, which is
    # PRE-EXISTING shared behaviour that USD and people already rely on. Retuning a
    # shared formatter's precision is a separate decision from routing units through
    # it, so this PR asserts the behaviour that exists rather than quietly changing it.
    assert out["gdp_ppp"] == "Int$100T", "a ten-digit run of figures is not a readable value"
    assert out["mobile"] == "141.6 per 100", "the unit is the whole point of this one"
    assert out["usd"] == "$77T"
    assert out["people"] == "1.4B"
    assert out["pct"] == "97.7%"
    assert out["fertility"] == "1.42 births/woman"
    assert out["physician"] == "3.78 per 1,000"
    assert out["maternal"] == "12 per 100,000"
    assert out["co2"] == "9.13 t/capita"


def test_ppp_dollars_are_not_shown_as_us_dollars():
    """Int$ and US$ are different units; a shared "$" would equate them silently."""
    out = _run_js(
        'console.log(JSON.stringify({a: _govFmt(1e12, "intl$"), b: _govFmt(1e12, "USD")}));'
    )
    assert out["a"] != out["b"]
    assert out["a"].startswith("Int$") and out["b"].startswith("$")


def test_an_unknown_unit_is_appended_rather_than_dropped():
    """The structural half: the fallthrough must degrade, not discard.

    The number keeps the fallthrough's existing 2-decimal form ("12.50"); what
    changes is that the unit is no longer thrown away.
    """
    out = _run_js('console.log(JSON.stringify({v: _govFmt(12.5, "kWh/capita")}));')
    assert out["v"] == "12.50 kWh/capita"
    assert out["v"].endswith("kWh/capita"), "a unit with no branch must still be shown"


def test_a_missing_value_is_a_dash_not_a_zero():
    """A published gap stays a gap -- the standing rule this must not break."""
    out = _run_js(
        'console.log(JSON.stringify({n: _govFmt(null, "%"), i: _govFmt(Infinity, "USD")}));'
    )
    assert out["n"] == "—" and out["i"] == "—"


# --------------------------------------------------------------------------- #
# G4 -- axis labels
# --------------------------------------------------------------------------- #


def test_a_huge_axis_value_is_compacted():
    out = _run_js('console.log(JSON.stringify({v: _axisNum(51167643745037.1)}));')
    assert out["v"] == "51T", "a 14-digit gridline label does not fit in ~40px"
    assert len(out["v"]) <= 6, out["v"]


def test_small_axis_values_are_byte_identical_to_before():
    """The twin. Count, price and percentage axes must not change.

    Compaction below a million would make an axis LESS precise for no gain, and this
    formatter is shared by every chart in the app, not only the Governments cards.
    """
    out = _run_js(
        """
        const vals = [0, 1, 23, 99.5, 1000, 12345, 999999];
        console.log(JSON.stringify({axis: vals.map(_axisNum), plain: vals.map(v => fmtNum(v))}));
        """
    )
    assert out["axis"] == out["plain"], out


# --------------------------------------------------------------------------- #
# G5 -- a one-point series labels its year
# --------------------------------------------------------------------------- #


def test_a_single_point_series_labels_the_year_not_a_month_and_day():
    app = read_static("app.js")
    harness = function_source(app, "_pointLabelFmt")
    proc = subprocess.run(
        [NODE, "-e", harness + """
        console.log(JSON.stringify({
          annual: _pointLabelFmt("2022-01-01"),
          daily:  _pointLabelFmt("2026-07-15"),
          hourly: _pointLabelFmt("2026-07-15T13:00:00Z"),
        }));"""],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["annual"] == "2022", "the Physicians card printed '01-01' for a 2022 figure"
    assert out["daily"] == "2026-07-15", "a real day keeps its day"
    assert out["hourly"] == "07-15 13", "an hourly stamp keeps its hour"


def test_the_zero_span_arm_is_reached_only_when_there_is_no_interval():
    """An hourly pair is 0.04 days apart, not 0, and must keep the hourly label."""
    body = function_body(read_static("app.js"), "_timeLabelFmt")
    assert "days === 0" in body, (
        "the point-precision arm must trigger on an EXACTLY zero span; a tolerance "
        "here would swallow real sub-day series"
    )


def test_the_chart_is_gated_on_plotted_points_not_raw_series():
    """A series of several entries with one non-null value is a ONE-point chart.

    Gating on the raw length is how a single point reached the renderer at all.
    """
    body = function_body(read_static("app.js"), "loadGovCountry")
    assert "pts.length > 1" in body, body[:400]


# --------------------------------------------------------------------------- #
# G6 -- chart geometry
# --------------------------------------------------------------------------- #


def test_the_sparkline_keeps_its_aspect_ratio():
    """A fixed 32px box against a 300x120 viewBox scaled the whole chart to 27%.

    An SVG with a viewBox letterboxes rather than squashing, so the symptom was a
    tiny centred sliver with ~2px axis text, not a distorted chart.
    """
    rule = css_rule(read_static("app.css"), ".gov-ind-spark svg")
    assert "aspect-ratio" in rule, rule
    assert "height:auto" in rule.replace(" ", ""), rule
    container = css_rule(read_static("app.css"), ".gov-ind-spark")
    assert "height:32px" not in container.replace(" ", ""), (
        "the container's fixed height also clipped the legend and caveat below the chart"
    )


# --------------------------------------------------------------------------- #
# The two figures that look wrong and are correct
# --------------------------------------------------------------------------- #


def test_the_two_misreadable_indicators_carry_a_definition():
    """141.6 per 100 and 103.2% gross both read as errors. They are not.

    A label is the honest fix; changing the number would be the dishonest one.
    """
    by_id = {i["id"]: i for i in INDICATOR_CATALOG}
    mobile = by_id["IT.CEL.SETS.P2"]
    enroll = by_id["SE.SEC.ENRR"]
    assert "SUBSCRIPTIONS" in mobile["note"]
    assert "exceed 100" in enroll["note"]
    for ind in (mobile, enroll):
        assert len(ind["note"]) > 80, "a definition, not a restatement of the label"


def test_the_note_reaches_the_card_as_a_hover():
    body = function_body(read_static("app.js"), "loadGovCountry")
    assert "ind.note" in body and "title=" in body, (
        "the definition must ride the #oo-tip hover convention (invariant #17)"
    )


def test_no_indicator_note_asserts_a_score_or_a_verdict():
    """These are definitions of a producer's measure, never a judgement of it."""
    banned = ("score", "rank", "rating", "grade", "better", "worse", "good", "bad")
    for ind in INDICATOR_CATALOG:
        note = (ind.get("note") or "").lower()
        for word in banned:
            assert word not in note.split(), f"{ind['id']}: {word!r} in note"
