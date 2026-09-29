"""The Ring dial (0.5 slice S05-09 S4; Q1120 = a, Q1121 = a).

"Interface depth: Essentials · Standard · Full" in Settings -> General, and a depth question
opening the first-run guide. The rule every assertion below serves: a depth changes what is
PINNED, never what is REACHABLE.

- Full is the depth of an install that never chose, so an upgrade un-pins nothing.
- The guide pre-selects Standard, and applies it on every way out, so a skipped question
  gives Standard (Q1121); Essentials only by an explicit choice.
- Essentials pins Ring 0 (Home, Feed) and puts Ring 1 behind a "Show more (N)" row that
  always carries TEXT, in the icon rail too; the open tab always stays listed.
- The top bar and the Settings button are the same at every depth.
- Ring 2 is each Lead's fine-tuning in Settings -> Leads: folded below Full, never removed,
  and never folded over a value that differs from the shipped one.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.js_source_helper import function_body, object_literal

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    return function_body(src, name)


def test_the_dial_sits_in_settings_general_with_three_depths():
    html = _read("index.html")
    general = html[html.index('id="set-general"'): html.index('class="set-view"', html.index('id="set-general"') + 20)]
    assert 'id="set-depth" role="radiogroup"' in general
    assert re.findall(r'name="set-depth" value="(\w+)"', general) == ["essentials", "standard", "full"]
    assert "never what is reachable" in general


def test_an_install_that_never_chose_is_at_full():
    shell = _read("app-shell.js")
    body = _fn(shell, "uiDepth")
    assert 'return DEPTHS.includes(d) ? d : "full";' in body
    assert "depth" not in object_literal(shell, "UI_DEFAULTS"), (
        "a default depth in UI_DEFAULTS would give every existing install that depth on upgrade")
    assert 'r.setAttribute("data-depth", uiDepth(ui));' in _fn(shell, "applyUi")


def test_the_guide_asks_first_preselects_standard_and_applies_it_on_every_way_out():
    core = _read("app-core.js")
    html = _read("index.html")
    assert 'const _GW_STEPS = ["depth", "sources", "finish"];' in core
    step = html[html.index('data-step="depth"'): html.index("</section>", html.index('data-step="depth"'))]
    assert re.findall(r'name="gw-depth" value="(\w+)"( checked)?', step) == [
        ("essentials", ""), ("standard", " checked"), ("full", "")]
    assert ': "standard";' in _fn(core, "_gwRenderDepth")
    # closing (X, Esc, Finish, Stay offline, Go online) all pass through closeGuide
    assert "_gwApplyDepth();" in _fn(core, "closeGuide")
    assert '"depth") _gwApplyDepth();' in core


def test_essentials_hides_only_ring_one_and_never_the_open_tab():
    css = _read("app.css")
    rules = [ln.strip() for ln in css.splitlines() if 'data-depth="essentials"' in ln]
    assert rules == [
        'html[data-depth="essentials"] .nav-more { display:flex; }',
        'html[data-depth="essentials"] #navGroups:not(.more-open) .nav-item[data-ring="1"]:not(.active) { display:none; }',
    ], "a depth rule may only un-pin Ring-1 sidebar tabs and show the Show-more row"
    # no depth rule anywhere touches the top bar or the Settings button
    for sel in ("data-depth",):
        for ln in css.splitlines():
            if sel in ln:
                for protected in ("#net-toggle", "#tm-open", "#lang", ".topbar", ".sb-foot", "#health", "#llm"):
                    assert protected not in ln, f"a depth rule touches {protected}"
    shell = _read("app-shell.js")
    assert 'const RING0_TABS = ["home", "feed"];' in shell


def test_the_show_more_row_always_carries_text():
    html = _read("index.html")
    css = _read("app.css")
    shell = _read("app-shell.js")
    row = html[html.index('id="nav-more"'): html.index("</button>", html.index('id="nav-more"'))]
    assert 'class="nav-more-long"' in row and 'class="nav-more-short"' in row
    assert 'aria-expanded="false"' in row
    # In both rails (collapsed and the 601-860 px automatic one) the SHORT label is drawn.
    assert css.count(".nav-more-short { display:block;") + css.count(".nav-more .nav-more-short { display:block;") >= 2
    paint = _fn(shell, "paintNavMore")
    for key in ('"Show more ({n})"', '"Show fewer"', '"More ({n})"', '"Fewer"'):
        assert key in paint, f"the row lost its {key} label"


def test_ring_two_folds_below_full_but_never_hides_a_changed_value():
    settings = _read("app-settings.js")
    body = _fn(settings, "_cardFineTune")
    assert 'const open = depth === "full" || changed > 0;' in body
    assert '<details class="card-finetune"' in body
    assert "_cardTunableRow(p.name, tn)" in body, "the tunables are folded, never dropped"
    # Saving reads every tunable wherever it sits.
    assert 'document.querySelectorAll("#cards-host .card-tune")' in settings


def test_every_depth_string_is_keyed_x12():
    import json

    keys = [
        "Interface depth", "Essentials", "Standard", "Full", "Show more ({n})", "Show fewer",
        "More ({n})", "Fewer", "Fine-tune ({n})", "{n} changed",
        "How much should the app show at once?",
        "Show the {n} tabs this depth does not pin", "Hide the tabs this depth does not pin",
    ]
    for p in sorted((_STATIC / "locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in keys:
            assert d.get(k, "").strip(), f"{p.name} has no key {k!r}"
            assert sorted(re.findall(r"\{(\w+)\}", d[k])) == sorted(re.findall(r"\{(\w+)\}", k))
