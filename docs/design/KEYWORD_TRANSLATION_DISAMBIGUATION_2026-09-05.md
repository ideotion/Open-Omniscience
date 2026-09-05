# Multilingual keyword translation + sense disambiguation — analysis & plan

**Status:** ANALYSIS + PLAN. Nothing built. Three rulings taken 2026-09-05 (§0); one
decision still owed (§6b.4, the Wiktextract licence mixture), and the month handling waits
on its own measurement rather than on a ruling (§5).
**Code state of record:** `main` @ 83b3cad, verified by direct reading — every claim
below carries its file:line anchor.

---

## 0. Rulings taken 2026-09-05

| # | Ruling | Consequence |
|---|--------|-------------|
| **R1** | **Cross-language search expansion is ON by default, and DISCLOSED.** Searching `climate` also matches `climat` / `Klima` / `clima` / `климат` / `مناخ`. The result surface states the expansion, shows the per-language breakdown, and offers one click back to the literal term. | §3 slice 1 |
| **R2** | **Sense-level identity via Wikidata QID is the target model** for ambiguous terms (April = month \| given name \| organisation). | §4 — the identity model; its *promise* is R2a |
| **R2a** | **That identity is a QUERY-TIME USER CHOICE, not a stored per-mention link.** Searching `April` surfaces the senses with their kinds and descriptions; the reader picks one and expansion runs per-sense from the chosen QID. | §6c.4. No linker, no per-mention storage, no `Keyword` schema change — slice 6 is permanently the inventory half |

Both compose: once a sense has been chosen, expansion can be *per sense* rather than
per string — searching the month April need not drag in April Ryan. R2a settles **who
chooses**: the reader, because the machine cannot (§6c.1(3)).

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

**Shape of the build — AMENDED BY R2a (ruled 2026-09-05).** The paragraph that stood here
described a sense column on the mention plus a linker that assigns a sense on evidence and
leaves it NULL otherwise. Pass 2 refuted the linker (0.335 F1 on news, §6c.1(3)) and the
maintainer ruled the query-time alternative, so the build is now: **a sense inventory
(surface form → candidate QIDs + `P31` kinds, CC0 from Wikidata) and nothing else.** No
sense column, no linker, no per-mention storage, no change to the one-row-per-normalized-
term identity above — the schema limitation this section opens with is no longer a blocker,
because the question it blocks is one we have stopped asking of the machine. What the
inventory publishes is *"this surface form denotes N things"*; which one a given occurrence
means is answered by the reader at query time, per sense, from the chosen QID. The eval
that a linker would have owed is therefore not owed: an inventory's failure mode is
under-coverage, and under-coverage is visible (§6c.4).

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

**(a) The month stoplist covers SEVEN of the twelve UI languages.**

> ⚠ **CORRECTED 2026-09-05 (pass 2), and the error is instructive.** This cross-check
> first read `configs/stopwords_extra/_multilingual.yml` *alone* and reported *"exactly two
> of twelve — es 0, pt 0, ru 0, ar 0"*. That is wrong. `_load_extra_stopwords()`
> (`extract.py:397`) unions **every `*.yml` file in the directory**, and the file's own
> header says so in the sentence this doc quoted at the time: *"LANGUAGE-AGNOSTIC UNION:
> global_stopwords() unions every file here regardless of which one a word lives in."* I
> quoted the warning and then measured as if it did not apply. The corrected figures are
> below; every conclusion drawn from the old ones is re-checked in place.

Measured over the union of all 34 files (2,343 entries), against the 12 UI languages'
month names: **en 12/12 · fr 12/12 · de 12/12 · es 12/12 · ru 12/12 in BOTH paradigms
(nominative and genitive) · id 9/12 · pt 2/12 · ar 0/12 · hi 0/12 · bn 0/12**; zh/ja have
no `一月`-style entries and need none (see §6c.3). Eighty-two distinct month surface forms
are globally banned, thirteen of them for languages the app does not even ship a UI in
(Italian `maggio`, Dutch `maart`).

