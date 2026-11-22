"""Row 299 (R781): the repair on a WAL store, the mode the app's real library is always in.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before this row the swap hard-linked the live ``-wal`` beside the damaged file's second name. A cut after that link (a power cut
at the replace) left the name pointing at a log SQLite then recreated under a new inode, so every later start's resume met a
different file there and failed with a raw ``FileExistsError``: the repair could never finish. A copy discarded at plan time left
the empty log name behind. The ruling (R781, option A): the damaged copy is the folded main file ALONE, the log is never linked
and ``-shm`` never kept; "the log holds nothing that is not in the file" is checked at the moment of naming; an earlier start's
log name is removed only when it is exactly 0 bytes, a regular file and the app's own damaged-name pattern; anything else there is
left in place, untouched and named, and the repair finishes under the next free numbered name (the coordinator's accepted fallback).

Every store here is in WAL mode through the app's own connection pragmas (``src.database.session._sqlite_pragmas``: through
``tests/_app_engine.py::app_sqlite_engine`` for a plaintext file, on the keyed factory connection for an encrypted one), with a
save committed into the log by a connection that stays open, on both engine legs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.database import damage, repair, verify
from src.database.damage import FILE_CORPUS
from tests import damaged_store_helpers as H
from tests import test_repair as _repair_tests
from tests._app_engine import app_sqlite_engine
from tests.test_repair import (
    _REAL_EMPTY_THE_LOG,
    UNCLEAN,
    _count_named,
    _cut_before_the_replace,
    _spread,
)

# The repair tests' own fixtures: a damage registry of the test's own, the running app's engine as a recorder, the key held.
reg = _repair_tests.reg
engine_calls = _repair_tests.engine_calls
key_held = _repair_tests.key_held
pytestmark = pytest.mark.usefixtures("reg", "engine_calls")

LEGS = [pytest.param(False, id="plaintext"), pytest.param(True, id="sqlcipher")]


def _to_wal(live: Path, encrypted: bool) -> None:
    """Put ``live`` in the app's journal mode through the app's own pragmas, as every connection the app opens does."""
    from src.database.session import _sqlite_pragmas

    if encrypted:
        con = H.open_store(live)
        try:
            _sqlite_pragmas(con, None)
            assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            con.close()
        return
    engine = app_sqlite_engine(live)
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    finally:
        engine.dispose()


def _wal_live(tmp_path, monkeypatch, request, encrypted: bool) -> Path:
    """A damaged WAL store this process's check measured, with the real fold of the log (the shared fixture stubs it)."""
    if encrypted:
        request.getfixturevalue("key_held")
    live = tmp_path / "live.db"
    H.build_app_store(live, articles=700, encrypted=encrypted)
    _to_wal(live, encrypted)
    if encrypted:
        H.damage_encrypted_table(live, "articles", count=2, key=H.KEY)
    else:
        H.overwrite_pages(live, _spread(H.leaf_pages(live, "articles"), 2), H.PLAIN_PAGE)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True and verify.run_armed() is True
    monkeypatch.setattr(repair, "_empty_the_log", _REAL_EMPTY_THE_LOG)
    return live


def _pending(live: Path, name: str):
    """A save committed into the log by a connection that stays open (a request's), so it is not folded in at a close."""
    con = H.open_store(live)
    con.execute("INSERT INTO sources (name, domain) VALUES (?, ?)", (name, name.replace(" ", "-") + ".example.org"))
    con.commit()
    assert Path(str(live) + "-wal").stat().st_size > 0, "the premise failed: the save is not in the log"
    return con


def _damaged_names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.glob("live.damaged-*"))


def _finishes(live: Path, folder: Path, saved: str) -> dict:
    """The next start: the plan resumes the cut repair, which runs to completion with the save and leaves the damaged file alone."""
    work = repair.plan()
    assert work is not None and work["kind"] == "resume", work
    report = repair.run(work)
    assert report["outcome"] == "repaired" and report["resumed"] is True
    assert _count_named(live, saved) == 1, "a save that was in the log is not in the repaired file"
    names = _damaged_names(folder)
    assert len(names) == 1 and names[0].endswith(".db"), f"the damaged copy is the main file alone: {names}"
    assert _count_named(folder / names[0], saved) == 1, "the kept damaged file lost a save it had"
    assert not list(folder.glob("live.salvage-*")), "the copy or its sidecar outlived the finished swap"
    return report


