"""Row 308: an export reads the destination's previous volume manifests like any untrusted manifest.

The destination of an oo-volumes-2 export is a drive anything may have written to. Before the build, the
previous ``volumes.json`` and a previous run's ``volumes.building.json`` are read to reuse what is already
there (``_load_reuse_pool``) and to note a change of volume size (``_previous_volume_size``). Both were a plain
``read_text``: a named pipe there blocked the export for ever, a link to ``/dev/zero`` read without end, JSON
nested deep enough raised ``RecursionError`` past the ``except (OSError, ValueError)``, and a manifest that was
not an object crashed at ``m.get``. They now go through R780's ``read_manifest_json`` (no link followed, no
blocking, bounded size and nesting) with the volume format's own size ceiling, and a manifest of another shape
offers nothing to reuse instead of crashing the export. Every case still ends in a complete, restorable set,
and a sound previous set is still reused exactly as before.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from src.backup import manifest_file, stream_backup
from src.backup.stream_backup import BUILDING_NAME, read_stream_backup
from src.backup.volumes import MANIFEST_MAX_BYTES as VOLUMES_MANIFEST_MAX_BYTES
from src.backup.volumes import MANIFEST_NAME
from tests.js_source_helper import python_function_source
from tests.test_stream_backup import _backup, _make_corpus
from tests.staged_db import same_database

posix_only = pytest.mark.skipif(os.name == "nt", reason="pipes and /dev/zero")


def _within(seconds: float, fn):
    out: list = []
    err: list = []

    def run():
        try:
            out.append(fn())
        except BaseException as exc:  # noqa: BLE001 - handed back to the test thread
            err.append(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "the reader blocked"
    if err:
        raise err[0]
    return out[0]


def _restores(tmp: Path, dest: Path, corpus: Path) -> None:
    staged = read_stream_backup(dest, "pw", staging_root=tmp / "st")
    assert staged.signature_state == "verified"
    assert same_database(staged.corpus_path, corpus)


@pytest.fixture
def corpus(tmp_path) -> Path:
    c = tmp_path / "corpus.db"
    _make_corpus(c, rows=120)
    return c


@posix_only
@pytest.mark.parametrize("name", [MANIFEST_NAME, BUILDING_NAME])
def test_a_pipe_at_the_destination_never_blocks_the_export(tmp_path, corpus, name):
    dest = tmp_path / "dest"
    dest.mkdir()
    os.mkfifo(dest / name)
    pool, notes = _within(5, lambda: stream_backup._load_reuse_pool(dest, "pw"))
    assert pool == {} and any("unreadable" in n for n in notes)
    assert _within(5, lambda: stream_backup._previous_volume_size(dest)) is None  # volumes.json only; a no-op for the log
    s = _within(60, lambda: _backup(tmp_path, dest, corpus))
    assert s["volumes_reused"] == 0
    _restores(tmp_path, dest, corpus)


@posix_only
@pytest.mark.parametrize("name", [MANIFEST_NAME, BUILDING_NAME])
def test_a_link_at_the_destination_is_never_followed(tmp_path, corpus, name):
    dest = tmp_path / "dest"
    dest.mkdir()
    os.symlink("/dev/zero", dest / name)
    pool, _ = _within(5, lambda: stream_backup._load_reuse_pool(dest, "pw"))
    assert pool == {}
    assert _within(5, lambda: stream_backup._previous_volume_size(dest)) is None
    _within(60, lambda: _backup(tmp_path, dest, corpus))
    _restores(tmp_path, dest, corpus)


@pytest.mark.parametrize("name", [MANIFEST_NAME, BUILDING_NAME])
def test_deep_nesting_is_refused_not_raised(tmp_path, corpus, name):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / name).write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")
    pool, notes = stream_backup._load_reuse_pool(dest, "pw")
    assert pool == {} and any("unreadable" in n for n in notes)
    assert stream_backup._previous_volume_size(dest) is None
    _backup(tmp_path, dest, corpus)
    _restores(tmp_path, dest, corpus)


@pytest.mark.parametrize(
    "doc",
    [
        [1, 2, 3],
        "a string",
        {"kind": "oo-volumes-2", "key_check": 7, "volumes": "x", "volume_size": True},
        {"kind": "oo-volumes-2", "key_check": ["x"], "volumes": [1, None, "s", {"member": "a"}], "volume_size": "big"},
        {"kind": ["not", "hashable"], "volumes": {"a": 1}, "volume_size": [65536]},
    ],
)
def test_a_manifest_of_another_shape_offers_nothing_and_the_export_completes(tmp_path, corpus, doc):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / MANIFEST_NAME).write_text(json.dumps(doc), encoding="utf-8")
    pool, _ = stream_backup._load_reuse_pool(dest, "pw")
    assert pool == {}
    assert stream_backup._previous_volume_size(dest) is None
    s = _backup(tmp_path, dest, corpus)
    assert s["volumes_reused"] == 0
    _restores(tmp_path, dest, corpus)


def test_a_sound_previous_set_is_still_reused_exactly_as_before(tmp_path, corpus):
    dest = tmp_path / "dest"
    s1 = _backup(tmp_path, dest, corpus)
    pool, notes = stream_backup._load_reuse_pool(dest, "pw")
    written = json.loads((dest / MANIFEST_NAME).read_text("utf-8"))["volumes"]
    assert set(pool) == {(v["member"], v["slice"]) for v in written} and notes == []  # every written entry offered
    assert stream_backup._previous_volume_size(dest) == json.loads((dest / MANIFEST_NAME).read_text("utf-8"))["volume_size"]
    s2 = _backup(tmp_path, dest, corpus)
    assert s2["volumes_emitted"] <= 1 and s2["volumes_reused"] == s1["volumes"] - s2["volumes_emitted"]
    _restores(tmp_path, dest, corpus)


def test_odd_entries_beside_sound_ones_keep_the_sound_ones(tmp_path, corpus):
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    m = json.loads((dest / MANIFEST_NAME).read_text("utf-8"))
    sound = len(stream_backup._load_reuse_pool(dest, "pw")[0])
    m["volumes"] = [*m["volumes"], 1, None, {"member": "x", "slice": "nope", "sha256": "", "plaintext_sha256": ""}]
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    assert len(stream_backup._load_reuse_pool(dest, "pw")[0]) == sound


def test_the_reader_uses_the_volume_formats_own_size_ceiling(tmp_path, monkeypatch):
    """A set the restore accepts (up to the volume format's ceiling) is never refused reuse for its size alone."""
    seen: list[int] = []
    real = manifest_file.read_manifest_json

    def spy(path, max_bytes=None):
        seen.append(max_bytes)
        return real(path, max_bytes=max_bytes)

    monkeypatch.setattr(stream_backup, "read_manifest_json", spy)
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / MANIFEST_NAME).write_text("{}", encoding="utf-8")
    (dest / BUILDING_NAME).write_text("{}", encoding="utf-8")
    stream_backup._load_reuse_pool(dest, "pw")
    stream_backup._previous_volume_size(dest)
    assert seen == [VOLUMES_MANIFEST_MAX_BYTES] * 3


