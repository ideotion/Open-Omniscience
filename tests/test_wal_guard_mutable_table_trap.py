"""PR-D / W1: an empirical, concrete reproduction of parity finding #3 (MEDIUM) --
``_WalGuardResult``'s generic COUNT-based fast-forward reissue mechanism (see its own
"KNOWN LIMITATION" docstring section, ``src/briefing/registry.py``) is a genuine, live
double-count/drop trap for any FUTURE producer that wraps a scan of a MUTABLE table
(one this app's own writers can delete-then-reinsert rows in) with the generic
``_wal_guard`` fallback, rather than a real keyset (``WHERE id > :cursor ORDER BY id``,
the ``build_keyword_daily`` fix).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THIS IS INTENTIONALLY A "PROVE THE DOCUMENTED LIMITATION IS REAL" TEST, NOT A
REGRESSION-AGAINST-A-BUG TEST: nothing in shipped code exercises this vulnerable path
today -- ``build_keyword_daily`` is the ONLY producer that EVER scanned a mutable table
through this generic wrapper, and it was rewritten (see ``refresh_keyword_daily`` and
``tests/test_keyword_daily_scan_bound_race.py``) to use its own real keyset instead,
precisely BECAUSE the generic COUNT-based fast-forward is unsafe here. So this test's
assertions PASS on today's code, on purpose: they empirically confirm the docstring's
"KNOWN LIMITATION" claim is accurate (not merely asserted prose), and serve as a canary
-- if ``_WalGuardResult``'s fast-forward mechanism is ever changed in a way that makes
this scenario stop reproducing, the docstring's KNOWN LIMITATION section (and this
test) both need revisiting together, keeping the code and its own documentation from
drifting apart. No fix belongs in this PR: the only shipped-code path that ever hit
this shape has already been rewritten off the generic mechanism entirely.

REAL SQLITE ROWID SEMANTICS RELIED ON (same as ``tests/test_keyword_daily_scan_bound_
race.py``, empirically confirmed there and reused here): for a plain ``INTEGER PRIMARY
KEY`` (no ``AUTOINCREMENT``), a row inserted WITHOUT an explicit id gets ``(SELECT MAX
(rowid))+1`` from the table's CURRENT state -- so deleting a row that is NOT the
table's current max and reinserting produces a fresh, HIGHER id. This test assigns the
reinsert's id explicitly (11) to keep the reproduction deterministic and
self-documenting, but the shape is the same real idiom ``index_article``'s
delete-then-reinsert uses (this project's own documented "delete-then-reinsert epoch
trap" lesson, CLAUDE.md's Session-rituals subsection).

THE SCENARIO (one delete-then-reinsert): a table of 10 rows (id 1..10, content ``x`` ==
id). A producer wraps ``session.execute(SELECT id, x FROM t)`` -- no ``WHERE``, no
``ORDER BY``, the exact "unfiltered/unordered scan of an [assumed] append-only table"
shape the generic wrapper's own docstring says it protects -- in ``_wal_guard``. It
fetches 4 rows in one ``fetchmany(4)`` call; because this is the wrapper's very FIRST
``fetchmany()`` call ever, ``_WalGuardResult`` unconditionally releases (closes +
commits) right after handing back that first chunk (see ``fetchmany()``'s own ``due``
check: ``self._last_release_mono is None`` is always true on the first call, so no
env/monkeypatch is needed to force this). Between that release and the producer's NEXT
``fetchmany()`` call, id=2 (already delivered) is deleted and its SAME logical content
(``x=2``) is reinserted as a brand-new row, id=11 (a genuine, concurrent delete-then-
reinsert -- e.g. a re-index cycle touching row 2 mid-scan). The next ``fetchmany()``
call transparently reissues the SELECT and skip-fast-forwards by the raw COUNT already
delivered (4) -- but the reissued scan's row COUNT and row ORDER have both shifted, so
the skip boundary no longer lines up with what was actually delivered before.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.briefing import registry
from src.database import session as db_session


def _fresh_engine(db_path):
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    event.listen(eng, "connect", db_session._sqlite_pragmas)
    with eng.connect() as c:
        c.exec_driver_sql("CREATE TABLE t(id INTEGER PRIMARY KEY, x)")
        for i in range(1, 11):
            c.exec_driver_sql(f"INSERT INTO t (id, x) VALUES ({i}, {i})")
        c.commit()
    return eng


def test_a_delete_then_reinsert_mid_scan_both_double_counts_and_drops_a_row(tmp_path):
    """The core reproduction: proves the generic wrapper's fast-forward delivers ``x=2``
    TWICE (once via its original row, once via the reinsert's fresh id=11) and NEVER
    delivers ``x=5`` even once, despite id=5/x=5 existing in the table for the scan's
    entire duration -- confirmed directly against the live table at the end, so the
    "drop" claim rests on evidence, not just an absent value in the delivered list.
    """
    eng = _fresh_engine(tmp_path / "wal_guard_mutable_trap.db")
    Session = sessionmaker(bind=eng, future=True)
    scanner = Session()
    writer = Session()

    delivered: list[int] = []
    try:
        with registry._wal_guard(scanner):  # noqa: SLF001 - exercising the mechanism directly
            result = scanner.execute(text("SELECT id, x FROM t"))

            # First fetchmany() call: delivers the ORIGINAL, unmutated rows [1,2,3,4] --
            # and, per the module docstring above, unconditionally releases (closes)
            # right after, since this is the wrapper's very first ever fetchmany() call.
            chunk1 = result.fetchmany(4)
            delivered.extend(row[1] for row in chunk1)
            assert delivered == [1, 2, 3, 4], f"unexpected first chunk: {delivered}"

            # The concurrent delete-then-reinsert, mid-scan, on a SEPARATE connection --
            # id=2 (already delivered) is deleted; its SAME logical content (x=2)
            # reappears as a brand-new row, id=11 (a genuinely higher, never-before-seen
            # id, per the rowid-reuse rule quoted in the module docstring: id=2 is not
            # the table's current max, so the freed slot is never reused).
            writer.execute(text("DELETE FROM t WHERE id=2"))
            writer.execute(text("INSERT INTO t (id, x) VALUES (11, 2)"))
            writer.commit()

            # Second fetchmany() call: this is where the trap fires. _reopen_if_needed()
            # reissues "SELECT id, x FROM t" against the NOW-MUTATED table (rows id
            # 1,3,4,5,6,7,8,9,10,11 in rowid-ascending scan order) and fast-forwards by
            # the raw COUNT already delivered (4) -- skipping [1,3,4,5] -- before this
            # call's own fetchmany(100) hands back whatever remains: [6,7,8,9,10,11].
            chunk2 = result.fetchmany(100)
            delivered.extend(row[1] for row in chunk2)

        # THE DOUBLE-COUNT: x=2's content is delivered twice -- once as the original row
        # (before the delete), once via the reinsert's fresh id=11 (after the reissue).
        assert delivered.count(2) == 2, (
            f"expected x=2 to be double-counted (delivered once at its original id, "
            f"once again at the reinsert's fresh id) -- got it {delivered.count(2)} "
            f"time(s) in {delivered}"
        )

        # THE DROP: x=5 is never delivered at all, despite existing in the table for
        # the scan's ENTIRE duration -- the fast-forward's skip boundary shifted past it
        # because the mutated table has one fewer row before that boundary than the
        # original did.
        assert 5 not in delivered, (
            f"expected x=5 to be silently dropped by the fast-forward's shifted skip "
            f"boundary -- but it WAS delivered: {delivered}"
        )
        still_exists = writer.execute(text("SELECT COUNT(*) FROM t WHERE x=5")).scalar()
        assert still_exists == 1, (
            "x=5 must still genuinely exist in the table throughout (proving this is a "
            "real drop by the scan, not merely a row that was itself deleted)"
        )

        # Sanity on the delivered TOTAL: 10 values delivered (4 + 6), covering 9
        # DISTINCT x-values (1,2,3,4,6,7,8,9,10 -- x=2 counted twice, x=5 never) even
        # though the live table holds exactly 10 rows with 10 distinct x-values
        # (1,3,4,5,6,7,8,9,10,2) the whole time -- the wrapper's delivered stream
        # matches neither the table's starting nor ending state.
        assert len(delivered) == 10
        assert sorted(set(delivered)) == [1, 2, 3, 4, 6, 7, 8, 9, 10]
    finally:
        scanner.close()
        writer.close()
        eng.dispose()
