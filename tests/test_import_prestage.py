"""Row 422 P1: the next corpus backup is staged while the one before it merges.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What may not regress:
  * the staging is the restore's own reader, started only once the item in flight is past its own staging (the two
    never compete for the disk), handed to the next item's restore, and removed on every path where it is not used;
  * the free-space preflight counts the merge in flight (its working copy and safety copy), and a staging that does
    not fit is DECLINED with the preflight's own words naming the space short; the item then stages at its own turn;
  * nothing about it can fail an import: a failed or declined staging leaves the item to stage as before;
  * a backup that would be skipped as already merged is not staged ahead; ``OO_IMPORT_PRESTAGE=0`` turns it off;
  * the stream reader stops between volumes when asked, and the restore job removes a staging it was handed and
    did not use.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.backup.import_queue import PRESTAGE_WHAT, ImportQueueManager


class _MergingVolumes:
    """A volume manager whose restore reports a few polls of 'merging' before it ends."""

    def __init__(self, polls: int = 6) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._polls = polls
        self._left = 0

    def start_restore(self, path, passphrase, **kw):
        self.calls.append((path, kw))
        self._left = self._polls
        return {}

    def status(self):
        if self._left > 0:
            self._left -= 1
            return {"state": "running", "progress": {"phase": "merging", "merge_step": 1}}
        return {"state": "done", "summary": {"report": {"plan": {}}}, "progress": {"phase": "done"}}

    def cancel(self):
        self._left = 0


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import src.backup.artifact as A
    import src.backup.merge as M
    import src.backup.stream_backup as SB
    import src.backup.volume_job as VJ
    import src.backup.volumes as V
    import src.scheduler.runner as R

    monkeypatch.setattr(R, "pause_for_exclusive_operation", lambda *a, **k: True)
    monkeypatch.setattr(R, "resume_after_exclusive_operation", lambda *a, **k: None)
    vols = _MergingVolumes()
    monkeypatch.setattr(VJ, "get_volume_manager", lambda: vols)
    monkeypatch.setattr(V, "load_manifest", lambda p: {"kind": SB.STREAM_KIND})
    monkeypatch.setattr(M, "artifact_source_digest", lambda p: f"digest-of-{Path(p).name}")
    monkeypatch.setattr(M, "find_completed_import", lambda d: None)
    reads: list[dict] = []
    cleaned: list[Path] = []

    def _read(src, pw, **kw):
        d = tmp_path / f"staged-{Path(src).name}"
        d.mkdir(exist_ok=True)
        reads.append({"src": str(src), **kw})
        return SimpleNamespace(staging_dir=d, stage_a_timings={})

    monkeypatch.setattr(A, "read_volume_backup", _read)
    monkeypatch.setattr(A, "cleanup_staging", lambda staged: cleaned.append(Path(staged.staging_dir)))
    monkeypatch.setattr(ImportQueueManager, "_merge_in_flight_reserve", staticmethod(lambda src: 123 << 20))
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    mgr._checkpoint_k = 1
    return SimpleNamespace(mgr=mgr, vols=vols, reads=reads, cleaned=cleaned, tmp=tmp_path)


def _drain(mgr, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if mgr.status()["state"] != "running":
            return mgr.status()
        time.sleep(0.02)
    raise AssertionError("queue never finished")


def _items(*names: str) -> list[dict]:
    return [{"kind": "corpus", "path": f"/b/{n}"} for n in names]


def test_the_next_backup_is_staged_under_the_merge_and_handed_to_its_restore(env):
    env.mgr.start(_items("1", "2", "3"), passphrase="pw")
    assert _drain(env.mgr)["state"] == "done"
    assert [c[0] for c in env.vols.calls] == ["/b/1", "/b/2", "/b/3"]
    assert "prestaged" not in env.vols.calls[0][1], "the first item stages itself"
    for path, kw in env.vols.calls[1:]:
        assert Path(kw["prestaged"].staging_dir).name == f"staged-{Path(path).name}"
    assert [r["src"] for r in env.reads] == ["/b/2", "/b/3"]
    for r in env.reads:
        assert r["reserve_bytes"] == 123 << 20 and r["reserve_what"] == PRESTAGE_WHAT
    notes = [it["summary"].get("prestage") for it in env.mgr._items]
    assert notes[0] is None and notes[1]["used"] is True and notes[2]["used"] is True
    assert env.cleaned == [], "a staging handed over is the restore's to remove"


def test_a_staging_that_does_not_fit_is_declined_with_the_space_named(env, monkeypatch):
    import src.backup.artifact as A

    def _short(src, pw, **kw):
        raise A.BackupSpaceError(
            f"Not enough free space for the {kw['reserve_what']}: needs about 9 GB, only 4 GB free at /data."
        )

    monkeypatch.setattr(A, "read_volume_backup", _short)
    env.mgr.start(_items("1", "2"), passphrase="pw")
    assert _drain(env.mgr)["state"] == "done"
    assert "prestaged" not in env.vols.calls[1][1], "declined: the item stages at its own turn"
    note = env.mgr._items[1]["summary"]["prestage"]
    assert note["used"] is False and note["reason"] == "space"
    assert "needs about 9 GB, only 4 GB free" in note["detail"] and PRESTAGE_WHAT in note["detail"]


def test_a_failed_staging_costs_nothing_and_names_no_detail(env, monkeypatch):
    import src.backup.artifact as A

    def _boom(src, pw, **kw):
        raise OSError(f"volume unreadable, passphrase {pw}")

    monkeypatch.setattr(A, "read_volume_backup", _boom)
    env.mgr.start(_items("1", "2"), passphrase="secret words")
    assert _drain(env.mgr)["state"] == "done"
    assert [c[0] for c in env.vols.calls] == ["/b/1", "/b/2"]
    note = env.mgr._items[1]["summary"]["prestage"]
    assert note == {"used": False, "reason": "failed"}
    assert "secret words" not in Path(env.tmp / "q.json").read_text(encoding="utf-8")


def test_a_stop_removes_a_staging_no_item_took(env):
    env.vols._polls = 10_000  # the first item merges until stopped
    env.mgr.start(_items("1", "2"), passphrase="pw")
    end = time.time() + 5
    while not env.reads and time.time() < end:
        time.sleep(0.02)
    assert env.reads, "the second backup was staged while the first merged"
    time.sleep(0.1)
    env.mgr.stop()
    _drain(env.mgr)
    assert [c[0] for c in env.vols.calls] == ["/b/1"]
    assert [p.name for p in env.cleaned] == ["staged-2"]
    from src.backup.stream_backup import _ACTIVE_STAGING

    assert not any("staged-2" in s for s in _ACTIVE_STAGING), "removed, it leaves the sweep's registry"


def test_an_already_merged_or_duplicate_backup_is_not_staged_ahead(env, monkeypatch):
    import src.backup.merge as M

    monkeypatch.setattr(M, "artifact_source_digest", lambda p: "same-digest")
    env.mgr.start(_items("1", "2"), passphrase="pw")
    _drain(env.mgr)
    assert env.reads == []
    assert env.mgr._items[1]["summary"]["prestage"] == {"used": False, "reason": "already-merged"}

    monkeypatch.setattr(M, "artifact_source_digest", lambda p: f"d-{p}")
    monkeypatch.setattr(M, "find_completed_import", lambda d: {"batch_id": 1})
    env.mgr.start(_items("3", "4"), passphrase="pw")
    _drain(env.mgr)
    assert env.reads == []


def test_the_switch_turns_it_off(env, monkeypatch):
    monkeypatch.setenv("OO_IMPORT_PRESTAGE", "0")
    env.mgr.start(_items("1", "2"), passphrase="pw")
    _drain(env.mgr)
    assert env.reads == [] and all("prestaged" not in kw for _p, kw in env.vols.calls)
    assert "prestage" not in env.mgr._items[1]["summary"]


@pytest.mark.parametrize("before", [{"phase": "reassembling"}, {"phase": "merging"}, {"phase": "prepare_staged"}])
def test_nothing_is_staged_before_the_item_in_flight_is_inside_its_merge(env, before):
    phase = {"now": before}

    def _status():
        if phase["now"] == "done":
            return {"state": "done", "summary": {"report": {}}, "progress": {"phase": "done"}}
        return {"state": "running", "progress": dict(phase["now"])}

    env.vols.status = _status  # type: ignore[method-assign]
    env.mgr.start(_items("1", "2"), passphrase="pw")
    time.sleep(0.6)
    assert env.reads == []
    phase["now"] = "done"
    _drain(env.mgr)


def test_only_a_corpus_item_next_in_line_is_staged(env):
    env.mgr.start(
        [{"kind": "corpus", "path": "/b/1"}, {"kind": "legacy", "path": "/b/x.oobak"},
         {"kind": "corpus", "path": "/b/2", "include_newsletters": False}],
        passphrase="pw",
    )
    _drain(env.mgr)
    assert env.reads == []


# --------------------------------------------------------------------------- #
# The reader and the restore job
# --------------------------------------------------------------------------- #
def _tiny_set(tmp: Path) -> Path:
    from src.backup.stream_backup import CorpusSource, MemberFile, _no_freeze, write_stream_backup

    corpus = tmp / "corpus.db"
    con = sqlite3.connect(corpus)
    con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, content TEXT)")
    con.executemany("INSERT INTO articles(content) VALUES(?)", [("x" * 3000,) for _ in range(300)])
    con.commit()
    con.close()
    side = tmp / "app_settings.json"
    side.write_text("{}", encoding="utf-8")
    dest = tmp / "dest"
    write_stream_backup(
        dest, "pw",
        corpus_source=CorpusSource(path=corpus, member_name="corpus.db", encrypted=False, freeze=_no_freeze),
        side_members=[MemberFile("app_settings.json", "state", side)], volume_size=65536,
    )
    return dest


def test_the_reader_stops_between_volumes_and_leaves_no_staging(tmp_path):
    from src.backup.stream_backup import read_stream_backup
    from src.backup.volumes import VolumeStopped

    dest = _tiny_set(tmp_path)
    root = tmp_path / "st"
    root.mkdir()
    with pytest.raises(VolumeStopped):
        read_stream_backup(dest, "pw", staging_root=root, include_merge_budget=False, should_stop=lambda: True)
    assert not any(root.iterdir())


def test_the_preflight_counts_the_reserve_and_names_it(tmp_path, monkeypatch):
    import src.backup.folder_backup as FB
    from src.backup.artifact import BackupSpaceError
    from src.backup.stream_backup import read_stream_backup

    dest = _tiny_set(tmp_path)
    root = tmp_path / "st"
    root.mkdir()
    monkeypatch.setattr(FB, "free_bytes", lambda p: 200 * 1024 * 1024)
    staged = read_stream_backup(dest, "pw", staging_root=root, include_merge_budget=False)  # fits on its own
    from src.backup.artifact import cleanup_staging

    cleanup_staging(staged)
    with pytest.raises(BackupSpaceError) as ei:
        read_stream_backup(
            dest, "pw", staging_root=root, include_merge_budget=False,
            reserve_bytes=1 << 30, reserve_what=PRESTAGE_WHAT,
        )
    assert PRESTAGE_WHAT in str(ei.value) and "free" in str(ei.value)


def test_the_restore_job_removes_a_staging_it_was_handed_and_did_not_use(tmp_path, monkeypatch):
    import src.backup.artifact as A
    from src.backup.volume_job import VolumeBackupManager

    removed: list[object] = []
    monkeypatch.setattr(A, "cleanup_staging", lambda s: removed.append(s))
    staged = SimpleNamespace(staging_dir=tmp_path / "pre")
    src = tmp_path / "set"
    src.mkdir()
    mgr = VolumeBackupManager()
    mgr.start_restore(str(src), "pw", prestaged=staged, _restore_fn=lambda p, pw: {"ok": True})
    end = time.time() + 5
    while mgr.status().get("state") == "running" and time.time() < end:
        time.sleep(0.02)
    assert removed == [staged]


def test_the_reserve_is_the_safety_copy_and_the_merges_growth(tmp_path, monkeypatch):
    import src.backup.sqlite_backup as SQ
    import src.backup.volumes as V

    live = tmp_path / "live.db"
    live.write_bytes(b"\0" * 4096)
    monkeypatch.setattr(SQ, "live_db_path", lambda: live)
    monkeypatch.setattr(V, "load_manifest", lambda p: {"members": [
        {"role": "corpus", "plaintext_bytes": 10_000}, {"role": "state", "plaintext_bytes": 7}]})
    assert ImportQueueManager._merge_in_flight_reserve(tmp_path) == 4096 + 10_000

    monkeypatch.setattr(V, "load_manifest", lambda p: {"members": []})
    assert ImportQueueManager._merge_in_flight_reserve(tmp_path) >= 1 << 60, "no corpus size known: nothing ahead"

    def _boom():
        raise OSError("unreadable")

    monkeypatch.setattr(SQ, "live_db_path", _boom)
    assert ImportQueueManager._merge_in_flight_reserve(tmp_path) >= 1 << 60, "an unknown size stages nothing ahead"
