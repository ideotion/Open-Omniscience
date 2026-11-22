"""Row 329: a restore never follows a volume swapped for a link after its check, and reads only the file it checked.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The restore checks every volume's name (not a link, not the same file as another) and its checksum before it reads
anything, then decrypts each volume by name much later -- on a large set, hours later. The decrypt opened through
``open_regular(follow_links=True)``, so a volume swapped for a link in that window was followed out of the chosen
folder, and one replaced by another file was read in its place. Now the open refuses a link, and the bytes decrypted
are hashed on the way and must be the manifest's: a volume swapped, rebuilt or rewritten since the checksum pass is
refused whatever its inode number (FAT and network drives change those between opens). Each test swaps a volume in
exactly that window for something that would decrypt cleanly under the same key, so only the refusal makes the
restore fail. A refusal is never reported as a wrong passphrase.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

import src.backup.stream_backup as sb
import src.backup.volumes as vol
from src.backup.stream_backup import (
    CorpusSource,
    MemberFile,
    _no_freeze,
    read_stream_backup,
    write_stream_backup,
)
from src.backup.volumes import read_volume_set, write_volume_set
from src.safety.crypto import (
    EncryptionError,
    decrypt_file,
    decrypt_stream,
    encrypt_file,
    stream_key_opens,
    stream_key_opens_or_digest,
)

posix_only = pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
VOL = 65536


def _stream_set(tmp: Path) -> Path:
    corpus = tmp / "corpus.db"
    con = sqlite3.connect(corpus)
    con.executescript("CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
                      "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);")
    con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", [(f"h{i:05d}", "x" * 3000) for i in range(200)])
    con.commit()
    con.close()
    a = tmp / "app_settings.json"
    a.write_text('{"k": 1}', encoding="utf-8")
    dest = tmp / "dest"
    write_stream_backup(dest, "pw", corpus_source=CorpusSource(path=corpus, member_name="corpus.db", encrypted=False,
                                                              freeze=_no_freeze),
                        side_members=[MemberFile("app_settings.json", "state", a)], volume_size=VOL, parity_fraction=0.0)
    for p in dest.glob("*.oopar"):
        p.unlink()
    return dest


def _swap_after(module, name: str, swap) -> None:
    """Run ``swap`` right after ``module.name`` returns: the window between the restore's checks and its reads."""
    real = getattr(module, name)

    def _wrapped(*a, **k):
        out = real(*a, **k)
        swap()
        return out

    return _wrapped


def _to_link(volume: Path, outside: Path) -> None:
    shutil.copy(volume, outside)  # byte-identical: a read that followed the link would decrypt cleanly
    volume.unlink()
    os.symlink(outside, volume)


def _to_copy(volume: Path, source: Path | None = None) -> None:
    tmp = volume.with_name(volume.name + ".other")
    shutil.copy(source or volume, tmp)  # another file: the same bytes, or another volume's sealed with the same key
    os.replace(tmp, volume)


@posix_only
def test_a_stream_volume_swapped_for_a_link_after_the_checks_is_refused(tmp_path, monkeypatch):
    dest = _stream_set(tmp_path)
    victim = sorted(dest.glob("vol-*.ooenc"))[1]
    outside = tmp_path / "outside.ooenc"
    monkeypatch.setattr(sb, "verify_volume_set", _swap_after(sb, "verify_volume_set", lambda: _to_link(victim, outside)))
    with pytest.raises(EncryptionError) as exc:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert "wrong passphrase" not in str(exc.value)
    assert "this file was not read" in str(exc.value)


def test_a_stream_volume_replaced_by_another_volume_after_the_checks_is_refused(tmp_path, monkeypatch):
    dest = _stream_set(tmp_path)
    vols = sorted(dest.glob("vol-*.ooenc"))
    victim, other = vols[1], vols[2]
    monkeypatch.setattr(sb, "verify_volume_set", _swap_after(sb, "verify_volume_set", lambda: _to_copy(victim, other)))
    with pytest.raises(EncryptionError) as exc:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert "not the one that was checked" in str(exc.value)
    assert "wrong passphrase" not in str(exc.value)
    assert not (tmp_path / "st").exists() or not any((tmp_path / "st").iterdir())


