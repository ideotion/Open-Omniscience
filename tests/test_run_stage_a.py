"""The one-command local Stage A runner -- its pure parts (no venv, no network, no subprocess).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

Pinned here: the Python floor is the kit's floor; the venv interpreter path follows the
platform; the worker cap holds; the run order is the shortlist first; the status tally reads
the JSONL cursor itself (exact mid-run, a torn last line skipped and counted, this session's
rate measured from the rows' own stamps); the results note and the package carry the runs
folder, the manifest and the note, with every verified.jsonl reduced to its complete lines;
and a snapshot is named as one.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, default: Path):
    p = Path(os.environ.get(name) or default)
    spec = importlib.util.spec_from_file_location(p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rsa = _load("RSA_MODULE", _ROOT / "scripts" / "analysis" / "run_stage_a.py")
bck = _load("BCK_MODULE", _ROOT / "scripts" / "analysis" / "build_candidate_kit.py")

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _fake_kit(tmp_path: Path) -> Path:
    """A kit root with a 3-row shortlist, two judged rows (this session, 30 minutes old), a
    torn third line, and no remainder run at all."""
    (tmp_path / "KIT_MANIFEST.json").write_text(json.dumps({"id": "oo-candidate-kit-x"}), encoding="utf-8")
    wl = tmp_path / "worklists"
    wl.mkdir()
    (wl / "worklist_1_shortlist.csv").write_text("tier,name,domain\nT1,A,a.example\nT1,B,b.example\nT1,C,c.example\n", encoding="utf-8")
    (wl / "worklist_2_remainder.csv").write_text("tier,name,domain\nT4,D,d.example\n", encoding="utf-8")
    w1 = tmp_path / "runs" / "w1"
    w1.mkdir(parents=True)
    stamp = (NOW - timedelta(minutes=30)).isoformat(timespec="seconds")
    rows = [
        {"domain": "a.example", "status": "verified", "reason": "verified", "checked_at": stamp},
        {"domain": "b.example", "status": "rejected", "reason": "no_feed_found", "checked_at": stamp},
    ]
    (w1 / "verified.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows) + '{"domain": "c.example", "status": "verif', encoding="utf-8")
    (w1 / "summary.json").write_text(json.dumps({"interrupted": True}), encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "never_packaged.py").write_text("", encoding="utf-8")
    return tmp_path


def test_the_python_floor_is_the_kit_floor():
    assert tuple(int(x) for x in bck.PYTHON_FLOOR.split(".")) == rsa.PYTHON_FLOOR
    assert rsa.python_ok((3, 12)) and rsa.python_ok((3, 13)) and rsa.python_ok((4, 0))
    assert not rsa.python_ok((3, 11)) and not rsa.python_ok((3, 9))


def test_the_venv_interpreter_path_follows_the_platform(tmp_path: Path):
    p = rsa.venv_python(tmp_path)
    assert p.parts[-3] == ".venv"
    assert p.name == ("python.exe" if os.name == "nt" else "python")


def test_the_run_order_is_the_shortlist_first_and_the_arguments_parse():
    assert list(rsa.WORKLISTS) == ["shortlist", "remainder"]  # insertion order is the run order
    a = rsa.parse_args(["--workers", "64", "--only", "shortlist", "--limit", "300", "--timeout", "9"])
    assert a.workers == rsa.MAX_WORKERS == 12 and a.only == "shortlist" and a.limit == 300 and a.timeout == 9.0
    d = rsa.parse_args([])
    assert d.only is None and d.limit is None and d.workers == 12
    assert not d.skip_selfcheck and not d.no_zip and not d.status
    assert rsa.parse_args(["--workers", "0"]).workers == 1 and rsa.parse_args(["--status"]).status


def test_the_tally_reads_the_cursor_exactly_mid_run_and_measures_this_sessions_rate(tmp_path: Path):
    root = _fake_kit(tmp_path)
    t = rsa.tally(root, "shortlist", now=NOW)
    assert (t["judged"], t["total"], t["verified"], t["torn"]) == (2, 3, 1, 1)
    assert t["by_reason"] == {"verified": 1, "no_feed_found": 1}
    assert t["session_rows"] == 2 and t["rate_per_hour"] == 4.0 and t["eta_hours"] == 0.25  # 2 rows in 30 min; 1 left
    assert rsa.tally(root, "remainder", now=NOW) is None
    lines = rsa.status_lines(root, now=NOW)
    assert lines[0].startswith("shortlist  2/3 judged, 1 feeds verified -- verified 1, no_feed_found 1")
    assert "4 hosts/hour" in lines[0] and "~0.2 h" in lines[0] and "1 line still being written" in lines[0]
    assert lines[1].startswith("remainder  not started")


def test_the_results_note_and_the_package_carry_the_runs_with_complete_lines_only(tmp_path: Path):
    root = _fake_kit(tmp_path)
    md = rsa.results_md(root, now=NOW)
    assert "oo-candidate-kit-x" in md
    assert "2 of 3 candidates judged, 1 feeds verified" in md and "no_feed_found 1" in md
    assert "INTERRUPTED" in md and "IN PROGRESS, 1 rows not yet judged" in md and "**remainder**" in md and "not run" in md

    z = rsa.package(root, now=NOW)
    assert z == root / "stage_a_results_2026-09-10.zip"
    with zipfile.ZipFile(z) as zf:
        assert set(zf.namelist()) == {"runs/w1/summary.json", "runs/w1/verified.jsonl", "runs/RESULTS.md", "KIT_MANIFEST.json"}
        lines = zf.read("runs/w1/verified.jsonl").decode("utf-8").splitlines()
        assert len(lines) == 2 and all(json.loads(ln) for ln in lines)  # the torn line stays out of the zip

    snap = rsa.package(root, now=NOW, snapshot=True)
    assert snap == root / "stage_a_snapshot_2026-09-10T1200.zip"
    assert (root / "runs" / "w1" / "verified.jsonl").read_text(encoding="utf-8").endswith('"status": "verif')  # the run's file is untouched


def test_the_kit_carries_the_runner_at_its_root():
    assert (_ROOT / bck.RUNNER).read_bytes() == (_ROOT / "scripts" / "analysis" / "run_stage_a.py").read_bytes()


def test_the_retry_flag_passes_through_and_the_selfcheck_marker_is_keyed_by_the_kit(tmp_path: Path, monkeypatch):
    assert rsa.parse_args(["--retry", "host_timeout,crawl_delay_too_long"]).retry == "host_timeout,crawl_delay_too_long"
    assert rsa.parse_args([]).retry is None

    root = _fake_kit(tmp_path)
    (root / "selfcheck.py").write_text("", encoding="utf-8")
    runs: list[list[str]] = []
    monkeypatch.setattr(rsa.subprocess, "run", lambda cmd, **kw: runs.append([str(c) for c in cmd]))
    marker = root / "runs" / ".selfcheck_ok"

    rsa.selfcheck(Path("py"), root)  # no marker: runs, and records the kit it passed for
    assert len(runs) == 1 and runs[0][-1].endswith("selfcheck.py")
    assert marker.read_text(encoding="utf-8") == "oo-candidate-kit-x" == rsa.kit_id(root)

    rsa.selfcheck(Path("py"), root)  # same kit: skipped
    assert len(runs) == 1

    (root / "KIT_MANIFEST.json").write_text(json.dumps({"id": "oo-candidate-kit-y"}), encoding="utf-8")
    rsa.selfcheck(Path("py"), root)  # an updated kit extracted over the folder: proves itself again
    assert len(runs) == 2 and marker.read_text(encoding="utf-8") == "oo-candidate-kit-y"

    marker.write_text("2026-09-10T10:00:00+00:00", encoding="utf-8")  # the pre-keyed marker shape
    rsa.selfcheck(Path("py"), root)
    assert len(runs) == 3


def test_a_sharded_run_names_its_zip_and_passes_the_shard_down(tmp_path, monkeypatch):
    """Eight machines, eight zips. If they all came back called stage_a_results_<date>.zip the
    operator would overwrite seven slices of the worklist on the way into one folder, and
    nothing in any single file would say so."""
    (tmp_path / "runs" / "w1").mkdir(parents=True)
    (tmp_path / "runs" / "w1" / "verified.jsonl").write_text("", encoding="utf-8")
    plain = rsa.package(tmp_path, now=NOW)
    sharded = rsa.package(tmp_path, now=NOW, shard="3/8")
    assert plain.name != sharded.name
    assert "shard3of8" in sharded.name and "shard" not in plain.name

    # ...and the flag actually reaches Stage A rather than only naming the output.
    seen = {}

    class _Proc:
        def wait(self): return 0

    monkeypatch.setattr(rsa.subprocess, "Popen", lambda cmd, **kw: (seen.update(cmd=cmd), _Proc())[1])
    args = argparse.Namespace(workers=4, timeout=20.0, limit=None, retry=None, shard="3/8")
    rsa.stage_a(Path("py"), next(iter(rsa.WORKLISTS)), args, root=tmp_path, env={})
    assert "--shard" in seen["cmd"] and seen["cmd"][seen["cmd"].index("--shard") + 1] == "3/8"