**The Spanish, German and Russian months are banned from a file named `hi.yml`.** That file
is headed *"Curated EXTRA stopwords — Hindi"* and holds 135 entries: 72 Devanagari, **39
Latin and 24 Cyrillic**. The PR #740/#744 Phase-4.1 migration that split one flat blob into
per-language files put a large multilingual month block there. Behaviourally this is a
no-op — the union is language-agnostic and a test pins the set as byte-identical to the
pre-migration blob, exactly as that migration promised — but the filename is now false
about its contents, and it is what made the pass-1 measurement above go wrong. Re-filing
that block into `_multilingual.yml` is a pure move, set-identical, and the byte-identity
test proves it; it is worth doing before anyone else reads a language file and believes it.

So the current state is still the worst of both directions, on a wider footing than pass 1
reported: **over-deleting in seven languages**, and **not filtering datelines at all** in
ar, hi, bn (and, for ten of twelve months, pt). A Russian dateline `15 января` *is* filtered
today — the pass-1 note claiming otherwise is withdrawn — while an Arabic `15 يناير` is not.

**(b) That makes a string-level CLDR extension actively harmful.** The obvious use of the
5,205-byte table — paste the missing month names into the stoplist — would extend the
deletion regression to six more languages, erasing `марта`/`مارس`/`março` as topics
wherever they are topics. The bounded harm today is the only thing keeping §5's regression
survivable. **CLDR must feed the date extractor, not the stoplist.**

