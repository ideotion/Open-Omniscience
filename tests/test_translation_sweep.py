"""The AI-coordinator translation sweeps (S05-08, gate row H of 0.5; Q405, Q513 = b + c).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mostly NEGATIVE SPACE, because that is where a translation sweep lies: no language
reported -> nothing is translated and nothing is guessed; a term a verified ring covers
-> the model is never asked; a model outage -> the cursor does not move; the coverage
file absent -> K6 says not measurable; the title sweep -> the article row is
byte-identical afterwards; the opt-in off -> no ≈ title reaches a list.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.ai_layer import translation_sweep as TSW
from src.analytics import translation_store as TS
from src.database.models import (
    Article,
    ArticleTitleTranslation,
    Base,
    Keyword,
    KeywordTranslation,
    Source,
)

# (term, language, article_count) chosen so each branch of the sweep is reached:
#   climat      fr, a verified-ring member            -> never sent to the model
#   kanzleramt  de, in no ring                        -> translated (stub)
#   zzznotaword fr, in no ring, the stub echoes it    -> no usable answer, nothing stored
#   budget      en, already the target language       -> skipped
#   nolang      no language in the corpus             -> skipped, counted, never guessed
_SEED = [
    ("climat", "fr", 60),
    ("kanzleramt", "de", 50),
    ("zzznotaword", "fr", 40),
    ("budget", "en", 30),
    ("nolang", None, 20),
]


class _Stub:
    """A loopback-model stand-in: answers from a table, echoes anything else."""

    def __init__(self, answers=None, *, fail=None):
        self.answers = answers or {"kanzleramt": "chancellery"}
        self.calls: list[str] = []
        self.fail = fail

    def generate(self, prompt, **_kw):
        self.calls.append(prompt)
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(text=self.answers.get(prompt.strip().lower(), prompt), model="stub")


@pytest.fixture()
def db(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True)
    Base.metadata.create_all(e)
    maker = sessionmaker(bind=e, future=True, expire_on_commit=False)
    with maker() as s:
        s.add(Source(name="S", domain="s.test"))
        s.flush()
        for term, lang, ac in _SEED:
            s.add(Keyword(term=term, normalized_term=term, language=lang, frequency=0,
                          mention_count=ac, article_count=ac))
        s.commit()

    @contextlib.contextmanager
    def factory():
        with maker() as s:
            yield s

    return factory


@pytest.fixture(autouse=True)
def _isolated_files(monkeypatch, tmp_path):
    from src.monitoring import kpi as kpi_mod

    monkeypatch.setattr(kpi_mod, "_coverage_path", lambda: tmp_path / "keyword-coverage.json")
    monkeypatch.setattr(TSW, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(TSW, "_hidden", lambda: set())
    return tmp_path


_CTX = SimpleNamespace(stopping=False, set_progress=lambda **_k: None)


def _run(db, stub, **kw):
    return TSW.run_keyword_translation_sweep(
        _CTX, model="stub-model", session_factory=db, client=stub, target_lang="en", **kw
    )


def test_the_sweep_records_tentative_rows_and_never_asks_about_a_ring_term(db):
    stub = _Stub()
    out = _run(db, stub)
    assert out["complete"] is True
    # climat (ring), budget (same language) and nolang (no language) never reached it.
    assert sorted(stub.calls) == ["kanzleramt", "zzznotaword"]
    with db() as s:
        rows = s.scalars(select(KeywordTranslation)).all()
        assert [(r.term, r.source_lang, r.target_lang, r.text) for r in rows] == [
            ("kanzleramt", "de", "en", "chancellery")
        ]
        assert rows[0].model == "stub-model" and rows[0].prompt_version
    t = out["totals"]
    assert t["verified"] == 1 and t["same_language"] == 1 and t["no_language"] == 1
    assert t["added"] == 1 and t["no_usable_answer"] == 1  # the echo stored nothing


def test_the_sweep_is_shown_by_the_ladder_it_feeds(db):
    _run(db, _Stub())
    with db() as s:
        got = TS.tentative_translations(s, ["Kanzleramt"], "en")
    assert got["kanzleramt"]["text"] == "chancellery"


def test_no_interface_language_means_nothing_is_translated_and_nothing_is_guessed(db, monkeypatch):
    monkeypatch.setattr(TSW, "interface_lang", lambda: None)
    stub = _Stub()
    out = TSW.run_keyword_translation_sweep(_CTX, model="m", session_factory=db, client=stub)
    assert out["complete"] is True and "No interface language" in out["note"]
    assert stub.calls == []


def test_an_outage_pauses_without_moving_the_cursor(db):
    from src.llm.ollama import LLMUnavailable

    out = _run(db, _Stub(fail=LLMUnavailable("down")))
    assert out["complete"] is False and "unavailable" in out["paused_reason"]
    assert out.get("cursor") is None and out.get("position") == 0
    # And the retry, with the model back, picks the SAME keywords up.
    again = _run(db, _Stub())
    assert again["complete"] is True and again["totals"]["added"] == 1


def test_a_finished_pass_rests_then_restarts_and_a_new_model_restarts_at_once(db):
    first = _run(db, _Stub())
    assert first["pass_completed_at"]
    stub = _Stub()
    assert _run(db, stub)["complete"] is True and stub.calls == []  # resting
    later = lambda: datetime.now(UTC) + TSW.REPASS_AFTER + timedelta(minutes=1)  # noqa: E731
    stub = _Stub()
    out = _run(db, stub, now=later)
    # A re-pass re-reads the head; the term already answered is not asked again.
    assert out["complete"] is True and "kanzleramt" not in stub.calls
    stub = _Stub()
    TSW.run_keyword_translation_sweep(_CTX, model="another", session_factory=db, client=stub,
                                      target_lang="en")
    assert "zzznotaword" in stub.calls  # a new model is a new pass


def test_the_head_bounds_the_pass(db):
    stub = _Stub()
    out = _run(db, stub, head=2)
    assert out["position"] == 2 and out["complete"] is True
    assert stub.calls == ["kanzleramt"]  # rank 2; rank 3 is beyond the head


def test_coverage_is_persisted_and_k6_shows_it_and_says_so_when_it_is_gone(db, _isolated_files):
    from src.monitoring.kpi import kpi_snapshot

    _run(db, _Stub())
    k6 = next(m for m in kpi_snapshot()["metrics"] if m["id"] == "K6")
    sw = k6["sweep"]
    assert sw["verdict"] == "measured-no-bar" and sw["as_of"]
    assert sw["value"] == 1 and sw["n"] == 5
    assert sw["counts"] == {"verified": 1, "tentative": 1, "untranslated": 1,
                            "same_language": 1, "no_language": 1}
    assert sum(sw["counts"].values()) == sw["n"]
    # THE MUTATION CHECK the brief asks for: delete the file -> not measurable, no value.
    (_isolated_files / "translation-sweep-coverage.json").unlink()
    k6 = next(m for m in kpi_snapshot()["metrics"] if m["id"] == "K6")
    assert k6["sweep"]["verdict"] == "not-measurable-here"
    assert k6["sweep"]["value"] is None and k6["sweep"]["as_of"] is None


def test_the_kpi_get_never_measures():
    import inspect

    from src.monitoring import kpi

    src = inspect.getsource(kpi._k6_sweep_block)
    assert "measure_keyword_coverage" not in src and "translation_sweep" not in src


# --------------------------------------------------------------------------- #
#  S2 -- the title sweep
# --------------------------------------------------------------------------- #
def _article(s, **kw):
    a = Article(url=kw.get("url", "u1"), canonical_url=kw.get("url", "u1"), source_id=1,
                title=kw.get("title", "Der Kanzler trifft die Presse"),
                content=kw.get("content", "Berlin. Der Kanzler sprach heute."),
                hash=kw.get("hash", "h1"), language=kw.get("language", "de"))
    s.add(a)
    s.commit()
    return a.id


def _row_bytes(s, aid):
    t = Article.__table__
    return tuple(s.execute(select(t).where(t.c.id == aid)).one())


def test_the_title_sweep_never_writes_the_article_row(db):
    with db() as s:
        aid = _article(s)
        en = _article(s, url="u2", hash="h2", language="en", title="Already English")
        before = _row_bytes(s, aid)
    stub = _Stub({"der kanzler trifft die presse": "The chancellor meets the press"})
    out = TSW.run_title_translation_sweep(_CTX, model="stub-model", session_factory=db,
                                          client=stub, target_lang="en")
    assert out["complete"] is True and out["totals"]["added"] == 1
    assert out["totals"]["same_language"] == 1
    with db() as s:
        assert _row_bytes(s, aid) == before  # byte-identical: never stored as the article
        rows = s.scalars(select(ArticleTitleTranslation)).all()
        assert [(r.article_id, r.title, r.target_lang, r.source_lang) for r in rows] == [
            (aid, "The chancellor meets the press", "en", "de")
        ]
        assert rows[0].summary  # the gist of the opening, a second call
        assert en not in {r.article_id for r in rows}


def test_titles_reach_a_list_only_with_both_switches_on(db, monkeypatch):
    with db() as s:
        aid = _article(s)
        s.add(ArticleTitleTranslation(article_id=aid, source_lang="de", target_lang="en",
                                      title="≈ title", summary=None, model="m",
                                      prompt_version=TSW.TITLE_PROMPT_VERSION))
        s.commit()
        for master, opt_in, shown in ((True, True, True), (True, False, False),
                                      (False, True, False)):
            st = SimpleNamespace(ai_background_enabled=master, ai_sweep_article_titles=opt_in)
            monkeypatch.setattr(TSW, "titles_shown", lambda settings=None, _st=st:
                                bool(_st.ai_background_enabled and _st.ai_sweep_article_titles))
            got = TSW.title_translations_for(s, [aid], "en")
            assert (aid in got) is shown
            if shown:
                assert got[aid]["tier"] == "tentative" and got[aid]["model"] == "m"


def test_the_title_sweep_is_opt_in_and_keyword_translation_rides_the_master():
    from src.ai_layer.coordinator import _member_specs
    from src.config.app_settings import AppSettings

    d = AppSettings()
    assert d.ai_sweep_article_titles is False  # Q513 = b: opt-in
    assert d.ai_sweep_keyword_translation is True  # Q405: shown by default under the master
    keys = {m.key: m.enabled_key for m in _member_specs()}
    assert keys["keyword_translation"] == "ai_sweep_keyword_translation"
    assert keys["article_titles"] == "ai_sweep_article_titles"


def test_the_interface_language_is_validated_before_it_is_stored(monkeypatch):
    stored = {}
    monkeypatch.setattr("src.config.kv_store.kv_set_json", lambda k, v: stored.update({k: v}))
    assert TSW.record_interface_lang("fr-FR") == "fr"
    assert stored[TSW.INTERFACE_LANG_KEY]["lang"] == "fr"
    stored.clear()
    for bad in ("", None, "../x", "english1"):
        assert TSW.record_interface_lang(bad) is None
    assert stored == {}


def test_the_title_table_is_not_carried_by_a_restore_and_says_why():
    from src.backup.merge import _MERGE_NOT_CARRIED

    assert "article_title_translations" in _MERGE_NOT_CARRIED
    assert "never the article" in _MERGE_NOT_CARRIED["article_title_translations"]
