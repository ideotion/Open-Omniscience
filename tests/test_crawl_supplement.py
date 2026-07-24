"""§8 crawl-by-default (2026-07-24 throughput brief, C3): a HYBRID BUDGETED
RUNG, never a mode flip. ``mode="crawl"`` (the explicit whole-source crawl
selector) stays orthogonal; the supplement is a small, bounded crawl sub-pass
over qualified sources every online pass, feedless-first + least-recently-
crawled, riding the housekeeping lane's LOWEST bandwidth-ladder rung.

C7 (same brief) wired consumer (a) into this same rung: when a candidate's
sitemap resolves, its declared article URLs are ingested DIRECTLY instead of
the BFS ``crawl_source`` fallback (see ``test_prefers_sitemap_derived_urls_
over_blind_link_following`` below). Every other test here uses a fake
EthicalFetcher backed by a fully-faked session that declares/serves NO
sitemap (a plain 404 for everything unrouted), so ``discover_sitemap_urls``
honestly finds nothing and the rung falls through to the (still monkeypatched)
``crawl_source`` -- proving the ORIGINAL wiring (candidate selection,
ordering, last_crawled_at stamping, isolation) is unchanged for a source with
no sitemap, without ever touching a real network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import STATUS_QUALIFIED
from src.database.models import Base, Source
from src.ingest import EthicalFetcher
from src.scheduler.runner import (
    _lane_pending_kinds,
    _lane_step_crawl,
    _select_crawl_candidates,
)
from src.scheduler.settings import SchedulerSettings

_ROOT = Path(__file__).resolve().parents[1]


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _Session:
    """A fake requests-like session that 404s everything unrouted -- so
    discover_sitemap_urls always finds nothing declared, letting these tests
    exercise the ORIGINAL crawl_source fallback path unchanged."""

    def __init__(self):
        self.headers = {}
        self._routes: dict[str, _Resp] = {}

    def route(self, url, **kwargs):
        self._routes[url] = _Resp(url=url, **kwargs)

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        if url in self._routes:
            return self._routes[url]
        return _Resp(status_code=404, text="not found", url=url)


def _no_sitemap_fetcher():
    """A real EthicalFetcher over a fully-faked, no-sitemap session -- the
    replacement for the bare ``object()`` placeholder these tests used before
    C7 added a real (fetcher-consulting) pre-step to _lane_step_crawl."""
    return EthicalFetcher(min_interval_s=0.0, session=_Session())


def _engine_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _qualified_source(session, *, domain, rss_url=None, last_crawled_at=None):
    s = Source(
        name=domain, domain=domain, rss_url=rss_url, enabled=True, status=STATUS_QUALIFIED,
        last_crawled_at=last_crawled_at,
    )
    session.add(s)
    session.commit()
    return s


# --------------------------------------------------------------------------- #
# Settings: default ON, budget 0 disables.
# --------------------------------------------------------------------------- #


def test_crawl_supplement_is_on_by_default():
    s = SchedulerSettings()
    assert s.crawl_supplement is True
    assert s.crawl_per_pass > 0
    assert "crawl" in _lane_pending_kinds(s)


def test_zero_budget_disables_the_supplement():
    s = SchedulerSettings(crawl_per_pass=0)
    assert "crawl" not in _lane_pending_kinds(s)


def test_toggle_off_disables_the_supplement_even_with_a_budget():
    s = SchedulerSettings(crawl_supplement=False, crawl_per_pass=5)
    assert "crawl" not in _lane_pending_kinds(s)


def test_settings_roundtrip_persists_both_fields(tmp_path, monkeypatch):
    from src.scheduler import settings as sch

    monkeypatch.setattr(sch, "_settings_path", lambda: tmp_path / "scheduler_settings.json")
    sch.save_settings({"crawl_supplement": False, "crawl_per_pass": 7})
    loaded = sch.load_settings()
    assert loaded.crawl_supplement is False
    assert loaded.crawl_per_pass == 7


def test_crawl_per_pass_is_bounded():
    from src.scheduler.settings import SchedulerSettingsError, save_settings

    try:
        save_settings({"crawl_per_pass": -1})
        raised = False
    except SchedulerSettingsError:
        raised = True
    assert raised


# --------------------------------------------------------------------------- #
# Rotation: feedless-first, least-recently-crawled -- never exclusion.
# --------------------------------------------------------------------------- #


def test_rotation_prefers_feedless_over_feed_carrying():
    session = _engine_session()
    settings = SchedulerSettings()
    feed_src = _qualified_source(session, domain="feed.example", rss_url="https://feed.example/rss")
    feedless_src = _qualified_source(session, domain="feedless.example", rss_url=None)
    order = _select_crawl_candidates(session, settings, 10)
    assert [s.id for s in order] == [feedless_src.id, feed_src.id]


def test_rotation_prefers_never_crawled_then_oldest():
    session = _engine_session()
    settings = SchedulerSettings()
    now = datetime.now(UTC)
    recently = _qualified_source(
        session, domain="recent.example", last_crawled_at=now - timedelta(hours=1)
    )
    long_ago = _qualified_source(
        session, domain="stale.example", last_crawled_at=now - timedelta(days=30)
    )
    never = _qualified_source(session, domain="never.example", last_crawled_at=None)
    order = _select_crawl_candidates(session, settings, 10)
    assert [s.id for s in order] == [never.id, long_ago.id, recently.id]


def test_a_recently_crawled_feed_carrying_source_is_not_reselected_over_budget():
    """NEGATIVE-SPACE: with a tight budget, a feed-carrying source that was
    JUST crawled must not be re-picked this pass while an untouched feedless
    source is waiting -- ordering, never exclusion, but the recent one's
    TURN has not come back around yet."""
    session = _engine_session()
    settings = SchedulerSettings()
    now = datetime.now(UTC)
    recently_crawled = _qualified_source(
        session, domain="recent-feed.example",
        rss_url="https://recent-feed.example/rss", last_crawled_at=now,
    )
    untouched = _qualified_source(session, domain="untouched.example", rss_url=None)
    order = _select_crawl_candidates(session, settings, 1)
    assert [s.id for s in order] == [untouched.id]
    assert recently_crawled.id not in [s.id for s in order]


def test_zero_limit_selects_nothing():
    session = _engine_session()
    _qualified_source(session, domain="a.example")
    assert _select_crawl_candidates(session, SchedulerSettings(), 0) == []


def test_only_qualified_enabled_sources_are_candidates():
    session = _engine_session()
    disabled = Source(name="d", domain="disabled.example", enabled=False, status=STATUS_QUALIFIED)
    unqualified = Source(name="u", domain="unqualified.example", enabled=True, status="unqualified")
    session.add_all([disabled, unqualified])
    session.commit()
    assert _select_crawl_candidates(session, SchedulerSettings(), 10) == []


# --------------------------------------------------------------------------- #
# C7 consumer (a): a source WITH a discoverable sitemap is ingested via its
# declared URLs directly -- crawl_source is never even reached.
# --------------------------------------------------------------------------- #

_URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://sitemap.example/a</loc></url>
  <url><loc>https://sitemap.example/b</loc></url>
</urlset>"""


