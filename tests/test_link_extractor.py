"""
Behavioral tests for the link extractor (Action Plan Phase 6.4).

Covers the genuinely-correct, useful behavior of a live but previously-untested
enricher: link extraction, relative-URL resolution against a base, and summary
statistics. (The link_type internal/external classification is a known weak spot
of this P2 enricher and is intentionally not pinned here.)
"""

from __future__ import annotations

from src.services.link_analyzer.extractor import LinkExtractor

_HTML = """<html><body>
  <a href="https://other.example/story">External</a>
  <a href="/local/page">Relative</a>
  <a href="https://example.com/about">Same site</a>
  <a href="mailto:a@b.com">Mail</a>
</body></html>"""


def _le():
    return LinkExtractor()


def test_extracts_all_anchors():
    links = _le().extract_links(_HTML, base_url="https://example.com")
    urls = {l["url"] for l in links}
    assert "https://other.example/story" in urls
    assert "https://example.com/about" in urls


def test_resolves_relative_against_base():
    links = _le().extract_links(_HTML, base_url="https://example.com")
    urls = {l["url"] for l in links}
    # the relative href is resolved against the base URL
    assert "https://example.com/local/page" in urls


def test_statistics_shape():
    le = _le()
    links = le.extract_links(_HTML, base_url="https://example.com")
    stats = le.get_link_statistics(links)
    assert stats["total_links"] == len(links)
    assert stats["unique_domains"] >= 1
    assert set(stats) >= {"total_links", "unique_domains", "internal_links", "external_links"}


def test_empty_html_yields_no_links():
    assert _le().extract_links("<html><body><p>no links</p></body></html>") == []
