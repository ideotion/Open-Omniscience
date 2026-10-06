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
* ``unchecked`` (NEVER damaged) when the file is busy or locked, a passphrase is missing or wrong, a disk
  I/O error stopped the read, or the check was stopped. Not reading is not a verdict.

The results go into the damage record (``verification``, per file, a few hundred bytes a table), and a
damaged table latches its file by the SAME door a corruption error does (``DamageRegistry._apply_incident``):
the scope is ``search-index`` only when every damaged table belongs to the full-text index, else ``data``.

WHEN, AND WHY THEN. ``arm_at_boot`` is called where the boot sequence thread is created, and arms the
registry (``verifying()``): from then until the check ends collection waits (the storage guard's
``"verifying"`` kind), so an operator who goes online in the seconds before the sequence reaches the check
does not slip a pass in first. The check is the sequence's FIRST step, ahead of the cache warm-up, the rollup
and the re-index, so nothing heavy competes with it. The app is offline at boot (R117) and starts no
collection by itself, so the read pins nothing a writer needs; the startup upkeep's own small writes
(statistics, the catalogue seed) happen before it and are not stopped.

WHAT IT DOES NOT DO. It does not repair or salvage (E3), and it does not release a latch: a clean verdict
says what this read found, not that an earlier error was wrong. It checks the STRUCTURE of each table and
its indexes (``quick_check``), not every row's content. The search index is a virtual table, and from SQLite
3.44 ``quick_check(<virtual table>)`` runs that module's own integrity check (FTS5's, which reads the content
table too: measured 0.65 s against 0.20 s for the content table alone on a 100 MB store), so the index is
checked with its shadow tables; on an older SQLite that call reads nothing and the shadow tables are all there
is. It is not run beside collection on a big store on purpose: ``quick_check`` holds a read snapshot for the
whole of a table, which is what pins the log.

A CHECK THAT DOES NOT FINISH is tried again at the next start, at most ``damage.MAX_VERIFY_ATTEMPTS`` starts
in a row: a check that itself brings the process down must not become a boot loop that never reaches
collection. The record says which files were skipped and why. ``OO_BOOT_VERIFY=0`` turns the check off.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.database import damage
from src.database.damage import VERDICT_DAMAGED, VERDICT_OK, VERDICT_UNCHECKED

_LOG = logging.getLogger(__name__)

TRIGGER_UNCLEAN_END = "unclean-end"
TRIGGER_UNFINISHED = "unfinished-check"

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

Opener = Callable[[Path], Any]


def switch_on() -> bool:
    """``OO_BOOT_VERIFY=0`` turns the check after an unexpected stop off."""
    return os.getenv("OO_BOOT_VERIFY", "1") != "0"


# --- reading one file ----------------------------------------------------------------------------


def _open(path: Path):
    """A read-only connection through the ONE factory every engine uses (SQLCipher, the search index's
    functions). ``query_only``: nothing on it can ever write."""
    from src.database.connect import connect

    if not Path(path).is_file():
        # ``connect`` CREATES a missing file (plaintext under OO_DB_PLAINTEXT=1, encrypted when a key is held):
        # a check must never be the thing that makes a data file exist.
        raise FileNotFoundError(f"{Path(path).name} does not exist")
    con = connect(str(path), check_same_thread=False, timeout=30)
    try:
        con.execute("PRAGMA query_only=ON")
    except Exception:
        con.close()
        raise
    return con


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


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
        return {"error": classify_error(exc)}
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
        return {"error": classify_error(exc)}
    finally:
        with contextlib.suppress(Exception):
            con.close()


def check_table(path: Path, table: str, *, opener: Opener | None = None, cancel: threading.Event | None = None) -> dict[str, Any]:
    """One table (and its indexes) through ``PRAGMA quick_check``, on its own connection. Never raises."""
    t0 = time.monotonic()
    detail: list[str] | None = None
    con = None
    try:
        con = (opener or _open)(path)
        if cancel is not None:
            with contextlib.suppress(Exception):
                con.set_progress_handler(lambda: 1 if cancel.is_set() else 0, _PROGRESS_STEPS)
        lines = [str(r[0]) for r in con.execute(f"PRAGMA quick_check({_ident(table)})").fetchall()]
        if lines == ["ok"]:
            verdict = VERDICT_OK
        else:
            verdict = VERDICT_DAMAGED
            detail = [ln.replace("\n", " ")[:DETAIL_CHARS] for ln in lines[:DETAIL_LINES]]
    except Exception as exc:  # noqa: BLE001 - the verdict IS the exception's class
        verdict, reason = classify_error(exc)
        if cancel is not None and cancel.is_set() and verdict == VERDICT_UNCHECKED:
            reason = _SQLITE_REASONS[9]
        detail = [reason[:DETAIL_CHARS]]
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()
    out: dict[str, Any] = {"table": table, "verdict": verdict, "seconds": round(time.monotonic() - t0, 2)}
    if detail:
        out["detail"] = detail
    return out


def file_verdict(tables: list[dict[str, Any]]) -> str:
    """``damaged`` if any table is, else ``ok`` if every table is, else ``unchecked``."""
    verdicts = {t.get("verdict") for t in tables}
    if VERDICT_DAMAGED in verdicts:
        return VERDICT_DAMAGED
    if tables and verdicts == {VERDICT_OK}:
        return VERDICT_OK
    return VERDICT_UNCHECKED


# --- the plan, the arming and the run ----------------------------------------------------------------


