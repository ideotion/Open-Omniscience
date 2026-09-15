# The beta pathway — session briefs (2026-09-12 round, written 2026-09-15)

**What this is.** One brief per slice of the alpha train to the beta, written from the maintainer's answered
roadmap sheet ([`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
the primary record; every answer indexed in [`docs/ledger/RULINGS_INDEX.md`](../../ledger/RULINGS_INDEX.md)) and
from the gate files it produced (`docs/product/RELEASE_0.4_GATE.md` amended, `RELEASE_0.5_GATE.md` …
`RELEASE_0.9_GATE.md` new). Ruled by Q112 = a, Q113 = a and Q1204 = a: "one prompt file per slice … the shape of
the 23-prompt action plan: scope fence, verbatim gate commands, the rulings it implements by ID, the operator
steps, what it may not decide" — written in one session from the answered sheet, as one docs PR. Nothing here
was built; nothing here decides a ⛔ question the maintainer left blank.

**Anchor:** the sheet's context was verified at `main`@`bebcef4` (2026-09-12); each brief's §2 says which anchors
it re-checked. **No dates** (Q110 = c). **The train:** 0.3 closes now (Q109) → 0.4 living sources → 0.5 the
investigator's desk → 0.6 elections + climate, plus breadth → 0.7 medical + patents, and the widening → 0.8
conflict + the 360° dossier, lane completion → **0.9.0 = Beta 1** (Q101 ⛔ = a) → 1.0.0 general availability.

## The files

| File | What it holds |
|---|---|
| [`_WORKING_MODE.md`](_WORKING_MODE.md) | The rules every brief shares — a delta over the 2026-09-06 working mode: the three files a brief rests on, what no brief may decide, what every brief owes, the gates verbatim. **Part of every brief.** |
| `S03-01_…` … `S09-01_…` | The slices, one file each; the table below is the map. |

## How to run one

Read `CLAUDE.md` and `docs/ledger/LESSONS.md` in full, then `_WORKING_MODE.md`, then the brief, then the gate
row it names, then its rulings in `RULINGS_INDEX.md`. Grep the tree before building (the staleness guard runs
both ways, and against a ruling's premise). Open one draft PR per coherent slice onto `main`; the maintainer
merges. Close out per the brief's §7 — a `shipped.csv` row naming which part shipped, the gate row's status, the
ruling's `where enforced` cell.

## The slices

Dependency order inside a release is the gate file's row order; across releases each gate's entry clause names
what must precede it (the 0.4 format bump before the 0.5 storage half; the substrate before the lanes; the OSM
seed before the change tracking). Operator steps are listed in every brief's §5 and are unbounded by ruling
(Q115 = c).

| Slice | Release | Brief | Gate row | Rulings (question IDs) | What it holds |
|---|---|---|---|---|---|
| `S03-01` | 0.3 | [`S03-01_release-0-3-close-and-version-flip.md`](S03-01_release-0-3-close-and-version-flip.md) | `RELEASE_0.4_GATE.md` row G | Q109 | Close 0.3 (row 5 + the v0.3.0 tag from the maintainer's machine), then the version flip to 0.4.0 |
| `S04-01` | 0.4 | [`S04-01_docs-security-enumeration-and-consent-hover.md`](S04-01_docs-security-enumeration-and-consent-hover.md) | `RELEASE_0.4_GATE.md` row H | Q1001, Q1002 | SECURITY.md enumerates every host the app can reach; the consent hover lists hosts per lane |
| `S04-02` | 0.4 | [`S04-02_import-lifecycle-and-fresh-page.md`](S04-02_import-lifecycle-and-fresh-page.md) | `RELEASE_0.4_GATE.md` row I | Q201, Q202, Q203, Q204, Q205, Q206, Q207, Q214, Q216, Q217, Q221, Q222 | The import experience: fresh page, four visible stages, one poll chain, the re-index inside, K = 3 checkpoints, one API path |
| `S04-03` | 0.4 | [`S04-03_export-folder-and-completion-panel.md`](S04-03_export-folder-and-completion-panel.md) | `RELEASE_0.4_GATE.md` row J | Q208, Q209, Q210, Q211, Q212, Q213, Q218, Q219, Q220, Q1008 | The export: dated OpenOmniscience_Backup folder, the completion panel, BACKUP_SUMMARY.md, verify-after-write, never scheduled |
| `S04-04` | 0.4 | [`S04-04_backup-format-bump-normaliser-and-fetch-history.md`](S04-04_backup-format-bump-normaliser-and-fetch-history.md) | `RELEASE_0.4_GATE.md` row K | Q215, Q310, Q313, Q404, Q409 | ONE backup-format bump carrying the alpha-3 restore normaliser, all rings, the tentative-translation table and the fetch/scrape history member with its trust toggle |
| `S04-05` | 0.4 | [`S04-05_alpha3-display-and-boundary.md`](S04-05_alpha3-display-and-boundary.md) | `RELEASE_0.4_GATE.md` row L | Q301, Q302, Q303, Q306, Q307, Q308, Q309, Q311, Q312 | ISO 3166-1 alpha-3 step 1: every code the user sees, payloads gain country_iso3, the loader normalises, the filename rule; ISO 639-2/3 display step |
| `S04-06` | 0.4 | [`S04-06_keyword-translation-ladder.md`](S04-06_keyword-translation-ladder.md) | `RELEASE_0.4_GATE.md` row M | Q401, Q402, Q403, Q406, Q407, Q408, Q410, Q411, Q412, Q413, Q414, Q416, Q418, Q1103, Q1104 | Keywords in the UI language, 'translated from X': the label grammar, the three-tier ladder, the auto-loaded Wikidata rings at 1 request / 10 s, lemmatisation, the per-mention language |
| `S04-07` | 0.4 | [`S04-07_cross-language-search-by-rings.md`](S04-07_cross-language-search-by-rings.md) | `RELEASE_0.4_GATE.md` row N | Q417, Q501, Q502, Q503, Q504, Q506, Q507, Q508, Q509, Q510, Q511, Q512, Q514, Q515, Q516 | Every search expands through the rings by default in every tab; CJK segmenters, Arabic folding, the literal toggle, per-language counts |
| `S04-08` | 0.4 | [`S04-08_versioned-source-substrate-and-lanes.md`](S04-08_versioned-source-substrate-and-lanes.md) | `RELEASE_0.4_GATE.md` row O | Q716, Q719, Q720, Q926, Q1003, Q1004, Q1005, Q1006, Q1007, Q1010, Q1011, Q1014, Q1015, Q1016, Q1018, Q1020 | src/versioned/ shared by wiki, law and OSM; one database file per lane, encrypted alike; lanes replace the scheduler mode; the Living sources view; budgets sized for the reference VM |
| `S04-09` | 0.4 | [`S04-09_wikipedia-lane-stream-and-hot-tier.md`](S04-09_wikipedia-lane-stream-and-hot-tier.md) | `RELEASE_0.4_GATE.md` row P | Q108, Q702, Q703, Q704, Q705, Q706, Q707, Q708, Q709, Q710, Q711, Q712, Q713, Q714, Q715, Q717, Q718, Q721, Q725, Q726, Q727, Q728, Q819 | Wikipedia as a lane: EventStreams metadata for every edit in all twelve editions, HOT full text, the top-bar toggle (default on), the wizard, disclosure |
| `S04-10` | 0.4 | [`S04-10_law-model-l0-defects-and-first-adapters.md`](S04-10_law-model-l0-defects-and-first-adapters.md) | `RELEASE_0.4_GATE.md` row Q | Q107, Q901, Q902, Q904, Q905, Q906, Q907, Q908, Q909, Q910, Q914, Q915, Q917, Q919, Q921, Q922, Q923, Q924, Q925, Q927 | The law metadata model (Akoma-Ntoso-lite), the L0 defects, translations as their own tracked documents, the first bulk adapters, the vetting board as the operator step |
| `S04-11` | 0.4 | [`S04-11_maps-equal-earth-and-borders.md`](S04-11_maps-equal-earth-and-borders.md) | `RELEASE_0.4_GATE.md` row R | Q801, Q802, Q803, Q826 | Equal Earth on all five map surfaces; Natural Earth 50m; OSM's border convention with CONTESTED both-claims rendering and a worldview toggle |
| `S04-12` | 0.4 | [`S04-12_sources-admission-institutions-and-splice.md`](S04-12_sources-admission-institutions-and-splice.md) | `RELEASE_0.4_GATE.md` row S | Q1101, Q1105, Q1106, Q1107, Q1108, Q1109, Q1110, Q1111, Q1112, Q1113, Q1114, Q1115, Q1116, Q1117, Q1118, Q1119, Q1156 | qualified => enabled and the hatch retired; the overlay editor; the institutions docket moves; the Stage B splice; the stratified round-robin |
| `S04-13` | 0.4 | [`S04-13_network-budgets-and-politeness.md`](S04-13_network-budgets-and-politeness.md) | `RELEASE_0.4_GATE.md` row T | Q1012, Q1013, Q1125, Q1126, Q1132, Q1148 | The per-process bandwidth budget under the governor; the persisted Crawl-delay next-allowed-at; the loopback rate limit; the airplane titles; the net-coach weights; weight digests |
| `S04-14` | 0.4 | [`S04-14_ui-i18n-and-small-rulings.md`](S04-14_ui-i18n-and-small-rulings.md) | `RELEASE_0.4_GATE.md` row U | Q1124, Q1130, Q1135, Q1139, Q1141, Q1149, Q1151, Q1152 | The 470-string i18n remainder; drop the religious calendars/eclipse feature; the encrypted click-through variant; the diagnostics.py split; the FUTURE_DEVELOPMENTS reality check; newsletter attach |
| `S04-15` | 0.4 | [`S04-15_release-0-4-board-and-verification-bar.md`](S04-15_release-0-4-board-and-verification-bar.md) | `RELEASE_0.4_GATE.md` row V | Q111, Q114, Q117, Q1128 | Rows D and E become bars, row F closes on the Chromium + click-through bar; release notes from shipped.csv; the allowlist as the operator step |
| `S05-01` | 0.5 | [`S05-01_advanced-search.md`](S05-01_advanced-search.md) | `RELEASE_0.5_GATE.md` row A | Q505, Q601, Q602, Q603, Q604, Q605, Q606, Q607, Q608, Q609, Q610, Q611, Q612, Q613, Q614, Q615, Q616, Q617, Q618 | One advanced-search UI: the builder, the FTS5 grammar extension, field search with match modes, NEAR, folding with an exact toggle, SymSpell did-you-mean, saved searches, permalinks, table view, relevance sort |
| `S05-02` | 0.5 | [`S05-02_alpha3-storage-half-and-language-codes.md`](S05-02_alpha3-storage-half-and-language-codes.md) | `RELEASE_0.5_GATE.md` row B | Q304, Q305 | ISO 3166-1 alpha-3 step 2: the store, the configs (scripted rewrite + test), the payload flip; ISO 639-2/3 in storage |
| `S05-03` | 0.5 | [`S05-03_entity-spine-wikidata-and-place.md`](S05-03_entity-spine-wikidata-and-place.md) | `RELEASE_0.5_GATE.md` row C | Q415, Q724, Q805, Q818, Q827 | Entities by QID (the same ladder), Wikidata items for entities, the Place entity, the gazetteer artifacts, names x12 |
| `S05-04` | 0.5 | [`S05-04_osm-lane-seed-first-country.md`](S05-04_osm-lane-seed-first-country.md) | `RELEASE_0.5_GATE.md` row D | Q106, Q806, Q807, Q808, Q809, Q810, Q811, Q814, Q815, Q817, Q820, Q822, Q823, Q824, Q825, Q828 | The OSM lane seeded: continent-level extracts, pyosmium [geo] extra, places + roads + buildings, the curated column set, SQLite, the tag-completeness view, notable Places as Articles, the local geocoder |
| `S05-05` | 0.5 | [`S05-05_osm-admin-boundary-artifacts.md`](S05-05_osm-admin-boundary-artifacts.md) | `RELEASE_0.5_GATE.md` row E | Q314, Q804, Q816 | OSM-derived admin-0/admin-1 artifacts keyed ISO 3166-2, rendered on all five surfaces; choropleths by alpha-3 and admin-1 |
| `S05-06` | 0.5 | [`S05-06_wikipedia-warm-tier-and-tail-walk.md`](S05-06_wikipedia-warm-tier-and-tail-walk.md) | `RELEASE_0.5_GATE.md` row F | Q701, Q722, Q1009 | WARM full text under the daily budget; the allpages tail walk (50 titles per request, serial) over the user's transport; analytics 4-5 |
| `S05-07` | 0.5 | [`S05-07_law-evolution-surface.md`](S05-07_law-evolution-surface.md) | `RELEASE_0.5_GATE.md` row G | Q916, Q918, Q920 | Point-in-time versions, the reader (version selector, side-by-side diff, provisions, permalinks, licence line), analytics 3-5, the multi-language switch; homogeneous with the wiki change surfaces |
| `S05-08` | 0.5 | [`S05-08_ai-translation-sweep-and-model-bench.md`](S05-08_ai-translation-sweep-and-model-bench.md) | `RELEASE_0.5_GATE.md` row H | Q405, Q513, Q1142, Q1143, Q1144 | The AI-coordinator sweep filling tentative translations; titles/summaries and on-demand full-article translation (never stored); the multi-model bench; the consented ollama.com browse |
| `S05-09` | 0.5 | [`S05-09_ui-shell-rings-handlers-and-themes.md`](S05-09_ui-shell-rings-handlers-and-themes.md) | `RELEASE_0.5_GATE.md` row I | Q1120, Q1121, Q1123, Q1127 | 'Rings, not gates' IA; the skipped-first-run default; the inline-handler retirement slice with its ratchet and the CSP; the theme cull to >= 10 with invariant #12 amended in the test |
| `S05-10` | 0.5 | [`S05-10_source-identity-feed-key-migration.md`](S05-10_source-identity-feed-key-migration.md) | `RELEASE_0.5_GATE.md` row J | Q1102 | A source is keyed on its FEED: the migration and its data-safety review across the alias dedup, the restore-merge joins, the overlay and the citations tally |
| `S05-11` | 0.5 | [`S05-11_investigators-desk-v1-carry.md`](S05-11_investigators-desk-v1-carry.md) | `RELEASE_0.5_GATE.md` row K | carried V1 content (no sheet IDs) | The approved V1 desk carried by Q105 = a: the claim workspace A1, the Conjunction Lens across verticals, the onboarding tour, signed-evidence export polish |
| `S06-01` | 0.6 | [`S06-01_osm-change-tracking-and-trends.md`](S06-01_osm-change-tracking-and-trends.md) | `RELEASE_0.6_GATE.md` row B | Q812, Q813 | Geofabrik daily diffs applied per extract, tag-level change rows, the adoption/openings/closures trend surfaces, the geography axis |
| `S06-02` | 0.6 | [`S06-02_law-breadth-to-the-coverage-floor.md`](S06-02_law-breadth-to-the-coverage-floor.md) | `RELEASE_0.6_GATE.md` row C | Q911, Q912, Q913, Q930, Q1146 | Breadth to every country in language_countries.yml: the per-language seed list verified live, treaties as INT, EuroVoc topic classification, the SKOS thesauri |
| `S06-03` | 0.6 | [`S06-03_wikipedia-coverage-report-and-located-data.md`](S06-03_wikipedia-coverage-report-and-located-data.md) | `RELEASE_0.6_GATE.md` row D | Q723 | The per-edition coverage report; every located datum in any indexed content linked onto the map (R17 step 4) |
| `S06-04` | 0.6 | [`S06-04_elections-and-climate-keyless.md`](S06-04_elections-and-climate-keyless.md) | `RELEASE_0.6_GATE.md` row A | Q1133, Q1134, Q1147, Q1153 | The V1 elections + climate verticals (keyless): IPCC AR6 SPMs, Open-Meteo temperature/precipitation, the statistics-agency directory, population-weighted indicators |
| `S06-05` | 0.6 | [`S06-05_help-body-x12.md`](S06-05_help-body-x12.md) | `RELEASE_0.6_GATE.md` row E | Q1122 | The Help body translated x12 (167,022 characters), staged 0.6 -> 0.8, AI-drafted and flagged for native review |
| `S07-01` | 0.7 | [`S07-01_medical-and-patents.md`](S07-01_medical-and-patents.md) | `RELEASE_0.7_GATE.md` row A | carried V1 content (no sheet IDs) | The V1 medical + patents verticals |
| `S07-02` | 0.7 | [`S07-02_osm-widen-countries-and-streets.md`](S07-02_osm-widen-countries-and-streets.md) | `RELEASE_0.7_GATE.md` row B | Q821 | More OSM countries; self-rendered vector streets at high zoom from the ingested roads |
| `S07-03` | 0.7 | [`S07-03_law-rest-of-world-and-subnational.md`](S07-03_law-rest-of-world-and-subnational.md) | `RELEASE_0.7_GATE.md` row C | Q903, Q928 | Laws: the rest of the world; subnational from 0.7 (Q903 CONFLICT flagged) |
| `S08-01` | 0.8 | [`S08-01_conflict-monitoring-and-360-dossier.md`](S08-01_conflict-monitoring-and-360-dossier.md) | `RELEASE_0.8_GATE.md` row A | carried V1 content (no sheet IDs) | The V1 conflict vertical + the 360-degree dossier |
| `S08-02` | 0.8 | [`S08-02_lane-completion-and-kpi-bars.md`](S08-02_lane-completion-and-kpi-bars.md) | `RELEASE_0.8_GATE.md` row B | Q1017 | The wiki/OSM/law lanes at their 0.8 breadth; KPI bars set from recorded values; Help x12 finished |
| `S09-01` | 0.9 | [`S09-01_beta-freeze-hardening-and-post-1-0-backlog.md`](S09-01_beta-freeze-hardening-and-post-1-0-backlog.md) | `RELEASE_0.9_GATE.md` row A–H | Q101, Q102, Q103, Q104, Q110, Q118, Q929, Q1019, Q1136, Q1138 | Beta 1 = 0.9.0: the freeze list, the public pre-release, the V1 section 8 exit bar, the security review, the Windows lane blocking, POST_1.0_BACKLOG.md |

## What is deliberately not here

- **A brief for a pending ⛔ question.** Q823 (ODbL), Q925 (the law adapter order), Q1009 (the storage round-2
  rows 3–6) and Q1113 (the compromised embassy platforms) were left blank; the briefs that reach them stop at
  the seam and say so (their §6).
- **A resolution of the two recorded CONFLICTS** — Q903 (subnational law: post-beta vs from 0.7) and
  Q1103/Q1104 (stoplist merges). The gate files say what ships around them until the maintainer picks.
- **Target dates or effort budgets.** Ruled out (Q110 = c, Q115 = c).
- **Back-filled rulings older than 2026-09-12** in the rulings index — recorded as a 0.4 docs item, not done.
