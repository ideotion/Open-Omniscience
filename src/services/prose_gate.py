"""
The PROSE GATE -- function-word density / prose-ness, an extraction-validity criterion.

NAV-SOUP SPECIMEN ruling (maintainer field specimen 2026-07-20: the Irish Mirror
``newsletter-preference-centre`` page stored as an Article): the ingest-door non-article filter
(``src/ingest/non_article.py``) has a load-bearing guard that KEEPS any extracted body at or above
``_ARTICLE_MIN_WORDS`` regardless of URL -- real articles run long, nav/tag/section junk runs thin.
But WORD-RICH nav soup defeats that precondition: the specimen is ~135 words of pure menu chrome
("News Latest . Irish News . Mirror Bingo . Soccer Golf Rugby Union . ...") -- plenty of words,
zero prose. This module is the criterion that catches THAT shape: real prose in ANY supported
language runs a healthy share of function words (articles, pronouns, prepositions, conjunctions --
"the", "and", "of", "to", ...) STRUNG INTO SENTENCES (real sentence-ending punctuation); a
menu/listing is mostly content-word noun phrases NOT strung into sentences at all.

THE SIGNAL is two-part, AND-gated (precision-serving: a drop needs BOTH signals, since a false
positive here is data loss, exactly the ``non_article`` module's own design principle):
  1. function-word DENSITY of the asserted/best-matching language -- near zero for nav soup (~5%
     for the specimen) vs ~40%+ for real prose in any of the vendored stopwords-iso languages.
  2. sentence-punctuation DENSITY (share of tokens followed by a `.`/`!`/`?`) -- near zero for a
     bare list of menu items/headlines (no sentences), healthy for real prose.
Either signal ALONE is not enough (a headline-LIST page can run a moderate function-word density
without being real body prose, and a real article quoting a bare list of proper nouns can dip in
density for a stretch) -- the AND is what keeps this a high-precision, keep-when-in-doubt criterion,
matching ``non_article.py``'s own "conservative when in doubt" posture.

GUARDS (the S5.2 mislabel lesson -- unmeasurable text is never dropped on a gap):
  * too few tokens to measure -> ``None`` (never judge on a sliver of text);
  * an UNSEGMENTED script (zh/ja/th have no word-boundary spaces, so a naive word-regex just globs
    a whole run into one "token" and the density measure is meaningless) -> skipped, ``None``, not
    dropped. Detected either from an asserted/detected ``language`` OR, when that is absent, from
    the character composition of the text itself (a CJK/Thai-dominant body with no language tag).
  * headline-LIST pages (moderate density, moderate-to-no punctuation) deliberately ESCAPE this
    gate by construction (the AND-gate only fires on the LOW/LOW corner) -- that is the source-
    level auditor's territory (``src/analytics/source_audit.py``), an honest undercount per this
    criterion's own design, not a gap to be closed here.

Reuses the vendored stopwords-iso lists (``src/services/stopwords.py`` / ``configs/stopwords_iso``)
-- the SAME function-word signal already used for the source-quality audit -- rather than adding
any new dependency; no ``py3langid``, no network, no new stoplist data.

Exposure (house convention, see ``src/analytics/source_audit.py``): the two raw measures are
returned as a plain tuple/float from the PURE functions below for internal composition only -- the
one thing callers act on is the categorical :class:`ProseVerdict` (``signal="nav_soup"``), never a
raw score/ranking/rating/grade field in a returned payload.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.analytics.managed import MANAGED_LANGUAGES, UNSEGMENTED, normalize_lang
from src.services.stopwords import stopwords_manager

# Letters-only "word" tokens (Unicode-aware, digits/underscore excluded) -- deliberately simpler
# than the keyword-extraction tokenizer (src/analytics/extract.py's _WORD_RE): this is a coarse
# density MEASURE, not a term extractor, so it does not need that tokenizer's code-token / roman-
# numeral / markup machinery.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_SENTENCE_PUNCT_RE = re.compile(r"[.!?]")
# CJK ideographs + kana + Hangul syllables + Thai (mirrors src/analytics/extract.py's _CJK_THAI_RE)
# -- the scripts a space-based word regex cannot tokenise, so a run of them collapses into one
# giant "word" and the density measure would be nonsense rather than merely imprecise.
_CJK_THAI_RE = re.compile(r"[぀-ヿ㐀-鿿가-힣฀-๿豈-﫿]")

_MIN_TOKENS = 20              # fewer tokens than this -> unmeasurable, never judge (guard)
_UNSEGMENTED_SCRIPT_SHARE = 0.3  # >= this share of CJK/Thai chars in the letters -> skip, unmeasurable
_DENSITY_LOW = 0.12           # function-word share below this = "not prose" (nav soup ~5%, prose ~40%+)
_PUNCT_LOW = 0.01             # sentence-punct-per-token below this = "not prose" (near-zero periods)


def tokenize_words(text: str | None) -> list[str]:
    """Lowercased letter-run tokens. PURE, no I/O."""
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def _is_unsegmented_script(text: str, *, threshold: float = _UNSEGMENTED_SCRIPT_SHARE) -> bool:
    """True when the text's alphabetic characters are dominated by an unsegmented script (zh/ja/th)
    -- used when no language is asserted, so a raw CJK/Thai body is never scored as low-density
    junk (it would be, since the word-regex globs it into one huge "token")."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    cjk = sum(1 for c in letters if _CJK_THAI_RE.match(c))
    return (cjk / len(letters)) >= threshold


