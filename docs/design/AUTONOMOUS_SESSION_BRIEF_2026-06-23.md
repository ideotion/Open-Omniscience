# AUTONOMOUS SESSION BRIEF — 2026-06-23

**This document is the opening prompt for a fully autonomous build session.** It is the
consolidated, prioritised inventory of *everything that remains* in the 0.09 cycle toward
the V0.1‑alpha tag, synthesised from `CLAUDE.md` (the live ledger), the canonical gate
`docs/product/RELEASE_0.1_RC_GATE.md`, `docs/product/BACKLOG_GROUPED.md`,
`FUTURE_DEVELOPMENTS.md`, and the field‑test briefs of 2026‑06‑21/22. Every item says where
it stands, what "done" means, and which non‑negotiable constrains it. It does **not** restate
the non‑negotiables — it assumes them.

---

## 0. How to work (READ FIRST)

- **Read `CLAUDE.md` in full before anything.** It is the single ledger of every maintainer
  ruling and all non‑negotiables. Record every new ruling you derive HERE → into `CLAUDE.md`
  in the same turn (THE PROTOCOL). Update `docs/product/RELEASE_0.1_RC_GATE.md` rows you close.
- **Fully autonomous. Ask the maintainer NOTHING.** Make every decision yourself; pick the most
  honest, conservative default; record the choice. (2026‑06‑21 autonomy hardening.) The only
  carve‑out is a genuinely NEW ethics/irreversible surface not covered here or in the ledger.
- **Working mode:** one PR per slice, **small + additive**, **draft onto `0.09`**, CI subscribed.
  `git fetch origin 0.09` immediately before cutting each branch (0.09 goes stale within minutes).
  The maintainer merges everything; nothing self‑merges. If a session is pinned to ONE branch by
  the harness, stack commits on it (the PR becomes a batch — acceptable; the maintainer merges it).
  After a push that prints "[new branch]", the previous PR merged → open a NEW draft PR onto 0.09.
- **The non‑negotiables bind even under "ship it" pressure:** local‑first / loopback‑only; the
  airplane‑mode socket guard; robots fail‑closed; **no composite scores** (`assert_no_score_fields`);
  **caveats visible by default**; the ONE informed‑consent popup on every offline→online transition;
  honesty‑by‑construction (gaps = `None`, never zero; producers never averaged; deduced ≠ confirmed).
  A redesign may **never** drop a disclosure or a working tool — the **Desk lesson**: make it
  unreachable, gate it with an absorption test, never silently delete. Never fabricate data
  (FRED ids, checksums, dates, translations marked native‑reviewed).
