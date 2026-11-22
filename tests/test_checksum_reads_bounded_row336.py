"""Row 336: the checksum pass reads a volume at most one block past the size its manifest lists.

A volume swapped for a huge sparse file, or for one that keeps growing, used to be hashed to its end: a restore's verify, the
volume-set check and the parity check each read every byte of whatever stood under the volume's name. Now a file longer than
the listed size does not match, from its size alone when it already is, and from the read when it grows while being read."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import src.backup.volumes as vol
from src.backup.volumes import _COPY_BUF, _digest_matches, listed_bytes


def _sparse(path: Path, size: int) -> Path:
    with open(path, "wb") as fh:
        fh.truncate(size)
    return path


def test_a_huge_sparse_volume_is_refused_from_its_size_without_a_read(tmp_path, monkeypatch):
    big = _sparse(tmp_path / "v0001.ooenc", 64 * 1024**3)  # 64 GiB of holes
    reads: list[int] = []
    real_open = vol.open_regular

    def counting(path, **kw):
        fh = real_open(path, **kw)
        real_read = fh.read
        fh.read = lambda n=-1: (lambda b: reads.append(len(b)) or b)(real_read(n))  # type: ignore[method-assign]
        return fh

    monkeypatch.setattr(vol, "open_regular", counting)
    t0 = time.monotonic()
    assert _digest_matches(big, "0" * 64, 1000) is False
    assert time.monotonic() - t0 < 5 and reads == []


def test_a_volume_that_grows_while_it_is_read_is_cut_one_block_past_its_size(tmp_path, monkeypatch):
    """fstat says the listed size; the file keeps yielding bytes (an ever-growing file). The read stops just past the bound."""
    listed = 3 * _COPY_BUF + 17
    grower = _sparse(tmp_path / "v0002.ooenc", 40 * _COPY_BUF)
    real_fstat = os.fstat
    monkeypatch.setattr(vol.os, "fstat", lambda fd: os.stat_result((*real_fstat(fd)[:6], listed, *real_fstat(fd)[7:])))
    total = [0]
    real_open = vol.open_regular

    def counting(path, **kw):
        fh = real_open(path, **kw)
        real_read = fh.read

        def read(n=-1):
            b = real_read(n)
            total[0] += len(b)
            return b

        fh.read = read  # type: ignore[method-assign]
        return fh

    monkeypatch.setattr(vol, "open_regular", counting)
    assert _digest_matches(grower, "0" * 64, listed) is False
    assert listed < total[0] <= listed + 1  # one byte past the bound proves it is longer; nothing more is read


def test_a_volume_of_exactly_the_listed_size_still_matches(tmp_path):
    p = tmp_path / "v0003.ooenc"
    p.write_bytes(os.urandom(2 * _COPY_BUF + 5))
    want = vol._sha256_file(p)
    assert _digest_matches(p, want, p.stat().st_size) is True
    assert _digest_matches(p, want, p.stat().st_size - 1) is False  # one byte longer than listed: not the file listed
    assert _digest_matches(p, want, None) is True  # no listed size (an older manifest): unbounded, as before
    assert _digest_matches(tmp_path / "v0003.ooenc", want) is True


@pytest.mark.parametrize("value", [None, -1, "12", 1.5, True])
def test_a_size_that_is_not_a_whole_number_of_bytes_is_no_bound(value):
    assert listed_bytes({"bytes": value}) is None
    assert listed_bytes("not an entry") is None


def test_the_volume_set_check_never_reads_a_swapped_sparse_volume_to_its_end(tmp_path):
    from src.backup.volumes import verify_volume_set, write_volume_set

    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(200_000))
    out = tmp_path / "set"
    write_volume_set(src, out, "pw", volume_size=65536)
    first = sorted(out.glob("*.ooenc"))[0]
    first.unlink()
    _sparse(first, 64 * 1024**3)
    t0 = time.monotonic()
    status = verify_volume_set(out)
    assert first.name in status["bad"] and not status["ok"]
    assert time.monotonic() - t0 < 10
