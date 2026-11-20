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
Exit code 0 = verified, 1 = failed, 2 = bad arguments, 3 = verified in the older bundle format (weaker guarantee),
4 = verified only by accepting an unendorsed key change (R716; it wins over 3).

--accept-unendorsed-rotation (R716) is needed when the signing key changed and the previous key could not vouch for
the change: keys re-created after a restore or a lost key folder, a post-quantum key re-created, or post-quantum
signing turned off before 0.5.1 (a log from then shows entries signed with both halves, then with the Ed25519 half
alone, with no record). Accepting it proves NOTHING about who made that change: someone holding the earlier Ed25519
key alone, or a forger who cut the log, writes the same. The verdict then never reads as a plain "verified": the
VERIFIED line says the change was unendorsed, and the exit code is 4. Use it only if you know, from elsewhere, why the
key changed and which key follows.

Bundle formats (R714). The app writes bundle format 2: its signed head commits to every entry's hash, so an entry
swapped, reordered, added or removed anywhere in the bundle is refused by name. A bundle from a development build
before that change is format 1: its head commits only to its count and last entry. It still verifies, but exits 3
and prints why it is weaker: in a one-item bundle (whose entries are not linked to each other) any entry but the last
could have been swapped for another one signed by the same key. Export it again from the app for the full check. The
format is read from the signed head; the bundle's top-level "bundle_format" is informational only.

A change of signing key is followed through its key-rotation record: endorsed by the previous key, it passes and is
named; unendorsed (the previous key was gone), it is refused unless --accept-unendorsed-rotation is given. A record
that only adds a post-quantum (ML-DSA) half passes, named; one that drops or replaces it needs the previous identity's
endorsement (both halves), or it is unendorsed.

With --pin, the head and every entry must be signed by the signer identity embedded in the
bundle (internal-consistency pinning); across a key rotation, each stretch of the chain is
held to the identity its rotation record introduced instead; where a 0.5.1 record introduced it, or for the head, a
signature stripped to its Ed25519 half under an identity that names an ML-DSA key is refused. In every mode, an entry
that drops or replaces the ML-DSA key its identity had shown, with no record, is refused (before any 0.5.1 record it
passes with --accept-unendorsed-rotation, named). To prove the bundle came from a *known*
signer, compare the printed signer public keys to that signer's known keys.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.custody.log import ACCEPTED_UNENDORSED_NOTE, scope_note, verify_export_report  # noqa: E402
from src.reporting.console_text import console_safe  # noqa: E402


def _say(line: object, *, file=None) -> None:
    """Every line goes out through console_safe: a bundle's own text can never draw a second verdict (row 199)."""
    print(console_safe(line), file=file if file is not None else sys.stdout)


def main(argv: list[str]) -> int:
    # A bundle's own text is printed back; a lone surrogate in it has no UTF-8 form and must not crash the report.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    unknown = flags - {"--pin", "--accept-unendorsed-rotation"}
    if unknown:
        # A misspelt --pin must not verify without the pin it was meant to add.
        _say(f"unknown option(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if len(args) != 1:
        _say(
            "usage: python scripts/verify_custody.py <custody_bundle.json> [--pin] [--accept-unendorsed-rotation]", file=sys.stderr
        )
        return 2

    try:
        bundle = json.loads(Path(args[0]).read_text(encoding="utf-8-sig"))  # UTF-8 as saved; never the locale's codec
    except (OSError, ValueError, RecursionError) as exc:  # ValueError: JSONDecodeError, UnicodeDecodeError, >4300-digit ints
        # A file cut mid-record is not JSON at all: refused by name, never a traceback.
        _say("VERIFIED       : False")
        _say("ISSUES:")
        _say(f"  - not a readable custody bundle ({type(exc).__name__}: {exc}); a file cut mid-record reads like this")
        return 1
    if not isinstance(bundle, dict):
        bundle = {"entries": bundle}
    report = verify_export_report(
        bundle, require_signer="--pin" in flags, accept_unendorsed_rotation="--accept-unendorsed-rotation" in flags
    )
    ok, issues = report["verified"], report["issues"]

    raw_signer = bundle.get("signer")
    signer: dict = raw_signer if isinstance(raw_signer, dict) else {}
    # From the signed head when there is one (row 46): the bundle's top-level copies are not signed.
    raw_head = bundle.get("head")
    shown: dict = raw_head if isinstance(raw_head, dict) else bundle
    _say(f"log_version    : {shown.get('log_version')}")
    _say(f"item_id        : {shown.get('item_id')}")
    _say(f"entry_count    : {shown.get('entry_count')}")
    _say(f"signer ed25519 : {signer.get('ed25519_pub')}")
    _say(f"signer ml-dsa  : {signer.get('ml_dsa_variant')} {signer.get('ml_dsa_pub')}")
    if ok:  # what a "verified" covers, said only beside one
        _say(f"scope          : {scope_note(bundle, report['notes'])}")
        for n in report["notes"]:
            _say(f"key rotation   : {n}")
        # R714: an old-format bundle is never reported as equal to a new one.
        _say(f"format         : {report['format_note'] or 'the signed head commits to every entry hash'}")
    unendorsed = ok and report["accepted_unendorsed"]
    _say(f"VERIFIED       : {ok}" + (" (old format: weaker guarantee)" if ok and report["format_note"] else "")
          + (f" -- UNENDORSED KEY CHANGE ACCEPTED: {ACCEPTED_UNENDORSED_NOTE}" if unendorsed else ""))
    if issues:
        _say("ISSUES:")
        for i in issues:
            _say(f"  - {i}")
    if not ok:
        return 1
    if unendorsed:
        return 4  # R716: never a plain "verified" when an unendorsed key change was accepted
    return 3 if report["format_note"] else 0  # R714: never the same answer for the weaker format


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
