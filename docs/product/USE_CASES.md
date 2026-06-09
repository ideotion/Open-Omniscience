# Use-case scenarios — Open Omniscience v0.0.7

Grounded in the audited reality of the system (see `docs/audit/`): every step is labelled
**[works today]** (verified capability), **[after audit fixes]** (works today *because of* the
v0.0.7 audit cycle), or **[needs RM-xx]** (requires a roadmap item from
[ROADMAP.md](ROADMAP.md)). No scenario relies on the quarantined, fabricated capabilities
(deepfake/propaganda/bot "detection") — where a persona wants those, the honest substitute or
the honest gap is stated.

Common preconditions for all scenarios: Linux with Python 3.13, `./install.sh` (or the
5-command dev path, verified in `docs/audit/05_DOCS_AND_RELEASE.md` §4); UI at
`http://127.0.0.1:8000`; optional Ollama for LLM steps.

---

## 1. Local investigative journalist — a cross-border corruption timeline

**Persona & context.** A reporter at a small Balkan outlet investigates a procurement scandal
spanning three countries and four languages. She cannot use cloud tools: her sources would be
exposed by a subpoena to a SaaS vendor.

**Goal.** A sourced, deduplicated timeline of every report touching the company "Adriatic
Logistics d.o.o.", with translations she can quote and provenance she can defend.

**Workflow.**
1. Add the regional outlets (Sources tab or `POST /api/sources/`); the packaged catalog
   already covers major outlets per country **[works today]**.
2. Ingest each outlet's RSS + bounded same-domain crawl (depth 2) — robots fail-closed,
   per-host politeness; transient fetch errors now retry with backoff **[after audit fixes:
   BUG-02]**.
3. Search `"Adriatic Logistics" AND (tender OR procurement OR ugovor)` — Boolean FTS5 with
   phrases and parentheses **[works today]**.
4. Per non-English article: `POST /api/llm/articles/{id}/translate` (local Ollama; result
   stored with model + prompt-version provenance) **[works today, needs Ollama]**.
5. Open the **Temporal map / article date-tags**: dates *mentioned in* the articles become
   confirmable timeline tags **[works today]**.
6. Build a **Briefing draft** (pin articles, add notes), export as Markdown; export the
   article set as CSV/JSON with URL + canonical URL + content hash + fetch time per row
   **[works today]**.
7. Optionally log the key articles into the **chain of custody** (signed, hash-chained) so
   she can later prove what she had and when **[works today]**.

**Data touched:** sources, articles (+FTS), article_analyses, article_mentioned_dates,
briefing draft, custody log.
**Output artifact:** Markdown timeline brief + CSV of evidence rows, e.g.
`title,url,canonical_url,hash,published_at,source,language` per line.
**Gap:** entity-aware search ("find the company under transliterated spellings") needs
semantic/NER search **[needs RM-05]**.
**Invariant check:** all fetches robots-checked; zero cloud calls (translation is local);
provenance on every row; operator identity never sent anywhere.
**Success metric:** timeline assembled offline in one afternoon; every claim in the published
story links to a hash-verifiable stored article.

## 2. Disinformation researcher — tracking a narrative's spread

**Persona & context.** An academic studying how a health-scare narrative propagates across
fringe and mainstream outlets.

**Goal.** Identify which outlets pushed near-identical copy, in what order, and export a
defensible dataset.

**Workflow.**
1. Seed a source set from the spectrum catalog (`configs/sources_spectrum.yml` ships
   lean-left → lean-right tags) + add fringe sites by domain **[works today]**.
2. Schedule incremental RSS pulls (Scheduler tab, e.g. every 6 h) **[works today]**.
3. Search the narrative's signature phrase; inspect **near-duplicate clusters** — MinHash/LSH,
   audited linear, honest caveat attached ("text overlap, not meaning") **[works today;
   scaling verified in the audit]**.
4. Check **coordination signals** (`src/signals/coordination.py`: same-story timing across
   source families) and **source-integrity prominence views** **[works today]**.
5. Order the cluster by `published_at` + confirmed mentioned-dates → propagation sequence
   **[works today]**.
6. Export cluster JSON; archive the run in the custody log for the paper's methods section
   **[works today]**.

**Honest gap:** *bot-network detection and "propaganda scoring" are not offered* — the old
implementations were quarantined as fabricated (hardcoded confidences). A graph artifact
(who-cites-whom network export) **[needs RM-15]**; real, measured stylometric/coordination
models **[needs RM-14]**.
**Invariant check:** spectrum tags are editorial metadata with stated sources, not algorithmic
verdicts; all signals carry caveats; everything local.
**Success metric:** a reproducible dataset (export + custody hashes) accepted by peer review.

## 3. Fact-checker — verifying a viral claim under deadline

**Persona & context.** A fact-checker gets a viral post claiming "EU bans wood stoves in 2027,
reported everywhere."

**Goal.** A structured verdict with citations, in under two hours.

