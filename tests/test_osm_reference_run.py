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
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import osm_reference_run as CLI
from src.osm import reference_run as R
from tests._osm_lane_helpers import FIXTURE, HAVE_OSMIUM, ROOT

HISTORY = ROOT / "tests" / "fixtures" / "osm" / "synthetic-history.osm.pbf"
GB = R.GIB


class _Probe(R.Probe):
    """A probe whose free disk and available memory are scripted; the real one is the default."""

    def __init__(self, free=100 * GB, avail=8 * GB, free_after=None, avail_after=None, after_calls=3):
        self._free, self._avail = free, avail
        self._free_after, self._avail_after, self._after = free_after, avail_after, after_calls
        self.calls = 0
        super().__init__(free_disk=self._f, available_memory=self._m)

    def _f(self, _p):
        self.calls += 1
        if self._free_after is not None and self.calls > self._after:
            return self._free_after
        return self._free

    def _m(self):
        if self._avail_after is not None and self.calls > self._after:
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
    (real / "sentinel").write_text("x")
    monkeypatch.setenv("OO_DATA_DIR", str(real))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")  # the children must NOT inherit this

    def refuse(*a, **k):
        raise AssertionError("the runner opened a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
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
    report, kept = _run(tmp_path, keep_store=True)
    assert report["status"] == "ok" and kept is not None and kept.is_dir()
    assert report["store"]["kept"] is True
    key = kept / ".throwaway-passphrase"
    assert key.is_file() and stat.S_IMODE(key.stat().st_mode) == 0o600
    secret = key.read_text("utf-8")
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


def test_cleanup_refuses_a_directory_without_the_runners_marker(tmp_path):
    victim = tmp_path / "someone_elses_folder"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep me")
    rec = R.cleanup(victim)
    assert rec["deleted"] is False and "marker" in rec["refused"]
    assert (victim / "precious.txt").read_text() == "keep me"
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
             "phases": [{"name": "ingest", "peak_data_dir_bytes": 3 * GB}]}
    pf2 = R.preflight(extract_bytes=10 * GB, history_bytes=None, free_bytes=100 * GB, reserve_bytes=2 * GB,
                      prior_report=prior)
    assert pf2["needed_bytes"] == int(3 * 1.25 * 10 * GB) + 2 * GB and "MEASURED" in pf2["floor_basis"]
    pf3 = R.preflight(extract_bytes=10 * GB, history_bytes=None, free_bytes=5 * GB, reserve_bytes=2 * GB,
                      min_free_override=4 * GB)
    assert pf3["ok"] is True and "override" in pf3["floor_basis"]
    # A history file lifts the need to the same footprint, never below the ingest's.
    pf4 = R.preflight(extract_bytes=10 * GB, history_bytes=150 * GB, free_bytes=100 * GB, reserve_bytes=2 * GB)
    assert pf4["needed_bytes"] >= pf["needed_bytes"]


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
    report, _ = _run(tmp_path, phases_override=_scripted("import time; time.sleep(1.5)"), sample_seconds=0.02)
    ph = report["phases"][0]
    assert ph["samples"] > 20 and 1 <= len(ph["timeline"]) <= 6


def _alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_a_guard_stop_reaches_the_whole_process_group_so_no_grandchild_keeps_writing(tmp_path, monkeypatch):
    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(0.1)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(g.pid))\n"
        "time.sleep(120)\n"
    )
    probe = _Probe(free=100 * GB, free_after=1 * GB, after_calls=6)
    report, _ = _run(tmp_path, probe=probe, phases_override=_scripted(code), reserve_bytes=2 * GB)
    assert report["status"] == "refused-mid-run"
    pid = int(pidfile.read_text())
    import time

    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid), "a grandchild outlived the guard's stop"


def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "TERMINATE_GRACE_S", 0.5)
    code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"
    import time

    t0 = time.monotonic()
    report, _ = _run(tmp_path, probe=_Probe(free=100 * GB, free_after=1 * GB, after_calls=4),
                     phases_override=_scripted(code), reserve_bytes=2 * GB)
    assert report["status"] == "refused-mid-run" and time.monotonic() - t0 < 30


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


def test_the_children_get_the_passphrase_in_their_environment_only(tmp_path):
    code = ("import os, sys, json; print(json.dumps({'has': bool(os.environ.get('OO_DB_PASSPHRASE')), "
            "'plain': os.environ.get('OO_DB_PLAINTEXT'), 'argv': ' '.join(sys.argv)}))")
    os.environ["OO_DB_PLAINTEXT"] = "1"
    try:
        report, _ = _run(tmp_path, phases_override=_scripted(code))
    finally:
        del os.environ["OO_DB_PLAINTEXT"]
    got = report["phases"][0]["app_report"]
    assert got["has"] is True and got["plain"] is None


def test_scrub_removes_secrets_and_foreign_paths_but_not_urls():
    run = Path("/var/work/run1")
    s = R.scrub("a /home/me/x/y.py b /var/work/run1/data/osm.db c https://www.openstreetmap.org/copyright d S3CR3T",
                secrets_=("S3CR3T",), run_dir=run)
    assert "S3CR3T" not in s and "/home/me" not in s and "y.py" in s
    assert "<run>/data/osm.db" in s and "https://www.openstreetmap.org/copyright" in s


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
