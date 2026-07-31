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

# index.html's JS/CSS were externalised into cached app.js/app.css (audit PR H), so
# the UI source the assertions grep is the three files together (a MOVE, not a loss).
_STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = "\n".join(
    (_STATIC_DIR / f).read_text(encoding="utf-8")
    for f in ("index.html", "app.js", "app.css")
    if (_STATIC_DIR / f).exists()
)


def test_single_file_create_is_removed_backups_go_through_unified_export():
    # The size-capped single-file CREATE was retired (2026-07-01): no create endpoint,
    # no v2Backup, no "download full backup" button. Backups are made by the unified
    # Export dialog; only the legacy single-file RESTORE remains (migration).
    assert '"/api/backup/v2"' not in _HTML       # the create endpoint URL is gone
    assert "function v2Backup" not in _HTML
    assert "Download full backup" not in _HTML
    assert "openUnifiedExport(" in _HTML         # the replacement create path


def test_additive_only_restore_no_destructive_paths():
    # Additive-only restore (maintainer 2026-06-13): the destructive replace-restore
    # is REMOVED entirely; the merge is the ONLY restore.
    assert 'onclick="restoreBackup()"' not in _HTML, (
        "the destructive replace-restore must be GONE — restore is additive-only"
    )
    assert 'onclick="encryptedRestore()"' not in _HTML


# REMOVED 2026-07-31 (Settings review, ruling 7): test_v2_preview_precedes_commit_and_
# warns_on_failed_verification and test_js_matches_the_api_form_contract both guarded the
# legacy-restore UPLOAD FORM (file picker -> preview -> apply, multipart file/passphrase/
# token). That panel is gone, so both asserted properties of markup that no longer exists.
# The /v2/restore preview+commit ENDPOINTS they exercised are deliberately retained and
# still pinned by test_additive_restore_only; restoring an existing single-file backup now
# runs through the unified Import (test_legacy_single_file_restore_is_kept_for_migration).


def test_merge_semantics_stated_to_the_operator():
    """The non-technical additive-restore promise must stay visible to the operator.

    2026-07-31: it moved with the restore itself. The legacy panel's wording went with
    that panel; the unified Import states the same guarantee, so this asserts it there.
    The promise is the point — where it is rendered is not."""
    assert "Additive restore: nothing in your corpus was replaced or deleted." in _HTML
