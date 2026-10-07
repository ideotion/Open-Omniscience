"""One-file-per-entry fragments for LESSONS.md and SHIPPED_LOG.md (protocol rule (5a)(b), 2026-10-06).

The failure this exists for: a PR appended its lesson to the tail of LESSONS.md and raised the shared
``_LESSONS_LINE_CEILING``, so every landing re-conflicted every other open PR in those places. The
tests below pin the three ways the convention dies: the fragments stop being found (a lesson
vanishes from ``lessons.py``), a fold loses or duplicates text or leaves the ceiling wrong, and the
protocol text drifts from the tool.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_fold  # noqa: E402
import lessons  # noqa: E402


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A throwaway ledger: an archive of two entries, an invariants file with a ceiling, empty fragment dirs."""
    led = tmp_path / "docs" / "ledger"
    led.mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    # bytes, never write_text: Windows text mode would turn every \n into \r\n and the LF-only checks would fail
    (led / "LESSONS.md").write_bytes("# Lessons\n\n## 2026-01-01 — OLD ONE\nbody one\n\n## 2026-01-02 — OLD TWO\nbody two\n".encode())
    (led / "SHIPPED_LOG.md").write_bytes("# Log\n\n## 2026-01-01 — first (PR #1)\nentry\n".encode())
    inv = tmp_path / "tests" / "test_repo_invariants.py"
    inv.write_bytes(b"_LESSONS_LINE_CEILING = 7\n")
    for mod, names in ((ledger_fold, {"LESSONS": "LESSONS.md", "SHIPPED_LOG": "SHIPPED_LOG.md"}),):
        for attr, f in names.items():
            monkeypatch.setattr(mod, attr, led / f)
    monkeypatch.setattr(ledger_fold, "LESSONS_D", led / "lessons.d")
    monkeypatch.setattr(ledger_fold, "SHIPPED_LOG_D", led / "shipped_log.d")
    monkeypatch.setattr(ledger_fold, "INVARIANTS", inv)
    monkeypatch.setattr(lessons, "LESSONS", led / "LESSONS.md")
    monkeypatch.setattr(lessons, "FRAGMENTS", led / "lessons.d")
    return tmp_path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # LF on every platform: the checker refuses CRLF
    return path


def test_the_real_fragments_are_well_formed_and_within_the_size_cap():
    """One of the tests that read the live tree (this, the protocol-text pins, the ceiling-line match and the
    command run): a malformed or oversize fragment fails on its own PR."""
    assert ledger_fold.problems() == []


def test_a_fragment_is_found_indexed_shown_and_tiles_with_the_archive(tree):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "2026-02-01-alpha-lesson.md", "## 2026-02-01 — ALPHA LESSON\nzzuniqueword is the point.\n")
    _write(led / "lessons.d" / "2026-02-02-beta-lesson.md", "## 2026-02-02 — BETA LESSON\nsecond.\n")
    lines, entries = lessons.load()
    hits = lessons.search(lines, entries, ["zzuniqueword"])
    assert [(e.title, e.source) for e, _ in hits] == [("2026-02-01 — ALPHA LESSON", "2026-02-01-alpha-lesson.md")]
    # the archive's own entries are untouched and still carry no source
    assert [e.source for e in entries] == ["", "", "2026-02-01-alpha-lesson.md", "2026-02-02-beta-lesson.md"]
    for a, b in zip(entries, entries[1:], strict=False):
        assert a.end == b.line - 1, (a, b)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lessons.py"), "--show", "x.md"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 1  # an unknown fragment is refused, never an empty success
    assert "ALPHA LESSON" in "\n".join(lines[entries[2].line - 1 : entries[2].end])


