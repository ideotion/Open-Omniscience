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
from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Query parsing: user Boolean syntax -> AST -> safe FTS5 MATCH string
# --------------------------------------------------------------------------- #

_OPERATORS = {"AND", "OR", "NOT"}
# A token is: a "quoted phrase", a parenthesis, or a run of non-space/paren/quote.
_TOKEN_RE = re.compile(r'"[^"]*"|\(|\)|[^\s()"]+')

# --------------------------------------------------------------------------- #
# THE ADVANCED GRAMMAR'S TOKEN CLASS (S05-01 S1; Q603, Q604, Q611, Q612, Q613).
#
# Three FTS5-native forms and five field filters, recognised ONLY when a caller asks for
# the grammar (``grammar=True``) -- the article search does, the Wikipedia dump index does
# not, so its MATCH stays byte-identical. Each form is recognised here as a WHOLE token and
# carried into the AST as a typed node; nothing the reader typed is ever pasted into the
# MATCH string. Every value still leaves through ``_quote``, and the only unquoted things
# the renderer emits are FTS5 syntax this module writes itself (``NEAR(``, ``*``, ``^``, a
# column name from ``_FTS_COLUMNS``) and an integer it parsed. That is the whole of the
# injection argument, and ``tests/test_search_grammar.py`` mutation-checks it by name.
#
#   word*  "a phrase"*        prefix (FTS5 native). At least two characters before the *.
#   NEAR(a b, N)  NEAR(a b)   the words within N tokens of each other (FTS5 native). N is
#                             optional; without it the caller's ``near_default`` applies
#                             (Q612: 10, and the reader can change the default).
#   field:value               field search; ``field`` is title, author, source, url or tag.
#   field:value*              ... "starts with"
#   field:=value              ... "is exactly"
#                             (no suffix = "contains"). Values may be "quoted phrases".
#
# ``title`` contains / starts-with run INSIDE the FTS index (the column filter ``title :``
# and the initial-token marker ``^``). ``author``, ``source``, ``url``, ``tag`` and
# ``title:=`` are NOT indexed columns of ``article_fts`` -- the index holds title and content
# only, and recreating it is out of this slice's reach -- so they compile to SQL predicates
# with bound values (:func:`field_where`). A SQL predicate cannot sit inside an FTS5 OR, so
# those five may be combined only with AND / NOT at the top level of a query; anywhere else
# they are refused with a sentence, never silently widened.
#
# DELIBERATE OMISSION (Q613 = a): regular expressions. FTS5 has no regex operator, so a
# regex would be a full scan of every article's text on every search -- the scan-on-type the
# search surface promises never to do -- and a pattern language is also a second injection
# surface this grammar exists to keep closed. ``title:/x/`` is simply a contains-search for
# the characters "/x/".
# --------------------------------------------------------------------------- #

#: The field filters, in the order the builder lists them.
FIELDS = ("title", "author", "source", "url", "tag")
#: The match modes a field filter takes (Q611 note): the text form of each is the suffix.
FIELD_MODES = ("contains", "prefix", "exact")
#: Fields the FTS index can answer itself, per mode. Everything else is a SQL predicate.
_FTS_FIELD_MODES = {("title", "contains"), ("title", "prefix")}
#: The NEAR distance when a query gives none (Q612 = a). Callers pass the reader's own.
NEAR_DEFAULT = 10
#: Bounds on a NEAR distance. FTS5 accepts any integer; a stepper and a sane ceiling.
NEAR_MIN, NEAR_MAX = 0, 1000
#: The shortest prefix accepted. A one-character prefix expands to a large share of the
#: index's vocabulary on a real corpus, and FTS5 then reads every one of those doclists.
PREFIX_MIN_CHARS = 2

_GRAMMAR_TOKEN_RE = re.compile(
    r'(?i:NEAR)\([^()]*\)'
    r'|(?i:title|author|source|url|tag):=?(?:"[^"]*"\**|[^\s()"]+)'
    r'|"[^"]*"\**'
    r'|\(|\)|[^\s()"]+'
)
_NEAR_DIST_RE = re.compile(r'\s*(-?\d+)\s*')
_NEAR_ITEM_RE = re.compile(r'"[^"]*"|[^\s",]+')
_FIELD_RE = re.compile(r'(?is)(title|author|source|url|tag):(=?)(.*)')
# Characters that carry searchable content (anything else tokenizes to nothing).
_HAS_WORD_CHAR = re.compile(r"\w", re.UNICODE)


class SearchQueryError(ValueError):
    """Raised when a search query cannot be parsed (e.g. unbalanced parentheses)."""


@dataclass
class _Term:
    value: str  # the raw text (phrase contents or a single word)


@dataclass
class _Prefix:
    """``word*`` / ``"a phrase"*``: the (last) word as a prefix (FTS5 native)."""

    value: str


@dataclass
class _Near:
    """``NEAR(a b, N)``: every item within ``distance`` tokens (``None`` = the default)."""

    items: list
    distance: int | None = None


@dataclass
class FieldFilter:
    """``field:value`` in one of three match modes (Q611). Public: the SQL half of a
    parsed query is a list of these, and the builder's chips are the same shape."""

    field: str
    mode: str  # contains | prefix | exact
    value: str
    negated: bool = False

    @property
    def in_index(self) -> bool:
        """True when the FTS index answers this filter itself (title contains / prefix)."""
        return (self.field, self.mode) in _FTS_FIELD_MODES


@dataclass
class _Or:
    children: list


@dataclass
class _AndGroup:
    """A conjunction with optional exclusions: (include AND ...) NOT (exclude OR ...)."""

    includes: list = field(default_factory=list)
    excludes: list = field(default_factory=list)


def _tokenize(query: str, grammar: bool = False) -> list[str]:
    return (_GRAMMAR_TOKEN_RE if grammar else _TOKEN_RE).findall(query)


def _near_node(tok: str):
    """A ``NEAR(...)`` token -> ``_Near`` (or a plain term / nothing when it has <2 items).

    The body is split into quoted phrases and bare words; commas, quotes and parentheses
    never survive into an item, so an item is always a value for ``_quote`` and never FTS5
    syntax. A trailing ``, N`` is the distance, clamped to ``[NEAR_MIN, NEAR_MAX]``."""
    # The token regex only yields `NEAR(` ... `)` here, so the body is sliced, not matched:
    # a `NEAR\((.*)\)` pattern was flagged polynomial by CodeQL on `near(near(a...`.
    body = tok[5:-1] if tok[:5].upper() == "NEAR(" and tok.endswith(")") else ""
    distance: int | None = None
    # The distance is whatever follows the LAST comma, when that is a bare integer. Split
    # with rpartition rather than one lazy regex over the whole body: `^(.*?),\s*(-?\d+)`
    # backtracks polynomially on a long comma-free body (CodeQL py/polynomial-redos), and
    # the body is the reader's typed text.
    head, sep, last = body.rpartition(",")
    tail = _NEAR_DIST_RE.fullmatch(last) if sep else None
    if tail:
        body = head
        distance = max(NEAR_MIN, min(NEAR_MAX, int(tail.group(1))))
    items = []
    for raw in _NEAR_ITEM_RE.findall(body):
        v = raw[1:-1].strip() if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2 else raw
        if v.upper() in _OPERATORS or not _HAS_WORD_CHAR.search(v):
            continue
        items.append(v)
    if not items:
        return None
    if len(items) == 1:
        return _Term(items[0])
    return _Near(items, distance)


