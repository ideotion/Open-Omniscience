"""The restore-merge matches a source on (domain, feed), never on the domain alone (row J, S05-10).

Before the key moved, ``m.domain = i.domain`` was an identity join. With several sources per domain it fans out: one
incoming row against N local rows, a ``map_sources`` that sends every later table's rows (articles above all) to the
wrong feed, and an adoption UPDATE whose scalar subquery picks an arbitrary sibling. These tests build real corpora and
run the real ``merge_corpus``.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup.merge import merge_corpus
from src.database.models import Article, Base, Source

_META = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0",
         "alembic_rev": "head", "manifest": None}


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _src(s, domain, feed, *, status="unqualified", name=None, article=None):
    row = Source(name=name or f"{domain} {feed or 'nofeed'}", domain=domain, rss_url=feed, status=status)
    s.add(row)
    s.flush()
    if article:
        s.add(Article(title=article, url=f"https://{domain}/{article}", canonical_url=f"https://{domain}/{article}",
                      source_id=row.id, content=article, hash=(article.encode().hex() * 64)[:64]))
    return row.id


def _rows(path: Path):
    with _corpus(path)() as s:
        return sorted((r.domain, r.feed_key, r.status) for r in s.query(Source).all())


def _article_feed(path: Path, title: str):
    with _corpus(path)() as s:
        a = s.query(Article).filter_by(title=title).one()
        return s.get(Source, a.source_id).feed_key


def _run(tmp_path, local, incoming):
    staged, working = tmp_path / "staged.db", tmp_path / "working.db"
    with _corpus(staged)() as s:
        incoming(s)
        s.commit()
    with _corpus(working)() as s:
        local(s)
        s.commit()
    report, _batch = merge_corpus(staged, working, _META)
    _LAST_REPORT[str(tmp_path)] = report
    return working


_LAST_REPORT: dict[str, dict] = {}


def _report_of(tmp_path):
    return _LAST_REPORT[str(tmp_path)]


def test_two_feeds_of_one_domain_arrive_as_two_sources_and_keep_their_articles(tmp_path):
    def incoming(s):
        _src(s, "bbc.com", "https://feeds.bbci.co.uk/news/rss.xml", article="en1")
        _src(s, "bbc.com", "https://feeds.bbci.co.uk/arabic/rss.xml", article="ar1")

    working = _run(tmp_path, lambda s: None, incoming)
    assert [r[:2] for r in _rows(working)] == [
        ("bbc.com", "f:feeds.bbci.co.uk/arabic/rss.xml"), ("bbc.com", "f:feeds.bbci.co.uk/news/rss.xml")]
    assert _article_feed(working, "en1") == "f:feeds.bbci.co.uk/news/rss.xml"
    assert _article_feed(working, "ar1") == "f:feeds.bbci.co.uk/arabic/rss.xml"


def test_a_known_feed_is_not_duplicated_and_the_new_sibling_lands(tmp_path):
    def local(s):
        _src(s, "dw.com", "https://dw.com/en/rss", article="local")

    def incoming(s):
        _src(s, "dw.com", "https://dw.com/en/rss/", article="same-feed-other-spelling")
        _src(s, "dw.com", "https://dw.com/es/rss", article="es1")

    working = _run(tmp_path, local, incoming)
    assert [r[:2] for r in _rows(working)] == [("dw.com", "f:dw.com/en/rss"), ("dw.com", "f:dw.com/es/rss")]
    assert _article_feed(working, "same-feed-other-spelling") == "f:dw.com/en/rss"
    assert _article_feed(working, "es1") == "f:dw.com/es/rss"


def test_an_old_domain_keyed_backup_does_not_duplicate_a_feed_keyed_source(tmp_path):
    """A pre-migration backup has no feed_key of its own (every row reads ''); the join recomputes it from rss_url."""
    def local(s):
        _src(s, "lemonde.fr", "https://lemonde.fr/rss/une.xml")

    def incoming(s):
        _src(s, "lemonde.fr", "https://lemonde.fr/rss/une.xml")
        s.execute(Source.__table__.update().values(feed_key=""))  # what an older backup carries

    working = _run(tmp_path, local, incoming)
    assert len(_rows(working)) == 1


def test_a_feed_the_catalogue_has_since_corrected_is_not_resurrected_as_a_second_source(tmp_path):
    """One source of the domain on each side: the same source, even though the feed differs (local wins)."""
    def local(s):
        _src(s, "stuff.co.nz", "https://www.stuff.co.nz/rss")

    def incoming(s):
        _src(s, "stuff.co.nz", "https://www.stuff.co.nz/old-rss.xml")

    working = _run(tmp_path, local, incoming)
    assert [r[:2] for r in _rows(working)] == [("stuff.co.nz", "f:www.stuff.co.nz/rss")]


def test_when_a_side_holds_several_only_the_exact_feed_matches(tmp_path):
    def local(s):
        _src(s, "x.com", "https://x.com/a")
        _src(s, "x.com", "https://x.com/b")

    def incoming(s):
        _src(s, "x.com", "https://x.com/c")  # not either of the two local feeds

    working = _run(tmp_path, local, incoming)
    assert [r[1] for r in _rows(working)] == ["f:x.com/a", "f:x.com/b", "f:x.com/c"]


def test_a_verdict_is_adopted_by_the_sibling_it_belongs_to_and_only_that_one(tmp_path):
    def local(s):
        _src(s, "y.com", "https://y.com/a")
        _src(s, "y.com", "https://y.com/b")

    def incoming(s):
        _src(s, "y.com", "https://y.com/a", status="unqualified")
        _src(s, "y.com", "https://y.com/b", status="disqualified")

    working = _run(tmp_path, local, incoming)
    assert _rows(working) == [("y.com", "f:y.com/a", "unqualified"), ("y.com", "f:y.com/b", "disqualified")]


def _legacy_working(s):
    """A store whose rebuild was refused at boot: ``sources`` still carries a UNIQUE key on the domain alone."""
    s.execute(__import__("sqlalchemy").text("CREATE UNIQUE INDEX legacy_domain ON sources(domain)"))


def test_a_backup_with_two_feeds_of_a_site_is_refused_by_name_when_the_store_cannot_hold_them(tmp_path):
    """Opus read, finding 6: without the check the INSERT breaks UNIQUE (domain) and the merge rolls back as a raw
    integrity error nobody can read; with it, a MergeError in words and the live store untouched."""
    import pytest

    from src.backup.merge import MergeError

    with pytest.raises(MergeError, match="several feeds"):
        _run(
            tmp_path,
            lambda s: (_src(s, "bbc.com", "https://bbc.com/en"), _legacy_working(s)),
            lambda s: (_src(s, "bbc.com", "https://bbc.com/en"), _src(s, "bbc.com", "https://bbc.com/ar")),
        )


def test_a_one_feed_per_site_backup_still_merges_into_a_legacy_store(tmp_path):
    working = _run(
        tmp_path,
        lambda s: (_src(s, "bbc.com", "https://bbc.com/en"), _legacy_working(s)),
        lambda s: (_src(s, "bbc.com", "https://bbc.com/en"), _src(s, "dw.com", "https://dw.com/rss")),
    )
    assert [r[0] for r in _rows(working)] == ["bbc.com", "dw.com"]


# --- R148: a feed the local outlet does not hold lands as a new sibling, with the outlet's verdict, and is reported ---
def test_an_unmatched_feed_lands_as_a_sibling_takes_the_outlets_verdict_and_is_listed(tmp_path):
    """R148 (coordinator, 2026-10-16): the sibling is created, takes the outlet's measured verdict (never laundered to
    the qualified another instance gave it), and the merge report lists it with its reason and counts it."""
    from src.database.models import SourceQualificationAttempt

    staged, working = tmp_path / "staged.db", tmp_path / "working.db"
    with _corpus(staged)() as s:
        # an old domain-keyed backup: one feed per domain, a feed this store does not hold, judged QUALIFIED elsewhere
        _src(s, "dw.com", "https://dw.com/old-feed", status="qualified")
        s.commit()
    with _corpus(working)() as s:
        _src(s, "dw.com", "https://dw.com/en", status="disqualified")
        _src(s, "dw.com", "https://dw.com/de", status="unqualified")
        s.commit()
    report, _batch = merge_corpus(staged, working, _META)

    rows = {r[1]: r for r in _rows(working)}
    assert "f:dw.com/old-feed" in rows  # created: the extra sibling
    assert rows["f:dw.com/old-feed"][2] == "disqualified"  # the outlet's verdict, not the incoming qualified
    with _corpus(working)() as s:
        sib = s.query(Source).filter_by(rss_url="https://dw.com/old-feed").one()
        assert "inherited" in [a.verdict for a in s.query(SourceQualificationAttempt).filter_by(source_id=sib.id)]
    sources = report["sources"]
    assert sources["added_as_sibling"] == 1
    entry = sources["siblings"][0]
    assert entry["domain"] == "dw.com" and entry["verdict_inherited"] is True
    assert entry["reason"] == "feed not present locally, added under outlet dw.com https://dw.com/en"  # the oldest local row names the outlet


def _stamp(path: Path, feed: str, criteria: str):
    with _corpus(path)() as s:
        s.query(Source).filter_by(rss_url=feed).one().qualification_criteria_version = criteria
        s.commit()


def test_a_catalogue_stamp_is_provenance_not_a_verdict_the_sibling_inherits(tmp_path):
    """R148 (a), kept by R153: a catalogue-curated 'qualified' on the outlet's only stamped row is not handed on; the
    incoming disqualified feed keeps its own verdict and is NOT reported as inheriting one."""
    from src.catalog.qualification import CURATED_CRITERIA_VERSION

    def local(s):
        _src(s, "dw.com", "https://dw.com/en", status="qualified")
        _src(s, "dw.com", "https://dw.com/de", status="unqualified")
        s.flush()
        s.query(Source).filter_by(rss_url="https://dw.com/en").one().qualification_criteria_version = CURATED_CRITERIA_VERSION

    working = _run(tmp_path, local, lambda s: _src(s, "dw.com", "https://dw.com/old-feed", status="disqualified"))
    rows = {r[1]: r for r in _rows(working)}
    assert rows["f:dw.com/old-feed"][2] == "disqualified"
    report = _report_of(tmp_path)
    assert report["sources"]["siblings"][0]["verdict_inherited"] is False


def test_the_qualification_tally_counts_what_lands_not_what_arrived(tmp_path):
    """The sibling arrives 'qualified' and lands 'disqualified' (the outlet's verdict): the tally must say
    introduced_disqualified, not introduced_qualified."""
    def local(s):
        _src(s, "dw.com", "https://dw.com/en", status="disqualified")
        _src(s, "dw.com", "https://dw.com/de", status="unqualified")

    _run(tmp_path, local, lambda s: _src(s, "dw.com", "https://dw.com/old-feed", status="qualified"))
    tally = _report_of(tmp_path)["_source_qualification"]
    assert tally["introduced_disqualified"] == 1
    assert tally["introduced_qualified"] == 0


def test_a_disqualified_feed_anywhere_in_the_outlet_decides_not_only_the_oldest_row(tmp_path):
    """R150/R153: the outlet's oldest measured row is qualified, a later feed is disqualified: the sibling lands
    disqualified (the stricter verdict wins; the oldest row does not)."""
    def local(s):
        _src(s, "dw.com", "https://dw.com/en", status="qualified")  # oldest measured row
        _src(s, "dw.com", "https://dw.com/de", status="unqualified")
        _src(s, "dw.com", "https://dw.com/fr", status="disqualified")  # newest, and decides

    working = _run(tmp_path, local, lambda s: _src(s, "dw.com", "https://dw.com/old-feed", status="qualified"))
    assert {r[1]: r for r in _rows(working)}["f:dw.com/old-feed"][2] == "disqualified"


def test_a_qualified_outlet_hands_nothing_on_the_sibling_keeps_its_own_evidence(tmp_path):
    """R153: verdicts are handed on in the disqualified direction ONLY. Under a qualified outlet an incoming
    unjudged feed stays unjudged (its own trial), an incoming disqualified one stays disqualified, and an incoming
    qualified one keeps the qualified another instance measured on that very feed."""
    def local(s):
        _src(s, "dw.com", "https://dw.com/en", status="qualified")
        _src(s, "dw.com", "https://dw.com/de", status="unqualified")

    def incoming(s):
        _src(s, "dw.com", "https://dw.com/a", status="unqualified")
        _src(s, "dw.com", "https://dw.com/b", status="disqualified")
        _src(s, "dw.com", "https://dw.com/c", status="qualified")

    working = _run(tmp_path, local, incoming)
    rows = {r[1]: r[2] for r in _rows(working)}
    assert rows["f:dw.com/a"] == "unqualified" and rows["f:dw.com/b"] == "disqualified" and rows["f:dw.com/c"] == "qualified"
    entries = _report_of(tmp_path)["sources"]["siblings"]
    assert len(entries) == 3 and not any(e["verdict_inherited"] for e in entries)
    assert all("not handed on" in e["verdict_rule"] for e in entries)


def test_an_incoming_row_without_a_feed_is_not_reported_as_a_feed(tmp_path):
    def local(s):
        _src(s, "dw.com", "https://dw.com/en")
        _src(s, "dw.com", "https://dw.com/de")

    _run(tmp_path, local, lambda s: _src(s, "dw.com", None))
    entry = _report_of(tmp_path)["sources"]["siblings"][0]
    assert entry["incoming_feed"] is None
    assert entry["reason"].startswith("entry without a feed")


def test_when_the_outlets_feeds_disagree_the_stricter_verdict_wins_and_the_report_names_the_rule(tmp_path):
    """R150/R153: en (oldest measured) is qualified, de is disqualified; an incoming QUALIFIED feed lands disqualified,
    and the report says a measured feed decided. With no disqualified feed nothing is handed on (the rule says so)."""
    def local(s):
        _src(s, "dw.com", "https://dw.com/en", status="qualified")
        _src(s, "dw.com", "https://dw.com/de", status="disqualified")
        _src(s, "bbc.com", "https://bbc.com/a", status="qualified")
        _src(s, "bbc.com", "https://bbc.com/b", status="unqualified")

    def incoming(s):
        _src(s, "dw.com", "https://dw.com/old-feed", status="qualified")
        _src(s, "bbc.com", "https://bbc.com/old-feed", status="disqualified")

    working = _run(tmp_path, local, incoming)
    rows = {r[1]: r for r in _rows(working)}
    assert rows["f:dw.com/old-feed"][2] == "disqualified"  # a disqualified feed of the outlet decides
    assert rows["f:bbc.com/old-feed"][2] == "disqualified"  # a qualified outlet hands nothing on: the feed's own evidence
    rules = {e["domain"]: e["verdict_rule"] for e in _report_of(tmp_path)["sources"]["siblings"]}
    assert rules == {
        "dw.com": "a measured feed of the outlet is disqualified",
        "bbc.com": "no feed of the outlet is disqualified (a qualified verdict is not handed on)",
    }
