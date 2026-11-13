"""The Evidence & custody tab's «Check a file» (Lane M, R684): two server checks given a button.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``POST /api/reports/evidence/verify`` and ``POST /api/verify/image-metadata`` existed with no
caller. They now sit behind one compact file picker in the custody tab. Both are loopback and
store nothing, so neither passes the network consent popup (#14 gates egress, not local reads).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"


def test_the_custody_tab_carries_one_compact_file_check():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    tab = html.split('id="tab-custody"', 1)[1].split('<div class="tab-page"', 1)[0]
    for node in (
        'id="cust-check-btn"',
        'id="cust-check-file"',
        'id="cust-check-key"',
        'id="cust-check-result"',
    ):
        assert node in tab, node
    assert 'accept=".json,application/json,image/*"' in tab
    # bound with addEventListener, never an inline handler
    assert "cust-check-btn" in tab and 'id="cust-check-btn" data-on-click' not in tab


def test_the_checks_call_their_routes_and_stay_on_this_machine():
    js = (_STATIC / "app-evidence.js").read_text(encoding="utf-8")
    body = js.split("async function custodyCheckFile(", 1)[1].split("\n    }\n", 1)[0]
    assert '"/api/verify/image-metadata"' in body and '"/api/reports/evidence/verify"' in body
    assert '"/api/custody/verify"' in body and "require_signer: true" in body
    assert "trusted_public_key" in body
    assert "http://" not in body and "https://" not in body
    src = (_ROOT / "src" / "api" / "verification.py").read_text(encoding="utf-8")
    assert "get_db" not in src and "Session" not in src, "the image check reads, it never stores"


def test_the_renderers_behave():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "file_check_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_source_trail_shows_observed_server_ips():
    """Sources tab, same lane: ``GET /api/sources/{id}/observed-ips`` had no caller. The
    source trail panel now shows the IPs a source answered from, with the CDN caveat visible.
    A failure of that one call leaves the line out rather than failing the panel."""
    js = (_STATIC / "app-sources.js").read_text(encoding="utf-8")
    body = js.split("async function toggleSourceTrail(", 1)[1].split("\n    }\n", 1)[0]
    assert "/observed-ips`).catch(() => null)" in body
    assert "srcIpsHtml(ips, t, tf)" in body
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "source_ips_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout
