"""
Tests for keyword/entity extraction (baseline).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the honesty-relevant behaviour: multi-word entities are one unit, a
gazetteer assigns person/org/location kinds (else the generic "entity"),
sentence-initial capitalisation isn't mistaken for an entity, topical n-gram
terms carry counts + first offsets, and offsets actually point at the term.
"""

from __future__ import annotations

from src.analytics.extract import BaselineExtractor, ExtractedTerm, get_extractor


def _by_norm(terms: list[ExtractedTerm]) -> dict[str, ExtractedTerm]:
    return {t.normalized: t for t in terms}


def test_multiword_titlecase_is_a_term_not_an_entity():
    # Title-Case is no longer an entity signal (anglocentric; breaks for German).
    # A multi-word name is captured as ONE topical TERM, offset intact; it becomes
    # a real entity only via the gazetteer / spaCy (see the gazetteer test below).
    text = (
        "Emmanuel Macron met advisers in the capital. "
        "Emmanuel Macron then addressed reporters about the economy."
    )
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "emmanuel macron" in by
    ent = by["emmanuel macron"]
    assert ent.kind == "term"  # Title-Case alone never makes an entity now
    assert ent.count == 2
    assert text[ent.first_offset : ent.first_offset + len("Emmanuel Macron")] == "Emmanuel Macron"


def test_gazetteer_promotes_a_term_to_its_entity_kind():
    # Named entities come from the gazetteer now, not capitalisation: "rio tinto"
    # is a term that the gazetteer promotes to kind="org".
    text = "Rio Tinto reported output. Rio Tinto shares moved on the news today."
    ex = BaselineExtractor(gazetteer={"rio tinto": "org"})
    by = _by_norm(ex.extract(text))
    assert by["rio tinto"].kind == "org"


def test_sentence_initial_capital_not_an_entity():
    # "Markets" only ever appears capitalised at sentence start -> not an entity.
    text = "Markets fell today. Traders worried about inflation and slowing growth."
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "markets" not in {k for k, v in by.items() if v.kind != "term"}


def test_acronym_is_an_entity_distinct_from_its_lowercase_homograph():
    # The WHO/Who problem: "WHO" (org) is an entity kept case-distinct from the
    # pronoun "who" — casefolding would merge them, so we don't.
    text = "Experts at WHO met on Friday. They asked who knew the risks beforehand."
    by = _by_norm(BaselineExtractor().extract(text))
    assert "WHO" in by and by["WHO"].kind == "entity"
    assert "who" not in {k for k, v in by.items() if v.kind != "term"}


def test_stopword_homograph_acronym_survives():
    # "US" must not vanish into the stopword "us": its case is preserved.
    text = "The US said it would act. The deal still mattered to the US and allies."
    by = _by_norm(BaselineExtractor().extract(text))
    assert "US" in by and by["US"].kind == "entity"


def test_german_capitalised_nouns_are_not_entities():
    # German capitalises every noun; none here is a proper name -> all terms.
    text = "Die Behauptung war falsch. Die Medien berichteten ausführlich über Menschen und Belege."
    by = _by_norm(BaselineExtractor().extract(text, language="de"))
    assert not [k for k, v in by.items() if v.kind != "term"]


def test_all_caps_headline_words_are_not_acronyms():
    # In an ALL-CAPS headline every word is caps -> none stands out as an acronym.
    text = "BREAKING NEWS REPORT: markets fell sharply as traders worried about the economy."
    by = _by_norm(BaselineExtractor().extract(text))
    ents = {k for k, v in by.items() if v.kind != "term"}
    assert not ({"BREAKING", "NEWS", "REPORT"} & ents)


def test_terms_have_counts_and_offsets():
    text = (
        "Climate policy dominated the summit. Climate policy negotiators "
        "debated climate targets and emissions for hours on end today."
    )
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "climate" in by and by["climate"].kind == "term"
    assert by["climate"].count >= 3
    # A bigram phrase is captured as a single term.
    assert "climate policy" in by and by["climate policy"].count >= 2
    off = by["climate"].first_offset
    assert text[off : off + 7].lower() == "climate"


def test_stopword_bounded_ngrams_are_dropped():
    text = "The cost of the project rose. The team reviewed the plan of the office."
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    # No phrase should start or end with a stopword.
    assert "of the" not in by
    assert not any(
        t.term.split()[0] in {"the", "of"}
        for t in ex.extract(text)
        if t.kind == "term" and " " in t.term
    )


