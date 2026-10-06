"""The per-table check after an unexpected stop (damaged-database plan, slice E2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. E1 (``database/damage.py``) notices a damaged file when something READS it and fails. A file that
is damaged but not read keeps collecting into it: measured on the Asus bundle, a corpus SQLite called
malformed from 2026-10-02 while ``count(*)``, ``max(id)`` and the first page all answered and collection
went on for a day and a half. After an unexpected stop (a kill, a power loss, a machine that went down) the
app now reads each table once, BEFORE collection writes to the file again.

WHAT IT DOES. For the corpus file and the Wikipedia and law files (the three files ``damage`` pauses),
when the previous session ended unclean (the session ledger knows) or an earlier check was left
unfinished: list the tables, smallest first when the planner's statistics say which is smallest, and run
``PRAGMA quick_check(<table>)`` on each, every one on its own read-only connection. A table is

* ``damaged`` when the check reports a problem (anything but ``ok``) or raises ``SQLITE_CORRUPT``,
* ``unchecked`` (NEVER damaged) when the file is busy or locked, a passphrase is missing or wrong, the driver reported a disk
  I/O error (``SQLITE_IOERR``) that stopped the read, or the check was stopped. Not reading is not a verdict. (SQLite 3.43 and
  later report a failed READ of a page as ``SQLITE_IOERR_CORRUPTFS``, which reaches the application as ``SQLITE_CORRUPT``: such a
  read is filed ``damaged`` here, as SQLite itself reports it, and is listed in the open queue as a limit; only the page pass
  below tells a read it could not make from a page that failed.)

AN ENCRYPTED FILE IS ASKED A SECOND QUESTION when the first one did not answer. Measured on a 500-article store
(367 pages of 16 KiB): of 40 single pages overwritten with random bytes, ``quick_check`` of the table filed 10 files
``damaged`` and 30 ``unchecked``, because under SQLCipher a page that fails its authentication tag makes the check raise the
driver's generic ``SQLITE_ERROR`` ("SQL logic error", code 1) as often as it makes it answer a row, depending on which page of
which table it is. ``PRAGMA cipher_integrity_check`` names the pages that fail ("HMAC verification failed for page N"): it
named the damaged page in 9 of 9 files tried, every ``unchecked`` one among them. So when a table came back ``unchecked`` WITH
that code, on a file whose header is ciphertext, the file is asked once (:func:`confirm_encrypted_damage`) and the answer is
recorded as one more entry, ``(pages)``: ``damaged`` when any page fails (the page numbers kept up to
:data:`MAX_PAGES_LISTED`, the count always), ``ok`` when none does (the tables that did not answer STAY unchecked, so the
file is not called clean), ``unchecked`` with the reason when the pass could not be made or could not read the file to the end.
A main file LONGER THAN 4 GiB is not given to it (:data:`PAGE_PASS_LIMIT_BYTES`: past that point the pass reads the wrong bytes, measured on a
healthy 4.52 GB file as a failure for every page from the first past 4 GiB), so such a file's pass is ``unchecked`` with that reason and
its unanswered tables stay unchecked.
Nothing else asks it: a healthy file, a wrong passphrase and a busy or locked file never reach it (an I/O error reaches it only as
the generic error a failing page also gives, and the pass then says what it read: a page it could not read is counted apart from a
page that failed, and is never filed as damage).

A DAMAGED ANSWER IS A SECOND READ'S TO CONFIRM (the coordinator's ruling, R100: a verdict must be measured). A table, the list of tables (``(schema)``)
and the page pass (``(pages)``) that report damage are read AGAIN, on a NEW connection, and are filed ``damaged`` only when the second read agrees
(``second_read: agreed`` on the entry). A second read that is clean (``second_read: clean``) or could not be made (``second_read: unavailable``,
with ``second_detail`` saying why: busy, locked, a stop, an I/O error) files the entry ``unchecked`` instead, with the first read's own first line kept
(``first_read``) and the sentence "nothing was concluded": nothing latches, nothing is repaired and the file is not called clean either. An ``ok`` or an
``unchecked`` first read is final and costs one read, so only a damaged answer costs two. A re-read that settles nothing never replaces a finding two reads
agreed on earlier (``DamageRegistry.recheck_finished`` keeps the older ``damaged`` entry over a newer ``unchecked`` one). What a second read does NOT
prove: it is not independent of the machine's state (a pressure that lasts through both reads fails both), so it is a guard against a read that
differs, not a proof of damage; the page numbers of the first pass are the ones kept.

The results go into the damage record (``verification``, per file, a few hundred bytes a table), and a
damaged table latches its file by the SAME door a corruption error does (``DamageRegistry._apply_incident``):
the scope is ``search-index`` only when every damaged table belongs to the full-text index, else ``data``.

WHEN, AND WHY THEN. ``arm_at_boot`` is the start-up upkeep's FIRST statement and arms the
registry (``verifying()``): from then until the check ends collection waits (the storage guard's
``"verifying"`` kind), so an operator who goes online in the seconds before the sequence reaches the check
does not slip a pass in first. The check is the boot sequence's FIRST step, ahead of the cache warm-up, the
rollup and the re-index, so nothing heavy competes with it. The app is offline at boot (R117) and starts no
collection by itself, so the read pins nothing a writer needs; the startup upkeep's own small writes
(statistics, the catalogue seed) happen before the sequence's thread starts and are not stopped.

A check that is DUE is also written down as ``state: owed`` the moment it is armed, and by a boot that stays
locked (``owe_at_locked_boot``: it cannot arm, the key is not there). The ledger reads a session that closed
before the check began as a CLEAN end, so without the record the next start would forget the unexpected stop
that made the check due. ``owed`` is read as an unfinished check and is not an attempt.

WHAT THE PAGE PASS COSTS, and why it stays inside the check's own budget. It is one sequential read of the file with one
HMAC per page, on a read-only connection that is closed on every path, with no temporary file (it runs in the C library and
neither sorts nor spills). MEASURED 2026-10-06 on a 234 MB store of 60,000 articles in the app's full schema at 16 KiB pages (4
vCPU, page cache dropped before the first run): the pragma took 1.0 s on a healthy file (about 230 MB/s, 4.3 s per GB) and 1.0 s with
356 of its 14,266 pages overwritten (all 356 named); through :func:`confirm_encrypted_damage` 1.2 to 1.3 s, the keyed open being the rest; peak resident memory 47 MB before the pass and 48 MB at its end, which is the
process's own on a healthy file. WHAT GROWS WITH THE DAMAGE, measured (a 4 GB copy, 247,877 failing pages): SQLCipher computes the
whole check while the statement is prepared and holds one result row per failing page inside SQLite before this code reads the
first, +25 MB resident (about 100 bytes a page; about 100 MB at a million failing pages, a 16 GB file in which every page failed;
+0 at 2,035 failing pages and +1 MB at 14,242). The code's own side is bounded: it keeps a count and the :data:`MAX_PAGES_LISTED`
lowest page numbers, never a row per failing page (a set of them was 65 MB more at a million pages). The 61 per-table checks of the same file took 12.6 s (a keyed connection each, 0.17 s of key
derivation apiece), so the pass adds under a tenth to a check that found a problem and runs at all only for one. The attempt budget is
the check's own: the pass runs inside the file's entry (``running`` until it is done), so a process killed in it leaves the entry the next
start counts as one unfinished attempt, ``MAX_VERIFY_ATTEMPTS`` of them in a row. It is NOT interruptible once begun (a single C loop answers
no progress handler: about a second per 230 MB, 19 s at 4 GB), so a stop is looked for before it starts. A quit does NOT let a pass that
began end (the thread is a daemon): :func:`stop` gives the attempt back at once, the pass's answer is dropped and the next start reads
the file again; only a kill counts. The progress line names the pass (``(pages)``) while it runs, and the app serves from the moment
the boot sequence's thread starts: only collection waits for the check, as it already does.

WHAT IT DOES NOT DO. It does not repair or salvage (E3), and it does not release a latch: a clean verdict
says what this read found, not that an earlier error was wrong. It checks the STRUCTURE of each table and
its indexes (``quick_check``): that the pages of each b-tree are well formed and its records readable. It does NOT
check that an index agrees with its table, or every row's content. The search index is a virtual table, and from
SQLite 3.44 ``quick_check(<virtual table>)`` asks that module to check itself (FTS5's own integrity check of its
inverted index; it does not compare the index with the articles: with the app's external-content ``article_fts`` a
changed article text still answers ``ok``; measured 0.65 s against 0.20 s for the content table alone on a 100 MB
store), so the index is checked with its shadow tables; on an older SQLite that call reads nothing and the shadow tables are all there
is. It is not run beside collection on a big store on purpose: ``quick_check`` holds a read snapshot for the
whole of a table, which is what pins the log.

A CHECK THAT DOES NOT FINISH is tried again at the next start, at most ``damage.MAX_VERIFY_ATTEMPTS`` starts
in a row: a check that itself brings the process down must not become a boot loop that never reaches
collection. The record says which files were skipped and why. ``OO_BOOT_VERIFY=0`` turns the check off.
"""
from __future__ import annotations

