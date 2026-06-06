"""
Tests for market price extraction, ingestion, and the markets API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The point of these tests is the honesty contract: a price exists ONLY when the
rule lands on a real number; every miss yields an explicit reason and stores
nothing. Number parsing is pinned across the common money formats.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, CommodityPrice, MarketExtractionRule, Source
from src.ingest import EthicalFetcher
from src.markets.extract import extract_price, parse_number
from src.markets.pipeline import run_rule

# --------------------------------------------------------------------------- #
# parse_number
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("text,expected", [
    ("$1,234.56", 1234.56),
    ("1.234,56", 1234.56),          # EU grouping + decimal comma
    ("1 234.56", 1234.56),          # space grouping
    (" 2 999,00 €", 2999.00),  # nbsp grouping, decimal comma
    ("12,5%", 12.5),                # decimal comma, percent stripped
    ("USD 45.30 / kg", 45.30),
    ("1,234", 1234.0),              # lone comma, 3 trailing -> grouping
    ("12,56", 12.56),               # lone comma, 2 trailing -> decimal
    ("1.234.567", 1234567.0),       # repeated dots -> grouping
    ("1.234", 1.234),               # lone dot -> decimal mark
    ("-3.5", -3.5),
    ("price: 0", 0.0),
])
def test_parse_number_formats(text, expected):
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "  ", None, "N/A", "—", "no digits here"])
def test_parse_number_rejects_non_numbers(text):
    assert parse_number(text) is None


# --------------------------------------------------------------------------- #
# extract_price
# --------------------------------------------------------------------------- #

_PAGE = """
<html><body>
  <div class="quote"><span id="last">$ 1,250.75</span></div>
  <div class="meta" data-value="98.6">Index</div>
  <p class="blurb">Closed at 42 USD/kg on heavy volume.</p>
  <span class="empty">N/A</span>
</body></html>
"""


def test_extract_by_selector_text():
    r = extract_price(_PAGE, selector="#last")
    assert r.ok and r.value == pytest.approx(1250.75)


def test_extract_by_attribute():
    r = extract_price(_PAGE, selector="div.meta", attribute="data-value")
    assert r.ok and r.value == pytest.approx(98.6)


def test_extract_with_value_regex_capture():
    r = extract_price(_PAGE, selector="p.blurb", value_regex=r"at\s+([\d.]+)\s*USD")
    assert r.ok and r.value == pytest.approx(42.0)


def test_extract_missing_element_is_explicit_failure():
    r = extract_price(_PAGE, selector="#nope")
    assert not r.ok and r.value is None
    assert "no element" in r.reason


def test_extract_unparseable_is_explicit_failure():
    r = extract_price(_PAGE, selector="span.empty")
    assert not r.ok and r.value is None
    assert "no parseable number" in r.reason


def test_extract_bad_regex_is_reported():
    r = extract_price(_PAGE, selector="#last", value_regex=r"([")
    assert not r.ok and "invalid value_regex" in r.reason


# --------------------------------------------------------------------------- #
# run_rule (ingestion) + API
# --------------------------------------------------------------------------- #

class FakeResponse:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url


class FakeSession:
    def __init__(self):
        self.headers = {}
        self._routes = {}

    def route(self, url, **kw):
        self._routes[url] = FakeResponse(url=url, **kw)

    def get(self, url, timeout=None, allow_redirects=True):
        return self._routes.get(url, FakeResponse(status_code=404, text="nf", url=url))


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Metals Exchange", domain="metals.test", language="en"))
    s.commit()
    yield s
    s.close()


def _rule(db, **kw):
    src = db.query(Source).first()
    defaults = {
        "source_id": src.id, "symbol": "Nd", "category": "commodity",
        "url": "https://metals.test/nd", "selector": "#price",
        "currency": "USD", "unit": "kg", "market": "spot", "enabled": True,
    }
    defaults.update(kw)
    r = MarketExtractionRule(**defaults)
    db.add(r)
    db.commit()
    return r


def test_run_rule_stores_price(db):
    rule = _rule(db)
    sess = FakeSession()
    sess.route("https://metals.test/robots.txt", status_code=404, text="")
    sess.route("https://metals.test/nd",
               text='<html><body><span id="price">$ 84.50</span></body></html>')
    out = run_rule(db, rule, fetcher=EthicalFetcher(min_interval_s=0.0, session=sess))
    assert out.status == "stored_price"
    assert out.value == pytest.approx(84.50)
    cp = db.query(CommodityPrice).one()
    assert cp.symbol == "Nd" and cp.price == pytest.approx(84.50)
    assert cp.source.startswith("market-rule:")

    # Second run the same day is a duplicate, not a second point.
    out2 = run_rule(db, rule, fetcher=EthicalFetcher(min_interval_s=0.0, session=sess))
    assert out2.status == "duplicate_price"
    assert db.query(CommodityPrice).count() == 1


def test_run_rule_no_match_stores_nothing(db):
    rule = _rule(db, selector="#does-not-exist")
    sess = FakeSession()
    sess.route("https://metals.test/robots.txt", status_code=404, text="")
    sess.route("https://metals.test/nd", text="<html><body><span id='price'>84</span></body></html>")
    out = run_rule(db, rule, fetcher=EthicalFetcher(min_interval_s=0.0, session=sess))
    assert out.status == "no_match"
    assert db.query(CommodityPrice).count() == 0
    assert rule.last_status.startswith("no_match")


def test_run_rule_blocked_robots(db):
    rule = _rule(db)
    sess = FakeSession()
    sess.route("https://metals.test/robots.txt", text="User-agent: *\nDisallow: /")
    sess.route("https://metals.test/nd", text="<html><body><span id='price'>84</span></body></html>")
    out = run_rule(db, rule, fetcher=EthicalFetcher(min_interval_s=0.0, session=sess))
    assert out.status == "blocked_robots"
    assert db.query(CommodityPrice).count() == 0


def test_markets_api_crud_and_overview(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.database.session import init_db, session_scope

    init_db()
    domain = f"mkt-{uuid.uuid4().hex}.test"
    with session_scope() as s:
        s.add(Source(name="MKT Probe", domain=domain))
    from src.api.main import app

    with TestClient(app) as client:
        with session_scope() as s:
            sid = s.query(Source).filter_by(domain=domain).first().id

        created = client.post("/api/markets/rules", json={
            "source_id": sid, "symbol": "ZZTEST", "url": "https://x.test/p",
            "selector": "#p", "category": "commodity",
        })
        assert created.status_code == 200
        rid = created.json()["id"]

        # Invalid category rejected.
        bad = client.post("/api/markets/rules", json={
            "source_id": sid, "symbol": "Q", "url": "https://x.test/p",
            "selector": "#p", "category": "weather",
        })
        assert bad.status_code == 400

        lst = client.get("/api/markets/rules?category=commodity").json()
        assert any(r["id"] == rid for r in lst["rules"])

        ov = client.get("/api/markets/overview?category=commodity").json()
        entry = next(i for i in ov["items"] if i["id"] == rid)
        assert entry["points"] == 0 and entry["latest"] is None

        assert client.put(f"/api/markets/rules/{rid}", json={"label": "Test"}).json()["label"] == "Test"
        assert client.delete(f"/api/markets/rules/{rid}").json()["deleted"] == rid

        # Clean up the probe source.
        with session_scope() as s:
            s.query(Source).filter_by(domain=domain).delete()
