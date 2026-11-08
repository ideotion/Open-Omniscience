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


def test_external_doctype_is_refused_without_a_network_call(tmp_path, monkeypatch):
    import socket

    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise AssertionError("the SKOS reader must never touch the network")

    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    for doc in (
        '<?xml version="1.0"?><!DOCTYPE rdf:RDF SYSTEM "http://evil.example/x.dtd">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>',
        '<?xml version="1.0"?><!DOCTYPE rdf:RDF [<!ENTITY x SYSTEM "http://evil.example/x">]>'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">&x;</rdf:RDF>',
    ):
        f = tmp_path / "ext.rdf"
        f.write_text(doc, encoding="utf-8")
        try:
            parsed = skos.parse_rdfxml(f)
        except skos.SkosError:
            continue  # refused: named, not fetched
        assert parsed["concepts"] == {}  # an external DTD ignored is also fine, never fetched
    assert calls == []


def _parse_text(tmp_path, body):
    f = tmp_path / "t.rdf"
    f.write_text(
        '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:skos="http://www.w3.org/2004/02/skos/core#" xml:lang="en">' + body + "</rdf:RDF>",
        encoding="utf-8",
    )
    return skos.parse_rdfxml(f)


def test_nested_broader_and_inherited_language(tmp_path):
    parsed = _parse_text(
        tmp_path,
        '<skos:Concept rdf:about="u:a"><skos:prefLabel>A</skos:prefLabel>'
        '<skos:broader><skos:Concept rdf:about="u:b"><skos:prefLabel>B</skos:prefLabel></skos:Concept></skos:broader>'
        "</skos:Concept>",
    )
    assert parsed["concepts"]["u:a"]["broader"] == ["u:b"]
    assert parsed["concepts"]["u:a"]["pref"] == {"en": "A"}  # xml:lang inherited from rdf:RDF
    assert parsed["concepts"]["u:b"]["pref"] == {"en": "B"}
    assert not any(g["kind"] == "concept_without_label" for g in parsed["gaps"])


def test_a_label_in_no_language_is_a_named_gap(tmp_path):
    f = tmp_path / "n.rdf"
    f.write_text(
        '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:skos="http://www.w3.org/2004/02/skos/core#"><skos:Concept rdf:about="u:a">'
        "<skos:prefLabel>A</skos:prefLabel></skos:Concept></rdf:RDF>",
        encoding="utf-8",
    )
    parsed = skos.parse_rdfxml(f)
    assert {"kind": "label_without_language", "detail": "u:a"} in parsed["gaps"]


def test_same_word_in_two_schemes_is_two_exact_tags_and_exact_beats_approx():
    def art(scheme, uri, pref, alt=None):
        return {"scheme": scheme, "concepts": {uri: {"pref": {"en": pref}, "alt": {"en": alt or []}, "broader": []}}}

    idx = tt.Index([art("eurovoc", "e:1", "water"), art("agrovoc", "a:1", "water")])
    tags = tt.tag_text("water", "en", idx)
    assert {(t.scheme, t.tier) for t in tags} == {("eurovoc", "exact"), ("agrovoc", "exact")}
    # a concept hit first by an alt label (≈) and later by its pref label keeps the exact tag
    idx2 = tt.Index([art("eurovoc", "e:2", "sea", alt=["ocean"])])
    (t,) = tt.tag_text("ocean and sea", "en", idx2)
    assert t.tier == "exact"


def test_a_bare_nested_reference_is_not_a_concept_of_its_own(tmp_path):
    parsed = _parse_text(
        tmp_path,
        '<skos:Concept rdf:about="u:c"><skos:prefLabel>Tax</skos:prefLabel>'
        '<skos:broader><skos:Concept rdf:about="u:p"/></skos:broader></skos:Concept>'
        '<skos:Concept rdf:about="u:p"><skos:prefLabel>Money</skos:prefLabel>'
        '<skos:broader><skos:Concept rdf:about="u:z"><skos:prefLabel>partial</skos:prefLabel></skos:Concept></skos:broader>'
        "</skos:Concept>",
    )
    assert parsed["n_seen"] == 3 and parsed["gaps"] == []  # u:c, u:p, and u:z defined by its nested labels
    assert parsed["concepts"]["u:c"]["broader"] == ["u:p"]
    assert parsed["concepts"]["u:p"]["broader"] == ["u:z"]  # the parent's links are not overwritten
    assert parsed["concepts"]["u:z"]["pref"] == {"en": "partial"}  # a nested concept WITH labels defines it


def test_one_gap_per_concept_for_labels_without_language(tmp_path):
    f = tmp_path / "n.rdf"
    f.write_text(
        '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:skos="http://www.w3.org/2004/02/skos/core#"><skos:Concept rdf:about="u:a">'
        "<skos:prefLabel>A</skos:prefLabel><skos:altLabel>B</skos:altLabel></skos:Concept></rdf:RDF>",
        encoding="utf-8",
    )
    kinds = [g["kind"] for g in skos.parse_rdfxml(f)["gaps"]]
    assert kinds.count("label_without_language") == 1


def test_a_labelless_top_level_entry_and_a_nested_labelled_one_are_one_defined_concept(tmp_path):
    nested = (
        '<skos:Concept rdf:about="a"><skos:broader><skos:Concept rdf:about="p"><skos:prefLabel>P</skos:prefLabel>'
        '</skos:Concept></skos:broader><skos:prefLabel>A</skos:prefLabel></skos:Concept>'
    )
    bare = '<skos:Concept rdf:about="p"/>'
    for body in (nested + bare, bare + nested):
        parsed = _parse_text(tmp_path, body)
        assert sorted(parsed["concepts"]) == ["a", "p"]
        assert parsed["n_seen"] == 2 and parsed["gaps"] == []
