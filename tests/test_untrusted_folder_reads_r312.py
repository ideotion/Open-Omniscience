"""Row 312: every read of a file inside an untrusted backup folder, destination or import folder is a regular-file read.

A backup folder, an export destination and a folder offered to the import scan sit on a drive anyone may have
written to. Row 308 hardened the export's reads of the destination's manifests; this row sweeps the rest: the
import scan's leftover check (both the folder-handle path and the Windows path) and its source-list CSV sniff,
the volume and parity checksum passes of a verify and a restore, parity recovery's band reads, the folder-backup
verify and the stream decryption itself. Each one now goes through ``src.backup.regular_file`` (never a link,
never blocking, the OPENED file checked to be regular), so a named pipe can no longer hold a scan, a verify or a
restore for ever, a link to ``/dev/zero`` is never read without end, and what a sound set does is unchanged.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from src.backup import import_scan, regular_file, volumes
from src.backup.manifest_file import read_manifest_json
from src.backup.regular_file import NotARegularFile, open_regular, open_regular_fd
from src.safety.crypto import EncryptionError, decrypt_stream, encrypt_file, stream_key_opens
from tests.js_source_helper import python_function_source

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


def _plant(p: Path, kind: str) -> None:
    if kind == "fifo":
        os.mkfifo(p)
    elif kind == "zero":
        os.symlink("/dev/zero", p)
    else:  # a link to a perfectly regular file outside the folder
        outside = p.parent.parent / ("outside-" + p.name)
        outside.write_bytes(b"outside")
        os.symlink(outside, p)


KINDS = ["fifo", "zero", "link"]


# --------------------------------------------------------------------------- the shared opener


def test_a_regular_file_reads_as_before(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"x" * 70_000)
    with open_regular(p) as fh:
        assert fh.read() == b"x" * 70_000  # O_NONBLOCK changes nothing for a regular file


@posix_only
@pytest.mark.parametrize("kind", KINDS)
def test_the_opener_refuses_without_reading_or_blocking(tmp_path, kind):
    (tmp_path / "d").mkdir()
    p = tmp_path / "d" / "f"
    _plant(p, kind)
    with pytest.raises(NotARegularFile):
        _within(5, lambda: open_regular(p))


@posix_only
def test_following_a_link_still_refuses_a_pipe_or_a_device_at_its_end(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    os.symlink(tmp_path / "pipe", tmp_path / "to-pipe")
    os.symlink("/dev/zero", tmp_path / "to-zero")
    (tmp_path / "real").write_bytes(b"ok")
    os.symlink(tmp_path / "real", tmp_path / "to-real")
    for name in ("to-pipe", "to-zero", "pipe"):
        with pytest.raises(NotARegularFile):
            _within(5, lambda n=name: open_regular(tmp_path / n, follow_links=True))
    with open_regular(tmp_path / "to-real", follow_links=True) as fh:
        assert fh.read() == b"ok"


@posix_only
def test_a_name_swapped_after_the_look_is_refused(tmp_path, monkeypatch):
    """Where there is no O_NOFOLLOW (Windows), the identity of the file opened is compared with the one looked at."""
    (tmp_path / "a").write_bytes(b"a")
    (tmp_path / "b").write_bytes(b"b")
    class _SwappingOs:  # this module's own view of os, never the process's (R351)
        def __getattr__(self, name):
            return getattr(os, name)

        @staticmethod
        def open(p, *a, **k):
            # Between the look and the open the name is swapped for a link, and (as on Windows, with no O_NOFOLLOW)
            # the open follows it to another regular file.
            os.unlink(tmp_path / "a")
            os.symlink(tmp_path / "b", tmp_path / "a")
            return os.open(tmp_path / "b", *a, **k)

    monkeypatch.setattr(regular_file, "os", _SwappingOs())
    with pytest.raises(NotARegularFile):
        open_regular_fd(tmp_path / "a")


def test_a_folder_is_refused(tmp_path):
    with pytest.raises(NotARegularFile):
        open_regular_fd(tmp_path)


@posix_only
def test_the_handle_relative_manifest_read(tmp_path):
    (tmp_path / "m.json").write_text('{"a": 1}', encoding="utf-8")
    os.mkfifo(tmp_path / "p.json")
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert read_manifest_json("m.json", dir_fd=fd) == {"a": 1}
        assert _within(5, lambda: read_manifest_json("p.json", dir_fd=fd)) is None
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- the import scan


def _v1_folder(d: Path) -> None:
    d.mkdir()
    (d / "vol-00001.ooenc").write_bytes(b"c")
    (d / "vol-00001.ooenc.plain").write_bytes(b"p")
    (d / "volumes.json").write_text(json.dumps({"kind": "oo-volumes-1", "volumes": [{"name": "vol-00001.ooenc"}]}), encoding="utf-8")


def test_a_leftover_is_still_found_on_both_paths(tmp_path, monkeypatch):
    d = tmp_path / "b"
    _v1_folder(d)
    assert import_scan.leftover_plaintext(d) == ["vol-00001.ooenc.plain"]
    monkeypatch.setattr(import_scan, "can_scan_by_handle", lambda: False)  # the Windows path
    assert import_scan.leftover_plaintext(d) == ["vol-00001.ooenc.plain"]


@posix_only
@pytest.mark.parametrize("handle", [True, False], ids=["folder-handle", "no-handle"])
@pytest.mark.parametrize("kind", ["fifo", "zero"])
def test_a_planted_manifest_never_blocks_the_leftover_check(tmp_path, monkeypatch, handle, kind):
    d = tmp_path / "b"
    _v1_folder(d)
    (d / "volumes.json").unlink()
    _plant(d / "volumes.json", kind)
    if not handle:
        monkeypatch.setattr(import_scan, "can_scan_by_handle", lambda: False)
    assert _within(5, lambda: import_scan.leftover_plaintext(d)) == []


@pytest.mark.parametrize("handle", [True, False], ids=["folder-handle", "no-handle"])
def test_a_deeply_nested_manifest_offers_nothing(tmp_path, monkeypatch, handle):
    d = tmp_path / "b"
    _v1_folder(d)
    (d / "volumes.json").write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")
    if not handle:
        monkeypatch.setattr(import_scan, "can_scan_by_handle", lambda: False)
    assert import_scan.leftover_plaintext(d) == []


@posix_only
@pytest.mark.parametrize("kind", KINDS)
def test_a_planted_csv_never_blocks_the_scan(tmp_path, kind):
    d = tmp_path / "scan"
    d.mkdir()
    (d / "sources.csv").write_text("domain,name\nexample.org,x\n", encoding="utf-8")
    _plant(d / "trap.csv", kind)
    found = _within(30, lambda: import_scan.scan_import_folder(d))["found"]
    assert found.get("source_csv") == ["sources.csv"]


def test_the_csv_sniff_reads_one_bounded_line(tmp_path):
    p = tmp_path / "big.csv"
    p.write_bytes(b"x" * (import_scan._CSV_SNIFF_BYTES * 3) + b"domain\n")
    assert import_scan._looks_like_source_csv(p) is False  # the header line was never read whole
    (tmp_path / "ok.csv").write_text("Domain,label\n", encoding="utf-8")
    assert import_scan._looks_like_source_csv(tmp_path / "ok.csv") is True


# --------------------------------------------------------------------------- verify, parity, decryption


def _small_set(tmp: Path) -> tuple[Path, dict]:
    src = tmp / "archive.bin"
    src.write_bytes(os.urandom(5000))
    out = tmp / "set"
    m = volumes.write_volume_set(src, out, "pw", volume_size=2048, chunk_size=1024)
    return out, m


@posix_only
@pytest.mark.parametrize("kind", KINDS)
def test_a_volume_swapped_for_a_pipe_or_a_link_is_reported_bad_not_read(tmp_path, kind):
    out, m = _small_set(tmp_path)
    victim = m["volumes"][0]["name"]
    real = (out / victim).read_bytes()
    (out / victim).unlink()
    _plant(out / victim, kind)
    if kind == "link":  # the link's target holds the volume's exact bytes: only the refusal can make it bad
        (out.parent / ("outside-" + victim)).write_bytes(real)
    status = _within(10, lambda: volumes.verify_volume_set(out))
    assert victim in status["bad"] and not status["ok"]
    with pytest.raises(volumes.VolumeError):
        _within(10, lambda: volumes.read_volume_set(out, "pw", tmp_path / "restored.bin"))


@pytest.mark.parametrize("name", ["../outside.ooenc", "sub/x.ooenc", "..", 7])
def test_a_volume_name_that_is_a_path_is_bad_and_never_read(tmp_path, name, monkeypatch):
    out, m = _small_set(tmp_path)
    (tmp_path / "outside.ooenc").write_bytes((out / m["volumes"][0]["name"]).read_bytes())
    m["volumes"][0]["name"] = name
    (out / "volumes.json").write_text(json.dumps(m), encoding="utf-8")
    hashed: list = []
    real = volumes._sha256_file
    monkeypatch.setattr(volumes, "_sha256_file", lambda p: hashed.append(p) or real(p))
    status = volumes.verify_volume_set(out)
    assert str(name) in status["bad"] and not status["ok"]
    assert all(Path(p).parent == out for p in hashed)  # nothing outside the folder was hashed


def test_parity_recovery_never_reads_a_parity_name_that_is_a_path(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    from src.backup import parity

    out, _ = _small_set(tmp_path)
    parity.write_parity(out, parity_count=1)
    m = volumes.load_manifest(out)
    data0 = m["volumes"][0]["name"]
    good = (out / data0).read_bytes()
    pv = m["parity"]["volumes"][0]
    (tmp_path / "elsewhere.oopar").write_bytes((out / pv["name"]).read_bytes())
    pv["name"] = "../elsewhere.oopar"
    (out / data0).write_bytes(b"damaged")
    read: list = []
    real = parity._read_band
    monkeypatch.setattr(parity, "_read_band", lambda p, o, n: read.append(p) or real(p, o, n))
    assert parity.recover_volumes(m, [data0], out_dir=out) == [data0]
    assert all(Path(p).parent == out for p in read) and (out / data0).read_bytes() != good


def test_a_sound_set_still_verifies_and_restores(tmp_path):
    out, _ = _small_set(tmp_path)
    assert volumes.verify_volume_set(out)["ok"] is True
    volumes.read_volume_set(out, "pw", tmp_path / "restored.bin")
    assert (tmp_path / "restored.bin").read_bytes() == (tmp_path / "archive.bin").read_bytes()


@posix_only
@pytest.mark.parametrize("kind", ["fifo", "zero"])
def test_decryption_refuses_a_pipe_or_a_device(tmp_path, kind):
    (tmp_path / "d").mkdir()
    p = tmp_path / "d" / "v.ooenc"
    _plant(p, kind)
    with pytest.raises(EncryptionError):
        _within(5, lambda: decrypt_stream(p, lambda b: None, "pw"))
    with pytest.raises(EncryptionError):
        _within(5, lambda: stream_key_opens(p, "pw"))


def test_decryption_of_a_real_file_is_unchanged(tmp_path):
    (tmp_path / "plain").write_bytes(b"hello" * 1000)
    encrypt_file(tmp_path / "plain", tmp_path / "sealed", "pw")
    got = bytearray()
    decrypt_stream(tmp_path / "sealed", got.extend, "pw")
    assert bytes(got) == b"hello" * 1000 and stream_key_opens(tmp_path / "sealed", "pw") is True


@posix_only
@pytest.mark.parametrize("kind", ["fifo", "zero"])
def test_parity_reads_a_planted_name_as_absent(tmp_path, kind):
    pytest.importorskip("numpy")
    from src.backup import parity

    (tmp_path / "d").mkdir()
    p = tmp_path / "d" / "par-00001.oopar"
    _plant(p, kind)
    band = _within(5, lambda: parity._read_band(p, 0, 16))
    assert bytes(band) == b"\0" * 16


@posix_only
def test_parity_recovery_with_a_planted_parity_volume_neither_blocks_nor_installs_a_wrong_rebuild(tmp_path):
    pytest.importorskip("numpy")
    from src.backup import parity

    out, _ = _small_set(tmp_path)
    parity.write_parity(out, parity_count=1)
    m = volumes.load_manifest(out)
    data0 = m["volumes"][0]["name"]
    (out / data0).write_bytes(b"damaged")
    pv = m["parity"]["volumes"][0]["name"]
    (out / pv).unlink()
    os.mkfifo(out / pv)
    left = _within(10, lambda: parity.recover_volumes(m, [data0], out_dir=out))
    assert left == [data0]  # the parity was refused, so nothing could be rebuilt; the damage stays named
    assert (out / data0).read_bytes() == b"damaged"


@posix_only
@pytest.mark.parametrize("kind", KINDS)
def test_the_folder_backup_hash_refuses_a_pipe_or_a_device(tmp_path, kind):
    from src.backup import folder_backup

    (tmp_path / "d").mkdir()
    p = tmp_path / "d" / "blob"
    _plant(p, kind)
    with pytest.raises(NotARegularFile):
        _within(5, lambda: folder_backup._sha256_file(p))
    (tmp_path / "real").write_bytes(b"abc")
    assert folder_backup._sha256_file(tmp_path / "real") == hashlib.sha256(b"abc").hexdigest()


# --------------------------------------------------------------------------- source pins


@pytest.mark.parametrize(
    "module, fn, must",
    [
        ("src/backup/import_scan.py", "leftovers_in_handle", "read_manifest_json("),
        ("src/backup/import_scan.py", "leftover_plaintext", "read_manifest_json("),
        ("src/backup/import_scan.py", "_looks_like_source_csv", "open_regular("),
        ("src/backup/volumes.py", "_sha256_file", "open_regular("),
        ("src/backup/volumes.py", "verify_volume_set", "_digest_matches("),
        ("src/backup/parity.py", "_read_band", "open_regular("),
        ("src/backup/parity.py", "recover_volumes", "_digest_matches("),
        ("src/backup/folder_backup.py", "_sha256_file", "open_regular("),
        ("src/backup/stream_backup.py", "verify_stream_backup", "_digest_matches("),
        ("src/safety/crypto.py", "decrypt_stream", "_open_sealed("),
        ("src/safety/crypto.py", "stream_key_opens", "_open_sealed("),
    ],
)
def test_no_plain_read_remains_at_a_swept_site(module, fn, must):
    body = python_function_source(Path(module).read_text(encoding="utf-8"), fn)
    assert must in body, (module, fn)
    for plain in (".read_text(", ".read_bytes(", "open(path, \"rb\")", "open(src, \"rb\")", "p.open(", "json.load("):
        assert plain not in body, (module, fn, plain)


def test_the_opener_module_stays_import_light():
    """The import scan is crypto-free and imports this; so does the crypto layer."""
    src = Path(regular_file.__file__).read_text(encoding="utf-8")
    imports = [ln for ln in src.splitlines() if ln.startswith(("import ", "from "))]
    assert all(ln.split()[1].split(".")[0] in {"__future__", "os", "stat", "typing"} for ln in imports), imports
