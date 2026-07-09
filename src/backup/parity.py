"""Reed-Solomon erasure parity over backup volumes (slice 2 of "volumes + parity").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Slice 1 split a backup into independently-authenticated <600 MB volumes and named the
exact corrupt/missing ones. This adds the RECOVERY the maintainer chose (2026-06-24): a
systematic MDS Reed-Solomon code over GF(2^8) produces M parity volumes such that ANY
corrupt/lost volume — INCLUDING a corpus volume — can be rebuilt, as long as no more
than M of the (N data + M parity) volumes are missing/corrupt at once. So a single SQLite
corpus, monolithic on its own, genuinely survives partial corruption once parity exists.

Layering: parity operates on the opaque CIPHERTEXT of the volumes (the .ooenc files), so
it is independent of the encryption — a rebuilt volume is then decrypted + GCM-verified by
the normal path, and its manifest SHA-256 confirms the reconstruction.

Performance: GF(2^8) arithmetic over multi-GB volumes is vectorised with numpy (a 256x256
multiply table + XOR over uint8 arrays). numpy is the ``[analysis]`` extra, so this module
imports WITHOUT it and degrades honestly: ``parity_available()`` is False on a core install
(the backup is then volumes-only; recovery of a corrupt volume is unavailable, reported
loudly — never a silent partial restore). The small matrix algebra (Cauchy build + inverse)
is exact-integer pure Python.

BOUNDED RAM (P0.1, 2026-07-09): the first implementation loaded EVERY volume into RAM at
once (N x 512 MiB = the whole archive — the 11.7 GB field corpus alone exceeds the 10 GB
field VM, so parity itself was an OOM on the very path meant to save the corpus). Encoding
and recovery now work in fixed-size BANDS across the stripe: memory is (m_parity + 1) bands
for encode and (n_erased + 1) bands for decode — a few hundred MiB regardless of corpus
size. The GF math is bytewise, so banding changes no output byte (the parity files are
bit-identical to the whole-stripe computation).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from src.backup.volumes import MANIFEST_NAME, VolumeError, _sha256_file, load_manifest

PARITY_KIND = "oo-parity-1"
_GF_LIMIT = 256  # GF(2^8): at most 255 data+parity volumes (128 GiB at 512 MiB volumes)
# Stripe band processed per pass. Encode holds (m+1) bands, decode (erased+1) bands —
# the bound that keeps parity off the OOM path regardless of corpus size.
_BAND_BYTES_DEFAULT = 32 * 1024 * 1024


# --------------------------------------------------------------------------- #
#  GF(2^8) arithmetic (generator polynomial 0x11d, the standard RS/AES field)
# --------------------------------------------------------------------------- #
def _gf_tables() -> tuple[list[int], list[int]]:
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _gf_tables()


def _gf_mul(a: int, b: int) -> int:
    return 0 if (a == 0 or b == 0) else _EXP[_LOG[a] + _LOG[b]]


def _gf_inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError("GF(2^8): 0 has no inverse")
    return _EXP[255 - _LOG[a]]


def _cauchy(m: int, n: int) -> list[list[int]]:
    """An m x n Cauchy matrix over GF(2^8): G[j][k] = 1 / ((n+j) XOR k). With the data
    using the identity rows e_0..e_{n-1}, the full (n+m) x n generator is MDS, so ANY n
    of its rows are invertible -> any M erasures (data or parity) are recoverable."""
    return [[_gf_inv((n + j) ^ k) for k in range(n)] for j in range(m)]


def _mat_inv(mat: list[list[int]]) -> list[list[int]]:
    """Gauss-Jordan inverse over GF(2^8) (subtraction is XOR). ``mat`` is n x n."""
    n = len(mat)
    a = [row[:] + [1 if i == j else 0 for j in range(n)] for i, row in enumerate(mat)]
    for col in range(n):
        piv = next((r for r in range(col, n) if a[r][col] != 0), None)
        if piv is None:
            raise ValueError("singular matrix (should not happen for a Cauchy/MDS code)")
        a[col], a[piv] = a[piv], a[col]
        inv = _gf_inv(a[col][col])
        a[col] = [_gf_mul(inv, v) for v in a[col]]
        for r in range(n):
            if r != col and a[r][col] != 0:
                f = a[r][col]
                a[r] = [a[r][j] ^ _gf_mul(f, a[col][j]) for j in range(2 * n)]
    return [row[n:] for row in a]


# --------------------------------------------------------------------------- #
#  numpy fast path
# --------------------------------------------------------------------------- #
def parity_available() -> bool:
    """True when numpy is importable (the [analysis] extra) -> parity can be computed."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _np() -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - guarded by parity_available()
        raise VolumeError(
            "parity needs numpy (the 'analysis' extra); this build is volumes-only"
        ) from exc
    return np


