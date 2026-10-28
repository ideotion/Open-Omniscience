"""Every test that skips for a missing optional package is run, for real, by at least one blocking CI job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. A test that starts with ``pytest.importorskip("duckdb")`` (or a ``skipif(not columnar.duckdb_available())``) is green in
every job that does not install the package, and it is green BY SKIPPING. The ``columnar`` job installs ``[columnar]`` but runs a named
list of nine files, and the rollup work since then added nineteen more gated files that nobody named there: measured on 2026-10-28 by making
``duckdb`` unimportable and running them (151 skipped, 50 passed), they skip in ``test``, ``core-only`` and the portability lane alike, and
install [columnar] in none of them. Their 151 tests had never run in CI. One of them, once run, was red (``test_top_terms_pre_aggregate``
read DuckDB 1.x's profile JSON and DuckDB 2.0.0, which pip resolves today, writes another).

What this pins. It reads ``.github/workflows/ci.yml`` and ``pyproject.toml`` and, for every test file that gates on a package that core does
not install, requires a blocking job that BOTH installs the package (an extra, or a ``pip install NAME==`` pin) AND either runs the whole
suite (a bare ``pytest -q``) or names the file. A job with a literal ``continue-on-error: true`` is an observation lane and does not count.
The gap that exists today is written down below as ``KNOWN_UNCOVERED`` and compared in BOTH directions with zero slack: a new gated file
that no job runs fails, and so does a file that a job started running while still listed here, so the list can only shrink.

What it does not see. A gate it has no name for (a bare ``try: import x`` at module top, ``find_spec``, a ``skipif`` on something other
than ``importorskip`` or ``duckdb_available``); a package whose import name differs from its distribution name and is missing from
``_IMPORT_NAME``; and a job that names a file but runs it with a flag that deselects the gated tests (``-k``).

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

#: The gap, measured 2026-10-28: file -> the package it skips on. A proposal to name these in the ``columnar`` job (and to turn the profile
#: reader in test_top_terms_pre_aggregate.py into one that reads DuckDB 2.x) is in docs/ledger/lessons.d/2026-10-28-tests-no-ci-job-runs.md.
#: Delete a line when a job starts running the file; the test below fails until you do.
KNOWN_UNCOVERED = {
    "tests/test_corpus_epoch.py": "duckdb",
    "tests/test_keyword_daily_merge_interrupted.py": "duckdb",
    "tests/test_keyword_daily_refresh.py": "duckdb",
    "tests/test_keyword_daily_refresh_wal_pinning.py": "duckdb",
    "tests/test_keyword_daily_scan_bound_race.py": "duckdb",
    "tests/test_map_serve.py": "duckdb",
    "tests/test_rollup_benchmark.py": "duckdb",
    "tests/test_rollup_benchmark_guard.py": "duckdb",
    "tests/test_rollup_generation_check.py": "duckdb",
    "tests/test_rollup_parity_bound.py": "duckdb",
    "tests/test_rollup_persisted_generation.py": "duckdb",
    "tests/test_rollup_scan_plan.py": "duckdb",
    "tests/test_rollup_shard_checkpoint.py": "duckdb",
    "tests/test_rollup_sharded_build.py": "duckdb",
    "tests/test_rollup_store_kind.py": "duckdb",
    "tests/test_serve_change_gate.py": "duckdb",
    "tests/test_serve_out_of_memory_goes_live.py": "duckdb",
    "tests/test_top_terms_pre_aggregate.py": "duckdb",
    "tests/test_wave7_poll_cache.py": "duckdb",
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
class Job:
    name: str
    packages: set[str] = field(default_factory=set)
    extras: set[str] = field(default_factory=set)
    bare: bool = False
    files: set[str] = field(default_factory=set)


def _pytest_commands(script: str) -> list[str]:
    """The logical command lines of a ``run`` script that invoke pytest, backslash and ``>-`` continuations joined."""
    text = re.sub(r"\\\n", " ", script)
    return [line for line in text.splitlines() if re.search(r"-m\s+pytest\b", line)]


def read_jobs(workflow: str) -> list[Job]:
    """Blocking jobs only: a literal ``continue-on-error: true`` marks an observation lane that cannot hold anything up."""
    doc = yaml.safe_load(workflow)
    out = []
    for name, job in (doc.get("jobs") or {}).items():
        if job.get("continue-on-error") is True:
            continue
        j = Job(name)
        for step in job.get("steps") or []:
            run = step.get("run")
            if not isinstance(run, str):
                continue
            for line in re.sub(r"\\\n", " ", run).splitlines():
                if "pip install" not in line:
                    continue
                for group in _EXTRA_RE.findall(line):
                    j.extras.update(e.strip() for e in group.split(",") if e.strip())
                for pin in _PIN_RE.findall(line):
                    j.packages.add(_import_name(pin))
            for cmd in _pytest_commands(run):
                named = set(_TEST_FILE_RE.findall(cmd))
                j.files |= named
                if not named and not re.search(r"\btests/", cmd):
                    j.bare = True
        if j.bare or j.files:
            out.append(j)
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


def uncovered(jobs: list[Job], core: set[str], extras: dict[str, set[str]], gated: dict[str, set[str]]) -> dict[str, str]:
    """file -> package, for each gated file no blocking job both installs the package for and runs."""
    stdlib = {m.lower() for m in sys.stdlib_module_names}
    out = {}
    for path, pkgs in sorted(gated.items()):
        for pkg in sorted(pkgs):
            if pkg in core or pkg in stdlib or pkg in ("src", "tests"):
                continue
            homes = extras.get(pkg, set())
            runs = [
                j
                for j in jobs
                if (pkg in j.packages or homes & j.extras) and (j.bare or path in j.files)
            ]
            if not runs:
                out[path] = pkg
    return out


def _gated_tests() -> dict[str, set[str]]:
    gated = {}
    for path in sorted(_TESTS.glob("test_*.py")):
        rel = f"tests/{path.name}"
        pkgs = gated_packages(path.read_text(encoding="utf-8"))
        if rel in _NOT_A_SKIP:
            pkgs.discard("duckdb")
        if pkgs:
            gated[rel] = pkgs
    return gated


def _live() -> dict[str, str]:
    core, extras = read_homes(_PYPROJECT.read_text(encoding="utf-8"))
    return uncovered(read_jobs(_CI.read_text(encoding="utf-8")), core, extras, _gated_tests())


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


def _job(name: str, install: str, test: str, extra: str = "") -> str:
    body = "\n".join("          " + ln for ln in test.splitlines())
    return (
        f"  {name}:\n{extra}    steps:\n"
        f"      - run: {install}\n"
        f"      - run: |\n{body}\n"
    )


def _check(workflow: str, sources: dict[str, str]) -> dict[str, str]:
    core, extras = read_homes(_PYPROJECT_TEXT)
    gated = {p: g for p, s in sources.items() if (g := gated_packages(s))}
    return uncovered(read_jobs(workflow), core, extras, gated)


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
        # the same pin spelled by import name does not exist: the dist name is mapped
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
    """Remove one property from the real ci.yml and the checker must name what that opened (and nothing else)."""
    text = _CI.read_text(encoding="utf-8")
    base = _live()

    # 1. take a file that the columnar job names out of its list
    victim = "tests/test_rollup_serve_persisted.py"
    assert text.count(victim) == 1, "the mutant's anchor moved: update this test"
    assert victim not in base, "the file is gated and listed: it must be covered"
    mutated = text.replace(victim, "")
    core, extras = read_homes(_PYPROJECT.read_text(encoding="utf-8"))
    after = uncovered(read_jobs(mutated), core, extras, _gated_tests())
    assert set(after) - set(base) == {victim}, after

    # 2. drop the columnar extra from the job that installs it: every file that job covered is open
    needle = 'python -m pip install -e ".[analysis,dev,columnar]"'
    assert text.count(needle) == 1, "the mutant's anchor moved: update this test"
    after = uncovered(read_jobs(text.replace(needle, 'python -m pip install -e ".[analysis,dev]"')), core, extras, _gated_tests())
    opened = set(after) - set(base)
    assert victim in opened and "tests/test_columnar_engine.py" in opened, sorted(opened)

    # 3. a gated file nobody names, as a developer adds one
    gated = _gated_tests()
    gated["tests/test_zz_new_rollup.py"] = {"duckdb"}
    after = uncovered(read_jobs(text), core, extras, gated)
    assert set(after) - set(base) == {"tests/test_zz_new_rollup.py"}
