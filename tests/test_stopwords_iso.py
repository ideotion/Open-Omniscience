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

from src.analytics.extract import global_stopwords
from src.services.stopwords import STOPWORDS_ISO_AS_OF, stopwords_manager

_LANGS = ["tr", "ro", "uk", "fi", "ur", "cs", "ca", "sk", "et", "hi", "vi", "bn", "fa", "sw"]


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


def test_as_of_is_set():
    assert STOPWORDS_ISO_AS_OF and len(STOPWORDS_ISO_AS_OF) >= 4
