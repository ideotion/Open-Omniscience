"""R702: Settings -> Maintenance can rebuild an older library at the current storage settings (16 KiB pages, gradual space reclaim).

The rebuild copies the library with ``sqlcipher_export`` into a new file declared at the current settings, checks the copy, and
switches it in inside the same swap window a restore uses. These tests run it over REAL stores (encrypted and plaintext, with the
app's schema) and pin, one test each:

  * the new file opens through ``connect()`` with no page size given and reads 16384 / auto_vacuum 2, with every row;
  * the old file is kept under a dated second name with its bytes unchanged, until the operator removes it (Q-a, no auto-removal);
  * every refusal (no backup answer, nothing to change, no room, something else running) happens before a byte is copied and
    leaves every file as it was;
  * a stop during the copy and a save during the copy each leave the library as it was and no unfinished copy behind;
  * the unfinished copies a crash leaves are swept by name only, never while a rebuild runs;
  * the kept copies are listed with size and date, a link is never offered, and only a listed name is removed;
  * the panic wipe and the data-folder scope both know the two new names;
  * the passphrase appears in no report and no error.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from src.database import damage, rebuild, repair
from src.database.damage import FILE_CORPUS

from . import damaged_store_helpers as H


class _Ctx:
    stopping = False

    def __init__(self) -> None:
        self.frames: list[str] = []

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        if detail is not None:
            self.frames.append(getattr(detail, "i18n", str(detail)))


@pytest.fixture(autouse=True)
def _no_stale_shutdown_stop():
    """A shutdown test earlier in this worker can leave the repair's stop raised; the app's start clears it (``reset_for_start``),
    and so does this, so a rebuild here is not refused as an app that is shutting down. Seen only in the full suite, never alone."""
    from src.database import repair

    repair.reset_for_start()
    yield
    repair.reset_for_start()


@pytest.fixture()
def key_held():
    from src.database import connect

    previous = connect.get_passphrase()
    connect.set_passphrase(H.KEY)
    yield H.KEY
    connect.set_passphrase(previous)


@pytest.fixture()
def no_key():
    from src.database import connect

    previous = connect.get_passphrase()
    connect.set_passphrase(None)
    yield
    connect.set_passphrase(previous)


@pytest.fixture()
def engine(monkeypatch):
    """The running app's engine is a recorder: the switch's file work is what is under test, not the pool."""
    from src.database import session

    calls: list[str] = []
    monkeypatch.setattr(session, "dispose_engine", lambda: calls.append("dispose"))
    monkeypatch.setattr(session, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(rebuild, "_kv_invalidate", lambda: calls.append("kv"))
    monkeypatch.setattr(rebuild, "_others_running", lambda: [])
    rebuild._record({})
    return calls


def _live(tmp_path: Path, monkeypatch, *, encrypted: bool, page: int | None = 4096, articles: int = 250) -> Path:
    live = tmp_path / "live.db"
    H.build_app_store(live, articles=articles, encrypted=encrypted, cipher_page_size=page if encrypted else None)
    if page is not None and page != 16384:
        (_set_plain_settings if not encrypted else _set_old_auto_vacuum)(live, page)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    return live


def _set_plain_settings(path: Path, page: int) -> None:
    """A plaintext library made before the 16 KiB / incremental settings: page ``page``, auto_vacuum NONE."""
    import sqlite3

    c = sqlite3.connect(path)
    try:
        c.execute("PRAGMA journal_mode = DELETE")
        c.execute(f"PRAGMA page_size = {int(page)}")
        c.execute("PRAGMA auto_vacuum = 0")
        c.execute("VACUUM")
    finally:
        c.close()


def _set_old_auto_vacuum(path: Path, page: int) -> None:
    """An encrypted library made before incremental reclaim: auto_vacuum NONE (a VACUUM may change it, never the cipher page)."""
    from src.database.connect import connect

    c = connect(str(path), check_same_thread=False, timeout=30, cipher_page_size=page)
    try:
        c.execute("PRAGMA journal_mode = DELETE")
        c.execute("PRAGMA auto_vacuum = 0")
        c.execute("VACUUM")
    finally:
        c.close()


def _settings(path: Path) -> dict:
    from src.database.connect import connect

    c = connect(str(path), check_same_thread=False, timeout=30)  # no page size given: the file must open as it is
    try:
        return {
            "page_size": int(c.execute("PRAGMA page_size").fetchone()[0]),
            "auto_vacuum": int(c.execute("PRAGMA auto_vacuum").fetchone()[0]),
            "articles": c.execute("SELECT count(*) FROM articles").fetchone()[0],
            "check": c.execute("PRAGMA quick_check").fetchone()[0],
        }
    finally:
        c.close()


def _names(folder: Path) -> set[str]:
    return {p.name for p in folder.iterdir()}


def _frozen(folder: Path) -> dict[str, str]:
    return {p.name: H.sha(p) for p in folder.iterdir() if p.is_file() and not p.name.endswith((".json", "-shm"))}


# --------------------------------------------------------------------------- #
#  the rebuild itself
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("encrypted", [True, False], ids=["encrypted", "plaintext"])
def test_a_rebuild_gives_the_current_settings_keeps_every_row_and_keeps_the_old_file(tmp_path, monkeypatch, key_held, engine, encrypted):
    if not encrypted:
        from src.database import connect

        connect.set_passphrase(None)
    live = _live(tmp_path, monkeypatch, encrypted=encrypted)
    before = _settings(live)
    assert before["page_size"] == 4096 and before["auto_vacuum"] == 0, before
    old_sha = H.sha(live)

    ctx = _Ctx()
    report = rebuild.run("have_backup", ctx)

    assert report["outcome"] == "rebuilt", report
    after = _settings(live)
    assert after == {"page_size": 16384, "auto_vacuum": 2, "articles": before["articles"], "check": "ok"}
    kept = live.parent / report["kept_file"]
    assert kept.name.startswith("live.pre-rebuild-") and kept.name.endswith(".db")
    assert H.sha(kept) == old_sha, "the kept file must be the old library, byte for byte"
    assert not [n for n in _names(tmp_path) if ".rebuild-" in n], "no unfinished copy may stay behind"
    assert ctx.frames == [rebuild.FRAME_COPYING, rebuild.FRAME_CHECKING, rebuild.FRAME_SWITCHING]
    assert "init_db" in engine and engine.index("init_db") > engine.index("dispose")
    assert rebuild.last_report()["outcome"] == "rebuilt"
    assert H.KEY not in repr(report) and H.KEY not in repr(rebuild.status())
    from src.database.connect import is_encrypted_file

    assert is_encrypted_file(live) is encrypted and is_encrypted_file(kept) is encrypted, "encrypted at rest exactly as it was"


def test_the_status_says_what_would_change_and_lists_the_kept_copy(tmp_path, monkeypatch, key_held, engine):
    live = _live(tmp_path, monkeypatch, encrypted=True)
    st = rebuild.status()
    assert st["supported"] and st["needed"] is True and st["scope"] == "main library only"
    assert st["current"] == {"page_size": 4096, "auto_vacuum": 0} and st["target"] == {"page_size": 16384, "auto_vacuum": 2}
    assert st["kept_copies"] == []
    rebuild.run("no_backup_understood")
    st = rebuild.status()
    assert st["needed"] is False and st["current"] == st["target"]
    (only,) = st["kept_copies"]
    assert only["bytes"] == (live.parent / only["name"]).stat().st_size and only["made_at"].endswith("+00:00")
    assert st["preflight"]["kept_copies_bytes"] == only["bytes"], "a later rebuild's free-space check counts the kept copy (Q-a)"


# --------------------------------------------------------------------------- #
#  refusals: before a byte is copied, every file as it was
# --------------------------------------------------------------------------- #
def _refused(tmp_path: Path, answer: str, code: str) -> None:
    frozen = _frozen(tmp_path)
    with pytest.raises(rebuild.Declined) as caught:
        rebuild.run(answer)
    assert caught.value.code == code, caught.value.code
    assert _frozen(tmp_path) == frozen
    assert rebuild.last_report()["outcome"] == "declined"


@pytest.mark.parametrize("answer", ["", "yes", "HAVE_BACKUP"])
def test_without_a_backup_answer_nothing_starts(tmp_path, monkeypatch, key_held, engine, answer):
    _live(tmp_path, monkeypatch, encrypted=True)
    _refused(tmp_path, answer, "no-backup-answer")
    with pytest.raises(rebuild.Declined):
        rebuild.start(answer)


def test_a_library_that_already_has_the_settings_is_not_rebuilt(tmp_path, monkeypatch, key_held, engine):
    _live(tmp_path, monkeypatch, encrypted=True, page=16384)
    if _settings(tmp_path / "live.db")["auto_vacuum"] != 2:
        pytest.skip("a fresh store here is not made at the current settings")
    _refused(tmp_path, "have_backup", "nothing-to-change")


def test_no_room_refuses_with_the_figures(tmp_path, monkeypatch, key_held, engine):
    import shutil

    _live(tmp_path, monkeypatch, encrypted=True)
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10**12, 10**12 - 1000, 1000))
    _refused(tmp_path, "have_backup", "no-room")
    room = rebuild.last_report()["preflight"]
    assert room["sufficient"] is False and room["free_bytes"] == 1000 and room["needed_bytes"] > rebuild.MARGIN_BYTES


def test_another_job_running_refuses_and_names_it(tmp_path, monkeypatch, key_held, engine):
    _live(tmp_path, monkeypatch, encrypted=True)
    monkeypatch.setattr(rebuild, "_others_running", lambda: ["Importing a backup"])
    _refused(tmp_path, "have_backup", "busy")
    assert "Importing a backup" in rebuild.last_report()["reason_text"]


def test_a_folder_or_volume_backup_in_progress_counts_as_running(monkeypatch):
    from src.backup import folder_backup, volume_job

    class Busy:
        def status(self):
            return {"running": True}

    monkeypatch.setattr(folder_backup, "get_folder_manager", lambda: Busy())
    monkeypatch.setattr(volume_job, "get_volume_manager", lambda: Busy())
    assert {"a folder backup", "a volume backup or restore"} <= set(rebuild._others_running())


def test_a_manager_that_cannot_say_counts_as_running(monkeypatch):
    from src.backup import folder_backup

    def broken():
        raise RuntimeError("no")

    monkeypatch.setattr(folder_backup, "get_folder_manager", broken)
    assert "a folder backup" in rebuild._others_running()


# --------------------------------------------------------------------------- #
#  a stop, a save during the copy
# --------------------------------------------------------------------------- #
def test_a_stop_during_the_copy_leaves_the_library_as_it_was(tmp_path, monkeypatch, key_held, engine):
    live = _live(tmp_path, monkeypatch, encrypted=True)
    old = H.sha(live)
    ctx = _Ctx()
    ctx.stopping = True
    with pytest.raises(rebuild.Stopped):
        rebuild.run("have_backup", ctx)
    assert H.sha(live) == old and _settings(live)["page_size"] == 4096
    assert not [n for n in _names(tmp_path) if ".rebuild-" in n or ".pre-rebuild-" in n]
    assert rebuild.last_report()["outcome"] == "stopped"


def test_a_save_during_the_copy_switches_nothing(tmp_path, monkeypatch, key_held, engine):
    from src.database import connect as connect_mod

    live = _live(tmp_path, monkeypatch, encrypted=True)
    real = connect_mod.copy_at_current_settings

    def copy_then_save(src, dest, **kw):
        out = real(src, dest, **kw)
        c = connect_mod.connect(str(live), check_same_thread=False, timeout=30)  # a writer that went round the app's lock
        c.execute("UPDATE articles SET title = 'saved meanwhile' WHERE id = 1")
        c.commit()
        c.close()
        return out

    monkeypatch.setattr(connect_mod, "copy_at_current_settings", copy_then_save)
    with pytest.raises(rebuild.Declined) as caught:
        rebuild.run("have_backup")
    # The copy's own check sees the save first here (the full-text triggers changed a row count), and the swap's check is the
    # net beneath it: either refusal leaves the library as it was.
    assert caught.value.code in ("copy-check", "saved-during-the-copy"), rebuild.last_report().get("reason_text")
    assert _settings(live)["page_size"] == 4096
    assert not [n for n in _names(tmp_path) if ".rebuild-" in n or ".pre-rebuild-" in n], "the copy and the second name both go"


def test_a_save_after_the_check_is_caught_at_the_swap(tmp_path, monkeypatch, key_held, engine):
    from src.database import connect as connect_mod

    live = _live(tmp_path, monkeypatch, encrypted=True)
    real = rebuild._check_copy

    def check_then_save(copy, target):
        out = real(copy, target)
        c = connect_mod.connect(str(live), check_same_thread=False, timeout=30)
        c.execute("UPDATE sources SET name = 'saved meanwhile' WHERE id = 1")
        c.commit()
        c.close()
        return out

    monkeypatch.setattr(rebuild, "_check_copy", check_then_save)
    with pytest.raises(rebuild.Declined) as caught:
        rebuild.run("have_backup")
    assert caught.value.code == "saved-during-the-copy", rebuild.last_report().get("reason_text")
    assert _settings(live)["page_size"] == 4096
    assert not [n for n in _names(tmp_path) if ".rebuild-" in n or ".pre-rebuild-" in n]


def test_a_failure_is_reported_by_its_class_only(tmp_path, monkeypatch, key_held, engine):
    from src.database import connect as connect_mod

    live = _live(tmp_path, monkeypatch, encrypted=True)
    old = H.sha(live)

    def boom(src, dest, **kw):
        raise ValueError(f"PRAGMA key = '{H.KEY}'")

    monkeypatch.setattr(connect_mod, "copy_at_current_settings", boom)
    with pytest.raises(RuntimeError) as caught:
        rebuild.run("have_backup")
    assert "ValueError" in str(caught.value) and H.KEY not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert H.KEY not in repr(rebuild.last_report()) and H.sha(live) == old


# --------------------------------------------------------------------------- #
#  the copy primitive
# --------------------------------------------------------------------------- #
def test_the_copy_stopped_mid_way_leaves_no_file(tmp_path, monkeypatch, key_held):
    from src.database.connect import SnapshotStopped, copy_at_current_settings

    live = _live(tmp_path, monkeypatch, encrypted=True, articles=400)
    dest = tmp_path / "out.db"
    with pytest.raises(SnapshotStopped):
        copy_at_current_settings(live, dest, should_stop=lambda: True)
    assert not [n for n in _names(tmp_path) if n.startswith("out.db")]


def test_the_copy_refuses_a_missing_source(tmp_path, key_held):
    from src.database.connect import copy_at_current_settings

    with pytest.raises(FileNotFoundError):
        copy_at_current_settings(tmp_path / "absent.db", tmp_path / "out.db")
    assert not (tmp_path / "out.db").exists()


# --------------------------------------------------------------------------- #
#  unfinished copies and kept copies
# --------------------------------------------------------------------------- #
def test_unfinished_copies_are_swept_by_their_whole_name_only(tmp_path, monkeypatch, no_key):
    live = tmp_path / "live.db"
    live.write_bytes(b"x")
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    ours = ["live.rebuild-20261114T101010Z.db.partial", "live.rebuild-20261114T101010Z.db.partial-journal"]
    theirs = ["live.rebuild-20261114T101010Z.db", "other.rebuild-20261114T101010Z.db.partial", "live.rebuild-x.db.partial", "notes.partial"]
    for n in ours + theirs:
        (tmp_path / n).write_bytes(b"y")
        _age(tmp_path / n)
    young = "live.rebuild-20261116T101010Z.db.partial"
    (tmp_path / young).write_bytes(b"being written by a rebuild that started after the running check")
    assert rebuild.sweep_partials() == len(ours)
    assert _names(tmp_path) == {"live.db", young, *theirs}, "a partial younger than PARTIAL_MIN_AGE_S may be one being written"


def _age(path: Path) -> None:
    old = time.time() - rebuild.PARTIAL_MIN_AGE_S - 60
    os.utime(path, (old, old))


def test_no_sweep_while_a_rebuild_runs(tmp_path, monkeypatch, no_key):
    live = tmp_path / "live.db"
    live.write_bytes(b"x")
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    (tmp_path / "live.rebuild-20261114T101010Z.db.partial").write_bytes(b"y")
    monkeypatch.setattr(rebuild.REBUILD_JOB, "status", lambda: {"state": "running"})
    assert rebuild.sweep_partials() == 0 and len(_names(tmp_path)) == 2


def test_kept_copies_are_listed_a_link_never_and_only_a_listed_name_is_removed(tmp_path, monkeypatch, no_key):
    live = tmp_path / "live.db"
    live.write_bytes(b"x")
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    old = tmp_path / "live.pre-rebuild-20261101T080000Z.db"
    new = tmp_path / "live.pre-rebuild-20261114T080000Z.db"
    old.write_bytes(b"a" * 10)
    new.write_bytes(b"b" * 20)
    Path(str(new) + "-wal").write_bytes(b"w")
    elsewhere = tmp_path / "precious.txt"
    elsewhere.write_bytes(b"keep me")
    os.symlink(elsewhere, tmp_path / "live.pre-rebuild-20261113T080000Z.db")
    listed = rebuild.kept_copies()
    assert [k["name"] for k in listed] == [new.name, old.name], "newest first, the link left out"
    assert listed[0]["bytes"] == 20 and listed[0]["made_at"] == "2026-11-14T08:00:00+00:00"
    for name in ("live.pre-rebuild-20261113T080000Z.db", "live.db", "precious.txt", "../live.db", new.name + "-wal"):
        with pytest.raises(rebuild.Declined):
            rebuild.remove_kept_copy(name)
    assert rebuild.remove_kept_copy(new.name) == {"removed": new.name, "bytes": 20}
    assert not new.exists() and not Path(str(new) + "-wal").exists()
    assert elsewhere.read_bytes() == b"keep me" and live.exists() and old.exists()


# --------------------------------------------------------------------------- #
#  the panic wipe and the data-folder scope know the names
# --------------------------------------------------------------------------- #
def test_the_wipe_takes_the_rebuild_copies_and_the_kept_file(tmp_path):
    from src.safety.crypto_erase import _db_copies

    db = tmp_path / "open_omniscience.db"
    db.write_bytes(b"x")
    names = [
        "open_omniscience.pre-rebuild-20261114T101010Z.db",
        "open_omniscience.pre-rebuild-20261114T101010Z.db-wal",
        "open_omniscience.rebuild-20261114T101010Z.db.partial",
        "open_omniscience.rebuild-20261114T101010Z.db.partial-journal",
    ]
    for n in names:
        (tmp_path / n).write_bytes(b"y")
    (tmp_path / "thesis.pre-rebuild-20261114T101010Z.db").write_bytes(b"theirs")
    found = {p.name for p in _db_copies(tmp_path, tmp_path, [db])}
    assert found == set(names)


def test_the_data_folder_scope_owns_the_rebuild_names(tmp_path):
    from src.safety.data_scope import is_app_owned

    assert is_app_owned("open_omniscience.pre-rebuild-20261114T101010Z.db", lanes=())
    assert is_app_owned("open_omniscience.rebuild-20261114T101010Z.db.partial", lanes=())
    assert not is_app_owned("thesis.pre-rebuild-20261114T101010Z.db", lanes=())


# --------------------------------------------------------------------------- #
#  the routes
# --------------------------------------------------------------------------- #
def test_the_routes_refuse_without_an_answer_and_remove_only_a_listed_name(tmp_path, monkeypatch, no_key):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.database import router

    live = tmp_path / "live.db"
    live.write_bytes(b"x")
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    prefix = next(r.path for r in router.routes if r.path.endswith("/rebuild")).rsplit("/rebuild", 1)[0]
    assert client.post(prefix + "/rebuild", json={}).status_code == 400
    assert client.post(prefix + "/rebuild", json={"backup_answer": "sure"}).status_code == 400
    assert client.post(prefix + "/rebuild/remove-kept", json={"name": "live.db"}).status_code == 400, "no confirm, no removal"
    assert client.post(prefix + "/rebuild/remove-kept", json={"name": "live.db", "confirm": True}).status_code == 404
    assert live.exists()
    assert client.get(prefix + "/rebuild").json()["scope"] == "main library only"


def test_the_job_is_a_cancellable_writer():
    st = rebuild.REBUILD_JOB.status()
    assert st["kind"] == "rebuild-database" and st["cancellable"] is True
    assert rebuild.REBUILD_JOB.is_writer is True
    assert repair.corpus_path is not None


# --------------------------------------------------------------------------- #
#  the review's findings, one test each
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows cannot replace a file a handle holds: the test keeps a raw connection open across the switch on its own thread, which refuses it as writer-busy there (R741, row 145)",
)
def test_a_library_in_wal_mode_with_saves_in_its_log_is_rebuilt_with_them(tmp_path, monkeypatch, key_held, engine):
    from src.database.connect import connect

    live = _live(tmp_path, monkeypatch, encrypted=True)
    holder = connect(str(live), check_same_thread=False, timeout=30, cipher_page_size=4096)
    try:
        holder.execute("PRAGMA journal_mode = WAL")
        holder.execute("UPDATE sources SET name = 'only in the log' WHERE id = 1")
        holder.commit()
        assert Path(str(live) + "-wal").stat().st_size > 0, "the save must sit in the log when the rebuild starts"
        report = rebuild.run("have_backup")
    finally:
        holder.close()
    assert report["outcome"] == "rebuilt"
    c = connect(str(live), check_same_thread=False, timeout=30)
    try:
        assert c.execute("SELECT name FROM sources WHERE id = 1").fetchone()[0] == "only in the log"
        assert int(c.execute("PRAGMA page_size").fetchone()[0]) == 16384
    finally:
        c.close()


def test_a_stop_during_the_check_stops_before_the_switch(tmp_path, monkeypatch, key_held, engine):
    live = _live(tmp_path, monkeypatch, encrypted=True)
    old = H.sha(live)

    class StopAtCheck(_Ctx):
        def set_progress(self, *, done=None, total=None, detail=None) -> None:
            super().set_progress(done=done, total=total, detail=detail)
            if getattr(detail, "i18n", None) == rebuild.FRAME_CHECKING:
                self.stopping = True  # pressed while the copy is being checked

    ctx = StopAtCheck()
    with pytest.raises(rebuild.Stopped):
        rebuild.run("have_backup", ctx)
    assert rebuild.FRAME_SWITCHING not in ctx.frames
    assert H.sha(live) == old and not [n for n in _names(tmp_path) if "rebuild-" in n]


def test_a_refusal_or_a_stop_ends_the_job_with_its_report_not_an_error(tmp_path, monkeypatch, key_held, engine):
    _live(tmp_path, monkeypatch, encrypted=True)
    out = rebuild._worker(_Ctx(), backup_answer="")
    assert out["outcome"] == "declined" and out["reason"] == "no-backup-answer"
    ctx = _Ctx()
    ctx.stopping = True
    assert rebuild._worker(ctx, backup_answer="have_backup")["outcome"] == "stopped"


def test_the_status_opens_no_connection_while_a_rebuild_runs(tmp_path, monkeypatch, key_held):
    live = _live(tmp_path, monkeypatch, encrypted=True)
    (tmp_path / "live.rebuild-20261114T101010Z.db.partial").write_bytes(b"being written")

    def no(*a, **kw):
        raise AssertionError("a keyed connection was opened while the rebuild ran")

    monkeypatch.setattr(rebuild, "_settings_of", no)
    monkeypatch.setattr(rebuild.REBUILD_JOB, "status", lambda: {"state": "running", "kind": rebuild.JOB_KIND})
    st = rebuild.status()
    assert st["running"] is True and st["current"] is None
    assert (tmp_path / "live.rebuild-20261114T101010Z.db.partial").exists(), "the copy being written is not swept"
    assert live.exists()


def test_a_kept_name_that_is_the_live_library_or_not_a_real_date_is_not_offered(tmp_path, monkeypatch, no_key):
    live = tmp_path / "live.db"
    live.write_bytes(b"x")
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    os.link(live, tmp_path / "live.pre-rebuild-20261114T080000Z.db")  # a rebuild cut between the link and the swap
    (tmp_path / "live.pre-rebuild-20261399T999999Z.db").write_bytes(b"y")
    assert rebuild.kept_copies() == []
    assert rebuild.status()["kept_copies"] == []


def test_a_kept_copy_is_not_removed_while_a_rebuild_runs(tmp_path, monkeypatch, no_key):
    live = tmp_path / "live.db"
    live.write_bytes(b"x")
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    kept = tmp_path / "live.pre-rebuild-20261101T080000Z.db"
    kept.write_bytes(b"old")
    monkeypatch.setattr(rebuild.REBUILD_JOB, "status", lambda: {"state": "running"})
    with pytest.raises(rebuild.Running):
        rebuild.remove_kept_copy(kept.name)
    assert kept.exists()


def test_a_volume_export_or_restore_refuses_while_a_rebuild_runs(tmp_path, monkeypatch):
    from src.backup import volume_job

    monkeypatch.setattr(rebuild.REBUILD_JOB, "status", lambda: {"state": "running"})
    mgr = volume_job.VolumeBackupManager()
    for what in ("export", "import"):
        with pytest.raises(RuntimeError, match="rebuilt"):
            mgr._reap_or_reject(what)
    mgr._reap_or_reject("verify")  # a verification reads the backup files only


# --------------------------------------------------------------------------- #
#  the second read's findings (2026-11-16)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows cannot replace a file a handle holds: the test itself puts a file under the name the probe holds open, which cannot happen there",
)
def test_a_library_replaced_under_its_name_during_the_copy_is_not_switched_over(tmp_path, monkeypatch, key_held, engine):
    """Encrypt (or a restore) can put a NEW file under the library's name while the copy runs: the probe watches the old file
    and never moves, so the switch compares the file's identity with the one taken when the probe opened."""
    live = _live(tmp_path, monkeypatch, encrypted=True)
    real = rebuild._check_copy

    def check_then_replace(copy, target):
        out = real(copy, target)
        twin = tmp_path / "twin.db"
        shutil.copy2(live, twin)
        os.replace(twin, live)  # same bytes, a different file: what an encrypt-in-place swap leaves under the name
        return out

    monkeypatch.setattr(rebuild, "_check_copy", check_then_replace)
    replaced = H.sha(live)
    with pytest.raises(rebuild.Declined) as caught:
        rebuild.run("have_backup")
    assert caught.value.code == "replaced-during-the-copy", rebuild.last_report().get("reason_text")
    assert H.sha(live) == replaced and _settings(live)["page_size"] == 4096, "the file now under the name is left exactly as it is"
    assert not [n for n in _names(tmp_path) if ".rebuild-" in n or ".pre-rebuild-" in n]


