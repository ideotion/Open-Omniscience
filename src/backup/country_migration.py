"""Move a store's country codes from alpha-2 to alpha-3: the app-stopped, resumable migration.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULINGS THIS BUILDS (Q301 = c, gate row B, brief S05-02; R136): ONE app-stopped run, with an estimate
shown FIRST; a VERIFIED backup taken automatically before it starts; a run that is RESUMABLE and IDEMPOTENT (a
kill at any instant leaves each batch applied or not, never half of one, and the next run finishes it); and, under
R100, a value :func:`to_iso3` cannot map STAYS AS STORED, counted and listed by table and column, never dropped and
never guessed.

WHY APP-STOPPED IS A LOCK AND NOT A REQUEST. The run takes the database file EXCLUSIVELY (``PRAGMA
locking_mode=EXCLUSIVE``) before it reads anything. A second connection from any process, the app's included, is
refused for as long as the run lives; and if the app is already holding the file, the run is the one refused, before
it has touched a row. The dangerous state is a store that holds both forms (an equality filter on ``FRA`` misses
every ``fr`` row, and a restore keyed on the value duplicates what it should have deduplicated), and the only way to
rule it out is to make sure nobody else is writing while the form changes.

THE FORM CHANGES IN ONE PLACE. The marker ``store.country_form`` (``src/database/country_form.py``) flips in the SAME
transaction as the last verification: the claim about the data changes together with the proof of it, or not at all.
Until then the store is alpha-2, and an interrupted run leaves it holding BOTH forms (the windows already committed are
alpha-3): the journal says so (``running`` / ``interrupted``), the app refuses to boot on it and ``store_form()`` refuses
every read of the form, until the run is finished (``src/database/country_form.py``, ``refuse_if_unfinished``).

HOW A RUN IS SHAPED
  1. take the file exclusively, then read the plan: per column, every distinct stored spelling and how many rows hold it,
     split into CONVERT (its alpha-3 differs from what is stored), ALREADY (it is the alpha-3) and UNMAPPED (no ISO
     meaning: ``uk``, ``eu``, ``int``, an aggregate, junk);
  2. refuse BEFORE touching a row when the conversion would collide two rows in a UNIQUE index (``law_documents`` holds
     one on ``(jurisdiction, url)``): the operator's data never gives way to make a code table happy;
  3. measure the disk on a window that is rolled back, show the plan and the estimate, ask;
  4. take the verified backup (a consistent copy through the connection that holds the file, keyed like the store,
     reopened and checked: ``quick_check`` and an equal row count for every table);
  5. sweep each column in windows of rowids, one transaction per window, converting every convertible spelling in the
     window and recording the cursor in the same transaction;
  6. verify, inside one last transaction, that nothing convertible is left, that every table has the rows it had and
     that each column's before/after counts balance spelling by spelling; convert the country codes written INSIDE
     the recorded differences (``metadata_alternates`` identity/field JSON: no column holds them); flip the marker in
     that transaction.

A killed run is resumed by running it again: the cursor is in the file, a window that was not committed was rolled
back by SQLite, and a row already converted no longer matches a spelling to convert.

WHAT THE NUMBERS PROTECT. ``BATCH_ROWIDS`` bounds how long one transaction holds the file and how far the log grows;
it caps nothing that is counted.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.database import country_form as cf

_LOG = logging.getLogger(__name__)

#: rowids per transaction. It protects the time one commit holds the file and the size the log reaches before it is
#: checkpointed; a window with fewer rows than this simply commits fewer.
BATCH_ROWIDS = 20_000
#: Spellings converted per statement: three bound values per spelling, and the oldest SQLite builds allow 999.
_SPELLINGS_PER_STATEMENT = 200

JOURNAL_KEY = cf.JOURNAL_KEY


class MigrationRefused(RuntimeError):
    """The run did not start, or stopped, for a reason the operator can act on. Nothing was left half-done."""


class AppStillRunning(MigrationRefused):
    """Another connection holds the file."""


# --------------------------------------------------------------------------- #
#  What the migration covers
# --------------------------------------------------------------------------- #
def migration_columns() -> list[tuple[str, str]]:
    """Every ``(table, column)`` whose type is :class:`~src.database.country_form.CountryCode`.

    Read from the model metadata, so the columns the app converts at its boundary and the columns this rewrites cannot
    disagree: a column added with the type is migrated, and one that is not typed is not (the restore registry,
    ``src/backup/country_codes.py``, is held equal to this by ``tests/test_country_migration.py``)."""
    from src.database.models import Base

    out: list[tuple[str, str]] = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, cf.CountryCode):
                out.append((table.name, col.name))
    return out


# --------------------------------------------------------------------------- #
#  Reading the plan
# --------------------------------------------------------------------------- #
@dataclass
class ColumnPlan:
    table: str
    column: str
    nulls: int = 0
    #: every non-NULL stored spelling -> rows holding it
    spellings: dict[str, int] = field(default_factory=dict)
    #: spelling -> the alpha-3 it becomes, for the ones that change
    convert: dict[str, str] = field(default_factory=dict)
    unmapped: dict[str, int] = field(default_factory=dict)

    @property
    def rows(self) -> int:
        return self.nulls + sum(self.spellings.values())

    @property
    def to_rewrite(self) -> int:
        return sum(n for v, n in self.spellings.items() if v in self.convert)

    @property
    def key(self) -> str:
        return f"{self.table}.{self.column}"


@dataclass
class Plan:
    columns: list[ColumnPlan]
    table_rows: dict[str, int]
    missing: list[str]  # "table.column" the file does not have (an older schema)

    @property
    def to_rewrite(self) -> int:
        return sum(c.to_rewrite for c in self.columns)

    def unmapped_report(self) -> dict[str, dict[str, int]]:
        return {c.key: dict(sorted(c.unmapped.items())) for c in self.columns if c.unmapped}


def _q(name: str) -> str:
    """A table or column name from the model metadata, quoted. Never input."""
    if not name.replace("_", "").isalnum():
        raise ValueError("not an identifier")
    return f'"{name}"'


def _table_columns(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({_q(table)})").fetchall()}


def read_plan(con) -> Plan:
    """Read-only: what the store holds in every country column and what a run would do about it."""
    from src.catalog.countries import to_iso3

    cols: list[ColumnPlan] = []
    missing: list[str] = []
    tables: dict[str, int] = {}
    for table, column in migration_columns():
        have = _table_columns(con, table)
        if not have:
            continue  # the table does not exist in this file (an older schema): nothing to convert there
        if column not in have:
            missing.append(f"{table}.{column}")
            continue
        if table not in tables:
            tables[table] = con.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0]  # noqa: S608  # nosec B608 - `_q` quotes a name from the module's own column registry, never input
        plan = ColumnPlan(table, column)
        for value, n in con.execute(f"SELECT {_q(column)}, COUNT(*) FROM {_q(table)} GROUP BY {_q(column)}").fetchall():  # noqa: S608  # nosec B608 - as above
            if value is None:
                plan.nulls = n
                continue
            plan.spellings[value] = n
            target = to_iso3(value)
            if target is None:
                plan.unmapped[value] = n
            elif target != value:
                plan.convert[value] = target
        cols.append(plan)
    return Plan(cols, tables, missing)


def _unique_indexes_with(con, table: str, column: str) -> list[list[str]]:
    out: list[list[str]] = []
    for row in con.execute(f"PRAGMA index_list({_q(table)})").fetchall():
        name, unique = row[1], row[2]
        if not unique:
            continue
        cols = [r[2] for r in con.execute(f"PRAGMA index_info({_q(name)})").fetchall()]
        if column in cols:
            out.append(cols)
    return out


def _case_sql(column: str, n: int) -> str:
    whens = " ".join("WHEN ? THEN ?" for _ in range(n))
    return f"CASE {_q(column)} {whens} ELSE {_q(column)} END"


def find_collisions(con, plan: Plan) -> list[dict]:
    """Rows the conversion would make equal in a UNIQUE index, found BEFORE any row is changed.

    One query per column that sits in a unique index: the table as it WOULD read after the conversion, grouped by the
    index's other columns, and any group of more than one row is a collision. Counted in full, however many are listed."""
    found: list[dict] = []
    for cp in plan.columns:
        if not cp.convert:
            continue
        for index_cols in _unique_indexes_with(con, cp.table, cp.column):
            others = [c for c in index_cols if c != cp.column]
            items = sorted(cp.convert.items())
            mapped_parts = []
            params: list[str] = []
            # the mapping is applied in chunks nested as COALESCE so any number of spellings fits one statement's limit
            for i in range(0, len(items), _SPELLINGS_PER_STATEMENT):
                chunk = items[i : i + _SPELLINGS_PER_STATEMENT]
                mapped_parts.append(_case_sql(cp.column, len(chunk)).replace(f"ELSE {_q(cp.column)}", "ELSE NULL"))
                for v, t in chunk:
                    params += [v, t]
            mapped = f"COALESCE({', '.join(mapped_parts)}, {_q(cp.column)})"
            sel_others = "".join(f", {_q(c)}" for c in others)
            sql = (
                f"SELECT {mapped} AS mapped{sel_others}, COUNT(*) FROM {_q(cp.table)} "  # noqa: S608  # nosec B608 - identifiers come from the model metadata; every value is bound
                f"GROUP BY mapped{sel_others} HAVING COUNT(*) > 1"
            )
            for row in con.execute(sql, params).fetchall():
                found.append(
                    {"table": cp.table, "column": cp.column, "becomes": row[0], "others": list(row[1:-1]), "rows": row[-1]}
                )
    return found


