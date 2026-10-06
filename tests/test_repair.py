"""The repair of a damaged library file at start-up (damaged-database plan, slice E3, R121).

The user ruled (R121, answer 27a): when damage is confirmed the app repairs the file itself, by a salvage copy and a swap,
and (R129, answer 35 = b) removes the damaged file the repair set aside thirty days after the repaired file first reads
clean, and nothing else. These tests run the orchestration over REAL stores damaged the way a bad sector damages them, through
the real per-table check that confirms the damage and the real salvage copy; only the engine of the running app is a
recorder (the swap's file work is the thing under test, not the pool):

  * a repair acts only on a corpus THIS process's check measured as damaged, and only while the switch is on;
  * a refusal (no room, no schema, no second file name, two unfinished starts) happens before a byte is copied, names its
    reason, and leaves every file exactly as it was;
  * the swap keeps the damaged file under a dated second name (the same bytes), removes the live log so it can never be
    replayed into the new file, and deletes nothing but the app's own scratch (the kept file's removal is the R129 sweep,
    tested apart below, at a start and after its thirty days);
  * a cut anywhere between the steps is finished at the next start when the damaged file is still the one the copy was made
    from, and discarded when it was written to since;
  * the attempt record is armed for the length of the repair and given back on an orderly quit;
  * the passphrase appears in no record, snapshot or log.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.database import damage, repair, salvage, verify
from src.database.damage import FILE_CORPUS, DamageRegistry

from . import damaged_store_helpers as H

UNCLEAN = {"clean": False, "at": "2026-10-06T01:00:00+00:00", "basis": "the liveness file"}


# --------------------------------------------------------------------------- #
#  fixtures: a registry of the test's own, a live file with real damage, the recorded engine
# --------------------------------------------------------------------------- #
@pytest.fixture()
def reg(tmp_path, monkeypatch):
    registry = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", registry)
    monkeypatch.setattr(repair, "_marker_path", lambda: tmp_path / repair.ATTEMPT_FILE)
    verify._reset_for_tests()
    repair._reset_for_tests()
    yield registry
    verify._reset_for_tests()
    repair._reset_for_tests()


@pytest.fixture()
def engine_calls(monkeypatch):
    """The running app's engine is a recorder: what is asserted is the swap's file work and its order."""
    from src.database import session

    calls: list[str] = []
    monkeypatch.setattr(session, "dispose_engine", lambda: calls.append("dispose"))
    monkeypatch.setattr(session, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(repair, "_after_the_swap", lambda: calls.append("after") or {"corpus_epoch": 1, "source_counts_cleared": 0})
    # The fold of the live log goes through the app's own engine, which is not over the test's file: it is tested apart, over a real
    # engine (``test_the_log_is_folded_in_before_the_swap`` and its neighbours).
    monkeypatch.setattr(repair, "_empty_the_log", lambda target: None)
    return calls


def _spread(pages: list[int], count: int) -> list[int]:
    step = max(1, len(pages) // (count + 1))
    return [pages[step * (i + 1)] for i in range(count)]


def _live(tmp_path, monkeypatch, reg, *, encrypted: bool = False, articles: int = 700, damage_it: bool = True) -> Path:
    """A live corpus file with the app's real schema, two damaged pages in the middle of its articles, and a start-up check
    that has read it and measured it ``damaged`` in THIS process (what the repair acts on)."""
    live = tmp_path / "live.db"
    H.build_app_store(live, articles=articles, encrypted=encrypted)
    if damage_it:
        if encrypted:
            H.damage_encrypted_table(live, "articles", count=2, key=H.KEY)
        else:
            H.overwrite_pages(live, _spread(H.leaf_pages(live, "articles"), 2), H.PLAIN_PAGE)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True
    assert verify.run_armed() is True
    return live


@pytest.fixture()
def key_held():
    from src.database import connect

    previous = connect.get_passphrase()
    connect.set_passphrase(H.KEY)
    yield H.KEY
    connect.set_passphrase(previous)


def _names(folder: Path) -> set[str]:
    return {p.name for p in folder.iterdir()}


class _Ctx:
    """The job context's progress, recorded."""

    stopping = False

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.frames: list[str] = []

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        if detail is not None:
            self.lines.append(str(detail))
            self.frames.append(getattr(detail, "i18n", ""))


def _the_kept_file(folder: Path) -> Path:
    found = sorted(folder.glob("live.damaged-*.db"))
    assert len(found) == 1, found
    return found[0]


# --------------------------------------------------------------------------- #
#  when the repair acts
# --------------------------------------------------------------------------- #
def test_the_step_acts_on_a_corpus_this_process_measured_damaged_and_on_nothing_else(tmp_path, monkeypatch, reg):
    live = _live(tmp_path, monkeypatch, reg)
    work = repair.plan()
    assert work["kind"] == "repair" and work["target"] == live and "articles" in work["tables"]
    # a finding an earlier process made and this one did not read again is not a reason to copy a file
    other = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", other)
    assert other.confirmed_damage(FILE_CORPUS) is None
    assert repair.plan() is None
    # a healthy file, a missing file, and the switch
    monkeypatch.setattr(damage, "registry", reg)
    monkeypatch.setenv("OO_BOOT_REPAIR", "0")
    assert repair.plan() is None, "the switch did not turn the repair off"
    monkeypatch.delenv("OO_BOOT_REPAIR")
    monkeypatch.setattr(damage, "_file_paths", lambda key: (tmp_path / "gone.db", "gone.db"))
    assert repair.plan() is None


def test_a_healthy_file_is_never_planned_for_repair(tmp_path, monkeypatch, reg):
    _live(tmp_path, monkeypatch, reg, damage_it=False)
    assert repair.plan() is None
    assert repair.run_now_and_wait() == "skipped" and repair.snapshot()["outcome"] == "skipped"


def test_only_the_corpus_is_repaired_a_damaged_wiki_file_is_left_to_its_latch(tmp_path, monkeypatch, reg):
    _live(tmp_path, monkeypatch, reg, damage_it=False)
    reg._note_verified_damage(damage.FILE_WIKI, ["articles"], path=tmp_path / "w.db", at="2026-10-06T03:00:00+00:00")
    assert repair.plan() is None


# --------------------------------------------------------------------------- #
#  refusals: before a byte is copied, in words, with every file untouched
# --------------------------------------------------------------------------- #
def _frozen(folder: Path) -> dict[str, str]:
    return {p.name: H.sha(p) for p in sorted(folder.iterdir()) if p.is_file() and p.name != "database-damage.json"}


def _refused(tmp_path, reg, work, code) -> repair.Declined:
    before = _frozen(tmp_path)
    with pytest.raises(repair.Declined) as caught:
        repair.run(work)
    assert caught.value.code == code
    assert _frozen(tmp_path) == before, "a refusal changed or made a file"
    assert not (tmp_path / repair.ATTEMPT_FILE).exists() or code == "unfinished-starts", "a refusal armed an attempt"
    rec = reg.repairs()[-1]
    assert rec["state"] == "refused" and rec["reason"] == code
    return caught.value


def test_no_room_refuses_with_the_figures_and_changes_nothing(tmp_path, monkeypatch, reg, engine_calls):
    _live(tmp_path, monkeypatch, reg)
    monkeypatch.setattr("src.config.hardware_reading.disk_bytes", lambda p: (1_000_000, 10**12))
    refusal = _refused(tmp_path, reg, repair.plan(), "no-room")
    assert refusal.facts["free_mb"] == 1 and refusal.facts["needed_mb"] > 1
    rec = reg.repairs()[-1]
    assert rec["free_mb"] == 1 and rec["needed_mb"] == refusal.facts["needed_mb"]
    notes = [n for n in reg.notes() if n["kind"] == "repair"]
    assert [n["frame"] for n in notes] == [damage.FRAME_REPAIR_NO_ROOM] and notes[0]["vars"]["free"] == 1
    assert engine_calls == [], "a refusal reached the engine"


