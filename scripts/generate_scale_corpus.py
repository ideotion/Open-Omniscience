#!/usr/bin/env python3
"""
Generate a synthetic, app-schema SQLite corpus for scale testing (P0.5 / G1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Runs OFFLINE (no network, no app boot). Writes a REAL app-schema corpus whose
distributions are grounded in the live 2026-07-09 field numbers, so scale cliffs
(unlock/backup/query time) can be found in dev with scripts/run_scale_bench.py
instead of in the field. The corpus carries a VISIBLE synthetic marker (an
app_state row + a SQLite application_id) so it can never be mistaken for real
user data. The generator NEVER overwrites an existing file.

The 50-100 GB operator tier is run here (a one-time, minutes-to-tens-of-minutes
offline job); the CI-safe smoke tier (~200 MB) rides the pytest marker
`-m scale_smoke`. Point --out at a NEW file, with the app STOPPED.

Examples:
  # A quick ~200 MB plaintext corpus dated up to today (recent windows populated):
  python scripts/generate_scale_corpus.py --out /data/bench/oo-200mb/open_omniscience.db \
      --target-size 200MB

  # A field-scale 50 GB ENCRYPTED corpus (realistic for the backup/unlock benchmark); the
  # passphrase comes from $OO_DB_PASSPHRASE, never from the command line:
  OO_DB_PASSPHRASE=... python scripts/generate_scale_corpus.py \
      --out /mnt/scratch/oo-50gb/open_omniscience.db --target-size 50GB
  # ... or from standard input:
  printf '%s\n' "$PASS" | python scripts/generate_scale_corpus.py \
      --out /mnt/scratch/oo-50gb/open_omniscience.db --target-size 50GB --passphrase-stdin

  # An exact, byte-reproducible small corpus (unit-test / debugging):
  python scripts/generate_scale_corpus.py --out /tmp/oo/open_omniscience.db \
      --articles 5000 --end-date 2026-07-01

PASSPHRASES NEVER GO ON THE COMMAND LINE (audit A-020's sibling; the arguments of a process are readable
by every user of the machine through ps and land in shell history and CI logs). The corpus is encrypted
when a passphrase is supplied by $OO_DB_PASSPHRASE (the name the app and scripts/run_scale_bench.py read)
or by --passphrase-stdin, and is plaintext otherwise; the mode line printed before the run says which.
The old --passphrase flag is kept ONLY to refuse it by name, and an unrecognized argument is reported by
count, never printed: argparse would otherwise print back the value it could not place.

The bench runner expects the db file named `open_omniscience.db` inside a data
directory it will point OO_DATA_DIR at, so prefer --out <dir>/open_omniscience.db.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

# Make `src` importable when run from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kmgtKMGT]?)([bB]?)\s*$")
_DB_KEY_ENV_NAME = "OO_DB_PASSPHRASE"
_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def parse_size(text: str) -> int:
    """Parse a human byte size like '200MB', '1.5GB', '50g', '1048576'."""
    m = _SIZE_RE.match(text)
    if not m:
        raise argparse.ArgumentTypeError(f"invalid size: {text!r} (use e.g. 200MB, 1.5GB)")
    value, unit, _ = m.groups()
    return int(float(value) * _UNITS[unit.lower()])


def parse_date(text: str) -> date:
    if text.lower() == "today":
        return datetime.now(UTC).date()
    return date.fromisoformat(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", required=True, type=Path, help="destination .db path (NEW file)")
    size = p.add_mutually_exclusive_group(required=True)
    size.add_argument("--articles", type=int, help="exact article count (byte-reproducible)")
    size.add_argument(
        "--target-size", type=parse_size, help="grow until the db reaches ~this size (e.g. 200MB)"
    )
    p.add_argument("--seed", type=int, default=1729, help="RNG seed (reproducibility)")
    p.add_argument("--sources", type=int, default=200)
    p.add_argument("--mentions-per-article", type=int, default=78, help="~distinct keywords/article")
    p.add_argument("--fresh-keywords", type=int, default=8, help="single-article tail keywords/article")
    p.add_argument("--head-pool", type=int, default=40000, help="shared common-keyword vocabulary")
    p.add_argument("--content-words", type=int, default=220)
    p.add_argument("--time-span-days", type=int, default=365)
    p.add_argument(
        "--end-date",
        type=parse_date,
        default=datetime.now(UTC).date(),
        help="latest article date; 'today' (default) populates the recent-window endpoints",
    )
    p.add_argument("--batch", type=int, default=2000, help="articles per insert transaction")
    # Refused, not accepted: see the module docstring. Hidden from --help so nobody is invited to use it.
    p.add_argument("--passphrase", default=None, help=argparse.SUPPRESS)
    p.add_argument(
        "--passphrase-stdin",
        action="store_true",
        help=f"read the corpus passphrase (SQLCipher) from standard input, one line; else ${_DB_KEY_ENV_NAME} "
        "if set; with neither the corpus is a faster plaintext one",
    )
    p.add_argument(
        "--max-articles",
        type=int,
        default=60_000_000,
        help="runaway backstop for --target-size runs",
    )
    return p


def _passphrase(args, stdin) -> str | None:
    """The corpus passphrase from standard input or the named environment variable; never from argv, never echoed."""
    if args.passphrase_stdin:
        line = stdin.readline().rstrip("\r\n")
        return line or None
    return os.environ.get(_DB_KEY_ENV_NAME) or None


def main(argv: list[str] | None = None) -> int:
    # parse_known_args, not parse_args: argparse's own "unrecognized arguments: ..." error prints the arguments back, and
    # an unknown flag may be a passphrase option under another spelling. Only a COUNT is printed.
    args, unknown = build_parser().parse_known_args(argv)
    if unknown:
        print(
            f"error: {len(unknown)} unrecognized argument(s) (not printed: they may carry a secret); see --help",
            file=sys.stderr,
        )
        return 2
    if args.passphrase is not None:
        # Named and valueless: the value is in the caller's shell history already, and is not printed again here.
        print(
            "error: a passphrase is not accepted on the command line (a process's arguments are readable by other "
            f"users and land in shell history). Set ${_DB_KEY_ENV_NAME}, or use --passphrase-stdin. "
            "The value you passed was not used.",
            file=sys.stderr,
        )
        return 2
    passphrase = _passphrase(args, sys.stdin)

    out: Path = args.out
    if out.exists():
        print(f"error: {out} already exists (the generator never overwrites)", file=sys.stderr)
        return 2

    # A plaintext corpus needs the explicit opt-out the connection factory honours.
    if passphrase is None:
        os.environ.setdefault("OO_DB_PLAINTEXT", "1")

    from src.testing.corpus_gen import CorpusSpec, generate_corpus

    spec = CorpusSpec(
        articles=args.articles,
        target_bytes=args.target_size,
        seed=args.seed,
        sources=args.sources,
        mentions_per_article=args.mentions_per_article,
        fresh_keywords_per_article=args.fresh_keywords,
        head_pool=args.head_pool,
        content_words=args.content_words,
        time_span_days=args.time_span_days,
        end_date=args.end_date,
        passphrase=passphrase,
        batch_articles=args.batch,
        max_articles=args.max_articles,
    )
    print(
        f"generating synthetic corpus -> {out}  "
        f"({'encrypted' if passphrase else 'plaintext'}; run offline, app stopped)",
        file=sys.stderr,
    )
    summary = generate_corpus(out, spec)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
