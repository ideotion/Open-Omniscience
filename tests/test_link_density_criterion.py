"""B6: `high_link_density` as the SECOND measured extraction-failure criterion.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Ruled 2026-09-15 (register B6, complementing Q1107 = a). Until now `pathology_rate` was the
only criterion that could carry a source to `failing`, and Q1107 keeps its absolute floor at
0.5 while RECORDING that the floor is unreachable — so what actually decides has to be the
measured criteria. B6 names the one the field already measured: the 2026-08-03 bundle put
415 of 675 pre-label hits on `high_link_density`, most of the discriminating power in the
whole export, computed from `external_link_count / word_count` alone with no content decrypt.

THE DANGER IN ADDING A SECOND ONE, which these tests are mostly about: the code that had one
extraction-failure criterion read `pathology_articles` and `PATHOLOGY_ABS_FLOOR` by name. A
second criterion inheriting those would be gated on evidence it does not have and flagged by
a floor nobody argued for it — a silent, plausible-looking wrong answer in the one place the
app can take a source out of collection.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.analytics.source_quality import _HIGH_LINK_DENSITY, link_dense_article_ids  # noqa: E402
from src.database.models import Article, ArticleLink, Base, Source  # noqa: E402


@pytest.fixture
def db(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'ld.db'}", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, future=True)


def _source(db: Session, domain: str) -> Source:
    s = Source(name=domain, domain=domain)
    db.add(s)
    db.commit()
    return s


def _article(db: Session, src: Source, *, words: int | None, links: int,
             quarantined: bool = False, link_type: str = "external") -> Article:
    n = db.query(Article).count()
    url = f"https://{src.domain}/{links}-{words}-{n}"
    a = Article(title=f"a{n}", url=url, canonical_url=url, content="body " * 50,
                hash=f"h{src.id}-{n}", language="en",
                source_id=src.id, word_count=words, quarantined=quarantined)
    db.add(a)
    db.commit()
    for i in range(links):
        u = f"https://out{i}.example/{a.id}"
        db.add(ArticleLink(article_id=a.id, url=u, normalized_url=u, link_type=link_type))
    db.commit()
    return a


def test_the_threshold_is_the_shipped_one_and_is_not_restated(db: Session) -> None:
    """Three surfaces read link density -- the pre-label, the cheap-signal selector and now
    this criterion -- and a restated constant is how they come to flag sources the sampler
    never showed anybody. Driven exactly AT the threshold and just under it."""
    src = _source(db, "s.example")
    at = _article(db, src, words=100, links=int(_HIGH_LINK_DENSITY * 100))       # == 0.05
    under = _article(db, src, words=100, links=int(_HIGH_LINK_DENSITY * 100) - 1)  # < 0.05

    dense = link_dense_article_ids(db)
    assert at.id in dense, "the shipped threshold is inclusive (>=) and must stay so"
    assert under.id not in dense


def test_an_article_with_no_word_count_yields_no_ratio_rather_than_a_verdict(db: Session) -> None:
    """NEGATIVE SPACE, and the one that would be a real bug: a division it cannot do must
    produce NO answer, never a dense verdict. A zero word count with links would otherwise be
    infinitely dense — the most link-dense article in any corpus, on no evidence at all."""
    src = _source(db, "s.example")
    none_wc = _article(db, src, words=None, links=50)
    zero_wc = _article(db, src, words=0, links=50)

    dense = link_dense_article_ids(db)
    assert none_wc.id not in dense
    assert zero_wc.id not in dense


def test_a_quarantined_article_never_counts_toward_its_sources_verdict(db: Session) -> None:
    """Inherited from `collect_article_stats` and asserted rather than assumed: an article the
    ARTICLE gate already condemned must not also count against its SOURCE. Two gates sharing an
    input and disagreeing about it is what one settings panel exists to make visible."""
    src = _source(db, "s.example")
    live = _article(db, src, words=100, links=40)
    dead = _article(db, src, words=100, links=40, quarantined=True)

    dense = link_dense_article_ids(db)
    assert live.id in dense
    assert dead.id not in dense, "a quarantined article reached the source's link-density rate"


def test_internal_links_are_not_outbound_links(db: Session) -> None:
    """The signal is OUTBOUND density. A long article that links its own site heavily is a
    navigation-rich page, not a link farm, and counting it would flag every well-cross-linked
    publisher in the corpus."""
    src = _source(db, "s.example")
    internal = _article(db, src, words=100, links=40, link_type="internal")
    assert link_dense_article_ids(db) == set()
    assert internal.id is not None


def test_the_scan_can_be_scoped_to_a_batch_without_changing_its_answers(db: Session) -> None:
    """`per_source_metrics` judges a batch against a frozen whole-corpus cohort, so this is
    read per batch. A scoped read must answer exactly what the unscoped one would for those
    sources -- a scan that narrows its ANSWER as well as its input is the shrinking-population
    defect."""
    a, b = _source(db, "a.example"), _source(db, "b.example")
    ad = _article(db, a, words=100, links=40)
    bd = _article(db, b, words=100, links=40)

    whole = link_dense_article_ids(db)
    scoped = link_dense_article_ids(db, source_ids={a.id})
    assert whole == {ad.id, bd.id}
    assert scoped == {ad.id}


def test_a_corpus_with_no_links_at_all_answers_empty_rather_than_scanning_articles(
    db: Session,
) -> None:
    """The cheap early exit, pinned because it is also the honest answer: no link rows means
    no article can be link-dense, and the result must be an empty set rather than anything
    derived from word counts alone."""
    src = _source(db, "s.example")
    _article(db, src, words=10, links=0)
    assert link_dense_article_ids(db) == set()


def test_the_rate_and_its_raw_count_both_reach_per_source_metrics(db: Session) -> None:
    """A rate cannot tell 1 link-dense article in 1,992 from 600 in 1,200, which is exactly
    why `pathology_rate` carries `pathology_articles`. The new criterion carries its own count
    for the same reason, and the tail guard reads THAT count rather than the other one's."""
    from src.analytics.source_audit import per_source_metrics

    src = _source(db, "s.example")
    for _ in range(3):
        _article(db, src, words=100, links=40)      # dense
    for _ in range(7):
        _article(db, src, words=100, links=0)       # not

    per = per_source_metrics(db)
    m = per[src.id]
    assert m["link_dense_articles"] == 3
    assert m["link_density_rate"] == pytest.approx(0.3)
    # The two evidence counts are INDEPENDENT -- that separation is the whole point.
    assert m["pathology_articles"] == 0
