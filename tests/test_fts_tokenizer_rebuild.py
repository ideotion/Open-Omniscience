"""The article index keeps Devanagari, Bengali and vocalised Arabic words whole (S05-02 S6, R39).

Under the default ``unicode61`` categories a vowel sign is a separator: सरकार indexed as सरक + र, so a search for सरक matched
सरकार and every word with a matra was shredded. The tokenizer option ``categories 'L* N* Co M*'`` fixes it, but a tokenizer
is fixed when the table is CREATED, so an index made before 0.5 is dropped, created again and rebuilt, once, in the same
app-stopped window as the country migration. These tests hold, in the order it matters:

1. the new tokenizer does what the finding measured, and does NOT change what it must not (é still folds; Chinese,
   Japanese and Arabic keep the paths of Q506/Q507, so ``tests/test_fts_cjk_arabic.py`` is the other half of this);
2. nothing is silent: a boot never rebuilds (the cost is corpus-sized), the explicit re-index and the migration do;
3. the swap is atomic (a run that dies leaves the OLD index, never an empty one), and never leaves a token behind a
   deleted document (the one way an FTS5 index is corrupted).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.backup import country_migration as cm
from src.database import fts
from src.database.fts import ensure_fts, fts_tokenizer, rebuild_with_current_tokenizer, search_ids
from src.database.models import Article, Base, Source

_DOCS = {
    "hi1": ("भारत सरकार ने नई नीति जारी की", "hi"),
    "hi2": ("मुख्यमंत्री ने सरकारी स्कूल का दौरा किया", "hi"),
    "bn1": ("বাংলা ভাষা আন্দোলন এবং শিক্ষাব্যবস্থা", "bn"),
    "ar1": ("أحمد ذهب إلى المَدْرَسَةِ الكبيرة في القاهرة", "ar"),
    "fr1": ("Le café de la rue déjà fermé, l'école aussi", "fr"),
    "zh1": ("东京大学的学生在北京参加了气候变化会议", "zh"),
}

_LEGACY_TABLE = (
    "CREATE VIRTUAL TABLE article_fts USING fts5(title, content, content='articles', "
    "content_rowid='id', tokenize='unicode61 remove_diacritics 2')"
)


def _seed(session, docs=_DOCS):
    src = session.query(Source).filter_by(domain="t.example").one_or_none()
    if src is None:
        src = Source(name="t", domain="t.example")
        session.add(src)
        session.flush()
    for key, (content, lang) in docs.items():
        session.add(
            Article(
                url=f"https://t.example/{key}", canonical_url=f"https://t.example/{key}", source_id=src.id,
                title=key, content=content, language=lang, hash=key.ljust(64, "0"),
            )
        )
    session.commit()


def _store(tmp_path: Path, *, legacy: bool) -> tuple[Path, object]:
    """A scratch store file whose search index was created the old way (``legacy``) or the new way, then filled by the
    app's own ``ensure_fts`` rebuild: the same path a real store's index was made by."""
    path = tmp_path / "s.db"
    eng = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(eng)
    if legacy:
        with eng.begin() as c:
            c.execute(text(_LEGACY_TABLE))
    with sessionmaker(bind=eng)() as s:
        _seed(s)
    ensure_fts(eng)  # creates the triggers, and fills an index the triggers never saw
    return path, eng


def _terms(eng) -> list[str]:
    with eng.begin() as c:
        c.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS v_probe USING fts5vocab(article_fts, 'row')"))
        rows = [r[0] for r in c.execute(text("SELECT term FROM v_probe ORDER BY term"))]
        c.execute(text("DROP TABLE v_probe"))
    return rows


def _hits(eng, query: str) -> list[int]:
    with sessionmaker(bind=eng)() as s:
        return sorted(search_ids(s, query) or [])


def _assert_clean_after_deleting_everything(eng):
    with sessionmaker(bind=eng)() as s:
        for a in s.query(Article).all():
            s.delete(a)
        s.commit()
    assert _terms(eng) == [], "a token outlived its document: the index was corrupted"


def test_a_new_index_has_the_current_tokenizer_and_keeps_the_words_whole(tmp_path):
    _path, eng = _store(tmp_path, legacy=False)
    with eng.connect() as c:
        assert fts_tokenizer(c) == "current"
    terms = _terms(eng)
    assert {"सरकार", "सरकारी", "বাংলা", "ভাষা"} <= set(terms), terms
    assert not {"सरक", "र", "ব", "ল"} & set(terms), "a vowel sign split a word"
    assert any("مدرس" in t for t in terms), terms  # the vocalised Arabic word is one token (the fold is Q507's)
    assert _hits(eng, "सरकार") and not _hits(eng, "सरक"), "सरक must not match सरकार"


def test_what_the_tokenizer_must_not_change_is_unchanged(tmp_path):
    _path, eng = _store(tmp_path, legacy=False)
    assert _hits(eng, "cafe") and _hits(eng, "deja") and _hits(eng, "ecole"), "diacritics must still fold"
    assert _hits(eng, "气候"), "Chinese keeps its segmenter path"
    assert _hits(eng, "المدرسه"), "Arabic keeps its fold path"


def test_a_legacy_index_is_left_alone_by_a_normal_boot_and_shows_the_old_behaviour(tmp_path):
    _path, eng = _store(tmp_path, legacy=True)
    ensure_fts(eng)  # a boot (auto): must NOT pay the corpus-sized rebuild
    with eng.connect() as c:
        assert fts_tokenizer(c) == "legacy"
    assert _hits(eng, "सरक"), "the legacy index shreds सरकार (this is the finding)"
    assert "सरक" in _terms(eng)


def test_the_explicit_reindex_gives_an_old_index_the_current_tokenizer(tmp_path):
    _path, eng = _store(tmp_path, legacy=True)
    assert ensure_fts(eng, rebuild="always") == "rebuilt"
    with eng.connect() as c:
        assert fts_tokenizer(c) == "current"
    assert _hits(eng, "सरकार") and not _hits(eng, "सरक")
    assert len(_hits(eng, "cafe")) == 1
    _assert_clean_after_deleting_everything(eng)


def test_a_rebuild_with_the_current_tokenizer_indexes_every_article_once(tmp_path):
    _path, eng = _store(tmp_path, legacy=True)
    with eng.begin() as c:
        out = rebuild_with_current_tokenizer(c)
    assert out["tokenizer_before"] == "legacy" and out["tokenizer_after"] == "current"
    assert out["indexed"] == len(_DOCS)
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM article_fts_docsize")).scalar() == len(_DOCS)
    # a second call on an index that already has it rebuilds in place and drops nothing
    with eng.begin() as c:
        again = rebuild_with_current_tokenizer(c)
    assert again["tokenizer_before"] == "current" and again["indexed"] == len(_DOCS)


def test_a_rebuild_that_dies_leaves_the_old_index_not_an_empty_one(tmp_path, monkeypatch):
    _path, eng = _store(tmp_path, legacy=True)
    before = _terms(eng)

    def boom(_con):
        raise RuntimeError("disk full")

    monkeypatch.setattr(fts, "rebuild_index", boom)
    with pytest.raises(RuntimeError), eng.begin() as c:
        rebuild_with_current_tokenizer(c)
    monkeypatch.undo()
    with eng.connect() as c:
        assert fts_tokenizer(c) == "legacy", "the drop was not rolled back"
    assert _terms(eng) == before, "the old index lost entries"
    assert _hits(eng, "सरक"), "and still answers"


def test_an_explicit_reindex_that_dies_leaves_the_old_index_not_an_empty_one(tmp_path, monkeypatch):
    _path, eng = _store(tmp_path, legacy=True)
    before = _terms(eng)

    def boom(_con):
        raise RuntimeError("disk full")

    monkeypatch.setattr(fts, "rebuild_index", boom)
    with pytest.raises(RuntimeError):
        ensure_fts(eng, rebuild="always")
    monkeypatch.undo()
    with eng.connect() as c:
        assert fts_tokenizer(c) == "legacy", "the drop was not rolled back"
        assert c.execute(text("SELECT count(*) FROM article_fts_docsize")).scalar() == len(_DOCS)
    assert _terms(eng) == before and _hits(eng, "सरक"), "the old index still answers"
    # and the next explicit re-index finishes the job
    assert ensure_fts(eng, rebuild="always") == "rebuilt"
    with eng.connect() as c:
        assert fts_tokenizer(c) == "current"


def test_the_tokenizer_swap_needs_an_index_to_swap(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'e.db'}", future=True)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        assert fts_tokenizer(c) is None
        with pytest.raises(RuntimeError):
            rebuild_with_current_tokenizer(c)


def test_the_status_says_which_tokenizer_the_index_has(tmp_path):
    from src.database.fts import fts_status

    for legacy, expected in ((True, "legacy"), (False, "current")):
        _path, eng = _store_in(tmp_path, legacy)
        with sessionmaker(bind=eng)() as s:
            assert fts_status(s)["tokenizer"] == expected


def _store_in(tmp_path: Path, legacy: bool):
    sub = tmp_path / ("legacy" if legacy else "current")
    sub.mkdir()
    return _store(sub, legacy=legacy)


# --- the migration window --------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _small_windows(monkeypatch):
    monkeypatch.setattr(cm, "BATCH_ROWIDS", 9)


def _alpha2_store(tmp_path: Path, *, legacy: bool) -> tuple[Path, object]:
    path, eng = _store(tmp_path, legacy=legacy)
    # give the rows a country so the sweep has work (the form marker is absent: an alpha-2 store)
    con = sqlite3.connect(path)
    con.execute("UPDATE articles SET country = 'fr' WHERE id % 2 = 0")
    con.commit()
    con.close()
    return path, eng


def test_the_migration_rebuilds_the_index_in_its_own_window_and_says_what_it_cost(tmp_path):
    path, eng = _alpha2_store(tmp_path, legacy=True)
    eng.dispose()
    events: list[dict] = []
    seen_estimate: dict = {}

    def confirm(_plan, est):
        seen_estimate.update(est)
        return True

    rep = cm.migrate(path, backup_dir=tmp_path / "bk", confirm=confirm, progress=events.append)
    assert rep.state == "done", rep.message
    assert rep.fts and rep.fts["tokenizer_before"] == "legacy" and rep.fts["tokenizer_after"] == "current"
    assert rep.fts["indexed"] == len(_DOCS)
    assert "the search index was rebuilt" in rep.message
    # the estimate shown BEFORE it started names the rebuild and its basis, and invents no single figure
    lo, hi = seen_estimate["fts"]["seconds_about"]
    assert 0 <= lo <= hi and "981 to 1,645 s" in seen_estimate["fts"]["basis"]
    phases = [e["phase"] for e in events]
    assert phases.index("verify") < phases.index("fts") < phases.index("fts-done") < phases.index("done")
    eng2 = create_engine(f"sqlite:///{path}", future=True)
    with eng2.connect() as c:
        assert fts_tokenizer(c) == "current"
    assert _hits(eng2, "सरकार") and not _hits(eng2, "सरक")
    _assert_clean_after_deleting_everything(eng2)


def test_a_store_that_never_had_a_legacy_index_pays_nothing(tmp_path):
    path, eng = _alpha2_store(tmp_path, legacy=False)
    eng.dispose()
    rep = cm.migrate(path, backup_dir=tmp_path / "bk")
    assert rep.state == "done" and rep.fts is None
    assert "search index" not in rep.message


def test_a_store_whose_codes_are_done_but_whose_index_is_old_gets_only_the_index(tmp_path):
    path, eng = _alpha2_store(tmp_path, legacy=False)
    eng.dispose()
    assert cm.migrate(path, backup_dir=tmp_path / "bk").state == "done"
    # an index created the old way in an alpha-3 store (a store migrated before the index moved)
    con = sqlite3.connect(path)
    from src.database.fts_norm import register

    register(con)
    con.execute("DROP TABLE article_fts")
    con.execute(_LEGACY_TABLE)
    con.execute("INSERT INTO article_fts(article_fts) VALUES ('rebuild')")
    con.commit()
    con.close()
    snap = cm.migrate(path, estimate_only=True)
    assert snap.state == "declined" and snap.estimate["fts"]["tokenizer"] == "legacy", "the estimate must name the index"
    rep = cm.migrate(path, backup_dir=tmp_path / "bk-none")
    assert rep.state == "done" and rep.fts["tokenizer_after"] == "current"
    assert "country codes were already done" in rep.message
    assert not (tmp_path / "bk-none").exists(), "the index is derived data: no second safety copy"
    assert cm.migrate(path).state == "already-done"


def test_a_failed_index_rebuild_does_not_undo_the_migrated_codes_and_the_next_run_finishes_it(tmp_path, monkeypatch):
    path, eng = _alpha2_store(tmp_path, legacy=True)
    eng.dispose()
    real = fts.rebuild_index

    def boom(_con):
        raise OSError("disk full at /secret/path")

    monkeypatch.setattr(fts, "rebuild_index", boom)
    rep = cm.migrate(path, backup_dir=tmp_path / "bk")
    monkeypatch.setattr(fts, "rebuild_index", real)
    assert rep.state == "fts-pending"
    assert rep.fts == {"state": "failed", "error": "OSError"}
    assert "/secret/path" not in rep.message and "disk full" not in rep.message, "the engine's text is never carried"
    chk = create_engine(f"sqlite:///{path}", future=True)
    with chk.connect() as c:
        assert fts_tokenizer(c) == "legacy", "the failed rebuild must leave the OLD index, not an empty current one"
        assert c.execute(text("SELECT count(*) FROM article_fts_docsize")).scalar() == len(_DOCS)
    chk.dispose()
    con = sqlite3.connect(path)
    assert con.execute("SELECT value FROM app_state WHERE key='store.country_form'").fetchone() is not None
    con.close()
    again = cm.migrate(path, backup_dir=tmp_path / "bk2")
    assert again.state == "done" and again.fts["tokenizer_after"] == "current"


def test_a_failed_index_only_run_says_so_by_class_and_the_next_run_finishes_it(tmp_path, monkeypatch):
    path, eng = _alpha2_store(tmp_path, legacy=False)
    eng.dispose()
    assert cm.migrate(path, backup_dir=tmp_path / "bk").state == "done"
    con = sqlite3.connect(path)
    from src.database.fts_norm import register

    register(con)
    con.execute("DROP TABLE article_fts")
    con.execute(_LEGACY_TABLE)
    con.execute("INSERT INTO article_fts(article_fts) VALUES ('rebuild')")
    con.commit()
    con.close()
    real = fts.rebuild_index

    def boom(_con):
        raise OSError("disk full at /secret/path")

    monkeypatch.setattr(fts, "rebuild_index", boom)
    rep = cm.migrate(path)
    monkeypatch.setattr(fts, "rebuild_index", real)
    assert rep.state == "fts-pending" and rep.fts == {"state": "failed", "error": "OSError"}
    assert "/secret/path" not in rep.message and rep.finished_at is None
    assert cm.migrate(path).state == "done"


def test_the_command_names_a_failure_by_class_and_never_prints_the_engines_text(monkeypatch, capsys):
    def boom(*_a, **_k):
        raise RuntimeError("could not open /secret/path with passphrase hunter2")

    monkeypatch.setattr(cm, "migrate", boom)
    assert cm.main(["--yes"]) == 3
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "hunter2" not in err and "/secret/path" not in err

    def interrupted(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cm, "migrate", interrupted)
    assert cm.main(["--yes"]) == 3
    assert "Interrupted" in capsys.readouterr().err


def test_the_diagnostics_card_says_which_tokenizer_the_search_index_has_and_names_the_rebuild(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        body = client.get("/api/diagnostics/country-form").json()
        assert body["search_index"] == {"tokenizer": "current", "needs_rebuild": False}
        est = client.get("/api/diagnostics/country-form?estimate=true").json()
        assert "search_index" in (est["estimate"] or {}) or "refused" in (est["estimate"] or {})
