"""The Maintenance section of Settings -> Advanced (R196): a dry run and two reports, read without curl.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What must hold:

* DRY RUN ONLY. The panel's one start URL spells ``write=false`` and no other file of the panel builds a start URL,
  so there is no path by which the page could write (ruled 2026-10-26, R196 point 2).
* LOOPBACK AND READ-ONLY. Every URL the panel requests is under ``/api/quarantine`` and one of the existing routes.
* THE PAGE IS WIRED: a Settings -> Advanced section (not a new Settings subtab, not a sidebar tab, R196 point 1),
  its loader on EXPAND, its script before boot, and the service worker caches it.
* THE DOC NAMES IT.

The renderers are driven in node (``tests/maintenance_node_test.js``).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"
_JS = (_STATIC / "app-maintenance.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")

_ROUTES = {
    "/api/quarantine/start",
    "/api/quarantine/status",
    "/api/quarantine/samples",
    "/api/quarantine/raw-id-sources",
    "/api/quarantine/source-furniture",
}


def test_the_panel_can_only_start_a_dry_run():
    assert "write=true" not in _JS and "write=1" not in _JS
    starts = re.findall(r'"/api/quarantine/start[^"]*"', _JS)
    assert starts == ['"/api/quarantine/start?write=false"'], starts
    # No other module of the app starts a run on the panel's behalf.
    assert "include_prose_gate" not in _JS


def test_every_request_is_an_existing_loopback_quarantine_route():
    urls = set(re.findall(r'"(/api/[^"?]*)', _JS))
    # "/api/quarantine/" is the pause / resume / cancel route's prefix; the reader path is a link, not a request.
    allowed = _ROUTES | {"/api/quarantine/", "/api/articles/${encodeURIComponent(r.id)}/view"}
    assert urls <= allowed, urls - allowed
    # pause / resume / cancel go through the one action route, with the verb allow-listed first.
    assert '["pause", "resume", "cancel"].indexOf(action) < 0' in _JS
    assert "http://" not in _JS and "https://" not in _JS


def test_it_is_an_advanced_section_not_a_tab():
    assert 'data-adv="maintenance"' in _HTML
    assert 'data-tab="maintenance"' not in _HTML, "R196: no new top-level or Settings subtab"
    shell = (_STATIC / "app-shell.js").read_text(encoding="utf-8")
    assert "maintenance: () => { loadMaintenance(); }" in shell, "loads on expand, never with the subtab"
    assert '<script src="/static/app-maintenance.js"></script>' in _HTML
    assert _HTML.index("app-maintenance.js") < _HTML.index('src="/static/app-boot.js"'), "boot runs last"
    assert '"/static/app-maintenance.js"' in (_STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_caveat_is_visible_and_nothing_hides_it():
    block = _HTML[_HTML.index('data-adv="maintenance"'):]
    block = block[: block.index("</details>")]
    assert 'class="card-caveat"' in block
    assert "not an error rate" in block
    assert "hidden" not in re.sub(r"\s", " ", block).replace('display:none', ""), "no [hidden] layer over the caveat"


def test_the_polling_stops_with_the_fold():
    assert "sec.open" in _JS, "a folded section must not keep a timer going"


def test_the_renderers_behave():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "maintenance_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_doc_names_the_panel():
    doc = (_ROOT / "docs" / "QUALIFICATION.md").read_text(encoding="utf-8")
    assert "Settings → Advanced → Maintenance" in doc
    assert "tests/test_maintenance_panel.py" in doc