_MUL_TABLE: Any = None


def _mul_table() -> Any:
    """A cached 256x256 GF multiply table as a numpy uint8 array: MUL[s][v] = s*v."""
    global _MUL_TABLE
    if _MUL_TABLE is None:
        np = _np()
        t = np.zeros((256, 256), dtype=np.uint8)
        for s in range(1, 256):
            ls = _LOG[s]
            for v in range(1, 256):
                t[s, v] = _EXP[ls + _LOG[v]]
        _MUL_TABLE = t
    return _MUL_TABLE


def _encode(data: list[Any], m: int) -> list[Any]:
    """Encode m parity arrays from n equal-length uint8 data arrays."""
    np = _np()
    n = len(data)
    length = int(data[0].size)
    g = _cauchy(m, n)
    mul = _mul_table()
    out = []
    for j in range(m):
        acc = np.zeros(length, dtype=np.uint8)
        for k in range(n):
            coef = g[j][k]
            if coef:
                acc ^= mul[coef][data[k]]
        out.append(acc)
    return out


def _decode(present: dict[int, Any], n: int, m: int, erased_data: list[int]) -> dict[int, Any]:
    """Reconstruct the erased DATA arrays from >= n present arrays (data rows are the
    identity 0..n-1, parity rows are n..n+m-1)."""
    np = _np()
    g = _cauchy(m, n)

    def row(i: int) -> list[int]:
        return [1 if c == i else 0 for c in range(n)] if i < n else g[i - n]

    chosen = sorted(present)[:n]
    inv = _mat_inv([row(i) for i in chosen])
    mul = _mul_table()
    length = int(next(iter(present.values())).size)
    out: dict[int, Any] = {}
    for k in erased_data:
        acc = np.zeros(length, dtype=np.uint8)
        for ri, r in enumerate(chosen):
            coef = inv[k][ri]
            if coef:
                acc ^= mul[coef][present[r]]
        out[k] = acc
    return out


# --------------------------------------------------------------------------- #
#  File-level: write parity for a volume set, and recover corrupt volumes
#  (band-wise: bounded RAM regardless of archive size — see the module docstring)
# --------------------------------------------------------------------------- #
def _load_padded(path: Path, length: int) -> Any:
    np = _np()
    raw = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    if raw.size < length:
        raw = np.concatenate([raw, np.zeros(length - raw.size, dtype=np.uint8)])
    return raw


def _read_band(path: Path, offset: int, length: int) -> Any:
    """Read ``length`` bytes of ``path`` at ``offset`` as a uint8 array, zero-padded
    past EOF (the stripe padding the whole-array `_load_padded` applied)."""
    np = _np()
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            raw = fh.read(length)
    except FileNotFoundError:
        raw = b""
    arr = np.frombuffer(raw, dtype=np.uint8)
    if arr.size < length:
        arr = np.concatenate([arr, np.zeros(length - arr.size, dtype=np.uint8)])
    return arr


def write_parity(
    out_dir: str | os.PathLike[str],
    *,
    parity_count: int | None = None,
    parity_fraction: float = 0.1,
    band_bytes: int = _BAND_BYTES_DEFAULT,
) -> dict[str, Any]:
    """Compute M parity volumes for an existing volume set and record them in the manifest.

    M = ``parity_count`` or ceil(``parity_fraction`` * N) (>= 1). Each parity volume is the
    stripe length (the largest data volume), so it stays < the volume size cap. Requires
    numpy; raises VolumeError otherwise (the set is then volumes-only).

    BOUNDED RAM: the stripe is processed in ``band_bytes`` bands — (M+1) bands in memory,
    never the whole volume set (the whole-set load was itself an OOM at field scale).
    Banding is bytewise-exact: the parity files are identical to a whole-stripe encode."""
    np = _np()
    if band_bytes < 1:
        raise VolumeError("band_bytes must be >= 1")
    out = Path(out_dir)
    manifest = load_manifest(out)
    data_files = [out / v["name"] for v in manifest["volumes"]]
    n = len(data_files)
    if n == 0:
        raise VolumeError("no volumes to protect")
    m = parity_count if parity_count is not None else max(1, math.ceil(parity_fraction * n))
    if n + m >= _GF_LIMIT:
        raise VolumeError(
            f"too many volumes for GF(2^8) parity (N+M={n + m} >= {_GF_LIMIT}); "
            "use larger volumes"
        )
    stripe = max(f.stat().st_size for f in data_files)
    g = _cauchy(m, n)
    mul = _mul_table()

    par_paths = [out / f"par-{j + 1:05d}.oopar" for j in range(m)]
    tmp_paths = [p.with_name(p.name + ".oopart") for p in par_paths]
    handles = [open(p, "wb") for p in tmp_paths]
    try:
        for off in range(0, stripe, band_bytes):
            blen = min(band_bytes, stripe - off)
            acc = [np.zeros(blen, dtype=np.uint8) for _ in range(m)]
            for k, f in enumerate(data_files):
                band = _read_band(f, off, blen)
                for j in range(m):
                    coef = g[j][k]
                    if coef:
                        acc[j] ^= mul[coef][band]
            for j, fh in enumerate(handles):
                fh.write(np.ascontiguousarray(acc[j]).tobytes())
    finally:
        for fh in handles:
            fh.close()
    par_meta = []
    for p, tmp in zip(par_paths, tmp_paths, strict=True):
        os.replace(tmp, p)
        par_meta.append({"name": p.name, "sha256": _sha256_file(p), "bytes": p.stat().st_size})

    manifest["parity"] = {
        "kind": PARITY_KIND,
        "generator": "cauchy-gf256",
        "data_count": n,
        "count": m,
        "stripe_len": stripe,
        "volumes": par_meta,
    }
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest["parity"]


