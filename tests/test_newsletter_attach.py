"""The newsletter write-path AUTO-ATTACH, its announcement and its UNDO (Q1151 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

The 2026-06-15 ruling (clause (d)) refused to let the silent attach ship alone: it pairs it
with an import UI that ANNOUNCES the placement and an UNDO for the automated ones. So the
matrix here is mostly not "does it attach". ARTICLES MOVE BETWEEN SOURCES, which makes this a
data-safety change, and a data-safety change is judged on the cases where it must do nothing:

  * a near miss must never attach (``bbc`` is not ``nbc`` -- the resolver's rule, re-checked
    from the write path because a wiring bug could bypass it);
  * a refusal must stay in the bucket AND carry no attach record, because a record beside a
    placement the app did not make would have the undo move an article it never touched;
  * the undo must restore EXACTLY its own placements and nothing a person filed by hand;
  * and every reader that meant "an imported newsletter" by asking about the SOURCE must keep
    meaning it -- two of those readers are privacy gates, and a newsletter filed under its
    publisher would have slipped through both.

NOT MEASURABLE HERE, and not claimed: a real operator restore of a backup taken with
newsletters excluded. The exclusion is measured below on a real snapshot database; the
restore of that snapshot into a live install is an operator step (0.4 gate rows A/E).
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog import publicsuffix as PS
from src.database.models import Article, Base, Source
from src.ingest.email import (
    count_imported_newsletters,
    delete_imported_newsletters,
    ingest_emails,
)

_BUCKET = "newsletters.import.local"


@pytest.fixture(autouse=True)
def _fresh_psl_cache():
    PS._reset_cache_for_tests()
    yield
    PS._reset_cache_for_tests()


def _db(sources: list[tuple[str, str]] | None = None):
    """An ISOLATED in-memory session (never SessionLocal -- a shared-store write pollutes
    every later test that reads it)."""
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for name, domain in sources or []:
        s.add(Source(name=name, domain=domain, enabled=True))
    s.commit()
    return s


def _bucket(session) -> Source:
    src = Source(name="Imported newsletters (.eml)", domain=_BUCKET,
                 enabled=False, source_type="newsletter")
    session.add(src)
    session.commit()
    return src


def _eml(sender: str, subject: str, mid: str, *, list_id: str | None = None) -> bytes:
    head = (
        f"From: Publisher <{sender}>\n"
        f"Subject: {subject}\n"
        f"Message-ID: <{mid}>\n"
        "Date: Mon, 05 Jan 2026 18:00:00 +0000\n"
    )
    if list_id:
        head += f"List-Id: The list <{list_id}>\n"
    return (
        head + "Content-Type: text/plain; charset=utf-8\n\n"
        f"A newsletter body about {subject} with enough ordinary sentences in it that the "
        "importer treats it as real prose rather than an empty shell.\n"
    ).encode("utf-8")


def _placed(session) -> dict[str, tuple[str | None, str | None]]:
    """title -> (source domain, attach record)."""
    return {
        a.title: (session.get(Source, a.source_id).domain, a.newsletter_attached_via)
        for a in session.query(Article)
    }


# --------------------------------------------------------------------------------------- #
# 1. the ladder, run from the write path
# --------------------------------------------------------------------------------------- #
def test_an_exact_domain_hit_files_the_newsletter_under_the_publisher_you_track():
    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    tally = ingest_emails(s, b, [_eml("news@email.bbc.com", "Exact", "e1@x")])
    assert tally["stored"] == 1
    assert _placed(s)["Exact"] == ("bbc.com", "attach-exact:etld1")
    assert tally["attached_existing"] == 1


def test_an_alias_hit_files_it_under_the_source_the_alias_map_names():
    s = _db([("BBC UK", "bbc.co.uk")])
    b = _bucket(s)
    ingest_emails(s, b, [_eml("news@email.bbc.com", "Alias", "a1@x")])
    domain, via = _placed(s)["Alias"]
    assert domain == "bbc.co.uk"
    assert via is not None and via.startswith("attach-alias:")


def test_an_unknown_publisher_gets_a_new_source_that_is_DISABLED():
    """The ladder's fourth rung, and the word DISABLED is the load-bearing half: arriving by
    email is not consent to start scraping the sender's website."""
    s = _db()
    b = _bucket(s)
    ingest_emails(s, b, [_eml("hello@thenewthing.example", "Fresh", "f1@x")])
    domain, via = _placed(s)["Fresh"]
    assert domain == "thenewthing.example"
    assert via is not None and via.startswith("new-email-source:")
    created = s.query(Source).filter_by(domain="thenewthing.example").one()
    assert created.enabled is False
    assert created.source_type == "newsletter"


