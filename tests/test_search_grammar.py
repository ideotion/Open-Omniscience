"""The advanced search grammar's token class (S05-01 S1/S2; Q603, Q604, Q610-Q613).

Three kinds of test, and the brief names each:

* a PARSER TABLE -- query in, MATCH out, pinned string for string;
* NEGATIVE SPACE -- FTS5 syntax smuggled inside a field value, a NEAR argument or a
  prefix must come out quoted (or be refused), never as syntax. The check is structural:
  strip every quoted string out of the MATCH and what remains may only be syntax this
  module writes itself;
* the MUTATION CHECK, by name -- with ``_quote`` replaced by the identity, the same
  negative-space check must FAIL. A guard that stays green when the thing it guards is
  removed guards nothing.

Plus the SQL half: the field filters and the exact toggle against a real FTS5 table.
"""

from __future__ import annotations

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database import fts
from src.database.fts import SearchQueryError, build_match, parse_query
from src.database.models import Article, Base, Source
from src.database.session import get_db

# --------------------------------------------------------------------------- #
# The parser table
# --------------------------------------------------------------------------- #

TABLE = [
    # plain terms: byte-identical to the legacy parser
    ("climate", '"climate"'),
    ("(climate OR energy) AND policy", '(("climate" OR "energy") AND "policy")'),
    # prefix
    ("clim*", '"clim"*'),
    ("clim**", '"clim"*'),
    ('"new yo"*', '"new yo"*'),
    # NEAR, default and explicit distance, phrases inside, clamping
    ("NEAR(climate energy)", 'NEAR("climate" "energy", 10)'),
    ("near(climate energy, 3)", 'NEAR("climate" "energy", 3)'),
    ('NEAR(climate "energy policy", 5)', 'NEAR("climate" "energy policy", 5)'),
    ("NEAR(a b, 99999)", 'NEAR("a" "b", 1000)'),
    ("NEAR(a OR b, 2)", 'NEAR("a" "b", 2)'),  # operators inside NEAR are dropped
    ("NEAR(solo)", '"solo"'),  # one item is just a term
    # title: in the index
    ("title:climate", 'title : ("climate")'),
    ('title:"climate talks"', 'title : ("climate talks")'),
    ("title:clim*", '(title : ^ "clim"*)'),
    # combination
    ("title:climate NOT energy", '(title : ("climate")) NOT ("energy")'),
    ("climate NEAR(oil gas) oi*", '("climate" AND NEAR("oil" "gas", 10) AND "oi"*)'),
]


@pytest.mark.parametrize("query,expected", TABLE)
def test_parser_table(query: str, expected: str) -> None:
    assert build_match(query, grammar=True) == expected


def test_near_default_is_the_callers() -> None:
    assert build_match("NEAR(a b)", grammar=True, near_default=4) == 'NEAR("a" "b", 4)'
    # an explicit distance wins over the default
    assert build_match("NEAR(a b, 7)", grammar=True, near_default=4) == 'NEAR("a" "b", 7)'


def test_grammar_off_is_byte_identical_to_the_legacy_parser() -> None:
    """The dump index (and every build_match caller that does not ask) is unchanged."""
    for q, legacy in [
        ("clim*", '"clim*"'),
        ("title:x", '"title:x"'),
        ("NEAR(a b)", '("NEAR" AND ("a" AND "b"))'),
    ]:
        assert build_match(q) == legacy


@pytest.mark.parametrize(
    "query,field,mode,value,negated",
    [
        ("author:smith", "author", "contains", "smith", False),
        ("author:smi*", "author", "prefix", "smi", False),
        ("author:=Smith", "author", "exact", "Smith", False),
        ('source:"le monde"', "source", "contains", "le monde", False),
        ("url:https://x.org/a?b=c", "url", "contains", "https://x.org/a?b=c", False),
        ("tag:=europe", "tag", "exact", "europe", False),
        ("title:=Climate", "title", "exact", "Climate", False),
        ("climate NOT author:smith", "author", "contains", "smith", True),
    ],
)
def test_sql_fields_split_off(query, field, mode, value, negated) -> None:
    parsed = parse_query(query)
    assert len(parsed.fields) == 1
    ff = parsed.fields[0]
    assert (ff.field, ff.mode, ff.value, ff.negated) == (field, mode, value, negated)
    match = build_match(query, grammar=True)
    assert match is None or field not in match.split('"')[0]


