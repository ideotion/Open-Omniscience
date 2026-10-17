"""The cross-process file lock and the atomic replace (R176).

Before: a trim and an append by two servers on one data folder could lose the appended line (measured 17 Oct, K4), and two writers on a fixed ``.tmp`` name left a
half file (K5). What is pinned: a second PROCESS waits for the first's exclusive section and sees its result; a trim never loses a line appended by another process
(a shared append waits for it, and it waits for the append); an interrupted section frees the lock; a re-entrant take raises instead of deadlocking; a filesystem that
cannot lock runs unlocked and says so ONCE, by file name and never by folder; no wait loop is a ``while <condition>`` loop (R161-R165); and two writers never share a
temp name."""

from __future__ import annotations

import ast
import errno
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from src.safety import file_lock
from src.safety.file_lock import atomic_replace, locked_append, temp_name
from src.safety.file_lock import file_lock as lock

ROOT = str(Path(file_lock.__file__).parents[2])


def _run(code: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", f"import sys; sys.path.insert(0, {ROOT!r})\n" + textwrap.dedent(code), *args], stdout=subprocess.PIPE, text=True)


def test_a_second_process_waits_for_the_exclusive_section_and_sees_its_result(tmp_path):
    target = tmp_path / "state.json"
    ready = tmp_path / "ready"
    child = _run(
        """
        import sys, time
        from pathlib import Path
        from src.safety.file_lock import atomic_replace, file_lock
        t = Path(sys.argv[1])
        with file_lock(t):
            Path(sys.argv[2]).write_text("in")
            time.sleep(1.0)
            atomic_replace(t, "from-child")
        """,
        str(target),
        str(ready),
    )
    deadline = time.monotonic() + 20
    while True:
        if ready.exists():
            break
        assert time.monotonic() < deadline, "the child never took the lock"
        time.sleep(0.02)
    began = time.monotonic()
    with lock(target) as held:
        waited = time.monotonic() - began
        assert held.locked
        assert target.read_text() == "from-child"
    child.wait(timeout=20)
    assert waited > 0.3, "the parent did not wait for the child's section"


def test_a_trim_in_one_process_never_loses_a_line_appended_by_another(tmp_path):
    target = tmp_path / "ledger.jsonl"
    target.write_text("".join(f"{i}\n" for i in range(200)))
    appender = _run(
        """
        import sys
        from pathlib import Path
        from src.safety.file_lock import locked_append
        t = Path(sys.argv[1])
        for i in range(400):
            locked_append(t, f"a{i}\\n")
        """,
        str(target),
    )
    trims = 0
    while appender.poll() is None:
        with lock(target):
            kept = target.read_text().splitlines()[-150:]
            atomic_replace(target, "\n".join(kept) + "\n")
        trims += 1
    appender.wait()
    assert trims >= 1
    got = [ln for ln in target.read_text().splitlines() if ln.startswith("a")]
    want = [f"a{i}" for i in range(400)]
    assert got == want[-len(got) :], "a line appended by the other process was lost, or the order broke"
    assert got[-1] == "a399"


def test_an_interrupted_section_frees_the_lock(tmp_path):
    target = tmp_path / "f"
    with pytest.raises(KeyboardInterrupt), lock(target):
        raise KeyboardInterrupt
    with lock(target) as held:  # would hang if the first was still held
        assert held.locked


def test_taking_it_twice_in_one_thread_raises_instead_of_deadlocking(tmp_path):
    target = tmp_path / "f"
    with lock(target), pytest.raises(RuntimeError, match="not re-entrant"), lock(target):
        pass


def test_shared_sections_run_together_and_an_exclusive_one_waits_for_them(tmp_path):
    target = tmp_path / "f"
    inside, release = threading.Barrier(2, timeout=10), threading.Event()
    order: list[str] = []

    def reader():
        with lock(target, shared=True):
            inside.wait()
            release.wait(10)
            order.append("reader-out")

    ts = [threading.Thread(target=reader) for _ in range(2)]
    for t in ts:
        t.start()
    time.sleep(0.3)  # both are inside: the barrier needed both to pass
    def writer():
        with lock(target):
            order.append("writer-in")

    got = threading.Thread(target=writer)
    got.start()
    time.sleep(0.3)
    assert order == [], "the exclusive section ran while readers held it"
    release.set()
    for t in [*ts, got]:
        t.join(10)
    assert order[-1] == "writer-in"


def test_a_filesystem_that_cannot_lock_runs_unlocked_and_warns_once_by_name(tmp_path, monkeypatch, capsys):
    def refuse(fd, shared):
        raise OSError(errno.ENOLCK, "no locks")

    monkeypatch.setattr(file_lock, "_try_os_lock", refuse)
    monkeypatch.setattr(file_lock, "_UNLOCKED_WARNED", set())
    target = tmp_path / "secretish-folder" / "journal.jsonl"
    for _ in range(2):
        with lock(target) as held:
            assert not held.locked and "OSError" in (held.reason or "")
    err = capsys.readouterr().err
    assert err.count("journal.jsonl runs UNLOCKED") == 1
    assert "secretish-folder" not in err, "the warning carried a folder path"


def test_two_writers_never_share_a_temp_name(tmp_path):
    target = tmp_path / "f"
    names: list[Path] = []
    t = threading.Thread(target=lambda: names.append(temp_name(target)))
    t.start()
    t.join()
    assert names[0] != temp_name(target)


def test_a_failed_replace_leaves_the_old_file_whole_and_no_temp(tmp_path, monkeypatch):
    target = tmp_path / "f"
    target.write_text("old")

    def boom(a, b):
        raise OSError("disk")

    monkeypatch.setattr(file_lock.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_replace(target, "new")
    assert target.read_text() == "old"
    assert not list(tmp_path.glob("f.tmp.*"))


def test_no_wait_loop_is_a_while_on_a_condition():
    """R161-R165: a wait loop is ``while True:`` with an ``if ...: break`` inside, never ``while <cond>:``."""
    tree = ast.parse(Path(file_lock.__file__).read_text())
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    assert loops, "the waits are gone; this test would pass for the wrong reason"
    for n in loops:
        assert isinstance(n.test, ast.Constant) and n.test.value is True, f"line {n.lineno}: a while on a condition"
        assert any(isinstance(x, ast.Break) for x in ast.walk(n)), f"line {n.lineno}: no break"


def test_the_longest_wait_and_hold_are_reported_by_file_name(tmp_path):
    with lock(tmp_path / "named.jsonl"):
        pass
    row = file_lock.stats()["named.jsonl"]
    assert row["max_hold_s"] >= 0.0 and row["max_wait_s"] >= 0.0


def test_locked_append_writes_the_text(tmp_path):
    p = tmp_path / "log"
    locked_append(p, "a\n")
    locked_append(p, "b\n")
    assert p.read_text() == "a\nb\n"
