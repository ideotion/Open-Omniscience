"""
A feed stored twice before R628, with and without a login, stays two rows: no write, bulk update or restore fails on it (R634).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before R628 the feed key kept a URL's userinfo, so one feed could be stored twice in one domain: ``https://news.example/rss`` and
``https://alice:hunter2@news.example/rss`` (or two logins) had two keys. R628 derives one key for both, so re-deriving the
credentialed row's key broke ``UNIQUE (domain, feed_key)``: its next ORM write (the crawl lane's stamp) failed and was rolled back,
the daily source-topics bulk UPDATE failed whole, the curated stamp's heal failed the boot step, and restoring a backup holding the
pair failed at the source INSERT (or, into a store holding one of the two, filed both halves under one row). R634 (option b): a row
whose stored key is its own feed's pre-R628 key keeps it when re-deriving would meet another row's key, and the pair stays two rows.
The kept key holds the login, so it is never a parameter of a write, never logged and never reported.

Driven through the real paths (``_lane_step_crawl`` over an in-memory fetch session, ``apply_source_topics``,
``stamp_curated_catalog``, ``merge_corpus``, ``source_for_feed``, ``upsert_sources``, the YAML import and ``export_csv``); nothing
leaves the process. The credentials are fakes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import STATUS_QUALIFIED, STATUS_UNQUALIFIED
from src.database.models import Article, Base, Source

_DOMAIN = "news.example"
_PASSWORD, _PASSWORD_B = "hunter2", "sw0rdfish"
_PLAIN = f"https://{_DOMAIN}/rss"
_CRED = f"https://alice:{_PASSWORD}@{_DOMAIN}/rss"
_OTHER = f"https://bob:{_PASSWORD_B}@{_DOMAIN}/rss"
_K = f"f:{_DOMAIN}/rss"


def _legacy(url: str) -> str:
    """The key a build before R628 stored for ``url``: the userinfo kept (for the plain URL, today's key)."""
    return "f:" + url.split("://", 1)[1].lower()


_SHAPES = {
    "plain-and-login": (_PLAIN, _CRED),
    "two-logins": (_CRED, _OTHER),
    "plain-and-two-logins": (_PLAIN, _CRED, _OTHER),
}


def _secret_free(value: object) -> None:
    said = value if isinstance(value, str) else json.dumps(value, default=str)
    assert _PASSWORD not in said and _PASSWORD_B not in said, said


# --------------------------------------------------------------------------- #
# A store holding the pair as a build before R628 left it
# --------------------------------------------------------------------------- #


def _engine(url: str = "sqlite:///:memory:"):
    engine = create_engine(url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


def _plant(s, urls, **fields) -> list[int]:
    """One row per URL of ``_DOMAIN``, each keyed as a build before R628 keyed it (written round the ORM, as that build's rows are)."""
    rows = [Source(name=f"feed {i}", domain=_DOMAIN, rss_url=f"https://{_DOMAIN}/planting-{i}", **fields) for i in range(len(urls))]
    s.add_all(rows)
    s.commit()
    ids = [r.id for r in rows]
    for sid, url in zip(ids, urls, strict=True):
        s.execute(text("UPDATE sources SET rss_url = :u, feed_key = :k WHERE id = :i"), {"u": url, "k": _legacy(url), "i": sid})
    s.commit()
    s.expire_all()
    return ids


def _keys(s) -> list[tuple[str, str]]:
    s.expire_all()
    return sorted((r.rss_url, r.feed_key) for r in s.query(Source).filter(Source.domain == _DOMAIN))


def _as_planted(urls) -> list[tuple[str, str]]:
    return sorted((u, _legacy(u)) for u in urls)


@pytest.fixture()
def engine():
    return _engine()


@pytest.fixture()
def db(engine):
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


@pytest.fixture()
def params():
    """Every parameter of every statement ANY engine runs from the moment a test calls ``params.start()``: the listener sits on
    the ``Engine`` class (the R628 reads' test note), so a path that opens its own engine is heard too, and it is removed after."""
    from sqlalchemy.engine import Engine

    class _Seen(list):
        armed = False

        def start(self):
            self.clear()
            self.armed = True

    seen = _Seen()

    def _record(conn, cursor, statement, parameters, context, executemany):
        if seen.armed:
            seen.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", _record)
    yield seen
    event.remove(Engine, "before_cursor_execute", _record)


def _no_login_in(params) -> None:
    for statement, parameters in params:
        assert _PASSWORD not in str(parameters) and _PASSWORD_B not in str(parameters), (statement, parameters)


# --------------------------------------------------------------------------- #
# 1. The ORM write (the before_update event): the crawl lane's stamp and every other write of a row
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_an_orm_write_of_each_row_of_a_pair_keeps_the_pair(db, params, shape):
    urls = _SHAPES[shape]
    ids = _plant(db, urls)
    params.start()
    for sid in ids:
        db.get(Source, sid).enabled = False
        db.commit()  # before: IntegrityError, UNIQUE (domain, feed_key), on the credentialed row
    assert _keys(db) == _as_planted(urls)
    _no_login_in(params)


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_one_flush_writing_every_row_of_a_pair_keeps_the_pair(db, shape):
    urls = _SHAPES[shape]
    ids = _plant(db, urls)
    for sid in ids:
        db.get(Source, sid).priority = 5
    db.commit()  # the events of one flush all run before its UPDATEs: each row reads the others as they are stored
    assert _keys(db) == _as_planted(urls)


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _FetchSession:
    """Answers in memory: every request is a 404 (robots: allow-all, no sitemap, an empty start page)."""

    def __init__(self):
        self.headers = {}
        self.fetched: list[str] = []

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        self.fetched.append(url)
        return _Resp(status_code=404, text="not found", url=url)


def test_the_crawl_lanes_stamp_of_the_credentialed_row_is_written(db, params, caplog):
    """The lane picks one feed per outlet and stamps it through the ORM; the credentialed half of the pair is due first here."""
    from src.ingest import EthicalFetcher
    from src.scheduler.runner import _lane_step_crawl
    from src.scheduler.settings import SchedulerSettings

    plain, cred = _plant(db, (_PLAIN, _CRED), enabled=True, status=STATUS_QUALIFIED, language="en")
    db.get(Source, plain).last_crawled_at = datetime(2026, 11, 1, tzinfo=UTC)
    db.commit()
    params.start()
    with caplog.at_level(logging.DEBUG):
        out = _lane_step_crawl(db, EthicalFetcher(min_interval_s=0.0, session=_FetchSession()), SchedulerSettings(crawl_per_pass=1))
    assert out["sources_crawled"] == 1  # before: 0, the stamp's commit failed and was rolled back, so the outlet stayed due
    db.expire_all()
    assert db.get(Source, cred).last_crawled_at is not None
    assert _keys(db) == _as_planted((_PLAIN, _CRED))
    assert "crawl supplement" not in caplog.text
    _secret_free(caplog.text)
    _no_login_in(params)


@pytest.mark.parametrize(
    ("mate_url", "mate_key"),
    [(f"https://{_DOMAIN}/moved", _K), (_PLAIN, f"f:{_DOMAIN}/stale")],
    ids=["a-twin-storing-todays-key-under-another-url", "a-twin-whose-own-url-derives-todays-key"],
)
def test_a_twin_with_a_stale_key_is_still_a_twin(db, mate_url, mate_key):
    """The key UNIQUE compares is the stored one, and the key a row takes when next written is its URL's: either makes a twin."""
    mate, cred = _plant(db, (mate_url, _CRED))
    db.execute(text("UPDATE sources SET feed_key = :k WHERE id = :i"), {"k": mate_key, "i": mate})
    db.commit()
    for sid in (cred, mate):
        db.get(Source, sid).enabled = False
        db.commit()
    assert dict(_keys(db))[_CRED] == _legacy(_CRED)


def test_control_a_legacy_key_with_no_twin_still_heals_on_its_next_write(db):
    (sid,) = _plant(db, (_CRED,))
    db.get(Source, sid).enabled = False
    db.commit()
    assert _keys(db) == [(_CRED, _K)]  # R628 unchanged: the login leaves the key


def test_control_a_legacy_key_beside_another_feed_still_heals(db):
    sid, _other = _plant(db, (_CRED, f"https://{_DOMAIN}/world"))
    db.get(Source, sid).enabled = False
    db.commit()
    assert dict(_keys(db))[_CRED] == _K


def test_control_editing_a_kept_rows_feed_onto_its_twins_is_still_refused(db):
    """Only a key the row's OWN URL derived is kept: an edit that makes a row the same feed as another is the duplicate it was."""
    _plain, cred = _plant(db, (_PLAIN, _CRED))
    db.get(Source, cred).rss_url = f"https://carol:pw11@{_DOMAIN}/rss/"
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_control_editing_a_kept_rows_feed_to_another_feed_derives_its_key(db):
    _plain, cred = _plant(db, (_PLAIN, _CRED))
    db.get(Source, cred).rss_url = f"https://{_DOMAIN}/world"
    db.commit()
    assert dict(_keys(db))[f"https://{_DOMAIN}/world"] == f"f:{_DOMAIN}/world"


# --------------------------------------------------------------------------- #
# 2. The daily source-topics bulk UPDATE
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_the_source_topics_bulk_update_writes_a_pair(engine, params, monkeypatch, shape):
    from src.analytics import source_topics as st

    factory = sessionmaker(bind=engine, future=True)
    urls = _SHAPES[shape]
    with factory() as s:
        ids = _plant(s, urls, tags="news")
    monkeypatch.setattr(st, "source_topic_candidates", lambda *a, **k: {"candidates": [{"id": i, "topics": ["economy"]} for i in ids]})
    params.start()
    # before: IntegrityError, the whole statement (every candidate of the chunk) failed and nothing was written
    assert st.apply_source_topics(factory()) == {"sources_updated": len(urls), "tags_added": len(urls)}
    with factory() as s:
        assert _keys(s) == _as_planted(urls)
        assert {r.tags for r in s.query(Source)} == {"news,economy"}
    _no_login_in(params)


def test_control_the_bulk_update_still_heals_a_legacy_key_with_no_twin(engine, monkeypatch):
    from src.analytics import source_topics as st

    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        ids = _plant(s, (_CRED,), tags="news")
    monkeypatch.setattr(st, "source_topic_candidates", lambda *a, **k: {"candidates": [{"id": i, "topics": ["economy"]} for i in ids]})
    st.apply_source_topics(factory())
    with factory() as s:
        assert _keys(s) == [(_CRED, _K)]


# --------------------------------------------------------------------------- #
# 3. The curated stamp's heal (boot)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape", list(_SHAPES))
def test_the_curated_stamp_heal_keeps_a_pair(db, params, shape):
    from src.catalog.qualification import stamp_curated_catalog

    urls = _SHAPES[shape]
    _plant(db, urls, tags="via:curated", status=STATUS_UNQUALIFIED)
    params.start()
    counts = stamp_curated_catalog(db)  # before: IntegrityError from the heal's executemany, after the stamp
    assert counts["stamped"] == len(urls)
    assert _keys(db) == _as_planted(urls)
    assert {r.status for r in db.query(Source)} == {STATUS_QUALIFIED}
    _no_login_in(params)


# --------------------------------------------------------------------------- #
# 4. Restoring a backup that holds the pair
# --------------------------------------------------------------------------- #


def _corpus(path: Path, rows) -> dict[str, int]:
    """A store at ``path`` holding ``rows`` (``(url, key)``), one article each, titled by its feed URL. Returns url -> source id."""
    engine = _engine(f"sqlite:///{path}")
    with sessionmaker(bind=engine, future=True)() as s:
        ids = _plant(s, [u for u, _k in rows])
        for sid, (url, key) in zip(ids, rows, strict=True):
            s.execute(text("UPDATE sources SET feed_key = :k WHERE id = :i"), {"k": key, "i": sid})
            n = len(s.query(Article).all())
            page = f"https://{_DOMAIN}/{path.stem}/{n}"
            s.add(Article(title=f"from {path.stem} {sid}", url=page, canonical_url=page, source_id=sid,
                          content=f"an article of {url} in {path.stem}", hash=f"{path.stem[:1]}{n}".ljust(64, "0")))
        s.commit()
        out = {u: sid for sid, (u, _k) in zip(ids, rows, strict=True)}
    engine.dispose()
    return out


def _restore(tmp_path, staged_rows, working_rows):
    from src.backup import merge

    staged, working = tmp_path / "staged.db", tmp_path / "working.db"
    _corpus(staged, staged_rows)
    _corpus(working, working_rows)
    asked: list[tuple] = []
    reader = merge._q

    def _q(con, sql, params=()):
        asked.append(tuple(params))
        return reader(con, sql, params)

    merge._q = _q
    try:
        report, _batch = merge.merge_corpus(staged, working, {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test",
                                                              "app_version": "0.5.0", "alembic_rev": "head", "manifest": None})
    finally:
        merge._q = reader
    _secret_free([str(p) for p in asked])  # the merge's own reads never carry a login as a parameter
    con = sqlite3.connect(working)
    try:
        rows = sorted(con.execute("SELECT rss_url, feed_key FROM sources").fetchall())
        filed = {
            content.split(" in ")[0].removeprefix("an article of "): url
            for content, url in con.execute(
                "SELECT a.content, s.rss_url FROM articles a JOIN sources s ON s.id = a.source_id WHERE a.content LIKE '% in staged'"
            )
        }
    finally:
        con.close()
    return report, rows, filed


_PAIR = [(_PLAIN, _K), (_CRED, _legacy(_CRED))]


@pytest.mark.parametrize(
    "working_rows",
    [[], [(_PLAIN, _K)], [(_CRED, _legacy(_CRED))], _PAIR],
    ids=["into-an-empty-store", "into-a-store-holding-the-plain-row", "into-a-store-holding-the-credentialed-row",
         "into-a-store-holding-both"],
)
def test_restoring_a_backup_that_holds_the_pair_keeps_two_rows(tmp_path, working_rows):
    report, rows, filed = _restore(tmp_path, _PAIR, working_rows)  # before: an empty store failed at the INSERT
    assert rows == sorted(_PAIR)
    assert filed == {_PLAIN: _PLAIN, _CRED: _CRED}  # each half's articles under its own row, never both under one
    _secret_free(report)


def test_restoring_a_backup_holding_two_logins_of_one_feed_keeps_two_rows(tmp_path):
    pair = [(_CRED, _legacy(_CRED)), (_OTHER, _legacy(_OTHER))]
    report, rows, filed = _restore(tmp_path, pair, [])
    assert rows == sorted(pair)
    assert filed == {_CRED: _CRED, _OTHER: _OTHER}
    _secret_free(report)


def test_restoring_the_credentialed_half_alone_files_it_under_its_own_row(tmp_path):
    _report, rows, filed = _restore(tmp_path, [(_CRED, _legacy(_CRED))], _PAIR)
    assert rows == sorted(_PAIR)
    assert filed == {_CRED: _CRED}  # before: under the plain row, the one today's key named


def test_restoring_the_credentialed_half_spelled_otherwise_files_it_under_its_own_row(tmp_path):
    """The store's row holds the same pre-R628 key under another spelling of the URL (scheme, case, a trailing slash)."""
    spelled = f"http://alice:{_PASSWORD}@NEWS.example/rss/"
    working = [(_PLAIN, _K), (spelled, _legacy(_CRED))]
    _report, rows, filed = _restore(tmp_path, [(_CRED, _legacy(_CRED))], working)
    assert rows == sorted(working)
    assert filed == {_CRED: spelled}


def test_restoring_the_pair_into_a_store_whose_one_row_was_healed_files_both_under_it(tmp_path):
    """Stated: the store already holds the feed as ONE row (its key healed), so the backup's two halves are that row (local wins)."""
    _report, rows, filed = _restore(tmp_path, _PAIR, [(_CRED, _K)])
    assert rows == [(_CRED, _K)]
    assert filed == {_PLAIN: _CRED, _CRED: _CRED}


def test_control_restoring_the_credentialed_feed_alone_beside_the_plain_one_is_one_source(tmp_path):
    """R628 unchanged: a backup holding the feed ONCE, with a login, is the store's plain row of the same feed."""
    _report, rows, filed = _restore(tmp_path, [(_CRED, _legacy(_CRED))], [(_PLAIN, _K)])
    assert rows == [(_PLAIN, _K)]
    assert filed == {_CRED: _PLAIN}


def test_a_credentialed_sibling_feed_is_masked_in_the_restore_report(tmp_path):
    report, _rows, _filed = _restore(tmp_path, _PAIR, [(_PLAIN, _K)])
    (sibling,) = report["sources"]["siblings"]
    assert sibling["incoming_feed"] == f"https://***@{_DOMAIN}/rss"
    _secret_free(report)


# --------------------------------------------------------------------------- #
# 5. An add or an import of one of the two URLs finds its own row
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("again", "row"), [(_CRED, 1), (_PLAIN, 0), (_OTHER, 0)])
def test_an_add_of_a_pairs_url_finds_its_own_row(db, again, row):
    from src.database.source_lookup import source_for_feed

    ids = _plant(db, (_PLAIN, _CRED))
    assert source_for_feed(db, _DOMAIN, again).id == ids[row]  # bob's login is the plain row's feed (R628)


def test_an_add_of_a_pairs_url_makes_no_third_row(db):
    from src.database.source_manager import SourceManager

    _plant(db, (_PLAIN, _CRED))
    got = SourceManager(db).create_source("again", _DOMAIN, rss_url=_CRED)
    assert got.rss_url == _CRED and db.query(Source).count() == 2


def test_a_csv_import_of_the_pair_edits_each_row(db):
    from src.catalog.csv_io import parse_sources_csv, upsert_sources, write_csv

    plain, cred = _plant(db, (_PLAIN, _CRED))
    rows, errors = parse_sources_csv(write_csv([{"name": "csv plain", "domain": _DOMAIN, "rss_url": _PLAIN},
                                                {"name": "csv cred", "domain": _DOMAIN, "rss_url": _CRED}]))
    assert errors == []
    res = upsert_sources(db, rows)
    assert res["errors"] == [] and (res["created"], res["updated"]) == (0, 2)
    db.expire_all()
    assert (db.get(Source, plain).name, db.get(Source, cred).name) == ("csv plain", "csv cred")
    assert _keys(db) == _as_planted((_PLAIN, _CRED))


def test_control_a_csv_record_of_the_plain_url_still_edits_a_lone_legacy_row(db):
    """R628's continuity, unchanged: with no twin, the legacy row is read under today's key, so the plain URL is its feed."""
    from src.catalog.csv_io import parse_sources_csv, upsert_sources, write_csv

    (cred,) = _plant(db, (_CRED,))
    rows, _errors = parse_sources_csv(write_csv([{"name": "csv plain", "domain": _DOMAIN, "rss_url": _PLAIN},
                                                 {"name": "csv world", "domain": _DOMAIN, "rss_url": f"https://{_DOMAIN}/world"}]))
    res = upsert_sources(db, rows)
    assert (res["created"], res["updated"]) == (1, 1)
    db.expire_all()
    assert db.get(Source, cred).name == "csv plain"


def test_a_yaml_import_of_the_pair_edits_each_row(db, tmp_path):
    import yaml

    from src.database.source_manager import SourceManager

    plain, cred = _plant(db, (_PLAIN, _CRED))
    path = tmp_path / "sources.yml"
    path.write_text(yaml.safe_dump({"sources": [{"name": "yaml cred", "domain": _DOMAIN, "rss_url": _CRED},
                                                {"name": "yaml plain", "domain": _DOMAIN, "rss_url": _PLAIN}]}), encoding="utf-8")
    SourceManager(db).import_sources_from_yaml(str(path))
    db.expire_all()
    assert db.query(Source).count() == 2
    assert (db.get(Source, plain).name, db.get(Source, cred).name) == ("yaml plain", "yaml cred")


# --------------------------------------------------------------------------- #
# 6. The kept key is never written out
# --------------------------------------------------------------------------- #

#: Every module that names the column: the identity's writers, matchers and its triage. A module that would carry a key into an
#: answer, a report, a bundle, a log or the UI is not one of them (none of src/api, src/static, src/monitoring, the doctor).
_NAMES_FEED_KEY = {
    "src/analytics/engine_identity.py",
    "src/analytics/source_topics.py",
    "src/backup/merge.py",
    "src/catalog/csv_io.py",
    "src/catalog/qualification.py",
    "src/database/feed_key.py",
    "src/database/models.py",
    "src/database/outlet.py",
    "src/database/source_identity.py",
    "src/database/source_lookup.py",
    "src/database/source_manager.py",
    "src/ingest/seed_plan.py",
    "src/ingest/seed_sources.py",
    "src/testing/corpus_gen.py",
}


#: A read of every column of ``sources`` carries the key without naming it (the R628 reads' test note): ``SELECT *`` or ``s.*``
#: from it, the ORM's own column list (``Source.__table__`` / ``__mapper__``, ``inspect(Source)``), a ``getattr`` over a column's
#: name, or the table's column listing (``PRAGMA table_info``, a ``_columns`` / ``_cols`` helper) by name. And a serialiser
#: generic over any model, which reaches a Source whenever one is handed to it (the independent read's M1 on R637: the diagnostics
#: zip's ``inspect(type(obj)).column_attrs``): a mapper's ``column_attrs``, ``inspect(type(...))``, any model's
#: ``__table__.columns``.
_READS_EVERY_COLUMN = re.compile(
    r"(?i:SELECT\s+(?:[\w\"]+\.)?\*\s+FROM\s+(?:\w+\.)?[\"']?sources\b)"
    r"|\bSource\.__(?:table|mapper)__"
    r"|inspect\(\s*Source\s*\)"
    r"|\.column_attrs\b"
    r"|inspect\(\s*type\("
    r"|\w\.__table__\.columns\b"
    r"|getattr\(\s*\w+\s*,\s*\w+\.(?:name|key)\s*\)"
    r"|(?i:(?:table_info|_columns|_cols)\(\s*(?:\w+\s*,\s*)?\(?[\"']?sources\b)",
)

#: The modules that read every column of ``sources`` and do not name the key, each with why that read carries no key out.
_READS_EVERY_COLUMN_WITHOUT_NAMING_IT = {
    "src/database/maintenance.py": "the boot migrations' PRAGMA table_info(sources): which columns exist, never a value",
    "src/database/derived_views.py": "KeywordMention.__table__.columns: the derived table copies that model's columns, never a source",
}

#: The modules that write every column of a source and name the key to write it masked, each with how (the independent read's M1
#: on R637). Named here, not in ``_NAMES_FEED_KEY``: they are a report, and a report writes the key only through ``shown_feed_key``.
_WRITES_THE_KEY_MASKED = {
    "src/api/diagnostics/source_samples.py": "the one-article-per-source zip: rss_url through shown_url, feed_key through "
    "shown_feed_key (tests/test_feed_identity_reads_r628.py builds the real zip and greps every member)",
}


def test_no_module_that_answers_reports_or_shows_names_the_feed_key():
    """No module outside the identity's writers and matchers names the key, or reads every column of ``sources`` (which would
    carry it without naming it). What this cannot see, stated: a table name built at run time (the merge's
    ``PRAGMA inc.table_info("{src}")``, whose module names the key anyway), an ORM row handed whole to a serializer
    (``jsonable_encoder``, ``vars``, ``__dict__``, a pydantic model read from attributes; no route does it today), a serialiser
    whose column listing reaches it by another spelling (an aliased ``inspect``, iterating ``Model.__table__.c``, a ``Row``'s
    ``_mapping`` from a select of the table), a column read through an attribute name held in data, and a copy of the database
    file itself (a full backup carries the kept key beside ``rss_url``, by design)."""
    root = Path(__file__).resolve().parents[1]
    files = [p for p in (root / "src").rglob("*") if p.is_file() and p.suffix in {".py", ".js", ".html", ".css", ".json"}]
    said = {str(p.relative_to(root)): p.read_text(encoding="utf-8", errors="replace") for p in files}
    named = {path for path, body in said.items() if "feed_key" in body}
    assert named <= _NAMES_FEED_KEY | set(_WRITES_THE_KEY_MASKED), sorted(named - _NAMES_FEED_KEY - set(_WRITES_THE_KEY_MASKED))
    generic = {path for path, body in said.items() if _READS_EVERY_COLUMN.search(body)}
    allowed = _NAMES_FEED_KEY | set(_READS_EVERY_COLUMN_WITHOUT_NAMING_IT) | set(_WRITES_THE_KEY_MASKED)
    assert generic <= allowed, sorted(generic - allowed)
    for path in _WRITES_THE_KEY_MASKED:  # each still writes the key through the mask
        assert "shown_feed_key" in said[path], path


@pytest.mark.parametrize(
    "line",
    [
        'con.execute("SELECT * FROM sources")',
        'con.execute("select s.* from main.sources s")',
        "cols = Source.__table__.columns",
        "for attr in sa_inspect(Source).attrs: pass",
        "row = {c.name: getattr(src, c.name) for c in cols}",
        'cols = _columns(conn, "sources")',
        'conn.execute(text("PRAGMA table_info(sources)"))',
        "for prop in inspect(type(obj)).column_attrs:",  # the independent read's M1 on R637, as the zip wrote it
        "props = sa_inspect(Model).column_attrs",
        "state = inspect( type(row) )",
        "names = [c.name for c in Model.__table__.columns]",
    ],
)
def test_the_ratchet_sees_a_read_of_every_column(line):
    assert _READS_EVERY_COLUMN.search(line), line


@pytest.mark.parametrize(
    "line",
    [
        'con.execute("SELECT id, name FROM sources")',
        'con.execute("SELECT * FROM source_topics")',
        "getattr(src, 'rss_url', None)",
        "identity = inspect(source).identity",  # an instance's state (its primary key), not the table's columns
        "state = inspect(obj)",  # an instance's state: the zip reads each column it lists through it, not a listing
        "kind = type(exc).__name__",
    ],
)
def test_control_the_ratchet_lets_a_named_column_read_pass(line):
    assert not _READS_EVERY_COLUMN.search(line), line


def test_the_csv_and_yaml_exports_carry_no_key_and_keep_the_url_as_written(db, tmp_path):
    """No export names the key column, and a kept key is in none of them. The exports DO carry the login: through ``rss_url``, as
    written, by R637, so a re-import fetches the feed again (Steward 3's read: this test used to pass while the password stood in
    the body, because it looked only for the key). The answers the UI shows mask it: tests/test_rss_url_masked_r637.py."""
    from src.api.source_io import export_csv
    from src.database.source_manager import SourceManager

    _plant(db, (_PLAIN, _CRED))
    async def _body(response):
        return "".join([chunk if isinstance(chunk, str) else chunk.decode() async for chunk in response.body_iterator])

    body = asyncio.run(_body(export_csv(db)))
    assert _legacy(_CRED) not in body and "feed_key" not in body
    assert _CRED in body and _PLAIN in body  # both rows of the pair, each URL as written (R637)
    path = tmp_path / "out.yml"
    SourceManager(db).export_sources_to_yaml(str(path))
    said = path.read_text(encoding="utf-8")
    assert _legacy(_CRED) not in said and "feed_key" not in said
    assert _CRED in said and _PLAIN in said


# --------------------------------------------------------------------------- #
# 7. The helpers (new in R634)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("url", "legacy"),
    [(_CRED, f"f:alice:{_PASSWORD}@{_DOMAIN}/rss"), (_PLAIN, _K), ("HTTPS://Alice:PW@News.Example/rss/", "f:alice:pw@news.example/rss"),
     ("", ""), (None, "")],
)
def test_legacy_feed_key_is_the_key_a_build_before_r628_derived(url, legacy):
    from src.database.feed_key import legacy_feed_key

    assert legacy_feed_key(url) == legacy


