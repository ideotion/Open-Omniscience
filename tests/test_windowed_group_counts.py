"""The two reads the 10-06 pin reports named are read in SHORT statements (WAL / disk thread, read-chunking PR).

``trending()._counts`` was one ``GROUP BY keyword_id`` over a date window, open until the last group was
read, and ``corpus_keywords`` was one ``GROUP BY`` over an article set; the guard's pin reports named both
(``fetchmany`` for 1,496 s on one machine, ``cursor.execute`` for 1,428 s on another). A statement that is
running is a reader a WAL checkpoint cannot pass, so these tests run against REAL WAL files and ask the one
question that matters, with a second connection: while this read is between two statements, can a checkpoint
pass? They also hold the answer equal to the single statement's, with writes landing between statements,
because a chunked read that is merely fast is worse than a slow one that is right.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database import query as dq
from src.database.derived_views import KeywordMentionRead as KM
from src.database.models import Article, Base, Keyword, KeywordMention, Source

TODAY = date(2026, 10, 6)
DAYS = 12
KEYWORDS = 60
ARTICLES = 90


def _build(tmp_path, *, seed: int = 5):
    """A real WAL database with the real schema, indexes and view: ``ARTICLES`` articles over ``DAYS`` days,
    each mentioning a handful of the ``KEYWORDS`` keywords (ids are NOT dense: every third id is skipped, as
    in a corpus whose keywords were folded and deleted)."""
    path = tmp_path / "chunk.db"
    engine = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _wal(dbapi, _rec):  # noqa: ANN001
        dbapi.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    rng = random.Random(seed)
    kids = [i for i in range(1, KEYWORDS * 2) if i % 3]
    with Sess() as s:
        s.add(Source(name="S", domain="x.test", country="fr"))
        s.commit()
        # every fifth keyword is an entity, so the ``kind`` filters of corpus_keywords have something to tell apart
        s.add_all(
            Keyword(id=k, term=f"t{k}", normalized_term=f"t{k}", language="en", is_entity=k % 5 == 0,
                    entity_type="person" if k % 10 == 0 else ("entity" if k % 5 == 0 else None))
            for k in kids
        )
        s.commit()
        for aid in range(1, ARTICLES + 1):
            s.add(
                Article(
                    url=f"https://x.test/{aid}",
                    canonical_url=f"https://x.test/{aid}",
                    source_id=1,
                    title="t",
                    content="c",
                    hash=f"h{aid}",
                    language="en",
                    created_at=datetime.now(UTC),
                )
            )
        s.commit()
        for aid in range(1, ARTICLES + 1):
            day = TODAY - timedelta(days=rng.randrange(DAYS))
            for k in rng.sample(kids, 6):
                s.add(
                    KeywordMention(
                        keyword_id=k,
                        article_id=aid,
                        count=rng.randint(1, 4),
                        observed_on=day,
                        country=rng.choice(["fr", "de"]),
                    )
                )
        s.commit()
    return engine, Sess, path


@pytest.fixture
def corpus(tmp_path):
    engine, Sess, path = _build(tmp_path)
    yield engine, Sess, path
    engine.dispose()


def _reference(session, lo, hi, keep, where=()):
    """The single statement the helper replaces: one GROUP BY over the window."""
    stmt = (
        select(KM.keyword_id, func.sum(KM.count))
        .where(KM.observed_on >= lo, KM.observed_on < hi, *where)
        .group_by(KM.keyword_id)
    )
    return dq.grouped_counts(session, stmt, keep)


def _chunked(session, lo, hi, keep, where=(), **kw):
    return dq.windowed_group_counts(
        session,
        key=KM.keyword_id,
        day=KM.observed_on,
        rowid=KM.id,
        value=func.sum(KM.count),
        lo=lo,
        hi=hi,
        keep=keep,
        where=where,
        **kw,
    )


def _always(_k, _v):
    return True


# --------------------------------------------------------------------------- #
#  the same answer as the one statement
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("width", [1, 4, 7, 50, 10_000])
@pytest.mark.parametrize("span", [(0, 1), (0, 5), (3, 9), (0, DAYS + 3)])
def test_the_chunked_answer_is_the_single_statements_for_every_range_width_and_window(corpus, width, span):
    _engine, Sess, _ = corpus
    lo, hi = TODAY - timedelta(days=span[1] - 1), TODAY - timedelta(days=span[0] - 1)
    with Sess() as s:
        want = _reference(s, lo, hi, _always)
        got = _chunked(s, lo, hi, _always, range_ids=width)
    assert got == want
    assert list(got[0].items()) == list(want[0].items()), "ascending keyword order is part of the contract"


def test_keep_decides_the_dict_and_groups_still_counts_every_keyword(corpus):
    _engine, Sess, _ = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    with Sess() as s:
        every, groups = _reference(s, lo, hi, _always)
        keep = lambda k, v: int(v) >= 9  # noqa: E731
        want = _reference(s, lo, hi, keep)
        got = _chunked(s, lo, hi, keep, range_ids=7)
    assert got == want and 0 < len(got[0]) < groups == len(every)


def test_the_country_filter_is_the_same_filter(corpus):
    _engine, Sess, _ = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    with Sess() as s:
        where = (KM.country == "de",)
        assert _chunked(s, lo, hi, _always, where, range_ids=9) == _reference(s, lo, hi, _always, where)
        assert _chunked(s, lo, hi, _always, where, range_ids=9) != _reference(s, lo, hi, _always)


def test_an_empty_table_and_an_empty_window_answer_nothing(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        assert _chunked(s, TODAY - timedelta(days=3), TODAY, _always) == ({}, 0)
    engine.dispose()


def test_a_window_with_no_days_is_empty_not_an_error(corpus):
    _engine, Sess, _ = corpus
    with Sess() as s:
        assert _chunked(s, TODAY, TODAY, _always) == ({}, 0)
        assert _chunked(s, TODAY, TODAY - timedelta(days=2), _always) == ({}, 0)


def test_a_wider_window_than_the_day_axis_allows_is_one_statement_as_before(corpus, monkeypatch):
    _engine, Sess, _ = corpus
    monkeypatch.setattr(dq, "MAX_WINDOW_DAYS", 3)
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    seen: list[str] = []
    event.listen(_engine, "before_cursor_execute", lambda c, cur, st, p, ctx, many: seen.append(st))
    with Sess() as s:
        got = _chunked(s, lo, hi, _always)
        assert got == _reference(s, lo, hi, _always)
    assert sum("GROUP BY" in st for st in seen) == 2, "one statement for the call, one for the reference"


@pytest.mark.parametrize("cap,width", [(3 * (DAYS + 1), 1), (50, 1), (47, 1), (100, 10), (155, 10)])
def test_the_statement_budget_widens_the_key_range_before_it_issues_more(corpus, monkeypatch, cap, width):
    """A cap of 50 over 13 days and 119 keys is the shape that overshot (width 31 gave four ranges, 52 statements).
    The last two sit between the cap and twice the cap (12 ranges x 13 days = 156 statements at width 10): a budget
    that only bites at twice the cap would let them through."""
    _engine, Sess, _ = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    seen: list[str] = []
    event.listen(_engine, "before_cursor_execute", lambda c, cur, st, p, ctx, many: seen.append(st))
    with Sess() as s:
        want = _reference(s, lo, hi, _always)
        seen.clear()
        monkeypatch.setattr(dq, "MAX_RANGE_STATEMENTS", cap)
        got = _chunked(s, lo, hi, _always, range_ids=width)
    assert got == want
    day_statements = [st for st in seen if "GROUP BY" in st]
    assert len(day_statements) <= cap, "the budget is a ceiling on short statements"
    assert len(day_statements) < 119 * (DAYS + 1), "a range of one key was used: the budget widened nothing"


def test_a_call_issues_ranges_times_days_statements_and_three_probes(corpus):
    """The statement count is the arithmetic the docstring states: ceil(span / width) ranges times the days of
    the window, plus the three probes."""
    engine, Sess, _ = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    seen: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda c, cur, st, p, ctx, many: seen.append(st))
    with Sess() as s:
        span = _key_span(s)
        seen.clear()
        _chunked(s, lo, hi, _always, range_ids=10)
    groups = [st for st in seen if "GROUP BY" in st]
    assert len(groups) == -(-span // 10) * (hi - lo).days
    assert len(seen) == len(groups) + 3, "three probes (top row, lowest key, highest key) and the seeks"


# --------------------------------------------------------------------------- #
#  the point: nothing is held between statements, and each statement is one seek
# --------------------------------------------------------------------------- #
def _checkpoint_passes(path) -> tuple[int, int, int]:
    """Commit one write on ANOTHER connection, then ask for a TRUNCATE checkpoint. busy=1 = a reader is in
    the way (the very thing the guard's pin reports measure); busy=0 = nothing older than the write holds
    the log."""
    con = sqlite3.connect(path, timeout=5)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=0")  # a blocked checkpoint answers busy=1 at once, it does not wait
        con.execute("INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on) VALUES (1, 1, 1, '1999-01-01') "
                    "ON CONFLICT DO NOTHING")
        con.execute("UPDATE keywords SET term = term WHERE id = 1")
        con.commit()
        return tuple(con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
    finally:
        con.close()


def test_a_checkpoint_passes_every_time_keep_is_asked_but_not_while_the_old_statement_is_open(
    corpus, monkeypatch
):
    """The chunked read asks ``keep`` only between statements; ``grouped_counts`` asks it with the cursor open."""
    _engine, Sess, path = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    chunked_busy: list[int] = []
    with Sess() as s:
        _chunked(s, lo, hi, lambda k, v: chunked_busy.append(_checkpoint_passes(path)[0]) or True, range_ids=11)
    assert len(chunked_busy) > 20 and set(chunked_busy) == {0}, "a reader held the log between statements"

    monkeypatch.setattr(dq, "GROUPED_CHUNK", 2)  # the old cursor stays open between fetches
    old_busy: list[int] = []
    with Sess() as s:
        _reference(s, lo, hi, lambda k, v: old_busy.append(_checkpoint_passes(path)[0]) or True)
    assert 1 in old_busy, "the contrast case did not pin: this test would pass for the wrong reason"


@pytest.mark.parametrize("country", [None, "fr"])
def test_each_statement_is_one_day_of_one_key_range_over_the_index_that_leads_with_the_day(corpus, country):
    """The plan IS the claim: ``observed_on = ? AND keyword_id`` range on ``ix_mention_date_keyword``, no temp
    b-tree. With the country filter the index is no longer covering (the country is not in it), but it is
    the same seek, as before the change. (Several days in one ``IN`` list were tried and refused: with the
    country filter the planner then chose ``ix_mention_country (country=? AND rowid<?)`` for EVERY statement,
    a scan of the country's rows per range.)"""
    engine, Sess, path = corpus
    seen: list[tuple[str, tuple]] = []
    event.listen(engine, "before_cursor_execute", lambda c, cur, st, p, ctx, many: seen.append((st, tuple(p))))
    lo, hi = TODAY - timedelta(days=2), TODAY + timedelta(days=1)
    where = (KM.country == country,) if country else ()
    with Sess() as s:
        _chunked(s, lo, hi, _always, where=where, range_ids=20)
    group_by = [(st, p) for st, p in seen if "GROUP BY" in st]
    assert len(group_by) >= 3
    st, params = group_by[0]
    con = sqlite3.connect(path)
    try:
        plan = " ".join(str(r[3]) for r in con.execute("EXPLAIN QUERY PLAN " + st, params))
    finally:
        con.close()
    assert "INDEX ix_mention_date_keyword" in plan and "observed_on=?" in plan and "keyword_id>" in plan, plan
    if not country:
        assert "COVERING INDEX" in plan, plan
    assert "TEMP B-TREE" not in plan, "the group came out in index order: nothing is sorted"


# --------------------------------------------------------------------------- #
#  writes landing BETWEEN statements do not change the answer
# --------------------------------------------------------------------------- #
def test_rows_written_between_statements_are_not_counted_so_the_chunked_answer_is_the_start_snapshot(corpus):
    engine, Sess, path = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    with Sess() as s:
        want = _reference(s, lo, hi, _always)  # the single read at the start
        calls = {"n": 0}

        def write_between(conn, cur, st, params, ctx, many):  # noqa: ANN001
            if "GROUP BY" not in st:
                return
            calls["n"] += 1
            if calls["n"] in (2, 40, 90):
                con = sqlite3.connect(path, timeout=5)
                try:
                    # new mentions of keywords in a range already read, one not read yet, and one never seen
                    for k in (1, 61, 400):
                        con.execute(
                            "INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on) "
                            "VALUES (?, ?, 9, ?) ON CONFLICT DO NOTHING",
                            (k, 1000 + calls["n"], TODAY.isoformat()),
                        )
                    con.commit()
                finally:
                    con.close()

        event.listen(engine, "before_cursor_execute", write_between)
        got = _chunked(s, lo, hi, _always, range_ids=10)
        assert calls["n"] > 90, "the test must reach its third write"
        event.remove(engine, "before_cursor_execute", write_between)
        after = _reference(s, lo, hi, _always)
    assert got == want, "a row inserted while the read ran changed its answer"
    assert after != want, "the writes did not land: the comparison above proved nothing"


def _write_after_statement(engine, path, n: int, action):
    """Run ``action(connection)`` on a second connection just before the n-th GROUP BY statement of a read."""
    calls = {"n": 0}

    def hook(conn, cur, st, params, ctx, many):  # noqa: ANN001
        if "GROUP BY" not in st:
            return
        calls["n"] += 1
        if calls["n"] == n:
            con = sqlite3.connect(path, timeout=5)
            try:
                action(con)
                con.commit()
            finally:
                con.close()

    event.listen(engine, "before_cursor_execute", hook)
    return hook, calls


def test_a_freed_row_id_that_is_re_used_below_the_bound_is_counted(corpus):
    """STATED LIMIT (a): SQLite hands the highest rowid out again after it is deleted, so an insert made after
    such a delete lands AT the bound and IS counted, which a single snapshot would not have done."""
    engine, Sess, path = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    con = sqlite3.connect(path)
    con.execute(  # the highest id, outside the window, so deleting it changes nothing the read counts
        "INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on) VALUES (1, 5000, 1, '1999-01-01')"
    )
    con.commit()
    top = con.execute("SELECT max(id) FROM keyword_mentions").fetchone()[0]
    con.close()

    def free_and_reuse(con):
        con.execute("DELETE FROM keyword_mentions WHERE id = ?", (top,))
        con.execute(
            "INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on) VALUES (61, 5001, 9, ?)",
            (TODAY.isoformat(),),
        )
        assert con.execute("SELECT id FROM keyword_mentions WHERE article_id = 5001").fetchone()[0] == top

    with Sess() as s:
        want = _reference(s, lo, hi, _always)
        hook, calls = _write_after_statement(engine, path, 2, free_and_reuse)
        got = _chunked(s, lo, hi, _always, range_ids=10)
        event.remove(engine, "before_cursor_execute", hook)
    assert calls["n"] > 2
    assert got[0][61] == want[0].get(61, 0) + 9, "the re-used id was not counted: the stated limit no longer holds"


def test_an_article_reindexed_without_the_top_ids_can_be_missing_from_the_read_and_is_never_over_it(corpus):
    """STATED LIMIT (b), for an article that does NOT hold the table's top ids: a re-index deletes its mentions and
    inserts new ones with ids above the bound. A statement that runs after that commit finds neither, so the
    article's later keywords come out short of the snapshot (here never over it): one snapshot would have counted
    the old rows, two reads a moment apart the new. An article that DOES hold the top ids gets them back, and
    the next test shows what that costs."""
    engine, Sess, path = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    con = sqlite3.connect(path)
    rows = con.execute(
        "SELECT keyword_id, article_id, count, observed_on, country FROM keyword_mentions WHERE article_id = "
        "(SELECT article_id FROM keyword_mentions WHERE keyword_id >= 11 GROUP BY article_id "
        "ORDER BY count(*) DESC LIMIT 1)"
    ).fetchall()
    con.close()
    article = rows[0][1]
    later = {k: c for k, _a, c, _d, _c in rows if k >= 11}  # keywords read after range 1 (ids 1..10)
    assert later, "the fixture has no article with a keyword outside the first range"

    def reindex(con):
        con.execute("DELETE FROM keyword_mentions WHERE article_id = ?", (article,))
        con.executemany(
            "INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on, country) VALUES (?, ?, ?, ?, ?)",
            rows,
        )

    with Sess() as s:
        want = _reference(s, lo, hi, _always)
        hook, calls = _write_after_statement(engine, path, 2, reindex)
        got = _chunked(s, lo, hi, _always, range_ids=10)
        event.remove(engine, "before_cursor_execute", hook)
    assert calls["n"] > 2
    for k, v in want[0].items():
        assert got[0].get(k, 0) <= v, f"keyword {k} came out OVER the snapshot: double counted"
    assert any(got[0].get(k, 0) < want[0][k] for k in later), "the stated limit is not reproduced: update the text"


def test_a_reindexed_article_that_holds_the_top_ids_can_be_counted_under_both_its_keywords(corpus):
    """The deep delta read's counterexample to "never double counted by a re-index": the re-indexed article holds
    the table's top mention id, so the delete frees it and the re-insert re-uses it (stated limit (a)), which puts
    the new row UNDER the bound; its keyword moved from a range already read to one not yet read, so the row is
    counted under both keys and the total passes what the table ever held. Pinned so the text that says
    it cannot go back to an absolute."""
    engine, Sess, path = corpus
    con = sqlite3.connect(path)
    kmin, kmax = con.execute("SELECT min(keyword_id), max(keyword_id) FROM keyword_mentions").fetchone()
    con.execute(
        "INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on) VALUES (?, 5000, 7, ?)",
        (kmin, TODAY.isoformat()),
    )
    con.commit()
    top = con.execute("SELECT max(id) FROM keyword_mentions").fetchone()[0]
    con.close()
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    days = (hi - lo).days
    seen: dict = {}

    def reindex(con):
        con.execute("DELETE FROM keyword_mentions WHERE article_id = 5000")
        con.execute(
            "INSERT INTO keyword_mentions (keyword_id, article_id, count, observed_on) VALUES (?, 5000, 7, ?)",
            (kmax, TODAY.isoformat()),
        )
        seen["id"] = con.execute("SELECT id FROM keyword_mentions WHERE article_id = 5000").fetchone()[0]

    with Sess() as s:
        before = _reference(s, lo, hi, _always)[0]
        # after range 1 (the first range's ``days`` statements; the three probes are not GROUP BY statements)
        hook, calls = _write_after_statement(engine, path, days + 1, reindex)
        got = _chunked(s, lo, hi, _always, range_ids=10)[0]
        event.remove(engine, "before_cursor_execute", hook)
    assert seen["id"] == top, "the re-insert did not re-use the freed top id: the scenario is not the one the text names"
    assert got[kmin] == before[kmin] and got[kmax] == before.get(kmax, 0) + 7, (got[kmin], got[kmax], before)
    assert sum(got.values()) == sum(before.values()) + 7, "no longer counted under both keys: update the text"


@pytest.mark.parametrize("move", ["low-to-high", "high-to-low"])
def test_a_row_moved_to_another_key_during_the_read_is_counted_twice_or_missed_as_documented(corpus, move):
    """A keyword fold rewrites ``keyword_id`` in place (``keyword_fold.py``): a row moved from a range already read
    to one not yet read is counted under BOTH keys (a state that never existed: deep read S3), and one moved the other way
    under neither. The docstring says so; this pins it, so a change to either has to change the other."""
    engine, Sess, path = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    con = sqlite3.connect(path)
    try:
        kmin, kmax = con.execute("SELECT min(keyword_id), max(keyword_id) FROM keyword_mentions").fetchone()
        src, dst = (kmin, kmax) if move == "low-to-high" else (kmax, kmin)
        row_id, cnt = con.execute(
            "SELECT id, count FROM keyword_mentions WHERE keyword_id = ? AND observed_on >= ? AND observed_on < ? LIMIT 1",
            (src, lo.isoformat(), hi.isoformat()),
        ).fetchone()
    finally:
        con.close()
    days = (hi - lo).days
    # the first statement of the SECOND range: the first range is read, the last is not
    _hook, calls = _write_after_statement(
        engine, path, days + 1, lambda c: c.execute("UPDATE keyword_mentions SET keyword_id = ? WHERE id = ?", (dst, row_id))
    )
    with Sess() as s:
        total_before = sum(v for _k, v in _reference(s, lo, hi, _always)[0].items())
        calls["n"] = 0
        got, _groups = _chunked(s, lo, hi, _always, range_ids=10)
    assert calls["n"] > days + 1, "the move never ran: the comparison below proved nothing"
    seen = sum(got.values())
    if move == "low-to-high":
        assert seen == total_before + cnt, "the row was not counted under both keys: update the text"
    else:
        assert seen == total_before - cnt, "the row was not missed: update the text"


def test_the_seeks_leave_nothing_behind_in_a_session_whose_executes_are_wrapped(corpus):
    """The briefing's WAL guard keeps a wrapper for every result ``session.execute`` returns, with its statement
    and its exhausted cursor result, until the next producer starts. MEASURED on this fixture's 1,550 seeks:
    15 KB each with a statement built per seek, 7.4 KB with one, and nothing once the seeks go through the
    session's connection. So the number kept is the probes', not the seeks'."""
    from src.briefing.registry import _wal_guard

    _engine, Sess, _ = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    with Sess() as s:
        want = _reference(s, lo, hi, _always)
        with _wal_guard(s):
            got = _chunked(s, lo, hi, _always, range_ids=1)
            kept = len(s._wal_guard_pending)
        assert got == want
    assert kept <= 3, f"{kept} wrapped results were kept: the seeks went through the guard's wrapper"


# --------------------------------------------------------------------------- #
#  the pool slot goes back between pieces (deep read B1), except on a snapshot session
# --------------------------------------------------------------------------- #
def _checkouts_and_statements(engine):
    """Listen on ``engine``: one entry per pool checkout, the number of statements it ran before it went back."""
    per_checkout: list[int] = []

    def out(*_a):  # noqa: ANN002
        per_checkout.append(0)

    def stmt(conn, cur, st, params, ctx, many):  # noqa: ANN001
        if per_checkout:
            per_checkout[-1] += 1

    event.listen(engine, "checkout", out)
    event.listen(engine, "before_cursor_execute", stmt)
    return per_checkout


def _key_span(session) -> int:
    lo, hi = session.execute(select(func.min(KM.keyword_id), func.max(KM.keyword_id))).one()
    return int(hi) - int(lo) + 1


def test_no_checkout_lasts_longer_than_one_key_range_so_no_slot_is_held_for_the_whole_read(corpus):
    """MEASURED defect (deep read of 3e66fb9b): the ORM session autobegan on the first statement and kept its
    pooled connection until the caller closed it, so the pool watch saw ONE checkout for the whole call (52.6 s
    of 52.6 s on a 1.3 M-mention table). Each key range is now its own checkout: the number of statements a
    checkout runs is bounded by one range's days (plus the three probes of the first), never by the window."""
    engine, Sess, _ = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    per_checkout = _checkouts_and_statements(engine)
    with Sess() as s:
        span = _key_span(s)
        per_checkout.clear()
        got = _chunked(s, lo, hi, _always, range_ids=7)
        assert got == _reference(s, lo, hi, _always)
    ranges = -(-span // 7)
    days = (hi - lo).days
    assert ranges > 10 and days > 10
    assert len(per_checkout) >= ranges, f"{len(per_checkout)} checkouts for {ranges} ranges: a slot was held across ranges"
    # the first checkout also ran the three probes; the call's own reference read adds one more checkout, one statement
    assert max(per_checkout) <= days + 3, per_checkout
    # and not one checkout per statement either: the slot goes back once per RANGE (a release after every statement
    # passed every other assertion here and turned a range's seeks into that many check-outs)
    assert len(per_checkout) <= ranges + 2, f"{len(per_checkout)} checkouts for {ranges} ranges: released more than once per range"


def test_the_real_pool_watch_lists_nothing_for_this_thread_while_keep_runs(corpus, monkeypatch):
    """``keep`` runs between ranges. With the release the pool watch (the storage guard's candidate list) shows no
    checkout of this thread at those moments; without it the same read shows one for the whole call."""
    import threading

    from src.database import pool_watch

    engine, Sess, _ = corpus
    assert pool_watch.register(engine, label="windowed-test")  # not the app engine's label: a leak elsewhere must not count
    me = threading.current_thread().name
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)

    def mine():
        return [r for r in pool_watch.checked_out() if r["thread"] == me and r["pool"] == "windowed-test"]

    held: list[int] = []
    with Sess() as s:
        _chunked(s, lo, hi, lambda k, v: held.append(len(mine())) or True, range_ids=11)
    assert len(held) > 20 and set(held) == {0}, "a slot was held while keep ran"

    monkeypatch.setattr(dq, "release_between_pieces", lambda _s: False)
    held_old: list[int] = []
    with Sess() as s:
        _chunked(s, lo, hi, lambda k, v: held_old.append(len(mine())) or True, range_ids=11)
    assert set(held_old) == {1}, "the contrast did not hold a slot: the assertion above proved nothing"


@pytest.mark.parametrize("how", ["text", "connection"])
def test_a_write_the_sessions_flags_cannot_see_is_not_rolled_back_by_the_release(corpus, how):
    """The deep delta read's S1: ``release_idle_connection`` read only the session's own flags, and DML run through
    ``session.execute(text(...))`` or on ``session.connection()`` sets none of them, so the read's release
    rolled the write back without a sound. The helper now compares the driver's changed-row count with the one
    taken when the transaction began (tests/test_release_declines_unseen_writes.py pins that on the primitive, for
    every caller); ``release_between_pieces`` keeps asking the driver's ``in_transaction`` as well, which also
    declines the explicit BEGIN of a snapshot session."""
    _engine, Sess, _ = corpus
    with Sess() as s:
        if how == "text":
            s.execute(text("UPDATE keywords SET term = 'WRITTEN' WHERE id = 1"))
        else:
            s.connection().execute(text("UPDATE keywords SET term = 'WRITTEN' WHERE id = 1"))
        assert dq.release_between_pieces(s) is False, "released a session holding a write it could not see"
        q.corpus_keywords(s, article_ids=list(range(1, ARTICLES + 1)), limit=5)
        s.commit()
    with Sess() as s:
        assert s.execute(text("SELECT term FROM keywords WHERE id = 1")).scalar_one() == "WRITTEN", "the write was lost"


def test_a_session_that_has_only_read_is_still_released_between_pieces(corpus):
    """The other half of the driver check: after SELECTs alone the driver reports no transaction (pysqlite's legacy
    mode begins none), so the read's release still hands the connection back."""
    _engine, Sess, _ = corpus
    with Sess() as s:
        s.execute(text("SELECT count(*) FROM keyword_mentions")).scalar_one()
        assert dq.release_between_pieces(s) is True


def test_a_snapshot_session_keeps_its_one_transaction_across_every_range(corpus):
    """``read_snapshot_session`` holds ONE explicit BEGIN on purpose (the bundle reads one consistent snapshot):
    releasing there would give the next piece, and everything the caller reads after, a newer snapshot."""
    from src.database.read_snapshot import (
        dispose_read_engines,
        holds_snapshot,
        read_snapshot_session,
    )

    engine, Sess, path = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    try:
        with Sess() as plain:
            want = _reference(plain, lo, hi, _always)
            assert not holds_snapshot(plain.get_bind())
        with read_snapshot_session(f"sqlite:///{path}") as rs:
            assert holds_snapshot(rs.get_bind())
            per_checkout = _checkouts_and_statements(rs.get_bind())
            _hook, calls = _write_after_statement(
                rs.get_bind(), path, 2, lambda con: con.execute("DELETE FROM keyword_mentions WHERE id % 2 = 0")
            )
            got = _chunked(rs, lo, hi, _always, range_ids=7)
            assert rs.in_transaction(), "the snapshot's transaction was ended"
        assert calls["n"] > 2, "the delete never ran: the comparison below proved nothing"
        assert got == want, "a commit made while the read ran was seen: the snapshot was released between pieces"
        assert per_checkout and len(per_checkout) == 1, per_checkout
    finally:
        dispose_read_engines()


def test_a_session_that_has_written_is_not_released_so_its_pending_work_survives(corpus):
    """``release_idle_connection`` declines a session with flushed-but-uncommitted work: the read goes on, the
    work is not rolled back (slower, never wrong)."""
    _engine, Sess, _ = corpus
    lo, hi = TODAY - timedelta(days=DAYS), TODAY + timedelta(days=1)
    with Sess() as s:
        s.add(Keyword(id=9001, term="pending", normalized_term="pending", language="en"))
        s.flush()
        assert dq.release_between_pieces(s) is False
        _chunked(s, lo, hi, _always, range_ids=11)
        assert s.query(Keyword).filter(Keyword.id == 9001).count() == 1, "the pending row was rolled back"
        s.rollback()


# --------------------------------------------------------------------------- #
#  a datetime bound is not walked by days (deep read S2)
# --------------------------------------------------------------------------- #
def test_only_a_date_is_walkable_by_days():
    assert dq._as_date(date(2026, 10, 1)) == date(2026, 10, 1)
    assert dq._as_date(datetime(2026, 10, 1, 0, 0)) is None  # a datetime is a date for isinstance, so say so
    assert dq._as_date("2026-10-01") is None and dq._as_date(None) is None


@pytest.mark.parametrize(
    "lo,hi",
    [
        (datetime(2026, 9, 28), datetime(2026, 10, 3)),
        (datetime(2026, 9, 28, 12, 30), datetime(2026, 10, 3, 12, 30)),
        (TODAY - timedelta(days=8), datetime(2026, 10, 5, 12)),
        (datetime(2026, 9, 28, 12), TODAY),
    ],
)
def test_a_datetime_bound_gives_the_single_statements_answer(corpus, lo, hi):
    """SQLAlchemy binds a datetime against a Date column as text, so the single statement excludes the day of a
    datetime lower bound and includes the day of a datetime upper bound; walking whole days from the date read
    other rows (155 groups against 179 on the real schema). The window is now left to the single statement."""
    _engine, Sess, _ = corpus
    with Sess() as s:
        want = _reference(s, lo, hi, _always)
        assert want[1] > 0
        assert _chunked(s, lo, hi, _always, range_ids=7) == want


# --------------------------------------------------------------------------- #
#  trending() reads through it, and says the same thing as before
# --------------------------------------------------------------------------- #
def _trending(Sess, **kw):
    with Sess() as s:
        return q.trending(s, min_recent=1, limit=200, **kw)


def _single(session, *, key, day, rowid, value, lo, hi, keep, where=(), range_ids=None, deadline=None):  # noqa: ARG001
    stmt = select(key, value).where(day >= lo, day < hi, *where).group_by(key)
    return dq.grouped_counts(session, stmt, keep)


@pytest.mark.parametrize("country", [None, "fr"])
def test_trending_is_unchanged_by_reading_in_short_statements(corpus, monkeypatch, country):
    _engine, Sess, _ = corpus
    for window, baseline in ((1, 7), (3, 8), (7, 5)):
        got = _trending(Sess, window_days=window, baseline_days=baseline, end=TODAY + timedelta(days=1), country=country)
        with monkeypatch.context() as m:
            m.setattr(dq, "windowed_group_counts", _single)
            want = _trending(Sess, window_days=window, baseline_days=baseline, end=TODAY + timedelta(days=1), country=country)
        assert got == want and got["terms"], (window, baseline, country)


def test_trending_goes_through_the_chunked_helper_and_never_the_open_cursor(corpus, monkeypatch):
    _engine, Sess, _ = corpus
    calls = {"chunked": 0, "single": 0}
    real = dq.windowed_group_counts
    monkeypatch.setattr(dq, "windowed_group_counts", lambda *a, **k: calls.__setitem__("chunked", calls["chunked"] + 1) or real(*a, **k))
    real_single = dq.grouped_counts
    monkeypatch.setattr(dq, "grouped_counts", lambda *a, **k: calls.__setitem__("single", calls["single"] + 1) or real_single(*a, **k))
    _trending(Sess, window_days=3, baseline_days=8, end=TODAY + timedelta(days=1))
    assert calls["chunked"] == 2 and calls["single"] == 0, calls  # the recent window, then the baseline


# --------------------------------------------------------------------------- #
#  corpus_keywords: a slice of articles at a time, the same top list
# --------------------------------------------------------------------------- #
def _corpus_keywords_reference(session, ids, kind, limit):
    """The single statement it replaces, with the tie-break the new one states (keyword id)."""
    qy = (
        session.query(
            Keyword,
            func.sum(KM.count).label("m"),
            func.count(func.distinct(KM.article_id)).label("arts"),
        )
        .join(KM, KM.keyword_id == Keyword.id)
        .filter(KM.article_id.in_(ids))
    )
    qy = q._apply_kind(qy, kind)
    rows = (
        qy.group_by(Keyword.id)
        .order_by(func.count(func.distinct(KM.article_id)).desc(), func.sum(KM.count).desc(), Keyword.id)
        .limit(limit)
        .all()
    )
    return [(k.id, int(m), int(a)) for k, m, a in rows]


def _slices(session, ids, kind, take):
    return [(k.id, m, a) for k, m, a in q._corpus_keyword_rows(session, ids, kind, take)]


@pytest.mark.parametrize("kind", [None, "term", "entity", "non_term", "person"])
@pytest.mark.parametrize("slice_size", [1, 3, 7, 100])
def test_corpus_keywords_by_slices_is_the_single_statements_top_list(corpus, monkeypatch, slice_size, kind):
    _engine, Sess, _ = corpus
    monkeypatch.setattr(q, "CORPUS_KEYWORD_SLICE", slice_size)
    rng = random.Random(slice_size)
    with Sess() as s:
        for n in (1, 5, 40, ARTICLES):
            ids = rng.sample(range(1, ARTICLES + 1), n)
            for take in (3, 12, 400):
                got = _slices(s, ids, kind, take)
                assert got == _corpus_keywords_reference(s, ids, kind, take), (n, take, kind)
        # the filter filters: each kind's rows differ from the unfiltered list and carry only that kind
        every = [k for k, _m, _a in _slices(s, list(range(1, ARTICLES + 1)), None, 400)]
        kept = [k for k, _m, _a in _slices(s, list(range(1, ARTICLES + 1)), kind, 400)]
        if kind is not None:
            assert kept and len(kept) < len(every), (kind, len(kept), len(every))


def test_a_repeated_article_id_counts_once_as_in_does(corpus, monkeypatch):
    _engine, Sess, _ = corpus
    monkeypatch.setattr(q, "CORPUS_KEYWORD_SLICE", 2)
    ids = [1, 2, 3, 4, 5]
    with Sess() as s:
        assert _slices(s, ids + ids + [1, 1], None, 50) == _corpus_keywords_reference(s, ids, None, 50)


def test_the_public_function_still_answers_and_keeps_its_shape(corpus, monkeypatch):
    _engine, Sess, _ = corpus
    monkeypatch.setattr(q, "CORPUS_KEYWORD_SLICE", 4)
    with Sess() as s:
        out = q.corpus_keywords(s, article_ids=list(range(1, 31)), limit=5)
    assert out["n_articles"] == 30 and out["count"] == len(out["terms"]) == 5
    assert all({"term", "normalized", "mentions", "articles"} <= set(t) for t in out["terms"])
    arts = [t["articles"] for t in out["terms"]]
    assert arts == sorted(arts, reverse=True)
    assert q.corpus_keywords(s, article_ids=[], limit=5) == {"count": 0, "n_articles": 0, "terms": []}


def test_a_checkpoint_passes_before_every_slice_after_the_first(corpus, monkeypatch):
    """Between two slices nothing of the first is open: a write that lands there is not in the way of a
    checkpoint. With one big statement (the old shape) there is no 'between' at all."""
    engine, Sess, path = corpus
    monkeypatch.setattr(q, "CORPUS_KEYWORD_SLICE", 10)
    busy: list[int] = []
    seen = {"n": 0}

    def at_start(conn, cur, st, params, ctx, many):  # noqa: ANN001
        if "GROUP BY" in st and "keyword_mentions" in st:
            seen["n"] += 1
            if seen["n"] > 1:
                busy.append(_checkpoint_passes(path)[0])

    event.listen(engine, "before_cursor_execute", at_start)
    with Sess() as s:
        _slices(s, list(range(1, ARTICLES + 1)), None, 20)
    assert seen["n"] == ARTICLES // 10, "a slice of ten articles is one statement"
    assert busy and set(busy) == {0}, "a reader held the log between two slices"


def test_no_statement_names_more_articles_than_a_slice(corpus, monkeypatch):
    engine, Sess, _ = corpus
    monkeypatch.setattr(q, "CORPUS_KEYWORD_SLICE", 7)
    widest = {"n": 0}

    def count_params(conn, cur, st, params, ctx, many):  # noqa: ANN001
        if "GROUP BY" in st and "keyword_mentions" in st:
            widest["n"] = max(widest["n"], len(params))

    event.listen(engine, "before_cursor_execute", count_params)
    with Sess() as s:
        _slices(s, list(range(1, ARTICLES + 1)), None, 20)
    assert widest["n"] == 7, widest  # kind=None binds the slice's ids and nothing else: a slice one wider shows here


def test_each_slice_is_its_own_checkout_so_no_slot_is_held_across_slices(corpus, monkeypatch):
    """deep read B1 for ``corpus_keywords``: the ORM session held one connection across every slice."""
    engine, Sess, _ = corpus
    monkeypatch.setattr(q, "CORPUS_KEYWORD_SLICE", 10)
    per_checkout = _checkouts_and_statements(engine)
    with Sess() as s:
        _slices(s, list(range(1, ARTICLES + 1)), None, 20)
    assert len(per_checkout) >= ARTICLES // 10, per_checkout
    assert max(per_checkout) <= 2, per_checkout  # one slice (the last also loads the ORM rows it returns)


def test_under_the_apps_own_engine_settings_a_checkpoint_passes_between_statements(tmp_path, monkeypatch):
    """Everything above uses a plain engine; the claim is about the app's: its pragmas, its pool, its listeners.
    (``release_idle_connection`` is written as if a session pinned a snapshot between statements. Pysqlite's
    legacy mode starts no transaction on a SELECT, so only a RUNNING statement pins: this is the measurement.)"""
    from src.database import session as app_session

    app_session.init_db()
    engine = app_session.engine
    path = engine.url.database
    assert path and str(path) != ":memory:"
    Sess = sessionmaker(bind=engine, future=True)
    own: dict[str, list[int]] = {"sources": [], "keywords": [], "articles": []}
    try:
        _app_engine_body(engine, Sess, path, monkeypatch, own)
    finally:
        # the engine is the process's own and shared with every test that runs after this one, so only what this
        # test made is removed (the neighbours' fixtures do the same), by the ids the inserts were given
        with Sess() as s:
            for aid in own["articles"]:
                s.execute(text("DELETE FROM keyword_mentions WHERE article_id = :a"), {"a": aid})
                s.execute(text("DELETE FROM articles WHERE id = :a"), {"a": aid})
            for kid in own["keywords"]:
                s.execute(text("DELETE FROM keywords WHERE id = :k"), {"k": kid})
            for sid in own["sources"]:
                s.execute(text("DELETE FROM sources WHERE id = :s"), {"s": sid})
            s.commit()


def _app_engine_body(engine, Sess, path, monkeypatch, own):
    with Sess() as s:
        src = Source(name="S-windowed-group-counts", domain="windowed.test")
        s.add(src)
        s.flush()
        own["sources"].append(src.id)
        words = [Keyword(term=f"wgc{k}", normalized_term=f"wgc{k}", language="en") for k in range(1, 40)]
        s.add_all(words)
        s.flush()
        kids = [w.id for w in words]
        own["keywords"].extend(kids)
        articles = [
            Article(url=f"https://windowed.test/{aid}", canonical_url=f"https://windowed.test/{aid}", source_id=src.id,
                    title="t", content="c", hash=f"wgc-h{aid}", language="en", created_at=datetime.now(UTC))
            for aid in range(1, 31)
        ]
        s.add_all(articles)
        s.flush()
        own["articles"].extend(a.id for a in articles)
        for aid, art in enumerate(articles, start=1):
            for k in range(aid, aid + 8):
                s.add(KeywordMention(keyword_id=kids[k - 1], article_id=art.id, count=2,
                                     observed_on=TODAY - timedelta(days=aid % 5)))
        s.commit()
    busy: list[int] = []
    with Sess() as s:
        got = _chunked(s, TODAY - timedelta(days=6), TODAY + timedelta(days=1),
                       lambda k, v: busy.append(_checkpoint_passes(path)[0]) or True, range_ids=6)
        assert got == _reference(s, TODAY - timedelta(days=6), TODAY + timedelta(days=1), _always)
    assert len(busy) >= 20 and set(busy) == {0}, "the app's own engine held the log between statements"
    # the contrast on the same engine: the single statement, with its cursor open, DOES keep the checkpoint out
    monkeypatch.setattr(dq, "GROUPED_CHUNK", 2)
    old: list[int] = []
    with Sess() as s:
        _reference(s, TODAY - timedelta(days=6), TODAY + timedelta(days=1), lambda k, v: old.append(_checkpoint_passes(path)[0]) or True)
    assert 1 in old, "the contrast did not pin on the app's engine: the assertion above proved nothing"
