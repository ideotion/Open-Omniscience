"""
Behavioral tests for the link extractor (Action Plan Phase 6.4).

Covers link extraction, relative-URL resolution against a base, internal/external
classification by same-site domain (fixed in v0.4), non-web scheme handling, and
summary statistics.
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


def test_internal_external_by_domain():
    links = {l["url"]: l["link_type"] for l in _le().extract_links(_HTML, base_url="https://example.com")}
    # same-site (incl. resolved relative) -> internal; other-site -> external
    assert links["https://example.com/about"] == "internal"
    assert links["https://example.com/local/page"] == "internal"
    assert links["https://other.example/story"] == "external"


def test_non_web_scheme_not_mislabelled():
    links = {l["url"]: l["link_type"] for l in _le().extract_links(_HTML, base_url="https://example.com")}
    # mailto must NOT be labelled 'internal' (the pre-v0.4 bug)
    assert links["mailto:a@b.com"] == "email"


def test_empty_html_yields_no_links():
    assert _le().extract_links("<html><body><p>no links</p></body></html>") == []
