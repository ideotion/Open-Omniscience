"""The two feed-refresh actions had no button, and deleting them was the wrong read.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``loadIndicesData`` and ``loadMarketData`` are complete, ``ensureOnline``-gated,
degrade-loudly refresh actions whose trigger buttons were lost in a past
dashboard restructuring, leaving ``#idx-status`` / ``#mkt-dash-status`` /
``#idx-verdicts`` / ``#mkt-verdicts`` permanently empty. Three records describe
the same fact and TWO CONCLUSIONS:

  * ``docs/ledger/OPEN_QUEUE.md``'s DEFERRED DEAD-UI-CODE worklist lists them as
    orphans to DELETE;
  * the 2026-07-22 GUI audit (``mkt-004-feed-verdicts-never-shown``, filed under
    HONESTY) and the 2026-09-08 visual audit (F11, "the cheapest fix in the whole
    report relative to value restored") say RESTORE THE TRIGGER.

The second reading wins, and the honesty argument is what decides it:
``_renderFeedVerdicts`` has no other entry point, so deleting these two would
remove the app's ONLY surface for "this official feed refused" — the exact
opposite of the degrade-loudly non-negotiable. A feed can fail forever with no
live signal while the failure-rendering code sits intact and unit-correct.

VERIFIED IN CHROMIUM, 2026-09-09: both buttons render (89x43, aligned with the
status line beside them), both open the ONE network-consent popup naming the
action, declining makes ZERO non-loopback requests and re-enables the button,
and the console stays clean.

ONE FIXTURE NOTE, because it nearly produced a false pass: the audit harness
boots with ``OO_NO_SCHEDULER=1``, and the boot-time kill-switch activation lives
inside the ``OO_NO_SCHEDULER != 1`` block — so that instance starts ONLINE and
``ensureOnline`` returns true without ever showing the popup. The gate was only
observable after engaging airplane mode explicitly. A consent check run against
an already-online fixture proves nothing.
"""

from __future__ import annotations

import re

from tests.js_source_helper import assert_present, function_source, read_static


def _index() -> str:
    return read_static("index.html")


def _markets() -> str:
    return read_static("app-markets.js")


def test_both_feed_refresh_actions_have_a_trigger_again() -> None:
    html = _index()
    for fn, tab in (("loadIndicesData", "tab-indices"), ("loadMarketData", "tab-markets")):
        m = re.search(rf'<button[^>]*onclick="{fn}\(this\)"[^>]*>', html)
        assert m, f"{fn} has no trigger button; its status/verdict panes can never fill"
        assert 'title="' in m.group(0), (
            f"{fn}'s button needs a translated title — it rides the #oo-tip hover "
            f"convention (invariant #17). Found: {m.group(0)}"
        )
        # In the right board, not merely somewhere on the page.
        page = html[html.index(f'id="{tab}"'):]
        assert m.group(0) in page[: page.index("</div><!--") if "</div><!--" in page else 40000], (
            f"{fn}'s button must live on its own board"
        )


def test_the_refresh_actions_still_pass_the_one_consent_popup() -> None:
    """Restoring a trigger for an egressing action is only safe because the action
    was already gated. Invariant #14: EVERY offline->online transition passes
    ``ensureOnline``."""
    for fn in ("loadIndicesData", "loadMarketData"):
        src = function_source(_markets(), fn)
        assert_present(src, "ensureOnline",
                       why=f"{fn} imports official feeds over the network")
        assert src.index("ensureOnline") < src.index("/api/markets/feeds"), (
            f"{fn} must ask BEFORE it fetches, not after"
        )


def test_the_verdict_renderer_keeps_its_only_entry_points() -> None:
    """The reason deletion was the wrong call, asserted rather than remembered."""
    js = _markets()
    callers = re.findall(r"_renderFeedVerdicts\(", js)
    assert len(callers) >= 3, (
        "expected the definition plus its call sites; if the call sites went away, "
        "a failing official feed has no surface left at all"
    )
    for fn in ("loadIndicesData", "loadMarketData"):
        assert_present(function_source(js, fn), "_renderFeedVerdicts",
                       why="this is one of the two entry points that make a feed "
                           "refusal visible anywhere in the UI")


def test_the_two_button_titles_ship_in_all_twelve_locales() -> None:
    import json
    from pathlib import Path

    keys = [
        "Import the index feeds now. Each feed's outcome is reported, "
        "including any that refuse.",
        "Import every official feed now. Each feed's outcome is reported, "
        "including any that refuse.",
    ]
    locales = sorted((Path(__file__).resolve().parents[1] / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        mapping = data.get("map", data)
        for key in keys:
            assert mapping.get(key), f"{path.name} is missing {key!r}"