import contextlib
import functools
import heapq
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from src.database import damage
from src.database.damage import VERDICT_DAMAGED, VERDICT_OK, VERDICT_UNCHECKED

_LOG = logging.getLogger(__name__)

TRIGGER_UNCLEAN_END = "unclean-end"
TRIGGER_UNFINISHED = "unfinished-check"
TRIGGER_DAMAGE_FOUND = "damage-found-before"

#: The name a check gives to a schema it could not read (the file's list of tables), in place of a table.
SCHEMA_ENTRY = "(schema)"

#: The name the page pass gives to its entry, in place of a table (see :func:`confirm_encrypted_damage`).
PAGES_ENTRY = "(pages)"

#: How many failing page NUMBERS the ``(pages)`` entry keeps. It protects the record's size (a few hundred bytes a table, and
#: the whole record rides the Diagnostics zip, which stays under 4 MB) from a file in which every page fails, which
#: is a count of pages in the hundreds of thousands on a big store; the count of failing pages is ALWAYS kept
#: (``pages_total``), so a cut list never reads as the whole finding.
MAX_PAGES_LISTED = 32

#: SQLite's primary result code for the generic error, and the text the driver gives it. A table whose check raised THIS is the
#: one a page pass is made for; "no such module" or "no such function" are the same primary code with a text of their own.
_SQLITE_ERROR = 1
_GENERIC_TEXT = "sql logic error"

#: The answer of ``PRAGMA cipher_integrity_check`` for one failing page.
_HMAC_ROW = re.compile(r"HMAC verification failed for page (\d+)")

#: The rows of the same pragma that say the PASS could not read a page or could not run, which is not a page that failed its
#: authentication tag: a disk error on a page ("error reading 16384 bytes from file page 40 at offset 638976", measured with a
#: ``pread`` that returned EIO: the pass ANSWERS this as a row, it does not raise), the crypto provider failing, a build without
#: the integrity check, and a connection with no database. THE OFFSET CAN BE NEGATIVE: SQLCipher prints it through a 32-bit
#: ``%d``, so a page at 2 GiB or later prints a negative number (measured on a 3 GiB store with EIO at page 140000: "error reading
#: 16384 bytes from file page 140000 at offset -2001223680"), and a pattern that wanted digits only filed that row as a row nobody
#: knows, which is damage (the coordinator's check of E2). Not reading is not a verdict (R100): a pass whose only rows are these
#: is ``unchecked``, and beside a page that did fail they are counted, never dropped. Any OTHER row is still damage in its own
#: words, because an answer this app cannot read is not a clean one.
_COULD_NOT_READ = re.compile(
    r"error reading \d+ bytes from file page \d+ at offset -?\d+"
    r"|HMAC operation failed for page \d+"
    r"|HMAC is not enabled, unable to integrity check"
    r"|database file is undefined"
)

#: A main file larger than this is NOT given to the page pass. WHAT IT PROTECTS: the verdict. MEASURED (the coordinator's check of
#: E2b): on a HEALTHY 4.52 GB store of 16 KiB pages, ``quick_check`` answered ``ok`` and every byte read fine through the codec, yet
#: ``PRAGMA cipher_integrity_check`` answered 13,934 "HMAC verification failed" rows, one for every page from 262,145 on (the first
#: page that starts at 2^32); a ``pread`` shim saw no read at or past 4 GiB, so the pass's offsets wrap and it checks the wrong bytes.
#: The pass builds every row before it returns the first (+28 MB at 260,000 rows, about 113 bytes a false row, about 250 MB on a
#: 40 GB corpus), so filtering the rows afterwards still reads the whole file and holds them: the file is skipped, ``unchecked``
#: with the reason, and the table that sent it here stays unchecked, so the file is not called clean either. A page that starts at
#: 2^32 or later exists exactly when the file is longer than 2^32 bytes (page sizes are powers of two).
PAGE_PASS_LIMIT_BYTES = 1 << 32

#: What the record says of a file the page pass was not run on. WHAT THE LENGTH PROTECTS: the sentence is cut at ``DETAIL_CHARS`` like every
#: detail line, and the half that matters (the pages were NOT checked) is its end, so it stays under that (pinned by a test); the
#: measurement is in :data:`PAGE_PASS_LIMIT_BYTES`'s comment and the module docstring.
_OVER_LIMIT_REASON = "the file is longer than 4 GiB, where the page check reads the wrong bytes (measured), so its pages were not checked"

#: What a damaged answer is filed as when the SECOND read, on a new connection, did not repeat it (a verdict must be measured, R100; a read that
#: two connections disagree about measured nothing). ``second_read`` is the KEY on the entry: ``agreed`` (the damage stands), ``clean`` (the
#: second read answered ``ok``, or listed the tables) or ``unavailable`` (it could not be made: busy, locked, a passphrase, a stop, an I/O error).
#: WHAT THE LENGTH PROTECTS: each sentence is cut at ``DETAIL_CHARS`` like every detail line and the half that matters (nothing was concluded) is
#: its end, so both stay under that (pinned by a test).
SECOND_READ_AGREED = "agreed"
SECOND_READ_CLEAN = "clean"
SECOND_READ_UNAVAILABLE = "unavailable"
_DIFFERENTLY = "a second read on a new connection did not report the damage the first one did, so nothing was concluded"
_SECOND_UNMADE = "a second read on a new connection could not be made, so the damage the first one reported is not confirmed and nothing was concluded"


def _size_of(path: Path) -> int:
    """The main file's length, or 0 when it cannot be read (the pass then says what it could not open)."""
    try:
        return path.stat().st_size
    except OSError:
        return 0

#: How many of a table's report lines, and how many characters of each, the record keeps. A check's
#: lines name pages and index entries ("Tree 5 page 1234: ...", "row 7 missing from index ix_x"), never a
#: value, but a table with thousands of problems is one finding, not thousands of lines.
DETAIL_LINES = 3
DETAIL_CHARS = 160

#: The progress handler's period: how many VM steps run between two looks at the stop flag.
_PROGRESS_STEPS = 100_000

_LOCK = threading.Lock()
_PLAN: dict[str, Any] | None = None
_CANCEL = threading.Event()
#: The file whose page pass is in flight (it cannot be interrupted: see :func:`stop`), and the files whose attempt a stop has already
#: given back in this run, so that the stop and the run's own end never give it back twice. Both under ``_LOCK``.
_PASS_FILE: str | None = None
_GAVE_BACK: set[str] = set()
#: Whether the thread that runs the armed check has been started (see :func:`hand_over`).
_HANDED_OVER = False

Opener = Callable[[Path], Any]


def switch_on() -> bool:
    """``OO_BOOT_VERIFY=0`` turns the check after an unexpected stop off."""
    return os.getenv("OO_BOOT_VERIFY", "1") != "0"