@pytest.mark.parametrize("encrypted", LEGS)
def test_a_whole_repair_names_the_main_file_alone_and_keeps_every_save(tmp_path, monkeypatch, request, encrypted):
    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    holder = _pending(live, "pending in the log")
    try:
        report = repair.run(repair.plan())
    finally:
        holder.close()
    assert report["outcome"] == "repaired"
    assert _count_named(live, "pending in the log") == 1
    names = _damaged_names(tmp_path)
    assert names == [report["kept_file"]], f"a log or index name was made beside the damaged file: {names}"
    assert "kept_wal_ino" not in report and _count_named(tmp_path / names[0], "pending in the log") == 1


@pytest.mark.parametrize("encrypted", LEGS)
def test_a_cut_at_the_replace_resumes_to_completion_at_the_next_start(tmp_path, monkeypatch, request, encrypted):
    """The cut that left repair failing at every start: the live log names are removed and the replace never runs. SQLite then
    recreates the live log under a new inode; with no log name beside the damaged file nothing conflicts."""
    from src.backup import merge

    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    holder = _pending(live, "pending at the cut")
    real = _cut_before_the_replace(monkeypatch)
    try:
        with pytest.raises(OSError):
            repair.run(repair.plan())
    finally:
        holder.close()
    assert _count_named(live, "pending at the cut") == 1, "the cut lost the save"
    assert not list(tmp_path.glob("live.damaged-*-wal")) and not list(tmp_path.glob("live.damaged-*-shm"))
    monkeypatch.setattr(merge, "_replace_live_corpus", real)
    _finishes(live, tmp_path, "pending at the cut")


@pytest.mark.parametrize("encrypted", LEGS)
def test_a_cut_after_the_link_before_the_window_resumes_to_completion(tmp_path, monkeypatch, request, encrypted):
    from src.backup import merge

    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    holder = _pending(live, "pending at the link")
    real = merge.swap_in_corpus

    def cut(*a, **kw):
        raise OSError(5, "the power went out")

    monkeypatch.setattr(merge, "swap_in_corpus", cut)
    try:
        with pytest.raises(OSError):
            repair.run(repair.plan())
    finally:
        holder.close()
    assert len(_damaged_names(tmp_path)) == 1 and _count_named(live, "pending at the link") == 1
    monkeypatch.setattr(merge, "swap_in_corpus", real)
    _finishes(live, tmp_path, "pending at the link")


@pytest.mark.parametrize("encrypted", LEGS)
def test_a_cut_after_the_sidecar_before_any_name_resumes_to_completion(tmp_path, monkeypatch, request, encrypted):
    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    holder = _pending(live, "pending before the name")
    real = repair._durable

    def cut(path):
        raise OSError(5, "the power went out")

    monkeypatch.setattr(repair, "_durable", cut)
    try:
        with pytest.raises(OSError):
            repair.run(repair.plan())
    finally:
        holder.close()
    assert _damaged_names(tmp_path) == [] and list(tmp_path.glob("live.salvage-*.db.json"))
    monkeypatch.setattr(repair, "_durable", real)
    _finishes(live, tmp_path, "pending before the name")


@pytest.mark.parametrize("encrypted", LEGS)
def test_an_empty_log_name_an_earlier_start_left_is_removed_and_the_resume_finishes(tmp_path, monkeypatch, request, encrypted):
    """What the earlier code left after a cut: a 0-byte log under the damaged name. It is the app's own, empty: removed."""
    from src.backup import merge

    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    real = _cut_before_the_replace(monkeypatch)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    (damaged,) = [tmp_path / n for n in _damaged_names(tmp_path)]
    Path(str(damaged) + "-wal").write_bytes(b"")
    monkeypatch.setattr(merge, "_replace_live_corpus", real)
    holder = _pending(live, "saved before the resume")  # moves the live file: the cut copy is stale and made again
    holder.close()
    work = repair.plan()
    assert work["kind"] == "repair", "a copy whose source moved is not resumed"
    assert not Path(str(damaged) + "-wal").exists(), "the empty log name of the discarded start was left"
    report = repair.run(work)
    assert report["outcome"] == "repaired" and _count_named(live, "saved before the resume") == 1
    assert not list(tmp_path.glob("live.damaged-*-wal"))


