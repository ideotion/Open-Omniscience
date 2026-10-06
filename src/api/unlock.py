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

import hmac
import logging
import os
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.monitoring.secret_scrub import log_failure, scrub_and_reraise, scrubbed

# Re-exported so the first-launch page and the module that creates the folder cannot
# disagree about the subfolder's name (the maintainer named it; see data_location.py).
from src.safety.data_location import DATA_SUBDIR

_LOG = logging.getLogger("api.unlock")

router = APIRouter(prefix="/api/system", tags=["unlock"])

_MIN_PASSPHRASE = 8

#: Held for the whole passphrase check and the open that follows it (see ``unlock``).
_UNLOCK_ONE_AT_A_TIME = threading.Lock()


def main_db_path() -> Path | None:
    """The live SQLite file, or None on non-SQLite backends (no at-rest layer)."""
    from src.database.session import DATABASE_URL

    if not DATABASE_URL.startswith("sqlite"):
        return None
    return Path(DATABASE_URL.removeprefix("sqlite:///"))


def app_lock_state() -> str:
    """unlocked-plaintext | unlocked-encrypted | locked | fresh (non-SQLite ->
    unlocked-plaintext: the at-rest layer does not apply and doctor says so).

    S3.6: reads the store header through the CACHED accessor, because this runs
    inside the lock middleware -- on every request, including every static asset
    -- and the uncached path is blocking file I/O on the event loop. The
    passphrase half is still read live, so an unlock is visible immediately;
    only the file's own header is cached, and every path that changes it calls
    ``invalidate_header_cache``.
    """
    from src.database.connect import main_header_state, state_for_header

    p = main_db_path()
    if p is None:
        return "unlocked-plaintext"
    return state_for_header(main_header_state(p))


#: The two states the lock gate answers for; everything else is an open store.
LOCKED_STATES = ("locked", "fresh")


def app_is_locked() -> bool:
    return app_lock_state() in LOCKED_STATES


