"""``scripts/sweep_pr_number.py`` writes the real PR number into the ledger fragments a branch added.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A fragment cannot carry its PR number before the PR exists, so it carries ``PR pending`` / ``#NNNN`` and the number goes in right after.
Every case here runs the script against a throwaway git repository (a ``main`` with some fragments, a branch with others) and compares
bytes, because the things that go wrong are the ones that touch more than they were asked to:

* only fragments the branch ADDED are swept (not ones it edited, not ones main already carries; a new file git pairs with a deleted one as a
  rename is still an addition; a branch stacked on another passes that branch as ``--base``);
* markdown is swept in prose only (fenced blocks and inline code keep a quoted placeholder), the case of the token does not matter, ``\\r\\n``
  line ends and the file mode survive;
* a ``shipped.d`` csv is swept in its ``refs`` cell only, whatever quoting the file was written with (every cell quoted, a cell that holds a
  newline), and every other byte stays;
* everything that is not a plain case is a REFUSAL (exit 2) that writes nothing, even when another fragment in the batch was fine: a number
  that is not a positive integer, a base that does not resolve or looks like an option, no added fragment, a symlink (or a path that runs
  through one), text or a file name that is not UTF-8, an unclosed fence, a csv that is not the header plus one row or that the csv module
  cannot read, and any placeholder the ledger would still refuse after the rewrite (a token the script has no rule for, one split by a line
  break, a code span or a quote, `#NNNN` run on into more letters, a `pending` the shipped.d guard refuses in any form);
* a second run says there is nothing to sweep and exits 0; a write that fails part-way exits 1 and names what was replaced; a failed replace
  leaves no temporary file beside the fragment.
"""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.os_scope import scope_os

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "sweep_pr_number.py"
_D = "docs/ledger/"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

_HEADER = "date,area,item,status,refs,key_paths,summary\n"
_LESSON = textwrap.dedent(
    """\
    ## 2026-10-29 — a lesson about #NNNN handling (PR #NNNN)

    Shipped in PR pending. Quoted: `#NNNN` and `PR pending` stay.
    ```
    PR pending
    #NNNN
    ```
    ~~~
    still quoted: PR pending
    ~~~
    After the fences: pr PENDING and #nnnn change.
    """
)
_LOG = "## 2026-10-29 — a log (PR #NNNN)\n\nbody\r\nsecond line with PR   pending\r\n"


def _row(refs: str, *, summary: str = "s", item: str = "i", date: str = "2026-10-29", quote_all: bool = False) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL)
    writer.writerow(["date", "area", "item", "status", "refs", "key_paths", "summary"])
    writer.writerow([date, "a", item, "shipped", refs, "k", summary])
    return buf.getvalue()


_OLD_MAIN = {
    _D + "lessons.d/2026-10-01-old.md": "## 2026-10-01 — old (PR #NNNN)\nPR pending\n",
    _D + "shipped.d/2026-10-01-old.csv": _row("PR pending", item="old", date="2026-10-01"),
}
_GOOD = {_D + "lessons.d/2026-10-29-t.md": _LESSON}


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return done.stdout


