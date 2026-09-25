"""A paused download says WHO paused it (S04-08's S5, Q1014).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before, a download held by airplane mode, one the operator paused, and one the process
left mid-transfer all read as a bare "paused" with no error. The first is this app's
own setting holding the transfer (invariant #14e's corollary: a refusal by the kill
switch is named as such wherever it surfaces), and the operator needs to tell it apart
from their own Pause before deciding whether to go online. Each path that pauses now
records its cause, and the task manager (``_jobWhy``, driven in node) says it.

Both download owners are exercised, because they are two copies of one state machine:
a fix to one that misses the other is the recorded shape of this repo's drift.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import threading
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


class _SlowResp:
    status_code = 200
    headers = {"Content-Length": "30"}

    def __init__(self, gate: threading.Event):
        self._gate = gate

    def raise_for_status(self):
        pass

    def iter_content(self, _chunk):
        for _ in range(3):
            self._gate.wait(5)
            yield b"0123456789"


def _wait_until(predicate, tries=250, delay=0.02):
    for _ in range(tries):
        if predicate():
            return True
        time.sleep(delay)
    return False


def _dump(base, gate):
    from src.wiki.dumps import DumpDownloadManager

    return DumpDownloadManager(base_dir=base, http_get=lambda u, h: _SlowResp(gate), max_concurrent=1)


def _osm(base, gate):
    from src.geo.osm_downloads import OsmDownloadManager

    return OsmDownloadManager(base_dir=base, http_get=lambda u, h: _SlowResp(gate), max_concurrent=1)


#: (factory, first item, second item) for each owner.
OWNERS = {
    "dump": (_dump, "en", "fr"),
    "osm": (_osm, "europe", "asia"),
}


def _entry(mgr, item):
    return next(e for e in mgr.list() if item in (e.get("wiki"), e.get("key"), e.get("region")))


@pytest.fixture()
def airplane():
    from src.ingest import activate_kill_switch, clear_kill_switch

    clear_kill_switch()
    try:
        yield activate_kill_switch
    finally:
        clear_kill_switch()


@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_the_pause_button_is_the_OPERATOR(owner, tmp_path):
    make, first, _second = OWNERS[owner]
    gate = threading.Event()
    mgr = make(tmp_path, gate)
    try:
        mgr.start(first)
        assert _wait_until(lambda: _entry(mgr, first)["status"] == "downloading")
        assert mgr.pause(_entry(mgr, first)["key"]) is True
        gate.set()
        assert _wait_until(lambda: _entry(mgr, first)["status"] == "paused")
        assert _entry(mgr, first)["paused_by"] == "operator"
    finally:
        gate.set()


@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_pausing_a_QUEUED_download_is_the_operator_too(owner, tmp_path):
    make, first, second = OWNERS[owner]
    gate = threading.Event()
    mgr = make(tmp_path, gate)
    try:
        mgr.start(first)
        assert _wait_until(lambda: _entry(mgr, first)["status"] == "downloading")
        mgr.start(second)  # capacity 1: queues
        assert mgr.pause(_entry(mgr, second)["key"]) is True
        assert _entry(mgr, second)["paused_by"] == "operator"
    finally:
        gate.set()


@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_airplane_mode_MID_DOWNLOAD_is_named_as_airplane_mode(owner, tmp_path, airplane):
    make, first, _second = OWNERS[owner]
    gate = threading.Event()
    mgr = make(tmp_path, gate)
    try:
        mgr.start(first)
        assert _wait_until(lambda: _entry(mgr, first)["status"] == "downloading")
        airplane()
        gate.set()
        assert _wait_until(lambda: _entry(mgr, first)["status"] == "paused")
        e = _entry(mgr, first)
        assert e["paused_by"] == "airplane", "the kill switch read as the operator's own pause"
        assert e["error"] is None, "a pause is not a failure"
    finally:
        gate.set()


@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_starting_UNDER_airplane_mode_is_named_as_airplane_mode(owner, tmp_path, airplane):
    make, first, _second = OWNERS[owner]
    gate = threading.Event()
    gate.set()
    mgr = make(tmp_path, gate)
    airplane()
    mgr.start(first)
    e = _entry(mgr, first)
    assert e["status"] == "paused"
    assert e["paused_by"] == "airplane"


@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_a_RESTART_mid_download_is_named_as_the_restart(owner, tmp_path):
    make, first, _second = OWNERS[owner]
    gate = threading.Event()
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    mgr = make(one, gate)
    try:
        mgr.start(first)
        assert _wait_until(lambda: _entry(mgr, first)["status"] == "downloading")
        assert _wait_until(lambda: '"downloading"' in mgr.state_path.read_text("utf-8"))
        # The state as a process that died now would leave it, loaded by the next one.
        # Without the owner's in-flight "*.tmp": it saves by write-then-rename from its
        # own thread, so a tmp file listed a moment ago can be gone when it is copied
        # (seen once in a full serial run), and a dead process leaves no such file anyway.
        shutil.copytree(one, two, ignore=shutil.ignore_patterns("*.tmp"))
    finally:
        gate.set()
    again = make(two, threading.Event())
    e = _entry(again, first)
    assert e["status"] == "paused"
    assert e["paused_by"] == "restart"


@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_the_cause_is_reported_ONLY_while_paused(owner, tmp_path):
    """A stale cause beside a running or failed download would explain the wrong thing."""
    make, first, _second = OWNERS[owner]
    gate = threading.Event()
    mgr = make(tmp_path, gate)
    try:
        mgr.start(first)
        assert _wait_until(lambda: _entry(mgr, first)["status"] == "downloading")
        key = _entry(mgr, first)["key"]
        mgr._entries[key].paused_by = "operator"  # left over from an earlier pause
        assert _entry(mgr, first)["paused_by"] is None
    finally:
        gate.set()
    assert _wait_until(lambda: _entry(mgr, first)["status"] == "done")
    assert _entry(mgr, first)["paused_by"] is None


def test_a_state_file_WITHOUT_the_field_still_loads(tmp_path):
    """An install upgrading from before the field: every old entry loads, cause unknown."""
    gate = threading.Event()
    mgr = _dump(tmp_path, gate)
    try:
        mgr.start("en")
        assert _wait_until(lambda: _entry(mgr, "en")["status"] == "downloading")
        assert mgr.pause(_entry(mgr, "en")["key"]) is True
        gate.set()
        assert _wait_until(lambda: _entry(mgr, "en")["status"] == "paused")
    finally:
        gate.set()
    raw = json.loads(mgr.state_path.read_text("utf-8"))
    entries = raw.get("entries", raw)
    for v in entries.values():
        v.pop("paused_by", None)
    mgr.state_path.write_text(json.dumps(raw), "utf-8")
    again = _dump(tmp_path, threading.Event())
    e = _entry(again, "en")
    assert e["status"] == "paused" and e["paused_by"] is None


@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_the_jobs_view_carries_the_cause(owner, tmp_path, monkeypatch, airplane):
    from src.api import jobs
    from src.geo import osm_downloads
    from src.wiki import dumps

    make, first, _second = OWNERS[owner]
    gate = threading.Event()
    gate.set()
    mgr = make(tmp_path, gate)
    module = dumps if owner == "dump" else osm_downloads
    monkeypatch.setattr(module, "get_manager", lambda: mgr)
    airplane()
    mgr.start(first)
    rows = jobs._dump_jobs() if owner == "dump" else jobs._osm_jobs()
    (row,) = rows
    assert row["state"] == "paused"
    assert row["paused_by"] == "airplane"


def test_the_task_manager_line_runs_as_real_code():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "job_why_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout
