#!/usr/bin/env python3
"""
Independent verifier for a Claim Workspace trail bundle (the ZIP of step 6).

Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Needs no database and no network: it opens the ZIP, checks every member against the
SHA-256 the manifest lists (and that nothing was added or removed), recomputes the
Merkle root, and verifies the custody signature over the manifest.

Usage:
    python scripts/verify_claim_trail.py trail.zip [signer_ed25519_public_key_hex]

Pass the signer's public key, as the sender gave it to you some other way, to prove WHO
made the bundle; without it the check proves only that the file is unchanged since the
key it carries signed it. Exit code 0 = verified, 1 = failed, 2 = usage.
"""

import sys
from pathlib import Path

# Allow running from a checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics.claim_bundle import verify_trail_bundle  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("usage: python scripts/verify_claim_trail.py <trail.zip> [signer_ed25519_pub_hex]",
              file=sys.stderr)
        return 2
    data = Path(argv[1]).read_bytes()
    pinned = None
    if len(argv) == 3:
        pinned = {"ed25519_pub": argv[2]}
    res = verify_trail_bundle(data, pinned=pinned)
    ident = res.get("identity") or {}
    print(f"members checked : {res.get('members')}")
    print(f"signer ed25519  : {ident.get('ed25519_pub')}")
    print(f"signer ml-dsa   : {ident.get('ml_dsa_variant') or 'none'}")
    print(f"key checked     : {res.get('key_checked')}")
    print(f"signature       : {res.get('signature')}")
    for issue in res.get("issues") or []:
        print(f"PROBLEM         : {issue}")
    print(f"VERIFIED        : {res.get('verified')}")
    return 0 if res.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