**(c) `dateextract` already carries most of the vocabulary the stoplist lacks — including
both Russian paradigms and two of the three Arabic systems.** Measured in
`src/timemap/dateextract.py`: Russian genitive *and* nominative (`января`/`январь`,
`февраля`/`февраль`, `марта`/`март`, …), Arabic Gulf/Egyptian (`يناير` `فبراير` `مارس`)
and **part of** the Levantine system, plus Hindi, Bengali, Thai and Persian
tables and a documented `_MONTH_LANG_OVERRIDES` policy for genuinely ambiguous tokens
(`listopad` = November in pl/cs, October in hr/bs — *"no hint means skipped, never
guessed"*). Chinese has no `一月` entry because CJK dates are handled **numerically**
(年月日, with a dedicated CJK block) — that is by design, not a gap.

This materially cheapens slice 3: **the date-aware fix does not need CLDR to start.** The
extractor's claim coverage is already far ahead of the stoplist's; what slice 3 needs is to
route the drop decision through the spans it already claims.

> **Sharpened by pass 2's own measurements (2026-09-05).** Two corrections, one in each
> direction. The Levantine claim above was too generous: of seven forms tested the extractor
> knows **three**, and is missing `كانون الثاني` (January), `نيسان` (April), `تموز` (July)
> and `آب` (August) — so Levantine coverage is partial, not complete.
>
> > ⚠ **THREE OF THOSE FOUR ARE WRONG, and the error is the dangerous direction (measured
> > against the tree 2026-09-05, while building the ride-along).** Driving the real
> > extractor over all twelve Levantine names, not a seven-form sample, gives **6/12**, and
> > the misses are not what this paragraph says:
> > * **`تموز` (July) EXTRACTS.** It is in `_MONTH_LANG_OVERRIDES`, ar-gated, because it is
> >   also a real Persian word ("midsummer heat"). Listed here as missing; it is handled.
> > * **`نيسان` (April) and `آب` (August) are DELIBERATE REFUSALS**, with measured
> >   fabrication evidence recorded beside them in `dateextract.py`: *"سيارة نيسان 2023"* is
> >   a Nissan model year, and `آب` is ordinary fa/ur prose ("water"). A month fires beside
> >   any adjacent number, so adding them invents dates. **Reading them as coverage gaps is
> >   how a later session "fixes" them and silently reintroduces the vectors** — which is
> >   what this paragraph invites. They are now pinned as BEHAVIOUR, with their reason, in
> >   `tests/test_arabic_month_coverage.py`.
> > * The genuine gap was the **four MULTI-WORD** names (`كانون الثاني`, `تشرين الأول`,
> >   `تشرين الثاني`, `كانون الأول`) — a third of the Levantine year. The code called them
> >   "out of scope"; that was a claim about the matcher and it was **measured false**
> >   (`_MONTH_ALT` is a plain alternation, the surrounding patterns already wrap it in
> >   `\s+`). All four now resolve with no pattern change: **Levantine 6/12 → 10/12.**
> >
> > The lesson generalises past Arabic: this section read an ABSENCE from a table as a gap
> > without reading the comment above it, and half of those absences were reasoned refusals. And the extractor is
> *better* than pass 2 assumed on Russian: pass 2 correctly reports that CLDR ships only the
> nominative and genitive of six cases, and recommends a suffix rule or stemmer for the
> prepositional `январе` ("в январе"). `dateextract.py` **already carries the prepositional
> forms** (5/5 tested). For Russian the extractor is strictly ahead of CLDR, which is
> cross-check (c) holding on a second, independent measurement.

**(d) The one real CLDR gap is the Maghrebi Arabic system.** `جانفي`, `فيفري` and `أفريل`
(ar-DZ/ar-TN) appear **0 times** in `dateextract.py`. That is a precisely-located, live
recall gap against a legal-source catalog covering dz and tn — and it is exactly the
finding the report surfaced. It is a handful of table entries, not a project.

> **Widened by pass 2 (2026-09-05).** Two independent research passes surfaced the Maghrebi
> system without knowing of each other, which is as close to corroboration as this exercise
> gets. Re-measured against the fuller list pass 2 supplies, the extractor knows **0 of 7**:
> the three above plus `ماي` (May), `جوان` (June), `جويلية` (July) and `أوت` (August). Still
> a table entry each — now with the missing set fully enumerated rather than sampled.
>
> > ✅ **BUILT 2026-09-05, and it was not "a table entry each".** Measured before: **1 of 8**
> > (`مارس` resolves, shared with the Gulf set). Measured after: **7 of 8**. Five names went
> > in ungated (`جانفي`, `فيفري`, `أفريل`/`افريل`, `جويلية`, `أوت`) — French loans with no
> > other Arabic reading. The other two needed the discipline the existing block already
> > applies, and recording WHY is the point:
> > * **`جوان` (June) is ar-GATED**, not ungated: it is a very common Persian word ("young"),
> >   exactly the `تموز` case, so it resolves under an ar hint and is skipped with none.
> > * **`ماي` (May) is WITHHELD.** It is colloquial *water* across the Gulf, Iraq and the
> >   Levant — a collision **within Arabic**, so the language gate that saves `جوان` cannot
> >   help, and the corpus probe that cleared the six ungated Levantine names could not be
> >   run here. Refused on the `آب` precedent: a missing dateline is a visible gap, an
> >   invented date is not. Running that probe is what would settle it.
> >
> > One claim written into the source during this work had to be withdrawn before it shipped:
> > that the non-hamza `اوت` was Persian *"out"* and therefore needed separating from the
> > Maghrebi `أوت`. The table already answered it — `اوت` is **Persian August**, the same
> > French loan, already mapped to 8. Both spellings agree, and the test pins that agreement
> > rather than the distinction it was written to pin.

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

## 6c. Research pass 2 — sense disambiguation (2026-09-05)

The second handed-over prompt came back the same day. Full report held by the maintainer;
what follows is the verdict set, the codebase cross-checks that move it, and the one
decision it puts back to the maintainer.

**Environment, first, because it is now a pattern rather than an incident.** The mandatory
probe ran before the research: `www.wikidata.org`, `query.wikidata.org`, `en-word.net`,
`kaikki.org`, `cldr.unicode.org` and `aclanthology.org` all returned **403 with
`x-deny-reason: host_not_allowed`**, while the `pypi.org` control returned 200 and DNS
resolved normally — a policy gateway, not the origins. A second, sanctioned channel reached
`ceur-ws.org` and arXiv but reports Wikimedia domains as cache-only. **That is the fifth
consecutive session to hit this allowlist on a reach-named-publishers task**, and the second
to characterise it instead of retrying. The consequence is structural and shows in the tags
below: everything GitHub-hosted is first-hand; **everything Wikimedia-hosted is second-hand,
including every dump size**. The fix is an allowlist entry, not a better prompt.

### 6c.1 The four verdicts

**1. The obvious route is a dead end, and knowing that is worth the pass on its own.**
Wikidata *disambiguation items* (`P31 = Q4167410`, ~1.4 M of them) exist only to carry
interlanguage links between Wikimedia projects; they model no real-world concept and
contain little but sitelinks to other disambiguation pages. This is the structural
difference from Wikipedia: an English Wikipedia disambiguation *page* lists the articles it
disambiguates and is therefore a surface-form→sense index, while the Wikidata item that
represents it lists **none of the senses**. Anyone building the homonym dictionary would
reach for `Q4167410` first — the ledger already carries that QID, as a *meta-class filter*
for the ring generator — and would get a list of strings that are ambiguous somewhere,
with not one sense attached. `search-verified` (the policy pages are Wikimedia-hosted).

**2. The mechanism that does work is the one this plan already proposed.** Two Wikidata
items may carry the *same label in the same language* — the paper's own example is `Curry`
as both Q2368856 (the programming language) and Q5195194 (a village in Alaska), separated
only by the description field. So the index is: group **labels and aliases** by
(normalized string, language), keep the groups of size ≥ 2, attach `P31` to each member.
That is exactly the §6 SOURCES plan's *"harvest the AMBIGUITY MAP from the SAME fetch"* —
independently arrived at, and now with named prior art that ships it (OpenTapioca,
Apache-2.0, `fetched`). It is CC0, it needs no live API at runtime, and `P31` gives the
month/person/organisation distinction the maintainer asked for **as a structured field**
rather than as free text.

**3. Resolution — picking *which* sense — is not shippable, and this is the pass's
decisive negative.** On the one apples-to-apples comparison over a news dataset (RSS-500,
InKB micro F1): best system **0.455**, DBpedia Spotlight 0.281, and the Wikidata-native
non-neural linker **0.335**. Word-sense disambiguation tells the same story more gently:
the entire non-neural literature sits in a 65–68 F1 band whose *floor is a lookup table*
(most-frequent-sense), against neural systems in the low-to-high 80s. All graph machinery
buys under three points over picking the commonest sense.

And the numbers are **generous**, for a reason that lands directly on this project's own
requirement: the InKB metric everyone reports **excludes out-of-KB mentions entirely**. Our
requirement is that an unlinked mention stay fully usable — which is precisely the part
nobody benchmarks. One concrete figure from the same paper: of 476 out-of-KB entities in
that news set, human review recovered only 63 in Wikidata. In news, unlinkable is the
majority case for out-of-KB mentions, not an edge.

**4. Two coverage problems, reported by the people who shipped it.** Wikidata aliases are
curated for the auto-suggest box, not for text coverage: `Trump` is an alias of Q22686,
`Cameron` is **not** an alias of David Cameron (Q192), and the alias guidelines explicitly
discourage adding misspellings. Surname-only mentions — routine in news — are where the
index will miss. Second, **Wikidata carries no occurrence counts**: there is no way inside
Wikidata to know how often `USA` meant Q30 rather than Q9212, which kills the
prior-probability idea in its cheapest form. The published substitute is a popularity proxy
from statement count, sitelink count and Wikidata PageRank — all CC0, all derivable from
the same dump.

### 6c.2 What the codebase says — and it refutes the report's first recommendation

The report's headline advice is to **un-ban month names per language** and ship that first,
calling it *"a scoping fix… under 4 KB… no accuracy question because there is no decision
being made"*, and claiming it *"recovers Mars, the March on Washington, and every one of the
losses in your table."* The measurements below say the first half is right about CLDR and
wrong about this codebase, and that the claim is false in a way that matters.

**(a) Per-language scoping of a month name is structurally impossible here — for exactly
the two languages whose months are banned.** Two independent mechanisms, both verified:

- `configs/stopwords_extra/*.yml` is a **language-agnostic union by construction**.
  `_load_extra_stopwords()` (`extract.py:397`) unions every file's word list; the loader's
  own docstring calls the per-language split *"a readability/maintenance convenience, NOT a
  per-language scoping guarantee."* Moving `may` into `en.yml` bans it in all twelve.
- The genuinely scoped channel (`StopwordsManager.scoped_stopwords`) **cannot be reached by
  en or fr**. `get_stopwords()` (`stopwords.py:354`) tests `language_stopwords` *first* and
  the scoped set only in the `elif`; `LANGUAGE_STOPWORDS` has exactly two keys, `en` and
  `fr`. This is a recorded ledger lesson, and it is decisive here: the two languages that
  need scoping are the two that cannot have it.

So the report's cheapest recommendation is, in this tree, a **stopwords-architecture
change** — not a data file. That does not make it wrong; it makes it not free, and it must
not be sequenced as though it were.

**(b) And it would recover under half of the named losses.** Measured over the seven losses
§5 names, asking what per-language scoping does in an English document:

| form | month in | English document |
|---|---|---|
| `mars` | fr | **recovered** — planet Mars, Mars rover, Mars Inc. |
| `avril` | fr | **recovered** in en (still banned in fr) — Avril Haines |
| `mayo` | es | **recovered** — Mayo Clinic, County Mayo |
| `march` | en | **still banned** — the March on Washington, a climate march |
| `may` | en | **still banned** — Theresa May |
| `april` | de, en, id | **still banned** — April Ryan, the April 6 Youth Movement |
| `august` | de, en | **still banned** — August Landmesser |

Three of seven. **The March on Washington is the case the report names as recovered and is
exactly the case scoping cannot touch**, because `march` is an English month in an English
document. Scoping fixes the *cross-language* half only — which the plan already recorded in
§5 and which this measurement now quantifies: of 69 banned forms belonging to a UI language,
**59 are a month in exactly one** of them (so scoping un-bans them in the other eleven) and
**10 are months in several**. The within-language collision, which is where the named
losses live, is untouched by construction.

**This does not retire the idea — it re-ranks it.** Per-language scoping and the date-aware
drop are complements, not alternatives: scoping addresses `mars`-in-English, the date-aware
rule addresses `March`-in-English, and only the second needs the extractor. §5's
recommendation stands, and the cheap occupancy diagnostic (slice 2) still decides it.

**(c) The unlinked case already has a shape in this tree.** The report recommends making
the unlinked value explicit in the schema rather than an absent link, following GERBIL's
epsilon and TAC KBP's NIL, and flags NIL granularity (one per distinct surface string, or
one per occurrence) as a decision to take early. We do not need to import a convention:
`ArticleMentionedDate` already stores `status="candidate"` and filters on
`status != "rejected"` (`datestore.py:90,233`) — a human-confirmable candidate model with a
third state, which is the same shape one layer down. The AI layer's `ai-who`/`ai-place`/
`ai-date` candidate kinds are the second precedent. The granularity question is real and
still open; the modelling question is largely answered by existing practice.

