"""A Linux CI runner has every tool that tests skip without, and no test starts skipping on a tool nobody has named.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. 54 test files skip when ``node`` is missing (measured 2026-10-31 by running them with no node on PATH: 99 tests skip, 590 pass, and
one, ``test_release_run_panel_node_suite``, fails because it calls node without a probe), five more files skip on ``bash``, three on ``git``, one on
``unzip``, one on a C compiler. ``ci.yml`` installs none of them: they come with the ``ubuntu-latest`` image, and nothing in the repository says so,
pins them or asserts them. If the image dropped one, those tests would turn into GREEN skips and the job would say nothing (the skip summary of the
``test`` and ``core-only`` jobs, 353 and 419 skips in 44 and 73 modules, shows the node-gated files are not among them, so today they run). The
repository already answered this for PowerShell: ``test_installer_windows.py`` asserts the tool when ``CI`` is set and skips on a developer machine. This
is the same shape for the rest.

What this pins:

* on a Linux machine with ``CI`` set, every tool in ``_REQUIRED`` and at least one C compiler is on ``PATH``; a missing one is a red test that
  names the tool and what skips without it. On a developer machine, and on the macOS and Windows legs of the observation lane, it skips: the blocking
  jobs are the Linux ones, and a leg that never turns a PR red is not where a runner image is pinned;
* the lists are COMPLETE in both directions: a test that starts probing a tool this file has not named fails (add it to ``_REQUIRED``, or to
  ``_EXEMPT`` with the reason), and a name here that no test probes any more fails, so the lists can only be as long as the truth;
* the guard proves itself: the same test, run in a process whose ``PATH`` lacks ``node``, is red and names it, and green when a ``node`` is there.

What it does not see: a gate on something other than ``shutil.which("literal")`` (``find_spec``, ``os.environ``, a platform check), a tool named
through a variable, or a tool that is on ``PATH`` but too old.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TESTS = Path(__file__).resolve().parent

#: Tools whose absence turns tests into skips, each provided by the runner image (``ci.yml`` has no setup or install step for any of them).
_REQUIRED = ("node", "bash", "git", "unzip")
#: ``test_malloc_arena_default.py`` builds a stand-in library with whichever of these it finds and skips where there is none.
_C_COMPILERS = ("cc", "gcc", "clang")
#: Probed by tests, covered by another test that asserts them on a runner.
_ELSEWHERE = {
    "pwsh": "tests/test_installer_windows.py asserts pwsh or powershell when CI is set, the same shape as this file (on Linux that means pwsh)",
    "powershell": "tests/test_installer_windows.py asserts pwsh or powershell when CI is set; Windows has it, Linux does not, and the observation lane is not a pin",
}
#: Probed by tests, deliberately not required of a runner, each with why.
_EXEMPT = {
    "original-awk": (
        "the ``test`` job installs it with its own apt step, whose ``command -v original-awk`` makes a failed install a red job; ``core-only`` does not "
        "install it and the test that names it skips there by design"
    ),
    "flock": "tests/test_launcher_records_race.py asserts flock is ABSENT from a filtered PATH to test the launcher's no-flock path; it is not a skip gate",
}


def _on_a_linux_ci_runner() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"1", "true"} and sys.platform.startswith("linux")


def probed_tools(source: str) -> set[str]:
    """The tool names this test source hands to ``which`` as a string literal (``shutil.which("node")``, ``which("git", path=...)``)."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            fn = node.func
            if (fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")) == "which" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.add(first.value)
    return found


def missing_on_runner(which=shutil.which) -> list[str]:
    """What a runner lacks, one sentence per tool. ``which`` is a parameter so the self-proof can hide a tool without touching the machine."""
    out = [f"{tool}: tests that skip without it would all turn green by skipping" for tool in _REQUIRED if not which(tool)]
    if not any(which(cc) for cc in _C_COMPILERS):
        out.append(f"a C compiler ({', '.join(_C_COMPILERS)}): the malloc-arena stand-in library test would skip")
    return out


def known_tools() -> set[str]:
    return {*_REQUIRED, *_C_COMPILERS, *_ELSEWHERE, *_EXEMPT}


def without_reason(*tables: dict[str, str]) -> list[str]:
    """The names in these tables whose reason is empty: every exemption says why it is one."""
    return sorted(name for table in tables for name, why in table.items() if not why.strip())


def _all_probed() -> set[str]:
    found: set[str] = set()
    for path in sorted(_TESTS.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "which(" in text:  # parse only what can contain a probe: a fixture of deliberately invalid Python elsewhere must not turn this red
            found |= probed_tools(text)
    return found


@pytest.mark.parametrize("tool", [*_REQUIRED, "c-compiler"])
def test_a_linux_ci_runner_has_the_tool_that_tests_skip_without(tool):
    if not _on_a_linux_ci_runner():
        pytest.skip("not a Linux CI runner: a missing tool is the right reason to skip on a developer machine")
    problems = [p for p in missing_on_runner() if p.startswith("a C compiler" if tool == "c-compiler" else f"{tool}:")]
    assert not problems, problems


def test_the_tool_lists_name_exactly_the_tools_the_tests_probe():
    probed = _all_probed()
    unknown = sorted(probed - known_tools())
    assert not unknown, (
        f"{unknown}: a test now skips (or branches) on a tool this file does not name. If the runner image provides it, add it to _REQUIRED so a runner that "
        "loses it is red; if it is not a runner tool, add it to _EXEMPT with the reason."
    )
    stale = sorted(known_tools() - probed)
    assert not stale, f"{stale}: no test probes these any more; delete them from the lists so the lists stay true"
    assert set(_REQUIRED).isdisjoint(_EXEMPT) and set(_REQUIRED).isdisjoint(_ELSEWHERE)
    assert without_reason(_EXEMPT, _ELSEWHERE) == [], "every exemption carries its reason"


# --- the guard proves itself ---------------------------------------------------------------------------------------------------------------------


def test_the_runner_gate_needs_ci_set_and_linux(monkeypatch):
    """The gate itself: a developer machine (no ``CI``) and a non-Linux leg skip; only both together ask."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("CI", raising=False)
    assert _on_a_linux_ci_runner() is False
    for value, expected in (("true", True), ("TRUE", True), ("1", True), (" true ", True), ("false", False), ("0", False), ("", False)):
        monkeypatch.setenv("CI", value)
        assert _on_a_linux_ci_runner() is expected, value
    monkeypatch.setenv("CI", "true")
    for platform in ("darwin", "win32"):
        monkeypatch.setattr(sys, "platform", platform)
        assert _on_a_linux_ci_runner() is False, platform


def test_the_scan_reads_which_calls_with_a_literal_and_nothing_else():
    src = (
        "import shutil\nfrom shutil import which\n"
        "a = shutil.which('node')\nb = which('git', path='/x')\nc = shutil.which(name)\nd = shutil.which(f'{x}')\ne = other.find('zip')\nf = which(err)\n"
    )
    assert probed_tools(src) == {"node", "git"}
    assert probed_tools("def which(x): return x\n") == set()


def test_a_new_tool_is_named_by_the_completeness_check(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "_all_probed", lambda: {*known_tools(), "newtool"})
    with pytest.raises(AssertionError, match="newtool"):
        test_the_tool_lists_name_exactly_the_tools_the_tests_probe()


def test_an_exemption_without_a_reason_is_named():
    assert without_reason({"a": "because", "b": ""}, {"c": "  "}) == ["b", "c"]
    assert without_reason({"a": "because"}) == []


def test_a_tool_no_test_probes_any_more_is_named_too(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "_all_probed", lambda: known_tools() - {"unzip"})
    with pytest.raises(AssertionError, match="unzip"):
        test_the_tool_lists_name_exactly_the_tools_the_tests_probe()


@pytest.mark.parametrize("tool", _REQUIRED)
def test_a_runner_without_a_tool_is_named_for_it(tool):
    everything = lambda name: f"/usr/bin/{name}"  # noqa: E731 - a which() that finds every tool
    assert missing_on_runner(everything) == []
    problems = missing_on_runner(lambda name: None if name == tool else everything(name))
    assert [p.split(":")[0] for p in problems] == [tool]


def test_a_runner_with_no_c_compiler_at_all_is_named_and_one_compiler_is_enough():
    only_gcc = lambda name: "/usr/bin/gcc" if name in ("gcc", *_REQUIRED) else None  # noqa: E731
    assert missing_on_runner(only_gcc) == []
    no_cc = lambda name: None if name in _C_COMPILERS else "/usr/bin/" + name  # noqa: E731
    assert [p.split(" (")[0] for p in missing_on_runner(no_cc)] == ["a C compiler"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the live check only asks on Linux")
def test_the_live_check_is_red_in_a_process_that_lacks_node_and_green_when_it_is_there(tmp_path):
    """The mutant, end to end: run this very test as CI would, once with no ``node`` on PATH and once with one."""
    target = f"{Path(__file__).as_posix()}::test_a_linux_ci_runner_has_the_tool_that_tests_skip_without[node]"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PATH")}
    env["CI"] = "true"
    env["OO_DATA_DIR"] = str(tmp_path / "data")  # the child's conftest must not bind to the parent's data folder

    def run(path: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
            cwd=_ROOT, capture_output=True, text=True, check=False, timeout=120, env={**env, "PATH": path},
        )

    empty = tmp_path / "empty"
    empty.mkdir()
    red = run(str(empty))
    assert red.returncode == 1 and "node: tests that skip without it" in red.stdout, red.stdout + red.stderr
    with_node = tmp_path / "with_node"
    with_node.mkdir()
    fake = with_node / "node"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    if not os.access(fake, os.X_OK):
        pytest.skip("this temporary directory is mounted noexec, so no fake node can be found on PATH")
    green = run(str(with_node))
    assert green.returncode == 0 and "1 passed" in green.stdout, green.stdout + green.stderr
