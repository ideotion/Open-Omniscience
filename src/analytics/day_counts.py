"""Per-day keyword mention counts kept in the database, for the Home trending windows (R623, R625).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. ``trending`` sums each mention row's ``count`` per keyword over a recent window and the baseline before it,
three times on the Home poll (24 h, week, month). With the DuckDB rollup off or not built, each sum is a scan
of ``ix_mention_date_keyword`` over up to 37 days: on a 12 M-mention store, 4.2 s plain and 5.1 s encrypted for
the six sums, and the 2026-11-07 field bundle measured 42 s on Home. The same six sums over this table take
0.10 s plain and 0.2 s encrypted (``/mnt/project-files/home-trending-day-counts/``).

THE SHAPE R625 RULED (A2, no insert trigger). An insert trigger costs every new mention: measured, paired, on
SQLCipher, +15.7 % for an upsert trigger, +13.4 % for an append-only log and about +5 % for a trigger that never
fires, past the 5 % gate R623 set. So nothing here runs on an INSERT. Instead:

  * ``keyword_day_counts`` holds ``SUM(count)`` per ``(observed_on, keyword_id)``. A day is always rebuilt
    WHOLE from ``ix_mention_date_keyword`` (one ``INSERT ... SELECT ... WHERE observed_on = ?``), never
    adjusted by a delta, so a day is either exactly the live answer or it is known to be stale.
  * New mentions are found by id: ``keyword_day_state.watermark`` is the highest mention id the table has
    seen. The days of the rows above it (the TAIL) are stale, and are folded in, throttled, by the scheduler's
    idle maintenance (:func:`fold_tail`); until then the serve reads those days live.
  * Deletes and moves cannot be found by id, so two triggers mark the days they touch in
    ``keyword_day_dirty``: an AFTER DELETE (a re-index's removed rows, a keyword prune, every FK cascade from
    an article, a source or a keyword) and an AFTER UPDATE OF ``keyword_id, observed_on, count`` (a re-index
    rewriting a row in place, ``keyword_fold`` moving a keyword's rows). New-article ingest is pure inserts
    and never fires either; a re-index pays them (+5.7 % measured on that pattern).
  * One more way a row can hide below the watermark: SQLite gives a new row ``max(id) + 1``, so deleting the
    TOP rows lets their ids be used again. The delete trigger records the lowest such id in
    ``reuse_floor`` and counts the event in ``floor_gen``, and the tail starts there. A fold moves the watermark to
    the ``max(id)`` it read (never above it: ids between the two would be given out again unseen) and clears the
    floor only when no such delete ran while it worked (``floor_gen`` unchanged).
  * A FULL rebuild runs when the corpus epoch changed (re-index, prune, restore, keyword fold:
    ``src/analytics/corpus_epoch.py``), at the backstop (:data:`BACKSTOP_S`), or when the triggers had to be
    (re)made, which resets the watermark too, so the build starts over rather than resuming. No writer inserts a
    mention with an explicit id (the export lane's read of 2026-11-09 checked every one); the restore swaps in a
    merged copy and bumps the epoch.

READS go through the ``keyword_mentions_all`` view (R96); only the triggers and the install name the table, as a
trigger must. Like ``database.query.windowed_group_counts``, the watermark assumes ONE id space behind the view.

SERVE (:func:`windowed_counts`). Read-only, as every GET must be: only a COMPLETE table built at the CURRENT
epoch, inside its backstop, is used. The stale days of a window (dirty, or in the tail) are summed live, one
day each, and every other day comes from the table, so the answer is exact rather than "as of the last fold".
Today is always stale while collection runs, which is why "only when fully current" would serve nothing.
Anything else -- not built, a build running, an epoch moved, a tail or a stale-day count past its cap, the
date index missing -- answers ``None`` and ``trending`` reads live as before. The country filter always reads
live: the table has no country.

BUILD (:data:`DAY_COUNTS_JOB`). A visible, stoppable background job (the task manager lists it), one day per
transaction under the writer gate, resumable from its stored cursor, standing aside while the storage guard
holds. Queued after the boot's heavy steps and by the idle maintenance when the table is not current.

Counts only. Not a score, no verdict, nothing leaves the machine.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from src.database.writer import write_lock
from src.jobs.background import BackgroundJob, Framed, JobContext, register_job
from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

TABLE = "keyword_day_counts"
DIRTY = "keyword_day_dirty"
STATE = "keyword_day_state"
#: The index every day is rebuilt from, and the live per-day read uses. Without it a day is a table scan
#: (the bulk build may drop it for its window), so the build, the fold and the serve all decline.
DATE_INDEX = "ix_mention_date_keyword"

#: A full rebuild at least this often, whatever the triggers and the epoch say (R625: "a full rebuild runs on
#: an epoch change or at the backstop"). A week: one rebuild is one scan of the date index (4.6 s plain on 12 M
#: mentions), and nothing is known to be missed, so this guards only against what nobody has thought of.
BACKSTOP_S = 7 * 24 * 3600

#: The serve reads live at most this many stale days of one window; more, and the whole window reads live.
MAX_LIVE_DAYS = 8
#: The serve answers ``None`` when the tail (mention ids above the table's watermark) is longer than this: the
#: scan for its days would cost more than it saves. The fold (no cap) catches up between passes.
MAX_TAIL_ROWS = 250_000

JOB_KIND = "keyword-day-counts"
LABEL = "Building the daily keyword counts"
FRAME_BUILDING = "Counting keyword mentions per day: {day} of {days}"

TRIGGERS: dict[str, str] = {
    # A deleted row's day is stale. Then, if the delete left max(id) below the watermark, the ids from
    # max(id) + 1 up to the watermark can be given to new rows; the lowest is kept. Evaluated per row, so
    # whatever order a statement deletes in, the LAST row it deletes leaves the final max(id).
    "trg_keyword_day_dirty_ad": (
        "CREATE TRIGGER IF NOT EXISTS trg_keyword_day_dirty_ad AFTER DELETE ON keyword_mentions "
        "BEGIN "
        "INSERT OR IGNORE INTO keyword_day_dirty (observed_on) "
        "SELECT old.observed_on WHERE old.observed_on IS NOT NULL; "
        "UPDATE keyword_day_state SET "
        "reuse_floor = min(coalesce(reuse_floor, (SELECT coalesce(max(id), 0) + 1 FROM keyword_mentions)), "
        "(SELECT coalesce(max(id), 0) + 1 FROM keyword_mentions)), "
        "floor_gen = coalesce(floor_gen, 0) + 1 "
        "WHERE id = 1 AND watermark IS NOT NULL "
        "AND (SELECT coalesce(max(id), 0) FROM keyword_mentions) < watermark; "
        "END"
    ),
    # A row whose count, keyword or day changed: both its old and its new day are stale.
    "trg_keyword_day_dirty_au": (
        "CREATE TRIGGER IF NOT EXISTS trg_keyword_day_dirty_au "
        "AFTER UPDATE OF keyword_id, observed_on, count ON keyword_mentions "
        "WHEN old.count IS NOT new.count OR old.observed_on IS NOT new.observed_on "
        "OR old.keyword_id IS NOT new.keyword_id "
        "BEGIN "
        "INSERT OR IGNORE INTO keyword_day_dirty (observed_on) "
        "SELECT old.observed_on WHERE old.observed_on IS NOT NULL; "
        "INSERT OR IGNORE INTO keyword_day_dirty (observed_on) "
        "SELECT new.observed_on WHERE new.observed_on IS NOT NULL; "
        "END"
    ),
}

#: Marks the counts unbuilt so the next build STARTS OVER (a build resumes only from a watermark it set at the
#: current epoch): used when a trigger had to be (re)made, and by a salvaged copy (src/database/salvage.py).
UNBUILT_SQL = (
    "UPDATE keyword_day_state SET complete = 0, watermark = NULL, cursor = NULL, built_epoch = NULL, "
    "reuse_floor = NULL WHERE id = 1"
)

#: Held by the build for its whole run and by a fold for its own, so the two never write at once.
_WORK = threading.Lock()


# --------------------------------------------------------------------------------------------- install


def _trigger_body_matches(stored: str | None, wanted: str) -> bool:
    from src.database.source_identity import _trigger_body_matches as match

    return match(stored, wanted)


def install(conn: Connection) -> dict[str, Any]:
    """Make the triggers (or replace one whose body an older build wrote) and the state row, on ``conn``.

    Never builds: the build is the visible job. If any trigger had to be written, the table cannot know what
    happened while it was missing, so it is marked incomplete and the next build starts over. Returns
    ``{"triggers": n}`` (the triggers written) or ``{"state": "absent"}`` when the tables are not there."""
    if conn.dialect.name != "sqlite":
        return {"state": "skipped"}
    names = {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if not {"keyword_mentions", TABLE, DIRTY, STATE} <= names:
        return {"state": "absent"}
    from src.database.source_identity import _owns_the_transaction

    own = _owns_the_transaction(conn)
    if own:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        have = {
            r[0]: r[1]
            for r in conn.exec_driver_sql(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='keyword_mentions'"
            ).fetchall()
        }
        made = 0
        for name, sql in TRIGGERS.items():
            if name in have:
                if _trigger_body_matches(have[name], sql):
                    continue
                conn.exec_driver_sql(f'DROP TRIGGER "{name}"')  # nosec B608 - a name from TRIGGERS, not input
            conn.exec_driver_sql(sql)
            made += 1
        conn.exec_driver_sql(f"INSERT OR IGNORE INTO {STATE} (id, complete) VALUES (1, 0)")  # nosec B608 - a constant
        if made:
            conn.exec_driver_sql(UNBUILT_SQL)
    except BaseException:
        if own:
            conn.exec_driver_sql("ROLLBACK")
        raise
    if own:
        conn.exec_driver_sql("COMMIT")
    return {"triggers": made}


def ensure_day_counts(engine: Engine) -> dict[str, Any]:
    """Boot self-heal (``init_db``): :func:`install` on its own connection. Never raises into boot; without the
    triggers the state stays incomplete (or is marked so) and the serve reads live, as before this table."""
    if engine.url.get_backend_name() != "sqlite":
        return {"state": "skipped"}
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            result = install(conn)
        if result.get("triggers"):
            _LOG.info("daily keyword counts: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001 - the boot goes on; trending reads live
        log_failure(_LOG, "could not set up the daily keyword counts", exc, level=logging.WARNING)
        return {"state": "refused", "error": type(exc).__name__}


# --------------------------------------------------------------------------------------------- state


def _state(conn: Connection) -> dict[str, Any] | None:
    try:
        row = conn.exec_driver_sql(
            f"SELECT complete, built_epoch, watermark, reuse_floor, cursor, started_at, built_at, floor_gen FROM {STATE} WHERE id = 1"  # nosec B608 - a constant
        ).fetchone()
    except Exception:  # noqa: BLE001 - no table yet (a store made before it): not built
        return None
    if row is None:
        return None
    return {
        "complete": bool(row[0]),
        "built_epoch": row[1],
        "watermark": row[2],
        "reuse_floor": row[3],
        "cursor": row[4],
        "started_at": row[5],
        "built_at": row[6],
        "floor_gen": row[7],
    }


def _epoch(conn: Connection) -> int:
    from src.analytics.corpus_epoch import CORPUS_EPOCH_KEY

    try:
        row = conn.exec_driver_sql("SELECT value FROM derived_meta WHERE key = ?", (CORPUS_EPOCH_KEY,)).fetchone()
        return int(row[0]) if row is not None else 0
    except Exception:  # noqa: BLE001 - the same degrade as get_corpus_epoch
        return 0


def _has_date_index(conn: Connection) -> bool:
    return (
        conn.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='index' AND name = ?", (DATE_INDEX,)).fetchone()
        is not None
    )


def _max_id(conn: Connection) -> int:
    return int(conn.exec_driver_sql("SELECT coalesce(max(id), 0) FROM keyword_mentions_all").scalar() or 0)


def _built_at_s(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _past_backstop(state: dict[str, Any], now: float | None = None) -> bool:
    built = _built_at_s(state.get("built_at"))
    return built is None or ((now if now is not None else time.time()) - built) > BACKSTOP_S


def _tail_floor(state: dict[str, Any]) -> int:
    """The highest mention id below which the table has seen every row: the watermark, or under it the first id
    a delete made available again."""
    w = int(state["watermark"] or 0)
    f = state.get("reuse_floor")
    return w if f is None else min(w, int(f) - 1)


def current(conn: Connection) -> str | None:
    """Why the table cannot be used as it stands, or ``None`` when it can (complete, at the current epoch,
    inside its backstop, with the date index there)."""
    st = _state(conn)
    if st is None:
        return "not-installed"
    if not st["complete"] or st["watermark"] is None:
        return "not-built"
    if st["built_epoch"] != _epoch(conn):
        return "epoch-moved"
    if _past_backstop(st):
        return "backstop"
    if not _has_date_index(conn):
        return "no-date-index"
    return None


# --------------------------------------------------------------------------------------------- writes


def _end_read(conn: Connection) -> None:
    """End the read a connection opened (SQLAlchemy refuses ``begin()`` inside the transaction a read began), so
    each write below is: the connection, then the writer gate, then one transaction."""
    if conn.in_transaction():
        conn.commit()


def _day(value: Any) -> date:
    """A day from a stored ``observed_on``: the first ten characters, so a value that ever carries a time part is still its day."""
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value)[:10])


def _iso(d: Any) -> str:
    return d.isoformat() if isinstance(d, date) else str(d)


def _rebuild_day(conn: Connection, day: str, *, after: str | None = None) -> None:
    """The build's step, one transaction under the writer gate: replace ``day``'s rows from the live mentions,
    clear its dirty mark and store the cursor. The days in ``(after, day)`` (every day up to ``day`` on the first
    step) are cleared too: the build's way of dropping days that no longer have a mention."""
    lo_sql, lo_args = ("observed_on > ? AND ", (after,)) if after is not None else ("", ())
    _end_read(conn)
    with write_lock(), conn.begin():
        conn.exec_driver_sql(f"DELETE FROM {TABLE} WHERE {lo_sql}observed_on <= ?", (*lo_args, day))  # nosec B608 - constants
        conn.exec_driver_sql(f"DELETE FROM {DIRTY} WHERE {lo_sql}observed_on <= ?", (*lo_args, day))  # nosec B608 - constants
        conn.exec_driver_sql(
            f"INSERT INTO {TABLE} (observed_on, keyword_id, mentions) "  # nosec B608 - a constant
            "SELECT observed_on, keyword_id, SUM(count) FROM keyword_mentions_all WHERE observed_on = ? GROUP BY keyword_id",
            (day,),
        )
        conn.exec_driver_sql(f"UPDATE {STATE} SET cursor = ? WHERE id = 1", (day,))  # nosec B608 - a constant


