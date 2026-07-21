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
    # "Everything" is the default selection: a present category is CHECKED (field ask
    # 2026-07-02) so a backup covers corpus + wiki + maps + models unless unticked.
    assert '(d.count || 0) > 0 ? "checked" : "disabled"' in _APP


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
    # the corpus MERGE phase reports step N/M so it gets a determinate bar + the same
    # rule-of-three ETA (field ask 2026-07-02) instead of an indeterminate spinner
    assert "p.merge_steps" in _APP
    # the import summary reuses the merge-plan table (new / already-present / conflicts)
    assert "_renderImportSummary" in _APP and "_v2PlanTable" in _APP
    # and leads with a prominent aggregate "backup successful" view: imported +
    # deduplicated totals (real backend counts) + the additive-restore honesty note
    assert "Import successful" in _APP
    assert '"imported"' in _APP and '"deduplicated"' in _APP
    assert "Additive restore: nothing in your corpus was replaced or deleted." in _APP


def test_post_import_headline_is_articles_first_never_a_cross_table_row_sum():
    """Root-cause fix (maintainer field report 2026-07-20, after merging a 10 GB
    corpus: "4,855,433 imported… I'm sure it doesn't contain 5 million articles"):
    the old headline summed EVERY merged TABLE (articles, keyword mentions, links,
    dates, custody rows, …) under the single unlabeled word "imported". The redesign
    must lead with ARTICLES specifically, keep the old cross-table row-sum ONLY under
    an explicit "database records, all types" label, and never re-introduce an
    unlabeled sum of every plan table."""
    fn = _APP[_APP.index("function _renderImportSummary("):]
    fn = fn[: fn.index("\n    }\n")]
    # the headline is built from plan.articles specifically, not a sum over every key
    assert "p.articles" in fn or "art.new" in fn
    assert 'art.new || 0' in fn
    # the old bug pattern (summing every value in the plan with no per-table split)
    # may still exist ONLY as the explicitly-labeled catch-all, never unlabeled
    assert "database records, all types" in fn
    # a tally-only run (newsletters/large-data, no per-table plan) keeps ITS own
    # original generic stat -- this redesign must not regress that shipped path
    assert "sawPlan" in fn


def test_post_import_per_type_breakdown_is_labeled_not_a_row_sum():
    """The per-table detail must surface as INDIVIDUALLY labeled counts (ruling
    2026-07-20's exact list), not folded back into one number."""
    fn = _APP[_APP.index("function _renderImportSummary("):]
    fn = fn[: fn.index("\n    }\n")]
    for key in (
        "sources", "keywords", "keyword_mentions", "article_links",
        "law_documents", "wiki_pages", "article_analyses",
    ):
        assert f'"{key}"' in fn, key
    for label in ("Sources", "Keywords", "Keyword mentions", "Links", "Law docs", "Wiki pages", "Analyses", "Events"):
        assert f't("{label}")' in fn, label


def test_post_import_corpus_delta_view_is_wired():
    """The dedicated CORPUS-DELTA view (before -> after per dimension) is rendered
    from the backend's cheap-counter snapshot (never a post-merge whole-table
    re-scan) and reaches the renderer through every push site."""
    assert "_uxCorpusDeltaView" in _APP
    dv = _APP[_APP.index("function _uxCorpusDeltaView("):]
    dv = dv[: dv.index("\n    }\n")]
    for label in ("Articles", "Sources", "Languages", "Countries", "Keywords", "Date range", "Before", "After"):
        assert f't("{label}")' in dv, label
    # _uxPlanExtras carries corpus_delta (+ the re-index / events signals) from a
    # run_restore() report into every summaries.push() call site
    assert "function _uxPlanExtras(" in _APP
    extras = _APP[_APP.index("function _uxPlanExtras("):]
    extras = extras[: extras.index("\n    }\n")]
    assert "r.corpus_delta" in extras
    assert "r.reindexed" in extras
    assert "_uxPlanExtras(rep)" in _APP


