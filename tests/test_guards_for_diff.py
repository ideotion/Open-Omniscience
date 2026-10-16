"""``scripts/guards_for_diff.py`` picks the tests to run before a first push (2026-10-16).

Built on a throwaway git repository with a ``main``, a feature branch that merged ``main`` once, a working tree with an
uncommitted change, and a workflow file carrying the ratchet's ceiling. Each assertion is about which files are picked and why,
so a change to the rule that loses a group (or picks the whole suite) fails here and not on the next branch that needed it.
"""

from __future__ import annotations

import shlex
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
    # a star-led walk on a repository-rooted receiver judges the tree (a suffix filter follows); on a scratch directory it does not
    write(r, "tests/test_walks_root_star.py", "ALL = [p for p in (_ROOT / 'src').rglob(\"*\") if p.suffix == '.py']\n")
    write(r, "tests/test_walks_a_scratch_dir.py", "ALL = list(tmp_path.rglob(\"*\"))\n")
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


def plan(r: Path, base: str = "main", since: str | None = None) -> g.Plan:
    return g.build_plan(r, base, since)


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
    assert p.tree_wide == [
        "tests/scale/test_walks_deep.py",
        "tests/test_walks_os.py",
        "tests/test_walks_root_star.py",  # rglob("*") on the repository root, a suffix filter after it
        "tests/test_walks_src.py",
    ]  # tests/test_walks_a_scratch_dir.py walks a scratch directory and is not a guard of the tree
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
        "tests/test_walks_root_star.py",
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


def test_paths_with_a_space_or_a_non_ascii_letter_are_picked_and_printed_quoted(repo: Path) -> None:
    """Without ``-z`` git prints ``"tests/test_caf\\303\\251.py"`` and the quoted text matches no file: the test was dropped silently."""
    git(repo, "checkout", "-q", "-b", "feature")
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_café.py")
    write(repo, "tests/test_with space.py")
    commit(repo, "main adds awkward names")
    git(repo, "checkout", "-q", "feature")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge main", "main")
    write(repo, "tests/test_ünïcode_own.py")  # untracked
    write(repo, "tests/test_own space.py")
    p = plan(repo)
    assert p.main_added == ["tests/test_café.py", "tests/test_with space.py"]
    assert p.own == ["tests/test_own space.py", "tests/test_ünïcode_own.py"]
    printed = g.render(p).splitlines()[-1]
    assert "'tests/test_with space.py'" in printed and "tests/test_café.py" in printed
    assert shlex.split(printed)[-len(p.files()) :] == p.files()  # the line pastes back into a shell as the same argv


def test_a_changed_helper_a_node_test_and_a_data_file_pick_the_tests_that_name_them(repo: Path) -> None:
    write(repo, "tests/_util.py", "def helper(): ...\n")
    write(repo, "tests/sub/data.json", "{}\n")
    write(repo, "tests/probe_node_test.js", "// node test\n")
    write(repo, "tests/test_uses_util.py", "from tests._util import helper\n")
    write(repo, "tests/test_uses_utility_only.py", "from tests._utility import other\n")  # a longer name is not the same name
    write(repo, "tests/test_runs_node.py", "NODE = 'probe_node_test.js'\n")
    write(repo, "tests/test_reads_data.py", "DATA = 'sub/data.json'\n")
    commit(repo, "support files and their users")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "tests/_util.py", "def helper(): return 1\n")
    write(repo, "tests/sub/data.json", '{"a": 1}\n')
    write(repo, "tests/probe_node_test.js", "// edited\n")
    write(repo, "tests/unused_helper.py", "x = 1\n")  # untracked, named by no test
    p = plan(repo)
    assert p.own == [] and p.main_added == []  # none of them is a test module
    assert p.support == {
        "tests/_util.py": ["tests/test_uses_util.py"],
        "tests/probe_node_test.js": ["tests/test_runs_node.py"],
        "tests/sub/data.json": ["tests/test_reads_data.py"],
        "tests/unused_helper.py": [],
    }
    assert {"tests/test_uses_util.py", "tests/test_runs_node.py", "tests/test_reads_data.py"} <= set(p.files())
    assert "tests/test_uses_utility_only.py" not in p.files()
    assert "NONE named it" in g.render(p)  # an empty pick is said, not printed as if it were fine


def test_a_deleted_helper_still_picks_the_tests_that_import_it(repo: Path) -> None:
    write(repo, "tests/_util.py")
    write(repo, "tests/test_uses_util.py", "from tests._util import helper\n")
    commit(repo, "helper")
    git(repo, "checkout", "-q", "-b", "feature")
    git(repo, "rm", "-q", "tests/_util.py")
    assert plan(repo).support == {"tests/_util.py": ["tests/test_uses_util.py"]}


