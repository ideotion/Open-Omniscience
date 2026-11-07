"""
Defensible, tamper-evident evidence bundles (chain of custody).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Turns the "legal admissibility" claim into something real (PRODUCT_SYNTHESIS §8):
an exported bundle of selected articles, each with its provenance and content
hash, bound together by a Merkle root and an Ed25519 signature over a canonical
serialization. A third party can verify integrity offline with only the bundle
and the public key -- no trust in this tool required.

Ed25519 (via `cryptography`) is used rather than GPG so verification is fully
self-contained and reproducible (no external gpg binary / keyring needed). The
Merkle root reuses the audited src/crypto/merkle_tree implementation.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from src.crypto.merkle_tree import compute_merkle_root

BUNDLE_VERSION = "oo-evidence-1"

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Signing keys (persistent under the data dir)
# --------------------------------------------------------------------------- #


def _default_key_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "keys" / "evidence_ed25519.pem"


class EvidenceKeyError(ValueError):
    """The evidence signing key file is there but cannot be used to sign.

    A ``ValueError`` (every caller that already catches one keeps working), with its own type so a
    caller that wants to say WHY can. The words never carry the passphrase: they name the file and
    which of the few causes it is.
    """


def _wrap_passphrase() -> bytes | None:
    """The passphrase the evidence key is wrapped under, as bytes; ``None`` when none is held.

    The custody signer's own rule, imported and not copied (one secret, one helper): the
    ``OO_KEY_PASSPHRASE`` variable wins, else THE database passphrase the unlocked session holds.
    No passphrase held (a plaintext store, a tool run, a test) means the key is written and read
    unwrapped, exactly as before this existed.
    """
    from src.custody.signing import SigningError
    from src.custody.signing import _passphrase as held_key_passphrase
    from src.monitoring.secret_scrub import UNENCODABLE_PASSPHRASE

    try:
        return held_key_passphrase()
    except SigningError:
        # the passphrase cannot be written as UTF-8: fixed words, raised after the handler so the
        # chain carries nothing (the held exception's context names the character and the text)
        pass
    raise EvidenceKeyError(UNENCODABLE_PASSPHRASE)


_PEM_START = b"-----BEGIN"


def _parse_key(path: Path, raw: bytes, passphrase: bytes | None) -> tuple[Ed25519PrivateKey, bool]:
    """``(key, legacy_plaintext)`` from the bytes of the key file; never writes.

    Two forms are written. A plaintext PKCS8 PEM (no passphrase held, or a key from before this
    wrapped anything: ``legacy_plaintext`` is True when a passphrase IS held, and the caller that is
    allowed to may wrap it in place). Or, under a passphrase, the custody signer's wrap of the 32
    key bytes: ``salt || nonce || AES-256-GCM`` under a scrypt key, which is not a PEM. A wrapped
    file with no passphrase held, or one the held passphrase does not open, raises
    :class:`EvidenceKeyError` naming which; neither is ever a reason to generate another key.
    """
    if not raw.strip():
        raise EvidenceKeyError(
            f"{path} is empty (a creation that was cut short). Nothing is replaced for you: delete "
            "it and a new key is made the next time one is needed."
        )
    if _PEM_START in raw:
        # anywhere, not only first: OpenSSL writes a "Bag Attributes" preamble and an editor can
        # add a byte-order mark, and ``load_pem_private_key`` reads both. A wrapped blob is random
        # bytes, which hold these ten of them with a chance of about 2**-72.
        try:
            # load_pem_private_key returns whatever the FILE holds. This app only ever
            # writes Ed25519 here, but a foreign key placed at this path used to be
            # returned as-is and fail later, somewhere else, as a signing error.
            pem_key = serialization.load_pem_private_key(raw, password=None)
        except TypeError:
            pem_key = None  # a PEM that is itself password-protected
        if pem_key is None:
            raise EvidenceKeyError(
                f"{path} is a password-protected PEM file, which is not a form this app writes for "
                "the evidence key. Nothing was replaced; move it aside to have a new key made."
            )
        if not isinstance(pem_key, Ed25519PrivateKey):
            raise EvidenceKeyError(
                f"{path} does not hold an Ed25519 private key (found "
                f"{type(pem_key).__name__}); evidence bundles are signed with Ed25519."
            )
        return pem_key, passphrase is not None
    if passphrase is None:
        raise EvidenceKeyError(
            f"{path} is wrapped under the store passphrase and none is held, so nothing can be "
            "signed while the store is locked; unlock it and try again."
        )
    from src.custody.signing import _unwrap as held_unwrap

    key: Ed25519PrivateKey | None = None
    try:
        key = Ed25519PrivateKey.from_private_bytes(held_unwrap(raw, passphrase))
    except Exception:  # noqa: BLE001 - the tag check, a short blob and a wrong-length seed all end here
        # Nothing the exception says helps and none of it is passed on. A wrong passphrase and a
        # damaged file cannot be told apart from here.
        key = None
    if key is None:
        raise EvidenceKeyError(
            f"{path} is wrapped under a passphrase other than the one held (a backup restored from "
            "another install carries its key as that install wrapped it), or the file is damaged. "
            "Nothing was replaced; restore the passphrase it was wrapped under, or move the file "
            "aside to have a new key made (bundles signed by the old key stay verifiable against "
            "its public key)."
        )
    return key, False


def _write_new(path: Path, data: bytes) -> None:
    """Create ``path`` (it must not exist), mode 0600 from the first byte, and flush it to disk.

    ``O_EXCL`` refuses a file that is already there (``FileExistsError``) and the mode is part of
    the creation, so there is no moment in which the key is readable by another account (the old
    ``write_bytes`` then ``chmod`` left one under a umask of 022).
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _seal(key: Ed25519PrivateKey, passphrase: bytes | None) -> bytes:
    """The bytes of the key file: the plaintext PEM with no passphrase, else the wrap of the key.

    The wrap is the custody signer's own (``_wrap``: scrypt with N = 2**15, then AES-256-GCM), not
    PKCS8's ``BestAvailableEncryption``: that one derives its key with PBKDF2-HMAC-SHA256 at 2048
    rounds, 0.3 ms a guess, which would make this file the cheapest way for whoever copied the data
    folder to test a guess at the database passphrase, which SQLCipher prices at 170 ms.
    """
    if passphrase:
        from src.custody.signing import _wrap as held_wrap

        seed = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        return held_wrap(seed, passphrase)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


