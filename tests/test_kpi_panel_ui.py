"""R751(c): the K1–K14 measures in the task manager's System tab.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The renderer is run as real code in node (``kpi_panel_node_test.js``: unknown never 0, no tally, the caveat visible, the
five K13 blocks with their own counts). This file pins the wiring the node suite cannot see: the panel is in ``#tm-system``,
it loads when the System tab opens, it reads the one KPI GET, the route has left the no-UI list, and every string is keyed
in all twelve locales.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, object_literal

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
    "Climate", "Elections", "Law", "Medical papers", "OpenStreetMap", "Wikipedia",
    "datasets fetched", "datasets listed", "countries on the floor", "countries covered", "only a passed projection",
    "present but dateless", "missing", "snapshot rows", "tracked documents", "baselined", "jurisdictions",
    "documents never checked", "countries listed", "countries with change files", "change files recorded", "gaps",
    "editions listed", "editions that have run", "editions with pages seen", "editions holding a text", "pages seen",
    "update files applied last run", "update files listed", "update files remaining", "papers kept",
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


def _js_object_keys(src: str, name: str) -> set[str]:
    """The keys of ``const NAME = {...}`` in the shipped module: each key is a bare name followed by a list or a string."""
    body = object_literal(src, name)
    return set(re.findall(r"(?<![\w\"])([A-Za-z_][A-Za-z0-9_]*): [\[\"]", body))


def _server_verticals() -> list[str]:
    """The vertical names ``_k13_verticals`` builds, read from its source: the one list the server sends."""
    tree = ast.parse((_ROOT / "src" / "monitoring" / "kpi.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_k13_verticals")
    loop = next(n for n in ast.walk(fn) if isinstance(n, ast.For))
    return [elt.elts[0].value for elt in loop.iter.elts]  # type: ignore[attr-defined]


def test_every_vertical_the_server_sends_has_a_name_and_a_figure_list() -> None:
    """Row 207: a block whose vertical has no ``_KPI_FIGURES`` entry shows its name and method but no number (the medical
    block did, for one release). Guards every future vertical the same way."""
    lib = _read("app-library.js")
    names = _server_verticals()
    assert len(names) >= 6 and "medical" in names, names
    figures, labels = _js_object_keys(lib, "_KPI_FIGURES"), _js_object_keys(lib, "_KPI_VERTICAL")
    assert not set(names) - figures, f"no figure list for {sorted(set(names) - figures)}"
    assert not set(names) - labels, f"no name for {sorted(set(names) - labels)}"


def test_the_medical_figures_are_counts_the_real_block_sends(tmp_path, monkeypatch) -> None:
    """Each medical figure the panel draws is a key the real block carries, holding a count (K13: counts only); the
    block's file name is not one of them."""
    from src.monitoring import kpi as K

    monkeypatch.setattr(K, "_coverage_path", lambda: tmp_path / "keyword-coverage.json")
    K.record_medical_fetch({"fetched_at": "2026-11-18T10:00:00+00:00", "listed": 40, "remaining": 33, "applied": 7,
                            "failed": False, "stopped": False, "papers": 3,
                            "by_class": {"journal": 2, "preprint": 0, "retracted": 1}, "coverage": {},
                            "last_file": "pubmed25n1400.xml.gz"})
    block = K._medical_block()
    lib = _read("app-library.js")
    entry = re.search(r"\bmedical: \[(.*?)\]\],", lib, re.S).group(1)
    keys = re.findall(r'\["([a-z_]+)", "', entry)
    assert keys == ["files_applied_last_run", "files_listed", "files_remaining", "papers_kept"], keys
    assert {k: block[k] for k in keys} == {"files_applied_last_run": 7, "files_listed": 40, "files_remaining": 33,
                                            "papers_kept": 3}
