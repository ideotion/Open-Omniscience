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
    se.run_facts(note, summary_error=value)
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


def test_run_facts_reach_only_the_run_of_their_own_note(journal):
    older = se.run_started("export")
    newest = se.run_started("export")
    other = se.run_started("import")
    se.run_facts(older, summary_error="OSError")
    se.run_ended(newest, "ok")
    se.run_ended(older, "ok")
    se.run_ended(other, "ok")
    by_start = _events("run_export")
    assert [("summary_error" in e) for e in by_start] == [True, False], "the older run's note reaches the older run, not the newest open one"
    assert "summary_error" not in _only("run_import")


def test_run_facts_on_a_run_that_ended_do_nothing(journal):
    note = se.run_started("export")
    se.run_ended(note, "ok")
    se.run_facts(note, summary_error="OSError")
    assert "summary_error" not in _only("run_export"), "a closed run is not reopened by a late step"


def test_free_bytes_of_stats_the_path_as_given_and_never_reports_another_volume(journal, tmp_path):
    free = se.free_bytes_of(tmp_path)
    assert isinstance(free, int) and free > 0
    assert se.free_bytes_of(tmp_path / "not" / "made" / "yet") is None, "a path that is not there is absent, not its parent's volume"


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
    member = se.diagnostics_member(10**9)
    assert member["file"]["internal_failures"] == 0, "a volume that cannot be read is an absent field, not a fault of the journal"
    _nothing_secret_anywhere(journal, MARKER)


def test_a_failure_that_is_not_an_os_error_is_the_journals_own_and_is_counted(journal, tmp_path, monkeypatch):
    def broken(_path):
        raise ValueError(f"not a path {MARKER}")

    monkeypatch.setattr(se.shutil, "disk_usage", broken)
    assert se.free_bytes_of(tmp_path) is None
    member = se.diagnostics_member(10**9)
    assert member["file"]["internal_failures"] == 1 and "ValueError" in member["file"]["last_internal_failure"]
    assert MARKER not in json.dumps(member), "counted by class, never by its message"


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


def test_the_backup_reads_the_free_space_after_its_run_is_written_open(journal, tmp_path, monkeypatch):
    """The order the docstrings promise, at the worker's own call site: a stat that hangs on a dead mount must find the run already open."""
    seen: list[list[dict]] = []
    real = se.shutil.disk_usage
    dest = tmp_path / "dest"

    def look(path):
        if Path(path) == dest:  # the run journal's own hardware profile also stats the data folder, before the run is opened
            seen.append([dict(e) for e in _events("run_export")])
        return real(path)

    monkeypatch.setattr(se.shutil, "disk_usage", look)
    mgr = VolumeBackupManager()
    mgr.start_backup(str(dest), "pw", verify_after_write=False, _backup_fn=_ok_backup)
    assert _finish(mgr)["state"] == "done"
    assert seen, "the worker read the free space"
    assert len(seen[0]) == 1 and seen[0][0]["open"] is True, "the run was already written open when the stat ran"


def test_a_backup_that_fails_leaves_the_class_and_no_word_of_the_exception_or_the_path(journal, tmp_path):
    dest = tmp_path / f"dest4711-{MARKER}"

    def failing(dest_, pw, **_k):
        raise RuntimeError(f"disk exploded at {dest_} while writing {pw}: {MARKER}")

    mgr = VolumeBackupManager()
    mgr.start_backup(str(dest), "the-typed-passphrase", _backup_fn=failing)
    assert _finish(mgr)["state"] == "error"
    event = _only("run_export")
    assert event["outcome"] == "error" and event["error"] == "RuntimeError" and event["seconds"] >= 0
    _nothing_secret_anywhere(journal, MARKER, "the-typed-passphrase", "disk exploded", str(tmp_path), "dest4711-")


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
    event = _only("run_export")
    assert (event["outcome"], event["reason"]) == ("refused", se.RUN_REFUSALS["destination-unusable"]), "mkdir refuses a file before is_dir is asked"


def test_a_destination_that_stops_being_a_folder_after_it_was_made_is_the_not_a_folder_refusal(journal, tmp_path, monkeypatch):
    monkeypatch.setattr(vj.Path, "is_dir", lambda _self: False)
    mgr = VolumeBackupManager()
    with pytest.raises(ValueError):
        mgr.start_backup(str(tmp_path / "gone-before-the-check"), "pw", _backup_fn=_ok_backup)
    event = _only("run_export")
    assert (event["outcome"], event["reason"]) == ("refused", se.RUN_REFUSALS["not-a-folder"])


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
        assert events[0]["via"] == "volume-set", f"{kind}: a refusal says which way in it was"
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


