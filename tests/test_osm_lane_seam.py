"""The OSM lane seam (S05-04 §4), after Q823 = a (2026-09-29): OSM rows are credited under the ODbL.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Checked from the outside: the lane's tables are not corpus tables (so no corpus export carries
them), the lane file rides the encrypted backup as a living-source store (R739; it was NOT
exportable until then), the attribution block credits an OSM table with OpenStreetMap's line and
the ODbL, and no export, bulletin, evidence or custody module imports the lane, except the one
that puts a backup's maps store back (named below, with its reason).
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


def test_the_lane_file_rides_a_backup_as_a_living_source_store(tmp_path, monkeypatch):
    # R739 (2026-11-17): the maps store rides the encrypted backup like the Wikipedia and law
    # stores, and is put back country by country (src/backup/lane_merge.py ``_merge_osm``).
    # Hermetic: the row reads the lanes present in the data directory.
    from src.backup.inventory import _lane_member
    from src.versioned import store

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    try:
        store.create_lane("osm")
        row = _lane_member()
    finally:
        store.dispose_all()
    assert row["exportable"] is True
    assert "osm" in row["breakdown"] and row["waiting"] == {}


_CARRIERS = ("src/backup", "src/bulletin", "src/custody", "src/reporting", "src/verification")

#: The one module of the carriers that reads the lane, and why. It is the IMPORT side of the
#: operator's own backup (R729, R739): it puts a backup's maps store back into this machine's
#: lane, and rebuilds the lane's own indexes from the rows it copied. It exports nothing; the
#: store leaves the machine only inside the encrypted backup, whose summary carries
#: OpenStreetMap's credit and the ODbL line (Q823 = a, ``attribution.lane_signal``).
_READS_THE_LANE = {"src/backup/lane_merge.py"}


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
                rel = path.relative_to(ROOT).as_posix()
                if rel not in _READS_THE_LANE and any(n == "src.osm" or n.startswith("src.osm.") for n in names):
                    offenders.append(rel)
    assert offenders == [], f"an export-shaped module reads the OSM lane: {offenders}"
