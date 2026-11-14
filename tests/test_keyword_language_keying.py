"""A keyword row recorded in one language never takes another language's mention (R698).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

M11 (OPEN_QUEUE, deferred from the 2026-09-27 fixes): keys are spelled language-agnostically,
so the fold merged English «errors» and Spanish «errores» into one key «error», and the Q414
majority vote then labelled the shared row Spanish -- a row reporting one language for counts
drawn from two. R698 (= RN2 (a)): the mention goes to the term's row in its own language, or
to a row with no language yet, and one is created when neither exists. Extraction and the
fold apply the same rule, so the fold still keys a mention exactly as a re-index would.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import ExtractedTerm
from src.analytics.store import index_article
from src.database.models import Keyword
from tests.test_keyword_fold import _art, _kw, _mention, _mini, _run_fold
from tests.test_mention_diff_write import _article, _session


class _Ex:
    name = "fake"

    def __init__(self, *terms):
        self.terms = [ExtractedTerm(term=t, normalized=t, kind="term", count=1, first_offset=0) for t in terms]

    def extract(self, text, language=None, **kw):
        return list(self.terms)


def _rows_by_term(s, term):
    return sorted(
        (k.id, k.language, k.mention_count)
        for k in s.query(Keyword).filter(Keyword.normalized_term == term)
    )


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
def test_a_spanish_mention_does_not_join_the_english_row():
    s = _session()
    en = _article(s, "en", language="en")
    es = _article(s, "es", language="es")
    index_article(s, en, extractor=_Ex("error"))
    index_article(s, es, extractor=_Ex("error"))
    s.commit()
    rows = _rows_by_term(s, "error")
    assert [lang for _id, lang, _n in rows] == ["en", "es"], rows
    assert all(n == 1 for _id, _l, n in rows)


def test_a_region_tag_is_the_same_language():
    s = _session()
    index_article(s, _article(s, "a", language="en"), extractor=_Ex("error"))
    index_article(s, _article(s, "b", language="en-GB"), extractor=_Ex("error"))
    s.commit()
    assert len(_rows_by_term(s, "error")) == 1


def test_a_row_with_no_language_takes_any_and_an_unknown_article_takes_the_lowest():
    s = _session()
    index_article(s, _article(s, "u", language=None), extractor=_Ex("error"))  # row with no language
    index_article(s, _article(s, "f", language="fr"), extractor=_Ex("error"))
    index_article(s, _article(s, "u2", language=None), extractor=_Ex("error"))
    s.commit()
    rows = _rows_by_term(s, "error")
    assert len(rows) == 1 and rows[0][2] == 3, rows


def test_two_language_rows_each_keep_their_own_mentions_on_re_index():
    s = _session()
    en = _article(s, "en", language="en")
    es = _article(s, "es", language="es")
    for a in (en, es, en, es):  # the second pass is a re-index: nothing may move
        index_article(s, a, extractor=_Ex("error"))
    s.commit()
    rows = _rows_by_term(s, "error")
    assert [(lang, n) for _id, lang, n in rows] == [("en", 1), ("es", 1)], rows


# --------------------------------------------------------------------------- #
# the fold
# --------------------------------------------------------------------------- #
def test_the_fold_files_errores_under_a_spanish_error_not_the_english_one(tmp_path, monkeypatch):
    eng, s = _mini(tmp_path)
    en, es = _art(s, "a", "en"), _art(s, "b", "es")
    english = _kw(s, "error", language="en")
    _mention(s, english, en, lang="en")
    errores = _kw(s, "errores", language="es")
    _mention(s, errores, es, lang="es")
    s.commit()

    _run_fold(tmp_path, eng, monkeypatch)
    s2 = sessionmaker(bind=eng)()
    rows = s2.execute(text(
        "SELECT k.normalized_term, k.language, m.language FROM keyword_mentions m "
        "JOIN keywords k ON k.id = m.keyword_id ORDER BY m.article_id"
    )).fetchall()
    assert [tuple(r) for r in rows] == [("error", "en", "en"), ("error", "es", "es")], rows
    english_after = s2.get(Keyword, english.id)
    assert english_after.mention_count == 1 and english_after.language == "en"