@pytest.mark.parametrize("encrypted", LEGS)
def test_an_empty_log_name_beside_a_resumed_copy_is_removed_and_the_swap_finishes(tmp_path, monkeypatch, request, encrypted):
    from src.backup import merge

    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    holder = _pending(live, "pending at the cut")
    real = _cut_before_the_replace(monkeypatch)
    try:
        with pytest.raises(OSError):
            repair.run(repair.plan())
    finally:
        holder.close()
    (damaged,) = [tmp_path / n for n in _damaged_names(tmp_path)]
    Path(str(damaged) + "-wal").write_bytes(b"")  # the name the earlier code made of the live log
    monkeypatch.setattr(merge, "_replace_live_corpus", real)
    _finishes(live, tmp_path, "pending at the cut")


def _cut_at_the_replace_with_a_save(tmp_path, monkeypatch, request, encrypted, saved: str):
    """A repair cut at the replace with a save pending in the log; the next start resumes it. Returns the live file and the damaged name
    the cut start gave."""
    from src.backup import merge

    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    holder = _pending(live, saved)
    real = _cut_before_the_replace(monkeypatch)
    try:
        with pytest.raises(OSError):
            repair.run(repair.plan())
    finally:
        holder.close()
    monkeypatch.setattr(merge, "_replace_live_corpus", real)
    (damaged,) = [tmp_path / n for n in _damaged_names(tmp_path)]
    return live, damaged


def _repaired_frames(request) -> list[dict]:
    return [n for n in request.getfixturevalue("reg").notes() if n["kind"] in ("repaired", "repair")]


@pytest.mark.parametrize("what", ["frames", "symlink"])
@pytest.mark.parametrize("encrypted", LEGS)
def test_a_file_under_the_damaged_log_name_is_left_in_place_and_the_repair_finishes_under_a_free_name(
    tmp_path, monkeypatch, request, encrypted, what
):
    """The coordinator's accepted fallback: anything but an empty log under the damaged name is never removed, and the repair no longer
    refuses at every start for it: it finishes under the next free numbered name, and the notice says it finished and names both."""
    live, damaged = _cut_at_the_replace_with_a_save(tmp_path, monkeypatch, request, encrypted, "pending at the cut")
    log = Path(str(damaged) + "-wal")
    other = tmp_path / "elsewhere.bin"
    other.write_bytes(b"")
    frames = b"\x37\x7f\x06\x82" + b"\0" * 60
    if what == "frames":
        log.write_bytes(frames)  # a log that may hold frames: never removed
    else:
        log.symlink_to(other)  # an empty file reached through a link: never followed, never removed
    work = repair.plan()
    assert work["kind"] == "resume"
    report = repair.run(work)
    assert report["outcome"] == "repaired" and report["name_left_in_place"] == log.name
    kept = tmp_path / report["kept_file"]
    assert kept.name == damaged.name.replace(".db", "-2.db") and kept.is_file() and not kept.is_symlink()
    assert not os.path.lexists(damaged), "the old name was the live file's own second name and is gone"
    assert _count_named(live, "pending at the cut") == 1 and _count_named(kept, "pending at the cut") == 1
    if what == "frames":
        assert log.read_bytes() == frames and not log.is_symlink()
    else:
        assert log.is_symlink() and os.readlink(log) == str(other) and other.read_bytes() == b""
    assert not list(tmp_path.glob("live.salvage-*")), "the copy or its sidecar outlived the finished swap"
    notes = _repaired_frames(request)
    assert all(n["frame"] != damage.FRAME_REPAIR_FAILED for n in notes), notes
    (said,) = [n for n in notes if n["frame"] == damage.FRAME_KEPT_NAME_LEFT]
    assert said["vars"] == {"name": kept.name, "left": log.name}
    assert repair.plan() is None, "the next start has nothing left to do"


@pytest.mark.parametrize("encrypted", LEGS)
def test_a_different_file_under_the_damaged_main_name_is_left_in_place_and_the_repair_finishes(tmp_path, monkeypatch, request, encrypted):
    live, damaged = _cut_at_the_replace_with_a_save(tmp_path, monkeypatch, request, encrypted, "pending at the cut")
    damaged.unlink()  # the live file's own second name gone; somebody else's file under that name instead
    damaged.write_bytes(b"somebody else's file")
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["name_left_in_place"] == damaged.name
    assert damaged.read_bytes() == b"somebody else's file"
    assert report["kept_file"].endswith("-2.db") and _count_named(live, "pending at the cut") == 1


