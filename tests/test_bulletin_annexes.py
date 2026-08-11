"""The report cites by number, and the annexes are those numbers.

Maintainer ask, 2026-08-11: bundle the articles the report mentions as one `.md`
file each, named `YYYYMMDD_Article_<ref>`, with a detailed contents page, in a ZIP
named after the report, and let one button download both.

The load-bearing property is not that a ZIP appears. It is that the report's
`[0007]` and the file `…_Article_0007.md` are the SAME article — and they are only
the same because one function assigns the numbers and both sides call it. A reader
following a reference to the wrong article has no way to notice, which is why the
numbering is tested for agreement rather than for existence.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin.annexes import (
    annexes_filename,
    article_filename,
    assign_refs,
    build_annexes,
    bundle_stem,
    contents_filename,
    creation_date,
    edition_ordinal,
    report_filename,
)
from src.bulletin.render import render
from src.database.models import Article, ArticleAnalysis, Base, Source

_PERIOD = {"cadence": "weekly", "start": "2026-08-04", "end": "2026-08-11",
           "last_day": "2026-08-10", "days": 7}


def _row(aid: int, title: str, lang: str = "fr", published: str = "2026-08-05T09:30:00") -> dict:
    # PUBLISHED and COLLECTED are deliberately DIFFERENT DAYS. The naming rule is
    # precisely that a file takes the publication date and never the collection date,
    # and a fixture where the two coincide cannot tell the two apart — a mutation that
    # named files by collection date passed all 44 tests while they matched.
    return {
        "id": aid,
        "title": title,
        "url": f"https://lemonde.fr/{aid}",
        "source": {"name": "Le Monde", "domain": "lemonde.fr", "country": "fr",
                   "source_type": "news"},
        "asserted": {"published_at": published, "author": "A. Dupont",
                     "language": lang},
        "deduced": {"collected_at": "2026-08-09T18:00:00", "detected_language": lang,
                    "word_count": 420, "reading_time": 2, "sentiment": None},
        "keywords": [{"term": "retraites", "mentions": 7}],
        "places": [{"name": "Paris", "country": "fr", "kind": "city", "mentions": 3}],
        "dates": [{"date": "2026-09-01", "precision": "day", "status": "candidate"}],
        "entities": [{"name": "CGT", "class": "org", "mentions": 2}],
        "excerpt": "Le début du texte",
        "excerpt_truncated": True,
    }


def _edition(**kw) -> dict:
    base = {
        "period": dict(_PERIOD),
        # Created the day after the period closed, which is the normal case and the
        # one that makes the three dates visibly different from each other.
        "generated_at": "2026-08-11T09:00:00+00:00",
        "masthead": {"articles": 72225},
        "sections": [
            {
                "section": "cards",
                "types": [
                    {"type": "rising", "cards_found": 1, "cards_shown": 1, "cards": [
                        {"title": "retraites is rising", "summary": "s", "bucket": "rising",
                         "signal": {"metric": "mentions", "value": 7},
                         "signal_line": "metric mentions", "method": "m", "caveat": "c",
                         "n": 7, "corpus_articles": 2,
                         "article_rows": [_row(11, "Grève des retraites"), _row(12, "Suite")]},
                    ]},
                ],
            },
        ],
        "stories": {"stories": [
            {"shared_terms": ["retraites"], "articles": 2, "distinct_sources": 1,
             "sources": ["Le Monde"], "single_source": True, "article_ids": [12, 13],
             # 12 is ALSO cited by the card above: one article, one number.
             "article_rows": [_row(12, "Suite"), _row(13, "Troisième")]},
        ]},
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
#  naming
# --------------------------------------------------------------------------- #
def test_the_names_are_the_ones_that_were_asked_for():
    ed = _edition()
    assert bundle_stem(ed) == "20260811_OOS_Bulletin_Weekly"
    assert report_filename(ed) == "20260811_OOS_Bulletin_Weekly.md"
    assert annexes_filename(ed) == "20260811_OOS_Bulletin_Weekly_Annexes.zip"
    assert contents_filename(ed) == "20260811_Table_of_Contents.md"
    assert article_filename("2026-08-05T09:30:00", "0001") == "20260805_Article_0001.md"


def test_the_three_dates_come_from_three_different_facts():
    """The report is dated when it was made; an article is dated when it was
    published; the contents page describes the bundle, so it takes the bundle's date.
    Reading one of them as another is the confusion this naming exists to prevent."""
    ed = _edition()
    assert bundle_stem(ed).startswith("20260811_"), "created 2026-08-11"
    assert contents_filename(ed).startswith("20260811_"), "describes the bundle"
    assert article_filename("2019-03-02T12:00:00", "0004") == "20190302_Article_0004.md", (
        "a 2019 piece in a 2026 bulletin reads as 2019"
    )


def test_a_repeat_created_the_same_day_gets_a_number_on_every_name():
    ed = _edition()
    assert bundle_stem(ed, ordinal=2) == "20260811_OOS_Bulletin_Weekly_2"
    assert annexes_filename(ed, ordinal=2) == "20260811_OOS_Bulletin_Weekly_2_Annexes.zip"
    assert report_filename(ed, ordinal=3) == "20260811_OOS_Bulletin_Weekly_3.md"


@pytest.mark.parametrize(
    "cadence,expect",
    [("weekly", "Weekly"), ("monthly", "Monthly"), ("daily", "Daily"),
     ("trimester", "Trimester"), ("yearly", "Yearly")],
)
def test_the_cadence_is_named_not_abbreviated(cadence, expect):
    ed = _edition(period={**_PERIOD, "cadence": cadence})
    assert bundle_stem(ed).endswith(f"_OOS_Bulletin_{expect}")


def test_the_report_is_dated_when_it_was_made_not_by_the_period_it_covers():
    """An old period written up today is today's document."""
    ed = _edition(period={**_PERIOD, "last_day": "2026-07-05"})
    assert bundle_stem(ed).startswith("20260811_")


