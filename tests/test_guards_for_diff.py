"""``scripts/guards_for_diff.py`` picks the tests to run before a first push (2026-10-16).

Built on a throwaway git repository with a ``main``, a feature branch that merged ``main`` once, a working tree with an
uncommitted change, and a workflow file carrying the ratchet's ceiling. Each assertion is about which files are picked and why,
so a change to the rule that loses a group (or picks the whole suite) fails here and not on the next branch that needed it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import guards_for_diff as g  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

CI = """jobs:
  test:
    steps:
      - name: Lint - style non-growth ratchet (may only be lowered)
        run: python scripts/ruff_ratchet.py --max 417
"""


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def write(repo: Path, rel: str, text: str = "x = 1\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, ".github/workflows/ci.yml", CI)
    write(r, "src/mod.py")
    write(r, "tests/conftest.py", "")
    write(r, "tests/test_plain.py")
    write(r, "tests/test_walks_src.py", "import pathlib\nFILES = list(pathlib.Path('src').rglob(\"*.py\"))\n")
    write(r, "tests/test_walks_os.py", "import os\nLIST = list(os.walk('src'))\n")
    write(r, "tests/scale/test_walks_deep.py", "import os\nLIST = list(os.walk('src'))\n")
    write(r, "tests/test_mentions_globs_only_data.py", "import pathlib\nLIST = list(pathlib.Path('data').glob('*.json'))\n")
    write(r, "tests/test_removed_by_main.py")
    write(r, "tests/test_shared.py")
    commit(r, "base")
    return r


def feature_with_merged_main(r: Path) -> None:
    """main gains a new test, edits an old one, adds a non-test file under tests/ and deletes a test; the branch merges it."""
    git(r, "checkout", "-q", "-b", "feature")
    write(r, "tests/sub/test_deep.py")  # a test below tests/ is collected too
    write(r, "tests/sub/helper.py")  # a helper is not
    write(r, "tests/probe_test.py")  # the other pattern pytest collects (python_files in pyproject.toml)
    write(r, "tests/test_own_committed.py")
    write(r, "tests/test_shared.py", "x = 'edited on the branch only'\n")  # main never touches it
    commit(r, "own commit")
    git(r, "checkout", "-q", "main")
    write(r, "tests/test_from_main.py")
    write(r, "tests/test_plain.py", "x = 2\n")
    write(r, "tests/data.json", "{}\n")
    git(r, "rm", "-q", "tests/test_removed_by_main.py")
    commit(r, "main moves")
    git(r, "checkout", "-q", "feature")
    git(r, "merge", "-q", "--no-ff", "-m", "merge main", "main")


def plan(r: Path, base: str = "main") -> g.Plan:
    return g.build_plan(r, base)


def test_the_tests_main_added_are_picked_apart_from_the_branch_s_own(repo: Path) -> None:
    feature_with_merged_main(repo)
    p = plan(repo)
    assert p.main_added == ["tests/test_from_main.py", "tests/test_plain.py"]
    assert p.own == [
        "tests/probe_test.py",
        "tests/sub/test_deep.py",
        "tests/test_own_committed.py",
        "tests/test_shared.py",
    ]  # a branch edit is not "main's" however the diff is read; helpers are not tests


def test_a_file_main_deleted_a_data_file_and_an_unchanged_test_are_not_picked(repo: Path) -> None:
    feature_with_merged_main(repo)
    everything = plan(repo).files()
    assert "tests/test_removed_by_main.py" not in everything  # gone from the tree, so there is nothing to run
    assert "tests/data.json" not in everything  # not a test module
    assert "tests/conftest.py" not in everything
    assert "tests/test_mentions_globs_only_data.py" not in everything  # globs data, not the tree


def test_a_test_main_added_and_this_branch_then_removed_is_not_picked(repo: Path) -> None:
    feature_with_merged_main(repo)
    git(repo, "rm", "-q", "tests/test_from_main.py")  # in the merge's diff, gone from the tree: pytest would error on it
    assert "tests/test_from_main.py" not in plan(repo).files()
    assert plan(repo).main_added == ["tests/test_plain.py"]


def test_uncommitted_and_untracked_tests_count_as_the_branch_s_own(repo: Path) -> None:
    feature_with_merged_main(repo)
    write(repo, "tests/test_own_committed.py", "x = 3\n")  # tracked, modified, not committed
    write(repo, "tests/test_brand_new.py")  # untracked
    assert plan(repo).own == [
        "tests/probe_test.py",
        "tests/sub/test_deep.py",
        "tests/test_brand_new.py",
        "tests/test_own_committed.py",
        "tests/test_shared.py",
    ]


def test_the_tree_walking_tests_are_picked_by_what_they_do(repo: Path) -> None:
    p = plan(repo)
    assert p.tree_wide == ["tests/scale/test_walks_deep.py", "tests/test_walks_os.py", "tests/test_walks_src.py"]
    assert p.main_added == [] and p.own == []  # an untouched branch has only the guards


def test_every_picked_file_is_listed_once_in_the_order_the_groups_are_shown(repo: Path) -> None:
    feature_with_merged_main(repo)
    write(repo, "tests/test_walks_src.py", "import pathlib\nFILES = list(pathlib.Path('src').rglob(\"*.py\"))\n# edited\n")
    files = plan(repo).files()
    assert len(files) == len(set(files))
    # main's tests first, then the branch's own, then the guards, each file once
    assert files == [
        "tests/test_from_main.py",
        "tests/test_plain.py",
        "tests/probe_test.py",
        "tests/sub/test_deep.py",
        "tests/test_own_committed.py",
        "tests/test_shared.py",
        "tests/test_walks_src.py",  # edited on the branch, so it is listed with the branch's own
        "tests/scale/test_walks_deep.py",
        "tests/test_walks_os.py",
    ]


def test_a_base_that_moved_on_without_being_merged_is_named_and_its_new_tests_are_not_picked(repo: Path) -> None:
    feature_with_merged_main(repo)
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_later_on_main.py")
    commit(repo, "main moves again")
    git(repo, "checkout", "-q", "feature")
    p = plan(repo)
    assert p.behind == 1
    assert "tests/test_later_on_main.py" not in p.files()  # it is not in this tree
    assert "WARNING" in g.render(p) and "git merge main" in g.render(p)


def test_a_branch_that_never_merged_anything_picks_nothing_from_main(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "solo")
    write(repo, "tests/test_solo.py")
    commit(repo, "solo")
    p = plan(repo)
    assert p.main_added == [] and p.own == ["tests/test_solo.py"] and p.behind == 0


def test_a_changed_conftest_says_to_run_the_whole_suite(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "solo")
    write(repo, "tests/conftest.py", "# changed\n")
    p = plan(repo)
    assert p.conftest_changed and "whole suite" in g.render(p)
    assert not plan_without_conftest_change(repo).conftest_changed


def plan_without_conftest_change(r: Path) -> g.Plan:
    git(r, "checkout", "-q", "tests/conftest.py")
    return plan(r)


def test_the_ratchet_ceiling_is_read_from_the_workflow_not_copied(repo: Path) -> None:
    assert plan(repo).ceiling == 417
    write(repo, ".github/workflows/ci.yml", CI.replace("417", "399"))
    p = plan(repo)
    assert p.ceiling == 399
    assert [sys.executable, "scripts/ruff_ratchet.py", "--max", "399"] in g.commands(p)


@pytest.mark.parametrize("text", ["jobs: {}\n", CI + "      - name: again\n        run: python scripts/ruff_ratchet.py --max 416\n"])
def test_no_ceiling_or_two_ceilings_is_a_named_stop_not_a_guess(repo: Path, text: str) -> None:
    write(repo, ".github/workflows/ci.yml", text)
    with pytest.raises(g.PlanError, match="ruff_ratchet"):
        plan(repo)


def test_a_base_that_does_not_exist_is_named(repo: Path) -> None:
    with pytest.raises(g.PlanError, match="no such base `origin/nowhere`"):
        plan(repo, "origin/nowhere")


def test_the_commands_are_the_ci_order_lint_ratchet_then_the_picked_tests(repo: Path) -> None:
    feature_with_merged_main(repo)
    steps = g.commands(plan(repo))
    assert steps[0][1:4] == ["-m", "ruff", "check"] and "--select=F,B" in steps[0]
    assert steps[1][1:] == ["scripts/ruff_ratchet.py", "--max", "417"]
    assert steps[2][1:4] == ["-m", "pytest", "-q"] and "tests/test_from_main.py" in steps[2]


def test_run_exits_nonzero_when_any_step_fails_and_still_runs_the_rest(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake(step: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        seen.append(step)
        return subprocess.CompletedProcess(step, 1 if "ruff_ratchet.py" in " ".join(step) else 0)

    monkeypatch.setattr(g.subprocess, "run", fake)
    p = g.Plan(base="main", ceiling=417, behind=0, own=["tests/test_plain.py"])
    assert g.run(p, repo) == 1
    assert len(seen) == len(g.commands(p)) == 3  # the pytest step ran after the ratchet failed


def test_the_picked_files_of_this_repository_exist_and_include_the_walkers() -> None:
    """On the real tree the rule finds the walkers by pattern, and every file it names exists (a regression that makes it print
    nothing, or a path pytest cannot open, is the way this tool dies)."""
    found = g.tree_wide_guards(ROOT)
    assert len(found) >= 20
    assert "tests/test_repo_invariants.py" in found or "tests/test_network_consent.py" in found
    assert all((ROOT / path).is_file() for path in found)
