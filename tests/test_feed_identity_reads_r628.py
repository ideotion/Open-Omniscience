"""
The R628 reads, folded: what Steward 3's and the independent read of R628+R634 found, each pinned on the path it was found on.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

1. A page's ``<link>`` is read as an anchor is (independent S1): ``<link href="/rss">`` on a page fetched from a URL with a login
   was stored as an outbound ArticleLink, the login in ``url`` and ``normalized_url``.
2. An edit onto a feed another row of the domain holds answers 409 in the add's words (independent S2 and nit c): a new login on
   the kept row of a plain+login pair raised UNIQUE as a 500, and the plain row could take its twin's exact URL.
3. An import finds the row an add finds (independent S3): on a two-logins pair the plain URL or a third login made a third row.
4. A restore files a feed under the store's unhealed legacy row of it (Steward 3's item 2, independent S4: rule 2b), and the order
   of rules 1 and 2 and the oldest of two same-URL rows are pinned (the two mutants the independent read left alive).
5. A database error whose statement holds a login never quotes it (Steward 3's item 5): the app reads it through
   ``record_text``, and the error hides its parameters for the server's own log.
6. The pipeline's two URL log lines mask the login (independent nit d).

The credentials are fakes; nothing leaves the process (every fetch is a stand-in).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source

_DOMAIN = "news.example"
_PASSWORD, _PASSWORD_B, _PASSWORD_C = "hunter2", "sw0rdfish", "newpass9"
_PLAIN = f"https://{_DOMAIN}/rss"
_CRED = f"https://alice:{_PASSWORD}@{_DOMAIN}/rss"
_OTHER = f"https://bob:{_PASSWORD_B}@{_DOMAIN}/rss"
_THIRD = f"https://carol:{_PASSWORD_C}@{_DOMAIN}/rss"
_WORLD = f"https://{_DOMAIN}/world"
_K = f"f:{_DOMAIN}/rss"
_HELD = f"Source with domain {_DOMAIN} and this feed already exists"


def _legacy(url: str) -> str:
    """The key a build before R628 stored for ``url``: the userinfo kept (for a URL without one, today's key)."""
    return "f:" + url.split("://", 1)[1].lower()


def _secret_free(said: str) -> None:
    for word in (_PASSWORD, _PASSWORD_B, _PASSWORD_C):
        assert word not in said, said


def _engine(url: str = "sqlite:///:memory:"):
    engine = create_engine(url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


def _plant(s, rows, **fields) -> list[int]:
    """One source of ``_DOMAIN`` per ``(url, key)``, written round the ORM as a build before R628 left it."""
    made = [Source(name=f"feed {i}", domain=_DOMAIN, rss_url=f"https://{_DOMAIN}/planting-{i}", **fields) for i in range(len(rows))]
    s.add_all(made)
    s.commit()
    ids = [r.id for r in made]
    for sid, (url, key) in zip(ids, rows, strict=True):
        s.execute(text("UPDATE sources SET rss_url = :u, feed_key = :k WHERE id = :i"), {"u": url, "k": key, "i": sid})
    s.commit()
    s.expire_all()
    return ids


def _rows(s) -> list[tuple[str, str]]:
    s.expire_all()
    return sorted((r.rss_url, r.feed_key) for r in s.query(Source).filter(Source.domain == _DOMAIN))


@pytest.fixture()
def db():
    engine = _engine()
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def sess_factory(tmp_path):
    engine = _engine(f"sqlite:///{tmp_path / 's.db'}")
    yield sessionmaker(bind=engine, future=True)
    engine.dispose()


@pytest.fixture()
def client(sess_factory):
    """The app over a file store; an unhandled error answers its 500 here instead of raising into the test."""
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        s = sess_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# 1. A page's <link> is read as an anchor is
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "href",
    ["/rss", "/s.css", f"https://{_DOMAIN}/q", "https://other.example/p", "https://cdn.other.example/s.css"],
)
def test_a_link_element_is_typed_exactly_as_an_anchor(href):
    from src.services.link_analyzer import LinkExtractor

    base = f"https://alice:{_PASSWORD}@{_DOMAIN}/a"
    # href written first: the extractor finds an element by its serialised text, which puts href before rel (seen, unchanged)
    (as_link,) = LinkExtractor().extract_links(f'<html><head><link href="{href}" rel="alternate"/></head></html>', base_url=base)
    (as_anchor,) = LinkExtractor().extract_links(f'<html><body><a href="{href}">x</a></body></html>', base_url=base)
    assert as_link["link_type"] == as_anchor["link_type"]  # before: "external" for every <link>, whatever its host


def test_a_pages_own_feed_link_is_not_stored_with_the_pages_login():
    from src.ingest.pipeline import _maybe_index_links

    s = sessionmaker(bind=_engine(), future=True)()
    base = f"https://alice:{_PASSWORD}@{_DOMAIN}/a"
    html = (
        '<html><head><link href="/rss" rel="alternate" type="application/rss+xml"/><link href="/s.css" rel="stylesheet"/>'
        '</head><body><p>text</p><a href="https://other.example/cited">cited</a></body></html>'
    )
    src = Source(name="n", domain=_DOMAIN, rss_url=_CRED)
    s.add(src)
    s.commit()
    page = Article(url=base, canonical_url=f"https://{_DOMAIN}/a", source_id=src.id, title="t", content="c" * 50, hash="h" * 64)
    s.add(page)
    s.commit()
    _maybe_index_links(s, page, html, base)
    stored = s.query(ArticleLink.url, ArticleLink.normalized_url).all()
    _secret_free(repr(stored))  # before: two rows, alice:hunter2 in both columns
    assert [u for u, _n in stored] == ["https://other.example/cited"]  # control: a cited page of another site is still a link
    s.close()


# --------------------------------------------------------------------------- #
# 2. An edit onto a feed another row holds: 409, in the add's words
# --------------------------------------------------------------------------- #


def _put(client, sid: int, **body):
    r = client.put(f"/api/sources/{sid}", json=body)
    _secret_free(r.text)
    for driver in ("UNIQUE", "IntegrityError", "sqlite3", "feed_key"):
        assert driver not in r.text, r.text
    return r


def test_a_new_login_on_the_kept_row_of_a_pair_is_a_409_in_words(client, sess_factory):
    with sess_factory() as s:
        _plain, cred = _plant(s, [(_PLAIN, _K), (_CRED, _legacy(_CRED))])
    r = _put(client, cred, rss_url=_THIRD)
    assert (r.status_code, r.json()["detail"]) == (409, _HELD)  # before: a 500, its driver text withheld
    with sess_factory() as s:
        assert _rows(s) == sorted([(_PLAIN, _K), (_CRED, _legacy(_CRED))])


def test_the_plain_row_of_a_pair_edited_to_its_twins_url_is_a_409(client, sess_factory):
    with sess_factory() as s:
        plain, _cred = _plant(s, [(_PLAIN, _K), (_CRED, _legacy(_CRED))])
    r = _put(client, plain, rss_url=_CRED)
    assert (r.status_code, r.json()["detail"]) == (409, _HELD)  # before: 200, and two rows held one URL
    with sess_factory() as s:
        assert _rows(s) == sorted([(_PLAIN, _K), (_CRED, _legacy(_CRED))])


def test_an_edit_moving_a_source_onto_a_domain_that_holds_its_feed_is_a_409(client, sess_factory):
    with sess_factory() as s:
        (sid,) = _plant(s, [(_WORLD, f"f:{_DOMAIN}/world")])
        s.add(Source(name="there", domain="other.example", rss_url="https://other.example/rss"))
        s.commit()
    r = _put(client, sid, domain="other.example", rss_url="https://other.example/rss/")  # another spelling: the key matches
    assert (r.status_code, r.json()["detail"]) == (409, "Source with domain other.example and this feed already exists")


@pytest.mark.parametrize(
    ("which", "body", "stored"),
    [
        ("cred", {"rss_url": f"https://***@{_DOMAIN}/rss"}, _CRED),  # the form sent back as shown: keeps the login (R637)
        ("cred", {"rss_url": _WORLD}, _WORLD),  # another feed of the domain
        ("plain", {"rss_url": f"https://{_DOMAIN}/rss/"}, f"https://{_DOMAIN}/rss/"),  # a respelling of its own feed
        ("cred", {"name": "renamed"}, _CRED),  # no feed field at all
    ],
    ids=["masked-url-sent-back", "another-feed", "respelling-the-plain-row", "another-field"],
)
def test_control_an_edit_that_moves_onto_no_held_feed_still_saves(client, sess_factory, which, body, stored):
    with sess_factory() as s:
        plain, cred = _plant(s, [(_PLAIN, _K), (_CRED, _legacy(_CRED))])
    sid = cred if which == "cred" else plain
    r = _put(client, sid, **body)
    assert r.status_code == 200, r.text
    with sess_factory() as s:
        assert s.get(Source, sid).rss_url == stored


def test_control_an_edit_leaving_the_feed_as_it_is_saves_where_two_rows_already_share_its_url(client, sess_factory):
    """Only an edit that MOVES a row is asked about: the two rows nit (c)'s edit left on one URL before this refusal (the twin
    keeping its key, the edited plain row today's) still save their other fields, the form sending the shown URL back."""
    with sess_factory() as s:
        _twin, second = _plant(s, [_ALICE, (_CRED, _K)])
    r = _put(client, second, rss_url=f"https://***@{_DOMAIN}/rss", name="kept")
    assert r.status_code == 200, r.text
    with sess_factory() as s:
        assert (s.get(Source, second).name, s.get(Source, second).rss_url) == ("kept", _CRED)


def test_control_an_integrity_error_no_row_explains_is_not_named_a_held_feed(client, sess_factory, monkeypatch):
    """The 409 is said only when another row does store the feed, read back from the store: any other refusal stays a 500."""
    from sqlalchemy.exc import IntegrityError

    from src.database.source_manager import SourceManager

    with sess_factory() as s:
        _plain, cred = _plant(s, [(_PLAIN, _K), (_CRED, _legacy(_CRED))])

    def _refuse(self, source_id, **kwargs):
        raise IntegrityError("UPDATE sources", {}, sqlite3.IntegrityError("NOT NULL constraint failed"))

    monkeypatch.setattr(SourceManager, "update_source", _refuse)
    r = client.put(f"/api/sources/{cred}", json={"rss_url": _WORLD})
    assert r.status_code == 500
    assert _HELD not in r.text
    assert r.json()["detail"] == "internal error: IntegrityError (a database driver's text is withheld)"  # its class, never its words


# --------------------------------------------------------------------------- #
# 3. An import finds the row an add finds
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("url", [_PLAIN, _THIRD], ids=["the-plain-url", "a-third-login"])
def test_an_import_and_an_add_of_a_two_logins_pairs_feed_find_the_same_row(db, url):
    from src.catalog.csv_io import upsert_sources
    from src.database.source_lookup import source_for_feed, source_for_import

    alice, _bob = _plant(db, [(_CRED, _legacy(_CRED)), (_OTHER, _legacy(_OTHER))])
    added = source_for_feed(db, _DOMAIN, url)
    imported = source_for_import(db, _DOMAIN, url)
    assert added is not None and imported is not None  # before: the import found none, and made a third row
    assert added.id == imported.id == alice  # both: the oldest of the two
    out = upsert_sources(db, [{"name": "News", "domain": _DOMAIN, "rss_url": url}])
    assert (out["created"], out["updated"]) == (0, 1), out
    assert db.query(Source).filter(Source.domain == _DOMAIN).count() == 2
    db.expire_all()
    assert db.get(Source, alice).rss_url == url


# --------------------------------------------------------------------------- #
# 4. The restore: rule 2b, and the order of rules 1 and 2
# --------------------------------------------------------------------------- #


def _corpus(path: Path, rows) -> None:
    """A store at ``path`` holding ``rows`` (``(url, key)``), each with one article whose text names its feed URL and store."""
    engine = _engine(f"sqlite:///{path}")
    with sessionmaker(bind=engine, future=True)() as s:
        ids = _plant(s, rows)
        for n, (sid, (url, _key)) in enumerate(zip(ids, rows, strict=True)):
            page = f"https://{_DOMAIN}/{path.stem}/{n}"
            s.add(Article(title=f"from {path.stem} {sid}", url=page, canonical_url=page, source_id=sid,
                          content=f"an article of {url} in {path.stem}", hash=f"{path.stem[:1]}{n}".ljust(64, "0")))
        s.commit()
    engine.dispose()


def _restore(tmp_path, staged_rows, working_rows):
    """Merge a backup holding ``staged_rows`` into a store holding ``working_rows``. Returns the report, the store's
    ``(rss_url, feed_key)`` rows after, and where each backup feed's article was filed (its URL -> the receiving row)."""
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
    _secret_free(repr(asked))  # the merge's own reads never carry a login as a parameter
    con = sqlite3.connect(working)
    try:
        rows = sorted(con.execute("SELECT rss_url, feed_key FROM sources").fetchall())
        filed = {
            content.split(" in ")[0].removeprefix("an article of "): (url, key)
            for content, url, key in con.execute(
                "SELECT a.content, s.rss_url, s.feed_key FROM articles a JOIN sources s ON s.id = a.source_id"
                " WHERE a.content LIKE '% in staged'"
            )
        }
    finally:
        con.close()
    return report, rows, filed


_ALICE = (_CRED, _legacy(_CRED))
_WORLD_ROW = (_WORLD, f"f:{_DOMAIN}/world")


def test_another_login_restored_beside_an_unhealed_legacy_row_is_that_row(tmp_path):
    """Steward 3's item 2: the store holds alice@ unhealed beside another feed; the backup brings bob@ of the same feed."""
    report, rows, filed = _restore(tmp_path, [(_OTHER, _legacy(_OTHER))], [_ALICE, _WORLD_ROW])
    assert rows == sorted([_ALICE, _WORLD_ROW])  # before: bob@ inserted beside alice@ as a third row
    assert filed == {_OTHER: _ALICE}
    _secret_free(repr(report))


def test_the_plain_feed_restored_beside_a_lone_legacy_row_is_that_row(tmp_path):
    """Independent S4: the store holds the credentialed row alone of its feed, beside another feed; the backup holds the plain one."""
    report, rows, filed = _restore(tmp_path, [(_PLAIN, _K)], [_ALICE, _WORLD_ROW])
    assert rows == sorted([_ALICE, _WORLD_ROW])  # before: the plain row inserted as a sibling, a pair from then on
    assert filed == {_PLAIN: _ALICE}
    _secret_free(repr(report))


def test_a_pair_restored_beside_a_lone_legacy_row_files_each_half_once(tmp_path):
    """The pair's credentialed half is the legacy row (rule 1); the plain half may not take that row again (rule 2b), so it is a
    sibling, as R634 lands a pair."""
    _report, rows, filed = _restore(tmp_path, [(_PLAIN, _K), _ALICE], [_ALICE, _WORLD_ROW])
    assert rows == sorted([(_PLAIN, _K), _ALICE, _WORLD_ROW])
    assert filed == {_PLAIN: (_PLAIN, _K), _CRED: _ALICE}


def test_a_backups_pair_restored_beside_a_lone_legacy_row_files_its_credentialed_half_there(tmp_path):
    """Both halves read as the legacy row's feed and only one may be it: the credentialed half, so the plain half lands as its
    own row, as a pair lands beside the credentialed row it was (R634). The plain half is the OLDER incoming row here."""
    _report, rows, filed = _restore(tmp_path, [(_PLAIN, _K), (_OTHER, _legacy(_OTHER))], [_ALICE, _WORLD_ROW])
    assert rows == sorted([(_PLAIN, _K), _ALICE, _WORLD_ROW])
    assert filed == {_PLAIN: (_PLAIN, _K), _OTHER: _ALICE}


def test_the_plain_feed_restored_beside_a_two_logins_pair_is_its_oldest_row(tmp_path):
    """As an add and an import find it (S3): the oldest of the rows whose key reads as the feed's."""
    bob = (_OTHER, _legacy(_OTHER))
    _report, rows, filed = _restore(tmp_path, [(_PLAIN, _K)], [_ALICE, bob])
    assert rows == sorted([_ALICE, bob])
    assert filed == {_PLAIN: _ALICE}


@pytest.mark.parametrize("incoming", [(_PLAIN, _K), (_OTHER, _legacy(_OTHER))], ids=["the-plain-url", "another-login"])
def test_control_a_feed_restored_beside_the_pair_is_the_plain_row_as_an_add_finds_it(tmp_path, incoming):
    """Rule 2b never reads past a row that stores today's key: the store's plain row is the feed, as ``source_for_feed`` finds."""
    _report, rows, filed = _restore(tmp_path, [incoming], [(_PLAIN, _K), _ALICE])
    assert rows == sorted([(_PLAIN, _K), _ALICE])
    assert filed == {incoming[0]: (_PLAIN, _K)}


def test_control_a_feed_restored_beside_a_healed_row_of_it_is_that_row(tmp_path):
    """Rule 2b reads only an unhealed row: a row that stores today's key is found by today's key, as before."""
    _report, rows, filed = _restore(tmp_path, [(_OTHER, _legacy(_OTHER))], [(_CRED, _K), _WORLD_ROW])
    assert rows == sorted([(_CRED, _K), _WORLD_ROW])
    assert filed == {_OTHER: (_CRED, _K)}


def test_control_another_feed_restored_beside_a_legacy_row_is_still_a_sibling(tmp_path):
    _report, rows, filed = _restore(tmp_path, [(f"https://{_DOMAIN}/sport", f"f:{_DOMAIN}/sport")], [_ALICE, _WORLD_ROW])
    assert len(rows) == 3
    assert filed == {f"https://{_DOMAIN}/sport": (f"https://{_DOMAIN}/sport", f"f:{_DOMAIN}/sport")}


def test_rule_1_the_urls_own_pre_r628_key_comes_before_rule_2_its_exact_url(tmp_path):
    """Two rows of the domain spell the feed differently: one holds the incoming URL's own pre-R628 key under another spelling,
    the other holds the incoming URL exactly under today's key. The key is the identity a build before R628 wrote: rule 1 wins.
    No writer makes this store today (R634 keeps both legacy keys of a pair), so it is planted: the order's pin."""
    spelled = f"http://alice:{_PASSWORD}@NEWS.example/rss/"
    working = [(spelled, _legacy(_CRED)), (_CRED, _K)]
    _report, rows, filed = _restore(tmp_path, [_ALICE], working)
    assert rows == sorted(working)
    assert filed == {_CRED: (spelled, _legacy(_CRED))}  # rules swapped: under (_CRED, _K)


def test_rule_2_takes_the_oldest_of_two_rows_holding_the_exact_url(tmp_path):
    """Two rows hold the incoming URL exactly and neither holds its pre-R628 key: the oldest is the row, as every reading of a
    domain's rows takes the oldest. No writer makes this store (nit c's leftover keeps the URL's own pre-R628 key, which rule 1
    reads first), so it is planted: the pin on which of the two rule 2 takes."""
    working = [(_CRED, _K), (_CRED, f"f:{_DOMAIN}/old")]
    _report, rows, filed = _restore(tmp_path, [_ALICE], working)
    assert rows == sorted(working)
    assert filed == {_CRED: (_CRED, _K)}  # same_url[-1]: under the newer row


# --------------------------------------------------------------------------- #
# 5. A database error whose statement holds a login
# --------------------------------------------------------------------------- #


@pytest.fixture()
def locked_on_a_login():
    """Every statement whose parameters hold the password fails as a locked database would; ``seen`` keeps the error's own
    text, to show the login was in it."""
    from sqlalchemy.engine import Engine

    seen: list[str] = []

    def _lock(conn, cursor, statement, parameters, context, executemany):
        if _PASSWORD in str(parameters):
            seen.append(f"{statement} {parameters}")
            raise sqlite3.OperationalError("database is locked")

    event.listen(Engine, "before_cursor_execute", _lock)
    yield seen
    event.remove(Engine, "before_cursor_execute", _lock)


def test_the_dedups_database_error_is_answered_and_logged_without_the_login(client, sess_factory, locked_on_a_login, caplog):
    """``_canonical_stored`` binds the url-v1 canonical, login included (Steward 3's item 5): its error reaches the caller only
    through ``record_text``'s class-only reading."""
    from src.api.ingestion import get_fetcher
    from src.api.main import app

    with sess_factory() as s:
        src = Source(name="News", domain=_DOMAIN, rss_url=_PLAIN)
        s.add(src)
        s.commit()
        sid = src.id
    app.dependency_overrides[get_fetcher] = lambda: SimpleNamespace(fetch=None)  # never reached: the dedup runs first
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/ingest", json={"source_id": sid, "url": f"https://alice:{_PASSWORD}@{_DOMAIN}/a"})
    assert locked_on_a_login and _PASSWORD in locked_on_a_login[0]  # the statement did carry it
    assert r.status_code == 500
    _secret_free(r.text)
    _secret_free(caplog.text)
    assert "OperationalError" in r.text  # the class is said


def test_the_dedups_database_error_never_quotes_the_login_to_any_reader(db, locked_on_a_login):
    """The server writes an escaped exception as it made its message (``Exception in ASGI application``, behind a filter that
    takes out passphrases only): so the error itself must not quote the url-v1 parameter, whoever formats it."""
    import traceback

    from sqlalchemy.exc import OperationalError

    from src.ingest.pipeline import _canonical_stored

    with pytest.raises(OperationalError) as caught:
        _canonical_stored(db, f"https://alice:{_PASSWORD}@{_DOMAIN}/a", f"https://{_DOMAIN}/a")
    assert locked_on_a_login and _PASSWORD in locked_on_a_login[0]  # the statement did carry it
    _secret_free(str(caught.value))  # before: "[parameters: ('https://alice:hunter2@news.example/a', 1, 0)]"
    _secret_free("".join(traceback.format_exception(caught.value)))
    assert "database is locked" in str(caught.value)  # the error is still the error


def test_the_scrape_runs_catch_reads_the_dedups_error_without_the_login(db, locked_on_a_login, caplog):
    from src.scheduler.runner import _process_source

    src = Source(name="News", domain=_DOMAIN, rss_url=_PLAIN)
    db.add(src)
    db.commit()

    def _ingest(session, source, *, fetcher):
        from src.ingest.pipeline import _canonical_stored

        _canonical_stored(session, f"https://alice:{_PASSWORD}@{_DOMAIN}/a", f"https://{_DOMAIN}/a")

    import src.ingest.pipeline as pipeline

    with caplog.at_level(logging.DEBUG), pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "ingest_source", _ingest)
        out = _process_source(src, session=db, fetcher=SimpleNamespace())
    assert out == ({"errors": 1}, 0, 0)
    assert locked_on_a_login
    assert "scrape run: source" in caplog.text
    _secret_free(caplog.text)