def test_romance_elision_is_stripped_from_terms():
    """l'assemblée -> assemblée (not the whole "l'assemblée"); qu'il -> the stopword
    "il" (dropped); d'euros -> euros. The elided article/pronoun is tokenization
    noise, so it must never become part of a keyword (field finding 2026-06-18)."""
    text = "L'Assemblée nationale a voté la réforme. D'euros et qu'il faut. L'assemblée débat."
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "assemblée" in by
    # `d'euros` -> `euros` is the ELISION claim this test makes, and it still holds: the
    # DISPLAY term is `euros`. The KEY is the lemma `euro` since 2026-09-17 (Q416 = a,
    # lemmatisation at extraction), which is a different rule in a different layer -- so
    # this asserts the elision on the surface form and names the lemma rather than
    # silently depending on whichever one the key happens to be.
    assert "euro" in by and by["euro"].term == "euros"
    assert "d'euros" not in by and "'euros" not in by
    # The contracted forms must NOT survive as keywords.
    assert "l'assemblée" not in by and "d'euros" not in by and "qu'il" not in by
    # And the de-elided form feeds the n-grams.
    assert "assemblée nationale" in by


def test_empty_text_yields_nothing():
    assert BaselineExtractor().extract("") == []
    assert BaselineExtractor().extract("   ") == []


def test_get_extractor_spacy_falls_back_when_absent():
    # spaCy isn't installed in the core test env -> must fall back to baseline,
    # never raise.
    ex = get_extractor("spacy")
    assert ex.name == "baseline"
    assert isinstance(ex, BaselineExtractor)


def test_2026_07_01_korean_marathi_stopword_batch_is_collision_free():
    """The 2026-07-01 keyword-log batch added Korean (Hangul) + Marathi (Devanagari)
    grammar to the language-agnostic stopword union. Distinct scripts -> collision-free:
    the batch words are filtered, but CONTENT (incl. the deliberately-excluded mr words)
    and any ASCII/Latin token are untouched, so no other-language content is hidden."""
    from src.analytics.extract import global_stopwords

    gs = global_stopwords()
    # grammar/connectives are now filtered
    for w in ("하지만", "그러나", "따라서", "때문에", "आहे", "आणि", "नाही", "होते"):
        assert w in gs, w
    # CONTENT stays a keyword: the mr words we deliberately EXCLUDED + a ko content noun
    for w in ("반도체", "जात", "कोटी", "माहिती", "कमी"):
        assert w not in gs, w
    # the batch is DISTINCT-SCRIPT only: it added no ASCII token, so no Latin-corpus
    # content word (e.g. English 'man'/'tag'/'state') can be hidden by it.
    added = set("공동으로 관계없이 하지만 그러나 आहे आणि नाही होते".split())
    assert all(not any(ord(c) < 128 for c in w) for w in added)
    for latin_content in ("man", "tag", "state", "time", "premier", "grande", "parte"):
        # these were NOT in the batch; the guard is that the batch can't touch them
        assert latin_content not in added


def test_2026_08_11_english_light_verb_batch_and_the_words_it_refused():
    """The source-quality export of 2026-08-11 showed 41.9% of source fingerprints (101 of
    the 241 carrying one) spending a top-12 slot on a contentless English word. This batch
    globalises those -- and the REFUSALS are the load-bearing half.

    ``global_stopwords()`` unions every ``configs/stopwords_extra/*.yml`` file
    LANGUAGE-AGNOSTICALLY, so a word that is content in ANY corpus language (or in another
    English sense) must never be added. Eight observed leaks were therefore rejected: nl
    ``top`` = summit, de/nl ``Post`` = mail, de ``Show`` = a programme, ``access``/``home``/
    ``life`` are content in their own right, ``right``/``left`` are political direction in a
    news corpus, and ``put`` is a finance term (the corpus carries finance.yahoo.com).
    Without this negative half a later session re-reads the same fingerprint export, sees
    ``top``/``post``/``left`` leaking exactly as loudly, and globalises them -- the whole
    open-class trap the 2026-07-01 #530 lesson names. Reasoning: PROVENANCE.md.
    """
    from src.analytics.extract import global_stopwords

    gs = global_stopwords()
    for w in ("added", "best", "down", "end", "every", "find", "hours", "look", "read",
              "set", "went"):
        assert w in gs, f"{w} was added by the 2026-08-11 batch"
    for w in ("top", "post", "show", "access", "home", "right", "left", "life", "put"):
        assert w not in gs, (
            f"{w!r} was DELIBERATELY refused by the 2026-08-11 collision review -- it is "
            f"content in some corpus language or English sense. If you are adding it on "
            f"purpose, update PROVENANCE.md's rejection table with the evidence first."
        )