#: Where the key's temporary files live: a subdirectory of the key's own directory, so a rename or a
#: link into place stays on one file system, and so the backups, which list the FILES directly in
#: ``keys/``, never pick one up (a temporary file is not part of the identity).
_PENDING = ".pending"


def _private_name(path: Path, kind: str) -> Path:
    """A temporary file name no other caller can hold: this host's process and thread, a random token.

    The token is what makes it true across machines too (two containers on one data volume can both
    be process 1 with the same thread number). A name is removed only by the caller that made it:
    a name shared by every caller let one delete another's finished copy and rename its own empty
    file over the key.
    """
    pending = path.parent / _PENDING
    pending.mkdir(mode=0o700, exist_ok=True)
    token = secrets.token_hex(6)
    return pending / f"{path.name}.{os.getpid()}.{threading.get_ident()}.{token}.{kind}"


def _write_private(path: Path, kind: str, data: bytes) -> Path:
    """Write ``data`` to a new private file for ``path`` and return its name; a failure leaves none.

    The directory is removed again when nothing is in it (:func:`_drop_pending`), and another caller
    can do that between this one's ``mkdir`` and its create: three tries cover it.
    """
    for _attempt in range(3):
        tmp = _private_name(path, kind)
        try:
            _write_new(tmp, data)
        except FileNotFoundError:
            continue
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise
        return tmp
    raise FileNotFoundError(
        f"{path.parent / _PENDING}: kept disappearing while a key file was written"
    )


def _drop_pending(path: Path) -> None:
    """Remove ``keys/.pending`` when it is empty, so the directory is not left in the keys listing
    (the encryption attestation names every entry of it). Refused by the file system while any
    caller's file is in it, which is exactly when it must stay."""
    with contextlib.suppress(OSError):
        (path.parent / _PENDING).rmdir()


