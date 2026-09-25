"""Arabic folding and Chinese / Japanese segmentation in the article search index.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q507 = a (fold Arabic at index AND query time), Q506 🔒 = b (jieba for zh, sudachipy for ja),
brief ``S04-07`` S8. What these tests hold, in the order it matters:

1. THE INDEX IS NEVER CORRUPTED. An external-content FTS5 ``'delete'`` handed values other
   than the ones indexed silently corrupts the index. Every path here -- the triggers, a
   document indexed raw before the upgrade, the re-index job, the merge's bulk path -- is
   checked the one way that cannot be fooled: delete every article and the index's own
   vocabulary must be EMPTY.
2. Nothing that is not Arabic, Chinese or Japanese changes: the MATCH for a Latin query is
   byte-identical, and the fold returns any other text unchanged.
3. The words become findable, measured before and after on a store indexed the old way.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import fts_norm
from src.database.fts import build_match, ensure_fts, index_articles, rebuild_index, search_ids
from src.database.fts_norm import ARABIC, JA_SUDACHI, ZH_JIEBA, fold_arabic, query_variants
from src.database.fts_reindex import (
    REFUSED_NOT_UPGRADED,
    SearchReindexJobManager,
    reindex_step,
)
from src.database.models import Article, Base, Source

jieba = pytest.importorskip("jieba")

_HAS_SUDACHI = fts_norm._sudachi() is not None

# The trigger DDL every store carried before Q506/Q507 (raw text into the index).
_LEGACY = [
    """CREATE TRIGGER article_fts_ai AFTER INSERT ON articles BEGIN
        INSERT INTO article_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
    END""",
    """CREATE TRIGGER article_fts_ad AFTER DELETE ON articles BEGIN
        INSERT INTO article_fts(article_fts, rowid, title, content)
        VALUES ('delete', old.id, old.title, old.content);
    END""",
    """CREATE TRIGGER article_fts_au AFTER UPDATE OF title, content ON articles BEGIN
        INSERT INTO article_fts(article_fts, rowid, title, content)
        VALUES ('delete', old.id, old.title, old.content);
        INSERT INTO article_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
    END""",
]

_DOCS = {
    "zh1": ("东京大学的学生在北京参加了气候变化会议", "zh"),
    "zh2": ("中华人民共和国国务院发布了新的气候政策", "zh"),
    "ar1": ("أحمد ذهب إلى المَدْرَسَةِ الكبيرة في القاهرة", "ar"),
    "ar2": ("وزارة الصحة تعلن عن مستشفى جديد ـــكبير", "ar"),
    "en1": ("Climate policy and the Beijing summit", "en"),
    "hi1": ("भारत सरकार ने नई नीति जारी की", "hi"),
}

#: The measured before/after table. Each query was typed the way a reader types it.
_QUERIES = ["东京", "北京", "气候", "政策", "احمد", "أحمد", "المدرسه", "مستشفي", "كبير", "climate", "सरकार"]


def _engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


def _seed(eng, docs=_DOCS):
    s = sessionmaker(bind=eng)()
    src = s.query(Source).filter_by(domain="t.example").one_or_none()
    if src is None:
        src = Source(name="t", domain="t.example")
        s.add(src)
        s.flush()
    for key, (content, lang) in docs.items():
        s.add(
            Article(
                url=f"https://t.example/{key}",
                canonical_url=f"https://t.example/{key}",
                source_id=src.id,
                title=key,
                content=content,
                language=lang,
                hash=key.ljust(64, "0"),
            )
        )
    s.commit()
    return s


def _legacy_store():
    """A store indexed the way every store was before this change: raw."""
    eng = _engine()
    with eng.begin() as c:
        c.execute(
            text(
                "CREATE VIRTUAL TABLE article_fts USING fts5(title, content, content='articles', "
                "content_rowid='id', tokenize='unicode61 remove_diacritics 2')"
            )
        )
        for ddl in _LEGACY:
            c.execute(text(ddl))
    return eng, _seed(eng)


def _hits(s):
    return {q: sorted(search_ids(s, q) or []) for q in _QUERIES}


def _vocab_rows(s) -> int:
    s.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS v_probe USING fts5vocab(article_fts, 'row')"))
    return int(s.execute(text("SELECT count(*) FROM v_probe")).scalar())


def _assert_clean_after_deleting_everything(s):
    for a in s.query(Article).all():
        s.delete(a)
    s.commit()
    assert _vocab_rows(s) == 0, "a token outlived its document: the index was corrupted"
    assert s.execute(text("SELECT count(*) FROM article_fts_norm")).scalar() == 0


# --------------------------------------------------------------------------- #
# The fold, and what it must not touch
# --------------------------------------------------------------------------- #


def test_the_fold_is_the_ruled_one():
    assert fold_arabic("أحمد إبراهيم آمنة ٱلله") == "احمد ابراهيم امنه الله"
    assert fold_arabic("مدرسة") == "مدرسه"  # teh marbuta -> heh
    assert fold_arabic("مستشفى") == "مستشفي"  # alef maksura -> yeh
    # Measured: the tokenizer SPLITS a vocalised word at every haraka, and keeps tatweel.
    assert fold_arabic("مَدْرَسَةٌ") == "مدرسه"
    assert fold_arabic("ـــكتاب") == "كتاب"


@pytest.mark.parametrize("other", ["Climate AT&T", "Москва", "भारत सरकार", "东京大学", "東京都", "café", ""])
def test_the_fold_returns_any_other_text_unchanged(other):
    assert fold_arabic(other) is other


@pytest.mark.parametrize(
    "q",
    ["climate change", "a OR (b AND c)", '"oil prices" NOT gas', "AT&T", "Москва", "café crème"],
)
def test_a_query_with_no_arabic_or_cjk_emits_the_same_match_as_before(q):
    assert build_match(q, variants=query_variants) == build_match(q)


def test_query_variants_keep_the_literal_first():
    assert query_variants("أحمد")[:2] == ["أحمد", "احمد"]
    v = query_variants("东京大学的学生")
    assert v[0] == "东京大学的学生"  # a document indexed before the re-index holds it raw
    assert ("东京大学", "的", "学生") in v


# --------------------------------------------------------------------------- #
# A fresh store: the triggers
# --------------------------------------------------------------------------- #


def test_a_fresh_store_finds_arabic_and_chinese_by_word():
    eng = _engine()
    ensure_fts(eng)
    s = _seed(eng)
    got = _hits(s)
    ids = {a.title: a.id for a in s.query(Article)}
    assert got["东京"] == got["北京"] == [ids["zh1"]]
    assert got["气候"] == sorted([ids["zh1"], ids["zh2"]])
    assert got["احمد"] == got["أحمد"] == got["المدرسه"] == [ids["ar1"]]
    assert got["مستشفي"] == got["كبير"] == [ids["ar2"]]
    assert got["climate"] == [ids["en1"]]
    masks = dict(s.execute(text("SELECT article_id, mask FROM article_fts_norm")).fetchall())
    assert masks == {ids["zh1"]: ZH_JIEBA, ids["zh2"]: ZH_JIEBA, ids["ar1"]: ARABIC, ids["ar2"]: ARABIC}
    _assert_clean_after_deleting_everything(s)


def test_updates_and_deletes_never_corrupt_the_index():
    eng = _engine()
    ensure_fts(eng)
    s = _seed(eng)
    zh = s.query(Article).filter_by(title="zh1").one()
    ar = s.query(Article).filter_by(title="ar1").one()
    en = s.query(Article).filter_by(title="en1").one()
    zh.content = "上海的天气"  # still Chinese, re-segmented
    ar.content = "plain English now"  # its record must go
    en.content = "المدرسة الجديدة"  # Latin -> Arabic with a teh marbuta to fold
    s.commit()
    assert search_ids(s, "东京") == []
    assert search_ids(s, "上海") == [zh.id]
    assert search_ids(s, "احمد") == []
    assert search_ids(s, "المدرسه") == search_ids(s, "المدرسة") == [en.id]
    masks = dict(s.execute(text("SELECT article_id, mask FROM article_fts_norm")).fetchall())
    assert ar.id not in masks and masks[en.id] == ARABIC
    # Arabic with nothing to fold is indexed exactly as stored, so it keeps no record.
    en.content = "الكتاب الجديد"
    s.commit()
    assert search_ids(s, "الكتاب") == [en.id]
    masks = dict(s.execute(text("SELECT article_id, mask FROM article_fts_norm")).fetchall())
    assert en.id not in masks
    _assert_clean_after_deleting_everything(s)


def test_a_connection_without_the_functions_cannot_write_articles(tmp_path):
    """The contract, stated as a test: a trigger calling a function the connection lacks
    fails, and so does the write. Loud and repairable, never a corrupted index."""
    path = tmp_path / "c.db"
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    _seed(eng, {"en1": ("x", "en")}).close()
    eng.dispose()
    raw = sqlite3.connect(str(path))
    try:
        with pytest.raises(sqlite3.OperationalError, match="oo_fts_"):
            raw.execute("DELETE FROM articles")
    finally:
        raw.close()
    from src.database.connect import connect

    con = connect(path, create_encrypted=False)
    try:
        con.execute("DELETE FROM articles")  # the factory registers them
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# An existing store: the heal, the mixed index, and the re-index job
# --------------------------------------------------------------------------- #


def test_the_heal_swaps_the_triggers_without_touching_the_index():
    eng, s = _legacy_store()
    before = _hits(s)
    stmts: list[str] = []
    event.listen(eng, "before_cursor_execute", lambda *a: stmts.append(a[2]))
    assert ensure_fts(eng) == "skipped"
    assert not any("'delete-all'" in x or "'rebuild'" in x for x in stmts)
    with eng.begin() as c:
        sql = [r[0] for r in c.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger'"))]
    assert sum(fts_norm.FN_NORM in x for x in sql) == 3
    assert _hits(s) == before, "the swap changed what the index holds"
    # A document indexed raw is deleted with its raw values: no record, so no transform.
    _assert_clean_after_deleting_everything(s)


def test_the_job_makes_an_old_store_searchable_and_leaves_it_consistent(tmp_path):
    eng, s = _legacy_store()
    ensure_fts(eng)
    before = _hits(s)
    mgr = SearchReindexJobManager(state_path=tmp_path / "state.json", report_path=tmp_path / "report.json")
    mgr.start(_session_factory=sessionmaker(bind=eng))
    mgr.join(30)
    assert mgr.status()["state"] == "done"
    s.expire_all()
    after = _hits(s)
    ids = {a.title: a.id for a in s.query(Article)}
    # THE MEASURED TABLE (also in the PR): words that were unfindable now are.
    assert before["东京"] == before["北京"] == before["气候"] == []
    assert after["东京"] == [ids["zh1"]] and after["气候"] == sorted([ids["zh1"], ids["zh2"]])
    assert before["المدرسه"] == [] and after["المدرسه"] == [ids["ar1"]]
    assert before["مستشفي"] == [] and after["مستشفي"] == [ids["ar2"]]
    assert before["climate"] == after["climate"] == [ids["en1"]]
    assert before["सरकार"] == after["सरकार"], "a script outside Q506/Q507 must not move"
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["articles_checked"] == len(_DOCS)
    assert report["articles_reindexed"] == 4
    assert report["by_script"] == {"arabic": 2, "chinese": 2, "japanese": 0}
    # Idempotent: a second run finds nothing to do.
    mgr2 = SearchReindexJobManager(state_path=tmp_path / "s2.json", report_path=tmp_path / "r2.json")
    mgr2.start(_session_factory=sessionmaker(bind=eng))
    mgr2.join(30)
    assert json.loads((tmp_path / "r2.json").read_text(encoding="utf-8"))["articles_reindexed"] == 0
    _assert_clean_after_deleting_everything(s)


def test_a_paused_run_resumes_where_it_stopped(tmp_path):
    eng, s = _legacy_store()
    ensure_fts(eng)
    state = tmp_path / "state.json"
    with eng.begin() as c:
        last, exhausted, tally = reindex_step(c, after_id=None, caps=fts_norm.available_mask(), fetch=2, budget_s=0)
    assert not exhausted and tally["articles_checked"] == 2
    # A run interrupted after that step: a new manager restores it PAUSED at its cursor.
    state.write_text(json.dumps({"state": "running", "cursor": last, "max_id": 6, "tally": {}}), encoding="utf-8")
    mgr = SearchReindexJobManager(state_path=state, report_path=tmp_path / "r.json")
    assert mgr.status()["state"] == "paused" and mgr.status()["cursor"] == last
    # start() on a paused run continues it (resume() is the same call with the stored factory)
    mgr.start(_session_factory=sessionmaker(bind=eng))
    mgr.join(30)
    assert mgr.status()["state"] == "done"
    assert mgr.status()["tally"]["articles_checked"] == len(_DOCS) - 2


def test_the_job_refuses_a_store_whose_triggers_still_index_raw(tmp_path):
    eng, s = _legacy_store()  # never healed
    mgr = SearchReindexJobManager(state_path=tmp_path / "s.json", report_path=tmp_path / "r.json")
    mgr.start(_session_factory=sessionmaker(bind=eng))
    mgr.join(30)
    st = mgr.status()
    assert st["state"] == "error" and st["error"] == REFUSED_NOT_UPGRADED
    assert _hits(s)["东京"] == []  # nothing was written


def test_rebuild_and_the_merge_path_index_the_way_the_triggers_delete():
    eng = _engine()
    ensure_fts(eng)
    s = _seed(eng)
    with eng.begin() as c:
        rebuild_index(c)
    assert search_ids(s, "北京")
    # the merge's bulk path: an article inserted with the insert trigger suspended
    with eng.begin() as c:
        ddl = c.execute(text("SELECT sql FROM sqlite_master WHERE name='article_fts_ai'")).scalar()
        c.execute(text("DROP TRIGGER article_fts_ai"))
    s2 = _seed(eng, {"zh9": ("广州的地铁", "zh")})
    new_id = s2.query(Article).filter_by(title="zh9").one().id
    with eng.begin() as c:
        index_articles(c, [new_id])
        c.execute(text(ddl))
    assert search_ids(s, "地铁") == [new_id]
    _assert_clean_after_deleting_everything(s)


def _chinese_rows(s) -> int:
    """Index vocabulary entries that contain a Han character."""
    s.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS v_probe USING fts5vocab(article_fts, 'row')"))
    return sum(1 for (t,) in s.execute(text("SELECT term FROM v_probe")) if fts_norm._HAN.search(t))


def test_a_segmenter_removed_later_never_blocks_or_corrupts_a_delete(monkeypatch):
    """The exact values a segmenter produced are kept, so deleting its documents needs no
    segmenter at all -- the day it is uninstalled included."""
    eng = _engine()
    ensure_fts(eng)
    s = _seed(eng, {"zh1": _DOCS["zh1"], "zh2": _DOCS["zh2"], "en1": _DOCS["en1"]})
    kept = s.execute(text("SELECT count(*) FROM article_fts_norm WHERE content IS NOT NULL")).scalar()
    assert kept == 2
    monkeypatch.setattr(fts_norm, "_jieba", lambda: None)
    s.delete(s.query(Article).filter_by(title="zh1").one())
    s.commit()
    assert search_ids(s, "东京") == []
    # The job, run without jieba, indexes the other one the way new articles now are.
    with eng.begin() as c:
        _last, _done, tally = reindex_step(c, after_id=None, caps=ARABIC, budget_s=5)
    assert tally["articles_reindexed"] == 1 and tally["unsegmented_by_a_missing_segmenter"] == 1
    assert tally["chinese"] == 1
    assert search_ids(s, "中华人民共和国国务院发布了新的气候政策") != []  # the raw sentence, whole
    _assert_clean_after_deleting_everything(s)


def test_a_new_dictionary_never_corrupts_a_delete_and_the_job_resegments(monkeypatch):
    """A dictionary release splits the same text differently. Deletes keep reading the kept
    values; the job re-indexes exactly the documents whose words changed."""
    eng = _engine()
    ensure_fts(eng)
    s = _seed(eng)
    before = _chinese_rows(s)

    def one_char_per_word(run: str, *, for_query: bool) -> list[str]:
        return list(run)

    monkeypatch.setattr(fts_norm, "_zh_tokens", one_char_per_word)
    zh = s.query(Article).filter_by(title="zh1").one()
    zh.content = "上海的天气"  # an update: the old entry is deleted under the OLD dictionary's words
    s.commit()
    assert search_ids(s, "上海") == [zh.id]
    with eng.begin() as c:
        _last, _done, tally = reindex_step(c, after_id=None, caps=fts_norm.available_mask(), budget_s=5)
    assert tally["articles_reindexed"] == 1 and tally["chinese"] == 1  # zh2 only; zh1 is already new
    assert _chinese_rows(s) != before
    _assert_clean_after_deleting_everything(s)


def test_a_write_the_segmenter_cannot_serve_is_refused_and_the_log_says_why(monkeypatch, caplog):
    """SQLite's own message for a failing SQL function names nothing, so the log must name
    the cause and the fix. (Only reachable if a segmenter vanishes under a running process.)"""
    eng = _engine()
    ensure_fts(eng)
    s = _seed(eng, {"en1": _DOCS["en1"]})  # the connection now advertises jieba
    monkeypatch.setattr(fts_norm, "_jieba", lambda: None)
    with (
        caplog.at_level("ERROR", logger="src.database.fts_norm"),
        pytest.raises(Exception, match="user-defined function raised exception"),
    ):
        _seed(eng, {"zh9": ("广州的地铁", "zh")})
    assert "jieba" in caplog.text and "Install jieba again" in caplog.text
    s.rollback()
    assert s.query(Article).count() == 1  # refused, not half-done


@pytest.mark.skipif(not _HAS_SUDACHI, reason="sudachipy + sudachidict_core ([segmentation] extra) not installed")
def test_japanese_is_found_by_word_and_a_han_only_query_tries_both_segmenters():
    eng = _engine()
    ensure_fts(eng)
    s = _seed(eng, {"ja1": ("東京都知事選挙に行きました", "ja"), "zh1": _DOCS["zh1"]})
    ids = {a.title: a.id for a in s.query(Article)}
    assert search_ids(s, "東京") == [ids["ja1"]]
    assert search_ids(s, "選挙") == [ids["ja1"]]
    masks = dict(s.execute(text("SELECT article_id, mask FROM article_fts_norm")).fetchall())
    assert masks[ids["ja1"]] == JA_SUDACHI
    assert len(query_variants("東京都知事")) >= 2  # Han only: zh and ja readings both tried
    _assert_clean_after_deleting_everything(s)


@pytest.mark.skipif(not _HAS_SUDACHI, reason="sudachipy + sudachidict_core ([segmentation] extra) not installed")
def test_japanese_segmentation_is_safe_from_several_threads_at_once():
    """A sudachipy tokenizer refuses concurrent use; each thread must get its own."""
    import threading

    errors: list[str] = []

    def work():
        try:
            for _ in range(50):
                assert fts_norm.normalize("東京都知事選挙に行きました", JA_SUDACHI) != "東京都知事選挙に行きました"
        except Exception as exc:  # noqa: BLE001 - collected for the assertion below
            errors.append(repr(exc))

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
