"""The Wikipedia-stream toggle: its markup, its wiring, and its node driver.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q702's NOTE (ruled 2026-09-15): "make it default on, and add a toggle on the taskbar
-like the AI toggle, with a nice and consistent animation- , to allow users to stop /
start / halt / resume wikipedia streaming". The label of Q702's answer said "default
off"; the note inverts it, and the beta pathway's working mode states that where the
two disagree the note is the ruling.

WHAT IS ASSERTED HERE AND WHAT IS NOT. Source-level assertions can only prove that a
thing EXISTS, never that it works -- the recorded lesson is a substring check that
stayed green against a mutant reading a field and discarding it. So the BEHAVIOUR is
driven in ``tests/wiki_toggle_node_test.js``, which extracts the shipped painter and
executes it; this file pins the structural facts a node harness cannot see (that the
button is in the chrome, that it carries the opt-out marker, that the CSS exists, that
boot calls the loader) and runs that driver.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.js_source_helper import (
    array_literal,
    css_rule,
    event_listener_bodies,
    function_body,
    function_source,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parents[1]
_INDEX = _ROOT / "src" / "static" / "index.html"
_SOURCES = _ROOT / "src" / "static" / "app-sources.js"
_BOOT = _ROOT / "src" / "static" / "app-boot.js"
_CSS = _ROOT / "src" / "static" / "app.css"

_STATES = ("running", "halted", "stopped")


def _button() -> str:
    """The toggle's own markup. One slice, bounded by the element's own close tag.

    Kept local because the shared helper has no HTML-element slicer; it is a single
    literal-bounded span rather than one of the brace-matching shapes that module
    exists to stop being re-derived.
    """
    html = _INDEX.read_text(encoding="utf-8")
    at = html.find('<button class="icon-btn" id="wiki-toggle"')
    assert at != -1, "#wiki-toggle is not in index.html"
    return html[at : html.index("</button>", at)]


#: Every function that renders a string on this surface. Named, because a guard that
#: reads one of them and calls itself complete is the blind spot it was written to
#: close -- and because a new function added here has to be added to this tuple, which
#: is a visible act rather than a silent omission.
_TOGGLE_FUNCTIONS = ("_paintWikiLane", "loadWikiLane", "toggleWikiLane", "stopWikiLane")


def _rendered_strings() -> set[str]:
    """Every literal this surface passes through ``t9()``, plus its markup's own."""
    src = _SOURCES.read_text(encoding="utf-8")
    out: set[str] = set()
    for name in _TOGGLE_FUNCTIONS:
        out |= set(re.findall(r't9\(\s*"((?:[^"\\]|\\.)*)"', function_source(src, name)))
    out |= set(re.findall(r'(?:title|aria-label)="([^"]+)"', _button()))
    return out


def test_the_toggle_lives_in_the_TOP_BAR_beside_the_other_two_chrome_toggles():
    """Q702's NOTE says "on the taskbar". Its neighbours are what make that true."""
    html = _INDEX.read_text(encoding="utf-8")
    wiki = html.index('id="wiki-toggle"')
    net = html.index('id="net-toggle"')
    rate = html.index('id="rate-toggle"')
    header_end = html.index("</header>")
    assert wiki < header_end, "the toggle must be inside the chrome header"
    assert rate < wiki < net, (
        "the toggle left the run of chrome icon buttons; invariant #3's constant "
        "footprint is about THAT strip"
    )


def test_the_button_carries_the_i18n_walker_OPT_OUT():
    """``data-i18n-dyn``: its title is ALREADY translated by the painter.

    Without it the DOM walker caches the first-seen text as "the original English" --
    the poisoning half of the frozen-locale bug, which then survives every switch.
    """
    assert "data-i18n-dyn" in _button()


def test_the_glyph_is_ONE_constant_mark_whose_FILL_is_the_state():
    """Invariant #14's grammar: never an action glyph that swaps on click."""
    button = _button()
    assert button.count("<path") == 1, (
        "more than one path in the glyph -- the state must be the FILL of one constant "
        "mark, not a different picture per state"
    )
    assert 'id="wiki-mark"' in button
    painter = _painter_body()
    assert 'setAttribute("fill"' in painter, "the painter does not set the FILL"


