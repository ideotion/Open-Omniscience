"""
Entity extractor — people and organizations, the third axis of space–time–WHO
(maintainer-ruled 2026-06-11). Treated as two SEPARATE classes by design: an
article about a person resists placement in space; an organization often
anchors to places differently — conflating them would blur both.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Explainable lexical heuristics, no NER model, bounded, snippet provenance,
every candidate marked deduced. Noisier than the date/location extractors by
nature — the notes say which rule fired so a human can judge.
"""

from __future__ import annotations

import re

_MAX_SCAN = 60_000

# Honorifics that PRECEDE a person's name (high-precision person signal).
_HONORIFIC = (
    r"(?:President|Prime Minister|Chancellor|Minister|Senator|Governor|Mayor|"
    r"Mr|Mrs|Ms|Dr|Sir|Dame|Pope|King|Queen|Prince|Princess|General|Colonel|"
    r"Président|Présidente|Premier ministre|Chancelier|Ministre|Sénateur|Maire|"
    r"M\.|Mme|Herr|Frau|Señor|Señora)"
)
_PERSON_HONORIFIC_RE = re.compile(
    rf"\b{_HONORIFIC}\s+([A-ZÀ-Þ][\w'’-]+(?:\s+[A-ZÀ-Þ][\w'’-]+)?)"
)
# "Firstname Lastname" shape: two TitleCase words preceded by a LOWERCASE-
# initial word (excludes sentence openers AND TitleCase runs like headlines).
_PERSON_SHAPE_RE = re.compile(
    r"\b[a-zà-þ][\w'’-]*[,;:]?\s+([A-ZÀ-Þ][a-zà-þ'’-]{2,})\s+([A-ZÀ-Þ][a-zà-þ'’-]{2,})\b"
)
# Organization tails (en/fr/de) + institutional heads.
_ORG_TAIL = (
    r"(?:Inc|Corp|Corporation|Ltd|LLC|PLC|SA|SE|AG|GmbH|SAS|SpA|NV|"
    r"Company|Group|Groupe|Bank|Banque|University|Université|Institute|Institut|"
    r"Ministry|Ministère|Agency|Agence|Authority|Commission|Committee|Comité|"
    r"Council|Conseil|Court|Cour|Police|Army|Armée|Parliament|Parlement|"
    r"Organization|Organisation|Association|Federation|Fédération|Union|Party|Parti)"
)
_ORG_RE = re.compile(
    rf"\b((?:[A-ZÀ-Þ][\w'’&.-]+\s+){{0,3}}{_ORG_TAIL})(?![\w-])"
)
# Standalone acronyms (UN, NATO, FIFA, OPEC…): 2–6 caps, must repeat to count.
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,6})\b")
_ACRONYM_STOP = frozenset(
    "I A AN THE OK USA UK EU US AI IT TV PDF HTML HTTP HTTPS API URL CEO CFO "
    "GDP USD EUR GBP AM PM Q1 Q2 Q3 Q4 COVID".split()
)
# Leading determiners never belong to the canonical org name.
_DETERMINERS = frozenset("the le la les l' der die das el los las un une una".split())

# ---- R730 (field test 2026-11-14 row 70): per-language person/organisation rejects --------- #
# Each rule names the languages it was TESTED on and runs for those alone (the R698 spirit:
# a rule never reaches a language it was not checked against). An article with no language
# gets none of them, exactly the extractor it had before. Measured cases, all from
# Nordic news (hbl.fi, Borgåbladet, epari.fi): "Afrika För" (a place + a capitalised
# function word across a headline break), "Borgåbon Olivia" (the demonym "the Borgå
# resident" + a first name), "Tampereen Nokia" (Tampere's genitive + a brand, from
# "Tampereen Nokia Arenalla"), and "VM" (världsmästerskap, the world championships) typed
# as an organisation.

#: Function words: a person-shape candidate with one as a token is rejected. A HAND-CURATED
#: closed-class list per tested language (articles, prepositions, conjunctions, pronouns,
#: auxiliaries), never the stopwords-iso grammar list: that one holds nouns and adjectives that
#: are common surnames (de Mann, Kurz, Lang, Ende; sv Dag; fi Aina). Left out on purpose, as
#: names or name parts: name particles (de, la, le, les, du, des, da, di, del, van, von, der,
#: den, af, al, el), Till, Til, Can, Will, May, Son, Eli, Han, He, An, Ole, Kai, Hans, Ville.
def _words(spaced: str) -> frozenset[str]:
    return frozenset(spaced.split())


_FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "sv": _words("och eller men att som för från med på av om i en ett det vi ni jag hon är var har inte när där efter "
                    "under över mot vid hos utan"),
    "da": _words("og eller men at som for fra med på om i en et det jeg vi er var har ikke når efter under over mod "
                    "ved hos uden"),
    "nb": _words("og eller men at som for fra med på av om i en et ett det jeg vi er var har ikke når etter under "
                    "over mot ved hos uten"),
    "fi": _words("ja mutta että jos on oli ovat ei se ne hän me te tämä joka mikä myös kuin"),
    "de": _words("und oder aber dass die das dem ein eine einen einem einer im in ist war hat nicht mit zu zum zur auf "
                    "für bei nach aus über unter vor gegen ohne durch wenn als wie auch noch sich er sie es wir ihr"),
    "en": _words("the and or but of to in on at for from with by as is was are were has have had not this that these "
                    "those which who when where after before about into over under it its she we they our their his her"),
    "fr": _words("et ou mais que qui dont où dans sur pour par avec sans sous chez entre vers est était sont il elle ils "
                    "elles nous vous ce cette ces un une au aux"),
}
_FUNCTION_WORDS["nn"] = _FUNCTION_WORDS["nb"]
_FUNCTION_WORDS["no"] = _FUNCTION_WORDS["nb"]
_FUNCTION_WORD_LANGS = frozenset(_FUNCTION_WORDS)
#: Swedish demonyms in their definite form ("Borgåbon", "Stockholmsborna": the resident(s) of
#: a place). No Swedish given name or surname ends this way in the test lists.
_SV_DEMONYM_RE = re.compile(r"(?:bon|borna)$")
#: Finnish place genitives: the first token of a pair, ending in -n, whose stem is a FINNISH
#: gazetteer city of at least :data:`_FI_GENITIVE_MIN_POPULATION` people ("Tampereen" ->
#: Tampere; a doubled final vowel is the genitive's lengthening). Never any place anywhere:
#: Simon (Simo, a Finnish municipality of 3,000), Helen (Hel, Poland) and Hassan (Hassa,
#: Turkey) are names, so a small town or a foreign one never makes a genitive.
_FI_GENITIVE_RE = re.compile(r"(?:en|n)$")
_FI_GENITIVE_MIN_POPULATION = 20_000
#: Two- and three-letter sports-event abbreviations written as capitals in the Nordic
#: languages (VM world championships, EM European, OS Olympics, SM/NM/DM national
#: championships): never an organisation, however often repeated ("VM-guld", "VM-historia").
_NORDIC_EVENT_ACRONYMS = frozenset({"VM", "EM", "OS", "SM", "NM", "DM"})
_NORDIC_LANGS = frozenset({"sv", "fi", "da", "nb", "nn", "no"})


def _base_language(language: str | None) -> str:
    return (language or "").strip().lower().replace("_", "-").split("-")[0]


def _function_words(lang: str) -> frozenset[str]:
    return _FUNCTION_WORDS.get(lang, frozenset())


def _is_fi_city(stem: str) -> bool:
    from src.catalog.cities import cached_index

    city = cached_index()["pair"].get((stem.strip().lower(), "fi"))
    return city is not None and (city.population or 0) >= _FI_GENITIVE_MIN_POPULATION


def _fi_nominatives(stem: str) -> list[str]:
    """The nominatives a genitive stem can come from: itself (Espoo-n, Pori-n), its final vowel undoubled
    (Tamperee-n -> Tampere) and the common consonant gradations (Helsingi-n -> Helsinki, Turu-n -> Turku,
    Lahde-n -> Lahti, Seinäjoe-n -> Seinäjoki)."""
    out = [stem]
    low = stem.lower()
    if low[-1:] == low[-2:-1] and low[-1:] in "aeiouyäö":
        out.append(stem[:-1])
    if low.endswith("ngi"):
        out.append(stem[:-2] + "ki")
    if low.endswith("de"):
        out.append(stem[:-2] + "ti")
    if low.endswith("e"):
        out.append(stem[:-1] + "ki")
    if len(low) >= 2 and low[-1] in "aeiouyäö" and low[-2] not in "aeiouyäö":
        out.append(stem[:-1] + "k" + stem[-1])
    return out


def _fi_place_genitive(token: str) -> bool:
    for stem in (token[:-1], token[:-2]):  # Espoon -> Espoo; Tampereen -> Tampere
        if len(stem) < 3:
            continue
        if any(_is_fi_city(n) for n in _fi_nominatives(stem)):
            return True
    return False


