#!/usr/bin/env python3
"""
Run the scale benchmark against a corpus and emit ONE honest JSON report (G2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measures the operations the 2026-07-09 field event proved break at scale:
  * unlock   -- cold init_db + ensure_* self-heals (builds ix_article_observed
                over every article, the field's 735 s cost) then a WARM re-run;
  * backup   -- the volumes+parity backup wall + PEAK RSS (the field's OOM);
  * restore  -- the volume-set restore round-trip (verify + parity-recover);
  * endpoints-- hot-endpoint p50/p95 (top/trending-windows/latest/graph/status);
  * wal      -- WAL growth under a write burst.

The report FORMAT is the acceptance instrument for the P0.1 backup rework: run it
before and after the change; the report is the pass/fail evidence. Nothing here is
a score -- only measured times, byte counts and status codes.

RUN OFFLINE, with the app STOPPED. --corpus is a DATA DIRECTORY containing
`open_omniscience.db` (the bench points OO_DATA_DIR at it, so the real app engine
and live_db_path resolve to the corpus). The backup/restore phases need
~corpus-size scratch inside the data dir; pick --phases to bound disk/time.

PASSPHRASES NEVER GO ON THE COMMAND LINE (audit A-020; the argv of a process is readable by every
user of the machine through ps, lands in shell history and in CI logs). The backup passphrase comes from
$OO_BENCH_BACKUP_PASSPHRASE, the corpus's from $OO_DB_PASSPHRASE (the name the app itself reads), set by
the caller; or each is read from standard input with --backup-passphrase-stdin / --corpus-passphrase-stdin
(the corpus line first when both are given, one line each). The old --backup-passphrase /
--corpus-passphrase flags are kept ONLY to refuse them by name, and an unrecognized argument is
reported by count, never printed: argparse would otherwise print the value it could not place.

Examples:
  # Full run on a plaintext corpus, report to stdout:
  OO_BENCH_BACKUP_PASSPHRASE=... python scripts/run_scale_bench.py --corpus /data/bench/oo-200mb

  # Field-scale ENCRYPTED corpus, unlock + backup only, report to a file (both from stdin):
  printf '%s\n%s\n' "$CORPUS_PASS" "$BACKUP_PASS" | python scripts/run_scale_bench.py \
      --corpus /mnt/scratch/oo-50gb --corpus-passphrase-stdin --backup-passphrase-stdin \
      --phases unlock,backup --out /mnt/scratch/report.json

The ~200 MB CI-safe smoke tier rides the pytest marker: `pytest -m scale_smoke`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SQLITE_MAGIC = b"SQLite format 3\x00"
_BACKUP_ENV = "OO_BENCH_BACKUP_PASSPHRASE"
_CORPUS_ENV = "OO_DB_PASSPHRASE"


def _passphrases(args, stdin) -> tuple[str | None, str | None]:
    """``(backup, corpus)`` from standard input or the named environment variables; never from argv, never echoed."""
    lines = None
    if args.corpus_passphrase_stdin or args.backup_passphrase_stdin:
        lines = stdin.read().splitlines()
    pos = 0
    corpus = os.environ.get(_CORPUS_ENV) or None
    backup = os.environ.get(_BACKUP_ENV) or None
    if args.corpus_passphrase_stdin:
        corpus = lines[pos] if len(lines) > pos and lines[pos] else None
        pos += 1
    if args.backup_passphrase_stdin:
        backup = lines[pos] if len(lines) > pos and lines[pos] else None
    return backup, corpus


def _is_encrypted(db_path: Path) -> bool:
    """Ciphertext header check without importing the app (so env is set first)."""
    try:
        with open(db_path, "rb") as fh:
            return fh.read(16) != _SQLITE_MAGIC
    except OSError:
        return False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--corpus", required=True, type=Path,
        help="data directory containing open_omniscience.db (OO_DATA_DIR will point here)",
    )
    p.add_argument("--out", type=Path, default=None, help="write the JSON report here (else stdout)")
    # Refused, not accepted: see the module docstring. Hidden from --help so nobody is invited to use them.
    p.add_argument("--backup-passphrase", default=None, help=argparse.SUPPRESS)
    p.add_argument("--corpus-passphrase", default=None, help=argparse.SUPPRESS)
    p.add_argument(
        "--backup-passphrase-stdin", action="store_true",
        help=f"read the backup-volume passphrase from standard input (else ${_BACKUP_ENV}); required for the backup/restore phases",
    )
    p.add_argument(
        "--corpus-passphrase-stdin", action="store_true",
        help=f"read the corpus's SQLCipher passphrase from standard input (else ${_CORPUS_ENV}); required if the corpus is encrypted",
    )
    p.add_argument(
        "--phases", default="all",
        help="comma list of phases to run: unlock,endpoints,backup,restore,wal (default all)",
    )
    p.add_argument("--repeats", type=int, default=8, help="GETs per endpoint")
    p.add_argument("--wal-writes", type=int, default=5000)
    p.add_argument("--parity-fraction", type=float, default=0.1)
    p.add_argument(
        "--interrupt-volumes", type=int, default=0,
        help="prove resumability: interrupt the backup after N volumes, then resume "
        "(the completed wall then includes reuse — NOT an official full-backup number)",
    )
    p.add_argument(
        "--gate", action="store_true",
        help="evaluate the P0.1 acceptance gate on the report (exit 1 on failure): "
        "corpus MUST be encrypted; backup/verify/restore phases error-free",
    )
    p.add_argument(
        "--max-backup-rss-mb", type=float, default=None,
        help="gate bound for the backup phase's sampled peak RSS (no default — the "
        "gate never invents a bound; without it the RSS check is not evaluated)",
    )
    p.add_argument(
        "--official", action="store_true",
        help="gate in OFFICIAL mode: requires this run to be a fresh-process "
        "--phases backup run (other phases inflate process-lifetime RSS)",
    )
    return p


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
    if args.backup_passphrase is not None or args.corpus_passphrase is not None:
        # Named and valueless: the value is in the caller's shell history already, and is not printed again here.
        print(
            "error: passphrases are not accepted on the command line (a process's arguments are readable "
            f"by other users and land in shell history). Set ${_BACKUP_ENV} / ${_CORPUS_ENV}, or use "
            "--backup-passphrase-stdin / --corpus-passphrase-stdin. The value you passed was not used.",
            file=sys.stderr,
        )
        return 2
    backup_passphrase, corpus_passphrase = _passphrases(args, sys.stdin)

    corpus_dir: Path = args.corpus
    corpus_db = corpus_dir / "open_omniscience.db"
    if not corpus_db.exists():
        print(f"error: no corpus at {corpus_db}", file=sys.stderr)
        return 2

    encrypted = _is_encrypted(corpus_db)
    if encrypted and not corpus_passphrase:
        print(
            f"error: the corpus is encrypted; set ${_CORPUS_ENV} or pass --corpus-passphrase-stdin",
            file=sys.stderr,
        )
        return 2

    # Point the process at the corpus BEFORE importing the app, so the module
    # engine + live_db_path + the app all resolve to this corpus. Never autostart
    # the scheduler / seed the catalog during a benchmark.
    os.environ["OO_DATA_DIR"] = str(corpus_dir)
    os.environ.setdefault("OO_NO_SCHEDULER", "1")
    os.environ.setdefault("OO_AUTOSEED", "0")
    os.environ.setdefault("OO_FIELD_TEST", "0")
    if encrypted:
        os.environ["OO_DB_PASSPHRASE"] = corpus_passphrase  # the app's own variable; a no-op when the caller set it
    else:
        os.environ.setdefault("OO_DB_PLAINTEXT", "1")

    from src.testing.scale_bench import ALL_PHASES, acceptance_gate, run_full

    if args.phases.strip().lower() == "all":
        phases = list(ALL_PHASES)
    else:
        phases = [x.strip() for x in args.phases.split(",") if x.strip()]
        unknown = [x for x in phases if x not in ALL_PHASES]
        if unknown:
            print(f"error: unknown phase(s): {unknown}; valid: {ALL_PHASES}", file=sys.stderr)
            return 2

    needs_backup = any(x in phases for x in ("backup", "verify", "restore"))
    if needs_backup and not backup_passphrase:
        print(
            f"error: the backup/restore phases need ${_BACKUP_ENV} or --backup-passphrase-stdin "
            "(the volume backup is always encrypted)",
            file=sys.stderr,
        )
        return 2

    report = run_full(
        corpus_dir,
        backup_passphrase=backup_passphrase or "",
        corpus_passphrase=corpus_passphrase,
        phases=phases,
        repeats=args.repeats,
        wal_writes=args.wal_writes,
        parity_fraction=args.parity_fraction,
        interrupt_volumes=args.interrupt_volumes,
    )
    gate = None
    if args.gate:
        gate = acceptance_gate(
            report,
            max_backup_peak_rss_mb=args.max_backup_rss_mb,
            official=args.official,
        )
        report["acceptance_gate"] = gate
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote report -> {args.out}", file=sys.stderr)
    else:
        print(text)
    if gate is not None and not gate["ok"]:
        print(f"acceptance gate FAILED: {gate['failures']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
