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
        "returns the store to how it was before the run."
    )


def refuse_if_unfinished() -> None:
    """Raise :class:`MigrationUnfinished` when the journal says a run began and did not end. Unreadable is not absent: a
    journal that cannot be read raises :class:`StoreFormUnreadable`."""
    from src.config.kv_store import KvReadError, kv_get_json_checked

    try:
        journal = kv_get_json_checked(JOURNAL_KEY)
    except KvReadError as exc:
        raise StoreFormUnreadable(f"the country migration journal could not be read ({type(exc).__name__})") from None
    if isinstance(journal, dict) and journal.get("state") in UNFINISHED_STATES:
        backup = journal.get("backup")
        raise MigrationUnfinished(unfinished_message(journal.get("state"), backup.get("path") if isinstance(backup, dict) else None))


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
    if not con.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name='app_state'").fetchone():  # noqa: S608  # nosec B608 - `schema` is a module-internal literal alias ("main"/"inc"), never input
        return "alpha2"
    row = con.execute(f'SELECT value FROM {schema}."app_state" WHERE key = ?', (KEY,)).fetchone()  # noqa: S608  # nosec B608 - as above
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