@pytest.mark.parametrize("query", ["(a OR author:x)", "a OR url:y", "(tag:x b) OR c", "NOT (a OR source:b)"])
def test_sql_field_outside_the_top_level_is_refused(query) -> None:
    with pytest.raises(SearchQueryError, match="top level"):
        parse_query(query)


def test_short_prefix_is_refused_not_silently_widened() -> None:
    with pytest.raises(SearchQueryError, match="at least 2"):
        build_match("c*", grammar=True)
    with pytest.raises(SearchQueryError, match="at least 2"):
        build_match("title:c*", grammar=True)


def test_negative_only_with_fields_keeps_the_exclusion() -> None:
    parsed = parse_query("author:smith NOT climate")
    assert parsed.negative_only
    assert fts.build_negative_match(parsed) == '"climate"'


def test_regex_is_a_deliberate_omission() -> None:
    """Q613 = a: a slash pattern is characters, never a regex."""
    assert build_match("/clim.*te/", grammar=True) == '"/clim.*te/"'
    from pathlib import Path

    assert "Q613" in Path(fts.__file__).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Negative space, and the mutation check that proves it can fail
# --------------------------------------------------------------------------- #

SMUGGLED = [
    'title:"x" OR y"',
    'title:"a"" OR ""b"',
    'title:{content}',
    'title:"^x"*',
    'author:" OR 1=1 --',
    "url:x) OR (y",
    'NEAR("a" OR b, 3)',
    'NEAR(a" b, 2)',
    'NEAR(a:b c^d, 2)',
    'NEAR({title} x, 1)',
    '"a*b"* c',
    'x NEAR y',
    'tag:"europe" NOT title:"x NEAR(y z)"',
    '"; DROP TABLE articles; --',
    'content:secret',
    '{title content}: x',
]

#: What the renderer may emit OUTSIDE quotes: parentheses, whitespace, the operators,
#: NEAR( ... , n), the prefix star, the initial-token caret and the one column filter.
_SYNTAX_OK = re.compile(r"^(?:\s|\(|\)|AND|OR|NOT|NEAR\(|,\s*\d+\)|\*|\^|title :)*$")


def _outside_quotes(match: str) -> str:
    return re.sub(r'"(?:[^"]|"")*"', "", match)


def _violations(queries) -> list[str]:
    bad = []
    for q in queries:
        try:
            m = build_match(q, grammar=True)
        except SearchQueryError:
            continue  # a refusal is an allowed outcome
        if m is None:
            continue
        rest = _outside_quotes(m)
        if not _SYNTAX_OK.match(rest):
            bad.append(f"{q!r} -> {m!r} (unquoted: {rest!r})")
    return bad


def test_smuggled_syntax_is_quoted_or_refused() -> None:
    assert _violations(SMUGGLED) == []


