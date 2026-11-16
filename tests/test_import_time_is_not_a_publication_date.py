"""Import time is not a publication date (R727, R730; field test 2026-11-14 row 63).

The PDF import, the statistics corpus and the Wikipedia corpus wrote the IMPORT time into ``published_at`` when
they had no real date, so a 2009 report read "Published 2026-11-14" and anchored year-less dates to the import
day. They now store none; ``created_at`` keeps the import time. ``clear_import_time_publication_dates`` clears every
value on the two importers' sources (they only ever held import times, a merged twin's included) and nothing else.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.import_dates import clear_import_time_publication_dates
from src.database.models import Article, Base, Source
from src.stats.series_corpus import upsert_series_article
from src.wiki.corpus import upsert_wiki_corpus_article

T0 = datetime(2026, 11, 14, 9, 0, 0)


class _NoExtract:
    def extract(self, *a, **k):
        return []


@pytest.fixture()
def store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'd.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, future=True)


def _article(s, n, source_id, published_at, created_at=T0):
    s.add(Article(url=f"https://x/{n}", canonical_url=f"https://x/{n}", source_id=source_id, title="t",
                  content="c", hash=f"{n:064d}", published_at=published_at, created_at=created_at))


# ---- the writers ------------------------------------------------------------ #

def test_a_statistics_series_page_is_stored_without_a_publication_date(store):
    _engine, Sess = store
    with Sess() as s:
        res = upsert_series_article(s, agency="worldbank", series_id="SP.POP.TOTL", ref_area="FR",
                                    points=[("2020", 1.0), ("2021", 2.0)], extractor=_NoExtract())
        art = s.get(Article, res["article_id"])
        assert art.published_at is None
        assert art.created_at is not None  # the import time has its own column


def test_a_wiki_page_keeps_its_revision_time_and_gets_none_without_one(store):
    _engine, Sess = store
    rev = datetime(2024, 3, 1, 12, 0, tzinfo=UTC)
    with Sess() as s:
        a = upsert_wiki_corpus_article(s, wiki="en", title="Alpha", plain="Alpha text.", published_at=rev,
                                       extractor=_NoExtract())
        b = upsert_wiki_corpus_article(s, wiki="en", title="Beta", plain="Beta text.", extractor=_NoExtract())
        assert s.get(Article, a["article_id"]).published_at.replace(tzinfo=UTC) == rev
        assert s.get(Article, b["article_id"]).published_at is None


def test_the_writers_never_fall_back_to_now():
    from pathlib import Path

    for path in ("src/ingest/pdf_import.py", "src/stats/series_corpus.py", "src/wiki/corpus.py"):
        src = Path(path).read_text(encoding="utf-8")
        assert "published_at=datetime.now" not in src, path
        assert "or datetime.now(UTC)" not in src, path
    assert "last_checked_at,\n" not in Path("src/wiki/corpus.py").read_text(encoding="utf-8")


# ---- the clean-up of stored rows ---------------------------------------------- #

def _seed(Sess):
    with Sess() as s:
        s.add_all([
            Source(name="PDF", domain="pdf.import.local", source_type="document", enabled=False),  # 1
            Source(name="WB", domain="statistics.worldbank.local", source_type="statistics"),  # 2
            Source(name="Wire", domain="wire.test"),  # 3: a news source
            Source(name="Stat office feed", domain="statistics.gov.local", source_type="news"),  # 4: not ours
            Source(name="Agency", domain="stats.example", source_type="statistics"),  # 5: a catalogue source
        ])
        s.commit()
        _article(s, 1, 1, T0 + timedelta(seconds=2))  # PDF, import time -> cleared
        _article(s, 2, 2, T0)  # statistics, import time -> cleared
        _article(s, 3, 2, T0 - timedelta(days=40))  # statistics, another machine's import time adopted by a merge -> cleared
        _article(s, 4, 3, T0)  # news article published the minute it was stored -> kept
        _article(s, 5, 4, T0)  # a look-alike domain that is not a statistics source -> kept
        _article(s, 6, 5, T0)  # a catalogue statistics source -> kept
        _article(s, 7, 1, None)  # already none -> unchanged
        s.commit()


def _published(Sess):
    with Sess() as s:
        return {a.id: a.published_at for a in s.query(Article).order_by(Article.id)}


def test_the_clean_up_clears_only_the_import_time_of_the_two_importers(store):
    engine, Sess = store
    _seed(Sess)
    assert clear_import_time_publication_dates(engine) == 3
    got = _published(Sess)
    assert got[1] is None and got[2] is None and got[3] is None and got[7] is None
    assert got[4] == T0 and got[5] == T0 and got[6] == T0


def test_the_clean_up_is_safe_to_run_again(store):
    engine, Sess = store
    _seed(Sess)
    clear_import_time_publication_dates(engine)
    before = _published(Sess)
    assert clear_import_time_publication_dates(engine) == 0
    assert _published(Sess) == before


def test_the_clean_up_leaves_a_store_without_tables_alone(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}", future=True)
    assert clear_import_time_publication_dates(engine) == 0


def test_init_db_runs_the_clean_up():
    from pathlib import Path

    src = Path("src/database/session.py").read_text(encoding="utf-8")
    assert '_init_step("clear_import_time_publication_dates")' in src
    assert "clear_import_time_publication_dates(engine)" in src


def test_a_store_with_nothing_to_clear_takes_no_write_lock(store, monkeypatch):
    engine, Sess = store
    _seed(Sess)
    clear_import_time_publication_dates(engine)
    began = []
    real = engine.begin
    monkeypatch.setattr(engine, "begin", lambda *a, **k: began.append(1) or real(*a, **k))
    assert clear_import_time_publication_dates(engine) == 0
    assert began == []
