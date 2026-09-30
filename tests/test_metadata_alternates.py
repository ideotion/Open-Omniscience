"""R61 (item 12): a restore keeps the OTHER value beside the local one, never instead of it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's rule (2026-09-29): deduced metadata rides backups with provenance; on a
contradiction imported data never prevails over local data, both are kept and reachable.
Every test here merges into a DIFFERENT corpus, because a self-restore sees every row as a
duplicate and never reaches the interesting branch.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.backup.provenance import provenance_tag  # noqa: E402
from src.database.models import (  # noqa: E402
    AiKeyword,
    Article,
    ArticleAnalysis,
    ArticleMentionedDate,
    ArticleTitleTranslation,
    Base,
    KeywordTranslation,
    LawDocument,
    LawRevision,
    LawRevisionSummary,
    MetadataAlternate,
    Source,
)

_META = {
    "artifact_kind": "oo-backup-3",
    "origin_fingerprint": "machine-B",
    "app_version": "0.5.0",
    "alembic_rev": "head",
    "manifest": None,
}
_T0 = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _article(s, hash_="h1"):
    src = s.query(Source).filter_by(domain="s.example").first()
    if src is None:
        src = Source(name="S", domain="s.example")
        s.add(src)
        s.flush()
    art = Article(
        url=f"https://s.example/{hash_}", canonical_url=f"https://s.example/{hash_}",
        source_id=src.id, title="T", content="c", hash=hash_,
    )
    s.add(art)
    s.flush()
    return art


def _two(tmp_path, incoming, local):
    """Populate an incoming and a local corpus, then merge incoming into local."""
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(inc)() as s:
        incoming(s)
        s.commit()
    with _corpus(live)() as s:
        local(s)
        s.commit()
    counts, batch = merge_corpus(inc, live, _META)
    return counts, batch, live, inc


def _alts(live):
    with _corpus(live)() as s:
        return [
            (a.table_name, json.loads(a.identity), json.loads(a.fields),
             json.loads(a.provenance), a.status, a.origin)
            for a in s.query(MetadataAlternate).order_by(MetadataAlternate.id)
        ]


def test_a_contradicting_translation_is_kept_beside_the_local_one(tmp_path):
    def tr(text):
        return lambda s: s.add(KeywordTranslation(
            term="chat", source_lang="fr", target_lang="en", text=text, model="m1",
            prompt_version="v1", created_at=_T0))

    counts, batch, live, _ = _two(tmp_path, tr("INCOMING"), tr("LOCAL"))

    with _corpus(live)() as s:
        assert s.query(KeywordTranslation).one().text == "LOCAL"   # local never gives way
    [(table, identity, fields, prov, status, origin)] = _alts(live)
    assert table == "keyword_translations"
    assert identity["term"] == "chat" and identity["model"] == "m1"
    assert fields == {"text": "INCOMING"}
    assert (status, origin) == ("pending", "machine-B")
    # the provenance tag names who produced it, when, and which restore brought it
    assert prov["v"] == 1 and prov["kind"] == "model" and prov["producer"] == "m1"
    assert prov["version"] == "v1" and prov["origin"] == "machine-B"
    assert prov["arrived"]["batch"] == batch and prov["arrived"]["app_version"] == "0.5.0"
    assert counts["keyword_translations"]["conflict"] == 1


def test_an_identical_value_is_not_a_contradiction(tmp_path):
    def tr(s):
        s.add(KeywordTranslation(term="chat", source_lang="fr", target_lang="en", text="cat",
                                 model="m1", prompt_version="v1", created_at=_T0))

    counts, _, live, _ = _two(tmp_path, tr, tr)
    assert _alts(live) == []
    assert counts["keyword_translations"]["conflict"] == 0


def test_restoring_the_same_backup_twice_records_the_difference_once(tmp_path):
    def inc(s):
        s.add(KeywordTranslation(term="chat", source_lang="fr", target_lang="en", text="X",
                                 model="m1", prompt_version="v1", created_at=_T0))

    def loc(s):
        s.add(KeywordTranslation(term="chat", source_lang="fr", target_lang="en", text="Y",
                                 model="m1", prompt_version="v1", created_at=_T0))

    _, _, live, incoming = _two(tmp_path, inc, loc)
    merge_corpus(incoming, live, _META)
    assert len(_alts(live)) == 1


def test_a_title_translation_is_carried_and_a_contradiction_kept(tmp_path):
    def add(title):
        def f(s):
            a = _article(s)
            s.add(ArticleTitleTranslation(
                article_id=a.id, source_lang="fr", target_lang="en", title=title, summary="s",
                model="m1", prompt_version="tt-v1", created_at=_T0))
        return f

    # into a corpus that has the article but no ≈ title: carried (new), no alternate
    counts, _, live, _ = _two(tmp_path, add("Incoming"), lambda s: _article(s))
    with _corpus(live)() as s:
        assert s.query(ArticleTitleTranslation).one().title == "Incoming"
    assert counts["article_title_translations"]["new"] == 1
    assert _alts(live) == []

    # into a corpus that has a DIFFERENT ≈ title for the same article: local stays, other kept
    tmp2 = tmp_path / "second"
    tmp2.mkdir()
    counts, _, live, _ = _two(tmp2, add("Incoming"), add("Local"))
    with _corpus(live)() as s:
        assert s.query(ArticleTitleTranslation).one().title == "Local"
    [(table, identity, fields, prov, _, _)] = _alts(live)
    assert table == "article_title_translations"
    assert identity["article_hash"] == "h1", "an article is named by its hash, not a local id"
    assert fields["title"] == "Incoming" and prov["kind"] == "model"


def test_a_date_confirmed_elsewhere_is_kept_as_a_human_judgement(tmp_path):
    def dt(status, snippet):
        def f(s):
            a = _article(s)
            s.add(ArticleMentionedDate(
                article_id=a.id, mentioned_on=date(1945, 8, 6), precision="day", snippet=snippet,
                confidence=0.9, extractor="dateextract", status=status, created_at=_T0))
        return f

    _, _, live, _ = _two(tmp_path, dt("confirmed", "6 Aug 1945"), dt("candidate", "6 Aug 1945"))
    with _corpus(live)() as s:
        assert s.query(ArticleMentionedDate).one().status == "candidate"
    [(_, _, fields, prov, _, _)] = _alts(live)
    assert fields["status"] == "confirmed"
    assert prov["kind"] == "human" and prov["producer"] == "user"

    # a different snippet alone is no contradiction: the status is what a person decides
    tmp2 = tmp_path / "b"
    tmp2.mkdir()
    _, _, live2, _ = _two(tmp2, dt("candidate", "SNIPPET A"), dt("candidate", "SNIPPET B"))
    assert _alts(live2) == []


def test_an_analysis_and_an_ai_keyword_that_disagree_are_kept(tmp_path):
    def add(result, confirmed):
        def f(s):
            a = _article(s)
            s.add(ArticleAnalysis(article_id=a.id, kind="summary", result=result, model="m",
                                  prompt_version="v1", prompt_text="P", created_at=_T0))
            s.add(AiKeyword(article_id=a.id, term="hiroshima", kind="entity", model="m",
                            prompt_version="v1", confirmed=confirmed, created_at=_T0))
        return f

    _, _, live, _ = _two(tmp_path, add("THEIRS", True), add("OURS", False))
    with _corpus(live)() as s:
        assert s.query(ArticleAnalysis).one().result == "OURS"
        assert s.query(AiKeyword).one().confirmed is False
    got = {t: (f, p) for t, _, f, p, _, _ in _alts(live)}
    assert got["article_analyses"][0] == {"result": "THEIRS"}
    assert got["article_analyses"][1]["prompt_text"] == "P"
    assert got["ai_keyword"][0]["confirmed"] == 1


def test_a_law_summary_that_disagrees_is_kept(tmp_path):
    def add(summary):
        def f(s):
            doc = LawDocument(jurisdiction="uk", title="Act", url="https://example.uk/act")
            s.add(doc)
            s.flush()
            rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash="ch1",
                              full_text="T")
            s.add(rev)
            s.flush()
            s.add(LawRevisionSummary(revision_id=rev.id, summary=summary, model="m",
                                     prompt_version="v1", created_at=_T0))
        return f

    _, _, live, _ = _two(tmp_path, add("THEIRS"), add("OURS"))
    with _corpus(live)() as s:
        assert s.query(LawRevisionSummary).one().summary == "OURS"
    [(table, identity, fields, _, _, _)] = _alts(live)
    assert table == "law_revision_summaries"
    assert identity["document_url"] == "https://example.uk/act"
    assert fields["summary"] == "THEIRS"


def test_the_tag_of_a_local_row_says_local_and_of_an_arrived_row_says_where_from(tmp_path):
    def inc(s):
        a = _article(s)
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result="R", model="m",
                              prompt_version="v1", created_at=_T0))

    def loc(s):
        a = _article(s, "h-local")
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result="L", model="m2",
                              prompt_version="v9", created_at=_T0))

    _, batch, live, _ = _two(tmp_path, inc, loc)
    with _corpus(live)() as s:
        rows = {r.result: r.id for r in s.query(ArticleAnalysis)}
        mine = provenance_tag(s, "article_analyses", rows["L"])
        theirs = provenance_tag(s, "article_analyses", rows["R"])
        assert provenance_tag(s, "article_analyses", 99999) is None
    assert mine["origin"] == "local" and mine["arrived"] is None and mine["producer"] == "m2"
    assert theirs["origin"] == "machine-B" and theirs["arrived"]["batch"] == batch
    assert set(theirs) == {"v", "kind", "producer", "version", "prompt_text", "produced_at",
                           "origin", "arrived"}


def test_every_captured_table_has_a_producer_mapping():
    """A table cannot be captured without saying who produced its values."""
    import re

    from src.backup import merge
    from src.backup.provenance import PRODUCER_COLUMNS

    src = Path(merge.__file__).read_text(encoding="utf-8")
    captured = set(re.findall(r'_capture_alternates\(\s*con, batch_id, "(\w+)"', src))
    assert captured, "found no capture call; the pattern is stale"
    assert captured <= set(PRODUCER_COLUMNS)


def test_a_value_the_corpus_already_holds_in_a_sibling_row_is_no_contradiction(tmp_path):
    """`article_analyses` has no unique constraint and a local pass appends a row per run,
    so an item can have several local rows. The backup's summary equals the SECOND one."""
    def inc(s):
        a = _article(s)
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result="OURS2", model="m",
                              prompt_version="v1", created_at=_T0))

    def loc(s):
        a = _article(s)
        for r in ("OURS1", "OURS2"):
            s.add(ArticleAnalysis(article_id=a.id, kind="summary", result=r, model="m",
                                  prompt_version="v1", created_at=_T0))

    counts, _, live, _ = _two(tmp_path, inc, loc)
    assert _alts(live) == []
    assert counts["article_analyses"]["conflict"] == 0


