"""Field test 2026-11-14, rows 62 (keyword tokenizer) and 63 (dates), under ruling R727.

Row 63: "১৮৮২ সালের ২৪শে মার্চ" (24 March 1882) was stored as 2027-03-24, and 8-20% of the
sampled dates fell in the year after publication. Two causes, both pinned here: the Bengali
YEAR-FIRST form was not read (the year was skipped, so the anchored no-year path placed the day
near the publication date), and a date written without a year could resolve up to 183 days
AFTER publication. R727: it resolves within 183 days before or 92 days after, otherwise not at
all; the deduced year is a stored, displayed fact ("year inferred"); and only a trustworthy
publication date anchors.

Row 62: the keyword tokenizer kept Devanagari, Bengali and Arabic combining marks only, so
Tamil, Telugu, Gurmukhi, Myanmar, Khmer (and more) keywords were cut at every vowel sign or
virama (bbc Tamil's top keyword read அவர for அவர்).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import _WORD_RE
from src.analytics.managed import UNSEGMENTED, language_status
from src.database.models import Article, ArticleMentionedDate, Base, Source
from src.timemap import datestore
from src.timemap.dateextract import extract_dates, publication_anchor

ANCHOR = date(2026, 11, 14)  # the field test's own publication anchor
TODAY = date(2026, 11, 16)


def _dates(text, lang="bn", anchor=ANCHOR):
    return [(c["date"], c["year_inferred"]) for c in extract_dates(text, today=TODAY, anchor=anchor, language=lang)]


# ---- row 63: the Bengali year-first form ------------------------------------- #

@pytest.mark.parametrize("lang", ["bn", None, "en"])
def test_bengali_year_first_dates_keep_their_own_year(lang):
    # The two field-test cases, verbatim. Bengali-script year words need no language gate.
    assert _dates("তিনি ১৮৮২ সালের ২৪শে মার্চ জন্মগ্রহণ করেন।", lang) == [("1882-03-24", False)]
    assert _dates("১৯৭১ সালের ২৫ মার্চ রাতে", lang) == [("1971-03-25", False)]


def test_a_refused_year_first_year_is_never_replaced_by_a_guess():
    # Year 999 is below the extractor's floor: the date is refused, and the claimed span stops the
    # no-year path from placing "২৫ মার্চ" near the publication date instead.
    assert _dates("৯৯৯ সালের ২৫ মার্চ") == []
    assert _dates("০৯৯৯ সালের ২৫ মার্চ") == []


def test_the_digit_year_forms_already_read_stay_read():
    # The report's first cause (Bengali digits) was not the cause: day-first with the year after parses.
    assert _dates("২৪ মার্চ ১৯৭১") == [("1971-03-24", False)]


# ---- row 63 / R727: the year-less window ------------------------------------- #

def test_a_year_less_date_no_longer_lands_a_season_ahead():
    # 24 March: last March is 235 days back, next March 130 days ahead -> neither window.
    assert _dates("The meeting is on 24 March.", "en") == []
    assert _dates("Заседание 15 марта.", "ru") == []


def test_the_window_is_183_days_back_and_92_ahead():
    a = date(2026, 6, 10)
    # 92 days ahead resolves, 93 does not.
    assert _dates("on 10 September", "en", anchor=a) == [("2026-09-10", True)]
    assert _dates("on 11 September", "en", anchor=a) == []
    # 183 days back resolves, 184 does not.
    assert (a - date(2025, 12, 9)).days == 183
    assert _dates("on 9 December", "en", anchor=a) == [("2025-12-09", True)]
    assert _dates("on 8 December", "en", anchor=a) == []


def test_a_near_future_and_a_recent_past_still_resolve():
    assert _dates("on 3 February", "en") == [("2027-02-03", True)]
    assert _dates("on 20 May", "en") == [("2026-05-20", True)]


def test_every_anchored_date_says_its_year_was_inferred_and_no_explicit_one_does():
    assert _dates("yesterday", "en") == [("2026-11-13", True)]
    assert _dates("On 11 September 2001 the towers fell.", "en") == [("2001-09-11", False)]
    # The same date written once with its year and once without keeps the explicit reading.
    assert _dates("on 20 May 2026, and again on 20 May", "en") == [("2026-05-20", False)]


def test_no_anchor_means_no_year_deduction():
    assert _dates("on 3 February", "en", anchor=None) == []
    assert _dates("yesterday", "en", anchor=None) == []


# ---- R727: only a trustworthy publication date anchors ------------------------ #

def test_publication_anchor():
    stored = datetime(2026, 11, 14, 9, tzinfo=UTC)
    assert publication_anchor(None, stored) is None  # the storing time is not a publication date
    assert publication_anchor(datetime(2026, 11, 13, tzinfo=UTC), stored) == date(2026, 11, 13)
    assert publication_anchor(datetime(2026, 11, 15, tzinfo=UTC), stored) == date(2026, 11, 15)  # a day of clock slack
    assert publication_anchor(datetime(2026, 11, 16, tzinfo=UTC), stored) is None  # published after it was stored
    assert publication_anchor(date(2001, 9, 11)) == date(2001, 9, 11)


# ---- the stored flag and where it is read ------------------------------------ #

def _session(tmp_path, *, published_at):
    engine = create_engine(f"sqlite:///{tmp_path / 'y.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        s.add(
            Article(
                url="https://wire.test/a", canonical_url="https://wire.test/a", source_id=1, title="t", hash="h1",
                language="en", content="Talks resume on 20 May 2026. The vote is on 3 February.",
                published_at=published_at, created_at=datetime(2026, 11, 14, 12, tzinfo=UTC),
            )
        )
        s.commit()
    return Sess


def test_the_store_records_the_inferred_year_and_reads_it_back(tmp_path):
    Sess = _session(tmp_path, published_at=datetime(2026, 11, 14, tzinfo=UTC))
    with Sess() as db:
        datestore.store_for_article(db, db.get(Article, 1), today=TODAY)
        rows = {t["date"]: t for t in datestore.for_article(db, 1)}
        assert rows["2026-05-20"]["year_inferred"] is False
        assert rows["2027-02-03"]["year_inferred"] is True
        ext = {t.mentioned_on.isoformat(): t.extractor for t in db.query(ArticleMentionedDate)}
        assert ext["2027-02-03"] == "dateextract:year-inferred"
        assert ext["2026-05-20"] == "dateextract"
        assert all(len(e) <= 40 for e in ext.values())  # the column is String(40)
        by_date = datestore.articles_for_date(db, date_str="2027-02-03")
        assert by_date and by_date[0]["year_inferred"] is True
        # A re-run is idempotent: same rows, same labels.
        assert datestore.store_for_article(db, db.get(Article, 1), today=TODAY) == 0
        assert {t.mentioned_on.isoformat(): t.extractor for t in db.query(ArticleMentionedDate)} == ext


def test_an_article_without_a_publication_date_gets_only_its_explicit_dates(tmp_path):
    Sess = _session(tmp_path, published_at=None)
    with Sess() as db:
        datestore.store_for_article(db, db.get(Article, 1), today=TODAY)
        assert [t["date"] for t in datestore.for_article(db, 1)] == ["2026-05-20"]


def test_the_agenda_counts_the_articles_whose_year_was_inferred(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'g.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    today = date.today()
    soon = today + timedelta(days=10)
    with Sess() as s:
        s.add(Source(name="A", domain="a.test"))
        s.commit()
        for i, ext in enumerate(["dateextract", "dateextract:year-inferred", "dateextract:no-language:year-inferred"], 1):
            s.add(Article(url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=1, title="t", content="c",
                          hash=f"h{i}", language="en", created_at=datetime.now(UTC)))
            s.flush()
            s.add(ArticleMentionedDate(article_id=i, mentioned_on=soon, precision="day", extractor=ext))
        s.commit()
        ev = datestore.upcoming_deduced(s, today=today)["events"]
        assert len(ev) == 1 and ev[0]["n_articles"] == 3 and ev[0]["n_year_inferred"] == 2


def test_the_agenda_and_reader_show_the_flag():
    from pathlib import Path

    js = Path("src/static/app-agenda.js").read_text(encoding="utf-8")
    assert "n_year_inferred" in js and "r.year_inferred" in js
    assert 'T("year inferred")' in js
    py = Path("src/api/main.py").read_text(encoding="utf-8")
    assert "year inferred" in py and 't.get("year_inferred")' in py


# ---- row 62: the tokenizer keeps every combining mark ------------------------ #

@pytest.mark.parametrize(
    "text, words",
    [
        ("அவர் சொன்னார் அரசாங்கம்", ["அவர்", "சொன்னார்", "அரசாங்கம்"]),  # Tamil
        ("ప్రభుత్వం నిర్ణయం", ["ప్రభుత్వం", "నిర్ణయం"]),  # Telugu
        ("સરકાર નિર્ણય", ["સરકાર", "નિર્ણય"]),  # Gujarati
        ("ಸರ್ಕಾರ ನಿರ್ಧಾರ", ["ಸರ್ಕಾರ", "ನಿರ್ಧಾರ"]),  # Kannada
        ("സർക്കാർ തീരുമാനം", ["സർക്കാർ", "തീരുമാനം"]),  # Malayalam
        ("ਸਰਕਾਰ ਨੇ ਕਿਹਾ", ["ਸਰਕਾਰ", "ਨੇ", "ਕਿਹਾ"]),  # Gurmukhi
        ("ସରକାର ନିଷ୍ପତ୍ତି", ["ସରକାର", "ନିଷ୍ପତ୍ତି"]),  # Odia
        ("ကျွန်တော် မြန်မာ", ["ကျွန်တော်", "မြန်မာ"]),  # Myanmar
        ("រដ្ឋាភិបាល កម្ពុជា", ["រដ្ឋាភិបាល", "កម្ពុជា"]),  # Khmer
    ],
)
def test_combining_marks_stay_inside_their_word(text, words):
    assert [m.group(0) for m in _WORD_RE.finditer(text)] == words


def test_text_without_marks_tokenises_exactly_as_before():
    old = r"[^\W\d_][\w'’\-]*"
    import re

    for text in ("The O'Neill-led talks resumed in Zürich", "Президент заявил", "सरकार", "café naïve"):
        if not any(0x300 <= ord(c) <= 0x36F or 0x900 <= ord(c) <= 0x9FF for c in text):
            assert [m.group(0) for m in _WORD_RE.finditer(text)] == re.findall(old, text)
    # A mark never STARTS a token.
    assert [m.group(0) for m in _WORD_RE.finditer("் அவர்")] == ["அவர்"]


def test_space_less_scripts_without_a_segmenter_are_reported_unsegmented():
    assert {"km", "lo", "my", "bo"} <= UNSEGMENTED
    for lang in ("km", "lo", "my", "bo"):
        assert language_status(lang) == "unsegmented"


# ---- the /api/keywords text processor keeps script marks, and only those ----------- #

def test_text_processor_keeps_script_marks_and_no_symbol_or_emoji_marks():
    from src.services.text_processor import TextProcessor

    t = TextProcessor()
    import unicodedata

    # The processor folds with NFKD, so the expectation is folded too (a Tamil vowel sign decomposes into two marks).
    assert t.tokenize("அவர் சொன்னார் सरकार") == [unicodedata.normalize("NFKD", w) for w in ("அவர்", "சொன்னார்", "सरकार")]
    assert t.tokenize("Step 1️⃣ then 2️⃣") == ["step", "then"]  # a keycap emoji is no keyword
    assert t.tokenize("vector v⃗ and ab᷄cd") == ["vector", "and", "ab", "cd"]  # symbol and Latin-extension marks
    # The Latin folding is what main does, unchanged (its "naïve" split is older than this fix and not its subject).
    assert t.tokenize("café naïve") == ["cafe", "nai", "ve"]
