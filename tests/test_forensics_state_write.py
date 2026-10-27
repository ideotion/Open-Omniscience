"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``session_state.json`` is the clean-shutdown sentinel the NEXT boot reads to say how this session ended. Its writer swapped ONE fixed
copy name (``session_state.json.tmp``) into place, so two servers on one data folder (R176) wrote the same file: the first swap moved
the other's half-written copy into place, or left the second writer with nothing to swap (its state was lost, with a warning). The
writer now goes through the house helper ``src.safety.file_lock.atomic_replace`` (a copy named for the process and the thread, removed
if the swap fails, a dead process's copies swept), with ``fsync=False`` because the write before this change was not synced either.

The race test runs the second writer in ANOTHER THREAD on purpose: the copy's name carries the thread, so a nested call from the same
thread would reuse the first writer's name and collide with itself, which no real second writer does. The kill tests run the write in a
CHILD PROCESS that dies with ``os._exit(9)`` at a named point (an exception would run the cleanup a real kill never runs).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.monitoring import forensics

_ROOT = Path(__file__).resolve().parents[1]
_OLD = {"state": "clean", "pid": 1, "started_at": "2026-10-26T00:00:00+00:00"}
_NEW = {"state": "running", "pid": 2, "started_at": "2026-10-27T00:00:00+00:00", "pad": "x" * 200}

# Runs in the child: the write dies at `argv[1]` ("write": mid-write after argv[2] characters; "swap": when the swap is asked for).
_CHILD = """
import os, pathlib, sys
from src.monitoring import forensics
where, limit = sys.argv[1], int(sys.argv[2])
if where == "write":
    real_open = pathlib.Path.open
    class Dying:
        def __init__(self, fh): self.fh = fh
        def __enter__(self): return self
        def __exit__(self, *exc): self.fh.close()
        def flush(self): self.fh.flush()
        def fileno(self): return self.fh.fileno()
        def write(self, text):
            self.fh.write(text[:limit]); self.fh.flush()
            os._exit(9)
    def fake_open(self, mode="r", *a, **kw):
        fh = real_open(self, mode, *a, **kw)
        return Dying(fh) if "w" in mode else fh
    pathlib.Path.open = fake_open
else:
    os.replace = lambda *a, **kw: os._exit(9)
forensics._write_state({"state": "running", "pid": 2, "started_at": "2026-10-27T00:00:00+00:00", "pad": "x" * 200})
"""


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def _state(tmp_path: Path) -> Path:
    return tmp_path / "session_state.json"


def _parts(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir() if ".tmp" in p.name)


def _killed_write(tmp_path: Path, where: str, limit: int = 0) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, where, str(limit)],
        cwd=_ROOT,
        env={**os.environ, "OO_DATA_DIR": str(tmp_path)},
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 9, f"the child must die at {where}, not finish or fail: {proc.returncode} {proc.stderr[-400:]!r}"


def test_the_sentinel_is_the_same_bytes_the_replaced_writer_made(tmp_path):
    import json

    forensics._write_state(_NEW)
    assert _state(tmp_path).read_text(encoding="utf-8") == json.dumps(_NEW, indent=1)
    assert forensics._read_state() == _NEW
    assert _parts(tmp_path) == []


def test_a_second_writer_in_another_thread_does_not_cost_the_first_its_swap(tmp_path, monkeypatch, caplog):
    """The first writer has written its copy; the second writer (another thread, as another server's would be) writes and swaps its own
    whole; the first then swaps. The last swap wins, nothing is lost and nothing is logged. With the one shared copy name the second
    writer rewrote the first's copy and swapped it away, so the first swap found nothing: its state was lost with a warning."""
    first, second = dict(_NEW, who="first"), dict(_NEW, who="second")
    real_replace = os.replace
    ran: list[int] = []

    def replace(src, dst):
        if not ran:
            ran.append(1)
            other = threading.Thread(target=forensics._write_state, args=(second,))
            other.start()
            other.join()
            assert forensics._read_state() == second, "the second writer's swap landed first"
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    with caplog.at_level(logging.WARNING):
        forensics._write_state(first)
    assert forensics._read_state() == first, "the last swap wins"
    assert not [r for r in caplog.records if "could not persist" in r.getMessage()]
    assert _parts(tmp_path) == []


