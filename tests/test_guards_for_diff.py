"""``scripts/guards_for_diff.py`` picks the tests to run before a first push (2026-10-16).

Built on a throwaway git repository with a ``main``, a feature branch that merged ``main`` once, a working tree with an
uncommitted change, and a workflow file carrying the ratchet's ceiling. Each assertion is about which files are picked and why,
so a change to the rule that loses a group (or picks the whole suite) fails here and not on the next branch that needed it.
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
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
    # a one-directory walk of the modules (or sub-directories) in a source directory judges every module anyone adds to it
    write(r, "tests/test_globs_with_the_module.py", "import glob\nFILES = glob.glob('src/**/*.py', recursive=True)\n")
    write(r, "tests/test_globs_one_src_dir.py", "ON_DISK = {p.stem for p in (ROOT / 'src' / 'bulletin').glob(\"*.py\")}\n")
    write(r, "tests/test_globs_a_dir_variable.py", "for f in sorted(_PKG.glob('*.py')):\n    pass\n")
    write(r, "tests/test_globs_data_dirs.py", "TREES = [p for p in (_ROOT / 'src').glob(\"*/data\")]\n")
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
        "tests/test_globs_a_dir_variable.py",  # glob("*.py") on a directory held in a variable
        "tests/test_globs_data_dirs.py",  # glob("*/data"): the directories of src
        "tests/test_globs_one_src_dir.py",  # glob("*.py") on one source directory
        "tests/test_globs_with_the_module.py",  # glob.glob over src
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
        "tests/test_globs_a_dir_variable.py",
        "tests/test_globs_data_dirs.py",
        "tests/test_globs_one_src_dir.py",
        "tests/test_globs_with_the_module.py",
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

    envs: list[dict[str, str]] = []

    def fake(step: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        seen.append(step)
        envs.append(env or {})
        return subprocess.CompletedProcess(step, 1 if "ruff_ratchet.py" in " ".join(step) else 0)

    monkeypatch.setattr(g.subprocess, "run", fake)
    p = g.Plan(base="main", ceiling=417, behind=0, own=["tests/test_plain.py"])
    assert g.run(p, repo) == 1
    assert len(seen) == len(g.commands(p)) == 3  # the pytest step ran after the ratchet failed
    assert all(e["PYTHONPATH"].split(os.pathsep)[0] == str(repo) for e in envs)  # every step runs with the tree it runs in first


def test_the_picked_files_of_this_repository_exist_and_include_the_walkers() -> None:
    """On the real tree the rule finds the walkers by pattern, and every file it names exists (a regression that makes it print
    nothing, or a path pytest cannot open, is the way this tool dies)."""
    found = g.tree_wide_guards(ROOT)
    assert len(found) >= 20
    assert "tests/test_repo_invariants.py" in found or "tests/test_network_consent.py" in found
    assert all((ROOT / path).is_file() for path in found)
    # the guards of ONE source directory, written with a plain glob, were missed by the first pattern (a measured miss)
    for named in (
        "tests/test_runs_log_sinks.py",
        "tests/test_diagnostics_package_split.py",
        "tests/test_clickthrough_b13_leftovers.py",
        "tests/test_packaging_data_files.py",
        "tests/test_sink_sweep_records.py",
    ):
        assert named in found, named


def test_a_merge_made_the_other_way_round_still_finds_the_tests_of_an_earlier_merge(repo: Path) -> None:
    """The first-parent line of ``HEAD`` is main's when the LAST merge was made the other way round, so a walk of that line never visits
    the earlier merge of main into the branch and the tests it brought were lost."""
    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, "tests/test_own.py")
    commit(repo, "own")
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_m1.py")
    commit(repo, "main adds m1")
    git(repo, "checkout", "-q", "feat")
    git(repo, "merge", "-q", "--no-ff", "-m", "feat merges main", "main")
    git(repo, "checkout", "-q", "main")
    write(repo, "tests/test_m2.py")
    commit(repo, "main adds m2")
    git(repo, "checkout", "-q", "--detach", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "main's tip merges feat", "feat")
    git(repo, "branch", "-f", "feat", "HEAD")
    git(repo, "checkout", "-q", "feat")
    git(repo, "update-ref", "refs/heads/base", "main")  # main as it was before that merge
    p = plan(repo, "base")
    assert p.main_added == ["tests/test_m1.py", "tests/test_m2.py"]
    assert p.own == ["tests/test_own.py"]


def test_a_renamed_helper_picks_the_tests_that_still_import_the_old_name(repo: Path) -> None:
    """With rename detection on (git's default, and a user's ``diff.renames``) the rename is listed under its new name only, and the tests
    that import the old one, which fail on import, were not picked."""
    write(repo, "tests/_util.py", "def helper():\n    return 1\n" * 3)
    write(repo, "tests/test_uses_old_name.py", "from tests._util import helper\n")
    commit(repo, "helper")
    git(repo, "checkout", "-q", "-b", "feat")
    git(repo, "mv", "tests/_util.py", "tests/_helpers.py")
    commit(repo, "rename")
    for renames in ("true", "false"):  # the result must not depend on the user's own setting
        git(repo, "config", "diff.renames", renames)
        p = plan(repo)
        assert p.support["tests/_util.py"] == ["tests/test_uses_old_name.py"], renames
        assert "tests/test_uses_old_name.py" in p.files(), renames


def test_a_changed_root_or_tests_conftest_makes_the_pick_the_whole_suite_in_files_and_run(repo: Path) -> None:
    """The whole-suite requirement was a NOTE in the printed plan only: ``--files`` listed a subset and exited 0, and ``--run`` ran the
    subset and said every step passed."""
    git(repo, "checkout", "-q", "-b", "solo")
    write(repo, "conftest.py", "# repository root\n")
    write(repo, "tests/test_own.py")
    p = plan(repo)
    assert p.conftest_changed and p.files() == [g.WHOLE_SUITE]
    assert g.commands(p)[-1][1:] == ["-m", "pytest", "-q", g.WHOLE_SUITE]
    assert f"the pick below is the whole suite ({g.WHOLE_SUITE}/)" in g.render(p)


def test_files_prints_the_whole_suite_when_a_conftest_changed(repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    git(repo, "checkout", "-q", "-b", "solo")
    write(repo, "tests/conftest.py", "# changed\n")
    monkeypatch.setattr(g, "ROOT", repo)
    assert g.main(["--base", "main", "--files"]) == 0
    assert capsys.readouterr().out.split() == [g.WHOLE_SUITE]


def test_a_line_that_is_not_in_the_base_at_all_is_read_with_its_first_parent_as_the_branch(repo: Path) -> None:
    """A merge whose parents are all OUTSIDE the base (another feature line merged into this one) brought the second parent."""
    git(repo, "checkout", "-q", "-b", "side")
    write(repo, "tests/test_side.py")
    commit(repo, "side")
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, "tests/test_own.py")
    commit(repo, "own")
    git(repo, "merge", "-q", "--no-ff", "-m", "feat takes side", "side")
    p = plan(repo)
    assert p.main_added == ["tests/test_side.py"] and p.own == ["tests/test_own.py", "tests/test_side.py"]


def _rename_helper_on_main_and_merge(r: Path) -> None:
    write(r, "tests/_util.py", "def helper():\n    return 1\n" * 3)
    write(r, "tests/test_uses_old_name.py", "from tests._util import helper\n")
    commit(r, "helper")
    git(r, "checkout", "-q", "-b", "feat")
    write(r, "tests/test_own.py")
    commit(r, "own")
    git(r, "checkout", "-q", "main")
    git(r, "mv", "tests/_util.py", "tests/_helpers.py")
    commit(r, "main renames the helper")


@pytest.mark.parametrize("renames", ["true", "false"])
def test_a_helper_main_renamed_picks_the_tests_that_still_import_the_old_name(repo: Path, renames: str) -> None:
    _rename_helper_on_main_and_merge(repo)
    git(repo, "config", "diff.renames", renames)
    git(repo, "checkout", "-q", "feat")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge main", "main")
    assert plan(repo).support["tests/_util.py"] == ["tests/test_uses_old_name.py"]


@pytest.mark.parametrize("renames", ["true", "false"])
def test_a_helper_main_renamed_since_a_rebase_is_found_through_since(repo: Path, renames: str) -> None:
    _rename_helper_on_main_and_merge(repo)
    git(repo, "config", "diff.renames", renames)
    git(repo, "checkout", "-q", "feat")
    before = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "rebase", "-q", "main")
    assert plan(repo, since=before).support["tests/_util.py"] == ["tests/test_uses_old_name.py"]


# ---------------------------------------------------------------------------------------------------------------------------------------
# --onto REF: the merged-tree run (2026-10-28)
# ---------------------------------------------------------------------------------------------------------------------------------------

#: A tree-wide guard main adds after the branch left it: it judges every module under src/.
MAIN_GUARD = """import pathlib