def _drop_aliases(path: Path, old: os.stat_result) -> None:
    """Remove the names in ``keys/.pending`` that are hard links to the file ``path`` just replaced.

    A creation that died between its ``os.link`` and the removal of its private name leaves that
    name as a second name for the key file's own bytes, and when those bytes were the plaintext key
    the replacement above would leave the key readable there for good, in a folder nothing sweeps.
    A name is matched by file identity (device and inode), never by its text, so only an alias of
    the very file that was replaced is removed: a caller's file that is not yet linked has an inode
    of its own. A caller whose name goes this way finds it missing at its own removal, which it
    allows. Best effort: the wrapped file is already in place, and a leftover is the stated limit.
    """
    if old.st_nlink < 2 or not old.st_ino:
        return
    with contextlib.suppress(OSError), os.scandir(path.parent / _PENDING) as entries:
        for entry in entries:
            try:
                # by path: ``DirEntry.stat()`` answers 0 for the device, inode and link count on
                # Windows, where a name would then never match and the sweep would do nothing
                st = os.stat(entry.path, follow_symlinks=False)
                if (st.st_dev, st.st_ino) == (old.st_dev, old.st_ino):
                    os.unlink(entry.path)
            except OSError:
                continue


def _identity(st: os.stat_result) -> tuple[int, int, int, int]:
    """Which file, and which state of it: device, inode, size and modification time."""
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _wrap_in_place(
    path: Path, key: Ed25519PrivateKey, passphrase: bytes, seen: os.stat_result | None = None
) -> bool:
    """Replace a legacy plaintext key file by the SAME key wrapped under ``passphrase``.

    The key never changes (a new key would orphan every bundle already signed, whose public half is
    in shipped evidence). The wrapped copy is written to a private file of this caller's, read back
    with the passphrase and compared with the original public key BEFORE it replaces anything, so a
    failure at any step leaves the original file exactly as it was. ``seen`` is the state of the
    file when ``key`` was read from it (``fstat`` of the open file); the wrapped copy replaces it
    only if the file is still exactly that, so a key erased, restored over or wrapped by another
    caller in the meantime is never replaced by this caller's copy of the key it read earlier.
    Returns whether the file was replaced. Never raises: signing goes on with the key it holds, and
    the next load tries again. The log names the exception CLASS only (the passphrase is in scope).
    """
    tmp: Path | None = None
    try:
        if seen is None:
            seen = os.stat(path)
        tmp = _write_private(path, "rewrap", _seal(key, passphrase))
        back, _legacy = _parse_key(path, tmp.read_bytes(), passphrase)
        if public_key_hex(back) != public_key_hex(key):
            raise EvidenceKeyError("the wrapped copy does not hold the same key")
        old = os.stat(path)
        if _identity(old) != _identity(seen):
            raise EvidenceKeyError("the key file changed while the wrapped copy was made")
        os.replace(tmp, path)
        _drop_aliases(path, old)
        return True
    except Exception as exc:  # noqa: BLE001 - best effort by design; the original file is untouched
        log.warning(
            "evidence key not wrapped under the passphrase this time (%s)", type(exc).__name__
        )
        if tmp is not None:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        return False
    finally:
        _drop_pending(path)


def _create_new(path: Path, data: bytes) -> None:
    """Create ``path`` (it must not exist) holding ``data``, so that no reader ever sees it half written.

    The bytes go to a private file first (``O_EXCL``, 0600, flushed), and ``os.link`` then makes
    the key file appear all at once; it is refused with ``FileExistsError`` when another caller got
    there first, which is the one answer that means "load theirs". A file system that has no hard
    links (a FAT or exFAT external drive), or one where the private file cannot be made, falls back
    to an exclusive create in place; there a reader can meet the file between its create and its
    write, which :func:`_read_settled` waits out.
    """
    try:
        tmp = _write_private(path, "new", data)
    except OSError:
        _write_new(path, data)
        return
    try:
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:
            _write_new(path, data)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        _drop_pending(path)


def _read_once(path: Path) -> tuple[bytes, os.stat_result]:
    """The bytes of the file and its state (``fstat`` of the same open file), read together."""
    with path.open("rb") as fh:
        return fh.read(), os.fstat(fh.fileno())


