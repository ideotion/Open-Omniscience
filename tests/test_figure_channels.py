"""Series identity must never rest on colour alone (GUI visualization plan, F1).

WHY THIS FILE EXISTS. A multi-series ooChart used to be told apart by colour and
nothing else: a four-entry palette indexed ``i % 4``, a solid stroke, a solid legend
swatch. Two things made that measurably wrong rather than merely unfashionable:

  * On ``--panel2`` — the background the ooChart canvas actually paints — three of
    those four colours were BELOW the WCAG 1.4.11 3:1 non-text bar (``--ok`` 2.86:1
    on dawn, ``--warn`` 2.76:1 on solar, ``--err`` 2.41:1 on solar).
  * The worst mutual contrast between two of the six replacement colours is 1.00:1,
    i.e. luminance-IDENTICAL. Pulling each hue toward ``--fg`` to clear the
    background bar necessarily converges them, so colour cannot be the channel that
    separates them — in greyscale, to a colour-blind reader, or at ``i == 4`` where
    the old cycle wrapped series 5 onto series 1.

So the dash pattern and the marker shape are load-bearing and colour is redundant,
which is what these guards pin. They are deliberately SCOPED to the function bodies
they name (``tests/js_source_helper.function_body``) rather than searching the whole
21,000-line file: a whole-file substring assertion is only as strong as that string's
uniqueness, and this repo has shipped guards that passed against a different call
site than the one they were named for.
"""

from __future__ import annotations

import re

from tests.js_source_helper import (
    array_literal,
    css_rule,
    function_body,
    read_static,
    strip_comments,
)

APP = read_static("app.js")
# CSS comments are stripped before any token assertion. The token block's own comment
# opens "/* --fig-1..--fig-6: the CATEGORICAL CHART SERIES set…", so a naive
# `--fig-6:([^;]+);` search matches the PROSE and reports a correct declaration as a
# hardcoded hue — the same comment-satisfied-guard trap this repo has hit repeatedly,
# arriving from the other direction.
CSS = re.sub(r"/\*.*?\*/", "", read_static("app.css"), flags=re.S)


def test_six_series_styles_each_pair_a_colour_with_a_dash_and_a_marker():
    """Six slots, not four: at i == 4 the old cycle made series 5 identical to
    series 1 in every channel it had."""
    src = array_literal(APP, "_FIG_STYLES")
    entries = re.findall(r"\{color:\s*\"var\((--fig-\d)\)\",\s*dash:\s*\[([^\]]*)\],"
                         r"\s*marker:\s*\"(\w+)\"\}", src)
    assert len(entries) == 6, f"expected six series slots, parsed {len(entries)}"
    tokens = [e[0] for e in entries]
    assert tokens == [f"--fig-{i}" for i in range(1, 7)], tokens
    markers = [e[2] for e in entries]
    assert len(set(markers)) == 6, f"marker shapes must all differ: {markers}"
    # A diamond is a rotated square; at a few pixels across they are the same blob.
    assert not ({"square", "diamond"} <= set(markers)), (
        "square and diamond are the same shape rotated — do not use both"
    )
    dashes = [tuple(float(x) for x in e[1].split(",") if x.strip()) for e in entries]
    assert dashes[0] == (), "slot 1 is the solid reference line"
    assert len({d for d in dashes}) == 6, f"dash patterns must all differ: {dashes}"


def test_no_two_dash_patterns_are_the_same_rhythm():
    """The first cut used [2,3] and [1,3] — both read as "the dotted one", since a
    1px difference in dot length is not perceptible — and [11,3,2,3] against
    [4,3,1,3], both dash-dot. Distinct NUMBERS are not distinct patterns.

    The signature is the ORDERED sequence of mark-length classes (dot / short / long),
    which is what the eye actually reads. Two patterns sharing it are the same family.
    """
    src = array_literal(APP, "_FIG_STYLES")
    dashes = [tuple(float(x) for x in m.split(",") if x.strip())
              for m in re.findall(r"dash:\s*\[([^\]]*)\]", src)]
    def cls(mark: float) -> str:
        return "dot" if mark < 3 else ("short" if mark < 6 else "long")

    sigs = []
    for d in dashes:
        if not d:
            sigs.append(("solid",))
            continue
        # The perceptual signature is the ORDERED sequence of mark-length CLASSES.
        # It catches both ways two patterns collide: the same class sequence at a
        # different scale ([1.5,3.5] vs [3,7] are both uniform-dotted, and doubling a
        # pattern does not make it a new one), and the same segment count with the
        # same shape ([9,4,2,4] vs [4,3,1,3], both long-then-dot). It deliberately
        # does NOT collide on order, so a dash-dot and a dot-dash are distinct.
        sigs.append(tuple(cls(m) for m in d[::2]))
    assert len(set(sigs)) == len(sigs), (
        "two dash patterns share a rhythm family and will read as the same pattern: "
        f"{list(zip(dashes, sigs, strict=True))}"
    )


