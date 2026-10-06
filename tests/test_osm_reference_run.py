"""The measured OSM ingest as one command (0.5 row D, S05-04): ``scripts/osm_reference_run.py``.

Fixture scale: the app's own scripts run as real children on row D's synthetic extract, so what is
proved is the INSTRUMENT -- its report, its guards and its cleanliness -- never the 2-core, 3.5 GB
VM, whose numbers only that VM's run can produce.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import osm_reference_run as CLI
from src.osm import reference_run as R
from tests._osm_lane_helpers import FIXTURE, HAVE_OSMIUM, ROOT

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the reference run is Linux-only")

HISTORY = ROOT / "tests" / "fixtures" / "osm" / "synthetic-history.osm.pbf"
GB = R.GIB


class _Probe(R.Probe):
    """A probe whose free disk and available memory are scripted; the real one is the default."""

    def __init__(self, free=100 * GB, avail=8 * GB, free_after=None, avail_after=None, after_calls=3, trigger=None,
                 release=None):
        """``trigger`` (a callable) flips the scripted values when it returns True, instead of a call count,
        so a test waits on the CHILD's own readiness rather than on the clock; ``release=(path, n)`` creates
        ``path`` at the n-th disk read, so a child can run exactly as long as the sampler has sampled."""
        self._free, self._avail = free, avail
        self._free_after, self._avail_after, self._after = free_after, avail_after, after_calls
        self._trigger, self._release = trigger, release
        self.calls = 0
        super().__init__(free_disk=self._f, available_memory=self._m)

    def _flipped(self) -> bool:
        return self._trigger() if self._trigger is not None else self.calls > self._after

    def _f(self, _p):
        self.calls += 1
        if self._release is not None and self.calls >= self._release[1]:
            Path(self._release[0]).write_text("go", encoding="utf-8")
        if self._free_after is not None and self._flipped():
            return self._free_after
        return self._free

    def _m(self):
        if self._avail_after is not None and self._flipped():
            return self._avail_after
        return self._avail


def _extract(tmp_path: Path, src: Path = FIXTURE) -> Path:
    d = tmp_path / "inputs"
    d.mkdir(exist_ok=True)
    p = d / src.name
    p.write_bytes(src.read_bytes())
    return p


def _run(tmp_path, **kw):
    kw.setdefault("workdir", tmp_path / "work")
    kw.setdefault("sample_seconds", 0.1)
    return R.run(extract=_extract(tmp_path), country="ZZ", **kw)


def _scripted(code: str, name: str = "scripted") -> list[R.PhaseSpec]:
    return [R.PhaseSpec(name, [sys.executable, "-c", code])]


# --------------------------------------------------------------------------- #
#  the real ingest, measured
# --------------------------------------------------------------------------- #


def test_a_real_run_writes_one_complete_report_and_deletes_its_own_store(tmp_path, monkeypatch):
    # The caller's own data directory must never be opened: point OO_DATA_DIR at a sentinel.
    real = tmp_path / "users_real_store"
    real.mkdir()
    (real / "sentinel").write_text("x", encoding="utf-8")
    monkeypatch.setenv("OO_DATA_DIR", str(real))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")  # the children must NOT inherit this

    report, kept = _run(tmp_path, gazetteer="osm-only", gazetteer_out=tmp_path / "out" / "g.yml")
    assert report["status"] == "ok" and kept is None

    names = [p["name"] for p in report["phases"]]
    assert names == ["ingest", "gazetteer"]
    ing = report["phases"][0]
    assert ing["status"] == "ok" and ing["exit_code"] == 0 and ing["wall_seconds"] > 0
    assert ing["peak_rss_bytes"] > 0 and ing["peak_rss_bytes_kernel"] > 0 and ing["peak_data_dir_bytes"] > 0
    assert ing["cpu_user_seconds"] is not None and ing["samples"] >= 1 and ing["timeline"]
    assert ing["disk_free_min_bytes"] <= ing["disk_free_before_bytes"]
    assert ing["app_report"]["alpha3"] == "ZZZ" and ing["app_report"]["osm_db_bytes"] > 0

    assert report["outputs"]["osm_db_bytes"] == ing["app_report"]["osm_db_bytes"]
    assert report["outputs"]["gazetteer"]["name"] == "g.yml" and report["outputs"]["gazetteer"]["sha256"]
    # The encrypted path really ran: the app's own header read says so, not our say-so.
    assert report["at_rest"]["osm_db_encrypted_by_header"] is True

    # The store was deleted as the LAST step and the report says what went.
    assert report["store"]["kept"] is False and report["store"]["deleted"] is True
    assert report["store"]["bytes_freed"] > 0
    assert not list((tmp_path / "work").glob("oo-osm-reference-run-*"))

    # The user's own store was never touched, and nothing was created in it.
    assert sorted(p.name for p in real.iterdir()) == ["sentinel"]

    host = report["host"]
    assert host["cpu_count_logical"] and host["memory_total_bytes"] > 0 and host["disk_free_bytes"] > 0
    assert report["inputs"]["extract"] == {"name": FIXTURE.name, "bytes": FIXTURE.stat().st_size}
    assert any("history phase" in n for n in report["not_measured"])
    assert any("Wikidata join" in n for n in report["not_measured"])


def test_the_report_holds_no_passphrase_and_no_path_outside_the_run(tmp_path):
    report, _ = _run(tmp_path, gazetteer="osm-only", gazetteer_out=tmp_path / "out" / "g.yml")
    text = json.dumps(report)
    for p in (str(tmp_path), str(ROOT), "/home/", "/tmp/", "/root/"):
        assert p not in text, f"a path leaked into the report: {p}"
    assert "OO_DB_PASSPHRASE" not in text
    # No absolute path at all, except nothing: inputs are file names only.
    import re

    assert not re.search(r'"/(?:[A-Za-z0-9_.-]+/)+', text)


def test_a_kept_store_is_readable_by_the_gazetteer_build_and_cleanup_deletes_it(tmp_path):
    key = tmp_path / "operators.key"  # the operator's own file; the runner only reads it
    key.write_text("an-operator-passphrase-0123456789\n", "utf-8")
    report, kept = _run(tmp_path, keep_store=True, passphrase_file=key)
    assert report["status"] == "ok" and kept is not None and kept.is_dir()
    assert report["store"]["kept"] is True
    assert not list(kept.rglob(".throwaway-passphrase"))  # the runner wrote no secret to disk
    secret = key.read_text("utf-8").strip()
    assert secret not in json.dumps(report)
    for log in (kept / "logs").glob("*"):
        assert secret not in log.read_text("utf-8", errors="replace")

    out = tmp_path / "g.yml"
    env = {k: v for k, v in os.environ.items() if k not in ("OO_DB_PLAINTEXT", "OO_DB_PASSPHRASE")}
    env["OO_DATA_DIR"] = str(kept / "data")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_place_gazetteer.py"), "--country", "ZZ", "--no-wikidata",
         "--out", str(out), "--passphrase-file", str(key)],
        env=env, capture_output=True, text=True, cwd=str(ROOT), timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fixtureville" in out.read_text("utf-8")
    assert secret not in r.stdout + r.stderr
    # The gazetteer script deleted nothing of the store it read.
    assert (kept / "data" / "osm.db").is_file()

    rec = R.cleanup(kept)
    assert rec["deleted"] is True and rec["bytes_freed"] > 0 and not kept.exists()


def test_keep_store_without_the_operators_passphrase_file_is_refused_and_writes_nothing(tmp_path):
    with pytest.raises(ValueError, match="passphrase-file"):
        _run(tmp_path, keep_store=True)
    assert not (tmp_path / "work").exists() or not list((tmp_path / "work").glob("oo-osm-reference-run-*"))
    empty = tmp_path / "empty.key"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        _run(tmp_path, keep_store=True, passphrase_file=empty)
    assert not list((tmp_path / "work").glob("oo-osm-reference-run-*"))


def test_cleanup_refuses_a_directory_without_the_runners_marker(tmp_path):
    victim = tmp_path / "someone_elses_folder"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep me", encoding="utf-8")
    rec = R.cleanup(victim)
    assert rec["deleted"] is False and "marker" in rec["refused"]
    assert (victim / "precious.txt").read_text(encoding="utf-8") == "keep me"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert CLI.main(["--cleanup", str(victim)]) == 2
    assert (victim / "precious.txt").exists()


@pytest.mark.skipif(not HAVE_OSMIUM, reason="the history cut needs the [geo] extra")
def test_the_history_phase_runs_after_the_ingest_and_is_measured_the_same_way(tmp_path):
    hist = _extract(tmp_path, HISTORY)
    report, _ = _run(tmp_path, history=hist)
    assert [p["name"] for p in report["phases"]] == ["ingest", "history"], report.get("reason")
    assert report["status"] == "ok" and report["inputs"]["history"]["name"] == HISTORY.name
    h = report["phases"][1]
    assert h["peak_rss_bytes"] > 0 and h["app_report"]["alpha3"] == "ZZZ"
    assert not any("history phase" in n for n in report["not_measured"])


# --------------------------------------------------------------------------- #
#  the guards
# --------------------------------------------------------------------------- #


def test_the_preflight_refuses_before_anything_runs_and_names_its_numbers(tmp_path):
    report, kept = _run(tmp_path, probe=_Probe(free=1 * GB))
    assert report["status"] == "refused-preflight" and kept is None and report["phases"] == []
    pf = report["preflight"]
    assert pf["ok"] is False and pf["free_bytes"] == 1 * GB and pf["needed_bytes"] > pf["free_bytes"]
    assert str(pf["free_bytes"]) in report["reason"] and str(pf["needed_bytes"]) in report["reason"]
    assert "GUESS" in pf["floor_basis"], "the unmodelled floor says it is a guess"
    assert not list((tmp_path / "work").glob("oo-osm-reference-run-*")), "no store was made"


def test_the_floor_is_a_labelled_guess_until_a_measured_report_replaces_it():
    pf = R.preflight(extract_bytes=10 * GB, history_bytes=None, free_bytes=100 * GB, reserve_bytes=2 * GB)
    assert pf["needed_bytes"] == 2 * 10 * GB + 2 * GB and "GUESS" in pf["floor_basis"]
    prior = {"inputs": {"extract": {"bytes": 1 * GB}},
             "phases": [{"name": "ingest", "status": "ok", "peak_data_dir_bytes": 3 * GB}]}
    pf2 = R.preflight(extract_bytes=10 * GB, history_bytes=None, free_bytes=100 * GB, reserve_bytes=2 * GB,
                      prior_report=prior)
    assert pf2["needed_bytes"] == int(3 * 1.25 * 10 * GB) + 2 * GB and "MEASURED" in pf2["floor_basis"]
    pf3 = R.preflight(extract_bytes=10 * GB, history_bytes=None, free_bytes=5 * GB, reserve_bytes=2 * GB,
                      min_free_override=4 * GB)
    assert pf3["ok"] is True and "override" in pf3["floor_basis"]
    # The history phase writes into the same store AFTER the ingest, so its footprint ADDS (one reserve).
    pf4 = R.preflight(extract_bytes=10 * GB, history_bytes=150 * GB, free_bytes=100 * GB, reserve_bytes=2 * GB)
    assert pf4["needed_bytes"] == 2 * (2 * 10 * GB) + 2 * GB and "history phase" in pf4["floor_basis"]
    # A prior phase that was stopped (or failed) peaked early: it is NOT a measurement of the footprint.
    stopped = {"inputs": {"extract": {"bytes": 1 * GB}},
               "phases": [{"name": "ingest", "status": "refused-mid-run", "peak_data_dir_bytes": 1 * GB}]}
    pf5 = R.preflight(extract_bytes=10 * GB, history_bytes=None, free_bytes=100 * GB, reserve_bytes=2 * GB,
                      prior_report=stopped)
    assert "GUESS" in pf5["floor_basis"] and pf5["needed_bytes"] == pf["needed_bytes"]


def test_free_disk_falling_below_the_reserve_stops_the_child_cleanly_and_ends_the_run(tmp_path):
    probe = _Probe(free=100 * GB, free_after=1 * GB, after_calls=4)
    specs = _scripted("import time; time.sleep(120)", "slow") + _scripted("print('never')", "second")
    import time

    t0 = time.monotonic()
    report, _ = _run(tmp_path, probe=probe, phases_override=specs, reserve_bytes=2 * GB)
    assert time.monotonic() - t0 < 30, "the child was stopped, not waited out"
    assert report["status"] == "refused-mid-run"
    assert [p["name"] for p in report["phases"]] == ["slow"], "the next phase was never started"
    ph = report["phases"][0]
    assert ph["status"] == "refused-mid-run" and "reserve" in ph["reason"] and ph["disk_free_min_bytes"] <= 1 * GB
    assert report["store"]["deleted"] is True, "the run's own store went, freeing what it held"


def test_available_memory_staying_below_the_minimum_stops_the_child_too(tmp_path):
    probe = _Probe(avail=8 * GB, avail_after=64 * R.MIB, after_calls=2)
    report, _ = _run(tmp_path, probe=probe, phases_override=_scripted("import time; time.sleep(120)"),
                     min_available_bytes=256 * R.MIB)
    assert report["status"] == "refused-mid-run"
    assert "memory" in report["phases"][0]["reason"] and report["phases"][0]["memory_available_min_bytes"] <= 64 * R.MIB


def test_a_failing_child_is_recorded_and_its_error_text_is_scrubbed(tmp_path):
    code = (
        "import os, sys\n"
        "print('secret is', os.environ['OO_DB_PASSPHRASE'], file=sys.stderr)\n"
        "print('see', os.environ['OO_DATA_DIR'] + '/osm.db', 'and /usr/lib/python3/site.py', file=sys.stderr)\n"
        "sys.exit(3)\n"
    )
    report, _ = _run(tmp_path, phases_override=_scripted(code))
    assert report["status"] == "failed" and report["phases"][0]["exit_code"] == 3
    tail = report["phases"][0]["error_tail"]
    assert "<redacted>" in tail and "<run>/data/osm.db" in tail and "site.py" in tail
    text = json.dumps(report)
    assert str(tmp_path) not in text and "/usr/lib" not in text


def test_a_child_that_refuses_by_name_is_a_refusal_not_a_failure(tmp_path):
    report, _ = _run(tmp_path, phases_override=_scripted("import sys; print('refused: no'); sys.exit(2)"))
    assert report["status"] == "refused" and report["phases"][0]["status"] == "refused"


def test_the_timeline_stays_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "TIMELINE_MAX", 6)
    go = tmp_path / "go"
    code = f"import os, time\nwhile not os.path.exists({str(go)!r}): time.sleep(0.02)\n"
    report, _ = _run(tmp_path, phases_override=_scripted(code), sample_seconds=R.SAMPLE_SECONDS_MIN,
                     probe=_Probe(release=(go, 25)))
    ph = report["phases"][0]
    assert ph["samples"] >= 20 and 1 <= len(ph["timeline"]) <= 6


def _alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _wait_dead(pid: int) -> bool:
    import time

    for _ in range(100):
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def _nonempty(path: Path) -> bool:
    """A pid file exists the moment ``open(..., 'w')`` runs and holds its number a moment later."""
    return path.exists() and path.read_text(encoding="utf-8").strip() != ""


def _pid(path: Path) -> int:
    return int(path.read_text(encoding="utf-8").strip())


def test_a_guard_stop_reaches_the_whole_process_group_so_no_grandchild_keeps_writing(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(0.1)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(g.pid))\n"
        "time.sleep(120)\n"
    )
    probe = _Probe(free=100 * GB, free_after=1 * GB, trigger=lambda: _nonempty(pidfile))
    report, _ = _run(tmp_path, probe=probe, phases_override=_scripted(code), reserve_bytes=2 * GB)
    assert report["status"] == "refused-mid-run"
    assert _wait_dead(_pid(pidfile)), "a grandchild outlived the guard's stop"


def test_a_helper_that_ignores_sigterm_is_killed_even_though_the_child_exits_on_it(tmp_path):
    """The leader leaving on SIGTERM must not end the stop: the group still has a member that ignores it.

    The helper writes its OWN pid file only after it ignores SIGTERM, and the guard fires only then, so the
    SIGTERM can never kill it by default action and the test cannot pass without the SIGKILL sweep."""
    pidfile = tmp_path / "helper.pid"
    helper = ("import os, signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
              f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\nwhile True: time.sleep(0.1)")
    code = ("import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {helper!r}])\ntime.sleep(120)\n")
    probe = _Probe(free=100 * GB, free_after=1 * GB, trigger=lambda: _nonempty(pidfile))
    report, _ = _run(tmp_path, probe=probe, phases_override=_scripted(code), reserve_bytes=2 * GB)
    assert report["status"] == "refused-mid-run"
    assert _wait_dead(_pid(pidfile)), "SIGKILL was skipped because the leader had already left"


def test_a_helper_still_running_after_a_clean_exit_is_swept_before_the_store_goes(tmp_path):
    pidfile = tmp_path / "late.pid"
    code = (
        "import subprocess, sys\n"
        "h = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(0.1)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(h.pid))\n"
    )
    report, _ = _run(tmp_path, phases_override=_scripted(code))
    assert report["status"] == "ok" and report["store"]["deleted"] is True
    assert _wait_dead(_pid(pidfile)), "a descendant outlived a clean exit"


def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "TERMINATE_GRACE_S", 0.5)
    ready = tmp_path / "ready"
    code = ("import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"open({str(ready)!r}, 'w').write('x')\ntime.sleep(120)")
    import time

    t0 = time.monotonic()
    report, _ = _run(tmp_path, probe=_Probe(free=100 * GB, free_after=1 * GB, trigger=lambda: _nonempty(ready)),
                     phases_override=_scripted(code), reserve_bytes=2 * GB)
    assert report["status"] == "refused-mid-run" and time.monotonic() - t0 < 30


def test_disk_collapsing_during_the_grace_ends_the_grace_at_once(tmp_path, monkeypatch):
    """Below the reserve the child is told to leave; below HALF the reserve the grace is over, whatever it was."""
    monkeypatch.setattr(R, "TERMINATE_GRACE_S", 60.0)
    ready, termed = tmp_path / "ready", tmp_path / "termed"
    code = ("import signal, time\n"
            f"signal.signal(signal.SIGTERM, lambda *a: open({str(termed)!r}, 'w').write('x'))\n"
            f"open({str(ready)!r}, 'w').write('x')\ntime.sleep(120)")
    probe = R.Probe(
        free_disk=lambda p: 100 * GB if not _nonempty(ready) else (int(0.5 * GB) if _nonempty(termed) else int(1.5 * GB)),
        available_memory=lambda: 8 * GB)
    import time

    t0 = time.monotonic()
    report, _ = _run(tmp_path, probe=probe, phases_override=_scripted(code), reserve_bytes=2 * GB)
    assert time.monotonic() - t0 < 30, "the 60 s grace was waited out while the disk filled"
    assert report["status"] == "refused-mid-run"


def test_a_dead_sampler_stops_the_phase_instead_of_leaving_it_unguarded(tmp_path):
    state = {"n": 0}

    def mem():
        state["n"] += 1
        if state["n"] > 3:
            raise OSError("psutil went away")
        return 8 * GB

    report, _ = _run(tmp_path, probe=R.Probe(free_disk=lambda p: 100 * GB, available_memory=mem),
                     phases_override=_scripted("import time; time.sleep(120)"))
    ph = report["phases"][0]
    assert report["status"] == "refused-mid-run" and "sampler failed" in ph["reason"] and "OSError" in ph["reason"]


# --------------------------------------------------------------------------- #
#  the runner itself being signalled or killed: each in its OWN subprocess, so a regression that drops the
#  handler fails the test instead of killing the pytest process
# --------------------------------------------------------------------------- #

_RUNNER = """
import json, sys
from pathlib import Path
from src.osm import reference_run as R
cfg = json.loads(sys.argv[1])
specs = [R.PhaseSpec("child", [sys.executable, "-c", cfg["code"]])]
report, _ = R.run(extract=Path(cfg["extract"]), country="ZZ", workdir=Path(cfg["work"]), phases_override=specs,
                  sample_seconds=0.1, report_path=Path(cfg["report"]))
