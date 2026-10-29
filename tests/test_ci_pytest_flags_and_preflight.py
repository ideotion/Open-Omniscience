"""The pytest flags of the two full-suite CI jobs, and the one local script that says it mirrors them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why. ``scripts/preflight.sh`` opened with "Mirrors ... the `test` job with the EXACT commands" and ran ``python -m pytest -q``, while the job ran
``python -m pytest -q -rfEs`` (the 2026-10-29 awk-step read named it, LOW). A claim of "exact" about a command line is a claim that nothing
checks, and it goes false the first time anyone adds a flag to ci.yml. Reading it for this PR found the same gap two more times: the script's
mypy gate compared an error count to a baseline that ci.yml stopped defining on 2026-08-20 (so 1 to 126 errors printed PASS where the job goes
red on one), and a substring check on its first version accepted a command that only appeared in an ``echo``. And the ``core-only`` job, which
skips the analysis-module tests on purpose, had the bare ``-q`` while its sibling printed every skip's reason.

What this pins:

* the ``test`` and ``core-only`` jobs each run exactly ``python -m pytest -q -rsfE --junitxml="$RUNNER_TEMP/junit.xml"`` in their pytest step.
  ``-r`` REPLACES pytest's default
  ``fE`` (reproduced on pytest 9.1.1: ``-rs`` alone prints only SKIPPED lines), and the summary is printed in the ORDER of the letters
  (``-rfEs``: FAILED, ERROR, SKIPPED; ``-rsfE``: SKIPPED, FAILED, ERROR). The last lines of a log are the ones a reader of a red run gets, and
  the skip block runs to hundreds of lines, so the skips come first and the failures last: ``-rfEs`` would put the failures out of the tail's reach;
* EVERY whole-suite pytest line of ``ci.yml`` and ``release.yml`` (no path, no ``-k`` / ``-m`` / ``--deselect`` / ``--ignore``: the lines that
  skip the tests whose package is missing) carries ``-rsfE``, so a skip count that differs between two jobs is read from their logs, and a NEW
  whole-suite line cannot come back bare. The four there today are named, so a deleted line cannot make the scan pass on nothing;
* the report is READ: straight after each full-suite job's installed-versions step comes one step that runs ``scripts/ci_skip_summary.py`` on
  that report, ``if: always()`` (a red suite is when "what did it not run" is asked), ``continue-on-error`` (an observation never turns a job red),
  and with no ``pytest`` in its command (tests/test_ci_installed_versions_step.py finds "the last pytest step" by that word);
* ``scripts/preflight.sh`` CALLS the ``test`` job's ruff correctness command and its mypy command unchanged (the calls are read out of its code
  lines, not its ``echo`` display lines and not its comments, and cut at the first ``;``, ``|``, ``)``, ``&&`` or redirection, so a flag appended to
  the call or a different path is a different call), gates mypy on its exit status and compares no count to a baseline, and its pytest command is
  the job's with the ``-rsfE`` and the ``--junitxml`` report removed and nothing else: a bare sandbox skips hundreds of tests and that block would
  bury the failures the advisory run is read for. The header SAYS so (it names both). A flag added to the job's pytest line breaks the last half
  and says why.

The guard proves itself: each mutant below is one property broken at ONE site (the real call, not its echo), and the checker must name it.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_RELEASE = _ROOT / ".github" / "workflows" / "release.yml"
_PREFLIGHT = _ROOT / "scripts" / "preflight.sh"

#: The two jobs that run the whole suite, block a merge, and write the junit report that their skip-summary step reads. ``portability`` also runs the
#: suite, as an observation lane, with ``-rsfE`` and no report (its Windows leg runs under PowerShell, which does not expand ``$RUNNER_TEMP``).
_JOBS = ("test", "core-only")
_SKIP_LISTING = " -rsfE"
_JUNIT = ' --junitxml="$RUNNER_TEMP/junit.xml"'
_PYTEST = "python -m pytest -q" + _SKIP_LISTING + _JUNIT
_SUMMARY = 'python scripts/ci_skip_summary.py "$RUNNER_TEMP/junit.xml" | tee -a "$GITHUB_STEP_SUMMARY"'
_VERSIONS = "pip list --format=freeze"
#: Where a whole-suite pytest line must exist today: (workflow file, job). A line that goes away is a change this guard must be told about.
_WHOLE_SUITE = (("ci", "test"), ("ci", "core-only"), ("ci", "portability"), ("release", "test"))
_RUFF = "ruff check --select=F,B --extend-ignore=B008 src/ tests/"
_MYPY = "python -m mypy src/"
#: (what the gate is called, the text that starts a call to the tool in a script line, the command the job runs).
_TOOLS = (("ruff correctness", "ruff check", _RUFF), ("mypy", "python -m mypy src", _MYPY))
_CALL_END = re.compile(r";|\||\)|&&|\s2>|\s>")
_EXIT_STATUS = re.compile(r"\w+=\$\?")
_PYTEST_LINE = re.compile(r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:python3?\s+-m\s+pytest|pytest)\b")
#: The options that choose which tests run: a command carrying one is a partial run, whatever else it says.
_SELECTING = re.compile(r"(?:^|\s)(?:-k|-m|--deselect|--ignore|--ignore-glob|--lf|--ff|--co|--collect-only)(?:[=\s]|$)")


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _workflows() -> dict[str, dict]:
    return {"ci": _workflow(), "release": yaml.safe_load(_RELEASE.read_text(encoding="utf-8"))}


def _runs(job: dict, needle: str) -> list[str]:
    """The ``run`` text of every step of ``job`` that contains ``needle``, stripped."""
    return [str(s.get("run") or "").strip() for s in job.get("steps") or [] if needle in str(s.get("run") or "")]


def _header(preflight: str) -> str:
    """The comment block before ``set -u``: what the script tells a reader it is."""
    return preflight.split("\nset -u", 1)[0]


def _code_lines(preflight: str) -> list[str]:
    """What the script EXECUTES: its stripped lines after the header, minus comments and the ``echo`` lines that only display a command."""
    body = preflight.split("\nset -u", 1)[1]
    stripped = (ln.strip() for ln in body.splitlines())
    return [s for s in stripped if s and not s.startswith(("#", "echo"))]


def _calls(code: list[str], marker: str) -> list[str]:
    """Every call to the tool that ``marker`` starts, from the marker to the end of the command (``;``, ``|``, ``)``, ``&&`` or a redirection)."""
    found: list[str] = []
    for line in code:
        at = line.find(marker)
        if at < 0:
            continue
        tail = line[at:]
        end = _CALL_END.search(tail)
        found.append((tail[: end.start()] if end else tail).strip())
    return found


def _summary_problems(name: str, job: dict) -> list[str]:
    """The skip-summary step of one full-suite job: present once, exact, on red as well as green, never red itself, straight after the versions step."""
    steps = job.get("steps") or []
    summary_at = [i for i, s in enumerate(steps) if "ci_skip_summary" in str(s.get("run") or "")]
    if len(summary_at) != 1:
        return [f"{name}: exactly one step must run scripts/ci_skip_summary.py on the junit report, {len(summary_at)} do"]
    step = steps[summary_at[0]]
    found: list[str] = []
    if str(step.get("run") or "").strip() != _SUMMARY:
        found.append(f"{name}: the skip-summary step must run exactly `{_SUMMARY}` (no `pytest` in it, the report path the pytest step writes), it runs {step.get('run')!r}")
    if step.get("if") != "always()":
        found.append(f"{name}: the skip-summary step must say `if: always()` (a red suite skips an unconditional step), it says {step.get('if')!r}")
    if step.get("continue-on-error") is not True:
        found.append(f"{name}: the skip-summary step must say `continue-on-error: true` (an observation never turns the job red), it says {step.get('continue-on-error')!r}")
    versions_at = [i for i, s in enumerate(steps) if _VERSIONS in str(s.get("run") or "")]
    if len(versions_at) != 1 or summary_at[0] != versions_at[0] + 1:
        found.append(f"{name}: the skip-summary step must come straight after the installed-versions step (tests/test_ci_installed_versions_step.py keeps that one straight after pytest)")
    return found


def _ci_problems(workflow: dict) -> list[str]:
    found: list[str] = []
    for name in _JOBS:
        runs = _runs(workflow["jobs"][name], "pytest")
        if runs != [_PYTEST]:
            found.append(f"{name}: the job's pytest step must run exactly `{_PYTEST}` (once), it runs {runs!r}")
        found += _summary_problems(name, workflow["jobs"][name])
    return found


def _whole_suite_commands(workflows: dict[str, dict]) -> list[tuple[str, str, str]]:
    """(workflow, job, command) of every pytest command that runs the whole suite: no test path and none of the options that choose tests."""
    found: list[tuple[str, str, str]] = []
    for which, workflow in workflows.items():
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                for line in str(step.get("run") or "").replace("\\\n", " ").splitlines():
                    if not _PYTEST_LINE.match(line) or _SELECTING.search(_PYTEST_LINE.sub("", line, count=1)):
                        continue
                    words = _PYTEST_LINE.sub("", line, count=1).split()
                    if any(not word.startswith("-") for word in words):  # a path (or any positional argument) names its tests
                        continue
                    found.append((which, job_name, line.strip()))
    return found


def _flag_problems(workflows: dict[str, dict]) -> list[str]:
    """Every whole-suite line carries ``-rsfE`` as a word of its own, and the lines this guard knows about are still there."""
    found: list[str] = []
    whole = _whole_suite_commands(workflows)
    for which, job_name in _WHOLE_SUITE:
        if not any(w == which and j == job_name for w, j, _ in whole):
            found.append(f"{which}/{job_name}: no whole-suite pytest line found, and this guard expects one (if the line was removed or given a path, change _WHOLE_SUITE)")
    for which, job_name, command in whole:
        if _SKIP_LISTING.strip() not in command.split():
            found.append(f"{which}/{job_name}: a whole-suite pytest line must carry `{_SKIP_LISTING.strip()}` (skips first, failures last), it is {command!r}")
    return found


def _preflight_problems(workflow: dict, preflight: str) -> list[str]:
    found: list[str] = []
    job = workflow["jobs"]["test"]
    code = _code_lines(preflight)
    for what, marker, command in _TOOLS:
        if _runs(job, command) != [command]:
            found.append(f"the `test` job must run `{command}` once; this guard compares preflight.sh's {what} gate against it")
        calls = _calls(code, marker)
        if not calls:
            found.append(f"preflight.sh must CALL the `test` job's {what} command `{command}` (an echo of it does not run it)")
        elif any(call != command for call in calls):
            found.append(f"preflight.sh's {what} call must be the job's `{command}` unchanged, it calls {calls!r}")
    mypy_at = [i for i, line in enumerate(code) if "python -m mypy src" in line]
    if mypy_at and not (mypy_at[-1] + 1 < len(code) and _EXIT_STATUS.fullmatch(code[mypy_at[-1] + 1])):
        found.append("preflight.sh must read mypy's exit status on the line straight after the call: the job's gate is that status, and a crash prints no error line")
    if any("baseline" in line.lower() for line in code):
        found.append("preflight.sh compares something to a baseline, but the job's mypy step is BLOCKING at any error (ci.yml defines no baseline)")
    ci_pytest = _runs(job, "pytest")
    differs = _SKIP_LISTING + _JUNIT
    if len(ci_pytest) != 1 or not ci_pytest[0].endswith(differs):
        found.append(f"the `test` job's pytest step must end in `{differs.strip()}`, it is {ci_pytest!r}")
    else:
        local = ci_pytest[0][: -len(differs)]
        if [line for line in code if "python -m pytest" in line] != [local]:
            found.append(f"preflight.sh must run `{local}` once: the `test` job's pytest command without `{differs.strip()}` and nothing else removed or added")
    for what in (_SKIP_LISTING.strip(), "--junitxml"):
        if what not in _header(preflight):
            found.append(f"preflight.sh's header must name `{what}`: one of the two ways its pytest line differs from the job's")
    return found


def test_the_two_full_suite_jobs_list_their_skips_first_and_keep_their_failures_last():
    assert _ci_problems(_workflow()) == []


def test_every_whole_suite_pytest_line_of_the_two_workflows_lists_its_skips_first():
    assert _flag_problems(_workflows()) == []


def test_preflight_runs_the_jobs_commands_and_says_how_its_pytest_line_differs():
    assert _preflight_problems(_workflow(), _PREFLIGHT.read_text(encoding="utf-8")) == []


# --- the guard proves itself: one property broken per mutant, at one site, and the checker names it -----------------------------------------------


def _with_pytest_run(workflow: dict, job_name: str, run: str) -> dict:
    out = copy.deepcopy(workflow)
    for step in out["jobs"][job_name]["steps"]:
        if "pytest" in str(step.get("run") or ""):
            step["run"] = run
    return out


def _edit_code(text: str, old: str, new: str) -> str:
    """``old`` -> ``new`` in the FIRST executed line (not an ``echo``, not a comment) that contains ``old``: one site, never the display copy of it."""
    head, rest = text.split("\nset -u", 1)
    lines = rest.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if old in line and not line.strip().startswith(("#", "echo")):
            lines[i] = line.replace(old, new, 1)
            return head + "\nset -u" + "".join(lines)
    raise AssertionError(f"no executed line contains {old!r}: the mutant would test nothing")


@pytest.mark.parametrize(
    ("job_name", "run", "says"),
    [
        ("core-only", "python -m pytest -q", "core-only"),
        ("core-only", "python -m pytest -q -rs", "core-only"),
        ("core-only", "python -m pytest -q -rfEs", "core-only"),
        ("test", "python -m pytest -q -rs", "test"),
        ("test", "python -m pytest -q -rfEs", "test"),
        ("test", "python -m pytest -q -rsfE -x", "test"),
        # the report the summary step reads is dropped, or written somewhere the step does not look
        ("test", "python -m pytest -q -rsfE", "test"),
        ("core-only", "python -m pytest -q -rsfE", "core-only"),
        ("core-only", 'python -m pytest -q -rsfE --junitxml="$RUNNER_TEMP/other.xml"', "core-only"),
    ],
)
def test_ci_flags_checker_names_a_job_that_drifts(job_name, run, says):
    problems = _ci_problems(_with_pytest_run(_workflow(), job_name, run))
    assert any(p.startswith(says + ":") for p in problems), problems


def _text_without_the_header_flag(text: str, flag: str) -> str:
    head, rest = text.split("\nset -u", 1)
    return head.replace(flag, "") + "\nset -u" + rest


@pytest.mark.parametrize(
    ("label", "mutate", "says"),
    [
        ("ci gains a pytest flag", lambda wf, t: (_with_pytest_run(wf, "test", "python -m pytest -q -rsfE -x"), t), "must end in"),
        ("ci drops the skip listing", lambda wf, t: (_with_pytest_run(wf, "test", "python -m pytest -q"), t), "must end in"),
        (
            "ruff call gains --exit-zero (the echo is untouched)",
            lambda wf, t: (wf, _edit_code(t, "src/ tests/; then", "src/ tests/ --exit-zero; then")),
            "ruff correctness call must be",
        ),
        ("ruff never runs (the echo is untouched)", lambda wf, t: (wf, _edit_code(t, "if ruff check --select=F,B --extend-ignore=B008 src/ tests/; then", "if true; then")), "must CALL"),
        ("mypy call is scoped to a subtree", lambda wf, t: (wf, _edit_code(t, "python -m mypy src/ 2>", "python -m mypy src/api/ 2>")), "mypy call must be"),
        ("mypy call gains a flag", lambda wf, t: (wf, _edit_code(t, "python -m mypy src/ 2>", "python -m mypy src/ --follow-imports=skip 2>")), "mypy call must be"),
        ("mypy exit status is not read", lambda wf, t: (wf, _edit_code(t, "mypy_rc=$?", "mypy_rc=0")), "exit status"),
        ("a baseline comes back", lambda wf, t: (wf, t.replace("\nfail=0\n", "\nfail=0\nbaseline=127\n", 1)), "baseline"),
        ("ci drops the junit report", lambda wf, t: (_with_pytest_run(wf, "test", "python -m pytest -q -rsfE"), t), "must end in"),
        ("preflight's pytest line gains a flag", lambda wf, t: (wf, _edit_code(t, "python -m pytest -q\n", "python -m pytest -q -x\n")), "pytest command without `-rsfE"),
        ("the header stops naming the skip listing", lambda wf, t: (wf, _text_without_the_header_flag(t, "-rsfE")), "header must name `-rsfE`"),
        ("the header stops naming the junit report", lambda wf, t: (wf, _text_without_the_header_flag(t, "--junitxml")), "header must name `--junitxml`"),
    ],
)
def test_preflight_checker_names_what_drifted(label, mutate, says):
    workflow, text = mutate(_workflow(), _PREFLIGHT.read_text(encoding="utf-8"))
    problems = _preflight_problems(workflow, text)
    assert any(says in p for p in problems), (label, problems)


# --- the skip summary: one step per full-suite job, straight after the installed versions, on red as well as green, never red itself ---------------


def _mutated_workflow(job_name: str, edit) -> dict:
    out = copy.deepcopy(_workflow())
    edit(out["jobs"][job_name]["steps"])
    return out


def _summary_index(steps: list[dict]) -> int:
    return next(i for i, s in enumerate(steps) if "ci_skip_summary" in str(s.get("run") or ""))


def _drop_summary(steps):
    del steps[_summary_index(steps)]


def _summary_before_versions(steps):
    at = _summary_index(steps)
    steps.insert(at - 1, steps.pop(at))


def _drop_condition(steps):
    del steps[_summary_index(steps)]["if"]


def _drop_continue(steps):
    del steps[_summary_index(steps)]["continue-on-error"]


def _set_run(run):
    def edit(steps):
        steps[_summary_index(steps)]["run"] = run

    return edit


def _second_summary(steps):
    steps.append(copy.deepcopy(steps[_summary_index(steps)]))


@pytest.mark.parametrize("job_name", _JOBS)
@pytest.mark.parametrize(
    ("label", "edit", "says"),
    [
        ("the step is gone", _drop_summary, "exactly one step must run"),
        ("the step runs twice", _second_summary, "exactly one step must run"),
        ("the step loses `if: always()`", _drop_condition, "`if: always()`"),
        ("the step loses `continue-on-error`", _drop_continue, "`continue-on-error: true`"),
        ("the step moves before the installed-versions step", _summary_before_versions, "straight after the installed-versions step"),
        ("the step reads a report nobody writes", _set_run('python scripts/ci_skip_summary.py "$RUNNER_TEMP/other.xml" | tee -a "$GITHUB_STEP_SUMMARY"'), "must run exactly"),
        ("the step stops writing the step summary", _set_run('python scripts/ci_skip_summary.py "$RUNNER_TEMP/junit.xml"'), "must run exactly"),
        # tests/test_ci_installed_versions_step.py finds the last pytest step by that word in `run`: the summary must not carry it
        ("the step names the test runner", _set_run(_SUMMARY + " # pytest"), "must run exactly"),
    ],
)
def test_summary_checker_names_what_drifted(job_name, label, edit, says):
    problems = _ci_problems(_mutated_workflow(job_name, edit))
    assert any(p.startswith(job_name + ":") and says in p for p in problems), (label, problems)


# --- the whole-suite scan: a bare line anywhere is named, a partial run is not a whole-suite line -------------------------------------------------


def _with_job_run(workflows: dict[str, dict], which: str, job_name: str, run: str) -> dict[str, dict]:
    out = copy.deepcopy(workflows)
    for step in out[which]["jobs"][job_name]["steps"]:
        if "pytest" in str(step.get("run") or ""):
            step["run"] = run
    return out


@pytest.mark.parametrize(
    ("which", "job_name", "run"),
    [
        ("ci", "portability", "python -m pytest -q"),
        ("ci", "portability", "python -m pytest -q -rs"),
        ("ci", "portability", "python -m pytest -q -rfEs"),
        ("release", "test", "python -m pytest -q"),
        ("release", "test", "python -m pytest -q -rfE"),
        ("ci", "test", "python -m pytest -q"),
        ("ci", "core-only", "PYTHONHASHSEED=0 python -m pytest -q"),
    ],
)
def test_the_scan_names_a_whole_suite_line_without_the_skip_listing(which, job_name, run):
    problems = _flag_problems(_with_job_run(_workflows(), which, job_name, run))
    assert any(p.startswith(f"{which}/{job_name}:") and "must carry `-rsfE`" in p for p in problems), problems


def test_the_scan_names_a_new_job_that_runs_the_whole_suite_bare():
    workflows = _workflows()
    workflows["ci"]["jobs"]["brand-new"] = {"steps": [{"run": "python -m pip install -e .\npython -m pytest -q"}]}
    problems = _flag_problems(workflows)
    assert any(p.startswith("ci/brand-new:") for p in problems), problems


def test_the_scan_names_a_whole_suite_line_that_has_gone_missing():
    problems = _flag_problems(_with_job_run(_workflows(), "release", "test", "python -m pytest -q tests/test_a.py"))
    assert any(p.startswith("release/test:") and "no whole-suite pytest line" in p for p in problems), problems


@pytest.mark.parametrize(
    "run",
    [
        "python -m pytest -q tests/test_a.py",
        "python -m pytest -q \\\n  tests/test_a.py \\\n  tests/test_b.py",
        "python -m pytest -q -k ci_encrypted_persisted_round_trip",
        "python -m pytest -q -m slow",
        "python -m pytest -q --deselect tests/test_a.py::test_b",
        "python -m pytest -q --ignore=tests/test_a.py",
        "python -m pytest -q --lf",
        "python -m pytest --collect-only -q",
        "# python -m pytest -q",
        "echo python -m pytest -q",
    ],
)
def test_the_scan_leaves_alone_a_partial_run_a_comment_and_an_echo(run):
    workflows = {"ci": {"jobs": {"j": {"steps": [{"run": run}]}}}}
    assert _whole_suite_commands(workflows) == [], run
