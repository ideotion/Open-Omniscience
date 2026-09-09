"""A render-once surface that loses the boot race has nothing to repair it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured 2026-09-09 in Chromium at ``fr``, while verifying the audit §4.2 fix.
That fix added an honest read-failure line to Home's stat strip, translated at
render time through ``t()`` -- correct, because ``#home-stats`` sits inside a
``[data-i18n-dyn]`` subtree that the i18n DOM walker is *required* to skip (it
would otherwise cache an already-translated string as "the original English" and
freeze the node forever).

But translating at render time only works if the locale is loaded when you
render. ``OOI18N.setLang()`` dispatches ``oo:langchange`` and several surfaces
already re-derive on it; ``OOI18N.init()`` -- the boot path -- dispatched
NOTHING. So a surface rendering during boot, before ``await load(c)`` resolved,
froze in English with no event coming. A forced ``OOI18N.apply()`` could not fix
it either, because the walker is skipping that subtree by design.

Measured, before the fix: at ``fr``, with a malformed ``/api/database/stats``,
the strip read "The corpus stats could not be read just now…" in English, while
the briefing's own failure line -- outside a dyn subtree, so walker-reachable --
translated correctly. That asymmetry is what makes this a race rather than a
missing key: the key was present and ``OOI18N.t()`` returned French when asked.

The primitive that was missing is ``OOI18N.ready``. A promise, not another
event: a late subscriber to an event that already fired hears nothing, which is
the same race one layer up.
"""

from __future__ import annotations

import re

from tests.js_source_helper import function_body, read_static

_I18N = read_static("i18n.js")
_HOME = read_static("app-home.js")
_BOOT = read_static("app-boot.js")


def test_i18n_exposes_a_boot_readiness_promise() -> None:
    """``ready`` must be on the public object, or no surface can await it."""
    assert re.search(r"window\.OOI18N\s*=\s*\{[^}]*\bready\b", _I18N), (
        "OOI18N must export `ready` -- without it a render-once surface has no way "
        "to know the boot locale load finished"
    )
    assert "const ready = new Promise(" in _I18N, (
        "`ready` must be a promise: an event only reaches subscribers who were already "
        "listening, which is the very race this fixes"
    )


def test_the_readiness_promise_resolves_at_the_end_of_init_not_before() -> None:
    """Resolving early would be worse than not resolving: a surface would repaint
    with a map that is not loaded yet and conclude it is up to date."""
    body = function_body(_I18N, "init")
    assert "_markReady(" in body, "init() must resolve the readiness promise"
    at_ready = body.index("_markReady(")
    at_apply = body.rindex("apply()")
    assert at_ready > at_apply, (
        "readiness must be signalled AFTER the locale is loaded and applied; "
        "resolving before apply() hands subscribers a half-initialised state"
    )
    # And after the load itself, which is the thing being waited for.
    assert body.index("await load(c)") < at_ready


def test_the_home_stats_failure_repaints_when_the_locale_arrives() -> None:
    """The surface that found this. It must repaint on readiness AND only while it
    is still the thing on screen -- repainting over real stats that arrived in the
    meantime would replace data with an error message."""
    body = function_body(_HOME, "renderHomeStatsFailure")
    assert "OOI18N.ready" in body, "the failure line must await boot readiness"
    assert "_homeStatsFailed" in body, (
        "the repaint must be conditional on the strip still showing the failure"
    )
    # One subscription, not one per render: the flag is what prevents a repaint loop.
    assert "_homeStatsAwaitingI18n" in body


def test_the_home_stats_failure_also_tracks_a_language_switch() -> None:
    """Boot readiness covers the race; oo:langchange covers the user switching
    language afterwards. Both are needed -- the walker will never reach this node.
    Verified in Chromium: fr at boot, then ja, then en, then fr again."""
    assert "homeStatsIsShowingFailure" in _BOOT and "renderHomeStatsFailure" in _BOOT, (
        "app-boot.js's oo:langchange handler must re-derive the stats failure line, "
        "beside the map, the sources table and the briefing"
    )
    assert "homeStatsIsShowingFailure()" in _BOOT, (
        "and it must be guarded, so a language switch never repaints over real stats"
    )


def test_the_strip_is_still_inside_a_walker_skipped_subtree() -> None:
    """The premise. If #home-stats ever leaves the [data-i18n-dyn] subtree the DOM
    walker would reach it again and this machinery could be simplified -- so pin the
    premise rather than leaving a future reader to rediscover why it exists."""
    html = read_static("index.html")
    at = html.index('id="home-stats"')
    before = html[:at]
    # The nearest enclosing element carrying the opt-out, searched backwards.
    assert "data-i18n-dyn" in before[-2000:], (
        "#home-stats is no longer inside a [data-i18n-dyn] subtree -- re-check whether "
        "the walker now reaches it, and simplify renderHomeStatsFailure if so"
    )