def test_a_volume_whose_file_changed_but_whose_bytes_did_not_still_restores(tmp_path, monkeypatch):
    """A FAT or network drive may give one untouched file a new inode number between two opens: the check is on the
    bytes, so a byte-identical file at the name is read and the restore completes."""
    dest = _stream_set(tmp_path)
    victim = sorted(dest.glob("vol-*.ooenc"))[1]
    monkeypatch.setattr(sb, "verify_volume_set", _swap_after(sb, "verify_volume_set", lambda: _to_copy(victim)))
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.hash_failures == []


def test_an_untouched_stream_set_still_restores(tmp_path):
    dest = _stream_set(tmp_path)
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.hash_failures == []


def test_the_stream_verify_refuses_a_volume_swapped_after_its_checksum(tmp_path, monkeypatch):
    dest = _stream_set(tmp_path)
    vols = sorted(dest.glob("vol-*.ooenc"))
    monkeypatch.setattr(sb, "verify_volume_set", _swap_after(sb, "verify_volume_set", lambda: _to_copy(vols[1], vols[2])))
    report = sb.verify_stream_backup(dest, passphrase="pw")
    assert report["ok"] is False
    assert not any("wrong passphrase" in str(pr) for pr in report["problems"])


@posix_only
def test_the_wrong_key_probe_gives_no_verdict_on_a_link_swapped_in_after_its_look(tmp_path, monkeypatch):
    """The probe's open refuses the link, and a refusal is no verdict: never "wrong passphrase"."""
    dest = _stream_set(tmp_path)
    m = vol.load_manifest(dest)
    first = next(v for mm in m["members"] for v in mm["volumes"])
    victim = dest / first
    outside = tmp_path / "outside.ooenc"
    raised: list[BaseException] = []
    real = sb.stream_key_opens_or_digest

    def _swap_then_open(p, pw, **kw):
        _to_link(victim, outside)
        try:
            return real(p, pw, **kw)
        except BaseException as e:
            raised.append(e)
            raise

    monkeypatch.setattr(sb, "stream_key_opens_or_digest", _swap_then_open)
    assert sb.backup_passphrase_is_wrong(dest, "not-the-passphrase") is False
    assert len(raised) == 1 and isinstance(raised[0], EncryptionError)


def test_the_right_passphrase_never_reads_as_wrong_when_the_first_volume_is_swapped_for_the_key_check(tmp_path, monkeypatch):
    """The key check and the checksum are one read: a volume sealed with another key, put in place only while the key
    is tried and taken away again, gives no verdict instead of "wrong passphrase"."""
    dest = _stream_set(tmp_path)
    m = vol.load_manifest(dest)
    victim = dest / next(v for mm in m["members"] for v in mm["volumes"])
    kept_aside = tmp_path / "kept_aside"
    plain = tmp_path / "q.bin"
    plain.write_bytes(b"q" * 1000)
    other = tmp_path / "other.ooenc"
    encrypt_file(plain, other, "someone-else")
    real = sb.stream_key_opens_or_digest

    def _swap_for_the_key_check(p, pw, **kw):
        os.replace(victim, kept_aside)
        shutil.copy(other, victim)
        try:
            return real(p, pw, **kw)
        finally:
            os.replace(kept_aside, victim)

    monkeypatch.setattr(sb, "stream_key_opens_or_digest", _swap_for_the_key_check)
    assert sb.backup_passphrase_is_wrong(dest, "pw") is False


def test_the_probe_still_says_wrong_for_an_intact_set_and_a_wrong_passphrase(tmp_path):
    dest = _stream_set(tmp_path)
    assert sb.backup_passphrase_is_wrong(dest, "not-the-passphrase") is True
    assert sb.backup_passphrase_is_wrong(dest, "pw") is False


