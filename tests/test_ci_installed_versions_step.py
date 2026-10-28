"""CI keeps the installed package versions in the log tail, on red as well as green (R364).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why the step exists. On 27-28 Oct 2026 the same code went green and then red with no merge in between (R349): pytest 9.2.0 had been published
between the two runs and CI installs ``pytest>=8.2`` unpinned. Finding that took a comparison of installed versions between a green and a red
job, and the versions are printed by the install step, at the HEAD of a log that is several thousand lines long. The only reader that was
available (``get_job_logs``) returns the last 5000 lines, so the install output was out of reach and the cause had to be rebuilt from three
sibling jobs that happened to be short. The versions are therefore printed again at the END, by a step that runs whatever the tests did.

What this pins, for the two jobs R364 names (``test`` and ``core-only``; the ``portability`` job runs the whole suite as well, as an observation lane
with ``continue-on-error``, and is not covered):

* the step exists once and says ``if: always()``: a red pytest step skips every later step that has no condition, which is the whole point;
* it runs ``python -m pip list --format=freeze`` (not ``pip freeze``, whose editable-install line carries the repository URL and the commit and
  which leaves pip itself out) and ``tee``s the result into ``$GITHUB_STEP_SUMMARY``, so it is in the log as well as in the summary: a plain
  redirect would take the list out of the log, the one copy ``get_job_logs`` can read;
* it comes straight after the pytest step and before any later ``pip install`` step: in ``test`` the bandit and pip-audit steps install their
  own packages, and a list taken after them is not the environment the tests ran in.

The guard proves itself: each mutant below is the step with one property removed, and the checker must name it.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"

#: The jobs R364 names. The other lanes run a named subset, except ``portability`` (macOS, observation only), which is left out on purpose.
_JOBS = ("test", "core-only")
_STEP_PREFIX = "Installed versions"
_COMMAND = "python -m pip list --format=freeze"
_SUMMARY = "$GITHUB_STEP_SUMMARY"
_TEE = f'tee -a "{_SUMMARY}"'


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _runs(step: dict) -> str:
    return str(step.get("run") or "")


def _problems(job_name: str, job: dict) -> list[str]:
    """Everything wrong with the installed-versions step of one job, as sentences; empty when it is as pinned above."""
    steps = job.get("steps") or []
    reports = [i for i, s in enumerate(steps) if str(s.get("name") or "").startswith(_STEP_PREFIX)]
    if len(reports) != 1:
        return [f"{job_name}: expected exactly one step named '{_STEP_PREFIX}...', found {len(reports)}"]
    at = reports[0]
    step = steps[at]
    found: list[str] = []
    if str(step.get("if") or "").strip() != "always()":
        found.append(f"{job_name}: the step must say `if: always()` (a red pytest step skips an unconditional step), it says {step.get('if')!r}")
    if _COMMAND not in _runs(step):
        found.append(f"{job_name}: the step must run `{_COMMAND}`")
    if _TEE not in _runs(step):
        found.append(f"{job_name}: the step must `{_TEE}`: to the log as well as to the summary, not a redirect that takes it out of the log")
    pytest_steps = [i for i, s in enumerate(steps) if "pytest" in _runs(s) and i != at]
    if not pytest_steps:
        found.append(f"{job_name}: no pytest step found, so there is nothing to report the environment of")
    elif at != max(pytest_steps) + 1:
        found.append(f"{job_name}: the step must come straight after the last pytest step (step {max(pytest_steps)}), it is step {at}")
    return found


@pytest.mark.parametrize("job_name", _JOBS)
def test_the_job_reports_its_installed_versions_after_pytest_on_red_as_well_as_green(job_name):
    job = _workflow()["jobs"][job_name]
    assert _problems(job_name, job) == []


# --- the guard proves itself: one property removed per mutant, and the checker names it ---------------------------------------------------------


def _mutants(job_name: str) -> dict[str, tuple[dict, str]]:
    """label -> (the job with one property removed, the sentence the checker must say about it)."""
    base = _workflow()["jobs"][job_name]
    out: dict[str, tuple[dict, str]] = {}

    def mutated(edit, says: str) -> tuple[dict, str]:
        job = copy.deepcopy(base)
        steps = job["steps"]
        at = next(i for i, s in enumerate(steps) if str(s.get("name") or "").startswith(_STEP_PREFIX))
        edit(steps, at)
        return job, says

    def rewrite(old: str, new: str):
        return lambda steps, at: steps[at].__setitem__("run", _runs(steps[at]).replace(old, new))

    last_pytest = lambda steps: max(i for i, s in enumerate(steps) if "pytest" in _runs(s))  # noqa: E731
    out["no `if: always()`"] = mutated(lambda steps, at: steps[at].pop("if"), "must say `if: always()`")
    out["`if: failure()` only"] = mutated(lambda steps, at: steps[at].__setitem__("if", "failure()"), "must say `if: always()`")
    out["`pip freeze` instead of `pip list --format=freeze`"] = mutated(rewrite(_COMMAND, "python -m pip freeze"), f"must run `{_COMMAND}`")
    out["a redirect to the summary instead of `tee` (the list leaves the log)"] = mutated(
        rewrite(f"| {_TEE}", f">> \"{_SUMMARY}\""), "to the log as well as to the summary"
    )
    out["not written to the step summary at all"] = mutated(rewrite(_SUMMARY, "/dev/null"), "to the log as well as to the summary")
    out["the step is missing"] = mutated(lambda steps, at: steps.pop(at), "expected exactly one step")
    out["the step comes before pytest"] = mutated(
        lambda steps, at: steps.insert(last_pytest(steps), steps.pop(at)), "straight after the last pytest step"
    )
    out["a step between pytest and the report (a later `pip install` would change the list)"] = mutated(
        lambda steps, at: steps.insert(at, {"name": "Install a scanner", "run": "python -m pip install bandit==1.9.4"}),
        "straight after the last pytest step",
    )
    return out


@pytest.mark.parametrize("job_name", _JOBS)
def test_every_mutant_of_the_step_is_named_by_the_checker(job_name):
    for label, (job, says) in _mutants(job_name).items():
        found = _problems(job_name, job)
        assert any(says in problem for problem in found), f"{job_name}: {label}: expected a problem saying {says!r}, got {found}"