def test_a_copy_not_encrypted_like_the_library_fails_its_check(tmp_path, monkeypatch, key_held):
    from src.database import connect as connect_mod

    live = _live(tmp_path, monkeypatch, encrypted=True)
    monkeypatch.setattr(connect_mod, "is_encrypted_file", lambda p: Path(p) == live)
    with pytest.raises(rebuild.Declined) as caught:
        rebuild._check_copy(tmp_path / "copy.db", live)
    assert caught.value.code == "copy-check" and "encrypted" in caught.value.detail


def test_a_library_whose_name_is_a_link_is_refused_before_anything_is_written(tmp_path, monkeypatch, key_held, engine):
    real = tmp_path / "elsewhere"
    real.mkdir()
    store = _live(real, monkeypatch, encrypted=True)
    link = tmp_path / "live.db"
    os.symlink(store, link)
    monkeypatch.setattr(damage, "_file_paths", lambda key: (link, link.name) if key == FILE_CORPUS else (None, None))
    before = _frozen(real)
    with pytest.raises(rebuild.Declined) as caught:
        rebuild.run("have_backup")
    assert caught.value.code == "library-is-a-link"
    assert link.is_symlink() and _frozen(real) == before and _names(tmp_path) == {"elsewhere", "live.db"}


def test_two_names_of_one_kept_file_are_listed_once(tmp_path, monkeypatch, no_key):
    live = tmp_path / "live.db"
    live.write_bytes(b"x")
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    first = tmp_path / "live.pre-rebuild-20261101T080000Z.db"
    first.write_bytes(b"a" * 10)
    os.link(first, tmp_path / "live.pre-rebuild-20261114T080000Z.db")
    assert [k["name"] for k in rebuild.kept_copies()] == [first.name], "one file, counted once, under its older name"