def _field_node(tok: str):
    """``field:value`` / ``field:value*`` / ``field:=value`` -> ``FieldFilter`` (or None)."""
    m = _FIELD_RE.fullmatch(tok)
    if m is None:  # pragma: no cover - the token regex only yields matching tokens
        return None
    field_name, eq, raw = m.group(1).lower(), m.group(2), m.group(3)
    mode = "exact" if eq else "contains"
    if not eq and raw.endswith("*"):
        mode = "prefix"
        raw = raw.rstrip("*")
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        raw = raw[1:-1]
    value = raw.strip()
    if not _HAS_WORD_CHAR.search(value):
        return None
    if mode == "prefix" and field_name == "title" and len(value.strip()) < PREFIX_MIN_CHARS:
        raise SearchQueryError(
            f"a prefix needs at least {PREFIX_MIN_CHARS} characters before the *"
        )
    return FieldFilter(field_name, mode, value)


class _Parser:
    """Recursive-descent parser producing an AST of _Or / _AndGroup / _Term (and, with
    ``grammar=True``, _Prefix / _Near / FieldFilter)."""

    def __init__(self, tokens: list[str], grammar: bool = False):
        self._tokens = tokens
        self._i = 0
        self._grammar = grammar

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
        prefix = False
        if self._grammar:
            if tok[:5].upper() == "NEAR(" and tok.endswith(")"):
                return _near_node(tok)
            if _FIELD_RE.fullmatch(tok) and ":" in tok:
                return _field_node(tok)
            if tok.endswith("*") and tok.rstrip("*"):
                prefix = True
                tok = tok.rstrip("*")
        if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
            value = tok[1:-1].strip()
        else:
            value = tok
        if prefix:
            if not _HAS_WORD_CHAR.search(value):
                return None
            if len(value.strip()) < PREFIX_MIN_CHARS:
                raise SearchQueryError(
                    f"a prefix needs at least {PREFIX_MIN_CHARS} characters before the *"
                )
            return _Prefix(value)
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


def _string_forms(value: str, variants: LiteralVariants | None) -> list[str]:
    """The STRING forms a literal takes to meet the index (the literal first).

    Prefix and NEAR items take only these: a segmented (tuple) form is already a NEAR of
    its own, and nesting one NEAR inside another is not FTS5 syntax. What that leaves out
    is disclosed in the builder's hover: a prefix or NEAR over Chinese or Japanese text
    matches the index as typed, not re-segmented."""
    forms = [value]
    if variants is not None:
        for v in variants(value):
            if isinstance(v, str) and v and v not in forms:
                forms.append(v)
    return forms


def _render_prefix(node: _Prefix, variants: LiteralVariants | None) -> str:
    forms = [_quote(f) + "*" for f in _string_forms(node.value, variants)]
    return forms[0] if len(forms) == 1 else "(" + " OR ".join(forms) + ")"


def _render_near(node: _Near, variants: LiteralVariants | None, near_default: int) -> str:
    distance = node.distance if node.distance is not None else near_default
    distance = max(NEAR_MIN, min(NEAR_MAX, int(distance)))
    per_item = [_string_forms(v, variants) for v in node.items]
    # Two readings at most: every item as typed, and every item in its index form (the
    # Arabic fold). A cartesian product of forms would multiply for no gain -- an item's
    # forms differ only when the fold changed it, and the index holds ONE of the two.
    readings = [[f[0] for f in per_item]]
    folded = [f[-1] for f in per_item]
    if folded != readings[0]:
        readings.append(folded)
    parts = ["NEAR(" + " ".join(_quote(w) for w in r) + f", {distance})" for r in readings]
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def _render_field(
    node: FieldFilter, expand: ExpandTerms | None, variants: LiteralVariants | None
) -> str | None:
    """A field filter the index answers itself: ``title :`` contains / starts with."""
    if not node.in_index:  # pragma: no cover - SQL fields are split off before rendering
        raise AssertionError(f"field {node.field}:{node.mode} is not an index filter")
    if node.mode == "prefix":
        forms = [_quote(f) + "*" for f in _string_forms(node.value, variants)]
        return "(" + " OR ".join(f"{node.field} : ^ {f}" for f in forms) + ")"
    return f"{node.field} : " + _parenthesise(_render_term(_Term(node.value), expand, variants))


def _parenthesise(expr: str) -> str:
    return expr if expr.startswith("(") and expr.endswith(")") else "(" + expr + ")"


def _render(
    node,
    expand: ExpandTerms | None = None,
    variants: LiteralVariants | None = None,
    near_default: int = NEAR_DEFAULT,
) -> str | None:
    if node is None:
        return None
    if isinstance(node, _Term):
        return _render_term(node, expand, variants)
    if isinstance(node, _Prefix):
        return _render_prefix(node, variants)
    if isinstance(node, _Near):
        return _render_near(node, variants, near_default)
    if isinstance(node, FieldFilter):
        return _render_field(node, expand, variants)
    if isinstance(node, _Or):
        parts = [p for p in (_render(c, expand, variants, near_default) for c in node.children) if p]
        if not parts:
            return None
        return "(" + " OR ".join(parts) + ")"
    if isinstance(node, _AndGroup):
        inc = [p for p in (_render(c, expand, variants, near_default) for c in node.includes) if p]
        exc = [p for p in (_render(c, expand, variants, near_default) for c in node.excludes) if p]
        if not inc:
            # FTS5 MATCH cannot express a purely-negative query; ignore the
            # exclusions rather than error. (Caller may treat None as "no match".)
            return None
        body = "(" + " AND ".join(inc) + ")"
        if exc:
            body = body + " NOT (" + " OR ".join(exc) + ")"
        return body
    raise AssertionError(f"unknown node type: {type(node)!r}")


def _is_sql_field(node) -> bool:
    return isinstance(node, FieldFilter) and not node.in_index


def _contains_sql_field(node) -> bool:
    if _is_sql_field(node):
        return True
    if isinstance(node, _Or):
        return any(_contains_sql_field(c) for c in node.children)
    if isinstance(node, _AndGroup):
        return any(_contains_sql_field(c) for c in node.includes + node.excludes)
    return False


_SQL_FIELD_PLACEMENT = (
    "author:, source:, url:, tag: and title:= can only be combined with AND or NOT at the "
    "top level of a query, never inside OR or parentheses"
)


