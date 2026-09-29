"""Q823 (ODbL) is unanswered: nothing OSM-derived leaves the machine (S05-04 §4, the seam).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Negative space, checked from the outside: the lane's tables are not corpus tables (so no corpus
export carries them), the lane file is a backup member marked NOT exportable, the attribution
block refuses an OSM table rather than rendering a short one, and no export, bulletin, evidence
or custody module imports the lane at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_the_lane_tables_are_not_on_the_corpus_metadata():
    from src.database.models import Base
    from src.osm.lane_models import OSM_LANE_MODELS

    for m in OSM_LANE_MODELS:
        assert m.__table__.name not in Base.metadata.tables, m.__table__.name


def test_the_attribution_block_refuses_osm_rows_rather_than_rendering_short():
    from src.backup.attribution import PendingRulingError, attribution_lines

    with pytest.raises(PendingRulingError, match="Q823"):
        attribution_lines({"table:osm_objects"})


def test_the_lane_file_is_a_backup_member_that_is_NOT_exportable():
    from src.backup.inventory import _lane_member

    assert _lane_member()["exportable"] is False


_CARRIERS = ("src/backup", "src/bulletin", "src/custody", "src/reporting", "src/verification")


def test_no_export_bulletin_or_evidence_module_imports_the_osm_lane():
    offenders = []
    for base in _CARRIERS:
        for path in (ROOT / base).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                if any(n == "src.osm" or n.startswith("src.osm.") for n in names):
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"an export-shaped module reads the OSM lane: {offenders}"