def test_a_free_space_figure_that_cannot_be_read_is_not_a_refusal(tmp_path, monkeypatch, reg, engine_calls):
    _live(tmp_path, monkeypatch, reg)
    monkeypatch.setattr("src.config.hardware_reading.disk_bytes", lambda p: (None, None))
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["preflight"]["sufficient"] is None


def test_a_schema_that_cannot_be_read_refuses_and_says_to_restore(tmp_path, monkeypatch, reg, engine_calls):
    _live(tmp_path, monkeypatch, reg)
    work = repair.plan()
    work["tables"] = [verify.SCHEMA_ENTRY]
    _refused(tmp_path, reg, work, "schema-unreadable")
    assert [n["frame"] for n in reg.notes() if n["kind"] == "repair"] == [damage.FRAME_REPAIR_NO_SCHEMA]


def test_a_drive_that_cannot_give_a_file_a_second_name_is_refused_up_front(tmp_path, monkeypatch, reg, engine_calls):
    _live(tmp_path, monkeypatch, reg)
    monkeypatch.setattr(repair, "_can_hard_link", lambda folder: False)
    _refused(tmp_path, reg, repair.plan(), "no-hard-links")
    assert [n["frame"] for n in reg.notes() if n["kind"] == "repair"] == [damage.FRAME_REPAIR_NO_LINKS]


def test_two_unfinished_starts_refuse_a_third_until_the_app_is_updated(tmp_path, monkeypatch, reg, engine_calls):
    from src import __version__

    _live(tmp_path, monkeypatch, reg)
    marker = tmp_path / repair.ATTEMPT_FILE
    marker.write_text(json.dumps({"schema": 1, "version": __version__, "attempts": repair.MAX_UNFINISHED_STARTS}), encoding="utf-8")
    _refused(tmp_path, reg, repair.plan(), "unfinished-starts")
    assert marker.exists(), "the refusal cleared the record that makes it"
    # another version's record is no reason: an update may have fixed what stopped it
    marker.write_text(json.dumps({"schema": 1, "version": "0.0.0-other", "attempts": 99}), encoding="utf-8")
    assert repair._unfinished_starts() == 0
    marker.write_text("not json", encoding="utf-8")
    assert repair._unfinished_starts() == 0


def test_a_drive_that_cannot_make_the_second_name_at_the_swap_leaves_the_live_file_alone_and_the_copy_is_removed(
    tmp_path, monkeypatch, reg, engine_calls
):
    live = _live(tmp_path, monkeypatch, reg)
    before = H.sha(live)
    real_link = os.link

    def link(src, dst, **kw):
        if ".damaged-" in str(dst):
            raise OSError(1, "Operation not permitted")
        return real_link(src, dst, **kw)

    monkeypatch.setattr(os, "link", link)
    with pytest.raises(repair.Declined) as caught:
        repair.run(repair.plan())
    assert caught.value.code == "no-hard-links"
    assert H.sha(live) == before, "the live file changed although the switch was refused"
    assert not list(tmp_path.glob("live.salvage-*")), "the finished copy and its sidecar outlived the refusal"
    assert not list(tmp_path.glob("live.damaged-*")), "a second name was left behind by the failed step"


# --------------------------------------------------------------------------- #
#  the repair
# --------------------------------------------------------------------------- #
def test_a_repair_keeps_the_damaged_file_under_a_dated_name_and_puts_a_clean_file_in_its_place(tmp_path, monkeypatch, reg, engine_calls):
    live = _live(tmp_path, monkeypatch, reg)
    for side in ("-wal", "-shm"):  # a leftover log the old engine had: it must never be replayed into the new file
        Path(str(live) + side).write_bytes(b"leftover")
    before = H.sha(live)
    ctx = _Ctx()
    report = repair.run(repair.plan(), ctx)
    assert report["outcome"] == "repaired" and report["kind"] == "repair"
    kept = _the_kept_file(tmp_path)
    assert report["kept_file"] == kept.name and kept.name.startswith("live.damaged-") and kept.suffix == ".db"
    assert H.sha(kept) == before, "the damaged file's bytes changed"
    assert os.stat(kept).st_ino != os.stat(live).st_ino, "the live name still points at the damaged file"
    assert not Path(str(live) + "-wal").exists() and not Path(str(live) + "-shm").exists(), "the old log is still there"
    assert salvage.check_copy(live) == (True, []), "the new file does not read clean"
    names = _names(tmp_path)
    assert not [n for n in names if ".partial" in n or n.endswith(".json") and "salvage" in n], names
    assert not (tmp_path / repair.ATTEMPT_FILE).exists(), "the attempt record outlived the repair"
    assert engine_calls == ["dispose", "dispose", "init_db", "after"] or engine_calls[0] == "dispose" and engine_calls[-2:] == ["init_db", "after"]
    # what was kept and what was not, in the record and in what the person is told
    lost = report["unreadable_ids"]
    readable = H.readable_ids(kept)
    assert lost > 0 and report["kept_rows"] > len(readable) and len(readable) < 700
    articles_now = H.rows_of(live, "articles")
    assert set(articles_now) == readable
    rec = reg.repairs()[-1]
    assert rec["state"] == "done" and rec["kept_file"] == kept.name and rec["kept_rows"] == report["kept_rows"]
    assert not reg.latched(FILE_CORPUS), "the latch of the replaced file outlived it"
    notes = [n for n in reg.notes() if n["kind"] == "repaired"]
    assert [n["frame"] for n in notes] == [damage.FRAME_REPAIRED, damage.FRAME_KEPT_UNTIL]
    assert notes[0]["vars"] == {"kept": report["kept_rows"], "lost": lost}
    # where the damaged file is, how big, and the day the app removes it (R129): the person is told all three
    assert notes[1]["vars"]["name"] == kept.name and notes[1]["vars"]["folder"] == str(tmp_path) and notes[1]["vars"]["size"] == damage._size_words(kept)
    assert notes[1]["vars"]["date"] == rec["kept_file_removal_after"][:10]
    assert datetime.fromisoformat(rec["kept_file_removal_after"]) - datetime.fromisoformat(rec["clean_at"]) == timedelta(days=repair.KEPT_COPY_DAYS)
    # the job row said what was happening, in keyed sentences
    assert repair.FRAME_COPYING in ctx.frames and repair.FRAME_CHECKING in ctx.frames and repair.FRAME_SWITCHING in ctx.frames
    assert "Anything the app saves waits" in ctx.lines[0]


def test_the_only_deletions_are_the_apps_own_scratch(tmp_path, monkeypatch, reg, engine_calls):
    live = _live(tmp_path, monkeypatch, reg)
    stale = [tmp_path / "live.salvage-20260101T000000Z.db.partial", tmp_path / "live.salvage-20260101T000000Z.db.partial-wal"]
    for p in stale:
        p.write_bytes(b"x")
    bystander = tmp_path / "live.damaged-20250101T000000Z.db"  # an earlier repair's kept file: never touched
    bystander.write_bytes(b"an earlier damaged file")
    repair.run(repair.plan())
    assert not any(p.exists() for p in stale), "a stale partial copy outlived the next start of the repair"
    assert bystander.read_bytes() == b"an earlier damaged file", "an earlier kept file was touched"
    assert len(list(tmp_path.glob("live.damaged-*"))) == 2
    assert live.exists()


