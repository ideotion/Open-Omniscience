"""The four tables the P0 validation caught riding inside every artifact, uncopied.

Field evidence, 2026-08-03: the maintainer's P0 run on a 16.5 GB / 794,333-article
corpus reported ``_unmerged_tables`` with 35,000 ``stat_figures`` in it. Those are
networked official-statistics observations -- not one of them is recomputable from the
corpus -- and no handler copied them, so a FRESH-INSTALL restore dropped the lot. The
same was true of ``stat_subscriptions``, ``hazard_event_details`` and ``keyword_tags``.

WHY IT SURVIVED SO LONG: the restore anyone actually runs is a self-restore, where every
row is already present and reads as a "duplicate". Only a merge into a DIFFERENT corpus
exercises what the handlers carry, which is exactly what these tests do.

Each test drives the REAL ``merge_corpus`` against two real SQLite corpora. A test that
called a handler directly would prove the handler runs, not that the merge runs it -- the
recorded house lesson that a double injected via a parameter bypasses the production path.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import (  # noqa: E402
    Article,
    Base,
    HazardEventDetail,
    Keyword,
    KeywordTag,
    Source,
    StatFigure,
    StatSubscription,
)

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}

_T0 = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC).replace(tzinfo=None)
_T1 = datetime(2026, 8, 2, 9, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _rows(path: Path, model):
    with _corpus(path)() as s:
        return s.query(model).all()


def _figure(agency="us-bls", series="CPI", area="US", period="2026-01",
            value=1.0, extracted_at=_T0):
    return StatFigure(agency=agency, series_id=series, ref_area=area, time_period=period,
                      value=value, unit="index", extracted_at=extracted_at, created_at=_T0)


# --------------------------------------------------------------------------- #
#  stat_figures -- the 35,000 rows the field run actually lost
# --------------------------------------------------------------------------- #
def test_official_statistics_figures_survive_a_merge_into_a_fresh_corpus(tmp_path):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_figure(value=317.6))
        s.commit()
    _corpus(working)  # a FRESH install: nothing local

    merge_corpus(staged, working, _BATCH_META)

    got = _rows(working, StatFigure)
    assert len(got) == 1, "a networked observation no re-index can rebuild was dropped"
    assert got[0].value == 317.6
    assert got[0].agency == "us-bls" and got[0].series_id == "CPI"


def test_two_VINTAGES_of_one_observation_both_survive(tmp_path):
    """Revisions are evidence: a re-fetch at a later ``extracted_at`` is a NEW row, never
    an overwrite. A dedup key that omitted ``extracted_at`` would silently collapse a
    revision history into whichever vintage happened to arrive first."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_figure(value=317.6, extracted_at=_T0))   # first publication
        s.add(_figure(value=318.1, extracted_at=_T1))   # the revision
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)

    got = sorted(_rows(working, StatFigure), key=lambda f: f.extracted_at)
    assert [f.value for f in got] == [317.6, 318.1], "a vintage was collapsed away"


def test_the_same_vintage_arriving_twice_is_a_duplicate_not_a_second_row(tmp_path):
    """The other direction: merging the same corpus twice must not grow the table.
    A merge that only ever inserts is as wrong as one that never does."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_figure(value=317.6))
        s.commit()
    with _corpus(working)() as s:
        s.add(_figure(value=317.6))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    assert len(_rows(working, StatFigure)) == 1, "the same vintage was inserted twice"


# --------------------------------------------------------------------------- #
#  stat_subscriptions -- the user's own tracking choices
# --------------------------------------------------------------------------- #
def test_tracked_series_survive_and_the_local_cadence_wins(tmp_path):
    """A subscription is carried, but ``interval_days`` describes THIS machine's
    schedule. Adopting the incoming corpus's cadence would silently retune the
    operator's own refresh rate behind their back."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(StatSubscription(source="worldbank", indicator="NY.GDP.MKTP.CD",
                               country="FR", interval_days=7, enabled=True, created_at=_T0))
        s.add(StatSubscription(source="worldbank", indicator="SP.POP.TOTL",
                               country="DE", interval_days=30, enabled=True, created_at=_T0))
        s.commit()
    with _corpus(working)() as s:  # the operator already tracks the first, less often
        s.add(StatSubscription(source="worldbank", indicator="NY.GDP.MKTP.CD",
                               country="FR", interval_days=90, enabled=False, created_at=_T0))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    got = {r.indicator: r for r in _rows(working, StatSubscription)}
    assert set(got) == {"NY.GDP.MKTP.CD", "SP.POP.TOTL"}, "a tracked series was dropped"
    assert got["NY.GDP.MKTP.CD"].interval_days == 90, "the incoming cadence overwrote the local one"
    assert got["NY.GDP.MKTP.CD"].enabled is False, "the local enabled state was overwritten"


# --------------------------------------------------------------------------- #
#  hazard_event_details -- ephemeral provider snapshots, with TWO unique constraints
# --------------------------------------------------------------------------- #
def _article(s, url: str, title: str) -> Article:
    """An article needs a Source: articles.source_id is NOT NULL, and the merge remaps
    both, so a fixture that skipped the source would not exercise the real id remap."""
    domain = url.split("/")[2]
    src = s.query(Source).filter_by(domain=domain).one_or_none()
    if src is None:
        src = Source(name=domain, domain=domain)
        s.add(src)
        s.flush()
    art = Article(url=url, canonical_url=url, source_id=src.id, title=title,
                  content="body", hash=url, created_at=_T0)
    s.add(art)
    s.flush()
    return art


