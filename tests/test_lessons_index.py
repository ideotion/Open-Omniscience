"""PF11 = D07 = b (2026-09-30): LESSONS.md is consulted by grep through a generated index.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The two ways this tool dies (the same pair tests/test_planned_index.py pins): it stops
finding things, or it finds so much that every answer is the same answer. Plus the
protocol facts the ruling changed, so the text and the tool cannot drift apart.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import lessons  # noqa: E402


def _entries():
    lines, entries = lessons.load()
    return lines, entries


def test_it_finds_the_entries_and_does_not_lose_them():
    lines, entries = _entries()
    # 739 at the time of writing (618 bullets + 121 heading lessons); a parser that stops matching a shape collapses this.
    assert len(entries) >= 700, f"only {len(entries)} entries parsed -- the parser lost a shape"
    assert all(e.title for e in entries), "an entry parsed with an empty title"
    starts = [e.line for e in entries]
    assert starts == sorted(set(starts)), "entry starts must be strictly increasing"
    # every entry's own text is non-empty and the ranges tile the file after the first entry
    for a, b in zip(entries, entries[1:], strict=False):
        assert a.end == b.line - 1, (a, b)


def test_every_heading_lesson_is_an_entry_of_its_own():
    """The newest ~120 lessons are `##`/`###` headings, not bullets. A parser that only knows
    bullets folds them into the bullet above (one entry ran 1,805 lines to the end of the file),
    so a search for them returns some other lesson's title -- the every-answer-the-same-answer
    failure. The tiling check above is true by construction and cannot see this; this compares
    against an independent count taken straight from the file, skipping code fences."""
    lines, entries = _entries()
    starts = {e.line for e in entries}
    fenced = False
    headings = []
    for n, ln in enumerate(lines, 1):
        if ln.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and ln.startswith("#") and not ln.startswith("# "):
            headings.append(n)
    assert len(headings) >= 100, "the file lost its heading lessons?"
    missing = [n for n in headings if n not in starts]
    assert not missing, f"heading lessons that are not entries: lines {missing[:10]}"
    longest = max(e.end - e.line for e in entries)
    assert longest < 600, f"an entry spans {longest} lines -- a lesson shape is being swallowed"


def test_a_heading_lesson_is_found_by_its_own_words_and_shown_whole():
    lines, entries = _entries()
    hits = lessons.search(lines, entries, ["audit's unit is the fact"])
    assert [e.title for e, _ in hits][:1] and "AN AUDIT'S UNIT IS THE FACT" in hits[0][0].title
    e = hits[0][0]
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lessons.py"), "--show", str(e.line)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("## 2026-09-18")


def test_an_empty_query_or_an_unknown_flag_is_refused_not_everything():
    script = str(ROOT / "scripts" / "lessons.py")
    for argv in (['""'], ["--bogus"]):
        proc = subprocess.run([sys.executable, script, *[a.strip('"') for a in argv]],
                              capture_output=True, text=True, check=False)
        assert proc.returncode == 2, (argv, proc.stdout[:80])


def test_a_search_is_selective_not_everything():
    lines, entries = _entries()
    every = lessons.search(lines, entries, ["the"])
    narrow = lessons.search(lines, entries, ["shallow", "clone"])
    assert 1 <= len(narrow) < 10, f"a two-word search returned {len(narrow)} entries"
    assert len(narrow) < len(every), "a narrower query must return fewer entries"
    nothing = lessons.search(lines, entries, ["zzqxjv-not-a-word"])
    assert nothing == []


def test_a_hit_lands_on_the_most_specific_entry_not_the_enclosing_bullet():
    """Two thirds of the entries nest inside one 'Lessons harvested' bullet; attributing a hit
    to that parent would make every answer the same answer."""
    lines, entries = _entries()
    hits = lessons.search(lines, entries, ["shallow", "clone"])
    parent = next(e for e in entries if e.title.startswith("Lessons harvested from the shipped log"))
    assert all(e.line != parent.line for e, _ in hits)


def test_show_prints_exactly_the_entry_that_starts_at_a_line():
    lines, entries = _entries()
    e = next(x for x in entries if x.title.startswith("A SESSION CLONE IS SHALLOW"))
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lessons.py"), "--show", f"L{e.line}"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(lines[e.line - 1].rstrip()[:40])
    miss = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lessons.py"), "--show", "1"],
        capture_output=True, text=True, check=False,
    )
    assert miss.returncode == 1


def test_the_index_is_generated_never_committed():
    """A checked-in index is stale whenever a lesson is added or moved (rule (7)'s reasoning)."""
    committed = [p for p in (ROOT / "docs" / "ledger").glob("*") if "LESSONS_INDEX" in p.name.upper()]
    assert not committed, f"a committed lessons index will go stale: {committed}"


def test_the_protocol_text_and_the_file_agree_that_it_is_consulted_not_read_in_full():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "scripts/lessons.py" in claude
    assert "no longer read in full" in claude
    assert "test_lessons_md_stays_within_its_ratchet" in claude
    header = (ROOT / "docs" / "ledger" / "LESSONS.md").read_text(encoding="utf-8").split("- **Lessons harvested", 1)[0]
    assert "MANDATORY READING every session" not in header
    assert "CONSULTED BY GREP" in header