def test_the_new_command_writes_a_fragment_the_checker_accepts_and_never_overwrites(tree, capsys):
    assert lessons.main(["--new", "a-fresh-lesson", "--date", "2026-03-04"]) == 0
    made = tree / "docs" / "ledger" / "lessons.d" / "2026-03-04-a-fresh-lesson.md"
    assert made.is_file() and made.read_text(encoding="utf-8").startswith("## 2026-03-04 — a fresh lesson")
    assert "the untouched template text" in "\n".join(ledger_fold.problems()), "an unwritten --new fragment must not pass"
    assert lessons.main(["--new", "a-fresh-lesson", "--date", "2026-03-04"]) == 1  # already there
    assert lessons.main(["--new", "Bad Slug"]) == 2
    assert lessons.main(["--new", "ok-slug", "--date", "yesterday"]) == 2
    assert ledger_fold.main(["new-log", "a-log-entry", "--date", "2026-03-04"]) == 0
    logs = "\n".join(p for p in ledger_fold.problems() if "shipped_log.d" in p)
    assert "#NNNN" in logs and "untouched template" in logs
    assert ledger_fold.main(["new-log", "a-log-entry", "--date", "2026-03-04"]) == 1
    # slug, date and existing-name refusal, for both commands (a refusal writes nothing)
    n = len(list((tree / "docs" / "ledger").rglob("*.md")))
    for cmd in (lambda *a: lessons.main(["--new", *a]), lambda *a: ledger_fold.main(["new-log", *a])):
        assert cmd("Bad Slug") == 2 and cmd("ab") == 2 and cmd("../escape-x") == 2
        assert cmd("ok-slug", "--date", "2026-02-30") == 2 and cmd("ok-slug", "--date", "٢٠٢٦-٠١-٠١") == 2
    assert len(list((tree / "docs" / "ledger").rglob("*.md"))) == n
    capsys.readouterr()


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # Windows without the privilege
        pytest.skip("this platform cannot create symlinks here")


def test_creation_never_writes_through_a_dangling_symlink(tree):
    d = tree / "docs" / "ledger" / "lessons.d"
    d.mkdir()
    _symlink(d / "2026-03-05-linked-lesson.md", tree / "elsewhere.md")
    assert lessons.main(["--new", "linked-lesson", "--date", "2026-03-05"]) == 1
    assert not (tree / "elsewhere.md").exists()


def test_the_checker_names_each_defect_and_the_size_cap(tree):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "not-dated.md", "## x\n")
    _write(led / "lessons.d" / "2026-02-01-no-heading.md", "plain text\n")
    _write(led / "lessons.d" / "2026-02-02-two-lessons.md", "## 2026-02-02 — A\nx\n## B\ny\n")
    _write(led / "lessons.d" / "2026-02-03-marker.md", "## 2026-02-03 — M\n<<<<<<< HEAD\nx\n")
    big = "## 2026-02-04 — BIG\n" + "line\n" * ledger_fold.LESSON_FRAGMENT_MAX_LINES
    _write(led / "lessons.d" / "2026-02-04-big.md", big)
    _write(led / "lessons.d" / "2026-02-05-no-newline.md", "## 2026-02-05 — N")
    text = "\n".join(ledger_fold.problems())
    for needle in ("not-dated.md: the name must be", "no-heading.md: the first line", "two-lessons.md: one lesson per file",
                   "marker.md: an unresolved", f"over the {ledger_fold.LESSON_FRAGMENT_MAX_LINES}-line cap", "no-newline.md: must end"):
        assert needle in text, (needle, text)
    # exactly at the cap is fine
    ok = "## 2026-02-06 — AT CAP\n" + "line\n" * (ledger_fold.LESSON_FRAGMENT_MAX_LINES - 1)
    for f in (led / "lessons.d").glob("*.md"):
        f.unlink()
    _write(led / "lessons.d" / "2026-02-06-at-cap.md", ok)
    assert ledger_fold.problems() == []


