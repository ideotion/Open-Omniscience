"""
The passphrase gate: unlock / first-launch create flows for the encrypted store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled UX (2026-06-11): app start asks for THE passphrase — one
stable secret, "like a user ID" — and unlocks storage. First launch shows a
plain note: choose something unique and remember it; **there is no recovery
and no decryption alternative** (recorded rationale: the corpus is
reconstitutable from the web — a premise that EXPIRES when newsletters ship;
revisit before that lands). ``OO_DB_PASSPHRASE`` serves scripted/headless
runs; ``OO_DB_PLAINTEXT=1`` is the explicit opt-out — there is never a lock
screen over a plaintext file (fabricated security is forbidden).

Honesty: wrong passphrases fail loudly with unlimited local retries (lockout
theater would protect nothing on the operator's own machine); the threat
model is stated where shown — an encrypted file protects a seized/off
machine or a copied file, never a compromised running session.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_LOG = logging.getLogger("api.unlock")

router = APIRouter(prefix="/api/system", tags=["unlock"])

_MIN_PASSPHRASE = 8


def main_db_path() -> Path | None:
    """The live SQLite file, or None on non-SQLite backends (no at-rest layer)."""
    from src.database.session import DATABASE_URL

    if not DATABASE_URL.startswith("sqlite"):
        return None
    return Path(DATABASE_URL.removeprefix("sqlite:///"))


def app_lock_state() -> str:
    """unlocked-plaintext | unlocked-encrypted | locked | fresh (non-SQLite ->
    unlocked-plaintext: the at-rest layer does not apply and doctor says so)."""
    from src.database.connect import locked_state

    p = main_db_path()
    if p is None:
        return "unlocked-plaintext"
    return locked_state(p)


def app_is_locked() -> bool:
    return app_lock_state() in ("locked", "fresh")


#: Paths served while locked: the unlock flow itself + the static assets it
#: needs. Everything else answers 503 {"locked": true} until the store opens.
ALLOWED_WHILE_LOCKED = (
    "/unlock",
    "/api/system/lock-state",
    "/api/system/unlock",
    "/api/system/create-db",
    "/api/health",
    # The first-launch legal-consent step runs BEFORE the store exists (between the
    # language and passphrase steps), so its endpoints must answer while fresh/locked:
    # read/accept the documents, download them, or decline (which uninstalls).
    "/api/legal/",
    "/static/",
    "/favicon",
    # NB: "/sw.js" was allowlisted here for a root-scoped service worker that was
    # removed 2026-08-04 (see src/api/main.py) — nothing registered it, and the
    # worker's own fetch guard declines "/" regardless. The worker still registers
    # from the unlock screen at /static/sw.js, which "/static/" above already
    # allows, so its reachability is unchanged.
)


class PassphraseBody(BaseModel):
    passphrase: str


class CreateBody(BaseModel):
    passphrase: str
    confirm: str


class EncryptBody(BaseModel):
    passphrase: str
    confirm: str
    consent: bool = False


@router.get("/doctor")
def doctor() -> dict:
    """Attest the REAL at-rest state of every store (header reads, never
    assumptions) + the threat model. The honest answer to 'is my corpus
    encrypted?'."""
    from src.database.connect import get_passphrase, have_driver, is_encrypted_file
    from src.paths import data_dir

    def _store(p: Path | None) -> dict:
        if p is None:
            return {"state": "n/a", "note": "non-SQLite backend"}
        enc = is_encrypted_file(p)
        if enc is None:
            return {"state": "absent"}
        if not enc:
            return {"state": "plaintext"}
        out: dict = {"state": "encrypted"}
        if get_passphrase():
            try:
                from src.database.connect import connect

                c = connect(p, check_same_thread=False)
                try:
                    ver = c.execute("PRAGMA cipher_version").fetchone()
                    out["cipher"] = ver[0] if ver else None
                finally:
                    c.close()
            except Exception:  # noqa: BLE001 - attestation must not raise
                pass
        return out

    keys_dir = data_dir() / "keys"
    key_files = sorted(p.name for p in keys_dir.iterdir()) if keys_dir.is_dir() else []
    return {
        "driver": have_driver(),
        "corpus": _store(main_db_path()),
        "custody_log": _store(data_dir() / "custody_log.db"),
        "signing_keys": {
            "files": key_files,
            "note": "wrapped with scrypt+AES-GCM when a key passphrase is set; "
            "plaintext 0600 otherwise (re-created wrapped after encryption)",
        },
        "threat_model": "At-rest encryption protects a seized or copied file. "
        "It cannot protect a compromised running session (keys live in memory), "
        "and it is independent of full-disk encryption only if the passphrases differ.",
    }


