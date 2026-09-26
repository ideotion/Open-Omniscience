"""
Full-text search over the article corpus using SQLite FTS5.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This module replaces the previous string-hack Boolean "parser" (which flattened
parentheses to spaces, ignored OR/NOT, reused the same bind parameter name in a
loop so every word collapsed to the last value, and ran user input through a SQL
keyword blocklist that silently corrupted queries like "oil prices DROP").

Two responsibilities:

1. ``build_match`` -- translate a user's Boolean query (AND / OR / NOT, quoted
   phrases, parentheses with correct precedence) into a *safe, fully-parenthesised
   FTS5 MATCH expression*. Every bare term is emitted as a quoted FTS5 string, so
   stray punctuation (``&``, ``*``, ``:`` ...) can never be misread as an operator
   or cause a syntax error, and nothing is ever stripped. The result is passed to
   SQLite as a single bound parameter, so there is no SQL injection surface.

2. ``ensure_fts`` / ``search_ids`` -- maintain an external-content FTS5 virtual
   table mirroring ``articles(title, content)`` (kept in sync by triggers) and run
   ranked MATCH queries against it.

Precedence implemented (standard Boolean): parentheses override; otherwise
NOT binds tightest, then AND (also the implicit operator between adjacent terms),
then OR. So ``(a OR b) AND c`` differs from ``a OR (b AND c)`` differs from
``a OR b AND c``.
"""

from __future__ import annotations

import logging
import os as _os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.database.fts_norm import SEGMENTERS as _SEGMENTERS

_LOG = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Query parsing: user Boolean syntax -> AST -> safe FTS5 MATCH string
# --------------------------------------------------------------------------- #

_OPERATORS = {"AND", "OR", "NOT"}
# A token is: a "quoted phrase", a parenthesis, or a run of non-space/paren/quote.
_TOKEN_RE = re.compile(r'"[^"]*"|\(|\)|[^\s()"]+')
# Characters that carry searchable content (anything else tokenizes to nothing).
_HAS_WORD_CHAR = re.compile(r"\w", re.UNICODE)


class SearchQueryError(ValueError):
    """Raised when a search query cannot be parsed (e.g. unbalanced parentheses)."""


@dataclass
class _Term:
    value: str  # the raw text (phrase contents or a single word)


@dataclass
class _Or:
    children: list


@dataclass
class _AndGroup:
    """A conjunction with optional exclusions: (include AND ...) NOT (exclude OR ...)."""

    includes: list = field(default_factory=list)
    excludes: list = field(default_factory=list)


def _tokenize(query: str) -> list[str]:
    return _TOKEN_RE.findall(query)


class _Parser:
    """Recursive-descent parser producing an AST of _Or / _AndGroup / _Term."""

    def __init__(self, tokens: list[str]):
        self._tokens = tokens
        self._i = 0

    def _peek(self):
        return self._tokens[self._i] if self._i < len(self._tokens) else None

    def _next(self):
        tok = self._tokens[self._i]
        self._i += 1
        return tok

    def parse(self):
        node = self._parse_or()
        if self._peek() is not None:
            # Leftover almost always means an unbalanced ')'.
            raise SearchQueryError(f"unexpected token: {self._peek()!r}")
        return node

    def _parse_or(self):
        children = [self._parse_and()]
        while (tok := self._peek()) is not None and tok.upper() == "OR":
            self._next()
            children.append(self._parse_and())
        children = [c for c in children if c is not None]
        if not children:
            return None
        return children[0] if len(children) == 1 else _Or(children)

    def _parse_and(self):
        group = _AndGroup()
        pending_op = "AND"  # operator that applies to the NEXT atom
        while True:
            tok = self._peek()
            if tok is None or tok == ")" or (tok.upper() == "OR"):
                break
            up = tok.upper()
            if up in ("AND", "NOT"):
                pending_op = up
                self._next()
                continue
            atom = self._parse_atom()
            if atom is not None:
                if pending_op == "NOT":
                    group.excludes.append(atom)
                else:
                    group.includes.append(atom)
            pending_op = "AND"  # implicit AND between adjacent atoms
        if not group.includes and not group.excludes:
            return None
        # Collapse a trivial group (single include, no excludes) to its child.
        if len(group.includes) == 1 and not group.excludes:
            return group.includes[0]
        return group

    def _parse_atom(self):
        tok = self._next()
        if tok == "(":
            inner = self._parse_or()
            if self._peek() != ")":
                raise SearchQueryError("unbalanced parentheses: missing ')'")
            self._next()  # consume ')'
            return inner
        if tok == ")":
            raise SearchQueryError("unbalanced parentheses: unexpected ')'")
        if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
            value = tok[1:-1].strip()
        else:
            value = tok
        if not _HAS_WORD_CHAR.search(value):
            # Pure punctuation carries no searchable content -- drop it.
            return None
        return _Term(value)


def _quote(value: str) -> str:
    """Emit a value as an FTS5 string literal (a phrase), escaping embedded quotes.

    Quoting even single words means punctuation inside them (e.g. ``AT&T``) is
    handed to the tokenizer verbatim instead of being parsed as FTS5 syntax.
    """
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


#: The cross-language expansion seam: a query term -> extra literals to OR in beside it.
#: Deliberately a bare callable rather than an import of the ring module -- this file is
#: the Boolean parser and must stay pure and dependency-free; see ``build_match``.
ExpandTerms = Callable[[str], Sequence[str]]

#: The index-shape seam: a literal -> every form it must take to meet the index (the
#: literal first). ``fts_norm.query_variants`` for the article index (Q506/Q507: Arabic
#: folded, Chinese and Japanese segmented); ``None`` for an index stored raw, such as the
#: Wikipedia dump index, whose MATCH stays byte-identical.
LiteralVariants = Callable[[str], Sequence["str | tuple[str, ...]"]]

