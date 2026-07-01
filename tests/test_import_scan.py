"""Tests for the unified-import folder discovery (pure filesystem, no DB/network)."""

from __future__ import annotations

import pytest

from src.backup.import_scan import scan_import_folder


def _touch(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_classifies_a_mixed_export_folder(tmp_path):
    _touch(tmp_path / "volumes.json", b"{}")            # corpus volume set
    _touch(tmp_path / "oo-vol-000.ooenc2")
    _touch(tmp_path / "wiki_dumps" / "enwiki.bz2")       # blobs
    _touch(tmp_path / "osm_regions" / "kenya.osm.pbf")
    _touch(tmp_path / "models" / "blobs" / "sha256-abc")
    _touch(tmp_path / "a.eml")                            # loose newsletters
    _touch(tmp_path / "sub" / "b.eml")
    (tmp_path / "sources.csv").write_text("name,domain,country\nBBC,bbc.com,gb\n")
    _touch(tmp_path / "open-omniscience-20260701.oobackup")  # legacy

    out = scan_import_folder(tmp_path)
    f = out["found"]
    assert f["corpus"]["manifest"] == "volumes.json"
    assert f["blobs"]["wiki"]["count"] == 1
    assert f["blobs"]["maps"]["count"] == 1
    assert f["blobs"]["models"]["count"] == 1
    assert f["newsletters"]["count"] == 2       # recursive
    assert "sources.csv" in f["source_csv"]
    assert any("open-omniscience-" in n for n in f["legacy_backup"])


def test_empty_folder_finds_nothing(tmp_path):
    assert scan_import_folder(tmp_path)["found"] == {}


def test_csv_without_domain_header_is_not_a_source_list(tmp_path):
    (tmp_path / "notes.csv").write_text("date,amount\n2026-01-01,5\n")
    assert "source_csv" not in scan_import_folder(tmp_path)["found"]


def test_models_export_is_not_mistaken_for_legacy_backup(tmp_path):
    _touch(tmp_path / "open-omniscience-models-20260701.oomodels")
    assert "legacy_backup" not in scan_import_folder(tmp_path)["found"]


def test_non_directory_raises(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hi")
    with pytest.raises(ValueError, match="not a folder"):
        scan_import_folder(f)


def test_volume_manifest_name_stays_in_sync():
    # the discovery module hardcodes the manifest name to stay crypto-free; guard drift
    from src.backup.import_scan import _VOL_MANIFEST
    from src.backup.volumes import MANIFEST_NAME

    assert _VOL_MANIFEST == MANIFEST_NAME
