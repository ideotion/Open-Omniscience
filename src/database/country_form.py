"""The form a store keeps its country codes in, and the column type that speaks it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY A STORE-LEVEL FACT (Q301 = c, gate row B, brief S05-02). The corpus held ISO 3166-1 alpha-2
(``fr``) since the first row. The 0.5 storage half moves it to alpha-3 (``FRA``). A move of that
size is never instantaneous on a real corpus: millions of keyword-mention rows, rewritten in
batches while the app is stopped. Until the last batch lands the store is in ONE form, never two,
because the dangerous state is the mixed one: an equality filter on ``FRA`` misses every ``fr`` row,
and a restore keyed on the value duplicates what it should have deduplicated.

So the form is a fact about the FILE, kept in the file (``app_state`` key ``store.country_form``), and
it changes in exactly one place: the last transaction of a migration that has just verified there is
nothing left to convert (``src/backup/country_migration.py``). A store with no such row is alpha-2,
which is every store that exists today; a store the app CREATES is stamped alpha-3 at birth.

THE BOUNDARY (:class:`CountryCode`). The Python side of the app speaks lowercase alpha-2 in 0.5-B1
whatever the store holds, so no payload, filter, export or test changes with the migration:

* a value BOUND for a write or a comparison is converted to the store's form;
* a value READ back is lowercase alpha-2.

Both directions FAIL CLOSED the way ``to_iso2``/``to_iso3`` do: a value with no ISO meaning (``uk``,
``eu``, ``int``, an aggregate, junk) passes through exactly as it is. Converting it to ``None`` would
delete the operator's data to make a code table happy (R100).

An alpha-2 store is untouched on the way in (nothing is converted). On the way out a three-letter code is read as its
alpha-2: such a store does not hold one written by the app, and one that does (a file filled by hand) reads as alpha-2
while it stays as stored, so a filter written ``== "fr"`` misses it. That is the store's own mixed state, which the scan
(``scan_country_code_duplicates``) reports; it is not made worse here.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
from collections.abc import Iterator
from typing import Literal

from sqlalchemy.types import String, TypeDecorator

_LOG = logging.getLogger(__name__)

Form = Literal["alpha2", "alpha3"]

#: The ``app_state`` key. One JSON object: ``{"form": "alpha3", ...}`` plus what wrote it.
KEY = "store.country_form"


class StoreFormUnreadable(RuntimeError):
    """The store's country form could not be read, so no code may be written or compared.

    Unreadable is not absent: reading a locked or damaged store as "alpha-2" would write the
    wrong form into a migrated store, which is the mixed state this module exists to prevent.
    """


#: The migration's journal (``src/backup/country_migration.py`` writes it, in the same transaction as each window).
JOURNAL_KEY = "store.country_migration"
#: Journal states that mean some rows hold alpha-3 while the marker still says alpha-2.
UNFINISHED_STATES = ("running", "interrupted")


class MigrationUnfinished(StoreFormUnreadable):
    """A migration converted some rows and did not finish, so the store holds both forms.

    A subclass of :class:`StoreFormUnreadable` on purpose: every place that already fails closed when the form cannot be
    read fails closed here too, and for the same reason (an equality filter on ``fr`` misses the converted rows, a
    restore keyed on the value duplicates what it should have deduplicated, and one app write would make the
    run unfinishable by changing a row count)."""


def unfinished_message(state: object, backup: object = None) -> str:
    where = f" at {backup}" if isinstance(backup, str) and backup else ""
    return (
        f"a country-form migration of this store started and did not finish (state: {state}). Some rows may already hold "
        "alpha-3 while the store still says alpha-2, so the app will not open or write it until the run is finished. Close "
        "everything that has the store open and run `open-omniscience migrate-countries`: it resumes where it stopped. If it "
        f"reports that it cannot finish, the verified safety copy taken before the run began{where} can be put back, which "
        "returns the store to how it was before the run: with the app closed, copy that file over the store file, delete "
        "the -wal and -shm files that sit beside the store file, and start again."
    )


def held_message() -> str:
    """What a start or a read of the form says when another program holds the store, so its country form could not be read
    (R788).

    The migration holds the file for its whole run, and before this a start under it said "the journal could not be
    read", which points at a damaged store. Nothing was read and nothing is known to be wrong: the file is in use. It says
    nothing about writes, because the same words answer a read, and it names the wait so a slow answer is explained (an
    answer repeated from the short failure hold comes at once). The migration is the one program of ours that holds the
    store exclusively; another program that opened it (a sqlite3 shell) could too, and the words do not name it."""
    return (
        "the store is in use by another program, so its country form could not be read. The app waits up to 30 seconds "
        "for the store to be free before it says so. A country-code migration (`open-omniscience migrate-countries`) "
        "holds the store this way for its whole run. Let it finish, then try again."
    )


def refuse_if_unfinished() -> None:
    """Raise :class:`MigrationUnfinished` when the journal says a run began and did not end. Unreadable is not absent: a
    journal that cannot be read raises :class:`StoreFormUnreadable`."""
    from src.config.kv_store import KvReadError, kv_get_json_checked

    try:
        journal = kv_get_json_checked(JOURNAL_KEY)
    except KvReadError as exc:
        if getattr(exc, "held", False):
            raise StoreFormUnreadable(held_message()) from None
        raise StoreFormUnreadable(f"the country migration journal could not be read ({type(exc).__name__})") from None
    if isinstance(journal, dict) and journal.get("state") in UNFINISHED_STATES:
        backup = journal.get("backup")
        raise MigrationUnfinished(unfinished_message(journal.get("state"), backup.get("path") if isinstance(backup, dict) else None))


_RECHECK_SQL = 'SELECT key, value FROM "app_state" WHERE key IN (?, ?)'


def recheck_on_new_connection(dbapi_connection) -> None:
    """Make the process's cached form and journal answer only what THIS file says now, and refuse the connection when the
    store's run state is not known to be sound (R788, row 309).

    The migration takes the file only while no connection of any process is open on it, so a process that is alive with
    an EMPTY pool (after a restore, repair, rebuild, unlock or panic disposed it) does not stop it, and once it is done
    that process's cache still says alpha-2 and "no journal": measured, its next write put ``de`` beside ``FRA`` under an
    alpha-3 marker, and after an interrupted run its writes made the resume unfinishable. Every read and write reaches the
    file through a connection, and after such a gap the first one is a NEW physical connection; this runs on it (the
    ``connect`` event of the corpus engine and of the read-snapshot engine) and reads the two rows through it, before
    any statement of the caller's runs on it. (A value a caller took from :func:`store_form` BEFORE asking for a
    connection, such as :func:`alpha2_order` building a query, was taken from the cache as it then stood.)

    - The cache: equal values cost one indexed read; a different value drops the cached entry, so the next
      :func:`store_form` reads the file. Either way the key's version moves, so a read of that key that began earlier,
      perhaps on the file as it was before a migration, never stores what it read.
    - The refusal, with the connection closed: a journal naming a run that began and did not end (``running`` /
      ``interrupted``) raises :class:`MigrationUnfinished`; rows that cannot be read (the file held, a damaged page) or a
      journal row that is not a JSON object raise :class:`StoreFormUnreadable`. Unreadable is not "no run". Only a store
      with no ``app_state`` table yet (a new file before ``create_all``) is let through without the rows: it has no run.
      A corruption answer is recorded as damage first (:func:`_note_damage`), since a refusal here never reaches the
      engine's damage observer.

    While this connection, or any other, stays open no migration can start, so what the cache holds from here on is what
    the file holds."""
    from src.config import kv_store

    try:
        cur = dbapi_connection.cursor()
        try:
            rows = dict(
                cur.execute(_RECHECK_SQL, (KEY, JOURNAL_KEY)).fetchall()
            )
        finally:
            cur.close()
    except Exception as exc:  # noqa: BLE001 - classified: a store with no app_state yet has no run; the rest refuses
        if _no_app_state_yet(exc):
            return
        held = _held(exc)
        damaged = _note_damage(exc)
        _LOG.debug("country form recheck on a new connection not read (%s); connection refused", type(exc).__name__)
        _close_quietly(dbapi_connection)
        if held:
            raise StoreFormUnreadable(held_message()) from None
        if damaged:
            raise StoreFormUnreadable(
                "the store is damaged where its country form is kept, so it could not be read on a new connection; the "
                "damage has been recorded (Diagnostics) and nothing was read or written"
            ) from None
        raise StoreFormUnreadable(
            f"the country form of the store could not be read on a new connection ({type(exc).__name__})"
        ) from None
    for key in (KEY, JOURNAL_KEY):
        kv_store.kv_forget_if_changed(key, rows.get(key))
    state, backup = _unfinished_state(rows.get(JOURNAL_KEY))
    if state is None:
        return
    _close_quietly(dbapi_connection)
    if state is _DAMAGED:
        raise StoreFormUnreadable("the country migration journal could not be read (it is not a JSON object)")
    raise MigrationUnfinished(unfinished_message(state, backup))


def _no_app_state_yet(exc: BaseException) -> bool:
    """A new file before ``create_all``: the table the rows live in does not exist yet. By SQLite's fixed words only."""
    return "no such table" in str(exc).lower()


