"""The custody Ed25519 key is wrapped under the held passphrase and made once (E3 / A-009 / R449).

Before: ``HybridSigner`` wrote the key as PKCS8 PEM, under a passphrase with ``BestAvailableEncryption``
(PBKDF2-HMAC-SHA256, 2048 rounds: 0.3 ms a guess, against SQLCipher's 170 ms for the same secret), by
``write_bytes`` then ``chmod`` (a window at mode 0644 under a umask of 022), with check-then-write creation
(two first callers could each make a key, and the second orphaned what the first had signed). The same
class writes the annotation signer's key, so both files are covered here.

After: with a passphrase held the file is the custody signer's own wrap of the raw key (scrypt, AES-256-GCM),
created ``O_EXCL`` at 0600 and linked into place from a finished private copy; a key written in either older
form (plaintext, or PKCS8-encrypted) is wrapped IN PLACE and never changes; a key that cannot be opened raises
``SigningError`` naming the cause and is never replaced; ``key_protection`` says what the file really holds.

The negative space carries the weight: the passphrase is in no file name, log line or error, a failed wrap
leaves the original bytes, a locked app signs nothing, a file that changed meanwhile is not overwritten.
"""

from __future__ import annotations

import logging
import os
import stat
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.custody import keyfile as kf
from src.custody import signing
from src.custody.signing import HybridSigner, SigningError, verify
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


def _hold(monkeypatch, passphrase: str | None) -> None:
    if passphrase is None:
        monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    else:
        monkeypatch.setenv("OO_KEY_PASSPHRASE", passphrase)


def _signer(directory: Path, name: str = "ed.pem") -> HybridSigner:
    """A signer on its own key files; Ed25519 only, which is all this file is about."""
    return HybridSigner(
        ed25519_path=directory / name, mldsa_path=directory / "ml.key", use_pqc=False
    )


def _seed(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )


def _pub(key: Ed25519PrivateKey) -> bytes:
    return signing._ed25519_public_bytes(key)


def _plain_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _old_pkcs8(key: Ed25519PrivateKey, passphrase: str) -> bytes:
    """What this signer wrote under a passphrase before the wrap: PKCS8 under BestAvailableEncryption."""
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase.encode()),
    )


def _is_wrapped(path: Path) -> bool:
    """A wrapped key file is not a PEM at all: salt(16) || nonce(12) || the 32 key bytes || the GCM tag(16)."""
    raw = path.read_bytes()
    return b"-----BEGIN" not in raw and len(raw) == 16 + 12 + 32 + 16