def _fold_day(conn: Connection, day: str) -> None:
    _end_read(conn)
    with write_lock(), conn.begin():
        conn.exec_driver_sql(f"DELETE FROM {TABLE} WHERE observed_on = ?", (day,))  # nosec B608 - a constant
        conn.exec_driver_sql(f"DELETE FROM {DIRTY} WHERE observed_on = ?", (day,))  # nosec B608 - a constant
        conn.exec_driver_sql(
            f"INSERT INTO {TABLE} (observed_on, keyword_id, mentions) "  # nosec B608 - a constant
            "SELECT observed_on, keyword_id, SUM(count) FROM keyword_mentions_all WHERE observed_on = ? GROUP BY keyword_id",
            (day,),
        )


def _stand_aside(ctx: JobContext | None) -> bool:
    """Wait while the storage guard's latch holds (as the article-list index build does); ``False`` = stopped."""
    try:
        from src.scheduler.storage_guard import stand_aside_detail, storage_guard

        storage_guard.wait_if_engaged(
            should_stop=lambda: ctx is not None and ctx.stopping,
            on_wait=lambda kind: ctx.set_progress(detail=stand_aside_detail(kind)) if ctx is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 - a guard that cannot be read is not a reason to fail the build
        _LOG.warning("daily keyword counts: the storage guard could not be consulted (%s)", type(exc).__name__)
    return not (ctx is not None and ctx.stopping)


def build(engine: Engine, ctx: JobContext | None = None) -> dict[str, Any]:
    """Build the table day by day, oldest first; resumable. Returns ``{"outcome": ...}``: ``built``,
    ``stopped``, ``declined`` (no date index, or the tables are not installed) or ``busy`` (a fold holds it).

    A build resumes from its cursor when it was started at the current epoch; otherwise it starts over:
    marked incomplete, the watermark taken as today's ``max(id)``, the reuse floor cleared. Each day is one
    transaction under the writer gate, so collection waits at most one day's ``GROUP BY`` (214 ms on the
    longest day of the 12 M-mention bench). A row that lands on a day already built is either above the
    watermark (the tail) or marked dirty by a trigger, so it is never lost; a day not yet built is read
    whole when its turn comes."""
    if not _WORK.acquire(timeout=60):
        return {"outcome": "busy"}
    try:
        with engine.connect() as conn:
            st = _state(conn)
            if st is None:
                return {"outcome": "declined", "reason": "not-installed"}
            if not _has_date_index(conn):
                return {"outcome": "declined", "reason": "no-date-index"}
            epoch = _epoch(conn)
            resume = (not st["complete"]) and st["watermark"] is not None and st["built_epoch"] == epoch
            if not resume:
                _end_read(conn)
                with write_lock(), conn.begin():
                    m = _max_id(conn)
                    conn.exec_driver_sql(
                        f"UPDATE {STATE} SET complete = 0, built_epoch = ?, watermark = ?, reuse_floor = NULL, "  # nosec B608 - a constant
                        "cursor = NULL, started_at = ?, built_at = NULL WHERE id = 1",
                        (epoch, m, datetime.now(UTC).isoformat()),
                    )
                cursor = None
            else:
                cursor = None if st["cursor"] is None else _iso(st["cursor"])
            bounds = conn.exec_driver_sql(
                "SELECT min(observed_on), max(observed_on) FROM keyword_mentions_all WHERE observed_on IS NOT NULL"
            ).fetchone()
            first = _day(bounds[0]) if bounds and bounds[0] else None
            last = _day(bounds[1]) if bounds and bounds[1] else None
            span = ((last - first).days + 1) if first and last else 0
            days = 0
            while True:
                if ctx is not None and ctx.stopping:
                    return {"outcome": "stopped", "days": days, "cursor": cursor}
                if not _stand_aside(ctx):
                    return {"outcome": "stopped", "days": days, "cursor": cursor}
                if cursor is None:
                    nxt = conn.exec_driver_sql(
                        "SELECT min(observed_on) FROM keyword_mentions_all WHERE observed_on IS NOT NULL"
                    ).scalar()
                else:
                    nxt = conn.exec_driver_sql(
                        "SELECT min(observed_on) FROM keyword_mentions_all WHERE observed_on > ?", (cursor,)
                    ).scalar()
                conn.commit()  # end the read the lookup opened, so no snapshot is held between days
                if nxt is None:
                    break
                day = _iso(nxt)
                _rebuild_day(conn, day, after=cursor)
                cursor = day
                days += 1
                if ctx is not None and first is not None:
                    at = (_day(day) - first).days + 1
                    at = max(1, min(at, max(span, at)))
                    ctx.set_progress(
                        done=at, total=max(span, at),
                        detail=Framed(FRAME_BUILDING.format(day=at, days=max(span, at)), FRAME_BUILDING, day=at, days=max(span, at)),
                    )
            _end_read(conn)
            with write_lock(), conn.begin():
                tail_sql, tail_args = ("observed_on > ?", (cursor,)) if cursor is not None else ("1", ())
                conn.exec_driver_sql(f"DELETE FROM {TABLE} WHERE {tail_sql}", tail_args)  # nosec B608 - constants
                conn.exec_driver_sql(f"DELETE FROM {DIRTY} WHERE {tail_sql}", tail_args)  # nosec B608 - constants
                conn.exec_driver_sql(
                    f"UPDATE {STATE} SET complete = 1, built_at = ? WHERE id = 1",  # nosec B608 - a constant
                    (datetime.now(UTC).isoformat(),),
                )
            if ctx is not None:
                ctx.set_progress(done=max(span, 1), total=max(span, 1))
            return {"outcome": "built", "days": days}
    finally:
        _WORK.release()


def fold_tail(engine: Engine, *, should_stop=None) -> dict[str, Any]:
    """Bring a complete table up to date: rebuild every stale day (dirty, or holding a mention above the tail
    floor), then move the watermark. Called by the scheduler's idle maintenance, between passes, so it is
    throttled to that cadence and yields at each day to ``should_stop``. When the table is not current (never
    built, the epoch moved, the backstop passed) it starts the build job instead and returns."""
    stop = should_stop or (lambda: False)
    with engine.connect() as conn:
        why = current(conn)
        conn.commit()
    if why == "not-installed":
        return {"skipped": why}
    if why == "no-date-index":
        return {"skipped": why}
    if why is not None:
        return {"rebuild": why, "job": start_build(engine)}
    if not _WORK.acquire(blocking=False):
        return {"skipped": "busy"}
    try:
        with engine.connect() as conn:
            st = _state(conn)
            if st is None or not st["complete"]:
                return {"skipped": "not-built"}
            # Under the gate, one transaction: the watermark becomes the max(id) read NOW (lower than before when the top
            # rows went, and never above what exists), and what is still unread is said as a floor, so the state means
            # the same thing while the fold works: every id up to ``floor`` is in the table.
            _end_read(conn)
            with write_lock(), conn.begin():
                st = _state(conn)
                if st is None or not st["complete"]:
                    return {"skipped": "not-built"}
                m = _max_id(conn)
                floor = min(_tail_floor(st), m)
                gen = st["floor_gen"]
                conn.exec_driver_sql(
                    f"UPDATE {STATE} SET watermark = ?, reuse_floor = ? WHERE id = 1",  # nosec B608 - a constant
                    (m, floor + 1 if floor < m else None),
                )
            stale = {
                _iso(r[0])
                for r in conn.exec_driver_sql(f"SELECT observed_on FROM {DIRTY}").fetchall()  # nosec B608 - a constant
            }
            stale |= {
                _iso(r[0])
                for r in conn.exec_driver_sql(
                    "SELECT DISTINCT observed_on FROM keyword_mentions_all WHERE id > ? AND id <= ? AND observed_on IS NOT NULL",
                    (floor, m),
                ).fetchall()
            }
            conn.commit()
            folded = 0
            for day in sorted(stale):
                if stop():
                    return {"stopped": True, "days": folded, "left": len(stale) - folded}
                _fold_day(conn, day)
                folded += 1
            # The floor is cleared only if no delete from the top ran while this worked (``floor_gen`` unchanged): such
            # a delete names ids this fold may not have read, and the next fold reads them.
            _end_read(conn)
            with write_lock(), conn.begin():
                cleared = conn.exec_driver_sql(
                    f"UPDATE {STATE} SET reuse_floor = NULL "  # nosec B608 - a constant
                    "WHERE id = 1 AND watermark IS ? AND floor_gen IS ?",
                    (m, gen),
                ).rowcount
            return {"days": folded, "watermark": m, "floor_cleared": bool(cleared)}
    finally:
        _WORK.release()


def drop_keywords(session: Session, keyword_ids: list[int]) -> int:
    """R632: the prune's own step, in ITS transaction (the caller holds the writer gate and commits): delete the day-count
    rows of keywords it is deleting, and return how many of them counted a mention. A keyword is pruned only when it has
    no mention left, so the answer is 0 whenever the counts are right; anything else means they were not, and the caller
    bumps the corpus epoch so they are rebuilt (fails closed)."""
    if not keyword_ids:
        return 0
    conn = session.connection()
    if conn.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (TABLE,)).fetchone() is None:
        return 0  # a store from before the table: nothing to drop, nothing wrong
    holes = ",".join("?" for _ in keyword_ids)
    counted = int(
        conn.exec_driver_sql(
            f"SELECT count(*) FROM {TABLE} WHERE keyword_id IN ({holes}) AND mentions <> 0",  # nosec B608 - placeholders only
            tuple(keyword_ids),
        ).scalar()
        or 0
    )
    conn.exec_driver_sql(f"DELETE FROM {TABLE} WHERE keyword_id IN ({holes})", tuple(keyword_ids))  # nosec B608 - placeholders only
    return counted


