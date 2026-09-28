"""Side-by-side comparison of two stored versions — the one diff every reader draws.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q918's note asks that the law reader be "homogenous with other parts of the app's ability
to track change, such as wikipedia articles". The stored per-revision diffs cannot give
that on their own: a law revision's ``diff`` is a unified diff against whichever anchor
its ``diff_basis`` names, a wiki revision's is a compact ``+added / -removed`` summary
truncated per side, and neither can compare two versions the reader PICKS. So the one
comparison both readers draw is computed here, on this machine, from the two FULL texts
the versions hold — never from a stored diff, and never for a version whose text is not
held (the caller refuses that by name before it reaches this module).

THE COMPARISON IS BOUNDED, AND THE BOUND IS THE LANE'S. ``SequenceMatcher`` is quadratic
in the worst case, so past ``src.versioned.revisions``' published limits nothing is
computed and ``method`` says ``too-large``. The same two constants, imported rather than
restated: two limits for one hazard is how one reader draws a diff the other refuses.

NOTHING HERE IS A SCORE. The counts are lines, the statuses are a closed vocabulary, and
nothing is ranked. A one-character change to a date can matter more than a rewritten
paragraph; this module reports which lines differ and leaves the weighing to the reader.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.versioned.revisions import _MAX_DIFF_CHARS, _MAX_DIFF_LINES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

#: Unchanged lines kept on each side of a change. Longer unchanged runs fold into one
#: ``skip`` row that SAYS how many lines it hides, so the fold is never a silent cut.
CONTEXT_LINES = 3

#: Rows returned at most. Past it the payload says ``truncated`` and how many rows were
#: left out — the reader is told the comparison is partial rather than shown an ending.
MAX_ROWS = 4000

#: The closed vocabulary of a part's fate between two versions. ``unchanged`` IS a
#: member here (unlike ``src.wiki.sections``' change list): this list is a NAVIGATION,
#: and a provision nobody amended is still a place a reader may want to go.
PART_STATUSES: tuple[str, ...] = ("changed", "added", "removed", "unchanged")


@dataclass(frozen=True, slots=True)
class Part:
    """One addressable part of one version: a provision, or a wikitext section."""

    address: str
    label: str
    text: str


def _lines(text: str | None) -> list[str]:
    return (text or "").splitlines()


def side_by_side(before: str | None, after: str | None, *, context: int = CONTEXT_LINES) -> dict:
    """Two texts as aligned rows: ``eq`` · ``del`` · ``ins`` · ``chg`` · ``skip``.

    ``chg`` pairs the i-th removed line with the i-th added line of one replaced block;
    the surplus of the longer side becomes plain ``del`` or ``ins`` rows. Line numbers
    are 1-based and belong to each side, so a reader can cite "line 12 of the 2019 text".
    """
    a, b = _lines(before), _lines(after)
    size = len(before or "") + len(after or "")
    if len(a) + len(b) > _MAX_DIFF_LINES or size > _MAX_DIFF_CHARS:
        return {
            "method": "too-large",
            "rows": [],
            "added": None,
            "removed": None,
            "changed": None,
            "truncated": False,
            "omitted_rows": 0,
            "limits": {"lines": _MAX_DIFF_LINES, "chars": _MAX_DIFF_CHARS},
        }
    rows: list[dict] = []
    added = removed = changed = 0
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    opcodes = matcher.get_opcodes()
    for idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            n = i2 - i1
            head = context if idx > 0 else 0
            tail = context if idx < len(opcodes) - 1 else 0
            if n <= head + tail + 1:
                keep = range(n)
                rows.extend(
                    {"op": "eq", "l": a[i1 + k], "r": b[j1 + k], "ln": i1 + k + 1, "rn": j1 + k + 1}
                    for k in keep
                )
                continue
            rows.extend(
                {"op": "eq", "l": a[i1 + k], "r": b[j1 + k], "ln": i1 + k + 1, "rn": j1 + k + 1}
                for k in range(head)
            )
            rows.append({"op": "skip", "n": n - head - tail})
            rows.extend(
                {"op": "eq", "l": a[i2 - tail + k], "r": b[j2 - tail + k],
                 "ln": i2 - tail + k + 1, "rn": j2 - tail + k + 1}
                for k in range(tail)
            )
        elif tag == "replace":
            pairs = min(i2 - i1, j2 - j1)
            for k in range(pairs):
                rows.append({"op": "chg", "l": a[i1 + k], "r": b[j1 + k], "ln": i1 + k + 1, "rn": j1 + k + 1})
            changed += pairs
            for k in range(i1 + pairs, i2):
                rows.append({"op": "del", "l": a[k], "ln": k + 1})
                removed += 1
            for k in range(j1 + pairs, j2):
                rows.append({"op": "ins", "r": b[k], "rn": k + 1})
                added += 1
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append({"op": "del", "l": a[k], "ln": k + 1})
                removed += 1
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append({"op": "ins", "r": b[k], "rn": k + 1})
                added += 1
    identical = added == removed == changed == 0
    omitted = max(0, len(rows) - MAX_ROWS)
    return {
        "method": "identical" if identical else "line",
        "rows": rows[:MAX_ROWS],
        "added": added,
        "removed": removed,
        "changed": changed,
        "truncated": omitted > 0,
        "omitted_rows": omitted,
        "limits": {"lines": _MAX_DIFF_LINES, "chars": _MAX_DIFF_CHARS},
    }


def compare_parts(before: Sequence[Part] | None, after: Sequence[Part] | None) -> list[dict]:
    """The navigation list: every part of either version, with its fate between them.

    Ordered as the NEWER version orders its parts, with parts only the older version had
    placed after the part that preceded them there — so a repealed section appears where
    it used to be, not at the bottom where it would read as the newest.

    A side that is ``None`` has no parts at all (its text was not split); the caller
    reports that instead of calling this, because "every part was added" is what this
    function would otherwise say, and it would be false.
    """
    old = {p.address: p for p in (before or ())}
    new = {p.address: p for p in (after or ())}
    order: list[str] = [p.address for p in (after or ())]
    seen = set(order)
    prev_in_old: str | None = None
    for p in before or ():
        if p.address not in seen:
            # prev_in_old is always already placed (a part of the newer version, or a
            # removed part inserted on an earlier turn), so successive removed parts
            # keep their old order.
            at = order.index(prev_in_old) + 1 if prev_in_old is not None else 0
            order.insert(at, p.address)
            seen.add(p.address)
        prev_in_old = p.address
    out = []
    for address in order:
        o, n = old.get(address), new.get(address)
        if o is None:
            status = "added"
        elif n is None:
            status = "removed"
        elif o.text == n.text:
            status = "unchanged"
        else:
            status = "changed"
        out.append({"address": address, "label": (n or o).label, "status": status})  # type: ignore[union-attr]
    return out


def part_text(parts: Sequence[Part] | None, address: str) -> str | None:
    """One part's text, or ``None`` when that version has no part at this address."""
    for p in parts or ():
        if p.address == address:
            return p.text
    return None
