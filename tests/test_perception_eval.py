"""
S6.5 — the LLM-perception (who/where/when) eval harness (the gate before extraction).

Proves the SCORING mechanism: precision/recall/HALLUCINATION-rate per stratum, place string
vs coordinate scored separately, de-US-centring split, no composite. The gold set is synthetic
+ modest (×12 languages, ar/zh/ja/hi/bn flagged). Deterministic — no model, no network.
"""

from __future__ import annotations

from src.analytics import perception_eval as PE


def test_selftest_passes_all_hand_computed_checks():
    r = PE.run_perception_eval_selftest()
    assert r["passed"] is True, r["checks"]
    assert all(r["checks"].values())


def test_metrics_are_hand_computable():
    cases = [
        PE.PerceptionCase("c", "en", "easy", "explicit-date", "x", who=("A", "B"), when=("2024-01-01",)),
    ]

    def fn(text, language=None):
        return {"who": ["A", "Z"], "where": [], "when": ["2024-01-01"]}  # A right, Z invented, B missed

    r = PE.evaluate_perception(fn, cases)
    who = r["by_field_overall"]["who"]
    assert who["tp"] == 1 and who["fp"] == 1 and who["fn"] == 1
    assert who["precision"] == 0.5 and who["recall"] == 0.5 and who["hallucination_rate"] == 0.5
    when = r["by_field_overall"]["when"]
    assert when["precision"] == 1.0 and when["hallucination_rate"] == 0.0


def test_negative_case_makes_any_prediction_a_hallucination():
    cases = [PE.PerceptionCase("n", "en", "easy", "negative", "nothing")]

    def fn(text, language=None):
        return {"who": ["Ghost"], "where": ["Nowhere"], "when": []}

    r = PE.evaluate_perception(fn, cases)
    assert r["by_field_overall"]["who"]["hallucination_rate"] == 1.0
    assert r["by_field_overall"]["who"]["fp"] == 1  # invented from empty gold


def test_place_string_and_coordinate_scored_separately():
    cases = [
        PE.PerceptionCase("p", "en", "hard", "ambiguous-place", "Paris hosted it.",
                          where=("Paris",), where_geo={"Paris": (48.8566, 2.3522)}),
    ]

    def fn(text, language=None):
        # the STRING is right ("Paris") but the COORDINATE resolves to Paris, Texas (wrong).
        return {"where": ["Paris"], "where_geo": {"Paris": (33.66, -95.55)}}

    r = PE.evaluate_perception(fn, cases)
    assert r["by_field_overall"]["where"]["precision"] == 1.0  # the string is correct
    assert r["place_coordinate"]["fp"] == 1  # the coordinate is wrong — scored apart


def test_de_us_centring_split_is_reported():
    cases = [
        PE.PerceptionCase("u", "en", "easy", "place", "x", where=("Washington",), us_centric=True),
        PE.PerceptionCase("w", "en", "easy", "place", "y", where=("Nairobi",)),
    ]

    def fn(text, language=None):
        return {"where": ["Washington"]} if "x" in text else {"where": []}  # US ok, non-US missed

    r = PE.evaluate_perception(fn, cases)
    assert "us-centric" in r["de_us_centring"] and "non-us" in r["de_us_centring"]
    assert r["de_us_centring"]["us-centric"]["where"]["recall"] == 1.0
    assert r["de_us_centring"]["non-us"]["where"]["recall"] == 0.0  # the bias signal


def test_no_composite_score_field_names():
    r = PE.run_perception_eval_selftest()
    banned = ("_score", "rating", "ranking", "verdict", "credibility")

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in banned), f"score-shaped key {k!r}"
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(r)


def test_gold_set_spans_twelve_languages_with_flags():
    langs = {c.language for c in PE.PERCEPTION_GOLD}
    assert {"en", "fr", "de", "es", "pt", "nl", "ru", "id", "ar", "zh", "ja", "hi", "bn"} <= langs
    flagged = {c.language for c in PE.PERCEPTION_GOLD if c.needs_native_review}
    assert {"ar", "zh", "ja", "hi", "bn"} <= flagged  # non-Latin cases flagged for native review
    # a negative + an ambiguous-place-with-geo case exist (the hallucination + coord strata)
    phen = {c.phenomenon for c in PE.PERCEPTION_GOLD}
    assert "negative" in phen and "ambiguous-place" in phen


def test_perception_delta_reports_fields_separately():
    cases = [PE.PerceptionCase("c", "en", "easy", "org", "x", who=("A",))]
    base = PE.evaluate_perception(lambda t, l=None: {"who": ["A"]}, cases)  # finds A, invents nothing
    cand = PE.evaluate_perception(lambda t, l=None: {"who": ["A", "B"]}, cases)  # finds A + invents B
    d = PE.perception_delta(base, cand)
    # recall is UNCHANGED but the hallucination ROSE — shown apart, never blended into one score.
    assert d["who"]["recall_delta"] == 0.0
    assert d["who"]["hallucination_delta"] == 0.5
