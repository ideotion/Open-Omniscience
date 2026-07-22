# ACTION PLAN 2026-07-22 — design-audit remediation

## 0. What this is

On 2026-07-22 a subagent fan-out (7 parallel forks, each reading its assigned
`docs/design/` files and verifying every "not built / remaining / pending" claim
directly against live `main` — grepping for the actual module, endpoint, or
migration, never trusting the doc's own self-description) audited **all 34
files** then present in `docs/design/`. This plan is the consolidated remediation
board from that audit: every genuinely open item, tagged by build-class, with a
recommended sequence, plus the documentation-hygiene work the audit itself made
necessary.

**Companion action already taken (same pass, before this plan was written):**
- 10 docs whose *entire* scope the audit confirmed fully executed were moved to
  `docs/archive/{design,session-briefs}/` (non-lossy `git mv`, index updated) —
  see those two archive READMEs for the list and the specific evidence.
- 22 docs that stay in `docs/design/` because they still describe real open work,
  but had at least one stale claim, got a short status-update banner at the top
  recording what the audit actually found, so the next reader isn't misled by an
  outdated self-description. This plan is the banners' cross-reference target.

**Ground truth hierarchy, unchanged:** `CLAUDE.md` is still the single binding
ledger. This plan does not restate its rulings; it organizes the *code and docs
work* those rulings (plus this audit's own findings) leave open, into an
executable sequence. When this plan and `CLAUDE.md` conflict, `CLAUDE.md` wins —
update this plan, not the other way around.

**Working mode for whoever executes this:** one PR per phase (or per slice within
a phase, for the larger phases), draft onto `main`, skeptics-before-push on
anything touching data safety or a shared connection (per the standing "adversarial
skeptic" convention — the negative-space lens especially for the DB-10 slice,
since it changes how every future corpus is created). Record each shipped slice as
a `docs/ledger/shipped.csv` row per the house append-rule; only add a
`SHIPPED_LOG.md` verbatim entry + a `CLAUDE.md` Lessons bullet if it carries a
reusable lesson. Re-verify staleness against a **freshly fetched** `origin/main`
before starting each phase — several 2026-07-18–21 sessions landed real work this
audit had to correct for, so don't assume this plan's "still missing" calls are
still accurate by the time you pick this up if significant time has passed.

---

## Phase 1 — DB-10 create-time seam (highest value, self-contained)

**Why first:** §1a (`auto_vacuum=INCREMENTAL`) was formally RULED 2026-07-17 and
§1b (`page_size=16384`) had its evidence delivered with "recommendation firm"
(PR #726) — but neither PRAGMA is actually set anywhere in the fresh-file
creation path. Every corpus created *right now*, including in any test fixture,
still gets the old un-reclaimable defaults. This is the single most concrete,
lowest-risk, highest-value gap the whole audit found.

- **1.1 [BUILDABLE-NOW]** In `src/database/connect.py`, the `if not p.exists() or
  p.stat().st_size == 0:` fresh-file branch (~line 86) gains `PRAGMA
  auto_vacuum=INCREMENTAL;` and `PRAGMA page_size=16384;` — set *before* the
  first table is created (SQLite requires `page_size`/`auto_vacuum` to be set
  before any content exists in the file; `pagesize_bench.py`'s rebuild-target
  code already proves the correct ordering — read it before writing this, don't
  rediscover it). Existing corpora are UNCHANGED (this only affects file
  creation) — the proven rebuild op (`sqlcipher_export`/`VACUUM INTO`, ~10–17
  s/GB) stays the maintainer's opt-in migration path for corpora already on disk,
  not built here.
- **1.2 [BUILDABLE-NOW]** Wire `incremental_vacuum(N)` into
  `src/scheduler/maintenance.py`'s idle-maintenance pass (DB10 §3) — bounded,
  throttled, run_now-honest, following the same idle-gated pattern
  `run_idle_maintenance` already uses for other housekeeping. A documented no-op
  on a pre-seam corpus (auto_vacuum still FULL/NONE) is correct and expected.
- **1.3 [BUILDABLE-NOW]** Add a size gate to the Settings "Full VACUUM" button
  (`vacuumNow()` in `app.js`) — DB10 §2. Today it runs unconditionally at any
  corpus size; a full VACUUM on a multi-GB corpus is the kind of unbounded
  synchronous operation the project's own async-def-freezes-the-server lesson
  warns against. Gate = a size threshold + an honest "this will take
  approximately N minutes" estimate from the pagesize-bench's own measured
  rebuild-seconds-per-GB, or a plain confirm-with-caveat if no estimate is cheap.
- **1.4 [MAINTAINER-RULING, do NOT skip]** Before merging 1.1, get an explicit
  "yes, wire it" from the maintainer — the PR #726 evidence delivery said
  "awaiting ratification," and `CLAUDE.md` still has no `RULED` bullet for §1b
  specifically (only §1a). Merging PR #726 was a data delivery, not itself a
  formal ruling. Ask, or at minimum flag the PR loudly and let the maintainer's
  merge stand as the ratification (matching how §1a was treated) — but say so
  explicitly in the PR description so it's an intentional reading, not an
  assumption slipped past review.
- **DoD:** `tests/test_repo_invariants.py` gains an assertion that a freshly
  created (non-fixture) DB reports `auto_vacuum=2` (incremental) and
  `page_size=16384` via `PRAGMA` read-back (the same `int()`-coercion lesson from
  the pagesize-bench work — some SQLCipher builds return PRAGMA values as text).
  Full suite green. Update this plan's own status once merged.

---

## Phase 2 — Documentation hygiene (carried forward from the 2026-07-17 plan)

The 2026-07-17 docs-review plan (`ACTION_PLAN_2026-07-17_DOCS_REVIEW.md`,
T1–T10) was itself barely executed — this audit found T1, T2, T3, T5, T6, and T8
all still open. T8 (archival) is **done as of this pass** (see §0 above); the
rest are carried forward here as the authoritative remaining scope for that plan
(its own banner now points here).

- **2.1 [BUILDABLE-NOW] T1 — `docs/README.md` index reconciliation.** The index
  is missing `docs/legal/`, `GOVERNANCE.md`, `CODE_OF_CONDUCT.md`,
  `QUARANTINE_ARCHIVE.md`, `docs/audit/` (both 2026-07 audits), `docs/process/`
  (`IMPROVEMENT_CYCLE.md`, `NAV_SOUP_QUARANTINE_STRATEGY_DRAFT.md`),
  `docs/maintenance/`, `docs/testing/`, `docs/research/`, `docs/i18n/`. Walk the
  live doc tree and reconcile.
- **2.2 [BUILDABLE-NOW] T2 — a repo-invariant test** guarding 2.1:
  `test_docs_index_covers_live_docs` — enumerate every top-level doc folder /
  first-launch-gated doc and assert `docs/README.md` mentions it. This is what
  stops the index drifting stale again (the whole reason this audit found so
  much drift is that nothing enforced it).
- **2.3 [BUILDABLE-NOW] T3 — `AUDIT_TRAIL.md` backfill.** The trail's last entry
  is from ~2026-06-14 (references PRs #150/#151) — it is missing the entire
  2026-07-13 cumulative-integrity audit AND the 2026-07-15 external audit, plus
  every audit/finding since. Append the missing entries (append-only, per the
  file's own convention — never rewrite history already there).
- **2.4 [BUILDABLE-NOW] T5 — banner the historical USER_MANUAL section.** The
  `### Recent additions (0.0.8 live-test cycle, June 2026)` section (~line 164)
  and the embedded `# What shipped in 0.0.8` roadmap-cycle section (~line 2280)
  read as current content with no indication they're historical. Add a short
  "this section is a historical snapshot from the 0.0.8 cycle; current behavior
  may have superseded it — see CLAUDE.md for the live ledger" banner above each.
- **2.5 [BUILDABLE-NOW] T6 — retire the QUICKSTART "Phases 2–5" heading.** `## D.
  Analysis capabilities (Phases 2–5)` (docs/QUICKSTART.md:187) uses a vocabulary
  ("Phases") the project stopped using long ago. The doc's *content* under that
  heading was independently verified current in the 2026-07-17 audit — only the
  heading needs updating (e.g. "## D. Analysis capabilities"), not a rewrite.
  Mirror the change to `docs/i18n/fr/QUICKSTART.md` per the doc's own reciprocity
  convention.
- **2.6 [BUILDABLE-NOW, small] Fix `ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md`'s
  bare `SCALE_ROADMAP.md` link** if it's still unqualified (flagged in the
  2026-07-17 review; verify it's actually broken before touching it — it may
  already be fine).
- **DoD:** `python scripts/i18n_report.py --min 100` unaffected (docs-only);
  the new invariant test (2.2) passes; a human skim of `docs/README.md` against
  `find docs -maxdepth 2 -type f` shows no orphaned top-level doc.

---

## Phase 3 — Law vertical remainder

Three of the eight brief slices (S1, S2, S4, S5) are done; S3, S6, S7 are
genuinely open (see the banner on
`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-17_LAW_VERTICAL.md` for the exact
evidence). This phase is that brief's remaining scope, re-sequenced by
buildability:

- **3.1 [BUILDABLE-NOW] S3 — add-a-document-by-URL.** A `POST /api/law/documents`
  (or similar) endpoint taking a URL + jurisdiction + title, running it through
  the SAME guarded-fetch → `LawDocument`/`LawRevision` → `index_article` pipeline
  `src/law/corpus.py` already wires for tracked documents. This closes the gap
  where the catalog can only grow via the maintainer editing YAML.
- **3.2 [BUILDABLE-NOW, needs a real fetch to verify] S6 — structured adapters,
  ONE first.** Per the brief's own sequencing, legislation.gov.uk (UK, clean
  XML) is the easiest real win — build ONE adapter (not all three) reusing the
  SDMX-parser precedent (a pure, network-free parser function + a thin guarded
  fetch wrapper, negative-space-tested). Do NOT attempt gesetze-im-internet or
  EUR-Lex ELI in the same slice — each is its own verify-the-real-endpoint-first
  task (the project's standing "never fabricate an endpoint" rule; a prior
  session's GDELT-endpoint mistake is the cautionary precedent).
- **3.3 [BUILDABLE-NOW, needs a real feed to verify] S7 — gazette-as-RSS.** At
  least one jurisdiction's official gazette (St Vincent's `legal.gov.vc` was
  identified during the 2026-07-17 acquisition batches as having a working
  Joomla RSS feed — verify it's still live) ingests through the existing RSS
  pipeline with `source_type=legal`, proving the pattern before generalizing.
- **3.4 [OPERATOR-GATED] Broaden 3.2/3.3 to more jurisdictions** once the first
  adapter/feed of each kind is proven — this is the scale-out step, sequenced
  after the pattern is validated once.
- **DoD:** each new adapter/feed has its own negative-space-tested parser (the
  S5.2/S5.1 skeptic lesson: verify the SHOULD-BE-EMPTY cases, not just the happy
  path) and a real fetch verified by whoever builds it (per the "every committed
  endpoint must be fetched by the executing session" rule from the original law
  brief).

---

## Phase 4 — Keyword-engine remainder

- **4.1 [BUILDABLE-NOW] Stoplists → data files** (KEYWORD_BASELINE_AND_MANAGEMENT
  S1b/Q3). Migrate `_EXTRA_STOPWORD_TEXT` (`src/analytics/extract.py:300`, a
  Python string blob) into `configs/keyword_baseline/<lang>.yml`-style data
  files, matching the pattern S2 already established for positive baseline tags.
  Byte-identical behavior is the acceptance bar (this is a representation
  change, not a content change) — pin that with a test.
- **4.2 [BUILDABLE-NOW] In-app one-click apply of analyzer proposals**
  (KEYWORD_BASELINE_AND_MANAGEMENT S4). The offline `analyze_keyword_log.py`
  script + the in-app `generic_terms` diagnostic already PROPOSE stopword/ring/
  mistag candidates; there's no in-app review-and-apply UI. Build a Settings
  panel (extending the existing Keywords explorer subtab, `#set-keywords`) that
  lists proposed candidates and lets the maintainer accept/reject per-item —
  NEVER auto-apply (the standing "propose, human judges" rule for this exact
  surface).
- **4.3 [OPERATOR-GATED, needs the graded gold set] P5.2 — static-embedding
  recall layer.** Zero code exists (model2vec/sqlite-vec/RRF). Per the strategy
  doc's own sequencing, this is gated on a real IR gold set existing (R6, still
  just a template) — do not start building this before that gate clears, or
  it'll be built against nothing to measure it with.
- **4.4 [BLOCKED, needs a networked machine + a licensing check] P6 —
  entity→QID linking (OpenTapioca).** Also zero code. Lower priority than 4.3;
  needs a license/bundling-size check on any OpenTapioca-adjacent index before
  committing to it.
- **DoD:** 4.1's byte-identity test; 4.2's Settings panel is browser-verify-
  gated per the standing Q6a convention (conservative + flagged, node-checked,
  no click-through claimed).

---

## Phase 5 — Source enrichment & diversification (operator-gated, but with a
buildable-now tooling gap)

- **5.1 [OPERATOR-GATED] Run Strategy 4's full LLM batch-enrichment** over the
  ~2,900 residual under-enriched sources (only a 12-source pilot has run). This
  needs a local Ollama rig, same chassis as the keyword-triage runs (Phase 8
  below) — consider running them in the same operator session.
- **5.2 [OPERATOR-GATED] Run the source-diversification brief's dedicated
  14-cluster live-network pass** — needs a networked Claude Code CLI session per
  the brief's own Part-0 preflight. English-source share (68.8% as of this
  audit) has drifted slightly *down* from the brief's 73% baseline already, but
  incidentally (from unrelated law-catalog batches), so the dedicated run is
  still fully un-started.
- **5.3 [BUILDABLE-NOW, small] Refresh both docs' numbers** after 5.1/5.2 run —
  the banners added in this pass record a snapshot (2026-07-22); update them (or
  better, remove the banner and let the doc's own self-tracking take over, per
  SOURCE_METADATA_ENRICHMENT_STRATEGY.md's existing convention) once real
  progress lands.

---

## Phase 6 — OSM/maps preprocessing bridge

- **6.1 [BUILDABLE-NOW, offline-preprocessable] Build the OSM boundary/gazetteer
  offline-preprocessing pipeline** (`ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md`'s
  ruled Part-1 data-source path — no-WebGL stands, per the 2026-07-13 ruling).
  Only `src/geo/osm_downloads.py`/`osm_regions.py` (the download manager) exist;
  there's no admin-1/boundary preprocessing turning a downloaded OSM extract
  into the choropleth-ready artifact the world map needs. This can be built and
  tested against a small downloaded region WITHOUT needing the full planet.
- **DoD:** a fixture-tested pure preprocessing function + the offline artifact
  format documented; wiring into the existing world-map choropleth is a
  follow-up slice, not required for this phase's DoD.

---

## Phase 7 — Keyword-skeleton fingerprint persistence

- **7.1 [BUILDABLE-NOW, but sequence AFTER Phase 4/8's keyword cleanup]**
  Persist `src/analytics/skeleton.py`'s pure in-memory fingerprint core: a
  migration adding whatever table the design calls for, plus wiring the live
  `skeleton_echo` producer to actually run. The doc's own docstring says this
  was deliberately deferred as a "skip without guilt" stretch — it's fine to
  leave it there if this plan's other phases are prioritized first, but it's no
  longer blocked on anything technical.

---

## Phase 8 — LLM triage/tag real runs + verification (operator-gated)

- **8.1 [OPERATOR-GATED]** The wiring (S1/S2 of
  `AUTONOMOUS_SESSION_BRIEF_2026-07-20_LLM_TRIAGE_TAG_RUNS.md`) is done — what's
  missing is the actual run on a real Ollama rig plus the Claude-side
  verification chain (§4 of that brief: canary integrity check, a stratified
  re-judgement sample weighted toward non-English, rejection/timing sanity, a
  draft PR built only from surviving verdicts). Combine with 5.1's source
  enrichment batch if run on the same machine.

---

## Phase 9 — Field-diagnostics findings (#728)

- **9.1 [BUILDABLE-NOW]** Fix the concrete, named bug: `rising_now`'s `Card(...)`
  call (`src/briefing/producers.py`, around line 230 per this audit) still
  doesn't pass `article_ids=` — the exact-set-seeding convention every other
  Home Lead card uses. Small, self-contained, matches the pattern already used
  for the other producers this bug class was fixed on (2026-06-16).
- **9.2 [BUILDABLE-NOW, investigation first]** The slow map-coverage endpoint
  (`src/api/insights.py:1161` per the finding) — profile it for real before
  assuming the fix; it may be a missing index rather than a structural issue.
- **9.3 [NEEDS THE RAW LOG, low priority]** The unexplained 2026-07-11 stall
  cluster and the 5 sources at 100% outlier rate — both need the raw diagnostics
  JSON (already delivered in PR #728) re-examined; low urgency, no code
  prerequisite.

---

## Phase 10 — Observatory frontend (browser-verify-gated by design)

- **10.1 [BROWSER-GATED, do not start without a real click-through plan]** The
  `ooSky` canvas renderer + its dedicated tab. The design doc is explicit that
  this is deliberately sequenced behind a maintainer browser click-through
  ("NOT conservative-flaggable") — respect that; don't build it
  conservative-and-flagged like other frontend work, build it only once a real
  browser session (the AppVM runner, R3, or a manual click-through) is actually
  available to validate against.

---

## Phase 11 — V1_PATHWAY rulings and verticals (mostly maintainer-gated)

- **11.1 [MAINTAINER-RULING]** V1-2 through V1-9 remain open decisions
  (user-supplied-API-keys policy, restrictive-license policy, PubMed
  bulk-vs-API, win/mac-at-1.0, KPI bars, the storage-§8 rulings — NOTE: §1a/§1b
  of THAT set is Phase 1 above, already actionable — elections-required-for-1.0,
  the Wikipedia edition-count bar). These need explicit maintainer answers, not
  code; batch them into one AskUserQuestion-style round when the maintainer has
  time, rather than trickling single questions.
- **11.2 [BLOCKED, large, needs its own dedicated session per vertical]** None of
  the five new verticals (patents, PubMed, a distinct climate/environment
  vertical, war/defense, elections) have any ingestion code yet. Each should
  follow the MANDATORY vertical pattern already proven by the law vertical
  (dated catalog → guarded fetch → pure parser with a negative-space skeptic →
  vintaged store → the Article/StatFigure/Agenda rails → a distinct provenance
  class → visible caveats → a per-vertical freshness diagnostic → ledger). Do
  not start any of these without an explicit maintainer go per V1-8 (elections)
  and the general "is 1.0 gated on this" sequencing question in 11.1.
- **11.3 [OPERATOR-GATED] R3 — stand up the `ui_walk` AppVM runner** for real (a
  real headless browser connection, not scaffolding). This unblocks Phase 10 and
  every other "browser-unverified, needs click-through" backlog item across the
  whole project — probably the single highest-leverage item in this entire
  plan if the maintainer can provide the AppVM environment, since it converts
  an entire *class* of disclosed-but-unverified frontend work into verified
  work.
- **11.4 [OPERATOR-GATED] R6 — grade a real IR gold set** (only the template
  exists). This unblocks 4.3 (P5.2 embeddings), the BM25F-default decision, and
  the lemma-quality measurement loop simultaneously — worth prioritizing once a
  maintainer session has 15–20 minutes free, per the gold-set-grading-flywheel
  design (the whole point of that design was to make this a small recurring
  task, not a heroic one-time session).

---

## Sequencing summary

| Phase | Tag | Depends on | Recommended order |
|---|---|---|---|
| 1 (DB-10 seam) | Buildable-now + 1 ruling ask | — | 1st — highest value, self-contained |
| 2 (docs hygiene) | Buildable-now | — | 2nd — cheap, unblocks nothing else but is overdue |
| 9 (field-diagnostics) | Buildable-now | — | 3rd — small, already-designed fixes |
| 3 (law vertical) | Buildable-now (3.1–3.3) | — | 4th |
| 4.1/4.2 (keyword baseline) | Buildable-now | — | 5th |
| 6 (OSM preprocessing) | Buildable-now | — | 6th, can run in parallel with 3–5 |
| 7 (skeleton persistence) | Buildable-now | after 4/8 cleanup | 7th |
| 11.3 (ui_walk runner) | Operator-gated | maintainer's AppVM | ASAP once available — unblocks 10 + the whole browser-verify backlog |
| 11.4 (gold set) | Operator-gated | maintainer's 15 min | ASAP once available — unblocks 4.3 + BM25F + lemma measurement |
| 5 (source enrichment/diversification) | Operator-gated | networked machine/Ollama rig | whenever available |
| 8 (LLM triage/tag runs) | Operator-gated | same Ollama rig as 5.1 | combine with 5.1 |
| 10 (Observatory frontend) | Browser-gated | 11.3 | after 11.3 |
| 4.3/4.4 (embeddings/entity-QID) | Operator-gated | 11.4 | after 11.4 |
| 11.1/11.2 (V1 rulings/verticals) | Maintainer-gated / large | maintainer time | ongoing, one vertical at a time |
