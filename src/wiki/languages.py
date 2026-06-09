"""
Catalogue of Wikipedia language editions (for the offline-baseline picker).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A curated, neutral list of the larger Wikipedia language editions: the wiki code
(used to build dump URLs, e.g. ``en`` -> ``enwiki``), the English name and the
language's own name (autonym), a coarse *size tier* so the UI can sort
"largest first" without hardcoding article counts that go stale, and the
language's *continent of origin* so a long picker can be split into short,
scannable sections. Real download sizes are always read from the dump server at
probe time — these tiers are only for ordering and a rough "how heavy is this"
hint, never presented as a fact about the current dump.

The ``region`` is the language's geographic origin / heartland (a single,
unambiguous bucket). Many languages are spoken across several continents; we pick
one origin bucket purely so the picker groups sensibly — it is a navigation aid,
not a claim about where the language is used today.

This is data, not behaviour: the dump downloader (src.wiki.dumps) accepts ANY
edition code, so an operator can still type one not listed here.
"""

from __future__ import annotations

from dataclasses import dataclass

# Coarse size tiers (largest editions first within each). "huge" ~ multi-million
# articles, "large" ~ 1M+, "medium" ~ 100k+, "small" the rest. Ordering hint only.
_TIER_RANK = {"huge": 0, "large": 1, "medium": 2, "small": 3}

# Continent buckets, ordered so the regions carrying the largest editions come
# first in the picker. "Constructed" holds international auxiliary languages
# (Esperanto, Interlingua, …) that have no single continent of origin; it sorts
# last. Empty regions are simply omitted when grouping.
_REGION_ORDER = ("Europe", "Asia", "Africa", "Americas", "Oceania", "Constructed")
_REGION_RANK = {r: i for i, r in enumerate(_REGION_ORDER)}


@dataclass(frozen=True)
class WikiLanguage:
    code: str  # wiki edition code (en, fr, de, ...) -> {code}wiki
    name: str  # English name
    autonym: str  # the language's own name
    tier: str  # huge | large | medium | small (ordering/heaviness hint)
    region: str  # continent of origin (Europe | Asia | Africa | Americas | Oceania)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "autonym": self.autonym,
            "tier": self.tier,
            "region": self.region,
        }