def test_the_creation_date_comes_from_the_record_so_a_re_download_keeps_its_name():
    """``now()`` would give one document two names across two days, and an operator's
    archive would gain a second copy of the same thing."""
    ed = _edition()
    assert creation_date(ed) == date(2026, 8, 11)
    assert bundle_stem(ed) == bundle_stem(ed), "stable within a run"
    # And it is the RECORD's account, not the clock's.
    assert creation_date(_edition(generated_at="2026-01-02T00:00:00")) == date(2026, 1, 2)


def test_a_record_with_no_generation_stamp_falls_back_to_today_honestly():
    """The bundle genuinely is being created now, so nothing is claimed that is not
    so — unlike a period, which the record either states or does not."""
    from datetime import UTC, datetime

    assert creation_date({"period": dict(_PERIOD)}) == datetime.now(UTC).date()
    assert creation_date(_edition(generated_at="not-a-date")) == datetime.now(UTC).date()


def test_the_ordinal_separates_bulletins_created_on_the_same_day():
    """Which is exactly the case the maintainer named: several produced the same day.
    A next-free counter would rename the same edition on every download, which is the
    opposite of what a filename is for."""
    siblings = [
        {"filename": "20260810-OOS-weekly-aaaaaaaa.json", "cadence": "weekly",
         "generated_at": "2026-08-11T09:00:00"},
        {"filename": "20260810-OOS-weekly-bbbbbbbb.json", "cadence": "weekly",
         "generated_at": "2026-08-11T16:30:00"},
        {"filename": "20260803-OOS-weekly-cccccccc.json", "cadence": "weekly",
         "generated_at": "2026-08-04T09:00:00"},
    ]
    assert edition_ordinal("20260810-OOS-weekly-aaaaaaaa.json", siblings) == 1
    assert edition_ordinal("20260810-OOS-weekly-bbbbbbbb.json", siblings) == 2
    # Twice, to make "stable" more than a claim.
    assert edition_ordinal("20260810-OOS-weekly-bbbbbbbb.json", siblings) == 2
    # A different DAY is not a repeat, even for the same cadence.
    assert edition_ordinal("20260803-OOS-weekly-cccccccc.json", siblings) == 1
    assert edition_ordinal("never-persisted", siblings) == 1
    assert edition_ordinal(None, siblings) == 1


def test_two_editions_of_different_periods_created_together_still_get_distinct_names():
    """The naming moved off the period, so two weeklies for different weeks written up
    in one afternoon share a stem — and the ordinal is the only thing standing between
    them and one filename for two documents."""
    siblings = [
        {"filename": "20260803-OOS-weekly-aaaaaaaa.json", "cadence": "weekly",
         "generated_at": "2026-08-11T09:00:00"},
        {"filename": "20260810-OOS-weekly-bbbbbbbb.json", "cadence": "weekly",
         "generated_at": "2026-08-11T09:05:00"},
    ]
    a = bundle_stem(_edition(), ordinal=edition_ordinal(siblings[0]["filename"], siblings))
    b = bundle_stem(_edition(), ordinal=edition_ordinal(siblings[1]["filename"], siblings))
    assert a != b
    assert {a, b} == {"20260811_OOS_Bulletin_Weekly", "20260811_OOS_Bulletin_Weekly_2"}


