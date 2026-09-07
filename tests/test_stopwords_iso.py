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
from src.services.stopwords import (
    CURATED_SCOPED_STOPWORDS,
    PUBLISHING_BOILERPLATE_SCOPED,
    STOPWORDS_ISO_AS_OF,
    StopwordsManager,
    stopwords_manager,
)

_LANGS = [
    # 2026-06-23 original no_stoplist wave
    "tr", "ro", "uk", "fi", "ur", "cs", "ca", "sk", "et", "hi", "vi", "bn", "fa", "sw",
    # 2026-07-01 wave: full scoped lists for managed languages that had only partial batches
    "ar", "bg", "da", "de", "el", "es", "hr", "hu", "id", "it",
    "nl", "no", "nb", "pl", "pt", "ru", "sl", "sv",
    # 2026-07-01 follow-up: bs aliased to the Croatian (hr) BCS list.
    "bs",
    # 2026-07-10 segmenter wave: zh/ja/th become segmentable via the [segmentation]
    # extra so their stoplist applies; ko (Hangul) + mr (Marathi) are space-segmented.
    "zh", "ja", "th", "ko", "mr",
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


# --- 2026-09-05 reviewed keyword-triage batch ------------------------------------- #
# The keyword-triage proposal in the 2026-09-05 AI-diagnostics export proposed 20,611
# terms as junk. The reviewed batch below is the twenty that survive the inclusion rule
# in PUBLISHING_BOILERPLATE_SCOPED's comment; the rest is refused, and the named
# refusals are pinned by test_2026_09_05_refused_terms_stay_out_of_every_stoplist.

_BATCH_20260905: dict[str, set[str]] = {
    "de": {"inhaltsverzeichnis", "aufklappen", "weiterlesen", "herunterladen", "originalpreis"},
    "nl": {"colofon", "rubriek", "rubrieken", "wachtwoord", "downloaden", "cookiebeleid"},
    "sv": {"inloggad", "webbplats", "webbplatsen", "användarvillkor", "a-ö"},
    "da": {"hjemmeside", "nyhedsbreve"},
}


def test_2026_09_05_publishing_chrome_batch_is_filtered_per_language():
    """Site CHROME the model flagged and a reviewer verified: a share/copy/login/paywall/
    navigation label is never what an article is ABOUT. Behavioural — the real extractor
    over a real sentence, because a membership assertion passes even if the word could
    never have been tokenised in the first place (sv "a-ö" is exactly that shape)."""
    ex = BaselineExtractor()
    cases = {
        "de": "Das Inhaltsverzeichnis aufklappen und den Originalpreis herunterladen, "
        "dann weiterlesen im Bericht.",
        "nl": "Het colofon en de rubriek tonen het wachtwoord, cookiebeleid en "
        "downloaden van rubrieken.",
        "sv": "Du är inloggad på webbplatsen och webbplats visar användarvillkor samt "
        "a-ö register.",
        "da": "Ministeriets hjemmeside sender nyhedsbreve til alle borgere i landet.",
    }
    for lang, txt in cases.items():
        kept = {k.normalized for k in ex.extract(txt, language=lang)}
        leaked = _BATCH_20260905[lang] & kept
        assert not leaked, f"{lang}: chrome leaked as a keyword: {sorted(leaked)}"


def test_2026_09_05_batch_is_scoped_and_never_globalised():
    """The collision guarantee, on a pair where it does real work rather than a
    hypothetical one: nl "downloaden" and da "hjemmeside" are ORDINARY WORDS in de and
    nb respectively, so scoping them to the wrong language would hide a live token in a
    language nobody reviewed."""
    ex = BaselineExtractor()
    g = global_stopwords()
    for lang, words in _BATCH_20260905.items():
        assert words <= stopwords_manager.get_stopwords(lang), lang
        assert not (words & g), f"{lang}: batch reached the global union: {sorted(words & g)}"
    # de keeps "downloaden" (a real German verb); nb keeps "hjemmeside".
    de = {k.normalized for k in ex.extract("Wir wollen die Datei downloaden können.", language="de")}
    assert "downloaden" in de
    nb = {k.normalized for k in ex.extract("Kommunens hjemmeside ble oppdatert i går.", language="nb")}
    assert "hjemmeside" in nb


def test_2026_09_05_turkish_cta_phrases_are_matched_as_joined_ngrams():
    """Multi-word entries are matched against the JOINED n-gram (extract.py's
    ``phrase in stop``) — the shape the vendored lists already use. The component
    unigrams are ordinary Turkish verbs and MUST survive: stoplisting "oku" (read) or
    "paylaş" (share) to kill a button label would delete the verbs with it.

    Stated limit: only the exact joined form is matched, so a LONGER n-gram overlapping
    the phrase still leaks ("devamını oku sayfasında"). In the 2026-09-05 export the
    CTAs occur only as the bare bigrams (35m/35a and 22m/2a), with no overlapping
    trigram extracted, so this covers what the corpus actually contains."""
    ex = BaselineExtractor()
    kept = {
        k.normalized
        for k in ex.extract("Bu haberi paylaş ve devamını oku sayfasında.", language="tr")
    }
    assert not ({"haberi paylaş", "devamını oku"} & kept)
    assert {"haberi", "paylaş", "devamını", "oku"} <= kept
    assert not ({"haberi paylaş", "devamını oku"} & global_stopwords())


def test_2026_09_05_refused_terms_stay_out_of_every_stoplist():
    """The other half of a reviewed batch: what was CONSIDERED and REFUSED, pinned so a
    later sweep has to argue with the reason instead of rediscovering it. sv
    "bindningstid" (725m/363a) and "nyhetssajter" (598m/299a) read as pure paywall
    furniture by df and are real Swedish consumer-affairs / media-industry topics; sv
    "kakor" is also biscuits; tr "günaydın" is a greeting and a proper-noun collision;
    de "abmelden" (deregister a residence) and nl "abonnementen" are dual use."""
    refused = {
        "sv": {"bindningstid", "nyhetssajter", "kakor"},
        "tr": {"günaydın"},
        "de": {"abmelden"},
        "nl": {"abonnementen"},
    }
    g = global_stopwords()
    for lang, words in refused.items():
        got = stopwords_manager.get_stopwords(lang)
        assert not (words & got), f"{lang}: refused term entered the stoplist: {sorted(words & got)}"
        assert not (words & g), f"{lang}: refused term was globalised: {sorted(words & g)}"


def test_curated_scoped_keys_never_shrink_a_stopset():
    """``__init__`` does ``scoped_stopwords.setdefault(lang, set()).update(curated)``, so a
    curated key for a language with NO vendored configs/stopwords_iso/<lang>.txt CREATES
    that key — and ``get_stopwords`` then stops falling back to the English default and
    returns the curated words ALONE. The hazard is proven here rather than asserted,
    because it is invisible in every existing test (all current keys have a file)."""
    base = pathlib.Path(__file__).resolve().parents[1] / "configs" / "stopwords_iso"
    vendored = {p.stem.lower() for p in base.glob("*.txt")}
    for name, src in (
        ("CURATED_SCOPED_STOPWORDS", CURATED_SCOPED_STOPWORDS),
        ("PUBLISHING_BOILERPLATE_SCOPED", PUBLISHING_BOILERPLATE_SCOPED),
    ):
        missing = sorted(set(src) - vendored)
        assert not missing, (
            f"{name} keys without a vendored stopwords_iso file: {missing} — each would "
            "REPLACE that language's English-default fallback with the curated words alone"
        )
    # The hazard is real: one curated word for a file-less language collapses its stopset.
    m = StopwordsManager()
    absent = next(c for c in ("sr", "lb", "eu", "zz") if c not in m.scoped_stopwords)
    before = len(m.get_stopwords(absent))
    m.scoped_stopwords.setdefault(absent, set()).update({"reklama"})
    assert before > 20 and len(m.get_stopwords(absent)) == 1, (
        "the shrink hazard this guard exists for is no longer reproducible — "
        "re-derive the guard before relaxing it"
    )


# --------------------------------------------------------------------------- #
#  The branch order in get_stopwords — why per-language scoping is unavailable
#  for en/fr, and why month scoping is an architecture change (2026-09-07)
# --------------------------------------------------------------------------- #

def test_language_stopwords_is_tested_first_so_en_and_fr_never_reach_the_scoped_channel():
    """Behavioural proof of the branch order, not a source read.

    ``get_stopwords`` tests ``language_stopwords`` BEFORE ``scoped_stopwords``, so for a
    language present in the first dict the second is unreachable. That is the whole
    reason "just scope the month names per language" is a stoplist-ARCHITECTURE change
    rather than a data-file edit: a curated ``en``/``fr`` word can only go into
    ``LANGUAGE_STOPWORDS``, which ``extract.global_stopwords()`` unions — i.e. globally,
    hiding that spelling in every corpus language."""
    m = StopwordsManager()
    for lang in ("en", "fr"):
        assert lang in m.language_stopwords
        m.language_stopwords[lang].add("zzfirstchannel")
        m.scoped_stopwords.setdefault(lang, set()).add("zzsecondchannel")
        got = m.get_stopwords(lang)
        assert "zzfirstchannel" in got
        assert "zzsecondchannel" not in got, (
            f"{lang} now reaches the scoped channel — the branch order changed, so a "
            "curated word for it is no longer necessarily global. Re-read the "
            "get_stopwords docstring before relaxing this."
        )
    # A language NOT in the first dict does reach the scoped channel — the same
    # mechanism, seen from the other side, so this is a branch-order guard and not a
    # blanket "scoping never works" claim.
    m.scoped_stopwords.setdefault("de", set()).add("zzsecondchannel")
    assert "de" not in m.language_stopwords
    assert "zzsecondchannel" in m.get_stopwords("de")


def test_the_global_channel_holds_exactly_en_and_fr():
    """Adding a key here MOVES that language from the collision-free scoped channel to
    the collision-prone global one (English "content" is French *content* = happy). That
    is a reviewed decision, never a silent edit — so it reddens here first."""
    from src.services.stopwords import StopwordsManager as _SM

    assert set(_SM.LANGUAGE_STOPWORDS) == {"en", "fr"}, (
        "LANGUAGE_STOPWORDS gained or lost a language: every word curated for it is now "
        "unioned into global_stopwords() and needs cross-language collision review"
    )


def test_the_banned_month_forms_that_hurt_most_collide_within_english():
    """Why scoping is a COMPLEMENT to the date-aware block and not a replacement for it:
    ``march``/``may``/``april``/``august`` are English months in English documents, so a
    per-language stoplist could not recover the March on Washington or Theresa May even
    if the scoped channel were reachable for ``en``. Only the date extractor's own claim
    on a span separates a dateline from a topic."""
    from src.analytics.month_occupancy import banned_month_tokens

    banned = banned_month_tokens()
    within_english = {"march", "may", "april", "august"}
    still_banned = {t for t in within_english if t in banned}
    assert still_banned == within_english, (
        f"only {sorted(still_banned)} of {sorted(within_english)} are still banned — "
        "re-derive the month-scoping argument against the current vocabulary"
    )
    # And they are banned out of the extractor's LANGUAGE-AGNOSTIC table ("global"), not
    # a language-hinted one — a second reason a per-language stoplist has nothing to
    # scope here. (The provenance values are table names, never language codes:
    # month_vocabulary() reports global / gated / thai / jalali.)
    for token in within_english:
        assert "global" in banned[token], (
            f"{token} is no longer in the language-agnostic month table "
            f"(now {banned[token]}) — the scoping argument needs re-deriving"
        )
