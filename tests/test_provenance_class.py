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
    # LAW joined 2026-07-17 (maintainer: a proper dedicated class for law articles).
    from src.catalog.provenance import LAW

    assert set(PROVENANCE_CLASSES) == {WEB, WIKIPEDIA, NEWSLETTER, STATISTICS, CITED, LAW}
    for dom in ("en.wikipedia.org", "newsletters.import.local", "x.com", "law.fr.local", None):
        assert provenance_of(dom) in PROVENANCE_CLASSES


def test_law_by_source_type_and_synthetic_domain():
    """2026-07-17: law is a first-class provenance class — legal/ip portals and the
    synthetic law.<jur>.local corpus sources all classify as LAW, never WEB."""
    from src.catalog.provenance import LAW, PROVENANCE_CLASSES

    assert LAW in PROVENANCE_CLASSES
    assert provenance_of("legifrance.gouv.fr", "legal") == LAW
    assert provenance_of("uspto.gov", "ip") == LAW
    assert provenance_of("law.fr.local") == LAW          # synthetic, even without type
    assert provenance_of("law.kh.local", "legal") == LAW
    assert provenance_of("lawyer-news.example") == WEB   # no substring spoofing
    assert provenance_of("example.local") == WEB


def test_implied_tags_merge_never_replace():
    from src.catalog.provenance import implied_tags

    # explicit tags keep order; class tag appended once
    assert implied_tags("legifrance.gouv.fr", "legal", "legislation,official") == [
        "legislation", "official", "law",
    ]
    assert implied_tags("law.kh.local", "legal", None) == ["law"]
    assert implied_tags("en.wikipedia.org", None, "") == ["wikipedia", "encyclopedia"]
    assert implied_tags("uspto.gov", "ip", "law") == ["law", "ip"]  # already-present kept once
    assert implied_tags("example.com", "news", "politics") == ["politics"]  # web implies nothing


def test_ensure_channel_tags_heals_idempotently():
    """The boot heal materialises implied tags on the bounded candidate set, appends
    only (never removes/reorders), and is a no-op the second time."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.catalog.provenance import ensure_channel_tags
    from src.database.models import Base, Source

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        Source(name="Wikipedia (fr)", domain="fr.wikipedia.org"),
        Source(name="Law (KH)", domain="law.kh.local", source_type="legal"),
        Source(name="Légifrance", domain="legifrance.gouv.fr", source_type="legal",
               tags="legislation,official"),
        Source(name="USPTO", domain="uspto.gov", source_type="ip"),
        Source(name="Plain news", domain="news.example", source_type="news", tags="politics"),
    ])
    s.commit()
    healed = ensure_channel_tags(s)
    assert healed == 4  # every channel source healed; the plain news row untouched
    tags = {src.domain: src.tags for src in s.query(Source).all()}
    assert tags["fr.wikipedia.org"] == "wikipedia,encyclopedia"
    assert tags["law.kh.local"] == "law"
    assert tags["legifrance.gouv.fr"] == "legislation,official,law"  # appended, order kept
    assert tags["uspto.gov"] == "law,ip"
    assert tags["news.example"] == "politics"
    assert ensure_channel_tags(s) == 0  # idempotent


def test_creation_sites_carry_channel_tags_source_pin():
    """The synthetic law + wiki source creation sites set their channel tags at birth
    (source-level pin; the ORM paths are exercised in CI — py3.11 cannot import the
    src.law/src.wiki packages past write.py's PEP-695 syntax)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    law = (root / "src" / "law" / "corpus.py").read_text(encoding="utf-8")
    wiki = (root / "src" / "wiki" / "corpus.py").read_text(encoding="utf-8")
    assert 'tags="law"' in law, "ensure_law_source lost its channel tag"
    assert 'tags="wikipedia,encyclopedia"' in wiki, "ensure_wiki_source lost its channel tags"