print(report["status"])
"""


def _spawn_runner(tmp_path: Path, code: str) -> subprocess.Popen:
    cfg = {"code": code, "extract": str(_extract(tmp_path)), "work": str(tmp_path / "work"),
           "report": str(tmp_path / "report.json")}
    return subprocess.Popen([sys.executable, "-c", _RUNNER, json.dumps(cfg)], cwd=str(ROOT), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)


def _wait_nonempty(path: Path, timeout: float = 60.0) -> None:
    import time

    t0 = time.monotonic()
    while not _nonempty(path):
        assert time.monotonic() - t0 < timeout, f"{path.name} never appeared"
        time.sleep(0.05)


_CHILD = "import os, time\nopen({pf!r}, 'w').write(str(os.getpid()))\ntime.sleep(120)"
_STUBBORN = ("import os, signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
             "open({pf!r}, 'w').write(str(os.getpid()))\ntime.sleep(120)")


def test_sighup_stops_the_child_deletes_the_store_and_still_writes_the_report(tmp_path):
    """A dropped SSH session sends SIGHUP: without the handler Python died on the spot and the child ran on."""
    import signal as sg

    pidfile = tmp_path / "child.pid"
    proc = _spawn_runner(tmp_path, _CHILD.format(pf=str(pidfile)))
    try:
        _wait_nonempty(pidfile)
        proc.send_signal(sg.SIGHUP)
        out, err = proc.communicate(timeout=60)
    finally:
        proc.kill()
    assert proc.returncode == 0, err
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "interrupted" and "SIGHUP" in report["reason"]
    assert report["phases"][0]["status"] == "interrupted"
    assert report["store"]["deleted"] is True and not list((tmp_path / "work").glob("oo-osm-reference-run-*"))
    assert _wait_dead(_pid(pidfile))


def test_a_second_signal_while_the_child_ignores_the_first_kills_it_at_once(tmp_path):
    import signal as sg
    import time

    pidfile = tmp_path / "child.pid"
    proc = _spawn_runner(tmp_path, _STUBBORN.format(pf=str(pidfile)))
    try:
        _wait_nonempty(pidfile)
        t0 = time.monotonic()
        proc.send_signal(sg.SIGTERM)
        time.sleep(0.5)
        proc.send_signal(sg.SIGTERM)
        proc.communicate(timeout=60)
    finally:
        proc.kill()
    assert time.monotonic() - t0 < R.TERMINATE_GRACE_S - 5, "the second signal did not cut the grace short"
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "interrupted" and report["store"]["deleted"] is True
    assert _wait_dead(_pid(pidfile)), "the child was abandoned alive"


def test_a_killed_runner_does_not_leave_the_child_running(tmp_path):
    """SIGKILL cannot be handled: the kernel's parent-death signal is the only thing that stops the child."""
    pidfile = tmp_path / "child.pid"
    proc = _spawn_runner(tmp_path, _CHILD.format(pf=str(pidfile)))
    try:
        _wait_nonempty(pidfile)
        proc.kill()
        proc.communicate(timeout=60)
    finally:
        proc.kill()
    child = _pid(pidfile)
    try:
        assert _wait_dead(child), "the child outlived a SIGKILLed runner"
    finally:
        for left in (tmp_path / "work").glob("oo-osm-reference-run-*"):  # the killed runner could not delete its store
            R.cleanup(left)


