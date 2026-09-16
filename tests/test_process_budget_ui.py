"""S04-13's UI half: the budget panel (S1), the net-coach weights (S4), the title (S5).

Three rulings meet here because they share one property -- the words a user reads --
and each is guarded at the level that can actually see its defect:

  * S1's PANEL is behavioural (``process_budget_panel_node_test.js``), because every
    refusal it makes is one character from its opposite in source and no grep can
    tell a null check from a truthiness test;
  * S4's WEIGHTS are a CSS-class fact, which source can see exactly;
  * S5's TITLE is a string swap, where the thing worth pinning is that the key
    really is translated everywhere and that the weaker claim is gone.

The x12 check is here rather than left to the i18n ratchets on purpose: those are
MAX gates, so a shrinking population and an improving codebase move them the same
way (the recorded max-gate blindness). "The gate is green" is no evidence that
THESE strings are covered, so they are named.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

def _budget_strings() -> list[str]:
    """Every string the budget panel can render, READ OUT OF THE PANEL.

    A hand-mirrored list is the thing this function exists not to be. It agreed with
    the renderer the day it was written -- verified string by string -- and from then
    on a copy in a test file is a claim about code it cannot see: add a note to
    ``_budgetHtml`` and the x12 check below simply stops covering it, silently and
    green. Deriving the list means a string that is added is a string that is
    checked.

    Comment-stripped first, because the renderer's comments quote the copy they
    explain, and a quoted example is not a rendered string.
    """
    import re

    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "_budgetHtml"))
    # ``t9`` and ``tf`` are the function's own two locals (t9 = translate, tf =
    # translate-with-data). Matching the CALL rather than every double-quoted run
    # keeps CSS class names and HTML fragments out.
    found = re.findall(r'\bt(?:9|f)\(\s*"((?:[^"\\]|\\.)*)"', body)
    out: list[str] = []
    for s in found:
        if s not in out:
            out.append(s)
    # An empty or collapsed population is how a derived list fails OPEN: rename the
    # helpers, or move the copy into a shared table, and every x12 assertion below
    # becomes a loop over nothing that passes. The floor is the count at the time of
    # writing; raise it deliberately, and never lower it to make a refactor green
    # without checking where the strings went.
    assert len(out) >= 9, (
        f"only {len(out)} translatable strings found in _budgetHtml -- the panel's "
        "copy moved, so the x12 checks below are no longer covering it"
    )
    return out


_BUDGET_STRINGS = _budget_strings()

#: Q1126 = a. The stronger, TRUE claim the task manager now makes.
_AIRPLANE_ONLINE_TITLE = (
    "Online — click to go offline (airplane mode); every new network request "
    "will be refused."
)
#: The weaker claim it replaced. True, and an under-statement of the operator's own
#: protection -- the kill switch refuses every new request process-wide, not only
#: the collector's.
_AIRPLANE_OLD_TITLE = "Online — click to go offline (airplane mode); stops all collection."


# --------------------------------------------------------------------------- #
# S1 -- the panel
# --------------------------------------------------------------------------- #


def test_budget_panel_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "process_budget_panel_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_budget_string_is_keyed_in_all_twelve_locales() -> None:
    missing: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        # encoding= is not optional: the tree's utf8 guard scans for it, and on a
        # cp1252 default these files (curly quotes, em dashes, Arabic isolates)
        # would CRASH the read rather than fail an assertion.
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _BUDGET_STRINGS:
            if s not in data:
                missing.append(f"{path.name}: {s[:48]!r}")
            elif not str(data[s]).strip():
                missing.append(f"{path.name}: {s[:48]!r} is EMPTY")
    assert not missing, "budget strings missing from locales:\n  " + "\n  ".join(missing)


def test_the_arabic_rate_strings_carry_a_bidi_isolate() -> None:
    """``kbit/s`` is a punctuation-joined LTR run inside RTL text.

    Without U+2068/U+2069 it renders in visual order -- the recorded ISO-timestamp
    defect, where an Arabic reader sees the parts of a value in the wrong order and
    MISREADS it rather than merely finding it ugly. The isolates are plain
    characters, so they survive ``esc()`` and are inert in every LTR locale.
    """
    ar = json.loads((_LOCALES / "ar.json").read_text(encoding="utf-8"))
    for s in _BUDGET_STRINGS:
        if "kbit/s" not in s:
            continue
        value = ar[s]
        assert "⁨" in value and "⁩" in value, (
            f"ar has no FIRST STRONG ISOLATE / POP DIRECTIONAL ISOLATE around the "
            f"LTR unit run in {s[:48]!r}"
        )


def test_the_panel_is_wired_into_the_vitals_render() -> None:
    """A renderer nothing calls is the recorded dead end, and the node suite above
    would pass just as happily against an unreachable function."""
    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "_renderVitals"))
    assert "_budgetHtml(" in body, (
        "_renderVitals no longer calls _budgetHtml -- the panel is unreachable"
    )


# --------------------------------------------------------------------------- #
# S4 -- Q1125: both actions carry equal visual weight
# --------------------------------------------------------------------------- #


def test_net_coach_actions_carry_equal_visual_weight() -> None:
    """"Not now" must not be quieter than "Go online".

    ``.secondary`` is a flatter panel background, a 1px border and font-weight 500
    against an unclassed primary -- a real difference in emphasis on a surface whose
    whole subject is a network-consent decision. Staying offline is a first-class
    answer and has to look like one.

    Scoped to the coach block rather than the file: ``.secondary`` is legitimate on
    dozens of other buttons, so a whole-file assertion would be the recorded
    non-unique-needle trap.
    """
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    start = html.index('<div id="net-coach"')
    block = html[start : html.index("</div>", html.index("coach-actions", start))]
    assert 'id="net-coach-dismiss"' in block and 'id="net-coach-go"' in block

    def classes(button_id: str) -> str:
        at = block.index(f'id="{button_id}"')
        tag = block[block.rindex("<button", 0, at) : block.index(">", at)]
        return tag

    dismiss, go = classes("net-coach-dismiss"), classes("net-coach-go")
    assert "secondary" not in dismiss, (
        "the dismiss button is still .secondary, i.e. quieter than 'Go online' "
        "(Q1125 = a)"
    )
    # Equal weight is a claim about BOTH, so assert the pair rather than one side:
    # moving .secondary onto 'Go online' would satisfy a one-sided check while
    # making the coachmark unequal in the other direction.
    assert ("secondary" in dismiss) == ("secondary" in go), (
        "the two coach actions carry different emphasis classes"
    )


# --------------------------------------------------------------------------- #
# S5 -- Q1126 = a: the task manager's airplane title
# --------------------------------------------------------------------------- #


def test_the_task_manager_online_title_makes_the_stronger_true_claim() -> None:
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    assert f't("{_AIRPLANE_ONLINE_TITLE}")' in tm, (
        "the task manager does not paint the stronger claim Q1126 ruled"
    )


def test_the_weaker_claim_is_gone_from_the_code_and_from_every_locale() -> None:
    """Both halves. The old key was used by exactly one call site, so leaving it in
    the locales would orphan eleven translations -- and a future reader would have no
    way to tell an orphan from a live string."""
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    # The removal's own explanation quotes the retired wording, so assert the CALL
    # rather than the words: the recorded "a must-be-gone guard trips on the comment
    # that records the removal" trap, in its silent direction.
    assert f't("{_AIRPLANE_OLD_TITLE}")' not in tm

    still_there = [
        p.name
        for p in sorted(_LOCALES.glob("*.json"))
        if _AIRPLANE_OLD_TITLE in json.loads(p.read_text(encoding="utf-8"))
    ]
    assert not still_there, f"orphaned translation left in: {still_there}"


def test_the_stronger_title_is_translated_in_all_twelve_locales() -> None:
    missing = [
        p.name
        for p in sorted(_LOCALES.glob("*.json"))
        if not str(
            json.loads(p.read_text(encoding="utf-8")).get(_AIRPLANE_ONLINE_TITLE, "")
        ).strip()
    ]
    assert not missing, f"the re-keyed airplane title is missing/empty in: {missing}"


def test_both_surfaces_paint_the_same_claim_for_the_same_state() -> None:
    """The defect Q1126 names, stated as a property: two surfaces describing ONE
    mechanism differently is how an operator comes to believe the weaker one."""
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    core = (_ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    assert _AIRPLANE_ONLINE_TITLE in tm and _AIRPLANE_ONLINE_TITLE in core


def test_the_offline_third_state_is_still_mirrored() -> None:
    """The AI-install egress window makes the strong claim FALSE while it is open,
    and both surfaces already paint a different title then. Pinned so the S5 edit
    cannot be read as licence to flatten it back to two states."""
    third = (
        "Offline (airplane mode), except the AI install you allowed — collection "
        "stays stopped. Click to go fully online."
    )
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    core = (_ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    assert third in tm and third in core


def test_the_task_manager_re_translates_its_painted_title_on_a_language_switch() -> None:
    """The airplane hover is PAINTED, so the i18n DOM walker cannot reach it.

    ``t()`` is evaluated once at paint time and the result is an attribute value that
    no longer matches any key, so without a listener the title stays frozen in the
    locale the tab opened with. Chromium-verified in both directions: English after
    switching to French before this listener existed, French and Arabic after.

    The app's own copy of the same button has always had this (``app-core.js``
    re-calls ``_paintNetwork`` from the same event); this page never registered,
    which is the recorded frozen-locale class on a render-once surface.
    """
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    # Comment-stripped: the explanation above the listener necessarily names the
    # event it registers, so a bare substring search would pass with the listener
    # deleted -- the recorded must-be-present-satisfied-by-its-own-comment trap, in
    # its silent direction.
    code = "\n".join(
        ln for ln in tm.splitlines() if not ln.strip().startswith("//")
    )
    assert 'addEventListener("oo:langchange"' in code, (
        "the task manager no longer re-paints on a language switch; its airplane "
        "title will stay frozen in whatever locale the tab opened with"
    )
    assert "paintAir()" in code.split('addEventListener("oo:langchange"', 1)[1][:200], (
        "the langchange listener does not re-paint the airplane button"
    )
