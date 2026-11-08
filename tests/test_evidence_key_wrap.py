"""The Ed25519 evidence key is wrapped under the held passphrase (E3 / A-009 / v0.6 row C2, R442).

Before: ``load_or_create_signing_key`` wrote the key as PKCS8 PEM with ``NoEncryption`` whatever the store's
passphrase state, by ``write_bytes`` then ``chmod`` (a window at mode 0644 under a umask of 022), with no
``O_EXCL`` (two first callers could each write a key and the last one won).

After: on a store with a passphrase held the file is wrapped (the custody key's rule, one helper), created
``O_EXCL`` at 0600; a legacy plaintext key is wrapped IN PLACE and never changes; a wrapped key that cannot be
opened raises ``EvidenceKeyError`` naming which cause and is never regenerated or overwritten; the review's
readers read with the held passphrase and never write.

The negative space carries the weight: the passphrase is in no file name, log line or error text, a failed
migration leaves the original bytes, a locked app signs nothing, a review creates and changes nothing.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
import threading
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.custody import keyfile as kf
from src.reporting import evidence as ev
from tests.os_scope import scope_os

PASS = "marker-passphrase-4f1c9e"
OTHER = "marker-other-passphrase-77b2d0"
MESSAGE = b"a fixed message to sign"

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")


@pytest.fixture(autouse=True)
def _no_passphrase_unless_a_test_holds_one(monkeypatch):
    """Every test starts with NO passphrase held anywhere; a test that wants one sets it."""
    from src.database import connect

    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(connect, "_passphrase", None)


def _hold(monkeypatch, passphrase: str) -> None:
    monkeypatch.setenv("OO_KEY_PASSPHRASE", passphrase)


def _plain_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _seed(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )


def _wrapped(key: Ed25519PrivateKey, passphrase: str) -> bytes:
    """What a key wrapped under ``passphrase`` looks like, built here from the custody signer's own wrap
    (salt || nonce || AES-256-GCM under a scrypt key), not through the code under test."""
    from src.custody import signing

    return signing._wrap(_seed(key), passphrase.encode())


def _is_wrapped(path: Path) -> bool:
    """A wrapped key file is not a PEM at all, and holds neither the key bytes nor the passphrase."""
    raw = path.read_bytes()
    return not raw.lstrip().startswith(b"-----BEGIN") and len(raw) == 16 + 12 + 32 + 16


def _opens_with(path: Path, passphrase: str | None) -> Ed25519PrivateKey:
    from src.custody import signing

    raw = path.read_bytes()
    if raw.lstrip().startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(raw, password=None)
        assert isinstance(key, Ed25519PrivateKey)
        return key
    assert passphrase is not None
    return Ed25519PrivateKey.from_private_bytes(signing._unwrap(raw, passphrase.encode()))


def _files(directory: Path) -> list[str]:
    """The FILES directly in ``directory``: what a backup's ``keys/`` listing takes."""
    return sorted(f.name for f in directory.iterdir() if f.is_file())


def _pending_left(directory: Path) -> list[str]:
    pending = directory / kf.PENDING
    return sorted(f.name for f in pending.iterdir()) if pending.is_dir() else []


# --------------------------------------------------------------------------- #
#  A new key
# --------------------------------------------------------------------------- #


def test_a_new_key_is_wrapped_when_a_passphrase_is_held(tmp_path, monkeypatch):
    _hold(monkeypatch, PASS)
    p = tmp_path / "keys" / "k.pem"
    key = ev.load_or_create_signing_key(p)
    raw = p.read_bytes()
    assert _is_wrapped(p)
    assert PASS.encode() not in raw
    assert _seed(key) not in raw
    assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(key)


