"""Pure unit tests for the content-provenance class derivation.

No ORM / crypto / network -- runs in every lane (incl. core-only). The endpoint
wiring (filter + per-article keyword count) is covered by tests/test_articles_provenance.py.
"""

from src.catalog.provenance import (
    CITED,
    NEWSLETTER,
    NEWSLETTER_DOMAINS,
    PROVENANCE_CLASSES,
    STATISTICS,
    WEB,
    WIKIPEDIA,
    provenance_of,
)


def test_wikipedia_recognised_by_domain_only():
    assert provenance_of("en.wikipedia.org") == WIKIPEDIA
    assert provenance_of("fr.wikipedia.org") == WIKIPEDIA
    assert provenance_of("wikipedia.org") == WIKIPEDIA
    # source_type is irrelevant for wiki (domain wins).
    assert provenance_of("de.wikipedia.org", "news") == WIKIPEDIA


def test_wikipedia_not_spoofable_by_suffix_or_subdomain():
    # A bare suffix match would be a security hole: these are NOT wikipedia.
    assert provenance_of("notwikipedia.org") == WEB
    assert provenance_of("wikipedia.org.attacker.com") == WEB
    assert provenance_of("evil-wikipedia.org.example.com") == WEB


def test_newsletter_buckets():
    for d in NEWSLETTER_DOMAINS:
        assert provenance_of(d) == NEWSLETTER
    assert provenance_of("newsletters.import.local") == NEWSLETTER
    assert provenance_of("mailbox.import.local") == NEWSLETTER


def test_statistics_by_source_type():
    assert provenance_of("data.worldbank.org", "statistics") == STATISTICS
    assert provenance_of("ec.europa.eu", "Statistics") == STATISTICS  # case-insensitive
    # Without the statistics type it is just a web source.
    assert provenance_of("data.worldbank.org") == WEB


def test_cited_by_source_type():
    # A citation-discovered secondary source has a normal web domain; the class comes
    # from its source_type, set by the promoter.
    assert provenance_of("reuters.com", "cited") == CITED
    assert provenance_of("apnews.com", "Cited") == CITED  # case-insensitive
    # Without the cited type it is just a web source.
    assert provenance_of("reuters.com") == WEB


def test_web_is_the_total_default():
    assert provenance_of("bbc.com") == WEB
    assert provenance_of("bbc.com", "news") == WEB
    assert provenance_of(None) == WEB
    assert provenance_of("") == WEB


def test_case_and_trailing_dot_normalised():
    assert provenance_of("EN.WIKIPEDIA.ORG") == WIKIPEDIA
    assert provenance_of("en.wikipedia.org.") == WIKIPEDIA


def test_classes_are_a_closed_descriptive_set():
    # Every output is a member of the advertised set (a channel label, never a score).
    assert set(PROVENANCE_CLASSES) == {WEB, WIKIPEDIA, NEWSLETTER, STATISTICS, CITED}
    for dom in ("en.wikipedia.org", "newsletters.import.local", "x.com", None):
        assert provenance_of(dom) in PROVENANCE_CLASSES