#: How far apart a segmented literal's words may sit, per word. The index holds a
#: compound's sub-words beside it (jieba's search mode, sudachi's short units), so two
#: words adjacent in the text are rarely adjacent in the index; 3 per word leaves room for
#: the sub-words of a compound between them and still keeps the words together.
_NEAR_PER_WORD = 3


def _render_literal(value: str | tuple[str, ...]) -> str:
    """A literal as FTS5 syntax: a string is a phrase; a tuple is words NEAR each other."""
    if isinstance(value, tuple):
        if len(value) == 1:
            return _quote(value[0])
        return "NEAR(" + " ".join(_quote(w) for w in value) + f", {_NEAR_PER_WORD * len(value)})"
    return _quote(value)


def _render_term(node: _Term, expand: ExpandTerms | None, variants: LiteralVariants | None = None) -> str:
    """One parsed term, optionally widened to its cross-language siblings.

    Expansion applies to EXCLUDES as well as includes, and that is deliberate: the unit
    the reader is asking about is the CONCEPT, so ``NOT climate`` means "not this
    concept", in every language the ring covers. Expanding only the positive half would
    make an exclusion mean something narrower than the inclusion beside it, silently.

    Every literal goes through ``_quote``, so a multi-word ring member (fr ``migration
    humaine``) is emitted as an FTS5 phrase rather than two loose words.

    ``variants`` runs AFTER expansion and after its cap, on each literal: it changes the
    shape a literal takes to meet the index, never which literals were asked for, so the
    expansion's disclosure ("expanded to 40 of 63 forms") counts the same forms either way.
    """
    literals: list[str | tuple[str, ...]] = [node.value]
    if expand is not None:
        for extra in expand(node.value):
            if extra and extra not in literals:
                literals.append(extra)
    if variants is not None:
        shaped: list[str | tuple[str, ...]] = []
        for lit in literals:
            for v in variants(lit if isinstance(lit, str) else " ".join(lit)):
                if v and v not in shaped:
                    shaped.append(v)
        literals = shaped or literals
    if len(literals) == 1:
        return _render_literal(literals[0])
    return "(" + " OR ".join(_render_literal(v) for v in literals) + ")"


def _render(node, expand: ExpandTerms | None = None, variants: LiteralVariants | None = None) -> str | None:
    if node is None:
        return None
    if isinstance(node, _Term):
        return _render_term(node, expand, variants)
    if isinstance(node, _Or):
        parts = [p for p in (_render(c, expand, variants) for c in node.children) if p]
        if not parts:
            return None
        return "(" + " OR ".join(parts) + ")"
    if isinstance(node, _AndGroup):
        inc = [p for p in (_render(c, expand, variants) for c in node.includes) if p]
        exc = [p for p in (_render(c, expand, variants) for c in node.excludes) if p]
        if not inc:
            # FTS5 MATCH cannot express a purely-negative query; ignore the
            # exclusions rather than error. (Caller may treat None as "no match".)
            return None
        body = "(" + " AND ".join(inc) + ")"
        if exc:
            body = body + " NOT (" + " OR ".join(exc) + ")"
        return body
    raise AssertionError(f"unknown node type: {type(node)!r}")


def build_match(
    query: str | None,
    *,
    expand: ExpandTerms | None = None,
    variants: LiteralVariants | None = None,
) -> str | None:
    """Translate a user Boolean query into a safe FTS5 MATCH expression.

    Returns ``None`` when the query has no searchable positive content (empty,
    whitespace, punctuation-only, or purely negative). Raises ``SearchQueryError``
    on structurally invalid input (e.g. unbalanced parentheses).

    ``expand`` is the cross-language hook (R1, 2026-09-05). It is a plain callable
    ``term -> extra literals``, so this module stays ring-unaware and pure -- the ring
    knowledge lives in ``src/analytics/equivalence.py`` and is injected, which is also
    what lets the caller read back WHICH terms were expanded and publish it. ``None``
    (the default) leaves the emitted MATCH byte-identical to before the hook existed.

    ``variants`` is the index-shape hook (:data:`LiteralVariants`); for a query with no
    Arabic, Chinese or Japanese in it the article index's variants are the literal alone,
    so the MATCH is byte-identical there too.
    """
    if not query or not query.strip():
        return None
    tokens = _tokenize(query)
    if not tokens:
        return None
    ast = _Parser(tokens).parse()
    return _render(ast, expand, variants)


# --------------------------------------------------------------------------- #
# FTS5 virtual table maintenance + ranked search
# --------------------------------------------------------------------------- #

# External-content FTS5 table mirroring articles(title, content). External content
# means FTS5 stores only the index, not a second copy of the text.
#
# WHAT THE TRIGGERS INDEX (Q506 🔒 = b, Q507 = a; ``fts_norm``). Not the stored text itself
# but ``oo_fts_norm(text, mask)``: Arabic folded, Chinese and Japanese runs segmented. An
# external-content ``'delete'`` must be handed EXACTLY the values that were indexed, so each
# document indexed differently from its stored text has a row in ``article_fts_norm``: its
# mask, and, when a segmenter produced the values, the values themselves (a segmenter is a
# third-party package whose next dictionary, or whose absence, would give different words;
# the Arabic fold is this code's own and is re-run). No row: indexed raw, which is every
# document indexed before this existed. The functions are registered on every connection
# (``fts_norm.register``); a connection without them cannot write ``articles``, which fails
# loudly rather than corrupting the index.


