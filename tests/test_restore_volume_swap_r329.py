"""Row 329: a restore never follows a volume swapped for a link after its check, and reads only the file it checked.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The restore checks every volume's name (not a link, not the same file as another) and its checksum before it reads
anything, then decrypts each volume by name much later -- on a large set, hours later. The decrypt opened through
``open_regular(follow_links=True)``, so a volume swapped for a link in that window was followed out of the chosen
folder, and one replaced by another file was read in its place. Each test swaps a volume in exactly that window,
for a link to (or a copy of) a byte-identical volume, so a read that followed it would decrypt cleanly: only the
refusal makes the restore fail. A refusal is never reported as a wrong passphrase.
"""

from __future__ import annotations

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
from src.safety import crypto
from src.safety.crypto import EncryptionError, decrypt_file, encrypt_file, stream_key_opens

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


def _to_copy(volume: Path) -> None:
    tmp = volume.with_name(volume.name + ".other")
    shutil.copy(volume, tmp)  # the same bytes, another file
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
    assert "nothing was read" in str(exc.value)


def test_a_stream_volume_replaced_by_another_file_after_the_checks_is_refused(tmp_path, monkeypatch):
    dest = _stream_set(tmp_path)
    victim = sorted(dest.glob("vol-*.ooenc"))[1]
    if not os.stat(victim).st_ino:
        pytest.skip("this file system reports no file identity")
    monkeypatch.setattr(sb, "verify_volume_set", _swap_after(sb, "verify_volume_set", lambda: _to_copy(victim)))
    with pytest.raises(EncryptionError) as exc:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert "no longer the one that was checked" in str(exc.value)
    assert "wrong passphrase" not in str(exc.value)


def test_an_untouched_stream_set_still_restores(tmp_path):
    dest = _stream_set(tmp_path)
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.hash_failures == []


@posix_only
def test_the_wrong_key_probe_gives_no_verdict_on_a_link_swapped_in_after_its_look(tmp_path, monkeypatch):
    """The probe's open refuses the link, and a refusal is no verdict: never "wrong passphrase"."""
    dest = _stream_set(tmp_path)
    m = vol.load_manifest(dest)
    first = next(v for mm in m["members"] for v in mm["volumes"])
    victim = dest / first
    outside = tmp_path / "outside.ooenc"
    raised: list[BaseException] = []
    real = sb.stream_key_opens

    def _swap_then_open(p, pw, **kw):
        _to_link(victim, outside)
        try:
            return real(p, pw, **kw)
        except BaseException as e:
            raised.append(e)
            raise

    monkeypatch.setattr(sb, "stream_key_opens", _swap_then_open)
    assert sb.backup_passphrase_is_wrong(dest, "not-the-passphrase") is False
    assert len(raised) == 1 and isinstance(raised[0], EncryptionError)


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


def test_a_volume_whose_identity_still_matches_by_name_is_read(tmp_path, monkeypatch):
    """Windows can report one file's identity at different widths through lstat and fstat: a second look by name
    that matches the recorded identity accepts the file, so a sound backup is never refused for it."""
    plain = tmp_path / "p.bin"
    plain.write_bytes(b"z" * 3000)
    sealed = tmp_path / "s.ooenc"
    encrypt_file(plain, sealed, "pw")
    st = os.stat(sealed)

    class _WideFstat:  # the module's own view of os (R351)
        def __getattr__(self, name):
            return getattr(os, name)

        @staticmethod
        def fstat(fd):
            r = os.fstat(fd)
            return os.stat_result((r.st_mode, r.st_ino + (1 << 40), *tuple(r)[2:]))

    monkeypatch.setattr(crypto, "os", _WideFstat())
    assert stream_key_opens(sealed, "pw", follow_links=False, identity=(st.st_dev, st.st_ino)) is True
