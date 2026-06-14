# V0.1 Alpha — Field-Test Baseline (session 2026-06-14)

**Purpose.** This is the consolidated, easy-to-read baseline prompt distilled from the
maintainer's 2026-06-14 field-test session (installing/running 0.09 ≤ PR123). It gathers
**23 captured items** into **themes**, marks what is **decided/agreed** vs **open/doubtful**,
and ends with a **numbered question list** the maintainer will answer in one prompt. It is
meant to seed the next autonomous build session.

**How to use.** Treat each ✅ item as ready to plan/build (respecting the honesty + consent
non-negotiables in `CLAUDE.md`). Do **not** start ❓ items until the maintainer answers the
matching question; do **not** implement 🔒 items until the maintainer gives UI input.

**Detail & provenance.** Full per-item capture (verbatim quotes + analysis + actions) is in
`docs/product/field-test-2026-06-14/LEDGER_full.md`. Concept memos and seed data are in the
same folder. The parallel session's grouped backlog (for dedup) is
`parallel_backlog_reference.md`.

**Status legend.** ✅ DECIDED (we agree) · ❓ OPEN (maintainer doubt / needs a ruling — see
question #) · 🔒 GATED (needs maintainer UI input before implementation) ·
[PLANNED] already in the parallel backlog · [NEW] net-new this session.

---

## Quick index

| # | Item | Theme | Status |
|---|------|-------|--------|
| 1 | Installer: no DB-init / no passphrase prompt; auto-launch app | A Install | ✅ [PLANNED] |
| 2 | First-launch stepped wizard: language → **T&C** → passphrase (+ author T&C ×12) | A Install | ✅ (T&C content [NEW]) |
| 4 | Unlock screen canonical eye; + FYI-log micro-bugs (create-db 400, favicon 404) | A Install | ✅ [PLANNED] |
| 6 | ONE logo everywhere; app-icon PNG off-canon; add favicon | A Install | ✅ [NEW] |
| 15 | Cross-distro installer (Fedora failed; Debian-only messages) | A Install | ✅ dir [NEW] / ❓Q9 |
| 5 | App-quit UX: browser↔terminal lifecycle; no "are you sure" | A Install | ❓ Q1 [NEW] |
| 11 | Field-log analysis: polling storm, keyword_export ~5 min, import-all 14.6 min | B Perf | ✅ [PLANNED] |
| 9 | Federated journalist DB merge + auto tamper-evidence + durable format | C Database | ✅ core / ❓Q2,Q3,Q4 |
| 10 | Multi-attestation on dedup + changes-only + **Difference Explorer** | C Database | ✅ [NEW] |
| 17 | Relocatable/external data store + **Tails** packaging + Qubes | C Database | ✅ / ❓Q8 [NEW] |
| 20 | Don't BLOB dumps into the DB; artifact = the portable object | C Database | ✅ / ❓Q7 |
| 21 | Crash/hot-unplug resilience: salvage-import + fixity + synchronous=FULL | C Database | ✅ [NEW] |
| 8 | Transversal change-tracking / provenance / audit (own subtab, all data) | D Audit | ✅ concept / ❓Q5 |
| 13 | Bulk LLM translation → derived corpus + isolated sub-analytics | E Translation | ✅ [NEW] |
| 14 | Persist translations as **typed derivations** (cache; Item-8 substrate) | E Translation | ✅ [NEW] |
| 16 | Count ONE translation per article (model-scoped; never by size) | E Translation | ✅ [NEW] |
| 3 | Settings: Ollama/LLM panel + runtime update detection + latest-models | F LLM | ✅ [PLANNED]+nuances |
| 12 | Language-independent keyword analytics (2-layer; Wikidata Q-IDs) | G Keywords | ✅ dir / ❓Q6 |
| 18 | Reverse link: corpus keywords → related commodity surfaced | H Data domains | ✅ [NEW] |
| 19 | Energy = Intelligence: commodity expansion + energy theme + datacenter map | H Data domains | ✅ dir / ❓Q11 |
| 22 | OSM **PBF** geographic backbone + change-tracking (NOT MWM) | H Data domains | ✅ backbone [NEW] |
| 23 | Map-analytics UI: complete world-map revamp; reliability-over-speed | H Data domains | 🔒 Q12 |
| 7 | Seed default agenda with the Wikipedia recurring-holidays list | I Agenda | ✅ / ❓Q10 |

---

## Theme A — Install & First-Run UX

- **Item 1 ✅ [PLANNED, Group D].** Interactive install must NOT init the DB or prompt for a
  passphrase — defer the encryption choice to first launch (in-browser); keep the terminal
  prompt only as the headless/env fallback. **Auto-launch the app** when install completes.
- **Item 2 ✅ (wizard [PLANNED]; T&C [NEW]).** First launch is a stepped wizard:
  **(1) language → (2) Terms & Conditions accept → (3) passphrase** (in the chosen language).
  Author professional T&C ×12 locales: defers liability, states open-source, honestly
  discloses "entirely vibe-coded / code available but not yet human-reviewed," affirms the
  genuine intent to be honest & ethical.
- **Item 4 ✅ [PLANNED].** `/unlock` must use the canonical invariant-#5 eye (today a different
  double-arc eye); extend the #5 test to `unlock.html`. Also verify the FYI-log micro-bugs:
  `POST /api/system/create-db → 400` during passphrase creation; serve a favicon (404 today);
  soften the expected "Could not seed default sources" WARNING.
