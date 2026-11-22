"""Row 325 (R788 follow-up): a restore refused because a country-code migration left the corpus half done is named as such.

R788 (#2288) made a committing restore refuse such a corpus (``merge.refuse_half_migrated_store``, raising
``HalfMigratedStoreRefused``, a ``RestoreRefused``). Two things were left: the volume restore journalled it as the swap barrier
(``reason="barrier"``: "another job still held the corpus when the restore reached the swap"), which sends the operator after a lease
holder that does not exist, and both staging paths asked it only inside ``run_restore``, after the whole backup had been verified,
reassembled and decrypted. Now the refusal has its own journal reason, and both staging paths ask it before a byte is decrypted, BEFORE
the writer-jobs check (which stops the jobs it may stop and starts them again only when it refuses itself).
"""

from __future__ import annotations

from pathlib import Path

from tests.js_source_helper import python_function_source

ROOT = Path(__file__).resolve().parents[1]


def test_the_journal_has_its_own_sentence_for_it():
    from src.monitoring import storage_events as se

    said = se.RUN_REFUSALS["half-migrated"]
    assert "migration" in said and "did not finish" in said and "could not be read" in said
    assert "held the corpus" not in said and said != se.RUN_REFUSALS["barrier"]


def test_the_journal_writes_that_sentence_for_the_reason(monkeypatch):
    from src.monitoring import storage_events as se

    written: list[dict] = []
    monkeypatch.setattr(se, "end", lambda kind, key, fields: written.append(fields))
    note = se.RunNote(kind="import", key="k", started=0.0)
    se.run_ended(note, "refused", failure="HalfMigratedStoreRefused", reason="half-migrated")
    assert written and written[0]["reason"] == se.RUN_REFUSALS["half-migrated"]
    assert written[0]["error"] == "HalfMigratedStoreRefused"


def test_the_volume_restore_journals_it_apart_from_the_barrier():
    vj = (ROOT / "src/backup/volume_job.py").read_text("utf-8")
    branch = vj[vj.index("elif issubclass(type(exc), HalfMigratedStoreRefused):") :][:200]
    assert 'reason="half-migrated"' in branch and 'reason="barrier"' not in branch
    # The writer-jobs branch comes first (both are RestoreRefused); the barrier is what is left.
    assert vj.index("if issubclass(type(exc), WriterJobsRefused):") < vj.index("elif issubclass(type(exc), HalfMigratedStoreRefused):")


def test_the_single_file_restore_journals_it_on_both_asks():
    legacy = (ROOT / "src/api/backup_v2.py").read_text("utf-8")
    assert legacy.count('reason="half-migrated"') == 2, "the ask before staging and the one inside run_restore"
    inner = legacy.index("except HalfMigratedStoreRefused as exc:", legacy.index("report = run_restore("))
    assert inner < legacy.index("except (MergeError, RestoreRefused) as exc:", inner), "caught before the generic refusal"


def test_both_staging_paths_ask_before_a_byte_is_decrypted_and_before_the_writer_check():
    vj = (ROOT / "src/backup/volume_job.py").read_text("utf-8")
    ask = vj.index("refuse_half_migrated_store()")
    assert ask < vj.index("refuse_while_writer_jobs_run()") < vj.index("staged = read_volume_backup(")
    legacy = (ROOT / "src/api/backup_v2.py").read_text("utf-8")
    ask = legacy.index("refuse_half_migrated_store()")
    assert legacy.index("data = p.read_bytes()") < ask < legacy.index("refuse_while_writer_jobs_run()") < legacy.index("staged = _stage_upload(")


def test_run_restore_still_asks_before_preparing_and_at_the_working_copy():
    body = python_function_source((ROOT / "src/backup/merge.py").read_text("utf-8"), "run_restore")
    assert body.count("refuse_half_migrated_store()") == 2
