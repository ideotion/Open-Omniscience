"""No lookup may read "the" source of a domain without saying which one (row J, S05-10).

With ``UNIQUE (domain, feed_key)`` a domain can hold several sources, and ``query(Source).filter_by(domain=x).first()``
is no longer an identity lookup: with no ORDER BY the row returned depends on which index the planner rides. Every
by-domain single-row read goes through ``src.database.source_lookup.source_for_domain`` (lowest id, so the row an
install already has keeps answering) or orders itself. This walks the tree's syntax, not its text, so a chain split
over lines is found as readily as a one-liner.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
_SINGLE = {"first", "one", "one_or_none", "scalar"}


def _chain(call: ast.Call) -> list[ast.Call]:
    out: list[ast.Call] = []
    node: ast.AST = call
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        out.append(node)
        node = node.func.value
    return out


def _is_source(arg: ast.AST) -> bool:
    """``Source`` itself or one of its columns (``Source.id``); not ``SourceCandidate`` or ``ExternalSource``."""
    return (isinstance(arg, ast.Name) and arg.id == "Source") or (
        isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id == "Source"
    )


def _offences(tree: ast.AST) -> list[int]:
    found: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _SINGLE):
            continue
        calls = _chain(node)
        names = [c.func.attr for c in calls]  # type: ignore[union-attr]
        if "order_by" in names:
            continue
        queries_source = any(
            c.func.attr == "query" and c.args and _is_source(c.args[0])  # type: ignore[union-attr]
            for c in calls
        )
        if not queries_source:
            continue
        by_domain = any(
            (c.func.attr == "filter_by" and any(k.arg == "domain" for k in c.keywords))  # type: ignore[union-attr]
            or (c.func.attr == "filter" and "Source.domain ==" in " ".join(ast.unparse(a) for a in c.args))  # type: ignore[union-attr]
            for c in calls
        )
        if by_domain:
            found.append(node.lineno)
    return found


def test_the_walker_finds_the_shapes_it_exists_for():
    src = (
        "a = session.query(Source).filter_by(domain=d).first()\n"
        "b = (session.query(Source)\n    .filter(Source.domain == d)\n    .first())\n"
        "c = session.query(Source).filter_by(domain=d).order_by(Source.id).first()\n"
        "d = session.query(Source).filter_by(id=1).first()\n"
        "e = session.query(Source.id).filter(Source.domain == d).scalar()\n"
    )
    assert _offences(ast.parse(src)) == [1, 2, 7]


def test_no_by_domain_single_row_lookup_is_left_unordered():
    bad: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        bad += [f"{path.relative_to(_SRC.parent)}:{n}" for n in _offences(tree)]
    assert not bad, (
        "these read one source by domain with no ORDER BY; use src.database.source_lookup.source_for_domain: "
        + ", ".join(bad)
    )
