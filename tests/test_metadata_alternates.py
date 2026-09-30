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
    MergeBatch,
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


# ----- slice 2: the operator's side (list, keep, discard) ---------------------------


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


def test_there_is_no_way_to_make_an_imported_value_the_shown_one(tmp_path):
    """The maintainer's rule: imported data never prevails. No action swaps a value in."""
    import src.backup.alternates as alt

    assert not hasattr(alt, "adopt")
    from src.api import backup_v2

    paths = {getattr(r, "path", "") for r in backup_v2.router.routes}
    assert not any(p.endswith("/adopt") for p in paths)


def test_the_local_side_is_found_by_identity_and_is_the_newest_row(tmp_path):
    """Two local rows share one identity (no unique constraint on analyses): the panel shows
    the one the readers show (the newest), never the oldest."""
    from src.backup.alternates import list_alternates

    def add(result, *more):
        def f(s):
            a = _article(s)
            for r in (result, *more):
                s.add(ArticleAnalysis(
                    article_id=a.id, kind="summary", model="m1", prompt_version="v1",
                    result=r, created_at=_T0))
        return f

    _, batch, live, _ = _two(tmp_path, add("THEIRS"), add("old local", "new local"))
    with _corpus(live)() as s:
        [item] = list_alternates(s)["items"]
    assert item["local"]["result"] == "new local"


def test_a_reused_row_id_never_shows_an_unrelated_row_as_the_local_side(tmp_path):
    """SQLite reuses the highest integer key after a delete: the stored local_row_id can then
    name a row of ANOTHER article. The panel resolves by identity and says the row is gone."""
    from src.backup.alternates import list_alternates

    batch, live = _live_with_a_title_difference(tmp_path)
    with _corpus(live)() as s:
        s.query(ArticleTitleTranslation).delete()
        other = _article(s, hash_="h2")
        s.add(ArticleTitleTranslation(
            article_id=other.id, source_lang="fr", target_lang="de", title="UNRELATED",
            summary="s", model="m1", prompt_version="tt-v1", created_at=_T0))
        s.commit()
        [item] = list_alternates(s)["items"]
    assert item["local"] is None, "an unrelated row that inherited the id is not the local side"


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
        for verb in ("keep", "discard"):
            assert c.post(f"/api/backup/alternates/999999/{verb}").status_code == 404
        assert c.post("/api/backup/alternates/batch/999999/discard").json()["discarded"] == 0


def _all_six(which):
    """One article and one law revision holding every kind of deduced item, valued by ``which``."""
    def f(s):
        a = _article(s)
        s.add(KeywordTranslation(term="chat", source_lang="fr", target_lang="en", text=which,
                                 model="m1", prompt_version="v1", created_at=_T0))
        s.add(ArticleTitleTranslation(article_id=a.id, source_lang="fr", target_lang="en",
                                      title=which, summary="s", model="m1",
                                      prompt_version="tt-v1", created_at=_T0))
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result=which, model="m1",
                              prompt_version="v1", created_at=_T0))
        s.add(AiKeyword(article_id=a.id, term="hiroshima", kind="entity", model="m1",
                        prompt_version="v1", confirmed=(which == "THEIRS"), created_at=_T0))
        s.add(ArticleMentionedDate(
            article_id=a.id, mentioned_on=date(1945, 8, 6), precision="day", snippet="x",
            confidence=0.9, extractor="dateextract",
            status="confirmed" if which == "THEIRS" else "candidate", created_at=_T0))
        doc = LawDocument(jurisdiction="uk", title="Act", url="https://example.uk/act")
        s.add(doc)
        s.flush()
        rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash="ch1", full_text="T")
        s.add(rev)
        s.flush()
        s.add(LawRevisionSummary(revision_id=rev.id, summary=which, model="m1",
                                 prompt_version="v1", created_at=_T0))
    return f


