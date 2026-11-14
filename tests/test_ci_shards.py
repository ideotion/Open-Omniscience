"""The CI ``test`` and ``core-only`` jobs run in three shards; this pins that the shards are a partition of the suite and that the workflow wires them as claimed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists (C10, decision 27, R412). Each job ran the whole suite in one process, 70 to 80 minutes. Each is now a matrix of three legs that run a third
of the test FILES (``scripts/ci_shard.py``, the cost table ``configs/ci_shard_costs.json``). Sharding can fail in ways one process cannot, and each is
pinned below, with a mutant that breaks it:

* a test file in NO shard (the suite quietly shrinks) or in two (it runs twice): the partition is checked over the real tree for the table's N and for
  other N, and for a file the table does not name;
* a leg that ran nothing, or a shard list so lopsided that the sharding bought nothing: every shard has files; the table's predicted loads are within 3 %;
* the REQUIRED CHECKS. Branch protection requires the checks named ``test`` and ``Core-only install (no [analysis] extra)``. A matrix leg is never named
  that; two aggregator jobs (``test-all``, ``core-only-all``) carry those names and are green only if every leg is. A check that never reports
  blocks every merge; one that reports green when a leg never ran lets a red suite through. The aggregator must run ``always()`` (a job whose needs failed
  is otherwise SKIPPED, and a skipped required check counts as passing), must need exactly its matrix job, and must test the result for ``success``;
* the legs' matrix is ``1..N`` for the N in the table and in the plan step; each leg plans its own files in a step of its own (no ``if``, not advisory)
  straight before pytest, and the pytest line that reads the list is pinned by tests/test_ci_pytest_flags_and_preflight.py;
* the static steps (lint, planned-work index, i18n gates, migration drift, mypy, bandit, pip-audit) are the ``static`` job since R668 (they ran in leg 1
  and made it the run's critical path): ``test`` holds only the steps every leg needs, the ``static`` job runs every gate it took over, blocking and on
  the same condition as the legs, and the required check ``test`` (``test-all``) needs it and fails unless it is ``success``.
  tests/test_skipped_tests_have_a_ci_job_that_runs_them.py knows that a job whose matrix is complete counts as the whole suite, and only then;
* each leg keeps its junit report as an artifact (R433), the source of the next cost table: one upload step per job, pinned, on red as well as green, never
  red itself, named per leg and per job, after pytest and before the skip summary (which has to stay the job's last step).

What it does not see. Whether a test is order-independent: that is what the one sharded-against-unsharded run on the same commit was for
(docs/ledger/shipped_log.d/2026-11-05-ci-test-and-core-only-run-in-three-shards.md), and what every later green run of the legs shows. Whether the
cost table is still a fair measurement: ``plan`` prints how many files it does not name and what it predicts, and the job summary has each leg's real
time. Whether GitHub's branch protection names the checks above: that setting is not in the repository (a user item in the PR that introduced this).

The guard proves itself: each mutant below breaks one property of the real ``ci.yml``, of the real table or of the digest comparison, and the checker
must name it.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_PYPROJECT = _ROOT / "pyproject.toml"
_SCRIPT = _ROOT / "scripts" / "ci_shard.py"


def _load():
    spec = importlib.util.spec_from_file_location("_ci_shard_under_test", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load()
_TABLE = S.load_table()
_N = _TABLE["shards"]


# ---------------------------------------------------------------------------------------------------- the planner
@pytest.mark.parametrize("spec, want", [("1/3", (1, 3)), ("3/3", (3, 3)), (" 2/10 ", (2, 10)), ("1/1", (1, 1))])
def test_a_shard_spec_is_read(spec, want):
    assert S.parse_shard(spec) == want


@pytest.mark.parametrize("spec", ["0/3", "4/3", "1/0", "a/b", "1/3/3", "", "1", "-1/3", "1.5/3", "2/3 x"])
def test_a_bad_shard_spec_is_refused(spec):
    with pytest.raises(ValueError):
        S.parse_shard(spec)


def test_dealing_is_longest_first_to_the_least_loaded_shard_and_ignores_the_order_it_is_given():
    costs = {"tests/a.py": 1.0, "tests/b.py": 10.0, "tests/c.py": 4.0, "tests/d.py": 9.0, "tests/e.py": 5.0}
    # b=10 -> shard 1; d=9 -> shard 2; e=5 -> shard 3; c=4 -> shard 3 (5 < 9 < 10); a=1 -> shard 2 (loads 10, 9, 9: the tie goes to the lower shard).
    # In name order the same costs would deal a -> 1, b -> 2, c -> 3, d -> 1, e -> 3.
    assert S.deal(costs, 3) == {"tests/b.py": 1, "tests/d.py": 2, "tests/e.py": 3, "tests/c.py": 3, "tests/a.py": 2}
    shuffled = dict(reversed(list(costs.items())))
    assert S.deal(shuffled, 3) == S.deal(costs, 3)
    # equal costs are told apart by name, not by the order they arrive in
    ties = {"tests/z.py": 1.0, "tests/y.py": 1.0, "tests/x.py": 1.0}
    assert S.deal(ties, 3) == {"tests/x.py": 1, "tests/y.py": 2, "tests/z.py": 3}


def test_the_overhead_of_a_shard_is_work_already_done():
    assert S.deal({"tests/a.py": 5.0, "tests/b.py": 5.0}, 2, [100]) == {"tests/a.py": 2, "tests/b.py": 2}
    assert S.deal({"tests/a.py": 5.0, "tests/b.py": 5.0}, 2, []) == {"tests/a.py": 1, "tests/b.py": 2}
    assert S.deal({"tests/a.py": 5.0}, 2, [1, 2, 3, 4]) == {"tests/a.py": 1}, "an overhead list longer than the shards is cut, not an error here (load_table refuses it)"


def test_a_file_the_table_does_not_name_goes_to_a_hash_that_is_the_same_everywhere():
    assert S.unlisted_shard("tests/test_brand_new.py", 3) == zlib.crc32(b"tests/test_brand_new.py") % 3 + 1
    assert zlib.crc32(b"tests/test_brand_new.py") == 2843097825, "crc32 itself changed"
    assert S.unlisted_shard("tests/test_brand_new.py", 3) == 1, "the hash is pinned: a change here moves every unlisted file"
    assert S.unlisted_shard("tests/test_brand_new.py", 1) == 1


def test_adding_or_removing_a_test_file_moves_no_file_the_table_names():
    table = {"shards": 3, "overhead_seconds": [80], "costs": {f"tests/test_f{i}.py": float(i % 17 + 1) for i in range(60)}}
    base = S.assign(sorted(table["costs"]), 3, table)
    more = sorted(table["costs"]) + ["tests/test_new_one.py", "tests/test_new_two.py"]
    assert {p: at for p, at in S.assign(more, 3, table).items() if p in base} == base
    fewer = sorted(table["costs"])[5:]
    assert S.assign(fewer, 3, table) == {p: base[p] for p in fewer}


def test_the_table_is_read_strictly(tmp_path):
    def write(**over):
        data = {"shards": 3, "overhead_seconds": [80], "costs": {"tests/a.py": 1.0}} | over
        path = tmp_path / "t.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    assert S.load_table(write())["shards"] == 3
    for bad in (
        {"costs": {"tests/a.py": -1}},
        {"costs": {"tests/a.py": "fast"}},
        {"costs": []},
        {"shards": 0},
        {"shards": "3"},
        {"overhead_seconds": [1, 2, 3, 4]},
        {"overhead_seconds": [-5]},
    ):
        with pytest.raises(ValueError):
            S.load_table(write(**bad))


# ------------------------------------------------------------------------------------- the partition of the real tree
def _shard_lists(shards: int) -> dict[int, list[str]]:
    return {k: S.files_of(k, shards, _TABLE) for k in range(1, shards + 1)}


@pytest.mark.parametrize("shards", sorted({1, 2, 3, 4, 5, _N}))
def test_the_shards_are_a_partition_of_the_test_files_of_the_tree(shards):
    files = S.test_files()
    assert len(files) > 1000, "the tree lost its tests, or test_files() stopped finding them"
    lists = _shard_lists(shards)
    flat = [f for group in lists.values() for f in group]
    assert sorted(flat) == files, "a test file is in no shard, or in two"
    assert all(lists.values()), "a shard has no test file"
    assert S.problems(files, shards, _TABLE) == []


def test_test_files_agree_with_pytest_config_and_with_a_walk_of_the_tree():
    text = _PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r'python_files = \["test_\*\.py", "\*_test\.py"\]', text), "pyproject's python_files changed: scripts/ci_shard.py's patterns must follow"
    assert re.search(r'testpaths = \["tests"\]', text), "pyproject's testpaths changed: scripts/ci_shard.py only looks under tests/"
    walked = set()
    for here, dirs, names in os.walk(_ROOT / "tests"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        walked |= {Path(here, n).relative_to(_ROOT).as_posix() for n in names if (n.startswith("test_") and n.endswith(".py")) or n.endswith("_test.py")}
    assert set(S.test_files()) == walked
    assert "tests/scale/test_scale_smoke.py" in walked, "the one nested test file: the walk is meant to see below tests/"


def test_a_file_the_table_does_not_name_is_in_exactly_one_shard():
    files = S.test_files() + ["tests/test_a_file_added_after_the_table.py", "tests/sub/test_another.py"]
    lists = {k: [f for f in files if S.assign(files, _N, _TABLE)[f] == k] for k in range(1, _N + 1)}
    assert sorted(f for group in lists.values() for f in group) == sorted(files)
    assert S.problems(files, _N, _TABLE) == []


def test_unlisted_files_take_the_hash_and_spread_over_the_shards():
    new = [f"tests/test_added_{i}.py" for i in range(40)]
    got = S.assign(new, _N, _TABLE)
    assert got == {f: S.unlisted_shard(f, _N) for f in new}
    assert set(got.values()) == set(range(1, _N + 1)), "forty new files all landed in one shard: the hash is not spreading them"


def test_the_partition_check_names_a_file_that_is_in_no_shard_or_a_shard_that_is_empty(monkeypatch):
    files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
    table = {"shards": 3, "costs": {}}
    monkeypatch.setattr(S, "assign", lambda f, n, t: {"tests/test_a.py": 1, "tests/test_b.py": 2, "tests/test_c.py": 4})
    found = S.problems(files, 3, table)
    assert any("tests/test_c.py is in 0 shards" in line for line in found), found
    assert any("shard 3/3 has no test file" in line for line in found), found
    monkeypatch.setattr(S, "assign", lambda f, n, t: {"tests/test_a.py": 1, "tests/test_b.py": 2})
    assert any("tests/test_c.py is in 0 shards" in line for line in S.problems(files, 3, table))


def test_the_table_balances_the_shards_it_deals_to():
    dealt = S.deal(_TABLE["costs"], _N, _TABLE.get("overhead_seconds"))
    overhead = list(_TABLE.get("overhead_seconds", [])) + [0.0] * _N
    loads = [float(overhead[k]) + sum(float(c) for p, c in _TABLE["costs"].items() if dealt[p] == k + 1) for k in range(_N)]
    assert max(loads) <= 1.03 * (sum(loads) / _N), f"the shards the table deals are lopsided: {[round(x) for x in loads]} s"


def test_every_path_in_the_table_is_a_normalised_test_file_path():
    for path in _TABLE["costs"]:
        assert path.startswith("tests/") and path.endswith(".py") and "\\" not in path and ".." not in path, path
    assert _TABLE["shards"] == 3, "the table's N moved: the matrix, the plan steps and the job names say 3 too (the wiring tests below name each)"


# --------------------------------------------------------------------------------------------- the digest comparison
_JUNIT = """<testsuites><testsuite>
<testcase classname="tests.test_a" name="test_one" time="0.5"/>
<testcase classname="tests.test_a.TestK" name="test_p[1]" time="1.0"/>
<testcase classname="tests.test_a" name="test_skip" time="0.0"><skipped type="pytest.skip" message="why"/></testcase>
<testcase classname="tests.test_a" name="test_xf" time="0.0"><skipped type="pytest.xfail" message=""/></testcase>
<testcase classname="tests.test_a" name="test_bad" time="2.0"><failure message="assert 0"/></testcase>
<testcase classname="tests.scale.test_scale_smoke" name="test_e" time="3.0"><failure message="x"/><error message="teardown"/></testcase>
<testcase classname="" name="tests.test_b" time="0.0"><skipped type="pytest.skip" message="collection skipped"/></testcase>
<testcase classname="tests.other_test.TestZ" name="test_z" time="0.25"/>
<testcase classname="odd name" name="x" time="1.0"/>
</testsuite></testsuites>"""


def _junit(tmp_path, text=_JUNIT, name="j.xml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_junit_report_is_read_into_modules_and_one_letter_outcomes(tmp_path):
    rows = S.read_junit(_junit(tmp_path))
    by = {(m, i.split("::")[1]): (o, t) for m, i, o, t in rows}
    assert by[("tests/test_a.py", "test_one")] == ("p", 0.5)
    assert by[("tests/test_a.py", "test_p[1]")][0] == "p", "a class's testcase belongs to its module"
    assert by[("tests/test_a.py", "test_skip")][0] == "s"
    assert by[("tests/test_a.py", "test_xf")][0] == "x", "an expected failure is not a skip"
    assert by[("tests/test_a.py", "test_bad")][0] == "f"
    assert by[("tests/scale/test_scale_smoke.py", "test_e")][0] == "e", "an error beats a failure"
    assert by[("tests/test_b.py", "tests.test_b")][0] == "s", "a collection-time skip has no classname: its name is the module"
    assert by[("tests/other_test.py", "test_z")][0] == "p", "a *_test.py module"
    assert by[(S._UNNAMED, "x")][0] == "p"


def test_a_digest_counts_hashes_and_sums(tmp_path):
    dig = S.digest(S.read_junit(_junit(tmp_path)))
    assert dig["tests/test_a.py"]["counts"] == "2p1s1x1f"
    assert dig["tests/test_a.py"]["seconds"] == 3.5
    assert re.fullmatch(r"[0-9a-f]{12}", dig["tests/test_a.py"]["hash"])
    again = S.digest(list(reversed(S.read_junit(_junit(tmp_path)))))
    assert again == dig, "the digest does not depend on the order the cases were written in"
    assert S.parse_rendered(S.render(dig)) == dig
    assert S.unpack(S.pack(S.render(dig))) == S.render(dig)
    assert "\n" not in S.pack("x\n" * 5000) and len(S.pack("tests/test_a.py 1p abc 1.0\n" * 2000)) < 5000


def test_an_unreadable_report_is_named_not_swallowed(tmp_path):
    with pytest.raises(ValueError):
        S.read_junit(_junit(tmp_path, "<testsuites><testcase"))
    with pytest.raises(OSError):
        S.read_junit(tmp_path / "missing.xml")


def _toy_table():
    return {"shards": 3, "overhead_seconds": [], "costs": {f"tests/test_m{i}.py": float(10 - i) for i in range(6)}}


def _toy_cases():
    return [(f"tests/test_m{i}.py", f"tests.test_m{i}::test_{j}", "p" if j else "s", 1.0) for i in range(6) for j in range(3)]


def _slice(rows, shard, table):
    of = S.shard_lookup(3, table)
    return [r for r in rows if of(r[0]) == shard]


def test_the_shards_of_a_toy_suite_match_the_unsharded_run():
    table, rows = _toy_table(), _toy_cases()
    oracle = S.digest(rows)
    for shard in (1, 2, 3):
        assert S.compare(oracle, S.digest(_slice(rows, shard, table)), shard, 3, table) == []


@pytest.mark.parametrize(
    ("label", "edit", "says"),
    [
        ("a test is missing from the shard", lambda rows: rows[1:], "unsharded"),
        ("a module is missing from the shard", lambda rows: [r for r in rows if r[0] != "tests/test_m0.py"], "absent from shard"),
        ("an outcome differs", lambda rows: [(m, i, "f" if n == 0 else o, t) for n, (m, i, o, t) in enumerate(rows)], "unsharded"),
        ("a test was renamed (same counts)", lambda rows: [(m, i + "x", o, t) for m, i, o, t in rows[:1]] + rows[1:], "unsharded"),
        ("a module ran in a shard it does not belong to", lambda rows: rows + [("tests/test_zz.py", "tests.test_zz::t", "p", 1.0)], "absent from the unsharded"),
    ],
)
def test_the_comparison_names_what_differs(label, edit, says):
    table, rows = _toy_table(), _toy_cases()
    oracle = S.digest(rows)
    broke = False
    for shard in (1, 2, 3):
        mine = _slice(rows, shard, table)
        found = S.compare(oracle, S.digest(edit(mine)), shard, 3, table)
        broke = broke or bool(found)
        assert not found or any(says in line for line in found), (label, found)
    assert broke, f"{label}: no shard named it"


def test_times_do_not_make_a_difference_and_unnamed_modules_are_left_out():
    table, rows = _toy_table(), _toy_cases()
    oracle = S.digest(rows + [(S._UNNAMED, "odd::x", "p", 1.0)])
    slow = [(m, i, o, t * 7) for m, i, o, t in _slice(rows, 1, table)]
    assert S.compare(oracle, S.digest(slow), 1, 3, table) == []


def test_costs_are_rewritten_from_reports_and_keep_the_shape(tmp_path):
    old = {"shards": 3, "overhead_seconds": [80], "source": "x", "costs": {"tests/test_old.py": 9.0}}
    new = S.measured_table(old, [_junit(tmp_path), _junit(tmp_path, name="k.xml")])
    assert new["shards"] == 3 and new["overhead_seconds"] == [80] and new["source"] == "x"
    assert new["costs"]["tests/test_a.py"] == 7.0 and "tests/test_old.py" not in new["costs"] and S._UNNAMED not in new["costs"]


def test_the_command_line_plans_checks_digests_and_compares(tmp_path, capsys, monkeypatch):
    out = tmp_path / "shard.args"
    assert S.main(["plan", "--shard", f"1/{_N}", "--out", str(out)]) == 0
    every = S.test_files()
    mine = S.files_of(1, _N, _TABLE)
    assert out.read_text(encoding="utf-8").splitlines() == [f"--ignore={f}" for f in every if f not in set(mine)], "the plan ignores every file of the OTHER shards"
    assert re.search(r"shard 1/3: runs \d+ of \d+ test files \(ignores \d+\); the table predicts \d+ s; \d+ not in the table", capsys.readouterr().out)
    assert S.main(["check"]) == 0
    assert S.main(["plan", "--shard", "4/3", "--out", str(out)]) == 2, "a shard past N is an error, not an empty list"
    # an empty shard is refused: `pytest @EMPTY` would run the whole suite
    monkeypatch.setattr(S, "test_files", lambda root=S.ROOT: ["tests/test_only.py"])
    empty = 1 if S.unlisted_shard("tests/test_only.py", 2) == 2 else 2
    assert S.main(["--table", str(tmp_path / "t.json"), "plan", "--shard", f"{empty}/2", "--out", str(out)]) == 2  # no such table: named, not a traceback
    (tmp_path / "t.json").write_text(json.dumps({"shards": 2, "costs": {}}), encoding="utf-8")
    assert S.main(["--table", str(tmp_path / "t.json"), "plan", "--shard", f"{empty}/2", "--out", str(out)]) == 1
    # the shard that owns the only file would ignore nothing, i.e. run the whole suite: refused too
    assert S.main(["--table", str(tmp_path / "t.json"), "plan", "--shard", f"{3 - empty}/2", "--out", str(out)]) == 1
    # one shard of one runs everything: an empty ignore list is right there (and only there)
    assert S.main(["--table", str(tmp_path / "t.json"), "plan", "--shard", "1/1", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == ""
    monkeypatch.undo()
    report = _junit(tmp_path)
    assert S.main(["digest", str(report)]) == 0
    printed = capsys.readouterr().out
    assert "tests/test_a.py 2p1s1x1f " in printed
    # parity: the unsharded digest is in an environment variable, packed
    rows = S.read_junit(report)
    table = _TABLE
    mine = [r for r in rows if r[0] != S._UNNAMED and S.shard_lookup(_N, table)(r[0]) == 1]
    (tmp_path / "mine.xml").write_text(_JUNIT, encoding="utf-8")
    monkeypatch.setenv("ORACLE", S.pack(S.render(S.digest(rows))))
    assert S.main(["parity", "--shard", f"1/{_N}", "--junit", str(report), "--oracle-env", "ORACLE"]) == 1, "the report holds every shard's modules: shard 1 has only its own"
    only = "<testsuites><testsuite>" + "".join(f'<testcase classname="{m[:-3].replace("/", ".")}" name="t" time="1"/>' for m in sorted({r[0] for r in mine})) + "</testsuite></testsuites>"
    monkeypatch.setenv("ORACLE", S.pack(S.render(S.digest([(m, f"{m[:-3].replace('/', '.')}::t", "p", 1.0) for m in sorted({r[0] for r in mine})]))))
    assert S.main(["parity", "--shard", f"1/{_N}", "--junit", str(_junit(tmp_path, only, "only.xml")), "--oracle-env", "ORACLE"]) == 0
    monkeypatch.delenv("ORACLE")
    assert S.main(["parity", "--shard", f"1/{_N}", "--junit", str(report), "--oracle-env", "ORACLE"]) == 1, "no oracle is a failure, not a pass"


# --------------------------------------------------------------------------------- how a shard is run: it ignores the others' files
def test_a_plan_ignores_the_files_of_the_other_shards_and_runs_the_rest():
    files = [f"tests/test_m{i}.py" for i in range(6)]
    assert S.ignore_args(files[:2], files) == [f"--ignore={f}" for f in files[2:]]
    assert S.ignore_args(files, files) == [] and S.ignore_args([], files) == [f"--ignore={f}" for f in files]
    everyone = [set(S.ignore_args(S.files_of(k, _N, _TABLE), S.test_files())) for k in range(1, _N + 1)]
    # a file is run by exactly the shard that does not ignore it
    for f in S.test_files():
        assert sum(f"--ignore={f}" not in ignored for ignored in everyone) == 1, f


def _run_pytest(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "COV_"))}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def test_a_file_named_on_the_command_line_escapes_collect_ignore_and_a_plan_does_not(tmp_path):
    """The first sharded Core-only leg named its files: the two analysis modules that tests/conftest.py keeps out of a core-only install through
    ``collect_ignore`` were collected, and died at import. Real pytest, on a toy tree built like the suite's: ``test_ignored.py`` is in ``collect_ignore``
    and cannot be imported; ``test_one.py`` and ``test_two.py`` are fine; the shards are ``{ignored, one}`` and ``{two}``."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    (tests / "conftest.py").write_text('collect_ignore = ["test_ignored.py"]\n', encoding="utf-8")
    (tests / "test_ignored.py").write_text("import module_that_is_not_installed\n\ndef test_x():\n    pass\n", encoding="utf-8")
    (tests / "test_one.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
    (tests / "test_two.py").write_text("def test_two():\n    pass\n", encoding="utf-8")
    files = S.test_files(tmp_path)
    assert files == ["tests/test_ignored.py", "tests/test_one.py", "tests/test_two.py"]

    named = _run_pytest(tmp_path, "tests/test_ignored.py", "tests/test_one.py")
    assert named.returncode != 0 and "module_that_is_not_installed" in named.stdout, "naming a file on the command line collects it even though collect_ignore lists it"

    plan = tmp_path / "shard.args"
    plan.write_text("".join(f"{line}\n" for line in S.ignore_args(["tests/test_ignored.py", "tests/test_one.py"], files)), encoding="utf-8")
    first = _run_pytest(tmp_path, f"@{plan}")
    assert first.returncode == 0 and "1 passed" in first.stdout, first.stdout
    plan.write_text("".join(f"{line}\n" for line in S.ignore_args(["tests/test_two.py"], files)), encoding="utf-8")
    second = _run_pytest(tmp_path, f"@{plan}")
    assert second.returncode == 0 and "1 passed" in second.stdout, second.stdout
    # a shard that ignores everything runs nothing and is RED (exit 5), where an empty list of files would have run the whole suite
    plan.write_text("".join(f"{line}\n" for line in S.ignore_args([], files)), encoding="utf-8")
    nothing = _run_pytest(tmp_path, f"@{plan}")
    # exit 5 IS pytest's "no tests collected"; the words beside it are not stable (pytest 9 prints "N warning(s) in ..." INSTEAD of "no tests ran" when
    # anything warns), so the test pins the code and that nothing ran, not the sentence
    assert nothing.returncode == 5 and " passed" not in nothing.stdout and " failed" not in nothing.stdout, (nothing.returncode, nothing.stdout)


_COLLECTED = """tests/test_a.py::test_one
tests/test_a.py::TestK::test_two[1-x y]
tests/test_b.py::test_three

3 tests collected in 0.01s
"""


def test_collected_ids_are_read_and_compared(tmp_path, capsys):
    ids = S.read_collected(_COLLECTED)
    assert ids == ["tests/test_a.py::test_one", "tests/test_a.py::TestK::test_two[1-x y]", "tests/test_b.py::test_three"], "the summary line and the blank line are not ids"
    assert S.read_collected("ERROR tests/test_c.py - ImportError: x\nno tests ran in 0.1s\n") == []
    assert S.compare_collected(ids, [ids[:1], ids[1:]]) == []
    assert any("by no shard" in line for line in S.compare_collected(ids, [ids[:1], ids[1:2]]))
    assert any("not by the whole suite" in line for line in S.compare_collected(ids, [ids, ["tests/test_z.py::t"]]))
    assert any("collected 2 times" in line for line in S.compare_collected(ids, [ids, ids[:1]]))
    assert any("collected 2 times" in line for line in S.compare_collected(ids, [ids + ids[:1]])), "twice in one shard"
    whole = tmp_path / "all.txt"
    whole.write_text(_COLLECTED, encoding="utf-8")
    a, b = tmp_path / "s1.txt", tmp_path / "s2.txt"
    a.write_text("\n".join(ids[:1]) + "\n\n1 test collected\n", encoding="utf-8")
    b.write_text("\n".join(ids[1:]) + "\n", encoding="utf-8")
    assert S.main(["collected", "--all", str(whole), str(a), str(b)]) == 0
    assert "shards together: 3 tests in 2 modules; 0 difference(s)" in capsys.readouterr().out
    assert S.main(["collected", "--all", str(whole), str(a)]) == 1, "a shard missing"
    assert "collected by the whole suite, by no shard" in capsys.readouterr().out
    empty = tmp_path / "e.txt"
    empty.write_text("no tests ran in 0.1s\n", encoding="utf-8")
    assert S.main(["collected", "--all", str(empty), str(empty)]) == 1, "an empty whole collection compares nothing: red, not green"


def test_totals_count_every_outcome_and_are_described_in_words(tmp_path, capsys):
    dig = S.digest(S.read_junit(_junit(tmp_path)))
    count = S.totals(dig)
    # 2p1s1x1f in tests/test_a.py, 1f1e... in scale (error beats failure -> 1e), 1s in test_b, 1p in other_test, 1p in the unnamed bucket
    assert dict(count) == {"p": 4, "s": 2, "x": 1, "f": 1, "e": 1}, count
    assert S.describe(count) == "4 passed 2 skipped 1 xfailed 1 failed 1 errors"
    assert S.describe(S.Counter()) == "0 passed 0 skipped 0 xfailed 0 failed 0 errors"
    assert S.main(["totals", str(_junit(tmp_path))]) == 0
    assert "9 tests in 5 modules: 4 passed 2 skipped 1 xfailed 1 failed 1 errors" in capsys.readouterr().out


def test_parity_compares_pass_skip_and_xfail_counts_not_only_the_module_set(tmp_path, capsys, monkeypatch):
    of = S.shard_lookup(_N, _TABLE)
    mods = [m for m in sorted(_TABLE["costs"]) if of(m) == 1][:2]
    assert len(mods) == 2, "the real table gives shard 1 at least two files"
    dotted = [m[:-3].replace("/", ".") for m in mods]

    def report(cases, name):
        body = "".join(cases)
        return _junit(tmp_path, f"<testsuites><testsuite>{body}</testsuite></testsuites>", name)

    def case(mod, name, kind=""):
        inner = {"": "", "s": '<skipped type="pytest.skip" message="why"/>', "x": '<skipped type="pytest.xfail" message=""/>'}[kind]
        return f'<testcase classname="{mod}" name="{name}" time="1">{inner}</testcase>'

    oracle_cases = [case(dotted[0], "a"), case(dotted[0], "b", "s"), case(dotted[1], "c", "x")]
    oracle = S.digest(S.read_junit(report(oracle_cases, "oracle.xml")))
    monkeypatch.setenv("ORACLE", S.pack(S.render(oracle)))
    args = ["parity", "--shard", f"1/{_N}", "--oracle-env", "ORACLE", "--junit"]

    assert S.main([*args, str(report(oracle_cases, "same.xml"))]) == 0
    out = capsys.readouterr().out
    assert "unsharded run, this shard's modules: 1 passed 1 skipped 1 xfailed 0 failed 0 errors" in out
    assert "this shard:                          1 passed 1 skipped 1 xfailed 0 failed 0 errors" in out
    assert "0 difference(s)" in out

    # same modules, same tests, a skip that ran (passed): the counts and the hash differ
    ran = [case(dotted[0], "a"), case(dotted[0], "b"), case(dotted[1], "c", "x")]
    assert S.main([*args, str(report(ran, "ran.xml"))]) == 1
    out = capsys.readouterr().out
    assert "1 difference(s)" in out and "2p" in out and "skipped" in out
    assert "counts differ" in out

    # an xfail that now skips
    swapped = [case(dotted[0], "a"), case(dotted[0], "b", "s"), case(dotted[1], "c", "s")]
    assert S.main([*args, str(report(swapped, "swapped.xml"))]) == 1

    # a module of the shard is absent: the module set and the totals both say so
    assert S.main([*args, str(report(oracle_cases[:2], "gone.xml"))]) == 1
    assert "absent from shard 1/3" in capsys.readouterr().out


def test_the_totals_check_fails_even_when_the_per_module_comparison_is_empty(monkeypatch, tmp_path, capsys):
    """The per-module counts already sit inside the comparison; the totals line is a second, coarser reading that must never pass alone."""
    monkeypatch.setattr(S, "compare", lambda *a, **k: [])
    of = S.shard_lookup(_N, _TABLE)
    mod = next(m for m in sorted(_TABLE["costs"]) if of(m) == 1)
    dotted = mod[:-3].replace("/", ".")
    one = f'<testsuites><testsuite><testcase classname="{dotted}" name="a" time="1"/></testsuite></testsuites>'
    two = f'<testsuites><testsuite><testcase classname="{dotted}" name="a" time="1"/><testcase classname="{dotted}" name="b" time="1"/></testsuite></testsuites>'
    monkeypatch.setenv("ORACLE", S.pack(S.render(S.digest(S.read_junit(_junit(tmp_path, two, "two.xml"))))))
    code = S.main(["parity", "--shard", f"1/{_N}", "--oracle-env", "ORACLE", "--junit", str(_junit(tmp_path, one, "one.xml"))])
    assert code == 1
    assert "counts differ" in capsys.readouterr().out


def test_a_parity_that_compared_nothing_is_not_a_pass(monkeypatch, tmp_path, capsys):
    """Two empty sides have no difference to find. A conftest import error leaves ONE testcase with no module, in the unsharded report and in every
    shard's, so the module sets, the per-module comparison and the totals all agree on nothing: that must be a refusal, not a green leg."""
    broken = '<testsuites><testsuite><testcase classname="" name="tests.conftest" time="0"><error message="ImportError"/></testcase></testsuite></testsuites>'
    empty = "<testsuites><testsuite></testsuite></testsuites>"
    of = S.shard_lookup(_N, _TABLE)
    elsewhere = next(m for m in sorted(_TABLE["costs"]) if of(m) == 2)
    other = f'<testsuites><testsuite><testcase classname="{elsewhere[:-3].replace("/", ".")}" name="a" time="1"/></testsuite></testsuites>'
    args = ["parity", "--shard", f"1/{_N}", "--oracle-env", "ORACLE", "--junit"]
    for label, (oracle, shard) in {
        "no module on either side": (broken, broken),
        "no testcase on either side": (empty, empty),
        "the unsharded run holds nothing of this shard, and this shard ran nothing": (other, empty),
    }.items():
        monkeypatch.setenv("ORACLE", S.pack(S.render(S.digest(S.read_junit(_junit(tmp_path, oracle, "oracle.xml"))))))
        assert S.main([*args, str(_junit(tmp_path, shard, "shard.xml"))]) == 1, label
        captured = capsys.readouterr()
        assert "nothing was compared" in captured.err, label
        assert "0 modules compared" in captured.out, label


def test_costs_rewrite_the_table_they_read_not_the_shipped_one(monkeypatch, tmp_path):
    shipped = tmp_path / "shipped.json"
    shipped.write_text(json.dumps({"shards": 3, "overhead_seconds": [80], "source": "shipped", "costs": {"tests/test_shipped.py": 1.0}}), encoding="utf-8")
    monkeypatch.setattr(S, "COSTS", shipped)
    before = shipped.read_bytes()
    mine = tmp_path / "mine.json"
    old = {"shards": 2, "overhead_seconds": [5], "source": "mine", "costs": {"tests/test_old.py": 9.0}}
    mine.write_text(json.dumps(old), encoding="utf-8")
    report = _junit(tmp_path)
    assert S.main(["--table", str(mine), "costs", str(report)]) == 0
    assert shipped.read_bytes() == before, "a table named with --table is not the shipped table"
    assert json.loads(mine.read_text(encoding="utf-8")) == S.measured_table(old, [report])
    assert S.main(["costs", str(report)]) == 0  # no --table: the shipped one, as before
    assert json.loads(shipped.read_text(encoding="utf-8"))["costs"] != {"tests/test_shipped.py": 1.0}


def test_the_partition_check_counts_each_problem_once(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(S, "test_files", lambda root=S.ROOT: ["tests/test_a.py", "tests/test_b.py"])
    monkeypatch.setattr(S, "assign", lambda files, n, table: {"tests/test_a.py": 1, "tests/test_b.py": 1})
    table = tmp_path / "t.json"
    table.write_text(json.dumps({"shards": 3, "costs": {}}), encoding="utf-8")
    assert S.main(["--table", str(table), "check"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert [line for line in lines if "has no test file" in line] == ["shard 2/3 has no test file", "shard 3/3 has no test file"]
    assert lines[-1] == "2 test files, 3 shards: 2 problem(s)"


# ------------------------------------------------------------------------------------------------ the workflow wiring
_AGGREGATORS ={"test": ("test-all", "test"), "core-only": ("core-only-all", "Core-only install (no [analysis] extra)")}
_PLAN = 'python scripts/ci_shard.py plan --shard ${{ matrix.shard }}/%d --out "$RUNNER_TEMP/shard.args"'
#: The junit report each leg's pytest step writes (tests/test_ci_pytest_flags_and_preflight.py pins that step) and the artifact each leg uploads it as (R433).
_REPORT = "${{ runner.temp }}/junit.xml"
_ARTIFACT = "junit-%s-shard-${{ matrix.shard }}"
#: Steps of ``test`` that every leg runs; any other step belongs in the ``static`` job (R668).
_EVERY_LEG = (
    "Set up Python",
    "Install the tesseract",
    "Install two more awk",
    "Install (core + analysis",
    "Plan this shard",
    "Test (pytest)",
    "Installed versions",
    "Skipped tests and slowest modules",
)


#: Jobs besides the matrix that an aggregator needs and requires to be `success`, and the variable its step reads each one's result from (R668).
_ALSO_REQUIRED = {"test-all": ["static"]}
_ENV_OF = {"static": "STATIC"}
#: The gates the `static` job took over from leg 1 of `test` (R668): a prefix of each step's name and a piece of its command. Each runs once, blocking.
_STATIC_GATES = (
    ("Lint — correctness", "ruff check --select=F,B"),
    ("Lint — style non-growth ratchet", "scripts/ruff_ratchet.py --max"),
    ("Planned-work index — blocked or forbidden paths", "--strict"),
    ("i18n locale completeness", "i18n_report.py --min 100"),
    ("i18n untranslatable-string ratchet", "--max-untranslatable 0"),
    ("i18n unkeyed t() call sites", "--max-unkeyed-t-calls 0"),
    ("i18n unkeyed tf() frames", "--max-unkeyed-tf-frames 0"),
    ("Migration drift", "alembic check"),
    ("Type check (mypy, BLOCKING)", "python -m mypy src/"),
    ("SAST (bandit", "bandit -r src/ -ll"),
    ("Dependency audit (pip-audit)", "pip-audit"),
)
#: The one gate that runs on a condition: the blocked-paths index compares a PR with its base, which a push has none of (as in leg 1 before R668).
_STATIC_GATE_IF = {"Planned-work index — blocked or forbidden paths": "github.event_name == 'pull_request'"}
_STATIC_INSTALL = 'python -m pip install -e ".[analysis,dev,segmentation,pdf,ocr,geo]"'


def _static_problems(jobs: dict) -> list[str]:
    """The `static` job (R668): on the legs' condition, blocking, the legs' install line, and every gate it took over present once and blocking."""
    job = jobs.get("static")
    if not isinstance(job, dict):
        return ["static: the job that runs the static checks is missing (R668): lint, planned-work index, i18n, migrations, mypy, bandit and pip-audit would run nowhere"]
    found: list[str] = []
    if job.get("if") != _GATE or job.get("needs") != ["changes"] or job.get("continue-on-error"):
        found.append(f"static: the job must run on every push and every pull request but a docs-only one, and must block (`if: {_GATE}`, `needs: [changes]`, no continue-on-error)")
    if "strategy" in job:
        found.append("static: the job must not be a matrix (each gate runs once)")
    steps = job.get("steps") or []
    if not any(_STATIC_INSTALL in str(s.get("run") or "") for s in steps):
        found.append(f"static: the install must be the legs' own line `{_STATIC_INSTALL}` (mypy and pip-audit must see the environment the suite runs on)")
    for prefix, piece in _STATIC_GATES:
        mine = [s for s in steps if str(s.get("name") or "").startswith(prefix)]
        if len(mine) != 1:
            found.append(f"static: exactly one step named `{prefix}...` expected, found {len(mine)}")
            continue
        step = mine[0]
        if piece not in str(step.get("run") or ""):
            found.append(f"static: the step `{prefix}...` must run `{piece}`, it runs {step.get('run')!r}")
        if step.get("continue-on-error"):
            found.append(f"static: the step `{prefix}...` must block, it says continue-on-error")
        want_if = _STATIC_GATE_IF.get(prefix)
        if step.get("if") != want_if:
            found.append(f"static: the step `{prefix}...` must say {'no `if`' if want_if is None else f'exactly `if: {want_if}`'}, it says {step.get('if')!r}")
        # the gate's own command line (the index step's `git fetch ... || true` before it is a best-effort fetch, not the gate)
        gate_lines = [line for line in str(step.get("run") or "").splitlines() if piece in line]
        if any(re.search(r"\|\|\s*(true|:)(\s|$)|\|\|\s*exit\s+0", line) for line in gate_lines):
            found.append(f"static: the step `{prefix}...` swallows its own failure (`|| true`): a gate must fail the job")
    return found


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _leg_names(job: dict) -> list[str]:
    legs = job["strategy"]["matrix"]["shard"]
    return [str(job.get("name", "")).replace("${{ matrix.shard }}", str(leg)) for leg in legs]


def _upload_problems(matrix_job: str, steps: list[dict], pytest_at: list[int]) -> list[str]:
    """The step that keeps a leg's junit report (R433): once, pinned, on red as well as green, never red itself, named per leg and per job, after pytest and before the skip summary."""
    uploads = [i for i, s in enumerate(steps) if "upload-artifact" in str(s.get("uses") or "")]
    if len(uploads) != 1:
        return [f"{matrix_job}: exactly one step that uploads the leg's junit report expected (the source of the next cost table), found {len(uploads)}"]
    step = steps[uploads[0]]
    with_ = step.get("with") or {}
    found: list[str] = []
    if not re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", str(step.get("uses") or "")):
        found.append(f"{matrix_job}: the upload step must be pinned to a full commit sha, as every action of ci.yml is ({step.get('uses')!r})")
    if step.get("if") != "always()":
        found.append(f"{matrix_job}: the upload step must say `if: always()` (a red leg's seconds are as good as a green one's), it says {step.get('if')!r}")
    if step.get("continue-on-error") is not True:
        found.append(f"{matrix_job}: the upload step must say `continue-on-error: true` (an upload never turns a leg red), it says {step.get('continue-on-error')!r}")
    if with_.get("path") != _REPORT:
        found.append(f"{matrix_job}: the upload step must upload `{_REPORT}`, the report the pytest step writes, it uploads {with_.get('path')!r}")
    if with_.get("name") != _ARTIFACT % matrix_job:
        found.append(f"{matrix_job}: the artifact name must be `{_ARTIFACT % matrix_job}`: one per leg and per job, or the legs overwrite each other ({with_.get('name')!r})")
    retention = with_.get("retention-days")
    if not isinstance(retention, int) or isinstance(retention, bool) or retention < 1:
        found.append(f"{matrix_job}: the upload step must say `retention-days` (a whole number of days), or the report stays for the repository's default of 90 ({retention!r})")
    if with_.get("overwrite") is not True:
        found.append(f"{matrix_job}: the upload step must say `overwrite: true`, or a re-run of a leg fails on the name its first run took ({with_.get('overwrite')!r})")
    summary_at = [i for i, s in enumerate(steps) if "ci_skip_summary" in str(s.get("run") or "")]
    if len(pytest_at) == 1 and not (pytest_at[0] < uploads[0] and summary_at and uploads[0] < summary_at[0]):
        found.append(f"{matrix_job}: the upload step must come after the pytest step and before the skip-summary step, which stays the job's last step")
    return found


#: The job-level condition of a sharded job (R462): not the weekly run, and not a docs-only pull request (the `changes` job decides that; it fails open).
_GATE = "github.event_name != 'schedule' && needs.changes.outputs.docs_only != 'true'"


def _wiring_problems(wf: dict, table: dict) -> list[str]:
    found: list[str] = []
    jobs = wf["jobs"]
    n = table["shards"]
    for matrix_job, (aggregator, required) in _AGGREGATORS.items():
        job = jobs.get(matrix_job) or {}
        legs = ((job.get("strategy") or {}).get("matrix") or {}).get("shard")
        if legs != list(range(1, n + 1)):
            found.append(f"{matrix_job}: the matrix must be `shard: {list(range(1, n + 1))}` (the table's N = {n}), it is {legs!r}")
            continue
        if (job.get("strategy") or {}).get("fail-fast") is not False:
            found.append(f"{matrix_job}: `fail-fast: false` is missing: a red leg would cancel the others and hide what they found")
        if job.get("if") != _GATE or job.get("needs") != ["changes"] or job.get("continue-on-error"):
            found.append(f"{matrix_job}: the job must run on every push and every pull request but a docs-only one, and must block (`if: {_GATE}`, `needs: [changes]`, no continue-on-error)")
        names = _leg_names(job)
        if len(set(names)) != n or required in names or matrix_job in names or "${{" in " ".join(names):
            found.append(f"{matrix_job}: each leg needs its own name that is not the required check `{required}` ({names})")
        if any(f" of {n}" not in name for name in names):
            found.append(f"{matrix_job}: each leg's name must say `of {n}` (the table's N), or a changed count leaves legs named `shard 4 of 3` ({names})")
        steps = job.get("steps") or []
        plans = [i for i, s in enumerate(steps) if "ci_shard.py" in str(s.get("run") or "")]
        pytest_at = [i for i, s in enumerate(steps) if "pytest" in str(s.get("run") or "")]
        if len(plans) != 1 or len(pytest_at) != 1:
            found.append(f"{matrix_job}: exactly one plan step and one pytest step expected, found {len(plans)} and {len(pytest_at)}")
        else:
            plan = steps[plans[0]]
            if str(plan.get("run") or "").strip() != _PLAN % n:
                found.append(f"{matrix_job}: the plan step must run exactly `{_PLAN % n}`, it runs {plan.get('run')!r}")
            if plan.get("if") is not None or plan.get("continue-on-error"):
                found.append(f"{matrix_job}: the plan step must be unconditional and blocking, or a leg could run on no list")
            if plans[0] + 1 != pytest_at[0]:
                found.append(f"{matrix_job}: the plan step must come straight before the pytest step (step {pytest_at[0]}), it is step {plans[0]}")
            installs = [i for i, s in enumerate(steps) if "pip install -e" in str(s.get("run") or "")]
            if not installs or max(installs) > plans[0]:
                found.append(f"{matrix_job}: the plan step must come after the install (it imports nothing from the project, but the leg's environment is what it plans for)")
        found += _upload_problems(matrix_job, steps, pytest_at)
        aggr = jobs.get(aggregator) or {}
        if aggr.get("name") != required:
            found.append(f"{aggregator}: the aggregator must be named exactly `{required}` (the check branch protection requires), it is {aggr.get('name')!r}")
        if aggr.get("if") != "always() && github.event_name != 'schedule'":
            found.append(f"{aggregator}: `if: always() && github.event_name != 'schedule'` expected (without always() a failed leg SKIPS it, and a skipped required check passes), it is {aggr.get('if')!r}")
        extra = _ALSO_REQUIRED.get(aggregator, [])
        if aggr.get("needs") != [matrix_job, *extra, "changes", "docs-checks"]:
            found.append(f"{aggregator}: must need exactly {[matrix_job, *extra, 'changes', 'docs-checks']} (the docs-only fast path), it needs {aggr.get('needs')!r}")
        if aggr.get("continue-on-error"):
            found.append(f"{aggregator}: must block")
        asteps = aggr.get("steps") or []
        run = "\n".join(str(s.get("run") or "") for s in asteps)
        env = {k: v for s in asteps for k, v in (s.get("env") or {}).items()}
        want_env = {"LEGS": "${{ needs." + matrix_job + ".result }}", "DOCS_ONLY": "${{ needs.changes.outputs.docs_only }}", "DOCS_CHECKS": "${{ needs.docs-checks.result }}"}
        want_env |= {_ENV_OF[job]: "${{ needs." + job + ".result }}" for job in extra}
        if len(asteps) != 1 or env != want_env or 'test "$LEGS" = "success"' not in run or 'test "$DOCS_ONLY" = "true" && test "$DOCS_CHECKS" = "success"' not in run:
            found.append(f"{aggregator}: one step that takes LEGS from `needs.{matrix_job}.result` and fails unless it is `success` is expected")
        for job in extra:
            if f'test "${_ENV_OF[job]}" = "success"' not in run:
                found.append(f"{aggregator}: its step must fail unless `needs.{job}.result` (${_ENV_OF[job]}) is `success`")
        if any(s.get("continue-on-error") or s.get("if") for s in asteps) or "|| true" in run:
            found.append(f"{aggregator}: its step must not be conditional or advisory")
    # the required names appear once each, on the aggregators
    names = [str(j.get("name", jid)) for jid, j in jobs.items()]
    for _, required in _AGGREGATORS.values():
        if names.count(required) != 1:
            found.append(f"the check `{required}` must be the name of exactly one job, it is the name of {names.count(required)}")
    # the legs of `test` run the suite and nothing else; the static steps are the `static` job (R668)
    for step in (jobs.get("test") or {}).get("steps") or []:
        label = str(step.get("name") or "")
        if step.get("uses") or any(label.startswith(p) for p in _EVERY_LEG):
            continue
        found.append(f"test: the step `{label}` is not one every leg needs: a static step belongs in the `static` job (or add it to _EVERY_LEG in tests/test_ci_shards.py if every leg needs it)")
    found += _static_problems(jobs)
    for step in (jobs.get("core-only") or {}).get("steps") or []:
        if "matrix.shard" in str(step.get("if") or ""):
            found.append(f"core-only: the step `{step.get('name')}` is conditional on the shard: this job has no static steps, every leg is the same")
    return found


def test_the_workflow_wires_the_shards_as_claimed():
    assert _wiring_problems(_workflow(), _TABLE) == []


def _edit(wf: dict, path: str, action) -> dict:
    out = copy.deepcopy(wf)
    action(out["jobs"])
    return out


def _step(jobs: dict, job: str, prefix: str) -> dict:
    return next(s for s in jobs[job]["steps"] if str(s.get("name") or "").startswith(prefix))


def _upload(jobs: dict, job: str) -> dict:
    return next(s for s in jobs[job]["steps"] if "upload-artifact" in str(s.get("uses") or ""))


def _move_upload(jobs: dict, job: str, to_end: bool) -> None:
    steps = jobs[job]["steps"]
    step = steps.pop(next(i for i, s in enumerate(steps) if "upload-artifact" in str(s.get("uses") or "")))
    steps.append(step) if to_end else steps.insert(0, step)


_MUTANTS = {
    "a leg is dropped": (lambda j: j["test"]["strategy"]["matrix"].__setitem__("shard", [1, 2]), "the matrix must be"),
    "a fourth leg": (lambda j: j["core-only"]["strategy"]["matrix"].__setitem__("shard", [1, 2, 3, 4]), "core-only: the matrix must be"),
    "legs numbered from 0": (lambda j: j["test"]["strategy"]["matrix"].__setitem__("shard", [0, 1, 2]), "the matrix must be"),
    "fail-fast comes back": (lambda j: j["test"]["strategy"].__setitem__("fail-fast", True), "fail-fast: false"),
    "fail-fast is gone": (lambda j: j["core-only"]["strategy"].pop("fail-fast"), "fail-fast: false"),
    "the job turns advisory": (lambda j: j["test"].__setitem__("continue-on-error", True), "must block"),
    "the job loses its condition": (lambda j: j["core-only"].pop("if"), "must run on every push"),
    "the job skips on every run": (lambda j: j["test"].__setitem__("if", "false"), "must run on every push"),
    "the job forgets to wait for the fast-path decision": (lambda j: j["core-only"].pop("needs"), "must run on every push"),
    "a leg is named like the required check": (lambda j: j["test"].__setitem__("name", "test"), "own name"),
    "all legs share one name": (lambda j: j["core-only"].__setitem__("name", "Core-only"), "own name"),
    "the legs say another N": (lambda j: j["test"].__setitem__("name", j["test"]["name"].replace(" of 3", " of 4")), "must say `of 3`"),
    "the plan step is gone": (lambda j: j["test"]["steps"].remove(_step(j, "test", "Plan this shard")), "exactly one plan step"),
    "the plan step names another N": (lambda j: _step(j, "core-only", "Plan this shard").__setitem__("run", _PLAN % 4), "must run exactly"),
    "the plan step is advisory": (lambda j: _step(j, "test", "Plan this shard").__setitem__("continue-on-error", True), "unconditional and blocking"),
    "the plan step is conditional": (lambda j: _step(j, "core-only", "Plan this shard").__setitem__("if", "matrix.shard == 1"), "unconditional and blocking"),
    "the plan step moves away from pytest": (
        lambda j: j["test"]["steps"].insert(0, j["test"]["steps"].pop(next(i for i, s in enumerate(j["test"]["steps"]) if str(s.get("name")).startswith("Plan this shard")))),
        "straight before",
    ),
    "the aggregator is renamed": (lambda j: j["test-all"].__setitem__("name", "tests"), "must be named exactly"),
    "the aggregator loses always()": (lambda j: j["core-only-all"].__setitem__("if", "github.event_name != 'schedule'"), "always()"),
    "the aggregator needs nothing": (lambda j: j["test-all"].pop("needs"), "must need exactly"),
    "the aggregator needs the other job": (lambda j: j["test-all"].__setitem__("needs", ["core-only"]), "must need exactly"),
    "the aggregator forgets the fast path": (lambda j: j["test-all"].__setitem__("needs", ["test"]), "must need exactly"),
    "the aggregator drops the fast-path clause": (lambda j: j["core-only-all"]["steps"][0].__setitem__("run", 'test "$LEGS" = "success"'), "fails unless it is `success`"),
    "the aggregator stops testing the result": (lambda j: j["test-all"]["steps"][0].__setitem__("run", "echo $LEGS"), "fails unless it is `success`"),
    "the aggregator reads another result": (lambda j: j["core-only-all"]["steps"][0]["env"].__setitem__("LEGS", "${{ needs.test.result }}"), "fails unless it is `success`"),
    "the aggregator swallows the failure": (lambda j: j["test-all"]["steps"][0].__setitem__("continue-on-error", True), "not be conditional or advisory"),
    "the aggregator is advisory": (lambda j: j["core-only-all"].__setitem__("continue-on-error", True), "must block"),
    "the aggregator goes": (lambda j: j.pop("test-all"), "must be named exactly"),
    "a second job takes the required name": (lambda j: j.__setitem__("dup", {"name": "test", "steps": []}), "must be the name of exactly one job"),
    "mypy moves back into the legs": (lambda j: j["test"]["steps"].append(j["static"]["steps"].pop(j["static"]["steps"].index(_step(j, "static", "Type check")))), "belongs in the `static` job"),
    "a new static step lands in the legs": (lambda j: j["test"]["steps"].append({"name": "A new scanner", "run": "echo scan"}), "belongs in the `static` job"),
    "the static job goes": (lambda j: j.pop("static"), "static: the job that runs the static checks is missing"),
    "the static job turns advisory": (lambda j: j["static"].__setitem__("continue-on-error", True), "static: the job must run on every push"),
    "the static job skips on every run": (lambda j: j["static"].__setitem__("if", "false"), "static: the job must run on every push"),
    "the static job becomes a matrix": (lambda j: j["static"].__setitem__("strategy", {"matrix": {"shard": [1, 2]}}), "must not be a matrix"),
    "the static job installs less": (lambda j: _step(j, "static", "Install").__setitem__("run", 'python -m pip install -e ".[dev]"'), "the legs' own line"),
    "mypy is dropped": (lambda j: j["static"]["steps"].remove(_step(j, "static", "Type check")), "`Type check (mypy, BLOCKING)...` expected, found 0"),
    "mypy turns advisory": (lambda j: _step(j, "static", "Type check").__setitem__("continue-on-error", True), "must block, it says continue-on-error"),
    "bandit stops scanning src": (lambda j: _step(j, "static", "SAST").__setitem__("run", "true"), "must run `bandit -r src/ -ll`"),
    "the blocking planned-work index is dropped": (lambda j: j["static"]["steps"].remove(_step(j, "static", "Planned-work index — blocked")), "found 0"),
    "a static step keeps the leg condition": (lambda j: _step(j, "static", "Migration drift").__setitem__("if", "matrix.shard == 1"), "must say no `if`"),
    "mypy never runs": (lambda j: _step(j, "static", "Type check").__setitem__("if", "false"), "must say no `if`"),
    "the blocking index runs on pushes only": (lambda j: _step(j, "static", "Planned-work index — blocked").__setitem__("if", "github.event_name == 'push'"), "must say exactly `if:"),
    "the blocking index loses --strict": (lambda j: _step(j, "static", "Planned-work index — blocked").__setitem__("run", 'python scripts/planned.py --diff "origin/main"'), "must run `--strict`"),
    "mypy swallows its failure": (lambda j: _step(j, "static", "Type check").__setitem__("run", "python -m mypy src/ || true"), "swallows its own failure"),
    "the t() gate loses its ceiling": (lambda j: _step(j, "static", "i18n unkeyed t()").__setitem__("run", "python scripts/i18n_report.py"), "must run `--max-unkeyed-t-calls 0`"),
    "the required check stops needing the static job": (lambda j: j["test-all"].__setitem__("needs", ["test", "changes", "docs-checks"]), "test-all: must need exactly"),
    "the required check stops reading the static result": (lambda j: j["test-all"]["steps"][0]["env"].pop("STATIC"), "fails unless it is `success`"),
    "the required check ignores a red static job": (
        lambda j: j["test-all"]["steps"][0].__setitem__("run", j["test-all"]["steps"][0]["run"].replace('test "$STATIC" = "success"', "true")),
        'must fail unless `needs.static.result`',
    ),
    "a core-only step is gated on the shard": (lambda j: _step(j, "core-only", "Boot check").__setitem__("if", "matrix.shard == 1"), "conditional on the shard"),
    "the junit upload is gone": (lambda j: j["test"]["steps"].remove(_upload(j, "test")), "exactly one step that uploads"),
    "the junit upload is gone from core-only": (lambda j: j["core-only"]["steps"].remove(_upload(j, "core-only")), "core-only: exactly one step that uploads"),
    "a second junit upload": (lambda j: j["test"]["steps"].append(copy.deepcopy(_upload(j, "test"))), "exactly one step that uploads"),
    "the junit upload is unconditional": (lambda j: _upload(j, "test").pop("if"), "`if: always()`"),
    "the junit upload turns the leg red": (lambda j: _upload(j, "core-only").pop("continue-on-error"), "`continue-on-error: true`"),
    "the junit upload is pinned to a tag": (lambda j: _upload(j, "test").__setitem__("uses", "actions/upload-artifact@v7"), "full commit sha"),
    "the junit upload reads another file": (lambda j: _upload(j, "core-only")["with"].__setitem__("path", "${{ runner.temp }}/other.xml"), "the report the pytest step writes"),
    "the legs share one artifact name": (lambda j: _upload(j, "test")["with"].__setitem__("name", "junit-test-shard"), "one per leg and per job"),
    "the two jobs share their artifact names": (lambda j: _upload(j, "core-only")["with"].__setitem__("name", _ARTIFACT % "test"), "one per leg and per job"),
    "the junit upload has no retention": (lambda j: _upload(j, "test")["with"].pop("retention-days"), "`retention-days`"),
    "the junit upload cannot be re-run": (lambda j: _upload(j, "core-only")["with"].pop("overwrite"), "`overwrite: true`"),
    "the junit upload comes after the skip summary": (lambda j: _move_upload(j, "test", True), "before the skip-summary step"),
    "the junit upload comes before pytest": (lambda j: _move_upload(j, "core-only", False), "after the pytest step"),
}


@pytest.mark.parametrize("label", sorted(_MUTANTS))
def test_the_wiring_checker_names_each_broken_property(label):
    action, says = _MUTANTS[label]
    problems = _wiring_problems(_edit(_workflow(), label, action), _TABLE)
    assert any(says in p for p in problems), (label, problems)


@pytest.mark.skipif(shutil.which("bash") is None, reason="the aggregator step is a bash script")
@pytest.mark.parametrize("aggregator", sorted(a for a, _ in _AGGREGATORS.values()))
@pytest.mark.parametrize(
    ("result", "passes"),
    [("success", True), ("failure", False), ("cancelled", False), ("skipped", False), ("", False), ("Success", False), ("success failure", False)],
)
def test_an_aggregator_is_green_only_when_every_leg_succeeded(aggregator, result, passes):
    """GitHub reports a matrix job's result as `success` only if EVERY leg succeeded; a cancelled or skipped leg is `cancelled` / `skipped`, never `success`.

    The aggregator's own script is run here with each value, so a loosened comparison (`!= failure`, a prefix match, a swallowed exit code) is caught."""
    steps = _workflow()["jobs"][aggregator]["steps"]
    assert len(steps) == 1
    others = {_ENV_OF[job]: "success" for job in _ALSO_REQUIRED.get(aggregator, [])}
    done = subprocess.run(["bash", "-e", "-c", steps[0]["run"]], env={**os.environ, **others, "LEGS": result}, capture_output=True, text=True, timeout=60)
    assert (done.returncode == 0) is passes, (aggregator, result, done.returncode, done.stdout, done.stderr)
    # the same values for each other job the aggregator requires (R668: the static checks), with every leg green
    for var in others:
        done = subprocess.run(["bash", "-e", "-c", steps[0]["run"]], env={**os.environ, **others, var: result, "LEGS": "success"}, capture_output=True, text=True, timeout=60)
        assert (done.returncode == 0) is passes, (aggregator, var, result, done.returncode, done.stdout, done.stderr)


@pytest.mark.skipif(shutil.which("bash") is None, reason="the aggregator step is a bash script")
def test_a_red_static_job_is_green_only_on_the_docs_only_fast_path():
    """R668: on a docs-only pull request the legs and the static job are skipped and docs-checks decides; anywhere else a skipped or red static job is red."""
    run = _workflow()["jobs"]["test-all"]["steps"][0]["run"]
    def ok(**env: str) -> bool:
        base = {"LEGS": "success", "STATIC": "success", "DOCS_ONLY": "false", "DOCS_CHECKS": "skipped"}
        return subprocess.run(["bash", "-e", "-c", run], env={**os.environ, **base, **env}, capture_output=True, timeout=60).returncode == 0
    assert ok()
    assert not ok(STATIC="failure") and not ok(STATIC="skipped") and not ok(STATIC="cancelled")
    assert ok(LEGS="skipped", STATIC="skipped", DOCS_ONLY="true", DOCS_CHECKS="success")
    assert not ok(LEGS="skipped", STATIC="skipped", DOCS_ONLY="true", DOCS_CHECKS="failure")


def test_a_table_for_another_n_is_named():
    problems = _wiring_problems(_workflow(), {**_TABLE, "shards": 4})
    assert any("the matrix must be" in p for p in problems), problems
