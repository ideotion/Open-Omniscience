"""Row 272: an unreadable law catalogue writes null, never 0 or an empty list, for every state nothing looked up.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

When ``load_legal_catalog`` cannot read the catalogue, only two things are known: which floor countries a tracked document
states (the database) and that the rest were not looked up. Verified-not-yet-tracked, unverified and no-eligible-source need the
catalogue, so the report writes null for each, in the floor's ``by_state``, in every language's ``states`` and in the world
block with its two research counts. Every reader treats that null as absent: the KPI record keeps it null, the read-back prints
"not looked up", the Living sources panel leaves the state out (``tests/living_sources_node_test.js``).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.law.coverage import FLOOR_NEEDS_CATALOG, FLOOR_TRACKED, FLOOR_UNCHECKED

ROOT = Path(__file__).resolve().parent.parent


def _readback():
    spec = importlib.util.spec_from_file_location(
        "oo_law_coverage_readback_272", ROOT / "scripts" / "law_coverage_readback.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def unread(monkeypatch, tmp_path):
    """The real route with the catalogue unreadable, and the KPI record it writes kept under tmp_path."""
    from fastapi.testclient import TestClient

    import src.law.catalog as catalog
    import src.monitoring.kpi as kpi
    from src.api.main import app

    def _unreadable():
        raise catalog.LawCatalogUnreadable("the law catalogue could not be parsed")

    monkeypatch.setattr(catalog, "load_legal_catalog", _unreadable)
    written: dict = {}
    monkeypatch.setattr(kpi, "_write_record", lambda name, schema, rec: written.update(rec) or rec)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        r = client.get("/api/diagnostics/law-coverage?download=1")
    assert r.status_code == 200
    return r.content, written


def test_the_floor_writes_null_for_every_state_nothing_looked_up(unread):
    floor = json.loads(unread[0])["data"]["floor"]
    assert floor["state"] == "unchecked" and floor["reason"]
    for st in FLOOR_NEEDS_CATALOG:
        assert floor["by_state"][st] is None, (
            f"{st} was written as {floor['by_state'][st]!r} for a lookup that never happened"
        )
    placed = floor["by_state"][FLOOR_TRACKED] + floor["by_state"][FLOOR_UNCHECKED]
    assert sorted(placed) == sorted(set(placed)) and len(placed) == floor["countries"], (
        "every floor country once, in a known state"
    )
    assert floor["languages"], "the twelve-language rows are still there"
    for row in floor["languages"]:
        for st in FLOOR_NEEDS_CATALOG:
            assert row["states"][st] is None, (
                f"{row['language']}: {st} = {row['states'][st]!r}, never a 0"
            )
        assert isinstance(row["states"][FLOOR_TRACKED], int) and isinstance(
            row["states"][FLOOR_UNCHECKED], int
        )


def test_the_world_block_writes_null_for_its_states_and_both_research_counts(unread):
    world = json.loads(unread[0])["data"]["world"]
    assert world["state"] == "unchecked"
    for st in FLOOR_NEEDS_CATALOG:
        assert world["by_state"][st] is None and world["states"][st] is None
    assert (
        world["no_eligible_source_to_research"] is None
        and world["no_eligible_source_no_permanent_population"] is None
    )
    assert world["states"][FLOOR_UNCHECKED] == len(world["by_state"][FLOOR_UNCHECKED]) > 0


def test_the_kpi_record_keeps_null_and_never_a_0(unread):
    rec = unread[1]
    assert rec["floor_state"] == "unchecked"
    counts = rec["floor_by_state"]
    for st in FLOOR_NEEDS_CATALOG:
        assert st in counts and counts[st] is None, (
            f"the KPI record wrote {st} as {counts.get(st, 'absent')!r}"
        )
    assert isinstance(counts[FLOOR_TRACKED], int) and isinstance(counts[FLOOR_UNCHECKED], int)


def test_the_read_back_says_not_looked_up_for_a_null_state_even_on_a_checked_report():
    R = _readback()
    floor = {
        "state": "checked",
        "countries": 1,
        "as_of": "2026-01-01",
        "verification_status": "drafted",
        "by_state": {"tracked": ["fr"], "unverified": None},
        "languages": [
            {"language": "fr", "official": ["fr"], "states": {"tracked": 1, "unverified": None}}
        ],
    }
    text = "\n".join(R.floor_lines(floor))
    assert "  unverified: not looked up" in text and "  unverified: 0" not in text
    assert "tracked 1, unverified not looked up" in text
    assert R.json_floor({"floor": floor})["by_state"]["unverified"] is None, (
        "--json keeps null, never []"
    )