def _indexed(row: str, col: str) -> str:
    """SQL for the value ``row``'s (``old``/``new``) column is indexed with, read from its
    ``article_fts_norm`` row: kept when a segmenter made it, re-folded when only the Arabic
    fold did, the stored text when there is no row. Mirrors ``fts_norm.indexed_values``."""
    return (
        f"COALESCE((SELECT CASE WHEN n.mask & {_SEGMENTERS} THEN n.{col} "  # nosec B608 - row and col are the literals "old"/"new" and "title"/"content" passed below; _SEGMENTERS is a module int
        f"ELSE oo_fts_norm({row}.{col}, n.mask) END "
        f"FROM article_fts_norm n WHERE n.article_id = {row}.id), {row}.{col})"
    )


# Index ``new`` under this connection's capabilities: record its entry first (the values
# themselves only when a segmenter made them), then index what the record says, so the
# segmenter runs once and the index and the record cannot disagree.
_INDEX_NEW = f"""
        DELETE FROM article_fts_norm WHERE article_id = new.id;
        INSERT INTO article_fts_norm(article_id, mask, title, content)
        SELECT new.id, m,
               CASE WHEN m & {_SEGMENTERS} THEN oo_fts_norm(new.title, m) END,
               CASE WHEN m & {_SEGMENTERS} THEN oo_fts_norm(new.content, m) END
        FROM (SELECT oo_fts_used(new.title, new.content, oo_fts_caps()) AS m) WHERE m != 0;
        INSERT INTO article_fts(rowid, title, content)
        VALUES (new.id, {_indexed("new", "title")}, {_indexed("new", "content")});
"""  # nosec B608 - every interpolation is a module constant (_SEGMENTERS, an int) or a literal row/column name from this file; the trigger bodies take no input

# Remove ``old``'s entry with exactly the values it was indexed with, then its record.
_DELETE_OLD = f"""
        INSERT INTO article_fts(article_fts, rowid, title, content)
        VALUES ('delete', old.id, {_indexed("old", "title")}, {_indexed("old", "content")});
        DELETE FROM article_fts_norm WHERE article_id = old.id;
"""  # nosec B608 - every interpolation is a module constant (_SEGMENTERS, an int) or a literal row/column name from this file; the trigger bodies take no input

_FTS_DDL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS article_fts USING fts5(
        title, content,
        content='articles', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    # The record of each document indexed differently from its stored text. Its name
    # starts with ``article_fts`` so every place that skips the FTS shadow tables by that
    # prefix (backup counts, the merge's table walk) skips it too: its ids are this store's
    # article ids and mean nothing in another, and every rebuild rewrites it.
    """
    CREATE TABLE IF NOT EXISTS article_fts_norm (
        article_id INTEGER PRIMARY KEY,
        mask INTEGER NOT NULL,
        title TEXT,
        content TEXT
    )
    """,
    # Keep the index in sync with the base table.
    f"""
    CREATE TRIGGER IF NOT EXISTS article_fts_ai AFTER INSERT ON articles BEGIN{_INDEX_NEW}    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS article_fts_ad AFTER DELETE ON articles BEGIN{_DELETE_OLD}    END
    """,
    # COLUMN-SCOPED ON PURPOSE -- `OF title, content` (PERF/F2, 2026-09-21 audit
    # docs/audit/15). An UPDATE that touches neither indexed column cannot change
    # what this index holds, so re-indexing the document for one is pure waste. It
    # became the common case on 2026-09-07 (PRH-01): `index_article` stamps
    # `keyword_indexed_at` on EVERY pass, so every re-indexed article UPDATEs its
    # row, and an unscoped trigger answered that by deleting and re-inserting the
    # document in a 1.34 M-document FTS5 index -- measured at 3.3-4.6 ms an article
    # in memory by the 2026-08-03 throughput analysis, which recorded it as a
    # ONE-TIME ingest cost. It has been a PER-PASS cost since, on the encrypted
    # store, for a column the pass never wrote.
    #
    # WHY THIS CANNOT GO STALE: SQLite fires an `UPDATE OF` trigger when a
    # statement's SET list MENTIONS one of the named columns -- not when the value
    # changes. A column can only be written by a statement that names it, so every
    # write to `title`/`content` still re-indexes, and a SET that writes the same
    # value re-indexes too (wasteful, never stale). That is the safe direction.
    f"""
    CREATE TRIGGER IF NOT EXISTS article_fts_au AFTER UPDATE OF title, content ON articles BEGIN{_DELETE_OLD}{_INDEX_NEW}    END
    """,
]

#: The three sync triggers, each of which must call the index transform.
_FTS_TRIGGERS = ("article_fts_ai", "article_fts_ad", "article_fts_au")

#: Name of the update trigger, so the self-heal below and the DDL above cannot drift apart.
_FTS_UPDATE_TRIGGER = "article_fts_au"


def _heal_unscoped_update_trigger(conn) -> bool:
    """Replace a legacy UNSCOPED ``article_fts_au`` with the column-scoped one.

    ``CREATE TRIGGER IF NOT EXISTS`` can never REPLACE a trigger that is already
    there, so without this every store created before the scoping shipped would keep
    the unscoped trigger for the life of the file -- the fix would reach new installs
    only, which is the opposite of where the cost was measured (a 1.34 M-article field
    corpus).

    O(1) AND CORPUS-BLIND, which is the constraint the P0.4 boot fix left behind: one
    ``sqlite_master`` read of one row's stored SQL. It never counts articles, never
    reads content through the codec, and never triggers a rebuild -- dropping and
    re-creating a trigger does not touch the index, so the documents already indexed
    stay indexed.

    Returns True when a legacy trigger was dropped (the caller's DDL then re-creates
    it scoped, inside the same transaction, so no window exists where an UPDATE to
    `title`/`content` could slip past untriggered).
    """
    row = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:n"),
        {"n": _FTS_UPDATE_TRIGGER},
    ).fetchone()
    sql = (row[0] if row else None) or ""
    if not sql:
        return False  # absent -> the DDL below creates the scoped one; nothing to heal
    # Whitespace-insensitive and case-insensitive: the stored SQL is whatever the
    # creating version wrote, and only the SHAPE (is it scoped?) decides.
    if "AFTER UPDATE OF" in " ".join(sql.split()).upper():
        return False  # already scoped
    conn.execute(text(f"DROP TRIGGER {_FTS_UPDATE_TRIGGER}"))
    return True