def test_a_refusal_stays_in_the_bucket_AND_carries_no_attach_record():
    """A bare platform host names no publication, so attaching would merge every publisher on
    that platform into one source. The refusal is a gap; the missing record is what keeps the
    undo from later "restoring" an article the app never moved."""
    s = _db()
    b = _bucket(s)
    ingest_emails(s, b, [_eml("digest@substack.com", "Refused", "r1@x")])
    assert _placed(s)["Refused"] == (_BUCKET, None)


# --------------------------------------------------------------------------------------- #
# 2. negative space — what must NOT happen
# --------------------------------------------------------------------------------------- #
def test_a_near_miss_is_never_merged_onto_the_source_it_resembles():
    """``bbc`` is not ``nbc``. The resolver enforces it; this re-checks it from the WRITE
    path, because a wiring bug that reached past the resolver would look identical from the
    outside until somebody's articles were under the wrong publisher."""
    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    ingest_emails(s, b, [_eml("news@email.nbc.com", "NearMiss", "n1@x")])
    domain, via = _placed(s)["NearMiss"]
    assert domain != "bbc.com"
    assert domain == "nbc.com"
    assert via is not None and via.startswith("new-email-source:")


def test_two_publications_on_one_platform_never_collapse_into_one_source():
    s = _db()
    b = _bucket(s)
    ingest_emails(s, b, [
        _eml("a@substack.com", "First", "p1@x", list_id="first.substack.com"),
        _eml("b@substack.com", "Second", "p2@x", list_id="second.substack.com"),
    ])
    placed = _placed(s)
    assert placed["First"][0] != placed["Second"][0], placed


# --------------------------------------------------------------------------------------- #
# 3. the tally the import UI announces
# --------------------------------------------------------------------------------------- #
def test_the_three_attach_counters_account_for_every_stored_article():
    """The screen shows these three beside `stored`; if they do not sum to it, the user is
    being told about a set of articles that is not the set that was imported."""
    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    tally = ingest_emails(s, b, [
        _eml("news@email.bbc.com", "Known", "t1@x"),
        _eml("hi@brandnew.example", "New", "t2@x"),
        _eml("digest@substack.com", "Refused", "t3@x"),
    ])
    assert tally["stored"] == 3
    assert (tally["attached_existing"] + tally["attached_new_source"]
            + tally["attach_refused"]) == tally["stored"]
    assert (tally["attached_existing"], tally["attached_new_source"],
            tally["attach_refused"]) == (1, 1, 1)


# --------------------------------------------------------------------------------------- #
# 4. the undo — exactness is the whole feature
# --------------------------------------------------------------------------------------- #
def _undo(session):
    from src.api.ingestion import newsletter_attach_undo

    return newsletter_attach_undo(db=session)


def test_undo_restores_the_placement_exactly_and_clears_the_record():
    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    ingest_emails(s, b, [_eml("news@email.bbc.com", "Moved", "u1@x")])
    assert _placed(s)["Moved"] == ("bbc.com", "attach-exact:etld1")
    out = _undo(s)
    assert out["restored"] == 1
    assert _placed(s)["Moved"] == (_BUCKET, None)


def test_undo_never_touches_an_article_a_person_filed_by_hand():
    """The column is written by nothing else in the tree, so "the app put this here" is a
    fact rather than an inference -- which is what lets the undo be this narrow."""
    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    hand = Source(name="Hand-filed", domain="hand.example", enabled=True)
    s.add(hand)
    s.commit()
    ingest_emails(s, b, [_eml("news@email.bbc.com", "Auto", "h1@x")])
    mine = Article(url="local:hand", canonical_url="local:hand", source_id=hand.id,
                   title="Mine", content="body", hash="hand-hash")
    s.add(mine)
    s.commit()
    _undo(s)
    assert _placed(s)["Mine"] == ("hand.example", None)


