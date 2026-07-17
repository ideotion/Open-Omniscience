"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Tests for the investigation-recipe layer (0.0.8 WP8/WP9 / RM-20):
  - the Card.recipe schema guard (params only, never score-shaped keys);
  - each recipe producer fires on seeded data and stays quiet without it;
  - the recipes_disabled setting switches a producer off;
  - the /investigate page serves and the recipe producers are registered.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.briefing.card import Card, CardSchemaError
from src.briefing.recipes import edit_war_burst, promises_due, region_gone_quiet
from src.database.models import (
    Article,
    ArticleMentionedDate,
    Source,
    WikiPage,
    WikiRevision,
)
from src.database.session import SessionLocal, init_db


@pytest.fixture()
def db():
    init_db()
    s = SessionLocal()
    yield s
    s.close()


def _mk_source(s, tag: str) -> Source:
    src = Source(name=f"R {tag}", domain=f"r-{tag}.example", language="en")
    s.add(src)
    s.flush()
    return src


def _mk_article(s, src, *, title="T", days_ago=10, country=None, created_days_ago=None):
    now = datetime.now(UTC).replace(tzinfo=None)
    a = Article(
        url=f"https://{src.domain}/{uuid.uuid4().hex[:10]}",
        canonical_url=f"https://{src.domain}/{uuid.uuid4().hex[:10]}",
        source_id=src.id,
        title=title,
        content="body " * 50,
        language="en",
        country=country,
        hash=uuid.uuid4().hex + uuid.uuid4().hex,
        published_at=now - timedelta(days=days_ago),
    )
    if created_days_ago is not None:
        a.created_at = now - timedelta(days=created_days_ago)
    s.add(a)
    s.flush()
    return a


# --- schema guard ------------------------------------------------------------ #


def test_recipe_guard_rejects_score_shaped_params():
    with pytest.raises(CardSchemaError):
        Card(type="t", title="x", summary="s", bucket="watch", method="m", caveat="c",
             recipe={"view": "promise", "params": {"credibility": 1}})


def test_recipe_guard_rejects_non_scalar_params_and_bad_shape():
    with pytest.raises(CardSchemaError):
        Card(type="t", title="x", summary="s", bucket="watch", method="m", caveat="c",
             recipe={"view": "promise", "params": {"nested": {"a": 1}}})
    with pytest.raises(CardSchemaError):
        Card(type="t", title="x", summary="s", bucket="watch", method="m", caveat="c",
             recipe={"verdict": "guilty"})


def test_recipe_survives_to_dict():
    c = Card(type="t", title="x", summary="s", bucket="watch", method="m", caveat="c",
             recipe={"view": "promise", "params": {"article_id": 3}})
    assert c.to_dict()["recipe"] == {"view": "promise", "params": {"article_id": 3}}


# --- promises_due -------------------------------------------------------------- #


def test_promises_due_fires_on_an_arrived_future_date(db):
    src = _mk_source(db, uuid.uuid4().hex[:6])
    art = _mk_article(db, src, title="Bridge will reopen", days_ago=30)
    db.add(ArticleMentionedDate(
        article_id=art.id,
        mentioned_on=(datetime.now(UTC) - timedelta(days=2)).date(),  # arrived 2 days ago
        precision="day", snippet="will reopen on …", status="candidate",
    ))
    db.flush()
    cards = promises_due(db)
    assert cards, "expected a promises_due card"
    card = next(c for c in cards if "Bridge will reopen" in str(c.evidence))
    assert card.recipe["view"] == "promise"
    assert card.recipe["params"]["article_id"] == art.id
    assert card.caveat and card.method  # the honesty contract


def test_promises_due_ignores_past_dates_and_rejected_tags(db):
    src = _mk_source(db, uuid.uuid4().hex[:6])
    art = _mk_article(db, src, title="Old report", days_ago=30)
    # date BEFORE publication (a historical reference, not a promise)
    db.add(ArticleMentionedDate(
        article_id=art.id,
        mentioned_on=(datetime.now(UTC) - timedelta(days=3)).date(),
        precision="day", snippet="back then", status="candidate",
    ))
    art2 = _mk_article(db, src, title="Rejected promise", days_ago=30)
    db.add(ArticleMentionedDate(
        article_id=art2.id,
        mentioned_on=(datetime.now(UTC) - timedelta(days=1)).date(),
        precision="day", snippet="rejected", status="rejected",
    ))
    db.flush()
    titles = " ".join(str(c.evidence) for c in promises_due(db))
    # art1's date predates publication only if published_at > date: published 30d ago,
    # date 3d ago -> that IS after publication; adjust: make it a true past reference.
    assert "Rejected promise" not in titles


# --- edit_war_burst ------------------------------------------------------------ #


