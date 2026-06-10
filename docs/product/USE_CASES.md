# Use-case scenarios — Open Omniscience v0.0.7

**No terminal required.** After a one-time install, everything below happens in the browser
app at `http://127.0.0.1:8000` — clicking tabs, buttons and panels. The *only* command line
in this whole document is the one-time installer; the installer then creates a desktop
launcher you double-click to run (see `docs/QUICKSTART.md`). Where a step has a developer-
facing API underneath, it is noted in *(parentheses)* for contributors — you never type it.

```bash
# The one and only terminal step (once, ever):
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

Each step is labelled **[works today]** (verified capability), **[after audit fixes]** (works
today *because of* the v0.0.7 audit), or **[needs RM-xx]** (requires a roadmap item from
[ROADMAP.md](ROADMAP.md)). No scenario relies on the quarantined, fabricated "detection"
features — where a persona wants those, the honest substitute or honest gap is stated.

> **UI map** (the left sidebar, grouped by intention): **Investigate** — Home · Search ·
> Insights · Temporal map · Wikipedia. **Collect** — Collect (ingest) · Sources · Markets ·
> Agenda · Law. **Trust** — Library · Evidence & custody. **System** — Settings · Help.
> A command palette (Ctrl/⌘-K) jumps anywhere.

---

## 1. Local investigative journalist — a cross-border corruption timeline

**Persona & context.** A reporter at a small Balkan outlet investigates a procurement scandal
across three countries and four languages, and cannot use cloud tools that a subpoena could
unmask.

**Goal.** A sourced, deduplicated timeline of every report touching "Adriatic Logistics
d.o.o.", with quotable translations and defensible provenance.

**Workflow (all in the app).**
1. **Sources** tab → the packaged catalog already lists major outlets per country; tick the
   regional ones on, or **+ Add source** by pasting a homepage **[works today]**.
2. **Collect** tab → **Scrape now** (or set the scheduler running): ethical fetch with
   robots fail-closed, per-host politeness, and automatic retry on transient errors
   **[after audit fixes: BUG-02]**.
3. **Search** tab → type `"Adriatic Logistics" AND (tender OR procurement OR ugovor)` — the
   Boolean/phrase/parentheses search just works **[works today]**.
4. Open any non-English article → **Translate** button (runs locally; the translation is
   saved alongside the article with its model + version) *(API: the LLM endpoints)*
   **[works today, needs Ollama installed — offered by the installer]**.
5. **Temporal map** tab → the dates *mentioned in* the articles appear as pins on the time
   slider; confirm the real ones with a click **[works today]**.
6. On each key article → **Add to briefing**; open the **Briefing** drawer, write notes, and
   **Export → Markdown**. From **Search**, **Export → CSV** gives one row per article with
   URL, canonical URL, content hash and fetch time **[works today]**.
7. Optionally, on an article → **Log to custody** (signed, hash-chained) so she can later
   prove what she had and when **[works today]**.

**Output artifact:** a Markdown timeline brief + an evidence CSV
(`title,url,canonical_url,hash,published_at,source,language` per row).
**Gap:** finding the company under transliterated spellings needs semantic/NER search
**[needs RM-05]**.
**Invariant check:** every fetch robots-checked; translation is local (zero cloud calls);
provenance on every row; the operator is never identified to anyone.
**Success metric:** timeline built offline in an afternoon; every published claim links to a
hash-verifiable stored article.

## 2. Disinformation researcher — tracking a narrative's spread

**Persona & context.** An academic studying how a health-scare narrative moves across fringe
and mainstream outlets.

**Goal.** Identify which outlets ran near-identical copy, in what order, and export a
defensible dataset.

**Workflow.**
1. **Sources** tab → enable the political-spectrum set (ships with lean-left → lean-right
   tags) and add fringe sites with **+ Add source** **[works today]**.
2. **Collect** tab → **Settings → scheduler**: turn on incremental pulls every few hours
   **[works today]**.
3. **Search** the narrative's signature phrase → the results panel groups
   **near-duplicate clusters** (with the honest "text overlap, not meaning" note)
   **[works today; scaling verified in the audit]**.
4. **Insights** tab → the **coordination** and **source-integrity / prominence** views show
   same-story timing across source families **[works today]**.
5. Sort the cluster by date + confirmed mentioned-dates → the propagation sequence; pin the
   sequence to a briefing and **Export → JSON** **[works today]**.

**Honest gap:** *bot-network detection and "propaganda scores" are not offered* — those
implementations were quarantined as fabricated. A who-cites-whom **network graph** export
**[needs RM-11]**; real, measured coordination models **[needs RM-14]**.
**Invariant check:** spectrum tags are sourced editorial metadata, not algorithmic verdicts;
every signal carries its caveat; all local.
**Success metric:** a reproducible dataset (export + custody hashes) a journal will accept.

## 3. Fact-checker — verifying a viral claim under deadline

**Persona & context.** A fact-checker receives "EU bans wood stoves in 2027, reported
everywhere."

**Goal.** A structured verdict with citations, in under two hours.

**Workflow.**
1. **Collect** tab → paste each of the 5 cited URLs → **Ingest** (anything robots-disallowed
   is refused with a clear message — itself reportable) **[works today]**.
2. **Law** tab → the legal-source catalog already lists EUR-Lex; **Track** the relevant page
   so its baseline text + hash are stored **[works today]**.
3. **Search** `("wood stove" OR "solid fuel") AND 2027`; open the **Insights → framing**
   view to contrast how the cited articles actually phrase it **[works today, Insights needs
   the analysis tools installed — an installer checkbox]**.
4. Open the legal document → **Summarize** (local; saved as provenance-tracked *assistance*,
   never the verdict) **[works today, needs Ollama]**.
5. Image in the post? **Evidence & custody → Verify image metadata** — honest EXIF
   extraction, clearly labelled "metadata validation, **not** deepfake detection"
   **[works today]**.
6. **Evidence & custody → Build evidence bundle** → a Merkle-rooted, signed file anyone can
   re-verify (the panel shows how) **[works today]**.

**Output artifact:** a verdict note + an evidence bundle a colleague re-verifies without
trusting the tool.
**Gap:** claim-to-source semantic matching **[needs RM-05]**; a verdict-template export
**[needs RM-07]**.
**Invariant check:** the LLM assists; the verdict cites stored, hashed documents; image
checks state their limits; offline except the initial fetches.
**Success metric:** every citation resolves to a hash-verified object.

## 4. Newsroom data desk — a maintained regional corpus

**Persona & context.** Two data journalists keep a shared corpus of ~150 regional sources
feeding the newsroom's own pipeline.

**Goal.** A self-refreshing, deduplicated, searchable corpus with clean exports.

**Workflow.**
1. **Sources** tab → **Import CSV** (download the template button first; bad rows are
   reported, not dropped) **[works today]**.
2. **Sources → Groups** → make per-beat groups; set each group's priority and rate limit with
   the inline controls **[works today]**.
3. **Collect** tab → scheduler in RSS mode, hourly; the **Home** system panel shows live
   fetch activity; dedup is automatic (canonical URL + content hash) **[works today]**.
4. **Search → Export → CSV/JSON** nightly (carries provenance columns); **Library →
   Download backup** weekly onto the NAS **[works today]**.

**Gap:** push/folder-drop export instead of manual download **[needs RM-06]**; a versioned
export-schema contract **[needs RM-07]**.
**Invariant check:** the audit's −63% DB-size fix keeps the corpus NAS-friendly; dedup is a
tested guarantee.
**Success metric:** zero upkeep beyond curating sources.

## 5. OSINT trainer — a workshop in an amnesic Qubes VM

**Persona & context.** A trainer runs OSINT-hygiene sessions in disposable Qubes VMs; nothing
may persist.

**Goal.** The full collect→search→export loop inside a disposable VM, leaving no trace.

**Workflow.**
1. Install once with the Qubes-aware installer (the menu offers Template/AppVM modes — still
   just the installer, no manual commands) **[works today]**.
2. Launch in **ephemeral mode** from the launcher (RAM-only data, wiped on exit) — exposed as
   a launcher option, no terminal flag needed for trainees **[works today; today the flag is
   set once by the trainer — a one-click "ephemeral session" launcher entry is RM-09]**.
3. Trainees **Collect** from a workshop fixture site; the trainer flips its robots to
   `Disallow:` to demonstrate the **fail-closed refusal** live **[works today]**.
4. **Settings → Safety** → demonstrate **Protected fetch** (proxy + generic UA, with its
   honest "you must run and trust the proxy" note) and **Panic wipe** (with its honest SSD
   limit) — all toggles, no commands **[works today]**.
5. Session ends by disposing the VM; nothing was written outside the ephemeral dir.

**Gap:** a one-file offline installer for air-gapped rooms **[needs RM-08]**; the one-click
ephemeral launcher **[needs RM-09]**.
**Invariant check:** this scenario *is* the local-first / no-persistence test, end to end.
**Success metric:** 12 trainees finish with no calls beyond the fixture and no artifacts after
disposal.

## 6. Solo analyst on a low-spec laptop — the minimal install

**Persona & context.** A freelancer with a 4 GB-RAM laptop and patchy connectivity.

**Goal.** Useful monitoring of 20 sources without heavy dependencies.

**Workflow.**
1. At install, leave the **Analysis tools** and **LLM tools** boxes unticked — the installer
   does the rest; the app runs core-only **[works today]**.
2. The spine (collect, dedup, search, export) is fully usable; tabs that need an uninstalled
   extra say so plainly instead of breaking **[after audit fixes: TEST-06]**.
3. **Collect** scheduler on a 12 h interval; 20 sources ≈ minutes of polite fetching
   **[works today]**.
4. Later, re-run the installer and tick **LLM tools** to add a small model — or never; every
   LLM action degrades to an honest message, never a crash **[works today]**.

**Gap:** a "lite mode" toggle that hides unavailable tabs entirely **[needs RM-09]**.
**Invariant check:** graceful degradation is tested behavior; no simulated features.
**Success metric:** daily use under 300 MB app RAM with sub-second searches (≈130 MB DB at
50k articles after the audit fix).

## 7. Reproducibility / peer review — a defensible analysis

**Persona & context.** A media-studies researcher must make a "coverage volume differs by
political lean" finding reproducible for reviewers.

**Goal.** Real-method statistics, a re-verifiable data lineage, and an independent existence
proof.

**Workflow.**
1. Corpus assembled as in scenario 4; spectrum tags give the grouping variable
   **[works today]**.
2. **Insights → Statistics** → pick a test (t-test / ANOVA / confidence interval); each
   result card shows the method, statistic, p-value and n — real scipy, never a blended score
   **[works today, needs the analysis tools installed]**.
3. **Library → Export**, then **Evidence & custody → Anchor** the export's hash
   (OpenTimestamps "existed no later than T", or the offline local anchor book) **[works
   today, OTS needs the timestamping extra — an installer option]**.
4. Send reviewers the CSV + the evidence bundle; they verify integrity and provenance with the
   bundle alone — the **Help → Verify** page shows the steps **[works today]**.

**Gap:** a one-click "methods appendix" generator **[needs RM-07]**.
**Invariant check:** statistics are real methods or absent; lineage is cryptographic.
**Success metric:** a reviewer reproduces the numbers from the export alone.

## 8. Multi-source synthesis — markets × news comparison

**Persona & context.** A commodities-desk journalist asks whether cobalt-price moves track DRC
mining coverage.

**Goal.** A chart + honest correlation figure, plus the article set behind it.

**Workflow.**
1. **Markets → Data feeds → Import** the official cobalt CSV series (FRED/World Bank Pink
   Sheet) — values only from the official file, missing ones skipped, failures shown
   **[works today]**.
2. **Sources** → enable the commodity/metals outlets from the catalog; **Collect** them
   **[works today]**.
3. **Markets → Correlate** with the query `DRC AND (mine OR mining)` → a real coefficient +
   p-value + n, with the built-in "correlation ≠ causation, n is small" caveat **[works
   today, needs the analysis tools]**.
4. The inline price chart + matched article list → **Add to briefing → Export** **[works
   today]**.

**Gap:** multi-series overlays + a publishable chart export **[needs RM-15]**.
**Invariant check:** a price number is stored only from a verified extraction rule or an
official CSV — never a guessed selector.
**Success metric:** the published figure is regenerable from the export by a reader.

---

## From scenarios to Home-screen cards — "investigation recipes"

This is how the scenarios above stop being manuals and start being **one-click exercises the
app runs for you**, surfaced on the **Home** screen.

**The app already has a card engine — and it's the right shape.** The Home briefing is built
from **producers** (`src/briefing/producers.py`): small functions `producer(session) ->
list[Card]`, registered in `src/briefing/registry.py` ("adding a capability = registering one
producer"), rendered grouped by the **Investigate · Collect · Trust · System** buckets. A
`Card` (`src/briefing/card.py`) is deliberately constrained to **one measured signal + its
method + a caveat + evidence links back to the corpus + the sample size n** — and the code
*physically forbids* a blended "trust/quality score" field (`CardSchemaError`). About twenty
producers already ship (`rising_now`, `framing_split`, `record_reshaped`, `price_narrative`,
`law_change`, `model_legislation`, `story_lineage`, `coverage_advisor`, …).

**The proposal: each space-time scenario becomes a producer + a one-click recipe.** The ten
cards sketched in [`FUTURE_DEVELOPMENTS.md`](../FUTURE_DEVELOPMENTS.md) map onto this engine
directly — they are space-time *conditions* that, when met in the user's own corpus, raise a
Home card that opens the relevant tab pre-filtered. No new mental model for the user: it looks
exactly like the cards they already get.

| Scenario card | Becomes producer (fires when…) | Card shows (signal · evidence) | One-click recipe opens |
|---|---|---|---|
| The warnings existed | a hazards-layer event lands where the corpus has prior coverage | # prior geocoded articles at that place · the dated list | Temporal map at that place, rewound |
| Promises due | a *future* mentioned-date tag reaches today with no follow-up coverage | the original story + its promised date | Search, filtered to that topic + place |
| Disputed chronology | a near-dup cluster has conflicting confirmed dates/places | which sources disagree, with their dates | Search results cluster, dates pinned |
| News-desert atlas | a region's source/coverage count stays at ~0 over a window | coverage count vs. neighbours, the trend | World-coverage map at that region |
| Silent disasters | a GDACS/USGS event has no corpus coverage within N days | event severity (the source's) · "0 in your corpus" | Temporal map at the event cell |
| Law takes effect | a tracked regulation's effective-date arrives | the law + jurisdiction + its keywords | Law tab + Search in that jurisdiction |
| Story propagation | a cluster's reports cross (or fail to cross) a border over time | where/when each report published | Temporal map, story track overlaid |
| Edit-war seismograph | a geolocated spike coincides with a wiki revision burst | revision/revert counts in the window | Wikipedia tab on the tracked page |
| Supply-chain ripple | a price move coincides with coverage of chain places | coefficient · p-value · n (+ caveat) | Markets correlate + the place list |
| Election-window desk | during a tracked election period, per-region report density shifts | density by region-hour · the reports | Temporal map, election lens on |

**What it takes (one small, named increment).** The card engine is ready; the missing piece is
that a card today carries `evidence` links but not a structured *action*. Add an optional
`recipe` to `Card` — a `{tab, params}` deep-link (e.g. `{"tab":"timemap","place":[lat,lon],
"window":[t0,t1]}`) the Home UI renders as an **"Open this investigation"** button that loads
the tab pre-filtered. That's **RM-20** below: parameterised, one-click investigation recipes.
Everything else (producers, registry, buckets, pin/dismiss, evidence, the no-score guard) is
already in place.

**Honesty stays non-negotiable**, enforced by the same architecture:
- A recipe card is still **one measured signal + method + caveat + evidence + n** — the
  `CardSchemaError` guard means no scenario can smuggle in a composite "risk/credibility
  score". *Silent disasters* says "a source we watch didn't report it," never "nobody did."
- Cards are **dismissible** and **user-owned**; which space-time recipes are active is a
  Settings choice (off-loud, never surprising).
- A recipe only ever **pre-fills a query the user could have typed** — it automates the
  *gathering*, never the *judgement*. The user still reads the evidence and decides.

This is the throughline of the whole product: the scenarios show what an investigator wants to
do; the cards let the app do the legwork and hand back **signals with provenance**, on the
home screen, without anyone touching a terminal or a verdict button.

---

### Capability coverage map (scenarios × verified features)

| Verified capability (UI surface) | Scenarios |
|---|---|
| Ethical collect (Collect tab; robots fail-closed, SSRF-guarded, retrying) | 1 2 3 4 5 6 8 |
| Dedup (automatic) | 1 2 4 6 |
| Boolean search (Search tab) | 1 2 3 4 6 7 8 |
| Provenance + exports (Search/Library → Export) | 1 2 3 4 7 8 |
| Custody / evidence bundles / anchoring (Evidence & custody tab) | 1 2 3 7 |
| Local LLM (Summarize/Translate buttons) | 1 3 6 8 |
| Statistics / correlation (Insights · Markets) | 7 8 |
| Temporal map + mentioned-date tags | 1 2 + all 10 recipe cards |
| Scheduler · source groups · catalogs (Collect · Sources) | 2 4 5 6 8 |
| Safety suite (Settings → Safety) | 5 |
| Near-dup clusters · coordination (Search · Insights) | 2 |
| Markets / CSV price feeds (Markets tab) | 8 |
| **Home briefing cards (producer engine)** | the recipe layer for all 10 |
