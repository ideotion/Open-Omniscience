"""
Catalogue of Wikipedia language editions (for the offline-baseline picker).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A curated, neutral list of the larger Wikipedia language editions: the wiki code
(used to build dump URLs, e.g. ``en`` -> ``enwiki``), the English name and the
language's own name (autonym), plus a coarse *size tier* so the UI can sort
"largest first" without hardcoding article counts that go stale. Real download
sizes are always read from the dump server at probe time — these tiers are only
for ordering and a rough "how heavy is this" hint, never presented as a fact
about the current dump.

This is data, not behaviour: the dump downloader (src.wiki.dumps) accepts ANY
edition code, so an operator can still type one not listed here.
"""

from __future__ import annotations

from dataclasses import dataclass

# Coarse size tiers (largest editions first within each). "huge" ~ multi-million
# articles, "large" ~ 1M+, "medium" ~ 100k+, "small" the rest. Ordering hint only.
_TIER_RANK = {"huge": 0, "large": 1, "medium": 2, "small": 3}


@dataclass(frozen=True)
class WikiLanguage:
    code: str       # wiki edition code (en, fr, de, ...) -> {code}wiki
    name: str       # English name
    autonym: str    # the language's own name
    tier: str       # huge | large | medium | small (ordering/heaviness hint)

    def to_dict(self) -> dict:
        return {"code": self.code, "name": self.name, "autonym": self.autonym, "tier": self.tier}


# Curated list — the editions most relevant to cross-language investigative work.
# Not exhaustive (there are 300+ editions); the picker also allows a free-text code.
_LANGUAGES: tuple[WikiLanguage, ...] = (
    WikiLanguage("en", "English", "English", "huge"),
    WikiLanguage("de", "German", "Deutsch", "huge"),
    WikiLanguage("fr", "French", "Français", "huge"),
    WikiLanguage("es", "Spanish", "Español", "huge"),
    WikiLanguage("ru", "Russian", "Русский", "huge"),
    WikiLanguage("ja", "Japanese", "日本語", "huge"),
    WikiLanguage("zh", "Chinese", "中文", "huge"),
    WikiLanguage("it", "Italian", "Italiano", "huge"),
    WikiLanguage("pt", "Portuguese", "Português", "large"),
    WikiLanguage("ar", "Arabic", "العربية", "large"),
    WikiLanguage("fa", "Persian", "فارسی", "large"),
    WikiLanguage("pl", "Polish", "Polski", "large"),
    WikiLanguage("nl", "Dutch", "Nederlands", "large"),
    WikiLanguage("uk", "Ukrainian", "Українська", "large"),
    WikiLanguage("tr", "Turkish", "Türkçe", "large"),
    WikiLanguage("id", "Indonesian", "Bahasa Indonesia", "large"),
    WikiLanguage("he", "Hebrew", "עברית", "large"),
    WikiLanguage("ko", "Korean", "한국어", "large"),
    WikiLanguage("vi", "Vietnamese", "Tiếng Việt", "large"),
    WikiLanguage("sv", "Swedish", "Svenska", "large"),
    WikiLanguage("cs", "Czech", "Čeština", "medium"),
    WikiLanguage("hu", "Hungarian", "Magyar", "medium"),
    WikiLanguage("ro", "Romanian", "Română", "medium"),
    WikiLanguage("fi", "Finnish", "Suomi", "medium"),
    WikiLanguage("el", "Greek", "Ελληνικά", "medium"),
    WikiLanguage("no", "Norwegian (Bokmål)", "Norsk bokmål", "medium"),
    WikiLanguage("da", "Danish", "Dansk", "medium"),
    WikiLanguage("th", "Thai", "ไทย", "medium"),
    WikiLanguage("bg", "Bulgarian", "Български", "medium"),
    WikiLanguage("sr", "Serbian", "Српски", "medium"),
    WikiLanguage("hi", "Hindi", "हिन्दी", "medium"),
    WikiLanguage("ca", "Catalan", "Català", "medium"),
    WikiLanguage("hr", "Croatian", "Hrvatski", "medium"),
    WikiLanguage("sk", "Slovak", "Slovenčina", "medium"),
    WikiLanguage("lt", "Lithuanian", "Lietuvių", "medium"),
    WikiLanguage("sl", "Slovenian", "Slovenščina", "medium"),
    WikiLanguage("et", "Estonian", "Eesti", "medium"),
    WikiLanguage("lv", "Latvian", "Latviešu", "medium"),
    WikiLanguage("ms", "Malay", "Bahasa Melayu", "medium"),
    WikiLanguage("az", "Azerbaijani", "Azərbaycanca", "medium"),
    WikiLanguage("bn", "Bengali", "বাংলা", "medium"),
    WikiLanguage("ka", "Georgian", "ქართული", "medium"),
    WikiLanguage("hy", "Armenian", "Հայերեն", "medium"),
    WikiLanguage("ur", "Urdu", "اردو", "medium"),
    WikiLanguage("ta", "Tamil", "தமிழ்", "medium"),
    WikiLanguage("be", "Belarusian", "Беларуская", "medium"),
    WikiLanguage("kk", "Kazakh", "Қазақша", "medium"),
    WikiLanguage("eu", "Basque", "Euskara", "medium"),
    WikiLanguage("gl", "Galician", "Galego", "medium"),
    WikiLanguage("af", "Afrikaans", "Afrikaans", "small"),
    WikiLanguage("sw", "Swahili", "Kiswahili", "small"),
    WikiLanguage("is", "Icelandic", "Íslenska", "small"),
    WikiLanguage("ga", "Irish", "Gaeilge", "small"),
    WikiLanguage("cy", "Welsh", "Cymraeg", "small"),
    WikiLanguage("mk", "Macedonian", "Македонски", "small"),
    WikiLanguage("sq", "Albanian", "Shqip", "small"),
    WikiLanguage("mn", "Mongolian", "Монгол", "small"),
    WikiLanguage("ne", "Nepali", "नेपाली", "small"),
    WikiLanguage("my", "Burmese", "မြန်မာဘာသာ", "small"),
)

_BY_CODE = {lang.code: lang for lang in _LANGUAGES}


def all_languages() -> list[WikiLanguage]:
    """Curated editions, largest tier first then alphabetical by English name."""
    return sorted(_LANGUAGES, key=lambda x: (_TIER_RANK.get(x.tier, 9), x.name))


def get_language(code: str) -> WikiLanguage | None:
    return _BY_CODE.get((code or "").strip().lower())


def is_known(code: str) -> bool:
    return (code or "").strip().lower() in _BY_CODE
