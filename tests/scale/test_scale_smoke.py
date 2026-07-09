"""
Scale-smoke tier (scale harness G3): generate a ~200 MB corpus and run the FULL
benchmark runner end-to-end, asserting it completes and emits sane shapes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the CI-safe tier: opt-in via ``-m scale_smoke`` (see conftest.py), size
tunable via ``OO_SCALE_SMOKE_MB`` (default 200). It is the smallest run that
exercises the WHOLE runner -- generation, cold/warm unlock, the volumes+parity
backup, the restore round-trip, the real app's hot endpoints, and WAL growth --
so a change that breaks the harness fails here in minutes rather than in a
hours-long operator run. The 50-100 GB tier is operator-run via the scripts.

The full runner is process-mode (it points OO_DATA_DIR at the corpus and boots the
real app), so it runs in a SUBPROCESS with its own env -- never touching this test
process's SessionLocal / data dir.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.testing.corpus_gen import CorpusSpec, generate_corpus

pytestmark = pytest.mark.scale_smoke

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _target_bytes() -> int:
    try:
        mb = int(os.environ.get("OO_SCALE_SMOKE_MB", "200"))
    except ValueError:
        mb = 200
    return max(8, mb) * 1024 * 1024


def _score_like_keys(obj) -> list[str]:
    found: list[str] = []

    def walk(d):
        if isinstance(d, dict):
            for k, v in d.items():
                kl = str(k).lower()
                if "score" in kl or "ranking" in kl or kl == "rank" or "grade" in kl:
                    found.append(str(k))
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)

    walk(obj)
    return found


def test_scale_smoke_generate_and_benchmark(tmp_path):
    target = _target_bytes()
    corpus_dir = tmp_path / "corpus"
    corpus_db = corpus_dir / "open_omniscience.db"

    # 1) Generate a ~target-size synthetic corpus (engine-mode, isolated).
    # ENCRYPTED: the P0.1 audit conditions ruled a plaintext corpus omits every
    # SQLCipher codec cost, so even the smoke tier measures the real thing (and
    # exercises the encrypted-corpus-member restore conversion end to end).
    summary = generate_corpus(
        corpus_db,
        CorpusSpec(
            target_bytes=target,
            batch_articles=2000,
            sources=120,
            mentions_per_article=78,
            fresh_keywords_per_article=8,
            head_pool=40_000,
            content_words=200,
            passphrase="scale-smoke-corpus-pass",
        ),
    )
    assert summary["synthetic"] is True
    assert summary["bytes"] >= target * 0.8  # target is approximate (~1 batch)

    # 2) Run the FULL benchmark runner as a subprocess (process-mode, isolated env).
    report_path = tmp_path / "report.json"
    env = {
        **os.environ,
        "OO_DATA_DIR": str(corpus_dir),
        "OO_NO_SCHEDULER": "1",
        "OO_AUTOSEED": "0",
    }
    env.pop("OO_DB_PLAINTEXT", None)
    proc = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "run_scale_bench.py"),
            "--corpus", str(corpus_dir),
            "--corpus-passphrase", "scale-smoke-corpus-pass",
            "--backup-passphrase", "scale-smoke-only-pass",
            "--gate",
            "--out", str(report_path),
            "--repeats", "4",
            "--wal-writes", "3000",
        ],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,  # generous "not hours" ceiling; a smoke run is minutes
    )
    assert proc.returncode == 0, f"bench runner failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    assert report_path.exists(), f"no report written; stderr:\n{proc.stderr}"

    report = json.loads(report_path.read_text(encoding="utf-8"))

    # 3) Sane shapes -----------------------------------------------------------
    assert report["report_schema"] == "oo-scale-bench-1"
    assert "generated_at" in report
    assert report["machine"]["cpu_count"] is not None
    assert report["corpus"]["synthetic"] is True
    assert report["corpus"]["encrypted"] is True  # the audit-condition corpus
    assert "plaintext_caveat" not in report
    assert report["corpus"]["row_counts"]["articles"] == summary["articles"]
    # the P0.1 acceptance gate ran and passed on this report
    assert report["acceptance_gate"]["ok"] is True, report["acceptance_gate"]["failures"]

    phases = report["phases"]
    assert set(phases) == {"unlock", "endpoints", "backup", "verify", "restore", "wal"}
    for name, ph in phases.items():
        assert "error" not in ph, f"phase {name} errored: {ph.get('error')}"

    # unlock: cold builds the self-heal index; warm is a near no-op (< cold).
    unlock = phases["unlock"]
    assert "ix_article_observed" in unlock["hot_indexes_created_cold"]
    assert unlock["hot_indexes_created_warm"] == []
    assert unlock["warm_unlock_s"] <= unlock["cold_unlock_s"] + 0.5

    # backup: at least one volume, a real wall + peak RSS, the streaming format.
    backup = phases["backup"]
    assert backup["volumes"] >= 1
    assert backup["wall_s"] > 0
    assert backup["peak_rss_mb"] > 0
    assert backup["format"] == "oo-volumes-2"
    assert backup["corpus_encrypted"] is True  # the corpus member stays ciphertext

    # verify: the end-to-end set verification (deep: decrypts into a hash sink).
    assert phases["verify"]["ok"] is True
    assert phases["verify"]["report"]["decrypted"] is True

    # restore verified; wal grew; every endpoint answered (200 on this corpus).
    assert phases["restore"]["verified"] is True
    assert phases["wal"]["wal_peak_bytes"] > 0
    statuses = [e["status"] for e in phases["endpoints"]["endpoints"]]
    assert all(s == 200 for s in statuses), f"endpoint statuses: {statuses}"

    # Minutes, not hours: the cold unlock on a ~200 MB corpus is well under the ceiling.
    assert unlock["cold_unlock_s"] < 600

    # Honesty: NO score/ranking key anywhere in the report.
    assert _score_like_keys(report) == []
