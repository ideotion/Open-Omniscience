"""
The period seam for card producers — the honesty problem the design record names.

Card producers took no period, so the Bulletin's card section computed against
"now" and said so. ``run_all_bounded`` now takes an ``as_of`` (exclusive) period
end and hands it to the producers that declare one; the rest are called exactly as
before. THE SECTION IS THEREFORE MIXED, and everything here is about not letting a
mixed section carry one verdict:

* ``as_of=None`` must be BYTE-IDENTICAL — Home passes nothing and must keep the
  cards it had, including the open upper bound that lets a future-dated mention in;
* an anchored producer must really receive the anchor, and an unanchored one must
  really not be handed a keyword it cannot take;
* ``matches_period`` is MEASURED — one unanchored card among many makes it False,
  which is the discriminating case a hardcoded True or False both miss;
* ``through_time`` anchors on ``end − 1 day`` and ``on_the_horizon`` on ``end``.
  They are one day apart and nothing about a passing test would say which shipped.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.briefing import producers as P
from src.briefing import registry as R
from src.briefing.card import Card
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_END = date(2026, 8, 1)  # exclusive period end; last covered day is 2026-07-31


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    try:
        yield s
    finally:
        s.close()


def _article(s, n, when=None):
    a = Article(
        url=f"https://s.test/{n}",
        canonical_url=f"https://s.test/{n}",
        source_id=1,
        title=f"Story {n}",
        content="body",
        hash=f"h{n}",
        published_at=when,
    )
    s.add(a)
    s.flush()
    return a


def _mention(s, kw, art, when):
    s.add(KeywordMention(keyword_id=kw.id, article_id=art.id, count=1, observed_on=when))


@pytest.fixture()
def _registry_reset():
    """The registry is a module global. Restore it, or a test here decides what a
    later file measures."""
    saved = list(R._REGISTRY)
    try:
        yield
    finally:
        R._REGISTRY = saved


# --------------------------------------------------------------------------- #
#  _articles_for_term: the window seam, both directions
# --------------------------------------------------------------------------- #
def test_an_explicit_end_excludes_a_mention_on_or_after_it(db):
    kw = Keyword(term="flood", normalized_term="flood", language="en")
    db.add(kw)
    db.flush()
    inside = _article(db, 1)
    on_the_boundary = _article(db, 2)
    _mention(db, kw, inside, _END - timedelta(days=1))
    _mention(db, kw, on_the_boundary, _END)  # the exclusive bound itself
    db.commit()

    rows = P._articles_for_term(db, kw.id, days=30, limit=10, end=_END)
    assert [a.id for a, _ in rows] == [inside.id], (
        "half-open [end - days, end): the boundary day belongs to the NEXT period, or "
        "consecutive editions double-count it"
    )


def test_no_end_keeps_the_open_upper_bound_exactly_as_before(db):
    """THE NEGATIVE-SPACE TWIN, and the one that catches an over-eager fix: the old
    query had NO upper bound, so a mention dated in the future is included. A version
    that always bounded the window would quietly drop it, and every ordinary fixture
    would still pass."""
    kw = Keyword(term="flood", normalized_term="flood", language="en")
    db.add(kw)
    db.flush()
    future = _article(db, 3)
    _mention(db, kw, future, date.today() + timedelta(days=2))
    db.commit()

    rows = P._articles_for_term(db, kw.id, days=30, limit=10)
    assert [a.id for a, _ in rows] == [future.id]


# --------------------------------------------------------------------------- #
#  the registry seam
# --------------------------------------------------------------------------- #
def test_only_a_producer_that_declares_as_of_is_offered_one(db, _registry_reset):
    seen: dict[str, object] = {}

    def anchored(session, *, as_of=None):
        seen["anchored"] = as_of
        return []

    def plain(session):
        seen["plain"] = "called with no anchor"
        return []

    R._REGISTRY = [("anchored", anchored), ("plain", plain)]
    _, stats = R.run_all_bounded(db, as_of=_END)
    assert seen["anchored"] == _END
    assert seen["plain"] == "called with no anchor"
    assert stats["anchored"] == ["anchored"]
    assert stats["unanchored"] == ["plain"]
    assert stats["as_of"] == _END.isoformat()


def test_without_an_anchor_no_producer_is_handed_one(db, _registry_reset):
    """Home's path. An anchorable producer called with no anchor must be called
    exactly as before — the seam is optional, so a core install is unchanged."""
    calls: list[dict] = []

    def anchored(session, *, as_of=None):
        calls.append({"as_of": as_of})
        return []

    R._REGISTRY = [("anchored", anchored)]
    _, stats = R.run_all_bounded(db)
    assert calls == [{"as_of": None}]
    assert "anchored" not in stats and "as_of" not in stats


def test_a_card_carries_the_producer_that_made_it(db, _registry_reset):
    def maker(session):
        return [
            Card(type="t", title="x", summary="y", bucket="watch", method="m", caveat="c")
        ]

    R._REGISTRY = [("maker", maker)]
    cards, _ = R.run_all_bounded(db)
    assert cards[0].produced_by == "maker"


def test_a_producer_that_sets_its_own_provenance_is_not_overwritten(db, _registry_reset):
    """Set-if-empty, so a card built elsewhere and re-emitted keeps its origin."""

    def maker(session):
        return [
            Card(
                type="t", title="x", summary="y", bucket="watch",
                method="m", caveat="c", produced_by="somewhere-else",
            )
        ]

    R._REGISTRY = [("maker", maker)]
    cards, _ = R.run_all_bounded(db)
    assert cards[0].produced_by == "somewhere-else"


def test_the_anchorable_set_is_read_from_signatures_not_a_hand_kept_list():
    """A list of names is a second place to update, and the one thing worse than an
    unanchored producer is a registry that believes it is anchored."""
    P.register_default_producers()
    got = R.period_anchorable()
    for name, producer in R.producers():
        declared = "as_of" in inspect.signature(producer).parameters
        assert got[name] is declared, name


def test_a_disabled_producer_is_counted_in_neither_list(db, _registry_reset, monkeypatch):
    """A producer the operator switched off did not decline the period — it did not
    run. Filing it under "unanchored" would report a coverage gap that is a settings
    choice."""

    def anchored(session, *, as_of=None):
        return []

    R._REGISTRY = [("anchored", anchored)]
    monkeypatch.setattr(R, "_disabled_names", lambda: frozenset({"anchored"}))
    _, stats = R.run_all_bounded(db, as_of=_END)
    assert stats["anchored"] == [] and stats["unanchored"] == []


# --------------------------------------------------------------------------- #
#  the section says which cards are the period's
# --------------------------------------------------------------------------- #
def _cards_section(db, monkeypatch, registry):
    from src.bulletin.cards import cards_by_type
    from src.bulletin.period import resolve_period

    monkeypatch.setattr(R, "_REGISTRY", registry)
    return cards_by_type(db, resolve_period("weekly", end=_END), articles_per_card=0)


def _card(kind="t", key=""):
    return Card(
        type=kind, title="x", summary="y", bucket="watch", method="m", caveat="c", key=key
    )


def test_a_section_of_only_anchored_cards_says_its_figures_are_the_periods(db, monkeypatch):
    def anchored(session, *, as_of=None):
        return [_card(key="a")]

    out = _cards_section(db, monkeypatch, [("anchored", anchored)])
    assert out["window"]["matches_period"] is True
    assert out["cards_period_anchored"] == out["cards_shown_total"] == 1
    assert "Every card here was computed against the period" in out["caveat"]


def test_one_unanchored_card_among_many_makes_the_section_not_the_periods(db, monkeypatch):
    """THE DISCRIMINATING CASE. A hardcoded False and a naive "any anchored → True"
    both pass a single-producer fixture; only a mixed one separates them."""

    def anchored(session, *, as_of=None):
        return [_card(kind="a", key="1"), _card(kind="a", key="2")]

    def plain(session):
        return [_card(kind="b", key="3")]

    out = _cards_section(db, monkeypatch, [("anchored", anchored), ("plain", plain)])
    assert out["window"]["matches_period"] is False
    assert out["cards_period_anchored"] == 2 and out["cards_shown_total"] == 3
    assert "Some cards here are anchored" in out["caveat"]


def test_a_section_of_only_unanchored_cards_keeps_the_original_wording(db, monkeypatch):
    def plain(session):
        return [_card(key="a")]

    out = _cards_section(db, monkeypatch, [("plain", plain)])
    assert out["window"]["matches_period"] is False
    assert "AS OBSERVED WHEN THIS EDITION WAS GENERATED" in out["caveat"]


def test_each_card_states_its_own_anchoring_and_names_its_producer(db, monkeypatch):
    def anchored(session, *, as_of=None):
        return [_card(kind="a", key="1")]

    def plain(session):
        return [_card(kind="b", key="2")]

    out = _cards_section(db, monkeypatch, [("anchored", anchored), ("plain", plain)])
    rows = {r["produced_by"]: r["period_anchored"] for t in out["types"] for r in t["cards"]}
    assert rows == {"anchored": True, "plain": False}


def test_both_producer_lists_travel_by_name(db, monkeypatch):
    def anchored(session, *, as_of=None):
        return [_card(kind="a", key="1")]

    def plain(session):
        return [_card(kind="b", key="2")]

    out = _cards_section(db, monkeypatch, [("anchored", anchored), ("plain", plain)])
    assert out["anchored_producers"] == ["anchored"]
    assert out["unanchored_producers"] == ["plain"]


def test_an_empty_section_does_not_claim_the_period(db, monkeypatch):
    """No cards is not "every card was anchored". An empty collection satisfies an
    all() for free, and a section with nothing in it must not report that its
    figures are the period's."""

    def anchored(session, *, as_of=None):
        return []

    out = _cards_section(db, monkeypatch, [("anchored", anchored)])
    assert out["cards_shown_total"] == 0
    assert out["window"]["matches_period"] is False