**(d) Two extractor corrections, both folded into §6b.2 above:** the Levantine Arabic
coverage this doc claimed is partial (3 of 7 forms), the Maghrebi gap is 7 forms rather than
3 — and, in the other direction, `dateextract.py` **already carries the Russian
prepositional forms** that the report correctly notes CLDR omits. For Russian our extractor
is strictly ahead of CLDR, which is the second independent confirmation of cross-check (c).

### 6c.3 Corroborated, and one disagreement left standing

Two research passes, run independently, agree on three things worth more for having been
reached twice: **Arabic is not one month list** (transliterated `يناير`, Levantine
`كانون الثاني`, Maghrebi `جانفي` — split by *region*, not by the `ar` tag, so scoping by
language tag silently fails on Lebanese, Syrian, Iraqi and Algerian sources); **CLDR is
`Unicode-3.0` and tiny**; and **the month-homonymy problem does not exist in zh/ja at all**,
because their month names are numeric plus 月 and cannot collide with a name — pass 2 states
it outright, pass 1 inferred it from the extractor's by-design numeric handling, and the
tree confirms 0/12 CJK forms known and 0 banned. A language-agnostic stoplist is therefore
imposing a cost on two of twelve languages in exchange for nothing.

They **disagree on the table's size**: pass 1 measured 5,205 bytes, pass 2 measures 3,843
for a months-only extract (and 228,896 for the twelve full `ca-gregorian.json` files, of
which 216 of 384 distinct forms are usable once the narrow width — single letters `J F M A
M J J A S O N D`, and bare digits in zh/ja — is excluded). Reporting the disagreement rather
than picking: both are under 6 KB, the difference is extraction scope, and nothing in the
plan turns on which is right.

