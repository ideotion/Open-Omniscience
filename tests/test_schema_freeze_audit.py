"""The schema-freeze audit's list matches the live schema, by name (0.8 row B, brief S08-02 S5 and §4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``docs/product/SCHEMA_FREEZE_AUDIT.md`` ends with the audited list: one line per table of the main database and of the
lane stores, with every column. The brief's skeptic matrix asks for a mutation check: drop one column from the audit's
list and the cross-check with the live schema must redden BY NAME. These tests run the cross-check on the committed
document and then on a copy of its list with one column taken out.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_AUDIT = _ROOT / "docs" / "product" / "SCHEMA_FREEZE_AUDIT.md"
_LANE_MODULES = ("src.versioned.models", "src.wiki.lane_models", "src.law.lane_models", "src.osm.lane_models",
                 "src.medical.lane_models")
_LINE = re.compile(r"^(main|lane) ([a-z_][a-z0-9_]*): (.+)$")


def _listed(text: str) -> dict[tuple[str, str], list[str]]:
    """The audit's list, ``{(store, table): [columns]}``, read from the last ``text`` block of the document."""
    block = text.rsplit("```text\n", 1)[1].split("```", 1)[0]
    out: dict[tuple[str, str], list[str]] = {}
    for line in block.splitlines():
        m = _LINE.match(line)
        assert m, f"not an audit line: {line!r}"
        key = (m.group(1), m.group(2))
        assert key not in out, f"{key} is listed twice"
        out[key] = [c.strip() for c in m.group(3).split(",")]
    return out


def _live() -> dict[tuple[str, str], list[str]]:
    from src.database.models import Base

    for mod in _LANE_MODULES:
        importlib.import_module(mod)
    from src.versioned.models import LaneBase

    out: dict[tuple[str, str], list[str]] = {}
    for store, md in (("main", Base.metadata), ("lane", LaneBase.metadata)):
        for name, table in md.tables.items():
            out[(store, name)] = [c.name for c in table.columns]
    return out


def _differences(listed: dict[tuple[str, str], list[str]], live: dict[tuple[str, str], list[str]]) -> list[str]:
    """Every table and column on one side only, named; empty when the audit and the code agree."""
    out = []
    for key in sorted(set(live) - set(listed)):
        out.append(f"{key[0]} table {key[1]} is in the schema but not in the audit")
    for key in sorted(set(listed) - set(live)):
        out.append(f"{key[0]} table {key[1]} is in the audit but not in the schema")
    for key in sorted(set(listed) & set(live)):
        for col in sorted(set(live[key]) - set(listed[key])):
            out.append(f"{key[0]} column {key[1]}.{col} is in the schema but not in the audit")
        for col in sorted(set(listed[key]) - set(live[key])):
            out.append(f"{key[0]} column {key[1]}.{col} is in the audit but not in the schema")
    return out


def test_the_audit_lists_exactly_the_live_schema():
    diff = _differences(_listed(_AUDIT.read_text(encoding="utf-8")), _live())
    assert not diff, ("docs/product/SCHEMA_FREEZE_AUDIT.md section 3 disagrees with the models; update the list "
                      "(and, after the freeze, show the change is additive under F2):\n" + "\n".join(diff))


def test_a_column_dropped_from_the_audit_list_reddens_by_name():
    """The mutation check (S08-02 §4): the audit's list with articles.title taken out names exactly that column."""
    listed = _listed(_AUDIT.read_text(encoding="utf-8"))
    assert "title" in listed[("main", "articles")]
    mutated = {k: [c for c in v if not (k == ("main", "articles") and c == "title")] for k, v in listed.items()}
    assert _differences(mutated, _live()) == ["main column articles.title is in the schema but not in the audit"]


def test_a_table_dropped_from_the_audit_list_reddens_by_name():
    listed = _listed(_AUDIT.read_text(encoding="utf-8"))
    mutated = {k: v for k, v in listed.items() if k != ("lane", "osm_objects")}
    assert _differences(mutated, _live()) == ["lane table osm_objects is in the schema but not in the audit"]


def test_the_audit_names_the_freeze_point_that_is_in_the_chain():
    """F1 names a revision; it must be one the chain has, so a renamed or squashed head cannot leave it dangling."""
    text = _AUDIT.read_text(encoding="utf-8")
    assert "**Status: PROPOSAL, not a ruling.**" in text or "Status: RULED" in text
    revs = {p.name.split("_", 1)[0] for p in (_ROOT / "migrations" / "versions").glob("*.py")}
    judged = text.split("## 3.", 1)[0]
    named = set(re.findall(r"`([0-9a-f]{12})`", judged))
    f1 = judged.split("**F1.", 1)[1].split("**F2.", 1)[0]
    assert re.search(r"`[0-9a-f]{12}`", f1), "F1 names the revision the freeze starts after"
    assert named and named <= revs, sorted(named - revs)
