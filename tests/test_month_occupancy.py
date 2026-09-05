"""Slice 2: how much of the month-name ban is not about dates.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

The measurement the 2026-09-05 design of record says decides slice 3. These pin the
properties that make its number trustworthy rather than merely plausible:

* the measured vocabulary is derived from BOTH live sources, so it cannot drift;
* the split really discriminates -- the same spelling is consumed in one language and
  free in another, which is the whole reason the ban is a cross-language problem;
* the production path's ANCHOR and LANGUAGE are passed, without which the extractor
  runs explicit-dates-only and the consumed side is silently understated (the
  2026-06-16 wiring bug, which is exactly the direction that would push the ruling the
  wrong way);
* every bound is honest at its edge: a token past the scan cut is not counted at all,
  and an empty denominator yields None rather than a 0.0 that reads as a finding.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import global_stopwords
from src.analytics.month_occupancy import (
    _share,
    _token_re,
    banned_month_tokens,
    month_occupancy_report,
    month_vocabulary,
    occupancy_for_text,
)
from src.database.models import Article, Base, Source
from src.timemap.dateextract import _MAX_SCAN

TODAY = date(2026, 6, 11)


def _sess(tmp_path, name="months.db"):
    eng = create_engine(
        f"sqlite:///{tmp_path / name}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)


def _seed(Session, bodies):
    """bodies: list of (content, language, published_at | None, quarantined)."""
    with Session() as s:
        src = Source(name="Month Gazette", domain="months.example")
        s.add(src)
        s.flush()
        for i, (content, lang, pub, quar) in enumerate(bodies):
            s.add(
                Article(
                    url=f"https://months.example/{i}",
                    canonical_url=f"https://months.example/{i}",
                    source_id=src.id,
                    title=f"Piece {i}",
                    content=content,
                    language=lang,
                    hash=f"mo{i}" + "e" * 61,
                    published_at=pub,
                    created_at=datetime(2026, 6, 1, tzinfo=UTC),
                    quarantined=quar,
                )
            )
        s.commit()


# --------------------------------------------------------------------------- vocabulary


def test_the_measured_set_is_derived_from_both_live_sources():
    """Never a hardcoded list: it is the extractor's month tables INTERSECTED with the
    live stopword union, so adding a month name to either side alone changes what the
    next run measures instead of measuring a stale set."""
    vocab, banned, stops = month_vocabulary(), banned_month_tokens(), global_stopwords()
    assert banned, "the stoplist bans month names -- an empty set means a broken derivation"
    assert set(banned) <= set(vocab), "a measured token the date extractor does not know"
    assert set(banned) <= stops, "a measured token the stoplist does not actually ban"
    # And the intersection is PROPER in both directions, or it is not an intersection.
    assert set(vocab) - set(banned), "no month name escapes the ban? check the derivation"
    assert stops - set(banned), "the stoplist is not made only of month names"


def test_every_measured_token_says_where_it_is_known_as_a_month():
    for token, where in banned_month_tokens().items():
        assert where, f"{token} carries no provenance"
        assert set(where) <= {"global", "gated", "thai", "jalali"}, (token, where)


# ------------------------------------------------------------------- the discrimination


def test_a_dateline_is_consumed_and_a_topic_is_not():
    got = occupancy_for_text(
        "Published 3 April 2026. The March on Washington was in August 1963. "
        "Mars is a planet.",
        language="en",
        anchor=date(2026, 4, 3),
        today=TODAY,
    )
    assert got["april"] == (1, 0)
    assert got["august"] == (1, 0)
    assert got["march"] == (0, 1), "the March on Washington is not a date"
    assert got["mars"] == (0, 1), "the planet is not a date"


def test_the_same_spelling_is_a_month_in_one_language_and_free_in_another():
    """THE cross-language case the ban cannot see, and the reason it is a problem.

    `mars` is French March and the English name of a planet; the ban is
    language-agnostic, so it deletes both everywhere."""
    fr = occupancy_for_text(
        "Le 11 mars 2026, la mission vers Mars a decolle.",
        language="fr", anchor=date(2026, 3, 11), today=TODAY,
    )
    en = occupancy_for_text(
        "The Mars rover landed safely.", language="en", anchor=date(2026, 6, 1), today=TODAY,
    )
    assert fr["mars"] == (1, 1), "one occurrence is the date, the other is the planet"
    assert en["mars"] == (0, 1), "no French date here, so the planet stands alone"


def test_word_boundaries_hold_in_both_directions():
    got = occupancy_for_text(
        "Marsh dismay maybe septic Augustine", language="en", today=TODAY
    )
    assert got == {}, f"a substring was mistaken for a month token: {got}"
    # ...and the real tokens ARE found next to punctuation, which is not a letter.
    got2 = occupancy_for_text("(may) — march, mars.", language="en", today=TODAY)
    assert set(got2) == {"may", "march", "mars"}


def test_the_longest_month_name_wins_the_alternation():
    """`sept` (French seven) is banned and is a prefix of `september`."""
    m = _token_re().search("september")
    assert m is not None and m.group(1).lower() == "september"


# ------------------------------------------------------- the anchor/language wiring


def test_a_day_and_month_with_no_year_needs_the_anchor_to_be_consumed():
    """The 2026-06-16 wiring bug, as a property of THIS measurement.

    Without the article's own publication date the extractor cannot resolve `11 mars`
    at all, so the token reads as free text and the consumed side is understated --
    which is the direction that would make the ban look cheaper than it is."""
    text = "La reunion du 11 mars a ete reportee."
    with_anchor = occupancy_for_text(
        text, language="fr", anchor=date(2026, 3, 1), today=TODAY
    )
    without = occupancy_for_text(text, language="fr", anchor=None, today=TODAY)
    assert with_anchor["mars"] == (1, 0)
    assert without["mars"] == (0, 1)


def test_a_language_gated_form_needs_the_language_to_be_consumed():
    """Hungarian writes a year-first named month -- "2024. december" -- and the extractor
    only reads that form under a `hu` hint. `december` is spelled identically in English,
    so this is the realistic case where the SAME banned token is a dateline in one
    language and free text in another, and the hint is the only thing that separates
    them. Measured: it is the one gate the current banned set can reach at all."""
    text = "2024. december volt a hatarido."
    assert occupancy_for_text(text, language="hu", anchor=None, today=TODAY)["december"] == (1, 0)
    assert occupancy_for_text(text, language=None, anchor=None, today=TODAY)["december"] == (0, 1)


def test_the_report_passes_the_article_anchor(tmp_path):
    """The wiring above, but through the REPORT -- a pure-function test cannot see a
    report that forgets to pass what it has."""
    Session = _sess(tmp_path)
    _seed(Session, [("La reunion du 11 mars a ete reportee.", "fr",
                     datetime(2026, 3, 1, tzinfo=UTC), None)])
    with Session() as s:
        rep = month_occupancy_report(s, sample=20, today=TODAY)
    assert rep["by_token"]["mars"]["consumed_as_a_date"] == 1, (
        "the report did not hand the extractor the article's own publication date"
    )
    assert rep["by_token"]["mars"]["outside_any_date"] == 0


def test_the_report_passes_the_article_language(tmp_path):
    """Separately, because only the Hungarian year-first form can currently tell the
    difference -- every other banned token lives in the language-agnostic table, so a
    report that dropped the hint would look correct on any other fixture."""
    Session = _sess(tmp_path)
    _seed(Session, [("2024. december volt a hatarido.", "hu", None, None)])
    with Session() as s:
        rep = month_occupancy_report(s, sample=20, today=TODAY)
    assert rep["by_token"]["december"]["consumed_as_a_date"] == 1, (
        "the report did not hand the extractor the article's own language"
    )


# --------------------------------------------------------------------------- the bounds


def test_a_token_past_the_scan_bound_is_not_counted_at_all():
    """Not counted as outside: the extractor never looked there, and calling an
    unexamined occurrence 'outside a date' fabricates an absence out of a bound."""
    tail = " The march was long."
    text = "x" * (_MAX_SCAN + 10) + tail
    assert occupancy_for_text(text, language="en", today=TODAY) == {}
    # The same sentence inside the bound IS counted, so the guard is about the cut.
    assert occupancy_for_text("y" * 100 + tail, language="en", today=TODAY)["march"] == (0, 1)


def test_an_empty_denominator_yields_none_not_zero():
    assert _share(0, 0) is None, "0.0 would read as 'measured, and none were outside'"
    assert _share(0, 4) == 0.0
    assert _share(1, 4) == 0.25


# --------------------------------------------------------------------------- the report


def test_the_report_reconciles_and_carries_its_caveats(tmp_path):
    Session = _sess(tmp_path)
    _seed(Session, [
        ("Published 3 April 2026. The March on Washington. Mars is a planet.", "en",
         datetime(2026, 4, 3, tzinfo=UTC), None),
        ("Le 11 mars 2026 la sonde vers Mars a decolle.", "fr",
         datetime(2026, 3, 11, tzinfo=UTC), None),
        ("Nothing calendrical in this body whatsoever.", "en",
         datetime(2026, 5, 1, tzinfo=UTC), None),
    ])
    with Session() as s:
        rep = month_occupancy_report(s, sample=40, today=TODAY)

    t = rep["totals"]
    assert t["occurrences"] == t["consumed_as_a_date"] + t["outside_any_date"]
    assert t["occurrences"] == sum(v["occurrences"] for v in rep["by_token"].values())
    for token, slot in rep["by_token"].items():
        assert slot["occurrences"] == slot["consumed_as_a_date"] + slot["outside_any_date"], token
        by_lang = slot["by_language"]
        assert sum(v["consumed_as_a_date"] for v in by_lang.values()) == slot["consumed_as_a_date"]
        assert sum(v["outside_any_date"] for v in by_lang.values()) == slot["outside_any_date"]
    assert set(rep["by_language"]) == {"en", "fr"}
    assert rep["basis"]["articles_with_a_banned_month_token"] == 2
    assert rep["basis"]["articles_scanned"] == 3
    assert len(rep["caveats"]) >= 4
    assert any("FLOOR" in c for c in rep["caveats"]), (
        "the unigram-only bound must be stated: the ban also kills every n-gram "
        "containing the token"
    )


def test_a_quarantined_article_is_never_sampled(tmp_path):
    """Nav soup is where month names sit as furniture ('May 2026 archive'), and it is
    already excluded from search and analytics -- counting it here would inflate the
    outside figure with text no keyword surface ever shows."""
    Session = _sess(tmp_path)
    _seed(Session, [
        ("The march was long and had no dates in it.", "en", None, True),
        ("Ordinary body with no calendar words.", "en", None, None),
    ])
    with Session() as s:
        rep = month_occupancy_report(s, sample=40, today=TODAY)
    assert rep["basis"]["articles_scanned"] == 1
    assert rep["by_token"] == {}


def test_the_sample_is_deterministic(tmp_path):
    """Two runs on one corpus must agree, or the number cannot be checked.

    The bodies DIFFER -- each carries a different month name a different number of times
    -- so which articles were drawn changes every figure. Interchangeable bodies would
    make an unseeded draw indistinguishable from a seeded one, which is the slack a
    mutation hides in."""
    Session = _sess(tmp_path)
    words = ["march", "avril", "mars", "august", "juin", "mayo"]
    _seed(Session, [
        (f"Body {i}: " + " ".join([words[i % len(words)]] * (i % 4 + 1)), "en", None, None)
        for i in range(60)
    ])
    with Session() as s:
        a = month_occupancy_report(s, sample=6, today=TODAY)
        b = month_occupancy_report(s, sample=6, today=TODAY)
    assert a["basis"]["sampled_article_ids"] == b["basis"]["sampled_article_ids"], (
        "two runs on one corpus drew different articles"
    )
    assert a["totals"] == b["totals"]
    assert a["by_token"] == b["by_token"]


def test_the_listed_ids_are_examples_and_the_count_is_not_capped(tmp_path):
    """A cap may bound which EXAMPLES are listed; it must never bound a displayed
    NUMBER (the 2026-07-18 ruling)."""
    from src.analytics import month_occupancy as mo

    Session = _sess(tmp_path)
    _seed(Session, [(f"Body {i} has no calendar words.", "en", None, None) for i in range(40)])
    with Session() as s:
        rep = month_occupancy_report(s, sample=30, today=TODAY)
    basis = rep["basis"]
    assert basis["distinct_articles"] == 30
    assert len(basis["sampled_article_ids"]) == min(30, mo._ID_SAMPLE_SHOWN)
    assert basis["sampled_article_ids_shown"] == len(basis["sampled_article_ids"])


def test_the_report_publishes_no_score_shaped_field(tmp_path):
    """The recursive KEY walk, not a repr() substring check: a caveat legitimately
    containing the word 'score' must not trip it, and a field named for one must."""
    Session = _sess(tmp_path)
    _seed(Session, [("Published 3 April 2026.", "en", datetime(2026, 4, 3, tzinfo=UTC), None)])
    with Session() as s:
        rep = month_occupancy_report(s, sample=10, today=TODAY)

    banned = ("score", "ranking", "rating", "grade", "quality")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in str(k).lower() for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(rep)


@pytest.mark.parametrize("sample", [1, 3, 400])
def test_the_sample_size_never_changes_what_a_hit_means(tmp_path, sample):
    Session = _sess(tmp_path, f"s{sample}.db")
    _seed(Session, [("The March on Washington.", "en", None, None)])
    with Session() as s:
        rep = month_occupancy_report(s, sample=sample, today=TODAY)
    assert rep["by_token"]["march"] == {
        "known_as_a_month_in": ["global"],
        "articles": 1,
        "occurrences": 1,
        "consumed_as_a_date": 0,
        "outside_any_date": 1,
        "by_language": {"en": {"consumed_as_a_date": 0, "outside_any_date": 1}},
        "outside_share": 1.0,
    }


# ------------------------------------------------------------------------ the wiring


def test_the_bundle_member_produces_a_real_report_not_a_degraded_stub():
    """Drives the REAL member generator, not the route signature.

    ``month-occupancy.json`` is produced by calling the route DIRECTLY, where a
    ``Query(...)`` default is an unresolved sentinel object rather than an int -- the
    recorded 2026-08-02 defect where a bundle shipped a degraded member and the
    per-member guard swallowed it. Only a behavioural drive can tell a real report from
    a sentinel-poisoned one."""
    import json

    from fastapi.testclient import TestClient

    from src.api import diagnostics as d
    from src.api.main import app
    from src.database.session import SessionLocal

    # The app lifespan is what creates the schema this member reads; a bare
    # SessionLocal() outside it would fail for a reason unrelated to the claim.
    with TestClient(app), SessionLocal() as db:
        members = dict(d._all_diagnostics_members(db))
        assert "month-occupancy.json" in members, "the member must be in the bundle"
        resp = members["month-occupancy.json"]()
    body = json.loads(bytes(resp.body))
    assert isinstance(body["basis"]["requested_sample"], int), (
        "the sample arrived as a Query sentinel, not an int"
    )
    assert body["totals"]["occurrences"] >= 0
    assert body["basis"]["banned_tokens_known"] == len(banned_month_tokens())
    assert body["caveats"] and body["method"]


def test_the_endpoint_is_reachable_and_bounded():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/diagnostics/month-occupancy", params={"sample": 3})
        assert r.status_code == 200
        assert r.json()["basis"]["requested_sample"] == 3
        assert c.get("/api/diagnostics/month-occupancy", params={"sample": 0}).status_code == 422
        assert c.get(
            "/api/diagnostics/month-occupancy", params={"sample": 999999}
        ).status_code == 422
