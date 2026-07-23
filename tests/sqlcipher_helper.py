"""
Subprocess helper for SQLCipher boot-state tests (PR-E).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Boot states involve import-time engine binding and module-global lock flags,
so each scenario runs in its own process with its own OO_DATA_DIR /
OO_DB_PASSPHRASE / OO_DB_PLAINTEXT environment (set by the test). Protocol:
the LAST stdout line is a JSON verdict.
"""

from __future__ import annotations

import argparse
import json


def _emit(o: dict) -> None:
    print(json.dumps(o))


def _client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    return TestClient(app)


def cmd_boot_fresh(_args) -> None:
    """No DB, no passphrase, no plaintext opt-out: the app must boot LOCKED
    (fresh), gate the API, and create an ENCRYPTED store via /create-db."""
    from src.api.unlock import main_db_path

    with _client() as c:
        state = c.get("/api/system/lock-state").json()
        root = c.get("/", follow_redirects=False)
        gated = c.get("/api/sources")
        unlock_page = c.get("/unlock")
        mismatch = c.post(
            "/api/system/create-db", json={"passphrase": "pw-boot-test", "confirm": "nope"}
        )
        created = c.post(
            "/api/system/create-db",
            json={"passphrase": "pw-boot-test", "confirm": "pw-boot-test"},
        )
        after = c.get("/api/system/lock-state").json()
        api_ok = c.get("/api/sources")
        doctor = c.get("/api/system/doctor").json()
    from src.database.connect import is_encrypted_file

    _emit(
        {
            "state": state["state"],
            "root_redirect": root.status_code == 307 and "/unlock" in root.headers["location"],
            "gated_503": gated.status_code == 503 and gated.json().get("locked") is True,
            "unlock_page_ok": unlock_page.status_code == 200,
            "mismatch_400": mismatch.status_code == 400,
            "created": created.status_code == 200 and created.json()["created"],
            "state_after": after["state"],
            "api_after": api_ok.status_code,
            "file_encrypted": is_encrypted_file(main_db_path()),
            "doctor_corpus": doctor["corpus"]["state"],
        }
    )


def cmd_boot_locked(_args) -> None:
    """Existing ENCRYPTED store, no passphrase in env: locked boot; a wrong
    passphrase fails loudly (403); the right one opens everything."""
    with _client() as c:
        state = c.get("/api/system/lock-state").json()
        gated = c.get("/api/sources")
        wrong = c.post("/api/system/unlock", json={"passphrase": "WRONG"})
        right = c.post("/api/system/unlock", json={"passphrase": "pw-boot-test"})
        after = c.get("/api/system/lock-state").json()
        api_ok = c.get("/api/sources")
    _emit(
        {
            "state": state["state"],
            "gated_503": gated.status_code == 503,
            "wrong_403": wrong.status_code == 403,
            "right_200": right.status_code == 200,
            "state_after": after["state"],
            "api_after": api_ok.status_code,
        }
    )


def cmd_boot_env(_args) -> None:
    """OO_DB_PASSPHRASE in the environment: headless boot, never locked."""
    with _client() as c:
        state = c.get("/api/system/lock-state").json()
        api_ok = c.get("/api/sources")
        doctor = c.get("/api/system/doctor").json()
    _emit(
        {
            "state": state["state"],
            "api": api_ok.status_code,
            "doctor_corpus": doctor["corpus"]["state"],
            "cipher": doctor["corpus"].get("cipher"),
        }
    )


def cmd_encrypt_inplace(_args) -> None:
    """Plaintext store -> /api/system/encrypt-db -> encrypted, with snapshot."""
    from src.api.unlock import main_db_path

    with _client() as c:
        before = c.get("/api/system/doctor").json()["corpus"]["state"]
        no_consent = c.post(
            "/api/system/encrypt-db",
            json={"passphrase": "pw-tool-test", "confirm": "pw-tool-test"},
        )
        done = c.post(
            "/api/system/encrypt-db",
            json={"passphrase": "pw-tool-test", "confirm": "pw-tool-test", "consent": True},
        )
        after = c.get("/api/system/doctor").json()["corpus"]
        api_ok = c.get("/api/sources")
    from src.database.connect import is_encrypted_file

    p = main_db_path()
    snaps = sorted(x.name for x in p.parent.glob("pre-encrypt-*"))
    _emit(
        {
            "before": before,
            "no_consent_400": no_consent.status_code == 400,
            "done": done.status_code == 200,
            "after": after["state"],
            "cipher": after.get("cipher"),
            "file_encrypted": is_encrypted_file(p),
            "snapshot_kept": bool(snaps),
            "api_after": api_ok.status_code,
        }
    )


def _live_page_size() -> int:
    """PRAGMA page_size read through the app's OWN live engine (no special
    test-only connection) — the strongest possible proof that the NORMAL
    boot path actually opened the store at the recorded size."""
    from sqlalchemy import text

    from src.database.session import engine

    with engine.connect() as conn:
        return int(conn.execute(text("PRAGMA page_size")).scalar())


def cmd_pagesize_create(_args) -> None:
    """DB-10 §1b round trip, part 1: create a fresh encrypted store via the
    REAL /create-db flow (no OO_DB_PASSPHRASE pre-set — a genuine first-launch
    create, mirroring boot-fresh) and report the page size it landed at."""
    with _client() as c:
        created = c.post(
            "/api/system/create-db",
            json={"passphrase": "pw-pagesize-test", "confirm": "pw-pagesize-test"},
        )
        api_ok = c.get("/api/sources")
        page_size = _live_page_size()
    _emit({"created": created.status_code == 200, "api_ok": api_ok.status_code, "page_size": page_size})


def cmd_pagesize_reopen(_args) -> None:
    """DB-10 §1b round trip, part 2: a COMPLETELY FRESH process reopens the
    SAME store via the NORMAL headless boot path (OO_DB_PASSPHRASE in the
    environment, exactly like a real restart) — connect()'s call site here
    (src/database/session.py's engine creator) passes NO cipher_page_size at
    all; if the verify-then-fallback probe didn't work, the correct passphrase
    would read as wrong (the field incident this fix closes)."""
    with _client() as c:
        state = c.get("/api/system/lock-state").json()
        api_ok = c.get("/api/sources")
        doctor = c.get("/api/system/doctor").json()
        page_size = _live_page_size()
    _emit(
        {
            "state": state["state"],
            "api_ok": api_ok.status_code,
            "doctor_corpus": doctor["corpus"]["state"],
            "cipher": doctor["corpus"].get("cipher"),
            "page_size": page_size,
        }
    )


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in (
        "boot-fresh", "boot-locked", "boot-env", "encrypt-inplace",
        "pagesize-create", "pagesize-reopen",
    ):
        sub.add_parser(name)
    args = p.parse_args()
    {
        "boot-fresh": cmd_boot_fresh,
        "boot-locked": cmd_boot_locked,
        "boot-env": cmd_boot_env,
        "encrypt-inplace": cmd_encrypt_inplace,
        "pagesize-create": cmd_pagesize_create,
        "pagesize-reopen": cmd_pagesize_reopen,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