def test_two_repairs_in_the_same_second_never_share_a_name(tmp_path, monkeypatch):
    target = tmp_path / "live.db"
    first = repair._damaged_name(target, "20261006T000000Z")
    first.write_bytes(b"1")
    second = repair._damaged_name(target, "20261006T000000Z")
    assert first != second and second.name == "live.damaged-20261006T000000Z-2.db"
    second.write_bytes(b"2")
    assert repair._damaged_name(target, "20261006T000000Z").name == "live.damaged-20261006T000000Z-3.db"


def test_a_second_name_that_belongs_to_a_different_file_is_never_overwritten(tmp_path, monkeypatch, reg, engine_calls):
    _live(tmp_path, monkeypatch, reg)
    work = repair.plan()
    monkeypatch.setattr(repair, "_damaged_name", lambda target, stamp: tmp_path / "live.damaged-fixed.db")
    (tmp_path / "live.damaged-fixed.db").write_bytes(b"somebody else's file")
    with pytest.raises(FileExistsError):
        repair.run(work)
    assert (tmp_path / "live.damaged-fixed.db").read_bytes() == b"somebody else's file"


def test_the_post_swap_steps_are_said_and_a_failed_one_does_not_undo_the_repair(tmp_path, monkeypatch, reg):
    from src.database import session

    _live(tmp_path, monkeypatch, reg)
    monkeypatch.setattr(session, "dispose_engine", lambda: None)
    monkeypatch.setattr(session, "init_db", lambda: None)
    monkeypatch.setattr(repair, "_after_the_swap", lambda: {"corpus_epoch": None, "source_counts_cleared": None})
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["post_steps"] == {"corpus_epoch": None, "source_counts_cleared": None}


# --------------------------------------------------------------------------- #
#  the attempt record
# --------------------------------------------------------------------------- #
def test_the_attempt_is_armed_for_the_length_of_the_repair_and_cleared_when_it_ends(tmp_path, monkeypatch, reg, engine_calls):
    _live(tmp_path, monkeypatch, reg)
    marker = tmp_path / repair.ATTEMPT_FILE
    seen: dict[str, object] = {}
    real_run = salvage.Salvage.run

    def spy(self):
        seen["armed"] = json.loads(marker.read_text(encoding="utf-8"))["attempts"]
        return real_run(self)

    monkeypatch.setattr(salvage.Salvage, "run", spy)
    repair.run(repair.plan())
    assert seen["armed"] == 1 and not marker.exists()


def test_a_failed_repair_clears_the_record_and_is_tried_again_at_the_next_start(tmp_path, monkeypatch, reg, engine_calls):
    live = _live(tmp_path, monkeypatch, reg)
    before = H.sha(live)

    def boom(self):
        raise salvage.SalvageFailed("table articles", "OperationalError: disk I/O error")

    monkeypatch.setattr(salvage.Salvage, "run", boom)
    with pytest.raises(salvage.SalvageFailed):
        repair.run(repair.plan())
    assert H.sha(live) == before and not (tmp_path / repair.ATTEMPT_FILE).exists()
    rec = reg.repairs()[-1]
    assert rec["state"] == "failed" and rec["reason"] == "copy-failed" and "disk I/O error" in rec["failure"]
    assert [n["frame"] for n in reg.notes() if n["kind"] == "repair"] == [damage.FRAME_REPAIR_FAILED]
    assert not list(tmp_path.glob("live.salvage-*")), "a failed copy left its scratch behind"
    assert engine_calls == []


def test_a_quit_during_the_repair_gives_the_attempt_back_and_a_second_quit_clears_it(tmp_path, monkeypatch, reg):
    marker = tmp_path / repair.ATTEMPT_FILE
    repair._arm(2)
    assert json.loads(marker.read_text(encoding="utf-8"))["attempts"] == 2
    repair.stop()
    assert json.loads(marker.read_text(encoding="utf-8"))["attempts"] == 1 and repair._CANCEL.is_set()
    repair._reset_for_tests()
    repair._arm(1)
    repair.stop()
    assert not marker.exists(), "a quit of a first attempt left a record that counts as an unfinished start"
    repair._reset_for_tests()
    repair.stop()  # never armed: nothing to give back and nothing raised
    assert not marker.exists()


def test_a_stop_ends_the_copy_at_its_next_batch_and_changes_nothing(tmp_path, monkeypatch, reg, engine_calls):
    live = _live(tmp_path, monkeypatch, reg)
    before = H.sha(live)
    real = salvage.Salvage.run

    def stopping(self):
        repair.stop()
        return real(self)

    monkeypatch.setattr(salvage.Salvage, "run", stopping)
    work = repair.plan()
    repair._CANCEL.clear()
    report = repair.run(work)
    assert report["outcome"] == "stopped" and H.sha(live) == before
    assert not list(tmp_path.glob("live.salvage-*")) and not list(tmp_path.glob("live.damaged-*"))
    assert reg.repairs()[-1]["state"] == "stopped"
    assert engine_calls == []


# --------------------------------------------------------------------------- #
#  a cut between the steps
# --------------------------------------------------------------------------- #
def _cut_before_the_replace(monkeypatch):
    from src.backup import merge

    real = merge._replace_live_corpus

    def cut(*a, **kw):
        raise OSError(5, "the power went out")

    monkeypatch.setattr(merge, "_replace_live_corpus", cut)
    return real


def test_a_cut_before_the_replace_is_finished_at_the_next_start_with_the_same_second_name(tmp_path, monkeypatch, reg, engine_calls):
    from src.backup import merge

    live = _live(tmp_path, monkeypatch, reg)
    real_replace = _cut_before_the_replace(monkeypatch)
    before_cut = H.sha(live)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    assert H.sha(live) == before_cut, "the live file changed before the replace"
    sidecars = list(tmp_path.glob("live.salvage-*.db.json"))
    finished = list(tmp_path.glob("live.salvage-*.db"))
    assert len(sidecars) == 1 and len(finished) == 1, _names(tmp_path)
    kept_before = _the_kept_file(tmp_path)
    # the copy first read clean at the FIRST start (R129's clock): a later start that finishes the swap must not restart the 30 days
    doc = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert doc["clean_at"], "the first start's clean read was not written into the sidecar"
    doc["clean_at"] = "2026-09-01T00:00:00+00:00"
    sidecars[0].write_text(json.dumps(doc), encoding="utf-8")
    # the next start: no new check has run (confirmed damage is this process's), the swap is resumed from the sidecar
    monkeypatch.setattr(merge, "_replace_live_corpus", real_replace)
    work = repair.plan()
    assert work["kind"] == "resume" and work["resume"]["doc"]["damaged"] == kept_before.name
    report = repair.run(work)
    assert report["outcome"] == "repaired" and report["resumed"] is True and report["kept_file"] == kept_before.name
    assert report["clean_at"] == "2026-09-01T00:00:00+00:00" and report["kept_file_removal_after"] == "2026-10-01T00:00:00+00:00", (
        "the thirty days run from the first clean read, not from the start that finished the swap"
    )
    assert _the_kept_file(tmp_path) == kept_before, "a resumed swap made a second kept file"
    assert salvage.check_copy(live) == (True, [])
    assert not list(tmp_path.glob("live.salvage-*")), "the sidecar or the copy outlived the finished swap"
    assert report["kept_rows"] == work["resume"]["doc"]["kept_rows"], "the numbers of the first start were lost"


