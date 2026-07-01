"""
Absorption guard for the unified Import/Export consolidation (Slices 1-3).

The scattered backup/restore panels were collapsed into two dialogs. This test
asserts the dialogs still route to EVERY always-works capability (the "never lose a
tool" lesson), and that the redundant panels + the capped single-file CREATE UI are
gone. Reads the static sources — no browser needed.
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")


def test_unified_dialogs_exist():
    for needle in ('id="ux-export"', 'id="ux-import"', "openUnifiedExport(", "openUnifiedImport("):
        assert needle in _HTML or needle in _APP, needle


def test_export_dialog_covers_the_streaming_backup_capabilities():
    # inventory + the two always-works engines the removed panels used
    for ep in ("/api/backup/inventory", "/api/backup/v2/volumes/start", "/api/backup/folder/start"):
        assert ep in _APP, ep


def test_import_dialog_covers_restore_and_ingest_capabilities():
    for ep in (
        "/api/backup/import-scan",
        "/api/backup/v2/volumes/restore",
        "/api/backup/folder/restore",
        "/api/newsletters/import-folder",
    ):
        assert ep in _APP, ep


def test_redundant_panels_were_collapsed():
    # the two panels fully covered by the dialogs are gone from the UI
    assert 'id="folder-backup-panel"' not in _HTML
    assert 'id="vbackup-panel"' not in _HTML


def test_capped_single_file_create_ui_is_removed():
    # the option that fails at scale is no longer offered as a CREATE control
    assert "v2Backup(false)" not in _HTML
    assert "Download full backup" not in _HTML


def test_legacy_single_file_restore_is_kept_for_migration():
    # restoring an EXISTING single-file backup stays reachable (data-safety)
    assert "v2Preview()" in _HTML


def test_llm_models_are_integrated_not_a_separate_panel():
    # the separate .oomodels panel + its handlers are gone
    assert "<h2>Local LLM models (separate backup)</h2>" not in _HTML
    assert "modelsBackupExport" not in _APP and "modelsBackupImport" not in _APP
    # models are now a category in the unified dialogs (export checklist + import scan)
    assert "ux-c-models" in _APP  # export checklist item
    assert 'cats.push("models")' in _APP  # import restores the models category
