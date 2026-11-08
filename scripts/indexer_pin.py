#!/usr/bin/env python3
"""Record the engine files' digest against INDEXER_VERSION (R412, which amends R24).

The engine identity carries a hand-bumped ``INDEXER_VERSION``; ``code_digest()`` (the hash of the
files an indexing pass reads) polices it. ``configs/indexer_pin.json`` holds the digest as of the
last judgement, and ``tests/test_indexer_pin.py`` is red whenever the two disagree. This script is
the only sanctioned way to turn it green again, and it refuses to do so without a sentence:

    python scripts/indexer_pin.py --bump "what changed in the rows an article gets"
    python scripts/indexer_pin.py --same "why the rows an article gets are identical"
    python scripts/indexer_pin.py --check       # exit 1 when the pin is stale (what the test asserts)

``--engine www`` does the same for the places-and-entities stage (``WWW_INDEXER_VERSION``, ``configs/www_indexer_pin.json``, R415).

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
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: ``OO_INDEXER_PIN`` / ``OO_INDEXER_MODULE`` point the script at copies; the tests use them so that exercising the script can never
#: record a judgement in the real pin.
MODULE = Path(os.environ.get("OO_INDEXER_MODULE") or ROOT / "src" / "analytics" / "engine_identity.py")
#: engine -> (pin file, version constant, digest function). "kw" is the keyword-and-dates engine (R412); "www" is the places-and-entities
#: engine (R415), whose code and gazetteers are versioned and pinned on their own.
ENGINES = {
    "kw": ("indexer_pin.json", "INDEXER_VERSION", "code_digest"),
    "www": ("www_indexer_pin.json", "WWW_INDEXER_VERSION", "www_code_digest"),
}
MIN_NOTE = 12


def _pin_path(engine: str) -> Path:
    return Path(os.environ.get("OO_INDEXER_PIN") or ROOT / "configs" / ENGINES[engine][0])


def _load(pin: Path) -> dict:
    return json.loads(pin.read_text(encoding="utf-8")) if pin.exists() else {"version": 0, "digest": "", "log": []}


def _digest(engine: str) -> str:
    sys.path.insert(0, str(ROOT))
    from src.analytics import engine_identity as ei

    fn = getattr(ei, ENGINES[engine][2])
    fn.cache_clear()
    return fn()


def _set_version(engine: str, new: int) -> None:
    const = ENGINES[engine][1]
    line = re.compile(rf"^{const} = (\d+)$", re.M)
    text = MODULE.read_text(encoding="utf-8")
    if not line.search(text):
        raise SystemExit(f"{const} line not found in engine_identity.py")
    MODULE.write_text(line.sub(f"{const} = {new}", text, count=1), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=sorted(ENGINES), default="kw", help="kw (keywords and dates, the default) or www (places and entities)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bump", metavar="WHAT", help="the output of the engine changed: raise the version")
    g.add_argument("--same", metavar="WHY", help="the output did not change: keep the version, re-record the digest")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    pin_path = _pin_path(a.engine)
    pin = _load(pin_path)
    digest = _digest(a.engine)
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
        _set_version(a.engine, version)
    pin.update({"version": version, "digest": digest})
    pin.setdefault("log", []).append(
        {"version": version, "digest": digest, "kind": "bump" if a.bump else "same", "note": note}
    )
    pin_path.write_text(json.dumps(pin, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{'bumped to' if a.bump else 'kept'} {ENGINES[a.engine][1]} {version}; digest {digest[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
