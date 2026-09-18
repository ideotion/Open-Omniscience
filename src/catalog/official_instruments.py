"""
The `primary_source` axis, rewritten as an OBSERVABLE (Q1110 = a, 2026-09-15).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULING, and the argument behind it. The institutions review asked whether
``primary_source`` -- a model's judgement about whether a body is a real institution -- is
the right cut at all, and answered: DEFER, NOT REJECT, and rewrite the axis as something
CHECKABLE. The recommendation, verbatim from the review: *"does this feed publish dated
official instruments (decisions, tenders, regulations, statistics releases)?" is checkable
against the headlines and does not require a model to hold opinions about which countries'
institutions are real.*

WHY THAT REWRITE IS THE POINT, not a simplification. The judgement axis reached 84.7 %
two-judge agreement across 84 countries, and the three stakes the review recorded are all
about what the remaining 15.3 % costs:

  * EQUITY — a model calibrated on Western administrative norms under-admits small-language
    and global-South bodies while looking like a quality filter. A Czech village's zoning
    notices ARE the only public record of that fact.
  * REFUSAL IS NOT NEUTRAL — "we could not tell" was being recorded as "no", which is the
    shape the robots ruling already rejected.
  * THE LABEL MUST BE TRUE — a list called `official_sources.yml` full of tourism boards
    lies, and one that excludes real ministries understates its own coverage.

So this module OBSERVES and never concludes. Its three outcomes are ``observed`` (headlines
carrying the shape), ``none_observed`` (the shape was looked for and not found) and
``no_evidence`` (there were no headlines to look at) -- and the second and third are kept
apart, because collapsing them is exactly the "could not tell recorded as no" the review
names. Nothing here returns a boolean called `primary_source`, and nothing here gates a
splice: the brief scopes this to a PROPOSAL SURFACE, and whether the observable ever becomes
a gate is explicitly not this slice's to decide.

HOW IT AVOIDS BEING AN ENGLISH TEST WITH TRANSLATIONS. A headline is instrument-shaped when
it carries BOTH a temporal or reference marker AND an instrument word. The first half is
script- and language-independent (a four-digit year, an ISO date, a `No. 123/2024`-style
reference); the second is a lexicon that must be extended in each language by someone who
reads it. The lexicon is therefore explicitly INCOMPLETE and says so in its own payload: a
language the lexicon does not cover yields ``none_observed`` about the LEXICON, never about
the source, and the coverage note names which languages are actually covered so a reader can
tell those two apart.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

#: The three outcomes. ``NONE_OBSERVED`` and ``NO_EVIDENCE`` are deliberately distinct.
OBSERVED = "observed"
NONE_OBSERVED = "none_observed"
NO_EVIDENCE = "no_evidence"

#: Languages whose instrument vocabulary is represented below. A source whose headlines are
#: in a language absent from this list cannot be observed by this rule, and the payload says
#: so rather than reporting a clean negative.
LEXICON_LANGUAGES: tuple[str, ...] = (
    "en", "fr", "de", "es", "pt", "it", "nl", "ru", "uk", "pl", "cs", "ro",
    "ar", "zh", "ja", "id", "hi", "bn", "tr", "vi",
)

#: Instrument words, lowercased and accent-folded. Grouped by the KIND of instrument the
#: review named -- decisions, tenders, regulations, statistics releases -- because a reader
#: checking whether a match is fair needs to see which kind fired, not just that one did.
#:
#: DELIBERATELY NOT A TRANSLATION TABLE. Each language contributes the words its own
#: administrations actually use on their own notices; several have no clean equivalent of an
#: English term and carry a different word entirely. Entries are matched as whole words
#: (or, for the unsegmented scripts, as substrings -- see `_contains`).
INSTRUMENT_WORDS: dict[str, tuple[str, ...]] = {
    "decision": (
        "decision", "decisions", "ruling", "rulings", "resolution", "resolutions",
        "decree", "decrees", "order", "ordinance", "ordinances", "judgment", "judgement",
        "decision", "arrete", "arretes", "deliberation", "deliberations", "ordonnance",
        "beschluss", "beschlusse", "verfugung", "erlass", "bescheid",
        "resolucion", "resoluciones", "decreto", "decretos", "acuerdo", "acuerdos",
        "despacho", "portaria", "portarias", "deliberacao",
        "delibera", "delibere", "determina", "ordinanza", "ordinanze",
        "besluit", "besluiten", "beschikking",
        "reshenie", "postanovlenie", "ukaz", "rasporyazhenie",
        "решение", "решения", "постановление", "постановления", "указ",
        "распоряжение", "приказ", "определение",
        "rishennya", "postanova", "nakaz",
        "рішення", "постанова", "наказ", "розпорядження",
        "uchwala", "rozporzadzenie", "zarzadzenie", "decyzja",
        "usneseni", "rozhodnuti", "vyhlaska", "narizeni",
        "hotarare", "hotarari", "ordin", "dispozitie",
        "qarar", "qararat", "marsoum", "ta'mim",
        "قرار", "قرارات", "مرسوم", "تعميم", "حكم",
        "决定", "决议", "令", "公告", "批复", "裁定",
        "決定", "告示", "訓令", "通達", "答申",
        "keputusan", "ketetapan", "peraturan",
        "aadesh", "adhisuchana", "nirnay",
        "आदेश", "अधिसूचना", "निर्णय", "संकल्प",
        "siddhanta", "adesh",
        "আদেশ", "বিজ্ঞপ্তি", "প্রজ্ঞাপন", "সিদ্ধান্ত",
        "karar", "kararlar", "genelge", "yonetmelik",
        "quyet dinh", "nghi quyet", "chi thi",
    ),
    "tender": (
        "tender", "tenders", "procurement", "bid", "bids", "bidding", "solicitation",
        "appel d'offres", "appel doffres", "marche public", "marches publics", "adjudication",
        "ausschreibung", "ausschreibungen", "vergabe", "bekanntmachung",
        "licitacion", "licitaciones", "concurso publico", "contratacion",
        "licitacao", "licitacoes", "pregao", "edital", "editais",
        "bando", "bandi", "gara", "gare",
        "aanbesteding", "aanbestedingen",
        "tender", "zakupka", "zakupki", "konkurs",
        "закупка", "закупки", "конкурс", "тендер", "аукцион",
        "zakupivlya", "tendernyy",
        "закупівля", "торги",
        "przetarg", "przetargi", "zamowienie",
        "verejna zakazka", "vyberove rizeni",
        "licitatie", "achizitie", "achizitii",
        "munaqasa", "munaqasat", "'ata'",
        "مناقصة", "مناقصات", "عطاء", "مزايدة",
        "招标", "采购", "投标", "中标",
        "入札", "公募", "調達",
        "lelang", "pengadaan", "tender",
        "nivida", "tender suchna",
        "निविदा", "टेंडर",
        "দরপত্র", "টেন্ডার",
        "ihale", "ihaleler", "satin alma",
        "dau thau", "mua sam cong",
    ),
    "regulation": (
        "regulation", "regulations", "directive", "directives", "statute", "statutes",
        "act", "bylaw", "by-law", "bylaws", "amendment", "gazette", "circular",
        "reglement", "reglements", "loi", "decret", "circulaire", "journal officiel",
        "verordnung", "verordnungen", "richtlinie", "gesetz", "satzung", "amtsblatt",
        "reglamento", "reglamentos", "ley", "circular", "boletin oficial",
        "regulamento", "lei", "diario oficial", "instrucao normativa",
        "regolamento", "regolamenti", "legge", "circolare", "gazzetta ufficiale",
        "verordening", "richtlijn", "wet", "staatsblad",
        "reglament", "zakon", "prikaz", "polozhenie",
        "регламент", "закон", "положение", "правила", "инструкция",
        "официальный вестник",
        "zakon", "polozhennya",
        "закон", "положення", "правила",
        "ustawa", "regulamin", "obwieszczenie", "dziennik ustaw",
        "zakon", "sbirka zakonu", "smernice",
        "lege", "regulament", "monitorul oficial", "circulara",
        "la'iha", "qanun", "ta'limat", "al-jarida al-rasmiyya",
        "لائحة", "قانون", "تعليمات", "الجريدة الرسمية", "نظام",
        "条例", "规定", "办法", "通知", "公报", "法规",
        "規則", "政令", "省令", "官報", "条例",
        "peraturan", "undang-undang", "surat edaran", "lembaran negara",
        "niyam", "adhiniyam", "rajpatra",
        "नियम", "अधिनियम", "राजपत्र", "विनियम",
        "niyam", "gazette",
        "আইন", "বিধি", "প্রবিধান", "গেজেট",
        "yonetmelik", "teblig", "resmi gazete", "kanun",
        "nghi dinh", "thong tu", "cong bao",
    ),
    "statistics": (
        "statistics", "statistical release", "bulletin", "indicator", "indicators",
        "census", "survey results", "quarterly report", "annual report", "data release",
        "statistiques", "bulletin statistique", "recensement", "indice",
        "statistik", "statistiken", "mikrozensus", "kennzahlen",
        "estadistica", "estadisticas", "censo", "indicadores", "boletin",
        "estatistica", "estatisticas", "censo", "indicadores", "boletim",
        "statistica", "statistiche", "censimento", "indicatori", "bollettino",
        "statistiek", "volkstelling",
        "statistika", "perepis", "byulleten", "pokazateli",
        "статистика", "перепись", "бюллетень", "показатели", "сводка",
        "statystyka", "perepys",
        "статистика", "перепис", "бюлетень", "показники",
        "statystyka", "spis powszechny", "wskazniki", "biuletyn",
        "statistika", "scitani", "ukazatele",
        "statistica", "recensamant", "indicatori", "buletin",
        "ihsa'at", "ta'dad", "nashra",
        "إحصاءات", "إحصائيات", "تعداد", "نشرة", "مؤشرات",
        "统计", "普查", "指标", "公报", "季报", "年报",
        "統計", "国勢調査", "指標", "月報", "年報",
        "statistik", "sensus", "indikator", "berita resmi statistik",
        "sankhyiki", "janaganana",
        "सांख्यिकी", "जनगणना", "आँकड़े", "सूचकांक",
        "parisankhyan",
        "পরিসংখ্যান", "আদমশুমারি", "সূচক",
        "istatistik", "sayim", "gosterge", "bulten",
        "thong ke", "tong dieu tra", "chi so",
    ),
}

#: Scripts that a whitespace tokenizer cannot segment, so their lexicon entries are matched
#: as substrings instead. Matching Chinese or Japanese on word boundaries would find nothing
#: at all, which would read as "this ministry publishes no instruments".
_UNSEGMENTED = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")

#: A four-digit year, an ISO-ish date, a d/m/y or y/m/d date, or a reference number of the
#: `No 123/2024` family. All of these are digit-shaped and therefore language-independent --
#: which is the half of the rule that must not encode anybody's administrative norms.
_TEMPORAL = re.compile(
    r"(?<!\d)(?:"
    r"(?:19|20)\d{2}"                      # a Gregorian year
    r"|\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}"    # a date in any field order
    r"|\d{1,6}\s*/\s*(?:19|20)\d{2}"       # 123/2024, the instrument-reference shape
    r")(?!\d)"
    # NON-GREGORIAN CALENDARS, because a Gregorian-only date test is the same equity failure
    # as an English-only lexicon. A Japanese ministry's notice dated 令和6年, a Taiwanese one
    # dated 民国113年 and a Gulf circular dated 1445هـ are all dated -- and a rule that read
    # them as undated would quietly under-observe exactly the administrations this ruling
    # exists to stop under-observing.
    r"|(?:令和|平成|昭和|大正|民国|民國)\s*\d{1,3}\s*年"
    r"|\d{1,4}\s*年(?:度)?"                  # a CJK year marker on its own
    r"|\d{3,4}\s*(?:هـ|هجري|ه\b)"           # a Hijri year
)
#: Eastern-Arabic and Devanagari digits, so a headline that dates itself in its own numerals
#: is not read as undated. Normalised to ASCII before the patterns above run.
_DIGIT_FOLD = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹०१२३४५६७८९০১২৩৪৫৬৭৮৯",
                            "0123456789" * 4)


def _fold(text: str) -> str:
    """Lowercase, strip accents, normalise digits. Accent folding is what lets one lexicon
    entry (`resolucion`) match both the accented and unaccented spellings a real headline
    might use, without listing every variant."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return folded.lower().translate(_DIGIT_FOLD)


