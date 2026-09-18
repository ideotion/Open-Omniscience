"""The 0.4 release run's FRESH-INSTALL restore -- a subprocess with its own data dir.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY A SUBPROCESS (the shape ``tests/test_restore_fixture_matrix.py`` records):
``data_dir()`` re-reads the environment per call, but the corpus engine is a module-level
singleton frozen at import, so an in-process "restore into a second directory" would
restore into the LIVE corpus -- a self-restore, in which every row reads as a duplicate
and no merge handler is exercised. Two processes are what gives two corpora, and the
P0.2 acceptance text names the fresh install as "the only case that exercises what the
merge carries".

WHAT IT DOES, in order, printing ONE json object at the end (and writing the same to
``OO_RELEASE_RUN_OUT`` so the parent can read it even if stdout is cut):

  1. boots the schema in the fresh data dir the parent handed it (``OO_DATA_DIR``),
     ENCRYPTED under ``OO_DB_PASSPHRASE`` -- no plaintext copy of the corpus on disk;
  2. restores ``OO_RELEASE_RUN_BACKUP`` COMMITTED: a directory is a volume set (the P0
     kit's own backup), a file is a legacy single-file artifact (row K's pre-migration
     case) -- both through the app's real restore paths, never a third one;
  3. reads the qualification integrity (row A's closing clause, on the RESTORED corpus:
     status == the verdict of its newest judging attempt), the duplicate-key scan (row
     K's artifact) and the row counts.

The parent deletes this directory afterwards unless asked to keep it. Nothing here
touches the operator's live corpus -- it cannot: this process's engine points at the
fresh directory by construction.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _restore(backup: Path, passphrase: str) -> dict:
    from src.backup.merge import run_restore

    if backup.is_dir():
        from src.backup.artifact import cleanup_staging, read_volume_backup

        staging_root = Path(os.environ["OO_DATA_DIR"]) / "restore-staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staged = read_volume_backup(
            backup, passphrase, staging_root=staging_root, include_merge_budget=True
        )
        try:
            report = run_restore(
                staged,
                commit=True,
                # The merge and the stamps are the claim; the post-swap keyword re-index
                # (stage 4 of the lifecycle) is hours at scale and says nothing about
                # either, so it is not run in a throwaway install. Stated in the report.
                reindex_imported=False,
                trust_fetch_history=True,
            )
        finally:
            cleanup_staging(staged)
        kind = "volume-set"
    else:
        from src.api.backup_v2 import restore_legacy_path

        report = restore_legacy_path(str(backup), passphrase or None, trust_fetch_history=True)
        kind = "legacy-single-file"
    plan = report.get("plan") if isinstance(report.get("plan"), dict) else {}
    return {
        "kind": kind,
        "committed": bool(report.get("committed")),
        "refused": report.get("refused"),
        "artifact_kind": report.get("artifact_kind"),
        "signature_state": report.get("signature_state"),
        "verification_ok": bool((report.get("verification") or {}).get("ok")),
        "plan_tables": {
            k: v for k, v in plan.items() if isinstance(v, (int, dict))
        } if plan else None,
        "country_codes_block": report.get("_country_codes"),
        "reindex_imported": False,
    }


def main() -> int:
    from src.monitoring.p0_validation import _RssSampler

    backup = Path(os.environ["OO_RELEASE_RUN_BACKUP"])
    passphrase = os.environ.get("OO_DB_PASSPHRASE") or ""
    out_path = Path(os.environ.get("OO_RELEASE_RUN_OUT") or (Path(os.environ["OO_DATA_DIR"]) / "result.json"))
    t0 = time.monotonic()
    result: dict = {"backup": str(backup), "data_dir": os.environ.get("OO_DATA_DIR")}
    try:
        from src.database.session import init_db

        init_db()
        with _RssSampler() as rss:
            result["restore"] = _restore(backup, passphrase)
        result["peak_rss_mb"] = rss.peak_mb
        result["baseline_rss_mb"] = rss.baseline_mb

        from sqlalchemy import func, select

        from src.backup.country_codes import scan_live_corpus
        from src.catalog.qualification_integrity import qualification_integrity_report
        from src.database.models import Article, Keyword, Source
        from src.database.session import session_scope

        with session_scope() as db:
            result["counts"] = {
                "articles": int(db.execute(select(func.count(Article.id))).scalar_one()),
                "sources": int(db.execute(select(func.count(Source.id))).scalar_one()),
                "keywords": int(db.execute(select(func.count(Keyword.id))).scalar_one()),
            }
            result["integrity"] = qualification_integrity_report(db)
            result["country_code_scan"] = scan_live_corpus(db)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 - the parent reads the failure; never a bare traceback only
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"[:600]
    result["elapsed_s"] = round(time.monotonic() - t0, 1)
    text = json.dumps(result, default=str)
    with contextlib.suppress(OSError):
        out_path.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