# --------------------------------------------------------------------------- #
#  the two clock producers, and the day between them
# --------------------------------------------------------------------------- #
def test_through_time_anchors_on_the_last_COVERED_day_not_the_exclusive_end(db):
    """One day apart, and the fixture makes them differ: articles are seeded on the
    period's LAST DAY in past years. Anchoring on `end` would look at 08-01 and find
    nothing."""
    last_day = _END - timedelta(days=1)  # 2026-07-31
    for i, yr in enumerate((2025, 2024, 2023)):
        _article(db, i, datetime(yr, last_day.month, last_day.day, 9, 0))
    db.commit()

    assert P.through_time(db, as_of=_END), "anchored on end - 1 day, it finds them"
    assert P.through_time(db, today=_END) == [], (
        "anchored on `end` itself it would look at the wrong calendar day — this is "
        "the assertion that says which one shipped"
    )


def test_an_explicit_today_still_wins_over_a_derived_anchor(db):
    """A derived clock silently overriding a named one is the two-notions-of-one-thing
    defect. The existing test-injection path must keep working."""
    day = date(2026, 3, 9)
    for i, yr in enumerate((2025, 2024, 2023)):
        _article(db, i, datetime(yr, day.month, day.day, 9, 0))
    db.commit()
    assert P.through_time(db, today=day, as_of=_END)


