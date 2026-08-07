"""World Bank pagination (field feedback 2026-08-07, item 8 / brief slice A1).

``fetch_worldbank`` made exactly ONE request and discarded the page meta, so for
``country=all`` — ~266 economies x ~65 years — roughly 94% of every indicator was
silently missing and read as "no data" rather than as a truncated fetch.

The skeptic lens the brief mandates for this slice is RESOURCE EXHAUSTION, so most of
what follows is negative space: a payload that cannot say how many pages there are, one
that claims a million, and one whose tail is empty must all TERMINATE. The positive test
alone would pass against a `while True`.
"""

from __future__ import annotations

import pytest

from src.stats.fetch import _WORLDBANK_MAX_PAGES, fetch_worldbank, worldbank_url


class _Resp:
    """Minimal requests-like response for the injectable getter."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _obs(country_iso3: str, year: str, value: float | None = 1.0) -> dict:
    return {
        "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
        "country": {"id": country_iso3[:2], "value": country_iso3},
        "countryiso3code": country_iso3,
        "date": year,
        "value": value,
    }


def _page(pages: int, rows: list[dict], *, page: int = 1) -> list:
    return [{"page": page, "pages": pages, "per_page": 2, "total": pages * 2}, rows]


class _Recorder:
    """A getter that serves a scripted list of payloads and records every URL asked."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.urls: list[str] = []

    def __call__(self, url: str):
        self.urls.append(url)
        if not self.payloads:
            raise AssertionError(f"unexpected extra request: {url}")
        return _Resp(self.payloads.pop(0))


# --------------------------------------------------------------------------- #
# The positive case
# --------------------------------------------------------------------------- #


def test_three_pages_are_all_fetched_in_order():
    getter = _Recorder([
        _page(3, [_obs("FRA", "2020"), _obs("FRA", "2019")], page=1),
        _page(3, [_obs("DEU", "2020"), _obs("DEU", "2019")], page=2),
        _page(3, [_obs("ITA", "2020"), _obs("ITA", "2019")], page=3),
    ])
    figures = fetch_worldbank("NY.GDP.MKTP.CD", "all", get=getter, extracted_at="2026-08-07")

    assert len(figures) == 6, "every page's rows must survive, not just page 1"
    assert [f.ref_area for f in figures] == ["FRA", "FRA", "DEU", "DEU", "ITA", "ITA"], (
        "pages must concatenate in order — a reordered series would misreport which "
        "observation is latest"
    )
    assert len(getter.urls) == 3
    # `&page=`, not `page=` — `per_page=1000` contains the shorter needle, so the loose
    # version passes for free (and did, on the first run of this file).
    assert "&page=" not in getter.urls[0], "page 1 is the server default; omit the param"
    assert "&page=2" in getter.urls[1] and "&page=3" in getter.urls[2]


def test_one_vintage_stamps_every_page():
    """A series fetched across several requests is ONE vintage, not a smear of them."""
    getter = _Recorder([
        _page(2, [_obs("FRA", "2020")], page=1),
        _page(2, [_obs("DEU", "2020")], page=2),
    ])
    figures = fetch_worldbank("X", "all", get=getter, extracted_at="2026-08-07T00:00:00Z")
    assert {f.extracted_at for f in figures} == {"2026-08-07T00:00:00Z"}


def test_single_page_is_byte_identical_to_the_pre_pagination_behaviour():
    """The acceptance criterion: one page in, one request out, same rows, same URL."""
    getter = _Recorder([_page(1, [_obs("FRA", "2020"), _obs("FRA", "2019")])])
    figures = fetch_worldbank("NY.GDP.MKTP.CD", "all", get=getter, extracted_at="v")

    assert len(figures) == 2
    assert len(getter.urls) == 1
    assert getter.urls[0] == worldbank_url("NY.GDP.MKTP.CD", "all", per_page=1000), (
        "the URL doubles as the Tor circuit-isolation token, so a single-page fetch's "
        "URL must not change shape"
    )