def _article_html(title, body_sentence):
    body = (body_sentence + " ") * 30
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    )


def test_prefers_sitemap_derived_urls_over_blind_link_following(monkeypatch):
    session = _engine_session()
    settings = SchedulerSettings(crawl_per_pass=1)
    src = _qualified_source(session, domain="sitemap.example")

    fake_session = _Session()
    fake_session.route("https://sitemap.example/robots.txt", status_code=404, text="")
    fake_session.route("https://sitemap.example/sitemap.xml", text=_URLSET_XML, content_type="text/xml")
    fake_session.route(
        "https://sitemap.example/a",
        text=_article_html("Article A", "real news content here"),
    )
    fake_session.route(
        "https://sitemap.example/b",
        text=_article_html("Article B", "more real news content"),
    )
    fetcher = EthicalFetcher(min_interval_s=0.0, session=fake_session)

    crawl_source_called = []
    monkeypatch.setattr(
        "src.ingest.crawl.crawl_source",
        lambda *a, **kw: crawl_source_called.append(True),
    )

    result = _lane_step_crawl(session, fetcher, settings)
    assert crawl_source_called == []  # the BFS fallback was never reached
    assert result["sitemap_urls_ingested"] == 2
    assert result["pages_fetched"] == 0  # this counter is crawl_source's own, untouched here

    from src.database.models import Article, SourceMetadata

    assert session.query(Article).filter_by(source_id=src.id).count() == 2
    meta = session.query(SourceMetadata).filter_by(source_id=src.id).first()
    assert meta is not None and meta.sitemap_url == "https://sitemap.example/sitemap.xml"
    assert src.last_crawled_at is not None


# --------------------------------------------------------------------------- #
# The step: stamps last_crawled_at, isolates one failure, adds no fetch path.
# --------------------------------------------------------------------------- #


def test_step_stamps_last_crawled_at_for_attempted_sources(monkeypatch):
    session = _engine_session()
    settings = SchedulerSettings(crawl_per_pass=2)
    src = _qualified_source(session, domain="a.example")

    class _FakeReport:
        pages_fetched = 3

    calls = []

    def _fake_crawl_source(session_, source, *, fetcher, config):
        calls.append(source.domain)
        return _FakeReport()

    monkeypatch.setattr("src.ingest.crawl.crawl_source", _fake_crawl_source)

    before = src.last_crawled_at
    result = _lane_step_crawl(session, _no_sitemap_fetcher(), settings)
    assert before is None
    assert src.last_crawled_at is not None
    assert calls == ["a.example"]
    assert result == {"sources_crawled": 1, "pages_fetched": 3, "sitemap_urls_ingested": 0}


