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
_CONNECTORS = {"of", "the", "and", "for", "de", "la", "le", "du", "des", "van",
               "von", "der", "den", "di", "da", "do", "al", "bin", "el", "&"}

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
)
_EXTRA_STOPWORDS: frozenset[str] = frozenset(_EXTRA_STOPWORD_TEXT.split())


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
    term: str            # display form (entities keep case; terms are lowercased)
    normalized: str      # dedup key (casefold)
    kind: str            # term | person | org | location | entity
    count: int
    first_offset: int | None


def _normalize(s: str) -> str:
    return " ".join(s.split()).casefold()


class BaselineExtractor:
    """Dependency-free n-gram terms + Title-Case entity detection."""

    name = "baseline"

    def __init__(self, *, gazetteer: dict[str, str] | None = None,
                 max_terms: int = _DEFAULT_MAX_TERMS, max_entities: int = _DEFAULT_MAX_ENTITIES):
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
            is_titlecase = surface[:1].isupper() and (len(surface) == 1 or any(c.islower() for c in surface))
            is_acronym = surface.isupper() and len(surface) >= 2
            if not (is_titlecase or is_acronym):
                i += 1
                continue
            start = tok.start()
            parts = [surface]
            j = i + 1
            while j < n:
                nxt = tokens[j].group(0)
                gap = text[tokens[j - 1].end():tokens[j].start()]
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
                surface_run = text[start:end_tok.end()]
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
            entities.append(ExtractedTerm(
                term=a["surface"], normalized=norm,
                kind=self.gazetteer.get(norm, "entity"),
                count=a["count"], first_offset=a["first"],
            ))
        entities.sort(key=lambda e: (-e.count, e.first_offset or 0))
        return entities[: self.max_entities]

    @staticmethod
    def _at_sentence_start(text: str, offset: int) -> bool:
        if offset == 0:
            return True
        return bool(_SENT_END.search(text[max(0, offset - 40):offset]))

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
                window = toks[k:k + size]
                words = [w for w, _ in window]
                # Drop a phrase if ANY token is a stopword or too short/numeric, so
                # fillers don't leak inside n-grams ("not one bit", "economy is not").
                if any(w in stop or len(w) < _MIN_TERM_LEN or w.isdigit() for w in words):
                    continue
                phrase = " ".join(words)
                _record(phrase, window[0][1])

        terms = [
            ExtractedTerm(term=t, normalized=t, kind="term", count=c, first_offset=first_at.get(t))
            for t, c in counts.items() if c >= 1
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
    _LABELS = {"PERSON": "person", "PER": "person", "ORG": "org",
               "GPE": "location", "LOC": "location", "FAC": "location", "NORP": "org"}

    def __init__(self, model: str = "en_core_web_sm", *, max_entities: int = _DEFAULT_MAX_ENTITIES,
                 baseline: BaselineExtractor | None = None):
        import spacy  # raises ImportError if the [nlp] extra is absent

        self._nlp = spacy.load(model, disable=["lemmatizer", "tagger"])
        self.model = model
        self.max_entities = max_entities
        self._baseline = baseline or BaselineExtractor()

    def extract(self, text: str, *, title: str = "", language: str = "en") -> list[ExtractedTerm]:
        if not text or not text.strip():
            return []
        doc = self._nlp(text[: 1_000_000])  # spaCy default max length guard
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
        entities = sorted(ents.values(), key=lambda e: (-e.count, e.first_offset or 0))[: self.max_entities]
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
