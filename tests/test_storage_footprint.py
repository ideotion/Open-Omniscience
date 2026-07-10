"""A12b: the unified, itemized storage footprint across ALL stores.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The reported "database size" must cover EVERYTHING as an itemized per-component payload —
crucially including the Ollama model store, which lives OUTSIDE data_dir (so a data-dir-only
total misses it). These pin the itemization, the grand total, and that the external model
store is counted.
"""

from __future__ import annotations

import pytest

import src.monitoring.forensics as forensics

_DB = "open_omniscience.db"


@pytest.fixture()
def stores(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / _DB).write_bytes(b"d" * 4000)
    (data / f"{_DB}-wal").write_bytes(b"w" * 500)
    (data / "wiki_dumps").mkdir()
    (data / "wiki_dumps" / "enwiki.bz2").write_bytes(b"k" * 9000)
    (data / "osm_regions").mkdir()
    (data / "osm_regions" / "europe.pbf").write_bytes(b"o" * 3000)
    (data / ".bak-build-abc").mkdir()
    (data / ".bak-build-abc" / "corpus.db").write_bytes(b"s" * 2000)  # orphaned staging
    ollama = tmp_path / "ollama"
    ollama.mkdir()
    (ollama / "blobs").mkdir()
    (ollama / "blobs" / "sha256-x").write_bytes(b"m" * 7000)  # OUTSIDE data_dir
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setenv("OLLAMA_MODELS", str(ollama))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    return data, ollama


def _by_kind(fp):
    return {c["kind"]: c["bytes"] for c in fp["components"]}


def test_footprint_itemizes_every_component(stores):
    fp = forensics.storage_footprint()
    kinds = _by_kind(fp)
    assert kinds["db"] == 4000
    assert kinds["wal"] == 500
    assert kinds["wiki_dumps"] == 9000
    assert kinds["osm_regions"] == 3000
    assert kinds["staging"] == 2000
    assert kinds["ollama_models"] == 7000  # OUTSIDE data_dir, still counted


def test_grand_total_includes_the_external_ollama_store(stores):
    fp = forensics.storage_footprint()
    t = fp["totals"]
    # data_dir = db 4000 + wal 500 + wiki 9000 + osm 3000 + staging 2000 = 18500
    assert t["data_dir_bytes"] == 18500
    assert t["ollama_models_bytes"] == 7000
    assert t["grand_total_bytes"] == 25500  # the TRUE on-disk footprint (data_dir + external)


def test_ollama_component_is_flagged_outside_data_dir(stores):
    fp = forensics.storage_footprint()
    ollama = next(c for c in fp["components"] if c["kind"] == "ollama_models")
    assert ollama["outside_data_dir"] is True
    assert fp["ollama_store"] == str(stores[1])


def test_no_ollama_store_is_zero_not_a_crash(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / _DB).write_bytes(b"d" * 100)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "no-such-ollama"))
    fp = forensics.storage_footprint()
    assert fp["totals"]["ollama_models_bytes"] == 0
    assert fp["totals"]["grand_total_bytes"] == fp["totals"]["data_dir_bytes"]
    assert _by_kind(fp)["db"] == 100


def _keys(obj):
    """Every dict KEY, recursively (the ledger lesson: a no-score check walks field NAMES,
    never repr() — a tmp path or a value legitimately containing 'score' would false-fail)."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k).lower())
            out += _keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += _keys(v)
    return out


def test_no_score_fields(stores):
    fp = forensics.storage_footprint()
    for k in _keys(fp):
        assert "score" not in k and "ranking" not in k, k


def test_session_forensics_embeds_the_footprint(stores):
    sf = forensics.session_forensics()
    assert "storage_footprint" in sf
    assert sf["storage_footprint"]["totals"]["grand_total_bytes"] == 25500
