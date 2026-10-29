"""Every test that skips for a missing optional package is run, for real, by at least one blocking CI job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. A test that starts with ``pytest.importorskip("duckdb")`` (or a ``skipif(not columnar.duckdb_available())``) is green in
every job that does not install the package, and it is green BY SKIPPING. The ``columnar`` job installs ``[columnar]`` but runs a named
list of nine files, and the rollup work since then added nineteen more gated files that nobody named there (the step names them since
R392): measured on 2026-10-28 by making ``duckdb`` unimportable and running them (230 tests collected with duckdb; 29 pass without it and
201 never run, reported as 151 skips because three files skip once at module level), they skip in ``test``, ``core-only`` and the portability lane alike, and
install [columnar] in none of them. Those 201 tests had never run in CI. One of them, once run, was red (``test_top_terms_pre_aggregate``
read DuckDB 1.x's profile JSON and DuckDB 2.0.0, which pip resolves today, writes another).

What this pins. It reads ``.github/workflows/ci.yml`` and ``pyproject.toml`` and, for every test file that gates on a package that core does
not install, requires a blocking job that BOTH installs the package (an extra, or a ``pip install NAME==`` pin) AND either runs the whole
suite (a bare ``pytest -q``) or names the file, ALL of a file's packages in the same command. What does not count: a job with a literal
``continue-on-error: true``, one whose matrix legs all say ``observe: true``, one with a condition other than ``!= 'schedule'``, a pytest
step with its own ``if:`` or ``continue-on-error``, a comment or echo that merely contains ``-m pytest``, a command that selects tests
(``-k``, ``-m``, ``--deselect``, ``--ignore``), a package installed after the pytest step or uninstalled before it.
The gap that exists today is written down below as ``KNOWN_UNCOVERED`` and compared in BOTH directions with zero slack: a new gated file
that no job runs fails, and so does a file that a job started running while still listed here, so the list can only shrink.

What it does not see. A gate it has no name for (a bare ``try: import x`` at module top, ``find_spec``, a ``skipif`` on something other
than ``importorskip`` or ``duckdb_available``); a package whose import name differs from its distribution name and is missing from
``_IMPORT_NAME``; an ``if:`` it cannot read (any step or job condition other than the one it knows counts as "does not run", which errs
red); and the DuckDB version the job resolves (``duckdb>=1.4`` has no ceiling, so no lane runs the 1.x profile reader today).

The guard proves itself: the pinned cases below run the checker on small synthetic workflows, and the live mutants remove one property from
the real ``ci.yml`` (a file from the columnar list; the ``columnar`` extra) and require the checker to name what that opened.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_PYPROJECT = _ROOT / "pyproject.toml"
_TESTS = _ROOT / "tests"

#: A distribution whose import name is not its lower-cased name. Everything else is compared by its lower-cased distribution name.
_IMPORT_NAME = {
    "beautifulsoup4": "bs4",
    "pillow": "pil",
    "pyyaml": "yaml",
    "scikit-learn": "sklearn",
    "python-dateutil": "dateutil",
    "python-multipart": "multipart",
    "pysocks": "socks",
    "pyosmium": "osmium",
    "pypdfium2": "pypdfium2",
}

#: A name that gates a test on a package without an ``importorskip`` of it.
_GATE_NAMES = {"duckdb_available": "duckdb"}

#: Files that mention a gate name without skipping on it, each with why.
_NOT_A_SKIP = {
    "tests/test_get_routes_side_effects.py": (
        "reads duckdb_available() to decide what a route walk may allow (a columnar install is MORE permissive); it skips on neither outcome"
    ),
}

#: The gap, measured 2026-10-28: file -> the package(s) it skips on. What is left is the two playwright files; the nineteen duckdb ones were named
#: in the ``columnar`` job's first pytest step (R392) and their lines deleted, as docs/ledger/lessons.d/2026-10-28-tests-no-ci-job-runs.md asked.
#: Delete a line when a job starts running the file; the test below fails until you do.
KNOWN_UNCOVERED = {
    # [uiwalk] (playwright) needs a Chromium download as well; no job installs either, the UI click-through runs by hand per release
    "tests/test_analytics45_generate.py": "playwright",
    "tests/test_ui_walk_playwright.py": "playwright",
}

_EXTRA_RE = re.compile(r'-e\s+["\']?\.\[([^\]]*)\]')
_PIN_RE = re.compile(r"(?:^|\s)([A-Za-z0-9][A-Za-z0-9._-]*)==[0-9]")
_TEST_FILE_RE = re.compile(r"\btests/[A-Za-z0-9_./-]+\.py\b")
_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _import_name(dist: str) -> str:
    dist = dist.strip().lower().replace("_", "-")
    return _IMPORT_NAME.get(dist, dist)


@dataclass
class Run:
    """One pytest command, with what its job had installed by the time it ran."""

    job: str
    packages: set[str] = field(default_factory=set)
    extras: set[str] = field(default_factory=set)
    bare: bool = False
    files: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)


#: The one job-level condition that still means "on every push and pull request": the schedule-only audit is the job it leaves out.
_EVERY_PUSH = "github.event_name != 'schedule'"
_PYTEST_LINE = re.compile(r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:python3?\s+-m\s+pytest|pytest)\b")
#: An option that selects or removes tests: a command carrying one is neither "the whole suite" nor a run of the files it names.
_SELECTING = re.compile(r"(?:^|\s)(?:-k|-m|--deselect|--ignore|--ignore-glob|--lf|--ff|--co|--collect-only)(?:[=\s]|$)")


def _pytest_commands(script: str) -> list[str]:
    """The logical command lines of a ``run`` script that START a pytest, backslash continuations joined; comments and echoes are not commands."""
    text = re.sub(r"\\\n", " ", script)
    return [line for line in text.splitlines() if _PYTEST_LINE.match(line)]


def _every_leg_observes(job: dict) -> bool:
    """A matrix whose every ``include`` leg sets ``observe: true`` blocks nothing, whatever ``continue-on-error`` is an expression of."""
    legs = ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []
    return bool(legs) and all(isinstance(leg, dict) and leg.get("observe") is True for leg in legs)


def read_runs(workflow: str) -> list[Run]:
    """The pytest commands of blocking jobs that run on every push, in step order, each with the installs made before it."""
    doc = yaml.safe_load(workflow)
    out = []
    for name, job in (doc.get("jobs") or {}).items():
        cond = job.get("if")
        if job.get("continue-on-error") is True or (cond is not None and str(cond).strip() != _EVERY_PUSH):
            continue
        if isinstance(job.get("continue-on-error"), str) and _every_leg_observes(job):
            continue
        packages: set[str] = set()
        extras: set[str] = set()
        removed: set[str] = set()
        for step in job.get("steps") or []:
            run = step.get("run")
            if not isinstance(run, str):
                continue
            for line in re.sub(r"\\\n", " ", run).splitlines():
                if line.lstrip().startswith("#"):
                    continue
                for part in re.split(r"&&|;|\|\|", line):  # in order: an install and an uninstall on one line
                    if "pip uninstall" in part:
                        removed |= {_import_name(w) for w in part.split() if re.match(r"[A-Za-z]", w) and w not in ("python", "pip", "uninstall", "-m")}
                    if "pip install" in part:
                        for group in _EXTRA_RE.findall(part):
                            extras.update(e.strip() for e in group.split(",") if e.strip())
                        for pin in _PIN_RE.findall(part):
                            packages.add(_import_name(pin))
                            removed.discard(_import_name(pin))
            if step.get("if") is not None or step.get("continue-on-error") is True:
                continue  # a conditional or advisory step is not a run on every push that can hold anything up
            for cmd in _pytest_commands(run):
                if _SELECTING.search(_PYTEST_LINE.sub("", cmd, count=1)):
                    continue
                named = set(_TEST_FILE_RE.findall(cmd))
                if named or re.search(r"\btests/", cmd):
                    out.append(Run(name, set(packages), set(extras), False, named, set(removed)))
                else:
                    out.append(Run(name, set(packages), set(extras), True, set(), set(removed)))
    return out


def read_homes(pyproject: str) -> tuple[set[str], dict[str, set[str]]]:
    """(import names core installs, import name -> the extras that carry it)."""
    data = tomllib.loads(pyproject)["project"]
    core = {_import_name(m.group(1)) for r in data.get("dependencies", []) if (m := _REQ_NAME_RE.match(r))}
    extras: dict[str, set[str]] = {}
    for extra, reqs in (data.get("optional-dependencies") or {}).items():
        for r in reqs:
            if m := _REQ_NAME_RE.match(r):
                extras.setdefault(_import_name(m.group(1)), set()).add(extra)
    return core, extras


def gated_packages(source: str) -> set[str]:
    """The top-level package names this test source skips on."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if fname == "importorskip" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found.add(node.args[0].value.split(".")[0].lower())
        name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else ""
        if name in _GATE_NAMES:
            found.add(_GATE_NAMES[name])
    return found


