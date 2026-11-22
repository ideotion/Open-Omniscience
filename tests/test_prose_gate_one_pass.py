"""The prose gate gives the verdicts it gave before it was made faster (the import's junk screen).

The import's screening of newly merged articles took 3,396 s for 258,903 articles on a field run
(2026-11-15). Most of the judging cost was the gate tokenizing each body three times, testing every
token against every language's function-word set, and walking every character in Python to rule out
an unsegmented script. ``src/services/prose_gate.py`` now tokenizes once, counts from one tally of the
distinct tokens, and counts characters with C-level calls. Nothing it decides may move: the reference
below is the previous implementation, kept verbatim, and every verdict, density and script answer is
compared on generated text in many scripts and languages, nav soup included.
"""

from __future__ import annotations

import random

import pytest

from src.analytics.managed import MANAGED_LANGUAGES, UNSEGMENTED, normalize_lang
from src.services import prose_gate as pg
from src.services.stopwords import stopwords_manager
from tests._app_engine import app_sqlite_engine

# --- the previous implementation, verbatim (the reference this change must match) ---------------


def _old_is_unsegmented_script(text, *, threshold=pg._UNSEGMENTED_SCRIPT_SHARE):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    cjk = sum(1 for c in letters if pg._CJK_THAI_RE.match(c))
    return (cjk / len(letters)) >= threshold


def _old_function_word_density(text, *, language=None):
    tokens = pg.tokenize_words(text)
    if not tokens:
        return 0.0, None
    n = len(tokens)
    lang = normalize_lang(language) if language else None
    candidates = [lang] if lang else sorted(MANAGED_LANGUAGES)
    best_density = 0.0
    best_lang = None
    for cand in candidates:
        if not cand:
            continue
        stops = stopwords_manager.get_grammar_stopwords(cand)
        hits = sum(1 for t in tokens if t in stops)
        density = hits / n
        if density > best_density or best_lang is None:
            best_density = density
            best_lang = cand
    return round(best_density, 4), best_lang


def _old_sentence_punct_density(text):
    tokens = pg.tokenize_words(text)
    if not tokens:
        return 0.0
    hits = len(pg._SENTENCE_PUNCT_RE.findall(text or ""))
    return round(hits / len(tokens), 4)


def _old_verdict(text, *, language=None):
    tokens = pg.tokenize_words(text)
    if len(tokens) < pg._MIN_TOKENS:
        return None
    lang = normalize_lang(language) if language else None
    if lang in UNSEGMENTED:
        return None
    if lang is None and _old_is_unsegmented_script(text or ""):
        return None
    if lang and not stopwords_manager.get_grammar_stopwords(lang):
        return None
    density, best_lang = _old_function_word_density(text, language=lang)
    punct = _old_sentence_punct_density(text)
    if lang is None and density == 0.0:
        return None
    if density < pg._DENSITY_LOW and punct < pg._PUNCT_LOW:
        return (
            "nav_soup",
            "word-rich nav/listing chrome, not prose: low function-word density "
            f"(best-matching language '{best_lang or lang or 'unknown'}') AND near-zero "
            "sentence-ending punctuation",
        )
    return None


# --- generated text --------------------------------------------------------------------------------

_ODD = ["Government", "İstanbul", "straße", "ÉTAT", "中国政府", "表示", "ภาษาไทย", "๑๒๓", "กรุงเทพ",
        "ー", "・", "नमस्ते", "مرحبا", "Привет", "123", "foo_bar", "x2y", "Ǆ", "ﬁ", "䷀"]
_CONTENT = ["News", "Sport", "Golf", "Rugby", "Bingo", "Markets", "Weather", "Politika", "Wirtschaft",
            "Économie", "Deportes", "Спорт", "Gallery", "Podcast", "Login", "Menu"]
_PUNCT = ["", "", " .", ". ", "!", "?", ",", ";", "...", "\n"]
_LANGS = [None, "en", "fr", "zh", "ja", "th", "sr", "az", "EN", "fr-FR", "xx", "cs", "de"]