def test_the_held_database_passphrase_wraps_it_and_the_environment_one_wins(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", PASS)
    held = tmp_path / "held.pem"
    ev.load_or_create_signing_key(held)
    _opens_with(held, PASS)
    # OO_KEY_PASSPHRASE wins over the held one: the custody signer's rule, one helper for both
    _hold(monkeypatch, OTHER)
    env = tmp_path / "env.pem"
    ev.load_or_create_signing_key(env)
    _opens_with(env, OTHER)
    with pytest.raises(InvalidTag):
        _opens_with(env, PASS)


def test_no_passphrase_held_writes_the_plaintext_key_it_always_wrote(tmp_path):
    p = tmp_path / "k.pem"
    key = ev.load_or_create_signing_key(p)
    assert p.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")
    assert ev.public_key_hex(_opens_with(p, None)) == ev.public_key_hex(key)
    assert ev.public_key_hex(ev.load_or_create_signing_key(p)) == ev.public_key_hex(key)


def test_a_wrapped_key_loads_again_under_the_same_passphrase_and_signs_the_same(
    tmp_path, monkeypatch
):
    _hold(monkeypatch, PASS)
    p = tmp_path / "k.pem"
    first = ev.load_or_create_signing_key(p)
    again = ev.load_or_create_signing_key(p)
    assert ev.public_key_hex(again) == ev.public_key_hex(first)
    assert first.sign(MESSAGE) == again.sign(MESSAGE)  # Ed25519 is deterministic: the same key


def test_the_wrap_is_priced_by_scrypt_not_by_pkcs8s_2048_rounds(tmp_path, monkeypatch):
    """PKCS8's BestAvailableEncryption is PBKDF2-HMAC-SHA256 at 2048 rounds: 0.3 ms a guess, so the key file
    would be the cheapest oracle for the database passphrase (SQLCipher: 170 ms). The wrap is the custody
    signer's scrypt one; this pins its cost parameter and that nothing else derives the key."""
    from src.custody import signing

    real = signing.Scrypt
    calls: list[dict] = []

    def spy(**kw):
        calls.append(kw)
        return real(**kw)

    monkeypatch.setattr(signing, "Scrypt", spy)
    _hold(monkeypatch, PASS)
    p = tmp_path / "k.pem"
    ev.load_or_create_signing_key(p)
    assert calls and all(c["n"] >= 2**15 for c in calls), calls
    assert not p.read_bytes().lstrip().startswith(b"-----BEGIN"), (
        "a PKCS8 PEM would be the weak form"
    )


def test_a_very_long_passphrase_wraps_and_loads(tmp_path, monkeypatch):
    """PKCS8 refuses a password over 1023 bytes, which would have broken every export and backup."""
    long_pass = "p" * 3000
    _hold(monkeypatch, long_pass)
    p = tmp_path / "k.pem"
    key = ev.load_or_create_signing_key(p)
    assert ev.public_key_hex(ev.load_or_create_signing_key(p)) == ev.public_key_hex(key)
    assert ev.public_key_hex(_opens_with(p, long_pass)) == ev.public_key_hex(key)


@posix_only
def test_the_key_is_created_0600_from_its_first_byte_under_a_permissive_umask(
    tmp_path, monkeypatch
):
    """The old write_bytes + chmod left a moment at 0644 under umask 022. The mode is now part of the creation,
    so the test asks the creation (the ``os.open`` call) and not only the file afterwards."""
    _hold(monkeypatch, PASS)
    seen: list[tuple[int, int]] = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **kw):
        if "k.pem" in str(path):
            seen.append((flags, mode))
        return real_open(path, flags, mode, *a, **kw)

    scope_os(monkeypatch, kf, open=spy)
    old = os.umask(0o022)
    try:
        ev.load_or_create_signing_key(tmp_path / "k.pem")
    finally:
        os.umask(old)
    assert len(seen) == 1
    flags, mode = seen[0]
    assert mode == 0o600
    assert flags & os.O_EXCL and flags & os.O_CREAT
    assert stat.S_IMODE((tmp_path / "k.pem").stat().st_mode) == 0o600


def test_two_first_callers_end_with_one_key_the_loser_loads_the_winners(tmp_path, monkeypatch):
    """The race the old code had: both generated, both wrote, the last write won while the first had already
    signed with the other key. Here the winner's file appears between the loser's look and its link."""
    winner = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    real_link = kf.os.link

    def racing(src, dst, *a, **kw):
        kf.write_new(Path(dst), _plain_pem(winner))  # the other caller got there first
        return real_link(src, dst, *a, **kw)  # ... so this link is refused with FileExistsError

    scope_os(monkeypatch, kf, link=racing)
    got = ev.load_or_create_signing_key(p)
    assert ev.public_key_hex(got) == ev.public_key_hex(winner)
    assert ev.public_key_hex(_opens_with(p, None)) == ev.public_key_hex(winner)
    assert _files(tmp_path) == ["k.pem"]
    assert _pending_left(tmp_path) == [], "the loser's private copy is gone"


def test_a_loser_that_holds_a_passphrase_wraps_a_plaintext_winners_key(tmp_path, monkeypatch):
    """The winner held no passphrase (a tool run) and made the key plaintext; the loser holds one. It loads that
    key, as before, and wraps it the way it would any plaintext key it found there, instead of returning early."""
    winner = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    real_link = kf.os.link

    def racing(src, dst, *a, **kw):
        kf.write_new(Path(dst), _plain_pem(winner))
        return real_link(src, dst, *a, **kw)

    scope_os(monkeypatch, kf, link=racing)
    _hold(monkeypatch, PASS)
    got = ev.load_or_create_signing_key(p)
    assert ev.public_key_hex(got) == ev.public_key_hex(winner)
    assert _is_wrapped(p)
    assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(winner)
    assert _pending_left(tmp_path) == []


@pytest.mark.parametrize("what", ["truncated", "public"])
def test_a_damaged_or_foreign_pem_is_named_not_left_as_a_bare_value_error(tmp_path, what):
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    if what == "truncated":
        data = _plain_pem(key)[:60]
    else:
        data = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    p.write_bytes(data)
    with pytest.raises(ev.EvidenceKeyError, match="not a readable PEM private key"):
        ev.load_or_create_signing_key(p)
    assert p.read_bytes() == data