**Workflow.**
1. `POST /api/ingest` the 5 URLs the viral post cites (single-URL ingest; anything
   robots-disallowed is refused and *says so* — that refusal is itself reportable)
   **[works today]**.
2. Ingest the actual EUR-Lex page via the **World Law** tracker (legal source catalog ships
   EUR-Lex); its baseline text + content hash are stored **[works today]**.
3. FTS search `("wood stove" OR "solid fuel") AND 2027` across the corpus; compare what the
   cited articles actually say (the **framing comparison** view contrasts coverage of the
   same story) **[works today, framing needs [analysis] extra]**.
4. LLM-summarize the legal document locally; the summary is stored as provenance-tracked
   *assistance*, never as the verdict **[works today, needs Ollama]**.
5. Image in the post? `POST /api/verify/image-metadata` — honest EXIF/metadata extraction
   ("this is metadata validation, **not** deepfake detection") **[works today]**.
6. Produce an **evidence bundle** (`POST /api/reports/evidence`) — Merkle-rooted, signed,
   independently verifiable with `scripts/verify_evidence.py` **[works today]**.

**Output artifact:** verdict note + evidence bundle JSON
(`{root, signature, items:[{url, hash, fetched_at}...]}`).
**Gap:** claim-to-source semantic matching **[needs RM-05]**; a verdict-template export
**[needs RM-07]**.
**Invariant check:** the LLM assists but the verdict cites stored, hashed documents; image
checks state their limits; everything offline except the initial fetches.
**Success metric:** published fact-check where every citation resolves to a hash-verified
stored object; a colleague can re-verify the bundle without trusting the tool.

## 4. Newsroom data desk — a maintained regional corpus

**Persona & context.** Two data journalists maintain a shared corpus of ~150 regional sources
feeding the newsroom's own analysis pipeline.

**Goal.** A self-refreshing, deduplicated, searchable corpus with clean exports into their
existing tooling.

**Workflow.**
1. Import the source list via CSV (`/api/catalog/import`, documented columns + downloadable
   template; bad rows reported, not dropped) **[works today]**.
2. Organize **source groups** (per beat); set per-group priorities and rate limits
   **[works today]**.
3. Scheduler in `rss` mode, hourly; per-source/host politeness is automatic; the dashboard's
   system-vitals shows live fetch activity **[works today]**.
4. Dedup is automatic (canonical URL + content hash, DB-enforced) **[works today]**.
5. Nightly `GET /api/articles/export?format=csv` (or JSON) into their pipeline; the export
   carries provenance columns **[works today]**.
6. Weekly `GET /api/database/backup` (consistent online snapshot) onto the newsroom NAS
   **[works today]**.

**Gap:** webhook/folder-drop integration instead of pull-export **[needs RM-06]**; a stable
versioned export schema contract **[needs RM-07]**.
**Invariant check:** the 224 MB/50k-article index removal (audit PERF-02) keeps the corpus
file small enough for NAS backups; dedup is a tested guarantee, not a hope.
**Success metric:** zero manual upkeep beyond source curation; downstream pipeline consumes
exports unchanged for months.

## 5. OSINT trainer — a workshop in an amnesic Qubes VM

**Persona & context.** A trainer teaches 12 journalists OSINT hygiene in disposable Qubes VMs;
nothing may persist after the session.

**Goal.** Full ingest→search→export loop inside a disposable VM, leaving no trace.

**Workflow.**
1. TemplateVM: `./install.sh --template`; AppVM: `./install.sh --appvm` (documented Qubes
   modes) **[works today]**.
2. Launch with `OO_EPHEMERAL=1` — RAM-only data dir, wiped on exit **[works today]**.
3. Each trainee ingests a workshop fixture site (local `python -m http.server` with a
   robots.txt — also demonstrates the fail-closed refusal when the trainer flips robots to
   `Disallow: /`) **[works today]**.