def test_the_identity_the_capture_writes_is_exactly_what_the_resolver_reads(tmp_path):
    """ALTERNATE_SPECS and the six capture calls in merge.py are two definitions of one thing;
    this pins them together, table by table, and proves every item resolves to its local row."""
    from src.backup.alternates import list_alternates
    from src.backup.provenance import ALTERNATE_SPECS, PRODUCER_COLUMNS

    _, _, live, _ = _two(tmp_path, _all_six("THEIRS"), _all_six("OURS"))
    scope_keys = {
        "article": {"article_hash"}, "none": set(),
        "law": {"jurisdiction", "document_url", "revision_content_hash"},
    }
    assert set(ALTERNATE_SPECS) == set(PRODUCER_COLUMNS)
    seen = set()
    for table, identity, _, _, _, _ in _alts(live):
        spec = ALTERNATE_SPECS[table]
        assert set(identity) == scope_keys[spec["scope"]] | set(spec["match"]), table
        seen.add(table)
    assert seen == set(ALTERNATE_SPECS), "every table records an alternate on a contradiction"
    with _corpus(live)() as s:
        items = list_alternates(s)["items"]
    assert {i["table"] for i in items} == set(ALTERNATE_SPECS)
    for i in items:
        assert i["local"] is not None, f"{i['table']}: the local row was not found by identity"
        assert i["local_provenance"]["origin"] == "local"


def test_the_same_law_url_in_two_jurisdictions_is_two_items(tmp_path):
    from src.backup.alternates import list_alternates

    def add(uk, eu):
        def f(s):
            for juris, summary in (("uk", uk), ("eu", eu)):
                doc = LawDocument(jurisdiction=juris, title="Act", url="https://example.org/act")
                s.add(doc)
                s.flush()
                rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash="ch1",
                                  full_text="T")
                s.add(rev)
                s.flush()
                s.add(LawRevisionSummary(revision_id=rev.id, summary=summary, model="m1",
                                         prompt_version="v1", created_at=_T0))
        return f

    _, _, live, _ = _two(tmp_path, add("UK-THEIRS", "EU-THEIRS"), add("UK-OURS", "EU-OURS"))
    with _corpus(live)() as s:
        items = {i["identity"]["jurisdiction"]: i for i in list_alternates(s)["items"]}
    assert set(items) == {"uk", "eu"}, "one alternate per document, not one for both"
    assert items["uk"]["local"]["summary"] == "UK-OURS"
    assert items["eu"]["local"]["summary"] == "EU-OURS"


def test_a_law_alternate_recorded_before_jurisdiction_joined_the_identity_still_finds_its_row(tmp_path):
    from src.backup.alternates import list_alternates

    def add(summary):
        def f(s):
            doc = LawDocument(jurisdiction="uk", title="Act", url="https://example.uk/act")
            s.add(doc)
            s.flush()
            rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash="ch1", full_text="T")
            s.add(rev)
            s.flush()
            s.add(LawRevisionSummary(revision_id=rev.id, summary=summary, model="m1",
                                     prompt_version="v1", created_at=_T0))
        return f

    _, _, live, _ = _two(tmp_path, add("THEIRS"), add("OURS"))
    with _corpus(live)() as s:
        alt = s.query(MetadataAlternate).one()
        ident = json.loads(alt.identity)
        del ident["jurisdiction"]
        alt.identity = json.dumps(ident)
        s.commit()
        [item] = list_alternates(s)["items"]
    assert item["local"]["summary"] == "OURS", "an old identity is not 'the row is gone'"


def test_the_list_pages_by_offset_without_repeating_or_skipping(tmp_path):
    from src.backup.alternates import list_alternates

    def inc(s):
        for n in range(7):
            s.add(KeywordTranslation(term=f"t{n}", source_lang="fr", target_lang="en",
                                     text=f"in{n}", model="m1", prompt_version="v1", created_at=_T0))

    def loc(s):
        for n in range(7):
            s.add(KeywordTranslation(term=f"t{n}", source_lang="fr", target_lang="en",
                                     text=f"loc{n}", model="m1", prompt_version="v1", created_at=_T0))

    _, _, live, _ = _two(tmp_path, inc, loc)
    with _corpus(live)() as s:
        first = list_alternates(s, limit=3, offset=0)
        second = list_alternates(s, limit=3, offset=3)
        third = list_alternates(s, limit=3, offset=6)
    ids = [i["id"] for r in (first, second, third) for i in r["items"]]
    assert first["total"] == 7 and len(ids) == 7 and len(set(ids)) == 7