def test_a_real_restore_that_merges_ends_ok_with_its_figures_and_not_as_the_net_would(journal, tmp_path, monkeypatch):
    """The path every good restore takes (the injected ``_restore_fn`` skips it): if its ``ok`` record is lost the finally net would
    write "ended-without-a-recorded-outcome" for every restore that worked."""
    import src.backup.artifact as artifact
    import src.backup.merge as merge
    import src.scheduler.runner as runner

    class _Staged:
        file_members = ()
        staging_dir = tmp_path / "staging"

    monkeypatch.setattr(merge, "artifact_source_digest", lambda _src: None)
    monkeypatch.setattr(merge, "find_completed_import", lambda _digest: None)
    monkeypatch.setattr(merge, "check_memory_before_staging", lambda: None)
    monkeypatch.setattr(merge, "run_restore", lambda _staged, **_k: {"articles_merged": 12, "reindexed": 7, "batch_id": 3})
    monkeypatch.setattr(artifact, "read_volume_backup", lambda *_a, **_k: _Staged())
    monkeypatch.setattr(artifact, "cleanup_staging", lambda _staged: None)
    monkeypatch.setattr(runner, "pause_for_exclusive_operation", lambda: False)
    monkeypatch.setattr(runner, "resume_after_exclusive_operation", lambda _was: None)
    monkeypatch.setattr(vj, "defer_reindex", lambda: False)
    mgr = VolumeBackupManager()
    mgr.start_restore(str(tmp_path), "pw")
    assert _finish(mgr)["state"] == "done"
    event = _only("run_import")
    assert (event["outcome"], event["articles_merged"], event["reindexed"]) == ("ok", 12, 7)
    assert isinstance(event["data_free_bytes"], int) and event["open"] is False


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


def test_a_summary_failure_with_no_note_lands_on_no_run_even_when_another_backup_is_open(journal, tmp_path, monkeypatch):
    """The folder backup also writes a summary and has no run in this journal; a volume backup that happens to be open is not its run."""
    dated = tmp_path / f"202610161200_{export_folder.BACKUP_FOLDER_TOKEN}_{export_folder.BACKUP_FOLDER_SUFFIX}"
    monkeypatch.setattr(export_summary, "export_facts", lambda *_a, **_k: {})
    monkeypatch.setattr(export_summary, "write_backup_summary", lambda *_a: (_ for _ in ()).throw(OSError("full")))
    unrelated = se.run_started("export")
    assert export_summary.write_summary_for_export_job(dated, volume_status=None) is None
    se.run_ended(unrelated, "ok")
    assert "summary_error" not in _only("run_export"), "a summary that failed for someone else's folder is not this run's fact"


def test_a_summary_failure_lands_on_the_run_whose_note_was_handed_over_and_on_no_other(journal, tmp_path, monkeypatch):
    dated = tmp_path / f"202610161200_{export_folder.BACKUP_FOLDER_TOKEN}_{export_folder.BACKUP_FOLDER_SUFFIX}"
    monkeypatch.setattr(export_summary, "export_facts", lambda *_a, **_k: {})
    monkeypatch.setattr(export_summary, "write_backup_summary", lambda *_a: (_ for _ in ()).throw(OSError("full")))
    mine = se.run_started("export")
    newer = se.run_started("export")
    assert export_summary.write_summary_for_export_job(dated, volume_status=None, run_note=mine) is None
    se.run_ended(newer, "ok")
    se.run_ended(mine, "ok")
    assert [("summary_error" in e) for e in _events("run_export")] == [True, False]


def test_a_burst_of_refused_starts_does_not_push_the_run_in_flight_out_of_the_journal(journal):
    running = se.run_started("export")
    for _ in range(se.KEEP["run_export"] + 3):
        se.run_refused("export", "already-running")
    se.run_ended(running, "ok")
    events = _events("run_export")
    assert [e for e in events if e.get("outcome") == "ok"], "the run that was in flight still has its end recorded"
    assert se.diagnostics_member(10**9)["kinds"]["run_export"]["total"] == 1 + se.KEEP["run_export"] + 3, "total counts every record"
    assert len(events) == se.KEEP["run_export"]


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


