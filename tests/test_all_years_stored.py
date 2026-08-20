"""Ruling 6 — "store all years" — proven end to end, not assumed (T7 verify-first).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-08-07 rulings asked for every year of a producer's series to be stored, and the
pagination fix (A1) made the FETCH capable of it. Nothing proved the whole chain, and the
chain is where a truncation would actually live: a `date=` range on the URL, a `limit` in
the store, a slice on the read. So this drives fetch -> store -> read with a 65-year
series arriving across three pages and asserts every year survives each hop.

The second half is the honesty twin. `GET /country/{iso}` bounds its series with
`history` (default 30) for the sparklines, which is a legitimate DISPLAY bound over a
complete store — but a bound nobody states cannot be told apart from a producer whose
series simply starts later, and a sparkline invites exactly that reading. So the response
carries `series_stored` per indicator and a `history` block naming what was cut. Both
directions are pinned: a truncated response must SAY so, and an untruncated one must not
claim a shortfall it did not make (an over-eager disclosure is the same defect pointing
the other way, and it reads as conservative while being false).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base
from src.stats import store
from src.stats.fetch import fetch_worldbank

# The producer's real span for a long-running indicator: 1960..2024 inclusive.
_FIRST_YEAR, _LAST_YEAR = 1960, 2024
_ALL_YEARS = [str(y) for y in range(_FIRST_YEAR, _LAST_YEAR + 1)]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _obs(year: str, value: float | None) -> dict:
    return {
        "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
        "country": {"id": "FR", "value": "France"},
        "countryiso3code": "FRA",
        "date": year,
        "value": value,
    }


def _paged_getter(pages: list[list[dict]]):
    """Serve `pages` in order, reporting the true page count in every meta."""
    served: list[str] = []

    def getter(url: str):
        served.append(url)
        idx = len(served) - 1
        rows = pages[idx] if idx < len(pages) else []
        return _Resp([{"page": idx + 1, "pages": len(pages), "per_page": 30}, rows])

    getter.served = served  # type: ignore[attr-defined]
    return getter


def test_a_65_year_series_survives_fetch_store_and_read_in_full(db):
    """The whole chain, one assertion per hop — no year may be lost at any of them."""
    # A published GAP in the middle: it must be carried like any other year, because a
    # dropped gap would silently shorten the series in exactly the direction that reads
    # as "the producer started later".
    rows = [_obs(y, None if y == "1987" else float(y)) for y in _ALL_YEARS]
    pages = [rows[0:30], rows[30:60], rows[60:]]
    getter = _paged_getter(pages)

    figures = fetch_worldbank("NY.GDP.MKTP.CD", "FRA", get=getter, extracted_at="v1")

    # hop 1 — fetch
    assert len(getter.served) == 3, "all three pages must be requested"
    assert sorted(f.time_period for f in figures) == sorted(_ALL_YEARS), (
        "every published year must survive the fetch; a short series here is the "
        "pre-pagination defect returning"
    )

    # hop 2 — store
    tally = store.store_figures(db, figures)
    db.commit()
    assert tally["stored"] == len(_ALL_YEARS), tally
    assert tally["gaps"] == 1, "the published gap is stored and reported, never dropped"

    # hop 3 — read back
    got = store.list_figures(
        db, series_id="NY.GDP.MKTP.CD", ref_area="FRA", latest_vintage_only=True, limit=10_000
    )["figures"]
    assert sorted(str(f["time_period"]) for f in got) == sorted(_ALL_YEARS), (
        "the store must return every year it was given"
    )
    gap = [f for f in got if str(f["time_period"]) == "1987"]
    assert gap and gap[0]["value"] is None, "a gap reads back as None, never as zero"


def test_the_url_asks_for_no_date_range(db):
    """A `date=` parameter would cap the years at the SOURCE, before anything else runs.

    Cheap, and the one truncation the end-to-end test above could never see: it would
    make the fixture and the production URL agree on a shortened series.
    """
    from src.stats.fetch import worldbank_url

    url = worldbank_url("NY.GDP.MKTP.CD", "FRA")
    assert "date=" not in url, f"the fetch must not bound the years at the source: {url}"


# --------------------------------------------------------------------------- #
# The display bound is a DISPLAY bound — and it says so
# --------------------------------------------------------------------------- #


def _country_payload(db, *, years: list[str], history: int | None = None):
    from src.api.governments import country_data

    figs = [
        store.StatFigure(  # type: ignore[attr-defined]
            agency="worldbank",
            series_id="NY.GDP.MKTP.CD",
            ref_area="FRA",
            time_period=y,
            value=float(y),
            unit="USD",
            methodology_ref=None,
            adjustment=None,
            base_year=None,
            extracted_at="v1",
        )
        for y in years
    ]
    store.store_figures(db, figs)
    db.commit()
    kwargs = {} if history is None else {"history": history}
    return country_data("FRA", db=db, **kwargs)


def test_a_truncated_history_names_what_it_cut(db):
    payload = _country_payload(db, years=_ALL_YEARS)  # default history=30
    gdp = next(i for i in payload["indicators"] if i["id"] == "NY.GDP.MKTP.CD")

    assert len(gdp["series"]) == 30, "the display bound still applies"
    assert gdp["series_stored"] == len(_ALL_YEARS), (
        "the payload must state how many periods are STORED, not only how many it sent"
    )
    assert payload["history"]["limit"] == 30
    assert "NY.GDP.MKTP.CD" in payload["history"]["truncated"], (
        "a series that was cut must be named; otherwise a reader cannot tell a bound "
        "from a producer that started reporting later"
    )
    # The years kept are the RECENT ones, and they are contiguous with the stored tail.
    assert gdp["series"][-1]["year"] == str(_LAST_YEAR)
    assert gdp["series"][0]["year"] == str(_LAST_YEAR - 29)


def test_an_untruncated_history_claims_no_shortfall(db):
    """The negative-space twin: no cut, no claim.

    An over-eager disclosure invents a gap, which is the same fabrication as hiding one
    and looks conservative while doing it.
    """
    payload = _country_payload(db, years=_ALL_YEARS, history=1000)
    gdp = next(i for i in payload["indicators"] if i["id"] == "NY.GDP.MKTP.CD")

    assert len(gdp["series"]) == len(_ALL_YEARS)
    assert gdp["series_stored"] == len(_ALL_YEARS)
    assert payload["history"]["truncated"] == [], (
        "nothing was cut, so nothing may be reported as cut"
    )


def test_an_indicator_with_no_figures_is_not_reported_as_truncated(db):
    """An empty series is a GAP, not a shortfall — the two must not collapse."""
    payload = _country_payload(db, years=["2020"])
    empty = next(i for i in payload["indicators"] if i["id"] == "SI.POV.GINI")

    assert empty["series"] == [] and empty["latest"] is None
    assert empty["series_stored"] == 0
    assert "SI.POV.GINI" not in payload["history"]["truncated"]