# --------------------------------------------------------------------------- #
#  The journal, the lock, the backup
# --------------------------------------------------------------------------- #
def _upsert_json(con, key: str, obj: dict) -> None:
    now = datetime.now(UTC).isoformat()
    con.execute('CREATE TABLE IF NOT EXISTS "app_state" (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)')
    con.execute(
        'INSERT INTO "app_state" (key, value, updated_at) VALUES (?, ?, ?) '
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, json.dumps(obj, sort_keys=True), now),
    )


def read_journal(con) -> dict | None:
    # Asked of the schema, not read off an engine's message: only a store with no ``app_state`` table has no journal, and a
    # read that fails for any other reason raises (unreadable is not absent).
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_state'").fetchone():
        return None
    row = con.execute('SELECT value FROM "app_state" WHERE key = ?', (JOURNAL_KEY,)).fetchone()
    return json.loads(row[0]) if row else None


def take_exclusive(con) -> None:
    """Hold the file against every other connection for the life of ``con``, or raise :class:`AppStillRunning`."""
    try:
        con.execute("PRAGMA locking_mode=EXCLUSIVE")
        con.execute("BEGIN IMMEDIATE")
        con.execute("COMMIT")
    except Exception as exc:  # noqa: BLE001 - driver text is never kept; the class and the way out are
        from src.database.write import is_locked_error

        if is_locked_error(exc):
            raise AppStillRunning(
                "another program has this database open (the app, a second copy of this command, a backup). "
                "Close it and run this again: the migration needs the file to itself."
            ) from None
        raise