def _heal_raw_triggers(conn) -> list[str]:
    """Replace sync triggers that index the stored text RAW with the transforming ones.

    Every store created before Q506/Q507 has ``article_fts_ai/ad/au`` indexing
    ``new.title``/``new.content`` as stored, and ``CREATE TRIGGER IF NOT EXISTS`` can never
    replace them. Dropping and re-creating a trigger does not touch the index, and the
    swap is safe at any moment: a document indexed raw has no ``article_fts_norm`` row, so
    the new delete side hands FTS5 its raw values -- exactly what was indexed. Only
    documents written from now on are indexed transformed; the search re-index job
    converts the rest. O(1): three ``sqlite_master`` reads. Returns the names dropped."""
    from src.database.fts_norm import FN_NORM

    dropped: list[str] = []
    for name in _FTS_TRIGGERS:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:n"), {"n": name}
        ).fetchone()
        sql = (row[0] if row else None) or ""
        if sql and FN_NORM not in sql:
            conn.execute(text(f"DROP TRIGGER {name}"))
            dropped.append(name)
    return dropped


def ensure_fts(engine: Engine, *, rebuild: str = "auto") -> str:
    """Create the FTS5 virtual table + sync triggers; (re)build the index ONLY when needed.

    THE UNLOCK-AT-SCALE FIX (P0.4). This runs from ``init_db`` on EVERY unlock. The old
    code unconditionally ran ``INSERT INTO article_fts(article_fts) VALUES ('rebuild')``,
    which for an external-content FTS5 table DELETES the whole index and re-reads every
    article's ``title`` + ``content`` from the base table through the SQLCipher codec — a
    corpus-scaled cost that RECURRED on every boot (measured 981 s → 1,645 s on the field's
    130 GB corpus; an index build would be one-time, this recurred). But the index is kept
    current INCREMENTALLY by the ``article_fts_ai/ad/au`` triggers, so once populated it
    never needs a full rebuild on a normal boot.

    ``rebuild`` decides the rebuild, never the DDL (the table + triggers are always ensured):
      * ``"auto"`` (default) — rebuild only when it is genuinely needed:
        - the FTS table was just created here while the store has articles (a schema
          upgrade: the triggers never fired for rows inserted before the table existed), or
        - the table exists but is EMPTY while articles exist (a past rebuild that never
          completed). Steady-state boots (table present + populated) SKIP the rebuild.
      * ``"always"`` — force a full rebuild (the explicit re-index / index-repair path).
      * ``"never"`` — ensure only the DDL, never rebuild.

    Returns the action taken: ``"rebuilt"`` | ``"skipped"`` | ``"skipped-non-sqlite"``. The
    return names the REBUILD only; the DDL self-heal below
    (:func:`_heal_unscoped_update_trigger`) is orthogonal, costs one ``sqlite_master`` read,
    and is reported in the log rather than in this value so every existing caller and
    assertion on it keeps reading the same three words.

    SCOPE OF THE BOOT SELF-HEAL (measured, deliberate): the boot path self-heals only a
    fully-EMPTY index (docsize == 0 while articles exist) — an O(1) probe. It does NOT try to
    detect a PARTIAL index (some rows indexed, some not) or a CORRUPT one, because the only
    way to detect partialness is to compare the indexed-row count against the article count,
    and ``count(*) FROM articles`` was measured at 74 s cold on a 2.7 GB encrypted corpus (a
    codec-heavy scan) — reintroducing the very corpus-scaled boot cost this fix removes. A
    partial/corrupt index is UNREACHABLE via normal operation anyway (ingest is an atomic
    INSERT + trigger; ``'rebuild'`` is atomic; restore runs a full rebuild in ``verify_copy``;
    re-index never touches article content) — it can arise only from external file corruption
    (e.g. a torn filesystem-copy backup). Those are the ``fts_status`` (D4) diagnostic's job:
    it reports a damaged/incomplete index and the explicit re-index job heals it
    (``rebuild="always"``).

    No-op for non-SQLite engines (PostgreSQL would use its own tsvector path).
    Safe to call repeatedly; called from ``init_db``.
    """
    if engine.dialect.name != "sqlite":
        return "skipped-non-sqlite"
    if rebuild not in ("auto", "always", "never"):
        raise ValueError(f"rebuild must be one of auto|always|never, got {rebuild!r}")
    with engine.begin() as conn:
        # The triggers call the index transform, so THIS connection needs it before any
        # DDL below can run a rebuild through it (``fts_norm.register`` is idempotent;
        # the pool listener gives every later connection the same functions).
        from src.database.fts_norm import register as _register_norm

        _register_norm(conn.connection.dbapi_connection)
        # Was the FTS table ALREADY present before this (idempotent) create? A table that
        # already existed is kept in sync by the triggers; a table we create here has never
        # seen the trigger fire for pre-existing rows.
        existed = (
            conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='article_fts'")
            ).fetchone()
            is not None
        )
        # Heal a legacy unscoped update trigger BEFORE the DDL, so the create below
        # re-makes it scoped in the same transaction (see _heal_unscoped_update_trigger).
        if _heal_unscoped_update_trigger(conn):
            _LOG.info("FTS: replaced the unscoped article_fts_au trigger with the scoped one")
        healed = _heal_raw_triggers(conn)
        if healed:
            _LOG.info("FTS: the sync triggers now index Arabic folded and CJK segmented (%s)", ", ".join(healed))
        for ddl in _FTS_DDL:
            conn.execute(text(ddl))
        action = _decide_fts_rebuild(conn, rebuild, existed)
        if action == "rebuilt":
            rebuild_index(conn)
    return action


