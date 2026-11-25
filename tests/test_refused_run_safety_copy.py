"""R833 (row 426): an import refused before activation removes the safety copy it made itself, and only that one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.js_source_helper import python_function_source

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    import src.backup.merge as m
    import src.backup.own_net as own
    import src.backup.sqlite_backup as sb

    data = tmp_path / "data"
    data.mkdir()
    live = data / "corpus.db"
    con = sqlite3.connect(live)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    monkeypatch.setattr(own, "data_dir", lambda: data)
    monkeypatch.setattr(m, "data_dir", lambda: data)
    monkeypatch.setattr(sb, "live_db_path", lambda: live)
    monkeypatch.setattr(own, "_OWN", {})
    monkeypatch.setattr(m, "_NET_READ_BACK", {})
    monkeypatch.setattr(m, "_RUN_SNAPSHOT", None)
    try:
        yield data, live, con
    finally:
        con.close()


_n = [0]


def _make_net(data: Path, live: Path) -> Path:
    _n[0] += 1
    net = data / f"pre-restore-20261125T0000{_n[0]:02d}Z.db"
    shutil.copyfile(live, net)
    return net


def test_a_copy_made_and_never_activated_is_removed_when_the_corpus_is_unchanged(folder):
    from src.backup import own_net as own

    data, live, _con = folder
    net = _make_net(data, live)
    own.note_made(net)
    assert own.read_record()[net.name]["state"] == own.MADE
    out = own.remove_if_refused_before_activation(net)
    assert out["removed"] and out["message"] == own.REMOVED == "safety copy removed: the import was refused before any change"
    assert not net.exists() and net.name not in (own.read_record() or {})
    assert "destroyed" not in out["message"] and "wiped" not in out["message"]


def test_a_changed_corpus_keeps_the_copy(folder):
    from src.backup import own_net as own

    data, live, con = folder
    net = _make_net(data, live)
    own.note_made(net)
    con.execute("INSERT INTO t VALUES (2)")
    con.commit()
    out = own.remove_if_refused_before_activation(net)
    assert not out["removed"] and out["message"] == own.KEPT_CHANGED and net.exists()


def test_an_activated_copy_is_kept_even_with_an_unchanged_corpus(folder):
    from src.backup import own_net as own

    data, live, _con = folder
    net = _make_net(data, live)
    own.note_made(net)
    own.note_activation(net)
    assert own.read_record()[net.name]["state"] == own.ACTIVATED
    assert own.remove_if_refused_before_activation(net)["message"] == own.KEPT_NOT_OURS
    assert net.exists()


@pytest.mark.parametrize("damage", ["missing", "garbage", "activated"])
def test_a_record_that_does_not_say_made_reads_as_after_activation(folder, damage):
    from src.backup import own_net as own

    data, live, _con = folder
    net = _make_net(data, live)
    own.note_made(net)
    rec = data / own.RECORD_NAME
    if damage == "missing":
        rec.unlink()
    elif damage == "garbage":
        rec.write_text("{not json", encoding="utf-8")
    else:
        rec.write_text('{"%s": {"state": "activated"}}' % net.name, encoding="utf-8")
    out = own.remove_if_refused_before_activation(net)
    assert out["message"] == own.KEPT_ACTIVATED and net.exists()


def test_only_the_file_this_run_made_is_removed(folder):
    from src.backup import own_net as own

    data, live, _con = folder
    net = _make_net(data, live)
    other = _make_net(data, live)  # never recorded: never touched, whatever its name
    assert own.remove_if_refused_before_activation(other)["message"] == own.KEPT_NOT_OURS
    own.note_made(net)
    net.unlink()
    shutil.copyfile(live, net)  # a different file under the same name
    assert own.remove_if_refused_before_activation(net)["message"] == own.KEPT_NOT_THE_FILE
    assert net.exists() and other.exists()


def test_a_link_at_the_copys_name_is_never_followed(folder, tmp_path):
    from src.backup import own_net as own

    data, live, _con = folder
    net = _make_net(data, live)
    own.note_made(net)
    target = tmp_path / "elsewhere.db"
    net.rename(target)
    net.symlink_to(target)
    assert own.remove_if_refused_before_activation(net)["message"] == own.KEPT_NOT_THE_FILE
    assert target.exists() and net.is_symlink()


def test_three_refused_runs_in_a_row_leave_no_new_copy_and_the_space_check_still_passes(folder, monkeypatch):
    import src.backup.merge as m
    from src.backup.artifact import preflight_free_space

    data, live, _con = folder
    before = set(data.glob("pre-restore-*.db"))
    for token in (11, 12, 13):
        monkeypatch.setattr("src.scheduler.runner.exclusive_window_token", lambda t=token: t)
        preflight_free_space(data, live.stat().st_size * 2, what="restore")
        net = _make_net(data, live)
        m._own_net().note_made(net)
        m._NET_READ_BACK[str(net)] = True
        m._remember_run_snapshot(net)
        got = m.settle_run_safety_copy()
        assert got["safety_copy"]["removed"], got
        assert m._run_scoped_snapshot() is None
    assert set(data.glob("pre-restore-*.db")) == before
    assert m.settle_run_safety_copy()["leftovers"]["count"] == len(before)


def test_a_restart_after_a_refusal_keeps_the_copy_and_lists_it(folder, monkeypatch):
    from src.backup import own_net as own

    data, live, _con = folder
    net = _make_net(data, live)
    own.note_made(net)
    monkeypatch.setattr(own, "_OWN", {})  # a new process: nothing it made
    assert own.remove_if_refused_before_activation(net)["message"] == own.KEPT_NOT_OURS
    left = own.leftovers()
    assert left["count"] == 1 and left["bytes"] == net.stat().st_size and left["names"] == [net.name]


def test_a_lone_restore_refused_before_its_swap_removes_its_verified_copy(folder, monkeypatch):
    import src.backup.merge as m

    data, live, _con = folder
    monkeypatch.setattr("src.scheduler.runner.exclusive_window_token", lambda: 0)
    net = _make_net(data, live)
    m._own_net().note_made(net)
    m._NET_READ_BACK[str(net)] = True

    def _restore():
        m._NET_PENDING.net = net
        raise ValueError("refused before the swap")

    with pytest.raises(ValueError):
        m._settle_pending_net(_restore)()
    assert not net.exists()


def test_a_lone_restore_with_a_changed_corpus_keeps_its_copy(folder, monkeypatch):
    import src.backup.merge as m

    data, live, con = folder
    monkeypatch.setattr("src.scheduler.runner.exclusive_window_token", lambda: 0)
    net = _make_net(data, live)
    m._own_net().note_made(net)
    m._NET_READ_BACK[str(net)] = True
    con.execute("INSERT INTO t VALUES (3)")
    con.commit()

    def _restore():
        m._NET_PENDING.net = net
        return {"committed": False}

    m._settle_pending_net(_restore)()
    assert net.exists()


def test_the_state_never_holds_corpus_bytes(folder):
    from src.backup import own_net as own

    data, live, _con = folder
    net = _make_net(data, live)
    own.note_made(net)
    head = live.read_bytes()[:100]
    raw = (data / own.RECORD_NAME).read_bytes()
    assert head[:16] not in raw and head.hex()[:32] not in raw.decode()
    state = own.live_state()
    assert head.hex() not in repr(state) and head[:16].hex() not in repr(state)


def test_the_wiring_marks_activation_before_the_swap_and_settles_before_the_run_writes():
    src = (_ROOT / "src/backup/merge.py").read_text(encoding="utf-8")
    restore = python_function_source(src, "run_restore")
    assert restore.index("_own_net().note_activation(") < restore.index("_carry_and_swap(working, target, report)")
    assert "_own_net().note_made(snapshot)" in restore
    take = python_function_source(src, "_take_safety_net_with_the_copy")
    assert "_own_net().note_made(net)" in take
    q = (_ROOT / "src/backup/import_queue.py").read_text(encoding="utf-8")
    drive = python_function_source(q, "_drive")
    assert drive.index("self._settle_safety_copy()") < drive.index("self._tune_after_run()")
