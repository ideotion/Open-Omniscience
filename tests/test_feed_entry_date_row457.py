"""Row 457 (R847): the feed entry's own date, kept for an article whose page gave none, and always shown as the feed's.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``published_at`` comes only from the page's own metadata, and the date the feed gave the item was dropped. The ruling: the
feed's date is a FALLBACK for an article with no date of its own, stored with its origin, shown flagged as the feed's
wherever it is shown; new articles only, no stored row rewritten.

What is pinned here:
- the feed walk, through the real ``EthicalFetcher`` over an in-memory session and the real ``ingest_source``, keeps the
  entry's date in ``feed_entry_published_at`` only for a page with no date of its own, never in ``published_at``; the
  collector's batch does the same; a page with its own date keeps none;
- the entry's date is read from published, then updated; a date beyond a day past the read, or one that is no date, is
  refused, never guessed;
- the reader, the API rows, the Home feed's cards, both exports, the Latest panel and the evidence audit carry it, and the
  reader shows it flagged with why on hover; the SPA's rows draw it through one helper (run as real code by
  ``tests/feed_entry_date_node_test.js``);
- a backup merge carries it on a new article, adopts it onto a duplicate only when neither side has a date of its own, and
  never replaces one; a backup made before the column restores with NULL through the migration chain;
- the boot self-heal adds the column with nothing backfilled; the migration is an ADD COLUMN and goes down without rebuilding
  the articles table (its triggers stay).
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.maintenance import ensure_article_feed_entry_date_column
from src.database.models import Article, Base, Source
from src.ingest import EthicalFetcher
from src.ingest.batch import ArticleBatch
from src.ingest.feed_entry_date import (
    FEED_DATE_HOVER,
    FEED_DATE_LABEL,
    ORIGIN_ARTICLE,
    ORIGIN_FEED,
    article_date,
    entry_date,
    feed_date_fields,
)
from src.ingest.pipeline import IngestResult, ingest_source, ingest_url
from tests._app_engine import app_sqlite_engine
from tests.js_source_helper import python_function_source

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "static"
G = "https://good.example"
FEED_DATE = datetime(2026, 11, 19, 22, 15, 0)
OWN_DATE = datetime(2026, 11, 1, 10, 0, 0)


def _html(title: str, *, own_date: datetime | None = None) -> str:
    body = ("A plain page about a plain subject, written out at some length. " * 30).strip()
    meta = (
        f'<meta property="article:published_time" content="{own_date.isoformat()}+00:00">' if own_date is not None else ""
    )
    return (
        f"<html><head><title>{title}</title>{meta}</head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    )


def _rss(items: list[tuple[str, str | None]]) -> str:
    out = "".join(
        f"<item><title>t</title><link>{link}</link>" + (f"<pubDate>{date}</pubDate>" if date else "") + "</item>"
        for link, date in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>f</title>{out}</channel></rss>'


class _Resp:
    def __init__(self, status_code, text, headers, url):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers
        self.url = url

    def close(self):
        pass


class _Session:
    """Answers in memory: a routed URL gets its answer, anything else a 404 (so an unrouted robots.txt allows everything)."""

    def __init__(self):
        self.headers: dict = {}
        self.routes: dict[str, tuple[int, str, dict]] = {}

    def page(self, url, title="Page", *, own_date=None):
        self.routes[url] = (200, _html(title, own_date=own_date), {"Content-Type": "text/html"})

    def feed(self, url, items):
        self.routes[url] = (200, _rss(items), {"Content-Type": "application/rss+xml"})

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        status, body, headers = self.routes.get(url, (404, "not found", {"Content-Type": "text/plain"}))
        return _Resp(status, body, dict(headers), url)


def _fetcher(tmp_path, session) -> EthicalFetcher:
    return EthicalFetcher(
        min_interval_s=0.0, session=session, robots_cache_path=tmp_path / "robots_cache.json", retry_backoff_s=0,
        max_retries=0,
    )


def _bounded(fn, seconds: float = 20.0):
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed back to the test as raised
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "the call did not finish"
    if "error" in box:
        raise box["error"]
    return box.get("value")


@pytest.fixture()
def db():
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Good News", domain="good.example", rss_url=f"{G}/feed.xml", language="en", enabled=True))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


# --- the entry's date ------------------------------------------------------------------------------------------------------------


def _st(dt: datetime) -> time.struct_time:
    return dt.timetuple()


def test_the_entry_date_is_its_published_date_then_its_updated_date():
    assert entry_date({"published_parsed": _st(FEED_DATE), "updated_parsed": _st(OWN_DATE)}) == FEED_DATE
    assert entry_date({"updated_parsed": _st(OWN_DATE)}) == OWN_DATE  # many Atom feeds give only <updated>
    assert entry_date({}) is None
    assert entry_date({"published_parsed": None}) is None


def test_an_entry_date_that_is_no_date_or_lies_in_the_future_is_refused():
    read_at = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    assert entry_date({"published_parsed": (2026, 2, 30, 0, 0, 0, 0, 0, 0)}, read_at=read_at) is None  # 30 February
    assert entry_date({"published_parsed": "nonsense"}, read_at=read_at) is None
    assert entry_date({"published_parsed": _st(datetime(2026, 11, 29, 11, 0))}, read_at=read_at) is not None  # within a day
    assert entry_date({"published_parsed": _st(datetime(2026, 11, 30, 0, 0))}, read_at=read_at) is None  # beyond it
    naive = read_at.replace(tzinfo=None)  # a naive read time is UTC, never the machine's local time
    assert entry_date({"published_parsed": _st(datetime(2026, 11, 29, 11, 0))}, read_at=naive) is not None
    assert entry_date({"published_parsed": _st(datetime(2026, 11, 29, 13, 0))}, read_at=naive) is None
    old = datetime(1999, 1, 1)
    assert entry_date({"published_parsed": _st(old)}, read_at=read_at) == old  # an old date is a claim the flag labels


def test_the_articles_own_date_always_wins():
    assert article_date(OWN_DATE, FEED_DATE) == (OWN_DATE, ORIGIN_ARTICLE)
    assert article_date(None, FEED_DATE) == (FEED_DATE, ORIGIN_FEED)
    assert article_date(None, None) == (None, None)
    assert feed_date_fields(OWN_DATE, FEED_DATE) == {"feed_entry_published_at": None, "date_origin": "article"}
    assert feed_date_fields(None, FEED_DATE) == {"feed_entry_published_at": FEED_DATE.isoformat(), "date_origin": "feed"}
    assert feed_date_fields(None, None) == {"feed_entry_published_at": None, "date_origin": None}


# --- the write path --------------------------------------------------------------------------------------------------------------


def test_the_feed_walk_keeps_the_entry_date_only_for_a_page_with_no_date_of_its_own(db, source, tmp_path):
    s = _Session()
    s.feed(f"{G}/feed.xml", [
        (f"{G}/undated", "Thu, 19 Nov 2026 22:15:00 GMT"),
        (f"{G}/dated", "Thu, 19 Nov 2026 22:15:00 GMT"),
        (f"{G}/nodate", None),
    ])
    s.page(f"{G}/undated", "Undated page")
    s.page(f"{G}/dated", "Dated page", own_date=OWN_DATE)
    s.page(f"{G}/nodate", "Neither")
    tally = _bounded(lambda: ingest_source(db, source, fetcher=_fetcher(tmp_path, s)))
    assert tally["stored"] == 3, tally
    got = {a.url: (a.published_at, a.feed_entry_published_at) for a in db.query(Article)}
    assert got[f"{G}/undated"] == (None, FEED_DATE)  # the feed's date, in its own column, never in published_at
    assert got[f"{G}/dated"] == (OWN_DATE, None)  # its own date wins and the feed's is not kept
    assert got[f"{G}/nodate"] == (None, None)


def test_the_collectors_batch_keeps_it_too(db, source, tmp_path):
    s = _Session()
    s.page(f"{G}/b1", "Batched undated")
    s.page(f"{G}/b2", "Batched dated", own_date=OWN_DATE)
    batch = ArticleBatch(db, source, size=10)
    f = _fetcher(tmp_path, s)
    for url in (f"{G}/b1", f"{G}/b2"):
        out = _bounded(lambda url=url: ingest_url(db, source, url, fetcher=f, batch=batch, feed_entry_date=FEED_DATE))
        assert out.result is IngestResult.STAGED, out
    batch.flush()
    got = {a.url: (a.published_at, a.feed_entry_published_at) for a in db.query(Article)}
    assert got == {f"{G}/b1": (None, FEED_DATE), f"{G}/b2": (OWN_DATE, None)}


def test_a_page_stored_without_a_feed_entry_keeps_none(db, source, tmp_path):
    s = _Session()
    s.page(f"{G}/manual", "Added by hand")
    _bounded(lambda: ingest_url(db, source, f"{G}/manual", fetcher=_fetcher(tmp_path, s)))
    assert db.query(Article.feed_entry_published_at).scalar() is None


# --- where it is shown -----------------------------------------------------------------------------------------------------------


_BODIES = (
    "Harbour workers voted on a new contract after a long night of talks.",
    "A comet passed close enough to be seen from the northern hills.",
    "The library reopened with a reading room for the city's archives.",
)


def _store(tmp_path):
    engine = app_sqlite_engine(tmp_path / "v.db", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Good News", domain="goodnews.org", status="qualified"))
        s.commit()
        for i, (own, feed) in enumerate([(None, FEED_DATE), (OWN_DATE, None), (None, None)], start=1):
            s.add(
                Article(
                    url=f"{G}/{i}", canonical_url=f"{G}/{i}", source_id=1, title=f"Story {i}", content=_BODIES[i - 1],
                    hash=f"h{i}", language="en", created_at=datetime.now(UTC), published_at=own,
                    feed_entry_published_at=feed,
                )
            )
        s.commit()
    return Sess


@pytest.fixture()
def client(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    Sess = _store(tmp_path)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


_EXPECTED = {
    1: (None, FEED_DATE.isoformat(), "feed"),
    2: (OWN_DATE.isoformat(), None, "article"),
    3: (None, None, None),
}


def _triples(rows):
    return {r["id"]: (r["published_at"], r["feed_entry_published_at"], r["date_origin"]) for r in rows}


def test_the_reader_shows_the_feeds_date_flagged_with_why_on_hover(client):
    from html import escape

    body = client.get("/api/articles/1/view").text
    assert (
        f"<span>Published</span><b>2026-11-19 <span class='muted feed-date' title='{escape(FEED_DATE_HOVER)}'>"
        f"· <span>{escape(FEED_DATE_LABEL)}</span></span></b>"
    ) in body
    own = client.get("/api/articles/2/view").text
    assert "<span>Published</span><b>2026-11-01</b>" in own and FEED_DATE_LABEL not in own
    neither = client.get("/api/articles/3/view").text
    assert "<span>Published</span>" not in neither and "feed-date" not in neither


def test_the_api_rows_and_the_home_feed_cards_carry_it(client):
    assert _triples(client.get("/api/articles?limit=10").json()["results"]) == _EXPECTED
    assert _triples(client.get("/api/feed?order=recent&limit=10").json()["results"]) == _EXPECTED


def test_both_exports_carry_it_and_the_csv_keeps_every_earlier_column_in_place(client):
    r = client.get("/api/articles/export?format=csv")
    assert r.status_code == 200, r.text
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][-2:] == ["Fetched From Host", "Feed Entry Date (no date of its own)"]
    assert rows[0][:9] == ["ID", "Title", "URL", "Canonical URL", "Source", "Published At", "Language", "Content", "Hash"]
    assert {row[0]: (row[5], row[-1]) for row in rows[1:]} == {
        "1": ("", FEED_DATE.isoformat()), "2": (OWN_DATE.isoformat(), ""), "3": ("", ""),
    }
    j = client.get("/api/articles/export?format=json").json()
    assert _triples(j["articles"]) == _EXPECTED


@pytest.mark.parametrize("collapse", [True, False])
def test_the_home_latest_panel_carries_it(tmp_path, collapse):
    from src.analytics.latest import latest_articles

    with _store(tmp_path)() as s:
        out = latest_articles(s, collapse=collapse, facets=False)
    assert _triples(out["articles"]) == _EXPECTED


def test_the_briefing_evidence_audit_carries_it(tmp_path):
    from src.briefing import card_audit

    with _store(tmp_path)() as s:
        out = card_audit._resolve_articles(
            s, [1, 2, 3], depth="summary", excerpt_chars=0, max_linked_rows=5, shown_ids=[1, 2, 3]
        )
    assert _triples(out["items"]) == _EXPECTED


def test_the_reader_words_match_the_spa_and_are_keyed_in_every_locale():
    core = (STATIC / "app-core.js").read_text(encoding="utf-8")
    assert f't("{FEED_DATE_HOVER}")' in core.replace("\\'", "'")
    assert f't("{FEED_DATE_LABEL}")' in core
    files = sorted((STATIC / "locales").glob("*.json"))
    assert len(files) == 12
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for key in (FEED_DATE_LABEL, FEED_DATE_HOVER):
            assert data.get(key), (f.name, key)
            assert f.stem == "en" or data[key] != key, (f.name, key)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_spa_helper_runs_as_real_code():
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "feed_entry_date_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# Every SPA row that prints the date of an article from /api/articles or /api/feed draws it through the one helper.
_SPA_ROWS = [
    ("app-analysis.js", r"\+ `\$\{ooArticleDateHtml\(a\)\} · \$\{esc\(TFW\(\"\{n\} words\""),
    ("app-analysis.js", r'\+ `<td class="muted">\$\{ooArticleDateHtml\(a\)\}</td>`'),
    ("app-analysis.js", r'<td class="muted">\$\{ooArticleDateHtml\(a\)\}</td>\n\s*<td>\$\{ooLangCell\(a\.language\)\}'),
    ("app-analysis.js", r'\$\{ooArticleDateHtml\(a\) \|\| esc\(t\("undated"\)\)\}'),
    ("app-home.js", r"ooFetchedOffSiteNote\(a\), ooArticleDateHtml\(a\)\]"),
    ("app-home.js", r"const when = ooArticleDateHtml\(a\);"),
]


@pytest.mark.parametrize(("module", "pattern"), _SPA_ROWS)
def test_each_spa_row_draws_the_date_through_the_helper(module, pattern):
    assert re.search(pattern, (STATIC / module).read_text(encoding="utf-8")), (module, pattern)


def test_the_helper_is_declared_once_across_the_spa():
    n = sum(f.read_text(encoding="utf-8").count("function ooArticleDateHtml(") for f in STATIC.glob("*.js"))
    assert n == 1


def test_no_feed_date_is_ever_written_into_published_at():
    """The safe way round, by construction: the write path never puts the feed's date in published_at."""
    src = (ROOT / "src" / "ingest" / "pipeline.py").read_text(encoding="utf-8")
    batch = (ROOT / "src" / "ingest" / "batch.py").read_text(encoding="utf-8")
    assert "published_at=doc.published_at," in src and "published_at=staged.published_at," in batch
    for text_ in (src, batch):
        assert not re.search(r"(?<![a-z_])published_at\s*=\s*(feed|staged\.feed)", text_)
    assert "feed_date = feed_entry_date if doc.published_at is None else None" in src