def function_word_density(text: str | None, *, language: str | None = None) -> tuple[float, str | None]:
    """Share of tokens that are function words -- of ``language`` if given (the asserted language),
    else the BEST-MATCHING language (the max density over every managed language's vendored
    stopwords-iso set: real prose in ANY supported language scores high in its OWN language; nav
    junk/product listings score near zero in EVERY language). PURE. Returns
    ``(density, best_matching_language)``; ``(0.0, None)`` for empty/unmeasurable text.

    Uses ``StopwordsManager.get_grammar_stopwords`` -- the PURE closed-class grammar set (no
    NEWS/PLATFORM/publishing-boilerplate domain-curation words folded in), since those curated
    additions are exactly the content-noise a nav/listing page is often saturated with, and would
    blur the very distinction this measure exists for."""
    tokens = tokenize_words(text)
    if not tokens:
        return 0.0, None
    n = len(tokens)
    lang = normalize_lang(language) if language else None
    candidates = [lang] if lang else sorted(MANAGED_LANGUAGES)
    best_density = 0.0
    best_lang: str | None = None
    for cand in candidates:
        if not cand:
            continue
        stops = stopwords_manager.get_grammar_stopwords(cand)
        hits = sum(1 for t in tokens if t in stops)
        density = hits / n
        if density > best_density or best_lang is None:
            best_density = density
            best_lang = cand
    return round(best_density, 4), best_lang


def sentence_punct_density(text: str | None) -> float:
    """Share of sentence-ending punctuation (``.``/``!``/``?``) per token -- near-zero for a bare
    list of menu items/headlines (no sentences), healthy for real prose strung into sentences.
    PURE. Returns ``0.0`` for empty/unmeasurable text."""
    tokens = tokenize_words(text)
    if not tokens:
        return 0.0
    hits = len(_SENTENCE_PUNCT_RE.findall(text or ""))
    return round(hits / len(tokens), 4)


@dataclass(frozen=True)
class ProseVerdict:
    """Why a body was judged nav-soup chrome rather than prose -- a categorical verdict (never a
    raw score), mirroring ``src.ingest.non_article.NonArticleVerdict``."""

    signal: str
    reason: str


