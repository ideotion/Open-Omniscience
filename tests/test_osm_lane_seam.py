"""The OSM lane seam (S05-04 §4), after Q823 = a (2026-09-29): OSM rows are credited under the ODbL.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Checked from the outside: the lane's tables are not corpus tables (so no corpus export carries
them), the lane file is a backup member marked NOT exportable (the lane row owns that line), the
attribution block credits an OSM table with OpenStreetMap's line and the ODbL, and no export,
bulletin, evidence or custody module imports the lane at all.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_the_lane_tables_are_not_on_the_corpus_metadata():
    from src.database.models import Base
    from src.osm.lane_models import OSM_LANE_MODELS

    for m in OSM_LANE_MODELS:
        assert m.__table__.name not in Base.metadata.tables, m.__table__.name


def test_the_attribution_block_credits_osm_rows_with_the_odbl():
    # Q823 = a (2026-09-29): the shared seam renders OSM's credit and the ODbL line where it
    # used to refuse. Whether the LANE's own file leaves the machine is the test below's.
    from src.backup.attribution import attribution_lines

    lines = attribution_lines({"table:osm_objects"})
    assert [ln.key for ln in lines] == ["openstreetmap"] and "ODbL" in lines[0].text


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
