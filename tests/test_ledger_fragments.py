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
    (led / "LESSONS.md").write_text("# Lessons\n\n## 2026-01-01 — OLD ONE\nbody one\n\n## 2026-01-02 — OLD TWO\nbody two\n", encoding="utf-8")
    (led / "SHIPPED_LOG.md").write_text("# Log\n\n## 2026-01-01 — first (PR #1)\nentry\n", encoding="utf-8")
    inv = tmp_path / "tests" / "test_repo_invariants.py"
    inv.write_text("_LESSONS_LINE_CEILING = 7\n", encoding="utf-8")
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
    path.write_text(text, encoding="utf-8")
    return path


def test_the_real_fragments_are_well_formed_and_within_the_size_cap():
    """The only test that reads the live tree: a malformed or oversize fragment fails on its own PR."""
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
    assert ledger_fold.problems() == []
    assert lessons.main(["--new", "a-fresh-lesson", "--date", "2026-03-04"]) == 1  # already there
    assert lessons.main(["--new", "Bad Slug"]) == 2
    assert lessons.main(["--new", "ok-slug", "--date", "yesterday"]) == 2
    assert ledger_fold.main(["new-log", "a-log-entry", "--date", "2026-03-04"]) == 0
    assert ledger_fold.problems() == []
    capsys.readouterr()


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
