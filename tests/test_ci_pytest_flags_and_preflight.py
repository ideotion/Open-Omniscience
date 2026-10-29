"""The pytest flags of the two full-suite CI jobs, and the one local script that says it mirrors them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why. ``scripts/preflight.sh`` opened with "Mirrors ... the `test` job with the EXACT commands" and ran ``python -m pytest -q``, while the job ran
``python -m pytest -q -rfEs`` (the 2026-10-29 awk-step read named it, LOW). A claim of "exact" about a command line is a claim that nothing
checks, and it goes false the first time anyone adds a flag to ci.yml. And the ``core-only`` job, which skips the analysis-module tests on
purpose, had the bare ``-q`` while its sibling printed every skip's reason.

What this pins:

* the ``test`` and ``core-only`` jobs each run exactly ``python -m pytest -q -rfEs`` in their pytest step. ``-r`` REPLACES pytest's default
  ``fE`` (reproduced on pytest 9.1.1: ``-rs`` alone prints only SKIPPED lines), so the flags are the default plus ``s``; ``-rs`` alone would
  hide the names of the failing tests from the tail of a red run's log;
* ``scripts/preflight.sh`` runs the ``test`` job's ruff correctness command and its mypy command verbatim, and its pytest command is the job's
  with the ``-rfEs`` removed and nothing else: a bare sandbox skips hundreds of tests and that block would bury the failures the advisory run
  is read for, and the header SAYS so (it names ``-rfEs``). A flag added to the job's pytest line breaks the second half and says why.

The guard proves itself: each mutant below is one property broken, and the checker must name it.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_PREFLIGHT = _ROOT / "scripts" / "preflight.sh"

#: The two jobs that run the whole suite and block a merge. ``portability`` also runs it, as an observation lane, and is left out on purpose.
_JOBS = ("test", "core-only")
_PYTEST = "python -m pytest -q -rfEs"
_SKIP_LISTING = " -rfEs"
_RUFF = "ruff check --select=F,B --extend-ignore=B008 src/ tests/"
_MYPY = "python -m mypy src/"


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _runs(job: dict, needle: str) -> list[str]:
    """The ``run`` text of every step of ``job`` that contains ``needle``, stripped."""
    return [str(s.get("run") or "").strip() for s in job.get("steps") or [] if needle in str(s.get("run") or "")]


def _header(preflight: str) -> str:
    """The comment block before ``set -u``: what the script tells a reader it is."""
    return preflight.split("\nset -u", 1)[0]


def _ci_problems(workflow: dict) -> list[str]:
    found: list[str] = []
    for name in _JOBS:
        runs = _runs(workflow["jobs"][name], "pytest")
        if runs != [_PYTEST]:
            found.append(f"{name}: the job's pytest step must run exactly `{_PYTEST}` (once), it runs {runs!r}")
    return found


def _preflight_problems(workflow: dict, preflight: str) -> list[str]:
    found: list[str] = []
    job = workflow["jobs"]["test"]
    lines = {ln.strip() for ln in preflight.splitlines()}
    for what, command in (("ruff correctness", _RUFF), ("mypy", _MYPY)):
        if _runs(job, command) != [command]:
            found.append(f"the `test` job must run `{command}` once; this guard compares preflight.sh's {what} gate against it")
        if not any(command in ln for ln in lines):
            found.append(f"preflight.sh must run the `test` job's {what} command `{command}`")
    ci_pytest = _runs(job, "pytest")
    if len(ci_pytest) != 1 or not ci_pytest[0].endswith(_SKIP_LISTING):
        found.append(f"the `test` job's pytest step must end in `{_SKIP_LISTING.strip()}`, it is {ci_pytest!r}")
    else:
        local = ci_pytest[0][: -len(_SKIP_LISTING)]
        if local not in lines:
            found.append(f"preflight.sh must run `{local}`: the `test` job's pytest command without `{_SKIP_LISTING.strip()}` and nothing else removed or added")
    if _SKIP_LISTING.strip() not in _header(preflight):
        found.append(f"preflight.sh's header must name `{_SKIP_LISTING.strip()}`: the one way its pytest line differs from the job's")
    return found


def test_the_two_full_suite_jobs_list_their_skips_without_hiding_their_failures():
    assert _ci_problems(_workflow()) == []


def test_preflight_runs_the_jobs_commands_and_says_how_its_pytest_line_differs():
    assert _preflight_problems(_workflow(), _PREFLIGHT.read_text(encoding="utf-8")) == []


# --- the guard proves itself: one property broken per mutant, and the checker names it ----------------------------------------------------------


def _with_pytest_run(workflow: dict, job_name: str, run: str) -> dict:
    out = copy.deepcopy(workflow)
    for step in out["jobs"][job_name]["steps"]:
        if "pytest" in str(step.get("run") or ""):
            step["run"] = run
    return out


@pytest.mark.parametrize(
    ("job_name", "run", "says"),
    [
        ("core-only", "python -m pytest -q", "core-only"),
        ("core-only", "python -m pytest -q -rs", "core-only"),
        ("test", "python -m pytest -q -rs", "test"),
        ("test", "python -m pytest -q -rfEs -x", "test"),
    ],
)
def test_ci_flags_checker_names_a_job_that_drifts(job_name, run, says):
    problems = _ci_problems(_with_pytest_run(_workflow(), job_name, run))
    assert any(p.startswith(says + ":") for p in problems), problems


def _text_without_the_header_flag(text: str) -> str:
    head, rest = text.split("\nset -u", 1)
    return head.replace("-rfEs", "") + "\nset -u" + rest


@pytest.mark.parametrize(
    ("label", "mutate", "says"),
    [
        ("ci gains a pytest flag", lambda wf, t: (_with_pytest_run(wf, "test", "python -m pytest -q -rfEs -x"), t), "must end in"),
        ("ci drops the skip listing", lambda wf, t: (_with_pytest_run(wf, "test", "python -m pytest -q"), t), "must end in"),
        ("preflight's ruff gate drifts", lambda wf, t: (wf, t.replace(_RUFF, "ruff check --select=F,B src/ tests/")), "ruff correctness"),
        ("preflight's mypy command drifts", lambda wf, t: (wf, t.replace(_MYPY, "python -m mypy src")), "mypy"),
        ("preflight's pytest line gains a flag", lambda wf, t: (wf, t.replace("python -m pytest -q\n", "python -m pytest -q -x\n")), "without `-rfEs`"),
        ("the header stops naming the difference", lambda wf, t: (wf, _text_without_the_header_flag(t)), "header must name"),
    ],
)
def test_preflight_checker_names_what_drifted(label, mutate, says):
    workflow, text = mutate(_workflow(), _PREFLIGHT.read_text(encoding="utf-8"))
    problems = _preflight_problems(workflow, text)
    assert any(says in p for p in problems), (label, problems)