def _held(exc: BaseException) -> bool:
    """SQLite's locked/busy answer: another connection holds the file. By its fixed words only."""
    from src.database.write import is_locked_error

    return is_locked_error(exc)


def _note_damage(exc: BaseException) -> bool:
    """A corruption answer is recorded as the engine's own damage observer would have recorded it: a refusal raised in a
    connect event never reaches SQLAlchemy's ``handle_error``, so without this the incident (the latch that pauses the
    writers, the record the next start plans a check from) would be lost. Returns whether it was corruption."""
    from src.database import damage

    return damage.registry.note(damage.FILE_CORPUS, exc, statement=_RECHECK_SQL)


def _close_quietly(dbapi_connection) -> None:
    try:
        dbapi_connection.close()
    except Exception:  # noqa: BLE001 - the refusal raised next is the answer; a failed close leaves it to the collector
        _LOG.debug("country form recheck: the refused connection did not close cleanly")


#: What :func:`_unfinished_state` answers for a journal row that is there and is not a JSON object.
_DAMAGED = "damaged"


def _unfinished_state(raw: object) -> tuple[str | None, str | None]:
    """``(state, backup path)`` when the journal names an unfinished run; ``(_DAMAGED, None)`` when the row is there and
    is not a JSON object (unreadable is not "no run"); ``(None, None)`` when there is no row or the run ended."""
    if raw is None:
        return None, None
    try:
        journal = json.loads(raw) if isinstance(raw, (str, bytes)) else None
    except ValueError:
        journal = None
    if not isinstance(journal, dict):
        return _DAMAGED, None
    if journal.get("state") not in UNFINISHED_STATES:
        return None, None
    backup = journal.get("backup")
    path = backup.get("path") if isinstance(backup, dict) else None
    return str(journal.get("state")), path if isinstance(path, str) else None