@posix_only
def test_a_legacy_volume_swapped_for_a_link_after_the_checks_is_refused(tmp_path, monkeypatch):
    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(5000))
    out = tmp_path / "set"
    write_volume_set(src, out, "pw", volume_size=2048)
    victim = sorted(out.glob("*.ooenc"))[1]
    outside = tmp_path / "outside.ooenc"
    monkeypatch.setattr(vol, "verify_volume_set", _swap_after(vol, "verify_volume_set", lambda: _to_link(victim, outside)))
    with pytest.raises(EncryptionError) as exc:
        read_volume_set(out, "pw", tmp_path / "restored.bin")
    assert "wrong passphrase" not in str(exc.value)
    assert not (tmp_path / "restored.bin").exists()


def test_a_legacy_volume_replaced_by_another_after_the_checks_is_refused(tmp_path, monkeypatch):
    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(5000))
    out = tmp_path / "set"
    write_volume_set(src, out, "pw", volume_size=2048)
    vols = sorted(out.glob("*.ooenc"))
    monkeypatch.setattr(vol, "verify_volume_set", _swap_after(vol, "verify_volume_set", lambda: _to_copy(vols[1], vols[0])))
    with pytest.raises(EncryptionError) as exc:
        read_volume_set(out, "pw", tmp_path / "restored.bin")
    assert "not the one that was checked" in str(exc.value)
    assert not (tmp_path / "restored.bin").exists()
    assert not list(tmp_path.glob(".*.plain"))


def test_an_untouched_legacy_set_still_restores(tmp_path):
    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(5000))
    out = tmp_path / "set"
    write_volume_set(src, out, "pw", volume_size=2048)
    read_volume_set(out, "pw", tmp_path / "restored.bin")
    assert (tmp_path / "restored.bin").read_bytes() == src.read_bytes()


@posix_only
def test_the_apps_own_sealed_file_behind_a_link_still_opens(tmp_path):
    """The default is unchanged: a sealed file of the app's own (its data folder may be a link) opens through one."""
    plain = tmp_path / "p.bin"
    plain.write_bytes(b"y" * 3000)
    real = tmp_path / "real" / "s.ooenc"
    real.parent.mkdir()
    encrypt_file(plain, real, "pw")
    link = tmp_path / "s.ooenc"
    os.symlink(real, link)
    assert stream_key_opens(link, "pw") is True
    decrypt_file(link, tmp_path / "back.bin", "pw")
    assert (tmp_path / "back.bin").read_bytes() == plain.read_bytes()
    with pytest.raises(EncryptionError):
        stream_key_opens(link, "pw", follow_links=False)  # a backup reader's open refuses the same link


def test_a_file_rewritten_in_place_while_it_is_decrypted_is_refused(tmp_path):
    """The digest is taken over the bytes the decrypt read: a change made through the same file while it is read (one
    whose chunks still decrypt, as another sealing of the same plaintext would) makes what was read unusable."""
    plain = tmp_path / "p.bin"
    plain.write_bytes(os.urandom(300_000))
    sealed = tmp_path / "s.ooenc"
    encrypt_file(plain, sealed, "pw")
    want = hashlib.sha256(sealed.read_bytes()).hexdigest()
    assert decrypt_stream(sealed, lambda b: None, "pw", follow_links=False, expect_sha256=want) == 300_000
    with pytest.raises(EncryptionError) as exc:
        decrypt_stream(sealed, lambda b: None, "pw", follow_links=False, expect_sha256="0" * 64)
    assert "not the one that was checked" in str(exc.value)
    assert "wrong passphrase" not in str(exc.value)
    with pytest.raises(EncryptionError):
        decrypt_stream(sealed, lambda b: None, "pw", follow_links=False, expect_sha256="")  # a manifest gave none


