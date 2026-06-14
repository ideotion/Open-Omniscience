"""Guard: restore is ADDITIVE-ONLY — no replace path may ever come back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-06-13: restoring a backup must NEVER replace the corpus.
The destructive "replace the live database" paths were removed; the merge engine
(the oo-backup-2 artifact + /api/backup/v2/restore) is the ONLY restore. This
test fails the build if a replace-restore endpoint or function reappears — so the
guarantee cannot silently regress between sessions.
"""

from __future__ import annotations

from pathlib import Path


def test_no_replace_restore_function_survives():
    import src.backup.sqlite_backup as sqlite_backup
    import src.safety
    import src.safety.backup as safety_backup

    # The destructive "atomically replace the live database" function is gone.
    assert not hasattr(sqlite_backup, "restore_from_bytes"), (
        "restore_from_bytes (replace-restore) must stay removed — restore is additive-only"
    )
    # Its encrypted envelope is gone too (it delegated to the same replace).
    assert not hasattr(safety_backup, "restore_encrypted_backup")
    assert not hasattr(src.safety, "restore_encrypted_backup")
    assert "restore_encrypted_backup" not in getattr(src.safety, "__all__", [])
    # Backup CREATION is untouched (still exported / present).
    assert hasattr(src.safety, "make_encrypted_backup")
    assert hasattr(sqlite_backup, "backup_to")


def test_replace_restore_endpoints_are_gone_and_merge_remains():
    import re

    from src.api import backup_v2, database, safety
    from src.api.main import app

    # The route checks are anchored to IMMUTABLE sources of truth — each router's
    # own module-level route definitions and the wiring in src/api/main.py — not
    # to the long-lived, shared ``src.api.main.app`` singleton's mutable .routes
    # list. Reading that process-global made this guard FLAKY in CI: it tripped
    # intermittently (assert False on `app.routes` lacking /v2/restore) even
    # though NO code anywhere mutates app.routes, rebinds the app, or reloads
    # src.api.main — verified statically AND by a per-test route watcher across
    # the whole suite that never once saw the route disappear. Asserting against
    # where routes are DECLARED and INCLUDED removes that dependency on runtime
    # singleton state while keeping every guarantee the ruling encodes.

    def _router_paths(router) -> set[str]:
        # APIRoute.path already carries the router's prefix (FastAPI applies it at
        # decoration time), so r.path is the full path — do not prepend it again.
        return {getattr(r, "path", "") for r in router.routes}

    db_paths = _router_paths(database.router)
    safety_paths = _router_paths(safety.router)
    backup_v2_paths = _router_paths(backup_v2.router)

    # The two destructive replace-restore endpoints no longer exist — neither as a
    # defined route on their routers nor on the live app.
    live_paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/database/restore" not in db_paths
    assert "/api/database/restore" not in live_paths
    assert "/api/safety/restore/encrypted" not in safety_paths
    assert "/api/safety/restore/encrypted" not in live_paths

    # The ONE restore — the additive merge — must remain: (a) /v2/restore is
    # DECLARED on the backup-v2 router, and (b) src/api/main.py INCLUDES that
    # router unconditionally. A regression that deleted the route or dropped the
    # registration still fails the build.
    assert any("/v2/restore" in p for p in backup_v2_paths), (
        "the merge restore endpoint must remain: no /v2/restore route is declared "
        "on the backup-v2 router"
    )
    main_src = (Path(__file__).resolve().parents[1] / "src" / "api" / "main.py").read_text(
        encoding="utf-8"
    )
    assert re.search(r"^\s*app\.include_router\(backup_v2_router\)", main_src, re.MULTILINE), (
        "the merge restore endpoint must remain: src/api/main.py must include the "
        "backup-v2 router unconditionally"
    )

    # Backup CREATION endpoints remain (creating a backup is not a replace) —
    # asserted on the router's own definition, the immutable source of truth.
    assert "/api/safety/backup/encrypted" in safety_paths