#: Articles read per step of a full rebuild (one read of each article's text).
_REBUILD_BATCH = 500

#: The statement every full rebuild starts with. FTS5's own ``'rebuild'`` is never run
#: any more, so this is what a probe looks for to tell whether a rebuild happened.
REBUILD_MARK = "INSERT INTO article_fts(article_fts) VALUES ('delete-all')"


def _dbapi(con):
    """The DB-API connection under ``con`` (a SQLAlchemy ``Connection`` or one already)."""
    inner = getattr(con, "connection", None)
    return getattr(inner, "dbapi_connection", None) or con


def _store_caps(con) -> int:
    """The transforms THIS store's index may be written under: today's capabilities when
    its delete trigger reproduces them, else 0 (index raw).

    Writing the index transformed under a delete trigger that hands FTS5 the RAW text
    would corrupt it on the first delete. That cannot happen in the app, where
    ``ensure_fts`` heals the triggers at every unlock, but a store opened by other means
    (an old working copy, a fixture) must be indexed the way ITS triggers will delete."""
    from src.database.fts_norm import FN_NORM, available_mask

    row = _run(
        con, "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='article_fts_ad'"
    ).fetchone()
    sql = row[0] if row else None
    return available_mask() if isinstance(sql, str) and FN_NORM in sql else 0


def _run(con, sql: str, params=()):
    """Execute on a SQLAlchemy ``Connection`` through ``exec_driver_sql`` (so its events,
    and the probes built on them, see the statement) or on a DB-API connection directly.
    A list of tuples is an executemany on both."""
    if hasattr(con, "exec_driver_sql"):
        return con.exec_driver_sql(sql, params)
    if isinstance(params, list):
        return con.executemany(sql, params)
    return con.execute(sql, params)


def rebuild_index(con) -> int:
    """Rebuild the whole article index THROUGH the transform; return the documents indexed.

    Replaces FTS5's own ``'rebuild'``, which re-reads ``articles`` and indexes the stored
    text raw: after Q506/Q507 that would leave every Arabic, Chinese and Japanese document
    indexed differently from what the triggers' delete side reproduces, and the next delete
    of one would corrupt the index. Here each document is indexed under this process's
    capabilities and its mask recorded, in ONE read of each article's text.

    ``con`` is a SQLAlchemy ``Connection`` or a DB-API connection (the merge's raw one):
    the caller owns the transaction, as it did for ``'rebuild'``."""
    from src.database.fts_norm import register

    register(_dbapi(con))
    caps = _store_caps(con)
    _run(con, REBUILD_MARK)
    if caps:
        _run(con, "DELETE FROM article_fts_norm")
    # The first page has no lower bound: a rowid may be 0 or negative, and a keyset that
    # started from "> 0" would silently leave those out of the rebuilt index.
    last: int | None = None
    n = 0
    while True:
        if last is None:
            rows = _run(
                con, "SELECT id, title, content FROM articles ORDER BY id LIMIT ?", (_REBUILD_BATCH,)
            ).fetchall()
        else:
            rows = _run(
                con,
                "SELECT id, title, content FROM articles WHERE id > ? ORDER BY id LIMIT ?",
                (last, _REBUILD_BATCH),
            ).fetchall()
        if not rows:
            return n
        _index_rows(con, rows, caps)
        n += len(rows)
        last = int(rows[-1][0])


def _index_rows(con, rows, caps: int) -> None:
    """Index ``(id, title, content)`` rows that are NOT in the index yet, through the
    transform, recording each one it changed exactly as the insert trigger does. The one
    place outside the triggers and the search re-index that writes this index."""
    from src.database.fts_norm import SEGMENTERS, index_entry

    if not rows:
        return
    if not caps:  # a store whose triggers index raw: so does this
        _run(con, "INSERT INTO article_fts(rowid, title, content) VALUES (?, ?, ?)", [tuple(r) for r in rows])
        return
    entries = [(r[0], *index_entry(r[1], r[2], caps)) for r in rows]
    _run(
        con,
        "INSERT INTO article_fts(rowid, title, content) VALUES (?, ?, ?)",
        [(aid, t, c) for aid, _m, t, c in entries],
    )
    records = [
        (aid, m, t, c) if m & SEGMENTERS else (aid, m, None, None) for aid, m, t, c in entries if m
    ]
    if records:
        _run(
            con,
            "INSERT OR REPLACE INTO article_fts_norm(article_id, mask, title, content) VALUES (?, ?, ?, ?)",
            records,
        )


def index_articles(con, ids: Sequence[int]) -> int:
    """Index the given articles, which must not be in the index yet (the merge's bulk
    path, run with the insert trigger suspended). Returns how many were indexed."""
    from src.database.fts_norm import register

    if not ids:
        return 0
    register(_dbapi(con))
    rows = _run(
        con,
        "SELECT id, title, content FROM articles WHERE id IN"  # noqa: S608  # nosec B608 - the only interpolation is a placeholder count derived from len(ids); every id is a bound parameter
        f" ({','.join('?' * len(ids))})",
        tuple(ids),
    ).fetchall()
    _index_rows(con, rows, _store_caps(con))
    return len(rows)


