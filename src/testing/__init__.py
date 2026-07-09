"""
Scale-test harness (P0.5): synthetic corpora + a benchmark runner.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Everything here is DEV/TEST tooling. It never runs at app boot, never touches
the network, and computes no scores. The two pieces:

* :mod:`src.testing.corpus_gen` -- write a REAL app-schema SQLite corpus of a
  target size, grounded in the live 2026-07-09 field numbers, so scale cliffs
  (unlock/backup/query time) are found in dev instead of in the field. Every
  generated corpus carries a visible SYNTHETIC marker (a marker row + a SQLite
  ``application_id``) so it can never be mistaken for real user data.
* :mod:`src.testing.scale_bench` -- measure the unlock path, the volumes+parity
  backup (wall + peak RSS), the restore round-trip, hot-endpoint p95s and WAL
  growth against a given corpus, emitting ONE honest JSON report whose shape IS
  the acceptance contract for the Round-2 backup rework.
"""

from __future__ import annotations
