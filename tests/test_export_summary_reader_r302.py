"""Row 302: the export summary reads the destination folder's manifests like any untrusted manifest.

The destination is a drive anything may have written to. ``oo-folder-backup.json`` and ``volumes.json``
were read with a plain ``read_text``: a named pipe there blocked the export summary for ever, a link to
``/dev/zero`` read without end, and JSON nested deep enough raised past the summary. They now go through
R780's ``read_manifest_json`` (no link followed, no blocking, bounded size and nesting), and a manifest
of another shape counts nothing instead of crashing the summary.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from src.backup import export_summary
from src.backup.folder_backup import MANIFEST_NAME as FOLDER_MANIFEST
from src.backup.volumes import MANIFEST_NAME as VOLUME_MANIFEST
from tests.js_source_helper import python_function_source

posix_only = pytest.mark.skipif(os.name == "nt", reason="pipes and /dev/zero")


def _within(seconds: float, fn):
    out: list = []
    t = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "the reader blocked"
    return out[0]


def test_sound_manifests_still_read(tmp_path):
    (tmp_path / FOLDER_MANIFEST).write_text(json.dumps({"categories": {"wiki_dumps": [{"size": 5}, {"size": 7}], "osm_regions": []}}),
                                            encoding="utf-8")
    (tmp_path / VOLUME_MANIFEST).write_text(json.dumps({"volumes": [{"bytes": 10}], "parity": {"volumes": [{"bytes": 3}]}}), encoding="utf-8")
    assert export_summary._file_categories(export_summary._folder_manifest(tmp_path)) == [
        {"category": "wiki_dumps", "files": 2, "bytes": 12}]
    assert export_summary._volume_bytes(tmp_path) == 13


@posix_only
@pytest.mark.parametrize("name", [FOLDER_MANIFEST, VOLUME_MANIFEST])
def test_a_pipe_never_blocks(tmp_path, name):
    os.mkfifo(tmp_path / name)
    assert _within(5, lambda: (export_summary._folder_manifest(tmp_path), export_summary._volume_manifest(tmp_path))) == (None, None)


@posix_only
@pytest.mark.parametrize("name", [FOLDER_MANIFEST, VOLUME_MANIFEST])
def test_a_link_is_never_followed(tmp_path, name):
    os.symlink("/dev/zero", tmp_path / name)
    assert _within(5, lambda: (export_summary._folder_manifest(tmp_path), export_summary._volume_manifest(tmp_path))) == (None, None)
    real = tmp_path / "elsewhere.json"
    real.write_text(json.dumps({"volumes": [{"bytes": 99}], "categories": {"x": [{"size": 1}]}}), encoding="utf-8")
    (tmp_path / name).unlink()
    (tmp_path / name).symlink_to(real)
    assert export_summary._folder_manifest(tmp_path) is None and export_summary._volume_bytes(tmp_path) is None


@pytest.mark.parametrize("name", [FOLDER_MANIFEST, VOLUME_MANIFEST])
def test_deep_nesting_is_refused_not_raised(tmp_path, name):
    (tmp_path / name).write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")
    assert export_summary._folder_manifest(tmp_path) is None and export_summary._volume_manifest(tmp_path) is None


@pytest.mark.parametrize(
    "folder, volumes",
    [
        ({"categories": ["not", "a", "map"]}, {"volumes": "nope", "parity": ["x"]}),
        ({"categories": {"wiki_dumps": "x", "osm_regions": [1, None, {"size": "9"}]}}, {"volumes": [1, None, {"bytes": "9"}, {"bytes": True}]}),
        ({"categories": {"wiki_dumps": [{"size": -4}, {"size": 2}]}}, {"volumes": [{"bytes": -1}, {"bytes": 2}], "parity": {"volumes": None}}),
    ],
)
def test_a_manifest_of_another_shape_counts_nothing(tmp_path, folder, volumes):
    (tmp_path / FOLDER_MANIFEST).write_text(json.dumps(folder), encoding="utf-8")
    (tmp_path / VOLUME_MANIFEST).write_text(json.dumps(volumes), encoding="utf-8")
    cats = export_summary._file_categories(export_summary._folder_manifest(tmp_path))
    assert all(c["bytes"] >= 0 for c in cats)
    assert export_summary._volume_bytes(tmp_path) in (0, 2)
    facts = export_summary.export_facts(tmp_path)
    assert isinstance(facts, dict)
    assert isinstance(export_summary.render_summary_markdown(facts), str)


def test_parity_of_another_shape_is_not_reported_as_written(tmp_path):
    (tmp_path / VOLUME_MANIFEST).write_text(json.dumps({"volumes": [{"bytes": 4}], "parity": {"volumes": "str"}}), encoding="utf-8")
    vols = export_summary.export_facts(tmp_path)["volumes"]
    assert vols["parity"] is False and vols["count"] == 1 and vols["bytes"] == 4


def test_the_summary_module_has_no_plain_read_of_a_manifest():
    src = (Path(export_summary.__file__)).read_text(encoding="utf-8")
    for fn in ("_folder_manifest", "_volume_manifest"):
        body = python_function_source(src, fn)
        assert "read_manifest_json(" in body and ".read_text(" not in body, fn
