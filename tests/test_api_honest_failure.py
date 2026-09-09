"""Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

Fix pass on the 2026-09-08 live visual audit -- two P0s in one call path, both proven
by a Node suite (tests/api_honest_failure_node_test.js) that EXTRACTS the real
functions from src/static/app-core.js and src/static/app-home.js BY NAME, never a
re-typed copy (a re-typed copy would pass while the shipped code was broken).

AUDIT §4.2 -- a malformed response rendered as a confident, false claim about the
user's corpus. Root cause: `api()`'s response parsing set `data` to the raw response
text (rather than throwing) whenever `JSON.parse` failed, even on a 200 whose
Content-Type declared `application/json`. `res.ok` stayed true, so every caller's
`data.cards` / `data.total` silently read `undefined` off that string, and the
existing `|| []` / falsy-empty rendering path printed the EMPTY-corpus copy over a
real database of 453 articles / 3,618 sources -- hand-verified against
`/api/briefing` and `/api/database/stats`: Home rendered "Your library is empty..."
and "No Leads yet...", with zero occurrences of failed/error/unavailable/retry.

Fix: `api()` now throws (marked `.parseFailure = true`) when the Content-Type
DECLARES json and the body still fails to parse -- never for a legitimately
non-JSON body, which is untouched. `app-home.js`'s `loadHome()` (the stat strip) and
`loadBriefing()` (the briefing panel) already had distinct `catch` blocks for this
exact case, but api()'s old behaviour meant those catches were NEVER REACHED for a
malformed 200 -- the try block "succeeded". Now that api() throws, both catches
render a loud (`role="alert"`, the caveat/error colour), translated, honestly worded
failure that names the data could not be read and never reuses the empty-corpus
sentence.

AUDIT §0c -- the airplane-mode toggle was dead for ~5s after every boot. Root cause:
`#net-toggle`'s only state signal was its `off` class, set exclusively by the first
resolved `GET /api/system/network` -- queued behind ~30 boot calls (measured median
4887ms). `toggleNetwork()` read `goingOnline = btn.classList.contains("off")`, so a
click inside that window took the wrong branch, silently, with no consent dialog and
no feedback of any kind.

Fix, combining both options the brief raised: (1) the button is painted with a
known-offline default the instant the script runs (`_paintNetToggleBootDefault()`,
since the app always boots with the kill switch engaged -- CLAUDE.md non-negotiable),
which narrows the window to near-zero; (2) `toggleNetwork()` itself no longer trusts
an unconfirmed class -- a new `_netStateKnown` flag (set only inside `_paintNetwork`,
the one function every real answer flows through) gates whether the class can be
trusted, and while it is false `toggleNetwork()` resolves the real state via a fresh
`GET /api/system/network` before deciding which branch to take. The ONE
consent-gating function (`ensureOnline`) and its POST are completely untouched --
this changes only which branch of `toggleNetwork()` is entered, never what either
branch does.

ITEM (c) -- the 429 retry (`_API_MAX_RETRIES = 4`) is documented as safe because a
429 means "refused before work". That holds for a load-shed 429 and fails for a
QUOTA 429 (`/api/articles` is 100/hour): retrying blindly spends the very budget
that is exhausted, up to 5 requests for one click. Fix: the retry now honours a
`Retry-After` when the server sends one, and does NOT retry blindly when it doesn't
-- it falls through and surfaces the honest refusal instead.

Running the Node suite here keeps the guarantee in CI; it skips cleanly where node
is absent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_api_honest_failure_node_suite() -> None:
    """Parse-failure honesty + the 429/Retry-After budget fix (app-core.js), the
    dead-toggle race fix (app-core.js), and an end-to-end reproduction spanning
    app-core.js + app-home.js of the exact hand-verified audit §4.2 scenario."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "api_honest_failure_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "api-honest-failure checks passed" in proc.stdout


def test_home_failure_copy_never_reuses_the_empty_corpus_sentence() -> None:
    """Static guard (runs even without node): the new honest-failure strings in
    app-home.js's loadHome()/loadBriefing() catches are present, translated via
    t(), and are never the literal empty-corpus sentences the audit found reused."""
    home_js = read_static("app-home.js")

    # Slice through the SHARED helper, never by hand. tests/js_source_helper.py
    # brace-matches from the body brace after balancing the parameter list, which
    # is what stops a default parameter being mistaken for the body; hand-rolling
    # it here is what tests/test_source_slicing_discipline.py counts, and it is
    # counted because the tree has been burned by a hand-rolled slice three times,
    # each with a green test asserting over the wrong span.
    #
    # strip_comments() is load-bearing, not tidiness: the catch block this guards
    # carries a comment that QUOTES the banned empty-corpus sentences to explain
    # why they must not be rendered. The ledger records three "this string must be
    # GONE" guards that failed against correct code on exactly that shape, so the
    # assertion has to run over code with the commentary removed.
    load_home_body = strip_comments(function_body(home_js, "loadHome"))
    assert 't("The corpus stats could not be read just now' in load_home_body
    assert "Your library is empty" not in load_home_body
    assert 'role="alert"' in load_home_body

    load_briefing_body = strip_comments(function_body(home_js, "loadBriefing"))
    assert 't("The briefing could not be read just now' in load_briefing_body
    assert "No Leads yet" not in load_briefing_body
    assert 'role="alert"' in load_briefing_body