def recover_volumes(
    manifest: dict[str, Any],
    bad: list[str],
    *,
    out_dir: str | os.PathLike[str],
    band_bytes: int = _BAND_BYTES_DEFAULT,
) -> list[str]:
    """The :func:`src.backup.volumes.read_volume_set` ``recover`` hook: rebuild the corrupt
    DATA volumes named in ``bad`` from parity, in place, and return the volumes that could
    NOT be repaired (too many lost, or no parity / no numpy). Each rebuilt volume is checked
    against its manifest SHA-256 BEFORE it replaces anything, so a wrong reconstruction is
    reported and discarded, never installed or trusted.

    BOUNDED RAM: banded like :func:`write_parity` — (n_erased + 1) bands in memory,
    never the whole surviving set."""
    par = manifest.get("parity")
    if not par or not parity_available():
        return list(bad)  # cannot recover -> all still bad (loud failure upstream)

    np = _np()
    out = Path(out_dir)
    n = int(par["data_count"])
    m = int(par["count"])
    stripe = int(par["stripe_len"])
    data_meta = manifest["volumes"]
    bad_set = set(bad)
    # A corrupt parity volume must not poison recovery: re-verify parity integrity too.
    for pv in par["volumes"]:
        p = out / pv["name"]
        if not p.exists() or _sha256_file(p) != pv["sha256"]:
            bad_set.add(pv["name"])

    present_rows: list[tuple[int, Path]] = []
    erased_data: list[int] = []
    for k, v in enumerate(data_meta):
        if v["name"] in bad_set:
            erased_data.append(k)
        else:
            present_rows.append((k, out / v["name"]))
    for j, pv in enumerate(par["volumes"]):
        if pv["name"] not in bad_set:
            present_rows.append((n + j, out / pv["name"]))

    if len(present_rows) < n:  # fewer than N survivors -> mathematically unrecoverable
        return [b for b in bad if b in bad_set]

    g = _cauchy(m, n)

    def row(i: int) -> list[int]:
        return [1 if c == i else 0 for c in range(n)] if i < n else g[i - n]

    chosen = sorted(present_rows)[:n]
    inv = _mat_inv([row(i) for i, _ in chosen])
    mul = _mul_table()

    tmp_paths = {
        k: out / (data_meta[k]["name"] + ".oopart") for k in erased_data
    }
    handles = {k: open(p, "wb") for k, p in tmp_paths.items()}
    try:
        for off in range(0, stripe, band_bytes):
            blen = min(band_bytes, stripe - off)
            acc = {k: np.zeros(blen, dtype=np.uint8) for k in erased_data}
            for ri, (_, path) in enumerate(chosen):
                band = _read_band(path, off, blen)
                for k in erased_data:
                    coef = inv[k][ri]
                    if coef:
                        acc[k] ^= mul[coef][band]
            for k in erased_data:
                real_len = int(data_meta[k]["bytes"])
                # Trim the zero padding: write only the bytes inside the real volume.
                if off < real_len:
                    keep = min(blen, real_len - off)
                    handles[k].write(np.ascontiguousarray(acc[k][:keep]).tobytes())
    finally:
        for fh in handles.values():
            fh.close()

    unrepaired: list[str] = []
    for k in erased_data:
        target = out / data_meta[k]["name"]
        if _sha256_file(tmp_paths[k]) != data_meta[k]["sha256"]:
            unrepaired.append(data_meta[k]["name"])  # reconstruction did not verify
            tmp_paths[k].unlink(missing_ok=True)  # never install a wrong rebuild
        else:
            os.replace(tmp_paths[k], target)
    return unrepaired