def test_on_the_horizon_anchors_on_the_exclusive_end_directly(db):
    """`end` is the first instant AFTER the period, so looking forward from it is
    exactly "what was on the horizon when this period closed"."""
    kw = Keyword(term="election", normalized_term="election", language="en")
    db.add(kw)
    db.flush()
    for i in range(4):
        a = _article(db, 100 + i)
        _mention(db, kw, a, _END - timedelta(days=1))
    db.commit()

    event = {
        "title": "General election",
        "tags": [],
        "next_occurrence": (_END + timedelta(days=10)).isoformat(),
        "id": "e1",
    }
    cards = P.on_the_horizon(db, as_of=_END, events=[event])
    assert cards, "an event ten days past the period end is on the horizon from it"

    far = dict(event, next_occurrence=(_END + timedelta(days=200)).isoformat())
    assert P.on_the_horizon(db, as_of=_END, events=[far]) == []


def test_on_the_horizon_also_lets_an_explicit_today_win(monkeypatch, db):
    """Found by a SURVIVING mutant: the precedence test above drives through_time,
    whose guard is a separate line, so `on_the_horizon`'s own ordering was unpinned
    and `as_of or today` passed everything. The fixture makes the two disagree — an
    event ten days past the period end is inside a 45-day horizon from `end` and
    outside one from June."""
    kw = Keyword(term="election", normalized_term="election", language="en")
    db.add(kw)
    db.flush()
    # INSIDE the trending window ending at `end`. Dated in June instead, the mutant
    # returned [] too — for want of a trending term rather than for the horizon — and
    # the fixture proved nothing. The discriminating input is the one where the two
    # versions really differ, and it is never the obvious example.
    for i in range(4):
        a = _article(db, 200 + i)
        _mention(db, kw, a, _END - timedelta(days=1))
    db.commit()

    event = {
        "title": "General election",
        "tags": [],
        "next_occurrence": (_END + timedelta(days=10)).isoformat(),
        "id": "e1",
    }
    june = date(2026, 6, 1)
    assert P.on_the_horizon(db, today=june, as_of=_END, events=[event]) == [], (
        "the explicit today must win: from June that event is 70 days out, past the "
        "45-day horizon"
    )