@pytest.mark.parametrize("encrypted", LEGS)
def test_the_free_name_search_is_bounded_and_claims_by_the_link(tmp_path, monkeypatch, request, encrypted):
    """No check-then-use gap: a name taken between the look and the link (here a link made while the sidecar is written) makes the
    link fail and the search move on; once the bound is reached the refusal names the file left in place, and nothing is switched."""
    live, damaged = _cut_at_the_replace_with_a_save(tmp_path, monkeypatch, request, encrypted, "pending at the cut")
    log = Path(str(damaged) + "-wal")
    log.write_bytes(b"\x37\x7f\x06\x82" + b"\0" * 60)
    decoy = tmp_path / "decoy.bin"
    decoy.write_bytes(b"decoy")
    real_write = repair._write_json_atomic

    def taken_meanwhile(path, doc):
        real_write(path, doc)
        name = tmp_path / doc["damaged"]
        if name != damaged and not os.path.lexists(name):
            name.symlink_to(decoy)  # somebody takes the candidate right after it was looked at

    monkeypatch.setattr(repair, "_write_json_atomic", taken_meanwhile)
    monkeypatch.setattr(repair, "_FREE_NAME_TRIES", 3)
    before = H.sha(live)
    with pytest.raises(repair.Declined) as refusal:
        repair.run(repair.plan())
    assert refusal.value.code == "damaged-name-taken" and log.name in str(refusal.value)
    assert H.sha(live) == before and decoy.read_bytes() == b"decoy"
    taken = sorted(p.name for p in tmp_path.glob("live.damaged-*") if p.is_symlink())
    assert len(taken) == 3 and all(os.readlink(tmp_path / n) == str(decoy) for n in taken), "a link was followed or overwritten"
    (sidecar,) = tmp_path.glob("live.salvage-*.db.json")
    doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert doc["damaged"] == damaged.name and "name_left_in_place" not in doc, "the next start names the file that blocked this one"
    notes = _repaired_frames(request)
    assert all(n["frame"] != damage.FRAME_KEPT_NAME_LEFT for n in notes)
    assert all(n["frame"] != damage.FRAME_REPAIR_FAILED for n in notes), notes


@pytest.mark.parametrize("encrypted", LEGS)
def test_a_save_in_the_window_after_a_fallback_leaves_no_unrecorded_second_name_of_the_library(tmp_path, monkeypatch, request, encrypted):
    """The name a fallback moved away from is recorded only in the sidecar. When the copy is then thrown away (a save landed in the
    window), that name goes with the new one, so no second name of the live library is left that no record knows of."""
    from src.backup import merge

    live, damaged = _cut_at_the_replace_with_a_save(tmp_path, monkeypatch, request, encrypted, "pending at the cut")
    log = Path(str(damaged) + "-wal")
    log.write_bytes(b"\x37\x7f\x06\x82" + b"\0" * 60)
    real = merge.swap_in_corpus

    def save_then_swap(finished, target, *, check, **kw):
        con = H.open_store(target)
        con.execute("INSERT INTO sources (name, domain) VALUES ('in the window', 'in-the-window.example.org')")
        con.commit()
        con.close()
        return real(finished, target, check=check, **kw)

    monkeypatch.setattr(merge, "swap_in_corpus", save_then_swap)
    with pytest.raises(repair.Declined) as refusal:
        repair.run(repair.plan())
    assert refusal.value.code == "saved-during-the-copy"
    assert sorted(p.name for p in tmp_path.glob("live.damaged-*")) == [log.name], "a second name of the library was left behind"
    assert log.read_bytes().startswith(b"\x37\x7f") and not list(tmp_path.glob("live.salvage-*"))
    assert _count_named(live, "in the window") == 1 and _count_named(live, "pending at the cut") == 1


@pytest.mark.parametrize("encrypted", LEGS)
def test_an_index_beside_the_damaged_name_is_left_in_place_too(tmp_path, monkeypatch, request, encrypted):
    live, damaged = _cut_at_the_replace_with_a_save(tmp_path, monkeypatch, request, encrypted, "pending at the cut")
    shm = Path(str(damaged) + "-shm")
    shm.write_bytes(b"not the repair's")
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["name_left_in_place"] == shm.name
    assert shm.read_bytes() == b"not the repair's" and report["kept_file"].endswith("-2.db")
    assert not os.path.lexists(damaged), "the old name, the kept file's own second name, is removed after the switch"
    assert _count_named(live, "pending at the cut") == 1