#: Paths served while locked: the unlock flow itself + the static assets it
#: needs. Everything else answers 503 {"locked": true} until the store opens.
ALLOWED_WHILE_LOCKED = (
    "/unlock",
    "/api/system/lock-state",
    "/api/system/unlock",
    "/api/system/create-db",
    # What the verify connection is doing while a passphrase is being checked (rank 5, phase 0):
    # numbers only, and ``{"active": false}`` whenever no unlock attempt is running. NB: the
    # ``"/api/system/unlock"`` entry above already matches it (the gate matches by PREFIX), so this
    # line adds no reach; it names the path so that tightening the match to exact paths one day
    # cannot silently lock the unlock page's own progress poll out.
    "/api/system/unlock-progress",
    "/api/health",
    # The data-drive countdown (R86) must reach a LOCKED app too: a drive can be pulled
    # while the unlock screen is up. It answers a phase and a number of seconds, never
    # the folder's path, so a locked app still discloses nothing but that it is locked.
    "/api/system/data-volume",
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

#: Paths served ONLY while the state is ``fresh`` -- no store exists yet -- and still
#: refused (503) while an existing store is locked. The first-launch "Where should your
#: corpus live?" step runs between the legal step and the passphrase, i.e. exactly at
#: ``fresh``; it was unreachable because this gate answered 503 for it (2026-09-26
#: click-through, I15/P4/U1). EXACT paths, never a prefix: the step needs these three
#: calls (GET and POST on the first, POST on the second) and nothing that might later
#: be mounted beside them. Against a LOCKED store the answer stays what it was -- the
#: endpoints would disclose the data folder's path, and a locked app says nothing but
#: that it is locked. The handlers' own ``fresh`` checks remain the second wall.
ALLOWED_ONLY_WHILE_FRESH = (
    "/api/system/data-location",
    "/api/system/data-location/check",
)


def allowed_while_locked(path: str, state: str) -> bool:
    """Does the lock gate let ``path`` through in ``state`` (one of ``LOCKED_STATES``)?"""
    if any(path == p or path.startswith(p) for p in ALLOWED_WHILE_LOCKED):
        return True
    return state == "fresh" and path in ALLOWED_ONLY_WHILE_FRESH


class PassphraseBody(BaseModel):
    passphrase: str


class CreateBody(BaseModel):
    passphrase: str
    confirm: str


class DataLocationBody(BaseModel):
    path: str


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
    # THE LANES ARE STORES, so this endpoint reports them. It answers the operator's
    # question "is my data encrypted?", and an answer that enumerates two files while a
    # third sits in the clear beside them is not a narrower answer — it is a wrong one,
    # and it is wrong in the direction the no-fabricated-security rule exists to forbid.
    # Read from the registry, with each lane's state taken from its own file HEADER by
    # the same ``_store`` every other row uses; an absent lane reports "absent", which
    # is the honest state for a lane the operator has never opened.
    from src.versioned.lanes import all_lanes

    lanes = {spec.kind: _store(data_dir() / spec.filename) for spec in all_lanes()}
    return {
        "driver": have_driver(),
        "corpus": _store(main_db_path()),
        "custody_log": _store(data_dir() / "custody_log.db"),
        "lanes": lanes,
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
    # The key typed into this request is not held until the store is encrypted, so the nets that read what the process holds
    # cannot know it, and an engine's error can quote the statement that carried it: what escapes the block is converted.
    with scrub_and_reraise(_LOG, "encrypt in place failed", body.passphrase):
        dispose_engine()
        try:
            reports = encrypt_all(body.passphrase)
        except EncryptToolError as exc:
            raise HTTPException(status_code=400, detail=scrubbed(str(exc), body.passphrase)) from exc
        set_passphrase(body.passphrase)
        dispose_engine()  # next connection opens through the keyed factory
    _LOG.info("store encrypted in place")
    return {"encrypted": True, "reports": reports, "state": app_lock_state()}


@router.get("/data-location")
def data_location() -> dict:
    """Where the corpus will live, and whether that is still a choice.

    ``offerable`` is the whole point: a data location may only be chosen while the state is
    ``fresh``. ``src.paths.data_dir()`` re-reads the environment on every call while
    ``DATABASE_URL``/``engine``/``SessionLocal`` are frozen at module import, so a switch
    made after a store exists would move the keys, the custody log and the model store to
    the new folder and leave the corpus behind in the old one -- and the next start would
    follow the environment to the new, empty folder and report ``fresh``, with the
    operator's corpus orphaned. Moving an existing corpus is the plain-folder-copy path the
    manual documents (app stopped, copy the folder), deliberately not a button here.
    """
    from src.paths import data_dir

    state = app_lock_state()
    return {
        "data_dir": str(data_dir()),
        "explicit_override": bool(os.getenv("OO_DATA_DIR")),
        "state": state,
        "offerable": state == "fresh",
        "subdir": DATA_SUBDIR,
        "why_not_offerable": None
        if state == "fresh"
        else (
            "A corpus already exists here. Moving it is a file copy with the app stopped, "
            "not a setting — see the manual."
        ),
    }


@router.post("/data-location/check")
def data_location_check(body: DataLocationBody) -> dict:
    """Could the corpus live in this folder? Read-mostly; changes no setting.

    Gated on ``fresh`` like the write below: after a store exists the answer is not
    actionable, and an ungated probe would let anything reaching loopback create
    directories by asking questions.
    """
    from src.safety.data_location import preflight

    if app_lock_state() != "fresh":
        raise HTTPException(status_code=409, detail="a database already exists")
    return preflight(body.path)


@router.post("/data-location")
def data_location_set(body: DataLocationBody) -> dict:
    """Record the folder in ``oo.env`` so the NEXT launch uses it.

    Refuses once a store exists (see :func:`data_location` for why that is a data-safety
    refusal rather than a convenience one). Nothing is copied and nothing is opened: at
    ``fresh`` there is no corpus yet, which is exactly why this is the only safe moment.
    """
    from src.safety.data_location import persist

    if app_lock_state() != "fresh":
        raise HTTPException(status_code=409, detail="a database already exists")
    out = persist(body.path)
    if not out.get("saved"):
        raise HTTPException(status_code=400, detail=out.get("reason", "could not save"))
    _LOG.info("data location recorded: %s", out.get("path"))
    return out


@router.get("/data-volume")
def data_volume_state() -> dict:
    """The data-drive watchdog's phase (R86): ``ok`` · ``reconnect`` · ``shutdown`` ·
    ``restarting`` · ``closing``, with the seconds left in a countdown. Needs no database."""
    from src.safety.data_volume import MONITOR

    return MONITOR.snapshot()


@router.post("/data-volume/close-now")
def data_volume_close_now() -> dict:
    """The countdown's «Close now». Acts only while a disconnection is being handled, so it
    is never a second, unconfirmed power button."""
    from src.safety.data_volume import MONITOR

    if not MONITOR.close_now():
        raise HTTPException(409, "no data-drive disconnection is being handled")
    return {"ok": True}


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
        from src.monitoring.forensics import UNLOCK_VERIFY_PHASE

        _t.add_phase(UNLOCK_VERIFY_PHASE, verify_ms)
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

    try:
        threading.Thread(target=_upkeep, name="oo-startup-upkeep", daemon=True).start()
    except Exception as exc:  # noqa: BLE001 - e.g. "can't start new thread" on a machine out of memory
        # The upkeep is best-effort and the store is queryable: a thread that cannot be created must not
        # return a usable app to the lock screen (the caller clears the key on any failure here).
        _LOG.warning("post-unlock startup upkeep could not be started", exc_info=True)
        set_startup("ready", "", error=str(exc))


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


# A log smaller than ``forensics.recovery_floor_bytes()`` is recovered before anyone could read
# a sentence about it (the keyed open's own key derivation is 0.2 to 0.4 s of it), and a log AT the
# ``-wal`` resting ceiling says nothing about pending writes (it is the size an old log was cut back
# to), so the page says nothing; the same bound decides which unlocks count as a measured rate.
def _begin_recovery_notice(wal_state: dict | None) -> int | None:
    """Tell the unlock page what the verify connection is about to do, when it has a large log to
    recover. Never raises: a progress sentence must not be able to refuse an unlock."""
    try:
        from src.api.startup_status import begin_recovery
        from src.monitoring.forensics import recovery_estimate, recovery_floor_bytes

        if not wal_state or wal_state.get("state") != "present":
            return None
        wal = wal_state.get("bytes")
        if not isinstance(wal, int) or wal < recovery_floor_bytes():
            return None
        eta_s, basis = recovery_estimate(wal)
        return begin_recovery(wal, eta_s, basis)
    except Exception:  # noqa: BLE001 - a notice never blocks an unlock
        _LOG.debug("could not record the recovery notice", exc_info=True)
        return None


def _close_after_checkpoint(conn, passphrase: str | None = None) -> None:
    """Close the verify connection, writing the recovered log back into the database FIRST, through
    ``execute``, and NEVER waiting for a reader.

    MEASURED (sandbox, 600 MiB log, a ticker thread timing its own wake-ups): sqlcipher3's
    ``Connection.close()`` holds the GIL for the whole checkpoint it runs when it closes the last
    connection (2.1 s, worst gap between the ticker's wake-ups 2.1 s), while the same backfill run
    through ``execute`` (a TRUNCATE checkpoint: worst gap between the ticker's wake-ups 0.006 to
    0.023 s; a PASSIVE one measured 1.7 s with worst gap 0.01 s) releases it, and so does stdlib
    sqlite3's own ``close()``. So an encrypted store whose last session left a large log froze the
    whole process -- the event loop included, so not even the unlock page's progress poll could be
    answered -- for as long as the backfill took. How much of the field's 24.7 s unlock was that
    freeze was never measured: the open that recovers the log (1.5 to 3 times the close from a
    cold cache) releases the GIL and was never split from it. With the log already written back,
    ``close()`` has nothing left to hold the GIL for.

    ``busy_timeout`` is set to 0 FIRST. This connection inherits ``connect()``'s 30 s timeout, and a
    TRUNCATE checkpoint with another connection holding a read snapshot (a second process on the
    file, or a POST /unlock on an app that is already unlocked, whose own pooled readers pin the
    log) does not return "busy": it waits the whole timeout holding the WAL write lock, while the
    old ``close()`` simply skipped the checkpoint (measured: 0.00 s against 30.12 s, and a second
    writer failed with "database is locked" after its own 5 s). Waiting is never the fix here
    (``scheduler/hygiene.py`` records the same measurement: the whole hold IS the busy handler).
    A busy or failed checkpoint returns at once and falls back to what ``close()`` always did, so
    this can only make the step answer other requests while it runs. ``passphrase`` is the key the
    connection was opened with, which the process does not hold until the verify has accepted it: the
    driver's words of a failure are written with it (and with what the process holds) taken out."""
    try:
        conn.execute("PRAGMA busy_timeout = 0")
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is not None and int(row[0]) != 0:
            _LOG.info(
                "verify checkpoint before close was busy (a reader holds the log): "
                "close() does what it always did"
            )
    except Exception as exc:  # noqa: BLE001 - the close below still checkpoints, as it always did
        # WARNING, not DEBUG: a write-back that fails (a full drive, an I/O error) is invisible
        # otherwise -- close() then fails the same way silently, the verify reports success and
        # the notice ends -- and the next thing the person meets is init_db on the same drive.
        # The driver's own message only (no SQL runs here, so it carries no statement), with the typed key out of
        # it BEFORE the first line is taken and cut: a driver's error can still quote what it was handed.
        said = scrubbed(str(exc), passphrase, withheld="its text is withheld")
        _LOG.warning(
            "the recovered log could not be written back into the database before the verify "
            "connection closed (%s: %s); close() will try again",
            type(exc).__name__,
            (said.splitlines() or [""])[0][:200],
        )
    conn.close()


def _end_recovery_notice(token: int | None) -> None:
    try:
        from src.api.startup_status import end_recovery

        end_recovery(token)
    except Exception:  # noqa: BLE001 - as above
        _LOG.debug("could not clear the recovery notice", exc_info=True)


@router.get("/unlock-progress")
def unlock_progress() -> dict:
    """While a passphrase is being checked: the size of the log the verify connection is
    recovering, this machine's estimate for it with the measurement that estimate came from, and
    the seconds elapsed -- numbers only, and ``{"active": false}`` when no attempt is running.

    It is served while the app is locked (the page that calls it IS the lock screen), so it says
    nothing a locked app may not: no path, no name, only numbers, and only WHILE an attempt is
    running (the record is the process's, not the caller's: any loopback client polling during
    someone's attempt reads it, and reads ``{"active": false}`` otherwise)."""
    from src.api.startup_status import get_recovery

    return get_recovery()


@router.post("/unlock")
def unlock(body: PassphraseBody) -> dict:
    """Unlock an existing encrypted store. Loud on a wrong passphrase;
    unlimited local retries (lockout would be theater on the operator's
    own machine)."""
    from src.database.connect import is_encrypted_file

    p = main_db_path()
    if p is None or is_encrypted_file(p) is not True:
        raise HTTPException(status_code=409, detail="this store is not locked")
    if not body.passphrase:
        raise HTTPException(status_code=400, detail="a passphrase is required")
    # ONE attempt at a time: a second one (a reload and a second click, a second tab) waits for the
    # first instead of racing it. Raced, it replaced the first attempt's recovery notice, read the
    # log the first was still recovering (so its own verify was short against a big log, and the
    # rate it then recorded was several times too fast, which the next unlock's page would state
    # as an estimate), and ran ``_finish_unlock`` beside it. Serialised, it starts after the
    # first has written the log back, reads an honest (empty) log and measures nothing.
    with _UNLOCK_ONE_AT_A_TIME:
        # Re-asked INSIDE the lock: an attempt that queued behind one that succeeded finds the app
        # already open. Run again, it would dispose the live engine, mark the app unqueryable for the
        # whole verify and start a second start-up upkeep thread beside the first, to prove a
        # passphrase that is already proven. It does not run again; the key it brings is asked of the
        # file below, and that answer is the true one.
        if app_lock_state() == "unlocked-encrypted":
            # "Open" says a key is in memory, NOT that the key in memory opened the file: it is also set at boot from
            # ``OO_DB_PASSPHRASE`` and trusted for the state, and a wrong one reads as open until a connection is made.
            # So no answer here comes from the held key's say-so; "that one was right" is the one false answer that
            # costs the person something later (THE passphrase has no recovery), and every key is asked of the FILE.
            from src.database.connect import get_passphrase

            held = get_passphrase()
            if held is not None and hmac.compare_digest(body.passphrase.encode("utf-8"), held.encode("utf-8")):
                # The held key, submitted again (a stale tab, a double click that lands late): there is nothing to
                # replace and nothing to run again (no engine disposal, no second start-up upkeep thread), so the
                # file is only READ with it, read-only, so that the read cannot fold a leftover log into the file.
                # A wrong held key is refused here as any wrong key is, and the right one, typed next, takes the
                # repair below.
                _file_opens_with(p, body.passphrase)
                return {"unlocked": True, "state": "unlocked-encrypted"}
            # Not the held key: ``_unlock_locked`` verifies it against the file too. A wrong one is refused there
            # (403), and the right one repairs an app that reads as open while it holds a wrong key.
        return _unlock_locked(body, p)


def _file_opens_with(p: Path, passphrase: str) -> None:
    """Prove ``passphrase`` opens the store at ``p`` and change nothing: one READ-ONLY connection, closed. A wrong
    key is the same 403 as in ``_unlock_locked``. No recovery notice, no key swap and no finish: this is a question
    to the file and not an unlock.

    Read-only on purpose, because the app's pool may hold nothing on the file (a held key that was never used, or a
    pool that was disposed): the connection would then be the LAST one on it, and the last connection to close
    checkpoints a leftover ``-wal`` into the file and deletes it, with a wrong key as with the right one, and
    ``PRAGMA query_only`` does not prevent that (measured; see ``connect.connect``). A leftover log is what a crash
    leaves for whoever reads it next, and a question must not consume it. A read-only connection leaves the file and
    its log as they were."""
    from src.database.connect import WrongPassphraseError, connect

    try:
        conn = connect(p, key=passphrase, check_same_thread=False, read_only=True)
    except WrongPassphraseError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    conn.close()


def _unlock_locked(body: PassphraseBody, p: Path) -> dict:
    from src.database.connect import WrongPassphraseError, connect, set_passphrase

    # The key typed into this request is not held until the verify below has accepted it, so no net that reads what the
    # process holds can know it, and an engine's error can quote the statement that carried it: whatever escapes the block (a
    # verify that fails some other way than a wrong key, a finish that fails after the key was proven right) is written with
    # the key out of it and raised again as a ``RuntimeError`` carrying the scrubbed text.
    with scrub_and_reraise(_LOG, "unlock failed", body.passphrase):
        # S0.1: read the -wal BEFORE the verify connection, because that connection
        # checkpoints and unlinks it. This reading is about the unlock path's own timing;
        # the load-bearing forensic reading is the one record_session_start() takes at
        # boot, which a wrong-passphrase attempt cannot destroy.
        try:
            from src.monitoring.forensics import wal_state_before_open

            _wal_state = wal_state_before_open()
        except Exception:  # noqa: BLE001 - forensics never blocks an unlock
            _wal_state = None
        _recovery_token = _begin_recovery_notice(_wal_state)
        _verify_t0 = time.monotonic()
        try:
            conn = connect(p, key=body.passphrase, check_same_thread=False)
            _close_after_checkpoint(conn, passphrase=body.passphrase)
        except WrongPassphraseError as exc:
            # A wrong key under the floor of what can be taken out of a text (src/monitoring/secret_scrub.py,
            # MIN_SECRET_CHARS) withholds the message whole, so the withheld text is the message's fixed words, not
            # the scrub's "text withheld" notice: a mistyped short key is the lock screen's commonest answer.
            raise HTTPException(
                status_code=403,
                detail=scrubbed(
                    str(exc), body.passphrase, withheld="the passphrase does not open this file (or the file is damaged)"
                ),
            ) from exc
        finally:
            _end_recovery_notice(_recovery_token)
        _verify_ms = round((time.monotonic() - _verify_t0) * 1000, 1)
        set_passphrase(body.passphrase)
        try:
            _finish_unlock(wal_state=_wal_state, verify_ms=_verify_ms)
        except Exception:
            # A key in memory means "a key is in memory", not "the unlock finished": left there after a failed
            # finish (init_db on a full drive or a damaged file), the app reads as open, a retry is answered from
            # that state without running anything, and the page waits on "opening the database" for ever. Back to
            # locked, as ``create_db`` does, so the retry is a real one.
            set_passphrase(None)
            try:
                # the pool keeps the connections init_db opened with the key; drop them with it
                from src.database.session import dispose_engine

                dispose_engine()
            except Exception as dispose_exc:  # noqa: BLE001 - the retry disposes the engine again before it connects
                # Written through ``log_failure`` with the passphrase out of it, as every handler that holds one is: this
                # function holds ``body.passphrase`` and ``tests/test_p0_validation.py`` reads its handlers.
                log_failure(
                    _LOG, "engine dispose after a failed unlock finish failed", dispose_exc, body.passphrase, level=logging.DEBUG
                )
            raise
        _LOG.info("store unlocked")
        return {"unlocked": True, "state": app_lock_state()}


@router.post("/create-db")
def create_db(body: CreateBody) -> dict:
    """First launch: choose THE passphrase and create the encrypted store.

    The no-recovery note is shown by the page; this endpoint enforces only
    what a server can (length, match) — never strength theater."""
    from src.database.connect import invalidate_header_cache, set_passphrase

    p = main_db_path()
    if p is None:
        raise HTTPException(status_code=409, detail="non-SQLite backend: no at-rest layer here")
    if app_lock_state() != "fresh":
        raise HTTPException(status_code=409, detail="a database already exists")
    if body.passphrase != body.confirm:
        raise HTTPException(status_code=400, detail="passphrases do not match")
    if len(body.passphrase) < _MIN_PASSPHRASE:
        raise HTTPException(status_code=400, detail=f"use at least {_MIN_PASSPHRASE} characters")
    # As in ``_unlock_locked``: the key is not held until the store is created, so what escapes the block is converted.
    with scrub_and_reraise(_LOG, "create failed", body.passphrase):
        set_passphrase(body.passphrase)
        try:
            _finish_unlock()
        except Exception:
            set_passphrase(None)  # leave the fresh state intact on any failure
            raise
        finally:
            # S3.6: the store file now exists (or the attempt touched it), so the
            # cached header is stale either way. In a `finally` on purpose -- a
            # half-created file left by a failure must not be answered for from a
            # cache that still says "fresh".
            invalidate_header_cache()
    _LOG.info("encrypted store created")
    return {"created": True, "state": app_lock_state()}
