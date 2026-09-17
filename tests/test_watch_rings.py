"""Q510 — a watch on "climate" watches the RING, and the row says so.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

`S04-07` made searching mean the CONCEPT. The watch module's own promise is that *"a
watch means exactly what searching for its query means"* — so a matcher that kept
searching the literal word would have quietly broken that promise the day the omnibar
changed, and gone on firing on a narrower set than the search the user is looking at,
with nothing anywhere saying the two had parted.

What is pinned here is the pair, because either half alone is worse than neither:
widening WITHOUT the disclosure changes what interrupts the reader in silence, and the
disclosure without the widening describes a search that did not happen.

Driven against the REAL FTS index over a seeded corpus, not an injected matcher: the
injected matcher is how the firing LOGIC is tested (``test_watch_engine.py``), and it
is exactly the thing that cannot see whether the production matcher expands.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import watches as W
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source


@pytest.fixture()
def corpus(tmp_path):
    """A real store with a real FTS index — four languages of one concept, plus a decoy.

    A LOCAL engine, the pattern the other real-FTS suites use: the module-level
    ``src.database.session.engine`` is a process singleton bound to the first
    ``OO_DATA_DIR`` any test set, so a per-test temp directory silently re-uses the
    first one's file and every test after the first reads someone else's corpus.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'watch_rings.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Session = sessionmaker(bind=engine, future=True)
    ex = BaselineExtractor()
    docs = [
        ("en", "Climate one", "the climate assessment for the harbour district"),
        ("en", "Climate two", "climate policy and the climate committee met"),
        ("fr", "Climat un", "le climat du quartier portuaire a change"),
        ("fr", "Climat deux", "le climat regional se rechauffe depuis des decennies"),
        ("de", "Klima eins", "das Klima der Region wird seit vierzig Jahren erfasst"),
        ("en", "Nothing to do with it", "football results and the transfer window"),
    ]
    with Session() as s:
        srcs: dict[str, Source] = {}
        for i, (lg, title, body) in enumerate(docs):
            if lg not in srcs:
                src = Source(name=f"s-{lg}", rss_url=f"https://{lg}.test/f",
                             domain=f"{lg}.test")
                s.add(src)
                s.flush()
                srcs[lg] = src
            u = f"https://{lg}.test/{i}"
            when = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=i)
            a = Article(title=title, content=body, url=u, canonical_url=u,
                        source_id=srcs[lg].id, language=lg, published_at=when,
                        created_at=when, hash=f"h{i}")
            s.add(a)
            s.flush()
            index_article(s, a, extractor=ex)
        s.commit()
    ensure_fts(engine, rebuild="always")
    with Session() as s:
        yield s
        s.rollback()


def test_a_watch_on_climate_matches_an_article_that_only_says_climat(corpus):
    """The ruling, in one assertion: the ring, not the word.

    Five of the six seeded articles are the concept in four languages; the sixth is
    about football and must never be reached, because a watch INTERRUPTS the reader and
    a false interruption is worse than a false row in a list.
    """
    ids = W._fts_matcher(corpus, "climate") or []
    assert len(ids) >= 4, (
        f"the production matcher reached {len(ids)} articles -- a watch on 'climate' "
        "is still searching the literal word while the omnibar beside it searches the "
        "concept"
    )
    from src.database.models import Article

    titles = {
        t for (t,) in corpus.query(Article.title).filter(Article.id.in_(ids)).all()
    }
    assert any(t.startswith("Climat ") for t in titles), (
        f"no French article was reached: {sorted(titles)}"
    )
    assert "Nothing to do with it" not in titles, (
        "the football article was reached -- a watch that interrupts on an unrelated "
        "article is worse than one that misses"
    )


def test_the_literal_search_is_still_narrower_the_negative_twin(corpus):
    """A widening that widens EVERYTHING is the same defect pointing the other way.

    Without this, a matcher that simply returned every article would satisfy the test
    above.
    """
    from src.database.fts import search_ids

    literal = search_ids(corpus, "climate", exclude_quarantined=True) or []
    ringed = W._fts_matcher(corpus, "climate") or []
    assert len(literal) < len(ringed), (
        f"the literal search reached {len(literal)} and the ring {len(ringed)} -- the "
        "expansion is not doing anything, or everything"
    )


def test_the_watch_row_discloses_the_ring_it_now_covers(corpus):
    """The half that makes the widening honest rather than merely correct."""
    w = W.create_watch(corpus, name="Climate", query="climate", threshold=2, window_days=30)
    corpus.commit()
    row = next(r for r in W.list_watches(corpus) if r["id"] == w.id)
    xl = row.get("cross_language")
    assert xl, "the watch row does not say it now covers the concept"
    assert xl.get("expanded") is True
    terms = xl.get("terms") or []
    assert terms and terms[0].get("by_language"), (
        "the disclosure names no per-language members, so the reader cannot see what "
        "the watch was widened to"
    )
    assert xl.get("caveat"), "the disclosure carries no caveat"


def test_a_firing_carries_the_concept_to_the_lead_card(corpus):
    """The Lead card is where a firing reaches the reader.

    Without the concept on the firing, the card names a count over a set the reader
    cannot reconstruct from the query printed beside it.
    """
    W.create_watch(corpus, name="Climate", query="climate", threshold=2, window_days=30)
    corpus.commit()
    fired = W.evaluate_watches(corpus)
    corpus.commit()
    assert fired, "the watch did not fire on a corpus that plainly matches it"
    assert fired[0].get("cross_language"), "a firing carries no disclosure"
    recent = W.recent_fired_watches(corpus)
    assert recent and recent[0].get("cross_language"), (
        "the Lead-card source drops the disclosure the firing carried"
    )


def test_a_watch_on_an_unringed_term_says_nothing_the_negative_space(corpus):
    """A disclosure on every watch would train the reader to ignore it.

    The unringed term is VERIFIED unringed at test time rather than chosen by hand: the
    first draft used "football", which is in a ring, so the test failed for the right
    reason and would have been "fixed" by weakening it. A term the resolver itself
    reports as unexpanded cannot rot when the ring file grows.
    """
    from src.analytics.equivalence import resolve_concept

    term = "zzqunringedterm"
    assert not resolve_concept(term, expand=True).expanded, (
        f"{term!r} turned out to be in a ring, so this test proves nothing -- pick "
        "another"
    )
    w = W.create_watch(corpus, name="Nothing", query=term, threshold=1, window_days=30)
    corpus.commit()
    row = next(r for r in W.list_watches(corpus) if r["id"] == w.id)
    assert "cross_language" not in row, (
        "an ordinary watch carries a cross-language disclosure, which makes the one "
        "that matters unreadable"
    )
    # ... and the mechanism is LIVE on the same corpus, so the absence above is a
    # refusal rather than a feature that never runs.
    w2 = W.create_watch(corpus, name="Climate", query="climate", threshold=1, window_days=30)
    corpus.commit()
    row2 = next(r for r in W.list_watches(corpus) if r["id"] == w2.id)
    assert row2.get("cross_language"), (
        "neither watch carries a disclosure, so the negative space above is vacuous"
    )


def test_the_quarantine_gate_survived_the_change(corpus):
    """The promise the matcher already made, re-checked because this touched it.

    A watch raising an alert from content the app itself judged not-an-article
    manufactures a signal out of nav soup, and that guard lives in the same call the
    expansion was threaded into.
    """
    import inspect

    src = inspect.getsource(W._fts_matcher)
    assert "exclude_quarantined=True" in src, (
        "the quarantine gate was dropped while the expansion was added"
    )
    assert "expand=" in src, "the expansion is not passed to the search"
