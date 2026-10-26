"""
Tests for honest hybrid signatures (src/custody/signing.py).

These prove the two properties that PR #18's implementation got wrong:

1. **Honest labels** -- a signer signs as "hybrid" only when an ML-DSA key really
   exists; otherwise it signs as "ed25519". The label always matches reality.
2. **Hybrid = AND** -- a "hybrid" signature verifies only if BOTH the Ed25519 and
   the ML-DSA components verify; tampering with either, or being unable to check
   the post-quantum half, is a failure -- never a silent pass on the classical
   half alone.

The whole module must behave correctly with *only* `cryptography` installed, so
the post-quantum paths are gated on ``PQC_AVAILABLE``.
"""

from __future__ import annotations

import pytest

from src.custody import signing
from src.custody.signing import HybridSigner, canonical_bytes, verify

DATA = b"the quick brown fox"


def _signer(tmp_path, monkeypatch, passphrase: str | None = None):
    if passphrase is not None:
        monkeypatch.setenv("OO_KEY_PASSPHRASE", passphrase)
    else:
        monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    return HybridSigner(
        ed25519_path=tmp_path / "ed.pem",
        mldsa_path=tmp_path / "ml.key",
    )


def test_label_matches_reality(tmp_path, monkeypatch):
    s = _signer(tmp_path, monkeypatch)
    sig = s.sign(DATA)
    expected = "hybrid" if signing.PQC_AVAILABLE else "ed25519"
    assert sig["algorithm"] == expected
    assert s.is_hybrid is signing.PQC_AVAILABLE


def test_valid_signature_verifies(tmp_path, monkeypatch):
    s = _signer(tmp_path, monkeypatch)
    sig = s.sign(DATA)
    ok, reason = verify(sig, DATA)
    assert ok, reason


def test_tampered_data_fails(tmp_path, monkeypatch):
    s = _signer(tmp_path, monkeypatch)
    sig = s.sign(DATA)
    ok, _ = verify(sig, DATA + b"!")
    assert not ok


def test_tampered_ed25519_sig_fails(tmp_path, monkeypatch):
    s = _signer(tmp_path, monkeypatch)
    sig = s.sign(DATA)
    sig["ed25519"]["sig"] = "00" * 64
    ok, reason = verify(sig, DATA)
    assert not ok
    assert "ed25519" in reason.lower()


def test_keys_persist(tmp_path, monkeypatch):
    s1 = _signer(tmp_path, monkeypatch)
    id1 = s1.public_identity()
    s2 = _signer(tmp_path, monkeypatch)
    id2 = s2.public_identity()
    assert id1.ed25519_pub == id2.ed25519_pub
    assert id1.ml_dsa_pub == id2.ml_dsa_pub


def test_pinning_catches_resign_with_other_key(tmp_path, monkeypatch):
    """Tamper-and-resign: an attacker re-signs forged data with their OWN key and
    swaps in their public key. Integrity-only verify passes; pinning the real
    signer's identity catches it."""
    real = _signer(tmp_path / "real", monkeypatch)
    attacker = _signer(tmp_path / "atk", monkeypatch)
    real_id = real.public_identity()

    forged = attacker.sign(b"FORGED")
    # Self-consistent: integrity-only verify is fooled.
    assert verify(forged, b"FORGED")[0] is True
    # Pinned to the real signer -> rejected.
    ok, reason = verify(forged, b"FORGED", pinned=real_id)
    assert ok is False
    assert "match the pinned signer" in reason
    # The genuine signature verifies against the pinned identity.
    assert verify(real.sign(DATA), DATA, pinned=real_id)[0] is True


def test_passphrase_encrypts_keys_at_rest(tmp_path, monkeypatch):
    s = _signer(tmp_path, monkeypatch, passphrase="correct horse battery staple")
    assert s.key_protection == "aes256gcm-scrypt"
    # The Ed25519 PEM must be an ENCRYPTED PKCS8 blob, not a plaintext key.
    pem = (tmp_path / "ed.pem").read_bytes()
    assert b"ENCRYPTED PRIVATE KEY" in pem
    # Reloading with the same passphrase yields the same identity.
    s2 = _signer(tmp_path, monkeypatch, passphrase="correct horse battery staple")
    assert s2.public_identity().ed25519_pub == s.public_identity().ed25519_pub


def test_no_passphrase_is_reported_honestly(tmp_path, monkeypatch):
    s = _signer(tmp_path, monkeypatch)
    assert s.key_protection == "plaintext-0600"


def test_unknown_algorithm_rejected():
    ok, reason = verify({"algorithm": "magic"}, DATA)
    assert not ok
    assert "unknown" in reason.lower()


# --------------------------------------------------------------------------- #
# Hybrid AND-semantics. These use synthetic signature dicts so the core logic is
# tested even on machines without the post-quantum library.
# --------------------------------------------------------------------------- #


