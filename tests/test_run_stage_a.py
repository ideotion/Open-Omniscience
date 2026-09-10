"""The one-command local Stage A runner -- its pure parts (no venv, no network, no subprocess).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

Pinned here: the Python floor is the kit's floor; the venv interpreter path follows the
platform; the worker cap holds; the results note is built from the scripts' own summaries and
says so when a run was interrupted; the package carries the runs folder, the manifest and the
note, and nothing else of the kit.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import zipfile
from datetime import UTC, datetime
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


def test_the_python_floor_is_the_kit_floor():
    assert tuple(int(x) for x in bck.PYTHON_FLOOR.split(".")) == rsa.PYTHON_FLOOR
    assert rsa.python_ok((3, 12)) and rsa.python_ok((3, 13)) and rsa.python_ok((4, 0))
    assert not rsa.python_ok((3, 11)) and not rsa.python_ok((3, 9))


def test_the_venv_interpreter_path_follows_the_platform(tmp_path: Path):
    p = rsa.venv_python(tmp_path)
    assert p.parts[-3] == ".venv"
    assert p.name == ("python.exe" if os.name == "nt" else "python")


def test_the_workers_are_capped_and_the_arguments_parse():
    a = rsa.parse_args(["--workers", "64", "--only", "shortlist", "--limit", "300", "--timeout", "9"])
    assert a.workers == rsa.MAX_WORKERS == 12 and a.only == "shortlist" and a.limit == 300 and a.timeout == 9.0
    d = rsa.parse_args([])
    assert d.only is None and d.limit is None and d.workers == 12 and not d.skip_selfcheck and not d.no_zip
    assert rsa.parse_args(["--workers", "0"]).workers == 1


def test_the_results_note_and_the_package_carry_the_runs_and_nothing_else(tmp_path: Path):
    (tmp_path / "KIT_MANIFEST.json").write_text(json.dumps({"id": "oo-candidate-kit-x"}), encoding="utf-8")
    w1 = tmp_path / "runs" / "w1"
    w1.mkdir(parents=True)
    (w1 / "summary.json").write_text(json.dumps({
        "candidates": 10, "verified": 4, "by_reason": {"verified": 4, "no_feed_found": 6}, "interrupted": True,
    }), encoding="utf-8")
    (w1 / "verified.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "never_packaged.py").write_text("", encoding="utf-8")
    when = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    md = rsa.results_md(tmp_path, now=when)
    assert "oo-candidate-kit-x" in md
    assert "10 candidates judged, 4 feeds verified" in md and "no_feed_found 6" in md
    assert "INTERRUPTED" in md and "remainder" in md and "not run" in md

    z = rsa.package(tmp_path, now=when)
    assert z == tmp_path / "stage_a_results_2026-09-10.zip"
    with zipfile.ZipFile(z) as zf:
        assert set(zf.namelist()) == {"runs/w1/summary.json", "runs/w1/verified.jsonl", "runs/RESULTS.md", "KIT_MANIFEST.json"}
        assert "INTERRUPTED" in zf.read("runs/RESULTS.md").decode("utf-8")


def test_the_kit_carries_the_runner_at_its_root(tmp_path: Path):
    assert (_ROOT / bck.RUNNER).read_bytes() == (_ROOT / "scripts" / "analysis" / "run_stage_a.py").read_bytes()