def _constants_of(node: ast.expr) -> set[str] | None:
    """The string constants an outcome argument can be: one constant, or a conditional of constants; ``None`` for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        a, b = _constants_of(node.body), _constants_of(node.orelse)
        return None if a is None or b is None else a | b
    return None


def test_every_hook_hands_over_a_class_name_a_table_key_and_a_named_fact():
    allowed_facts = set(se._RUN_NUMBERS) | set(se._RUN_FLAGS) | set(se._RUN_CLASSES) | {"verify"}
    seen: dict[str, int] = {}
    for path in (
        "src/backup/volume_job.py", "src/backup/export_summary.py", "src/api/backup_v2.py", "src/ingest/import_job.py",
        "src/backup/folder_backup.py",
    ):
        for call in _calls(path, {"run_started", "run_facts", "run_ended", "run_refused", "run_free_space", "run_path_checked",
                                  "run_refusals_net", "run_open"}):
            seen[path] = seen.get(path, 0) + 1
            where = f"{path}:{call.lineno}"
            name = call.func.attr  # type: ignore[attr-defined]
            if name in ("run_path_checked", "run_refusals_net", "run_open"):
                first = call.args[0]  # a kind, or ``what`` in the one helper every folder start passes through, or the folder's kind of its mode
                assert (
                    (isinstance(first, ast.Constant) and first.value in se.RUN_KINDS)
                    or (isinstance(first, ast.Name) and first.id == "what")
                    or (isinstance(first, ast.Call) and ast.unparse(first) == "_RUN_OF.get(mode, '')")
                ), where
            if name in ("run_ended", "run_refused"):
                outcome_arg = call.args[1] if name == "run_ended" else None
                if outcome_arg is not None:
                    outcomes = _constants_of(outcome_arg)
                    assert outcomes is not None and outcomes <= se.RUN_OUTCOMES, where
                if name == "run_refused":
                    first = call.args[0]  # a kind, or ``what`` in the one helper every start passes through
                    assert (isinstance(first, ast.Constant) and first.value in se.RUN_KINDS) or (isinstance(first, ast.Name) and first.id == "what"), where
                    keys = _constants_of(call.args[1])  # one key, or a conditional of keys (the no-space / free-space-unreadable pair)
                    assert keys is not None and keys <= set(se.RUN_REFUSALS), where
            for kw in call.keywords:
                assert kw.arg is not None, f"{where}: a ** mapping can carry anything"
                if kw.arg in ("failure", "summary_error"):
                    assert _is_type_name_of_a_name(kw.value), f"{where}: {kw.arg} must be type(exc).__name__, never a message"
                elif kw.arg == "reason":
                    assert isinstance(kw.value, ast.Constant) and kw.value.value in se.RUN_REFUSALS, where
                elif kw.arg == "via":
                    # a key of the fixed table, written out at the call: no local, no expression
                    assert isinstance(kw.value, ast.Constant) and kw.value.value in se.RUN_VIA, f"{where}: via must be a key of the table"
                elif kw.arg == "refused_as":
                    # the classes a net may name, written at the header or the one constant of the table; never a name taken from a variable
                    assert (
                        ast.unparse(kw.value) in ("storage_events.NOT_A_FOLDER", "((HTTPException, 'not-a-file'),)")
                        or ast.unparse(kw.value) == "storage_events.NOT_A_FOLDER if mode in ('restore', 'verify') else ()"
                    ), f"{where}: refused_as must be the one table or the one pair written out"
                else:
                    assert kw.arg in allowed_facts, f"{where}: {kw.arg} is not a fact a run may carry"
    # Per file, so a file whose hooks were deleted cannot hide behind the others' count. EXACT at the time of writing (27, 1, 6, 8 and 17):
    # a hook added or removed here moves the number in the same change, which is the point of a ratchet; a floor with slack let one
    # missing hook through.
    counts = {"src/backup/volume_job.py": 27, "src/backup/export_summary.py": 1, "src/api/backup_v2.py": 6, "src/ingest/import_job.py": 8,
              "src/backup/folder_backup.py": 17}
    for path, expected in counts.items():
        assert seen.get(path, 0) == expected, f"the scan found {seen.get(path, 0)} hooks in {path}, expected {expected}"


#: The six statements that examine a path a request handed in, as (file, the statement's source, the column it starts at). The column is
#: where the statement stood before any record was written: a record that wraps one moves it one level in, and code scanning reports a
#: finding on a pull request for every line the pull request changes, so a check that was already on the base branch comes back as
#: a new finding of the pull request (live, 2026-10-16: six alerts on a head whose check lines hashed exactly as the base's).
_PATH_CHECKS = (
    ("src/backup/volume_job.py", "if not destp.is_dir():", 12),
    ("src/backup/volume_job.py", "if not srcp.is_dir():", 12),
    ("src/api/backup_v2.py", "if not p.is_file():", 4),
    ("src/api/backup_v2.py", "data = p.read_bytes()", 12),
    ("src/backup/folder_backup.py", "if not destp.is_dir():", 16),
)


def test_the_path_checks_stay_where_they_were_written_and_nothing_wraps_or_enters_them():
    """The records are written by a NET round the header of the start (and a decorator on the legacy restore), never round the statement or
    inside its branch: each check stands at its original column, its branch is the raise and nothing else, and the handler after a read
    is the raise and nothing else. (An ``if`` that gained a record, or a ``with`` that wrapped it, fails here.)"""
    seen = 0
    for path, source, column in _PATH_CHECKS:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.Assign)) or ast.unparse(node).split("\n")[0] != source:
                continue
            seen += 1
            assert node.col_offset == column, f"{path}:{node.lineno}: {source} moved from column {column} to {node.col_offset}"
            if isinstance(node, ast.If):
                calls = [
                    c.func.attr
                    for stmt in node.body
                    for c in ast.walk(stmt)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)
                    and c.func.value.id == "storage_events"
                ]
                assert calls == [], f"{path}:{node.lineno}: a record inside the branch of the check: {calls}"
    assert seen == 6, f"expected the 6 path checks, found {seen}"
    legacy = ast.parse((ROOT / "src/api/backup_v2.py").read_text(encoding="utf-8"))
    (read,) = [
        t for t in ast.walk(legacy) if isinstance(t, ast.Try) and any(ast.unparse(b).startswith("data = p.read_bytes()") for b in t.body)
    ]
    assert [type(b).__name__ for b in read.body] == ["Assign"], "nothing but the read itself in the try"
    assert len(read.handlers) == 1 and [type(b).__name__ for b in read.handlers[0].body] == ["Raise"], "the handler of the read is its raise"


def test_the_net_is_on_the_header_of_every_start_and_on_the_legacy_restore():
    """Where the records of the six path checks come from. A start loses its refusal record when the net leaves its ``with`` header."""
    tree = ast.parse((ROOT / "src/backup/volume_job.py").read_text(encoding="utf-8"))
    for name, kind in (("start_backup", "export"), ("start_restore", "import"), ("start_verify", "verify")):
        fn = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == name)
        header = next(n for n in ast.walk(fn) if isinstance(n, ast.With))
        text = [ast.unparse(item.context_expr) for item in header.items]
        assert text == [
            "self._lock",
            f"storage_events.run_refusals_net('{kind}', via='volume-set', refused_as=storage_events.NOT_A_FOLDER)",
        ], (name, text)
    folder = ast.parse((ROOT / "src/backup/folder_backup.py").read_text(encoding="utf-8"))
    start = next(f for f in ast.walk(folder) if isinstance(f, ast.FunctionDef) and f.name == "start")
    header = next(n for n in ast.walk(start) if isinstance(n, ast.With))
    assert [ast.unparse(item.context_expr) for item in header.items] == [
        "self._lock",
        "storage_events.run_refusals_net(_RUN_OF.get(mode, ''), via='folder', "
        "refused_as=storage_events.NOT_A_FOLDER if mode in ('restore', 'verify') else ())",
    ]
    legacy = ast.parse((ROOT / "src/api/backup_v2.py").read_text(encoding="utf-8"))
    fn = next(f for f in ast.walk(legacy) if isinstance(f, ast.FunctionDef) and f.name == "restore_legacy_path")
    assert [ast.unparse(d) for d in fn.decorator_list] == [
        "storage_events.run_refusals_net('import', via='single-file', refused_as=((HTTPException, 'not-a-file'),))"
    ]
    opened = [n for n in ast.walk(fn) if isinstance(n, ast.With) and any("run_open" in ast.unparse(i.context_expr) for i in n.items)]
    assert len(opened) == 1, "the legacy restore's run is opened by one `with`, on the header that already converted its errors"


def test_no_file_that_carries_a_run_hook_writes_the_journal_by_hand():
    """A raw ``record``/``update``/``end``/``note_*`` call in these files would bypass ``_run_fields``' allowlist at the call site; the
    scan above reads only the ``run_*`` builders, so this one says there is nothing else to read."""
    for path in (
        "src/backup/volume_job.py", "src/backup/export_summary.py", "src/api/backup_v2.py", "src/ingest/import_job.py",
        "src/backup/folder_backup.py",
    ):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        raw = [
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "storage_events" and not n.func.attr.startswith("run_")
        ]
        assert raw == [], f"{path} calls storage_events.{raw} directly"


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
        _assert_each_raise_follows_a_refusal(fn)
    reject = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "_reap_or_reject")
    _assert_each_raise_follows_a_refusal(reject)


def _is_refusal_statement(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Attribute)
        and stmt.value.func.attr == "run_refused"
    )


def _raised_type(stmt: ast.Raise) -> str | None:
    """The name of the exception a ``raise`` makes: ``raise ValueError(...)`` and ``raise ValueError`` both say ``ValueError``."""
    exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
    return exc.id if isinstance(exc, ast.Name) else None


def _net_call(fn: ast.FunctionDef, stmt: ast.Raise, parent: dict[ast.AST, ast.AST]) -> ast.Call | None:
    """The ``run_refusals_net(...)`` call that covers ``stmt``: the one on a ``with`` header round it, else the function's decorator."""
    up: ast.AST | None = parent.get(stmt)
    while up is not None and up is not fn:
        if isinstance(up, ast.With):
            for item in up.items:
                if isinstance(item.context_expr, ast.Call) and "run_refusals_net" in ast.unparse(item.context_expr.func):
                    return item.context_expr
        up = parent.get(up)
    return next((d for d in fn.decorator_list if isinstance(d, ast.Call) and "run_refusals_net" in ast.unparse(d.func)), None)


