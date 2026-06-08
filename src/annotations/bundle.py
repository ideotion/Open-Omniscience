"""
The signed annotation bundle — build & verify (reuses the hybrid custody signer).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A bundle is a portable, self-verifying document: a set of source annotations + the
author's public identity + a signature over the canonical manifest. Verification needs
only the bundle (the embedded public key is *pinned*, so a tamper-and-re-sign attack
fails to impersonate the original author — it merely produces a *different* author).
The signing primitive is the same hybrid Ed25519 (+ ML-DSA) signer as the chain of
custody — mutualisation, not a second crypto stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.custody.signing import HybridSigner, PublicIdentity, canonical_bytes, verify

BUNDLE_VERSION = "oo-annotations-1"

# Annotation kinds are *descriptive, contestable facts/tags* — never a composite score.
VALID_KINDS = (
    "coordination-tag",     # "these sources are a coordinated network"
    "ownership",            # "owned by X" / "state-media" / "wire-agency"
    "leaning",              # reputational political-leaning tag
    "transparency-fact",    # masthead, registration, funding disclosure, etc.
    "correction",           # a noted error / dispute about a source
    "note",                 # free-text observation
)


@dataclass
class Annotation:
    """One assertion about a source — a contestable fact/tag, never a verdict/score."""

    target: str             # source name or domain the annotation is about
    kind: str               # one of VALID_KINDS
    value: str              # the asserted tag/fact (e.g. "state-media", "owned by ACME")
    note: str = ""          # optional free-text context / evidence link
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"unknown annotation kind {self.kind!r}; use one of {VALID_KINDS}")
        if not self.target or not self.value:
            raise ValueError("target and value are required")

    def to_dict(self) -> dict:
        return {"target": self.target, "kind": self.kind, "value": self.value,
                "note": self.note, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, d: dict) -> Annotation:
        return cls(target=d["target"], kind=d["kind"], value=d["value"],
                   note=d.get("note", ""), created_at=d.get("created_at", datetime.now(UTC).isoformat()))


def build_manifest(author_name: str, annotations: list[Annotation]) -> dict:
    return {
        "bundle_version": BUNDLE_VERSION,
        "author_name": author_name,
        "created_at": datetime.now(UTC).isoformat(),
        "annotations": [a.to_dict() for a in annotations],
    }


def build_signed_bundle(author_name: str, annotations: list[Annotation],
                        signer: HybridSigner) -> dict:
    """Build a portable, signed annotation bundle."""
    manifest = build_manifest(author_name, annotations)
    signature = signer.sign(canonical_bytes(manifest))
    return {
        "manifest": manifest,
        "identity": signer.public_identity().to_dict(),
        "signature": signature,
    }


def author_id(identity: dict) -> str:
    """A stable author id = the Ed25519 public key hex (the web-of-trust handle)."""
    return identity.get("ed25519_pub", "")


def verify_bundle(bundle: dict) -> tuple[bool, str, dict]:
    """Verify a bundle against its *embedded* identity (pinned). Returns (ok, reason, identity).

    Pinning to the embedded key means a tamperer cannot forge the original author: any
    re-sign changes the identity, so a verified bundle is always truthfully attributed
    to whatever key signed it.
    """
    manifest = bundle.get("manifest")
    identity = bundle.get("identity") or {}
    signature = bundle.get("signature")
    if not manifest or not signature or not identity.get("ed25519_pub"):
        return False, "malformed bundle (missing manifest/identity/signature)", identity
    pinned = PublicIdentity(
        ed25519_pub=identity.get("ed25519_pub", ""),
        ml_dsa_variant=identity.get("ml_dsa_variant"),
        ml_dsa_pub=identity.get("ml_dsa_pub"),
    )
    ok, reason = verify(signature, canonical_bytes(manifest), pinned=pinned)
    return ok, reason, identity


def annotation_signer() -> HybridSigner:
    """The user's annotation-authoring signer (a key distinct from the custody key)."""
    from src.custody.signing import _keys_dir  # local import: same keys dir, separate files

    keys = _keys_dir()
    return HybridSigner(
        ed25519_path=keys / "annotations_ed25519.pem",
        mldsa_path=keys / "annotations_ml_dsa_65.key",
    )