# --------------------------------------------------------------------------------------------- serve


def _memo(session: Session) -> dict:
    return session.info.setdefault("keyword_day_counts", {})


def windowed_counts(session: Session, *, lo: date, hi: date, deadline: float | None = None) -> dict[int, int] | None:
    """``{keyword_id: SUM(count)}`` over the INCLUSIVE day range ``[lo, hi]`` (the rollup's convention), or
    ``None`` to read live. Read-only. Exact: the window's stale days are summed live, the others come from the
    table. Within one session the live sums of a day and the tail's days are computed once (``trending_windows``
    asks for six windows in one request).

    ``deadline`` (a ``time.monotonic()`` instant, trending's ``read_deadline``) bounds the live per-day reads: once it
    has passed, the answer is ``None``, and trending's live path then reports the window as over budget (a partial
    Home answer) instead of running into the statement deadline."""
    try:
        conn = session.connection()
        if current(conn) is not None:
            return None
        st = _state(conn)
        if st is None:
            return None
        floor = _tail_floor(st)
        m = _max_id(conn)
        if m - floor > MAX_TAIL_ROWS:
            return None
        memo = _memo(session)
        key = ("tail", floor, m)
        tail_days = memo.get(key)
        if tail_days is None:
            tail_days = {
                _iso(r[0])
                for r in conn.exec_driver_sql(
                    "SELECT DISTINCT observed_on FROM keyword_mentions_all WHERE id > ? AND id <= ? AND observed_on IS NOT NULL",
                    (floor, m),
                ).fetchall()
            }
            memo[key] = tail_days
        lo_s, hi_s = _iso(lo), _iso(hi)
        dirty = {
            _iso(r[0])
            for r in conn.exec_driver_sql(
                f"SELECT observed_on FROM {DIRTY} WHERE observed_on >= ? AND observed_on <= ?", (lo_s, hi_s)  # nosec B608 - a constant
            ).fetchall()
        }
        stale = sorted(dirty | {d for d in tail_days if lo_s <= d <= hi_s})
        if len(stale) > MAX_LIVE_DAYS:
            return None
        holes = ",".join("?" for _ in stale)
        not_stale = f" AND observed_on NOT IN ({holes})" if stale else ""
        out: dict[int, int] = {
            int(k): int(v)
            for k, v in conn.exec_driver_sql(
                f"SELECT keyword_id, SUM(mentions) FROM {TABLE} WHERE observed_on >= ? AND observed_on <= ?{not_stale} "  # nosec B608 - placeholders only
                "GROUP BY keyword_id",
                (lo_s, hi_s, *stale),
            ).fetchall()
        }
        for day in stale:
            if deadline is not None and time.monotonic() >= deadline:
                return None
            dkey = ("day", day, m)
            live = memo.get(dkey)
            if live is None:
                live = {
                    int(k): int(v)
                    for k, v in conn.exec_driver_sql(
                        "SELECT keyword_id, SUM(count) FROM keyword_mentions_all WHERE observed_on = ? AND id <= ? GROUP BY keyword_id",
                        (day, m),
                    ).fetchall()
                }
                memo[dkey] = live
            for k, v in live.items():
                out[k] = out.get(k, 0) + v
        memo["live_days"] = max(int(memo.get("live_days", 0)), len(stale))
        return out
    except Exception as exc:  # noqa: BLE001 - any doubt reads live
        log_failure(_LOG, "daily keyword counts: serve failed; reading live", exc, level=logging.WARNING)
        return None