@dataclass
class ParsedQuery:
    """A query split into the part the FTS index answers and the part SQL answers.

    ``ast`` is the FTS part (``None`` when there is none); ``fields`` are the SQL field
    filters, each marked ``negated`` when it sat after a NOT. ``negative_only`` is True
    when, once the fields left, the FTS part holds exclusions and nothing else -- the one
    shape FTS5 cannot run on its own (``author:x NOT climate``), which the caller then
    runs as an exclusion (:func:`build_negative_match`)."""

    ast: object | None
    fields: list = field(default_factory=list)
    negative_only: bool = False


def parse_query(query: str | None, *, grammar: bool = True) -> ParsedQuery:
    """Parse ``query`` and split its SQL field filters off the FTS part.

    Raises :class:`SearchQueryError` on structurally invalid input, and on a SQL field
    anywhere but the top level (:data:`_SQL_FIELD_PLACEMENT`)."""
    if not query or not query.strip():
        return ParsedQuery(None)
    tokens = _tokenize(query, grammar)
    if not tokens:
        return ParsedQuery(None)
    root = _Parser(tokens, grammar).parse()
    if not grammar:
        return ParsedQuery(root)
    fields: list[FieldFilter] = []
    if _is_sql_field(root):
        return ParsedQuery(None, [root])
    if isinstance(root, _AndGroup):
        keep_inc, keep_exc = [], []
        for c in root.includes:
            if _is_sql_field(c):
                fields.append(c)
            elif _contains_sql_field(c):
                raise SearchQueryError(_SQL_FIELD_PLACEMENT)
            else:
                keep_inc.append(c)
        for c in root.excludes:
            if _is_sql_field(c):
                fields.append(FieldFilter(c.field, c.mode, c.value, negated=True))
            elif _contains_sql_field(c):
                raise SearchQueryError(_SQL_FIELD_PLACEMENT)
            else:
                keep_exc.append(c)
        if not keep_inc and not keep_exc:
            return ParsedQuery(None, fields)
        if not keep_inc:
            return ParsedQuery(_AndGroup([], keep_exc), fields, negative_only=True)
        if len(keep_inc) == 1 and not keep_exc:
            return ParsedQuery(keep_inc[0], fields)
        return ParsedQuery(_AndGroup(keep_inc, keep_exc), fields)
    if _contains_sql_field(root):
        raise SearchQueryError(_SQL_FIELD_PLACEMENT)
    return ParsedQuery(root, fields)


