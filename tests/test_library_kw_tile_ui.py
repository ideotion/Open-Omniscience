"""The Library keywords-per-article tile, driven as real code in node (``library_kw_tile_node_test.js``).

The suite extracts ``_kwPerArticleTile`` from the shipped module: an unknown start of the background count is drawn as unknown
(not the epoch), and a count stopped for low memory is named as such, not as a time limit. This file is the driver the node-suite
ratchet requires, and keys the one string the memory stop introduces in all twelve locales.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"
_KEY = "stopped because the machine was nearly out of memory"


def test_library_kw_tile_node_suite() -> None:
    proc = subprocess.run(["node", str(_ROOT / "tests" / "library_kw_tile_node_test.js")], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_memory_stop_string_is_keyed_in_all_twelve_locales() -> None:
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data.get(_KEY), f"{f.name} lacks the memory-stop string"
