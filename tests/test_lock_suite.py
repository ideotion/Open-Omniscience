"""Row 114: the weekly suite on requirements.lock's own pins.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The PR test jobs run on the newest release of every dependency (R318/R412); a user installing from the lock runs
on its pins, where five tests once failed unseen (row 113). ``.github/workflows/lock-suite.yml`` runs the suite there
weekly and keeps one rolling issue. These pin the constraints it builds, the issue it writes and its wiring.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("lock_suite", ROOT / "scripts" / "lock_suite.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lock_suite"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_every_pin_of_the_lock_becomes_a_plain_constraint():
    mod = _mod()
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins = mod.constraints_from_lock(lock)
    names_in_lock = [ln.split("==")[0] for ln in lock.splitlines() if "==" in ln and not ln.startswith((" ", "#"))]
    assert len(pins) == len(names_in_lock) and pins, "one constraint per pinned line"
    assert all("[" not in p and "--hash" not in p and " " not in p for p in pins), "pip refuses extras as constraints"
    assert any(p.lower().startswith("sqlalchemy==") for p in pins)


def test_an_extra_a_marker_and_a_hash_are_dropped():
    mod = _mod()
    text = "uvicorn[standard]==0.30.0 \\\n    --hash=sha256:ab\n# comment\nfoo==1.2 ; python_version >= '3.13'\n    # via bar\n"
    assert mod.constraints_from_lock(text) == ["uvicorn==0.30.0", "foo==1.2"]


def test_a_green_week_closes_and_any_other_outcome_keeps_it_open():
    mod = _mod()
    ok = {"shard 1": "success", "shard 2": "success", "shard 3": "success"}
    assert mod.build_issue_body(ok, [], [], "u", {})[0] is False
    for other in ("failure", "cancelled", "skipped", "unfinished"):
        assert mod.build_issue_body({**ok, "shard 2": other}, [], [], "u", {})[0] is True, other
    assert mod.build_issue_body({}, [], [], "u", {})[0] is True, "no outcome is not a pass"


def test_the_issue_names_the_failures_and_the_pins(tmp_path):
    mod = _mod()
    junit = tmp_path / "a" / "junit.xml"
    junit.parent.mkdir()
    junit.write_text(
        '<testsuites><testsuite><testcase classname="tests.test_x" name="test_ok"/>'
        '<testcase classname="tests.test_x" name="test_bad"><failure message="m"/></testcase>'
        '<testcase classname="tests.test_y" name="test_err"><error message="e"/></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    broken = tmp_path / "b" / "junit.xml"
    broken.parent.mkdir()
    broken.write_text("<not xml", encoding="utf-8")
    failed, unreadable = mod.failures_from_junit([junit, broken])
    assert failed == ["tests.test_x::test_bad", "tests.test_y::test_err"]
    assert unreadable == [str(broken)]
    _, body = mod.build_issue_body({"shard 1": "failure"}, failed, unreadable, "https://run", {"SQLAlchemy": "2.0.51"})
    assert "tests.test_x::test_bad" in body and "SQLAlchemy 2.0.51" in body and "https://run" in body
    assert "newest release" in body, "the packages the lock does not name are said, not hidden"


def test_the_workflow_runs_the_three_shards_on_the_lock_and_never_on_a_pr():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "lock-suite.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))
    assert set(on) == {"schedule", "workflow_dispatch"}, "never a PR's CI line"
    shards = wf["jobs"]["shards"]
    assert shards["strategy"]["matrix"]["shard"] == [1, 2, 3] and shards["strategy"]["fail-fast"] is False
    steps = "\n".join(s.get("run", "") for s in shards["steps"])
    assert "lock_suite.py constraints requirements.lock" in steps
    assert '-c "$RUNNER_TEMP/lock-constraints.txt" -e ".[analysis,dev,segmentation,pdf,ocr,geo]"' in steps
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    ci_pytest = next(s["run"] for s in ci["jobs"]["test"]["steps"] if s.get("name") == "Test (pytest)")
    assert ci_pytest in steps, "the same pytest line as ci.yml's test job"
    report = wf["jobs"]["report"]
    assert report["if"] == "always()" and report["permissions"]["issues"] == "write"
    assert any("lock_suite.py report" in s.get("run", "") for s in report["steps"])


def test_a_local_run_never_touches_the_repositorys_issues(tmp_path, monkeypatch):
    """A local dry run created the workflow's label on the real repository while this was built: only the workflow may."""
    mod = _mod()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    called = []
    monkeypatch.setattr(mod, "_gh", lambda args: called.append(args) or (0, ""))
    (tmp_path / "outcomes.json").write_text('{"shard 1": "failure"}', encoding="utf-8")
    assert mod.report(tmp_path) == 0
    assert called == [] and (tmp_path / "lock_suite_issue_body.md").exists()
