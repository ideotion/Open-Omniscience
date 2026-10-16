"""The storage-events journal's run kinds: the last ten volume backups, restores and verifications, and what they may carry (WAL, 2026-10-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``run-journal.json`` keeps the runs that opened a journal; a start that was REFUSED before any run existed (no passphrase, a destination
that cannot be made, a job already running) left nothing, and a process killed in the middle of a backup left only the lines the run
journal had flushed. ``run_export``, ``run_import`` and ``run_verify`` (``src/monitoring/storage_events.py``) are the durable last ten
of each kind, written OPEN at the start so a kill leaves "started, never ended".

What this file pins:

1. what a run may carry: numbers, flags, class names, a fixed refusal sentence and one of five read-back states, and NOTHING else: a hook
   that hands over a message, a path or a folder name leaves a marker or no field, never the text (the passphrase rule);
2. each kind has its own cap and the total counts every run;
3. the real manager's end branches record the right outcome, with the real worker threads and the real journal;
4. the hooks hand over ``type(exc).__name__`` and a key of the refusal table, by reading the sources, so a later hook cannot add text.
"""

from __future__ import annotations

import ast
import json
import re
import time
from pathlib import Path

import pytest

from src.backup import export_folder, export_summary
from src.backup import volume_job as vj
from src.backup.volume_job import VolumeBackupManager
from src.backup.volumes import VolumeStopped
from src.monitoring import storage_events as se

ROOT = Path(__file__).resolve().parents[1]
MARKER = "MARKER-passphrase-4711-correct-horse"


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    """A journal whose file is ``tmp_path``'s and whose background writer runs at test speed."""
    path = tmp_path / "storage_events.json"
    monkeypatch.setattr(se, "_path", lambda: path)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.02)
    se.reset_for_tests()
    yield path
    se.reset_for_tests()


def _events(kind: str) -> list[dict]:
    return se.diagnostics_member(10_000_000)["kinds"][kind]["events"]


def _only(kind: str) -> dict:
    events = _events(kind)
    assert len(events) == 1, events
    return events[0]


def _finish(mgr: VolumeBackupManager, timeout: float = 10.0) -> dict:
    """Wait for the job's state to settle, then for its worker thread to return: the journal's end is written after the state is."""
    t0 = time.time()
    while mgr.status()["running"] and time.time() - t0 < timeout:
        time.sleep(0.01)
    thread = mgr._thread
    if thread is not None:
        thread.join(timeout)
    return mgr.status()


def _nothing_secret_anywhere(journal_path: Path, *needles: str) -> None:
    """The marker (and every other needle) is in neither the file the journal wrote, the member, nor the slot's answer."""
    from src.api import diagnostics_slots as slots

    (slot,) = [s for s in slots.SLOTS if s.name == "storage-events.json"]
    se.flush()
    texts = {
        "the journal file": journal_path.read_text(encoding="utf-8"),
        "the member": json.dumps(se.diagnostics_member(10**9)),
        "the slot's answer": json.dumps(slots.thunk(slot)()),
    }
    for where, text in texts.items():
        for needle in needles:
            assert needle not in text, f"{needle!r} reached {where}"


# --------------------------------------------------------------------------- #
#  1. The API: what a run is, and what it may carry
# --------------------------------------------------------------------------- #
def test_a_run_is_written_open_and_closed_with_its_outcome_and_seconds(journal):
    note = se.run_started("export")
    assert note is not None
    (open_event,) = _events("run_export")
    assert open_event["open"] is True and "outcome" not in open_event, "a run in progress says only that it started"
    se.run_ended(note, "ok", volumes=3, bytes=12_345, gate_held_s=1.5, verify="verified")
    event = _only("run_export")
    assert event["open"] is False and event["outcome"] == "ok" and event["seconds"] >= 0
    assert (event["volumes"], event["bytes"], event["gate_held_s"], event["verify"]) == (3, 12_345, 1.5, "verified")
    assert event["ended_at"] and event["session"] == "this"
    assert se.diagnostics_member(10**9)["kinds"]["run_export"]["total"] == 1