One arithmetic nit, recorded because this document's discipline is not mixing tiers: the
report's prose contrasts a most-frequent-sense baseline of **65.6** against a best
knowledge-based **68.0**, but 65.6 is a SensEval-2 column figure while 68.0 is the ALL
column. The like-for-like ALL comparison is 65.2 → 68.0. The conclusion is unchanged.

### 6c.4 What this does to R2 — RULED: a query-time user choice

R2 reads: *sense-level identity keyed on Wikidata QID is the target model*, and R1×R2
compose because *"once a mention carries a sense, expansion can be per-SENSE rather than
per-string."* Pass 2 leaves the **identity model intact** — QID is the right key, `P31` is
the right kind field, CC0 is the right licence — and refutes the step that would make a
mention *carry* a sense automatically. Slice 6 is two halves and the evidence splits them:

- **the inventory** (surface form → candidate QIDs + kinds): a committed lookup, not a
  prediction. Its accuracy is Wikidata's label accuracy; its failure mode is
  under-coverage, not wrong answers. **Supported.**
- **the linker** (which QID *this* mention means): 0.335 F1 on news, measured on the subset
  where an answer exists. **Not supported**, and the standing preference — *rather ship no
  disambiguation than a silently wrong one* — settles it.

So "once a mention carries a sense" needs a source other than a linker, and there is one
that costs nothing extra: **the reader chooses**. Searching `April` surfaces *"this term
denotes one of three things — the month, the given name, the movement"* with each one's kind
and description, and expansion then runs per-sense from the chosen QID. That is the same
disclosure grammar R1 already requires (expansion stated, breakdown shown, one click back to
the literal term), it ships a claim we can defend instead of one we cannot, and it needs no
per-mention storage at all.