def test_the_check_rules_a_replaced_ledger_check_used_to_make(tree):
    led = tree / "docs" / "ledger"
    d = led / "lessons.d"
    _write(d / "2026-02-01-placeholder.md", "## 2026-02-01 — P\nShipped in PR #NNNN.\n")
    _write(d / "2026-02-02-pending.md", "## 2026-02-02 — Q\nrefs: PR pending\n")
    _write(d / "2026-02-03-dup-a.md", "## 2026-02-03 — SAME TITLE\nx\n")
    _write(d / "2026-02-03-dup-b.md", "## 2026-02-03 — SAME TITLE\ny\n")
    _write(d / "2026-02-04-in-archive.md", "## 2026-01-01 — OLD ONE\nz\n")
    _write(d / "2026-02-05-fence.md", "## 2026-02-05 — F\n```\ncode never closed\n")
    _write(d / "2026-02-06-fenced-hash.md", "## 2026-02-06 — H\n```\n## not a heading, inside a fence\n```\nok\n")
    _write(d / "2026-02-07-hash-heading.md", "## 2026-02-07 — K\n### a deeper heading\n")
    _write(d / "2026-02-30-bad-date.md", "## 2026-02-30 — D\nx\n")
    (d / "2026-02-08-latin1.md").write_bytes(b"## 2026-02-08 \xe9\n")
    (d / "2026-02-09-crlf.md").write_bytes(b"## 2026-02-09 \xe2\x80\x94 C\r\nx\r\n")
    text = "\n".join(ledger_fold.problems())
    for needle in ("placeholder.md: a placeholder", "pending.md: a placeholder", "dup-b.md: the same title as lessons.d/2026-02-03-dup-a.md",
                   "in-archive.md: the same title as an entry already in the archive", "fence.md: an unclosed code fence",
                   "hash-heading.md: one lesson per file", "bad-date.md: 2026-02-30 is not a real date",
                   "latin1.md: not valid UTF-8", "crlf.md: CRLF"):
        assert needle in text, (needle, text)
    assert "fenced-hash.md" not in text, "a # line inside a fence is not a second heading"
    # lessons.py names the bad fragment instead of crashing, and still serves the rest
    lines, entries = lessons.load()
    assert any(e.source == "2026-02-06-fenced-hash.md" for e in entries)
    assert not any(e.source == "2026-02-08-latin1.md" for e in entries)


def test_a_shipped_log_fragment_defect_is_named(tree):
    _write(tree / "docs" / "ledger" / "shipped_log.d" / "2026-02-01-logx.md", "no heading (PR #NNNN)\n")
    text = "\n".join(ledger_fold.problems())
    assert "shipped_log.d/2026-02-01-logx.md: the first line" in text and "a placeholder" in text


def test_check_runs_as_a_command_and_reports_a_defect(tree):
    ok = subprocess.run([sys.executable, str(ROOT / "scripts" / "ledger_fold.py"), "check"], capture_output=True, text=True, check=False)
    assert ok.returncode == 0 and "ok" in ok.stdout  # the real tree
    assert ledger_fold.main(["check"]) == 0
    _write(tree / "docs" / "ledger" / "lessons.d" / "2026-02-01-bad.md", "no heading\n")
    assert ledger_fold.main(["check"]) == 1


def test_show_prints_a_whole_fragment_by_file_name(tree, capsys):
    _write(tree / "docs" / "ledger" / "lessons.d" / "2026-02-01-whole.md", "## 2026-02-01 — WHOLE\nline a\n### sub\nline b\n")
    assert lessons.main(["--show", "2026-02-01-whole.md"]) == 0
    out = capsys.readouterr().out
    assert "line a" in out and "### sub" in out and "line b" in out
    assert lessons.main(["--show", "../x.md"]) == 1
    assert lessons.main(["--index"]) == 0
    idx = capsys.readouterr().out
    assert "L3 " in idx or "L3" in idx.split()[0]


