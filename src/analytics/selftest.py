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
    # 2026-06-23 field test: a ~35k bucket of digit-heavy CODE tokens (A-10C, internal
    # ids, model-variant cruft) leaked as keywords. They drop by letter<->digit
    # transition count (>= 2), while one-transition designations (a-10, f-18, g7) and
    # allowlisted real multi-transition terms (h1n1) survive. Non-vacuous: a real
    # designation MUST stay while the multi-segment code MUST go.
    Challenge(
        "digit_code_tokens_dropped",
        "multi-segment alphanumeric codes (A-10C, a1b2) are dropped; real designations stay",
        "The A-10C variant and the a1b2 sensor were tested; the A-10, the F-18 and the "
        "H1N1 response shaped the wider economy.",
        term=("a-10", "f-18", "economy"),
        absent=("a-10c", "A-10C", "a1b2"),
    ),
    Challenge(
        # 1h15 / 12h00 tokenise to h15 / h00 (the leading digit can't start a token);
        # the glued-digit-prefix rule drops these clock-time fragments.
        "clock_timecode_fragments_dropped",
        "clock timecodes (1h15, 12h00) do not leave h15/h00 keyword fragments",
        "The session opened at 1h15 and closed at 12h00 after a debate about elections.",
        term=("elections",),
        absent=("h15", "h00"),
    ),
    Challenge(
        # §2.6: an underscore inside a token = a CSS/template/code identifier (no natural
        # orthography uses a word-internal underscore), so it is dropped; real words — and
        # the BRAND token 'govdelivery' (ruling 2026-06-23 #4: brand/company tokens stay
        # content, never stoplisted) — stay. The gov-newsletter "?"-bucket junk is the
        # underscore template ids (dropped here) + undetected-English (the §2.6 langdetect),
        # NOT the brand name.
        "underscore_identifiers_dropped",
        "underscore code/template ids (gd_combo_table) drop; real words + the brand "
        "'govdelivery' (ruling #4) stay content",
        # ('newsletter' is now platform FURNITURE — 2026-07-01 open-class batch — so the
        # surviving content control is 'layout', not 'newsletter'.)
        "The govdelivery newsletter used a gd_combo_table layout while covering the elections.",
        term=("elections", "layout", "govdelivery"),
        absent=("gd_combo_table", "newsletter"),
    ),
    Challenge(
        "url_residue_not_tokenised",
        "tracker-URL residue (utm_source/mc_eid/path fragments) never becomes a keyword (2026-07-14)",
        "Read the full report at https://example.com/page?utm_source=newsletter&mc_eid=abc123def "
        "about the election and the economy.",
        term=("election", "economy"),
        absent=("utm_source", "mc_eid", "abc123def", "https"),
    ),
    Challenge(
        "accented_and_cta_caps_are_not_entities",
        "an accented-Latin all-caps shout (DÉCOUVREZ) and a CTA button word (PARTAGEZ) are terms, "
        "not acronym entities; a real ASCII acronym (NASA) still is (2026-07-14)",
        "DÉCOUVREZ our story and PARTAGEZ it now. The NASA mission continued over France.",
        entity=("NASA",),
        not_entity=("découvrez", "partagez"),
    ),
    Challenge(
        "repeated_token_ngram_dropped",
        "a repeated-token n-gram ('share share') is a chrome/CTA artifact, never a phrase (2026-07-14)",
        "Please share share share this article about the government budget and the new policy.",
        absent=("share share",),
    ),
    Challenge(
        # 2026-07-18 entity-families field export: FOTO/VIDEO/LIVE/INFO/PREMIUM/PDF/RSS
        # ranked among the top "entities" -- caps publishing/headline furniture passing
        # the acronym detector. A real acronym (NASA) still is one.
        "caps_furniture_not_entity",
        "publishing/headline furniture (FOTO, PDF, RSS) is not an entity; a real acronym still is",
        "Check the FOTO gallery and download the PDF. RSS feed available. NASA confirmed the launch.",
        entity=("NASA",),
        not_entity=("foto", "pdf", "rss"),
    ),
    Challenge(
        # Same export: pure Roman numerals (XIV, III) passed the all-caps rule too.
        "roman_numerals_not_entities",
        "pure Roman numerals (XIV, III, MMXXVI) are not entities",
        "Louis XIV ruled France. Pope John Paul III visited. The event drew MMXXVI attendees.",
        not_entity=("xiv", "iii", "mmxxvi"),
    ),
    Challenge(
        # Negative space the Roman-numeral rule must not swallow: a real acronym that
        # ALSO happens to be a well-formed Roman numeral stays an entity.
        "roman_numeral_acronym_allowlist_kept",
        "real acronyms that are also valid Roman numerals (LIV, DC, MD, CV) stay entities",
        "LIV Golf hosted a tournament. The DC branch confirmed it. Her MD credentials were "
        "verified. Send your CV today.",
        entity=("LIV", "DC", "MD", "CV"),
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

    # 4) OPT-IN lemmatization mechanism (P4.3): the lemmatizer conflates a morphological
    # variant (studied -> study) a plural heuristic misses, and the mislemma denylist
    # blocks a meaning-changer (media !-> medium). Checked DIRECTLY on _lemma() — no env
    # toggle, thread-safe in the live process — and only when the optional simplemma is
    # present (a core install simply omits this case; the feature is a no-op there).
    from src.analytics.families import _lemma, _simplemma

    if _simplemma is not None:
        lemma_fails: list[str] = []
        for word, lg, want_lemma in (("studied", "en", "study"), ("running", "en", "run"),
                                     ("Wahlen", "de", "wahl")):
            got = _lemma(word, lg)
            if got != want_lemma:
                lemma_fails.append(f"{word!r} ({lg}) -> {got!r}, expected {want_lemma!r}")
        for word in ("media", "data"):  # denylisted meaning-changers must stay unchanged
            if _lemma(word, "en") != word:
                lemma_fails.append(f"{word!r} is denylisted; must not lemmatize, got {_lemma(word, 'en')!r}")
        out.append(
            _result(
                "lemmatization_mechanism",
                "simplemma conflates study<-studied/running and the denylist blocks media!->medium",
                lemma_fails,
                "multi",
            )
        )

    # 5) OPTIONAL word segmentation ([segmentation] extra): a space-less script
    # (zh/ja/th) yields REAL words instead of one sentence-long junk token. Checked
    # only when that language's segmenter is installed — a core install omits the case
    # (the feature is a no-op there and the language stays honestly 'unsegmented').
    from src.analytics.extract import BaselineExtractor
    from src.analytics.segmentation import segmenter_available

    _seg_cases = [
        # (lang, text, a real content word that MUST survive, the whole sentence that must NOT be a keyword)
        ("zh", "中国政府今天宣布了新的经济政策。", "经济", "中国政府今天宣布了新的经济政策"),
        ("ja", "日本政府は新しい経済政策を発表した。", "経済", "日本政府は新しい経済政策を発表した"),
        ("th", "รัฐบาลไทยประกาศนโยบายเศรษฐกิจใหม่", "เศรษฐกิจ", None),
    ]
    for lang, text, want_term, junk in _seg_cases:
        if not segmenter_available(lang):
            continue  # a core install has no segmenter for this language — omit, never fail
        seg_terms = {t.normalized for t in BaselineExtractor().extract(text, language=lang) if t.kind == "term"}
        seg_fails: list[str] = []
        if want_term not in seg_terms:
            seg_fails.append(f"{lang}: expected the real word {want_term!r} among terms, got {sorted(seg_terms)[:8]}")
        if junk and junk in seg_terms:
            seg_fails.append(f"{lang}: the whole sentence {junk!r} must not survive as one keyword")
        out.append(
            _result(
                f"segmentation_{lang}",
                f"{lang}: word segmentation yields real words, not one sentence-long junk token",
                seg_fails,
                "multi",
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
