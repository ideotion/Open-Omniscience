#!/usr/bin/env python3
"""Record the engine files' digest against INDEXER_VERSION (R412, which amends R24).

The engine identity carries a hand-bumped ``INDEXER_VERSION``; ``code_digest()`` (the hash of the
files an indexing pass reads) polices it. ``configs/indexer_pin.json`` holds the digest as of the
last judgement, and ``tests/test_indexer_pin.py`` is red whenever the two disagree. This script is
the only sanctioned way to turn it green again, and it refuses to do so without a sentence:

    python scripts/indexer_pin.py --bump "what changed in the rows an article gets"
    python scripts/indexer_pin.py --same "why the rows an article gets are identical"
    python scripts/indexer_pin.py --check       # exit 1 when the pin is stale (what the test asserts)

``--bump`` raises INDEXER_VERSION by one: every article's stamp stops matching, so the next restore or
re-index re-extracts it, and the release notes owe a line (R319). ``--same`` keeps the version: a
backup from the previous build still carries its derived rows. Choose ``--same`` only for a change that
cannot alter any row ``index_article`` writes (a docstring, a log line, a rename, an unrelated function).
A data file, a dictionary, a rule or a stoplist entry DOES alter rows: that is a ``--bump``.
The sentence goes into the pin's log and must be repeated in the PR description.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "configs" / "indexer_pin.json"
MODULE = ROOT / "src" / "analytics" / "engine_identity.py"
_VERSION_LINE = re.compile(r"^INDEXER_VERSION = (\d+)$", re.M)
MIN_NOTE = 12


def _load() -> dict:
    return json.loads(PIN.read_text(encoding="utf-8")) if PIN.exists() else {"version": 0, "digest": "", "log": []}


def _digest() -> str:
    sys.path.insert(0, str(ROOT))
    from src.analytics import engine_identity as ei

    ei.code_digest.cache_clear()
    return ei.code_digest()


def _set_version(new: int) -> None:
    text = MODULE.read_text(encoding="utf-8")
    if not _VERSION_LINE.search(text):
        raise SystemExit("INDEXER_VERSION line not found in engine_identity.py")
    MODULE.write_text(_VERSION_LINE.sub(f"INDEXER_VERSION = {new}", text, count=1), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bump", metavar="WHAT", help="the output of the engine changed: raise the version")
    g.add_argument("--same", metavar="WHY", help="the output did not change: keep the version, re-record the digest")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    pin = _load()
    digest = _digest()
    if a.check:
        ok = pin.get("digest") == digest
        print("pin current" if ok else f"pin STALE: recorded {pin.get('digest','')[:12]} actual {digest[:12]}")
        return 0 if ok else 1
    note = (a.bump or a.same or "").strip()
    if len(note) < MIN_NOTE:
        raise SystemExit(f"say what changed (>= {MIN_NOTE} characters); the sentence is the record")
    if a.same and pin.get("digest") == digest:
        raise SystemExit("--same refused: the engine files have not changed since the last judgement")
    version = int(pin.get("version", 0)) + (1 if a.bump else 0)
    if a.bump:
        _set_version(version)
    pin.update({"version": version, "digest": digest})
    pin.setdefault("log", []).append(
        {"version": version, "digest": digest, "kind": "bump" if a.bump else "same", "note": note}
    )
    PIN.write_text(json.dumps(pin, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{'bumped to' if a.bump else 'kept'} INDEXER_VERSION {version}; digest {digest[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