#: The lexicon, FOLDED ONCE at import with the same `_fold` the headlines go through.
#:
#: This is not an optimisation, it is a correctness fix found by driving the rule on real
#: headlines: `_fold` strips COMBINING marks, and in Bengali, Devanagari and Arabic the
#: virama, the vowel signs and the harakat are combining marks. Folding only the haystack
#: left `প্রজ্ঞাপন` (a Bangladeshi gazette notification) unmatched against its own lexicon
#: entry, because the text had been decomposed and the needle had not. Latin entries were
#: unaffected -- which is precisely why it would have shipped: the languages it silently
#: failed on are the ones fewest readers of this code would have checked.
_FOLDED_WORDS: dict[str, tuple[str, ...]] = {}


def _contains(haystack: str, needle: str) -> bool:
    """Whole-word for segmented scripts, substring for unsegmented ones."""
    if _UNSEGMENTED.search(needle):
        return needle in haystack
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


_FOLDED_WORDS.update({
    kind: tuple(dict.fromkeys(_fold(w) for w in words if _fold(w).strip()))
    for kind, words in INSTRUMENT_WORDS.items()
})


def instrument_signals(title: str) -> dict:
    """The PURE per-headline read: which instrument kinds it names, and whether it is dated.

    Both halves are reported even when only one fires, because "an undated decision" and "a
    dated headline that names no instrument" are different things to look at and a caller
    tuning this needs to see which half is missing.
    """
    folded = _fold(title)
    kinds = sorted(
        kind for kind, words in _FOLDED_WORDS.items()
        if any(_contains(folded, w) for w in words)
    )
    dated = bool(_TEMPORAL.search(folded))
    return {"kinds": kinds, "dated": dated, "instrument_shaped": bool(kinds and dated)}


