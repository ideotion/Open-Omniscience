"""
B15: OPT-IN local-LLM language detection for articles STILL unknown after the offline detector.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the doctrine end to end with a DETERMINISTIC stub client (no Ollama, no network) over
an ISOLATED in-memory DB (never the shared session DB — the #577 pollution lesson):
  * detector-first: only articles with BOTH language AND detected_language unset are worked;
  * writes ONLY ai_keyword(kind="language") — Article.language / detected_language untouched;
  * garbage / unknown / chatty answers store NOTHING (miss over invent);
  * skip-existing tops up; a cancel stops early; an Ollama outage aborts loudly.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import langdetect_llm as ld
from src.database.models import AiKeyword, Article, Base, Source
from src.llm.ollama import GenerationResult, LLMError, LLMUnavailable


class _FakeOllama:
    """Deterministic offline stand-in. ``reply`` is a fixed string, a per-call list, or a
    callable(prompt)->str. ``unavailable``/``fail`` exercise the error paths."""

    def __init__(self, reply="", *, unavailable=False, fail=False):
        self.base_url = "http://127.0.0.1:11434"
        self._reply = reply
        self._unavailable = unavailable
        self._fail = fail
        self.calls: list[str] = []

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        self.calls.append(prompt)
        if self._unavailable:
            raise LLMUnavailable("Ollama not reachable (fake)")
        if self._fail:
            raise LLMError("model error (fake)")
        r = self._reply
        if callable(r):
            text = r(prompt)
        elif isinstance(r, list):
            i = len(self.calls) - 1
            text = r[i] if i < len(r) else ""
        else:
            text = r
        return GenerationResult(model=model, text=text)


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def _seed(session, *, language, detected, title="Titre", body=None):
    src = session.query(Source).first()
    if src is None:
        src = Source(name="s", domain=f"{uuid.uuid4().hex[:8]}.ex", language="en")
        session.add(src)
        session.flush()
    a = Article(
        url=f"https://x/{uuid.uuid4().hex}", canonical_url=f"https://x/{uuid.uuid4().hex}",
        source_id=src.id, title=title,
        content=body or ("Un texte assez long pour la détection. " * 20),
        language=language, detected_language=detected,
        hash=uuid.uuid4().hex + uuid.uuid4().hex,
    )
    session.add(a)
    session.flush()
    return a.id


# --- pure parse units (no DB) ---------------------------------------------- #


def test_parse_lang_accepts_a_clean_known_code():
    assert ld.parse_lang("ko") == "ko"
    assert ld.parse_lang("FR") == "fr"
    assert ld.parse_lang("  de \n") == "de"
    assert ld.parse_lang("Language: fr") == "fr"
    assert ld.parse_lang("The language is ja.") == "ja"
    assert ld.parse_lang('"ru"') == "ru"


def test_parse_lang_rejects_garbage_and_chatty_and_unknown():
    # a chatty sentence is ambiguous ("it"/"no"/"he" are codes) -> reject, never guess
    assert ld.parse_lang("It is French") is None
    assert ld.parse_lang("The text appears to be written in Korean") is None
    # refusals / non-answers
    assert ld.parse_lang("unknown") is None
    assert ld.parse_lang("As an AI, I cannot be sure") is None
    assert ld.parse_lang("mixed") is None
    # a made-up / app-unknown code stores nothing
    assert ld.parse_lang("xx") is None
    assert ld.parse_lang("zz") is None
    assert ld.parse_lang("english") is None      # a word, not a 2-letter code
    assert ld.parse_lang("") is None and ld.parse_lang(None) is None


def test_build_system_demands_only_the_code():
    sysp = ld.build_system().lower()
    assert "iso 639-1" in sysp and "code" in sysp
    assert "nothing else" in sysp or "output nothing" in sysp


# --- detector-first worklist ----------------------------------------------- #


def test_unknown_language_work_is_detector_first(db):
    a_unknown = _seed(db, language=None, detected=None)
    _seed(db, language="fr", detected=None)        # asserted -> excluded
    _seed(db, language=None, detected="de")        # offline-deduced -> excluded
    _seed(db, language="", detected="")            # both empty strings -> INCLUDED
    work = ld.unknown_language_work(db, 50)
    ids = {w.article_id for w in work}
    assert a_unknown in ids
    assert len(work) == 2                            # only the two genuinely-unknown ones
    # every returned article really is unknown on BOTH channels
    for w in work:
        row = db.get(Article, w.article_id)
        assert (row.language or "") == "" and (row.detected_language or "") == ""


# --- the writer: only ai_keyword, never the trusted channels --------------- #


def _run(session, monkeypatch, work, client, **kw):
    """Route the module's session_scope to our isolated session, then drain the generator."""
    @contextlib.contextmanager
    def _scope():
        yield session
    monkeypatch.setattr(ld, "session_scope", _scope)
    return list(ld.detect_for_articles(work, client, model="m", **kw))