def test_a_writer_that_is_half_way_through_its_copy_cannot_tear_the_sentinel_another_one_swaps_in(tmp_path, monkeypatch):
    """One writer has written half of its state when another writes and swaps its own whole; the first then finishes. With the one
    shared copy name the second writer truncated the first's open file and swapped that very file into place, so the first's remaining
    half landed INSIDE the live sentinel (a mixture of two states), and its own swap then found nothing. Each writer has its own copy
    now: the sentinel holds a whole state throughout, and the writer that swaps last is the one it holds."""
    first, second = dict(_NEW, pid=111, tail="first"), dict(_NEW, pid=222, tail="second")  # differ at both ends of the text
    half_written, release = threading.Event(), threading.Event()
    real_open = Path.open

    class Gated:
        """The handle of the half-way writer: writes half, says so, waits to be released, writes the rest."""

        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()

        def flush(self):
            self.fh.flush()

        def fileno(self):
            return self.fh.fileno()

        def write(self, text):
            cut = len(text) // 2
            self.fh.write(text[:cut])
            self.fh.flush()
            half_written.set()
            assert release.wait(30)
            self.fh.write(text[cut:])

    def fake_open(self, mode="r", *a, **kw):
        fh = real_open(self, mode, *a, **kw)
        return Gated(fh) if "w" in mode and threading.current_thread().name == "half-way" else fh

    monkeypatch.setattr(Path, "open", fake_open)
    half_way = threading.Thread(target=forensics._write_state, args=(second,), name="half-way")
    half_way.start()
    assert half_written.wait(30)
    forensics._write_state(first)  # a whole write, start to swap, while the other is half-way
    assert forensics._read_state() == first
    release.set()
    half_way.join(30)
    assert forensics._read_state() == second, "the last swap wins, and it is a whole state"
    assert _parts(tmp_path) == []


def test_a_kill_while_the_copy_is_being_written_leaves_the_old_sentinel_whole(tmp_path):
    forensics._write_state(_OLD)
    before = _state(tmp_path).read_bytes()
    for written in (0, 40):
        _killed_write(tmp_path, "write", written)
        assert _state(tmp_path).read_bytes() == before
        assert forensics._read_state() == _OLD


def test_a_kill_at_the_swap_leaves_the_old_sentinel_whole(tmp_path):
    forensics._write_state(_OLD)
    before = _state(tmp_path).read_bytes()
    _killed_write(tmp_path, "swap")
    assert _state(tmp_path).read_bytes() == before
    assert len(_parts(tmp_path)) == 1, "the kill at the swap leaves the finished copy beside the sentinel"


def test_the_next_write_removes_the_copy_a_killed_process_left_and_writes(tmp_path):
    forensics._write_state(_OLD)
    _killed_write(tmp_path, "swap")
    assert len(_parts(tmp_path)) == 1
    forensics._write_state(_NEW)
    assert _parts(tmp_path) == []
    assert forensics._read_state() == _NEW


def test_a_refused_swap_leaves_the_old_sentinel_whole_and_no_copy(tmp_path, monkeypatch, caplog):
    forensics._write_state(_OLD)
    before = _state(tmp_path).read_bytes()

    def refuse(*_a, **_k):
        raise PermissionError("the sentinel is held open")  # Windows, when another handle has it

    monkeypatch.setattr(os, "replace", refuse)
    with caplog.at_level(logging.WARNING):
        forensics._write_state(_NEW)  # warns, never raises
    assert _state(tmp_path).read_bytes() == before and _parts(tmp_path) == []
    assert [r for r in caplog.records if "could not persist" in r.getMessage()]


def test_the_sentinel_is_not_synced(tmp_path, monkeypatch):
    """It is rewritten at every lifecycle step, a sync could block the shutdown path on a wedged device, and the writer this one
    replaced did not sync either: the choice (``fsync=False``) is pinned so a later change to the helper's default does not make it."""
    synced: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd))
    forensics._write_state(_NEW)
    assert synced == [] and forensics._read_state() == _NEW


def test_the_copy_is_named_for_the_process_and_the_thread(tmp_path, monkeypatch):
    """Two processes (or threads) writing at once must not write one file: the name differs between them."""
    names: list[str] = []
    real_replace = os.replace

    def spy(a, b):
        names.append(Path(a).name)
        real_replace(a, b)

    monkeypatch.setattr(os, "replace", spy)
    forensics._write_state(_NEW)
    worker = threading.Thread(target=forensics._write_state, args=(_NEW,))
    worker.start()
    worker.join()
    assert len(names) == 2 and names[0] != names[1]
    assert all(n.startswith(f"session_state.json.tmp.{os.getpid()}.") for n in names)


def test_without_psutil_the_write_still_happens_and_a_leftover_copy_is_left_in_place(tmp_path, monkeypatch):
    """psutil is a core dependency, so only a broken install lacks it. The helper's sweep cannot tell live from dead there ("unknown is
    not dead"), removes nothing and does not break the write: the sentinel still lands."""
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    orphan = tmp_path / f"session_state.json.tmp.{gone.pid}.1"
    orphan.write_text("x", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "psutil", None)  # `import psutil` raises ImportError
    forensics._write_state(_NEW)
    assert orphan.exists(), "unknown is not dead"
    assert forensics._read_state() == _NEW, "and the write still happens"


def test_a_state_that_cannot_be_serialised_leaves_no_copy_behind(tmp_path):
    forensics._write_state(_OLD)
    with pytest.raises(TypeError):
        forensics._write_state({"state": object()})
    assert forensics._read_state() == _OLD and _parts(tmp_path) == []