def _opens_with(path: Path, passphrase: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(
        signing._unwrap(path.read_bytes(), passphrase.encode())
    )


def _pending_left(directory: Path) -> list[str]:
    pending = directory / kf.PENDING
    return sorted(f.name for f in pending.iterdir()) if pending.is_dir() else []


def _files(directory: Path) -> list[str]:
    return sorted(f.name for f in directory.iterdir() if f.is_file())


# --------------------------------------------------------------------------- #
#  A new key
# --------------------------------------------------------------------------- #


def test_a_new_key_is_wrapped_when_a_passphrase_is_held(tmp_path, monkeypatch):
    _hold(monkeypatch, PASS)
    s = _signer(tmp_path)
    p = tmp_path / "ed.pem"
    raw = p.read_bytes()
    assert _is_wrapped(p)
    assert PASS.encode() not in raw
    assert s.key_protection == "aes256gcm-scrypt"
    opened = _opens_with(p, PASS)
    assert _seed(opened) not in raw
    assert _pub(opened) == bytes.fromhex(s.public_identity().ed25519_pub)
    # it is the key that signs: the identity verifies a signature made now
    assert verify(s.sign(MESSAGE), MESSAGE, pinned=s.public_identity())[0] is True


def test_the_same_passphrase_reloads_the_same_identity(tmp_path, monkeypatch):
    _hold(monkeypatch, PASS)
    first = _signer(tmp_path).public_identity().ed25519_pub
    assert _signer(tmp_path).public_identity().ed25519_pub == first
    assert _pending_left(tmp_path) == []


def test_the_held_database_passphrase_wraps_it_and_the_environment_one_wins(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", PASS)
    held = tmp_path / "held"
    held.mkdir()
    _signer(held)
    _opens_with(held / "ed.pem", PASS)
    _hold(monkeypatch, OTHER)  # OO_KEY_PASSPHRASE wins over the held one
    env = tmp_path / "env"
    env.mkdir()
    _signer(env)
    _opens_with(env / "ed.pem", OTHER)


def test_no_passphrase_held_writes_the_plaintext_key_it_always_wrote(tmp_path):
    s = _signer(tmp_path)
    raw = (tmp_path / "ed.pem").read_bytes()
    assert raw.startswith(b"-----BEGIN PRIVATE KEY-----")
    assert s.key_protection == "plaintext-0600"
    loaded = serialization.load_pem_private_key(raw, password=None)
    assert isinstance(loaded, Ed25519PrivateKey)
    assert _pub(loaded) == bytes.fromhex(s.public_identity().ed25519_pub)


@posix_only
@pytest.mark.parametrize("passphrase", [None, PASS])
def test_a_new_key_is_never_readable_by_another_account_not_even_for_a_moment(
    tmp_path, monkeypatch, passphrase
):
    """The file is created with mode 0600 and O_EXCL (a flag of the creation itself), not chmod-ed afterwards."""
    _hold(monkeypatch, passphrase)
    seen: list[tuple[str, int, int]] = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **kw):
        seen.append((os.fspath(path), flags, mode))
        return real_open(path, flags, mode, *a, **kw)

    scope_os(monkeypatch, kf, open=spy)
    old = os.umask(0o022)
    try:
        _signer(tmp_path)
    finally:
        os.umask(old)
    creates = [(f, m) for _p, f, m in seen if f & os.O_CREAT]
    assert creates, "no create was seen"
    assert all(f & os.O_EXCL and m == 0o600 for f, m in creates)
    assert stat.S_IMODE((tmp_path / "ed.pem").stat().st_mode) == 0o600
    assert _pending_left(tmp_path) == []
    assert "ed.pem" in _files(tmp_path)


# --------------------------------------------------------------------------- #
#  A key written before
# --------------------------------------------------------------------------- #


def test_a_legacy_plaintext_key_is_wrapped_in_place_and_stays_the_same_key(tmp_path, monkeypatch):
    before = _signer(tmp_path)  # no passphrase: plaintext, as before
    ident = before.public_identity().ed25519_pub
    signature = before.sign(MESSAGE)
    assert before.key_protection == "plaintext-0600"
    _hold(monkeypatch, PASS)
    after = _signer(tmp_path)
    p = tmp_path / "ed.pem"
    assert _is_wrapped(p) and _pub(_opens_with(p, PASS)) == bytes.fromhex(ident)
    assert after.public_identity().ed25519_pub == ident
    assert after.key_protection == "aes256gcm-scrypt"
    # what the old key signed stays verifiable against the identity that has not changed
    assert verify(signature, MESSAGE, pinned=after.public_identity())[0] is True
    assert _pending_left(tmp_path) == []


def test_a_pkcs8_encrypted_key_from_before_is_wrapped_in_place_and_stays_the_same_key(
    tmp_path, monkeypatch
):
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(_old_pkcs8(key, PASS))
    _hold(monkeypatch, PASS)
    s = _signer(tmp_path)
    assert b"ENCRYPTED PRIVATE KEY" not in p.read_bytes()
    assert _is_wrapped(p)
    assert _pub(_opens_with(p, PASS)) == _pub(key)
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(key)
    assert s.key_protection == "aes256gcm-scrypt"


@pytest.mark.parametrize("old_form", ["plaintext", "pkcs8"])
@pytest.mark.parametrize("how", ["replace", "write"])
def test_a_failed_wrap_leaves_the_original_file_and_still_signs(
    tmp_path, monkeypatch, old_form, how
):
    key = Ed25519PrivateKey.generate()
    original = _plain_pem(key) if old_form == "plaintext" else _old_pkcs8(key, PASS)
    p = tmp_path / "ed.pem"
    p.write_bytes(original)
    _hold(monkeypatch, PASS)

    def boom(*_a, **_k):
        raise OSError("disk says no")

    if how == "replace":
        scope_os(monkeypatch, kf, replace=boom)
    else:
        monkeypatch.setattr(kf, "write_new", boom)
    s = _signer(tmp_path)
    assert p.read_bytes() == original
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(key)
    assert verify(s.sign(MESSAGE), MESSAGE, pinned=s.public_identity())[0] is True
    # what the FILE holds, not what the environment wishes
    assert s.key_protection == ("plaintext-0600" if old_form == "plaintext" else "pkcs8-pbkdf2")
    assert _pending_left(tmp_path) == []
    # the next load tries again, and this time nothing is in the way
    monkeypatch.undo()
    _hold(monkeypatch, PASS)
    assert _signer(tmp_path).key_protection == "aes256gcm-scrypt"
    assert _is_wrapped(p)


def test_a_copy_that_does_not_open_to_the_same_key_never_replaces_the_file(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(_plain_pem(key))
    _hold(monkeypatch, PASS)
    other = Ed25519PrivateKey.generate()
    monkeypatch.setattr(signing, "seal_ed25519_key", lambda _k, pp: signing._wrap(_seed(other), pp))
    s = _signer(tmp_path)
    assert p.read_bytes() == _plain_pem(key)
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(key)
    assert _pending_left(tmp_path) == []


def test_a_file_that_changed_while_the_copy_was_made_is_not_overwritten(tmp_path, monkeypatch):
    """Another caller wrapped (or restored over) the file between our read and our swap: theirs stays."""
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(_plain_pem(key))
    _hold(monkeypatch, PASS)
    real_seal = signing.seal_ed25519_key
    theirs = signing._wrap(_seed(key), PASS.encode())

    def seal_then_lose_the_race(k, pp):
        blob = real_seal(k, pp)
        side = tmp_path / "side"
        side.write_bytes(theirs)
        os.replace(side, p)  # a different file under the same name
        return blob

    monkeypatch.setattr(signing, "seal_ed25519_key", seal_then_lose_the_race)
    s = _signer(tmp_path)
    assert p.read_bytes() == theirs
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(key)
    # it reports the file as it IS now (wrapped by the other caller), not as this caller first read it
    assert s.key_protection == "aes256gcm-scrypt"
    assert _pending_left(tmp_path) == []


# --------------------------------------------------------------------------- #
#  A key that cannot be opened: loud, named, never replaced
# --------------------------------------------------------------------------- #


def _assert_untouched_and_clean(
    directory: Path, name: str, before: bytes, files: list[str]
) -> None:
    assert (directory / name).read_bytes() == before
    assert _files(directory) == files
    assert _pending_left(directory) == []


@pytest.mark.parametrize("old_form", ["wrapped", "pkcs8"])
def test_the_wrong_passphrase_raises_naming_the_file_and_changes_nothing(
    tmp_path, monkeypatch, old_form
):
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(
        signing._wrap(_seed(key), PASS.encode()) if old_form == "wrapped" else _old_pkcs8(key, PASS)
    )
    before, files = p.read_bytes(), _files(tmp_path)
    _hold(monkeypatch, OTHER)
    with pytest.raises(SigningError) as err:
        _signer(tmp_path)
    text = str(err.value)
    assert "ed.pem" in text and "passphrase" in text
    assert PASS not in text and OTHER not in text
    _assert_untouched_and_clean(tmp_path, "ed.pem", before, files)


@pytest.mark.parametrize("old_form", ["wrapped", "pkcs8"])
def test_a_locked_app_signs_nothing_and_changes_nothing(tmp_path, monkeypatch, old_form):
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(
        signing._wrap(_seed(key), PASS.encode()) if old_form == "wrapped" else _old_pkcs8(key, PASS)
    )
    before, files = p.read_bytes(), _files(tmp_path)
    with pytest.raises(SigningError, match="no passphrase is held"):
        _signer(tmp_path)
    _assert_untouched_and_clean(tmp_path, "ed.pem", before, files)


def test_an_empty_file_is_named_as_a_cut_short_creation_and_not_replaced(tmp_path):
    p = tmp_path / "ed.pem"
    p.write_bytes(b"")
    with pytest.raises(SigningError, match="empty"):
        _signer(tmp_path)
    assert p.read_bytes() == b""
    assert _pending_left(tmp_path) == []


def test_a_foreign_key_type_is_refused_not_signed_with(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PrivateKey

    p = tmp_path / "ed.pem"
    foreign = Ed448PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    p.write_bytes(foreign)
    with pytest.raises(SigningError, match="Ed25519"):
        _signer(tmp_path)
    assert p.read_bytes() == foreign


def test_a_pem_with_a_preamble_or_a_byte_order_mark_still_loads(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(b"\xef\xbb\xbfBag Attributes\n    friendlyName: x\n" + _plain_pem(key))
    s = _signer(tmp_path)
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(key)


def test_a_damaged_wrapped_file_is_refused_and_never_regenerated(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    blob = bytearray(signing._wrap(_seed(key), PASS.encode()))
    blob[40] ^= 0x01  # one flipped bit in the ciphertext: the GCM tag no longer holds
    p = tmp_path / "ed.pem"
    p.write_bytes(bytes(blob))
    _hold(monkeypatch, PASS)
    with pytest.raises(SigningError):
        _signer(tmp_path)
    assert p.read_bytes() == bytes(blob)


# --------------------------------------------------------------------------- #
#  Made once
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("passphrase", [None, PASS])
def test_two_first_callers_end_with_one_key_and_no_reader_sees_half_a_file(
    tmp_path, monkeypatch, passphrase
):
    _hold(monkeypatch, passphrase)
    callers = 6
    start = threading.Barrier(callers)
    results: list[str] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            start.wait(timeout=30)
            results.append(_signer(tmp_path).public_identity().ed25519_pub)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors, errors
    assert len(results) == callers and len(set(results)) == 1
    on_disk = tmp_path / "ed.pem"
    if passphrase:
        assert _is_wrapped(on_disk)
        assert bytes.fromhex(results[0]) == _pub(_opens_with(on_disk, passphrase))
    assert _pending_left(tmp_path) == []
    assert _files(tmp_path).count("ed.pem") == 1


def test_the_loser_of_a_creation_race_uses_the_winners_key(tmp_path, monkeypatch):
    """The create is refused with FileExistsError at the link: ONE key, the one already there."""
    _hold(monkeypatch, PASS)
    p = tmp_path / "ed.pem"
    winner = Ed25519PrivateKey.generate()
    real_link = kf.os.link

    def racing(src, dst, *a, **kw):
        kf.write_new(
            Path(dst), signing._wrap(_seed(winner), PASS.encode())
        )  # the other caller got there first
        return real_link(src, dst, *a, **kw)

    scope_os(monkeypatch, kf, link=racing)
    s = _signer(tmp_path)
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(winner)
    assert _pub(_opens_with(p, PASS)) == _pub(winner)
    assert _pending_left(tmp_path) == []


def test_a_pending_folder_that_is_gone_again_after_mkdir_answered_exists_is_not_an_error(
    tmp_path, monkeypatch
):
    """Path.mkdir(exist_ok=True) answers EEXIST and then asks is_dir(): a caller that removed the empty
    folder in between made it raise FileExistsError for a folder that was there when it looked, and
    create_new quietly took the in-place fallback, which a reader can meet half done."""
    import pathlib

    p = tmp_path / "ed.pem"
    (tmp_path / kf.PENDING).mkdir()
    real = pathlib.Path.is_dir
    monkeypatch.setattr(
        pathlib.Path, "is_dir", lambda self: False if self.name == kf.PENDING else real(self)
    )
    name = kf.private_name(p, "new")
    assert name.parent == tmp_path / kf.PENDING


def test_a_pending_folder_removed_before_the_file_is_created_is_made_again(tmp_path, monkeypatch):
    p = tmp_path / "ed.pem"
    real = kf.write_new
    gone = {"left": 7}

    def folder_gone_again(path, data):
        if gone["left"]:
            gone["left"] -= 1
            raise FileNotFoundError(path)
        return real(path, data)

    monkeypatch.setattr(kf, "write_new", folder_gone_again)
    tmp = kf.write_private(p, "new", b"x")
    assert tmp.read_bytes() == b"x" and gone["left"] == 0
    tmp.unlink()
    gone["left"] = 100
    with pytest.raises(FileNotFoundError, match="kept disappearing"):
        kf.write_private(p, "new", b"x")


def test_the_annotation_signers_key_is_wrapped_the_same_way(tmp_path, monkeypatch):
    """``annotation_signer`` is a HybridSigner on its own file: it gets the same protection with no code of its own."""
    from src.annotations.bundle import annotation_signer

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _hold(monkeypatch, PASS)
    s = annotation_signer()
    p = tmp_path / "keys" / "annotations_ed25519.pem"
    assert _is_wrapped(p)
    assert _pub(_opens_with(p, PASS)) == bytes.fromhex(s.public_identity().ed25519_pub)
    assert s.key_protection == "aes256gcm-scrypt"


# --------------------------------------------------------------------------- #
#  The passphrase stays out of every record
# --------------------------------------------------------------------------- #


def test_the_passphrase_is_in_no_log_line_or_error(tmp_path, monkeypatch, caplog):
    key = Ed25519PrivateKey.generate()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "ed.pem").write_bytes(_plain_pem(key))
    pkcs8 = tmp_path / "pkcs8"
    pkcs8.mkdir()
    (pkcs8 / "ed.pem").write_bytes(_old_pkcs8(key, PASS))
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "ed.pem").write_bytes(signing._wrap(_seed(key), OTHER.encode()))
    _hold(monkeypatch, PASS)

    def boom(*_a, **_k):
        raise OSError(
            f"marker {PASS}"
        )  # an error that carries the secret: it must not reach a record

    with caplog.at_level(logging.DEBUG):
        _signer(tmp_path)  # a fresh creation
        _signer(legacy)  # a wrap
        _signer(pkcs8)  # a wrap of the old form
        with monkeypatch.context() as m:
            scope_os(m, kf, replace=boom)
            fail = tmp_path / "fail"
            fail.mkdir()
            (fail / "ed.pem").write_bytes(_plain_pem(key))
            _signer(fail)  # a failed wrap
        with pytest.raises(SigningError) as err:
            _signer(bad)
    assert PASS not in caplog.text and OTHER not in caplog.text
    assert PASS not in str(err.value) and OTHER not in str(err.value)
    assert any("not wrapped" in r.getMessage() for r in caplog.records)
    for path in tmp_path.rglob("*"):
        assert PASS not in path.name and OTHER not in path.name


# --------------------------------------------------------------------------- #
#  Review findings (the independent read of the first build)
# --------------------------------------------------------------------------- #


@posix_only
def test_a_key_file_that_is_a_symbolic_link_is_never_replaced_and_is_reported_as_it_is(
    tmp_path, monkeypatch, caplog
):
    """``os.replace`` would swap the link for a regular file and leave the plaintext key at its target, while
    ``key_protection`` said the wrap was done."""
    key = Ed25519PrivateKey.generate()
    target = tmp_path / "elsewhere.pem"
    target.write_bytes(_plain_pem(key))
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "ed.pem").symlink_to(target)
    _hold(monkeypatch, PASS)
    with caplog.at_level(logging.WARNING):
        s = _signer(keys)
    assert (keys / "ed.pem").is_symlink() and target.read_bytes() == _plain_pem(key)
    assert s.key_protection == "plaintext-0600"
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(key)
    assert any("KeyFileLinked" in r.getMessage() for r in caplog.records)
    assert _pending_left(keys) == []


@posix_only
def test_a_key_file_with_another_hard_link_outside_pending_is_never_replaced(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(_plain_pem(key))
    other = tmp_path / "backup-of-the-key.pem"
    os.link(p, other)
    _hold(monkeypatch, PASS)
    s = _signer(tmp_path)
    assert p.read_bytes() == _plain_pem(key) and other.read_bytes() == _plain_pem(key)
    assert s.key_protection == "plaintext-0600"


@posix_only
def test_an_alias_a_dead_creation_left_in_pending_does_not_stop_the_wrap(tmp_path, monkeypatch):
    """The one extra name that is expected, and swept: a creation killed between its link and its unlink."""
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(_plain_pem(key))
    pending = tmp_path / kf.PENDING
    pending.mkdir()
    os.link(p, pending / "ed.pem.1.2.abc.new")
    _hold(monkeypatch, PASS)
    s = _signer(tmp_path)
    assert _is_wrapped(p) and s.key_protection == "aes256gcm-scrypt"
    assert _pending_left(tmp_path) == [], "the alias of the plaintext key is gone"


def test_a_creation_loser_that_holds_a_passphrase_judges_the_winners_file_like_any_other(
    tmp_path, monkeypatch
):
    """The winner held no passphrase (a tool run) and wrote the plaintext key. The loser used to trust it as it
    was and report the wrap over a plaintext file; it now wraps it, or reports what the file holds."""
    winner = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    real_link = kf.os.link

    def racing(src, dst, *a, **kw):
        kf.write_new(Path(dst), _plain_pem(winner))
        return real_link(src, dst, *a, **kw)

    scope_os(monkeypatch, kf, link=racing)
    _hold(monkeypatch, PASS)
    s = _signer(tmp_path)
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(winner)
    assert _is_wrapped(p) and s.key_protection == "aes256gcm-scrypt"
    assert _pending_left(tmp_path) == []


def test_a_loser_that_cannot_wrap_the_winners_plaintext_file_says_so(tmp_path, monkeypatch):
    winner = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    real_link = kf.os.link

    def racing(src, dst, *a, **kw):
        kf.write_new(Path(dst), _plain_pem(winner))
        return real_link(src, dst, *a, **kw)

    def boom(*_a, **_k):
        raise OSError("disk says no")

    with monkeypatch.context() as m:
        scope_os(m, kf, link=racing)
        scope_os(m, kf, replace=boom)
        _hold(m, PASS)
        s = _signer(tmp_path)
    assert p.read_bytes() == _plain_pem(winner)
    assert s.key_protection == "plaintext-0600"


@pytest.mark.parametrize("what", ["truncated", "public", "garbage"])
def test_a_damaged_or_foreign_pem_is_a_signing_error_naming_the_file(tmp_path, what):
    key = Ed25519PrivateKey.generate()
    if what == "truncated":
        data = _plain_pem(key)[:60]
    elif what == "public":
        data = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    else:
        data = b"-----BEGIN PRIVATE KEY-----\nnot base64 at all !!\n-----END PRIVATE KEY-----\n"
    p = tmp_path / "ed.pem"
    p.write_bytes(data)
    with pytest.raises(SigningError, match="ed.pem is not a readable PEM private key"):
        _signer(tmp_path)
    assert p.read_bytes() == data


def test_losing_the_wrap_race_is_not_a_warning(tmp_path, monkeypatch, caplog):
    """Six callers load one legacy plaintext key at once: one wraps it, five stand down because the file is
    already what they wanted. That is not worth a warning each."""
    key = Ed25519PrivateKey.generate()
    (tmp_path / "ed.pem").write_bytes(_plain_pem(key))
    _hold(monkeypatch, PASS)
    callers = 6
    start = threading.Barrier(callers)
    results: list[str] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            start.wait(timeout=30)
            results.append(_signer(tmp_path).key_protection)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    with caplog.at_level(logging.DEBUG):
        threads = [threading.Thread(target=run) for _ in range(callers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
    assert not errors, errors
    assert results == ["aes256gcm-scrypt"] * callers
    assert _is_wrapped(tmp_path / "ed.pem")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], caplog.text


def test_a_file_that_changed_between_the_read_and_the_copy_is_not_overwritten(
    tmp_path, monkeypatch
):
    """The stand-down depends on the state of the file AT THE READ (``seen``), not on one taken when the copy
    starts: the file changes after it is read and before ``replace_in_place`` begins."""
    key = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(_plain_pem(key))
    _hold(monkeypatch, PASS)
    theirs = signing._wrap(_seed(key), PASS.encode())
    real_parse = signing.parse_ed25519_key
    calls = {"n": 0}

    def parse_then_lose_the_race(path, raw, passphrase):
        out = real_parse(path, raw, passphrase)
        calls["n"] += 1
        if calls["n"] == 1:  # the first read of the file, before anything is replaced
            side = tmp_path / "side"
            side.write_bytes(theirs)
            os.replace(side, p)
        return out

    monkeypatch.setattr(signing, "parse_ed25519_key", parse_then_lose_the_race)
    s = _signer(tmp_path)
    assert p.read_bytes() == theirs
    assert s.key_protection == "aes256gcm-scrypt"


def test_a_file_restored_over_the_key_with_another_key_does_not_change_the_answer_given(
    tmp_path, monkeypatch
):
    """The status read after a stand-down compares keys: a file that now holds some OTHER key says nothing about
    how this signer's key is kept, so the answer already given stands."""
    key = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    p = tmp_path / "ed.pem"
    p.write_bytes(_plain_pem(key))
    _hold(monkeypatch, PASS)
    real_seal = signing.seal_ed25519_key

    def seal_then_restore_another_key(k, pp):
        blob = real_seal(k, pp)
        side = tmp_path / "side"
        side.write_bytes(signing._wrap(_seed(other), pp))
        os.replace(side, p)  # a restore put another install's key here
        return blob

    monkeypatch.setattr(signing, "seal_ed25519_key", seal_then_restore_another_key)
    s = _signer(tmp_path)
    assert bytes.fromhex(s.public_identity().ed25519_pub) == _pub(
        key
    )  # it signs with the key it read
    assert _pub(_opens_with(p, PASS)) == _pub(other)  # and the other install's file is untouched
    assert (
        s.key_protection == "plaintext-0600"
    )  # the answer for the key it holds: it was read as plaintext


# --------------------------------------------------------------------------- #
#  What a restore can call (R454)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("form", ["wrapped", "plaintext", "pkcs8"])
def test_the_public_parser_reads_every_form_with_the_passphrase_it_is_given_not_the_held_one(
    tmp_path, monkeypatch, form
):
    key = Ed25519PrivateKey.generate()
    raw = {
        "wrapped": signing._wrap(_seed(key), PASS.encode()),
        "plaintext": _plain_pem(key),
        "pkcs8": _old_pkcs8(key, PASS),
    }[form]
    _hold(monkeypatch, OTHER)  # what this install holds is not what the file was wrapped under
    got, seen_form = signing.parse_ed25519_key(tmp_path / "ed.pem", raw, PASS.encode())
    assert seen_form == form and _pub(got) == _pub(key)
    if form != "plaintext":
        with pytest.raises(SigningError):
            signing.parse_ed25519_key(tmp_path / "ed.pem", raw, OTHER.encode())


def test_the_public_seal_round_trips_through_the_public_parser(tmp_path):
    key = Ed25519PrivateKey.generate()
    for passphrase, form in ((PASS.encode(), "wrapped"), (None, "plaintext")):
        blob = signing.seal_ed25519_key(key, passphrase)
        got, seen_form = signing.parse_ed25519_key(tmp_path / "ed.pem", blob, passphrase)
        assert seen_form == form and _pub(got) == _pub(key)


class _FakeMldsa:
    """Stands in for the post-quantum backend, so the ML-DSA key file's logic is tested without the library."""

    PUBLIC_KEY_SIZE = 40

    @staticmethod
    def generate_keypair():
        return os.urandom(40), os.urandom(100)


def test_the_mldsa_parser_and_seal_round_trip_and_keep_the_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    pk, sk = _FakeMldsa.generate_keypair()
    p = tmp_path / "ml.key"
    wrapped = signing.seal_mldsa_key(pk, sk, PASS.encode())
    plain = signing.seal_mldsa_key(pk, sk, None)
    assert plain == pk + sk and pk not in wrapped
    assert signing.parse_mldsa_key(p, wrapped, PASS.encode()) == (pk, sk, "wrapped")
    assert signing.parse_mldsa_key(p, plain, None) == (pk, sk, "plaintext")
    # a legacy plaintext key of the exact length still loads under a passphrase, and says it is plaintext
    assert signing.parse_mldsa_key(p, plain, PASS.encode()) == (pk, sk, "plaintext")
    # the two refusals are the ones the signer has always raised, in the same words
    with pytest.raises(SigningError, match="could not be unwrapped with the passphrase held"):
        signing.parse_mldsa_key(p, wrapped, OTHER.encode())
    with pytest.raises(SigningError, match="wrapped but no passphrase is held"):
        signing.parse_mldsa_key(p, wrapped, None)
    with pytest.raises(SigningError):
        signing.parse_mldsa_key(
            p, plain[:-1], PASS.encode()
        )  # a plaintext-looking key of any other length


# --------------------------------------------------------------------------- #
#  The ML-DSA key file, by the same protocol (R484 (1) and (2), go 2026-11-08)
# --------------------------------------------------------------------------- #
#
# Before: the ML-DSA key was written by ``write_bytes`` then ``chmod`` (a window at 0644 under a umask of
# 022), two first callers could each make a pair (the last writer won, orphaning what the first had
# signed), and a pair written in the clear before the passphrase existed stayed in the clear. Now it is
# created and re-wrapped through ``src.custody.keyfile``, as the Ed25519 key is.


@pytest.fixture
def fake_pqc(monkeypatch):
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)


def _hybrid(directory: Path) -> HybridSigner:
    return HybridSigner(ed25519_path=directory / "ed.pem", mldsa_path=directory / "ml.key")


def _wrapped_ed25519_first(directory: Path, monkeypatch) -> None:
    """Make the Ed25519 key already wrapped under PASS, so a test sees only what happens to the ML-DSA file."""
    _hold(monkeypatch, PASS)
    _signer(directory)


@posix_only
@pytest.mark.parametrize("passphrase", [None, PASS])
def test_a_new_mldsa_key_is_made_0600_from_its_first_byte(tmp_path, monkeypatch, fake_pqc, passphrase):
    _hold(monkeypatch, passphrase)
    seen: list[tuple[str, int, int]] = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **kw):
        seen.append((os.fspath(path), flags, mode))
        return real_open(path, flags, mode, *a, **kw)

    scope_os(monkeypatch, kf, open=spy)
    old = os.umask(0o022)
    try:
        s = _hybrid(tmp_path)
    finally:
        os.umask(old)
    creates = [(f, m) for p, f, m in seen if f & os.O_CREAT and "ml.key" in p]
    assert creates, "the ML-DSA key was not created through keyfile"
    assert all(f & os.O_EXCL and m == 0o600 for f, m in creates)
    ml = tmp_path / "ml.key"
    assert stat.S_IMODE(ml.stat().st_mode) == 0o600
    pk, _sk, form = signing.parse_mldsa_key(ml, ml.read_bytes(), passphrase.encode() if passphrase else None)
    assert form == ("wrapped" if passphrase else "plaintext")
    assert s.public_identity().ml_dsa_pub == pk.hex()
    assert _pending_left(tmp_path) == []


def test_two_first_callers_end_with_one_mldsa_pair(tmp_path, monkeypatch, fake_pqc):
    _hold(monkeypatch, PASS)
    callers = 6
    start = threading.Barrier(callers)
    results: list[str | None] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            start.wait(timeout=30)
            results.append(_hybrid(tmp_path).public_identity().ml_dsa_pub)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors, errors
    assert len(results) == callers and len(set(results)) == 1
    ml = tmp_path / "ml.key"
    pk, _sk, form = signing.parse_mldsa_key(ml, ml.read_bytes(), PASS.encode())
    assert form == "wrapped" and results[0] == pk.hex()
    assert _pending_left(tmp_path) == []


def test_the_loser_of_an_mldsa_creation_race_uses_the_winners_pair(tmp_path, monkeypatch, fake_pqc):
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    winner_pk, winner_sk = _FakeMldsa.generate_keypair()
    real_link = kf.os.link

    def racing(src, dst, *a, **kw):
        if Path(dst).name == "ml.key":  # the other caller got there first
            kf.write_new(Path(dst), signing.seal_mldsa_key(winner_pk, winner_sk, PASS.encode()))
        return real_link(src, dst, *a, **kw)

    scope_os(monkeypatch, kf, link=racing)
    s = _hybrid(tmp_path)
    assert s.public_identity().ml_dsa_pub == winner_pk.hex()
    ml = tmp_path / "ml.key"
    assert signing.parse_mldsa_key(ml, ml.read_bytes(), PASS.encode()) == (winner_pk, winner_sk, "wrapped")
    assert _pending_left(tmp_path) == []


def test_a_legacy_plaintext_mldsa_pair_is_wrapped_in_place_and_stays_the_same_pair(
    tmp_path, monkeypatch, fake_pqc
):
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    ml = tmp_path / "ml.key"
    ml.write_bytes(pk + sk)  # what the file was before the store had a passphrase
    s = _hybrid(tmp_path)
    assert signing.parse_mldsa_key(ml, ml.read_bytes(), PASS.encode()) == (pk, sk, "wrapped")
    assert pk not in ml.read_bytes() and sk not in ml.read_bytes()
    assert s.public_identity().ml_dsa_pub == pk.hex()
    assert s.key_protection == "aes256gcm-scrypt"
    assert stat.S_IMODE(ml.stat().st_mode) == 0o600 or os.name == "nt"
    assert _pending_left(tmp_path) == []


def test_a_failed_mldsa_wrap_leaves_the_file_and_says_what_it_holds(tmp_path, monkeypatch, fake_pqc):
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    ml = tmp_path / "ml.key"
    ml.write_bytes(pk + sk)

    def boom(*_a, **_k):
        raise OSError("disk says no")

    scope_os(monkeypatch, kf, replace=boom)
    s = _hybrid(tmp_path)
    assert ml.read_bytes() == pk + sk
    assert s.key_protection == "plaintext-0600"
    assert s.public_identity().ml_dsa_pub == pk.hex()
    assert _pending_left(tmp_path) == []
    # the next load tries again, and this time nothing is in the way
    monkeypatch.undo()
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)
    _hold(monkeypatch, PASS)
    assert _hybrid(tmp_path).key_protection == "aes256gcm-scrypt"
    assert signing.parse_mldsa_key(ml, ml.read_bytes(), PASS.encode()) == (pk, sk, "wrapped")


@pytest.mark.parametrize("bad", ["another_pair", "same_public_other_secret", "not_wrapped"])
def test_an_mldsa_copy_that_is_not_the_same_wrapped_pair_never_replaces_the_file(
    tmp_path, monkeypatch, fake_pqc, bad
):
    """The check runs on the copy before anything is replaced. ``not_wrapped`` is the case a key comparison
    alone would pass: a copy left in the clear would be put in place and reported as the wrap."""
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    ml = tmp_path / "ml.key"
    ml.write_bytes(pk + sk)
    other_pk, other_sk = _FakeMldsa.generate_keypair()
    if bad == "another_pair":
        monkeypatch.setattr(signing, "seal_mldsa_key", lambda _pk, _sk, pp: signing._wrap(other_pk + other_sk, pp))
    elif bad == "same_public_other_secret":  # a copy cut or mixed up: the public half alone proves nothing
        monkeypatch.setattr(signing, "seal_mldsa_key", lambda pk_, _sk, pp: signing._wrap(pk_ + other_sk, pp))
    else:
        monkeypatch.setattr(signing, "seal_mldsa_key", lambda pk_, sk_, _pp: pk_ + sk_)
    s = _hybrid(tmp_path)
    assert ml.read_bytes() == pk + sk
    assert s.key_protection == "plaintext-0600"
    assert s.public_identity().ml_dsa_pub == pk.hex()
    assert _pending_left(tmp_path) == []


def test_an_mldsa_wrap_another_caller_won_is_reported_as_the_wrap(tmp_path, monkeypatch, fake_pqc):
    """This caller's replace stood down because another caller wrapped the file meanwhile: the answer is what
    the file holds NOW (the wrap), not what it held when this caller read it."""
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    ml = tmp_path / "ml.key"
    ml.write_bytes(pk + sk)
    real = kf.replace_in_place

    def the_other_caller_won(*a, **kw):
        assert real(*a, **kw) is True  # the file is wrapped, by "someone else"
        return False

    monkeypatch.setattr(kf, "replace_in_place", the_other_caller_won)
    s = _hybrid(tmp_path)
    assert signing.parse_mldsa_key(ml, ml.read_bytes(), PASS.encode()) == (pk, sk, "wrapped")
    assert s.key_protection == "aes256gcm-scrypt"


def test_an_mldsa_file_restored_over_with_another_pair_does_not_change_the_answer_given(
    tmp_path, monkeypatch, fake_pqc
):
    """A restore lands another install's wrapped pair while this caller's replace stands down: that file says
    nothing about how THIS signer's pair is kept, so the answer stays what this caller read."""
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    ml = tmp_path / "ml.key"
    ml.write_bytes(pk + sk)
    other_pk, other_sk = _FakeMldsa.generate_keypair()

    def restored_meanwhile(*_a, **_kw):
        ml.write_bytes(signing.seal_mldsa_key(other_pk, other_sk, PASS.encode()))
        return False

    monkeypatch.setattr(kf, "replace_in_place", restored_meanwhile)
    s = _hybrid(tmp_path)
    assert s.public_identity().ml_dsa_pub == pk.hex()
    assert s.key_protection == "plaintext-0600"


def _restore_on_first_parse(monkeypatch, ml: Path, restored: bytes) -> None:
    """A restore lands ``restored`` at ``ml`` right after this caller's first read of it, before anything is
    replaced: the stand-down must depend on the file's state AT THE READ."""
    real_parse = signing.parse_mldsa_key
    calls = {"n": 0}

    def parse_then_lose_the_race(path, raw, passphrase):
        out = real_parse(path, raw, passphrase)
        calls["n"] += 1
        if calls["n"] == 1:
            side = ml.parent / "side"
            side.write_bytes(restored)
            os.replace(side, ml)
        return out

    monkeypatch.setattr(signing, "parse_mldsa_key", parse_then_lose_the_race)


def test_an_mldsa_file_that_changed_between_the_read_and_the_copy_is_not_overwritten(
    tmp_path, monkeypatch, fake_pqc
):
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    ml = tmp_path / "ml.key"
    ml.write_bytes(pk + sk)
    other_pk, other_sk = _FakeMldsa.generate_keypair()
    restored = signing.seal_mldsa_key(other_pk, other_sk, PASS.encode())
    _restore_on_first_parse(monkeypatch, ml, restored)
    _hybrid(tmp_path)
    assert ml.read_bytes() == restored  # never this caller's stale pair over the restored one


def test_a_creation_loser_does_not_overwrite_a_file_restored_after_it_read_the_winners(
    tmp_path, monkeypatch, fake_pqc
):
    """The loser's ``seen`` is the state of the WINNER'S file as it read it, not one taken later."""
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    ml = tmp_path / "ml.key"
    winner_pk, winner_sk = _FakeMldsa.generate_keypair()
    real_link = kf.os.link

    def racing(src, dst, *a, **kw):
        if Path(dst).name == "ml.key":  # a winner with no passphrase got there first, in the clear
            kf.write_new(Path(dst), winner_pk + winner_sk)
        return real_link(src, dst, *a, **kw)

    scope_os(monkeypatch, kf, link=racing)
    other_pk, other_sk = _FakeMldsa.generate_keypair()
    restored = signing.seal_mldsa_key(other_pk, other_sk, PASS.encode())
    _restore_on_first_parse(monkeypatch, ml, restored)
    _hybrid(tmp_path)
    assert ml.read_bytes() == restored


def test_with_no_passphrase_a_plaintext_pair_is_loaded_and_nothing_is_written(
    tmp_path, monkeypatch, fake_pqc, caplog
):
    _hold(monkeypatch, None)
    _signer(tmp_path)  # the Ed25519 key, plaintext
    pk, sk = _FakeMldsa.generate_keypair()
    ml = tmp_path / "ml.key"
    ml.write_bytes(pk + sk)
    created: list[str] = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **kw):
        if flags & os.O_CREAT:
            created.append(os.fspath(path))
        return real_open(path, flags, mode, *a, **kw)

    scope_os(monkeypatch, kf, open=spy)
    with caplog.at_level(logging.DEBUG, logger="src.custody"):
        s = _hybrid(tmp_path)
    assert created == []  # no private copy of the pair, not even one removed again
    assert ml.read_bytes() == pk + sk
    assert s.key_protection == "plaintext-0600"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert _pending_left(tmp_path) == []