# --- reading one file ----------------------------------------------------------------------------


def _open(path: Path):
    """A read-only connection through the ONE factory every engine uses (SQLCipher, the search index's
    functions), opened ``mode=ro``: the last connection to close a file with a leftover write-ahead log folds the
    log into it and deletes it, and ``query_only`` does not prevent that, so a check that only reads must not be
    the thing that does it (see ``connect.connect``'s ``read_only``, whose price is a directory its process can
    write to). ``query_only`` stays on as well: nothing on it can ever write."""
    from src.database.connect import connect

    if not Path(path).is_file():
        # ``connect`` CREATES a missing file (plaintext under OO_DB_PLAINTEXT=1, encrypted when a key is held):
        # a check must never be the thing that makes a data file exist.
        raise FileNotFoundError(f"{Path(path).name} does not exist")
    con = connect(str(path), check_same_thread=False, timeout=30, read_only=True)
    try:
        con.execute("PRAGMA query_only=ON")
    except Exception:
        con.close()
        raise
    return con


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


#: FTS5 reports an error that stopped ITS check as a ROW, "unable to validate the inverted index for FTS5 table X:
#: <the error's own text>" (measured on SQLite 3.45.1: an allocation failure comes back as a result, not an exception),
#: so a row naming one of these is a read that could not finish, never damage.
_WRAPPED_FTS = "unable to validate the inverted index"
_NOT_DAMAGE_TEXT = (
    ("out of memory", "the read ran out of memory"),
    ("disk i/o error", "a disk I/O error stopped the read"),
    ("database or disk is full", "the disk was full"),
    ("interrupted", "the check was stopped"),
    ("database is locked", "the file was locked"),
    ("database table is locked", "the file was locked"),
    ("unable to open database file", "the file could not be opened"),
)


def _unread_reason(lines: list[str]) -> str | None:
    """The reason, when EVERY answer line is FTS5 saying its own check could not run (see ``_WRAPPED_FTS``)."""
    reasons: list[str] = []
    for ln in lines:
        low = ln.lower()
        if _WRAPPED_FTS not in low:
            return None
        why = next((r for needle, r in _NOT_DAMAGE_TEXT if needle in low.split(":")[-1]), None)
        if why is None:
            return None
        reasons.append(why)
    return reasons[0] if reasons else None


_SQLITE_REASONS = {
    5: "the file was busy",
    6: "the file was locked",
    9: "the check was stopped",
    10: "a disk I/O error stopped the read",
    14: "the file could not be opened",
    26: "the file did not open as a database (a wrong passphrase, or a damaged first page)",
}


def classify_error(exc: BaseException) -> tuple[str, str]:
    """``(verdict, reason)`` for an exception a check raised. ``damaged`` ONLY for ``SQLITE_CORRUPT``
    (``damage.corruption_of``, the driver's own code); every other failure is ``unchecked`` with the reason in
    plain words, because a read that could not happen says nothing about the file."""
    found = damage.corruption_of(exc)
    if found is not None:
        return VERDICT_DAMAGED, found["message"] or "SQLITE_CORRUPT"
    try:
        from src.database.connect import DatabaseLockedError, WrongPassphraseError

        if isinstance(exc, DatabaseLockedError):
            return VERDICT_UNCHECKED, "the library is locked by its passphrase"
        if isinstance(exc, WrongPassphraseError):
            return VERDICT_UNCHECKED, "the passphrase did not open the file"
    except Exception:  # noqa: BLE001
        pass
    driver = damage.driver_error(exc) or exc
    code = getattr(driver, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) in _SQLITE_REASONS:
        return VERDICT_UNCHECKED, _SQLITE_REASONS[code & 0xFF]
    return VERDICT_UNCHECKED, type(exc).__name__


def is_generic_error(exc: BaseException) -> bool:
    """Whether ``exc`` is the driver's generic ``SQLITE_ERROR`` ("SQL logic error"): what a page that fails its authentication tag
    makes SQLCipher raise in about three tries of four (module docstring). Corruption (its own code), a passphrase problem, a
    busy or locked file and an I/O error are NOT: each has a code and a reason of its own, and none of them reaches the page pass.
    The text is part of the test because other errors share the primary code (``no such module``, ``no such function``): those
    say what is missing, and a pass over the file would explain nothing about them."""
    if damage.corruption_of(exc) is not None:
        return False
    driver = damage.driver_error(exc)
    code = getattr(driver, "sqlite_errorcode", None)
    return isinstance(code, int) and (code & 0xFF) == _SQLITE_ERROR and str(driver).lower().startswith(_GENERIC_TEXT)


def _error_of(exc: BaseException) -> dict[str, Any]:
    """The ``error`` answer of :func:`inspect_file`: ``(verdict, reason)``, and ``sqlite_code`` when it was the generic error."""
    out: dict[str, Any] = {"error": classify_error(exc)}
    if out["error"][0] == VERDICT_UNCHECKED and is_generic_error(exc):
        out["sqlite_code"] = _SQLITE_ERROR
    return out


def inspect_file(path: Path, *, opener: Opener | None = None) -> dict[str, Any]:
    """The tables of ``path`` in the order they will be checked, and a few facts about the file. ``{"names",
    "facts"}``, or ``{"error": (verdict, reason)}`` when even the list could not be read (a schema that
    cannot be read is damage; anything else is unchecked).

    Order: smallest first by the row counts the planner's statistics hold (``sqlite_stat1``, which the
    app's own start-up refreshes), a table without a statistic after those, ties by name. The order matters
    only for how soon the small tables get a verdict; it is a heuristic, never a claim about size."""
    try:
        con = (opener or _open)(path)
    except Exception as exc:  # noqa: BLE001
        return _error_of(exc)
    try:
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        rows: dict[str, int] = {}
        with contextlib.suppress(Exception):
            for tbl, _idx, stat in con.execute("SELECT tbl, idx, stat FROM sqlite_stat1").fetchall():
                first = str(stat or "").split(" ")[0]
                if first.isdigit():
                    rows[tbl] = max(rows.get(tbl, 0), int(first))
        facts: dict[str, Any] = {}
        for pragma in ("page_size", "page_count", "freelist_count"):
            with contextlib.suppress(Exception):
                facts[pragma] = con.execute(f"PRAGMA {pragma}").fetchone()[0]
        sizes = damage._sizes(path)
        facts["file_bytes"], facts["wal_bytes"] = sizes.get("file_bytes"), sizes.get("wal_bytes")
        names.sort(key=lambda n: (n not in rows, rows.get(n, 0), n))
        return {"names": names, "facts": facts}
    except Exception as exc:  # noqa: BLE001
        return _error_of(exc)
    finally:
        with contextlib.suppress(Exception):
            con.close()


def inspect_confirmed(path: Path, *, opener: Opener | None = None) -> dict[str, Any]:
    """:func:`inspect_file`, with an answer that reads as DAMAGE (a schema that cannot be read) read again on a NEW connection:

    * the first answer, unchanged, when it was not damage (the list, or a reason that is not damage);
    * the first answer with ``second_read: agreed`` when the second read reports damage too;
    * the SECOND read's list with ``second_read: clean`` and ``first_read`` (the first read's reason) when it lists the tables: the list is the
      answer, the caller reads every table, and files a ``(schema)`` entry that is ``unchecked`` (:func:`_not_concluded`);
    * ``error: (unchecked, ...)`` with ``second_read: unavailable``, the second read's own ``sqlite_code`` and ``second_detail`` when the second
      read could not be made.
    Nothing latches on a listing that two connections disagree about."""
    first = inspect_file(path, opener=opener)
    err = first.get("error")
    if err is None or err[0] != VERDICT_DAMAGED:
        return first
    second = inspect_file(path, opener=opener)
    err2 = second.get("error")
    if err2 is not None and err2[0] == VERDICT_DAMAGED:
        return {**first, "second_read": SECOND_READ_AGREED}
    seen = [err[1][:DETAIL_CHARS]]
    if err2 is None:
        return {**second, "second_read": SECOND_READ_CLEAN, "first_read": seen}
    return {
        **second,
        "error": (VERDICT_UNCHECKED, _SECOND_UNMADE),
        "second_read": SECOND_READ_UNAVAILABLE,
        "first_read": seen,
        "second_detail": [str(err2[1])[:DETAIL_CHARS]],
    }


