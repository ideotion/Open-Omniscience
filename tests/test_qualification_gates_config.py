"""The qualification engine's own settings surface: both gates, units, and two scope toggles.

The maintainer's 2026-08-03 amendment asked for one panel covering BOTH quality gates, with
units and a discreet hover explanation on every row, plus two scraping-scope toggles.

The premise needed checking first, and checking it was itself a finding: the two gates are
NOT fused today. Verified by grep, both directions, zero hits either way -- the source-side
modules hold no ``quarantined`` reference and the article-side modules hold no
``Source.status`` reference. They are independent passes over the same articles.

They belong in one panel anyway, and for a stronger reason than tidiness: the source gate's
inputs ARE article-level measurements, so an article the article gate had already condemned
was still counting toward its source's verdict. Two gates that share an input and disagree
about it is exactly what one panel makes visible and two panels hide.

What these tests pin, in the brief's own words: turning qualification OFF must not change a
single existing stamp; a clamped value must be REPORTED rather than silently applied; toggle
A must never admit a disqualified source; and toggle B must not capture
``via:wikidata-discovery``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.catalog.gates import (  # noqa: E402
    ALL_GATE_TUNABLES,
    ARTICLE_GATE_TUNABLES,
    SOURCE_GATE_TUNABLES,
    clamp_gate_settings,
    tunable_payload,
)
from src.catalog.provenance_scope import APP_PROVIDED_TAGS, is_app_provided  # noqa: E402
from src.catalog.qualification import (  # noqa: E402
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
)
from src.database.models import Base, Source  # noqa: E402
from src.scheduler.runner import select_sources  # noqa: E402
from src.scheduler.settings import SchedulerSettings  # noqa: E402


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'q.db'}", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, future=True)


def _src(s, domain: str, *, status: str, tags: str = "", enabled: bool = True) -> Source:
    src = Source(name=domain, domain=domain, status=status, tags=tags, enabled=enabled)
    s.add(src)
    s.flush()
    return src


# --------------------------------------------------------------------------- #
#  Every row carries a unit and an impact
# --------------------------------------------------------------------------- #
def test_every_tunable_states_its_unit_and_its_consequence() -> None:
    """An unlabelled number is the thing this amendment exists to remove. A bare `0.5`
    tells an operator nothing about whether it is a share, a count or a percentile."""
    for t in ALL_GATE_TUNABLES:
        assert t.unit, f"{t.key} has no unit"
        assert t.impact and len(t.impact) > 20, f"{t.key}'s impact line is too thin to act on"
        assert t.lo < t.hi, f"{t.key} has an empty range"
        assert t.lo <= t.default <= t.hi, f"{t.key}'s default is outside its own safe range"


def test_the_bounds_that_are_not_taste_say_why() -> None:
    """Several of these are not preferences, and the panel shows the reason beside the
    control -- a limit whose reason is hidden reads as an arbitrary restriction."""
    need_a_reason = {
        "pathology_abs_floor",     # the only criterion that can disqualify
        "min_pathology_articles",  # the raw-count guard beneath a rate
        "ladder_cap_months",       # the cap IS the second chance
        "source_cohort_floor",     # below it there is no baseline at all
    }
    have = {t.key for t in ALL_GATE_TUNABLES if t.floor_reason}
    assert need_a_reason <= have, f"missing a stated reason: {sorted(need_a_reason - have)}"


def test_a_tunable_can_make_a_gate_stricter_but_never_claim_more_than_the_evidence() -> None:
    """FENCE 1, inherited verbatim from the Leads catalogue. Concretely: the raw-count
    guard has no zero, and the re-check cap has no "never"."""
    by_key = {t.key: t for t in SOURCE_GATE_TUNABLES}
    assert by_key["min_pathology_articles"].lo >= 2, (
        "a zero here would let a single article become an extraction-failure verdict, "
        "because a clean cohort's p90 is exactly 0"
    )
    assert by_key["ladder_cap_months"].hi <= 24, (
        "the cap is what GUARANTEES a disqualified source is re-checked; it may be "
        "shortened, never effectively removed"
    )


def test_the_soft_criteria_cap_is_not_exposed_as_a_setting() -> None:
    """FENCE 2. derive_status caps style-ambiguous criteria at `watch`, and that cap is
    load-bearing: exposing it would let a settings row turn "this source writes unusually"
    into "this source is broken"."""
    keys = {t.key for t in ALL_GATE_TUNABLES}
    for forbidden in ("soft_criteria_cap", "allow_soft_disqualify", "watch_cap"):
        assert forbidden not in keys


# --------------------------------------------------------------------------- #
#  A clamp REPORTS (the Cards precedent)
# --------------------------------------------------------------------------- #
def test_an_out_of_range_value_is_corrected_and_reported() -> None:
    """Silently rewriting a number the operator typed would leave them believing the gate
    runs at a setting it does not have -- the exact behaviour the ruling forbids."""
    clamped, notes = clamp_gate_settings({"min_pathology_articles": 0})
    assert clamped["min_pathology_articles"] == 2
    assert notes and notes[0]["key"] == "min_pathology_articles"
    assert notes[0]["given"] == 0 and notes[0]["used"] == 2
    assert notes[0]["reason"], "a clamp without a reason is indistinguishable from a bug"


def test_an_in_range_value_is_applied_without_a_note() -> None:
    """The negative-space twin: a clamp that fires on a legitimate value would train the
    operator to ignore the notes."""
    clamped, notes = clamp_gate_settings({"min_pathology_articles": 7, "tail_p": 95})
    assert clamped == {"min_pathology_articles": 7, "tail_p": 95}
    assert notes == []


def test_an_unknown_or_non_numeric_setting_is_dropped_with_a_note() -> None:
    """Never guessed at -- an unknown key silently accepted would read as applied."""
    clamped, notes = clamp_gate_settings({"nonsense": 3, "tail_p": "abc"})
    assert clamped == {}
    assert {n["key"] for n in notes} == {"nonsense", "tail_p"}


def test_the_payload_carries_the_live_value_not_only_the_default() -> None:
    rows = tunable_payload(ARTICLE_GATE_TUNABLES, {"article_min_words": 250})
    by_key = {r["key"]: r for r in rows}
    assert by_key["article_min_words"]["value"] == 250
    assert by_key["article_min_words"]["default"] == 100
    assert by_key["wall_max_words"]["value"] == 40, "an unset row falls back to its default"


# --------------------------------------------------------------------------- #
#  Toggle A -- "also scrape sources not yet qualified"
# --------------------------------------------------------------------------- #
def test_an_untouched_install_scrapes_exactly_what_it_scraped_before(tmp_path) -> None:
    """Both toggles default to today's behaviour."""
    s = _session(tmp_path)
    _src(s, "qualified.example", status=STATUS_QUALIFIED)
    _src(s, "unqualified.example", status=STATUS_UNQUALIFIED)
    _src(s, "disqualified.example", status=STATUS_DISQUALIFIED)
    s.commit()

    picked = {x.domain for x in select_sources(s, SchedulerSettings())}
    assert picked == {"qualified.example"}