- **Frontend is browser‑unverifiable here (fork‑3):** ship conservative + flagged
  "browser‑unverified, needs click‑through"; `node --check` every `<script>` touched; extend
  `tests/test_repo_invariants.py` (incl. `test_ui_invariants`); keep i18n at 100%
  (`scripts/i18n_report.py --min 100`). New chrome strings may be English‑fallback via `t()` and
  keyed later, but the gate stays green. After ANY frontend/wiring change run the FULL
  `test_repo_invariants` (a verbatim‑asserted line can break even when your feature's own test passes).
- **Verify with the real toolchain each commit:** `ruff check --select=F,B --extend-ignore=B008`,
  `mypy src/` (must stay ≤ baseline 127), `scripts/i18n_report.py --min 100`, `node --check`, the
  targeted tests + full `test_repo_invariants`. The sandbox is py3.11/core‑only for some extras;
  the full pytest + the 3‑OS matrix run in CI — subscribe and drive CI green.
- **Sequence by the tiers below. P0 (reliability/data‑integrity) ALWAYS first** — the app holds a
  real corpus the maintainer cares about; correctness outranks features.

### State as of this brief (what just shipped, so you don't redo it)
Branch `claude/trusting-maxwell-p7y2g8` / PR #445 (open, draft onto 0.09) carries: the
**Governments** tab (rename of World Law + per‑country World‑Bank data + a choropleth Map subtab +
the Law subtab); the **home‑card click diagnostic** (`GET /api/diagnostics/home-cards` — classifies
each Lead hard‑linked vs search‑fallback‑mismatch) + the briefing `CACHE_VERSION` bump (1→2) that
makes existing installs serve cards carrying `article_ids`; the **all‑diagnostics ZIP**
(`GET /api/diagnostics/all`) + the diagnostics buttons shed the "Download " prefix; the **i18n
keying** of Governments/Sources‑facets/strata strings; and the **flip‑card redesign** (front/back,
equal size, family‑themed via `--fam`, click‑to‑flip, caveat on the back, a themed "Open corpus ↗"
that opens the corpus in a NEW WINDOW via `window.open("/?corpus=…")` + a `_hydrateCardCorpus()` boot
deep‑link). All browser‑unverified per fork‑3 — a human click‑through across themes/breakpoints is owed.

---

## 1. THE RELEASE GATE (the path to the V0.1 tag — maintainer pivot, ruling #1)

`docs/product/RELEASE_0.1_RC_GATE.md` is the authoritative checklist; the tag is earned the day
**every RC‑BLOCKING row reads ✅** (ruling #2 HOLDS the 0.0.9→0.1 flip until then). The
release‑engineering set is the lead priority. The still‑open RC‑BLOCKING rows:

### 1.1 Backups & restore — the LARGE redesign (P0; folds in §1 gate rows + ruled‑but‑unbuilt pieces)
The maintainer's 2026‑06‑21/22 backups vision is only partly built. Bring it home, *reliably or
not at all* ("entirely reliable or it should not exist"):
- **File‑member backup for wiki dumps + OSM maps + Ollama models inside the additive restore.**
  The large‑data **folder backup** (`src/backup/folder_backup.py`) streams these AS‑IS to a
  server‑side directory and restores additively — DONE. The MISSING piece is the **additive‑restore
  MERGE that places FILE members** (bit‑identical dedup, never overwrite a differing local file) so
  the *encrypted oo‑backup‑2 artifact* path and the *selective backup/restore tickboxes* can carry
  them too (today wiki/maps/models tickboxes say "coming soon — folder backup"). Build the
  file‑member placement once; reuse `ollama_models.py`'s checksum‑dedup pattern.
- **Restore as a task‑manager JOB** (P0‑2: a 236 s synchronous preview/restore blocks the request).
  Make restore (and a large export) a pausable, visible job; surface progress both directions.
- **Unify the include/restore selection UI** (the "what to back up / what to restore" tickboxes are
  two parallel fieldsets; fold the separate `.oomodels` models backup into the one flow).
- **Encryption‑as‑an‑in‑flow EXPORT option** + **direct‑import‑with‑summary** (the maintainer's
  "import a backup and see what it added").
- **State‑into‑DB migrations (D1/D4, RC §1 SHOULD):** settings / annotations / event‑imports / agenda
  subscriptions → tables (today JSON files under `data_dir`), imported once, artifact member list
  updated, suite green.
- Acceptance: torture suite stays 10/10; a backup carrying a (stub) dump file restores it bit‑identically
  and additively; restore never overwrites a differing local file; the job is visible + pausable; i18n 100%.

### 1.2 Single‑writer gate — re‑verify under live parallel load (P0, standing keystone #1)
The 2026‑06‑22 audit concluded the 149 `database is locked` errors in the field bundle **predate** the
`do_orm_execute` gate fix (#384) and every audited write path is now gated + has `busy_timeout=30000`.
But the corpus runs **50 parallel collect workers** against one encrypted writer. **Re‑audit** that
EVERY write goes through the gate (ingest sub‑writes `index_article`/links/when‑where‑who, post‑pass
housekeeping: auto‑reindex top‑up, briefing refresh, auto‑on‑ingest AI, stats vintages, columnar
maintenance, FTS triggers, VACUUM/ANALYZE). Add an **ingest‑under‑parallel‑load** test that stores N
articles across many workers and asserts ZERO dropped keyword/link/date rows. Defence‑in‑depth already
shipped (the best‑effort sub‑writes retry via `run_write_with_retry`); confirm no path bypasses it.

### 1.3 Final claim‑sweep + docs↔app reciprocity (RC‑BLOCKING, §5)
- **USER_MANUAL** chapters: backup/restore + encryption; running‑over‑Tor; task‑manager + agenda;
  Governments; the FOOS naming note; the flip‑card Leads.
- **Two‑direction diff**: every feature sentence in README/USER_MANUAL/QUICKSTART/ETHICS resolves to a
  working surface, AND every shipped surface is documented (the 06‑audit method). ARCHITECTURE/DESIGN
  refreshed for backup‑v2 + SQLCipher + the data‑architecture seams + Governments.

### 1.4 Release mechanics (RC‑BLOCKING, §2) — do the plumbing now, flip last
- **Version flip 0.0.9→0.1**: the single‑source plumbing (`importlib.metadata`) is DONE and guarded.
  Execute the flip + the CHANGES.md 0.0.9→0.1 section + release notes **only when every RC‑BLOCKING row
  is ✅** (ruling #2). The FOOS suffix stays until a rename ruling.
- **`release.yml` end‑to‑end on a real tag** (held until the flip) — prove tag→sdist/wheel/SHA256SUMS/
  verify‑version/GitHub‑release.
- **Debian install path** verified end‑to‑end (win/mac are POST per ruling #5).
- **Single guarded socket factory (RC §1 SHOULD):** refactor the remaining allowed HTTP importers onto
  the ONE `guarded_session` factory (the socket‑importer ratchet pins the allowlist meanwhile).

### 1.5 The FINAL security review pass (RC‑BLOCKING, §4 — scheduled as the LAST batch before tagging)
A fresh full review over the RC diff with the 06‑audit method (agents + **hand‑verification of every
critical** — the false‑positive lesson). Plus the audit‑remediation tail: inline‑handler retirement
(§8 below), a11y batch, "stays on this machine" exact wording (ruling default applied — finalise).

---

## 2. THE FLAGSHIP UI SURFACES (RC‑BLOCKING centerpieces + the maintainer's recent asks)

### 2.1 Source‑tags everywhere + the world‑map "Sources by location" bubble layer (maintainer 2026‑06‑22, explored not built)
- **Filter sources by their tags throughout the app** — wherever sources appear as a list: the analysis/
  advanced search (`anParams` must send `tags`; the backend `_structured_filters` ALREADY filters
  `Source.tags` via `?tags=` — this is mostly frontend wiring + a multi‑select tag control), the Library
  tab, search results, etc. Reuse the Sources‑facets multi‑select grammar (`/api/sources/facets`).
- **World‑map "Sources by location" subtab**: circles sized ∝ source count per location, with a
  **country | IP** toggle (IP mode fills the large "no country" gap). Both data sources exist:
  `queries.source_country_counts` (per‑country) and `queries.server_locations` (per‑geolocated‑IP, with
  `distinct_sources` + lat/lon). Add `GET /api/insights/source-locations?mode=country|ip`; render via
  `ooMap` `overlayPoints` (size ∝ count). Honesty: "no country" bucketed + stated; IP geo carries the
  CDN‑edge/anycast/approximate caveats (already in `ip_geo`); no score.

### 2.2 The ONE corpora system / two‑windows consolidation (RC‑BLOCKING flagship)
- The `#an` analysis window is now the multi‑document spawned‑tab workspace and `#corpus-win` is retired
  (THEME‑3). REMAINING: the **remaining entry points** into the corpora object (commodity/date‑keyword
  pivots beyond what's wired); **surface the card CAVEAT inside the analysis window** the flip‑card "Open
  corpus" opens (today the caveat travels on the card back + the analysis has its own per‑subtab caveats —
  the 2026‑06‑23 flip nicety); TIME‑SCOPE on the non‑trend sub‑tabs; one‑click ethical ingestion of linked
  pages ("the sources' sources").

### 2.3 The 3D keyword explorer (maintainer FLAGSHIP, ruled 2026‑06‑16 — NOT yet built)
Hand‑rolled **canvas 2.5D / CSS‑3D, NO Three.js/WebGL** (ruling A), bundled loopback‑only. Unify
Keywords / Families / Super‑groups into ONE continuous layered hierarchy (super‑groups above families
above keywords; LOD drill, bounded — 60k+ keywords can't all render). Honest encodings, each a real
measured quantity with a stated method (size ∝ mention/spread count with n shown; trend = windowed
rise/fall + early‑corpus caveat + the n<10→bar rule; language spread = distinct languages; territory
spread = distinct countries) — **never a composite "importance score."** True Fullscreen API with a
visible exit; keep the tabular Families/Groups + word‑cloud as redundant a11y paths; the deterministic
mind‑map rules (outward, no cross‑tangle, no fabricated structure) carry into the layered form.

### 2.4 Home → dashboard / helicopter view (extends invariant #19)
Top **ooChart** graphs; a **synthesized‑Leads carousel** (pausable + keyboard a11y, never hides a caveat
behind rotation; "synthesized" = LOCAL analytic synthesis, NEVER LLM — zero‑network Home); **dynamic
data‑driven sections** (a commodity's price graph surfaces WHEN its keyword family trends); **most‑recent
articles by tag**. Everything redundant by design (#8) — deep‑links to its real tab; honest "top"
ordering (evidence tier + recency + corpus spread), never a hidden score; fail‑safe empty state.

### 2.5 Insights rework + the wider Trends redesign
Remove the Insights search bar (gated on the omnibar fully absorbing term‑exploration — the Desk lesson);
present the non‑searchable aggregates (the cards become canonical here; the three‑window Trends + top‑5
graphs slice shipped — finish the wider redesign).

### 2.6 Governments tab follow‑ups (this session's new tab)
A **Compare** subtab (multi‑country side‑by‑side); a **bundled offline indicator snapshot** (needs a
networked‑machine World‑Bank fetch — 403 in‑sandbox; fetch‑on‑demand works meanwhile); per‑country
flag/name polish; key the new English‑fallback strings ×12; **auto‑load** the standard indicators on a
freshness cadence in the scheduler markets pass (like commodity feeds), consented/airplane‑gated.

### 2.7 World map (ooMap) + markets + charts cleanups
- World map: **browser‑verified deletion‑cleanup** of the now‑unreachable temporal‑map functions;
  **embed ooMap on When/Where + Insights**; per‑slide perf on huge corpora (update only the signals layer).
- Markets: unify the indices CARDS (compact spark) onto the commodity `dashChartSvg`; a commodities **tag
  facet** for twin‑board symmetry; reclassify **S&P 500 as an INDEX** not a commodity; expand feeds (rare
  earths, LNG, cereals, sugar, gas…). Charts: commodity‑card enlarge → `ooChart` (the n<10→bar rule).
- The `openLinkPreview` ANYWHERE sweep (invariant #6 extension): reader source↗, search rows,
  markets/law/wiki tabs onto the same local‑preview path.

---

## 3. KEYWORD ENGINE / ANALYTICS DEPTH (the recurring optimisation loop)

- **Run on the live corpus** (existing buttons, not new code): the one‑click **"Clean up keywords
  (re‑index → prune)"**, then re‑measure via the keyword‑engine report's `mention_distribution` +
  `translation_coverage`. This is the maintainer's loop — they export the log, you read it.
- **Rings → ~2000, supergroups → ~200 (networked machine):** Wikidata is 403 in‑sandbox, so the generator
  (`scripts/generate_wikidata_rings.py --from-log LOG.json`) runs on a networked box; the cross‑language
  `ring_candidates` gap digest already ships in the keyword‑log zip to target it. You **vet** the output
  (≈6% first‑hit‑wrong — never auto‑trust), commit the vetted rings, re‑measure coverage. Consider an
  in‑app consented Wikidata importer (airplane‑gated, guarded factory, task‑manager job, candidates
  reviewed not auto‑merged).
- **Families↔rings↔supergroups translation binding in the UI** (Phase 3 frontend — original→translation
  through the family/group views; backend `equivalence.translate_term` exists).
- **no_stoplist Latin tail** (await the maintainer's exported per‑language keyword log); **CJK
  segmentation decision** for zh/ja (today honestly UNSEGMENTED + disclosed); date‑gap depth (CJK 年月日,
  the remaining date‑vocab langs).
- **Item AC keyword EXPLORER subtab:** the per‑keyword TAG add/remove UI (the S3a write endpoints exist;
  S3b shipped explore+hide+backfill); S1b stoplists → data files; S4 in‑app analyzer‑proposal review.
- **Sentiment:** surface the stored `sentiment_score`/`label` in the reader/cards/lists (columns are
  populated on re‑index; the UI still reads on‑demand framing); a multilingual path beyond English VADER
  (per‑language lexicons / a local model) — honest gaps for unscored languages, never a fabricated neutral.
- **Manipulation‑pattern cards** (ruling #13, design‑heavy, AI‑free is the asset): build the remaining six
  (headline‑body‑mismatch, outrage‑intensity, flood/bury, manufactured‑emergence, event‑timed‑op;
  astroturf/copypasta partly covered by echo_chamber). Each a new producer feeding an existing bucket,
  components never a blend (passes `assert_no_score_fields`), innocent‑explanation beside the pattern,
  "absence of a flag ≠ absence of manipulation." Spine in `docs/FUTURE_DEVELOPMENTS.md`.

---

## 4. AGENDA / CALENDARS / ASTRONOMY (RC‑BLOCKING content batch — "all and everything accessible")

- **Deduced events as FIRST‑CLASS agenda events** with ⊞ keyword links (parity with the moon/season
  glyph treatment); moons/seasons as first‑class events in day‑detail + all views; **El Niño** episodes
  as month‑span banners.
- **World calendars:** Islamic = computed tabular dates with the honest ±1‑day moon‑sighting caveat;
  Hindu/Buddhist = sourced published tables (NEVER a fabricated panchanga). **Religious‑calendar / eclipse‑
  canon dates: the maintainer will PROVIDE them (ruling #9) — never fabricate meanwhile; mark the TODO.**
- **Eclipse‑canon astronomy slice** (bundled public canon table + provenance + method/accuracy).
- **Play speeds 0.05–16× log‑stepped**; **preloaded worldwide bank holidays**.
- **Massively expand** the calendars (elections, summits, central banks, parliaments, courts, UN days,
  fiscal dates…), every entry sourced, movable dates marked, subscribe‑default off‑flood.
- **World‑law auto‑scrape (Governments→Law):** the per‑pass `auto_track_due` shipped; REMAINING = the
  per‑country legal‑source catalog for every UI language (a languages→countries map + curated sourced
  portals — large hand‑curation; today ~30 mostly anglophone/EU) + the Law subtab's content‑first revamp.

---

## 5. LLM / AI DEPTH (mostly POST; a few quick wins)

- **AI lens UI** beside the trusted keywords (backend `ai_keyword` ready) — render the "AI‑derived ·
  unreliable" layer in the analytics views, not only inline in the article.
- **AI‑tab Ollama BINARY installer** (Q7=B: download + verify checksum/signature + run the official
  per‑OS installer with a VISIBLE elevation step) — BLOCKED offline on real per‑OS checksums (networked
  machine; never fabricate them). The pull/remove/queue UI + active‑model picker already shipped.
- **Deep‑model tier + long‑context unlocks** (whole‑corpus CITED synthesis over full articles; corpus
  Q&A without RAG, refuse‑when‑absent; long single documents; cross‑language synthesis) — the LLM
  expansion design (stronger‑rig, POST). All keep: grounded+cited, no score/verdict, loopback, provenance,
  caveats visible, never auto‑fed into the trusted pipeline.
- **LLM‑PERCEPTION eval‑first harness** (who/where/when + sentiment‑vs‑VADER): build the difficulty‑tiered,
  phenomenon‑tagged, ×12‑language eval set FIRST (measure precision/recall/HALLUCINATION on the SHIPPED
  small model vs the rule‑based baseline) before the extractor — the larger track.
- Polish: a per‑article Summarize/Translate/extract on the analysis Articles list (the bulk path + reader
  tabs exist); the synthesis window chrome ×12.

---

## 6. WIKIPEDIA‑AS‑A‑SOURCE (RC‑BLOCKING living‑source design — partly built)

- **Full‑text SEARCH over downloaded dumps** + wikitext rendering + the **dumps→corpus ingestion path**
  (today dumps are files; one page reads locally; watched pages already enter the corpus). The
  omnibar already searches watched‑page CONTENT; dumps are the standing gap.
- **The dedicated tracked‑changes TAB** (the full‑attention GUI: scroll/discover/analyse edits through
  time; browser‑verified — its own slice). Per‑mention revid anchoring.
- **Drop the per‑edition "Estimate size" probe** → ONE consented "refresh exact sizes" that reads the
  dump date's `dumpstatus.json` (all editions in one call) through the guarded factory + the ONE consent.
- Superseding ruling (record‑only, build WHEN the time comes): once a language DUMP is downloaded the whole
  edition is tracked by default; per‑article tracking retires (scale honesty: enwiki ≈100k edits/day).

---

## 7. CONTINUOUS COLLECTION / TASK MANAGER / DOWNLOADS (RC‑BLOCKING, twice‑repeated)

- **Onboarding country/language emphasis picker** (folds into the guided wizard's consented first collect)
  + an **explainable schedule** (which language/tag is next and why). The strata preview now shows the
  actual language/tag buckets (#5 shipped) — extend to per‑country priority.
- **Task‑manager: History tab**; per‑country scrape priority; arbitration ask on the remaining starters.
  DELIBERATELY omitted unless the owners measure it: per‑job **rate/ETA + bandwidth cap** (needs
  owner‑measured bytes‑over‑time + a throttling backend — never a client‑side guess).
- Surface the client‑side bulk translate/summary QUEUE in the backend task manager (only the active run is
  in `/api/jobs` today) — but NOT via shadow state (the `tasks.py` no‑shadow‑state principle).
- Segmented HTTP‑Range over multiple Tor circuits for one big dump; dump mirror selection (the Tor
  speed levers — `SCRAPING_AUTOMATION_PLAN.md` Steps 3–4).

---

## 8. SECURITY / ETHICS / ACCESSIBILITY / i18n LONG TAIL

- **Inline‑handler retirement → CSP** (audit OO‑D12‑001): ~295 inline `on*=` handlers (229 onclick + 35
  onchange + 15 onkeydown + 14 oninput + 2 onmouse*) → `addEventListener` + a Content‑Security‑Policy.
  Large + browser‑verifiable‑only — do it in reviewable slices with a headless click‑through, never blind.
- **a11y batch**; the **custody/crypto UI "make it foolproof"** plain‑language simplification (#20
  remaining: plain controls + `#oo-tip` detail).
- **i18n long tail → ~0** (`--audit-chrome`, ~110–140 untranslatable as of 2026‑06‑20): key the
  recently‑shipped English‑fallback panels (folder backup/restore, model downloads, newsletter remove,
  offline‑map, synthesis window, the dynamic `loadWatches` rows, the new Governments/Sources/flip‑card
  strings already done this session); the tail is mostly inline‑`<a>`‑linked help paragraphs (need the
  link‑at‑end restructure) + a few deliberately‑emphasised `<strong>` privacy warnings + data/examples
  that stay literal. Plus the **server‑built Home‑card TITLE translation** design (titles carry data
  values — template‑based). Non‑en stays AI‑drafted + flagged for native review.

---

## 9. NETWORKED‑MACHINE / LIVE‑CORPUS TASKS (cannot be done in this sandbox)

Hand these to a networked run or the maintainer; never fabricate the artifacts:
- Wikidata **ring generation** (Wikidata 403 here) → vet + commit + re‑measure coverage.
- Replacement **FRED ids** for the dead GOLD/SILVER/SAWNWOOD commodity series (verify on a networked box;
  a wrong id fails loudly today).
- Exact **dump sizes** refresh; the **bundled offline indicator snapshot** (World Bank); the **IP‑geo DB**
  refresh.
- The **per‑OS httpfs/OpenSSL crypto‑extension packaging decision** — enables PERSISTED‑encrypted columnar
  analytics (today in‑memory only); follow `docs/maintenance/EXTERNAL_DEPENDENCIES.md`. The optional
  columnar acceleration of the inherent `co_rows` GROUP BY waits on this.
- The **100k‑article scale** empirical run (perf‑harness profile; measure EXPLAIN/timing on the real
  encrypted DB before adding any drift surface like a per‑day rollup).
- Run **orphan‑prune + tag‑backfill** on the live corpus and measure the keyword‑count reduction.

---

## 10. MAINTAINER‑RULING‑GATED (DO NOT build without a ruling — note + skip)

- App **self‑update**: build snapshot→verify→staged‑migrate→atomic‑swap→rollback MECHANICS only (default
  OFF); the 5 open Qs (channel, trust root, cadence, curl|bash‑vs‑git, mirror‑anchoring) + a signing key
  are a ruling — "use signing keys" is FUTURE.
- **Signing/notarization** decision; **win/mac CI lanes → required**; **religious‑calendar/eclipse dates**
  (maintainer provides); the poll‑analysis "ever say push poll / answer who's‑winning more directly" Qs.
- **Open Commons Mirror** = a SEPARATE sister project / new repo, only when this app is mature (V0.1+) —
  NOT this session's work. **Voice‑only mode**, in‑app **Tor/Stem** management, **two‑hop keyword graphs**,
  the autonomous **onboarding track**, the **event‑family merge/split UI**, **smart calendars**, the
  **OPT‑IN oo‑netcut OS layer** — all designed‑only, each needs its own design session.

---

## 11. SUGGESTED SEQUENCE (maintainer veto applies)

1. **P0 reliability:** re‑verify the writer gate under parallel load (§1.2) → backups redesign (§1.1,
   incl. restore‑as‑a‑job + file‑member placement) → state‑into‑DB (D1/D4).
2. **Release‑eng spine:** guarded‑socket‑factory refactor (§1.4) → docs↔app reciprocity + USER_MANUAL
   (§1.3). (Hold the version flip + release.yml + the final security pass for last.)
3. **Flagship UI:** source‑tags‑everywhere + the bubble map (§2.1, high value, mostly wiring) → the
   corpora‑system remaining + the caveat‑in‑analysis nicety (§2.2) → Home dashboard (§2.4) → the 3D
   keyword explorer (§2.3, the big one).
4. **Depth loops:** keyword‑engine live runs + rings (§3) → agenda content (§4) → Wikipedia dumps (§6).
5. **POST / gated:** LLM depth (§5), manipulation cards remainder (§3), the networked‑machine list (§9),
   the i18n tail + a11y + CSP (§8).
6. **LAST before the tag:** the final full security review (§1.5) + the docs reciprocity sweep + CHANGES →
   flip 0.0.9→0.1 → prove release.yml on the tag.

Estimated honestly from the demonstrated pace: the RC‑BLOCKING set is several dedicated sessions; "every
POST row" is materially more. The gate file is the truth; the tag is earned the day every RC‑BLOCKING row
reads ✅ — not before.
