"""R61 (item 12): the operator may show a restore's value instead -- reversibly, never by itself.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's rulings: a restore never changes what is shown (both values are kept); 2026-09-30
"bring it back, give users the choice" -- so the choice to show the restore's value exists, is
the operator's explicit act, and loses nothing: the row and the alternate trade places, each with
its own provenance tag, and swapping again puts everything back. Every test merges into a
DIFFERENT corpus (a self-restore sees only duplicates).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.alternates import (  # noqa: E402
    AlternateError,
    discard,
    discard_batch,
    keep,
    list_alternates,
    swap,
)
from src.backup.merge import merge_corpus  # noqa: E402
from src.backup.provenance import provenance_tag  # noqa: E402
from src.database.models import (  # noqa: E402
    Article,
    ArticleAnalysis,
    Base,
    KeywordTranslation,
    MetadataAlternate,
    Place,
    Source,
)

_META = {
    "artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}
_T0 = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)
_T1 = _T0 + timedelta(days=9)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _two(tmp_path, incoming, local, meta=_META):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(inc)() as s:
        incoming(s)
        s.commit()
    with _corpus(live)() as s:
        local(s)
        s.commit()
    counts, batch = merge_corpus(inc, live, meta)
    return counts, batch, live


def _tr(value, at=_T0):
    return lambda s: s.add(KeywordTranslation(
        term="chat", source_lang="fr", target_lang="en", text=value, model="m1",
        prompt_version="v1", created_at=at))


def _one(s, table="metadata_alternates"):
    return s.query(MetadataAlternate).one()


def _row(s):
    return s.query(KeywordTranslation).one()


def test_a_swap_shows_the_restores_value_and_keeps_the_old_one_beside_it(tmp_path):
    _, batch, live = _two(tmp_path, _tr("THEIRS", _T1), _tr("OURS", _T0))
    with _corpus(live)() as s:
        alt = _one(s)
        assert swap(s, alt.id)["status"] == "swapped"
        row = _row(s)
        assert row.text == "THEIRS" and row.created_at == _T1, "the value and its producer stamp move together"
        tag = provenance_tag(s, "keyword_translations", row.id)
        assert tag["origin"] == "machine-B" and tag["arrived"]["batch"] == batch
        assert tag["produced_at"].startswith("2026-09-10"), "the tag reads the row it now describes"
        alt = _one(s)
        assert json.loads(alt.fields) == {"text": "OURS"}
        assert json.loads(alt.provenance)["origin"] == "local", "the kept value says it was made here"
        [item] = list_alternates(s)["items"]
        assert item["swapped"] and item["local"]["text"] == "THEIRS" and item["imported"]["text"] == "OURS"


def test_swapping_again_puts_every_bit_back(tmp_path):
    _, _, live = _two(tmp_path, _tr("THEIRS", _T1), _tr("OURS", _T0))
    with _corpus(live)() as s:
        before = (_row(s).text, _row(s).created_at, provenance_tag(s, "keyword_translations", _row(s).id))
        alt_id = _one(s).id
        alt_before = (_one(s).fields, json.loads(_one(s).provenance)["origin"])
        swap(s, alt_id)
        assert swap(s, alt_id)["status"] == "pending"
        after = (_row(s).text, _row(s).created_at, provenance_tag(s, "keyword_translations", _row(s).id))
        assert after == before
        assert s.execute(text("SELECT COUNT(*) FROM merged_rows WHERE table_name = 'keyword_translations'")).scalar() == 0
        assert (_one(s).fields, json.loads(_one(s).provenance)["origin"]) == alt_before


def test_a_restore_alone_never_swaps_and_the_swapped_alternate_is_protected(tmp_path):
    _, batch, live = _two(tmp_path, _tr("THEIRS"), _tr("OURS"))
    with _corpus(live)() as s:
        assert _row(s).text == "OURS", "the restore itself changes nothing that is shown"
        alt_id = _one(s).id
        swap(s, alt_id)
        with pytest.raises(AlternateError) as e:
            keep(s, alt_id)
        assert e.value.status == 409
        with pytest.raises(AlternateError) as e:
            discard(s, alt_id)
        assert e.value.status == 409, "a single discard of the only copy needs an explicit confirm"
        out = discard_batch(s, batch)
        assert out["discarded"] == 0 and out["left_swapped"] == 1
        assert s.query(MetadataAlternate).count() == 1
        discard(s, alt_id, confirm=True)
        assert s.query(MetadataAlternate).count() == 0 and _row(s).text == "THEIRS"


def test_a_swap_with_a_missing_local_row_changes_nothing(tmp_path):
    _, _, live = _two(tmp_path, _tr("THEIRS"), _tr("OURS"))
    with _corpus(live)() as s:
        alt_id = _one(s).id
        s.execute(text("DELETE FROM keyword_translations"))
        s.commit()
        with pytest.raises(AlternateError) as e:
            swap(s, alt_id)
        assert e.value.status == 409
        assert _one(s).status == "pending"


def test_a_stored_difference_that_is_not_well_formed_is_refused_and_writes_nothing(tmp_path):
    _, _, live = _two(tmp_path, _tr("THEIRS"), _tr("OURS"))
    with _corpus(live)() as s:
        alt = _one(s)
        alt.fields = json.dumps({"text": {"nested": 1}})
        s.commit()
        with pytest.raises(AlternateError) as e:
            swap(s, alt.id)
        assert e.value.status == 400 and _row(s).text == "OURS"


def test_only_the_tables_own_shown_columns_are_ever_written(tmp_path):
    """The stored JSON came from a backup file: a key that is not one of the table's shown
    columns (here the identity's own ``model``, and a made-up column) is ignored, never written."""
    _, _, live = _two(tmp_path, _tr("THEIRS"), _tr("OURS"))
    with _corpus(live)() as s:
        alt = _one(s)
        alt.fields = json.dumps({"text": "THEIRS", "model": "EVIL", "no_such_column": "x"})
        s.commit()
        swap(s, alt.id)
        row = _row(s)
        assert row.text == "THEIRS" and row.model == "m1"


def test_the_swap_carries_the_prompt_text_too(tmp_path):
    def add(result, prompt, at):
        def f(s):
            src = Source(name="S", domain="s.example")
            s.add(src)
            s.flush()
            a = Article(url="https://s.example/1", canonical_url="https://s.example/1",
                        source_id=src.id, title="T", content="c", hash="h1")
            s.add(a)
            s.flush()
            s.add(ArticleAnalysis(article_id=a.id, kind="summary", result=result, model="m",
                                  prompt_version="v", prompt_text=prompt, created_at=at))
        return f

    _, _, live = _two(tmp_path, add("THEIRS", "their prompt", _T1), add("OURS", "our prompt", _T0))
    with _corpus(live)() as s:
        swap(s, _one(s).id)
        a = s.query(ArticleAnalysis).one()
        assert (a.result, a.prompt_text, a.created_at) == ("THEIRS", "their prompt", _T1)
        assert provenance_tag(s, "article_analyses", a.id)["prompt_text"] == "their prompt"


def _place(pid, name, at):
    return lambda s: s.add(Place(
        id=pid, qid="Q90", kind="city", name=name, names_json="{}", country="fr", country_alpha3="FRA",
        admin_path_json="[]", geometry_ref=f"osm.db:{pid}", lat=48.0, lon=2.0, population=1,
        gazetteer_vintage="2026-09", as_of=at))


def test_a_text_keyed_row_swaps_by_its_key_and_survives_a_vacuum(tmp_path):
    def local(s):
        _place("node/1", "Gone", _T0)(s)
        _place("node/2", "Ours", _T0)(s)

    _, batch, live = _two(tmp_path, _place("node/2", "Theirs", _T1), local)
    with _corpus(live)() as s:
        swap(s, _one(s).id)
        assert s.get(Place, "node/2").name == "Theirs"
        s.execute(text("DELETE FROM places WHERE id = 'node/1'"))   # opens a gap so VACUUM renumbers
        s.commit()
    raw = create_engine(f"sqlite:///{live}", future=True)
    with raw.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("VACUUM"))
    with _corpus(live)() as s:
        rid = s.execute(text("SELECT rowid FROM places WHERE id = 'node/2'")).scalar()
        tag = provenance_tag(s, "places", rid)
        assert tag["arrived"]["batch"] == batch, "the arrival is found by the row's key, not its old rowid"
        # and it is still swappable, by identity, after the renumbering
        swap(s, _one(s).id)
        assert s.get(Place, "node/2").name == "Ours"
        assert provenance_tag(s, "places", rid)["arrived"] is None