def _read_table(path: Path, table: str, *, opener: Opener | None = None, cancel: threading.Event | None = None) -> dict[str, Any]:
    """ONE read of one table (and its indexes) through ``PRAGMA quick_check``, on its own connection. Never raises."""
    t0 = time.monotonic()
    detail: list[str] | None = None
    code: int | None = None
    con = None
    try:
        con = (opener or _open)(path)
        if cancel is not None:
            with contextlib.suppress(Exception):
                con.set_progress_handler(lambda: 1 if cancel.is_set() else 0, _PROGRESS_STEPS)
        lines = [str(r[0]) for r in con.execute(f"PRAGMA quick_check({_ident(table)})").fetchall()]
        if lines == ["ok"]:
            verdict = VERDICT_OK
        elif (unread := _unread_reason(lines)) is not None:
            verdict = VERDICT_UNCHECKED
            detail = [unread[:DETAIL_CHARS]]
        else:
            verdict = VERDICT_DAMAGED
            detail = [ln.replace("\n", " ")[:DETAIL_CHARS] for ln in lines[:DETAIL_LINES]]
    except Exception as exc:  # noqa: BLE001 - the verdict IS the exception's class
        verdict, reason = classify_error(exc)
        if cancel is not None and cancel.is_set() and verdict == VERDICT_UNCHECKED:
            reason = _SQLITE_REASONS[9]
        elif verdict == VERDICT_UNCHECKED and is_generic_error(exc):
            code = _SQLITE_ERROR  # the one answer the page pass is asked after (:func:`page_check`)
        detail = [reason[:DETAIL_CHARS]]
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()
    out: dict[str, Any] = {"table": table, "verdict": verdict, "seconds": round(time.monotonic() - t0, 2)}
    if detail:
        out["detail"] = detail
    if code is not None:
        out["sqlite_code"] = code
    return out


def _not_concluded(first: dict[str, Any], second_read: str, second: dict[str, Any] | None = None) -> dict[str, Any]:
    """The entry for what ONE read reported as damaged and a second read, on a NEW connection, did not confirm: ``unchecked`` (never ``damaged``),
    with the key of what the second read did, the first read's own first line (the record says what was reported and not repeated) and, when the
    second read could not be made, why. Nothing latches on it and nothing is repaired because of it."""
    out: dict[str, Any] = {
        "table": first.get("table"),
        "verdict": VERDICT_UNCHECKED,
        "seconds": round(float(first.get("seconds") or 0) + float((second or {}).get("seconds") or 0), 2),
        "detail": [(_DIFFERENTLY if second_read == SECOND_READ_CLEAN else _SECOND_UNMADE)[:DETAIL_CHARS]],
        "second_read": second_read,
        "first_read": [str(d)[:DETAIL_CHARS] for d in (first.get("detail") or [])[:1]],
    }
    if second_read == SECOND_READ_UNAVAILABLE and second is not None and second.get("detail"):
        out["second_detail"] = [str(d)[:DETAIL_CHARS] for d in second["detail"][:1]]
    return out


