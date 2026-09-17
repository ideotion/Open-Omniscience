"""Q511 — the bulletin uses the ring, and the annexe that says which rings it used.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two halves. ``country_coverage`` listed `climate` and `climat` as two smaller things and
did it hardest in exactly the corpora the section exists to describe — the multilingual
ones. And the note asks for the ring analytics as their own annexe: in this codebase an
"annexe" is one companion ZIP per edition, so that is a new Markdown member beside the
per-article files.

What is pinned is mostly what the merge may NOT do. A merged row's article count is the
one number that three plausible implementations get wrong in three different directions —
a sum over-reports, a ``max()`` is a floor wearing a count's name, and the pre-merge
top-N cut silently drops the members that make the merge worth doing.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.bulletin.annexes import concepts_markdown
from src.bulletin.coverage import _terms
from src.bulletin.period import Period
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def corpus(tmp_path):
    """Two ring members and one article that carries BOTH — the overlap, seeded.

    Without that article a sum, a max and the true union all agree and the test cannot
    tell which one the code computed.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bulletin_rings.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    day = date.today() - timedelta(days=1)
    with Session() as s:
        src = Source(name="s", rss_url="https://x.test/f", domain="x.test")
        s.add(src)
        s.flush()
        arts = []
        for i in range(4):
            when = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
            a = Article(title=f"t{i}", content="x", url=f"https://x.test/{i}",
                        canonical_url=f"https://x.test/{i}", source_id=src.id,
                        language="en", published_at=when, created_at=when, hash=f"h{i}")
            s.add(a)
            s.flush()
            arts.append(a)
        kws = {}
        for term, lang in (("climate", "en"), ("climat", "fr"), ("football", "en")):
            k = Keyword(term=term, normalized_term=term, language=lang)
            s.add(k)
            s.flush()
            kws[term] = k
        def mention(kw, art, n):
            s.add(KeywordMention(keyword_id=kw.id, article_id=art.id, source_id=src.id,
                                 observed_on=day, count=n))
        # articles 0,1 -> climate ; articles 1,2 -> climat ; article 1 carries BOTH.
        mention(kws["climate"], arts[0], 5)
        mention(kws["climate"], arts[1], 4)
        mention(kws["climat"], arts[1], 3)
        mention(kws["climat"], arts[2], 2)
        mention(kws["football"], arts[3], 9)
        s.commit()
    with Session() as s:
        yield s
        s.rollback()


def _period():
    today = date.today()
    return Period(cadence="weekly", start=today - timedelta(days=7),
                  end=today + timedelta(days=1), baseline_start=today - timedelta(days=60))


def test_country_coverage_merges_cross_language_equivalents(corpus):
    """Q511 = a: one concept, one row — not one row per spelling."""
    rows = _terms(corpus, _period(), where=[], limit=10)
    ringed = [r for r in rows if r.get("ring_id")]
    assert ringed, (
        "climate and climat are still listed separately, so a country column reports "
        f"one concept as two smaller things: {[r['normalized'] for r in rows]}"
    )
    row = ringed[0]
    assert {m["normalized"] for m in row["members"]} == {"climate", "climat"}
    assert row["mentions"] == 5 + 4 + 3 + 2, "mentions are not summed across the members"


def test_the_merged_article_count_is_the_union_not_a_sum_and_not_a_floor(corpus):
    """THE number three plausible implementations get wrong three different ways.

    `climate` is in articles 0 and 1, `climat` in 1 and 2 — so the union is **3**, a sum
    of the members' own distinct counts is 4 (article 1 counted twice) and ``max()`` is 2
    (a conservative floor presented as a count). Only the union is the number the row
    claims to be.
    """
    rows = _terms(corpus, _period(), where=[], limit=10)
    row = next(r for r in rows if r.get("ring_id"))
    assert row["articles"] == 3, (
        f"the merged article count is {row['articles']}: 4 means the members were "
        "summed and an article carrying both was counted twice; 2 means a max() floor "
        "is being published as a count"
    )


def test_an_unringed_term_is_untouched_the_negative_space(corpus):
    """A merge that merges everything is the same defect pointing the other way."""
    rows = _terms(corpus, _period(), where=[], limit=10)
    solo = [r for r in rows if not r.get("ring_id")]
    assert any(r["normalized"] == "football" for r in solo), (
        "an ordinary keyword was swept into a ring"
    )
    assert all("members" not in r for r in solo), (
        "a solo row carries a members list, which invites a reader to look for a ring "
        "that is not there"
    )


