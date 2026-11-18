"""
One-way encrypt tool for EXISTING plaintext stores (maintainer-ruled flow).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Snapshot first, explicit consent, never silent on upgrade: an existing
plaintext database keeps working untouched until the operator explicitly
encrypts it. The pre-encrypt snapshot is DELIBERATELY plaintext — it is the
operator's last escape hatch if the passphrase is mistyped into muscle memory
wrong; the report says so and the operator deletes it when satisfied.
"One-way" means the tool never decrypts in place; an operator who knows the
passphrase can always produce a plaintext *backup* through the normal flow.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path

from src.database.connect import (
    connect,
    is_encrypted_file,
    reencrypt_plain_to,
    snapshot_to_plaintext,
)
from src.monitoring.secret_scrub import log_failure, passphrase_bytes

_LOG = logging.getLogger("database.encrypt_tool")


class EncryptToolError(RuntimeError):
    """Raised when an in-place encryption cannot proceed safely."""


def _table_counts(conn) -> dict[str, int]:
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'article_fts%'"
        )
    ]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}  # noqa: S608  # nosec B608 # identifier from the fixed store list, never input


def encrypt_database(
    path: Path | str,
    key: str,
    *,
    library: bool = False,
    on_swapped: Callable[[], object] | None = None,
    keep_snapshot_on_failure: bool = True,
) -> dict:
    """Encrypt one SQLite file in place: snapshot -> export -> verify -> swap.

    The live file is replaced only AFTER the encrypted copy passes
    quick_check and per-table count equality. Returns an honest report.

    ``library`` is True for the file the app's engine is open on (the corpus): the swap then happens inside the one window of
    ``library_generation`` (``backup.merge.swap_in_corpus`` uses it for the restore and the repair). A request that held a pooled
    connection to the old file while it waited for the write gate would otherwise save into the replaced inode after the gate was
    given back: it reports success and the row is in no library. Inside the window every connection made before is refused from its
    first line (``StaleLibraryError``: "do it again"), so that save fails loudly and loses nothing. The other stores (the custody log,
    the lanes) have no engine of that kind and swap as they always did."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {"path": str(p), "skipped": "file does not exist"}
    if is_encrypted_file(p):
        return {"path": str(p), "skipped": "already encrypted"}
    if not key or len(key) < 8:
        raise EncryptToolError("use at least 8 characters")
    # BEFORE the plaintext snapshot below: a key that cannot be written as text (a lone surrogate) is refused with fixed words,
    # and no file is made on the drive for it.
    passphrase_bytes(key, error=EncryptToolError)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot = p.with_name(f"pre-encrypt-{ts}-{p.name}")
    removed: list[str] = []  # the side files already gone when a step was refused: what the message may still claim
    swapped = False
    try:
        snapshot_to_plaintext(p, snapshot)  # inside: a snapshot a full disk cut short is a partial plaintext copy too
        swapped, retired = _export_and_swap(p, key, ts, library, removed)
    except BaseException:
        # R742: an AUTOMATIC retry (the next unlock) that fails before anything was touched drops the snapshot it just made, so a
        # store that keeps failing (a held file, a full disk) does not leave one more full plaintext copy at every start. The
        # operator's own run keeps it, as it always did: the snapshot is that run's documented escape hatch.
        if not keep_snapshot_on_failure and not swapped and not removed:
            try:
                snapshot.unlink(missing_ok=True)
            except OSError:
                _LOG.warning("encrypt: a snapshot made for a retry that failed could not be removed")
        raise
    # R742: the key is handed over the moment the file is ciphertext, BEFORE the read-back: a read-back that fails must not leave the
    # app keyless against a file it has just encrypted.
    if on_swapped is not None:
        on_swapped()
    try:
        tables = len(_table_counts_safe(p, key))  # read back with the key BEFORE the replaced file is overwritten
    finally:
        # Even when the read-back fails: the second name is a plaintext copy nobody asked for, and the deliberate escape hatch is
        # the snapshot. A crash between the swap and here leaves it named ``*.replaced-<time>``; the next unlock removes it.
        overwritten = _shred_retired(retired)
    _LOG.info("encrypted %s (snapshot kept: %s)", p.name, snapshot.name)
    return {
        "path": str(p),
        "encrypted": True,
        "tables": tables,
        "replaced_file_overwritten": overwritten,
        "plaintext_snapshot": str(snapshot),
        "snapshot_note": "kept ON PURPOSE as your escape hatch -- delete it once "
        "you have unlocked successfully and are satisfied",
    }


