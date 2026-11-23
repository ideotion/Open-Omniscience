"""Row 336: the checksum pass reads a volume at most one block past the size its manifest lists.

A volume swapped for a huge sparse file, or for one that keeps growing, used to be hashed to its end: a restore's verify, the
volume-set check and the parity check each read every byte of whatever stood under the volume's name. Now a file longer than
the listed size does not match, from its size alone when it already is, and from the read when it grows while being read."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import src.backup.bounded_hash as bounded_hash
import src.backup.volumes as vol
from src.backup.volumes import _COPY_BUF, _digest_matches, listed_bytes
from tests.os_scope import scope_os


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
    assert _digest_matches(big, "0" * 64, max_bytes=1000) is False
    assert time.monotonic() - t0 < 5 and reads == []


def test_a_volume_that_grows_while_it_is_read_is_cut_one_block_past_its_size(tmp_path, monkeypatch):
    """fstat says the listed size; the file keeps yielding bytes (an ever-growing file). The read stops just past the bound."""
    listed = 3 * _COPY_BUF + 17
    grower = _sparse(tmp_path / "v0002.ooenc", 40 * _COPY_BUF)
    real_fstat = os.fstat
    scope_os(monkeypatch, bounded_hash, fstat=lambda fd: os.stat_result((*real_fstat(fd)[:6], listed, *real_fstat(fd)[7:])))
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
    assert _digest_matches(grower, "0" * 64, max_bytes=listed) is False
    assert listed < total[0] <= listed + 1  # one byte past the bound proves it is longer; nothing more is read


def test_a_volume_of_exactly_the_listed_size_still_matches(tmp_path):
    p = tmp_path / "v0003.ooenc"
    p.write_bytes(os.urandom(2 * _COPY_BUF + 5))
    want = vol._sha256_file(p)
    assert _digest_matches(p, want, max_bytes=p.stat().st_size) is True
    assert _digest_matches(p, want, max_bytes=p.stat().st_size - 1) is False  # one byte longer than listed
    assert vol._sha256_file(p) == want  # the low-level read without a bound is still there for the writers


@pytest.mark.parametrize("value", [None, -1, "12", 1.5, True])
def test_an_entry_without_a_whole_number_size_never_matches(value, tmp_path):
    """Security read of row 336: the size sits in the same manifest as the volumes, so whoever swaps in a huge file can
    drop it too; a missing or malformed size is a mismatch, never a switch that turns the bound off."""
    assert listed_bytes({"bytes": value}) is None
    assert listed_bytes("not an entry") is None
    p = tmp_path / "v0001.ooenc"
    p.write_bytes(b"x" * 10)
    entry = {"name": p.name, "sha256": vol._sha256_file(p), "bytes": value}
    assert _digest_matches(p, entry["sha256"], max_bytes=listed_bytes(entry)) is False
    assert _digest_matches(p, entry["sha256"], max_bytes=listed_bytes({**entry, "bytes": 10})) is True


def test_dropping_the_size_from_the_list_does_not_reopen_the_long_read(tmp_path, monkeypatch):
    from src.backup.volumes import MANIFEST_NAME, verify_volume_set, write_volume_set

    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(200_000))
    out = tmp_path / "set"
    write_volume_set(src, out, "pw", volume_size=65536)
    man = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    for v in man["volumes"]:
        v.pop("bytes", None)
    (out / MANIFEST_NAME).write_text(json.dumps(man), encoding="utf-8")
    first = sorted(out.glob("*.ooenc"))[0]
    first.unlink()
    _sparse(first, 64 * 1024**3)
    read = [0]
    real = vol.open_regular

    def counting(path):
        fh = real(path)
        inner = fh.read

        def r(n=-1):
            b = inner(n)
            read[0] += len(b)
            return b

        fh.read = r  # type: ignore[method-assign]
        return fh

    monkeypatch.setattr(vol, "open_regular", counting)
    status = verify_volume_set(out)
    assert first.name in status["bad"] and not status["ok"]
    assert read[0] == 0, "no entry lists a size, so nothing is hashed at all"


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


# --------------------------------------------------------------------------- #
# Row 342: the folder-backup verify hashes through the same bounded read.
# --------------------------------------------------------------------------- #


def _folder_backup(tmp_path):
    from src.backup.folder_backup import BackupItem, verify_folder_backup, write_folder_backup

    src = tmp_path / "src"
    src.mkdir()
    (src / "c.pbf").write_bytes(b"c" * 200)
    dest = tmp_path / "dest"
    write_folder_backup(dest, [BackupItem("osm_regions", "europe.pbf", src / "c.pbf", 200)])
    assert verify_folder_backup(dest)["ok"] is True
    return dest


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="finds the open file's name through /proc")
def test_a_folder_member_that_grows_after_its_size_was_checked_is_a_mismatch_read_no_further(tmp_path, monkeypatch):
    from src.backup import folder_backup
    from src.backup.folder_backup import verify_folder_backup

    dest = _folder_backup(tmp_path)
    real = folder_backup._hash_fd

    def grows_then_hashes(fd, **k):
        with open(os.readlink(f"/proc/self/fd/{fd}"), "ab") as f:  # the size check has passed; now it grows
            f.write(b"x" * (4 * _COPY_BUF))
        assert k.get("max_bytes") == 200, "the folder verify hands the listed size to the read"
        return real(fd, **k)

    monkeypatch.setattr(folder_backup, "_hash_fd", grows_then_hashes)
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert {p["rel"]: p["status"] for p in rep["problems"]}["europe.pbf"] == "checksum_mismatch"


def test_the_folder_hash_helpers_stop_one_byte_past_the_listed_size(tmp_path):
    from src.backup import folder_backup
    from src.backup.bounded_hash import LongerThanListed

    big = tmp_path / "big.pbf"
    _sparse(big, 64 * 1024**3)
    t0 = time.monotonic()
    with pytest.raises(LongerThanListed):
        folder_backup._sha256_file(big, 200)
    with pytest.raises(LongerThanListed):
        folder_backup._hash_fd(os.open(big, os.O_RDONLY), max_bytes=200)
    assert time.monotonic() - t0 < 5
    small = tmp_path / "s.pbf"
    small.write_bytes(b"c" * 200)
    assert folder_backup._sha256_file(small, 200) == folder_backup._hash_fd(os.open(small, os.O_RDONLY), max_bytes=200)
