"""CI builds this project's wheel the way release.yml does and reads its file list, in the lockfile-install job (R380).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why the step exists. ``release.yml`` is the only workflow that builds the wheel, and it builds it at TAG time; every CI job installs the project
editable, which reads the checkout and can never show a file the wheel lacks, so a data file the code reads and the wheel does not carry used to be
found after the tag (the quiet case on record is ``src/geo/data``, uncovered by every built wheel from the day it was added; R330 was the occasion on
which the question was raised, and it was a path bug that this check does not catch). ``scripts/check_wheel_layout.py`` reads the built wheel's own
file list (its rule and its limits are pinned in ``tests/test_wheel_layout_check.py``); this file pins that CI really builds the wheel and runs it.

What this pins, for the one job R380 names (``lockfile-install``, the short job that already installs the project from a clean environment):

* the step exists exactly once in that job (a copy in another job leaves this one without it);
* the step's commands are exactly three, each alone on its line: install ``build``, ``python -m build --outdir DIR`` (the command ``release.yml`` runs,
  which builds the sdist first and the wheel from the sdist, so ``MANIFEST.in`` decides what the wheel carries here as it does there; a direct
  ``pip wheel .`` does not), and ``python scripts/check_wheel_layout.py`` on exactly ``DIR/*.whl``, in that order;
* nothing makes the step pass when the check fails: the workflow sets no default shell, so a step runs plain ``bash -e`` without ``pipefail``, and a pipe,
  ``||``, ``&``, ``!``, an ``if``, ``set +e`` or ``continue-on-error`` (on the step or the job) each hide the exit status, so none is allowed; the step has
  no ``if:``, ``shell:`` or ``working-directory:``, and the job keeps its one condition.

The guard proves itself: each mutant below is the workflow with one property removed, and the checker must name it.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"

_JOB = "lockfile-install"
_JOB_IF = "github.event_name != 'schedule'"
_STEP_PREFIX = "Wheel carries the runtime data trees"
_SCRIPT = "scripts/check_wheel_layout.py"
_INSTALL_LINE = "python -m pip install --upgrade build"
_BUILD_RE = re.compile(r"^python -m build --outdir (\S+)$")
_CHECK_RE = re.compile(r"^python scripts/check_wheel_layout\.py (\S+)$")
_FORBIDDEN_STEP_KEYS = ("if", "shell", "working-directory")


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _runs(step: dict) -> str:
    return str(step.get("run") or "")


def _truthy(value: object) -> bool:
    """GitHub reads ``continue-on-error: "false"`` as false, so a string is compared by its text."""
    return str(value).strip().lower() not in ("", "none", "false")


def _unquote(token: str) -> str:
    return token.replace('"', "")


def _problems(workflow: dict) -> list[str]:
    """Everything wrong with the wheel-layout step of the workflow, as sentences; empty when it is as pinned above."""
    job = (workflow.get("jobs") or {}).get(_JOB)
    if job is None:
        return [f"the workflow has no job named {_JOB}"]
    found: list[str] = []
    if job.get("if") != _JOB_IF:
        found.append(f"{_JOB}: the job's own `if` must stay `{_JOB_IF}`, it says {job.get('if')!r}")
    if _truthy(job.get("continue-on-error")):
        found.append(f"{_JOB}: the job must not say continue-on-error (job-level)")
    steps = job.get("steps") or []
    mine = [s for s in steps if str(s.get("name") or "").startswith(_STEP_PREFIX)]
    if len(mine) != 1:
        return [*found, f"{_JOB}: expected exactly one step named '{_STEP_PREFIX}...', found {len(mine)}"]
    step = mine[0]
    if _truthy(step.get("continue-on-error")):
        found.append(f"{_JOB}: the step must not say continue-on-error (a red wheel check must redden the job)")
    for key in _FORBIDDEN_STEP_KEYS:
        if key in step:
            found.append(f"{_JOB}: the step must not set `{key}:` (it runs on every pull request, in the repository root, under the default shell)")
    lines = [line.strip() for line in _runs(step).splitlines() if line.strip() and not line.strip().startswith("#")]
    build = [i for i, line in enumerate(lines) if _BUILD_RE.match(line)]
    check = [i for i, line in enumerate(lines) if _CHECK_RE.match(line)]
    if not build:
        near = [line for line in lines if line != _INSTALL_LINE and re.search(r"\bbuild\b|pip wheel|install -e", line)]
        found.append(
            f"{_JOB}: the step must build the wheel with `python -m build --outdir DIR` alone on its line, as release.yml does"
            + (f"; the nearest line is {near[0]!r}" if near else "")
        )
    if not check:
        near = [line for line in lines if "check_wheel_layout" in line]
        found.append(
            f"{_JOB}: the step must run `{_SCRIPT} DIR/*.whl` alone on its line (no pipe, `||`, `&`, `!` or `if`); the nearest line is {near[0]!r}"
            if near
            else f"{_JOB}: no line runs {_SCRIPT} on the wheel"
        )
    allowed = [lines[i] for i in (*build, *check)] + [_INSTALL_LINE]
    for line in lines:
        if line not in allowed:
            found.append(f"{_JOB}: the step may run only the install of build, the build and the checker; it also runs {line!r}")
    if build and check:
        if build[0] > check[0]:
            found.append(f"{_JOB}: the step must build the wheel before it runs the checker")
        out_dir = _unquote(_BUILD_RE.match(lines[build[0]]).group(1))  # type: ignore[union-attr]
        read = _unquote(_CHECK_RE.match(lines[check[0]]).group(1))  # type: ignore[union-attr]
        if read != f"{out_dir}/*.whl":
            found.append(f"{_JOB}: the checker must read exactly the directory the build wrote ({out_dir}/*.whl), it reads {read}")
    if not (_ROOT / _SCRIPT).is_file():
        found.append(f"{_SCRIPT} does not exist")
    return found


def test_the_lockfile_job_builds_the_wheel_and_reads_its_file_list():
    assert _problems(_workflow()) == []


def test_a_string_false_is_not_an_error_flag():
    wf = _workflow()
    step = next(s for s in wf["jobs"][_JOB]["steps"] if str(s.get("name") or "").startswith(_STEP_PREFIX))
    step["continue-on-error"] = "false"
    assert _problems(wf) == []


# --- the guard proves itself: one property removed per mutant, and the checker names it ---------------------------------------------------------


def _mutants() -> dict[str, tuple[dict, str]]:
    """label -> (the workflow with one property removed, the sentence the checker must say about it)."""
    base = _workflow()
    out: dict[str, tuple[dict, str]] = {}

    def mutated(edit, says: str) -> tuple[dict, str]:
        wf = copy.deepcopy(base)
        steps = wf["jobs"][_JOB]["steps"]
        at = next(i for i, s in enumerate(steps) if str(s.get("name") or "").startswith(_STEP_PREFIX))
        edit(wf, steps, at)
        return wf, says

    def rewrite(old: str, new: str):
        def edit(wf, steps, at):
            text = _runs(steps[at])
            assert old in text, f"the mutant's anchor {old!r} is not in the step"
            steps[at]["run"] = text.replace(old, new)

        return edit

    def set_key(key: str, value):
        return lambda wf, steps, at: steps[at].__setitem__(key, value)

    build_line = 'python -m build --outdir "$RUNNER_TEMP/oo-dist"'
    check_line = f'python {_SCRIPT} "$RUNNER_TEMP"/oo-dist/*.whl'
    out["the step is removed"] = mutated(lambda wf, steps, at: steps.pop(at), "found 0")
    out["the step is in another job (the wrong job)"] = mutated(
        lambda wf, steps, at: wf["jobs"]["core-only"]["steps"].append(steps.pop(at)), "found 0"
    )
    out["the step is duplicated"] = mutated(lambda wf, steps, at: steps.append(copy.deepcopy(steps[at])), "found 2")
    out["a direct pip wheel instead of python -m build (the wheel skips the sdist)"] = mutated(
        rewrite(build_line, 'python -m pip wheel . --no-deps -w "$RUNNER_TEMP/oo-dist"'), "the nearest line is 'python -m pip wheel"
    )
    out["an editable install instead of a build"] = mutated(rewrite(build_line, "python -m pip install -e ."), "the nearest line is 'python -m pip install -e .'")
    out["the build skips isolation"] = mutated(rewrite(build_line, build_line + " --no-isolation"), "--no-isolation")
    out["the build is piped to tail"] = mutated(rewrite(build_line, build_line + " | tail -n 40"), "| tail")
    out["the build is only in a comment"] = mutated(rewrite(build_line, "# " + build_line), "the step must build the wheel with")
    out["the checker is not run"] = mutated(rewrite(_SCRIPT, "scripts/some_other_script.py"), f"no line runs {_SCRIPT}")
    out["the checker's output is tee'd (no pipefail, the exit status is tee's)"] = mutated(
        rewrite(check_line, check_line + ' | tee -a "$GITHUB_STEP_SUMMARY"'), "| tee"
    )
    out["the checker's failure is swallowed (|| true)"] = mutated(rewrite(check_line, check_line + " || true"), "|| true")
    out["the checker runs in the background"] = mutated(rewrite(check_line, check_line + " &"), "*.whl &")
    out["the checker's status is negated"] = mutated(rewrite(check_line, "! " + check_line), "'! python")
    out["the checker is inside an if"] = mutated(rewrite(check_line, f"if {check_line}; then :; fi"), "'if python")
    out["errexit is turned off"] = mutated(rewrite(build_line, "set +e\n" + build_line), "also runs 'set +e'")
    out["an extra command is run"] = mutated(rewrite(build_line, "echo hello\n" + build_line), "also runs 'echo hello'")
    out["the checker runs before the build"] = mutated(rewrite(f"{build_line}\n{check_line}", f"{check_line}\n{build_line}"), "before it runs the checker")
    out["the checker reads another directory than the build wrote"] = mutated(
        rewrite('"$RUNNER_TEMP"/oo-dist/*.whl', '"$RUNNER_TEMP"/oo-dist-old/*.whl'), "exactly the directory the build wrote"
    )
    out["continue-on-error: true on the step"] = mutated(set_key("continue-on-error", True), "must not say continue-on-error (a red wheel check")
    out["continue-on-error: 'true' as a string"] = mutated(set_key("continue-on-error", "true"), "must not say continue-on-error (a red wheel check")
    out["the step only runs on tags"] = mutated(set_key("if", "startsWith(github.ref, 'refs/tags/v')"), "must not set `if:`")
    out["the step sets a shell"] = mutated(set_key("shell", "bash {0}"), "must not set `shell:`")
    out["the step runs in another directory"] = mutated(set_key("working-directory", "docs"), "must not set `working-directory:`")
    out["continue-on-error: true on the job"] = mutated(
        lambda wf, steps, at: wf["jobs"][_JOB].__setitem__("continue-on-error", True), "must not say continue-on-error (job-level)"
    )
    out["the job never runs"] = mutated(lambda wf, steps, at: wf["jobs"][_JOB].__setitem__("if", "false"), "the job's own `if` must stay")
    out["the job is renamed (the step is no longer in lockfile-install)"] = mutated(
        lambda wf, steps, at: wf["jobs"].__setitem__("lockfile-renamed", wf["jobs"].pop(_JOB)), f"has no job named {_JOB}"
    )
    return out


def test_every_mutant_of_the_step_is_named_by_the_checker():
    for label, (workflow, says) in _mutants().items():
        found = _problems(workflow)
        assert any(says in problem for problem in found), f"{label}: expected a problem saying {says!r}, got {found}"


def test_every_mutant_leaves_the_workflow_with_a_problem():
    """The unmutated workflow is clean, so a mutant whose edit did not take would show up here as still clean."""
    assert _problems(_workflow()) == []
    for label, (workflow, _says) in _mutants().items():
        assert _problems(workflow), f"{label}: the mutant is still clean"