def test_a_helper_main_deleted_still_picks_the_tests_that_import_it(repo: Path) -> None:
    write(repo, "tests/_util.py")
    write(repo, "tests/test_uses_util.py", "from tests._util import helper\n")
    commit(repo, "helper")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "tests/test_own.py")
    commit(repo, "own")
    git(repo, "checkout", "-q", "main")
    git(repo, "rm", "-q", "tests/_util.py")
    commit(repo, "main deletes the helper")
    git(repo, "checkout", "-q", "feature")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge main", "main")
    assert plan(repo).support == {"tests/_util.py": ["tests/test_uses_util.py"]}  # it fails on import here, whoever deleted the helper


def test_a_changed_nested_conftest_picks_the_tests_below_it_and_a_root_one_says_the_whole_suite(repo: Path) -> None:
    write(repo, "tests/sub/test_a.py")
    write(repo, "tests/sub/deeper/test_b.py")
    write(repo, "tests/subtle/test_c.py")  # a sibling whose name starts the same is not below tests/sub
    commit(repo, "tree")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "tests/sub/conftest.py", "# changed\n")
    p = plan(repo)
    assert p.scoped == {"tests/sub/conftest.py": ["tests/sub/deeper/test_b.py", "tests/sub/test_a.py"]}
    assert not p.conftest_changed
    assert "tests/subtle/test_c.py" not in p.files() and "tests/sub/test_a.py" in p.files()
    write(repo, "conftest.py", "# repository root\n")
    p = plan(repo)
    assert p.conftest_changed and "whole suite" in g.render(p)


def test_an_init_file_scopes_its_directory_like_a_conftest(repo: Path) -> None:
    write(repo, "tests/sub/test_a.py")
    commit(repo, "tree")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "tests/sub/__init__.py", "")
    assert plan(repo).scoped == {"tests/sub/__init__.py": ["tests/sub/test_a.py"]}
    write(repo, "tests/__init__.py", "")
    assert plan(repo).conftest_changed  # a package root changes every import path


def test_a_conftest_main_changed_reaches_the_note_through_the_merge(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "tests/test_own.py")
    commit(repo, "own")
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/conftest.py", "# main changed the fixtures\n")
    commit(repo, "main edits conftest")
    git(repo, "checkout", "-q", "feature")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge main", "main")
    assert plan(repo).conftest_changed  # every test sees a fixture main changed, whoever edited it


def test_a_merge_with_main_as_the_first_parent_still_finds_main_s_tests(repo: Path) -> None:
    """``git checkout --detach main && git merge --no-ff feat`` puts main's tip first: reading the second parent as main's line
    picked the branch's own test as main's and never picked main's."""
    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, "tests/test_own.py")
    commit(repo, "own")
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_from_main.py")
    commit(repo, "main moves")
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat into main's tip", "feat")
    git(repo, "branch", "-f", "feat", "HEAD")
    git(repo, "checkout", "-q", "feat")
    git(repo, "update-ref", "refs/heads/base", "main")  # the base is main as it was before the merge: the merge is not in it
    p = plan(repo, "base")
    assert p.main_added == ["tests/test_from_main.py"]
    assert p.own == ["tests/test_own.py"]


def test_a_rebased_branch_finds_main_s_tests_only_through_since(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, "tests/test_own.py")
    commit(repo, "own")
    before_rebase = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_from_main.py")
    commit(repo, "main moves")
    git(repo, "checkout", "-q", "feat")
    git(repo, "rebase", "-q", "main")
    assert plan(repo).main_added == []  # no merge, so the base alone cannot tell which of its tests are new to this branch
    p = plan(repo, since=before_rebase)
    assert p.main_added == ["tests/test_from_main.py"] and p.own == ["tests/test_own.py"] and p.since == before_rebase
    assert "since " + before_rebase in g.render(p)


def test_since_with_a_ref_that_does_not_exist_is_named(repo: Path) -> None:
    with pytest.raises(g.PlanError, match="no such ref `nowhere` for --since"):
        plan(repo, since="nowhere")


def test_merges_already_inside_the_base_are_not_news_to_a_branch_cut_after_them(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "side")
    write(repo, "tests/test_side.py")
    commit(repo, "side")
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_main_line.py")
    commit(repo, "main line")
    git(repo, "merge", "-q", "--no-ff", "-m", "main merges side", "side")
    git(repo, "checkout", "-q", "-b", "feat")
    assert plan(repo).main_added == []  # both parents of that merge are in the base; the branch has merged nothing


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
