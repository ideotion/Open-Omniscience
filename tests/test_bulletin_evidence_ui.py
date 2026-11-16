"""The Bulletin's evidence archive (Check, then Write) and narration Stop have buttons (Lane M's routes list, R684).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``POST /api/bulletin/evidence/plan``, ``/evidence/build`` and ``/narration/stop`` were server features no
button reached: a narration could be started from the Review and stopped nowhere, and the evidence archive
existed only for curl. The BEHAVIOUR (Write only after a passing Check of the same period and folder, the
stale-reply guard, Stop shown only while a run is watched) is driven in node
(``bulletin_evidence_node_test.js``); this file is its driver plus the claims a static read can make.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import function_source

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_AGENDA = (_STATIC / "app-agenda.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")


def test_bulletin_evidence_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "bulletin_evidence_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_evidence_block_sits_in_the_bulletin_panel() -> None:
    panel = _HTML[_HTML.index('id="bulletin-panel"') : _HTML.index("</section>", _HTML.index('id="bulletin-panel"'))]
    for needle in ('id="bul-ev-dest"', 'data-on-click="bulletinEvidencePlan(this)"', 'data-on-click="bulletinEvidenceBuild(this)"'):
        assert needle in panel, needle
    # Write starts OFF: only a passing Check turns it on.
    build = panel[panel.index('id="bul-ev-build"') :]
    assert build[: build.index(">")].rstrip().endswith("disabled"), "Write must start disabled"


def test_the_plaintext_caveat_is_drawn_visible_with_the_numbers() -> None:
    paint = function_source(_AGENDA, "_bulPaintEvidence")
    assert 'class="card-caveat"' in paint
    assert "Plain text: your corpus is encrypted, this archive is not." in paint
    assert "hidden" not in paint.split("card-caveat", 1)[1].split("</p>", 1)[0]


def test_the_review_offers_stop_beside_narrate() -> None:
    render = _AGENDA[_AGENDA.index('data-on-click="bulletinNarrate(this)"') :][:800]
    assert 'data-on-click="bulletinNarrateStop(this)"' in render
    assert '"/api/bulletin/narration/stop"' in function_source(_AGENDA, "bulletinNarrateStop")


def test_every_new_string_is_keyed_in_all_twelve_locales() -> None:
    keys = [
        "Stop narration",
        "Could not stop narration: {error}",
        "Plain text: your corpus is encrypted, this archive is not. It holds the full text of every article in the period. "
        "Keep it where you keep the corpus; it is not meant to be shared.",
        "Articles: {n} · period {start} – {end}",
        "Evidence archive",
        "Check the folder and size",
        "Write the archive",
    ]
    for path in sorted((_STATIC / "locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys if not data.get(k)]
        assert not missing, f"{path.name}: {missing}"