@posix_only
def test_a_key_file_that_is_a_symbolic_link_is_never_replaced_and_is_reported_as_it_is(
    tmp_path, monkeypatch
):
    """``os.replace`` would swap the link for a regular file and leave the plaintext key at its target, while the
    wrap looked done."""
    key = Ed25519PrivateKey.generate()
    target = tmp_path / "elsewhere.pem"
    target.write_bytes(_plain_pem(key))
    keys = tmp_path / "keys"
    keys.mkdir()
    link = keys / "k.pem"
    link.symlink_to(target)
    _hold(monkeypatch, PASS)
    got = ev.load_or_create_signing_key(link)
    assert ev.public_key_hex(got) == ev.public_key_hex(key)
    assert link.is_symlink() and target.read_bytes() == _plain_pem(key)
    assert _pending_left(keys) == []


def test_a_key_appears_complete_or_not_at_all(tmp_path, monkeypatch):
    """The file is linked into place from a finished private copy, so a reader never meets it half written."""
    seen: list[bytes] = []
    real_link = kf.os.link

    def look(src, dst, *a, **kw):
        assert not Path(dst).exists()
        assert _files(tmp_path) == [], "a backup listing keys/ now would see a temporary file"
        out = real_link(src, dst, *a, **kw)
        seen.append(Path(dst).read_bytes())
        return out

    scope_os(monkeypatch, kf, link=look)
    key = ev.load_or_create_signing_key(tmp_path / "k.pem")
    assert seen and ev.public_key_hex(_opens_with(tmp_path / "k.pem", None)) == ev.public_key_hex(
        key
    )
    assert seen[0] == (tmp_path / "k.pem").read_bytes()


def test_a_file_system_without_hard_links_still_gets_its_key_created_exclusively(
    tmp_path, monkeypatch
):
    def no_links(src, dst, *a, **kw):
        raise PermissionError(1, "Operation not permitted")  # what FAT and exFAT answer

    scope_os(monkeypatch, kf, link=no_links)
    _hold(monkeypatch, PASS)
    p = tmp_path / "k.pem"
    key = ev.load_or_create_signing_key(p)
    assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(key)
    assert _files(tmp_path) == ["k.pem"] and _pending_left(tmp_path) == []
    # and the exclusive create still refuses a file that is there
    with pytest.raises(FileExistsError):
        kf.create_new(p, b"x")
    assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(key)


def test_a_reader_that_meets_an_empty_key_file_waits_for_the_write(tmp_path, monkeypatch):
    winner = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(b"")  # created, not yet written (the no-hard-link fallback)
    real_sleep = kf.time.sleep

    def fill(_seconds):
        p.write_bytes(_plain_pem(winner))
        monkeypatch.setattr(kf.time, "sleep", real_sleep)

    monkeypatch.setattr(kf.time, "sleep", fill)
    assert ev.public_key_hex(ev.load_or_create_signing_key(p)) == ev.public_key_hex(winner)


def test_a_key_file_that_stays_empty_is_named_as_a_cut_short_creation_and_left_alone(tmp_path):
    p = tmp_path / "k.pem"
    p.write_bytes(b"")
    with pytest.raises(ev.EvidenceKeyError, match="cut short"):
        ev.load_or_create_signing_key(p)
    assert p.read_bytes() == b"", "an empty file is not replaced by a new key"
    assert ev.signing_key_state(p) == ("unreadable", None)


def _create_at_once(p: Path, how_many: int = 8) -> tuple[list[str], list[BaseException]]:
    out: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(how_many)

    def go() -> None:
        try:
            barrier.wait()
            out.append(ev.public_key_hex(ev.load_or_create_signing_key(p)))
        except BaseException as exc:  # noqa: BLE001 - reported by the caller
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(how_many)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out, errors


def test_eight_threads_creating_at_once_all_hold_the_key_that_is_on_disk(tmp_path, monkeypatch):
    _hold(monkeypatch, PASS)
    for trial in range(10):
        p = tmp_path / f"t{trial}.pem"
        out, errors = _create_at_once(p)
        assert not errors, errors
        assert len(out) == 8 and len(set(out)) == 1, "two callers signed with different keys"
        assert ev.public_key_hex(_opens_with(p, PASS)) == out[0]
    assert all(f.endswith(".pem") for f in _files(tmp_path)), (
        "no private copy is left in the listing"
    )
    assert _pending_left(tmp_path) == [], "no private copy is left behind"


# --------------------------------------------------------------------------- #
#  A legacy plaintext key (ruling a: wrapped in place, the key never changes)
# --------------------------------------------------------------------------- #


