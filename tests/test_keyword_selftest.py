"""The keyword pre-selection self-test harness (src/analytics/selftest.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The harness asserts known-good keyword behaviour on curated golden cases (Who vs
WHO + the per-language tweaks). These tests pin that (a) every case passes on the
CURRENT pipeline — so a future regression turns a case red here AND in the in-app
log the maintainer exports — and (b) the runner actually checks (a bogus
expectation fails), so a green run is meaningful.
"""

from src.analytics.selftest import Challenge, _check_extraction, run_keyword_selftest


def test_selftest_all_cases_pass_on_current_pipeline():
    log = run_keyword_selftest()
    assert log["kind"] == "keyword-selftest" and log["schema"] == "oo-selftest-1"
    failed = [(c["id"], c["detail"]) for c in log["cases"] if c["status"] == "fail"]
    assert not failed, f"keyword self-test regressions: {failed}"
    assert log["summary"]["failed"] == 0 and log["summary"]["total"] >= 20


def test_selftest_challenges_many_languages_not_just_english():
    # the stopword filters cover every source language with a stoplist, so the
    # harness must challenge more than English (incl. Cyrillic + RTL Arabic).
    langs = {c["language"] for c in run_keyword_selftest()["cases"]}
    assert {"en", "fr", "es", "de", "it", "pt", "nl", "ru", "ar", "hu", "id"} <= langs


def test_who_vs_who_is_guarded_and_passes():
    who = next(c for c in run_keyword_selftest()["cases"] if c["id"] == "who_vs_WHO")
    assert who["status"] == "pass", who["detail"]


def test_caps_furniture_and_roman_numerals_are_guarded_and_pass():
    # 2026-07-18 entity-families brief S2: the live-corpus export found caps publishing
    # furniture (FOTO/VIDEO/LIVE.../PDF/RSS) and pure Roman numerals (XIV/III) ranking as
    # top "entities" — pinned here so a regression turns these red in both this suite
    # and the in-app self-test export the maintainer sends.
    cases = {c["id"]: c for c in run_keyword_selftest()["cases"]}
    for cid in (
        "caps_furniture_not_entity",
        "roman_numerals_not_entities",
        "roman_numeral_acronym_allowlist_kept",
    ):
        c = cases.get(cid)
        assert c is not None, f"missing golden case {cid!r}"
        assert c["status"] == "pass", c["detail"]


def test_lemmatization_mechanism_case_present_and_passes_when_available():
    # P4.3: the lemma mechanism (study<-studied) + denylist (media!->medium) is a golden
    # case when the optional simplemma is installed (CI [analysis] + the maintainer's export);
    # a core install simply omits it (the feature no-ops there), never a failure.
    from src.analytics.families import _simplemma

    cases = {c["id"]: c for c in run_keyword_selftest()["cases"]}
    if _simplemma is None:
        assert "lemmatization_mechanism" not in cases
    else:
        lm = cases.get("lemmatization_mechanism")
        assert lm is not None and lm["status"] == "pass", lm and lm["detail"]


def test_runner_detects_a_deliberate_failure():
    # "markets" is a term, not an entity — a bogus entity expectation must FAIL,
    # proving the harness really checks (a green run is not vacuous).
    bogus = Challenge("bogus", "guards nothing", "Markets fell today.", entity=("markets",))
    assert _check_extraction(bogus)
