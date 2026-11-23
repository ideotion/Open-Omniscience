"""Settings -> Integrity: R804 (row 353) and the row 352 repaint.

A row with no stored hash was never checked. The fixity result counts it apart as not checkable,
never as diverged and never as evidence of tampering, never shows the hash the server computes now
beside it, and never reads "All articles match" while such rows exist. The result is drawn from the
last report on hosts marked data-i18n-dyn, so a language switch repaints it without a second audit.
The behaviour is driven as real code in ``fixity_result_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_fixity_result_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "fixity_result_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "fixity_result_node_test.js: OK" in proc.stdout


def test_the_hosts_are_marked_and_the_listener_repaints_them():
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    for host in ("fixity-summary", "fixity-result"):
        assert re.search(rf'<div id="{host}"[^>]*\bdata-i18n-dyn\b', html), host
    boot = (_ROOT / "src" / "static" / "app-boot.js").read_text(encoding="utf-8")
    assert "fixityRepaint()" in boot
    # The listener's call is typeof-guarded, so a rename would stop the redraw silently.
    assert "function fixityRepaint(" in (_ROOT / "src" / "static" / "app-settings.js").read_text(
        encoding="utf-8"
    )
