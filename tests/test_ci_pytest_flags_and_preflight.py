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

* the ``test`` and ``core-only`` jobs each run exactly ``python -m pytest -q -rsfE`` in their pytest step. ``-r`` REPLACES pytest's default
  ``fE`` (reproduced on pytest 9.1.1: ``-rs`` alone prints only SKIPPED lines), and the summary is printed in the ORDER of the letters
  (``-rfEs``: FAILED, ERROR, SKIPPED; ``-rsfE``: SKIPPED, FAILED, ERROR). The last lines of a log are the ones a reader of a red run gets, and
  the skip block runs to hundreds of lines, so the skips come first and the failures last: ``-rfEs`` would put the failures out of the tail's reach;
* ``scripts/preflight.sh`` CALLS the ``test`` job's ruff correctness command and its mypy command unchanged (the calls are read out of its code
  lines, not its ``echo`` display lines and not its comments, and cut at the first ``;``, ``|``, ``)``, ``&&`` or redirection, so a flag appended to
  the call or a different path is a different call), gates mypy on its exit status and compares no count to a baseline, and its pytest command is
  the job's with the ``-rsfE`` removed and nothing else: a bare sandbox skips hundreds of tests and that block would bury the failures the
  advisory run is read for. The header SAYS so (it names ``-rsfE``). A flag added to the job's pytest line breaks the last half and says why.

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
_PREFLIGHT = _ROOT / "scripts" / "preflight.sh"

#: The two jobs that run the whole suite and block a merge. ``portability`` also runs it, as an observation lane, and is left out on purpose.
_JOBS = ("test", "core-only")
_PYTEST = "python -m pytest -q -rsfE"
_SKIP_LISTING = " -rsfE"
_RUFF = "ruff check --select=F,B --extend-ignore=B008 src/ tests/"
_MYPY = "python -m mypy src/"
#: (what the gate is called, the text that starts a call to the tool in a script line, the command the job runs).
_TOOLS = (("ruff correctness", "ruff check", _RUFF), ("mypy", "python -m mypy src", _MYPY))
_CALL_END = re.compile(r";|\||\)|&&|\s2>|\s>")
_EXIT_STATUS = re.compile(r"\w+=\$\?")


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


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
    if len(ci_pytest) != 1 or not ci_pytest[0].endswith(_SKIP_LISTING):
        found.append(f"the `test` job's pytest step must end in `{_SKIP_LISTING.strip()}`, it is {ci_pytest!r}")
    else:
        local = ci_pytest[0][: -len(_SKIP_LISTING)]
        if [line for line in code if "python -m pytest" in line] != [local]:
            found.append(f"preflight.sh must run `{local}` once: the `test` job's pytest command without `{_SKIP_LISTING.strip()}` and nothing else removed or added")
    if _SKIP_LISTING.strip() not in _header(preflight):
        found.append(f"preflight.sh's header must name `{_SKIP_LISTING.strip()}`: the one way its pytest line differs from the job's")
    return found


def test_the_two_full_suite_jobs_list_their_skips_first_and_keep_their_failures_last():
    assert _ci_problems(_workflow()) == []


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
    ],
)
def test_ci_flags_checker_names_a_job_that_drifts(job_name, run, says):
    problems = _ci_problems(_with_pytest_run(_workflow(), job_name, run))
    assert any(p.startswith(says + ":") for p in problems), problems


def _text_without_the_header_flag(text: str) -> str:
    head, rest = text.split("\nset -u", 1)
    return head.replace("-rsfE", "") + "\nset -u" + rest


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
        ("preflight's pytest line gains a flag", lambda wf, t: (wf, _edit_code(t, "python -m pytest -q\n", "python -m pytest -q -x\n")), "without `-rsfE`"),
        ("the header stops naming the difference", lambda wf, t: (wf, _text_without_the_header_flag(t)), "header must name"),
    ],
)
def test_preflight_checker_names_what_drifted(label, mutate, says):
    workflow, text = mutate(_workflow(), _PREFLIGHT.read_text(encoding="utf-8"))
    problems = _preflight_problems(workflow, text)
    assert any(says in p for p in problems), (label, problems)