def test_a_signal_between_phases_stops_the_run_before_the_next_one(tmp_path, monkeypatch):
    """The handler sets a flag and the loop reads it: no phase starts after the signal."""
    import signal as sg

    seen = {}

    def _phase_then_signal(spec, **kw):
        res = R.PhaseResult(spec.name)
        os.kill(os.getpid(), sg.SIGTERM)  # arrives with no child alive: only the flag changes
        seen["signal"] = R._INT.signal
        return res

    monkeypatch.setattr(R, "run_phase", _phase_then_signal)
    specs = _scripted("print(1)", "first") + _scripted("print(2)", "second")
    report, _ = _run(tmp_path, phases_override=specs)
    assert seen["signal"] == "SIGTERM" and report["status"] == "interrupted"
    assert [p["name"] for p in report["phases"]] == ["first"], "a phase started after the signal"
    assert report["store"]["deleted"] is True
    assert sg.getsignal(sg.SIGTERM) == sg.SIG_DFL or callable(sg.getsignal(sg.SIGTERM))


def test_the_reference_run_refuses_a_system_that_is_not_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "win32")
    with pytest.raises(ValueError, match="Linux"):
        _run(tmp_path)


def test_the_online_join_is_not_offered_inside_the_throwaway_store(tmp_path):
    """Its store has none of the operator's persisted transport settings: a silent clearnet fallback."""
    with pytest.raises(ValueError, match="separate step"):
        _run(tmp_path, gazetteer="online")
    with pytest.raises(SystemExit):
        CLI.main(["--extract", "x", "--country", "ZZ", "--gazetteer", "online"])