def test_a_legacy_plaintext_key_is_wrapped_in_place_and_stays_the_same_key(tmp_path, monkeypatch):
    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(_plain_pem(legacy))
    before_sig = legacy.sign(MESSAGE)
    _hold(monkeypatch, PASS)
    key = ev.load_or_create_signing_key(p)
    assert ev.public_key_hex(key) == ev.public_key_hex(legacy)
    assert _is_wrapped(p)
    reopened = _opens_with(p, PASS)
    assert ev.public_key_hex(reopened) == ev.public_key_hex(legacy)
    # a signature made before the wrap still verifies against the key after it
    reopened.public_key().verify(before_sig, MESSAGE)
    assert _pending_left(tmp_path) == []
    if os.name != "nt":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_a_legacy_plaintext_key_stays_plaintext_while_no_passphrase_is_held(tmp_path):
    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    raw = _plain_pem(legacy)
    p.write_bytes(raw)
    ev.load_or_create_signing_key(p)
    assert p.read_bytes() == raw


@pytest.mark.parametrize("how", ["replace fails", "read-back is another key", "write fails"])
def test_a_failed_wrap_leaves_the_original_file_and_still_signs(tmp_path, monkeypatch, caplog, how):
    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    raw = _plain_pem(legacy)
    p.write_bytes(raw)
    _hold(monkeypatch, PASS)
    if how == "replace fails":

        def boom(src, dst):
            raise OSError(f"cannot replace, passphrase {PASS}")

        scope_os(monkeypatch, kf, replace=boom)
    elif how == "read-back is another key":
        other = Ed25519PrivateKey.generate()
        monkeypatch.setattr(ev, "_seal", lambda key, passphrase: _wrapped(other, PASS))
    else:
        real_write = kf.write_new

        def boom_write(path, data):
            real_write(path, b"half written")  # the private copy exists, then the disk fails
            raise OSError(f"disk full, passphrase {PASS}")

        monkeypatch.setattr(kf, "write_new", boom_write)
    with caplog.at_level(logging.DEBUG):
        key = ev.load_or_create_signing_key(p)
    assert ev.public_key_hex(key) == ev.public_key_hex(legacy), (
        "signing goes on with the key it holds"
    )
    assert p.read_bytes() == raw, "a failed wrap leaves the original exactly as it was"
    assert _pending_left(tmp_path) == [], "no half-written copy is left behind"
    # the log names the exception class and never its words (the passphrase is in scope there)
    assert PASS not in caplog.text
    assert any("not wrapped" in r.getMessage() for r in caplog.records)


def test_temporary_names_differ_even_for_the_same_process_and_thread_number(tmp_path, monkeypatch):
    """Two containers on one data volume can both be process 1 with the same thread number."""
    scope_os(monkeypatch, kf, getpid=lambda: 1)
    monkeypatch.setattr(kf.threading, "get_ident", lambda: 7)
    p = tmp_path / "k.pem"
    names = {kf.private_name(p, "new").name for _ in range(50)}
    assert len(names) == 50


def test_the_pending_directory_does_not_stay_in_the_keys_listing(tmp_path, monkeypatch):
    """The encryption attestation names every entry of keys/; a leftover directory would be one."""
    _hold(monkeypatch, PASS)
    ev.load_or_create_signing_key(tmp_path / "new.pem")
    legacy = Ed25519PrivateKey.generate()
    (tmp_path / "old.pem").write_bytes(_plain_pem(legacy))
    ev.load_or_create_signing_key(tmp_path / "old.pem")
    assert sorted(f.name for f in tmp_path.iterdir()) == ["new.pem", "old.pem"]


def test_a_plaintext_alias_a_dead_creation_left_is_removed_when_the_key_is_wrapped(
    tmp_path, monkeypatch
):
    """A creation killed between its ``os.link`` and the removal of its private name leaves that name as
    a second name for the key file's bytes. On a store with no passphrase those bytes are the plaintext
    key, and wrapping only the canonical name would leave the key readable there for good."""
    p = tmp_path / "k.pem"
    real_unlink = Path.unlink

    def dies_at_the_private_name(self, *a, **kw):
        if kf.PENDING in self.parts:
            raise KeyboardInterrupt  # the process is gone before it removes its own name
        return real_unlink(self, *a, **kw)

    with monkeypatch.context() as m:
        m.setattr(Path, "unlink", dies_at_the_private_name)
        with pytest.raises(KeyboardInterrupt):
            ev.load_or_create_signing_key(p)
    leftover = _pending_left(tmp_path)
    assert len(leftover) == 1  # the premise: the crash does leave a second name
    plain = (tmp_path / kf.PENDING / leftover[0]).read_bytes()
    assert plain.startswith(b"-----BEGIN PRIVATE KEY-----") and plain == p.read_bytes()

    _hold(monkeypatch, PASS)
    key = ev.load_or_create_signing_key(p)
    assert _is_wrapped(p)
    assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(key)
    assert _pending_left(tmp_path) == []
    assert not (tmp_path / kf.PENDING).exists()
    assert not any(
        b"BEGIN PRIVATE KEY" in f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()
    )