def _classes_the_net_names(call: ast.Call) -> set[str]:
    """The exception classes ``refused_as`` of a ``run_refusals_net`` call names: the ones written in it, and those of ``NOT_A_FOLDER``."""
    kw = next((k.value for k in call.keywords if k.arg == "refused_as"), None)
    if kw is None:
        return set()
    names = {n.id for n in ast.walk(kw) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(kw) if isinstance(n, ast.Attribute)}
    if "NOT_A_FOLDER" in names:
        names |= {cls.__name__ for cls, _key in se.NOT_A_FOLDER}
    return names


def _is_a_path_check(test: ast.expr) -> bool:
    """``not <name>.is_dir()`` or ``not <name>.is_file()``: the one statement of a start that looks at a path."""
    return (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Call)
        and isinstance(test.operand.func, ast.Attribute)
        and test.operand.func.attr in ("is_dir", "is_file")
        and isinstance(test.operand.func.value, ast.Name)
    )


def raise_is_recorded_by_the_net(fn: ast.FunctionDef, stmt: ast.Raise) -> bool:
    """The ``raise`` is a refusal the net round the start records: it is the end of the branch of a path check (``if not x.is_dir():``)
    AND the class it raises is one the net was handed (``refused_as``). The net reads the CLASS, so a ``raise`` of that class anywhere
    else under the net would be recorded as a missing folder whatever it was; this is the only place the tests let that be true. A raise
    the net cannot name is recorded by a call before it or not at all; the net is not a way to leave a refusal unrecorded."""
    parent = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
    branch = parent.get(stmt)
    if not (isinstance(branch, ast.If) and branch.body[-1] is stmt and _is_a_path_check(branch.test)):
        return False
    call = _net_call(fn, stmt, parent)
    return call is not None and _raised_type(stmt) in _classes_the_net_names(call)