def build_negative_match(
    parsed: ParsedQuery,
    *,
    expand: ExpandTerms | None = None,
    variants: LiteralVariants | None = None,
    near_default: int = NEAR_DEFAULT,
) -> str | None:
    """The EXCLUSIONS of a negative-only FTS part as one positive MATCH (their OR), for
    the caller to subtract. ``None`` when the parsed query is not negative-only."""
    if not parsed.negative_only or not isinstance(parsed.ast, _AndGroup):
        return None
    parts = [p for p in (_render(c, expand, variants, near_default) for c in parsed.ast.excludes) if p]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def build_match(
    query: str | None,
    *,
    expand: ExpandTerms | None = None,
    variants: LiteralVariants | None = None,
    grammar: bool = False,
    near_default: int = NEAR_DEFAULT,
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

    ``grammar`` turns on the advanced token class (prefix, NEAR, field filters; see the
    block above :data:`FIELDS`). ``False`` -- the default, and what the Wikipedia dump
    index passes -- keeps the MATCH byte-identical to before it existed. With it on, the
    SQL field filters are NOT in the returned MATCH: :func:`parse_query` hands them back
    separately, and :func:`search_ids` / :func:`search_total` apply them.
    """
    parsed = parse_query(query, grammar=grammar)
    if parsed.negative_only:
        return None
    return _render(parsed.ast, expand, variants, near_default)


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

#: The tokenizer a NEW index is created with (S05-02 S6, R39). ``categories 'L* N* Co M*'`` keeps the combining marks
#: and vowel signs of Devanagari, Bengali and vocalised Arabic INSIDE a word: under the default categories सरकार indexed
#: as सरक + र, so a search for सरक matched सरकार and every word with a matra was shredded. Measured on the SQLCipher the
#: app ships (3.51.1) and on SQLite 3.45.1: सरकार, বাংলা and a vocalised مَدْرَسَةٌ each stay one token and ``remove_diacritics 2``
#: still folds é, ï and the like. A tokenizer is fixed when the table is CREATED, so an index made before this has to be
#: dropped and rebuilt (:func:`rebuild_with_current_tokenizer`); it is never swapped silently at boot.
FTS_TOKENIZER = "unicode61 remove_diacritics 2 categories 'L* N* Co M*'"

#: What every index made before 0.5 was created with.
FTS_TOKENIZER_LEGACY = "unicode61 remove_diacritics 2"


def _tokenize_clause(tokenizer: str) -> str:
    """The ``tokenize=`` option text for ``tokenizer``: FTS5 reads a quote inside it doubled."""
    return "tokenize='" + tokenizer.replace("'", "''") + "'"


def _article_fts_ddl(tokenizer: str = FTS_TOKENIZER) -> str:
    return f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS article_fts USING fts5(
        title, content,
        content='articles', content_rowid='id',
        {_tokenize_clause(tokenizer)}
    )
    """  # nosec B608 - the tokenizer is one of this module's two constants, never input


_FTS_DDL = [
    _article_fts_ddl(),
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
    corpus-scaled cost that RECURRED on every boot (an index build would be one-time, this
    recurred). The field's unlock took 981 s, then 1,645 s, on two consecutive boots on
    2026-07-09 (docs/product/SCALE_ROADMAP.md P0.4; the first export's database was 11.7 GB /
    268,241 articles, the second's size is not recorded). That record is of the unlock as a
    whole and does not split it by phase, so the share of it this rebuild took was never
    measured; the fix was validated afterwards, on the maintainer's live runs (unlock 602 ms in
    docs/product/RELEASE_0.2_GATE.md, 323 ms on 1,048,725 articles / 21.0 GB on 2026-08-12 in
    docs/ledger/shipped.csv). But the index is kept
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

    SCOPE OF THE BOOT SELF-HEAL (deliberate): the boot path self-heals only a
    fully-EMPTY index (docsize == 0 while articles exist) — an O(1) probe. It does NOT try to
    detect a PARTIAL index (some rows indexed, some not) or a CORRUPT one. The way to see a partial one
    whole is to compare the indexed-row count against the article count, and the boot makes no such
    comparison: that is a decision, not a measured necessity, and it is left as it was. What was measured
    (2026-10-27): ``count(1) FROM articles`` is a scan of a covering index (which one is the planner's choice;
    on the measured store it was ``idx_article_created_at``, about four times the pages of the smallest
    candidate at 100,000 articles, so the figure is conservative) and took 0.24 to 0.33 s cold on 1,000,000
    articles (five cold runs, median 0.29 s). LIMITS of that figure: one
    machine, an encrypted (SQLCipher) store on a virtual disk reading 1.3 GB/s, synthetic Latin
    text of 1.3 KB per article, nothing above 1 M, the cost follows the NUMBER of articles and not their
    text, and the plan is the planner's choice, not a promise (``tests/test_fts_status.py`` pins that it is a
    covering-index scan on the real schema). An earlier figure for this count, 74 s on a 2.7 GB encrypted corpus, is not reproduced on
    the current schema and what it timed is not recorded: do not build on it. A
    partial/corrupt index is UNREACHABLE via normal operation anyway (ingest is an atomic
    INSERT + trigger; ``'rebuild'`` is atomic; restore runs a full rebuild in ``verify_copy``;
    re-index never touches article content) — it can arise only from external file corruption
    (e.g. a torn filesystem-copy backup). Those are the ``fts_status`` (D4) diagnostic's job:
    it reports a damaged index, an EMPTY one and, while no article has been ingested since, a PARTIAL one whose
    TAIL is missing (``indexed_documents`` / ``index_state``; the probe it also runs reads the content
    table and cannot see them), and the explicit re-index job heals it (``rebuild="always"``). It repairs nothing
    and is operator-initiated: it never runs at boot, and the boot refusal above stands.

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
        # The explicit re-index is a full rebuild already; it is where an old index gets the current tokenizer. A
        # normal boot never does (``auto``): that would be the corpus-sized cost at every upgrade. The swap runs
        # under a savepoint (``rebuild_with_current_tokenizer``): a bare DROP commits by itself under pysqlite, and a
        # re-index that died after it would leave an empty index.
        swap = rebuild == "always" and existed and fts_tokenizer(conn) == "legacy"
        for ddl in _FTS_DDL:
            conn.execute(text(ddl))
        if swap:
            rebuild_with_current_tokenizer(conn)
            return "rebuilt"
        action = _decide_fts_rebuild(conn, rebuild, existed)
        if action == "rebuilt":
            rebuild_index(conn)
    return action


#: Articles read per step of a full rebuild (one read of each article's text).
_REBUILD_BATCH = 500

#: The statement every full rebuild starts with. FTS5's own ``'rebuild'`` is never run
#: any more, so this is what a probe looks for to tell whether a rebuild happened.
REBUILD_MARK = "INSERT INTO main.article_fts(article_fts) VALUES ('delete-all')"


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
        _run(con, "DELETE FROM main.article_fts_norm")
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


def _tokenizer_of(ddl) -> str:
    """``"current"`` or ``"legacy"`` from an index's own ``CREATE VIRTUAL TABLE`` text (the one place that decides)."""
    sql = str(ddl or "").lower()
    return "current" if "categories" in sql and "m*" in sql else "legacy"


def fts_tokenizer(con) -> str | None:
    """Which tokenizer the article index was created with: ``"current"``, ``"legacy"`` (every index made before 0.5),
    or ``None`` when there is no index. Read from the table's own DDL in ``sqlite_master``: the schema is the truth,
    so there is no marker that could drift from it. ``con`` is a SQLAlchemy ``Connection`` or a DB-API connection."""
    row = _run(con, "SELECT sql FROM sqlite_master WHERE type='table' AND name='article_fts'").fetchone()
    if row is None:
        return None
    return _tokenizer_of(row[0])


def rebuild_with_current_tokenizer(con) -> dict:
    """Make the article index use :data:`FTS_TOKENIZER`, then rebuild it in full. Returns what happened.

    An index made with the legacy tokenizer is dropped and created again (the tokenizer cannot be altered), then
    :func:`rebuild_index` fills it; one that already has the current tokenizer is rebuilt as is. The caller owns the
    transaction, so the drop, the create and the rebuild commit together or not at all: a run that dies half way
    leaves the old index and the old tokenizer, never an empty one. Only for a window the app is stopped in, or an
    explicit re-index: the rebuild reads every article's text through the codec, a cost that grows with the corpus (see :func:`ensure_fts`)."""
    before = fts_tokenizer(con)
    if before is None:
        raise RuntimeError("there is no article index to rebuild")
    # pysqlite opens its transaction before a DML statement and not before DDL, so the drop below would commit by
    # itself; a savepoint makes the drop, the create and the rebuild ONE unit whatever the driver does.
    _run(con, "SAVEPOINT oo_fts_tokenizer")
    try:
        if before == "legacy":
            _run(con, "DROP TABLE main.article_fts")
            _run(con, _article_fts_ddl())
        out = {"tokenizer_before": before, "tokenizer_after": fts_tokenizer(con), "indexed": rebuild_index(con)}
    except BaseException:
        # SQLite can already have rolled the whole transaction back (a full disk, an I/O error): then there is no
        # savepoint to return to, and that second error must not hide the one the caller needs.
        try:
            _run(con, "ROLLBACK TO oo_fts_tokenizer")
            _run(con, "RELEASE oo_fts_tokenizer")
        except Exception:  # noqa: BLE001
            pass
        raise
    _run(con, "RELEASE oo_fts_tokenizer")
    return out


def _index_rows(con, rows, caps: int) -> None:
    """Index ``(id, title, content)`` rows that are NOT in the index yet, through the
    transform, recording each one it changed exactly as the insert trigger does. The one
    place outside the triggers and the search re-index that writes this index. It names ``main`` on
    every write: the merge calls it with the incoming backup attached."""
    from src.database.fts_norm import SEGMENTERS, index_entry

    if not rows:
        return
    if not caps:  # a store whose triggers index raw: so does this
        _run(con, "INSERT INTO main.article_fts(rowid, title, content) VALUES (?, ?, ?)", [tuple(r) for r in rows])
        return
    entries = [(r[0], *index_entry(r[1], r[2], caps)) for r in rows]
    _run(
        con,
        "INSERT INTO main.article_fts(rowid, title, content) VALUES (?, ?, ?)",
        [(aid, t, c) for aid, _m, t, c in entries],
    )
    records = [
        (aid, m, t, c) if m & SEGMENTERS else (aid, m, None, None) for aid, m, t, c in entries if m
    ]
    if records:
        _run(
            con,
            "INSERT OR REPLACE INTO main.article_fts_norm(article_id, mask, title, content) VALUES (?, ?, ?, ?)",
            records,
        )


def index_articles(con, ids: Sequence[int]) -> int:
    """Index the given articles, which must not be in the index yet (the merge's bulk
    path, run with the insert trigger suspended). Returns how many were indexed.

    It must NOT (re)register the transform's SQL functions: it never calls them (the
    transform runs in Python, in ``_index_rows``), and the merge calls it once per chunk
    inside one write transaction, where the second registration fails. SQLite refuses to
    replace a function while a statement is active, and after the first chunk's index
    write FTS5's open blob reader is one -- every import adding more than
    ``_FTS_BULK_BATCH`` (20,000) articles died there (2026-09-27). The connection has
    the functions from the moment it was opened (``connect.py``, the pool hook), which
    is what the triggers that do call them rely on."""
    if not ids:
        return 0
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
    from src.database.writer import connection_first, write_lock

    try:
        connection_first(session)  # the connection, then the gate; a pool timeout is a skipped tuning step, as the gate's would be
        with write_lock():
            session.execute(text("INSERT INTO article_fts(article_fts) VALUES ('optimize')"))
            session.commit()
        out["fts"] = True
    except Exception as exc:  # noqa: BLE001 - a tuning step must never break the caller
        session.rollback()
        log_failure(_LOG, "FTS5 optimize failed", exc, level=logging.WARNING)
    try:
        from src.config.power_profiles import fts_analysis_limit

        _analysis_limit = fts_analysis_limit()  # §7 knob: OO_FTS_ANALYSIS_LIMIT, clamped int.
        connection_first(session)  # the commit above gave the connection back
        with write_lock():
            # nosec B608 - _analysis_limit is a clamped int from power_profiles, never user input;
            # PRAGMA does not accept a bound parameter.
            session.execute(text(f"PRAGMA analysis_limit={_analysis_limit}"))  # noqa: S608
            session.execute(text("PRAGMA optimize"))
            session.commit()
        out["planner"] = True
    except Exception as exc:  # noqa: BLE001 - a tuning step must never break the caller
        session.rollback()
        log_failure(_LOG, "planner optimize failed", exc, level=logging.WARNING)
    return out


def _fts_probe_deadline_s() -> float:
    """Deadline for the cheap FTS health probe (OO_FTS_PROBE_DEADLINE_S, default 5s)."""
    try:
        return max(0.5, float(_os.getenv("OO_FTS_PROBE_DEADLINE_S", "5")))
    except (TypeError, ValueError):
        return 5.0


def _fts_count_deadline_s() -> float:
    """Deadline for each count ``fts_status`` takes, the articles' and the index's own population
    (OO_FTS_COUNT_DEADLINE_S, default 15s). The deadline is a progress handler, which SQLite consults once per
    20,000 virtual-machine opcodes: it stops ``count(1)`` (step 3), a loop of three opcodes per row, and cannot
    stop a bare ``count(*)`` (step 4's shadow-table count), which is nine opcodes in all, the whole walk done
    inside ONE of them (``OP_Count``), so the handler is never consulted before it returns; that count is
    bounded only by the size of the table it walks."""
    try:
        return max(0.5, float(_os.getenv("OO_FTS_COUNT_DEADLINE_S", "15")))
    except (TypeError, ValueError):
        return 15.0


def fts_status(session: Session) -> dict:
    """Robust, transaction/timing-safe status of the ``article_fts`` search index (D4).

    PRESENCE is read from ``sqlite_master`` — the authoritative table list, a metadata read
    that never scans and never trips the statement deadline — NOT from a ``COUNT(*)`` over
    the external-content FTS5 index (which reads every row of the content table, can hit the deadline,
    and was then MISREAD as "table absent", contradicting the schema-drift probe that reads
    the same list). So the two probes can no longer disagree silently: both derive presence
    from the schema.

    Returns (SQLite only; ``{"supported": False, ...}`` on another backend):
      * ``present``      — ``article_fts`` is declared in the schema (authoritative); ``None``
        only if even the metadata read failed.
      * ``tokenizer``    — ``"current"`` or ``"legacy"`` (an index made before 0.5, which splits Devanagari and
        Bengali words at their vowel signs until the migration (or ``ensure_fts(rebuild="always")``) rebuilds it); absent when there
        is no index.
      * ``healthy``      — a cheap bounded probe (``SELECT rowid ... LIMIT 1``) ran without a
        corruption error. ``False`` = the index exists but is DAMAGED (a post-crash malformed
        FTS index — a re-index / ``ensure_fts`` rebuild heals it, the actionable verdict D4
        asked for); ``None`` = present but could not confirm (the probe timed out). ALSO ``False``
        over an EMPTY or a PARTIAL index (``index_state``): see ``indexed_documents`` for why this probe
        alone cannot say it.
      * ``rows``         — the count of ``articles`` rows (``SELECT count(1) FROM articles``, a scan of a covering index the
        planner picks), or ``None`` when the count timed out / errored (``count_status`` says which) — NEVER
        conflated with absence. It is the figure FTS5's own ``count(*) FROM article_fts`` returned until 0.5.1: that
        statement reads every row of the content table, ``articles``, for this external-content table, so on a store
        whose indexes agree with their table (``PRAGMA integrity_check``) it is the same number
        (``tests/test_fts_status.py`` compares them over a full, a shrunken, an emptied and a partial index; an index
        missing entries is not covered: the new count would read it short, and ``quick_check`` does not see that
        either). It is ``count(1)`` and not ``count(*)`` on purpose: SQLite runs a bare ``count(*)`` as ONE opcode that
        the progress-handler deadline can never interrupt (measured at 200,000 articles: the handler was consulted 0 times, against
        30 for ``count(1)`` over the same covering index), so only ``count(1)`` keeps ``count_status: timed_out``
        reachable. Measured 2026-10-27 on 1,000,000 articles: 9.6 to 11.9 s cold for the FTS statement (a table scan,
        which follows the article TEXT, and 3 to 5 s from its 15 s deadline) against 0.24 to 0.33 s cold for this count (five
        cold runs, median 0.29 s; it follows the NUMBER of articles; warm it is a row loop of 16 to 24 ms where
        ``count(*)`` is 1 ms: the price of being interruptible). LIMITS:
        one machine, an encrypted store on a virtual disk reading 1.3 GB/s, synthetic Latin text of 1.3 KB per
        article, nothing above 1 M. The old statement also read every article row, so a damaged ``articles`` page
        surfaced here as an ``error``; this one reads one index and does not (``PRAGMA integrity_check`` and the
        foreign-key check read the table), while damage to a page of the index it reads now shows as an ``error`` in
        this block. ``rows`` is the content table's count, NOT the index's size: ``indexed_documents`` is, and the
        probe is answered from the content table too, so both read healthy and full over an index that holds no
        document (measured: after ``'delete-all'`` the probe said healthy and ``rows`` equalled the articles).
      * ``count_status`` — ok | timed_out | error | skipped.
      * ``indexed_documents`` — the documents the index itself holds: ``COUNT(*)`` of its shadow table
        ``article_fts_docsize`` (one row per indexed document; ``backup/merge.py``'s restore probe reads it for
        the same reason), or ``None`` when it could not be had (``indexed_status`` says why).
      * ``indexed_status`` — ok | timed_out | error | skipped | ``unprobeable`` (an index built without the
        shadow table, ``columnsize=0``, has no cheap population count; nothing is rebuilt on that account).
      * ``index_state``  — what the index's ENDS say (the two highest ids and the index's own count, read in one statement;
        that statement counts no article): ``"empty"`` when
        it holds no document while ``articles`` holds a row (the state ``ensure_fts`` heals at the next start);
        ``"partial (inferred)"`` when its highest document id is below the highest article id (a tail of the
        articles is not indexed: a torn file copy or a hand-made restore, since no app writer leaves one; INFERRED
        from two ends, so how many documents are missing is unknown); ``"ends-agree"`` when neither was seen, which
        is NOT a proof of completeness and not agreement either: a hole in the middle, a missing head and an index
        that holds documents beyond the highest article id all read this way. A partial index stops reading
        ``"partial (inferred)"`` at the NEXT INGEST (the new article is indexed by its trigger, the missing tail becomes
        a hole in the middle, and the ends agree again); only a count comparison or a walk key by key sees a
        hole: ``rows`` (the articles' count) against ``indexed_documents`` is that comparison, which
        ``monitoring.integrity`` makes as its ``delta`` from its own count of the articles. ``None`` when unknown. An index
        read while ``ensure_fts`` is building it on a store that already has articles (boot, ``init_db``) reads empty
        until the first build is done.
      * ``error``        — what failed when unhealthy / the count failed: the DRIVER's class and a fixed label
        (:func:`src.database.damage.failure_text`), never the engine's own message (the integrity report that
        carries this rides the diagnostics bundle); ``"EmptyIndex"`` or ``"PartialIndex"`` over an empty or a partial one
        (fixed labels), unless the count had already named a failure: the first failure stays the one named, and
        ``index_state`` carries the verdict.

    Callers should run this OUTSIDE any enclosing ``statement_deadline`` block: it manages its
    own bounded deadlines, and nesting the progress-handler-based deadline would clobber the
    outer one on exit.
    """
    from src.database.damage import failure_text
    from src.database.maintenance import StatementTimeout, statement_deadline

    bind = session.get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") != "sqlite":
        return {
            "supported": False, "present": None, "healthy": None, "rows": None,
            "count_status": "skipped", "error": None,
            "indexed_documents": None, "indexed_status": "skipped", "index_state": None,
        }

    out: dict = {
        "supported": True, "present": False, "healthy": None, "rows": None,
        "count_status": "skipped", "error": None,
        "indexed_documents": None, "indexed_status": "skipped", "index_state": None,
    }

    # 1) PRESENCE via sqlite_master (fast, authoritative, deadline-proof — a virtual table is
    #    listed with type='table', exactly what schema-drift's get_table_names() reads).
    try:
        row = session.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='article_fts'")
        ).fetchone()
        out["present"] = row is not None
        if row is not None:
            out["tokenizer"] = _tokenizer_of(row[0])
    except Exception as exc:  # noqa: BLE001 - a diagnostic degrades, never crashes
        out["present"] = None
        out["error"] = failure_text(exc)
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
        out["error"] = failure_text(exc)
        out["count_status"] = "error"
        return out  # damaged -> don't attempt the heavier COUNT; re-index heals

    # 3) ROWS: the articles' count (best-effort; a slow COUNT is reported as timed_out, never "absent"). It is the number
    #    ``count(*) FROM article_fts`` gave for this external-content table, taken from a covering index instead of by
    #    reading every article row (0.24 to 0.33 s against 9.6 to 11.9 s cold at 1 M articles; limits in the docstring).
    #    ``count(1)``, not ``count(*)``: a bare ``count(*)`` does its walk inside one opcode and the deadline's progress
    #    handler is never consulted while it runs, so the block around it would bound nothing (tests/test_fts_status.py
    #    pins this by running the real deadline, at a tiny value, over enough rows).
    try:
        with statement_deadline(session, seconds=_fts_count_deadline_s()):
            n = session.execute(text("SELECT count(1) FROM articles")).scalar()
        out["rows"] = int(n) if n is not None else 0
        out["count_status"] = "ok"
    except StatementTimeout:
        out["count_status"] = "timed_out"
    except Exception as exc:  # noqa: BLE001 - count failure is disclosed, presence stands
        out["count_status"] = "error"
        out["error"] = failure_text(exc)

    # 4) THE INDEX'S OWN POPULATION. Steps 2 and 3 are answered from ``articles`` (see ``rows``), so neither
    #    can see an index that holds nothing or only a front part of the articles; the shadow table
    #    ``article_fts_docsize`` is the index's own record, one row per indexed document. The three numbers (the
    #    articles' top id, the index's count and the index's top id) are taken in ONE statement: one statement is one
    #    read snapshot, so no ingest or delete can fall between them. Separate reads cannot be ordered safely: ids are
    #    reused (no AUTOINCREMENT), so after the top articles are deleted a new article takes the same id and an
    #    id read afterwards looks like a document the index never saw. Two O(1) id lookups and one scan of the small
    #    shadow table, inside one deadline block (which cannot stop that count, a bare ``count(*)``: it is bounded by the shadow
    #    table's size, one short row per article, 61 to 82 ms cold at 1 M); the verdict is applied only when the statement has come back, so a
    #    timeout or an error states nothing.
    try:
        with statement_deadline(session, seconds=_fts_count_deadline_s()):
            if session.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='article_fts_docsize'")
            ).fetchone() is None:
                out["indexed_status"] = "unprobeable"
            else:
                top, n, last = session.execute(text(
                    "SELECT (SELECT max(id) FROM articles), (SELECT count(*) FROM article_fts_docsize), "
                    "(SELECT max(id) FROM article_fts_docsize)"
                )).one()
                state, label = "ends-agree", None
                if top is not None and (last is None or last < top):  # (no article: nothing to index)
                    state, label = ("empty", "EmptyIndex") if not n else ("partial (inferred)", "PartialIndex")
                out["indexed_documents"], out["index_state"] = int(n), state
                if label is not None:
                    out["healthy"] = False
                    if out["error"] is None:  # a failure step 3 already named stays the one named
                        out["error"] = label
                out["indexed_status"] = "ok"
    except StatementTimeout:
        out["indexed_status"], out["indexed_documents"], out["index_state"] = "timed_out", None, None
    except Exception as exc:  # noqa: BLE001 - the population is disclosed as a status, presence stands
        out["indexed_status"], out["indexed_documents"], out["index_state"] = "error", None, None
        if out["error"] is None:  # an earlier step's failure stays the one named
            out["error"] = failure_text(exc)
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