- **Item 6 ✅ [NEW concrete].** ONE canonical logo everywhere. `assets/icon.png` (the desktop
  launcher icon) is an off-canon globe+pupil variant — regenerate it from the canonical
  `assets/icon.svg`; add a favicon; fix unlock.html (Item 4); extend the #5 test to every
  surface.
- **Item 15 ✅ direction [NEW] / ❓Q9.** Make the installer cross-distro: detect the package
  manager (`/etc/os-release` + probe apt/dnf/zypper/pacman/apk), print correct per-distro
  install commands for git/python3.13/venv/pip, optional consented auto-install; add distro
  CI smoke lanes. The Python-3.13 availability wrinkle → **Q9**.
- **Item 5 ❓Q1 [NEW].** App-quit UX. Verified: no "are you sure" quit popup exists today
  (keep it that way). Open: should closing the browser stop the server, or keep it running for
  background collection? My recommendation: decouple + add an explicit frictionless Quit +
  make "still collecting in background" visible. **→ Q1.**

## Theme B — Performance & Reliability

- **Item 11 ✅ [PLANNED — corroborates Groups A/B, ELEVATE].** Field logs (PR≤110 build,
  2-core/6 GB, encrypted, over Tor): **polling storm** (`scheduler/activity` 2,519 req /
  288 CPU-s; vitals 3,536; etc.) → consolidate to one status poll/SSE; **`keyword_export`
  353→276 s (~5 min)** under collect contention → give exports a read snapshot; **market
  `import-all` 878 s (14.6 min)** from FRED-over-Tor timeouts + serial fetch → parallel +
  official endpoints. Calendar preflight confirms dead default feeds (→ drop them; supports
  Item 7's bundling).

## Theme C — Database: portability, federation, integrity, storage location

- **Item 9 ✅ core / ❓Q2,Q3,Q4.** Two journalists merge entire DBs without losing trust in
  their own, + automatic (ISO-style) tamper-evidence, + a durable format. Foundation already
  exists (oo-backup-2 signed artifact + additive merge + reliable-memory design). NEW framings:
  journalist-to-journalist federated exchange with signed per-contributor origin attribution
  (mine/theirs/both); fully automatic hash+signature verification with a plain verdict + peer
  keyring (TOFU) + continuous fixity; a durable, forward-compatible interchange format.
  Memo: `concept_federated_corpus_exchange.md`. **→ Q2 (schema reframe), Q3 (alpha scope),
  Q4 (keys UX).**
- **Item 10 ✅ [NEW].** On dedup, don't discard the duplicate — attach an **attestation**
  ("signed corpus X also held this exact content") = corroboration counter + tamper-evidence
  multiplier (with the anti-false-triangulation independence caveat). Store only changes on
  difference (content-addressing). A **Difference Explorer** tool (explore/analyze/act,
  additive-only) lives in Settings → Database management.
- **Item 17 ✅ / ❓Q8 [NEW].** Relocatable/external data store. Architecture already supports
  it (`data_dir()` + `OO_DATA_DIR`; everything lives under one root). Missing: a GUI location
  picker, a safe move tool, removable-media safety (UUID identity, loud-stop-on-missing,
  FAT32/exFAT warnings, LUKS recommendation). Serves the 20 GB-laptop user, **Tails** (install
  on Persistent Storage, data external; Tor-native fit; uv-Python for 3.13), and Qubes — one
  mechanism. **→ Q8 (keys with data vs host).**
- **Item 20 ✅ (my rec) / ❓Q7.** Don't put multi-GB Wikipedia dumps INSIDE the SQLCipher DB
  (2 GB BLOB cap, codec-drag, lost seek, hot/cold mixing, corruption blast radius). Structured
  data already IS in the one DB. Deliver "copy-paste + dedup-import everything" via the
  **oo-backup-2 artifact** (which already bundles dumps, checksum-deduped). **→ Q7 (confirm).**
- **Item 21 ✅ [NEW + PLANNED substrate].** Crash/hot-unplug resilience (first-class for Tails).
  WAL already makes a single unplug non-fatal. Add: `synchronous=FULL` on removable media; a
  **fixity audit** (per-record content_hash = the honest "verified"); **salvage-import** that
  skips + reports corrupted records and imports the intact ones; corrupt-boot recovery UX
  (never silent reinit); a "Safe eject/flush" control.

## Theme D — Change-tracking / Provenance / Audit (transversal)

- **Item 8 ✅ concept / ❓Q5.** Elevate change-tracking from Wikipedia-specific to a **complete
  transversal tool** anchored to ALL data, with its **own subtab** in the universal subtab
  system and a consistent anchored-field schema (initial-scrape date · verification date ·
  audit trail · change list · keyword-impact delta · baseline-vs-revised · version history).
  Likely needs a unified provenance/revision substrate (version blobs separate from metadata;
  content-hash dedup) and must stay off the critical write path (append-only; snapshot reads).
  Shares its substrate with Items 9/14/21/22. **→ Q5 (DB-architecture + alpha scope).**

## Theme E — Translation (LLM)

- **Item 13 ✅ [NEW].** Bulk-translate all foreign-language (≠ UI language) articles via the
  local LLM → a labeled, filterable **derived corpus** (distinct provenance class, original one
  click away). New window + Ollama-synced LLM tab (model picker, queue, measured ETA). Keep the
  **canonical keyword engine on original-language keywords**; the derived corpus gets an
  isolated, non-destructive sub-analytics, with each keyword tagged direct vs indirect(MT).
- **Item 14 ✅ [NEW].** Persist + cache translations as **typed derivations** (transform-
  derivation ≠ temporal-revision) attached to the original — NOT as articles. Content-addressed
  key (hash + lang + model + params) → never re-translate; stale-invalidate on content/model
  change. Reuses the Item-8 substrate. Guard: canonical queries never include derivations.
- **Item 16 ✅ [NEW].** The derived sub-analytics is **scoped to one model+version** → exactly
  one translation per article (no double-count). Default latest/user-pinned; **never** auto-pick
  by model size (recent small models beat older large ones). State the model in the header.

## Theme F — LLM / Ollama

- **Item 3 ✅ [PLANNED Group J + nuances].** Settings → LLM panel: install Ollama, list/refresh
  **latest models** (consented, honest freshness), pull/remove (checksum-verified, task-manager
  jobs, size/RAM/license never a score), + **Ollama runtime update detection** (distinct from
  app self-update). Prerequisite for Theme E (needs a usable model) — see Q13.

## Theme G — Keywords & cross-language analytics

- **Item 12 ✅ direction / ❓Q6.** Keywords are already language-qualified (good substrate; keep
  it). Add a **second layer** for language-independent analytics so a monolingual analyst sees
  across all languages: cross-language concept nodes (Wikidata Q-IDs/langlinks for entities;
  curated rings for terms; optional LLM/embeddings) — non-destructive, per-language counts
  visible, contributing languages disclosed. Honest limit: CJK extraction still absent. **→ Q6
  (route priority vs Theme E's translate→extract).**

## Theme H — Data domains: Commodities, Energy, Geographic/Maps

- **Item 18 ✅ [NEW].** Reverse of the ruled commodity→corpus link: when a corpus/article's
  keywords mention a tracked commodity, surface the **related commodity** (a "Related
  commodities" subtab with the price-curve × article-timeline overlay; commodity badges on the
  keyword tab). Build the curated, **multilingual** symbol↔keyword-family table (serves both
  directions). Co-occurrence ≠ causation; precise matching.
- **Item 19 ✅ direction / ❓Q11.** "Energy = intelligence." (1) Extend commodities massively via
  World Bank Pink Sheet (~70) + IMF SDMX (~60) + exchanges + Comtrade, through the official-
  statistics ingestion design (provenance/vintages/comparability). (2) A first-class **energy
  analytics** theme (prices/production/capacity/grid/carbon + the AI-energy nexus). (3) A global
  **datacenter map** (attributes tiered disclosed/estimated/deduced, never fabricated).
  Memo: `concept_energy_and_datacenters.md`. **→ Q11 (alpha vs V0.1+ scope).** NB: energy was a
  repeat that hadn't landed — now captured.
- **Item 22 ✅ backbone [NEW].** Offline OSM as a geographically-anchored analytics substrate +
  change-tracking. Course-correction: target **OSM PBF** extracts (Geofabrik), **NOT** Organic
  Maps' lossy MWM. Feeds the gazetteer + datacenter/energy seeding + place resolution; OSC-diff
  versioning via the Item-8 substrate enables "what got built where, when." Ingest ALL feature
  classes (no cap — reliability over speed, per Item 23); index the complete set.
- **Item 23 🔒 GATED (Q12).** The current world-map is "quite un-useful" → **complete revamp**.
  Reliability over speed, **no feature-class cap** (decided). The **UI needs maintainer input
  before implementation** — propositions A–G are in the ledger (revamped map tab with map
  search; conditional Map subtab in the analysis window; temporal×spatial fusion; feature
  inspection; geographic corpus entry; honesty layers; performance-honesty UI). **→ Q12.**

## Theme I — Agenda / Calendar content

- **Item 7 ✅ / ❓Q10 [PLANNED].** Seed the default agenda with the supplied Wikipedia
  recurring-holidays list (`seed_wikipedia_holidays.md`), each marked "sourced from Wikipedia,"
  shown for any year. Classify each by recurrence type (fixed / nth-weekday / span /
  **astronomical → reuse the shipped Meeus engine** / **movable → sourced tables, never
  fabricated**); never hardcode movable feasts to the example dates; strip POV wording; tradition
  tags become off-flood subscription groups. **→ Q10 (dubious/[citation-needed] entries).**

---

## Open questions (please answer in one prompt)

1. **App lifecycle (Item 5):** Closing the browser should keep the server running for
   background collection (my rec: decouple + explicit frictionless Quit + visible "still
   collecting" state) — agree? Or should closing the browser fully quit the app?
2. **Durable format reframe (Item 9):** Confirm — a literally frozen internal schema is
   impossible; we deliver a stable, **forward-compatible interchange format + content-addressed
   identity** (the oo-backup-2 lineage) instead. OK?
3. **Tamper-evidence v0.1 scope (Item 9):** Ship local fixity + signed-manifest auto-verify in
   the app for alpha; defer public-chain anchoring + witness cosigning to the Open Commons
   Mirror? Agree?
4. **Per-journalist keys (Item 9):** How much key/identity UX in alpha (generate / back-up /
   exchange / pin peers' keys) vs later? It's the hardest UX piece.
5. **Change-tracking scope (Item 8):** Alpha = the Wikipedia per-article tracked-changes tab
   built on a transversal-ready substrate, with the full transversal "Changes/Provenance"
   subtab as V0.1+? Or aim for the full transversal tool now? And: OK that it touches DB
   architecture (a unified provenance/revision substrate)?
6. **Cross-language keywords (Items 12/13):** Confirm both routes coexist — keep canonical
   per-language keywords; Route B (translate→extract, isolated sub-analytics) as the user-driven
   tool; Route A (Wikidata/equivalence overlay) as a non-destructive structural view. Which gets
   priority for alpha?
7. **"Everything in one DB file" (Item 20):** Confirm you accept keeping big dumps as external
   seekable files and using the **oo-backup-2 artifact** as the portable "copy/share everything"
   object (we do NOT BLOB dumps into the encrypted DB).
8. **External-drive keys (Item 17):** Should signing keys travel **with** the data (self-
   contained portable corpus) or stay on the **trusted host** (a stolen data drive lacks keys)?
9. **Cross-distro Python (Item 15):** OK to adopt a distro-agnostic Python (uv /
   python-build-standalone) so the installer + Tails stop depending on each distro shipping 3.13?
10. **Holiday seed dubious entries (Item 7):** Keep the `[citation needed]` / likely-vandalism
    entries with honest Wikipedia provenance + a verification flag, or exclude them? (e.g.
    "World Klassik Day", "International Pianist Day", "World Dates Day".)
11. **Energy/commodities/datacenter scope (Item 19):** Alpha = commodity breadth (World
    Bank/IMF) + an energy theme tab; datacenter map = V0.1+ flagship? Agree?
12. **Map-analytics UI (Item 23 — GATED):** Which UI propositions (A–G in the ledger) do you
    want, and any direction for the world-map revamp? (Backbone is agreed; the UI awaits this.)
13. **Translation sequencing (Items 13/3):** Confirm the Ollama installer (a usable, bigger
    model) precedes the bulk-translation feature, since local translation needs a capable model.

---

## Notes for the next autonomous session

- Honor all `CLAUDE.md` non-negotiables (local-first, consent-by-construction, no fabricated
  security/scores, honesty-by-layering, ×12 locales, SI units, co-occurrence ≠ causation).
- Several items share **one substrate** — design Items 8 (change-tracking), 9/10 (federation/
  fixity), 14 (translation derivations), 21 (fixity/salvage), 22 (OSM versioning) **together**
  (content-addressed provenance/version store).
- Dedup against `parallel_backlog_reference.md`: ~half these items are already tracked
  (Groups D/J/A/B/G); the net-new clusters are Translation (E), Database federation/portability
  (C), the transversal audit tool (D/Item 8), and the energy/geographic data domains (H).
- Do not start ❓ items before answers; do not implement 🔒 Item 23's UI before input.
