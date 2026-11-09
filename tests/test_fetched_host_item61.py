"""Queue item 61: where an article was actually fetched from is recorded and shown beside the source's credit.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A feed item's link is followed wherever it redirects (feeds stay unscoped, R635), and the article is credited to the source.
Before this, the stored ``url`` was the address ASKED for, so nothing said the page came from another site.
``Article.fetched_host`` now holds the host of the address the fetch ENDED on, after its redirects.

What is pinned here:
- the page fetch, run through the real ``EthicalFetcher`` over an in-memory session, the real ``ingest_url`` and the real
  per-source batch, records the host of the final address;
- the API row, the Home feed's cards, the reader, both exports and the briefing's evidence audit carry it, beside the source;
- a backup merge carries it on a new article and adopts it onto a duplicate that never recorded one, never over one it did;
- the SPA says "fetched from <host>" beside the source on every row it draws from ``/api/articles`` and ``/api/feed`` (the helper run as real code
  by ``tests/fetched_host_node_test.js``, and each of those rows checked to call it);
- the same-site test that says "another site" gives the crawl's own answers;
- the boot self-heal adds the column to an older store, with nothing backfilled.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.maintenance import ensure_article_fetched_host_column
from src.database.models import Article, Base, Source
from src.ingest import EthicalFetcher
from src.ingest.batch import ArticleBatch
from src.ingest.crawl import _off_site, _registrable_host
from src.ingest.pipeline import IngestResult, ingest_url
from src.utils.url_utils import fetched_host, off_the_source_site

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "static"
G = "https://good.example"
OTHER = "https://other.example"
_ALLOW_ALL = "User-agent: *\nAllow: /\n"


def _html(title: str) -> str:
    body = ("A plain page about a plain subject, written out at some length. " * 30).strip()
    return f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1><p>{body}</p></article></body></html>"


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
        self.fetched: list[str] = []

    def page(self, url, title="Page"):
        self.routes[url] = (200, _html(title), {"Content-Type": "text/html"})

    def redirect(self, url, location, *, status=302):
        self.routes[url] = (status, "", {"Location": location, "Content-Type": "text/html"})

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        self.fetched.append(url)
        status, body, headers = self.routes.get(url, (404, "not found", {"Content-Type": "text/plain"}))
        return _Resp(status, body, dict(headers), url)


def _fetcher(tmp_path, session) -> EthicalFetcher:
    return EthicalFetcher(
        min_interval_s=0.0, session=session, robots_cache_path=tmp_path / "robots_cache.json", retry_backoff_s=0,
        max_retries=0,
    )


def _bounded(fn, seconds: float = 10.0):
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
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Good News", domain="good.example", language="en", enabled=True))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


# --- the fetch records where it ended --------------------------------------------------------------------------------------------


def test_a_feed_item_redirected_to_another_site_records_that_site(db, source, tmp_path):
    s = _Session()
    s.redirect(f"{G}/item", f"{OTHER}/story", status=301)
    s.page(f"{OTHER}/story", "Elsewhere")
    out = _bounded(lambda: ingest_url(db, source, f"{G}/item", fetcher=_fetcher(tmp_path, s)))
    assert out.result is IngestResult.STORED, out
    art = db.query(Article).one()
    assert art.url == f"{G}/item"  # the address asked for is kept as it was
    assert art.fetched_host == "other.example"  # ... and the host the bytes came from beside it
    assert art.source_id == source.id


def test_a_page_fetched_from_its_own_address_records_its_host(db, source, tmp_path):
    s = _Session()
    s.page(f"{G}/plain", "Here")
    _bounded(lambda: ingest_url(db, source, f"{G}/plain", fetcher=_fetcher(tmp_path, s)))
    assert db.query(Article).one().fetched_host == "good.example"


def test_a_redirect_through_a_relay_to_the_source_site_records_the_source_site(db, source, tmp_path):
    """The usual feed relay: the item's link is another host, and the redirect lands on the source's own site."""
    s = _Session()
    s.redirect("https://relay.example/r/1", f"{G}/landed", status=302)
    s.page(f"{G}/landed", "Landed")
    _bounded(lambda: ingest_url(db, source, "https://relay.example/r/1", fetcher=_fetcher(tmp_path, s)))
    art = db.query(Article).one()
    assert art.url == "https://relay.example/r/1" and art.fetched_host == "good.example"
    assert off_the_source_site(art.fetched_host, source.domain) is False


def test_the_collectors_batch_records_it_too(db, source, tmp_path):
    s = _Session()
    s.redirect(f"{G}/b1", f"{OTHER}/b1", status=301)
    s.page(f"{OTHER}/b1", "Batched elsewhere")
    s.page(f"{G}/b2", "Batched here")
    batch = ArticleBatch(db, source, size=10)
    f = _fetcher(tmp_path, s)
    for url in (f"{G}/b1", f"{G}/b2"):
        out = _bounded(lambda url=url: ingest_url(db, source, url, fetcher=f, batch=batch))
        assert out.result is IngestResult.STAGED, out
    batch.flush()
    hosts = {a.url: a.fetched_host for a in db.query(Article)}
    assert hosts == {f"{G}/b1": "other.example", f"{G}/b2": "good.example"}


# --- the host, read from the final address ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://u:p@WWW.Good.Example:8443/x?q=1#f", "www.good.example"),  # no login, no port, lower-cased
        ("http://[2001:db8::1]:8080/a", "2001:db8::1"),  # an IPv6 literal without its brackets
        ("https://good.example./a", "good.example."),  # a trailing dot stays, as in the fetcher's host key
        ("/relative/only", None),
        ("", None),
        (None, None),
        ("http://[not-closed/a", None),  # unreadable: nothing names a host
    ],
)
def test_fetched_host_reads_the_host_and_never_raises(url, host):
    assert fetched_host(url) == host


def test_fetched_host_is_cut_to_the_column(db):
    long = "a" * 300 + ".example"
    assert fetched_host(f"https://{long}/") == long[:255]


# --- "another site" is the crawl's own same-site answer --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "domain"),
    [
        ("good.example", "good.example"),
        ("www.good.example", "good.example"),
        ("good.example", "www.good.example"),
        ("GOOD.example", "good.example"),
        ("news.good.example", "good.example"),  # a subdomain is another host to the crawl too
        ("other.example", "good.example"),
        ("xn--bcher-kva.example", "bücher.example"),  # one site in Unicode and punycode (R631)
        ("bücher.example", "xn--bcher-kva.example"),
        ("good.example", "good.example:8443"),  # the port is left out
        ("good.example", "u:p@good.example"),  # so is a login written into the domain
        ("2001:db8::1", "[2001:db8::1]"),
        ("a" * 70 + ".example", "good.example"),  # an ASCII host is compared as written, as the crawl does
        ("☃.example", "☃.example"),  # a host idna refuses is another site even beside the same text: fail closed
        ("ü" + "a" * 63 + ".example", "ü" + "a" * 63 + ".example"),  # a label over 63 that idna refuses, the same
    ],
)
def test_off_the_source_site_agrees_with_the_crawls_same_site_test(host, domain):
    netloc = f"[{host}]" if ":" in host else host
    assert off_the_source_site(host, domain) is _off_site(netloc, _registrable_host(domain))


@pytest.mark.parametrize(("host", "domain"), [(None, "good.example"), ("good.example", None), ("good.example", ""), ("", "x")])
def test_off_the_source_site_says_nothing_when_there_is_nothing_to_compare(host, domain):
    assert off_the_source_site(host, domain) is None


# --- shown beside the source's credit --------------------------------------------------------------------------------------------


def _store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'v.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Good News", domain="good.example", status="qualified"))  # qualified, so the Home feed shows them
        s.commit()
        for i, (host, title) in enumerate(
            [("other.example", "Redirected story"), ("www.good.example", "Home story"), (None, "Older story")], start=1
        ):
            s.add(
                Article(
                    url=f"{G}/{i}", canonical_url=f"{G}/{i}", source_id=1, title=title, content=f"Body {i}.",
                    hash=f"h{i}", language="en", created_at=datetime.now(UTC), fetched_host=host,
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


def test_the_reader_says_beside_the_source_that_the_page_came_from_another_site(client):
    body = client.get("/api/articles/1/view").text
    assert "Good News <span class='muted'>— this page was fetched from another site, other.example</span>" in body
    assert "Fetched from (app-observed, after redirects)" in body
    assert "<code>other.example</code> <span class='muted'>— not the source's site (good.example): the article's link led there</span>" in body


def test_the_reader_shows_an_on_site_host_without_the_warning(client):
    body = client.get("/api/articles/2/view").text
    assert "<code>www.good.example</code>" in body
    assert "fetched from another site" not in body and "not the source's site" not in body


def test_the_reader_shows_no_row_for_an_article_stored_before_the_column(client):
    body = client.get("/api/articles/3/view").text
    assert "Fetched from (app-observed" not in body and "fetched from another site" not in body


def test_the_home_feed_card_carries_it_beside_the_source(client):
    cards = {c["id"]: c for c in client.get("/api/feed?order=recent&limit=10").json()["results"]}
    assert (cards[1]["source"], cards[1]["fetched_host"], cards[1]["fetched_off_site"]) == ("Good News", "other.example", True)
    assert (cards[2]["fetched_host"], cards[2]["fetched_off_site"]) == ("www.good.example", False)
    assert (cards[3]["fetched_host"], cards[3]["fetched_off_site"]) == (None, None)


def test_the_api_row_carries_the_host_and_whether_it_is_another_site(client):
    rows = {r["id"]: r for r in client.get("/api/articles?limit=10").json()["results"]}
    assert (rows[1]["fetched_host"], rows[1]["fetched_off_site"]) == ("other.example", True)
    assert (rows[2]["fetched_host"], rows[2]["fetched_off_site"]) == ("www.good.example", False)
    assert (rows[3]["fetched_host"], rows[3]["fetched_off_site"]) == (None, None)


def test_both_exports_carry_it_and_the_csv_keeps_every_earlier_column_in_place(client):
    r = client.get("/api/articles/export?format=csv")
    assert r.status_code == 200, r.text
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == [
        "ID", "Title", "URL", "Canonical URL", "Source", "Published At", "Language", "Content", "Hash", "Fetched From Host",
    ]
    assert {row[0]: row[-1] for row in rows[1:]} == {"1": "other.example", "2": "www.good.example", "3": ""}
    j = client.get("/api/articles/export?format=json").json()
    assert {a["id"]: a["fetched_host"] for a in j["articles"]} == {1: "other.example", 2: "www.good.example", 3: None}


def test_the_briefing_evidence_audit_carries_it_beside_the_source(tmp_path):
    from src.briefing import card_audit

    Sess = _store(tmp_path)
    with Sess() as s:
        out = card_audit._resolve_articles(
            s, [1, 2, 3], depth="summary", excerpt_chars=0, max_linked_rows=5, shown_ids=[1, 2, 3]
        )
    items = {i["id"]: i for i in out["items"]}
    assert (items[1]["fetched_host"], items[1]["fetched_off_site"]) == ("other.example", True)
    assert (items[2]["fetched_host"], items[2]["fetched_off_site"]) == ("www.good.example", False)
    assert (items[3]["fetched_host"], items[3]["fetched_off_site"]) == (None, None)


# --- an older store ---------------------------------------------------------------------------------------------------------------


def test_the_boot_self_heal_adds_the_column_with_nothing_backfilled():
    eng = create_engine("sqlite:///:memory:", future=True)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE articles (id INTEGER PRIMARY KEY, hash VARCHAR(64))"))
        c.execute(text("INSERT INTO articles (id, hash) VALUES (1, 'h')"))
    assert ensure_article_fetched_host_column(eng) == ["fetched_host"]
    with eng.begin() as c:
        assert c.execute(text("SELECT fetched_host FROM articles WHERE id = 1")).scalar() is None
    assert ensure_article_fetched_host_column(eng) == []  # idempotent



# --- a backup merge ------------------------------------------------------------------------------------------------------------------


def _merged(tmp_path, local_host, incoming_host):
    """The same article (same hash) on both sides of a merge; returns the local row's ``fetched_host`` after it."""
    from src.backup.merge import merge_corpus

    meta = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0", "alembic_rev": "head",
            "manifest": None}
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    for path, host in ((working, local_host), (staged, incoming_host)):
        engine = create_engine(f"sqlite:///{path}", future=True)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine, future=True)() as s:
            s.add(Source(name="Good News", domain="good.example"))
            s.flush()
            s.add(Article(url=f"{G}/a", canonical_url=f"{G}/a", source_id=1, title="T", content="Same body.", hash="H1",
                          fetched_host=host))
            s.commit()
        engine.dispose()
    counts, _ = merge_corpus(staged, working, meta)
    assert counts["articles"]["duplicate"] == 1, "the fixture must exercise the duplicate path"
    engine = create_engine(f"sqlite:///{working}", future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as s:
            return s.query(Article).one().fetched_host
    finally:
        engine.dispose()


def test_a_merge_adopts_the_host_onto_a_duplicate_that_never_recorded_one(tmp_path):
    assert _merged(tmp_path, None, "other.example") == "other.example"


def test_a_merge_never_replaces_a_host_this_install_recorded(tmp_path):
    assert _merged(tmp_path, "good.example", "other.example") == "good.example"


def test_the_boot_path_runs_the_self_heal():
    """init_db and the scale bench both heal an older store (the drift test checks the heal exists, not that boot calls it)."""
    for rel, fn in (("src/database/session.py", "def init_db"), ("src/testing/scale_bench.py", None)):
        text_ = (ROOT / rel).read_text(encoding="utf-8")
        body = text_.split(fn, 1)[1].split("\ndef ", 1)[0] if fn else text_
        assert "ensure_article_fetched_host_column(engine)" in body, rel


# --- the SPA's rows ----------------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_spa_note_runs_as_real_code():
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "fetched_host_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# Every row the SPA draws from /api/articles or /api/feed that credits the source. Each names the source and, in the same expression, the note.
_SPA_ROWS = [
    ("app-analysis.js", r'an-card-meta">\$\{esc\(a\.source \|\| ""\)\}\$\{ooFetchedOffSiteNote\(a\)\}'),
    ("app-analysis.js", r'<td>\$\{esc\(a\.source \|\| ""\)\}\$\{ooFetchedOffSiteNote\(a\)\}</td>'),
    ("app-analysis.js", r"<td>\$\{esc\(a\.source\)\}\$\{ooFetchedOffSiteNote\(a\)\}\$\{_anToneChip\(a\)\}</td>"),
    ("app-analysis.js", r'font-size:12px">\$\{esc\(a\.source \|\| ""\)\}\$\{ooFetchedOffSiteNote\(a\)\} · '),
    ("app-home.js", r'\[esc\(a\.source \|\| ""\) \+ ooFetchedOffSiteNote\(a\), esc\(ooIsoDate'),
    ("app-home.js", r'feed-meta muted">\$\{esc\(a\.source \|\| ""\)\}\$\{ooFetchedOffSiteNote\(a\)\}'),
]


@pytest.mark.parametrize(("module", "pattern"), _SPA_ROWS)
def test_each_spa_row_that_credits_the_source_says_where_the_page_came_from(module, pattern):
    assert re.search(pattern, (STATIC / module).read_text(encoding="utf-8")), (module, pattern)


def test_the_helper_is_declared_once_across_the_spa():
    # Duplicate top-level function names in the shared global scope silently override each other.
    n = sum(f.read_text(encoding="utf-8").count("function ooFetchedOffSiteNote(") for f in STATIC.glob("*.js"))
    assert n == 1


def test_both_strings_are_keyed_in_every_locale():
    keys = (
        "fetched from {host}",
        "The source listed this article, but its link led to another site, and the stored page was fetched from there.",
    )
    files = sorted((STATIC / "locales").glob("*.json"))
    assert len(files) == 12
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for k in keys:
            assert data.get(k), (f.name, k)
        assert "{host}" in data[keys[0]], f.name
