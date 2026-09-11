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
    # The caveat used to read "the List-Id is not stored on already-imported
    # messages". It IS stored now (Article.newsletter_list_id), so that sentence
    # would be a false disclosure -- but the residue is real and narrower: a message
    # imported BEFORE the column existed still carries none, and a NULL there means
    # "carried none, or predates the column", never "this list has no identifier".
    # The caveat has to keep naming that, and has to keep naming the only cure.
    assert "predates the column" in out["caveat"]
    assert "Re-importing the .eml files fills it" in out["caveat"]
    assert "List-Id is not stored" not in out["caveat"], (
        "the preview still disclaims a limitation it no longer has -- a stale caveat "
        "is a false statement about the software, not a harmless leftover"
    )
    # The method must say why one sending domain can now open several rows.
    assert "once per publication" in out["method"]


# --------------------------------------------------------------------------- #
# The stored List-Id — what the preview could not reach without it
# --------------------------------------------------------------------------- #

def _seed_with_list_ids(s, rows: list[tuple[str, str, str | None]]):
    """rows = (author, title, stored bare List-Id or None)."""
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    bucket = Source(name="Imported newsletters", domain=NEWSLETTER_SOURCE_DOMAINS[0])
    s.add(bucket)
    s.commit()
    for i, (author, title, lid) in enumerate(rows):
        s.add(
            Article(
                url=f"eml://L{i}", canonical_url=f"eml://L{i}", source_id=bucket.id,
                title=title, content="body", hash=f"L{i}", author=author,
                newsletter_list_id=lid,
            )
        )
    s.commit()


def test_ingest_persists_the_list_id_and_an_absent_header_stays_absent():
    """The header is read at parse and was dropped at persist, which is why the
    preview had nothing to resolve with. NULL must stay NULL -- an invented
    identifier is exactly what parse_list_id refuses to produce."""
    from src.ingest.email import _email_article, parse_email

    src = Source(name="Imported newsletters", domain="newsletters.local")
    src.id = 1
    raw = (
        b"From: The Weekly <hello@substack.com>\r\n"
        b'List-Id: "The Weekly" <theweekly.substack.com>\r\n'
        b"Subject: Hello\r\n\r\nbody\r\n"
    )
    art = _email_article(src, parse_email(raw), "h", "eml://1")
    assert art.newsletter_list_id == "theweekly.substack.com"

    bare = raw.replace(b'List-Id: "The Weekly" <theweekly.substack.com>\r\n', b"")
    assert _email_article(src, parse_email(bare), "h", "eml://2").newsletter_list_id is None


def test_the_stored_identifier_is_NOT_parsed_a_second_time():
    """THE TRAP. publisher_key's `list_id` is a RAW header and it calls
    parse_list_id, which by design refuses a bare unbracketed value. What we store
    is the already-parsed bare identifier, so routing it through `list_id` returns
    None and drops silently to the refusal branch -- with every wiring assertion
    still passing. `list_id_parsed` is the door that does not re-parse."""
    stored = "theweekly.substack.com"  # what Article.newsletter_list_id holds
    assert NS.parse_list_id(stored) is None, "premise: a bare value is refused"

    through_raw_door = NS.publisher_key("hello@substack.com", stored)
    assert through_raw_door.basis == "refused"

    through_parsed_door = NS.publisher_key("hello@substack.com", list_id_parsed=stored)
    assert through_parsed_door.basis == "platform-list-id"
    assert through_parsed_door.key == "theweekly.substack.com"


def test_the_preview_reaches_platform_list_id_from_the_stored_column():
    """The whole point. resolution_preview is the resolver's one non-test caller,
    and before the column it could ONLY refuse a platform sender whose host names
    no publication -- however clearly the message named one."""
    s = _db()
    _seed_with_list_ids(
        s,
        [("a@substack.com", "Weekly 1", "theweekly.substack.com"),
         ("b@substack.com", "Weekly 2", "theweekly.substack.com")],
    )
    out = NS.resolution_preview(s)
    assert len(out["groups"]) == 1
    g = out["groups"][0]
    assert g["basis"] == "platform-list-id"
    assert g["publisher"] == "theweekly.substack.com"
    assert g["action"] == "new-email-source"
    assert g["list_id"] == "theweekly.substack.com"
    assert g["articles"] == 2


def test_two_publications_on_one_platform_domain_are_two_rows_not_one():
    """Merging them is the exact fabrication the refusal branch exists to prevent:
    one row for substack.com would assert that two unrelated publishers are one
    source. The counts stay true per publication, and `senders` keeps meaning
    distinct sending DOMAINS rather than being silently redefined as rows."""
    s = _db()
    _seed_with_list_ids(
        s,
        [("a@substack.com", "W1", "weekly.substack.com"),
         ("b@substack.com", "W2", "weekly.substack.com"),
         ("c@substack.com", "D1", "daily.substack.com")],
    )
    out = NS.resolution_preview(s)
    by_pub = {g["publisher"]: g for g in out["groups"]}
    assert set(by_pub) == {"weekly.substack.com", "daily.substack.com"}
    assert by_pub["weekly.substack.com"]["articles"] == 2
    assert by_pub["daily.substack.com"]["articles"] == 1
    assert out["senders"] == 1, "one sending domain, however many publications"
    assert out["publications"] == 2
    assert out["articles"] == 3


def test_a_platform_message_with_no_stored_list_id_is_still_refused_not_folded_in():
    """The honest residue: a message imported before the column existed carries
    NULL. It must NOT inherit a sibling's publication -- that would attribute an
    article to a publisher on no evidence, which is worse than the refusal."""
    s = _db()
    _seed_with_list_ids(
        s,
        [("a@substack.com", "W1", "weekly.substack.com"),
         ("b@substack.com", "Legacy", None)],
    )
    out = NS.resolution_preview(s)
    by_lid = {g["list_id"]: g for g in out["groups"]}
    assert by_lid["weekly.substack.com"]["basis"] == "platform-list-id"
    assert by_lid[None]["action"] == "refused"
    assert by_lid[None]["articles"] == 1


def test_a_NON_platform_sender_never_splits_on_its_list_id():
    """publisher_key ignores the List-Id off a platform, so splitting there would
    scatter one publisher across rows for a field that cannot change the answer.
    The report reads exactly as it did before for every ordinary sender."""
    s = _db([("BBC News", "bbc.com")])
    _seed_with_list_ids(
        s,
        [("x@email.bbc.com", "One", "news.bbc.co.uk"),
         ("y@email.bbc.com", "Two", "sport.bbc.co.uk"),
         ("z@email.bbc.com", "Three", None)],
    )
    out = NS.resolution_preview(s)
    assert len(out["groups"]) == 1
    assert out["groups"][0]["articles"] == 3
    assert out["groups"][0]["list_id"] is None
    assert out["groups"][0]["action"] == "attach-exact"


def test_the_list_id_column_is_classified_by_the_restore_merge():
    """A column in neither set is silently dropped by the merge's allowlist and
    arrives as a plausible NULL nothing reports (the 2026-08-03 defect). This one
    is ADOPTABLE: duplicates match on HASH, so the incoming row is the same message
    body, and a List-Id is a property of that message, not of the reader."""
    from src.backup.merge import _ADOPTABLE_ARTICLE_COLUMNS, _NOT_ADOPTABLE_ARTICLE_COLUMNS

    adoptable = {c for _a, cols in _ADOPTABLE_ARTICLE_COLUMNS for c in cols}
    assert "newsletter_list_id" in adoptable
    assert "newsletter_list_id" not in _NOT_ADOPTABLE_ARTICLE_COLUMNS
