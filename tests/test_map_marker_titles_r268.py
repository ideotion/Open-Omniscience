"""Every marker the map renderer draws carries its hover in a title ATTRIBUTE (row 268, invariant #17).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The shared #oo-tip bubble marks ``[title]`` elements and opens on hover and touch long-press; an SVG
``<title>`` child only ever reached a mouse. The wiki page and infobox-address markers (gate row D's
address provenance), the mentioned-place and server-IP markers, the signal shapes and the Insights
cities map all used a ``<title>`` child until this row. What each one says is run as real code in
tests/map_marker_titles_r268_node_test.js and tests/wiki_map_layer_node_test.js.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "script", ["map_marker_titles_r268_node_test.js", "wiki_map_layer_node_test.js"]
)
def test_the_map_markers_hover_rides_a_title_attribute(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run(
        [node, str(ROOT / "tests" / script)], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stdout + r.stderr
