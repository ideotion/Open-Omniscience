"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Unit tests for src.reporting.methods.build_methods_markdown. There was no
dedicated test file for this module (a repo-wide search finds no
tests/test_*.py referencing it). Covers the Markdown table-cell escaping of
the pipe delimiter (``|``) across the columns that can contain one: title,
source name and URL (audit finding P3-16 -- the URL column was inserted
unescaped, misaligning the rendered table for any URL containing a literal
``|``, e.g. in a query string).

Builds bare stand-in objects rather than real ORM ``Article``/``Source`` rows:
``build_methods_markdown`` only ever reads a handful of duck-typed attributes
off each article, so no database/SQLAlchemy setup is needed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.reporting.methods import build_methods_markdown


@dataclass
class _FakeSource:
    name: str


@dataclass
class _FakeArticle:
    id: int
    title: str | None
    url: str
    hash: str
    source: _FakeSource | None = None
    published_at: object = None


def _rows(markdown: str) -> list[str]:
    """Return the article-table data rows (skip header + separator)."""
    lines = markdown.splitlines()
    start = lines.index("## Articles (provenance)") + 4  # blank, header, sep
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        rows.append(line)
    return rows


def test_normal_url_renders_unescaped():
    a = _FakeArticle(
        id=1,
        title="A plain title",
        url="https://example.com/article",
        hash="a" * 64,
        source=_FakeSource(name="Example"),
    )
    md = build_methods_markdown(
        [a], query=None, case_name="t", notes=None, corpus_total=1,
        corpus_range=(None, None),
    )
    rows = _rows(md)
    assert len(rows) == 1
    assert "https://example.com/article" in rows[0]
    assert "\\|" not in rows[0]


def test_url_containing_pipe_is_escaped_in_the_url_column():
    a = _FakeArticle(
        id=1,
        title="A plain title",
        url="https://example.com/search?q=a|b",
        hash="b" * 64,
        source=_FakeSource(name="Example"),
    )
    md = build_methods_markdown(
        [a], query=None, case_name="t", notes=None, corpus_total=1,
        corpus_range=(None, None),
    )
    rows = _rows(md)
    assert len(rows) == 1
    row = rows[0]
    # The literal pipe from the URL must be escaped, not left to break the
    # table's column count.
    assert "https://example.com/search?q=a\\|b" in row
    # Every remaining "|" in the row is a real column delimiter (i.e. not
    # preceded by a backslash) -- a naive split() would otherwise treat the
    # escaped pipe as an extra delimiter and misreport the column count.
    unescaped_pipes = sum(
        1 for i, ch in enumerate(row) if ch == "|" and row[i - 1] != "\\"
    )
    # 6 named columns (#, Title, Source, Published, URL, Content SHA-256)
    # delimited by 7 real pipes.
    assert unescaped_pipes == 7


def test_title_and_source_pipes_still_escaped():
    a = _FakeArticle(
        id=2,
        title="Title | with a pipe",
        url="https://example.com/x",
        hash="c" * 64,
        source=_FakeSource(name="Source | Name"),
    )
    md = build_methods_markdown(
        [a], query=None, case_name="t", notes=None, corpus_total=1,
        corpus_range=(None, None),
    )
    row = _rows(md)[0]
    assert "Title \\| with a pipe" in row
    assert "Source \\| Name" in row
