# Source qualification — throughput, efficiency and article junk: analysis and plan (2026-09-10)

**Status:** planning-only. Nothing was coded, no setting was changed, no verdict was touched.
**Anchor:** `main` @ `f85899a` (2026-09-10). Every code claim below was re-read from that tree; every
field number carries the date and artifact it came from. Numbers this document could NOT measure are
marked as estimates and say what they depend on.
**Reads with:** `docs/plans/2026-09-06-repo-analysis/PROMPT_04_sources-qualification-and-promotion.md`
(the standing prompt for this area — this document supersedes its S1/S2/S4 framing with measured
arithmetic and adds the throughput findings it did not have),
`QUESTIONS_FOR_THE_MAINTAINER.md` B1/B5/B6/B7/B11, the 2026-08-03 source-qualification brief, and
`docs/design/SCRAPING_10X_SCALING_STRATEGIES_2026-07-24.md` §3 S-A ("widen the funnel").

## 0. The maintainer's three observations, restated as claims the tree can test

The maintainer (2026-09-10) reported, on a live instance:

1. The app starts from ~3,600 curated, tagged sources, all deliberately stamped **unqualified**.
   After nearly three weeks of collection, only **~1,000** are qualified.
2. In the same period discovery produced **~80,000 source candidates**.
3. Articles that should never have entered the corpus are still being stored, with the
   qualification engine on.

And two asks: the qualification engine must become much faster **and** more efficient, and the
initial source list should grow significantly.

Restated as testable claims:

- **C1.** At the shipped budgets, ~1,000 qualified in ~21 days is close to what the design permits,
  not a malfunction. (§2 F1 — true, with the arithmetic.)
- **C2.** The curated catalog is not merely slow to qualify; part of it is *parked* behind the
  discovery backlog by the queue's own fairness rule. (§2 F2 — true by construction; the bundle
  will say how much.)
- **C3.** The dominant per-verdict cost is a whole-corpus scan whose cost tracks the corpus, not the
  batch, and the steady-state engine pays it once per collection pass. (§2 F3 — true.)
- **C4.** "Qualified" today means little more than "the trial stored at least one article", so the
  stamp cannot keep junk out and was never designed to. (§2 F4 — true, and the junk the maintainer
  sees is the *article* gate's known, measured hole, §2 F8.)
- **C5.** ~80,000 candidates is discovery working as designed, and most of them are not things a
  trial can judge. (§2 F7 — true.)

## 1. What the machinery does today (verified against `main` @ `f85899a`)

### 1.1 The catalog, and the unqualified-by-decision stamp

- `configs/sources.yml` holds **3,429** entries, every one with an `rss_url`, 3,427 of them
  `enabled: true`. Boot also seeds `sources_spectrum.yml` (278, 11 with a feed), `markets_sources.yml`
  (112, no feeds) and `legal_sources_generated.yml` (226, no feeds). Of the 3,870 entries a boot
  seeds, **475 are shadowed** by a same-domain sibling and never register (`Source.domain` is UNIQUE;
  ruling B11 open) — so an install starts with ~3,400 registered app-provided sources.
- Every seeded row is `status='unqualified'` (`Source.status`, `server_default`). No grandfathering
  of the curated catalog is a **maintainer ruling** (2026-07-20; restated as item 2 of 0.4 gate Row
  A): "a catalog source that fails is a catalog-review signal, not a source to exempt". The
  2026-09-04 ruling then added the designed way to make verdicts *travel*: a generated
  `configs/source_qualification.yml` overlay adopted at boot (`src/catalog/qualification_overlay.py`),
  produced by `GET /api/diagnostics/source-qualification-export` + `scripts/merge_source_qualification.py`.
  **That file does not exist yet** (operator step B5), so every fresh install re-qualifies the
  whole catalog from zero.

### 1.2 The admission gate and its two scope toggles

`select_sources` (`src/scheduler/runner.py:386-427`) admits `enabled=True AND status='qualified'`.
Two toggles shipped 2026-08-03 (`src/scheduler/settings.py:125-132`), both default off:

- `scrape_unqualified` — also admit not-yet-judged sources (never `disqualified`; enabled only).
- `scrape_app_provided_only` — narrow to the seed-time `via:*` provenance set
  (`src/catalog/provenance_scope.py`).

With both on, the app collects from the shipped list without waiting for trials. This is the
already-built, already-consented lever behind the maintainer's "maybe we will revise this decision".

### 1.3 How a verdict is reached

`run_qualification_pass` (`src/catalog/qualification.py:~440-700`), per invocation:

1. **Select** up to `per_pass` never-yet-qualified sources — `select_unqualified` orders
   never-attempted first (by id), then least-recently-attempted; it has **no `enabled` filter**
   (B1). Plus up to `recheck_per_pass` due re-checks (own budget since 2026-09-04).
2. **Trial-fetch** each candidate **serially**: a feed source runs `ingest_source(max_items=5)` —
   one feed fetch plus up to five article fetches; a feedless one runs `sitemap_trial_ingest` —
   robots-declared or conventional sitemaps (≤5 fetched, ≤500 URLs) then ≤5 article ingests. Every
   fetch goes through `EthicalFetcher` (robots fail-closed, per-host politeness, `rate_limit_ms`
   default 2,000, Tor when the install runs protected mode). Stored articles are kept.
3. **Freeze the cohort**: `source_audit.frozen_cohort` — `collect_article_stats` over the **whole
   corpus** (every non-quarantined article row + a `GROUP BY article_id` over `keyword_mentions`),
   the per-language article baselines, the per-source metrics for every source, and the
   cross-source furniture DF (one `corpus_keywords` per source). The bulk job freezes it **once per
   run** (S5.1, 2026-09-03). The ride-along passes no provider, so it freezes **once per pass**
   (`advance_qualification` → `run_qualification_pass(cohort_provider=None)`).
4. **Judge** the candidates' own metrics against the frozen cohort (`scoped_metrics` +
   `flag_criteria(min_articles=1)`) and **stamp** (`evaluate_and_stamp`). A candidate with zero
   stored articles gets a `no_evidence` attempt row and keeps `unqualified`.