def form_from_value(value: dict | None) -> Form:
    """The form a stored marker names. Anything but an explicit ``alpha3`` is alpha-2: the marker's
    absence is the state of every store that predates it."""
    return "alpha3" if isinstance(value, dict) and value.get("form") == "alpha3" else "alpha2"


#: The form a block of code writes in when it writes into a file that is NOT the live store (a generator building a
#: pre-migration corpus, a test building a side corpus). Per context, so it cannot leak into the live store's writers.
_WRITING_IN: contextvars.ContextVar[Form | None] = contextvars.ContextVar("oo_country_form_override", default=None)


@contextlib.contextmanager
def writing_in(form: Form) -> Iterator[None]:
    """Everything bound in this block (this thread/context) is written in ``form``, whatever the live store holds.

    For code that fills a file that is not the live store: the type cannot see which file a session is bound to, and
    writing a side corpus in the live store's form is the bug this exists to prevent."""
    token = _WRITING_IN.set(form)
    try:
        yield
    finally:
        _WRITING_IN.reset(token)


def store_form() -> Form:
    """The live store's country form (cached in-process by the settings store; a restore or a
    migration drops the entry), unless a block says it is writing a side file (:func:`writing_in`).
    Raises :class:`StoreFormUnreadable` when it cannot be read, and :class:`MigrationUnfinished` (its subclass) when a
    migration began and did not end."""
    forced = _WRITING_IN.get()
    if forced is not None:
        return forced
    from src.config.kv_store import KvReadError, kv_get_json_checked

    refuse_if_unfinished()  # a store that holds both forms is not read as either
    try:
        return form_from_value(kv_get_json_checked(KEY))
    except KvReadError as exc:
        if getattr(exc, "held", False):
            raise StoreFormUnreadable(held_message()) from None
        raise StoreFormUnreadable(f"the country form of the store could not be read ({type(exc).__name__})") from None