@router.post("/encrypt-db")
def encrypt_db(body: EncryptBody) -> dict:
    """One-way encryption of an EXISTING plaintext store (snapshot first,
    explicit consent, never silent). Covers corpus + custody log (D6)."""
    from src.database.connect import set_passphrase
    from src.database.encrypt_tool import EncryptToolError, encrypt_all
    from src.database.session import dispose_engine

    if app_lock_state() != "unlocked-plaintext":
        raise HTTPException(
            status_code=409, detail="only an unlocked plaintext store can be encrypted"
        )
    if not body.consent:
        raise HTTPException(
            status_code=400,
            detail="explicit consent required: there is no recovery and no "
            "decryption alternative if the passphrase is lost",
        )
    if body.passphrase != body.confirm:
        raise HTTPException(status_code=400, detail="passphrases do not match")
    dispose_engine()
    try:
        reports = encrypt_all(body.passphrase)
    except EncryptToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_passphrase(body.passphrase)
    dispose_engine()  # next connection opens through the keyed factory
    _LOG.info("store encrypted in place")
    return {"encrypted": True, "reports": reports, "state": app_lock_state()}


@router.get("/lock-state")
def lock_state() -> dict:
    from src.database.connect import have_driver, plaintext_mode

    state = app_lock_state()
    return {
        "state": state,
        "locked": state in ("locked", "fresh"),
        "plaintext_mode": plaintext_mode(),
        "driver": have_driver(),
        # Threat model, stated wherever the lock surfaces (CLAUDE.md ruling):
        "threat_model": "Protects a seized or copied database file. "
        "It cannot protect a compromised running session.",
    }


@router.get("/startup-status")
def startup_status() -> dict:
    """Post-unlock progress for the unlock page's progress view. ``ready`` means the
    corpus is prepared and the Console is safe to enter; ``running`` carries the
    current human phase (an honest label, never a fabricated percentage)."""
    from src.api.startup_status import get_startup

    return get_startup()