def test_a_workdir_inside_the_repository_is_refused(tmp_path):
    with pytest.raises(ValueError, match="outside the repository"):
        R.run(extract=_extract(tmp_path), country="ZZ", workdir=ROOT / "oo-should-not-exist")
    assert not (ROOT / "oo-should-not-exist").exists()


def test_the_passphrase_value_never_reaches_the_report_whatever_the_child_prints(tmp_path):
    seen = tmp_path / "seen.txt"
    code = ("import os, sys\n"
            "p = os.environ['OO_DB_PASSPHRASE']\n"
            f"open({str(seen)!r}, 'w').write(p)\n"
            "print('stdout says', p); print('stderr says', p, file=sys.stderr); sys.exit(1)")
    report, _ = _run(tmp_path, phases_override=_scripted(code))
    secret = seen.read_text(encoding="utf-8")
    assert len(secret) >= 16
    assert secret not in json.dumps(report) and "<redacted>" in json.dumps(report)
    assert report["status"] == "failed"


def test_no_phase_the_runner_builds_carries_a_passphrase_in_its_argv():
    for gaz in ("off", "osm-only"):
        phases = R.build_phases(extract=Path("e.osm.pbf"), country="ZZ", history=Path("h.osm.pbf"), reader=None,
                                gazetteer=gaz, gazetteer_out=Path("g.yml"))
        for ph in phases:
            joined = " ".join(ph.argv).lower()
            assert "passphrase" not in joined and "oo_db" not in joined, ph.name


