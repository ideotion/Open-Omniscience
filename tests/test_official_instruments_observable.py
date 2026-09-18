"""Q1110: the `primary_source` axis rewritten as a checkable OBSERVABLE.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Ruled 2026-09-15 (Q1110 = a): defer-not-reject the judgement axis, and rewrite it as *"does
this feed publish dated official instruments?"* — checkable against the headlines, and not
requiring a model to hold opinions about which countries' institutions are real.

THE THREE STAKES the institutions review recorded are what these tests are actually about,
because each one is a way this rule could be wrong while looking right:

  * EQUITY — a rule calibrated on Western administrative norms under-admits small-language
    and global-South bodies WHILE LOOKING LIKE A QUALITY FILTER. So the multilingual cases
    below are not decoration: they are the failure mode. Two real ones were caught by driving
    them (a Bengali gazette notification the accent-folding had mangled, and a Japanese
    notice dated in the Reiwa era that a Gregorian-only date test read as undated) — and both
    would have shipped, because the languages they broke on are the ones fewest readers of
    this code would have checked.
  * REFUSAL IS NOT NEUTRAL — "we could not tell" must not be recorded as "no".
  * THE LABEL MUST BE TRUE — the rule must not fire on ordinary news.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.catalog.official_instruments import (
    NO_EVIDENCE,
    NONE_OBSERVED,
    OBSERVED,
    instrument_signals,
    lexicon_coverage,
    observe_headlines,
)

# One real-shaped headline per writing system, with the language it belongs to. Every one
# must be seen; a rule that sees only the Latin ones is the equity failure, not a partial win.
INSTRUMENT_HEADLINES = [
    ("en", "Decision No. 512 of 2024 on municipal zoning"),
    ("fr", "Décision n° 2024/512 du 3 mars 2024"),
    ("de", "Ausschreibung 2025: Sanierung der Grundschule"),
    ("es", "Resolución 145/2023 del Ministerio de Hacienda"),
    ("pt", "Portaria nº 88, de 4 de janeiro de 2024"),
    ("cs", "Vyhláška č. 145/2024 Sb."),
    ("ro", "Hotărâre nr. 233 din 2024 privind achiziția"),
    ("ru", "Обнародовано постановление №77 от 2024 года"),
    ("uk", "Постанова Кабінету Міністрів №113 від 2024"),
    ("ar", "قرار وزاري رقم 45 لسنة 2024 بشأن المناقصات"),
    ("ar", "تعميم رقم 12 لسنة 1445هـ"),
    ("hi", "राजपत्र अधिसूचना संख्या 212/2024"),
    ("bn", "প্রজ্ঞাপন নং ৭৭/২০২৪"),
    ("zh", "国务院关于印发2024年统计公报的通知"),
    ("ja", "令和6年 統計月報の公表について"),
    ("zh-tw", "民国113年 招标公告"),
    ("tr", "Resmî Gazete 2024 sayılı yönetmelik"),
    ("id", "Peraturan Menteri Nomor 12 Tahun 2024"),
]

# Ordinary journalism and commentary. None may fire: a rule that flags these makes the label
# untrue in the other direction.
ORDINARY_HEADLINES = [
    "Local football team wins on Saturday",
    "Opinion: why the mayor should resign",
    "Cinq choses à savoir sur la nouvelle saison",
    "Wetterbericht: Sonne am Wochenende",
    "市长视察了新建的公园",
    "Пять лучших ресторанов города",
]


@pytest.mark.parametrize(("lang", "title"), INSTRUMENT_HEADLINES)
def test_a_dated_instrument_is_seen_in_every_covered_writing_system(lang, title) -> None:
    sig = instrument_signals(title)
    assert sig["instrument_shaped"], (
        f"[{lang}] not seen — kinds={sig['kinds']} dated={sig['dated']} for {title!r}. "
        "A rule that sees only some scripts under-admits exactly the administrations "
        "Q1110 exists to stop under-admitting."
    )


@pytest.mark.parametrize("title", ORDINARY_HEADLINES)
def test_ordinary_journalism_never_reads_as_an_official_instrument(title) -> None:
    assert not instrument_signals(title)["instrument_shaped"], (
        f"ordinary news matched the instrument rule: {title!r}"
    )


def test_the_two_halves_are_reported_separately_even_when_only_one_fires() -> None:
    """A near-miss is what someone tuning the lexicon needs, and it is different from a
    clean negative. An undated decision and a dated headline naming no instrument are
    different things to look at."""
    undated = instrument_signals("Decision on municipal zoning")
    assert undated["kinds"] == ["decision"] and undated["dated"] is False
    assert not undated["instrument_shaped"]

    dated = instrument_signals("Weather forecast for 2024")
    assert dated["kinds"] == [] and dated["dated"] is True
    assert not dated["instrument_shaped"]


def test_no_headlines_is_NOT_a_negative_result() -> None:
    """REFUSAL IS NOT NEUTRAL — the review's second stake, as a test. "We could not tell"
    being recorded as "no" is the shape the robots ruling already rejected."""
    empty = observe_headlines([])
    blank = observe_headlines(["", "   ", None])  # type: ignore[list-item]
    for out in (empty, blank):
        assert out["outcome"] == NO_EVIDENCE
        assert out["outcome"] != NONE_OBSERVED, "an absence of evidence became a negative"
        assert out["n"] == 0
        assert "not a negative result" in out["note"]


def test_none_observed_and_no_evidence_are_different_outcomes() -> None:
    """The distinction, driven from both sides so neither can quietly become the other."""
    looked = observe_headlines(ORDINARY_HEADLINES)
    assert looked["outcome"] == NONE_OBSERVED
    assert looked["n"] == len(ORDINARY_HEADLINES), "it must report what it actually read"
    assert observe_headlines([])["outcome"] == NO_EVIDENCE
    assert looked["outcome"] != observe_headlines([])["outcome"]


def test_an_observation_carries_the_headlines_that_produced_it() -> None:
    """A reader must be able to check the rule rather than trust it, so the matching
    headlines travel with the count."""
    titles = [t for _lang, t in INSTRUMENT_HEADLINES] + ORDINARY_HEADLINES
    out = observe_headlines(titles)
    assert out["outcome"] == OBSERVED
    assert out["matched"] == len(INSTRUMENT_HEADLINES)
    assert out["n"] == len(titles)
    assert out["examples"], "an observation with no examples cannot be checked"
    for ex in out["examples"]:
        assert ex["title"] in titles and ex["kinds"]
    assert set(out["kinds"]) <= {"decision", "tender", "regulation", "statistics"}


def test_the_lexicon_publishes_its_own_incompleteness() -> None:
    """The asymmetry this guards: a source publishing decrees in an uncovered language reads
    exactly like one publishing none. That is the equity failure, so the coverage travels
    with every result and says which way the silence points."""
    cov = lexicon_coverage()
    assert len(cov["languages"]) >= 15
    assert cov["terms"] >= 200
    assert set(cov["kinds"]) == {"decision", "tender", "regulation", "statistics"}
    assert "incomplete" in cov["caveat"]
    assert "not about that source" in cov["caveat"]


def test_the_endpoint_is_a_proposal_surface_and_applies_nothing() -> None:
    """The brief scopes this to a proposal surface and leaves 'does it become a splice gate'
    explicitly undecided — so there is no apply, and the route must not be shadowed by
    `/{source_id}` (the lesson this branch already paid for once)."""
    from src.api import source_management as sm

    src = Path(sm.__file__).read_text(encoding="utf-8")
    assert "official-instruments" in src
    # No mutating sibling: a proposal surface with an apply button is not a proposal surface.
    assert "/official-instruments/apply" not in src

    paths = [r.path for r in sm.router.routes]
    first_obs = min(i for i, p in enumerate(paths) if "official-instruments" in p)
    first_by_id = min(i for i, p in enumerate(paths) if "{source_id}" in p)
    assert first_obs < first_by_id, "the observable route is shadowed by /{source_id}"


def test_the_route_answers_and_never_writes(tmp_path) -> None:
    """Driven through the real app, because a handler exercised as a function is not a tested
    route — and because the payload's own caveat is part of what Q1110 asks for."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/sources/official-instruments?limit=5&headlines_per_source=10")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["counts"]) >= {"examined", OBSERVED, NONE_OBSERVED, NO_EVIDENCE}
        assert body["lexicon"]["caveat"].strip()
        assert "not a verdict" in body["caveat"]
        assert "Nothing here is applied" in body["caveat"]