def _finish_unlock(wal_state: dict | None = None, verify_ms: float | None = None) -> None:
    """Open the engine on the now-available key, make the DB queryable, and run the
    slow startup upkeep IN THE BACKGROUND.

    ``verify_ms`` is the caller's own passphrase-verify step. It is timed and reported
    as its own phase because it is not free: on the field's S3 boot the unlock spent
    24.7 s outside every timed phase, and that time was inside exactly this
    connect/close — wal-index recovery, WAL replay, the page-size probe and the
    checkpoint-on-close. Attributed to nothing, it read as unexplained overhead.

    ``wal_state`` is the caller's -wal reading taken BEFORE it opened any connection
    (S0.1). The timer used to take its own reading here, which was worthless on an
    encrypted store: ``unlock()`` verifies the passphrase with a connect/close first,
    and SQLite checkpoints and unlinks the -wal on the last close — so the reading was
    always ``absent``, whatever the previous session had left. A caller that has no
    reading (a fresh store) passes None and the timer says so rather than inventing
    one.

    On a large encrypted corpus the upkeep (bounded ANALYZE + catalog seeding + full
    COUNTs that decrypt every page + a cache warm) took long enough to freeze the
    Unlock button — and, on a single worker, any other tab opened meanwhile. So: open
    + ``init_db`` synchronously (fast on an existing store; guarantees the schema is
    queryable before we return), engage airplane mode synchronously (the zero-network
    guarantee must not lag), then run the upkeep off-thread. The unlock page polls
    ``/api/system/startup-status`` and only enters the Console when it reads ``ready``,
    so nothing queries a half-prepared corpus."""
    import os
    import threading

    from src.api.main import _run_startup_upkeep, init_db
    from src.api.startup_status import mark_queryable, set_startup
    from src.database.session import dispose_engine

    dispose_engine()  # drop any pre-unlock failed pool state
    set_startup("running", "opening the database", queryable=False)
    # Session forensics (2026-07-09, the 981 s field unlock): record the -wal size
    # BEFORE the first connection (a large WAL predicts recovery time inside it) and
    # time the synchronous phases, so "why was unlock slow" answers itself in the
    # next diagnostics export instead of needing the maintainer's stopwatch.
    _t = _forensic_timer(wal_state=wal_state)
    if verify_ms is not None:
        _t.add_phase("passphrase verify + WAL recovery + checkpoint-on-close", verify_ms)
    init_db()  # schema self-heal — fast on an existing store; makes the DB queryable
    _t.phase("init_db (schema self-heal + migrations + WAL recovery)")
    # The corpus is now fully usable — everything the background thread does below
    # (ANALYZE, catalog seed-dedup, COUNTs, cache warm) is best-effort optimization.
    # Tell the unlock page it may enter the Console NOW rather than wait out the whole
    # serial upkeep on a large encrypted corpus (field report: "unlocking takes ages").
    mark_queryable()

    # Engage airplane mode synchronously so there is never a window where the corpus
    # is unlocked but the socket-level guard is not yet installed.
    if os.getenv("OO_NO_SCHEDULER", "0") != "1":
        try:
            from src.ingest import activate_kill_switch
            from src.ingest.airplane import install_airplane_socket_guard

            install_airplane_socket_guard()
            activate_kill_switch()
        except Exception:  # noqa: BLE001 - never block the unlock on this
            _LOG.warning("could not engage airplane mode at unlock", exc_info=True)
    _t.phase("airplane guard")
    _t.finish()  # persist {wal_bytes_before, phases, total_ms} for the next export

    def _upkeep() -> None:
        try:
            _run_startup_upkeep()
            set_startup("ready", "")
        except Exception as exc:  # noqa: BLE001 - report, never crash the thread
            _LOG.warning("post-unlock startup upkeep failed", exc_info=True)
            # The DB is queryable (init_db ran synchronously) even if upkeep hiccuped,
            # so the corpus is usable — report ready rather than trap the user.
            set_startup("ready", "", error=str(exc))

    threading.Thread(target=_upkeep, name="oo-startup-upkeep", daemon=True).start()


class _forensic_timer:
    """Times the SYNCHRONOUS unlock phases + the -wal size before the first
    connection, and persists the record via forensics.record_unlock_timing.
    Every step is best-effort: a forensics failure never touches the unlock."""

    def __init__(self, wal_state: dict | None = None) -> None:
        import time as _time

        self._time = _time
        self._t0 = _time.monotonic()
        self._last = self._t0
        self._phases: list[dict] = []
        self._caller_ms = 0.0
        # The reading is HANDED IN, never taken here (S0.1): by the time this runs the
        # caller has already opened and closed a verify connection, which unlinks the
        # -wal, so a reading taken at this point describes the probe rather than the
        # store. A caller with nothing to hand in gets an explicit "not measured".
        self._wal_state: dict | None = wal_state or {
            "bytes": None,
            "state": "not-measured",
            "reason": (
                "the caller took no -wal reading before opening the store, so this "
                "unlock's WAL component is unmeasured — never reported as zero"
            ),
        }
        # The legacy field keeps its EXACT two-state meaning (present -> size,
        # absent/unreadable/not-measured -> None) so existing readers are byte-unchanged;
        # the state record beside it is what tells those cases apart.
        self._wal = (
            self._wal_state.get("bytes") if self._wal_state.get("state") == "present" else None
        )

    def phase(self, name: str) -> None:
        now = self._time.monotonic()
        self._phases.append({"phase": name, "ms": round((now - self._last) * 1000, 1)})
        self._last = now

    def add_phase(self, name: str, ms: float) -> None:
        """Record a phase the CALLER timed (it happened before this timer existed).
        Its duration is added to the reported total so the phases and the total agree
        — an equation that does not reproduce its own number is worse than none."""
        self._phases.append({"phase": name, "ms": round(float(ms), 1)})
        self._caller_ms += float(ms)

    def finish(self) -> None:
        try:
            from src.monitoring.forensics import record_unlock_timing

            record_unlock_timing(
                {
                    "wal_bytes_before_open": self._wal,
                    "wal_state_before_open": self._wal_state,
                    "phases": self._phases,
                    "synchronous_total_ms": round(
                        (self._time.monotonic() - self._t0) * 1000 + self._caller_ms, 1
                    ),
                    "method": (
                        "Wall-clock over the SYNCHRONOUS unlock phases (the wait the "
                        "user actually feels), INCLUDING the caller's passphrase-verify "
                        "step; the background upkeep is tracked separately by "
                        "startup-status. The -wal state is the caller's reading taken "
                        "before it opened ANY connection: a WAL present then is replayed "
                        "inside the verify connect and init_db, so a large one predicts "
                        "a slow unlock. An ABSENT -wal says nothing about how the "
                        "previous session ended — any connection, including a "
                        "wrong-passphrase attempt, unlinks it. The forensic reading "
                        "about the previous session is the one taken at boot "
                        "(previous_session.wal_at_boot), not this one."
                    ),
                }
            )
        except Exception:  # noqa: BLE001 - forensics never blocks the unlock
            _LOG.debug("could not record unlock timing", exc_info=True)