def _tables_with_rows(con) -> dict[str, int]:
    """Every ordinary table and its row count (the virtual search tables count too: a copy that lost an index row is a
    copy that cannot be searched)."""
    names = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    out: dict[str, int] = {}
    for name in names:
        try:
            out[name] = con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0]  # noqa: S608  # nosec B608 - a name read from sqlite_master and checked by _q
        except Exception as exc:  # noqa: BLE001 - a shadow table of a module this build lacks is not a copy failure
            _LOG.debug("could not count %s (%s)", name, type(exc).__name__)
    return out


@dataclass
class BackupInfo:
    path: str
    bytes: int
    tables: dict[str, int]
    verified_at: str
    quick_check: str


def _free_bytes(directory: Path) -> int:
    probe = directory
    while not probe.exists() and probe != probe.parent:  # the nearest folder that exists: asking must not create one
        probe = probe.parent
    return shutil.disk_usage(probe).free


def store_bytes(db_path: Path) -> int:
    total = 0
    for suffix in ("", "-wal"):
        with contextlib.suppress(OSError):
            total += Path(str(db_path) + suffix).stat().st_size
    return total


_ALREADY_THERE = (
    "there is already a file at {dest}: it may be the safety copy of another migration, and this one would replace it. "
    "Nothing was changed. Pass --backup-dir with a folder that does not hold one."
)


_BACKUP_DIR_HINT = "Pass --backup-dir with a folder this command can read and write."


