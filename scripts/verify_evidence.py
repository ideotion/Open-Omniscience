#!/usr/bin/env python3
"""
Independent verifier for Open Omniscience evidence bundles.

Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Deliberately standalone: it depends only on `cryptography` and the small Merkle
helper -- NOT on the database or the running app -- so a third party (a court, an
editor, a collaborator) can confirm a bundle's integrity without trusting this
tool. Recomputes the Merkle root from the items and checks the Ed25519 signature.

Usage:
    python scripts/verify_evidence.py bundle.json
Exit code 0 = verified, 1 = failed.
"""

import json
import sys
from pathlib import Path

# Allow running from a checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reporting.evidence import verify_bundle  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/verify_evidence.py <bundle.json>", file=sys.stderr)
        return 2
    bundle = json.loads(Path(argv[1]).read_text())
    ok, reason = verify_bundle(bundle)
    manifest = bundle.get("manifest", {})
    print(f"bundle_version : {manifest.get('bundle_version')}")
    print(f"case_name      : {manifest.get('case_name')}")
    print(f"generated_at   : {manifest.get('generated_at')}")
    print(f"item_count     : {manifest.get('item_count')}")
    print(f"merkle_root    : {manifest.get('merkle_root')}")
    print(f"public_key     : {bundle.get('public_key')}")
    print(f"VERIFIED       : {ok}  ({reason})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