def _decide_fts_rebuild(conn, rebuild: str, existed_before: bool) -> str:
    """Decide whether ``ensure_fts`` should run the corpus-scaled ``'rebuild'``.

    All probes here are CHEAP (``LIMIT 1`` / a shadow-table lookup) — none scans the corpus
    or reads article content through the codec, so the decision itself is fast even at 5 TB.

    THE EXTERNAL-CONTENT GOTCHA: ``SELECT rowid FROM article_fts`` reads the *content* table
    (``articles``), NOT the index, so it can NEVER tell "is the index populated?" — it
    returns rows even after ``'delete-all'`` empties the index (verified). The reliable,
    term-independent index-population probe is the FTS5 ``article_fts_docsize`` shadow table
    (one row per indexed document; 0 rows == empty index, verified)."""
    if rebuild == "always":
        return "rebuilt"
    if rebuild == "never":
        return "skipped"
    # auto:
    if not existed_before:
        # Freshly created: index any pre-existing articles the triggers never saw. A no-op
        # when ``articles`` is empty (fresh install / a test that creates FTS then inserts).
        return "rebuilt"
    # Table already existed -> the triggers have kept it current. Only guard the
    # present-but-EMPTY-while-articles-exist case (a rare interrupted past rebuild): search
    # would silently return nothing until a manual re-index, so self-heal it.
    articles_present = (
        conn.execute(text("SELECT 1 FROM articles LIMIT 1")).fetchone() is not None
    )
    if not articles_present:
        return "skipped"
    try:
        index_has_docs = (
            conn.execute(text("SELECT 1 FROM article_fts_docsize LIMIT 1")).fetchone() is not None
        )
    except Exception:  # noqa: BLE001 - a columnsize=0 build has no docsize shadow
        # Cannot cheaply prove the index is empty -> trust the triggers and SKIP rather than
        # risk a corpus-scaled rebuild on a false negative (a false skip only costs a manual
        # re-index; a false rebuild reintroduces the P0.4 slow boot).
        return "skipped"
    return "rebuilt" if not index_has_docs else "skipped"


def optimize_after_bulk(session: Session) -> dict:
    """Tuning pass after a BULK write (a whole-corpus re-index or a large article
    import) — keyword-engine Phase 1.4. Two cheap, gated, SQLite-only steps:

    * FTS5 ``'optimize'`` — merge the external-content FTS index segments that a bulk
      article load churns into many small b-trees, for faster MATCH queries. DISTINCT
      from ``PRAGMA optimize``; a near no-op when the index is already merged (e.g.
      after a keyword-only re-index that never touched ``articles``).
    * ``PRAGMA optimize`` (bounded by ``analysis_limit``) — refresh the query planner's
      statistics after a big ``keyword_mentions`` / ``keywords`` churn so the next
      trending / top / associations queries pick good indexes.

    Both are writes (the FTS merge writes the index; ``PRAGMA optimize`` may run ANALYZE),
    so they take the single-writer gate. Best-effort: a tuning failure (incl. a missing
    FTS table) never breaks the caller. Returns a ``{"fts", "planner"}`` bool tally.

    (The in-memory READ lever is ``cache_size`` — env ``OO_SQLITE_CACHE_MB``, default
    64 MiB, set per connection in ``session.py``; mmap is unavailable under the SQLCipher
    codec, so cache_size is the main one. Left at its memory-conservative default for the
    reference AppVM; raise the env on a larger machine.)"""
    out = {"fts": False, "planner": False}
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return out
    from src.database.writer import write_lock

    try:
        with write_lock():
            session.execute(text("INSERT INTO article_fts(article_fts) VALUES ('optimize')"))
            session.commit()
        out["fts"] = True
    except Exception:  # noqa: BLE001 - a tuning step must never break the caller
        session.rollback()
        _LOG.warning("FTS5 optimize failed", exc_info=True)
    try:
        from src.config.power_profiles import fts_analysis_limit

        _analysis_limit = fts_analysis_limit()  # §7 knob: OO_FTS_ANALYSIS_LIMIT, clamped int.
        with write_lock():
            # nosec B608 - _analysis_limit is a clamped int from power_profiles, never user input;
            # PRAGMA does not accept a bound parameter.
            session.execute(text(f"PRAGMA analysis_limit={_analysis_limit}"))  # noqa: S608
            session.execute(text("PRAGMA optimize"))
            session.commit()
        out["planner"] = True
    except Exception:  # noqa: BLE001 - a tuning step must never break the caller
        session.rollback()
        _LOG.warning("planner optimize failed", exc_info=True)
    return out


def _fts_probe_deadline_s() -> float:
    """Deadline for the cheap FTS health probe (OO_FTS_PROBE_DEADLINE_S, default 5s)."""
    try:
        return max(0.5, float(_os.getenv("OO_FTS_PROBE_DEADLINE_S", "5")))
    except (TypeError, ValueError):
        return 5.0


def _fts_count_deadline_s() -> float:
    """Deadline for the (potentially slow, index-enumerating) FTS row COUNT
    (OO_FTS_COUNT_DEADLINE_S, default 15s)."""
    try:
        return max(0.5, float(_os.getenv("OO_FTS_COUNT_DEADLINE_S", "15")))
    except (TypeError, ValueError):
        return 15.0


