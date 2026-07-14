"""
Wikipedia-references discovery channel (Part-3B / Phase-2, ruling Q3a) — the flagship ZERO-NETWORK
channel: parse the external references cited in the already-stored watched-page wikitext, across all
editions, and register domains cited by >= N distinct pages as DISABLED candidates.

The NEGATIVE-SPACE lens is mandatory for a parser: should-be-empty inputs must return no candidate —
empty text, internal-only links, Wikimedia self/asset hosts, commerce/social/infrastructure noise,
and inline images all yield nothing (never a fabricated source).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import Base, Source, SourceCandidate, WikiPage
from src.discovery.channels import extract_reference_domains, wikipedia_reference_channel

# --------------------------------------------------------------------------- #
# PURE parser — extract_reference_domains
# --------------------------------------------------------------------------- #

def test_extracts_cite_templates_refs_and_bare_links():
    wikitext = (
        "'''Example''' is a thing.<ref>{{cite web|url=https://www.reuters.com/article/foo|title=Foo}}</ref>\n"
        "It was reported.<ref name=bbc>{{cite news|url=http://news.bbc.co.uk/2/hi/bar.stm}}</ref>\n"
        "See [https://www.example.gov/report Report] and [[Internal Link]].\n"
    )
    doms = extract_reference_domains(wikitext)
    # registrable_domain strips only 'www.', never other subdomains (the app-wide
    # email.bbc.com != bbc.com convention), so a host keeps its meaningful subdomain.
    assert set(doms) == {"reuters.com", "news.bbc.co.uk", "example.gov"}
    assert doms["reuters.com"] == 1


def test_negative_space_no_external_references_yields_nothing():
    assert extract_reference_domains("") == {}
    assert extract_reference_domains(None) == {}
    assert extract_reference_domains("No links here, only [[Internal Link]] and prose.") == {}


def test_wikimedia_self_and_interwiki_hosts_excluded():
    # a self-reference / interwiki / DBpedia link is never a discovered source
    wt = ("<ref>https://en.wikipedia.org/wiki/Foo</ref> "
          "https://commons.wikimedia.org/wiki/File:X https://www.wikidata.org/wiki/Q1 "
          "https://dbpedia.org/page/Foo")
    assert extract_reference_domains(wt) == {}


def test_commerce_social_infrastructure_noise_excluded():
    wt = ("[https://shop.foo.com/x buy] "
          "<ref>https://twitter.com/someone/status/1</ref> "
          "https://fonts.googleapis.com/css?family=X")
    assert extract_reference_domains(wt) == {}


def test_inline_image_urls_skipped_but_pdf_reports_kept():
    assert extract_reference_domains("<ref>https://cdn.foo.com/image.JPG</ref>") == {}  # image asset
    assert extract_reference_domains("<ref>https://cdn.foo.com/pic.png?v=2</ref>") == {}  # query-suffixed image
    # a PDF is a legitimate report reference — kept
    assert set(extract_reference_domains("<ref>https://reports.example.org/2026/study.pdf</ref>")) == {
        "reports.example.org",
    }


def test_trailing_sentence_punctuation_is_not_part_of_the_url():
    doms = extract_reference_domains("As shown at https://www.example.gov.")
    assert set(doms) == {"example.gov"}  # the trailing '.' is stripped


# --------------------------------------------------------------------------- #
# DB channel — wikipedia_reference_channel over an in-memory corpus
# --------------------------------------------------------------------------- #

def _corpus() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    # a real seeded source (so its domain counts as already-known)
    s.add(Source(name="Existing", domain="existing.example", language="en", enabled=True))
    s.flush()
    return s


def _page(s, *, wiki, title, text, watched=True):
    p = WikiPage(wiki=wiki, title=title, watched=watched, baseline_text=text)
    s.add(p)
    s.flush()
    return p


def test_channel_registers_a_domain_cited_by_enough_pages_with_edition_evidence():
    s = _corpus()
    # newsdaily.example cited in BOTH an en and an fr page -> multi-edition de-biasing signal
    _page(s, wiki="en", title="A", text="<ref>{{cite web|url=https://www.newsdaily.example/a}}</ref>")
    _page(s, wiki="fr", title="B", text="Voir [https://newsdaily.example/b source].")
    # onceonly.example cited by a single page -> below the min_pages floor
    _page(s, wiki="en", title="C", text="<ref>https://onceonly.example/x</ref>")
    created = wikipedia_reference_channel(s, cap=10, min_pages=2)

    assert created == ["newsdaily.example"]
    cand = s.query(SourceCandidate).filter_by(domain="newsdaily.example").one()
    assert cand.channel == "wikipedia" and cand.status == "candidate"
    ev = json.loads(cand.evidence)
    assert ev["distinct_citing_pages"] == 2 and ev["editions"] == ["en", "fr"]
    # the single-page domain is NOT a candidate (honest floor, never a fabricated source)
    assert s.query(SourceCandidate).filter_by(domain="onceonly.example").first() is None


def test_channel_skips_already_known_domains_and_unwatched_pages():
    s = _corpus()
    # cited by 2 pages but the domain is already a seeded Source -> skip
    _page(s, wiki="en", title="A", text="<ref>https://existing.example/a</ref>")
    _page(s, wiki="en", title="B", text="<ref>https://existing.example/b</ref>")
    # an UNWATCHED page's references are ignored entirely
    _page(s, wiki="en", title="U1", text="<ref>https://hidden.example/a</ref>", watched=False)
    _page(s, wiki="en", title="U2", text="<ref>https://hidden.example/b</ref>", watched=False)
    created = wikipedia_reference_channel(s, cap=10, min_pages=2)
    assert created == []
    assert s.query(SourceCandidate).count() == 0


def test_channel_honours_the_cap():
    s = _corpus()
    for i in range(5):
        _page(s, wiki="en", title=f"P{i}a", text=f"<ref>https://cap{i}.example/a</ref>")
        _page(s, wiki="en", title=f"P{i}b", text=f"<ref>https://cap{i}.example/b</ref>")
    created = wikipedia_reference_channel(s, cap=2, min_pages=2)
    assert len(created) == 2
