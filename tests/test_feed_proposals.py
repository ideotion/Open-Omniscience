"""Feed addresses PROPOSED for feed-less sources (row 463, R852).

What is pinned here: a proposal is found without a request (the module imports no fetcher and no network library, and a
run with every socket call refused still records one); the untrusted page is checked before anything is recorded
(scheme, user info, length, internal names and addresses, at most three per page); a proposal is never an ``rss_url``
change until one click accepts ONE proposal; a dismissed address is never proposed again; same-domain proposals match
the exact host only (``www.`` ignored, a subdomain is another site) and name their sibling; the crawl reads the start
page of a feed-less source only, and never stages a row between two fetches.
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from tests._app_engine import app_sqlite_engine

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "ingest" / "feed_proposals.py"


@pytest.fixture
def db(tmp_path):
    from src.database.models import Base

    engine = app_sqlite_engine(tmp_path / "fp.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _src(db, name, domain, rss=None):
    from src.database.models import Source

    s = Source(name=name, domain=domain, rss_url=rss)
    db.add(s)
    db.commit()
    return s


def _page(*hrefs, kind="application/rss+xml"):
    links = "".join(f'<link rel="alternate" type="{kind}" href="{h}">' for h in hrefs)
    return f"<html><head>{links}</head><body>x</body></html>"


# ---------------------------------------------------------------- the address check (writing only, never resolved)


@pytest.mark.parametrize("url,reason", [
    ("ftp://example.com/feed", "scheme"),
    ("javascript:alert(1)", "scheme"),
    ("https://user:pw@example.com/feed", "userinfo"),
    ("https://example.com/" + "a" * 600, "length"),
    ("http://127.0.0.1/feed", "internal_address"),
    ("http://10.1.2.3/feed", "internal_address"),
    ("http://169.254.169.254/latest", "internal_address"),
    ("http://[::1]/feed", "internal_address"),
    ("http://localhost/feed", "internal_name"),
    ("http://intranet/feed", "internal_name"),
    ("http://printer.local/feed", "internal_name"),
    ("http://db.internal/feed", "internal_name"),
    ("http://router.lan/feed", "internal_name"),
])
def test_an_address_the_app_will_not_record(url, reason):
    from src.ingest.feed_proposals import address_refusal

    assert address_refusal(url) == reason


@pytest.mark.parametrize("url", ["https://example.com/feed.xml", "http://news.example.org/rss", "https://8.8.8.8/rss"])
def test_a_public_address_passes(url):
    from src.ingest.feed_proposals import address_refusal

    assert address_refusal(url) is None


def test_the_check_never_resolves_a_name(monkeypatch):
    from src.ingest.feed_proposals import address_refusal

    def _refuse(*a, **k):
        raise AssertionError("address_refusal resolved a name")

    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
    monkeypatch.setattr(socket, "gethostbyname", _refuse)
    assert address_refusal("https://example.com/feed") is None


# ---------------------------------------------------------------- from a page the crawl already read


def test_links_from_page_caps_at_three_and_drops_refused_ones(db):
    from src.ingest.feed_proposals import MAX_PER_PAGE, links_from_page

    s = _src(db, "Ex", "example.com")
    html = _page("http://127.0.0.1/x", "/feed1", "/feed2", "https://u:p@example.com/f", "/feed3", "/feed4")
    out = links_from_page(s, html, "https://example.com/")
    assert MAX_PER_PAGE == 3
    assert out == ["https://example.com/feed1", "https://example.com/feed2", "https://example.com/feed3"]


def test_links_from_page_is_for_a_feed_less_source_only(db):
    from src.ingest.feed_proposals import links_from_page

    s = _src(db, "Ex", "example.com", rss="https://example.com/rss")
    assert links_from_page(s, _page("/feed"), "https://example.com/") == []


def test_links_from_page_never_raises(db):
    from src.ingest.feed_proposals import links_from_page

    s = _src(db, "Ex", "example.com")
    assert links_from_page(s, "<link rel=alternate type='application/rss+xml' href='http://[bad'>", "https://example.com/") == []
    assert links_from_page(s, None, "https://example.com/") == []  # type: ignore[arg-type]


def test_record_links_records_proposals_and_never_repeats_a_dismissed_one(db):
    from src.database.models import FeedProposal, Source
    from src.ingest import feed_proposals as fp

    s = _src(db, "Ex", "example.com")
    assert fp.record_links(db, s.id, ["https://example.com/feed"]) == 1
    db.commit()
    p = db.query(FeedProposal).one()
    assert (p.origin, p.status, p.host) == ("crawl_page", "proposed", "example.com")
    assert db.get(Source, s.id).rss_url is None, "a proposal is never an rss_url change"
    fp.dismiss(db, p.id)
    db.commit()
    assert fp.record_links(db, s.id, ["https://example.com/feed"]) == 0
    assert fp.counts(db) == {"proposed": 0, "accepted": 0, "dismissed": 1}


def test_record_links_checks_and_caps_again(db):
    from src.ingest import feed_proposals as fp

    s = _src(db, "Ex", "example.com")
    urls = ["http://localhost/a", "https://example.com/1", "https://example.com/2", "https://example.com/3"]
    assert fp.record_links(db, s.id, urls) == 2  # the first three only, of which one is refused


# ---------------------------------------------------------------- same domain


def test_same_domain_matches_the_exact_host_and_names_the_sibling(db):
    from src.database.models import FeedProposal
    from src.ingest import feed_proposals as fp

    fed = _src(db, "Fed", "www.example.com", rss="https://example.com/rss")
    bare = _src(db, "Bare", "example.com")
    sub = _src(db, "Edition", "en.example.com")
    other = _src(db, "Other", "example.org")
    assert fp.record_same_domain(db) == 1
    db.commit()
    p = db.query(FeedProposal).one()
    assert (p.source_id, p.sibling_source_id, p.origin, p.url) == (bare.id, fed.id, "same_domain", "https://example.com/rss")
    assert sub.id != p.source_id and other.id != p.source_id
    assert fp.record_same_domain(db) == 0, "proposed once"


def test_same_domain_does_not_propose_a_refused_address(db):
    from src.ingest import feed_proposals as fp

    _src(db, "Fed", "example.com", rss="http://localhost/rss")
    _src(db, "Bare", "www.example.com")
    assert fp.record_same_domain(db) == 0


# ---------------------------------------------------------------- the click


def test_accept_sets_the_feed_and_fetches_nothing(db, monkeypatch):
    from src.database.models import Source
    from src.ingest import feed_proposals as fp

    s = _src(db, "Ex", "example.com")
    fp.record_links(db, s.id, ["https://example.com/feed"])
    db.commit()
    pid = fp.counts(db) and db.execute(__import__("sqlalchemy").text("select id from feed_proposals")).scalar_one()

    def _refuse(*a, **k):
        raise AssertionError("accept made a network call")

    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    p = fp.accept(db, pid)
    db.commit()
    assert p.status == "accepted" and p.decided_at is not None
    assert db.get(Source, s.id).rss_url == "https://example.com/feed"
    r = fp.accept(db, pid)
    assert isinstance(r, fp.Refusal) and r.code == 409


def test_accept_leaves_a_source_that_has_a_feed_by_now(db):
    from src.database.models import FeedProposal, Source
    from src.ingest import feed_proposals as fp

    s = _src(db, "Ex", "example.com")
    fp.record_links(db, s.id, ["https://example.com/feed"])
    db.commit()
    db.get(Source, s.id).rss_url = "https://example.com/own"
    db.commit()
    pid = db.query(FeedProposal).one().id
    r = fp.accept(db, pid)
    assert isinstance(r, fp.Refusal) and r.code == 409
    assert db.get(Source, s.id).rss_url == "https://example.com/own"


def test_accept_checks_the_address_again(db):
    from src.database.models import FeedProposal
    from src.ingest import feed_proposals as fp

    s = _src(db, "Ex", "example.com")
    db.add(FeedProposal(source_id=s.id, url="http://127.0.0.1/feed", host="127.0.0.1", origin="crawl_page"))
    db.commit()
    r = fp.accept(db, db.query(FeedProposal).one().id)
    assert isinstance(r, fp.Refusal) and r.code == 422


def test_missing_proposal_is_a_404(db):
    from src.ingest import feed_proposals as fp

    for fn in (fp.accept, fp.dismiss):
        r = fn(db, 999)
        assert isinstance(r, fp.Refusal) and r.code == 404


# ---------------------------------------------------------------- the API


def test_the_api_lists_says_another_host_and_accepts_one(tmp_path):
    from fastapi.testclient import TestClient

    from src.database.models import Base, FeedProposal, Source
    from src.database.session import get_db

    engine = app_sqlite_engine(tmp_path / "api.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        src = Source(name="Ex", domain="example.com")
        s.add(src)
        s.commit()
        s.add(FeedProposal(source_id=src.id, url="https://feeds.example.net/x", host="feeds.example.net", origin="crawl_page"))
        s.add(FeedProposal(source_id=src.id, url="https://www.example.com/rss", host="www.example.com", origin="crawl_page"))
        s.commit()
        sid = src.id

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        c = TestClient(app)
        r = c.get("/api/sources/feed-proposals").json()
        assert r["counts"] == {"proposed": 2, "accepted": 0, "dismissed": 0}
        by_url = {p["url"]: p for p in r["proposals"]}
        assert by_url["https://feeds.example.net/x"]["other_host"] is True
        assert by_url["https://www.example.com/rss"]["other_host"] is False
        pid = by_url["https://www.example.com/rss"]["id"]
        a = c.post(f"/api/sources/feed-proposals/{pid}/accept")
        assert a.status_code == 200, a.text
        assert a.json()["source_name"] == "Ex"
        again = c.post(f"/api/sources/feed-proposals/{pid}/accept")
        assert again.status_code == 409
        other = by_url["https://feeds.example.net/x"]["id"]
        assert c.post(f"/api/sources/feed-proposals/{other}/accept").status_code == 409  # the source has a feed now
        assert c.post(f"/api/sources/feed-proposals/{other}/dismiss").status_code == 200
    finally:
        app.dependency_overrides.clear()
    with Sess() as s:
        assert s.get(Source, sid).rss_url == "https://www.example.com/rss"
    engine.dispose()


# ---------------------------------------------------------------- the crawl hook


class _Fetched:
    def __init__(self, url, html):
        self.url = url
        self.final_url = url
        self.content = html
        self.status_code = 200
        self.headers = {"content-type": "text/html"}


class _Fetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, url, **kw):
        self.calls.append(url)
        from src.ingest import FetchError

        if url not in self.pages:
            raise FetchError("not here")
        return _Fetched(url, self.pages[url])


def _crawl(db, source, pages, monkeypatch):
    from src.ingest import crawl as C

    dup = next(r for r in C.IngestResult if r is not C.IngestResult.STAGED)
    monkeypatch.setattr(C, "store_fetched", lambda *a, **k: type("O", (), {"result": dup})())
    fetcher = _Fetcher(pages)
    rep = C.crawl_source(db, source, fetcher=fetcher, config=C.CrawlConfig(max_depth=1, max_pages=3),
                         start_url="https://example.com/")
    return rep, fetcher


def test_the_crawl_holds_start_page_links_in_memory_and_stages_nothing(db, monkeypatch):
    s = _src(db, "Ex", "example.com")
    pages = {"https://example.com/": _page("/feed") + '<a href="/a1">a</a>',
             "https://example.com/a1": _page("/other-feed")}
    rep, fetcher = _crawl(db, s, pages, monkeypatch)
    assert rep.feed_links == ["https://example.com/feed"], "the start page only (depth 0)"
    assert not db.new, "no row is staged between two fetches"
    assert not any("feed" in u for u in fetcher.calls), "a proposed feed is never fetched by the crawl"


def test_the_crawl_proposes_nothing_for_a_source_with_a_feed(db, monkeypatch):
    s = _src(db, "Ex", "example.com", rss="https://example.com/rss")
    rep, _ = _crawl(db, s, {"https://example.com/": _page("/feed")}, monkeypatch)
    assert rep.feed_links == []


# ---------------------------------------------------------------- the source guard: this path cannot issue a request

_NETWORK_MODULES = {
    "requests", "httpx", "urllib3", "aiohttp", "socket", "http", "ssl", "ftplib", "smtplib", "imaplib", "poplib",
    "telnetlib", "urllib.request", "http.client", "dns", "pycurl",
}
_ALLOWED_FROM = {
    "src.ingest": {"_carries_userinfo", "_unsafe_url_text"},
    "src.ingest.feed_find": {"feed_links_in_page"},
    "src.ingest.ssrf_guard": {"is_blocked_ip"},
    "src.database.models": {"FeedProposal", "Source"},
}


def test_the_module_imports_no_fetcher_and_no_network_library():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                assert a.name not in _NETWORK_MODULES and top not in _NETWORK_MODULES, f"imports {a.name}"
                assert not a.name.startswith("src."), f"imports a whole package {a.name}: name what is used"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod not in _NETWORK_MODULES and mod.split(".")[0] not in _NETWORK_MODULES, f"imports from {mod}"
            if mod.startswith("src."):
                names = {a.name for a in node.names}
                assert mod in _ALLOWED_FROM, f"imports from {mod}: not a module this path may use"
                assert names <= _ALLOWED_FROM[mod], f"imports {names - _ALLOWED_FROM[mod]} from {mod}"
        elif isinstance(node, ast.Attribute):
            assert node.attr not in {"fetch", "urlopen", "request", "connect"}, f"calls .{node.attr}"
        elif isinstance(node, ast.Name):
            assert "Fetcher" not in node.id, f"names {node.id}"


def test_the_discovery_path_runs_with_every_socket_call_refused(db, monkeypatch):
    from src.ingest import EthicalFetcher
    from src.ingest import feed_proposals as fp

    def _refuse(*a, **k):
        raise AssertionError("the discovery path issued a request")

    for name in ("getaddrinfo", "create_connection", "gethostbyname"):
        monkeypatch.setattr(socket, name, _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(EthicalFetcher, "fetch", _refuse)
    s = _src(db, "Ex", "example.com")
    _src(db, "Fed", "www.example.org", rss="https://example.org/rss")
    _src(db, "Bare", "example.org")
    urls = fp.links_from_page(s, _page("https://example.com/feed", "https://feeds.example.net/x"), "https://example.com/")
    assert fp.record_links(db, s.id, urls) == 2
    assert fp.record_same_domain(db) == 1
    db.commit()
    pid = db.execute(__import__("sqlalchemy").text("select id from feed_proposals order by id")).scalars().first()
    fp.accept(db, pid)
    db.commit()


def test_backup_merge_lists_the_table():
    from src.backup.merge import _MERGE_NOT_CARRIED

    assert "feed_proposals" in _MERGE_NOT_CARRIED