def _export_and_swap(p: Path, key: str, ts: str, library: bool, removed: list[str]) -> tuple[bool, Path | None]:
    """Export, verify and swap (the body of :func:`encrypt_database`). ``removed`` collects the side files removed inside the window.
    Returns ``(True, the replaced file's second name or None)`` once the swap is made; raises otherwise."""
    enc_tmp = p.with_name(p.name + f".enc-{ts}")
    try:
        reencrypt_plain_to(p, enc_tmp, key)

        src = connect(p, check_same_thread=False)
        try:
            want = _table_counts(src)
        finally:
            src.close()
        chk = connect(enc_tmp, key=key, check_same_thread=False)
        try:
            ok = chk.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            got = _table_counts(chk)
        finally:
            chk.close()
        if not ok or got != want:
            raise EncryptToolError(
                f"verification failed on {p.name} (quick_check={ok}, counts match="
                f"{got == want}); the original file is untouched"
            )

        retired = _retired_name(p, ts)
        try:
            with _library_window(enc_tmp) if library else nullcontext():
                for suffix in ("-wal", "-shm"):
                    stale = p.with_name(p.name + suffix)
                    # the guard-clause form, not ``if stale.exists(): stale.unlink()``: a loop whose body ends in a bare ``if`` has its back-edge
                    # outside the exception table of the ``try`` around it on CPython 3.13 (R163; tests/test_gates_survive_an_interrupt.py)
                    if not stale.exists():
                        continue
                    os.unlink(stale)
                    removed.append(suffix)
                retired = _link_retired(p, retired)
                try:
                    os.replace(enc_tmp, p)  # atomic on the same filesystem
                except OSError:
                    _drop_name(retired)  # only the second NAME goes: the plaintext file is still the library under its own name
                    raise
        except OSError as refused:
            # Windows: a request of this app or another program still had the file open (R741, row 145). No retry here: the gate this
            # holds may be what that request waits on. Fixed words, the chain cut (the OS's text names a path). ONLY for the library:
            # the words name the library file and say it was not encrypted, which is true only for the corpus, the FIRST store
            # ``encrypt_all`` encrypts. A later store (the custody log, a lane) refused after the corpus became ciphertext keeps the
            # error it always raised, never a sentence that would tell the operator nothing was encrypted.
            from src.backup.merge import _file_is_locked

            if not library or not _file_is_locked(refused):
                raise
            raise EncryptToolError(_held_words(removed)) from None
    finally:
        enc_tmp.unlink(missing_ok=True)
    return True, retired


#: The two refusals of a swap Windows would not allow because the library file was still open (R741, row 145). FIXED words (keyed in every
#: locale; the page translates the detail it is given), each true at the step it is given: before any log file went, the file and its log
#: are as they were; after one went, the file was still not replaced but "untouched" would no longer be true, and the snapshot made just
#: before is the complete copy.
HELD_UNTOUCHED = (
    "A request of this app or another program was still using the library file, so it was not encrypted. The original file is untouched, "
    "and the plaintext snapshot made just before (pre-encrypt-…) is kept too. Try again when the app is idle."
)
HELD_LOG_REMOVED = (
    "A request of this app or another program was still using the library file, so it was not encrypted. The library file itself was not "
    "replaced, but its write-ahead log was already removed, so the plaintext snapshot made just before (pre-encrypt-…) is the complete copy. "
    "Try again when the app is idle."
)


def _held_words(removed: list[str]) -> str:
    # Only the ``-wal`` carries saves; a removed ``-shm`` is an index SQLite rebuilds, so the file is still whole without it.
    return HELD_LOG_REMOVED if "-wal" in removed else HELD_UNTOUCHED


@contextmanager
def _library_window(enc_tmp: Path) -> Iterator[None]:
    """The window in which the library's name is moved onto the encrypted copy: connections made before it are refused from here on,
    and the log names about to be removed are announced (``disk_changing``) so a replace that fails after that point does not give the
    earlier connections their validity back. A window that cannot be had (a connection still being opened after its wait) is a named
    refusal before anything was touched."""
    from src.database import library_generation

    try:
        with library_generation.swap_window(enc_tmp):
            library_generation.disk_changing()
            yield
    except library_generation.LibraryBusy:
        raise EncryptToolError(
            "a connection to the library was still being opened, so the file was not replaced; the original file is untouched"
        ) from None


#: The second name a replaced plaintext store carries between the swap and its overwrite (``<store>.replaced-<time>``).
RETIRED_INFIX = ".replaced-"


def _retired_name(p: Path, ts: str) -> Path | None:
    return p.with_name(f"{p.name}{RETIRED_INFIX}{ts}")


