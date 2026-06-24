"""Multi-volume encrypted backup codec (src/backup/volumes.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Slice 1 of the maintainer-chosen "volumes + parity" large backup. Pins: a large
archive splits into independently-authenticated <volume_size> volumes and reassembles
byte-identically; per-volume SHA-256 verification names exactly which volume is corrupt
or missing; a corrupt volume fails the restore LOUDLY (no silent partial archive) when
no recovery is available; the slice-2 ``recover`` hook is invoked with the bad set and,
when it repairs them, the restore completes; a wrong passphrase fails loudly.
"""

import os

import pytest

from src.backup.volumes import (
    VolumeError,
    load_manifest,
    read_volume_set,
    verify_volume_set,
    write_volume_set,
)

VOL = 2048  # tiny volumes to force a multi-volume set on a few KB
CS = 1024


def _make(tmp_path, data: bytes):
    src = tmp_path / "archive.bin"
    src.write_bytes(data)
    out = tmp_path / "vols"
    manifest = write_volume_set(src, out, "pw", volume_size=VOL, chunk_size=CS)
    return src, out, manifest


def test_split_and_reassemble_round_trip(tmp_path):
    data = os.urandom(5000)  # -> 3 volumes (2048, 2048, 904)
    src, out, manifest = _make(tmp_path, data)
    assert len(manifest["volumes"]) == 3
    assert manifest["plaintext_bytes"] == 5000
    assert verify_volume_set(out)["ok"] is True

    dest = tmp_path / "restored.bin"
    info = read_volume_set(out, "pw", dest)
    assert dest.read_bytes() == data
    assert info["volumes"] == 3


def test_exact_multiple_has_no_empty_trailing_volume(tmp_path):
    data = os.urandom(VOL * 2)  # exact 2 volumes; the trailing empty volume is dropped
    _src, out, manifest = _make(tmp_path, data)
    assert len(manifest["volumes"]) == 2
    dest = tmp_path / "r.bin"
    read_volume_set(out, "pw", dest)
    assert dest.read_bytes() == data


def test_verify_names_the_corrupt_volume(tmp_path):
    _src, out, _m = _make(tmp_path, os.urandom(5000))
    victim = out / "vol-00002.ooenc"
    b = bytearray(victim.read_bytes())
    b[-1] ^= 1  # bit-rot in the middle volume
    victim.write_bytes(bytes(b))
    status = verify_volume_set(out)
    assert status["ok"] is False and status["bad"] == ["vol-00002.ooenc"]


def test_missing_volume_is_reported(tmp_path):
    _src, out, _m = _make(tmp_path, os.urandom(5000))
    (out / "vol-00003.ooenc").unlink()
    status = verify_volume_set(out)
    assert "vol-00003.ooenc" in status["missing"] and "vol-00003.ooenc" in status["bad"]


def test_restore_fails_loudly_on_corruption_without_recovery(tmp_path):
    _src, out, _m = _make(tmp_path, os.urandom(5000))
    victim = out / "vol-00002.ooenc"
    victim.write_bytes(victim.read_bytes()[:-4])  # truncate -> sha mismatch
    with pytest.raises(VolumeError) as exc:
        read_volume_set(out, "pw", tmp_path / "out.bin")
    assert "vol-00002.ooenc" in str(exc.value)


def test_recover_hook_repairs_then_restore_completes(tmp_path):
    """The slice-2 parity seam: a corrupt volume is handed to ``recover``, which (here)
    restores it from a saved good copy and reports nothing unrepaired -> restore works."""
    src, out, _m = _make(tmp_path, os.urandom(5000))
    victim = out / "vol-00002.ooenc"
    good = victim.read_bytes()
    victim.write_bytes(good[:-4])  # corrupt it

    def recover(_manifest, bad):
        assert bad == ["vol-00002.ooenc"]
        victim.write_bytes(good)  # stand-in for parity rebuild
        return []  # nothing left unrepaired

    dest = tmp_path / "rec.bin"
    read_volume_set(out, "pw", dest, recover=recover)
    assert dest.read_bytes() == src.read_bytes()


def test_wrong_passphrase_fails_loudly(tmp_path):
    _src, out, _m = _make(tmp_path, os.urandom(3000))
    with pytest.raises(Exception):  # noqa: B017 - EncryptionError or VolumeError, both loud
        read_volume_set(out, "WRONG", tmp_path / "out.bin")


def test_manifest_shape(tmp_path):
    _src, out, _m = _make(tmp_path, os.urandom(3000))
    m = load_manifest(out)
    assert m["kind"] == "oo-volumes-1" and m["parity"] is None
    for v in m["volumes"]:
        assert {"name", "sha256", "bytes", "plaintext_bytes"} <= set(v)