def uncovered(runs: list[Run], core: set[str], extras: dict[str, set[str]], gated: dict[str, set[str]]) -> dict[str, str]:
    """file -> the packages it skips on (joined with ``+``), for each gated file no ONE run installs all of and runs.

    One run has to satisfy every package at once: a file gated on two packages skips if either is missing, so two jobs that each have one
    of them do not run it.
    """
    stdlib = {m.lower() for m in sys.stdlib_module_names}
    out = {}
    for path, pkgs in sorted(gated.items()):
        need = sorted(p for p in pkgs if p not in core and p not in stdlib and p not in ("src", "tests"))
        if not need:
            continue

        def has(r: Run, pkg: str) -> bool:
            return pkg not in r.removed and (pkg in r.packages or bool(extras.get(pkg, set()) & r.extras))

        if not any(all(has(r, p) for p in need) and (r.bare or path in r.files) for r in runs):
            out[path] = "+".join(need)
    return out


def _gated_tests() -> dict[str, set[str]]:
    gated = {}
    for path in sorted({*_TESTS.rglob("test_*.py"), *_TESTS.rglob("*_test.py")}):
        rel = path.relative_to(_ROOT).as_posix()
        pkgs = gated_packages(path.read_text(encoding="utf-8"))
        if rel in _NOT_A_SKIP:
            pkgs.discard("duckdb")
        if pkgs:
            gated[rel] = pkgs
    return gated