# ----- slice 3: the differences travel with the backup ---------------------------------------


def _meta(origin):
    return {**_META, "origin_fingerprint": origin}


def _tr(text):
    return lambda s: s.add(KeywordTranslation(
        term="chat", source_lang="fr", target_lang="en", text=text, model="m1",
        prompt_version="v1", created_at=_T0))


def _chain(tmp_path):
    """A's value reaches B (kept beside B's own); then B's file is restored on C."""
    a, b, c = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "c.db"
    for path, text in ((a, "FROM-A"), (b, "FROM-B"), (c, "FROM-C")):
        with _corpus(path)() as s:
            _tr(text)(s)
            s.commit()
    merge_corpus(a, b, _meta("machine-A"))
    counts, batch = merge_corpus(b, c, _meta("machine-B"))
    return counts, batch, c, b


def test_an_alternate_a_backup_carries_reaches_the_next_machine(tmp_path):
    counts, batch, c, _ = _chain(tmp_path)
    with _corpus(c)() as s:
        assert s.query(KeywordTranslation).one().text == "FROM-C"
    got = {a[2]["text"]: a for a in _alts(c)}
    assert set(got) == {"FROM-B", "FROM-A"}, "B's own value AND the one A left beside it"
    assert got["FROM-B"][5] == "machine-B"
    assert got["FROM-A"][5] == "machine-A", "the origin the exporter recorded is kept, not rewritten"
    tag = got["FROM-A"][3]
    assert tag["origin"] == "machine-B", "the immediate backup is the arrival, as for every row"
    assert tag["carried"]["origin"] == "machine-A", "what the exporter recorded rides beside it"
    with _corpus(c)() as s:
        batch = s.get(MergeBatch, tag["arrived"]["batch"])
        assert batch.origin_fingerprint == "machine-B", "the batch id is one of THIS corpus's"
    assert counts["metadata_alternates"]["new"] == 1


def test_restoring_the_same_carrying_backup_again_adds_nothing(tmp_path):
    _, _, c, b = _chain(tmp_path)
    again, _ = merge_corpus(b, c, _meta("machine-B"))
    assert len(_alts(c)) == 2
    assert again["metadata_alternates"]["new"] == 0 and again["metadata_alternates"]["duplicate"] == 1


def test_a_carried_alternate_whose_value_the_corpus_already_holds_is_no_difference(tmp_path):
    a, b, c = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "c.db"
    for path, text in ((a, "SAME"), (b, "FROM-B"), (c, "SAME")):
        with _corpus(path)() as s:
            _tr(text)(s)
            s.commit()
    merge_corpus(a, b, _meta("machine-A"))
    merge_corpus(b, c, _meta("machine-B"))
    assert [x[2]["text"] for x in _alts(c)] == ["FROM-B"], "C already has A's value; only B's differs"


