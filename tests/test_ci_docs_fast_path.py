"""The docs-only fast path of ci.yml (R462): what counts as documentation, that it fails open, and that no job is left out of the decision.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The path rule lives in ``scripts/ci_changed_kind.py``; the workflow only calls it. The risk is a fast path taken where it should not be: a change that
touches code but is judged documentation, or a job that was never told to wait for the decision and so runs (or is skipped) by accident.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
import ci_changed_kind as K  # noqa: E402

_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_GATED = "needs.changes.outputs.docs_only != 'true'"

#: Jobs that are NOT gated by the decision, each with the reason. A new job must be gated or named here.
_NOT_GATED = {
    "scheduled-audit": "runs only on the weekly schedule",
    "changes": "makes the decision",
    "docs-checks": "is the fast path itself (runs only when docs_only is true)",
    "test-all": "aggregator: the required check `test`; reports on every run",
    "core-only-all": "aggregator: the required check Core-only; reports on every run",
    "sqlcipher-smoke": "a second per OS; the one per-push macOS signal",
    "portability": "macOS, weekly and on every dispatch; never part of a plain pull_request run",
    "portability-windows": "Windows, nightly on main and on a dispatch that asks for it (R743); never part of a pull request",
}


@pytest.mark.parametrize(
    "path",
    ["docs/ledger/OPEN_QUEUE.md", "docs/ledger/shipped.d/2026-11-07-x.csv", "CLAUDE.md", "README.md", ".github/PULL_REQUEST_TEMPLATE.md", ".github/ISSUE_TEMPLATE/bug_report.md"],
)
def test_documentation_paths_are_documentation(path):
    assert K.is_doc(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/api/main.py",
        "tests/test_x.py",
        "scripts/README.md",
        "configs/stopwords_iso/NOTICE.md",
        "pyproject.toml",
        "requirements.lock",
        ".github/workflows/ci.yml",
        ".github/workflows/notes.md",
        ".github/copilot-instructions.md",
        "docs/../src/api/main.py",
        "/etc/passwd",
        "",
    ],
)
def test_everything_else_is_not(path):
    assert not K.is_doc(path)


def test_one_code_file_among_many_docs_means_the_full_matrix():
    assert K.docs_only(["docs/a.md", "docs/b.md", "CLAUDE.md"])
    assert not K.docs_only(["docs/a.md", "src/x.py"])


def test_nothing_changed_or_unknown_fails_open():
    assert not K.docs_only([])
    assert not K.docs_only(["", "  "])


def test_a_git_error_fails_open(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not a repository
    assert K.main(["nope", "nope2"]) == 0
    assert capsys.readouterr().out.strip() == "docs_only=false"


def test_the_stdin_form_prints_the_workflow_line(monkeypatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/a.md\nREADME.md\n"))
    assert K.main(["--stdin"]) == 0
    assert capsys.readouterr().out.strip() == "docs_only=true"


def _jobs() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]


def test_every_job_is_gated_by_the_decision_or_named_with_its_reason():
    loose = []
    for name, job in _jobs().items():
        if name in _NOT_GATED:
            continue
        if _GATED not in str(job.get("if") or "") or "changes" not in (job.get("needs") or []):
            loose.append(name)
    assert loose == [], f"jobs neither gated on `changes` nor listed in _NOT_GATED with a reason: {loose}"


def test_the_not_gated_list_names_real_jobs():
    assert set(_NOT_GATED) <= set(_jobs()), sorted(set(_NOT_GATED) - set(_jobs()))


def test_the_decision_fails_open_for_everything_but_a_plain_pull_request():
    steps = _jobs()["changes"]["steps"]
    script = "\n".join(str(s.get("run") or "") for s in steps)
    assert 'verdict="docs_only=false"' in script, "the default must be the full matrix"
    assert '"$EVENT" = "pull_request"' in script and '"$FORCE_FULL" != "true"' in script
    assert "|| echo docs_only=false" in script, "a script failure must mean the full matrix"
    env = {k: v for s in steps for k, v in (s.get("env") or {}).items()}
    assert "ci-full" in env["FORCE_FULL"]


def test_the_fast_path_runs_only_when_the_decision_says_so_and_checks_the_ledger():
    job = _jobs()["docs-checks"]
    assert job["if"] == "needs.changes.outputs.docs_only == 'true'"
    run = "\n".join(str(s.get("run") or "") for s in job["steps"])
    for needle in ("planned.py", "ledger_fold.py check", "i18n_report.py --min 100", "pytest", "check_wheel_layout.py", "grep -lE 'docs|"):
        assert needle in run, needle


def test_portability_is_not_part_of_a_pull_request_and_fits_its_cap():
    job = _jobs()["portability"]
    assert job["if"] == "github.event.schedule == '0 6 * * 1' || github.event_name == 'workflow_dispatch'"
    assert job["strategy"]["matrix"] == {"os": ["macos-latest"], "shard": [1, 2, 3]}, "Windows has its own job (R743)"
    # 60 min a macOS leg (row 93): a cap cannot quietly grow
    assert job["timeout-minutes"] == 60 and job["continue-on-error"] is True


def test_windows_runs_nightly_on_main_and_on_request_in_six_non_required_shards():
    """R743: on every PR dispatch the three Windows legs hit their cap and proved nothing; they run once a night, and when a dispatch asks."""
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    job = workflow["jobs"]["portability-windows"]
    crons = [c["cron"] for c in workflow[True]["schedule"]]
    assert job["if"] == "github.event.schedule == '0 2 * * *' || (github.event_name == 'workflow_dispatch' && inputs.windows)"
    assert "0 2 * * *" in crons and "0 6 * * 1" in crons
    windows = workflow[True]["workflow_dispatch"]["inputs"]["windows"]
    assert windows["type"] == "boolean" and windows["default"] is False, "a plain dispatch (every PR line) must not start the Windows legs"
    assert job["runs-on"] == "windows-latest" and job["strategy"]["matrix"]["shard"] == [1, 2, 3, 4, 5, 6]
    assert job["timeout-minutes"] == 120 and job["continue-on-error"] is True  # row 238: 90 until shard 1 measured 70.6 to over 90 minutes
    plan = [s["run"] for s in job["steps"] if "ci_shard.py plan" in str(s.get("run") or "")]
    assert plan == ["python scripts/ci_shard.py plan --shard ${{ matrix.shard }}/6 --out shard.args"], plan
    assert "macos-latest" not in str(job) and "windows-latest" not in str(workflow["jobs"]["portability"]["strategy"])


def test_each_scheduled_job_names_its_own_cron():
    """Two crons: a job that tested only ``event_name == 'schedule'`` would run on both, so the weekly audit would run every night."""
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    crons = {c["cron"] for c in workflow[True]["schedule"]}
    for name, job in workflow["jobs"].items():
        cond = str(job.get("if") or "")
        assert "event_name == 'schedule'" not in cond, f"{name} runs on every cron; name the one it wants with github.event.schedule"
        for cron in re.findall(r"github\.event\.schedule == '([^']+)'", cond):
            assert cron in crons, f"{name} waits for a cron the workflow does not have: {cron}"
    assert workflow["jobs"]["scheduled-audit"]["if"] == "github.event.schedule == '0 6 * * 1'"