def test_a_run_that_ended_cannot_be_ended_again_so_the_finally_net_is_harmless(journal):
    note = se.run_started("import")
    se.run_ended(note, "refused", failure="RestoreRefused", reason="barrier")
    se.run_ended(note, "ended-without-a-recorded-outcome")
    event = _only("run_import")
    assert event["outcome"] == "refused", "the net must never overwrite a real outcome"
    assert event["reason"] == se.RUN_REFUSALS["barrier"]


def test_an_unknown_kind_or_a_missing_note_does_nothing(journal):
    assert se.run_started("backup") is None and se.run_started("") is None
    se.run_ended(None, "ok")
    se.run_facts(None, volumes=1)
    se.run_free_space(None, "dest_free_bytes", "/")
    se.run_refused("nope", "no-passphrase")
    assert se.run_part("nope", summary_error="OSError") is False
    for kind in se.RUN_KINDS.values():
        assert se.diagnostics_member(10**9)["kinds"][kind]["total"] == 0


def test_an_outcome_outside_the_table_is_recorded_as_unnamed_and_never_as_the_text(journal):
    note = se.run_started("verify")
    se.run_ended(note, f"it went wrong {MARKER}")
    assert _only("run_verify")["outcome"] == "(unnamed outcome)"
    _nothing_secret_anywhere(journal, MARKER, "it went wrong")


@pytest.mark.parametrize(
    "value",
    ["it went wrong", "C:\\Users\\someone\\backup", "/home/someone/backup", MARKER, "x" * 81, "OSError: [Errno 28] No space left", "", "a b", b"bytes"],
)
def test_only_a_class_name_gets_into_an_error_field(journal, value):
    note = se.run_started("export")
    se.run_part("export", summary_error=value)
    se.run_ended(note, "error", failure=value)
    event = _only("run_export")
    assert event["error"] == "(not a class name)" and event["summary_error"] == "(not a class name)"
    _nothing_secret_anywhere(journal, MARKER, "someone", "No space")


@pytest.mark.parametrize("name", ["OSError", "PermissionError", "src.backup.merge.MergeError", "A", "_x1", "E" * 80])
def test_a_class_name_is_kept_as_it_is(journal, name):
    note = se.run_started("export")
    se.run_ended(note, "error", failure=name)
    assert _only("run_export")["error"] == name


def test_facts_keep_numbers_flags_class_names_and_the_five_read_back_states_and_drop_everything_else(journal):
    note = se.run_started("export")
    se.run_ended(
        note,
        "ok",
        volumes=2,
        bytes=3.5,
        dest=f"/home/someone/{MARKER}",  # an unknown key: dropped
        label=MARKER,  # an unknown key: dropped
        gate_held_s=MARKER,  # a number field handed text: dropped
        snapshot_s=True,  # a bool is not a number
        snapshot_bytes=float("nan"),  # not finite: dropped
        engine_wall_s=float("inf"),
        verify=f"verified {MARKER}",  # not one of the five states: dropped
        set_ok="yes",  # a flag handed text: dropped
    )
    event = _only("run_export")
    assert (event["volumes"], event["bytes"]) == (2, 3.5)
    for dropped in ("dest", "label", "gate_held_s", "snapshot_s", "snapshot_bytes", "engine_wall_s", "verify", "set_ok"):
        assert dropped not in event, dropped
    _nothing_secret_anywhere(journal, MARKER, "someone")


@pytest.mark.parametrize("state", sorted(se._RUN_VERIFY_STATES))
def test_each_of_the_five_read_back_states_is_kept(journal, state):
    assert state in {"verified", "failed", "off", "stopped", "unavailable"}
    note = se.run_started("export")
    se.run_ended(note, "ok", verify=state)
    assert _only("run_export")["verify"] == state


def test_a_flag_is_kept_only_as_a_bool(journal):
    note = se.run_started("verify")
    se.run_ended(note, "ok", set_ok=False)
    assert _only("run_verify")["set_ok"] is False