def test_a_volume_parity_rebuilt_then_replaced_is_refused(tmp_path, monkeypatch):
    """A volume parity rebuilt is read like any other: only bytes whose checksum is the manifest's."""
    pytest.importorskip("numpy")
    import src.backup.parity as parity

    corpus = tmp_path / "corpus.db"
    con = sqlite3.connect(corpus)
    con.executescript("CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
                      "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);")
    con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", [(f"h{i:05d}", os.urandom(1500).hex()) for i in range(200)])
    con.commit()
    con.close()
    a = tmp_path / "a.json"
    a.write_text("{}", encoding="utf-8")
    dest = tmp_path / "dest"
    write_stream_backup(dest, "pw", corpus_source=CorpusSource(path=corpus, member_name="corpus.db", encrypted=False,
                                                              freeze=_no_freeze),
                        side_members=[MemberFile("app_settings.json", "state", a)], volume_size=VOL, parity_fraction=0.5)
    vols = sorted(dest.glob("vol-*.ooenc"))
    victim, other = vols[1], vols[2]
    damaged = bytearray(victim.read_bytes())
    damaged[100] ^= 1
    victim.write_bytes(bytes(damaged))
    real = parity.recover_volumes

    def _rebuild_then_replace(*a, **k):
        out = real(*a, **k)
        _to_copy(victim, other)
        return out

    monkeypatch.setattr(parity, "recover_volumes", _rebuild_then_replace)
    with pytest.raises(EncryptionError) as exc:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert "not the one that was checked" in str(exc.value)
    assert "wrong passphrase" not in str(exc.value)


def test_the_probe_gives_no_verdict_when_the_file_grows_back_after_its_end_was_seen(tmp_path, monkeypatch):
    """A volume cut to its first chunk while the key is tried (so that chunk is taken as the last one and fails its tag
    under the right passphrase) and grown back before the checksum would hash as the genuine file: the probe sees
    bytes after the end it saw and gives no verdict, so the right passphrase never reads as wrong."""
    import src.safety.crypto as crypto

    plain = tmp_path / "p.bin"
    sealed = tmp_path / "s.ooenc"
    real = crypto._open_stream_header
    seen: dict[str, int] = {}

    def _end_seen_after_the_first_chunk(fin, passphrase):
        out = real(fin, passphrase)
        seen["block"] = out[2]
        inner_read, calls = fin.read, []

        def _read(n=-1):
            calls.append(n)
            return b"" if len(calls) == 2 else inner_read(n)  # read(1) sees an end, as a cut file would show it

        fin.read = _read
        return out

    plain.write_bytes(b"\0")
    encrypt_file(plain, sealed, "pw")
    with open(sealed, "rb") as fh:
        block = real(fh, "pw")[2]
    plain.write_bytes(os.urandom(block + 7))  # two chunks
    encrypt_file(plain, tmp_path / "two.ooenc", "pw")
    assert crypto.stream_key_opens_or_digest(tmp_path / "two.ooenc", "pw", follow_links=False) == (True, None)
    monkeypatch.setattr(crypto, "_open_stream_header", _end_seen_after_the_first_chunk)
    with pytest.raises(EncryptionError) as exc:
        crypto.stream_key_opens_or_digest(tmp_path / "two.ooenc", "pw", follow_links=False)
    assert "no verdict" in str(exc.value)


def test_a_volume_altered_after_the_checks_never_reads_as_a_wrong_passphrase(tmp_path, monkeypatch):
    """A volume changed after the checksum pass fails a chunk's tag before the digest is known: the rest is hashed and
    the refusal says the file is not the one checked, never that the passphrase may be wrong."""
    dest = _stream_set(tmp_path)
    victim = sorted(dest.glob("vol-*.ooenc"))[1]

    def _flip():
        b = bytearray(victim.read_bytes())
        b[200] ^= 1
        victim.write_bytes(bytes(b))

    monkeypatch.setattr(sb, "verify_volume_set", _swap_after(sb, "verify_volume_set", _flip))
    with pytest.raises(EncryptionError) as exc:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert "not the one that was checked" in str(exc.value)
    assert "passphrase" not in str(exc.value)


@posix_only
def test_a_link_put_at_the_name_between_the_look_and_the_open_is_an_encryption_refusal(tmp_path, monkeypatch):
    """The open's own refusal of a link (ELOOP) is the same refusal as the look's, so a verify records it."""
    import src.backup.regular_file as rf
    import src.safety.crypto as crypto

    sealed = tmp_path / "s.ooenc"
    plain = tmp_path / "p.bin"
    plain.write_bytes(b"k" * 100)
    encrypt_file(plain, tmp_path / "real.ooenc", "pw")
    os.symlink(tmp_path / "real.ooenc", sealed)

    def _eloop(path, *, follow_links=False, dir_fd=None):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", str(path))

    monkeypatch.setattr(crypto, "open_regular", _eloop)
    with pytest.raises(EncryptionError):
        stream_key_opens(sealed, "pw", follow_links=False)
    del rf