**RULED 2026-09-05 (maintainer): option (i) — sense identity is a QUERY-TIME USER
CHOICE.** The options put were (i) a query-time user choice (recommended — fully evidenced,
no schema change, no linker); (ii) sense identity **stored per mention**, which needs the
refuted linker and the `Keyword` identity change §4 describes; (iii) both, sequenced.

**Option (ii) is DECLINED, and the reason is recorded so it is not re-proposed without new
evidence**: it rests on a linker measured at 0.335 F1 on news — and measured on the InKB
subset, i.e. on the mentions where an answer exists at all, which flatters it in exactly
the direction our requirement does not allow (§6c.1(3)) — plus a change to the
one-row-per-normalized-term identity model. At 0.335 F1 the majority of mentions would be
linked wrongly or not at all; the loss splits between the two, and the wrong half is the
dangerous one, because an absent link is visible and a wrong one is not.

So **slice 6 is now permanently the inventory half**, not provisionally: surface form →
candidate QIDs + kinds, published as *"this term denotes N things"*, with the reader
choosing and the expansion running per-sense from the chosen QID. Nothing stores a sense
against a mention, so nothing can be silently wrong about one. Slice 4 (the ambiguity map)
was always a lookup, is unaffected, and is now the inventory's data source rather than a
step toward a linker.

**What this costs, stated rather than glossed:** a reader who does not pick gets the
existing per-string behaviour, so an ambiguous term still expands across all its senses
unless someone chooses — the honest default, and the one R1 already discloses. Automatic
per-mention sense identity is not deferred pending a better linker; it is out of the plan
until a measurement changes, and the measurement to watch is news-domain linking, not WSD
benchmarks (§6c.1(3)).

