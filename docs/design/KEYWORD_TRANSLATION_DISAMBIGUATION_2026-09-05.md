# Multilingual keyword translation + sense disambiguation — analysis & plan

**Status:** ANALYSIS + PLAN. Nothing built. Two rulings taken 2026-09-05 (§0), two
decisions recommended and awaiting the maintainer (§5, §6).
**Code state of record:** `main` @ 83b3cad, verified by direct reading — every claim
below carries its file:line anchor.

---

## 0. Rulings taken 2026-09-05

| # | Ruling | Consequence |
|---|--------|-------------|
| **R1** | **Cross-language search expansion is ON by default, and DISCLOSED.** Searching `climate` also matches `climat` / `Klima` / `clima` / `климат` / `مناخ`. The result surface states the expansion, shows the per-language breakdown, and offers one click back to the literal term. | §3 slice 1 |
| **R2** | **Sense-level identity via Wikidata QID is the target model** for ambiguous terms (April = month \| given name \| organisation). | §4 — a schema change, sequenced behind the measurement in §5 |

Both compose: once a mention carries a sense, expansion can be *per sense* rather than
per string — searching the month April need not drag in April Ryan.

---

## 1. What already exists (the headline: the dictionary is built)

The engine has four tiers, one of them invisible:

| Tier | Where | Scope |
|---|---|---|
| keyword | `keywords` table | one row per `normalized_term`, **globally** |
| family | `analytics/families.py` | invisible variant collapse (plural, possessive, lemma, honorific), within a language |
| **group / ring** | `analytics/equivalence.py` + `configs/keyword_rings_generated.yml` | **698 concepts, ~22,000 members, exactly the 12 UI languages** |
| super-group | `configs/keyword_supergroups.yml` | 77 umbrella concepts over rings, in ~12 domains |

Measured against the live table (`load_rings()` → 698 rings):

```
climate  -> ring 'climate':  fr:climat  de:klima  es:clima  pt:clima  ru:климат  ar:مناخ
drought  -> ring 'drought':  fr:sécheresse de:dürre es:sequía pt:seca ru:засуха
                             ar:جفاف zh:干旱 ja:干ばつ hi:सूखा bn:খরা id:kekeringan
```

Per-language ring coverage in the generated file: en 684, es 676, fr 674, de 665,
ru 659, ja 657, zh 651, pt 650, ar 646, id 629, hi 558, bn 553.

**So the "integrated keyword translation dictionary" the ask describes is already in
the repository** — Wikidata-QID-sourced, hand-vetted (47 mis-resolutions dropped across
two vetting passes), covering the exact 12 languages the UI ships.

## 2. What is missing (one consumer, not one subsystem)

Rings are read by **analytics** — `top_terms`, `trending`, associations / mind-map,
`group_stats`, `card_audit`, ring-countries, the AI translate fallback, `engine_report`.

Rings are read by **nothing in the search path**:

* `src/database/fts.py:build_match()` — a pure Boolean parser. It tokenises, builds an
  AST, and emits quoted FTS5 literals. No ring lookup anywhere in the module.
* `src/api/search_omni.py:_keywords_group()` — `Keyword.normalized_term LIKE 'climate%'`.
  A prefix match; `climat` and `Klima` do not start with `climate`.

That is the whole gap for R1. `equivalence.ring_of()` / `ring_translation()` are already
pure, cached, language-qualified, and unit-tested — the search path simply never calls them.

**Coverage is the real ceiling, not the mechanism:** 698 concepts against ~250,000
distinct terms in the field corpus. Expansion helps exactly where a ring exists.

## 3. R1 — cross-language search expansion

**Slice 1 (backend).** A pure `expand_query(term, *, languages) -> ExpandedQuery`
alongside `build_match`, returning the literal term plus its ring siblings **and the
provenance** (ring id, per-language member, QID). `build_match` gains an opt-in expansion
hook; `_keywords_group` gains ring-sibling rows. Off ⇒ byte-identical to today.

**Honesty rails (non-negotiable, from the standing rules):**
* the expansion is STATED on the result surface, never silent — it changes which articles
  match, so it must be visible by default;
* the per-language breakdown is shown (`language_breakdown` already exists on merged rows);
* one click narrows to the literal term;
* an expanded total is a REAL total — the recorded *never-capped-figures* rule applies, and
  `search_ids`' `_MAX_CANDIDATES` bound must not become the reported number.

