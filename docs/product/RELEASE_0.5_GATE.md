# Release gate — v0.5.0 · The investigator's desk

**Status: OPEN — written 2026-09-15 from the answered roadmap sheet, ahead of the `0.4` tag.** This is the
checkable inventory for closing the `0.5` cycle. It exists now because the maintainer ruled (Q112 = a, Q1204 =
a) that the gate files for 0.4–0.9 are written in one session from the answered sheet
([`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
indexed in [`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md)), every row citing the question ID it
implements, so that nothing is restated when the release starts.

**What is ruled here and what is not.** The theme is the approved V1 train's (`V1_PATHWAY_2026-07-14.md` §3,
ruled 2026-09-07); its contents were amended by **Q105 = a** — the advanced search, the Place entity and the
OSM artifacts (pulled forward from 0.8) join the approved desk. A row whose origin is a question ID is
**ruled**. A sentence marked *proposed placement* is the planning session's sequencing of a ruling the sheet
did not date (Q306's storage step, Q1102's migration, Q821's streets), and *design note* marks a build-level
suggestion — neither binds the maintainer, and declining one belongs in §3 with its reason. The ⛔ questions
left blank — **Q823 (ODbL)** and **Q1009 (the storage round-2 rows 3–6)** — are named on the rows they touch
and never assumed. **No target date** (Q110 = c); operator time is unbounded (Q115 = c).

**How a row closes** (inherited from the `0.3` and `0.4` gates, unchanged): only when there is a **named
artifact** — a report file, a merged PR, a measured number, a recorded click-through — that a later reader can
re-open and check. "It was built" is not closure; *merged ≠ green ≠ verified*. The verification bar is the
one ruled for 0.4 (Q1128 = a): Chromium in the sandbox plus the maintainer's click-through = verified; Gecko
best-effort. A row that cannot be measured in the sandbox says `not-measurable-here` and names the operator
step.

**Entry.** `v0.4.0` tagged (`RELEASE_0.4_GATE.md` rows A–E, G–V closed). Two 0.4 rows are hard preconditions
here by ruling: row K (the backup-format bump, exercised on a real restore) precedes row B below (Q301 = c),
and row O (the substrate) precedes rows D and F.

---

## 1. The board

| # | Row | Owner | Origin | Status |
|---|---|---|---|---|
| A | The advanced search — one UI for every search need | session | ruled (R11; Q505, Q601–Q618) · brief `S05-01` | **OPEN** |
| B | ISO 3166-1 alpha-3, step 2: the store, the configs, the payload flip | session + operator (a real restore) | ruled (Q301 ⛔ = c step 2, Q304, Q305, Q313; Q306 storage step *proposed placement*) · `S05-02` | **OPEN** — needs 0.4 row K exercised |
| C | The entity spine: QIDs, Wikidata items, the Place entity, the gazetteer artifacts | session + operator (artifact build) | ruled (Q415, Q724, Q805, Q818, Q827) · `S05-03` | **OPEN** |
| D | The OSM lane seeded: the first country's places, roads and buildings; the tag-completeness view | session + operator (extract + planet history download) | ruled (R16; Q106, Q806–Q811, Q813, Q814, Q815 · 1, Q817, Q819 · 3, Q820, Q822, Q824, Q825, Q828, Q1008) · `S05-04` | **OPEN** — ODbL (Q823 ⛔) PENDING |
| E | OSM-derived admin-0 / admin-1 artifacts keyed ISO 3166-2, on all five surfaces | session + operator (artifact build) | ruled (Q314, Q816, Q802 second half); Q804 an ASSUMPTION at its default · `S05-05` | **OPEN** |
| F | Wikipedia: the WARM tier and the `allpages` tail walk under budget | session + operator (the run) | ruled (R12; Q701 ⛔ = c, Q707, Q712 · 4–5, Q722 = b, Q727) · `S05-06` | **OPEN** — the Phase-C store (Q1009 ⛔) PENDING |
| G | Laws: the evolution surface — versions, the reader, point-in-time search, analytics 3–5 | session | ruled (R14; Q107, Q905, Q908, Q914 · 3–5, Q916, Q918, Q920) · `S05-07` | **OPEN** |
| H | The AI-coordinator translation sweep; titles, summaries and on-demand full text; the model bench | session | ruled (Q405, Q513 = b + c, Q1142, Q1143, Q1144) · `S05-08` | **OPEN** |
| I | The UI shell: "rings, not gates", the first-run default, the inline-handler retirement + CSP, the theme cull | session | ruled (Q1120, Q1121, Q1123, Q1127) · `S05-09` | **OPEN** |
| J | A source is keyed on its FEED — the migration and its data-safety review | session + operator (a real restore) | ruled (Q1102 ⛔ = b); *proposed placement* 0.5 · `S05-10` | **OPEN** |
| K | The approved desk: the claim workspace A1, the Conjunction Lens across verticals, the onboarding tour, signed-evidence export polish | session | carried from the V1 train (ruled 2026-09-07), kept by Q105 = a · `S05-11` | **OPEN** |

**The exit.** `v0.5.0` is tagged when rows A–K are CLOSED on named artifacts, the three i18n gates and the
whole-tree guards are green on the tagged tree, and the release notes carry the no-telemetry re-check (Q111).
Row D closes with OSM rows INSIDE the machine only: until Q823 ⛔ is ruled, no OSM-derived row enters an export,
a bulletin or an evidence ZIP (today's state, not a decision). Row F closes at the budgeted depth the store
allows; if Q1009 ⛔ is still blank, the walk runs under the existing store and the row says how far it got.

---

## 2. The rows

### Row A — The advanced search · ruled (R11; Q505, Q601–Q618) · OPEN

**What it must demonstrate.** The v1 filter list confirmed (Q601: language multi-select over asserted **and**
detected, labelled · sources facet with counts · source tags · provenance / channel · source country + region
(alpha-3) · published range via `ooTimeScope` with presets + a timescale selector · a separate "collected
between" · word-count bands, script-aware · sentiment with the English-only caveat visible · "mentions a date
in range" · include-quarantined, advanced only · keyword / concept, ring or literal · sort); the builder — rows
of `field · operator · value` rendered as chips above the query box, two-way with the editable box (Q602);
the grammar extension — prefix `word*`, `NEAR(a b, N)`, column filters `title:`, `author:` — behind an explicit
token class so `_quote`'s injection safety stays (Q603); English operator tokens canonical, the builder as the
localised layer (Q604); **typo tolerance as a SymSpell-shaped precomputed table built by a background job,
offering "did you mean", never silently rewriting** (Q605 = b — the 2026-09-09 "RULING NEEDED" docket entry,
now ruled); saved searches as watches with threshold zero (Q606); `/api/articles/export` takes the full
parameter set (Q607); the omnibar's Enter always opens the analysis window (Q608); `ooTimeScope` becomes the
one begin / end / scale component for Advanced, Markets and Insights (Q609); folding by default **with an
on/off toggle in the advanced search and an explanation in its hover** (Q610 note); field search also over
`url:` and `tag:` — **and the match mode made precise and user-chosen: does the url / title / author / source
"contain", "start with", or else, while the UI stays fresh and simple** (Q611 note — *design note:* FTS5 gives
prefix natively; "contains" over `url` is not an FTS5 operation and needs its own index or a stated cost);
`NEAR` defaulting to 10 tokens with a distance stepper, **and a user-changeable default** (Q612 note); regular
expressions a deliberate omission (Q613); search history local, private, opt-in, default off, clearable, never
exported — **offered during the installation process, after the legal screen** (Q614 note); list + table
views (Q615); permalinks carrying the full query + every filter (Q616); quarantined excluded by default, an
advanced-only "include quarantined" with the reason shown (Q617); **default sort = relevance** (Q618 = b —
FTS5 `bm25`; the relevance-ranked list is not a sample frame, per the recorded lesson); language restriction
lives here, in the advanced search only (Q505 = b). **Closes when** every ruled field is reachable and exported
(the intake's exit row: an export reproduces the filtered view, compared row-for-row on the reference corpus),
a saved search re-runs identically, the "did you mean" table exists as a job with its build cost measured on
the reference corpus, and the surface is Chromium-verified + click-through in two locales. Brief `S05-01`.

### Row B — ISO 3166-1 alpha-3, step 2 · ruled (Q301 ⛔ = c, Q304, Q305, Q313) · OPEN

**What it must demonstrate.** The storage half of FULL, staged: `country` becomes alpha-3 everywhere in the
store (the six `String(2)` columns widen; `LawDocument.jurisdiction` normalised), every parameter accepts both
forms through `normalize_country`, external-contract endpoints emit `country_iso2` beside it (Q304 = a); the
5,803 config lines rewritten in one scripted pass with a test that no lowercase alpha-2 `country:` value
remains (Q305 "follows Q301" → its (a) step); diagnostics payloads switch in this release and the old export
column is dropped (Q313); the restore normaliser of 0.4 row K is what makes every older backup restorable —
this row **runs it on a real pre-migration backup again after the storage migration** and re-reads the
duplicate-key scan. *Proposed placement:* the ISO 639-2/3 language move (Q306 = b) completes here in storage,
with the same both-forms acceptance and a test over the twelve locale codes. **Closes when** the migration's
before/after row counts per table are recorded, the config test is green, the real-restore scan reports 0
duplicates (operator; `not-measurable-here` in the sandbox), and the P0 data-safety trio is green on the
migrated store. Brief `S05-02`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC08.1` asked where register ruling **C5** (the DB-10
migrate-op: rebuild the store at the ruled pragmas, as a Settings → Advanced action carrying the honest cost
estimate from `rebuild.seconds`) lands. Blank, so its stated default is a labelled **ASSUMPTION: (a) — this
row, the storage half.** What that places here is an app-stopped, hours-long operation needing one spare
drive, whose estimate comes from a real `rebuild.seconds` reading and is shown before it starts; the
informed-consent non-negotiable makes that estimate and its caveat visible by default, ×12. It does not
change this row's own bar (Q301 = c step 2) and it does not open a new row. Reversed by writing a letter at
`ANSWER RC08.1`.

### Row C — The entity spine · ruled (Q415, Q724, Q805, Q818, Q827) · OPEN

**What it must demonstrate.** Entities (people, organisations, places) on the same three-tier ladder as
keywords, keyed by Wikidata QID — the spine's first concrete use (Q415); Wikidata items for the QIDs the corpus
mentions — labels, descriptions, a claims subset (P31, P17, P625, P571 …) — fetched at etiquette pace, cached
locally (Q724); the Place entity `Place(id = OSM type + id, qid, kind, admin path, names ×12, geometry ref,
as_of)`, `article_mentioned_places` resolving into it, its body the Wikidata / Wikipedia description + its OSM
metadata rendered as metadata, searchable and indexed (Q818); the gazetteer built from ingested OSM `place=*`
nodes joined to Wikidata at artifact-build time on the maintainer's machine, shipped with a registry entry and
a freshness test (Q805); place names `name:xx` first, Wikidata labels as the fallback, the source shown in the
hover (Q827). **Closes when** a press article's mentioned place resolves to a Place that a wiki page with the
same QID also resolves to (Q819 step 2 completed), the gazetteer artifact carries its registry entry and
vintage, and the Wikidata fetch is proven consented, spaced and refused under the kill switch by a fixture.
**Operator:** the networked artifact build. Brief `S05-03`.

### Row D — The OSM lane seeded · ruled (R16; Q106, Q806–Q811, Q813, Q814, Q815, Q817, Q819, Q820, Q822, Q824, Q825, Q828, Q1008) · OPEN, ODbL PENDING

**What it must demonstrate.** The seed the maintainer placed in 0.5 (Q106 = a): the Place entity (row C), the
first country's POIs and the tag-completeness view. Continent-level extracts as today (Q806 = b); the lane
off until the user picks countries, sizes and the daily diff cost shown, the wizard suggesting the countries
of the UI language, never from the IP (Q807); a `[geo]` extra with `pyosmium` for the extract pass, `.osc` diffs
pure Python, the small-country path offered without the extra (Q808); **places with metadata AND roads and
buildings** (Q809 = b); the curated column set + every other tag in one compact JSON blob — **the column list
extended to minimise the blob** (Q810 note; the Q1140 note's column ceiling applies); **SQLite for everything**
(Q811 = b); tag-level change rows — key added / removed / modified with the diff's timestamp and the object's
`version` (Q813; the daily apply itself is 0.6); **history depth = the full-history planet** (Q814 = b — one
planet-wide file from `planet.openstreetmap.org`; Geofabrik's per-region full-history extracts sit behind an
OSM login, which Q910's reasoning treats as key-gated; the download is consented, sized and shown before it
starts, and this row RECORDS the measured size and ingest time for the first country); analytic 1 — tag
completeness per country / admin-1 for `opening_hours`, `website`, `email`, `phone` (Q815); notable Places
only become Articles — admin areas, `place=*`, anything carrying `wikidata` / `wikipedia` — every other POI a
structured row with its own "Places" search facet (Q817); press articles' mentioned places resolve through the
gazetteer to Places (Q819 step 3); a local geocoder from the ingested addresses for the user's countries,
disclosed, never an external service (Q820); Canvas 2D with published level-of-detail caps, degrading to
clusters, never a frozen tab (Q822); the daily cadence and re-baseline rule stated, the per-country cost shown
before selection (Q824); `osm.db` encrypted alike (Q825); the country picker in Settings → Data sources → Maps,
the World map tab showing the vintage (Q828); the attribution lines at every export point — **for OSM-derived
rows only once Q823 ⛔ is ruled** (Q1008). **PENDING:** ODbL (Q823 ⛔, blank) — until ruled, OSM-derived rows
stay inside the machine: no export member, no bulletin line, no evidence ZIP. **Closes when** one country is
ingested on the reference VM with its measured sizes (extract, planet-history slice, `osm.db`) and ingest
times recorded, the tag-completeness view renders from the ingested rows and is Chromium-verified, a Place
opens as a card, and the fixture extract of 0.4 row O runs the same pipeline in CI. **Operator:** the
downloads. Brief `S05-04`.

### Row E — OSM-derived admin boundary artifacts · ruled (Q314, Q816, Q802); Q804 ASSUMED · OPEN

**What it must demonstrate.** OSM `admin_level=4` relations → shipped artifacts keyed ISO 3166-2 (`FR-75`,
`US-CA`) where OSM carries the tag, the relation id as the fallback identity (Q314; Q804 — blank, the sheet's
default taken as an ASSUMPTION: "rendered on all five surfaces from 0.5"), replacing Natural Earth from this
release (Q802); choropleths by alpha-3 and admin-1 on Equal Earth + the ranked table in full — the Observatory
rule, the table canonical — with the vintage stated (Q816); contested borders rendered CONTESTED with both
claims in the artifacts too (Q826, 0.4 row R). **Closes when** the artifacts carry their registry entry and
freshness test, all five surfaces render admin-1 from them with the vintage (Chromium-verified + click-through),
and one contested area is shown with both claims. **Operator:** the artifact build (a networked run of the OSM
preprocessing bridge on the maintainer's machine). Brief `S05-05`.

### Row F — Wikipedia: the WARM tier and the tail walk · ruled (Q701 ⛔ = c, Q707, Q712, Q722, Q727) · OPEN, the store PENDING

**What it must demonstrate.** WARM — every other changed page, full text, indexed lazily under the daily
budget — and COLD — the tail reached by the walk, metadata now, text as budget allows (Q707); **the slow
`allpages` walk for the never-edited tail, batched 50 titles per request, serial, under the storage budget,
coverage reported per edition** (Q701 ⛔ = c — the trade ruled knowingly; the reason dumps are out was asked
for as a NOTE and not given, so it stays unstated); analytics 4–5 — cross-edition divergence for one QID, and
attention (pageviews) versus press coverage (Q712); **everything follows the transport setting, the walk
included** (Q722 = b — over Tor the walk waits for the transport the user chose; it never downgrades; the row
records the measured throughput on both transports); the gap fallback (Q727). The sheet's arithmetic is the
planning figure, not a measurement: ~24 M articles ÷ 50 per request ≈ 480 k serial requests ≈ 5.6 days per pass
at 1 request / s on clearnet, moving on the order of 150–250 GB of wikitext (FROM MEMORY per-page size) — this
row replaces it with the measured rate of the first week. **PENDING:** the storage round-2 rulings (Q1009 ⛔,
blank — blob dedup, OOENC2 vs `age`, keyed-HMAC addressing, the sqlite3mc trial) gate the Phase-C store the
walk needs at full depth; if still blank, the walk runs under the existing store and the row states the depth
reached. **Closes when** the walk has run for a stated period on the reference VM inside the budget with its
own coverage counters (pages seen / edition total per edition) read from one artifact, the budget surface
(Q1006) shows the lane's growth, and analytics 4–5 render from real rows. `not-measurable-here` for the run;
**operator:** the run and the transport choice. Brief `S05-06`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC03` ⛔ (C4 = Q1009, the storage round-2 rows
3–6 — blob-store dedup · OOENC2 for pack AEAD · keyed-HMAC blob addressing with opaque pack names · the
sqlite3mc benchmark trial) came back blank on a ⛔ question, so it **stays PENDING and is never defaulted**.
The four values are still unwritten, so none of rows 3–6 may be executed and **this row's Phase-C seam stays
shut** — unchanged from before the round, and stated here so the pending is visible where the work is
blocked rather than only on the 0.9 board. The tail walk's own bar (Q722 = b) is untouched.

### Row G — Laws: the evolution surface · ruled (Q107, Q905, Q908, Q914, Q916, Q918, Q920) · OPEN

**What it must demonstrate.** The reader — version selector · side-by-side diff · provision navigation · an ELI
/ CELEX permalink · the licence line · "AI-derived · unreliable" on summaries · translation provenance —
**homogeneous with the app's other change-tracking surfaces, Wikipedia's first** (Q918 note: one Living-sources
grammar for wiki, law and OSM, 0.4 row O); point-in-time search — FTS over versions with `valid_on`, so "what
did this say in 2019" works without an Article per version (Q916); one document identity, N language versions
aligned, the reader's language switch, cross-language search finding it through any version (Q908); analytics
3–5 — cross-jurisdiction comparison by topic, an Equal Earth map of amendment activity with the vintage, "what
changed this week in the laws I follow" (Q914); AI summaries only, ≈, labelled; dates, provisions and
identifiers from rules, never the model (Q920); the versioning primitive of 0.4 row Q surfaced (Q905).
**Closes when** a law's 2019 text is findable by point-in-time search on the fixture jurisdiction and on one
real source, the reader's diff is Chromium-verified + click-through beside the wiki reader's (same controls,
same disclosures), and the map of amendment activity states its vintage. Brief `S05-07`.

### Row H — The AI-coordinator translation sweep and the model bench · ruled (Q405, Q513, Q1142, Q1143, Q1144) · OPEN

**What it must demonstrate.** Tentative translations shown by default once persisted, ≈-marked, when the AI
coordinator is on, filled by a background sweep over the untranslated head (Q405 — placed in 0.5 by Q1142's own
wording); **article titles and summaries translated by the local LLM, ≈-marked, on hover and in lists, never
stored as the article, opt-in — AND full-article translation in the reader, on demand, local LLM, ≈, never
stored** (Q513 = b + c); the multi-model specialisation bench run when the sweep lands (Q1142); a consented,
opt-in ollama.com library browse with the egress named (Q1143); perception extraction enabled per language only
where the measured gate passes, `who` refused where it fails (Q1144). **Closes when** the sweep's coverage
appears on the KPI board as a persisted measurement (the recorded K6 lesson: on-demand is unreadable), the
reader's on-demand translation is Chromium-verified with its ≈ label in two locales, and the bench report
exists with its fixture stated. Brief `S05-08`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** Three things land on this row, each reversible.
**`RC04` → (a): the model bench is NOT run in 0.5.** The register's D8 side wins §0's later-channel default
over Q1142 = a, so this row drops its bench part and the app-wide one-model decision is taken before 0.8
opens (0.8 row C; the 0.7 exit clause). The CONFLICT with Q1142 stays recorded on both rows. **`RC09` → (a):
the live ollama.com library browse is DROPPED** — no new consented egress surface, no search-and-filter UI,
no ×12 strings for it; the custom-model field stays the only path. The CONFLICT with Q1143 = a (a consented,
opt-in browse) stays recorded. **`RC08.2` → (a):** register rulings **D2** (editions open on the
deterministic introduction; the narrated path stays opt-in with its `fallback_reason`) and **D4** (the eight
bulletin sections and the checkbox review screen ratified as-is) are placed as a small `bulletin-defaults`
slice BESIDE this row in 0.5 — one setting plus its copy ×12, no model needed. It is recorded as a placement,
not opened as a board row: the two rulings already stand, and only where they sit was assumed. Q405, Q513
and Q1144 (D10) are untouched.

### Row I — The UI shell · ruled (Q1120, Q1121, Q1123, Q1127) · OPEN

**What it must demonstrate.** "Rings, not gates" as the information-architecture spine — a Ring controls what
is pinned, never what is reachable — with the two grafts from "Works while you sleep" (Q1120); Standard (Ring
1) when the depth question is skipped, Essentials only by explicit choice (Q1121); **the theme catalogue culled
to ≥ 10 named themes with invariant #12's pin lowered in the same PR** (Q1123 = b — CLAUDE.md amended
2026-09-15; the test moves here, not before); **a retirement slice for the ~613 inline handlers with a ratchet
that fails on any new inline handler, `'unsafe-inline'` dropped from the CSP when the count reaches zero**
(Q1127). **Closes when** the handler ratchet exists at the measured count and the count reaches zero (or the
row records the measured residue and why), the CSP change is Chromium-verified across the 17-then-≥10 themes at
the widths of the 2026-09-09 axe sweep (the 0.4 gate's log names 1440×900, 768×1024 and 390×844; the
audit's own viewport table lists five — the session reads the sweep record for the set it drives), and the
culled themes are named with their nearest survivor.
Brief `S05-09`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC08.5` asked where register ruling **H3**
(remove `#ins-term` + `exploreTerm`, behind the omnibar-absorption test) lands. Blank, so its stated default
is a labelled **ASSUMPTION: (a) — this row, the UI shell.** The gate on it is the one the ruling itself
names and is not weakened here: the surface goes only once its absorption test passes, which is the recorded
"never lose a tool" discipline and the reason the 2026-07-12 blind hide was refused. The theme cull (Q1123 =
b, invariant #12's floor moving to ≥ 10 in the same PR as the cull) and the inline-handler retirement (Q1127,
H4's one-module-per-slice method) are untouched. Reversed by writing a letter at `ANSWER RC08.5`.

### Row J — A source is keyed on its FEED · ruled (Q1102 ⛔ = b) · *proposed placement* 0.5 · OPEN

**What it must demonstrate.** The identity migration the maintainer chose — a source keyed on its feed, so
the 75 language services (BBC Arabic, DW Español …) and the 192 `lean-*`-tagged entries shadowed by a
same-domain sibling can exist — with its data-safety review reaching the alias dedup, the restore-merge joins,
the overlay and the citations tally (the sheet's own list). *Proposed placement:* 0.5 rather than 0.4, after the
0.4 format bump has been exercised on a real restore, so the two identity migrations (country codes, source
keys) never land on one untested format; the maintainer may pull it forward in §3. **Closes when** the
migration's row counts before/after are recorded, a real pre-migration backup restores with 0 duplicates from
the scan (operator), the shadowed-entry count falls from 475 to the measured residue, and the citations tally
is proven stable across the migration by a fixture. Brief `S05-10`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC16` came back blank → **ASSUMPTION (a): the
`lean-*` political-lean scale is REMOVED from the offerable vocabulary.** The LLM may no longer propose a
lean tag; human-asserted lean tags stay, and the stated position in `source_tags.py` changes with its reason
recorded in the same diff. This follows the register's L9 as §0's later-channel default over Q1129 = a (keep
the stance: reported, never filtered) — and note what the 2026-09-11 check measured before either answer
existed: the code already classifies `lean-*` as non-topical and declines to filter it, twice in 921
assignments, so this assumption changes what may be PROPOSED, not what is displayed. The CONFLICT with Q1129
stays recorded on both rows. This row's own ruling (Q1102 ⛔ = b, the feed key) is untouched.

### Row K — The approved desk · carried from the V1 train, kept by Q105 = a · OPEN

**What it must demonstrate.** The V1 §3 contents of 0.5 the sheet did not touch: the claim workspace A1 with
evidence trails, the cross-vertical entity / topic dossier seed on the spine of row C, the Conjunction Lens
across verticals, the onboarding tour, signed-evidence export polish. They are carried as ruled 2026-09-07;
their own open design questions are in the V1 pathway, `docs/FUTURE_DEVELOPMENTS.md` §"User-centric
reflections" A1–A9 and the 23-prompt plan (PROMPT_23 §S5; `INVENTORY.md` row V1-E — not PROMPT_17, which
carries none of them; corrected 2026-09-15 from brief `S05-11`'s grep), not re-asked here.
**Closes when** each ships with its own tests and click-through record; the dossier's 1.0 bar (V1 §8 item 4:
≥ 6 rails) is not owed here — 0.8 row A owes it. Brief `S05-11`.

---

## 3. Amendment log

| Date | Change | Source |
|---|---|---|
| 2026-09-15 | Board created from the answered roadmap sheet (Q112 = a, Q1204 = a): rows A–K, each citing its question IDs; the entry precondition (0.4 row K before row B) recorded from Q301 = c | maintainer (answer sheet) · rows written by the session |
| 2026-09-15 | **The 2026-09-06 register's 65 answers (rulings artifact, 15:02–16:00Z) — effects on this board, nothing resolved by the session:** row H — D8 «wait for the app wide one model ruling … before version 0.8» CONFLICTS with Q1142 = a (run the bench in 0.5; `RC04`) and D9 `default` (drop the live ollama.com browse) CONFLICTS with Q1143 = a (`RC09`); D10 consistent; row I — H4's method (one module per slice, `app-boot.js` first) recorded; H3 (remove `#ins-term` behind the absorption test) proposed here (`RC08.5`); row J — L9 `default` (remove the lean scale) CONFLICTS with Q1129 = a (`RC16`); row B — C5 (the DB-10 migrate-op as a Settings → Advanced action) proposed here (`RC08.1`); row F — C4 came back `default` (yes / OOENC2 / yes / yes) at 15:12Z where Q1009 was blank that morning: ⛔, `RC03` asks for the four values; the seam stays. A `bulletin-defaults` slice (D2 + D4) is proposed beside row H (`RC08.2`). | maintainer (the register, 2026-09-15) · reconciled by the session |
| 2026-09-15 | **The RC confirmation round came back UNANSWERED — 0 of 22 `ANSWER` lines carry a letter — processed per its own §0; nothing resolved by the session.** Effects on this board, all reversible by writing a letter: row B — `RC08.1` ASSUMPTION (a), C5's DB-10 migrate-op placed here; row F — `RC03` ⛔ PENDING, the four storage round-2 values still unwritten so the Phase-C seam stays shut; row H — `RC04` ASSUMPTION (a) the bench is NOT run in 0.5 (the decision moves to 0.8 row C), `RC09` ASSUMPTION (a) the live ollama.com browse dropped, `RC08.2` ASSUMPTION (a) D2 + D4 placed as a small `bulletin-defaults` slice beside this row; row I — `RC08.5` ASSUMPTION (a), H3 placed here behind its absorption test; row J — `RC16` ASSUMPTION (a), the `lean-*` scale leaves the offerable vocabulary. A NEW 0.5 slice is also assumed by `RC07` (article revision tracking on the finished 0.4 row O substrate, B7's note) — recorded as a placement, not opened as a board row. Four of these sit on CONFLICT questions and follow the later channel exactly as §0 directs; BOTH answers stay recorded on their `A1`–`L10` and `Qnnn` rows. **No row changed status.** | maintainer (the round, left blank) · §0's blank rules applied by the session |

---

## 4. Not in this gate

- **The OSM daily change tracking and the trend surfaces** — 0.6 (Q106 = a; `RELEASE_0.6_GATE.md` row B).
- **Law breadth to the language coverage floor** — 0.6 (Q107 = a); treaties as `INT` — 0.6 (Q930).
- **The Wikipedia coverage report per edition** — 0.6 (Q108 = a); the free-text address geocoding of R17 step 4
  — 0.6 (Q819).
- **Self-rendered vector streets** (Q821 = b) — *proposed placement* 0.7, after the ingested roads exist.
- **Subnational law** — 0.7 (Q903, a recorded CONFLICT; `RELEASE_0.7_GATE.md` row C).
- **Help's body ×12** (Q1122 = b) — staged 0.6 → 0.8 (*proposed placement*).
- **The four ⛔ questions left blank** — Q823, Q925, Q1009, Q1113 — not decided here, not defaulted anywhere.
- **The version flip to `0.5.0`.** It follows the `v0.4.0` tag, mechanically.
