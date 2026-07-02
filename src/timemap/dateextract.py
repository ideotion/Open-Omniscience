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
  * era-name years by exact conversion — ``令和6年6月11日`` (Reiwa), ``民國113年6月11日``
    (ROC); a bare era year with no month stays unextracted, like any bare year

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
    # "سبتمبر/أيلول"). These six were probed against fa/ur prose and verified
    # single-meaning (the Persian-yeh spellings ایلول/ایار are different
    # codepoints and never match), so they are safe ungated. THREE are NOT here:
    # نيسان (April) and آب (August) are WITHHELD outright — measured fabrication
    # vectors ("سيارة نيسان 2023" is a Nissan model year; آب is fa/ur prose,
    # "water") — and تموز (July) is a REAL Persian word ("midsummer heat",
    # گرمای تموز), so it lives in the language-gated override map below.
    "أيلول": 9, "ايلول": 9, "شباط": 2, "آذار": 3, "اذار": 3, "أيار": 5,
    "ايار": 5, "حزيران": 6,
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
    # Greek — ACCUSATIVE forms ("τον Σεπτέμβριο του 2001", the idiomatic
    # month-year construction) + ACCENTLESS variants: Greek ALL-CAPS drops the
    # tonos, so "ΣΕΠΤΕΜΒΡΙΟΣ".lower() ("σεπτεμβριος") misses the accented keys —
    # the same casefold class as the Turkish dotless-ı. Final-ς spelling matches
    # what str.lower() emits (verified).
    "ιανουάριο": 1, "φεβρουάριο": 2, "μάρτιο": 3, "απρίλιο": 4, "μάιο": 5,
    "ιούνιο": 6, "ιούλιο": 7, "αύγουστο": 8, "σεπτέμβριο": 9, "οκτώβριο": 10,
    "νοέμβριο": 11, "δεκέμβριο": 12,
    "ιανουαριος": 1, "ιανουαριου": 1, "ιανουαριο": 1,
    "φεβρουαριος": 2, "φεβρουαριου": 2, "φεβρουαριο": 2,
    "μαρτιος": 3, "μαρτιου": 3, "μαρτιο": 3,
    "απριλιος": 4, "απριλιου": 4, "απριλιο": 4,
    "μαιος": 5, "μαιου": 5, "μαιο": 5,
    "ιουνιος": 6, "ιουνιου": 6, "ιουνιο": 6,
    "ιουλιος": 7, "ιουλιου": 7, "ιουλιο": 7,
    "αυγουστος": 8, "αυγουστου": 8, "αυγουστο": 8,
    "σεπτεμβριος": 9, "σεπτεμβριου": 9, "σεπτεμβριο": 9,
    "οκτωβριος": 10, "οκτωβριου": 10, "οκτωβριο": 10,
    "νοεμβριος": 11, "νοεμβριου": 11, "νοεμβριο": 11,
    "δεκεμβριος": 12, "δεκεμβριου": 12, "δεκεμβριο": 12,
    # Croatian — genitive (the date form: "5. rujna 2024.") + nominative. The
    # listopad AND kolovoz families are in the override map (homographs:
    # pl/cs November vs hr October; hr "roadway"); "studeni" (Nov) doubles as
    # the adjective "cold", covered by the adjacency rule like مارس.
    "siječnja": 1, "veljače": 2, "ožujka": 3, "travnja": 4, "svibnja": 5,
    "lipnja": 6, "srpnja": 7, "rujna": 9, "studenoga": 11,
    "studenog": 11, "prosinca": 12,
    "siječanj": 1, "veljača": 2, "ožujak": 3, "travanj": 4, "svibanj": 5,
    "lipanj": 6, "srpanj": 7, "rujan": 9, "studeni": 11,
    "prosinac": 12,
    # Czech — genitive ("5. září 2024") + nominative. "listopadu" is in the
    # override map; "dubna" (April genitive) too — Dubna is a Russian town that
    # appears with years in physics prose ("the Dubna 2024 workshop").
    "ledna": 1, "února": 2, "března": 3, "května": 5, "června": 6,
    "července": 7, "srpna": 8, "září": 9, "října": 10, "prosince": 12,
    "leden": 1, "únor": 2, "březen": 3, "květen": 5, "červen": 6,
    "červenec": 7, "srpen": 8, "říjen": 10, "prosinec": 12,
    # Serbian (Latin) — unaccented genitives, the common written form. "marta"
    # (given name), "juna"/"jula" (given name / Norwegian "the Christmas") are
    # in the override map; septembra/novembra/decembra/maja/aprila already
    # resolve via the Slovak/Polish/Slovenian entries above.
    "januara": 1, "februara": 2, "avgusta": 8, "oktobra": 10,
    # Malay ("5 Ogos 2024"); "mac" (March) is in the override map (English Mac);
    # januari/februari/april/mei/jun/julai/september/oktober/november already
    # resolve via the Indonesian/Nordic/shared entries.
    "ogos": 8, "julai": 7, "disember": 12,
    # Filipino/Tagalog ("ika-5 ng Hunyo 2024"); Enero/Abril/Mayo/Agosto shared
    # with Spanish already resolve.
    "pebrero": 2, "hunyo": 6, "hulyo": 7, "setyembre": 9,
    "oktubre": 10, "nobyembre": 11, "disyembre": 12,
    # Swahili ("5 Machi 2024"); Januari/Februari/Mei/Juni/Julai shared entries
    # already resolve. "Agosti"/"Machi" (surname/name in Latin citations) are
    # sw-gated via the override map.
    "aprili": 4, "septemba": 9, "oktoba": 10,
    "novemba": 11, "desemba": 12,
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
    # Slavic "leaf-fall" month: November in Polish/Czech/(archaic) Slovenian,
    # October in Croatian/Bosnian.
    "listopad": {"pl": 11, "cs": 11, "sl": 11, "hr": 10, "bs": 10},
    "listopada": {"pl": 11, "sl": 11, "hr": 10, "bs": 10},
    "listopadu": {"cs": 11, "hr": 10, "bs": 10},
    "marta": {"sr": 3, "bs": 3},  # Latin-script Serbian genitive; a given name elsewhere
    "mac": {"ms": 3},  # Malay March; English "Mac" tech prose otherwise
    "dubna": {"cs": 4},  # Czech April genitive; Dubna, Russia in physics prose
    "duben": {"cs": 4},  # Czech April nominative; Duben is a German village/surname
    # hr August genitive/nominative — but kolovoz = "roadway" in Croatian ITSELF
    # ("sletio s kolovoza 20 metara" is standard traffic-accident prose, measured
    # fabricating Aug 20): gating kills the month-first shape outright and the
    # no-hint case; the residual "s kolovoza 2024." month reading under an hr
    # hint is a real, bounded ambiguity accepted as month-precision only.
    "kolovoza": {"hr": 8},
    "kolovoz": {"hr": 8},
    # sw/tl months that are surnames/names in Latin prose ("(Agosti 2024)" is an
    # author-year citation — an extremely common scraped shape; "Marso 11" a name):
    "agosti": {"sw": 8},
    "machi": {"sw": 3},
    "marso": {"tl": 3},
    # sr/bs Latin genitives that are words/names elsewhere: "juna" is a given
    # name (the "Marta 30" shape), "jula" is Norwegian "the Christmas" ("i jula
    # 2024" is real nb prose — ungated it would fabricate July from Christmas).
    "juna": {"sr": 6, "bs": 6},
    "jula": {"sr": 7, "bs": 7},
    # تموز = July in Levantine Arabic, but a REAL Persian word ("midsummer
    # heat" — گرمای تموز): ungated it fabricated month rows from fa prose,
    # including Solar-Hijri years (1403 passes the CE window). ar-gated only.
    "تموز": {"ar": 7},
}
_MONTH_ALT = "|".join(  # longest first so 'sept' beats 'sep'
    sorted(set(_MONTHS) | set(_MONTH_LANG_OVERRIDES), key=len, reverse=True)
)