**Known risks to pin as tests:**
1. `ring_of` is deliberately case-insensitive to let UPPERCASE entity norms match
   lowercase ring members (`equivalence.py:139-150`). Expansion inherits that, so an
   acronym could expand through a ring it only matches by casefold. Needs a negative test.
2. Ring members are multi-word for some concepts (`fr:migration humaine`,
   `pt:movimento migratório`) — these must be emitted as FTS5 phrases, which `_quote()`
   already does.
3. Expansion multiplies the match set, so it interacts with the FTS candidate bound.

## 4. R2 — sense-level identity

**Why the schema cannot express it today.** `analytics/store.py:113` —
`_get_or_create_keyword` does `filter_by(normalized_term=t.normalized).first()`. One row
per normalized term, **globally, with no language in the identity key**. `Keyword.language`
is first-write-wins (`store.py:120`), later corrected only by the background
`reconcile_keyword_language` majority pass (`store.py:1443`). And `ring_of(lang, term)`
maps one (language, term) to **one** ring id.

So the model can say *"april is English"*; it cannot say *"this occurrence is the month,
that one is the journalist."*

**The scale of the problem is already measured** — by the attached triage itself:
**59,206 of 250,000 judged terms (23.7%) exist under several languages** and were
correctly held back for exactly this reason (`held_back.ambiguous_language`). That block
is the single most valuable artefact in the file: a free, corpus-derived map of where
collision actually happens.

**Shape of the build (sequenced behind §5):** a sense inventory (surface form → candidate
QIDs, CC0 from Wikidata), a sense column on the mention, a linker that assigns a sense
only on evidence and otherwise leaves it NULL, and rings keyed per sense. Every link is a
labelled assertion, so it needs its own eval before it is trusted — the perception-harness
precedent. **An unlinked mention must stay usable**, never dropped for want of a sense.

## 5. Months — the live regression, and the recommendation

`configs/stopwords_extra/_multilingual.yml` puts month names into a
**language-agnostic union** (`extract.py:421 global_stopwords()`), applied at **both**
extraction and query time. Confirmed present: `april august avril août janvier june mai
march mars may`.

And `extract.py:612-615` drops an n-gram if **any** token is a stopword.

**Measured consequence — the keyword engine cannot see:**

| lost | because |
|---|---|
| the planet **Mars**, Mars rover, Mars Inc. | `mars` = French *March* |
| the **March** on Washington, a climate march | `march` = English month |
| Theresa **May**, Brian May | `may` |
| **April** Ryan, the April 6 Youth Movement | `april` |
| **Avril** Haines, Avril Lavigne | `avril` |
| **August** Landmesser, Augustus | `august` |

Not ranked low — **absent**, and absent as phrases too. Full-text search still finds them
in article bodies, so the search index and the keyword engine disagree about whether these
topics exist.

This is the project's own recorded stoplist-architecture lesson biting: *never globalise a
word that is content elsewhere.* Months were globalised and the collateral was never measured.

### The recommendation: make the block DATE-AWARE, not string-level

The noise months were banned to suppress is **datelines** ("Published April 3, 2026").
The app already has a component whose entire job is identifying those spans:
`src/timemap/dateextract.py` carries month vocabulary in many languages
(`:33`, `:63`, `:269`) and already resolves overlapping matches most-specific-first,
i.e. it internally knows which span each date occupies.

So the honest fix is to stop claiming *"this string is always noise"* and instead claim
*"this occurrence was consumed as a date"* — drop a month token only where the date
extractor claimed its span, and keep it otherwise. Mechanism-matched, no sense layer, no
external dictionary, no new ruling.

**Why this beats the two obvious alternatives:**
* *De-globalise months to per-language stoplists* fixes only the cross-language half
  (`mars` no longer blocking English Mars). `march` / `may` / `april` / `august` collide
  **within English**, so scoping cannot reach them.
* *Exempt n-grams* recovers `april ryan` and `mars rover`, but not bare `Mars` or `march`,
  and `march on washington` still dies on `on`.

