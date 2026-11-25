"""Row 423: the post-import drain analyses a batch NEWEST FIRST, and resumes from the stamps.

Before, both orders were the article id (``sorted(...)``), which is merge insertion order: on a 2M-article import the recent news
a reader looks at first was analysed last. Now the order is ``published_at IS NULL, published_at DESC, id DESC``, and the exact
resume cursor is the pair of analysis stamps ``index_article`` writes in the same transaction as the rows (an id watermark is an
exact cursor only in ascending id order, so it is kept as a diagnostic).

Three things are pinned:
  1. the order the drain hands the pass, including undated articles and an id that names no article any more;
  2. a resume after a crash redoes nothing the stamps say is done and skips nothing they do not, whatever the cursor file says;
  3. draining in the new order writes the same derived rows as draining in id order, on two copies of one corpus, with
     keyword ids compared through their (term, language).
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import get_extractor
from src.analytics.store import reindex_articles
from src.database.fts import _FTS_DDL
from src.database.models import Article, Base, KeywordMention, Source
from tests._app_engine import app_sqlite_engine

# --------------------------------------------------------------------------------------------------------------------- #
# 1 + 2. the drain itself, on the live database


def _live_source(s, domain):
    row = s.query(Source).filter_by(domain=domain).first()
    if row is None:
        row = Source(name=domain, domain=domain, country="fr")
        s.add(row)
        s.flush()
    return row


_TEXTS = (
    "The election in France saw record inflation and a climate summit in Paris.",
    "Sanctions and an energy crisis hit the economy of Germany this winter.",
    "A drought and a market crash dominated headlines across Spain.",
    "A pandemic and a vaccine rollout dominated the news in Italy.",
    "Central bank raises interest rates as inflation persists in Europe.",
    "Flooding in Bangladesh displaces thousands as the monsoon intensifies.",
)


def _batch(s, tag: str, dates: list[datetime | None]) -> tuple[int, list[int]]:
    from src.database.models import MergeBatch, MergedRow

    src = _live_source(s, f"{tag}.row423.test")
    ids = []
    for i, when in enumerate(dates):
        a = Article(
            url=f"https://{tag}.row423.test/{i}", canonical_url=f"https://{tag}.row423.test/{i}", source_id=src.id,
            title=f"Imported {i}", content=_TEXTS[i % len(_TEXTS)], hash=f"{tag}-row423-{i}", country="fr", language="en",
            published_at=when, created_at=datetime.now(UTC),
        )
        s.add(a)
        s.flush()
        ids.append(a.id)
    batch = MergeBatch(artifact_kind="oo-backup-2", origin_fingerprint="unsigned", status="merged")
    s.add(batch)
    s.flush()
    for aid in ids:
        s.add(MergedRow(batch_id=batch.id, table_name="articles", row_id=aid))
    s.commit()
    return batch.id, ids


def _cleanup(batch_id, ids) -> None:
    from src.database.models import ArticleIndexStamp, ArticleWwwStamp, MergeBatch, MergedRow
    from src.database.session import session_scope

    with session_scope() as s:
        for aid in ids:
            s.query(ArticleIndexStamp).filter_by(article_id=aid).delete()
            s.query(ArticleWwwStamp).filter_by(article_id=aid).delete()
            s.query(KeywordMention).filter_by(article_id=aid).delete()
            a = s.get(Article, aid)
            if a is not None:
                s.delete(a)
        if batch_id is not None:
            s.query(MergedRow).filter_by(batch_id=batch_id).delete()
            b = s.get(MergeBatch, batch_id)
            if b is not None:
                s.delete(b)
        s.commit()


def _spy(monkeypatch, *, real: bool, cut: int | None = None) -> list[list[int]]:
    """Record the ids each pass is handed. ``real`` runs the pass; ``cut`` runs only the first ``cut`` of them, the way a crash
    after that many committed articles would leave the store."""
    import src.analytics.store as store_mod

    seen: list[list[int]] = []
    original = store_mod.reindex_articles

    def _pass(session, *, article_ids, **kw):
        seen.append(list(article_ids))
        if not real:
            return {"reindexed": len(article_ids), "failed": 0}
        return original(session, article_ids=list(article_ids)[:cut] if cut is not None else article_ids, **kw)

    monkeypatch.setattr(store_mod, "reindex_articles", _pass)
    return seen


def test_the_drain_hands_the_pass_the_newest_articles_first(monkeypatch, tmp_path):
    from src.backup import merge as merge_mod
    from src.database.models import MergedRow
    from src.database.session import init_db, session_scope

    monkeypatch.setattr(merge_mod, "data_dir", lambda: tmp_path)  # the cursor file stays in this test
    init_db()
    d = lambda y, m=1: datetime(y, m, 1, tzinfo=UTC)  # noqa: E731
    batch_id = ids = None
    try:
        with session_scope() as s:
            # inserted oldest-id-first in an order that is NOT date order, with a tie and two undated articles
            batch_id, ids = _batch(s, "order", [d(2020), d(2024, 6), None, d(2022), d(2024, 6), None, d(2023)])
            gone = max(ids) + 1000  # an imported article deleted since: merged_rows has no cascade
            s.add(MergedRow(batch_id=batch_id, table_name="articles", row_id=gone))
            s.commit()
        seen = _spy(monkeypatch, real=False)
        merge_mod.reindex_imported_articles(batch_id, workers=0)
        i = ids
        assert seen == [[i[4], i[1], i[6], i[3], i[0], i[5], i[2], gone]], (
            "newest date first, the id breaking a tie newest-inserted first; undated after them; an id naming no article last"
        )
    finally:
        _cleanup(batch_id, ids or [])
        if batch_id is not None:
            with session_scope() as s:
                s.query(MergedRow).filter_by(batch_id=batch_id).delete()
                s.commit()


def test_a_resume_redoes_nothing_the_stamps_say_is_done_and_skips_nothing_else(monkeypatch, tmp_path):
    """A crash after three of six committed articles. The resume is handed exactly the other three, newest first. Under the
    old id watermark, the cursor the first run left (the id of the third NEWEST article) would have dropped every owed article
    with a lower id -- articles never analysed, and the batch stamped done over them."""
    from src.backup import merge as merge_mod
    from src.database.models import ArticleIndexStamp, ArticleWwwStamp
    from src.database.session import init_db, session_scope

    monkeypatch.setattr(merge_mod, "data_dir", lambda: tmp_path)
    init_db()
    batch_id = ids = None
    try:
        with session_scope() as s:
            # newest article inserted LAST, so newest first is descending id order and an id watermark would skip the rest
            batch_id, ids = _batch(s, "resume", [datetime(2020 + k, 1, 1, tzinfo=UTC) for k in range(6)])
            ids = ids[::-1]  # the order the drain owes them in
        first = _spy(monkeypatch, real=True, cut=3)
        out1 = merge_mod.reindex_imported_articles(batch_id, workers=0, commit_batch=1)
        assert first == [ids], "first run: the whole batch, newest first"
        assert out1["reindexed"] == 3
        cursor = merge_mod.peek_reindex_cursor()
        assert cursor and cursor["batch_id"] == batch_id and cursor["last_id"] == ids[2], "the diagnostic names the last finished"

        with session_scope() as s:
            status = s.execute(text("SELECT status FROM merge_batches WHERE id = :b"), {"b": batch_id}).scalar()
        assert status == merge_mod._STATUS_MERGED, "a batch the crash left short is not stamped done"

        second = _spy(monkeypatch, real=True)
        out2 = merge_mod.reindex_imported_articles(batch_id, workers=0, commit_batch=1)
        assert second == [ids[3:]], "the resume: exactly what the stamps say is owed, newest first -- nothing redone, nothing skipped"
        assert out2["reindexed"] == 3 and out2.get("already_certified") == 3
        with session_scope() as s:
            stamped = {r[0] for r in s.query(ArticleIndexStamp.article_id).filter(ArticleIndexStamp.article_id.in_(ids))}
            www = {r[0] for r in s.query(ArticleWwwStamp.article_id).filter(ArticleWwwStamp.article_id.in_(ids))}
            status = s.execute(text("SELECT status FROM merge_batches WHERE id = :b"), {"b": batch_id}).scalar()
        assert stamped == www == set(ids)
        assert status == merge_mod._STATUS_REINDEXED
    finally:
        _cleanup(batch_id, ids or [])


def test_without_an_engine_identity_the_drain_keeps_the_ascending_order_and_its_exact_watermark(monkeypatch, tmp_path):
    """When an engine identity cannot be computed nothing is ever stamped, so the stamps cannot be the cursor: a newest-first resume would
    start again from the top every time (and the storage guard's one-window re-runs would never advance). The batch then goes in ascending
    id order and resumes from the id watermark, which is exact in that order. A newest-first cursor left on disk is not read as one."""
    from src.backup import merge as merge_mod
    from src.database.session import init_db, session_scope

    monkeypatch.setattr(merge_mod, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(merge_mod, "_backlog_www_engine", lambda: "<unknown>")
    init_db()
    batch_id = ids = None
    try:
        with session_scope() as s:
            batch_id, ids = _batch(s, "fallback", [datetime(2020 + k, 1, 1, tzinfo=UTC) for k in range(6)])
        merge_mod._save_reindex_cursor(batch_id, last_id=ids[-1], done=1, total=6, order="newest")  # another order's cursor
        first = _spy(monkeypatch, real=True, cut=3)
        merge_mod.reindex_imported_articles(batch_id, workers=0, commit_batch=1)
        assert first == [ids], "ascending id order, and the other order's watermark is not a cursor here"
        assert merge_mod.peek_reindex_cursor()["order"] == "id"
        second = _spy(monkeypatch, real=True)
        out = merge_mod.reindex_imported_articles(batch_id, workers=0, commit_batch=1)
        assert second == [ids[3:]], "the resume skips exactly what the watermark says is finished, though nothing is certified"
        assert out.get("resumed_already_done") == 3 and "already_certified" not in out
    finally:
        _cleanup(batch_id, ids or [])


def test_the_newest_first_order_reads_the_date_index_not_the_article_rows():
    """``published_at`` sits after ``content`` in the table: reading it row by row walks every article's overflow pages."""
    from src.backup import merge as merge_mod

    assert "INDEXED BY idx_article_published_at" in merge_mod._BATCH_NEWEST_FIRST_SQL
    assert "published_at IS NULL, a.published_at DESC, a.id DESC" in merge_mod._BATCH_NEWEST_FIRST_SQL
    assert "sorted(" not in __import__("inspect").getsource(merge_mod.reindex_imported_articles)


# --------------------------------------------------------------------------------------------------------------------- #
# 3. the same rows, in either order

_CORPUS = (
    ("en", "The election in France saw record inflation and a climate summit in Paris on 3 March 2024. Inflation, inflation."),
    ("en", "Inflation and the election dominated Paris as the climate summit closed."),
    ("fr", "L'inflation et l'élection en France ont dominé le sommet sur le climat à Paris."),
    ("en", "Sanctions and an energy crisis hit Germany; Berlin warned of inflation. Sanctions again, sanctions everywhere."),
    ("fr", "Les sanctions et la crise de l'énergie frappent l'Allemagne et Berlin."),
    ("en", "A drought in Spain and a market crash in Madrid worried the European Central Bank."),
    ("en", "The European Central Bank raised rates as inflation persisted in Germany and France."),
    ("en", "Flooding in Bangladesh displaced thousands as the monsoon reached Dhaka on 12 July 2023."),
    ("fr", "Inondations au Bangladesh : des milliers de déplacés à Dhaka pendant la mousson. La mousson, encore la mousson."),
    ("en", "A pandemic and a vaccine rollout dominated the news in Italy and Rome. The vaccine, the vaccine, the vaccine."),
    ("en", "Rome and Milan reported vaccine shortages during the pandemic."),
    ("en", "Climate summit delegates in Paris discussed energy, sanctions and the drought."),
)


def _corpus(path: Path) -> None:
    engine = app_sqlite_engine(path, future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    con = sqlite3.connect(path, isolation_level=None)
    for ddl in _FTS_DDL:
        con.execute(ddl)
    con.close()
    engine = app_sqlite_engine(path, future=True)
    s = sessionmaker(bind=engine, future=True)()
    try:
        src = Source(name="Wire", domain="wire.row423.test", country="fr")
        s.add(src)
        s.flush()
        for i, (lang, body) in enumerate(_CORPUS):
            # dates deliberately out of id order, with a tie and an undated article
            when = None if i == 4 else datetime(2020 + (i * 7) % 6, 1 + i % 12, 1, tzinfo=UTC)
            s.add(Article(url=f"https://wire.row423.test/{i}", canonical_url=f"https://wire.row423.test/{i}", source_id=src.id,
                          title=f"Report {i}", content=body, hash=f"h{i:04d}", country="fr", language=lang,
                          published_at=when, created_at=datetime(2024, 1, 1, tzinfo=UTC)))
        s.commit()
    finally:
        s.close()
        engine.dispose()


def _drain(path: Path, newest_first: bool) -> list[int]:
    engine = app_sqlite_engine(path, future=True)
    s = sessionmaker(bind=engine, future=True)()
    try:
        rows = s.execute(Article.__table__.select().with_only_columns(Article.id, Article.published_at)).fetchall()
        if newest_first:
            order = [r[0] for r in sorted(rows, key=lambda r: (r[1] is None, -(r[1].timestamp() if r[1] else 0), -r[0]))]
        else:
            order = sorted(r[0] for r in rows)
        reindex_articles(s, extractor=get_extractor("baseline"), article_ids=order, commit_batch=3, workers=0, bump_epoch=False)
        return order
    finally:
        s.close()
        engine.dispose()


def _snapshot(path: Path) -> dict:
    """Every derived table, keyed on natural identities: a keyword id is replaced by its (term, language), the article id by
    its hash. The top keyword is compared only when it is a single keyword: with a tie, ``top_keyword_of`` names the lowest
    id as a representative (store.py: "carries no meaning of its own"), and ids are handed out in processing order."""
    con = sqlite3.connect(path)
    try:
        def rows(sql):
            return sorted(tuple(r) for r in con.execute(sql).fetchall())

        return {
            "mentions": rows(
                "SELECT a.hash, k.normalized_term, k.language, m.count, m.first_offset, m.observed_on, m.country, m.city,"
                " m.language, m.extractor FROM keyword_mentions m JOIN articles a ON a.id = m.article_id"
                " JOIN keywords k ON k.id = m.keyword_id"
            ),
            "keywords": rows(
                "SELECT normalized_term, term, language, is_entity, entity_type, mention_count, article_count, frequency"
                " FROM keywords"
            ),
            "places": rows(
                "SELECT a.hash, p.name, p.country, p.kind, p.mentions, p.snippet, p.lat, p.lon, p.note, p.extractor"
                " FROM article_mentioned_places p JOIN articles a ON a.id = p.article_id"
            ),
            "entities": rows(
                "SELECT a.hash, e.name, e.entity_class, e.mentions, e.snippet, e.note, e.extractor"
                " FROM article_entities e JOIN articles a ON a.id = e.article_id"
            ),
            "dates": rows(
                "SELECT a.hash, d.mentioned_on, d.precision, d.snippet, d.confidence, d.extractor, d.status"
                " FROM article_mentioned_dates d JOIN articles a ON a.id = d.article_id"
            ),
            "articles": rows(
                "SELECT a.hash, CASE WHEN a.top_keyword_tied_n = 1 THEN k.normalized_term END, a.top_keyword_count,"
                " a.top_keyword_tied_n, a.sentiment_score, a.sentiment_label, a.detected_language"
                " FROM articles a LEFT JOIN keywords k ON k.id = a.top_keyword_id"
            ),
            "stamps": rows(
                "SELECT a.hash, st.engine, st.inputs FROM article_index_stamps st JOIN articles a ON a.id = st.article_id"
            ),
            "www_stamps": rows(
                "SELECT a.hash, st.engine, st.inputs FROM article_www_stamps st JOIN articles a ON a.id = st.article_id"
            ),
        }
    finally:
        con.close()


def test_draining_newest_first_writes_the_same_rows_as_draining_in_id_order(tmp_path):
    base = tmp_path / "corpus.db"
    _corpus(base)
    by_id, newest = tmp_path / "by_id.db", tmp_path / "newest.db"
    shutil.copyfile(base, by_id)
    shutil.copyfile(base, newest)
    order_a = _drain(by_id, newest_first=False)
    order_b = _drain(newest, newest_first=True)
    assert order_a != order_b, "the two drains must really run in different orders"
    a, b = _snapshot(by_id), _snapshot(newest)
    assert a["mentions"] and a["stamps"] and len(a["stamps"]) == len(_CORPUS), "the corpus must really be analysed"
    assert sum(1 for r in a["articles"] if r[1] is not None) >= 3, "some articles must have a single top keyword to compare"
    for key in a:
        assert a[key] == b[key], (
            f"draining newest first wrote different {key}:\n"
            f"only by id:        {sorted(set(a[key]) - set(b[key]))[:5]}\n"
            f"only newest first: {sorted(set(b[key]) - set(a[key]))[:5]}"
        )


def test_a_store_without_the_date_index_gets_the_same_order(tmp_path):
    from src.backup.merge import _batch_in_drain_order
    from src.database.models import MergeBatch, MergedRow

    path = tmp_path / "c.db"
    _corpus(path)
    engine = app_sqlite_engine(path, future=True)
    s = sessionmaker(bind=engine, future=True)()
    try:
        b = MergeBatch(artifact_kind="oo-backup-2", origin_fingerprint="unsigned", status="merged")
        s.add(b)
        s.flush()
        ids = [r[0] for r in s.execute(text("SELECT id FROM articles"))]
        for aid in [*ids, max(ids) + 50]:  # and one id naming no article
            s.add(MergedRow(batch_id=b.id, table_name="articles", row_id=aid))
        s.commit()
        with_index = _batch_in_drain_order(s, b.id, newest_first=True)
        s.execute(text("DROP INDEX idx_article_published_at"))
        s.commit()
        without = _batch_in_drain_order(s, b.id, newest_first=True)
        assert with_index == without and with_index[-1] == max(ids) + 50 and len(with_index) == len(ids) + 1
        assert _batch_in_drain_order(s, b.id, newest_first=False) == sorted([*ids, max(ids) + 50])
    finally:
        s.close()
        engine.dispose()
