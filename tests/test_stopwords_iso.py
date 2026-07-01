"""Vendored stopwords-iso lists for the no_stoplist languages (2026-06-23).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-06-23 keyword-engine report showed ~88k keywords leaking function words
in space-segmented languages with NO stoplist (tr/ro/uk/fi/ur/cs/ca/sk/et/hi/vi/
bn/fa/sw). We vendor a SUBSET of stopwords-iso (MIT) and apply it LANGUAGE-SCOPED:
``get_stopwords(lang)`` returns it for THAT language, but it is kept OUT of the
language-agnostic ``global_stopwords()`` union — so a word grammatical in one
language (vi "nam") can never hide a content word ("Nam") in another.
"""

from __future__ import annotations

import pathlib

from src.analytics.extract import BaselineExtractor, global_stopwords
from src.services.stopwords import STOPWORDS_ISO_AS_OF, stopwords_manager

_LANGS = [
    # 2026-06-23 original no_stoplist wave
    "tr", "ro", "uk", "fi", "ur", "cs", "ca", "sk", "et", "hi", "vi", "bn", "fa", "sw",
    # 2026-07-01 wave: full scoped lists for managed languages that had only partial batches
    "ar", "bg", "da", "de", "el", "es", "hr", "hu", "id", "it",
    "nl", "no", "nb", "pl", "pt", "ru", "sl", "sv",
    # 2026-07-01 follow-up: bs aliased to the Croatian (hr) BCS list.
    "bs",
]


def test_vendored_files_exist_and_load():
    base = pathlib.Path(__file__).resolve().parents[1] / "configs" / "stopwords_iso"
    for lang in _LANGS:
        assert (base / f"{lang}.txt").is_file(), f"missing vendored stoplist {lang}"
        assert lang in stopwords_manager.scoped_stopwords
        assert stopwords_manager.scoped_stopwords[lang], f"{lang} stoplist is empty"


def test_scoped_list_is_returned_for_its_language():
    # Real function words from the 2026-06-23 log are now filtered for their language.
    assert "ise" in stopwords_manager.get_stopwords("tr")
    assert "ilk" in stopwords_manager.get_stopwords("tr")
    assert {"sau", "iar", "pentru"} <= stopwords_manager.get_stopwords("ro")
    assert {"jen", "pak"} <= stopwords_manager.get_stopwords("cs")
    # An unknown language still falls back to the English default (unchanged behaviour).
    assert "the" in stopwords_manager.get_stopwords("zz")


def test_scoped_lists_are_applied_per_language_not_globally():
    """The collision mechanism: the scoped channel adds per-language stopwords that
    are NOT folded into the language-agnostic ``global_stopwords()`` union — so a word
    grammatical in one language can never hide that token in EVERY language. (Some
    words may ALSO be in the global union from the hand-built batches; the guarantee is
    that the scoped channel does not BY ITSELF globalise them — proven by the large set
    of scoped words absent from the global union.)"""
    g = global_stopwords()
    for lang in ("tr", "ro", "fi", "vi", "cs"):
        scoped = stopwords_manager.get_stopwords(lang)
        only_scoped = scoped - g
        assert only_scoped, (
            f"{lang}: every scoped word is also global — the scoping would be pointless"
        )
        # And those words ARE applied for this language (the extraction stopset).
        from src.analytics.extract import _stopset

        assert only_scoped <= _stopset(lang), f"{lang}: scoped words not applied at extraction"


def test_2026_07_01_full_scoped_lists_filter_grammar_per_language():
    """The 2026-07-01 wave: managed languages that leaked grammar (they had only
    partial hand-grown batches) now carry the FULL stopwords-iso list. A real
    auxiliary/function word is filtered for its language."""
    cases = {
        "de": ("wurden", "und", "der"),  # aux "were" + and + the
        "ru": ("будут", "сегодня", "это"),  # aux "will" + today + this
        "es": ("serían", "el", "que"),  # aux "would-be" + the + that
        "it": ("saranno", "il", "che"),  # aux "will-be" + the + that
        "nl": ("worden", "het", "een"),  # aux "become" + the + a
        "pt": ("seria", "que", "para"),  # aux "would-be" + that + for
    }
    for lang, words in cases.items():
        sw = stopwords_manager.get_stopwords(lang)
        for w in words:
            assert w in sw, f"{lang}: {w!r} should be filtered"