**Honest cost, stated up front:** the date extractor's recall is imperfect (the recorded
CJK-boundary gap; measured field coverage in the 36–52% range), so some datelines would
leak back in as keywords. That is the trade — **leaked datelines are visible and
stoplistable; deleted topics are invisible and unrecoverable.** The project's posture
prefers the visible failure. Either way this needs a re-index to recover existing articles.

**Do this first, and it is cheap:** a diagnostic that counts, per month token, how many
occurrences fall **outside** any span the date extractor claims. That number is the whole
decision, and it costs nothing to be wrong about. If it is small, the block is nearly free
and this drops down the queue; if it is large, the fix pays for itself immediately.

### On the maintainer's "integrated homonym dictionary" idea

It is the right instinct, and it is **R2 under another name** — a homonym dictionary is
exactly *surface form → set of candidate senses*. It is worth building, but it is the
**sense inventory for R2**, not a month patch: a homonym table tells you `april` has three
senses; it does not by itself tell you which one *this* occurrence is. The month fix
should not wait for it.

## 6. Dictionary + synonym sources — recommendation

Constraints taken from the ask and the standing rules: fully open-source, offline, bundled,
and under the repo's 100 MB-per-file limit. Every candidate below is a **static data file
generated on a networked machine and committed** — the shipped pattern
(`keyword_rings_generated.yml`, `stopwords_iso/`, `world_countries.json`, the DB-IP table).

| Source | Licence | Gives | Verdict |
|---|---|---|---|
| **Wikidata** (labels + aliases) | CC0 | translations, aliases | **already in use — extend it** |
| **Wikidata** (same fetch, unused) | CC0 | **items sharing a label = the homonym map** | **highest value, free** |
| **Wikidata Lexemes** | CC0 | lexical senses, forms | **refuted for ring growth** (§6b.3) — a morphology resource; ru has 2,292 senses to 101,137 lexemes |
| ~~PanLex~~ | **CC BY-NC-SA 4.0** (verified 2026-09-05, §6b) | — | **DISQUALIFIED** — NC is not GPL-3.0-compatible |
| Open Multilingual WordNet | **varies per pack** — measured, §6b.1(3) | synsets = senses + synonyms | **seed generator only** — 8/12, no ru/hi/bn, translated synsets already leak hypernyms |
| Wiktionary / Wiktextract | CC BY-SA **3.0/4.0 mixture** — §6b.3 | largest sense + synonym coverage | **needs your share-alike ruling** — reframed: only 4.0 is GPLv3-compatible |
| BabelNet | research / non-commercial | — | **excluded**, not open |

**Recommended sequence — Wikidata first, and twice over.** The generator
(`scripts/generate_wikidata_rings.py`) already fetches labels *and aliases* per QID. Two
extensions need no new source, no new licence, and no new vetting protocol:
1. **more seeds** → more rings (coverage, the actual ceiling);
2. **harvest the ambiguity map from the same fetch** — for each surface form, which *other*
   QIDs carry it as a label. That is the homonym dictionary, CC0, from data already retrieved.

**On synonyms — a caution worth stating before anyone ships one.** Cross-language
equivalence is near-identity (`climate`↔`climat`) and low-risk. Within-language synonymy is
not: WordNet-style synsets and Wiktionary sections routinely mix true synonyms with
**hypernyms** (`car`↔`automobile` is fine; `car`↔`vehicle` loses precision). Synonyms should
therefore be a **separate, separately-disclosed expansion tier**, never merged silently into
rings.

**Facts to verify before committing to anything past Wikidata** — routed to two
self-contained research prompts handed to the maintainer directly (2026-09-05) for a
genuinely networked session, deliberately NOT committed here: they are throwaway session
inputs, not project documentation, and the findings come back as a report. Guessing a
licence or a dump size is exactly the fabrication this project forbids, so each prompt
carries a mandatory host-probe-first rule and a fetched / search-verified / lead
verification tier per claim.

## 6b. Research pass 1 — measured source verdicts (2026-09-05)

The operator ran the first of the two handed-over prompts (translation/synonym SOURCES) on a
networked machine and returned a report. This section records what it **settled**, what it
**refuted**, and what it left owed. Verification tiers are the report's own: `fetched` (the
artefact was retrieved and read), `search-verified` (a secondary page stated it), `lead`,
`NOT VERIFIED`.

