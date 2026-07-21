"""
The PROSE GATE — function-word density / prose-ness (NAV-SOUP SPECIMEN ruling, 2026-07-20).

Covers the PURE measures (tokenize_words / function_word_density / sentence_punct_density) across
several languages, the NAV-SOUP SPECIMEN shape (word-rich, punctuation-free menu chrome — expected
to score near zero and get caught), real prose in several languages (the negative space — a false
positive here is data loss), the AND-gate (either signal alone must not trigger a drop), the
unsegmented-script guard (zh/ja/th — never dropped on a measurement gap), and the house "no score
field" convention.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.services.prose_gate import (
    ProseVerdict,
    function_word_density,
    prose_gate_verdict,
    run_prose_gate_selftest,
    sentence_punct_density,
    tokenize_words,
)

_BANNED = ("score", "ranking", "rating", "grade")


def _walk_no_score(o) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            assert not any(b in str(k).lower() for b in _BANNED), k
            _walk_no_score(v)
    elif isinstance(o, list):
        for v in o:
            _walk_no_score(v)


# The specimen shape: a long menu of nav/section words, no sentences, near-zero function words —
# mirrors the actual Irish Mirror ``newsletter-preference-centre`` capture the ruling describes.
NAV_SOUP_BODY = (
    "News Latest Irish News Mirror Bingo Soccer Golf Rugby Union Sport Business Politics "
    "World News Travel Money Markets Weather Video Photos Gallery Podcast Newsletters Events "
    "About Contact Home Search Login Sign Up Subscribe Cookies Advertisement Privacy Terms "
    "Follow Facebook Twitter Instagram Newsletter Preference Centre Manage Subscriptions "
    "Menu Toggle Navigation Skip Content Latest News Sport GAA Rugby Soccer Racing Golf Boxing "
    "Motors Showbiz TV Fashion Beauty Food Recipes Property Travel Family Voucher Codes Bingo "
    "Dating Contact Advertise Cookie Policy Privacy Policy Terms Conditions Modern Slavery "
    "Statement Complaints Regulation Archive Sitemap Jobs Shop Weddings Announcements Obituaries "
    "Horoscopes Puzzles Crosswords Competitions Vouchers Discounts Deals Reviews Betting Casino "
    "Lottery Results Traffic Cameras Roadworks Bus Times Train Times Flight Tracker Currency "
    "Converter Recipes Wine Beer Cocktails Restaurants Bars Nightlife Theatre Cinema Music Books"
)

REAL_PROSE = {
    "en": "The government said on Tuesday that it would review the policy after months of "
    "criticism from opposition lawmakers, who argued that the reform had failed to deliver "
    "the promised benefits to the region's struggling economy.",
    "fr": "Le gouvernement a annonce mardi qu'il allait revoir la politique apres des mois de "
    "critiques de la part des parlementaires de l'opposition, qui affirmaient que la reforme "
    "n'avait pas apporte les benefices promis a l'economie de la region.",
    "es": "El gobierno anuncio el martes que revisaria la politica tras meses de criticas de "
    "los legisladores de la oposicion, que argumentaban que la reforma no habia logrado los "
    "beneficios prometidos para la economia de la region.",
    "de": "Die Regierung erklarte am Dienstag, dass sie die Politik nach monatelanger Kritik "
    "von Oppositionspolitikern uberprufen werde, die argumentierten, dass die Reform die "
    "versprochenen Vorteile fur die angeschlagene Wirtschaft der Region nicht gebracht habe.",
    "pt": "O governo anunciou na terca-feira que iria rever a politica apos meses de criticas "
    "dos parlamentares da oposicao, que argumentaram que a reforma nao havia entregue os "
    "beneficios prometidos para a economia da regiao.",
}


def test_tokenize_words_lowercases_and_drops_punctuation_and_digits():
    assert tokenize_words("Hello, WORLD! 123 test-case") == ["hello", "world", "test", "case"]
    assert tokenize_words("") == []
    assert tokenize_words(None) == []


def test_function_word_density_bounded_and_zero_for_empty():
    d, lang = function_word_density("", language="en")
    assert d == 0.0 and lang is None
    d, lang = function_word_density(NAV_SOUP_BODY, language="en")
    assert 0.0 <= d <= 1.0 and lang == "en"


def test_function_word_density_high_for_real_prose_every_language():
    # the negative space across languages: real prose scores comfortably above the gate's
    # density_low floor in ITS OWN asserted language.
    for lang, text in REAL_PROSE.items():
        d, best = function_word_density(text, language=lang)
        assert d >= 0.15, f"{lang}: density too low for real prose ({d})"
        assert best == lang


def test_function_word_density_best_matching_language_with_no_assertion():
    # no language given -> searches every managed language and returns the best match, which
    # should be the text's OWN language (real prose peaks in its own language).
    for lang, text in REAL_PROSE.items():
        d, best = function_word_density(text)
        assert best == lang, f"expected {lang}, best-matched {best}"


def test_sentence_punct_density_near_zero_for_menu_and_healthy_for_prose():
    p_nav = sentence_punct_density(NAV_SOUP_BODY)
    p_prose = sentence_punct_density(REAL_PROSE["en"])
    assert p_nav < 0.01
    assert p_prose > 0.02
    assert p_nav < p_prose


def test_prose_gate_catches_the_nav_soup_specimen_shape():
    v = prose_gate_verdict(NAV_SOUP_BODY, language="en")
    assert isinstance(v, ProseVerdict)
    assert v.signal == "nav_soup"
    assert "nav" in v.reason.lower() or "listing" in v.reason.lower()


def test_prose_gate_keeps_real_prose_every_language_asserted_and_auto():
    for lang, text in REAL_PROSE.items():
        long_text = (text + " ") * 4
        assert prose_gate_verdict(long_text, language=lang) is None, lang
        assert prose_gate_verdict(long_text) is None, f"{lang} (auto)"


def test_prose_gate_and_gate_either_signal_alone_is_not_enough():
    # high density, no punctuation (repeated real words, no periods) -> kept: density alone saves it
    high_density_no_punct = "the government and the people and the economy and the policy " * 10
    assert prose_gate_verdict(high_density_no_punct, language="en") is None

    # low density, WITH punctuation (a bare list of proper nouns split into "sentences") -> kept:
    # punctuation alone also saves it from the AND-gate.
    low_density_with_punct = ("Widgets. Gadgets. Sprockets. Contraptions. Doohickeys. Thingamajigs. "
                              "Gizmos. Gubbins. Whatsits. Doodads. ") * 3
    assert prose_gate_verdict(low_density_with_punct, language="en") is None

    # BOTH low -> caught (this is the actual nav-soup shape)
    assert prose_gate_verdict(NAV_SOUP_BODY, language="en") is not None


def test_prose_gate_headline_list_escapes_by_design():
    headlines = (
        "Storm warning issued for the coast. Markets fall on rate fears. Council votes on new "
        "budget plan. Local team wins the regional final. Weather turns colder into the weekend. "
    ) * 3
    assert prose_gate_verdict(headlines, language="en") is None


def test_prose_gate_never_drops_on_a_measurement_gap():
    # too little text to measure
    assert prose_gate_verdict("News Sport Weather", language="en") is None
    assert prose_gate_verdict("", language="en") is None
    assert prose_gate_verdict(None, language="en") is None

    # unsegmented script (zh) -- asserted OR detected from character composition, word-rich or not
    zh_text = "中国政府周二表示将审查该政策" * 10
    assert prose_gate_verdict(zh_text, language="zh") is None
    assert prose_gate_verdict(zh_text) is None  # no language given -> detected from characters
    ja_text = "政府は火曜日に政策を見直すと発表しました" * 10
    assert prose_gate_verdict(ja_text, language="ja") is None


def test_prose_gate_never_drops_a_managed_language_with_no_grammar_vocabulary():
    # sr/az are MANAGED (keyword extraction works, sources are enabled) but have NEITHER a
    # vendored stopwords-iso file NOR a hardcoded grammar list -- get_grammar_stopwords('sr') is
    # EMPTY. Without the guard, density collapses to 0.0 for ANY body in that language, degrading
    # the AND-gate to punctuation-only and risking a real article (a sparse-punctuation sports
    # results page, a listicle) being dropped. This is a REAL ARTICLE shape (word-rich, low
    # punctuation is common in results/listicle journalism), not the nav-soup shape -- it must be
    # kept, not caught, because the language is honestly unmeasurable here.
    sparse_punct_article = (
        "Rezultati Utakmica Fudbal Kosarka Odbojka Tenis Rukomet Vaterpolo Atletika Plivanje "
    ) * 12
    assert prose_gate_verdict(sparse_punct_article, language="sr") is None
    assert prose_gate_verdict(sparse_punct_article, language="az") is None


def test_prose_gate_never_drops_an_untagged_uncovered_language_article():
    # Code-review finding (2026-07-20 re-review): the guard above only fires when a language IS
    # asserted. But the real ingest call site (src/ingest/pipeline.py) passes doc.language, which
    # per its own docstring is populated "only when trafilatura's detector is enabled" -- commonly
    # None. With no language asserted, function_word_density auto-searches EVERY managed language's
    # grammar stoplist; for a real sr/az article none of them score above zero either (sr/az have
    # no grammar vocabulary at all), so the auto-search also finds an all-languages density of 0.0.
    # That must be treated as an untrustworthy measurement (unmeasurable -> None), not as nav-soup
    # evidence, or a real Serbian/Azerbaijani article silently becomes data loss.
    sparse_punct_article = (
        "Rezultati Utakmica Fudbal Kosarka Odbojka Tenis Rukomet Vaterpolo Atletika Plivanje "
    ) * 12
    assert prose_gate_verdict(sparse_punct_article) is None  # no language asserted at all


def test_prose_gate_selftest_all_green():
    log = run_prose_gate_selftest()
    assert log["passed"] is True, [c for c in log["checks"] if not c["passed"]]


def test_no_score_field():
    _walk_no_score(run_prose_gate_selftest())
    v = prose_gate_verdict(NAV_SOUP_BODY, language="en")
    _walk_no_score({"signal": v.signal, "reason": v.reason})
