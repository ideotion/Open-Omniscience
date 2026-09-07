"""Newsletter publisher resolution: the ruled ladder, and what it must REFUSE.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

The 2026-06-15 ruling (clause (d)) is mostly a list of things that must NOT happen:
never fuzzy-merge (``bbc`` is not ``nbc``), never collapse many publishers into one
platform domain, never invent a publisher when the evidence is missing. So the
negative space carries most of the weight here — every refusal below is a case
where the tempting answer is a merge, and a merge is a fabrication that reads as
data, where a refusal reads as a gap.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog import publicsuffix as PS
from src.database.models import Article, Base, Source
from src.ingest import newsletter_source as NS


@pytest.fixture(autouse=True)
def _fresh_psl_cache():
    PS._reset_cache_for_tests()
    yield
    PS._reset_cache_for_tests()


def _db(sources: list[tuple[str, str]] | None = None):
    """An ISOLATED in-memory session (never SessionLocal — a shared-store write
    pollutes every later test that reads it)."""
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for name, domain in sources or []:
        s.add(Source(name=name, domain=domain))
    s.commit()
    return s


# --------------------------------------------------------------------------- #
# The eTLD+1 rung
# --------------------------------------------------------------------------- #

def test_a_send_subdomain_resolves_to_the_publisher_and_attaches_exactly():
    s = _db([("BBC News", "bbc.com")])
    r = NS.resolve_newsletter_publisher(s, "BBC News <newsletter@email.bbc.com>")
    assert r.action == "attach-exact"
    assert r.key == "bbc.com" and r.basis == "etld1"
    assert r.source_name == "BBC News"


def test_the_alias_map_is_the_second_rung_and_is_named_in_the_reason():
    s = _db([("BBC", "bbc.co.uk")])
    r = NS.resolve_newsletter_publisher(s, "x@email.bbc.com")
    assert r.action == "attach-alias"
    assert r.source_domain == "bbc.co.uk"
    assert "bbc.co.uk" in r.reason


def test_an_unknown_publisher_becomes_a_new_disabled_email_source():
    s = _db([("BBC News", "bbc.com")])
    r = NS.resolve_newsletter_publisher(s, "hello@mail.someweekly.example")
    assert r.action == "new-email-source"
    assert r.key == "someweekly.example"
    assert "DISABLED" in r.reason


def test_it_never_fuzzy_merges_bbc_is_not_nbc():
    """The ruling's own example. A near-miss must reach the new-source rung, never
    the attach rung — a wrong attach files one publisher's newsletters under
    another and nothing downstream can tell."""
    s = _db([("BBC News", "bbc.com"), ("The Guardian", "theguardian.com")])
    for sender in ("x@nbc.com", "x@mail.nbc.com", "x@bbcnews.com", "x@guardian-news.com"):
        r = NS.resolve_newsletter_publisher(s, sender)
        assert r.action == "new-email-source", f"{sender} -> {r.action} ({r.key})"


def test_a_source_stored_with_unusual_casing_is_still_matched():
    """``Source.domain`` is compared with BINARY collation and the add-a-source form
    stores it as typed, so lowercasing only OUR side would miss it — and a match
    that does not fire is indistinguishable from a publisher nobody has."""
    s = _db([("Example", "Example.COM")])
    r = NS.resolve_newsletter_publisher(s, "x@news.example.com")
    assert r.action == "attach-exact" and r.source_domain == "Example.COM"


# --------------------------------------------------------------------------- #
# The platform inversion — the half that is easy to get backwards
# --------------------------------------------------------------------------- #

def test_two_publications_on_one_platform_never_collapse_into_one_source():
    s = _db()
    a = NS.resolve_newsletter_publisher(s, "x@alice-writes.substack.com")
    b = NS.resolve_newsletter_publisher(s, "x@bobs-briefing.substack.com")
    assert a.key == "alice-writes.substack.com"
    assert b.key == "bobs-briefing.substack.com"
    assert a.key != b.key
    assert a.basis == b.basis == "platform-subdomain"
    # And neither may be the bare platform, which is the merge being prevented.
    assert "substack.com" not in {a.key, b.key}


def test_the_platform_check_runs_BEFORE_the_etld1_and_that_is_the_whole_point():
    """Without the inversion the list answers ``substack.com`` for both senders
    above — measured 2026-09-07: no newsletter platform is in either section of
    the PSL, so the list would perform exactly the collapse the ruling forbids."""
    assert PS.registrable_domain_psl("alice-writes.substack.com", include_private=True) == (
        "substack.com"
    )
    r = NS.resolve_newsletter_publisher(_db(), "x@alice-writes.substack.com")
    assert r.key == "alice-writes.substack.com" and r.basis != "etld1"


def test_a_bare_platform_sender_is_refused_rather_than_attached_to_the_platform():
    s = _db()
    r = NS.resolve_newsletter_publisher(s, "hello@substack.com")
    assert r.action == "refused"
    assert r.key is None
    assert "merge every publisher" in r.reason


def test_an_infrastructure_label_is_not_a_publication():
    """``mail.substack.com`` is the platform's own mail server. Reading ``mail`` as
    a publication would invent a publisher called Mail and file real newsletters
    under it."""
    s = _db()
    for sender in ("x@mail.substack.com", "x@bounces.beehiiv.com", "x@newsletter.ghost.io"):
        r = NS.resolve_newsletter_publisher(s, sender)
        assert r.action == "refused", f"{sender} -> {r.key}"


def test_a_list_id_rescues_a_platform_sender_that_has_no_publication_label():
    """The ruling names List-Id as the stable newsletter key, and this is the case
    it exists for."""
    s = _db()
    r = NS.resolve_newsletter_publisher(
        s, "x@mail.substack.com", 'The Weekly <alice-writes.substack.com>'
    )
    assert r.action == "new-email-source"
    assert r.key == "alice-writes.substack.com"
    assert r.basis == "platform-list-id"


def test_a_list_id_from_another_platform_is_not_used():
    """A List-Id must corroborate the sending platform, not override it — otherwise
    a forwarded or relayed message files a publisher under a platform it never used."""
    s = _db()
    r = NS.resolve_newsletter_publisher(
        s, "x@mail.substack.com", "<somebody.beehiiv.com>"
    )
    assert r.action == "refused"


# --------------------------------------------------------------------------- #
# Refusals that are about evidence, not about the publisher
# --------------------------------------------------------------------------- #

def test_no_sender_domain_is_a_refusal_with_its_reason():
    s = _db()
    for bad in (None, "", "not an address", "Anon <>"):
        r = NS.resolve_newsletter_publisher(s, bad)
        assert r.action == "refused" and r.key is None, repr(bad)


def test_an_unavailable_list_refuses_and_says_so_rather_than_guessing(monkeypatch, tmp_path):
    monkeypatch.setattr(PS, "_LIST_PATH", tmp_path / "absent.dat")
    PS._reset_cache_for_tests()
    s = _db([("BBC News", "bbc.com")])
    r = NS.resolve_newsletter_publisher(s, "x@email.bbc.com")
    assert r.action == "refused"
    assert "Public Suffix List is unavailable" in r.reason
    # The negative-space twin: the platform path does NOT need the list, so it must
    # keep working — a degrade should surrender only what depended on the missing thing.
    r2 = NS.resolve_newsletter_publisher(s, "x@alice-writes.substack.com")
    assert r2.key == "alice-writes.substack.com"


def test_a_public_suffix_sender_is_refused():
    s = _db()
    r = NS.resolve_newsletter_publisher(s, "x@co.uk")
    assert r.action == "refused" and "no registrable domain" in r.reason


# --------------------------------------------------------------------------- #
# List-Id parsing (ruling clause (a): a KEEP field, recipient-safe)
# --------------------------------------------------------------------------- #

def test_list_id_takes_only_the_bracketed_identifier():
    assert NS.parse_list_id('"The Weekly" <weekly.example.com>') == "weekly.example.com"
    assert NS.parse_list_id("<Weekly.Example.COM>") == "weekly.example.com"
    # An unbracketed value is free text; reading it as an identifier invents one.
    assert NS.parse_list_id("The Weekly") is None
    assert NS.parse_list_id(None) is None
    assert NS.parse_list_id("") is None


def test_parse_email_keeps_list_id_and_absence_is_absence():
    from src.ingest.email import parse_email

    raw = (
        b"From: The Weekly <hello@news.example.com>\r\n"
        b'List-Id: "The Weekly" <weekly.example.com>\r\n'
        b"Subject: Hello\r\n\r\nbody\r\n"
    )
    assert parse_email(raw).list_id == "weekly.example.com"
    assert parse_email(raw.replace(b'List-Id: "The Weekly" <weekly.example.com>\r\n', b"")).list_id is None


# --------------------------------------------------------------------------- #
# The preview — the resolver's real, read-only caller
# --------------------------------------------------------------------------- #

def _seed_newsletters(s, rows: list[tuple[str, str]]):
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    bucket = Source(name="Imported newsletters", domain=NEWSLETTER_SOURCE_DOMAINS[0])
    s.add(bucket)
    s.commit()
    for i, (author, title) in enumerate(rows):
        s.add(
            Article(
                url=f"eml://{i}", canonical_url=f"eml://{i}", source_id=bucket.id,
                title=title, content="body", hash=f"h{i}", author=author,
            )
        )
    s.commit()


def test_the_preview_groups_by_sender_and_reports_exact_counts():
    s = _db([("BBC News", "bbc.com")])
    _seed_newsletters(
        s,
        [("x@email.bbc.com", f"BBC {i}") for i in range(5)]
        + [("y@alice-writes.substack.com", f"Alice {i}") for i in range(2)]
        + [("z@substack.com", "Platform")]
        + [("", "No sender")],
    )
    out = NS.resolution_preview(s, limit_examples=2)
    assert out["articles"] == 9  # 5 + 2 + 1 + 1
    assert out["articles_without_a_sender_domain"] == 1
    by_dom = {g["send_domain"]: g for g in out["groups"]}
    assert by_dom["email.bbc.com"]["articles"] == 5
    assert by_dom["email.bbc.com"]["action"] == "attach-exact"
    assert by_dom["alice-writes.substack.com"]["action"] == "new-email-source"
    assert by_dom["substack.com"]["action"] == "refused"
    # ANTI-CAPPING: the example list is bounded, the COUNT never is.
    assert len(by_dom["email.bbc.com"]["examples"]) == 2
    assert by_dom["email.bbc.com"]["articles"] == 5


def test_the_preview_writes_nothing():
    """It is a preview. A run that attached would be a data-placement change the
    ruling gates on an announcing UI and an undo, neither of which exists yet."""
    s = _db([("BBC News", "bbc.com")])
    _seed_newsletters(s, [("x@email.bbc.com", "One")])
    before_sources = s.query(Source).count()
    before_map = {a.id: a.source_id for a in s.query(Article).all()}
    NS.resolution_preview(s)
    assert s.query(Source).count() == before_sources
    assert {a.id: a.source_id for a in s.query(Article).all()} == before_map


def test_an_empty_corpus_gets_an_honest_empty_state_not_a_zeroed_report():
    out = NS.resolution_preview(_db())
    assert out["groups"] == [] and out["articles"] == 0
    assert "no imported newsletters" in out["note"]
    assert out["list_status"]["available"] is True


def test_the_preview_carries_its_method_and_its_caveat():
    out = NS.resolution_preview(_db())
    assert "no network call" in out["method"]
    assert "no newsletter has been attached" in out["caveat"]
    assert "List-Id is not stored" in out["caveat"]
