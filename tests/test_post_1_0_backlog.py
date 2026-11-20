"""`docs/product/POST_1.0_BACKLOG.md`: every ruling it cites resolves (0.9 gate row H, Q118 = a; rows 219-220).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The file is a list of decisions, so the one way it can rot is by citing a ruling that does not exist, or by an item
that cites nothing. A Q, R or RC id must be a first-column id of ``docs/ledger/RULINGS_INDEX.md``; a V1-n id predates
the index and must be a row of the V1 pathway's §7 table. Mutation-checked by hand: an id renamed to one that does
not exist reddens the first test, and a bullet stripped of its "Ruling" clause reddens the second.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / "docs" / "product" / "POST_1.0_BACKLOG.md"
INDEX = ROOT / "docs" / "ledger" / "RULINGS_INDEX.md"
V1 = ROOT / "docs" / "design" / "V1_PATHWAY_2026-07-14.md"

_ID = re.compile(r"\b(V1-\d|RC\d{1,2}|Q\d{3,4}|R\d{1,4})\b")


def _index_ids() -> set[str]:
    return {m.group(1) for m in re.finditer(r"^\| ([A-Z][A-Z0-9-]*\d) \|", INDEX.read_text(encoding="utf-8"), re.M)}


def _v1_ids() -> set[str]:
    return {m.group(1) for m in re.finditer(r"^\| (V1-\d) \|", V1.read_text(encoding="utf-8"), re.M)}


def _bullets() -> list[str]:
    return [ln for ln in BACKLOG.read_text(encoding="utf-8").splitlines() if ln.startswith("- **")]


def test_every_cited_ruling_resolves():
    text = BACKLOG.read_text(encoding="utf-8")
    known_index, known_v1 = _index_ids(), _v1_ids()
    cited = {m.group(1) for m in _ID.finditer(text)}
    assert cited, "the backlog cites no ruling at all"
    missing = sorted(i for i in cited if i not in (known_v1 if i.startswith("V1-") else known_index))
    assert not missing, f"cited but not a ruling id: {missing}"


def test_every_item_names_its_ruling():
    # A bullet may wrap onto continuation lines: read each one up to the next bullet or heading.
    lines = BACKLOG.read_text(encoding="utf-8").splitlines()
    items: list[str] = []
    current: str | None = None
    for ln in [*lines, ""]:
        if ln.startswith("- **"):
            if current is not None:
                items.append(current)
            current = ln
        elif current is not None and ln.startswith("  "):
            current += " " + ln.strip()
        elif current is not None:
            items.append(current)
            current = None
    assert len(items) == len(_bullets()) >= 10
    bare = [i[:60] for i in items if not re.search(r"Rulings?: .*" + _ID.pattern, i)]
    assert not bare, f"items that cite no ruling: {bare}"


def test_the_never_section_holds_only_never_rulings():
    """§2 must not list Q1135: RC13's 2026-09-29 answer and R99 rule that feature a build (Q1135's index line keeps its old CONFLICT note)."""
    text = BACKLOG.read_text(encoding="utf-8")
    never = text.split("## 2.", 1)[1].split("## 3.", 1)[0]
    assert "Q1135" not in never
    assert {"Q220", "Q1131", "Q1137", "Q613", "Q718"} <= {m.group(1) for m in _ID.finditer(never)}
