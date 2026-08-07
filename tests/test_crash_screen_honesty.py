"""The health pill tells the truth, and the crash screen refuses to guess.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-07, item 4: the top-bar pill was green "healthy" on an app that
was not working. Root cause: ``loadHealth()`` is called exactly ONCE, at boot, so the
green was a boot-time paint that could never go red.

Rulings 17-19 add the other half: an honest crash screen, with a run-journal download,
and **no auto-restart -- "honesty first"**.

The load-bearing distinction, and the one most likely to be broken by a later edit, is
that an HTTP ERROR STATUS is a WORKING SERVER. Only a rejected fetch means nothing
answered. Getting that backwards would paint the app dead every time a request
legitimately 404s or 422s, so both directions are driven here, not asserted in prose.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.js_source_helper import assert_absent, function_body, read_static, strip_comments

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to drive app.js logic")

#: Declared here rather than sliced: these are the real signatures, asserted present in
#: the shipped file below, so the harness cannot drift from it without failing loudly.
_DECLS = {
    "_noteReachable": "function _noteReachable(ok) {",
    "_paintHealth": "function _paintHealth(ok) {",
}


def _harness() -> str:
    """The REAL functions from app.js, over a DOM stub small enough to reason about."""
    app = read_static("app.js")
    out = [
        """
        const _painted = {health: null, crash: 0, removed: 0};
        function esc(s) { return String(s); }
        function $(id) {
          if (id === "health") return {set innerHTML(v) { _painted.health = v; }};
          return null;
        }
        const window = {};
        const document = {
          getElementById: () => null,
          createElement: () => ({ setAttribute(){}, remove(){ _painted.removed++; },
                                  set innerHTML(v){}, addEventListener(){} }),
          body: { appendChild(){ _painted.crash++; } },
        };
        function _paintCrashScreen() { if (_serverDown) _painted.crash++; else _painted.removed++; }
        """
    ]
    for name, decl in _DECLS.items():
        assert decl in app, f"the shipped signature of {name} is not {decl!r}"
        out.append(decl[:-1] + function_body(app, name))
    # The module-level state the two functions read.
    out.append("""
        let _downStreak = 0, _serverDown = false, _lastReachableAt = Date.now();
        const _DOWN_STRIKES = 3;
    """)
    return "\n".join(out)


def _run(snippet: str) -> dict:
    proc = subprocess.run([NODE, "-e", _harness() + "\n" + snippet],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------- #
#  The pill
# --------------------------------------------------------------------------- #


def test_the_pill_is_not_painted_once_at_boot_any_more():
    """The defect itself: loadHealth ran once, so the green could never go red.

    It still fetches the version -- but the PILL must no longer be its business.
    """
    body = function_body(read_static("app.js"), "loadHealth")
    stripped = strip_comments(body)
    assert "dot ok" not in stripped and "dot err" not in stripped, (
        "loadHealth must not paint the pill: it runs exactly once, so any state it "
        "writes is frozen for the life of the page"
    )
    assert "/api/health" in stripped, "it still fetches the version"


def test_every_request_repaints_the_pill():
    """The replacement, and why it costs nothing: api() is the one chokepoint, so the
    evidence is already there. A dedicated poll would re-enter the measured
    polling-storm defect."""
    api = strip_comments(function_body(read_static("app.js"), "api"))
    assert "_noteReachable(true)" in api and "_noteReachable(false)" in api


def test_an_error_STATUS_does_not_mean_the_app_is_down():
    """THE distinction. A 404/422/500 is a server that answered. Painting the app dead
    on those would make the pill red during perfectly normal use -- the inverse of the
    bug being fixed, and just as false."""
    out = _run("""
      _noteReachable(true);   // as api() does for ANY response, including an error status
      console.log(JSON.stringify({health: _painted.health, down: _serverDown, streak: _downStreak}));
    """)
    assert "dot ok" in out["health"]
    assert out["down"] is False and out["streak"] == 0


def test_only_an_unanswered_request_counts_against_the_app():
    out = _run("""
      _noteReachable(false);
      console.log(JSON.stringify({health: _painted.health, down: _serverDown, streak: _downStreak}));
    """)
    assert "dot err" in out["health"], "the pill goes red on the first unanswered call"
    assert out["down"] is False, "...but one blip is a blip, not an outage"
    assert out["streak"] == 1


def test_the_crash_screen_needs_a_RUN_of_unanswered_calls():
    out = _run("""
      const seen = [];
      for (let i = 0; i < 4; i++) { _noteReachable(false); seen.push(_serverDown); }
      console.log(JSON.stringify({seen}));
    """)
    assert out["seen"] == [False, False, True, True], out
    # ...and the screen is painted once, not once per further failure.


def test_recovery_clears_it_without_reloading_anything():
    out = _run("""
      for (let i = 0; i < 3; i++) _noteReachable(false);
      const downAfter = _serverDown;
      _noteReachable(true);
      console.log(JSON.stringify({downAfter, downNow: _serverDown, health: _painted.health,
                                  removed: _painted.removed}));
    """)
    assert out["downAfter"] is True and out["downNow"] is False
    assert "dot ok" in out["health"]
    assert out["removed"] >= 1, "the screen is taken down when the server answers again"


# --------------------------------------------------------------------------- #
#  Ruling 19 -- honesty first
# --------------------------------------------------------------------------- #


def test_nothing_restarts_reloads_or_reconnects_by_itself():
    """Ruling 19 is explicit: NO auto-restart. The screen states what was observed and
    leaves every action to the reader.

    Comment-stripped, because the comment explaining the absence necessarily names the
    thing that is absent (the recorded 2026-07-31 trap)."""
    body = strip_comments(function_body(read_static("app.js"), "_paintCrashScreen"))
    for forbidden in ("location.reload", "location.replace", "location.href", "setInterval"):
        assert forbidden not in body, f"the crash screen must not {forbidden}"
    assert_absent(body, "setTimeout")


def test_it_states_what_was_observed_and_refuses_to_name_a_cause():
    """From the browser a stopped server, a crash and a sleeping machine are the same
    silence. Naming one would be a fabricated diagnosis on the screen a reader trusts
    most."""
    app = read_static("app.js")
    assert "a stopped server, a crash and a sleeping machine look identical" in app
    # The elapsed time is DATA in a keyable frame, never a concatenated sentence.
    assert 'OOI18N.tf("Last answered {seconds}s ago."' in app


def test_the_journal_link_is_not_offered_while_it_cannot_work():
    """The run journal lives behind /api/diagnostics/run-journal, so if the server is
    not answering, the download cannot work either. A button that fabricates a
    capability is worse than an absent one -- so the screen says why it is missing."""
    body = strip_comments(function_body(read_static("app.js"), "_paintCrashScreen"))
    assert "cannot be downloaded while the server is not answering" in body
    assert "run-journal" not in body, (
        "no download URL may be wired into a screen shown only when downloads fail"
    )


# --------------------------------------------------------------------------- #
#  Consent/caveat strings ship x12
# --------------------------------------------------------------------------- #


def test_every_crash_string_is_keyed_in_all_twelve_locales():
    import pathlib

    strings = [
        "not responding",
        "The app stopped answering",
        "Check again",
        "Still not answering.",
        "The run journal cannot be downloaded while the server is not answering.",
        "Last answered {seconds}s ago.",
        "Requests to the local server are going unanswered. This page is still here, "
        "but it is showing you the last data it received, which may now be out of date.",
        "What happened is not known from here: a stopped server, a crash and a sleeping "
        "machine look identical to this page. Nothing has been restarted for you.",
        "Your corpus is on disk and is not affected by this. Relaunch the app the way "
        "you normally start it.",
    ]
    base = pathlib.Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    files = sorted(base.glob("*.json"))
    assert len(files) == 12, [f.name for f in files]
    for f in files:
        m = json.loads(f.read_text(encoding="utf-8"))
        missing = [s for s in strings if s not in m]
        assert not missing, f"{f.name} is missing {len(missing)}: {missing[0][:60]!r}"
        if f.stem != "en":
            same = [s for s in strings if m[s] == s and len(s) > 24]
            assert not same, f"{f.stem} left {len(same)} long string(s) in English"


def test_the_long_strings_are_single_literals_so_the_audit_can_see_them():
    """A t() argument built by concatenation resolves fine at RUNTIME but the i18n
    audit's scan reads only the first fragment -- so a fully keyed sentence is counted
    as untranslatable and the gate measures something other than what ships. Caught by
    the ratchet while writing this: 3 keyed strings still read as unkeyed."""
    app = read_static("app.js")
    for name in ("_CRASH_WHAT", "_CRASH_UNKNOWN", "_CRASH_CORPUS"):
        assert f"const {name} = \"" in app, f"{name} must be ONE string literal"
        assert f"t({name})" in app
