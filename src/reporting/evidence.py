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


# --------------------------------------------------------------------------- #
# Signing keys (persistent under the data dir)
# --------------------------------------------------------------------------- #


def _default_key_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "keys" / "evidence_ed25519.pem"


def load_or_create_signing_key(path: Path | None = None) -> Ed25519PrivateKey:
    """Load the persistent Ed25519 signing key, creating it on first use."""
    path = path or _default_key_path()
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return key


def public_key_hex(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return raw.hex()


# --------------------------------------------------------------------------- #
# Bundle construction
# --------------------------------------------------------------------------- #


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