def test_ooChart_strokes_the_series_dash_and_draws_its_marker_shape():
    """The load-bearing pair, asserted inside ooChart's own body."""
    body = function_body(APP, "ooChart")
    assert "ctx.setLineDash(st.dash)" in body, (
        "the series line must be stroked with its own dash pattern"
    )
    assert "_figMarkerCanvas(ctx, st.marker" in body, (
        "each plotted point must carry the series' own marker SHAPE"
    )
    assert "s.style || _figStyle(" in body, "each series must resolve a style"


def test_ooChart_no_longer_cycles_four_raw_semantic_tokens():
    """The old palette also read good/bad on a NEUTRAL count series — the same
    fabricated semantics dashChartSvg's opts.neutral exists to avoid.

    Comment-stripped, because the comment that RECORDS the removal necessarily
    quotes the removed thing (this repo has failed three guards that way)."""
    body = strip_comments(function_body(APP, "ooChart"))
    assert '["var(--accent)", "var(--ok)", "var(--warn)", "var(--err)"][i % 4]' not in body
    assert "_figStyle(i).color" in body, "the default colour comes from the series set"


def test_the_legend_is_a_button_with_a_real_listener_not_an_inline_handler():
    """Two properties in one place. The inline ``onclick="this._oo&&this._oo()"``
    added to the 'unsafe-inline' script-src debt this work must not deepen — AND
    ``elm._oo`` was only ever ASSIGNED, never attached, so dropping the attribute
    without adding a listener would have left the toggle silently dead."""
    body = strip_comments(function_body(APP, "ooChart"))
    assert "onclick=" not in body, "no inline handler in the legend"
    assert 'class="fig-leg"' in body and "<button" in body, (
        "the legend entry is a real button (keyboard-reachable, aria-pressed)"
    )
    assert 'addEventListener("click", elm._oo)' in body, (
        "the toggle needs a REAL listener: elm._oo alone is a property nothing calls"
    )
    assert "aria-pressed=" in body, "the toggle must announce its state"


def test_the_legend_glyph_shows_the_pattern_it_is_teaching():
    """A key that cannot show the pattern cannot teach it. The marker sat centred on
    a 30px swatch, exactly over the stretch where a dash-dot cycle shows its
    distinguishing detail, so slot 4 rendered as two solid runs with the whole
    pattern hidden behind the glyph."""
    body = function_body(APP, "_figGlyph")
    assert "stroke-dasharray=" in body, "the glyph must draw the series' dash"
    m = re.search(r"const c = st\.color, mx = (\d+)", body)
    assert m, "the glyph must place its marker at a named x"
    mx = int(m.group(1))
    line = re.search(r'<line x1="0" y1="7" x2="(\d+)"', body)
    assert line, "the glyph must draw a rule for the dash to run along"
    assert mx >= int(line.group(1)) - 2, (
        f"the marker (x={mx}) must sit at the END of the {line.group(1)}px rule, not "
        "over the middle of it, or it hides the pattern"
    )


def test_every_series_token_is_theme_derived_and_never_a_hardcoded_hue():
    """The --caveat lesson: a fixed hue failed contrast on 8 of 17 themes. Every
    figure token is a color-mix over that theme's OWN variables."""
    for i in list(range(1, 7)):
        m = re.search(rf"--fig-{i}:([^;]+);", CSS)
        assert m, f"--fig-{i} must be defined"
        val = m.group(1).strip()
        assert val.startswith("color-mix("), f"--fig-{i} must be derived, got {val!r}"
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", val), (
            f"--fig-{i} must not contain a hardcoded hue: {val!r}"
        )
    gap = re.search(r"--fig-gap:([^;]+);", CSS)
    assert gap and gap.group(1).strip().startswith("color-mix("), "--fig-gap too"


