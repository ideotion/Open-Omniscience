"""A duplicate article must still contribute the metadata this corpus never had.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field question 2026-08-10: "in the case I imported a backup with redundant articles,
yet they would have more metadata (due for example to AI enrichment, or better metadata
extraction engine), the importing process would disregard those redundant articles and
dismiss also the enhanced metadata."

Measured against the unchanged merge, the answer was a SPLIT:

  * the per-article CHILD tables already carried, because ``temp.map_articles`` joins on
    HASH and therefore maps duplicates onto their local twin -- so AI summaries and
    translations (article_analyses), AI-derived metadata (ai_keyword), extracted dates
    and links were never lost;
  * the article's own COLUMNS were dropped, because a duplicate takes the
    ``WHERE NOT EXISTS`` path and nothing updated the local row. A merge of an enriched
    duplicate left detected_language, sentiment, author, word_count and the whole
    server_ip observation at NULL.

So AI enrichment survived and better EXTRACTION did not. These tests pin both halves,
and -- as with the qualification stamp one level up -- both directions of the rule: fill
what was never measured here, never overwrite what was.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup.merge import (
    _ADOPTABLE_ARTICLE_COLUMNS,
    _NOT_ADOPTABLE_ARTICLE_COLUMNS,
    merge_corpus,
)
from src.database.models import AiKeyword, Article, ArticleAnalysis, Base, Source

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}
_T0 = datetime(2026, 7, 1, 9, 0, 0, tzinfo=UTC).replace(tzinfo=None)
_BODY = "The summit opened in Geneva on 3 March 2026 with twelve delegations present."


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _article(s, **kw) -> Article:
    """One article, identical by hash+content on both sides unless told otherwise."""
    s.add(Source(name="x", domain="x.example"))
    s.flush()
    a = Article(
        url="http://x.example/a", canonical_url="http://x.example/a", source_id=1,
        title="Summit", content=kw.pop("content", _BODY), hash=kw.pop("hash", "H1"), **kw,
    )
    s.add(a)
    s.flush()
    return a


def _merged(tmp_path, local: dict, incoming: dict):
    """Same article on both sides; returns (local row after the merge, counts)."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _article(s, **local)
        s.commit()
    with _corpus(staged)() as s:
        _article(s, **incoming)
        s.commit()
    counts, _ = merge_corpus(staged, working, _BATCH_META)
    with _corpus(working)() as s:
        return s.query(Article).one(), counts


# --------------------------------------------------------------------------- #
#  Fill what was never measured here
# --------------------------------------------------------------------------- #
def test_a_duplicate_contributes_the_metadata_this_corpus_never_had(tmp_path):
    """THE field case: same article, enriched on the incoming side."""
    got, counts = _merged(
        tmp_path,
        local={"language": "en"},
        incoming={
            "language": "en", "detected_language": "en", "author": "A. Reporter",
            "word_count": 13, "reading_time": 1, "published_at": _T0,
            "sentiment_score": 0.42, "sentiment_label": "positive",
            "server_ip": "192.0.2.7", "ip_observed_at": _T0,
            "server_ip_reason": "socket peer",
        },
    )
    assert counts["articles"]["new"] == 0, "the fixture must exercise the DUPLICATE path"
    assert counts["articles"]["duplicate"] == 1
    assert got.detected_language == "en"
    assert got.author == "A. Reporter"
    assert got.word_count == 13
    assert got.published_at == _T0
    assert got.sentiment_score == 0.42
    # The one nothing can rebuild: the connection is gone, and a re-fetch reaches a
    # different CDN edge or nothing at all.
    assert got.server_ip == "192.0.2.7"
    assert got.server_ip_reason == "socket peer"


def test_the_enrichment_that_already_worked_still_works(tmp_path):
    """The half that was never broken, pinned so a change to the column path cannot
    quietly take the child tables with it: AI output rides temp.map_articles, which
    joins on hash and therefore maps duplicates onto the local twin."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _article(s, language="en")
        s.commit()
    with _corpus(staged)() as s:
        a = _article(s, language="en")
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result="An AI summary.",
                              model="ministral-3"))
        s.add(AiKeyword(article_id=a.id, term="Geneva", kind="ai-place",
                        model="ministral-3", confirmed=False))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        local_id = s.query(Article).one().id
        assert s.query(ArticleAnalysis).filter_by(article_id=local_id).count() == 1
        assert s.query(AiKeyword).filter_by(article_id=local_id).count() == 1


# --------------------------------------------------------------------------- #
#  Never overwrite what WAS measured here
# --------------------------------------------------------------------------- #
def test_a_local_measurement_is_never_overwritten(tmp_path):
    """The twin. Adoption fills absences; it is not a sync, and the incoming corpus does
    not get to restate this machine's own measurements."""
    got, _ = _merged(
        tmp_path,
        local={"author": "Local Byline", "word_count": 99, "sentiment_score": 0.9,
               "sentiment_label": "positive", "server_ip": "198.51.100.1"},
        incoming={"author": "Other Byline", "word_count": 13, "sentiment_score": -0.5,
                  "sentiment_label": "negative", "server_ip": "192.0.2.7"},
    )
    assert got.author == "Local Byline"
    assert got.word_count == 99
    assert got.sentiment_score == 0.9
    assert got.server_ip == "198.51.100.1"


