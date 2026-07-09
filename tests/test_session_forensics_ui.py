"""EPSILON E2 guard: the session-forensics diagnostics surface (#596 backend).

Surfaces the app's own root-cause records — the previous-session clean/unclean verdict
(with the OOM-inference wording shown VERBATIM as a caveat), the last unlock's phase
timings + -wal size, and the data-dir inventory with orphaned PLAINTEXT staging flagged
loudly. Read-only; NO delete button this round (deletion is destructive, ships later).
Source-text guard (no browser).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def test_forensics_button_wired_in_diagnostics_panel() -> None:
    html = _read("index.html")
    assert 'id="session-forensics-box"' in html, "no forensics block in the diagnostics panel"
    assert "loadSessionForensics(this)" in html, "button not wired"
    assert 'id="session-forensics-out"' in html
    # It lives inside the diagnostics panel (surfaced where the other diagnostics live).
    box = html.index('id="session-forensics-box"')
    panel = html.index('id="diagnostics-panel"')
    nxt = html.index("</section>", panel)
    assert panel < box < nxt, "forensics block is not inside #diagnostics-panel"


def test_loader_hits_the_live_endpoint() -> None:
    app = _read("app.js")
    assert "async function loadSessionForensics(" in app
    assert "/api/diagnostics/session-forensics" in app, "does not call the live endpoint"


def test_inference_and_method_wording_shown_verbatim() -> None:
    app = _read("app.js")
    m = re.search(r"function _renderSessionForensics\(", app)
    assert m, "_renderSessionForensics missing"
    body = app[m.start() : app.index("async function loadSessionForensics(")]
    # The method / inference strings are backend DATA (caveats) — rendered verbatim,
    # never re-worded/keyed. All three method surfaces must be shown.
    assert "esc(prev.method)" in body, "previous-session inference wording not shown"
    assert "esc(u.method)" in body, "unlock method wording not shown"
    assert "esc(inv.method)" in body, "inventory method wording not shown"
    # Shown in the visible caveat line, not hidden.
    assert '"card-caveat"' in body


def test_orphaned_plaintext_staging_flagged_loudly() -> None:
    app = _read("app.js")
    assert "suspect_staging" in app
    assert "plaintext_snapshot" in app, "the decrypted-copy case is not detected"
    assert 't("Decrypted copy on disk — remove it deliberately.")' in app
    # The staging block uses the loud warn note, not a muted line.
    m = app.index("_renderSessionForensics(")
    body = app[m : m + 4000]
    assert '"note warn"' in body, "orphaned staging is not surfaced loudly"


def test_no_delete_affordance_this_round() -> None:
    app = _read("app.js")
    html = _read("index.html")
    m = app.index("function _renderSessionForensics(")
    end = app.index("async function loadSessionForensics(")
    render = app[m:end]
    # No destructive action wired into the forensics render or its HTML block.
    assert "method: \"DELETE\"" not in render and "method:'DELETE'" not in render
    box_start = html.index('id="session-forensics-box"')
    box = html[box_start : html.index("</div>", box_start + 200) + 6]
    assert "delete" not in box.lower() or "deleted" in box.lower(), "unexpected delete affordance"


def test_forensics_keys_present_in_en_locale() -> None:
    d = json.loads((_STATIC / "locales" / "en.json").read_text(encoding="utf-8"))
    for k in (
        "Session forensics",
        "Previous session",
        "Ended cleanly",
        "Ended unexpectedly",
        "Last unlock",
        "WAL before first open",
        "Data folder",
        "Orphaned staging detected",
        "Decrypted copy on disk — remove it deliberately.",
    ):
        assert k in d, f"missing en.json key: {k!r}"