def _painter_body() -> str:
    """Through the shared slicer, never a local brace walk.

    ``tests/js_source_helper`` exists because that walk was re-derived in dozens of
    files and got the default-parameter case wrong each time; ``test_source_slicing_
    discipline`` counts every re-derivation and its budget has zero slack.
    """
    return function_source(_SOURCES.read_text(encoding="utf-8"), "_paintWikiLane")


def test_the_painter_handles_every_state_the_backend_can_store():
    """A state the painter cannot draw is a control that lies about the lane."""
    from src.scheduler.settings import WIKI_LANE_STATES

    assert set(WIKI_LANE_STATES) == set(_STATES), (
        "the backend's state vocabulary moved; this test and the painter are its readers"
    )
    # Through the shared slicer: a local regex over an array literal is exactly the
    # re-derivation ``tests/js_source_helper`` exists to end, and its budget counts one.
    declared = array_literal(_SOURCES.read_text(encoding="utf-8"), "WIKI_LANE_STATES")
    drawn = set(re.findall(r'"([a-z]+)"', declared))
    assert drawn == set(WIKI_LANE_STATES), (
        f"the UI draws {sorted(drawn)} and the backend stores {sorted(WIKI_LANE_STATES)}; "
        "a state the painter does not know would be drawn as whatever the else-branch is"
    )


def test_going_to_RUNNING_passes_the_ONE_consent_popup():
    """Invariant #14: every offline -> online transition passes ``ensureOnline``.

    Starting the stream opens a connection to stream.wikimedia.org, so it is a
    transition. The settings write itself is loopback and needs no gate; the EGRESS
    does. Scoped to the toggle's own function body, never a whole-file search -- a
    "must be present" guard is only as strong as the scope it searches.
    """
    # Strip comments first: a guard that reads un-stripped source cannot tell a call
    # from a note ABOUT a call -- the recorded defect where a "must be present" guard
    # stayed green after the call was commented out.
    code = strip_comments(function_body(_SOURCES.read_text(encoding="utf-8"), "toggleWikiLane"))
    assert "ensureOnline(" in code, "the start path does not pass the consent popup"
    assert 'next === "running"' in code, (
        "the gate is not conditional on the direction; gating a PAUSE on a network "
        "consent popup would ask for permission to stop using the network"
    )


def test_stopping_and_pausing_are_NOT_gated_on_a_network_consent():
    """Turning something off must never require consent to go online."""
    body = strip_comments(function_body(_SOURCES.read_text(encoding="utf-8"), "stopWikiLane"))
    assert "ensureOnline" not in body


def test_boot_loads_the_real_state_rather_than_trusting_the_markup():
    assert "loadWikiLane()" in _BOOT.read_text(encoding="utf-8")


def test_a_language_switch_REPAINTS_the_toggle_from_the_state_it_already_holds():
    """The frozen-locale class. And it must NEVER fetch: a switch is not a refresh."""
    # EVERY listener body, never the first one: an anchor to "the first occurrence" is
    # an unstated uniqueness assumption, and adding a second listener earlier in module
    # order once broke three guards at once, each accusing the wrong code.
    bodies = event_listener_bodies(_BOOT.read_text(encoding="utf-8"), "oo:langchange")
    assert bodies, "no oo:langchange listener at all in app-boot.js"
    # Matched on the CALL and its first argument, not on an exact argument list: the
    # guard is about "something repaints it from state it already holds", and pinning
    # the arity would redden on a correct change (the recorded proxy-assertion trap).
    assert any(re.search(r"_paintWikiLane\(\s*_wikiLaneState\b", b) for b in bodies), (
        f"none of the {len(bodies)} langchange handler(s) repaints the toggle; its "
        "hover would stay frozen in whichever locale painted it first"
    )


