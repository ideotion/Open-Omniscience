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

import json
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
    # Any quote style: a template literal or a concatenation must not slip a variable write flag past this.
    starts = re.findall(r"""["'`]/api/quarantine/start[^"'`]*["'`]""", _JS)
    assert starts == ['"/api/quarantine/start?write=false"'], starts
    assert not re.search(r"write\s*=\s*\$\{|write=['\"`]\s*\+", _JS), "a write flag must never be a variable"
    # No other module of the app starts a run on the panel's behalf.
    assert "include_prose_gate" not in _JS


def test_a_paused_run_that_has_writing_on_is_not_resumable_from_here():
    """Resume continues in the paused run's OWN mode, so offering it for a write run would let the page
    write without ever spelling write=true."""
    assert 'st.state === "paused" && st.dry_run === true' in _JS
    assert 'show("maint-resume", st && st.state === "paused");' not in _JS


def test_every_request_is_an_existing_loopback_quarantine_route():
    urls = set(re.findall(r"""["'`](/api/[^"'`?]*)""", _JS))
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
    # ...and reopening it re-reads, because the Advanced loader only runs once per page.
    assert 'addEventListener("toggle"' in _JS


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


def test_no_raw_job_state_word_is_printed():
    """F1 (R289): the state line passes the job's state through t() (measured in an Arabic page: it read
    "الحالة: done"). A state with no word here is shown as sent, by ``_maintStateLabel`` only."""
    src = (_STATIC / "app-maintenance.js").read_text(encoding="utf-8")
    assert "String(st.state)" not in src, "the state line must go through _maintStateLabel"
    assert "_maintStateLabel(st.state, t)" in src
    assert "esc(d.method)" not in src and "esc(data.method)" not in src, "method sentences go through _maintMethodHtml"
    assert "esc(String(st.error))" not in src, "a failed run's error text is labelled by _maintServerTextHtml"
    for locale_file in sorted((_STATIC / "locales").glob("*.json")):
        lang = locale_file.stem
        loc = json.loads(locale_file.read_text(encoding="utf-8"))
        for key in ("running", "paused", "done", "error", "cancelled", "Server text, in English"):
            assert loc.get(key), (lang, key)