def test_a_wrap_that_cannot_land_pays_no_extra_derivation_on_each_load(tmp_path, monkeypatch, fake_pqc):
    """A symbolic link is refused before the copy is sealed, and the stand-down reads the unchanged file
    without parsing it again: a link left in place is met on every load, and each scrypt is about 80 ms."""
    keys = tmp_path / "keys"
    keys.mkdir()
    _wrapped_ed25519_first(keys, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    target = tmp_path / "elsewhere.key"
    target.write_bytes(pk + sk)
    (keys / "ml.key").symlink_to(target)
    counts = {"seal": 0, "parse": 0}
    real_seal, real_parse = signing.seal_mldsa_key, signing.parse_mldsa_key

    def seal(*a, **kw):
        counts["seal"] += 1
        return real_seal(*a, **kw)

    def parse(*a, **kw):
        counts["parse"] += 1
        return real_parse(*a, **kw)

    monkeypatch.setattr(signing, "seal_mldsa_key", seal)
    monkeypatch.setattr(signing, "parse_mldsa_key", parse)
    s = _hybrid(keys)
    assert counts == {"seal": 0, "parse": 1}
    assert s.key_protection == "plaintext-0600"
    assert target.read_bytes() == pk + sk


@posix_only
def test_a_hard_link_made_while_the_copy_is_sealed_still_stops_the_replace(tmp_path, monkeypatch, fake_pqc, caplog):
    """The early refusal saves the derivation; the late one is what holds when a second name appears while
    the copy is being made (the plaintext pair would stay readable at it)."""
    _wrapped_ed25519_first(tmp_path, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    ml = tmp_path / "ml.key"
    ml.write_bytes(pk + sk)
    elsewhere = tmp_path / "another-name"
    real_seal = signing.seal_mldsa_key

    def seal_while_someone_links(*a, **kw):
        os.link(ml, elsewhere)
        return real_seal(*a, **kw)

    monkeypatch.setattr(signing, "seal_mldsa_key", seal_while_someone_links)
    with caplog.at_level(logging.WARNING):
        s = _hybrid(tmp_path)
    assert ml.read_bytes() == pk + sk and elsewhere.read_bytes() == pk + sk
    assert s.key_protection == "plaintext-0600"
    assert any("KeyFileLinked" in r.getMessage() for r in caplog.records)
    assert _pending_left(tmp_path) == []


def test_an_mldsa_key_file_that_is_a_symbolic_link_is_never_replaced(tmp_path, monkeypatch, fake_pqc, caplog):
    keys = tmp_path / "keys"
    keys.mkdir()
    _wrapped_ed25519_first(keys, monkeypatch)
    pk, sk = _FakeMldsa.generate_keypair()
    target = tmp_path / "elsewhere.key"
    target.write_bytes(pk + sk)
    (keys / "ml.key").symlink_to(target)
    with caplog.at_level(logging.WARNING):
        s = _hybrid(keys)
    assert (keys / "ml.key").is_symlink() and target.read_bytes() == pk + sk
    assert s.key_protection == "plaintext-0600"
    assert any("KeyFileLinked" in r.getMessage() and "ML-DSA" in r.getMessage() for r in caplog.records)
    assert PASS not in caplog.text
    assert _pending_left(keys) == []


# --------------------------------------------------------------------------- #
#  A burst of constructions
# --------------------------------------------------------------------------- #


def test_scrypt_runs_at_most_once_per_core_at_a_time(monkeypatch):
    """Fifty callers opening a custody log at once held fifty derivations (32 MiB each) at the same time, 1.3 GiB
    measured, for no gain in wall time. The bound is the machine's cores."""
    cores = max(1, getattr(os, "process_cpu_count", os.cpu_count)() or 1)
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    class FakeScrypt:
        def __init__(self, **_kw):
            pass

        def derive(self, _passphrase):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.02)
            with lock:
                state["now"] -= 1
            return b"k" * 32

    monkeypatch.setattr(signing, "Scrypt", FakeScrypt)
    threads = [
        threading.Thread(target=signing._wrap, args=(b"x" * 32, b"pass"))
        for _ in range(cores * 6 + 3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert 1 <= state["peak"] <= cores
