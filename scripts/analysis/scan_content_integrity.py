#!/usr/bin/env python3
"""Flag Stage A rows whose FETCHED CONTENT contradicts their CLAIMED IDENTITY.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. Stage A answers one question honestly and refuses every other: does this
feed parse, and is it fresh? It says so itself -- "Nothing here judges what the outlet IS".
That refusal is right, and it leaves a gap that the two-judge run walked into by hand: a
domain whose registration or CMS has been taken over serves a feed that parses perfectly and
is extremely fresh, because a content farm publishes constantly. Stage A verifies it. A
reader catches it. Nothing in between did.

Judges reading 1,840 rows named a dozen such domains one at a time. This finds the same
class from the titles Stage A ALREADY fetched, at zero token cost and zero further network
traffic -- it never opens a socket, it reads run output.

WHAT IT IS NOT. It is not a verdict and must never become one. Measured over 6,036 verified
rows from three runs, the lexicon rule alone flags 39, of which roughly a dozen are entirely
legitimate: a national GAMBLING REGULATOR publishing a tender for casino licences, Italian
football reporting where "poker" means four goals in a match, sports outlets quoting betting
odds, and a historic Pamplona social club called the Nuevo Casino Principal. Three of them
-- redgol.cl, elivebrescia.tv, radiorukungiri.co.ug -- are ALREADY in the shipped catalogue
as the legitimate news outlets they are. A rule that auto-rejected on this signal would have
deleted them. So the output is a worklist for a reader, tiered by how much the evidence
actually supports, and the tier names say which.

THE TIERS, and what each was measured at.
  restricted_namespace  Gambling/adult/pharma lexicon on a namespace a private party CANNOT
                        register -- .gov.*, .gob.*, .go.id, .gouv.*, .mil. An expired domain
                        cannot explain it, so the site is compromised rather than lapsed.
                        10 for 10 on the measured corpus, including eight Venezuelan embassy
                        subdomains under one parent and two Indonesian district courts.
  placeholder           Entry titles that are CMS defaults -- "test", "Sample Page", lorem
                        ipsum. 9 rows, every one either a takeover or a site that was never
                        configured. Both mean the same thing for triage: THE EVIDENCE IS
                        EMPTY, so a judge asked to rule on evidence has none, and a row whose
                        freshness comes from placeholder posts is fresh about nothing.
  lexicon               The lexicon anywhere else. ~0.6 precision -- REVIEW REQUIRED, and the
                        tier is named so no caller can mistake it for the tier above.

Usage:
    python scripts/analysis/scan_content_integrity.py \\
        --run RUNS/shards/1/runs/w3 [--run ...] --out flags.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

# Namespaces whose registration is restricted to a government body. The point is not that
# government sites matter more -- it is that nobody else can HOLD one, so spam under it is a
# compromise of a live delegation rather than someone buying a lapsed name.
RESTRICTED_NAMESPACE = re.compile(
    r"\.(?:gov|gob|gouv|govt|go|gv|gc)\.[a-z]{2}$"   # .gov.uk .gob.ve .go.id .gouv.fr ...
    r"|\.gov$|\.mil$|\.int$"                          # .gov .mil .int
    r"|\.nat\.[a-z]{2}$",                             # .nat.tn and kin
    re.I,
)

# Deliberately narrow. Every term here is one an affiliate farm needs in a HEADLINE; broad
# words that merely co-occur with gambling ("odds", "win", "jackpot" alone) are left out,
# because the false positives they buy are exactly the sports desks this must not accuse.
SPAM_LEXICON = re.compile(
    r"\b(?:casino|kasino|slots?|poker|betting|bookmaker|sportsbook|bet365|judi|togel|gacor"
    r"|maxwin|situs|viagra|cialis|porn|escort|free spins|bonus code|no[- ]deposit bonus"
    r"|apuestas|wettanbieter)\b",
    re.I,
)

# CMS defaults and filler. Matched WHOLE-TITLE by the caller's fullmatch and carrying no
# anchors of its own, so that one mechanism is load-bearing rather than two agreeing: a
# headline that IS "test" is a placeholder, a headline that CONTAINS "test" is an ordinary
# word in some language and belongs to a lab, an exam board or a drug regulator.
PLACEHOLDER_TITLE = re.compile(
    r"test(?:ing)?\s*\d*|hello world|lorem ipsum\b.*|sample page|untitled|new post"
    r"|no title|prueba|teste|essai|demo|asdf+|a{3,}",
    re.I,
)

TIER_RESTRICTED = "restricted_namespace"
TIER_PLACEHOLDER = "placeholder"
TIER_LEXICON = "lexicon"

# Ordered most-supported first; a row reports the strongest tier that fired, and `rules`
# records every one, so a reader can see corroboration without the tier being inflated by it.
TIER_ORDER = (TIER_RESTRICTED, TIER_PLACEHOLDER, TIER_LEXICON)

FLAG_FIELDS = (
    "domain", "name", "country", "source_type", "tier", "rules", "status",
    "feed_url", "language_export", "language_detected", "evidence",
)


def classify(row: dict) -> dict | None:
    """The tiers a single Stage A row trips, or None. Pure; takes the row, opens nothing."""
    titles = [str(t).strip() for t in (row.get("titles") or []) if str(t).strip()]
    domain = str(row.get("domain") or "").strip().lower()
    if not domain:
        return None

    spam_hits = [t for t in titles if SPAM_LEXICON.search(t)]
    placeholder_hits = [t for t in titles if PLACEHOLDER_TITLE.fullmatch(t)]

    rules: list[str] = []
    if spam_hits:
        rules.append(TIER_RESTRICTED if RESTRICTED_NAMESPACE.search(domain) else TIER_LEXICON)
    if placeholder_hits:
        rules.append(TIER_PLACEHOLDER)
    if not rules:
        return None

    tier = next(t for t in TIER_ORDER if t in rules)
    evidence = (spam_hits + placeholder_hits)[:3]
    return {
        "domain": domain,
        "name": str(row.get("name") or ""),
        "country": str(row.get("country") or ""),
        "source_type": str(row.get("source_type") or ""),
        "tier": tier,
        "rules": ",".join(sorted(set(rules))),
        "status": str(row.get("status") or ""),
        "feed_url": str(row.get("feed_url") or ""),
        "language_export": str(row.get("language_export") or ""),
        "language_detected": str(row.get("language_detected") or ""),
        "evidence": " | ".join(t[:120] for t in evidence),
    }


def _rows_of(run_dir: Path) -> list[dict]:
    """Every judged row a run recorded. ``verified.jsonl`` holds them ALL, whatever its
    name suggests -- the same file ``build_retry_worklist`` reads, read the same way."""
    path = run_dir / "verified.jsonl"
    if not path.exists():
        raise SystemExit(f"no verified.jsonl in {run_dir}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def scan(runs: list[Path], out: Path | None, verified_only: bool = True) -> dict:
    seen: set[str] = set()
    flags: list[dict] = []
    scanned = 0
    tiers: Counter = Counter()
    for run_dir in runs:
        for row in _rows_of(run_dir):
            if verified_only and str(row.get("status") or "") != "verified":
                continue
            domain = str(row.get("domain") or "").strip().lower()
            # A domain re-judged by two runs is one publisher, and listing it twice would
            # inflate a count a reader is meant to work through by hand.
            if not domain or domain in seen:
                continue
            seen.add(domain)
            scanned += 1
            hit = classify(row)
            if hit:
                flags.append(hit)
                tiers[hit["tier"]] += 1
    flags.sort(key=lambda f: (TIER_ORDER.index(f["tier"]), f["domain"]))
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(FLAG_FIELDS), lineterminator="\n")
            w.writeheader()
            w.writerows(flags)
    return {
        "runs": len(runs),
        "scanned": scanned,
        "flagged": len(flags),
        "by_tier": {t: tiers.get(t, 0) for t in TIER_ORDER if tiers.get(t)},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", action="append", required=True, type=Path,
                    help="a finished run directory (the one holding verified.jsonl); repeatable")
    ap.add_argument("--out", type=Path, help="where to write the flag CSV")
    ap.add_argument("--all-statuses", action="store_true",
                    help="scan rejected and deferred rows too (default: verified only)")
    args = ap.parse_args(argv)
    stats = scan(args.run, args.out, verified_only=not args.all_statuses)
    print(json.dumps(stats, indent=1))
    print(f"\n{stats['flagged']:,} flagged of {stats['scanned']:,} scanned"
          + (f" -> {args.out}" if args.out else ""))
    print("\nThese are a READING LIST, not a verdict: the lexicon tier is ~0.6 precise and\n"
          "three of its hits are legitimate outlets already in the shipped catalogue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
