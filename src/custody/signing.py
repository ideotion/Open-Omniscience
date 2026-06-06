"""
Honest hybrid (classical + post-quantum) signatures for chain of custody.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the signing primitive behind the custody log and (optionally) evidence
bundles. It combines a classical **Ed25519** signature with a post-quantum
**ML-DSA** (FIPS 204, the standardised successor to CRYSTALS-Dilithium)
signature so that a recorded custody chain stays verifiable even against a future
adversary with a quantum computer ("harvest now, decrypt later").

The design follows two non-negotiables of this project (PRODUCT_SYNTHESIS §3):

1. **Honest labels.** A signature is labelled with *exactly* the algorithms that
   were actually used. If the post-quantum library is not installed we sign with
   Ed25519 alone and label the result ``"ed25519"`` -- never ``"hybrid"``. The
   code can never claim quantum resistance it did not produce.

2. **Hybrid means AND, not OR.** A signature labelled ``"hybrid"`` verifies only
   if **both** the Ed25519 *and* the ML-DSA components verify. (A naive scheme
   that accepts *either* component is worthless: once Ed25519 is broken by a
   quantum adversary, a forged Ed25519 signature alone would pass even though a
   sound ML-DSA signature is attached.) A verifier that cannot check the
   post-quantum half returns a clear *failure*, never a silent pass.

Private keys live under the data dir. They are encrypted at rest when a
passphrase is provided (``OO_KEY_PASSPHRASE``); without one they are written
0600 in the clear and ``key_protection`` reports ``"plaintext-0600"`` so the
operator is never misled about how their keys are stored.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# --------------------------------------------------------------------------- #
# Post-quantum backend (optional, import-guarded)
# --------------------------------------------------------------------------- #
# Current pqcrypto (>=0.3) exposes the standardised ML-DSA family. We default to
# ML-DSA-65 (NIST security category 3, ~AES-192) to mirror the original
# "Dilithium3" intent. Older "dilithium3" module names are gone, so we bind to
# the real, current API only.
_MLDSA_VARIANT = "ml_dsa_65"
try:  # pragma: no cover - exercised indirectly; availability is environment-dependent
    from pqcrypto.sign import ml_dsa_65 as _mldsa  # type: ignore

    PQC_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means "no PQC here"
    _mldsa = None  # type: ignore
    PQC_AVAILABLE = False


class SigningError(RuntimeError):
    """Raised when signing cannot proceed (e.g. a requested algorithm is absent)."""


# --------------------------------------------------------------------------- #
# Key paths / at-rest protection
# --------------------------------------------------------------------------- #

def _keys_dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "keys"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _passphrase() -> Optional[bytes]:
    p = os.getenv("OO_KEY_PASSPHRASE")
    return p.encode("utf-8") if p else None


def _wrap(plaintext: bytes, passphrase: bytes) -> bytes:
    """Encrypt key material with AES-256-GCM under a scrypt-derived key.

    Layout: ``salt(16) || nonce(12) || ciphertext+tag``. scrypt parameters are
    embedded implicitly (fixed, conservative) -- this is local at-rest protection
    for a single user, not an interoperable key format.
    """
    salt = os.urandom(16)
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return salt + nonce + ct


def _unwrap(blob: bytes, passphrase: bytes) -> bytes:
    salt, nonce, ct = blob[:16], blob[16:28], blob[28:]
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase)
    return AESGCM(key).decrypt(nonce, ct, None)


# --------------------------------------------------------------------------- #
# Hybrid signer
# --------------------------------------------------------------------------- #

@dataclass
class PublicIdentity:
    """The public half of a signer -- everything a third party needs to verify."""

    ed25519_pub: str  # hex
    ml_dsa_variant: Optional[str]  # e.g. "ml_dsa_65" or None
    ml_dsa_pub: Optional[str]  # hex or None

    def to_dict(self) -> dict:
        return {
            "ed25519_pub": self.ed25519_pub,
            "ml_dsa_variant": self.ml_dsa_variant,
            "ml_dsa_pub": self.ml_dsa_pub,
        }


class HybridSigner:
    """Persistent Ed25519 (+ optional ML-DSA) signer.

    Loads existing keys or creates them on first use. The post-quantum key is
    only created/used when ``pqcrypto`` is importable; otherwise the signer is
    Ed25519-only and says so via :pyattr:`is_hybrid`.
    """

    def __init__(self, ed25519_path: Path | None = None, mldsa_path: Path | None = None):
        self._ed_path = ed25519_path or (_keys_dir() / "custody_ed25519.pem")
        self._mldsa_path = mldsa_path or (_keys_dir() / "custody_ml_dsa_65.key")
        for p in (self._ed_path, self._mldsa_path):
            p.parent.mkdir(parents=True, exist_ok=True)
        self._pp = _passphrase()
        self._ed_key = self._load_or_create_ed25519()
        self._mldsa_pk, self._mldsa_sk = self._load_or_create_mldsa()

    # -- properties -------------------------------------------------------- #
    @property
    def is_hybrid(self) -> bool:
        return self._mldsa_sk is not None

    @property
    def key_protection(self) -> str:
        return "aes256gcm-scrypt" if self._pp else "plaintext-0600"

    # -- Ed25519 ----------------------------------------------------------- #
    def _load_or_create_ed25519(self) -> Ed25519PrivateKey:
        if self._ed_path.exists():
            raw = self._ed_path.read_bytes()
            pw = self._pp if self._pp else None
            return serialization.load_pem_private_key(raw, password=pw)
        key = Ed25519PrivateKey.generate()
        enc = (
            serialization.BestAvailableEncryption(self._pp)
            if self._pp
            else serialization.NoEncryption()
        )
        self._ed_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=enc,
            )
        )
        self._ed_path.chmod(0o600)
        return key

    # -- ML-DSA ------------------------------------------------------------ #
    def _load_or_create_mldsa(self) -> tuple[Optional[bytes], Optional[bytes]]:
        if not PQC_AVAILABLE:
            return None, None
        if self._mldsa_path.exists():
            blob = self._mldsa_path.read_bytes()
            data = _unwrap(blob, self._pp) if self._pp else blob
            pk_len = _mldsa.PUBLIC_KEY_SIZE
            return data[:pk_len], data[pk_len:]
        pk, sk = _mldsa.generate_keypair()
        data = pk + sk
        blob = _wrap(data, self._pp) if self._pp else data
        self._mldsa_path.write_bytes(blob)
        self._mldsa_path.chmod(0o600)
        return pk, sk

    # -- identity ---------------------------------------------------------- #
    def public_identity(self) -> PublicIdentity:
        ed_pub = self._ed_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        ).hex()
        if self._mldsa_pk is not None:
            return PublicIdentity(ed_pub, _MLDSA_VARIANT, self._mldsa_pk.hex())
        return PublicIdentity(ed_pub, None, None)

    # -- signing ----------------------------------------------------------- #
    def sign(self, data: bytes) -> dict:
        """Sign ``data``; the returned dict is JSON-serialisable and self-describing.

        ``algorithm`` reflects what was *actually* produced: ``"hybrid"`` when an
        ML-DSA key is present, otherwise ``"ed25519"``.
        """
        ed_sig = self._ed_key.sign(data).hex()
        ed_pub = self._ed_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        ).hex()
        if self._mldsa_sk is not None:
            ml_sig = _mldsa.sign(self._mldsa_sk, data).hex()
            return {
                "algorithm": "hybrid",
                "ed25519": {"sig": ed_sig, "pub": ed_pub},
                "ml_dsa": {"variant": _MLDSA_VARIANT, "sig": ml_sig, "pub": self._mldsa_pk.hex()},
            }
        return {"algorithm": "ed25519", "ed25519": {"sig": ed_sig, "pub": ed_pub}}


# --------------------------------------------------------------------------- #
# Verification (stateless -- needs only the signature dict + data)
# --------------------------------------------------------------------------- #

def _verify_ed25519(pub_hex: str, sig_hex: str, data: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(
            bytes.fromhex(sig_hex), data
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _verify_mldsa(variant: str, pub_hex: str, sig_hex: str, data: bytes) -> Optional[bool]:
    """Return True/False, or None if this verifier cannot check the variant."""
    if not PQC_AVAILABLE or variant != _MLDSA_VARIANT:
        return None
    try:
        return bool(_mldsa.verify(bytes.fromhex(pub_hex), data, bytes.fromhex(sig_hex)))
    except (ValueError, TypeError):
        return False


def verify(signature: dict, data: bytes, *, pinned: PublicIdentity | None = None) -> tuple[bool, str]:
    """Verify a signature dict over ``data``.

    Returns ``(ok, reason)``.

    Hybrid signatures require **both** components to verify (AND). A verifier that
    lacks the post-quantum library cannot check the ML-DSA half of a hybrid
    signature and therefore returns *failure* with an explanatory reason -- it
    never silently downgrades to "Ed25519 was fine".

    Pass ``pinned`` (the signer's known :class:`PublicIdentity`) to prove
    *provenance*: the signature's embedded public keys must then match the pinned
    ones, defeating a "tamper, re-sign with my own key" attack.
    """
    alg = signature.get("algorithm")
    ed = signature.get("ed25519") or {}

    if pinned is not None:
        if ed.get("pub") != pinned.ed25519_pub:
            return False, "ed25519 public key does not match the pinned signer"
        if alg == "hybrid":
            ml = signature.get("ml_dsa") or {}
            if ml.get("pub") != pinned.ml_dsa_pub:
                return False, "ml-dsa public key does not match the pinned signer"

    if alg == "ed25519":
        if _verify_ed25519(ed.get("pub", ""), ed.get("sig", ""), data):
            return True, "ok (ed25519; classical signature only -- not quantum-resistant)"
        return False, "ed25519 signature invalid"

    if alg == "hybrid":
        ml = signature.get("ml_dsa") or {}
        ed_ok = _verify_ed25519(ed.get("pub", ""), ed.get("sig", ""), data)
        ml_ok = _verify_mldsa(ml.get("variant", ""), ml.get("pub", ""), ml.get("sig", ""), data)
        if ml_ok is None:
            return False, (
                "cannot verify hybrid signature: the ML-DSA component is "
                f"uncheckable here ({ml.get('variant')!r} unavailable -- install the "
                "'pqc' extra). Refusing to pass on the classical half alone."
            )
        if ed_ok and ml_ok:
            return True, "ok (hybrid Ed25519 + ML-DSA; both components verified)"
        if not ed_ok and not ml_ok:
            return False, "hybrid signature invalid (both components failed)"
        return False, (
            "hybrid signature invalid ("
            + ("ed25519 ok, ml-dsa failed" if ed_ok else "ml-dsa ok, ed25519 failed")
            + ")"
        )

    return False, f"unknown signature algorithm: {alg!r}"


def canonical_bytes(payload: dict) -> bytes:
    """Deterministic serialisation for signing/hashing (sorted keys, compact)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
