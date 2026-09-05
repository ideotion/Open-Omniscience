# Extra-stopword evidence trail (Phase 4.1 migration)

Preserved **verbatim** from `src/analytics/extract.py`'s `_EXTRA_STOPWORD_TEXT` inline
comments before the Phase 4.1 migration (PR #740/#744 remediation) split the word lists
into `configs/stopwords_extra/<lang>.yml`. This is the historical justification for each
batch -- field-log dates, corpus sizes, mention counts, and collision-safety reasoning --
kept for anyone auditing why a given word is a stopword.

```
# English fillers the base set lacks
# Relative time + news-attribution fillers users flagged as noise
# Contractions (ASCII; curly-apostrophe variants are added programmatically below)
# Spanish
# German
# Italian
# Portuguese
# Dutch
# French (was MISSING entirely — the 2026-06-11 field log leaked dans/plus/
# pas/aux/ont/ses… as top "entities"; added with elision combos + fillers)
# Month names leak as entities ("June" en:317, "Juin" fr:68 in the field log)
# English generics observed leaking as entities in the field log
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
# Spanish (extends the thin block above; 48 leaked words, 5,754 mentions)
# German (48 leaked, 8,194 mentions: sich/bei/wie/aus/über/nach/einem/einen…)
# Italian (42 leaked, 3,230 mentions: alla/dei/nel/più/delle/anche…)
# Portuguese (20 leaked: não/ele/também/até/foram/seu/ela…)
# Dutch (34 leaked, 10,257 mentions — the worst: dat/voor/hij/uit/bij/naar…)
# Russian (54 leaked, 2,658 mentions: что/для/как/его/также/это/при/более…)
# Swedish (30 leaked, 3,752 mentions: som/har/det/och/för…)
# Norwegian bokmål (30 leaked: til/jeg/seg/ble/også/hadde/ved/når…)
# Danish (9 leaked; same family as nb/sv — completes the Scandinavian set)
# Polish (42 leaked, 2,789 mentions: się/jest/jak/przez/czy/dla…)
# Hungarian (32 leaked: hogy/nem/egy/már/volt/vagy/még/több…)
# Arabic (22 leaked, 1,417 mentions: على/إلى/هذا/التي/هذه/كما/ذلك…)
# Serbian/Croatian/Bosnian latin (30 leaked: kako/još/sve/više/biti/kada…)
# Turkish (26 leaked: için/olarak/daha/çok/veya/ancak/gibi/değil…)
# Indonesian (33 leaked: untuk/ini/dengan/itu/adalah/pada/juga…)
# Finnish (16 leaked: että/olla/hän/myös…)
# Hindi (1 leaked — अगर; the conjunction/pronoun core completes the policy)
# Second evidence pass (same export, post-policy survivors): inflected
# function words, modals, attribution verbs and date-generics that the
# core sets miss — plus month names beyond en/fr (es "junio"×257 and
# ru "июня"×133 leaked exactly like the en/fr months above).
# nl
# sv
# es
# de
# it
# ru
# nb
# Field log (2026-06-14 keyword-diagnostics export, 1,201-article corpus;
# surfaced via scripts/analyze_keyword_log.py). The de-US-centred corpus kept
# leaking per-language FUNCTION words the earlier passes missed, plus WEEKDAY
# names (the month blocks above never covered weekdays: "Sunday"/"sábado"/
# "lørdag" sat among the top keywords) and comment-widget/paywall BOILERPLATE.
# Net-new vs the blocks above; applied retroactively by global_stopwords().
# Names, places and content words the analyzer flagged stay OUT (its 'review'
# bucket); cross-language collisions (sea/tom/fin/laut…) deliberately omitted
# because this set is unioned across ALL languages.
# Weekday names across the corpus languages (fr weekdays already covered above)
# French function words still leaking (afin/lire la suite/doit/soit/à travers)
# Spanish function words + number/temporal generics
# German modals / conjunctions / adverbs
# Italian auxiliaries / prepositions / adverbs
# Portuguese function words
# Russian conjunctions / pronouns / adverbs / aux
# Danish function words + paywall/comment boilerplate (læs/adgang/dagens)
# Polish function words + temporal
# Hungarian function words + temporal/number generics
# Serbian/Croatian function words + comment-widget boilerplate
# Slovenian function words
# Arabic prepositions / conjunctions
# Indonesian function words
# Field log (2026-06-17 keyword-diagnostics export, 2,324-article corpus). The
# per-source concentration suspects surfaced LOGIN/SUBSCRIBE widget chrome that
# appears in ~every article of a source (share_of_source ≈ 1.0) — pure UI, not
# content. ONLY unambiguous chrome + pure function words are added; dual-use
# platform NAMES (facebook/twitter/telegram…) and content-capable words
# (comments/follow/correo/electrónico) are deliberately left OUT (a story may be
# ABOUT them), staying visible in the diagnostics for a maintainer ruling.
# French account-wall chrome (Le Nouvelliste: connectez-vous/inscrivez-vous in
# 27/27 of its articles) + leaked function words (selon/lors/avez):
# English subscribe button:
# Round-2 of the same 2026-06-17 export: PURE function words still leaking in
# the higher-volume non-English corpora (analyzer "high-confidence" bucket,
# hand-filtered). Deliberately CONSERVATIVE because global_stopwords() is
# unioned across ALL languages: every word here is either accented (so it
# can't be a content token in another corpus language) or unambiguous grammar
# that is not an English/name homograph. Cross-language homographs were
# EXCLUDED on purpose — mint/nun/sei/seine (de), ska/nye/nyt/ole (Nordic/fi
# collide with ska-genre / Bill Nye / NYT / the name Ole), dana/nagy/srbije
# (names/places), kroner/ritzau (currency / the Ritzau agency name).
# German
# Hungarian
# Serbian
# Swedish
# Norwegian
# Danish
# Finnish
# Azerbaijani postposition (Meydan TV per-source concentration)
# Universal WEB-MARKUP / URL junk (2026-06-18 field log: a source whose page
# chrome leaked into the indexed content turned 'https', 'www', 'img',
# 'margin-left', … into top keywords). These are never meaningful content in
# ANY language, so the global union is safe. NB: the real fix is stripping
# HTML/CSS/URLs from article content BEFORE extraction (a content-extraction
# issue, flagged separately) — this only stops the markup that still leaks
# from polluting keywords. Dual-use words (table/body/icon/html/css) are
# deliberately left OUT (a story may be about them).
# 2026-06-18 keyword-log: the highest-volume no_stoplist languages (el 4992,
# uk 3684, bg 3090 keywords) leaked their grammar into the index. These are
# GREEK and CYRILLIC scripts, so the global union can never collide with a Latin
# corpus language; cross-Cyrillic overlap (bg/uk/ru/sr) is fine — a shared
# function word is a stopword in each. Hand-filtered to PURE grammar (articles,
# prepositions, pronouns, conjunctions, common auxiliaries); content/entities/
# months were excluded on purpose (el: ηπα/ιράν/τραμπ/πηγές; bg: българия/юни/
# евро/софия/директор; uk: україни/нато/завод/червня + the ru-mislabelled forms).
# el promotes to MANAGED (src/analytics/managed.py); uk stays gated (its sample
# mixed ru-spelled tokens, so the language signal is not yet trustworthy).
# Greek
# Greek
# Greek
# Bulgarian
# Bulgarian
# Bulgarian
# Ukrainian
# 2026-06-21 keyword-log (29k-article corpus): more CSS/markup leaked into the
# unknown-language ('?') bucket (table/width/div/block-1/max-width/font-size) — the
# root fix is HTML/CSS stripping before extraction (flagged), this stops the markup
# that still leaks. Only UNAMBIGUOUS CSS/HTML tokens (never natural content in any
# language); dual-use (table/width/body/icon) deliberately left OUT.
# de dialectal weekday the month/weekday pass missed (Saturday).
# Pure grammar still leaking in the higher-volume corpora (analyzer high-confidence,
# hand-filtered per the standing rule: accented OR unambiguous grammar, no English/
# name homograph, no cross-language content collision).
# Spanish
# Italian
# Portuguese
# Polish
# Slovenian
# Swedish
# Norwegian
# Turkish (accented; promotes toward managed)
# 2026-06-22 (field test, engine report): hi + bn are UI languages but were
# no_stoplist, leaking grammar into the index ("give them stoplists … hi/bn no
# longer no_stoplist"). DEVANAGARI + BENGALI scripts, so the global union can
# NEVER collide with a Latin/Cyrillic/Greek corpus language. Hand-filtered to
# PURE grammar (postpositions, pronouns, conjunctions, common auxiliaries);
# content nouns, names and months were excluded on purpose. Both promote to
# MANAGED (src/analytics/managed.py).
# Hindi
# Hindi
# Bengali
# Bengali
# 2026-06-22 field test, remainder batch (engine report no_stoplist tail).
# Adding more of the corpus languages the engine could not analyse. Two
# collision-safety classes, both honouring the standing union rule:
#   (1) DISTINCT-SCRIPT languages are collision-free by construction — Arabic
#       script (fa/ur) and Cyrillic (uk expansion) can NEVER overlap a Latin/
#       Greek content word; cross-script overlap (fa↔ar, uk↔ru/bg) is fine (a
#       shared function word is a stopword in each). Hand-filtered to PURE
#       grammar (pronouns, prepositions, conjunctions, common auxiliaries).
#   (2) LATIN languages add ONLY length>=4 distinctive grammar OR accented
#       words (the accent/length makes a content-word collision in es/it/pt/
#       en/de/nl effectively impossible); every short unaccented homograph was
#       EXCLUDED by hand (ro "cine"=es cinema; sk "bola/bolo"=es/pt ball/cake;
#       ca "sense/fins"=en sense/fins; sw "wake/sana/kama"=en wake / es heal /
#       name). These languages tokenise whole words (verified 2026-06-22), so
#       they promote to MANAGED in src/analytics/managed.py.
# Persian (fa) — Arabic script:
# Urdu (ur) — Arabic script:
# Ukrainian (uk) — Cyrillic; expands the gated 2026-06-18 set into a full
# function-word stoplist (the union filters these regardless of the ru-mislabel
# noise that kept uk gated; uk tokenises whole words, so it promotes now).
# Romanian (ro) — Latin, len>=4 / accented (short homographs excluded):
# Czech (cs) — Latin, len>=4 / accented ('ale'=ale beer, 'ano'=pt year EXCLUDED):
# Slovak (sk) — Latin, len>=4 / accented ('bola/bolo'=es/pt ball/cake EXCLUDED):
# Catalan (ca) — Latin, len>=4 / accented ('sense'=en, 'fins'=en EXCLUDED):
# Swahili (sw) — Latin, distinctive ('wake'/'sana'/'kama' EXCLUDED):
# Azerbaijani (az) — Latin, accented ('amma'/'kimi' name homographs EXCLUDED):
# Estonian (et) — Latin, len>=4 / accented ('aga'=name homograph EXCLUDED):
# languages leaked their grammar. Korean (Hangul) + Marathi (Devanagari) are DISTINCT
# scripts, so the language-agnostic union is collision-free with the Latin/Arabic/
# Cyrillic/CJK corpus languages (mr shares Devanagari only with the managed hi — a
# shared function word is a stopword in both, which is fine). Sourced from stopwords-iso
# INTERSECTED with the ACTUAL leaked keywords (so each word is BOTH a curated function
# word AND observed leaking); CONTENT excluded (mr जात=caste, कोटी=crore,
# माहिती=information/RTI, कमी=shortage). Native review welcome. ko/mr STAY no_stoplist
# (agglutination means much still leaks) — a partial, collision-free win, not a promotion.
# Korean (ko) — Hangul; connectives/adverbs (하지만=but, 그러나=however, 따라서=therefore):
# Marathi (mr) — Devanagari; copulas/conjunctions/pronouns/auxiliaries (आहे=is, आणि=and, नाही=not):
```

## English light verbs / quantifiers — source-quality export 2026-08-11

Evidence: the `oo-source-quality-2` bundle of 2026-08-11 (1,047,146-article corpus,
2,247 sources with articles, 241 of them carrying a non-empty top-12 fingerprint).
**101 of those 241 fingerprints (41.9%) spend at least one top-12 slot on a contentless
English word** — 4.1% of fingerprint mentions (9,000 of 217,600). The `per_source_keywords`
fingerprint is the analyst's first read of whether a source is broken, so a wasted slot
costs legibility out of proportion to the mention volume.

Added (source-fingerprint count in brackets): `down` [29], `every` [16], `set` [15],
`best` [15], `read` [11], `find` [9], `added` [8], `end` [8], `went` [5], `look` [5],
`hours` [2]. Same class as the existing block (`according`/`across`/`ago`/`amid`/
`among`/`back`/`bad`/`big`) — none was present in any `stopwords_extra` file or
hard-coded in `extract.py`/`stopwords.py` before this batch.

**Collision review — these were observed leaking and DELIBERATELY NOT added**, because
`global_stopwords()` unions every file here LANGUAGE-AGNOSTICALLY, so a word that is
content in any corpus language (or in another English sense) must not be globalised:

| rejected | fingerprints | why it stays a keyword |
|---|---|---|
| `top` | 13 | nl *top* = summit (`EU-top`) — a topic, not furniture |
| `post` | 9 | de/nl *Post* = mail/postal service |
| `show` | 9 | de *Show* is a noun (a programme) |
| `access` | 9 | content in its own right — "access to water/healthcare" |
| `home` | 9 | content in housing/homelessness reporting |
| `right`, `left` | 7, 6 | political direction — unambiguously content in a news corpus |
| `life` | 13 | content — "life expectancy", "cost of living" |
| `put` | 4 | en finance: a *put* option (the corpus carries `finance.yahoo.com`) |

The corpus could not corroborate or refute the collisions on its own: no non-English
source carries any candidate in its fingerprint, but only 241 sources have a fingerprint
at all and most are English, so that is absence of evidence rather than evidence of
absence. The rejections above rest on linguistic review, not on the export.

`hidden_set()` unions `global_stopwords()` at QUERY time
(`src/analytics/filters.py:121`), so this batch is retroactive with no re-index;
`extract.py:436` also filters at EXTRACTION time, so applying it BEFORE a large
re-index additionally stops the rows being written at all.

---

## Re-filing the two misfiled blocks (2026-09-05)

The Phase 4.1 split (PR #740/#744) turned one flat blob into per-language files. Two
blocks landed under the wrong filename, and **both were behaviourally invisible** because
`global_stopwords()` unions every file here language-agnostically — the union is what the
engine reads, so a word in the wrong file is filtered exactly as if it were in the right
one. The cost is not behavioural; it is that a **filename became false about its
contents**, and a reader who trusts one measures the wrong thing:

* `hi.yml` ("Hindi") held **63 non-Devanagari entries** — 39 Latin and 24 Cyrillic month
  names (`abril`, `märz`, `января`, …) beside its 72 genuine Devanagari words. This is
  the block the 2026-09-05 keyword-translation research pass read past: pass 1 reported
  the month stoplist covered "exactly two of twelve UI languages" because it read
  `_multilingual.yml` alone; the corrected figure over the whole union is **seven**
  (en/fr/de/es/ru 12/12, id 9/12, pt 2/12; ar/hi/bn 0/12).
* `ru.yml` ("Russian") held **61 Latin entries** — Polish (`aby`, `oraz`, `może`,
  `roku`, `które`, `również`), Hungarian (`ahogy`, `kell`, `mondta`, `szerint`, `után`,
  `így`), Danish/Norwegian (`ikke`, `ingen`, `læs`, `første`, `dagens`), and BCS
  (`ili`, `kao`, `nakon`, `nije`, `pročitajte`, `što`) function words beside its 115
  genuine Cyrillic ones. **This one was not in the research pass's findings** — it was
  found by auditing every file's script composition while fixing the first.

**Both blocks moved to `_multilingual.yml`.** That destination is deliberate and is the
conservative choice, not the tidy one: files exist for `pl`, `hu`, `da`, `nb`, `sl` and
`sr`, but several of the 61 words are genuinely ambiguous between them (`ili`/`tako` are
BCS *and* Slovene shapes; `kun`/`vil`/`ikke` are Danish *and* Norwegian), so a per-language
re-filing would have to **assert 61 language attributions we cannot check** — inventing
provenance to make a filename prettier. `_multilingual.yml` is the one filename that is
*true* of a mixed block. A finer per-word attribution stays available later, on evidence.

**The move is set-identical, and that is provable rather than asserted:**
`tests/test_analytics_extract.py::test_extra_stopwords_migration_is_byte_identical_to_the_pre_migration_blob`
hashes the whole union against the pre-migration digest and is untouched by this change
(`git diff --numstat` shows 118 added / 124 removed / **0 modified** — 118 rather than 124
because six month names already existed in `_multilingual.yml`).

**The durable half is the guard, not the move.** `tests/test_stopword_file_scripts.py`
asserts that every file named for a language written in a NON-LATIN script contains only
that script, so this class cannot regrow silently. It is honest about its own reach: it
can say nothing about the Latin-script files, because Polish in `pl.yml` and Polish in
`en.yml` look identical to a script check. That half of the class stays uncaught, and the
test says so rather than implying whole coverage.
