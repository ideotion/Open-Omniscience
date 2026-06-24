"""Reed-Solomon erasure parity over volumes (src/backup/parity.py), slice 2.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The recovery the maintainer chose: ANY <= M of the (N data + M parity) volumes may be
lost/corrupt and still rebuild exactly — including a corpus volume. Pins the GF(2^8)
algebra, EXHAUSTIVE erasure recovery (every subset of <= M erasures over a small code),
and the file-level auto-recovery through read_volume_set. numpy is the [analysis] extra,
so the whole module is skipped on a core install (where the backup is volumes-only).
"""

import itertools
import os

import pytest

np = pytest.importorskip("numpy")  # parity needs the [analysis] extra; core install skips

from src.backup.parity import (  # noqa: E402
    _cauchy,
    _decode,
    _encode,
    _gf_inv,
    _gf_mul,
    _mat_inv,
    parity_available,
    write_parity,
)
from src.backup.volumes import (  # noqa: E402
    VolumeError,
    load_manifest,
    read_volume_set,
    verify_volume_set,
    write_volume_set,
)


def test_gf_field_is_consistent():
    assert parity_available() is True
    for a in range(1, 256):
        assert _gf_mul(a, _gf_inv(a)) == 1  # every non-zero element has an inverse
    assert _gf_mul(0, 5) == 0 and _gf_mul(7, 0) == 0


def test_any_n_generator_rows_are_invertible():
    """The MDS property: any N rows of [I_n ; Cauchy] invert -> any M erasures recover."""
    n, m = 5, 3
    rows = [[1 if c == i else 0 for c in range(n)] for i in range(n)] + _cauchy(m, n)
    for combo in itertools.combinations(range(n + m), n):
        _mat_inv([rows[i] for i in combo])  # must not raise (singular)


def test_exhaustive_erasure_recovery():
    n, m, length = 5, 3, 200
    data = [np.frombuffer(os.urandom(length), dtype=np.uint8) for _ in range(n)]
    parity = _encode(data, m)
    allv = {i: data[i] for i in range(n)}
    allv.update({n + j: parity[j] for j in range(m)})
    for ecount in range(0, m + 1):
        for erased in itertools.combinations(range(n + m), ecount):
            present = {i: allv[i] for i in range(n + m) if i not in erased}
            erased_data = [i for i in erased if i < n]
            rebuilt = _decode(present, n, m, erased_data)
            for k in erased_data:
                assert bytes(rebuilt[k]) == bytes(data[k]), (erased, k)


def _vols(tmp_path, data: bytes, *, parity_count: int):
    src = tmp_path / "archive.bin"
    src.write_bytes(data)
    out = tmp_path / "vols"
    write_volume_set(src, out, "pw", volume_size=2048, chunk_size=1024)
    write_parity(out, parity_count=parity_count)
    return src, out


def test_write_parity_manifest_and_sizes(tmp_path):
    _src, out = _vols(tmp_path, os.urandom(5000), parity_count=2)  # 3 data volumes
    m = load_manifest(out)
    par = m["parity"]
    assert par["kind"] == "oo-parity-1" and par["data_count"] == 3 and par["count"] == 2
    assert len(par["volumes"]) == 2
    # parity volumes are the stripe length (the largest data volume) -> still < volume cap
    assert all(pv["bytes"] == par["stripe_len"] for pv in par["volumes"])


def test_restore_recovers_two_corrupt_data_volumes(tmp_path):
    data = os.urandom(5000)  # 3 data volumes; M=2 parity -> any 2 may die
    src, out = _vols(tmp_path, data, parity_count=2)
    for name in ("vol-00001.ooenc", "vol-00002.ooenc"):
        p = out / name
        p.write_bytes(p.read_bytes()[:-4])  # corrupt (truncate)
    assert verify_volume_set(out)["ok"] is False
    dest = tmp_path / "restored.bin"
    read_volume_set(out, "pw", dest)  # auto-recovers from parity
    assert dest.read_bytes() == data == src.read_bytes()


def test_restore_recovers_mixed_data_and_parity_loss(tmp_path):
    data = os.urandom(5000)
    _src, out = _vols(tmp_path, data, parity_count=2)
    (out / "vol-00001.ooenc").unlink()  # a data volume entirely LOST
    pp = out / "par-00001.oopar"
    pp.write_bytes(pp.read_bytes()[:-4])  # AND a parity volume corrupt = 2 erasures
    dest = tmp_path / "restored.bin"
    read_volume_set(out, "pw", dest)
    assert dest.read_bytes() == data


def test_too_many_erasures_fails_loudly(tmp_path):
    data = os.urandom(5000)  # 3 data volumes, M=1 parity -> 2 losses is unrecoverable
    _src, out = _vols(tmp_path, data, parity_count=1)
    for name in ("vol-00001.ooenc", "vol-00002.ooenc"):
        (out / name).unlink()
    with pytest.raises(VolumeError):
        read_volume_set(out, "pw", tmp_path / "x.bin")
