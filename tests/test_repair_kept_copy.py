"""The damaged file a repair set aside is removed thirty days after the repaired file first read clean (R129, the user's answer 35 = b).

The user ruled: "auto-remove the kept damaged copy 30 days after the repaired file's first clean read". This is the one place the
app deletes a file the person may care about (a copy of their library, up to 14 GB, that may still hold rows the salvage could
not read), so every condition of the removal is pinned here, one test each, over real files and real hard links:

  * it is removed at the first START on or after the date, never by a timer, and only while the repair step's switch is on;
  * never while a repair or a check of the data files runs, and never while the live library is latched damaged again;
  * only the file the repair itself recorded: its name, its folder and its inode (the swap noted them while the second name was
    made); a link, something that is not a regular file, a different file under that name, a name that is not the repair's
    pattern and the live file itself are each refused FOR GOOD, and the notice then says the app will not remove it;
  * the ``-wal`` hard link the swap made goes with it, by the same identity, and an unrecognised ``-wal`` is left;
  * a copy the person removed first is recorded and nothing else is said or touched; a failed unlink is retried at the next start;
  * the removal (date, size) is written into the repair record the damage notice and the Diagnostics zip read.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.database import damage, repair
from src.database.damage import FILE_CORPUS, DamageRegistry

CLEAN_AT = "2026-10-06T03:00:00+00:00"
DUE = datetime(2026, 11, 5, 3, 0, 0, tzinfo=UTC)  # CLEAN_AT plus KEPT_COPY_DAYS
KEPT_NAME = "live.damaged-20261006T030000Z.db"


class World:
    """A data folder with a live library file, the damaged file a repair set aside and the repair record that says so."""

    def __init__(self, folder: Path, reg: DamageRegistry) -> None:
        self.folder, self.reg = folder, reg
        self.live = folder / "live.db"
        self.live.write_bytes(b"the repaired library" * 100)
        self.kept = folder / KEPT_NAME
        self.kept.write_bytes(b"the damaged library" * 500)
        self.wal: Path | None = None
        self.record(self.kept)

    def record(self, kept: Path, **more) -> None:
        st = os.lstat(kept)
        fields = {
            "file": FILE_CORPUS, "state": "done", "kept_file": kept.name, "folder": str(self.folder), "kept_rows": 10, "unreadable_ids": 2,
            "kept_file_ino": st.st_ino, "kept_file_dev": st.st_dev, "clean_at": CLEAN_AT,
            "kept_file_removal_after": DUE.isoformat(timespec="seconds"),
        }
        fields.update(more)
        self.reg.repair_upsert("a", **fields)

    def with_a_log(self) -> Path:
        """The second name of the live log the swap makes (a hard link), and its inode in the record."""
        original = self.folder / "live.db-wal"
        original.write_bytes(b"a log")
        self.wal = Path(str(self.kept) + "-wal")
        os.link(original, self.wal)
        self.reg.repair_upsert("a", kept_wal_ino=os.lstat(self.wal).st_ino, kept_wal_bytes=5)
        return self.wal

    def rec(self) -> dict:
        return self.reg.repairs()[-1]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", reg)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (tmp_path / "live.db", "live.db") if key == FILE_CORPUS else (None, None))
    monkeypatch.delenv("OO_BOOT_REPAIR", raising=False)
    repair._reset_for_tests()
    yield World(tmp_path, reg)
    repair._reset_for_tests()


def _only(results: list[dict]) -> dict:
    assert len(results) == 1, results
    return results[0]


# --------------------------------------------------------------------------- #
#  when
# --------------------------------------------------------------------------- #
def test_the_date_is_thirty_days_from_the_first_clean_read_and_the_day_itself_is_due(world):
    assert repair.KEPT_COPY_DAYS == 30, "the user's number moved: the notices say 30 days"
    assert datetime.fromisoformat(CLEAN_AT) + timedelta(days=repair.KEPT_COPY_DAYS) == DUE
    assert repair.sweep_kept_copies(now=DUE - timedelta(seconds=1)) == [], "removed a second early"
    assert world.kept.exists() and "kept_file_removed_at" not in world.rec()
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert result["outcome"] == "removed" and result["name"] == KEPT_NAME
    assert not world.kept.exists()


def test_a_record_without_a_date_is_never_swept(world):
    world.reg.repair_upsert("a", kept_file_removal_after=None)
    assert repair.sweep_kept_copies(now=DUE + timedelta(days=3650)) == []
    world.reg.repair_upsert("a", kept_file_removal_after="not a date")
    assert repair.sweep_kept_copies(now=DUE + timedelta(days=3650)) == []
    assert world.kept.exists()


def test_only_a_repair_that_finished_has_a_copy_to_remove(world):
    for state in ("running", "refused", "failed", "stopped"):
        world.reg.repair_upsert("a", state=state)
        assert repair.sweep_kept_copies(now=DUE + timedelta(days=1)) == [], state
        assert world.kept.exists(), state


def test_the_switch_that_turns_the_repair_off_turns_the_removal_off(world, monkeypatch):
    monkeypatch.setenv("OO_BOOT_REPAIR", "0")
    assert repair.sweep_kept_copies(now=DUE + timedelta(days=30)) == []
    assert world.kept.exists(), "a person who switched the repair off has not asked for file work"
    monkeypatch.delenv("OO_BOOT_REPAIR")
    assert _only(repair.sweep_kept_copies(now=DUE + timedelta(days=30)))["outcome"] == "removed"


def test_the_removal_is_a_step_of_the_start_and_nothing_else_calls_it():
    """Never from a timer, a request or a job: a library that runs for weeks removes the file at the first START after the date, and
    the notice says so. The only callers of the sweep are the boot step's own function and its definition."""
    root = Path(__file__).resolve().parents[1] / "src"
    callers = {
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "sweep_kept_copies(" in p.read_text(encoding="utf-8")
    }
    assert callers == {"database/repair.py"}, callers
    text = (root / "database" / "repair.py").read_text(encoding="utf-8")
    assert text.count("sweep_kept_copies(") == 2, "the definition and the boot step's one call: no other call"
    boot = (root / "api" / "boot_sequence.py").read_text(encoding="utf-8")
    assert "repair.run_now_and_wait()" in boot
    users = {str(p.relative_to(root)) for p in root.rglob("*.py") if "run_now_and_wait()" in p.read_text(encoding="utf-8")}
    assert "api/boot_sequence.py" in users and not any("scheduler" in u or "jobs" in u for u in users), users