# Numeric dates (dd/mm/yyyy · dd.mm.yyyy · dd-mm-yyyy · yyyy/mm/dd). When both
# fields are ≤12 the order is ambiguous: the ARTICLE LANGUAGE decides (en→MDY,
# everything else→DMY); with no hint, an ambiguous numeric date is SKIPPED —
# never guessed (provenance honesty).
# Custom boundaries instead of \b: ideographs/Hangul are \w in Python re, so
# \b never fires between 于 and 2024 — a glued "报道于2024-06-11发布" was
# invisible (measured). The rule, verified adversarially: ANY digit (any script,
# \d — the same digit rule \b enforced, so ٥٠2024 stays ONE numeral and no date
# is ever carved out of a longer number) and ASCII letters/_ still BLOCK; any
# LETTER — ideograph, Hangul, or a glued Cyrillic "…2024г."/accented Latin — is
# now a boundary (measured recall gain; the extracted string is always a full
# explicit date).
_NUM_BOUND_L = r"(?<!\d)(?<![A-Za-z_])"
_NUM_BOUND_R = r"(?!\d)(?![A-Za-z_])"
_NUM_DMY_RE = re.compile(rf"{_NUM_BOUND_L}(\d{{1,2}})[./-](\d{{1,2}})[./-](\d{{4}}){_NUM_BOUND_R}")
_NUM_YMD_RE = re.compile(rf"{_NUM_BOUND_L}(\d{{4}})[./](\d{{1,2}})[./](\d{{1,2}}){_NUM_BOUND_R}")

# Connectors seen in real news dates between the date fields ("the 3rd of June
# 2026", "mayo de 2024", el "11 Σεπτεμβρίου του 2001", ar "11 سبتمبر من عام 2001",
# tl "ika-5 ng Hunyo 2026"). LOCKSTEP RULE (the root cause of three measured
# wrong-year fabrications): every alternation added here MUST appear in BOTH the
# full-date patterns AND the no-year negative lookaheads below — an un-mirrored
# connector makes the anchored path re-classify an explicit-year date as
# year-less and resolve it near the PUBLICATION year (el/ar September-11 pieces
# were stored as 2026-09-11).
_Y_CONN = r"(?:de\s+|of\s+|του\s+|من\s+عام\s+|عام\s+|سنة\s+)"  # month -> year
# Day -> month. The English "of" REQUIRES the ordinal day suffix ("the 3rd of
# June 2026"): a BARE cardinal + "of" + month is a counter reference in English
# ("Page 3 of May 2024", "Chapter 11 of September 2001") — accepting it invented
# day components (adversarial-verifier finding). "de" (the standard es/pt
# bare-cardinal date form, long shipped) and "ng" (the tl parallel) stay as-is.
# Two branches -> two possible day groups; callers take whichever matched.
# The standard-branch day suffix accepts the Cyrillic ordinal attachments
# ("11-го сентября" genitive / "11-е" nominative — day precision was silently
# LOST to the month match before) and the Bengali date clitics ("১১ই সেপ্টেম্বর",
# "২৫শে ডিসেম্বর", "১লা জানুয়ারি"). Each is glued to the digit and only ever
# consumed between a day number and a known month name — it cannot free-stand.
_DAY_PART = (
    r"(?:(\d{1,2})(?:st|nd|rd|th)\s+of\s+"  # en ordinal-of day
    r"|(\d{1,2})(?:st|nd|rd|th|er|-го|-е|ই|শে|লা|রা|ঠা|\.)?\s+(?:(?:de|ng)\s+)?)"  # all other forms
)
_D_CONN_RANGE = r"(?:(?:de|ng)\s+)"  # ranges: bare cardinals by nature — never "of"