def test_the_absence_hatch_is_a_texture_and_not_a_colour():
    """An absence must be distinguishable from a measured zero WITHOUT relying on
    telling two colours apart, so the cue is a shape (diagonal hatch)."""
    body = function_body(APP, "figGapDefs")
    assert "<pattern" in body and "rotate(45)" in body, "the cue is a hatch pattern"
    assert "var(--fig-gap)" in body, "stroked with the dedicated token"
    # The two shipped hatches stroked var(--border), which measures 1.20:1 against
    # --panel on garnet — the honesty instrument was itself near-invisible.
    assert "var(--border)" not in body, (
        "var(--border) is too faint for a state cue (1.20:1 on garnet)"
    )


def test_the_grouped_bar_clamp_keeps_every_sub_slot_distinct():
    """The bug this pins actually shipped for one iteration: clamping each series'
    OWN x0 made series 0 and series 1 both land on padL at the first time slot, so
    one drew over the other and a real measurement was invisible — and not hatched.
    Clamp the GROUP, then offset within it."""
    body = strip_comments(function_body(APP, "ooChart"))
    assert re.search(r"const g0 = nS > 1\s*\?\s*Math\.max\(padL, Math\.min\(cx - slot / 2,"
                     r" W - padR - slot\)\)", body), (
        "the GROUP's left edge is what gets clamped"
    )
    assert "const x0 = g0 + si * bw;" in body, "each series offsets within the group"
    assert not re.search(r"x0 = Math\.max\(padL, Math\.min\(x0", body), (
        "clamping each series' own x0 collapses two sub-slots onto the same pixel"
    )


def test_the_legend_uses_a_gap_not_whitespace_between_flex_items():
    """A flex container discards the whitespace between its items, so the space in
    `${label} <span>n=…</span>` vanished and the legend read "series 1n=40"."""
    rule = css_rule(CSS, ".fig-leg")
    assert "display:inline-flex" in rule.replace(" ", "")
    m = re.search(r"gap:\s*(\d+)px", rule)
    assert m and int(m.group(1)) > 0, f"the legend needs a real gap, got {rule!r}"


def test_the_figure_meta_panel_renders_the_envelope_shape_visibly():
    """"Every displayed figure carries its method, its caveat and its n" was 41
    hand-built sites and no component. It must also be VISIBLE by default — never
    behind a toggle (the informed-consent non-negotiable)."""
    body = function_body(APP, "figMeta")
    for field in ("method", "caveat", "n", "basis", "as_of"):
        assert f"env.{field}" in body, f"figMeta must render {field}"
    assert "hidden" not in body, "the panel is visible by default, never toggled"
    # n === 0 is a real measurement ("nothing matched") and must print.
    assert "env.n != null" in body, (
        "only an ABSENT n is omitted; n === 0 is a measurement and must render"
    )
    # Each basis value needs its own fixed key, or the disclosure cannot translate.
    for lab in ("verified against the corpus", "counted live just now",
                "from a maintained counter — may have drifted"):
        assert lab in body, f"the basis label {lab!r} must be a translatable literal"


def test_figMeta_puts_the_method_sentence_in_its_own_element():
    """The i18n walker matches a text node EXACTLY, so `Method: <sentence>` as one
    text node is not a key and renders in English in all 11 non-English locales —
    for the very text that carries the figure's honesty. Caught by screenshotting the
    panel in Arabic."""
    body = function_body(APP, "figMeta")
    assert 'esc(t9("Method"))}:</span>' in body, (
        "the label and the sentence must be separate elements, each an exact key"
    )
    assert re.search(r'<span class="fig-method">\$\{esc\(env\.method\)\}</span>', body), (
        "the method sentence must be alone in its element"
    )


def test_the_composition_figures_re_render_on_a_language_change():
    """The same frozen-locale bug class as the Home Lead titles: a Library view
    renders ONCE, and an already-interpolated OOI18N.tf() string is no longer a key,
    so it stays in whatever locale first rendered it."""
    assert '_libViewLoaded.has("composition")' in APP
    assert "renderCompositionFigures();" in APP
    at = APP.index('document.addEventListener("oo:langchange"')
    handler = APP[at : at + 4000]
    assert "renderCompositionFigures" in handler, (
        "the figures must be re-rendered by the oo:langchange handler"
    )
