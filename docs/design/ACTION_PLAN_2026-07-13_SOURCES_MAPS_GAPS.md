> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — the OSM boundary/gazetteer offline-preprocessing bridge for choropleth maps is confirmed STILL MISSING (only the download-manager pieces exist in `src/geo/`), as is keyword-skeleton fingerprint persistence (`src/analytics/skeleton.py` remains explicitly a pure in-memory core, deliberately dormant per its own docstring). Most of this plan's other rulings (source qualification, the discovery funnel core, tags) landed via separate later sessions — see CLAUDE.md. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Action plan — self-curating sources · maps/OSM · planned-but-partial remediation (2026-07-13)

**Status:** DESIGN / PLAN OF RECORD. Consolidates the 2026-07-13 planning dialogue
(source-quality → auto-audit → auto-discovery; OSM/maps leverage; the planned-but-partial
gap sweep). Companion to the two existing forward docs — do NOT duplicate them:
- `docs/design/PLANNING_2026-07-12_OPTIMIZATION_PROGRAM.md` + its `..._ACTION_PLAN_2026-07-13.md`
  (Conjunction Lens · Leads 2.0 · fingerprints · search · Tor · power · triage · AppVM) —
  **most of that program has since SHIPPED** (#648–#653: search-timing, power-profiles,
  conjunction-lens, leads-cores, keyword-fingerprints, tor-throughput; verify per the audit
  discipline, don't re-plan).
- `docs/design/STORAGE_5TB_PLAN.md` (storage at 5 TB).

**Binding honesty rails for everything below** (the project's spec): no composite scores; every
signal carries method + baseline + n; caveats visible by default; three provenance classes never
blended; degrade loudly; read-only/EXPORT-ONLY unless a network action passes the ONE consent;
the de-US-centring/source-diversity investment must be *protected*, never eroded.

---

## PART 1 — The self-curating sources system (the spine)

One loop: **discovery grows the source list; auditing prunes it.** Three phases; Phase 0 shipped.

### Phase 0 — Source & article quality DIAGNOSTIC — ✅ SHIPPED (#655–#657)
`src/analytics/source_quality.py` + `GET /api/diagnostics/source-quality` (a TEMPORARY/removable
button) produces the one ZIP: per-article keyword-stat outliers · a text sample from THREE labeled
selectors (`random_per_source` control + `keyword_outlier` + `source_fingerprint`) · per-source
keyword fingerprints · per-language health · newsletter text-gate
(`OO_QUALITY_INCLUDE_NEWSLETTER_TEXT`, default off). Matches the spec exactly.
**REMAINING (operator + analyst loop):** the maintainer runs it → sends the zip → analysis reads
`per_source_keywords` first (fastest triage), establishes the base rate from the random control,
checks the outlier detector's recall gap, and rolls up a per-source **exclude / optimize-extractor
/ keep** list. That list is the calibration input for Phase 1.

### Phase 1 — Standing automatic source AUDITOR (the quality gate) — NEXT, design-ready
The one-shot diagnostic generalized into a continuous, in-app auditor. **The reframe that keeps it
honest is load-bearing: it audits EXTRACTION VALIDITY / content-vs-non-content, NEVER editorial
merit.** "Disqualify" = *this source's scrapes are systematically not usable articles* (paywall
stubs, nav/index pages, consent walls, wrong-DOM extraction) — never "terse/unfamiliar prose," which
is legitimate variety and is exactly what a naive length/structure auditor would wrongly cut.
- **Criteria panel (all descriptive, corpus-relative per-language cohort, robust stats, n shown,
  NO absolute magic thresholds, NO blended score):** the four keyword ratios + top-keyword furniture
  share (reuse `source_quality.py` + `engine_report` `generic_terms` DF-ubiquity); article length
  (`article_length.py`, script-aware); sentence + paragraph structure (degenerate = nav/stub); link
  density; boilerplate signatures; within-source near-dup rate (`near_dup.py`); language consistency
  (`langdetect` vs asserted `Source.language`); scrape yield (storable-article vs paywall/error).
- **Status not verdict:** per-source status (healthy/watch/degraded/failing) with the *failing
  criteria + values*. **Precision-biased auto-action, recall-biased flag:** auto-DEMOTE
  (`enabled=false`, reversible, reason recorded) ONLY on high-confidence *extraction-failure*
  signatures + sustained low yield; everything softer is a human-review FLAG.
- **Guardrails:** maintainer allowlist (a trusted atypical source is never auto-cut); the
  auto-demote flag distribution surfaced BY REGION as a self-audit (never disproportionately cut an
  under-represented bucket); criteria + thresholds VISIBLE + configurable in Settings ("agreed"
  policy the human owns).
- **Runs** in the S2.2 idle-maintenance regime; count-based whole-corpus + bounded text sampling for
  the sentence/paragraph metrics; a rollup at 5 TB.
- **Sequence:** prove the criteria on the Phase-0 diagnostic results FIRST → ship the auditor
  flag-only (no auto-action) → add narrow auto-demote last, once the false-positive rate is measured.

### Phase 2 — Automatic source DISCOVERY funnel — design-ready; foundation partly built
Grow the source list from evidence the corpus already holds (citations beat search: self-curating,
primary-leaning). Three channels → one funnel → the Phase-1 quality gate.
- **Channels:** (a) article-citations — `src/discovery/cited_sources.py` ships: harvest cited
  domains, rank by INDEPENDENT citing sources (r-not-n), register DISABLED. (b) **Wikipedia
  references** — the flagship NEW channel: parse `References`/`{{cite web|url=}}` from the
  already-stored wiki text (zero-network), **across ALL 12 editions** (built-in geographic/language
  de-biasing — French Wikipedia cites French sources, etc.). (c) DDG topic discovery — the existing
  gated, off-by-default channel.
- **The promotion frontier (the "automatic + discreet" part, as a bounded funnel):** candidate
  (disabled, provenance) → **trial** (clears an independence threshold + robots + valid kind →
  auto-enable at LOW cadence) → **quality gate** (Phase-1 auditor: real articles → graduate; junk →
  auto-demote) → graduated. Humans set thresholds + audit; they don't hand-approve each domain.
- **Guardrails:** DIVERSITY-WEIGHTED promotion (a candidate filling an under-represented region/
  language promotes on a lower threshold; never worsen the balance); every scrape of a new source is
  a network action under the ONE consent + the bandwidth ladder (trial cadence bounds growth + the
  5 TB trajectory); a "discovered sources" AUDIT VIEW (provenance `discovered_via` · first-cited-by ·
  date · trial/graduated) + UNDO — discreet means low-friction, never hidden.
- **Border/citation-bias honesty:** any citation graph (Wikipedia's included) over-represents
  established/Western sources; the multi-edition harvest helps, but the diversity weighting is the
  enforcement.
- **The composition:** Phase 1 IS the quality gate that makes Phase 2 safe. Build Phase 1 first.

---

## PART 2 — OSM / maps leverage

**Verified current state:** OSM is *partly* leveraged, not unbuilt — `src/static/osmpbf.js` (a
node-tested pure-JS `.osm.pbf` parser) is wired into ooMap as an opt-in **bounded preview** overlay
(national rings that upgrade the coarse 110m polygons + microstates). But every map still draws its
base from bundled **Natural Earth**; OSM is an overlay on one map, not the base for all; and map
change-tracking is NOT built. Two very different ambitions, and the no-WebGL ruling decides which:
- **OSM as a better DATA SOURCE (recommended, tractable, fits no-WebGL):** preprocess OSM extracts
  OFFLINE into compact simplified geometry — finer admin-0 boundaries, **sub-national admin-1**
  polygons (the missing piece for region-level choropleth), a richer place gazetteer — and feed
  EVERY map surface. Fixes concrete Natural-Earth gaps (the ~75 microstate centroid-fallbacks, coarse
  borders, no sub-national). **The missing bridge:** an offline preprocessing job (OSM → boundaries/
  admin/places → simplified artifacts → replace/augment NE), run like the download-manager jobs.
- **OSM as LIVE street-level detail (ceilinged by the no-WebGL ruling):** the bounded preview is
  about as far as pure-JS goes; full detail wants vector tiles + GPU. Honest verdict: expensive, and
  arguably not what a journalism tool needs.
- **Border-honesty constraint (on-mission):** borders are political; OSM has conventions + disputed
  territories. Any OSM-boundary use must disclose "reflects OSM's convention as of `<date>`" and
  surface disputed borders as CONTESTED (multiple claims), never silently pick one. This is
  "name the shape, never prescribe" applied to cartography — and the seam into change-tracking.
- **Map change-tracking over time (later, depends on the bridge):** on-mission (reliable-memory /
  borders get redrawn / "history written by winners"); OSM is fully versioned (dated extracts), so
  dated boundary snapshots are feasible — the geographic analog of the Wikipedia/law versioning
  (a boundary is an Article; its OSM history is the linked audit layer).
- **OPEN RULING (maintainer):** (1) is the no-WebGL ruling firm? (it forecloses live detail, not the
  data-source path). (2) which ambition — data-source (recommended) vs live-detail? ROI note: this
  sits BEHIND P0 scale + the sources system; the highest-value achievable slice is the data-source
  path's sub-national boundaries + gazetteer.

---

## PART 3 — Planned-but-partial remediation (from the 2026-07-13 gap sweep)

Four tree-verified verifier sweeps found the "OSM pattern" (substrate shipped, leverage stalled) in
several places. Full evidence: the four agent reports (2026-07-13). Actionable tiers:

### 3A — Quick wins: surface an already-built backend (the highest ROI)
- **AI-derived keyword read-only lens** — table + endpoints ship; no reader UI (only a count tile).
  Render the labelled "AI-derived · unreliable" lens beside the trusted keywords. **S.**
- **Subjectivity / loaded-language engine** — `subjectivity.py` + endpoint + seed lexicons ship;
  ZERO frontend consumer. Render it on the manipulation cards. (Real license-clean lexicons =
  operator sourcing.) **M.**
- **El Niño / climate dataset** — bundled data + `/api/events/climate` ship; verification-pending +
  ZERO frontend consumer. Surface it (agenda banners) + operator clearnet verification. **M.**

### 3B — A decision, not a build
- **`external_sources` table** — model + migration + backup-carry ship; **0 rows, never written**;
  the citation consumer went another route. Decide: WIRE it (into the Phase-2 discovery funnel — its
  natural consumer) or DELETE it. Recommendation: fold into Phase 2, else remove the dead weight. **M.**

### 3C — The measure-gate linchpin (one operator action unblocks three)
Grade the IR gold set (~10 min): it unblocks **lemmatization** (`OO_FAMILY_LEMMA`, built, never
measured), the **BM25F default** (A/B harness built, no chosen weights), and the **static-embedding
pilot**. Highest leverage-per-effort in the whole tree. **Operator.**

### 3D — Dead-code + growing debt → an AppVM Gecko-verified cleanup pass
- Retired **temporal-map** cluster (~250 lines interleaved with LIVE shared helpers — the dangerous
  cut), dead **`#corpus-win`** modal DOM + boot listener, orphaned **`loadIndicesData`/
  `loadMarketData`**, orphaned **`#onboard`** i18n keys. All gated on browser verification → the
  AppVM is the venue. **M.**
- **Inline `on*=` handler retirement** — planned ~295, now ~500 (accreting); a11y/CSP. **L.**
- **i18n audit-chrome → 0** — ~170+ untranslatable static strings remain. **M.**

### 3E — Re-decide, don't let drift: the 3D keyword explorer (flagship)
Ruled "BUILD IT, do NOT defer the 3D," yet still the 3 toggled levels the plan said to REPLACE, and
"Enlarge" is a CSS toggle not `requestFullscreen`. Needs a conscious maintainer "still want the
flagship?" rather than silent drift. **L.**

### 3F — Consciously gated (inventory only — correctly parked, not problems)
D1/D2/D3 columnar (httpfs binaries) · storage Phase B/C · the LLM-expansion bundle (deep-model tier /
whole-corpus cited synthesis / corpus Q&A / per-surface lenses) · Wikipedia dumps→corpus +
whole-edition tracking (P0-gated) · Leads 2.0 Settings subtab · segmented Tor downloads / mirror
selection · entity→QID · eclipse canon + bundled religious calendars · sub-national boundaries (= the
Part-2 data-source path) · evidence-tier what's-missing/BH-FDR · clickable-keywords stats hover.

### 3G — Operator/networked (a run, not code)
Segmenter LIVE re-index over the existing corpus · DB-5 (name the ~120 GB, field export) · USGS
fetch · subjectivity lexicon sourcing · gold-set grading · El Niño verification.

### 3H — Stale-ledger drift (mark done; a reconciliation, not a build)
The ledger still lists as REMAINING several items that SINCE-SHIPPED: full-text dump search, weather
signal-keywords, deduced-events-in-agenda, ring-translation fallback, LLM langdetect, sentiment
surfacing, super-groups/ring-country UI. A periodic reconciliation should mark these.

---

## Consolidated sequencing (recommendation)

1. **Operator, now:** run the Phase-0 quality diagnostic → send the zip (calibrates Phase 1); grade
   the IR gold set (3C — unblocks three retrieval wins).
2. **Cheap high-value builds:** 3A surface-the-backend trio (AI lens · subjectivity · El Niño);
   3B `external_sources` decision.
3. **The sources spine:** Phase 1 standing auditor (flag-only first) → then Phase 2 discovery funnel
   (Wikipedia-references channel first, zero-network) → then narrow auto-action, gated on the
   measured false-positive rate.
4. **AppVM cleanup pass:** 3D dead-code + inline-handler + i18n tail (Gecko-verified deletions).
5. **Maps:** decide the Part-2 ruling; if data-source path → the offline preprocessing bridge +
   sub-national boundaries; change-tracking later.
6. **Gated tiers (3F) + operator tiers (3G)** proceed on their own ruling/field-data cadence.

## Open maintainer rulings this plan surfaces — ✅ ANSWERED 2026-07-13 (omnibus session)
- **Phase-1 auto-demote trigger set** — ✅ extraction-failure + sustained low yield ONLY; build the
  machinery DEFAULT-OFF, activation gated on Phase-0 zip calibration. FLAG-ONLY this session.
- **Phase-2 promotion automaticity** — ✅ full funnel (candidate→trial→graduated); trial auto-enable
  DEFAULT-OFF (enabling passes the ONE consent); diversity-weighted; quality-gated by Phase 1.
- **`external_sources`** — ✅ WIRE it (becomes the discovery funnel's resolution table). Dormancy ends.
- **Maps** — ✅ no-WebGL firm; data-source path (OSM→offline boundary/gazetteer artifacts for all
  maps). BUILD DEFERRED to its own session (ROADMAP row added); NOT built here.
- **3D keyword explorer** — ✅ formally DEPRIORITIZED (supersedes the 2026-06-16 "do NOT defer");
  the 3-level mind-map stays. Do NOT build.

## Omnibus execution status (2026-07-13, closeout)
Executed under full autonomy, DRAFT-PR-only (nothing auto-merges — the review is the gate). The
session prioritised the fully-VERIFIABLE backend spine + the mandated ledger work at full quality,
and parked the browser-UNVERIFIED frontend + the large Phase-2 backend HONESTLY (never a fabricated
pass). What shipped, what's parked:

**SHIPPED (draft PRs onto 0.2):**
- **Item 0 / Part-3H — ledger reconciliation + the 6 rulings** — ✅ MERGED (#662).
- **Item 2 / Part-1 Phase 1 — the standing source AUDITOR** — ✅ #663 (the board's own linchpin:
  "Phase 1 IS the quality gate that makes Phase 2 safe"). `src/analytics/source_audit.py` +
  `/api/diagnostics/source-audit{,-selftest}` + Settings buttons. FLAG-ONLY (Q2a): auto-demote
  machinery built but DEFAULT-OFF. Reuses the source_quality collectors (count-only, no content
  decrypt); status is the categorical rollup of a criteria LIST, never a score; soft/style-ambiguous
  signals never exceed `watch` (the reframe); a per-region self-audit + allowlist cap. Adversarial
  skeptic pre-push found + fixed a HIGH (the nearest-rank p90 tail trap — the worst nav sources
  escaped `failing` once EF sources were ≳10% of a cohort; fixed with an absolute EF-only floor,
  regression-pinned) + L3 sort. 18 tests, ruff/mypy/i18n clean.
- **Item 1 / Part-3A surfacings** — #664. (a) AI-keyword lens: VERIFIED ALREADY SHIPPED
  (`view_article` renders `ai_keyword` inline — the board's "zero UI" was stale; staleness-guard
  win). (b) subjectivity: SHIPPED a "Loaded language" reader tab (density + terms + honest gap),
  conservative + flagged, browser-unverified per Q6a. (c) El Niño banners: PARKED (below).

**PARKED — honest carry-over (precise specs in the closeout PR body + below):**
- **Item 1(c) El Niño agenda banners** — the bundled climate dataset is `verification_status=flagged`
  (pending the NOAA CPC ONI clearnet check), episodes are historical multi-month SPANS that don't fit
  the forward agenda, and span-banners aren't supported — prominently surfacing unverified data
  browser-unverified would breach "nothing presented as verified before it is." Build after the ONI
  check + span-banner support.
- **Item 3 / Part-3B + Phase 2 — the discovery funnel** — ✅ **TWO SLICES SHIPPED (2026-07-14, #667):**
  (1) the flagship **zero-network Wikipedia-references channel** (Q3a — parses the watched-page wikitext
  references across editions → DISABLED `SourceCandidate`s, editions = the diversity signal; negative-space
  lens pinned) + (2) **`external_sources` WIRED** (Q4a — `discovered_via` provenance, idempotent resolve on
  every discovery, dormancy ended; additive migration + self-heal, `test_no_model_drift` green). **REMAINING
  (the dedicated Phase-2 slice, parked honestly):** the **promotion frontier** (candidate → trial → graduated,
  trial auto-enable DEFAULT-OFF per Q3a, diversity-weighted, the Phase-1 auditor as the graduation gate — needs
  its own additive `SourceCandidate` state columns + the consent-gated trial-enable scheduler wiring) + a
  browser-verified **audit view + undo** + the citing-trail surface (S6.1b). A migration-heavy state machine
  whose trial-enable is a NETWORK action = a clean dedicated slice, not a rushed one.
- **Item 4 / Leads 2.0 + Conjunction Lens UI · Item 5 / small tails** — browser-UNVERIFIED frontend
  (Q6a). Parked with the cores already shipped (§1/§2 of the optimization program); each needs a
  browser-verified UI pass.
- **Item 6 / fingerprint persistence (§3 stretch)** — the skip-without-guilt dormant stretch; not built.

**MAINTAINER-VERIFY (could not confirm in-session):** the columnar "Columnar store" CI lane green at
the #661 tip (Part-3H asked to verify it; the real-httpfs round-trip is egress-blocked in-sandbox and
there is no `gh` here — check the lane on origin/0.2).