# Anchored expressions (resolved against the article's PUBLICATION date; each
# carries graded provenance — FUTURE_DEVELOPMENTS design, now implemented).
# The negative lookaheads MIRROR every explicit-year continuation the full-date
# patterns accept (connectors, the dual slash-joined month, day ranges): when an
# explicit year follows in ANY accepted shape, the no-year path must never fire —
# suppress rather than anchor-guess, even for forms we do not extract.
_DM_NOYEAR_RE = re.compile(
    rf"\b{_DAY_PART}({_MONTH_ALT})\.?\b"
    rf"(?!(?:\.?(?:\s*/\s*(?:{_MONTH_ALT})\.?)?\s+{_Y_CONN}?\d{{4}}"
    # cross-month range continuation ("11 May – 13 June 2026"): the explicit
    # year governs the whole expression — suppress the first endpoint.
    rf"|\s*[-–—]\s*\d{{1,2}}(?:st|nd|rd|th|er|\.)?\s+(?:{_MONTH_ALT})\.?\s+{_Y_CONN}?\d{{4}}))",
    re.I,
)
# Every explicit-year continuation after "Month DD" that must SUPPRESS the
# anchored path (verifier-measured: the bare-dash mirror alone left the common
# range spellings fabricating — "June 11-June 13, 2026", "June 11 to 13, 2026",
# "June 11 and 12, 2026", "overnight June 11/12, 2026", "June 11/2026"):
#   1. a separator straight into a 4-digit year ("11/2026");
#   2. a dash/slash/worded second endpoint — optionally month-repeated, in
#      either digit-month or month-digit order — then the year;
#   3. the plain year (the original mirror, connectors included).
_MD_YEAR_AHEAD = (
    rf"(?:\s*[-–—/]\s*\d{{4}}\b"
    rf"|\s*(?:[-–—/]\s*|,?\s+(?:to|and|or)\s+)(?:(?:{_MONTH_ALT})\.?\s+)?"
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s*{_Y_CONN}?\d{{4}}\b"
    rf"|\s*(?:[-–—/]\s*|,?\s+(?:to|and|or)\s+)\d{{1,2}}(?:st|nd|rd|th|er|\.)?\s+"
    rf"(?:{_MONTH_ALT})\.?\s+{_Y_CONN}?\d{{4}}\b"
    rf"|\.?\s*,?\s*{_Y_CONN}?\d{{4}}\b)"
)
_MD_NOYEAR_RE = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!{_MD_YEAR_AHEAD})",
    re.I,
)
# Relative day words. UNGATED tokens are single-meaning in every language that
# writes them; collision-prone tokens are LANGUAGE-GATED via _REL_LANG_GATES —
# with the article-language hint they resolve, without it (or with the wrong
# language) they are SKIPPED, never guessed (the _MONTH_LANG_OVERRIDES policy
# applied to relative words). DELIBERATE OMISSIONS (miss over invent): hi "कल"
# and bare bn "কাল" are BIDIRECTIONAL (yesterday AND tomorrow — only context
# disambiguates); ro ASCII "maine" (Maine, USA) — only diacritic "mâine".
_REL_WORDS = {
    "yesterday": -1, "today": 0, "tomorrow": 1,
    "hier": -1, "aujourd'hui": 0, "aujourd’hui": 0, "demain": 1,
    "gestern": -1, "heute": 0, "morgen": 1,
    "ayer": -1, "hoy": 0, "mañana": 1,
    "ontem": -1, "hoje": 0, "amanhã": 1,
    "ieri": -1, "oggi": 0, "domani": 1,
    # ru (script-unique)
    "вчера": -1, "сегодня": 0, "завтра": 1,
    # ar — both hamza/tanwin spellings; اليوم is also the plain noun "the day"
    "أمس": -1, "امس": -1, "غدا": 1, "غداً": 1, "غدًا": 1, "اليوم": 0,
    # hi + bn (directional forms only; the bare deictics are omitted above)
    "आज": 0, "আজ": 0, "গতকাল": -1, "আগামীকাল": 1,
    # el + accentless variants (ALL-CAPS Greek drops the tonos — slice-B quirk)
    "χθες": -1, "χτες": -1, "σήμερα": 0, "σημερα": 0, "αύριο": 1, "αυριο": 1,
    # pl (jutro gated — sr/hr/bs "jutro" = morning)
    "wczoraj": -1, "dziś": 0, "dzisiaj": 0, "jutro": 1,
    # ro ("azi" gated: the ASCII trigram is also an en drug abbreviation)
    "azi": 0, "astăzi": 0, "mâine": 1,
    # nl ("morgen" itself rides the de/nl gate)
    "gisteren": -1, "vandaag": 0,
    # sv/da/nb — the "i X" phrases are the standard forms; the one-word sv
    # spellings are common online. da/nb bare "morgen" = MORNING (measured
    # false positive: "mandag morgen") → excluded by the de/nl gate; the da/nb
    # tomorrow is the PHRASE "i morgen".
    "igår": -1, "idag": 0, "imorgon": 1,
    "i går": -1, "i dag": 0, "i morgon": 1, "i morgen": 1,
    # sr Cyrillic + Latin (Latin "sutra" gated — the en loan noun)
    "јуче": -1, "данас": 0, "сутра": 1, "juče": -1, "danas": 0, "sutra": 1,
    # tr (the _REL_WORDS.get round-trip guard covers DOTLESS-I headline forms)
    "dün": -1, "bugün": 0, "yarın": 1,
    # id/ms
    "kemarin": -1, "besok": 1, "hari ini": 0,
}
# token -> base languages allowed to resolve it. A gated token with no language
# hint, or a language outside its set, is skipped — never guessed.
_REL_LANG_GATES = {
    "morgen": {"de", "nl"},        # da/nb "morgen" = morning (measured live FP)
    "jutro": {"pl"},               # sr/hr/bs "jutro" = morning
    "sutra": {"sr", "hr", "bs"},   # en "sutra" = the Buddhist text
    "сутра": {"sr"},               # ru "Алмазная сутра" (the same text) + the
                                   # colloquial "сутра" (= "с утра", since
                                   # morning) — verifier-measured in ru prose
    "اليوم": {"ar"},               # also the ordinary noun "the day"
    # BOTH spellings of yesterday gated: hamza-less امس is Urdu "humidity"
    # ("گرمی اور امس" is stock ur weather prose — verifier-measured), and the
    # hamza form travels in the same script.
    "أمس": {"ar"}, "امس": {"ar"},
    "azi": {"ro"},                 # ASCII trigram (AZI = azithromycin in en)
    "dün": {"tr"}, "bugün": {"tr"}, "yarın": {"tr"},
    "kemarin": {"id", "ms"}, "besok": {"id", "ms"}, "hari ini": {"id", "ms"},
}
_REL_RE = re.compile(r"\b(" + "|".join(sorted(_REL_WORDS, key=len, reverse=True)) + r")\b", re.I)
# Weekdays (anchored-only; bare token = the most recent such day, the news
# convention). Collision-prone tokens are language-gated (_WD_LANG_GATES) or
# accepted ONLY inside an unambiguous collocation (_WD_COLLOCATIONS below).
# DELIBERATE OMISSIONS: ro "luni" (= "months"); ALL el weekday names (ordinal
# homographs — need case-sensitive treatment, a separate ruling); ru/sr bare
# среда/среду (= "environment") and sr bare недеља/nedelja (= "week") — those
# resolve only via their prepositional collocations.
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4,
    "samedi": 5, "dimanche": 6,
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,
    "samstag": 5, "sonntag": 6,
    # nl
    "maandag": 0, "dinsdag": 1, "woensdag": 2, "donderdag": 3, "vrijdag": 4,
    "zaterdag": 5, "zondag": 6,
    # sv + da/nb (the shared tokens all name the SAME day)
    "måndag": 0, "tisdag": 1, "onsdag": 2, "torsdag": 3, "fredag": 4,
    "lördag": 5, "söndag": 6,
    "mandag": 0, "tirsdag": 1, "lørdag": 5, "søndag": 6,
    # pl — nominative + the accusative news idiom ("w niedzielę")
    "poniedziałek": 0, "wtorek": 1, "środa": 2, "środę": 2, "czwartek": 3,
    "piątek": 4, "sobota": 5, "sobotę": 5, "niedziela": 6, "niedzielę": 6,
    # ru (nominative + the accusative feminine news forms)
    "понедельник": 0, "вторник": 1, "четверг": 3, "пятница": 4, "пятницу": 4,
    "суббота": 5, "субботу": 5, "воскресенье": 6,
    # ro
    "marți": 1, "miercuri": 2, "joi": 3, "vineri": 4, "sâmbătă": 5, "duminică": 6,
    # ar definite forms (the news standard; the optional يوم prefix is a
    # separate word, no pattern change) — both hamza spellings
    "الاثنين": 0, "الإثنين": 0, "الثلاثاء": 1, "الأربعاء": 2, "الاربعاء": 2,
    "الخميس": 3, "الجمعة": 4, "السبت": 5, "الأحد": 6, "الاحد": 6,
    # hi + bn (-वार / -বার forms, script-unique)
    "सोमवार": 0, "मंगलवार": 1, "बुधवार": 2, "गुरुवार": 3, "शुक्रवार": 4,
    "शनिवार": 5, "रविवार": 6,
    "সোমবার": 0, "মঙ্গলবার": 1, "বুধবার": 2, "বৃহস্পতিবার": 3, "শুক্রবার": 4,
    "শনিবার": 5, "রবিবার": 6,
    # tr (cuma/pazar = ar-loan "Friday"-homographs / "market" → collocations)
    "pazartesi": 0, "salı": 1, "çarşamba": 2, "perşembe": 3, "cumartesi": 5,
    # sr Cyrillic + Latin, gated {sr(,hr,bs)}: id "petak" = a plot/compartment,
    # and the Latin forms are BCS-shared
    "понедељак": 0, "уторак": 1, "четвртак": 3, "петак": 4, "субота": 5,
    "ponedeljak": 0, "ponedjeljak": 0, "utorak": 1, "četvrtak": 3, "petak": 4,
    "subota": 5,
    # id (senin gated — tr "senin" = "your"; minggu = "week" → collocation)
    "senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4, "sabtu": 5,
}
_WD_LANG_GATES = {
    "senin": {"id"},
    "понедељак": {"sr"}, "уторак": {"sr"}, "четвртак": {"sr"}, "петак": {"sr"},
    "субота": {"sr"},
    "ponedeljak": {"sr", "bs"}, "ponedjeljak": {"hr", "bs"},
    "utorak": {"sr", "hr", "bs"}, "četvrtak": {"sr", "hr", "bs"},
    "petak": {"sr", "hr", "bs"}, "subota": {"sr", "hr", "bs"},
}
# Weekday tokens that are also PLACE names, blocked by their measured name
# context (evidence-grown, like the stoplist denylists — never a category
# sweep): Środa Wielkopolska/Śląska (pl towns), Murska Sobota (sl city),
# Çarşamba/Perşembe (tr districts). All three verifier-measured fabrications.
_WD_NAME_AFTER = {  # token -> the FOLLOWING text must not start with this
    "środa": re.compile(r"\s+(?:wielkopolsk|śląsk)", re.I),
    "çarşamba": re.compile(r"\s+(?:ilçe|belediye)", re.I),
    "perşembe": re.compile(r"\s+(?:ilçe|belediye)", re.I),
}
_WD_NAME_BEFORE = {  # token -> the PRECEDING text must not end with this
    "sobota": re.compile(r"murska\s+\Z", re.I),
}
_WD_RE = re.compile(
    r"\b(next\s+|last\s+)?(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b", re.I
)
# sv + da definite-past weekday forms ("i fredags" = LAST Friday, up to a week
# earlier than the bare-token most-recent reading): resolved with the "last"
# arithmetic. The bare-token regex can never claim these — the trailing -s is
# a word character, so \bfredag\b does not match inside "fredags" (measured).
_WD_LAST_PHRASES = {
    "i måndags": 0, "i tisdags": 1, "i onsdags": 2, "i torsdags": 3,
    "i fredags": 4, "i lördags": 5, "i söndags": 6,
    "i mandags": 0, "i tirsdags": 1, "i lørdags": 5, "i søndags": 6,  # da/nb
}
_WD_LAST_RE = re.compile(
    r"\b(" + "|".join(sorted(_WD_LAST_PHRASES, key=len, reverse=True)) + r")\b", re.I
)
# sv/da "på + weekday" is grammatically the UPCOMING one ("på fredag" said on a
# Wednesday = this coming Friday; the past form is "i fredags" above) — the
# bare-token most-recent fallback would systematically invert the direction
# (verifier-measured). Resolved as next-or-today; runs before the bare loop so
# its claim wins.
_WD_COMING_PHRASES = {
    "på måndag": 0, "på tisdag": 1, "på onsdag": 2, "på torsdag": 3,
    "på fredag": 4, "på lördag": 5, "på söndag": 6,
    "på mandag": 0, "på tirsdag": 1, "på lørdag": 5, "på søndag": 6,  # da/nb
}
_WD_COMING_RE = re.compile(
    r"\b(" + "|".join(sorted(_WD_COMING_PHRASES, key=len, reverse=True)) + r")\b", re.I
)
# Collocation-only weekday tokens: the bare word is a homograph in its own or a
# sibling language (sr среда = milieu, sr недеља/nedelja = week, tr pazar =
# market, id minggu = week), so ONLY the unambiguous prepositional / "günü" /
# "hari" collocation resolves; the bare token is never in _WEEKDAYS.
# DELIBERATE OMISSION (verifier-measured): ru "в среду" is NOT accepted — the
# accusative is also "into the environment" ("внедрение в среду разработки",
# "выброс в среду обитания" are everyday tech/ecology prose), so even the
# collocation cannot disambiguate; ru Wednesday is an honest miss. The id
# collocation excludes "hari minggu ini/lalu/depan" ("every day THIS WEEK").
_WD_COLLOCATIONS = {
    "у среду": 2, "у недељу": 6, "u nedelju": 6,
    "cuma günü": 4, "pazar günü": 6, "hari minggu": 6,
}
_WD_COLLOC_RE = re.compile(
    r"\b(?:(у среду|у недељу|u nedelju|cuma günü|pazar günü)"
    r"|(hari minggu)(?!\s+(?:ini|lalu|depan)\b))\b",
    re.I,
)
# CJK relative words + weekdays — boundary-FREE (ideographs are \w in Python
# re, so \b never fires inside a CJK run; the slice-B measured fact) and
# language-GATED to zh/ja (production always passes the article language).
# Lookaheads exclude the measured proper-noun compounds: 明日香 (Asuka),
# 今日头条/今日頭條 (Toutiao), 明天系 (Tomorrow Holding).
_CJK_REL_WORDS = {"昨天": -1, "今天": 0, "明天": 1, "昨日": -1, "今日": 0, "明日": 1}
_CJK_REL_RE = re.compile(
    r"(昨天|今天|明天(?!系)|昨日"
    r"|今日(?!头条|頭條|俄罗斯|俄羅斯|美国|美國)"  # Toutiao · RT · USA Today
    r"|明日(?!香|黄花|黃花))"  # Asuka; 明日黄花 = the "outdated" idiom
)
_CJK_WD_NUMS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_JA_WD_KANJI = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
# zh 星期X · ja X曜日/X曜 · zh [上下本]周X. Segmentation guards (all
# verifier-measured trap classes — each blocked continuation is a common word
# that re-segments the string: 天气/天氣 weather · 日本 Japan · 日经/日經 Nikkei ·
# 日元/日圆/日圓 yen · 五金 hardware · 六成 "60%" — while 成交 keeps the genuine
# 成交量 "trading volume" reading): miss over invent on the ambiguous ones.
# The short 周X form REQUIRES the 上/下/本 modifier — the modifier carries the
# direction (上周二 = LAST Tuesday; bare 周二 would mis-resolve most-recent) —
# and 周日 is deliberately NOT accepted even with a modifier ("上周日本首相…" =
# 上周+日本, not 上周日+本; Sunday stays reachable via 星期日/星期天/日曜日).
# A weekday DIGIT followed by a counter/classifier/quantity word re-segments
# ("本周一些地区" = 本周 + 一些 "some", "上周三名工人" = 上周 + 三名 "three
# (workers)", "下周一系列活动" = 下周 + 一系列 "a series of") — all
# verifier-measured; each blocked continuation is an honest miss on a genuine
# ambiguity, per the 周日 doctrine.
# 人(?!民), 大(?!会), 分(?!析) are one-sided refinements (round 2): 人民银行/
# 人民日报, 周三大会, 周三分析师 are constant weekday-side news patterns with no
# counting reading, while 三人/三大运营商/三分之一 stay blocked.
_CJK_WD_CONT = (
    r"(?!些|系列|名|起|万|萬|千|百|亿|億|个|個|项|項|次|人(?!民)|家|户|戶|位|天|年|月"
    r"|种|種|批|条|條|场|場|轮|輪|度|分(?!析)|半|大(?!会))"
)
_CJK_WD_DAY = rf"(?:(?:[一二三四]|五(?!金(?!融))|六(?!成(?!交))){_CJK_WD_CONT})"
_CJK_WD_RE = re.compile(
    rf"(?:星期({_CJK_WD_DAY}|天(?!气|氣)|日(?!本|经|經|元|圆|圓))"
    r"|([月火水木金土日])曜日?"
    rf"|([上下本])[周週]({_CJK_WD_DAY}))"
)
_KO_REL_WORDS = {"어제": -1, "오늘": 0, "내일": 1}
# Hangul boundaries: \b never fires inside a Hangul run, so the lookbehind
# blocks compound substrings (안내일정 contains 내일) and the lookahead admits
# only a common particle / non-Hangul / end — 내일신문 (the newspaper) and
# 오늘날 ("nowadays") never match, while 어제는/오늘도/내일부터 do.
_KO_REL_RE = re.compile(r"(?<![가-힣])(어제|오늘|내일)(?=[은는도만의엔부까]|[^가-힣]|$)")
_KO_WD_RE = re.compile(r"(?<![가-힣])([월화수목금토일])요일")
_KO_WD_SYLL = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
# English anchored offsets (en-gated + anchor-only): "N days ago" and the
# last/next/this month family at the existing MONTH precision (day normalised
# to 1, like every _MY_RE match). The FULL "days ago" phrase is required (bare
# "ago" is Italian for "needle"); "(the) last month" is excluded — "the last
# month of the war" is a duration, and "in the last month" a rolling window,
# not the previous calendar month; "a week ago" is deliberately NOT interpreted
# (a −7d convention would be a ruling, not a fact in the text).
_EN_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_EN_AGO_RE = re.compile(
    r"\b(\d{1,2}|" + "|".join(_EN_NUM_WORDS) + r")\s+days\s+ago\b", re.I
)
# "two years and three days ago": the phrase is the TAIL of a compound
# duration — searched with endpos = the match start, so \Z anchors right
# before the number token. The comma branch requires a NUMBER/duration word
# on its left ("two years, three days ago") — a bare comma is ordinary prose
# ("However, five days ago…" — round-2 measured false suppression).
_EN_AGO_COMPOUND = re.compile(
    r"(?:\band|(?:\d|\byears?|\bmonths?|\bweeks?)\s*,)\s*\Z", re.I
)
_EN_MONTH_OFF_RE = re.compile(
    r"\b(?:(last|next)\s+month|(?:(?:earlier|later)\s+)?this\s+month)\b", re.I
)
# A determiner/possessive before "last/next month" flips the meaning to the
# final/following month OF A PERIOD or a rolling window ("the last month of
# the war", "his last month in office", "the company's last month", "over the
# next month") — never the previous/next calendar month. In-loop guard, not a
# lookbehind: fixed-width lookbehinds cannot cover possessives or a double
# space (both verifier-measured bypasses).
_EN_MONTH_DETERMINED = re.compile(
    r"(?:\bthe|\bhis|\bher|\bits|\btheir|\bour|\bmy|\byour|\bevery|\bfinal|\bone|'s|s’)\s*\Z",
    re.I,  # \bone: "gave it one last month" = one FINAL month (round 2)
)

