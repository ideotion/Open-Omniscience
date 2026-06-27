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
import re
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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
        with write_lock():
            session.execute(text("PRAGMA analysis_limit=1000"))
            session.execute(text("PRAGMA optimize"))
            session.commit()
        out["planner"] = True
    except Exception:  # noqa: BLE001 - a tuning step must never break the caller
        session.rollback()
        _LOG.warning("planner optimize failed", exc_info=True)
    return out


# Upper bound on candidate ids pulled from FTS before structured filters apply.
# Generous for a single-user corpus; prevents pathological memory use.
_MAX_CANDIDATES = 20000


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
) -> list[int] | None:
    """Return article ids matching ``query``, ranked best-first (BM25F).

    Ranking is FTS5 bm25 with per-column weights (title vs body, :func:`_bm25_weights`) —
    keyword-engine P5.1: a title keyword is a stronger relevance signal than a body
    mention. ``None`` means "no text constraint" (empty/positive-less query) -- distinct
    from ``[]`` which means "searched, matched nothing".

    ``weights`` (title, body) OVERRIDES the env-configured default for one call — a
    thread-safe seam to A/B a weight set over a gold set (``ir_eval.bm25f_weight_ab``)
    without mutating the process-wide env. ``None`` uses the configured default.
    """
    match = build_match(query)
    if match is None:
        return None
    wt, wb = weights if weights is not None else _bm25_weights()
    rows = session.execute(
        text(
            "SELECT rowid FROM article_fts WHERE article_fts MATCH :q "
            "ORDER BY bm25(article_fts, :wt, :wb) LIMIT :lim"
        ),
        {"q": match, "wt": wt, "wb": wb, "lim": limit},
    ).fetchall()
    return [r[0] for r in rows]
