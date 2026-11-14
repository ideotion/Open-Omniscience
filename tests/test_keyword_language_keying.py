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


# --------------------------------------------------------------------------- #
# the restore carry resolves a carried mention by the same rule
# --------------------------------------------------------------------------- #
def _carry_con(local_rows, incoming_kw, plan):
    """A bare connection holding just what the carry's keyword resolution reads."""
    import sqlite3

    from src.backup.merge import _ensure_carry_tables

    con = sqlite3.connect(":memory:")
    con.execute("ATTACH DATABASE ':memory:' AS inc")
    con.execute("CREATE TABLE main.keywords (id INTEGER PRIMARY KEY, normalized_term TEXT, language TEXT)")
    con.execute("CREATE TABLE inc.keywords (id INTEGER PRIMARY KEY, normalized_term TEXT, is_entity INTEGER)")
    con.execute("CREATE TABLE inc.keyword_mentions (keyword_id INTEGER, article_id INTEGER)")
    con.executemany("INSERT INTO main.keywords VALUES (?, ?, ?)", local_rows)
    con.executemany("INSERT INTO inc.keywords VALUES (?, ?, 0)", incoming_kw)
    _ensure_carry_tables(con)
    for aid, key_lang, kids in plan:
        con.execute("INSERT INTO temp.carry_plan (old, kw, key_lang) VALUES (?, 1, ?)", (aid, key_lang))
        con.executemany("INSERT INTO inc.keyword_mentions VALUES (?, ?)", [(k, aid) for k in kids])
    return con


def test_the_carry_files_a_mention_where_index_article_would():
    from src.backup.merge import _fill_carry_keywords

    con = _carry_con(
        # 1: Italian, lowest. 2: no language. 3: English. Plus a term only Italian holds.
        [(1, "error", "it"), (2, "error", None), (3, "error", "en"), (4, "solo", "it")],
        [(10, "error"), (11, "solo"), (12, "")],
        [
            (100, "en-GB", [10, 11]),  # English: the no-language row 2; "solo" has none
            (101, "", [10, 11]),  # unknown: plain lowest id
            (102, "-en", [10]),  # a language that normalises to nothing: only row 2
            (103, "\tEN\n", [10]),  # whitespace and case Python strips: English
            (104, "en", [12]),  # an empty term: nothing local
        ],
    )
    _fill_carry_keywords(con)
    got = dict(((o, l), n) for o, l, n in con.execute("SELECT old, lang, new FROM temp.carry_kw"))
    assert got == {
        (10, "en-GB"): 2, (11, "en-GB"): None,
        (10, ""): 1, (11, ""): 4,
        (10, "-en"): 2,
        (10, "\tEN\n"): 2,
        (12, "en"): None,
    }, got


def test_a_carry_never_reproduces_a_language_the_indexer_would_change(monkeypatch):
    import src.analytics.langdetect as ld
    from src.backup.merge import _language_resolution_moves

    ru = "Правительство России представило проект бюджета на следующий год. " * 6
    assert _language_resolution_moves("en", None, ru)  # refuted by its own script (R699)
    assert not _language_resolution_moves("ru", None, ru)
    assert not _language_resolution_moves(None, "ru", ru)  # already deduced: kept
    monkeypatch.setattr(ld, "detect_language", lambda *a, **k: "ru")
    assert _language_resolution_moves(None, None, ru)  # untagged and detectable
    monkeypatch.setattr(ld, "detect_language", lambda *a, **k: None)
    assert not _language_resolution_moves("", " ", ru)  # untagged and undetectable


def test_a_mixed_page_keeps_each_language_on_its_own_new_row(tmp_path, monkeypatch):
    # No «taxi» row exists yet; one page moves «taxis» from an untagged, an English and a
    # Spanish article. A row the untagged group created would carry no language and take
    # English and Spanish alike, so the known languages are resolved first.
    eng, s = _mini(tmp_path)
    unknown, en, es = _art(s, "u"), _art(s, "a", "en"), _art(s, "b", "es")
    taxis = _kw(s, "taxis")
    _mention(s, taxis, unknown)
    _mention(s, taxis, en, lang="en")
    _mention(s, taxis, es, lang="es")
    s.commit()

    _run_fold(tmp_path, eng, monkeypatch)
    s2 = sessionmaker(bind=eng)()
    rows = s2.execute(text(
        "SELECT a.hash, k.id, k.language FROM keyword_mentions m JOIN keywords k ON k.id = m.keyword_id"
        " JOIN articles a ON a.id = m.article_id WHERE k.normalized_term = 'taxi'"
    )).fetchall()
    by_hash = {h: (kid, lang) for h, kid, lang in rows}
    assert by_hash["a"][1] == "en" and by_hash["b"][1] == "es", by_hash
    assert by_hash["a"][0] != by_hash["b"][0], by_hash
    assert by_hash["u"][0] == min(by_hash["a"][0], by_hash["b"][0]), by_hash  # unknown: lowest id


def test_a_mixed_page_with_a_quarantined_article_keeps_languages_apart_and_counters_exact(tmp_path, monkeypatch):
    # R698 and R101 on one page: the quarantined English article's mention still moves to
    # the English row (quarantine is reversible), but adds nothing to its counters; the
    # Spanish one moves to its own row and counts there.
    eng, s = _mini(tmp_path)
    en, es = _art(s, "a", "en"), _art(s, "b", "es")
    en.quarantined = True
    taxis = _kw(s, "taxis")
    _mention(s, taxis, en, count=2, lang="en")
    taxis.mention_count -= 2  # a quarantined article's mentions are not in the counters
    taxis.article_count -= 1
    _mention(s, taxis, es, count=3, lang="es")
    s.commit()

    _run_fold(tmp_path, eng, monkeypatch)
    s2 = sessionmaker(bind=eng)()
    rows = s2.execute(text(
        "SELECT a.hash, k.language, k.mention_count, k.article_count FROM keyword_mentions m"
        " JOIN keywords k ON k.id = m.keyword_id JOIN articles a ON a.id = m.article_id"
        " WHERE k.normalized_term = 'taxi'"
    )).fetchall()
    by_hash = {h: (lang, men, arts) for h, lang, men, arts in rows}
    assert by_hash == {"a": ("en", 0, 0), "b": ("es", 3, 1)}, by_hash
    left = s2.execute(text(
        "SELECT COALESCE(SUM(mention_count), 0), COALESCE(SUM(article_count), 0) FROM keywords"
        " WHERE normalized_term = 'taxis'"
    )).one()
    assert tuple(left) == (0, 0), left