def test_the_limit_is_applied_after_the_merge_not_before(corpus):
    """Merging AFTER a top-N cut loses exactly the members that make the merge matter.

    With `limit=1` the pre-merge query would return `football` alone (9 mentions beats
    either member on its own) and the concept would never form. The headroom is what
    makes the merged row — worth 14 mentions — reachable at all.
    """
    rows = _terms(corpus, _period(), where=[], limit=1)
    assert len(rows) == 1
    assert rows[0].get("ring_id"), (
        f"the top row is {rows[0]['normalized']!r}: the limit was applied before the "
        "merge, so the concept lost to a term that beats only its individual spellings"
    )


def _edition_with_ring():
    return {
        "sections": [
            {"section": "rising_concepts", "terms": [
                {"term": "climate", "normalized": "ring:climate", "ring_id": "climate",
                 "language_breakdown": {"en": 9, "fr": 5},
                 "members": [
                     {"term": "climate", "normalized": "climate", "language": "en", "recent": 9},
                     {"term": "climat", "normalized": "climat", "language": "fr", "recent": 5},
                     {"term": "Klima", "normalized": "klima", "language": None, "recent": 1},
                 ]},
                {"term": "football", "normalized": "football"},
            ]},
        ],
    }


def test_the_annexe_lists_every_ring_the_edition_merged(corpus):
    md = concepts_markdown(_edition_with_ring())
    assert "climate" in md and "climat" in md, "the merged forms are not listed"
    assert "rising_concepts" in md, "the annexe does not say WHICH section merged the ring"
    assert "football" not in md, "an unringed term was listed as a concept"


def test_the_annexe_never_totals_the_per_language_figures(corpus):
    """They overlap, so the caveat travels with them rather than a total."""
    md = concepts_markdown(_edition_with_ring())
    assert "do not add up" in md, "the overlap caveat is missing"
    assert "never a score" in md


def test_a_member_with_no_resolved_language_is_listed_under_a_question_mark(corpus):
    """Dropping it makes the per-language figures fail to reconcile invisibly."""
    md = concepts_markdown(_edition_with_ring())
    assert "Klima" in md, "a member whose language could not be resolved was dropped"
    assert "| ? |" in md, "an unresolved language is not marked as unresolved"


def test_the_annexe_says_how_many_forms_the_ring_DEFINES(corpus):
    """Anti-capping: three rows must not read as a three-form concept."""
    md = concepts_markdown(_edition_with_ring())
    assert "Forms present in this edition" in md
    assert "Forms the ring defines" in md, (
        "the table states only what this corpus reached, so a short list reads as the "
        "ring being small rather than as the corpus being thin"
    )


def test_an_edition_that_merged_nothing_says_so_in_words(corpus):
    """An absent annexe reads as 'no concept crossed languages' — the one thing it must
    never mean. So it is written for every edition, with an honest empty state."""
    md = concepts_markdown({"sections": []})
    assert "not a gap in this file" in md
    assert "|---|" not in md, "an empty annexe still draws a table header"


def test_the_member_terms_are_never_run_through_the_translator():
    """`i18n.py`'s own rule: a keyword extracted from someone else's text is DATA.

    Translating one both mistranslates a proper word and silently depresses every
    locale's measured coverage, because a value-bearing string can never match a key.
    """
    from tests.js_source_helper import python_function_source

    src = (_ROOT / "src" / "bulletin" / "annexes.py").read_text(encoding="utf-8")
    body = python_function_source(src, "concepts_markdown")
    for forbidden in ("T.t(m[", "T.t(m.get", "T.t(row[", "T.t(row.get"):
        assert forbidden not in body, (
            f"{forbidden!r} runs corpus data through the translator"
        )


def test_the_annexe_is_a_member_of_the_bundle_and_degrades_without_costing_it():
    """A file that cannot be written is a different thing from one with nothing to say."""
    from tests.js_source_helper import python_function_source

    src = (_ROOT / "src" / "bulletin" / "annexes.py").read_text(encoding="utf-8")
    body = python_function_source(src, "build_annexes")
    assert "CONCEPTS_FILENAME" in body, "the annexe is never written into the ZIP"
    tail = body.split("CONCEPTS_FILENAME", 1)[1]
    assert "except Exception" in tail.split("contents_filename")[0], (
        "the concepts member is written without a degrade, so one bad edition costs the "
        "whole bundle"
    )


def test_the_zip_really_carries_it(corpus):
    """The end-to-end half: a member asserted in source and absent from the ZIP is the
    shape every other test here would miss."""
    from src.bulletin.annexes import CONCEPTS_FILENAME, build_annexes

    out = build_annexes(corpus, {
        "kind": "weekly", "created_at": "2026-08-11T00:00:00Z",
        "period": {"start": "2026-08-05", "end": "2026-08-12", "label": "W"},
        **_edition_with_ring(),
    })
    names = zipfile.ZipFile(BytesIO(out["data"])).namelist()
    assert any(n.endswith(CONCEPTS_FILENAME) for n in names), names