def test_extra_stopwords_migration_is_byte_identical_to_the_pre_migration_blob():
    """Phase 4.1 (PR #740/#744 remediation) replaced the 370-line in-Python
    ``_EXTRA_STOPWORD_TEXT`` string blob with a loader over
    ``configs/stopwords_extra/<lang>.yml`` data files. That was declared a
    REPRESENTATION change only -- the acceptance bar is that the resulting
    ``_EXTRA_STOPWORDS`` frozenset (after the curly-apostrophe contraction
    expansion the module already applies) is byte-identical to the set the old
    blob produced. The digest below was computed once, directly from
    ``origin/main``'s pre-migration ``_EXTRA_STOPWORD_TEXT`` via AST
    (``ast.literal_eval``, never a hand-transcription) plus the SAME
    curly-apostrophe expansion the module performs, over the sorted,
    newline-joined member set -- so any accidental drop, duplication, or the
    YAML-1.1-boolean-scalar trap (PyYAML's safe_load silently turning an
    unquoted ``no``/``yes``/``on``/``off``/``true``/``false`` list item into a
    Python bool instead of a string -- a real bug caught by this exact check
    during the migration) reddens this test immediately.
    """
    import hashlib

    from src.analytics.extract import _EXTRA_STOPWORDS

    # Every member must be a str: the YAML-boolean-coercion regression guard.
    assert all(isinstance(w, str) for w in _EXTRA_STOPWORDS)

    # Words deliberately ADDED to the data files SINCE the migration. The migration digest
    # below is taken over the set MINUS these, so the original "representation change only"
    # guarantee stays provable forever instead of being re-baselined away by the first
    # legitimate addition -- and every later batch has to declare itself HERE rather than be
    # absorbed into a fresh digest, where a genuine accidental drop would hide beside it.
    added_since_migration = frozenset({
        # source-quality export 2026-08-11: contentless English light verbs / quantifiers
        # occupying a top-12 slot in 41.9% of source fingerprints.
        # Evidence + the collision review that REJECTED top/post/show/access/home/right/
        # left/life/put: configs/stopwords_extra/PROVENANCE.md.
        "added", "best", "down", "end", "every", "find", "hours", "look", "read", "set",
        "went",
        # R102 / D24, the maintainer's answer 12 = a (2026-09-30): German "all" and Spanish
        # "are" stay hidden in their own language (they are in the vendored English list but
        # were not in the extras union); English "bio" and "uno" went into en.yml too but
        # other files already held them.
        "all", "are",
        # stoplist batch 1 (2026-10-06): LaTeX macros and boilerplate in en, markup debris and
        # keyboard noise in ko; evidence in configs/stopwords_extra/PROVENANCE.md.
        "crossref", "fig", "likelyno7", "mathbb", "mathbf", "mathcal", "mathrm",
        "supplementary",
        "addclass", "attr", "cssclip", "dhmkkh", "dhmkkhh", "encodeuricomponent",
        "pclassname", "pdesc", "pmurl", "ppurl",
        # stoplist batch 2 (2026-10-13, R131, language group 1: de fr es it pt nl sv da ca nb): function words,
        # number and month words, and site chrome the triage called noise twice, kept only where the log shows no
        # other-language content sense; evidence in configs/stopwords_extra/PROVENANCE.md.
        "11a", "abo", "abonner", "abonneret", "abonnieren", "abstractfr", "achteren'", "agost", "ahir",
        "ait", "alcun", "alcune", "algum", "alguém", "algú", "all'11", "allemaal", "alsof", "anders'",
        "angesichts", "anmelden", "anzi", "apontou", "artikeldel", "artikeltyp", "assinante", "attualita'",
        "aucun", "aufgrund", "aufs", "augusti", "auprès", "auraient", "aurait", "autour", "avais", "avons",
        "avonturenmachine'", "ayant", "bedriftsannonse", "bevor", "både", "bé'", "bör", "cela", "chacun",
        "ciento", "cinc", "contre", "cookieverklaring", "cuya", "daarbij", "daarmee", "daarnaast",
        "daarvoor", "damunt", "dani'", "dankzij", "davant", "delen'", "dell'", "dell'11", "dell'8", "den'",
        "derrière", "dertien", "dessutom", "desto", "det'", "devant", "dezelfde", "dezembro", "dieci",
        "dijous", "dilluns", "dimarts", "dimecres", "dissabte", "disso", "diumenge", "divendres",
        "dobbeltfejl'", "doordat", "dotze", "dès", "dürfte", "elkaar", "ell", "emotioneel'", "entro",
        "envers", "eraan", "erbij", "erop", "ervan", "ervoor", "eux", "eva'", "familia'", "femte", "foruden",
        "fos", "fredagen", "fut", "följ", "fødselsdagen'", "fürs", "george'", "hagenallerede", "hagin",
        "hauria", "haurien", "haurà", "havien", "helskärmslägeannonstekniskt", "helvede'", "hinanden",
        "hinaus", "hingegen", "hinzufügen", "hoeveel", "hors", "horse'", "hos", "hundert", "hverken",
        "hvilke", "hvilket", "ifrån", "ifølgje", "igennem", "igjennom", "ik'", "imens", "imod", "inden",
        "indtil", "inloggen", "innerhalb", "iria", "is'", "julho", "juliol", "junho", "juny", "jährig",
        "jährigen", "karlsenallerede", "ketportret'", "klicka", "knappen", "kring", "kunnet", "könne",
        "könnten", "leestijd", "lequel", "lesezeit", "liefdesbrief'", "ligesom", "lijn'", "lolita'",
        "lorsque", "längs", "lördag", "lördagen", "maand", "maig", "maj", "malgré", "marts", "març", "março",
        "mehreren", "mellem", "menn22", "mennesker'", "mese", "mil", "milers", "miljard", "miljoen",
        "miljoner", "mille", "milliarde", "millionen", "millón", "mim", "minuts'", "mois", "molte", "monat",
        "muligt'", "måndagen", "müsse", "naast", "nenhum", "ninguém", "ningú", "novembro", "nu'", "nueve",
        "obwohl", "olie'", "omkring", "online'", "outubro", "ovvero", "parmi", "pisuerga'", "port'", "porém",
        "pourquoi", "pra", "prenumerant", "presso", "probleem'", "prozent", "qu'", "qualsevol", "quand",
        "quei", "quel", "registrieren", "requiem'", "rere", "rien", "rivalerne'", "rolig'", "runt",
        "résuméen", "résuméfr", "samme", "samt", "sauf", "segons", "selvom", "semaine", "serait", "serem",
        "serà", "setembre", "setembro", "seues", "sidenoppdatert", "siguin", "sinó", "site'", "själva",
        "soient", "solle", "syv", "sånne", "såväl", "söndag", "söndagen", "søndag13", "tausend", "terem",
        "textrobotdenna", "textrobottextredaktionens", "tienduizenden", "today11", "torsdagen", "tothom",
        "trods", "trotz", "trás", "twaalf", "twee'", "twintig", "udvekslingspraktikant'", "ukendt'", "ums",
        "unserem", "unseren", "uppdatera", "utifrån", "varandra", "vecka", "vegetaren'", "vijftien", "vint",
        "vissa", "vore", "vuit", "vóór", "waarbij", "waardoor", "waarin", "waarmee", "waarna", "waaronder",
        "waarop", "waarvan", "weder", "wobei", "woche", "wären", "zesde", "zijn'", "zowel", "zufolge",
        "årig", "étaient", "étais", "étant", "één", "êtes",
        # and the curly-apostrophe spelling of each apostrophe word above, which the module adds on load.
        "achteren’", "all’11", "anders’", "attualita’", "avonturenmachine’", "bé’", "dani’", "delen’",
        "dell’", "dell’11", "dell’8", "den’", "det’", "dobbeltfejl’", "emotioneel’", "eva’", "familia’",
        "fødselsdagen’", "george’", "helvede’", "horse’", "ik’", "is’", "ketportret’", "liefdesbrief’",
        "lijn’", "lolita’", "mennesker’", "minuts’", "muligt’", "nu’", "olie’", "online’", "pisuerga’",
        "port’", "probleem’", "qu’", "requiem’", "rivalerne’", "rolig’", "site’", "twee’",
        "udvekslingspraktikant’", "ukendt’", "vegetaren’", "zijn’",
        # stoplist batch 3 (2026-10-13, R131, language group 2: ru uk pl cs sk sl): function words, number and
        # month words, reporting verbs and site chrome the triage called noise twice, kept only where the log
        # shows no other-language content sense; evidence in configs/stopwords_extra/PROVENANCE.md.
        "akoby", "ampak", "aprila", "buď", "bych", "bychom", "bądź", "będziemy", "czego", "cztery", "czym",
        "czytaj", "desať", "deseti", "desetih", "dle", "dodaj", "dvaja", "dveh", "dvema", "dvoch",
        "dvou", "dvěma", "dzięki", "díky", "iskanja", "izmed", "jakim", "jaké", "jaký", "jakým",
        "jaką", "jednej", "jejích", "jejího", "jejím", "jejíž", "jenže", "jesteśmy", "junija", "júla",
        "júni", "kakšen", "katere", "katerem", "kateri", "katerih", "katero", "każda", "każdej", "każdym",
        "každou", "kdyby", "keby", "kedy", "kljub", "koho", "kolem", "koľko", "kterého", "kterém", "kterých",
        "kterým", "ktorom", "ktorého", "ktorému", "którą", "kvôli", "kým", "ledna", "lenže", "lipca",
        "lipcu", "ljudstva'", "metrů", "miliard", "miliardy", "milijona", "milijonov", "milionů",
        "mld", "mln", "mája", "namiesto", "namreč", "nanj", "napriek", "napísal", "naszej", "naszym",
        "naszą", "naň", "našem", "našich", "našo", "naší", "nebol", "nebola", "nedeljo", "nedeľu", "neděli",
        "nejen", "nichž", "niedzielę", "niekto", "niektorí", "nihče", "nikdo", "nikogo", "nikt", "nikto",
        "nisem", "niso", "nista", "njegovi", "njimi", "něj", "někoho", "některé", "některých", "někteří",
        "něm", "němž", "obou", "obu", "obě", "odkar", "odkud", "ohledně", "okolo", "okrem", "oproti", "osem",
        "osiem", "ovšem", "oziroma", "pač", "października", "piatich", "piatok", "pięć", "poblíž",
        "pomiędzy", "pomocou", "pomocí", "pondělí", "poprzez", "počas", "preden", "prek", "pričom", "proc",
        "proti", "przeciwko", "pátek", "päť", "pěti", "přece", "přesto", "přitom", "samego", "seboj",
        "sebou", "sedem", "sedmi", "siebie", "sierpnia", "skoro", "soboto", "sobotu", "sobotę", "sobě",
        "sredo", "srpna", "srpnu", "svojega", "svojej", "svojem", "svoji", "svojo", "svojom", "svou",
        "svého", "svém", "swoich", "swoim", "swojego", "swojej", "swoją", "sześciu", "sześć", "sám", "síce",
        "takiej", "takim", "taką", "temveč", "tisoč", "tistem", "tisíc", "torej", "totiž", "treh", "trije",
        "trzech", "trzy", "tysięcy", "týchto", "těch", "těchto", "třicet", "uviedla", "uviedol", "voči",
        "vraj", "vsako", "vseh", "vsem", "vsemi", "včetně", "všech", "všechny", "všem", "všetkých", "vůči",
        "wobec", "wokół", "września", "wyślij", "zamiast", "zanim", "zanj", "zarówno", "zatem", "zobraziť",
        "zoper", "zostanie", "zostało", "září", "złotych", "čem", "čeprav", "června", "červnu", "česar",
        "čimer", "čosi", "čtvrtek", "čtyř", "čím", "čímž", "října", "środę", "šestih", "šesť", "štirih",
        "štvrtok", "štyri", "štyrmi", "štyroch", "žiadne", "žádné", "žádný", "аби", "августе", "апреле",
        "буде", "будуть", "біля", "вашей", "вересня", "внаслідок", "внутри", "возле", "всій", "всім",
        "вісім", "грн", "грудня", "двома", "двох", "двоє", "двумя", "дві", "деякі", "додав", "доки",
        "жовтні", "жодного", "завдяки", "задля", "зазначив", "заради", "заявив", "згідно", "июле", "йому",
        "каждого", "какие", "которое", "крім", "кілометрів", "липні", "любой", "мене", "мені", "месяц",
        "метрів", "миллиард", "миллион", "млн", "млрд", "нагадаємо", "наголосив", "назвав", "нашего",
        "нашим", "нашої", "наші", "неделя", "нею", "неї", "нього", "ніж", "ніхто", "однак", "окрім",
        "октябре", "оскільки", "поблизу", "повідомив", "повідомили", "подписаться", "поки", "помимо",
        "понад", "попри", "поскольку", "потім", "поэтому", "проте", "проти", "протягом", "саме", "самих",
        "самому", "самі", "свого", "своє", "своєму", "своєї", "свої", "своїх", "сентябре", "серед", "серпні",
        "сказав", "собою", "собі", "среди", "суботу", "сім", "січня", "таке", "таким", "такої", "таку",
        "такі", "теж", "тижня", "тис", "тисяч", "тисячі", "тих", "травня", "троє", "трьох", "тысяча",
        "тільки", "унаслідок", "усе", "усі", "усім", "усіх", "феврале", "хтось", "цим", "цими", "цих",
        "цьому", "цій", "цією", "цієї", "чей", "чим", "читайте", "чотири", "чотирьох", "шість", "щодо",
        "щось", "яка", "якби", "яке", "яким", "якими", "яких", "якого", "якому", "яку", "іншого", "їхню",
        "їхня", "їхні", "їхній",
        # and the curly-apostrophe spelling of each apostrophe word of batch 3, which the module adds on load.
        "ljudstva’",
        # stoplist batch 4 (2026-10-13, R131, language group 3: sr bg el): function words, number and month
        # words and site chrome the triage called noise twice, kept only where the log shows no other-language
        # content sense; evidence in configs/stopwords_extra/PROVENANCE.md (the curly spelling of an apostrophe
        # word is listed beside the straight one).
        "avgusta", "bili", "biće", "bude", "budu", "deset", "devet", "drugih", "duž", "dva", "dve",
        "hiljada", "iako", "ispred", "jeste", "jula", "kad", "koga", "koje", "kojeg", "kojem", "koji",
        "kojih", "kojim", "kojoj", "koju", "koliko", "mene", "meni", "među", "međutim", "miliona",
        "moja", "moje", "najčitanije", "naša", "naše", "našeg", "naši", "naših", "našim", "našoj", "našu",
        "nedelju", "nego", "neke", "neki", "nekih", "neko", "neće", "nešto", "nijesu", "nisam", "nismo",
        "nisu", "njega", "njegov", "njegova", "njegove", "njegovim", "njemu", "njen", "njene", "njih",
        "njihove", "njima", "nju", "odnosno", "odsto", "oktobar", "oktobra", "onaj", "onih", "osam", "osim",
        "ovih", "ovim", "ovog", "ovom", "ovu", "podeli", "pogledajte", "poput", "pored", "posle", "poslije",
        "povodom", "pošto", "pratite", "pre", "pred", "pretplatite", "pridružite", "prije", "prilikom",
        "pročitaj", "sebe", "sedam", "septembra", "svaka", "svi", "svih", "svim", "svima", "svog", "svoje",
        "svojih", "svojim", "svojoj", "svoju", "svom", "takva", "takve", "tih", "toj", "tvoje",
        "ukoliko", "umesto", "unutar", "uoči", "uprkos", "vam", "zato", "ćemo", "čega", "čemu", "četiri",
        "čija", "čiji", "čim", "čime", "šest", "άλλο", "άλλοι", "άλλους", "άλλων", "άρα", "έναντι", "έξι",
        "έχω", "έως", "ανά", "ανάμεσα", "αντί", "απ'", "απέναντι", "απ’", "αυγούστου", "αυτά", "αυτές",
        "αυτήν", "αυτής", "αυτοί", "αυτού", "αυτόν", "αυτός", "αυτών", "αφού", "γιατί", "δέκα", "δευτέρας",
        "δηλαδή", "δισ", "διότι", "δυο", "δύο", "εάν", "είμαι", "είμαστε", "είτε", "είχα", "είχαν", "εγώ",
        "εκατ", "εκείνη", "εκτός", "εμείς", "εναντίον", "εντός", "επειδή", "επτά", "εφόσον", "ιουλίου",
        "κάθε", "κάποια", "καθ'", "καθ’", "καμία", "καν", "κανείς", "κατ'", "κατ’", "κυριακή", "κυριακής",
        "λοιπόν", "λόγω", "μένα", "μέσω", "μέχρι", "οκτωβρίου", "οκτώ", "οποίες", "οποίοι", "οποίος",
        "οποίων", "οπότε", "ούτε", "πάρα", "πέμπτη", "πέντε", "παρ'", "παρασκευή", "παρ’", "πού",
        "προκειμένου", "πόσο", "πότε", "πώς", "σάββατο", "σαββάτου", "σεπτεμβρίου", "τέσσερα", "τέσσερις",
        "τίποτα", "τρία", "τρεις", "τριών", "υπέρ", "χωρίς", "ωστόσο", "όλες", "όλη", "όλων", "όμως",
        "όπου", "όσα", "όσο", "όσοι", "όσον", "όσους", "όσων", "όχι", "ώστε", "ама", "април", "бих", "биха",
        "бях", "бяхме", "вашата", "влезете", "девет", "декември", "десет", "едни", "извън", "какви",
        "когото", "милиона", "моята", "нали", "нашите", "нашия", "нашият", "неговите", "негово", "нека",
        "октомври", "онова", "относно", "пет", "петък", "понеделник", "самият", "своето", "своите", "своя",
        "своята", "септември", "спрямо", "сряда", "събота", "такова", "трима", "февруари", "четири",
        "чиито", "чиято", "щеше", "юли", "юни", "януари",
        # stoplist batch 5 (2026-10-13, R131, language group 4: id ms tl): function words, number words, month
        # and weekday names, "tomorrow" and apostrophe debris the triage called noise twice, kept only where the log shows no
        # other-language content sense; evidence in configs/stopwords_extra/PROVENANCE.md.
        "adakah", "agustus", "ahad", "alas-11", "alas-12", "alas-5", "alas-6", "alas-7", "alas-8", "alas-9",
        "anumang", "apabila", "apat", "ataupun", "bagaimanapun", "bahawa", "bawat", "beliau", "berapa",
        "berkata", "besok", "bilion", "biyernes", "boleh", "bukan", "comel'", "comel’", "dahil", "daripada",
        "delapan", "enam", "guru'", "guru’", "habang", "halo'", "halo’", "hanggang", "hingga",
        "hinggil", "iaitu", "ika-166", "ika-24", "ilang", "isang", "isnin", "julai", "juta", "kahit",
        "kalau", "kanilang", "kanyang", "kapag", "kaysa", "ke-10", "ke-11", "ke-12", "ke-14", "ke-15",
        "ke-16", "ke-18", "ke-19", "ke-20", "ke-34", "ke-47", "ke-51", "ke-65", "ke-7", "ke-73",
        "ke-90", "kelapan", "kemudian", "kepada", "kerana", "ketika", "lamang", "lantaran",
        "manakala", "maret", "memandangkan", "menerusi", "mengenai", "menurut", "mga", "miliar", "namun",
        "ngunit", "nitong", "niya", "niyang", "noong", "ogos", "puluh", "ribu", "rm11", "rm23",
        "rm28", "rm32", "rm39", "rm400", "rm600", "rm610", "rp10", "rp100", "rp12", "rp15", "rp17", "rp18",
        "rp2", "rp22", "rp23", "rp231", "rp25", "rp3", "rp314", "rp5", "rp500", "rp56", "rp6", "rp62",
        "rp7", "sahaja", "samantala", "sebelum", "sebuah", "seeding'", "seeding’", "sehingga", "sejak",
        "sejuta", "sekitar", "selagi", "selain", "selepas", "seorang", "sepanjang", "seperti", "serta",
        "sesuatu", "setyembre", "sih", "siyam", "supaya", "tersebut", "tiga", "tujuh", "tungkol", "ujarnya",
        "upang", "vibe'", "vibe’", "walong",
        # stoplist batch 6 (2026-10-13, R131, language group 5: ja ko zh): boilerplate lines, function words,
        # weekday names, reporting verbs and number debris the triage called noise twice; fragments, names and
        # mojibake left out; evidence in configs/stopwords_extra/PROVENANCE.md.
        "aiの特性上", "facebookxblueskycopy", "mail帳號", "spotifyで聴く", "xlinefacebookemailprint", "あらかじめご了承ください",
        "あらかじめ御了承ください", "おくやみ情報もいち早く", "お問い合わせ", "お問い合わせフォームよりご連絡ください", "お問合せ", "お楽しみに", "お申し込み", "お知らせ",
        "お試し", "お送りする内容は", "きょう", "こうした中", "こちらからお聴きください", "こちらのメディアもお役に立てるかもしれません", "この続きでは",
        "この記事に載せきれなかった画像を一覧でご覧いただけます", "この記事の画像", "この記事の著者", "この記事は有料会員限定です", "この記事を共有する", "これは", "これを受け",
        "こんなメディアも見られています", "ご不明な点がございましたら", "ご了承ください", "ご案内", "ご遺族の方からのご連絡をお受けします", "さらにスタンダードプランなら", "すると",
        "そこで", "そのため", "それでも", "それは", "そんな", "だから", "だった", "つまり", "であり", "である", "でした", "ではなく", "ところが",
        "とした上で", "とはいえ", "とコメントしています", "と伝えた", "と呼びかけた", "と報告", "と強調した", "と明かした", "と訴え", "と訴えた", "と話した",
        "と話していた", "と話していました", "と話す", "と語った", "と語り", "と説明した", "と述べ", "と述べた", "と述べました", "によると",
        "のスタンダードプラン会員", "の最新記事をトップページに表示", "よくある質問", "よく一緒に読まれている記事", "より一部抜粋してお届けする", "をクリック", "を発表した",
        "を発表しました", "イベントなど速報でとちぎの", "インターネット放送でも同時配信します", "イントネーションで再生される場合がありますので", "オススメ",
        "キャリア会員はコース変更をお願いします", "ギャラリーページはこちら", "クリップ機能は有料会員の方のみお使いいただけます",
        "クレジットカード決済会員は新コースに自動移行するので特に作業は不要です", "サービス内容や料金をもっと詳しく", "シェアボタン", "スタンダードプラン記事",
        "スマートフォンやパソコンで試合の流れが楽しめます", "デジタル有料記事の大半が読める", "ニュースレターで最新情報を受け取れる", "フルプランなら", "フルプラン会員のみご覧いただけます",
        "プレゼント企画に応募が出来る", "プレミアムコース限定機能です", "ホーム", "マイページ", "ラジオを片手に応援する方も", "リンクをコピー", "ログイン", "ログインする",
        "一手掌握經濟脈動", "一方で", "一気に振り返るのがこの番組", "一覧ページへ", "上周五", "下野新聞デジタルに会員登録すると", "不付稿酬", "不自然なアクセント",
        "不論是對政治", "中新社记者", "也就是說", "事件事故や高校野球", "人気記事", "亿美元", "今回お届けする内容は", "今週は放送時間を拡大してお届けします",
        "他にはない神奈川のニュースを", "他強調", "他指出", "他提醒", "他直言", "他表示", "他認為", "他认为", "令和7", "以下简称", "会員登録", "会員登録すると",
        "会社案内", "会社概要", "來稿請附真實姓名", "依台灣網站分級推廣基金會規定作標示", "保證天天中獎", "個人情報保護方針", "值得一提的是", "值得注意的是", "值得留意的是",
        "健康頻道", "億美元", "億美金", "兆美元", "全てのコンテンツが読み放題", "全ての写真を見る", "全文を読む", "全文記事を読むには", "八萬五", "公開日",
        "写真ページはこちら", "分享工具", "初回価格は約13", "判決指出", "午前1", "午前11", "午後0", "午後4", "午後6", "午後7", "午後8", "原刊於",
        "口座番号4097270", "可撥衛福部專線", "台南市政府提供", "周波数79", "問い合わせ", "問合せ", "国内新闻精选", "国际新闻精选", "圖為預想圖", "圖片來源",
        "圖由警方提供", "報告指出", "報導指出", "変更はこちら", "外媒指出", "契約はこちら閉じる現在あなたのご自宅で西日本新聞紙面を購読していますか", "她表示", "定数22",
        "宮日会館のご利用", "専門用語において読み間違いや", "屏東縣政府提供", "已於網站首頁或各該限制級網頁", "幅広い分野に渡って", "幅広い分野をフォロー", "平日9",
        "店番128", "延伸內容", "延伸閱讀", "当月無料", "後10", "徐欣瑩競辦提供", "您即將進入之新聞內容", "愛読者プラン会員", "成為粉絲", "或張老師服務專線",
        "投稿信箱", "投稿案内", "拡大拡大", "按我看活動辦法", "据了解", "据介绍", "採用情報", "據了解", "據報導", "放送番組の種別", "教育や仕事に役立つ情報が充実",
        "整體而言", "文娱新闻精选", "文責は編集部に帰属します", "料金はかかりません", "新着記事", "新聞主頁", "新規会員登録", "新規登録", "方可瀏覽", "日媒報導",
        "日媒指出", "日曜日", "昼12", "時に深く掘り下げ", "時報訊", "更多精采文章", "更多試駕影片", "更新時間", "更重要的是", "最新全国ニュースの他の記事",
        "月12", "月24", "月曜日", "月曜日から金曜日の以心伝心の話題を", "有意見想表達", "有料この記事は有料会員限定です", "有料プランをご購読の方のみご利用いただけます",
        "有料会員限定記事", "有筆名請另註", "朝刊広告料金表", "木曜日", "本報合成", "本報有錄取及刪修權", "本文の音声は", "本社獲作者授權轉載", "本社編輯部", "根據統計",
        "楽曲は省略させて頂いています", "次のページ", "毎週日曜", "民眾提供", "水曜日", "法官認為", "法新社檔案照", "滋賀の暮らしや仕事に役立つニュースをお届けします",
        "火曜日", "災害や事故の速報などを発信します", "為達最佳瀏覽效果", "無料会員向け記事が読める", "無料会員登録", "無料期間中に解約すると", "熱門新聞",
        "現在あなたのご自宅で", "現地に行けない方も", "生命一定可以找到出路", "生命線專線", "生成aiの音声合成技術を利用して自動生成しています", "番組一覧", "番組概要",
        "登録すると続きをお読みいただけます", "發佈時間", "發燒文章", "相關新聞", "相關新聞請見", "看更多", "示意圖", "社会新闻精选", "立即追蹤", "約23",
        "約新台幣1", "紙面の購読が必要です", "紙面ビューアーで", "紙面ビューアーなど全ての機能が使えます", "紙面ビューアーは利用できません", "紙面購読申し込み",
        "続きをお読み頂けます", "続きを読むには会員登録やプランの利用申し込みが必要です", "綜合外媒報導", "網友回應", "緊貼全城熱話", "編譯陳成良", "翌月まで無料",
        "翻攝自小紅書", "翻攝自微博", "翻攝自臉書", "聯絡電話", "自殺不能解決問題", "自由時報提醒您遠離毒品", "自由時報電子報提醒您", "若須諮商或相關協助", "萬元台幣",
        "著作権とリンク", "著作権保護のため", "西日本新聞meとは", "西日本新聞紙面を購読していますか", "視聴データの取り扱い", "觀光局提供", "記者俞肇福攝", "記者劉婉君攝",
        "記者劉詠韻攝", "記者吳孟儒", "記者姚岳宏翻攝", "記者徐聖倫翻攝", "記者方賓照攝", "記者李惠洲攝", "記者李文德攝", "記者林南谷", "記者林正堃攝", "記者楊綿傑攝",
        "記者歐素美攝", "記者王冠仁翻攝", "記者王藝菘攝", "記者蔡宗勳攝", "記者賴筱桐攝", "記者陳建志翻攝", "記者陳彥廷攝", "記者陳逸寬攝", "記者陳鳳麗攝",
        "詳しくはこちら閉じる閉じる", "詳報含めて発信します", "請加入自由時報粉絲團", "請勿一稿多投", "警察によりますと", "警方指出", "警方提供", "警方表示", "財經頻道",
        "責任編輯", "購読料", "購読者無料", "责任编辑", "路透資料照", "追加料金なしで全てのコンテンツが読み放題", "送信中止", "速報メールやニュースレターもお届け",
        "速報メールや週間ランキングメールもお届け", "都歡迎你熱烈投稿", "金曜日", "錄用與否將不另行通知", "閉じる", "関連記事", "閱讀所有文章",
        "電子書籍やスクラップなど全機能が使えます", "音声に関するご注意", "音声に関するご注意本文の音声は", "音声読み上げは", "首次上稿", "點我訂閱自由財經youtube頻道",
        "點這裡", "그에게", "금요일", "금합니다", "누군가", "당신의", "대표자명", "대표전화", "등록번호", "등록일", "무엇을", "무엇이", "사업자등록번호",
        "않겠다", "않았고", "어디에", "예정이다", "우리의", "이것은", "일까지", "일부터", "자신을", "자신의", "주요뉴스", "지적했다", "참석했다",
        "청소년보호책임자",
    })
    assert added_since_migration <= _EXTRA_STOPWORDS, (
        "a declared post-migration addition is missing from the data files"
    )

    baseline = _EXTRA_STOPWORDS - added_since_migration
    assert len(baseline) == 2377

    digest = hashlib.sha256("\n".join(sorted(baseline)).encode("utf-8")).hexdigest()
    assert (
        digest
        == "a1a7493a21afb9abfe48eb1f13b323df6ea2cff46a21f03f7c3901f62221fc86"
    ), "the extra-stopword SET changed -- confirm this is intentional, not a migration regression"
