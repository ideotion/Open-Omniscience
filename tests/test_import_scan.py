"""Tests for the unified-import folder discovery (pure filesystem, no DB/network)."""

from __future__ import annotations

import pytest

from src.backup.import_scan import scan_import_folder


def _touch(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_classifies_a_mixed_export_folder(tmp_path):
    _touch(tmp_path / "volumes.json", b"{}")            # corpus volume set
    _touch(tmp_path / "vol-00000.ooenc")
    _touch(tmp_path / "wiki_dumps" / "enwiki.bz2")       # blobs
    _touch(tmp_path / "osm_regions" / "kenya.osm.pbf")
    _touch(tmp_path / "models" / "blobs" / "sha256-abc")
    _touch(tmp_path / "a.eml")                            # loose newsletters
    _touch(tmp_path / "sub" / "b.eml")
    (tmp_path / "sources.csv").write_text("name,domain,country\nBBC,bbc.com,gb\n", encoding="utf-8")
    _touch(tmp_path / "open-omniscience-20260701.oobackup")  # legacy

    out = scan_import_folder(tmp_path)
    f = out["found"]
    assert f["corpus"][0]["manifest"] == "volumes.json"
    assert f["corpus"][0]["path"] == str(tmp_path)
    assert f["corpus"][0]["volumes"] == 1
    assert f["blobs"]["wiki"]["count"] == 1
    assert f["blobs"]["maps"]["count"] == 1
    assert f["blobs"]["models"]["count"] == 1
    assert f["newsletters"]["count"] == 2       # recursive
    assert "sources.csv" in f["source_csv"]
    assert any("open-omniscience-" in x["name"] for x in f["legacy_backup"])


def test_empty_folder_finds_nothing(tmp_path):
    assert scan_import_folder(tmp_path)["found"] == {}


def test_csv_without_domain_header_is_not_a_source_list(tmp_path):
    (tmp_path / "notes.csv").write_text("date,amount\n2026-01-01,5\n", encoding="utf-8")
    assert "source_csv" not in scan_import_folder(tmp_path)["found"]


def test_models_export_is_not_mistaken_for_legacy_backup(tmp_path):
    _touch(tmp_path / "open-omniscience-models-20260701.oomodels")
    assert "legacy_backup" not in scan_import_folder(tmp_path)["found"]


def test_non_directory_raises(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="not a folder"):
        scan_import_folder(f)


def test_volume_manifest_name_stays_in_sync():
    # the discovery module hardcodes the manifest name to stay crypto-free; guard drift
    from src.backup.import_scan import _VOL_MANIFEST
    from src.backup.volumes import MANIFEST_NAME

    assert _VOL_MANIFEST == MANIFEST_NAME


# --------------------------------------------------------------------------- #
#  Recursive discovery — the field report: a folder of MIXED backups where each
#  backup type sits in its OWN subfolder. Every kind must still be found.
# --------------------------------------------------------------------------- #
def test_finds_every_backup_type_nested_in_subfolders(tmp_path):
    # a volume set one level deep
    _touch(tmp_path / "corpus-backup" / "volumes.json", b"{}")
    _touch(tmp_path / "corpus-backup" / "vol-00000.ooenc")
    _touch(tmp_path / "corpus-backup" / "vol-00001.ooenc")
    # large data two levels deep
    _touch(tmp_path / "big" / "run1" / "wiki_dumps" / "frwiki.bz2")
    _touch(tmp_path / "big" / "run1" / "models" / "blobs" / "sha256-xyz")
    # a legacy single-file backup in its own subfolder
    _touch(tmp_path / "legacy" / "open-omniscience-20260101.oobackup", b"OOENC1..")
    # newsletters deeper still
    _touch(tmp_path / "mail" / "2026" / "jan" / "n1.eml")
    # a source CSV nested
    (tmp_path / "lists").mkdir(parents=True, exist_ok=True)
    (tmp_path / "lists" / "srcs.csv").write_text("name,domain\nA,a.com\n", encoding="utf-8")

    f = scan_import_folder(tmp_path)["found"]
    # corpus found in its subfolder, with the RIGHT path for the restore call
    assert len(f["corpus"]) == 1
    assert f["corpus"][0]["path"] == str(tmp_path / "corpus-backup")
    assert f["corpus"][0]["volumes"] == 2
    # blobs found + grouped by their parent root (the folder-restore unit)
    assert f["blobs"]["wiki"]["count"] == 1
    assert f["blobs"]["models"]["count"] == 1
    roots = {r["root"]: r for r in f["blob_roots"]}
    br = roots[str(tmp_path / "big" / "run1")]
    assert set(br["categories"]) == {"wiki_dumps", "models"}
    # legacy found with a server-side PATH (a first-class importable item now)
    assert len(f["legacy_backup"]) == 1
    assert f["legacy_backup"][0]["path"] == str(
        tmp_path / "legacy" / "open-omniscience-20260101.oobackup"
    )
    # newsletters + csv found recursively
    assert f["newsletters"]["count"] == 1
    assert "srcs.csv" in f["source_csv"]


def test_multiple_volume_sets_are_all_found(tmp_path):
    _touch(tmp_path / "a" / "volumes.json", b"{}")
    _touch(tmp_path / "a" / "vol-00000.ooenc")
    _touch(tmp_path / "b" / "volumes.json", b"{}")
    _touch(tmp_path / "b" / "vol-00000.ooenc")
    f = scan_import_folder(tmp_path)["found"]
    paths = {c["path"] for c in f["corpus"]}
    assert paths == {str(tmp_path / "a"), str(tmp_path / "b")}


def test_junk_and_blob_trees_are_not_descended_for_other_kinds(tmp_path):
    # a models blob dir with many files must not be walked hunting for legacy/csv,
    # and a .git dir is skipped entirely
    for i in range(5):
        _touch(tmp_path / "models" / "blobs" / f"sha256-{i}")
    _touch(tmp_path / ".git" / "objects" / "open-omniscience-should-not-count")
    f = scan_import_folder(tmp_path)["found"]
    assert f["blobs"]["models"]["count"] == 5
    assert "legacy_backup" not in f  # the .git impostor is skipped


def test_depth_bound_stops_runaway_recursion(tmp_path):
    deep = tmp_path
    for i in range(20):
        deep = deep / f"d{i}"
    _touch(deep / "n.eml")
    # with a tiny depth bound the very-deep newsletter is not reached
    assert "newsletters" not in scan_import_folder(tmp_path, max_depth=3)["found"]
    # with the default bound (8) a 20-deep tree is still not reached
    assert "newsletters" not in scan_import_folder(tmp_path)["found"]