def test_the_routes(tmp_path):
    from fastapi.testclient import TestClient

    from src.api import backup_v2
    from src.api.main import app

    paths = {getattr(r, "path", "") for r in backup_v2.router.routes}
    assert "/api/backup/alternates/{alt_id}/swap" in paths or any(p.endswith("/{alt_id}/swap") for p in paths)
    with TestClient(app) as c:
        assert c.post("/api/backup/alternates/999999/swap").status_code == 404


def test_re_restoring_the_same_backup_after_a_swap_records_nothing_new(tmp_path):
    counts, batch, live = _two(tmp_path, _tr("THEIRS"), _tr("OURS"))
    with _corpus(live)() as s:
        alt_id = _one(s).id
        swap(s, alt_id)
        swap(s, alt_id)     # back to the original state: the restore's value waits again
        assert s.query(MetadataAlternate).count() == 1
    merge_corpus(tmp_path / "inc.db", live, _META)
    with _corpus(live)() as s:
        assert s.query(MetadataAlternate).count() == 1, "byte-identical fields, so the capture sees it"


def test_every_deduced_table_swaps_and_swaps_back_exactly(tmp_path):
    from datetime import date

    from src.database.models import (
        AiKeyword,
        ArticleMentionedDate,
        ArticleTitleTranslation,
        LawDocument,
        LawRevision,
        LawRevisionSummary,
    )

    def populate(tag, at):
        def f(s):
            src = Source(name="S", domain="s.example")
            s.add(src)
            s.flush()
            a = Article(url="https://s.example/1", canonical_url="https://s.example/1",
                        source_id=src.id, title="T", content="c", hash="h1")
            s.add(a)
            s.flush()
            s.add(ArticleAnalysis(article_id=a.id, kind="summary", result=f"R-{tag}", model="m",
                                  prompt_version="v1", prompt_text=f"P-{tag}", created_at=at))
            s.add(AiKeyword(article_id=a.id, term="t", kind="entity", model="m", prompt_version="v1",
                            confirmed=(tag == "A"), evidence=f"E-{tag}", created_at=at))
            s.add(ArticleMentionedDate(article_id=a.id, mentioned_on=date(2001, 9, 11), precision="day",
                                       snippet=f"S-{tag}", confidence=0.5, extractor=f"x-{tag}",
                                       status="confirmed" if tag == "A" else "candidate", created_at=at))
            s.add(ArticleTitleTranslation(article_id=a.id, source_lang="fr", target_lang="en",
                                          title=f"T-{tag}", summary="s", model="m", prompt_version="v1",
                                          created_at=at))
            s.add(KeywordTranslation(term="chat", source_lang="fr", target_lang="en", text=f"K-{tag}",
                                     model="m", prompt_version="v1", created_at=at))
            doc = LawDocument(jurisdiction="uk", title="Act", url="https://example.uk/act")
            s.add(doc)
            s.flush()
            rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash="ch1", full_text="T")
            s.add(rev)
            s.flush()
            s.add(LawRevisionSummary(revision_id=rev.id, summary=f"L-{tag}", model="m",
                                     prompt_version="v1", prompt_text=f"LP-{tag}", created_at=at))
        return f

    _, _, live = _two(tmp_path, populate("A", _T1), populate("B", _T0))
    tables = ["article_analyses", "ai_keyword", "article_mentioned_dates",
              "article_title_translations", "keyword_translations", "law_revision_summaries"]

    def dump(s):
        out = {}
        for t in tables:
            out[t] = [tuple(r) for r in s.execute(text(f"SELECT * FROM {t} ORDER BY id"))]  # noqa: S608
        out["m"] = [tuple(r) for r in s.execute(text("SELECT * FROM merged_rows ORDER BY 1, 2, 3"))]
        return out

    with _corpus(live)() as s:
        before = dump(s)
        alts = s.query(MetadataAlternate).order_by(MetadataAlternate.id).all()
        assert {a.table_name for a in alts} == set(tables)
        ids = [a.id for a in alts]
        for i in ids:
            assert swap(s, i)["status"] == "swapped"
        during = dump(s)
        assert all(during[t] != before[t] for t in tables), "every table's shown row changed"
        for i in ids:
            assert swap(s, i)["status"] == "pending"
        assert dump(s) == before
