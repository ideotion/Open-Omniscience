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

Examples:
  # Full run on a plaintext corpus, report to stdout:
  python scripts/run_scale_bench.py --corpus /data/bench/oo-200mb \
      --backup-passphrase bench-only-pass

  # Field-scale ENCRYPTED corpus, unlock + backup only, report to a file:
  python scripts/run_scale_bench.py --corpus /mnt/scratch/oo-50gb \
      --corpus-passphrase "$OO_PASS" --backup-passphrase bench-only-pass \
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
    p.add_argument(
        "--backup-passphrase", default=None,
        help="encrypts the backup VOLUMES; required for the backup/restore phases",
    )
    p.add_argument(
        "--corpus-passphrase", default=None,
        help="the corpus's SQLCipher passphrase (required if the corpus is encrypted)",
    )
    p.add_argument(
        "--phases", default="all",
        help="comma list of phases to run: unlock,endpoints,backup,restore,wal (default all)",
    )
    p.add_argument("--repeats", type=int, default=8, help="GETs per endpoint")
    p.add_argument("--wal-writes", type=int, default=5000)
    p.add_argument("--parity-fraction", type=float, default=0.1)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    corpus_dir: Path = args.corpus
    corpus_db = corpus_dir / "open_omniscience.db"
    if not corpus_db.exists():
        print(f"error: no corpus at {corpus_db}", file=sys.stderr)
        return 2

    encrypted = _is_encrypted(corpus_db)
    if encrypted and not args.corpus_passphrase:
        print(
            "error: the corpus is encrypted; pass --corpus-passphrase",
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
        os.environ["OO_DB_PASSPHRASE"] = args.corpus_passphrase
    else:
        os.environ.setdefault("OO_DB_PLAINTEXT", "1")

    from src.testing.scale_bench import ALL_PHASES, run_full

    if args.phases.strip().lower() == "all":
        phases = list(ALL_PHASES)
    else:
        phases = [x.strip() for x in args.phases.split(",") if x.strip()]
        unknown = [x for x in phases if x not in ALL_PHASES]
        if unknown:
            print(f"error: unknown phase(s): {unknown}; valid: {ALL_PHASES}", file=sys.stderr)
            return 2

    needs_backup = "backup" in phases or "restore" in phases
    if needs_backup and not args.backup_passphrase:
        print(
            "error: the backup/restore phases need --backup-passphrase "
            "(the volume backup is always encrypted)",
            file=sys.stderr,
        )
        return 2

    report = run_full(
        corpus_dir,
        backup_passphrase=args.backup_passphrase or "",
        corpus_passphrase=args.corpus_passphrase,
        phases=phases,
        repeats=args.repeats,
        wal_writes=args.wal_writes,
        parity_fraction=args.parity_fraction,
    )
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote report -> {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
