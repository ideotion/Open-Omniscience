"""
Source guards for the 2026-08-20 browser-verification matrix session (gate row 8's
stretch matrix — docs/audit/UI_CLICKTHROUGH_2026-08-20.md).

Each guard follows the house source-guard discipline: comment-STRIPPED source (a rule's
explanatory comment necessarily quotes the rule's own vocabulary, in both the must-be-
present and must-be-absent directions — both recorded lessons), block-SCOPED slicing via
real brace matching (never a whole-file substring), and every must-be-absent assertion
paired with the reason it is absent in the test's own docstring rather than in a comment
the guard could trip on.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"


def _css() -> str:
    return (_SRC / "static" / "app.css").read_text(encoding="utf-8")


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _media_blocks(css: str, query_snippet: str) -> list[str]:
    """Every ``@media`` block whose query contains ``query_snippet``, body sliced by REAL
    brace matching from the block's own opening brace (a guessed end delimiter is the
    recorded mis-slice trap; CSS has no braces inside strings in this stylesheet, so a
    depth counter over comment-stripped source is exact)."""
    blocks: list[str] = []
    for m in re.finditer(r"@media[^{]*\{", css):
        if query_snippet not in m.group(0):
            continue
        depth = 1
        i = m.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        blocks.append(css[m.end() : i - 1])
    return blocks


def _phone_topbar_block() -> str:
    """The T1 phone block: of the (max-width:600px) media blocks, the one that carries the
    status-cluster collapse. Asserting it EXISTS is part of the guard."""
    stripped = _strip_css_comments(_css())
    candidates = [b for b in _media_blocks(stripped, "max-width:600px") if ".status-cluster" in b]
    assert candidates, (
        "the T1 phone top-bar block is gone: no @media (max-width:600px) block styles "
        ".status-cluster — the 375px overflow (measured 452px scrollWidth from the "
        "cluster's 434px nowrap min-content while the activity chip is visible) regresses "
        "without it (docs/audit/UI_CLICKTHROUGH_2026-08-20.md, T1)"
    )
    assert len(candidates) == 1, "expected exactly one phone block styling .status-cluster"
    return candidates[0]


def test_t1_phone_topbar_collapse_block() -> None:
    """T1 (2026-08-20): the 375px overflow fix. The status cluster must WRAP internally and
    the two informational footprints must collapse to SMALLER CONSTANTS at phone width —
    still fixed sizes, so invariant #3's real property (a text change never reflows its
    neighbours) holds per breakpoint. Nothing may be hidden: the fix collapses, never
    removes (controls are commitments)."""
    block = _phone_topbar_block()
    flat = block.replace(" ", "")
    cluster = block.split(".status-cluster", 1)[1].split("}", 1)[0]
    assert "flex-wrap:wrap" in cluster.replace(" ", ""), (
        ".status-cluster must wrap internally at phone width — its nowrap min-content "
        "(160px act-host + 110px health + 46px llm + gaps = 434px) is the measured 375px "
        "overflow mechanism"
    )
    acthost = block.split(".act-host", 1)[1].split("}", 1)[0].replace(" ", "")
    assert re.search(r"width:\d+px", acthost), (
        ".act-host's phone footprint must stay a FIXED pixel constant (a smaller slot), "
        "never auto — invariant #3's no-reflow-as-labels-change property holds per "
        "breakpoint only while the footprint is constant"
    )
    health = block.split("#health", 1)[1].split("}", 1)[0].replace(" ", "")
    assert "max-width" in health and "text-overflow:ellipsis" in health, (
        "#health must ellipsize at phone width (full text stays on its hover title), "
        "never push the row wide"
    )
    assert "display:none" not in flat, (
        "the phone block must never HIDE an element — the T1 strategy is collapse+wrap; "
        "controls and status readouts all stay rendered (controls are commitments)"
    )


def test_t1_phone_grid_track_clamp() -> None:
    """T1: every tab page is a single-column grid whose IMPLICIT auto track is
    content-sized, so one panel's intrinsic width silently widened the whole page (the
    Agenda panel's track measured 486px in a 375px viewport). minmax(0,1fr) pins the
    track at phone width."""
    block = _phone_topbar_block()
    flat = block.replace(" ", "")
    assert ".tab-page.active{grid-template-columns:minmax(0,1fr)" in flat, (
        "the tab-page grid track must be pinned with minmax(0,1fr) at phone width — an "
        "auto track is content-sized and lets any panel's intrinsic width scroll the page"
    )


def test_t1_phone_row_children_shrinkable_and_contain_trap_stays_out() -> None:
    """T1: .row > div must be shrinkable (min-width:0, the flexbox escape) and form
    controls clamped, and `contain:inline-size` must stay OUT of the phone block: it
    zeroes any wrapper whose flex-basis is auto with no grow (flex:0 0 auto — the
    Insights Explore-button wrapper), and the un-containable button then protrudes from
    a 0px box. That regression was measured live in this session before the rule was
    replaced; this guard reads comment-stripped source precisely so the CSS comment
    recording the trap cannot satisfy or trip it."""
    block = _phone_topbar_block()
    flat = block.replace(" ", "")
    assert ".row>div{min-width:0" in flat, (
        ".row > div needs min-width:0 at phone width (the 140px min-width two-up is the "
        "measured row min-content overflow)"
    )
    assert "max-width:100%" in flat and ".rowselect" in flat.replace(",", ""), (
        "form controls in rows must clamp to their container at phone width (a select "
        "sizes to its longest option and never shrinks below it — measured 452px "
        "intrinsic on the Agenda country picker)"
    )
    assert "contain:inline-size" not in flat, (
        "contain:inline-size must stay OUT of the phone block — it zero-widths any "
        "no-grow auto-basis wrapper (measured: the Insights Explore button protruding "
        "from a 0px box) — see this test's docstring for the mechanism"
    )


def test_t1_base_topbar_invariants_untouched() -> None:
    """T1 must not weaken the base (all-widths) invariant-#3 rules — the phone block
    OVERRIDES at <=600px; the base constants stay."""
    stripped = _strip_css_comments(_css())
    assert ".act-host:empty { visibility:hidden; }" in stripped
    assert re.search(r"#health\s*\{\s*min-width:110px", stripped)
    topbar_rule = stripped.split(".topbar {", 1)[1].split("}", 1)[0]
    assert "flex-wrap:wrap" in topbar_rule.replace(" ", "")


def test_t1_phone_advanced_section_tables_self_scroll() -> None:
    """The flagship-375 walk (2026-08-20 clean run) found source_management widening the
    page to 478px in a 375 viewport: the discovery-candidates table has no overflow
    wrapper (#src-table does), so its 443px min-content scrolled the BODY — the repo-wide
    rule is that wide content scrolls inside its own container, never the page. The phone
    block's generic rule makes every Settings>Advanced section table a self-scrolling
    block (the stylesheet's own .prose-table convention)."""
    block = _phone_topbar_block()
    flat = block.replace(" ", "")
    assert "details.adv-sectable{display:block" in flat and "overflow-x:auto" in flat, (
        "advanced-section tables must self-scroll at phone width — without this the "
        "candidates table's min-content scrolls the whole page (measured 478px at 375)"
    )


def test_agenda_deduced_events_bypass_the_subscribed_only_filter() -> None:
    """Found by the 2026-08-20 agenda-provenance drill: #agenda-subonly defaults CHECKED
    and agFiltered's bypass named only `imported`, so corpus-DEDUCED events — whose
    synthetic "deduced" calendar can never be subscribed — were invisible in every agenda
    view at default settings while the category filter still offered "deduced" as an
    empty lens. The 2026-06-16 design maps them "like imported events"; the bypass must
    carry both. Sliced by the SHARED brace-matching helper (the slicing-discipline
    ratchet's own prescribed shape) and comment-stripped (the fix's comment quotes the
    vocabulary in both directions)."""
    from tests.js_source_helper import function_body, read_static, strip_comments

    body = strip_comments(function_body(read_static("app.js"), "agFiltered"))
    flat = body.replace(" ", "")
    assert "e.imported||e.deduced||" in flat, (
        "agFiltered's subscribed-only bypass must cover DEDUCED events beside imported "
        "ones — without it the default-checked filter hides the whole deduced category "
        "(its synthetic calendar cannot be subscribed), verified live 2026-08-20"
    )


def test_ai_pill_off_label_text_is_fg_mixed_never_raw_err() -> None:
    """The 2026-08-20 matrix run's theme-axis widening (5 -> 17 themes) found the ai-off
    "AI" label at raw var(--err) below WCAG AA 4.5:1 against the pill's own 8%-err tint
    on 13 of 17 themes (worst solar 2.41:1). The repair is the established theme-derived
    mix toward --fg (the same one the diagonal bar and the state marks carry); 55% is the
    measured smallest 5-point step clearing 4.5:1 on every theme (worst 4.82:1, solar).
    Comment-stripped source, block-scoped: the rule's own comment quotes both the old and
    the new value, so a whole-file or comment-inclusive assertion would pass against a
    revert (the recorded must-be-present-guard trap)."""
    stripped = _strip_css_comments(_css())
    block = stripped.split("#llm.ai-off {", 1)[1].split("}", 1)[0].replace(" ", "")
    assert "color:color-mix(insrgb,var(--fg)55%,var(--err))" in block, (
        "#llm.ai-off's label colour must stay the measured 55% fg-mix — raw var(--err) "
        "fails AA text contrast on 13 of 17 themes against this rule's own pill tint"
    )
    assert "color:var(--err)" not in block, (
        "raw var(--err) must not return as the ai-off label colour (2.41:1 on solar)"
    )
