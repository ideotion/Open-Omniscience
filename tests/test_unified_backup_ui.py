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
        "/api/backup/legacy/restore",  # legacy single-file backups now import in the unified dialog
    ):
        assert ep in _APP, ep


def test_dialogs_have_a_real_progress_bar_and_import_summary():
    # honest <progress> bars (never a fake %) + a post-import summary
    assert 'id="ux-bar"' in _HTML and 'id="ux-imp-bar"' in _HTML
    assert 'id="ux-imp-summary"' in _HTML
    # the poller paints the bar from the manager's real status, indeterminate when
    # no total is known (the volume engine streams) — never a fabricated number
    assert "_uxPaintBar" in _APP and "_uxProgressView" in _APP
    assert "removeAttribute(\"value\")" in _APP  # indeterminate = no fake %
    # the import can be sent to the background (jobs keep running, task manager shows
    # them) so the user isn't trapped in the modal — field ask 2026-07-02
    assert 'id="ux-imp-bg"' in _HTML and "_uxImBackground" in _APP
    assert "openTaskManager" in _APP
    # a rule-of-three time-remaining ESTIMATE on the long byte-based copies (folder
    # restore) — the maintainer's ask: humans prefer an approximate ETA to none. It is
    # marked approximate ("~ … left") and computed from wall-clock elapsed × remaining.
    assert "_uxRuleOfThree" in _APP
    assert "elapsed * (1 - frac) / frac" in _APP
    # the import summary reuses the merge-plan table (new / already-present / conflicts)
    assert "_renderImportSummary" in _APP and "_v2PlanTable" in _APP
    # and leads with a prominent aggregate "backup successful" view: imported +
    # deduplicated totals (real backend counts) + the additive-restore honesty note
    assert "Import successful" in _APP
    assert '"imported"' in _APP and '"deduplicated"' in _APP
    assert "Additive restore: nothing in your corpus was replaced or deleted." in _APP


def test_import_restores_each_volume_set_from_its_own_scanned_path():
    # root-cause fix: a nested volume set restores from c.path, not the scanned parent
    assert "c.path" in _APP
    assert "blob_roots" in _APP  # blobs grouped by their parent root for folder/restore


def test_import_failure_surfaces_the_real_error_not_see_console():
    # the swallowed "Import failed — see console" is replaced by the backend detail
    assert "Import failed:" in _APP


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
    assert "b.models" in _APP  # import scan shows the models blobs
    assert 'models: "models"' in _APP  # import restores the models category (blob_roots mapping)