# --- an older store ---------------------------------------------------------------------------------------------------------------


def test_the_boot_self_heal_adds_the_column_with_nothing_backfilled():
    eng = app_sqlite_engine(":memory:", future=True)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE articles (id INTEGER PRIMARY KEY, hash VARCHAR(64), published_at DATETIME)"))
        c.execute(text("INSERT INTO articles (id, hash) VALUES (1, 'h')"))
    assert ensure_article_feed_entry_date_column(eng) == ["feed_entry_published_at"]
    with eng.begin() as c:
        assert c.execute(text("SELECT feed_entry_published_at FROM articles WHERE id = 1")).scalar() is None
    assert ensure_article_feed_entry_date_column(eng) == []  # idempotent


def test_the_boot_path_runs_the_self_heal():
    for rel, fn in (("src/database/session.py", "init_db"), ("src/testing/scale_bench.py", "_run_init_sequence")):
        body = python_function_source((ROOT / rel).read_text(encoding="utf-8"), fn)
        assert "ensure_article_feed_entry_date_column(engine)" in body, rel


def test_the_migration_is_one_add_column_and_goes_down_without_rebuilding_the_articles_table(tmp_path):
    from alembic import command

    from src.database.migrate import _alembic_config

    mig = (ROOT / "migrations" / "versions" / "c2f6a8e4d1b7_article_feed_entry_date.py").read_text(encoding="utf-8")
    upgrade = python_function_source(mig, "upgrade")
    assert upgrade.count("op.add_column(") == 1 and "nullable=True" in upgrade
    assert "execute(" not in upgrade and "batch_alter_table(" not in mig  # no backfill, no rebuild

    engine = app_sqlite_engine(tmp_path / "m.db", future=True)
    Base.metadata.create_all(engine)

    def shape(c):
        trig = {r[0] for r in c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='articles'")}
        idx = {r[0] for r in c.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='articles' AND name NOT LIKE 'sqlite_%'")}
        cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(articles)")}
        return trig, idx, cols

    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE trig_log (n INTEGER)")
        c.exec_driver_sql("CREATE TRIGGER art_probe_ai AFTER INSERT ON articles BEGIN INSERT INTO trig_log VALUES (new.id); END")
        c.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        c.exec_driver_sql("INSERT INTO alembic_version VALUES ('c2f6a8e4d1b7')")
        trig0, idx0, cols0 = shape(c)
    assert "art_probe_ai" in trig0 and "feed_entry_published_at" in cols0
    try:
        for target, has_column in (("c4f1a9e27b53", False), ("c2f6a8e4d1b7", True)):
            with engine.begin() as conn:
                cfg = _alembic_config()
                cfg.attributes["connection"] = conn
                (command.downgrade if not has_column else command.upgrade)(cfg, target)
            with engine.begin() as c:
                trig, idx, cols = shape(c)
            assert (trig, idx) == (trig0, idx0), target
            assert ("feed_entry_published_at" in cols) is has_column, target
    finally:
        engine.dispose()


# --- a backup merge ------------------------------------------------------------------------------------------------------------------


def _side(path, own, feed, h="H1"):
    engine = app_sqlite_engine(path, future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        s.add(Source(name="Good News", domain="goodnews.org"))
        s.flush()
        s.add(Article(url=f"{G}/{h}", canonical_url=f"{G}/{h}", source_id=1, title="T", content=f"Wire story {h}.",
                      hash=h, published_at=own, feed_entry_published_at=feed))
        s.commit()
    engine.dispose()


def _merge(staged, working):
    from src.backup.merge import merge_corpus

    meta = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0", "alembic_rev": "head",
            "manifest": None}
    counts, _ = merge_corpus(staged, working, meta)
    engine = app_sqlite_engine(working, future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as s:
            return counts, {a.hash: (a.published_at, a.feed_entry_published_at) for a in s.query(Article).all()}
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("local", "incoming", "after"),
    [
        ((None, None), (None, FEED_DATE), (None, FEED_DATE)),  # neither has its own date: the feed's date is adopted
        ((None, OWN_DATE), (None, FEED_DATE), (None, OWN_DATE)),  # a recorded feed date is never replaced
        ((OWN_DATE, None), (None, FEED_DATE), (OWN_DATE, None)),  # the local article has its own date: nothing is adopted
        ((None, None), (OWN_DATE, None), (OWN_DATE, None)),  # the incoming one has its own: that is adopted, not a feed date
        ((None, FEED_DATE), (OWN_DATE, None), (OWN_DATE, FEED_DATE)),  # both kept; the reading prefers the article's own
    ],
)
def test_a_merge_adopts_the_feed_date_onto_a_duplicate_only_when_neither_has_its_own(tmp_path, local, incoming, after):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _side(working, *local)
    _side(staged, *incoming)
    counts, got = _merge(staged, working)
    assert counts["articles"]["duplicate"] == 1
    assert got == {"H1": after}
    # The per-group count agrees with what the UPDATE did: the feed's date is counted only where it was adopted.
    adopted_feed = local[1] is None and local[0] is None and incoming[0] is None and incoming[1] is not None
    by_column = counts["_article_metadata"]["by_column"]
    assert by_column.get("feed_entry_published_at", 0) == (1 if adopted_feed else 0), counts["_article_metadata"]


def test_a_merge_carries_the_feed_date_of_a_new_article(tmp_path):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _side(working, OWN_DATE, None, h="H1")
    _side(staged, None, FEED_DATE, h="H2")
    counts, got = _merge(staged, working)
    assert counts["articles"]["new"] == 1
    assert got == {"H1": (OWN_DATE, None), "H2": (None, FEED_DATE)}


def test_a_backup_made_before_the_column_restores_with_null(tmp_path):
    """The staged copy goes through the migration chain first (prepare_staged_corpus), which adds the column empty."""
    from src.database.migrate import file_revision, upgrade_database_file

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _side(working, OWN_DATE, None, h="H1")
    _side(staged, None, None, h="H2")
    con_engine = app_sqlite_engine(staged, future=True)
    with con_engine.begin() as c:
        c.exec_driver_sql("ALTER TABLE articles DROP COLUMN feed_entry_published_at")
        c.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        c.exec_driver_sql("INSERT INTO alembic_version VALUES ('b8d4f2a6c1e9')")
    con_engine.dispose()
    upgrade_database_file(staged)
    assert file_revision(staged) == "c2f6a8e4d1b7"
    counts, got = _merge(staged, working)
    assert counts["articles"]["new"] == 1
    assert got == {"H1": (OWN_DATE, None), "H2": (None, None)}