def test_the_alias_sweep_removes_only_names_that_are_the_replaced_file(tmp_path, monkeypatch):
    """By file identity, never by name or by being in the directory: another caller's file that is not
    linked to the key has an inode of its own and stays."""
    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(_plain_pem(legacy))
    pending = tmp_path / kf.PENDING
    pending.mkdir()
    alias = pending / "k.pem.9.9.aaaaaaaaaaaa.new"
    os.link(p, alias)
    stranger = pending / "k.pem.8.8.bbbbbbbbbbbb.new"
    stranger.write_bytes(
        _plain_pem(Ed25519PrivateKey.generate())
    )  # same bytes' shape, another file
    _hold(monkeypatch, PASS)
    ev.load_or_create_signing_key(p)
    assert _is_wrapped(p)
    assert not alias.exists()
    assert stranger.exists()


def test_the_alias_sweep_does_not_trust_a_directory_entrys_own_stat(tmp_path, monkeypatch):
    """On Windows ``DirEntry.stat()`` answers 0 for the device, the inode and the link count, so a sweep
    that matched names with it would find nothing and leave the plaintext alias there. Model that: the
    entries the sweep is handed answer zeros, and the alias must still go."""
    import types

    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(_plain_pem(legacy))
    pending = tmp_path / kf.PENDING
    pending.mkdir()
    alias = pending / "k.pem.9.9.aaaaaaaaaaaa.new"
    os.link(p, alias)

    class Zeroed:
        def __init__(self, entry):
            self.path, self.name, self._entry = entry.path, entry.name, entry

        def stat(self, *, follow_symlinks=True):
            real = self._entry.stat(follow_symlinks=follow_symlinks)
            return types.SimpleNamespace(st_dev=0, st_ino=0, st_nlink=0, st_mode=real.st_mode)

    class Scan:
        def __init__(self, where):
            self._real = os.scandir(where)

        def __enter__(self):
            return (Zeroed(e) for e in self._real.__enter__())

        def __exit__(self, *exc):
            return self._real.__exit__(*exc)

    scope_os(monkeypatch, kf, scandir=Scan)
    _hold(monkeypatch, PASS)
    ev.load_or_create_signing_key(p)
    assert _is_wrapped(p)
    assert not alias.exists()


@pytest.mark.parametrize(
    "how", ["replaced by another file", "rewritten in place", "replaced before the wrap starts"]
)
def test_a_wrap_stands_down_when_the_key_file_changed_while_its_copy_was_made(
    tmp_path, monkeypatch, caplog, how
):
    """The caller read K1; before its rename the file was erased and a restore (or another caller) put
    another key there, or it was overwritten where it stood. Its copy of K1 must not replace that, and
    the sweep must not then remove the other key's surviving names."""
    k1, k2 = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(_plain_pem(k1))
    other = _plain_pem(k2)
    real_seal = ev._seal

    def seal_then_the_file_changes(key, passphrase):
        out = real_seal(key, passphrase)
        if how == "replaced by another file":
            p.unlink()
            p.write_bytes(other)
        elif how == "rewritten in place":
            p.write_bytes(other)  # same inode, new content and time
        return out

    monkeypatch.setattr(ev, "_seal", seal_then_the_file_changes)
    if how == "replaced before the wrap starts":
        # between the read that gave the caller K1 and the start of its wrap (the identity must be
        # the one it READ, not one taken when the wrap begins)
        real_parse, calls = ev._parse_key, []

        def parse_then_the_file_changes(path, raw, passphrase):
            out = real_parse(path, raw, passphrase)
            if not calls:
                calls.append(1)
                p.unlink()
                p.write_bytes(other)
            return out

        monkeypatch.setattr(ev, "_parse_key", parse_then_the_file_changes)
    _hold(monkeypatch, PASS)
    with caplog.at_level(logging.WARNING):
        got = ev.load_or_create_signing_key(p)
    assert ev.public_key_hex(got) == ev.public_key_hex(k1)  # this call signs with what it read
    assert p.read_bytes() == other  # and the file is what the other caller left, not K1 wrapped
    assert _pending_left(tmp_path) == []
    assert not (tmp_path / kf.PENDING).exists()
    assert PASS not in caplog.text


@pytest.mark.parametrize(
    "decorate",
    [
        pytest.param(lambda pem: b"\xef\xbb\xbf" + pem, id="byte-order mark"),
        pytest.param(
            lambda pem: b"Bag Attributes\n    friendlyName: evidence\n" + pem, id="openssl preamble"
        ),
    ],
)
def test_a_pem_with_something_before_its_header_is_still_a_pem(tmp_path, monkeypatch, decorate):
    """``load_pem_private_key`` reads these, and the file used to load; they must not be taken for a
    wrapped blob (which would name a false cause and refuse every export and backup)."""
    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(decorate(_plain_pem(legacy)))
    assert ev.public_key_hex(ev.load_or_create_signing_key(p)) == ev.public_key_hex(legacy)
    assert ev.existing_public_key_hex(p) == ev.public_key_hex(legacy)
    _hold(monkeypatch, PASS)
    assert ev.public_key_hex(ev.load_or_create_signing_key(p)) == ev.public_key_hex(legacy)
    assert _is_wrapped(p)  # and it is wrapped in place like any legacy key
    assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(legacy)