_ISO_RE = re.compile(  # digit-safe boundaries: see _NUM_DMY_RE (glued CJK prose)
    rf"{_NUM_BOUND_L}(\d{{4}})-(\d{{2}})-(\d{{2}}){_NUM_BOUND_R}"
)
# Full day-month-year, with the optional connectors above and an optional
# DUAL-NAMED month ("سبتمبر/أيلول" — pan-Arab media slash-join the international
# and Levantine names). The two names must resolve to the SAME month or the whole
# match is skipped (never a guess); the no-year lookahead mirrors the slash form.
_DMY_RE = re.compile(
    rf"\b{_DAY_PART}({_MONTH_ALT})\.?"
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
_RANGE_DMY_RE = re.compile(  # day suffixes CAPTURED: the loop requires symmetry
    rf"\b(\d{{1,2}})((?:st|nd|rd|th|er|\.)?)\s*[-–—]\s*(\d{{1,2}})((?:st|nd|rd|th|er|\.)?)\s+"
    rf"{_D_CONN_RANGE}?({_MONTH_ALT})\.?\s+{_Y_CONN}?(\d{{4}})\b",
    re.I,
)
_RANGE_ENUM_RE = re.compile(  # "between 11 and 13 June 2026" (en connector for now)
    rf"\b(\d{{1,2}})\s+and\s+(\d{{1,2}})\s+{_D_CONN_RANGE}?({_MONTH_ALT})\.?\s+{_Y_CONN}?(\d{{4}})\b",
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
# 日 standard · 号/號 colloquial day markers — but 号 is ALSO the universal
# "No. N" marker (11号线 = Metro LINE 11, 6号楼 = Building 6, 2号台风 = Typhoon
# No. 2, 11号文件 = Document No. 11): a classifier ideograph right after 号
# means an ordinal, not a day (adversarially measured), so it suppresses.
_CJK_DAY_MARK = r"(?:日|[号號](?![线線楼樓房店院栋棟楼文台颱馆館厅廳桥橋]))"
_CJK_YMD_RE = re.compile(rf"({_CJK_D}{{4}})\s*年\s*({_CJK_D}{{1,2}})\s*月\s*({_CJK_D}{{1,2}})\s*{_CJK_DAY_MARK}")
_CJK_YM_RE = re.compile(rf"({_CJK_D}{{4}})\s*年\s*({_CJK_D}{{1,2}})\s*月")
_CJK_MD_RE = re.compile(rf"({_CJK_D}{{1,2}})\s*月\s*({_CJK_D}{{1,2}})\s*{_CJK_DAY_MARK}")  # no year -> anchored
# Korean dates use Hangul markers (년/월/일), NOT the 年月日 ideographs — Korean
# had ZERO coverage (measured; the field probe was equally blind). Same shape,
# same digits helper, same anchored rule for the year-less form.
_KO_YMD_RE = re.compile(rf"({_CJK_D}{{4}})\s*년\s*({_CJK_D}{{1,2}})\s*월\s*({_CJK_D}{{1,2}})\s*일")
_KO_YM_RE = re.compile(rf"({_CJK_D}{{4}})\s*년\s*({_CJK_D}{{1,2}})\s*월")
_KO_MD_RE = re.compile(rf"({_CJK_D}{{1,2}})\s*월\s*({_CJK_D}{{1,2}})\s*일")  # no year -> anchored

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
    rf"({_ERA_ALT})\s*({_CJK_D}{{1,3}}|元)\s*年\s*({_CJK_D}{{1,2}})\s*月(?:\s*({_CJK_D}{{1,2}})\s*{_CJK_DAY_MARK})?"
)
# Deictic year words before 月日 (今年6月11日 — among the commonest ja/zh date
# forms): these resolve EXACTLY against the anchor's year (offset 0/±1), unlike
# an unparsed era name or a bare 2-digit year, which must SUPPRESS. Note the old
# code anchored 昨年6月11日 to the nearest instance — often the WRONG year; the
# exact offset fixes that too.
_CJK_YEAR_DEICTICS = {
    "今年": 0, "本年": 0, "毎年": 0, "每年": 0,  # this year / annually
    "昨年": -1, "去年": -1,  # last year
    "来年": 1, "來年": 1, "明年": 1,  # next year
    # Korean — the 년-suffixed ones trip the year guard; 올해 (this year) and
    # the THREE-syllable 지난해 (last year, as common as 작년 in news prose —
    # a 2-char-only peek missed it and pinned the WRONG year, adversarially
    # measured) are caught by the length-aware peek in the guard:
    "작년": -1, "금년": 0, "매년": 0, "올해": 0, "내년": 1, "지난해": -1,
}
_CJK_TRAIL_PUNCT = "、。，．,.;；：:"  # 令和6年、6月11日 — the guard peeks past these


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

    # Day-precision dates PER CLAIMED SPAN (span start -> dates). `found` dedups
    # by (date, precision) keeping only the first occurrence's pos, so a
    # REPEATED dateline's second span would look date-less to the appositive
    # guard and its weekday would anchor-resolve (verifier-measured) — this
    # record survives the dedup.
    day_spans: dict[int, list[date]] = {}

    def add(d: date, precision: str, m: re.Match) -> None:
        if precision == "day":
            day_spans.setdefault(m.start(), []).append(d)
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
        n_int = 1 if n == "元" else _cjk_int(n)
        if n_int < 1:  # gengō/ROC year 0 does not exist (元年 = year 1)
            continue
        year = _ERA_BASES[m.group(1)] + n_int
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
        if m.group(1).lower() in _MONTH_LANG_OVERRIDES:  # month-first order (see _MDY_RE)
            continue
        mon = _month_of(m.group(1), language)
        d1n, d2n = int(m.group(2)), int(m.group(3))
        if mon and d1n < d2n:
            d1 = _valid(int(m.group(4)), mon, d1n, today)
            d2 = _valid(int(m.group(4)), mon, d2n, today)
            if d1 and d2 and claim(*m.span()):
                add(d1, "day", m)
                add(d2, "day", m)
    for m in _RANGE_DMY_RE.finditer(text):
        mon = _month_of(m.group(5), language)
        d1n, d2n = int(m.group(1)), int(m.group(3))
        # "aged 5-7. June 2026": a dot on the SECOND day only is a sentence
        # boundary, not the German "5.–7. Juni" ordinal pair — skip (verifier).
        if m.group(4) == "." and not m.group(2):
            continue
        # "May 11-13 June 2026": a month name right before the range means the
        # first endpoint belongs to THAT month — cross-month and ambiguous:
        # skip; the no-year lookaheads suppress the pieces, nothing is invented.
        prev_words = text[: m.start()].split()
        if prev_words and _month_of(prev_words[-1].strip(".,;:"), language):
            continue
        if mon and d1n < d2n:
            d1 = _valid(int(m.group(6)), mon, d1n, today)
            d2 = _valid(int(m.group(6)), mon, d2n, today)
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
        mon = _month_of(m.group(3), language)
        if mon is None:
            continue
        if m.group(4):  # dual-named "سبتمبر/أيلول": both must agree, else skip — never a guess
            alt = _month_of(m.group(4), language)
            if alt != mon:
                continue
        day = m.group(1) or m.group(2)  # ordinal-of branch | standard branch
        d = _valid(int(m.group(5)), mon, int(day), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _MDY_RE.finditer(text):
        # Homograph-month tokens never take the MONTH-FIRST order: they are all
        # genitive forms of day-first languages ("30. marta"), so "Marta 30,
        # 2024" is a name + number, not a date (verifier-measured fabrication).
        if m.group(1).lower() in _MONTH_LANG_OVERRIDES:
            continue
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
    for m in _KO_YMD_RE.finditer(text):  # 2024년 6월 11일 (Korean day)
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
    for m in _KO_YM_RE.finditer(text):  # 2024년 6월 (Korean month precision)
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

        # _DM_NOYEAR has TWO possible day groups (the ordinal-of branch vs the
        # standard branch of _DAY_PART); _MD_NOYEAR has one.
        for rx, gis_d, gi_m in ((_DM_NOYEAR_RE, (1, 2), 3), (_MD_NOYEAR_RE, (2,), 1)):
            for m in rx.finditer(text):
                # Homograph months never take the month-first order ("Marta 30
                # godina" is a name + number — verifier-measured fabrication).
                if rx is _MD_NOYEAR_RE and m.group(gi_m).lower() in _MONTH_LANG_OVERRIDES:
                    continue
                mon = _month_of(m.group(gi_m), language)
                if not mon:
                    continue
                day = next((m.group(i) for i in gis_d if m.group(i)), None)
                if day is None:
                    continue
                d = nearest_year(mon, int(day))
                if d and claim(*m.span()):
                    add(d, "day", m)
        def _cjk_anchor_day(m: re.Match) -> date | None:
            """The year-prefix guard + resolution shared by the CJK and Korean
            year-less month-day loops (deictic-FIRST so 올해/今年 — which do not
            all end in 年/년 — pin the exact year). A 年/년 just before the match
            means a year expression precedes: DEICTIC years (今年/昨年/작년/…)
            resolve EXACTLY against the anchor's year; anything else (an era
            name we could not parse, a bare 2-digit year like 24年) is an
            explicit year we failed to read — suppress, never anchor-guess
            (measured ~80-year fabrications). Punctuation-tolerant
            (令和6年、6月11日 still suppresses)."""
            before = text[: m.start()].rstrip().rstrip(_CJK_TRAIL_PUNCT)
            # Length-aware deictic peek (지난해 is three syllables).
            off = _CJK_YEAR_DEICTICS.get(before[-3:])
            if off is None:
                off = _CJK_YEAR_DEICTICS.get(before[-2:])
            if off is not None:
                return _valid(anchor.year + off, _cjk_int(m.group(1)), _cjk_int(m.group(2)), today)
            if before[-1:] in ("年", "년"):
                return None  # an explicit year we could not parse: suppress
            # Model-year suffixes ("2024년형" ko / "2024年式" ja) hide the year
            # token one character deeper — same rule: suppress, never guess.
            if before[-1:] in ("형", "式") and before[-2:-1] in ("年", "년"):
                return None
            return nearest_year(_cjk_int(m.group(1)), _cjk_int(m.group(2)))

        for m in _CJK_MD_RE.finditer(text):  # 5月11日 with no year -> nearest to the anchor
            d = _cjk_anchor_day(m)
            if d and claim(*m.span()):
                add(d, "day", m)
        for m in _KO_MD_RE.finditer(text):  # 6월 11일 with no year -> nearest to the anchor
            d = _cjk_anchor_day(m)
            if d and claim(*m.span()):
                add(d, "day", m)
        for m in _VI_DM_NOYEAR_RE.finditer(text):  # ngày 5 tháng 5 (no year) -> nearest
            d = nearest_year(int(m.group(2)), int(m.group(1)))
            if d and claim(*m.span()):
                add(d, "day", m)
        base = (language or "")[:2].lower()

        def _appositive_of_claimed(s: int, e: int, wd: int) -> bool:
            """A weekday ADJACENT to an already-claimed date that FALLS ON that
            weekday names it — an appositive ("2024年6月11日（星期二）", "wtorek,
            11 czerwca 2024", "Tuesday, June 12, 2026"), not an independent
            reference; resolving it against the anchor would invent a SECOND,
            different date. The AGREEMENT test is what keeps independent
            neighbours alive (verifier-measured regressions without it): a
            weekday list ("runs Friday, Saturday and Sunday") never agrees —
            consecutive days differ — and "…of 2026-06-08, Friday's session"
            (a Monday) stays an independent Friday. Only soft separators
            bridge (space/comma/parens — never a sentence-ending period)."""
            seps = " \t,、，()（）[]"
            left_end = len(text[:s].rstrip(seps))
            right_start = e + (len(text[e:]) - len(text[e:].lstrip(seps)))
            return any(
                (ce == left_end or cs == right_start)
                and any(dt.weekday() == wd for dt in day_spans.get(cs, ()))
                for cs, ce in consumed
            )

        def _wd_resolve(wd: int, mod: str) -> date:
            delta = (wd - anchor.weekday()) % 7
            if mod == "next":
                return anchor + timedelta(days=delta or 7)
            if mod == "last":
                return anchor - timedelta(days=((anchor.weekday() - wd) % 7) or 7)
            return anchor - timedelta(days=(anchor.weekday() - wd) % 7)  # most recent

        for m in _REL_RE.finditer(text):
            tok = m.group(1).lower()
            off = _REL_WORDS.get(tok)
            if off is None:  # casefold round-trip miss (dotless-ı class): skip, never abort
                continue
            gate = _REL_LANG_GATES.get(tok)
            if gate is not None and base not in gate:
                continue  # collision-prone token without its language: skip, never guess
            if claim(*m.span()):
                add(anchor + timedelta(days=off), "day", m)
        for m in _WD_LAST_RE.finditer(text):  # sv/da "i fredags" = LAST Friday
            wd = _WD_LAST_PHRASES.get(m.group(1).lower())
            if wd is not None and claim(*m.span()):
                add(_wd_resolve(wd, "last"), "day", m)
        for m in _WD_COMING_RE.finditer(text):  # sv/da "på fredag" = the COMING one
            wd = _WD_COMING_PHRASES.get(m.group(1).lower())
            if wd is None or _appositive_of_claimed(*m.span(), wd):
                continue
            if claim(*m.span()):
                add(anchor + timedelta(days=(wd - anchor.weekday()) % 7), "day", m)
        for m in _WD_COLLOC_RE.finditer(text):  # "у среду" / "cuma günü" / "hari Minggu"
            tok = (m.group(1) or m.group(2)).lower()
            wd = _WD_COLLOCATIONS.get(tok)
            if wd is None or _appositive_of_claimed(*m.span(), wd):
                continue
            if claim(*m.span()):
                add(_wd_resolve(wd, ""), "day", m)
        for m in _WD_RE.finditer(text):
            tok = m.group(2).lower()
            wd = _WEEKDAYS.get(tok)
            if wd is None:  # casefold round-trip miss (dotless-ı class): skip, never abort
                continue
            gate = _WD_LANG_GATES.get(tok)
            if gate is not None and base not in gate:
                continue  # collision-prone token without its language: skip, never guess
            # Place-name traps ("Środa Wielkopolska", "Murska Sobota",
            # "Çarşamba ilçesi") — measured, evidence-grown context denylist.
            after_rx = _WD_NAME_AFTER.get(tok)
            if after_rx is not None and after_rx.match(text, m.end()):
                continue
            before_rx = _WD_NAME_BEFORE.get(tok)
            if before_rx is not None and before_rx.search(text, 0, m.start()):
                continue
            if _appositive_of_claimed(*m.span(), wd):
                continue  # names the adjacent explicit date, not a new reference
            mod = (m.group(1) or "").strip().lower()
            if claim(*m.span()):
                add(_wd_resolve(wd, mod), "day", m)
        if base in ("zh", "ja"):
            for m in _CJK_REL_RE.finditer(text):
                off = _CJK_REL_WORDS.get(m.group(1))
                if off is not None and claim(*m.span()):
                    add(anchor + timedelta(days=off), "day", m)
            for m in _CJK_WD_RE.finditer(text):
                if m.group(3):  # [上下本]周X — CALENDAR-week semantics: 上周二 is
                    # Tuesday of the previous Monday-start week (NOT the English
                    # "most recent past Tuesday" — up to a week apart).
                    wd = _CJK_WD_NUMS.get(m.group(4))
                    if wd is None or _appositive_of_claimed(*m.span(), wd):
                        continue
                    week_off = {"上": -7, "下": 7, "本": 0}[m.group(3)]
                    d = anchor + timedelta(days=wd - anchor.weekday() + week_off)
                    if claim(*m.span()):
                        add(d, "day", m)
                    continue
                if m.group(1):  # 星期X
                    wd = _CJK_WD_NUMS.get(m.group(1))
                else:  # X曜日 / X曜
                    wd = _JA_WD_KANJI.get(m.group(2))
                if wd is None or _appositive_of_claimed(*m.span(), wd):
                    continue
                if claim(*m.span()):
                    add(_wd_resolve(wd, ""), "day", m)
        if base == "ko":
            for m in _KO_REL_RE.finditer(text):
                off = _KO_REL_WORDS.get(m.group(1))
                if off is not None and claim(*m.span()):
                    add(anchor + timedelta(days=off), "day", m)
            for m in _KO_WD_RE.finditer(text):
                wd = _KO_WD_SYLL[m.group(1)]
                if _appositive_of_claimed(*m.span(), wd):
                    continue
                if claim(*m.span()):
                    add(_wd_resolve(wd, ""), "day", m)
        if base == "en":
            for m in _EN_AGO_RE.finditer(text):
                # "two years and three days ago" is a COMPOUND duration — the
                # tail alone would be off by the years (verifier-measured):
                # a preceding and/comma/larger-unit word suppresses.
                if _EN_AGO_COMPOUND.search(text, 0, m.start()):
                    continue
                tok = m.group(1).lower()
                n = int(tok) if tok.isdigit() else _EN_NUM_WORDS[tok]
                if claim(*m.span()):
                    add(anchor - timedelta(days=n), "day", m)
            for m in _EN_MONTH_OFF_RE.finditer(text):
                # "the/his/its/the company's last month (of …)" is the FINAL
                # month of a period or a rolling window, not the previous
                # calendar month (verifier-measured: possessives slipped the
                # old lookbehind, as did a double space).
                if m.group(1) and _EN_MONTH_DETERMINED.search(text, 0, m.start()):
                    continue
                off = {"last": -1, "next": 1}.get((m.group(1) or "").lower(), 0)
                mo0 = anchor.month - 1 + off
                d = _valid(anchor.year + mo0 // 12, mo0 % 12 + 1, 1, today)
                if d and claim(*m.span()):
                    add(d, "month", m)

    out = sorted(found.values(), key=lambda c: c["pos"])
    for c in out:
        c.pop("pos", None)
    return out[:limit]