def test_no_bad_files_in_src():
    src = pathlib.Path(__file__).resolve().parent.parent / "src"
    bad = [p.name for p in src.rglob("*.py") if p.name.startswith("bad_")]
    assert not bad, bad
"""


@pytest.fixture()
def clean_repo(tmp_path: Path) -> Path:
    """A repository whose every test file RUNS (the ``repo`` fixture's tree-walking files are text to be searched, not tests)."""
    r = tmp_path / "clean"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, ".github/workflows/ci.yml", CI)
    write(r, "src/mod.py")
    write(r, "tests/conftest.py", "")
    write(r, "tests/test_plain.py", "def test_plain():\n    assert True\n")
    commit(r, "base")
    return r


def add_a_guard_on_main_the_branch_breaks(r: Path, *, branch_touches_src: bool = True) -> None:
    """The branch adds ``src/bad_thing.py`` and its own (green) test; main then adds ``MAIN_GUARD``, which rejects that file.

    On the branch alone nothing is red, and nothing says so: the guard is not in its tree. Merged, it is."""
    git(r, "checkout", "-q", "-b", "feature")
    write(r, "src/bad_thing.py" if branch_touches_src else "docs/notes.md")
    write(r, "tests/test_feature.py", "def test_feature():\n    assert True\n")
    commit(r, "feature work")
    git(r, "checkout", "-q", "main")
    write(r, "tests/test_main_guard.py", MAIN_GUARD)
    commit(r, "main adds a guard")
    git(r, "checkout", "-q", "feature")