def test_a_refusal_writes_the_fixed_sentence_of_its_key_and_never_a_free_text(journal):
    se.run_refused("export", "destination-unusable", failure="PermissionError")
    se.run_refused("export", f"the folder /home/someone/{MARKER} is full")  # not a key: no sentence at all
    first, second = _events("run_export")
    assert first["reason"] == se.RUN_REFUSALS["destination-unusable"] and first["error"] == "PermissionError"
    assert "reason" not in second
    for event in (first, second):
        assert event["outcome"] == "refused" and event["ran"] is False and "open" not in event, "a start that never became a run is written closed"
    _nothing_secret_anywhere(journal, MARKER, "someone")


def test_a_run_that_ends_refused_writes_the_fixed_sentence_of_its_key_and_never_a_free_text(journal):
    known, unknown = se.run_started("import"), se.run_started("import")
    se.run_ended(known, "refused", reason="barrier")
    se.run_ended(unknown, "refused", reason=f"folder {MARKER} is full")  # not a key: no sentence at all
    first, second = _events("run_import")
    assert first["reason"] == se.RUN_REFUSALS["barrier"]
    assert "reason" not in second
    _nothing_secret_anywhere(journal, MARKER)


def test_every_refusal_sentence_is_fixed_text_with_no_slot():
    for key, sentence in se.RUN_REFUSALS.items():
        assert re.fullmatch(r"[a-z-]+", key), key
        assert "{" not in sentence and "%" not in sentence and "/" not in sentence and "\\" not in sentence, key


def test_run_part_reaches_the_newest_open_run_of_its_own_kind_only(journal):
    older = se.run_started("export")
    newest = se.run_started("export")
    other = se.run_started("import")
    assert se.run_part("export", summary_error="OSError") is True
    se.run_ended(newest, "ok")
    se.run_ended(older, "ok")
    se.run_ended(other, "ok")
    by_start = _events("run_export")
    assert [("summary_error" in e) for e in by_start] == [False, True], "only the newest open run of the kind"
    assert "summary_error" not in _only("run_import")


def test_run_part_with_no_open_run_does_nothing(journal):
    note = se.run_started("export")
    se.run_ended(note, "ok")
    assert se.run_part("export", summary_error="OSError") is False
    assert "summary_error" not in _only("run_export"), "a closed run is not reopened by a late step"


def test_free_bytes_of_walks_up_to_an_existing_parent(journal, tmp_path):
    free = se.free_bytes_of(tmp_path / "not" / "made" / "yet")
    assert isinstance(free, int) and free > 0


def test_an_unreadable_volume_leaves_the_field_absent_and_never_zero(journal, tmp_path, monkeypatch):
    def refuse(_path):
        raise PermissionError(f"nothing for you {MARKER}")

    monkeypatch.setattr(se.shutil, "disk_usage", refuse)
    assert se.free_bytes_of(tmp_path) is None
    note = se.run_started("export")
    se.run_free_space(note, "dest_free_bytes", tmp_path)
    se.run_ended(note, "ok")
    event = _only("run_export")
    assert "dest_free_bytes" not in event, "an unreadable figure is not 0, which would read as a full drive"
    _nothing_secret_anywhere(journal, MARKER)


def test_the_free_space_is_read_after_the_run_is_open_so_a_hang_leaves_it_open(journal, tmp_path, monkeypatch):
    seen: list[dict] = []

    def look(_path):
        seen.append(dict(_events("run_export")[-1]))
        raise OSError("gave up")

    monkeypatch.setattr(se.shutil, "disk_usage", look)
    note = se.run_started("export")
    se.run_free_space(note, "dest_free_bytes", tmp_path)
    assert seen and seen[0]["open"] is True, "the stat ran while the run was already open in the journal"


def test_a_fact_name_that_is_not_a_free_space_figure_is_not_read(journal, tmp_path):
    note = se.run_started("export")
    se.run_free_space(note, "bytes", tmp_path)
    se.run_free_space(note, f"x{MARKER}", tmp_path)
    se.run_ended(note, "ok")
    assert "bytes" not in _only("run_export")


