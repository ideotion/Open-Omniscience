"""Row 462 (#2418 OPEN-QUESTIONS Q2): which extraction path produced each body, counted per pass.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``extract_article`` takes the one-parse ``bare_extraction`` path and falls back to the two-call ``extract`` path
only when that raises. The field data could not say how often the fallback ran, because nothing recorded it. The
pass's ``extraction_lock`` block now carries ``by_method``: counts only, never a URL or a word of the page.
"""

from __future__ import annotations

import json

import pytest
import trafilatura

from src.ingest import lock_stats
from src.ingest.extract import extract_article

_ARTICLE = (
    "<html><head><title>A headline</title></head><body><article><h1>A headline</h1>"
    + "".join(f"<p>Paragraph {i} carries a full sentence of reporting about the harbour council's budget vote.</p>" for i in range(12))
    + "</article></body></html>"
)
_NOT_AN_ARTICLE = "<html><body><nav><a href='/'>Home</a></nav></body></html>"


@pytest.fixture(autouse=True)
def _window():
    lock_stats.reset()
    yield
    lock_stats.reset()


def _by_method() -> dict:
    return lock_stats.snapshot().get("by_method", {})


def test_the_one_parse_path_is_counted_as_bare():
    assert extract_article(_ARTICLE, url="https://example.test/a") is not None
    assert _by_method() == {"bare": 1}


def test_no_article_on_the_one_parse_path_is_bare_none():
    assert extract_article(_NOT_AN_ARTICLE) is None
    assert _by_method() == {"bare_none": 1}


def test_a_raise_in_bare_extraction_is_counted_as_the_fallback(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("metadata pass fault")

    monkeypatch.setattr(trafilatura, "bare_extraction", boom)
    assert extract_article(_ARTICLE) is not None
    assert extract_article(_NOT_AN_ARTICLE) is None
    assert _by_method() == {"fallback": 1, "fallback_none": 1}


def test_a_raise_on_both_paths_is_counted_as_raised(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("fault")

    monkeypatch.setattr(trafilatura, "bare_extraction", boom)
    monkeypatch.setattr(trafilatura, "extract", boom)
    with pytest.raises(RuntimeError):
        extract_article(_ARTICLE)
    assert _by_method() == {"raised": 1}


def test_the_counts_sum_to_the_holds_and_carry_no_words():
    extract_article(_ARTICLE, url="https://example.test/secret-path")
    extract_article(_NOT_AN_ARTICLE)
    snap = lock_stats.snapshot()
    assert sum(snap["by_method"].values()) == snap["holds"] == 2
    text = json.dumps(snap["by_method"])
    assert "example.test" not in text and "harbour" not in text


def test_a_window_with_no_hold_has_no_block():
    assert lock_stats.snapshot() == {"holds": 0}