def _link_retired(p: Path, retired: Path | None) -> Path | None:
    """A second name for the plaintext file, made just before the replace, so that once the encrypted copy has taken the library's
    name the replaced file can still be reached and overwritten (R742: the replaced file goes through the secure-delete path rather
    than being left to the free space). A file system that cannot link (FAT) or a refusal gives no second name: the encryption goes
    on, and the report says the replaced file was not overwritten."""
    if retired is None:
        return None
    try:
        os.link(p, retired)
    except OSError:
        return None
    return retired


def _drop_name(retired: Path | None) -> None:
    if retired is None:
        return
    try:
        os.unlink(retired)
    except OSError:
        _LOG.warning("encrypt: a second name of the library file could not be removed")


def _shred_retired(retired: Path | None) -> bool:
    """Overwrite and remove the replaced plaintext file through the crypto-erase path. True only when every byte was overwritten.
    The overwrite is defence in depth only (SSDs and copy-on-write file systems may keep old blocks); the pre-encrypt snapshot
    beside the store is a separate, deliberate plaintext copy that the operator deletes."""
    if retired is None:
        return False
    from src.safety.crypto_erase import _shred

    _seen, overwritten, unlinked = _shred(retired)
    if not unlinked:
        _LOG.warning("encrypt: the replaced plaintext file could not be removed after its overwrite")
    return bool(overwritten)


def dispose_lane_engines() -> None:
    """Close any lane pool: the store swap replaces the file underneath, and a cached engine would go on using a handle to the
    replaced one. Never raises."""
    try:
        from src.versioned.store import dispose_all as _dispose_lanes

        _dispose_lanes()
    except Exception as exc:  # noqa: BLE001 - never let bookkeeping block the encryption
        log_failure(_LOG, "could not dispose the lane engines before encrypting", exc, level=logging.WARNING)


#: A store already encrypted that the key does not open: it is not the operator's passphrase's store, and nothing here may treat it
#: as done (R742: a store is recorded only once it reads back with the key).
NOT_THIS_KEY = "a store is already encrypted, but not with this passphrase, so it was left as it is"


def encrypt_store(
    name: str,
    path: Path,
    key: str,
    *,
    main: Path | None = None,
    library: bool = False,
    on_swapped: Callable[[], object] | None = None,
    keep_snapshot_on_failure: bool = True,
) -> dict:
    """One store's step: encrypt it (idempotent: an already-encrypted store is skipped), read it back with the key, and only then
    add it to the at-rest record (R742). An absent store is skipped and not recorded. The custody log is swapped holding its own
    append lock: its appends are serialised there, not on the write gate, so no append runs while the file is replaced. (A log a
    caller opened BEFORE the swap and keeps open is kept out by the exclusive window and the wait for work in flight that both
    callers take, not by this lock.)"""
    from src.database import at_rest_state

    if name == "custody":
        from src.custody.log import _APPEND_LOCK

        guard: AbstractContextManager[object] = _APPEND_LOCK
    else:
        guard = nullcontext()
    with guard:
        report = encrypt_database(
            path, key, library=library, on_swapped=on_swapped, keep_snapshot_on_failure=keep_snapshot_on_failure
        )
    if report.get("skipped") == "file does not exist":
        return report
    if report.get("skipped") == "already encrypted":
        try:
            _table_counts_safe(Path(path), key)
        except Exception:  # noqa: BLE001 - any failure to read it with this key means it is not this key's store
            raise EncryptToolError(NOT_THIS_KEY) from None
    at_rest_state.record_encrypted(name, main)
    return report


#: The words when the library was encrypted and at least one other store was not (R742). The key is already held, so the app goes
#: on with the encrypted library; the stores left are finished at the next unlock, or by pressing the encrypt button again now.
PARTIAL = (
    "The library is now encrypted with this passphrase and stays open with it: keep the passphrase, it is required at every start. "
    "Some other stores could not be encrypted yet and are still unencrypted; they are finished at the next unlock, or press "
    "the encrypt button again now. Settings shows which."
)


class EncryptPartial(EncryptToolError):
    """The library is encrypted and the key is held, but ``pending`` stores are still plaintext (R742)."""

    def __init__(self, pending: list[str]) -> None:
        super().__init__(PARTIAL)
        self.pending = list(pending)


def _table_counts_safe(p: Path, key: str) -> dict:
    conn = connect(p, key=key, check_same_thread=False)
    try:
        return _table_counts(conn)
    finally:
        conn.close()


def _still_plaintext(rows: list[tuple[str, Path]]) -> list[str]:
    """The stores whose header reads as plaintext. Its own function for the same reason as :func:`_encrypt_the_rest`."""
    return [name for name, path in rows if is_encrypted_file(path) is False]