def test_a_monthly_and_a_weekly_created_on_one_day_are_not_repeats_of_each_other():
    siblings = [
        {"filename": "20260810-OOS-weekly-aaaaaaaa.json", "cadence": "weekly",
         "generated_at": "2026-08-11T09:00:00"},
        {"filename": "20260810-OOS-monthly-bbbbbbbb.json", "cadence": "monthly",
         "generated_at": "2026-08-11T09:00:00"},
    ]
    assert edition_ordinal("20260810-OOS-monthly-bbbbbbbb.json", siblings) == 1


def test_an_article_with_no_publication_date_is_named_undated_never_collected():
    """Substituting the day we happened to fetch something for the day it was
    published is precisely the conflation this naming was changed to remove."""
    assert article_filename(None, "0007") == "undated_Article_0007.md"
    assert article_filename("", "0007") == "undated_Article_0007.md"
    assert article_filename("not-a-date", "0007") == "undated_Article_0007.md"


def test_two_articles_published_the_same_day_do_not_collide():
    assert article_filename("2026-08-05", "0001") != article_filename("2026-08-05", "0002")


def test_the_bundle_names_a_file_by_publication_never_by_collection(corpus):
    """Driven through the real bundle, not the pure function, and with an article
    published in a different YEAR from the day it was collected — which is the only
    shape that can tell the two rules apart. The fixture's other articles are
    published 2026-08-05 and collected 2026-08-09, so even they discriminate."""
    ed = _edition()
    ed["sections"][0]["types"][0]["cards"][0]["article_rows"] = [
        _row(11, "Une archive", published="2019-03-02T08:00:00")
    ]
    ed["stories"]["stories"] = []
    names = list(_unzip(build_annexes(corpus, ed)))
    assert "20260811_OOS_Bulletin_Weekly/20190302_Article_0001.md" in names
    assert not any("20260809" in n for n in names), "the collection date appears nowhere"
    assert not any("20260811_Article" in n for n in names), "nor the bundle's own date"


# --------------------------------------------------------------------------- #
#  reference numbers
# --------------------------------------------------------------------------- #
def test_one_article_gets_one_number_however_often_it_is_cited():
    """The number identifies the ARTICLE, not the mention — otherwise the same text
    would arrive as two files and a reader would not know they are the same piece."""
    ed = _edition()
    index = assign_refs(ed)
    assert [e["ref"] for e in index] == ["0001", "0002", "0003"]
    twelve = next(e for e in index if e["id"] == 12)
    assert twelve["ref"] == "0002"
    assert len(twelve["cited_in"]) == 2, "cited by a card and by a story"
    assert any("rising" in w for w in twelve["cited_in"])
    assert any(w.startswith("story") for w in twelve["cited_in"])


def test_every_row_naming_an_article_carries_the_same_number():
    """The renderer prints `row["ref"]`, so a row the walk missed would render a
    citation with no number while its file existed under one."""
    ed = _edition()
    assign_refs(ed)
    card_row = ed["sections"][0]["types"][0]["cards"][0]["article_rows"][1]
    story_row = ed["stories"]["stories"][0]["article_rows"][0]
    assert card_row["id"] == story_row["id"] == 12
    assert card_row["ref"] == story_row["ref"] == "0002"


def test_numbering_is_deterministic_so_two_callers_cannot_disagree():
    a = [e["ref"] for e in assign_refs(_edition())]
    ed = _edition()
    assign_refs(ed)
    b = [e["ref"] for e in assign_refs(ed)]  # second call over an already-numbered record
    assert a == b == ["0001", "0002", "0003"]


def test_the_numbers_run_in_the_order_a_reader_meets_them():
    ed = _edition()
    index = assign_refs(ed)
    # The card section renders before the stories, so its articles are numbered first.
    assert [e["id"] for e in index] == [11, 12, 13]


def test_an_edition_that_names_no_articles_is_numbered_empty_not_guessed():
    assert assign_refs({"period": dict(_PERIOD), "sections": [], "masthead": {}}) == []


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_report_prints_the_number_and_explains_it(fmt):
    text = render(_edition(), fmt)
    assert "[0001]" in text
    assert "annex file" in text
    assert "_Annexes.zip" in text