# --------------------------------------------------------------------------- #
# The SQL half of the advanced grammar: field filters and the "exact" toggle
# --------------------------------------------------------------------------- #

#: Which stored columns each SQL-answered field reads. ``a`` is ``articles``, ``s`` its
#: ``sources`` row. A field over two columns matches when EITHER does (a source is its name
#: or its domain; an article's address is its URL or its canonical URL).
_FIELD_COLUMNS = {
    "title": ("a.title",),
    "author": ("a.author",),
    "url": ("a.url", "a.canonical_url"),
    "source": ("s.name", "s.domain"),
    "tag": ("s.tags",),
}


def _field_condition(ff: FieldFilter, pname: str, exact: bool) -> tuple[str, dict]:
    """One field filter as a SQL boolean over ``a``/``s`` with ONE bound value.

    Folded by default (Q610 = a: the column and the value both through ``oo_search_fold``,
    so ``José`` finds ``jose``); ``exact`` compares the stored bytes. The three modes are
    ``instr`` (contains), ``instr = 1`` (starts with) and ``=`` (is exactly) -- no LIKE, so
    a ``%`` or ``_`` the reader typed is a character, never a wildcard. Every column name
    comes from :data:`_FIELD_COLUMNS`; the value is always ``:pname``."""
    from src.database.fts_norm import FN_FOLD, search_fold

    value = ff.value.strip()
    bound = value if exact else (search_fold(value) or "")
    conds = []
    for col in _FIELD_COLUMNS[ff.field]:
        x = col if exact else f"{FN_FOLD}({col})"
        if ff.field == "tag":
            # Tags are one comma-separated string per source ("europe, politics"). Starts
            # with / is exactly apply to EACH tag, so the string is normalised to
            # ",europe,politics," and the value is anchored on the commas.
            norm = f"(',' || replace(replace({x}, ', ', ','), ' ,', ',') || ',')"
            if ff.mode == "exact":
                conds.append(f"instr({norm}, ',' || :{pname} || ',') > 0")
            elif ff.mode == "prefix":
                conds.append(f"instr({norm}, ',' || :{pname}) > 0")
            else:
                conds.append(f"instr({x}, :{pname}) > 0")
            continue
        if ff.mode == "exact":
            conds.append(f"{x} = :{pname}")
        elif ff.mode == "prefix":
            conds.append(f"instr({x}, :{pname}) = 1")
        else:
            conds.append(f"instr({x}, :{pname}) > 0")
    return "(" + " OR ".join(conds) + ")", {pname: bound}