# Curated list — the editions most relevant to cross-language investigative work.
# Not exhaustive (there are 300+ editions); the picker also allows a free-text code.
_LANGUAGES: tuple[WikiLanguage, ...] = (
    WikiLanguage("en", "English", "English", "huge", "Europe"),
    WikiLanguage("de", "German", "Deutsch", "huge", "Europe"),
    WikiLanguage("fr", "French", "Français", "huge", "Europe"),
    WikiLanguage("es", "Spanish", "Español", "huge", "Europe"),
    WikiLanguage("ru", "Russian", "Русский", "huge", "Europe"),
    WikiLanguage("ja", "Japanese", "日本語", "huge", "Asia"),
    WikiLanguage("zh", "Chinese", "中文", "huge", "Asia"),
    WikiLanguage("it", "Italian", "Italiano", "huge", "Europe"),
    WikiLanguage("pt", "Portuguese", "Português", "large", "Europe"),
    WikiLanguage("ar", "Arabic", "العربية", "large", "Asia"),
    WikiLanguage("fa", "Persian", "فارسی", "large", "Asia"),
    WikiLanguage("pl", "Polish", "Polski", "large", "Europe"),
    WikiLanguage("nl", "Dutch", "Nederlands", "large", "Europe"),
    WikiLanguage("uk", "Ukrainian", "Українська", "large", "Europe"),
    WikiLanguage("tr", "Turkish", "Türkçe", "large", "Asia"),
    WikiLanguage("id", "Indonesian", "Bahasa Indonesia", "large", "Asia"),
    WikiLanguage("he", "Hebrew", "עברית", "large", "Asia"),
    WikiLanguage("ko", "Korean", "한국어", "large", "Asia"),
    WikiLanguage("vi", "Vietnamese", "Tiếng Việt", "large", "Asia"),
    WikiLanguage("sv", "Swedish", "Svenska", "large", "Europe"),
    WikiLanguage("cs", "Czech", "Čeština", "medium", "Europe"),
    WikiLanguage("hu", "Hungarian", "Magyar", "medium", "Europe"),
    WikiLanguage("ro", "Romanian", "Română", "medium", "Europe"),
    WikiLanguage("fi", "Finnish", "Suomi", "medium", "Europe"),
    WikiLanguage("el", "Greek", "Ελληνικά", "medium", "Europe"),
    WikiLanguage("no", "Norwegian (Bokmål)", "Norsk bokmål", "medium", "Europe"),
    WikiLanguage("da", "Danish", "Dansk", "medium", "Europe"),
    WikiLanguage("th", "Thai", "ไทย", "medium", "Asia"),
    WikiLanguage("bg", "Bulgarian", "Български", "medium", "Europe"),
    WikiLanguage("sr", "Serbian", "Српски", "medium", "Europe"),
    WikiLanguage("hi", "Hindi", "हिन्दी", "medium", "Asia"),
    WikiLanguage("ca", "Catalan", "Català", "medium", "Europe"),
    WikiLanguage("hr", "Croatian", "Hrvatski", "medium", "Europe"),
    WikiLanguage("sk", "Slovak", "Slovenčina", "medium", "Europe"),
    WikiLanguage("lt", "Lithuanian", "Lietuvių", "medium", "Europe"),
    WikiLanguage("sl", "Slovenian", "Slovenščina", "medium", "Europe"),
    WikiLanguage("et", "Estonian", "Eesti", "medium", "Europe"),
    WikiLanguage("lv", "Latvian", "Latviešu", "medium", "Europe"),
    WikiLanguage("ms", "Malay", "Bahasa Melayu", "medium", "Asia"),
    WikiLanguage("az", "Azerbaijani", "Azərbaycanca", "medium", "Asia"),
    WikiLanguage("bn", "Bengali", "বাংলা", "medium", "Asia"),
    WikiLanguage("ka", "Georgian", "ქართული", "medium", "Asia"),
    WikiLanguage("hy", "Armenian", "Հայերեն", "medium", "Asia"),
    WikiLanguage("ur", "Urdu", "اردو", "medium", "Asia"),
    WikiLanguage("ta", "Tamil", "தமிழ்", "medium", "Asia"),
    WikiLanguage("be", "Belarusian", "Беларуская", "medium", "Europe"),
    WikiLanguage("kk", "Kazakh", "Қазақша", "medium", "Asia"),
    WikiLanguage("eu", "Basque", "Euskara", "medium", "Europe"),
    WikiLanguage("gl", "Galician", "Galego", "medium", "Europe"),
    WikiLanguage("af", "Afrikaans", "Afrikaans", "small", "Africa"),
    WikiLanguage("sw", "Swahili", "Kiswahili", "small", "Africa"),
    WikiLanguage("is", "Icelandic", "Íslenska", "small", "Europe"),
    WikiLanguage("ga", "Irish", "Gaeilge", "small", "Europe"),
    WikiLanguage("cy", "Welsh", "Cymraeg", "small", "Europe"),
    WikiLanguage("mk", "Macedonian", "Македонски", "small", "Europe"),
    WikiLanguage("sq", "Albanian", "Shqip", "small", "Europe"),
    WikiLanguage("mn", "Mongolian", "Монгол", "small", "Asia"),
    WikiLanguage("ne", "Nepali", "नेपाली", "small", "Asia"),
    WikiLanguage("my", "Burmese", "မြန်မာဘာသာ", "small", "Asia"),
    # --- Wider coverage (notable additional editions; tiers are coarse hints) ---
    # Europe
    WikiLanguage("bs", "Bosnian", "Bosanski", "medium", "Europe"),
    WikiLanguage("nn", "Norwegian (Nynorsk)", "Norsk nynorsk", "small", "Europe"),
    WikiLanguage("la", "Latin", "Latina", "small", "Europe"),
    WikiLanguage("lb", "Luxembourgish", "Lëtzebuergesch", "small", "Europe"),
    WikiLanguage("oc", "Occitan", "Occitan", "small", "Europe"),
    WikiLanguage("br", "Breton", "Brezhoneg", "small", "Europe"),
    WikiLanguage("ast", "Asturian", "Asturianu", "small", "Europe"),
    WikiLanguage("an", "Aragonese", "Aragonés", "small", "Europe"),
    WikiLanguage("fy", "West Frisian", "Frysk", "small", "Europe"),
    WikiLanguage("gd", "Scottish Gaelic", "Gàidhlig", "small", "Europe"),
    WikiLanguage("nds", "Low German", "Plattdüütsch", "small", "Europe"),
    WikiLanguage("bar", "Bavarian", "Boarisch", "small", "Europe"),
    WikiLanguage("lmo", "Lombard", "Lombard", "small", "Europe"),
    WikiLanguage("scn", "Sicilian", "Sicilianu", "small", "Europe"),
    WikiLanguage("vec", "Venetian", "Vèneto", "small", "Europe"),
    WikiLanguage("nap", "Neapolitan", "Napulitano", "small", "Europe"),
    WikiLanguage("sc", "Sardinian", "Sardu", "small", "Europe"),
    WikiLanguage("rm", "Romansh", "Rumantsch", "small", "Europe"),
    WikiLanguage("wa", "Walloon", "Walon", "small", "Europe"),
    WikiLanguage("li", "Limburgish", "Limburgs", "small", "Europe"),
    WikiLanguage("fo", "Faroese", "Føroyskt", "small", "Europe"),
    WikiLanguage("mt", "Maltese", "Malti", "small", "Europe"),
    WikiLanguage("yi", "Yiddish", "ייִדיש", "small", "Europe"),
    WikiLanguage("tt", "Tatar", "Татарча", "medium", "Europe"),
    WikiLanguage("ba", "Bashkir", "Башҡортса", "small", "Europe"),
    WikiLanguage("cv", "Chuvash", "Чӑвашла", "small", "Europe"),
    # Asia
    WikiLanguage("ceb", "Cebuano", "Sinugboanong Binisaya", "large", "Asia"),
    WikiLanguage("war", "Waray", "Winaray", "medium", "Asia"),
    WikiLanguage("tl", "Tagalog", "Tagalog", "medium", "Asia"),
    WikiLanguage("jv", "Javanese", "Basa Jawa", "medium", "Asia"),
    WikiLanguage("su", "Sundanese", "Basa Sunda", "small", "Asia"),
    WikiLanguage("min", "Minangkabau", "Baso Minangkabau", "medium", "Asia"),
    WikiLanguage("ml", "Malayalam", "മലയാളം", "medium", "Asia"),
    WikiLanguage("te", "Telugu", "తెలుగు", "medium", "Asia"),
    WikiLanguage("kn", "Kannada", "ಕನ್ನಡ", "medium", "Asia"),
    WikiLanguage("mr", "Marathi", "मराठी", "medium", "Asia"),
    WikiLanguage("gu", "Gujarati", "ગુજરાતી", "small", "Asia"),
    WikiLanguage("pa", "Punjabi", "ਪੰਜਾਬੀ", "small", "Asia"),
    WikiLanguage("as", "Assamese", "অসমীয়া", "small", "Asia"),
    WikiLanguage("or", "Odia", "ଓଡ଼ିଆ", "small", "Asia"),
    WikiLanguage("si", "Sinhala", "සිංහල", "small", "Asia"),
    WikiLanguage("km", "Khmer", "ភាសាខ្មែរ", "small", "Asia"),
    WikiLanguage("lo", "Lao", "ລາວ", "small", "Asia"),
    WikiLanguage("uz", "Uzbek", "Oʻzbekcha", "medium", "Asia"),
    WikiLanguage("ky", "Kyrgyz", "Кыргызча", "small", "Asia"),
    WikiLanguage("tg", "Tajik", "Тоҷикӣ", "small", "Asia"),
    WikiLanguage("tk", "Turkmen", "Türkmençe", "small", "Asia"),
    WikiLanguage("ku", "Kurdish (Kurmanji)", "Kurdî", "small", "Asia"),
    WikiLanguage("ckb", "Central Kurdish (Sorani)", "کوردیی ناوەندی", "small", "Asia"),
    WikiLanguage("ps", "Pashto", "پښتو", "small", "Asia"),
    WikiLanguage("sd", "Sindhi", "سنڌي", "small", "Asia"),
    WikiLanguage("ug", "Uyghur", "ئۇيغۇرچە", "small", "Asia"),
    WikiLanguage("bo", "Tibetan", "བོད་ཡིག", "small", "Asia"),
    WikiLanguage("dv", "Divehi", "ދިވެހި", "small", "Asia"),
    WikiLanguage("ce", "Chechen", "Нохчийн", "small", "Asia"),
    WikiLanguage("sah", "Sakha (Yakut)", "Саха тыла", "small", "Asia"),
    # Africa
    WikiLanguage("mg", "Malagasy", "Malagasy", "medium", "Africa"),
    WikiLanguage("am", "Amharic", "አማርኛ", "small", "Africa"),
    WikiLanguage("ti", "Tigrinya", "ትግርኛ", "small", "Africa"),
    WikiLanguage("so", "Somali", "Soomaaliga", "small", "Africa"),
    WikiLanguage("ha", "Hausa", "Hausa", "small", "Africa"),
    WikiLanguage("yo", "Yoruba", "Yorùbá", "small", "Africa"),
    WikiLanguage("ig", "Igbo", "Igbo", "small", "Africa"),
    WikiLanguage("zu", "Zulu", "isiZulu", "small", "Africa"),
    WikiLanguage("xh", "Xhosa", "isiXhosa", "small", "Africa"),
    WikiLanguage("st", "Sesotho", "Sesotho", "small", "Africa"),
    WikiLanguage("tn", "Tswana", "Setswana", "small", "Africa"),
    WikiLanguage("sn", "Shona", "chiShona", "small", "Africa"),
    WikiLanguage("ny", "Chichewa", "Chichewa", "small", "Africa"),
    WikiLanguage("rw", "Kinyarwanda", "Ikinyarwanda", "small", "Africa"),
    WikiLanguage("ln", "Lingala", "Lingála", "small", "Africa"),
    WikiLanguage("wo", "Wolof", "Wolof", "small", "Africa"),
    # Americas
    WikiLanguage("ht", "Haitian Creole", "Kreyòl ayisyen", "small", "Americas"),
    WikiLanguage("qu", "Quechua", "Runa Simi", "small", "Americas"),
    WikiLanguage("gn", "Guarani", "Avañe'ẽ", "small", "Americas"),
    WikiLanguage("ay", "Aymara", "Aymar aru", "small", "Americas"),
    WikiLanguage("nah", "Nahuatl", "Nāhuatl", "small", "Americas"),
    WikiLanguage("pap", "Papiamento", "Papiamentu", "small", "Americas"),
    # Oceania
    WikiLanguage("mi", "Māori", "Māori", "small", "Oceania"),
    WikiLanguage("haw", "Hawaiian", "ʻŌlelo Hawaiʻi", "small", "Oceania"),
    WikiLanguage("sm", "Samoan", "Gagana Samoa", "small", "Oceania"),
    WikiLanguage("to", "Tongan", "lea faka-Tonga", "small", "Oceania"),
    WikiLanguage("fj", "Fijian", "Na Vosa Vakaviti", "small", "Oceania"),
    WikiLanguage("ty", "Tahitian", "Reo Tahiti", "small", "Oceania"),
    # Constructed / international auxiliary
    WikiLanguage("eo", "Esperanto", "Esperanto", "large", "Constructed"),
    WikiLanguage("vo", "Volapük", "Volapük", "medium", "Constructed"),
    WikiLanguage("ia", "Interlingua", "Interlingua", "small", "Constructed"),
    WikiLanguage("io", "Ido", "Ido", "small", "Constructed"),
)

