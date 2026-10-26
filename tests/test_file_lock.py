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
        assert target.read_text(encoding="utf-8") == "from-child"
    child.wait(timeout=20)
    assert waited > 0.3, "the parent did not wait for the child's section"


def test_a_trim_in_one_process_never_loses_a_line_appended_by_another(tmp_path):
    target = tmp_path / "ledger.jsonl"
    target.write_text("".join(f"{i}\n" for i in range(200)), encoding="utf-8")
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
            kept = target.read_text(encoding="utf-8").splitlines()[-150:]
            atomic_replace(target, "\n".join(kept) + "\n")
        trims += 1
    appender.wait()
    assert trims >= 1
    got = [ln for ln in target.read_text(encoding="utf-8").splitlines() if ln.startswith("a")]
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
    target.write_text("old", encoding="utf-8")

    def boom(a, b):
        raise OSError("disk")

    monkeypatch.setattr(file_lock.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_replace(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob("f.tmp.*"))


def test_no_wait_loop_is_a_while_on_a_condition():
    """R161-R165: a wait loop is ``while True:`` with an ``if ...: break`` inside, never ``while <cond>:``."""
    tree = ast.parse(Path(file_lock.__file__).read_text(encoding="utf-8"))
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
    assert p.read_text(encoding="utf-8") == "a\nb\n"


def test_fsync_can_be_skipped_and_the_sweep_is_throttled(tmp_path, monkeypatch):
    synced, swept = [], []
    monkeypatch.setattr(file_lock.os, "fsync", lambda fd: synced.append(fd))
    monkeypatch.setattr(file_lock, "sweep_dead_temps", lambda p: swept.append(p))
    f = tmp_path / "state.json"
    atomic_replace(f, "a", fsync=False, sweep_every_s=300.0)
    atomic_replace(f, "b", fsync=False, sweep_every_s=300.0)
    assert synced == [] and len(swept) == 1, "a throttled writer swept twice, or synced when told not to"
    atomic_replace(f, "c")
    assert len(synced) == 1 and len(swept) == 2
    assert f.read_text(encoding="utf-8") == "c"


def test_holding_runs_the_function_inside_the_lock_and_follows_a_redirected_path(tmp_path):
    from src.safety.file_lock import holding

    target = {"p": tmp_path / "a"}
    seen: list[bool] = []

    @holding(lambda: target["p"])
    def work(x):
        # the lock is held: a second take from ANOTHER thread has to wait for us
        got = []
        t = threading.Thread(target=lambda: got.append(lock(target["p"]).__enter__()))
        t.daemon = True
        t.start()
        t.join(0.3)
        seen.append(not got)
        return x + 1

    assert work(1) == 2 and seen == [True]
    target["p"] = tmp_path / "b"
    assert work(2) == 3
    assert (tmp_path / "b.lock").exists(), "the decorator did not follow the redirected path"


def test_a_finalizer_that_reaches_file_lock_while_a_lock_object_is_built_leaves_one_object_for_the_key(tmp_path, monkeypatch):
    """The first section to meet a lock file builds its in-process object, and a finalizer's log record can reach ``file_lock`` for the same file at the
    allocation: a check-then-set would register two objects for one lock file, and two threads would hold it at once."""
    import threading

    from src.safety import file_lock as fl

    key = str(tmp_path / "j.jsonl.lock")
    real = fl._Local
    fired = []
    inner = []

    def building(*args, **kwargs):
        if not fired:
            fired.append(1)
            inner.append(fl._local(key))  # the re-entry: registers its own object first
        return real(*args, **kwargs)

    monkeypatch.setattr(fl, "_Local", building)
    out = []
    t = threading.Thread(target=lambda: out.append(fl._local(key)), daemon=True)
    t.start()
    t.join(20)
    assert out, "the registry waited on a lock its own thread holds"
    assert out[0] is fl._LOCALS[key] and inner[0] is out[0], "the re-entry and the outer section were given different objects for one lock file"


def test_a_statistic_noted_inside_a_registry_section_is_applied_after_it_and_a_walk_is_never_changed_under_its_feet(monkeypatch):
    """``stats`` walks ``_STATS`` and a finalizer's record can note a NEW file name in the middle (a walk over a dict that gains a key raises). The re-entrant
    note is held and applied once the section ends."""
    import threading

    from src.safety import file_lock as fl

    class _Row(dict):
        def __iter__(self):  # overriding it makes ``dict(row)`` ask for ``keys()`` instead of copying in C
            return super().__iter__()

        def keys(self):
            fl._note("new.jsonl", "max_wait_s", 2.0)
            return super().keys()

    table: dict = {"old.jsonl": _Row({"max_wait_s": 0.0, "max_hold_s": 0.0})}
    monkeypatch.setattr(fl, "_STATS", table)
    out: list = []

    def run():
        try:
            out.append(fl.stats())
        except RuntimeError as fault:  # "dictionary changed size during iteration" is the failure this pins
            out.append(fault)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(20)
    assert out and isinstance(out[0], dict), out
    assert "old.jsonl" in out[0] and "new.jsonl" not in out[0]
    assert fl.stats()["new.jsonl"]["max_wait_s"] == 2.0


def test_the_registry_section_is_reentrant_for_the_same_thread():
    from src.safety import file_lock as fl

    with fl._registry():
        fl._note("held.jsonl", "max_wait_s", 1.5)
        assert "held.jsonl" not in fl._STATS
        with fl._registry():
            assert fl._local("x.lock") is fl._local("x.lock")
    assert fl._STATS["held.jsonl"]["max_wait_s"] == 1.5


# --- the folds of the independent read (25 Oct) ----------------------------------------------------------------------------------------------------


def _another_thread_takes_it(target: Path) -> bool:
    """True when a second thread gets the lock within 10 s (a daemon thread, so a stuck lock fails this test and does not hang the suite)."""
    got = threading.Event()

    def run() -> None:
        with lock(target):
            got.set()

    threading.Thread(target=run, daemon=True).start()
    return got.wait(10)


def test_an_interrupt_in_the_hold_statistic_after_the_section_leaves_nothing_held(tmp_path, monkeypatch):
    """The count at the end of a section takes the registry lock and allocates: an interrupt there used to skip the release that came after it."""
    fcntl = pytest.importorskip("fcntl")
    target = tmp_path / "f"
    real = file_lock._note

    def interrupted(name, field, seconds):
        if field == "max_hold_s":
            raise KeyboardInterrupt
        real(name, field, seconds)

    monkeypatch.setattr(file_lock, "_note", interrupted)
    with pytest.raises(KeyboardInterrupt), lock(target):
        pass
    monkeypatch.setattr(file_lock, "_note", real)
    assert _another_thread_takes_it(target), "the in-process gate stayed held"
    with open(tmp_path / "f.lock", "a+b") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises BlockingIOError if this process still holds the operating-system lock


def test_an_interrupt_between_the_gate_marks_and_the_end_of_the_gate_leaves_nothing_held(tmp_path, monkeypatch):
    """The reader mark goes in and an interrupt lands right after it: what to give back is read from the gate, not from a flag set a line later."""

    class MarkThenInterrupt(set):
        armed = True

        def add(self, item):
            super().add(item)
            if MarkThenInterrupt.armed:
                MarkThenInterrupt.armed = False
                raise KeyboardInterrupt

    target = tmp_path / "f"
    real = file_lock._local

    def local(key):
        got = real(key)
        if not isinstance(got.reader_threads, MarkThenInterrupt):
            got.reader_threads = MarkThenInterrupt(got.reader_threads or ())
        return got

    monkeypatch.setattr(file_lock, "_local", local)
    with pytest.raises(KeyboardInterrupt), lock(target, shared=True):
        pytest.fail("the body must not run")
    assert _another_thread_takes_it(target), "an exclusive take waits for ever on a reader that is not there"


def test_one_file_under_two_spellings_of_its_path_raises_instead_of_deadlocking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outcome: list[BaseException | str] = []

    def run() -> None:
        with lock(tmp_path / "a.json"):
            try:
                with lock(Path("a.json")):
                    outcome.append("took it twice")
            except RuntimeError as fault:
                outcome.append(fault)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive(), "the second spelling waited for ever on the operating-system lock this thread holds"
    assert isinstance(outcome[0], RuntimeError)


def test_a_failed_fsync_keeps_the_old_file_and_removes_the_temp_but_a_filesystem_without_fsync_still_writes(tmp_path, monkeypatch):
    target = tmp_path / "marker"
    target.write_text("good", encoding="utf-8")

    def eio(fd):
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(file_lock.os, "fsync", eio)
    with pytest.raises(OSError):
        atomic_replace(target, "new")
    assert target.read_text(encoding="utf-8") == "good", "data that never reached the disk was renamed over the good file"
    assert [p.name for p in tmp_path.iterdir() if ".tmp" in p.name] == []

    def einval(fd):
        raise OSError(errno.EINVAL, "no fsync here")

    monkeypatch.setattr(file_lock.os, "fsync", einval)
    atomic_replace(target, "new")
    assert target.read_text(encoding="utf-8") == "new"

    for code in (errno.ENOSYS, errno.EOPNOTSUPP):  # the other ways a filesystem says it has no fsync

        def none_here(fd, code=code):
            raise OSError(code, "no fsync here")

        monkeypatch.setattr(file_lock.os, "fsync", none_here)
        atomic_replace(target, f"written-{code}")
        assert target.read_text(encoding="utf-8") == f"written-{code}"


def test_one_file_through_a_symlinked_folder_raises_instead_of_deadlocking(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    outcome: list[BaseException | str] = []

    def run() -> None:
        with lock(real / "a.json"):
            try:
                with lock(link / "a.json"):
                    outcome.append("took it twice")
            except RuntimeError as fault:
                outcome.append(fault)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive(), "the second spelling waited for ever on the operating-system lock this thread holds"
    assert isinstance(outcome[0], RuntimeError)