def test_post_import_positive_but_honest_growth_line_uses_i18n_template():
    """Positive-but-honest framing (ruling: "imports should give positive
    feedback") — the delta itself is the good news, via a fixed OOI18N.tf template
    (never string-concatenated, so it stays translatable) with real deltas only."""
    fn = _APP[_APP.index("function _renderImportSummary("):]
    fn = fn[: fn.index("\n    }\n")]
    assert "Your corpus grew by {articles} articles from {sources} new sources spanning {languages} new languages." in fn


def test_post_import_work_induced_queue_never_claims_unbuilt_qualification():
    """(3) WORK INDUCED, stated honestly: new sources, articles still awaiting
    indexing, discovery candidates. The qualification LIFECYCLE (ledger ruling,
    same-day amend) is NOT yet built in this codebase (no qualification-status
    column/gate exists), so a new source must be reported plainly -- never as
    "awaiting qualification", which would fabricate a queue state the app cannot
    actually enforce."""
    fn = _APP[_APP.index("function _renderImportSummary("):]
    fn = fn[: fn.index("\n    }\n")]
    assert 't("New sources")' in fn
    assert 't("Articles awaiting indexing")' in fn
    assert 't("Discovery candidates")' in fn
    # "qualification" may appear in explanatory CODE COMMENTS (documenting the
    # deferral), but must never be user-facing text: no t("...qualification...")
    import re as _re
    assert not _re.search(r't\(\s*"[^"]*qualification[^"]*"', fn, _re.I)


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


def test_backup_poll_is_job_state_as_truth_not_transport_failure():
    """B5 (field-test Item 9): a dropped /volumes/status poll must NOT print a fatal
    "Backup failed" over a healthy running job. The poll retries transport hiccups with
    backoff and shows an honest "connection hiccup — retrying"; only a backend-reported
    error/cancelled STATE is a real failure."""
    poll = _APP[_APP.index("function _uxPoll("):]
    poll = poll[: poll.index("\n    }\n")]
    # a transport catch retries (does not reject on the first failed poll)
    assert "Connection hiccup" in poll
    assert "MAX_FAILS" in poll and "fails++" in poll
    # only a backend error/cancelled state rejects
    assert 'state === "error"' in poll and 'state === "cancelled"' in poll
    # the START request is ALSO job-state-as-truth: a lost start response consults /status
    # before declaring failure, so a running job never shows a fatal "Backup failed".
    assert "_uxStartThenPoll" in _APP
    starter = _APP[_APP.index("async function _uxStartThenPoll("):]
    starter = starter[: starter.index("\n    }\n")]
    assert "await api(statusUrl)" in starter and "throw e" in starter
    # every start/resume/verify goes through it (no bare await api(.../start) left)
    assert "() => api(\"/api/backup/v2/volumes/start\"" in _APP
    assert "() => api(\"/api/backup/folder/resume\"" in _APP


def test_backup_pause_resume_and_paused_label_are_wired():
    """B5: paused != complete. The export dialog exposes Pause/Resume, and a paused job
    shows the paused label (never "Backup complete")."""
    assert 'id="ux-pause"' in _HTML and "_uxPauseResume" in _APP
    assert "_uxShowPaused" in _APP and "Backup paused." in _APP
    # pause routes to the live phase's endpoint; resume continues, never re-does finished work
    assert "/api/backup/v2/volumes/pause" in _APP and "/api/backup/folder/pause" in _APP
    assert "/api/backup/folder/resume" in _APP


def test_backup_verify_job_is_wired_into_the_import_dialog():
    """B5: the shipped verify job is reachable — verify a backup's integrity without
    restoring (the live corpus untouched), reporting bad/missing volumes + recoverability."""
    assert "_uxImVerify" in _APP and "_uxRenderVerify" in _APP
    assert "/api/backup/v2/volumes/verify" in _APP
    assert 'onclick="_uxImVerify(this)"' in _HTML
    # honest report fields (no score): bad/missing volumes + parity recoverability
    assert "bad_volumes" in _APP and "recoverable" in _APP


