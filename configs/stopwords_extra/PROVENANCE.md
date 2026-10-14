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

### The four standing cross-language refusals (`sea` · `tom` · `fin` · `laut`)

Recorded here 2026-09-07 (PRH-11). These were refused by the 2026-06-14 batch and the
refusal lived as a parenthetical mid-file — *"cross-language collisions (sea/tom/fin/laut…)
deliberately omitted"* — with no reason per word and no statement of where each one IS
handled. A future batch re-proposing them would have found the words but not the argument,
which is how a reasoned refusal becomes a re-litigated one.

They are not one case but two, and the difference is the whole point. Measured against the
live channels on 2026-09-07 (`StopwordsManager.get_stopwords` per language, and
`global_stopwords()`):

| word | in the GLOBAL union | scoped languages that already filter it | the content sense the union would have hidden |
|---|---|---|---|
| `sea` | no | `es` | en *sea* — a body of water, plainly content |
| `tom` | no | `cs`, `sk` | a given name; sv/no/da *tom* = empty |
| `fin` | no | `es`, `it`, `sv` | en *fin* — of a fish; and *fin de siècle* as a topic |
| `laut` | no | **none — not even `de`** | id *laut* = sea (the app ships an Indonesian locale and Indonesian sources) |

For the first three the refusal is not a gap at all: each is a function word in some
language, each is ALREADY filtered there by the language-SCOPED channel
(`configs/stopwords_iso/<lang>.txt`), which is collision-free by construction, and the
only thing refused was the additional step of globalising it — which would have hidden it
everywhere else too. The scoped channel is where a word like this belongs, and it is
already there. Nothing is owed.

`laut` is different and the table says so rather than rounding it into the group: it is
in no list at all, German's included, so if it is genuinely leaking as German chrome
(*laut* is a preposition, "according to") it is currently filtered NOWHERE. That is a
candidate for a scoped `de` entry with evidence behind it, not for the global union —
but the evidence has not been gathered, so this records the observation and not a verdict.

The general rule these four illustrate, and the reason to keep them written down: a word
that is a function word in one corpus language and content in another belongs in the
SCOPED channel, never in this directory. Everything here is unioned across all languages
regardless of which file it sits in.

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

---

## Four ring members kept hidden (2026-09-30, R102 / D24, the maintainer's answer 12 = a)