def test_the_LIVE_state_has_an_accent_that_is_theme_derived_and_reduced_motion_safe():
    """The note asks for "a nice and consistent animation"; the repo's rule is that a
    colour comes from a token via ``color-mix``, never a hardcoded hue."""
    css = _CSS.read_text(encoding="utf-8")
    # Brace-matched to the rule itself: a fixed span once read 820 lines instead of 20,
    # inside which the token it was looking for appeared 73 times.
    block = css_rule(css, "#wiki-toggle.wiki-live")
    assert "color-mix" in block and "var(--accent)" in block
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", block), (
        "a hardcoded hue in the toggle's accent -- it must be derived from the theme's "
        "tokens so all 17 themes work"
    )
    assert "prefers-reduced-motion" in css[css.index("#wiki-toggle.wiki-live") :], (
        "the breathing ring has no reduced-motion escape; the static accent and the "
        "glyph FILL still carry the state, so disabling it costs nothing"
    )


def test_every_sentence_the_toggle_renders_is_KEYED_IN_ALL_TWELVE_LOCALES():
    """The informed-consent non-negotiable: a caveat surface ships x12.

    The three i18n gates measure the locale FILES; this measures the other direction --
    that every literal this specific surface renders has a key everywhere. A string
    that never requests a key is missing none, which is how English reaches eleven
    locales with every gate green.
    """
    # EVERY function this surface owns, not just the painter. Extracting only the
    # painter is how "Stop the Wikipedia stream" -- rendered by `stopWikiLane`'s toast
    # and by nothing else -- reached the locale merge unkeyed while this guard read
    # green. A surface's strings are wherever the surface says them.
    rendered = _rendered_strings()
    assert rendered, "nothing extracted -- this guard would pass against anything"
    locales = sorted((_ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12, f"expected twelve locale files, found {len(locales)}"
    for path in locales:
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(s for s in rendered if s not in catalogue)
        assert not missing, f"{path.name} is missing {len(missing)}: {missing[:3]}"


def test_the_host_names_survive_every_translation_verbatim():
    """A localized hostname is an unreachable address printed on a consent surface."""
    key = (
        "This lane contacts stream.wikimedia.org, each edition's Action API, "
        "and wikimedia.org for daily pageviews."
    )
    for path in sorted((_ROOT / "src" / "static" / "locales").glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8")).get(key)
        assert value, f"{path.name} has no translation for the hosts line"
        # WHOLE TOKENS, not substrings. `"...stream.wikimedia.org...".find("wikimedia.org")`
        # succeeds, so a substring check for the pageviews host was being satisfied by the
        # STREAM host and testing nothing -- a translation that dropped the second host
        # entirely would have passed. (CodeQL flagged the same shape in this slice's node
        # test; the weak assertion underneath it was the defect worth fixing, in both
        # languages.)
        # Trailing `-`/`.` trimmed: a host token cannot end in one, and Bengali
        # attaches its genitive suffix to a Latin word with a hyphen
        # (`stream.wikimedia.org-এর`, the same shape bn.json already uses for `GB-কে`),
        # so a greedy class would report a mangled host where the host is verbatim.
        hosts = {h.rstrip("-.") for h in re.findall(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value)}
        assert "stream.wikimedia.org" in hosts, f"{path.name} mangled stream.wikimedia.org"
        assert "wikimedia.org" in hosts, (
            f"{path.name} does not carry the pageviews host as its own token"
        )


@pytest.mark.skipif(
    subprocess.run(["which", "node"], capture_output=True).returncode != 0,
    reason="node is not installed",
)
def test_the_node_driver_runs_the_real_painter():
    """The behavioural half. Registered here so the every-node-suite-has-a-driver
    guard can see it -- a node suite nothing runs is a file, not a test."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "wiki_toggle_node_test.js")],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_the_toggle_reads_the_STATUS_not_only_the_config():
    """The config holds the operator's CHOICE; the status holds the choice AND
    whether anything is acting on it. Reading only the first is what would let this
    button claim a stream that is not running."""
    code = strip_comments(function_body(_SOURCES.read_text(encoding="utf-8"), "loadWikiLane"))
    assert "/api/scheduler/status" in code
    assert "wiki_lane" in code


def test_a_CHOSEN_but_idle_lane_is_not_drawn_as_a_running_one():
    """A control that renders claims its capability. Nothing consumes
    ``wiki_lane_state`` on this build, so "running" is a choice and not an event, and
    the surface has to say which."""
    body = _painter_body()
    assert "_wikiLaneActive" in body, "the painter never reads whether anything is collecting"
    assert 'classList.toggle("wiki-live", running && _wikiLaneActive)' in body, (
        "the LIVE accent is gated on the choice rather than on the activity; a "
        "breathing ring over an idle lane is the picture contradicting the words"
    )


def test_the_backend_reports_the_two_facts_SEPARATELY():
    from src.api.scheduler import _wiki_lane_block

    block = _wiki_lane_block()
    assert set(block) >= {"state", "active", "reason", "states"}
    assert block["active"] is False, (
        "something now consumes wiki_lane_state -- good, but this block and the UI "
        "sentence that depends on it both have to learn about it"
    )
    assert block["reason"] == "no-collector-yet"
    banned = ("score", "ranking", "rating", "grade")
    for key in block:
        assert not any(b in key.lower() for b in banned), key


def test_the_reason_travels_as_a_TOKEN_never_as_prose():
    """A payload field that is prose renders untranslated English to every non-English
    operator; the sentence is composed by the UI through ``OOI18N.t`` and ships x12."""
    from src.api.scheduler import _wiki_lane_block

    reason = _wiki_lane_block()["reason"]
    assert " " not in reason and reason.islower(), f"{reason!r} reads as prose, not a token"


def test_ACTIVE_is_measured_from_the_running_loop_not_hardcoded():
    """The inverse lie this avoids.

    ``active: False`` as a constant is true today and becomes a LIE the day someone
    wires a collector and does not think to come back here -- an operator told nothing
    is happening while their machine streams, which is the worse direction of the two.
    ``live_streams()`` is maintained by the read loop itself, so the answer is true in
    both directions without anyone remembering anything.
    """
    from src.api.scheduler import _wiki_lane_block
    from src.wiki import stream as stream_mod

    assert _wiki_lane_block()["active"] is False, "nothing is running, so nothing claims to be"

    # A stream inside its loop registers itself; the block sees it WITHOUT any other
    # change. Driven through the real registry rather than by patching the block.
    fake = object()
    with stream_mod._LIVE_LOCK:
        stream_mod._LIVE[id(fake)] = ("en", "fr")
    try:
        block = _wiki_lane_block()
        assert block["active"] is True, (
            "a running stream did not reach the status; `active` is not measured"
        )
        assert block["reason"] is None, "there is nothing to explain while it runs"
        assert block["editions_live"] == ["en", "fr"]
    finally:
        with stream_mod._LIVE_LOCK:
            stream_mod._LIVE.pop(id(fake), None)
    assert _wiki_lane_block()["active"] is False, "the registry did not clear"


def test_a_real_run_registers_and_DEREGISTERS_itself():
    """Through the actual client, so the registry is not a second thing to remember."""
    from src.testing.wiki_stream_fixture import FixtureStreamSession
    from src.wiki.stream import WikiEventStream, live_streams

    # Sampled from INSIDE the loop, because the registry is only interesting while
    # the run is in flight: a check after it returns can only ever see the empty
    # registry, and would pass against a version that never registered at all. (The
    # recorded rule that a test for "this is asynchronous" must observe DURING.)
    seen: list[int] = []

    def sample(*_args):
        seen.append(len(live_streams()))

    stream = WikiEventStream(session=FixtureStreamSession(), editions=("oo",))
    stream.run(lambda _change: None, max_connections=1, on_position=sample)
    assert seen, "the fixture delivered nothing, so the registry was never observed"
    assert max(seen) == 1, "the run did not register itself while it was running"
    assert live_streams() == (), "the run did not deregister itself when it ended"


def test_a_run_that_RAISES_still_deregisters():
    """A registry that leaks on the error path would report a dead stream as live."""
    import pytest as _pytest

    from src.ingest import activate_kill_switch, clear_kill_switch
    from src.testing.wiki_stream_fixture import FixtureStreamSession
    from src.wiki.stream import StreamStopped, WikiEventStream, live_streams

    stream = WikiEventStream(session=FixtureStreamSession(), editions=("oo",))
    activate_kill_switch()
    try:
        with _pytest.raises(StreamStopped):
            stream.run(lambda _c: None, max_connections=1)
    finally:
        clear_kill_switch()
    assert live_streams() == (), "a refused run stayed in the registry as though live"