def test_conflict_and_duplicate_are_disjoint_and_stable_across_a_second_restore(tmp_path):
    def tr(text, term):
        return KeywordTranslation(term=term, source_lang="fr", target_lang="en", text=text,
                                  model=None, prompt_version=None, created_at=_T0)

    def inc(s):
        s.add(tr("THEIRS", "chat"))   # contradicts (NULL model and prompt: the COALESCE key)
        s.add(tr("same", "chien"))    # agrees

    def loc(s):
        s.add(tr("OURS", "chat"))
        s.add(tr("same", "chien"))

    counts, _, live, incoming = _two(tmp_path, inc, loc)
    got = counts["keyword_translations"]
    assert (got["new"], got["duplicate"], got["conflict"]) == (0, 1, 1)
    assert len(_alts(live)) == 1
    again, _ = merge_corpus(incoming, live, _META)
    assert again["keyword_translations"]["conflict"] == 1, "the same contradiction, still reported"
    assert len(_alts(live)) == 1, "...but never recorded twice"


def test_two_incoming_rows_that_collapse_onto_one_item_record_one_alternate(tmp_path):
    """Two incoming articles with different hashes cannot collapse, so drive the same shape
    directly: two incoming translations with the identical contradicting value."""
    def inc(s):
        a = _article(s)
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result="THEIRS", model="m",
                              prompt_version="v1", created_at=_T0))
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result="THEIRS", model="m",
                              prompt_version="v1", created_at=_T0))

    def loc(s):
        a = _article(s)
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result="OURS", model="m",
                              prompt_version="v1", created_at=_T0))

    _, _, live, _ = _two(tmp_path, inc, loc)
    assert len(_alts(live)) == 1


