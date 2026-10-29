"""Every ``item (N)`` that RULINGS_INDEX.md cites resolves to exactly one entry in OPEN_QUEUE.md.

The index points a reader at the queue by number ("user item (28)"). A number that names no entry,
or that names several, sends the reader to the wrong proposal or nowhere, and nothing else checks it:
the queue is prose, the index is prose, and the two are edited by different bundles.

MEASURED on main 6a81aa7ff, not assumed: the queue holds 127 entries that open ``(N) **``, but the
numbering RESTARTS between its sections, so ``(1)`` to ``(17)`` each appear several times and
only ``(18)`` to ``(30)`` are unique. So the rule is "a cited number has exactly one entry", which
today holds for all ten citations (items 20, 21, 26, 28, 29 and 30), and NOT "the numbering is
contiguous" (it has no gaps, but it is not unique below 18, so contiguity would say nothing).
A citation of an item below 18 would be refused as ambiguous, which is the intended pressure: name
the section instead.

Limits: the citation pattern is ``item (N)`` or ``items (N)`` anywhere in the index, so a future
row using that phrase for something that is not an OPEN_QUEUE item would be judged against the
queue; the fix then is to word it differently, not to loosen the test. The test checks that an
entry EXISTS, not that the row's claim about it is true, and only the number right after ``item``
or ``items`` is read, so the second number of "items (7) and (8)" is not judged (no row does that today).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "ledger" / "RULINGS_INDEX.md"
QUEUE = ROOT / "docs" / "ledger" / "OPEN_QUEUE.md"

_CITATION = re.compile(r"\bitems?\s+\((\d+)\)")
_ENTRY = re.compile(r"^\s*(?:[-*]\s+)?\((\d+)\)\s+\*\*", re.MULTILINE)


def cited_items(index_text: str) -> list[int]:
    return [int(n) for n in _CITATION.findall(index_text)]


def queue_entries(queue_text: str) -> Counter:
    return Counter(int(n) for n in _ENTRY.findall(queue_text))


def problems(index_text: str, queue_text: str) -> list[str]:
    """One line per cited number that names no entry or more than one."""
    entries = queue_entries(queue_text)
    out: list[str] = []
    for n in sorted(set(cited_items(index_text))):
        if entries[n] == 0:
            out.append(f"item ({n}) is cited but OPEN_QUEUE.md has no entry that opens '({n}) **'")
        elif entries[n] > 1:
            out.append(
                f"item ({n}) is cited but {entries[n]} OPEN_QUEUE.md entries open '({n}) **' "
                "(the numbering restarts between sections): name the section, not the number"
            )
    return out


def test_every_cited_queue_item_resolves_to_exactly_one_entry():
    bad = problems(INDEX.read_text(encoding="utf-8"), QUEUE.read_text(encoding="utf-8"))
    assert not bad, "\n".join(bad)


def test_the_two_readers_still_find_what_they_judge_by():
    """A reader that finds nothing makes the test above pass on an empty comparison."""
    cites = cited_items(INDEX.read_text(encoding="utf-8"))
    entries = queue_entries(QUEUE.read_text(encoding="utf-8"))
    assert cites, "no 'item (N)' citation found in RULINGS_INDEX.md: the pattern or the index changed"
    assert entries[30] == 1, "OPEN_QUEUE.md's entry (30) is not found exactly once: the entry pattern changed"
    assert sum(entries.values()) >= 30


@pytest.mark.parametrize(
    ("index_text", "queue_text", "needle"),
    [
        ("see user item (99).", "(1) **a** x\n", "item (99) is cited but OPEN_QUEUE.md has no entry"),
        ("see user item (5).", "(5) **a** x\n(5) **b** y\n", "2 OPEN_QUEUE.md entries"),
    ],
)
def test_the_checker_refuses_a_missing_and_an_ambiguous_number(index_text, queue_text, needle):
    got = problems(index_text, queue_text)
    assert any(needle in line for line in got), got


def test_the_checker_accepts_a_unique_entry_and_a_dash_led_one():
    assert problems("user item (21).", "intro\n(21) **q?** body\n") == []
    assert problems("user item (21).", "- (21) **q?** body\n") == []
    assert problems("nothing cited here", "") == []