def _encrypt_the_rest(rows: list[tuple[str, Path]], key: str, main: Path, reports: dict) -> list[str]:
    """Each store after the library is its own step; one that fails stays plaintext and is named, and the others go on.

    A function of its own so the loop has no ``with`` around it in its own scope (tests/test_database_loop_heads_are_classified.py): an
    interrupt landing on its back-edge leaves this frame normally, and ``encrypt_all``'s ``write_lock`` is released by its own ``with``."""
    pending: list[str] = []
    for name, path in rows:
        try:
            reports[name] = encrypt_store(name, path, key, main=main)
        except Exception as exc:  # noqa: BLE001 - a later store's failure must not hide that the library is encrypted
            log_failure(_LOG, f"the {name} store could not be encrypted yet; it stays pending", exc, key, level=logging.WARNING)
            pending.append(name)
    return pending


def encrypt_all(key: str, *, on_library_encrypted: Callable[[], object] | None = None) -> dict:
    """Encrypt EVERY at-rest store under THE one passphrase (design D6).
    The caller disposes the engine before and re-opens after.

    THE LIST IS THE FEATURE, and it is the part that rots. This function enumerated
    the corpus and the custody log for as long as those were the only two databases.
    The versioned-source LANES (``wiki.db`` / ``law.db`` / ``osm.db``) are encrypted
    stores too, and left out they would survive "Encrypt my store" untouched: the
    operator consents, the corpus becomes ciphertext, and the lane stays plaintext on
    disk FOREVER — every later open takes ``connect()``'s plaintext branch, which never
    consults the passphrase at all. The lane holds which sources the operator tracks,
    which is exactly the selection Q1005 = a says is as revealing as the data.

    So the lanes are read from the REGISTRY (``src.versioned.lanes``) rather than listed
    here, and an absent lane is skipped rather than created — ``encrypt_database``
    already reports ``skipped`` for a file that does not exist, which is how the custody
    log has always been handled.

    Held under the single-writer gate (audit finding 2026-07-17): encrypt_database
    reads the live file through a RAW sqlcipher3/sqlite3 connection, not the ORM
    session the gate's flush/commit events watch, so without an EXPLICIT hold a
    concurrently-committing scraper could write new rows into the plaintext file
    AFTER the encrypted copy is built but BEFORE the atomic swap -- those rows
    would be silently discarded when the swap lands. The gate makes every other
    writer QUEUE (never error) for the duration, exactly its documented purpose;
    holding it across this one-time, user-consented, non-hot-path operation is
    the safe tradeoff over risking silent data loss.
    """
    from src.api.unlock import main_db_path
    from src.database import at_rest_state
    from src.database.writer import write_lock

    # First of all, before the gate is taken and before any store is looked at: a key that cannot be written as text is refused
    # with fixed words (``encrypt_database`` asks again, for its own callers).
    passphrase_bytes(key, error=EncryptToolError)
    main = main_db_path()
    if main is None:
        raise EncryptToolError("non-SQLite backend: the at-rest layer does not apply")
    # The lanes BESIDE THE CORPUS THIS CALL IS ENCRYPTING (``main.parent``), never from ``data_dir()`` independently: the two
    # resolvers do not always agree (``main_db_path()`` reads ``DATABASE_URL``, computed at import), and encrypting a corpus in one
    # directory and lanes in another would leave the real lanes untouched while reporting success. ``at_rest_state.stores`` is the
    # one list, shared with the status and the finish, so the three can never disagree about a file.
    rows = at_rest_state.stores(main)
    reports: dict = {}
    with write_lock():
        # The corpus FIRST, alone: a failure here leaves every store as it was (nothing is encrypted yet), so it is raised as before.
        name, path = rows[0]
        # R742: the key is held the moment the library is ciphertext (``on_swapped``, before its read-back), so whatever happens next
        # the app goes on with the library it can open, never keyless against an encrypted file. A library already encrypted (the
        # retry) hands it over once it has read back with the key.
        handed: list[int] = []

        def _hand() -> None:
            handed.append(1)
            if on_library_encrypted is not None:
                on_library_encrypted()

        try:
            reports[name] = encrypt_store(name, path, key, main=main, library=True, on_swapped=_hand)
        except Exception as exc:
            if not handed:
                raise  # nothing was swapped: every store is as it was, raised as before
            # The library IS ciphertext and the key is held, but it did not read back: the other stores are left for the next
            # unlock (or the encrypt button), and the caller takes the partial path (the keyed pool, the plaintext serves retired).
            log_failure(_LOG, "the library is encrypted but did not read back with the key", exc, key, level=logging.WARNING)
            raise EncryptPartial(_still_plaintext(rows[1:])) from None
        if not handed:
            _hand()
        dispose_lane_engines()
        pending = _encrypt_the_rest(rows[1:], key, main, reports)
    if pending:
        raise EncryptPartial(pending)
    return reports
