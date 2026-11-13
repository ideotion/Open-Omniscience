"""v0.6.0 row C (Q913): the labelled law-titles sample, its measurement script, and the ≈ policy for languages written
without spaces (R680, OPEN_QUEUE 38(d)). Offline fixtures only; the real thesauri are operator-built after a licence fetch.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.catalog import topic_tagging as tt

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "src" / "catalog" / "data" / "topic_sample_law_titles.json"
UI_LANGUAGES = {"en", "fr", "de", "es", "pt", "ar", "ru", "zh", "ja", "hi", "bn", "id"}


def _art(scheme="eurovoc", **concepts):
    """concepts: uri=(pref {lang: label}, alt {lang: [labels]})"""
    return {"scheme": scheme, "vintage": "test", "license": "test", "upstream": "test",
            "concepts": {u: {"pref": p, "alt": a, "broader": []} for u, (p, a) in concepts.items()}}


@pytest.fixture()
def zh_index():
    return tt.Index([_art(
        env=({"zh": "环境保护", "en": "environmental protection"}, {}),
        info=({"zh": "个人信息"}, {}),
        infop=({"zh": "个人信息保护"}, {}),
        law=({"zh": "法"}, {}),
    )])


# --- R680: a language written without spaces --------------------------------------------------------------------------


def test_an_unsegmented_label_is_found_inside_a_run_of_text_and_is_always_approximate(zh_index):
    tags = tt.tag_text("中华人民共和国环境保护法", "zh", zh_index)
    assert [(t.concept, t.tier, t.approx_reason) for t in tags] == [("env", "approx", "unsegmented_substring")]


def test_a_one_character_label_is_never_matched_and_is_counted_not_dropped(zh_index):
    assert all(t.concept != "law" for t in tt.tag_text("国旗法", "zh", zh_index))
    assert zh_index.short_labels == {"zh": 1}
    m = tt.measure([{"id": "x", "lang": "zh", "text": "国旗法", "expected": []}], zh_index)
    assert m["one_character_labels_skipped"] == {"zh": 1} and m["n_items"] == 1
    # a language whose ONLY labels are one character long cannot be tagged at all: set aside, never scored as zero
    only_short = tt.Index([_art(law=({"zh": "法"}, {}))])
    m = tt.measure([{"id": "x", "lang": "zh", "text": "国旗法", "expected": ["law"]}], only_short)
    assert m["n_items"] == 0 and m["unsupported_languages"] == {"zh": 1}


def test_the_longest_label_wins_and_a_match_never_crosses_punctuation_or_space(zh_index):
    assert [t.concept for t in tt.tag_text("个人信息保护法", "zh", zh_index)] == ["infop"]
    assert tt.tag_text("环境，保护", "zh", zh_index) == [] and tt.tag_text("环境 保护", "zh", zh_index) == []


def test_a_segmented_language_still_needs_whole_words(zh_index):
    assert [t.tier for t in tt.tag_text("an environmental protection act", "en", zh_index)] == ["exact"]
    assert tt.tag_text("environmental protectionism", "en", zh_index) == []


def test_measure_scores_an_unsegmented_language_that_has_labels_and_sets_aside_one_that_has_none(zh_index):
    sample = [
        {"id": "a", "lang": "zh", "text": "环境保护法", "expected": ["env"]},
        {"id": "b", "lang": "ja", "text": "環境基本法", "expected": ["env"]},
        {"id": "c", "lang": "hi", "text": "पर्यावरण संरक्षण अधिनियम", "expected": ["env"]},
    ]
    m = tt.measure(sample, zh_index)
    assert m["n_items"] == 1 and m["unsupported_languages"] == {"ja": 1, "hi": 1}
    assert m["approx_share"] == {"value": 1.0, "n": 1} and m["recall"] == {"value": 1.0, "n": 1}
    assert "R680" in m["method"]


# --- resolving the sample's labels against ONE thesaurus -------------------------------------------------------------


def test_a_label_is_resolved_only_to_one_concept_and_otherwise_listed_unresolved():
    art = _art(a=({"en": "Data protection"}, {}), b=({"en": "copyright"}, {}), c=({"en": "copyright"}, {}))
    sample = [{"id": "1", "lang": "en", "text": "t", "expected_labels": [
        {"scheme": "eurovoc", "label": "data protection"},  # case-folded, found
        {"scheme": "eurovoc", "label": "copyright"},  # two concepts share it: not one concept
        {"scheme": "eurovoc", "label": "climate change"},  # absent: never matched loosely
        {"scheme": "agrovoc", "label": "data protection"},  # another thesaurus: not this one's to resolve
    ]}]
    res = tt.resolve_sample(sample, art)
    assert res["sample"] == [{"id": "1", "lang": "en", "text": "t", "expected": ["a"]}] and res["resolved"] == 1
    assert res["unresolved"] == [{"id": "1", "label": "copyright"}, {"id": "1", "label": "climate change"}]
    assert res["other_schemes"] == {"agrovoc": 1}, "a label for another thesaurus is counted, never silently dropped"


# --- the sample itself -------------------------------------------------------------------------------------------------


def test_the_sample_covers_all_twelve_languages_with_a_negative_in_each_and_says_who_labelled_it():
    doc = json.loads(SAMPLE.read_text("utf-8"))
    items = doc["items"]
    assert {i["lang"] for i in items} == UI_LANGUAGES
    assert len({i["id"] for i in items}) == len(items)
    for lang in UI_LANGUAGES:
        mine = [i for i in items if i["lang"] == lang]
        assert any(not i["expected_labels"] for i in mine), f"{lang}: no item that expects nothing"
        assert any(i["expected_labels"] for i in mine), f"{lang}: no item that expects a topic"
    assert all(e["scheme"] and e["label"] for i in items for e in i["expected_labels"])
    assert doc["as_of"] and "not a legal expert" in doc["labelled_by"] and "from memory" in doc["about"]


# --- the script --------------------------------------------------------------------------------------------------------


def _script(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "topic_sample_measure.py"), *args],
                          capture_output=True, text=True, timeout=60, cwd=ROOT)


def test_with_no_thesaurus_built_the_script_says_not_measured_and_exits_apart(tmp_path):
    r = _script("--artifact", str(tmp_path / "eurovoc.json"))
    out = json.loads(r.stdout)
    assert r.returncode == 3 and out["status"] == "not-measured" and "licence" in out["reason"]
    assert "measurement" not in out, "a not-measured run carries no figure"


def test_with_a_built_thesaurus_the_script_measures_and_states_the_approximate_share(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import topic_sample_measure as tsm

    def boom(*a, **k):
        raise AssertionError("the measurement must never touch the network")

    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, boom)
    art = _art(
        dp=({"en": "data protection", "fr": "protection des données", "es": "protección de datos"}, {}),
        tax=({"en": "income tax", "fr": "impôt sur le revenu"}, {"es": ["impuesto sobre la renta"]}),
    )
    path = tmp_path / "eurovoc.json"
    path.write_text(json.dumps(art), "utf-8")
    code, out = tsm.run(path, SAMPLE)
    assert code == 0 and out["status"] == "measured" and out["scheme"] == "eurovoc"
    m = out["measurement"]
    assert m["approx_share"]["n"] > 0 and m["approx_share"]["value"] is not None
    assert {"zh", "ja", "hi", "bn", "id", "ar", "ru"} <= set(m["unsupported_languages"]), "no label: set aside, not zero"
    assert any(u["label"] == "environmental protection" for u in out["unresolved"])


@pytest.mark.parametrize("body", ['{"scheme": "eurovoc", "concepts": []}', '{"scheme": "eurovoc", "concepts": {"u": {"pref": ["x"]}}}'])
def test_an_artifact_malformed_inside_is_not_measured_never_a_traceback(tmp_path, monkeypatch, body):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import topic_sample_measure as tsm

    path = tmp_path / "eurovoc.json"
    path.write_text(body, "utf-8")
    code, out = tsm.run(path, SAMPLE)
    assert code == 3 and out["status"] == "not-measured" and "malformed" in out["reason"]


@pytest.mark.parametrize("body", [
    None, "[]", '{"items": {}}', '{"items": [{"id": "x", "lang": "en"}]}',
    '{"items": [{"id": "x", "lang": "en", "text": "t", "expected_labels": [{"scheme": "eurovoc", "label": 5}]}]}',
    '{"items": [{"id": "x", "lang": "en", "text": "t", "expected_labels": [{"scheme": "eurovoc", "label": null}]}]}',
])
def test_a_missing_or_malformed_sample_is_not_measured_and_named(tmp_path, monkeypatch, body):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import topic_sample_measure as tsm

    sample = tmp_path / "sample.json"
    if body is not None:
        sample.write_text(body, "utf-8")
    art = tmp_path / "eurovoc.json"
    art.write_text(json.dumps(_art(dp=({"en": "data protection"}, {}))), "utf-8")
    code, out = tsm.run(art, sample)
    assert code == 3 and "sample could not be read" in out["reason"] and out["sample"] == str(sample)


def test_a_bug_on_valid_data_surfaces_as_a_bug_never_as_not_measured(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import topic_sample_measure as tsm

    path = tmp_path / "eurovoc.json"
    path.write_text(json.dumps(_art(dp=({"en": "data protection"}, {}))), "utf-8")

    def broken(*a, **k):
        raise TypeError("a regression in the tagger")

    monkeypatch.setattr(tt, "measure", broken)
    with pytest.raises(TypeError):
        tsm.run(path, SAMPLE)


# --- R690: combining marks belong to their word -------------------------------------------------------------------------


def test_a_hindi_vowel_sign_or_virama_never_splits_a_word():
    """मनुष्य ("human") once folded to मन + ुष + ्य, so the label मन ("mind") matched inside it as EXACT."""
    assert tt.fold("मनुष्य अधिकार") == ("मनुष्य", "अधिकार")
    idx = tt.Index([_art(mind=({"hi": "मन"}, {}))])
    assert tt.tag_text("मनुष्य अधिकार अधिनियम", "hi", idx) == []
    assert [(t.concept, t.tier) for t in tt.tag_text("मन की शांति", "hi", idx)] == [("mind", "exact")]


def test_a_bengali_vowel_sign_never_splits_a_word():
    assert tt.fold("মনোবিজ্ঞান আইন") == ("মনোবিজ্ঞান", "আইন")
    idx = tt.Index([_art(mind=({"bn": "মন"}, {}))])
    assert tt.tag_text("মনোবিজ্ঞান আইন", "bn", idx) == []
    assert [t.concept for t in tt.tag_text("মন ও শরীর", "bn", idx)] == ["mind"]


def test_arabic_vowelling_neither_splits_a_word_nor_hides_it():
    """A haraka once split قَانُون into ق + ان + ون, and the label ان ("that") matched a fragment."""
    assert tt.fold("قَانُون") == tt.fold("قانون") == ("قانون",)
    idx = tt.Index([_art(that=({"ar": "ان"}, {}), law=({"ar": "قانون"}, {}))])
    assert [t.concept for t in tt.tag_text("قَانُون العَمَل", "ar", idx)] == ["law"]


def test_thai_marks_stay_in_the_run_and_one_letter_with_marks_is_still_one_character(zh_index):
    env = tt.Index([_art(env=({"th": "สิ่งแวดล้อม"}, {}), that=({"th": "ที่"}, {}))])
    tags = tt.tag_text("การคุ้มครองสิ่งแวดล้อมที่ดี", "th", env)
    assert [(t.concept, t.tier) for t in tags] == [("env", "approx")], "a marked label is found, and only as ≈"
    assert env.short_labels == {"th": 1}, "ที่ is one letter and two marks: never matched (R680)"


def test_khmer_lao_and_burmese_are_unsupported_until_a_test_shows_they_work():
    idx = tt.Index([_art(law=({"km": "ច្បាប់", "lo": "ກົດໝາຍ", "my": "ဥပဒေ", "en": "law"}, {}))])
    sample = [
        {"id": "k", "lang": "km", "text": "ច្បាប់ស្តីពីការងារ", "expected": ["law"]},
        {"id": "l", "lang": "lo", "text": "ກົດໝາຍແຮງງານ", "expected": ["law"]},
        {"id": "m", "lang": "my", "text": "အလုပ်သမားဥပဒေ", "expected": ["law"]},
    ]
    m = tt.measure(sample, idx)
    assert m["unsupported_languages"] == {"km": 1, "lo": 1, "my": 1} and m["n_items"] == 0
    assert m["precision"]["value"] is None, "no precision figure for a language whose matching is unverified"
    assert m["unverified_languages"]["labels_set_aside"] == {"km": 1, "lo": 1, "my": 1}


def test_optional_points_and_joiners_and_stray_marks_never_hide_a_word():
    assert tt.fold("می\u200cخواهم") == tt.fold("میخواهم"), "a ZWNJ is written or omitted for the same word"
    assert tt.fold("शिक्\u200dषा") == tt.fold("शिक्षा")
    assert tt.fold("שָׁלוֹם") == tt.fold("שלום") == ("שלום",), "Hebrew points are optional"
    assert tt.fold("\u0301abc") == ("abc",), "a mark with no letter before it starts no word"


def test_an_unsegmented_label_with_inner_punctuation_matches_written_joined_and_is_counted():
    idx = tt.Index([_art(ict=({"ja": "情報・通信"}, {}), ir=({"ko": "국제 관계"}, {}))])
    assert idx.split_labels == {"ja": 1, "ko": 1}
    assert [t.concept for t in tt.tag_text("情報通信法", "ja", idx)] == ["ict"]
    assert [t.concept for t in tt.tag_text("국제관계법", "ko", idx)] == ["ir"]
    assert tt.tag_text("情報・通信法", "ja", idx) == [], "a match never crosses punctuation"
    m = tt.measure([{"id": "x", "lang": "ja", "text": "情報・通信法", "expected": ["ict"]}], idx)
    assert m["labels_matched_only_when_written_joined"] == {"ja": 1, "ko": 1}