def test_a_copy_whose_source_was_written_to_since_is_discarded_and_a_fresh_one_is_made(tmp_path, monkeypatch, reg, engine_calls):
    from src.backup import merge

    live = _live(tmp_path, monkeypatch, reg)
    _cut_before_the_replace(monkeypatch)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    with open(live, "ab") as f:  # the damaged file is written to after the copy was made (a late save, a log folded in)
        f.write(b"\0" * 4096)
    monkeypatch.undo()  # the real replace is back; the registry and the hooks are set again below
    monkeypatch.setattr(damage, "registry", reg)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    monkeypatch.setattr(repair, "_marker_path", lambda: tmp_path / repair.ATTEMPT_FILE)
    from src.database import session

    monkeypatch.setattr(session, "dispose_engine", lambda: None)
    monkeypatch.setattr(session, "init_db", lambda: None)
    monkeypatch.setattr(repair, "_after_the_swap", lambda: {})
    work = repair.plan()
    assert work["kind"] == "repair", "a stale copy was resumed over a file that had been written to"
    assert not list(tmp_path.glob("live.salvage-*")), "the stale copy and its sidecar were not removed"
    assert merge is not None


def _sidecar_doc(live: Path, stamp: str, **over) -> dict:
    """A sidecar as ``_swap`` writes it, for a copy made at ``stamp``."""
    doc = {
        "schema": 1, "stamp": stamp, "finished": f"live.salvage-{stamp}.db", "damaged": f"live.damaged-{stamp}.db",
        "source": repair.fingerprint(live), "created_at": "2026-10-06T03:00:00+00:00", "kept_rows": 5, "unreadable_ids": 1,
        "open_ended": False, "copy_bytes": 10, "reconnects": 0, "tables": [], "clean_at": "2026-10-06T03:00:00+00:00",
        "page_size": 4096, "disk_unread_pages": 0, "disk_unread_first": [], "check_pages_unread": 0,
    }
    doc.update(over)
    return doc


def _write_sidecar(folder: Path, stamp: str, doc) -> Path:
    path = folder / f"live.salvage-{stamp}.db.json"
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def test_a_sidecar_nothing_matches_is_spent_and_is_removed(tmp_path, monkeypatch, reg):
    live = _live(tmp_path, monkeypatch, reg, damage_it=False)
    _write_sidecar(tmp_path, "20260101T000000Z", "not json")
    # its copy is not there and no second name of the damaged file exists: the swap never ran and never will
    _write_sidecar(tmp_path, "20260102T000000Z", _sidecar_doc(live, "20260102T000000Z"))
    assert repair.find_resumable(live) is None
    assert not list(tmp_path.glob("live.salvage-*")), "a spent sidecar outlived its swap"
    assert repair.snapshot()["late_sidecar"]["swapped"] is True


# --------------------------------------------------------------------------- #
#  a sidecar is an untrusted input (the deep read of E3, B3)
# --------------------------------------------------------------------------- #
_NOT_THE_KEPT_NAME = "live.db"


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(lambda live, stamp: {"finished": "live.db"}, id="finished-names-the-live-library"),
        pytest.param(lambda live, stamp: {"finished": "live.salvage-20260109T000000Z.db"}, id="finished-is-another-copy"),
        pytest.param(lambda live, stamp: {"finished": "../live.db"}, id="finished-leaves-the-folder"),
        pytest.param(lambda live, stamp: {"source": None}, id="source-is-null"),
        pytest.param(lambda live, stamp: {"source": {"size": 1}}, id="source-is-partial"),
        pytest.param(lambda live, stamp: {"source": {"size": "1", "mtime_ns": 1, "ino": 1, "wal": 0}}, id="source-is-not-numbers"),
        pytest.param(lambda live, stamp: {"damaged": _NOT_THE_KEPT_NAME}, id="damaged-names-the-live-library"),
        pytest.param(lambda live, stamp: {"damaged": "../elsewhere.damaged-20260102T000000Z.db"}, id="damaged-leaves-the-folder"),
        pytest.param(lambda live, stamp: {"schema": 2}, id="schema-is-another-version"),
        pytest.param(lambda live, stamp: {"schema": None}, id="schema-is-missing"),
    ],
)
def test_an_edited_sidecar_never_deletes_or_swaps_a_file_it_names(tmp_path, monkeypatch, reg, edit):
    live = _live(tmp_path, monkeypatch, reg, damage_it=False)
    before = H.sha(live)
    stamp = "20260102T000000Z"
    copy = tmp_path / f"live.salvage-{stamp}.db"
    copy.write_bytes(b"a finished copy")
    sidecar = _write_sidecar(tmp_path, stamp, {**_sidecar_doc(live, stamp), **edit(live, stamp)})
    assert repair.find_resumable(live) is None, "an edited sidecar was believed"
    assert repair.plan() is None
    assert live.exists() and H.sha(live) == before, "the live library was deleted or changed by what a sidecar said"
    assert not sidecar.exists(), "an untrusted sidecar was left to be read again"
    assert copy.exists(), "a file was deleted on the word of a sidecar that could not vouch for it"


def test_a_sidecar_that_names_a_symlink_as_its_copy_deletes_nothing(tmp_path, monkeypatch, reg):
    live = _live(tmp_path, monkeypatch, reg, damage_it=False)
    before = H.sha(live)
    stamp = "20260102T000000Z"
    link = tmp_path / f"live.salvage-{stamp}.db"
    try:
        link.symlink_to(live)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot make a symlink")
    _write_sidecar(tmp_path, stamp, _sidecar_doc(live, stamp))
    assert repair.find_resumable(live) is None
    assert live.exists() and H.sha(live) == before


def test_a_json_file_that_is_not_a_name_a_repair_gives_is_left_exactly_as_it_is(tmp_path, monkeypatch, reg):
    """The glob finds ``live.salvage-*.db.json``; a person's own ``live.salvage-notes.db.json`` matches it and is not this module's file.
    It is not believed AND not removed (a sidecar that FAILS is removed, a file that was never a sidecar is not touched)."""
    live = _live(tmp_path, monkeypatch, reg, damage_it=False)
    theirs = tmp_path / "live.salvage-notes.db.json"
    theirs.write_text('{"schema": 1, "my": "notes"}', encoding="utf-8")
    assert repair.find_resumable(live) is None
    assert repair.plan() is None
    assert theirs.exists() and theirs.read_text(encoding="utf-8") == '{"schema": 1, "my": "notes"}', "a file the app did not write was removed"


def test_a_scratch_name_must_be_the_apps_whole_pattern_before_it_is_deleted(tmp_path, monkeypatch, reg):
    live = _live(tmp_path, monkeypatch, reg, damage_it=False)
    mine = [tmp_path / "live.salvage-20260102T000000Z.db.partial", tmp_path / "live.salvage-20260102T000000Z.db.partial-wal"]
    not_mine = [tmp_path / "live.salvage-notes.db.partial", tmp_path / "live.salvage-20260102T000000Z.db.partial.bak"]
    for path in (*mine, *not_mine):
        path.write_bytes(b"x")
    assert repair._remove_scratch(live) == 2
    assert not any(p.exists() for p in mine) and all(p.exists() for p in not_mine), "a file the app did not make was removed"


# --------------------------------------------------------------------------- #
#  saves that sit in the log, and the swap that must not lose them (the deep read of E3, B2)
# --------------------------------------------------------------------------- #
_REAL_EMPTY_THE_LOG = repair._empty_the_log


def _engine_over(live: Path):
    from sqlalchemy import create_engine

    return create_engine("sqlite://", creator=lambda: H.open_store(live), future=True)


def _wal_save(live: Path, name: str):
    """A save the app made: committed into the write-ahead log of ``live`` through a connection that STAYS OPEN (a request's), so the
    log is not folded in when it closes. Returns that connection."""
    con = H.open_store(live)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("INSERT INTO sources (name, domain) VALUES (?, ?)", (name, name.replace(" ", "-") + ".example.org"))
    con.commit()
    return con


