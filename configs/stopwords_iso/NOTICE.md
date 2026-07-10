# Vendored stopword lists — stopwords-iso

Source:  https://github.com/stopwords-iso/stopwords-iso
Package: stopwordsiso 0.7.0 (2026-06 waves) / 0.7.1 (2026-07 segmenter wave — the
         two releases emit byte-identical lists for the languages we vendor)
License: MIT (see the upstream repository)
As of:   2026-07

These per-language stopword lists cover the space-segmented languages whose
function words leaked as keywords. Two waves:

- 2026-06-23 keyword-engine report — the original no_stoplist set (tr/ro/uk/fi/
  ur/cs/ca/sk/et/hi/vi/bn/fa/sw), ~88k of the 406k keywords.
- 2026-07-01, live 36k-article / 727k-keyword corpus — German/Russian/Spanish/
  Italian/Portuguese/Dutch and other MANAGED languages still leaked grammar
  (gestern, wurden, вчера, serían …). They were "claimed managed" via small
  hand-grown `_EXTRA_STOPWORD_TEXT` batches, but those were PARTIAL. The FULL
  stopwords-iso lists are vendored here: ar, bg, da, de, el, es, hr, hu, id, it,
  nl, no, pl, pt, ru, sl, sv (and nb, aliased to the Bokmål-based "no" list).
- 2026-07-01 (follow-up) — bs (Bosnian) aliased to the Croatian "hr" list (BCS /
  Serbo-Croatian Latin function words are shared). A hand-curated temporal-deictic
  adverb layer (yesterday/tomorrow: gestern/вчера/mañana/…) lives in
  src/services/stopwords.py CURATED_SCOPED_STOPWORDS — NOT here, because it is not
  from stopwords-iso and build_stopwords.py would overwrite these files. It is merged
  into the same language-scoped channel.

They are a SUBSET of stopwords-iso (only the languages we needed), applied
LANGUAGE-SCOPED at extraction — i.e. the Vietnamese list filters only Vietnamese
articles. They are deliberately NOT folded into the language-agnostic global
stopword union, so a short word that is grammatical in one language (e.g. vi
"nam", or German "man"/"die") can never hide a content word ("Nam", English
"man"/"die") in another. That scoping is exactly what makes vendoring the FULL
Latin-script lists (de 620, es 732, it 632 …) collision-free.

Scope stays closed-class: these are function/auxiliary words (articles, pronouns,
prepositions, conjunctions, copulas/auxiliaries). Open-class content — lexical
verbs (erklärt), adjectives (neuen/green), common nouns — is deliberately kept;
the engine has no POS tagger and those words are dual-use (content in one story,
noise in another). Boilerplate that the keyword-diagnostics log PROVES is junk is
pruned per language via scripts/analyze_keyword_log.py, never a category sweep.

sr/bs/az are managed but ABSENT from stopwords-iso, so they keep their hand-grown
grammar batches in src/analytics/extract.py (not vendored here).

Update: re-run `python scripts/build_stopwords.py` on a networked machine to
refresh from the upstream snapshot, and bump STOPWORDS_ISO_AS_OF in
src/services/stopwords.py + the configs/external_artifacts.yml registry entry.