def prose_gate_verdict(
    text: str | None,
    *,
    language: str | None = None,
    min_tokens: int = _MIN_TOKENS,
    density_low: float = _DENSITY_LOW,
    punct_low: float = _PUNCT_LOW,
) -> ProseVerdict | None:
    """The PROSE GATE verdict: ``ProseVerdict("nav_soup", ...)`` when the body's function-word
    density AND sentence-punctuation density are BOTH low (word-rich nav/listing chrome), else
    ``None`` (keep -- conservative, matching ``non_article.py``'s own high-precision posture).

    Guards (never drop on a measurement gap): too little text to measure, an unsegmented script
    (zh/ja/th -- asserted/detected OR character-composition-detected), or an ASSERTED language with
    NO grammar vocabulary at all (a managed-but-uncovered language like ``sr``/``az`` -- managed for
    keyword extraction, but ``get_grammar_stopwords`` has nothing for it; scoring that as density
    0.0 would silently degrade the AND-gate to punctuation-only, exactly the single-signal weakness
    the AND exists to avoid), or -- when NO language is asserted at all (the common ingest-path
    shape: ``doc.language`` is only populated when trafilatura's detector fires) -- an auto-search
    that finds ZERO function-word hits in EVERY managed language (the mirror of the asserted-
    language guard, for the untagged path: a real article in any managed language finds SOME
    hits in its own stoplist, so an all-zero result is an untrustworthy measurement, not nav-soup
    evidence) -> ``None``, all guards. A headline-LIST page (moderate density, low-to-no
    punctuation) deliberately escapes the AND-gate -- that undercount is by design (the
    source-level auditor's territory), not a bug here."""
    tokens = tokenize_words(text)
    if len(tokens) < min_tokens:
        return None
    lang = normalize_lang(language) if language else None
    if lang in UNSEGMENTED:
        return None
    if lang is None and _is_unsegmented_script(text or ""):
        return None
    if lang and not stopwords_manager.get_grammar_stopwords(lang):
        return None
    density, best_lang = function_word_density(text, language=lang)
    punct = sentence_punct_density(text)
    if lang is None and density == 0.0:
        # Auto-search found ZERO function-word hits in EVERY managed language's grammar
        # stoplist -- the mirror of the asserted-language guard above, for the (more common,
        # per doc.language's own "guarded" docstring) untagged path: a genuine article in
        # ANY managed language would find SOME function-word hits in its own stoplist, so an
        # all-languages-zero result is an untrustworthy measurement (e.g. a managed-but-
        # grammar-uncovered language's real prose, or a script/encoding the tokenizer can't
        # read), not evidence of nav-soup. Never drop on this signal alone (unmeasurable).
        return None
    if density < density_low and punct < punct_low:
        return ProseVerdict(
            "nav_soup",
            "word-rich nav/listing chrome, not prose: low function-word density "
            f"(best-matching language '{best_lang or lang or 'unknown'}') AND near-zero "
            "sentence-ending punctuation",
        )
    return None


