"""The Observatory frontend — the ooSky renderer, its tab, and its disclosures.

Design of record: ``docs/design/OBSERVATORY_DESIGN.md`` (maintainer-ruled
2026-07-18). The geometry's own behaviour is pinned by ``tests/oosky_node_test.js``,
driven below; what THIS file guards is the wiring and the honesty statements —
the things that are true of the surface rather than of the maths.

Every assertion here exists because the corresponding claim cannot be checked by
reading the diff: that the tab is reachable, that the canvas is not the only way
to read the data, that the caveat is in the DOM rather than behind a toggle, and
that the two disclosures the design calls anti-capping are actually rendered.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import (
    app_modules,
    function_body,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


def _html() -> str:
    return read_static("index.html")


def _obs() -> str:
    return read_static("app-observatory.js")


def _code_only(js: str) -> str:
    """Source with BOTH comment forms removed.

    ``strip_comments`` drops whole-line ``//`` only, deliberately -- a trailing
    ``//`` cannot be removed without a tokenizer because ``"https://"`` lives in
    string literals. But a "must be absent" guard also trips on a ``/* */`` header
    that explains the absence, which is exactly what happened to the Math.random
    guard below on its first run: ``oosky.js``'s own header says "never
    Math.random". The recorded rule is to STRIP the comment, never to reword it --
    that sentence is what a future session reads before deciding the absence was an
    oversight. So block comments come out too, and the assertion below proves the
    strip is safe for these files rather than assuming it.
    """
    import re

    assert "/*" not in re.sub(r"/\*.*?\*/", "", js, flags=re.S), (
        "an unbalanced /* means a block comment marker sits inside a string literal, "
        "and this strip would eat code"
    )
    return strip_comments(re.sub(r"/\*.*?\*/", "", js, flags=re.S))


def test_oosky_node_suite_runs() -> None:
    """Drive the node suite from pytest.

    Required by ``test_every_node_suite_has_a_driver``: an unrun node suite looks
    exactly like a passing one, and that has already cost a shipped defect here.
    """
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oosky_node_test.js")],
        capture_output=True, text=True, cwd=str(_ROOT), check=False,
    )
    assert proc.returncode == 0, f"oosky_node_test.js failed:\n{proc.stdout}\n{proc.stderr}"
    assert "ooSky checks passed" in proc.stdout


def test_the_observatory_is_a_tab_the_sidebar_lists_and_the_shell_loads() -> None:
    """Invariant #2's roster grows by one (the 2026-07-18 ruling: a DEDICATED main
    tab beside the others). Three things have to line up or the tab is unreachable
    in a way no syntax check would show: the nav button, the page, and the loader."""
    html = _html()
    assert '<button class="nav-item" data-tab="observatory"' in html, (
        "the Observatory must be listed in the sidebar (invariant #2)"
    )
    assert 'id="tab-observatory"' in html, "the tab page must exist"
    # The loader map is what `showTab` consults; a page with no entry renders empty.
    shell = read_static("app-shell.js")
    assert "observatory: () => loadObservatory()" in shell, (
        "showTab's TAB_LOADERS must call loadObservatory, or the tab renders blank"
    )
    assert "app-observatory.js" in app_modules(), (
        "index.html must LOAD the module -- app_modules() reads the script tags, so a "
        "module the browser never loads is also one every source guard here goes blind to"
    )
    assert '<script src="/static/oosky.js">' in html, "the renderer itself must be loaded"


def test_ooviz_is_loaded_before_oosky_that_depends_on_it() -> None:
    """ooSky reads ooViz off the global at call time, but the ORDER still matters
    for every other reader, and there is no module system here to enforce it."""
    html = _html()
    assert html.index('/static/ooviz.js') < html.index('/static/oosky.js'), (
        "ooviz.js must be loaded before oosky.js"
    )


def test_the_caveat_is_in_the_dom_and_not_behind_a_toggle() -> None:
    """The informed-consent non-negotiable: caveats are VISIBLE BY DEFAULT, never
    hidden behind a calm-UI toggle. This is the check that fails if someone later
    tidies the surface by folding the caveat into a <details>."""
    html = _html()
    page = html.split('id="tab-observatory"', 1)[1].split('<!-- =====', 1)[0]
    assert 'class="card-caveat" id="sky-caveat"' in page, (
        "the Observatory's caveat must render in the visible .card-caveat line"
    )
    assert "no composite score" in page, "the caveat must say there is no composite score"
    # It must not be inside a hidden container or a disclosure widget.
    before = page.split('id="sky-caveat"', 1)[0]
    assert before.count("<details") == before.count("</details>"), (
        "the caveat must not sit inside an unclosed <details> (a toggle is not layering)"
    )
    assert "hidden" not in page.split('id="sky-caveat"', 1)[1][:60], (
        "the caveat element must not be hidden"
    )


def test_the_table_is_rendered_in_full_and_is_the_canonical_path() -> None:
    """Anti-capping plus accessibility rule A1 in one: the chart is backed by a real
    table that IS its content. `rankedGalaxies` returns placed AND unplaced rows, so
    a `.slice(0, N)` anywhere in the render would silently cap the canonical view."""
    body = strip_comments(function_body(_obs(), "_obsTable"))
    assert "rankedGalaxies" in body, "the table must come from the one canonical order"
    assert ".slice(" not in body, (
        "the ranked table must never be truncated -- it is the canonical view, and a "
        "displayed figure is never secretly a cap"
    )
    assert "<table" in body, "it must be a real table, not a caption"


def test_the_sky_and_the_table_cannot_drift_apart() -> None:
    """Both orders come from ONE function. Two sort implementations would agree on
    the day they were written and diverge on the first tie-break someone changed."""
    obs = _obs()
    for fn in ("_obsTable", "_obsAria"):
        assert "rankedGalaxies" in strip_comments(function_body(obs, fn)), (
            f"{fn} must read the canonical order from ooSky.rankedGalaxies"
        )


def test_the_scale_in_force_is_printed_not_implied() -> None:
    """The recorded logY defect put a hint claiming "equal ratios are equal
    distances" above a chart that had drawn linear. ooSky chooses the mode from the
    data, so the surface owes the reader the mode it actually drew -- all three of
    them, including the refusal."""
    body = strip_comments(function_body(_obs(), "_obsDisclosure"))
    assert 'S.mode === "log"' in body and 'S.mode === "linear"' in body, (
        "the disclosure must branch on the mode the renderer actually chose"
    )
    assert "logarithmic" in body and "linear from zero" in body, (
        "each branch must NAME the scale it drew"
    )
    assert "under one full decade" in body, (
        "the linear branch must say WHY the log mode was refused, not merely that it is linear"
    )


def test_the_populations_the_picture_omits_are_disclosed_on_the_surface() -> None:
    """"N shown, M in the nebula" is the design's own anti-capping answer, and it is
    the one line that keeps a bounded render from hiding the long tail."""
    body = strip_comments(function_body(_obs(), "_obsDisclosure"))
    for token in ("{plotted}", "{unplaced}", "{nebula}", "{total}"):
        assert token in body, f"the disclosure line must carry {token}"
    assert "nebula" in body.lower(), "the nebula must be named on the surface"


def test_the_trend_lens_refuses_to_colour_a_non_ratio() -> None:
    """`growth_is_ratio` false means `growth` is the RECENT COUNT standing in for a
    ratio. Painting that red would fabricate a measured decline out of a sentinel --
    and the flag exists precisely so a consumer can tell them apart."""
    body = strip_comments(function_body(_obs(), "_obsColorOf"))
    assert "growth_is_ratio" in body, "the trend lens must consult the ratio flag"
    guard = body.split("growth_is_ratio", 1)[1][:120]
    assert "return" in guard, "a non-ratio must return early, before any warm/cool branch"
    assert body.index("growth_is_ratio") < body.index("_OBS_WARM"), (
        "the flag must be checked BEFORE the thresholds, or a count reaches them"
    )
    cell = strip_comments(function_body(_obs(), "_obsTrendText"))
    assert "growth_is_ratio" in cell and "Not comparable" in cell, (
        "the table cell must say the comparison could not be made, never print the sentinel"
    )


def test_colour_is_never_the_only_signal() -> None:
    """Accessibility rule A2, and the arithmetic behind it: the worst mutual contrast
    between two theme-derived series colours is 1.00:1, so colour CANNOT carry
    identity. Every galaxy must also reach the reader as text."""
    table = strip_comments(function_body(_obs(), "_obsTable"))
    assert "ooLangName" in table, "the table must name the language, not only colour it"
    readout = strip_comments(function_body(_obs(), "_obsReadout"))
    assert "Main language" in readout, "the readout must name the language too"


def test_the_keyboard_path_does_not_go_through_pointer_geometry() -> None:
    """Accessibility rule A5. `hitTest` is canvas hit-testing; a keyboard user must
    never depend on it, or the sky is mouse-only in a way nothing would report."""
    body = strip_comments(function_body(_obs(), "_obsKey"))
    assert "hitTest" not in body, "keyboard traversal must not route through hit-testing"
    assert "ArrowRight" in body and "ArrowLeft" in body and "Enter" in body, (
        "arrow keys must move the focus and Enter must open the galaxy"
    )
    html = _html()
    canvas = html.split('id="sky-canvas"', 1)[1][:200]
    assert 'tabindex="0"' in canvas, "the canvas must be focusable for the keyboard path to start"
    assert 'role="img"' in canvas, "and expose itself as an image with a text equivalent (A1)"


def test_the_canvas_reads_theme_tokens_rather_than_hardcoded_colour() -> None:
    """Accessibility rule A3 and the reason --caveat exists: a hardcoded hue failed
    contrast on 8 of 17 themes. Canvas has no CSS, so the colours must be READ."""
    body = strip_comments(function_body(_obs(), "_obsTheme"))
    assert "readCssVar" in body, "canvas colours must come from the theme's custom properties"
    import re
    hexes = re.findall(r"#[0-9a-fA-F]{3,6}", body)
    # Fallbacks are allowed (a var can resolve empty), but every one must sit in a
    # `css(name, fallback)` call rather than being used as the colour itself.
    for h in hexes:
        assert f'"{h}"' in body, f"{h} must be a named fallback argument, not an inline colour"
    assert "--fig-" in body, "the categorical series tokens are the app's own chart palette"


def test_the_renderer_never_calls_math_random() -> None:
    """Honesty rule H5, and the whole basis of "same corpus, same sky". A single
    Math.random in the layout would reshuffle every user's sky on every visit and
    destroy the spatial memory that makes a new bright star readable."""
    # strip_comments FIRST: a "must be absent" guard trips on the comment that
    # explains the absence, and this one did on its first run -- oosky.js's own
    # header says "never Math.random". The recorded fix is to check the CODE.
    sky = (_STATIC / "oosky.js").read_text(encoding="utf-8")
    assert "mulberry32" in sky, "the seeded PRNG ooViz already ships is the one to use"
    assert "Math.random" not in _code_only(sky), (
        "ooSky must be deterministic -- use ooViz.mulberry32"
    )
    assert "Math.random" not in _code_only(_obs()), (
        "the Observatory wiring must be deterministic too"
    )


def test_the_surface_is_static_when_idle() -> None:
    """Design §7: no animation loops, zero idle CPU on the 2-core reference VM. A
    rAF that reschedules itself unconditionally is the shape to keep out."""
    obs = _obs()
    paint = strip_comments(function_body(obs, "_obsPaint"))
    assert "requestAnimationFrame" in paint, "repaints should be rAF-coalesced"
    inner = strip_comments(function_body(obs, "_obsPaintNow"))
    assert "requestAnimationFrame" not in inner, (
        "the paint itself must not schedule another frame -- that is an animation loop"
    )


def test_depth_never_scales_a_mark() -> None:
    """Design §7: depth is NAVIGATIONAL only and marks are screen-space sized, so
    perspective can never distort a magnitude (the reject-list rationale that 3D
    foreshortening fabricates area). The star radius must not be multiplied by the
    view scale, and the guard is worth having because writing `* z` there looks
    exactly like the surrounding correct code."""
    body = strip_comments(function_body((_STATIC / "oosky.js").read_text(encoding="utf-8"), "drawSky"))
    assert "var r = Math.max(MIN_STAR, g.star);" in body, (
        "the star radius must be screen-space -- never multiplied by the view scale"
    )


def test_every_new_observatory_string_is_keyed_in_all_twelve_locales() -> None:
    """The durable fix for the recorded "English honesty text under translated
    Arabic caveats" defect is a guard, not memory. Every locale carries every key
    or this fails by name."""
    locales = sorted((_STATIC / "locales").glob("*.json"))
    assert len(locales) == 12, f"expected 12 locale files, found {len(locales)}"
    en = json.loads((_STATIC / "locales" / "en.json").read_text(encoding="utf-8"))
    required = [
        "Observatory",
        "Distance from centre",
        "Reference stars",
        "Not observed in this corpus yet",
        "Ranked table",
        "Not comparable — no earlier window to compare with",
        "Star size saturates below {n} mentions — smaller galaxies are drawn at the same minimum size.",
        "Plotted: {plotted} galaxies · not observed in this corpus yet: {unplaced} · "
        "keywords in the nebula, outside every curated galaxy: {nebula} of {total}.",
        "Quarantined articles are held out of this distribution: {n} excluded.",
    ]
    missing: list[str] = []
    for key in required:
        assert key in en, f"en.json is missing the Observatory key {key[:60]!r}"
        for path in locales:
            data = json.loads(path.read_text(encoding="utf-8"))
            if key not in data:
                missing.append(f"{path.name}:{key[:50]!r}")
    assert not missing, "locale files missing Observatory keys: " + ", ".join(missing)


def test_templates_keep_their_placeholders_in_every_locale() -> None:
    """A `{placeholder}` with no matching var renders a literal `{x}` to the reader,
    and a translation that drops or renames one is a broken frame no rendering check
    would catch. Compare the placeholder SETS, not the sentences."""
    import re

    base = _STATIC / "locales"
    en = json.loads((base / "en.json").read_text(encoding="utf-8"))
    templates = {k for k in en if "{" in k and "Observatory" not in k}
    observatory = {k for k in templates if any(
        w in k for w in ("galaxies", "galaxy", "Star size", "centre", "member keyword",
                         "previous window", "nebula", "Quarantined")
    )}
    assert observatory, "no Observatory templates found -- this guard would be vacuous"
    problems: list[str] = []
    for path in sorted(base.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in observatory:
            want = set(re.findall(r"\{(\w+)\}", key))
            got = set(re.findall(r"\{(\w+)\}", data.get(key, "")))
            if want != got:
                problems.append(f"{path.name}: {key[:40]!r} wants {sorted(want)} got {sorted(got)}")
    assert not problems, "broken template frames:\n" + "\n".join(problems)