def test_fragments_sort_by_name_with_same_date_and_prefix_names(tree):
    led = tree / "docs" / "ledger"
    for k, slug in enumerate(("alpha-two", "alpha", "alpha-one")):
        _write(led / "lessons.d" / f"2026-02-01-{slug}.md", f"## 2026-02-01 — T{k}\nbody-{slug}-end\n")
    assert ledger_fold.main(["fold"]) == 0
    got = (led / "LESSONS.md").read_bytes()
    # file-name order: "-" sorts before "." so alpha-one < alpha-two < alpha (a prefix name comes last here)
    pos = [got.index(f"body-{slug}-end".encode()) for slug in ("alpha-one", "alpha-two", "alpha")]
    assert pos == sorted(pos)


def test_a_fold_appends_in_name_order_deletes_the_fragments_and_sets_the_ceiling(tree):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "2026-02-02-second.md", "## 2026-02-02 — SECOND\nb\n")
    _write(led / "lessons.d" / "2026-02-01-first.md", "## 2026-02-01 — FIRST\na\n")
    _write(led / "shipped_log.d" / "2026-02-01-log.md", "## 2026-02-01 — logged (PR #9)\nentry\n")
    before = (led / "LESSONS.md").read_bytes()
    assert ledger_fold.main(["fold"]) == 0
    after = (led / "LESSONS.md").read_bytes()
    assert after.startswith(before), "a fold only appends; it never rewrites the archive"
    assert after.index(b"FIRST") < after.index(b"SECOND")
    assert b"\r" not in after
    assert not list((led / "lessons.d").glob("*.md")) and not list((led / "shipped_log.d").glob("*.md"))
    assert b"logged (PR #9)" in (led / "SHIPPED_LOG.md").read_bytes()
    n = after.count(b"\n")
    assert (tree / "tests" / "test_repo_invariants.py").read_text(encoding="utf-8") == f"_LESSONS_LINE_CEILING = {n}\n"
    # nothing left to fold: a second fold is a no-op that still leaves the ceiling equal to the count
    assert ledger_fold.main(["fold"]) == 0
    assert (led / "LESSONS.md").read_bytes() == after


def test_a_fold_refuses_a_broken_fragment_and_changes_nothing(tree):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "2026-02-01-bad.md", "no heading\n")
    before = (led / "LESSONS.md").read_bytes()
    assert ledger_fold.main(["fold"]) == 1
    assert (led / "LESSONS.md").read_bytes() == before
    assert (led / "lessons.d" / "2026-02-01-bad.md").exists()


def test_the_protocol_text_names_the_fragments_and_the_tool_that_folds_them():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for needle in ("docs/ledger/lessons.d/", "docs/ledger/shipped_log.d/", "scripts/lessons.py --new",
                   "scripts/ledger_fold.py new-log", "ledger_fold.py fold", "LESSON_FRAGMENT_MAX_LINES"):
        assert needle in claude, needle
    header = (ROOT / "docs" / "ledger" / "LESSONS.md").read_text(encoding="utf-8").split("- **Lessons harvested", 1)[0]
    assert "lessons.d/" in header and "NEW FILE" in header
    assert re.search(r"LESSON_FRAGMENT_MAX_LINES = \d+", (ROOT / "scripts" / "ledger_fold.py").read_text(encoding="utf-8"))
    # the prose copies of the bound say the constant's value, so changing one without the others fails here
    n = ledger_fold.LESSON_FRAGMENT_MAX_LINES
    assert f"({n} lines:" in claude, "CLAUDE.md (5a)(b) states the bound"
    assert f"`LESSON_FRAGMENT_MAX_LINES` = {n} lines" in header, "the LESSONS.md header states the bound"
    assert f"under {n} lines" in (ROOT / "docs" / "CONTRIBUTING.md").read_text(encoding="utf-8"), "CONTRIBUTING states the bound"


def _two_fragments(led):
    _write(led / "lessons.d" / "2026-02-01-one.md", "## 2026-02-01 — ONE\na\n")
    _write(led / "lessons.d" / "2026-02-02-two.md", "## 2026-02-02 — TWO\nb\n")
    _write(led / "shipped_log.d" / "2026-02-01-log.md", "## 2026-02-01 — logged (PR #9)\nentry\n")