_NET_CASES = (
    # (what it is, the source of one function, whether the rule lets the net stand for the ``raise``)
    ("the check's own raise, the net on a header",
     "def start(self, p):\n    with self._lock, storage_events.run_refusals_net('export', refused_as=storage_events.NOT_A_FOLDER):\n"
     "        if not p.is_dir():\n            raise ValueError('x')\n", True),
    ("the check's own raise, the net a decorator and the class written out",
     "@storage_events.run_refusals_net('import', refused_as=((HTTPException, 'not-a-file'),))\n"
     "def start(p):\n    if not p.is_file():\n        raise HTTPException(status_code=400, detail='x')\n", True),
    ("a raise of the class that is not the check's own",
     "def start(self, p):\n    with self._lock, storage_events.run_refusals_net('export', refused_as=storage_events.NOT_A_FOLDER):\n"
     "        if self.busy:\n            raise ValueError('x')\n", False),
    ("a raise after a check of something that is not a path",
     "def start(self, p):\n    with self._lock, storage_events.run_refusals_net('export', refused_as=storage_events.NOT_A_FOLDER):\n"
     "        if not p.exists():\n            raise ValueError('x')\n", False),
    ("a class the net was not handed",
     "def start(self, p):\n    with self._lock, storage_events.run_refusals_net('export', refused_as=storage_events.NOT_A_FOLDER):\n"
     "        if not p.is_dir():\n            raise RuntimeError('x')\n", False),
    ("a net with nothing handed to it",
     "def start(self, p):\n    with self._lock, storage_events.run_refusals_net('export'):\n"
     "        if not p.is_dir():\n            raise ValueError('x')\n", False),
    ("no net at all",
     "def start(self, p):\n    with self._lock:\n        if not p.is_dir():\n            raise ValueError('x')\n", False),
    ("a raise before the check's branch ends",
     "def start(self, p):\n    with self._lock, storage_events.run_refusals_net('export', refused_as=storage_events.NOT_A_FOLDER):\n"
     "        if not p.is_dir():\n            raise ValueError('x')\n            self.done = True\n", False),
)