def field_where(
    fields: Sequence[FieldFilter], *, outer: str, exact: bool = False, prefix: str = "oof"
) -> tuple[str, dict]:
    """The SQL field filters as ONE boolean, correlated on ``outer`` (an article-id
    expression: ``article_fts.rowid`` inside the index query, ``articles.id`` in an ORM
    query). ``("", {})`` when there are none.

    A negated filter is ``NOT EXISTS`` rather than ``NOT (...)``: an article whose author
    is ``NULL`` IS "not by Smith", and ``NOT (instr(NULL, 'smith') > 0)`` is ``NULL`` --
    which a WHERE reads as false, silently dropping every unattributed article."""
    if outer not in ("article_fts.rowid", "articles.id", "a0.id"):
        raise ValueError(f"unexpected correlation {outer!r}")
    parts: list[str] = []
    params: dict = {}
    for i, ff in enumerate(fields):
        cond, p = _field_condition(ff, f"{prefix}{i}", exact)
        params.update(p)
        body = (
            "SELECT 1 FROM articles a LEFT JOIN sources s ON s.id = a.source_id "  # nosec B608 - `outer` is checked against three literals above; `cond` is built from _FIELD_COLUMNS literals and one bound :param
            f"WHERE a.id = {outer} AND {cond}"
        )
        parts.append(("NOT EXISTS (" if ff.negated else "EXISTS (") + body + ")")
    return (" AND ".join(parts), params) if parts else ("", {})