def test_encrypting_the_library_is_refused_while_a_rebuild_runs(monkeypatch):
    from fastapi import HTTPException

    from src.api import unlock

    monkeypatch.setattr(unlock, "app_lock_state", lambda: "unlocked-plaintext")
    monkeypatch.setattr(rebuild.REBUILD_JOB, "status", lambda: {"state": "running"})
    body = unlock.EncryptBody(passphrase="p" * 20, confirm="p" * 20, consent=True)
    with pytest.raises(HTTPException) as caught:
        unlock.encrypt_db(body)
    assert caught.value.status_code == 409 and "rebuilt" in caught.value.detail


def test_the_copy_keeps_its_temporary_data_in_memory(tmp_path, monkeypatch, key_held):
    """A sorter or temp table spilled to disk is plaintext whatever the key: the copy forces temp_store MEMORY on its connection."""
    from src.database import connect as connect_mod

    live = _live(tmp_path, monkeypatch, encrypted=True, articles=20)
    seen: list[str] = []
    real = connect_mod._export

    def export_and_look(conn, schema):
        seen.append(str(conn.execute("PRAGMA temp_store").fetchone()[0]))
        return real(conn, schema)

    monkeypatch.setattr(connect_mod, "_export", export_and_look)
    connect_mod.copy_at_current_settings(live, tmp_path / "copy.db")
    assert seen == ["2"], "temp_store 2 is MEMORY"