@pytest.mark.parametrize(("what", "source", "expected"), _NET_CASES, ids=[c[0] for c in _NET_CASES])
def test_the_net_stands_for_a_raise_only_where_it_is_the_path_checks_own(what, source, expected):
    """The net reads a CLASS, so which ``raise`` of the class it stands for is decided here, by the shape of the code. RED WITHOUT any
    one of the conditions: the case that breaks it is the line of this table that turns."""
    fn = next(f for f in ast.walk(ast.parse(source)) if isinstance(f, ast.FunctionDef))
    raises = [n for n in ast.walk(fn) if isinstance(n, ast.Raise)]
    assert len(raises) == 1
    assert raise_is_recorded_by_the_net(fn, raises[0]) is expected, what


def _assert_each_raise_follows_a_refusal(fn: ast.FunctionDef) -> None:
    """Every ``raise`` is preceded, in the SAME block, by a ``run_refused`` statement, or is recorded by a wrapper
    (:func:`raise_is_recorded_by_the_net`): a record moved after its raise is dead code."""
    raises = 0
    for node in ast.walk(fn):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for i, stmt in enumerate(block):
                if isinstance(stmt, ast.Raise):
                    raises += 1
                    recorded = any(_is_refusal_statement(earlier) for earlier in block[:i]) or raise_is_recorded_by_the_net(fn, stmt)
                    assert recorded, f"{fn.name}:{stmt.lineno}: a raise with no refusal record before it"
    assert raises, f"{fn.name} raises nothing: the pin found nothing to guard"


def test_the_member_says_what_the_run_kinds_are():
    for kind in se.RUN_KINDS.values():
        assert kind in se._METHOD, kind
    assert "dest_free_bytes" in se._METHOD and "data_free_bytes" in se._METHOD
    assert "newsletter filter" in se._METHOD, "an outcome that differs from the run journal's is said so"


def test_the_kinds_are_the_run_journals_names_and_the_caps_are_ten_each():
    assert se.RUN_KINDS == {"export": "run_export", "import": "run_import", "verify": "run_verify"}
    assert all(se.KEEP[kind] == 10 for kind in se.RUN_KINDS.values())
    assert vj.storage_events is se, "the manager records into the journal this module reads"


# --------------------------------------------------------------------------- #
#  4. A start that cannot even look at its path
# --------------------------------------------------------------------------- #
def _unreadable(monkeypatch, method: str, needle: str = "UNREADABLE") -> None:
    """Make ``Path.<method>`` raise what a dropped mount or a too-long name raises (ENAMETOOLONG) for a path that holds ``needle``;
    every other path is answered by the real method. Python 3.13's ``Path.exists`` and ``is_dir`` re-raise every error but a missing path."""
    import errno

    real = getattr(Path, method)

    def look(self, *a, **k):
        if needle in str(self):
            raise OSError(errno.ENAMETOOLONG, f"File name too long: {self}")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, method, look)


def test_a_path_the_system_cannot_examine_ends_the_start_in_a_refusal_record_and_the_error_is_raised_on_unchanged(journal):
    with pytest.raises(OSError) as caught, se.run_path_checked("import", via="single-file"):
        raise OSError(36, f"File name too long: /home/someone/{MARKER}")
    assert caught.value.errno == 36, "the caller sees the error it saw before the record existed"
    event = _only("run_import")
    assert (event["outcome"], event["ran"], event["via"], event["error"]) == ("refused", False, "single-file", "OSError")
    assert event["reason"] == se.RUN_REFUSALS["path-unreadable"] and "open" not in event
    _nothing_secret_anywhere(journal, MARKER, "someone", "too long")


def test_only_an_oserror_is_a_refusal_here_and_a_kind_the_journal_does_not_have_records_nothing(journal):
    with pytest.raises(ValueError), se.run_path_checked("import", via="folder"):
        raise ValueError("not this module's business")
    with pytest.raises(OSError), se.run_path_checked("", via="folder"):  # the folder manager's "no such mode"
        raise OSError(5, "I/O error")
    with se.run_path_checked("import", via="folder"):
        pass
    for kind in se.RUN_KINDS.values():
        assert se.diagnostics_member(10**9)["kinds"][kind]["total"] == 0


def test_the_two_new_refusal_keys_have_fixed_sentences_that_claim_only_what_was_known():
    for key in ("path-unreadable", "free-space-unreadable"):
        assert key in se.RUN_REFUSALS and "{" not in se.RUN_REFUSALS[key], key
    assert "could not be" in se.RUN_REFUSALS["free-space-unreadable"], "an unread figure is not a shortage"
    assert "free space the backup needs" in se.RUN_REFUSALS["no-space"]


def test_the_member_names_the_run_journals_own_names_for_the_runs_and_says_where_the_outcomes_differ():
    method = se._METHOD
    for word in ("folder-export", "folder-import", "newsletter-import", "match by 'via'", "stopped-by-operator", "merge check", "bad signature"):
        assert word in method, word
    assert "the run journal's 'export'" not in method, "the folder backup is not the run journal's 'export'"
    doc = se.__doc__ or ""
    assert "folder-export" in doc and "newsletter-import" in doc and "volume-set verification has no run there" in doc