def _path_of(file_key: str) -> Path | None:
    path, _name = damage._file_paths(file_key)
    return path


def plan_boot(*, previous_end: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """What the start-up check will do, or ``None`` when it has nothing to do.

    A file is checked when the previous session ended unclean (``previous_end["clean"] is False``: an UNKNOWN
    end, ``None``, is not a reason) or an earlier process left a check of that file unfinished. A file that
    does not exist is not checked (and never created: ``connect`` would create it). A file whose check has
    been left unfinished ``MAX_VERIFY_ATTEMPTS`` starts in a row is SKIPPED, and said."""
    if not switch_on():
        return None
    prev = previous_end if previous_end is not None else damage._previous_end()
    unclean = prev is not None and prev.get("clean") is False
    files: list[tuple[str, Path, int]] = []
    skipped: list[dict[str, Any]] = []
    for key in damage.PAUSED_FILES:
        path = _path_of(key)
        try:
            if path is None or not path.is_file() or path.stat().st_size == 0:
                continue
        except OSError:
            continue
        if damage.registry.checked_by_this_process(key):
            continue
        last = damage.registry.previous_verification(key)
        unfinished = last is not None and last.get("state") == "running"
        if not (unclean or unfinished):
            continue
        attempts = int(last.get("attempts") or 0) if (last is not None and unfinished) else 0
        if attempts >= damage.MAX_VERIFY_ATTEMPTS:
            skipped.append({"file": key, "path": path, "attempts": attempts})
            continue
        files.append((key, path, attempts))
    if not files and not skipped:
        return None
    return {"trigger": TRIGGER_UNCLEAN_END if unclean else TRIGGER_UNFINISHED, "files": files, "skipped": skipped}


def arm_at_boot() -> bool:
    """Decide, and when a check is due ARM it (collection waits from this call). Returns whether a check is
    armed. Never raises: a failure to decide is logged and collection is not held for a check that will not
    run."""
    global _PLAN
    try:
        plan = plan_boot()
        if plan is None:
            return False
        for sk in plan["skipped"]:
            reason = (
                f"the check of the {sk['file']} file was left unfinished on the last {sk['attempts']} starts, so it is "
                "not tried again until the next unexpected stop"
            )
            _LOG.warning("database check skipped: %s", reason)
            damage.registry.verification_file_skipped(sk["file"], path=sk["path"], attempts=sk["attempts"], reason=reason)
        if not plan["files"]:
            return False
        with _LOCK:
            _PLAN = plan
        damage.registry.verification_arm(plan["trigger"])
        _LOG.info(
            "database check armed (%s): %s",
            plan["trigger"],
            ", ".join(k for k, _p, _a in plan["files"]),
        )
        return True
    except Exception:  # noqa: BLE001 - never hold collection for a check that cannot be planned
        _LOG.warning("database check: could not plan the start-up check", exc_info=True)
        return False


def disarm() -> None:
    """Withdraw an armed check that will not run (the thread that would have run it could not be started):
    collection must never wait for a check nothing is going to make."""
    global _PLAN
    with _LOCK:
        _PLAN = None
    damage.registry.verification_end()


def stop() -> None:
    """Stop the running check (the app is shutting down): the table in hand ends at the next look of the progress
    handler, no further table is started, and the file's entry stays ``running`` so the next start reads it again."""
    _CANCEL.set()


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
    except Exception:  # noqa: BLE001
        _LOG.warning("database check: the start-up check failed", exc_info=True)
        return True
    finally:
        reg.verification_end()


def _run_plan(plan: dict[str, Any], *, opener: Opener | None) -> None:
    reg = damage.registry
    inspected = [(key, path, attempts, inspect_file(path, opener=opener)) for key, path, attempts in plan["files"]]
    reg.verification_begin(sum(len(i.get("names", ())) for _k, _p, _a, i in inspected))
    done = 0
    for key, path, attempts, info in inspected:
        t0 = time.monotonic()
        if "error" in info:
            verdict, reason = info["error"]
            reg.verification_file_started(key, path=path, trigger=plan["trigger"], tables_total=0, attempts=attempts + 1)
            schema_tables: list[dict[str, Any]] = (
                [{"table": "(schema)", "verdict": VERDICT_DAMAGED, "seconds": 0.0, "detail": [reason[:DETAIL_CHARS]]}]
                if verdict == VERDICT_DAMAGED
                else []
            )
            result = {
                "verdict": verdict,
                "tables": schema_tables,
                "tables_total": 0,
                "reason": None if verdict == VERDICT_DAMAGED else reason,
                "seconds": round(time.monotonic() - t0, 2),
            }
            reg.verification_file_done(key, result, path=path)
            continue
        names = info["names"]
        reg.verification_file_started(key, path=path, trigger=plan["trigger"], tables_total=len(names), attempts=attempts + 1)
        tables: list[dict[str, Any]] = []
        for name in names:
            if _CANCEL.is_set():
                break
            done += 1
            reg.verification_progress(key, name, done)
            tables.append(check_table(path, name, opener=opener, cancel=_CANCEL))
        if _CANCEL.is_set():
            # Stopped (the app is shutting down): what was read is not a verdict on the file, and the record keeps
            # ``state: running`` so the next start reads it again (the attempt count bounds that).
            _LOG.info("database check: stopped before the %s file was finished", key)
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


def _reset_for_tests() -> None:
    global _PLAN
    with _LOCK:
        _PLAN = None
    _CANCEL.clear()