def _count_named(path: Path, name: str) -> int:
    con = H.open_store(path)
    try:
        return int(con.execute("SELECT count(*) FROM sources WHERE name = ?", (name,)).fetchone()[0])
    finally:
        con.close()


def test_the_log_is_folded_into_the_file_before_the_swap_and_a_log_that_stays_full_is_refused(tmp_path, monkeypatch, reg):
    import shutil

    live = _live(tmp_path, monkeypatch, reg, damage_it=False)
    engine = _engine_over(live)
    monkeypatch.setattr(repair, "_live_engine", lambda: engine)
    wal = Path(str(live) + "-wal")
    holder = _wal_save(live, "folded")
    try:
        assert wal.exists() and wal.stat().st_size > 0, "the test needs a save that sits in the log"
        _REAL_EMPTY_THE_LOG(live)
        assert not wal.exists() or wal.stat().st_size == 0, "the log still held saves after the fold"
        alone = tmp_path / "alone.db"
        shutil.copyfile(live, alone)  # the file with NO log beside it
        assert _count_named(alone, "folded") == 1, "the save was not in the file itself"
        # a reader that holds a snapshot keeps the newest saves in the log: refused, with the files as they are
        reader = H.open_store(live)
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM sources").fetchone()
        holder.execute("INSERT INTO sources (name, domain) VALUES ('later', 'later.example.org')")
        holder.commit()
        with pytest.raises(repair.Declined) as refusal:
            _REAL_EMPTY_THE_LOG(live)
        assert refusal.value.code == "writer-busy" and wal.stat().st_size > 0
        # the short wait the fold asked for is given back before the connection returns to the pool: a writer that gets it later waits
        again = engine.raw_connection()
        try:
            assert again.cursor().execute("PRAGMA busy_timeout").fetchone()[0] == 30000, "the fold left a short busy wait on a pooled connection"
        finally:
            again.close()
        reader.close()
    finally:
        holder.close()
        engine.dispose()


def test_a_log_that_does_not_exist_needs_no_fold(tmp_path, monkeypatch, reg):
    live = _live(tmp_path, monkeypatch, reg, damage_it=False)
    monkeypatch.setattr(repair, "_live_engine", lambda: (_ for _ in ()).throw(AssertionError("the engine was used for a log that is not there")))
    Path(str(live) + "-wal").unlink(missing_ok=True)
    _REAL_EMPTY_THE_LOG(live)


def test_the_identity_of_a_file_includes_its_log(tmp_path, monkeypatch, reg):
    """In WAL mode a commit leaves the file's size, time and inode alone: a copy "matches" a file that has been saved to unless the
    log is part of the identity."""
    live = _live(tmp_path, monkeypatch, reg, damage_it=False)
    switch = H.open_store(live)
    switch.execute("PRAGMA journal_mode=WAL")  # the one-time change of the file's mode writes the file itself
    switch.close()
    before = repair.fingerprint(live)
    assert before is not None and before["wal"] == 0
    holder = _wal_save(live, "saved")
    try:
        after = repair.fingerprint(live)
        assert {k: after[k] for k in ("size", "mtime_ns", "ino")} == {k: before[k] for k in ("size", "mtime_ns", "ino")}, (
            "the premise failed: the save changed the file itself"
        )
        assert after["wal"] > 0 and after != before
    finally:
        holder.close()


def test_a_copy_whose_source_was_saved_to_in_the_log_since_is_discarded_at_plan_time(tmp_path, monkeypatch, reg, engine_calls):
    live = _live(tmp_path, monkeypatch, reg)
    _cut_before_the_replace(monkeypatch)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    assert len(list(tmp_path.glob("live.salvage-*.db"))) == 1
    holder = _wal_save(live, "saved after the cut")
    try:
        work = repair.plan()
        assert work["kind"] == "repair", "a copy made before a save was resumed over it"
        assert not list(tmp_path.glob("live.salvage-*")), "the stale copy or its sidecar was left"
        assert not list(tmp_path.glob("live.damaged-*")), "the extra name the cut start made of the live file was left"
    finally:
        holder.close()


def test_a_resume_over_a_file_saved_to_between_the_decision_and_the_gate_is_refused_and_the_save_survives(
    tmp_path, monkeypatch, reg, engine_calls
):
    from src.backup import merge

    live = _live(tmp_path, monkeypatch, reg)
    real_replace = _cut_before_the_replace(monkeypatch)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    monkeypatch.setattr(merge, "_replace_live_corpus", real_replace)
    work = repair.plan()
    assert work["kind"] == "resume"
    holder = _wal_save(live, "saved after the decision")  # the save that the copy does not have
    engine = _engine_over(live)
    monkeypatch.setattr(repair, "_empty_the_log", _REAL_EMPTY_THE_LOG)
    monkeypatch.setattr(repair, "_live_engine", lambda: engine)
    try:
        with pytest.raises(repair.Declined) as refusal:
            repair.run(work)
        assert refusal.value.code == "copy-stale"
        assert not list(tmp_path.glob("live.salvage-*")), "the stale copy or its sidecar was left"
        assert not list(tmp_path.glob("live.damaged-*")), "the extra name of the live file was left"
        assert _count_named(live, "saved after the decision") == 1, "the save was lost under the older copy"
        assert reg.repairs()[-1]["state"] == "refused" and reg.repairs()[-1]["reason"] == "copy-stale"
    finally:
        holder.close()
        engine.dispose()


def test_a_repair_over_a_log_that_stays_full_is_refused_before_anything_is_named_or_linked(tmp_path, monkeypatch, reg, engine_calls):
    live = _live(tmp_path, monkeypatch, reg)
    engine = _engine_over(live)
    monkeypatch.setattr(repair, "_empty_the_log", _REAL_EMPTY_THE_LOG)
    monkeypatch.setattr(repair, "_live_engine", lambda: engine)
    holder = _wal_save(live, "pinned one")
    reader = H.open_store(live)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM sources").fetchone()
    holder.execute("INSERT INTO sources (name, domain) VALUES ('pinned two', 'two.example.org')")
    holder.commit()
    before = (H.sha(live), Path(str(live) + "-wal").stat().st_size)
    try:
        with pytest.raises(repair.Declined) as refusal:
            repair.run(repair.plan())
        assert refusal.value.code == "writer-busy"
        assert (H.sha(live), Path(str(live) + "-wal").stat().st_size) == before, "the refusal changed a file"
        assert not list(tmp_path.glob("live.damaged-*")) and not list(tmp_path.glob("live.salvage-*")), _names(tmp_path)
    finally:
        reader.close()
        holder.close()
        engine.dispose()


# --------------------------------------------------------------------------- #
#  an earlier process's finding is not this install's measurement (the deep read of E3, S1)
# --------------------------------------------------------------------------- #
def test_a_finished_copy_is_resumed_only_by_a_start_that_measured_the_damage_itself(tmp_path, monkeypatch, reg, engine_calls):
    _live(tmp_path, monkeypatch, reg)
    _cut_before_the_replace(monkeypatch)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    sidecar = next(tmp_path.glob("live.salvage-*.db.json"))
    other = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")  # the next process: it has measured nothing yet
    monkeypatch.setattr(damage, "registry", other)
    assert repair.plan() is None, "an earlier process's finding was acted on"
    assert sidecar.exists() and next(tmp_path.glob("live.salvage-*.db")).exists(), "a copy of a file that may still be damaged was thrown away"
    monkeypatch.setattr(damage, "registry", reg)  # a start that measured it
    assert repair.plan()["kind"] == "resume"


