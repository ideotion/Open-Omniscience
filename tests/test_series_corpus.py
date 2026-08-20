"""Official-statistics series as corpus Articles (2026-08-07, rulings 5, 30, 31).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Half of this is the feature: a series becomes an Article, keyed on (agency, series,
area), idempotent, indexed through the ordinary hook so "GDP france" matches without a
bespoke search path.

The other half is the SKEPTIC LENS the brief mandates for this slice — corpus
pollution — and it is the half that decides whether the feature may ship at all.
Roughly 9,800 templated documents entering a corpus is precisely the shape MinHash
clusters, and a fabricated coordination signal is worse than no search. So the tests
that matter here are the ones about what this must NOT do to everything else: not
manufacture agreement between sources, not make its own boilerplate a top corpus term,
not hide inside corpus-wide figures that should be able to exclude it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.extract import BaselineExtractor
from src.catalog.provenance import provenance_of
from src.database.models import Article, Keyword, KeywordMention, Source, StatFigure
from src.stats import series_corpus as sc


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    from src.database.models import Base
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _seed(db, *, areas, series, years=range(2015, 2025), gap_year="2018"):
    rows = []
    for a in areas:
        for code in series:
            for y in years:
                rows.append(StatFigure(
                    agency="worldbank", series_id=code, ref_area=a, time_period=str(y),
                    value=None if str(y) == gap_year else float(y) * 1000,
                    unit="", extracted_at="2026-08-01"))
    db.add_all(rows)
    db.commit()


# --------------------------------------------------------------------------- #
# The feature
# --------------------------------------------------------------------------- #


def test_a_series_becomes_one_article_keyed_on_agency_series_and_area(db):
    _seed(db, areas=["FRA", "DEU"], series=["NY.GDP.MKTP.CD"])
    out = sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=50)

    assert out["created"] == 2 and out["total_series"] == 2
    arts = db.query(Article).all()
    assert {a.title for a in arts} == {
        "GDP (current US$) — France", "GDP (current US$) — Germany"}
    assert {a.canonical_url for a in arts} == {
        "statistics://worldbank/NY.GDP.MKTP.CD/FRA",
        "statistics://worldbank/NY.GDP.MKTP.CD/DEU"}


def test_re_running_adds_no_duplicate(db):
    """The property that makes this schedulable at all."""
    _seed(db, areas=["FRA"], series=["NY.GDP.MKTP.CD"])
    ex = BaselineExtractor()
    sc.sync_series_corpus(db, extractor=ex, limit=50)
    before = db.query(func.count(Article.id)).scalar()

    again = sc.sync_series_corpus(db, extractor=ex, limit=50)

    assert db.query(func.count(Article.id)).scalar() == before
    assert again["unchanged"] == 1 and again["created"] == 0


def test_a_new_vintage_updates_the_article_rather_than_adding_one(db):
    """A revision is a new StatFigure row and must be. It is NOT a new Article —
    a corpus that grew a near-copy per restatement would be a duplicate farm."""
    _seed(db, areas=["FRA"], series=["NY.GDP.MKTP.CD"])
    ex = BaselineExtractor()
    sc.sync_series_corpus(db, extractor=ex, limit=50)

    db.add(StatFigure(agency="worldbank", series_id="NY.GDP.MKTP.CD", ref_area="FRA",
                      time_period="2024", value=99.0, unit="", extracted_at="2026-09-01"))
    db.commit()
    out = sc.sync_series_corpus(db, extractor=ex, limit=50)

    assert out["updated"] == 1 and out["created"] == 0
    assert db.query(func.count(Article.id)).scalar() == 1
    art = db.query(Article).one()
    assert "2024: 99.0" in art.content, "the article shows the CURRENT reading"


def test_a_published_gap_renders_as_a_gap_not_a_zero(db):
    _seed(db, areas=["FRA"], series=["NY.GDP.MKTP.CD"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=50)
    body = db.query(Article).one().content

    assert "2018: —" in body, "a gap the producer published is a dash"
    assert "2018: 0" not in body
    # ...and every other period IS present, so the dash reads as a hole in a real
    # span rather than as a series that simply skipped a year.
    assert "2017: " in body and "2019: " in body


def test_an_aggregate_is_named_as_one_and_a_country_as_a_country(db):
    _seed(db, areas=["WLD", "FRA"], series=["SP.POP.TOTL"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=50)
    titles = {a.title for a in db.query(Article).all()}

    assert "Population, total — World" in titles
    assert "Population, total — France" in titles


def test_an_unrecognised_area_renders_as_its_code_rather_than_being_invented(db):
    """classify_ref_area's third state, carried through to the reader."""
    _seed(db, areas=["ZZQ"], series=["SP.POP.TOTL"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=50)

    assert db.query(Article).one().title == "Population, total — ZZQ"


def test_the_series_is_indexed_through_the_ordinary_hook(db):
    """No bespoke search path: keywords exist because index_article ran."""
    _seed(db, areas=["FRA"], series=["NY.GDP.MKTP.CD"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=50)

    art = db.query(Article).one()
    mentions = db.query(func.count(KeywordMention.id)).filter(
        KeywordMention.article_id == art.id).scalar()
    assert mentions > 0, "a series Article with no keywords is invisible to the corpus"
    terms = {k.term.lower() for k in db.query(Keyword).all()}
    assert any("france" in t for t in terms), f"the country must be findable: {sorted(terms)[:20]}"


def test_the_channel_is_a_distinct_filterable_provenance_class(db):
    _seed(db, areas=["FRA"], series=["NY.GDP.MKTP.CD"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=50)

    src = db.query(Source).one()
    assert src.source_type == "statistics"
    assert src.domain == "statistics.worldbank.local"
    assert provenance_of(src.domain, src.source_type) == "statistics", (
        "a corpus-wide figure must be able to exclude this channel deliberately"
    )


def test_the_walk_is_bounded_and_resumable(db):
    _seed(db, areas=["FRA", "DEU", "ITA"], series=["NY.GDP.MKTP.CD"])
    ex = BaselineExtractor()

    first = sc.sync_series_corpus(db, extractor=ex, limit=2)
    assert first["examined"] == 2 and first["next_start"] == 2 and not first["complete"]

    second = sc.sync_series_corpus(db, extractor=ex, limit=2, start=first["next_start"])
    assert second["examined"] == 1 and second["complete"]
    assert db.query(func.count(Article.id)).scalar() == 3


def test_a_stop_is_honoured_between_series(db):
    _seed(db, areas=["FRA", "DEU", "ITA"], series=["NY.GDP.MKTP.CD"])
    seen = {"n": 0}

    def stop():
        seen["n"] += 1
        return seen["n"] > 2

    out = sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=50, should_stop=stop)
    assert out["stopped"] is True
    assert out["examined"] < 3
    assert out["complete"] is False, "a stopped pass must never report itself complete"


# --------------------------------------------------------------------------- #
# The skeptic lens: corpus pollution
# --------------------------------------------------------------------------- #


def test_every_series_article_shares_one_source_per_agency(db):
    """The structural protection, asserted rather than assumed.

    echo_chamber, copypasta and skeleton_echo all gate on THREE DISTINCT SOURCES.
    ~9,800 near-identically-templated documents are exactly what MinHash clusters, so
    what stops a fabricated coordination signal is not a filter anyone has to remember
    but the fact that one source cannot manufacture agreement with itself. If a future
    change gives each indicator its own source, this test is what fails.
    """
    _seed(db, areas=["FRA", "DEU", "ITA", "ESP"],
          series=["NY.GDP.MKTP.CD", "SP.POP.TOTL", "SP.DYN.LE00.IN"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=200)

    arts = db.query(Article).all()
    assert len(arts) == 12, "guard against an empty corpus satisfying this for free"
    assert len({a.source_id for a in arts}) == 1, (
        "series Articles must share one source, or the coordination producers' "
        "distinct-source gate stops protecting the corpus from them"
    )


def test_the_boilerplate_does_not_become_a_top_corpus_term(db):
    """The templated body must not rewrite what the corpus is ABOUT.

    A caveat sentence repeated once per series would put its own vocabulary at the top
    of the corpus's keyword ranking — damaging the trusted index for every other
    article, to say something that belongs to the channel rather than to any one
    series. Measured against the real extractor rather than reasoned about: the terms
    that lead must be the SUBJECT terms (the indicator, the country), never the
    scaffolding.
    """
    _seed(db, areas=["FRA", "DEU", "ITA", "ESP", "USA", "CHN"],
          series=["NY.GDP.MKTP.CD", "SP.POP.TOTL", "SP.DYN.LE00.IN"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=200)

    top = db.execute(
        select(Keyword.term, func.count(KeywordMention.id).label("n"))
        .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .group_by(Keyword.id).order_by(func.count(KeywordMention.id).desc()).limit(12)
    ).all()
    terms = [t.lower() for t, _n in top]
    assert terms, "guard against an unindexed corpus passing for free"

    scaffolding = {"producer", "published", "figure", "score", "series", "unit",
                   "periods", "reported", "latest", "earliest", "value", "dash", "gap"}
    leaked = [t for t in terms[:6] if t in scaffolding]
    assert not leaked, (
        f"template scaffolding reached the top of the corpus ranking: {leaked} "
        f"(top terms: {terms})"
    )

    # The brief's own acceptance assertion, and the one that was FALSE until the
    # producer line came out of the body: measured over 1,298 real series it ranked
    # `world`, `bank` and `world bank` at #1-#3 with 1,298 mentions each -- exactly one
    # per article, i.e. a count that tracks the channel's size rather than anything the
    # corpus is about.
    for producer_word in ("world bank", "bank", "world", "indicator"):
        assert producer_word not in terms, (
            f"{producer_word!r} is the PRODUCER, not the subject; it ranks in the top "
            f"{len(terms)} corpus terms (got: {terms}). It belongs to the source, which "
            "every surface already shows and an exact source filter already matches."
        )


def test_the_figures_themselves_are_not_indexed_as_keywords(db):
    """A column of digits is data, not vocabulary.

    The digit-code filter is on by default; this asserts it still holds for a body
    that is mostly numbers, because a corpus whose top terms are years would be
    useless and the failure would look like nothing at all.
    """
    _seed(db, areas=["FRA"], series=["NY.GDP.MKTP.CD"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=50)

    terms = {k.term for k in db.query(Keyword).all()}
    numeric = [t for t in terms if t.replace(".", "").replace("-", "").isdigit()]
    assert not numeric, f"figures became keywords: {numeric}"


def test_what_this_channel_adds_to_the_shared_vocabulary_is_known(db):
    """The vocabulary cost, pinned as a FACT rather than left to be rediscovered.

    An earlier cut of this test asserted the OPPOSITE and argued for it: the body
    carried ``{agency} · {series_id}`` because "the code is how a figure is reconciled
    against the producer, and removing it from the body would remove it from FTS too".
    Measuring it over 1,298 real series refuted the premise. The keyword index never
    sees a searchable code at all -- the tokenizer splits ``SP.DYN.LE00.IN`` on its
    dots, so what it indexes is ``dyn``, ``le00``, ``totl``, ``mktp`` -- and the line
    as a whole was a THIRD of the corpus's entire mention volume (30,358 -> 20,372
    without it) while owning the top three ranks outright.

    So what this channel contributes now is SUBJECT and AREA and nothing else, and
    that is what this test pins in both directions: the scaffolding is absent, and the
    subject is present (an empty index would satisfy the first half for free).
    """
    _seed(db, areas=["FRA", "DEU", "ITA"], series=["SP.POP.TOTL", "NY.GDP.MKTP.CD"])
    sc.sync_series_corpus(db, extractor=BaselineExtractor(), limit=200)

    counts = dict(db.execute(
        select(Keyword.term, func.count(KeywordMention.id))
        .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .group_by(Keyword.id)
    ).all())
    lower = {t.lower(): n for t, n in counts.items()}
    assert lower, "guard against an unindexed corpus passing every assertion below"

    # THE POSITIVE HALF -- the subject is indexed and findable, which is the whole
    # point of rulings 5/30/31 ("government data goes DEEP into search").
    assert any(k.startswith("population") for k in lower), sorted(lower)[:20]
    assert any(k.startswith("gdp") for k in lower), sorted(lower)[:20]

    # THE NEGATIVE HALF -- the producer's name is not vocabulary. It reaches the reader
    # through the source ("Official statistics (World Bank)") and an exact source
    # filter, neither of which costs the shared keyword index anything.
    assert "world bank" not in lower and "bank" not in lower, (
        f"the producer must not be indexed once per article: {lower}"
    )

    # ...nor are the dot-separated fragments of the machine identifier, which are the
    # DEBRIS of a code rather than the code. The intact identifier stays reachable
    # exactly, via /api/stats/figures?series_id= and this article's canonical URL.
    for fragment in ("totl", "mktp", "dyn", "le00", "pcap"):
        assert fragment not in lower, (
            f"{fragment!r} is a fragment of a series id, not a word: {lower}"
        )

    # And the prose scaffolding the first design leaked is GONE, not merely rarer.
    for gone in ("producer", "periods", "earliest", "dash", "score", "figure"):
        assert gone not in lower, f"{gone!r} is template scaffolding and must not be indexed"


def test_a_figure_is_never_shown_without_its_unit(db):
    """A bare number is a value without its unit -- the standing rule forbids it.

    The FIRST version of this test appended ``({unit})`` unconditionally and asserted
    ``"(years)" in body``. It passed with the unit REMOVED, because the World Bank's
    own label is "Life expectancy at birth (years)" -- so the guard was reading the
    producer's parenthetical and calling it ours, and the shipped code would have
    printed "(years) (years)". That is why the assertions below are split by whether
    the label already carries a qualifier: a fixture in which the two are
    indistinguishable cannot test which one produced the text.
    """
    # The producer already qualifies this one; the app must not double it.
    _t, already = sc.render_series(
        agency="worldbank", series_id="SP.DYN.LE00.IN", ref_area="FRA",
        points=[("2020", 82.3), ("2021", None)],
    )
    assert already.splitlines()[0] == "France — Life expectancy at birth (years)", already
    assert "(years) (years)" not in already, "the producer's own unit must not be doubled"
    assert "82.3" in already and "—" in already, "the figures and the published gap both stay"

    # ...and this one it does not, so the app states it rather than showing bare digits.
    _t, bare = sc.render_series(
        agency="worldbank", series_id="SP.POP.TOTL", ref_area="FRA",
        points=[("2020", 67_000_000.0)],
    )
    assert bare.splitlines()[0] == "France — Population, total (people)", bare

    # The producer and the series id are absent from BOTH -- the property the two tests
    # above pin from the index side, pinned here at the source.
    for body in (already, bare):
        assert "World Bank" not in body, body
    assert "SP.DYN.LE00.IN" not in already and "SP.POP.TOTL" not in bare


def test_an_indicator_with_no_unit_renders_without_an_empty_bracket(db):
    """The twin. A code the catalog does not know must not print ``()``.

    An unconditional f-string would, and it would read as a unit the producer did not
    state rather than as one this app does not hold.
    """
    _t, body = sc.render_series(
        agency="worldbank", series_id="ZZ.UNKNOWN.CODE", ref_area="FRA",
        points=[("2020", 1.0)],
    )
    assert body.splitlines()[0] == "France — ZZ.UNKNOWN.CODE", body
    assert "()" not in body and "( )" not in body, body


def test_every_catalog_indicator_states_its_unit_somewhere_in_the_heading(db):
    """The rule holds for the WHOLE catalog, not the three specimens above.

    The parenthetical convention is the PRODUCER's, so a future indicator whose label
    breaks it would silently ship a column of digits with nothing saying what they
    measure. This is the guard that notices.
    """
    from src.stats.indicators import INDICATOR_CATALOG

    naked = []
    for ind_meta in INDICATOR_CATALOG:
        _t, body = sc.render_series(
            agency="worldbank", series_id=ind_meta["id"], ref_area="FRA",
            points=[("2020", 1.0)],
        )
        head = body.splitlines()[0]
        if "(" not in head:
            naked.append((ind_meta["id"], head))
    assert not naked, f"these render as bare figures with no unit stated: {naked}"


# --------------------------------------------------------------------------- #
# The job wiring
# --------------------------------------------------------------------------- #


def test_the_endpoints_are_composed_where_the_caller_expects_them():
    """Prefix + decorator composed, matched against the path the UI would call.

    Asserting the two strings side by side is what let a /api/backup/... vs
    /api/backup/v2/... mismatch 404 in the field, so the route is COMPOSED here.
    """
    from src.api.governments import router

    # APIRouter stores the COMPOSED path on the route, so the prefix is already in
    # it — prepending it again is how this test failed on correct code the first time.
    # router.routes (the router's OWN definitions), never app.routes: a positive
    # assertion against the shared mutable app singleton is what made an earlier route
    # guard flaky in CI and never reproducible locally.
    paths = {r.path for r in router.routes}
    assert router.prefix == "/api/governments"
    assert "/api/governments/series-corpus" in paths
    assert "/api/governments/series-corpus/status" in paths

    # ...and the CALLER asks for exactly those. Asserting only that the backend defines
    # a route proves nothing about whether anything reaches it — a /api/backup/... vs
    # /api/backup/v2/... mismatch 404'd in the field with both halves individually
    # correct, which is why the frontend side is checked here rather than trusted.
    app_js = (Path(__file__).resolve().parents[1] / "src" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    called = set(re.findall(r'api\(\s*"(/api/governments/series-corpus[^"]*)"', app_js))
    assert called, "no frontend caller reaches the endpoint — a job nobody can start"
    assert called <= paths, f"the UI calls routes the router does not define: {called - paths}"


def test_the_job_is_a_writer_and_is_cancellable():
    """Both flags are load-bearing rather than decorative.

    `is_writer` is what makes it arbitrate with collection instead of racing it, and
    `cancellable` is a promise BackgroundJob's own docstring reserves for workers that
    genuinely stop early — this one checks between series and between batches.
    """
    from src.api.governments import _SERIES_CORPUS_JOB

    assert _SERIES_CORPUS_JOB.is_writer is True
    assert _SERIES_CORPUS_JOB.cancellable is True


def test_the_worker_reports_an_interrupted_run_as_incomplete(db, monkeypatch):
    """A cancelled walk must not report the tally it reached as a finished one."""
    from src.api import governments as gov

    _seed(db, areas=["FRA", "DEU", "ITA"], series=["NY.GDP.MKTP.CD"])

    class _Ctx:
        stopping = True
        def set_progress(self, **kw): pass

    monkeypatch.setattr(gov, "session_scope", lambda: _NullCtx(db))
    out = gov._series_corpus_worker(_Ctx(), agency="worldbank", batch=10)
    assert out["complete"] is False
    assert out["created"] == 0, "a run that stops before its first batch creates nothing"


class _NullCtx:
    """session_scope() stand-in that yields the test session without closing it."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False


def test_the_worker_walks_every_series_and_says_so(db, monkeypatch):
    from src.api import governments as gov

    _seed(db, areas=["FRA", "DEU", "ITA", "ESP", "USA"], series=["NY.GDP.MKTP.CD"])

    class _Ctx:
        stopping = False
        def set_progress(self, **kw): pass

    monkeypatch.setattr(gov, "session_scope", lambda: _NullCtx(db))
    out = gov._series_corpus_worker(_Ctx(), agency="worldbank", batch=2)

    assert out["complete"] is True
    assert out["created"] == 5, out
    assert db.query(func.count(Article.id)).scalar() == 5

    # ...and a second pass is a no-op, which is what makes it safe to schedule.
    again = gov._series_corpus_worker(_Ctx(), agency="worldbank", batch=2)
    assert again["created"] == 0 and again["unchanged"] == 5
    assert db.query(func.count(Article.id)).scalar() == 5
