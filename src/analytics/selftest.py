"""Keyword pre-selection self-test — the maintainer's challenge harness.

A small, DECLARATIVE set of golden challenge cases that exercise the tricky
keyword-extraction decisions this project tuned — above all that the organisation
acronym ``WHO`` stays distinct from the pronoun ``who`` — plus the per-language
tweaks: German capitalised nouns are terms (not entities), a sentence-initial
capital is not an entity, the stopword/weekday batches filter junk, the
singular/plural family merge, cross-language equivalence rings, and the curated
baseline tags.

It runs the REAL pipeline the app uses (``BaselineExtractor`` / ``build_families`` /
``equivalence`` / ``baseline``) over each case and checks the outcome, so a
regression shows up immediately. ``run_keyword_selftest()`` returns an exportable
log (schema ``oo-selftest-1``); the in-app tool surfaces it at
``GET /api/diagnostics/keyword-selftest`` so the maintainer can run it and send the
results back for the next optimization round. It asserts known-good behaviour on
curated inputs — no DB, no network, no score, and it never edits data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Challenge:
    """One golden extraction case. The expectation tuples carry NORMALISED forms
    (an acronym stays UPPER-case, a term is lower-case)."""

    id: str
    guards: str  # the behaviour this case protects (human-readable)
    text: str = ""
    language: str = "en"
    entity: tuple[str, ...] = ()  # MUST be present AND kind=entity
    term: tuple[str, ...] = ()  # MUST be present AND kind=term
    not_entity: tuple[str, ...] = ()  # if present, MUST NOT be an entity (a term is fine)
    absent: tuple[str, ...] = ()  # MUST be filtered out entirely (stopwords / weekdays)


# The challenge set. Each line states, in data, exactly what behaviour it guards.
_CASES: tuple[Challenge, ...] = (
    Challenge(
        "who_vs_WHO",
        "the organisation WHO stays distinct from the pronoun who (case-preserved acronym)",
        "Experts at WHO met on a panel; afterwards they asked who really knew the risks.",
        entity=("WHO",),
        not_entity=("who",),
    ),
    Challenge(
        "us_survives_stopword",
        "the acronym US is kept, not lost to the stopword 'us'",
        "The US said it would act. The deal still mattered to the US and its allies.",
        entity=("US",),
        absent=("us",),
    ),
    Challenge(
        "german_nouns_are_terms",
        "German capitalises every noun, so none of these is a proper-name entity",
        "Die Behauptung war falsch. Die Medien berichteten ausführlich über Menschen und Belege.",
        language="de",
        not_entity=("behauptung", "medien", "menschen"),
    ),
    Challenge(
        "sentence_initial_not_entity",
        "a word capitalised only at a sentence start is not an entity",
        "Markets fell today. Traders worried about inflation and slowing growth.",
        not_entity=("markets",),
    ),
    Challenge(
        "digit_acronym_kept",
        "digit/hyphen acronyms (G7, COVID-19) are recognised as entities",
        "The G7 leaders met while COVID-19 cases rose again across the wider region.",
        entity=("G7", "COVID-19"),
    ),
    Challenge(
        "headline_caps_not_acronyms",
        "an all-caps headline run yields no acronym entities",
        "BREAKING NEWS REPORT: markets fell sharply as traders weighed the latest data.",
        not_entity=("BREAKING", "NEWS", "REPORT"),
    ),
    Challenge(
        "english_stopword_filtered",
        "a classic English function word ('that') is never collected",
        "The report said that the economy that everyone watched had quietly slowed.",
        absent=("that",),
    ),
    Challenge(
        "weekday_filtered",
        "weekday names are filtered (the 2026-06 batch covers every UI language)",
        "The summit opened on Tuesday and the decisive vote was finally held on Saturday.",
        absent=("tuesday", "saturday"),
    ),
    Challenge(
        "german_function_words_filtered",
        "German function words from the evidence batch are filtered (können, sondern)",
        "Wir können daran nichts ändern, sondern nur ruhig abwarten und sorgfältig weiterarbeiten.",
        language="de",
        absent=("können", "sondern"),
    ),
    # --- multilingual stopword / weekday coverage --------------------------------- #
    # The filters are a UNION applied to every language that has a stoplist, so the
    # self-test must challenge more than English. Each word below is verified-present
    # in global_stopwords(); a content noun in the sentence keeps the case non-vacuous.
    Challenge(
        "french_stopwords_and_weekdays",
        "French weekdays + function words are filtered",
        "Marchés en baisse mardi; chez le ministre, la réunion de samedi a été reportée.",
        language="fr",
        absent=("mardi", "samedi", "chez"),
    ),
    Challenge(
        "spanish_stopwords_and_weekdays",
        "Spanish weekdays + function words are filtered",
        "La reunión del sábado se aplazó, pero desde el miércoles nada cambió, aunque insistieron.",
        language="es",
        absent=("sábado", "miércoles", "pero", "desde", "aunque"),
    ),
    Challenge(
        "italian_stopwords_and_weekday",
        "Italian weekday + function word are filtered",
        "La riunione di sabato è stata rinviata perché mancavano ancora i dati ufficiali importanti.",
        language="it",
        absent=("sabato", "perché"),
    ),
    Challenge(
        "portuguese_stopwords_and_weekday",
        "Portuguese weekday + function words are filtered",
        "A reunião foi adiada porque faltavam dados, embora todos soubessem, no sábado de manhã.",
        language="pt",
        absent=("sábado", "porque", "embora"),
    ),
    Challenge(
        # NB: stoplists are by BASE form, so an inflected weekday ("среду") still
        # leaks — a real limitation in inflecting languages. We assert only the
        # function words actually present, to stay honest and non-vacuous.
        "russian_function_words",
        "Russian (Cyrillic) function words are filtered",
        "Совещание перенесли, чтобы успеть подготовить отчёт, которые все долго ждали.",
        language="ru",
        absent=("чтобы", "которые"),
    ),
    Challenge(
        "arabic_function_words",
        "Arabic (RTL, space-segmented) function words are filtered",
        "اجتمع القادة خلال الأسبوع. قبل القمة ناقشوا الاقتصاد. بعد النقاش الطويل اتفقوا.",
        language="ar",
        absent=("خلال", "قبل", "بعد"),
    ),
    Challenge(
        # "szombaton" (inflected) leaks; we assert the uninflected forms present.
        "hungarian_function_words_and_weekday",
        "Hungarian function words + an uninflected weekday are filtered",
        "A jelentés szerint a hétfő hivatalos ünnepnap, a fontos találkozó pedig végül elmarad.",
        language="hu",
        absent=("szerint", "pedig", "hétfő"),
    ),
    Challenge(
        "indonesian_function_words_and_weekdays",
        "Indonesian function words + weekdays are filtered",
        "Pertemuan dalam pekan ini diadakan oleh menteri pada Sabtu dan Minggu pagi.",
        language="id",
        absent=("dalam", "oleh", "sabtu", "minggu"),
    ),
    Challenge(
        "dutch_stopwords_and_weekdays",
        "Dutch weekdays + function word are filtered",
        "De vergadering van maandag werd uitgesteld omdat de cijfers op zaterdag nog ontbraken.",
        language="nl",
        absent=("maandag", "zaterdag", "omdat"),
    ),
    Challenge(
        # 2026-06-22 field test: hi/bn were UI languages but no_stoplist. Distinct
        # scripts -> the union is collision-free. A content noun is asserted as a term
        # so the case is NON-VACUOUS (it proves the script IS extracted AND the grammar
        # is filtered, not that nothing tokenised).
        "hindi_function_words_filtered",
        "Hindi (Devanagari) grammar words are filtered while a content noun survives",
        # The content noun survives = the Mn-matra tokenizer fix works (सरकार no longer
        # splits at the ा matra). The absent words are >=3 chars, so they prove the
        # STOPLIST (not the <3-char length filter): लिए / नहीं are in the hi block.
        "सरकार ने जनता के लिए यह फैसला नहीं बदला और नीति वही रही।",
        language="hi",
        term=("सरकार",),
        absent=("लिए", "नहीं"),
    ),
    Challenge(
        "bengali_function_words_filtered",
        "Bengali grammar words are filtered while a content noun survives",
        # করেছে / জন্য are >=3 chars and in the bn block -> they prove the stoplist;
        # সরকার surviving proves the Bengali matra/virama tokenizer fix.
        "সরকার নতুন নীতি ঘোষণা করেছে এবং জনগণের জন্য নয়।",
        language="bn",
        term=("সরকার",),
        absent=("করেছে", "জন্য"),
    ),
    Challenge(
        "spanish_sentence_initial_not_entity",
        "a Romance sentence-initial capital is a term, not an entity (Title-case is not a signal)",
        "Mercados cayeron ayer. Inversores temían una recesión y un crecimiento más lento.",
        language="es",
        not_entity=("mercados",),
    ),
    Challenge(
        # 2026-06-18 keyword-log: Greek was the largest no_stoplist language (4992
        # keywords of leaked grammar). Distinct script -> the union is collision-free.
        "greek_function_words_filtered",
        "Greek (distinct script) function words are filtered; content survives",
        "Ο πρωθυπουργός είπε ότι η κυβέρνηση δεν θα αλλάξει την πολιτική για την οικονομία.",
        language="el",
        absent=("και", "του", "ότι", "δεν", "την", "για"),
        term=("κυβέρνηση",),
    ),
    Challenge(
        "bulgarian_function_words_filtered",
        "Bulgarian (Cyrillic) function words are filtered; content survives",
        "Правителството заяви, че може да промени политиката, защото икономиката се забавя.",
        language="bg",
        absent=("като", "защото", "може", "това"),
    ),
    Challenge(
        # 2026-06-18 field finding: the elided article was kept whole ("l'assemblée"
        # was a keyword). De-elision makes the bare content word the keyword and
        # reduces "qu'il" to the stopword "il".
        "french_elision_is_stripped",
        "Romance elisions (l'/d'/qu') are not kept as part of a keyword",
        "L'Assemblée a voté la réforme. D'euros et qu'il faut. L'assemblée débat encore.",
        language="fr",
        term=("assemblée", "euros"),
        absent=("l'assemblée", "d'euros", "qu'il"),
    ),
    # 2026-06-22 field test, remainder batch: each newly-MANAGED language gets a
    # NON-VACUOUS guard — a content noun MUST survive (proves the script tokenises
    # whole words) AND a >=3-char grammar word MUST be filtered (proves the stoplist,
    # not the length filter). Distinct-script (fa/ur/uk) cannot collide; the Latin
    # ones use accented/long grammar so the union stays safe.
    Challenge(
        "persian_function_words_filtered",
        "Persian (Arabic script) grammar is filtered while a content noun survives",
        "دولت برای مردم سیاست اقتصادی را تغییر داد و رشد کرد.",
        language="fa", term=("سیاست",), absent=("برای", "این"),
    ),
    Challenge(
        "urdu_function_words_filtered",
        "Urdu (Arabic script) grammar is filtered while a content noun survives",
        "حکومت نے معیشت کی پالیسی تبدیل کرنے کا فیصلہ کیا، یہ آسان نہیں تھا۔",
        language="ur", term=("معیشت",), absent=("نہیں", "کیونکہ"),
    ),
    Challenge(
        "ukrainian_function_words_filtered",
        "Ukrainian (Cyrillic) grammar is filtered while a content noun survives",
        "Уряд змінить економічну політику країни, тому що ситуація триває.",
        language="uk", term=("політику",), absent=("тому", "коли"),
    ),
    Challenge(
        "romanian_function_words_filtered",
        "Romanian grammar (accented/long) is filtered while a content noun survives",
        "Guvernul va schimba politica economică deoarece situația continuă.",
        language="ro", term=("politica",), absent=("deoarece", "pentru"),
    ),
    Challenge(
        "czech_function_words_filtered",
        "Czech grammar (accented/long) is filtered while a content noun survives",
        "Vláda změní hospodářskou politiku, protože ekonomika zpomaluje.",
        language="cs", term=("politiku",), absent=("protože", "která"),
    ),
    Challenge(
        "slovak_function_words_filtered",
        "Slovak grammar (accented/long) is filtered while a content noun survives",
        "Vláda zmení hospodársku politiku, pretože ekonomika spomaľuje.",
        language="sk", term=("politiku",), absent=("pretože", "ktorý"),
    ),
    Challenge(
        "catalan_function_words_filtered",
        "Catalan grammar (accented/long) is filtered while a content noun survives",
        "El govern canviarà la política econòmica però la regió continua.",
        language="ca", term=("política",), absent=("però", "aquest"),
    ),
    Challenge(
        "swahili_function_words_filtered",
        "Swahili grammar (distinctive) is filtered while a content noun survives",
        "Serikali itabadilisha sera ya uchumi lakini hali katika nchi inaendelea.",
        language="sw", term=("uchumi",), absent=("lakini", "katika"),
    ),
    Challenge(
        "azerbaijani_function_words_filtered",
        "Azerbaijani grammar (accented) is filtered while a content noun survives",
        "Hökumət iqtisadi siyasəti dəyişəcək, çünki vəziyyət üçün davam edir.",
        language="az", term=("iqtisadi",), absent=("çünki", "üçün"),
    ),
    Challenge(
        "estonian_function_words_filtered",
        "Estonian grammar (accented/long) is filtered while a content noun survives",
        "Valitsus muudab majanduspoliitikat, sest olukord samuti halveneb.",
        language="et", term=("olukord",), absent=("sest", "samuti"),
    ),
    Challenge(
        "turkish_function_words_filtered",
        "Turkish grammar is filtered while a content noun survives (agglutinative)",
        "Hükümet ekonomik politikayı değiştirecek çünkü durum için kötüleşiyor.",
        language="tr", term=("ekonomik",), absent=("için", "çünkü"),
    ),
    Challenge(
        "finnish_function_words_filtered",
        "Finnish grammar is filtered while a content noun survives (agglutinative)",
        "Hallitus muuttaa talouspolitiikkaa, koska tilanne että jatkuu edelleen.",
        language="fi", term=("tilanne",), absent=("että", "koska"),
    ),
)


def _result(case_id: str, guards: str, fails: list[str], language: str = "—") -> dict:
    return {
        "id": case_id,
        "guards": guards,
        "language": language,
        "status": "pass" if not fails else "fail",
        "detail": fails,
    }


def _check_extraction(c: Challenge) -> list[str]:
    """Run the real extractor over one case and collect any expectation failures."""
    from src.analytics.extract import BaselineExtractor

    kind: dict[str, str] = {}
    for t in BaselineExtractor().extract(c.text, language=c.language):
        kind[t.normalized] = t.kind

    fails: list[str] = []
    for e in c.entity:
        got = kind.get(e)
        if got is None or got == "term":
            fails.append(f"{e!r} expected entity, got {got or 'absent'}")
    for t in c.term:
        if kind.get(t) != "term":
            fails.append(f"{t!r} expected term, got {kind.get(t) or 'absent'}")
    for ne in c.not_entity:
        got = kind.get(ne)
        if got is not None and got != "term":
            fails.append(f"{ne!r} must not be an entity, got {got}")
    for a in c.absent:
        if a in kind:
            fails.append(f"{a!r} expected to be filtered, present as {kind[a]}")
    return fails


def _check_structural() -> list[dict]:
    """The cross-keyword behaviours that aren't a single-text extraction:
    family merge, equivalence rings, and curated baseline tags."""
    out: list[dict] = []

    # 1) singular/plural family merge (state + states -> one family)
    from src.analytics.families import build_families

    fams = build_families(
        [
            {"normalized": "state", "term": "state", "kind": "term", "mentions": 80},
            {"normalized": "states", "term": "states", "kind": "term", "mentions": 40},
        ]
    )
    merged = any({"state", "states"} <= {m["normalized"] for m in f.members} for f in fams)
    out.append(
        _result(
            "plural_family_merge",
            "singular/plural collapse into one family (state + states)",
            [] if merged else ["state and states did not merge into one family"],
        )
    )

    # 2) cross-language equivalence ring (election / élection / wahl -> one ring)
    from src.analytics.equivalence import ring_of

    rings = {ring_of("en", "election"), ring_of("fr", "élection"), ring_of("de", "wahl")}
    ring_ok = len(rings) == 1 and None not in rings
    out.append(
        _result(
            "equivalence_ring",
            "election / élection / wahl resolve to one cross-language ring",
            [] if ring_ok else [f"expected one shared ring, got {sorted(str(r) for r in rings)}"],
        )
    )

    # 3) curated baseline pre-tags a known keyword (election -> type:event, topic:politics)
    from src.analytics.baseline import baseline_tags

    tags = dict(baseline_tags("en", "election"))
    want = {"type": "event", "topic": "politics"}
    out.append(
        _result(
            "baseline_tag_applied",
            "the curated baseline pre-tags a known keyword (election)",
            [] if tags == want else [f"expected {want}, got {tags}"],
        )
    )
    return out


def run_keyword_selftest() -> dict:
    """Run the whole challenge harness and return an exportable log (oo-selftest-1)."""
    cases: list[dict] = [_result(c.id, c.guards, _check_extraction(c), c.language) for c in _CASES]
    cases.extend(_check_structural())
    passed = sum(1 for c in cases if c["status"] == "pass")
    return {
        "kind": "keyword-selftest",
        "schema": "oo-selftest-1",
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {"total": len(cases), "passed": passed, "failed": len(cases) - passed},
        "cases": cases,
    }