def only_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run only the pytest step: the throwaway repository has no ratchet script, and ruff is not a dependency of this suite's job."""
    monkeypatch.setattr(g, "commands", lambda plan: [[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *plan.files()]])


def scratch_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point ``tempfile`` at a directory of this test's own, so a leftover scratch worktree is visible as a file."""
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return scratch


@pytest.fixture(autouse=True)
def _nothing_left_in_the_scratch_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Every test of this file runs with ``tempfile`` pointed at a directory of its own and finds it empty afterwards, whether or not the test
    looks: a cleanup that regresses would otherwise leave the scratch worktrees in the real temporary directory, with nothing red."""
    scratch = scratch_dirs(monkeypatch, tmp_path)
    yield
    assert list(scratch.iterdir()) == [], "a scratch worktree directory was left behind"


def worktrees(r: Path) -> list[str]:
    return [line.split()[0] for line in git(r, "worktree", "list").splitlines()]


def admin_entries(r: Path) -> list[str]:
    """The names under ``.git/worktrees``: git's own record of every linked worktree (the directory is gone when there is none)."""
    folder = r / ".git" / "worktrees"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def snapshot(r: Path) -> tuple[str, str, str, str]:
    """Everything ``--onto`` must leave alone: HEAD, every ref, the working tree's status, the worktree list."""
    return (git(r, "rev-parse", "HEAD"), git(r, "for-each-ref"), git(r, "status", "--porcelain"), "\n".join(worktrees(r)))


