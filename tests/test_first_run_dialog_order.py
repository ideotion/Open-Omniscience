"""A fresh install opens its first-run dialogs one at a time, in one order.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-09-26 click-through U8: after a fresh create, unlock.html hands off to
``/?wikiwizard=1``, and two first-run dialogs then opened independently -- the Wikipedia
wizard (``openWikiWizard``, behind two fetches) and the one-time guide
(``checkEmptyCorpus`` -> ``openGuide``, behind one). Both ended up open, stacked, and which
one sat on top depended on which fetch answered first (it differed between two runs).

The shipped ``checkEmptyCorpus`` and ``wikiWizardPending`` are lifted from the source and
driven under node with the DOM reduced to the three facts they read: whether the wizard is
open, whether the hand-off asked for it, and whether it has been shown yet.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.js_source_helper import function_source, read_static

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _drive(search: str, wiz_shown: bool, wiz_open: bool) -> dict:
    fns = "\n".join(
        (
            function_source(read_static("app-sources.js"), "wikiWizardPending"),
            # `async` precedes the declaration the slicer anchors on.
            "async " + function_source(read_static("app-backup.js"), "checkEmptyCorpus"),
        )
    )
    harness = f"""
const location = {{ search: {json.dumps(search)} }};
let _wizShown = {json.dumps(wiz_shown)};
const listeners = {{}};
const dlg = {{ open: {json.dumps(wiz_open)},
  addEventListener(ev, fn, opts) {{ listeners[ev] = {{ fn, once: !!(opts && opts.once) }}; }} }};
function $(id) {{ return id === "wiki-wizard" ? dlg : null; }}
let guideOpened = 0, done = false;
function guideDone() {{ return done; }}
function openGuide() {{ guideOpened++; }}
async function api() {{ return {{ counts: {{ articles: 0 }} }}; }}
{fns}
(async () => {{
  await checkEmptyCorpus();
  const atStats = guideOpened;
  const waits = !!listeners.close;
  if (listeners.close) {{ dlg.open = false; listeners.close.fn(); }}
  console.log(JSON.stringify({{ atStats, waits, once: waits && listeners.close.once,
                                afterWizardClosed: guideOpened }}));
}})();
"""
    r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"node failed:\n{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_guide_waits_for_the_hand_off_wizard_that_has_not_opened_yet():
    """The racy case: the stats answer before the wizard's two fetches do."""
    out = _drive("?wikiwizard=1", wiz_shown=False, wiz_open=False)
    assert out == {"atStats": 0, "waits": True, "once": True, "afterWizardClosed": 1}, out


def test_the_guide_waits_for_an_open_wizard():
    out = _drive("?wikiwizard=1", wiz_shown=True, wiz_open=True)
    assert out["atStats"] == 0 and out["afterWizardClosed"] == 1, out


def test_without_the_wizard_the_guide_opens_straight_away():
    """An ordinary empty-corpus launch (no hand-off), or a wizard already answered and
    closed: nothing to wait for, and waiting would mean the guide never opens."""
    for search, shown in (("", False), ("?wikiwizard=1", True)):
        out = _drive(search, wiz_shown=shown, wiz_open=False)
        assert out == {"atStats": 1, "waits": False, "once": False, "afterWizardClosed": 1}, (
            search,
            out,
        )


def test_the_airplane_coachmark_does_not_join_the_first_run_dialogs():
    """With the guide now waiting for the wizard, the coachmark -- which already stands down
    while the guide is open -- would otherwise show BEHIND the wizard's modal, a prompt
    nobody can press (measured in Chromium on a fresh install). It stands down for the
    wizard too; the guide that follows hides it as before."""
    from tests.js_source_helper import function_body, strip_comments

    body = strip_comments(function_body(read_static("app-core.js"), "maybeShowNetCoach"))
    assert "wikiWizardPending()" in body, body