_BY_CODE = {lang.code: lang for lang in _LANGUAGES}


def all_languages() -> list[WikiLanguage]:
    """Curated editions, largest tier first then alphabetical by English name."""
    return sorted(_LANGUAGES, key=lambda x: (_TIER_RANK.get(x.tier, 9), x.name))


def languages_by_region() -> list[tuple[str, list[WikiLanguage]]]:
    """Editions grouped by continent of origin.

    Regions are ordered largest-edition-first (see ``_REGION_ORDER``); within a
    region the editions keep the usual "largest tier first, then English name"
    ordering. Empty regions are omitted. This lets the UI render short, scannable
    ``<optgroup>`` sections instead of one long flat scroll.
    """
    groups: dict[str, list[WikiLanguage]] = {}
    for lang in _LANGUAGES:
        groups.setdefault(lang.region, []).append(lang)
    ordered: list[tuple[str, list[WikiLanguage]]] = []
    for region in sorted(groups, key=lambda r: _REGION_RANK.get(r, 99)):
        langs = sorted(groups[region], key=lambda x: (_TIER_RANK.get(x.tier, 9), x.name))
        ordered.append((region, langs))
    return ordered


def get_language(code: str) -> WikiLanguage | None:
    return _BY_CODE.get((code or "").strip().lower())


def is_known(code: str) -> bool:
    return (code or "").strip().lower() in _BY_CODE
