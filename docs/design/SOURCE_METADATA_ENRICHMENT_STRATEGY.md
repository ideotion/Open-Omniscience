> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — Strategies 1–3 (corpus topic fingerprints, Wikidata reconciliation, deterministic cleanup) are confirmed SHIPPED. Measured coverage as of 2026-07-22: `source_type` 8.4% (289/3429, up from the doc's 2026-06-27 baseline of 2%), `country` 53.4% (up from 45%) — real but partial progress. Strategy 4 (LLM batch-enrichment of the ~2,900 residual sources) has still only run a 12-source pilot, never the full batch. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Source-metadata enrichment — strategy & automation plan

Status: design + tooling delivered (2026-06-27). Scope: enrich `configs/sources.yml`
so every source carries useful, honest, multi-dimensional metadata instead of the
single `news` tag most of them have today.

Companion artifacts shipped with this doc:
- `scripts/make_enrichment_batches.py` — generate parallel-session worklists.
- `scripts/merge_enrichment_results.py` — fold session results back in, additively.
- `docs/archive/source_enrichment/PROMPT_TEMPLATE.md` — the session prompt.
- `docs/archive/source_enrichment/README.md` — the operator runbook.

---

## 1. Current state (measured, not assumed)

`configs/sources.yml` holds **3,205 sources**. Field coverage:

| field | coverage | note |
|---|---|---|
| name, domain, rss_url, tags, priority, enabled | 3205 / 3205 | always present |
| language | 3109 | 96% |
| country | 1434 | **45%** — over half have no country |
| region | 1398 | 44% |
| source_type | **65** | **2%** — only the hand-curated head carries it |
| reliability_score / update_frequency / cacheability | 65 | same curated head only |

Tag richness is the real gap:

| topical tags per source | count |
|---|---|
| 0 tags | 189 |
| exactly 1 tag | 2502 |
| 2 tags | 471 |
| 3 tags | 43 |

- **675 sources have tags == `[news]` exactly**; **2,958 carry ≤ 1 topical tag**
  (counting tags other than the bucket word `news`). That is the enrichment target.
- The rich vocabulary (history, science, energy, biotech, ai, climate, robotics,
  agriculture, geopolitical, state-media, fake-news, …) exists but is concentrated
  on a few hundred curated entries.

### Data-quality defects found (fix opportunistically)
- **Leaked code tags**: `be`, `lb`, `pcm`, `so`, `ig`, `rw`, `yue` appear as *tags*
  — these are country/language codes that leaked into the tag list from some
  seeding pass. They belong in `country`/`language`, not `tags`.
- **Leaked territory-name tags**: `cook-islands`, `faroe-islands`, `french-polynesia`,
  `new-caledonia`, `marshall-islands`, `saint-lucia`, `antigua-and-barbuda`,
  `saint-vincent-and-the-grenadines` — territory names used as topic tags. Same class.
- These should be migrated to the right field and removed from `tags` (a small,
  deterministic cleanup pass — no research needed).

---

## 2. Taxonomy: the "≈10 types" problem, and the fix

There is **taxonomy drift** — `source_type` is defined differently in every file
that touches it, and it conflates *several orthogonal dimensions* into one string:

- `configs/catalog_query.yml` → `news`, `institution`, `religious` (3)
- live `configs/sources.yml` → `news, scientific, geopolitical, investigative,
  financial, technology, legal` (7)
- `src/stats/ingest.py` → `statistics`
- `src/law/catalog.py` → `legal` / `ip`
- `docs/research/sources/` (the maintainer's gap-fill pass) → **9 values**: `news,
  investigative, geopolitical, government-primary, academic-research, fact-checker,
  data-portal, igo, ngo-civil-society`

So "10 types" is really **9 conventions in the most recent pass, with no single
canonical list anywhere**, and the field tries to encode *medium*, *ownership*, and
*topic* all at once. The fix is to **separate the dimensions** — this is the
"complementing them" the brief asks for. Five orthogonal axes:

### Axis A — `source_type` (the MEDIUM/genre, exactly one). Proposed canonical 16:
`news`, `wire-agency`, `magazine`, `broadcaster`, `investigative`,
`academic-research`, `scientific-journal`, `government-primary`, `igo`,
`ngo-civil-society`, `think-tank`, `fact-checker`, `data-portal`, `blog`,
`religious`, `financial-data`.
(Supersedes the drifted lists; `statistics`→`data-portal`, `institution`→
`government-primary`/`igo`, `legal`→`government-primary`. Keep it tight; add a value
only with a maintainer ruling so the vocabulary stays a controlled set.)

### Axis B — `ownership` (funding/control, exactly one): `independent`, `state-owned`,
`public-broadcaster`, `state-media`, `corporate`, `party-affiliated`, `nonprofit`,
`cooperative`, `wire-agency`. Describes the money/control, **not** slant.

### Axis C — `lean` (political slant, rare): `lean-left … center … lean-right`.
**Reputational and contestable** — set only where a widely-cited assessment exists,
omit otherwise (matches `configs/sources_spectrum.yml`'s existing discipline).

### Axis D — `topics` (subject coverage, 1–4): the open-ended controlled vocabulary
(`politics, economy, science, technology, ai, health, climate, energy, …`).
**Bridge to keyword analytics**: align topic tags with the keyword
ring/super-group vocabulary (`configs/keyword_supergroups.yml`) so a source's
declared topics and the corpus's keyword families speak the same language — this is
literally "sources better attributed keywords."

### Axis E — geography/scope: `country` (ISO-2), `language` (ISO-639-1), `region`
(continental), `coverage_scope` (`local|national|regional|global`).

**Encoding without a schema change**: the DB `Source` model already stores
`source_type`, `country`, `language`, `region`, and a flat `tags` list, and the
spectrum file already puts `lean`/`ownership` *into tags*. So ownership + lean +
topics + scope all fold into `tags` (ownership/lean as controlled tag values), and
only `source_type`/`country`/`language` use their own fields. No migration needed.
The `merge_enrichment_results.py` script encodes exactly this. (A later, optional
refinement: promote ownership/lean/scope to first-class columns + a documented
controlled-vocabulary test — but that is not required to ship the enrichment.)

---

## 3. Automation strategies, ranked by leverage

Five complementary mechanisms. Use them in this order; each one's output narrows
the work the next one must do.

### Strategy 1 — Corpus-derived topic fingerprints (LOCAL, zero-network) ★ primary
The app already extracts keywords per article and stores `KeywordMention.source_id`.
So a source's *real* topical profile is observable from what it actually publishes.
A local job/script aggregates each source's top keyword families/rings over the
corpus and **proposes** topic tags (`tags deduced from N articles`, labelled
deduced, gated by a min-article floor, never auto-applied to curated tags).
- Why first: on-mission (local-first, no fabrication, self-improving as the corpus
  grows), and it directly answers "attribute keywords to sources." It needs no
  network and no LLM.
- Honesty: deduced tags carry provenance and a separate namespace from human tags
  so they never masquerade as asserted facts; aligns with the deduced/confirmed
  two-class convention already used app-wide.
- Limitation: only covers sources you've actually scraped; cold for new/disabled
  sources. That residue is exactly what Strategies 2–4 cover.
- *Status: **BUILT** (2026-06-27). `src/analytics/source_topics.py` (pure,
  unit-tested aggregator) + `scripts/derive_source_topics.py` (the live-corpus
  runner). It aggregates the controlled TOPIC tags (`keyword_tags` axis="topic")
  of the keywords each source publishes, weighted by distinct articles, and emits
  deduced rows (`note: deduced:corpus`, confidence never "high") in the merge
  format. Perf-safe: keys off the denormalised `keyword_mentions.source_id`, no
  keyword_mentions->articles decrypt join (the ledger trap). Coverage scales with
  how many keywords carry baseline topic tags — grows as that vocabulary fills.*

### Strategy 2 — Wikidata reconciliation (NETWORK, deterministic, no LLM) ★ high
`src/catalog/wikidata.py` + `scripts/build_world_news_catalog.py` already query
Wikidata to *create* sources. Extend the pattern to *enrich existing domains*: for
each `domain` in sources.yml, reverse-lookup the entity by official website (P856),
then read:
- `P31` instance-of → `source_type` (newspaper/news agency/magazine/scientific
  journal/public-broadcasting org/…),
- `P127` owned-by / `P749` parent-org / instance-of public-broadcaster →
  `ownership` (state-owned when owner is a government; public-broadcaster by type),
- `P452` industry / `P101` field-of-work / `P921` main-subject / `P136` genre →
  `topics`,
- `P17` country / `P407` language / `P571` inception → geography.
- Why: deterministic, CC0, refreshable, sourced by QID — same ethos as the keyword
  rings; **no hallucination**. Best for well-known outlets.
- Limitation: long-tail/small outlets are absent from Wikidata; Wikidata gives **no
  editorial lean** (the spectrum file's standing note). Expect good coverage on the
  head, thin on the tail.
- The module is pure/testable (build query + parse JSON); only the HTTP call needs
  network (run on a connected machine / the maintainer's box, like the catalog
  builder). *Status: **BUILT** (2026-06-27). `src/catalog/wikidata_enrich.py` (pure,
  fixture-tested) + `scripts/enrich_sources_wikidata.py` (the networked fetch).*
  - v1 scope = **`source_type`** (only 2% covered today) via P31 instance-of, plus
    a `wire-agency` ownership tag. **Anti-fabrication gate**: a name search is
    accepted only when the candidate's official website (P856) resolves to the same
    registrable domain as the source — a wrong hit yields nothing, never a wrong
    type. The P31→type map is deliberately limited to QIDs verified in the repo's
    own `catalog_query.yml` (+ the stable scientific-journal class); extend it on the
    networked run after confirming each class QID, since the gate guards the entity,
    not the mapping. Output rows feed `merge_enrichment_results.py` unchanged.
  - Deferred (honestly): lean (Wikidata has none), fine topics (subject/genre QIDs
    map noisily without label resolution → Strategies 1/4), country/language (ccTLD
    + catalog already cover them).

### Strategy 3 — Deterministic cleanup + heuristics (LOCAL, zero-network) ★ quick win
- Migrate the leaked code/territory tags (§1) into `country`/`language` and drop
  them from `tags`.
- ccTLD → country fallback for the 1,584 under-enriched sources lacking a country
  (the seeder already has `normalize_country`/`cctld`).
- RSS `<category>` terms already present in fetched feeds → candidate topic tags
  (cheap, but noisy → propose, don't apply).
- Why: zero-cost, high-confidence, shrinks the dataset the expensive strategies see.

### Strategy 4 — LLM parallel sessions (NETWORK, the brief's prompt path) ★ the residue
For everything Strategies 1–3 can't resolve — especially `lean`, nuanced
`ownership`, and topics for small outlets — classify in batches with Opus 4.8 + web
search. This is what the maintainer already did for the gap-fill scaffold. **The
prompts and worklist tooling are delivered with this doc** (§4).
- Use it on the *residual* under-enriched set after 1–3, not the full 2,958, to save
  effort — but it can also run standalone today (the worklist generator selects the
  full under-enriched set by default).

### Strategy 5 — External datasets (NETWORK, optional, licence-gated)
GDELT GKG / Media Cloud / OpenSources domain→metadata exports can be folded via the
catalog builder's existing `--merge-csv`. Media-bias datasets (e.g. MBFC) could seed
`lean`/`ownership` but are **contestable and licence-encumbered** — treat as a
*suggestion* source, never authoritative, and only with a maintainer ruling on
licence. Lowest priority.

---

## 4. The parallel-session pipeline (delivered, ready to run)

Designed around **Opus 4.8's limited tool-call budget**: one session = one batch =
one structured answer after a *handful* of searches. The prompt forbids multi-step
browsing and caps web search at one call per uncertain source, leaning on the
model's parametric knowledge for the (many) well-known outlets.

1. **Generate worklists** (local, no network):
   ```
   python scripts/make_enrichment_batches.py            # batches of 50, by language
   python scripts/make_enrichment_batches.py --max-tags 0 --languages en,fr
   ```
   Writes `docs/archive/source_enrichment/batches/prompt_<lang>-NNN.md` (each = the
   template with that batch's compact input inlined) + a `MANIFEST.txt`. Default run
   = **113 batches** (en: 43, es/fr: 4 each, then the long multilingual tail). The
   bulk is gitignored; `prompt_en-001.md` is committed as a worked example.

2. **Run in parallel**: paste each `prompt_<id>.md` into a fresh Opus 4.8 session
   with web search. Group by language so each session stays in one linguistic lane
   (better recognition, fewer searches). Save each session's YAML answer to a file.

   *Throughput note:* batch size × parallelism is the dial. 50 sources/batch keeps a
   session comfortably inside the tool-call budget (most rows answered from
   knowledge, searches reserved for the uncertain). Drop to 30–40 for tails in
   languages the model knows less well.

3. **Merge back** (local, additive, dry-run by default):
   ```
   python scripts/merge_enrichment_results.py results/ --min-confidence medium
   python scripts/merge_enrichment_results.py results/ --min-confidence medium --write
   ```
   - Unions tags (topics + valid ownership + valid lean), sets `source_type` only
     when missing/default, fills `country`/`language` only when absent. **Never
     overwrites curated values; never invents new sources** (unmatched domains are
     reported, not added). Low-confidence rows are skipped by default.

Review the diff before committing (it is a normal `git diff` on sources.yml). Keep
new rows `enabled:false` if you ever extend the pipeline to add sources — but the
default merge only *enriches existing* entries.

---

## 4b. Subagent / Workflow fan-out (the scalable execution of Strategy 4)

The brief flagged the scale ("so many sources") and the single-session tool-call
limit. The decisive property: **each subagent has its own tool-call budget.** So
splitting the work one-batch-per-subagent multiplies the usable budget by the number
of agents — fan-out is the correct tool for thousands of sources, not a nicety.

Verified 2026-06-27: **web search works from inside this environment**, so the
classification can run *in-session* via subagents rather than only via external chat
sessions. Two delivered execution paths (same output rows, same merge):

- **Workflow** (`docs/archive/source_enrichment/enrich_sources.workflow.js`): pass the
  under-enriched rows as `args`; it chunks them (default 40/batch), spawns one
  web-enabled subagent per batch with **schema-validated** structured output (no YAML
  parsing, the model retries on mismatch), and returns the merged row array. Honors
  the concurrency cap (~10–16 agents at once) up to the 1000-agent ceiling — ample for
  ~60–75 batches over 2,958 sources. Requires opting into the Workflow tool.
- **Agent fan-out**: spawn a handful of `general-purpose` subagents in parallel, each
  given one `input_*.txt` batch + the template rules, each returning YAML. No Workflow
  opt-in needed; good for pilots and small runs.

Either way the rows land in `results/` and flow through `merge_enrichment_results.py`.

**Pilot (2026-06-27, live):** three `general-purpose` subagents ran in parallel over
a 12-source slice of en-001 and each returned clean schema-conforming YAML in
~6–10 s. Quality was high (Al Jazeera → broadcaster/state-owned; AP →
wire-agency/cooperative; RT → state-media; Fox → corporate/lean-right; ABC Australia
→ public-broadcaster; +972 → magazine/nonprofit/lean-left), and the agents answered
from parametric knowledge (**0 tool calls** on this well-known slice), spending
search budget only where genuinely uncertain — confirming the per-agent-budget
economics. The long tail of obscure outlets will trigger more searches; that is
exactly the work fan-out distributes. See `docs/archive/source_enrichment/README.md`.

**Taxonomy edge found in the pilot:** a few `sources.yml` entries are not
journalistic at all (e.g. `new.abb.com` = ABB Robotics' corporate vendor page).
No `source_type` fits, and the honest output is `confidence: low,
note: "corporate vendor site, not news"`. The merge skips low-confidence rows by
default, so these surface for human review rather than getting a fabricated type —
and they are candidates for *removal* from the catalog, a separate cleanup.

## 5. Honesty constraints (non-negotiable, carried from the project ethos)
- **Never fabricate** a tag/type/country. Omit + lower confidence instead. A wrong
  attribution is worse than a missing one (it corrupts every geographic/topical
  analysis downstream — the same failure that motivated the de-US-centring work).
- **No composite scores.** These axes are descriptive labels; `reliability_score`
  stays operator-set, never computed. `lean` is reputational/contestable and stated
  as such, never presented as fact.
- **Deduced ≠ confirmed.** Corpus-derived (Strategy 1) and LLM-derived (Strategy 4)
  tags are labelled by provenance and confidence; Wikidata-derived (Strategy 2)
  carries its QID. The merge keeps human/curated values winning over machine ones.
- **Controlled vocabularies** for source_type/ownership/lean so the set stays small
  and analysable; topics are open but should lean on the keyword-ring vocabulary.

---

## 6. Recommended sequencing
1. Deterministic cleanup (Strategy 3) — **SHIPPED** (PR #498): leaked-tag migration + ccTLD backfill.
2. Wikidata reconciliation (Strategy 2) — **SHIPPED** (PR #499): `source_type` coverage; run the fetch on a networked box.
3. Corpus topic fingerprints (Strategy 1) — **BUILT**: deduced topic tags from the corpus; run on the live DB.
4. LLM parallel sessions (Strategy 4) — the residual + lean/ownership. *(tooling delivered — run now)*
5. External datasets (Strategy 5) — optional, licence-gated. *(deferred)*

Items 1–3 are designed here and are the recommended next code builds; item 4 is
runnable today with the delivered tooling.
