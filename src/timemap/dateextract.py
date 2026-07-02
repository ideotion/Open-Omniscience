"""Extract explicit dates *mentioned in article text* (for the temporal map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A story's *publication* date is not the date it is *about*: a 2024 piece may report
on a 1945 event or a 2026 election. This module finds the explicit calendar dates a
text mentions so the temporal map can place coverage at the moment it discusses.

**High precision by design** (the project's ethos — better to miss a date than invent
one). We match only unambiguous forms:

  * ISO ``YYYY-MM-DD``
  * ``11 September 2001`` / ``11 Sept 2001`` / ``the 3rd of June 2026`` (day)
  * ``September 11, 2001`` (day)
  * ``September 2001`` / ``Sept 2001`` / ``January of 2024`` (month)
  * explicit day ranges — ``June 11-13, 2026`` / ``11–13 June 2026`` (both endpoints)
  * era-name years by exact conversion — ``令和6年6月11日`` (Reiwa), ``民國113年`` (ROC)

We deliberately do **not** extract bare years (``in 1945`` — too easily a quantity,
a page number, a model year) or relative expressions (``last Tuesday`` — needs a
reference and guesses), and every result is a *candidate* carrying the matched snippet
as provenance, never a confirmed fact. Pure: no I/O, fully unit-tested.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
# Multilingual month names (field log 2026-06-11: the corpus is half French —
# "le 11 juin 2026" was invisible to an English-only table). Unambiguous tokens:
# every name maps to exactly one month, so all tables stay active at once.
_MONTHS.update({
    # French
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "décembre": 12, "decembre": 12,
    # German
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "juni": 6, "juli": 7, "oktober": 10, "dezember": 12,
    # Spanish
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
    # Italian
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "settembre": 9, "ottobre": 10, "dicembre": 12,
    # Portuguese
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "maio": 5, "junho": 6,
    "julho": 7, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
})
# Additional UI/corpus languages (date-diagnostics 2026-06-17: these had NO month
# vocabulary, so date coverage cratered despite real article volume — sr 6.8 %,
# hu 3.7 %, tr 8.9 %, ro 15.6 %, da 25.8 %, sk/pl/fi/bg ~0 %). SAFE to add: a month
# name only ever yields a date when a day number or a year sits ADJACENT (every
# regex below requires it), so vocabulary raises recall without inventing dates
# from running prose. Inflected forms idiomatic in dates are included (Slavic
# GENITIVE "5 maja", Finnish PARTITIVE "5. toukokuuta"). Every token maps to ONE
# month. Tokens that are common words in a HIGHER-volume language are deliberately
# omitted to preserve precision (e.g. Polish/Slovak genitive "marca" = March, but
# also Spanish/Italian "marca" = brand → omitted; "5 marca" still resolves via the
# nominative marzec/marec or numeric forms).
_MONTHS.update({
    # Romanian
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "iunie": 6,
    "iulie": 7, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
    # Hungarian ("2024. május 5.")
    "január": 1, "február": 2, "március": 3, "április": 4, "május": 5,
    "június": 6, "július": 7, "augusztus": 8, "szeptember": 9, "október": 10,
    # Turkish ("5 Mayıs 2024")
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
    # Nordic (Danish / Swedish / Norwegian Bokmål)
    "marts": 3, "maj": 5, "desember": 12, "januari": 1, "februari": 2,
    "augusti": 8,
    # Finnish — nominative + partitive ("5. toukokuuta 2024")
    "tammikuu": 1, "helmikuu": 2, "maaliskuu": 3, "huhtikuu": 4, "toukokuu": 5,
    "kesäkuu": 6, "heinäkuu": 7, "elokuu": 8, "syyskuu": 9, "lokakuu": 10,
    "marraskuu": 11, "joulukuu": 12,
    "tammikuuta": 1, "helmikuuta": 2, "maaliskuuta": 3, "huhtikuuta": 4,
    "toukokuuta": 5, "kesäkuuta": 6, "heinäkuuta": 7, "elokuuta": 8,
    "syyskuuta": 9, "lokakuuta": 10, "marraskuuta": 11, "joulukuuta": 12,
    # Polish — nominative + genitive ("5 maja 2024"); "marca" omitted (see above).
    # "listopad"/"listopada" MOVED to _MONTH_LANG_OVERRIDES: the same spelling is
    # NOVEMBER in Polish/Czech but OCTOBER in Croatian (a measured live wrong-month
    # bug) — homograph months resolve only via the article-language hint.
    "styczeń": 1, "luty": 2, "marzec": 3, "kwiecień": 4, "czerwiec": 6,
    "lipiec": 7, "sierpień": 8, "wrzesień": 9, "październik": 10,
    "grudzień": 12,
    "stycznia": 1, "lutego": 2, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "października": 10,
    "grudnia": 12,
    # Slovak — nominative + genitive ("5. mája 2024"); "marca" omitted (see above)
    "marec": 3, "apríl": 4, "máj": 5, "jún": 6, "júl": 7,
    "januára": 1, "februára": 2, "apríla": 4, "mája": 5, "júna": 6, "júla": 7,
    "augusta": 8, "septembra": 9, "októbra": 10, "novembra": 11, "decembra": 12,
    # Serbian (Latin)
    "avgust": 8, "septembar": 9, "oktobar": 10, "novembar": 11, "decembar": 12,
    # Serbian (Cyrillic)
    "јануар": 1, "фебруар": 2, "март": 3, "април": 4, "мај": 5, "јун": 6,
    "јул": 7, "август": 8, "септембар": 9, "октобар": 10, "новембар": 11,
    "децембар": 12,
    # Bulgarian (Cyrillic)
    "януари": 1, "февруари": 2, "май": 5, "юни": 6, "юли": 7,
    "септември": 9, "октомври": 10, "ноември": 11, "декември": 12,
    # Arabic — Gregorian transliteration (the internationally common set; the
    # multi-word Levantine names like كانون الثاني are out of scope for now).
    # Eastern-Arabic digits (٠-٩) parse via \d + int() already. "مارس" also means
    # "practised", but a month only fires with an adjacent day/year, so prose is safe.
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5,
    "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10,
    "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
    # Arabic — Levantine single-word month names (Iraq/Syria/Lebanon/Jordan/
    # Palestine standard; pan-Arab media slash-join them with the set above:
    # "سبتمبر/أيلول"). Script-unique + single-meaning, so safe ungated. نيسان
    # (April) and آب (August) are DELIBERATELY WITHHELD — measured fabrication
    # vectors ("سيارة نيسان 2023" is a Nissan model year; آب is fa/ur prose,
    # "water"); they may only ever enter via the language-gated override map
    # under an explicit maintainer ruling.
    "أيلول": 9, "ايلول": 9, "شباط": 2, "آذار": 3, "اذار": 3, "أيار": 5,
    "ايار": 5, "حزيران": 6, "تموز": 7,
    # Hindi (Devanagari) — Gregorian month names; Devanagari digits parse via \d.
    "जनवरी": 1, "फरवरी": 2, "फ़रवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5,
    "जून": 6, "जुलाई": 7, "अगस्त": 8, "सितंबर": 9, "सितम्बर": 9, "अक्टूबर": 10,
    "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
    # Bengali — Gregorian month names; Bengali digits parse via \d.
    "জানুয়ারি": 1, "ফেব্রুয়ারি": 2, "মার্চ": 3, "এপ্রিল": 4, "মে": 5, "জুন": 6,
    "জুলাই": 7, "আগস্ট": 8, "সেপ্টেম্বর": 9, "অক্টোবর": 10, "নভেম্বর": 11, "ডিসেম্বর": 12,
    # Russian (Cyrillic) — nominative + genitive ("5 мая 2024") + prepositional
    # ("в марте 2024"), the three forms a date uses. (март/май/август are already
    # in the table from Serbian Cyrillic, same months.)
    "январь": 1, "января": 1, "январе": 1, "февраль": 2, "февраля": 2,
    "феврале": 2, "марта": 3, "марте": 3, "апрель": 4, "апреля": 4, "апреле": 4,
    "мая": 5, "мае": 5, "июнь": 6, "июня": 6, "июне": 6, "июль": 7, "июля": 7,
    "июле": 7, "августа": 8, "августе": 8, "сентябрь": 9, "сентября": 9,
    "сентябре": 9, "октябрь": 10, "октября": 10, "октябре": 10, "ноябрь": 11,
    "ноября": 11, "ноябре": 11, "декабрь": 12, "декабря": 12, "декабре": 12,
    # Indonesian (the months not already covered by other tables)
    "maret": 3, "mei": 5, "agustus": 8,
    # Dutch (date-diagnostics 2026-06-18: nl coverage 38 % — most months overlapped
    # other tables, but "maart" and "augustus" were absent, so "5 maart"/"3 augustus"
    # never resolved). The rest (januari/februari/april/mei/juni/juli/september/
    # oktober/november/december) are already present via the Nordic/German/Indonesian
    # tables. Same months in Afrikaans.
    "maart": 3, "augustus": 8,
    # Greek (date-diagnostics 2026-06-21: el coverage 8.5 %, in_month_vocab=FALSE —
    # the month names were entirely absent). Nominative + genitive (Greek dates use the
    # genitive: "5 Μαΐου 2024"). Greek script, so no Latin collision; a month only fires
    # next to a day/year, so prose homographs are safe.
    "ιανουάριος": 1, "ιανουαρίου": 1, "φεβρουάριος": 2, "φεβρουαρίου": 2,
    "μάρτιος": 3, "μαρτίου": 3, "απρίλιος": 4, "απριλίου": 4, "μάιος": 5, "μαΐου": 5,
    "ιούνιος": 6, "ιουνίου": 6, "ιούλιος": 7, "ιουλίου": 7, "αύγουστος": 8, "αυγούστου": 8,
    "σεπτέμβριος": 9, "σεπτεμβρίου": 9, "οκτώβριος": 10, "οκτωβρίου": 10,
    "νοέμβριος": 11, "νοεμβρίου": 11, "δεκέμβριος": 12, "δεκεμβρίου": 12,
    # Slovenian (date-diagnostics 2026-06-21: sl coverage 6.2 %, in_month_vocab=FALSE).
    # Genitive forms ("5. junija 2024") + the months not already in the table; the
    # nominatives januar/februar (German) and marec (Slovak) are already present, so
    # only the Slovenian-specific forms are added here. "marca" omitted (collision).
    "januarja": 1, "februarja": 2, "aprila": 4,
    "junij": 6, "junija": 6, "julij": 7, "julija": 7,
    # Ukrainian (Cyrillic) — Slavic month names, DISTINCT from the Latin-derived
    # Russian set already in this table (no overlap). Dates use the genitive
    # ("5 травня 2024 року"), so nominative + genitive are both included; the
    # trailing "року" (=year) is ignored by the regex. (date-diagnostics: uk had
    # NO month vocabulary, so coverage was ~0 despite war-coverage volume.)
    "січень": 1, "січня": 1, "січні": 1, "лютий": 2, "лютого": 2, "лютому": 2,
    "березень": 3, "березня": 3, "березні": 3, "квітень": 4, "квітня": 4, "квітні": 4,
    "травень": 5, "травня": 5, "травні": 5, "червень": 6, "червня": 6, "червні": 6,
    "липень": 7, "липня": 7, "липні": 7, "серпень": 8, "серпня": 8, "серпні": 8,
    "вересень": 9, "вересня": 9, "вересні": 9, "жовтень": 10, "жовтня": 10, "жовтні": 10,
    "листопад": 11, "листопада": 11, "листопаді": 11, "грудень": 12, "грудня": 12, "грудні": 12,
    # Estonian — the names not already covered by other tables (mai/august/september/
    # november are shared). Estonian dates are nominative ("5. mai 2024"); the
    # double-vowel/double-l forms are et-specific so they don't collide.
    "jaanuar": 1, "veebruar": 2, "märts": 3, "aprill": 4, "juuni": 6, "juuli": 7,
    "oktoober": 10, "detsember": 12,
    # Urdu (Arabic script) — Gregorian month names spelled with Urdu letters (ک U+06A9,
    # ی U+06CC), so they are DISTINCT strings from the Arabic-script set above (مارچ≠مارس,
    # اکتوبر[Urdu ک]≠اكتوبر[Arabic ك]). Eastern-Arabic digits parse via \d. A month only
    # fires next to a day/year, so prose homographs stay safe.
    "جنوری": 1, "فروری": 2, "مارچ": 3, "اپریل": 4, "مئی": 5, "جولائی": 7,
    "اگست": 8, "ستمبر": 9, "اکتوبر": 10, "نومبر": 11, "دسمبر": 12,
})
# Cross-language HOMOGRAPH months — the same spelling names DIFFERENT months in
# different languages, so a global single-value entry would INVENT dates (measured
# live: Croatian "5. listopada 2024" = 5 OCTOBER was stored as 5 November via the
# Polish entry). These resolve ONLY through the article-language hint — the
# module's own ambiguous-numeric policy applied to month names: a hint picks the
# meaning, no hint means skipped, never guessed. (Production always passes
# ``article.language``, so pl/cs recall is preserved.)
_MONTH_LANG_OVERRIDES: dict[str, dict[str, int]] = {
    "listopad": {"pl": 11, "cs": 11, "hr": 10},
    "listopada": {"pl": 11, "hr": 10},
    "listopadu": {"cs": 11, "hr": 10},
    "marta": {"sr": 3, "bs": 3},  # Latin-script Serbian genitive; a given name elsewhere
    "mac": {"ms": 3},  # Malay March; English "Mac" tech prose otherwise
}
_MONTH_ALT = "|".join(  # longest first so 'sept' beats 'sep'
    sorted(set(_MONTHS) | set(_MONTH_LANG_OVERRIDES), key=len, reverse=True)
)

# Numeric dates (dd/mm/yyyy · dd.mm.yyyy · dd-mm-yyyy · yyyy/mm/dd). When both
# fields are ≤12 the order is ambiguous: the ARTICLE LANGUAGE decides (en→MDY,
# everything else→DMY); with no hint, an ambiguous numeric date is SKIPPED —
# never guessed (provenance honesty).
_NUM_DMY_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_NUM_YMD_RE = re.compile(r"\b(\d{4})[./](\d{1,2})[./](\d{1,2})\b")

# Connectors seen in real news dates between the date fields ("the 3rd of June
# 2026", "mayo de 2024", el "11 Σεπτεμβρίου του 2001", ar "11 سبتمبر من عام 2001",
# tl "ika-5 ng Hunyo 2026"). LOCKSTEP RULE (the root cause of three measured
# wrong-year fabrications): every alternation added here MUST appear in BOTH the
# full-date patterns AND the no-year negative lookaheads below — an un-mirrored
# connector makes the anchored path re-classify an explicit-year date as
# year-less and resolve it near the PUBLICATION year (el/ar September-11 pieces
# were stored as 2026-09-11).
_Y_CONN = r"(?:de\s+|of\s+|του\s+|من\s+عام\s+|عام\s+|سنة\s+)"  # month -> year
_D_CONN = r"(?:(?:de|of|ng)\s+)"  # day -> month

# Anchored expressions (resolved against the article's PUBLICATION date; each
# carries graded provenance — FUTURE_DEVELOPMENTS design, now implemented).
# The negative lookaheads MIRROR every explicit-year continuation the full-date
# patterns accept (connectors, the dual slash-joined month, day ranges): when an
# explicit year follows in ANY accepted shape, the no-year path must never fire —
# suppress rather than anchor-guess, even for forms we do not extract.
_DM_NOYEAR_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+{_D_CONN}?({_MONTH_ALT})\.?\b"
    rf"(?!\.?(?:\s*/\s*(?:{_MONTH_ALT})\.?)?\s+{_Y_CONN}?\d{{4}})",
    re.I,
)
_MD_NOYEAR_RE = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"(?!\s*(?:[-–—]\s*\d{{1,2}})?(?:st|nd|rd|th)?\s*,?\s*{_Y_CONN}?\d{{4}})",
    re.I,
)
_REL_WORDS = {
    "yesterday": -1, "today": 0, "tomorrow": 1,
    "hier": -1, "aujourd'hui": 0, "aujourd’hui": 0, "demain": 1,
    "gestern": -1, "heute": 0, "morgen": 1,
    "ayer": -1, "hoy": 0, "mañana": 1,
    "ontem": -1, "hoje": 0, "amanhã": 1,
    "ieri": -1, "oggi": 0, "domani": 1,
}
_REL_RE = re.compile(r"\b(" + "|".join(sorted(_REL_WORDS, key=len, reverse=True)) + r")\b", re.I)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4,
    "samedi": 5, "dimanche": 6,
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,
    "samstag": 5, "sonntag": 6,
}
_WD_RE = re.compile(
    r"\b(next\s+|last\s+)?(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b", re.I
)

_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# Full day-month-year, with the optional connectors above and an optional
# DUAL-NAMED month ("سبتمبر/أيلول" — pan-Arab media slash-join the international
# and Levantine names). The two names must resolve to the SAME month or the whole
# match is skipped (never a guess); the no-year lookahead mirrors the slash form.
_DMY_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+{_D_CONN}?({_MONTH_ALT})\.?"
    rf"(?:\s*/\s*({_MONTH_ALT})\.?)?\s+{_Y_CONN}?(\d{{4}})\b",
    re.I,
)
_MDY_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
# Explicit date RANGES — both endpoints are IN the text, so both are extracted
# and the span is claimed, which stops the anchored no-year path from grabbing
# the first endpoint and resolving it near the publication year (measured:
# "June 11-13, 2026" with a 2027 anchor stored 2027-06-11, overriding the
# explicit in-text year). d1 < d2 is required (range semantics); otherwise the
# match is skipped and nothing is invented.
_RANGE_MDY_RE = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*[-–—]\s*"
    rf"(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
    re.I,
)
_RANGE_DMY_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s*[-–—]\s*(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+"
    rf"{_D_CONN}?({_MONTH_ALT})\.?\s+{_Y_CONN}?(\d{{4}})\b",
    re.I,
)
_RANGE_ENUM_RE = re.compile(  # "between 11 and 13 June 2026" (en connector for now)
    rf"\b(\d{{1,2}})\s+and\s+(\d{{1,2}})\s+{_D_CONN}?({_MONTH_ALT})\.?\s+{_Y_CONN}?(\d{{4}})\b",
    re.I,
)
# Year-first with a NAMED month ("2024. május 5." Hungarian / "2024 m. gegužės"
# patterns): unambiguous (full year + month name + day all present), so it is a
# day match like ISO. Covers locales that write Y M D in prose with words.
_YMD_NAME_RE = re.compile(rf"\b(\d{{4}})\.?\s+({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)
# Month-year with the optional connector CAPTURED: the English homograph months
# (march/may/august are verbs/nouns too) skip the "of" form — "the march of 2024
# protesters" must never become March 2024 (miss over invent).
_MY_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+({_Y_CONN}?)(\d{{4}})\b", re.I)
_MY_OF_HOMOGRAPHS = frozenset({"march", "may", "august"})

# CJK calendar dates (Chinese / Japanese): the 年 (year) 月 (month) 日 (day)
# ideographs are unambiguous date markers, so these never collide with prose or
# any Latin/Cyrillic vocabulary — no word boundary needed. Half-width and
# full-width digits (０-９, common in formal CJK text) are both accepted and
# normalised to ASCII before parsing.
_CJK_D = r"[0-9０-９]"
_FW_DIGITS = {ord("０") + i: ord("0") + i for i in range(10)}
_CJK_YMD_RE = re.compile(rf"({_CJK_D}{{4}})\s*年\s*({_CJK_D}{{1,2}})\s*月\s*({_CJK_D}{{1,2}})\s*日")
_CJK_YM_RE = re.compile(rf"({_CJK_D}{{4}})\s*年\s*({_CJK_D}{{1,2}})\s*月")
_CJK_MD_RE = re.compile(rf"({_CJK_D}{{1,2}})\s*月\s*({_CJK_D}{{1,2}})\s*日")  # no year -> anchored

# Era-name years — Japanese gengō (令和6年 = 2024) and Taiwanese ROC (民國113年 =
# 2024). Each era name is a multi-ideograph token appearing in no other language's
# prose, and the conversion is exact calendar arithmetic (the same honesty class as
# the shipped Thai Buddhist-Era -> CE conversion below) — a conversion, never an
# inference. 元年 = year 1. Before this, the anchored no-year path resolved the
# 月日 tail of era dates near the PUBLICATION year (measured: 昭和20年8月15日 —
# 15 August 1945 — was stored as 2026-08-15, an 81-year fabrication).
_ERA_BASES = {
    "令和": 2018,  # Reiwa: 令和1 = 2019
    "平成": 1988,  # Heisei: 平成1 = 1989
    "昭和": 1925,  # Shōwa: 昭和1 = 1926
    "大正": 1911,  # Taishō: 大正1 = 1912
    "明治": 1867,  # Meiji: 明治1 = 1868
    "民國": 1911,  # ROC: 民國1 = 1912
    "民国": 1911,  # ROC, simplified form
}
_ERA_ALT = "|".join(_ERA_BASES)
_ERA_YMD_RE = re.compile(
    rf"({_ERA_ALT})\s*({_CJK_D}{{1,3}}|元)\s*年\s*({_CJK_D}{{1,2}})\s*月(?:\s*({_CJK_D}{{1,2}})\s*日)?"
)


def _cjk_int(s: str) -> int:
    """Parse a CJK date number tolerant of full-width digits (２０２４ -> 2024)."""
    return int(s.translate(_FW_DIGITS))


# Vietnamese: the month is written as a NUMBER after "tháng" ("ngày 5 tháng 5 năm
# 2024"), so the name table can't help — these read the number directly. (Plain
# numeric "5/5/2024" already resolves via _NUM_DMY_RE with language=vi -> DMY.) The
# full-date pattern runs FIRST (its day match claims the span before the month-only
# pattern can). Vietnamese is syllable-segmented (so its KEYWORDS stay unmanaged),
# but these explicit date markers are unambiguous regardless.
_VI_DMY_RE = re.compile(r"\bngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})\b", re.I)
_VI_DM_NOYEAR_RE = re.compile(r"\bngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\b(?!\s+năm)", re.I)
_VI_MY_RE = re.compile(r"\btháng\s+(\d{1,2})\s*(?:năm\s+|/)(\d{4})\b", re.I)

# Thai: month NAMES in Thai script; the year is usually the Buddhist Era (BE = CE +
# 543), often introduced by "พ.ศ.". Thai has no inter-word spaces, so whitespace is
# optional around the parts; the specific multi-char Thai month string + an adjacent
# 4-digit year keeps it precise. A BE year (>= _BE_FLOOR) is converted to CE; a year
# already in the plausible CE window is kept as-is (some Thai sites use CE). Thai
# digits (๐-๙) parse via \d. (Thai KEYWORDS are unsegmented; these date markers are
# still extractable.)
_TH_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}
_TH_ALT = "|".join(_TH_MONTHS)
_TH_PE = r"(?:พ\.?\s*ศ\.?\s*)?"  # optional "พ.ศ." (B.E.) marker
_TH_DMY_RE = re.compile(rf"(\d{{1,2}})\s*({_TH_ALT})\s*{_TH_PE}(\d{{4}})")
_TH_MY_RE = re.compile(rf"({_TH_ALT})\s*{_TH_PE}(\d{{4}})")
_BE_FLOOR = 2200  # CE 2200 is far beyond the window, so any year >= this is Buddhist Era


def _be_to_ce(year: int) -> int:
    """A Buddhist-Era year (>= _BE_FLOOR) -> CE; a year already in CE is unchanged."""
    return year - 543 if year >= _BE_FLOOR else year


# Plausible window for a *mentioned* date: deep history up to a little ahead of "now".
_MIN_YEAR, _MAX_AHEAD = 1000, 5


def _valid(year: int, month: int, day: int, today: date) -> date | None:
    if not (_MIN_YEAR <= year <= today.year + _MAX_AHEAD):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_of(token: str, language: str | None = None) -> int | None:
    """Month number for a matched month name, tolerant of case-fold quirks. A
    regex hit case-insensitively matches the table, but ``str.lower()`` does not
    always round-trip to the stored key (Turkish DOTLESS ı: ``"MAYIS".lower()``
    is ``"mayis"`` ≠ the table's ``"mayıs"``). Returns None on a miss so the hit
    is skipped, never a ``KeyError`` that would abort extraction for the article.

    A cross-language HOMOGRAPH month (``_MONTH_LANG_OVERRIDES``) resolves ONLY
    via the article-language hint — no hint, or a language outside the token's
    map, returns None: skipped, never guessed (the ambiguous-numeric policy)."""
    tok = token.lower()
    if tok in _MONTH_LANG_OVERRIDES:
        return _MONTH_LANG_OVERRIDES[tok].get((language or "")[:2].lower())
    return _MONTHS.get(tok)


def _snippet(text: str, start: int, end: int, pad: int = 24) -> str:
    s = text[max(0, start - pad) : min(len(text), end + pad)].strip()
    return re.sub(r"\s+", " ", s)


def extract_dates(
    text: str,
    *,
    today: date | None = None,
    limit: int = 8,
    anchor: date | None = None,
    language: str | None = None,
) -> list[dict]:
    """Calendar dates mentioned in ``text``, as candidates with provenance.

    Returns up to ``limit`` de-duplicated ``{date, precision, text}`` dicts, ordered by
    first appearance. ``precision`` is ``"day"`` or ``"month"``. Overlapping matches are
    resolved most-specific-first (a day match suppresses the month match inside it).

    ``anchor`` (the article's publication date) unlocks ANCHORED resolution —
    day+month without a year, yesterday/today/tomorrow words, bare weekdays —
    each marked with how it was resolved. ``language`` decides the order of
    ambiguous numeric dates (en→MDY, others→DMY; no hint + ambiguous → skipped,
    never guessed). Optimized 2026-06-11 (maintainer: far too few dates).
    """
    if not text:
        return []
    today = today or date.today()
    consumed: list[tuple[int, int]] = []  # spans claimed by more specific matches
    found: dict[tuple[str, str], dict] = {}

    def claim(start: int, end: int) -> bool:
        for cs, ce in consumed:
            if start < ce and cs < end:  # overlaps an already-claimed span
                return False
        consumed.append((start, end))
        return True

    def add(d: date, precision: str, m: re.Match) -> None:
        key = (d.isoformat(), precision)
        if key not in found:
            found[key] = {
                "date": d.isoformat(),
                "precision": precision,
                "text": _snippet(text, m.start(), m.end()),
                "pos": m.start(),
            }

    for m in _ISO_RE.finditer(text):
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _ERA_YMD_RE.finditer(text):  # 令和6年6月11日 / 民國113年6月11日 — exact conversion
        n = m.group(2)
        year = _ERA_BASES[m.group(1)] + (1 if n == "元" else _cjk_int(n))
        if m.group(4):  # day present
            d = _valid(year, _cjk_int(m.group(3)), _cjk_int(m.group(4)), today)
            if d and claim(*m.span()):
                add(d, "day", m)
        else:  # era year + month only
            d = _valid(year, _cjk_int(m.group(3)), 1, today)
            if d and claim(*m.span()):
                add(d, "month", m)
    # Explicit ranges claim BEFORE the single-date patterns: both endpoints are in
    # the text (nothing inferred), and the claimed span stops the anchored no-year
    # path from resolving an endpoint near the publication year.
    for m in _RANGE_MDY_RE.finditer(text):
        mon = _month_of(m.group(1), language)
        d1n, d2n = int(m.group(2)), int(m.group(3))
        if mon and d1n < d2n:
            d1 = _valid(int(m.group(4)), mon, d1n, today)
            d2 = _valid(int(m.group(4)), mon, d2n, today)
            if d1 and d2 and claim(*m.span()):
                add(d1, "day", m)
                add(d2, "day", m)
    for m in _RANGE_DMY_RE.finditer(text):
        mon = _month_of(m.group(3), language)
        d1n, d2n = int(m.group(1)), int(m.group(2))
        if mon and d1n < d2n:
            d1 = _valid(int(m.group(4)), mon, d1n, today)
            d2 = _valid(int(m.group(4)), mon, d2n, today)
            if d1 and d2 and claim(*m.span()):
                add(d1, "day", m)
                add(d2, "day", m)
    for m in _RANGE_ENUM_RE.finditer(text):  # "between 11 and 13 June 2026"
        mon = _month_of(m.group(3), language)
        d1n, d2n = int(m.group(1)), int(m.group(2))
        if mon and d1n < d2n:
            d1 = _valid(int(m.group(4)), mon, d1n, today)
            d2 = _valid(int(m.group(4)), mon, d2n, today)
            if d1 and d2 and claim(*m.span()):
                add(d1, "day", m)
                add(d2, "day", m)
    for m in _DMY_RE.finditer(text):
        mon = _month_of(m.group(2), language)
        if mon is None:
            continue
        if m.group(3):  # dual-named "سبتمبر/أيلول": both must agree, else skip — never a guess
            alt = _month_of(m.group(3), language)
            if alt != mon:
                continue
        d = _valid(int(m.group(4)), mon, int(m.group(1)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _MDY_RE.finditer(text):
        mon = _month_of(m.group(1), language)
        d = _valid(int(m.group(3)), mon, int(m.group(2)), today) if mon else None
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _YMD_NAME_RE.finditer(text):  # "2024. május 5." (year-first, named month)
        mon = _month_of(m.group(2), language)
        d = _valid(int(m.group(1)), mon, int(m.group(3)), today) if mon else None
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _CJK_YMD_RE.finditer(text):  # 2024年5月11日 (CJK day)
        d = _valid(_cjk_int(m.group(1)), _cjk_int(m.group(2)), _cjk_int(m.group(3)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _VI_DMY_RE.finditer(text):  # ngày 5 tháng 5 năm 2024 (Vietnamese day)
        d = _valid(int(m.group(3)), int(m.group(2)), int(m.group(1)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _TH_DMY_RE.finditer(text):  # 5 มกราคม 2567 (Thai day; BE -> CE)
        mon = _TH_MONTHS.get(m.group(2))
        d = _valid(_be_to_ce(int(m.group(3))), mon, int(m.group(1)), today) if mon else None
        if d and claim(*m.span()):
            add(d, "day", m)
    # Numeric dates — language picks the order when ambiguous; never guessed.
    mdy_first = (language or "").lower().startswith("en")
    for m in _NUM_YMD_RE.finditer(text):
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _NUM_DMY_RE.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            d = _valid(y, b, a, today)
        elif b > 12 and a <= 12:
            d = _valid(y, a, b, today)
        elif a <= 12 and b <= 12 and language:
            d = _valid(y, a, b, today) if mdy_first else _valid(y, b, a, today)
        else:
            continue  # ambiguous with no language hint: skipped, not guessed
        if d and claim(*m.span()):
            add(d, "day", m)

    for m in _MY_RE.finditer(text):  # month precision — only where no day match claimed it
        mon = _month_of(m.group(1), language)
        if mon is None:
            continue
        # "the march of 2024 protesters": the en homograph months never take the
        # "of" connector form — miss over invent.
        conn = (m.group(2) or "").strip().lower()
        if conn == "of" and m.group(1).lower() in _MY_OF_HOMOGRAPHS:
            continue
        d = _valid(int(m.group(3)), mon, 1, today)
        if d and claim(*m.span()):
            add(d, "month", m)
    for m in _CJK_YM_RE.finditer(text):  # 2024年5月 (CJK month precision; day match claims first)
        d = _valid(_cjk_int(m.group(1)), _cjk_int(m.group(2)), 1, today)
        if d and claim(*m.span()):
            add(d, "month", m)
    for m in _VI_MY_RE.finditer(text):  # tháng 5 năm 2024 / tháng 5/2024 (month precision)
        d = _valid(int(m.group(2)), int(m.group(1)), 1, today)
        if d and claim(*m.span()):
            add(d, "month", m)
    for m in _TH_MY_RE.finditer(text):  # มกราคม 2567 (Thai month precision; BE -> CE)
        mon = _TH_MONTHS.get(m.group(1))
        d = _valid(_be_to_ce(int(m.group(2))), mon, 1, today) if mon else None
        if d and claim(*m.span()):
            add(d, "month", m)

    # ---- anchored resolution (needs the article's publication date) -------- #
    if anchor is not None:
        def nearest_year(month: int, day: int) -> date | None:
            best = None
            for y in (anchor.year - 1, anchor.year, anchor.year + 1):
                try:
                    cand = date(y, month, day)
                except ValueError:
                    continue
                if best is None or abs((cand - anchor).days) < abs((best - anchor).days):
                    best = cand
            return best if best and abs((best - anchor).days) <= 183 else None

        for rx, gi_d, gi_m in ((_DM_NOYEAR_RE, 1, 2), (_MD_NOYEAR_RE, 2, 1)):
            for m in rx.finditer(text):
                mon = _month_of(m.group(gi_m), language)
                if not mon:
                    continue
                d = nearest_year(mon, int(m.group(gi_d)))
                if d and claim(*m.span()):
                    add(d, "day", m)
        for m in _CJK_MD_RE.finditer(text):  # 5月11日 with no year -> nearest to the anchor
            # Era/short-year guard: if the character just before the match (past
            # whitespace) is 年/년, an explicit year we could NOT parse precedes
            # (an unknown era name, or a bare 2-digit year like 24年) — suppress
            # rather than anchor-resolve to the publication year (measured: era
            # dates were stored ~80 years wrong before the _ERA_YMD_RE support).
            before = text[: m.start()].rstrip()
            if before[-1:] in ("年", "년"):
                continue
            d = nearest_year(_cjk_int(m.group(1)), _cjk_int(m.group(2)))
            if d and claim(*m.span()):
                add(d, "day", m)
        for m in _VI_DM_NOYEAR_RE.finditer(text):  # ngày 5 tháng 5 (no year) -> nearest
            d = nearest_year(int(m.group(2)), int(m.group(1)))
            if d and claim(*m.span()):
                add(d, "day", m)
        for m in _REL_RE.finditer(text):
            off = _REL_WORDS.get(m.group(1).lower())
            if off is None:  # casefold round-trip miss (dotless-ı class): skip, never abort
                continue
            if claim(*m.span()):
                add(anchor + timedelta(days=off), "day", m)
        for m in _WD_RE.finditer(text):
            wd = _WEEKDAYS.get(m.group(2).lower())
            if wd is None:  # casefold round-trip miss (dotless-ı class): skip, never abort
                continue
            mod = (m.group(1) or "").strip().lower()
            delta = (wd - anchor.weekday()) % 7
            if mod == "next":
                d = anchor + timedelta(days=delta or 7)
            elif mod == "last":
                d = anchor - timedelta(days=((anchor.weekday() - wd) % 7) or 7)
            else:  # bare weekday in news prose: the most recent such day
                d = anchor - timedelta(days=(anchor.weekday() - wd) % 7)
            if claim(*m.span()):
                add(d, "day", m)

    out = sorted(found.values(), key=lambda c: c["pos"])
    for c in out:
        c.pop("pos", None)
    return out[:limit]
