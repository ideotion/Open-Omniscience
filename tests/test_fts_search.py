"""
Behavioral tests for full-text search (Action Plan Phase 1.5).

Two layers:
  * build_match: the Boolean -> FTS5 translator, as a pure function (no DB).
  * end-to-end: an FTS5 index over real rows, proving AND/OR/NOT semantics,
    parenthesised precedence, phrase search, and that NOTHING is stripped
    (the old code mangled "AT&T" and "oil prices DROP").
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.database.fts import SearchQueryError, build_match, ensure_fts, search_ids
from src.database.models import Article, Base, Source

# --------------------------------------------------------------------------- #
# Pure translator
# --------------------------------------------------------------------------- #

def test_build_match_quotes_terms_and_neutralises_punctuation():
    # Every term is emitted as an FTS5 phrase literal -> punctuation is safe.
    assert build_match("AT&T") == '"AT&T"'
    assert build_match("oil prices DROP") == '("oil" AND "prices" AND "DROP")'


def test_build_match_operators():
    assert build_match("a OR b") == '("a" OR "b")'
    assert build_match("a AND b") == '("a" AND "b")'
    assert build_match("a NOT b") == '("a") NOT ("b")'


def test_build_match_precedence_is_explicit_and_parenthesised():
    # Parentheses must be honoured (the old parser deleted them).
    assert build_match("(a OR b) AND c") == '(("a" OR "b") AND "c")'
    assert build_match("a OR (b AND c)") == '("a" OR ("b" AND "c"))'
    # ... and the two must not render the same.
    assert build_match("(a OR b) AND c") != build_match("a OR (b AND c)")
    # Implicit AND binds tighter than OR: "a OR b c" == "a OR (b AND c)".
    assert build_match("a OR b c") == '("a" OR ("b" AND "c"))'


def test_build_match_phrases_and_empties():
    assert build_match('"climate change"') == '"climate change"'
    assert build_match("") is None
    assert build_match("   ") is None
    assert build_match("&&&") is None          # punctuation-only -> no content
    assert build_match("NOT b") is None        # purely negative is inexpressible


def test_build_match_rejects_unbalanced_parens():
    with pytest.raises(SearchQueryError):
        build_match("(a OR b")
    with pytest.raises(SearchQueryError):
        build_match("a OR b)")


# --------------------------------------------------------------------------- #
# End-to-end against a real FTS5 index
# --------------------------------------------------------------------------- #

@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fts.db'}", future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    src = Source(name="Test", domain="t.example")
    s.add(src)
    s.flush()
    docs = {
        "alpha": "the quick brown fox",
        "beta": "a lazy brown dog",
        "gamma": "quick silver fox runs",
        "delta": "oil prices DROP sharply today",
        "epsilon": "merger talks at AT&T continue",
    }
    for key, content in docs.items():
        s.add(Article(
            url=f"https://t.example/{key}",
            canonical_url=f"https://t.example/{key}",
            source_id=src.id,
            title=key,
            content=content,
            hash=key.ljust(64, "0"),
        ))
    s.commit()
    yield s
    s.close()


def _titles(session, query):
    ids = search_ids(session, query)
    if not ids:
        return set()
    rows = session.query(Article).filter(Article.id.in_(ids)).all()
    return {r.title for r in rows}


def test_and_is_intersection(session):
    assert _titles(session, "quick AND fox") == {"alpha", "gamma"}
    assert _titles(session, "quick brown") == {"alpha"}  # implicit AND


def test_or_is_union(session):
    assert _titles(session, "fox OR dog") == {"alpha", "gamma", "beta"}


def test_not_excludes(session):
    assert _titles(session, "brown NOT dog") == {"alpha"}


def test_parenthesised_precedence(session):
    # (quick OR lazy) AND brown -> alpha (quick+brown) and beta (lazy+brown)
    assert _titles(session, "(quick OR lazy) AND brown") == {"alpha", "beta"}
    # quick OR (lazy AND brown) -> quick docs + beta
    assert _titles(session, "quick OR (lazy AND brown)") == {"alpha", "gamma", "beta"}


def test_no_keyword_stripping(session):
    # "DROP" is a normal word, not stripped as a SQL keyword.
    assert _titles(session, "oil prices DROP") == {"delta"}
    # "AT&T" is tokenised, not HTML-escaped or mangled.
    assert _titles(session, "AT&T") == {"epsilon"}


def test_phrase_search(session):
    assert _titles(session, '"brown fox"') == {"alpha"}
    assert _titles(session, '"brown dog"') == {"beta"}


def test_triggers_keep_index_in_sync(session):
    # Delete a row -> it leaves the index.
    art = session.query(Article).filter_by(title="alpha").one()
    session.delete(art)
    session.commit()
    assert _titles(session, "quick AND fox") == {"gamma"}
    # Insert a new matching row -> it enters the index.
    src_id = session.query(Source).first().id
    session.add(Article(
        url="https://t.example/zeta", canonical_url="https://t.example/zeta",
        source_id=src_id, title="zeta", content="quick brown fox returns",
        hash="zeta".ljust(64, "0"),
    ))
    session.commit()
    assert _titles(session, "quick AND fox") == {"gamma", "zeta"}
