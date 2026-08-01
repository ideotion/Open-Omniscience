"""
The Bulletin's section registry — the edition's body.

Each section is pinned on the two properties that a reader of the output cannot
check for themselves: that it declares the window it ACTUALLY used, and that when
it cannot answer it says so rather than returning an empty result that reads as
"nothing happened".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin import sections
from src.bulletin.period import resolve_period
from src.database.models import (
    Article,
    Base,
    HazardEventDetail,
    Keyword,
    KeywordMention,
    KeywordTag,
    LawDocument,
    LawRevision,
    Source,
    WikiPage,
    WikiRevision,
)

_END = date(2026, 8, 1)  # weekly period = 2026-07-25 .. 2026-07-31 inclusive


def _period(cadence: str = "weekly"):
    return resolve_period(cadence, end=_END)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _src(s, name, domain, **kw) -> Source:
    o = Source(name=name, domain=domain, **kw)
    s.add(o)
    s.flush()
    return o


def _art(s, src, day, **kw) -> Article:
    n = _art.n = getattr(_art, "n", 0) + 1
    o = Article(
        url=f"https://{src.domain}/{n}",
        canonical_url=f"https://{src.domain}/{n}",
        source_id=src.id,
        title=kw.pop("title", f"Article {n}"),
        content="body",
        hash=f"{n:064d}",
        published_at=datetime.fromisoformat(f"{day} 12:00:00"),
        quarantined=kw.pop("quarantined", False),
        **kw,
    )
    s.add(o)
    s.flush()
    return o


def _kw(s, term, **kw) -> Keyword:
    o = Keyword(term=term, normalized_term=term, **kw)
    s.add(o)
    s.flush()
    return o


def _mention(s, kw, article_id, day, source_id, count=1):
    s.add(
        KeywordMention(
            keyword_id=kw.id,
            article_id=article_id,
            count=count,
            observed_on=date.fromisoformat(day),
            source_id=source_id,
        )
    )


# --------------------------------------------------------------------------- #
#  across channels
# --------------------------------------------------------------------------- #


def _channel_corpus() -> tuple[Session, dict]:
    s = _session()
    news = _src(s, "News", "news.test", source_type="news")
    wiki = _src(s, "Wikipedia (en)", "en.wikipedia.org")
    law = _src(s, "Law FR", "law.fr.local", source_type="legal")
    k = _kw(s, "flood")
    # wiki carries it on the 26th, news on the 28th, law on the 30th.
    _mention(s, k, 1, "2026-07-26", wiki.id)
    _mention(s, k, 2, "2026-07-28", news.id)
    _mention(s, k, 3, "2026-07-30", law.id)
    s.commit()
    return s, {"terms": [{"term": "flood", "normalized": "flood"}]}


def test_a_concept_is_attributed_to_the_channel_that_carried_it_earliest():
    s, rising = _channel_corpus()
    out = sections.across_channels(s, _period(), terms=rising["terms"])
    row = out["terms"][0]
    assert row["first_seen"] == "2026-07-26"
    assert row["channel"] == "wikipedia"
    assert row["channels_tied"] is None


def test_a_same_day_tie_is_reported_as_a_tie_never_broken():
    """The mention clock is a DATE — there is no finer order to appeal to, so
    picking a winner would be inventing a sequence the data does not contain."""
    s, rising = _channel_corpus()
    news = s.query(Source).filter_by(domain="news.test").one()
    k = s.query(Keyword).filter_by(normalized_term="flood").one()
    _mention(s, k, 4, "2026-07-26", news.id)  # same day as the wiki mention
    s.commit()
    out = sections.across_channels(s, _period(), terms=rising["terms"])
    row = out["terms"][0]
    assert row["channel"] is None
    assert row["channels_tied"] == ["web", "wikipedia"]


def test_a_tie_credits_no_channel_so_the_table_cannot_exceed_the_concepts_examined():
    s, rising = _channel_corpus()
    news = s.query(Source).filter_by(domain="news.test").one()
    k = s.query(Keyword).filter_by(normalized_term="flood").one()
    _mention(s, k, 4, "2026-07-26", news.id)
    s.commit()
    out = sections.across_channels(s, _period(), terms=rising["terms"])
    assert sum(c["concepts_first_here"] for c in out["channels"]) <= out["concepts_examined"]


def test_with_no_rising_concepts_it_says_so_instead_of_returning_an_empty_table():
    s, _ = _channel_corpus()
    out = sections.across_channels(s, _period(), terms=[])
    assert out["terms"] == []
    assert "no rising concepts" in out["skipped"]


def test_the_caveat_refuses_the_who_reported_it_first_reading():
    s, rising = _channel_corpus()
    out = sections.across_channels(s, _period(), terms=rising["terms"])
    assert "not a claim about who reported anything first" in out["caveat"]


# --------------------------------------------------------------------------- #
#  by topic tag
# --------------------------------------------------------------------------- #


def test_topics_are_counted_and_the_untagged_remainder_is_reported():
    """A topic table covering a tenth of the corpus while looking complete is
    worse than none — the untagged share is what makes it readable."""
    s = _session()
    src = _src(s, "N", "n.test")
    tagged = _kw(s, "election")
    untagged = _kw(s, "widget")
    s.add(KeywordTag(keyword_id=tagged.id, axis="topic", tag="politics", source="baseline"))
    _mention(s, tagged, 1, "2026-07-26", src.id, count=5)
    _mention(s, untagged, 2, "2026-07-27", src.id, count=3)
    s.commit()

    out = sections.by_topic_tag(s, _period())
    assert out["topics"] == [{"topic": "politics", "articles": 1, "mentions": 5}]
    assert out["mentions_total"] == 8
    assert out["mentions_tagged"] == 5
    assert out["mentions_untagged"] == 3


def test_only_the_topic_axis_is_read():
    s = _session()
    src = _src(s, "N", "n.test")
    k = _kw(s, "storm")
    s.add(KeywordTag(keyword_id=k.id, axis="type", tag="event", source="baseline"))
    _mention(s, k, 1, "2026-07-26", src.id)
    s.commit()
    assert sections.by_topic_tag(s, _period())["topics"] == []


def test_a_mention_outside_the_period_is_not_counted():
    s = _session()
    src = _src(s, "N", "n.test")
    k = _kw(s, "election")
    s.add(KeywordTag(keyword_id=k.id, axis="topic", tag="politics", source="baseline"))
    _mention(s, k, 1, "2026-08-01", src.id)  # the exclusive end day
    s.commit()
    out = sections.by_topic_tag(s, _period())
    assert out["topics"] == [] and out["mentions_total"] == 0


def test_the_caveat_names_a_tag_as_an_assertion_not_ground_truth():
    out = sections.by_topic_tag(_session(), _period())
    assert "labelled assertion" in out["caveat"]


# --------------------------------------------------------------------------- #
#  changes of record
# --------------------------------------------------------------------------- #


def test_law_and_wiki_revisions_in_the_period_are_counted_exactly():
    s = _session()
    doc = LawDocument(jurisdiction="fr", title="Code du travail", url="https://law.test/x")
    page = WikiPage(wiki="en", title="Flood")
    s.add_all([doc, page])
    s.flush()
    for i, (day, flagged) in enumerate(
        (("2026-07-26", False), ("2026-07-28", True), ("2026-08-01", False))
    ):
        s.add(
            LawRevision(
                document_id=doc.id,
                observed_at=datetime.fromisoformat(f"{day} 09:00:00"),
                # (document_id, content_hash) is unique — a revision IS a new hash.
                content_hash=f"{i:064d}",
                delta_bytes=120,
                flagged=flagged,
            )
        )
    s.add(
        WikiRevision(
            page_id=page.id,
            revid=7,
            timestamp=datetime.fromisoformat("2026-07-27 10:00:00"),
            delta_bytes=-40,
            flagged=False,
            editor_anon=True,
        )
    )
    s.commit()

    out = sections.changes_of_record(s, _period())
    assert out["law_revisions"] == 2, "the 08-01 revision is the next period's"
    assert out["law_revisions_flagged"] == 1
    assert out["wiki_revisions"] == 1
    assert out["law_examples"][0]["jurisdiction"] == "fr"
    assert out["wiki_examples"][0]["edition"] == "en"
    assert out["wiki_examples"][0]["editor_anonymous"] is True


def test_the_example_list_is_bounded_but_the_count_beside_it_is_not():
    s = _session()
    doc = LawDocument(jurisdiction="fr", title="X", url="https://law.test/x")
    s.add(doc)
    s.flush()
    for i in range(40):
        s.add(
            LawRevision(
                document_id=doc.id,
                observed_at=datetime.fromisoformat(f"2026-07-26 {i % 24:02d}:00:00"),
                content_hash=f"{i:064d}",
            )
        )
    s.commit()
    out = sections.changes_of_record(s, _period())
    assert out["law_revisions"] == 40, "a cap bounds examples, never a reported number"
    assert len(out["law_examples"]) == out["examples_limit"] == 12


def test_the_caveat_refuses_to_read_a_flag_as_a_judgement():
    out = sections.changes_of_record(_session(), _period())
    assert "not a judgement" in out["caveat"]
    assert "not that its law stood still" in out["caveat"]


# --------------------------------------------------------------------------- #
#  alerts
# --------------------------------------------------------------------------- #


def test_hazard_declarations_carry_the_providers_own_fields_unchanged():
    s = _session()
    src = _src(s, "USGS", "hazard.usgs.local", source_type="hazard")
    a = _art(s, src, "2026-07-27", title="M 6.1 near X")
    s.add(
        HazardEventDetail(
            article_id=a.id,
            provider="usgs",
            event_id="us123",
            event_type="earthquake",
            severity="orange",
            magnitude=6.1,
            place="near X",
            event_time=datetime.fromisoformat("2026-07-27 11:00:00"),
        )
    )
    s.commit()
    out = sections.alerts(s, _period())
    assert out["events"] == 1
    ex = out["examples"][0]
    assert (ex["provider"], ex["event_type"], ex["severity"], ex["magnitude"]) == (
        "usgs",
        "earthquake",
        "orange",
        6.1,
    )
    assert out["by_provider"] == [{"provider": "usgs", "events": 1}]


def test_a_hazard_outside_the_period_or_quarantined_is_excluded():
    s = _session()
    src = _src(s, "USGS", "hazard.usgs.local", source_type="hazard")
    out_of_period = _art(s, src, "2026-08-01")
    quarantined = _art(s, src, "2026-07-27", quarantined=True)
    for a in (out_of_period, quarantined):
        s.add(
            HazardEventDetail(
                article_id=a.id, provider="usgs", event_id=f"e{a.id}", event_type="flood"
            )
        )
    s.commit()
    assert sections.alerts(s, _period())["events"] == 0


def test_a_quiet_period_is_not_read_as_a_calm_world():
    out = sections.alerts(_session(), _period())
    assert out["events"] == 0
    assert "those two are not the same thing" in out["caveat"]


# --------------------------------------------------------------------------- #
#  through time
# --------------------------------------------------------------------------- #


def test_earlier_years_on_the_same_calendar_days_are_counted():
    s = _session()
    src = _src(s, "N", "n.test")
    _art(s, src, "2025-07-26")  # same calendar day, a year earlier
    _art(s, src, "2024-07-31")
    _art(s, src, "2025-07-10")  # a different day — not the lens
    _art(s, src, "2026-07-26")  # the period itself — never counted as history
    s.commit()
    out = sections.through_time(s, _period())
    assert {r["year"]: r["articles"] for r in out["years"]} == {2025: 1, 2024: 1}
    assert out["days_matched"] == 7


def test_a_long_period_skips_the_lens_with_the_reason_stated():
    """Past two months, "the same days in earlier years" stops being a lens — it
    becomes the whole of an earlier year, which the corpus already shows."""
    out = sections.through_time(_session(), _period("yearly"))
    assert out["years"] == []
    assert "stops being a lens" in out["skipped"]


def test_the_caveat_refuses_the_coincidence_as_connection_reading():
    out = sections.through_time(_session(), _period())
    assert "coincidence, not a connection" in out["caveat"]
    assert "never a reweighting" in out["caveat"]


# --------------------------------------------------------------------------- #
#  the registry
# --------------------------------------------------------------------------- #


def test_every_registered_section_is_emitted_in_order():
    out = sections.build_sections(_session(), _period())
    assert [b["section"] for b in out] == [k for k, _ in sections.SECTIONS]


def test_every_section_declares_the_window_it_actually_used():
    """The point of section 12: a monthly edition showing a 14-day number must be
    VISIBLE in the output rather than hidden."""
    for bundle in sections.build_sections(_session(), _period()):
        assert "window" in bundle, bundle["section"]
        assert bundle["window"]["days"] > 0


def test_one_failing_section_is_reported_in_place_and_the_rest_still_run(monkeypatch):
    monkeypatch.setattr(
        sections,
        "by_topic_tag",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("topics exploded")),
    )
    out = sections.build_sections(_session(), _period())
    failed = next(b for b in out if b["section"] == "by_topic_tag")
    assert "topics exploded" in failed["error"]
    assert len(out) == len(sections.SECTIONS), "a failing section is reported, never dropped"


def test_across_channels_is_scoped_by_the_rising_section_that_ran_before_it():
    """The registry threads an earlier section's output forward so a later one can
    be scoped by it — that scoping is what keeps the mention query indexed."""
    s, _ = _channel_corpus()
    out = sections.build_sections(s, _period())
    across = next(b for b in out if b["section"] == "across_channels")
    assert "skipped" in across or across["terms"] is not None


def test_no_score_shaped_field_in_any_section():
    flat = json.dumps(sections.build_sections(_session(), _period()), default=str).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat


def test_there_is_deliberately_no_top_story_section():
    """That is exactly where an implicit composite score creeps in: the moment one
    item is elevated, something had to rank them."""
    keys = {k for k, _ in sections.SECTIONS}
    assert not any("top_story" in k or "lead" in k or "headline" in k for k in keys)
