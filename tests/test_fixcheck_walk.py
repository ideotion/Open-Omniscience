"""The two items the 2026-09-27 fix-check walk still found (R37; ``docs/audit/``).

- **N-4** (row N): the Diagnostics job lines kept the old language after a live switch.
  The behaviour runs as extracted code under node (``tests/fixcheck_n4_node_test.js``);
  the wiring into the ONE ``oo:langchange`` listener is checked here.
- **O-5** (row O): the ``/tasks`` page's failure line welded a Latin space after zh's
  full-width colon. Pinned in ``tests/job_why_node_test.js`` (run by
  ``tests/test_download_paused_by.py``), beside the in-app renderer it must match.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import event_listener_bodies, function_body, read_static

_ROOT = Path(__file__).resolve().parents[1]


def test_the_diagnostics_job_lines_repaint_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "fixcheck_n4_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_one_langchange_listener_repaints_the_diagnostics_job_lines():
    handlers = event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    assert any("repaintDiagnosticsJobsFromCache()" in h for h in handlers), (
        "the ONE oo:langchange listener must redraw the Diagnostics job lines (N-4)"
    )
    body = function_body(read_static("app-diagnostics.js"), "repaintDiagnosticsJobsFromCache")
    assert "api(" not in body, "a language switch must never fetch"


def test_the_tasks_page_failure_line_uses_the_keyed_label_frame():
    tm = read_static("taskmanager.html")
    why = function_body(tm, "jobWhy")
    assert 'tf("{prefix}: {text}"' in why, "the /tasks failure line must use the keyed label frame (O-5)"
    assert 't("Failed:") + " "' not in why