def _live() -> dict[str, str]:
    core, extras = read_homes(_PYPROJECT.read_text(encoding="utf-8"))
    return uncovered(read_runs(_CI.read_text(encoding="utf-8")), core, extras, _gated_tests())


def test_every_gated_test_file_is_run_by_a_blocking_job_or_is_listed():
    live = _live()
    new = {f: p for f, p in live.items() if f not in KNOWN_UNCOVERED}
    assert not new, (
        f"{sorted(new.items())}: these files skip when the package is missing and no blocking CI job both installs it and runs the file; "
        "name them in the job that installs the package (tests/ list in .github/workflows/ci.yml) or, for a package no job installs, say so in KNOWN_UNCOVERED"
    )
    fixed = sorted(f for f in KNOWN_UNCOVERED if f not in live)
    assert not fixed, f"{fixed} are run by a CI job now: delete them from KNOWN_UNCOVERED, so the list can only shrink"
    assert live == {f: p for f, p in KNOWN_UNCOVERED.items() if f in live}, "a listed file now skips on a different package"


def test_the_not_a_skip_list_names_files_that_still_mention_the_gate():
    for rel, why in _NOT_A_SKIP.items():
        assert why
        assert "duckdb" in gated_packages((_ROOT / rel).read_text(encoding="utf-8")), f"{rel} no longer mentions a gate: delete its entry"


# --- the checker on synthetic workflows -------------------------------------------------------------------------------------------------

_PYPROJECT_TEXT = """
[project]
name = "x"
dependencies = ["requests>=2", "beautifulsoup4>=4"]
[project.optional-dependencies]
columnar = ["duckdb>=1.4"]
uiwalk = ["playwright>=1.45"]
socks = ["PySocks>=1.7"]
"""


def _wf(*jobs: str) -> str:
    return "jobs:\n" + "".join(jobs)


def _job(name: str, install: str, test: str, extra: str = "", step: str = "", after: str = "") -> str:
    """``extra`` is job-level text, ``step`` the options of the pytest step, ``after`` a run step placed after it."""
    body = "\n".join("          " + ln for ln in test.splitlines())
    tail = f"      - run: {after}\n" if after else ""
    return f"  {name}:\n{extra}    steps:\n      - run: {install}\n      - run: |\n{body}\n{step}{tail}"


