# Vendored stopword lists — stopwords-iso

Source:  https://github.com/stopwords-iso/stopwords-iso
Package: stopwordsiso 0.7.0 (PyPI), file stopwords-iso.json
License: MIT (see the upstream repository)
As of:   2026-06

These per-language stopword lists cover the languages the keyword engine could
tokenise (space-segmented) but had NO stoplist for — so their function words
leaked as keywords (the 2026-06-23 keyword-engine report: tr/ro/uk/fi/ur/cs/ca/
sk/et/hi/vi/bn/fa/sw were "no_stoplist", ~88k of the 406k keywords).

They are a SUBSET of stopwords-iso (only the languages we needed), applied
LANGUAGE-SCOPED at extraction — i.e. the Vietnamese list filters only Vietnamese
articles. They are deliberately NOT folded into the language-agnostic global
stopword union, so a short word that is grammatical in one language (e.g. vi
"nam") can never hide a content word ("Nam") in another.

Update: re-run `python scripts/build_stopwords.py` on a networked machine to
refresh from the upstream snapshot, and bump STOPWORDS_ISO_AS_OF in
src/services/stopwords.py + the configs/external_artifacts.yml registry entry.