# ----- slice 2: the operator's side (list, keep, discard, adopt) ---------------------------


def _live_with_a_title_difference(tmp_path):
    def add(title):
        def f(s):
            a = _article(s)
            s.add(ArticleTitleTranslation(
                article_id=a.id, source_lang="fr", target_lang="en", title=title, summary="s",
                model="m1", prompt_version="tt-v1", created_at=_T0))
        return f

    _, batch, live, _ = _two(tmp_path, add("Theirs"), add("Ours"))
    return batch, live


def test_the_list_shows_both_values_and_both_tags(tmp_path):
    from src.backup.alternates import list_alternates

    batch, live = _live_with_a_title_difference(tmp_path)
    with _corpus(live)() as s:
        out = list_alternates(s)
    assert out["total"] == 1
    assert out["batches"][0]["id"] == batch and out["batches"][0]["pending"] == 1
    [item] = out["items"]
    assert item["imported"]["title"] == "Theirs" and item["local"]["title"] == "Ours"
    assert item["differing"] == ["title"], "the summary is equal, so it is not marked as differing"
    assert item["imported_provenance"]["origin"] == "machine-B"
    assert item["local_provenance"]["origin"] == "local"
    assert item["article"]["title"] == "T", "the item names its article"


def test_keep_and_discard_never_touch_the_local_row(tmp_path):
    from src.backup.alternates import discard, keep, list_alternates

    batch, live = _live_with_a_title_difference(tmp_path)
    with _corpus(live)() as s:
        alt_id = list_alternates(s)["items"][0]["id"]
        keep(s, alt_id)
        assert list_alternates(s)["total"] == 0
        assert list_alternates(s, status="kept")["total"] == 1
        discard(s, alt_id)
        assert list_alternates(s, status="all")["total"] == 0
        assert s.query(ArticleTitleTranslation).one().title == "Ours"