def alpha2_order(column):
    """``column`` as an ORDER BY key that sorts in the Python side's alpha-2, whatever the store holds.

    Sorting a country column by its stored text orders ``AUS`` before ``AUT`` where ``at`` comes before ``au``, so an
    alpha-3 store would list the same rows in another order than an alpha-2 one: a change of payload B1 promises not to
    make. In an alpha-2 store the column itself is the key. A value with no alpha-3 meaning sorts as stored, as it reads."""
    if store_form() != "alpha3":
        return column
    from sqlalchemy import case
    from sqlalchemy.types import String as _String

    from src.catalog.countries import ISO3_TO_ISO2

    raw = column.expression if hasattr(column, "expression") else column
    return case(*[(raw == a3.upper(), a2) for a3, a2 in sorted(ISO3_TO_ISO2.items())], else_=raw).cast(_String)


def order_key(value, *then):
    """A Python sort key that orders rows as ``ORDER BY <country column>, ...`` does in an alpha-2 store: NULL first, then the
    value as the Python side reads it (lowercase alpha-2), then ``then``. For the few lists that are read whole and sorted here
    because the column's STORED text (alpha-3) would order them differently."""
    return (value is not None, value or "", *then)


def read_form(con) -> Form:
    """The form of the database ``con`` is open on (a plain DB-API connection, ``main`` schema, or the
    ``schema`` named). Used by the migration and the restore, which hold a connection and must not go
    through the process-wide cache."""
    return read_form_in(con, "main")


def read_form_in(con, schema: str) -> Form:
    import json

    # Asked of the schema, not read off an engine's message: a file with no ``app_state`` table is alpha-2 (every store that
    # predates the marker), and a read that fails for any other reason raises (unreadable is not absent).
    if not con.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name='app_state'").fetchone():  # noqa: S608  # nosec B608 # `schema` is a module-internal literal alias ("main"/"inc"), never input
        return "alpha2"
    row = con.execute(f'SELECT value FROM {schema}."app_state" WHERE key = ?', (KEY,)).fetchone()  # noqa: S608  # nosec B608 # as above
    if not row:
        return "alpha2"
    try:
        return form_from_value(json.loads(row[0]))
    except ValueError:
        raise StoreFormUnreadable("the stored country form is not readable JSON") from None


def write_form(con, form: Form, *, by: str) -> None:
    """Write the marker through ``con`` WITHOUT committing: the migration commits it in the same
    transaction as its last batch, so the data and the claim about it change together or not at all."""
    import json
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    con.execute('CREATE TABLE IF NOT EXISTS "app_state" (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)')
    con.execute(
        'INSERT INTO "app_state" (key, value, updated_at) VALUES (?, ?, ?) '
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (KEY, json.dumps({"form": form, "set_by": by, "at": now}, sort_keys=True), now),
    )


def stamp_new_store(engine, *, had_tables: bool) -> bool:
    """Stamp a store the app has just CREATED as alpha-3. ``had_tables`` is what the caller saw before
    ``create_all``: a store that already held tables is somebody's corpus and keeps the form it has.
    Returns whether it stamped."""
    if had_tables:
        return False
    from sqlalchemy import text

    from src.config import kv_store

    with engine.begin() as conn:
        # Through the ENGINE's own connection, in the first transaction the new file sees: nothing
        # else can have written a country yet, so no row can precede the claim.
        conn.execute(text('CREATE TABLE IF NOT EXISTS "app_state" (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)'))
        have = conn.execute(text('SELECT 1 FROM "app_state" WHERE key = :k'), {"k": KEY}).first()
        if have:
            return False
        import json
        from datetime import UTC, datetime

        from src.backup.country_codes import CANONICAL_COUNTRY_FORM

        now = datetime.now(UTC).isoformat()
        conn.execute(
            text('INSERT INTO "app_state" (key, value, updated_at) VALUES (:k, :v, :t)'),
            {"k": KEY, "v": json.dumps({"form": CANONICAL_COUNTRY_FORM, "set_by": "new-store", "at": now}, sort_keys=True), "t": now},
        )
    kv_store.kv_invalidate(KEY)
    return True


class CountryCode(TypeDecorator):
    """A country column: Python speaks lowercase alpha-2, the file speaks the store's form."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or not isinstance(value, str):
            return value
        if store_form() != "alpha3":
            return value  # an alpha-2 store is written exactly as it always was
        from src.catalog.countries import to_iso3

        code = to_iso3(value)
        return code if code is not None else value

    def process_result_value(self, value, dialect):
        if value is None or len(value) != 3:
            return value
        from src.catalog.countries import to_iso2

        code = to_iso2(value)
        return code if code is not None else value
