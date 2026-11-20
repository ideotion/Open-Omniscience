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

from src.reporting.console_text import console_field, console_safe  # noqa: E402
from src.reporting.evidence import verify_bundle  # noqa: E402


def _say(line: object, *, file=None) -> None:
    """Every line goes out through console_safe: a bundle's own text can never draw a second verdict (row 199)."""
    print(console_safe(line), file=file if file is not None else sys.stdout)


def main(argv: list[str]) -> int:
    # A bundle's own text is printed back; on a cp1252 console (Windows) a non-ASCII case name must not crash it.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if len(argv) not in (2, 3):
        _say(
            "usage: python scripts/verify_evidence.py <bundle.json> [trusted_public_key_hex]",
            file=sys.stderr,
        )
        _say(
            "  Pass the signer's known public key to prove provenance (not just integrity).",
            file=sys.stderr,
        )
        return 2
    # The browser saves UTF-8; never the locale's codec (cp1252 on Windows broke non-ASCII bundles, row 198).
    bundle = json.loads(Path(argv[1]).read_text(encoding="utf-8-sig"))
    trusted = argv[2] if len(argv) == 3 else None
    ok, reason = verify_bundle(bundle, trusted_public_key=trusted)
    manifest = bundle.get("manifest", {})
    _say(f"bundle_version : {console_field(manifest.get('bundle_version'))}")
    _say(f"case_name      : {console_field(manifest.get('case_name'))}")
    _say(f"generated_at   : {console_field(manifest.get('generated_at'))}")
    _say(f"item_count     : {console_field(manifest.get('item_count'))}")
    _say(f"merkle_root    : {console_field(manifest.get('merkle_root'))}")
    _say(f"public_key     : {console_field(bundle.get('public_key'))}")
    _say(f"VERIFIED       : {ok}  ({reason})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
