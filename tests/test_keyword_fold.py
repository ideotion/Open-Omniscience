"""The keyword FOLD job (Q416 = a): re-keying keywords written before lemmatisation.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The one property everything else serves: **after the job, the corpus is keyed exactly as a
re-index with lemmatisation would key it** -- same keyword per mention, same counts, same
first offsets, exact counters, the same top keyword per article -- without reading a single
article body. It is pinned against a real re-index of the same articles, in both states a
corpus can be in: mentions that carry their language (written since PR #1148) and mentions
that do not (written before it).

Around it, the negative space: what the job must NOT touch (phrases, entities, a keyword the
user's families name, a lemma the stoplist would refuse, a language the lemmatiser does not
cover), what it must never do (delete a keyword row, copy a baseline tag), and the chassis
(it refuses when lemmatisation is off, it resumes after a pause without double counting, a
second run finds nothing).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.analytics import keyword_fold
from src.analytics.article_lang_map import MAP_SQL, ArticleLanguageMap
from src.analytics.extract import BaselineExtractor, get_extractor, lemma_key
from src.analytics.keyword_fold import (
    REFUSED_LEMMA_OFF,
    FoldRefused,
    FoldRules,
    KeywordFoldJobManager,
)
from src.analytics.lemma import LEMMA_LANGS, lemmatizer_available
from src.analytics.store import index_article, prune_orphan_keywords
from src.database.models import (
    Article,
    Base,
    Keyword,
    KeywordFamilyOverride,
    KeywordMention,
    KeywordTag,
    Source,
)

pytestmark = pytest.mark.skipif(not lemmatizer_available(), reason="simplemma not importable here")

# (hash, language, detected_language, text). Chosen so that every path is exercised: an
# English plural that folds into a keyword that already exists (studies -> study), one whose
# base form the corpus does not have yet in that article, a French and a German fold, a word
# that folds differently per language (studies: en -> study, nl -> studie, fr -> studies), a
# lemma the English stoplist refuses (cars -> car stays cars), a phrase, an acronym, and an
# article whose language is only DEDUCED.
_ARTICLES = [
    ("en1", "en", None,
     "Researchers study climate policy. The study of studies shows that studies about "
     "climate matter. Electric cars and more cars were counted. The WHO said so."),
    ("en2", "en-GB", None,
     "Elections in the region were close. The elections followed earlier elections, "
     "and studies of the vote continue."),
    ("fr1", "fr", None,
     "Les élections municipales et les études récentes. Une étude montre que les "
     "élections comptent. Le rapport cite des studies anglaises."),
    ("de1", "de", None,
     "Die Wahlen und die Studien. Eine Studie zeigt, dass die Wahlen wichtig sind."),
    ("nl1", "nl", None,
     "De studies over de verkiezingen. Nieuwe studies volgen de verkiezingen."),
    ("fr2", None, "fr",
     "Des études sur les élections régionales. Les études se multiplient."),
]


def _engine(tmp_path, name):
    eng = create_engine(f"sqlite:///{tmp_path / name}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


def _corpus(tmp_path, name, *, lemma: bool, monkeypatch):
    eng = _engine(tmp_path, name)
    s = sessionmaker(bind=eng)()
    s.add(Source(name="Test Source", domain="src.test"))
    s.commit()
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1" if lemma else "0")
    ex = get_extractor("baseline")
    for h, lang, det, body in _ARTICLES:
        a = Article(
            url=f"https://src.test/{h}", canonical_url=f"https://src.test/{h}", source_id=1,
            title="", content=body, hash=h, language=lang, detected_language=det,
            published_at=datetime(2026, 9, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.flush()
        index_article(s, a, extractor=ex)
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1")
    return eng, s


def _run_fold(tmp_path, eng, monkeypatch, *, page=500) -> KeywordFoldJobManager:
    monkeypatch.setattr(keyword_fold, "_import_owns_the_machine", lambda: False)
    mgr = KeywordFoldJobManager(
        state_path=tmp_path / f"fold_{id(eng)}.json", report_path=tmp_path / f"report_{id(eng)}.json"
    )
    mgr.start(_session_factory=sessionmaker(bind=eng), _page=page)
    mgr.join(60)
    assert mgr.status()["state"] == "done", mgr.status()
    return mgr


def _mentions(s) -> set[tuple[str, str, int, int | None]]:
    return set(
        s.execute(
            text(
                "SELECT k.normalized_term, a.hash, m.count, m.first_offset FROM keyword_mentions m "
                "JOIN keywords k ON k.id = m.keyword_id JOIN articles a ON a.id = m.article_id"
            )
        ).fetchall()
    )


def _counters_are_exact(s) -> None:
    live = {
        int(k): (int(m), int(n))
        for k, m, n in s.execute(
            text("SELECT keyword_id, SUM(count), COUNT(*) FROM keyword_mentions GROUP BY keyword_id")
        )
    }
    for kid, mc, ac in s.execute(text("SELECT id, mention_count, article_count FROM keywords")):
        assert (int(mc or 0), int(ac or 0)) == live.get(int(kid), (0, 0)), f"keyword {kid} drifted"


def _tops(s) -> dict[str, tuple]:
    out = {}
    for h, kid, cnt, tied in s.execute(
        text("SELECT hash, top_keyword_id, top_keyword_count, top_keyword_tied_n FROM articles")
    ):
        term = s.execute(text("SELECT normalized_term FROM keywords WHERE id=:k"), {"k": kid}).scalar()
        # With a tie the representative is the lowest id, and ids differ between two stores
        # built in a different order, so only an untied top keyword is compared by name.
        out[h] = (cnt, tied, term if tied == 1 else None)
    return out


@pytest.mark.parametrize("mention_languages", ["stored", "missing"])
def test_the_fold_keys_the_corpus_EXACTLY_as_a_lemmatised_reindex_would(
    tmp_path, monkeypatch, mention_languages
):
    """THE invariant, in both states a real corpus is in. "missing" nulls every mention's
    language, which is what a corpus indexed before PR #1148 looks like: the job must then
    resolve the language from the article (asserted, else deduced) and reach the same keys."""
    old_eng, old = _corpus(tmp_path, "old.db", lemma=False, monkeypatch=monkeypatch)
    new_eng, new = _corpus(tmp_path, "new.db", lemma=True, monkeypatch=monkeypatch)
    if mention_languages == "missing":
        old.execute(text("UPDATE keyword_mentions SET language = NULL"))
        old.commit()

    before = _mentions(old)
    target = _mentions(new)
    assert before != target, "fixture does not exercise lemmatisation: nothing would fold"

    mgr = _run_fold(tmp_path, old_eng, monkeypatch)
    old.expire_all()
    prune_orphan_keywords(old, budget_s=0)

    assert _mentions(old) == target
    _counters_are_exact(old)
    assert _tops(old) == _tops(new)
    tally = mgr.status()["tally"]
    assert tally["mentions_moved"] + tally["mentions_merged"] > 0
    assert tally["mentions_merged"] > 0, "no fold into an EXISTING row was exercised"
    # The language split: `studies` folds three different ways, and stays in French.
    assert ("studies", "fr1") in {(t, h) for t, h, _c, _o in _mentions(old)}
    assert ("studie", "nl1") in {(t, h) for t, h, _c, _o in _mentions(old)}
    assert ("cars", "en1") in {(t, h) for t, h, _c, _o in _mentions(old)}, "a stoplisted lemma was adopted"


def test_the_report_is_written_and_names_what_it_did(tmp_path, monkeypatch):
    eng, s = _corpus(tmp_path, "c.db", lemma=False, monkeypatch=monkeypatch)
    mgr = _run_fold(tmp_path, eng, monkeypatch)
    report = json.loads(mgr._report_file().read_text(encoding="utf-8"))
    folds = {(e["from"], e["to"], e["lang"]) for e in report["largest_folds"]}
    assert ("studies", "study", "en") in folds
    assert ("élections", "élection", "fr") in folds
    assert report["fold"]["keywords_folded"] >= 4
    assert report["language"]["complete"] is True
    assert report["lemmatiser"]["languages"] == sorted(LEMMA_LANGS)
    assert "No article text is read" in report["method"]


def test_a_second_run_finds_nothing_to_fold(tmp_path, monkeypatch):
    """Idempotence: what makes a resumed, re-run or doubly-started job safe."""
    eng, s = _corpus(tmp_path, "c.db", lemma=False, monkeypatch=monkeypatch)
    _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    once = _mentions(s)
    mgr = _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    assert _mentions(s) == once
    tally = mgr.status()["tally"]
    assert tally.get("mentions_moved", 0) == 0 and tally.get("mentions_merged", 0) == 0


#: M10 (the delegated click-through of 2026-09-26): Portuguese forms whose lemma is not
#: itself a lemma (cooperativas -> cooperativa -> cooperativo), and the noun the seeded
#: fold filed under a verb (fila, a queue -> filar, to spin).
_PT_CHAINS = [
    ("pt1", "pt", None,
     "As cooperativas agrícolas cresceram. Cada cooperativa local e as cooperativas "
     "regionais formaram filas longas; a fila durou horas."),
    ("pt2", "pt-BR", None,
     "A cooperativa abriu novas filas. Outra cooperativa seguiu as cooperativas."),
]


def test_a_second_run_moves_nothing_even_where_the_lemma_is_not_a_lemma(tmp_path, monkeypatch):
    """M10: the seeded corpus's second fold ended "Keywords folded: 1 · mentions moved: 27",
    because the first run filed ``cooperativas`` under ``cooperativa`` and the second then
    moved ``cooperativa`` on to ``cooperativo``. ``test_a_second_run_finds_nothing_to_fold``
    stayed green through it: its fixture has no word whose lemma lemmatises again. This one
    is built from exactly such words, and the first run must already reach the fixed point."""
    eng = _engine(tmp_path, "pt.db")
    s = sessionmaker(bind=eng)()
    s.add(Source(name="Test Source", domain="src.test"))
    s.commit()
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "0")
    ex = get_extractor("baseline")
    for h, lang, det, body in _PT_CHAINS:
        a = Article(
            url=f"https://src.test/{h}", canonical_url=f"https://src.test/{h}", source_id=1,
            title="", content=body, hash=h, language=lang, detected_language=det,
            published_at=datetime(2026, 9, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.flush()
        index_article(s, a, extractor=ex)
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1")
    before = {t for t, _h, _c, _o in _mentions(s)}
    # ANTI-VACUITY: the fixture must hold a form whose lemma lemmatises again.
    assert {"cooperativas", "cooperativa"} <= before

    first = _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    once = _mentions(s)
    keys = {t for t, _h, _c, _o in once}
    # The plural and its singular end under ONE key -- which one is the installed
    # dictionary's chain (cooperativo under simplemma 1.2.0, cooperativa under 1.1).
    coop = {"cooperativas", "cooperativa", "cooperativo"} & keys
    assert len(coop) == 1, keys
    assert "filar" not in keys, "the noun 'fila' (a queue) was filed under the verb 'to spin'"
    assert "fila" in keys and "filas" not in keys, keys
    assert first.status()["tally"].get("mentions_moved", 0) > 0

    second = _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    assert _mentions(s) == once
    tally = second.status()["tally"]
    assert tally.get("mentions_moved", 0) == 0 and tally.get("mentions_merged", 0) == 0, tally
    assert tally.get("keywords_folded", 0) == 0, tally


def test_a_term_the_fold_emptied_resolves_to_the_keyword_its_mentions_went_to(tmp_path, monkeypatch):
    """Row M1 (delegated click-through 2026-09-26): after a fold and BEFORE the prune, every
    keyword surface still passes the display surface (``elections``), and the exact match
    used to land on the emptied row: "Resolved to elections · 0 mentions in 0 articles"
    beside a chip counting them. The read side must prefer the keyword that carries the
    mentions, and must not change what the fold wrote (the husk is still there)."""
    from src.analytics import queries as q

    eng, s = _corpus(tmp_path, "c.db", lemma=False, monkeypatch=monkeypatch)
    _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    husk = s.query(Keyword).filter_by(normalized_term="elections").one()
    assert s.query(KeywordMention).filter_by(keyword_id=husk.id).count() == 0, "fixture: not emptied"

    kw = q.resolve_keyword(s, "elections", exact=True)
    assert kw is not None and kw.normalized_term == "election"
    trend = q.trend(s, "elections")
    assert trend["resolved"]["normalized"] == "election"
    assert trend["total"] == q.trend(s, "election")["total"] > 0
    stats = q.keyword_stats(s, "elections")
    assert stats["mentions"] > 0
    # A keyword that still carries mentions is never swapped for its lemma.
    kept = q.resolve_keyword(s, "studies", exact=True)
    assert kept is not None and kept.normalized_term == "studies"


def test_a_paused_run_resumes_to_the_same_result_without_double_counting(tmp_path, monkeypatch):
    """Page size 1, stopped after every page and resumed from the persisted state by a NEW
    manager (a restart): the result must equal an uninterrupted run, counters included."""
    ref_eng, ref = _corpus(tmp_path, "ref.db", lemma=False, monkeypatch=monkeypatch)
    _run_fold(tmp_path, ref_eng, monkeypatch)
    ref.expire_all()

    eng, s = _corpus(tmp_path, "c.db", lemma=False, monkeypatch=monkeypatch)
    monkeypatch.setattr(keyword_fold, "_import_owns_the_machine", lambda: False)
    state = tmp_path / "state.json"
    report = tmp_path / "report.json"
    real_fold_page = keyword_fold.fold_page
    restarts = 0
    for _ in range(500):
        mgr = KeywordFoldJobManager(state_path=state, report_path=report)
        if mgr.status()["state"] == "idle" and restarts:
            break

        def _one_page_then_stop(*a, _m=mgr, **kw):
            r = real_fold_page(*a, **kw)
            _m.pause()
            return r

        monkeypatch.setattr(keyword_fold, "fold_page", _one_page_then_stop)
        mgr.start(_session_factory=sessionmaker(bind=eng), _page=1)
        mgr.join(60)
        restarts += 1
        if mgr.status()["state"] == "done":
            break
    assert restarts > 5, "the fixture never paused mid-run"
    assert mgr.status()["state"] == "done"
    s.expire_all()
    assert _mentions(s) == _mentions(ref)
    _counters_are_exact(s)


def test_the_fold_refuses_when_lemmatisation_is_off(tmp_path, monkeypatch):
    """Folding while extraction does not lemmatise would file old articles under keys new
    articles never use: the split the job exists to remove, reversed."""
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "0")
    mgr = KeywordFoldJobManager(state_path=tmp_path / "s.json", report_path=tmp_path / "r.json")
    with pytest.raises(FoldRefused) as exc:
        mgr.start()
    assert exc.value.code == REFUSED_LEMMA_OFF
    assert mgr.status()["refusal"] == REFUSED_LEMMA_OFF


def _mini(tmp_path):
    eng = _engine(tmp_path, "mini.db")
    s = sessionmaker(bind=eng)()
    s.add(Source(name="S", domain="s.test"))
    s.commit()
    return eng, s


def _art(s, h, lang=None, det=None):
    a = Article(url=f"https://s.test/{h}", canonical_url=f"https://s.test/{h}", source_id=1,
                title="", content="x", hash=h, language=lang, detected_language=det)
    s.add(a)
    s.flush()
    return a


def _kw(s, norm, **kw):
    k = Keyword(term=norm, normalized_term=norm, **kw)
    s.add(k)
    s.flush()
    return k


def _mention(s, k, a, count=1, off=0, lang=None):
    s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=count, first_offset=off, language=lang))
    k.mention_count = (k.mention_count or 0) + count
    k.article_count = (k.article_count or 0) + 1


def test_what_the_fold_never_touches(tmp_path, monkeypatch):
    """Phrases, entities, a keyword the user's families name, and a language the
    lemmatiser does not cover all keep every mention -- and no keyword row is deleted."""
    eng, s = _mini(tmp_path)
    en = _art(s, "a", "en")
    ar = _art(s, "b", "ar")
    phrase = _kw(s, "rising prices", is_ngram=True)
    entity = _kw(s, "studies", is_entity=True, entity_type="person")  # a spaCy-style entity row
    curated = _kw(s, "elections")
    stoplisted = _kw(s, "cars")  # en would give `car`, which the English stoplist refuses
    uncovered = _kw(s, "villages")  # en would give `village`; this mention is in Arabic
    _mention(s, phrase, en)
    _mention(s, entity, en)
    _mention(s, curated, en)
    _mention(s, stoplisted, en)
    _mention(s, uncovered, ar)
    s.add(KeywordFamilyOverride(normalized_term="elections", family_key="elections"))
    s.commit()
    kw_before = s.execute(text("SELECT COUNT(*) FROM keywords")).scalar()

    mgr = _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    rows = {(t, n) for t, n in s.execute(text(
        "SELECT k.normalized_term, COUNT(*) FROM keyword_mentions m JOIN keywords k ON k.id=m.keyword_id "
        "GROUP BY k.id"))}
    assert rows == {("rising prices", 1), ("studies", 1), ("elections", 1), ("cars", 1), ("villages", 1)}
    assert s.execute(text("SELECT COUNT(*) FROM keywords")).scalar() == kw_before, "a keyword row was deleted"
    tally = mgr.status()["tally"]
    assert tally["skipped_phrase"] == 1 and tally["skipped_entity"] == 1
    assert tally["skipped_curated"] == 1 and tally["unchanged"] == 1 and tally["candidates"] == 1
    assert tally.get("mentions_moved", 0) == 0 and tally.get("mentions_merged", 0) == 0


def test_the_fold_writes_the_top_without_the_shipped_stoplist_words(tmp_path, monkeypatch):
    """The stored top is made without the stoplist's words (R111 step T3): a page of moved mentions
    recomputes it the same way, so a hidden word is never written back into the top columns."""
    from src.analytics.extract import global_stopwords

    assert "the" in global_stopwords()
    eng, s = _mini(tmp_path)
    a = _art(s, "a", "en")
    b = _art(s, "b", "en")
    hid = _kw(s, "the")
    studies = _kw(s, "studies")
    study = _kw(s, "study")
    # `a`: the hidden word leads, the folded word is visible: the top moves from studies to study
    _mention(s, hid, a, count=5)
    _mention(s, studies, a, count=3)
    _mention(s, study, a, count=2)
    # `b`: the hidden word leads and `studies` folds into `study`: the visible top keeps its count
    # but moves to the target keyword, so its columns are rewritten to (study, 1, 1), never to `the`
    _mention(s, hid, b, count=4)
    _mention(s, studies, b, count=1)
    s.execute(text("UPDATE articles SET top_keyword_id=:k, top_keyword_count=1, top_keyword_tied_n=1 "
                   "WHERE id=:a"), {"k": studies.id, "a": b.id})
    s.execute(text("UPDATE articles SET top_keyword_id=:k, top_keyword_count=3, top_keyword_tied_n=1 "
                   "WHERE id=:a"), {"k": studies.id, "a": a.id})
    s.commit()

    _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    tops = {h: (k, c, n) for h, k, c, n in s.execute(text(
        "SELECT hash, top_keyword_id, top_keyword_count, top_keyword_tied_n FROM articles"))}
    assert tops["a"] == (study.id, 5, 1), "the hidden word must not return to the top"
    assert tops["b"] == (study.id, 1, 1)


def test_user_tags_follow_the_fold_and_baseline_tags_do_not(tmp_path, monkeypatch):
    eng, s = _mini(tmp_path)
    a = _art(s, "a", "en")
    src = _kw(s, "studies")
    _mention(s, src, a, count=3, off=40)
    s.add(KeywordTag(keyword_id=src.id, axis="topic", tag="science", source="user"))
    s.add(KeywordTag(keyword_id=src.id, axis="type", tag="event", source="baseline"))
    s.commit()
    _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    study = s.query(Keyword).filter_by(normalized_term="study").one()
    tags = {(t.axis, t.tag, t.source) for t in s.query(KeywordTag).filter_by(keyword_id=study.id)}
    assert ("topic", "science", "user") in tags
    assert ("type", "event", "baseline") not in tags
    # The source row keeps its own tags: nothing is deleted, the prune owns the empty row.
    assert s.query(KeywordTag).filter_by(keyword_id=src.id).count() == 2
    m = s.query(KeywordMention).filter_by(keyword_id=study.id).one()
    assert (m.count, m.first_offset) == (3, 40)


def test_an_article_with_no_language_folds_under_the_extraction_default(tmp_path, monkeypatch):
    """`index_article` extracts an article with no language as "en" (a working assumption it
    never stores). The fold must use the same assumption or it would disagree with the next
    re-index -- and the language pass must NOT count that assumption as a vote."""
    eng, s = _mini(tmp_path)
    a = _art(s, "a")  # neither asserted nor deduced
    src = _kw(s, "studies", language=None)
    _mention(s, src, a)
    s.commit()
    mgr = _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    study = s.query(Keyword).filter_by(normalized_term="study").one()
    assert s.query(KeywordMention).filter_by(keyword_id=study.id).count() == 1
    assert study.language is None, "the extraction assumption was stored as a language"
    assert mgr.status()["tally"]["lang:en"] == 1


def test_the_fold_bumps_the_corpus_epoch(tmp_path, monkeypatch):
    """Moving a mention to another keyword without changing its id is invisible to the
    rollup's id-watermark merge; only an epoch bump makes it rebuild."""
    from src.analytics.corpus_epoch import get_corpus_epoch

    eng, s = _corpus(tmp_path, "c.db", lemma=False, monkeypatch=monkeypatch)
    e0 = get_corpus_epoch(s)
    _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    assert get_corpus_epoch(s) > e0