def test_a_wrap_never_removes_or_uses_a_file_it_did_not_make(tmp_path, monkeypatch):
    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(_plain_pem(legacy))
    others = [
        tmp_path / "k.pem.rewrap",  # the name every caller used to share
        tmp_path / kf.PENDING / "k.pem.1.2.rewrap",  # another process's file, in flight
        tmp_path / kf.PENDING / "k.pem.1.2.new",
    ]
    (tmp_path / kf.PENDING).mkdir()
    for f in others:
        f.write_bytes(b"somebody else's, unfinished")
    _hold(monkeypatch, PASS)
    ev.load_or_create_signing_key(p)
    assert _is_wrapped(p)
    assert all(f.read_bytes() == b"somebody else's, unfinished" for f in others)


def test_two_callers_wrapping_at_once_never_rename_the_others_unfinished_file(
    tmp_path, monkeypatch
):
    """The interleaving that lost a key: A has written and checked its wrapped copy and is about to rename
    it; B starts, makes its own file (created, still empty) and A's rename must not move B's file."""
    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(_plain_pem(legacy))
    _hold(monkeypatch, PASS)
    real_write, real_replace = kf.write_new, kf.os.replace
    b_created, b_go = threading.Event(), threading.Event()
    state: dict = {}

    def write(path, data):
        if threading.current_thread() is state.get("b"):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # created, still empty
            b_created.set()
            b_go.wait(10)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            return
        real_write(path, data)

    def replace(src, dst):
        if "b" not in state:  # A's rename: B comes in just before it
            t = threading.Thread(target=lambda: ev._wrap_in_place(p, legacy, PASS.encode()))
            state["b"] = t
            t.start()
            assert b_created.wait(10)
        real_replace(src, dst)

    monkeypatch.setattr(kf, "write_new", write)
    scope_os(monkeypatch, kf, replace=replace)
    assert ev._wrap_in_place(p, legacy, PASS.encode()) is True
    assert p.read_bytes(), "A's rename moved B's empty file over the key"
    assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(legacy)
    b_go.set()
    state["b"].join(10)
    assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(legacy)
    assert _pending_left(tmp_path) == []


def test_eight_threads_wrapping_a_legacy_key_at_once_end_with_one_wrapped_key(
    tmp_path, monkeypatch
):
    legacy = Ed25519PrivateKey.generate()
    _hold(monkeypatch, PASS)
    for trial in range(8):
        p = tmp_path / f"t{trial}.pem"
        p.write_bytes(_plain_pem(legacy))
        out, errors = _create_at_once(p)
        assert not errors, errors
        assert set(out) == {ev.public_key_hex(legacy)}
        assert ev.public_key_hex(_opens_with(p, PASS)) == ev.public_key_hex(legacy)
    assert all(f.endswith(".pem") for f in _files(tmp_path))
    assert _pending_left(tmp_path) == []


# --------------------------------------------------------------------------- #
#  A wrapped key that cannot be opened (rulings b and c): loud, never destructive
# --------------------------------------------------------------------------- #


def test_a_wrapped_key_with_no_passphrase_held_refuses_to_sign_and_says_it_is_locked(tmp_path):
    owner = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    raw = _wrapped(owner, PASS)
    p.write_bytes(raw)
    with pytest.raises(ev.EvidenceKeyError) as err:
        ev.load_or_create_signing_key(p)
    assert "none is held" in str(err.value) and "locked" in str(err.value)
    assert p.read_bytes() == raw, "a locked app never replaces the key"
    assert isinstance(err.value, ValueError), (
        "the API's (ValueError, OSError) handler still catches it"
    )


def test_a_wrapped_key_under_another_passphrase_names_the_cause_and_is_left_alone(
    tmp_path, monkeypatch
):
    """Ruling (b): a backup restored from another install carries its key as that install wrapped it."""
    owner = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    raw = _wrapped(owner, PASS)
    p.write_bytes(raw)
    _hold(monkeypatch, OTHER)
    with pytest.raises(ev.EvidenceKeyError) as err:
        ev.load_or_create_signing_key(p)
    text = str(err.value)
    assert "another install" in text and "damaged" in text
    assert PASS not in text and OTHER not in text
    assert p.read_bytes() == raw, "no new key is generated over a key that is there"
    assert "marker" not in repr(err.value)