def test_a_fold_deletes_only_the_files_it_folded_by_exact_path(tree):
    led = tree / "docs" / "ledger"
    _two_fragments(led)
    keep = _write(led / "lessons.d" / "README.txt", "not a fragment\n")
    other = _write(led / "elsewhere" / "2026-02-01-one.md", "## 2026-02-01 — ONE\nsame name, other directory\n")
    assert ledger_fold.main(["fold"]) == 0
    assert keep.exists() and other.exists()
    assert not list((led / "lessons.d").glob("*.md")) and not list((led / "shipped_log.d").glob("*.md"))


def test_a_fold_interrupted_while_deleting_does_not_append_twice_on_the_rerun(tree, monkeypatch):
    led = tree / "docs" / "ledger"
    _two_fragments(led)
    real = ledger_fold._remove
    calls = []

    def flaky(path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("interrupted")
        real(path)

    monkeypatch.setattr(ledger_fold, "_remove", flaky)
    with pytest.raises(OSError):
        ledger_fold.main(["fold"])
    monkeypatch.setattr(ledger_fold, "_remove", real)
    survivors = list((led / "lessons.d").glob("*.md")) + list((led / "shipped_log.d").glob("*.md"))
    assert survivors, "the interruption left fragments behind"
    assert ledger_fold.main(["fold"]) == 0  # the survivors are already in the archive: skipped, then deleted
    data = (led / "LESSONS.md").read_bytes()
    assert data.count("— ONE\n".encode()) == 1 and data.count("— TWO\n".encode()) == 1
    assert (led / "SHIPPED_LOG.md").read_bytes().count(b"logged (PR #9)") == 1
    assert not list((led / "lessons.d").glob("*.md")) and not list((led / "shipped_log.d").glob("*.md"))
    n = data.count(b"\n")
    assert (tree / "tests" / "test_repo_invariants.py").read_text(encoding="utf-8") == f"_LESSONS_LINE_CEILING = {n}\n"


def test_a_torn_fold_keeps_every_fragment_and_the_rerun_completes_it(tree, monkeypatch):
    led = tree / "docs" / "ledger"
    _two_fragments(led)
    before = {n: (led / n).read_bytes() for n in ("LESSONS.md", "SHIPPED_LOG.md")}
    real = ledger_fold._atomic_write
    n = []

    def torn(path, data):
        n.append(path.name)
        if len(n) == 2:  # LESSONS.md written, SHIPPED_LOG.md not
            raise OSError("torn")
        real(path, data)

    monkeypatch.setattr(ledger_fold, "_atomic_write", torn)
    with pytest.raises(OSError):
        ledger_fold.main(["fold"])
    assert (led / "SHIPPED_LOG.md").read_bytes() == before["SHIPPED_LOG.md"], "the failed archive is whole, not truncated"
    assert (led / "lessons.d" / "2026-02-01-one.md").exists() and (led / "shipped_log.d" / "2026-02-01-log.md").exists()
    monkeypatch.setattr(ledger_fold, "_atomic_write", real)
    assert ledger_fold.main(["fold"]) == 0
    assert (led / "LESSONS.md").read_bytes().count("— ONE\n".encode()) == 1
    assert b"logged (PR #9)" in (led / "SHIPPED_LOG.md").read_bytes()


def test_a_noop_fold_leaves_the_bytes_and_the_ceiling_untouched(tree):
    led = tree / "docs" / "ledger"
    inv = tree / "tests" / "test_repo_invariants.py"
    n = (led / "LESSONS.md").read_bytes().count(b"\n")
    inv.write_text(f"# header\n_LESSONS_LINE_CEILING = {n}\n# footer\n", encoding="utf-8")
    snap = {f: f.stat().st_mtime_ns for f in (inv, led / "LESSONS.md", led / "SHIPPED_LOG.md")}
    bytes_before = (inv.read_bytes(), (led / "LESSONS.md").read_bytes())
    assert ledger_fold.main(["fold"]) == 0
    assert (inv.read_bytes(), (led / "LESSONS.md").read_bytes()) == bytes_before
    assert {f: f.stat().st_mtime_ns for f in snap} == snap, "nothing was even rewritten"


def test_the_ceiling_regex_matches_the_real_line_and_a_fold_refuses_without_it(tree):
    real = (ROOT / "tests" / "test_repo_invariants.py").read_text(encoding="utf-8")
    assert len(ledger_fold._CEILING.findall(real)) == 1, "the fold's pattern must find the live ceiling line exactly once"
    led = tree / "docs" / "ledger"
    _two_fragments(led)
    (tree / "tests" / "test_repo_invariants.py").write_text("no ceiling here\n", encoding="utf-8")
    before = (led / "LESSONS.md").read_bytes()
    assert ledger_fold.main(["fold"]) == 1
    assert (led / "LESSONS.md").read_bytes() == before and (led / "lessons.d" / "2026-02-01-one.md").exists()


def test_a_fragment_that_is_only_the_start_of_an_existing_entry_is_folded_not_skipped(tree):
    led = tree / "docs" / "ledger"
    long_entry = "## 2026-03-01 — LONG ENTRY\nline one\nline two\n\nline four after a blank\n"
    (led / "LESSONS.md").write_bytes((led / "LESSONS.md").read_bytes() + b"\n" + long_entry.encode())
    prefix = "## 2026-03-01 — LONG ENTRY\nline one\nline two\n"  # a line-aligned prefix of the entry above
    _write(led / "lessons.d" / "2026-03-02-prefix.md", prefix.replace("2026-03-01", "2026-03-02"))
    _write(led / "lessons.d" / "2026-03-03-exact.md", "## 2026-03-03 — EXACT\nbody\n")
    # a true prefix of an existing entry, with the SAME first line, must not be taken for "already folded"
    _write(led / "lessons.d" / "2026-03-01-prefix-same.md", prefix)
    before = (led / "LESSONS.md").read_bytes()
    assert ledger_fold._already_in(before, led / "lessons.d" / "2026-03-01-prefix-same.md") is False
    assert ledger_fold.main(["fold"]) == 1, "its title is a duplicate of the archive's, and it is named, not swallowed"
    (led / "lessons.d" / "2026-03-01-prefix-same.md").unlink()
    assert ledger_fold.main(["fold"]) == 0
    assert (led / "LESSONS.md").read_bytes().count(b"line one") == 2  # the original and the folded copy


def test_the_fold_reports_skipped_fragments_apart_from_folded_ones(tree, capsys):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "2026-02-01-one.md", "## 2026-02-01 — ONE\na\n")
    assert ledger_fold.main(["fold"]) == 0
    capsys.readouterr()
    _write(led / "lessons.d" / "2026-02-01-one.md", "## 2026-02-01 — ONE\na\n")  # the interrupted-run leftover
    _write(led / "lessons.d" / "2026-02-02-two.md", "## 2026-02-02 — TWO\nb\n")
    assert ledger_fold.main(["fold"]) == 0
    out = capsys.readouterr().out
    assert "folded 1 fragment(s) (1 already in an archive, only deleted)" in out, out