def test_the_boot_step_removes_a_due_copy_even_when_nothing_is_damaged(world):
    """A start with nothing to repair is the ordinary start, and it is the one that removes the file: the step runs the sweep after
    the repair whatever the repair did."""
    due_in_the_past = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="seconds")
    world.reg.repair_upsert("a", kept_file_removal_after=due_in_the_past)
    assert repair.run_now_and_wait() == "skipped"
    assert not world.kept.exists()
    assert world.rec()["kept_file_removed_at"]


def test_a_sweep_that_goes_wrong_is_never_the_starts_failure(world, monkeypatch):
    monkeypatch.setattr(repair, "sweep_kept_copies", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    assert repair.run_now_and_wait() == "skipped"


# --------------------------------------------------------------------------- #
#  never while the copy may still matter
# --------------------------------------------------------------------------- #
def test_nothing_is_removed_while_a_repair_runs(world, monkeypatch):
    real_status = repair.REPAIR_JOB.status
    monkeypatch.setattr(repair.REPAIR_JOB, "status", lambda: {"state": "running"})
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert (result["outcome"], result["reason"]) == ("waiting", "repair-running") and world.kept.exists()
    monkeypatch.setattr(repair.REPAIR_JOB, "status", real_status)
    # a repair another record says is running counts the same, whatever the job says
    world.reg.repair_upsert("b", file=FILE_CORPUS, state="running")
    assert _only(repair.sweep_kept_copies(now=DUE))["reason"] == "repair-running" and world.kept.exists()


def test_nothing_is_removed_while_a_check_of_the_data_files_runs(world, monkeypatch):
    monkeypatch.setattr(world.reg, "check_is_running", lambda: True)
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert (result["outcome"], result["reason"]) == ("waiting", "check-running") and world.kept.exists()


def test_the_holds_of_the_removal_do_not_follow_the_switch_that_turns_the_pause_off(world, monkeypatch):
    """``OO_DAMAGE_GUARD=0`` turns the PAUSE of writers off (``latched()`` and ``verifying()`` answer False). The notice says the copy
    stays "unless your library is damaged again then": that must hold with the pause off too (the deep read of E3, S3)."""
    monkeypatch.setenv("OO_DAMAGE_GUARD", "0")
    world.reg._note_verified_damage(FILE_CORPUS, ["articles"], path=world.live, at="2026-11-05T02:00:00+00:00")
    assert world.reg.latched(FILE_CORPUS) is False, "the premise: the switch makes the pause answer False"
    result = _only(repair.sweep_kept_copies(now=DUE + timedelta(days=100)))
    assert (result["outcome"], result["reason"]) == ("waiting", "corpus-latched") and world.kept.exists()
    world.reg.retry(reason="replaced", files=(FILE_CORPUS,), file_replaced=True)
    monkeypatch.setattr(world.reg, "check_is_running", lambda: True)
    assert world.reg.verifying() is False
    result = _only(repair.sweep_kept_copies(now=DUE + timedelta(days=100)))
    assert (result["outcome"], result["reason"]) == ("waiting", "check-running") and world.kept.exists()


def test_a_repair_an_earlier_process_left_running_holds_nothing_and_is_marked_interrupted(world, tmp_path, monkeypatch):
    """A repair a crash, a power cut or a stop ended leaves its record ``running`` for ever; counting it made every later removal wait
    for ten newer repairs to push it out, while the notice kept promising the date (the deep read of E3, S2)."""
    world.reg.repair_upsert("dead", file=FILE_CORPUS, state="running")
    world.reg._flush_latest()  # what the dead process had written before it died
    nxt = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")  # the next process
    monkeypatch.setattr(damage, "registry", nxt)
    assert any(r["id"] == "dead" and r["state"] == "running" for r in nxt.repairs()), "the premise: the record is carried over"
    assert nxt.repairing_now() is False, "an earlier process's record held the removal (asked AFTER the file was read: before it, an empty answer proves nothing)"
    assert nxt.settle_interrupted_repairs() == 1
    assert next(r for r in nxt.repairs() if r["id"] == "dead")["state"] == "interrupted"
    assert nxt.settle_interrupted_repairs() == 0
    assert _only(repair.sweep_kept_copies(now=DUE))["outcome"] == "removed"


def test_this_processs_own_running_repair_still_holds_the_removal(world):
    world.reg.repair_upsert("mine", file=FILE_CORPUS, state="running")
    assert world.reg.repairing_now() is True
    assert _only(repair.sweep_kept_copies(now=DUE))["reason"] == "repair-running"
    assert world.reg.settle_interrupted_repairs() == 0, "a repair of this process was marked interrupted while it ran"


def test_the_notice_does_not_promise_a_date_the_switched_off_sweep_will_never_keep(world, monkeypatch):
    monkeypatch.setenv("OO_BOOT_REPAIR", "0")
    notes = [n for n in world.reg.notes() if n["kind"] == "repaired"]
    assert notes[-1]["frame"] == damage.FRAME_KEPT_SWITCH, notes
    assert {"name", "size", "folder"} <= set(notes[-1]["vars"]) and "{date}" not in damage.FRAME_KEPT_SWITCH
    assert "OO_BOOT_REPAIR=0" in damage.FRAME_KEPT_SWITCH and "remove it yourself" in damage.FRAME_KEPT_SWITCH
    monkeypatch.delenv("OO_BOOT_REPAIR")
    assert [n for n in world.reg.notes() if n["kind"] == "repaired"][-1]["frame"] == damage.FRAME_KEPT_UNTIL


def test_nothing_is_removed_while_the_live_library_is_latched_damaged_again_and_it_goes_at_the_start_after(world):
    """The copy may hold rows the live file lost; a library that is damaged again is exactly when it matters. The copy waits, and
    nothing is recorded, so the next start tries again."""
    world.reg._note_verified_damage(FILE_CORPUS, ["articles"], path=world.live, at="2026-11-05T02:00:00+00:00")
    assert world.reg.latched(FILE_CORPUS)
    result = _only(repair.sweep_kept_copies(now=DUE + timedelta(days=100)))
    assert (result["outcome"], result["reason"]) == ("waiting", "corpus-latched")
    assert world.kept.exists() and "kept_file_removed_at" not in world.rec() and "kept_file_removal_refused" not in world.rec()
    world.reg.retry(reason="replaced", files=(FILE_CORPUS,), file_replaced=True)
    assert not world.reg.latched(FILE_CORPUS)
    assert _only(repair.sweep_kept_copies(now=DUE + timedelta(days=101)))["outcome"] == "removed"


# --------------------------------------------------------------------------- #
#  the removal: the file the repair set aside, and nothing else
# --------------------------------------------------------------------------- #
def test_the_file_and_its_log_are_removed_and_the_record_says_what_and_when(world):
    wal = world.with_a_log()
    size = world.kept.stat().st_size
    original = world.folder / "live.db-wal"
    live_before = world.live.read_bytes()
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert result["outcome"] == "removed"
    assert not world.kept.exists() and not wal.exists(), "the log's second name stayed behind"
    assert original.read_bytes() == b"a log", "the LIVE log was touched: only its second name is the kept file's"
    assert world.live.read_bytes() == live_before and world.live.exists()
    rec = world.rec()
    assert rec["kept_file_removed_at"] == DUE.isoformat(timespec="seconds")
    assert rec["kept_file_removed_bytes"] == size and rec["kept_wal_removed"] is True and "kept_wal_left" not in rec
    # the sentence the person reads afterwards, and no second removal
    notes = [n for n in world.reg.notes() if n["kind"] == "repaired"]
    assert notes[-1]["frame"] == damage.FRAME_KEPT_REMOVED
    assert notes[-1]["vars"] == {"name": KEPT_NAME, "size": damage._bytes_words(size), "date": "2026-11-05"}
    assert repair.sweep_kept_copies(now=DUE + timedelta(days=1)) == []


def test_a_log_nobody_recognises_is_left_where_it_is_and_recorded(world):
    original = world.folder / "live.db-wal"
    original.write_bytes(b"a log")
    stranger = Path(str(world.kept) + "-wal")
    stranger.write_bytes(b"someone else's file")  # not the hard link the swap made: another inode
    world.reg.repair_upsert("a", kept_wal_ino=os.lstat(original).st_ino)
    assert _only(repair.sweep_kept_copies(now=DUE))["outcome"] == "removed"
    assert not world.kept.exists() and stranger.read_bytes() == b"someone else's file"
    rec = world.rec()
    assert rec["kept_wal_left"] is True and "kept_wal_removed" not in rec


def test_a_copy_the_person_removed_first_is_recorded_as_gone_and_nothing_is_said(world):
    world.kept.unlink()
    assert [n for n in world.reg.notes() if n["kind"] == "repaired"] == [], "a file that is not there is not described"
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert result["outcome"] == "gone"
    rec = world.rec()
    assert rec["kept_file_gone_at"] and "kept_file_removed_at" not in rec
    assert repair.sweep_kept_copies(now=DUE + timedelta(days=1)) == [], "a gone copy is looked for once"
    assert world.live.exists()


def test_a_failed_unlink_is_tried_again_at_the_next_start_and_records_nothing(world, monkeypatch):
    real = os.unlink

    def refuse(path, *a, **k):
        if str(path).endswith(KEPT_NAME):
            raise PermissionError(13, "Permission denied")
        return real(path, *a, **k)

    monkeypatch.setattr(os, "unlink", refuse)
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert (result["outcome"], result["reason"]) == ("failed", "unlink") and world.kept.exists()
    rec = world.rec()
    assert "kept_file_removed_at" not in rec and "kept_file_removal_refused" not in rec
    monkeypatch.setattr(os, "unlink", real)
    assert _only(repair.sweep_kept_copies(now=DUE + timedelta(days=1)))["outcome"] == "removed"


def test_a_file_that_is_not_in_the_record_is_never_touched(world):
    """An earlier repair's kept file, a person's own copy, a salvage in progress: none of them is the file this record names."""
    bystanders = [
        world.folder / "live.damaged-20250101T000000Z.db",
        world.folder / "live.damaged-20260101T000000Z-2.db",
        world.folder / "live.salvage-20261006T030000Z.db",
        world.folder / "backup-of-my-library.db",
    ]
    for b in bystanders:
        b.write_bytes(b"not the file the repair set aside")
    assert _only(repair.sweep_kept_copies(now=DUE))["outcome"] == "removed"
    assert all(b.read_bytes() == b"not the file the repair set aside" for b in bystanders)


# --------------------------------------------------------------------------- #
#  refused for good: what is there now is not the file the repair set aside
# --------------------------------------------------------------------------- #
def _refused(world, code: str, *, said: bool = True) -> None:
    """Refused FOR GOOD: recorded, said (when there is a file to say it about), never tried again."""
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert (result["outcome"], result["reason"]) == ("refused", code), result
    rec = world.rec()
    assert rec["kept_file_removal_refused"] == code and "kept_file_removed_at" not in rec
    assert repair.sweep_kept_copies(now=DUE + timedelta(days=400)) == []
    frames = [n["frame"] for n in world.reg.notes() if n["kind"] == "repaired"]
    assert (damage.FRAME_KEPT_NOT_REMOVED in frames) is said, frames
    assert damage.FRAME_KEPT_UNTIL not in frames, "the notice still promised a removal it had refused"


def test_a_link_under_the_name_is_refused_and_what_it_points_at_is_untouched(world, tmp_path):
    precious = tmp_path / "elsewhere"
    precious.mkdir()
    target = precious / "my-holiday-photos.db"
    target.write_bytes(b"precious")
    ino = os.lstat(world.kept).st_ino
    world.kept.unlink()
    world.kept.symlink_to(target)
    world.reg.repair_upsert("a", kept_file_ino=ino)
    _refused(world, "symlink")
    assert target.read_bytes() == b"precious" and world.kept.is_symlink()


def test_a_different_file_under_the_name_is_refused_by_its_inode(world):
    # written BESIDE the old one and moved over it, so the two never share an inode (a freed inode is handed out again at once)
    other = world.folder / "something-else.db"
    other.write_bytes(b"a file the person put here after the repair")
    os.replace(other, world.kept)
    _refused(world, "not-the-file-set-aside")
    assert world.kept.read_bytes() == b"a file the person put here after the repair"


def test_a_directory_under_the_name_is_refused(world):
    ino = os.lstat(world.kept).st_ino
    world.kept.unlink()
    world.kept.mkdir()
    (world.kept / "inside").write_bytes(b"x")
    world.reg.repair_upsert("a", kept_file_ino=ino)
    _refused(world, "not-a-file", said=False)
    assert (world.kept / "inside").read_bytes() == b"x"


@pytest.mark.parametrize(
    "name",
    [
        "live.db",  # the live library itself
        "live.damaged-20261006T030000Z.db.bak",  # not the pattern's suffix
        "other.damaged-20261006T030000Z.db",  # another file's kept copy
        "live.damaged-yesterday.db",
        "live.damaged-20261006T030000Z.db/../live.db",  # a path, not a name
        "../live.damaged-20261006T030000Z.db",
    ],
)
def test_a_record_that_names_anything_but_a_kept_copy_of_the_live_file_removes_nothing(world, name):
    world.reg.repair_upsert("a", kept_file=name)
    before = {p.name: p.read_bytes() for p in world.folder.iterdir() if p.is_file() and p.name != "database-damage.json"}
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert (result["outcome"], result["reason"]) == ("refused", "name-pattern"), result
    assert {p.name: p.read_bytes() for p in world.folder.iterdir() if p.is_file() and p.name != "database-damage.json"} == before


def test_a_record_with_no_name_has_nothing_to_remove(world):
    world.reg.repair_upsert("a", kept_file="")
    assert repair.sweep_kept_copies(now=DUE) == [] and world.kept.exists() and world.live.exists()


def test_a_record_for_another_folder_is_refused(world, tmp_path):
    other = tmp_path / "another-drive"
    other.mkdir()
    twin = other / KEPT_NAME
    twin.write_bytes(b"the same name in another folder")
    world.reg.repair_upsert("a", folder=str(other), kept_file_ino=os.lstat(twin).st_ino)
    _refused(world, "outside-data-folder")
    assert twin.read_bytes() == b"the same name in another folder" and world.kept.exists()


def test_the_live_library_under_a_second_name_is_never_removed(world):
    """If the swap did not happen, the kept name is a second name of the LIVE file: removing it would be removing nothing, and
    removing the wrong one would be removing the library. It is refused whichever way the two names are held."""
    world.kept.unlink()
    os.link(world.live, world.kept)
    world.reg.repair_upsert("a", kept_file_ino=os.lstat(world.live).st_ino)
    _refused(world, "is-the-live-file")
    assert world.live.read_bytes() == b"the repaired library" * 100 and world.kept.exists()


def test_no_live_file_to_compare_with_waits_and_removes_nothing(world, monkeypatch):
    monkeypatch.setattr(damage, "_file_paths", lambda key: (None, None))
    result = _only(repair.sweep_kept_copies(now=DUE))
    assert (result["outcome"], result["reason"]) == ("waiting", "no-live-file") and world.kept.exists()
    assert "kept_file_removal_refused" not in world.rec()


def test_a_device_number_that_changed_is_not_a_refusal(world):
    """Measured as the reason it is not compared: device numbers change across mounts (btrfs subvolumes, a drive re-attached) while
    the name, the folder and the inode still bind the file."""
    world.reg.repair_upsert("a", kept_file_dev=os.lstat(world.kept).st_dev + 7)
    assert _only(repair.sweep_kept_copies(now=DUE))["outcome"] == "removed" and not world.kept.exists()


# --------------------------------------------------------------------------- #
#  what the person reads
# --------------------------------------------------------------------------- #
def test_the_notice_names_the_file_where_it_is_how_big_and_the_day_it_goes(world):
    notes = [n for n in world.reg.notes() if n["kind"] == "repaired"]
    assert [n["frame"] for n in notes] == [damage.FRAME_REPAIRED, damage.FRAME_KEPT_UNTIL]
    where = notes[1]["vars"]
    assert where == {"name": KEPT_NAME, "size": damage._size_words(world.kept), "folder": str(world.folder), "date": "2026-11-05"}
    for frame in (damage.FRAME_KEPT_UNTIL, damage.FRAME_KEPT_REMOVED, damage.FRAME_KEPT_NOT_REMOVED, damage.FRAME_REPAIR_NEXT_START, damage.FRAME_REPAIRING):
        assert "the app deletes nothing" not in frame.lower() and "nothing is deleted" not in frame.lower(), "the sentence is no longer true"
    assert "30 days" in damage.FRAME_KEPT_UNTIL and "first start" in damage.FRAME_KEPT_UNTIL and "damaged again" in damage.FRAME_KEPT_UNTIL
    assert "{date}" in damage.FRAME_KEPT_UNTIL and "{folder}" in damage.FRAME_KEPT_UNTIL and "{size}" in damage.FRAME_KEPT_UNTIL
    assert "you can remove it" in damage.FRAME_KEPT_UNTIL, "the person is told they may remove it sooner"


def test_the_notice_that_the_app_removed_the_file_does_not_outlive_its_use(world):
    """A banner nobody can dismiss goes after as many days as the copy was kept; the record the Diagnostics zip reads stays."""
    just_now = datetime.now(UTC)
    world.reg.repair_upsert("a", kept_file_removed_at=just_now.isoformat(timespec="seconds"), kept_file_removed_bytes=1_500_000)
    world.kept.unlink()
    assert [n["frame"] for n in world.reg.notes() if n["kind"] == "repaired"][-1] == damage.FRAME_KEPT_REMOVED
    old = (just_now - timedelta(days=damage.KEPT_COPY_DAYS, seconds=5)).isoformat(timespec="seconds")
    world.reg.repair_upsert("a", kept_file_removed_at=old)
    assert [n for n in world.reg.notes() if n["kind"] == "repaired"] == []
    assert world.rec()["kept_file_removed_at"] == old, "the record keeps the date for the zip"
    world.reg.repair_upsert("a", kept_file_removed_at="not a time")
    assert [n for n in world.reg.notes() if n["kind"] == "repaired"] == []


def test_the_removal_survives_a_restart_in_the_record_the_diagnostics_zip_reads(world, tmp_path):
    assert _only(repair.sweep_kept_copies(now=DUE))["outcome"] == "removed"
    world.reg._flush_latest()
    again = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    rec = again.repairs()[-1]
    assert rec["kept_file_removed_at"] == DUE.isoformat(timespec="seconds") and rec["kept_file_removed_bytes"] > 0
    assert repair.sweep_kept_copies(now=DUE + timedelta(days=1)) == []


# --------------------------------------------------------------------------- #
#  a file the drive could not read is never removed (the coordinator's ruling, 2026-10-06)
# --------------------------------------------------------------------------- #
def test_a_copy_the_drive_could_not_read_is_not_removed_whatever_the_date_says(world):
    world.reg.repair_upsert("a", kept_file_removal_withheld="disk-read-failed", kept_file_disk_unread_pages=4)
    assert repair.sweep_kept_copies(now=DUE + timedelta(days=3650)) == [], "a withheld copy is not even listed"
    assert world.kept.exists() and "kept_file_removed_at" not in world.rec() and "kept_file_removal_refused" not in world.rec()
    # the one place a file goes refuses it too: a record that carries only the count (or a sweep that reached it by another road)
    for fields in ({"kept_file_removal_withheld": "disk-read-failed", "kept_file_disk_unread_pages": 0},
                   {"kept_file_removal_withheld": None, "kept_file_disk_unread_pages": 1}):
        rec = {**world.rec(), **fields}
        assert repair._remove_kept_copy(rec, DUE + timedelta(days=1)) == {"outcome": "withheld", "reason": "disk-read-failed"}
        assert world.kept.exists(), fields


def test_the_notice_for_a_copy_the_drive_could_not_read_says_so_and_does_not_promise_a_removal(world):
    world.reg.repair_upsert("a", kept_file_removal_withheld="disk-read-failed", kept_file_disk_unread_pages=4, kept_file_removal_after=None)
    notes = [n for n in world.reg.notes() if n["kind"] == "repaired"]
    assert [n["frame"] for n in notes] == [damage.FRAME_REPAIRED, damage.FRAME_KEPT_DISK], notes
    assert notes[1]["vars"] == {"name": KEPT_NAME, "size": damage._size_words(world.kept), "folder": str(world.folder), "pages": 4}
    for var in ("{pages}", "{name}", "{size}", "{folder}"):
        assert var in damage.FRAME_KEPT_DISK, var
    assert "will not remove it" in damage.FRAME_KEPT_DISK and "Check the drive" in damage.FRAME_KEPT_DISK
    assert "{date}" not in damage.FRAME_KEPT_DISK, "a date was promised for a file that is never removed"
    # the withheld notice outranks a refusal's: it is the truer reason
    world.reg.repair_upsert("a", kept_file_removal_refused="symlink")
    assert [n["frame"] for n in world.reg.notes() if n["kind"] == "repaired"][-1] == damage.FRAME_KEPT_DISK