def _exact_condition(node, params: dict, prefix: str) -> str | None:
    """The positive literals of an FTS part, as byte-exact ``instr`` tests (Q610's toggle).

    The index folds case and diacritics at INDEX time (``remove_diacritics 2``), so it
    cannot tell ``café`` from ``cafe``. The exact reading therefore runs the folded match
    and then keeps only the articles whose stored title or text holds each positive literal
    exactly as typed. EXCLUSIONS stay folded -- ``NOT café`` still drops an article saying
    ``cafe`` -- because the index already removed those rows and a post-filter can only
    narrow; that is the stricter of the two readings and the builder's hover says so."""

    def bind(v: str) -> str:
        name = f"{prefix}{len(params)}"
        params[name] = v
        return name

    if node is None:
        return None
    if isinstance(node, (_Term, _Prefix)):
        n = bind(node.value)
        return f"(instr(a.title, :{n}) > 0 OR instr(a.content, :{n}) > 0)"
    if isinstance(node, _Near):
        parts = [_exact_condition(_Term(v), params, prefix) for v in node.items]
        return "(" + " AND ".join(p for p in parts if p) + ")"
    if isinstance(node, FieldFilter):
        n = bind(node.value)
        return f"(instr(a.title, :{n}) {'= 1' if node.mode == 'prefix' else '> 0'})"
    if isinstance(node, _Or):
        ors: list[str] = []
        for c in node.children:
            part = _exact_condition(c, params, prefix)
            if part:
                ors.append(part)
        return ("(" + " OR ".join(ors) + ")") if ors else None
    if isinstance(node, _AndGroup):
        ands: list[str] = []
        for c in node.includes:
            part = _exact_condition(c, params, prefix)
            if part:
                ands.append(part)
        return ("(" + " AND ".join(ands) + ")") if ands else None
    return None


def exact_where(parsed: ParsedQuery, *, outer: str, prefix: str = "oox") -> tuple[str, dict]:
    """The exact-reading filter (see :func:`_exact_condition`), correlated on ``outer``;
    ``("", {})`` when the query has no positive FTS literal to hold to."""
    if outer not in ("article_fts.rowid", "articles.id", "a0.id"):
        raise ValueError(f"unexpected correlation {outer!r}")
    params: dict = {}
    cond = _exact_condition(parsed.ast, params, prefix)
    if not cond:
        return "", {}
    return (
        "EXISTS (SELECT 1 FROM articles a WHERE a.id = "  # nosec B608 - `outer` is checked against three literals above; `cond` holds only instr() over two literal columns and bound :params
        f"{outer} AND {cond})",
        params,
    )


def _grammar_sql(
    query: str | None,
    *,
    expand: ExpandTerms | None,
    near_default: int,
    exact: bool,
    outer: str,
) -> tuple[str | None, str | None, str, dict, bool]:
    """``(match, negative_match, extra_where, params, has_constraint)`` for one query."""
    from src.database.fts_norm import query_variants

    parsed = parse_query(query, grammar=True)
    match = None if parsed.negative_only else _render(parsed.ast, expand, query_variants, near_default)
    neg = build_negative_match(parsed, expand=expand, variants=query_variants, near_default=near_default)
    where_parts: list[str] = []
    params: dict = {}
    fw, fp = field_where(parsed.fields, outer=outer, exact=exact)
    if fw:
        where_parts.append(fw)
        params.update(fp)
    if exact:
        ew, ep = exact_where(parsed, outer=outer)
        if ew:
            where_parts.append(ew)
            params.update(ep)
    has = match is not None or bool(parsed.fields)
    return match, neg, " AND ".join(where_parts), params, has