def test_toggle_a_admits_the_unjudged_and_still_refuses_the_judged_bad(tmp_path) -> None:
    """THE data-safety line on this toggle. Unqualified means NOT YET JUDGED; disqualified
    is a verdict, and the re-qualification ladder is how a disqualified source comes back --
    not a checkbox that forgets the verdict was ever reached."""
    s = _session(tmp_path)
    _src(s, "qualified.example", status=STATUS_QUALIFIED)
    _src(s, "unqualified.example", status=STATUS_UNQUALIFIED)
    _src(s, "disqualified.example", status=STATUS_DISQUALIFIED)
    s.commit()

    picked = {x.domain for x in select_sources(s, SchedulerSettings(scrape_unqualified=True))}
    assert "unqualified.example" in picked, "the toggle did not admit a not-yet-judged source"
    assert "disqualified.example" not in picked, (
        "a source that was judged and found wanting was scraped anyway"
    )


def test_toggle_a_still_reaches_only_enabled_sources(tmp_path) -> None:
    """What makes the toggle much safer than it sounds: the ~42,600 discovered candidates
    are DISABLED, so they stay out either way."""
    s = _session(tmp_path)
    _src(s, "candidate.example", status=STATUS_UNQUALIFIED, enabled=False)
    s.commit()

    picked = {x.domain for x in select_sources(s, SchedulerSettings(scrape_unqualified=True))}
    assert picked == set()


# --------------------------------------------------------------------------- #
#  Toggle B -- "only the sources that came with the app"
# --------------------------------------------------------------------------- #
def test_toggle_b_includes_the_shipped_catalogue_and_excludes_what_the_app_found(tmp_path) -> None:
    """⚠ THE TRAP, pinned. `via:wikidata` is the committed world_news_sources.yml;
    `via:wikidata-discovery` is what the RUNNING app found for itself. They differ by a
    suffix, so a prefix or substring match captures both and quietly defeats the toggle --
    the result still looks like a plausible subset."""
    s = _session(tmp_path)
    _src(s, "shipped.example", status=STATUS_QUALIFIED, tags="news,via:wikidata")
    _src(s, "found.example", status=STATUS_QUALIFIED, tags="news,via:wikidata-discovery")
    _src(s, "curated.example", status=STATUS_QUALIFIED, tags="via:curated")
    _src(s, "legalgen.example", status=STATUS_QUALIFIED, tags="law,via:legal-generated")
    _src(s, "untagged.example", status=STATUS_QUALIFIED, tags="news")
    s.commit()

    picked = {x.domain for x in select_sources(
        s, SchedulerSettings(scrape_app_provided_only=True),
    )}
    assert "shipped.example" in picked
    assert "curated.example" in picked
    assert "found.example" not in picked, (
        "via:wikidata-discovery was captured by a match meant for via:wikidata"
    )
    assert "legalgen.example" not in picked, "via:legal-generated is a runtime channel"
    assert "untagged.example" not in picked, (
        "a source with no provenance tag was CLAIMED as app-provided -- that is a guess "
        "about its origin, not a fact"
    )


