"""The brush-to-select affordance in ooChart (GUI visualization plan F4, frontend half).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Slices come from tests.js_source_helper so they are brace-matched from the BODY brace:
``function ooChart(el, seriesList, opts = {})`` carries a ``{}`` in a DEFAULT PARAMETER,
and taking the first brace after the name lands there, truncating the "body" to the
signature and making every assertion over it pass for free. That really happened here.

The load-bearing guard is the OPT-IN one. Only a chart whose x-axis is article time can
honestly answer "which articles are under this span"; a commodity price chart's axis is
price time and a statistics chart's is the observation period, so brushing either and
calling the result "the articles behind this" is a category error. The affordance must
therefore appear for exactly the charts that pass ``onSelectRange`` and for no others.
"""

from __future__ import annotations

import re

from tests.js_source_helper import function_body, read_static, strip_comments

APP = read_static("app.js")
CHART = function_body(APP, "ooChart")
BRUSH = function_body(APP, "_brushToCorpus")


def test_the_affordance_is_opt_in_and_inert_without_it():
    """Every brush path hangs off opts.onSelectRange, so a chart that does not pass it
    keeps its previous behaviour exactly."""
    body = strip_comments(CHART)
    assert 'typeof opts.onSelectRange === "function"' in body, (
        "the opt-in must be an explicit callable check, not a truthiness test on an "
        "arbitrary value"
    )
    assert "const canBrush" in body
    # the button, the band and the gesture must all be gated on it
    assert re.search(r"if\s*\(\s*canBrush\s*\)", body), "the toolbar button is gated"
    assert "canBrush && (brushMode || ev.shiftKey)" in body, (
        "the gesture itself is gated, so Shift+drag cannot brush a chart that never "
        "offered selection"
    )


def test_only_article_time_charts_opt_in():
    """The whole-file check that matters: exactly one chart passes onSelectRange today.

    If a price or statistics chart ever appears in this list, a brush there would claim
    its axis measures article time. The analysis window's #an-trend-chart is absent for a
    different reason: it plots the analysed term ALONGSIDE related keywords, so "which
    series' articles" has no unambiguous answer without a per-series control.
    """
    body = strip_comments(APP)
    sites = re.findall(r'ooChart\(\s*\$\("([a-z0-9-]+)"\)[^;]*?onSelectRange', body, re.S)
    assert set(sites) == {"ins-trend-oo"}, (
        f"unexpected brushable charts: {sorted(set(sites))} -- a chart whose x-axis is "
        f"not article time must not offer a selection, and a chart no reader can reach "
        f"must not either (corpusTab has no callers, so #corpus-chart is excluded on "
        f"purpose: a capability on dead code is a guard that passes while proving nothing)"
    )


def test_a_drag_still_pans_and_a_click_still_pins():
    """The brush must not cost the two gestures that already existed."""
    body = strip_comments(CHART)
    assert "dragT = [t0, t1]" in body, "plain drag still records a pan window"
    assert "dragT == null" in body, (
        "a null dragT is what distinguishes a brush from a pan; without it the two "
        "gestures cannot coexist"
    )
    assert "pinned = b ? b.p : null" in body, "click-to-pin survives"
    assert re.search(r"if\s*\(\s*wasBrush\s*\)\s*\{\s*bFrom = bTo = null", body), (
        "a brush shorter than the click threshold must fall through to the click, not "
        "emit an empty span"
    )


def test_the_emitted_span_is_local_calendar_days_not_utc():
    """toISOString() on a local midnight can land on the previous day, so a reader who
    brushed one day could receive the day before it."""
    body = strip_comments(CHART)
    assert "getTimezoneOffset()" in body, (
        "the emitted dates must be shifted by the local offset before slicing, or the "
        "span will not be the span that was drawn"
    )
    assert "toISOString().slice(0, 10)" in body


def test_the_live_readout_states_the_same_span_the_brush_will_emit():
    """Caught in the browser, not in review. fmtT picks its granularity from the whole
    axis span, so on a multi-month chart the readout rendered "2026-05" while the brush
    selected 2026-05-10 -- the reader was shown a month and handed a span starting
    mid-month, with no way to tell before releasing. One shared formatter makes the two
    agree by construction rather than by coincidence."""
    body = strip_comments(CHART)
    assert body.count("const dayOf") == 1, (
        "one definition only: two copies could drift and the readout would silently stop "
        "describing the selection"
    )
    # The readout previews the SNAPPED span, because the server widens a brush to whole
    # chart buckets: previewing the raw drag showed 2026-05-10 -> 06-26 while the result
    # reported 05-04 -> 06-28, two spans for one gesture. Asserted on the VALUES rendered
    # rather than the expression's shape, which is what made this guard stale twice.
    assert re.search(r"\{from: dayOf\(_snap\(lo, false\)\), to: dayOf\(_snap\(hi, true\)\)", body), (
        "the live readout must preview the bucket-snapped span through the same day "
        "formatter as the emit -- never fmtT, whose granularity follows the whole axis, "
        "and never the raw drag, which is not the span the server will use"
    )
    assert re.search(r"onSelectRange\(dayOf\(", body), "and the emit must use it too"
    assert "readout.textContent = fmtT(" not in body, "the old, coarser formatter is gone"


def test_the_toggle_is_a_real_button_with_state_not_an_inline_handler():
    body = strip_comments(CHART)
    assert 'brushBtn.addEventListener("click"' in body, (
        "a real listener, never an inline onclick -- the component must stay off the "
        "unsafe-inline script-src debt"
    )
    assert 'setAttribute("aria-pressed"' in body, (
        "the pressed state must not be colour-only"
    )
    assert "brushBtn.title = t9(" in body, "the hover explanation is translated"


