#!/usr/bin/env python3
"""Resolve locale-file merge conflicts and keep the 12 locale files sorted.

Why: parallel PRs each append new UI strings at the END of every
src/static/locales/*.json, so any two of them conflict at the same spot. The
files are therefore kept SORTED (`_meta` first, then keys in code-point
order): two PRs then insert at different places and git merges them cleanly.

Usage (after `git merge origin/main` left conflict markers in locale files):

    python scripts/locales_merge.py            # resolve markers, sort, check
    python scripts/locales_merge.py --check    # only verify (no writes); CI/test use

Resolution keeps BOTH sides of every conflict hunk (a locale hunk is only
ever added keys). If both sides define the same key with different text the
script stops and names the key, because that is a real contradiction to be
decided, not a routine conflict.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"


def _pairs(text: str, path: Path) -> list[tuple[str, object]]:
    last: list[tuple[str, object]] = []

    def hook(kv):
        last[:] = kv  # the outermost object is decoded last
        return dict(kv)

    json.loads(text, object_pairs_hook=hook)
    return list(last)


def _split_hunks(raw: str) -> tuple[str, str] | None:
    """Return (ours-file, theirs-file) texts if raw carries conflict markers."""
    lines = raw.split("\n")
    if not any(ln.startswith("<<<<<<<") for ln in lines):
        return None
    ours: list[str] = []
    theirs: list[str] = []
    side = "both"
    for ln in lines:
        if ln.startswith("<<<<<<<"):
            side = "ours"
        elif ln.startswith("=======") and side == "ours":
            side = "theirs"
        elif ln.startswith(">>>>>>>") and side == "theirs":
            side = "both"
        else:
            if side in ("both", "ours"):
                ours.append(ln)
            if side in ("both", "theirs"):
                theirs.append(ln)
    return "\n".join(_commas(ours)), "\n".join(_commas(theirs))


def _commas(lines: list[str]) -> list[str]:
    """Make a one-sided reconstruction valid JSON again (trailing comma before `}`)."""
    out = list(lines)
    idx = [i for i, ln in enumerate(out) if ln.strip()]
    if len(idx) >= 2 and out[idx[-1]].strip() == "}":
        j = idx[-2]
        out[j] = out[j].rstrip().rstrip(",")
    return out


def _canonical(data: dict, sort: bool = True) -> str:
    if not sort:
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    meta = {k: v for k, v in data.items() if k == "_meta"}
    rest = {k: data[k] for k in sorted(k for k in data if k != "_meta")}
    return json.dumps({**meta, **rest}, ensure_ascii=False, indent=2) + "\n"


def _load_unique(text: str, path: Path) -> dict:
    pairs = _pairs(text, path)
    merged: dict = {}
    for k, v in pairs:
        if k in merged and merged[k] != v:
            raise SystemExit(f"{path.name}: key defined twice with different text: {k!r}")
        merged[k] = v
    return merged


def resolve(path: Path, sort: bool = True) -> str:
    raw = path.read_text(encoding="utf-8")
    hunks = _split_hunks(raw)
    if hunks is None:
        return _canonical(_load_unique(raw, path), sort)
    ours, theirs = hunks
    a = _load_unique(ours, path)
    b = _load_unique(theirs, path)
    for k in a.keys() & b.keys():
        if a[k] != b[k]:
            raise SystemExit(f"{path.name}: both sides changed key {k!r} differently")
    return _canonical({**a, **b}, sort)


def check() -> list[str]:
    problems: list[str] = []
    for p in sorted(LOCALES.glob("*.json")):
        raw = p.read_text(encoding="utf-8")
        if any(ln.startswith(("<<<<<<<", ">>>>>>>")) for ln in raw.split("\n")):
            problems.append(f"{p.name}: conflict markers")
            continue
        try:
            keys = [k for k, _ in _pairs(raw, p)]
        except ValueError as exc:
            problems.append(f"{p.name}: invalid JSON ({exc})")
            continue
        if len(keys) != len(set(keys)):
            problems.append(f"{p.name}: duplicate keys")
        if raw != _canonical(json.loads(raw)):
            problems.append(f"{p.name}: not in canonical sorted order (run scripts/locales_merge.py)")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    ap.add_argument("--no-sort", action="store_true",
                    help="resolve conflicts but keep file order (for branches cut before the locale files were sorted)")
    args = ap.parse_args(argv)
    if args.check:
        problems = check()
        for line in problems:
            print(line)
        return 1 if problems else 0
    for p in sorted(LOCALES.glob("*.json")):
        text = resolve(p, sort=not args.no_sort)
        if text != p.read_text(encoding="utf-8"):
            p.write_text(text, encoding="utf-8")
            print(f"rewrote {p.name}")
    if args.no_sort:
        return 0
    problems = check()
    for line in problems:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