def basis(session: Session | None = None) -> dict[str, Any]:
    """The disclosure ``trending`` attaches when it served from this table (the rollup's keys, so a reader of
    one reads the other)."""
    live_days = int(_memo(session).get("live_days", 0)) if session is not None else 0
    return {
        "source": "day-counts",
        "store": "database",
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "age_seconds": 0,
        "stale": False,
        "rebuilding": False,
        "live_days": live_days,
        "note": (
            "Served from the per-day keyword counts kept in the database, for speed. Mention counts are exact: "
            "the days that changed since the counts were last brought up to date (today, while collection runs) "
            "were read live."
        ),
    }


# --------------------------------------------------------------------------------------------- job


def _worker(ctx: JobContext, *, engine: Engine | None = None) -> dict[str, Any]:
    if engine is None:
        from src.database import session as _session

        engine = _session.engine
    return build(engine, ctx)


DAY_COUNTS_JOB = register_job(BackgroundJob(JOB_KIND, LABEL, _worker, is_writer=True, cancellable=True))


def start_build(engine: Engine | None = None) -> str:
    """Start the build job unless it runs. ``started``, ``running`` or ``failed`` (no thread)."""
    try:
        DAY_COUNTS_JOB.start(**({"engine": engine} if engine is not None else {}))
        return "started"
    except RuntimeError:
        return "running" if DAY_COUNTS_JOB.status().get("state") == "running" else "failed"


def start_build_if_needed(engine: Engine | None = None) -> str:
    """The boot's call, after the heavy steps: start the build when the table is not current. Never raises."""
    try:
        if engine is None:
            from src.database import session as _session

            engine = _session.engine
        with engine.connect() as conn:
            why = current(conn)
        if why is None:
            return "current"
        if why in ("not-installed", "no-date-index"):
            return why
        return start_build(engine)
    except Exception as exc:  # noqa: BLE001 - best effort; the idle maintenance asks again
        log_failure(_LOG, "daily keyword counts: build not queued", exc, level=logging.INFO)
        return "failed"


__all__ = [
    "BACKSTOP_S",
    "DAY_COUNTS_JOB",
    "JOB_KIND",
    "LABEL",
    "TRIGGERS",
    "basis",
    "build",
    "current",
    "drop_keywords",
    "ensure_day_counts",
    "fold_tail",
    "install",
    "start_build",
    "start_build_if_needed",
    "windowed_counts",
]