def _read_settled(path: Path) -> tuple[bytes, os.stat_result]:
    """The bytes of the key file and its state, waiting a moment if it is there and still empty.

    An empty key file is never a key: it is another caller's create that has not been written yet
    (only on a file system without hard links, see :func:`_create_new`). Five short looks cover that
    and nothing else; a file that stays empty is returned empty and fails as the unreadable key it is.
    """
    raw, seen = _read_once(path)
    for _ in range(5):
        if raw:
            break
        time.sleep(0.02)
        raw, seen = _read_once(path)
    return raw, seen


def load_or_create_signing_key(path: Path | None = None) -> Ed25519PrivateKey:
    """Load the persistent Ed25519 signing key, creating it on first use.

    On a store with a passphrase held the key file is WRAPPED under it (the custody signer's wrap
    of the raw key: scrypt, then AES-256-GCM; not PKCS8, see :func:`_seal`), so a copied data folder
    does not let its holder sign as this install. A legacy
    plaintext key is wrapped in place on its first load under a passphrase. With no passphrase
    held the file is plaintext, as before. A wrapped key that cannot be opened raises
    :class:`EvidenceKeyError`; nothing is ever regenerated over an existing file.
    """
    path = path or _default_key_path()
    passphrase = _wrap_passphrase()
    try:
        raw, seen = _read_settled(path)
    except FileNotFoundError:
        key = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _create_new(path, _seal(key, passphrase))
        except FileExistsError:
            # another caller created it between our look and our create: ONE key, theirs
            return _parse_key(path, _read_settled(path)[0], passphrase)[0]
        return key
    key, legacy_plaintext = _parse_key(path, raw, passphrase)
    if legacy_plaintext and passphrase is not None:
        _wrap_in_place(path, key, passphrase, seen)
    return key


def existing_public_key_hex(path: Path | None = None) -> str | None:
    """The public half of the signing key IF one exists already, else None.

    The review screen before an export needs to say which key WILL sign; it must not create
    one to say so (a review that changes the install is not a review), so this never writes
    (it does not even wrap a legacy plaintext key: that is the export's job). A wrapped key is
    read with the passphrase the session holds; an unreadable, foreign or unopenable key file
    reads as None here and fails loudly at export time, in ``load_or_create_signing_key``,
    where a person is waiting on the outcome.
    """
    path = path or _default_key_path()
    try:
        # read and parse only: ``load_or_create_signing_key`` would GENERATE a key if the file
        # vanished between an exists() check and its read, and a review must never do that
        key, _legacy = _parse_key(path, path.read_bytes(), _wrap_passphrase())
    except Exception:  # noqa: BLE001 - missing, unreadable, foreign or unopenable all read as "no key"
        return None
    return public_key_hex(key)


def signing_key_state(path: Path | None = None) -> tuple[str, str | None]:
    """``(state, public key hex)`` for the review screen; never writes.

    ``state`` is ``"none"`` (no key file yet: export creates one), ``"ok"`` (a readable
    Ed25519 key) or ``"unreadable"`` (a file is there but export cannot use it, so the review
    must not promise a key is created: it is not, and saving fails).
    """
    path = path or _default_key_path()
    if not path.exists():
        return "none", None
    pub = existing_public_key_hex(path)
    return ("ok", pub) if pub is not None else ("unreadable", None)


