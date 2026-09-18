"""RC06: the recency-windowed re-check, published BESIDE the whole-history verdict.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RC06 came back BLANK, so its stated default stands as a LABELLED ASSUMPTION: a 90-day
window published beside the whole-history verdict, never replacing it, each with its own n.
The answer sheet's Q1108 = a proposes six months over the whole history instead. BOTH
ANSWERS STAND — the conflict is recorded, not resolved — so what is built here is RC06's
shape, and the payload says so in `assumption` where a reader will meet it.

THE PROPERTY THESE TESTS ARE ABOUT is that the two verdicts are never merged. A source
broken for two years and fixed last month, and a source that worked for two years and broke
last month, have the SAME whole-history rate and opposite futures. Publishing one number
would have to choose which of those two failures to ship; publishing both chooses neither.
So the fixture builds exactly that pair, and the tests assert that the two verdicts DIFFER
on it — a fixture where they agreed would let every assertion below pass while the code
quietly returned one verdict twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.analytics.source_audit import (  # noqa: E402
    RECENCY_WINDOW_DAYS,
    paired_verdicts,
    recency_window_start,
)
from src.analytics.source_quality import collect_article_stats  # noqa: E402
from src.database.models import Article, ArticleLink, Base, Source  # noqa: E402

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=400)     # far outside any window
RECENT = NOW - timedelta(days=10)   # inside a 90-day window


@pytest.fixture
def db(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'rc06.db'}", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, future=True)


def _source(db: Session, domain: str) -> Source:
    s = Source(name=domain, domain=domain, language="en")
    db.add(s)
    db.commit()
    return s


def _articles(db: Session, src: Source, *, n: int, when: datetime, links: int = 0,
              words: int = 200) -> None:
    """`when` lands on created_at, which is the axis the window reads."""
    base = db.query(Article).count()
    for i in range(n):
        url = f"https://{src.domain}/{base + i}"
        a = Article(url=url, canonical_url=url, content="body " * 60, hash=f"h{base + i}",
                    title=f"t{base + i}", language="en", word_count=words,
                    source_id=src.id, created_at=when.replace(tzinfo=None))
        db.add(a)
        db.flush()
        for j in range(links):
            u = f"https://out{j}.example/{a.id}"
            db.add(ArticleLink(article_id=a.id, url=u, normalized_url=u, link_type="external"))
    db.commit()


def test_the_window_reads_ingest_time_and_excludes_what_falls_outside_it(db: Session) -> None:
    """The scan's own half, driven directly: `since` bounds the population and nothing else
    about the pass changes. Asserted on BOTH sides, because a filter that excluded everything
    would satisfy a one-sided check."""
    src = _source(db, "s.example")
    _articles(db, src, n=4, when=OLD)
    _articles(db, src, n=6, when=RECENT)

    whole = collect_article_stats(db)
    windowed = collect_article_stats(db, since=recency_window_start(NOW))
    assert len(whole) == 10
    assert len(windowed) == 6, "the window kept the wrong articles"


def test_a_window_of_zero_days_is_clamped_rather_than_answering_nothing(db: Session) -> None:
    """NEGATIVE SPACE. A caller passing 0 or a negative day count must not silently produce a
    window that starts in the future and reports every source as unjudged -- that reads as a
    corpus-wide collapse rather than as a bad argument."""
    assert recency_window_start(NOW, days=0) < NOW.replace(tzinfo=None)
    assert recency_window_start(NOW, days=-5) < NOW.replace(tzinfo=None)


def test_the_two_verdicts_are_published_side_by_side_and_disagree_where_the_facts_do(
    db: Session,
) -> None:
    """THE CASE RC06 EXISTS FOR, built explicitly.

    `recovered` was a link farm for its whole old history and is clean lately; `broke` is the
    mirror. Their whole-history rates are close and their recent behaviour is opposite, so a
    single number could not tell them apart in the direction that matters.
    """
    recovered = _source(db, "recovered.example")
    _articles(db, recovered, n=40, when=OLD, links=40)      # old: link-dense
    _articles(db, recovered, n=40, when=RECENT, links=0)    # recent: clean

    broke = _source(db, "broke.example")
    _articles(db, broke, n=40, when=OLD, links=0)           # old: clean
    _articles(db, broke, n=40, when=RECENT, links=40)       # recent: link-dense

    # A COHORT, not a handful. `SOURCE_COHORT_FLOOR` is 8, so a population of three gets no
    # baseline at all and nothing can be flagged -- correct behaviour that would make every
    # assertion below pass for a reason unrelated to the window. These eight are clean in
    # both windows, so they define the tail the two sources above sit in or out of.
    for i in range(8):
        filler = _source(db, f"f{i}.example")
        _articles(db, filler, n=40, when=OLD, links=0)
        _articles(db, filler, n=40, when=RECENT, links=0)

    out = paired_verdicts(db, now=NOW)
    by_domain = {r["domain"]: r for r in out["sources"]}
    assert {"recovered.example", "broke.example"} <= set(by_domain)
    assert len(by_domain) == 10, "the cohort must be at or above SOURCE_COHORT_FLOOR"

    # Both verdicts are present for every source, each with its OWN n -- and the two n's
    # differ, which is what makes them two measurements rather than one repeated.
    for row in out["sources"]:
        assert row["whole_history"]["n"] == 80
        assert row["window"]["n"] == 40
        assert row["whole_history"]["status"] is not None

    # The window sees what the whole history cannot: the recent link density is in `broke`'s
    # windowed criteria and NOT in `recovered`'s.
    assert "link_density_rate" in by_domain["broke.example"]["window"]["criteria"], (
        f"the window missed a source that broke recently: {by_domain['broke.example']}"
    )
    assert "link_density_rate" not in by_domain["recovered.example"]["window"]["criteria"], (
        "the window flagged a source whose recent articles are clean"
    )
    # ...and the fixture really does separate them, so the two assertions above are not both
    # satisfiable by a verdict that ignores the window.
    assert (by_domain["broke.example"]["window"]["criteria"]
            != by_domain["recovered.example"]["window"]["criteria"])


def test_a_window_with_too_few_articles_is_reported_unjudged_rather_than_judged(
    db: Session,
) -> None:
    """The zero-evidence rule applied to a smaller population. A source with a long history
    and almost nothing recent must not be handed a verdict built on three articles -- and
    'unjudged because thin' must be distinguishable from 'unjudged because fine'."""
    quiet = _source(db, "quiet.example")
    _articles(db, quiet, n=60, when=OLD)
    _articles(db, quiet, n=3, when=RECENT)

    out = paired_verdicts(db, now=NOW)
    row = next(r for r in out["sources"] if r["domain"] == "quiet.example")
    assert row["whole_history"]["status"] is not None, "the long history is still judgeable"
    assert row["window"]["status"] is None
    assert row["window"]["n"] == 3
    assert "3 article" in row["window"]["not_judged_reason"]
    assert row["changed"] is False, "an unjudged window can never count as a disagreement"
    assert out["counts"]["window_too_thin"] == 1


def test_the_payload_names_the_window_the_method_and_the_assumption(db: Session) -> None:
    """Every number a reader meets carries what produced it, and the 90 days are named as an
    ASSUMPTION rather than presented as a ruling — RC06 was blank, and the sheet's Q1108
    proposes a different shape that still stands."""
    src = _source(db, "s.example")
    _articles(db, src, n=30, when=RECENT)

    out = paired_verdicts(db, now=NOW)
    assert out["window_days"] == RECENCY_WINDOW_DAYS == 90
    assert out["window_start"] == recency_window_start(NOW).isoformat()
    assert "created_at" in out["method"] or "fetched" in out["method"]
    assert "ASSUMPTION" in out["assumption"]
    assert "Q1108" in out["assumption"], "the conflicting answer must be named, not buried"
    assert "beside" in out["caveat"] or "both" in out["caveat"]


def test_the_window_is_judged_against_its_own_cohort_not_the_whole_historys(
    db: Session,
) -> None:
    """A windowed source measured against a whole-history baseline would be compared with a
    population it is not part of — the fabricated-baseline defect this module refuses
    elsewhere. Driven by making the WINDOW's cohort different from the whole history's: every
    source is link-dense recently, so within the window that is normal and none of them sits
    in its own cohort's tail."""
    for i in range(10):
        s = _source(db, f"s{i}.example")
        _articles(db, s, n=40, when=OLD, links=0)
        _articles(db, s, n=40, when=RECENT, links=40)

    out = paired_verdicts(db, now=NOW)
    flagged = [r for r in out["sources"] if "link_density_rate" in r["window"]["criteria"]]
    assert flagged == [], (
        "every source is link-dense in the window, so none is in the window cohort's tail; "
        f"{len(flagged)} were flagged, which means a foreign baseline was used"
    )
    # ...and the same population IS flagged when it is the minority, which is what proves the
    # criterion is live rather than switched off.
    assert out["counts"]["audited"] == 10