def test_an_alternate_with_no_home_here_is_counted_not_invented(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(inc)() as s:
        a = _article(s, "only-there")
        s.add(ArticleAnalysis(article_id=a.id, kind="summary", result="X", model="m",
                              prompt_version="v", created_at=_T0))
        s.add(MetadataAlternate(
            batch_id=1, table_name="article_analyses",
            identity=json.dumps({"article_hash": "not-in-live", "kind": "summary", "model": "m",
                                 "prompt_version": "v"}),
            local_row_id=1, fields=json.dumps({"result": "Y"}),
            provenance=json.dumps({"v": 1}), origin="machine-Z", status="pending"))
        s.commit()
    with _corpus(live)() as s:
        s.commit()
    from src.database.models import MergeBatch  # noqa: F401  (the FK target exists in create_all)
    counts, _ = merge_corpus(inc, live, _meta("machine-Z"))
    assert counts["metadata_alternates"]["deferred"] == 1
    assert _alts(live) == []


def test_the_capture_specs_agree_with_what_is_stored():
    """One definition drives the capture and the carry: `shown` covers `differs` and the scope is
    one the carry understands. (The identity keys a capture writes are pinned against the
    resolver by test_the_identity_the_capture_writes_is_exactly_what_the_resolver_reads.)"""
    from src.backup.provenance import ALTERNATE_SPECS

    for table, spec in ALTERNATE_SPECS.items():
        assert set(spec["differs"]) <= set(spec["shown"]), table
        assert spec["scope"] in ("article", "law", "none"), table


def test_every_table_re_attaches_by_its_own_identity_across_two_hops(tmp_path):
    """The identity a capture stores must be exactly what the carry needs to find the row again:
    run all six tables through A -> B -> C and check each one's alternate lands on C."""
    def populate(tag, ident):
        def f(s):
            a = _article(s)
            s.add(ArticleAnalysis(article_id=a.id, kind="summary", result=f"R-{tag}", model="m",
                                  prompt_version="v1", created_at=_T0))
            s.add(AiKeyword(article_id=a.id, term="t", kind="entity", model="m",
                            prompt_version="v1", confirmed=(tag == "A"), created_at=_T0))
            s.add(ArticleMentionedDate(article_id=a.id, mentioned_on=date(2001, 9, 11),
                                       precision="day", snippet="s", confidence=0.5,
                                       extractor="x", status="confirmed" if tag == "A" else "candidate",
                                       created_at=_T0))
            s.add(ArticleTitleTranslation(article_id=a.id, source_lang="fr", target_lang="en",
                                          title=f"T-{tag}", summary="s", model="m",
                                          prompt_version="v1", created_at=_T0))
            s.add(KeywordTranslation(term="chat", source_lang="fr", target_lang="en",
                                     text=f"K-{tag}", model="m", prompt_version="v1", created_at=_T0))
            doc = LawDocument(jurisdiction="uk", title="Act", url="https://example.uk/act")
            s.add(doc)
            s.flush()
            rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash="ch1", full_text="T")
            s.add(rev)
            s.flush()
            s.add(LawRevisionSummary(revision_id=rev.id, summary=f"L-{tag}", model="m",
                                     prompt_version="v1", created_at=_T0))
        return f

    paths = {k: tmp_path / f"{k}.db" for k in "ABC"}
    for k, path in paths.items():
        with _corpus(path)() as s:
            populate(k, k)(s)
            s.commit()
    merge_corpus(paths["A"], paths["B"], _meta("machine-A"))
    merge_corpus(paths["B"], paths["C"], _meta("machine-B"))
    from src.backup.provenance import ALTERNATE_SPECS

    tables = {a[0] for a in _alts(paths["C"])}
    assert tables == set(ALTERNATE_SPECS), sorted(set(ALTERNATE_SPECS) - tables)
    from_a = {a[0] for a in _alts(paths["C"]) if a[5] == "machine-A"}
    assert from_a == set(ALTERNATE_SPECS), "A's value reached C through B for every table"


def _restored_with(tmp_path, alternates):
    """C restores a backup whose alternates table holds exactly ``alternates`` (each a dict of
    MetadataAlternate columns); returns the merge counts and C's path."""
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(inc)() as s:
        _tr("FROM-B")(s)
        for a in alternates:
            s.add(MetadataAlternate(batch_id=1, local_row_id=1, origin="machine-Z",
                                    status="pending", **a))
        s.commit()
    with _corpus(live)() as s:
        _tr("FROM-C")(s)
        s.commit()
    counts, _ = merge_corpus(inc, live, _meta("machine-B"))
    return counts, live


