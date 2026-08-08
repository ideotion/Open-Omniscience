"""The two stages that actually dominate a large import.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field logs 2026-07-31, report #15 (2.96 h, 700,503 duplicate articles, ZERO new):

    prepare_staged   5773 s   54%
    merge            2857 s   27%   (link graph 2483 s -- 87% of the merge)
    verify           1521 s   14%
    reindex             0.169 s

The re-index -- the stage everyone suspected, including me -- was a sixth of a
second. These pin the two that were not looked at.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.database.maintenance import HOT_INDEXES

_DDL = """
CREATE TABLE article_links (
  id INTEGER PRIMARY KEY, article_id INTEGER NOT NULL, url VARCHAR(1000) NOT NULL,
  normalized_url VARCHAR(1000) NOT NULL, position INTEGER, link_type VARCHAR(20));
CREATE INDEX idx_article_link_article_id ON article_links(article_id);
CREATE INDEX idx_article_link_url ON article_links(url);
"""

# The merge's own dedup predicate (src/backup/merge.py _merge_external_link_graph).
_DEDUP_Q = (
    "SELECT COUNT(*) FROM inc.article_links i"
    " JOIN temp.map_articles ma ON ma.old = i.article_id"
    " WHERE EXISTS (SELECT 1 FROM article_links t WHERE t.article_id = ma.new"
    " AND t.url = i.url AND COALESCE(t.position,-1) = COALESCE(i.position,-1))"
)


def _corpus(tmp_path, name, n_articles=40, links=5):
    p = tmp_path / name
    db = sqlite3.connect(p)
    db.executescript(_DDL)
    rows = [
        (a + 1, f"https://example.com/{a}/{q}", f"https://example.com/{a}/{q}", q, "external")
        for a in range(n_articles)
        for q in range(links)
    ]
    db.executemany(
        "INSERT INTO article_links(article_id,url,normalized_url,position,link_type)"
        " VALUES(?,?,?,?,?)",
        rows,
    )
    db.commit()
    db.close()
    return p, len(rows)


def _wire(tmp_path, n_articles=40):
    live, n = _corpus(tmp_path, "live.db", n_articles)
    inc, _ = _corpus(tmp_path, "inc.db", n_articles)
    con = sqlite3.connect(live)
    con.execute(f"ATTACH DATABASE '{inc}' AS inc")
    con.execute("CREATE TEMP TABLE map_articles(old INTEGER PRIMARY KEY, new INTEGER)")
    con.executemany(
        "INSERT INTO map_articles VALUES(?,?)", [(i + 1, i + 1) for i in range(n_articles)]
    )
    return con, n


def _plan(con, sql):
    return " | ".join(r[-1] for r in con.execute("EXPLAIN QUERY PLAN " + sql))


def test_the_dedup_index_is_registered_as_a_hot_index_and_on_the_model():
    assert "idx_article_link_dedup" in HOT_INDEXES
    ddl = HOT_INDEXES["idx_article_link_dedup"]
    assert "article_links (article_id, url, position)" in ddl
    assert "IF NOT EXISTS" in ddl, "the boot self-heal must be idempotent"

    from src.database.models import ArticleLink

    names = {ix.name: [c.name for c in ix.columns] for ix in ArticleLink.__table__.indexes}
    assert names.get("idx_article_link_dedup") == ["article_id", "url", "position"], (
        "a fresh DB must get the index from the model, not only from the migration"
    )


def test_without_the_index_the_dedup_reads_rows(tmp_path):
    """The BEFORE state, pinned so the improvement is a measured delta rather than
    a claim: a seek on article_id, then a row read to compare url and position --
    and those are two String(1000) columns, decrypted per read under SQLCipher."""
    con, _ = _wire(tmp_path)
    try:
        plan = _plan(con, _DEDUP_Q)
        assert "idx_article_link_article_id" in plan
        assert "COVERING" not in plan, f"unexpectedly already covering: {plan}"
    finally:
        con.close()


def test_with_the_index_the_dedup_is_answered_from_the_index_alone(tmp_path):
    con, n = _wire(tmp_path)
    try:
        before = con.execute(_DEDUP_Q).fetchone()[0]
        con.execute(HOT_INDEXES["idx_article_link_dedup"])
        con.commit()
        plan = _plan(con, _DEDUP_Q)
        assert "COVERING INDEX idx_article_link_dedup" in plan, plan
        # The seek now uses BOTH columns, so candidates are narrowed in the index.
        assert "article_id=? AND url=?" in plan, plan
        # ...and the ANSWER is unchanged. An index that alters the result is a bug,
        # not an optimisation.
        assert con.execute(_DEDUP_Q).fetchone()[0] == before == n
    finally:
        con.close()


def test_the_index_does_not_change_the_answer_when_rows_genuinely_differ(tmp_path):
    """Negative space: the dedup must still MISS when position or url differ, or a
    covering index would turn distinct links into false duplicates and drop them."""
    con, n = _wire(tmp_path)
    try:
        con.execute(HOT_INDEXES["idx_article_link_dedup"])
        # Same article + url, different position => NOT a duplicate.
        con.execute(
            "INSERT INTO inc.article_links(article_id,url,normalized_url,position,link_type)"
            " VALUES(1,'https://example.com/0/0','https://example.com/0/0',999,'external')"
        )
        # Same article + position, different url => NOT a duplicate.
        con.execute(
            "INSERT INTO inc.article_links(article_id,url,normalized_url,position,link_type)"
            " VALUES(1,'https://example.com/brand-new','https://example.com/brand-new',0,'x')"
        )
        con.commit()
        assert con.execute(_DEDUP_Q).fetchone()[0] == n, "a differing row was counted as a dup"
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  prepare_staged: 54% of a large import, reported as ONE opaque number
# --------------------------------------------------------------------------- #
def test_prepare_staged_records_its_two_expensive_halves_separately():
    """quick_check (reads every page of a multi-GB file) and the alembic upgrade
    chain (real migrations over the whole corpus) are unrelated costs summed into
    one figure. Optimising either without knowing which is guessing."""
    import inspect

    from src.backup import merge as m

    sig = inspect.signature(m.prepare_staged_corpus)
    assert "timings" in sig.parameters
    assert sig.parameters["timings"].default is None, "must stay optional for every caller"

    src = inspect.getsource(m.prepare_staged_corpus)
    assert "prepare_staged:validate" in src
    assert "prepare_staged:upgrade" in src
    # RECORD, not STAGE: .stage() also fires stage_progress_cb, whose names are
    # the user-visible phases counted against restore_stage_plan(). A sub-stage
    # pinged as a phase makes _phase_of report its honest-unknown 0.
    #
    # Read from _sub_timer, which is where the mechanism lives now that
    # verify_copy needs it too. This assertion previously read
    # prepare_staged_corpus's own source and broke on the hoist -- the claim was
    # still true, it was just pointed at the old address.
    assert 'getattr(timings, "record", None)' in inspect.getsource(m._sub_timer)
    assert "_stage(name)" not in src, "a sub-timing must never emit a phase ping"

    caller = inspect.getsource(m.run_restore)
    assert "timings=timings" in caller, "run_restore must actually pass its recorder"


def test_prepare_staged_still_works_with_no_recorder():
    """The default path (no timings) must be byte-identical in behaviour -- every
    existing caller and test relies on it.

    BEHAVIOURAL, not a word-grep. This asserted ``"if _record is None:" in src``
    and broke when the closure was hoisted into ``_sub_timer`` -- a true claim
    anchored to an address. Driving the timer proves the same thing and cannot be
    moved out from under itself.
    """
    from src.backup import merge as m

    ran = []
    with m._sub_timer(None)("prepare_staged:validate"):
        ran.append("body")
    assert ran == ["body"], "the sub-context must yield straight through"

    # THE TWIN, and it is what makes the line above mean anything: a context that
    # yields is not evidence of a no-recorder BRANCH -- a timer that recorded
    # nothing for everyone would pass that assertion just as happily. So prove the
    # branch exists by taking the other side of it.
    seen: list[str] = []

    class _Rec:
        def record(self, name, seconds):  # noqa: ANN001
            seen.append(name)

    with m._sub_timer(_Rec())("prepare_staged:validate"):
        pass
    assert seen == ["prepare_staged:validate"], (
        "with a recorder the sub-timing must actually be recorded"
    )


def test_sub_timings_are_recorded_but_never_pinged_as_phases(monkeypatch, tmp_path):
    """THE defect this pair exists for, pinned behaviourally rather than by grep.

    timings.stage() does two things: it records a duration AND fires
    stage_progress_cb, whose names are the user-visible phases counted against
    restore_stage_plan(). Using it for a sub-stage emitted a phase ping for a name
    that is not in the plan, which volume_job._phase_of answers with its
    honest-unknown 0 -- so the UI would flash an unknown phase mid-import.
    (Caught by test_stage_progress_cb_pings_fire_for_every_stage_in_order, which
    asserts the ping list EXACTLY; this is its positive half.)
    """
    from src.backup import merge as m

    recorded: list[str] = []
    staged_names: list[str] = []

    class _Recorder:
        def record(self, name, seconds):
            recorded.append(name)
            assert seconds >= 0, "a recorded duration must be real"

        def stage(self, name):  # pragma: no cover - must never be reached here
            staged_names.append(name)
            raise AssertionError(f"sub-timing {name!r} emitted a user-visible phase ping")

    monkeypatch.setattr(m, "prepare_staged_corpus", m.prepare_staged_corpus)
    monkeypatch.setattr(
        "src.backup.sqlite_backup.validate_sqlite_file", lambda p: 1, raising=False
    )
    monkeypatch.setattr("src.database.migrate.file_revision", lambda p: "abc123", raising=False)
    monkeypatch.setattr("src.database.migrate.known_revisions", lambda: {"abc123"}, raising=False)
    monkeypatch.setattr(
        "src.database.migrate.upgrade_database_file", lambda p: None, raising=False
    )

    class _Staged:
        hash_failures: list = []
        kind = "oo-backup-2"
        signature_state = "verified"
        corpus_path = tmp_path / "corpus.db"

    m.prepare_staged_corpus(_Staged(), timings=_Recorder())

    assert recorded == ["prepare_staged:validate", "prepare_staged:upgrade"]
    assert staged_names == [], "no sub-timing may reach timings.stage()"


def test_a_failing_validate_still_records_the_time_the_operator_waited():
    """A quick_check that reads 90 minutes of a multi-GB file and THEN rejects it
    has still cost 90 minutes. Recording only on success would hide exactly the
    case worth measuring.

    BEHAVIOURAL, not a word-grep: this sliced ``prepare_staged_corpus``'s source
    from ``def _sub(`` and raised ValueError once the closure was hoisted into
    ``_sub_timer``. Driving a failing body proves the ``finally`` does its job,
    which is what the test is named for.
    """
    from src.backup import merge as m

    seen: dict[str, float] = {}

    class _Rec:
        def record(self, name, seconds):  # noqa: ANN001
            seen[name] = seconds

    with pytest.raises(RuntimeError, match="rejected"):
        with m._sub_timer(_Rec())("prepare_staged:validate"):
            raise RuntimeError("the corpus was rejected after 90 minutes")

    assert "prepare_staged:validate" in seen, (
        "time the operator waited before a REJECTION is still time they waited"
    )
    assert seen["prepare_staged:validate"] >= 0.0


# --------------------------------------------------------------------------- #
#  apply: the serial 94% of a re-index, previously ONE number
# --------------------------------------------------------------------------- #
def test_apply_reports_staging_and_commit_separately():
    """Field logs 2026-07-31: apply_s was 758 s of an 806 s re-index -- and, like
    prepare_staged, one opaque figure over two unrelated costs. Staging an article
    (keyword lookups, mention rows, when/where/who, sentiment) is CPU and reads;
    the periodic COMMIT is fsync and WAL through the codec. The fix for one is not
    the fix for the other.

    This split exists because guessing was already tried: a covering index on the
    per-term keyword lookup measured 1.9x on plaintext, which works out to ~0.2%
    of apply -- a real speedup of an irrelevant slice.
    """
    import inspect

    from src.analytics import store as st

    src = inspect.getsource(st.reindex_articles)
    assert "_apply_index_s" in src and "_apply_commit_s" in src
    assert '"apply_index_s"' in src and '"apply_commit_s"' in src

    # The commit timer must wrap the COMMIT only -- not the staging before it, or
    # the two buckets stop meaning different things.
    flush = src[src.index("def _flush("):]
    flush = flush[: flush.index("for art in articles:")]
    assert "session.commit()" in flush
    before, after = flush.split("session.commit()", 1)
    assert "_t_c = time.monotonic()" in before.rsplit("try:", 1)[-1]
    assert "_apply_commit_s += time.monotonic() - _t_c" in after.split("\n")[1]


def test_the_apply_split_is_disclosed_as_not_summing_to_the_whole():
    """apply_index_s + apply_commit_s < apply_s, and the remainder is real
    per-article bookkeeping. Presenting two parts as if they were the whole would
    be the same aggregate-hides-a-residual problem one level down."""
    import inspect

    from src.analytics import store as st

    src = inspect.getsource(st.reindex_articles)
    assert "do not sum to it" in src, "the residual must be stated, not implied"