# --------------------------------------------------------------------------- #
#  a cut right after the replace (the deep read of E3, S2)
# --------------------------------------------------------------------------- #
def test_a_cut_right_after_the_replace_is_finished_at_the_next_start_with_a_record_and_the_follow_up_steps(
    tmp_path, monkeypatch, reg, engine_calls
):
    from src.database import library_generation

    live = _live(tmp_path, monkeypatch, reg)

    def die_after_the_replace() -> int:
        raise OSError(5, "the power went out")

    monkeypatch.setattr(library_generation, "bump", die_after_the_replace)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    kept = _the_kept_file(tmp_path)
    assert salvage.check_copy(live) == (True, []), "the switch had not run"
    assert list(tmp_path.glob("live.salvage-*.db.json")) and not list(tmp_path.glob("live.salvage-*.db")), "the cut is not the one under test"
    # the next process: no registry memory of the repair, no check of its own, the attempt marker the dead process left
    nxt = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", nxt)
    monkeypatch.undo()
    monkeypatch.setattr(damage, "registry", nxt)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    monkeypatch.setattr(repair, "_marker_path", lambda: tmp_path / repair.ATTEMPT_FILE)
    monkeypatch.setattr(repair, "_after_the_swap", lambda: engine_calls.append("after") or {"corpus_epoch": 1})
    repair._reset_for_tests()
    repair._write_marker(1)
    work = repair.plan()
    assert work["kind"] == "finish", work
    report = repair.run(work)
    assert report["outcome"] == "repaired" and report["kept_file"] == kept.name
    record = nxt.repairs()[-1]
    assert record["state"] == "done" and record["kept_file"] == kept.name and record["kept_file_ino"] == os.lstat(kept).st_ino
    assert record["kept_file_removal_after"], "the thirty days were never recorded: the kept file would never be removed or mentioned"
    assert "after" in engine_calls, "the corpus epoch and the source counts were never brought up to date"
    assert not (tmp_path / repair.ATTEMPT_FILE).exists(), "the attempt the cut start left behind was never cleared"
    assert not list(tmp_path.glob("live.salvage-*")), "the sidecar outlived the finished repair"
    assert _the_kept_file(tmp_path) == kept
    assert repair.plan() is None
    assert [n["frame"] for n in nxt.notes() if n["kind"] == "repaired"][-1] == damage.FRAME_KEPT_UNTIL


# --------------------------------------------------------------------------- #
#  durable before it is named (the deep read of E3, S7), and the counter moves (B1)
# --------------------------------------------------------------------------- #
def test_the_copy_is_made_durable_before_it_replaces_the_library_and_the_folder_after(tmp_path, monkeypatch, reg, engine_calls):
    from src.backup import merge

    _live(tmp_path, monkeypatch, reg)
    order: list[str] = []
    real_replace = merge._replace_live_corpus
    monkeypatch.setattr(repair, "_durable", lambda path: order.append("fsync-copy:" + ("copy" if ".salvage-" in path.name else path.name)))
    monkeypatch.setattr(repair, "_fsync_dir", lambda folder: order.append("fsync-dir"))
    monkeypatch.setattr(merge, "_replace_live_corpus", lambda *a, **kw: order.append("replace") or real_replace(*a, **kw))
    assert repair.run(repair.plan())["outcome"] == "repaired"
    assert order[:2] == ["fsync-copy:copy", "fsync-dir"], order  # the data first, then the folder entry of the copy's final name
    assert order.index("fsync-copy:copy") < order.index("replace"), order
    assert order[order.index("replace") + 1] == "fsync-dir", "the folder entries of the switch were not made durable"


def test_the_swap_moves_the_library_generation_after_the_replace(tmp_path, monkeypatch, reg, engine_calls):
    from src.database import library_generation

    _live(tmp_path, monkeypatch, reg)
    before = library_generation.current()
    assert repair.run(repair.plan())["outcome"] == "repaired"
    assert library_generation.current() == before + 1
    assert engine_calls.count("dispose") >= 3, "the pool was not let go again after the switch"


# --------------------------------------------------------------------------- #
#  the job: registered, a writer, and run by the boot step
# --------------------------------------------------------------------------- #
def test_the_job_is_registered_a_writer_and_not_cancellable_by_a_button():
    from src.api import jobs
    from src.jobs.background import BackgroundJob

    assert isinstance(repair.REPAIR_JOB, BackgroundJob) and repair.REPAIR_JOB.kind == repair.JOB_KIND == "repair-database"
    assert repair.JOB_KIND in jobs._DB_WRITER_KINDS
    assert repair.REPAIR_JOB.is_writer is True and repair.REPAIR_JOB.cancellable is False


def test_run_now_and_wait_runs_the_job_and_returns_what_happened(tmp_path, monkeypatch, reg, engine_calls):
    live = _live(tmp_path, monkeypatch, reg)
    assert repair.run_now_and_wait() == "repaired"
    snap = repair.snapshot()
    assert snap["outcome"] == "repaired" and snap["kept_file"].startswith("live.damaged-")
    assert salvage.check_copy(live) == (True, [])
    assert repair.REPAIR_JOB.status()["state"] == "done"


def test_a_refusal_through_the_job_is_declined_not_failed(tmp_path, monkeypatch, reg, engine_calls):
    _live(tmp_path, monkeypatch, reg)
    monkeypatch.setattr(repair, "_can_hard_link", lambda folder: False)
    assert repair.run_now_and_wait() == "declined"
    assert repair.snapshot()["reason"] == "no-hard-links"


def test_a_writer_that_does_not_go_quiet_refuses_and_names_it(tmp_path, monkeypatch, reg, engine_calls):
    from src.database import corpus_lease

    _live(tmp_path, monkeypatch, reg)
    monkeypatch.setattr(repair, "QUIESCE_S", 0.2)
    release, held = threading.Event(), threading.Event()

    def writer():
        with corpus_lease.corpus_lease("reindex"):
            held.set()
            release.wait(10)

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    assert held.wait(5)
    try:
        refusal = _refused(tmp_path, reg, repair.plan(), "writer-busy")
        assert "reindex" in refusal.detail
        assert [n["frame"] for n in reg.notes() if n["kind"] == "repair"] == [damage.FRAME_REPAIR_BUSY]
    finally:
        release.set()
        t.join(5)