def run_prose_gate_selftest() -> dict:
    """Prove the pure mechanism on hand-built fixtures -- the NAV-SOUP SPECIMEN shape (word-rich,
    punctuation-free menu chrome) vs real multi-language prose (the negative space; a false
    positive here is data loss) vs the guard cases (too-short text, unsegmented script). No DB,
    no I/O, no score."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    # The specimen shape: a long menu of nav/section words, no sentences, near-zero function words.
    nav_soup = (
        "News Latest Irish News Mirror Bingo Soccer Golf Rugby Union Sport Business Politics "
        "World News Travel Money Markets Weather Video Photos Gallery Podcast Newsletters Events "
        "About Contact Home Search Login Sign Up Subscribe Cookies Advertisement Privacy Terms "
        "Follow Facebook Twitter Instagram Newsletter Preference Centre Manage Subscriptions "
        "Menu Toggle Navigation Skip Content Latest News Sport GAA Rugby Soccer Racing Golf Boxing "
        "Motors Showbiz TV Fashion Beauty Food Recipes Property Travel Family Voucher Codes Bingo "
        "Dating Contact Advertise Cookie Policy Privacy Policy Terms Conditions Modern Slavery "
        "Statement Complaints Regulation Archive Sitemap Jobs Shop"
    )
    v = prose_gate_verdict(nav_soup, language="en")
    check("catches_nav_soup_specimen_shape", v is not None and v.signal == "nav_soup", str(v))

    # Real prose, several languages -- the negative space (a false positive drops a real article).
    real_prose = {
        "en": "The government said on Tuesday that it would review the policy after months of "
        "criticism from opposition lawmakers, who argued that the reform had failed to deliver "
        "the promised benefits to the region's struggling economy.",
        "fr": "Le gouvernement a annonce mardi qu'il allait revoir la politique apres des mois de "
        "critiques de la part des parlementaires de l'opposition, qui affirmaient que la reforme "
        "n'avait pas apporte les benefices promis a l'economie de la region.",
        "es": "El gobierno anuncio el martes que revisaria la politica tras meses de criticas de "
        "los legisladores de la oposicion, que argumentaban que la reforma no habia logrado los "
        "beneficios prometidos para la economia de la region.",
        "de": "Die Regierung erklarte am Dienstag, dass sie die Politik nach monatelanger Kritik "
        "von Oppositionspolitikern uberprufen werde, die argumentierten, dass die Reform die "
        "versprochenen Vorteile fur die angeschlagene Wirtschaft der Region nicht gebracht habe.",
    }
    for lang, text in real_prose.items():
        long_text = (text + " ") * 4  # comfortably above the token floor
        v = prose_gate_verdict(long_text, language=lang)
        check(f"keeps_real_prose_{lang}", v is None, f"{lang}: {v}")
        # also verified via best-matching-language search (no asserted language passed)
        v_auto = prose_gate_verdict(long_text)
        check(f"keeps_real_prose_{lang}_auto_language", v_auto is None, f"{lang} auto: {v_auto}")

    # A headline-LIST page deliberately escapes (moderate density is not "low") -- an honest
    # undercount by design, the source-auditor's territory, not this criterion's job.
    headlines = (
        "Storm warning issued for the coast. Markets fall on rate fears. Council votes on new "
        "budget plan. Local team wins the regional final. Weather turns colder into the weekend. "
    ) * 3
    v = prose_gate_verdict(headlines, language="en")
    check("headline_list_escapes_by_design", v is None, str(v))

    # Guards: too little text to measure -> never drop on a gap.
    check("too_short_is_unmeasurable", prose_gate_verdict("News Sport Weather", language="en") is None)

    # Guard: unsegmented script (zh) -> skipped, never dropped on a measurement gap, whether via
    # an asserted language or via character-composition detection with no language given at all.
    zh_text = "中国政府周二表示将审查该政策" * 10
    check("unsegmented_script_skipped_asserted", prose_gate_verdict(zh_text, language="zh") is None)
    check("unsegmented_script_skipped_detected", prose_gate_verdict(zh_text) is None)

    # function_word_density / sentence_punct_density are pure and bounded in [0, 1].
    d, best = function_word_density(nav_soup, language="en")
    p = sentence_punct_density(nav_soup)
    check("density_bounded", 0.0 <= d <= 1.0 and best == "en", f"d={d} best={best}")
    check("punct_bounded", 0.0 <= p <= 1.0, f"p={p}")
    check("nav_soup_is_low_low", d < _DENSITY_LOW and p < _PUNCT_LOW, f"d={d} p={p}")

    passed = all(c["passed"] for c in checks)
    return {
        "schema": "oo-prose-gate-selftest-1",
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": "Hand-built nav-soup/real-prose/headline-list/guard fixtures through "
        "prose_gate_verdict + the underlying pure measures, both should-catch and should-KEEP "
        "(the negative space) across several languages.",
        "caveat": "High-precision, AND-gated by design (both density AND punctuation must be low) "
        "-- a headline-list page deliberately escapes (undercount by design, not a gap). "
        "Unsegmented scripts (zh/ja/th) are skipped, never dropped on a measurement gap. "
        "No score field.",
    }
