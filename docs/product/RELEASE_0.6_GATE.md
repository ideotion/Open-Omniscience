# Release gate — v0.6.0 · Elections + climate (keyless), plus breadth

> **PROVISIONAL ON THE V1 ROUND (`RC11` = b, 2026-09-29).** The maintainer re-opened all nine V1 rulings of
> 2026-09-07 (V1-1..V1-9): every row of this gate that cites a V1 ruling is provisional until the detailed V1 round
> is written and answered. V1-4 is already answered: PubMed BULK over the API («pubmed bulk prefered over API»).

**Status: OPEN — written 2026-09-15 from the answered roadmap sheet.** The checkable inventory for closing the
`0.6` cycle, written now because the maintainer ruled the gate files for 0.4–0.9 are written together from the
answered sheet ([`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
indexed in [`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md); Q112 = a, Q1204 = a).

**What is ruled here and what is not.** The theme and the two verticals are the approved V1 train's
(`V1_PATHWAY_2026-07-14.md` §3 with the four amendments of 2026-09-07: climate survives keyless without FIRMS
and OpenAQ; elections ships its CALENDAR as the 1.0 bar, rosters and poll Tier-2 post-1.0). The breadth rows
(B–D) are ruled by the sheet's release statements (Q106, Q107, Q108). Anything marked *proposed placement* is
the planning session's sequencing, not a ruling. No ⛔ question lands here; **Q823 (ODbL)** still governs
whether any OSM-derived row may leave the machine. **No target date** (Q110 = c).

**How a row closes:** as the `0.3`/`0.4` gates say — a named artifact; `not-measurable-here` when the sandbox
cannot measure the bar; the verification bar is Chromium + the maintainer's click-through (Q1128 = a).

**Entry.** `v0.5.0` tagged; the substrate and the lanes of 0.4–0.5 running; the OSM seed (0.5 row D) in the
tree.

---

## 1. The board

| # | Row | Owner | Origin | Status |
|---|---|---|---|---|
| A | Elections + climate, keyless — the approved verticals, plus the four docket rulings that feed them | session + operator (a networked directory build) | V1 §3/§4.3/§4.5 (ruled 2026-09-07) · Q1133, Q1134, Q1147, Q1153 · brief `S06-04` | **OPEN** |
| B | OSM change tracking: daily diffs applied, tag-level change rows, the trend surfaces 2–6, the geography axis | session + operator (daily diffs) | ruled (R16; Q106, Q812 🔒, Q813, Q815 · 2–6, Q816, Q824) · `S06-01` | **OPEN** |
| C | Laws: breadth to the language coverage floor — the seed list verified live, treaties as `INT`, EuroVoc topics, the SKOS thesauri | session + operator (live verification per source) | ruled (R15; Q107, Q911, Q912, Q913, Q930, Q1146, Q902 · d) · `S06-02` | **OPEN** |
| D | Wikipedia: the coverage report per edition; every located datum in any indexed content onto the map | session | ruled (R12, R17; Q108, Q723, Q819 · 4) · `S06-03` | **OPEN** |
| E | Help's body translated ×12 — the first tranche | session | ruled (Q1122 = b); *proposed staging* 0.6 → 0.8 · `S06-05` | **OPEN** |

**The exit.** `v0.6.0` is tagged when rows A–E are CLOSED on named artifacts (row E at its stated tranche),
the three i18n gates and the whole-tree guards are green, and the release notes carry the no-telemetry
re-check (Q111). The intake's exit rows are kept: the elections coverage floor at CALENDAR scope; laws tracked
in all twelve UI languages — or, per country, the gap stated; the OSM vintage stated on every map; a contested
border rendering as contested.
**One tag condition (R418).** No release tag is cut between the merge of the re-index PR that adds the `article_www_stamps` line to the restore registry in `src/backup/merge.py` (classified as not carried) and the merge of WAL's carry that follows it immediately, so no tagged build holds the table without its carry (R415).

---

## 2. The rows

### Row A — Elections + climate, keyless · V1 §4.3/§4.5 + Q1133, Q1134, Q1147, Q1153 · OPEN