def public_key_hex(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return raw.hex()


# --------------------------------------------------------------------------- #
# Bundle construction
# --------------------------------------------------------------------------- #


#: The fields of one evidence item, in the order a reader sees them. The review screen
#: before an export lists THESE, so what it promises and what ``_article_item`` writes are
#: one list (tests/test_evidence_review.py asserts they agree). The article's TEXT is not
#: among them: the item carries the SHA-256 of the text, never the text.
ITEM_FIELDS = (
    "id",
    "url",
    "canonical_url",
    "source_id",
    "title",
    "published_at",
    "stored_hash",
    "content_sha256",
)


def _article_item(article) -> dict:
    """One evidence item: provenance + a content hash recomputed from the stored text."""
    content_sha256 = hashlib.sha256((article.content or "").encode("utf-8")).hexdigest()
    return {
        "id": article.id,
        "url": article.url,
        "canonical_url": article.canonical_url,
        "source_id": article.source_id,
        "title": article.title,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "stored_hash": article.hash,
        "content_sha256": content_sha256,
    }


def canonical_bytes(payload: dict) -> bytes:
    """Deterministic serialization used for hashing/signing (sorted keys, no spaces)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _leaf(item: dict) -> str:
    """Merkle leaf = hash of the ENTIRE canonical item, so every provenance field
    (url, canonical_url, source_id, published_at, stored_hash, content_sha256) is
    covered by the Merkle root -- not just the content hash."""
    return hashlib.sha256(canonical_bytes(item)).hexdigest()


def build_manifest(articles, *, case_name: str | None = None) -> dict:
    """Build the unsigned manifest (items + Merkle root + metadata)."""
    items = [_article_item(a) for a in articles]
    leaves = [_leaf(it) for it in items]
    merkle_root = compute_merkle_root(leaves) if leaves else None
    return {
        "bundle_version": BUNDLE_VERSION,
        "case_name": case_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "item_count": len(items),
        "merkle_root": merkle_root,
        "items": items,
    }


def sign_manifest(manifest: dict, key: Ed25519PrivateKey) -> dict:
    """Return a signed bundle: {manifest, signature, public_key, algorithm}."""
    signature = key.sign(canonical_bytes(manifest)).hex()
    return {
        "manifest": manifest,
        "signature": signature,
        "public_key": public_key_hex(key),
        "algorithm": "ed25519",
    }


def build_signed_bundle(articles, key: Ed25519PrivateKey, *, case_name: str | None = None) -> dict:
    return sign_manifest(build_manifest(articles, case_name=case_name), key)


# --------------------------------------------------------------------------- #
# Independent verification (no app/DB needed -- just the bundle + crypto)
# --------------------------------------------------------------------------- #


def verify_bundle(bundle: dict, *, trusted_public_key: str | None = None) -> tuple[bool, str]:
    """Verify a bundle's Merkle root and Ed25519 signature.

    Returns (ok, reason). Recomputes the Merkle root from the full items (detecting
    any tampered field) and checks the signature over the manifest.

    IMPORTANT (chain of custody): a valid signature only proves "signed by the key
    embedded in the bundle". An attacker can tamper, re-sign with their OWN key, and
    swap in their public key. To prove the bundle came from a specific signer, pass
    ``trusted_public_key`` (the signer's known/pinned public key); verification then
    requires the bundle's key to match it. Without it, the result note says the key
    is unpinned.
    """
    manifest = bundle.get("manifest")
    if not manifest:
        return False, "no manifest"

    bundle_key = bundle.get("public_key")
    if trusted_public_key is not None and bundle_key != trusted_public_key:
        return False, "signed by an untrusted key (does not match the pinned public key)"

    # 1. Recompute the Merkle root from the full items as presented.
    leaves = [_leaf(it) for it in manifest.get("items", [])]
    recomputed = compute_merkle_root(leaves) if leaves else None
    if recomputed != manifest.get("merkle_root"):
        return False, "merkle root mismatch (an item was altered/added/removed)"

    # 2. Verify the signature over the canonical manifest bytes.
    # A missing/non-string public key already reached the same verdict via the
    # TypeError that bytes.fromhex raises below; checking it here reports the same
    # thing without relying on an exception to classify it. Placed AFTER the Merkle
    # step so a bundle that is broken in both ways still reports the Merkle failure
    # first, exactly as before.
    if not isinstance(bundle_key, str):
        return False, "malformed signature or public key"
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(bundle_key))
        pub.verify(bytes.fromhex(bundle["signature"]), canonical_bytes(manifest))
    except (KeyError, ValueError, TypeError):
        return False, "malformed signature or public key"
    except InvalidSignature:
        return False, "signature does not match (manifest altered or wrong key)"

    if trusted_public_key is None:
        return (
            True,
            f"ok (signed by unpinned key {bundle_key[:16]}...; pin the key to prove provenance)",
        )
    return True, "ok (signature valid and key matches the pinned trusted key)"