# --------------------------------------------------------------------------- #
#  it reaches the reader — a field nothing renders is a dead end
# --------------------------------------------------------------------------- #
def _rendered(anchored: bool | None) -> tuple[str, str]:
    from src.bulletin.render import render_html, render_markdown

    card: dict = {"title": "A card", "method": "m", "corpus_articles": 0}
    if anchored is not None:
        card["period_anchored"] = anchored
    ed = {
        "generated_at": "2026-08-01T09:00:00+00:00",
        "period": {"cadence": "weekly", "start": "2026-07-25", "last_day": "2026-07-31", "days": 7},
        "masthead": {},
        "sections": [
            {
                "section": "cards",
                "types": [{"type": "t", "cards_found": 1, "cards_shown": 1, "cards": [card]}],
                "window": {"days": 7, "matches_period": bool(anchored)},
            }
        ],
    }
    return render_markdown(ed), render_html(ed)


#: The two per-card wordings, quoted here rather than a bare "Window: " — the SECTION
#: prints a window note of its own, so the short needle is satisfied by a line these
#: assertions are not about. A needle is only as meaningful as its uniqueness.
_ANCHORED_LINE = "Window: this edition's period"
_UNANCHORED_LINE = "Window: as observed when this edition was generated"


def test_a_cards_own_window_is_printed_in_both_renderers():
    """Found by a SURVIVING mutant: the catalog guard cannot see a line the renderer
    stopped emitting — nothing asks the translator for a string nobody prints, so
    coverage stays at 100% while the disclosure vanishes. This is behavioural."""
    import html as _html

    for anchored, needle in ((True, _ANCHORED_LINE), (False, _UNANCHORED_LINE)):
        md, page = _rendered(anchored)
        assert needle in md, anchored
        # Unescaped first: the page escapes the apostrophe, so a raw needle would
        # fail against correct output and invite the wrong repair.
        assert needle in _html.unescape(page), anchored


def test_a_card_written_before_the_seam_gets_no_window_line_at_all():
    """The negative-space twin. An edition on disk from before this field existed
    carries no answer, and inventing one for it would be a fabricated measurement —
    an over-eager disclosure is as dishonest as an omitted one."""
    import html as _html

    md, page = _rendered(None)
    for needle in (_ANCHORED_LINE, _UNANCHORED_LINE):
        assert needle not in md
        assert needle not in _html.unescape(page)
