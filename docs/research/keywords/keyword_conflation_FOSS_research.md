# Keyword Conflation in Open-Omniscience: FOSS Technology Research

Author of request: Ideotion
Scope: how to stop the keyword engine fragmenting one concept into many rows
(country / country's / countries / governing / governed), and which free,
fully open-source engines and lexical resources can do the unification — with
emphasis on Wikimedia-backed options.
Status: research reference. All sources listed at the end; only DOIs/identifiers
actually verified during research are quoted.


## 1. Diagnosis: what your code actually does

Two keyword paths exist in the repo:

  Path A (legacy)  src/services/keyword_extractor.py + text_processor.py
                   Counter() over tokens. No stemming, no lemmatization.

  Path B (live)    src/analytics/extract.py -> store.py -> families.py
                   spaCy/baseline extraction, then a DISPLAY-time grouping layer
                   (families, equivalence rings, super-groups).

The keying chokepoint is src/analytics/extract.py:

    def _normalize(s: str) -> str:
        s = _ELISION.sub("", s)                 # strips l' d' qu' (Romance)
        return " ".join(s.split()).casefold()   # collapse spaces + lowercase

This is the entire normalization. It strips leading Romance elisions and
lowercases. It does NOT strip a trailing possessive, does NOT stem, does NOT
lemmatize. So "country" -> "country" and "country's" -> "country's" become two
distinct normalized_term values, hence two Keyword rows. That is the root cause.

Important nuance you already half-solved: src/analytics/families.py DOES contain
a possessive collapse (the regexes _POSS_APOS_S = ['']s$ and _POSS_S_APOS = ['']$)
plus honorific stripping and same-kind containment merging. Its own docstring
says the store keeps Trump / Trump's / Donald Trump / President Donald Trump as
four rows and the module groups them "for display ... never deletes or rewrites
the stored rows."

So if you are still seeing country and country's as two separate items, one of
two things is true:

  (a) You are looking at a view that reads raw Keyword rows directly
      (e.g. GET /api/keywords, the keyword-management screen, or a CSV export)
      WITHOUT routing through the families grouping layer; or
  (b) The grouping is applied, but you want conflation that goes beyond the
      possessive/containment rules families.py implements today — i.e. plurals
      (country/countries), verb inflections (govern/governs/governed/governing),
      and cross-form variants that a rule set does not cover.

Either way the fix is the same architectural move: introduce a real
morphological normalization step, and decide whether it runs at WRITE time
(fewer, cleaner rows) or stays at DISPLAY time (rows preserved, grouped on read,
fully reversible — the philosophy your families.py already follows).


## 2. The distinction that determines which tool you need

Your question asks about "keyword engines." There are two different jobs that
get lumped under that phrase, and only one of them is your problem:

  Job 1  CANDIDATE SELECTION / SCORING
         Decide which words or phrases are worth keeping as keywords.
         Tools: YAKE, RAKE, KeyBERT, TextRank, TopicRank, MultipartiteRank,
         KP-Miner, the pke toolkit.

  Job 2  MORPHOLOGICAL CONFLATION / NORMALIZATION
         Map every surface form of one concept to a single canonical key.
         Tools: stemmers (Snowball), lemmatizers (simplemma, spaCy, Stanza),
         lexical databases (Wikidata Lexemes, Wiktionary via Wiktextract),
         and — for named entities — entity linking (OpenTapioca, DBpedia
         Spotlight).

Your "too many keywords / country vs country's" problem is Job 2. Swapping your
extractor for YAKE or KeyBERT will NOT fix it. In fact YAKE is documented to
emit overlapping duplicates of exactly this kind (it returns both "Desired" and
"Desired portions"). The literature comparing these engines treats duplicate
variants as a known weakness, not a feature. Sections 3-6 below cover Job 2
properly; Section 7 covers Job 1 for completeness because you asked for the
engine landscape.


## 3. Rule-based normalization (zero dependencies)

The cheapest possible fix, and the one that resolves your literal example today.
Strip the possessive (both straight ' and typographic ') before keying. This is
already written in families.py — the move is to apply the same two regexes
inside _normalize() so the rows never split in the first place (or to ensure the
view you use passes through families). Pure standard library, no install, works
in every language for the apostrophe-s case, no model, no network.

Limitation: handles possessives and whatever affixes you hand-code. It will not
unify country/countries or govern/governing. For that you need Section 4 or 5.


## 4. Stemmers and lemmatizers (the core conflation layer)

Stemming chops affixes to a crude root ("countries" -> "countri"); fast, broad,
language-light, but the root is often not a real word and over-merges
(university/universe -> univers). Lemmatization maps to a real dictionary form
("countries" -> "country", "ran" -> "run"); more accurate, needs a dictionary or
model. For a searchable journalism corpus, lemmatization is the better fit
because the canonical key stays human-readable in your GUI and exports.

### 4.1 Snowball stemmer (Porter successor)
- What: classic multilingual affix stemmer; the de-facto standard. Elasticsearch,
  Solr, and most search engines use Snowball stemmers by default for indexing.
- Languages: NLTK's SnowballStemmer ships Arabic, Danish, Dutch, English,
  Finnish, French, German, Hungarian, Italian, Norwegian, Portuguese, Romanian,
  Russian, Spanish, Swedish (the upstream Snowball project covers a few more).
- License: BSD (permissive). Available via nltk.stem.snowball and the
  snowballstemmer PyPI package.
- Fit for you: good as a FALLBACK key for languages a lemmatizer misses, or for
  a high-recall search index. In Boolean retrieval, stemming never lowers recall
  (it only broadens matches) — useful for the "find everything" search use case,
  less so for a clean displayed keyword list because stems are not real words.

### 4.2 simplemma  <- best first-line fit for your constraints
- What: a simple multilingual lemmatizer; rule-plus-dictionary, no model server,
  no morphosyntactic input required. Operates on individual tokens, so it drops
  straight into your _normalize() chokepoint.
- Languages: ~49 (current PyPI), identified by BCP-47 tags; includes en, fr, de,
  es, it, pt, nl, ru and more — covering the languages your corpus comments
  mention. Chaining languages is supported, e.g. lemmatize('Vaccines',
  lang=('de','en')) -> 'vaccine'.
- Footprint: pure Python, zero hard dependencies. Optional marisa-trie backend
  cuts memory ~20x and init time ~100x (at some accuracy cost) — relevant for a
  portable/offline Debian app.
- License: MIT (code). Linguistic data licenses are documented per-language in
  the repo's licenses/ folder — worth a glance given your licensing care.
- Evidence: evaluated on Universal Dependencies treebanks; in an independent
  library-science comparison of nine lemmatization methods it was judged the most
  promising simple option — fast, broad language coverage, decent (never top, but
  solid) accuracy.
- DOI: 10.5281/zenodo.4673264

### 4.3 spaCy lemmatizer
- What: rule-based lemmatizer (lookup tables + edit-tree component) inside the
  industrial spaCy pipeline; you already pull spaCy via Pillar 3.
- Languages: lemmatization quality is per-language and depends on installing the
  matching model; coverage is narrower than Stanza or simplemma for lemmatization
  specifically (historically strong for English, expanding for others).
- License: MIT. Note: spaCy does NOT provide stemming, only lemmatization.
- Fit: natural if you standardize the whole analytics pipeline on spaCy anyway,
  and it gives you POS context so you lemmatize verbs vs nouns correctly.

### 4.4 Stanza (Stanford NLP)
- What: fully neural UD pipeline (tokenize, POS, morphology, lemmatize, parse,
  NER). Lemmatizer is an ensemble of a dictionary lookup and a neural seq2seq
  model, trained on Universal Dependencies treebanks.
- Languages: 66 in the original release; 70+ in current versions — the widest
  language coverage of the mainstream pipelines. NER for a selected subset.
- License: Apache 2.0 (permissive).
- Cost: heaviest of the four (neural models, slower, larger download). Best when
  you want top accuracy and very broad language coverage and can afford the
  compute. There is a spacy-stanza wrapper to run Stanza models inside spaCy.

### 4.5 NLTK WordNet lemmatizer
- What: dictionary lemmatizer over Princeton WordNet.
- Languages: English-centric. License: permissive (WordNet + NLTK Apache).
- Fit: fine for an English-only path; not a multilingual answer on its own.


## 5. Wikimedia lexical resources (your explicit ask)

These are the "from foundations such as Wikimedia" options. They are not engines
you run; they are open lexical databases you turn into a form -> lemma lookup
table offline, then consult at keying time. This is the most auditable and the
most on-brand option for your project, and you are already on this path: your
scripts/generate_wikidata_rings.py builds configs/keyword_rings_generated.yml
from Wikidata labels, and src/analytics/equivalence.py consumes them.

### 5.1 Wikidata Lexemes (lexicographical data)  <- the precise tool for your example
- What: structured words/forms/senses on Wikidata. A Lexeme has a lemma and a
  set of Forms. The canonical example in the documentation is the verb "run" =
  {run, runs, ran, running} with lemma "run" — exactly the unification you want.
  The English noun "table" lists forms table, tables, table's, tables' — i.e.
  the possessive forms are modelled explicitly, so a Lexeme lookup maps
  "country's" -> the country lexeme -> lemma "country" by data, not by regex.
- Coverage: many languages, but incomplete versus Wiktionary; coverage varies a
  lot by language and part of speech.
- License: CC0 (public domain dedication). This is the cleanest license of any
  resource here — no attribution or share-alike obligations.
- Access: SPARQL via the Wikidata Query Service, or the lexeme dumps. Example —
  canonical forms of all English noun lexemes:

      SELECT ?lexeme ?lemma WHERE {
        ?lexeme dct:language        wd:Q1860 ;   # English
                wikibase:lexicalCategory wd:Q1084 ; # noun
                wikibase:lemma      ?lemma .
      }

  To build a conflation map you query each Form representation and its Lexeme's
  lemma, producing a {surface_form -> lemma} dictionary per language, shipped as
  a local file (mirrors how you already ship keyword_rings_generated.yml).
- Fit: extend generate_wikidata_rings.py to also pull Lexeme forms. You get a
  CC0, offline, multilingual, fully-auditable form->lemma table with QID
  provenance for every mapping — consistent with your "honest by construction"
  and no-fabrication standards.

### 5.2 Wiktionary via Wiktextract / kaikki.org  <- broadest coverage
- What: machine-readable extraction of Wiktionary. Inflected/abbreviated/
  alternative-form entries are recognized, linked to their base form, and tagged.
  It fully expands Wiktionary's Lua templates, so inflection tables are captured,
  not just headwords.
- Coverage: hundreds of languages from the English Wiktionary alone; the paper
  reports coverage for non-English languages often matches or exceeds the
  language-specific Wiktionary editions. This is the highest-coverage free
  morphological resource available.
- License: Wiktionary content is CC BY-SA. So a derived form->lemma table carries
  attribution + share-alike obligations (unlike Wikidata Lexemes' CC0). The
  Wiktextract tool code is separately free for commercial and non-commercial use;
  the obligation is on the DATA. Given your licensing sensitivity, this is the
  key trade-off versus 5.1: much more coverage, heavier license.
- Access: pre-extracted JSONL dumps at kaikki.org, updated roughly weekly
  (raw ~21 GB, ~2.5 GB compressed; an English-only subset ~2.4 GB). You filter to
  form-of relations and build the lookup once, offline.
- Cite: Ylonen, T. (2022), Wiktextract: Wiktionary as Machine-Readable
  Structured Data, LREC 2022, pp. 1317-1325.
- Fit: use as the high-coverage layer, with Wikidata Lexemes (CC0) preferred
  whenever both have the form, so the cleaner license wins on collision — the
  exact precedence pattern your equivalence.py already uses (curated ring wins
  over generated ring).

### 5.3 Related Wikimedia-derived entity resources
- DBpedia Spotlight: entity recognition + linking against DBpedia (extracted
  from Wikipedia infoboxes/categories). Mature, multilingual, self-hostable.
- See Section 6 for OpenTapioca, which links to Wikidata directly.


## 6. Entity linking to Wikidata (the gold standard for the journalism core)

For named entities — people, organizations, places — morphological lemmatization
is the wrong tool. "Trump", "Trump's", "Donald Trump", "President Donald Trump",
"Дональд Трамп" should all collapse to ONE canonical entity, and the principled
way to do that is to link each mention to a Wikidata QID and key on the QID. This
is the natural successor to the same-kind containment merging in your families.py,
and it dovetails with the Wikidata rings you already generate.

- OpenTapioca: a lightweight Named Entity Linker trainable from Wikidata ONLY.
  It indexes (by default) humans, organizations, and geographic objects, can be
  kept in near real-time sync with live Wikidata, and is simple to reproduce and
  self-host. A spaCy wrapper exists (spaCyOpenTapioca) so it slots into a spaCy
  pipeline. Best fit for your offline-first, Wikidata-aligned, FOSS design.
  Cite: Delpeuch, A. (2019), OpenTapioca: Lightweight Entity Linking for Wikidata.
- DBpedia Spotlight: links to DBpedia/Wikipedia; mature and multilingual; an
  alternative if you prefer the DBpedia knowledge base.
- Others in the literature (for context, varying license/footprint): Babelfy/
  BabelNet, Falcon 2.0, REL (Radboud Entity Linker), ReFinED, TagMe. Most are
  heavier or have license constraints; OpenTapioca is the cleanest match to your
  constraints.

Design payoff: keep the morphological lemma key for ordinary topical terms
(Sections 4-5), and add a QID key for entities. Your families.py containment rule
becomes a fallback for entities OpenTapioca cannot link, rather than the primary
mechanism.


## 7. Keyword extraction engines (Job 1 — the landscape you asked to see)

These choose and score candidate keywords. They are orthogonal to your
fragmentation problem, but here is the open-source field, since you asked. All
are free/open-source and run offline.

Statistical (fast, language-light):
- YAKE — single-document, statistical (casing, position, frequency, context).
  Fast, multilingual. Known to emit overlapping/duplicate candidates — the same
  fragmentation symptom you are fighting, so it is not a fix.
- RAKE — Rapid Automatic Keyword Extraction; among the fastest; simple; stopword
  handling is basic.
- KP-Miner — modified TF-IDF with length/position filtering; in one comparative
  study the most consistent on f-score across short and long texts.

Graph-based (better on long documents):
- TextRank — PageRank over a word co-occurrence graph.
- SingleRank / TopicRank / TopicalPageRank / PositionRank / MultipartiteRank —
  refinements; TopicRank and MultipartiteRank perform well on long text because
  they rank topics rather than raw words.

Embedding-based (semantic, heavier):
- KeyBERT — ranks candidate phrases by BERT-embedding similarity to the document;
  in comparative studies KeyBERT(mmr) often has the best f-score but is the
  slowest and needs a transformer model. You already ship sentence-transformer
  models (all-mpnet-base-v2), so the dependency cost is partly paid.

Toolkit that bundles most of the above:
- pke (Python Keyphrase Extraction) — open-source toolkit implementing TopicRank,
  MultipartiteRank, SingleRank, PositionRank, TopicalPageRank, KP-Miner, TextRank,
  TfIdf, YAKE, KEA. Uses spaCy for preprocessing, multilingual, and exposes a
  normalization='stemming' option (Porter) — i.e. it can apply Job-2 stemming
  during Job-1 extraction. If you ever want to upgrade candidate selection, pke
  is the single dependency that gives you the whole menu.
  Cite: Boudin, F. (2016), pke: an open source python-based keyphrase extraction
  toolkit, COLING 2016 demos, pp. 69-73.


## 8. Master comparison

Legend: Off = runs fully offline; Foot = footprint (S small / M medium / L large).

Job 2 — conflation (THE fix for your problem):

  Tool                Category        Languages     License      Off  Foot  Notes
  ------------------- --------------- ------------- ------------ ---- ----- ---------------------------------
  Possessive regex    rule-based      all (apos)    n/a (yours)  yes  S     already in families.py; literal fix
  Snowball            stemmer         ~15 (NLTK)    BSD          yes  S     search-index recall; stems not words
  simplemma           lemmatizer      ~49           MIT          yes  S     best first-line multilingual fit
  spaCy lemmatizer    lemmatizer      per-model     MIT          yes  M     already a dep; POS-aware; no stemming
  Stanza              lemmatizer+NER  66 (70+)      Apache-2.0   yes  L     widest coverage; neural; slowest
  WordNet (NLTK)      lemmatizer      English       permissive   yes  S     English-only
  Wikidata Lexemes    lexical DB      many          CC0          yes  M     models forms incl. possessives; QID
  Wiktextract/kaikki  lexical DB      hundreds      CC BY-SA     yes  L     broadest coverage; share-alike data
  OpenTapioca         entity linking  multilingual  open/Wikidata yes M    entities -> QID; the entity gold std
  DBpedia Spotlight   entity linking  multilingual  open         yes  M    entities -> DBpedia

Job 1 — extraction (NOT your fix; for completeness):

  Tool          Type        Speed   Notes
  ------------- ----------- ------- --------------------------------------------
  YAKE          statistical fast    multilingual; emits duplicate variants
  RAKE          statistical fastest simple; basic stopword handling
  KP-Miner      statistical fast    most consistent f-score across text lengths
  TextRank      graph       medium  classic co-occurrence PageRank
  TopicRank     graph       medium  strong on long text (ranks topics)
  MultipartiteRank graph    medium  strong on long text
  KeyBERT       embedding   slow    best f-score (mmr); needs transformer model
  pke (toolkit) all above   varies  one dep for the whole menu; spaCy preproc


## 9. Recommended architecture (layered, tailored to your repo)

This mirrors the philosophy already in families.py: store everything, conflate by
explainable layers, keep it reversible and auditable. Apply the layers in order;
the first that yields a canonical key wins, and you record WHICH layer keyed it
(you already store an `extractor` provenance field on Keyword — add a parallel
`conflated_by` so every merge is explainable).

  L0  Possessive + whitespace normalization        (stdlib; you have the regexes)
      -> resolves country's today. Move the families.py possessive regexes into
         _normalize(), or guarantee every keyword view passes through families.

  L1  simplemma lemmatization at the chokepoint     (MIT, offline, ~49 langs)
      -> resolves country/countries, govern/governing/governed across languages.
         Lemmatize per the article's detected language (you already have
         src/analytics/langdetect.py). Falls back to Snowball stem for languages
         simplemma lacks, if you want maximum recall in the search index.

  L2  Wikimedia lexical override map                (CC0 first, CC BY-SA second)
      -> Wikidata Lexemes (CC0) gives an auditable, QID-backed form->lemma table;
         optionally backfill gaps from Wiktextract (CC BY-SA), CC0 winning on
         collision. Built offline by extending generate_wikidata_rings.py; ships
         as a local file like keyword_rings_generated.yml. This is where the
         hard cases the lemmatizer misses get a curated, sourced answer.

  L3  Entity linking to Wikidata QIDs               (OpenTapioca, self-hosted)
      -> for is_entity terms, key on the QID so Trump / Donald Trump / President
         Donald Trump / the Cyrillic form collapse to one canonical entity.
         families.py containment becomes the fallback for unlinkable entities.

Where it plugs in:
- src/analytics/extract.py :: _normalize()      -> L0 + L1 (term keying)
- src/analytics/store.py   :: _get_or_create_keyword() -> read canonical key;
                              write conflated_by provenance
- src/analytics/families.py                     -> L3 fallback; keep as the
                              transparent display grouping it already is
- configs/                                      -> L2 lexeme map + L2 license note
- existing equivalence.py rings                 -> unchanged; cross-language layer
                              sits ABOVE L1/L2 (élection/elections/election ring)

Write-time vs display-time: your current design conflates at DISPLAY time and
preserves rows. You can keep that — run L0/L1/L2 to compute the canonical key
used by the grouping/read model, leaving stored rows intact and the merge
reversible. Or move L0/L1 to WRITE time for a smaller, cleaner keyword table
(fewer rows, faster aggregations) at the cost of reversibility. Given your
"honest, reversible, never rewrite the stored row" stance, computing canonical
keys for the read model while preserving raw rows is the more consistent choice.


## 10. Honest caveats

- Over-conflation is real. Stemmers merge unrelated words (universe/university).
  Lemmatizers mislabel without POS (saw the tool -> see, vs the noun saw). Run
  lemmatization with POS context (spaCy/Stanza give it) where precision matters.
- Language detection is now load-bearing. A multilingual lemmatizer needs the
  right language per text; a wrong guess yields wrong lemmas. You already have
  langdetect.py — its accuracy becomes part of the conflation quality.
- Coverage gaps. Wikidata Lexemes is incomplete; Wiktextract is broad but its
  data is CC BY-SA. Decide per your licensing posture whether CC BY-SA data may
  ship in the app, or whether you stay CC0-only (Lexemes) and accept lower
  coverage.
- Entity linking can mislink (wrong QID). Keep the link as a labelled assertion
  with its confidence and source — exactly how your schema already treats
  entity_type ("a labelled-by-X assertion, never ground truth").
- None of this needs the cloud. Every option in Sections 3-6 runs offline, which
  matches the project's local-only design.


## 11. References (verified during research)

Lemmatizers / stemmers
- simplemma — adbar/simplemma (MIT). DOI 10.5281/zenodo.4673264.
  https://github.com/adbar/simplemma ; https://pypi.org/project/simplemma/
- Stanza — Qi, P. et al. (2020), Stanza: A Python NLP Toolkit for Many Human
  Languages. arXiv:2003.07082. https://stanfordnlp.github.io/stanza/
- spaCy — https://spacy.io ; spacy-stanza https://github.com/explosion/spacy-stanza
- Snowball / NLTK SnowballStemmer — https://www.nltk.org (nltk.stem.snowball)
- Lemmatizer comparison (library science) — Code4Lib Journal, Annif Analyzer
  Shootout. https://journal.code4lib.org/articles/16719

Wikimedia lexical / entity resources
- Wikidata Lexicographical data (CC0) — https://www.wikidata.org/wiki/Wikidata:Lexicographical_data/Documentation
  Glossary (run/runs/ran/running example): .../Lexicographical_data/Glossary
- Wiktextract — Ylonen, T. (2022), Wiktextract: Wiktionary as Machine-Readable
  Structured Data, LREC 2022, pp. 1317-1325.
  https://aclanthology.org/2022.lrec-1.140/ ; data: https://kaikki.org/dictionary/rawdata.html
  code: https://github.com/tatuylonen/wiktextract
- OpenTapioca — Delpeuch, A. (2019), OpenTapioca: Lightweight Entity Linking for
  Wikidata. arXiv:1904.09131 ; spaCy wrapper https://spacy.io/universe/project/spacyopentapioca
- DBpedia Spotlight — https://www.dbpedia-spotlight.org

Keyword extraction engines
- pke — Boudin, F. (2016), pke: an open source python-based keyphrase extraction
  toolkit, COLING 2016 demos, pp. 69-73. https://github.com/boudinfl/pke
- YAKE — Campos, R. et al. (2020), YAKE! Keyword extraction from single documents
  using multiple local features, Information Sciences 509, pp. 257-289.
- RAKE — Rose, S. et al. (2010), Automatic keyword extraction from individual
  documents, in Text Mining: Applications and Theory.
- TextRank — Mihalcea, R. & Tarau, P. (2004), TextRank: Bringing Order into Text,
  EMNLP 2004.
- TopicRank — Bougouin, A., Boudin, F., Daille, B. (2013), IJCNLP 2013, pp. 543-551.
- MultipartiteRank — Boudin, F. (2018), NAACL 2018.
- KeyBERT — Grootendorst, M. (2020), KeyBERT: Minimal keyword extraction with BERT.
- Comparative assessment of unsupervised keyword extraction tools — IEEE Access
  (2023), survey finding KP-Miner most consistent and KeyBERT(mmr) strongest on
  f-score, RAKE/YAKE fastest.

Note on identifiers: only the DOI for simplemma (10.5281/zenodo.4673264) and the
arXiv IDs above were directly verified in source pages during this research. The
YAKE Information Sciences article's journal DOI was not re-verified here and is
therefore cited by title/venue/pages only, per the project's no-fabricated-
citation standard.