def test_the_python_and_sql_definitions_of_app_provided_agree(tmp_path) -> None:
    """Two definitions of the same thing drift. The SQL predicate is what the scheduler
    uses and the Python helper is what everything else uses, so they are checked against
    each other over the same rows rather than each against its own idea."""
    s = _session(tmp_path)
    rows = [
        ("a.example", "via:wikidata"),
        ("b.example", "via:wikidata-discovery"),
        ("c.example", "news,via:curated,extra"),
        ("d.example", ""),
        ("e.example", "via:legal"),
        ("f.example", "via:legal-generated"),
    ]
    for domain, tags in rows:
        _src(s, domain, status=STATUS_QUALIFIED, tags=tags)
    s.commit()

    sql_picked = {x.domain for x in select_sources(
        s, SchedulerSettings(scrape_app_provided_only=True),
    )}
    py_picked = {x.domain for x in s.query(Source).all() if is_app_provided(x)}
    assert sql_picked == py_picked, f"SQL says {sorted(sql_picked)}, Python says {sorted(py_picked)}"
    assert sql_picked == {"a.example", "c.example", "e.example"}


def test_the_app_provided_set_is_exact_never_a_prefix_rule() -> None:
    """Guards the definition itself: every entry is a full tag, so nobody can later
    "simplify" it into a prefix that reintroduces the discovery collision."""
    assert "via:wikidata" in APP_PROVIDED_TAGS
    assert "via:wikidata-discovery" not in APP_PROVIDED_TAGS
    assert all(t.startswith("via:") and "," not in t for t in APP_PROVIDED_TAGS)


# --------------------------------------------------------------------------- #
#  Turning qualification off is not a re-judgement
# --------------------------------------------------------------------------- #
def test_qualification_off_changes_no_existing_stamp(tmp_path) -> None:
    """OFF means "stop judging new candidates", never "reconsider the ones already
    judged". A settings change that silently rewrote verdicts would be the same class of
    surprise as a merge that laundered a disqualified source back into the queue."""
    from src.catalog.qualification import advance_qualification

    s = _session(tmp_path)
    _src(s, "qualified.example", status=STATUS_QUALIFIED)
    _src(s, "disqualified.example", status=STATUS_DISQUALIFIED)
    _src(s, "unqualified.example", status=STATUS_UNQUALIFIED)
    s.commit()
    before = {x.domain: x.status for x in s.query(Source).all()}

    result = advance_qualification(s, None, per_pass=0)

    after = {x.domain: x.status for x in s.query(Source).all()}
    assert after == before, "turning qualification off changed an existing verdict"
    # It must DECLARE that it is off rather than report a zero-work pass, which would be
    # indistinguishable from "it ran and found nothing to do".
    assert result == {"enabled": False}, f"an off ride-along reported {result!r}"
    assert "qualified" not in result and "examined" not in result


# --------------------------------------------------------------------------- #
#  The panel renders from the backend's own declarations
# --------------------------------------------------------------------------- #
def test_every_criterion_reaches_the_config_payload(tmp_path) -> None:
    """So a criterion added to the engine later cannot be silently absent from the panel,
    and the panel can never describe one the engine no longer applies."""
    from src.analytics.source_audit import CRITERIA
    from src.api.source_management import qualification_config

    s = _session(tmp_path)
    _src(s, "a.example", status=STATUS_QUALIFIED)
    s.commit()

    payload = qualification_config(db=s)
    names = {c["name"] for c in payload["criteria"]}
    assert names == {c["name"] for c in CRITERIA}

    disqualifiers = [c for c in payload["criteria"] if c["can_disqualify"]]
    assert len(disqualifiers) == 1 and disqualifiers[0]["name"] == "pathology_rate", (
        "exactly one criterion can disqualify, and the panel must mark WHICH -- a reader "
        "cannot tell from the list otherwise"
    )
    assert {g["id"] for g in payload["gates"]} == {"article", "source"}
    for gate in payload["gates"]:
        assert gate["tunables"], f"{gate['id']} gate rendered with no tunables"
        for row in gate["tunables"]:
            assert row["unit"] and row["impact"]
