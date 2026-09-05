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
| **Wikidata Lexemes** | CC0 | lexical senses, forms | strong R2/synonym candidate; size + coverage unverified |
| PanLex | believed CC0 — **verify** | very broad translation pairs | promising for the long tail; quality varies by pair |
| Open Multilingual WordNet | **varies per language pack** | synsets = senses + synonyms | directly models April-as-sense; per-pack licence review needed |
| Wiktionary / Wiktextract | CC BY-SA | largest sense + synonym coverage | **needs your share-alike ruling** — already flagged as open in the ledger |
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

**Facts to verify before committing to anything past Wikidata** — routed to the research
sessions in `docs/design/research-prompts/`, because guessing a licence or a dump size is
exactly the fabrication this project forbids.

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
| 3 | Date-aware month handling + re-index | slice 2's number |
| 4 | Ambiguity map from the existing Wikidata fetch + the triage's `ambiguous_language` | none |
| 5 | Ring coverage expansion (more seeds) | operator: networked run |
| 6 | Sense layer + linker + eval (**R2**) | slices 2–4; own reviewed slice |
| 7 | Synonym tier, separately disclosed | source ruling (§6) |

Slices 1, 2 and 4 need no network, no new dependency, and no ruling.