def test_smuggled_syntax_runs_against_a_real_fts5_table() -> None:
    """Structural cleanliness is the claim; running it is the proof it is valid FTS5."""
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE VIRTUAL TABLE article_fts USING fts5(title, content, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    con.execute("INSERT INTO article_fts(rowid, title, content) VALUES (1, 'x y', 'a b c')")
    for q in SMUGGLED + [q for q, _ in TABLE]:
        try:
            m = build_match(q, grammar=True)
        except SearchQueryError:
            continue
        if m:
            con.execute("SELECT rowid FROM article_fts WHERE article_fts MATCH ?", (m,)).fetchall()


def test_mutation_check_quote_is_the_guard(monkeypatch) -> None:
    """With ``_quote`` gutted, the negative-space check must go RED -- by name."""
    monkeypatch.setattr(fts, "_quote", lambda v: v)
    assert _violations(SMUGGLED), "the guard stayed green with _quote removed"


# --------------------------------------------------------------------------- #
# The SQL half: field filters + the exact toggle, end to end
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path):
    from src.database.fts import ensure_fts
    from src.database.fts_norm import install_pool_hook

    install_pool_hook()
    engine = create_engine(
        f"sqlite:///{tmp_path / 'g.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    TS = sessionmaker(bind=engine, future=True)
    with TS() as s:
        a = Source(name="Le Monde", domain="lemonde.fr", tags="europe, politics")
        b = Source(name="Reuters", domain="reuters.com", tags="markets,world")
        s.add_all([a, b])
        s.flush()
        rows = [
            (a, "https://lemonde.fr/eco/1", "Le café du commerce", "un café serré", "José Martí", 120),
            (a, "https://lemonde.fr/pol/2", "Cafe society", "the cafe opens", None, 900),
            (b, "https://reuters.com/markets/3", "Oil prices", "crude oil and gas prices climb", "Jane Smith", 400),
            (b, "https://reuters.com/world/4", "Gas deal", "gas pipeline deal, oil later", "john smithson", 50),
        ]
        for i, (src, url, title, content, author, wc) in enumerate(rows):
            s.add(Article(
                url=url, canonical_url=url, source_id=src.id, title=title, content=content,
                hash=str(i).ljust(64, "0"), language="fr" if src is a else "en",
                author=author, word_count=wc,
            ))
        s.commit()

    def _db():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _titles(client, **params) -> list[str]:
    r = client.get("/api/articles", params=params)
    assert r.status_code == 200, r.text
    return sorted(x["title"] for x in r.json()["results"])


def test_author_contains_prefix_exact_and_fold(client) -> None:
    assert _titles(client, query="author:smith") == ["Gas deal", "Oil prices"]
    assert _titles(client, query='author:="jane smith"') == ["Oil prices"]  # fold: case
    assert _titles(client, query='author:="jane smith"', exact="true") == []
    assert _titles(client, query='author:="Jane Smith"', exact="true") == ["Oil prices"]
    assert _titles(client, query="author:jose") == ["Le café du commerce"]  # fold: accent
    assert _titles(client, query="author:jose", exact="true") == []
    assert _titles(client, query="author:joh*") == ["Gas deal"]


def test_negated_field_keeps_rows_where_the_column_is_null(client) -> None:
    """``NOT author:smith`` must keep the unattributed article (NOT EXISTS, not NOT(...))."""
    assert _titles(client, query="cafe NOT author:smith") == ["Cafe society", "Le café du commerce"]
    assert _titles(client, query="cafe NOT author:jose") == ["Cafe society"]


def test_url_source_tag_modes(client) -> None:
    assert _titles(client, query="url:/markets/") == ["Oil prices"]
    assert _titles(client, query="url:https://reuters*") == ["Gas deal", "Oil prices"]
    assert _titles(client, query="source:monde") == ["Cafe society", "Le café du commerce"]
    assert _titles(client, query="source:=reuters.com") == ["Gas deal", "Oil prices"]
    assert _titles(client, query="tag:=politics") == ["Cafe society", "Le café du commerce"]
    assert _titles(client, query="tag:=polit") == []  # exact is one whole tag
    assert _titles(client, query="tag:polit*") == ["Cafe society", "Le café du commerce"]
    assert _titles(client, query="tag:=world") == ["Gas deal", "Oil prices"]


def test_field_only_query_is_an_uncapped_browse(client) -> None:
    r = client.get("/api/articles", params={"query": "source:reuters"}).json()
    assert r["total"] == 2
    assert r["ordering"]["by"] == "date"  # nothing to rank: stated as such


def test_exact_toggle_is_the_only_thing_between_e_and_e_acute(client) -> None:
    """S2 acceptance: `é` and `e` differ ONLY when the toggle is on."""
    folded_accent = _titles(client, query="café")
    folded_plain = _titles(client, query="cafe")
    assert folded_accent == folded_plain == ["Cafe society", "Le café du commerce"]
    assert _titles(client, query="café", exact="true") == ["Le café du commerce"]
    assert _titles(client, query="cafe", exact="true") == ["Cafe society"]


def test_prefix_near_and_title_through_the_api(client) -> None:
    assert _titles(client, query="pric*") == ["Oil prices"]
    # "crude oil and gas" (1 token between) vs "gas pipeline deal, oil" (2 between)
    assert _titles(client, query="NEAR(oil gas, 1)") == ["Oil prices"]
    assert _titles(client, query="NEAR(oil gas)") == ["Gas deal", "Oil prices"]
    assert _titles(client, query="NEAR(oil gas)", near="1") == ["Oil prices"]
    assert _titles(client, query="title:gas") == ["Gas deal"]
    assert _titles(client, query='title:="gas deal"') == ["Gas deal"]
    assert _titles(client, query='title:="gas deal"', exact="true") == []


def test_misplaced_field_is_a_400_with_the_sentence(client) -> None:
    r = client.get("/api/articles", params={"query": "oil OR author:smith"})
    assert r.status_code == 400
    assert "top level" in r.json()["detail"]
