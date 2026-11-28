"""Row 434: ``index_article`` resolves an article's keywords as columns, not ``Keyword`` objects.

The writer's ``_prefetch_keywords`` built and tracked one ORM object per kept term, and each batch commit expired them
all; ``_prefetch_keyword_rows`` reads the same rows as plain values. The contract is that nothing an article gets
changes: these tests run the same articles through the new read and through the old ORM read (patched back in) and
compare every stored column except the write clocks -- keywords, their baseline tags, the mention rows and each
article's top keyword -- across the cases where the two reads could drift: duplicate rows sharing a term (the
lowest-id and language rules), an entity upgrade of a stored row, an upgrade of a row this same article creates, a
second article in the same uncommitted batch, a re-index that changes an article's terms, and both counter shapes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.analytics import store
from src.analytics.extract import ExtractedTerm
from src.database.models import Article, Base, Keyword, Source
from tests._app_engine import app_sqlite_engine


class _Ex:
    name = "baseline"


def _t(norm: str, kind: str = "term", count: int = 1, term: str | None = None) -> ExtractedTerm:
    return ExtractedTerm(term=term or norm, normalized=norm, kind=kind, count=count, first_offset=count)


def _session(path):
    engine = app_sqlite_engine(path, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, autoflush=False)()


def _seed(s) -> list[Article]:
    src = Source(name="Row 434 Source", domain="r434.example")
    s.add(src)
    s.flush()
    # Rows sharing a term: two in English (the lower id must win), one in Spanish, one with no language yet.
    for term, lang, ent in (
        ("error", "es", False),
        ("error", "en", False),
        ("error", "en", False),
        ("paris", None, False),
        ("paris", "fr", True),
        ("acme", "en", False),
        ("zeta", "en", False),
    ):
        s.add(Keyword(term=term, normalized_term=term, language=lang, frequency=0, is_entity=ent,
                      entity_type=("org" if ent else None), is_ngram=False, ngram_size=1, extractor="old"))
    now = datetime.now(UTC)
    arts = []
    for i, lang in enumerate(("en", "en", "fr", None, "es")):
        u = f"https://r434.example/{i}"
        a = Article(url=u, canonical_url=u, source_id=src.id, title=f"T{i}", content="x", hash=u, language=lang,
                    created_at=now, updated_at=now)
        s.add(a)
        arts.append(a)
    s.commit()
    return arts


PASS_1 = [
    # article 0 (en): an upgrade of a stored row, a brand-new term and a brand-new entity
    [_t("error", count=3), _t("acme", "org", 2, "ACME"), _t("newterm", count=1), _t("fresh", "person", 2, "Fresh")],
    # article 1 (en), same uncommitted batch: the row article 0 upgraded, and an upgrade of the row it created
    [_t("acme", "person", 1, "Acme"), _t("newterm", "org", 4, "NewTerm"), _t("zeta", count=2), _t("two words", count=1)],
    # article 2 (fr): the language rule picks the fr row, never the en one
    [_t("paris", "location", 5, "Paris"), _t("error", count=1)],
    # article 3 (unknown language): the plain lowest-id rule
    [_t("error", count=2), _t("paris", count=1)],
    # article 4 (es)
    [_t("error", count=1), _t("nuevo", "person", 1, "Nuevo")],
]
PASS_2 = {
    0: [_t("error", count=1), _t("zeta", "org", 3, "Zeta"), _t("other", count=2)],  # changed terms: kept, updated, gone, new
    2: [_t("paris", "location", 5, "Paris")],
}


def _run(path, *, old_read: bool, counters: bool, monkeypatch) -> dict:
    with monkeypatch.context() as m:
        if old_read:
            m.setattr(store, "_prefetch_keyword_rows", store._prefetch_keywords)
        s = _session(path)
        arts = _seed(s)
        # A Keyword this session already holds when an upgrade of its row is written (the identity map's copy).
        held = s.query(Keyword).filter_by(normalized_term="zeta").one()
        for a, terms in zip(arts, PASS_1, strict=True):
            store.index_article(s, a, extractor=_Ex(), scope="keywords", commit=False, precomputed_terms=terms,
                                precomputed_sentiment=(0.1, "positive"), precomputed_www={}, maintain_counters=counters)
        s.commit()
        assert held.is_entity is False  # loaded again, in memory, before the upgrade of its row
        for i, terms in PASS_2.items():
            store.index_article(s, arts[i], extractor=_Ex(), scope="keywords", commit=False, precomputed_terms=terms,
                                precomputed_sentiment=(0.1, "positive"), precomputed_www={}, maintain_counters=counters)
        assert held.is_entity is True and held.entity_type == "org", "the held object sees the upgrade of its row"
        s.commit()
        out = {
            "keywords": s.execute(text(
                "SELECT id, term, normalized_term, language, frequency, is_entity, entity_type, is_ngram, ngram_size, "
                "extractor, mention_count, article_count FROM keywords ORDER BY id")).all(),
            "tags": s.execute(text("SELECT keyword_id, axis, tag, source FROM keyword_tags ORDER BY 1, 2, 3")).all(),
            "mentions": s.execute(text(
                "SELECT id, keyword_id, article_id, count, first_offset, observed_on, country, city, language, "
                "source_id, extractor FROM keyword_mentions ORDER BY id")).all(),
            "articles": s.execute(text(
                "SELECT id, top_keyword_id, top_keyword_count, top_keyword_tied_n, sentiment_score, sentiment_label "
                "FROM articles ORDER BY id")).all(),
        }
        s.close()
        return out


@pytest.mark.parametrize("counters", [False, True], ids=["drain-deferred-counters", "inline-counters"])
def test_the_column_read_writes_exactly_what_the_orm_read_wrote(tmp_path, monkeypatch, counters):
    new = _run(tmp_path / "new.db", old_read=False, counters=counters, monkeypatch=monkeypatch)
    old = _run(tmp_path / "old.db", old_read=True, counters=counters, monkeypatch=monkeypatch)
    assert new == old
    kw = {(r.normalized_term, r.language): r for r in new["keywords"]}
    # The cases are really exercised, not vacuously equal.
    assert kw[("acme", "en")].is_entity and kw[("acme", "en")].entity_type == "org"
    assert kw[("fresh", "en")].is_entity and kw[("fresh", "en")].entity_type == "person"
    en_errors = sorted(r.id for r in new["keywords"] if r.normalized_term == "error" and r.language == "en")
    used = {m.keyword_id for m in new["mentions"]}
    assert en_errors[0] in used and en_errors[1] not in used, "the lowest-id English row takes the mentions"


def test_the_writer_builds_no_keyword_object_for_a_stored_term(tmp_path):
    s = _session(tmp_path / "n.db")
    arts = _seed(s)
    store.index_article(s, arts[1], extractor=_Ex(), scope="keywords", commit=False,
                        precomputed_terms=[_t("zeta", count=2), _t("acme", count=1)],
                        precomputed_sentiment=(None, None), precomputed_www={}, maintain_counters=False)
    held = [o for o in s.identity_map.values() if isinstance(o, Keyword)]
    assert held == [], "stored keywords are read as columns; no Keyword enters the session"
    s.rollback()
    s.close()


def test_the_column_read_keeps_the_lowest_id_and_language_rules(tmp_path):
    s = _session(tmp_path / "r.db")
    _seed(s)
    terms = ["error", "paris", "zeta", "missing"]
    for lang in ("en", "es", "fr", None):
        new = {k: v.id for k, v in store._prefetch_keyword_rows(s, terms, language=lang).items()}
        old = {k: v.id for k, v in store._prefetch_keywords(s, terms, language=lang).items()}
        assert new == old, lang
    s.close()


def test_a_rolled_back_upgrade_leaves_a_held_keyword_as_stored(tmp_path):
    """Row 434 read: an upgrade written by the UPDATE and rolled back with the article's savepoint (the ingest batch's
    begin_nested) must not leave a Keyword this session holds saying is_entity=True."""
    s = _session(tmp_path / "rb.db")
    arts = _seed(s)
    for a, terms in zip(arts, PASS_1, strict=True):
        store.index_article(s, a, extractor=_Ex(), scope="keywords", commit=False, precomputed_terms=terms,
                            precomputed_sentiment=(0.1, "positive"), precomputed_www={}, maintain_counters=False)
    s.commit()
    held = s.query(Keyword).filter_by(normalized_term="zeta").one()
    assert held.is_entity is False
    i, terms = next((i, t) for i, t in PASS_2.items() if any(x.normalized == "zeta" for x in t))
    sp = s.begin_nested()
    store.index_article(s, arts[i], extractor=_Ex(), scope="keywords", commit=False, precomputed_terms=terms,
                        precomputed_sentiment=(0.1, "positive"), precomputed_www={}, maintain_counters=False)
    assert held.is_entity is True and held.entity_type == "org", "the held object sees the upgrade while it stands"
    sp.rollback()
    assert held.is_entity is False and held.entity_type is None, "and the stored value after the savepoint rolls back"
    s.close()
