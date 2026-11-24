"""Row 395 (anti-capping): a sources table cut to its biggest rows says so.

``corpus_sources`` keeps ``limit`` rows for the table, and now also counts EVERY source
in the matched set (``sources_total``, ``truncated``) and reads the corpus's publication
span over every matched article (``corpus_first``/``corpus_last``), so a cut table can
say "40 of 120 shown" and the Competitive tab's corpus span is the corpus's own. The
renderers are driven in ``an_sources_cut_node_test.js``; this file also drives it.
"""

from __future__ import annotations

import pathlib
import subprocess
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base, Source
from tests._app_engine import app_sqlite_engine

_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def db():
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _corpus(db, per_source: list[int]) -> list[int]:
    """One source per entry, holding that many articles; source k publishes on day k+1
    of March, so the LAST source (the smallest when sizes fall) holds the latest date."""
    ids: list[int] = []
    for k, n in enumerate(per_source):
        src = Source(name=f"S{k}", domain=f"s{k}.test", country="fr")
        db.add(src)
        db.commit()
        for j in range(n):
            a = Article(
                url=f"https://s{k}.test/{j}",
                canonical_url=f"https://s{k}.test/{j}",
                source_id=src.id,
                title="T",
                content="x",
                hash=f"h{k}-{j}",
                language="en",
                published_at=datetime(2026, 3, k + 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
            db.add(a)
            db.commit()
            ids.append(a.id)
    return ids


def test_a_cut_table_reports_every_source_and_the_whole_span(db):
    ids = _corpus(db, [5, 4, 3, 2, 1])
    r = q.corpus_sources(db, article_ids=ids, limit=2)
    assert r["count"] == 2 and [s["name"] for s in r["sources"]] == ["S0", "S1"]
    assert r["sources_total"] == 5
    assert r["truncated"] is True
    # the span is the corpus's: S4 (cut from the table) published last
    assert r["corpus_first"].startswith("2026-03-01")
    assert r["corpus_last"].startswith("2026-03-05")
    assert max(s["last"] for s in r["sources"]).startswith("2026-03-02")


def test_a_whole_table_is_not_marked_cut(db):
    ids = _corpus(db, [2, 1])
    r = q.corpus_sources(db, article_ids=ids, limit=40)
    assert r["sources_total"] == 2 and r["count"] == 2
    assert r["truncated"] is False


def test_only_the_matched_articles_count(db):
    ids = _corpus(db, [3, 3, 3])
    r = q.corpus_sources(db, article_ids=ids[:3], limit=40)  # all from S0
    assert r["sources_total"] == 1 and r["truncated"] is False
    assert r["corpus_last"].startswith("2026-03-01")


def test_an_empty_set_carries_the_same_keys(db):
    r = q.corpus_sources(db, article_ids=[])
    assert r == {
        "count": 0,
        "sources": [],
        "sources_total": 0,
        "truncated": False,
        "corpus_first": None,
        "corpus_last": None,
    }


def test_the_renderers_say_when_the_table_was_cut_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "an_sources_cut_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "an_sources_cut_node_test.js: OK" in proc.stdout
