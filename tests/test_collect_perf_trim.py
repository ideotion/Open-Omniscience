"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``collect_perf.jsonl`` holds the last samples crash forensics reads, and its trim used to rewrite it in place: ``write_text`` truncates
the log first, so a process killed before the rows were written back left it EMPTY (the crash this file is evidence for destroyed the
evidence). The trim now writes the kept rows to a copy beside the log and swaps it in with ``os.replace``.

The kill tests run the trim in a CHILD PROCESS that dies with ``os._exit(9)`` at a named point (an exception would run the cleanup a
real kill never runs) and then read the log from here. They are written against the effect, not the implementation: the child kills
itself the moment the cut is written to whichever file the code opens for writing, so the in-place version leaves the log empty or
short and the swapped version leaves the old log whole.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.monitoring import collect_perf

_ROOT = Path(__file__).resolve().parents[1]
_CAP = collect_perf._CAP_LINES

# Runs in the child: the cut dies at `argv[1]` ("write": mid-write after argv[2] characters; "swap": when the swap is asked for).
_CHILD = """
import os, pathlib, sys
from src.monitoring import collect_perf
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
collect_perf._trim_jsonl()
"""


def _rows(n: int) -> list[str]:
    return [f'{{"i":{i},"pad":"{"x" * 40}"}}' for i in range(n)]


def _write_log(tmp_path: Path, n: int) -> tuple[Path, bytes]:
    path = tmp_path / "collect_perf.jsonl"
    path.write_bytes(("\n".join(_rows(n)) + "\n").encode("utf-8"))
    return path, path.read_bytes()


def _parts(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".part"))


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def _killed_cut(tmp_path: Path, where: str, limit: int = 0) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, where, str(limit)],
        cwd=_ROOT,
        env={**os.environ, "OO_DATA_DIR": str(tmp_path)},
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 9, f"the child must die at {where}, not finish or fail: {proc.returncode} {proc.stderr[-400:]!r}"


def test_the_cut_keeps_the_newest_rows_as_the_same_bytes_the_in_place_write_made(tmp_path):
    path, _ = _write_log(tmp_path, _CAP + 37)
    collect_perf._trim_jsonl()
    reference = tmp_path / "reference"
    reference.write_text("\n".join(_rows(_CAP + 37)[-_CAP:]) + "\n", encoding="utf-8")  # what the replaced code wrote
    assert path.read_bytes() == reference.read_bytes()
    assert _parts(tmp_path) == []


def test_a_log_within_the_cap_is_not_rewritten(tmp_path):
    path, before = _write_log(tmp_path, _CAP)
    mtime = path.stat().st_mtime_ns
    collect_perf._trim_jsonl()
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime and _parts(tmp_path) == []


@pytest.mark.parametrize("written", [0, 4096])
def test_a_kill_while_the_cut_is_being_written_leaves_the_old_log_whole(tmp_path, written):
    """0 characters = the kill lands right after the file the code opened for writing was truncated: the in-place version's window."""
    path, before = _write_log(tmp_path, _CAP + 50)
    _killed_cut(tmp_path, "write", written)
    assert path.read_bytes() == before


def test_a_kill_at_the_swap_leaves_the_old_log_whole(tmp_path):
    path, before = _write_log(tmp_path, _CAP + 50)
    _killed_cut(tmp_path, "swap")
    assert path.read_bytes() == before


def test_the_next_cut_removes_the_copy_a_killed_process_left_and_cuts(tmp_path):
    path, before = _write_log(tmp_path, _CAP + 50)
    _killed_cut(tmp_path, "swap")
    assert len(_parts(tmp_path)) == 1, "the kill at the swap leaves the finished copy beside the log"
    collect_perf._trim_jsonl()
    assert _parts(tmp_path) == []
    assert path.read_text(encoding="utf-8").splitlines() == _rows(_CAP + 50)[-_CAP:]


def test_a_refused_swap_leaves_the_old_log_whole_and_no_copy(tmp_path, monkeypatch):
    path, before = _write_log(tmp_path, _CAP + 50)

    def refuse(*_a, **_k):
        raise PermissionError("the log is held open")  # Windows, when another handle has it

    monkeypatch.setattr(os, "replace", refuse)
    collect_perf._trim_jsonl()  # logs at debug level, never raises
    assert path.read_bytes() == before and _parts(tmp_path) == []


def test_the_copy_is_synced_before_it_is_swapped_in(tmp_path, monkeypatch):
    _write_log(tmp_path, _CAP + 50)
    order: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1])
    collect_perf._trim_jsonl()
    assert order == ["fsync", "replace"]


def test_the_copy_is_named_for_the_process_and_the_thread(tmp_path, monkeypatch):
    """Two processes (or threads) cutting at once must not write one file: the name differs between them."""
    _write_log(tmp_path, _CAP + 50)
    names: list[str] = []
    real_replace = os.replace

    def spy(a, b):
        names.append(Path(a).name)
        real_replace(a, b)

    monkeypatch.setattr(os, "replace", spy)
    collect_perf._trim_jsonl()
    _write_log(tmp_path, _CAP + 50)
    worker = threading.Thread(target=collect_perf._trim_jsonl)
    worker.start()
    worker.join()
    assert len(names) == 2 and names[0] != names[1]
    assert all(n.startswith(f"collect_perf.jsonl.{os.getpid()}.") and n.endswith(".part") for n in names)


def test_only_a_copy_whose_process_is_gone_is_removed(tmp_path):
    _write_log(tmp_path, _CAP + 50)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        dead_copy = tmp_path / f"collect_perf.jsonl.{gone.pid}.1.part"
        live_copy = tmp_path / f"collect_perf.jsonl.{live.pid}.1.part"
        not_a_pid = tmp_path / "collect_perf.jsonl.notes.part"
        other_log = tmp_path / f"other.jsonl.{gone.pid}.1.part"
        for p in (dead_copy, live_copy, not_a_pid, other_log):
            p.write_text("x", encoding="utf-8")
        collect_perf._trim_jsonl()
        assert not dead_copy.exists()
        assert live_copy.exists() and not_a_pid.exists() and other_log.exists()
    finally:
        live.kill()
        live.wait()


def test_with_no_way_to_tell_live_from_dead_nothing_is_removed(tmp_path, monkeypatch):
    _write_log(tmp_path, _CAP + 50)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    orphan = tmp_path / f"collect_perf.jsonl.{gone.pid}.1.part"
    orphan.write_text("x", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "psutil", None)  # `import psutil` raises ImportError
    collect_perf._trim_jsonl()
    assert orphan.exists(), "unknown is not dead"
    assert len((tmp_path / "collect_perf.jsonl").read_text(encoding="utf-8").splitlines()) == _CAP, "and the cut still happens"
