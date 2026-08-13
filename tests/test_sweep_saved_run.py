"""Driver for tests/sweep_saved_run_node_test.js, plus the wiring that made the panel
unreachable in the first place.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-13, after an overnight keyword-triage run: "Can't find your keyword
triage button." Two independent defects stacked, and the panel's own markup was innocent
of both -- it is static HTML and had been in the tree the whole time.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import object_literal, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_sweep_saved_run_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "sweep_saved_run_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


def test_the_advanced_ai_section_syncs_the_sweeps_that_live_in_it() -> None:
    """The three progressive-sweep panels sit in Settings -> Advanced -> AI, and their
    syncs were left behind on the AI SUBTAB when the markup moved. So opening the section
    that contains them never asked whether a run existed, and the download links -- which
    only the sync renders -- could not appear where the panels actually are.

    Read comment-stripped: the comment above the loader necessarily names the very calls
    being asserted, and a guard satisfied by its own explanation fails OPEN.
    """
    js = strip_comments(read_static("app.js"))
    loaders = object_literal(js, "_ADV_LOADERS")
    ai = loaders.split("ai:", 1)[1].split("},", 1)[0]
    for fn in ("syncKeywordTriageToggle", "syncSourceTagsToggle", "syncPerceptionExtractToggle"):
        assert f"{fn}()" in ai, (
            f"the Advanced 'ai' section holds the sweep panels but never calls {fn}() -- "
            "a moved panel takes its loader with it, or its state never loads"
        )


def test_the_sweep_panels_really_are_in_the_advanced_subtab() -> None:
    """The anchor the guard above rests on. If the panels move again, this fails first and
    names the reason, instead of leaving a loader wired to a section that no longer holds
    them -- which is exactly the state this whole file exists to close."""
    html = read_static("index.html")
    start = html.index('<div class="set-view" id="set-advanced"')
    depth = 0
    end = start
    for i in range(start, len(html)):
        if html.startswith("<div", i):
            depth += 1
        elif html.startswith("</div", i):
            depth -= 1
            if depth == 0:
                end = i
                break
    advanced = html[start:end]
    for box in ("keyword-triage-box", "kt-toggle-btn"):
        assert f'id="{box}"' in advanced, (
            f"{box} is no longer inside #set-advanced -- move its sync out of the "
            "_ADV_LOADERS 'ai' entry to wherever it went, or its panel goes dark again"
        )
