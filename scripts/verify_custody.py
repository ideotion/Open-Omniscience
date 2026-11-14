#!/usr/bin/env python3
"""
Independent verifier for Open Omniscience custody-log bundles.

Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Standalone like scripts/verify_evidence.py: depends only on the small custody
verification code (which needs `cryptography`, and `pqcrypto` only to check the
post-quantum half of hybrid signatures) -- NOT on the database or running app. A
third party (court, editor, collaborator) can confirm a custody chain offline.

Usage:
    python scripts/verify_custody.py custody_bundle.json [--pin] [--accept-unendorsed-rotation]
Exit code 0 = verified, 1 = failed, 2 = bad arguments.

A change of signing key is followed through its key-rotation record: endorsed by the previous key, it passes and is
named; unendorsed (the previous key was gone), it is refused unless --accept-unendorsed-rotation is given.

With --pin, the head and every entry must be signed by the signer identity embedded in the
bundle (internal-consistency pinning); across a key rotation, each stretch of the chain is
held to the identity its rotation record introduced instead. To prove the bundle came from a *known*
signer, compare the printed signer public keys to that signer's known keys.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.custody.log import scope_note, verify_export_report  # noqa: E402


def main(argv: list[str]) -> int:
    # A bundle's own text is printed back; a lone surrogate in it has no UTF-8 form and must not crash the report.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if len(args) != 1:
        print(
            "usage: python scripts/verify_custody.py <custody_bundle.json> [--pin] [--accept-unendorsed-rotation]", file=sys.stderr
        )
        return 2

    try:
        bundle = json.loads(Path(args[0]).read_text())
    except (OSError, ValueError, RecursionError) as exc:  # ValueError: JSONDecodeError, UnicodeDecodeError, >4300-digit ints
        # A file cut mid-record is not JSON at all: refused by name, never a traceback.
        print(f"VERIFIED       : False\nISSUES:\n  - not a readable custody bundle ({type(exc).__name__}: {exc}); "
              "a file cut mid-record reads like this")
        return 1
    if not isinstance(bundle, dict):
        bundle = {"entries": bundle}
    report = verify_export_report(
        bundle, require_signer="--pin" in flags, accept_unendorsed_rotation="--accept-unendorsed-rotation" in flags
    )
    ok, issues = report["verified"], report["issues"]

    raw_signer = bundle.get("signer")
    signer: dict = raw_signer if isinstance(raw_signer, dict) else {}
    print(f"log_version    : {bundle.get('log_version')}")
    print(f"item_id        : {bundle.get('item_id')}")
    print(f"entry_count    : {bundle.get('entry_count')}")
    print(f"signer ed25519 : {signer.get('ed25519_pub')}")
    print(f"signer ml-dsa  : {signer.get('ml_dsa_variant')} {signer.get('ml_dsa_pub')}")
    if ok:  # what a "verified" covers, said only beside one
        print(f"scope          : {scope_note(bundle, report['notes'])}")
        for n in report["notes"]:
            print(f"key rotation   : {n}")
    print(f"VERIFIED       : {ok}")
    if issues:
        print("ISSUES:")
        for i in issues:
            print(f"  - {i}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