@router.post("/unlock")
def unlock(body: PassphraseBody) -> dict:
    """Unlock an existing encrypted store. Loud on a wrong passphrase;
    unlimited local retries (lockout would be theater on the operator's
    own machine)."""
    from src.database.connect import (
        WrongPassphraseError,
        connect,
        is_encrypted_file,
        set_passphrase,
    )

    p = main_db_path()
    if p is None or is_encrypted_file(p) is not True:
        raise HTTPException(status_code=409, detail="this store is not locked")
    if not body.passphrase:
        raise HTTPException(status_code=400, detail="a passphrase is required")
    # S0.1: read the -wal BEFORE the verify connection, because that connection
    # checkpoints and unlinks it. This reading is about the unlock path's own timing;
    # the load-bearing forensic reading is the one record_session_start() takes at
    # boot, which a wrong-passphrase attempt cannot destroy.
    try:
        from src.monitoring.forensics import wal_state_before_open

        _wal_state = wal_state_before_open()
    except Exception:  # noqa: BLE001 - forensics never blocks an unlock
        _wal_state = None
    _verify_t0 = time.monotonic()
    try:
        conn = connect(p, key=body.passphrase, check_same_thread=False)
        conn.close()
    except WrongPassphraseError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    _verify_ms = round((time.monotonic() - _verify_t0) * 1000, 1)
    set_passphrase(body.passphrase)
    _finish_unlock(wal_state=_wal_state, verify_ms=_verify_ms)
    _LOG.info("store unlocked")
    return {"unlocked": True, "state": app_lock_state()}


@router.post("/create-db")
def create_db(body: CreateBody) -> dict:
    """First launch: choose THE passphrase and create the encrypted store.

    The no-recovery note is shown by the page; this endpoint enforces only
    what a server can (length, match) — never strength theater."""
    from src.database.connect import set_passphrase

    p = main_db_path()
    if p is None:
        raise HTTPException(status_code=409, detail="non-SQLite backend: no at-rest layer here")
    if app_lock_state() != "fresh":
        raise HTTPException(status_code=409, detail="a database already exists")
    if body.passphrase != body.confirm:
        raise HTTPException(status_code=400, detail="passphrases do not match")
    if len(body.passphrase) < _MIN_PASSPHRASE:
        raise HTTPException(
            status_code=400, detail=f"use at least {_MIN_PASSPHRASE} characters"
        )
    set_passphrase(body.passphrase)
    try:
        _finish_unlock()
    except Exception:
        set_passphrase(None)  # leave the fresh state intact on any failure
        raise
    _LOG.info("encrypted store created")
    return {"created": True, "state": app_lock_state()}