def test_an_empty_log_name_that_cannot_be_removed_is_left_in_place_and_the_repair_finishes(tmp_path, monkeypatch, request):
    """A Windows sharing violation on the empty leftover: never a raw error at every start; it is left where it is and named."""
    live, damaged = _cut_at_the_replace_with_a_save(tmp_path, monkeypatch, request, False, "pending at the cut")
    log = Path(str(damaged) + "-wal")
    log.write_bytes(b"")
    real_unlink = Path.unlink

    def held(self, *a, **kw):
        if self == log:
            raise PermissionError(13, "the file is in use")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", held)
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and report["name_left_in_place"] == log.name and log.exists()
    assert _count_named(live, "pending at the cut") == 1


def test_a_link_error_that_is_not_a_drive_without_links_keeps_the_finished_copy(tmp_path, monkeypatch, request):
    """A full folder or a read error at the link is not "this drive cannot hard-link": the finished copy and its sidecar stay, the
    refusal is named, and the next start finishes the switch."""
    import errno

    live, damaged = _cut_at_the_replace_with_a_save(tmp_path, monkeypatch, request, False, "pending at the cut")
    damaged.unlink()  # the earlier start's second name gone: this start must make it again
    from tests.os_scope import scope_os

    def full(src, dst, *a, **kw):
        raise OSError(errno.ENOSPC, "No space left on device")

    scope_os(monkeypatch, repair, link=full)  # the repair module's os only, never the whole process (R351)
    with pytest.raises(repair.Declined) as refusal:
        repair.run(repair.plan())
    assert refusal.value.code == "name-not-given"
    assert list(tmp_path.glob("live.salvage-*.db.json")) and len(list(tmp_path.glob("live.salvage-*.db"))) == 1
    scope_os(monkeypatch, repair, link=os.link)
    _finishes(live, tmp_path, "pending at the cut")


def test_a_name_left_in_place_with_control_or_format_characters_is_not_carried():
    for bad in ("a\u202eb.db-wal", "a\nb", "a/b", "..\\x", ""):
        report: dict = {}
        repair._carry_from(report, {"name_left_in_place": bad, "created_at": "2026-11-22T00:00:00+00:00"}, Path("/data/live.db"))
        assert "name_left_in_place" not in report, bad
    report = {}
    repair._carry_from(report, {"name_left_in_place": "live.damaged-20261122T010203Z.db-wal", "created_at": "2026-11-22T00:00:00+00:00"},
                       Path("/data/live.db"))
    assert report["name_left_in_place"] == "live.damaged-20261122T010203Z.db-wal"


def test_the_name_left_notice_is_said_only_while_the_kept_copy_is_there(tmp_path, monkeypatch):
    from src.database.damage import DamageRegistry

    reg = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", reg)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (tmp_path / "live.db", "live.db"))
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    kept = tmp_path / "live.damaged-20261006T000000Z-2.db"
    kept.write_bytes(b"x" * 1000)
    reg.repair_upsert("a", file=FILE_CORPUS, state="done", reason=None, kept_file=kept.name, kept_rows=5, unreadable_ids=0,
                      folder=str(tmp_path), name_left_in_place="live.damaged-20261006T000000Z.db-wal")

    def frames():
        return [n for n in reg.notes() if n["kind"] == "repaired"]

    (said,) = [n for n in frames() if n["frame"] == damage.FRAME_KEPT_NAME_LEFT]
    assert said["vars"] == {"name": kept.name, "left": "live.damaged-20261006T000000Z.db-wal"}
    kept.unlink()
    reg.repair_upsert("a", kept_file_removed_at="2026-11-06T00:00:00+00:00", kept_file_removed_bytes=1000)
    assert all(n["frame"] != damage.FRAME_KEPT_NAME_LEFT for n in frames()), "a removed copy is never said to be kept"


@pytest.mark.parametrize("encrypted", LEGS)
def test_the_old_shape_a_log_name_linked_to_the_live_log_never_loses_a_frame(tmp_path, monkeypatch, request, encrypted):
    """What the code before R781 left: the damaged log name hard-linked to the live log. When the live log is closed away the name keeps
    its frames (all of them already folded into the library file); it is left in place, and the repair still finishes."""
    from src.backup import merge

    live = _wal_live(tmp_path, monkeypatch, request, encrypted)

    def cut(*a, **kw):
        raise OSError(5, "the power went out")

    real = merge.swap_in_corpus
    monkeypatch.setattr(merge, "swap_in_corpus", cut)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    monkeypatch.setattr(merge, "swap_in_corpus", real)
    (damaged,) = [tmp_path / n for n in _damaged_names(tmp_path)]
    holder = _pending(live, "in the old log")
    os.link(str(live) + "-wal", str(damaged) + "-wal")  # the old code's second name of the live log
    held = Path(str(damaged) + "-wal").read_bytes()
    holder.close()  # SQLite folds the log in at the last close and removes ITS name; the second one keeps the frames
    report = repair.run(repair.plan())
    assert report["outcome"] == "repaired" and _count_named(live, "in the old log") == 1
    assert Path(str(damaged) + "-wal").read_bytes() == held, "the file that was left in place was changed"
    # The save moved the file, so the cut copy is discarded and a new one is made: the plan dropped the live file's own second name and
    # left the log name with its frames where it was; the new copy's damaged name is a free one, never beside that log.
    assert not os.path.lexists(damaged) and report["kept_file"] != damaged.name
    assert not os.path.lexists(tmp_path / (report["kept_file"] + "-wal"))