# --------------------------------------------------------------------------- #
#  the sentences the person reads, one per state
# --------------------------------------------------------------------------- #
def test_the_notes_say_what_the_repair_is_doing_in_every_state(tmp_path, monkeypatch):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", reg)
    kept = tmp_path / "live.damaged-20261006T000000Z.db"
    kept.write_bytes(b"x" * 1_500_000)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (tmp_path / "live.db", "live.db"))
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)

    def frames():
        return [n["frame"] for n in reg.notes() if n["kind"] in ("repair", "repaired")]

    assert frames() == [], "nothing is said about a repair that is not wanted"
    reg._note_verified_damage(FILE_CORPUS, ["articles"], path=tmp_path / "live.db", at="2026-10-06T03:00:00+00:00")
    assert frames() == [damage.FRAME_REPAIR_NEXT_START], "a latched corpus says the repair happens at the next start"
    monkeypatch.setenv("OO_BOOT_REPAIR", "0")
    assert frames() == [], "the switch off must not promise a repair"
    monkeypatch.delenv("OO_BOOT_REPAIR")
    reg.repair_upsert("a", file=FILE_CORPUS, state="running")
    assert frames() == [damage.FRAME_REPAIRING]
    reg.repair_upsert("a", state="refused", reason="unfinished-starts")
    assert frames() == [damage.FRAME_REPAIR_UNFINISHED]
    reg.repair_upsert("a", state="failed", reason="copy-failed")
    assert frames() == [damage.FRAME_REPAIR_FAILED]
    reg.repair_upsert("a", state="done", reason=None, kept_file=kept.name, kept_rows=12345, unreadable_ids=7, folder=str(tmp_path))
    reg.retry(reason="replaced", files=(FILE_CORPUS,), file_replaced=True)
    done = [n for n in reg.notes() if n["kind"] == "repaired"]
    assert [n["frame"] for n in done] == [damage.FRAME_REPAIRED], "no removal date recorded: nothing is promised about one"
    assert done[0]["vars"] == {"kept": 12345, "lost": 7}
    reg.repair_upsert("a", open_ended=True, kept_file_removal_after="2026-11-05T03:00:00+00:00")
    done = [n for n in reg.notes() if n["kind"] == "repaired"]
    assert [n["frame"] for n in done] == [damage.FRAME_REPAIRED_OPEN, damage.FRAME_KEPT_UNTIL]
    assert done[1]["vars"] == {"name": kept.name, "size": damage._size_words(kept), "folder": str(tmp_path), "date": "2026-11-05"}
    reg.repair_upsert("a", kept_file_removal_refused="symlink")
    assert [n["frame"] for n in reg.notes() if n["kind"] == "repaired"][-1] == damage.FRAME_KEPT_NOT_REMOVED
    reg.repair_upsert("a", kept_file_removal_refused=None, kept_file_removed_at="2026-11-06T03:00:00+00:00", kept_file_removed_bytes=1_500_000)
    done = [n for n in reg.notes() if n["kind"] == "repaired"]
    assert [n["frame"] for n in done][-1] == damage.FRAME_KEPT_REMOVED
    assert done[-1]["vars"] == {"name": kept.name, "size": "1.5 MB", "date": "2026-11-06"}
    kept.unlink()  # gone from the folder (the app removed it, or the person did): no sentence says where it is kept
    assert [n["frame"] for n in reg.notes() if n["kind"] == "repaired"] == [damage.FRAME_REPAIRED_OPEN, damage.FRAME_KEPT_REMOVED]
    reg.repair_upsert("a", kept_file_removed_at=None)
    assert [n["frame"] for n in reg.notes() if n["kind"] == "repaired"] == [], "the person deleted it before the date: nothing is said about a file that is not there"


def test_the_repair_record_is_bounded_and_survives_a_restart(tmp_path):
    path = tmp_path / "database-damage.json"
    reg = DamageRegistry(path_fn=lambda: path)
    for i in range(damage.REPAIRS_KEEP + 5):
        reg.repair_upsert(f"r{i}", file=FILE_CORPUS, state="done", kept_file=f"x{i}.db")
    reg._flush_latest()
    again = DamageRegistry(path_fn=lambda: path)
    kept = again.repairs()
    assert len(kept) == damage.REPAIRS_KEEP and kept[-1]["id"] == f"r{damage.REPAIRS_KEEP + 4}"
    assert "kept_file" in json.dumps(json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
#  the encrypted file: the one every real operator has
# --------------------------------------------------------------------------- #
def test_an_encrypted_library_is_repaired_into_an_encrypted_file_and_the_passphrase_is_written_nowhere(
    tmp_path, monkeypatch, reg, engine_calls, key_held, caplog
):
    H.needs_sqlcipher()
    live = _live(tmp_path, monkeypatch, reg, encrypted=True, articles=500)
    before = H.sha(live)
    with caplog.at_level(logging.DEBUG):
        report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["encrypted"] is True
    from src.database import connect

    kept = _the_kept_file(tmp_path)
    assert H.sha(kept) == before, "the damaged file's bytes changed"
    assert connect.is_encrypted_file(live) and connect.is_encrypted_file(kept)
    assert salvage.check_copy(live) == (True, [])
    con = H.open_store(live, key=H.KEY)
    try:
        articles = con.execute("SELECT count(*) FROM articles").fetchone()[0]
        assert 400 <= articles <= 500 and articles <= report["kept_rows"], "the repaired library lost most of its articles"
    finally:
        con.close()
    blob = (
        json.dumps(repair.snapshot(), default=str)
        + json.dumps(reg.state(detail=True), default=str)
        + (tmp_path / "database-damage.json").read_text(encoding="utf-8")
        + caplog.text
    )
    assert H.KEY not in blob, "the passphrase reached a record, a snapshot or a log"
    assert b"Title 5 " not in live.read_bytes(), "article text was written in the clear"


def test_a_failed_repair_and_a_failed_step_after_the_switch_record_the_type_of_the_failure_never_its_text(
    tmp_path, monkeypatch, reg, caplog
):
    """The passphrase rule: the copy and the steps after the switch run on keyed connections, so what a driver says (and the error
    it was raised from, which a traceback prints) can carry a ``PRAGMA key`` statement; a record's traceback rides the diagnostics
    bundle. The repair's own record carries the driver's first line scrubbed; the log carries only the type."""
    import sqlite3

    from src.database import connect, session

    secret = "correct horse battery staple 8842"
    previous = connect.get_passphrase()
    connect.set_passphrase(secret)
    try:
        live = _live(tmp_path, monkeypatch, reg)
        before = H.sha(live)

        def driver_error():
            try:
                raise sqlite3.OperationalError(f"PRAGMA key = '{secret}' failed")
            except sqlite3.OperationalError as driver:
                raise RuntimeError("could not open the library") from driver

        def boom(self):
            driver_error()

        monkeypatch.setattr(salvage.Salvage, "run", boom)
        with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError):
            repair.run(repair.plan())
        assert H.sha(live) == before
        assert secret not in caplog.text and "PRAGMA key" not in caplog.text, caplog.text
        assert all(r.exc_info is None for r in caplog.records), "a traceback prints the error a driver's was raised from"
        assert "database repair failed (RuntimeError)" in caplog.text, caplog.text
        rec = reg.repairs()[-1]
        assert secret not in json.dumps(rec, default=str), "the repair's own record is scrubbed too"

        caplog.clear()
        monkeypatch.setattr(session, "session_scope", driver_error)
        with caplog.at_level(logging.DEBUG):
            out = repair._after_the_swap()
        assert out == {"corpus_epoch": None, "source_counts_cleared": None}
        assert secret not in caplog.text and "PRAGMA key" not in caplog.text, caplog.text
        assert all(r.exc_info is None for r in caplog.records)
        assert "the corpus epoch was not bumped (RuntimeError)" in caplog.text, caplog.text
        assert "the stored source counts were not cleared (RuntimeError)" in caplog.text, caplog.text
    finally:
        connect.set_passphrase(previous)


# --------------------------------------------------------------------------- #
#  a drive that could not read the damaged file: the copy is kept, never removed (the coordinator's ruling, 2026-10-06)
# --------------------------------------------------------------------------- #
class _FailingReads:
    """A file whose reads fail with EIO over the pages named (1-based, ``unit`` bytes each): a drive that fails cannot be made on
    demand, and the real file under it is read for everything else."""

    def __init__(self, real, bad_pages, unit):
        self._real, self._bad, self._unit, self._pos = real, set(bad_pages), unit, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._real.close()
        return False

    def seek(self, offset, *a):
        self._pos = offset
        return self._real.seek(offset, *a)

    def read(self, n=-1):
        first, last = self._pos // self._unit + 1, (self._pos + max(n, 1) - 1) // self._unit + 1
        if any(p in self._bad for p in range(first, last + 1)):
            raise OSError(5, "Input/output error")
        data = self._real.read(n)
        self._pos += len(data)
        return data


