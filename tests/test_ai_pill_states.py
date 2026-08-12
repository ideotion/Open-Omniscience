"""The top-bar AI pill: green when a backend serves, red + crossed when it does not.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer 2026-08-02: "decrease the size of the top bar's AI button, make it red and
crossed (diagonal) when off, keep green when on."

Two states must be readable at a glance, so EVERY branch that is not a serving backend
carries the off marking -- including the one where the health probe itself failed, where
a neutral pill would read as "fine" on no evidence.
"""


from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.js_source_helper import css_rule, function_body, python_function_source, read_static

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def js() -> str:
    return (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return (_ROOT / "src" / "static" / "app.css").read_text(encoding="utf-8")


def _paint_body(js: str) -> str:
    """The painter's body only -- a whole-file search would match any other pill.

    RE-POINTED 2026-08-12 from ``loadLlmHealth`` to ``_paintAiPill``. The fetch and the
    paint were split so a start in flight could outrank a stale health reading, and the
    branch table moved with the paint. The stale-anchor class this repo has been bitten
    by twice: the guard would have failed against correct code, naming a function that
    no longer decides anything."""
    return function_body(js, "_paintAiPill")


def test_every_non_serving_branch_marks_the_pill_off(js):
    """Unchanged in INTENT, re-expressed for the 2026-08-12 structure.

    It used to count three ``"pill warn ai-off"`` literals, one per non-serving branch.
    The painter now reaches the same three cases (hardware-impractical, backend down, and
    the probe itself failing) through two assignments, because the last two share the
    class and differ only in the title they explain it with. Counting literals would
    therefore fail against correct code -- so this asserts the PROPERTY the count was
    standing in for: once the serving branch has returned, nothing may paint the pill
    anything other than off.
    """
    body = _paint_body(js)
    after_serving = body.split("if (h && h.available)", 1)[1]
    # Drop the serving branch itself (it returns), then look at every remaining paint.
    tail = after_serving.split("return;", 1)[1]
    classes = re.findall(r'el\.className\s*=\s*"([^"]+)"', tail)
    assert classes, "the painter must still paint something after the serving branch"
    assert all("ai-off" in c for c in classes), (
        "each non-serving branch must mark the pill off -- including the catch, where a "
        f"neutral pill would claim health the probe never established. Got: {classes}"
    )
    # And the probe-failed case must be reachable rather than merged into "backend down",
    # which would attribute a reason nothing observed.
    assert "if (!h)" in tail, "the failed-probe case must keep its own honest branch"


def test_the_serving_state_stays_green_and_uncrossed(js):
    body = _paint_body(js)
    green = body.split("if (h && h.available)", 1)[1].split("return;", 1)[0]
    assert '"pill ok"' in green
    assert "ai-off" not in green, "a serving backend must never be crossed out"
    # A serving backend that is BUSY is still serving: green, plus the working mark.
    assert '"pill ok ai-busy"' in green, "the working state must stay green, never off"


def test_off_is_red_and_carries_a_diagonal_bar(css):
    rule = css.split("#llm.ai-off {", 1)[1].split("}", 1)[0]
    assert "var(--err)" in rule, "off is RED"
    after = css.split("#llm.ai-off::after {", 1)[1].split("}", 1)[0]
    assert "linear-gradient" in after and "to top right" in after, (
        "the diagonal bar is the non-colour signal -- colour must never be the only one"
    )


def test_every_colour_is_theme_derived(css):
    """A hardcoded hue failed 8/17 themes when --caveat was introduced. The pill is
    painted from --err through color-mix, exactly as .pill.err already is."""
    # Scoped to the pill's OWN rules. Bounding "whole" by splitting on the next
    # selector that came to mind took 820 lines of app.css, in which var(--border)
    # occurs 73 times -- so the assertion held for the stylesheet at large and could
    # not have caught a hardcoded hue in the pill, the one regression it names.
    block = css_rule(css, "#llm.ai-off::after")
    whole = "".join(css_rule(css, sel) for sel in ("#llm", "#llm.ai-off", "#llm.ai-off::after"))
    assert "#" not in block, "no hex literals in the bar"
    for token in ("var(--err)", "var(--border)", "var(--panel2)"):
        assert token in whole, f"{token} must come from the theme"


def test_the_pill_is_smaller_but_still_a_FIXED_footprint(css):
    """Invariant #3: top-bar elements keep constant footprints so nothing to their right
    shifts. The label is a constant "AI", so a smaller fixed width is safe -- 96px was
    sized for the old "<N> LLM" text and has been oversized since the count was dropped."""
    rule = css.split("#llm {", 1)[1].split("}", 1)[0]
    assert "min-width:" in rule, "the fixed footprint must survive (invariant #3)"
    px = int(rule.split("min-width:", 1)[1].split("px", 1)[0].strip())
    assert px < 96, "the ask was to make it smaller"
    assert px >= 34, "still wide enough for the label plus the bar, at a constant width"


# ------------------------------------------------------------------------- #
#  2026-08-12: the two states the pill could not express -- starting, and working
# ------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_ai_pill_settle_node_suite() -> None:
    """Driver for the fake-clock suite. Without one the file is documentation: the
    ratchet in test_import_conclusion.py exists because an orphan suite already cost a
    shipped defect."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "ai_pill_settle_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


# --------------------------------------------------------------------------- #
#  The states must survive being FROZEN
# --------------------------------------------------------------------------- #
def test_each_state_carries_a_shape_not_only_motion_and_colour() -> None:
    """THE ONE THAT MATTERS FOR ACCESSIBILITY. app.css disables every animation under
    ``prefers-reduced-motion: reduce`` with one global rule -- so a state expressed by
    movement alone simply VANISHES for those readers, and colour alone was never
    allowed either (the pill's own off-state uses a diagonal bar for exactly this
    reason).

    So each new state owes a static mark that reads frozen and in greyscale: a dot
    under the label while starting, an arc beneath it while working.
    """
    css = read_static("app.css")

    dot = css_rule(css, "#llm.ai-starting::after")
    assert "border-radius:50%" in dot.replace(" ", ""), "the starting dot must be a dot"
    assert "background:" in dot, "a shape with no paint is not a shape"

    arc = css_rule(css, "#llm.ai-busy::after")
    assert "height:2px" in arc.replace(" ", ""), "the working arc must have a thickness"
    assert "background:" in arc, "a shape with no paint is not a shape"

    # The two must not resolve to the same mark, or the states are distinguishable in
    # motion and identical without it -- which is the failure this test exists for.
    assert dot != arc


def test_the_breathing_tint_is_still_visible_when_the_animation_is_frozen() -> None:
    """``animation: none`` leaves the element's own declarations standing. If the base
    opacity lived only inside the keyframes, freezing would paint the overlay at its
    default opacity of 1 -- a solid slab over the label rather than a tint."""
    rule = css_rule(css := read_static("app.css"), "#llm.ai-starting::before")
    assert "opacity:.35" in rule.replace(" ", ""), (
        "the base opacity must be on the element, not only in the keyframes, or the "
        "frozen state is a solid block"
    )
    assert "@keyframes oo-ai-breathe" in css, "the motion layer must exist too"


def test_every_pill_mark_resets_what_the_tip_marker_would_leak() -> None:
    """THE ONE THAT CAUGHT A SHIPPED BUG. ``.pill.oo-tip-target::after`` is the
    hover-convention's 4px corner dot, and the pill carries a title in every state, so
    that class is always present. The cascade merges per PROPERTY: a state's own
    ``::after`` wins on specificity for what it DECLARES and silently inherits what it
    does not.

    ``#llm.ai-off::after`` declared ``inset:0`` and nothing else, so ``width:4px;
    height:4px; border-radius:50%; opacity:.55`` leaked in -- and an absolutely
    positioned box with left, right AND width all set ignores ``right``. The
    maintainer's ruled "red WITH A DIAGONAL BAR" was therefore rendering as a 4x4
    rounded dot in the top-left corner at 55% opacity, over which a 50%-stop gradient is
    invisible. Measured in Chromium: the bar had not been drawn since the pill gained a
    title.

    So every mark on this element must declare all four, or the next one inherits the
    same dot.
    """
    css = read_static("app.css")
    for sel in ("#llm.ai-off::after", "#llm.ai-starting::after", "#llm.ai-busy::after"):
        # STRIP THE COMMENTS FIRST. Caught by mutation, and it is the ledger's recorded
        # trap in mirror image: a "must be ABSENT" guard trips on the comment explaining
        # the removal, and this "must be PRESENT" one was SATISFIED by the comment
        # explaining the fix -- which quotes `width:4px; height:4px; border-radius:50%;
        # opacity:.55` verbatim to say what leaks. Deleting the real declarations left
        # the guard green. Rewording the comment would be the wrong repair: it is what a
        # future session reads before deciding these resets are redundant.
        rule = _strip_css_comments(css_rule(css, sel)).replace(" ", "")
        for prop in ("width:", "height:", "border-radius:", "opacity:"):
            assert prop.replace(" ", "") in rule, (
                f"{sel} does not declare {prop!r}, so it inherits the tip marker's value "
                "for it -- the defect that hid the off-state's diagonal bar entirely"
            )


def _strip_css_comments(css: str) -> str:
    import re

    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_no_state_hardcodes_a_hue() -> None:
    """A hardcoded hue failed 8 of 17 themes when --caveat was introduced. Every colour
    here is derived from a theme token through color-mix, so a theme cannot be left with
    an unreadable pill."""
    css = read_static("app.css")
    for sel in (
        "#llm.ai-starting",
        "#llm.ai-starting::before",
        "#llm.ai-starting::after",
        "#llm.ai-busy::after",
        "#llm.ai-busy::before",
    ):
        rule = css_rule(css, sel)
        assert "#" not in rule.split("{", 1)[-1], f"{sel} carries a literal hex colour"
        assert "rgb(" not in rule and "hsl(" not in rule, f"{sel} carries a literal colour"


def test_the_label_never_changes_so_the_footprint_never_moves() -> None:
    """Invariant #3: the top bar's chips keep a constant footprint, so nothing to their
    right shifts. Every branch of the painter writes the same constant label."""
    body = _js_function("_paintAiPill")
    assert body.count('el.textContent = "AI"') == 1, (
        "the label must be set once, unconditionally -- a per-state label is a per-state "
        "width"
    )
    for state in ('"pill ai-starting"', '"pill ok ai-busy"', '"pill ok"', '"pill warn ai-off"'):
        assert state in body, f"the painter must be able to reach {state}"


def test_the_starting_state_outranks_a_stale_health_reading() -> None:
    """We know we just asked for a start, which makes any earlier "offline" reading
    stale by definition. Showing red through a start we ourselves triggered is what made
    the old pill read as "it didn't work"."""
    body = _js_function("_paintAiPill")
    starting_at = body.index("if (_aiStarting)")
    health_at = body.index("h.available")
    assert starting_at < health_at, (
        "the starting branch must be tested BEFORE the last health reading, or a stale "
        "offline reading paints over a start in progress"
    )


# --------------------------------------------------------------------------- #
#  The "working" signal is counted at the seam, not enumerated
# --------------------------------------------------------------------------- #
def test_both_clients_count_at_the_generate_seam() -> None:
    """An enumeration of "the things that run models" is wrong the day someone adds a
    caller and does not think of this file -- the recorded shape of the airplane
    backstop's own hole. Counting at ``generate()`` covers callers that do not exist
    yet, so BOTH implementations must be instrumented, not whichever one was in front
    of the author."""
    for mod, backend in (
        ("src/llm/ollama.py", "ollama"),
        ("src/llm/vllm_client.py", "vllm"),
    ):
        src = (_ROOT / mod).read_text(encoding="utf-8")
        body = python_function_source(src, "generate")
        assert "from src.llm.inflight import generating" in body, f"{mod} does not count"
        assert f'generating(model, backend="{backend}")' in body, (
            f"{mod} must name its own backend, or the report cannot say which is busy"
        )


def test_a_failed_call_still_clears() -> None:
    """A leaked entry pins the pill on "working" forever, which is a worse lie than
    showing nothing. The decrement is in a finally, so a raising call clears too."""
    from src.llm.inflight import _reset_for_tests, generating, inflight

    _reset_for_tests()
    assert inflight()["n"] == 0
    with pytest.raises(RuntimeError):
        with generating("m", backend="ollama"):
            assert inflight()["n"] == 1
            raise RuntimeError("the backend fell over mid-call")
    assert inflight()["n"] == 0, "a call that raised is not a call still running"


def test_it_counts_concurrent_calls_and_names_their_models() -> None:
    from src.llm.inflight import _reset_for_tests, generating, inflight

    _reset_for_tests()
    with generating("mistral", backend="vllm"), generating("ministral", backend="vllm"):
        snap = inflight()
        assert snap["n"] == 2
        assert snap["models"] == ["ministral", "mistral"]
        assert snap["oldest_elapsed_s"] is not None
    assert inflight()["n"] == 0


def test_it_reports_no_progress_because_a_model_gives_none() -> None:
    """The counter knows how many calls are open and how old the oldest is. It does not
    know how far along any of them is, and a bar drawn from that gap would be a
    fabricated measurement on a status pill."""
    from src.llm.inflight import _reset_for_tests, generating, inflight

    _reset_for_tests()
    with generating("m", backend="ollama"):
        snap = inflight()
    banned = ("percent", "progress", "eta", "remaining", "score", "total")
    for key in snap:
        assert not any(w in key.lower() for w in banned), (
            f"{key!r} promises something a model never reports"
        )


def _js_function(name: str) -> str:
    from tests.js_source_helper import function_body

    return function_body(read_static("app.js"), name)