def _second_read(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """The entry of a damaged first read once the second read (another entry of the same kind, made on a new connection) is in."""
    if second.get("verdict") == VERDICT_DAMAGED:
        return {**first, "second_read": SECOND_READ_AGREED, "seconds": round(float(first.get("seconds") or 0) + float(second.get("seconds") or 0), 2)}
    if second.get("verdict") == VERDICT_OK:
        return _not_concluded(first, SECOND_READ_CLEAN, second)
    return _not_concluded(first, SECOND_READ_UNAVAILABLE, second)


def check_table(path: Path, table: str, *, opener: Opener | None = None, cancel: threading.Event | None = None) -> dict[str, Any]:
    """One table (and its indexes) through ``PRAGMA quick_check``, on its own connection. Never raises.

    A ``damaged`` answer is read AGAIN, on a NEW connection, and stands only when the second read agrees (``second_read: agreed``): a read that
    two connections disagree about, or a second read that could not be made, is ``unchecked`` with the key of what happened (R100: nothing
    latches and nothing is repaired on a verdict that was not measured twice). An ``ok`` or an ``unchecked`` answer is final and costs one read."""
    first = _read_table(path, table, opener=opener, cancel=cancel)
    if first["verdict"] != VERDICT_DAMAGED:
        return first
    if cancel is not None and cancel.is_set():
        return _not_concluded(first, SECOND_READ_UNAVAILABLE, {"detail": [_SQLITE_REASONS[9]]})
    return _second_read(first, _read_table(path, table, opener=opener, cancel=cancel))


def file_verdict(tables: list[dict[str, Any]]) -> str:
    """``damaged`` if any table is, else ``ok`` if every table is, else ``unchecked``."""
    verdicts = {t.get("verdict") for t in tables}
    if VERDICT_DAMAGED in verdicts:
        return VERDICT_DAMAGED
    if tables and verdicts == {VERDICT_OK}:
        return VERDICT_OK
    return VERDICT_UNCHECKED


# --- the page pass of an encrypted file ----------------------------------------------------------------

_CHECK_PRESENT: bool | None = None


def cipher_check_present() -> bool:
    """Whether this build's SQLCipher has ``PRAGMA cipher_integrity_check``. SQLite answers a pragma it does not know with NO
    rows, which is also what this one answers for a healthy file, so the call on the file cannot tell "clean" from "not in this
    build". A keyed in-memory database can: the pragma answers it with a row ("database file is undefined") and an unknown one with
    none. Asked once per process; a build that cannot be asked counts as not having it."""
    global _CHECK_PRESENT
    if _CHECK_PRESENT is None:
        try:
            from sqlcipher3 import dbapi2 as sqc

            probe = sqc.connect(":memory:")
            try:
                probe.execute("PRAGMA key = 'probe'")  # a constant of this function, never the library's passphrase
                _CHECK_PRESENT = bool(probe.execute("PRAGMA cipher_integrity_check").fetchall())
            finally:
                probe.close()
        except Exception:  # noqa: BLE001 - no driver, or one that cannot answer: the pass is not available
            _CHECK_PRESENT = False
    return _CHECK_PRESENT


class _Kept:
    """The first ``limit`` lines of one kind of row and the count of ALL of them: a cap may shrink what is printed, never what is
    counted (the maintainer's ruling of 2026-09-11). WHAT THE LIMIT PROTECTS: the Python-side list the record is cut from (the
    engine holds every row of the pass already, so keeping another copy of the unknown ones in a pass where every row is unknown
    would double it); it is pinned by ``test_the_kept_lines_are_bounded_and_the_count_is_not``."""

    __slots__ = ("count", "limit", "lines")

    def __init__(self, limit: int) -> None:
        self.count = 0
        self.limit = limit
        self.lines: list[str] = []

    def add(self, line: str) -> None:
        self.count += 1
        if len(self.lines) < self.limit:
            self.lines.append(line)


def _page_pass(path: Path, *, opener: Opener | None = None, cancel: threading.Event | None = None) -> dict[str, Any]:
    """ONE page pass of an encrypted file: ``PRAGMA cipher_integrity_check``, once, on a read-only connection that is
    closed on every path. Never raises. ``damaged`` when any page fails its authentication tag (``pages`` the first
    :data:`MAX_PAGES_LISTED` numbers, ``pages_total`` ALL of them), ``ok`` when none does, ``unchecked`` with the reason when the
    pass could not be made: a stop was asked for before it began, this build has no such pragma, or the driver raised (the
    exception's class decides, as for a table), or the rows it answered say it could not READ (``_COULD_NOT_READ``: a disk error
    on a page is answered as a row, measured, never raised; ``pages_unread`` counts them, and beside a failing page they are kept
    in the detail and the count, not dropped; the unknown rows are counted as ``strange_rows``: a cap shrinks what is printed, never
    what is counted), or the file is longer than :data:`PAGE_PASS_LIMIT_BYTES` (``skipped = "file-over-4-gib"``, the pass is not run).
    A pass that did not finish never reads as clean. The measurements are in the module docstring."""
    t0 = time.monotonic()

    def entry(verdict: str, detail: list[str], **more: Any) -> dict[str, Any]:
        return {
            "table": PAGES_ENTRY,
            "verdict": verdict,
            "seconds": round(time.monotonic() - t0, 2),
            "detail": [d[:DETAIL_CHARS] for d in detail],
            **more,
        }

    if cancel is not None and cancel.is_set():
        return entry(VERDICT_UNCHECKED, [_SQLITE_REASONS[9]])
    if not cipher_check_present():
        return entry(
            VERDICT_UNCHECKED,
            ["this build of SQLCipher has no page-authentication check (PRAGMA cipher_integrity_check), so the pages were not checked"],
        )
    def skipped(size: int) -> dict[str, Any]:
        return entry(VERDICT_UNCHECKED, [_OVER_LIMIT_REASON], skipped="file-over-4-gib", file_bytes=size)

    size = _size_of(path)
    if size > PAGE_PASS_LIMIT_BYTES:
        return skipped(size)
    con = None
    try:
        con = (opener or _open)(path)
        failing = 0  # one row per failing page; the numbers kept are the lowest MAX_PAGES_LISTED (a max-heap, negated)
        lowest: list[int] = []
        other = _Kept(DETAIL_LINES)  # rows this app does not know: damage in their own words
        unread = _Kept(DETAIL_LINES)  # rows that say the pass could not read or run (``_COULD_NOT_READ``)
        answered = False
        for row in con.execute("PRAGMA cipher_integrity_check"):
            answered = True
            line = str(row[0])
            if (m := _HMAC_ROW.search(line)) is not None:
                failing += 1
                number = int(m.group(1))
                if len(lowest) < MAX_PAGES_LISTED:
                    heapq.heappush(lowest, -number)
                elif number < -lowest[0]:
                    heapq.heapreplace(lowest, -number)
            elif _COULD_NOT_READ.search(line) is not None:
                unread.add(line.replace("\n", " "))
            else:
                other.add(line.replace("\n", " "))
    except Exception as exc:  # noqa: BLE001 - the verdict IS the exception's class
        verdict, reason = classify_error(exc)
        return entry(verdict, [reason])
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()
    size = _size_of(path)
    if size > PAGE_PASS_LIMIT_BYTES:
        # The file crossed 2^32 bytes WHILE the pass ran (an outside writer, a backup landing): what the pass answered is about wrong bytes
        # past that point, so its rows are dropped, exactly as if the file had been that long when it began.
        return skipped(size)
    if not answered:
        return entry(VERDICT_OK, ["no page of the file failed its authentication check"])
    unreadable, strange = unread.count, other.count
    unread_line = (
        f"{unreadable} page(s) could not be read by the page check and are not counted above: {unread.lines[0]}" if unreadable else None
    )
    counts: dict[str, int] = {}  # what was COUNTED stays in the record whatever the detail shows
    if unreadable:
        counts["pages_unread"] = unreadable
    if strange:
        counts["strange_rows"] = strange
    if not failing and not strange:
        # Every row was a "could not read" one (the pass answered at least one row): it did not get to the end of the file, which is no
        # verdict on the file (R100). The record keeps the first lines and the count; the table that sent it here stays unchecked, so
        # the file is not called clean either.
        return entry(
            VERDICT_UNCHECKED,
            [f"the page check could not read {unreadable} page(s) and so did not check the file to the end", *unread.lines[: DETAIL_LINES - 1]],
            **counts,
        )
    if not failing:
        # An answer this app does not know how to read is not a clean one (the check's own rule: anything but its clean answer).
        lines = [*other.lines, *([unread_line] if unread_line else [])]
        return entry(VERDICT_DAMAGED, lines[:DETAIL_LINES], pages=[], pages_total=0, **counts)
    pages = sorted(-n for n in lowest)
    shown = ", ".join(str(n) for n in pages[:8]) + (" and more" if failing > 8 else "")
    lines = [f"{failing} page(s) failed their authentication check (HMAC verification): {shown}"]
    if unread_line:
        lines.append(unread_line)
    lines.extend(other.lines)
    return entry(VERDICT_DAMAGED, lines[:DETAIL_LINES], pages=pages, pages_total=failing, **counts)


def confirm_encrypted_damage(path: Path, *, opener: Opener | None = None, cancel: threading.Event | None = None) -> dict[str, Any]:
    """The ``(pages)`` entry of an encrypted file (:func:`_page_pass`: ``PRAGMA cipher_integrity_check`` on a read-only connection that is
    closed on every path). Never raises. A ``damaged`` pass is run AGAIN on a NEW connection and stands only when the second pass agrees
    (``second_read: agreed``, the first pass's page list kept); a second pass that is clean, or could not be made, files ``unchecked`` with the key of
    what happened (:func:`_not_concluded`): nothing latches and nothing is repaired on a damage that was not measured twice. A pass that is
    clean, or could not be made at all, is final and costs one pass."""
    first = _page_pass(path, opener=opener, cancel=cancel)
    if first["verdict"] != VERDICT_DAMAGED:
        return first
    return _second_read(first, _page_pass(path, opener=opener, cancel=cancel))  # a stop already asked for ends that pass before it opens anything


def page_check(
    path: Path,
    answers: list[dict[str, Any]],
    *,
    earlier: list[str] | tuple[str, ...] = (),
    opener: Opener | None = None,
    cancel: threading.Event | None = None,
    before: Callable[[], None] | None = None,
) -> dict[str, Any] | None:
    """The ``(pages)`` entry a check owes, or ``None`` when it owes none. ``before`` is called once, just before the pass begins (the
    progress line names the pass while it runs, which can be a long time on a big file). Owed when a table (or the list of tables) of an
    ENCRYPTED file answered ``unchecked`` with the generic error (``sqlite_code``), or when an earlier check reported
    ``(pages)`` and this read has to answer for it. A file whose header is plaintext has no authentication tags: an earlier
    ``(pages)`` finding is about a file that no longer is, and reads ``ok``; a file that cannot be examined reads ``unchecked``."""
    again = PAGES_ENTRY in earlier
    asked = any(a.get("verdict") == VERDICT_UNCHECKED and a.get("sqlite_code") == _SQLITE_ERROR for a in answers)
    if not (again or asked):
        return None
    from src.database.connect import is_encrypted_file

    encrypted = is_encrypted_file(path)
    if encrypted is True:
        if before is not None:
            before()
        return confirm_encrypted_damage(path, opener=opener, cancel=cancel)
    if not again:
        return None  # a plaintext file never reaches the pass by the generic error: that error is about something else
    if encrypted is False:
        return {
            "table": PAGES_ENTRY,
            "verdict": VERDICT_OK,
            "seconds": 0.0,
            "detail": ["the file is not encrypted now: it has no page authentication to fail"],
        }
    return {
        "table": PAGES_ENTRY,
        "verdict": VERDICT_UNCHECKED,
        "seconds": 0.0,
        "detail": ["the file could not be examined, so the page check was not run"],
    }


# --- the plan, the arming and the run ----------------------------------------------------------------


def _path_of(file_key: str) -> Path | None:
    path, _name = damage._file_paths(file_key)
    return path


def _attempts_of(entry: dict[str, Any]) -> int:
    """The attempts a record carries; a record with anything else there counts as none, rather than aborting the plan."""
    try:
        return max(0, int(entry.get("attempts") or 0))
    except (TypeError, ValueError):
        return 0


def plan_boot(*, previous_end: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """What the start-up check will do, or ``None`` when it has nothing to do.

    A file is checked when the previous session ended unclean (``previous_end["clean"] is False``: an UNKNOWN
    end, ``None``, is not a reason), an earlier process left a check of that file unfinished, or an earlier
    process's check found it DAMAGED (the latch lives in memory and the ledger reads a clean end, so without this a
    restart would forget the finding; the file is read again at every start until it reads clean or is replaced). A file that
    does not exist is not checked (and never created: ``connect`` would create it); a file that cannot even be examined
    (an I/O error from ``stat``) is UNCHECKED, not absent. A file whose check has been left unfinished
    ``MAX_VERIFY_ATTEMPTS`` starts in a row is SKIPPED, and said: the cap stops re-running the check, and a finding
    an earlier check made for that file (or for a file that could not be examined) is NOT given up with it: such a file is
    listed in ``skipped`` with its ``tables`` and :func:`arm_at_boot` latches it from them. THE HOLD LASTS: a file held at
    the cap stays held at every CLEAN start after it (its ``skipped`` entry carries the attempts it used), and only a new
    unexpected stop, a new reason to check, starts the count again at 0. A file that cannot be examined while its check is
    due is written down as OWED, with the reason and the attempts it had (a clean end does not cancel it). The record an
    earlier process left is carried through every entry that replaces it (``damage.carried_damage``)."""
    if not switch_on():
        return None
    prev = previous_end if previous_end is not None else damage._previous_end()
    unclean = prev is not None and prev.get("clean") is False
    files: list[tuple[str, Path, int]] = []
    skipped: list[dict[str, Any]] = []
    any_unfinished = False
    for key in damage.PAUSED_FILES:
        path = _path_of(key)
        if path is None:
            continue
        last = damage.registry.previous_verification(key)
        carried = damage.carried_damage(last)
        try:
            if not path.is_file() or path.stat().st_size == 0:
                continue
        except OSError:
            # Could not tell whether there is a file: UNCHECKED, never "nothing to read". An earlier finding stands.
            reason = "the file could not be examined (an I/O error), so the check of it was not run"
            unfinished_before = last is not None and last.get("state") in ("running", "owed")
            if carried:
                skipped.append({"file": key, "path": path, "attempts": _attempts_of(last or {}), "tables": carried, "reason": reason})
            elif unclean or unfinished_before:
                # Nothing earlier to hold, but a check that was due is still due: written down as owed (see ``_owe``), so
                # the session that could not read the file ending cleanly does not cancel it.
                due_for = TRIGGER_UNCLEAN_END if unclean else str((last or {}).get("trigger") or TRIGGER_UNFINISHED)
                skipped.append(
                    {
                        "file": key,
                        "path": path,
                        "attempts": _attempts_of(last or {}) if unfinished_before else 0,
                        "owe": due_for,
                    }
                )
            continue
        if damage.registry.checked_by_this_process(key):
            continue
        # "running": a check began and the process ended before it finished. "owed": a check was due and the process
        # ended before it began (a boot that stayed locked, or a quit between arming and the first table). The ``owed``
        # entry THIS process wrote at a locked boot is the same process unlocking: due, not unfinished, and its own
        # trigger names why (an "unfinished check" label for a file damaged before was untrue).
        own_owed = last is not None and bool(last.get("own")) and last.get("state") == "owed"
        unfinished = last is not None and (last.get("state") == "running" or (last.get("state") == "owed" and not own_owed))
        if not (unclean or unfinished or own_owed or carried):
            continue
        # A file HELD on an earlier finding keeps the attempts its hold carries at every clean start that follows: the hold
        # writes a ``skipped`` entry that is neither unfinished nor owed, and reading it as "no attempts" would run the check
        # another ``MAX_VERIFY_ATTEMPTS`` times (a crashing check: 3 runs, 1 held start, 3 runs, ...). The cap below does the
        # holding, so a hold written under it (a file that could not be examined, attempts 2) is planned with its 2. A new
        # unexpected stop is a new reason to check, so it alone starts the count again.
        held_before = last is not None and last.get("state") == "skipped" and bool(carried) and not unclean
        attempts = _attempts_of(last) if (last is not None and (unfinished or own_owed or held_before)) else 0
        if attempts >= damage.MAX_VERIFY_ATTEMPTS:
            skipped.append({"file": key, "path": path, "attempts": attempts, **({"tables": carried} if carried else {})})
            continue
        files.append((key, path, attempts))
        any_unfinished = any_unfinished or unfinished or (own_owed and last is not None and last.get("trigger") == TRIGGER_UNFINISHED)
    if not files and not skipped:
        return None
    if unclean:
        trigger = TRIGGER_UNCLEAN_END
    elif any_unfinished:
        trigger = TRIGGER_UNFINISHED
    else:
        trigger = TRIGGER_DAMAGE_FOUND
    return {"trigger": trigger, "files": files, "skipped": skipped}


def _owe(plan: dict[str, Any]) -> None:
    """Write down, per file, that its check is DUE (``state: owed``), before anything has read it: a session that
    ends without reaching the check (a boot that stays locked, a quit in the seconds between arming and the first
    table) must not read, in the next session's ledger, as the clean end that cancels the check."""
    for key, path, attempts in plan["files"]:
        damage.registry.verification_file_owed(key, path=path, trigger=plan["trigger"], attempts=attempts)
    for sk in plan["skipped"]:
        if sk.get("owe"):
            # A file that could not be examined: its check is still due, and nothing here read it.
            damage.registry.verification_file_owed(sk["file"], path=sk["path"], trigger=sk["owe"], attempts=sk["attempts"])


def owe_at_locked_boot() -> None:
    """A boot that starts LOCKED cannot read the files (the key is not here), so it arms nothing; it still records
    that the check is owed, because if the app is closed from the lock screen this session ends cleanly and the
    unexpected stop before it would otherwise be forgotten. Never raises."""
    try:
        plan = plan_boot()
        if plan is not None:
            _owe(plan)
    except Exception:  # noqa: BLE001 - a bookkeeping failure must never take the lock screen down
        _LOG.warning("database check: could not record the check as owed", exc_info=True)


def arm_at_boot() -> bool:
    """Decide, and when a check is due ARM it (collection waits from this call). Returns whether a check is
    armed. Called once the database is open and BEFORE the slow start-up work, so the wait covers it; a second
    call while armed changes nothing. Never raises: a failure to decide is logged and collection is not held for
    a check that will not run."""
    global _PLAN, _HANDED_OVER
    try:
        with _LOCK:
            if _PLAN is not None:
                return True
        plan = plan_boot()
        if plan is None:
            return False
        for sk in plan["skipped"]:
            if sk.get("owe"):
                continue  # written down as owed by ``_owe``, not skipped: its check is still due
            tables = sk.get("tables")
            if tables:
                # The cap stops re-running the check; it does not give up what an earlier check found. The file is
                # latched from the record, says so (``FRAME_CHECK_STOPPED``), and is released only by a re-read of those
                # tables that comes back clean (a start of collection) or by a replacement of the file.
                reason = sk.get("reason") or (
                    f"the check of the {sk['file']} file was left unfinished on the last {sk['attempts']} starts, so it is "
                    "not run again; an earlier check found damage in it, so its writers stay paused until the part that was "
                    "reported reads clean"
                )
                _LOG.warning("database check not run, file held on an earlier finding: %s", reason)
                damage.registry.verification_file_held(
                    sk["file"], path=sk["path"], attempts=sk["attempts"], reason=reason, tables=list(tables)
                )
                continue
            reason = (
                f"the check of the {sk['file']} file was left unfinished on the last {sk['attempts']} starts, so it is "
                "not tried again until the next unexpected stop"
            )
            _LOG.warning("database check skipped: %s", reason)
            damage.registry.verification_file_skipped(sk["file"], path=sk["path"], attempts=sk["attempts"], reason=reason)
        if not plan["files"]:
            _owe(plan)  # the files that could not be examined (there is nothing to run)
            return False
        with _LOCK:
            _PLAN = plan
            _HANDED_OVER = False
        damage.registry.verification_arm(plan["trigger"])
        _owe(plan)
        _LOG.info(
            "database check armed (%s): %s",
            plan["trigger"],
            ", ".join(k for k, _p, _a in plan["files"]),
        )
        return True
    except Exception:  # noqa: BLE001 - never hold collection for a check that cannot be planned
        _LOG.warning("database check: could not plan the start-up check", exc_info=True)
        return False


def hand_over() -> None:
    """The thread whose first step runs the armed check has been started: ending the wait is its job from here
    (:func:`run_armed` ends it however the run ends)."""
    global _HANDED_OVER
    with _LOCK:
        _HANDED_OVER = True


def withdraw_unless_handed_over() -> None:
    """The start-up upkeep ended. If the thread that runs the check was never started (the upkeep raised on the way
    to it, or the scheduler is off), withdraw the wait: collection must never wait for a check nothing is going to
    make. A no-op when nothing is armed."""
    with _LOCK:
        if _HANDED_OVER:
            return
    disarm()


def disarm() -> None:
    """Withdraw an armed check that will not run (the thread that would have run it could not be started):
    collection must never wait for a check nothing is going to make."""
    global _PLAN
    with _LOCK:
        _PLAN = None
    damage.registry.verification_end()


def stop() -> None:
    """Stop the running check (the app is shutting down): the table in hand ends at the next look of the progress
    handler, no further table is started, and the file's entry stays ``running`` so the next start reads it again.

    A page pass in flight is ONE call into the C library that no progress handler reaches, and the thread that waits in it is a
    daemon, so a quit does not wait for it to end: the attempt the pass cost is given back HERE, at the stop, because nothing after
    the call would ever run (three quits that landed in the pass would otherwise spend the file's three attempts and skip the check
    until the next unexpected stop, with no finding recorded). A kill, which cannot say anything, still counts as the one unfinished
    attempt it is."""
    _CANCEL.set()
    with _LOCK:
        key = _PASS_FILE
    if key is not None:
        _give_back_attempt(key)


def _give_back_attempt(key: str) -> None:
    """The stop of the check of ``key`` hands its attempt back, once per run (``verification_file_stopped``). Never raises."""
    with _LOCK:
        if key in _GAVE_BACK:
            return
        _GAVE_BACK.add(key)
    damage.registry.verification_file_stopped(key)


@contextlib.contextmanager
def _pass_in_flight(key: str) -> Iterator[None]:
    """Names the file whose page pass is running, so that :func:`stop` can give its attempt back while the pass cannot end."""
    global _PASS_FILE
    with _LOCK:
        _PASS_FILE = key
    try:
        yield
    finally:
        with _LOCK:
            _PASS_FILE = None


def run_armed(*, opener: Opener | None = None) -> bool:
    """Run the check :func:`arm_at_boot` armed, in the calling thread. Returns whether one ran. ALWAYS ends the
    arming (``verification_end``), however the run ends: a check that raised must never leave collection
    waiting for ever."""
    global _PLAN
    with _LOCK:
        plan, _PLAN = _PLAN, None
    if plan is None:
        return False
    reg = damage.registry
    try:
        _run_plan(plan, opener=opener)
        return True
    except Exception as exc:  # noqa: BLE001
        # The TYPE only, never the text or a traceback: the check opens keyed connections, and an engine's or a driver's message
        # (and the error a driver's was raised from, which a traceback prints too) can carry a statement that holds the
        # passphrase. A record's ``exc_info`` rides the diagnostics bundle through data/app_errors.jsonl.
        _LOG.warning("database check: the start-up check failed (%s)", type(exc).__name__)
        return True
    finally:
        reg.verification_end()


def _run_plan(plan: dict[str, Any], *, opener: Opener | None) -> None:
    reg = damage.registry
    inspected = [(key, path, attempts, inspect_confirmed(path, opener=opener)) for key, path, attempts in plan["files"]]
    reg.verification_begin(sum(len(i.get("names", ())) for _k, _p, _a, i in inspected))
    with _LOCK:
        _GAVE_BACK.clear()
    done = 0
    for key, path, attempts, info in inspected:
        if _CANCEL.is_set():
            return  # stopped before this file was begun: no attempt is spent on it
        t0 = time.monotonic()
        # What an earlier check reported for this file and nothing has read clean since, taken BEFORE this file's entry is
        # begun (the new entry carries it, and the page pass is owed again when it names ``(pages)``).
        earlier = damage.carried_damage(reg.previous_verification(key)) or []
        if "error" in info:
            verdict, reason = info["error"]
            reg.verification_file_started(key, path=path, trigger=plan["trigger"], tables_total=0, attempts=attempts + 1)
            schema_tables: list[dict[str, Any]] = (
                [
                    {
                        "table": SCHEMA_ENTRY,
                        "verdict": VERDICT_DAMAGED,
                        "seconds": 0.0,
                        "detail": [reason[:DETAIL_CHARS]],
                        "second_read": info.get("second_read", SECOND_READ_AGREED),
                    }
                ]
                if verdict == VERDICT_DAMAGED
                else (
                    # The list read as damage once and the second read could not be made: no verdict, and the record says what was reported.
                    [
                        _not_concluded(
                            {"table": SCHEMA_ENTRY, "seconds": 0.0, "detail": info.get("first_read")},
                            SECOND_READ_UNAVAILABLE,
                            {"detail": info.get("second_detail")},
                        )
                    ]
                    if info.get("second_read") == SECOND_READ_UNAVAILABLE
                    else []
                )
            )
            pages = None
            unread_kept = 0
            if not _CANCEL.is_set():
                with _pass_in_flight(key):
                    pages = page_check(
                        path,
                        [{"verdict": verdict, "sqlite_code": info.get("sqlite_code")}],
                        earlier=earlier,
                        opener=opener,
                        cancel=_CANCEL,
                        before=functools.partial(reg.verification_progress, key, PAGES_ENTRY, done),
                    )
            if _CANCEL.is_set():
                # Stopped in or before the pass: what it answered is not a verdict on the file (the same rule as the tables'), and the
                # entry stays ``running`` with its attempt given back.
                _LOG.info("database check: stopped before the %s file was finished", key)
                _give_back_attempt(key)
                return
            if pages is not None and pages["verdict"] == VERDICT_DAMAGED:
                if verdict != VERDICT_DAMAGED:
                    # The list could not be read AND pages fail their authentication: damage, and "(schema)" in the record
                    # is what makes a re-read read every table again (a clean page pass alone must not release it).
                    verdict = VERDICT_DAMAGED
                    schema_tables = [
                        {
                            "table": SCHEMA_ENTRY,
                            "verdict": VERDICT_DAMAGED,
                            "seconds": 0.0,
                            "detail": [f"the table list could not be read ({reason}); see {PAGES_ENTRY}"[:DETAIL_CHARS]],
                            "second_read": info.get("second_read", SECOND_READ_AGREED),
                        }
                    ]
                schema_tables = [*schema_tables, pages]
            elif pages is not None and verdict != VERDICT_DAMAGED:
                reason = f"{reason}; {PAGES_ENTRY}: {pages['detail'][0]}"
                unread_kept = int(pages.get("pages_unread") or 0)  # a NUMBER in the record, not only words inside the reason
            result = {
                "verdict": verdict,
                "tables": schema_tables,
                "tables_total": 0,
                "listed": False,  # the table list could not be read: no table was, and no earlier finding is cleared
                "reason": None if verdict == VERDICT_DAMAGED else reason,
                "seconds": round(time.monotonic() - t0, 2),
                **({"pages_unread": unread_kept} if unread_kept else {}),
            }
            reg.verification_file_done(key, result, path=path)
            continue
        names = info["names"]
        reg.verification_file_started(key, path=path, trigger=plan["trigger"], tables_total=len(names), attempts=attempts + 1)
        # A list that read as damage once and as a list the second time is no verdict either way: every table is read below, and the (schema)
        # entry says so (``unchecked``, so the file is not called clean either).
        tables: list[dict[str, Any]] = (
            [_not_concluded({"table": SCHEMA_ENTRY, "seconds": 0.0, "detail": info.get("first_read")}, SECOND_READ_CLEAN)]
            if info.get("second_read") == SECOND_READ_CLEAN
            else []
        )
        for name in names:
            if _CANCEL.is_set():
                break
            done += 1
            reg.verification_progress(key, name, done)
            tables.append(check_table(path, name, opener=opener, cancel=_CANCEL))
        if not _CANCEL.is_set():
            with _pass_in_flight(key):
                pages = page_check(
                    path,
                    tables,
                    earlier=earlier,
                    opener=opener,
                    cancel=_CANCEL,
                    before=functools.partial(reg.verification_progress, key, PAGES_ENTRY, done),
                )
            if pages is not None:
                tables.append(pages)
        if _CANCEL.is_set():
            # Stopped (the app is shutting down): what was read is not a verdict on the file, and the record keeps
            # ``state: running`` so the next start reads it again (the attempt is given back: a quit is not a failure of the check).
            _LOG.info("database check: stopped before the %s file was finished", key)
            _give_back_attempt(key)
            return
        result = {
            "verdict": file_verdict(tables),
            "tables": tables,
            "tables_total": len(names),
            "facts": info["facts"],
            "seconds": round(time.monotonic() - t0, 2),
        }
        reg.verification_file_done(key, result, path=path)
        _LOG.info(
            "database check: the %s file: %s (%d table(s), %.1f s)", key, result["verdict"], len(names), result["seconds"]
        )


# --- the re-read a start of collection asks for ------------------------------------------------------------


def recheck(files: dict[str, list[str]], *, reason: str, claims: dict[str, int] | None = None) -> dict[str, str]:
    """Re-read, for each latched file in ``files`` (``{file key: the tables the check reported damaged}``), those
    tables, on a thread of their own: the operator started collection again, and a latch the check set is released
    only by a read that comes back clean (``DamageRegistry.retry`` calls this; the claim on each file was made there).
    ``claims`` is each file's claim token (``DamageRegistry.retry`` made the claim); the thread settles only that claim.
    Never blocks and never raises. ``{file key: outcome}``:

    * ``started``: a thread is reading it; it ends the claim itself (``recheck_finished`` or ``recheck_abandoned``).
    * ``nothing-to-read``: the check is switched off (``OO_BOOT_VERIFY=0``) or the file is not there; the caller
      releases the latch as a plain retry does.
    * ``kept``: the start-up check is armed or still reading (it decides), the file could not be examined (an I/O error
      is "unchecked", never "nothing to read"), or the thread could not be started; the latch stays.
    """
    out: dict[str, str] = {}
    reg = damage.registry
    try:
        plan: list[tuple[str, Path, list[str]]] = []
        for key, names in files.items():
            path = _path_of(key)
            try:
                readable = switch_on() and path is not None and path.is_file() and path.stat().st_size > 0
            except OSError:
                # Could not tell whether there is a file to read: that is UNCHECKED, never "nothing to read" (which
                # releases the latch). The latch stays and the next start of collection asks again.
                _LOG.warning("database check: could not examine the %s file for the re-read", key, exc_info=True)
                out[key] = "kept"
                continue
            if not readable or path is None:
                out[key] = "nothing-to-read"
            else:
                plan.append((key, path, list(names)))
        if not plan:
            return out
        if reg.verifying():
            out.update({key: "kept" for key, _p, _n in plan})
            return out
        t = threading.Thread(target=_recheck_main, args=(plan, reason, claims or {}), name="oo-database-recheck", daemon=True)
        try:
            t.start()
        except Exception:  # noqa: BLE001 - no thread, no read: the latch stays
            _LOG.warning("database check: could not start the re-read of the reported tables", exc_info=True)
            out.update({key: "kept" for key, _p, _n in plan})
            return out
        out.update({key: "started" for key, _p, _n in plan})
        return out
    except Exception:  # noqa: BLE001
        _LOG.warning("database check: could not plan the re-read of the reported tables", exc_info=True)
        return {key: out.get(key, "kept") for key in files}


def _recheck_main(plan: list[tuple[str, Path, list[str]]], reason: str, claims: dict[str, int] | None = None) -> None:
    """The thread body of :func:`recheck`: each file's reported tables, one on its own read-only connection, then the
    answer to the registry. A stop (the app is shutting down) or a failure ends the claim without an answer, so the
    latch stays."""
    reg = damage.registry
    claims = claims or {}
    for key, path, wanted in plan:
        token = claims.get(key)
        try:
            if _CANCEL.is_set():
                continue
            info = inspect_confirmed(path)
            if "error" in info:
                verdict, why = info["error"]
                # A schema that cannot be read as damage is damage; anything else is no answer about the tables.
                answers = (
                    [{"table": SCHEMA_ENTRY, "verdict": VERDICT_DAMAGED, "seconds": 0.0, "detail": [why[:DETAIL_CHARS]]}]
                    if verdict == VERDICT_DAMAGED
                    else []
                )
                if answers:
                    reg.recheck_finished(key, answers, path=path, token=token)
                _LOG.info("database check: the %s file's reported tables could not be listed (%s)", key, verdict)
                continue
            # A "(schema)" the check could not read means it read NO table at all: when the list reads now, every
            # table of it is read, and the schema is answered clean only beside them (the deep delta read's S3: the
            # list alone released a file whose tables were never read).
            everything = SCHEMA_ENTRY in wanted
            present = [n for n in info["names"] if everything or n in wanted]
            # A table that is no longer in the file has nothing in it to be damaged. ``(pages)`` is no table of the list:
            # it is answered by the page pass below, never by its absence from the list.
            gone = [
                {
                    "table": n,
                    "verdict": VERDICT_OK,
                    "seconds": 0.0,
                    "detail": ["the table list read clean" if n == SCHEMA_ENTRY else "the table is no longer in the file"],
                }
                for n in wanted
                if n not in info["names"] and n != PAGES_ENTRY
            ]
            reg.recheck_total(key, len(present), token)
            answers = []
            stopped = False
            for i, name in enumerate(present, 1):
                if _CANCEL.is_set():
                    stopped = True
                    break
                reg.recheck_progress(key, i, token)
                answers.append(check_table(path, name, cancel=_CANCEL))
            if not (stopped or _CANCEL.is_set()):
                pages = page_check(path, answers, earlier=[PAGES_ENTRY] if PAGES_ENTRY in wanted else [], cancel=_CANCEL)
                if pages is not None:
                    answers.append(pages)
            if stopped or _CANCEL.is_set():
                _LOG.info("database check: the re-read of the %s file was stopped", key)
                continue
            released = reg.recheck_finished(key, answers + gone, path=path, token=token)
            _LOG.info(
                "database check: the %s file's reported tables re-read (%s): %s",
                key,
                reason,
                "clean, released" if released else "latch stays",
            )
        except Exception as exc:  # noqa: BLE001 - a re-read that failed gives no answer, and the latch stays
            # The TYPE only: the re-read opens keyed connections (see ``run_armed``).
            _LOG.warning("database check: the re-read of the %s file failed (%s)", key, type(exc).__name__)
        finally:
            reg.recheck_abandoned(key, token)  # a no-op after an answer: ends THIS claim whatever happened


def _reset_for_tests() -> None:
    global _PLAN, _HANDED_OVER, _CHECK_PRESENT, _PASS_FILE
    _CHECK_PRESENT = None
    with _LOCK:
        _PLAN = None
        _HANDED_OVER = False
        _PASS_FILE = None
        _GAVE_BACK.clear()
    _CANCEL.clear()