def test_each_run_kind_has_its_own_cap_and_the_total_counts_every_run(journal):
    se.run_refused("export", "no-passphrase")
    for _ in range(se.KEEP["run_import"] + 3):
        se.run_ended(se.run_started("import"), "error", failure="MergeError")
    member = se.diagnostics_member(10**9)["kinds"]
    assert (member["run_import"]["kept"], member["run_import"]["total"], member["run_import"]["dropped"]) == (10, 13, 3)
    assert member["run_export"]["kept"] == 1, "twelve failed restores did not push the failed backup out"
    assert member["run_verify"]["total"] == 0


def test_a_run_the_process_was_killed_in_reads_as_started_and_never_ended(journal, monkeypatch):
    se.run_started("export")
    se.flush()
    se.reset_for_tests(keep_file=True)  # the process is gone, the file stays
    monkeypatch.setattr(se, "_PROC", "the-next-process")
    event = _only("run_export")
    assert event["session"] == "earlier" and event["open"] is False
    assert "not recorded" in event["ended"], "the next start says the run's end was never recorded"
    assert "outcome" not in event


def test_a_journal_that_cannot_record_never_raises_into_the_run_hooks(journal, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError(f"the journal is broken {MARKER}")

    monkeypatch.setattr(se, "record", broken)
    monkeypatch.setattr(se, "update", broken)
    monkeypatch.setattr(se, "end", broken)
    note = se.run_started("export")
    assert note is None
    se.run_refused("export", "no-passphrase")
    se.run_facts(se.RunNote("run_export", ("run", 1), 0.0), volumes=1)
    se.run_ended(se.RunNote("run_export", ("run", 1), 0.0), "ok")
    assert se.run_part("export", summary_error="OSError") is False
    assert MARKER not in json.dumps(se.diagnostics_member(10**9)), "a failure inside the journal is counted by class, never by its message"


# --------------------------------------------------------------------------- #
#  2. The real manager: every end branch of the three workers
# --------------------------------------------------------------------------- #
def _ok_backup(dest, pw, *, include_newsletters=True, parity_fraction=0.1, should_stop, progress_cb, include_blobs=None):
    return {
        "volumes": 4,
        "total_bytes": 4_000_000,
        "gate_held_s": 2.5,
        "snapshot_s": 3.25,
        "snapshot_bytes": 3_000_000,
        "wall_s": 90.5,
        "dest": str(dest),
        "envelope": {"k": 1},
    }


def test_a_backup_that_is_done_leaves_its_measurements_and_the_free_bytes_of_its_destination(journal, tmp_path):
    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "dest"), "pw", verify_after_write=False, _backup_fn=_ok_backup)
    assert _finish(mgr)["state"] == "done"
    event = _only("run_export")
    assert event["outcome"] == "ok" and event["open"] is False
    assert (event["volumes"], event["bytes"], event["gate_held_s"], event["snapshot_s"], event["snapshot_bytes"], event["engine_wall_s"]) == (
        4, 4_000_000, 2.5, 3.25, 3_000_000, 90.5)
    assert event["verify"] == "off"
    assert isinstance(event["dest_free_bytes"], int) and event["dest_free_bytes"] > 0
    assert "data_free_bytes" not in event, "a backup writes to its destination, not the data folder"


def test_a_backup_that_fails_leaves_the_class_and_no_word_of_the_exception_or_the_path(journal, tmp_path):
    dest = tmp_path / f"folder-{MARKER}"

    def failing(dest_, pw, **_k):
        raise RuntimeError(f"disk exploded at {dest_} while writing {pw}: {MARKER}")

    mgr = VolumeBackupManager()
    mgr.start_backup(str(dest), "the-typed-passphrase", _backup_fn=failing)
    assert _finish(mgr)["state"] == "error"
    event = _only("run_export")
    assert event["outcome"] == "error" and event["error"] == "RuntimeError" and event["seconds"] >= 0
    _nothing_secret_anywhere(journal, MARKER, "the-typed-passphrase", "disk exploded", str(tmp_path), "folder-")


