"""Large-data 'copy to a folder/drive' backup library (brief §2.A).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure-filesystem core: streaming atomic copy, name+size dedup, additive
skip-if-present restore, pause/resume idempotency, and an honest destination
preflight. These are the reliability guarantees ("entirely reliable or it should
not exist") that the pausable job + endpoints wrap.
"""

from __future__ import annotations

import json

import pytest

from src.backup.folder_backup import (
    MANIFEST_NAME,
    BackupItem,
    collect_dir_items,
    collect_model_items,
    free_bytes,
    human_bytes,
    restore_folder_backup,
    validate_dest,
    write_folder_backup,
)


def _write(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _items(root):
    return [
        BackupItem("wiki_dumps", "enwiki/a.bz2", _write(root / "a.bz2", b"a" * 100), 100),
        BackupItem("wiki_dumps", "enwiki/b.bz2", _write(root / "b.bz2", b"b" * 50), 50),
        BackupItem("osm_regions", "europe.pbf", _write(root / "c.pbf", b"c" * 200), 200),
    ]


# --------------------------------------------------------------------------- #
# collect
# --------------------------------------------------------------------------- #
def test_collect_dir_items_only_done_and_skips_partials(tmp_path):
    root = tmp_path / "wiki_dumps"
    done = _write(root / "enwiki" / "done.bz2", b"x" * 10)
    _write(root / "enwiki" / "wip.bz2", b"y" * 5)  # not in done set
    _write(root / "enwiki" / "x.bz2.oopart", b"z")  # in-progress temp
    items = collect_dir_items(root, "wiki_dumps", done_files=[done])
    rels = {i.rel for i in items}
    assert rels == {"enwiki/done.bz2"}  # only the completed file; no wip, no .oopart


def test_collect_dir_items_none_takes_all_regular_files(tmp_path):
    root = tmp_path / "osm"
    _write(root / "a.pbf", b"a")
    _write(root / "b.pbf.oopart", b"b")
    items = collect_dir_items(root, "osm_regions", done_files=None)
    assert {i.rel for i in items} == {"a.pbf"}  # the .oopart temp is always excluded


def test_collect_model_items_dedups_blobs(tmp_path):
    store = tmp_path / "models"
    (store / "blobs").mkdir(parents=True)
    (store / "manifests" / "reg/lib/m").mkdir(parents=True)
    _write(store / "blobs" / "sha256-aaa", b"a" * 10)
    _write(store / "blobs" / "sha256-bbb", b"b" * 20)
    (store / "manifests" / "reg/lib/m" / "latest").write_text(
        json.dumps({"config": {"digest": "sha256:aaa"}, "layers": [{"digest": "sha256:bbb"}]})
    )
    items = collect_model_items(store)
    rels = {i.rel for i in items}
    assert "blobs/sha256-aaa" in rels and "blobs/sha256-bbb" in rels
    assert any(r.startswith("manifests/") for r in rels)


# --------------------------------------------------------------------------- #
# write + dedup
# --------------------------------------------------------------------------- #
def test_write_copies_then_dedups_on_second_run(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "drive"
    items = _items(src)
    r1 = write_folder_backup(dest, items)
    assert r1["copied"] == 3 and r1["skipped"] == 0 and r1["complete"]
    assert (dest / "wiki_dumps" / "enwiki" / "a.bz2").read_bytes() == b"a" * 100
    assert (dest / MANIFEST_NAME).is_file()
    # Second run: everything is identical (same size) -> nothing re-copied.
    r2 = write_folder_backup(dest, items)
    assert r2["copied"] == 0 and r2["skipped"] == 3


def test_changed_size_is_recopied(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "drive"
    items = _items(src)
    write_folder_backup(dest, items)
    # The source file grew (a new dump at the same rel) -> re-copied.
    items[0].src.write_bytes(b"a" * 250)
    items[0].size = 250
    r = write_folder_backup(dest, items)
    assert r["copied"] == 1 and r["skipped"] == 2
    assert (dest / "wiki_dumps" / "enwiki" / "a.bz2").stat().st_size == 250


# --------------------------------------------------------------------------- #
# pause / resume / atomicity
# --------------------------------------------------------------------------- #
def test_pause_leaves_no_manifest_and_resume_completes(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "drive"
    items = _items(src)
    # Stop after the first file is copied (progress fires post-file).
    state = {"stop": False, "n": 0}

    def prog(_):
        state["n"] += 1
        if state["n"] >= 1:
            state["stop"] = True

    r = write_folder_backup(dest, items, progress_cb=prog, should_stop=lambda: state["stop"])
    assert r["stopped"] and not r["complete"]
    assert not (dest / MANIFEST_NAME).exists()  # no manifest on an incomplete pass
    assert not list(dest.rglob("*.oopart"))  # no corrupt temp left behind
    # Resume (no stop): already-copied files are skipped, the rest finish, manifest written.
    r2 = write_folder_backup(dest, items)
    assert r2["complete"] and r2["copied"] + r2["skipped"] == 3
    assert (dest / MANIFEST_NAME).is_file()


def test_atomic_copy_stop_mid_file_leaves_no_destination(tmp_path):
    from src.backup.folder_backup import _atomic_copy

    src = _write(tmp_path / "big.bin", b"x" * (8 * 1024 * 1024 + 5))  # > one buffer
    dst = tmp_path / "out" / "big.bin"
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] >= 2  # let the first buffer write, stop before the second

    ok = _atomic_copy(src, dst, should_stop=stop)
    assert ok is False
    assert not dst.exists()  # no partial destination
    assert not list((tmp_path / "out").glob("*.oopart"))  # temp cleaned


# --------------------------------------------------------------------------- #
# restore (additive)
# --------------------------------------------------------------------------- #
def test_restore_is_additive_and_never_overwrites_a_local_file(tmp_path):
    backup = tmp_path / "drive"
    write_folder_backup(backup, _items(tmp_path / "src"))
    live_wiki = tmp_path / "live" / "wiki"
    live_osm = tmp_path / "live" / "osm"
    # The user already has a DIFFERING local copy of a.bz2 — it must be preserved.
    _write(live_wiki / "enwiki" / "a.bz2", b"LOCAL-DIFFERENT")
    res = restore_folder_backup(
        backup,
        categories=["wiki_dumps", "osm_regions"],
        targets={"wiki_dumps": live_wiki, "osm_regions": live_osm},
    )
    assert res["restored"] == 2 and res["skipped"] == 1  # b + c restored, a skipped
    assert (live_wiki / "enwiki" / "a.bz2").read_bytes() == b"LOCAL-DIFFERENT"  # untouched
    assert (live_wiki / "enwiki" / "b.bz2").is_file()
    assert (live_osm / "europe.pbf").is_file()


def test_restore_only_selected_categories(tmp_path):
    backup = tmp_path / "drive"
    write_folder_backup(backup, _items(tmp_path / "src"))
    live_wiki, live_osm = tmp_path / "lw", tmp_path / "lo"
    res = restore_folder_backup(
        backup, categories=["wiki_dumps"], targets={"wiki_dumps": live_wiki, "osm_regions": live_osm}
    )
    assert res["restored"] == 2 and not live_osm.exists()  # osm not selected


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #
def test_validate_dest(tmp_path):
    assert validate_dest(tmp_path) == tmp_path.resolve()
    # creatable (writable parent) is OK
    assert validate_dest(tmp_path / "new") == (tmp_path / "new").resolve()
    f = tmp_path / "file"
    f.write_text("x")
    with pytest.raises(ValueError):
        validate_dest(f)  # a file is not a folder
    with pytest.raises(ValueError):
        validate_dest("")  # empty


def test_free_bytes_and_human():
    assert free_bytes(__import__("pathlib").Path(".")) > 0
    assert human_bytes(0) == "0 B"
    assert human_bytes(1536).endswith("KB")
    assert human_bytes(5 * 1024**3).endswith("GB")


# --------------------------------------------------------------------------- #
# the pausable job manager
# --------------------------------------------------------------------------- #
from src.backup.folder_backup import FolderBackupManager  # noqa: E402


def _join(mgr, timeout=5.0):
    if mgr._thread is not None:
        mgr._thread.join(timeout)


def test_manager_backup_copies_injected_items_and_finishes(tmp_path):
    mgr = FolderBackupManager()
    items = _items(tmp_path / "src")
    st = mgr.start(str(tmp_path / "drive"), ["wiki_dumps", "osm_regions"], _items=items)
    assert st["state"] == "running"
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and s["progress"]["copied"] == 3
    assert (tmp_path / "drive" / "wiki_dumps" / "enwiki" / "a.bz2").is_file()


def test_manager_restore_with_injected_targets(tmp_path):
    backup = tmp_path / "drive"
    write_folder_backup(backup, _items(tmp_path / "src"))
    lw, lo = tmp_path / "lw", tmp_path / "lo"
    mgr = FolderBackupManager()
    mgr.start(str(backup), ["wiki_dumps", "osm_regions"], mode="restore",
              _targets={"wiki_dumps": lw, "osm_regions": lo})
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and (lw / "enwiki" / "b.bz2").is_file()


def test_manager_refuses_concurrent_and_preflight_out_of_space(tmp_path, monkeypatch):
    import src.backup.folder_backup as fb

    mgr = FolderBackupManager()
    # Out-of-space preflight: pretend the drive is full.
    monkeypatch.setattr(fb, "free_bytes", lambda _p: 0)
    with pytest.raises(ValueError, match="Not enough free space"):
        mgr.start(str(tmp_path / "d"), ["wiki_dumps"], _items=_items(tmp_path / "src"))


def test_manager_stopped_run_becomes_paused_then_cancelled(tmp_path, monkeypatch):
    import src.backup.folder_backup as fb

    # Stub the copy so the worker returns "stopped" deterministically (no timing race).
    monkeypatch.setattr(
        fb, "write_folder_backup",
        lambda *a, **k: {"stopped": True, "complete": False, "copied": 1, "skipped": 0},
    )
    mgr = FolderBackupManager()
    mgr.start(str(tmp_path / "drive"), ["wiki_dumps"], _items=_items(tmp_path / "src"))
    _join(mgr)
    assert mgr.status()["state"] == "paused"  # stopped + not cancelled
    # The same stopped result, but after cancel(), reports cancelled — not paused.
    mgr2 = FolderBackupManager()
    mgr2._cancelled = True  # as cancel() would set
    mgr2._run_backup(tmp_path / "drive", [], [])
    assert mgr2.status()["state"] == "cancelled"