def _put(root: Path, files: dict) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, tuple):  # ("symlink", target)
            try:
                os.symlink(data[1], path)
            except (OSError, NotImplementedError):
                pytest.skip("symlinks are not available here")
        else:
            path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _repo(tmp_path: Path, branch_files: dict, main_files: dict | None = None) -> Path:
    """``main`` carries ``main_files``; the branch ``feat`` is cut from it and adds ``branch_files``; ``origin/main`` is main."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, timeout=120)
    _put(root, main_files or {})
    (root / "README").write_text("x", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "main")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-q", "-b", "feat")
    _put(root, branch_files)
    _git(root, "add", "-A")
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", "-C", str(root), "commit", "-q", "-m", "branch"],
        capture_output=True,
        timeout=120,
    )  # an empty branch has nothing to commit: that is a case, not an error
    return root


def _sweep(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), *args, "--root", str(root)], capture_output=True, text=True, timeout=120
    )


def _snap(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)).replace(os.sep, "/"): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


def _load():
    spec = importlib.util.spec_from_file_location("sweep_pr_number_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sweeps_markdown_and_csv_in_every_shape_and_touches_only_added_fragments(tmp_path):
    quoted = _row("PR pending; R12", summary="mentions #NNNN and PR pending\nin a\nmultiline cell", item="q", quote_all=True)
    files = {
        _D + "lessons.d/2026-10-29-t.md": _LESSON,
        _D + "shipped_log.d/2026-10-29-l.md": _LOG.encode("utf-8"),
        _D + "shipped.d/2026-10-29-c1.csv": _row("PR pending", item="c1"),
        _D + "shipped.d/2026-10-29-c2.csv": quoted,
        _D + "shipped.d/2026-10-29-c3.csv": _row("PR #1500", item="c3"),
        _D + "shipped.d/2026-10-29-c4.csv": _row("PR #NNNN, R9", item="c4"),
    }
    root = _repo(tmp_path, files, _OLD_MAIN)
    before = _snap(root)
    done = _sweep(root, "1636")
    assert done.returncode == 0, (done.stdout, done.stderr)
    after = _snap(root)
    changed = {k for k in after if after[k] != before[k]}
    assert changed == {
        _D + "lessons.d/2026-10-29-t.md",
        _D + "shipped_log.d/2026-10-29-l.md",
        _D + "shipped.d/2026-10-29-c1.csv",
        _D + "shipped.d/2026-10-29-c2.csv",
        _D + "shipped.d/2026-10-29-c4.csv",
    }, changed
    lesson = after[_D + "lessons.d/2026-10-29-t.md"].decode("utf-8")
    assert lesson.startswith("## 2026-10-29 — a lesson about #1636 handling (PR #1636)\n"), lesson
    assert "Shipped in PR #1636." in lesson and "`#NNNN` and `PR pending` stay." in lesson
    assert "```\nPR pending\n#NNNN\n```" in lesson and "~~~\nstill quoted: PR pending\n~~~" in lesson
    assert "After the fences: PR #1636 and #1636 change." in lesson, lesson
    log = after[_D + "shipped_log.d/2026-10-29-l.md"]
    assert log == b"## 2026-10-29 \xe2\x80\x94 a log (PR #1636)\n\nbody\r\nsecond line with PR #1636\r\n", log
    assert after[_D + "shipped.d/2026-10-29-c1.csv"].decode("utf-8") == _row("PR #1636", item="c1")
    # the quote-all, multi-line row: only the refs cell moved, every other byte is the same
    expected = quoted.replace('"PR pending; R12"', '"PR #1636; R12"')
    assert after[_D + "shipped.d/2026-10-29-c2.csv"].decode("utf-8") == expected
    assert after[_D + "shipped.d/2026-10-29-c4.csv"].decode("utf-8") == _row("PR #1636, R9", item="c4")
    assert after[_D + "shipped.d/2026-10-29-c3.csv"] == before[_D + "shipped.d/2026-10-29-c3.csv"]
    for key in _OLD_MAIN:
        assert after[key] == before[key], "a fragment already on main was touched"
    assert "swept 10 placeholder(s) in 5 file(s) to #1636" in done.stdout, done.stdout
    assert not [p for p in after if p.endswith(".tmp")], "a temporary file was left behind"


def test_a_second_run_changes_nothing_and_exits_zero(tmp_path):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-t.md": _LESSON}, _OLD_MAIN)
    assert _sweep(root, "7").returncode == 0
    first = _snap(root)
    done = _sweep(root, "8")
    assert done.returncode == 0 and "nothing to sweep" in done.stdout, (done.stdout, done.stderr)
    assert _snap(root) == first


def test_dry_run_prints_the_change_and_writes_nothing(tmp_path):
    root = _repo(tmp_path, {_D + "shipped.d/2026-10-29-c1.csv": _row("PR pending")}, _OLD_MAIN)
    before = _snap(root)
    done = _sweep(root, "9", "--dry-run")
    assert done.returncode == 0 and "PR #9" in done.stdout and "dry run" in done.stdout, done.stdout
    assert _snap(root) == before


def test_a_fragment_the_branch_edits_is_not_swept_only_added_ones_are(tmp_path):
    edited = "## 2026-10-01 — old (PR #NNNN)\nPR pending\nedited\n"
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-01-old.md": edited, _D + "lessons.d/2026-10-29-t.md": _LESSON}, _OLD_MAIN)
    done = _sweep(root, "11")
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert (root / _D / "lessons.d/2026-10-01-old.md").read_text(encoding="utf-8") == edited
    assert "#11" in (root / _D / "lessons.d/2026-10-29-t.md").read_text(encoding="utf-8")


def test_a_new_fragment_git_pairs_with_a_deleted_one_as_a_rename_is_still_swept(tmp_path):
    same = "## 2026-10-29 — twin (PR #NNNN)\n" + "\n".join(f"line {i} of a lesson that is long enough for similarity" for i in range(12)) + "\n"
    main = dict(_OLD_MAIN)
    main[_D + "lessons.d/2026-10-20-twin.md"] = same.replace("PR #NNNN", "PR #1400").replace("2026-10-29", "2026-10-20")
    root = _repo(tmp_path, {}, main)
    _git(root, "rm", "-q", _D + "lessons.d/2026-10-20-twin.md")
    (root / _D / "lessons.d/2026-10-29-twin.md").write_text(same, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "swap")
    status = _git(root, "diff", "--name-status", "origin/main", "HEAD").split()[0]
    assert status.startswith("R"), "the fixture must be seen as a rename by git, or the case proves nothing"
    done = _sweep(root, "12")
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "#12" in (root / _D / "lessons.d/2026-10-29-twin.md").read_text(encoding="utf-8")


def test_a_stacked_branch_sweeps_only_its_own_fragments_with_base(tmp_path):
    lower = "## 2026-10-28 — lower (PR #NNNN)\n"
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-28-lower.md": lower}, _OLD_MAIN)
    _git(root, "branch", "lower")
    (root / _D / "lessons.d/2026-10-29-upper.md").write_text("## 2026-10-29 — upper (PR #NNNN)\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "upper")
    done = _sweep(root, "20", "--base", "lower")
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "#20" in (root / _D / "lessons.d/2026-10-29-upper.md").read_text(encoding="utf-8")
    assert (root / _D / "lessons.d/2026-10-28-lower.md").read_text(encoding="utf-8") == lower, "the lower branch's fragment got the upper number"


@pytest.mark.parametrize("bad", ["#1636", "0", "abc", " 12", "012", "1234567890", "12.5", "-3", ""])
def test_refuses_a_number_that_is_not_a_positive_integer(tmp_path, bad):
    root = _repo(tmp_path, _GOOD, _OLD_MAIN)
    before = _snap(root)
    done = _sweep(root, bad)
    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert "positive integer" in done.stderr, done.stderr
    assert _snap(root) == before, "a refusal wrote something"


_SPLIT = {_D + "lessons.d/2026-10-29-sp.md": "## 2026-10-29 — x\nSee PR `a` pending now.\n"}
_BROKEN = {_D + "lessons.d/2026-10-29-br.md": "## 2026-10-29 — wrapped\n\nThis shipped in PR\npending and the rest of the sentence.\n"}
_BROKEN_BY_A_FENCE = {_D + "lessons.d/2026-10-29-fb.md": "## 2026-10-29 — fenced\n\nShipped in PR\n```\nquoted\n```\npending now.\n"}
_UNCLOSED = {_D + "lessons.d/2026-10-29-un.md": "## 2026-10-29 — unclosed\n\n```\nsome code\n\nShipped in PR pending.\n"}
_TYPO = {_D + "lessons.d/2026-10-29-ty.md": "## 2026-10-29 — typo (PR #NNNNN)\n"}


def _refs(raw: str, name: str = "x") -> dict:
    """A shipped.d fragment whose refs cell is written exactly as ``raw`` (``_row`` would re-quote it)."""
    return {_D + f"shipped.d/2026-10-29-{name}.csv": _HEADER + f"2026-10-29,a,i,shipped,{raw},k,s\n"}


_REFUSALS = {
    "an unknown base": (_GOOD, ["5", "--base", "nope"], "does not resolve"),
    "a base that looks like an option": (_GOOD, ["5", "--base=--all"], "is not a ref"),
    "a branch that adds no fragment": ({"other.txt": "x"}, ["5"], "adds no ledger fragment"),
    "fragments added outside the ledger directories": (
        {_D + "lessons.d/notes.txt": "x", _D + "README.md": "#NNNN"},
        ["5"],
        "adds no ledger fragment",
    ),
    "a non-UTF-8 fragment": ({_D + "lessons.d/2026-10-29-u.md": b"## 2026-10-29 \xff\xfe PR pending\n"}, ["5"], "UTF-8"),
    "a csv with two rows": (
        {_D + "shipped.d/2026-10-29-two.csv": _HEADER + "2026-10-29,a,b,c,PR pending,k,s\n2026-10-29,a,b2,c,PR pending,k,s\n"},
        ["5"],
        "exactly one row",
    ),
    "a csv with the wrong header": ({_D + "shipped.d/2026-10-29-hdr.csv": "date,area,item\n2026-10-29,a,b\n"}, ["5"], "header"),
    "a csv whose file name does not start with its date": (
        {_D + "shipped.d/2026-10-30-x.csv": _row("PR pending")},
        ["5"],
        "file name must start",
    ),
    "a placeholder split by inline code, which would survive": (_SPLIT, ["5"], "would remain"),
    "a batch with one good fragment and one that would survive": ({_D + "lessons.d/2026-10-29-ok.md": _LESSON, **_SPLIT}, ["5"], "would remain"),
    "a placeholder broken across a line": (_BROKEN, ["5"], "would remain"),
    "a placeholder broken across a line by a fenced block": (_BROKEN_BY_A_FENCE, ["5"], "would remain"),
    "an unclosed code fence": (_UNCLOSED, ["5"], "unclosed"),
    "a #NNNN run on into more letters": (_TYPO, ["5"], "would remain"),
    "a refs cell the csv reader joins into PR pending": (_refs('"PR" pending'), ["5"], "would remain"),
    "a refs cell with a colon after PR": (_refs("PR: pending"), ["5"], "would remain"),
    "a refs cell with a pending the placeholder pattern does not name": (_refs("PRs pending (R12)"), ["5"], "would remain"),
    "a csv cell past the csv module's field limit": (
        {_D + "shipped.d/2026-10-29-big.csv": _HEADER + "2026-10-29,a,i,shipped,PR pending,k," + "x" * 200_000 + "\n"},
        ["5"],
        "not readable as csv",
    ),
}


@pytest.mark.parametrize("name", list(_REFUSALS))
def test_a_refusal_exits_two_names_the_reason_and_writes_nothing(tmp_path, name):
    branch_files, args, needle = _REFUSALS[name]
    root = _repo(tmp_path, branch_files, _OLD_MAIN)
    before = _snap(root)
    done = _sweep(root, *args)
    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert needle in done.stderr, done.stderr
    assert _snap(root) == before, "a refusal wrote something"


def test_refuses_a_symlinked_fragment(tmp_path):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-s.md": ("symlink", "/etc/hostname")}, _OLD_MAIN)
    done = _sweep(root, "5")
    assert done.returncode == 2 and "symlink" in done.stderr, (done.returncode, done.stderr)


def test_not_a_git_repository_is_refused(tmp_path):
    done = _sweep(tmp_path, "5")
    assert done.returncode == 2 and "refused" in done.stderr and "does not resolve" in done.stderr, (done.returncode, done.stderr)


def test_a_fragment_deleted_from_the_working_tree_is_skipped_and_the_rest_is_swept(tmp_path):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-t.md": _LESSON, _D + "lessons.d/2026-10-29-gone.md": _LESSON}, _OLD_MAIN)
    (root / _D / "lessons.d/2026-10-29-gone.md").unlink()
    done = _sweep(root, "31")
    assert done.returncode == 0 and "skipped" in done.stdout, (done.stdout, done.stderr)
    assert "#31" in (root / _D / "lessons.d/2026-10-29-t.md").read_text(encoding="utf-8")


def test_a_write_failing_part_way_exits_one_names_what_was_replaced_and_the_rerun_finishes(tmp_path):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-a.md": _LESSON, _D + "lessons.d/2026-10-29-b.md": _LESSON}, _OLD_MAIN)
    module = _load()
    real, calls = module._replace, []

    def flaky(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, data)

    module._replace = flaky
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = module.run(root, "40", "origin/main", False)
    said = err.getvalue()
    assert code == 1 and "disk full" in said and "replaced: " in said and "2026-10-29-a.md" in said, (code, said, calls)
    assert "2026-10-29-b.md" not in said, "the file whose write FAILED was reported as replaced"
    module._replace = real
    with contextlib.redirect_stdout(io.StringIO()):
        assert module.run(root, "40", "origin/main", False) == 0
    for name in ("a", "b"):
        text = (root / _D / f"lessons.d/2026-10-29-{name}.md").read_text(encoding="utf-8")
        assert text.startswith("## 2026-10-29 — a lesson about #40 handling (PR #40)\n"), name


def test_a_failed_replace_leaves_no_temporary_file_and_the_original_intact(tmp_path, monkeypatch):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-a.md": _LESSON}, _OLD_MAIN)
    module = _load()

    def refuse(src, dst):
        raise OSError("replace refused")

    scope_os(monkeypatch, module, replace=refuse)  # the script's own name for os, never the process-wide one (R351)
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        code = module.run(root, "41", "origin/main", False)
    assert code == 1, code
    left = [p.name for p in (root / _D / "lessons.d").iterdir() if p.name.startswith(".sweep-")]
    assert not left, left
    assert "#NNNN" in (root / _D / "lessons.d/2026-10-29-a.md").read_text(encoding="utf-8"), "the original must be intact"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_file_mode_survives_the_rewrite(tmp_path):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-t.md": _LESSON}, _OLD_MAIN)
    path = root / _D / "lessons.d/2026-10-29-t.md"
    path.chmod(0o640)
    assert _sweep(root, "50").returncode == 0
    assert (path.stat().st_mode & 0o777) == 0o640


_CSV_SHAPES = {
    "CRLF line ends": _HEADER.replace("\n", "\r\n") + "2026-10-29,a,i,shipped,PR pending,k,s\r\n",
    "a doubled quote inside a quoted cell": _HEADER + '2026-10-29,a,i,shipped,PR pending,"a ""b, c"" d",s\n',
    "a quote in the middle of an unquoted cell": _HEADER + '2026-10-29,a,i,shipped,PR pending,a"b,c"d\n',
    "no final newline": _HEADER + "2026-10-29,a,i,shipped,PR pending,k,s",
}


@pytest.mark.parametrize("name", list(_CSV_SHAPES))
def test_a_csv_is_swept_in_its_refs_cell_whatever_its_line_ends_and_quoting(tmp_path, name):
    text = _CSV_SHAPES[name]
    root = _repo(tmp_path, {_D + "shipped.d/2026-10-29-shape.csv": text.encode("utf-8")}, _OLD_MAIN)
    done = _sweep(root, "16")
    assert done.returncode == 0, (done.stdout, done.stderr)
    swept = (root / _D / "shipped.d/2026-10-29-shape.csv").read_bytes()
    assert swept == text.replace("PR pending", "PR #16", 1).encode("utf-8"), swept


_NOT_ONE_ROW = {
    "an empty text": "",
    "another header": "date,area,item,status,refs,key_paths,other\n2026-10-29,a,i,shipped,PR pending,k,s\n",
    "two rows": _HEADER + "2026-10-29,a,i,shipped,PR pending,k,s\n2026-10-29,a,j,shipped,PR pending,k,s\n",
    "a short row": _HEADER + "2026-10-29,a,i,shipped,PR pending\n",
}


@pytest.mark.parametrize("name", list(_NOT_ONE_ROW))
def test_sweep_csv_refuses_a_text_that_is_not_the_header_plus_one_row_on_its_own(name):
    """``read_fragment`` refuses these first in a real run; ``sweep_csv`` is also a function of its own and says so itself."""
    module = _load()
    with pytest.raises(module.Refused, match="exactly one"):
        module.sweep_csv("x.csv", _NOT_ONE_ROW[name], "5")


def test_sweep_csv_refuses_when_the_spans_it_found_are_not_the_records_csv_read():
    module = _load()
    text = _HEADER + "2026-10-29,a,i,shipped,PR pending,k,s\n"
    real = module._spans
    module._spans = lambda text: real(text)[:1]  # a field locator that lost the row
    with pytest.raises(module.Refused, match="could not be located"):
        module.sweep_csv("x.csv", text, "5")


def test_sweep_csv_refuses_when_the_span_does_not_cover_the_whole_refs_cell():
    module = _load()
    text = _HEADER + "2026-10-29,a,i,shipped,PR pending PR pending,k,s\n"
    real = module._spans

    def short(text):  # the refs span stops after the first `PR pending`: every other cell is still equal, refs is not what it should be
        spans = real(text)
        a, _ = spans[1][module._REFS]
        spans[1][module._REFS] = (a, a + len("PR pending"))
        return spans

    module._spans = short
    with pytest.raises(module.Refused, match="more than the refs cell"):
        module.sweep_csv("x.csv", text, "5")


def test_a_fragment_named_with_a_space_and_an_accent_is_swept_and_one_in_a_subdirectory_is_not(tmp_path):
    odd = _D + "lessons.d/2026-10-29-sp ace é.md"
    sub = _D + "lessons.d/sub/2026-10-29-s.md"
    root = _repo(tmp_path, {odd: _LESSON, sub: _LESSON, _D + "lessons.d/2026-10-29-t.md": _LESSON}, _OLD_MAIN)
    done = _sweep(root, "15")
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert (root / odd).read_text(encoding="utf-8").startswith("## 2026-10-29 — a lesson about #15 handling (PR #15)\n"), "the odd name was not seen"
    assert (root / _D / "lessons.d/2026-10-29-t.md").read_text(encoding="utf-8").startswith("## 2026-10-29 — a lesson about #15 handling")
    assert (root / sub).read_text(encoding="utf-8") == _LESSON, "a fragment in a subdirectory is not one the ledger reads, and was swept"


def test_a_root_below_the_repository_top_level_is_swept(tmp_path):
    main = {"sub/" + k: v for k, v in _OLD_MAIN.items()}
    root = _repo(tmp_path, {"sub/" + _D + "lessons.d/2026-10-29-t.md": _LESSON}, main)
    done = _sweep(root / "sub", "14")
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "(PR #14)" in (root / "sub" / _D / "lessons.d/2026-10-29-t.md").read_text(encoding="utf-8")


def test_a_fragment_main_removed_since_the_cut_is_not_the_branchs(tmp_path):
    root = _repo(tmp_path, _GOOD, _OLD_MAIN)
    old = _D + "lessons.d/2026-10-01-old.md"
    _git(root, "checkout", "-q", "main")
    _git(root, "rm", "-q", old)  # a release fold removes fragments from main after the branch was cut
    _git(root, "commit", "-q", "-m", "fold")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-q", "feat")
    kept = (root / old).read_text(encoding="utf-8")
    assert "#NNNN" in kept
    done = _sweep(root, "13")
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert (root / old).read_text(encoding="utf-8") == kept, "a fragment main removed was swept with this PR's number"
    assert "#13" in (root / _D / "lessons.d/2026-10-29-t.md").read_text(encoding="utf-8")


def test_histories_with_nothing_in_common_are_a_refusal_that_says_why(tmp_path):
    root = _repo(tmp_path, _GOOD, _OLD_MAIN)
    _git(root, "checkout", "-q", "--orphan", "island")
    _git(root, "commit", "-q", "-m", "island")
    done = _sweep(root, "5")
    assert done.returncode == 2 and "common ancestor" in done.stderr and "unshallow" in done.stderr, (done.returncode, done.stderr)


def test_a_symlinked_ledger_directory_is_refused_and_the_file_behind_it_is_not_rewritten(tmp_path):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-t.md": _LESSON}, _OLD_MAIN)
    outside = tmp_path / "outside"
    shutil.move(str(root / _D / "lessons.d"), str(outside))
    try:
        os.symlink(outside, root / _D / "lessons.d", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    before = (outside / "2026-10-29-t.md").read_bytes()
    done = _sweep(root, "18")
    assert done.returncode == 2 and "symlink" in done.stderr, (done.returncode, done.stdout, done.stderr)
    assert (outside / "2026-10-29-t.md").read_bytes() == before, "a file outside the repository was rewritten"


def test_a_file_name_that_is_not_utf8_is_a_refusal_not_a_traceback(tmp_path):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-ok.md": _LESSON}, _OLD_MAIN)
    odd = os.fsencode(str(root / _D / "lessons.d")) + b"/2026-10-29-\xff.md"
    try:
        with open(odd, "wb") as fh:
            fh.write(b"## 2026-10-29 - x (PR #NNNN)\n")
    except (OSError, ValueError):
        pytest.skip("this filesystem will not hold a file name that is not UTF-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "odd name")
    done = _sweep(root, "19")
    assert done.returncode == 2 and "UTF-8" in done.stderr and "Traceback" not in done.stderr, (done.returncode, done.stderr)
    assert (root / _D / "lessons.d/2026-10-29-ok.md").read_text(encoding="utf-8") == _LESSON, "a refusal wrote something"


@pytest.mark.skipif(os.name == "nt", reason="the interpreter needs the system environment on Windows")
def test_git_missing_from_the_path_is_a_refusal_not_a_traceback(tmp_path):
    env = {**os.environ, "PATH": str(tmp_path / "no-such-bin")}
    done = subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), "5", "--root", str(tmp_path)], capture_output=True, text=True, env=env, timeout=120
    )
    assert done.returncode == 2 and "git could not be run" in done.stderr and "Traceback" not in done.stderr, (done.returncode, done.stderr)


def test_an_output_stream_that_cannot_encode_the_text_does_not_crash_the_sweep(tmp_path):
    root = _repo(tmp_path, {_D + "lessons.d/2026-10-29-t.md": "## 2026-10-29 → an arrow (PR #NNNN)\n"}, _OLD_MAIN)
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}  # a Windows console redirected to a file; `-I` would ignore the variable
    done = subprocess.run([sys.executable, str(_SCRIPT), "17", "--root", str(root)], capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0 and "Traceback" not in done.stderr, (done.returncode, done.stdout, done.stderr)
    assert "\\u2192" in done.stdout, done.stdout
    assert (root / _D / "lessons.d/2026-10-29-t.md").read_text(encoding="utf-8") == "## 2026-10-29 → an arrow (PR #17)\n"