def test_a_newsletter_filter_refusal_is_a_refused_run_with_the_class(journal, tmp_path):
    from src.backup.newsletter_export import NewsletterFilterRefused

    def refusing(dest_, pw, **_k):
        raise NewsletterFilterRefused(f"the driver said {MARKER}", space=False)

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "d"), "pw", include_newsletters=False, _backup_fn=refusing)
    assert _finish(mgr)["state"] == "error"
    event = _only("run_export")
    assert (event["outcome"], event["error"]) == ("refused", "NewsletterFilterRefused")
    _nothing_secret_anywhere(journal, MARKER, "the driver said")


def test_a_cancelled_backup_and_a_paused_one_are_two_different_outcomes(journal, tmp_path):
    import threading

    started = threading.Event()

    def waits(dest_, pw, *, should_stop, **_k):
        Path(dest_).mkdir(parents=True, exist_ok=True)
        started.set()
        while not should_stop():
            time.sleep(0.005)
        raise VolumeStopped("stopped")

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "one"), "pw", _backup_fn=waits)
    assert started.wait(5)
    mgr.cancel()
    assert _finish(mgr)["state"] == "cancelled"
    started.clear()
    mgr.start_backup(str(tmp_path / "two"), "pw", _backup_fn=waits)
    assert started.wait(5)
    mgr.pause()
    assert _finish(mgr)["state"] == "paused"
    assert [e["outcome"] for e in _events("run_export")] == ["cancelled", "paused"]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_an_exit_no_branch_names_still_closes_the_run_as_ended_without_an_outcome(journal, tmp_path):
    """A BaseException (no ``except Exception`` takes it) ends the worker thread; the finally net is what writes the run's end."""

    class Quit(BaseException):
        pass

    def quits(dest_, pw, **_k):
        raise Quit(f"asked to leave {MARKER}")

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "d"), "pw", _backup_fn=quits)
    thread = mgr._thread
    assert thread is not None
    thread.join(10)
    event = _only("run_export")
    assert event["outcome"] == "ended-without-a-recorded-outcome" and event["open"] is False
    _nothing_secret_anywhere(journal, MARKER, "asked to leave")


def test_a_backup_start_with_no_passphrase_is_a_refusal_with_its_sentence(journal, tmp_path):
    mgr = VolumeBackupManager()
    with pytest.raises(ValueError):
        mgr.start_backup(str(tmp_path / "d"), "", _backup_fn=_ok_backup)
    event = _only("run_export")
    assert (event["outcome"], event["ran"], event["reason"]) == ("refused", False, se.RUN_REFUSALS["no-passphrase"])
    assert not (tmp_path / "d").exists(), "the refusal came before the destination was touched"


def test_a_destination_that_cannot_be_made_is_a_refusal_with_the_class_and_not_the_path(journal, tmp_path):
    blocker = tmp_path / f"a-file-{MARKER}"
    blocker.write_text("not a folder", encoding="utf-8")
    mgr = VolumeBackupManager()
    with pytest.raises(ValueError):
        mgr.start_backup(str(blocker / "inside"), "pw", _backup_fn=_ok_backup)
    event = _only("run_export")
    assert event["reason"] == se.RUN_REFUSALS["destination-unusable"]
    assert event["error"] in {"NotADirectoryError", "FileExistsError", "OSError"}
    _nothing_secret_anywhere(journal, MARKER, "a-file-", str(tmp_path))


def test_a_destination_that_is_a_file_is_refused_too(journal, tmp_path):
    target = tmp_path / "plain-file"
    target.write_text("x", encoding="utf-8")
    mgr = VolumeBackupManager()
    with pytest.raises(ValueError):
        mgr.start_backup(str(target), "pw", _backup_fn=_ok_backup)
    assert _only("run_export")["outcome"] == "refused"