D24 measured 38 ring members hidden by the language-agnostic union and exempted 34 of them
(the other four were already their own language's words to hide), so a word hidden only by
ANOTHER language's list shows again in the language whose ring names it. The maintainer was
shown the list and asked to keep four of the proposed words hidden: German `all` (`de.yml`),
Spanish `are` (`es.yml`) and English `bio` and `uno` (`en.yml`). Putting each in its OWN
language's file is what keeps it hidden, because the exemption rule already refuses to lift
a word its own language stoplists. `bio` and `uno` were already in the union through other
files; `all` and `are` are new to it, which is why
`tests/test_analytics_extract.py` declares them in `added_since_migration`. German `bio` and
`uno` stay shown. No corpus evidence backs these four: they are a stated preference, recorded
as one.

---

## Stoplist batch 1: LaTeX macros, boilerplate, markup debris, keyboard noise (2026-10-06, R98/R111)

Eighteen words, from the keyword-log triage (two blind reads of a language's high-confidence "noise" rows; every word below passed the
verdict gate with no `unstable` or `not_repeated` flag and `scripts/stopword_batch.py` refused none of them). Evidence is the 09-30 shards
(`log sha256` in the batch comments); counts are articles / mentions in that shard.

- **English (`en.yml`), 8 words.** LaTeX macros left in article text: `mathcal` (34 / 722), `mathbf` (33 / 1,786), `mathbb` (25 / 388), `mathrm` (7 / 453).
  Paper boilerplate: `fig` (79 / 822), `supplementary` (75 / 891), `crossref` (42 / 931). A run-on token, `likelyno7` (2 / 774).
  NOT taken: `table` (an ordinary word, 1,139 / 3,369), `doi` and `figure` (the tool's own `also_an_entity` refusal).
- **Korean log, 10 words, filed in `_multilingual.yml`.** Script and markup text that survives extraction on Korean pages: `addclass`, `attr`, `cssclip`,
  `encodeuricomponent`, `pclassname`, `pdesc`, `pmurl`, `ppurl` (2 articles each, 6 to 18 mentions), and the keyboard noise `dhmkkh`, `dhmkkhh` (25 articles each).
  They are Latin script, and `ko.yml` holds Hangul only (`tests/test_stopword_file_scripts.py`), so they go where the web-markup junk already lives.
  `stopword_batch.py --apply` files a batch under the language it was run for and does NOT know this rule: it wrote them to `ko.yml` and the guard failed.
  Move such a batch by hand until the tool does it (OPEN_QUEUE, 2026-10-06).
- **Left out on purpose, per the coordinator's ruling.** The 88 `lng` words (foreign words in another language's log), and every mojibake fragment (zh 19, ja 1): the
  cause is upstream (see the OPEN_QUEUE entry), and a stoplist word per fragment would hide the symptom one spelling at a time.

A stoplist word is language-agnostic in effect (`global_stopwords()` unions every file), so each of these is hidden in every language. That is safe for the
words above (none is a word of the app's shipped rings or a platform name; the tool checks both), and it is the reason `table` stayed out.

## Stoplist batch 2: function words, number and month words, site chrome in ten languages (2026-10-13, R131, language group 1)

309 words from the same triage (two blind reads of a language's high-confidence "noise" rows; every word passed the verdict gate with no `unstable` or `not_repeated`
flag, and `scripts/stopword_batch.py` refused none of them): de 40, fr 42, es 6, it 16, pt 24, nl 56, sv 36, da 35, ca 43, nb 11. By the triage's codes: 160 function
words (`trotz`, `obwohl`, `malgré`, `lorsque`, `trods`, `waarin`), 38 calendar words (30 month and weekday names, `dilluns`, `söndagen`, `setembro`, and 8 generic time words: `monat`, `woche`,
`mois`, `semaine`, `mese`, `maand`, `vecka`, `ahir`), 29 number words (`dertien`, `nueve`, `tausend`), 25 site chrome (`abo`, `anmelden`, `leestijd`, `klicka`, `prenumerant`), 21 `fr` rows
(a stem glued to a suffix, or an apostrophe left on a word), 2 others, and 34 that a count by code could not place (all apostrophe debris whose spelling the tool normalises: `nu'`, `dell'`, `site'`). 46 words carry
an apostrophe; each is declared in the test beside its curly spelling, which the module adds on load, and each hides only the debris token, never the bare word.

The evidence is ONE log, `combine_logs.py` over the 79 shards of 09-30 (`log sha256 6467504ab8ab`; script and per-language tool output in
`/mnt/project-files/keyword-session/t5-group1-2026-10-13/`), because the tool's `content_elsewhere` check can only see the rows it is given: one shard holds a language's top 5,000, so a
combined log is the stronger cross-language test. It is still a sample, and a log row carries ONE language (the dominant one), so a word that is content in a language with no row of
its own never shows there. The tool now prints, per word, the other languages whose articles the word was read in (`language_signature`), as evidence for the reader and a decision for
no one (an English-tagged article quoting a French word is in that list too, and a Norwegian article under `no` or `nn` is listed beside `nb`), and it refuses the four words of the standing
ruling above (`sea` `tom` `fin` `laut`) with no override: before this batch it ACCEPTED `laut` (934 articles in German, and 71 Indonesian articles read it as "sea").

**Left out after reading each word's other languages (the words files in the pool folder omit them, and every language file was written by `--apply` from them):** de `falls` (the English
verb and noun); fr `moi` (a surname, 53 English-tagged articles) and `durant` (Kevin Durant); es `diez` (a surname); pt `maio` (Luigi Di Maio); ca `hagi` (Gheorghe and Ianis Hagi, in Romanian
articles), `gener` (Swedish "genes"), `sis` (the SIS acronym) and `dues` (English "dues"); sv `borde` (Spanish "edge", 88 articles) and `medan` (the Indonesian city); nl `results`, `readers`,
`donating`, `femmes` (foreign words in the Dutch log: the `lng` group stays out by the batch 1 ruling); ca `instal`, `ligència`, `lacions`, `lícula` (a middle dot splitting
`intel·ligència` and `pel·lícula`: the cause is upstream, and a stoplist word per fragment hides the symptom one spelling at a time). The names matter beyond the keyword itself: a stopword also
drops every phrase that contains it, so `hagi` would take "gheorghe hagi" with it. Read and KEPT, as the stronger case for noise: `mil` (a Scandinavian mile, but also the top number word
of es), `fut`, `vore`, `abo`.

**What a reader of the lists will see change.** The 30 month and weekday names and 29 number words are no longer keywords in any language; words two Nordic languages share (`hos`, `samt`) are
hidden in both, which is where they are function words. Hiding is retroactive with no re-index (`hidden_set()` unions the list at query time); extraction also drops them from now on.

## Stoplist batch 3: function words, number and month words, reporting verbs and site chrome in six Slavic languages (2026-10-13, R131, language group 2)

415 words from the same triage and the same method as batch 2 (read it first: the merged log `6467504ab8ab`, the verdict gate, the tool's refusals, and the rule that each word's other languages
are read by a person): ru 28, uk 124, pl 64, cs 87, sk 54, sl 58. By the triage's codes: 278 function words (`среди`, `щодо`, `dzięki`, `totiž`, `počas`, `kljub`), 69 number words, 48 calendar words (month
names in the case the news writes them in, and the weekday: `июле`, `вересня`, `września`, `neděli`, `piatok`, `soboto`), 12 attribution verbs coded `ph` (`заявив`, `повідомив`, `uviedol`: "said", "reported"), 7 site
chrome (`читайте`, `подписаться`, `czytaj`, `dodaj`, `wyślij`, `zobraziť`, `iskanja`) and 1 fragment. The attribution verbs are the one class batch 2 did not have; they carry no topic, but they are verbs the maintainers may
want to see again if a reading finds a topical use.

