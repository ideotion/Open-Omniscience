"""R24: a same-engine backup CARRIES its derived rows -- and they are exactly the rows a
re-index would have written.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ACCEPTANCE CRITERION IS A DIFFERENTIAL, NOT A LIST OF EXPECTATIONS. The same backup is
restored twice into two identical copies of one target: once with the carry, once with it
switched off so the 2026-07-29 option (a) runs -- the merge copies no derived rows and a
re-index produces them. Everything the carry claims to reproduce is then compared,
row for row: every mention (to the KEYWORD ROW, not just the term), every place, entity
and date, each article's top keyword and sentiment, each keyword's entity status and
counters, and the stamps. If they differ, the carry wrote something a re-index would not
have, which is the one thing it exists never to do.

The scenarios are the ways it could go wrong, each made to fire (a scenario that does not
fire proves nothing, so each asserts it did):

  * a FRESH INSTALL, where everything should carry;
  * a POPULATED corpus with a keyword row that shares a carried term under another
    language and a LOWER id -- the merge's own map (term + language) and the indexer's
    lookup (term alone, lowest id) disagree there, and the carry must follow the indexer;
  * a local keyword that is NOT an entity where the incoming one is -- a re-index would
    upgrade it, the carry cannot, so the article must be left to the re-index;
  * a local source with the same domain and a DIFFERENT name -- its self-name forms are
    different inputs, so its articles must be left to the re-index;
  * an article already present locally, which nothing carries INTO.

What deliberately differs between the two, and is excluded from the comparison with the
reason: row ids and ``created_at`` stamps (a clock, not a fact), and
``articles.keyword_indexed_at`` -- the per-machine attempt record, which stays NULL for a
carried article because this machine ran no pass on it.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.analytics.engine_identity import baseline_engine_id
from src.analytics.extract import get_extractor
from src.analytics.store import index_article, reindex_articles
from src.backup.merge import _BACKLOG_SQL, _STATUS_MERGED, _STATUS_REINDEXED, merge_corpus
from src.database.fts import _FTS_DDL
from src.database.fts_norm import register as _register_fts_functions
from src.database.models import Article, ArticleIndexStamp, Base, Keyword, Source


def _writer(path: Path) -> sqlite3.Connection:
    """A raw connection that may write ``articles``: the index's sync triggers call the
    search transform (``src/database/fts_norm.py``), which every app connection registers."""
    con = sqlite3.connect(path)
    _register_fts_functions(con)
    return con


_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}

_DAILY = ("The Daily Test", "dailytest.example")
_WIRE = ("Wire", "wire.example")

#: (source, language, title, body, stored compressed?)
_ARTICLES = [
    (_DAILY, "en", "Budget talks",
     "Chancellor Olaf Scholz met President Emmanuel Macron in Berlin on 12 March 2024. "
     "The budget talks in Berlin covered the European budget and energy prices. "
     # Acronyms are the one route by which the BASELINE extractor yields an entity
     # keyword (no gazetteer, no spaCy), and the entity-upgrade guard needs one.
     "NATO and the OECD sent observers. Budget budget energy.", False),
    (_DAILY, "fr", "Budget européen",
     "Le président Emmanuel Macron a rencontré le chancelier Olaf Scholz à Paris le "
     "3 avril 2024 pour discuter du budget européen et des prix de l'énergie.", False),
    (_DAILY, "de", "Haushalt",
     "Bundeskanzler Olaf Scholz traf Präsident Emmanuel Macron am 12. März 2024 in Berlin, "
     "um den europäischen Haushalt zu besprechen.", False),
    (_DAILY, None, "United Nations",
     "The United Nations met in New York and Geneva on 5 May 2024 to discuss climate "
     "finance and energy prices. Climate climate finance.", False),
    (_DAILY, "en", "Compressed",
     "A compressed article about the World Health Organization in Geneva on 1 June 2024, "
     "and vaccine supply chains. Vaccine supply.", True),
    (_DAILY, "en", "Ties", "Alpha beta gamma delta. Alpha beta. Gamma delta.", False),
    (_WIRE, "en", "Wire copy",
     "Energy prices rose in Madrid and Lisbon on 2 February 2024, the wire reported. "
     "Energy energy markets.", False),
]


def _schema(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    con = sqlite3.connect(path, isolation_level=None)
    for ddl in _FTS_DDL:
        con.execute(ddl)
    con.close()


def _session(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    return engine, sessionmaker(bind=engine, future=True)()


def _backup(path: Path) -> None:
    """The exporting corpus: every article indexed by THIS engine, so each is stamped."""
    _schema(path)
    engine, s = _session(path)
    try:
        sources = {}
        for name, domain in (_DAILY, _WIRE):
            # A source country that DIFFERS from its articles' own, on purpose: live
            # ingest denormalises the SOURCE's country and city onto each mention, a
            # re-index the ARTICLE's country and no city, and a carried mention must come
            # out the way the re-index would write it.
            src = Source(name=name, domain=domain, country="fr")
            s.add(src)
            s.flush()
            sources[(name, domain)] = src
        ex = get_extractor("baseline")
        for i, (src, lang, title, body, compressed) in enumerate(_ARTICLES):
            a = Article(
                url=f"https://{src[1]}/{i}", canonical_url=f"https://{src[1]}/{i}",
                source_id=sources[src].id, title=title, content=body, hash=f"h{i:04d}",
                language=lang, country="de" if src == _DAILY else "es",
                published_at=datetime(2024, 3, 12, 9, 0, tzinfo=UTC),
                created_at=datetime(2024, 3, 12, 10, 0, tzinfo=UTC),
            )
            if compressed:
                # The stored-compressed shape: the text lives in compressed_content and
                # the NOT NULL content column is empty -- so get_content() and the raw
                # column the When x Where x Who stores read DISAGREE, which is exactly
                # the case the inputs digest hashes both halves for.
                a.compress_content()
                a.content = ""
            s.add(a)
            s.commit()
            # Indexed the way src/ingest/pipeline.py indexes: the source's country, a city.
            index_article(s, a, extractor=ex, country=sources[src].country, city="Lyon")
    finally:
        s.close()
        engine.dispose()


def _stamped(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT COUNT(*) FROM article_index_stamps").fetchone()[0]
    finally:
        con.close()


def _populated_target(path: Path, backup: Path) -> dict:
    """A target that already holds things the backup collides with, each chosen to make
    one guard fire. Returns what it planted, for the assertions."""
    _schema(path)
    src_con = sqlite3.connect(backup)
    try:
        # An entity term the backup's articles use, and a plain term they use.
        entity_term = src_con.execute(
            "SELECT k.normalized_term FROM keywords k JOIN keyword_mentions m"
            " ON m.keyword_id = k.id WHERE k.is_entity = 1 ORDER BY k.id LIMIT 1"
        ).fetchone()[0]
        plain_term = src_con.execute(
            "SELECT k.normalized_term FROM keywords k JOIN keyword_mentions m"
            # 'budget', because a CARRIED article (h0001) uses it. The first draft planted
            # 'energy', which only REFUSED articles use -- so every mention of it came from
            # the re-index, and a mutation resolving terms to the HIGHEST id survived.
            " ON m.keyword_id = k.id WHERE k.is_entity = 0 AND k.normalized_term = 'budget'"
            " LIMIT 1"
        ).fetchone()[0]
        dup = src_con.execute(
            "SELECT url, canonical_url, title, content, hash FROM articles"
            " WHERE hash = 'h0005'"
        ).fetchone()
    finally:
        src_con.close()
    engine, s = _session(path)
    try:
        # FIRST, so these rows hold the LOWEST ids for their terms.
        s.add(Keyword(term=plain_term, normalized_term=plain_term, language="it", frequency=0))
        s.add(Keyword(term=entity_term, normalized_term=entity_term, language="en",
                      frequency=0, is_entity=False))
        s.flush()
        # Same domain as the backup's wire source, different NAME: different self-name
        # forms, so different inputs for every article of that source.
        wire = Source(name="Wire Service International", domain=_WIRE[1])
        daily = Source(name=_DAILY[0], domain=_DAILY[1])
        s.add_all([wire, daily])
        s.flush()
        # The backup's "Ties" article, already here.
        s.add(Article(url=dup[0], canonical_url=dup[1], source_id=daily.id, title=dup[2],
                      content=dup[3], hash=dup[4], language="en",
                      created_at=datetime(2024, 3, 12, 10, 0, tzinfo=UTC)))
        s.commit()
    finally:
        s.close()
        engine.dispose()
    return {"entity_term": entity_term, "plain_term": plain_term}


def _restore(backup: Path, target: Path, working: Path, *, carry: bool, monkeypatch) -> dict:
    """merge_corpus, then the post-swap re-index of every batch article not certified --
    the same selection reindex_imported_articles makes, run against this file."""
    shutil.copyfile(target, working)
    monkeypatch.setenv("OO_CARRY_DERIVED", "1" if carry else "0")
    counts, batch_id = merge_corpus(backup, working, _BATCH_META)
    engine, s = _session(working)
    try:
        ids = [int(r[0]) for r in s.execute(text(
            "SELECT row_id FROM merged_rows WHERE batch_id = :b AND table_name = 'articles'"
        ), {"b": batch_id})]
        certified = {int(r[0]) for r in s.execute(text(
            "SELECT article_id FROM article_index_stamps WHERE engine = :e"
        ), {"e": baseline_engine_id()})}
        todo = sorted(set(ids) - certified)
        if todo:
            reindex_articles(s, extractor=get_extractor("baseline"), article_ids=todo,
                             commit_batch=1, workers=0, bump_epoch=False)
        status = s.execute(text("SELECT status FROM merge_batches WHERE id = :b"),
                           {"b": batch_id}).scalar()
    finally:
        s.close()
        engine.dispose()
    return {"counts": counts, "batch_id": batch_id, "reindexed": todo, "status": status,
            "inserted": ids}


def _snapshot(path: Path) -> dict:
    """Everything the carry claims to reproduce, keyed on natural identities."""
    con = sqlite3.connect(path)
    try:
        def rows(sql):
            return sorted(tuple(r) for r in con.execute(sql).fetchall())

        return {
            "mentions": rows(
                "SELECT a.hash, m.keyword_id, k.normalized_term, m.count, m.first_offset,"
                " m.observed_on, m.country, m.city, m.language, s.domain, m.extractor"
                " FROM keyword_mentions m JOIN articles a ON a.id = m.article_id"
                " JOIN keywords k ON k.id = m.keyword_id"
                " LEFT JOIN sources s ON s.id = m.source_id"
            ),
            "places": rows(
                "SELECT a.hash, p.name, p.country, p.kind, p.mentions, p.snippet, p.lat,"
                " p.lon, p.note, p.extractor FROM article_mentioned_places p"
                " JOIN articles a ON a.id = p.article_id"
            ),
            "entities": rows(
                "SELECT a.hash, e.name, e.entity_class, e.mentions, e.snippet, e.note,"
                " e.extractor FROM article_entities e JOIN articles a ON a.id = e.article_id"
            ),
            "dates": rows(
                "SELECT a.hash, d.mentioned_on, d.precision, d.snippet, d.confidence,"
                " d.extractor, d.status FROM article_mentioned_dates d"
                " JOIN articles a ON a.id = d.article_id"
            ),
            "articles": rows(
                "SELECT hash, top_keyword_id, top_keyword_count, top_keyword_tied_n,"
                " sentiment_score, sentiment_label, detected_language FROM articles"
            ),
            "keywords": rows(
                "SELECT id, normalized_term, language, is_entity, entity_type,"
                " mention_count, article_count FROM keywords"
            ),
            "stamps": rows(
                "SELECT a.hash, st.engine, st.inputs FROM article_index_stamps st"
                " JOIN articles a ON a.id = st.article_id"
            ),
        }
    finally:
        con.close()


def _assert_same(carried: dict, reindexed: dict) -> None:
    for key in carried:
        assert carried[key] == reindexed[key], (
            f"the carry wrote different {key} than a re-index would have:\n"
            f"only carried:   {sorted(set(carried[key]) - set(reindexed[key]))[:5]}\n"
            f"only reindexed: {sorted(set(reindexed[key]) - set(carried[key]))[:5]}"
        )


@pytest.fixture(scope="module")
def backup(tmp_path_factory):
    path = tmp_path_factory.mktemp("carry") / "backup.db"
    _backup(path)
    assert _stamped(path) == len(_ARTICLES), "the exporter did not stamp every article"
    return path


# --- the differential ------------------------------------------------------- #

def test_a_fresh_install_restore_carries_everything_and_matches_a_re_index(
    backup, tmp_path, monkeypatch
):
    target = tmp_path / "empty.db"
    _schema(target)
    carried = _restore(backup, target, tmp_path / "carry.db", carry=True, monkeypatch=monkeypatch)
    classic = _restore(backup, target, tmp_path / "classic.db", carry=False,
                       monkeypatch=monkeypatch)

    plan = carried["counts"]["_derived_carry"]
    assert plan["carried"]["articles"] == len(_ARTICLES), plan
    assert plan["carried"]["mentions"] > 0 and plan["carried"]["places"] > 0
    assert carried["reindexed"] == [], "a fresh install of a same-engine backup owes nothing"
    assert classic["reindexed"], "the comparison run must actually have re-indexed"
    _assert_same(_snapshot(tmp_path / "carry.db"), _snapshot(tmp_path / "classic.db"))


def test_many_small_windows_write_the_same_rows_as_one(backup, tmp_path, monkeypatch):
    """The field corpus carries across hundreds of windows; the fixture fits in one. So
    shrink both windows until every article is its own round trip, and require the SAME
    rows as a re-index -- a boundary that dropped or repeated an article would differ."""
    import src.backup.merge as merge_mod

    monkeypatch.setattr(merge_mod, "_CARRY_PLAN_CHUNK", 2)
    monkeypatch.setattr(merge_mod, "_CARRY_WRITE_WINDOW", 1)
    target = tmp_path / "empty.db"
    _schema(target)
    carried = _restore(backup, target, tmp_path / "carry.db", carry=True, monkeypatch=monkeypatch)
    _restore(backup, target, tmp_path / "classic.db", carry=False, monkeypatch=monkeypatch)
    assert carried["counts"]["_derived_carry"]["carried"]["articles"] == len(_ARTICLES)
    _assert_same(_snapshot(tmp_path / "carry.db"), _snapshot(tmp_path / "classic.db"))


def test_a_merge_into_a_populated_corpus_matches_a_re_index(backup, tmp_path, monkeypatch):
    target = tmp_path / "populated.db"
    planted = _populated_target(target, backup)
    # One article whose TITLE was edited after it was indexed. Its stored rows describe
    # the old title, so carrying them would differ from a re-index -- which makes the
    # inputs check load-bearing in THIS comparison, not only in a refusal count.
    edited = tmp_path / "edited.db"
    shutil.copyfile(backup, edited)
    con = _writer(edited)
    # Not h0000: that one carries the acronyms the entity scenario needs, and an input
    # refusal would pre-empt it (the first draft edited it, and the entity guard went
    # silent -- the scenario assertions below are what said so).
    con.execute("UPDATE articles SET title = 'Climate finance talks resume' WHERE hash = 'h0003'")
    con.commit()
    con.close()
    backup = edited
    carried = _restore(backup, target, tmp_path / "carry.db", carry=True, monkeypatch=monkeypatch)
    classic = _restore(backup, target, tmp_path / "classic.db", carry=False,
                       monkeypatch=monkeypatch)

    assert classic["reindexed"], "the comparison run must actually have re-indexed"
    plan = carried["counts"]["_derived_carry"]
    refused = plan["refused"]
    # Every scenario FIRED -- a guard that was never exercised proves nothing.
    assert refused["already_present"] == 1, refused
    assert refused["inputs_changed"] >= 1, refused  # the wire source's renamed articles
    assert refused["entity_upgrade"] >= 1, refused
    assert plan["carried"]["articles"] >= 1, plan
    # ...and the carried ones still match a re-index, row for row, including which
    # KEYWORD ROW each mention landed on where two rows share a term.
    snap = _snapshot(tmp_path / "carry.db")
    _assert_same(snap, _snapshot(tmp_path / "classic.db"))
    plain_rows = {r[1] for r in snap["mentions"] if r[2] == planted["plain_term"]}
    con = sqlite3.connect(target)
    lowest = con.execute(
        "SELECT MIN(id) FROM keywords WHERE normalized_term = ?", (planted["plain_term"],)
    ).fetchone()[0]
    con.close()
    # The term exists here under another language with a LOWER id than the row the merge
    # inserts for the incoming one. The indexer resolves by term alone to the lowest id,
    # the merge's own map by term + language to the inserted row; the carry must follow
    # the indexer, so every mention of the term lands on the planted row.
    assert plain_rows == {lowest}, f"expected every {planted['plain_term']!r} on {lowest}: {plain_rows}"
    con = sqlite3.connect(tmp_path / "carry.db")
    marks = ",".join("?" * len(carried["reindexed"])) or "NULL"
    carried_uses = con.execute(
        "SELECT COUNT(*) FROM keyword_mentions m JOIN keywords k ON k.id = m.keyword_id"
        f" WHERE k.normalized_term = ? AND m.article_id NOT IN ({marks})",
        (planted["plain_term"], *carried["reindexed"]),
    ).fetchone()[0]
    con.close()
    assert carried_uses, "no CARRIED article mentions the shared term, so its resolution is untested"
    # The ingest-vs-re-index convention: no carried mention keeps the exporter's city.
    assert not any(r[7] for r in snap["mentions"]), "a mention kept the ingest city"


# --- what is refused, and why ------------------------------------------------ #

def test_a_backup_without_stamps_carries_nothing(backup, tmp_path, monkeypatch):
    """Every backup made before this change: option (a), unchanged."""
    old = tmp_path / "old.db"
    shutil.copyfile(backup, old)
    con = sqlite3.connect(old)
    con.execute("DELETE FROM article_index_stamps")
    con.commit()
    con.close()
    target = tmp_path / "t.db"
    _schema(target)
    out = _restore(old, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    plan = out["counts"]["_derived_carry"]
    assert plan.get("carried") is None and plan["stamped"] == 0, plan
    assert sorted(out["reindexed"]) == sorted(out["inserted"])


def test_a_backup_without_an_article_index_is_declined_not_scanned(backup, tmp_path, monkeypatch):
    """The carry reaches each article's incoming rows through an index led by
    article_id. Without one, every window would scan the whole incoming table -- so it
    declines, says why, and the merge runs exactly as option (a)."""
    bare = tmp_path / "bare.db"
    shutil.copyfile(backup, bare)
    con = sqlite3.connect(bare)
    for (name,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'keyword_mentions'"
        " AND sql IS NOT NULL"
    ).fetchall():
        first = con.execute(f'PRAGMA index_info("{name}")').fetchone()[2]
        if first == "article_id":
            con.execute(f'DROP INDEX "{name}"')
    con.commit()
    con.close()
    target = tmp_path / "t.db"
    _schema(target)
    out = _restore(bare, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    plan = out["counts"]["_derived_carry"]
    assert "article_id" in plan.get("reason", ""), plan
    assert out["counts"]["keyword_mentions"]["new"] == 0
    assert sorted(out["reindexed"]) == sorted(out["inserted"])


def test_a_foreign_engine_carries_nothing(backup, tmp_path, monkeypatch):
    foreign = tmp_path / "foreign.db"
    shutil.copyfile(backup, foreign)
    con = sqlite3.connect(foreign)
    con.execute("UPDATE article_index_stamps SET engine = 'e1-' || substr(engine, 4, 31) || 'x'")
    con.commit()
    con.close()
    target = tmp_path / "t.db"
    _schema(target)
    out = _restore(foreign, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    assert out["counts"]["_derived_carry"]["stamped"] == 0
    assert out["counts"]["keyword_mentions"]["new"] == 0


def test_the_switch_turns_the_carry_off(backup, tmp_path, monkeypatch):
    target = tmp_path / "t.db"
    _schema(target)
    out = _restore(backup, target, tmp_path / "w.db", carry=False, monkeypatch=monkeypatch)
    plan = out["counts"]["_derived_carry"]
    assert "OO_CARRY_DERIVED" in plan["reason"]
    assert out["counts"]["keyword_mentions"]["new"] == 0


def test_an_article_edited_after_it_was_indexed_is_refused(backup, tmp_path, monkeypatch):
    """The stamp says which inputs its rows came from. A title edited afterwards (a wiki
    revision, an adopted field) means a re-index would read different inputs."""
    edited = tmp_path / "edited.db"
    shutil.copyfile(backup, edited)
    con = _writer(edited)
    con.execute("UPDATE articles SET title = title || ' (updated)' WHERE hash = 'h0000'")
    con.commit()
    con.close()
    target = tmp_path / "t.db"
    _schema(target)
    out = _restore(edited, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    plan = out["counts"]["_derived_carry"]
    assert plan["refused"]["inputs_changed"] == 1, plan
    assert plan["carried"]["articles"] == len(_ARTICLES) - 1
    assert len(out["reindexed"]) == 1


def test_a_forged_collision_is_refused_not_fatal(backup, tmp_path, monkeypatch):
    """Two incoming mentions of ONE article naming two keyword rows that share a term.
    A real pass cannot write that (it would collide on the exporter's own unique index),
    so only a hand-edited or damaged backup can -- and without the guard the carried
    INSERT would hit the unique (keyword_id, article_id) index here and abort the WHOLE
    merge. Refused, and re-indexed instead."""
    forged = tmp_path / "forged.db"
    shutil.copyfile(backup, forged)
    con = sqlite3.connect(forged)
    aid = con.execute("SELECT id FROM articles WHERE hash = 'h0001'").fetchone()[0]
    con.execute(
        "INSERT INTO keywords (term, normalized_term, language, frequency, is_ngram,"
        " ngram_size, is_entity, mention_count, article_count)"
        " VALUES ('budget', 'budget', 'fr', 0, 0, 1, 0, 0, 0)"
    )
    kid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.execute(
        "INSERT INTO keyword_mentions (keyword_id, article_id, count, first_offset)"
        " VALUES (?, ?, 1, 0)", (kid, aid),
    )
    con.commit()
    con.close()
    target = tmp_path / "t.db"
    _schema(target)
    out = _restore(forged, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    plan = out["counts"]["_derived_carry"]
    assert plan["refused"]["keyword_collision"] == 1, plan
    assert len(out["reindexed"]) == 1


def test_a_stamp_is_never_copied_only_written_for_what_was_carried(backup, tmp_path, monkeypatch):
    target = tmp_path / "populated.db"
    _populated_target(target, backup)
    out = _restore(backup, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    # Re-index nothing, to see the merge's own writes.
    con = sqlite3.connect(tmp_path / "w.db")
    try:
        engines = {r[0] for r in con.execute("SELECT engine FROM article_index_stamps")}
        n_stamps = con.execute("SELECT COUNT(*) FROM article_index_stamps").fetchone()[0]
    finally:
        con.close()
    assert engines == {baseline_engine_id()}
    # carried articles, plus the ones the post-swap re-index certified in _restore
    assert n_stamps == out["counts"]["_derived_carry"]["carried"]["articles"] + len(out["reindexed"])


# --- bookkeeping: the batch, the backlog, the counters, provenance ---------- #

def test_a_fully_carried_batch_is_complete_at_merge(backup, tmp_path, monkeypatch):
    target = tmp_path / "t.db"
    _schema(target)
    out = _restore(backup, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    assert out["status"] == _STATUS_REINDEXED


def test_a_partly_carried_batch_stays_merged_and_the_backlog_counts_only_what_is_owed(
    backup, tmp_path, monkeypatch
):
    target = tmp_path / "populated.db"
    _populated_target(target, backup)
    working = tmp_path / "w.db"
    shutil.copyfile(target, working)
    monkeypatch.setenv("OO_CARRY_DERIVED", "1")
    counts, batch_id = merge_corpus(backup, working, _BATCH_META)
    carried = counts["_derived_carry"]["carried"]["articles"]
    con = sqlite3.connect(working)
    try:
        status = con.execute("SELECT status FROM merge_batches WHERE id = ?", (batch_id,)).fetchone()[0]
        row = con.execute(
            _BACKLOG_SQL.replace(":s", "?").replace(":engine", "?"),
            (baseline_engine_id(), _STATUS_MERGED),
        ).fetchone()
        inserted = con.execute(
            "SELECT COUNT(*) FROM merged_rows WHERE batch_id = ? AND table_name = 'articles'",
            (batch_id,),
        ).fetchone()[0]
    finally:
        con.close()
    assert status == _STATUS_MERGED
    assert row[2] == inserted and row[3] == carried
    assert row[2] - row[3] == inserted - carried > 0


def test_the_keyword_counters_equal_the_mentions_after_a_carry(backup, tmp_path, monkeypatch):
    target = tmp_path / "t.db"
    _schema(target)
    _restore(backup, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    con = sqlite3.connect(tmp_path / "w.db")
    try:
        drift = con.execute(
            "SELECT k.id, k.mention_count, k.article_count, COALESCE(SUM(m.count), 0),"
            " COUNT(m.id) FROM keywords k LEFT JOIN keyword_mentions m ON m.keyword_id = k.id"
            " GROUP BY k.id HAVING k.mention_count <> COALESCE(SUM(m.count), 0)"
            " OR k.article_count <> COUNT(m.id)"
        ).fetchall()
    finally:
        con.close()
    assert not drift, f"counters disagree with the mentions they count: {drift[:5]}"


def test_carried_rows_leave_no_provenance_but_their_articles_do(backup, tmp_path, monkeypatch):
    """~92 provenance rows per article would cost more than the rows they describe; a
    carried row's provenance is its article's, which is recorded."""
    target = tmp_path / "t.db"
    _schema(target)
    out = _restore(backup, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    con = sqlite3.connect(tmp_path / "w.db")
    try:
        tables = {r[0] for r in con.execute(
            "SELECT DISTINCT table_name FROM merged_rows WHERE batch_id = ?", (out["batch_id"],)
        )}
    finally:
        con.close()
    assert "articles" in tables
    assert not tables & {"keyword_mentions", "article_mentioned_places", "article_entities",
                         "article_index_stamps"}


def test_a_leftover_stamp_on_a_reused_id_cannot_certify_a_new_article(backup, tmp_path, monkeypatch):
    """SQLite hands the highest rowid out again after it is deleted. A stamp that outlived
    its article (deleted with foreign keys off) must not certify whatever lands on that id
    next -- the post-swap re-index would skip it and it would have no keywords."""
    target = tmp_path / "t.db"
    _schema(target)
    engine, s = _session(target)
    try:
        src = Source(name="Other", domain="other.example")
        s.add(src)
        s.flush()
        gone = Article(url="https://other.example/x", canonical_url="https://other.example/x",
                       source_id=src.id, title="gone", content="gone", hash="gone",
                       created_at=datetime.now(UTC))
        s.add(gone)
        s.flush()
        s.add(ArticleIndexStamp(article_id=gone.id, engine=baseline_engine_id(),
                                inputs="i1-" + "0" * 32))
        s.commit()
        gone_id = gone.id
    finally:
        s.close()
        engine.dispose()
    con = _writer(target)
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("DELETE FROM articles WHERE id = ?", (gone_id,))
    con.commit()
    con.close()
    # Nothing carries: every inserted article must be re-indexed, INCLUDING the one that
    # lands on the reused id.
    monkeypatch.setenv("OO_CARRY_DERIVED", "0")
    working = tmp_path / "w.db"
    shutil.copyfile(target, working)
    counts, batch_id = merge_corpus(backup, working, _BATCH_META)
    con = sqlite3.connect(working)
    try:
        reused = con.execute(
            "SELECT row_id FROM merged_rows WHERE batch_id = ? AND table_name = 'articles'"
            " AND row_id = ?", (batch_id, gone_id),
        ).fetchone()
        stamp = con.execute(
            "SELECT 1 FROM article_index_stamps WHERE article_id = ?", (gone_id,)
        ).fetchone()
    finally:
        con.close()
    assert reused, "the fixture did not reuse the id, so this proves nothing"
    assert stamp is None, "a leftover stamp survived onto a newly inserted article"


def test_the_post_swap_re_index_skips_an_article_already_certified(monkeypatch):
    """Through the REAL reindex_imported_articles against the app's store -- the file
    tests above replicate its selection, and a replica can agree with itself while the
    real function drifts (PR 5's lesson: pin the wiring)."""
    from src.backup import merge as merge_mod
    from src.database.models import KeywordMention, MergeBatch, MergedRow
    from src.database.session import init_db, session_scope

    init_db()
    made: list[int] = []
    batch_id = None
    try:
        with session_scope() as s:
            src = s.query(Source).filter_by(domain="carry-skip.test").first()
            if src is None:
                src = Source(name="Carry Skip", domain="carry-skip.test")
                s.add(src)
                s.flush()
            for i in range(2):
                a = Article(url=f"https://carry-skip.test/{i}",
                            canonical_url=f"https://carry-skip.test/{i}", source_id=src.id,
                            title=f"Skip {i}", content="Energy prices and the budget.",
                            hash=f"carry-skip-{i}-{datetime.now(UTC).timestamp()}",
                            language="en", created_at=datetime.now(UTC))
                s.add(a)
                s.flush()
                made.append(a.id)
            batch = MergeBatch(artifact_kind="oo-backup-2", origin_fingerprint="t", status="merged")
            s.add(batch)
            s.flush()
            batch_id = batch.id
            for aid in made:
                s.add(MergedRow(batch_id=batch_id, table_name="articles", row_id=aid))
            # The first article arrives CERTIFIED by this engine (as a carry leaves it).
            s.add(ArticleIndexStamp(article_id=made[0], engine=baseline_engine_id(),
                                    inputs="i1-" + "0" * 32))
            s.commit()

        seen: list[list[int]] = []
        import src.analytics.store as store_mod

        real = store_mod.reindex_articles

        def _spy(session, *, article_ids, **kw):
            seen.append(list(article_ids))
            return real(session, article_ids=article_ids, **kw)

        # The backlog, through BOTH readers: one article owed, one certified.
        mine = [b for b in merge_mod.reindex_backlog()["batches"] if b["batch_id"] == batch_id]
        assert mine and mine[0]["articles"] == 1 and mine[0]["certified"] == 1, mine
        pend = [b for b in merge_mod.pending_reindex_batches() if b["batch_id"] == batch_id]
        assert pend and pend[0]["articles"] == 1 and pend[0]["certified"] == 1, pend

        monkeypatch.setattr(store_mod, "reindex_articles", _spy)
        out = merge_mod.reindex_imported_articles(batch_id, commit_batch=1, workers=0)
        assert seen == [[made[1]]], f"the certified article was re-indexed: {seen}"
        assert out["already_certified"] == 1
    finally:
        with session_scope() as s:
            for aid in made:
                s.query(ArticleIndexStamp).filter_by(article_id=aid).delete()
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


def test_carried_timestamps_are_stored_in_the_orms_own_format(backup, tmp_path, monkeypatch):
    """One format per column. A '+00:00' suffix in rows the carry wrote beside offset-free
    rows the ORM wrote is two formats in one column, and every reader assumes one."""
    import re

    target = tmp_path / "t.db"
    _schema(target)
    _restore(backup, target, tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    shape = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}$")
    con = sqlite3.connect(tmp_path / "w.db")
    try:
        for table, col in (("keyword_mentions", "created_at"), ("article_mentioned_places", "created_at"),
                           ("article_entities", "created_at"), ("article_index_stamps", "stamped_at")):
            bad = [v for (v,) in con.execute(f"SELECT {col} FROM {table}") if not shape.match(v or "")]
            assert not bad, f"{table}.{col} holds a second timestamp format: {bad[:3]}"
    finally:
        con.close()
