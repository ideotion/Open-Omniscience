"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

T6 — the Settings restore-preview UI on the /api/backup/v2 endpoints
(RC-gate section 1: "a non-technical operator can preview+merge from the
UI"). The API behaviour itself is covered by test_backup_v2_api.py; this
file pins the UI contract: the v2 flow is the PRIMARY path, preview comes
before commit, the legacy replace-style tools are demoted to a collapsed
details block, and the JS speaks the API's exact form fields.
"""

from __future__ import annotations

from pathlib import Path

_HTML = (Path(__file__).resolve().parents[1] / "src" / "static" / "index.html").read_text(
    encoding="utf-8"
)


def test_v2_flow_is_the_primary_backup_path():
    panel = _HTML.split('id="backup-panel"', 1)[1].split("</section>", 1)[0]
    v2_pos = panel.find('id="v2-pass"')
    legacy_pos = panel.find('onclick="downloadBackup()"')
    assert v2_pos != -1 and legacy_pos != -1
    assert v2_pos < legacy_pos, "the signed-archive flow must come before the legacy tools"
    # Additive-only restore (maintainer ruling 2026-06-13): the destructive
    # replace-restore is REMOVED entirely (not merely demoted). The legacy block
    # keeps only the raw .db snapshot DOWNLOAD; the merge is the ONLY restore.
    assert 'onclick="restoreBackup()"' not in _HTML, (
        "the destructive replace-restore must be GONE — restore is additive-only"
    )
    assert 'onclick="encryptedRestore()"' not in _HTML


def test_v2_preview_precedes_commit_and_warns_on_failed_verification():
    assert "v2Preview" in _HTML and "v2Apply" in _HTML and "v2Discard" in _HTML
    js = _HTML.split("async function v2Apply", 1)[1].split("async function", 1)[0]
    assert "_v2Token" in js, "apply must use the preview's one-shot commit token"
    prev = _HTML.split("async function v2Preview", 1)[1].split("async function", 1)[0]
    assert '"v2-apply-btn").disabled = !ver.ok' in prev, (
        "a failed verification must disable Apply (the merge would refuse anyway; "
        "the UI must not invite it)"
    )


def test_js_matches_the_api_form_contract():
    # The API expects multipart fields named exactly: file, passphrase, token.
    assert 'fd.append("file", f)' in _HTML
    assert 'fd.append("passphrase"' in _HTML
    assert 'fd.append("token", _v2Token)' in _HTML
    assert '"/api/backup/v2/restore/preview"' in _HTML
    assert '"/api/backup/v2/restore/commit"' in _HTML
    assert '"/api/backup/v2"' in _HTML


def test_merge_semantics_stated_to_the_operator():
    # The non-technical promise, verbatim in the chrome (and keyed x12):
    assert "nothing is replaced\n        or deleted" in _HTML.replace("<b>merges</b>", "merges") or (
        "nothing is replaced" in _HTML
    )
    assert "your local version is kept" in _HTML
    assert "safety snapshot" in _HTML