**Left out after reading each word's other languages:** the ten `lng` words the Russian and Ukrainian logs hold in another language (ru `noted`, `marking`, `guests`, `established`, `enabled`, `races`,
`textbooks`; uk the Russian `сборной`, `оккупанты`, `воздушные`: a Russian word hidden here would be hidden in Russian too, where `оккупанты` is signal), the English `uploads` and the Latin fragments `secur` and
`rippin'`, the Russian fragment `кий`, pl `maju` (Indonesian "forward", 18 articles) and `amet` (lorem ipsum, also a name), sl `glede` (Norwegian "joy", 17 articles). The independent read of the PR added four more: uk `ось` (the Russian noun "axis", already in 5 Russian-tagged articles), pl `jaka` (Serbian and
Croatian "strong" and "collar"), cs `mimo` (Spanish and Italian "mime", Spanish "affection": es 11, pt 3) and cs `dubna` (the Russian science city Dubna, a place name). No other word of the six lists shows a
content sense in another language in the log or in the reader's knowledge of those languages.

Nothing is filed in `_multilingual.yml`: every word is in the script of its language's file.

## Stoplist batch 4: function words, number and month words and site chrome in Serbian, Bulgarian and Greek (2026-10-13, R131, language group 3)

288 words from the same triage and the same method as batches 2 and 3 (read batch 2 first: the merged log `6467504ab8ab`, the verdict gate, the tool's refusals, and the rule that each word's other languages
are read by a person): sr 132, bg 49, el 107. By the triage's codes: 220 function words (`koji`, `među`, `своя`, `извън`, `όμως`, `χωρίς`; four of them elided Greek forms with their apostrophe, `απ'`, `κατ'`,
`καθ'`, `παρ'`), 31 number words, 29 calendar words (the month names Serbian, Bulgarian and Greek write dates with, and the weekdays), 8 site chrome (`podeli`, `pročitaj`, `pratite`, `pridružite`, `pogledajte`,
`pretplatite`, `najčitanije`, `влезете`).