@pytest.mark.parametrize(
    ("stored", "url", "keeps"),
    [
        (_legacy(_CRED), _CRED, True),
        (_K, _CRED, False),                              # already healed
        (_K, _PLAIN, False),                             # a plain row
        (_legacy(_CRED), f"https://{_DOMAIN}/world", False),  # its URL was edited since: the stored key is another URL's
        (f"f:{_DOMAIN}/@me/rss", f"https://{_DOMAIN}/@me/rss", False),  # an @ in the path is today's key too
        ("", _CRED, False),
        (None, None, False),
    ],
)
def test_only_a_rows_own_pre_r628_key_may_be_kept(stored, url, keeps):
    from src.database.feed_key import keeps_a_stored_key

    assert keeps_a_stored_key(stored, url) is keeps


@pytest.mark.parametrize(
    ("mates", "kept"),
    [
        ([], False),
        ([(_K, _PLAIN)], True),                            # the plain twin holds today's key
        ([(_legacy(_OTHER), _OTHER)], True),               # another login would take it
        ([(f"f:{_DOMAIN}/world", f"https://{_DOMAIN}/world")], False),
        ([(_legacy(_CRED).replace("rss", "x"), f"https://alice:{_PASSWORD}@{_DOMAIN}/x")], False),
    ],
)
def test_key_to_write_keeps_a_stored_key_only_against_a_twin(mates, kept):
    from src.database.feed_key import key_to_write

    assert key_to_write(_legacy(_CRED), _CRED, mates) == (_legacy(_CRED) if kept else _K)


def test_lookup_key_names_the_pre_r628_key_only_where_it_is_held():
    from src.database.feed_key import lookup_key

    assert lookup_key(_CRED, {_K, _legacy(_CRED)}) == _legacy(_CRED)
    assert lookup_key(_CRED, {_K}) == _K
    assert lookup_key(_PLAIN, {_K, _legacy(_CRED)}) == _K


def test_the_collision_is_one_query_on_the_domains_index_and_only_for_a_key_that_can_be_kept(db, params):
    ids = _plant(db, (_PLAIN, _CRED, f"https://{_DOMAIN}/world"))
    params.start()
    for sid in ids:
        db.get(Source, sid).enabled = False
        db.commit()
    asked = [(st, p) for st, p in params if st.lstrip().startswith("SELECT") and "sources.id != ?" in st]
    assert len(asked) == 1  # the credentialed row's; the plain row and the other feed ask nothing
    statement, parameters = asked[0]
    plan = db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).all()
    assert "USING INDEX" in " ".join(str(r) for r in plan)