### 6c.5 Still owed

The **one measurement this pass could not make** is the one that decides whether slice 4
ships at all: the row count of an ambiguous-only, twelve-language surface-form index. The
dump could not be downloaded, so the report measured the **cost per row** instead and left
the arithmetic: a synthetic index in the shipping shape costs **35.8 bytes per row gzipped**
(TSV, sorted), so a 100 MB file holds about **2.8 million ambiguous surface forms** — a
floor, since synthetic random QIDs are the worst case for compression and real data is
sorted with delta-encodable id runs. Whether twelve languages of *ambiguous-only* forms fit
under that is unknown, and the "ambiguous-only" filter is where the order-of-magnitude
saving lives: unambiguous forms need no sense identity, because the existing one-row-per-
string model already handles them correctly.

Also unverified and worth not re-deriving: CrossWikis (the canonical prior table, 297 M
string-concept pairs) has a **download reported broken and no licence identifier anyone
could find** — not guessed; UKB's licence returned 404 on three standard filenames, which
matters because it is the strongest non-neural WSD system in the comparison; the WordNet
supersense list could not be fetched; and BabelNet's terms were deliberately not asserted.

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
| 3 | Date-aware month handling + re-index | slice 2's number. **Cheaper than it looked** — `dateextract` already carries ru (all three cases tested, incl. the prepositional CLDR omits), ar Gulf + *part of* Levantine, hi, bn, th, fa; §6b.2(c). Ride-alongs: the 7-form Maghrebi gap and the 4 missing Levantine forms, §6b.2(d) |
| 3b | Re-file the mis-filed month block out of `hi.yml` into `_multilingual.yml` | none — a pure move, set-identical, byte-identity test proves it (§6b.2(a)) |
| 4 | Ambiguity map from the existing Wikidata fetch + the triage's `ambiguous_language` | none. Mechanism + prior art confirmed by pass 2 (§6c.1(2)); **size unmeasured** — the one open number (§6c.5) |
| 5 | Ring coverage expansion (more seeds) | operator: networked run. ru/hi/bn need a source OMW structurally cannot provide (§6b.1(3)) — the SKOS family covers ru+ar (§6b.3) |
| 6 | Sense **inventory** (**R2** / **R2a**) | slices 2–4; own reviewed slice. **Permanently** the inventory half — RULED 2026-09-05, §6c.4 |
| ~~6b~~ | ~~Sense linker + eval~~ | **evidence-refuted** (§6c.1(3)): 0.335 F1 on news, measured on the subset where an answer exists |
| 7 | Synonym tier, separately disclosed | **answered NEGATIVE for OMW** (§6b.1(2)) — the translated synsets already contain hypernyms. Open only for the SKOS family, gated on its licence |
| — | Per-language month scoping | **not free here**: a stopwords-architecture change, not a data file (§6c.2(a)), and it recovers 3 of 7 named losses (§6c.2(b)). Complement to slice 3, not a substitute |

Slices 1, 2, 3b and 4 need no network, no new dependency, and no ruling.

**After both research passes, nothing in slices 1–4 is gated on anything.** Two decisions
were owed; one has been taken and one remains, and neither blocks those slices:

1. **What R2 promises** (§6c.4) — **RULED 2026-09-05: a query-time user choice.**
   Stored-per-mention is declined (it needs the refuted linker plus a `Keyword` identity
   change), so slice 6 is permanently the inventory half and row 6b stays struck.
2. The **Wiktextract 3.0/4.0 mixture** (§6b.4), unchanged and still gating nothing.

The **one open number** in the whole plan is slice 4's: whether an ambiguous-only,
twelve-language surface-form index fits under 100 MB. At the measured 35.8 bytes/row that
file holds ~2.8 M forms, and the row count is unknown because the dump is behind the same
allowlist that has now blocked five consecutive sessions (§6c.0). Opening it for
`dumps.wikimedia.org` is the single highest-value operator step remaining.