def onto(monkeypatch: pytest.MonkeyPatch, r: Path, *args: str) -> int:
    monkeypatch.setattr(g, "ROOT", r)
    return g.main(["--onto", "main", *args])


def test_a_guard_main_added_is_green_on_the_branch_and_red_on_the_merged_tree(
    clean_repo: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """The point of the flag. The branch's own tree passes everything it contains; merged onto main, the guard main added since rejects the
    branch's file, and ``--onto main --run`` says so (exit 1) where the plain run could not."""
    repo = clean_repo
    add_a_guard_on_main_the_branch_breaks(repo)
    only_pytest(monkeypatch)
    monkeypatch.setattr(g, "ROOT", repo)
    plain = g.build_plan(repo, "main")
    assert plain.behind == 1 and "tests/test_main_guard.py" not in plain.files()  # the plain plan is of a tree without the guard
    assert g.run(plain, repo) == 0  # ... and green: this is the miss
    capfd.readouterr()
    assert onto(monkeypatch, repo, "--run") == 1
    out = capfd.readouterr().out
    assert "tests/test_main_guard.py" in out and "bad_thing.py" in out  # the red names the guard and the file it rejects


def test_onto_picks_what_ref_changed_and_what_the_branch_adds_as_seen_in_the_merged_tree(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add_a_guard_on_main_the_branch_breaks(repo)
    assert onto(monkeypatch, repo) == 0
    out = capsys.readouterr().out
    head = out.split("tests main added")[0]
    assert head.startswith("merged tree: main (") and "this branch's HEAD (" in head and "scratch worktree" in head
    main_group = out.split("tests main added or changed since this branch left it (")[1].split("tests this branch adds")[0]
    own_group = out.split("tests this branch adds or changes (")[1].split("changed support files")[0]
    assert main_group.startswith("1):") and "tests/test_main_guard.py" in main_group
    assert own_group.startswith("1):") and "tests/test_feature.py" in own_group
    assert "WARNING" not in out  # the merged tree has main in it: nothing is "ahead"
    capsys.readouterr()
    assert onto(monkeypatch, repo, "--files") == 0
    files = capsys.readouterr().out.split()
    assert files[:2] == ["tests/test_main_guard.py", "tests/test_feature.py"]  # main's first, then the branch's own, as the groups are listed


def test_onto_leaves_the_repository_and_the_scratch_directory_as_it_found_them(
    clean_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = clean_repo
    add_a_guard_on_main_the_branch_breaks(repo)
    scratch = scratch_dirs(monkeypatch, tmp_path)
    only_pytest(monkeypatch)
    before = snapshot(repo)
    assert onto(monkeypatch, repo, "--run") == 1  # a red run cleans up as well as a green one
    assert snapshot(repo) == before and len(worktrees(repo)) == 1
    assert list(scratch.iterdir()) == []
    assert onto(monkeypatch, repo, "--files") == 0
    assert snapshot(repo) == before and list(scratch.iterdir()) == []


def test_onto_cleans_up_when_the_plan_itself_cannot_be_built(repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No ratchet ceiling in the merged tree's workflow is a named stop inside the ``with``: the worktree must still go."""
    add_a_guard_on_main_the_branch_breaks(repo)
    git(repo, "checkout", "-q", "main")
    write(repo, ".github/workflows/ci.yml", "jobs: {}\n")
    commit(repo, "main loses the ceiling")
    git(repo, "checkout", "-q", "feature")
    scratch = scratch_dirs(monkeypatch, tmp_path)
    assert onto(monkeypatch, repo, "--files") == 2
    assert list(scratch.iterdir()) == [] and len(worktrees(repo)) == 1


def test_a_branch_that_does_not_merge_onto_ref_is_a_named_stop_listing_the_conflicting_files(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "src/mod.py", "x = 'branch'\n")
    write(repo, "tests/test_plain.py", "x = 'branch'\n")
    commit(repo, "branch edits")
    git(repo, "checkout", "-q", "main")
    write(repo, "src/mod.py", "x = 'main'\n")
    write(repo, "tests/test_plain.py", "x = 'main'\n")
    commit(repo, "main edits the same lines")
    git(repo, "checkout", "-q", "feature")
    git(repo, "config", "rerere.enabled", "true")  # a conflict would be recorded in the repository's shared rr-cache, which is the user's
    scratch = scratch_dirs(monkeypatch, tmp_path)
    before = snapshot(repo)
    assert onto(monkeypatch, repo, "--run", "--keep") == 2  # --keep does not keep a worktree that never became a merged tree
    err = capsys.readouterr().err
    assert "does not merge onto main" in err and "2 file(s) conflict" in err and "src/mod.py" in err and "tests/test_plain.py" in err
    assert snapshot(repo) == before and list(scratch.iterdir()) == []
    assert not (repo / ".git" / "rr-cache").exists()


def test_a_ref_that_does_not_exist_is_named(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(g, "ROOT", repo)
    assert g.main(["--onto", "no-such-ref"]) == 2
    assert "no such ref `no-such-ref` for --onto" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--base", "main"], ["--since", "main"]])
def test_onto_replaces_base_and_since_and_keep_belongs_to_onto(repo: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str]) -> None:
    monkeypatch.setattr(g, "ROOT", repo)
    with pytest.raises(SystemExit) as raised:
        g.main(["--onto", "main", *extra])
    assert raised.value.code == 2
    with pytest.raises(SystemExit) as raised:
        g.main(["--keep"])
    assert raised.value.code == 2


def test_keep_leaves_the_merged_worktree_and_names_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_a_guard_on_main_the_branch_breaks(repo)
    scratch = scratch_dirs(monkeypatch, tmp_path)
    assert onto(monkeypatch, repo, "--files", "--keep") == 0
    captured = capsys.readouterr()
    kept = Path(captured.err.split("kept: ")[1].split()[0])
    try:
        assert kept.is_dir() and (kept / "tests" / "test_main_guard.py").is_file() and (kept / "tests" / "test_feature.py").is_file()
        assert kept.parent.parent == scratch and len(worktrees(repo)) == 2
    finally:
        git(repo, "worktree", "remove", "--force", str(kept))
        shutil.rmtree(kept.parent, ignore_errors=True)
    assert len(worktrees(repo)) == 1


def test_a_branch_already_inside_ref_says_so_and_has_only_the_guards(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(repo, "checkout", "-q", "-b", "feature")  # no commit of its own: HEAD is main's
    assert onto(monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "is already inside it" in out and "tests main added or changed since this branch left it (0)" in out


def test_a_branch_that_already_merged_ref_is_merged_again_without_a_word_about_being_inside(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feature_with_merged_main(repo)  # the branch merged main, then main did not move: REF is inside the branch, the branch is not inside REF
    assert onto(monkeypatch, repo, "--files") == 0
    files = capsys.readouterr().out.split()
    assert "tests/test_from_main.py" in files and "tests/test_own_committed.py" in files  # the same groups as the plain plan, as seen in the merged tree
    assert onto(monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "this branch's HEAD (" in out and "already inside" not in out


def test_onto_names_uncommitted_work_and_a_change_under_src(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    add_a_guard_on_main_the_branch_breaks(repo)
    git(repo, "config", "status.showUntrackedFiles", "no")  # the user's setting hides an untracked file from a plain status; the note must not
    write(repo, "tests/test_unsaved.py")  # untracked
    write(repo, "tests/test_plain.py", "x = 3\n")  # tracked, modified
    assert onto(monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "NOTE: 2 path(s) of the working tree are uncommitted or untracked and are NOT in the merged tree" in out
    assert "NOTE: this branch changes 1 file(s) under src/" in out and "touches no src/" in out
    assert "tests/test_unsaved.py" not in out.split("tree-wide guards")[0]  # left out of the picks, as the note says


def test_onto_has_nothing_to_say_about_src_or_the_working_tree_when_there_is_nothing_to_say(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add_a_guard_on_main_the_branch_breaks(repo, branch_touches_src=False)
    assert onto(monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "NOTE" not in out


def test_a_change_under_src_that_only_ref_made_is_not_the_branch_s(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The src NOTE is about what THIS branch changed since it left REF, not about the difference between the two trees."""
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "tests/test_feature.py", "def test_feature():\n    assert True\n")
    commit(repo, "feature work, tests only")
    git(repo, "checkout", "-q", "main")
    write(repo, "src/other.py", "y = 2\n")
    commit(repo, "main changes src")
    git(repo, "checkout", "-q", "feature")
    assert onto(monkeypatch, repo) == 0
    assert "NOTE" not in capsys.readouterr().out


def test_the_scratch_merge_runs_no_hook_signs_nothing_and_needs_no_identity(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A user's hooks, signing key and name are none of the scratch merge's business: a repository whose hooks fail, with signing on and no
    identity anywhere, still gets its merged tree."""
    add_a_guard_on_main_the_branch_breaks(repo)
    marker = tmp_path / "hook-ran"
    for hook in ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "post-merge", "pre-merge-commit", "post-checkout", "reference-transaction"):
        path = repo / ".git" / "hooks" / hook
        path.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
        path.chmod(0o755)
    git(repo, "config", "commit.gpgsign", "true")
    git(repo, "config", "gpg.program", "/nonexistent/gpg")
    git(repo, "config", "merge.verifySignatures", "true")  # an unsigned commit would stop the merge
    git(repo, "config", "user.useConfigOnly", "true")  # no identity is guessed from the host name: the test is the same on every machine
    nowhere = tmp_path / "no-git-config"
    nowhere.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(nowhere))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)
    assert onto(monkeypatch, repo, "--files") == 0
    assert not marker.exists()


def test_a_failing_post_checkout_hook_does_not_stop_the_worktree_from_being_made(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``git worktree add`` runs ``post-checkout``, a hook of the user's, and a failing one made ``--onto`` exit 2 with only "failed: 1"."""
    add_a_guard_on_main_the_branch_breaks(repo)
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    assert onto(monkeypatch, repo, "--files") == 0


def test_onto_does_not_prune_a_worktree_of_the_users_whose_folder_is_missing(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``git worktree prune`` drops the entry of EVERY worktree whose folder is gone (one on an unmounted disk, say): only the scratch one is ours."""
    add_a_guard_on_main_the_branch_breaks(repo)
    other = tmp_path / "another-checkout"
    git(repo, "worktree", "add", "--detach", "-q", str(other), "main")
    shutil.rmtree(other)
    before = snapshot(repo)
    assert onto(monkeypatch, repo, "--files") == 0
    assert snapshot(repo) == before
    assert admin_entries(repo) == ["another-checkout"]


def test_a_worktree_git_would_not_remove_is_still_removed_with_its_entry(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``worktree remove --force`` refuses a locked worktree; the directory and the administrative entry recorded at creation go all the same."""
    add_a_guard_on_main_the_branch_breaks(repo)
    monkeypatch.setattr(g, "ROOT", repo)
    with g.merged_worktree(repo, "main") as tree:
        git(repo, "worktree", "lock", str(tree.path))
        assert admin_entries(repo) == ["onto"]
    assert len(worktrees(repo)) == 1
    assert admin_entries(repo) == []


def test_the_termination_handlers_are_the_callers_again_when_the_run_is_over(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The handlers that turn SIGTERM and SIGHUP into an exit exist only while a scratch worktree does, on a clean end and on an error."""
    add_a_guard_on_main_the_branch_breaks(repo)
    names = [getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name)]
    before = {number: signal.getsignal(number) for number in names}
    with g.merged_worktree(repo, "main"):
        assert all(signal.getsignal(number) is not before[number] for number in names)
    assert {number: signal.getsignal(number) for number in names} == before
    with pytest.raises(RuntimeError), g.merged_worktree(repo, "main"):
        raise RuntimeError("a step blew up")
    assert {number: signal.getsignal(number) for number in names} == before


def test_keep_names_the_worktree_even_when_the_run_ends_in_a_named_stop(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stop after the merged tree exists (here: no ceiling to read in its workflow) used to keep the tree and say nothing of where."""
    add_a_guard_on_main_the_branch_breaks(repo)
    git(repo, "checkout", "-q", "main")
    write(repo, ".github/workflows/ci.yml", "jobs: {}\n")
    commit(repo, "main loses the ceiling")
    git(repo, "checkout", "-q", "feature")
    assert onto(monkeypatch, repo, "--files", "--keep") == 2
    err = capsys.readouterr().err
    kept = Path(err.split("kept: ")[1].split()[0])
    try:
        assert kept.is_dir() and len(worktrees(repo)) == 2
    finally:
        git(repo, "worktree", "remove", "--force", str(kept))
        shutil.rmtree(kept.parent, ignore_errors=True)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_a_terminated_run_removes_its_scratch_worktree(clean_repo: Path, tmp_path: Path, sig: signal.Signals) -> None:
    """A closed terminal (SIGHUP) or a ``kill`` (SIGTERM) in the middle of a step: Python would die at once and leave the worktree, its directory
    and its entry. The script runs as a real process in a copy of itself inside the throwaway repository (it finds its repository from its own
    location), waiting in a test that never returns."""
    repo = clean_repo
    started = tmp_path / "started"
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "tests/test_waits.py", f"import pathlib, time\n\n\ndef test_waits():\n    pathlib.Path({str(started)!r}).write_text('x')\n    time.sleep(90)\n")
    commit(repo, "a test that waits")
    script = repo / "scripts" / "guards_for_diff.py"
    script.parent.mkdir()
    shutil.copy(ROOT / "scripts" / "guards_for_diff.py", script)
    scratch = tmp_path / "process-scratch"
    scratch.mkdir()
    proc = subprocess.Popen(
        [sys.executable, str(script), "--onto", "main", "--run"],
        cwd=repo,
        env={**os.environ, "TMPDIR": str(scratch)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 120
        while not started.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        assert started.exists(), "the step never started"
        assert any(scratch.iterdir())  # the worktree is there while the step runs
        proc.send_signal(sig)
        assert proc.wait(timeout=60) == 128 + sig
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert list(scratch.iterdir()) == []
    assert len(worktrees(repo)) == 1
    assert admin_entries(repo) == []


def test_a_file_both_sides_changed_that_the_merge_unions_is_named(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``.gitattributes`` marks ``docs/ledger/shipped.csv`` ``merge=union``: git keeps both sides' lines, GitHub reports a conflict. The merged
    tree is then not the one GitHub would make, and the page says which file."""
    write(repo, "docs/ledger/shipped.csv", "row 1\n")
    write(repo, "docs/ledger/other.csv", "row 1\n")
    write(repo, "docs/notes.md", "".join(f"line {i}\n" for i in range(1, 11)))
    commit(repo, "ledger files")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "docs/ledger/shipped.csv", "row 1\nbranch row\n")
    write(repo, "docs/ledger/other.csv", "row 1\nbranch row\n")  # changed on this side only
    write(repo, "docs/notes.md", "".join(f"line {i}\n" for i in range(1, 11)).replace("line 1\n", "branch line\n"))  # both sides, different hunks
    commit(repo, "branch work")
    git(repo, "checkout", "-q", "main")
    write(repo, ".gitattributes", "docs/ledger/shipped.csv merge=union\ndocs/ledger/other.csv merge=union\n")  # only the merged tree has the rule
    write(repo, "docs/ledger/shipped.csv", "row 1\nmain row\n")
    write(repo, "docs/notes.md", "".join(f"line {i}\n" for i in range(1, 11)).replace("line 10\n", "main line\n"))
    commit(repo, "main work")
    git(repo, "checkout", "-q", "feature")
    assert onto(monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "NOTE: docs/ledger/shipped.csv changed on both sides and is merged here with the `merge=union` rule" in out
    assert "other.csv changed on both sides" not in out and "notes.md changed on both sides" not in out
    assert out.count("merge=union") == 1


def test_tree_env_leads_pythonpath_with_the_tree_and_keeps_the_rest() -> None:
    assert g.tree_env(Path("/t"), {"PYTHONPATH": "/a:/b", "K": "v"}) == {"PYTHONPATH": "/t" + os.pathsep + "/a:/b", "K": "v"}
    assert g.tree_env(Path("/t"), {"K": "v"})["PYTHONPATH"] == "/t"  # no trailing separator: an empty entry means the working directory
    assert g.tree_env(Path("/t"), {"PYTHONPATH": ""})["PYTHONPATH"] == "/t"


def test_a_child_process_of_a_picked_test_imports_the_tree_the_steps_run_in(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The measured miss: on one tree, tests that start a child went red because the child imported ``src`` from where the editable install
    points. The test below does what they do (a child, started elsewhere, imports ``src``); with the control, it is red without the tree on
    ``PYTHONPATH`` on any machine, so the green below is the environment's doing and not luck."""
    write(repo, "src/__init__.py", "")
    write(
        repo,
        "tests/test_child_imports_src.py",
        "import pathlib, subprocess, sys, tempfile\n\n\n"
        "def test_child():\n"
        "    done = subprocess.run([sys.executable, '-c', 'import src; print(src.__file__)'], cwd=tempfile.gettempdir(), capture_output=True, text=True)\n"
        "    assert done.returncode == 0, done.stderr\n"
        "    assert pathlib.Path(done.stdout.strip()).resolve().is_relative_to(pathlib.Path(__file__).resolve().parents[1])\n",
    )
    commit(repo, "a test with a child")
    step = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_child_imports_src.py"]
    monkeypatch.setattr(g, "commands", lambda plan: [step])
    bare = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    assert subprocess.run(step, cwd=repo, env=bare, capture_output=True).returncode != 0  # the control: red without it
    assert g.run(g.Plan(base="main", ceiling=417, behind=0), repo) == 0


@pytest.mark.parametrize(
    "line",
    ['for f in sorted(root.glob("test_*.py")):', "ROOT.rglob('test_*.py')", 'tests_dir.glob( "test_*" )'],
)
def test_a_guard_that_walks_the_test_files_is_a_tree_wide_guard(line: str) -> None:
    assert g.TREE_WIDE.search(line)


@pytest.mark.parametrize("line", ['tmp_path.glob("data_*.json")', 'p.glob("tests_*.py")', 'p.glob("not_a_test_*.py")'])
def test_a_glob_of_something_else_with_a_star_is_not(line: str) -> None:
    assert not g.TREE_WIDE.search(line)


def test_the_test_walking_guards_of_this_repository_are_picked() -> None:
    found = g.tree_wide_guards(ROOT)
    for named in ("tests/test_artifact_file_members.py", "tests/test_import_conclusion.py", "tests/test_source_slicing_discipline.py"):
        assert named in found, named