def test_the_report_publishes_the_window_BESIDE_the_history_and_can_be_turned_off() -> None:
    """RC06's word is BESIDE. The windowed verdict is its own key on the source-audit report,
    carrying its own window, its own per-source n and its own caveat — never folded into the
    historical rows, where it would read as a correction of them rather than as a second
    measurement. Driven through the real route, not the function."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        on = c.get("/api/diagnostics/source-audit?with_furniture=0")
        assert on.status_code == 200, on.text
        body = on.json()
        assert "recency_window" in body, "the windowed verdict is missing from the report"
        rw = body["recency_window"]
        assert rw["window_days"] == RECENCY_WINDOW_DAYS
        assert "ASSUMPTION" in rw["assumption"] and "Q1108" in rw["assumption"]
        # BESIDE: the historical rows must not have grown a windowed field, which is what
        # "never replacing" means in the payload rather than in prose.
        for row in body.get("sources", [])[:5]:
            assert "window" not in row and "recency" not in row

        off = c.get("/api/diagnostics/source-audit?with_furniture=0&recency_window=0")
        assert off.status_code == 200, off.text
        assert "recency_window" not in off.json(), (
            "recency_window=0 must omit the second pass, not run it and hide it"
        )


def test_a_scoped_paired_verdict_is_refused_rather_than_answered(db: Session) -> None:
    """Each verdict is judged against a cohort computed over its own whole population, so a
    scoped call would judge a handful of sources against a baseline made of themselves. The
    module refuses that everywhere else; it refuses it here too, by name, instead of
    answering something that looks right."""
    src = _source(db, "s.example")
    _articles(db, src, n=30, when=RECENT)
    with pytest.raises(ValueError, match="cannot be scoped"):
        paired_verdicts(db, now=NOW, source_ids={src.id})