def test_a_malformed_incoming_alternate_is_counted_and_never_fails_the_restore(tmp_path):
    good_id = json.dumps({"term": "chat", "source_lang": "fr", "target_lang": "en", "model": "m1",
                          "prompt_version": "v1"})
    base = {"table_name": "keyword_translations", "identity": good_id,
            "fields": json.dumps({"text": "X"}), "provenance": json.dumps({"v": 1})}
    counts, live = _restored_with(tmp_path, [
        {**base, "identity": "[]"},                                  # not an object
        {**base, "fields": json.dumps({"text": {"x": 1}})},          # a value that cannot bind
        {**base, "provenance": "not json"},                          # unreadable tag
        {**base, "provenance": "[1]"},                               # a tag that is not an object
        {**base, "table_name": "no_such_table"},                     # an unknown table
        {**base, "fields": json.dumps({"text": "GOOD"})},            # the one sound row
    ])
    r = counts["metadata_alternates"]
    assert (r["new"], r["deferred"]) == (1, 5)
    # FROM-B is the restore's own capture (its translation contradicts C's); GOOD is the carry.
    assert sorted(a[2]["text"] for a in _alts(live)) == ["FROM-B", "GOOD"]
    from src.backup.alternates import list_alternates

    with _corpus(live)() as s:
        assert len(list_alternates(s)["items"]) == 2, "the list still renders"


def test_a_carried_law_alternate_without_a_jurisdiction_still_finds_its_row(tmp_path):
    def add(summary):
        def f(s):
            doc = LawDocument(jurisdiction="uk", title="Act", url="https://example.uk/act")
            s.add(doc)
            s.flush()
            rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash="ch1", full_text="T")
            s.add(rev)
            s.flush()
            s.add(LawRevisionSummary(revision_id=rev.id, summary=summary, model="m1",
                                     prompt_version="v1", created_at=_T0))
        return f

    a, b, c = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "c.db"
    for path, text in ((a, "L-A"), (b, "L-B"), (c, "L-C")):
        with _corpus(path)() as s:
            add(text)(s)
            s.commit()
    merge_corpus(a, b, _meta("machine-A"))
    with _corpus(b)() as s:
        alt = s.query(MetadataAlternate).one()
        ident = json.loads(alt.identity)
        del ident["jurisdiction"]          # as an alternate recorded before that key existed
        alt.identity = json.dumps(ident)
        s.commit()
    counts, _ = merge_corpus(b, c, _meta("machine-B"))
    assert counts["metadata_alternates"]["new"] == 1 and counts["metadata_alternates"].get("deferred", 0) == 0


def test_an_item_and_its_alternate_arriving_in_one_restore_are_both_kept(tmp_path):
    """C lacks the item entirely: the row is inserted and the alternate attaches to it, which
    holds only because the carry runs after every table's rows are in."""
    a, b, c = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "c.db"
    for path, text in ((a, "FROM-A"), (b, "FROM-B")):
        with _corpus(path)() as s:
            _tr(text)(s)
            s.commit()
    with _corpus(c)() as s:
        s.commit()
    merge_corpus(a, b, _meta("machine-A"))
    counts, _ = merge_corpus(b, c, _meta("machine-B"))
    assert counts["metadata_alternates"]["new"] == 1
    with _corpus(c)() as s:
        assert s.query(KeywordTranslation).one().text == "FROM-B"


def test_a_kept_alternate_arrives_pending_and_a_discarded_one_returns_on_a_re_restore(tmp_path):
    _, _, c, b = _chain(tmp_path)
    with _corpus(b)() as s:
        s.query(MetadataAlternate).update({"status": "kept"})
        s.commit()
    with _corpus(c)() as s:
        s.query(MetadataAlternate).delete()
        s.commit()
    merge_corpus(b, c, _meta("machine-B"))
    got = _alts(c)
    assert got and all(a[4] == "pending" for a in got), "what one machine kept is new to the next"