def test_undo_never_touches_a_newsletter_the_ladder_refused():
    s = _db()
    b = _bucket(s)
    ingest_emails(s, b, [_eml("digest@substack.com", "Refused", "x1@x")])
    out = _undo(s)
    assert out["restored"] == 0
    assert _placed(s)["Refused"] == (_BUCKET, None)


def test_a_second_undo_is_a_no_op_rather_than_a_second_move():
    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    ingest_emails(s, b, [_eml("news@email.bbc.com", "Once", "o1@x")])
    assert _undo(s)["restored"] == 1
    assert _undo(s)["restored"] == 0


def test_undo_deletes_the_source_it_created_and_never_one_that_existed_before():
    """Deleting a source the operator configured would be a second, unasked-for change riding
    along with the undo. An empty pre-existing source stays empty and stays."""
    s = _db([("Pre-existing", "known.example")])
    b = _bucket(s)
    ingest_emails(s, b, [
        _eml("hi@created.example", "Created", "d1@x"),
        _eml("news@known.example", "Known", "d2@x"),
    ])
    out = _undo(s)
    assert out["sources_deleted"] == ["created.example"]
    assert s.query(Source).filter_by(domain="created.example").first() is None
    assert s.query(Source).filter_by(domain="known.example").first() is not None


def test_undo_never_deletes_a_source_that_still_holds_an_article():
    """The data-loss case, and it is literal: ``Source.articles`` is mapped
    ``cascade="all, delete-orphan"``, so deleting a Source DELETES ITS ARTICLES. A source the
    ladder created can pick up articles the undo will NOT restore -- anything a person filed
    into it afterwards, which carries no attach record by definition. So emptiness is checked
    AFTER the restore, and the source survives whenever anything is left in it."""
    from src.api.ingestion import newsletter_attach_undo

    s = _db()
    b = _bucket(s)
    ingest_emails(s, b, [_eml("hi@created.example", "Auto", "k1@x")])
    created = s.query(Source).filter_by(domain="created.example").one()
    s.add(Article(url="local:kept", canonical_url="local:kept", source_id=created.id,
                  title="Kept", content="body", hash="kept-hash"))
    s.commit()

    out = newsletter_attach_undo(db=s)
    assert out["restored"] == 1
    assert out["sources_deleted"] == [], "a source holding an article was deleted"
    assert s.query(Source).filter_by(domain="created.example").first() is not None
    assert {a.title for a in s.query(Article)} == {"Auto", "Kept"}


def test_undo_never_deletes_a_users_own_disabled_newsletter_source():
    """The case a flag heuristic gets wrong. "disabled + newsletter-typed + now empty" is a
    shape a USER's own source can have -- the mailbox bucket is one -- so deleting on those
    three facts would delete theirs. What actually proves the source is ours is the rung the
    ladder RECORDED: an `attach-exact` article can only exist against a source that was
    already there."""
    from src.api.ingestion import newsletter_attach_undo

    s = _db()
    b = _bucket(s)
    mine = Source(name="My own quiet feed", domain="quiet.example",
                  enabled=False, source_type="newsletter")
    s.add(mine)
    s.commit()
    ingest_emails(s, b, [_eml("news@quiet.example", "Theirs", "z1@x")])
    # it matched the user's existing source, so the record says attach-exact
    assert _placed(s)["Theirs"] == ("quiet.example", "attach-exact:etld1")
    out = newsletter_attach_undo(db=s)
    assert out["restored"] == 1
    assert out["sources_deleted"] == []
    assert s.query(Source).filter_by(domain="quiet.example").first() is not None


# --------------------------------------------------------------------------------------- #
# 5. every reader that meant "an imported newsletter" must still mean it
# --------------------------------------------------------------------------------------- #
def test_an_attached_newsletter_is_still_counted_as_an_imported_newsletter():
    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    ingest_emails(s, b, [_eml("news@email.bbc.com", "Counted", "c1@x")])
    assert count_imported_newsletters(s) == 1


def test_remove_imported_newsletters_still_removes_an_attached_one():
    """The screen promises it removes EVERY imported-newsletter article. A source-only
    definition would have left the attached ones behind while saying otherwise."""
    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    ingest_emails(s, b, [_eml("news@email.bbc.com", "Gone", "g1@x")])
    out = delete_imported_newsletters(s)
    assert out["removed_articles"] == 1
    assert s.query(Article).count() == 0


