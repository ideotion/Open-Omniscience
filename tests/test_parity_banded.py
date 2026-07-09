"""Banded (bounded-RAM) Reed-Solomon parity — P0.1 scale rework.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The first parity implementation loaded EVERY volume into RAM at once (N x 512 MiB =
the whole archive), which is itself an OOM at field scale — the very failure the
backup is meant to survive. write_parity/recover_volumes now stream the stripe in
fixed-size BANDS. These tests pin that banding is bytewise-EXACT (same parity files
as a whole-stripe pass) and that a reconstruction that fails its manifest checksum
is discarded, never installed over the original bytes.
"""

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from src.backup.parity import recover_volumes, write_parity  # noqa: E402
from src.backup.volumes import load_manifest, write_volume_set  # noqa: E402


def _make_set(tmp: Path, name: str, payload: bytes) -> Path:
    src = tmp / f"{name}.bin"
    src.write_bytes(payload)
    dest = tmp / name
    write_volume_set(src, dest, "pw", volume_size=4096, chunk_size=1024)
    return dest


def _payload() -> bytes:
    # > several volumes, sizes NOT band-aligned so band edges + EOF padding are exercised.
    return bytes((i * 131 + 7) % 256 for i in range(4096 * 3 + 1234))


def test_banded_parity_is_bytewise_identical_to_whole_stripe(tmp_path):
    payload = _payload()
    a = _make_set(tmp_path, "a", payload)
    b = _make_set(tmp_path, "b", payload)
    # The two sets have different ciphertext (fresh salts), so compare each set's
    # banded parity against ITS OWN whole-stripe parity, not set A against set B.
    for dest in (a, b):
        stripe = max(p.stat().st_size for p in dest.glob("vol-*.ooenc"))
        write_parity(dest, parity_count=2, band_bytes=999)  # tiny, non-aligned bands
        banded = {p.name: p.read_bytes() for p in dest.glob("par-*.oopar")}
        for p in dest.glob("par-*.oopar"):
            p.unlink()
        write_parity(dest, parity_count=2, band_bytes=stripe + 1)  # one whole-stripe band
        whole = {p.name: p.read_bytes() for p in dest.glob("par-*.oopar")}
        assert banded == whole


def test_banded_recovery_rebuilds_a_corrupt_volume(tmp_path):
    dest = _make_set(tmp_path, "set", _payload())
    write_parity(dest, parity_count=2, band_bytes=777)
    manifest = load_manifest(dest)
    victim = dest / manifest["volumes"][1]["name"]
    good = victim.read_bytes()
    victim.write_bytes(good[:100] + b"X" * 32 + good[132:])  # same-length corruption

    unrepaired = recover_volumes(
        manifest, [victim.name], out_dir=dest, band_bytes=777
    )
    assert unrepaired == []
    assert victim.read_bytes() == good


def test_failed_reconstruction_is_never_installed(tmp_path):
    dest = _make_set(tmp_path, "set", _payload())
    write_parity(dest, parity_count=1, band_bytes=512)
    manifest = load_manifest(dest)

    # Sabotage: corrupt a parity volume but FORGE its manifest entry so the
    # integrity re-check cannot exclude it — the reconstruction then computes
    # wrong bytes and MUST be discarded, not installed.
    par = dest / manifest["parity"]["volumes"][0]["name"]
    par.write_bytes(bytes(len(par.read_bytes())))
    import hashlib

    manifest["parity"]["volumes"][0]["sha256"] = hashlib.sha256(par.read_bytes()).hexdigest()
    (dest / "volumes.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    victim = dest / manifest["volumes"][0]["name"]
    corrupt = b"Z" * victim.stat().st_size
    victim.write_bytes(corrupt)

    unrepaired = recover_volumes(manifest, [victim.name], out_dir=dest, band_bytes=512)
    assert unrepaired == [victim.name]  # loud: named as unrepaired
    assert victim.read_bytes() == corrupt  # original bytes untouched — nothing installed
    assert not (dest / (victim.name + ".oopart")).exists()  # temp cleaned
