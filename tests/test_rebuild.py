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
    assert rebuild.sweep_partials() == len(ours)
    assert _names(tmp_path) == {"live.db", *theirs}


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
    assert client.post(prefix + "/rebuild/remove-kept", json={"name": "live.db"}).status_code == 404
    assert live.exists()
    assert client.get(prefix + "/rebuild").json()["scope"] == "main library only"


def test_the_job_is_a_cancellable_writer():
    st = rebuild.REBUILD_JOB.status()
    assert st["kind"] == "rebuild-database" and st["cancellable"] is True
    assert rebuild.REBUILD_JOB.is_writer is True
    assert repair.corpus_path is not None