def _person_rejected(tokens: list[str], lang: str, function_words: frozenset[str]) -> str | None:
    """Which R730 rule rejects this person candidate, or None. Per language only."""
    if function_words and any(t.lower() in function_words for t in tokens):
        return "function-word"
    if lang == "sv" and _SV_DEMONYM_RE.search(tokens[0].lower()):
        return "demonym"
    if lang == "fi" and len(tokens) > 1 and _FI_GENITIVE_RE.search(tokens[0]) and _fi_place_genitive(tokens[0]):
        return "place-genitive"
    return None


def _snippet(text: str, start: int, end: int, pad: int = 30) -> str:
    return text[max(0, start - pad) : min(len(text), end + pad)].replace("\n", " ").strip()


def extract_entities(text: str, *, limit: int = 6, language: str | None = None) -> dict:
    """``{"people": [...], "organizations": [...]}`` — DEDUCED candidates.

    Each entry: ``{name, mentions, snippet, note}``, ordered by mentions.
    People and organizations are separate lists by design (the maintainer's
    space–time–who ruling): they answer different questions and anchor to
    space differently. A name claimed by the organization rules never doubles
    as a person.

    ``language`` (the article's own tag) switches on the R730 rejects tested for it; without
    one, none of them runs.
    """
    if not text:
        return {"people": [], "organizations": []}
    text = text[:_MAX_SCAN]
    lang = _base_language(language)
    function_words = _function_words(lang)

    orgs: dict[str, dict] = {}
    for m in _ORG_RE.finditer(text):
        toks = m.group(1).split()
        while len(toks) > 1 and toks[0].lower() in _DETERMINERS:
            toks = toks[1:]  # "The Finance Ministry" -> "Finance Ministry"
        name = " ".join(toks)
        key = name.lower()
        if key in orgs:
            orgs[key]["mentions"] += 1
        else:
            orgs[key] = {
                "name": name,
                "mentions": 1,
                "snippet": _snippet(text, m.start(), m.end()),
                "note": "deduced: capitalized phrase ending in an organization word",
            }
    acro_counts: dict[str, int] = {}
    acro_first: dict[str, re.Match] = {}
    for m in _ACRONYM_RE.finditer(text):
        a = m.group(1)
        if a in _ACRONYM_STOP or (lang in _NORDIC_LANGS and a in _NORDIC_EVENT_ACRONYMS):
            continue
        acro_counts[a] = acro_counts.get(a, 0) + 1
        acro_first.setdefault(a, m)
    for a, n in acro_counts.items():
        if n >= 2 and a.lower() not in orgs:  # repetition required: one-off caps stay out
            m = acro_first[a]
            orgs[a.lower()] = {
                "name": a,
                "mentions": n,
                "snippet": _snippet(text, m.start(), m.end()),
                "note": "deduced: repeated acronym (organization assumed, unverified)",
            }

    org_words = {w.lower() for o in orgs.values() for w in o["name"].split()}
    people: dict[str, dict] = {}

    def _add_person(name: str, m: re.Match, note: str) -> None:
        name = " ".join(name.split())
        key = name.lower()
        if any(w.lower() in org_words for w in name.split()):
            return  # claimed by an organization — never double-classed
        if lang in _FUNCTION_WORD_LANGS and "\n" in text[m.start(1):m.end(m.lastindex or 1)]:
            # R730: a headline break between two capitalised words ("Afrika\nFör"), not a name. The whole candidate
            # goes, never its first word alone: after an honorific that word is as often a Title-Case headline verb
            # ("President Warns\nMarkets fell") as a name (measured on the third review, 2026-11-16).
            return
        if lang and _person_rejected(name.split(), lang, function_words):
            return  # R730: a place genitive, a demonym or a function word, not a name
        if key in people:
            people[key]["mentions"] += 1
        else:
            people[key] = {
                "name": name,
                "mentions": 1,
                "snippet": _snippet(text, m.start(), m.end()),
                "note": note,
            }

    for m in _PERSON_HONORIFIC_RE.finditer(text):
        _add_person(m.group(1), m, "deduced: name following an honorific/title")
    for m in _PERSON_SHAPE_RE.finditer(text):
        _add_person(
            f"{m.group(1)} {m.group(2)}", m,
            "deduced: mid-sentence Firstname-Lastname shape (weakest rule)",
        )

    rank = lambda d: sorted(d.values(), key=lambda e: -e["mentions"])[:limit]  # noqa: E731
    return {"people": rank(people), "organizations": rank(orgs)}
