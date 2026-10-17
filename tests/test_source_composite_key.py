"""A source is keyed on (domain, feed): the schema rebuild must never lose a child row (row J, S05-10 S2b).

The rebuild of ``sources`` is the one step of this slice that can destroy data: ``feed_fetch_state`` and
three other tables reference ``sources.id`` with ``ON DELETE CASCADE`` and the app runs with
``PRAGMA foreign_keys=ON``, so a naive ``DROP TABLE sources`` deletes their rows. These tests build a LEGACY store
(UNIQUE on domain alone, no feed_key), give it children, rebuild it and compare.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, FeedFetchState, Source
from src.database.source_identity import (
    SourceIdentityRefused,
    composite_key_active,
    ensure_source_composite_key,
    source_identity_state,
    upgrade_sources_to_composite_key,
)


def _legacy_engine(tmp_path):
    """A store as it was before this slice: sources UNIQUE(domain), no feed_key, foreign keys ON."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}", future=True)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi, _rec):  # the app's own pragma
        dbapi.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        rows = conn.exec_driver_sql("SELECT * FROM sources").fetchall()
        assert rows == []
        ddl = conn.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='sources'").scalar_one()
        legacy = "\n".join(
            line for line in ddl.splitlines() if "feed_key" not in line.split("--")[0] or "CONSTRAINT" in line
        )
        legacy = legacy.replace("CONSTRAINT uq_source_domain_feed UNIQUE (domain, feed_key)", "UNIQUE (domain)")
        assert "feed_key" not in legacy and "UNIQUE (domain)" in legacy, legacy
        conn.exec_driver_sql("DROP TABLE sources")
        conn.exec_driver_sql(legacy)
        conn.exec_driver_sql("CREATE UNIQUE INDEX idx_source_domain ON sources (domain)")
    engine.dispose()  # the pooled connection above holds enforcement OFF; the app's connections start ON
    return engine


def _seed(engine):
    with engine.begin() as conn:
        for sid, name, dom, feed in [
            (1, "A", "a.com", "https://a.com/rss/"),
            (2, "B", "b.com", None),
            (3, "C", "c.com", "https://a.com/rss"),  # the same feed under another domain (52 such in the catalogue)
        ]:
            conn.exec_driver_sql(
                "INSERT INTO sources (id, name, domain, rss_url, status) VALUES (?,?,?,?, 'unqualified')",
                (sid, name, dom, feed),
            )
            conn.exec_driver_sql("INSERT INTO feed_fetch_state (source_id, last_status) VALUES (?, 200)", (sid,))
    session = sessionmaker(bind=engine, future=True)()
    try:
        for sid in (1, 2, 3):
            session.add(Article(
                id=sid, title=f"t{sid}", url=f"https://x/{sid}", canonical_url=f"https://x/{sid}",
                source_id=sid, content="body", hash=f"{sid:064d}",
            ))
        session.commit()
    finally:
        session.close()


@pytest.fixture()
def legacy(tmp_path):
    engine = _legacy_engine(tmp_path)
    _seed(engine)
    yield engine
    engine.dispose()


def _counts(engine):
    with engine.connect() as c:
        return {
            "sources": c.exec_driver_sql("SELECT COUNT(*) FROM sources").scalar_one(),
            "feed_fetch_state": c.exec_driver_sql("SELECT COUNT(*) FROM feed_fetch_state").scalar_one(),
            "articles": c.exec_driver_sql("SELECT COUNT(*) FROM articles").scalar_one(),
        }


def test_the_legacy_fixture_is_really_legacy(legacy):
    with legacy.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1  # else the cascade tests prove nothing
        assert source_identity_state(c) == "legacy"
        assert not composite_key_active(c)