def test_one_source_failing_does_not_abort_the_rest(monkeypatch):
    session = _engine_session()
    settings = SchedulerSettings(crawl_per_pass=5)
    a = _qualified_source(session, domain="a.example")
    b = _qualified_source(session, domain="b.example")

    class _FakeReport:
        pages_fetched = 1

    def _flaky(session_, source, *, fetcher, config):
        if source.domain == "a.example":
            raise RuntimeError("simulated crawl failure")
        return _FakeReport()

    monkeypatch.setattr("src.ingest.crawl.crawl_source", _flaky)

    result = _lane_step_crawl(session, _no_sitemap_fetcher(), settings)
    assert result["sources_crawled"] == 1  # only b succeeded
    assert a.last_crawled_at is None  # the failed one is NOT stamped -- retried next pass
    assert b.last_crawled_at is not None


def test_the_supplement_uses_a_tight_crawl_config(monkeypatch):
    """The supplement's CrawlConfig is deliberately smaller than the explicit
    whole-source mode="crawl" caps -- never a full crawl every pass."""
    session = _engine_session()
    settings = SchedulerSettings(crawl_per_pass=1, crawl_max_pages=500, crawl_max_depth=6)
    _qualified_source(session, domain="a.example")

    seen_cfg = {}

    class _FakeReport:
        pages_fetched = 0

    def _capture(session_, source, *, fetcher, config):
        seen_cfg["max_pages"] = config.max_pages
        seen_cfg["max_depth"] = config.max_depth
        return _FakeReport()

    monkeypatch.setattr("src.ingest.crawl.crawl_source", _capture)
    _lane_step_crawl(session, _no_sitemap_fetcher(), settings)
    assert seen_cfg["max_pages"] < 500
    assert seen_cfg["max_depth"] < 6


def test_step_calls_only_the_ONE_fetch_paths_no_raw_http():
    """Source-level guard: _lane_step_crawl's body must reference no fetch
    primitive OTHER than crawl_source (the BFS fallback) / ingest_url /
    discover_sitemap_urls (C7's sitemap-preferred path) -- ALL THREE already
    route through the ONE EthicalFetcher; no raw requests/httpx bypass."""
    runner_src = (_ROOT / "src" / "scheduler" / "runner.py").read_text("utf-8")
    step_body = runner_src.split("def _lane_step_crawl(", 1)[1].split("\ndef ", 1)[0]
    assert "crawl_source(" in step_body
    assert "ingest_url(" in step_body
    assert "discover_sitemap_urls(" in step_body
    assert "fetcher.fetch(" not in step_body  # no LITERAL bypass in this function's own body
    assert "requests." not in step_body and "httpx." not in step_body


# --------------------------------------------------------------------------- #
# Wiring guard: settings exist with the ruled defaults/ranges, migration +
# self-heal wired, Source.last_crawled_at column present.
# --------------------------------------------------------------------------- #


def test_scheduler_wiring_and_setting():
    settings_src = (_ROOT / "src" / "scheduler" / "settings.py").read_text("utf-8")
    api_src = (_ROOT / "src" / "api" / "scheduler.py").read_text("utf-8")
    models_src = (_ROOT / "src" / "database" / "models.py").read_text("utf-8")
    maint_src = (_ROOT / "src" / "database" / "maintenance.py").read_text("utf-8")
    session_src = (_ROOT / "src" / "database" / "session.py").read_text("utf-8")

    assert "crawl_supplement: bool = True" in settings_src  # default ON (the ruling)
    assert "crawl_per_pass: int = 3" in settings_src
    assert '_ranged("crawl_per_pass", 0, 100' in settings_src  # 0 = the off switch
    assert 'raw.get("crawl_supplement")' in settings_src  # persisted round-trip
    assert 'raw.get("crawl_per_pass")' in settings_src
    assert "crawl_supplement: bool | None = None" in api_src  # PUT /config parity
    assert "crawl_per_pass: int | None = None" in api_src

    assert "last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime)" in models_src
    assert 'Index("idx_source_last_crawled", "last_crawled_at")' in models_src
    assert "def ensure_source_last_crawled_column(engine: Engine)" in maint_src
    assert "ensure_source_last_crawled_column(engine)" in session_src

    from src.scheduler.settings import SchedulerSettings

    assert SchedulerSettings().crawl_supplement is True
    assert SchedulerSettings().crawl_per_pass == 3


def test_migration_exists_for_last_crawled_at():
    versions_dir = _ROOT / "migrations" / "versions"
    hits = [
        p for p in versions_dir.glob("*.py")
        if "last_crawled_at" in p.read_text("utf-8") and "add_column" in p.read_text("utf-8")
    ]
    assert hits, "expected an alembic migration adding sources.last_crawled_at"