def fts_status(session: Session) -> dict:
    """Robust, transaction/timing-safe status of the ``article_fts`` search index (D4).

    PRESENCE is read from ``sqlite_master`` — the authoritative table list, a metadata read
    that never scans and never trips the statement deadline — NOT from a ``COUNT(*)`` over
    the external-content FTS5 index (which enumerates the whole index, can hit the deadline,
    and was then MISREAD as "table absent", contradicting the schema-drift probe that reads
    the same list). So the two probes can no longer disagree silently: both derive presence
    from the schema.

    Returns (SQLite only; ``{"supported": False, ...}`` on another backend):
      * ``present``      — ``article_fts`` is declared in the schema (authoritative); ``None``
        only if even the metadata read failed.
      * ``healthy``      — a cheap bounded probe (``SELECT rowid ... LIMIT 1``) ran without a
        corruption error. ``False`` = the index exists but is DAMAGED (a post-crash malformed
        FTS index — a re-index / ``ensure_fts`` rebuild heals it, the actionable verdict D4
        asked for); ``None`` = present but could not confirm (the probe timed out).
      * ``rows``         — the indexed-row count, or ``None`` when the count timed out /
        errored (``count_status`` says which) — NEVER conflated with absence.
      * ``count_status`` — ok | timed_out | error | skipped.
      * ``error``        — the probe error message when unhealthy / the count failed.

    Callers should run this OUTSIDE any enclosing ``statement_deadline`` block: it manages its
    own bounded deadlines, and nesting the progress-handler-based deadline would clobber the
    outer one on exit.
    """
    from src.database.maintenance import StatementTimeout, statement_deadline

    bind = session.get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") != "sqlite":
        return {
            "supported": False, "present": None, "healthy": None, "rows": None,
            "count_status": "skipped", "error": None,
        }

    out: dict = {
        "supported": True, "present": False, "healthy": None, "rows": None,
        "count_status": "skipped", "error": None,
    }

    # 1) PRESENCE via sqlite_master (fast, authoritative, deadline-proof — a virtual table is
    #    listed with type='table', exactly what schema-drift's get_table_names() reads).
    try:
        row = session.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='article_fts'")
        ).fetchone()
        out["present"] = row is not None
    except Exception as exc:  # noqa: BLE001 - a diagnostic degrades, never crashes
        out["present"] = None
        out["error"] = str(exc)[:200]
        return out
    if not out["present"]:
        return out  # genuinely absent -> init_db()/ensure_fts() recreates it (a re-index heals)

    # 2) HEALTH: a cheap bounded probe that surfaces post-crash corruption FAST (a malformed
    #    FTS index raises here, quickly, distinct from a slow-but-fine large index).
    try:
        with statement_deadline(session, seconds=_fts_probe_deadline_s()):
            session.execute(text("SELECT rowid FROM article_fts LIMIT 1")).fetchone()
        out["healthy"] = True
    except StatementTimeout:
        out["healthy"] = None  # present but too slow to confirm — NOT corruption, NOT absent
        out["count_status"] = "timed_out"
        return out
    except Exception as exc:  # noqa: BLE001 - a corruption error is the actionable signal
        out["healthy"] = False
        out["error"] = str(exc)[:200]
        out["count_status"] = "error"
        return out  # damaged -> don't attempt the heavier COUNT; re-index heals

    # 3) ROWS (best-effort; a slow COUNT is reported as timed_out, never "absent").
    try:
        with statement_deadline(session, seconds=_fts_count_deadline_s()):
            n = session.execute(text("SELECT count(*) FROM article_fts")).scalar()
        out["rows"] = int(n) if n is not None else 0
        out["count_status"] = "ok"
    except StatementTimeout:
        out["count_status"] = "timed_out"
    except Exception as exc:  # noqa: BLE001 - count failure is disclosed, presence stands
        out["count_status"] = "error"
        out["error"] = str(exc)[:200]
    return out


# Upper bound on candidate ids pulled from FTS before structured filters apply.
# Generous for a single-user corpus; prevents pathological memory use.
_MAX_CANDIDATES = 20000

#: The same bound, public: a caller that reports a MATCH TOTAL needs to know whether the
#: list it holds hit the cap (in which case ``len(ids)`` is the cap, not a count) — see
#: :func:`search_total`.
MAX_CANDIDATES = _MAX_CANDIDATES

#: The quarantine gate, shared by :func:`search_ids` and :func:`search_total` so the two
#: can never describe different sets. A correlated EXISTS on the articles PK: one index
#: probe per matched row, no chunking around SQLite's ~999-variable ceiling, and (verified
#: against a real FTS5 table) it leaves the bm25 ordering byte-identical. ``IS NOT 1``
#: keeps a NULL (never judged) row, exactly like ``Article.quarantined.isnot(True)``.
_QUARANTINE_GATE = (
    " AND EXISTS (SELECT 1 FROM articles a WHERE a.id = article_fts.rowid"
    " AND a.quarantined IS NOT 1)"
)


def _bm25_weights() -> tuple[float, float]:
    """BM25F per-column weights (title, body) — keyword-engine P5.1. FTS5's bm25() weights
    each indexed column; a higher weight ranks that column's matches higher (verified:
    bm25(ft,10,1) ranks a title match above a body match, bm25(ft,1,10) flips it). A title
    keyword is a strong relevance signal in news, so title is weighted above body by
    default; both are env-tunable and the change is reversible (set them equal = the old
    flat ``rank``). The weights are bound parameters, never string-formatted into SQL."""
    import os

    def _w(name: str, default: float) -> float:
        try:
            return max(0.0, float(os.getenv(name, str(default))))
        except (TypeError, ValueError):
            return default

    return _w("OO_BM25_TITLE_WEIGHT", 4.0), _w("OO_BM25_BODY_WEIGHT", 1.0)