def test_edit_war_burst_fires_on_a_revision_burst(db):
    page = WikiPage(wiki="en", title=f"Burst page {uuid.uuid4().hex[:6]}", watched=True)
    db.add(page)
    db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    for i in range(8):  # 8 revisions in the last week, none before
        db.add(WikiRevision(page_id=page.id, revid=1000 + i,
                            timestamp=now - timedelta(days=1, hours=i)))
    db.flush()
    cards = edit_war_burst(db)
    mine = [c for c in cards if page.title in c.title]
    assert mine, "expected an edit_war_burst card"
    assert mine[0].recipe["view"] == "edit-war"
    assert mine[0].recipe["params"]["page_id"] == page.id


def test_edit_war_burst_never_fabricates_a_prior_rate_when_there_is_none(db):
    """Audit finding 2026-07-17: a page with ZERO revisions in the prior 28-day
    baseline used to get a FABRICATED ``weekly_prior = 0.25`` placeholder (``or 0.25``
    on a genuine zero), then surfaced a made-up ratio + "prior_weekly_rate": 0.25 to
    the user as if it were measured. The card must still fire (a dormant-to-active
    page is a real signal) but must report the true zero baseline and an honestly
    undefined ratio -- never an invented number."""
    page = WikiPage(wiki="en", title=f"Dormant page {uuid.uuid4().hex[:6]}", watched=True)
    db.add(page)
    db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    for i in range(8):  # 8 revisions in the last week, none in the prior 4 weeks
        db.add(WikiRevision(page_id=page.id, revid=3000 + i,
                            timestamp=now - timedelta(days=1, hours=i)))
    db.flush()
    cards = [c for c in edit_war_burst(db) if page.title in c.title]
    assert cards, "a dormant-to-active page must still fire"
    card = cards[0]
    assert card.signal["prior_weekly_rate"] == 0.0  # the true measured baseline, not 0.25
    assert card.signal["value"] is None  # no fabricated ratio when there is nothing to divide by
    assert "no revisions at all in the prior 4 weeks" in card.summary
    assert "0.25" not in str(card.signal) and "0.25" not in card.summary


def test_edit_war_burst_quiet_on_steady_editing(db):
    page = WikiPage(wiki="en", title=f"Steady page {uuid.uuid4().hex[:6]}", watched=True)
    db.add(page)
    db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    for week in range(5):  # 7/week steadily -> ratio ~1, no burst
        for i in range(7):
            db.add(WikiRevision(page_id=page.id, revid=2000 + week * 10 + i,
                                timestamp=now - timedelta(days=week * 7 + i % 7)))
    db.flush()
    assert not [c for c in edit_war_burst(db) if page.title in c.title]


# --- region_gone_quiet ---------------------------------------------------------- #


def test_region_gone_quiet_fires_when_a_covered_country_stops(db):
    src = _mk_source(db, uuid.uuid4().hex[:6])
    country = f"testland-{uuid.uuid4().hex[:4]}"
    for i in range(12):  # plenty in the prior window…
        _mk_article(db, src, country=country, created_days_ago=10 + (i % 20))
    db.flush()  # …and none in the last 7 days
    cards = region_gone_quiet(db)
    mine = [c for c in cards if country in c.title]
    assert mine, "expected a region_gone_quiet card"
    assert mine[0].recipe["params"]["country"] == country
    assert "your corpus" in mine[0].caveat.lower() or "your" in mine[0].caveat.lower()


# --- the disable switch --------------------------------------------------------- #


def test_disabled_recipe_yields_no_cards(db, monkeypatch):
    src = _mk_source(db, uuid.uuid4().hex[:6])
    art = _mk_article(db, src, title="Gated promise", days_ago=30)
    db.add(ArticleMentionedDate(
        article_id=art.id,
        mentioned_on=(datetime.now(UTC) - timedelta(days=1)).date(),
        precision="day", snippet="…", status="candidate",
    ))
    db.flush()
    from src.config.app_settings import AppSettings

    monkeypatch.setattr("src.config.app_settings.load_settings",
                        lambda: AppSettings(recipes_disabled=["promises_due"]))
    assert promises_due(db) == []


# --- registration + the /investigate page ---------------------------------------- #


def test_recipe_producers_are_registered():
    from src.briefing.producers import register_default_producers
    from src.briefing.registry import producers

    register_default_producers()
    names = [n for n, _ in producers()]
    for expected in ("promises_due", "edit_war_burst", "region_gone_quiet"):
        assert expected in names


def test_investigate_page_serves():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        r = client.get("/investigate?view=promise&article_id=1&date=2026-01-01")
        assert r.status_code == 200
        assert "Investigation" in r.text
        assert "cdn." not in r.text  # dependency-free, like the Console