def test_the_copy_is_keyed_with_the_library_key_bound_not_written_into_the_statement(tmp_path, monkeypatch, key_held):
    """The ATTACH binds the key (CodeQL py/sql-injection on the old escaped literal): the copy opens with the same key, not
    with another, and no statement the copy runs carries the key's text."""
    import sqlcipher3.dbapi2 as sqc

    from src.database import connect as connect_mod

    live = _live(tmp_path, monkeypatch, encrypted=True, articles=20)
    statements: list[str] = []
    real_connect = connect_mod.connect

    class _Recording:  # the statement TEXT each call hands SQLite (a trace callback would show the bound values expanded)
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *args):
            statements.append(sql)
            return self._conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    def traced(*a, **kw):
        return _Recording(real_connect(*a, **kw))

    monkeypatch.setattr(connect_mod, "connect", traced)
    copy = tmp_path / "copy.db"
    connect_mod.copy_at_current_settings(live, copy)
    monkeypatch.setattr(connect_mod, "connect", real_connect)
    assert statements and not [s for s in statements if H.KEY in s], "the key's text is never in a statement"
    assert _settings(copy)["articles"] == 20, "the copy opens with the library's key"
    other = sqc.connect(str(copy))
    try:
        other.execute("PRAGMA key = 'not-the-key'")
        with pytest.raises(sqc.DatabaseError):
            other.execute("SELECT count(*) FROM sqlite_master").fetchone()
    finally:
        other.close()
