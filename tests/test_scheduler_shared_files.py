"""The scheduler's shared files take the cross-process lock and a unique temp (R176).

Before: the pass journal's trim read the file and swapped a temp over it, so a line a second server appended in between was lost; the memory-stop record and the
capacity state were each replaced through ONE fixed ``.tmp`` name, so two servers writing at once left a half file. What is pinned: a trim never loses a line
another process appends, and the two whole-file states are moved into place from a temp named for the process and the thread."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.scheduler import capacity, memstop, pass_journal


@pytest.fixture
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def test_a_pass_journal_trim_never_loses_a_line_another_process_appends(dd, monkeypatch):
    monkeypatch.setattr(pass_journal, "_MAX_LINES", 100)
    root = str(Path(pass_journal.__file__).parents[2])
    script = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {root!r})
        os.environ["OO_DATA_DIR"] = {str(dd)!r}
        from src.scheduler import pass_journal
        for i in range(300):
            pass_journal._append({{"kind": "probe", "n": i}})
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script])
    while child.poll() is None:
        pass_journal.trim()
    child.wait()
    got = [json.loads(ln)["n"] for ln in pass_journal._path().read_text().splitlines()]
    assert got == list(range(300 - len(got), 300)), "a line appended by the other process was lost by a trim"
    assert got


def _spy_replace(monkeypatch):
    seen: list[str] = []
    real = os.replace
    monkeypatch.setattr("src.safety.file_lock.os.replace", lambda a, b: (seen.append(os.fspath(a)), real(a, b))[1])
    return seen


def test_the_memory_stop_record_is_replaced_through_a_unique_temp(dd, monkeypatch):
    seen = _spy_replace(monkeypatch)
    assert memstop._write({"kind": "memstop", "session_id": "s", "pid": 1, "at": "x", "uptime_s": 1.0, "decision": {}}) is not None
    assert seen and all(f".tmp.{os.getpid()}." in n for n in seen), seen
    assert not list(dd.glob("*.tmp*"))


def test_the_capacity_state_is_replaced_through_a_unique_temp(dd, monkeypatch):
    seen = _spy_replace(monkeypatch)
    target = dd / "collect_capacity.json"
    capacity._save(target, {"a": 1})
    assert seen and all(f".tmp.{os.getpid()}." in n for n in seen), seen
    assert json.loads(target.read_text()) == {"a": 1}