# --------------------------------------------------------------------------- #
# 6. The pipeline's URL log lines
# --------------------------------------------------------------------------- #


def _fetched(url: str):
    from datetime import UTC, datetime

    from src.ingest import FetchResult

    return FetchResult(requested_url=url, final_url=url, status_code=200, content="<html><body><p>x</p></body></html>",
                       content_type="text/html", fetched_at=datetime.now(UTC))


@pytest.mark.parametrize(
    ("doc", "line"),
    [
        (None, "extract failed for https://***@news.example/tag/politics"),
        (SimpleNamespace(title="Politics", text="Politics news", language="en"), "skipping non-article"),
    ],
    ids=["extract-failed", "non-article"],
)
def test_the_pipelines_url_log_lines_mask_the_login(db, monkeypatch, caplog, doc, line):
    import src.ingest.pipeline as pipeline

    monkeypatch.setenv("OO_SKIP_NON_ARTICLES", "1")
    monkeypatch.setattr(pipeline, "extract_article", lambda content, url=None: doc)
    src = Source(name="News", domain=_DOMAIN, rss_url=_PLAIN)
    db.add(src)
    db.commit()
    with caplog.at_level(logging.INFO, logger="src.ingest.pipeline"):
        out = pipeline.store_fetched(db, src, _fetched(f"https://alice:{_PASSWORD}@{_DOMAIN}/tag/politics"))
    assert out.result in (pipeline.IngestResult.EXTRACT_FAILED, pipeline.IngestResult.NON_ARTICLE)
    assert line in caplog.text, caplog.text
    assert f"https://***@{_DOMAIN}/tag/politics" in caplog.text
    _secret_free(caplog.text)  # before: the login in both lines