def test_a_chunk_cut_short_and_grown_back_during_the_decrypt_never_reads_as_a_wrong_passphrase(tmp_path, monkeypatch):
    """A read that returns half a chunk saw the end of the file there; bytes after it mean the file changed while it
    was read, and that is what the refusal says, even when every byte read still hashes to the manifest's digest."""
    import src.safety.crypto as crypto

    plain = tmp_path / "p.bin"
    plain.write_bytes(b"\0")
    sealed = tmp_path / "one.ooenc"
    encrypt_file(plain, sealed, "pw")
    with open(sealed, "rb") as fh:
        block = crypto._open_stream_header(fh, "pw")[2]
    plain.write_bytes(os.urandom(2 * block + 9))
    sealed = tmp_path / "three.ooenc"
    encrypt_file(plain, sealed, "pw")
    want = hashlib.sha256(sealed.read_bytes()).hexdigest()
    real = crypto._open_stream_header

    def _half_then_rest(fin, passphrase):
        out = real(fin, passphrase)
        inner_read, calls, carry = fin.read, [], []

        def _read(n=-1):
            calls.append(n)
            if len(calls) == 1:
                b = inner_read(n)
                carry.append(b[len(b) // 2:])
                return b[: len(b) // 2]  # the end seen mid-chunk
            if carry:
                head = carry.pop()
                return head + inner_read(n - len(head))  # grown back: the rest, read on from where the end was seen
            return inner_read(n)

        fin.read = _read
        return out

    monkeypatch.setattr(crypto, "_open_stream_header", _half_then_rest)
    with pytest.raises(EncryptionError) as exc:
        decrypt_stream(sealed, lambda b: None, "pw", follow_links=False, expect_sha256=want)
    assert "passphrase" not in str(exc.value)


def test_a_volume_swapped_for_a_longer_one_is_refused_at_the_checked_size(tmp_path, monkeypatch):
    """A volume swapped after the checks for its own header and a huge tail cannot hold the restore reading: the read
    stops one byte past the size the manifest gives it."""
    dest = _stream_set(tmp_path)
    victim = sorted(dest.glob("vol-*.ooenc"))[1]
    reads: list[int] = []

    def _grow():
        size = victim.stat().st_size
        with open(victim, "r+b") as f:
            f.truncate(size + 64 * 1024 * 1024)  # sparse: cheap to make, slow to read

    monkeypatch.setattr(sb, "verify_volume_set", _swap_after(sb, "verify_volume_set", _grow))
    import src.safety.crypto as crypto

    real_read = crypto._HashedReads.read

    def _count(self, n=-1):
        b = real_read(self, n)
        reads.append(len(b))
        return b

    monkeypatch.setattr(crypto._HashedReads, "read", _count)
    with pytest.raises(EncryptionError) as exc:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert "not the one that was checked" in str(exc.value)
    assert sum(reads) < 16 * 1024 * 1024  # stopped at the checked size, never read the 64 MiB tail


def test_the_probe_stops_at_the_size_the_manifest_gives(tmp_path):
    plain = tmp_path / "p.bin"
    plain.write_bytes(b"s" * 5000)
    sealed = tmp_path / "s.ooenc"
    encrypt_file(plain, sealed, "pw")
    size = sealed.stat().st_size
    assert stream_key_opens_or_digest(sealed, "pw", follow_links=False, max_bytes=size) == (True, None)
    with pytest.raises(EncryptionError):
        stream_key_opens_or_digest(sealed, "wrong", follow_links=False, max_bytes=size - 1)
    opens, digest = stream_key_opens_or_digest(sealed, "wrong", follow_links=False, max_bytes=size)
    assert opens is False and digest == hashlib.sha256(sealed.read_bytes()).hexdigest()