Two process notes first, because both are the project's own recorded lessons working:

- **The host probe ran first and found a policy gateway.** 7 of 9 target hosts answered 403
  with an explicit `x-deny-reason: host_not_allowed` while the control (`pypi.org`) answered
  200. A second channel (`web_fetch`) reached panlex.org and kaikki.org but reports
  `www.wikidata.org` as *"cache-only and cannot be fetched"* — so **both channels fail on
  Wikidata, and every Wikidata claim in the report is capped at `search-verified`.** This is
  the fourth consecutive session to hit a host allowlist on a task defined by reaching named
  publishers; the probe is what turned it into a stated limit instead of a fourth silent
  failure.
- **One served-URL mismatch occurred, and it was caught.** A request for
  `https://panlex.org/snapshot/` was served the PanLex **home page** (`canonical: /`, title
  `PanLex | PanLex`). No snapshot facts were attributed — format, table inventory and size
  are recorded `NOT VERIFIED`. This is the recorded *"read the URL you were SERVED, never
  the one you asked for"* rule, working as designed.

### 6b.1 The four decisive verdicts

**(1) PanLex is DISQUALIFIED on licence — the ledger's "believed CC0" note was wrong.**
`https://panlex.org/license/`, fetched 2026-09-05, states **CC BY-NC-SA 4.0**, with
commercial use only by written permission. The CC0 belief traces to a *cached 2019-dated
snippet of the same URL*; two HuggingFace mirrors (`cointegrated/panlex-meanings`,
`cointegrated/panlex-definitions`) still carry `license: cc0-1.0` in their metadata. The
sources disagree **asymmetrically**: a publisher's live licence page outranks a cached
snippet and a downstream metadata field. NC is incompatible with GPL-3.0 and is not open
under the Open Definition, so PanLex cannot be bundled. Note also that the PanLex home page
calls the data "free and open" and links that phrase *to the NC licence page* — take the
licence, not the marketing copy. (§6's table is corrected accordingly.)

**(2) The synonym-tier question is ANSWERED, and the answer is: not from OMW.** This is
what §6's SYNONYM CAUTION asked for. The distinction is real and machine-readable — in
WN-LMF, synonymy is *membership of a synset* and hypernymy is a *typed `SynsetRelation`
between synsets*, two different structures. Measured in `omw-en.xml`: hypernym/hyponym
89,089 each, derivation 74,708, similar 23,136, mero/holo_member 12,293 each,
instance_hypernym/hyponym 8,577 each, antonym 7,979. The brief's own example resolves
cleanly in English: synset `02958343-n` holds {auto, automobile, car, machine, motorcar}
and reaches {automotive vehicle, **motor vehicle**} across a hypernym edge — so
`car`↔`automobile` is inside, `car`↔`motor vehicle` is outside.

**But only `omw-en` carries relations at all.** Measured `SynsetRelation` counts: omw-en
285,348; **fr, es, pt, arb, cmn, ja, id — 0 each**. ILI references are present in every
pack (fr 59,091 · es 78,948 · pt 43,895 · arb 9,916 · cmn 42,300 · ja 117,659 · id 46,774),
so the English relation graph *could* be joined onto any language by synset id. That is not
the problem. The problem is that the translated synsets have **already leaked the hypernym
into the synonym set**: the Spanish `02958343-n` contains `vehículo`, the Indonesian
contains `kendaraan bermotor` and `mesin`, while English correctly keeps `motor vehicle`
outside. English separately carries archaic `machine`, which would false-match on
industrial and technology articles.

So a synonym tier built from OMW imports **precisely the `car`↔`vehicle` failure the
caution was written about** — unevenly, silently, and only in the non-English languages,
which is the hardest kind to notice. Slice 7's gate is therefore answered in the negative
for this source; it is not answered for the SKOS family below.

**(3) OMW cannot cover ru, hi or bn — so ring expansion structurally needs a second
source.** Per-pack licences, read from LICENSE files inside the measured 55,846,636-byte
`omw-2.0.tar.xz` (all `fetched`):

| Pack | Project | Licence, from the artefact | XML | entries / senses |
|---|---|---|---|---|
| omw-en | WordNet 3.0 | Princeton WordNet 3.0 (BSD-like) | 109.9 MiB | 156,584 / 206,978 |
| omw-fr | WOLF | **CeCILL-C** (a copyleft *software* licence) | 21.9 MiB | 59,612 / 102,647 |
| omw-es | MCR 3.0 | **mixed** — `engWN/` Princeton, rest CC BY 3.0 | 33.5 MiB | 93,834 / 145,641 |
| omw-pt | OpenWN-PT | CC BY-SA **3.0 Unported** | 17.4 MiB | 54,932 / 74,012 |
| omw-arb | Arabic WordNet v2 | Creative Commons + AWN notice | 8.6 MiB | 18,000 / 37,335 |
| omw-cmn | Chinese Open WordNet | WordNet-style | 19.2 MiB | 63,339 / 79,797 |
| omw-ja | Japanese WordNet | WordNet-style | 53.0 MiB | 94,002 / 158,069 |
| omw-id | Wordnet Bahasa | MIT | 20.0 MiB | 41,478 / 106,688 |
| de | — | only via **odenet**, CC BY-SA 4.0 — there is no `omw-de` | — | — |
| **ru, hi, bn** | — | **no pack exists** | — | — |

`wn/index.toml` (21,022 bytes, measured) lists every available language: `arb bg ca ckb
cmn-Hans da de el en es eu fi fr gl he hr id is it ja lt mul nb nl nn pl pt ro sk sl sq sv
th zsm`. **Russian, Hindi and Bengali are absent from the whole index**, not merely from
OMW 2.0. Two licence disagreements were recorded rather than resolved silently: the `wn`
index calls omw-pt CC BY-SA with *no version* (the artefact says 3.0 Unported — the
artefact wins) and calls omw-es flatly CC BY 3.0 (the artefact says mixed). The umbrella
`[omw]` claim that "all packs permit redistribution" is a convenience assertion, not a
licence.

Filtered size for a lemma+synset-id+language ring file: 911,167 senses across the 8 usable
packs; at ~40 B/row ≈ **35 MiB** — inside the 100 MB cap, no runtime service, a pure-Python
XML pass. That figure is the report's *inference* (arithmetic on real sense counts × an
assumed row width), not a measured output file; the sense arithmetic checks out
(206,978+102,647+145,641+74,012+37,335+79,797+158,069+106,688 = 911,167).