def test_a_source_that_is_not_a_folder_is_a_refusal_for_a_restore_and_for_a_verify(journal, tmp_path):
    missing = tmp_path / f"missing-{MARKER}"
    mgr = VolumeBackupManager()
    with pytest.raises(ValueError):
        mgr.start_restore(str(missing), "pw")
    with pytest.raises(ValueError):
        mgr.start_verify(str(missing), "pw")
    for kind in ("run_import", "run_verify"):
        event = _only(kind)
        assert (event["outcome"], event["reason"]) == ("refused", se.RUN_REFUSALS["not-a-folder"]), kind
    _nothing_secret_anywhere(journal, MARKER, "missing-", str(tmp_path))


def test_a_start_while_a_job_runs_is_a_refusal_of_the_kind_that_asked(journal, tmp_path):
    import threading

    release, started = threading.Event(), threading.Event()

    def holds(dest_, pw, **_k):
        started.set()
        release.wait(10)
        return {"volumes": 1, "envelope": {}}

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "d"), "pw", verify_after_write=False, _backup_fn=holds)
    assert started.wait(5)
    try:
        with pytest.raises(RuntimeError):
            mgr.start_backup(str(tmp_path / "e"), "pw", _backup_fn=_ok_backup)
        with pytest.raises(RuntimeError):
            mgr.start_restore(str(tmp_path), "pw")
        with pytest.raises(RuntimeError):
            mgr.start_verify(str(tmp_path), "pw")
    finally:
        release.set()
        _finish(mgr)
    refused = {k: [e for e in _events(k) if e["outcome"] == "refused"] for k in se.RUN_KINDS.values()}
    for kind, events in refused.items():
        assert len(events) == 1 and events[0]["reason"] == se.RUN_REFUSALS["already-running"], kind
    assert [e["outcome"] for e in _events("run_export")].count("ok") == 1, "the run that held the job still ended ok"


def test_a_restore_that_is_done_ends_ok(journal, tmp_path):
    mgr = VolumeBackupManager()
    mgr.start_restore(str(tmp_path), "pw", _restore_fn=lambda src, pw: {"articles_merged": 5})
    assert _finish(mgr)["state"] == "done"
    assert _only("run_import")["outcome"] == "ok"


@pytest.mark.parametrize(
    ("raises", "outcome", "error", "reason"),
    [
        ("refused", "refused", "RestoreRefused", "barrier"),
        ("aborted", "stopped-by-operator", "RestoreAborted", None),
        ("other", "error", "ValueError", None),
    ],
)
def test_each_end_of_a_restore_has_its_own_outcome_and_never_its_text(journal, tmp_path, raises, outcome, error, reason):
    from src.backup.merge import RestoreAborted, RestoreRefused

    def fn(src, pw):
        text = f"holder {MARKER} at {src}"
        raise {"refused": RestoreRefused, "aborted": RestoreAborted, "other": ValueError}[raises](text)

    mgr = VolumeBackupManager()
    mgr.start_restore(str(tmp_path), "pw", _restore_fn=fn)
    _finish(mgr)
    event = _only("run_import")
    assert (event["outcome"], event["error"]) == (outcome, error)
    assert event.get("reason") == (se.RUN_REFUSALS[reason] if reason else None)
    _nothing_secret_anywhere(journal, MARKER, "holder", str(tmp_path))


def test_an_artifact_already_merged_is_recorded_as_skipped_and_reads_no_drive(journal, tmp_path, monkeypatch):
    import src.backup.merge as merge

    monkeypatch.setattr(merge, "artifact_source_digest", lambda _src: "abc123")
    monkeypatch.setattr(merge, "find_completed_import", lambda _digest: {"batch_id": 7, "imported_at": "2026-10-01"})
    calls: list[str] = []
    monkeypatch.setattr(se, "free_bytes_of", lambda *_a, **_k: calls.append("read") or 1)
    mgr = VolumeBackupManager()
    mgr.start_restore(str(tmp_path), "pw")
    assert _finish(mgr)["state"] == "done"
    event = _only("run_import")
    assert event["outcome"] == "skipped-already-merged" and "data_free_bytes" not in event
    assert calls == [], "a restore that writes nothing does not stat the data folder"


