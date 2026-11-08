"""CI type-checks ``src/`` a second time on requirements.lock's own pins, in the lockfile-install job (R318, option A adopted by R412).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why the step exists. The ``test`` job's mypy run type-checks what ``-e ".[analysis,dev,...]"`` resolves: the newest release of every
dependency pyproject leaves unbounded. A user who installs from ``requirements.lock`` gets its pins instead, and the typing of a library can
differ between the two. ``src/api/diagnostics/keywords.py`` had two ``arg-type`` errors on SQLAlchemy 2.0.51 (the lock) and none on the 2.1
series CI resolved, and they were found a day late on a lock install (#1576; ``audit-0.5.0/proposal-mypy-lock-profile-2026-10-27.md``).
Measured when this step was added, with mypy 2.4.1: undoing one of #1576's two lines turns ``mypy`` red on the lock's SQLAlchemy 2.0.51 and
leaves it clean on 2.1.8, the release the ``test`` job resolved that day (run 42488350732).

What this pins, in ``lockfile-install`` (the job that already installs the lock, hash-checked, in a clean environment):

* the job keeps its ``if:``: it runs on every pull request and push that is not docs-only, never only on a schedule or by hand;
* the step exists exactly once in that job;
* its commands are exactly five, each alone on its line and in this order:
  - read the mypy release pyproject's ``[dev]`` extra pins into ``pin``, as an assignment of its own (a second hard-coded pin would drift
    from the first, and an assignment that fails stops the step, where a read inside the install line would hand pip an empty name);
  - install ``"$pin"``;
  - install the lock again, ``--require-hashes --no-deps``, which puts back any pinned package mypy's own install moved;
  - ``pip check``;
  - the same mypy command as the ``test`` job's type-check step;
* the step comes after the lock and the project are installed and before any later step installs something else (the wheel step installs
  ``build``), so mypy reads the lock's set and nothing more;
* nothing makes the step pass when mypy fails: no pipe, ``||``, ``&``, ``!``, ``if`` or ``set +e`` (the workflow sets no default shell, so a
  step runs ``bash -e`` without ``pipefail``), no ``continue-on-error`` on the step or the job, no ``if:``, ``shell:`` or
  ``working-directory:`` on the step, and no ``defaults.run`` shell or directory on the job or the workflow.

This job is not one of the checks branch protection requires (the ``test`` and Core-only roll-ups are): a red run here is visible on the
pull request but does not block a merge until a repository setting makes it required.

The guard proves itself: each mutant below is the workflow with one property removed, and the checker must name it.
"""

from __future__ import annotations

import copy
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"