**What can actually flip a verdict.** `decide_verdict` disqualifies only when `derive_status` is
`degraded`/`failing`, which requires the one `extraction_failure` criterion, `pathology_rate`, to
flag. It flags either on the **cohort tail** (above the language cohort's p90, *and* ≥5 pathological
articles — impossible from a 5-item trial unless every item is pathological) or on the **absolute
floor** (≥50 % of the source's articles pathological). A "pathological" article is one whose
`mention_density` is high AND `type_token` low AND `single_kw_dominance` high relative to its
language cohort's p10/p90 — all three derived from the **keyword index**, so an article with no
keyword mentions has no metrics and can never be pathological. The five soft criteria are capped at
`watch` by design and never disqualify. So, for a trial:

| Trial outcome | Verdict |
|---|---|
| 0 articles stored (feed dead / robots / Tor 403 / no sitemap / all duplicates / all non-article) | `no_evidence`, stays unqualified, rotates to the back |
| ≥1 stored, fewer than half look like keyword-furniture vs the cohort | **qualified** |
| ≥1 stored, half or more pathological | disqualified |

Field data on the third row: on the 2026-08-03 merged corpus **no source of 457 reached the floor**
(max 0.211); the 2026-08-11 1M-article export found **only 2.89 % of audited articles carried any
keyword mention** (21 languages at exactly zero), which makes the pathology signal blind for the
other 97 %. In practice the stamp is a *liveness* check with a rare-catastrophe detector on top —
exactly what the 2026-08-03 brief §0 already said ("the gate cannot currently disqualify any source
in this corpus").

### 1.4 The two engines, their budgets and their stop rules

| | Ride-along (`_lane_step_qualification`) | Bulk drain (`qualify_job.run_bulk_qualification`) |
|---|---|---|
| Trigger | every online collection pass, on the housekeeping lane thread | manual button / `POST /api/sources/qualify-bulk` / the unattended-run button |
| Budget | `qualification_per_pass` = 5 (profile low 2 / optimized 5 / max 20; range 0–100) + `qualification_recheck_per_pass` = 2 | batch 20 (profile 10 / 20 / 100), loops until empty |
| Cohort scan | **once per pass** | once per run |
| Skips | lane still busy from the previous pass → this pass's kick is dropped (`runner.py:1909`); memory guard engaged → lane stops taking kinds; machine below the floor (`scan_budget`: <4 GB total or <1 GB available) → declines the whole pass | memory guard → pauses, **does not auto-resume**; 10 consecutive batches with no stamp (200 candidates) → honest stop, **does not auto-restart**; unattended start refuses when available RAM < 1,000 MB + 1,000 MB per million articles |
| Concurrency | trial fetches serial within the step; the step is one of up to nine lane kinds run in sequence | trial fetches serial within a batch |

### 1.5 Discovery — where ~73–80k candidates come from, and what they are

- **World discovery** (`src/catalog/discover_job.py`, ride-along `world_discovery_per_pass`=2
  countries/pass): Wikidata entities per country with an official website, for the types in
  `configs/catalog_query.yml` — newspapers, agencies, TV and radio stations, periodicals, magazines,
  broadcasters, **plus legislatures, ministries, government agencies, religious organisations and
  denominations**, `limit: 5000` per (country, type). Inserted as **disabled** `Source` rows with
  `via:wikidata-discovery`, **no `rss_url`**, no topical tags. Field: 66,697 added by 2026-07-24
  (245/249 countries); 73,079 "Discovered candidates" on 2026-07-26; the maintainer's ~80k today.
  Composition of the 2026-07-23 field export (46,213 rows = 42,612 disabled + 3,599 enabled):
  `source_type` **institution 20,777 · news 17,021 · religious 7,957** — the ledger's own
  comment: "the Wikidata specs' breadth makes the qualification membrane ESSENTIAL before any of it
  enables".
- **Citation funnel**: `citation_channel` (a domain cited by ≥3 distinct stored articles →
  `SourceCandidate`, review-before-promote) and `promote_cited_sources` (≥2 distinct citing
  *sources* → disabled `Source` tagged `cited`). Commerce / social / infrastructure / disqualified
  domains are refused at the chokepoint.
- **Wikipedia references** channel (zero-network, from watched pages' wikitext).

Two facts about this population matter for throughput: it is overwhelmingly **feedless** (the
Wikidata generator never sets `rss_url`), and a large share is **not a publisher** at all (ministries,
agencies, churches). The OPEN_QUEUE records ~17k discovered/cited sources with **no topical tags**.

### 1.6 The article gate, and what it deliberately lets through

At ingest, `store_fetched` → `classify_non_article` (`src/ingest/non_article.py`):

- a body of **≥100 words is kept whatever its URL looks like**, unless the prose gate fires
  (function-word density < 0.12 **and** sentence punctuation < 0.01 — both, by design);
- only a thin body reaches the URL-shape rules (homepage, `/tag/x`, `/category/x`, `/search`,
  `/page/N`, single-segment section fronts) and the consent/paywall wall phrases.

`classify_index_page` — the same URL shapes **regardless of body length**, split into Tier 1
("a real article is structurally impossible here") and Tier 2 ("a listing by convention") — exists
since 2026-08-11 but is used **only** by the source-quality report and the retroactive quarantine
job, never as an ingest drop. The quarantine job's write is opt-in and has **not been run** (0.3 gate
row 5: Tier A = 8 articles agreed 2026-08-23; Tier B = the listings above the guard, "not proposed,
measure first").

Measured on the 2026-08-11 1M-article export: in a 2,247-article unbiased control, **10.95 %** of
stored articles carry a URL the module's own rules call a non-article, **8.10 % of the corpus sits
above the 100-word guard** at such a URL, and **36 of 36** hand-read above-guard items were listings
(section fronts, tag archives, homepages, a sitemap, a search page). On the 2026-08-23 40,260-article
release bundle: 8 Tier A + 451 index pages above the guard (1.12 %). The prose gate also lets
**headline-list pages** through by construction (moderate density, no sentences) — the module
docstring calls that "the source-level auditor's territory".

### 1.7 The counters the maintainer sees

`database_stats` partitions `sources` exactly: *Sources (collecting)* = enabled ∧ qualified;
*awaiting qualification (enabled)* = enabled ∧ not qualified; *Discovered candidates* = disabled.
The Library tile additionally records `sources_never_attempted` (enabled, unqualified, **no attempt
row**) beside `sources_never_judged` (enabled, unqualified — including sources tried repeatedly with
no evidence). The attempt log (`source_qualification_attempts`) stores the verdict, the time and the
criteria version — **not why** a trial produced no evidence, and not the trial's tally.

## 2. Findings

### F1 — ~1,000 qualified in ~21 days is inside the design envelope

The ride-along ceiling is `qualification_per_pass` × lane invocations. With `continuous=True`, a
5 s inter-pass gap and a 60-minute pass budget, an instance runs somewhere between ~24 passes/day
(long passes) and a few hundred (short passes over a small qualified set, most feeds answering
304). The lane is kicked once per pass and dropped when the previous kick is still running. So:

| Passes/day | Attempts/day at 5/pass | Attempts in 21 days |
|---|---|---|
| 24 | 120 | ~2,500 |
| 100 | 500 | ~10,500 |

Qualified ≤ attempts, and on the recorded field shape roughly a third to a half of first trials
yield no evidence (feed unreachable through the transport, robots unavailable, zero entries, or
all entries already stored/non-article). ~1,000 qualified in three weeks is therefore what a
5-per-pass trickle produces; the bulk drain is the tool the ledger already names for the catalog
("~180 batches, ~15 h" for the enabled set — `docs/product/UNATTENDED_RUN_RUNBOOK.md`), and
whether it ran, ran to completion, was declined on memory, or stopped on the no-progress rule is
the first thing the bundle must answer (§9).

### F2 — the curated catalog gets parked behind the discovery backlog

`select_unqualified` orders never-attempted sources first, then oldest-attempt first. On a fresh
install the catalog is seeded before discovery, so the first ~3,400 attempts do reach it. But **a
catalog source whose first trial produced no evidence** (one Tor-403, one robots timeout, one dead
feed, one pass where every entry was already stored) receives a `no_evidence` attempt row and moves
**behind every never-attempted candidate** — i.e. behind ~73,000 disabled Wikidata rows. At 5 per
pass that is ~14,600 passes before it is retried: for practical purposes never. The rule was built
to end a livelock (2026-07-23, correctly) and, at this backlog size, it turned into a one-strike
parking rule for the very list the app ships with. On a merged multi-instance corpus, where ids
interleave, the catalog does not even get the first sweep to itself.

**How to see it:** in the Library tile, `sources_never_attempted` ≈ 0 for enabled sources while
`sources_never_judged` ≈ 2,600 means the catalog was swept once and its failures are parked.

### F3 — the whole-corpus scan is paid per verdict batch, and per pass in steady state

`frozen_cohort` reads every article row and aggregates every keyword mention. Recorded costs:
~131.8 MiB of Python per call on the 2026-09-02 field corpus (before S5.1), ~1,025 B/article
measured with `tracemalloc` (rounded up to 1,200 in `machine_floor`), ~797 B/article in the
expedition heuristic, "~5 min per batch on a slow box" (2026-08-12). On a 1M-article instance that
is on the order of **1 GB and minutes, to judge ≤7 sources**, on every collection pass — and it is
the reason the machine floor (`<4 GB / <1 GB available`) can decline the ride-along outright and the
unattended button can decline the drain (need = 1,000 MB + 1,000 MB per million articles). The
2026-07-26 seven-instance comparison recorded that the diagnostics bundle's `source-audit` member —
the same scan — "categorically cannot finish inside its 300 s deadline" at ~6.9 M keywords /
76,679 sources on the 700k-article machine. The 2026-08-12 lesson named the fix shape ("O(corpus)
per RUN instead of per batch") and S5.1 built it for the bulk job on 2026-09-03; the ride-along has
no "run", so it never received it.

Three things make most of that scan unnecessary for a *trial* verdict:

- the cohort changes slowly (a batch of 20 does not move a corpus-wide p90 — S5.1's own argument),
  so a baseline frozen once per **change-token / time window** serves every pass in between;
- the only cohort-dependent path that can disqualify is the pathology **tail**, which a 5-item
  trial cannot reach (needs ≥5 pathological articles); the **absolute** floor needs only the
  candidate's own articles and the per-language article baselines;
- the furniture DF (one `corpus_keywords` per source over a bounded sample) feeds a soft criterion
  that can never disqualify, yet it is the expensive half of the freeze.

### F4 — the verdict is nearly liveness, and it depends on keyword indexing

From §1.3: with fewer than five pathological articles the only disqualifier is "≥50 % of the trial's
stored articles look like keyword furniture relative to the language cohort". Two consequences:

- A source whose feed is a list of **section fronts** or **tag archives** with ≥100-word teaser
  bodies stores them as articles, has ordinary keyword ratios, and qualifies. This is the maintainer's
  observation 3, and it is the article gate's hole (F8), not a qualification bug.
- If the keyword index lags the trial (the backfill queue was wedged until PRH-01, 2026-09-07; the
  2026-08-11 export saw 2.89 % coverage), the trial's articles have no metrics, nothing can be
  pathological, and the verdict degrades to "stored ≥1 → qualified". Whether that is the case on the
  maintainer's instance is a bundle question (§9).

### F5 — the bulk drain is a one-shot tool

`_MAX_CONSECUTIVE_NO_PROGRESS = 10` × batch 20 = **200 consecutive no-evidence candidates** end the
run. The backlog is ~73k mostly-feedless rows, and the sitemap channel rescues only sites that
publish one; a run of 200 unresolvable candidates in a row is not rare in a queue ordered by id
within a country's Wikidata dump. A memory pause also ends the run. Neither restarts itself, and the
unattended button starts the job exactly once. So even when the drain is started, it can quietly end
on day one and leave the trickle to do the rest.

### F6 — per-candidate network cost, and a serial loop

A feed candidate costs up to 6 fetches; a feedless one up to 5 sitemap fetches + 5 article fetches;
each fetch pays transport latency (seconds over Tor) and, within one host, the 2 s politeness gap.
Candidates in one batch are different hosts, but the loop is **serial**, so a 20-candidate batch is
~100–200 fetches end to end — on the order of 5–10 minutes of wall clock per batch that the
collector's own bounded fan-out (`collect_parallelism`, 50 workers optimized; the machine-floor cap
of 8 on small boxes) would compress by an order of magnitude with **per-host politeness untouched**.

### F7 — qualification bandwidth is spent on rows whose verdict has no effect (B1), and on rows that are not sources

`select_unqualified` has no `enabled` filter and `evaluate_and_stamp` never writes `enabled`, so the
disabled ~73k are trial-fetched and judged, and a `qualified` verdict on one of them changes
nothing for collection (recorded 2026-07-26; ruling B1 still open). Independently, the Wikidata
specs admit legislatures, ministries, agencies and religious organisations — **28,734 of the
46,213 rows in the 2026-07-23 export (62 %) are `institution` or `religious`**, not `news`. A trial
can only ever find "no feed, maybe a sitemap" there, and if it does find pages they are not
journalism — the gate judges extraction validity, never editorial merit, so they would qualify.
Nothing screens the queue by channel, feed presence, language manageability or `source_type`
before spending fetches.

### F8 — the junk articles are expected under the current design, and they are measured

Three populations enter the corpus by design (§1.6): listing pages ≥100 words at listing-shaped
URLs (8–11 % of a 1M corpus on the 2026-08-11 measurement; 1.12 % on the 40k release bundle),
headline-list pages that pass the AND-gated prose gate, and non-article prose from non-publisher
sources. A fourth population, articles in **unmanaged languages** (no stoplist / unsegmented), is
"un-analysable junk" for the keyword engine by the app's own `unmanaged-languages` endpoint's
wording, and nothing at qualification time checks it. The retroactive clean-up that would remove the
first population is an agreed-but-unrun operator step (Tier A), and its larger half (Tier B) is
explicitly unmeasured.

### F9 — the measurement gap

The attempt log records `verdict` only. A `no_evidence` row cannot say *feed 403* vs *robots
unavailable* vs *zero entries* vs *all duplicates* vs *no sitemap*; a `qualified` row does not carry
the trial tally (entries / stored / non_article / duplicate). Every diagnosis in this document
therefore has to be inferred from counters, and the first slice below fixes exactly that, because
tuning a funnel nobody can see is how the 2026-07-23 livelock and the 2026-09-04 never-ran ladder
both happened.

### F10 — supply growth channels exist and have never been run

`scripts/build_world_news_catalog.py` (the committed `world_news_sources.yml`, seeded automatically
once present) has never been run; the 14-cluster diversification brief has never executed
(English share 68.8 % on 2026-07-22); the overlay file (B5) does not exist; 475 shadowed catalog
entries — including 30 BBC language services and the political-spectrum catalog at 79 % — are
waiting on the source-identity ruling (B11).

## 3. What "efficiency" should mean here

Why the qualified-source count is the lever at all, in the ledger's own words: the 2026-07-23
throughput verdict measured that **2,766 of 3,599 enabled sources have an `rss_url` and yield ≈2
new articles/day/feed**, with ~90 % of feed entries already stored, and concluded "10× needs more
QUALIFIED+ENABLED sources + crawl mode, not more workers". Collection volume is bounded by the offer,
and the offer is bounded by how many sources have passed — or been let past — the membrane.

The qualification funnel, with the cost of each stage today and the stage that should bear it:

| Stage | Today | Cost driver | Should be |
|---|---|---|---|
| Intake (what enters the trial queue) | every `unqualified` row, enabled or not, any channel/type | none — so fetch budget goes to rows that cannot resolve or cannot matter | screened: has a channel (feed / sitemap / autodiscovered feed), is a publisher type, manageable language; disabled rows only when a verdict can act (R2) |
| Ordering | never-attempted first, then oldest attempt; one queue | catalog parked behind 73k after one miss (F2) | two queues with their own budgets: app-provided/enabled first, discovered second; retry ladder for `no_evidence` inside each |
| Trial fetch | serial, ≤6 or ≤10 fetches per candidate | transport latency × serial loop (F6) | bounded parallel across hosts, same politeness per host |
| Verdict | needs a whole-corpus cohort freeze | corpus size, per pass in steady state (F3) | cohort cached by change-token/TTL; absolute, cohort-free criteria for the trial; the cohort-relative audit reserved for the periodic re-check |
| Stop/resume | no-progress stop, memory pause, no restart (F5) | operator attention | self-resuming with backoff; no-progress judged per queue |
| Visibility | verdict only (F9) | — | reason + tally per attempt; a funnel diagnostic |

Targets this plan is written to (estimates from the code's shape and recorded latencies, to be
re-derived from the Phase-0 measurements):

- the enabled catalog (~3,400) judged in **under one day** on an optimized-profile box;
- a 73k feedless backlog screened in hours (no fetches for rows with no channel) and its
  fetchable remainder trialled in **days, not months**;
- the ride-along's steady-state cost independent of corpus size;
- zero fetches spent on a candidate whose verdict cannot change what the app collects.

## 4. Decisions only the maintainer can take

Each is recorded as a question in `docs/ledger/OPEN_QUEUE.md` (this session, rule (2)); none is
assumed below. Recommended defaults are marked.

**R1 — Revise "the curated catalog starts unqualified"?** The 2026-07-20 no-grandfathering
ruling protects against a verdict asserted by curation. Options:

- (a) keep it, and make verdicts travel: the maintainer generates `configs/source_qualification.yml`
  from the live instance (B5, zero code) so every install inherits the ~1,000 verdicts earned so
  far and re-verifies them on the 6-month clock;
- (b) **provisional admission for app-provided sources** — collection from the shipped list
  starts on day one (the semantics `scrape_unqualified` + `scrape_app_provided_only` already
  implement, made the default for `via:curated`/`via:spectrum`/`via:markets`/`via:legal` rows), the
  trial runs in the background and a `disqualified` verdict still removes the source. The stamp
  stays honest: an unjudged source reads "collecting · not yet verified" in the row pill, never
  "qualified";
- (c) stamp the curated catalog `qualified` by curation — the option the 2026-07-20 ruling
  rejected as fabricated-by-curation; **not recommended**;
- (d) (a) + (b) together.

**Recommended: (d).** What the gate measurably protects the curated list against is a source whose
trial stores nothing — and such a source collects nothing under (b) as well. The pathology floor has
fired on zero of 457 field sources; the cost of the gate on the catalog is weeks of silence for a
protection the data has not yet needed. (b) amends a ruling and is therefore R1, not a settings row.

Three facts to weigh with it:

- The 2026-07-20 ruling's own corollary was that "the preliminary/release tests must verify the
  INITIAL LIST PASSES qualification — a catalog source failing it is a CATALOG-REVIEW signal". The
  ruling assumed the catalog would be judged quickly and pass; three weeks to reach 1,000 is the
  premise not holding, not the protection working.
- Two UI rulings already treat "collected but not yet qualified" as a distinct, hidden class: the
  Feed tab excludes "quarantined AND not-yet-qualified" articles (ruling 11, 2026-08-07) and Home's
  "Latest" counts and names the articles it withholds because their source is not qualified
  (`USER_MANUAL.md`). Under (b) those rulings do exactly the right thing — the articles are gathered
  now and surface the moment the trial passes — and the withheld count becomes visible progress
  rather than silence. Whether Search/analytics should also withhold them is part of R1.
- The catalog carries its own human verification: **405 entries** are `verified: true` with a
  `last_verified` date (2026-06-09 / 2026-07-01), 3,024 are `verified: false`, and the seeder
  currently **drops both fields**. A narrower (b) — provisional admission only for entries a human
  verified — is available at zero fabrication cost if the field is carried; it is a claim about the
  feed, not a quality stamp (the 2026-09-07 "a row-level verification tier says nothing about the
  endpoints inside the row" lesson applies: `verified` was set by fetching the feed, which is the
  thing being admitted).

**R2 — `enabled` vs `qualified` for discovered candidates (B1).** Recommend **(b)**: a `qualified`
verdict on a discovered candidate flips `enabled=True`, with (i) a per-pass promotion cap, (ii)
diversity weighting by language/country so one Wikidata dump cannot flood collection, (iii) an
audit view listing every auto-enabled source with its trial evidence and a one-click undo, and (iv)
intake screening (R5) so the trial queue holds only rows a verdict can act on. Under (a) instead,
`select_unqualified` gains the `enabled` filter and the 73k rows stop consuming fetches, but they
also never become sources without a manual enable step — which at 73k rows is no path at all.
Precedent: ruling Q3a (2026-07-13) already asked for "the FULL funnel (candidate → trial →
graduated) with trial auto-enable behind a DEFAULT-OFF setting", and the 2026-07-20 gate ruling
amended it to "qualification IS the admission gate"; (b) is the reading in which those two rulings
say the same thing.

**R3 — What must a source verdict protect against, beyond "the scrape is furniture"?** The one
disqualifier is calibrated above the observable range (B6). Recommend B6 **(c) extended**: add two
**absolute, cohort-free** extraction-failure criteria, each with its raw count and a stated method:
`listing_url_rate` (share of the source's stored articles whose URL is listing-shaped — already
computed per source by the 2026-08-11 export, language-agnostic, needs no keyword index) and
`high_link_density` (415 of 675 pre-label hits in the 2026-08-03 exports, from `article_links` and
`word_count` alone). Thresholds are **calibrated from the maintainer's export**, published beside
the constant, never tuned to make a number move. Keep `pathology_abs_floor` at 0.5 as the
rare-catastrophe detector, as B6 (a) words it.

**R4 — The article gate.** Recommend: (i) drop **Tier 1** listing shapes at ingest regardless of
body length — a homepage, a bare `/tag/`, `/page/N`, an auth/cart/feed/sitemap/search path cannot
carry an article, so the "a false positive is data loss" argument that keeps the 100-word guard does
not apply to them; (ii) run the agreed Tier A quarantine (operator); (iii) measure Tier B on the
maintainer's instance with the calibration diagnostic before proposing it; (iv) surface a per-source
"listing share" in the Sources row so an operator can see a feed that is really a section index.
Tier 2 shapes above the guard stay kept at ingest until (iii) has numbers.

**R5 — Discovery intake.** Which rows may enter the trial queue at all: recommend *publisher* types
only (newspaper, agency, broadcaster, periodical, magazine, TV/radio) by default, with institution
and religious-organisation rows kept as **registry entries** (they remain discoverable and
promotable by hand) rather than trial candidates; unmanaged-language rows deferred until their
language gains a stoplist; feedless rows trialled only after a one-fetch feed autodiscovery
(`<link rel="alternate">` on the homepage, through `EthicalFetcher`) or a sitemap is found.

**R6 — Supply growth.** Which operator runs to schedule: the world catalog generator (commit
`world_news_sources.yml`), the diversification brief, the overlay (B5), and the B11 source-identity
decision (one feed per outlet, or a feed-keyed source).

**R7 — Baseline staleness.** How stale may a cached cohort baseline be for a trial verdict — the
session default proposed below is *"the newer of: 24 h, or the serve-gate change token moving by
≥1 % of articles"*, recorded in the attempt result as `baseline_age_s` exactly as S5.1 already does.
Listed for transparency; a session may set it.

## 5. The plan

Each slice is one draft PR, its own tests, and the honest carry-over section the working-mode file
requires. ⚠ marks a mandatory adversarial pass with the negative-space lens before push (a gate,
a threshold, or the write path is touched).

### Phase 0 — measure on the real instance (operator + one session, ~1 day)

The maintainer pulls the all-diagnostics bundle (§9). A session reads `source-qualification-export`
(the app-provided split: qualified / disqualified / pending / never-attempted), the expedition log
(did the drain start, decline, pause, or stop on no-progress), `qualification-integrity`, the
source-quality export (per-source `listing_url_rate`, `pct_indexed`, the pathology distribution) and
the pass journal (lane skips per pass). Output: which of F1/F2/F3/F5 dominates on this instance, and
the calibration numbers R3/R4 need. **Nothing below depends on Phase 0 for its design; several
depend on it for their thresholds.**

### Phase 1 — efficiency slices that need no ruling

- **S1 · Attempt reasons + a funnel diagnostic (F9).** Additive columns on
  `source_qualification_attempts`: `reason` (a closed vocabulary: `feed_unreachable`,
  `robots_unavailable`, `robots_disallowed`, `no_entries`, `all_duplicates`, `all_non_article`,
  `no_sitemap`, `transport_refused`, `judged`), plus the trial tally as JSON. Migration (random
  12-hex id, head from `alembic heads`), boot self-heal for the columns, merge carries them.
  `GET /api/diagnostics/qualification-funnel`: attempts per reason per channel per day, the two
  queues' depths, lane skips, scan declines. A Library-tile line for "attempted, no evidence" by
  reason. Every later slice reports its effect through this.
- **S2 · Two queues, two budgets (F2).** `select_unqualified` becomes two selections — app-provided
  ∪ enabled first, discovered/disabled second — each with its own per-pass budget
  (`qualification_per_pass` splits into `qualification_catalog_per_pass` and
  `qualification_discovery_per_pass`, the old key kept as the sum for settings compatibility) and
  its own least-recently-attempted rotation, so a miss in one queue never parks a source behind the
  other. Inside a queue, `no_evidence` retries follow a short ladder (1 h → 6 h → 1 d → 7 d, capped)
  instead of "after everyone else". Ordering, never exclusion — pinned by a test that every
  candidate is reached in bounded passes, and by the 2026-07-23 livelock reproducer re-run
  against the new order (a candidate that can never produce evidence must still rotate out of the
  way, never occupy a window forever). ⚠
- **S3 · Cohort cache for the ride-along (F3).** The scheduler owns a process-level cached freeze
  keyed by `serve_gate.change_token`, refreshed per R7's staleness default, passed as
  `cohort_provider` to `advance_qualification` — the same seam the bulk job already uses, so
  verdict semantics are unchanged and `baseline_token`/`baseline_age_s` say how old the baseline was.
  Also: `with_furniture=False` for trial verdicts. That is verdict-neutral by construction —
  `furniture_share` can only move a source between `degraded` and `failing`, and `decide_verdict`
  maps both to `disqualified` — but it is the kind of one-line change the 2026-08-11 lesson says
  to ship as its own reviewed step with a parity test, so it is its own commit. Expected:
  steady-state qualification cost independent of corpus size; the machine-floor decline becomes a
  once-a-day event instead of a per-pass one. ⚠
- **S4 · Bounded parallel trial fetches (F6).** The trial loop fans out across candidates through
  the collector's existing worker pool and `BandwidthGovernor` (per-host politeness and robots are
  per-fetch and untouched; the machine-floor worker cap applies). Stored-article writes stay behind
  the single-writer gate. Expected: batch wall clock ÷ ~8–10.
- **S5 · The drain that keeps going (F5).** Bulk job: no-progress judged **per queue** (a run of
  feedless discovered rows must not end the catalog's drain); pause/stop reasons recorded; an
  automatic resume with backoff from the maintenance loop (memory recovered → resume; no-progress →
  resume after the S2 retry ladder has something due). The unattended-run button arms the resume
  rather than a single start.
- **S6 · Pre-trial screening (F7, no ruling needed for the cheap half).** Before any trial: skip a
  row whose language is unmanaged (deferred with a reason, not judged); for a feedless row, one
  guarded homepage fetch for feed autodiscovery (`<link rel="alternate" type=application/rss+xml|atom>`)
  writes `rss_url` when found (NULL-only, never overwriting an operator value), else the existing
  sitemap trial, else `no_channel` with no further fetches until the retry ladder says so. The
  autodiscovery fetch goes through `EthicalFetcher.fetch` — never the guard helpers directly — and
  its test asserts zero DNS resolutions under airplane mode, because a resolve is itself egress
  (the 2026-08-01 preflight lesson). The `source_type` screen (institutions, religious
  organisations) waits on R5.

### Phase 2 — ruling-gated slices

- **S7 · Provisional admission of the app-provided list (R1).** Defaults flip for app-provided
  rows; the Sources row pill reads "collecting · not yet verified" (×12 locales, invariant #17
  hover); `select_sources`' docstring and `USER_MANUAL.md` §"Source qualification" amended; the
  2026-07-20 ruling amendment recorded. Tests: an untouched install with the ruling off is
  byte-identical; a `disqualified` app-provided source is still excluded; a discovered row is never
  admitted by this path. ⚠
- **S8 · The promotion frontier (R2).** `qualified` ⇒ `enabled` for discovered rows, capped per
  pass, diversity-weighted (language/country round-robin over the due set), audit view (every
  auto-enabled source with its trial evidence, channel, first citing article where known) and undo
  (disable + a recorded reason, never a delete). Migration-free if the cap and the audit ride the
  attempt log (S1). ⚠
- **S9 · Two absolute extraction-failure criteria (R3).** `listing_url_rate` and
  `high_link_density` join `source_audit.CRITERIA` with `extraction_failure: True`, raw counts,
  `min_articles` guards, thresholds from Phase 0 published in `gates.py` beside their basis;
  `CRITERIA_VERSION` bumped; the criteria panel renders them from the backend as it does today. ⚠
- **S10 · Article gate hardening (R4).** Tier 1 at ingest (counted, reversible via the existing
  `OO_SKIP_NON_ARTICLES`, a distinct `IngestResult` detail); per-source listing share in the row;
  Tier B measured on the instance. ⚠
- **S11 · Discovery intake by type and channel (R5).** The Wikidata specs split into *trial-eligible*
  and *registry-only*; existing rows reclassified by their `source_type`; the funnel diagnostic
  shows both classes.

### Phase 3 — supply (operator runs, session support)

- **S12** run and commit `world_news_sources.yml` (needs a clearnet session; the sandbox's egress
  allowlist refuses publisher hosts — record the probe, do not retry blindly).
- **S13** the diversification brief's 14 clusters (same constraint).
- **S14** generate and commit `configs/source_qualification.yml` from the maintainer's instance
  (B5) — after S1/S7, so the exported verdicts carry reasons.
- **S15** the B11 source-identity decision; if "feed-keyed", its own migration stack.

### Sequencing

S1 first (everything else reports through it), then S2 + S3 (independent files; the two largest
throughput wins that need no ruling), S4 + S5 + S6, then Phase 2 as rulings land — S7 can go the
day R1 is answered and needs none of Phase 1. Phase 3 in parallel, operator-paced.

## 6. What each slice buys (estimates; the funnel diagnostic replaces them with measurements)

| Slice | Mechanism | Expected effect |
|---|---|---|
| S2 | the catalog gets its own budget and a short retry ladder | the ~2,600 parked catalog sources are retried within days instead of never |
| S3 | cohort cached per change-token | per-pass qualification cost drops from a corpus scan to a scoped read; the memory-floor decline stops being per pass |
| S4 | parallel trial fetches | 20-candidate batch from ~5–10 min to ~1 min of fetching |
| S5 | self-resuming drain | the drain runs to completion unattended instead of ending on the first 200 dead rows |
| S6 | screening | no fetches for unmanaged-language rows; a share of feedless rows gain a feed from one fetch; the rest cost zero further fetches until due |
| S7 | provisional admission | the shipped list collects from day one; qualification becomes verification rather than a gate on the catalog |
| S8 | promotion | discovered candidates that pass become sources, at a capped, diverse rate |
| S9 | absolute criteria | a source whose feed is a section index can be disqualified on its own evidence, without a cohort scan |
| S10 | Tier 1 at ingest | the structurally-impossible listing shapes stop entering the corpus |

Combined, the catalog is judged in hours (S2 + S4 + S5) and the discovery backlog is *screened* in
hours and *trialled* in days; the steady-state engine stops scaling with the corpus (S3).

## 7. What this plan does not do, and the lines it keeps

- **No composite score, no ranking.** New criteria are categorical with value + count + method;
  no payload key contains `score`/`rating`/`ranking`/`grade` (`_walk_no_score` covers the panel).
- **Extraction validity only, never editorial merit.** R5 screens by *type of entity* and *channel
  presence*, not by what an outlet says; a terse or unfamiliar source is never penalised for style.
- **Review-before-enable is kept for everything that is not a verdict.** S8 enables only on a
  measured `qualified` verdict, capped and auditable; nothing enables on discovery alone.
- **Consent and transport unchanged.** Every new fetch (feed autodiscovery, parallel trials) goes
  through `EthicalFetcher` under the standing online envelope; never under airplane; no transport
  downgrade.
- **Reversibility.** Quarantine stays a stamp; disqualification keeps its ladder; undo is a disable
  with a recorded reason.
- **No threshold is tuned to make a number move.** Every threshold in S9/S10 is calibrated from a
  named export and published beside its constant with the observed range.
- **The local model stays propose-only.** The qualification assist exists and has a button; the
  measured record of small local models on adjacent tasks is the reason it does not become a gate:
  the source-tag sweep's canary scored 118 of 118 batches "failed" with zero wrong topics (a
  transport failure read as a judgement), its systematic defect is that a keyword-derived tag
  describes the scrape window rather than the source, and the keyword-junk sweep's verdicts were
  90 % not stoplist material on a hand-classified sample (all 2026-09-05). A sampled second opinion
  on trial articles can help *calibrate* R3's thresholds; it must not decide a verdict.
- **Not in scope:** `derive_status`'s soft-criteria cap (load-bearing, unchanged); the stoplist
  rulings; the recency-windowed re-check (B7, its own slice); the storage rulings; whether keyword
  aggregates should exclude quarantined articles (PRH-06 — a pending ruling whose answer moves the
  `furniture_share` denominator, so S3/S9 must not pre-empt it).

## 8. How we will know

- Phase 0 gives the baseline: qualified / pending / never-attempted / attempted-no-evidence for the
  app-provided set; attempts per day; lane skips; scan declines.
- After S1–S6: the funnel diagnostic shows attempts per reason per day; the target is "catalog
  pending → 0 within a day of the drain starting, and the discovery queue's fetch count per verdict
  falling below 2".
- After S9/S10: the source-quality export's per-source `listing_url_rate` distribution for
  *qualified* sources, before and after; the count of Tier 1 drops per day at ingest.
- The Library qualification tile already plots the four counters hourly; the drain's effect is
  visible there without new UI.

## 9. What to send now (operator)

From the running instance, `GET /api/diagnostics/all` (the bundle carries every member below), or
individually: `source-qualification-export` (the app-provided split), `qualification-integrity`,
the source-quality export (`source-quality` with its manifest — `listing_url_rate`, `pct_indexed`,
the per-source pathology distribution), the expedition log if the unattended button was used, the
scheduler pass journal, and `GET /api/sources/qualification/config` (the live counts and the
current toggles). Plus, if easy: the Settings → Diagnostics memory line and the power profile in
use. That is enough to decide which of F1–F5 dominates and to calibrate R3/R4.

## Appendix A — anchors

| Fact | Where |
|---|---|
| admission gate + scope toggles | `src/scheduler/runner.py:386-427`; `src/scheduler/settings.py:98-132` |
| selection, trial, verdict, no-evidence, ride-along | `src/catalog/qualification.py` (`select_unqualified`, `trial_fetch`, `run_qualification_pass`, `advance_qualification`) |
| criteria, cohort freeze, flagging, status | `src/analytics/source_audit.py` (`CRITERIA`, `frozen_cohort`, `flag_criteria`, `derive_status`) |
| pathology definition, article stats, cheap signals | `src/analytics/source_quality.py` (`compute_metrics`, `flag_outliers`, `collect_article_stats`, `select_cheap_signals`) |
| bulk drain, stop rules | `src/catalog/qualify_job.py` |
| lane kick / skip | `src/scheduler/runner.py:1895-1935`, `run_housekeeping_lane` |
| memory floor, scan budget | `src/config/machine_floor.py`; `src/monitoring/expedition.py:400-485` |
| profiles | `src/config/power_profiles.py` (`qualification_per_pass`, `qualification_batch_size`, `pass_budget_minutes`, `collect_parallelism`) |
| discovery | `src/catalog/discover.py`, `discover_job.py`; `src/discovery/channels.py`, `cited_sources.py`; `configs/catalog_query.yml` |
| article gate | `src/ingest/pipeline.py:139-180`; `src/ingest/non_article.py`; `src/services/prose_gate.py` |
| quarantine | `src/analytics/quarantine_job.py`; `docs/product/RELEASE_0.3_GATE.md` row 5 |
| overlay / export / merge | `src/catalog/qualification_overlay.py`, `qualification_export.py`, `scripts/merge_source_qualification.py` |
| counters | `src/api/database.py:110-160`; `src/database/snapshots.py:55-160` |
| panel payload | `src/api/source_management.py:1590-1725`; `src/catalog/gates.py` |

## Appendix B — numbers used, and where each comes from

| Number | Provenance |
|---|---|
| 3,429 catalog entries; 3,427 enabled; 3,870 seeded; 475 shadowed / 299 domains | `configs/*.yml` counted in this session; `tests/test_catalog_domain_collisions.py` (2026-09-07) |
| 5 / 2 per pass; batch 20; profiles 2/5/20 and 10/20/100 | `src/scheduler/settings.py`; `src/config/power_profiles.py` |
| 66,697 discovered (245/249 countries); 73,079 candidates; 42.6k–66.7k backlog | field diagnostics 2026-07-23/24/26 (ledger) |
| 0 of 457 sources at the 0.5 floor; max 0.211 | two `source-quality` exports, 2026-08-03 |
| 2.89 % of 991,686 audited articles with a keyword mention | source-quality export, 2026-08-11 |
| 10.95 % listing-shaped URLs in a 2,247-article control; 8.10 % above the guard; 36/36 listings | source-quality export, 2026-08-11 (`non_article.py` module comment) |
| 8 Tier A + 451 above-guard index pages of 40,260 | release-scale bundle, 2026-08-23 (`RELEASE_0.3_GATE.md` row 5) |
| ~131.8 MiB per cohort call; ~1,025 B/article; ~797 B/article; ~5 min/batch on a slow box | 2026-09-02 crash analysis; `machine_floor.py`; `expedition.py`; 2026-08-12 unattended-run diagnosis |
| 415 of 675 pre-label hits = `high_link_density`; 1.64× enrichment | 2026-08-03 brief F3 |
| ~17k discovered/cited sources without topical tags | OPEN_QUEUE (source-tag assignment entry) |
| 46,213 = 42,612 disabled + 3,599 enabled; institution 20,777 / news 17,021 / religious 7,957 | field feedback answer A7, 2026-07-23 (OPEN_QUEUE) |
| 2,766 of 3,599 enabled sources with `rss_url`, ≈2 new/day/feed, ~90 % duplicates | field feedback A11/A12 + the throughput verdict, 2026-07-23 (OPEN_QUEUE) |
| `source-audit` bundle member cannot finish in 300 s at ~6.9 M keywords / 76,679 sources | hardware diagnostics comparison, 2026-07-26 (OPEN_QUEUE) |
| 405 `verified: true` / 3,024 `verified: false` catalog entries; both fields dropped by the seeder | `configs/sources.yml` counted in this session; `seed_sources._PASSTHROUGH_FIELDS` |
| source-tag canary 118/118 "failed", 0 wrong topics; keyword-junk sample 90 % not stoplist material | LESSONS.md, 2026-09-05 entries |
| English share 68.8 % (2358/3429) | diversification brief status, 2026-07-22 |
| ~1,000 qualified in ~21 days; ~80,000 candidates | maintainer, 2026-09-10 (this session) |