def _path_exists(path: Path, *, follow: bool = False, hint: str = _BACKUP_DIR_HINT) -> bool:
    """Whether ``path`` is there. Only "no such file" means absent: a path that cannot be examined (no permission, a loop)
    is refused with the class, never read as free to write over.

    ``follow`` is the question being asked. Writing a NEW copy asks "is this name taken", and a dangling symlink IS taken
    (writing through it would land somewhere nobody looked), so that check does not follow (``lstat``). Resuming asks "is the
    copy the journal names still THERE to be put back", and a dangling link is not a copy, so that check follows (``stat``)
    and reads it as absent. ``hint`` is what the refusal tells the operator to do, because the two callers need different
    advice (a resume has no ``--backup-dir`` to change)."""
    try:
        (os.stat if follow else os.lstat)(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise MigrationRefused(
            f"the place for the safety copy could not be examined ({type(exc).__name__}): {path}. Nothing was changed. {hint}"
        ) from None
    return True


def backup_name(db_path: Path, stamp: str) -> str:
    """A safety copy's file name: the store's own name, the run's time and a short digest of the store's full path, so two
    stores migrated into one folder never share a name."""
    import hashlib

    digest = hashlib.sha256(str(Path(db_path).resolve()).encode("utf-8", "surrogateescape")).hexdigest()[:8]
    return f"{Path(db_path).stem}.pre-country-form-{stamp}-{digest}.db"


def take_verified_backup(con, db_path: Path, dest: Path) -> BackupInfo:
    """A consistent copy of the store, THROUGH the connection that holds it, reopened and checked.

    Verified means: it opens with the store's own key, ``PRAGMA quick_check`` answers ``ok``, and every table has exactly
    the rows the live file has. The copy keeps the store's encryption state (an encrypted corpus stays ciphertext)."""
    from src.database.connect import connect, snapshot_open_connection

    dest = Path(dest).resolve()  # the journal keeps this path: a relative one would not be found from another folder
    if _path_exists(dest):
        raise MigrationRefused(_ALREADY_THERE.format(dest=dest))
    need = int(store_bytes(db_path) * 1.1) + (1 << 20)
    free = _free_bytes(dest.parent)
    if free < need:
        raise MigrationRefused(
            f"not enough free space for the safety copy in {dest.parent}: needs about {need} bytes, {free} free. "
            "Free some space, or pass --backup-dir with a folder on a bigger drive."
        )
    live = _tables_with_rows(con)
    # Written under a name that is not the safety copy's, and renamed once it has been checked: a kill during the copy
    # leaves a ``.partial`` file, never a truncated file wearing the name an operator would restore from.
    partial = dest.with_name(dest.name + ".partial")
    snapshot_open_connection(con, partial)
    copy = connect(partial, check_same_thread=False)
    try:
        qc = copy.execute("PRAGMA quick_check").fetchone()
        verdict = qc[0] if qc else "no answer"
        got = _tables_with_rows(copy)
    finally:
        copy.close()
    for suffix in ("-wal", "-shm"):
        partial.with_name(partial.name + suffix).unlink(missing_ok=True)
    if verdict != "ok":
        partial.unlink(missing_ok=True)
        raise MigrationRefused("the safety copy failed its integrity check, so it was removed and nothing was changed")
    if got != live:
        diff = sorted(t for t in set(live) | set(got) if live.get(t) != got.get(t))
        partial.unlink(missing_ok=True)
        raise MigrationRefused(
            "the safety copy does not hold the same rows as the store (" + ", ".join(diff[:8]) + "), so it was removed and nothing was changed"
        )
    # Publish under the final name without ever replacing a file that is there: a hard link fails if the name exists, which
    # closes the gap between the check above and this line. A file system with no hard links falls back to the check.
    try:
        os.link(partial, dest)
    except FileExistsError:
        partial.unlink(missing_ok=True)
        raise MigrationRefused(_ALREADY_THERE.format(dest=dest)) from None
    except OSError:
        if _path_exists(dest):
            partial.unlink(missing_ok=True)
            raise MigrationRefused(_ALREADY_THERE.format(dest=dest)) from None
        try:
            os.replace(partial, dest)
        except OSError as exc:
            # The copy was checked and cannot be published: say so by class, and take the half-named file away so no
            # ``.partial`` is left to be mistaken for a copy.
            partial.unlink(missing_ok=True)
            raise MigrationRefused(
                f"the safety copy was written and checked but could not be put under its final name "
                f"({type(exc).__name__}): {dest}. It was removed and nothing was changed."
            ) from None
    else:
        partial.unlink(missing_ok=True)
    return BackupInfo(str(dest), dest.stat().st_size, live, datetime.now(UTC).isoformat(), verdict)


def _fts_update_trigger_is_scoped(con) -> bool:
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='article_fts_au'").fetchone()
    if not row or not row[0]:
        return True  # no trigger: nothing re-indexes
    return "AFTER UPDATE OF" in " ".join(row[0].split()).upper()


# --------------------------------------------------------------------------- #
#  The sweep
# --------------------------------------------------------------------------- #
Progress = Callable[[dict], None]


def _sweep_window(con, cp: ColumnPlan, lo: int, hi: int) -> int:
    """Convert every convertible spelling of ``cp`` in rowids ``(lo, hi]``. The caller owns the transaction."""
    changed = 0
    items = sorted(cp.convert.items())
    for i in range(0, len(items), _SPELLINGS_PER_STATEMENT):
        chunk = items[i : i + _SPELLINGS_PER_STATEMENT]
        params: list = []
        for v, t in chunk:
            params += [v, t]
        sql = (
            f"UPDATE {_q(cp.table)} SET {_q(cp.column)} = {_case_sql(cp.column, len(chunk))} "  # noqa: S608  # nosec B608 - identifiers come from the model metadata; every value is bound
            f"WHERE rowid > ? AND rowid <= ? AND {_q(cp.column)} IN ({', '.join('?' for _ in chunk)})"
        )
        params += [lo, hi] + [v for v, _t in chunk]
        changed += con.execute(sql, params).rowcount
    return changed


def _rowid_span(con, table: str) -> tuple[int, int] | None:
    lo, hi = con.execute(f"SELECT MIN(rowid), MAX(rowid) FROM {_q(table)}").fetchone()  # noqa: S608  # nosec B608 - a table name from the model metadata
    return None if lo is None else (lo, hi)


def probe_rate(con, plan: Plan) -> dict:
    """Time ONE window of the biggest column to rewrite, then roll it back. A rough reading of the rate, not a floor and not
    a promise: it leaves out the commit and the checkpoint a real window pays (the real run is slower there) and it times a
    window whose share of convertible rows may differ from the table's (sparse here, the real run is faster per row)."""
    candidates = sorted((c for c in plan.columns if c.to_rewrite), key=lambda c: -c.to_rewrite)
    if not candidates:
        return {"rate_rows_per_s": None, "basis": "nothing to rewrite"}
    cp = candidates[0]
    span = _rowid_span(con, cp.table)
    if span is None:
        return {"rate_rows_per_s": None, "basis": "empty table"}
    con.execute("BEGIN IMMEDIATE")
    try:
        t0 = time.perf_counter()
        n = _sweep_window(con, cp, span[0] - 1, span[0] - 1 + BATCH_ROWIDS)
        dt = time.perf_counter() - t0
    finally:
        con.execute("ROLLBACK")
    if n <= 0 or dt <= 0:
        return {"rate_rows_per_s": None, "basis": f"the first window of {cp.key} had no row to rewrite"}
    return {
        "rate_rows_per_s": n / dt,
        "basis": (
            f"{n} rows of {cp.key} rewritten in {dt:.3f} s on this machine and rolled back. It leaves out the commit and "
            "the log checkpoint of a real window, and the window may hold more or fewer convertible rows than the table as a whole, so "
            "read it as a rough order of magnitude"
        ),
    }


@dataclass
class Report:
    state: str  # done | interrupted | refused | declined | already-done
    started_at: str
    finished_at: str | None = None
    store_bytes: int = 0
    backup: dict | None = None
    plan: dict | None = None
    estimate: dict | None = None
    rewritten: dict[str, int] = field(default_factory=dict)
    balance: dict[str, dict] = field(default_factory=dict)
    unmapped: dict[str, dict[str, int]] = field(default_factory=dict)
    collisions: list[dict] = field(default_factory=list)
    table_rows_before: dict[str, int] = field(default_factory=dict)
    table_rows_after: dict[str, int] = field(default_factory=dict)
    rate_rows_per_s: float | None = None
    seconds: float | None = None
    #: Country codes inside the recorded differences (``metadata_alternates``), which no column rewrite reaches.
    alternates: dict = field(default_factory=dict)
    #: Where the time went, so an estimate scales each part by what it scales with: the sweep by rows, the copy and the
    #: proof by the size of the store.
    backup_seconds: float | None = None
    sweep_seconds: float | None = None
    verify_seconds: float | None = None
    message: str = ""


def _plan_dict(plan: Plan) -> dict:
    return {
        "to_rewrite": plan.to_rewrite,
        "table_rows": plan.table_rows,
        "missing_columns": plan.missing,
        "columns": {
            c.key: {
                "rows": c.rows, "nulls": c.nulls, "spellings": dict(sorted(c.spellings.items())),
                "convert": dict(sorted(c.convert.items())), "unmapped": dict(sorted(c.unmapped.items())),
            }
            for c in plan.columns
        },
    }


def _original_snapshot(plan: Plan) -> dict:
    """What every column held when the migration FIRST started, kept in the journal: a run that was killed and resumed
    must still balance against the store as it was before the first row moved, not against its own half-way state."""
    return {c.key: {"nulls": c.nulls, "spellings": dict(c.spellings)} for c in plan.columns}


def _balance(original: dict, after: ColumnPlan) -> dict:
    """Spelling by spelling: what the column held at the start, what it holds, and whether every row is accounted for.

    A spelling with no alpha-3 stays under its own name; one that has an alpha-3 is expected under that name."""
    from src.catalog.countries import to_iso3

    expect: dict[str, int] = {}
    for v, n in original["spellings"].items():
        target = to_iso3(v) or v
        expect[target] = expect.get(target, 0) + n
    ok = expect == after.spellings and original["nulls"] == after.nulls
    return {"balanced": ok, "expected": dict(sorted(expect.items())), "found": dict(sorted(after.spellings.items())),
            "nulls_before": original["nulls"], "nulls_after": after.nulls}


def migrate(
    db_path: Path,
    *,
    backup_dir: Path | None = None,
    confirm: Callable[[Plan, dict], bool] | None = None,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
    estimate_only: bool = False,
) -> Report:
    """Run (or resume) the migration of the store at ``db_path``. See the module docstring for the shape.

    ``confirm`` is shown the plan and the estimate and answers whether to go on (None = go on); ``progress`` gets one
    event per phase and per committed window; ``should_stop`` is polled between windows. ``estimate_only`` reads the
    plan and the free disk without taking the file or writing a byte."""
    from src.database.connect import connect, is_encrypted_file

    t_start = time.perf_counter()
    report = Report(state="refused", started_at=datetime.now(UTC).isoformat(), store_bytes=store_bytes(db_path))
    say: Progress = progress or (lambda _e: None)

    if is_encrypted_file(db_path) is None:
        raise MigrationRefused(f"there is no database at {db_path}")

    if estimate_only:
        con = connect(db_path, check_same_thread=False, timeout=5, read_only=True)
        try:
            form = cf.read_form(con)
            plan = read_plan(con)
        finally:
            con.close()
        report.state = "already-done" if form == "alpha3" and plan.to_rewrite == 0 else "declined"
        report.plan = _plan_dict(plan)
        report.unmapped = plan.unmapped_report()
        report.estimate = {"rows_to_rewrite": plan.to_rewrite, "store_bytes": report.store_bytes,
                           "free_bytes": _free_bytes(backup_dir or db_path.parent),
                           "time": "not measured: the estimate is taken in the run itself, on a window it rolls back"}
        report.message = "estimate only: nothing was changed"
        say({"phase": "plan", "plan": report.plan, "estimate": report.estimate})
        return report

    con = connect(db_path, check_same_thread=False, timeout=5)
    con.isolation_level = None  # explicit BEGIN/COMMIT: a window is a transaction we name
    try:
        take_exclusive(con)
        say({"phase": "locked"})
        form = cf.read_form(con)
        journal = read_journal(con) or {}
        plan = read_plan(con)
        report.table_rows_before = dict(plan.table_rows)
        report.plan = _plan_dict(plan)
        report.unmapped = plan.unmapped_report()

        if form == "alpha3" and plan.to_rewrite == 0:
            report.state = "already-done"
            report.message = "the store is already in alpha-3 and nothing is left to convert"
            return report
        if form == "alpha3":
            raise MigrationRefused(
                "the store says it is alpha-3 but still holds alpha-2 values. Nothing was changed: restore the safety "
                "copy, or ask for help, before anything else writes."
            )
        if not _fts_update_trigger_is_scoped(con):
            raise MigrationRefused(
                "the search index trigger on articles is the old, unscoped one, so every country update would re-index the "
                "article. Start the app once (it replaces the trigger), close it and run this again."
            )

        collisions = find_collisions(con, plan)
        if collisions:
            report.collisions = collisions
            report.message = (
                f"{len(collisions)} group(s) of rows would become identical in a unique index. Nothing was changed: "
                "resolve them by hand (they are listed by table and column), then run this again."
            )
            return report

        est = probe_rate(con, plan)
        rate = est.get("rate_rows_per_s")
        est.update(
            rows_to_rewrite=plan.to_rewrite,
            store_bytes=report.store_bytes,
            free_bytes=_free_bytes(backup_dir or db_path.parent),
            seconds_about=(plan.to_rewrite / rate) if rate else None,
        )
        report.estimate = est
        say({"phase": "plan", "plan": report.plan, "estimate": est})
        if confirm is not None and not confirm(plan, est):
            report.state = "declined"
            report.message = "declined: nothing was changed"
            return report

        # ---- the safety copy: once per migration, and kept
        bk = journal.get("backup")
        if not (
            bk
            and _path_exists(
                Path(bk["path"]),
                follow=True,
                hint="Put the safety copy back where the journal says it was, or restore from your own backup.",
            )
        ):
            if journal.get("cursors") or journal.get("rewritten"):
                raise MigrationRefused(
                    "an earlier run converted rows and its safety copy is gone, so a new copy would already be "
                    "half-migrated. Put the safety copy back where the journal says it was, or restore from your own backup."
                )
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            root = Path(backup_dir or (db_path.parent / "backups" / f"pre-country-form-{stamp}")).resolve()
            say({"phase": "backup", "dir": str(root)})
            t_backup = time.perf_counter()
            info = take_verified_backup(con, db_path, Path(root) / backup_name(db_path, stamp))
            bk = info.__dict__
            report.backup_seconds = time.perf_counter() - t_backup
            journal = {"state": "running", "backup": bk, "cursors": {}, "rewritten": {}, "started_at": report.started_at,
                       "original": _original_snapshot(plan), "original_table_rows": dict(plan.table_rows)}
            _upsert_json(con, JOURNAL_KEY, journal)
        report.backup = bk
        say({"phase": "backup-verified", "backup": bk})

        # ---- the sweep
        cursors: dict[str, int] = dict(journal.get("cursors", {}))
        rewritten: dict[str, int] = dict(journal.get("rewritten", {}))
        done_before = sum(rewritten.values())
        total = done_before + plan.to_rewrite
        t_sweep = time.perf_counter()
        sweep_rows = 0
        for cp in plan.columns:
            if not cp.convert:
                continue
            span = _rowid_span(con, cp.table)
            if span is None:
                continue
            lo = cursors.get(cp.key, span[0] - 1)
            while lo < span[1]:
                if should_stop is not None and should_stop():
                    journal.update(state="interrupted")
                    con.execute("BEGIN IMMEDIATE")
                    _upsert_json(con, JOURNAL_KEY, journal)
                    con.execute("COMMIT")
                    report.state = "interrupted"
                    report.message = "stopped between windows; run it again to finish"
                    return report
                hi = min(lo + BATCH_ROWIDS, span[1])
                con.execute("BEGIN IMMEDIATE")
                try:
                    n = _sweep_window(con, cp, lo, hi)
                    cursors[cp.key] = hi
                    rewritten[cp.key] = rewritten.get(cp.key, 0) + n
                    journal.update(state="running", cursors=cursors, rewritten=rewritten)
                    _upsert_json(con, JOURNAL_KEY, journal)
                    con.execute("COMMIT")
                except BaseException:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise
                lo = hi
                sweep_rows += n
                dt = time.perf_counter() - t_sweep
                say({"phase": "sweep", "column": cp.key, "cursor": hi, "of": span[1], "rewritten": rewritten[cp.key],
                     "done": done_before + sweep_rows, "total": total,
                     "rate_rows_per_s": (sweep_rows / dt) if dt > 0 else None})
        report.rewritten = dict(rewritten)
        dt = time.perf_counter() - t_sweep
        report.sweep_seconds = dt
        report.rate_rows_per_s = (sweep_rows / dt) if sweep_rows and dt > 0 else None

        # ---- the proof, and the one place the form changes
        say({"phase": "verify"})
        t_verify = time.perf_counter()
        con.execute("BEGIN IMMEDIATE")
        try:
            after = read_plan(con)
            report.table_rows_after = dict(after.table_rows)
            original = journal["original"]
            if after.table_rows != journal.get("original_table_rows", plan.table_rows):
                raise MigrationRefused("a table's row count changed during the run. The marker was NOT flipped; nothing is lost, the safety copy is intact.")
            by_key_after = {c.key: c for c in after.columns}
            for key, orig in original.items():
                bal = _balance(orig, by_key_after[key])
                report.balance[key] = bal
                if not bal["balanced"]:
                    raise MigrationRefused(f"{key} does not balance after the run. The marker was NOT flipped; the safety copy is intact.")
            if after.to_rewrite:
                raise MigrationRefused("values that should have converted are still there. The marker was NOT flipped; run it again.")
            # The codes inside an alternate's identity and field JSON are not columns, so the sweep never touched them;
            # they move in the SAME transaction as the marker, or a captured `fr` would swap into an alpha-3 store as `fr`.
            from src.backup.country_codes import convert_alternate_countries

            report.alternates = convert_alternate_countries(con, schema="main", form="alpha3")
            cf.write_form(con, "alpha3", by="country-migration")
            journal.update(state="done", finished_at=datetime.now(UTC).isoformat())
            _upsert_json(con, JOURNAL_KEY, journal)
            con.execute("COMMIT")
            report.verify_seconds = time.perf_counter() - t_verify
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        with contextlib.suppress(Exception):  # the next process reads the file
            from src.config.kv_store import kv_invalidate

            kv_invalidate()
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as exc:  # noqa: BLE001 - a checkpoint that cannot run is not a failed migration
            _LOG.debug("checkpoint after the migration did not run (%s)", type(exc).__name__)
        report.state = "done"
        report.finished_at = datetime.now(UTC).isoformat()
        report.message = "migrated: every convertible value is alpha-3 and the store says so"
        say({"phase": "done"})
        return report
    finally:
        report.seconds = time.perf_counter() - t_start
        with contextlib.suppress(Exception):  # closing a connection that already failed
            con.close()


# --------------------------------------------------------------------------- #
#  The command
# --------------------------------------------------------------------------- #
def _human(n: float | int | None) -> str:
    if n is None:
        return "unknown"
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    s = int(seconds)
    return f"{s // 3600} h {(s % 3600) // 60} min" if s >= 3600 else f"{s // 60} min {s % 60} s"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from src.monitoring.secret_scrub import exception_text

    ap = argparse.ArgumentParser(
        prog="open-omniscience migrate-countries",
        description="Move the store's country codes from alpha-2 to alpha-3. Run it with the app CLOSED.",
    )
    ap.add_argument("--estimate", action="store_true", help="read the plan and the free disk; change nothing; the app may stay open")
    ap.add_argument("--yes", action="store_true", help="do not ask before starting (the estimate is still printed)")
    ap.add_argument("--backup-dir", type=Path, default=None, help="where the verified safety copy goes (default: next to the store)")
    ap.add_argument("--json", type=Path, default=None, help="also write the full report here")
    args = ap.parse_args(argv)

    from src.database.session import engine  # the live file, resolved like the app resolves it

    path = Path(engine.url.database) if engine.url.database else None
    if path is None or engine.url.get_backend_name() != "sqlite":
        print("This command works on the local SQLite store only.", file=sys.stderr)
        return 2
    engine.dispose()  # this process must not hold the file itself

    from src.database.connect import get_passphrase, is_encrypted_file, set_passphrase

    if is_encrypted_file(path) and not get_passphrase():
        if not sys.stdin.isatty():
            print("The store is encrypted: set OO_DB_PASSPHRASE, or run this in a terminal.", file=sys.stderr)
            return 2
        import getpass

        set_passphrase(getpass.getpass("Passphrase of the store: "))

    def show(event: dict) -> None:
        ph = event["phase"]
        if ph == "locked":
            print("The database is held exclusively for this run.")
        elif ph == "plan":
            est = event["estimate"]
            print(f"Rows to rewrite: {est['rows_to_rewrite']:,}   Store: {_human(est['store_bytes'])}   Free: {_human(est['free_bytes'])}")
            for key, c in event["plan"]["columns"].items():
                if c["convert"] or c["unmapped"]:
                    print(f"  {key}: {sum(n for v, n in c['spellings'].items() if v in c['convert']):,} to convert, {sum(c['unmapped'].values()):,} left as stored")
            if "time" in est:
                print("Time: " + est["time"])
            else:
                print("Time: about " + _duration(est.get("seconds_about")) + " for the sweep alone.  " + est["basis"])
        elif ph == "backup":
            print(f"Taking the verified safety copy in {event['dir']} ...")
        elif ph == "backup-verified":
            print(f"Safety copy verified: {event['backup']['path']} ({_human(event['backup']['bytes'])})")
        elif ph == "sweep":
            pct = 100 * event["done"] / event["total"] if event["total"] else 100
            print(f"  {event['column']}: rowid {event['cursor']:,} of {event['of']:,}   {event['done']:,}/{event['total']:,} rows ({pct:.1f}%)", flush=True)
        elif ph == "verify":
            print("Verifying every table and column ...")

    def ask(plan: Plan, est: dict) -> bool:
        if args.yes:
            return True
        if not sys.stdin.isatty():
            print("Not a terminal: pass --yes to go on.", file=sys.stderr)
            return False
        return input("Go on? [y/N] ").strip().lower() in ("y", "yes")

    try:
        rep = migrate(path, backup_dir=args.backup_dir, confirm=ask, progress=show, estimate_only=args.estimate)
    except MigrationRefused as exc:
        print(f"Stopped: {exception_text(exc, typed=False)}", file=sys.stderr)
        return 3
    print(rep.message)
    if rep.collisions:
        for c in rep.collisions:
            print(f"  collision in {c['table']}.{c['column']}: {c['rows']} rows would all become {c['becomes']!r} with {c['others']}")
    if rep.unmapped:
        print("Left exactly as stored (no ISO meaning):")
        for key, vals in rep.unmapped.items():
            print(f"  {key}: " + ", ".join(f"{v!r} x{n:,}" for v, n in vals.items()))
    left_in_json = (rep.alternates or {}).get("left_as_stored")
    if left_in_json:
        print("Left exactly as stored inside recorded differences (no ISO meaning):")
        for key, vals in left_in_json.items():
            print(f"  {key}: " + ", ".join(f"{v!r} x{n:,}" for v, n in vals.items()))
    unreadable_json = int((rep.alternates or {}).get("left_unreadable") or 0)
    if unreadable_json:
        # Counted in the report already (R100); said here too, because a count only the --json file carries is a count the
        # operator at the console never sees.
        print(
            f"Recorded differences whose stored JSON could not be read, left untouched: {unreadable_json:,} "
            "(a code inside one of them was not converted; nothing was dropped)."
        )
    if args.json:
        args.json.write_text(json.dumps(rep.__dict__, indent=1, default=str, sort_keys=True), encoding="utf-8")
    return 0 if rep.state in ("done", "already-done", "declined") else 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
