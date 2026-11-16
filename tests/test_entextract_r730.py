"""R730 (field test 2026-11-14 row 70): per-language person and organisation rejects.

Measured junk from Nordic news: "Afrika För" (a place + a capitalised function word across a headline
break), "Borgåbon Olivia" (a Swedish demonym + a first name), "Tampereen Nokia" (Tampere's genitive + a
brand) as persons, and "VM" (the world championships) as an organisation. Every rule runs only for the
languages it was tested on; an article without a language gets the extractor it had before.

The SAMPLE below is the before/after measure the ruling asks for: hand-written sentences in nine
languages carrying the field cases and ordinary named people, counted by ``sample_counts``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.timemap import entextract
from src.timemap.entextract import extract_entities

#: (language, text, real people the text names, junk the field test saw or its shape).
SAMPLE: list[tuple[str, str, set[str], set[str]]] = [
    ("sv", "Skriver VM-historia – första gången i Afrika\nFör första gången arrangeras VM i Afrika, sade tränaren Anna Svensson.",
     {"Anna Svensson"}, {"Afrika För", "VM"}),
    ("sv", "Olivia Kindstedt siktar på VM-guld. Den unga Borgåbon Olivia Kindstedt tränar hårt, sade coachen Hans Berg.",
     {"Hans Berg"}, {"Borgåbon Olivia", "VM"}),
    ("sv", "Enligt den nyblivna Stockholmsbon Erik Larsson och ministern Magdalena Andersson ökar stödet, och Ulf Kristersson svarade.",
     {"Magdalena Andersson", "Ulf Kristersson"}, {"Stockholmsbon Erik"}),
    ("fi", "Ottelu pelattiin Tampereen Nokia Arenalla, ja valmentaja Jukka Jalonen kiitti joukkuetta. Pelaaja Olli Määttä loukkaantui.",
     {"Jukka Jalonen", "Olli Määttä"}, {"Tampereen Nokia"}),
    ("da", "Det skete i går, og ministeren Mette Frederiksen sagde, at holdet vandt EM-guld. EM blev holdt i Danmark.",
     {"Mette Frederiksen"}, {"EM"}),
    ("nb", "Laget vant OS-gull i fjor, sa treneren Ole Gunnar Solskjær og spilleren Erling Haaland. OS samlet mange.",
     {"Erling Haaland"}, {"OS"}),
    ("de", "Die Kanzlerin sagte gestern, dass der Minister Olaf Scholz und die Abgeordnete Ricarda Lang im Bundestag sprachen.",
     {"Olaf Scholz", "Ricarda Lang"}, set()),
    ("en", "The meeting was chaired by Prime Minister Keir Starmer and attended by envoy Theresa May on Monday.",
     {"Keir Starmer", "Theresa May"}, set()),
    ("fr", "Selon le ministre Gabriel Attal, la réforme avance, a déclaré mardi la députée Marine Le Pen.",
     {"Gabriel Attal"}, set()),
]


@pytest.fixture
def tampere_in_gazetteer(monkeypatch):
    """The Finnish genitive rule needs the gazetteer to know the place. A clean install ships a 21-city
    sample without Tampere; a generated ``cities.yml`` has it (a Finnish city of 240,000). The test supplies it."""
    real = entextract._is_fi_city
    monkeypatch.setattr(entextract, "_is_fi_city", lambda n: n.strip().lower() == "tampere" or real(n))


def sample_counts(with_language: bool) -> dict[str, int]:
    kept_real = junk = 0
    for lang, text, real, bad in SAMPLE:
        res = extract_entities(text, language=lang if with_language else None)
        names = {e["name"] for e in res["people"]} | {e["name"] for e in res["organizations"]}
        kept_real += len(real & names)
        junk += len(bad & names)
    return {"real_people_kept": kept_real, "junk_found": junk, "real_people": sum(len(r) for _, _, r, _ in SAMPLE)}


def test_the_sample_before_and_after(tampere_in_gazetteer):
    before = sample_counts(with_language=False)  # exactly the pre-R730 extractor
    after = sample_counts(with_language=True)
    # The figures the PR states: all seven junk names before, none after; no real name lost.
    assert before["junk_found"] == 7
    assert after["junk_found"] == 0
    assert after["real_people_kept"] == before["real_people_kept"]


@pytest.mark.parametrize("lang, text, junk", [(lang, text, bad) for lang, text, _real, bad in SAMPLE if bad])
def test_each_field_case_is_rejected_in_its_language(tampere_in_gazetteer, lang, text, junk):
    res = extract_entities(text, language=lang)
    names = {e["name"] for e in res["people"]} | {e["name"] for e in res["organizations"]}
    assert not (junk & names)


def test_no_rule_runs_without_a_language_or_in_an_untested_one():
    text = "Skriver VM-historia – första gången i Afrika\nFör första gången arrangeras VM i Afrika."
    for lang in (None, "", "pl", "et"):
        res = extract_entities(text, language=lang)
        assert {e["name"] for e in res["people"]} == {"Afrika För"}
        assert {e["name"] for e in res["organizations"]} == {"VM"}


def test_the_nordic_event_abbreviations_stay_organisations_elsewhere():
    # "OS" is not a Nordic sports event in an English article; the stop applies to the Nordic tags only.
    text = "The OS update shipped. Engineers said the OS was faster."
    assert {e["name"] for e in extract_entities(text, language="en")["organizations"]} == {"OS"}


def test_given_names_in_a_grammar_list_are_never_rejected():
    for lang, name in (("sv", "Hans Berg"), ("fi", "Olli Rehn"), ("en", "Theresa May"), ("de", "Ernst Fischer"), ("nb", "Ville Haugen")):
        text = f"Det var en dag och ministern sade att tränaren {name} kom. " if lang != "en" else f"the minister said that {name} came."
        assert name in {e["name"] for e in extract_entities(text, language=lang)["people"]}, (lang, name)


def test_a_finnish_name_ending_in_n_is_not_a_genitive_without_a_gazetteer_place():
    text = "Kokouksessa puhui valtiovarainministeri Johan Lindberg, ja keskustelu jatkui pitkään."
    assert "Johan Lindberg" in {e["name"] for e in extract_entities(text, language="fi")["people"]}


# ---- the second review's cases: real names the first rule set dropped --------------------- #

@pytest.mark.parametrize("lang, text, name", [
    ("de", "Das Buch von Thomas Mann erschien gestern.", "Thomas Mann"),
    ("de", "Ein Gespräch mit Sebastian Kurz fand statt.", "Sebastian Kurz"),
    ("de", "Das ist ein Film von Fritz Lang aus Berlin.", "Fritz Lang"),
    ("de", "Das ist das Buch von Michael Ende für Kinder.", "Michael Ende"),
    ("de", "Danach sagte Christian Lange etwas.", "Christian Lange"),
    ("sv", "Det var enligt Dag Hammarskjöld en bra dag.", "Dag Hammarskjöld"),
    ("sv", "Det sa sångaren Till Lindemann i går.", "Till Lindemann"),
    ("fi", "Asiasta kertoi Aina Wifalk eilen.", "Aina Wifalk"),
    ("fi", "Asiasta kertoi Eli Wiesel eilen.", "Eli Wiesel"),
    ("nb", "Det sa Fritz Lang i går.", "Fritz Lang"),
    ("en", "The goal was scored, said Emre Can on Sunday.", "Emre Can"),
    ("fr", "Selon Mme Le Pen hier, la réforme avance.", "Le Pen"),
    ("fr", "Le but de attaquant Son Heung-min a compté.", "Son Heung-min"),
    ("sv-FI", "Det var enligt Dag Hammarskjöld en bra dag.", "Dag Hammarskjöld"),
])
def test_a_surname_or_given_name_that_is_also_a_word_is_kept(lang, text, name):
    assert name in {e["name"] for e in extract_entities(text, language=lang)["people"]}


def test_a_finnish_name_whose_stem_is_a_small_or_foreign_place_is_kept(monkeypatch):
    # Simo is a Finnish municipality of about 3,000; Hel is in Poland. Neither makes "Simon" or "Helen" a genitive.
    from src.catalog.cities import City

    pair = {("simo", "fi"): City(name="Simo", lat=65.6, lon=25.0, country="fi", population=3000),
            ("hel", "pl"): City(name="Hel", lat=54.6, lon=18.8, country="pl", population=3300),
            ("tampere", "fi"): City(name="Tampere", lat=61.5, lon=23.8, country="fi", population=240000)}
    monkeypatch.setattr("src.catalog.cities.cached_index", lambda: {"pair": pair, "name": {}})
    for text, name in (("Asiasta puhui kansanedustaja Simon Elo eilen.", "Simon Elo"),
                       ("Asiasta puhui pääministeri Helen Clark eilen.", "Helen Clark")):
        assert name in {e["name"] for e in extract_entities(text, language="fi")["people"]}, name
    junk = extract_entities("Ottelu pelattiin Tampereen Nokia Arenalla eilen.", language="fi")["people"]
    assert "Tampereen Nokia" not in {e["name"] for e in junk}


def test_a_candidate_across_a_line_break_is_not_a_name_in_a_tested_language():
    text = "Kriget i Ukraina\nStora protester i Stockholm i dag."
    assert "Ukraina Stora" not in {e["name"] for e in extract_entities(text, language="sv")["people"]}


def test_nynorsk_and_bokmal_share_one_list():
    assert entextract._function_words("nn") == entextract._function_words("nb") != frozenset()