def search_ids(
    session: Session,
    query: str | None,
    limit: int = _MAX_CANDIDATES,
    *,
    weights: tuple[float, float] | None = None,
    exclude_quarantined: bool = False,
    expand: ExpandTerms | None = None,
) -> list[int] | None:
    """Return article ids matching ``query``, ranked best-first (BM25F).

    Ranking is FTS5 bm25 with per-column weights (title vs body, :func:`_bm25_weights`) —
    keyword-engine P5.1: a title keyword is a stronger relevance signal than a body
    mention. ``None`` means "no text constraint" (empty/positive-less query) -- distinct
    from ``[]`` which means "searched, matched nothing".

    ``weights`` (title, body) OVERRIDES the env-configured default for one call — a
    thread-safe seam to A/B a weight set over a gold set (``ir_eval.bm25f_weight_ab``)
    without mutating the process-wide env. ``None`` uses the configured default.

    ``exclude_quarantined`` drops articles the app itself judged not-an-article
    (S3.2 nav-soup screening) IN SQL, so the caller's count and its rows describe
    the SAME set -- the property ``source_type_facets`` once claimed and did not
    keep. It is OPT-IN rather than the default because ``search_ids`` also backs
    non-user-facing callers (eval harnesses, parity checks) that must see the raw
    match set; user-facing search surfaces pass ``True``.

    The filter is a correlated ``EXISTS`` on the articles PK rather than an
    ``id IN (...)`` list: it costs one index probe per matched row, needs no
    chunking around SQLite's ~999-variable ceiling, and — verified against a real
    FTS5 table — leaves the bm25 ordering byte-identical. ``IS NOT 1`` keeps a
    NULL (never judged) row, exactly like ``Article.quarantined.isnot(True)``
    everywhere else.

    ``expand`` is the cross-language hook (see :func:`build_match`); ``None`` leaves the
    emitted MATCH and therefore the returned ids byte-identical to before it existed.
    """
    from src.database.fts_norm import query_variants

    match = build_match(query, expand=expand, variants=query_variants)
    if match is None:
        return None
    wt, wb = weights if weights is not None else _bm25_weights()
    gate = _QUARANTINE_GATE if exclude_quarantined else ""
    # `gate` is one of the two constant fragments chosen just above -- never a
    # caller-supplied value, and every value is bound. bandit attributes B608 to the
    # first line of the concatenation, so the marker belongs HERE and not on the
    # enclosing text(...) call, where it silently does nothing.
    sql = (
        "SELECT rowid FROM article_fts WHERE article_fts MATCH :q"  # nosec B608 - only the constant `gate` fragment above is concatenated; every value is a bound :param
        + gate
        + " ORDER BY bm25(article_fts, :wt, :wb) LIMIT :lim"
    )
    rows = session.execute(
        text(sql),
        {"q": match, "wt": wt, "wb": wb, "lim": limit},
    ).fetchall()
    return [r[0] for r in rows]


def search_total(
    session: Session,
    query: str | None,
    *,
    exclude_quarantined: bool = False,
    expand: ExpandTerms | None = None,
) -> int | None:
    """The EXACT number of articles matching ``query`` — no cap, no ranking.

    WHY THIS EXISTS: :func:`search_ids` takes a ``limit`` (default
    :data:`MAX_CANDIDATES`), so a caller that reports ``len(ids)`` as a match TOTAL
    publishes the CAP as a count the moment the query matches more than that. The
    maintainer's 2026-07-18 ruling is explicit — "a cap may bound which EXAMPLES are
    listed; it must never bound a displayed NUMBER" — and asked for a sweep for any
    other displayed figure that is secretly a cap. The omnibar's articles group was
    one (it reported a flat 20000 on any broad query over a large corpus).

    Counting is much cheaper than ranking because no bm25 score is computed and
    nothing is sorted: measured on a 300k-doc FTS5 fixture with a term matching
    essentially the whole corpus, ``count(*)`` is **96 ms** against **415 ms** for
    the capped ranked fetch it supplements.

    ``None`` mirrors :func:`search_ids`: "no text constraint", distinct from ``0``
    ("searched, matched nothing"). The quarantine gate is the SAME shared fragment
    :func:`search_ids` uses, so the count can never describe a different set than
    the rows — the property ``source_type_facets`` once claimed and did not keep.

    ``expand`` is the SAME cross-language hook :func:`search_ids` takes, and passing it
    is what keeps the count and the rows describing one set. It was accepted and then
    DROPPED here for as long as it existed — the parameter was declared, the caller at
    ``search_omni.py`` passed it with a comment explaining exactly why, and the body
    called ``build_match(query)`` without it. Live-reproduced on a seven-article fixture
    (3 en ``climate``, 2 fr ``climat``, 2 de ``Klima``): ``search_ids`` returned **7**
    ids and ``search_total`` answered **3**, i.e. the omnibar's "exact total" described
    the literal query while its rows described the concept. Q515 = b (exact, uncapped)
    is a ruling about THIS function, so the fix belongs here rather than at each caller.
    The index-shape variants are passed for the same reason: rows and count, one set.
    """
    from src.database.fts_norm import query_variants

    match = build_match(query, expand=expand, variants=query_variants)
    if match is None:
        return None
    gate = _QUARANTINE_GATE if exclude_quarantined else ""
    # As in search_ids: `gate` is one of two CONSTANT fragments, never caller-supplied,
    # and the only value is a bound :param. bandit attributes B608 to the first line of
    # the concatenation, so the marker belongs here.
    sql = (
        "SELECT count(*) FROM article_fts WHERE article_fts MATCH :q"  # nosec B608 - only the constant `gate` fragment above is concatenated; the query is a bound :param
        + gate
    )
    row = session.execute(text(sql), {"q": match}).fetchone()
    return int(row[0]) if row else 0