def test_database_url_is_dropped_from_the_childs_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:////home/someone/own-store.db")
    code = "import os, json\nprint(json.dumps({'dburl': os.environ.get('DATABASE_URL'), 'tmp': os.environ.get('TMPDIR')}))"
    report, _ = _run(tmp_path, phases_override=_scripted(code))
    got = report["phases"][0]["app_report"]
    assert got["dburl"] is None, "the child could have opened the operator's own main database"
    assert got["tmp"] == "<run>/tmp", "temp and spill files stay on the filesystem the guard reads"


def test_a_path_inside_a_childs_json_report_is_scrubbed(tmp_path):
    code = "import json\nprint(json.dumps({'where': '/home/alice/secret/place/osm.db', '/srv/keyed/path.txt': 1}))"
    report, _ = _run(tmp_path, phases_override=_scripted(code))
    text = json.dumps(report)
    assert "/home/alice" not in text and "/srv/keyed" not in text and "osm.db" in text


def test_the_childs_logs_are_owner_only(tmp_path):
    code = "print('x')"
    pf = tmp_path / "op.key"
    pf.write_text("op-passphrase-0123456789\n", encoding="utf-8")
    _report, kept = _run(tmp_path, phases_override=_scripted(code), keep_store=True, passphrase_file=pf)
    try:
        for f in (kept / "logs").glob("*"):
            assert (f.stat().st_mode & 0o077) == 0, f.name
    finally:
        R.cleanup(kept)


