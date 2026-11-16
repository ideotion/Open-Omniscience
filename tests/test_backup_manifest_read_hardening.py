"""The two security reads of #2061 and the planner's follow-up (2026-11-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

1. ``load_manifest`` reads ``volumes.json`` only when it is a REGULAR file of at most ``MANIFEST_MAX_BYTES``: a FIFO there
   blocked the import start for ever (measured), a link could point at ``/dev/zero`` or anywhere else.
2. A volume name is checked with ``fullmatch``: ``^...$`` with ``match`` let ``"v1\\n"`` through, and ``.``/``..`` are refused.
3. The early passphrase check does not try a key on a backup the run skips as already merged: one merged backup under an
   old passphrase must not refuse a whole batch over a backup that is never opened again.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from src.backup.stream_backup import STREAM_KIND, VolumeError, _require_safe_volume_name
from src.backup.volumes import MANIFEST_NAME, load_manifest


def _manifest(folder: Path, names=("v0001.ooenc",)) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"x")
    m = {"kind": STREAM_KIND, "volumes": [{"name": n, "sha256": "0" * 64} for n in names],
         "members": [{"name": "corpus.db", "volumes": list(names)}]}
    (folder / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    return folder


def test_a_regular_manifest_still_reads(tmp_path):
    assert load_manifest(_manifest(tmp_path / "ok"))["kind"] == STREAM_KIND


def test_a_missing_manifest_says_so(tmp_path):
    (tmp_path / "none").mkdir()
    with pytest.raises(VolumeError, match="no volume manifest"):
        load_manifest(tmp_path / "none")


@pytest.mark.skipif(os.name == "nt", reason="creating a symbolic link needs a privilege on Windows")
def test_a_linked_manifest_is_never_read(tmp_path):
    real = _manifest(tmp_path / "real")
    folder = tmp_path / "linked"
    folder.mkdir()
    (folder / MANIFEST_NAME).symlink_to(real / MANIFEST_NAME)
    with pytest.raises(VolumeError, match="not a regular file"):
        load_manifest(folder)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this platform")
def test_a_fifo_manifest_is_refused_and_never_blocks(tmp_path):
    folder = tmp_path / "fifo"
    folder.mkdir()
    os.mkfifo(folder / MANIFEST_NAME)
    outcome: list[object] = []
    t = threading.Thread(target=lambda: outcome.append(_try(load_manifest, folder)), daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), "load_manifest blocked on a FIFO"
    assert isinstance(outcome[0], VolumeError) and "not a regular file" in str(outcome[0])


def _try(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - the test reads the exception
        return exc


def test_an_oversized_manifest_is_refused_before_it_is_parsed(tmp_path, monkeypatch):
    import src.backup.volumes as V

    folder = _manifest(tmp_path / "big")
    monkeypatch.setattr(V, "MANIFEST_MAX_BYTES", 16)
    with pytest.raises(VolumeError, match="larger than 16 bytes"):
        load_manifest(folder)


@pytest.mark.parametrize("name", ["v1\n", ".", "..", "a/b", "", "v1 "])
def test_an_unsafe_volume_name_is_refused(name):
    with pytest.raises(VolumeError, match="unsafe volume file name"):
        _require_safe_volume_name(name)


@pytest.mark.parametrize("name", ["v0001.ooenc", "a-b_c.1"])
def test_a_plain_volume_name_passes(name):
    _require_safe_volume_name(name)


def test_an_already_merged_backup_under_an_old_passphrase_never_stops_the_start(tmp_path, monkeypatch):
    import src.backup.lane_merge as LM
    import src.backup.merge as MG
    import src.backup.stream_backup as SB
    from src.backup.import_queue import ImportQueueManager

    merged = _manifest(tmp_path / "merged")
    fresh = _manifest(tmp_path / "fresh")
    tried: list[str] = []
    monkeypatch.setattr(SB, "backup_passphrase_is_wrong", lambda p, k: tried.append(Path(p).name) or Path(p) == merged)
    monkeypatch.setattr(MG, "artifact_source_digest", lambda p: "d" * 64 if Path(p) == merged else None)
    monkeypatch.setattr(MG, "find_completed_import", lambda d: {"batch_id": 7, "imported_at": "x"} if d else None)
    monkeypatch.setattr(LM, "lanes_pending", lambda d: False)
    ImportQueueManager._refuse_wrong_backup_passphrases(
        [{"kind": "corpus", "path": str(merged), "passphrase": "old words"}, {"kind": "corpus", "path": str(fresh)}], "new words"
    )
    assert tried == ["fresh"]  # the merged backup's key is never tried
    with pytest.raises(ValueError, match="Wrong passphrase for merged"):  # force reads it again, so its key is checked
        ImportQueueManager._refuse_wrong_backup_passphrases(
            [{"kind": "corpus", "path": str(merged), "passphrase": "old words", "force": True}], "new words"
        )


@pytest.mark.parametrize("case", ["lanes-owed", "question-raises"])
def test_a_backup_the_run_would_open_again_still_has_its_key_tried(tmp_path, monkeypatch, case):
    """The two directions where a skip would bring back the late failure (the second security read): a merged backup whose
    living-source lanes are still owed is opened again by the run (R729), and a question that raises is not "already merged"."""
    import src.backup.lane_merge as LM
    import src.backup.merge as MG
    import src.backup.stream_backup as SB
    from src.backup.import_queue import ImportQueueManager

    merged = _manifest(tmp_path / "merged")
    monkeypatch.setattr(SB, "backup_passphrase_is_wrong", lambda p, k: True)
    monkeypatch.setattr(MG, "find_completed_import", lambda d: {"batch_id": 7, "imported_at": "x"} if d else None)
    if case == "lanes-owed":
        monkeypatch.setattr(MG, "artifact_source_digest", lambda p: "d" * 64)
        monkeypatch.setattr(LM, "lanes_pending", lambda d: True)
    else:

        def _raises(p):
            raise OSError("unreadable")

        monkeypatch.setattr(MG, "artifact_source_digest", _raises)
        monkeypatch.setattr(LM, "lanes_pending", lambda d: False)
    with pytest.raises(ValueError, match="Wrong passphrase for merged"):
        ImportQueueManager._refuse_wrong_backup_passphrases(
            [{"kind": "corpus", "path": str(merged), "passphrase": "old words"}], "new words"
        )


@pytest.mark.skipif(os.name == "nt", reason="creating a symbolic link needs a privilege on Windows")
def test_a_folder_that_cannot_be_examined_is_a_volume_refusal(tmp_path):
    """The first security read: a folder that is a file (ENOTDIR) or a link loop (ELOOP) raised a bare OSError."""
    not_a_folder = tmp_path / "file"
    not_a_folder.write_text("x", encoding="utf-8")
    with pytest.raises(VolumeError, match="cannot be examined"):
        load_manifest(not_a_folder)
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    with pytest.raises(VolumeError):
        load_manifest(loop)


@pytest.mark.skipif(os.name == "nt", reason="Windows does not open a directory as a file")
def test_a_directory_swapped_in_after_the_check_is_refused_and_its_descriptor_closed(tmp_path, monkeypatch):
    """The first security read: a directory swapped in after the lstat opens on Linux, and fdopen then raised with the
    descriptor left open. The raw descriptor is checked first and always closed."""
    import os as _os

    import src.backup.volumes as V

    folder = _manifest(tmp_path / "set")
    real_open, closed, opened = _os.open, [], []

    def _swap_then_open(path, flags, *a):
        target = Path(path)
        target.unlink()
        target.mkdir()
        fd = real_open(path, flags & ~getattr(_os, "O_NOFOLLOW", 0), *a)
        opened.append(fd)
        return fd

    real_close = _os.close
    monkeypatch.setattr(V.os, "open", _swap_then_open)
    monkeypatch.setattr(V.os, "close", lambda fd: closed.append(fd) or real_close(fd))
    with pytest.raises(VolumeError, match="not a regular file"):
        load_manifest(folder)
    assert opened and closed == opened