def test_max_bytes_bounds_the_read(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"a": "x" * 100}), encoding="utf-8")
    assert manifest_file.read_manifest_json(p, max_bytes=50) is None
    assert manifest_file.read_manifest_json(p, max_bytes=500) == {"a": "x" * 100}


def test_no_plain_read_of_a_destination_manifest_remains():
    src = Path(stream_backup.__file__).read_text(encoding="utf-8")
    for fn in ("_load_reuse_pool", "_previous_volume_size"):
        body = python_function_source(src, fn)
        assert "read_manifest_json(" in body and ".read_text(" not in body, fn


def _plant(dest: Path, mutate) -> None:
    """Rewrite every entry of the previous manifest with ``mutate``; key_check and digests stay the user's own, as
    an attacker holding the drive could copy them."""
    m = json.loads((dest / MANIFEST_NAME).read_text("utf-8"))
    for v in m["volumes"]:
        mutate(v)
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.__setitem__("name", "/dev/zero"),
        lambda v: v.__setitem__("name", "../outside.ooenc"),
        lambda v: v.__setitem__("name", ["x"]),
        lambda v: v.__setitem__("plaintext_bytes", "x"),
        lambda v: v.__setitem__("plaintext_bytes", [1]),
        lambda v: v.__setitem__("sha256", 5),
    ],
    ids=["device", "parent", "name-not-str", "bytes-not-number", "bytes-list", "digest-not-str"],
)
def test_an_entry_naming_what_this_module_never_writes_is_never_reused(tmp_path, corpus, mutate):
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    _plant(dest, mutate)
    assert stream_backup._load_reuse_pool(dest, "pw")[0] == {}
    s = _within(60, lambda: _backup(tmp_path, dest, corpus))
    assert s["volumes_reused"] == 0
    _restores(tmp_path, dest, corpus)


@posix_only
@pytest.mark.parametrize("kind", ["fifo", "link"])
def test_a_volume_file_swapped_for_a_pipe_or_a_link_is_re_written_not_hashed(tmp_path, corpus, kind):
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    vols = json.loads((dest / MANIFEST_NAME).read_text("utf-8"))["volumes"]
    victim = dest / vols[0]["name"]
    victim.unlink()
    if kind == "fifo":
        os.mkfifo(victim)
    else:
        os.symlink("/dev/zero", victim)
    s = _within(60, lambda: _backup(tmp_path, dest, corpus))
    assert s["volumes_reused"] <= len(vols) - 1
    _restores(tmp_path, dest, corpus)