def test_sample_seconds_outside_the_sane_range_is_refused(tmp_path):
    for bad in (0, 0.001, 3600):
        with pytest.raises(ValueError, match="sample-seconds"):
            _run(tmp_path, sample_seconds=bad)
    rc, out = _cli("--extract", str(_extract(tmp_path)), "--country", "ZZ", "--sample-seconds", "3600")
    assert rc == 2 and "sample-seconds" in out


def test_the_children_get_the_passphrase_in_their_environment_only(tmp_path, monkeypatch):
    code = ("import os, sys, json; print(json.dumps({'has': bool(os.environ.get('OO_DB_PASSPHRASE')), "
            "'plain': os.environ.get('OO_DB_PLAINTEXT'), 'argv': ' '.join(sys.argv)}))")
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")  # restored afterwards: the suite's own default must survive
    report, _ = _run(tmp_path, phases_override=_scripted(code))
    got = report["phases"][0]["app_report"]
    assert got["has"] is True and got["plain"] is None


def test_scrub_removes_secrets_and_foreign_paths_but_not_urls():
    run = Path("/var/work/run1")
    s = R.scrub("a /home/me/x/y.py b /var/work/run1/data/osm.db c https://www.openstreetmap.org/copyright d S3CR3T",
                secrets_=("S3CR3T",), run_dir=run)
    assert "S3CR3T" not in s and "/home/me" not in s and "y.py" in s
    assert "<run>/data/osm.db" in s and "https://www.openstreetmap.org/copyright" in s