def test_detect_stores_only_ai_keyword_and_never_touches_article_language(db, monkeypatch):
    aid = _seed(db, language=None, detected=None)
    work = ld.unknown_language_work(db, 10)
    events = _run(db, monkeypatch, work, _FakeOllama("ko"))
    done = events[-1]
    assert done["event"] == "done" and done["stored"] == 1 and not done["aborted"]
    # the AI-derived label landed, kind="language", with provenance + no score
    rows = db.query(AiKeyword).filter_by(article_id=aid, kind="language").all()
    assert len(rows) == 1
    r = rows[0]
    assert r.term == "ko" and r.language == "ko"
    assert r.prompt_version == ld.LANGDETECT_PROMPT_VERSION and r.confirmed is False
    assert not hasattr(r, "score")
    # the TRUSTED channels are untouched (the whole point)
    art = db.get(Article, aid)
    assert art.language is None and art.detected_language is None


def test_garbage_answer_stores_nothing(db, monkeypatch):
    aid = _seed(db, language=None, detected=None)
    work = ld.unknown_language_work(db, 10)
    events = _run(db, monkeypatch, work, _FakeOllama("It is definitely some language"))
    done = events[-1]
    assert done["stored"] == 0 and done["none"] == 1
    assert db.query(AiKeyword).filter_by(article_id=aid).count() == 0


def test_worklist_slides_past_labelled_so_the_tail_is_reachable(db, monkeypatch):
    """Skeptic HIGH: the job never writes the trusted channels, so the worklist MUST exclude
    already-AI-labelled articles in SQL — otherwise every run re-fetches the same newest N
    and the tail beyond ``limit`` is unreachable. With limit=1: run 1 labels the newest, run 2
    slides to the OLDER one (never the labelled newest), so re-running continues the tail."""
    a1 = _seed(db, language=None, detected=None)   # lower id (older)
    a2 = _seed(db, language=None, detected=None)    # higher id (newer) -> first by id DESC
    w1 = ld.unknown_language_work(db, 1)
    assert [w.article_id for w in w1] == [a2]        # newest first
    _run(db, monkeypatch, w1, _FakeOllama("fr"))
    # run 2: the labelled a2 is now EXCLUDED in SQL -> the window slides to a1 (the tail)
    w2 = ld.unknown_language_work(db, 1)
    assert [w.article_id for w in w2] == [a1]
    _run(db, monkeypatch, w2, _FakeOllama("de"))
    # both articles ended up labelled across two bounded runs; the worklist is now empty
    assert ld.unknown_language_work(db, 10) == []
    assert db.query(AiKeyword).filter_by(article_id=a1, kind="language").count() == 1
    assert db.query(AiKeyword).filter_by(article_id=a2, kind="language").count() == 1


def test_exclude_ids_makes_the_query_advance_past_unstored_attempts(db):
    """The continuous-mode seam: unlike the AI-label exclusion (which only advances past
    STORED results), exclude_ids must also advance past articles a caller has merely
    ATTEMPTED this run — even though a "none"/garbage result writes no ai_keyword row and
    would otherwise keep re-appearing at the top of every subsequent (newest-first) query."""
    a1 = _seed(db, language=None, detected=None)  # lower id (older)
    a2 = _seed(db, language=None, detected=None)  # higher id (newer) -> first by id DESC
    w1 = ld.unknown_language_work(db, 1)
    assert [w.article_id for w in w1] == [a2]
    # a2 is "attempted" (imagine it came back "none" -- no ai_keyword row written), so
    # exclude_ids must slide the window to a1 exactly as the AI-label exclusion would.
    w2 = ld.unknown_language_work(db, 1, exclude_ids={a2})
    assert [w.article_id for w in w2] == [a1]
    # excluding BOTH leaves nothing -- the query converges, never spins forever.
    assert ld.unknown_language_work(db, 10, exclude_ids={a1, a2}) == []
    # an empty/falsy exclude_ids must behave exactly like omitting the parameter (no filter).
    assert [w.article_id for w in ld.unknown_language_work(db, 1, exclude_ids=set())] == [a2]


def test_skip_existing_defends_against_a_stale_worklist(db, monkeypatch):
    """Defense-in-depth: even if a caller hands detect_for_articles a work item that was
    already labelled (a stale snapshot), skip_existing tops up rather than duplicating."""
    aid = _seed(db, language=None, detected=None)
    work = ld.unknown_language_work(db, 10)
    _run(db, monkeypatch, work, _FakeOllama("fr"))
    # re-run the SAME (now-stale) work list -> the row exists -> skipped, no override/dup
    events = _run(db, monkeypatch, work, _FakeOllama("de"))
    done = events[-1]
    assert done["skipped"] == 1 and done["stored"] == 0
    rows = db.query(AiKeyword).filter_by(article_id=aid, kind="language").all()
    assert len(rows) == 1 and rows[0].term == "fr"   # the first label stands


def test_cancel_stops_early(db, monkeypatch):
    for _ in range(4):
        _seed(db, language=None, detected=None)
    work = ld.unknown_language_work(db, 10)
    events = _run(db, monkeypatch, work, _FakeOllama("fr"), should_stop=lambda: True)
    done = events[-1]
    assert done["aborted"] is True and done["reason"] == "cancelled"
    assert done["stored"] == 0


def test_ollama_outage_aborts_loudly(db, monkeypatch):
    _seed(db, language=None, detected=None)
    work = ld.unknown_language_work(db, 10)
    events = _run(db, monkeypatch, work, _FakeOllama(unavailable=True))
    done = events[-1]
    assert done["event"] == "done" and done["aborted"] is True
    assert db.query(AiKeyword).count() == 0
