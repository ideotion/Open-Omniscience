"""Tests for honest ccTLD-based country/language inference + seed backfill."""

from src.catalog.cctld import infer_country, infer_language
from src.ingest.seed_sources import _to_source_kwargs


def test_infer_country_reliable_cctlds():
    assert infer_country("lemonde.fr") == "fr"
    assert infer_country("asahi.co.jp") == "jp"  # second-level ccTLD
    assert infer_country("bbc.co.uk") == "gb"  # .uk -> ISO gb
    assert infer_country("spiegel.de") == "de"


def test_infer_country_generic_and_unknown_are_none():
    assert infer_country("example.com") is None  # gTLD
    assert infer_country("startup.io") is None  # repurposed-generic ccTLD
    assert infer_country("blog.co") is None  # repurposed-generic ccTLD
    assert infer_country("") is None
    assert infer_country(None) is None


def test_infer_language_only_when_unambiguous():
    assert infer_language("lemonde.fr") == "fr"
    assert infer_language("asahi.co.jp") == "ja"
    assert infer_language("example.com") is None
    assert infer_language("admin.ch") is None  # multilingual country -> no guess


def test_seed_kwargs_backfills_and_tags_provenance():
    kw = _to_source_kwargs(
        {"name": "Le Monde", "domain": "lemonde.fr", "tags": ["news"], "_provenance": "curated"}
    )
    assert kw["country"] == "fr"
    assert kw["language"] == "fr"
    assert "via:curated" in kw["tags"].split(",")
    assert "news" in kw["tags"].split(",")


def test_seed_kwargs_does_not_override_explicit_values():
    kw = _to_source_kwargs({"name": "X", "domain": "x.fr", "country": "BE", "language": "nl"})
    # explicit wins over ccTLD inference (canonicalised to lowercase ISO-2, 0.09)
    assert kw["country"] == "be"
    assert kw["language"] == "nl"


def test_seed_kwargs_generic_domain_stays_unknown():
    kw = _to_source_kwargs({"name": "Y", "domain": "example.com"})
    assert "country" not in kw  # no fabrication for gTLDs
    assert "language" not in kw
