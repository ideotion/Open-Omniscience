"""R751(c): the K1–K14 measures in the task manager's System tab.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The renderer is run as real code in node (``kpi_panel_node_test.js``: unknown never 0, no tally, the caveat visible, the
five K13 blocks with their own counts). This file pins the wiring the node suite cannot see: the panel is in ``#tm-system``,
it loads when the System tab opens, it reads the one KPI GET, the route has left the no-UI list, and every string is keyed
in all twelve locales.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import function_body

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"
_LOCALES = _STATIC / "locales"

_STRINGS = [
    "Measures (K1–K14)",
    "The K1–K14 measures this build keeps, each with its own method; hover a measure for it.",
    "Each measure stands alone: there is no overall score. “Not measurable here” means its instrument has not run on this "
    "machine, not that it failed.",
    "No measures could be read.",
    "meets its target", "misses its target", "not measurable here", "measured, no target set yet",
    "target", "recorded", "first slice in", "no first slice yet", "not measured", "unknown", "as of", "value", "n = {n}",
    "Loading…", "Could not load:",
    "Climate", "Elections", "Law", "OpenStreetMap", "Wikipedia",
    "datasets fetched", "datasets listed", "countries on the floor", "countries covered", "only a passed projection",
    "present but dateless", "missing", "snapshot rows", "tracked documents", "baselined", "jurisdictions",
    "documents never checked", "countries listed", "countries with change files", "change files recorded", "gaps",
    "editions listed", "editions that have run", "editions with pages seen", "editions holding a text", "pages seen",
]


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def test_kpi_panel_node_suite() -> None:
    proc = subprocess.run(["node", str(_ROOT / "tests" / "kpi_panel_node_test.js")],  # noqa: S607
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_panel_sits_in_the_system_tab_and_loads_when_it_opens() -> None:
    html = _read("index.html")
    system = html[html.index('id="tm-system"'):]
    system = system[: system.index("</div>\n      </div>")]
    assert 'id="vitals-kpi"' in system, "the measures panel left the System tab"
    fn = function_body(_read("app-core.js"), "tmSelectTab")
    assert re.search(r'key === "system"\) renderKpiPanel\("vitals-kpi"\)', fn), "the System tab no longer loads the measures"
    assert 'api("/api/diagnostics/kpi")' in function_body(_read("app-library.js"), "renderKpiPanel")


def test_the_kpi_route_has_a_caller_and_left_the_no_ui_list() -> None:
    tsv = (_ROOT / "configs" / "routes_without_ui.tsv").read_text(encoding="utf-8")
    assert "\t/api/diagnostics/kpi\t" not in tsv


def test_every_panel_string_is_keyed_in_all_twelve_locales() -> None:
    lib = _read("app-library.js")
    for s in ("meets its target", "countries on the floor", "editions holding a text", "No measures could be read."):
        assert f'"{s}"' in lib, s  # the list above is the renderer's, not a copy that drifted
    missing = []
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _STRINGS:
            if not str(data.get(s, "")).strip():
                missing.append(f"{path.name}: {s[:48]!r}")
    assert not missing, missing