def test_a_report_with_no_cited_articles_prints_no_legend():
    """A legend for a convention the document never uses is furniture."""
    text = render({"period": dict(_PERIOD), "masthead": {}, "sections": []}, "markdown")
    assert "annex file" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_story_names_its_own_articles(fmt):
    """FOUND BY THIS FEATURE, and it is why the reference test is written as a
    round-trip rather than as "the zip has three files".

    The previous slice added ``story["article_rows"]`` so "the document can name
    them" — and neither renderer printed them. A cluster of 115 articles arrived as a
    count with no way in, and the annexes then held files the report never cited: the
    numbering was right and the citation was missing, which is the failure a
    file-count assertion cannot see.
    """
    text = render(_edition(), fmt)
    assert "Troisième" in text, "the story's third article reaches the page"
    assert "[0003]" in text, "with its reference number"
    assert "Showing 2 of 2" in text or "Articles:" in text


# --------------------------------------------------------------------------- #
#  the bundle
# --------------------------------------------------------------------------- #
@pytest.fixture
def corpus():
    # StaticPool + check_same_thread=False because the route tests below drive this
    # same session through a TestClient, which runs a `def` handler on the threadpool.
    # Without it teardown floods stderr with cross-thread ProgrammingErrors.
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="Le Monde", domain="lemonde.fr", country="fr", source_type="news")
    s.add(src)
    s.flush()
    for aid, body in ((11, "Le corps entier de l'article onze. " * 20),
                      (12, "Le corps entier de l'article douze. " * 20),
                      (13, "Le corps entier de l'article treize. " * 20)):
        s.add(Article(
            id=aid, url=f"https://lemonde.fr/{aid}", canonical_url=f"https://lemonde.fr/{aid}",
            source_id=src.id, title=f"Article {aid}", content=body, hash=f"{aid:064d}",
            language="fr", published_at=datetime(2026, 8, 5, 9, 30), quarantined=False,
        ))
    s.add(ArticleAnalysis(article_id=11, kind="summary", result="Un résumé.",
                          model="ministral-3:8b", prompt_version="summary-v2",
                          created_at=datetime(2026, 8, 6, 8, 0)))
    s.add(ArticleAnalysis(article_id=11, kind="translation", result="An English rendering.",
                          model="ministral-3:8b", prompt_version="translate-v2:English+chunked-3",
                          created_at=datetime(2026, 8, 6, 8, 5)))
    s.commit()
    return s


def _unzip(out: dict) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(out["data"])) as zf:
        return {n: zf.read(n).decode("utf-8") for n in zf.namelist()}


def test_the_bundle_is_one_file_per_cited_article_plus_a_contents_page(corpus):
    out = build_annexes(corpus, _edition())
    names = sorted(_unzip(out))
    assert out["filename"] == "20260811_OOS_Bulletin_Weekly_Annexes.zip"
    assert out["articles"] == 3
    # Sorted by name, the articles come FIRST: they are dated by publication and this
    # week's articles predate the day the bundle was made. A consequence of dating the
    # contents page by creation, pinned here so it is a known property rather than a
    # surprise the next reader has to work out.
    assert names == [
        "20260811_OOS_Bulletin_Weekly/20260805_Article_0001.md",
        "20260811_OOS_Bulletin_Weekly/20260805_Article_0002.md",
        "20260811_OOS_Bulletin_Weekly/20260805_Article_0003.md",
        "20260811_OOS_Bulletin_Weekly/20260811_Table_of_Contents.md",
    ]


def test_the_files_sit_in_a_folder_so_two_bundles_unzip_side_by_side(corpus):
    """Two bundles for the same period differ only by the ordinal in the ZIP name; if
    their members were at the top level, unzipping both into one directory would
    silently overwrite the first one's articles."""
    a = _unzip(build_annexes(corpus, _edition(), ordinal=1))
    b = _unzip(build_annexes(corpus, _edition(), ordinal=2))
    assert not set(a) & set(b)
    assert all(n.startswith("20260811_OOS_Bulletin_Weekly/") for n in a)
    assert all(n.startswith("20260811_OOS_Bulletin_Weekly_2/") for n in b)