def test_a_foreign_key_type_is_refused_wrapped_or_not(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PrivateKey

    foreign = Ed448PrivateKey.generate()
    plain = tmp_path / "plain.pem"
    plain.write_bytes(
        foreign.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(ev.EvidenceKeyError, match="does not hold an Ed25519"):
        ev.load_or_create_signing_key(plain)
    protected = tmp_path / "protected.pem"
    raw = foreign.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(PASS.encode()),
    )
    protected.write_bytes(raw)
    _hold(monkeypatch, PASS)
    with pytest.raises(ev.EvidenceKeyError, match="password-protected PEM"):
        ev.load_or_create_signing_key(protected)
    assert protected.read_bytes() == raw, "a file that is not ours is never replaced"
    assert ev.signing_key_state(protected) == ("unreadable", None)


def test_a_wrapped_blob_that_holds_the_wrong_number_of_key_bytes_is_refused_as_damaged(
    tmp_path, monkeypatch
):
    from src.custody import signing

    p = tmp_path / "k.pem"
    raw = signing._wrap(b"not thirty-two bytes", PASS.encode())
    p.write_bytes(raw)
    _hold(monkeypatch, PASS)
    with pytest.raises(ev.EvidenceKeyError, match="damaged"):
        ev.load_or_create_signing_key(p)
    assert p.read_bytes() == raw


def test_a_passphrase_that_cannot_be_written_as_utf8_is_refused_with_fixed_words(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "OO_KEY_PASSPHRASE", "ab\udcffcd"
    )  # an environment of non-UTF-8 bytes reads as a lone surrogate
    with pytest.raises(ev.EvidenceKeyError) as err:
        ev.load_or_create_signing_key(tmp_path / "k.pem")
    assert "\udcff" not in str(err.value) and "ab" not in str(err.value).replace("cannot", "")
    assert not (tmp_path / "k.pem").exists()


# --------------------------------------------------------------------------- #
#  The review reads and never writes
# --------------------------------------------------------------------------- #


def test_the_review_reads_a_wrapped_key_with_the_held_passphrase_and_changes_nothing(
    tmp_path, monkeypatch
):
    owner = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    p.write_bytes(_wrapped(owner, PASS))
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    _hold(monkeypatch, PASS)
    assert ev.existing_public_key_hex(p) == ev.public_key_hex(owner)
    assert ev.signing_key_state(p) == ("ok", ev.public_key_hex(owner))
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before


def test_the_review_does_not_wrap_a_legacy_plaintext_key_that_is_the_exports_job(
    tmp_path, monkeypatch
):
    legacy = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    raw = _plain_pem(legacy)
    p.write_bytes(raw)
    before = (raw, p.stat().st_mtime_ns)
    _hold(monkeypatch, PASS)
    assert ev.signing_key_state(p) == ("ok", ev.public_key_hex(legacy))
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before
    # a review that wrote a temporary file and left it would show here (the temporary files of this
    # key live in ``.pending``; nothing is ever beside it)
    assert _pending_left(tmp_path) == []
    assert not (tmp_path / kf.PENDING).exists()
    assert _files(tmp_path) == ["k.pem"]


def test_the_review_calls_a_key_it_cannot_open_unreadable_and_never_creates_one(
    tmp_path, monkeypatch
):
    owner = Ed25519PrivateKey.generate()
    p = tmp_path / "k.pem"
    raw = _wrapped(owner, PASS)
    p.write_bytes(raw)
    assert ev.signing_key_state(p) == ("unreadable", None), "locked: no passphrase held"
    _hold(monkeypatch, OTHER)
    assert ev.signing_key_state(p) == ("unreadable", None), "another passphrase"
    assert p.read_bytes() == raw
    absent = tmp_path / "absent.pem"
    assert ev.signing_key_state(absent) == ("none", None)
    assert ev.existing_public_key_hex(absent) is None
    assert not absent.exists()


# --------------------------------------------------------------------------- #
#  The passphrase is nowhere it must not be
# --------------------------------------------------------------------------- #


def test_the_passphrase_is_in_no_log_line_or_error(tmp_path, monkeypatch, caplog):
    _hold(monkeypatch, PASS)
    p = tmp_path / "keys" / "k.pem"
    with caplog.at_level(logging.DEBUG):
        ev.load_or_create_signing_key(p)
        ev.load_or_create_signing_key(p)
        ev.signing_key_state(p)
        _hold(monkeypatch, OTHER)
        with pytest.raises(ev.EvidenceKeyError) as err:
            ev.load_or_create_signing_key(p)
    assert PASS not in caplog.text and OTHER not in caplog.text
    assert PASS not in str(err.value) and OTHER not in str(err.value)


# --------------------------------------------------------------------------- #
#  Through the real exports
# --------------------------------------------------------------------------- #


def _corpus(tmp_path: Path) -> Path:
    p = tmp_path / "corpus.db"
    con = sqlite3.connect(p)
    con.executescript(
        """
        CREATE TABLE articles (id INTEGER PRIMARY KEY, hash TEXT, title TEXT, content TEXT);
        CREATE UNIQUE INDEX ix_articles_hash ON articles(hash);
        CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE wiki_pages (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE law_documents (id INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE keyword_mentions (id INTEGER PRIMARY KEY, term TEXT);
        CREATE TABLE alembic_version (version_num TEXT);
        INSERT INTO alembic_version VALUES ('f4c2a1b9d7e0');
        INSERT INTO articles VALUES (1, 'h1', 't', 'c');
        """
    )
    con.commit()
    con.close()
    return p


def _export(tmp_path: Path):
    from src.backup.export_folder import allocate_export_folder
    from src.backup.stream_backup import CorpusSource, _no_freeze, write_stream_backup

    dest = allocate_export_folder(tmp_path / "drive")
    src = CorpusSource(
        path=_corpus(tmp_path), member_name="corpus.db", encrypted=False, freeze=_no_freeze
    )
    return write_stream_backup(
        dest, "a-backup-passphrase", corpus_source=src, volume_size=128 * 1024
    )


def test_the_first_encrypted_export_makes_a_wrapped_key_and_signs_with_it(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    _hold(monkeypatch, PASS)
    summary = _export(tmp_path)
    key_file = data / "keys" / "evidence_ed25519.pem"
    assert _is_wrapped(key_file)
    env = summary["envelope"]
    assert env["public_key"] == ev.public_key_hex(_opens_with(key_file, PASS))
    names = [m["name"] for m in env["manifest"]["members"]]
    assert "keys/evidence_ed25519.pem" in names, "the identity that signed it still travels with it"
    from src.backup.stream_backup import (
        _sign_manifest,
    )  # the same loader signs every later manifest

    sig = _sign_manifest({"a": 1})
    assert sig["public_key"] == env["public_key"]
    pub = _opens_with(key_file, PASS).public_key()
    body = ev.canonical_bytes({"a": 1})
    pub.verify(bytes.fromhex(sig["signature"]), body)
    with pytest.raises(InvalidSignature):
        pub.verify(bytes.fromhex(sig["signature"]), body + b" ")


def test_an_export_with_a_key_wrapped_under_another_passphrase_fails_naming_the_cause(
    tmp_path, monkeypatch
):
    """Ruling (b) through the real writer: the failure is the loader's own words, reaching the export job's
    status text, and the key file is not touched."""
    data = tmp_path / "data"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    (data / "keys").mkdir(parents=True)
    key_file = data / "keys" / "evidence_ed25519.pem"
    raw = _wrapped(Ed25519PrivateKey.generate(), PASS)
    key_file.write_bytes(raw)
    _hold(monkeypatch, OTHER)
    with pytest.raises(ev.EvidenceKeyError, match="another install"):
        _export(tmp_path)
    assert key_file.read_bytes() == raw


def _seed_one_article() -> int:
    import uuid

    from src.database.models import Article, Source
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        domain = f"evwrap-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=f"Wrap {domain}", domain=domain, language="en")
        s.add(src)
        s.flush()
        art = Article(
            url=f"https://{domain}/a/1",
            canonical_url=f"https://{domain}/a/1",
            source_id=src.id,
            title="Wrap article",
            content="Body " * 30,
            language="en",
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        s.add(art)
        s.flush()
        return art.id


def test_the_evidence_export_answers_409_with_the_cause_for_a_key_it_cannot_open(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from src.api.main import app

    key_file = tmp_path / "keys" / "evidence_ed25519.pem"
    key_file.parent.mkdir(parents=True)
    raw = _wrapped(Ed25519PrivateKey.generate(), PASS)
    key_file.write_bytes(raw)
    monkeypatch.setattr(ev, "_default_key_path", lambda: key_file)
    _hold(monkeypatch, OTHER)
    art_id = _seed_one_article()
    with TestClient(app) as client:
        r = client.post("/api/reports/evidence", json={"article_ids": [art_id]})
        plan = client.post("/api/reports/evidence/plan", json={"article_ids": [art_id]})
    assert r.status_code == 409, r.text
    assert "another install" in r.json()["detail"]
    assert OTHER not in r.text and PASS not in r.text
    assert plan.status_code == 200, plan.text
    assert plan.json()["signer"] == {"exists": True, "state": "unreadable", "ed25519_pub": None}
    assert key_file.read_bytes() == raw


def test_the_evidence_export_signs_with_the_wrapped_key_and_the_review_names_the_same_key(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from src.api.main import app

    key_file = tmp_path / "keys" / "evidence_ed25519.pem"
    monkeypatch.setattr(ev, "_default_key_path", lambda: key_file)
    _hold(monkeypatch, PASS)
    art_id = _seed_one_article()
    with TestClient(app) as client:
        bundle = client.post("/api/reports/evidence", json={"article_ids": [art_id]}).json()
        plan = client.post("/api/reports/evidence/plan", json={"article_ids": [art_id]}).json()
    assert _is_wrapped(key_file)
    ok, _reason = ev.verify_bundle(
        bundle, trusted_public_key=ev.public_key_hex(_opens_with(key_file, PASS))
    )
    assert ok
    assert plan["signer"] == {"exists": True, "state": "ok", "ed25519_pub": bundle["public_key"]}
