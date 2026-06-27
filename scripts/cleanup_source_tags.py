#!/usr/bin/env python3
"""
Deterministic cleanup of leaked code/territory tags in configs/sources.yml.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Some seeding passes leaked geographic/linguistic identifiers into the topical
``tags`` list, where they are noise and invisible to every geographic/linguistic
analysis. This script migrates each leaked tag into the field it belongs in and
removes it from ``tags`` -- nothing is fabricated:

  A. LANGUAGE-edition codes (be, lb, so, ig, rw, yue, pcm, eu) -- these mark a
     publisher's language edition (BBC Somali, RTL Luxembourg, Berria/Basque...).
     Set ``language`` to the code WHEN it is absent, then drop the tag.
  B. TERRITORY / country tags (cook-islands, faroe-islands, marshall-islands,
     guam, bermuda, us, ...) -- set ``country`` to the ISO-2 code WHEN absent,
     then drop the tag.
  C. ccTLD -> country/language for sources still missing them, via the existing
     CONSERVATIVE inferrer (src/catalog/cctld.py excludes vanity TLDs like
     .io/.tv/.me and only infers language for single-language ccTLDs). Opt-in via
     --cctld because it touches many rows.

Every mapping in A/B was hand-verified against the actual entries (see the PR).
Existing country/language values are NEVER overwritten. Entries are matched by
object identity (``bbc.com`` repeats across editions, so domain is not a key).

Dry run by default; pass --write to apply. The file round-trips through PyYAML
with a zero-line no-op diff, so only genuinely-changed entries appear in git diff.

Examples:
  python scripts/cleanup_source_tags.py                 # dry run, tags only
  python scripts/cleanup_source_tags.py --cctld         # dry run, incl. ccTLD
  python scripts/cleanup_source_tags.py --cctld --write  # apply everything
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
from src.catalog.cctld import infer_country, infer_language  # noqa: E402

_SOURCES = _ROOT / "configs" / "sources.yml"

# A. tag -> language code (the tag IS the language of a publisher's edition).
LANG_EDITION_TAGS: dict[str, str] = {
    "be": "be",    # Belarusian  (Nasha Niva)
    "lb": "lb",    # Luxembourgish (RTL Luxembourg)
    "so": "so",    # Somali      (BBC Somali)
    "ig": "ig",    # Igbo        (BBC Igbo)
    "rw": "rw",    # Kinyarwanda (BBC Gahuza)
    "yue": "yue",  # Cantonese   (RFA Cantonese)
    "pcm": "pcm",  # Nigerian Pidgin (BBC Pidgin)
    "eu": "eu",    # Basque      (Berria)
}

# B. tag -> ISO-3166-1 alpha-2 country code.
TERRITORY_TAGS: dict[str, str] = {
    "cook-islands": "ck",
    "faroe-islands": "fo",
    "french-polynesia": "pf",
    "new-caledonia": "nc",
    "marshall-islands": "mh",
    "saint-lucia": "lc",
    "antigua-and-barbuda": "ag",
    "saint-vincent-and-the-grenadines": "vc",
    "guam": "gu",
    "bermuda": "bm",
    "us": "us",
}


def clean(sources: list[dict], *, do_cctld: bool) -> dict:
    stats = {
        "lang_from_tag": 0, "country_from_tag": 0, "tags_removed": 0,
        "country_from_cctld": 0, "language_from_cctld": 0,
    }
    changed: list[str] = []
    for s in sources:
        tags = list(s.get("tags") or [])
        new_tags = []
        touched = False
        for t in tags:
            if t in LANG_EDITION_TAGS:
                if not s.get("language"):
                    s["language"] = LANG_EDITION_TAGS[t]
                    stats["lang_from_tag"] += 1
                stats["tags_removed"] += 1
                touched = True
                continue
            if t in TERRITORY_TAGS:
                if not s.get("country"):
                    s["country"] = TERRITORY_TAGS[t]
                    stats["country_from_tag"] += 1
                stats["tags_removed"] += 1
                touched = True
                continue
            new_tags.append(t)
        if touched:
            s["tags"] = new_tags
        if do_cctld:
            if not s.get("country"):
                cc = infer_country(s.get("domain"))
                if cc:
                    s["country"] = cc
                    stats["country_from_cctld"] += 1
                    touched = True
            if not s.get("language"):
                lg = infer_language(s.get("domain"))
                if lg:
                    s["language"] = lg
                    stats["language_from_cctld"] += 1
                    touched = True
        if touched:
            changed.append(s.get("domain") or s.get("name") or "?")
    return {"stats": stats, "changed": changed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sources", type=Path, default=_SOURCES)
    ap.add_argument("--cctld", action="store_true", help="also infer country/language from ccTLD")
    ap.add_argument("--write", action="store_true", help="apply (default: dry run)")
    args = ap.parse_args(argv)

    data = yaml.safe_load(args.sources.read_text(encoding="utf-8"))
    sources = data.get("sources") or []
    report = clean(sources, do_cctld=args.cctld)
    s = report["stats"]
    print(f"Catalog: {len(sources)} sources. Changed: {len(report['changed'])}.")
    print(
        f"  tags removed:          {s['tags_removed']}\n"
        f"  language from tag:     {s['lang_from_tag']}\n"
        f"  country from tag:      {s['country_from_tag']}\n"
        f"  country from ccTLD:    {s['country_from_cctld']}\n"
        f"  language from ccTLD:   {s['language_from_cctld']}"
    )
    if args.write:
        args.sources.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
            encoding="utf-8",
        )
        print(f"\nWROTE {args.sources}")
    else:
        print("\n(dry run — pass --write to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