def test_a_restore_that_goes_on_reads_the_free_bytes_of_the_data_folder_and_a_failure_keeps_them(journal, tmp_path, monkeypatch):
    import src.backup.merge as merge

    monkeypatch.setattr(merge, "artifact_source_digest", lambda _src: None)
    monkeypatch.setattr(merge, "find_completed_import", lambda _digest: None)

    def refuses() -> None:
        raise MemoryError(f"short of memory {MARKER}")

    monkeypatch.setattr(merge, "check_memory_before_staging", refuses)
    mgr = VolumeBackupManager()
    mgr.start_restore(str(tmp_path), "pw")
    assert _finish(mgr)["state"] == "error"
    event = _only("run_import")
    assert (event["outcome"], event["error"]) == ("error", "MemoryError")
    assert isinstance(event["data_free_bytes"], int) and event["data_free_bytes"] > 0
    assert "dest_free_bytes" not in event
    _nothing_secret_anywhere(journal, MARKER, "short of memory")


def test_a_verify_that_finds_a_bad_set_is_a_run_that_ended_ok_with_the_set_marked_not_ok(journal, tmp_path):
    mgr = VolumeBackupManager()
    mgr.start_verify(str(tmp_path), None, _verify_fn=lambda src, pw: {"ok": False, "problems": [f"bad volume {MARKER}"]})
    assert _finish(mgr)["state"] == "done"
    event = _only("run_verify")
    assert (event["outcome"], event["set_ok"]) == ("ok", False)
    _nothing_secret_anywhere(journal, MARKER, "bad volume")


def test_a_verify_that_cannot_run_ends_in_error_with_the_class(journal, tmp_path):
    def fails(src, pw):
        raise OSError(f"cannot read {src} {MARKER}")

    mgr = VolumeBackupManager()
    mgr.start_verify(str(tmp_path), "pw", _verify_fn=fails)
    assert _finish(mgr)["state"] == "error"
    event = _only("run_verify")
    assert (event["outcome"], event["error"]) == ("error", "OSError") and "set_ok" not in event
    _nothing_secret_anywhere(journal, MARKER, "cannot read", str(tmp_path))


def test_a_backup_summary_that_cannot_be_written_is_named_on_the_run_that_ended_ok(journal, tmp_path, monkeypatch):
    dated = tmp_path / f"202610161200_{export_folder.BACKUP_FOLDER_TOKEN}_{export_folder.BACKUP_FOLDER_SUFFIX}"
    assert export_folder.is_export_folder_name(dated.name)

    def cannot(_d, _facts):
        raise PermissionError(f"read-only drive {MARKER}")

    monkeypatch.setattr(export_summary, "export_facts", lambda *_a, **_k: {})
    monkeypatch.setattr(export_summary, "write_backup_summary", cannot)
    mgr = VolumeBackupManager()
    mgr.start_backup(str(dated), "pw", verify_after_write=False, _backup_fn=_ok_backup)
    assert _finish(mgr)["state"] == "done", "a summary that cannot be written is not a failed backup"
    event = _only("run_export")
    assert (event["outcome"], event["summary_error"]) == ("ok", "PermissionError")
    _nothing_secret_anywhere(journal, MARKER, "read-only drive")


def test_a_summary_failure_with_no_backup_in_flight_records_nothing(journal, tmp_path, monkeypatch):
    """The folder backup also writes a summary and opens no run in this journal."""
    dated = tmp_path / f"202610161200_{export_folder.BACKUP_FOLDER_TOKEN}_{export_folder.BACKUP_FOLDER_SUFFIX}"
    monkeypatch.setattr(export_summary, "export_facts", lambda *_a, **_k: {})
    monkeypatch.setattr(export_summary, "write_backup_summary", lambda *_a: (_ for _ in ()).throw(OSError("full")))
    assert export_summary.write_summary_for_export_job(dated, volume_status=None) is None
    assert _events("run_export") == []