def test_the_preview_still_sees_newsletters_it_has_already_filed():
    """Otherwise the preview reports an ever-shrinking corpus as the attach succeeds -- i.e.
    the feature working would look like the feature losing data."""
    from src.ingest.newsletter_source import resolution_preview

    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    ingest_emails(s, b, [_eml("news@email.bbc.com", "Seen", "s1@x")])
    out = resolution_preview(s)
    assert out["articles"] == 1, out


def test_the_backup_newsletter_exclusion_drops_an_attached_one():
    """PRIVACY, not counting: a user who unticks "include newsletters" must not find every
    auto-filed newsletter body in the backup because it now sits under its publisher."""
    from src.backup.artifact import _drop_newsletter_rows

    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE sources (id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INTEGER,"
        " newsletter_attached_via TEXT);"
        f"INSERT INTO sources VALUES (1, '{_BUCKET}'), (2, 'bbc.com');"
        "INSERT INTO articles VALUES (10, 1, NULL);"          # refused, in the bucket
        "INSERT INTO articles VALUES (11, 2, 'attach-exact:etld1');"  # auto-filed
        "INSERT INTO articles VALUES (12, 2, NULL);"          # a real scraped bbc.com article
    )
    assert _drop_newsletter_rows(con) == 2
    left = [r[0] for r in con.execute("SELECT id FROM articles ORDER BY id")]
    assert left == [12], "a scraped article was dropped, or a newsletter survived"
    con.close()


def test_the_backup_exclusion_still_works_on_a_snapshot_without_the_column():
    """It runs against an arbitrary snapshot, including one an older build wrote. Absent
    column -> bucket-only, which is exactly right for a snapshot in which nothing was ever
    auto-filed. Raising there would break backups of older corpora."""
    from src.backup.artifact import _drop_newsletter_rows

    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE sources (id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INTEGER);"
        f"INSERT INTO sources VALUES (1, '{_BUCKET}');"
        "INSERT INTO articles VALUES (10, 1);"
    )
    assert _drop_newsletter_rows(con) == 1
    con.close()


def test_the_quality_bundle_still_gates_an_attached_newsletters_body():
    """The other privacy gate. The diagnostic zip withholds private .eml bodies by default; a
    per-SOURCE test would have exported exactly the bodies it exists to hold back."""
    from src.analytics.source_quality import build_sample_records

    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    ingest_emails(s, b, [_eml("news@email.bbc.com", "Private", "q1@x")])
    art = s.query(Article).one()
    bucket_ids = {int(b.id)}
    recs = build_sample_records(
        s, {int(art.id): ["control"]}, bucket_ids, include_newsletter_text=False
    )
    assert len(recs) == 1
    assert recs[0]["is_newsletter"] is True
    assert recs[0]["text_head_gated"] is True
    assert recs[0]["text_head"] is None


# --------------------------------------------------------------------------------------- #
# 6. the announcement surface
# --------------------------------------------------------------------------------------- #
def test_the_summary_groups_by_destination_and_states_its_method_and_caveat():
    from src.api.ingestion import newsletter_attach_summary

    s = _db([("BBC", "bbc.com")])
    b = _bucket(s)
    ingest_emails(s, b, [
        _eml("news@email.bbc.com", "One", "m1@x"),
        _eml("more@email.bbc.com", "Two", "m2@x"),
        _eml("hi@other.example", "Three", "m3@x"),
    ])
    out = newsletter_attach_summary(db=s)
    assert out["attached"] == 3
    assert [g["articles"] for g in out["groups"]] == [2, 1], out["groups"]
    assert out["groups"][0]["source_domain"] == "bbc.com"
    assert out["groups"][1]["source_enabled"] is False
    # Informed consent: the method and the caveat travel WITH the numbers, never separately.
    assert "deterministic or refused" in out["method"].lower()
    assert "never that the two are equally reliable" in out["caveat"]


def test_an_untouched_corpus_reports_nothing_rather_than_an_empty_shell():
    from src.api.ingestion import newsletter_attach_summary

    s = _db()
    _bucket(s)
    out = newsletter_attach_summary(db=s)
    assert out["attached"] == 0 and out["groups"] == []