def test_the_rebuild_keeps_every_row_and_every_child(legacy):
    before = _counts(legacy)
    assert before == {"sources": 3, "feed_fetch_state": 3, "articles": 3}
    result = ensure_source_composite_key(legacy)
    assert result["state"] == "rebuilt", result
    assert _counts(legacy) == before  # the cascade children are the point
    with legacy.connect() as c:
        assert source_identity_state(c) == "composite"
        assert [r[0] for r in c.exec_driver_sql("SELECT id FROM sources ORDER BY id")] == [1, 2, 3]
        assert [tuple(r) for r in c.exec_driver_sql("SELECT id, feed_key FROM sources ORDER BY id")] == [
            (1, "f:a.com/rss"), (2, ""), (3, "f:a.com/rss"),
        ]
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1  # restored for the app
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert c.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"


def test_after_the_rebuild_one_domain_holds_several_feeds_and_refuses_the_same_feed(legacy):
    ensure_source_composite_key(legacy)
    session = sessionmaker(bind=legacy, future=True)()
    try:
        session.add_all([
            Source(name="A-ar", domain="a.com", rss_url="https://a.com/ar/rss"),
            Source(name="A-nofeed", domain="a.com"),
        ])
        session.commit()
        assert session.query(Source).filter_by(domain="a.com").count() == 3
        session.add(Source(name="dup", domain="a.com", rss_url="http://A.com/rss"))
        with pytest.raises(Exception) as err:
            session.commit()
        assert "UNIQUE" in str(err.value).upper()
    finally:
        session.rollback()
        session.close()


def test_the_ordinary_indexes_survive(legacy):
    ensure_source_composite_key(legacy)
    with legacy.connect() as c:
        have = {r[1] for r in c.exec_driver_sql("PRAGMA index_list(sources)")}
    for ix in Source.__table__.indexes:
        assert ix.name in have, ix.name
    with legacy.connect() as c:
        info = {r[1]: r[2] for r in c.exec_driver_sql("PRAGMA index_list(sources)")}
    assert info["idx_source_domain"] == 0  # no longer unique on its own


def test_it_is_idempotent_and_a_second_run_changes_nothing(legacy):
    assert ensure_source_composite_key(legacy)["state"] == "rebuilt"
    with legacy.connect() as c:
        schema = c.exec_driver_sql("SELECT sql FROM sqlite_master WHERE tbl_name='sources' ORDER BY name").fetchall()
    assert ensure_source_composite_key(legacy) == {"state": "composite"}
    with legacy.connect() as c:
        assert c.exec_driver_sql("SELECT sql FROM sqlite_master WHERE tbl_name='sources' ORDER BY name").fetchall() == schema


def test_it_refuses_when_foreign_keys_cannot_be_turned_off_and_changes_nothing(legacy):
    """Inside a transaction ``PRAGMA foreign_keys=OFF`` is silently ignored, and a DROP TABLE would then delete the
    children. A transaction that is already open is refused (never committed on the caller's behalf); here one is held
    open to prove it."""
    before = _counts(legacy)
    with legacy.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("BEGIN")
        conn.exec_driver_sql("UPDATE sources SET name = name")
        with pytest.raises(SourceIdentityRefused, match="transaction is already open"):
            upgrade_sources_to_composite_key(conn)
        conn.exec_driver_sql("ROLLBACK")
    assert _counts(legacy) == before
    with legacy.connect() as c:
        assert source_identity_state(c) == "legacy"


def test_a_failed_copy_rolls_back_with_the_old_table_intact(legacy, monkeypatch):
    """A table the rebuild cannot carry across leaves the store exactly as it was."""
    before = _counts(legacy)
    import src.database.source_identity as si

    class _Fake:
        def __init__(self, table):
            self._t = table

        def compile(self, dialect=None):
            return "CREATE TABLE sources_composite_new (id INTEGER PRIMARY KEY, domain TEXT)"

    monkeypatch.setattr(si, "CreateTable", _Fake)
    result = ensure_source_composite_key(legacy)
    assert result["state"] == "refused"
    assert _counts(legacy) == before
    with legacy.connect() as c:
        assert source_identity_state(c) == "legacy"
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert c.exec_driver_sql(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='sources_composite_new'"
        ).scalar_one() == 0


