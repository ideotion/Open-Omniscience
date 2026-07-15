"""S7 — the /keywords diagnostic collapses its TWO full ``keyword_mentions`` scans
into ONE.

Pins the contract that made the collapse safe: the per-keyword totals (mentions =
SUM(count), articles = COUNT(DISTINCT article_id), first/last = MIN/MAX(observed_on))
computed in the ONE ordered scan are BYTE-IDENTICAL to the retired
``GROUP BY keyword_id`` second scan — because a row is unique per (keyword, article)
under ``ix_mention_covering``, so a per-keyword row count == the distinct-article count,
and MIN/MAX ignore NULL exactly as SQL does. Plus a query-count guard that the second
full scan is gone (efficiency by construction — NEVER by capping the crunch).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

# A keyword that recurs ACROSS articles with DIFFERENT dates (so MIN != MAX) and
# MULTIPLE times WITHIN one article (so SUM(count) > distinct-article-count) — both
# branches of the collapse are genuinely exercised, not vacuously.
_DOCS = [
    ("en", "climate climate climate policy shaped the trade debate.", datetime(2026, 6, 1)),
    ("en", "climate policy and trade policy returned to the summit.", datetime(2026, 6, 10)),
    ("en", "markets and inflation dominated while traders weighed the data.", datetime(2026, 6, 4)),
    ("fr", "la politique climatique et le commerce ont dominé le sommet.", datetime(2026, 6, 2)),
    ("de", "die klimapolitik und der handel bestimmten die debatte heute.", datetime(2026, 6, 3)),
]


def _client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pc.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test", country="fr"))
        s.commit()
        for i, (lang, content, pub) in enumerate(_DOCS):
            a = Article(
                url=f"https://wire.test/{i}",
                canonical_url=f"https://wire.test/{i}",
                source_id=1,
                title=f"t{i}",
                content=content,
                hash=f"pc{i:060d}",
                language=lang,
                published_at=pub.replace(tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
            s.add(a)
            s.commit()
            index_article(s, a, extractor=BaselineExtractor(), country="fr")

    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app, TestClient(app), engine


def _reference_group_by(engine) -> dict:
    """The RETIRED second scan, run independently as the source of truth."""
    ref: dict[int, tuple] = {}
    kmap: dict[int, tuple] = {}
    with engine.connect() as c:
        for kid, m, a, first, last in c.execute(
            text(
                "SELECT keyword_id, COALESCE(SUM(count), 0), COUNT(DISTINCT article_id),"
                " MIN(observed_on), MAX(observed_on)"
                " FROM keyword_mentions GROUP BY keyword_id"
            )
        ):
            ref[kid] = (
                int(m),
                int(a),
                str(first) if first else None,
                str(last) if last else None,
            )
        for kid, norm, lang in c.execute(
            text("SELECT id, normalized_term, language FROM keywords")
        ):
            kmap[kid] = (norm, lang)
    return {kmap[kid]: tup for kid, tup in ref.items()}


def test_totals_are_byte_identical_to_the_retired_group_by(tmp_path):
    app, client, engine = _client(tmp_path)
    try:
        with client:
            r = client.get("/api/diagnostics/keywords")
            assert r.status_code == 200, r.text
        entries = json.loads(r.content)["data"]["keywords"]
    finally:
        app.dependency_overrides.clear()

    ref = _reference_group_by(engine)  # {(normalized, language): (m, a, first, last)}
    assert ref, "fixture produced no keyword mentions"
    # The corpus genuinely exercises both collapse branches (not a vacuous pass).
    assert any(f != last for (m, a, f, last) in ref.values() if f), "no multi-date keyword"
    assert any(m > a for (m, a, f, last) in ref.values()), "no keyword with mentions > articles"

    by_nl = {(e["normalized"], e["language"]): e for e in entries}
    for key, (m, a, first, last) in ref.items():
        e = by_nl.get(key)
        assert e is not None, f"keyword {key} missing from the export"
        assert (e["mentions"], e["articles"], e["first_seen"], e["last_seen"]) == (
            m,
            a,
            first,
            last,
        ), key


def test_only_one_full_mention_scan_remains(tmp_path):
    """The second full ``keyword_mentions`` scan (the GROUP BY) is gone: exactly ONE
    unfiltered scan runs (the ordered collapse); the retired GROUP BY never executes.
    The bounded per-survivor ``WHERE keyword_id IN (...)`` probe is not a full scan."""
    app, client, engine = _client(tmp_path)
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _cap(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        seen.append(" ".join(statement.split()).lower())

    try:
        with client:
            assert client.get("/api/diagnostics/keywords").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _cap)
        app.dependency_overrides.clear()

    full_scans = [
        s
        for s in seen
        if "from keyword_mentions" in s and "where keyword_id in" not in s
    ]
    assert len(full_scans) == 1, full_scans
    assert not any("keyword_mentions group by keyword_id" in s for s in seen), (
        "the retired second GROUP BY scan still runs"
    )