def test_the_selection_resolves_server_side_on_the_charts_own_clock():
    """It must call the endpoint that matches on observed_on, never build a start/end
    date filter -- which means a different thing and would under-select."""
    body = strip_comments(BRUSH)
    assert "/api/insights/trend-articles" in body
    for wrong in ("start_date=", "end_date=", "published"):
        assert wrong not in body, (
            f"{wrong!r} would route the span through the published_at date filter, which "
            f"drops any article whose publish date could not be extracted -- the very "
            f"defect this design exists to avoid"
        )


def test_both_numbers_are_shown_because_they_are_different_quantities():
    body = strip_comments(BRUSH)
    assert "r.articles" in body and "r.mentions" in body, (
        "a bar's height is a mention total and the selection is a set of articles; "
        "showing one alone lets it stand for the other"
    )
    assert "r.quarantined_excluded" in body, "the excluded count is disclosed"
    assert "r.capped" in body, "a truncated selection says so"


def test_an_empty_span_is_stated_not_silently_ignored():
    body = strip_comments(BRUSH)
    assert re.search(r"if\s*\(\s*!ids\.length\s*\)", body), (
        "an empty result must be reported; a silent no-op is indistinguishable from a "
        "broken control"
    )


def test_the_error_path_does_not_re_wrap_an_error_through_the_body_helper():
    """api() already throws an Error whose message _apiErrorMessage composed. Passing that
    Error back in would read e.detail (undefined) then res.status on a string, printing
    the 'undefined undefined' the helper exists to prevent."""
    body = strip_comments(BRUSH)
    assert "_apiErrorMessage" not in body
    assert "e.message" in body


def test_every_new_string_is_keyed_in_all_twelve_locales():
    """The durable guard: a string added here without its twelve entries renders English
    for eleven locales, which is how honesty text has silently gone untranslated before."""
    import json
    from pathlib import Path

    loc = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    needed = [
        "Select a period",
        "No articles in {from} → {to}.",
        "{term} · {articles} articles · {mentions} mentions · {from} → {to}",
        "Selected {from} → {to} · {n} of {total} points",
        "n counts the datapoints plotted here, not articles.",
        "{n} quarantined, not included",
        "showing the first 5000",
        "{term}: {from} → {to}",
        "Could not open that period",
    ]
    files = sorted(loc.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for k in needed:
            assert k in d, f"{f.stem}: missing key {k!r}"
            assert str(d[k]).strip(), f"{f.stem}: empty value for {k!r}"


def test_the_templates_keep_their_placeholders_in_every_locale():
    """A mangled {from} renders as a literal brace to the reader."""
    import json
    from pathlib import Path

    loc = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    ph = re.compile(r"\{(\w+)\}")
    templates = [
        "No articles in {from} → {to}.",
        "{term} · {articles} articles · {mentions} mentions · {from} → {to}",
        "Selected {from} → {to} · {n} of {total} points",
        "n counts the datapoints plotted here, not articles.",
        "{n} quarantined, not included",
        "{term}: {from} → {to}",
    ]
    for f in sorted(loc.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for k in templates:
            assert set(ph.findall(d[k])) == set(ph.findall(k)), (
                f"{f.stem}: placeholders differ for {k!r} -> {d[k]!r}"
            )


def test_the_superseded_toast_key_is_gone_not_orphaned_beside_its_replacement():
    """The toast template gained a {term} slot so it says WHAT was counted. Adding the new
    key while leaving the old one would orphan a reviewed translation and leave the i18n
    gate green -- the recorded ALERT_CAVEAT failure. Each locale's existing wording was
    reused by prefixing the term slot, so nothing was re-invented either."""
    import json
    from pathlib import Path

    loc = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    superseded = "{articles} articles · {mentions} mentions · {from} → {to}"
    for f in sorted(loc.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert superseded not in d, (
            f"{f.stem}: the superseded template is still present -- a re-key must replace "
            f"the old entry, not sit beside it"
        )


def test_the_readout_states_how_many_points_the_span_covers():
    """A critic reading the screenshot estimated four bars inside the band when three were,
    because two lookalike bars sat either side of the edge. Stating the count settles it
    ADDITIVELY -- nothing is dimmed, since element opacity makes a contrast pair lie."""
    body = strip_comments(CHART)
    assert "of {total} points" in body, "the readout must state the count, not only the dates"
    assert re.search(r"if \(pt\.t >= lo && pt\.t <= hi\) inside\+\+", body), (
        "the count must be computed from the points actually inside the span"
    )
    assert "globalAlpha = 0.15" in body, (
        "the band stays a light overlay; if this became a dimming pass over the excluded "
        "data, re-read the .ag-cal lesson about opacity and measured contrast"
    )


def test_the_brush_snaps_to_whole_chart_buckets():
    """A brush over a weekly chart can only honestly select whole weeks. Measured before
    this: four visible bars summing to 65 were reported as 50, because a week bar drawn at
    its Monday (2026-06-22) whose every mention fell on 06-28 sat inside a span ending
    06-26. The bucket travels with the request and the span widens to its edges."""
    body = strip_comments(CHART)
    assert "const _snap" in body, "the preview must snap client-side"
    assert 'opts.bucket || "day"' in body, (
        'the default must be "day" -- the identity case, so a chart that declares no '
        "bucket behaves exactly as before"
    )
    brush = strip_comments(BRUSH)
    assert "bucket=${encodeURIComponent(bucket" in brush, (
        "the chart's own bucket must reach the resolver, or it widens by the wrong unit"
    )
    assert re.search(r"r\.start \|\| from", brush) and re.search(r"r\.end \|\| to", brush), (
        "the result must report the EFFECTIVE span the server used, not the raw drag"
    )