# --------------------------------------------------------------------------- #
#  3. The sources: the hooks hand over a class name and a key of the table, by construction
# --------------------------------------------------------------------------- #
def _calls(path: str, names: set[str]) -> list[ast.Call]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in names
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "storage_events"
    ]


def _is_type_name_of_a_name(node: ast.expr) -> bool:
    """``type(x).__name__`` with ``x`` a plain name."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "type"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Name)
    )


def test_every_hook_hands_over_a_class_name_a_table_key_and_a_named_fact():
    allowed_facts = set(se._RUN_NUMBERS) | set(se._RUN_FLAGS) | set(se._RUN_CLASSES) | {"verify"}
    seen = 0
    for path in ("src/backup/volume_job.py", "src/backup/export_summary.py"):
        for call in _calls(path, {"run_started", "run_facts", "run_ended", "run_refused", "run_part", "run_free_space"}):
            seen += 1
            where = f"{path}:{call.lineno}"
            name = call.func.attr  # type: ignore[attr-defined]
            if name in ("run_ended", "run_refused"):
                outcome_arg = call.args[1] if name == "run_ended" else None
                if outcome_arg is not None:
                    assert isinstance(outcome_arg, ast.Constant) and outcome_arg.value in se.RUN_OUTCOMES, where
                if name == "run_refused":
                    first = call.args[0]  # a kind, or ``what`` in the one helper every start passes through
                    assert (isinstance(first, ast.Constant) and first.value in se.RUN_KINDS) or (isinstance(first, ast.Name) and first.id == "what"), where
                    assert isinstance(call.args[1], ast.Constant) and call.args[1].value in se.RUN_REFUSALS, where
            for kw in call.keywords:
                assert kw.arg is not None, f"{where}: a ** mapping can carry anything"
                if kw.arg in ("failure", "summary_error"):
                    assert _is_type_name_of_a_name(kw.value), f"{where}: {kw.arg} must be type(exc).__name__, never a message"
                elif kw.arg == "reason":
                    assert isinstance(kw.value, ast.Constant) and kw.value.value in se.RUN_REFUSALS, where
                else:
                    assert kw.arg in allowed_facts, f"{where}: {kw.arg} is not a fact a run may carry"
    assert seen >= 25, "the scan found the hooks"


def test_each_worker_closes_its_run_in_a_finally_net_and_every_start_names_its_refusal():
    tree = ast.parse((ROOT / "src/backup/volume_job.py").read_text(encoding="utf-8"))
    workers = {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name in ("_run_backup", "_run_restore", "_run_verify")}
    assert set(workers) == {"_run_backup", "_run_restore", "_run_verify"}
    for name, fn in workers.items():
        nets = [
            c
            for t in ast.walk(fn)
            if isinstance(t, ast.Try)
            for stmt in t.finalbody
            for c in ast.walk(stmt)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "run_ended"
            and len(c.args) == 2 and isinstance(c.args[1], ast.Constant) and c.args[1].value == "ended-without-a-recorded-outcome"
        ]
        assert len(nets) == 1, f"{name} must close its run in a finally"
    for name in ("start_backup", "start_restore", "start_verify"):
        fn = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == name)
        raises = [n for n in ast.walk(fn) if isinstance(n, ast.Raise)]
        refusals = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "run_refused"]
        assert raises and len(refusals) >= len(raises), f"{name}: every raise of a refusal is preceded by a journal record"
    reject = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "_reap_or_reject")
    assert any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "run_refused" for c in ast.walk(reject))


def test_the_member_says_what_the_run_kinds_are():
    for kind in se.RUN_KINDS.values():
        assert kind in se._METHOD, kind
    assert "run journal's 'export'" in se._METHOD and "dest_free_bytes" in se._METHOD and "data_free_bytes" in se._METHOD


def test_the_kinds_are_the_run_journals_names_and_the_caps_are_ten_each():
    assert se.RUN_KINDS == {"export": "run_export", "import": "run_import", "verify": "run_verify"}
    assert all(se.KEEP[kind] == 10 for kind in se.RUN_KINDS.values())
    assert vj.storage_events is se, "the manager records into the journal this module reads"
