"""app-map.js renderers follow a live language switch (row 372(b)).

The behaviour is driven as real code in ``app_map_live_i18n_node_test.js``: four of the renderers
that left ``configs/i18n_frozen_renderers.txt`` in row 372(b) -- the OSM lane line, the official
figures fetch tally, the series-corpus tally and the folder picker's note and parent row -- are
drawn in English, the language is switched, and each node must read the new language with no
second request. This file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_app_map_live_i18n_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "app_map_live_i18n_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "app_map_live_i18n_node_test.js: OK" in proc.stdout


def test_the_app_map_listener_repaints_the_surfaces_it_holds():
    """The surfaces drawn with controls or a map are redrawn by app-map.js's own oo:langchange listener."""
    src = (_ROOT / "src" / "static" / "app-map.js").read_text(encoding="utf-8")
    at = src.index('document.addEventListener("oo:langchange", () => {\n      if (_osmPicker)')
    body = src[at : src.index("\n    });", at)]
    for call in (
        "_renderWikiDumps(_wikiDumpsLast)",
        "_renderOsmList()",
        "_renderDumpIndexStatus(_dumpIdxLast)",
        "_renderOsmProfile()",
        "_renderOsmGeography(_osmGeogDone)",
    ):
        assert call in body, f"{call} left the oo:langchange listener"
