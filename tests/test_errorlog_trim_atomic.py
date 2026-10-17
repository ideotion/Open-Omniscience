"""The error journal's trim moves a finished temp over the file and never truncates it in place (R175).

Before: past 512 KiB the trim read the file and wrote the newest 2,000 lines back over it with write_text, which empties the file first. A crash inside it (the
journal exists for crashes) left no journal; a second process appending between the read and the write lost its line (read from the code, 17 Oct). What is
pinned: a process that dies at the moment of the swap leaves the old file whole, byte for byte; two writers never share a temp name; a temp a dead process left is
swept and a live process's is not; and the kept lines are the same bytes as before."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.monitoring import errorlog


def _big(path: Path, n: int = 6000) -> bytes:
    pad = "x" * 100
    data = "".join(f'{{"at":"2026-10-17T07:00:00+00:00","n":{i},"pad":"{pad}"}}\n' for i in range(n)).encode()
    path.write_bytes(data)
    assert len(data) > 512 * 1024
    return data


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path / "app_errors.jsonl"


def test_the_kept_lines_are_the_same_bytes_as_before(journal):
    data = _big(journal)
    errorlog._trim(journal)
    want = b"\n".join(data.splitlines()[-errorlog._CAP:]) + b"\n"
    assert journal.read_bytes() == want
    assert not list(journal.parent.glob("app_errors.jsonl.tmp.*"))


def test_a_process_that_dies_at_the_swap_leaves_the_old_file_whole_and_the_next_trim_sweeps_its_temp(journal, tmp_path):
    data = _big(journal)
    script = textwrap.dedent(
        f"""
        import os, sys
        from pathlib import Path
        sys.path.insert(0, {str(Path(errorlog.__file__).parents[2])!r})
        os.environ["OO_DATA_DIR"] = {str(tmp_path)!r}
        from src.monitoring import errorlog
        def _die(*a, **k): os._exit(9)
        os.replace = _die                      # the swap: the process dies as it begins
        _real = Path.write_text
        def _truncating(self, *a, **k):        # what an in-place write does first: empty the file, then die
            open(self, "w").close(); os._exit(9)
        Path.write_text = _truncating
        errorlog._trim(Path({str(journal)!r}))
        """
    )
    done = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 9, done.stderr
    assert journal.read_bytes() == data, "the journal was not whole after a death at the swap"
    left = list(journal.parent.glob("app_errors.jsonl.tmp.*"))
    assert len(left) == 1  # the dead process's temp, named for its pid
    errorlog._trim(journal)
    assert not list(journal.parent.glob("app_errors.jsonl.tmp.*")), "a dead process's temp was not swept"


def test_a_live_processs_temp_is_not_swept(journal):
    _big(journal)
    live = journal.with_name(f"app_errors.jsonl.tmp.{os.getppid()}.1")  # the process that started the tests runs
    live.write_text("half", encoding="utf-8")
    errorlog._trim(journal)
    assert live.exists()


def test_two_writers_never_share_a_temp_name(journal, monkeypatch):
    _big(journal)
    seen: list[str] = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append(Path(a).name), real(a, b))[1])
    errorlog._trim(journal)
    monkeypatch.setattr(os, "getpid", lambda: 999_999_001)
    _big(journal)
    errorlog._trim(journal)
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(n.startswith("app_errors.jsonl.tmp.") for n in seen)


def test_a_failed_swap_removes_its_own_temp_and_the_journal_stays(journal, monkeypatch):
    data = _big(journal)

    def boom(a, b):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        errorlog._trim(journal)
    assert journal.read_bytes() == data
    assert not list(journal.parent.glob("app_errors.jsonl.tmp.*"))


def test_a_record_raised_while_the_journal_is_locked_by_the_same_thread_is_written_after_it_not_waited_for(journal, monkeypatch):
    """The garbage collector runs a finalizer (SQLAlchemy's reports a collected connection) inside the trim; the finalizer logs; the record came back into the
    locked ``_append`` on the same thread and waited for its own lock for ever (a full-suite run of 17 Oct, 20 minutes)."""
    import threading

    _big(journal, 6000)
    fired = []

    def a_finalizer_that_logs(path):
        if not fired:
            fired.append(1)
            errorlog._append({"at": "2026-10-17T00:00:00+00:00", "n": "nested-record"})

    monkeypatch.setattr(errorlog, "_sweep_dead_temps", a_finalizer_that_logs)
    done = threading.Event()
    threading.Thread(target=lambda: (errorlog._append({"at": "2026-10-17T00:00:00+00:00", "n": "outer-record"}), done.set()), daemon=True).start()
    assert done.wait(20), "the journal waited on a lock its own thread holds"
    text = journal.read_text(encoding="utf-8")
    assert '"outer-record"' in text and '"nested-record"' in text


class _FinalizerDict(dict):
    """A dict whose first ``get`` does what a garbage-collector finalizer does at an allocation: it logs a record on the thread that holds the journal lock."""

    def get(self, *args, **kwargs):
        if not getattr(self, "fired", False):
            self.fired = True
            errorlog._append({"at": "2026-10-17T00:00:00+00:00", "n": "nested-record"})
        return super().get(*args, **kwargs)


@pytest.mark.parametrize("which", ["http", "frontend"])
def test_a_record_raised_while_a_throttle_holds_the_journal_lock_is_written_after_it_not_waited_for(journal, monkeypatch, which):
    """``note_http_error`` and ``note_frontend_error`` hold the same plain lock while they touch their throttle dict; a finalizer that logs there waited for the
    lock its own thread held. The record is held and written once the lock is let go (not through an RLock: a record written mid-change would see half a state)."""
    import threading

    monkeypatch.setattr(errorlog, "_http_last" if which == "http" else "_frontend_last", _FinalizerDict())
    call = (lambda: errorlog.note_http_error("GET", "/x", 500)) if which == "http" else (lambda: errorlog.note_frontend_error("js", "boom"))
    done = threading.Event()
    threading.Thread(target=lambda: (call(), done.set()), daemon=True).start()
    assert done.wait(20), "the journal waited on a lock its own thread holds"
    assert '"nested-record"' in journal.read_text(encoding="utf-8")


def test_an_interrupt_leaving_the_locked_append_still_writes_the_records_held_meanwhile(journal, monkeypatch):
    """A record logged by a finalizer while the lock is held is written after the lock is let go, also when the body is left by an interrupt (not an ``Exception``)."""
    _big(journal, 6000)
    fired = []

    def interrupted(path):
        if not fired:
            fired.append(1)
            errorlog._append({"at": "2026-10-17T00:00:00+00:00", "n": "held-record"})
            raise KeyboardInterrupt

    monkeypatch.setattr(errorlog, "_sweep_dead_temps", interrupted)
    with pytest.raises(KeyboardInterrupt):
        errorlog._append({"at": "2026-10-17T00:00:00+00:00", "n": "outer-record"})
    assert '"held-record"' in journal.read_text(encoding="utf-8")