def _drive_fails_on(monkeypatch, pages, unit=4096):
    real_open = open
    monkeypatch.setattr(repair, "_raw_open", lambda path, mode="rb", **kw: _FailingReads(real_open(path, mode, **kw), pages, unit))


def test_the_raw_pass_counts_the_pages_the_drive_cannot_give_and_not_the_pages_that_are_merely_wrong(tmp_path, monkeypatch):
    path = tmp_path / "f.db"
    path.write_bytes(b"x" * (4096 * 9 + 100))  # nine pages and a short tail: ten pages
    cancel = threading.Event()
    assert repair._disk_unread_pages(path, 4096, cancel) == (0, []), "a clean read counted a page"
    path.write_bytes(b"\0" * (4096 * 9 + 100))  # a file full of nonsense reads fine: that is damage, SQLite's to name
    assert repair._disk_unread_pages(path, 4096, cancel) == (0, [])
    _drive_fails_on(monkeypatch, [3, 10])
    assert repair._disk_unread_pages(path, 4096, cancel) == (2, [3, 10]), "the first read is a whole-file chunk that fails and is read page by page"
    monkeypatch.setattr(repair, "RAW_CHUNK_BYTES", 8192)  # several chunks: the bad page costs its chunk, no more
    assert repair._disk_unread_pages(path, 4096, cancel) == (2, [3, 10])
    _drive_fails_on(monkeypatch, list(range(1, 11)))
    count, first = repair._disk_unread_pages(path, 4096, cancel)
    assert count == 10 and first == list(range(1, 9)), "the pages named are capped; the count is not"


def test_the_raw_pass_stops_when_the_app_does_and_a_file_that_cannot_be_opened_is_not_a_clean_read(tmp_path, monkeypatch):
    path = tmp_path / "f.db"
    path.write_bytes(b"x" * 8192)
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(salvage.SalvageStopped):
        repair._disk_unread_pages(path, 4096, stopped)

    def cannot_open(*a, **k):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(repair, "_raw_open", cannot_open)
    with pytest.raises(OSError):
        repair._disk_unread_pages(path, 4096, threading.Event())


def test_a_repair_of_a_file_the_drive_could_not_read_keeps_the_damaged_copy_with_no_date_and_says_to_check_the_drive(
    tmp_path, monkeypatch, reg, engine_calls
):
    live = _live(tmp_path, monkeypatch, reg)
    before = H.sha(live)
    _drive_fails_on(monkeypatch, [5, 6])
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["disk_unread_pages"] == 2 and report["disk_unread_first"] == [5, 6]
    kept = _the_kept_file(tmp_path)
    assert H.sha(kept) == before, "the damaged file's bytes changed"
    rec = reg.repairs()[-1]
    assert rec["kept_file_removal_withheld"] == "disk-read-failed" and rec["kept_file_disk_unread_pages"] == 2
    assert "kept_file_removal_after" not in rec, "a date was recorded for a file that is never removed"
    assert rec["disk_unread_pages"] == 2 and rec["check_pages_unread"] == 0
    notes = [n for n in reg.notes() if n["kind"] == "repaired"]
    assert [n["frame"] for n in notes] == [damage.FRAME_REPAIRED, damage.FRAME_KEPT_DISK], notes
    assert notes[1]["vars"] == {"name": kept.name, "size": damage._size_words(kept), "folder": str(tmp_path), "pages": 2}
    # a start any time later (a century on) removes nothing, and lists nothing
    far = datetime.now(UTC) + timedelta(days=36500)
    assert repair.sweep_kept_copies(now=far) == [] and kept.exists()
    assert "kept_file_removed_at" not in reg.repairs()[-1]
    assert repair._remove_kept_copy(reg.repairs()[-1], far) == {"outcome": "withheld", "reason": "disk-read-failed"} and kept.exists()


def test_pages_the_start_up_checks_page_pass_could_not_read_withhold_the_removal_even_when_the_raw_read_is_clean(
    tmp_path, monkeypatch, reg, engine_calls
):
    live = _live(tmp_path, monkeypatch, reg)
    work = repair.plan()
    assert work["pages_unread"] == 0
    work["pages_unread"] = 3  # what the check's page pass answered as "error reading ... page N" (counted apart from damage)
    report = repair.run(work)
    assert report["disk_unread_pages"] == 0 and report["check_pages_unread"] == 3
    rec = reg.repairs()[-1]
    assert rec["kept_file_removal_withheld"] == "disk-read-failed" and rec["kept_file_disk_unread_pages"] == 3
    assert "kept_file_removal_after" not in rec
    assert live.exists() and repair.sweep_kept_copies(now=datetime.now(UTC) + timedelta(days=36500)) == []


def test_a_clean_drive_still_sets_the_date_and_a_raw_pass_that_cannot_open_the_file_is_a_failed_repair_with_every_file_as_it_was(
    tmp_path, monkeypatch, reg, engine_calls
):
    live = _live(tmp_path, monkeypatch, reg)
    before = H.sha(live)

    def cannot_open(*a, **k):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(repair, "_raw_open", cannot_open)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    assert H.sha(live) == before and not list(tmp_path.glob("live.damaged-*")) and not list(tmp_path.glob("live.salvage-*"))
    rec = reg.repairs()[-1]
    assert rec["state"] == "failed" and rec["reason"] == "copy-failed"
    monkeypatch.setattr(repair, "_raw_open", open)
    work = repair.plan()
    assert work is not None, "the next start must try again"
    report = repair.run(work)
    assert report["outcome"] == "repaired" and report["disk_unread_pages"] == 0
    assert "kept_file_removal_withheld" not in reg.repairs()[-1] and reg.repairs()[-1]["kept_file_removal_after"]


def test_a_swap_finished_at_the_next_start_keeps_what_the_drive_said_at_the_first(tmp_path, monkeypatch, reg, engine_calls):
    from src.backup import merge

    live = _live(tmp_path, monkeypatch, reg)
    real_replace = _cut_before_the_replace(monkeypatch)
    _drive_fails_on(monkeypatch, [4])
    with pytest.raises(OSError):
        repair.run(repair.plan())
    sidecar = next(tmp_path.glob("live.salvage-*.db.json"))
    doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert doc["disk_unread_pages"] == 1 and doc["disk_unread_first"] == [4], "the sidecar did not carry the measurement"
    monkeypatch.setattr(repair, "_raw_open", open)  # the drive reads fine at the next start: the first start's word stands
    monkeypatch.setattr(merge, "_replace_live_corpus", real_replace)
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["resumed"] is True
    rec = reg.repairs()[-1]
    assert rec["kept_file_removal_withheld"] == "disk-read-failed" and rec["kept_file_disk_unread_pages"] == 1
    assert "kept_file_removal_after" not in rec and live.exists()


def test_a_sidecar_that_carries_no_measurement_is_measured_at_the_resume_and_never_taken_as_a_clean_read(
    tmp_path, monkeypatch, reg, engine_calls
):
    from src.backup import merge

    live = _live(tmp_path, monkeypatch, reg)
    real_replace = _cut_before_the_replace(monkeypatch)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    sidecar = next(tmp_path.glob("live.salvage-*.db.json"))
    doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert doc["disk_unread_pages"] == 0
    for key in ("disk_unread_pages", "disk_unread_first", "check_pages_unread"):
        doc.pop(key)
    sidecar.write_text(json.dumps(doc), encoding="utf-8")
    _drive_fails_on(monkeypatch, [2, 3])
    monkeypatch.setattr(merge, "_replace_live_corpus", real_replace)
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["disk_unread_pages"] == 2
    rec = reg.repairs()[-1]
    assert rec["kept_file_removal_withheld"] == "disk-read-failed" and rec["kept_file_disk_unread_pages"] == 2 and live.exists()