def test_adopt_swaps_the_values_and_records_where_it_came_from(tmp_path):
    from src.backup.alternates import adopt, list_alternates

    batch, live = _live_with_a_title_difference(tmp_path)
    with _corpus(live)() as s:
        alt_id = list_alternates(s)["items"][0]["id"]
        adopt(s, alt_id)
        row = s.query(ArticleTitleTranslation).one()
        assert row.title == "Theirs"
        [item] = list_alternates(s, status="all")["items"]
        assert item["imported"]["title"] == "Ours", "the replaced value is kept, not lost"
        assert item["status"] == "kept"
        # the row now carries an arrival record for that restore, like one the restore inserted
        tag = provenance_tag(s, "article_title_translations", row.id)
        assert tag["origin"] == "machine-B" and tag["arrived"]["batch"] == batch
        # and adopting again reverses it
        adopt(s, alt_id)
        assert s.query(ArticleTitleTranslation).one().title == "Ours"


def test_adopt_refuses_when_the_local_row_is_gone(tmp_path):
    from src.backup.alternates import AlternateError, adopt, list_alternates

    batch, live = _live_with_a_title_difference(tmp_path)
    with _corpus(live)() as s:
        alt_id = list_alternates(s)["items"][0]["id"]
        s.query(ArticleTitleTranslation).delete()
        s.commit()
        with pytest.raises(AlternateError) as e:
            adopt(s, alt_id)
        assert e.value.status == 409
        with pytest.raises(AlternateError) as e2:
            adopt(s, 99999)
        assert e2.value.status == 404


def test_discarding_a_restore_discards_only_that_restores_alternates(tmp_path):
    from src.backup.alternates import discard_batch, list_alternates

    batch, live = _live_with_a_title_difference(tmp_path)
    with _corpus(live)() as s:
        assert discard_batch(s, batch + 1)["discarded"] == 0
        assert list_alternates(s)["total"] == 1
        assert discard_batch(s, batch)["discarded"] == 1
        assert list_alternates(s, status="all")["total"] == 0


def test_the_routes_exist_and_refuse_an_unknown_id():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/backup/alternates")
        assert r.status_code == 200 and {"total", "batches", "items"} <= set(r.json())
        assert c.get("/api/backup/alternates?status=bogus").status_code == 422
        for verb in ("keep", "discard", "adopt"):
            assert c.post(f"/api/backup/alternates/999999/{verb}").status_code == 404
        assert c.post("/api/backup/alternates/batch/999999/discard").json()["discarded"] == 0