**Verdict: OMW is a SEED GENERATOR, not a shipped tier** — propose candidate rings
mechanically for 8 of 12, keep them in the hand-vetting pipeline that produced the current
698, and accept that ru/hi/bn need a different source regardless.

**(4) CLDR is a clean, measured win — and it is the smallest artefact on the list.**
`cldr-dates-full` 48.2.0 from npm: licence `Unicode-3.0`, 94,909,291 bytes unpacked for all
locales, 5,708,206-byte tarball, `LICENSE` inside the package is UNICODE LICENSE V3. All 12
UI locales present. The report **built the 12-language month table** (wide, abbreviated,
stand-alone) and measured it at **5,205 bytes** — 0.005% of the per-file limit, produced by
a ~20-line filter with no runtime dependency. Non-Gregorian calendars ship as separate
`Unicode-3.0` packages (islamic 67.5 MB, chinese 33.0, hebrew 13.7, indian 13.4, persian
13.4 unpacked), relevant to the calendar-aware holiday layer rather than to this work.

Two traps the data exposes that a hand-built month list would miss:

- **Russian has two paradigms**: format/genitive `января февраля марта` (what appears *in
  dates*) vs stand-alone/nominative `январь февраль март`.
- **Arabic has three competing systems, by region**: `ar`/`ar-EG`/`ar-MA` → يناير فبراير
  مارس; `ar-SY`/`ar-IQ`/`ar-LB` → كانون الثاني شباط آذار; `ar-DZ`/`ar-TN` → جانفي فيفري
  مارس. Indexing only the `ar` locale is a systematic, region-correlated blind spot — and
  the legal-source catalog covers ma, dz, tn, sy, iq and lb.

### 6b.2 What the codebase says that the research pass could not know

Four cross-checks measured **here**, against the tree, on the same day. They change where
CLDR belongs in the plan.