def test_the_key_the_fold_uses_IS_the_key_extraction_uses(monkeypatch):
    """One function, two callers: extraction's own keys, recomputed through `lemma_key` from
    the un-lemmatised keys, must be exactly what the lemmatising extractor produced."""
    from src.analytics.extract import _stopset, code_token_filter_enabled

    text_en = _ARTICLES[0][3] + " " + _ARTICLES[1][3]
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "0")
    off = {t.normalized: t.count for t in BaselineExtractor().extract(text_en, language="en") if t.kind == "term"}
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1")
    on = {t.normalized: t.count for t in BaselineExtractor().extract(text_en, language="en") if t.kind == "term"}
    stop, cf = _stopset("en"), code_token_filter_enabled()
    rekeyed: dict[str, int] = {}
    for k, c in off.items():
        key = k if " " in k else lemma_key(k, "en", stop=stop, segmented=False, code_filter=cf)
        rekeyed[key] = rekeyed.get(key, 0) + c
    assert rekeyed == on


def test_the_rules_cover_exactly_the_lemmatised_languages():
    s = sessionmaker(bind=_engine_mem())()
    rules = FoldRules.build(s)
    assert set(rules.stops) == set(LEMMA_LANGS)
    assert rules.movable("studies") == {"en": "study", "nl": "studie"}
    assert rules.movable("cars") == {}, "a lemma the stoplist refuses is not a target"
    assert rules.target("studies", "ar") == "studies"


def _engine_mem():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return eng


def test_the_article_language_map_matches_index_article_and_reads_an_index(tmp_path):
    """The resolution rule (asserted, else deduced, normalised; nothing -> not a language)
    and the plan: one covering-index scan, never the article rows."""
    eng, s = _mini(tmp_path)
    ids = {h: _art(s, h, lang, det).id for h, lang, det in [
        ("a", "en-US", None), ("b", None, "fr"), ("c", "", "de"), ("d", None, None), ("e", "de", "fr"),
    ]}
    s.commit()
    m = ArticleLanguageMap(s)
    assert m.mention_language(ids["a"]) == "en"
    assert m.mention_language(ids["b"]) == "fr"
    assert m.mention_language(ids["c"]) == "de"
    assert m.mention_language(ids["d"]) is None
    assert m.mention_language(ids["e"]) == "de", "the asserted language must win over the deduced one"
    assert m.extraction_language(ids["d"]) == "en"
    assert m.extraction_language(10_000) == "en"
    plan = " ".join(str(r) for r in s.execute(text("EXPLAIN QUERY PLAN " + MAP_SQL)))
    assert "COVERING INDEX" in plan, plan
