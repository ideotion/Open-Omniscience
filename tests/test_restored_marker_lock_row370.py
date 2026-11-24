"""Row 370: the R801 marker's look-and-write is serialised across processes, not only threads.

A restore looks for an evidence key and writes its marker, and a new key's creation drops the marker, both under
``KEY_FILES_LOCK``: a lock inside ONE process. A second server on the same data folder (R176 allows one) could make its
own key between a restore's look and its marker write, and its own key then read as another installation's. Both now
run under :func:`src.reporting.evidence.restored_marker_lock`, which adds a cross-process file lock on ``keys.lock``
beside the ``keys`` folder. What the marker means is unchanged.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from src.backup import merge
from src.reporting import evidence as ev
from src.safety import data_scope


@pytest.fixture(autouse=True)
def _plaintext_install(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(connect, "_passphrase", None)
    (tmp_path / "live" / "keys").mkdir(parents=True)


def _holder(key: Path) -> subprocess.Popen:
    """Another process that takes the marker lock for ``key``, says so, and holds it until its stdin closes."""
    code = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        from src.reporting.evidence import restored_marker_lock
        with restored_marker_lock(Path(sys.argv[1])):
            print("held", flush=True)
            sys.stdin.read()
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(key)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
        cwd=Path(__file__).resolve().parents[1],
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "held"
    return proc


def _release(proc: subprocess.Popen) -> None:
    assert proc.stdin is not None
    proc.stdin.close()
    proc.wait(timeout=30)


@pytest.mark.skipif(sys.platform == "win32", reason="the subprocess holder is exercised on POSIX here")
def test_a_new_key_waits_while_another_process_holds_the_marker_lock(tmp_path):
    key = tmp_path / "live" / "keys" / "evidence_ed25519.pem"
    proc = _holder(key)
    done = threading.Event()
    try:
        t = threading.Thread(target=lambda: (ev.load_or_create_signing_key(key), done.set()), daemon=True)
        t.start()
        time.sleep(0.6)
        assert not done.is_set(), "a key was made while another process held the marker lock"
        assert not key.exists()
    finally:
        _release(proc)
    assert done.wait(15), "the key was never made once the other process let go"
    assert key.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the subprocess holder is exercised on POSIX here")
def test_a_restores_marker_waits_too(tmp_path):
    key = tmp_path / "live" / "keys" / "evidence_ed25519.pem"
    proc = _holder(key)
    got: list[object] = []
    try:
        def look_and_mark():
            with ev.restored_marker_lock(key):
                got.append(ev.mark_key_as_restored(key))

        t = threading.Thread(target=look_and_mark, daemon=True)
        t.start()
        time.sleep(0.6)
        assert got == [] and not ev.restored_key_marker(key).exists()
    finally:
        _release(proc)
    t.join(15)
    assert got and ev.restored_key_marker(key).exists()


def test_the_lock_is_reentrant_in_a_thread_and_keeps_the_keys_folder_clean(tmp_path):
    key = tmp_path / "live" / "keys" / "evidence_ed25519.pem"
    with ev.restored_marker_lock(key), ev.restored_marker_lock(key):
        pass
    ev.load_or_create_signing_key(key)  # makes the key and drops the marker under the lock it already holds
    assert sorted(os.listdir(key.parent)) == ["evidence_ed25519.pem"]
    assert (tmp_path / "live" / "keys.lock").exists()
    assert data_scope.is_app_owned("keys.lock")  # an erase still knows it as the app's


def test_the_marker_sites_take_the_cross_process_lock():
    assert "with restored_marker_lock(path):" in inspect.getsource(ev.load_or_create_signing_key)
    assert "with restored_marker_lock(path):" in inspect.getsource(ev._drop_restored_marker)
    assert "with restored_marker_lock(keys_dir / _EVIDENCE_KEY_FILE):" in inspect.getsource(merge._restore_key_members_now)
    assert "with restored_marker_lock(evidence):" in inspect.getsource(merge._settle_restore_marker)
    body = inspect.getsource(ev.restored_marker_lock).split('"""')[-1]
    assert body.index("file_lock(keys_dir)") < body.rindex("KEY_FILES_LOCK")  # cross-process first, always the same order


@pytest.mark.skipif(sys.platform == "win32", reason="the subprocess holder is exercised on POSIX here")
def test_a_waiter_never_holds_the_in_process_key_lock_while_another_process_holds_the_file(tmp_path):
    """The emergency erase and every key change take KEY_FILES_LOCK alone: a thread waiting on another process for the
    marker lock must not be holding it, or a stopped second server would stall this process's erase."""
    from src.custody import keyfile

    key = tmp_path / "live" / "keys" / "evidence_ed25519.pem"
    proc = _holder(key)
    try:
        t = threading.Thread(target=ev.load_or_create_signing_key, args=(key,), daemon=True)
        t.start()
        time.sleep(0.4)
        assert t.is_alive()
        assert keyfile.KEY_FILES_LOCK.acquire(timeout=2), "the waiter held the in-process key lock"
        keyfile.KEY_FILES_LOCK.release()
    finally:
        _release(proc)
    t.join(15)
    assert key.exists()


def test_a_body_that_raises_leaves_the_lock_usable_again(tmp_path):
    key = tmp_path / "live" / "keys" / "evidence_ed25519.pem"
    with pytest.raises(ZeroDivisionError), ev.restored_marker_lock(key):
        1 / 0  # noqa: B018 - the body raises on purpose
    done: list[bool] = []

    def take():
        with ev.restored_marker_lock(key):
            done.append(True)

    t = threading.Thread(target=take, daemon=True)
    t.start()
    t.join(10)
    assert done == [True], "another thread could not take the lock after a body raised"
    with ev.restored_marker_lock(key):  # and this thread takes the cross-process lock again, not the re-entrant path
        assert os.path.realpath(key.parent) in ev._MARKER_LOCKS_HELD.paths
    assert os.path.realpath(key.parent) not in ev._MARKER_LOCKS_HELD.paths
