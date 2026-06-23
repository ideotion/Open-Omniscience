# AUTONOMOUS SESSION BRIEF — 2026-06-23 (UNIFIED)

**This is the single opening prompt for a fully autonomous, unsupervised build session.** It
merges two parallel tracks into one: (A) the **field‑test keyword‑reduction + live‑corpus loop**
(the maintainer's "address the ~400k keywords for good"), and (B) the **full remaining V0.1‑alpha
inventory** (everything still open in the 0.09 cycle toward the tag). It is the consolidated,
prioritised, evidence‑cited synthesis of `CLAUDE.md` (the live ledger),
`docs/product/RELEASE_0.1_RC_GATE.md` (the canonical gate), `BACKLOG_GROUPED.md`,
`FUTURE_DEVELOPMENTS.md`, and the 2026‑06‑21/22/23 field‑test exports. It does **not** restate the
non‑negotiables — it assumes them.

---

## 0. HOW TO WORK (READ FIRST)

- **Read `CLAUDE.md` in full before anything.** It is the single ledger of every maintainer ruling
  and all non‑negotiables. Record every new ruling you derive HERE → into `CLAUDE.md` in the same turn
  (THE PROTOCOL). Update the RC‑gate rows you close.
- **Fully autonomous & unsupervised. Ask the maintainer NOTHING.** Make every decision yourself; pick
  the most honest, conservative default; record the choice. The ONLY carve‑out is a genuinely NEW
  ethics/irreversible surface not covered here or in the ledger. The live‑corpus loop (§2) depends on a
  fresh log the maintainer produces between sessions — **never block waiting for it**: do all buildable
  work, and run the log‑dependent steps if/when the export appears in the thread.
- **Working mode:** one PR per slice, **small + additive**, **draft onto `0.09`**, CI subscribed.
  `git fetch origin 0.09` immediately before cutting each branch (0.09 goes stale within minutes). The
  maintainer merges everything; nothing self‑merges. If the harness pins you to ONE branch, stack
  commits on it (the PR becomes a batch — fine). A push printing "[new branch]" means the previous PR
  merged → open a NEW draft PR onto 0.09.
- **Non‑negotiables bind even under "ship it" pressure:** local‑first / loopback‑only; the airplane‑mode
  socket guard; robots fail‑closed; **no composite scores** (`assert_no_score_fields`); **caveats
  visible by default**; the ONE informed‑consent popup on every offline→online transition;
  honesty‑by‑construction (gaps = `None` never zero; producers never averaged; deduced ≠ confirmed). A
  redesign may **never** drop a disclosure or a working tool — the **Desk lesson**: make it unreachable,
  gate it with an absorption test, never silently delete. **Never fabricate data** — FRED ids, per‑OS
  checksums, dates, or "native‑reviewed" translations.
- **Frontend is browser‑unverifiable here (fork‑3):** ship conservative + flagged "browser‑unverified,
  needs click‑through"; `node --check` every `<script>` touched; extend `tests/test_repo_invariants.py`
  (incl. `test_ui_invariants`); keep i18n at 100% (`scripts/i18n_report.py --min 100`). After ANY
  frontend/wiring change run the FULL `test_repo_invariants` (a verbatim‑asserted line can break even
  when your feature's own test passes).
- **Verify with the real toolchain each commit:** `ruff check --select=F,B --extend-ignore=B008`,
  `mypy src/` (≤ baseline 127), `--min 100`, `node --check`, targeted tests + full `test_repo_invariants`.
  The sandbox is py3.11 / core‑only for some extras; the full pytest + 3‑OS matrix run in CI — drive CI green.
- **Sequence: P0 reliability (§3) before features, always** — the app holds a real ~27k‑article corpus
  the maintainer cares about. The keyword‑reduction loop (§1/§2) is the maintainer's named priority and
  runs in parallel with the reliability work (different files), so both progress.

### PROCESS FLAGS (binding)
- **NEVER force‑push the shared default branch `0.09`.** It was history‑rewritten during this period and
  **broke every user's `git pull` update**. The `bootstrap.sh` fix in PR #446 self‑recovers a diverged
  checkout, but the rule stands: only fast‑forward `0.09`; rewriting shared history is forbidden.

### Open PRs to reconcile at session start (CHECK BOTH FIRST)
- **PR #446** — branch `claude/magical-brown-49m9nd` (the keyword/field‑test track): three stacked fixes —
  (1) **keyword reduction**: vendored **stopwords‑iso** (MIT) language‑scoped lists for the 14 no_stoplist
  langs (`configs/stopwords_iso/*.txt` + `src/services/stopwords.py:scoped_stopwords` + `STOPWORDS_ISO_AS_OF`
  + `scripts/build_stopwords.py` + `tests/test_stopwords_iso.py`); (2) **bootstrap.sh** recovers from a
  force‑updated/diverged 0.09 (ff → `reset --hard FETCH_HEAD` on a clean checkout, guidance on a dirty one);
  (3) **install.sh** `pip_install` redirects TMPDIR off `/tmp` (Qubes RAM‑tmpfs disk‑full) + classifies
  disk‑full vs network failures (`tests/test_installer.py`).
- **PR #445** — branch `claude/trusting-maxwell-p7y2g8` (the V0.1/UI track): Governments tab + home‑card
  click diagnostics + all‑diagnostics ZIP + i18n keying + the **flip‑card redesign** (front/back,
  equal‑size, family‑themed, caveat‑on‑back, "Open corpus ↗" in a new window).
- For each: `git fetch`; **if the branch is gone it merged** (open a fresh branch off the new 0.09 for
  follow‑ups). If still open and CI is red or there are review comments, investigate + fix small/confident
  issues; don't rework architecture without cause.

### State as of this brief (what just shipped, so you don't redo it)
PR #445 shipped: the **Governments** tab (rename of World Law + per‑country World‑Bank data + a choropleth
Map subtab + the Law subtab); the **home‑card click diagnostic** (`GET /api/diagnostics/home-cards`) + the
briefing `CACHE_VERSION` bump (1→2) so existing installs serve cards carrying `article_ids`; the
**all‑diagnostics ZIP** (`GET /api/diagnostics/all`) + the diagnostics buttons shed the "Download " prefix;
the **i18n keying** of Governments/Sources‑facets/strata; the **flip‑card** Leads. All browser‑unverified
(fork‑3) — a human click‑through is owed. PR #446 shipped the stopwords‑iso reduction + the
bootstrap/install resilience (verify it merged + landed).

---

## 1. FIRST ACTIONS (session start — do before anything else)

1. **Reconcile PR #446 and PR #445** (status above): merged? CI green? review comments? Resolve anything
   small/confident; re‑cut a fresh branch off the latest `0.09` for further work.
2. **The live‑corpus keyword loop (don't block on it).** The maintainer is mid‑restore (see §2's "between
   sessions"): a fresh install, the saved data dir placed back, unlock, **update to latest 0.09 → Settings
   → Diagnostics → "Clean up keywords (re‑index, then prune)" → download a fresh keyword‑engine report +
   keyword log.** When that export appears: compare `composition.keywords` and `language_coverage` vs the
   2026‑06‑23 baseline (**406,723 keywords**); confirm the no_stoplist langs now read **"functional"** and
   their counts dropped; quantify the reduction via `composition.mention_distribution`. Until it appears,
   proceed with everything else.
3. **Remind the maintainer (once, in the PR/thread) to run the baseline‑tag backfill** — `tag_coverage` is
   **0%**, it has never been run (Settings → Keywords → "Apply baseline tags", or `POST
   /api/insights/keyword-tags/backfill`). Also confirm the "Clean up keywords" run happened.
4. **Kick the corpus‑driven ring round** the moment a fresh keyword log exists (see §2.4) — this is the
   single biggest lever on `translation_coverage` (13.4% today).

---

## 2. FIELD‑TEST CONTINUATION — the ~400k‑keyword reduction + perf (MAINTAINER PRIORITY)

Field‑tested on a Qubes disposable VM, real corpus: **~27,303 articles / 406,723 keywords / 1.8M mentions
/ 3,202 sources.** The maintainer wants to "address the ~400k keywords for good." The honest diagnosis
(2026‑06‑23 logs) — the count is mostly LEGITIMATE long tail, so this is junk‑REMOVAL, never a cap
(the no‑arbitrary‑cap policy holds):

| Bucket | ~count | Verdict / lever |
|---|---|---|
| single‑article **hapax** | 287,845 (71%) | **LEGITIMATE multilingual long tail — policy‑protected, NO cap.** Leave it. |
| function‑word leakage (space‑segmented no_stoplist: tr/ro/uk/fi/ur/cs/ca/sk/et/hi/vi/bn/fa/sw) | ~88k | Those langs are **ALREADY promoted to managed in current 0.09** (the 2026‑06‑23 report was an OUTDATED build), so **update→re‑index→prune already drops most of this**; **PR #446** adds the short‑function‑word tail via stopwords‑iso. Confirm it landed in the fresh log. |
| **digit‑heavy code tokens** (`A-10C`, `1h15`) | ~35k | **NOT yet filtered at extraction** (`drop_numeric` only hides pure‑digit at query time). **Candidate next lever (§2.5).** Needs a false‑positive‑safe rule (must NOT eat `A-10`/`F-18`/`COVID-19`/`G7`). |
| **"?" unknown‑language** = English gov‑newsletter boilerplate (`govdelivery`, `gd_combo_table`) + undetected‑language English | ~30k | Needs **language detection** for un‑languaged articles + **.eml boilerplate filtering**. **NOT built (§2.6).** |
| zero‑mention **orphans** | only 110 | Prune alone is negligible now (corpus isn't markup‑polluted). |

`translation_coverage` **13.4%** (550 rings) → needs ring generation (§2.4). `tag_coverage` **0%** →
baseline‑tag backfill has NEVER been run (§1.3).

### 2.1 Confirm the reduction landed (when the fresh log arrives)
Diff the fresh keyword‑engine report + keyword log against the 406,723 baseline. Expected: no_stoplist
langs → "functional", their keyword counts drop, the function‑word bucket shrinks. Quantify via
`composition.mention_distribution`. Record the measured before→after in `CLAUDE.md`.

### 2.2 stopwords‑iso tail (PR #446) — verify + extend
Confirm the vendored MIT lists landed and apply at query time (`scoped_stopwords`, language‑scoped so a
content word in one language isn't killed in another). If the fresh log shows residual short function
words in a managed lang, extend the curated `_EXTRA_STOPWORD_TEXT` batch (the established collision‑safe
rule: distinct scripts are collision‑free; Latin additions length≥4 / accented‑only / hand‑excluded for
es/it/pt/en/de/nl clashes). `STOPWORDS_ISO_AS_OF` is registry‑tracked (freshness test).

### 2.3 Run the cleanup on the live corpus (maintainer's button, your analysis)
The reduction workflow is: **update → re‑index (drains markup + applies the now‑managed langs) → prune
(GCs the now‑zero‑mention tokens)** — the one‑click "Clean up keywords (re‑index, then prune)". You don't
run it (no live corpus in‑sandbox); you read the resulting log and decide the next lever.

### 2.4 Corpus‑driven ring generation round (the `translation_coverage` lever — NETWORKED machine)
From the keyword log's **`ring_candidates`** cross‑language gap digest:
`scripts/generate_wikidata_rings.py --from-log <log> --top N` (Wikidata 403s in‑sandbox → a networked box).
**VET the output** (~6% first‑hit‑wrong — drop journals/bands/place‑names/companies/films/homographs/
Wikidata meta‑classes, exactly the 35 the last batch dropped), commit `configs/keyword_rings_generated.yml`
(read alongside the curated file, curated wins on id clash), re‑measure `translation_coverage`. Target:
rings 550→~2000, supergroups 77→~200 as the ring set fills. Consider an **in‑app consented Wikidata
importer** (airplane‑gated, guarded factory, task‑manager job, candidates REVIEWED not auto‑merged) so the
maintainer can drive it without a CLI.

### 2.5 NEXT LEVER — digit‑heavy extraction filter (~35k) [you own extraction now — the parallel session is merged in]
Add a **false‑positive‑safe** rule at the ONE extraction chokepoint (`src/analytics/extract.py`, alongside
`strip_markup`) to drop alphanumeric code tokens like `A-10C`/`1h15`/timecodes while KEEPING real terms
(`A-10`, `F-18`, `COVID-19`, `G7`, `Boeing 747`, `5G`). Build it conservatively (a token that is mostly
digits with embedded letters in a non‑acronym shape), test it hard against a curated keep/drop fixture
(the keyword self‑test harness pattern), and only ship when the fixture proves no real term is lost.
Re‑index drains the old ones.

### 2.6 NEXT LEVER — the "?" English‑boilerplate / language‑detection fix (~30k)
Two parts: (a) **detect language** for articles stored as unknown/"?" (esp. `.eml` newsletters) — a
local, offline detector (e.g. a bundled n‑gram/`langdetect`‑class lib, no network) so English boilerplate
is classified `en` and runs through the EN stoplist; (b) **filter newsletter‑template boilerplate** tokens
(`govdelivery`, `gd_combo_table`, …) — extend the `.eml` `_strip_html`/extraction cleanup to drop known
template artefacts (evidence‑based denylist, dated). Honesty: never guess a language with low confidence
(leave it "?" rather than mislabel); re‑index applies it forward.

### 2.7 Perf hotspots (live benchmark — will improve as the keyword count drops)
`layered_graph_keyword` 11.6s · `supergroups` 7.1s · `trending_windows` 7.4s · `trending` 4.5s ·
`associations` 3.8s. The covering index `ix_mention_date_keyword` targets `trending_windows`; **if still
slow on the real DB after update+re‑index, the per‑day rollup is the next lever — MEASURE EXPLAIN/timing
on the live encrypted DB FIRST; never add a drift surface speculatively.** Persisted columnar is gated on
the httpfs crypto‑extension packaging decision (§12). Re‑run the benchmark after the cleanup to confirm.

### 2.8 The maintainer's between‑session process (context, so your guidance fits)
They could not restart the DispVM (shutdown‑only), so they **saved the whole data dir**
(`~/.local/share/open-omniscience` — corpus.db + keys + `osm_regions/` ~80 GB maps + `wiki_dumps/`) to
external storage and will do a **FRESH install, place the dir back at the same path, and unlock with their
passphrase (no re‑import).** This is exactly why `bootstrap.sh`/`install.sh` resilience (PR #446) and the
"reinstall never touches data_dir" guarantee matter — confirm both hold, and that update→clean‑up works on
a restored dir.

---

## 3. P0 — RELIABILITY & DATA‑INTEGRITY (build tier — always first)

### 3.1 Single‑writer gate — re‑verify under live parallel load (standing keystone #1)
The 2026‑06‑22 audit found the 149 `database is locked` errors PREDATE the `do_orm_execute` gate fix
(#384) and every audited path is gated + has `busy_timeout=30000`. But the corpus runs **50 parallel
collect workers** against one encrypted writer. **Re‑audit** that EVERY write goes through the gate
(ingest sub‑writes `index_article`/links/when‑where‑who; post‑pass housekeeping: auto‑reindex top‑up,
briefing refresh, auto‑on‑ingest AI, stats vintages, columnar maintenance, FTS triggers, VACUUM/ANALYZE).
Add an **ingest‑under‑parallel‑load** test (N articles across many workers → ZERO dropped keyword/link/date
rows). Defence‑in‑depth (best‑effort sub‑writes retry via `run_write_with_retry`) already shipped — confirm
no path bypasses it.

### 3.2 Backups & restore — the LARGE redesign ("entirely reliable or it should not exist")
- **File‑member backup for wiki dumps + OSM maps + Ollama models inside the additive restore.** The
  large‑data **folder backup** streams these AS‑IS to a server‑side dir + restores additively (DONE). The
  MISSING piece is the **additive‑restore MERGE that places FILE members** (bit‑identical dedup, never
  overwrite a differing local file) so the *encrypted oo‑backup‑2 artifact* + the *selective tickboxes* can
  carry them (today wiki/maps/models say "coming soon — folder backup"). Reuse `ollama_models.py`'s
  checksum‑dedup pattern.
- **Restore as a task‑manager JOB** (P0‑2: a 236 s synchronous preview/restore blocks the request) — pausable,
  visible, progress both directions.
- **Unify the include/restore selection UI** (fold the separate `.oomodels` models backup into the one flow);
  **encryption‑as‑an‑in‑flow EXPORT option**; **direct‑import‑with‑summary**.
- **State‑into‑DB migrations (D1/D4):** settings / annotations / event‑imports / agenda subs → tables,
  imported once, artifact member list updated.
- Acceptance: torture suite stays 10/10; a (stub) dump file restores bit‑identically + additively; restore
  never overwrites a differing local file; the job is visible + pausable; i18n 100%.

---

## 4. THE RELEASE GATE (the path to the V0.1 tag — maintainer pivot, ruling #1)

`docs/product/RELEASE_0.1_RC_GATE.md` is authoritative; the tag is earned the day **every RC‑BLOCKING row
reads ✅** (ruling #2 HOLDS the 0.0.9→0.1 flip until then).

### 4.1 Final claim‑sweep + docs↔app reciprocity (RC‑BLOCKING, §5)
USER_MANUAL chapters: backup/restore + encryption; running‑over‑Tor; task‑manager + agenda; Governments;
the FOOS naming note; the flip‑card Leads. **Two‑direction diff**: every feature sentence in
README/USER_MANUAL/QUICKSTART/ETHICS resolves to a working surface AND every shipped surface is documented
(06‑audit method). ARCHITECTURE/DESIGN refreshed for backup‑v2 + SQLCipher + the data‑architecture seams +
Governments.

### 4.2 Release mechanics (RC‑BLOCKING, §2) — plumbing now, flip last
Version flip 0.0.9→0.1 (single‑source plumbing DONE + guarded) **only when every RC‑BLOCKING row is ✅**
(ruling #2) + CHANGES.md 0.0.9→0.1 + release notes; FOOS suffix stays. `release.yml` end‑to‑end on a real
tag (held until the flip). Debian install path verified end‑to‑end (win/mac POST, ruling #5). Refactor the
remaining allowed HTTP importers onto the ONE `guarded_session` factory (the socket‑importer ratchet pins
them meanwhile).

### 4.3 The FINAL security review pass (RC‑BLOCKING, §4 — the LAST batch before tagging)
A fresh full review over the RC diff with the 06‑audit method (agents + **hand‑verification of every
critical** — the false‑positive lesson). Plus the audit tail: inline‑handler retirement (§11), a11y batch,
"stays on this machine" exact wording (default applied — finalise).

---

## 5. THE FLAGSHIP UI SURFACES (RC‑BLOCKING centerpieces + the maintainer's recent asks)

### 5.1 Source‑tags everywhere + the world‑map "Sources by location" bubble layer (maintainer 2026‑06‑22)
- **Filter sources by their tags throughout** — wherever sources appear as a list: the analysis/advanced
  search (`anParams` must send `tags`; the backend `_structured_filters` ALREADY filters `Source.tags` via
  `?tags=` — mostly frontend wiring + a multi‑select tag control reusing `/api/sources/facets`), the Library
  tab, search results.
- **World‑map "Sources by location" subtab**: circles ∝ source count per location, with a **country | IP**
  toggle (IP mode fills the large "no country" gap). Data exists: `queries.source_country_counts` +
  `queries.server_locations` (per‑geolocated‑IP, `distinct_sources` + lat/lon). Add
  `GET /api/insights/source-locations?mode=country|ip`; render via `ooMap` `overlayPoints`. Honesty: "no
  country" bucketed + stated; IP geo carries the CDN‑edge/anycast/approximate caveats; no score.

### 5.2 The ONE corpora system / two‑windows consolidation (RC‑BLOCKING flagship)
`#an` is the multi‑document spawned‑tab workspace; `#corpus-win` retired (THEME‑3). REMAINING: the
remaining entry points (commodity/date‑keyword pivots); **surface the card CAVEAT inside the analysis
window** the flip‑card "Open corpus" opens (the 2026‑06‑23 flip nicety); TIME‑SCOPE on the non‑trend
sub‑tabs; one‑click ethical ingestion of linked pages ("the sources' sources").

### 5.3 The 3D keyword explorer (maintainer FLAGSHIP, ruled 2026‑06‑16 — NOT built)
Hand‑rolled **canvas 2.5D / CSS‑3D, NO Three.js/WebGL** (ruling A), bundled loopback‑only. Unify
Keywords / Families / Super‑groups into ONE continuous layered hierarchy (LOD drill, bounded — 60k+ can't
all render). Honest encodings each a real measured quantity with a stated method (size ∝ mention/spread
with n; trend = windowed rise/fall + early‑corpus caveat + the n<10→bar rule; language spread = distinct
languages; territory spread = distinct countries) — **never a composite "importance score."** True
Fullscreen API + visible exit; keep the tabular Families/Groups + word‑cloud as redundant a11y paths; the
deterministic mind‑map rules carry into the layered form.

### 5.4 Home → dashboard / helicopter view (extends invariant #19)
Top **ooChart** graphs; a **synthesized‑Leads carousel** (pausable + keyboard a11y, never hides a caveat
behind rotation; "synthesized" = LOCAL analytic synthesis, NEVER LLM — zero‑network Home); **dynamic
data‑driven sections** (a commodity's price graph surfaces WHEN its family trends); **most‑recent by tag**.
Everything redundant by design (#8); honest "top" ordering, never a hidden score; fail‑safe empty state.

### 5.5 Insights rework + the wider Trends redesign
Remove the Insights search bar (gated on the omnibar fully absorbing term‑exploration — Desk lesson); the
cards become canonical here; the three‑window Trends + top‑5 graphs slice shipped — finish the redesign.

### 5.6 Governments tab follow‑ups (this session's new tab)
A **Compare** subtab (multi‑country side‑by‑side); a **bundled offline indicator snapshot** (networked WB
fetch — 403 in‑sandbox; fetch‑on‑demand works meanwhile); per‑country flag/name polish; key the new
English‑fallback strings ×12; **auto‑load** the standard indicators on a freshness cadence in the markets
pass, consented/airplane‑gated.

### 5.7 World map + markets + charts cleanups
World map: **browser‑verified deletion‑cleanup** of the unreachable temporal‑map functions; **embed ooMap
on When/Where + Insights**; per‑slide perf (update only the signals layer). Markets: unify the indices CARDS
onto the commodity `dashChartSvg`; a commodities **tag facet**; reclassify **S&P 500 as an INDEX**; expand
feeds (rare earths, LNG, cereals, sugar, gas). Charts: commodity‑card enlarge → `ooChart` (n<10→bar). The
`openLinkPreview` ANYWHERE sweep (invariant #6): reader source↗, search rows, markets/law/wiki tabs.

---

## 6. KEYWORD / ANALYTICS DEPTH (beyond the §2 reduction loop)

- **Families↔rings↔supergroups translation binding in the UI** (Phase 3 frontend — original→translation
  through the family/group views; backend `equivalence.translate_term` exists).
- **Item AC keyword EXPLORER subtab:** the per‑keyword TAG add/remove UI (the S3a write endpoints exist;
  S3b shipped explore+hide+backfill); S1b stoplists → data files; S4 in‑app analyzer‑proposal review.
- **Sentiment:** surface the stored `sentiment_score`/`label` in the reader/cards/lists (populated on
  re‑index; the UI still reads on‑demand framing); a multilingual path beyond English VADER (per‑language
  lexicons / a local model) — honest gaps for unscored languages, never a fabricated neutral.
- **Manipulation‑pattern cards** (ruling #13, AI‑free is the asset): build the remaining six
  (headline‑body‑mismatch, outrage‑intensity, flood/bury, manufactured‑emergence, event‑timed‑op;
  astroturf/copypasta partly covered by echo_chamber). Each a new producer feeding an existing bucket,
  components never a blend, innocent‑explanation beside the pattern, "absence of a flag ≠ absence of
  manipulation." Spine in `FUTURE_DEVELOPMENTS.md`.

---

## 7. AGENDA / CALENDARS / ASTRONOMY (RC‑BLOCKING content batch — "all and everything accessible")

- **Deduced events as FIRST‑CLASS agenda events** with ⊞ keyword links (parity with moon/season glyphs);
  moons/seasons first‑class in day‑detail + all views; **El Niño** episodes as month‑span banners.
- **World calendars:** Islamic = computed tabular dates + the honest ±1‑day moon‑sighting caveat;
  Hindu/Buddhist = sourced published tables (NEVER a fabricated panchanga). **Religious‑calendar / eclipse‑
  canon dates: the maintainer PROVIDES them (ruling #9) — never fabricate; mark the TODO.**
- **Eclipse‑canon astronomy slice** (bundled public canon + provenance + method/accuracy); **play speeds
  0.05–16× log‑stepped**; **preloaded worldwide bank holidays**.
- **Massively expand** the calendars (elections, summits, central banks, parliaments, courts, UN days,
  fiscal dates), every entry sourced, movable dates marked, subscribe‑default off‑flood.
- **World‑law auto‑scrape (Governments→Law):** the per‑pass `auto_track_due` shipped; REMAINING = the
  per‑country legal‑source catalog for every UI language (a languages→countries map + curated sourced
  portals — large hand‑curation; today ~30 mostly anglophone/EU) + the Law subtab's content‑first revamp.

---

## 8. LLM / AI DEPTH (mostly POST; a few quick wins)

- **AI lens UI** beside the trusted keywords (backend `ai_keyword` ready) — render the "AI‑derived ·
  unreliable" layer in the analytics views, not only inline in the article.
- **AI‑tab Ollama BINARY installer** (Q7=B: download + verify checksum/signature + run the official per‑OS
  installer with a VISIBLE elevation step) — BLOCKED offline on real per‑OS checksums (networked machine;
  never fabricate). Pull/remove/queue + active‑model picker already shipped.
- **Deep‑model tier + long‑context unlocks** (whole‑corpus CITED synthesis over full articles; corpus Q&A
  without RAG, refuse‑when‑absent; long single docs; cross‑language synthesis) — stronger‑rig, POST. All
  keep: grounded+cited, no score/verdict, loopback, provenance, caveats visible, never auto‑fed into the
  trusted pipeline.
- **LLM‑PERCEPTION eval‑first harness** (who/where/when + sentiment‑vs‑VADER): build the difficulty‑tiered,
  phenomenon‑tagged, ×12‑language eval set FIRST (precision/recall/HALLUCINATION on the SHIPPED small model
  vs the rule‑based baseline) before the extractor.
- Polish: a per‑article Summarize/Translate/extract on the analysis Articles list; the synthesis window
  chrome ×12.

---

## 9. WIKIPEDIA‑AS‑A‑SOURCE (RC‑BLOCKING living‑source design — partly built)

- **Full‑text SEARCH over downloaded dumps** + wikitext rendering + the **dumps→corpus ingestion path**
  (today dumps are files; one page reads locally; watched pages already enter the corpus + the omnibar
  searches watched‑page CONTENT — dumps are the standing gap).
- **The dedicated tracked‑changes TAB** (the full‑attention GUI: scroll/discover/analyse edits through
  time; browser‑verified). Per‑mention revid anchoring.
- **Drop the per‑edition "Estimate size" probe** → ONE consented "refresh exact sizes" reading the dump
  date's `dumpstatus.json` (all editions in one call) through the guarded factory + the ONE consent.
- Superseding ruling (record‑only, build WHEN the time comes): once a language DUMP is downloaded the whole
  edition is tracked by default; per‑article tracking retires (scale honesty: enwiki ≈100k edits/day).

---

## 10. CONTINUOUS COLLECTION / TASK MANAGER / DOWNLOADS (RC‑BLOCKING, twice‑repeated)

- **Onboarding country/language emphasis picker** (folds into the guided wizard's consented first collect)
  + an **explainable schedule** (which language/tag is next + why; the strata preview shipped — extend to
  per‑country priority).
- **Task‑manager: History tab**; per‑country scrape priority; arbitration ask on the remaining starters.
  DELIBERATELY omitted unless the owners measure it: per‑job **rate/ETA + bandwidth cap** (needs
  owner‑measured bytes‑over‑time + a throttling backend — never a client‑side guess).
- Surface the client‑side bulk translate/summary QUEUE in the backend task manager (only the active run is
  in `/api/jobs` today) — NOT via shadow state.
- Segmented HTTP‑Range over multiple Tor circuits for one big dump; dump mirror selection
  (`SCRAPING_AUTOMATION_PLAN.md` Steps 3–4).

---

## 11. SECURITY / ACCESSIBILITY / i18n LONG TAIL

- **Inline‑handler retirement → CSP** (audit OO‑D12‑001): ~295 inline `on*=` handlers → `addEventListener`
  + a Content‑Security‑Policy. Large + browser‑verifiable‑only — reviewable slices with a headless
  click‑through, never blind.
- **a11y batch**; the **custody/crypto UI "make it foolproof"** plain‑language simplification (#20: plain
  controls + `#oo-tip` detail).
- **i18n long tail → ~0** (`--audit-chrome`, ~110–140 untranslatable): key the recently‑shipped
  English‑fallback panels (folder backup/restore, model downloads, newsletter remove, offline‑map,
  synthesis window, the dynamic `loadWatches` rows); the tail is mostly inline‑`<a>`‑linked help paragraphs
  (need the link‑at‑end restructure) + a few deliberately‑emphasised `<strong>` privacy warnings +
  data/examples that stay literal. Plus the **server‑built Home‑card TITLE translation** design. Non‑en
  stays AI‑drafted + flagged for native review.

---

## 12. NETWORKED‑MACHINE / LIVE‑CORPUS TASKS (cannot be done in this sandbox)

Hand to a networked run or the maintainer; never fabricate the artifacts:
- Wikidata **ring generation** (Wikidata 403 here) → vet + commit + re‑measure coverage (§2.4).
- Replacement **FRED ids** for the dead GOLD/SILVER/SAWNWOOD series (a wrong id fails loudly today).
- Exact **dump sizes** refresh; the **bundled offline indicator snapshot** (World Bank); the **IP‑geo DB**
  refresh.
- The **per‑OS httpfs/OpenSSL crypto‑extension packaging decision** — enables PERSISTED‑encrypted columnar
  analytics (today in‑memory); follow `docs/maintenance/EXTERNAL_DEPENDENCIES.md`. The optional columnar
  acceleration of the inherent `co_rows` GROUP BY waits on this.
- The **100k‑article scale** empirical run (perf‑harness; measure EXPLAIN/timing on the real encrypted DB
  before adding any drift surface like a per‑day rollup — §2.7).
- Run **orphan‑prune + tag‑backfill + the keyword cleanup** on the live corpus and measure the reduction (§2).

---

## 13. MAINTAINER‑RULING‑GATED (DO NOT build without a ruling — note + skip)

- App **self‑update**: MECHANICS only (default OFF); the 5 open Qs (channel, trust root, cadence,
  curl|bash‑vs‑git, mirror‑anchoring) + a signing key are a ruling.
- **Signing/notarization**; **win/mac CI lanes → required**; **religious‑calendar/eclipse dates**
  (maintainer provides); the poll‑analysis "ever say push poll / answer who's‑winning more directly" Qs.
- **Open Commons Mirror** = a SEPARATE sister project / new repo, only when this app is mature (V0.1+) —
  NOT this session. **Voice‑only mode**, in‑app **Tor/Stem**, **two‑hop keyword graphs**, the autonomous
  **onboarding track**, **event‑family merge/split UI**, **smart calendars**, the OPT‑IN **oo‑netcut** OS
  layer — designed‑only, each needs its own design session.

---

## 14. SUGGESTED SEQUENCE (maintainer veto applies)

1. **Session start (§1):** reconcile PR #446 + #445; kick the keyword loop; remind on baseline‑tag backfill.
2. **In parallel — the keyword reduction (§2):** confirm the stopwords‑iso/cleanup reduction when the fresh
   log lands; build the **digit‑heavy extraction filter** (§2.5) and the **"?" English‑boilerplate /
   language‑detection fix** (§2.6); drive the **ring generation** round (§2.4) on a networked box.
3. **P0 reliability (§3):** writer‑gate re‑verify under parallel load → backups redesign (restore‑as‑a‑job
   + file‑member placement) → state‑into‑DB.
4. **Release‑eng spine (§4):** guarded‑socket factory; docs↔app reciprocity + USER_MANUAL. (Hold the
   version flip + release.yml + the final security pass for last.)
5. **Flagship UI (§5):** source‑tags‑everywhere + the bubble map (high value, mostly wiring) → corpora
   remaining + caveat‑in‑analysis → Home dashboard → the 3D keyword explorer (the big one).
6. **Depth loops:** keyword/analytics depth (§6) → agenda content (§7) → Wikipedia dumps (§9).
7. **POST / gated:** LLM depth (§8), manipulation cards (§6), collection/task‑manager (§10), the
   networked‑machine list (§12), the i18n tail + a11y + CSP (§11).
8. **LAST before the tag:** the final full security review (§4.3) + the docs reciprocity sweep + CHANGES →
   flip 0.0.9→0.1 → prove release.yml on the tag.

Estimated honestly from the demonstrated pace: the RC‑BLOCKING set is several dedicated sessions; "every
POST row" is materially more. The RC gate file is the truth; the tag is earned the day every RC‑BLOCKING
row reads ✅ — not before.
