"""ooLive: text drawn in the active language that follows a language switch (row 364).

The behaviour is driven as real code in ``oo_live_node_test.js`` (draw, repaint, release back to
the walker, a gone node pruned, a foreign write dropped, one throwing render isolated); this file
is its driver, plus the wiring a rename would break silently: the one ``oo:langchange`` listener
calls ``ooLiveRepaint`` behind a ``typeof`` guard, and the helper is declared once.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


def test_oolive_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oo_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "oo_live_node_test.js: OK" in proc.stdout


def test_the_listener_repaints_and_the_helper_is_declared_once():
    boot = (_STATIC / "app-boot.js").read_text(encoding="utf-8")
    assert 'typeof ooLiveRepaint === "function") ooLiveRepaint();' in boot
    every = "".join(p.read_text(encoding="utf-8") for p in sorted(_STATIC.glob("*.js")))
    for name in ("ooLive", "ooLiveHtml", "ooLiveRepaint", "_ooLiveTake", "_ooLiveDraw", "_ooLiveDrop", "_ooLiveMark", "_ooLiveForeign", "_ooLiveWatch"):
        found = re.findall(rf"(?<![\w$.])function\s+{name}\s*\(", every)
        assert len(found) == 1, f"{name} declared {len(found)} times: a later one silently overrides"