@pytest.mark.parametrize("encrypted", LEGS)
def test_a_held_reader_over_a_folded_log_does_not_stop_the_repair(tmp_path, monkeypatch, request, encrypted):
    """A reader keeps the log from being truncated, not from being folded: every frame is in the file, nothing is lost."""
    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    holder = _pending(live, "folded under a reader")
    reader = H.open_store(live)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM sources").fetchone()  # its snapshot includes every frame there is
        report = repair.run(repair.plan())
    finally:
        reader.close()
        holder.close()
    assert report["outcome"] == "repaired" and _count_named(live, "folded under a reader") == 1
    assert _damaged_names(tmp_path) == [report["kept_file"]]


@pytest.mark.parametrize("encrypted", LEGS)
def test_a_save_between_the_fold_and_the_swap_is_refused_and_survives(tmp_path, monkeypatch, request, encrypted):
    """The check at the moment of naming: a save that reached the log after the fold is not in the file, so nothing is named or
    switched, and the save is still in the live library."""
    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    holder = _pending(live, "before the fold")

    def fold_then_save(target, watch):
        _REAL_EMPTY_THE_LOG(target, watch)
        holder.execute("INSERT INTO sources (name, domain) VALUES ('after the fold', 'after-the-fold.example.org')")
        holder.commit()

    monkeypatch.setattr(repair, "_empty_the_log", fold_then_save)
    try:
        with pytest.raises(repair.Declined) as refusal:
            repair.run(repair.plan())
    finally:
        holder.close()
    assert refusal.value.code == "saved-during-the-copy"
    assert _damaged_names(tmp_path) == [], "a name was given to a file whose log held a save the copy does not have"
    assert _count_named(live, "after the fold") == 1 and _count_named(live, "before the fold") == 1
    # The next start: the copy that missed the save is discarded, a new one is made, and both saves are in the repaired library.
    monkeypatch.setattr(repair, "_empty_the_log", _REAL_EMPTY_THE_LOG)
    work = repair.plan()
    assert work is not None and work["kind"] == "repair", work
    report = repair.run(work)
    assert report["outcome"] == "repaired"
    assert _count_named(live, "after the fold") == 1 and _count_named(live, "before the fold") == 1
    assert _damaged_names(tmp_path) == [report["kept_file"]]


def test_the_name_left_in_place_notice_is_translated_into_every_language():
    files = sorted((Path(__file__).resolve().parent.parent / "src" / "static" / "locales").glob("*.json"))
    assert len(files) == 12
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data.get(damage.FRAME_KEPT_NAME_LEFT)
        assert entry, f"{path.name} has no translation of the notice"
        assert "{name}" in entry and "{left}" in entry, f"{path.name} lost a slot"
        assert data.get(damage.FRAME_REPAIR_NAME_TAKEN), f"{path.name} has no translation of the refusal"
        assert data.get(damage.FRAME_REPAIR_NOT_NAMED), f"{path.name} has no translation of the name-not-given refusal"


def test_the_damaged_name_pattern_is_the_repairs_own():
    target = Path("/data/corpus.db")
    assert repair._is_damaged_name(target, Path("/data/corpus.damaged-20261122T010203Z.db"))
    assert repair._is_damaged_name(target, Path("/data/corpus.damaged-20261122T010203Z-2.db"))
    for other in ("/data/corpus.damaged-x.db", "/data/other.damaged-20261122T010203Z.db", "/elsewhere/corpus.damaged-20261122T010203Z.db",
                  "/data/corpus.db", "/data/corpus.damaged-20261122T010203Z.db.bak"):
        assert not repair._is_damaged_name(target, Path(other)), other
