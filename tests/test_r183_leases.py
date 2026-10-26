"""R183: with several servers on one data folder, a live holder is skipped and a dead one is taken over.

The three claims that mean "a job is running here" (the corpus lease, the rollup build marker, the backup staging owner file) share one owner record and one verdict
(``src/safety/process_owner.py``): alive = skip, dead = take over, unknown = never taken over, named.
"""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.analytics import rollup_marker
from src.database import corpus_lease
from src.safety import process_owner

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    yield tmp_path
    rollup_marker.clear()


def _child(code: str, data: Path) -> subprocess.Popen:
    """A second server: runs ``code`` with the same data folder, prints READY once its claim is written, then waits to be killed."""
    env = {**os.environ, "OO_DATA_DIR": str(data), "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen(
        [sys.executable, "-c", code + "\nprint('READY', flush=True)\nimport time\ntime.sleep(120)\n"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True,
    )
    assert proc.stdout is not None and proc.stdout.readline().strip() == "READY"
    return proc


def _kill(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=30)


def test_the_owner_verdict_tells_alive_dead_and_unknown_apart(data):
    mine = process_owner.owner_record()
    assert mine["pid"] == os.getpid()
    assert process_owner.record_state(mine) == "unknown", "this process's own claim is judged by its own registry"
    proc = _child("pass", data)
    try:
        theirs = process_owner.owner_record()  # not the child's: ask the child
        out = subprocess.run(
            [sys.executable, "-c", "import json;from src.safety import process_owner as p;print(json.dumps(p.owner_record()))"],
            cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True, check=True,
        ).stdout
        gone = json.loads(out)  # that process has exited by now
        assert process_owner.record_state(gone, machine=process_owner.machine_tag()) == "dead"
        assert process_owner.record_state({**theirs, "pid": proc.pid, "started": 1.0}, machine=process_owner.machine_tag()) == "dead", "a recycled pid is another process"
        live = {"pid": proc.pid, "started": __import__("psutil").Process(proc.pid).create_time(), "host": platform.node(), "machine": process_owner.machine_tag()}
        assert process_owner.record_state(live, machine=process_owner.machine_tag()) == "alive"
    finally:
        _kill(proc)
    assert process_owner.record_state(live, machine=process_owner.machine_tag()) == "dead"
    assert process_owner.record_state({**live, "host": "another-" + platform.node()}) == "unknown"
    assert process_owner.record_state({"pid": "x"}) == "unknown"
    assert process_owner.record_state(None) == "unknown"


def test_a_lease_leaves_a_file_while_held_and_none_after(data):
    with corpus_lease.corpus_lease("reindex"):
        files = list((data / "leases").glob("*.lease"))
        assert [f.name.split(".")[0] for f in files] == ["reindex"]
        with corpus_lease.corpus_lease("reindex"):  # nested: still one file
            assert len(list((data / "leases").glob("*.lease"))) == 1
        assert len(list((data / "leases").glob("*.lease"))) == 1
        assert corpus_lease.active_leases() == ["reindex"]
    assert list((data / "leases").glob("*.lease")) == []
    assert corpus_lease.active_leases() == []


def test_a_second_servers_live_lease_is_seen_and_a_killed_ones_is_taken_over(data):
    proc = _child("from src.database import corpus_lease as c\nl = c.corpus_lease('reindex'); l.__enter__()", data)
    try:
        assert corpus_lease.active_leases() == ["reindex"], "a swap here must see the batch in flight in the other server"
        assert corpus_lease.wait_for_quiescence(0.2, poll=0.05) == ["reindex"], "and refuse, naming it"
    finally:
        _kill(proc)
    assert corpus_lease.active_leases() == [], "the holder is dead: its lease is a leftover"
    assert list((data / "leases").glob("*.lease")) == [], "and the takeover removes the file"


def test_a_lease_this_machine_cannot_judge_is_held_and_named(data):
    (data / "leases").mkdir()
    other = {"pid": 1, "started": 1.0, "host": "another-" + platform.node(), "machine": None, "name": "newsletter-import", "process": "x"}
    (data / "leases" / "newsletter-import.x.lease").write_text(json.dumps(other), encoding="utf-8")
    (data / "leases" / "garbled.y.lease").write_text("{not json", encoding="utf-8")
    assert corpus_lease.active_leases() == ["garbled", "newsletter-import"], "unknown = fail closed: a swap refuses rather than swaps under someone"


def test_a_lease_that_cannot_be_written_leaves_the_in_process_lease_standing(data, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(data / "plain-file"))
    (data / "plain-file").write_text("a file where the folder should be", encoding="utf-8")
    monkeypatch.setattr(corpus_lease, "_FILE_WARNED", False)
    with corpus_lease.corpus_lease("reindex"):
        assert "reindex" in corpus_lease.active_leases()
    assert corpus_lease.active_leases() == []


def _marker_child(data: Path) -> subprocess.Popen:
    return _child("from src.analytics import rollup_marker as m\nm.begin(rss_mb=500.0, avail_mb=3000.0, limit_mb=740.0)", data)


def test_a_live_second_servers_build_is_not_a_kill_and_blocks_a_second_build(data):
    proc = _marker_child(data)
    try:
        assert rollup_marker.read()["stage"] == "start"
        assert rollup_marker.killed_build() is None, "a running build is not a killed one"
        assert rollup_marker.running_elsewhere() is not None
        verdict = rollup_marker.retry_verdict(avail_mb=10_000.0, floor_mb=100.0)
        assert verdict and verdict["reason"] == rollup_marker.ELSEWHERE
        assert rollup_marker.begin(rss_mb=500.0, avail_mb=3000.0, limit_mb=740.0) is False, "the claim is checked under the lock, not only before it"
        assert rollup_marker.read()["process"] != rollup_marker._PROCESS_ID, "and the other server's record is left whole"
        rollup_marker.clear()
        assert rollup_marker.read() is not None, "a record of another process's build is not ours to remove"
    finally:
        _kill(proc)
    # the owner is dead now: the same file reads as a killed build, and the next build takes over
    assert rollup_marker.running_elsewhere() is None
    assert rollup_marker.killed_build() is not None
    assert rollup_marker.retry_verdict(avail_mb=10_000.0, floor_mb=100.0) is None
    assert rollup_marker.begin(rss_mb=500.0, avail_mb=3000.0, limit_mb=740.0) is True
    assert rollup_marker.read()["process"] == rollup_marker._PROCESS_ID


def test_a_marker_with_no_owner_field_is_judged_as_before(data):
    (data / "rollup_build.json").write_text(
        json.dumps({"format": rollup_marker.FORMAT, "process": "an-older-process", "stage": "keywords", "rows_done": 5, "rss_mb": 900.0, "rss_begin_mb": 100.0}),
        encoding="utf-8",
    )
    assert rollup_marker.killed_build() is not None
    assert rollup_marker.running_elsewhere() is None


def test_a_marker_from_a_host_this_machine_cannot_judge_is_a_build_elsewhere(data):
    owner = {"pid": 1, "started": 1.0, "host": "another-" + platform.node(), "machine": None}
    (data / "rollup_build.json").write_text(
        json.dumps({"format": rollup_marker.FORMAT, "process": "theirs", "owner": owner, "stage": "mentions", "rows_done": 5}), encoding="utf-8"
    )
    assert rollup_marker.running_elsewhere() is not None and rollup_marker.killed_build() is None
    assert rollup_marker.begin(rss_mb=1.0, avail_mb=1.0, limit_mb=1.0) is False


def test_two_servers_writing_progress_never_leave_a_torn_marker(data):
    rollup_marker.begin(rss_mb=500.0, avail_mb=3000.0, limit_mb=740.0)
    time.sleep(0.01)
    for stage in ("mentions", "keywords", "aggregate"):  # a stage change bypasses the throttle: every call writes
        rollup_marker.progress(stage, 1, rss_mb=600.0, avail_mb=2000.0)
        rec = json.loads((data / "rollup_build.json").read_text(encoding="utf-8"))
        assert rec["stage"] == stage and rec["owner"]["pid"] == os.getpid()
    assert not list(data.glob("rollup_build.json.tmp*")), "the temp name is unique and removed"


# --- the Opus read's findings on the first push (312c2b4b6) ---------------------------------------------------------------------------------------------------------


def test_a_matching_machine_tag_does_not_override_another_hostname(data):
    """Machine ids are copied with cloned images, so two hosts can share one: a different hostname stays unjudgeable (a swept neighbour is data loss; a drifted host is named and cleared by hand)."""
    machine = "m" * 16
    gone = {"pid": 2**22 - 3, "started": 1.0, "host": "old-" + platform.node(), "machine": machine}
    assert process_owner.record_state(gone, machine=machine) == "unknown"
    assert process_owner.record_state({**gone, "host": platform.node()}, machine=machine) == "dead"
    assert process_owner.record_state({**gone, "machine": "n" * 16}, machine=machine) == "unknown", "another machine's tag is still not ours to judge"
    assert process_owner.record_state({**gone, "machine": None}, machine=None) == "unknown", "no machine tag (macOS, Windows): a changed host cannot be judged"


def test_an_empty_or_garbled_lease_file_is_held_while_young_and_swept_when_old(data, caplog):
    (data / "leases").mkdir()
    empty = data / "leases" / "reindex.z.lease"
    empty.write_text("", encoding="utf-8")
    assert corpus_lease.active_leases() == ["reindex"], "a young unreadable file may be a writer on a drive whose rename is not atomic"
    old = time.time() - corpus_lease._UNREADABLE_GRACE_S - 5
    os.utime(empty, (old, old))
    assert corpus_lease.active_leases() == [], "an old one is a leftover of a crash before the data reached the disk"
    assert not empty.exists()


def test_the_refusal_names_the_file_and_prints_the_owner_fields_unchanged(data):
    (data / "leases").mkdir()
    other = {"pid": 7, "started": 12.5, "host": "elsewhere", "machine": None, "name": "reindex", "process": "x"}
    f = data / "leases" / "reindex.x.lease"
    f.write_text(json.dumps(other), encoding="utf-8")
    note = corpus_lease.foreign_note(["reindex"])
    assert "leases/reindex.x.lease" in note and str(data) not in note and '"pid": 7' in note and '"started": 12.5' in note and '"host": "elsewhere"' in note and "unknown" in note
    assert corpus_lease.foreign_note(["nothing-held"]) == ""
    with corpus_lease.corpus_lease("mine"):
        assert corpus_lease.foreign_note(["mine"]) == "", "this process's own lease is not a neighbour"


def test_an_interrupt_between_the_file_and_the_count_does_not_leave_the_file(data, monkeypatch):
    real = corpus_lease._write_file

    def write_then_interrupt(name):
        real(name)
        raise KeyboardInterrupt

    monkeypatch.setattr(corpus_lease, "_write_file", write_then_interrupt)
    with pytest.raises(KeyboardInterrupt), corpus_lease.corpus_lease("reindex"):
        pass
    assert list((data / "leases").glob("*.lease")) == []
    assert corpus_lease.active_leases() == []


def test_an_empty_owner_record_is_not_kept_for_every_later_lease(data, monkeypatch):
    monkeypatch.setattr(corpus_lease, "_OWNER", None)
    calls = iter([{}, {"pid": 1, "started": 1.0, "host": "h", "machine": None}])
    monkeypatch.setattr(process_owner, "owner_record", lambda: next(calls))
    with corpus_lease.corpus_lease("a"):
        pass
    with corpus_lease.corpus_lease("b"):
        rec = json.loads(next((data / "leases").glob("b.*.lease")).read_text(encoding="utf-8"))
        assert rec.get("pid") == 1, "the second take asked again instead of reusing the empty answer"


def test_a_lease_file_that_cannot_be_read_is_never_aged_out(data, monkeypatch):
    (data / "leases").mkdir()
    f = data / "leases" / "reindex.q.lease"
    f.write_text(json.dumps({"pid": 1, "started": 1.0, "host": "h", "machine": None, "name": "reindex", "process": "q"}), encoding="utf-8")
    old = time.time() - 3600
    os.utime(f, (old, old))
    real = Path.read_text

    def deny(self, *a, **k):
        if self.suffix == ".lease":
            raise PermissionError
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", deny)
    assert corpus_lease.active_leases() == ["reindex"] and f.exists(), "no read says nothing about the owner"


def test_the_interrupt_cleanup_leaves_a_file_another_thread_now_owns(data, monkeypatch):
    real = corpus_lease._write_file

    def interrupted(name):
        real(name)
        # the gap after this thread's lock is released: another thread takes the same name
        corpus_lease._HELD[name] = 1
        raise KeyboardInterrupt

    monkeypatch.setattr(corpus_lease, "_write_file", interrupted)
    try:
        with pytest.raises(KeyboardInterrupt), corpus_lease.corpus_lease("reindex"):
            pass
        assert len(list((data / "leases").glob("*.lease"))) == 1
    finally:
        corpus_lease._HELD.pop("reindex", None)