# --------------------------------------------------------------------------- #
#  5. The net round a start and the scope round a run (the six path checks stay where they were written)
# --------------------------------------------------------------------------- #
def test_the_net_records_the_refusal_its_error_class_names_and_raises_the_error_on_unchanged(journal):
    """Only the CLASS is read: the same ValueError a path check raises leaves one refusal, with the class, and the caller still gets the
    very exception it got before the record existed. RED WITHOUT the ``refused_as`` pairs: nothing is recorded."""
    boom = ValueError(f"/home/someone/{MARKER} is not a folder.")
    with pytest.raises(ValueError) as caught, se.run_refusals_net("export", via="volume-set", refused_as=se.NOT_A_FOLDER):
        raise boom
    assert caught.value is boom
    event = _only("run_export")
    assert (event["outcome"], event["ran"], event["via"], event["error"]) == ("refused", False, "volume-set", "ValueError")
    assert event["reason"] == se.RUN_REFUSALS["not-a-folder"]
    _nothing_secret_anywhere(journal, MARKER, "someone")


def test_every_pair_the_callers_hand_over_is_its_refusal_for_its_class_and_a_key_of_the_table(journal):
    from fastapi import HTTPException

    with pytest.raises(ValueError), se.run_refusals_net("import", via="folder", refused_as=se.NOT_A_FOLDER):
        raise ValueError("/x anything at all")
    pairs = ((HTTPException, "not-a-file"),)
    with pytest.raises(HTTPException), se.run_refusals_net("import", via="single-file", refused_as=pairs):
        raise HTTPException(status_code=400, detail="/y anything at all")
    assert {e["reason"] for e in _events("run_import")} == {se.RUN_REFUSALS["not-a-folder"], se.RUN_REFUSALS["not-a-file"]}
    assert sorted(e["via"] for e in _events("run_import")) == ["folder", "single-file"]
    assert all(key in se.RUN_REFUSALS for _cls, key in se.NOT_A_FOLDER + pairs), "a pair names a key the journal has a sentence for"


def test_no_word_of_the_error_is_read_and_a_class_that_was_not_handed_over_is_not_named(journal):
    """The words of a refusal can hold anything (a path, a passphrase): they decide nothing and are kept nowhere. A class the net was not
    given is not a reason it may invent. RED WITHOUT the class test: a RuntimeError is recorded as a missing folder."""
    secret = "hunter2-" + MARKER
    with pytest.raises(ValueError), se.run_refusals_net("export", via="volume-set", refused_as=se.NOT_A_FOLDER):
        raise ValueError(f"Cannot use destination /a/{secret} b: [Errno 13] Permission denied")
    with pytest.raises(RuntimeError), se.run_refusals_net("export", via="volume-set", refused_as=se.NOT_A_FOLDER):
        raise RuntimeError("anything else")
    with pytest.raises(ValueError), se.run_refusals_net("verify", via="volume-set"):  # no pairs handed over: nothing to name
        raise ValueError("/a is not a folder to verify.")
    (event,) = _events("run_export")
    assert event["reason"] == se.RUN_REFUSALS["not-a-folder"] and event["error"] == "ValueError"
    assert _events("run_verify") == [] and _events("run_import") == []
    _nothing_secret_anywhere(journal, secret, MARKER, "Permission denied")


def test_an_oserror_that_leaves_a_start_is_a_path_that_could_not_be_examined(journal):
    with pytest.raises(OSError) as caught, se.run_refusals_net("verify", via="volume-set"):
        raise OSError(36, f"File name too long: /home/someone/{MARKER}")
    assert caught.value.errno == 36
    event = _only("run_verify")
    assert (event["outcome"], event["error"], event["reason"]) == ("refused", "OSError", se.RUN_REFUSALS["path-unreadable"])
    _nothing_secret_anywhere(journal, MARKER, "someone", "too long")


def test_a_start_that_recorded_its_own_refusal_or_opened_a_run_is_not_recorded_twice(journal):
    """One start, one record. RED WITHOUT the scope's mark: the OSError below leaves two refusals, and a run opened in the body leaves a
    refusal beside it."""
    with pytest.raises(OSError), se.run_refusals_net("export", via="volume-set"):
        se.run_refused("export", "destination-unusable", failure="PermissionError", via="volume-set")
        raise OSError(13, "denied")
    (event,) = _events("run_export")
    assert event["reason"] == se.RUN_REFUSALS["destination-unusable"]
    with pytest.raises(ValueError), se.run_refusals_net("import", via="single-file", refused_as=se.NOT_A_FOLDER):
        se.run_started("import", via="single-file")
        raise ValueError("/z is not a file to restore.")
    (opened,) = _events("run_import")
    assert opened["open"] is True and "outcome" not in opened, "the run opened in the body is the only record; the net stood down"


def test_a_net_ends_with_its_start_so_a_later_start_is_judged_alone_and_a_kind_the_journal_lacks_records_nothing(journal):
    assert se._REFUSAL_SCOPE.get() is None
    with se.run_refusals_net("export", via="volume-set"):
        assert se._REFUSAL_SCOPE.get() is not None
        se.run_refused("export", "no-passphrase", via="volume-set")
    assert se._REFUSAL_SCOPE.get() is None, "the scope ends with the start (a later one starts clean)"
    with pytest.raises(OSError), se.run_refusals_net("export", via="volume-set"):
        raise OSError(5, "I/O error")
    reasons = [e["reason"] for e in _events("run_export")]
    assert se.RUN_REFUSALS["path-unreadable"] in reasons and len(reasons) == 2, "the first start's record did not hide the second's"
    with pytest.raises(OSError), se.run_refusals_net("", via="folder"):  # the folder manager's "no such mode"
        raise OSError(5, "I/O error")
    assert len(_events("run_export")) == 2 and _events("run_import") == [] and _events("run_verify") == []


def test_the_net_is_also_a_decorator_and_hands_the_result_and_the_arguments_through(journal):
    @se.run_refusals_net("import", via="single-file", refused_as=((ValueError, "not-a-file"),))
    def restore(path, *, flag=False):
        if flag:
            raise ValueError(f"{path} is not a file to restore.")
        return {"path": path}

    assert restore("/a") == {"path": "/a"}
    with pytest.raises(ValueError):
        restore("/b", flag=True)
    assert _only("run_import")["reason"] == se.RUN_REFUSALS["not-a-file"]


def test_a_run_open_is_closed_as_an_error_with_the_class_of_what_leaves_and_the_error_goes_on(journal, monkeypatch):
    monkeypatch.setattr(se, "free_bytes_of", lambda path=None: 4096)
    with pytest.raises(ValueError, match="no"), se.run_open("import", via="single-file") as note:
        assert note is not None
        (running,) = _events("run_import")
        assert running["open"] is True and running["data_free_bytes"] == 4096 and running["via"] == "single-file"
        raise ValueError("no")
    event = _only("run_import")
    assert (event["open"], event["outcome"], event["error"]) == (False, "error", "ValueError")
    assert "no" not in repr(event.get("reason", "")), "the words of the error are not kept"


def test_a_run_open_leaves_what_the_block_wrote_and_closes_the_rest_without_an_outcome(journal):
    with se.run_open("import", via="single-file") as note:
        se.run_ended(note, "ok", articles_merged=7)
    ok = _only("run_import")
    assert (ok["outcome"], ok["articles_merged"]) == ("ok", 7), "the exit must not overwrite an outcome the block wrote"
    se.reset_for_tests()
    with se.run_open("import", via="single-file"):
        pass
    assert _only("run_import")["outcome"] == "ended-without-a-recorded-outcome"
    se.reset_for_tests()
    with pytest.raises(KeyboardInterrupt), se.run_open("import", via="single-file"):
        raise KeyboardInterrupt
    event = _only("run_import")
    assert event["open"] is False and event["outcome"] == "ended-without-a-recorded-outcome", "an exit that is not an Exception still closes the run"


def test_an_outcome_the_block_wrote_before_it_raised_stands_over_the_plain_error(journal):
    """The legacy restore writes ``refused`` (a merge check) or ``stopped-by-operator`` where it knows, then raises an HTTP error the
    ``run_open`` sees as one more Exception. RED WITHOUT the first-outcome-stands rule of ``end``: the run reads ``error``."""
    with pytest.raises(RuntimeError), se.run_open("import", via="single-file") as note:
        se.run_ended(note, "refused", failure="MergeError")
        raise RuntimeError("converted")
    event = _only("run_import")
    assert (event["outcome"], event["error"]) == ("refused", "MergeError")


def test_a_net_inside_a_net_records_the_error_once(journal):
    """A restore run from a queue item may pass two nets; the error is the same error. RED WITHOUT the parent mark: two records."""
    pairs = se.NOT_A_FOLDER
    with (
        pytest.raises(ValueError),
        se.run_refusals_net("import", via="single-file", refused_as=pairs),
        se.run_refusals_net("import", via="volume-set", refused_as=pairs),
    ):
        raise ValueError("/q is not a folder to restore from.")
    event = _only("run_import")
    assert event["via"] == "volume-set" and event["reason"] == se.RUN_REFUSALS["not-a-folder"]