def test_hybrid_requires_pqc_to_verify_when_absent(tmp_path, monkeypatch):
    """A 'hybrid'-labelled signature must NOT pass on a verifier that cannot check
    the ML-DSA half. This is the exact bug we are guarding against."""
    monkeypatch.setattr(signing, "PQC_AVAILABLE", False)
    fake_hybrid = {
        "algorithm": "hybrid",
        "ed25519": {"sig": "ab", "pub": "cd"},
        "ml_dsa": {"variant": "ml_dsa_65", "sig": "ef", "pub": "01"},
    }
    ok, reason = verify(fake_hybrid, DATA)
    assert ok is False
    assert "cannot verify hybrid" in reason.lower()


@pytest.mark.skipif(not signing.PQC_AVAILABLE, reason="pqcrypto/ML-DSA not installed")
def test_hybrid_fails_if_only_one_component_valid(tmp_path, monkeypatch):
    s = _signer(tmp_path, monkeypatch)
    assert s.is_hybrid
    sig = s.sign(DATA)
    # Break ONLY the ML-DSA component; Ed25519 stays valid. AND semantics -> fail.
    broken = {**sig, "ml_dsa": {**sig["ml_dsa"], "sig": "00" * 3309}}
    ok, reason = verify(broken, DATA)
    assert ok is False
    assert "ml-dsa failed" in reason.lower()


@pytest.mark.skipif(not signing.PQC_AVAILABLE, reason="pqcrypto/ML-DSA not installed")
def test_hybrid_both_valid_passes(tmp_path, monkeypatch):
    s = _signer(tmp_path, monkeypatch)
    ok, reason = verify(s.sign(DATA), DATA)
    assert ok
    assert "both components verified" in reason


def test_canonical_bytes_is_stable():
    a = canonical_bytes({"b": 1, "a": 2})
    b = canonical_bytes({"a": 2, "b": 1})
    assert a == b == b'{"a":2,"b":1}'


# ---- audit 0.5.0 A-018: a failed unwrap of the ML-DSA key is a wrong passphrase unless the file is a legacy plaintext key ----

class _FakeMldsa:
    PUBLIC_KEY_SIZE = 10

    @staticmethod
    def generate_keypair():
        return b"P" * 10, b"S" * 30


def _fake_pqc(monkeypatch):
    monkeypatch.setattr(signing, "_mldsa", _FakeMldsa)
    monkeypatch.setattr(signing, "PQC_AVAILABLE", True)


def test_a_wrong_passphrase_on_the_wrapped_mldsa_key_raises_instead_of_signing_with_garbage(tmp_path, monkeypatch):
    _fake_pqc(monkeypatch)
    _signer(tmp_path, monkeypatch, "right-pass")  # creates both keys wrapped under it
    ml = tmp_path / "ml.key"
    ml.write_bytes(signing._wrap(b"P" * 10 + b"S" * 30, b"other-pass"))
    try:
        _signer(tmp_path, monkeypatch, "right-pass")
    except signing.SigningError as exc:
        assert "wrong passphrase" in str(exc) and "other-pass" not in str(exc)
    else:  # pragma: no cover - the defect: the wrapped blob was split into a garbage key pair
        raise AssertionError("a wrong passphrase on the wrapped ML-DSA key must not load")


def test_a_legacy_plaintext_mldsa_key_of_the_exact_length_still_loads_under_a_passphrase(tmp_path, monkeypatch):
    _fake_pqc(monkeypatch)
    _signer(tmp_path, monkeypatch, "pass-1")
    ml = tmp_path / "ml.key"
    ml.write_bytes(b"P" * 10 + b"S" * 30)  # what the key file was before the database had a passphrase
    s = _signer(tmp_path, monkeypatch, "pass-1")
    assert s.key_protection == "plaintext-0600" and s.is_hybrid


def test_a_plaintext_looking_mldsa_key_of_any_other_length_is_refused(tmp_path, monkeypatch):
    _fake_pqc(monkeypatch)
    _signer(tmp_path, monkeypatch, "pass-1")
    (tmp_path / "ml.key").write_bytes(b"P" * 10 + b"S" * 31)
    try:
        _signer(tmp_path, monkeypatch, "pass-1")
    except signing.SigningError:
        pass
    else:  # pragma: no cover
        raise AssertionError("a blob that is neither wrapped under this passphrase nor the exact plaintext length must be refused")


def test_the_right_passphrase_loads_the_wrapped_mldsa_key_and_is_not_legacy(tmp_path, monkeypatch):
    _fake_pqc(monkeypatch)
    _signer(tmp_path, monkeypatch, "pass-1")
    s = _signer(tmp_path, monkeypatch, "pass-1")
    assert s.key_protection == "aes256gcm-scrypt" and s.is_hybrid


def test_a_wrapped_mldsa_key_with_no_passphrase_held_raises_instead_of_signing_with_garbage(tmp_path, monkeypatch):
    _fake_pqc(monkeypatch)
    _signer(tmp_path, monkeypatch, None)  # both keys plaintext
    (tmp_path / "ml.key").write_bytes(signing._wrap(b"P" * 10 + b"S" * 30, b"earlier-pass"))
    try:
        _signer(tmp_path, monkeypatch, None)
    except signing.SigningError as exc:
        assert "no passphrase" in str(exc) and "earlier-pass" not in str(exc)
    else:  # pragma: no cover - the defect: the wrapped blob was split into a garbage key pair
        raise AssertionError("a wrapped ML-DSA key with no passphrase held must not load")