def test_full_latin_lists_are_collision_free_at_extraction():
    """The load-bearing guarantee for the 2026-07-01 wave: adding the FULL German
    list (620 words incl. "die"/"man"/"was") must NOT hide those tokens when they are
    CONTENT in an English article, because the list is language-scoped, not global."""
    ex = BaselineExtractor()
    # "die"/"was" are English function words (dropped for en anyway); "man"/"state"/
    # "union" are English CONTENT and must survive despite being in the German list.
    de_words = stopwords_manager.get_stopwords("de")
    assert {"die", "man", "was"} <= de_words  # they ARE in the German scoped list
    en = ex.extract(
        "The man reformed the state as the union met to weigh the die that was cast.",
        language="en",
    )
    kept = {k.normalized for k in en}
    assert {"man", "state", "union"} <= kept, kept  # English content untouched
    # ...and the German words are NOT globalised by the scoped channel.
    g = global_stopwords()
    assert "wurden" not in g and "serían" not in g and "saranno" not in g


def test_bosnian_is_aliased_to_the_croatian_bcs_list():
    """bs is absent from stopwords-iso; BCS/Serbo-Croatian Latin function words are shared,
    so bs is sourced from the Croatian (hr) list — a documented alias, not a fabrication."""
    base = pathlib.Path(__file__).resolve().parents[1] / "configs" / "stopwords_iso"
    hr = {w for w in (base / "hr.txt").read_text(encoding="utf-8").split() if w}
    bs = {w for w in (base / "bs.txt").read_text(encoding="utf-8").split() if w}
    assert hr and bs == hr, "bs.txt should mirror the Croatian (hr) BCS list"
    # bs previously ran on the ENGLISH default; it now carries the real BCS grammar.
    assert stopwords_manager.get_stopwords("bs") >= hr


def test_curated_temporal_adverbs_are_scoped_and_collision_free():
    """The 2026-07-01 curated layer: yesterday/tomorrow leaked as top keywords in every
    managed language even after the iso lists (they carried 'today' but not the rest).
    They are filtered per-language, kept OUT of the global union, and never touch a
    same-spelled content word in another language."""
    ex = BaselineExtractor()
    # filtered for their language (a real news sentence loses the temporal adverb)
    cases = {
        "de": ("Gestern und morgen tagt der Ausschuss.", {"gestern", "morgen"}),
        "ru": ("Вчера и завтра пройдёт саммит.", {"вчера", "завтра"}),
        "es": ("Ayer y mañana se reúne el comité.", {"ayer", "mañana"}),
        "nl": ("Gisteren en morgen vergadert de raad.", {"gisteren", "morgen"}),
        "bs": ("Juče i sutra zasjeda odbor.", {"juče", "sutra"}),
    }
    for lang, (txt, temporal) in cases.items():
        kept = {k.normalized for k in ex.extract(txt, language=lang)}
        assert not (temporal & kept), f"{lang}: temporal adverb leaked: {temporal & kept}"
    # collision-free: none of them are globalised (else they'd hide these tokens everywhere)
    g = global_stopwords()
    assert not ({"gestern", "morgen", "вчера", "mañana", "gisteren", "juče"} & g)
    # and applied only to the right language (de gestern, but not es)
    assert "gestern" in stopwords_manager.get_stopwords("de")
    assert "gestern" not in stopwords_manager.get_stopwords("es")


def test_open_class_closed_gaps_and_platform_furniture_are_filtered():
    """The open-class detector surfaced two low-dual-use wins: CLOSED-CLASS English
    indefinite pronouns (a gap in the base list) and platform/publishing FURNITURE (the
    same class English already stoplists: photo/video/story). Both are filtered; the
    collision-risky fr 'content' (= happy) is NOT globalised."""
    en = stopwords_manager.get_stopwords("en")
    assert {"something", "everyone", "nothing", "none", "anyone", "anybody"} <= en
    assert {"podcast", "newsletter", "cookies", "gallery", "comments"} <= en
    # per-language publishing furniture rides the language-scoped channel
    assert "inhalte" in stopwords_manager.get_stopwords("de")
    assert "publicidad" in stopwords_manager.get_stopwords("es")
    assert "реклама" in stopwords_manager.get_stopwords("ru")
    assert "column" in stopwords_manager.get_stopwords("nl")
    # COLLISION avoided: fr 'content' (happy) is a real word — it must NOT be globalised,
    # and the scoped publishing words must never reach the global union either.
    g = global_stopwords()
    assert "content" not in g
    assert not ({"contenido", "inhalte", "publicidad"} & g)


def test_as_of_is_set():
    assert STOPWORDS_ISO_AS_OF and len(STOPWORDS_ISO_AS_OF) >= 4