**(a) The month stoplist covers exactly two of the twelve UI languages.**
`configs/stopwords_extra/_multilingual.yml` holds 216 entries, of which **15 are non-Latin
and every one of those is a WEEKDAY** (7 Russian, 8 Arabic). Month coverage measured
against the 12 UI languages: **en 12/12, fr 12/12, de 5/12, id 3/12, es 0/12, pt 0/12,
ru 0, ar 0**, and zh/ja/hi/bn have no entries of any kind. The German and Indonesian hits
are *accidental* — they are only the spellings that collide with English or French
(`april`, `mai`, `august`, `september`, `november`).

So the current state is the worst of both directions at once: **over-deleting in en/fr**
(the Mars/March/May/April regression §5 records) and **not filtering datelines at all** in
ru, ar, zh, ja, hi, bn, es, pt. A Russian dateline `15 января` is indexed as a keyword
today with nothing stopping it.

**(b) That makes a string-level CLDR extension actively harmful.** The obvious use of the
5,205-byte table — paste the missing month names into the stoplist — would extend the
deletion regression to six more languages, erasing `марта`/`مارس`/`março` as topics
wherever they are topics. The bounded harm today is the only thing keeping §5's regression
survivable. **CLDR must feed the date extractor, not the stoplist.**

**(c) `dateextract` already carries most of the vocabulary the stoplist lacks — including
both Russian paradigms and two of the three Arabic systems.** Measured in
`src/timemap/dateextract.py`: Russian genitive *and* nominative (`января`/`январь`,
`февраля`/`февраль`, `марта`/`март`, …), Arabic Gulf/Egyptian (`يناير` `فبراير` `مارس`)
**and** Levantine (`كانون الثاني` `شباط` `آذار`), plus Hindi, Bengali, Thai and Persian
tables and a documented `_MONTH_LANG_OVERRIDES` policy for genuinely ambiguous tokens
(`listopad` = November in pl/cs, October in hr/bs — *"no hint means skipped, never
guessed"*). Chinese has no `一月` entry because CJK dates are handled **numerically**
(年月日, with a dedicated CJK block) — that is by design, not a gap.

This materially cheapens slice 3: **the date-aware fix does not need CLDR to start.** The
extractor's claim coverage is already far ahead of the stoplist's; what slice 3 needs is to
route the drop decision through the spans it already claims.

**(d) The one real CLDR gap is the Maghrebi Arabic system.** `جانفي`, `فيفري` and `أفريل`
(ar-DZ/ar-TN) appear **0 times** in `dateextract.py`. That is a precisely-located, live
recall gap against a legal-source catalog covering dz and tn — and it is exactly the
finding the report surfaced. It is a handful of table entries, not a project.

### 6b.3 Refuted, sharpened, and newly surfaced

**Wikidata Lexemes — refuted for ring growth.** 2020 figures (`search-verified`, both
channels blocked on wikidata.org): lexemes ru 101,137 / en 38,122 / fr 10,520, but
**senses** — the thing a translation attaches to — eu 20,272 / en 12,911 / he 3,845 /
ru 2,292 / da 2,217. Only en and ru of our 12 appear at all, and ru's 2,292 senses against
101,137 lexemes is ~2%. The report's reading, flagged as *its inference*: Lexemes are a
**morphology** resource (useful for matching inflected Russian surface forms back to a
lemma, which FTS5 cannot do) and not a translation resource. Two candidate dump URLs are in
circulation and the sources disagree — **do not hardcode either without a networked check.**

**Wiktextract — the share-alike question is sharpened into a version question.** The kaikki
rawdata page carries **no licence statement at all** (a gap at the distributor); the tool is
MIT; the data is Wikimedia ToU = CC BY-SA 4.0 + GFDL for revisions after ~1 June 2023 and
**CC BY-SA 3.0 for older ones**. CC declared GPLv3 a BY-SA-Compatible License for **4.0
only**, one-way, conditional on providing source (GPL-3.0 satisfies that). **The real
obstacle is the mixture**: a 2026 extract reflects each page's *current* revision, so it is
part 4.0 and part 3.0-only, and the 3.0 portion has no compatibility path into GPLv3.
Coverage: per-edition extracts exist for fr/de/ru/zh/es/ja/pt/id (fr 6.3 GB … id 28.5 MB)
but **no ar, hi or bn edition** — those are reachable only inside the 22.9 GB English
extract (2.6 GB gzipped, extracted 2026-08-28 from the 2026-08-05 dump).

**ConceptNet — per-component licences unsatisfiable, and `/r/Synonym` is not what its name
suggests.** `LICENSE.txt` (1,001 bytes, fetched) splits data CC BY-SA 4.0 / code Apache-2.0
and directs the reader to `DATA-CREDITS.txt` for per-source attribution — **that file 404s
at the documented path**. Structurally, `conceptnet5/readers/wiktionary.py` maps line 126
`synonym → /r/Synonym`, 129 `hypernym → /r/IsA`, 141 `quasi-synonym → /r/SimilarTo` and 142
**`translation → /r/Synonym`** — so cross-language translation and within-language synonymy
collapse into one relation, separable only by comparing endpoint language tags.
`/r/RelatedTo` is a distinct relation, so the loose edges *are* separable.

**A new source family surfaced (not in the brief): multilingual SKOS thesauri.** The UNESCO
Thesaurus is ~4,500 concepts in ar/en/fr/ru/es, ISO 25964, with `prefLabel` + `altLabel` per
language and `skos:broader`/`narrower` keeping the hierarchy **outside** the synonym set —
i.e. it is already ring-shaped, and it has by construction the exact property §6b.1(2) found
missing from OMW. It covers 5 of 12, but **two of them are ru and ar, which OMW cannot
supply at all**. Its licence is described as "open access" and the **identifier is NOT
VERIFIED** — an "open access" claim is not a licence. Leads in the same family, none
investigated: EuroVoc (~7,000 descriptors, 24+ languages), AGROVOC (40+), and **IPTC Media
Topics**, a taxonomy built specifically for news — the most interesting of the three here.

**Prior art (`search-verified`).** Dictionary-based *query* translation — translate the
query, expand to all candidate translations — is the dominant non-neural CLIR technique and
is what rings already implement. A Hindi→English study (arXiv 1608.01561) describes the
baseline concretely (include all translations for multi-translation words, drop multi-word
translations, transliterate named entities) and reports honestly that the plain dictionary
baseline **did not beat** the monolingual baseline — a useful ceiling to hold R1's
expectations against. Anserini/Pyserini (arXiv 2304.01019) do query-translation CLIR on
Lucene with per-language analyzers and no neural first stage. The closest architectural
match found is a Solr plug-in doing Chinese-English cross-language query expansion **from a
SKOS thesaurus** — which is another reason the family above is worth a look.

### 6b.4 Still owed

| Item | Owed by | Note |
|---|---|---|
| Wiktextract 3.0/4.0 revision mixture | **maintainer ruling** | The share-alike question, now correctly framed. Not a blocker for slices 1-4. |
| UNESCO (and EuroVoc / AGROVOC / IPTC) licence identifiers | operator, networked | One session's work, not a research programme. |
| Which Wikidata lexeme dump URL is live | operator, networked | Sources disagree; nothing hardcoded. |
| Q-IDs for "list article" / "Wikimedia internal item" | operator, networked | Deliberately omitted rather than guessed. Confirmed meta-classes: Q4167410 disambiguation page, Q4167836 category item, Q17362920 Wikimedia duplicated page. |
| PanLex format/size | — | Moot given the licence; recorded `NOT VERIFIED` rather than filled in. |

**Seed selection, for slice 5 when it runs.** `wikibase:sitelinks` is the conventional
popularity predicate, and the Freiburg AD cheat sheet warns explicitly that **statement
count is a poor proxy** because external-identifier triples inflate it. Wikidata's own
maintenance-query page documents the `" (actor)"`-suffix trap in its own words: Wikipedia
titles must be unique, Wikidata labels need no disambiguating parentheses, so a
parenthesised label is almost certainly a Wikipedia import. `wikibase-dump-filter` handles
P31/P279 filtering but does not by itself solve the band/film/journal collisions — those
items have legitimate P31 values. **No published ready-made deny-list was found; that is a
gap, not a finding.**

## 7. The attached triage — verification verdict

`oo-keyword-triage-proposal-20260905.json`, model `mistralai/Ministral-3-3B-Instruct-2512`,
prompt `keyword-triage-v1`, `run_state: error`, canaries OK overall, 250,000 terms judged
(truncated), 200 repeat disagreements.

Per the standing **ai-proposed → claude-verified → maintainer-merged** chain, I sampled and
measured rather than trusting the file.

**`stoplist_additions` — 20,611 proposals. NOT safe to apply as a batch.** Three classes:

1. **Genuine publishing furniture — the valuable part.** `COMMENTS`, `RELATED`,
   `unsubscribe`, `browser extensions seems`, `barchart`, `items-`, `menu close menu`,
   `أضف تعليقك` ("add your comment"). This is the class the run was worth doing for.
2. **Dual-use content words — must NOT be applied.** **353 English single lowercase words
   with ≥20 articles** are proposed as junk, including `helicopter` (150 articles),
   `guitar`, `needle`, `pets`, `pigs`, `tomato`, `vacation`, `hikes`, `expense`, `clarity`,
   `height`. These are real topics in a news corpus. Applying them is the recorded
   open-class trap: *no safe blanket rule exists for adjectives and common nouns.*
3. **Mis-languaged rows — 1,547 of 20,611 (7.5%)** are non-Latin script filed under a
   Latin-script language: 1,245 Cyrillic, 208 Hangul, 57 Arabic, 21 Devanagari under `en`.
   Two of the highest-spread "English" proposals are Russian UI boilerplate
   (`разблокировать аккаунт`, 585 articles; `выберите скриншот отправить`, 553).
   The strings are genuinely junk — but the **language field is what makes scoping
   collision-free**, so a 7.5% error rate matters for every scoped decision.

**`kind_overrides` — 64,910 proposals (org 31,126 / person 24,541 / place 9,243). Not
applicable as a batch.** A 25-item sample shows systematic failure modes: **roles labelled
as persons** (`home affairs minister`, `development officer`, `kommissaren`), **common
nouns as orgs** (`circoli` = "circles", `gazetesi` = "newspaper of", `juthat` = a Hungarian
verb), **adjectives as persons** (`graduée`, `هنری` = "artistic"), and mis-language
(`ษโคว`, Thai, filed under `en`). Correct ones exist (`richard pettigrew`, `jacek dubiel`,
`marrakech`, `월간조선`) — roughly half. A ~50% precision label set cannot be merged.

**The most valuable thing in the file is not the junk list.** It is
`held_back.ambiguous_language` — 59,206 terms with the languages each appears under. That
is a corpus-derived ambiguity map, produced for free, and it is a direct input to R2 and to
the diagnostic in §5.

**Recommended disposition:** take the multi-word / boilerplate subset as a reviewed batch,
reject the single-common-word subset outright with the reason recorded so nobody re-proposes
it, treat `kind_overrides` as a worklist rather than a patch, and **keep the ambiguity map**.

## 8. Sequencing

| # | Slice | Gate |
|---|---|---|
| 1 | `expand_query` + search/omnibar wiring + disclosure (**R1**) | none — buildable now |
| 2 | Month-occupancy diagnostic (§5) — how often is a month token outside a claimed date span? | none — read-only |
| 3 | Date-aware month handling + re-index | slice 2's number. **Cheaper than it looked** — `dateextract` already carries ru (both paradigms), ar (Gulf + Levantine), hi, bn, th, fa; §6b.2(c). Ride-along: add the Maghrebi `جانفي`/`فيفري`/`أفريل` gap, §6b.2(d) |
| 4 | Ambiguity map from the existing Wikidata fetch + the triage's `ambiguous_language` | none |
| 5 | Ring coverage expansion (more seeds) | operator: networked run. ru/hi/bn need a source OMW structurally cannot provide (§6b.1(3)) — the SKOS family covers ru+ar (§6b.3) |
| 6 | Sense layer + linker + eval (**R2**) | slices 2–4; own reviewed slice |
| 7 | Synonym tier, separately disclosed | **answered NEGATIVE for OMW** (§6b.1(2)) — the translated synsets already contain hypernyms. Open only for the SKOS family, gated on its licence |

Slices 1, 2 and 4 need no network, no new dependency, and no ruling.

**After research pass 1 (§6b), nothing in slices 1–4 is gated on anything.** The one
maintainer ruling still owed anywhere in the plan is the Wiktextract 3.0/4.0 mixture, which
gates neither. Research pass 2 (sense/homonym disambiguation) is still outstanding and bears
on slices 4 and 6.
