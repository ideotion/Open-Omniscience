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

**Entry.** `v0.4.0` tagged (`RELEASE_0.4_GATE.md` rows A–E, G–W closed; row W was added 2026-09-27 by `RC01` = a). Two 0.4 rows are hard preconditions
here by ruling: row K (the backup-format bump, exercised on a real restore) precedes row B below (Q301 = c),
and row O (the substrate) precedes rows D and F. **2026-09-28:** the maintainer tagged `v0.4.0` with 0.4 rows
still open (`RELEASE_0.4_GATE.md` §3, 2026-09-28); the tag half of this entry is met, the closed-rows half is not,
and the two hard preconditions above stand unchanged.

---

## 1. The board

| # | Row | Owner | Origin | Status |
|---|---|---|---|---|
| A | The advanced search — one UI for every search need | session | ruled (R11; Q505, Q601–Q618) · brief `S05-01` | **BUILT 2026-09-28 (PR #1198)** — Chromium-verified (remote sandbox) in en and ar · awaiting human UX pass |
| B | ISO 3166-1 alpha-3, step 2: the store, the configs, the payload flip | session + operator (a real restore) | ruled (Q301 ⛔ = c step 2, Q304, Q305, Q313; `R38` first of B/J, `R39` the hi/bn rebuild; Q306 storage step *proposed placement*) · `S05-02` | **OPEN** — needs 0.4 row K exercised |
| C | The entity spine: QIDs, Wikidata items, the Place entity, the gazetteer artifacts | session + operator (artifact build) | ruled (Q415, Q724, Q805, Q818, Q827) · `S05-03` | **OPEN** |
| D | The OSM lane seeded: the first country's places, roads and buildings; the tag-completeness view | session + operator (extract + planet history download) | ruled (R16; Q106, Q806–Q811, Q813, Q814, Q815 · 1, Q817, Q819 · 3, Q820, Q822, Q824, Q825, Q828, Q1008) · `S05-04` | **OPEN** — ODbL (Q823 ⛔) PENDING |
| E | OSM-derived admin-0 / admin-1 artifacts keyed ISO 3166-2, on all five surfaces | session + operator (artifact build) | ruled (Q314, Q816, Q802 second half); Q804 an ASSUMPTION at its default · `S05-05` | **OPEN** |
| F | Wikipedia: the WARM tier and the `allpages` tail walk under budget | session + operator (the run) | ruled (R12; Q701 ⛔ = c, Q707, Q712 · 4–5, Q722 = b, Q727; `R40` built first) · `S05-06` | **OPEN** — the Phase-C store (Q1009 ⛔) PENDING |
| G | Laws: the evolution surface — versions, the reader, point-in-time search, analytics 3–5 | session | ruled (R14; Q107, Q905, Q908, Q914 · 3–5, Q916, Q918, Q920) · `S05-07` | **BUILT 2026-09-28 (PR #1203)** — Chromium-verified (remote sandbox) in en and ar · awaiting human UX pass; the real-source 2019 search is operator |
| H | The AI-coordinator translation sweep; titles, summaries and on-demand full text; the model bench | session | ruled (Q405, Q513 = b + c, Q1142, Q1143, Q1144) · `S05-08` | **OPEN** |
| I | The UI shell: "rings, not gates", the first-run default, the inline-handler retirement + CSP, the theme cull | session | ruled (Q1120, Q1121, Q1123, Q1127) · `S05-09` | **OPEN** |
| J | A source is keyed on its FEED — the migration and its data-safety review | session + operator (a real restore) | ruled (Q1102 ⛔ = b; `R38` after row B); *proposed placement* 0.5 · `S05-10` | **OPEN** |
| K | The approved desk: the claim workspace A1, the Conjunction Lens across verticals, the onboarding tour, signed-evidence export polish | session | carried from the V1 train (ruled 2026-09-07), kept by Q105 = a · `S05-11` | **OPEN** |
| L | Q803's default: OSM's border convention as of a stated date opens every map (moved from 0.4 row R) | session + operator (row E's artifact build) | ruled (Q803 and its note, Q826); placement `PF06` = a, 2026-09-27 · `S05-05` | **OPEN** — waits on row E's OSM-derived artifacts |

**The exit.** `v0.5.0` is tagged when rows A–L are CLOSED on named artifacts, the three i18n gates and the
whole-tree guards are green on the tagged tree, and the release notes carry the no-telemetry re-check (Q111).
Row D closes with OSM rows INSIDE the machine only: until Q823 ⛔ is ruled, no OSM-derived row enters an export,
a bulletin or an evidence ZIP (today's state, not a decision). Row F closes at the budgeted depth the store
allows; if Q1009 ⛔ is still blank, the walk runs under the existing store and the row says how far it got.

---

## 2. The rows

### Row A — The advanced search · ruled (R11; Q505, Q601–Q618) · BUILT 2026-09-28 (PR #1198), awaiting human UX pass

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

**2026-09-28 — the order and the re-index (`R38`, `R39`, «D2: a · D3: a» in chat).** Row B goes before row J,
never beside it. The same app-stopped window also recreates `article_fts` with the tokenizer option that
keeps Devanagari and Bengali vowel signs inside a word (`OPEN_QUEUE.md`, «FINDING OUTSIDE Q507») and rebuilds
it in full, so the operator stops the app once. **This row now also closes on** the rebuild's measured time
recorded beside the migration's row counts, and a fixture proving that a search for सरक no longer matches
सरकार on the migrated store.

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

**2026-09-28 — built first (`R40`).** The maintainer asked whether the long walk should be built early and
left running while the other rows are built; it is. This moves the build order and nothing else: the walk
(S2 + S3) ships first, in its own table so it never makes a page followed, and WARM (S1) right after it; the
⛔ above still caps its depth, and the run is still the operator's. After any
restart the app boots offline, so the walk resumes from its per-edition cursor only once the operator goes
online again.

**2026-09-28 — the walk is built (S2 + S3, PR #1197), off by default.** `src/wiki/walk.py` asks each of the lane's
editions' `allpages` for 50 articles a request (the main namespace, no redirects), serially and round-robin
across the editions, in the lane's own idle time and on the lane's own client (one kill switch, one proxy, one
user agent, one second between requests). Its pages go to `wiki_walk_pages` in `wiki.db` and never to the
pages the lane follows, so no walked page is fetched or indexed as HOT. Each edition keeps the source's own
continuation verbatim, so a restart resumes and re-asks for nothing. A spent budget, airplane mode and a
protected mode with no usable proxy stop it by name, and it never goes direct (Q722 = b); a refusal from one
edition backs off that edition alone, 60 s doubling to an hour. Coverage per edition — pages seen of the
edition's own article count, read from `siteinfo` — and the measured rate per transport ride the lane
counters artifact as its `walk` block; Living sources' Wikipedia panel shows a «Page walk» group, and the task
manager shows the walk while it walks, pauses or waits, with counts and no ETA. The switch is Settings →
Wikipedia, «Also walk every article title», **off** until the operator turns it on for the instance
that should carry the run (`R51`, «Switch, off»). Chromium-verified (remote sandbox) in `en` and `ar` · awaiting human UX
pass. **Seams, stated:** (1) S2's fetch-history round trip waits on the lane riding a backup (Q721; the
inventory keeps it non-exportable until S04-04 owns the lane format); the walk's rows are that history, and
`lane_models.py` names the one table the toggle will gate. (2) S3 names `tor_throughput.py`, which is the
scheduler's kind ladder and records nothing, so the walk writes its own per-transport samples per hour.
(3) Only the first pass is built; when to walk an edition again is not ruled. (4) Round-robin is the
proposed per-edition order (the brief's §6 leaves it unruled). (5) Q1009 ⛔ still caps the depth.

**2026-09-28 — WARM is built (S1, PR #1200), off by default.** `src/wiki/warm.py` reads the stream's own
change log (`versioned_changes`, Q708 = b) forward from its bookmark and queues each changed page the lane does
not follow in `wiki_warm_pages`, so there is one record of what the wiki reported and WARM reads it. In the
lane's idle time, after the drain and before the walk (Q707's HOT, then WARM, then COLD), it asks for the pages
that have waited longest, 50 to a request, and for each page's NEWEST text: a page edited ten times while it
waited costs one fetch. A row holds at most the latest and the previous text (Q710 🔒 = a); a page deleted later
keeps its text (Q713), and a page that becomes followed stops being asked for and keeps what WARM held. It
stops at `WARM_BUDGET_SHARE` (0.9) of the lane's budget under its own named reason and leaves the rest to HOT;
that share is a **proposed default, not a ruling**, and every surface that shows the pause says so. Its
refusals are the walk's: a spent budget, airplane mode and protected mode with no usable proxy pause it by
name and it never goes direct (Q722 = b); one edition's refusal backs off that edition alone. Its counts ride
the lane counters artifact as a `warm` block, and Living sources' Wikipedia panel shows an «Other changed
pages» group above the walk's. The switch is Settings → Wikipedia, «Also fetch the text of other changed
pages», **off** until the operator turns it on; where WARM runs was put on a decision card and is built at the
recommended «Switch, off» meanwhile. Chromium-verified (remote sandbox) in `en` and `ar` · awaiting human UX
pass. **Where its texts live (`R52`, «In the lane»):** in `wiki.db`, under the budget, never corpus articles
by themselves (Q719). So this row also owes the lane's own search index over them, their hits in the one
search box beside the corpus's, and «Add to corpus» per hit for the version hit. **The index and «Add to
corpus» are PR #1202**: `src/wiki/lane_search.py` indexes each changed page's latest text in
full and every older held version by the lines a later edit removed, fed by triggers in the same transaction
as each text and built in the lane's idle time before WARM; `GET /api/wiki/lane/search` answers with an exact
total, what the search covered and the index's one caveat; `POST /api/wiki/lane/add-to-corpus` adds ONE held
version as its own article under its `oldid` address; the command palette lists the hits beside the corpus's
and opens each version in a window with that button, and the Search tab lists them below the corpus's results,
after saying what was searched. **Still owed in this row:** COLD text, analytics 4–5 (S4) and the operator's run (S5).

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC03` ⛔ (C4 = Q1009, the storage round-2 rows
3–6 — blob-store dedup · OOENC2 for pack AEAD · keyed-HMAC blob addressing with opaque pack names · the
sqlite3mc benchmark trial) came back blank on a ⛔ question, so it **stays PENDING and is never defaulted**.
The four values are still unwritten, so none of rows 3–6 may be executed and **this row's Phase-C seam stays
shut** — unchanged from before the round, and stated here so the pending is visible where the work is
blocked rather than only on the 0.9 board. The tail walk's own bar (Q722 = b) is untouched.

### Row G — Laws: the evolution surface · ruled (Q107, Q905, Q908, Q914, Q916, Q918, Q920) · BUILT 2026-09-28 (PR #1203), awaiting human UX pass

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

**2026-09-28 — built (PR #1203).** ONE version reader, `src/static/ooversions.js`, mounted by the standalone law
page, the Living sources Law panel and the Wikipedia tracked-changes panel, fed by one payload shape
(`src/law/versions.py`, `src/wiki/versions.py`) and one comparison computed locally from the two full texts
(`src/versioned/compare.py`, bounded by the lane's own diff limits). Parts are a law's provisions or a page's
`== sections ==`; a version whose text was never stored refuses the comparison by name. A Wikipedia page's
versions are read from both stores, the old tracker's and the Wikipedia lane's, one row per edit. Dating follows ONE rule:
official where the source states it, else the observation day, labelled. Point-in-time search is a contentless
FTS5 index in `law.db` synced on read (`src/law/pit_search.py`), with a coverage line naming the versions it
cannot search. Analytics 3–5 are in `src/law/analytics.py` (by topic across jurisdictions; the Equal Earth map
with its window and newest capture; this week in the laws you watch). Verified on the fixture jurisdiction
(`tests/test_law_evolution_surface.py`, `tests/test_law_evolution_ui.py`) and walked in Chromium in en and ar.
**Still open:** the 2019 search against one REAL source (operator) and the human UX pass.

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

**2026-09-28 — after row B (`R38`, «D2: a» in chat).** The order the brief left unruled is settled: row B's
migration lands and is restored for real first, then this one; never both at once.

### Row K — The approved desk · carried from the V1 train, kept by Q105 = a · OPEN

**What it must demonstrate.** The V1 §3 contents of 0.5 the sheet did not touch: the claim workspace A1 with
evidence trails, the cross-vertical entity / topic dossier seed on the spine of row C, the Conjunction Lens
across verticals, the onboarding tour, signed-evidence export polish. They are carried as ruled 2026-09-07;
their own open design questions are in the V1 pathway, `docs/FUTURE_DEVELOPMENTS.md` §"User-centric
reflections" A1–A9 and the 23-prompt plan (PROMPT_23 §S5; `INVENTORY.md` row V1-E — not PROMPT_17, which
carries none of them; corrected 2026-09-15 from brief `S05-11`'s grep), not re-asked here.
**Closes when** each ships with its own tests and click-through record; the dossier's 1.0 bar (V1 §8 item 4:
≥ 6 rails) is not owed here — 0.8 row A owes it. Brief `S05-11`.

### Row L — OSM's border convention as the default · ruled (Q803 and its note, Q826; placement `PF06` = a, 2026-09-27) · OPEN

**What it must demonstrate.** Q803's ruled DEFAULT, moved off 0.4 row R by `PF06` = (a) («Row R: OK to move that
to 0.5»): every map opens on OSM's border convention as of a stated `<date>`, named in the legend, while every
disputed area is still rendered CONTESTED showing both claims (Q826) and the worldview toggles still let the
user see the difference between conventions (Q803's note); 0.4 row R shipped those last two. It waits on row E,
because Natural Earth's de-facto policy is not OSM's, and calling it OSM's would be the silent pick the same
ruling forbids; until then the default is `contested` (it assigns nothing). The `<date>` and the SOURCE of
OSM's claims are named in the PR, and the maintainer may move either (brief `S04-11` §6). **Closes when** a
Chromium click-through record shows the five surfaces opening on OSM's convention with its date in the
legend, one disputed area with both claims, and the toggle switching to another convention, and a test pins
the default. Brief `S05-05`, with `S04-11` S3's toggle.

---

## 3. Amendment log

| Date | Change | Source |
|---|---|---|
| 2026-09-15 | Board created from the answered roadmap sheet (Q112 = a, Q1204 = a): rows A–K, each citing its question IDs; the entry precondition (0.4 row K before row B) recorded from Q301 = c | maintainer (answer sheet) · rows written by the session |
| 2026-09-15 | **The 2026-09-06 register's 65 answers (rulings artifact, 15:02–16:00Z) — effects on this board, nothing resolved by the session:** row H — D8 «wait for the app wide one model ruling … before version 0.8» CONFLICTS with Q1142 = a (run the bench in 0.5; `RC04`) and D9 `default` (drop the live ollama.com browse) CONFLICTS with Q1143 = a (`RC09`); D10 consistent; row I — H4's method (one module per slice, `app-boot.js` first) recorded; H3 (remove `#ins-term` behind the absorption test) proposed here (`RC08.5`); row J — L9 `default` (remove the lean scale) CONFLICTS with Q1129 = a (`RC16`); row B — C5 (the DB-10 migrate-op as a Settings → Advanced action) proposed here (`RC08.1`); row F — C4 came back `default` (yes / OOENC2 / yes / yes) at 15:12Z where Q1009 was blank that morning: ⛔, `RC03` asks for the four values; the seam stays. A `bulletin-defaults` slice (D2 + D4) is proposed beside row H (`RC08.2`). | maintainer (the register, 2026-09-15) · reconciled by the session |
| 2026-09-15 | **The RC confirmation round came back UNANSWERED — 0 of 22 `ANSWER` lines carry a letter — processed per its own §0; nothing resolved by the session.** Effects on this board, all reversible by writing a letter: row B — `RC08.1` ASSUMPTION (a), C5's DB-10 migrate-op placed here; row F — `RC03` ⛔ PENDING, the four storage round-2 values still unwritten so the Phase-C seam stays shut; row H — `RC04` ASSUMPTION (a) the bench is NOT run in 0.5 (the decision moves to 0.8 row C), `RC09` ASSUMPTION (a) the live ollama.com browse dropped, `RC08.2` ASSUMPTION (a) D2 + D4 placed as a small `bulletin-defaults` slice beside this row; row I — `RC08.5` ASSUMPTION (a), H3 placed here behind its absorption test; row J — `RC16` ASSUMPTION (a), the `lean-*` scale leaves the offerable vocabulary. A NEW 0.5 slice is also assumed by `RC07` (article revision tracking on the finished 0.4 row O substrate, B7's note) — recorded as a placement, not opened as a board row. Four of these sit on CONFLICT questions and follow the later channel exactly as §0 directs; BOTH answers stay recorded on their `A1`–`L10` and `Qnnn` rows. **No row changed status.** | maintainer (the round, left blank) · §0's blank rules applied by the session |
| 2026-09-27 | **Row L added: Q803's default moved here from 0.4 row R** (`PF06` = a, «Row R: OK to move that to 0.5»), beside row E's OSM artifacts it waits on. The entry clause now names 0.4 rows G–W (row W, `RC01` = a), and the exit clause A–L. | maintainer (chat, 2026-09-27) · recorded by the session, PR #1191 |
| 2026-09-28 | **The 0.5 start, answered in chat** («D1: Yes, start. … D2: a D3: a», with a question about the Wikipedia walk): `R38` — row B before row J, never concurrently; `R39` — the hi/bn tokenizer rebuild is paid inside row B's window, and row B now also closes on its measured rebuild time and a hi fixture; `R40` — row F is built first so its operator run overlaps the build (order only; no gate moved). Wave 1 starts with rows A and I in their own threads. **No row changed status.** | maintainer (chat, 2026-09-28 11:07 UTC) · recorded by the session |
| 2026-09-28 | **Row F: the walk built (S2 + S3), off by default.** The `allpages` walk, its per-edition bookmark, its coverage and per-transport counters in the lane counters artifact, a Living sources group and a task-manager row; the switch that decides where it runs is asked on a card and built at the recommended «off» meanwhile (`OPEN_QUEUE.md` «THE WALK'S SWITCH»). Five seams stated in the row, the fetch-history round trip first. **No row changed status.** | session, PR #1197 |
| 2026-09-28 | **`R51`: the walk runs only where it is switched on, off by default** («Switch, off» on the decision card, the recommended option). Row F's text now names the ruling where it named the open question; the default was already built this way, so only a test pinning it was added. **No row changed status.** | decision card in the project thread «Plan v0.5», 2026-09-28 12:41 UTC |
| 2026-09-28 | **`R52`: WARM's texts stay in the lane, with a search index of their own** («In the lane» on the decision card, the recommended option, after the maintainer's stated intent: one search, and a Wikipedia hit — an article, an edit or a previous version — can be added to the corpus). Row F now owes, beside WARM itself, the lane search index, its hits in the one search box and «Add to corpus» per hit. **No row changed status.** | decision card in the project thread «Plan v0.5», 2026-09-28 13:20 UTC |
| 2026-09-28 | **Row A built (S05-01, PR #1198).** All nineteen rulings implemented; Chromium-verified in the remote sandbox in English and Arabic (the builder, the timescale, list and table views, did-you-mean, save and re-open, the permalink, history, the omnibar's Enter, the first-launch history step); the did-you-mean table on the 200 MB reference corpus: 873,889 rows, 4.9 s, 12.6 MB. Status stays short of CLOSED until a human UX pass. | session |
| 2026-09-28 | **Row I, first PR (S05-09 S1 + S3, and S2 for the main app):** the inline-handler ratchet exists at the measured count, 656 on `main`@00af1d9 with its own published pattern (`tests/test_inline_handler_ratchet.py`; the brief's 602/613 were other patterns); the main app's 644 converted to allowlisted `data-on-*` bindings (`src/static/oo-on.js`), leaving the measured residue pinned: `taskmanager.html` 11, `unlock.html` 1, six inline `<script>` blocks (task manager, unlock, investigate, the reader, the law reader). `'unsafe-inline'` stays in `script-src` until that residue is zero (next entry). The theme cull: slate → Ink, arctic → Ink, mist → Light (surface ΔE76 1.92 / 1.81 / 1.25; next pair 3.87), 14 named themes, invariant #12's pin `>= 16` → `>= 13` in the same PR (`tests/test_theme_cull.py`). Chromium walk under `script-src 'self'` at 1440×900; the three-width sweep is owed with the CSP-drop PR. **Row stays OPEN.** | session (0.5 row I thread) |
| 2026-09-28 | **Row I, the CSP drop (S2 end, pushed onto the same PR #1199):** the residue reached ZERO. The task manager's 11 handlers became `data-tm` bindings, unlock's one a listener, and the six inline `<script>` blocks became files (`taskmanager.js`, `unlock.js`, `investigate.js`, `ext-confirm.js`, and `reader.js` for the Dates pane). Both ratchet maps are empty and `script-src` is `'self'` alone (NET-04 closed, no nonce needed; `style-src 'unsafe-inline'` stays, unruled). Chromium-verified under the real header: 14 named themes plus System × 1440×900, 768×1024 and 390×844, the main app's Home, Settings, Search, Insights and Living sources plus `/tasks`, `/investigate`, `/unlock`, the article reader and the law reader: 45 runs, 0 CSP violations, 0 console errors, 0 horizontal overflow; both reader link confirms, unlock's console button and the task manager's cancel and resume bindings driven for real. No axe run (not available offline in the sandbox). The ratchet, CSP and cull halves of this row are done; **row stays OPEN** for S4 (the Ring dial, Q1120/Q1121) and S5, S6 waiting on the maintainer. | session (0.5 row I thread) |
| 2026-09-28 | **Row F: the lane search built (`R52`'s two conditions, PR #1202).** The lane's own index over WARM's texts and every older held version; its hits in the command palette and in the Search tab, below the corpus's results, after a line saying what was searched (the texts the lane holds on this machine, per edition, never Wikipedia itself); «Add to corpus» adds ONE version per click. A query reads with row A's grammar, and the filters that describe articles are named as not applied. Chromium-verified in the remote sandbox in English and Arabic. **No row changed status.** | session, PR #1202 |
| 2026-09-28 | **Row G built (S05-07, PR #1203).** One version reader for law and Wikipedia (selector, side-by-side diff, provision or section navigation, permalink, licence, AI-derived label, language switch, provenance), point-in-time search over law versions with its coverage stated, and analytics 3–5; Chromium-verified in en and ar. The real-source search and the UX pass remain. |
| 2026-09-28 | **Row F: «Add to corpus» in the version reader (`R52`, PR #1207).** Each end of row G's comparison offers the add for a Wikipedia version from either store, so a revision «Track now» stored, which no search reads yet, can reach the corpus. The reader says when the corpus already holds a version, and a version whose text was not stored says why it cannot be added. The law reader offers nothing. Chromium-verified in the remote sandbox in English and Arabic. **No row changed status.** | session, PR #1207 |

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
