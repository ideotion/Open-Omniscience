"""
Pluggable keyword & entity extraction (offset-aware).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Turns an article body into ``ExtractedTerm``s carrying their occurrence count and
the char offset of their first occurrence (so the surrounding sentence can be
shown later, sliced from the stored article text). Two honest backends:

  * **BaselineExtractor** (core, no deps): topical n-gram *terms* (stopword-filtered,
    lowercased) PLUS *entities* detected as multi-word Title-Case sequences, with a
    person/org/location ``kind`` only when a supplied gazetteer says so — otherwise
    the honest generic kind ``entity``. Best for space-delimited scripts; it does
    not pretend to segment CJK/Arabic.
  * **SpacyExtractor** (opt-in ``[nlp]`` extra): real PERSON/ORG/GPE/LOC entities
    from a local spaCy model, reusing the baseline for topical terms. Constructed
    only if spaCy + a model are installed; callers fall back to baseline otherwise.

Every term records which extractor produced it; an entity ``kind`` is a
"labelled-by-X" assertion, never asserted as ground truth.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from src.services.stopwords import stopwords_manager

# A word token: starts with a (unicode) letter, may contain letters, marks,
# apostrophes and hyphens. Digits-only / punctuation tokens are ignored.
_WORD_RE = re.compile(r"[^\W\d_][\w'’\-]*", re.UNICODE)
_SENT_END = re.compile(r"[.!?]['\"”’)]?\s+$")

# Lowercase connector words allowed *inside* a multi-word entity (e.g. "Bank of
# England", "Rio Tinto plc", "Université de Paris").
_CONNECTORS = {
    "of",
    "the",
    "and",
    "for",
    "de",
    "la",
    "le",
    "du",
    "des",
    "van",
    "von",
    "der",
    "den",
    "di",
    "da",
    "do",
    "al",
    "bin",
    "el",
    "&",
}

_DEFAULT_MAX_TERMS = 80
_DEFAULT_MAX_ENTITIES = 80
_MIN_TERM_LEN = 3

# Curated extra stoplist: very common function words / fillers that the per-language
# sets miss, plus number-words, across the major Latin-script languages. Combined
# with the per-language sets into global_stopwords(). The user can add more from
# the Settings tab (keyword filter).
_EXTRA_STOPWORD_TEXT = (
    # English fillers the base set lacks
    "not no nor one two three four five six seven eight nine ten "
    "get got gets getting make made makes making take takes took taking "
    "go goes going gone come comes coming came see sees seen saw "
    "know knows knew known think thinks thought want wants wanted need needs "
    "like likes liked use used uses using way ways thing things lot lots "
    "new old good bad big small great little much many even still back "
    "people person time times part parts case cases number numbers group "
    "well around across along yet ever never always often sometimes maybe perhaps "
    "really quite rather pretty almost enough across upon onto unto whatever whoever "
    "into within without toward towards among amongst per via "
    "this that these those here there what which whose "
    # Relative time + news-attribution fillers users flagged as noise
    "since last next first second third ago today yesterday tomorrow soon "
    "early late later recent recently latest current currently meanwhile amid "
    "said says say told tells according reportedly however therefore thus hence "
    "indeed instead although though whereas whilst despite "
    # Contractions (ASCII; curly-apostrophe variants are added programmatically below)
    "it's don't doesn't didn't won't can't cannot isn't aren't wasn't weren't "
    "hasn't haven't hadn't couldn't wouldn't shouldn't i'm you're we're they're "
    "i've you've we've they've i'll you'll that's there's what's let's he's she's "
    "dont doesnt didnt wont cant isnt arent wasnt werent hasnt havent hadnt "
    "couldnt wouldnt shouldnt youre theyre ive youve weve theyve thats theres whats lets "
    # Spanish
    "el la los las un una unos unas de del y o pero que como para por con sin "
    "es son fue era ser estar su sus lo le les nos se mas muy "
    # German
    "der die das den dem ein eine einer und oder aber auch ist sind war "
    "nicht mit von zu im am ich du wir sie es auf für "
    # Italian
    "il lo la gli le un uno una di del della che chi non con per tra fra "
    "sono era essere ho hai abbiamo questo quello "
    # Portuguese
    "o a os as um uma uns umas de do da dos das que nao com para por "
    "sou somos foi ser este esse isso "
    # Dutch
    "de het een en of maar ook is zijn was niet met van te ik je wij zij "
    # French (was MISSING entirely — the 2026-06-11 field log leaked dans/plus/
    # pas/aux/ont/ses… as top "entities"; added with elision combos + fillers)
    "le la les un une des du de au aux et ou mais donc or ni car que qui quoi "
    "dont où dans sur sous avec sans pour par entre vers chez pas plus moins "
    "très tout tous toute toutes même aussi ainsi alors comme encore déjà "
    "depuis pendant avant après être avoir fait faire été ont sont est était "
    "avait avaient seront sera leur leurs ses son sa ce cet cette ces celui "
    "celle ceux celles il elle ils elles nous vous je tu on lui y en se soi "
    "notre votre nos vos mon ma mes ton ta tes deux trois quatre cinq six "
    "sept huit neuf dix plusieurs quelques chaque autre autres certains "
    "certaines désormais également notamment toutefois cependant pourtant "
    "c'est n'est d'un d'une qu'il qu'elle qu'ils s'est j'ai l'on jusqu'à "
    "aujourd'hui hier demain lundi mardi mercredi jeudi vendredi samedi dimanche "
    # Month names leak as entities ("June" en:317, "Juin" fr:68 in the field log)
    "january february march april may june july august september october november december "
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre "
    # English generics observed leaking as entities in the field log
    "including found help work million billion millions billions "
    # ----------------------------------------------------------------------- #
    # Field log #2 (2026-06-12, 63,672-keyword export): the de-US-centred
    # catalog brought 22 source languages, 16 of them WITHOUT stoplists —
    # function words sat in TOP analytics slots (nl "dat"×1599, de "sich"×982,
    # es "más"×1001, sv "som"×795, ru "что"×531…). Maintainer ruling: NO cap on
    # keyword counts; instead a clear exception policy for pronouns,
    # conjunctions & co. in ALL the app's corpus languages. Every block below
    # is evidence-backed by that export; global_stopwords() applies these
    # retroactively at query time, so stored junk disappears from analytics
    # without touching data.
    # English (the 3 residual leaks)
    "another further yes "
    # Spanish (extends the thin block above; 48 leaked words, 5,754 mentions)
    "al en sobre entre desde hasta yo tú él ella ellos ellas nosotros usted "
    "ustedes mi tu nuestro este esta estos estas ese esa esos esas aquel quien "
    "cual cuyo donde cuando fueron hay también ya si sólo solo así pues porque "
    "aunque mientras cada todo toda todos todas otro otra otros otras mismo misma qué "
    # German (48 leaked, 8,194 mentions: sich/bei/wie/aus/über/nach/einem/einen…)
    "des einem einen eines kein keine ja nein bei aus nach über unter vor "
    "hinter zwischen durch gegen ohne um er ihr sich mein dein sein unser euer "
    "dieser diese dieses jener welche welcher was wer wie wo wann warum waren "
    "haben hat hatte werden wird wurde noch schon nur sehr mehr als wenn weil "
    "dass damit sowie sowohl beide jeder jede jedes alle "
    # Italian (42 leaked, 3,230 mentions: alla/dei/nel/più/delle/anche…)
    "i dei delle a al alla in nel nella con da dal su sul senza io tu lui lei "
    "noi voi loro mio tuo suo nostro questa questi queste quella cui dove "
    "quando perché è erano avere ha hanno fu furono anche molto più meno già "
    "sì così poiché mentre ogni tutto tutta tutti tutte altro altra "
    # Portuguese (20 leaked: não/ele/também/até/foram/seu/ela…)
    "no na nos nas em sem sobre entre desde até eu tu ele ela eles elas nós "
    "você vocês meu teu seu nosso estes estas essa aquele quem qual cujo onde "
    "quando porque é são era eram estar foram há também muito mais menos já "
    "não sim só assim pois embora enquanto cada todo toda todos todas outro outra "
    # Dutch (34 leaked, 10,257 mentions — the worst: dat/voor/hij/uit/bij/naar…)
    "dat voor naar in op bij uit door over onder tussen tegen zonder om jij "
    "hij wie zich mijn jouw zijn haar ons hun deze die dit welke wat waar "
    "wanneer hoe waarom waren worden wordt werd hebben heeft had nog al alleen "
    "zeer meer als toen omdat zodat beide elke alle "
    # Russian (54 leaked, 2,658 mentions: что/для/как/его/также/это/при/более…)
    "и в во не на я он она оно они мы вы ты что это эта этот эти как так но "
    "или а же бы был была были быть есть от до из у за под над при с со для "
    "по о об к ко его её их наш ваш мой твой свой кто где когда почему зачем "
    "тоже также уже ещё еще только очень более менее всех весь вся всё все "
    "другой другая каждый если потому пока между через без "
    # Swedish (30 leaked, 3,752 mentions: som/har/det/och/för…)
    "och eller men av till i på vid med för från ut genom över under mellan "
    "mot utan om jag du han hon vi ni de sig min din sin vår er denna detta "
    "dessa den det som vem vad var när hur varför är varit bli blir blev ha "
    "har hade också än redan bara mycket mer mest alla varje annan "
    # Norwegian bokmål (30 leaked: til/jeg/seg/ble/også/hadde/ved/når…)
    "og av til ved fra gjennom mellom mot uten jeg han hun dere seg din sin "
    "deres denne dette disse hvem hva hvor når hvordan hvorfor vært ble enn "
    "hver annen "
    # Danish (9 leaked; same family as nb/sv — completes the Scandinavian set)
    "ud mod hvis bliver blive meget havde vores hvad gennem uden anden "
    # Polish (42 leaked, 2,789 mentions: się/jest/jak/przez/czy/dla…)
    "i w we na nie z ze do od po za pod nad przy o u dla przez bez się to ta "
    "ten te tej tego tych jak tak ale lub albo czy że by był była było były "
    "być jest są ma mają mój twój swój nasz wasz kto co gdzie kiedy dlaczego "
    "też także już jeszcze tylko bardzo więcej mniej każdy wszystko wszyscy "
    "inny inna jeśli bo między "
    # Hungarian (32 leaked: hogy/nem/egy/már/volt/vagy/még/több…)
    "a az és vagy de hogy nem igen egy ez ezek azok aki ami amely ahol amikor "
    "miért hogyan én te ő mi ti ők enyém tied övé miénk van volt lesz lenni "
    "már még csak nagyon több kevesebb minden mindenki más ha mert között "
    "nélkül ellen alatt felett által "
    # Arabic (22 leaked, 1,417 mentions: على/إلى/هذا/التي/هذه/كما/ذلك…)
    "في من إلى على عن مع هذا هذه ذلك تلك التي الذي الذين ما لا لم لن إن أن "
    "كان كانت يكون هو هي هم هن نحن أنت أنا أو ثم بل لكن حتى إذا كما قد كل "
    "بعض غير بين عند منذ أي "
    # Serbian/Croatian/Bosnian latin (30 leaked: kako/još/sve/više/biti/kada…)
    "u za od do po pri sa bez kroz preko ispod iznad između protiv ovaj ova "
    "ovo taj ona oni ko šta gde gdje kada kako zašto je su bio bila bilo biti "
    "ima imaju takođe također već još samo veoma više manje svaki sve drugi "
    "druga ako jer moj tvoj svoj naš vaš "
    # Turkish (26 leaked: için/olarak/daha/çok/veya/ancak/gibi/değil…)
    "ve veya ama fakat ancak ki bu şu bir için ile gibi kadar sonra önce "
    "üzere göre eğer çünkü her hem ya ne hangi kim nerede zaman nasıl niçin "
    "neden ben sen biz siz onlar benim senin onun bizim sizin değil var yok "
    "daha çok az en idi olan olarak "
    # Indonesian (33 leaked: untuk/ini/dengan/itu/adalah/pada/juga…)
    "dan atau tetapi tapi dari ke di pada dengan untuk tanpa atas bawah "
    "antara terhadap ini itu yang siapa apa mana kapan bagaimana mengapa saya "
    "kamu dia kami kita mereka aku adalah ialah ada sudah telah akan juga "
    "masih hanya sangat lebih kurang semua setiap lain jika karena "
    # Finnish (16 leaked: että/olla/hän/myös…)
    "ja tai mutta että ei kyllä se tämä nämä nuo joka mikä kuka missä milloin "
    "miksi miten minä sinä hän me te he on oli ollut olla olen myös jo vain "
    "hyvin enemmän vähemmän kaikki jokainen muu jos koska välillä ilman "
    # Hindi (1 leaked — अगर; the conjunction/pronoun core completes the policy)
    "और या लेकिन कि नहीं हाँ यह वह ये वे जो क्या कौन कहाँ कब कैसे क्यों मैं तुम आप हम "
    "का की के को से में पर है हैं था थे थी होना भी अभी केवल बहुत अधिक कम सब हर "
    "अन्य अगर क्योंकि बीच बिना "
    # Second evidence pass (same export, post-policy survivors): inflected
    # function words, modals, attribution verbs and date-generics that the
    # core sets miss — plus month names beyond en/fr (es "junio"×257 and
    # ru "июня"×133 leaked exactly like the en/fr months above).
    "aan geen wel veel zegt zei jaar jaren niet maar werd onder meer "  # nl
    "att ett kommer skriver sade säger mån månader dag dagar år procent "  # sv
    "está según durante contra años año donde fueron sido siendo estado "  # es
    "zum zur kann muss soll andere anderen ihre ihren seinen seiner jahr jahren "  # de
    "anni anno dopo prima contro essere stato stata fatto detto "  # it
    "года году год лет годы после этом этой этого того тем том тех ней нем них ему ей им "  # ru
    "etter siden også året år dager "  # nb
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre "
    "januar februar märz april mai juni juli august september oktober november dezember "
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre "
    "januari februari maart april mei juni juli augustus oktober "
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря "
    "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь "
)
_EXTRA_STOPWORDS: frozenset[str] = frozenset(_EXTRA_STOPWORD_TEXT.split())
# News text often uses a curly apostrophe (’) — match those spellings of any
# contraction too, so "don't" and "don’t" are both filtered without listing each twice.
_EXTRA_STOPWORDS = _EXTRA_STOPWORDS | frozenset(
    w.replace("'", "’") for w in _EXTRA_STOPWORDS if "'" in w
)


@lru_cache(maxsize=1)
def global_stopwords() -> frozenset[str]:
    """Union of all built-in per-language stoplists + the curated extra set.

    Language-agnostic: a word that is a stopword in any supported language (or in
    the curated extra list) is treated as one. Used both at extraction time and at
    query time (so leaky terms already in the store are hidden retroactively).
    """
    s: set[str] = set(_EXTRA_STOPWORDS)
    s |= set(stopwords_manager.default_stopwords)
    for lang in getattr(stopwords_manager, "language_stopwords", {}):
        s |= set(stopwords_manager.get_stopwords(lang))
    return frozenset(s)


def _stopset(language: str) -> frozenset[str]:
    return frozenset(stopwords_manager.get_stopwords(language)) | global_stopwords()


@dataclass
class ExtractedTerm:
    term: str  # display form (entities keep case; terms are lowercased)
    normalized: str  # dedup key (casefold)
    kind: str  # term | person | org | location | entity
    count: int
    first_offset: int | None


_ELISION = re.compile(r"\b([dlncjmst]|qu)['’](?=\w)", re.IGNORECASE)


def _normalize(s: str) -> str:
    # French elisions are tokenization noise, not meaning: "d'euros" is about
    # euros, "l'ia" about ia. Strip the elided article before keying (field
    # log 2026-06-11). Contraction STOPWORDS like c'est stay listed verbatim
    # (they're filtered before this matters).
    s = _ELISION.sub("", s)
    return " ".join(s.split()).casefold()


class BaselineExtractor:
    """Dependency-free n-gram terms + Title-Case entity detection."""

    name = "baseline"

    def __init__(
        self,
        *,
        gazetteer: dict[str, str] | None = None,
        max_terms: int = _DEFAULT_MAX_TERMS,
        max_entities: int = _DEFAULT_MAX_ENTITIES,
    ):
        # gazetteer maps normalized name -> kind ("person"|"org"|"location").
        self.gazetteer = gazetteer or {}
        self.max_terms = max_terms
        self.max_entities = max_entities

    # -- entities ---------------------------------------------------------- #

    def _entities(self, text: str) -> list[ExtractedTerm]:
        tokens = list(_WORD_RE.finditer(text))
        # Mark which tokens begin a sentence (their capitalisation is uninformative).
        runs: list[tuple[str, int]] = []  # (surface, start_offset)
        i = 0
        n = len(tokens)
        while i < n:
            tok = tokens[i]
            surface = tok.group(0)
            is_titlecase = surface[:1].isupper() and (
                len(surface) == 1 or any(c.islower() for c in surface)
            )
            is_acronym = surface.isupper() and len(surface) >= 2
            if not (is_titlecase or is_acronym):
                i += 1
                continue
            start = tok.start()
            parts = [surface]
            j = i + 1
            while j < n:
                nxt = tokens[j].group(0)
                gap = text[tokens[j - 1].end() : tokens[j].start()]
                if "\n" in gap or len(gap) > 3:  # broken by a line/large gap -> stop the run
                    break
                if nxt[:1].isupper() or nxt in _CONNECTORS or (nxt.isupper() and len(nxt) >= 2):
                    parts.append(nxt)
                    j += 1
                else:
                    break
            # Trim trailing connectors.
            while parts and parts[-1] in _CONNECTORS:
                parts.pop()
            if parts:
                end_tok = tokens[i + len(parts) - 1]
                surface_run = text[start : end_tok.end()]
                runs.append((surface_run, start))
            i = max(j, i + 1)

        # Aggregate runs by normalised form, tracking whether a form is ever
        # multi-word and whether it ever occurs *mid-sentence* (a strong proper-noun
        # signal). A single-word, only-ever-sentence-initial form is capitalisation
        # noise (e.g. "Climate" starting a sentence) and is dropped unless the
        # gazetteer vouches for it.
        agg: dict[str, dict] = {}
        for surface, offset in runs:
            norm = _normalize(surface)
            a = agg.get(norm)
            if a is None:
                a = {"count": 0, "first": offset, "multi": False, "mid": False, "surface": surface}
                agg[norm] = a
            a["count"] += 1
            if len(surface.split()) > 1:
                a["multi"] = True
            if not self._at_sentence_start(text, offset):
                a["mid"] = True

        gstop = global_stopwords()
        entities: list[ExtractedTerm] = []
        for norm, a in agg.items():
            if not (a["multi"] or a["mid"] or norm in self.gazetteer):
                continue
            # Never treat a function word or single character as an entity (e.g.
            # "I", "A", "The") — unless the gazetteer vouches for it.
            if norm not in self.gazetteer and (len(norm) < 2 or norm in gstop):
                continue
            entities.append(
                ExtractedTerm(
                    term=a["surface"],
                    normalized=norm,
                    kind=self.gazetteer.get(norm, "entity"),
                    count=a["count"],
                    first_offset=a["first"],
                )
            )
        entities.sort(key=lambda e: (-e.count, e.first_offset or 0))
        return entities[: self.max_entities]

    @staticmethod
    def _at_sentence_start(text: str, offset: int) -> bool:
        if offset == 0:
            return True
        return bool(_SENT_END.search(text[max(0, offset - 40) : offset]))

    # -- topical terms ----------------------------------------------------- #

    def _terms(self, text: str, language: str) -> list[ExtractedTerm]:
        stop = _stopset(language)
        toks = [(m.group(0).lower(), m.start()) for m in _WORD_RE.finditer(text)]
        counts: Counter[str] = Counter()
        first_at: dict[str, int] = {}

        def _record(term: str, offset: int) -> None:
            counts[term] += 1
            first_at.setdefault(term, offset)

        # Unigrams (content words only).
        for word, off in toks:
            if len(word) >= _MIN_TERM_LEN and word not in stop and not word.isdigit():
                _record(word, off)
        # Bigrams / trigrams over the raw token stream, dropping ones bounded by
        # stopwords so phrases stay meaningful ("prime minister", not "of the").
        for size in (2, 3):
            for k in range(len(toks) - size + 1):
                window = toks[k : k + size]
                words = [w for w, _ in window]
                # Drop a phrase if ANY token is a stopword or too short/numeric, so
                # fillers don't leak inside n-grams ("not one bit", "economy is not").
                if any(w in stop or len(w) < _MIN_TERM_LEN or w.isdigit() for w in words):
                    continue
                phrase = " ".join(words)
                _record(phrase, window[0][1])

        terms = [
            ExtractedTerm(term=t, normalized=t, kind="term", count=c, first_offset=first_at.get(t))
            for t, c in counts.items()
            if c >= 1
        ]
        terms.sort(key=lambda e: (-e.count, len(e.term)))
        return terms[: self.max_terms]

    def extract(self, text: str, *, title: str = "", language: str = "en") -> list[ExtractedTerm]:
        if not text or not text.strip():
            return []
        entities = self._entities(text)
        ent_norms = {e.normalized for e in entities}
        # Drop topical terms that duplicate a detected entity (e.g. the bigram
        # "emmanuel macron") so the entity is the single unit, as intended.
        terms = [t for t in self._terms(text, language) if t.normalized not in ent_norms]
        return entities + terms


class SpacyExtractor:
    """Opt-in real NER (PERSON/ORG/GPE/LOC) + baseline topical terms."""

    name = "spacy"
    _LABELS = {
        "PERSON": "person",
        "PER": "person",
        "ORG": "org",
        "GPE": "location",
        "LOC": "location",
        "FAC": "location",
        "NORP": "org",
    }

    def __init__(
        self,
        model: str = "en_core_web_sm",
        *,
        max_entities: int = _DEFAULT_MAX_ENTITIES,
        baseline: BaselineExtractor | None = None,
    ):
        import spacy  # raises ImportError if the [nlp] extra is absent

        self._nlp = spacy.load(model, disable=["lemmatizer", "tagger"])
        self.model = model
        self.max_entities = max_entities
        self._baseline = baseline or BaselineExtractor()

    def extract(self, text: str, *, title: str = "", language: str = "en") -> list[ExtractedTerm]:
        if not text or not text.strip():
            return []
        doc = self._nlp(text[:1_000_000])  # spaCy default max length guard
        ents: dict[str, ExtractedTerm] = {}
        for ent in doc.ents:
            kind = self._LABELS.get(ent.label_)
            if kind is None:
                continue
            norm = _normalize(ent.text)
            if norm in ents:
                ents[norm].count += 1
            else:
                ents[norm] = ExtractedTerm(ent.text, norm, kind, 1, ent.start_char)
        entities = sorted(ents.values(), key=lambda e: (-e.count, e.first_offset or 0))[
            : self.max_entities
        ]
        # Topical terms from the baseline (entities here are model-labelled), minus
        # any that duplicate a detected entity.
        ent_norms = {e.normalized for e in entities}
        terms = [t for t in self._baseline._terms(text, language) if t.normalized not in ent_norms]
        return entities + terms


def get_extractor(name: str = "baseline", *, gazetteer: dict[str, str] | None = None, **kw):
    """Factory. ``name='spacy'`` falls back to baseline if the extra is missing."""
    if name == "spacy":
        try:
            return SpacyExtractor(baseline=BaselineExtractor(gazetteer=gazetteer), **kw)
        except Exception:  # noqa: BLE001 - spaCy/model absent -> honest fallback
            return BaselineExtractor(gazetteer=gazetteer)
    return BaselineExtractor(gazetteer=gazetteer)