**Left out after reading each word's other languages (the tool listed some, the rest are a person's reading):** sr `tri` (the Indonesian given name and port name Tri Sakti, the French "tri" of sorting, the Vietnamese syllable of "tri thức"), `kojima` (the Japanese surname), `kod` (Swedish, Norwegian, Polish and Turkish "code"), `dok` (Dutch and Indonesian "dock"),
`ono` (the Japanese surname Ono), `ove` (the Scandinavian given name), `toga` (English "toga"), `smo` (the acronym SMO, "special military operation"), `niko` (the given name), `niti` (NITI Aayog, Indian
policy commission), `iza` (the Polish given name), `bile` (English "bile"), `tome` (English "tome"), `neka` (Swedish "deny"), `ovi` (Finnish "door"); bg `шест` (Russian "pole"), `ото` (a glued suffix and the
Russian name Ото), `макар` (the Russian and Ukrainian given name Makar); el `microgreens` and `servicers` (English words in the Greek log, the `lng` group left out by ruling). The tool itself refused
sr `joj` (a French entity, almost certainly the Youth Olympic Games acronym), `kome`, `kom` and `sva` (keywords in Norwegian, Dutch and Swedish), bg `неговата` and `против` (keywords in English), and every phrase.

Nothing is filed in `_multilingual.yml`: every word is in the script of its language's file.

**Kept on purpose after the independent read:** sr `koji` (a Japanese given name and a food term, but 725 articles in Serbian and no topical use found), `koga`, `neko`, `bude`, `osim`, `biće`, `nju`, `meni`;
el `παρασκευή` (Friday; also "preparation" and a place and given name, kept for its use as the weekday) and `κυριακή`. `kad` is also Malay "kad" (card, as in "kad merah"), which the Malay group should read before it relies on this entry.

## Stoplist batch 5: function words, number and calendar words in Indonesian, Malay and Tagalog (2026-10-13, R131, language group 4)

146 words from the same triage and the same method as batches 2 to 4 (read batch 2 first): id 46, ms 63, tl 37, in two NEW files (`ms.yml`, `tl.yml`; the loader unions every file in the directory). By the triage's codes: 64
function words (`sebelum`, `daripada`, `kerana`, `dahil`, `upang`, `habang`), 66 number words (the Indonesian ordinals `ke-18` and rupiah amounts `rp5`, the Malay ringgit amounts `rm39`, the Tagalog clock times `alas-9` and
ordinals `ika-24`, and the number words themselves), 9 calendar words (`agustus`, `ogos`, `julai`, `setyembre`, `biyernes`), 2 attribution verbs (`berkata`, `ujarnya`) and 5 quoted-word debris with a trailing apostrophe
(`halo'`, `comel'`, `guru'`, `seeding'`, `vibe'`).

**Left out after reading each word's other languages:** id `ke-80` and `ke-81` (Indonesia's 80th and 81st independence anniversaries, "HUT RI ke-80"), id `isn` (the acronym) and the Arabic `اللَّهُمَّ` and `لَنَا` (a prayer widget's text, content in Arabic); ms `empat` (Catalan "empat", a draw in sport, in 9 Catalan articles; Indonesian keeps it through the vendored list); tl `nang` ("Da Nang" in English, French and German, with `da` already hidden: the city's only trace; also a Thai and Lao title), `rin` (the Japanese given name), `naman` (the Indian given name), `kanya`
(Hindi "Virgo"), `halos` (English "halos") and `mula` (Spanish "mule"). The tool itself refused every phrase and, in tl, `nito`, `saan` and `itong` (keywords in other languages) and the English words in the Tagalog log.

**Left out on purpose, not decided: Vietnamese.** The triage coded 73 of its 82 candidates `fr` (fragments), but every Vietnamese syllable is a word and the keywords are made of them: `thủ` is inside "thủ tướng"
(prime minister), `nẵng` inside "Đà Nẵng", `phương` is also a given name. A stopword drops every phrase that contains it, so hiding a syllable hides the names built on it, and nothing in the log can say which. The
Vietnamese list waits for a reader of Vietnamese. The Japanese, Korean and Chinese lists (1,333 candidates, mostly `bp` chrome and `fr` fragments of a script with no spaces) are the next group's.

Hiding is retroactive with no re-index; extraction also drops them from now on. The two Arabic-script words the triage accepted for id are not here, so nothing is filed in `_multilingual.yml` by this batch. Batch 4 flagged Serbian `kad` as also the Malay "kad" (card, as in "kad merah", red card): the Malay list here does not contain it, and the Serbian entry stays; whether the Malay card sense matters is for a reader of Malay to weigh when the next Malay batch is read.