def _texts():
    rnd = random.Random(20261116)
    pool = list(_ODD)
    for lang in sorted(MANAGED_LANGUAGES):
        pool += sorted(stopwords_manager.get_grammar_stopwords(lang))[:40]
    out: list[str | None] = ["", None, "中国政府周二表示将审查该政策" * 10, "ภาษาไทย๑๒๓ " * 40]
    for _ in range(700):  # prose-like: any mix of words and punctuation
        n = rnd.choice([0, 3, 19, 20, 21, 50, 200])
        out.append(" ".join(rnd.choice(pool) + rnd.choice(_PUNCT) for _ in range(n)))
    for _ in range(500):  # menu-like: mostly content words, rarely a full stop (the nav-soup corner)
        n = rnd.choice([20, 25, 60, 150])
        share = rnd.choice([0.0, 0.05, 0.1, 0.13, 0.2])
        out.append(" ".join(
            (rnd.choice(pool) if rnd.random() < share else rnd.choice(_CONTENT))
            + ("." if rnd.random() < 0.012 else "")
            for _ in range(n)
        ))
    return out


_TEXTS = _texts()
_ALL_LANGS = _LANGS + sorted(MANAGED_LANGUAGES)


def _as_tuple(v):
    return None if v is None else (v.signal, v.reason)


def test_every_verdict_is_the_one_the_previous_gate_gave():
    rnd = random.Random(7)
    nav_soup = 0
    for text in _TEXTS:
        for lang in [None, *rnd.sample(_ALL_LANGS, 3)]:
            got = _as_tuple(pg.prose_gate_verdict(text, language=lang))
            assert got == _old_verdict(text, language=lang), (repr(text)[:80], lang)
            nav_soup += got is not None
    assert nav_soup > 300, "the generated text must reach the nav-soup verdict, or the comparison proves little"


def test_the_measures_and_the_script_check_are_unchanged():
    rnd = random.Random(11)
    for text in _TEXTS:
        for lang in [None, *rnd.sample(_ALL_LANGS, 2)]:
            assert pg.function_word_density(text, language=lang) == _old_function_word_density(text, language=lang)
        assert pg.sentence_punct_density(text) == _old_sentence_punct_density(text)
        if text is not None:
            for threshold in (0.3, 0.0, 1.0):
                assert pg._is_unsegmented_script(text, threshold=threshold) == _old_is_unsegmented_script(
                    text, threshold=threshold
                ), (repr(text)[:60], threshold)


@pytest.mark.parametrize("text", ["ภาษาไทย๑๒๓", "๑๒๓ abc", "䷀䷁ abc", "・・ー abc", ""])
def test_a_non_letter_in_the_cjk_thai_range_is_not_counted_as_a_letter(text):
    assert pg._is_unsegmented_script(text) == _old_is_unsegmented_script(text)


def test_the_screening_result_says_where_its_time_went(tmp_path):
    from sqlalchemy.orm import sessionmaker

    from src.analytics.quarantine_job import default_quarantine_candidates_batch
    from src.database.models import Article, Base, Source

    engine = app_sqlite_engine(tmp_path / 'q.db', future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        for i in range(3):
            url = f"https://x.test/2026/11/{i}/story"
            s.add(Article(url=url, canonical_url=url, source_id=1, content="The cat sat on the mat. " * 30,
                          hash=f"h{i}", word_count=180, language="en", title="t"))
        s.commit()
        ids = [r[0] for r in s.query(Article.id)]
        for kwargs in ({"article_ids": ids}, {"after_id": 0}):
            r = default_quarantine_candidates_batch(s, **kwargs)
            assert r["scanned"] == 3
            assert isinstance(r["read_s"], float) and r["read_s"] >= 0.0
            assert isinstance(r["classify_s"], float) and r["classify_s"] >= 0.0