4. Demonstrate **protected fetch mode** (proxy routing + generic UA, with its honest "you
   must run and trust the proxy" limit) and **panic wipe** (with its honest SSD limit)
   **[works today]**.
5. End of session: VM disposal is the cleanup; nothing was written outside the ephemeral dir
   (audit-verified: the test suite itself runs hermetically via `OO_DATA_DIR`)
   **[works today]**.

**Gap:** a one-file offline installer (wheelhouse) for air-gapped classrooms
**[needs RM-08]**.
**Invariant check:** this scenario *is* the §0.5 local-first/no-persistence test, end to end.
**Success metric:** 12 trainees complete the loop with no network calls beyond the fixture
site and no artifacts after VM disposal.

## 6. Solo analyst on a low-spec laptop — the minimal install

**Persona & context.** A freelance analyst with a 4 GB-RAM laptop and intermittent
connectivity.

**Goal.** Useful monitoring of 20 sources without heavy dependencies.

**Workflow.**
1. `pip install -e .` core only — no numpy/scipy/torch; the spine (ingest, dedup, store,
   FTS search, export) is fully functional, and the analysis endpoints honestly report
   themselves disabled **[works today]**.
2. The test suite is green on this exact profile — the "extras are optional" contract is now
   CI-enforced **[after audit fixes: TEST-06]**.
3. Scheduler on a 12 h interval; 20 sources at default politeness ≈ minutes of fetch time
   **[works today]**.
4. Optional LLM: `gemma2:2b` (~1.6 GB) for summaries, or skip Ollama entirely — every LLM
   endpoint degrades to an honest 503, never a crash **[works today]**.
5. The −63% DB-size fix keeps a 50k-article corpus ≈ 130 MB **[after audit fixes: PERF-02]**.

**Gap:** none blocking; nicer would be a "lite mode" UI toggle hiding unavailable tabs
**[needs RM-09]**.
**Invariant check:** graceful degradation is tested behavior; no silent feature simulation.
**Success metric:** daily use under 300 MB RAM (app) with sub-second searches.

## 7. Reproducibility / peer review — a defensible analysis

**Persona & context.** A media-studies researcher must make her "coverage volume differs by
outlet political lean" finding reproducible for reviewers.

**Goal.** Statistics with real methods, a data lineage reviewers can re-verify, and an
independent existence proof of the dataset.

**Workflow.**
1. Corpus assembled as in scenario 4; spectrum tags give the grouping variable
   **[works today]**.
2. Run the **statistical endpoints** (salvaged, real scipy/statsmodels — the audited
   remnant of "Pillar 2"): `POST /api/analysis/t-test/independent`,
   `/api/analysis/anova/one-way`, `/api/analysis/confidence-interval/mean` — each response
   carries the method, statistic, p-value, n **[works today, needs [analysis] extra]**.
   Example: `{"groups": [[12,9,14...],[4,6,3...]], "equal_var": false}` →
   `{"test":"welch_t","t":3.41,"p":0.0021,"df":27.4,"n":[30,30]}`.
3. Custody-log the dataset export; **OpenTimestamps-anchor** the hash (Bitcoin-anchored
   "existed no later than T", no wallet needed) or keep the offline local anchor book
   **[works today, OTS needs the [timestamping] extra]**.
4. Ship reviewers: the CSV export + evidence bundle + `scripts/verify_evidence.py` — they
   verify integrity and provenance **without trusting the tool or needing the DB**
   **[works today]**.

**Gap:** a one-click "methods appendix" generator (query + parameters + versions)
**[needs RM-07]**.
**Invariant check:** statistics are real methods or absent (the project's core honesty rule);
lineage is cryptographic, not asserted.
**Success metric:** a reviewer reproduces the numbers from the export alone.

## 8. Multi-source synthesis — markets × news comparison report

**Persona & context.** A commodities-desk journalist asks whether cobalt-price moves track
DRC mining coverage.

**Goal.** A chart + correlation figure with honest statistics, and the article set behind it.

**Workflow.**
1. One-click import of official CSV price feeds (FRED carries the World Bank Pink Sheet /
   EIA series); values come only from the official files — missing values skipped, failures
   loud **[works today]**.
2. Ingest mining-news sources (catalog ships commodity/metals sources) **[works today]**.
3. `GET /api/commodities/COBALT/correlation?query=DRC AND (mine OR mining)` → real
   coefficient + p-value + n, with the built-in "correlation ≠ causation, n is small"
   caveat **[works today, needs [analysis] extra]**.
4. Inline price chart + the matched article list; pin both into a Briefing draft; export
   **[works today]**.

**Gap:** multi-series overlays and a publishable chart export **[needs RM-15]**; LLM
cross-model synthesis of the article set **[needs RM-16]**.
**Invariant check:** price numbers are never scraped from guessed selectors (a number is
stored only where a verified extraction rule or official CSV provides one).
**Success metric:** the published piece's figure is regenerable from the export by a reader.

---

### Capability coverage map (scenarios × verified features)

| Verified capability | Used by scenario |
|---|---|
| Ethical ingest (robots fail-closed, SSRF-guarded, rate-limited, retrying) | 1 2 3 4 5 6 8 |
| Dedup (hash + canonical URL, DB-enforced) | 1 2 4 6 |
| FTS5 Boolean search | 1 2 3 4 6 7 8 |
| Provenance columns + exports | 1 2 3 4 7 8 |
| Chain of custody / evidence bundles / OTS | 1 2 3 7 |
| Local LLM (summarize/translate, honest degradation) | 1 3 6 8 |
| Statistics (real scipy) / correlation | 7 8 |
| Temporal map + mentioned-date tags | 1 2 |
| Scheduler + source groups + catalogs | 2 4 5 6 8 |
| Safety suite (ephemeral, panic, protected fetch) | 5 |
| Near-dup clustering + coordination signals | 2 |
| Markets/CSV price feeds | 8 |
