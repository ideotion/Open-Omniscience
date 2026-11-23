"""Row 368: a diagnostics volume set's checks read only regular files, and never past the size listed.

``verify_volume_set`` hashed each volume with a plain ``open`` read to the end, after a size check by name: a volume
that grew between the two, or a name swapped for a link to some other file, was read whole. ``load_manifest`` read
the sidecar with ``read_text``, so a FIFO at ``volumes.json`` (the app reads that folder on every listing) blocked the
read for ever. Both now go through the backup checks' reader: a regular file only (a link, a pipe or a device is never
opened for a read), at most one byte past the size the manifest lists, and the sidecar at most
:data:`MANIFEST_MAX_BYTES` long.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from src.api import diagnostics_volumes as dv

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="FIFOs and links are POSIX here")


def _set(tmp_path: Path) -> tuple[Path, dict]:
    src = tmp_path / "oo-all-diagnostics-20261123-120000.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({"kind": "all-diagnostics"}))
        z.writestr("random.bin", os.urandom(20_000))
    out = tmp_path / "v"
    return out, dv.write_volume_set(src, out)


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


def test_a_whole_set_still_verifies(tmp_path):
    out, manifest = _set(tmp_path)
    ver = dv.verify_volume_set(out)
    assert ver["ok"] and ver["bad"] == [] and ver["total"] == len(manifest["volumes"])
    assert dv.load_manifest(out)["kind"] == dv.VOLUME_KIND


@posix_only
def test_a_fifo_at_the_sidecar_name_is_refused_and_never_blocks(tmp_path):
    out, _ = _set(tmp_path)
    side = out / dv.MANIFEST_NAME
    side.unlink()
    os.mkfifo(side)
    try:
        done, _result, error = _within(5, dv.load_manifest, out)
        assert done, "load_manifest blocked on a FIFO at the sidecar's name"
        assert isinstance(error, dv.VolumeError) and "not a regular file" in str(error)
    finally:
        _unblock(side)


@posix_only
def test_a_link_at_the_sidecar_name_is_never_followed(tmp_path):
    out, _ = _set(tmp_path)
    side = out / dv.MANIFEST_NAME
    real = tmp_path / "elsewhere.json"
    real.write_bytes(side.read_bytes())
    side.unlink()
    side.symlink_to(real)
    with pytest.raises(dv.VolumeError, match="not a regular file"):
        dv.load_manifest(out)


def test_a_sidecar_over_the_ceiling_is_refused_unread(tmp_path, monkeypatch):
    out, _ = _set(tmp_path)
    monkeypatch.setattr(dv, "MANIFEST_MAX_BYTES", 16)
    with pytest.raises(dv.VolumeError, match="larger than 16 bytes"):
        dv.load_manifest(out)


def test_no_sidecar_is_still_no_sidecar(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(dv.VolumeError, match="no volume manifest"):
        dv.load_manifest(tmp_path / "empty")


@posix_only
def test_a_fifo_or_a_link_at_a_volume_name_is_bad_and_never_read(tmp_path):
    out, manifest = _set(tmp_path)
    first, *_ = manifest["volumes"]
    vol = out / first["name"]
    copy = tmp_path / "copy.zip"
    copy.write_bytes(vol.read_bytes())
    vol.unlink()
    vol.symlink_to(copy)  # the same bytes, through a link: still never followed
    ver = dv.verify_volume_set(out)
    assert first["name"] in ver["bad"] and first["name"] not in ver["missing"]
    vol.unlink()
    os.mkfifo(vol)
    try:
        done, ver, error = _within(5, dv.verify_volume_set, out)
        assert done and error is None, "the verify blocked on a FIFO at a volume's name"
        assert first["name"] in ver["bad"]
    finally:
        _unblock(vol)


def test_a_volume_that_grows_while_it_is_read_stops_one_byte_past_its_listed_size(tmp_path, monkeypatch):
    """``fstat`` said the listed size, then the file kept growing: the read takes at most one byte past it."""
    out, manifest = _set(tmp_path)
    first = manifest["volumes"][0]
    asked: list[int] = []
    real_open = dv.open_regular

    class _Endless:
        """The real file's descriptor (so ``fstat`` sees the listed size), but reads that never end."""

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

    monkeypatch.setattr(dv, "open_regular", lambda p: _Endless(real_open(p)))
    assert dv._volume_matches(out / first["name"], first) is False
    assert sum(asked) == first["bytes"] + 1


def test_a_volume_larger_than_listed_is_bad(tmp_path):
    out, manifest = _set(tmp_path)
    first = manifest["volumes"][0]
    with (out / first["name"]).open("ab") as fh:
        fh.write(b"x")
    assert first["name"] in dv.verify_volume_set(out)["bad"]


def test_an_entry_with_no_whole_number_size_or_a_path_name_is_bad_and_never_read(tmp_path, monkeypatch):
    out, manifest = _set(tmp_path)
    m = json.loads((out / dv.MANIFEST_NAME).read_text(encoding="utf-8"))
    m["volumes"][0]["bytes"] = True
    m["volumes"].append({"name": "../outside.zip", "bytes": 1, "sha256": "0" * 64})
    (out / dv.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    opened: list[str] = []
    real_open = dv.open_regular
    monkeypatch.setattr(dv, "open_regular", lambda p: opened.append(os.fspath(p)) or real_open(p))
    ver = dv.verify_volume_set(out)
    assert manifest["volumes"][0]["name"] in ver["bad"] and "../outside.zip" in ver["bad"]
    assert not any(p.endswith(manifest["volumes"][0]["name"]) or "outside" in p for p in opened)


def test_the_checks_read_through_the_bounded_reader():
    verify = inspect.getsource(dv.verify_volume_set)
    load = inspect.getsource(dv.load_manifest)
    assert "_volume_matches(" in verify and ".stat()" not in verify
    assert "open_regular(" in load and "read_text(" not in load
    assert "sha256_read(" in inspect.getsource(dv._sha256_file)
