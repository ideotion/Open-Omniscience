#!/usr/bin/env python3
"""
Independent verifier for Open Omniscience custody-log bundles.

Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Standalone like scripts/verify_evidence.py: depends only on the small custody
verification code (which needs `cryptography`, and `pqcrypto` only to check the
post-quantum half of hybrid signatures) -- NOT on the database or running app. A
third party (court, editor, collaborator) can confirm a custody chain offline.

Usage:
    python scripts/verify_custody.py custody_bundle.json [--pin]
Exit code 0 = verified, 1 = failed, 2 = bad arguments.

With --pin, every entry must be signed by the signer identity embedded in the
bundle (internal-consistency pinning). To prove the bundle came from a *known*
signer, compare the printed signer public keys to that signer's known keys.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.custody.log import verify_export  # noqa: E402


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if len(args) != 1:
        print("usage: python scripts/verify_custody.py <custody_bundle.json> [--pin]",
              file=sys.stderr)
        return 2

    bundle = json.loads(Path(args[0]).read_text())
    ok, issues = verify_export(bundle, require_signer="--pin" in flags)

    signer = bundle.get("signer", {})
    print(f"log_version    : {bundle.get('log_version')}")
    print(f"item_id        : {bundle.get('item_id')}")
    print(f"entry_count    : {bundle.get('entry_count')}")
    print(f"signer ed25519 : {signer.get('ed25519_pub')}")
    print(f"signer ml-dsa  : {signer.get('ml_dsa_variant')} {signer.get('ml_dsa_pub')}")
    print(f"VERIFIED       : {ok}")
    if issues:
        print("ISSUES:")
        for i in issues:
            print(f"  - {i}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
