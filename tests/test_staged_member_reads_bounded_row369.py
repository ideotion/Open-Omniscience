"""Row 369: a restore's staging check reads only regular files, and never past the size the manifest lists.

``_finalize_staged`` hashed each staged member with a plain ``open`` read to the end, after an ``exists`` check that
follows links, and read the staged ``manifest.json`` with ``read_text``. A member that was a link (to ``/dev/zero``,
or to any file), a pipe or a device, or one swapped for a far larger file, was read whole, and a pipe at the manifest's
name blocked the restore for ever. Both now go through the backup checks' reader (rows 336, 342): a regular file only,
never opened through a link or for a blocking read, at most one byte past the listed size, and the manifest at most
:data:`STAGED_MANIFEST_MAX_BYTES` long.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import threading
from pathlib import Path

import pytest

from src.backup import artifact as art

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="FIFOs and links are POSIX here")


def _stage(tmp_path: Path) -> tuple[Path, list[dict]]:
    staging = tmp_path / "staging"
    staging.mkdir()
    members = []
    for name, data in (("corpus.db", os.urandom(5000)), ("logs/a.jsonl", b'{"x": 1}\n' * 50)):
        p = staging / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        members.append({"name": name, "role": "x", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    _write_manifest(staging, members)
    return staging, members


def _write_manifest(staging: Path, members: list[dict]) -> None:
    env = {"manifest": {"backup_schema": art.ACCEPTED_BACKUP_SCHEMAS[-1], "members": members}}
    (staging / "manifest.json").write_text(json.dumps(env), encoding="utf-8")


def _within(seconds: float, fn, *args):
    out: dict = {}

    def run():
        try:
            out["result"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            out["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), out.get("result"), out.get("error")


def _unblock(path: Path) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return
    os.close(fd)


def test_a_whole_staging_still_verifies(tmp_path):
    staging, _ = _stage(tmp_path)
    assert art._finalize_staged(staging, False).hash_failures == []


@posix_only
def test_a_fifo_at_the_manifest_name_is_refused_and_never_blocks(tmp_path):
    staging, _ = _stage(tmp_path)
    side = staging / "manifest.json"
    side.unlink()
    os.mkfifo(side)
    try:
        done, _r, error = _within(5, art._finalize_staged, staging, False)
        assert done, "the staging check blocked on a FIFO at the manifest's name"
        assert isinstance(error, art.ArtifactError) and "could not be read" in str(error)
    finally:
        _unblock(side)


@posix_only
def test_a_link_at_the_manifest_name_is_never_followed(tmp_path):
    staging, _ = _stage(tmp_path)
    side = staging / "manifest.json"
    real = tmp_path / "elsewhere.json"
    real.write_bytes(side.read_bytes())
    side.unlink()
    side.symlink_to(real)
    with pytest.raises(art.ArtifactError, match="could not be read"):
        art._finalize_staged(staging, False)


def test_a_manifest_over_the_ceiling_or_not_an_object_is_refused(tmp_path, monkeypatch):
    staging, _ = _stage(tmp_path)
    monkeypatch.setattr(art, "STAGED_MANIFEST_MAX_BYTES", 16)
    with pytest.raises(art.ArtifactError, match="larger than 16 bytes"):
        art._finalize_staged(staging, False)
    monkeypatch.undo()
    (staging / "manifest.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(art.ArtifactError, match="could not be read"):
        art._finalize_staged(staging, False)


@posix_only
def test_a_link_or_a_fifo_at_a_member_name_is_named_unreadable_and_never_read(tmp_path):
    staging, members = _stage(tmp_path)
    vol = staging / members[0]["name"]
    copy = tmp_path / "copy.db"
    copy.write_bytes(vol.read_bytes())
    vol.unlink()
    vol.symlink_to(copy)  # the same bytes through a link: still never followed
    fails = art._finalize_staged(staging, False).hash_failures
    assert fails == [f"{members[0]['name']}: unreadable: not a regular file (a link, a pipe or a device is never read)"]
    vol.unlink()
    vol.symlink_to(tmp_path / "nowhere")  # a dangling link is not "missing"
    assert "not a regular file" in art._finalize_staged(staging, False).hash_failures[0]
    vol.unlink()
    os.mkfifo(vol)
    try:
        done, staged, error = _within(5, art._finalize_staged, staging, False)
        assert done and error is None, "the staging check blocked on a FIFO at a member's name"
        assert "not a regular file" in staged.hash_failures[0]
    finally:
        _unblock(vol)


def test_a_member_larger_than_listed_is_a_mismatch_unread(tmp_path, monkeypatch):
    staging, members = _stage(tmp_path)
    with (staging / members[1]["name"]).open("ab") as fh:
        fh.write(b"x")
    fails = art._finalize_staged(staging, False).hash_failures
    assert fails == [f"{members[1]['name']}: larger than its listed size (corrupted or altered)"]


def test_a_member_that_grows_while_it_is_read_stops_one_byte_past_its_listed_size(tmp_path, monkeypatch):
    staging, members = _stage(tmp_path)
    asked: list[int] = []
    from src.backup import regular_file

    real_open = regular_file.open_regular

    class _Endless:
        def __init__(self, f):
            self._f = f

        def fileno(self):
            return self._f.fileno()

        def read(self, n=-1):
            asked.append(n)
            return b"\0" * n

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._f.close()

    monkeypatch.setattr(regular_file, "open_regular", lambda p, **kw: _Endless(real_open(p, **kw)))
    problem = art._staged_member_problem(staging / members[0]["name"], members[0])
    assert problem == "larger than its listed size (corrupted or altered)"
    assert sum(asked) == members[0]["bytes"] + 1


def test_a_smaller_or_altered_member_and_an_entry_without_a_size_still_verify_by_hash(tmp_path):
    staging, members = _stage(tmp_path)
    (staging / members[1]["name"]).write_bytes(b"short")
    members[0]["bytes"] = True  # no whole-number size: hashed, regular files only
    _write_manifest(staging, members)
    fails = art._finalize_staged(staging, False).hash_failures
    assert fails == [f"{members[1]['name']}: sha256 mismatch (corrupted or altered)"]


def test_the_staging_check_reads_through_the_bounded_reader():
    fin = inspect.getsource(art._finalize_staged)
    assert "_read_staged_manifest(" in fin and "read_text(" not in fin and "_sha256_file(" not in fin
    assert ".exists()" not in fin.split("hash_failures: list[str] = []")[1].split("custody =")[0]
    prob = inspect.getsource(art._staged_member_problem)
    assert "open_regular(" in prob and "sha256_read(" in prob
    assert "read_manifest_json(" in inspect.getsource(art._read_staged_manifest)
