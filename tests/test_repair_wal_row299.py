"""Row 299 (R781): the repair on a WAL store, the mode the app's real library is always in.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before this row the swap hard-linked the live ``-wal`` beside the damaged file's second name. A cut after that link (a power cut
at the replace) left the name pointing at a log SQLite then recreated under a new inode, so every later start's resume met a
different file there and failed with a raw ``FileExistsError``: the repair could never finish. A copy discarded at plan time left
the empty log name behind. The ruling (R781, option A): the damaged copy is the folded main file ALONE, the log is never linked
and ``-shm`` never kept; "the log holds nothing that is not in the file" is checked at the moment of naming; an earlier start's
log name is removed only when it is exactly 0 bytes, a regular file and the app's own damaged-name pattern, and anything else
there is refused by name and kept.

Every store here is in WAL mode through the app's own connection pragmas (``src.database.session._sqlite_pragmas``: through
``tests/_app_engine.py::app_sqlite_engine`` for a plaintext file, on the keyed factory connection for an encrypted one), with a
save committed into the log by a connection that stays open, on both engine legs.
"""

from __future__ import annotations

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


@pytest.mark.parametrize("what", ["frames", "symlink"])
@pytest.mark.parametrize("encrypted", LEGS)
def test_anything_but_an_empty_log_under_the_damaged_name_is_refused_by_name_and_kept(tmp_path, monkeypatch, request, encrypted, what):
    from src.backup import merge

    live = _wal_live(tmp_path, monkeypatch, request, encrypted)
    real = _cut_before_the_replace(monkeypatch)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    (damaged,) = [tmp_path / n for n in _damaged_names(tmp_path)]
    log = Path(str(damaged) + "-wal")
    other = tmp_path / "elsewhere.bin"
    other.write_bytes(b"")
    if what == "frames":
        log.write_bytes(b"\x37\x7f\x06\x82" + b"\0" * 60)  # a log that may hold frames: never removed
    else:
        log.symlink_to(other)  # an empty file reached through a link: never followed, never removed
    monkeypatch.setattr(merge, "_replace_live_corpus", real)
    before = H.sha(live)
    for _start in range(2):  # the same clean, named refusal at each start, never a raw error
        work = repair.plan()
        assert work["kind"] == "resume"
        with pytest.raises(repair.Declined) as refusal:
            repair.run(work)
        assert refusal.value.code == "damaged-name-taken" and log.name in str(refusal.value)
    assert H.sha(live) == before and os.path.lexists(log) and other.exists()
    assert list(tmp_path.glob("live.salvage-*.db.json")), "the finished copy was thrown away"


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


def test_the_damaged_name_pattern_is_the_repairs_own():
    target = Path("/data/corpus.db")
    assert repair._is_damaged_name(target, Path("/data/corpus.damaged-20261122T010203Z.db"))
    assert repair._is_damaged_name(target, Path("/data/corpus.damaged-20261122T010203Z-2.db"))
    for other in ("/data/corpus.damaged-x.db", "/data/other.damaged-20261122T010203Z.db", "/elsewhere/corpus.damaged-20261122T010203Z.db",
                  "/data/corpus.db", "/data/corpus.damaged-20261122T010203Z.db.bak"):
        assert not repair._is_damaged_name(target, Path(other)), other