def test_a_naive_drop_really_does_cascade_the_children():
    """The hazard the procedure exists for, demonstrated rather than asserted: with enforcement ON, dropping the
    parent deletes the cascade children. If this ever stops being true the rebuild's care is pointless; until
    then it is what the other tests are protecting."""
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("CREATE TABLE p (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE c (pid INTEGER REFERENCES p(id) ON DELETE CASCADE)")
    con.execute("INSERT INTO p VALUES (1)")
    con.execute("INSERT INTO c VALUES (1)")
    con.commit()
    con.execute("DROP TABLE p")
    assert con.execute("SELECT COUNT(*) FROM c").fetchone()[0] == 0


def test_a_fresh_store_is_born_composite():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with engine.connect() as c:
        assert source_identity_state(c) == "composite"
    assert ensure_source_composite_key(engine) == {"state": "composite"}
    session = sessionmaker(bind=engine, future=True)()
    session.add(Source(name="x", domain="x.com", rss_url="https://x.com/rss"))
    session.commit()
    row = session.query(Source).one()
    assert row.feed_key == "f:x.com/rss"
    row.rss_url = "https://x.com/atom/"
    session.commit()
    assert row.feed_key == "f:x.com/atom"  # the key follows the feed on every ORM write
    session.add(FeedFetchState(source_id=row.id, last_status=200))
    session.commit()


def test_the_alembic_revision_takes_the_same_path_on_a_staged_copy(tmp_path):
    """``upgrade_database_file`` is what a restore uses on a copy; it must reach the composite key with every child."""
    from src.database.migrate import upgrade_database_file

    engine = _legacy_engine(tmp_path)
    _seed(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('c3a91f5e7b24')")
    before = _counts(engine)
    engine.dispose()
    assert upgrade_database_file(tmp_path / "legacy.db") == "d5a1c7e9b3f2"
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}", future=True)
    try:
        assert _counts(engine) == before
        with engine.connect() as c:
            assert source_identity_state(c) == "composite"
            assert [tuple(r) for r in c.exec_driver_sql("SELECT id, feed_key FROM sources ORDER BY id")][0] == (1, "f:a.com/rss")
    finally:
        engine.dispose()