def test_hazard_detail_follows_its_article_across_the_id_remap(tmp_path):
    """The incoming article's id is not the local one, so the detail has to travel
    through map_articles. A handler that copied ``article_id`` verbatim would attach the
    magnitude to whatever local article happened to hold that id."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        art = _article(s, "https://x.test/quake", "M6.8 offshore")
        s.add(HazardEventDetail(article_id=art.id, provider="usgs", event_id="us7000abcd",
                                event_type="earthquake", magnitude=6.8, lat=38.1, lon=141.2,
                                place="offshore", created_at=_T0))
        s.commit()
    with _corpus(working)() as s:      # local ids are offset, so a verbatim copy misattaches
        _article(s, "https://other.test/a", "unrelated")
        _article(s, "https://other.test/b", "also unrelated")
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    got = _rows(working, HazardEventDetail)
    assert len(got) == 1, "provider-asserted hazard metadata was dropped"
    assert got[0].magnitude == 6.8 and got[0].event_id == "us7000abcd"
    with _corpus(working)() as s:
        owner = s.get(Article, got[0].article_id)
        assert owner.url == "https://x.test/quake", "the detail was attached to the wrong article"


def test_a_detail_for_an_article_that_already_has_one_is_a_duplicate(tmp_path):
    """``hazard_event_details`` is unique on ``article_id`` AND on (provider, event_id).
    Guarding only the provider pair would let a row whose event_id is new pass the
    NOT-EXISTS and then violate the article_id constraint on insert -- the exact shape of
    the article_mentioned_dates key bug that broke a real backup preview in 2026-06."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        art = _article(s, "https://x.test/quake", "M6.8 offshore")
        s.add(HazardEventDetail(article_id=art.id, provider="gdacs", event_id="EQ-999",
                                event_type="earthquake", magnitude=6.8, created_at=_T0))
        s.commit()
    with _corpus(working)() as s:
        art = _article(s, "https://x.test/quake", "M6.8 offshore")   # SAME article
        s.add(HazardEventDetail(article_id=art.id, provider="usgs", event_id="us7000abcd",
                                event_type="earthquake", magnitude=6.7, created_at=_T0))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)   # must not raise

    got = _rows(working, HazardEventDetail)
    assert len(got) == 1, "a second detail landed on an article that already had one"
    assert got[0].provider == "usgs", "local was replaced rather than kept"


# --------------------------------------------------------------------------- #
#  keyword_tags -- part config-seeded, part reviewed by the operator
# --------------------------------------------------------------------------- #
def test_keyword_tags_follow_their_keyword_and_keep_the_source_distinct(tmp_path):
    """``source`` is in the key on purpose: a curated assignment and an
    analyzer-proposed one for the same tag are different claims about the same keyword,
    and collapsing them would let a proposal stand in for a human decision."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(Keyword(term="election", normalized_term="election"))
        s.flush()
        kid = s.query(Keyword).one().id
        s.add(KeywordTag(keyword_id=kid, axis="topic", tag="politics", source="curated",
                         created_at=_T0))
        s.add(KeywordTag(keyword_id=kid, axis="topic", tag="politics", source="analyzer",
                         created_at=_T0))
        s.commit()
    with _corpus(working)() as s:
        s.add(Keyword(term="unrelated", normalized_term="unrelated"))   # id offset
        s.add(Keyword(term="election", normalized_term="election"))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    got = _rows(working, KeywordTag)
    assert {t.source for t in got} == {"curated", "analyzer"}, "two distinct claims collapsed into one"
    with _corpus(working)() as s:
        for t in got:
            assert s.get(Keyword, t.keyword_id).normalized_term == "election", "tag attached to the wrong keyword"


# --------------------------------------------------------------------------- #
#  The report must stop calling these unmerged.
# --------------------------------------------------------------------------- #
def test_the_restore_report_no_longer_lists_them_as_unmerged(tmp_path):
    """``_unmerged_tables`` is what surfaced this in the field. Once a handler exists the
    table must leave that list -- otherwise the report still reads as though the data was
    dropped, which is its own kind of dishonesty."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_figure())
        s.add(StatSubscription(source="worldbank", indicator="X", created_at=_T0))
        s.add(Keyword(term="k", normalized_term="k"))
        s.flush()
        s.add(KeywordTag(keyword_id=s.query(Keyword).one().id, axis="topic", tag="t",
                         source="curated", created_at=_T0))
        art = _article(s, "https://x.test/h", "hazard")
        s.add(HazardEventDetail(article_id=art.id, provider="usgs", event_id="e1",
                                event_type="flood", created_at=_T0))
        s.commit()
    _corpus(working)

    counts, _batch_id = merge_corpus(staged, working, _BATCH_META)
    unmerged = counts.get("_unmerged_tables", {})
    for name in ("stat_figures", "stat_subscriptions", "hazard_event_details", "keyword_tags"):
        assert name not in unmerged, f"{name} is merged now but still reported as unmerged"