**Kept on purpose after the independent read:** tl `mga` (also the Malta Gaming Authority acronym), id `sih` (also the Smart India Hackathon acronym), id `ahad` (Sunday; also the given name Ahad), and the marginal collisions `siyam`, `isang`, `maret`, `juta`, `serta`, `niya`, `ilang`, `lamang`, `boleh`, `dahil`. The apostrophe forms are junk left by closing quotes (the tokenizer keeps "'s", so "guru's" is never cut to `guru'`).

## Stoplist batch 6: chrome lines, function words and number debris in Japanese, Korean and Chinese (2026-10-13, R131, language group 5)

379 words from the same triage and the same method as batches 2 to 5 (read batch 2 first): ja 215, ko 26, zh 138, ja and zh in two NEW files (the loader unions every file in the directory) and eight entries that carry
Latin letters inside Japanese or Chinese text in `_multilingual.yml`, because `ja.yml` and `zh.yml` may hold their own scripts only (`test_stopword_file_scripts`; the tool's script map knows both now). Of the 1,333
candidates the tool itself refused 548 (a phrase containing a listed word, already hidden, or also an entity), the thread left out 404 by hand and kept 381; the independent read then removed two more.

**Taken out again by the layout PR (the repeat-agreement marker, which did not exist when this batch shipped).** Korean is one of the four twice-read languages (`TWICE_READ` in `scripts/stopword_batch.py`: vi, ko, as, tl): a
word enters only when its blind repeat agreed (`repeat_agreed`) or a reader's hand review lists it. Run over the 26 Korean entries this batch shipped, the rule keeps 25. `참석했다` ("attended") came out: the
first reading called it a phrase fragment (`ph`), the blind repeat called it an everyday verb (`lv`, one of the two open boundaries), so the two readings did not agree on what it is and no hand review lists it. Korean now
holds 25 entries from this batch (the batch is 378 words, not 379). The same check run over the 37 Tagalog entries of batch 5 (`tl`) found none to remove. The ten Latin-token Korean entries in `_multilingual.yml` (batch 1) all carry the marker.

**How these entries match, which the other groups did not need to say.** Hiding is exact: at read time the whole stored keyword must equal an entry, and at extraction a word must equal an entry (a phrase containing one
is dropped). The stored keywords of these three languages are whole sentences or runs of text because the log's tokenizer has no spaces to cut at, so most entries hide only the stored run they name, retroactively and
with no re-index. New Chinese keywords are split into words by jieba (a core dependency since 2026-09-25) and new Japanese ones by janome when the optional `[segmentation]` extra is installed (measured for Chinese,
reasoned for Japanese: janome was not installed to test). The independent read ran jieba over every entry: 13 come out as a single word (`上周五`, `亿美元`, `值得一提的是`, `八萬五`, `据介绍`, `责任编辑`, `點這裡` and the
seven Japanese weekday names), none of which means anything else in Chinese. So the page chrome is mostly about the stored runs, and the short function words and weekday names act on new extraction too.

The accepted candidates are mostly page chrome read as one keyword (ja 132 `bp` lines such as `この記事は有料会員限定です` "this article is for paying members" and `閉じる` "close", zh 97 such as `保證天天中獎`, `更新時間` and the
photo credits `記者…攝`), plus ja 19 and ko 12 function words (`一方で`, `つまり`, `자신의`), 15 weekday and date words (`月曜日` … `日曜日`, ko `금요일`, `일까지`, `일부터`), 23 number-and-clock fragments (`午後6`,
`口座番号4097270`, zh `億美元`) and the stock reporting phrases (ja `と述べた`, `と語った`, `警察によりますと`, zh `他表示`, `據了解`, `值得一提的是`).

**Left out on purpose:** (1) the fragments the triage coded `fr`: ko 225 (and 7 apostrophe forms), ja 60, zh 25 — a Korean word is a noun with its particle (`기자회견을`, `한국이`), a real word cut at the particle, and a
stopword drops every phrase that contains it, so hiding it hides the name or topic built on it; the same holds for a Japanese or Chinese cut. (2) Sentences that name a person, an organisation or an event, however
generic the rest: ja `第十一菅区海上保安本部によると` (sic: the agency is 第十一管区, quoted as the log spelled it), `代表荒木が参加`, zh `习近平指出`, `盧秀燕表示`, `翁曉玲說`, `教育局表示`, `關務署表示`, and the clauses that are the story itself
(ja `いずれも機関砲を搭載している`, zh `海基會也在搞統戰`, `近日已補發差額`, and the other headline fragments). (3) The mojibake runs (zh 19, ja 1) and the English words, by the batch 1 ruling: `reserved`, `aired`, `20s`, `48mm`,
`00utc`; the mojibake filter also caught `β版音声読み上げは` (page chrome, a Greek letter inside Japanese), and 5 ja rows had no triage verdict under their spelling. (4) ja `フォロー` and `万円の修理代` (content senses),
ja `ついに登場` and `登場の裏で` (headline hype), `完成したムービーを圧縮してファイルサイズを小さくする` (a how-to). (5) After the independent read: zh `徐欣瑩競辦提供` (a credit that names a political candidate and
her campaign office, not a journalist) and ja `ホーム` (once Japanese is split into words it is the station platform and the home game, and every phrase containing it would be dropped). The triage labelled its
reading of these three languages "partial", and no word kept carries the `single_reader` flag.

**Kept on purpose:** the photo credits that name the source rather than a person (`記者林正堃攝`, `警方提供`, `法新社檔案照`, `路透資料照`, `翻攝自微博`) are bylines, not subjects; the credits that name a government body
(`台南市政府提供`, `屏東縣政府提供`, `觀光局提供`) have the shape of the statement lines left out above (`教育局表示`), but a credit line says who supplied a picture and never what that body did or said, so hiding it
loses no statement. The suicide-prevention footer lines (`生命線專線`, `自殺不能解決問題`) are a fixed block of Taiwanese newsrooms. ja `ログイン` is kept for its volume (76 articles) although, once Japanese is split,
it would also drop a phrase such as `不正 ログイン` (unauthorised login); `お知らせ`, `購読料`, `オススメ`, `閉じる` and ko `등록번호` are marginal labels that can also be words, hidden at read time and so reversible. Not done
and for a later batch (batch 8 did the attribution tails, all but `を発表`): the reporting phrases `と指摘した`, `と強調`, `と説明`, `を発表` and `としています` are the same kind as the kept `と述べた` and were left out as over-cautious; `々` (as in 人々) is not yet allowed in
`ja.yml` by the script guard. Hiding is retroactive with no re-index; extraction also drops them from now on.

## Stoplist batch 7: function words, number words and calendar words in Amharic, Basque, Faroese, Galician, Hausa, Kazakh, Macedonian, Kinyarwanda and Swahili (2026-10-13, R131, language group 6)

344 words from the same triage and the same method as batches 2 to 6 (read batch 2 first): am 29, eu 56, fo 15, gl 10, ha 25, kk 76, mk 58, rw 14, sw 61, in eight NEW files (the loader unions every file in the directory;
`sw.yml` existed). By the triage's codes: 258 function words (Basque `baina`, `zein`, Kazakh `және`, `үшін`, Macedonian `што`, `дека`, Swahili `kuhusu`, `ambapo`, Amharic `ውስጥ`, Faroese `frá`), 40 number words (`ehun`, `мың`,
`dubu`, Swahili shilling amounts `sh50`), 38 weekday and month names (`astelehena`, `сенбі`, `мај`, `satumba`, `jumamosi`) and 8 attribution verbs and button labels (Kazakh `деді`, `айтты`, `бөлісу`, `көшіру`, Swahili
`ilisema`, Amharic `ብሏል`). Every word of these nine languages has ONE reader in the triage (the `single_reader` flag, 100 % of their candidates), so the batch was read a second time by hand, word by word, the way the
earlier groups read the "also read in" notes; the 344 are the words both readings accepted and the independent read of the PR diff kept, which is the third.

