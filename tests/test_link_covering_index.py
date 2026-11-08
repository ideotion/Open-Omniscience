"""The links' covering index ``idx_article_link_article_url (article_id, normalized_url)`` (R455, R611).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``convergence._shared_origin`` groups the links of a few hundred article ids by ``normalized_url``. Without this index the
plan seeks each id and reads the whole link row (two String(1000) columns, a page decrypt each under SQLCipher); the
2026-11-07 field bundle measured 32-55 s a statement (F2/F8). What is pinned here, against REAL SQLite stores:

  * the plan: the ``_shared_origin`` statement the code emits is answered from this index alone, and its answer is the
    same with and without it (only the cost changes);
  * where it is declared: the model, the self-heal entry (DEFERRED, so ``init_db`` never builds it: a sort of every
    link's url holds the write lock), and the migration, chained on b3d8f1a6c4e2, are the same statement;
  * the start-up step builds it after the article list's two, with its own words, and measures it on its own: links
    refused for memory or room do not hold the article indexes back, and the job ends declined in the links' words;
  * the four new frames are keys in every locale, translated, with their placeholders.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from src.analytics.convergence import _shared_origin
from src.database import article_indexes as ai
from src.database import damage
from src.database.damage import DamageRegistry
from src.database.maintenance import DEFERRED_INDEXES, HOT_INDEXES, ensure_hot_indexes
from src.database.models import Article, ArticleLink, Base, Source
from src.jobs.background import Framed

ROOT = Path(__file__).resolve().parents[1]
LINK = "idx_article_link_article_url"
LANG = "idx_article_language_published"
TITLE = "idx_article_title_nocase"


def _store(
    tmp_path: Path, *, drop: tuple[str, ...] = (LINK,), articles: int = 60, links_per: int = 6
):
    """A real store from the models with ``articles`` articles of ``links_per`` links each (every third url shared by
    several articles), then with ``drop`` dropped: the state of a store made before the index existed."""
    eng = create_engine(f"sqlite:///{tmp_path / 'corpus.db'}")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    with S() as s:
        s.add(Source(name="s", domain="example.org"))
        s.flush()
        src_id = s.execute(select(Source.id)).scalar_one()
        for i in range(articles):
            a = Article(
                url=f"https://example.org/{i}",
                canonical_url=f"https://example.org/{i}",
                source_id=src_id,
                content="x" * 50,
                hash=f"h{i}",
                title=f"t{i}",
                language="en",
            )
            s.add(a)
            s.flush()
            for j in range(links_per):
                u = f"https://origin.example/{j}" if j % 3 == 0 else f"https://own.example/{i}/{j}"
                s.add(ArticleLink(article_id=a.id, url=u + "?x=1", normalized_url=u, position=j))
        s.commit()
    with eng.begin() as c:
        for n in drop:
            c.execute(text(f"DROP INDEX IF EXISTS {n}"))
    return eng


def _names(eng) -> set[str]:
    with eng.connect() as c:
        return {r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}


class _Ctx:
    stopping = False

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def set_progress(self, **kw):
        self.calls.append(kw)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    ai._reset_for_tests()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(ai, "_available_ram_bytes", lambda: 8 * 1024**3)
    monkeypatch.setattr(
        damage, "registry", DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    )
    monkeypatch.delenv("OO_ARTICLE_INDEXES", raising=False)
    yield


def _shared_origin_sql(eng, ids: list[int]) -> tuple[str, list[str]]:
    """The statement ``_shared_origin`` sends, captured from the engine, and its EXPLAIN QUERY PLAN."""
    from sqlalchemy import event

    seen: list[tuple[str, object]] = []

    def _look(conn, cursor, statement, parameters, context, executemany):
        if "article_links" in statement and "GROUP BY" in statement:
            seen.append((statement, parameters))

    event.listen(eng, "before_cursor_execute", _look)
    try:
        with sessionmaker(bind=eng)() as s:
            _shared_origin(s, ids)
    finally:
        event.remove(eng, "before_cursor_execute", _look)
    assert len(seen) == 1, "one scan of the id set (#1770)"
    statement, params = seen[0]
    with eng.connect() as c:
        plan = [r[3] for r in c.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, params)]
    return statement, plan


def test_the_shared_origin_statement_is_answered_from_the_index_alone(tmp_path):
    eng = _store(tmp_path, drop=())
    ids = list(range(1, 41))
    _sql, plan = _shared_origin_sql(eng, ids)
    assert any(f"USING COVERING INDEX {LINK}" in p for p in plan), plan


def test_without_it_the_plan_reads_the_rows_and_the_answer_is_the_same(tmp_path):
    eng = _store(tmp_path, drop=())
    ids = list(range(1, 41))
    with sessionmaker(bind=eng)() as s:
        with_index = _shared_origin(s, ids)
    with eng.begin() as c:
        c.execute(text(f"DROP INDEX {LINK}"))
    _sql, plan = _shared_origin_sql(eng, ids)
    assert not any("COVERING INDEX" in p for p in plan), (
        "the assertion above would otherwise prove nothing"
    )
    with sessionmaker(bind=eng)() as s:
        assert _shared_origin(s, ids) == with_index, "an index changes the cost, never the answer"
    assert with_index[0] == 2 and len(with_index[1]) == 2, with_index


def test_the_model_the_deferred_self_heal_and_the_migration_are_one_statement():
    assert LINK in {ix.name for ix in ArticleLink.__table__.indexes}, (
        "a self-heal entry the model lacks reads as drift"
    )
    assert (
        LINK in DEFERRED_INDEXES
        and ai.LINK_NAMES == (LINK,)
        and ai.ALL_NAMES == (LANG, TITLE, LINK)
    )
    assert HOT_INDEXES[LINK] == (
        "CREATE INDEX IF NOT EXISTS idx_article_link_article_url ON article_links (article_id, normalized_url)"
    )
    import importlib.util

    path = next((ROOT / "migrations" / "versions").glob("a7c3e5f19b20_*.py"))
    spec = importlib.util.spec_from_file_location("mig_a7c3e5f19b20", path)
    assert spec and spec.loader
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == "a7c3e5f19b20" and mig.down_revision == "b3d8f1a6c4e2"
    body = path.read_text(encoding="utf-8")
    assert "CREATE INDEX IF NOT EXISTS idx_article_link_article_url" in body
    assert " ON article_links (article_id, normalized_url)" in body
    assert "DROP INDEX IF EXISTS idx_article_link_article_url" in body


def test_init_db_leaves_it_to_the_start_up_step(tmp_path):
    eng = _store(tmp_path)
    created = ensure_hot_indexes(eng, include_deferred=False)
    assert LINK not in created and LINK not in _names(eng), (
        "never inside the call that opens the database"
    )


def test_the_start_up_step_builds_it_with_its_own_words(tmp_path):
    eng = _store(tmp_path)
    assert ai.pending(eng) == ("work", [LINK])
    ctx = _Ctx()
    rep = ai.build_missing(eng, ctx)
    assert rep["outcome"] == "built" and list(rep["built"]) == [LINK]
    assert LINK in _names(eng)
    detail = ctx.calls[0]["detail"]
    assert isinstance(detail, Framed) and detail.i18n == ai.FRAME_LINK_BUILDING, (
        "never the article list's words"
    )
    assert rep["link_rows_bound"] == 60 * 6 and "rows_bound" not in rep
    assert ai.pending(eng) == ("present", [])


def test_after_the_article_indexes_and_in_one_job(tmp_path):
    eng = _store(tmp_path, drop=(LANG, TITLE, LINK))
    ctx = _Ctx()
    rep = ai.build_missing(eng, ctx)
    assert list(rep["built"]) == [LANG, TITLE, LINK]
    frames = [c["detail"].i18n for c in ctx.calls if isinstance(c.get("detail"), Framed)]
    assert frames == [ai.FRAME_BUILDING, ai.FRAME_BUILDING, ai.FRAME_LINK_BUILDING]
    first = next(c["detail"] for c in ctx.calls if isinstance(c.get("detail"), Framed))
    assert first.vars == {"index": 1, "total": 2}, (
        "the article frame counts the article indexes only"
    )


def test_links_refused_for_memory_do_not_hold_the_article_indexes_back(tmp_path, monkeypatch):
    eng = _store(tmp_path, drop=(LANG, TITLE, LINK))
    monkeypatch.setattr(ai, "RAM_BYTES_PER_LINK", 10**12)  # the links alone cannot fit
    ctx = _Ctx()
    with pytest.raises(ai.Declined):
        ai.build_missing(eng, ctx)
    snap = ai.snapshot()
    assert snap["outcome"] == "declined" and list(snap["built"]) == [LANG, TITLE]
    assert {LANG, TITLE} <= _names(eng) and LINK not in _names(eng)
    last = ctx.calls[-1]["detail"]
    assert last.i18n == ai.FRAME_LINK_NO_MEMORY and last.vars["rows"] == 360, last.vars
    assert snap["link_preflight"]["short_on"] == ["memory"]


def test_the_links_are_asked_against_the_room_left_after_the_article_indexes(tmp_path, monkeypatch):
    eng = _store(tmp_path, drop=(LANG, TITLE, LINK))
    articles_need = 60 * ai.BYTES_PER_ARTICLE
    links_need = 360 * ai.BYTES_PER_LINK

    class Usage:
        free = articles_need + links_need - 1  # each fits alone, not both

    monkeypatch.setattr(ai.shutil, "disk_usage", lambda where: Usage)
    with pytest.raises(ai.Declined):
        ai.build_missing(eng, _Ctx())
    snap = ai.snapshot()
    assert list(snap["built"]) == [LANG, TITLE]
    assert snap["link_preflight"]["reserved_bytes"] == articles_need and snap["link_preflight"][
        "short_on"
    ] == ["database"]


def test_only_links_missing_and_refused_is_a_declined_row_in_the_links_words(tmp_path, monkeypatch):
    from src.api import jobs as jobs_api

    eng = _store(tmp_path)

    class Usage:
        free = 1_000

    monkeypatch.setattr(ai.shutil, "disk_usage", lambda where: Usage)
    assert ai.run_now_and_wait(eng) == "declined"
    row = next(j for j in jobs_api.list_jobs()["jobs"] if j["id"] == "article-indexes")
    assert row["detail_i18n"] == ai.FRAME_LINK_NO_ROOM, row
    assert row["detail_vars"]["rows"] == 360


def test_two_unfinished_starts_name_the_links_when_only_they_are_missing(tmp_path):
    eng = _store(tmp_path)
    from src import __version__

    marker = ai._marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"version": __version__, "attempts": ai.MAX_UNFINISHED_STARTS}), encoding="utf-8"
    )
    ctx = _Ctx()
    with pytest.raises(ai.Declined):
        ai.build_missing(eng, ctx)
    assert ctx.calls[-1]["detail"].i18n == ai.FRAME_LINK_UNFINISHED


def test_the_four_frames_are_keys_in_every_locale_translated_with_their_placeholders():
    frames = (
        ai.FRAME_LINK_BUILDING,
        ai.FRAME_LINK_NO_ROOM,
        ai.FRAME_LINK_NO_MEMORY,
        ai.FRAME_LINK_UNFINISHED,
    )
    for p in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for key in frames:
            assert key in d, (p.name, key[:40])
        for key in (ai.FRAME_LINK_NO_ROOM, ai.FRAME_LINK_NO_MEMORY):
            assert all(f"{{{v}}}" in d[key] for v in ("free", "needed", "rows")), (p.name, key[:40])
        for key in (ai.FRAME_LINK_BUILDING, ai.FRAME_LINK_UNFINISHED):
            assert "{" not in d[key], (p.name, key[:40])
        if p.stem != "en":
            assert all(d[k] != k for k in frames), f"{p.name}: left in English"
    assert "two starts in a row" in ai.FRAME_LINK_UNFINISHED and ai.MAX_UNFINISHED_STARTS == 2