def observe_headlines(titles: Iterable[str], *, sample_cap: int = 12) -> dict:
    """The observable, over one source's headlines. NEVER a verdict about the source.

    Three outcomes, and the distinction between the last two is the ruling's own point:
      * ``observed``      -- at least one headline carries a dated instrument;
      * ``none_observed`` -- headlines were read and none did;
      * ``no_evidence``   -- there were no headlines to read.

    A caller that collapses the last two is recording "we could not tell" as "no", which is
    the shape the review named and the robots ruling already rejected.
    """
    seen = [t for t in titles if (t or "").strip()]
    if not seen:
        return {
            "outcome": NO_EVIDENCE, "n": 0, "matched": 0, "kinds": {}, "examples": [],
            "dated_only": 0, "instrument_only": 0,
            "note": (
                "No headlines were available for this source, so the observable could not be "
                "checked. This is not a negative result."
            ),
        }

    matched: list[tuple[str, list[str]]] = []
    kind_counts: dict[str, int] = {}
    dated_only = instrument_only = 0
    for title in seen:
        sig = instrument_signals(title)
        if sig["instrument_shaped"]:
            matched.append((title, sig["kinds"]))
            for k in sig["kinds"]:
                kind_counts[k] = kind_counts.get(k, 0) + 1
        elif sig["dated"]:
            dated_only += 1
        elif sig["kinds"]:
            instrument_only += 1

    return {
        "outcome": OBSERVED if matched else NONE_OBSERVED,
        "n": len(seen),
        "matched": len(matched),
        "kinds": dict(sorted(kind_counts.items())),
        # The headlines that fired, so a reader can check the rule instead of trusting it.
        "examples": [{"title": t, "kinds": k} for t, k in matched[:sample_cap]],
        # The near-misses, which are what a reader tuning the lexicon actually needs.
        "dated_only": dated_only,
        "instrument_only": instrument_only,
        "note": (
            "A headline counts when it names an instrument AND carries a date or reference "
            "number. `none_observed` means this rule found none in the headlines available "
            "— it is not a finding that the source publishes no official instruments, and it "
            "is never a judgement about whether the body behind it is a real institution."
        ),
    }


def lexicon_coverage() -> dict:
    """What the rule can and cannot see, published beside every result that uses it.

    It exists because the alternative is a silent negative: a source publishing decrees in a
    language this lexicon does not carry reads exactly like a source publishing none, and
    that asymmetry is precisely the equity failure the ruling is a response to.
    """
    return {
        "languages": list(LEXICON_LANGUAGES),
        "kinds": sorted(INSTRUMENT_WORDS),
        "terms": sum(len(v) for v in INSTRUMENT_WORDS.values()),
        "caveat": (
            "The instrument lexicon covers the languages listed here and is deliberately "
            "incomplete. A source whose headlines are in another language cannot be observed "
            "by this rule, and reads the same as one that publishes nothing — so a "
            "`none_observed` result for such a source says something about this lexicon, not "
            "about that source. Extending it needs someone who reads the language."
        ),
    }