**What it must demonstrate.** The elections vertical at the 2026-06-15 design's CALENDAR scope: sourced
calendars, **coverage floor = every language-covered country** (`configs/language_countries.yml`, the same floor
Q912 names for laws), the three-tier scheduled / window / projected date-confidence model, snap-election
freshness stated as a gap (V1-3 removed ElectionGuide). The climate vertical keyless: ONI · USGS quakes · OWID
· GISTEMP · NSIDC · GHCN-Daily, with FIRMS and OpenAQ **out**, not deferred (V1-1). From the sheet's docket
answers: IPCC AR6 Summaries for Policymakers first, `pypdf` acceptable (Q1133); the Open-Meteo layer —
temperature and precipitation first, 1991–2020 baseline, soil moisture later (Q1134 — an external, consented
call named in `SECURITY.md` and the popup hover per Q1001/Q1002); the official-statistics directory built by a
networked session with `news_url` per agency verified live, toward the ~152 agencies (Q1147); intensive
indicators population-weighted with the weighting disclosed on the figure (Q1153). **Closes when** the
elections calendar covers the floor with each country's tier stated (a coverage report as the artifact), the
climate series render from real fetches through the consent gate with their freshness diagnostics (V1's
per-vertical freshness), the AR6 and Open-Meteo lanes have registry entries and disclosure lines, and the
directory's verified count is recorded beside the total. **Operator:** the networked directory build; the
maintainer's own runs where the sandbox's egress refuses a host. Brief `S06-04`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC08.4` asked where register ruling
**G3** (the bloc-roster networked session — the registry stays EMPTY until it runs, because a partial roster
is more dangerous than none) lands. Blank, so its stated default is a labelled **ASSUMPTION: (a) — this row,
beside the statistics directory of G5 / Q1147.** It places one networked session producing several hundred
dated member rows under the external-artifact registry, on the same contract as this row's other networked
acquisitions (G2's elections session, §5 step 1). The empty-until-it-runs clause is the ruling's own and is
not weakened here. No new board row; the placement is what was assumed. Reversed by writing a letter at
`ANSWER RC08.4`.

**Progress 2026-11-13 (PR #1935, R661 + R662): the climate half has its surface; the row stays OPEN.** The six keyless
series now have one Climate main tab, a subtab each, fetched only through the consent gate and read back offline, with
source, licence, last fetch, gaps and parse diagnostics shown per series. A re-fetch keeps every vintage (R662). Still
owed for this half: a run against the REAL hosts (the sandbox's egress refuses most of them, so it is the maintainer's
run), and the AR6 and Open-Meteo lanes. The elections calendar and the statistics directory are untouched.

### Row B — OSM change tracking and the trend surfaces · ruled (Q106, Q812 🔒, Q813, Q815, Q816, Q824) · OPEN

**What it must demonstrate.** Geofabrik daily diffs per selected extract applied to the ingested classes; if
a diff older than the three-month retention is needed, re-baseline from a fresh extract and say so (Q812 🔒 =
a); tag-level change rows as defined in 0.5 (Q813); the trend surfaces in order — 2 adoption trends of each
metadata type over time · 3 openings and closures (objects appearing / disappearing, `disused:*`,
`shop=vacant`, `opening_hours` set to closed) · 4 brand and chain footprint by country · 5 contact-channel mix
· 6 data freshness by area (Q815 — the "never seen anywhere before" feature of R16, now visible); choropleths by
alpha-3 and admin-1 on Equal Earth + the ranked table in full, the vintage stated (Q816); the daily apply inside
the online consent, the per-country cost shown before selection (Q824). Every trend states "observed since
<date>" for the tracked window and the full-history planet's prior separately (Q814 = b), never blended.
**Closes when** a tracked country shows a real day-over-day tag change on the trend surface from an applied
diff (the diff's timestamp as the artifact), the re-baseline path is exercised on the fixture, the ranked table
is canonical beside every choropleth (Chromium-verified + click-through), and the measured daily diff cost for
one country is recorded. **Operator:** the daily apply on a real selection. Brief `S06-01`.

### Row C — Laws: breadth to the coverage floor · ruled (R15; Q107, Q911, Q912, Q913, Q930, Q1146, Q902) · OPEN

**What it must demonstrate.** Floor = every country in `language_countries.yml` (official / de-facto / regional
bases all count, labelled); order = sources serving many countries first (EU, OHADA, UN / WIPO), then by
population reached (Q912); **the per-language seed list is the 0.6 verification worklist — every row verified
live for reachability, robots, licence and format before it enters a catalogue** (Q911 = a; the maintainer's
note asking whether China is missing is answered in the ledger: `zh` is a UI locale, the seed's `zh` row
lists the national law database, Hong Kong, Taiwan, Macau and Singapore, and NPC is already in
`legal_sources.yml` — and the emphasis **"incorporate China and Chinese support throughout the app; this is
important"** is a standing ruling: this row reports zh coverage separately); treaties and international
instruments in 0.6 as jurisdiction `INT` — the UN Treaty Collection in six UI languages at once, WIPO Lex
(Q930, Q902 · d); EuroVoc concepts (en/fr/de/es/pt) reached in the other seven languages through Wikidata's
EuroVoc-ID property and the keyword rings, assigned by rules, ≈ where the LLM proposes (Q913 — P5437 is FROM
MEMORY in the sheet and must be confirmed); the SKOS family adopted for topic tagging — EuroVoc + the UNESCO
Thesaurus + AGROVOC + IPTC Media Topics (Q1146, registry-tracked); the adapters follow the order Q925 ⛔
settles — **still PENDING** if unruled, in which case this row builds breadth through whichever adapters exist
and records the ones it could not start. **Closes when** a coverage report lists every floor country with its
state (tracked / verified-not-yet-tracked / unverified / no eligible source) and the twelve-language tally,
the `INT` lane ingests one treaty in six languages aligned by identity (Q908), and the topic assignment is
measured on a labelled sample with the ≈ share stated. **Operator:** the live verification of each seed row
(the allowlist of 0.4 row V or the maintainer's machine). Brief `S06-02`.

### Row D — Wikipedia coverage and located data · ruled (Q108, Q723, Q819) · OPEN

**What it must demonstrate.** Per edition: pages seen / edition total (from `siteinfo` statistics), full-text
share, last event time, gap history — in the Living sources view and the diagnostics bundle (Q723); R17 step 4:
free-text addresses in articles and wiki infoboxes located through the local OSM address index of the user's
countries (Q819, Q820), disclosed as "addresses outside your OSM countries are not located". **Closes when** the
report renders for all twelve editions from the lane's own counters (the numbers read back from the bundle
member), and a located address from a wiki infobox appears on the map with its provenance in the hover.
Brief `S06-03`.

### Row E — Help's body ×12, the first tranche · ruled (Q1122 = b); *proposed staging* · OPEN

**What it must demonstrate.** The 167,022-character Help body translated ×12 (~2 M characters), AI-drafted
and flagged for native review like the GUI-gallery precedent, staged across 0.6 → 0.8 (*proposed*: the TEN
Help documents — `_DOCS` in `src/api/main.py:2558` lists ten slugs, grep-verified 2026-09-15; this row said
"eight" until then — in three tranches, the most-visited first, each tranche's coverage stated in the document's own
banner per the recorded mixed-language-document lesson). **Closes when** the tranche's documents pass the
three i18n gates run separately and a live locale switch shows them (the recorded "keys exist ≠ ×12" lesson),
with the translated-of-total figure on each document. Brief `S06-05`.

---

## 3. Amendment log

| Date | Change | Source |
|---|---|---|
| 2026-09-15 | Board created from the answered roadmap sheet (Q112 = a); the V1 verticals carried with their 2026-09-07 amendments; rows B–D from Q106/Q107/Q108's release statements | maintainer (answer sheet) · rows written by the session |
| 2026-09-15 | **Premise correction from the brief-writing pass (row E):** the Help documents are TEN, not eight (`_DOCS` in `src/api/main.py:2558`: user-manual, quickstart, ethics, governance, security, design, roadmap, architecture, contributing, changes). The 167,022-character figure is the 2026-09-08 visual audit's measurement of the RENDERED Help tab (`docs/audit/ui-visual-2026-09-08/findings.csv:127`); the documents' source is larger (`docs/USER_MANUAL.md` alone is 180,594 bytes), so the ~2 M-character ×12 estimate is a floor, to be re-measured per tranche. The serving seam exists (`docs/i18n/<lang>/<file>`, one translated draft: `docs/i18n/fr/QUICKSTART.md`). No ruling changed. | session (`S06-05` §2, hand-verified) |
| 2026-09-15 | **The 2026-09-06 register's 65 answers (rulings artifact, 15:02–16:00Z) — effects on this board:** row A — G2 `default` AUTHORISES the networked elections-acquisition session (§5 step 1 of `S06-04`) and G3 `default` the bloc-roster session (registry EMPTY until it runs; placement proposed here, `RC08.4`); G4 adds operator-curated prediction extraction from a suggested list; G7 adds the signal-keywords layer as toggleable and OFF; G5 consistent with Q1147. G6 re-states the poll idea (raw poll data, verbatim questions and results, orienting-question detection) with the version left blank — `RC12` asks it; V1-8's poll placement is in tension; not placed here by the session. | maintainer (the register, 2026-09-15) · reconciled by the session |
| 2026-09-15 | **The RC confirmation round came back UNANSWERED — 0 of 22 `ANSWER` lines carry a letter — processed per its own §0.** Effect on this board: row A — `RC08.4` ASSUMPTION (a), register ruling G3's bloc-roster networked session is placed here beside the statistics directory, the registry staying EMPTY until it runs. Reversible by writing a letter. **No row changed status.** | maintainer (the round, left blank) · §0's blank rules applied by the session |
| 2026-09-29 | **`RC11` = b: the V1 round re-opens all nine rulings**, so the rows here that cite V1-1..V1-9 are provisional (the banner above); V1-4 answered, PubMed bulk. | maintainer (project chat, 2026-09-29 19:55 UTC) · recorded by the session |
| 2026-11-04 | **Row E tranche plan, measured (E1, `S06-05` S1; PROPOSED placement per Q1122 = b, not a ruling: the maintainer may move membership).** Method: `len(text)` in characters of each served Help document on main `5f07a389f`, ten slugs from `_DOCS`, against the eleven non-English locales of `src/static/locales/` (ar bn de es fr hi id ja pt ru zh; English is the authoritative text). Sizes: user-manual 225,673 · quickstart 24,620 · ethics 27,844 · governance 4,931 · security 80,666 · design 57,726 · roadmap 97,612 · architecture 24,987 · contributing 12,062 · changes 194,108; total 750,229 characters, so the owed body is 750,229 × 11 = 8,252,519 characters (the earlier ~2 M figure, 167,022 × 12, was the RENDERED Help tab and understates the owed body 4.1 times: 2,004,264 against 8,252,519). **Tranche 1 (0.6):** user-manual + quickstart = 250,293 characters × 11 = 2,753,223 (22 of the 110 document-locale pairs). **Tranche 2 (by 0.7):** governance, ethics, security, contributing, architecture = 150,490 × 11 = 1,655,390 (55 pairs; short, user-facing and safety-relevant first). **Tranche 3 (by 0.8):** design, roadmap, changes = 349,446 × 11 = 3,843,906 (33 pairs; the plan and release-by-release log, read least). Today: 0 of 110 pairs COMPLETE; one PARTIAL draft (`docs/i18n/fr/QUICKSTART.md`: 8 headings against the English 17, served but never counted). Drafting is local-model-only and no local model is reachable in the build container, so drafting the 22 tranche-1 pairs is an OPERATOR step (the maintainer's machine); each draft's banner flags it for native review, never a merge condition. The guard is `tests/test_help_docs_translated.py` (skeleton equality per pair, exact PARTIAL listing, a per-tranche floor that may only rise, a truthful `X-OO-Doc-Lang`, mutation-checked). | session (E1, measured) |
| 2026-11-04 | **R418: a tag-timing condition on the exit.** The stage-2 stamp table `article_www_stamps` (R415) lands in two merges, the re-index PR with one registry line in `src/backup/merge.py` (cross-owner touch granted) and WAL's carry straight after; no release tag falls between them. | the coordinator session (R418) · recorded by Plan |
| 2026-11-13 | **Row E, tranche 1 drafted (R677): 22 of 22 pairs COMPLETE.** `docs/i18n/<lang>/USER_MANUAL.md` and `QUICKSTART.md` for ar bn de es fr hi id ja pt ru zh, AI-drafted by Opus workers in a build session (R677 replaces the "local model only" reading of 2026-11-04) from the English refreshed against the code in #1944. Each opens with a banner comment stating it is AI-drafted, not native-reviewed, and its coverage (124 of 124 and 17 of 17 headings); each passes `tests/test_help_docs_translated.py` (skeleton, banner, FLOOR[1] = 22, PARTIAL now empty because the 8-heading fr quick start was replaced); fenced blocks, inline code and link targets are byte-identical to the English, and in-page anchors are rewritten to the translated headings. A fidelity read compared, per language, the quick start, §1, §3.6c, §3.6d, §5.6 and three random subsections with the English; its findings (English-style digit separators in es/pt/fr/de/id/ru, "terms" read as terminology in bn/id/ja, a fail-closed rendering in es, one word in ar) were fixed before merge. Listed in `docs/product/NATIVE_REVIEW_QUEUE.md` (Help documents). **Row E stays OPEN** until a live locale switch shows them (this row's own close condition). | session (Lane J) |

---

## 4. Not in this gate

- **More OSM countries and self-rendered streets** — 0.7 (Q106; Q821 *proposed placement*).
- **Laws: the rest of the world and subnational** — 0.7–0.8 (Q107; Q903 CONFLICT recorded).
- **Case law, bills and drafts** — post-beta (Q929, Q902 note; `POST_1.0_BACKLOG.md` at 0.9, Q118).
- **Anything that lets OSM-derived rows leave the machine** — waits on Q823 ⛔.
- **The version flip to `0.6.0`.** It follows the `v0.5.0` tag, mechanically.
