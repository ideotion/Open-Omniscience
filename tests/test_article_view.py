"""
Test the offline article view endpoint (renders the stored copy, no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Article,
    ArticleEntity,
    ArticleLink,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Source,
)


def test_article_offline_view(tmp_path):
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'v.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Example News", domain="ex.test"))
        s.commit()
        s.add(
            Article(
                url="https://ex.test/story",
                canonical_url="https://ex.test/story",
                source_id=1,
                title="A Big Story",
                content="First paragraph here.\nSecond paragraph here.",
                hash="h1",
                language="en",
                author="J. Doe",
                published_at=datetime(2024, 6, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/html")
            body = r.text
            assert "A Big Story" in body
            assert "First paragraph here." in body and "Second paragraph here." in body
            assert "Example News" in body and "J. Doe" in body
            assert "https://ex.test/story" in body  # original source link present
            assert "offline stored copy" in body  # provenance crumb
            assert "Captured" in body  # ingest-date metadata row
            # Leaving the corpus is an explicit, confirmed action.
            assert "EXTERNAL site on the public web" in body
            # Missing article -> 404.
            assert client.get("/api/articles/999/view").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_article_view_shows_server_ip_with_caveat(tmp_path):
    """SOURCE IPs ruling (2026-07-20): the captured server_ip must surface in the
    reader's app-deduced metadata, with its reason and the standing never-proof-of-
    origin caveat -- previously verified absent from this endpoint."""
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ip.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Example News", domain="ex.test"))
        s.commit()
        s.add(
            Article(
                url="https://ex.test/story",
                canonical_url="https://ex.test/story",
                source_id=1,
                title="IP Story",
                content="Body.",
                hash="h-ip",
                server_ip="203.0.113.5",
                server_ip_reason="captured at fetch",
                created_at=datetime.now(UTC),
            )
        )
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            body = r.text
            assert "203.0.113.5" in body
            assert "captured at fetch" in body
            assert "never proof of origin" in body
    finally:
        app.dependency_overrides.clear()


def test_article_view_shows_unavailable_server_ip_with_reason(tmp_path):
    """A Tor/proxy fetch captures no IP by design -- the row must say so honestly
    (with the reason) rather than showing blank or a guessed address."""
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ip2.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Example News", domain="ex.test"))
        s.commit()
        s.add(
            Article(
                url="https://ex.test/story2",
                canonical_url="https://ex.test/story2",
                source_id=1,
                title="Tor Story",
                content="Body.",
                hash="h-ip2",
                server_ip=None,
                server_ip_reason="fetched via Tor/SOCKS proxy -- only the proxy socket is known",
                created_at=datetime.now(UTC),
            )
        )
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            body = r.text
            assert "unavailable" in body
            assert "only the proxy socket is known" in body
    finally:
        app.dependency_overrides.clear()


def test_article_view_shows_co_citation(tmp_path):
    """When two articles cite the same external link, the reader flags the shared source."""
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'cc.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    shared = "https://shared.example/primary-report"
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        s.add_all(
            [
                Article(
                    url="https://wire.test/a",
                    canonical_url="https://wire.test/a",
                    source_id=1,
                    title="Article A",
                    content="Body A.",
                    hash="ha",
                    language="en",
                    created_at=datetime.now(UTC),
                ),
                Article(
                    url="https://wire.test/b",
                    canonical_url="https://wire.test/b",
                    source_id=1,
                    title="Article B",
                    content="Body B.",
                    hash="hb",
                    language="en",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        s.commit()
        # Both articles cite the same external URL (the co-citation signal).
        s.add_all(
            [
                ArticleLink(
                    article_id=1,
                    url=shared,
                    normalized_url=shared,
                    link_text="the report",
                    link_type="external",
                ),
                ArticleLink(
                    article_id=2,
                    url=shared,
                    normalized_url=shared,
                    link_text="the report",
                    link_type="external",
                ),
            ]
        )
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            body = client.get("/api/articles/1/view").text
            assert "Sources this article cites" in body
            assert "shared.example" in body
            assert "also cited by 1 of your article(s)" in body  # in-degree 2 -> 1 other
    finally:
        app.dependency_overrides.clear()


def test_article_view_related_and_dup_badge_read_keyword_mentions(tmp_path):
    """P0 fix (reader-dead-legacy-table-related) + its OPT bonus
    (reader-dupbadge-n-plus-1-decrypt-risk): the reader's 'Related in your corpus'
    list and the near-dup '~N' badge must read KeywordMention -- the table the real
    per-article ingest chokepoint (src/analytics/store.index_article) actually
    writes -- not the legacy article_keyword_association table, which has zero
    writers anywhere in the live ingest path and always yielded an empty candidate
    set. Seeds three verbatim near-duplicate articles from three different
    outlets (differing only by a bracketed source tag, matching the finding's own
    repro) through the REAL index_article ingestion path -- never raw SQL -- so the
    KeywordMention rows are the genuine article ever writes."""
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'related.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    # A long shared body so word-shingle MinHash similarity clears the 0.7
    # near-dup threshold despite the few differing title tokens below.
    shared_body = (
        "The ministry announced a sweeping new policy on coastal infrastructure "
        "funding today, citing climate resilience and regional development goals "
        "as the central justification for the multi-year program of public works "
        "it intends to deliver across the northern provinces over the coming "
        "decade and beyond. Officials said the plan would also expand port "
        "capacity, modernize rail links and strengthen flood defenses in "
        "low-lying communities that have repeatedly suffered storm damage in "
        "recent years, while independent analysts cautioned that financing "
        "details remain unresolved and depend on parliamentary approval expected "
        "later this year."
    )
    with Sess() as s:
        for i in (1, 2, 3):
            s.add(Source(name=f"Outlet {i}", domain=f"outlet{i}.test"))
        s.commit()
        arts = []
        for i in (1, 2, 3):
            art = Article(
                url=f"https://outlet{i}.test/central-bank",
                canonical_url=f"https://outlet{i}.test/central-bank",
                source_id=i,
                title=f"Coastal infrastructure policy unveiled [Outlet {i}]",
                content=shared_body,
                hash=f"cb{i}",
                language="en",
                created_at=datetime.now(UTC),
            )
            s.add(art)
            s.commit()
            arts.append(art)
        ex = BaselineExtractor()
        for art in arts:
            index_article(s, art, extractor=ex, country="fr")
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            body = r.text
            # "Related in your corpus" now correctly lists the two near-identical
            # siblings, ranked by shared extracted keywords -- not the honest-
            # looking-but-wrong empty state the dead legacy table used to force.
            assert "Related in your corpus" in body
            assert "No related articles yet" not in body
            assert "/api/articles/2/view" in body
            assert "/api/articles/3/view" in body
            assert "shared keyword" in body
            # The inline near-dup "~N" badge fires: all 3 outlets are one cluster.
            assert 'class="dup-pill"' in body
            assert "≈3" in body  # "≈3" -- the cluster's full member count
            assert "Show the copies" in body
    finally:
        app.dependency_overrides.clear()


def _engine_with_article(tmp_path, name):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Example News", domain="ex.test"))
        s.commit()
        s.add(
            Article(
                url="https://ex.test/story",
                canonical_url="https://ex.test/story",
                source_id=1,
                title="A Big Story",
                content="Some body mentioning Paris and Angela Merkel.",
                hash="hwww",
                language="en",
                created_at=datetime.now(UTC),
            )
        )
        s.commit()
    return Sess


def test_reader_reads_stored_when_where_who_without_recomputing(tmp_path, monkeypatch):
    """An article WITH persisted T12 rows is rendered from the DB, NOT recomputed.

    We make the live extractors raise; the reader must still surface the stored
    place + entities, proving it read article_mentioned_places / article_entities.
    """
    from src.database.session import get_db

    Sess = _engine_with_article(tmp_path, "stored.db")
    with Sess() as s:
        s.add(
            ArticleMentionedPlace(
                article_id=1,
                name="Storedville",
                country="fr",
                kind="city",
                mentions=3,
                snippet="…near Storedville…",
                note="gazetteer match",
                extractor="lexical-v1",
            )
        )
        s.add(
            ArticleEntity(
                article_id=1,
                name="Stored Person",
                entity_class="person",
                mentions=2,
                note="capitalized bigram",
                extractor="lexical-v1",
            )
        )
        s.add(
            ArticleEntity(
                article_id=1,
                name="Stored Org Inc",
                entity_class="organization",
                mentions=4,
                note="org suffix",
                extractor="lexical-v1",
            )
        )
        s.commit()

    def _boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("live extractor recomputed despite stored rows")

    monkeypatch.setattr("src.timemap.locextract.extract_locations", _boom)
    monkeypatch.setattr("src.timemap.entextract.extract_entities", _boom)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            body = r.text
            assert "Storedville" in body  # stored place rendered
            assert "Stored Person" in body  # stored person rendered
            assert "Stored Org Inc" in body  # stored organization rendered
    finally:
        app.dependency_overrides.clear()


def test_reader_falls_back_to_live_when_no_stored_rows(tmp_path, monkeypatch):
    """An article with NO persisted T12 rows falls back to the live extractor."""
    from src.database.session import get_db

    Sess = _engine_with_article(tmp_path, "fallback.db")  # no place/entity rows

    calls = {"loc": 0, "ent": 0}

    def _fake_locs(*a, **k):
        calls["loc"] += 1
        return [{"name": "Fallbackton", "country": "us", "kind": "city", "mentions": 1}]

    def _fake_ents(*a, **k):
        calls["ent"] += 1
        return {
            "people": [{"name": "Fallback Person", "mentions": 1}],
            "organizations": [],
        }

    monkeypatch.setattr("src.timemap.locextract.extract_locations", _fake_locs)
    monkeypatch.setattr("src.timemap.entextract.extract_entities", _fake_ents)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            body = r.text
            assert "Fallbackton" in body  # live-computed place surfaced
            assert "Fallback Person" in body  # live-computed entity surfaced
            assert calls["loc"] == 1 and calls["ent"] == 1  # fallback ran
    finally:
        app.dependency_overrides.clear()


def test_reader_reads_stored_dates_without_recomputing(tmp_path, monkeypatch):
    """The 'Event dates in text' row reads stored article_mentioned_dates (T12),
    NOT the live date extractor, when stored tags exist. A user-REJECTED tag is
    excluded from the compact summary."""
    from datetime import date

    from src.database.session import get_db

    Sess = _engine_with_article(tmp_path, "dates.db")
    with Sess() as s:
        s.add(
            ArticleMentionedDate(
                article_id=1,
                mentioned_on=date(1945, 8, 6),
                precision="day",
                snippet="…on 6 August 1945…",
                status="candidate",
                extractor="dateextract",
            )
        )
        s.add(
            ArticleMentionedDate(
                article_id=1,
                mentioned_on=date(1969, 7, 20),
                precision="day",
                snippet="…20 July 1969…",
                status="rejected",  # must NOT appear in the deduced summary
                extractor="dateextract",
            )
        )
        s.commit()

    def _boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("live date extractor recomputed despite stored rows")

    monkeypatch.setattr("src.timemap.dateextract.extract_dates", _boom)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            body = r.text
            assert "Event dates in text" in body
            # Assert against the COMPACT deduced summary cell ("Event dates in
            # text") only: the rejected tag still legitimately appears in the
            # full "Dates mentioned in this text" management section below (with
            # its confirm/reject controls), so a whole-body check would be wrong.
            i = body.index("Event dates in text")
            summary_cell = body[i : body.index("</div>", i)]
            assert "1945-08-06" in summary_cell  # stored candidate date rendered
            assert "1969-07-20" not in summary_cell  # rejected tag excluded
    finally:
        app.dependency_overrides.clear()


def test_reader_falls_back_to_live_dates_when_no_stored_rows(tmp_path, monkeypatch):
    """With NO stored date tags, the deduced 'Event dates in text' row falls back
    to the live extractor."""
    from src.database.session import get_db

    Sess = _engine_with_article(tmp_path, "dates_fallback.db")  # no date rows

    calls = {"dates": 0}

    def _fake_dates(*a, **k):
        calls["dates"] += 1
        return [{"date": "2030-01-02", "precision": "day", "text": "…2 Jan 2030…"}]

    monkeypatch.setattr("src.timemap.dateextract.extract_dates", _fake_dates)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            body = r.text
            assert "2030-01-02" in body  # live-computed date surfaced
            assert calls["dates"] >= 1  # fallback ran
    finally:
        app.dependency_overrides.clear()