def test_scrub_catches_the_forms_the_plain_pattern_missed():
    run = Path("/home/alice/work/oo-osm-reference-run-X")
    cases = {
        "PYTHONPATH=/a/lib:/home/alice/x": "/home/alice",
        f"sqlite:////{str(run)[1:]}/data/osm.db": "/home/alice",
        "file:///home/alice/proj/x.py": "/home/alice",
        "at /srv/Alice Smith/repo/x.py line 3": "Alice Smith",
    }
    roots = (("/srv/Alice Smith", "<repo>"),)
    for text, leaked in cases.items():
        out = R.scrub(text, run_dir=run, roots=roots)
        assert leaked not in out, f"{leaked!r} survived in {out!r}"
    assert "<run>/data/osm.db" in R.scrub(f"sqlite:////{str(run)[1:]}/data/osm.db", run_dir=run)
    assert R.scrub("see https://www.openstreetmap.org/copyright", run_dir=run) == "see https://www.openstreetmap.org/copyright"
    assert "<repo>/repo/x.py" in R.scrub("at /srv/Alice Smith/repo/x.py", roots=roots)


# --------------------------------------------------------------------------- #
#  the command line
# --------------------------------------------------------------------------- #


def _cli(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = CLI.main(list(argv))
    return rc, buf.getvalue()


def test_plan_prints_the_disk_it_needs_and_runs_nothing(tmp_path):
    ext = _extract(tmp_path)
    rc, out = _cli("--extract", str(ext), "--country", "ZZ", "--plan", "--workdir", str(tmp_path / "w"))
    data = json.loads(out)
    assert rc == 0 and data["preflight"]["needed_bytes"] > 0 and "GUESS" in data["preflight"]["floor_basis"]
    assert not list((tmp_path / "w").glob("oo-osm-reference-run-*"))
    assert data["guards"]["reserve_bytes"] == R.DEFAULT_RESERVE_BYTES


def test_the_command_writes_the_report_and_says_where(tmp_path):
    ext = _extract(tmp_path)
    rep = tmp_path / "run.json"
    rc, out = _cli("--extract", str(ext), "--country", "ZZ", "--report", str(rep), "--workdir", str(tmp_path / "w"),
                   "--sample-seconds", "0.1")
    assert rc == 0 and "status: ok" in out and "store: deleted" in out
    data = json.loads(rep.read_text("utf-8"))
    assert data["schema_version"] == R.SCHEMA_VERSION and data["status"] == "ok"


def test_a_missing_extract_and_a_bad_country_are_named_refusals(tmp_path):
    rc, out = _cli("--extract", str(tmp_path / "nope.osm.pbf"), "--country", "ZZ")
    assert rc == 2 and "download it in the app first" in out
    ext = _extract(tmp_path)
    rc, out = _cli("--extract", str(ext), "--country", "NOPE")
    assert rc == 2 and "not an ISO 3166-1" in out


def test_there_is_no_download_flag():
    src = (ROOT / "scripts" / "osm_reference_run.py").read_text("utf-8")
    assert "--download" not in src.replace("has no download flag", "")
    mod = (ROOT / "src" / "osm" / "reference_run.py").read_text("utf-8")
    for needle in ("import requests", "import httpx", "urllib.request", "create_connection"):
        assert needle not in mod