def search_ids(
    session: Session,
    query: str | None,
    limit: int = _MAX_CANDIDATES,
    *,
    weights: tuple[float, float] | None = None,
    exclude_quarantined: bool = False,
    expand: ExpandTerms | None = None,
    grammar: bool = True,
    near_default: int = NEAR_DEFAULT,
    exact: bool = False,
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

    ``grammar`` (default on) reads the advanced token class -- prefix, ``NEAR``, and the
    field filters, whose SQL half is applied HERE rather than left to each caller, so no
    caller of this function can drop an ``author:`` it never heard of and return a wider
    set than the query asked for. A query of field filters alone (``author:smith``) has no
    FTS part; it returns the matching ids newest first, since there is nothing to rank by.
    ``exact`` is Q610's toggle (see :func:`exact_where`); ``near_default`` the distance a
    ``NEAR`` without one takes.
    """
    from src.database.fts_norm import query_variants

    if not grammar:
        match = build_match(query, expand=expand, variants=query_variants)
        if match is None:
            return None
        extra = ""
        params: dict = {}
    else:
        match, neg, extra, params, has = _grammar_sql(
            query, expand=expand, near_default=near_default, exact=exact,
            outer="article_fts.rowid",
        )
        if not has:
            return None
        if match is None:
            return _field_only_ids(
                session, query, limit=limit, exclude_quarantined=exclude_quarantined,
                expand=expand, near_default=near_default, exact=exact, neg=neg,
            )
    wt, wb = weights if weights is not None else _bm25_weights()
    gate = _QUARANTINE_GATE if exclude_quarantined else ""
    # `gate` is one of the two constant fragments chosen just above -- never a
    # caller-supplied value, and every value is bound. `extra` is built by field_where /
    # exact_where from module literals and bound :params only. bandit attributes B608 to
    # the first line of the concatenation, so the marker belongs HERE and not on the
    # enclosing text(...) call, where it silently does nothing.
    sql = (
        "SELECT rowid FROM article_fts WHERE article_fts MATCH :q"  # nosec B608 - only the constant `gate` fragment and the literal-built `extra` are concatenated; every value is a bound :param
        + gate
        + (" AND " + extra if extra else "")
        + " ORDER BY bm25(article_fts, :wt, :wb) LIMIT :lim"
    )
    rows = session.execute(
        text(sql),
        {"q": match, "wt": wt, "wb": wb, "lim": limit, **params},
    ).fetchall()
    return [r[0] for r in rows]


def _field_only_sql(
    query: str | None,
    *,
    exclude_quarantined: bool,
    expand: ExpandTerms | None,
    near_default: int,
    exact: bool,
    neg: str | None,
) -> tuple[str, dict]:
    """The WHERE clause over ``articles a0`` for a query with no positive FTS part."""
    _m, _n, extra, params, _h = _grammar_sql(
        query, expand=expand, near_default=near_default, exact=exact, outer="a0.id"
    )
    where = "1 = 1"
    if exclude_quarantined:
        where += " AND a0.quarantined IS NOT 1"
    if extra:
        where += " AND " + extra
    if neg:
        where += " AND a0.id NOT IN (SELECT rowid FROM article_fts WHERE article_fts MATCH :neg)"
        params = {**params, "neg": neg}
    return where, params


def has_ranked_part(query: str | None) -> bool:
    """True when ``query`` has a positive FTS part to rank by (the grammar on).

    A field-only query (``source:reuters``) or an empty one has nothing for bm25 to
    score, so its results are a browse, newest first -- and the ordering statement must
    say so rather than claim relevance. A query that does not parse reports ``True``:
    it will be refused with its own message, and this is not the place to pre-empt it."""
    try:
        parsed = parse_query(query, grammar=True)
    except SearchQueryError:
        return True
    return parsed.ast is not None and not parsed.negative_only


def field_only_where(
    query: str | None, *, near_default: int = NEAR_DEFAULT, exact: bool = False
) -> tuple[str, dict] | None:
    """For a query with NO positive FTS part but field filters (``author:smith``,
    ``source:reuters NOT climate``): one boolean correlated on ``articles.id``, so the
    caller can BROWSE with it -- uncapped and in its own order -- instead of taking
    :func:`search_ids`' candidate list, which is bounded by :data:`MAX_CANDIDATES` and so
    would make the displayed total a cap. ``None`` for every other query."""
    from src.database.fts_norm import query_variants

    parsed = parse_query(query, grammar=True)
    if not parsed.fields:
        return None
    if parsed.ast is not None and not parsed.negative_only:
        return None
    neg = build_negative_match(parsed, variants=query_variants, near_default=near_default)
    where, params = _field_only_sql(
        query, exclude_quarantined=False, expand=None, near_default=near_default,
        exact=exact, neg=neg,
    )
    return (
        "EXISTS (SELECT 1 FROM articles a0 WHERE a0.id = articles.id AND "  # nosec B608 - `where` is built by _field_only_sql from literals and bound :params only
        + where + ")",
        params,
    )


def _field_only_ids(session: Session, query, *, limit, exclude_quarantined, expand,
                    near_default, exact, neg) -> list[int]:
    where, params = _field_only_sql(
        query, exclude_quarantined=exclude_quarantined, expand=expand,
        near_default=near_default, exact=exact, neg=neg,
    )
    sql = (
        "SELECT a0.id FROM articles a0 WHERE "  # nosec B608 - `where` is built by _field_only_sql from literals and bound :params only
        + where
        + " ORDER BY a0.published_at DESC, a0.id DESC LIMIT :lim"
    )
    return [r[0] for r in session.execute(text(sql), {**params, "lim": limit}).fetchall()]


def search_total(
    session: Session,
    query: str | None,
    *,
    exclude_quarantined: bool = False,
    expand: ExpandTerms | None = None,
    grammar: bool = True,
    near_default: int = NEAR_DEFAULT,
    exact: bool = False,
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

    The grammar arguments are :func:`search_ids`'s, for the same reason as ``expand``.
    """
    from src.database.fts_norm import query_variants

    if not grammar:
        match = build_match(query, expand=expand, variants=query_variants)
        if match is None:
            return None
        extra = ""
        params: dict = {}
    else:
        match, neg, extra, params, has = _grammar_sql(
            query, expand=expand, near_default=near_default, exact=exact,
            outer="article_fts.rowid",
        )
        if not has:
            return None
        if match is None:
            where, fparams = _field_only_sql(
                query, exclude_quarantined=exclude_quarantined, expand=expand,
                near_default=near_default, exact=exact, neg=neg,
            )
            row = session.execute(
                text("SELECT count(*) FROM articles a0 WHERE " + where), fparams  # nosec B608 - `where` is built by _field_only_sql from literals and bound :params only
            ).fetchone()
            return int(row[0]) if row else 0
    gate = _QUARANTINE_GATE if exclude_quarantined else ""
    # As in search_ids: `gate` is one of two CONSTANT fragments, never caller-supplied,
    # `extra` is literal-built, and every value is a bound :param. bandit attributes B608
    # to the first line of the concatenation, so the marker belongs here.
    sql = (
        "SELECT count(*) FROM article_fts WHERE article_fts MATCH :q"  # nosec B608 - only the constant `gate` fragment and the literal-built `extra` are concatenated; the query is a bound :param
        + gate
        + (" AND " + extra if extra else "")
    )
    row = session.execute(text(sql), {"q": match, **params}).fetchone()
    return int(row[0]) if row else 0