def test_the_reference_in_the_report_opens_the_file_of_the_same_article(corpus):
    """The one property the whole feature rests on."""
    ed = _edition()
    report = render(ed, "markdown")
    files = _unzip(build_annexes(corpus, ed))

    # Every reference the report prints resolves to a file, and that file is about
    # the article the report was citing.
    import re

    for ref in sorted(set(re.findall(r"`\[(\d{4})\]`", report))):
        name = f"20260811_OOS_Bulletin_Weekly/20260805_Article_{ref}.md"
        assert name in files, f"the report cites {ref} and no such annex exists"
        body = files[name]
        assert f"# {ref} · " in body
        assert f"cited there as `[{ref}]`" in body
    assert len(set(re.findall(r"`\[(\d{4})\]`", report))) == 3


def test_an_article_file_keeps_the_two_classes_of_fact_apart(corpus):
    files = _unzip(build_annexes(corpus, _edition()))
    body = files["20260811_OOS_Bulletin_Weekly/20260805_Article_0001.md"]
    a = body.index("## What the source asserted")
    d = body.index("## What this app deduced")
    assert a < d
    assert "A. Dupont" in body[a:d], "the byline is the source's"
    assert "420" in body[d:], "the word count is this app's"
    assert "not measured" in body, "an absent sentiment is absent, never neutral"
    assert "never confirmed" in body


def test_the_stored_model_text_is_labelled_and_carries_its_provenance(corpus):
    files = _unzip(build_annexes(corpus, _edition()))
    body = files["20260811_OOS_Bulletin_Weekly/20260805_Article_0001.md"]
    assert "AI-derived — unreliable" in body
    assert "Un résumé." in body
    assert "An English rendering." in body
    assert "Translation into English" in body, (
        "the target comes out of prompt_version, with the +chunked suffix stripped"
    )
    assert "chunked-3" not in body.split("Translation into")[1][:40]
    assert "ministral-3:8b" in body


def test_the_article_files_carry_the_full_stored_text(corpus):
    files = _unzip(build_annexes(corpus, _edition()))
    body = files["20260811_OOS_Bulletin_Weekly/20260805_Article_0001.md"]
    assert body.count("Le corps entier de l'article onze.") == 20, "all of it, not the excerpt"
    assert "## The article, as stored" in body


def test_an_excerpt_only_bundle_says_so_rather_than_looking_complete(corpus):
    out = build_annexes(corpus, _edition(), full_text=False)
    files = _unzip(out)
    toc = files["20260811_OOS_Bulletin_Weekly/20260811_Table_of_Contents.md"]
    body = files["20260811_OOS_Bulletin_Weekly/20260805_Article_0001.md"]
    assert out["full_text"] is False
    assert "EXCERPT ONLY" in toc
    assert "Le début du texte" in body
    assert body.count("Le corps entier") == 0


def test_the_text_budget_degrades_loudly_and_names_the_boundary(corpus):
    """A bundle quietly holding excerpts where it promised full text would be worse
    than a large download."""
    out = build_annexes(corpus, _edition(), text_budget_bytes=800)
    files = _unzip(out)
    toc = files["20260811_OOS_Bulletin_Weekly/20260811_Table_of_Contents.md"]
    assert out["text_truncated_from"] is not None
    assert "reached its text budget" in toc
    later = files["20260811_OOS_Bulletin_Weekly/20260805_Article_0003.md"]
    assert "reached its text budget" in later, "the affected file says so itself"


def test_a_body_that_cannot_be_read_still_leaves_a_file(corpus, monkeypatch):
    """The reference must resolve even when the text does not — a missing file would
    make the report cite something that is not there."""
    monkeypatch.setattr(
        "src.bulletin.articles.article_bodies",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("codec exploded")),
    )
    ed = _edition()
    for rows in (ed["sections"][0]["types"][0]["cards"][0]["article_rows"],
                 ed["stories"]["stories"][0]["article_rows"]):
        for r in rows:
            r["excerpt"] = ""
    files = _unzip(build_annexes(corpus, ed))
    assert len(files) == 4
    assert "No text is included" in files[
        "20260811_OOS_Bulletin_Weekly/20260805_Article_0001.md"
    ]


def test_the_contents_page_is_a_table_that_says_where_each_article_is_cited(corpus):
    toc = _unzip(build_annexes(corpus, _edition()))[
        "20260811_OOS_Bulletin_Weekly/20260811_Table_of_Contents.md"
    ]
    assert "| # | file | title | source | published | cited in |" in toc
    assert "`20260805_Article_0002.md`" in toc
    assert "story · retraites" in toc
    assert "cards · rising · retraites is rising" in toc
    assert "With a stored model summary" in toc and "With a stored model translation" in toc
    assert "1" in toc


