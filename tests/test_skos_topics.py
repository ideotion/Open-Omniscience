"""C-L3: the SKOS reader, the rule tagger and the labelled-sample measurement (offline fixtures)."""
import json
from pathlib import Path

import pytest

from src.catalog import skos
from src.catalog import topic_tagging as tt

D = Path(__file__).parent / "data" / "skos"
A = "http://example.org/c/asylum"
P = "http://example.org/c/privacy"
DATA = "http://example.org/c/data"


@pytest.fixture(scope="module")
def index():
    parsed = skos.parse_rdfxml(D / "mini_scheme.rdf")
    art = skos.build_artifact("eurovoc", parsed, vintage="2026-11", license="CC0 (unconfirmed)", upstream="fixture")
    return tt.Index([art])


def test_concept_without_label_is_a_gap_not_a_label():
    parsed = skos.parse_rdfxml(D / "mini_scheme.rdf")
    assert "http://example.org/c/nolabel" not in parsed["concepts"]
    assert {"kind": "concept_without_label", "detail": "http://example.org/c/nolabel"} in parsed["gaps"]
    assert parsed["n_seen"] == 4


def test_empty_scheme_is_a_gap():
    parsed = skos.parse_rdfxml(D / "empty_scheme.rdf")
    assert parsed["concepts"] == {} and parsed["gaps"][-1]["kind"] == "empty_scheme"
    art = skos.build_artifact("agrovoc", parsed, vintage="2026-11", license="x", upstream="x")
    assert tt.Index([art]).empty == ["agrovoc"]
    assert tt.tag_text("anything", "en", tt.Index([art])) == []


def test_language_filter_turns_labelless_concepts_into_gaps():
    parsed = skos.parse_rdfxml(D / "mini_scheme.rdf")
    art = skos.build_artifact("eurovoc", parsed, vintage="2026-11", license="x", upstream="x", languages=("de",))
    assert list(art["concepts"]) == [DATA]
    assert any(g["kind"] == "concept_without_label_in_languages" for g in art["gaps"])


def test_unknown_scheme_and_malformed_xml_are_named(tmp_path):
    with pytest.raises(skos.SkosError):
        skos.build_artifact("nope", {"concepts": {}}, vintage="x", license="x", upstream="x")
    bad = tmp_path / "bad.rdf"
    bad.write_text("<rdf:RDF", encoding="utf-8")
    with pytest.raises(skos.SkosError):
        skos.parse_rdfxml(bad)


def test_entity_bomb_is_refused(tmp_path):
    bomb = tmp_path / "bomb.rdf"
    bomb.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><x>&b;</x>',
                    encoding="utf-8")
    with pytest.raises(skos.SkosError):
        skos.parse_rdfxml(bomb)


def test_exact_and_approx_tiers(index):
    t = tt.tag_text("New Asylum Law passes", "en", index)
    assert [(x.concept, x.tier) for x in t] == [(A, "exact")]
    # a label shared by two concepts: both returned, both ≈, neither picked
    t = tt.tag_text("a right of asylum", "en", index)
    assert {(x.concept, x.approx_reason) for x in t} == {(A, "ambiguous_label"), (P, "ambiguous_label")}
    assert all(x.approx for x in t)
    # whole words only
    assert tt.tag_text("privacyx", "en", index) == []


def test_measure_on_the_labelled_sample(index):
    sample = json.loads((D / "labelled_sample.json").read_text(encoding="utf-8"))
    m = tt.measure(sample, index)
    assert m["n_items"] == 6 and m["unsupported_languages"] == {"zh": 1}
    assert m["tagged_share"]["value"] == pytest.approx(5 / 6)
    assert m["approx_share"] == {"value": pytest.approx(2 / 7), "n": 7}
    assert m["precision_exact"]["value"] == 1.0
    assert m["precision_approx"]["value"] == pytest.approx(0.5)
    assert m["recall"] == {"value": 1.0, "n": 6}
    assert "lens" in m["caveat"] and "approximate" in m["caveat"]


def test_zero_denominator_is_null_with_reason(index):
    m = tt.measure([{"id": "x", "lang": "en", "text": "nothing here", "expected": []}], index)
    assert m["precision"]["value"] is None and m["precision"]["reason"]
    assert m["recall"]["value"] is None and m["recall"]["reason"]
    assert m["tagged_share"]["value"] == 0.0