def test_the_alembic_revision_keeps_the_children_when_enforcement_is_on(tmp_path):
    """The live app's connections run with foreign keys ON; the revision must still not cascade."""
    from alembic import command

    from src.database.migrate import _alembic_config

    engine = _legacy_engine(tmp_path)
    _seed(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('c3a91f5e7b24')")
    engine.dispose()
    before = _counts(engine)
    with engine.begin() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        cfg = _alembic_config()
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    assert _counts(engine) == before
    with engine.connect() as c:
        assert source_identity_state(c) == "composite"
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_an_older_build_refuses_a_feed_keyed_backup_by_a_named_error(tmp_path, monkeypatch):
    """R145 point 3: no backup-format bump is needed ONLY because a build that does not know this revision refuses
    a store stamped with it, by name, rather than dropping the feed key. A feed-keyed store is stamped at (or past)
    the revision that introduced the key, so the older build's own check stops it before any merge."""
    from src.backup.artifact import StagedArtifact
    from src.backup.merge import MergeError, prepare_staged_corpus
    from src.database import migrate

    engine = create_engine(f"sqlite:///{tmp_path / 'corpus.db'}", future=True)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('d5a1c7e9b3f2')")
    engine.dispose()
    staged = StagedArtifact(
        kind="oo-backup-3", staging_dir=tmp_path, corpus_path=tmp_path / "corpus.db", custody_path=None,
        manifest={}, signature_state="verified", origin_fingerprint="test",
    )
    older_build = [r for r in migrate.known_revisions() if r != "d5a1c7e9b3f2"]
    monkeypatch.setattr(migrate, "known_revisions", lambda: older_build)
    with pytest.raises(MergeError, match="unknown to this build"):
        prepare_staged_corpus(staged)


def test_the_alembic_path_commits_an_earlier_revisions_open_transaction_and_still_keeps_the_children(legacy):
    """A restore of an old backup runs several revisions on one connection; an earlier one's DML leaves a driver
    transaction open. The first cut refused there and broke the cross-version restore (found by the full run, not by
    these tests): the revision commits it, and the children still survive."""
    before = _counts(legacy)
    with legacy.connect() as conn:
        conn.exec_driver_sql("UPDATE sources SET name = name")  # opens the driver's implicit transaction
        assert conn.connection.dbapi_connection.in_transaction
        with pytest.raises(SourceIdentityRefused, match="transaction is already open"):
            upgrade_sources_to_composite_key(conn)  # the boot path never commits for a caller
        assert upgrade_sources_to_composite_key(conn, commit_open_transaction=True)["state"] == "rebuilt"
    assert _counts(legacy) == before


def test_a_refused_rebuild_still_leaves_the_feed_key_column_the_model_reads(tmp_path):
    """Opus read, finding 5: the additive column and backfill run before any refusal, so a store whose rebuild is
    refused keeps answering queries on ``sources`` (one feed per domain) instead of failing on a missing column."""
    engine = create_engine(f"sqlite:///{tmp_path / 'odd.db'}", future=True)
    with engine.begin() as conn:
        # no UNIQUE key on the domain at all: ``unreadable``, which the rebuild refuses
        conn.exec_driver_sql("CREATE TABLE sources (id INTEGER PRIMARY KEY, name VARCHAR(255), domain VARCHAR(255), rss_url VARCHAR(500))")
        conn.exec_driver_sql("INSERT INTO sources VALUES (1, 'A', 'a.com', 'https://a.com/rss')")
    assert ensure_source_composite_key(engine)["state"] == "refused"
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT feed_key FROM sources").scalar_one() == "f:a.com/rss"


def test_the_rebuild_refuses_a_column_it_would_otherwise_drop(legacy):
    """Opus read, finding 4: only the shared columns are copied, so a column the model no longer declares would vanish
    without a word; the rebuild names it and stops."""
    with legacy.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN retired_note TEXT")
    with legacy.connect().execution_options(isolation_level="AUTOCOMMIT") as conn, pytest.raises(
        SourceIdentityRefused, match="retired_note"
    ):
        upgrade_sources_to_composite_key(conn)
    assert source_identity_state(legacy.connect()) == "legacy"  # nothing was changed


def _trace(conn):
    seen: list[str] = []
    conn.connection.dbapi_connection.set_trace_callback(seen.append)
    return seen


def _unkeyed(engine, n=40):
    """Legacy rows that DO need a backfill: the column added, every row holding a feed, no key yet."""
    from src.database.source_identity import add_feed_key_column

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        add_feed_key_column(conn)
        for i in range(100, 100 + n):
            conn.exec_driver_sql("INSERT INTO sources (id, name, domain, rss_url, status) VALUES (?,?,?,?, 'unqualified')",
                                 (i, f"S{i}", f"s{i}.example", f"https://s{i}.example/rss"))


def test_the_backfill_is_one_commit_on_an_autocommit_connection_not_one_per_source(legacy):
    """Measured: 6,400 UPDATEs in autocommit are 6,400 commits, 10.5 s on an encrypted store (0.47 s in one transaction)."""
    from src.database.source_identity import backfill_feed_keys

    _unkeyed(legacy)
    with legacy.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        seen = _trace(conn)
        changed = backfill_feed_keys(conn)
        conn.connection.dbapi_connection.set_trace_callback(None)
        assert changed >= 40
        updates = [i for i, q in enumerate(seen) if q.startswith("UPDATE sources SET feed_key")]
        begins = [i for i, q in enumerate(seen) if q.startswith("BEGIN")]
        commits = [i for i, q in enumerate(seen) if q == "COMMIT"]
        assert len(updates) == changed and len(begins) == 1 and len(commits) == 1
        assert begins[0] < updates[0] and updates[-1] < commits[0]            # every update inside the one transaction
        assert not conn.connection.dbapi_connection.in_transaction
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM sources WHERE feed_key = ''").scalar_one() == 1  # b.com has no feed


def test_the_backfill_inside_a_callers_transaction_begins_and_commits_nothing(legacy):
    from src.database.source_identity import backfill_feed_keys

    _unkeyed(legacy)
    with legacy.connect() as conn:
        conn.exec_driver_sql("UPDATE sources SET name = name")                # the caller's transaction, open
        dbapi = conn.connection.dbapi_connection
        assert dbapi.in_transaction
        seen = _trace(conn)
        backfill_feed_keys(conn)
        dbapi.set_trace_callback(None)
        assert not [q for q in seen if q.startswith("BEGIN") or q == "COMMIT" or q == "ROLLBACK"]
        assert dbapi.in_transaction                                            # still the caller's, still open
        conn.rollback()                                                        # and the caller can still take it all back
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM sources WHERE feed_key <> ''").scalar_one() == 0


def test_a_failed_backfill_in_its_own_transaction_changes_no_key(legacy):
    from src.database.source_identity import backfill_feed_keys

    _unkeyed(legacy)
    with legacy.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("CREATE TRIGGER no_key_for_130 BEFORE UPDATE OF feed_key ON sources WHEN NEW.id = 130 "
                             "BEGIN SELECT RAISE(ABORT, 'refused'); END")
        with pytest.raises(Exception, match="refused"):
            backfill_feed_keys(conn)
        assert not conn.connection.dbapi_connection.in_transaction
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM sources WHERE feed_key <> ''").scalar_one() == 0   # all or nothing


def test_a_sqlalchemy_transaction_that_has_only_read_owns_the_backfill_and_its_rollback_takes_the_keys_back(legacy):
    """The independent read's L2: pysqlite sets ``in_transaction`` at the first DML only, so a caller inside ``engine.begin()``
    that had only read looked idle, the backfill ran its own BEGIN IMMEDIATE...COMMIT, and the caller's rollback no longer
    undid the keys. Red when the decision goes back to the driver's flag alone."""
    from src.database.source_identity import backfill_feed_keys

    _unkeyed(legacy)
    conn = legacy.connect()
    trans = conn.begin()
    conn.exec_driver_sql("SELECT COUNT(*) FROM sources").scalar_one()
    assert not conn.connection.dbapi_connection.in_transaction        # SQLAlchemy says open, the driver says idle
    seen = _trace(conn)
    assert backfill_feed_keys(conn) >= 40
    conn.connection.dbapi_connection.set_trace_callback(None)
    # the implicit BEGIN of the first UPDATE is pysqlite's own and belongs to the caller; the backfill adds none of its own
    assert "COMMIT" not in [q.strip().upper() for q in seen] and "BEGIN IMMEDIATE" not in [q.strip().upper() for q in seen]
    trans.rollback()
    conn.close()
    with legacy.connect() as c:
        assert c.exec_driver_sql("SELECT COUNT(*) FROM sources WHERE feed_key <> '' AND id >= 100").scalar_one() == 0


def test_the_same_transaction_commits_the_keys_when_the_caller_commits(legacy):
    from src.database.source_identity import backfill_feed_keys

    _unkeyed(legacy)
    with legacy.begin() as conn:
        conn.exec_driver_sql("SELECT COUNT(*) FROM sources").scalar_one()
        assert backfill_feed_keys(conn) >= 40
    with legacy.connect() as c:
        assert c.exec_driver_sql("SELECT COUNT(*) FROM sources WHERE feed_key <> '' AND id >= 100").scalar_one() >= 40