def test_the_contents_page_states_that_this_is_other_peoples_text(corpus):
    """The report reads on its own; the annexes hold the sources. Saying so is what
    makes the bundle honest about what an operator is now holding."""
    toc = _unzip(build_annexes(corpus, _edition()))[
        "20260811_OOS_Bulletin_Weekly/20260811_Table_of_Contents.md"
    ]
    assert "published by other people" in toc
    assert "encrypted at rest and this ZIP is not" in toc
    assert "each publisher's terms" in toc


def test_an_edition_naming_no_articles_produces_an_honest_empty_bundle(corpus):
    out = build_annexes(corpus, {"period": dict(_PERIOD), "masthead": {}, "sections": []})
    files = _unzip(out)
    assert out["articles"] == 0
    assert list(files) == ["20260811_OOS_Bulletin_Weekly/20260811_Table_of_Contents.md"]
    assert "nothing to annex" in files[
        "20260811_OOS_Bulletin_Weekly/20260811_Table_of_Contents.md"
    ]


def test_a_quarantined_article_never_reaches_the_bundle(corpus):
    """It is excluded from every figure in the edition, so its text must not arrive
    through the annexes instead."""
    corpus.query(Article).filter(Article.id == 11).one().quarantined = True
    corpus.commit()
    files = _unzip(build_annexes(corpus, _edition()))
    # The reference still resolves (the record cited it), but no stored text arrives.
    body = files["20260811_OOS_Bulletin_Weekly/20260805_Article_0001.md"]
    assert body.count("Le corps entier de l'article onze.") == 0


# --------------------------------------------------------------------------- #
#  one button, two files
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch, corpus):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_LLM_ALLOW_IMPRACTICAL_HW", "1")

    from src.api.main import app
    from src.bulletin.period import resolve_period
    from src.bulletin.store import persist_edition
    from src.database.session import get_db

    name = persist_edition(_edition(), resolve_period("weekly", end=date(2026, 8, 11))).name

    def _db():
        yield corpus

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            yield c, name
    finally:
        app.dependency_overrides.clear()


def test_the_report_downloads_under_its_own_name_not_the_records(client):
    c, name = client
    r = c.get(f"/api/bulletin/editions/{name}/render?fmt=markdown")
    assert r.status_code == 200, r.text
    assert 'filename="20260811_OOS_Bulletin_Weekly.md"' in r.headers["content-disposition"]


def test_the_annexes_download_as_a_zip_named_after_the_report(client):
    c, name = client
    r = c.get(f"/api/bulletin/editions/{name}/annexes")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="20260811_OOS_Bulletin_Weekly_Annexes.zip"' in r.headers[
        "content-disposition"
    ]
    assert r.headers["X-OO-Annex-Articles"] == "3"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert len(zf.namelist()) == 4


def test_the_annexes_honour_the_same_selection_as_the_report(client):
    """The numbers are assigned over the document as published. A bundle built without
    the operator's exclusions would number a different set, and `[0001]` in the report
    would open the wrong article."""
    c, name = client
    q = "exclude_sections=cards"
    report = c.get(f"/api/bulletin/editions/{name}/render?fmt=markdown&{q}").text
    zipped = c.get(f"/api/bulletin/editions/{name}/annexes?{q}")
    assert zipped.headers["X-OO-Annex-Articles"] == "2", "the card's own article is gone"

    import re

    refs = sorted(set(re.findall(r"`\[(\d{4})\]`", report)))
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as zf:
        files = set(zf.namelist())
    for ref in refs:
        assert f"20260811_OOS_Bulletin_Weekly/20260805_Article_{ref}.md" in files


def test_an_unknown_edition_is_a_404_not_an_empty_zip(client):
    c, _ = client
    assert c.get("/api/bulletin/editions/nope.json/annexes").status_code == 404
    assert c.get("/api/bulletin/editions/..%2Fx.json/annexes").status_code in (400, 404)


def test_the_annexes_route_never_writes_the_numbering_into_the_record(client):
    """`assign_refs` stamps rows in memory. Persisting that would put a presentation
    detail into a record of measurements."""
    c, name = client
    c.get(f"/api/bulletin/editions/{name}/annexes")
    c.get(f"/api/bulletin/editions/{name}/render?fmt=markdown")
    saved = json.dumps(c.get(f"/api/bulletin/editions/{name}").json())
    assert '"ref"' not in saved
