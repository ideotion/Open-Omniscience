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

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from src.crypto.merkle_tree import compute_merkle_root
from src.custody import keyfile

BUNDLE_VERSION = "oo-evidence-1"


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
        unreadable = False
        try:
            # load_pem_private_key returns whatever the FILE holds. This app only ever
            # writes Ed25519 here, but a foreign key placed at this path used to be
            # returned as-is and fail later, somewhere else, as a signing error.
            pem_key = serialization.load_pem_private_key(raw, password=None)
        except TypeError:
            pem_key = None  # a PEM that is itself password-protected
        except ValueError:
            pem_key = None
            unreadable = True  # truncated, or a PEM of another kind (a public key, a certificate)
        if unreadable:
            raise EvidenceKeyError(
                f"{path} is not a readable PEM private key (damaged, cut short, or another kind of "
                "key file). Nothing was replaced; move it aside to have a new key made."
            )
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


def _wrap_in_place(
    path: Path, key: Ed25519PrivateKey, passphrase: bytes, seen: os.stat_result | None = None
) -> bool:
    """Replace a legacy plaintext key file by the SAME key wrapped under ``passphrase``.

    The key never changes (a new key would orphan every bundle already signed, whose public half is
    in shipped evidence). How the copy is made, checked and swapped in is
    :func:`src.custody.keyfile.replace_in_place`: the wrapped copy is read back with the passphrase
    and compared with the original public key BEFORE it replaces anything, and only lands if the
    file is still the one ``seen`` describes. Returns whether the file was replaced. Never raises:
    signing goes on with the key it holds, and the next load tries again.
    """

    def same_key(blob: bytes) -> None:
        back, _legacy = _parse_key(path, blob, passphrase)
        if public_key_hex(back) != public_key_hex(key):
            raise EvidenceKeyError("the wrapped copy does not hold the same key")

    return keyfile.replace_in_place(
        path, lambda: _seal(key, passphrase), same_key, seen, "evidence key"
    )


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
        raw, seen = keyfile.read_settled(path)
    except FileNotFoundError:
        key = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            keyfile.create_new(path, _seal(key, passphrase))
        except FileExistsError:
            # another caller created it between our look and our create: ONE key, theirs, judged like
            # any file found there (a caller with no passphrase may have made it plaintext)
            raw, seen = keyfile.read_settled(path)
        else:
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