def test_reopening_the_import_dialog_recovers_the_last_completed_summary():
    """Field report 2026-07-16: "after a successful import/merge, the interface
    doesn't show the amounts of deduplicated and other import statistics." Root
    cause: a large restore runs for hours as a background job, so the tab is very
    likely closed/reloaded before it finishes -- and openUnifiedImport() then
    unconditionally blanked #ux-imp-summary on every reopen, discarding the result
    forever. Each job manager is a process-wide singleton whose last completed
    summary survives any number of page reloads, so the dialog-open handler must
    recover and render it -- never just wipe it."""
    assert "_uxShowLastCompletedSummary" in _APP
    fn = _APP[_APP.index("async function _uxShowLastCompletedSummary("):]
    fn = fn[: fn.index("\n    }\n")]
    # checks the same three job kinds the live run itself populates a summary from
    for ep in ("/api/backup/v2/volumes/status", "/api/backup/folder/status", "/api/newsletters/import-folder/status"):
        assert ep in fn, ep
    # only a TERMINAL, successful state is ever shown (never a running/error job's
    # stale progress), and the folder check is restore-scoped (never a backup's stats
    # bleeding into the Import dialog)
    assert 's.state === "done"' in fn
    assert 's.mode === "restore"' in fn
    # reuses the SAME renderer the live run uses -- one code path, not a duplicate
    assert "_renderImportSummary(document.getElementById(\"ux-imp-summary\")" in fn
    # openUnifiedImport() must actually call it (wiring, not just a dangling helper)
    opener = _APP[_APP.index("function openUnifiedImport("):]
    opener = opener[: opener.index("\n    }\n")]
    assert "_uxShowLastCompletedSummary()" in opener


def test_reopening_the_export_dialog_recovers_the_last_completed_backup():
    """Audit finding 2026-07-17: the same field report 2026-07-16 root cause the
    Import dialog was fixed for ("after a successful run, the interface doesn't
    show the result") applies to the EXPORT dialog too. A large export can run for
    hours as a background job, so the tab is very likely closed/reloaded before it
    finishes -- and openUnifiedExport() unconditionally blanked #ux-progress on
    every reopen, discarding the "Backup complete" result forever. Each job
    manager is a process-wide singleton whose last completed state survives any
    number of page reloads, so the dialog-open handler must recover and render it
    -- never just wipe it."""
    assert "_uxShowLastCompletedExportSummary" in _APP
    fn = _APP[_APP.index("async function _uxShowLastCompletedExportSummary("):]
    fn = fn[: fn.index("\n    }\n")]
    # checks the same two job kinds the live export run itself populates a status from
    for ep in ("/api/backup/v2/volumes/status", "/api/backup/folder/status"):
        assert ep in fn, ep
    # filtered to a BACKUP job (never showing a restore's or verify's status in the
    # export dialog), and a paused run is shown as paused, never as complete.
    assert 's.mode === "backup"' in fn
    assert '"paused"' in fn and '"done"' in fn
    # openUnifiedExport() must actually call it (wiring, not just a dangling helper)
    opener = _APP[_APP.index("async function openUnifiedExport("):]
    opener = opener[: opener.index("\n    }\n")]
    assert "_uxShowLastCompletedExportSummary()" in opener


def test_llm_models_are_integrated_not_a_separate_panel():
    # the separate .oomodels panel + its handlers are gone
    assert "<h2>Local LLM models (separate backup)</h2>" not in _HTML
    assert "modelsBackupExport" not in _APP and "modelsBackupImport" not in _APP
    # models are now a category in the unified dialogs (export checklist + import scan)
    assert "ux-c-models" in _APP  # export checklist item
    assert "b.models" in _APP  # import scan shows the models blobs
    assert 'models: "models"' in _APP  # import restores the models category (blob_roots mapping)