_JOB = "lockfile-install"
_STEP_PREFIX = "Type check against the lock's own pins"
_TEST_JOB_STEP_PREFIX = "Type check (mypy, BLOCKING)"
_JOB_IF = "github.event_name != 'schedule' && needs.changes.outputs.docs_only != 'true'"
_PIN_READ = re.compile(r"""^pin="\$\(python -c '([^']+)'\)"$""")
_PIN_INSTALL = 'python -m pip install "$pin"'
_REINSTALL = "python -m pip install --require-hashes --no-deps -r requirements.lock"
_CHECK = "python -m pip check"
_LOCK_INSTALL = "python -m pip install --require-hashes -r requirements.lock"
_PROJECT_INSTALL = "python -m pip install -e . --no-deps"
_FORBIDDEN_STEP_KEYS = ("if", "shell", "working-directory")
_FORBIDDEN_DEFAULTS = ("shell", "working-directory")


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _lines(step: dict) -> list[str]:
    return [
        line.strip()
        for line in str(step.get("run") or "").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _truthy(value: object) -> bool:
    """GitHub reads ``continue-on-error: "false"`` as false, so a string is compared by its text."""
    return str(value).strip().lower() not in ("", "none", "false")


def _dev_mypy_pin() -> str:
    dev = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["dev"]
    pins = [r for r in dev if r.startswith("mypy==")]
    assert len(pins) == 1, f"pyproject's [dev] extra must pin mypy exactly once, it has {pins}"
    return pins[0]


def _named(steps: list[dict], prefix: str) -> list[int]:
    return [i for i, s in enumerate(steps) if str(s.get("name") or "").startswith(prefix)]


def _installs(step: dict) -> bool:
    return any("pip install" in line for line in _lines(step))


def _problems(workflow: dict) -> list[str]:
    """Everything wrong with the lock-profile mypy step of the workflow, as sentences; empty when it is as pinned above."""
    jobs = workflow.get("jobs") or {}
    job = jobs.get(_JOB)
    if job is None:
        return [f"the workflow has no job named {_JOB}"]
    found: list[str] = []
    if _truthy(job.get("continue-on-error")):
        found.append(f"{_JOB}: the job must not say continue-on-error (job-level)")
    if str(job.get("if") or "").strip() != _JOB_IF:
        found.append(
            f"{_JOB}: the job's `if:` must stay {_JOB_IF!r} (it runs on every pull request that is not docs-only), it is {job.get('if')!r}"
        )
    for where, holder in (("the job", job), ("the workflow", workflow)):
        run_defaults = (holder.get("defaults") or {}).get("run") or {}
        for key in _FORBIDDEN_DEFAULTS:
            if key in run_defaults:
                found.append(
                    f"{_JOB}: {where} must not set `defaults.run.{key}` (the step relies on the default `bash -e` in the repository root)"
                )
    steps = job.get("steps") or []
    mine = _named(steps, _STEP_PREFIX)
    if len(mine) != 1:
        return [
            *found,
            f"{_JOB}: expected exactly one step named '{_STEP_PREFIX}...', found {len(mine)}",
        ]
    at = mine[0]
    step = steps[at]
    if _truthy(step.get("continue-on-error")):
        found.append(
            f"{_JOB}: the step must not say continue-on-error (a red type check must redden the job)"
        )
    for key in _FORBIDDEN_STEP_KEYS:
        if key in step:
            found.append(
                f"{_JOB}: the step must not set `{key}:` (it runs on every pull request, in the repository root, under the default shell)"
            )

    test_steps = (jobs.get("test") or {}).get("steps") or []
    theirs = _named(test_steps, _TEST_JOB_STEP_PREFIX)
    mypy_line = (
        _lines(test_steps[theirs[0]])[-1] if theirs and _lines(test_steps[theirs[0]]) else None
    )
    if mypy_line is None:
        found.append(f"test: no step named '{_TEST_JOB_STEP_PREFIX}' to take the mypy command from")

    lines = _lines(step)
    want = [
        "<pin=, the mypy pin read from pyproject>",
        _PIN_INSTALL,
        _REINSTALL,
        _CHECK,
        mypy_line or "<the test job's mypy command>",
    ]
    if len(lines) != len(want):
        found.append(
            f"{_JOB}: the step must run exactly five commands ({', '.join(want)}), it runs {len(lines)}: {lines}"
        )
    else:
        m = _PIN_READ.match(lines[0])
        if not m:
            found.append(
                f"{_JOB}: the first command must assign the mypy pin read from pyproject to `pin`, alone on its line; it is {lines[0]!r}"
            )
        else:
            got = subprocess.run(
                [sys.executable, "-c", m.group(1)],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if got.returncode != 0 or got.stdout.strip() != _dev_mypy_pin():
                found.append(
                    f"{_JOB}: the first command's python must print pyproject's [dev] mypy pin {_dev_mypy_pin()!r}, "
                    f"it printed {got.stdout.strip()!r} (exit {got.returncode})"
                )
        for i, (line, expected) in enumerate(zip(lines[1:], want[1:], strict=True), start=2):
            if mypy_line is not None and line != expected:
                found.append(f"{_JOB}: command {i} must be {expected!r}, it is {line!r}")
    if any(re.search(r"mypy==\d", line) for line in lines):
        found.append(
            f"{_JOB}: the step must not name a mypy release itself (it reads pyproject's [dev] pin, so the two cannot drift)"
        )

    before = [str(s.get("run") or "") for s in steps[:at]]
    if not any(_LOCK_INSTALL in run for run in before):
        found.append(f"{_JOB}: the step must come after the lock is installed ({_LOCK_INSTALL!r})")
    if not any(_PROJECT_INSTALL in run for run in before):
        found.append(
            f"{_JOB}: the step must come after the project is installed ({_PROJECT_INSTALL!r})"
        )
    installs_before = [
        str(s.get("name") or "?")
        for s in steps[:at]
        if _installs(s)
        and not any(x in str(s.get("run")) for x in (_LOCK_INSTALL, _PROJECT_INSTALL))
    ]
    if installs_before:
        found.append(
            f"{_JOB}: no step before this one may install anything but the lock and the project; {installs_before} does"
        )
    return found


def test_the_lockfile_job_type_checks_src_on_the_lock_pins():
    assert _problems(_workflow()) == []


def test_a_string_false_is_not_an_error_flag():
    wf = _workflow()
    steps = wf["jobs"][_JOB]["steps"]
    steps[_named(steps, _STEP_PREFIX)[0]]["continue-on-error"] = "false"
    assert _problems(wf) == []


# --- the guard proves itself: one property removed per mutant, and the checker names it ---------------------------------------------------------


def _mutants() -> dict[str, tuple[dict, str]]:
    """label -> (the workflow with one property removed, the sentence the checker must say about it)."""
    base = _workflow()
    out: dict[str, tuple[dict, str]] = {}

    def mutated(edit, says: str) -> tuple[dict, str]:
        wf = copy.deepcopy(base)
        steps = wf["jobs"][_JOB]["steps"]
        at = _named(steps, _STEP_PREFIX)[0]
        edit(wf, steps, at)
        return wf, says

    def rewrite(old: str, new: str):
        def edit(wf, steps, at):
            text = str(steps[at]["run"])
            assert old in text, f"the mutant's anchor {old!r} is not in the step"
            steps[at]["run"] = text.replace(old, new)

        return edit

    def set_key(key: str, value):
        return lambda wf, steps, at: steps[at].__setitem__(key, value)

    def move_after_wheel(wf, steps, at):
        step = steps.pop(at)
        steps.insert(_named(steps, "Wheel carries")[0] + 1, step)

    mypy = "python -m mypy src/"
    out["the step is removed"] = mutated(lambda wf, steps, at: steps.pop(at), "found 0")
    out["the step is in another job"] = mutated(
        lambda wf, steps, at: wf["jobs"]["core-only"]["steps"].append(steps.pop(at)), "found 0"
    )
    out["the step is duplicated"] = mutated(
        lambda wf, steps, at: steps.append(copy.deepcopy(steps[at])), "found 2"
    )
    out["a hard-coded mypy release"] = mutated(
        lambda wf, steps, at: steps[at].__setitem__(
            "run", "\n".join(["python -m pip install mypy==2.4.1", *_lines(steps[at])[2:]])
        ),
        "must not name a mypy release itself",
    )
    out["the read prints a hard-coded release"] = mutated(
        lambda wf, steps, at: steps[at].__setitem__(
            "run",
            "\n".join(
                [f"""pin="$(python -c 'print("{_dev_mypy_pin()}")')\"""", *_lines(steps[at])[1:]]
            ),
        ),
        "must not name a mypy release itself",
    )
    out["the read's failure is swallowed (|| true)"] = mutated(
        lambda wf, steps, at: steps[at].__setitem__(
            "run", "\n".join([_lines(steps[at])[0] + " || true", *_lines(steps[at])[1:]])
        ),
        "the first command must assign the mypy pin",
    )
    out["the read is folded into the install line"] = mutated(
        lambda wf, steps, at: steps[at].__setitem__(
            "run",
            "\n".join(
                [
                    "python -m pip install " + _lines(steps[at])[0].removeprefix("pin="),
                    *_lines(steps[at])[2:],
                ]
            ),
        ),
        "exactly five commands",
    )
    out["something else is installed beside the pin"] = mutated(
        rewrite(_PIN_INSTALL, _PIN_INSTALL + " types-requests"), "command 2 must be"
    )
    out["the pin is read from another extra"] = mutated(
        rewrite('["dev"]', '["analysis"]'), "must print pyproject's [dev] mypy pin"
    )
    out["the lock is not put back"] = mutated(
        rewrite(_REINSTALL + "\n", ""), "exactly five commands"
    )
    out["the lock is put back with its deps re-resolved"] = mutated(
        rewrite(_REINSTALL, _REINSTALL.replace(" --no-deps", "")), "command 3 must be"
    )
    out["pip check is dropped"] = mutated(rewrite(_CHECK + "\n", ""), "exactly five commands")
    out["mypy checks less than the test job"] = mutated(
        rewrite(mypy, "python -m mypy src/api/"), "command 5 must be"
    )
    out["mypy's failure is swallowed (|| true)"] = mutated(
        rewrite(mypy, mypy + " || true"), "command 5 must be"
    )
    out["mypy is piped to tail"] = mutated(
        rewrite(mypy, mypy + " | tail -n 20"), "command 5 must be"
    )
    out["errexit is turned off"] = mutated(
        rewrite(_CHECK, "set +e\n" + _CHECK), "exactly five commands"
    )
    out["the step runs after the wheel step installs build"] = mutated(
        move_after_wheel, "may install anything but"
    )
    out["the step runs before the lock is installed"] = mutated(
        lambda wf, steps, at: steps.insert(1, steps.pop(at)), "after the lock is installed"
    )
    out["the project is never installed"] = mutated(
        lambda wf, steps, at: steps.pop(
            next(i for i, s in enumerate(steps) if _PROJECT_INSTALL in str(s.get("run")))
        ),
        "after the project is installed",
    )
    out["something else is installed before it"] = mutated(
        lambda wf, steps, at: steps.insert(
            at, {"name": "Install a tool", "run": "python -m pip install build"}
        ),
        "may install anything but",
    )
    out["continue-on-error: true on the step"] = mutated(
        set_key("continue-on-error", True), "must not say continue-on-error (a red type check"
    )
    out["continue-on-error: 'true' as a string"] = mutated(
        set_key("continue-on-error", "true"), "must not say continue-on-error (a red type check"
    )
    out["the step only runs on tags"] = mutated(
        set_key("if", "startsWith(github.ref, 'refs/tags/v')"), "must not set `if:`"
    )
    out["the step sets a shell"] = mutated(set_key("shell", "bash {0}"), "must not set `shell:`")
    out["the step runs in another directory"] = mutated(
        set_key("working-directory", "docs"), "must not set `working-directory:`"
    )
    out["continue-on-error: true on the job"] = mutated(
        lambda wf, steps, at: wf["jobs"][_JOB].__setitem__("continue-on-error", True),
        "must not say continue-on-error (job-level)",
    )
    out["the job only runs by hand"] = mutated(
        lambda wf, steps, at: wf["jobs"][_JOB].__setitem__(
            "if", "github.event_name == 'workflow_dispatch'"
        ),
        "the job's `if:` must stay",
    )
    out["the job sets a default shell"] = mutated(
        lambda wf, steps, at: wf["jobs"][_JOB].__setitem__(
            "defaults", {"run": {"shell": "bash {0}"}}
        ),
        "the job must not set `defaults.run.shell`",
    )
    out["the workflow sets a default shell"] = mutated(
        lambda wf, steps, at: wf.__setitem__("defaults", {"run": {"shell": "bash {0}"}}),
        "the workflow must not set `defaults.run.shell`",
    )
    out["the job runs in another directory by default"] = mutated(
        lambda wf, steps, at: wf["jobs"][_JOB].__setitem__(
            "defaults", {"run": {"working-directory": "docs"}}
        ),
        "the job must not set `defaults.run.working-directory`",
    )
    out["the job is renamed"] = mutated(
        lambda wf, steps, at: wf["jobs"].__setitem__("lockfile-renamed", wf["jobs"].pop(_JOB)),
        f"has no job named {_JOB}",
    )
    return out


def test_every_mutant_of_the_step_is_named_by_the_checker():
    for label, (workflow, says) in _mutants().items():
        found = _problems(workflow)
        assert found, f"{label}: the checker found nothing wrong"
        assert any(says in problem for problem in found), (
            f"{label}: expected a problem saying {says!r}, got {found}"
        )
