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

import re
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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


def _render(node) -> str | None:
    if node is None:
        return None
    if isinstance(node, _Term):
        return _quote(node.value)
    if isinstance(node, _Or):
        parts = [p for p in (_render(c) for c in node.children) if p]
        if not parts:
            return None
        return "(" + " OR ".join(parts) + ")"
    if isinstance(node, _AndGroup):
        inc = [p for p in (_render(c) for c in node.includes) if p]
        exc = [p for p in (_render(c) for c in node.excludes) if p]
        if not inc:
            # FTS5 MATCH cannot express a purely-negative query; ignore the
            # exclusions rather than error. (Caller may treat None as "no match".)
            return None
        body = "(" + " AND ".join(inc) + ")"
        if exc:
            body = body + " NOT (" + " OR ".join(exc) + ")"
        return body
    raise AssertionError(f"unknown node type: {type(node)!r}")


def build_match(query: str | None) -> str | None:
    """Translate a user Boolean query into a safe FTS5 MATCH expression.

    Returns ``None`` when the query has no searchable positive content (empty,
    whitespace, punctuation-only, or purely negative). Raises ``SearchQueryError``
    on structurally invalid input (e.g. unbalanced parentheses).
    """
    if not query or not query.strip():
        return None
    tokens = _tokenize(query)
    if not tokens:
        return None
    ast = _Parser(tokens).parse()
    return _render(ast)


# --------------------------------------------------------------------------- #
# FTS5 virtual table maintenance + ranked search
# --------------------------------------------------------------------------- #

# External-content FTS5 table mirroring articles(title, content). External content
# means FTS5 stores only the index, not a second copy of the text.
_FTS_DDL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS article_fts USING fts5(
        title, content,
        content='articles', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    # Keep the index in sync with the base table.
    """
    CREATE TRIGGER IF NOT EXISTS article_fts_ai AFTER INSERT ON articles BEGIN
        INSERT INTO article_fts(rowid, title, content)
        VALUES (new.id, new.title, new.content);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS article_fts_ad AFTER DELETE ON articles BEGIN
        INSERT INTO article_fts(article_fts, rowid, title, content)
        VALUES ('delete', old.id, old.title, old.content);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS article_fts_au AFTER UPDATE ON articles BEGIN
        INSERT INTO article_fts(article_fts, rowid, title, content)
        VALUES ('delete', old.id, old.title, old.content);
        INSERT INTO article_fts(rowid, title, content)
        VALUES (new.id, new.title, new.content);
    END
    """,
]


def ensure_fts(engine: Engine) -> None:
    """Create the FTS5 virtual table + sync triggers and (re)build the index.

    No-op for non-SQLite engines (PostgreSQL would use its own tsvector path).
    Safe to call repeatedly; called from ``init_db``.
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        for ddl in _FTS_DDL:
            conn.execute(text(ddl))
        # Rebuild from base table so pre-existing rows are indexed.
        conn.execute(text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))


# Upper bound on candidate ids pulled from FTS before structured filters apply.
# Generous for a single-user corpus; prevents pathological memory use.
_MAX_CANDIDATES = 20000


def search_ids(session: Session, query: str | None, limit: int = _MAX_CANDIDATES) -> list[int] | None:
    """Return article ids matching ``query``, ranked best-first (bm25).

    ``None`` means "no text constraint" (empty/positive-less query) -- distinct
    from ``[]`` which means "searched, matched nothing".
    """
    match = build_match(query)
    if match is None:
        return None
    rows = session.execute(
        text(
            "SELECT rowid FROM article_fts WHERE article_fts MATCH :q "
            "ORDER BY rank LIMIT :lim"
        ),
        {"q": match, "lim": limit},
    ).fetchall()
    return [r[0] for r in rows]