def test_os_replace_failing_after_the_temp_write_leaves_the_archive_untouched(tree, monkeypatch):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "2026-02-01-one.md", "## 2026-02-01 — ONE\na\n")
    before = (led / "LESSONS.md").read_bytes()

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(ledger_fold.os, "replace", boom)
    with pytest.raises(OSError):
        ledger_fold.main(["fold"])
    assert (led / "LESSONS.md").read_bytes() == before, "the archive is whole: the write goes to a temp file first"
    assert (led / "lessons.d" / "2026-02-01-one.md").exists()


def test_a_failed_delete_leaves_the_ceiling_alone(tree, monkeypatch):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "2026-02-01-one.md", "## 2026-02-01 — ONE\na\n")
    inv = tree / "tests" / "test_repo_invariants.py"
    before = inv.read_bytes()

    def boom(path):
        raise OSError("delete failed")

    monkeypatch.setattr(ledger_fold, "_remove", boom)
    with pytest.raises(OSError):
        ledger_fold.main(["fold"])
    assert inv.read_bytes() == before, "the ceiling moves last, after every delete"


def test_a_fold_refuses_when_the_ceiling_line_is_not_there_exactly_once_or_a_file_is_missing(tree):
    led = tree / "docs" / "ledger"
    _two_fragments(led)
    inv = tree / "tests" / "test_repo_invariants.py"
    inv.write_bytes(b"_LESSONS_LINE_CEILING = 7\n_LESSONS_LINE_CEILING = 8\n")
    before = (led / "LESSONS.md").read_bytes()
    assert ledger_fold.main(["fold"]) == 1 and (led / "LESSONS.md").read_bytes() == before
    inv.write_bytes(b"_LESSONS_LINE_CEILING = 7\n")
    (led / "SHIPPED_LOG.md").unlink()
    assert ledger_fold.main(["fold"]) == 1 and (led / "LESSONS.md").read_bytes() == before
    assert (led / "lessons.d" / "2026-02-01-one.md").exists()