**Left out:** the triage's fragments (am `ኛውን` and `ከፉልሃም` "from Fulham"; the closing-quote forms eu `ilargia'`, `katana'`, `plague'`, gl `pasar'`, `xerión'`, sw `samantha'`, `uzungu'`); eu `hamar` (ten, but also the Norwegian
town, read in Norwegian articles) and `elkar` (each other, but also the Basque publisher Elkar); ha `kuma` (and, but read in 5 English articles) and `inda` (read in 3 Spanish
articles); kk `бес` (five, but also the Russian "demon", a content word). The independent read took eight more out of the first 352, each with a sense in another language that a global stoplist would hide there: kk `сол` (Bulgarian and Macedonian "salt", Russian Saul) and `осы` (Russian "wasps"), mk `кон` (Bulgarian "horse", Russian "stake"), eu `baita` (Italian "mountain hut", Brazilian Portuguese "huge"), sw `tisa` (the river Tisza in Serbian and Croatian), `hawa` (Indonesian and Malay "air"), `kabla` (the genitive of "cable" in Polish, Serbian and Slovene) and `kumi` (the Ugandan district, a Japanese given name). The tool refused most of the triage's other candidates of these languages (gl 139 of 151, mk 159 of 218, eu 122 of 184), but almost all of those refusals are multi-word phrases, which it never adds (gl 135, mk 159, eu 118); only a handful were refused for a content sense in another language, so the weighing of senses was the readers' work, not the tool's.

**Kept on purpose:** the Kazakh, Basque and Macedonian words the notes show in Russian-, Spanish- and English-tagged articles are those languages' function words quoted or mis-tagged, not a second sense. The same holds for `zao` (read in Serbian-tagged articles, where it is also "bad", mostly in "zao mi je"; kept, a known small cost), `huu`, `што`, `кои` (Belarusian- and Bulgarian-tagged articles) and `duen` (Catalan-tagged articles), whose notes name a language the word is quoted in, not a content use of it. The script guard
and the tool's script map gain Ethiopic (am) and Cyrillic (kk, mk). Hiding is retroactive with no re-index; extraction also drops them from now on.

## Stoplist batch 8: attribution tails in Japanese (2026-10-14, R131 follow-up to batch 6)

10 words, all in `ja.yml`, from the same triage and the same method as batches 2 to 7 (read batch 2 first), run on the decision file `full.repeat-agreed.tsv` (sha256 47400de97c79; the earlier batches cite `full.tsv`, whose
ja rows are the same readings without the repeat marker): `としています`, `とコメント`, `と強調`, `と指摘`, `と指摘した`, `と振り返った`, `と振り返り`, `と振り返る`, `と語る`, `と説明`. Batch 6 named five of these families as "for a
later batch": they are the same kind as the `と述べた`, `と語った`, `と強調した` and `と説明した` it kept, a quotation particle and a verb of saying that attribute a statement and carry none of its content, and leaving
them out was over-cautious. The triage coded them `fr` (fragment) where the kept ones are `ph`, but the fragment rule of batch 6 exists for a noun cut at its particle (`기자회견을`), where hiding the entry hides the
name or topic built on it; these have no noun to lose. Every one is a high-confidence N with the blind repeat agreeing (`repeat_agreed`, 10 of 10, no `single_reader` flag), the tool refused none, and each is read in 8 to
14 articles.

**Left out on purpose** (the other `fr` rows of the same shape, which say what happened rather than who said it): `を発表` and `を発表せず` (announced / did not announce), `を発売` (put on sale), `が登場` and
`は登場せず` (appeared), `を紹介` (introduced), `を搭載` (equipped with), `に出演` (appeared in), `が復活` (came back); `と言うために` and `と言うコーナーがありましたら` are not attributions. The earlier note listed `を発表`
among the candidates; on reading, an announcement is the event of a news item, so hiding it would hide the story, and it stays out.

**How these entries match:** hiding is exact (the whole stored keyword must equal an entry at read time, a token at extraction). The log's Japanese keywords are stored runs, so these hide the runs that are exactly
one of them, retroactively and with no re-index; new Japanese keywords are split into words by janome when the optional `[segmentation]` extra is installed, and a token like `と` then comes apart from `指摘`, so on new
extraction they act on little (reasoned: janome was not installed to test, as in batch 6). The `々` note of batch 6 is moot for this batch: no Japanese or Chinese candidate of the decision file contains it, and the
script guard is unchanged.