def _check(workflow: str, sources: dict[str, str]) -> dict[str, str]:
    core, extras = read_homes(_PYPROJECT_TEXT)
    gated = {p: g for p, s in sources.items() if (g := gated_packages(s))}
    return uncovered(read_runs(workflow), core, extras, gated)


_DUCK = 'import pytest\npytest.importorskip("duckdb")\n'


@pytest.mark.parametrize(
    "workflow, sources, want",
    [
        # a job that installs the extra and names the file covers it
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q tests/test_a.py")),
            {"tests/test_a.py": _DUCK},
            {},
        ),
        # ... and does not cover a file it does not name
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q tests/test_a.py")),
            {"tests/test_a.py": _DUCK, "tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # a bare pytest covers everything the job installs for
        (
            _wf(_job("t", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q")),
            {"tests/test_b.py": _DUCK},
            {},
        ),
        # a bare pytest in a job that does NOT install the extra covers nothing
        (
            _wf(_job("t", 'python -m pip install -e ".[dev]"', "python -m pytest -q")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # an observation lane (literal continue-on-error: true) does not count
        (
            _wf(_job("o", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q", extra="    continue-on-error: true\n")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # an expression for continue-on-error is not a literal and still counts
        (
            _wf(_job("o", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q", extra="    continue-on-error: ${{ matrix.observe }}\n")),
            {"tests/test_b.py": _DUCK},
            {},
        ),
        # a pip pin installs a package no extra names for this job
        (
            _wf(_job("t", 'python -m pip install -e ".[dev]" && python -m pip install PySocks==1.7.1', "python -m pytest -q")),
            {"tests/test_s.py": 'import pytest\npytest.importorskip("socks")\n'},
            {},
        ),
        # no pin and no extra: nothing installs it
        (
            _wf(_job("t", 'python -m pip install -e ".[dev]"', "python -m pytest -q")),
            {"tests/test_s.py": 'import pytest\npytest.importorskip("socks")\n'},
            {"tests/test_s.py": "socks"},
        ),
        # core packages, the standard library and the project's own modules are never a gap
        (
            _wf(_job("t", 'python -m pip install -e ".[dev]"', "python -m pytest -q tests/x.py")),
            {"tests/test_c.py": 'import pytest\npytest.importorskip("bs4")\npytest.importorskip("fcntl")\npytest.importorskip("src.api.main")\n'},
            {},
        ),
        # a dotted name is its top-level package
        (
            _wf(_job("t", 'python -m pip install -e ".[dev]"', "python -m pytest -q")),
            {"tests/test_d.py": 'import pytest\npytest.importorskip("playwright.sync_api")\n'},
            {"tests/test_d.py": "playwright"},
        ),
        # the duckdb_available() gate counts, in a skipif or an explicit skip
        (
            _wf(_job("t", 'python -m pip install -e ".[dev]"', "python -m pytest -q")),
            {
                "tests/test_e.py": "import pytest\npytestmark = pytest.mark.skipif(not columnar.duckdb_available(), reason='x')\n",
                "tests/test_f.py": "def test_x():\n    if not columnar.duckdb_available():\n        pytest.skip('x')\n",
            },
            {"tests/test_e.py": "duckdb", "tests/test_f.py": "duckdb"},
        ),
        # a file list continued over backslash lines is read whole
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q \\\n  tests/test_a.py \\\n  tests/test_b.py")),
            {"tests/test_b.py": _DUCK},
            {},
        ),
        # a pytest step that is advisory or conditional runs nothing that can hold a push up
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q tests/test_b.py", step="        continue-on-error: true\n")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q tests/test_b.py", step="        if: github.event_name == 'pull_request'\n")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # a job limited to the schedule runs nothing per push; the one condition that means "every push" still counts
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q", extra="    if: github.event_name == 'schedule'\n")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q", extra="    if: github.event_name != 'schedule'\n")),
            {"tests/test_b.py": _DUCK},
            {},
        ),
        # a comment or an echo containing "-m pytest" is not a pytest command: it must not turn the job into the whole suite
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "# the files below run with python -m pytest in the next step\necho python -m pytest\npython -m pytest -q tests/test_a.py")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # a command that selects tests is neither the whole suite nor a run of the files it names
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q -k something")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q tests/test_a.py --deselect tests/test_b.py::t")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q --ignore=tests/test_b.py")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # a file gated on two packages needs ONE command that has both: duckdb in one job and playwright in another is a skip in each
        (
            _wf(
                _job("c", 'python -m pip install -e ".[dev,columnar]"', "python -m pytest -q tests/test_b.py"),
                _job("u", 'python -m pip install -e ".[dev,uiwalk]"', "python -m pytest -q tests/test_b.py"),
            ),
            {"tests/test_b.py": 'import pytest\npytest.importorskip("duckdb")\npytest.importorskip("playwright")\n'},
            {"tests/test_b.py": "duckdb+playwright"},
        ),
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar,uiwalk]"', "python -m pytest -q tests/test_b.py")),
            {"tests/test_b.py": 'import pytest\npytest.importorskip("duckdb")\npytest.importorskip("playwright")\n'},
            {},
        ),
        # an install that comes after the pytest step is not in the environment the tests ran in
        (
            _wf(_job("c", 'python -m pip install -e ".[dev]"', "python -m pytest -q tests/test_b.py", after='python -m pip install -e ".[columnar]"')),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # a matrix whose every leg is an observation leg blocks nothing; one blocking leg is enough
        (
            _wf(
                _job(
                    "m",
                    'python -m pip install -e ".[dev,columnar]"',
                    "python -m pytest -q",
                    extra="    strategy:\n      matrix:\n        include:\n          - {engine: a, observe: true}\n          - {engine: b, observe: true}\n    continue-on-error: ${{ matrix.observe }}\n",
                )
            ),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # an uninstall before the pytest step takes the package out again
        (
            _wf(_job("c", 'python -m pip install -e ".[dev,columnar]" && python -m pip uninstall -y duckdb', "python -m pytest -q tests/test_b.py")),
            {"tests/test_b.py": _DUCK},
            {"tests/test_b.py": "duckdb"},
        ),
        # an importorskip that is not a string literal is not read (the stated limit)
        (
            _wf(_job("t", 'python -m pip install -e ".[dev]"', "python -m pytest -q")),
            {"tests/test_g.py": "import pytest\nm = 'duckdb'\npytest.importorskip(m)\n"},
            {},
        ),
    ],
)
def test_the_checker_on_synthetic_workflows(workflow, sources, want):
    assert _check(workflow, sources) == want


def test_the_mutants_of_the_real_workflow_open_the_gap_the_checker_names():
    """Remove one property from the real ci.yml and the checker must name what that opened (the first and third: and nothing else)."""
    text = _CI.read_text(encoding="utf-8")
    base = _live()

    # 1. take a file that the columnar job names out of its list
    victim = "tests/test_rollup_serve_persisted.py"
    assert text.count(victim) == 1, "the mutant's anchor moved: update this test"
    assert victim not in base, "the file is gated and listed: it must be covered"
    mutated = text.replace(victim, "")
    core, extras = read_homes(_PYPROJECT.read_text(encoding="utf-8"))
    after = uncovered(read_runs(mutated), core, extras, _gated_tests())
    assert set(after) - set(base) == {victim}, after

    # 2. drop the columnar extra from the job that installs it: every file that job covered is open
    needle = 'python -m pip install -e ".[analysis,dev,columnar]"'
    assert text.count(needle) == 1, "the mutant's anchor moved: update this test"
    after = uncovered(read_runs(text.replace(needle, 'python -m pip install -e ".[analysis,dev]"')), core, extras, _gated_tests())
    opened = set(after) - set(base)
    assert victim in opened and "tests/test_columnar_engine.py" in opened, sorted(opened)

    # 3. a gated file nobody names, as a developer adds one
    gated = _gated_tests()
    gated["tests/test_zz_new_rollup.py"] = {"duckdb"}
    after = uncovered(read_runs(text), core, extras, gated)
    assert set(after) - set(base) == {"tests/test_zz_new_rollup.py"}