# --------------------------------------------------------------------------- #
# Negative space: every unreadable or hostile meta must TERMINATE
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "meta",
    [
        {"page": 1, "pages": 1},           # honestly one page
        {"page": 1, "pages": 0},           # nonsense low
        {"page": 1, "pages": -5},          # nonsense negative
        {"page": 1},                       # no pages key at all
        {"page": 1, "pages": None},        # explicit null
        {"page": 1, "pages": "many"},      # non-numeric
        {"page": 1, "pages": [2]},         # wrong type entirely
    ],
    ids=["one", "zero", "negative", "missing", "null", "non-numeric", "wrong-type"],
)
def test_an_unreadable_page_count_issues_exactly_one_request(meta):
    """'I could not tell how many pages' must mean STOP, never 'keep going'."""
    getter = _Recorder([[meta, [_obs("FRA", "2020")]]])
    figures = fetch_worldbank("X", "all", get=getter, extracted_at="v")
    assert len(getter.urls) == 1
    assert len(figures) == 1


def test_a_bare_observation_list_with_no_meta_issues_exactly_one_request():
    """The parser tolerates a bare list; the fetcher must not then loop forever."""
    getter = _Recorder([[_obs("FRA", "2020")]])
    figures = fetch_worldbank("X", "all", get=getter, extracted_at="v")
    assert len(getter.urls) == 1
    assert len(figures) == 1


def test_a_meta_claiming_a_million_pages_stops_at_the_ceiling():
    """A hostile or broken meta must not spin. The ceiling bounds REQUESTS."""
    payloads = [_page(1_000_000, [_obs("FRA", str(2000 + i))], page=i + 1) for i in range(400)]
    getter = _Recorder(payloads)
    figures = fetch_worldbank("X", "all", get=getter, extracted_at="v")

    assert len(getter.urls) == _WORLDBANK_MAX_PAGES
    assert len(figures) == _WORLDBANK_MAX_PAGES


def test_hitting_the_ceiling_logs_that_the_series_is_truncated(caplog):
    """A short answer must never be returned SILENTLY — that is the fabrication."""
    payloads = [_page(1_000_000, [_obs("FRA", str(2000 + i))], page=i + 1) for i in range(400)]
    with caplog.at_level("WARNING"):
        fetch_worldbank("NY.GDP.MKTP.CD", "all", get=_Recorder(payloads), extracted_at="v")
    assert any("TRUNCATED" in r.message or "TRUNCATED" in r.getMessage() for r in caplog.records)


def test_an_empty_page_stops_the_loop_early():
    """`pages` can over-report. Stop rather than spend the rest of the budget on nothing."""
    getter = _Recorder([
        _page(10, [_obs("FRA", "2020")], page=1),
        _page(10, [_obs("DEU", "2020")], page=2),
        _page(10, [], page=3),
        # Pages 4..10 are deliberately NOT scripted: the recorder raises if asked.
    ])
    figures = fetch_worldbank("X", "all", get=getter, extracted_at="v")
    assert len(getter.urls) == 3
    assert len(figures) == 2


def test_no_page_is_requested_while_airplane_mode_is_engaged(monkeypatch):
    """The up-front refusal still fires, and fires BEFORE the first request."""
    monkeypatch.setattr("src.stats.fetch.kill_switch_active", lambda: True)
    getter = _Recorder([])
    with pytest.raises(RuntimeError, match="airplane"):
        fetch_worldbank("X", "all", get=getter)
    assert getter.urls == [], "a refusal that still opened a socket would not be a refusal"


def test_page_two_onward_goes_through_the_same_injectable_getter():
    """Every page must ride the guarded path, not just the first.

    Guards a plausible refactor in which the loop reaches for requests directly. The
    recorder IS the seam, so an unseen request would raise here.
    """
    getter = _Recorder([
        _page(2, [_obs("FRA", "2020")], page=1),
        _page(2, [_obs("DEU", "2020")], page=2),
    ])
    fetch_worldbank("X", "all", get=getter, extracted_at="v")
    assert len(getter.urls) == 2
    assert all(u.startswith("https://api.worldbank.org/v2/") for u in getter.urls)