def test_heading_date_rule_log_second_headings_and_case_insensitive_placeholders(tree):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "2026-02-01-other-date.md", "## 2026-02-09 — WRONG DATE\nx\n")
    _write(led / "lessons.d" / "2026-02-02-lower.md", "## 2026-02-02 — LOWER\nrefs: pr pending, and #nnnn\n")
    _write(led / "lessons.d" / "2026-02-03-spaced.md", "## 2026-02-03 — SPACED\nrefs: PR   pending\n")
    _write(led / "shipped_log.d" / "2026-02-04-log-two.md", "## 2026-02-04 — LOG (PR #9)\nx\n## 2026-02-05 — a second heading is fine here\ny\n")
    text = "\n".join(ledger_fold.problems())
    assert "other-date.md: the heading must start with the file's date" in text
    assert "lower.md: a placeholder" in text and "spaced.md: a placeholder" in text
    assert "log-two.md" not in text, "a shipped-log entry may carry sub-headings; only a lesson is one entry"


def test_a_quoted_placeholder_is_prose_not_a_placeholder(tree):
    led = tree / "docs" / "ledger"
    _write(led / "lessons.d" / "2026-02-01-quoted.md",
           "## 2026-02-01 — QUOTED\nA row may say `PR pending`, and `#NNNN` is the template's:\n```\nPR pending\n```\n")
    assert ledger_fold.problems() == []


def test_a_symlinked_fragment_is_named_and_never_followed_or_folded(tree):
    led = tree / "docs" / "ledger"
    outside = _write(tree / "outside" / "secret.md", "## 2026-02-01 — OUTSIDE\nnot a fragment\n")
    (led / "lessons.d").mkdir()
    _symlink(led / "lessons.d" / "2026-02-01-linked.md", outside)
    assert "linked.md: a symlink" in "\n".join(ledger_fold.problems())
    assert ledger_fold.main(["fold"]) == 1
    assert b"OUTSIDE" not in (led / "LESSONS.md").read_bytes()
    lines, entries = lessons.load()
    assert not any(e.source == "2026-02-01-linked.md" for e in entries)


def test_the_index_is_aligned_and_show_refuses_a_path(tree, capsys):
    assert lessons.main(["--index"]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert re.match(r"L\d+ +", first) and re.match(r"L\d+ +", first).end() == 8, first  # width 7, one space
    sub = tree / "docs" / "ledger" / "lessons.d" / "sub"
    _write(sub / "x.md", "## 2026-02-01 — X\nb\n")
    assert lessons.main(["--show", "sub/x.md"]) == 1, "a path is not a fragment name"
    assert lessons.main(["--show", "..\\x.md"]) == 1