def test_a_pair_moves_together_or_not_at_all(tmp_path):
    """Sentiment is a score AND its label. A per-column COALESCE would adopt the
    incoming LABEL onto the local SCORE whenever the local label happened to be absent,
    publishing 'negative' next to +0.9 -- a reading no run ever produced. The group is
    anchored on the score, so a local score keeps its own label slot untouched.

    ``author`` is in the fixture ONLY to make the row eligible for the UPDATE at all.
    Without it no anchor fires, the guard skips the row entirely, and the assertion below
    passes for a reason that has nothing to do with pair atomicity -- which is exactly
    what the first draft of this test did, and what the mutation check caught."""
    got, _ = _merged(
        tmp_path,
        local={"sentiment_score": 0.9},                                  # label absent
        incoming={"sentiment_score": -0.5, "sentiment_label": "negative",
                  "author": "A. Reporter"},
    )
    assert got.author == "A. Reporter", "the row must really have been updated"
    assert got.sentiment_score == 0.9, "the local measurement must stand"
    assert got.sentiment_label is None, (
        "a foreign label was grafted onto a local score -- the pair was not atomic"
    )


def test_the_ip_triple_moves_together_or_not_at_all(tmp_path):
    """Same property for the socket observation: an observation time that belongs to a
    different IP is worse than no observation time. ``author`` again only makes the row
    eligible, so the assertion is about atomicity rather than about the guard."""
    got, _ = _merged(
        tmp_path,
        local={"server_ip": "198.51.100.1"},                             # no timestamp
        incoming={"server_ip": "192.0.2.7", "ip_observed_at": _T0,
                  "server_ip_reason": "socket peer", "author": "A. Reporter"},
    )
    assert got.author == "A. Reporter", "the row must really have been updated"
    assert got.server_ip == "198.51.100.1"
    assert got.ip_observed_at is None
    assert got.server_ip_reason is None


def test_an_import_with_nothing_to_add_changes_nothing(tmp_path):
    """The guard's own negative space. Without the WHERE clause every duplicate would be
    rewritten to store the values it already had -- invisible in the result and a full
    row write per duplicate at a ~90% duplicate rate."""
    got, counts = _merged(
        tmp_path,
        local={"author": "Local Byline", "word_count": 99},
        incoming={"author": "Local Byline", "word_count": 99},
    )
    assert got.author == "Local Byline"
    assert counts["_article_metadata"]["articles_enriched"] == 0
    assert counts["_article_metadata"]["by_column"] == {}


# --------------------------------------------------------------------------- #
#  The tally, and the completeness guard
# --------------------------------------------------------------------------- #
def test_the_tally_reports_what_was_actually_filled(tmp_path):
    _, counts = _merged(
        tmp_path,
        local={"author": "Local Byline"},          # kept; only the others can be filled
        incoming={"author": "Other", "detected_language": "en", "word_count": 13},
    )
    m = counts["_article_metadata"]
    assert m["articles_enriched"] == 1
    assert m["by_column"] == {"detected_language": 1, "word_count": 1}, (
        "a column that was NOT filled (author, kept local) must not be counted"
    )


def test_every_article_column_is_either_adoptable_or_refused_with_a_reason():
    """The 2026-08-03 lesson, applied before it can cost anything: an explicit column
    allowlist fails OPEN and in silence, so a column added to the model later is simply
    never carried and nothing says so. Membership of one of the two sets is mandatory,
    which makes a new column a loud choice."""
    model = {c.name for c in Article.__table__.columns}
    adoptable = {c for _, cols in _ADOPTABLE_ARTICLE_COLUMNS for c in cols}
    refused = set(_NOT_ADOPTABLE_ARTICLE_COLUMNS)

    assert not (adoptable & refused), "a column cannot be both adoptable and refused"
    missing = model - adoptable - refused
    assert not missing, (
        f"Article columns in neither set: {sorted(missing)}. Add each to "
        "_ADOPTABLE_ARTICLE_COLUMNS, or to _NOT_ADOPTABLE_ARTICLE_COLUMNS with the "
        "reason a local NULL there does not mean 'never measured here'."
    )
    assert not (adoptable | refused) - model, "a set names a column the model dropped"
    assert all(_NOT_ADOPTABLE_ARTICLE_COLUMNS.values()), "every refusal needs its reason"


def test_a_quarantine_verdict_is_not_smuggled_in_as_a_measurement():
    """Quarantine carries its own criteria version: it is a JUDGEMENT, and judgements
    follow the qualification rule (adopt-if-never-judged, both verdict directions), not
    the fill-a-NULL rule. Adopting it here would silently apply the weaker one."""
    adoptable = {c for _, cols in _ADOPTABLE_ARTICLE_COLUMNS for c in cols}
    for col in ("quarantined", "quarantine_reason", "quarantine_criteria_version",
                "quarantined_at"):
        assert col not in adoptable
        assert col in _NOT_ADOPTABLE_ARTICLE_COLUMNS
