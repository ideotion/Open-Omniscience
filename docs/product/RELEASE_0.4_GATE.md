# Release gate — v0.4.0

**Status: OPEN — RULED 2026-09-15 (rows A–F), and grown to rows G–V by the answered roadmap sheet; row W added
2026-09-27 (`RC01` = a). `v0.4.0` TAGGED by the maintainer 2026-09-28 with the exit clause unmet (§3, 2026-09-28), and PUBLISHED
the same day by `release.yml` once the tag moved onto the `0.4.0` flip (row G): the rows still open stay open
below.**
This is the checkable inventory for closing the `0.4`
cycle. It exists now, before the `0.3` tag, because [`RELEASE_0.3_GATE.md`](RELEASE_0.3_GATE.md)
§5 says in its own words that the `0.4` board *"starts from this list"*, and a postponed
data-safety demonstration nobody writes down becomes one that never happens.

**What is ruled here and what is not.** Rows **A, B and C** were moved off the `0.3` board by
explicit maintainer rulings (2026-08-13 and 2026-08-23) that named them **required in 0.4, not
merely deferred** — those are carried, not proposed. Rows **D, E and F** are this session's
**proposals**, marked as such: they are work `0.3` leaves behind, not decisions anyone has
made. A proposed row is not a bar until the maintainer says it is; declining one is a
legitimate outcome and belongs in §3 with its reason.

**AMENDED 2026-09-15 — the board is now RULED, and it grew.** The maintainer's answered roadmap sheet
([`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
indexed line by line in [`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md)) settled this board:
**Q117 = a** makes rows **D and E bars** (no longer proposals) and **closes row F as-is** on **Q1128 = a**
(Chromium in the sandbox + the maintainer's click-through = verified; Gecko stays best-effort). **Q105 = a**
amends the release's CONTENTS while keeping its theme — rows **G–V** below are the sixteen slices the answers
put in 0.4 (the 0.3 close first), each row citing the question IDs it implements (Q112), each with a session
brief under [`docs/plans/2026-09-12-beta-pathway/`](../plans/2026-09-12-beta-pathway/00_INDEX.md) (Q113).
**Q110 = c: no target dates**, on this board or any later one. **Q115 = c:** the operator-time budget per
release is unbounded — the V1 train's "a few hours" assumption is retired, and operator rows are listed
without apology. **Q116 = a:** three lanes as today (planning, build, verification). A row is *ruled* when its
origin is a question ID; anything marked *proposed placement* is the planning session's sequencing, not a
ruling; the ⛔ questions left blank (Q823, Q925, Q1009, Q1113) are named on the rows they touch and are never
assumed — **all four answered 2026-09-29 (Q823 = a, Q925 = a, Q1009 = a, Q1113 = a; §3).** Row order is dependency order, not priority: K (the format bump) precedes the 0.5 storage half by
ruling (Q301 = c), O (the substrate) precedes P and Q by construction.

**How a row closes** (inherited from the `0.3` gate, unchanged): only when there is a **named
artifact** — a report file, a merged PR, a measured number — that a later reader can re-open
and check. "It was built" is not closure; *merged ≠ green ≠ verified*. A row that cannot be
measured here says so and names the operator step, rather than passing on no evidence.

**The version.** `pyproject.toml` reads `0.3.0` and stays there until `v0.3.0` is tagged; the
flip to `0.4.0` follows the tag, as it did at `0.2`→`0.3` (the 2026-07-18 sequence: P0 pass →
tag → flip). Nothing on this board touches the version. **AMENDED 2026-09-27 (`RC01` = a, answered in
chat):** the `v0.3.0` tag the remote has carried since 2026-08-23, a pre-release, IS the `0.3` close, so the
flip no longer waits on `0.3`'s row 5, which is carried here as row W. The flip is the maintainer's own act,
«OK for RC01, I'll do the versino switching after all current draft PRs are merged»; no session opens it unless
the maintainer asks. **AMENDED 2026-09-28:** the maintainer tagged `v0.4.0` on `ad0f2062` (the PR #1191 merge),
where `pyproject.toml` still read `0.3.0`, and `release.yml` refused it at its tag-matches-version step (run
36368552522; the full-suite job had passed), so the release carried no wheel, sdist or checksums. The flip to
`0.4.0` followed at the maintainer's pick, in PR #1195, for the tag to move onto its merge (the maintainer's
step: a session never moves a tag). Row G records it, and the release published from the moved tag.

---

## 1. The board

| # | Row | Owner | Origin | Status |
|---|---|---|---|---|
| A | A committed full import that re-checks **all** sources | operator | ruled 2026-08-13, moved from 0.3 row 4 | **OPEN — the button exists (2026-09-18):** Settings → Advanced → Diagnostics → *0.4 release run*; its report's row A is the committed fresh-install restore + the integrity reading. Pressing it is the operator's; reading its report is the maintainer's · **Field evidence 2026-09-30 (§2):** two instances already read `inversions-found`, three named domains; the merge fix is on `main` (PR #1278), its field proof is this row's |
| B | A multi-day (≥72 h) collector soak | operator | ruled 2026-08-23, moved from 0.3 row 7b | **CLOSED 2026-10-01 (`R113`, «17a»)** on instance 090243's 72 h run of 19–22 September, its 73 hourly readings as the memory evidence; §2 says what the close does not claim. (The button of 2026-09-18, which arms the unattended kit and heartbeats hourly, is how that run was made) |
| C | Diagnostics on the ~1M-article instance | operator | ruled 2026-08-23, moved from 0.3 row 3's earlier bar | **OPEN — the button exists (2026-09-18):** the second button (*Run as the ~1M-article instance*) makes the end-of-run all-diagnostics bundle the REQUIRED artifact and reads its coverage block and zero-byte members into the report |
| D | Row B's evidence is readable from one artifact | session | *proposed* → **BAR, ruled 2026-09-15 (Q117 = a)** | **BUILT, and DRIVEN end to end at fixture scale 2026-09-15** — four of six blocks measured, the other two `measured: false` with a reason · **CLOSED 2026-10-01** on its own exit text: instance 090243's 72 h release run (`20260919T043901Z`) carries the six-block soak-window report of its window (80.46 h, `reaches_bar: true`) and the P0.3 collector check re-taken in the same `collect` phase; §2 records both, and what the close does not claim |
| E | Row A's demonstration has tooling that can state its own result | session | *proposed* → **BAR, ruled 2026-09-15 (Q117 = a)** | **PARTIAL** — built, riding the bundle, and driven end to end 2026-09-15 in BOTH directions (clean → `consistent`; seeded laundering → `inversions-found`, named); the RUN is Row A's |
| F | The browser bar reaches a human, a second engine, or is closed as-is | shared | *proposed* → **closed as-is, ruled 2026-09-15 (Q117 = a on Q1128 = a)** | **CLOSED 2026-09-15** — the bar is Chromium-in-sandbox + the maintainer's click-through; Gecko best-effort. The citable sentence lives in §2 row F behind `<!-- release-notes: verification-bar -->`, and the release notes quote it from there |
| G | `0.3` closed and the version flipped | operator | ruled 2026-09-15 (Q109 = a); 2026-09-27 (`RC01` = a) · brief `S03-01` | **CLOSED 2026-09-28 — `main` reads `0.4.0` (PR #1195).** `RC01` ANSWERED (a) 2026-09-27: the existing `v0.3.0` pre-release is the `0.3` close and `0.3`'s row 5 moved to row W. The flip came after the `v0.4.0` tag, which was cut while the version read `0.3.0`; the tag moves onto the flip's merge (the maintainer's step) |
| H | `docs/SECURITY.md` enumerates every host; the consent hover lists them per lane | session | ruled (Q1001, Q1002) · `S04-01` | **BUILT 2026-09-16, awaiting the maintainer's own click-through** — the enumeration (14 lanes, PR #1135), the hover, and `tests/test_security_endpoint_enumeration.py`; Chromium-verified in the sandbox (en/ar/zh, 900px and 375px), recorded in `docs/audit/net-consent-hosts-2026-09-16/`. Three broken ride-along opt-outs found and DISCLOSED, not fixed — the fix needs a ruling on where it lands (`OPEN_QUEUE.md`, 2026-09-16) · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P1 1 · P3 7): the per-lane host bubble is drawn under the modal consent popup — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27 on the fixed build: every walkable step passes and all 19 first-walk defects checked are fixed; OPEN on 5 new items (P2 2 · P3 3), among them the Home strip's false «server busy» — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 5 items fixed; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 5 re-walk items fixed; not walkable in a sandbox: H9 asks the maintainer's word on the 15 lane names and 3 headings, and H10 needs going online — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| I | The import lifecycle: fresh page, four visible stages, one poll chain, K = 3, one API path | session | ruled (R1–R3; Q201–Q207, Q214, Q216, Q217, Q221, Q222) · `S04-02` | **BUILT 2026-09-16, awaiting the operator's real restore and the maintainer's click-through.** The fresh page + its quiet line, the four stage rows, the three statements, one poll chain, K = 3, the `v2/restore/*` deletion with `allow_unverified`/`include_newsletters` carried onto the queue, the boot auto-resume, and the history list in Settings → Data & backup. Chromium-verified in the sandbox on a REAL import (en/fr/ar/zh, 21 coverage rows, `docs/audit/import-lifecycle-clickthrough-2026-09-16/`). **Q207 is an ASSUMPTION** (blank sheet, default a). **Q217 measured and PARKED** — prepare dominates (0.976 s of a 0.804 s stage sum across four backups, matching the field's 54%), but 73% of it is `stage_a:reassemble` rather than the validate/upgrade pair the ruling names, and the three C3 blockers are unlifted; the field-scale read is the operator's. **Five defects found by the adversarial passes and fixed**, the worst a refused backup reading `done` beside the two good ones reading `discarded`. Remaining: a real four-backup restore at corpus scale, a kill between stages 3 and 4 on that machine · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P2 9 · P3 6): Q203/Q204/Q205 statements and stage 4, and R1's fresh page on reopen — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: every walkable step passes, 25 first-walk defects checked are fixed; OPEN on 8 new items (P2 1 · P3 7), among them «Already judged here, kept» over-counting — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 8 items fixed; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 8 re-walk items fixed; not walkable in a sandbox: I1 needs the real install and its import history, which is the operator's restore run — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| J | The export: dated `OpenOmniscience_Backup` folder, completion panel, `BACKUP_SUMMARY.md`, verify-after-write | session | ruled (R4, R5; Q208–Q213, Q218–Q220, Q1008) · `S04-03` | **BUILT 2026-09-16, awaiting the operator's removable-drive export and the maintainer's click-through.** The dated folder (local time, `_2` on collision, exclusive `mkdir` so an existing folder is never entered), verify-after-write ON by default with its four verdicts kept apart, the completion panel and `BACKUP_SUMMARY.md` rendered from ONE `export_facts`, Q1008's licence lines in all three carriers, Q219's member hook, and Q220 stated as a non-feature. Chromium-verified in the sandbox on THREE REAL exports (en/fr/ar, `docs/audit/export-folder-clickthrough-2026-09-16/`). **Q823 ⛔ is the stated seam** — no ODbL line, and an OSM-derived corpus table makes the attribution layer REFUSE rather than ship a short block. Remaining: the operator's export to a real removable drive (the re-read cost is `not-measurable-here`) and their word on the reference VM · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): PASSES for everything a sandbox reaches (P2 2 · P3 7 to fix); the removable drive stays the operator's — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: every walkable step passes, 14 fixed; OPEN on 4 new items (P2 1 · P3 3): a reload during the corpus phase silently drops the large-data copy — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 4 items fixed; J-1 by the minimum fix (a reload no longer drops the large-data copy silently), the one-job export deferred; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 4 re-walk items fixed (J-1 by the minimum fix); not walkable in a sandbox: J7 and J8 need the removable drive, which is the operator's export run (their sandbox equivalents pass) — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| K | ONE backup-format bump: the alpha-3 restore normaliser, all rings, the tentative-translation table, the fetch/scrape-history member with its trust toggle | session + operator (the real-restore proof) | ruled (Q215, Q310, Q313, Q404, Q409, Q701 note) · `S04-04` | **BUILT — OPEN on the operator's real-restore proof** |
| L | ISO 3166-1 alpha-3 step 1: display + boundary, the loader normalises, the filename rule | session | ruled (R6; Q301 = c step 1, Q302, Q303, Q307–Q309, Q311, Q312; Q306 display step *proposed placement*) · `S04-05` | **BUILT — OPEN on the two surfaces no offline machine can show (Governments figures, Markets)** · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P2 4 · P3 13): 28 ISO territories missing from the alpha-3 table; five surfaces still print two-letter codes — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: every step passes, 26 fixed; OPEN on 10 new items (P2 2 · P3 8), among them the Home Lead cards' English prose — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 10 items fixed; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 10 re-walk items fixed; every step was walkable — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| M | Keywords in the UI language: the label grammar, the three-tier ladder, auto-loaded rings at 1 / 10 s, lemmatisation, per-mention language | session (+ one operator ritual per tag) | ruled (R7, R8; Q401–Q404, Q406–Q408, Q410–Q414, Q416, Q418) · `S04-06` | **PARTIAL 2026-09-17 (PR #1148)** — the ladder, the label grammar through ONE helper, Q412's refusal, the cards, lemmatisation at extraction with `simplemma` in core, `KeywordMention.language` and the generator at 10 s. **S6, the consented in-app Wikidata ring job, is now BUILT** (Q406 ⛔ = b, Q407, Q408, R8): one request per 10 seconds enforced as a gate over REQUESTS rather than a sleep over items, both the button and the endpoint gated, airplane mode refused by name, rings merged into the local file at the lowest precedence. **THE TWO CARRIED ITEMS ARE BUILT 2026-09-25:** the re-normalisation job (`src/analytics/keyword_fold.py`, Settings → Advanced → Diagnostics, kind `keyword-fold` in the task manager) re-keys pre-lemmatisation mentions through the SAME `lemma_key` extraction uses and is proven EQUAL to a lemmatised re-index on the fixture in both corpus states (mentions, counters, top keywords); `reconcile_keyword_language` is now a keyset scan of `keyword_mentions` alone, a pre-#1148 mention voting through its article's language read from a covering index (`ArticleLanguageMap`), which is what a backfill would have written, without writing it. Both run as one job and one report (`tests/test_keyword_fold.py`, `tests/test_keyword_fold_ui.py`). **OPEN on:** operator step 2, both reports on the real corpus; and the Q1128 = a bar is HALF met — Chromium in the sandbox walked the keyword labels (en/fr/ar/zh) and the ring panel (en/fr/ar/ja), the maintainer's own pass is still owed. The stoplist merge (Q1103/Q1104) stayed HELD on its CONFLICT and nothing was merged into any stoplist **(2026-09-30: `R98` released it, `R111` amends it — batches are curated by us and ship with each app update, no review screen — and it closes on the first curated batch taking effect on every surface, after R111 steps T2 and T3)** · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P2 7 · P3 7): most keyword surfaces still draw bare foreign words; post-fold terms resolve to emptied keywords — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: FAILS M3, M4 and M8; M1, M7 and M14 only partly fixed, 21 fixed; 16 items (P2 7 · P3 9) — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 16 items fixed, among them the first walk's M1, M3, M4, M7, M8 and M14, which the re-walk found still present or partly fixed; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 16 re-walk items fixed; not walkable in a sandbox: M7 needs a real corpus with a rising Lead and M10 needs going online to Wikidata; the operator's keyword clean-up report stays owed — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| N | Cross-language search through the rings in every tab; CJK segmenters; Arabic folding; the literal toggle | session | ruled (R10; Q417, Q501–Q504, Q506–Q512, Q514–Q516; `PF12` 2026-09-27) · `S04-07` | **OPEN — the backend spine BUILT 2026-09-17 (PR #1149).** S1/S3/S5/S6 and Q417's server half: `resolve_concept` computed once and passed to both paths, the 40-literal cap with its switch and its anti-capping disclosure, and `search_total`'s dropped expansion hook (live-reproduced at 7 ids against a total of 3). The agreement bar is demonstrated at fixture scale — 6/6/6/6/6/6 expanded, 2/2/2/2/2/2 literal, in `docs/audit/cross-language-agreement-2026-09-17/`. **THE READER-FACING HALF BUILT 2026-09-17 (PR 2).** S4, S3's reader half and S1's persistence half: the literal toggle and the cap switch with their URL and tab-seed state (Q503 note, Q504), a language chip on every row with a group-by-language view (Q508 note), and the per-form counts with their single total (Q509 note) — measured live at `climate 156 · climat 3 · clima 1 · klima 1`, summing to 161 against a distinct total of 160, which is the overlap the caveat warns about demonstrated rather than asserted. Chromium-verified in en/ar/zh/ja/hi (`docs/audit/cross-language-lens-clickthrough-2026-09-17/`), which found the server's caveat rendering in English on four translated pages and a boot race in `hi`, both fixed. **S7 HALF-BUILT 2026-09-17 (PR 3):** Q510 — a watch on "climate" watches the ring, threaded into `_fts_matcher` beside the quarantine gate and disclosed on every watch row and firing; Q512 — `GET /api/insights/concept-map` and the mind map's Concept view, the ring at the centre with one arm per language and associations off the arms, its geometry measured out of the emitted SVG in `tests/concept_tree_node_test.js` and walked in Chromium in five locales (`docs/audit/concept-map-clickthrough-2026-09-17/`). **S7 COMPLETE 2026-09-17 (PR 4):** Q511 — `country_coverage` merges cross-language equivalents into one concept row (the merged article count a real union, never a sum and never a `max()` floor), and the note's annexe ships as `CROSS-LANGUAGE-CONCEPTS.md` inside the bundle ZIP. `by_topic_tag` groups by TAG and presents no keyword, so it was deliberately left alone. **S2 BUILT 2026-09-17 (PR #1153):** Q502 — `ooChart` learned to stack, so the ONE toolkit still draws every chart, and the stack is earned rather than assumed (five NAMED refusals, an axis that starts at zero, and the overlap stated beside it because per-language mention counts do not sum to the distinct article total printed next to them); Q417 — the per-language breakdown reaches the aggregate rows' hover, where `queries.trending` had been publishing it on every ring row for the whole feature with no reader on that surface. Three defects the Chromium walk found rather than assumed: the first rendering drew filled BANDS, so a corpus with two timestamps became six wedges sweeping across a week — every assertion passed and the picture was the only thing wrong, because invariant #16's sparse rule is written about lines and the new renderer is not one (it now obeys the shared `_SPARSE_BAR_MAX` and draws stacked COLUMNS); the stacked hover reported the BOTTOM band wherever the reader pointed (the hit test tied on time and every band shares the grid); and `loadAnalysis` built the lens for EVERY tab one line ABOVE the `await OOI18N.ready` it had just been given, so a non-`en` reader's first chart described a resolution computed without their language — measured as `hi` issuing the trend request twice. A fourth came from the translation pass: `hi.json`'s `"mentions"` spelled one Devanagari word with a BENGALI letter in it, on a string this view renders, and a scan now guards all twelve locales (`tests/test_locale_script_purity.py`). **S8 BUILT 2026-09-25:** the search index folds Arabic and segments Chinese (jieba, now core) and Japanese (sudachipy, `[segmentation]`) at index and query time through one transform the sync triggers call, each transformed document recorded so a delete is exact whatever happens to a dictionary later; the search re-index job carries the older articles over, before/after counted at fixture scale (`tests/test_fts_cjk_arabic.py`). REMAINING: the re-index and the agreement comparison on the reference corpus (operator), Q515's cost, and the maintainer's own click-through (the maintainer's word on `sudachipy` versus `janome` for ja came 2026-09-27: keep `sudachipy`, `PF12`) · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P1 1 · P2 3 · P3 10): a deep-linked analysis tab can paint another tab's results — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: FAILS N11; 21 fixed; 8 items (P1 1 · P2 3 · P3 4), the P1 being the trend's Counts mode labelling mention counts as articles — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 8 items fixed, the P1 (N-3) among them; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 8 re-walk items fixed, N-4's Diagnostics half after the walk (`38965c0e`, re-checked in Chromium); not walkable in a sandbox: N12 and N13 need the real install, which is the operator's search re-index report — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| O | The versioned-source substrate; one encrypted database file per lane; lanes replace the scheduler mode; the Living sources view; reference-VM budgets | session | ruled (Q716, Q719, Q720, Q926, Q1003–Q1007, Q1010, Q1011, Q1014–Q1016, Q1018, Q1020) · `S04-08` | **PARTIAL 2026-09-17 (PR #1154)** — S1 and S2 BUILT. `src/versioned/` (Q1003 = a) and one encrypted SQLite file per lane beside the corpus (Q719/Q1004/Q720/Q1005/Q926) through the ONE keyed factory, proven by the gate itself: `alembic upgrade head && alembic check` reports no new operations, because the lane metadata is invisible to alembic by construction. The change feed with cursor, dedup and gap detection; the immutable baseline, the bounded PUBLISHED diff and the point-in-time read; the wiki adapter over Q1018's synthetic edition with **zero name resolutions**; the backup MEMBER hook. **THE SLICE'S OWN TWO SKEPTIC PASSES FOUND NINE DEFECTS, EVERY ONE REPRODUCED BEFORE IT WAS FIXED** — among them three separate at-rest paths that enumerate this app's databases as a LITERAL LIST, none of which knew a third had arrived: `encrypt_all` (a lane created while the store was plaintext stayed plaintext FOREVER after the operator consented to encryption), `quick_crypto_erase` step 1 (a lane fell through to the full-overwrite path, turning an instant crypto-erase into an hours-long data erase at the 100 GB Q719 anticipates), and `GET /api/system/doctor` — the endpoint whose docstring is *"the honest answer to 'is my corpus encrypted?'"* — which answered while a plaintext store sat beside the one it described. Also: the cursor tie-broke on a third party's `revid`, silently dropping a real change and then advancing past the loss; and `OO_DB_PLAINTEXT` outranked the passphrase for a FRESH file, so "no per-lane plaintext" was true of the mechanism and false as an outcome. **S3 BUILT 2026-09-25:** the scheduler `mode` and `VALID_MODES` retired, the pass is the press lane and markets, law, hazards, discovery and the crawl supplement run beside it; the one-time migration exercised on BOTH stores and disclosed ×12 until dismissed (`tests/test_scheduler_mode_retired.py`, `docs/audit/scheduler-lanes-clickthrough-2026-09-25/`). **S4 BUILT 2026-09-25:** the published budget table is a FILE, `configs/lane_budgets.yml` (version 1; reference machine 2 cores / 3.5 GB; the wiki row's 20 GB from Q707 and NO number for press, law or OSM, because none was ruled and the app never invents one), refused whole when malformed; the machine reading (cores, RAM, free disk) taken at boot before the lock check with no network, shown beside the reference with NO verdict between them (the reference class reports 3.2–3.46 GB, so a strict "below 3.5 GB" would call the reference machine smaller than itself); each lane's size recorded hourly as `lane_mib_<kind>` (MiB for the Q1140 column limit, absent never recorded as zero); and Settings → Data & backup → Storage showing each lane's size, its budget (the wiki one editable through the same config write as the wizard), its measured growth over 30 days once 7 days of readings exist (a rate, never a projection) and the disk left (`tests/test_lane_budgets.py`, `tests/test_hardware_reading.py`, `tests/lane_storage_node_test.js`, `docs/audit/storage-budgets-clickthrough-2026-09-25/`). A PANEL at the top of Data & backup rather than a tenth subtab, because ruling 42 pins nine; the maintainer confirmed that placement on the decision card (R33). **S5 BUILT 2026-09-25:** every lane in the consent hover carries its transport line, taken from the server's reading of the fetch path (`transport_summary`) rather than the stored `http_proxy`, which had made the popup say "fetches ride the proxy you configured" in transparent mode, where that proxy is not used, and "no proxy" beside a working pool or when the settings could not be read; the Wikipedia stream WAITS with a named reason (`transport-waiting` and the failure verbatim) instead of reading as running while every connection fails, and never falls back to a direct connection; a paused map or dump download says whether airplane mode, the operator or a restart paused it, and a failed one shows its error; the law lane runs two passes of the scheduler's own law step over the S04-10 jurisdiction, and a new synthetic OSM extract (`tests/fixtures/osm/`, written by `scripts/make_osm_fixture.py`, digest pinned) is downloaded by the real manager and read by the in-browser reader, each with the socket guard installed and ZERO name resolutions (`tests/test_lane_transport.py`, `tests/net_lane_transport_node_test.js`, `tests/test_download_paused_by.py`, `tests/job_why_node_test.js`, `tests/test_law_lane_offline.py`, `tests/test_osm_fixture.py`, `tests/osm_extract_node_test.js`, `docs/audit/lane-transport-clickthrough-2026-09-25/`). **THE CHROMIUM WALK FOUND FOUR MORE, EACH FIXED BEFORE IT WAS RECORDED:** the stream slept through airplane mode and Stop for as long as its backoff (up to five minutes), and now waits in one-second slices; on a fresh install the drain and the pin made `wiki.db` without its schema, so the Wikipedia lane stored nothing and its status answered 500, and both now create the lane first with the Q1005 refusals, repairing an existing empty file on the next drain (`tests/test_wiki_lane_schema.py`); the task manager the top-bar button opens is its own page, whose rows had no cause line; and the offline hint raised by cancelling the consent popup covered the open language menu. The versioned OSM adapter stays an interface in 0.4; 0.5 consumes the extract. **S6 BUILT 2026-09-25:** the Living sources view is a MAIN TAB — Q1016's NOTE, answered «Main tab» on the decision card the same day (`R32`, UI invariant #32) — with Wikipedia, Law and Maps as subtabs: coverage (pages followed, text stored for N of M, changes on pages nobody follows), freshness as the newest and OLDEST check and never a verdict, the feed's complete-through point (the feed that is behind), open gaps, the stored diff opened in place, and Settings → Storage's own cells without the budget input (#8). It REPLACES the tracked-changes dialog, whose ids and renderer moved into the tab; the reader's deep link lands there. One read endpoint, `GET /api/living/overview`, plus the stream's timeline and one stored diff (`/api/wiki/lane/changes`, `/api/wiki/lane/revisions/{id}`); nothing writes, nothing leaves the machine, and a read never creates the lane file (`tests/test_living_sources.py`, `tests/living_sources_node_test.js`, `docs/audit/living-sources-clickthrough-2026-09-25/`). Its tests and its walk found seven defects, each fixed before it was recorded, the two worst being failed map downloads counted under a word the manager never writes (every failure read zero) and every diff line drawn backwards in Arabic. **ALL SIX SLICES ARE BUILT; the row stays PARTIAL** until the operator steps of the brief's §5: the upgrade of an existing encrypted install on the maintainer's machine, and the click-through of the new surfaces (Q1128 = a). Two findings DISCLOSED not fixed, both in `OPEN_QUEUE.md` · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): PASSES for everything a sandbox reaches (P1 1 · P2 1 · P3 2 to fix, the P1 being H's); O13–O15 stay the operator's — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: every walkable step passes, 21 fixed; OPEN on 6 new P3 items — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 6 items fixed; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 6 re-walk items fixed, O-5's `/tasks` line after the walk (`38965c0e`, re-checked in Chromium); not walkable in a sandbox: O11's online half and O13 to O15 need the real encrypted install, which is the operator's upgrade run — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| P | The Wikipedia lane: EventStreams metadata for every edit in twelve editions, HOT full text, the top-bar toggle (default on), the wizard, disclosure | session + operator (the ≥ 72 h run) | ruled (R12; Q108, Q702–Q715, Q717, Q718, Q721, Q725–Q728, Q819 steps 1–2) · `S04-09` | **PARTIAL 2026-09-17** — S1 and S2 BUILT. The hand-rolled SSE client over the guarded session (Q1015), the lane's identity on `(wiki, pageid)` (Q715), Q705's fields as ROWS so absence stays absent, Q713's deletion mark as a flushed column, Q708/Q709's every-edit rows, and Q727's gap published rather than inferred away. **THE KILL SWITCH IS CHECKED ON EVERY READ, NOT ONLY AT CONNECT** — `GuardedSession` consults it inside `request()`, which is right for every other caller in this tree because their requests are short; a stream's `request()` returns in milliseconds and then delivers bytes for hours, so airplane mode engaged mid-stream would keep storing edits from a connection whose permission was withdrawn, and the socket guard cannot close a socket that is already open. **A PREMISE CORRECTION MADE THE RULED IDENTITY FREE:** `src/versioned/adapters/wiki.py` recorded that `list=recentchanges` carries no `pageid` — read off OUR parser rather than the API, which already asks `rcprop=ids` and already kept `revid`/`old_revid` from that same prop while dropping `pageid`. **SIX DEFECTS FOUND IN THE SLICE'S OWN WORK, EACH REPRODUCED FIRST**, among them a cursor that trailed the stream by every FILTERED event (which would have fabricated a retention gap on a quiet edition) and an `idle_seconds` frozen at `0.0` for the duration of the stall it exists to show. A mutation matrix over all six new guards reddened each by name; two survivors were coverage findings. **S3 AND Q728's ENDPOINT HALF BUILT** too: the top-bar toggle (Q702's NOTE — default ON, three stored states, four verbs, the `#net-toggle` grammar since `#llm` is a pill with no click behaviour to mirror), ×12 with the hostnames kept Latin, Chromium-walked in en/ar/zh/de/fr × three states with zero findings; and the dump→corpus POST retired with the offline READER kept, both pinned. **The toggle does not overclaim:** nothing consumes `wiki_lane_state` yet, so the status reports `state` (the choice) and `active` (whether anything acts on it) separately, `active` MEASURED from a registry the read loop maintains rather than hardcoded — a constant would be true today and the inverse lie the day a collector lands. **S4, S5 AND THE RUNNER WIRING BUILT 2026-09-18** (PR #1156; #1155 merged mid-build, so this is the rest of the slice rebased onto it). The runner is the gap this row named as the slice's largest — *"nothing schedules the stream, so the lane does not collect"* — and it is closed: the lane rides the ONE online seam (`POST /api/system/network`'s "Online ⟺ collecting"), never the boot path, so Q702's DEFAULT-ON is a statement about what happens when the operator goes online rather than a reason to go online for them. **Q707's budget is a STORAGE cap and NOT a second rate authority**: the ruling says "per-edition daily budget" and the naive reading builds a bytes-per-day allowance, which is exactly what Q1012 forbids beside the collection-speed governor — so the cap is on bytes HELD, the rate stays the governor's, and the wizard says so in the operator's own words. A tier this release does not ingest gets its OWN counter and reason, distinct from both a feed gap and a spent budget: three ways to not have something, three names. **THE COUNTERS ARE COMPUTED, NOT ACCUMULATED** — there is no counters file, so every figure survives the restart a ≥ 72 h run is likeliest to contain, and the soak bundle and the operator's own route call one function. **Q711 needed no column**, which is a finding rather than an omission: the standing ruling makes the anchor `Article.source_revision`, so the obvious reading of that question — a schema change — would have undone a decision nobody wrote down where it would be read. **Analytic 2 is not called what Q712 calls it**: this lane stores no editor, so one person editing ten times and ten people disagreeing are identical rows and "contested" would be a claim about people from data about bytes; it ships as edit CONCENTRATION plus size REVERSALS with the gap stated where the operator reads it. **FOUR MORE DEFECTS, EACH REPRODUCED FIRST:** the adapter's seen-map kept only the NEWEST title, so a page renamed mid-batch — plainly mentioned by the corpus under its old name — was never followed, with nothing saying why; `create_all` never adds a column to an existing table, so a lane file written by S04-08's build raised `no such column: versioned_entities.deleted_at` under this one (closed by a reconciliation that PLANS first and APPLIES second, since a refusal applying as it went leaves a file that is neither shape); the section walk emitted a repeated heading twice and compared the second occurrence against the first's old body; and the Home strip's "today" boundary was a naive datetime, which the lane's timestamp type refuses BY NAME and was right to. **REMAINING:** the operator's ≥ 72 h run (row P's operator half, now STARTABLE and listed with the counters it must show), the maintainer's own click-through, and Q717's live verification of the scoring endpoint — every Wikimedia host answers `000` from the build sandbox, so `ORES_AS_OF` is dated to the day the client was written against the documented shape and NOT to today. Q728's other half stays blocked: the Living sources view does not exist (row O) · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P1 1 · P2 4 · P3 5): the consent popup's host and transport lines are unreadable; ORES pre-ticked against Q717 — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: FAILS P11 and the 375 px pass (both P3); 23 fixed; 6 items (P3 6) — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 6 items fixed; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 6 re-walk items fixed; not walkable in a sandbox: P5 needs Wikimedia after consent; the ≥ 72 h run stays the operator's — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| Q | The law metadata model, the L0 defects, translations as tracked documents, the first bulk adapters, the vetting board | session + operator (the 44-row board; live adapter checks) | ruled (R14, R15; Q107, Q901, Q902, Q904–Q910, Q914 1–2, Q915, Q917, Q919, Q921–Q924, Q927) · `S04-10` | **OPEN — S1–S4 SHIPPED 2026-09-18 (PR #1157): the three L0 defects (Q917), L6, the metadata model, the adapter framework + the Q925 seam report, and analytics 1–2. Remaining and NOT this session's: the adapter ORDER and the first managed dataset (Q925 ⛔, PENDING — 117 verified sources are listed in `LAW_ADAPTER_SEAM.md` and none is chosen); the 44-row vetting board (operator); the live checks against the three priority hosts, `not-measurable-here` here** |
| R | Equal Earth on all five map surfaces; Natural Earth 50m; CONTESTED both-claims, a worldview toggle (OSM's convention as the default moved to 0.5, `PF06` = a) | session | ruled (R13; Q801–Q803, Q826; `PF06` = a 2026-09-27) · `S04-11` | **OPEN — on its click-through only.** The seam, 50m and the CONTESTED layer shipped 2026-09-16 (sandbox Chromium record `docs/audit/14_MAPS_EQUAL_EARTH_CLICKTHROUGH_2026-09-16.md`); Q803's ruled DEFAULT moved to `RELEASE_0.5_GATE.md` row L with the OSM artifacts it waits on (`PF06` = a, 2026-09-27); the maintainer's click-through (Q1128 = a) is owed · **CLAUDE WALK 2026-09-27 (R35's terms, not a ruling): FAILS (P2 5 · P3 19 items). The geometry passes on all five surfaces; contested-area names are English in every locale, three areas name one claimant, a worldview is not shared across maps, two maps do not follow a language switch, and the When / Where embed Q1150 kept was never built — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 21 of 24 items fixed in code; R-6, R-14 and R-24 are the Q1150 embed that was never built, resolved by the corrected row text; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 24 re-walk items fixed (R-6, R-14, R-24 by the corrected row text); not walkable in a sandbox: the cities map shows only its honest empty state, since placing a city needs a source city — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| S | Sources: `qualified` ⇒ `enabled`, the hatch retired, the overlay editor, the institutions moves, the Stage B splice, the stratified round-robin | session + operator (the shortlist run) | ruled (Q1101, Q1105–Q1112, Q1114–Q1119, Q1156) · `S04-12` | **SESSION WORK COMPLETE, awaiting the operator** — S1–S4 all SHIPPED. Outstanding and NOT this session's: the shortlist (3,031) run (Q1118, needs the maintainer's machine or row V's allowlist), the human review of the SPLICE REPORT before any row is applied, and the maintainer's own click-through. The embassy platforms (Q1113 ⛔) are PENDING and nothing in S1–S4 decided them · **VERIFICATION PASS 2026-09-18 (PR #1159)**: the click-through this row was missing now exists (`docs/audit/sources-admission-clickthrough-2026-09-18/`, Chromium, en/fr/ar, the undo and the overlay round trip driven for real) and it is the SESSION's pass, not the maintainer's — that one is still outstanding. It found three unkeyed panel strings and a four-fragment sentence; a skeptic pass on the safety valve found and this session reproduced an undo that overwrote a later `disqualified` verdict. Both fixed here. **The Q1113 ⛔ seam was NOT crossed**: the embassy platforms stay excluded, nothing was published and nobody was contacted · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P2 4 · P3 4): the merge refusal never renders; a live language switch freezes the Quality gates panel — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: FAILS the 375 px pass, a regression from the S8 fix; 15 fixed; 12 items (P3 12) — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 12 items fixed, the 375 px regression among them; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 12 re-walk items fixed; not walkable in a sandbox: the shortlist run stays the operator's — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| T | Network budgets and politeness: the per-process bandwidth budget, the persisted Crawl-delay cap, the loopback rate limit, the airplane titles, the net-coach weights, weight digests | session | ruled (Q1012, Q1013, Q1125, Q1126, Q1132, Q1148) · `S04-13` | **OPEN — five of six BUILT 2026-09-16; Q1132 was already shipped 2026-09-07. Remaining: the operator's own click-through, and the weights digest VALUES (`huggingface.co`/`ollama.com` are egress-blocked here, so the pins ship blank-and-refusing by design)** · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P1 1 · P2 3 · P3 3): the task-manager page always reads online — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: every walkable step passes, 21 fixed; OPEN on 9 new items (P2 1 · P3 8) — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 9 items fixed; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 9 re-walk items fixed; not walkable in a sandbox: T9 needs a collection pass online, and T10 was not observed on this corpus — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| U | UI, i18n and the small rulings: the 470-string remainder, the religious-calendar feature dropped, the encrypted click-through variant, the `diagnostics.py` split, the FUTURE_DEVELOPMENTS reality check, newsletter attach | session | ruled (Q1124, Q1130, Q1135, Q1139, Q1141, Q1149, Q1151, Q1152) · `S04-14` | **SESSION WORK COMPLETE 2026-09-18 (PR #1160), awaiting the maintainer's click-through and ONE separate session.** Every clause of this row is now built: Q1139 (2026-09-16), Q1141 (2026-09-16), Q1149 (2026-09-16), Q1151 (2026-09-16), and in PR #1160 Q1152, Q1130/RC17, RC08.6/L5 and Q1124. **All three i18n gates are at ZERO** — 461 → 0 untranslatable, 224 → 0 unkeyed `t()` literals, and a THIRD gate (`--max-unkeyed-tf-frames`) added because the other two are blind to the app's own interpolation frame by construction, also at 0. What is NOT this session's and never was: **`RC13` = (b)'s networked research session for the religious dates**, whose brief is written into §3 below — a session with no egress to published calendars can only fabricate a date; the **eclipse canon stays UNSTATED** (the `± eclipses` suffix was never written); and the **Patterns-lens FLIP** (Q1124), which needs an operator-labelled sample 0.4 does not produce, so the gate panel ships reporting that the rate is unmeasured rather than defaulting it to a number. **RE-VERIFIED 2026-09-18 (PR #1161, session 2): the three zeros are real — and they were measuring less than they appeared.** The chrome audit read only `<th>` and `<button>` inside the `app-*.js` template literals, so Home's empty state and four reader caveats were English in twelve locales behind a green gate; widened to 21 tags in two measured steps and **120 more strings keyed ×12**, with the ratchet never moving off 0. Two surfaces frozen in the boot locale were also fixed · **DELEGATED CLICK-THROUGH 2026-09-26 (R35): FAILS (P2 1 · P3 8): the first-launch data-location screen never appears (503 while locked) — `docs/audit/delegated-clickthrough-2026-09-26/`** · **RE-WALKED 2026-09-27: every walkable step passes, 21 fixed; OPEN on 11 new items (P2 1 · P3 10) — `docs/audit/delegated-rewalk-2026-09-27/`** · **RE-WALK ITEMS FIXED 2026-09-27 (R37, PR #1191): 11 items fixed; the row closes when its next walk, of these fixes and its steps, passes** · **FIX-CHECK WALK 2026-09-27 (R37): the click-through clause PASSES — every walkable step passes and all 11 re-walk items fixed; not walkable in a sandbox: U4 and U8 need the real install and mailbox — `docs/audit/delegated-fixcheck-2026-09-27/`** |
| V | The release ritual and the allowlist: release notes from `shipped.csv` + the no-telemetry re-check; the session environment's egress allowlist | operator | ruled (Q111, Q114 ⛔ = a, Q116; `RC10` ⛔ = b 2026-09-27) · `S04-15` | **OPEN — the generator half SHIPPED 2026-09-15** (`scripts/release_notes.py`, wired into `release.yml`); the allowlist and the per-surface click-through records are the operator's. `RC10` ANSWERED (b) 2026-09-27: `dumps.wikimedia.org` excluded for now, so the closing probe moves to a Q114 host that stays on the list; a session's probe that morning read `000` for all seventeen Q114 hosts, so the allowlist is not applied yet |
| W | `0.3`'s row 5 — the Tier-A quarantine run (8 articles), carried here as an operator step beside rows A–C | operator | ruled 2026-09-27 (`RC01` = a, moving it off the `0.3` board; its criteria agreed 2026-08-23) · brief `S03-01` S2 | **OPEN — the button exists (2026-09-18):** the release run's opt-in step runs it last, with collection paused (`FD01`, `FD02`); pressing it is the operator's |

Rows A–C are the substance. D and E exist because A and B are both **operator** rows whose
closing clauses ask for a number nobody currently has a single place to read — and a row whose
evidence has to be assembled by hand is a row that closes on somebody's memory.

**The exit (amended 2026-09-15, and 2026-09-27).** `v0.4.0` is tagged when rows A–E and G–W are CLOSED on named artifacts
(F is closed), the three i18n gates and the whole-tree guards are green on the tagged tree, and the release
notes carry the no-telemetry re-check (row V). A PENDING ⛔ question blocks only the row that names it:
Q925 blocks nothing on row Q beyond the adapter order; Q1113 blocks nothing on row S (the status quo
excludes those hosts); Q823 and Q1009 are `0.5` matters. No date (Q110 = c). **2026-09-27:** row W (`0.3`'s
row 5, `RC01` = a) joins the clause; row R closes without Q803's default, which moved to the `0.5` board
(`PF06` = a); row V's probe leaves out `dumps.wikimedia.org` (`RC10` = b). **2026-09-28:** the maintainer tagged
`v0.4.0` before this clause was met (§3); the rows it names that were open then are still open below.

---

## 2. The rows

### Row A — a committed full import that re-checks all sources

**Carried verbatim in substance from `0.3` §5.** Was row 4 of the `0.3` gate. Moved
2026-08-13: the full source re-check *"will take ages"*.

**What it must demonstrate** — three things, and the ordering matters, because each later one
depends on the earlier one having actually run:

1. **A committed merge at scale.** Every P0 restore so far ran `committed=false` — a
   self-restore in which every row reads as a duplicate. The committed write path at ~1M
   articles has never been exercised in the field.
2. **The qualification admission gate over every source that is not the curated catalogue,
   and the six-month re-check over the catalogue itself.** *Amended 2026-09-10:* the
   maintainer ruled the curated catalogue **qualified at seed** ("make the curated catalogue
   qualified, and as with any other qualified sources, they should go through the same
   periodic re-qualification process"), which supersedes the 2026-07-20 no-grandfathering
   clause this item carried. What the row now demonstrates is that the stamp's basis
   survives the import as `curated` (never laundered into a measured verdict), that the
   catalogue's re-checks actually run, and that a catalogue source whose re-check fails is
   disqualified like any other — still a **catalog-review** signal, not a source to exempt.
3. **The qualification stamp surviving a restore.** This is the load-bearing one. On
   2026-07-24 `_merge_sources`' column allowlist dropped the three stamp columns and
   `source_qualification_attempts` had no handler, so a merged-in source arrived
   `unqualified` — a plausible legal value, therefore invisible — and a **disqualified**
   source was laundered back into the trial queue with its backoff ladder reset. It is fixed
   and unit-covered; what is missing is the field proof.

**Closes when:** one committed import at release scale reports the source verdicts it stamped,
**and a spot-check confirms a previously-disqualified source is still disqualified afterwards.**
That last clause is the whole point — a pass that only counts `qualified` rows cannot see the
inversion this row exists to catch.

**Field evidence, 2026-09-30 (the 16-instance diagnostics, rank 14; added 2026-10-01).** The
failing shape this clause exists to catch has now been seen in the field twice, by the integrity
check row E built. `qualification-integrity.json` reads `inversions-found` on `20260930-085639`
(2 laundered: `psx.com.pk`, newest judging attempt `disqualified` on 2026-09-03, and `law.go.kr`,
2026-09-04, both `oo-source-qualification-1`) and on `20260930-091717` (3: the same two plus
`wiadomosci.onet.pl`, `oo-source-qualification-2`, 2026-09-08). Each is live `qualified` while its
newest judging attempt reads `disqualified`, and each carries the catalogue's own stamp
(`oo-curated-catalog-1`, one shared `qualified_at` per instance). Three other instances read
`consistent` (`085454`, 20 sources with a judging attempt; `090243`, 657; `101538`, 511) and the
other eleven carry no judging attempt at all, so their member reads `not-measurable-here`. The mechanism was **reproduced with the real `merge_corpus`** in PR #1278 (merged
2026-10-01 00:25 UTC): the adoption `UPDATE` fired only where the local status was `unqualified`,
and a curated stamp is `qualified`, so another instance's measured disqualification landed in
the attempt history beside a live `qualified`. The merge now lets a curated stamp give way to an
incoming measured verdict when that is the newest judging evidence either side holds (a locally
measured verdict still wins, and an incoming curated stamp never replaces a curated stamp or a
measured verdict this instance already holds), pinned by
`tests/test_merge_source_qualification.py`. **That fix is unit-proved; its field proof is this
row.**

What this adds to the clause, none of it a new bar:

1. The spot-check is answered by `inversions_total` in the integrity member, with
   `checked.with_judging_attempt` as the denominator, as row E states — and an instance whose
   member reads `inversions-found` with `laundered_total` above 0 fails it, because a
   laundered row is a previously-disqualified source that is not still disqualified there (all
   five inversions of the round are laundered; `demoted_total` is 0 on both instances).
2. PR #1278 stops a merge from turning another instance's measured verdict into a new
   inversion on a row that carries only the catalogue's curated stamp, which is the case the
   field showed. It does not rewrite rows that are already inverted, and two shapes still arrive
   inverted (both reproduced 2026-10-01 with the real `merge_corpus`; no test covers either).
   A row holding THIS instance's own measured verdict keeps it while a newer, disagreeing
   attempt from the backup is copied beside it, which reads `inversions-found` (laundered when
   the local verdict is `qualified`, demoted when it is `disqualified`). And a backup from an
   instance that is itself inverted carries its inversions in, because an incoming curated
   stamp replaces neither a curated stamp nor a measured verdict while its attempt rows are
   copied unchanged: a curated instance that imports `085639`'s shape (a live curated
   `qualified` stamp whose newest judging attempt is `disqualified`; there the stamps are dated
   2026-09-25 and the attempts 2026-09-03 and 04) reads `inversions-found` afterwards. A later
   import that carries the agreeing measured verdict heals such a curated row, per the merge's
   own comment. The direct way is `scripts/repair_qualification_inversions.py`,
   on `main` since 2026-09-12 (PR #1117): operator-run, a dry run unless `--apply`, it sets
   `Source.status` back to what the instance's own newest judging attempt recorded. Until this
   entry no gate file named it (the ledger had it only in PR #1117's `shipped.csv` row).
3. `checked.with_judging_attempt` and `basis: "measured"` are not evidence that a pass ran on that
   build: the backup merge copies attempt rows unchanged, so a judgement made on another instance
   counts. Read the report's verdict counts with that in mind (on `085639` and `091717` the
   2,049 and 2,195 "measured" rows all carry the curated stamp; an export from a build with
   PR #1281 reads such a row `curated`, item 4).
4. **PR #1281 (merged 2026-10-01 05:45 UTC) makes the inversions that already exist visible and
   withdraws the ones the field showed.** *At boot* (`auto_repair_inversions`, called from
   `run_deferred_startup`; `OO_QUALIFICATION_AUTO_REPAIR=0` switches it off and only the test
   configuration sets it) a source whose newest judging attempt says `disqualified` and whose
   live verdict is the catalogue's own stamp (`oo-curated-catalog-1`) or nothing (`unqualified`)
   goes back to `disqualified`. The plan, with the status and stamp each source is about to lose,
   is written to the `app_state` store before anything changes, so that a maintainer can undo it
   (`scripts/repair_qualification_inversions.py --revert-repairs`, which also holds the domain
   out of the next boot). A verdict measured on that install, or taken from an earlier import,
   is never changed by an imported history on its own (rule 12 = b): such a row stays in the
   report (`not_auto_repaired_measured_here_total`) and waits for the install's own re-check, so
   the first shape of item 2 stays reported, while the second shape's result (a curated
   `qualified` stamp whose newest judging attempt is `disqualified`) is what the boot repair
   withdraws at the next boot. It only withdraws sources from collection: restoring `qualified`
   stays operator-run. All five inversions of this round carried the catalogue's own stamp
   (above), so the repair covers each of them; it is unit-proved only, no instance has yet
   booted this build, and its field proof is this row's, as the merge fix's is.
   *The integrity member* (`qualification-integrity.json`) gains `checked.last_attempt_at`,
   `last_judging_attempt_at`, `attempts_last_24h` and `judging_attempts_last_24h`, a
   `live_stamp` (`none`, `catalogue` or `measured`) on every inverted row,
   `auto_repairable_total` and `not_auto_repaired_total` with its reasons, and every automatic
   repair made (`repaired_total`, `repairs_unconfirmed`, `repair_runs`, `last_repair_at`); its
   caveat says the timestamps cannot tell an attempt this instance's engine made from one copied
   in by an import, so they do not turn item 3's warning into a proof. *The qualification
   export* (`source-qualification-export.json`) now gives a row whose live stamp is the
   catalogue's `basis: "curated"` even when judging attempts sit beside it, and
   `basis.curated_stamp_with_judging_history` counts those rows apart. A row the boot repair
   withdrew exports `basis: "inherited"` and is counted in `basis.repaired_exported_as_inherited`
   (PR #1288, merged 06:23 UTC), but only while no judging attempt this install made is newer than
   the imported one the repair followed: a later local judgement (in either direction) makes it
   `measured`, a later attempt a backup merge brought in (named in `merged_rows`) does not (PR #1294,
   merged 06:36 UTC; PR #1316 for the imported attempts). The residue, an imported attempt with no
   `merged_rows` row (a batch removed by hand in the database), reads as local and is pinned by a test. The same rule decides every judged row: a source whose whole judging history a backup merge brought in exports `inherited`, never `measured` (PR #1316); that includes a restore of THIS install's own backup (a rebuild, a new machine), whose attempts the merge records as imported, so its verdicts read `inherited` until the install judges the sources again (OPEN_QUEUE proposes how an own backup could keep its history). A repair run whose record
   cannot be read is named in `basis.repair_runs_unreadable`, and the rows it withdrew may then
   read `measured` although an imported history decided them.

**What the release run's own report said about the restore, and what it says now (2026-10-01).**
Four of the five release-run reports in the sixteen bundles reached the restore. Two restored:
instance `085214` (3,509.9 s, 152,778 articles; integrity `not-measurable-here`, because none of
its 23,470 sources had a judging attempt) and instance `090243` (2,435.5 s, 257,971 articles;
`consistent` over the 657 of its 86,378 sources that had one). Neither held a source that was
disqualified and judged (`currently_disqualified_and_judged` 0, `verified_disqualified_sample`
empty), so the clause's spot-check had nothing to find on either, which is not the same as having
passed it. The other two **failed and were recorded as `measured`**. Instance `085218` was refused
by the restore engine's own staging check after 128 s («needs about 38.0 GB, only 14.7 GB free»:
the engine's GB are GiB; its backup held 29.36 GiB of plaintext, 20.75 GiB of it in members other
than the corpus, and the backup's own note says a residual WAL rode as a member, but the files
hold totals and not member lists, so that those 20.75 GiB are the WAL is inferred); the run's
preflight had read 70.99 GiB free for a 6.12 GiB corpus on 2026-09-19, and a resume does not take
it again. Instance `085230` passed that check and died after 53 minutes with `OperationalError:
Error creating function`, the text of the import error fixed on 2026-09-27 (PR #1192; its build
predates the fix; an inferred match, not a proved one). On both, rows A and I read `measured` over
an empty `restore` block (row K read `measured` from the P0 trio, its scan of the restored corpus
empty), because the phase was `measured` whenever the PARENT returned: the child's own `ok` and its
exit status were never read. **PR #1312 changes that.** A restore counts only when its child reports
`ok`, its process exited 0 and its restore was committed (the engine can return a refusal without
raising); one that does not reads `error` with the child's own words, what it measured stays in
the record, rows A and I read `error`, rows E and K say the restored install's reading is not
counted, and a resume retakes it, asking for the passphrase as a first run does (a state file an
earlier build wrote keeps no restore this rule would not count). The passphrase is also taken out of
what the child says and out of the run journal and import reports that a KEPT fresh install
leaves on the drive. **Neither failed run is evidence for this row, and a report written before
this change must be read through `phase_results.fresh_install_restore` (`returncode`, `child.ok`),
not through its row statuses.** The change is unit-proved only; no instance has yet run a release
run on it.

**The cheaper substitute, still available.** A *small* committed backup demonstrates (1) and
(3) in minutes; only (2) genuinely needs the full corpus. This split was **proposed and
declined for 0.3** (maintainer, 2026-08-13: *"mark it as a necessary step for v0.4, we won't do
it today"*) and the row moved undivided. It is recorded here so the option does not have to be
re-invented, not because it has been re-proposed.

---

### Row B — a multi-day (≥72 h) collector soak · CLOSED 2026-10-01 (`R113`)

**Carried from `0.3` §5.** Was the second half of row 7. Moved 2026-08-23: *"Postpone the >72h
with the other P0 validation to the v0.4 release."* The cold-boot half (7a) stayed, because it
is five minutes and this is three days.

**What it must demonstrate:** memory flat across ≥72 h of continuous collection at release
scale — P0.3 with samples spanning the window and no climb against the 512 MB floor.

**Read both signals, not just the rate.** `collect_perf.jsonl` is a 5,000-line ring — roughly
two hours — so P0.3 only ever sees the recent window; the durable multi-day evidence is the app
**surviving**: the memory guard not stuck engaged, and the previous session ending cleanly in
session forensics. A pass on the rate alone would be a verdict about two hours wearing a
three-day label.

**Closes when** one report shows P0.3 with samples spanning ≥ 72 h and no climb, **and** the
soak-window artifact (row D) shows the process actually stayed up for the window it reports on.

**CLOSED 2026-10-01 (`R113`, «17a»).** The maintainer closed this row on instance 090243's
72-hour run of 19 to 22 September and accepted its hourly memory readings as the memory evidence.
The question put to them (2026-09-30 22:23 UTC) was exactly the gap the "Read both signals"
paragraph above names: `collect_perf.jsonl` keeps about two hours, so no report can show a P0.3
reading that spans 72 h. The two options were «Yes, the hourly readings count as the memory
evidence» (recommended) and «No, make the memory check cover a whole run, then run another 72-hour
soak».

*The evidence*, from that instance's own `release-run.json` and `chronology.json` (the
`20260930-090243` diagnostics, re-read 2026-10-01): a `release-scale` run (256,341 articles at
preflight, 257,951 when the soak was armed, 4 cores, 3,740 MB); the soak window ran 2026-09-19
15:03:34 to 2026-09-22 15:03:36 (+02:00), 72.0 h, `ended_by` window-complete, `outcome` done, one
stretch, no restart seen in the heartbeats, process `pid 3266`. There are 73 hourly heartbeats,
every `elapsed_h` step 1.0 h (the beats' own timestamps 3,595 to 3,605 s apart) and none dropped,
with the scheduler running and the kill switch off on every one and the memory guard never engaged
(0 engagements). RSS: first 958.7 MB, minimum 788.2, maximum 1,623.1, last 1,260.9, and the medians
of the three 24-beat days (beats 0 to 23, 24 to 47, 48 to 71) 1,349.15 / 1,307.05 / 1,322.95 — no
climb. The same process ran 2026-09-19 04:36:15Z to 2026-09-24 14:14:03Z (129.6 h) and ended by its
own shutdown hook (chronology: `clean`, `end_basis` «this session's own shutdown hook»), so it
contains the whole window. The run's own soak-window block (`phase_results.collect.soak_window`,
the artifact row D's table describes for its six blocks; the seventh, `wiki_lane` (the Wikipedia
lane, row P's), is not in that table and reads `measured: false` on this run; this close does not
change row D), taken by `pid 3266` as the window ended, reads 80.46 h of process uptime from
2026-09-19T04:36:14Z (`reaches_bar: true`) and 0 memory-guard engagements over 3.35 days. The
report's own P0.3 line reads `pass` (+79 MB over 2 passes, 1,718 → 1,797 MB) but covers only the
retained ~2 h: it is **not** the multi-day evidence, the heartbeats are.

**What this close does not claim** — recorded here so nobody has to rediscover it, none of it
reopening the ruling:

- `soak-window.json`'s `reaches_bar: true` on 090243 (119.69 h, basis «process uptime») and
  chronology's `bar_reached: true` (basis «collection», a stretch of 430,600 s) are both read from
  the instance's CURRENT process (`pid 2093`, started 2026-09-25T07:38Z), not from the soak
  process: `soak-window.json` describes only the process that produced the export, and `pid
  3266`'s build predates PR #1172, so its collection was not recorded (`collection_recorded`
  false) and the collection-basis bar cannot count it. The close rests on the release run's own
  soak-window block (80.46 h, above) and chronology's process basis (anchored at the run's start,
  2026-09-19T04:39:01Z, 8.4 h before the soak was armed, it reaches 72 h on 2026-09-22T04:39:01Z:
  `summary.process_bar.reached_at` in `chronology.json`).
- That later process (`pid 2093`) engaged the memory guard **76 times in 119.7 h** (15.2 a day,
  2,483.7 s engaged, 0.58 % of the time), in `soak-window.json`. It is outside this row's clause.
- «The previous session ended cleanly» is read here from chronology's session list (`pid 3266`).
  Session forensics' `previous_session` on 090243 is a later 786 s process (`pid 2164`, unclean),
  so the key the "Read both signals" paragraph points at names a different process from the one
  that ran the window.
- The other windows of the round are recorded and do not close the row: `085214` (72.0 h, done)
  climbs — day medians (the same beats) 2,116.55 / 2,481.25 / 2,545.35 MB, last beat 2,625.4, 7
  guard engagements, P0.3 `not-measurable-here`, its window process ended unclean 8.2 h after the
  window; `085218`'s 72.0 h exists only in its live state file (`live_run`, and chronology's
  `release_run`, which reads the same file): its last liveness tick is 5.1 minutes after the
  window, in the bundle phase, unclean, and its final report was never written; `085230` reached
  30.0 h; `101538` was cancelled.

**New in this window, and worth a glance while it runs (P6, 2026-09-11):** every
`collect_perf.jsonl` sample now carries a `loop` block — the API server's own event-loop lag,
as the share of a 10 s window that was blocked. It is *not* a gate condition and closes
nothing here; it is recorded because the bench that motivated it could not make the collector
starve the server (a synchronous handler cost 3.4-3.5 ms at p50 whether 0 or 32 workers were
collecting), and a three-day run at release scale is the first thing that could contradict
that. `loop_lag_ticks` in the pass summary is 0 on a healthy pass by design, so a non-zero one
is the signal — and if the accompanying note says the back-off *stood down*, the loop was
being blocked by something that is not the collector.

---

### Row C — diagnostics on the ~1M-article instance

**Carried from `0.3` §5.** Was row 3's bar from 2026-07-30 until 2026-08-23, when the
maintainer ruled that the ~1M instance *"is NOT the v0.3 release-scale one"* and the bar moved
with the instance it describes. Row 3 closed instead against the real release-scale instance
(40,260 articles).

**What `0.3` gave up:** every figure in the 2026-08-23 bundle is evidence **at forty thousand
articles**. Anything that only appears an order of magnitude higher — a member that finishes in
19 minutes here and does not there, a query whose plan flips, a memory profile that only bends
at scale — is **unmeasured** for `0.3`, not measured-and-fine. The two members that died in
that bundle are the reminder that the run is where such things surface.

**Closes when:** one bundle from the ~1M instance whose coverage block reads `complete: true`,
on a build carrying the `statement_deadline` fix, with every member non-zero. The P0
data-safety trio has already been read at that scale (2026-08-12: 1,048,725 articles, 21.0 GB,
backup RSS +1.4 %), so what is owed is the *diagnostics* run, not the safety evidence.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies.** `RC08.3` asked where register ruling
**E1** («Automate this in the diagnostic bundle.») lands. It came back blank, so its stated default is taken
as a labelled **ASSUMPTION: (a) — `month-occupancy.json` becomes a member of THIS row's bundle**, sampled as
the ruling specifies, with no operator script run; PROMPT_06 slice 3 (the date-aware month block and its
re-index) reads it from the bundle rather than from a hand-run measurement. This adds ONE member to the
bundle and changes no bar: the row still closes on a `complete: true` coverage block with every member
non-zero — which the new member must therefore satisfy too. The re-index remains the operator's. Reversed by
writing a letter at `ANSWER RC08.3`.

---

### Row D — row B's evidence is readable from one artifact · *proposed* · BUILT · CLOSED 2026-10-01

**Why it is a row.** Row B's bar is a property of a three-day window, and until now no single
artifact answered *"did the soak pass"*. The instruments existed — `collect_perf`, the memory
guard, the write gate, the `wal_bytes` hourly series, the latency reservoir, the error log,
session forensics — with **different and mostly undocumented windows**, several of them far
shorter than three days. Assembling the answer by hand is how a two-hour reading acquires a
three-day label.

**Built in this PR:** `GET /api/diagnostics/soak-window`, riding the all-diagnostics bundle
as `soak-window.json`. It adds no sampler. It composes the durable readings that already exist
and states, per block, **the window it actually read**:

| Block | Reading | Its window |
|---|---|---|
| `window` | process uptime, and whether it reaches 72 h | the soak's own clock |
| `memory_guard` | engage cycles per day, paused share | process-cumulative, aligns with the clock |
| `wal` | the `wal_bytes` maximum inside the window | hourly snapshots, infinite retention, filtered down to it |
| `write_gate` | busy share, contention | process-cumulative, aligns with the clock |
| `database_stats_latency` | the `/api/database/stats` p95 | the last ≤512 requests — **not** the soak |
| `interrupted` | statements aborted mid-flight | a rolling 2,000-record log — a **floor** at capacity |

Three counters had to become durable for this to be possible at all: the write gate now
accumulates `total_held_s` on release (an in-flight hold stays in `held_for_s`), the memory
guard counts `engagements` and `total_engaged_s` (closed episodes only), and the error log
recognises both shapes of an aborted statement — the typed `StatementTimeout` and SQLite's raw
`interrupted` — and publishes its own `records_cap` beside every count, so the retention that
bounds them travels with them.

It is **verdict-free** on purpose: `window.reaches_bar` is a fact about the window's *length*,
and what the numbers inside it mean is the maintainer's reading. It does not re-derive P0.3's
RSS verdict — that stays P0's — and it publishes no composite.

**Closes when:** one soak-window report from a run of ≥ 72 h exists and is read alongside the
P0.3 report. Until a real soak happens, this row is *built, unread* — the honest state, and
not the same as closed. **Met 2026-10-01: see «READ ON A REAL RUN AND CLOSED» below.**

**DRIVEN END TO END AT FIXTURE SCALE (2026-09-15).** A synthetic corpus seeded through the real
`index_article` (`scripts/ui_clickthrough_seed.py`, 440 articles), the app served on loopback,
and the report read twice — once from `GET /api/diagnostics/soak-window` and once as
`soak-window.json` out of the 73-member `GET /api/diagnostics/all` archive, which is the "ONE
artifact" this row is named for. Per block, what fixture scale could and could not reach:

| Block | At fixture scale | What it needs from row B |
|---|---|---|
| `window` | **measured** — 0.01 h, `reaches_bar: false` | the 72 h itself: only a real soak can make that `true` |
| `write_gate` | **measured** — 1 grant, `busy_share` 0.0098, 0 contended | nothing; the counters are process-cumulative and already live |
| `interrupted` | **measured** — 0 this session, 9 log records, `at_capacity: false` | nothing; a long run is what makes `at_capacity` meaningful |
| `database_stats_latency` | **measured after one call** — p95 12.8 ms at `window_n: 1` | volume: it reads a 512-request reservoir, so its `window_n` is what makes a p95 readable, and the payload already says the window is not the soak |
| `memory_guard` | **unmeasured** — "uptime is 77.9 s, under the 300 s floor a per-day rate needs to mean anything" | any run over five minutes clears the floor |
| `wal` | **unmeasured** — "`wal_bytes` has never been recorded on this install" | the hourly, off-peak recorder has to have run, i.e. a scheduler up for hours against a real corpus |

So **the mechanism is proven and the window is not**: nothing in the tree can make
`reaches_bar` true, and `memory_guard` / `wal` leave `unmeasured` for the same reason —
elapsed time on the operator's machine. The two blocks that report `measured: false` do so with
a reason and are listed in `unmeasured`, which is the honest shape and not a reading of zero.

**READ ON A REAL RUN AND CLOSED (2026-10-01).** The row's exit text is «one soak-window report from a
run of ≥ 72 h exists and is read alongside the P0.3 report». Instance `090243`'s release run
`20260919T043901Z` is that run, and the artifact is its own report: the `collect` phase of
`release-run.json` (taken 2026-09-22T15:03:36 +02:00, the moment the run's 72.0 h `soak` phase ended)
holds the six blocks of the table above (`phase_results.collect.soak_window`) and, in the same phase,
the P0.3 collector check re-taken (`phase_results.collect.collector`). Side by side, with no verdict
attached (the report is verdict-free on purpose):

| Block | What the soak's own process (`pid 3266`) read |
|---|---|
| `window` | 80.46 h of process uptime from 2026-09-19T04:36:14Z, `reaches_bar: true` (the run's `soak` phase is the last 72.0 h of it, from 2026-09-19T15:03:34 +02:00; the first hours were the run's preflight, row 5, P0 and restore phases) |
| `memory_guard` | 0 engagements, 0.0 s engaged, over 3.35 days |
| `wal` | 63 hourly points inside the window; maximum 1,499,707,640 bytes, minimum 18,508,256 |
| `write_gate` | 11,851 grants, 6,841 contended; `busy_share` 0.9402; longest hold 500.25 s (`oo-collect_4`); longest wait 902.76 s; 0 timeouts |
| `database_stats_latency` | 4 requests, p95 4,796.8 ms — the route's last ≤ 512 requests, **not** the soak |
| `interrupted` | 0 this session; the log is at its 2,000-record cap, so the count is a floor |
| P0.3 (`collector`), same phase | `pass`: +79 MB over 2 passes (1,718 → 1,797 MB) in the retained window, about 2 h |

**What this close does not claim.** It claims that the report is READABLE from one artifact, which is
what the row is for; it does not say the figures are good (`write_gate`'s 0.9402 busy share and 6,841
contended grants are for the collector's own work to read, not for this row). The P0.3 line covers the
retained ~2 h, so it is not the multi-day memory evidence: the 73 hourly heartbeats are, in row B's
section. `database_stats_latency` describes four calls, not the window. The seventh block of the report,
`wiki_lane` (the Wikipedia lane, row P's), is not one of the table's six and reads `measured: false`
here — `OperationalError: no such table: versioned_changes`, listed in `unmeasured`, «not a reading of
zero»; the lane's own 72 h run is row P, still open. The standalone `p0-validation.json` in the same
bundle is NOT what row D reads: it is the P0 report the run took at its start (created
2026-09-19T14:22:40 +02:00, 41 minutes before the run armed its soak at 15:03:34, with one collector pass
in its window: its `p0_3_collector` is `not-measurable-here`). The same instance's later process
(`pid 2093`, started 2026-09-25T07:38:00Z) has a second report in `soak-window.json` (119.69 h); row B's
section records that process, and this close does not rest on it.

---

### Row E — row A's demonstration has tooling that can state its own result · *proposed*

**Why it is a row.** Row A's closing clause is a **spot-check that a previously-disqualified
source is still disqualified after the import**, and the reason it is worded that way is that
the 2026-07-24 defect was invisible: the merged-in source carried a plausible legal value, not
a NULL and not an error. A spot-check performed by hand, on an instance with tens of thousands
of sources, is exactly the shape of check that gets reported as done without being done.

**What it wants:** a bounded report that names, for a committed import, the source verdicts it
stamped **and** the before/after status of the sources that were disqualified before it —
enough that the closing clause is a number a reader can re-open, not a memory. The measurement
side already exists in pieces (`source_qualification_attempts` carries an append-only history,
and the qualification export was built 2026-09-04); what does not exist is the before/after
pairing across an import.

**Not built here**, and deliberately: it is tooling for a data-safety demonstration, it wants
its own reviewed slice with the full skeptic matrix, and building it in the same PR as the gate
that asks for it would leave nobody to check it against the ask.

**BUILT 2026-09-07** (prompt 07 S5, `src/catalog/qualification_integrity.py` +
`GET /api/diagnostics/qualification-integrity`, a member of the all-diagnostics bundle as
`qualification-integrity.json`). It answers the closing clause and does **not** need the
before/after pairing this row asked for, because of one property of the data: the attempt log
**is** the "before". `source_qualification_attempts` is append-only, it is carried by the merge
with ids remapped, and `evaluate_and_stamp` writes the attempt row and `Source.status` in the
same transaction — so for any judged source the two must agree, and

    status == the verdict of its NEWEST judging attempt

A violation is exactly the 2026-07-24 inversion. That makes the clause answerable **after** an
import rather than only around one, so an operator who has already run it can still answer this
row months later from the corpus itself.

**What it publishes:** both directions kept apart (`laundered` — judged disqualified, no longer
disqualified, the direction Row A names; `demoted` — the same stamp loss starving a source out
of collection), each **named** up to a cap with the exact total beside it; the disqualified
sources it examined, named (Row E's "state its own result"); and `checked.with_judging_attempt`
as the denominator, because a corpus with no judgements reports `not-measurable-here` rather
than a clean bill of health — "nothing wrong" and "nothing to look at" are opposite findings.

**What it cannot see, stated in the payload:** a regression that dropped the stamp columns *and*
the attempt rows together leaves the receiving instance no "before" either. That is what the
denominator is for.

**Still open on this row:** the RUN. The check is Row A's instrument, so it closes when Row A
does — read `qualification-integrity.json` out of an all-diagnostics bundle taken after the
committed import, and the clause is answered by a number naming the sources.

**DRIVEN END TO END AT FIXTURE SCALE, IN BOTH DIRECTIONS (2026-09-15).** On the same seeded
instance as row D, read through `GET /api/diagnostics/qualification-integrity` and out of the
`GET /api/diagnostics/all` archive:

- **Clean corpus** → `verdict: "consistent"`, *"Every one of the 14 judged sources still carries
  the verdict its own attempt history last recorded"*, with `checked.with_judging_attempt: 14`
  against `sources_total: 18` and the one currently-disqualified source NAMED
  (`verified_disqualified_sample: ["prefcentre.example"]`). The denominator is the point: it is
  what separates *nothing wrong* from *nothing to look at*.
- **Seeded inversion** (that source's live status flipped to `qualified` while its newest
  judging attempt still reads `disqualified` — the exact 2026-07-24 shape) → `verdict:
  "inversions-found"`, `laundered_total: 1`, `demoted_total: 0`, and the row named in full:
  `{domain: prefcentre.example, live_status: qualified, last_judged: disqualified, judged_at:
  2026-08-11T17:54:21+00:00, criteria_version: v1}`. The finding arrives intact in the archive
  member, not only from the function — `test_the_bundle_member_carries_the_finding_not_a_stub`
  pins that layer, and this run confirms the HTTP layer above it.
- **Reading `laundered_total` after an import (2026-10-01, rank 14).** A number above zero is not by
  itself a laundering. The report splits it: `auto_repairable_total` is what the boot repair
  withdraws by itself (a source still on the catalogue's own stamp), and
  `not_auto_repaired_measured_here_total` is what it deliberately LEAVES (a verdict measured here or
  adopted from an import is never changed by an imported history, rule 12 = b) until this install's
  own re-check, which the forced re-check list brings forward. (This reads the report; it does not
  change how row A is judged.)

So **"tooling that can state its own result" is true today**: it states a verdict, both
directions apart, names the sources, and refuses to read a corpus with no judgements as a clean
bill of health. **What it needs from row A is the IMPORT** — this check cannot supply one, and
a `consistent` verdict on a corpus that has not been imported into says nothing about the
merge. Row A's operator step is: take an all-diagnostics bundle AFTER the committed import and
read this member; the clause is answered by `inversions_total` with the sources named beside
it, whichever way it goes.

---

### Row F — the browser bar reaches a human, a second engine, or is closed as-is · *proposed* · CLOSED as-is 2026-09-15

**THE VERIFICATION BAR — the sentence every surface cites, and the one place it lives.** Ruled
2026-09-15, **Q1128 = a** (`RULINGS_INDEX.md`), which **Q117 = a** used to close this row as-is:

<!-- release-notes: verification-bar -->
> Chromium in the sandbox + the maintainer's click-through = verified; Gecko best-effort.

It is quoted from HERE and nowhere else — `scripts/release_notes.py` reads it out of this file
behind the marker above rather than carrying a copy, because a mirrored copy fails in the
safe-looking direction: reword the gate and a copy goes on quoting the old wording while every
check still passes. `docs/plans/2026-09-12-beta-pathway/_WORKING_MODE.md` §3 carries the same
sentence verbatim as the instruction to a building session; this block is the citable form.

**Both halves, or neither.** A surface that a session drove in Chromium and no human has opened
is stamped *"Chromium-verified (remote sandbox) · awaiting human UX pass"* — that is not
*verified*, and the stamp may not be shortened to it. A Gecko run is a strengthening nobody is
owed: its absence never blocks a row, and its presence is recorded as *"Gecko-verified (VM)"*
beside the Chromium record, never instead of the click-through.

**Where it stands.** `0.3`'s row 8 closed against its literal bar, and the stretch matrix was
executed on 2026-08-20 (`docs/audit/UI_CLICKTHROUGH_2026-08-20.md`): all 17 themes, the Reader
surface, a real import fixture, the a11y axis with vendored axe-core, five lens drills. Every
stamp from it reads **"Chromium-verified (remote sandbox) · awaiting human UX pass"**, which is
the honest wording and also an open loop.

**What that report itself left open:** the 12-locale sweep (4 covered), honesty rule 9
(adversarial screenshot reading), and the Gecko/AppVM bar.

**Three ways this closes, and they are not equivalent:** a human click-through (what the stamp
is waiting for); a second-engine run under the AppVM recursive environment (which would let the
stamps read *"Gecko-verified (VM)"*); or a deliberate ruling that Chromium-in-sandbox plus the
audit is the bar `0.4` ships against, recorded in §3. The third is a legitimate outcome. What
is not legitimate is carrying "awaiting human UX pass" into a second release without saying
which of the three happened.

**What the 2026-09-08/09 live visual audit + fix pass added, and what it did not close (2026-09-09).**
Two of the three open items above moved:

- **The 12-locale sweep is done.** All 12 locales were driven live, crossed with all 17 themes and 5
  viewports, plus `prefers-reduced-motion`, `prefers-contrast`, greyscale and colour-blind simulation
  (`docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md`, §7). The four-locale gap this row records is closed.
- **Honesty rule 9 (adversarial screenshot reading) ran in a different form than the rule imagines.**
  Rather than one pass re-reading its own screenshots, three independent adversarial re-verifiers
  re-derived every fix against pre-fix code and were asked specifically for fixes that do NOT work.
  They found one real regression (a French-locale mixed-language screen), confirmed its repair by
  revert-reproduce-restore, and reported two residuals the fix pass had missed. That is the *function*
  rule 9 exists for; whether it satisfies the rule as written is a maintainer call.

**Neither closes the row.** The Gecko/AppVM bar is untouched, and every stamp still reads
*"Chromium-verified (remote sandbox) · awaiting human UX pass"* — deliberately, because no human has
used the app. The three ways this closes are unchanged. What the audit does change is the cost of the
third option: a ruling that "Chromium-in-sandbox plus the audit is the bar" is now a ruling about a
much larger body of evidence than it was on 2026-08-20, and §0.1b of that report is the honest
counterweight — the instrument itself was wrong twice, and both times the error ran toward a false
pass.

---

## 2b. The rows added 2026-09-15 (G–V) — from the answered roadmap sheet

*Row W, at the end of this section, was added 2026-09-27 by `RC01` = a, not from the sheet.*

Every row below is **ruled** by the question IDs it cites (labels verbatim in `docs/ledger/RULINGS_INDEX.md`);
sentences marked *proposed placement* or *design note* are the planning session's and bind nobody. "Closes
when" names an artifact a later reader can re-open. Where the sandbox cannot measure a bar the row says so
and names the operator step (`not-measurable-here` is a legitimate state, `pass` on a proxy is not).

### Row G — `0.3` closed and the version flipped · ruled (Q109 = a) · CLOSED 2026-09-28

**What it must demonstrate.** The `0.3` board's row 5 (the Tier-A quarantine run, 8 articles — the four
commands in `RELEASE_0.3_GATE.md` §7.1) is run from the maintainer's machine and the `v0.3.0` tag exists;
then `pyproject.toml` flips to `0.4.0` (the 0.2→0.3 sequence: pass → tag → flip). **Closes when** the tag is
on the remote and `main` reads `0.4.0`. **Operator:** both steps. Brief `S03-01`.

**PREMISE CHECK (2026-09-15, found while writing brief `S03-01`; hand-verified):** the remote ALREADY carries
`refs/tags/v0.3.0` at `917e8095` — the 2026-08-23 merge of PR #979 — and a published GitHub release `v0.3.0`
(`prerelease: true`, created 2026-08-23T12:39Z, wheel + sdist + `SHA256SUMS` uploaded by the release
workflow), cut BEFORE row 5 was run and before this board or the answer sheet were written; the 0.3 gate's
§7.3 says "do not start this until row 5 is ticked", `README.md:8` still reads "latest tagged release:
`v0.2.0`", and the 0.3 gate's §1/§3 record no tag. So the sheet's "the `v0.3.0` tag from your machine" and
this row's "then the tag" describe a step that is ALREADY DONE as a pre-release; what remains is row 5 (the
quarantine run), the maintainer's word on whether that pre-release IS the 0.3 tag or is to be superseded by a
full release once row 5 is run (a tag cannot be moved; a second release can be published), the README /
0.3-gate records, and the version flip. Q109 = a stands as answered; its premise is corrected here and in
the brief, per the recorded rule that a plan's premise is checked in the tree, never accepted from the
document that states it.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC01` asked whether the version flip may proceed on the
existing `v0.3.0` pre-release without row 5. It came back blank, so its stated default is taken as a labelled
**ASSUMPTION: (b) — this row keeps waiting on 0.3 row 5.** The version stays `0.3.0` until the maintainer runs
the quarantine; A1 stays `deferred` with no date; the premise check above is unchanged and still describes the
pre-release. Reversed by writing a letter at `ANSWER RC01`.

**ANSWERED 2026-09-27 — `RC01` = (a), in chat:** «OK for RC01, I'll do the versino switching after all current draft PRs are merged». The 2026-09-15
ASSUMPTION (b) above is reversed. The `v0.3.0` pre-release of 2026-08-23 IS the `0.3` close (`S03-01`'s
operator step 1, answered); `0.3`'s row 5 leaves this row for row W, an operator step beside rows A–C; and the
flip itself (`pyproject.toml`, the README `**Version:**` line and a `0.4.0` section in `docs/CHANGES.md`,
`S03-01`'s S3) is the maintainer's own act, after all current draft PRs are merged. **Closes when**
`main` reads `0.4.0`; the tag is already on the remote. The README's stale «latest tagged release: `v0.2.0`»
was corrected in the PR that recorded the answer (#1191); its version number waits for the flip.

**CLOSED 2026-09-28 — `main` reads `0.4.0` (PR #1195).** The maintainer merged the draft PRs and tagged
`v0.4.0` on `ad0f2062`, the PR #1191 merge, publishing a GitHub pre-release at 02:06 UTC with GitHub's own
generated notes. The version file was not changed, so that tree reads `0.3.0`: it calls itself `0.3.0` in the
sidebar, `doctor`, diagnostics bundles and backup manifests, and `release.yml` run 36368552522 stopped at
«Verify the tag matches the package version» (`tag=0.4.0 pkg=0.3.0`) after its full-suite job passed, so no
wheel, sdist or `SHA256SUMS` were built and no generated notes were written. At the maintainer's pick in the
project thread, PR #1195 is `S03-01`'s S3: `pyproject.toml`, the README `**Version:**` line and status, a
`0.4.0` section in `docs/CHANGES.md`, the version lines in `docs/CONTRIBUTING.md`, `docs/ROADMAP.md` and
`CLAUDE.md`, this row and the ledger. **The tag is the maintainer's step**, after the merge: delete the
`v0.4.0` GitHub release (not the tag), then move the tag onto the merge (`git fetch origin && git tag -f
v0.4.0 origin/main && git push -f origin v0.4.0`). `release.yml` then runs on the moved tag, finds no release
and creates one with the generated notes (the shipped rows since `v0.3.0` and the no-telemetry re-check, row
V), the wheel, the sdist and `SHA256SUMS`. Keeping the existing release instead also gets the files, but the
workflow then keeps its notes and appends only the checksums, so the no-telemetry re-check would not reach
the notes. If no run starts on the moved tag, Actions → Release → Run workflow on the tag does the same.

**PUBLISHED 2026-09-28 11:00 UTC.** A first attempt from GitHub's website re-published the release on the
old tag and started no run: the website can neither delete nor move a tag, so the release reused
`ad0f2062`. With no release left in place, the maintainer then moved the tag at 10:13 UTC from a GitHub
Codespace on `main` (`ad0f2062...00af1d9c`, the PR #1195 merge). `release.yml` run 36408430314 passed its
full-suite job on `00af1d9c` (pytest 10:14–10:59 UTC), passed «Verify the tag matches the package version»,
found no release, and created the `v0.4.0` pre-release with the generated notes (the shipped rows since
`v0.3.0`, the no-telemetry re-check with the socket-importer ratchet passing, and the verification bar), the
wheel, the sdist and `SHA256SUMS`.

### Row H — `docs/SECURITY.md` enumerates every host; the consent hover lists them per lane · ruled (Q1001 = a, Q1002 = a) · BUILT, the delegated click-through passed 2026-09-27

**What it must demonstrate.** The "full set of endpoints the app can reach" section names the hosts the tree
already reaches and the section omits today (the Wikidata Query Service the default-on discovery ride-along
reaches, the Wikipedia Action API, ORES / Lift Wing, the Wikimedia dumps host, the OSM mirrors), and from
then on every PR that adds a host adds it there **and** to the consent popup's hover in the same diff, with a
repo test that greps the fetch sites against the list (Q1001). The one popup stays; its hover lists, per lane,
the hosts that lane will contact, and its body names the lanes that are on (Q1002). **Closes when** the test
exists and is green on the tree that tags, and a Chromium click-through of the popup hover is recorded
(Q1128). Docs-only first (the SECURITY.md half ships as its own PR, per Q1001's "now"). Brief `S04-01`. *Premise check (brief `S04-01`):* two more hosts the tree reaches are absent from the list — `www.wikidata.org/w/api.php` (`src/catalog/wikidata_enrich.py:33`) and `huggingface.co` (`src/llm/weights_pin.py:30`, `vllm_lifecycle.py:241`); the consent dialog has no hover `title` today (`index.html:3133–3149`); no test references `SECURITY.md`.

### Row I — The import lifecycle · ruled (R1–R3; Q201–Q207, Q214, Q216, Q217, Q221, Q222) · OPEN

**What it must demonstrate.** Four stages shown as four rows with their own progress (Q202); the three safety
statements at the moments ruled — files removable after the swap, close/update safe after the swap (a durable
cursor resumes stages 3–4 on the next boot), analytics complete after stage 4 (Q203); stage 4 (the deferred
re-index) inside the import experience as its own row, progress from the existing resume status endpoint, a
link to the task manager (Q204), auto-resuming on boot with "resuming re-index (N left)" (Q205); ONE poll
chain, ONE bar owner, rows patched in place (Q206) — the blinking and overlap R2 named are a defect and their
absence is a bar; a fresh page on reopen (R1) with one quiet "Last import · date · N articles · open report"
line linking the persisted import report (Q201 — this SUPERSEDES the 2026-07-16 `_uxShowLastCompletedSummary`
behaviour); the "Details" block removed (Q207, an ASSUMPTION at the sheet's default, supported by R2);
`import-queue/*` is the one path — `v2/restore/*` deleted after anything only it does moves into the queue,
`reindex-*` wired (Q214); verify + swap once per **K = 3** backups (Q216 ⛔ = a — a checkpoint the code counts:
a two-item group reuses the working copy, `merge_batches` 2 vs 1, per the recorded 2026-09-07 measure);
prefetch only if the first real `verify_copy` timing shows "prepare" still dominating (Q217 — measure first);
each lane's import is a row with the same four stages when lanes exist (Q221); history lives in Settings →
Backup (Q222 = b). **Closes when** (1) a recorded Chromium click-through shows the four rows, the three
statements at their stages and the fresh page with its one line; (2) a test kills the app between stages 3
and 4 and proves the resume; (3) a repo test asserts the `v2/restore` routes are gone (anchored to the router
definitions, never the app singleton's live route table, per the recorded flakiness lesson). Brief `S04-02`. *Premise check (brief `S04-02`):* the durable cursor exists (`reindex_job.json`, the resume endpoint) but boot only LOGS the backlog and an interrupted run is parked PAUSED — the auto-resume Q205 names is the delta, not a fact; the sheet's "zero frontend callers" holds.

### Row J — The export · ruled (R4, R5; Q208–Q213, Q218–Q220, Q1008) · OPEN

**What it must demonstrate.** The folder `YYYYMMDDHHMM_OpenOmniscience_Backup` (Q212 = c spells the token
out, amending R5's literal `OOS`), local time (Q210), `_2`, `_3` … on collision (Q211); **always a full new
backup, no reuse** (Q213 = c — the incremental reuse pool is not consulted by exports; state the cost in the
panel: every export writes every volume); the completion panel listing volumes · total bytes · per-table counts
with articles first · files copied per category (dumps, models, newsletters) · elapsed · destination ·
encryption state · schema version · app version · the licence lines that apply (Q208, Q1008 — the press
lines now; OSM lines wait on Q823 ⛔); `BACKUP_SUMMARY.md` beside `volumes.json` with the same facts (Q209);
re-read every volume after writing and check its checksum, default ON, the panel says "verified" (Q218);
never a scheduled export (Q220 = c); the Wikipedia, OSM and law lanes as opt-in members with their sizes shown
before the export starts (Q219 — the member hook now, members as the lanes land). **Closes when** an export
produced on the reference VM shows the folder name, a `BACKUP_SUMMARY.md` whose figures equal `volumes.json`'s,
and a panel reading "verified"; the artifact is the folder listing + the summary file quoted in the PR.
Brief `S04-03`. *Premise check (brief `S04-03`):* the sheet's "no `OOS` string exists in the tree" is FALSE — `src/bulletin/annexes.py:122–130` (`YYYYMMDD_OOS_Bulletin_<cadence>`, `_2` and up), `src/bulletin/evidence.py:232` (`-OOS-…-evidence.zip`), `src/bulletin/store.py:19–60`; whether Q212 = c's spelled-out token also renames the bulletin, evidence and store names is an OPEN DETAIL for the maintainer (the brief lists it, never decides it).

### Row K — ONE backup-format bump · ruled (Q215 ⛔ = a, Q310, Q313, Q404, Q409, the Q701 note) · **BUILT 2026-09-16 (`S04-04`), OPEN on the operator's real restore**

**What it must demonstrate.** One format-version bump carrying five payloads, so the 0.5 storage half has one
format to exercise (Q301 = c makes this row its precondition): (1) the restore path normalises alpha-2 →
alpha-3 while importing, so every older backup stays restorable forever, and the gate proves it with a
duplicate-key scan after restoring a PRE-migration backup (Q310); (2) ALL rings ride the backup, shipped ones
included (Q409 = b) — *design note:* a restored backup's shipped rings must never override a newer release's
shipped rings, so the member carries the ring file's version and the newer wins; (3) the `keyword_translations`
table (term, source lang, target lang, text, model, prompt version, created), never the trusted index, always
≈ (Q404 🔒 = a); (4) **the fetch / scrape history of everything the app downloads** — press feeds, the
Wikipedia lane, and later OSM and law — rides the backup so a fresh install restored from an old backup does not
re-download the same pages and prioritises other fetches, with a **"trust the backup scrapping history"** toggle
offered at install and at import (the Q701 note, verbatim intent; the toggle's copy ×12 and its caveat
visible per the informed-consent non-negotiable); (5) the legacy single-file restore half is kept forever,
as its docstring commits (Q215 ⛔ = a — register C1 closed); exports carry both `country` and `country_iso3`
for this one release (Q313). **Closes when** the maintainer restores a real pre-migration backup on their
machine and the duplicate-key scan reports 0 duplicates (operator; the scan's output is the artifact), the P0
data-safety trio is re-run green on the new format (the `0.3` runbook), and a CI restore of a fixture backup
proves each of the five members round-trips. `not-measurable-here` for the real-restore half. Brief `S04-04`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC02` ⛔ (C1 «a, but wait for version 0.7» against
Q215 = a) came back blank on a ⛔ question, so it **stays PENDING and is never defaulted**. Payload (5) is
unchanged: the legacy single-file restore half is kept forever as its docstring commits, `S04-04` builds on
Q215 = a, and no 0.7 removal row exists. Nothing in this row moved.

**BUILT 2026-09-16 (`S04-04`, branch `claude/backup-format-bump`). ONE bump: `oo-backup-2` →
`oo-backup-3`, and `ACCEPTED_BACKUP_SCHEMAS` carries BOTH — a set a future bump may only add
to, which is what makes Q215 = a structural rather than documentary. The volume container was
deliberately NOT bumped: its slicing, parity and manifest are unchanged, so telling an older
build it cannot read a set it reads perfectly would be a second bump the row does not ask for.**

**ROW K IS THE 0.5 STORAGE HALF'S PRECONDITION (Q301 = c), so what it leaves for `S05-02` is
stated rather than implied.** The normaliser is direction-agnostic and reads ONE constant,
`CANONICAL_COUNTRY_FORM` — 0.5 changes that literal and nothing else in the module. But the
ordering around it is load-bearing and was measured, not assumed: the normaliser rewrites the
STAGED copy and never the live corpus, so flipping the constant while the live corpus is still
on the other form makes every value-keyed join miss. Reproduced under simulation — one law
document came out of a restore as TWO rows while the report said "2 rows converted". No
automatic verdict is available (a real corpus legitimately holds values the converter refuses,
and can be honestly mixed), so every restore now MEASURES the gap as
`_country_codes.live_corpus_in_target_form` (0 today) and
`test_flip_day_is_REPORTED_when_the_live_corpus_is_still_on_the_other_form` is the tripwire.
**The live rewrite lands BEFORE the flip, never after.**

**The five payloads, and what each is pinned by.** (1) Normaliser + duplicate-key scan —
`src/backup/country_codes.py`, merge step 0; `GET /api/diagnostics/country-code-duplicates` and
the `all`-bundle member; `tests/test_country_code_normaliser.py` (24). (2) All rings —
`_ring_members` carries both shipped files and the operator's local one, `_restore_ring_members`
places only the local one and REPORTS the shipped ones as carried-not-placed. *The design note's
version comparison was declined with a reason:* precedence by SOURCE (the loader reads local
first, shipped last) gives the same newer-wins guarantee by construction, with no version to
carry, no comparison rule, no tie-break, and it fails closed where a comparison fails open.
`tests/test_backup_rings_member.py` (12). (3) `keyword_translations` + migration `5adfcc0ed33e`;
writers stay `S04-06`'s. (4) The fetch-history member and its toggle on BOTH surfaces the Q701
note names, ×12, caveat visible; `last_checked_at` deliberately not adopted. (5) Legacy restore
KEPT — C1 closed as KEPT in `OPEN_QUEUE.md`, two `FUTURE_DEVELOPMENTS.md` sections corrected to
RECORDS, RC02 ⛔ still PENDING and the conflict listed rather than resolved. Exports carry both
`country` and `country_iso3` (Q313).

**The CI half of "closes when" is MET:** `tests/test_restore_fixture_matrix.py` builds a
genuinely-signed `oo-backup-2` artifact with the REAL writer in one data dir and restores it
into a DIFFERENT one through `restore_legacy_path`, asserting all five payloads round-trip and
that the duplicate-key scan reports **0**. Two subprocesses, because `live_db_path()` resolves
through a module-level engine singleton and an in-process variant would have been a self-restore
— which sees every row as a duplicate and can never exercise a handler.

**WHAT KEEPS THE ROW OPEN:** the operator's own clauses — a real pre-migration backup restored
on the maintainer's machine with the scan's output as the artifact, and the P0 data-safety trio
re-run green on the new format (the 0.3 runbook). Both are `not-measurable-here`.

**Two adversarial passes found four defects that the build's own tests did not, each
hand-verified before being acted on.** A collision in the normaliser rolled back the WHOLE
`UPDATE` statement, so one colliding pair stranded unrelated rows sharing that spelling and
they landed as duplicate documents — now retried row by row, so a collision costs exactly the
rows that collide. `stat_subscriptions.country` is exempt from the rewrite (Q311) but reaches a
value-keyed join from a free-text box that folds neither case nor form, so two installs typing
"FR" and "fr" duplicated a subscription; the comparison is now case-folded and the stored value
still never rewritten. The migration crashed `alembic upgrade head` against a table
`create_all` had already made — fatal on the restore path, which never calls `create_all` —
now guarded like its siblings. And SQLite's UNIQUE treats NULL as distinct, so the declared
five-column identity enforced nothing when the provenance was unset; a unique expression index
over the COALESCEd columns now matches the merge key exactly.

### Row L — ISO 3166-1 alpha-3, step 1 · ruled (R6; Q301 ⛔ = c, Q302, Q303, Q307–Q309, Q311, Q312) · OPEN

**What it must demonstrate.** The DISPLAY + BOUNDARY half of Q301 = c (FULL, staged): every code the user sees
is alpha-3; **the code is displayed and the full country name, in the UI language, is in the hover bubble**
(Q302 as the maintainer wrote it — the note inverts the option label; the hover is the #oo-tip convention,
invariant #17); World-Bank-compatible codes for non-countries (`EUU`, `XKX`, `ANT` legacy only, `GBR` for the
law `uk`, app-defined `INT`), each disclosed in the hover as "not an ISO code" (Q303); payloads gain
`country_iso3` beside `country` and every parameter accepts both forms through `normalize_country` (the 0.4
shape of Q304; the flip is 0.5); the loader normalises the 5,803 `country:` / `jurisdiction:` config lines
without rewriting the files (Q305 "follows Q301" — step 1); flags derived internally alpha-3 → alpha-2
(Q307); pickers ordered by localised name with the code as a secondary column (Q308); the filename rule — a
filename carrying a country uses uppercase alpha-3 — enforced by a repo test over the `data/` naming helpers
(Q309); external contracts stay alpha-2 behind converters, with `P298` fetched in the catalog query as a
cross-check (Q311); timing 0.4 (Q312). The two frontend mechanisms that break silently on alpha-3
(`Intl.DisplayNames` at `app-map.js:91–99`, the `/^[A-Z]{2}$/` flag gate at `app-agenda.js:981–985`) are
fixed and browser-checked. *Proposed placement:* the ISO 639-2/3 language-code move (Q306 = b) takes the same
two steps — display here, storage in 0.5 — because the two normalisations share a branch at `csv_io.py:130`.
**Closes when** a Chromium click-through record shows codes + hovers on every surface that shows a country
(map, agenda, sources, markets, laws, wiki), the filename-rule test exists, and the 0.4 exports carry both
columns. Brief `S04-05`.

**BUILT 2026-09-16 (PR #1147).** One display helper per side (`country_display` / `ooCountryCell`, and the
language twins), 43 display surfaces rewired through it across 11 static modules and the bulletin, payloads
carrying `country_iso3` beside `country`, and every touched filter widened through `country_query_forms` —
which WIDENS rather than normalises, so a filter that worked yesterday works today and the `GBR` an operator
reads off a row now matches the rows stored as `uk`. The filename rule is `country_filename()`, which REFUSES
an unresolvable country rather than composing a name around it, swept by `tests/test_country_filename_rule.py`
BY NAME and BY ARGUMENT. Both silent-failure mechanisms the row names are closed: `Intl.DisplayNames` is
pinned to the two helpers that own it (it answers an alpha-3 by handing it straight back — no exception, no
empty string — so a stray call site fails by printing the code it was given), and `agFlag` delegates to
`ooCountryFlag`. The prohibitions hold and are TESTED, not asserted: the six `String(2)` columns are counted,
the OSM `ISO3166-1:alpha2` tag is unrewritten, and `configs/` is hashed before and after a catalogue LOAD,
because the fear is a loader that normalises on read and writes back.

**Chromium click-through — `docs/audit/alpha3-clickthrough-2026-09-16/`.** en · fr · ar (RTL) · zh, zero page
errors. Laws, Agenda, Library → World coverage (218 country cells, every one with a hover name), Settings →
Data (the sources table AND the multi-select country filter, which shows `Name (CODE)` per Q308), and the
Wikipedia `<select>` (invariant #1) all show alpha-3 with the localised name in the hover, `EUU` carrying its
"not an ISO code" disclosure translated. The `#oo-tip` bubble was opened and read back.

**Why the row stays OPEN.** Governments → Countries/Map and Markets read World Bank figures and the market
importers; both are empty on a machine that has never been online, so the walk saw their honest empty states
rather than a country. Their renderers are covered by the table in `tests/test_alpha3_display_surfaces.py`,
which is a weaker instrument than a real screen and is recorded as weaker. **Closes when** those two surfaces
are walked with real data.

**Three findings, all fixed in the same PR, and none of them reachable from source alone.** (1) The two halves
of one helper disagreed: `Intl.DisplayNames(…,{type:"region"}).of("AN")` answers **Curaçao** — CLDR aliases the
withdrawn Netherlands Antilles code to its successor territory — so the hover named a different place than the
code means, where the server's `SPECIAL_CODES` had it right all along; `INT` is not a region at all and had no
name. Both overrides now ship ×12. (2) The coverage panel froze its locale, and the FIRST FIX WAS HALF A FIX:
the panel has TWO payload-fingerprint repaint guards and only the map's was made locale-aware, and even with
both fixed a bare language switch still changed nothing because no handler re-ran the loader. Both halves
landed and were re-walked on a bare switch, fr → ar → zh → en → ar → fr. (3) The full suite caught the one this
slice would otherwise have shipped: teaching `normalize_country` the alpha-3 forms made `country_from_title`
read a trailing ACRONYM as a country — `(PRI)` is the Permaculture Research Institute and Puerto Rico, `(ARM)`
is the Alliance for Regenerative Medicine and Armenia — filing two catalogue sources under a country nobody
claimed for them. The opt-out (`accept_alpha3=False`) sits on the one caller that reads prose, because "this
input is a guess about human text" is a fact about the call site, not about the codes.

### Row M — Keywords in the UI language, "translated from X" · ruled (R7, R8; Q401–Q404, Q406 ⛔ = b, Q407, Q408, Q410–Q414, Q416, Q418) · OPEN

**What it must demonstrate.** The translation is the visible term, a small "translated from French" tag
follows it, the hover shows the original, the ring's other members with counts and the source (Q401); the
source language is named in the UI language (Q402); the three-tier ladder — verified (ring) · tentative (LLM,
always ≈) · untranslated (tagged, still searchable) — through ONE display helper on every keyword surface,
the seven endpoints gaining `target_lang`, `_annotate_translations` gaining `translation_source_lang`,
`translation_tier`, `senses` (Q403); the `keyword_translations` table (Q404, row K); **rings auto-load
without review** at ≤ 1 request / 10 s (Q406 ⛔ = b; the generator's 0.2 s spacing changes to 10 s) — *design
note:* an auto-loaded ring is disclosed as "from Wikidata, unreviewed" and stays editable in Settings, and the
consent/visible-job rules apply to the fetch; growth from the gap digest (Q407) through `wbsearchentities` then
`wbgetentities` per item, 10 s apart (Q408); the shipped rings regenerated on the maintainer's machine before
each tag, top 2,000 keywords per language (Q410 — an operator ritual, recorded in the release notes); cards
translate the term as a ruled exception to the "data never translates" note at `i18n.js:162` (Q411 — the
comment is amended in the same change); the 91 collision terms get "several senses" + a sense picker and
`translate_term` gains the refusal path (Q412); the source language is the ring member's effective language and
the `reconcile_keyword_language` pass **runs in this gate** (Q413 — the report is the artifact); language
stored per mention with the keyword's language derived as the majority (Q414); `simplemma` in core, lemmatise
at extraction, a migration job re-normalises existing keywords (Q416); the hover bubble contents (Q418).
**RELEASED 2026-09-30 (R98, D11):** the triage-derived stoplist merge — Q1103 = b ("Never; the shipped stoplists are frozen", with a
note asking for a stopword diagnostic and per-release growth) against Q1104 = a ("Yes, through the review
surface, batch by batch") was a recorded CONFLICT; the maintainer ruled the lists grow in reviewed batches, and the row ships the merge as curated batches with each app update (R111 amends R98: no Settings review screen, users are never asked; we curate from the diagnostics),
and the stopword DIAGNOSTIC the note asks for already exists (the keyword log's `stopword_candidates` digest, `src/api/diagnostics/keywords.py`) and R111 makes it the feed for those batches (it decides nothing). **Closes when** every keyword
surface renders a tier tag (a Chromium click-through record across the eleven silent surfaces), the reconcile
report exists, a fixture proves the 10 s spacing and the refusal on the kill switch, `simplemma` is in
`pyproject` core with its registry entry, **and the first curated stoplist batch has shipped in an app update and takes effect on every surface that shows keywords (after R111 steps T2 and T3 in `OPEN_QUEUE.md`; this criterion follows from R111)**. Brief `S04-06`. *Premise check (brief `S04-06`):* `simplemma` is ALREADY a dependency — `pyproject.toml:147` under the `[analysis]` extra, used display-time only (`OO_FAMILY_LEMMA`, `src/analytics/families.py`), with no registry entry; the delta Q416 asks for is core + at-extraction + the migration, not a new package.

### Row N — Cross-language search through the rings, everywhere · ruled (R10; Q417, Q501–Q504, Q506 🔒 = b, Q507–Q512, Q514–Q516) · OPEN

**What it must demonstrate.** `resolve_concept(term, ui_lang, sense)` computed once per analysis tab and passed
to both the FTS path and the keyword-keyed aggregates; "only the words I typed" is one toggle persisted in the
tab seed and the URL (Q501, Q504); stacked per-language series with a legend (Q502); the 40-literal cap, most
frequent first, disclosed — **with a user toggle to deactivate it, cap on by default** (Q503 note); the
segmenter dependency for zh / ja (`jieba`, `sudachipy`) (Q506 🔒 = b — registered, optional-extra or core per
Q1015's rule, with the re-index job it implies; the zh emphasis of the Q911 note applies); Arabic
`remove_diacritics=2` + alef / teh-marbuta / yeh folding at index and query time (Q507); results interleaved by
date with a language chip **and a group-by-language option** (Q508 note); per-language counts on the chip
**plus the single total** (Q509 note); a watch on "climate" watches the ring (Q510); bulletin sections built
from keywords use the ring, **and a new bulletin annexe carries all ring analytics and details** (Q511 note);
the ring is the mind-map centre, each language an arm (Q512); tentative translations never expand a search
unless the user opts in per query (Q514); **exact, uncapped totals** (Q515 = b — state the cost on the
ring-size extremes); the Observatory, the map and the sources tab read the same resolution (Q516); rising /
trends / top computed per ring with a per-language breakdown in the hover (Q417). **Closes when** "every
analysis tab agrees with the Articles list on the same concept" is demonstrated on the reference corpus (a
recorded comparison, numbers in the PR), the CJK and Arabic re-index has run on it (the fixture and the
reference corpus, counts before/after), and the toggles are Chromium-verified. Brief `S04-07`. *Premise check (brief `S04-07`):* the FTS tokenizer is already `unicode61 remove_diacritics 2` (`src/database/fts.py:254`; also `src/wiki/dump_index.py:84`), so Q507's first half exists and only the alef / teh-marbuta / yeh folding is new; and the tree's `[segmentation]` extra (`pyproject.toml:193–195`) already carries `jieba` + `janome` (ja) + `pythainlp` on the keyword-extraction path, where Q506 = b's label names `sudachipy` for ja — which library serves the FTS path is an OPEN DETAIL for the maintainer, never substituted by a session. **ANSWERED 2026-09-27 (`PF12`, in chat: «Row N: keep sudachipy»):** `sudachipy` serves the FTS path for ja, as built; the keyword path keeps `janome`, which the answer does not reach.

### Row O — The versioned-source substrate and the lanes · ruled (Q716, Q719 🔒, Q720 🔒, Q926, Q1003–Q1007, Q1010, Q1011, Q1014–Q1016, Q1018, Q1020) · OPEN

**What it must demonstrate.** `src/versioned/` shared by the wiki, law and OSM lanes, the wiki adapter first
(Q1003): identity `(kind, external_id)` + QID, an immutable baseline, a change feed with cursor, gap detection,
budget and politeness, a revision store, the latest as an Article, point in time, disclosure. One database file
per lane — `corpus.db` + `wiki.db` + `osm.db` + `law.db` — each encrypted alike, each an opt-in backup member,
linked by ids (Q1004, Q719, Q926); encrypted with the same passphrase and threat model, no per-lane plaintext
(Q1005, Q720); **SQLite for everything**, DuckDB not used for the lane tables (Q1007 = b, Q811 = b) — the
PostgreSQL-parity aspiration stands (Q1140) and no table widens past Postgres's column limit (the Q1140 note,
*design note*). Wikipedia becomes a lane beside RSS; `mode="wiki"` is retired with a migration; `POST
/api/wiki/pages` survives as "pin this page to HOT" (Q716, Q1020): the scheduler runs lanes (press, wiki, osm,
law, hazards, discovery) under one online consent, one governor, per-lane budgets. Each lane declares its
transport in the consent hover and never downgrades Tor → clearnet (Q1014). Dependencies: compiled code only in
optional extras, pure Python in core, SSE hand-rolled over the guarded session, every addition registered
(Q1015). Settings → Storage shows each lane's size, budget, the honest growth arithmetic and the disk left,
budgets published and sized for the 2-core / 3.5 GB reference VM (Q1006, Q1010); the app reads cores, RAM and
free disk at boot — no network — and proposes budgets from a published table (Q1011). Synthetic fixtures — a
wiki edition, an OSM extract, a jurisdiction — so every lane's pipeline runs end-to-end in CI without a socket
(Q1018). The Living sources view — timeline of changes, diff, coverage, freshness, budget — replaces the
tracked-changes modal (Q1016; its detail "a main tab or a Home family — your call in a NOTE" was answered
«Main tab» on 2026-09-25, `R32`, so invariant #2's tab roster grew by one). **Closes when** the CI fixtures run green with the socket guard armed (the airplane socket guard proves
zero resolutions), a wiki page round-trips baseline → change → revision → Article on the fixture, the lane
files exist encrypted with the corpus passphrase, and the `mode` migration is exercised on a real settings
store. Brief `S04-08`.

### Row P — The Wikipedia lane: the stream and the HOT tier · ruled (R12; Q108, Q702 ⛔, Q703–Q715, Q717, Q718, Q721, Q725–Q728, Q819) · OPEN

**What it must demonstrate.** EventStreams (a persistent SSE connection, hand-rolled) delivering metadata for
every edit in all twelve editions, resumed with `Last-Event-ID`, falling back to `list=recentchanges` per
edition when a gap exceeds the stream's retention and recording an honest gap otherwise (Q727); **a dedicated
Wikipedia toggle in the top bar, DEFAULT ON — like the AI toggle, with a nice and consistent animation — letting
the user stop / start / halt / resume the streaming** (Q702 ⛔ as the maintainer wrote it; the label's "default
off" is overridden by the note; the one online consent still gates the first egress, invariant #14; the new
element keeps a constant footprint, invariant #3, and its strings ship ×12). Namespace 0 without redirects,
with disambiguation and list pages (Q703); wikitext stored + a derived plain text for FTS (Q704); the metadata
list confirmed (Q705: pageid · QID · sitelink count · categories · length · revision count · protection ·
last editor class · infobox fields · coordinates · image / external-link / citation-needed counts · assessment
class · creation date · edition); pageviews: the daily top-1,000 per edition + per-article daily views for HOT
pages (Q706); three tiers under a per-edition daily budget the wizard sets, default 20 GB total, published
(Q707); **every edit as a row for every page, kept raw** (Q708 = b, Q709 = b — the FROM-MEMORY figure is
250–300 k rows / day; this row MEASURES it); retention HOT every version, WARM latest + previous, counters and
metadata forever (Q710 🔒); the diff against the previous ingested version, section-aware, revid-anchored
(Q711); analytics 1–3 in 0.4 — edit velocity per topic / country / language, contested pages by revert rate,
newly created pages as emerging topics (Q712); creation / deletion / move from the log events (Q713); separate
lane counts everywhere, the "articles" headline stays press (Q714); identity `WikiPage(wiki, pageid)` + `qid`,
the Article carrying `wiki_pageid`, `qid`, `source_revision`, `source_type="wikipedia"`, the edition as
language (Q715); ORES / Lift Wing verified, opt-in, ≈ (Q717); Wikimedia Enterprise excluded under V1-2 (Q718);
HOT pages' Articles ride the corpus backup, the lane is an opt-in member (Q721); the first-run wizard: edition
choice (default all twelve) + the storage budget + the plain statement of what the lane contacts (Q725);
disclosure in `SECURITY.md`, the robots exemption stated the way `stats/fetch.py:22–25` does, the reader shows
the CC BY-SA 4.0 attribution with a link to the page history (Q726); the modal becomes the Living sources view,
the dump machinery stays as an opt-in offline reader, the dump→corpus endpoint is retired (Q728); Wikipedia
page coordinates become a map layer and OSM objects tagged `wikidata` / `wikipedia` resolve to the same Place
(Q819 steps 1–2 — step 2 completes with the Place entity in 0.5). Transport: the stream follows the user's
transport setting, never downgraded (Q722 = b, Q1014). **Closes when** the lane has run **≥ 72 h on the
reference VM inside its budget** with all twelve editions and the run's own counters are read from one
artifact (rows / day, bytes / day, gap history — the intake's exit row, now with the measured figures replacing
the FROM-MEMORY ones), the toggle and wizard are Chromium-verified + click-through, and the fixture pipeline of
row O carries the stream. `not-measurable-here` for the 72 h run; **operator:** that run. Brief `S04-09`.

### Row Q — Laws: the metadata model, the L0 defects, the first bulk adapters · ruled (R14, R15; Q107, Q901, Q902, Q904–Q910, Q914, Q915, Q917, Q919, Q921–Q924, Q927) · OPEN, the adapter order ANSWERED 2026-09-29 (Q925 = a)

**What it must demonstrate.** The L0 defects first, before anything else in the section (Q917); the internal
model — Akoma-Ntoso-lite: document → versions → provisions with stable addresses + a metadata block, one adapter
per source format, text-only sources filling one provision (Q906); the metadata fields confirmed (Q907:
identifiers ELI / CELEX / ECLI / act number / gazette reference · title ×languages · issuing body · dates ·
status · legal system · jurisdiction alpha-3 + level · language + translation provenance · licence · source
authority + URL · amends / amended-by · topics); point-in-time consolidated versions with `valid_from` /
`valid_to`, an observed snapshot dated by observation and labelled so (Q905); act / code level by default,
per-provision rows where a source arrives pre-split (Q904); **"formally translated" admits official
translations, intergovernmental bodies' translations, and any government's translation of another state's law
— and each translation is its own document with rich metadata, individually tracked for changes, linked to the
other translations and to the original** (Q901 = a, b, c with the note); in scope: constitutions / statutes /
codes, executive instruments, treaties (`INT`); bills and drafts recorded for post-beta (Q902 note); one
document identity with N language versions aligned by identity, no ring needed (Q908); bulk open data first,
then enumeration adapters, then gazette feeds (Q909); account-gated bulk data treated as key-gated and excluded
under V1-2 — EU law through the open per-document API, the Cellar SPARQL endpoint and the weekly public RDF
bulk (Q910); cadence daily / weekly / on-demand within the adaptive per-pass budget (Q915); every law authority
a `Source` row with `source_type="law"` (Q919); `counts_documents` declared per official count (Q921); `[pdf]`
in the default install — 63 of 275 sources are PDF-only (Q922); each source carries `verified: live | fixture |
unverified` with a date, shown in the UI (Q924); the licence recorded per document, shown in the reader, stated
at every export point, a source whose terms forbid redistribution excluded (Q927); analytics 1–2 on the small
corpus — the per-provision diff timeline and amendment velocity per jurisdiction (Q914). **The 44-row vetting
board is run as the 0.4 law operator step** (Q923; `docs/product/LAW_VETTING_BOARD.md`). **PENDING:** the
adapter ORDER and the first managed dataset (Q925 ⛔, blank) — this row builds the adapter framework and feeds it
with the CLML adapter that exists; no second adapter is chosen by the session. Live adapter checks need the
allowlist (row V) or the maintainer's machine. **Closes when** the L0 fixes have tests, a fetched CLML document
round-trips into the model and the reader shows its latest text with the licence line, the vetting-board run's
report exists (operator), and the fixture jurisdiction of row O exercises versions + provisions end-to-end.
Brief `S04-10`.

### Row R — Maps: Equal Earth and the borders · ruled (R13; Q801–Q803, Q826) · OPEN (ADVANCED 2026-09-16)

**What it must demonstrate.** Equal Earth on all five map surfaces through the one `project(lon, lat)` seam
(the current projection is plate carrée at `app-map.js:21–24`, not Mercator), no toggle, named in the legend
("Equal Earth · equal-area") (Q801) — the polynomial's coefficients are FROM MEMORY in the sheet (A₁ 1.340264,
A₂ −0.081106, A₃ 0.000893, A₄ 0.003796) and **must be confirmed against a published source by the building
session** (proj.org was egress-blocked here); Natural Earth 50m now, the OSM-derived admin artifacts replacing
it from 0.5 (Q802); OSM's border convention as of a stated date, every disputed area rendered CONTESTED showing
both claims, the convention named in the legend, **with toggles letting the user see the difference between
conventions, OSM's as the default** (Q803 note); contested borders never a silent pick (Q826); the ooMap
embed on When / Where stays (Q1150). **Closes when** a Chromium click-through record shows the five surfaces
on Equal Earth with the legend, the CONTESTED rendering and the worldview toggle, and the `world_countries.json`
count test still pins the ring inventory. Brief `S04-11`.

**AMENDED 2026-09-27 (`PF06` = a, in chat: «Row R: OK to move that to 0.5»):** Q803's ruled DEFAULT, OSM's
border convention as of a stated date, leaves this row for the `0.5` board (`RELEASE_0.5_GATE.md` row L),
beside the OSM-derived artifacts it waits on. Until then the default stays `contested` (it assigns nothing),
because Natural Earth's de-facto policy is not OSM's and naming it so would be the silent pick the ruling
forbids. The rest of the bar is unchanged: the row closes on the click-through record of the five surfaces on
Equal Earth with the legend, the CONTESTED rendering and the worldview toggle, and on the count test. The
sandbox Chromium record is `docs/audit/14_MAPS_EQUAL_EARTH_CLICKTHROUGH_2026-09-16.md`; the maintainer's half
(Q1128 = a) is owed. R35 delegated that half to Claude for rows H, I, J, L, M, N, O, P, S, T and U; row R is not
among them (nor are K and Q) and R35 gives no reason. Whether R's pass is the maintainer's own or a Claude-run
walk on R35's terms is the session's reading, not a ruling.

**CLAUDE WALK 2026-09-27 (on R35's terms; `docs/audit/delegated-rewalk-2026-09-27/`, ids `R-1` to `R-24`):
FAILS.** The walker fed all five maps data, so none was judged on an empty screen. The geometry passes on every
surface: Equal Earth (aspect 2.0547), 229 countries, 28 contested areas, the translated legend, the visible caveat,
the 34-option worldview picker defaulting to `contested`, and the count test (13 passed). It fails on 2 P2 and 8
distinct P3 defects: contested-area names are English in fr, ar and zh (the renderer reads `OOI18N.lang`, which does
not exist); Abyei, Tigri Area and Lawa Headwaters each name ONE claimant, because the claims come only from Natural
Earth's 33 viewpoint fields and South Sudan and Suriname are not among them; a worldview chosen on one map does not
reach the others; the Statistics and ring maps keep the old language after a switch; and on touch the claims cannot
be reached. The fixes are batch B20 in PR #1191; the row closes on a walk of those fixes.

**CORRECTED 2026-09-27: the When / Where embed was never built.** The row's «the ooMap embed on When / Where stays
(Q1150)» read Q1150 as naming an existing surface. `docs/ledger/shipped.csv` (2026-09-10, PR #1107) records it as
**scoped, not built**: the coordinates are already on the wire, but ooMap's marker layer is time-filtered and a
corpus place has no time. Register M3 asked how to build it ((a) a timeless mark kind, or (b) aggregate places to
country and use the choropleth, recommended), and the answer sheet re-asked it as keep or remove; «Keep» (Q1150 = a)
kept the PLAN. It is not one of the five surfaces the row closes on, and no release is named for it; this session's
default is to build it with `0.5`'s map work (row L's slice `S05-05`) unless the maintainer asks for it in `0.4`.

### Row S — Sources: admission, identity, the institutions docket, the splice · ruled (Q1101 ⛔ = a, Q1105–Q1112, Q1114–Q1119, Q1156) · OPEN, the embassy platforms ANSWERED 2026-09-29 (Q1113 = a)

**What it must demonstrate.** A `qualified` verdict flips `enabled=True` and the `scrape_unqualified` hatch is
retired (Q1101 ⛔ = a — qualification IS the admission gate; the audit view's undo is the safety valve; the
per-pass hardware budget bounds Tor use); the 64,910 `kind_overrides` proposals as a worklist, never
auto-applied (Q1105); the `source_qualification.yml` overlay editor (adopt / export / revert) in Settings
(Q1106); `PATHOLOGY_ABS_FLOOR` kept at 0.5 and recorded unreachable (Q1107); the 6-month re-verification reads
the last 6 months (Q1108); research institutes to `academic_sources.yml` **plus a written strategy to grow that
list comprehensively** (Q1109 = b with the note); `primary_source` deferred-not-rejected and rewritten as an
observable (Q1110); the 16 mis-shelved journals moved (Q1111); a candidate tripping `restricted_namespace`
cannot be spliced without a written override, never a silent drop (Q1112); **THE number = `enabled AND
qualified`** everywhere a headline count is shown, the other predicates labelled (Q1114); a diagnostic proposes
country-vs-domain corrections for review (Q1115); bare QID names resolved at the polite rate or declined
(Q1116); the 116 Czech municipalities admitted, tagged with the vendor path (Q1117); the shortlist (3,031) run
next, the remainder and the religious lists after the splice review (Q1118 — operator / session run); the Stage
B splice admits where both judges agree, defers the ~15 % contested band (Q1119); the stratified round-robin
kept with the singleton strata's order randomised across passes (Q1156). **PENDING:** the compromised embassy
platforms (Q1113 ⛔, blank) — they stay excluded by the existing flag, nothing is published, nobody is
contacted; that is today's state, not a decision. **Closes when** the flip + hatch removal has its data-safety
review and tests, the overlay editor is Chromium-verified, the moves land as catalogue diffs, the splice report
exists with its agree / defer counts, and one headline count on each surface is proven to be `enabled AND
qualified` by a test that reads the shipped predicate. Brief `S04-12`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** Three assumptions land here, each reversible.
**`RC05` → (a): no tool.** The 64,910 `kind_overrides` proposals stay a design-doc measurement and the
worklist Q1105 = a funds is NOT built in `S04-12` — the register's B4 side, taken as §0's later-channel
default; the CONFLICT with Q1105 stays recorded on both rows. **`RC06` → (a): 90 days BESIDE the
whole-history verdict**, never replacing it — two verdicts per source, each with its own n, rather than
Q1108 = a's six months instead of the whole history; the CONFLICT stays recorded. **`RC07` → (b):** B7's
article-revision-tracking note is placed as its own 0.5 slice on the finished row O substrate — a PLACEMENT
assumption only; the feature itself is ruled. B5 and B6 are unaffected. The embassy platforms (Q1113 ⛔)
remain PENDING for their own reason.


**VERIFICATION PASS 2026-09-18 (PR #1159) — what this row's built state actually is.** S1–S4
merged as `#1158`; this session re-walked them rather than rebuilding, per the working mode's staleness
guard. **The Q1113 ⛔ SEAM WAS NOT CROSSED.** `embajada.gob.ve` appears in this tree only in test
fixtures and pre-existing research notes; `src/catalog/stage_b_splice.py` refuses a
`restricted_namespace` row absent a written override (Q1112), and the SPLICE REPORT's 807 admitted /
7 blocked leaves them blocked. Nothing was published, nobody was contacted, and no proposal was
auto-applied. **The RC05/RC06 state this was built under is the one §0 recorded**: RC05 → (a), no
kind-overrides tool (the Q1105 conflict stays on both rows); RC06 → (a), the 90-day window published
BESIDE the whole-history verdict. Both remain ASSUMPTIONS, not rulings. **Still the operator's, not
the session's:** the shortlist (3,031) run (Q1118 — needs the maintainer's machine or row V's
allowlist; this container's egress is proxied and the politeness budget is not the session's to
spend), the human review of the SPLICE REPORT before any row is applied, and the maintainer's own
click-through. **What the walk changed:** the undo now refuses an admission a later verdict replaced
(it had been writing `unqualified` over a `disqualified`, returning a judged-and-refused source to
the un-laddered trial queue), the audit view publishes that refusal so the button cannot claim a
capability the endpoint lacks, and four panel strings are keyed ×12. The panel is at **Settings →
Advanced → Quality gates**, not the "Settings → Sources" this row and the brief both name — worth
knowing before the maintainer's pass, because the section renders nothing until its `<details>` is
expanded.

### Row T — Network budgets and politeness · ruled (Q1012, Q1013, Q1125, Q1126 ⛔ = a, Q1132, Q1148) · OPEN

**What it must demonstrate.** A per-PROCESS bandwidth budget composed with the collection-speed governor
(`#rate-toggle`), never a second rate authority; per-job caps stay omitted (Q1012 — CLAUDE.md invariant #20
amended 2026-09-15); a per-host next-allowed-at persisted beside the robots cache, an inline wait beyond a few
minutes refused with a named deferral counted as its own bucket, the ride-along and the trial fetch inheriting
both (Q1013 — the 2026-09-10 pending ruling, now ruled); the guarded-route rate limit raised to 1,000 / hour
for loopback UI calls, 100 kept for anything else (Q1148); `#net-coach`'s two actions at equal visual weight
(Q1125); the task-manager airplane title aligned to "every new network request will be refused", re-translated
×12 (Q1126 ⛔ = a — consent copy; the three i18n gates are the bar); model-weight digests pinned in the
external-artifact registry and verified on pull (Q1132). **Closes when** each has a behavioural test (the
deferral bucket appears in the pass summary on a fixture host declaring a long `Crawl-delay`; the budget
composes with the governor in one place), the ×12 strings pass all three i18n gates run separately, and the
net-coach weights are Chromium-verified. Brief `S04-13`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC15` came back blank → **ASSUMPTION (a): L4's
«most ethical» is the app's own loopback guard**, so Q1148's figures stand exactly as this row already states
them (1,000 / hour for loopback UI calls, 100 for anything else) and the per-host egress politeness
(Q1013 = a, the other clause of this row) is NOT re-opened. Nothing in this row changed; the assumption is
recorded so that a later reading of L4 as the egress knob is a reversal rather than a discovery.

### Row U — UI, i18n and the small rulings · ruled (Q1124, Q1130, Q1135, Q1139, Q1141, Q1149, Q1151, Q1152) · OPEN

**What it must demonstrate.** The i18n remainder — 470 strings — keyed ×12 in 0.4 (Q1152), the
`--audit-chrome` ratchet lowered by the measured amount in the same PR; **the religious calendars and the
eclipse canon feature dropped** (Q1135 = b — name the loss in the PR: the 2026-06-17 "you will provide the
dates" ruling is superseded; the agenda's other categories are untouched); the synthetic click-through corpus
gains an encrypted variant (Q1149); `src/api/diagnostics.py` split mechanically into a package, routes
unchanged, proven by a route-table equality test read from the router definitions (Q1139); a full
`docs/FUTURE_DEVELOPMENTS.md` reality check against the tree, stale claims corrected in place (Q1141); the
newsletter attach go-ahead built (Q1151); only the `via:*` provenance prefixes filtered from topical displays
(Q1130); the Patterns lens flips on only when the corpus is ≥ 100 k articles and a labelled sample shows a
false-positive rate ≤ 5 %, both numbers on the toggle (Q1124 — no flip in 0.4 unless measured). **Closes when**
the three i18n gates are green at the lowered numbers, the removal PR names what went, the route-equality
test exists, and the reality-check PR lists every corrected claim. Brief `S04-14`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** Three assumptions land here. **`RC13` → (b): the
religious calendars are NOT dropped** — a dedicated networked session researches the dates from published
calendars and authorities and implements them, dated, sourced, method stated, ×12, nothing fabricated (the
register's G8 side; the CONFLICT with Q1135 = b stays recorded). **The eclipse canon is the half this
assumption does not reach:** `RC13` asks for `+ eclipses` or `− eclipses` after the letter and nothing was
written, so the eclipse canon is neither dropped nor funded and this row no longer reads it as dropped —
that clause of Q1135 = b is UNSTATED pending the letter, and no session may decide it. **`RC17` → (a):** the
coverage-state prefixes (data-gap, thin-coverage, fragmented, …) are filtered from topical displays ALONGSIDE
the `via:*` provenance prefixes, widening Q1130 = a's `via:*`-only clause; the judgement words stay reported
and the CONFLICT with Q1130 stays recorded. **`RC08.6` → (a):** L5's `_SPARSE_BAR_MAX` extension to
`commodityOverlaySvg` only is PLACED in this row; invariant #16 is unchanged. Every other clause of this row
(Q1124, Q1139, Q1141, Q1149, Q1151, Q1152) is untouched.

### Row V — The release ritual and the allowlist · ruled (Q111, Q114 ⛔ = a, Q116) · OPEN

**What it must demonstrate.** Every alpha tag ships with GitHub release notes generated from `shipped.csv` since
the previous tag + the no-telemetry re-check stated in the notes (Q111 — the per-release ritual already in
`CLAUDE.md`) **+ one ENCRYPTED click-through run, stated in the notes (Q1149 = a / L7, the ritual added to
`CLAUDE.md` 2026-09-16): `OO_UIWALK_ENCRYPTED_PASS=… scripts/ui_clickthrough_run.py --require-encrypted`, which
refuses to produce a report unless a seeded, WALKED state measures encrypted at rest by the app's own header
read**; the session environment's egress allowlist gains the hosts named in Q114 (legislation.gov.uk,
eur-lex.europa.eu, gesetze-im-internet.de, laws.e-gov.go.jp, echanges.dila.gouv.fr, dumps.wikimedia.org,
stream.wikimedia.org, *.wikipedia.org, wikidata.org, query.wikidata.org, download.geofabrik.de,
planet.openstreetmap.org, api.worldbank.org, sdmx.oecd.org, api.imf.org, extensions.duckdb.org, proj.org)
(Q114 ⛔ = a — an OPERATOR step in the environment settings, nothing in the tree); three lanes as today
(Q116). **Closes when** the `v0.4.0` release notes carry both items and a session's probe to
`dumps.wikimedia.org` (AMENDED 2026-09-27 by `RC10` = b: to a Q114 host that stays on the list, below) returns an HTTP status rather than `000` (the recorded 2026-09-07 probe shape) — until
then every live-verification step reads `not-measurable-here`. Brief `S04-15`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC10` ⛔ (does F1's «add them» include
`dumps.wikimedia.org`?) came back blank on a ⛔ question, so it **stays PENDING and is never defaulted**:
that one host is CARVED OUT of the Q114 list above and is not added to the session environment's allowlist.
Every other host in the list stands under Q114 = a / F1. The consequence is unchanged and stated rather than
worked around: PROMPT_06's sense inventory and ambiguity map (slices 4 and 6) stay operator-side, and this
row's closing probe to `dumps.wikimedia.org` still reads `not-measurable-here`.

**ANSWERED 2026-09-27 — `RC10` = (b), in chat («RC10: go with your recommendation»):** `dumps.wikimedia.org`
is EXCLUDED for now and every other Q114 host is added; PROMPT_06's slices 4 and 6 stay operator-side, and the
answer can be reversed at any time by adding the host. **The closing clause is amended with it**, as the
thread recommended on 2026-09-26 («I recommend changing the closing clause to probe a host that's already allowed, so your (b) answer still stands»):
the probe goes to a Q114 host that stays on the list, beside a control host as `S04-15` S4 has it, and this
half closes when that host returns an HTTP status rather than `000`. **Measured 2026-09-27 at about 09:00 UTC from a session: all seventeen, `dumps.wikimedia.org`
included, answered `000`** (the proxy refused each CONNECT), so the allowlist step is still the operator's and
every live-verification step still reads `not-measurable-here`.

### Row W — `0.3`'s row 5, the Tier-A quarantine run · ruled (`RC01` = a, 2026-09-27; its criteria agreed 2026-08-23) · OPEN

**What it must demonstrate.** The pass `RELEASE_0.3_GATE.md` §7.1 describes, unchanged: the 8-article Tier-A
drop path run with `include_prose_gate=false`, then the keyword re-index, then the composition read under
`nav-soup-v2` (§7.1 says to expect 8 there), on the maintainer's corpus. It moved here from the `0.3` board when
the maintainer answered `RC01` = (a), which closes `0.3` on the existing `v0.3.0` pre-release and makes row 5
«an operator step of 0.4, beside rows A–C». So it no longer holds the version flip (row G); it does hold the
`v0.4.0` tag. **The instrument exists:** the release run's opt-in step (`run_row5_quarantine`,
`src/monitoring/release_run.py`) runs it LAST, after the bundle, with collection paused (`FD01`, `FD02`). The
run's report still files the result under board row `G`, its letter before `RC01` = a, and the checkbox still
says «deferred by ruling A1»; read both as row W until they are relabelled (owed, `OPEN_QUEUE.md` head entry).
**Closes when** the composition payload is quoted in this gate; a decline is §7.1's own branch and is recorded
the same way. **Operator:** the run. Brief `S03-01` S2.

---

## 3. Amendment log

Every change to a row's status or bar lands here with its date, its source, and what it costs.
The `0.3` gate's own log is the format.

| Date | Change | Source |
|---|---|---|
| 2026-10-01 | **Release-run report: a restore that failed reads `error` (PR #1312; no row changed status).** Two of the four release runs in the 2026-09-30 diagnostics that reached the restore had failed there (instance 085218 refused by the restore engine's own staging check after 128 s, instance 085230 dead after 53 minutes with `Error creating function`), and the report recorded both as `measured`: rows A and I over an empty `restore` block, row K over a scan of the restored corpus that was empty. A restore now counts only when its child reported `ok`, its process exited 0 and its restore was committed; otherwise the phase reads `error` with the child's own words, rows A and I read `error`, rows E and K say the restored install's reading is not counted, and a resume retakes the restore and asks for the passphrase as a first run does (a state file written by an earlier build keeps no restore this rule would not count). The passphrase is taken out of what the child says and out of the run journal and import reports a kept fresh install leaves on the drive. §2 row A's evidence paragraph carries the figures and what stays inferred. The change is unit-proved only; no instance has run a release run on it, and the two failed runs are not evidence for row A. | session (project thread «Release candidate diagnostics»; the coordinator's ask, 2026-10-01 01:36 UTC) |
| 2026-10-01 | **Row D CLOSED on its own exit text.** The report row D asks for exists: instance 090243's 72 h release run (`20260919T043901Z`) holds the six-block soak-window report of its window (80.46 h, `reaches_bar: true`, all six blocks measured) and the P0.3 collector check re-taken in the same `collect` phase (`pass`, +79 MB over 2 passes in the retained ~2 h), so «one soak-window report from a run of ≥ 72 h exists and is read alongside the P0.3 report» is met on one artifact. §2 records the six blocks and what the close does not claim: the figures are not judged, the P0.3 line is not multi-day evidence, `wiki_lane` (the seventh block) is unmeasured and is row P's, and the standalone `p0-validation.json` is the P0 report taken at the run's start, which is not what the row reads. No new ruling: this reads the exit text as written, in a draft PR for the maintainer. The row is verdict-free by design (§2: `window.reaches_bar` is a fact about the window's length, and «what the numbers inside it mean is the maintainer's reading»), so merging this PR is that reading, for the maintainer to confirm, and reverting this hunk reopens the row. | session (project thread «Release candidate diagnostics»; the coordinator's reading, 2026-10-01 02:44 UTC) |
| 2026-10-01 | **Row B CLOSED (`R113`, «17a»); row A gains the field evidence of the 16-instance diagnostics.** Row B closes on instance 090243's 72-hour run of 19 to 22 September with its 73 hourly readings as the memory evidence (the built-in memory check keeps about two hours, so no P0.3 reading can span 72 h). §2 records what the close does not claim: `soak-window.json`'s `reaches_bar` is the later process's (the release run's own soak-window block, taken by the soak process, reads 80.46 h), that later process engaged the memory guard 76 times, which process «ended cleanly» reads, and why the other windows of the round (085214 climbing, 085218's missing final report, 085230 at 30 h) do not close it. Row A stays OPEN and its bar is unchanged: §2 now records `inversions-found` on two instances (three named domains), the merge fix on `main` (PR #1278, unit-proved; its field proof is this row's), the two import shapes that still arrive inverted (a row holding the instance's own measured verdict beside a newer, disagreeing incoming attempt, and a backup from an instance that is itself inverted; both reproduced with the real merge, no test covers either), and the repair script that was on `main` since PR #1117 but named in no gate file. **A date corrected:** no release run started on 2026-09-26. The eight runs in the 16 bundles (five with a report file, three interrupted in the `row5_quarantine` phase (0.3's row 5, row W here) with no heartbeat) all started on 2026-09-19 (run ids `20260919T04…Z`; `085218` and `085230` were resumed on 2026-09-22, `085230` again on 2026-09-26, and armed their soaks on 2026-09-26: `soak.started_at` 15:23:51 and 15:07:57, +02:00). The «release run of 2026-09-26» of the 2026-09-28 entry below, and the sentence of `docs/CHANGES.md` that repeated it (replaced in this PR), therefore do not name the date a run started. | maintainer (project chat, 2026-10-01 00:12 UTC, «17a») · diagnostics ranks 13 and 14 · recorded by the session |
| 2026-09-30 | **The older-rounds list, answered in the thread (03:35 UTC; recorded without code changes).** Rows carried onto the 0.5 list by `R92`: **row H** `PF07` = a (the three ride-along opt-outs fixed now, in their own small PR); **row T** `PF08` = a (the knob's words become kbit/s ×12 and invariant #4 is amended in that PR); **row U** `R99` = with eclipses (the eclipse canon is no longer unstated). | maintainer (project thread «Record the 37 answers», 2026-09-30 03:35 UTC) · recorded by the session |
| 2026-09-29 | **The 37-question list, answered in chat (19:55 UTC; recorded without code changes).** **`R92` («21=b», over the recommended «keep them here»): every row still open at the `v0.4.0` tag — A, B, C, D, E and H to W — is now also a condition of the 0.5 exit** (`RELEASE_0.5_GATE.md` §1b); each keeps its text, bar and status HERE and closes here on its named artifact. **`R91` («20=a»): row H's 15 lane names, three headings and the 16th lane «Places and people» are kept** (H9 answered). **Q925 = a** (row Q: legislation.gov.uk → gesetze-im-internet → e-Gov → EUR-Lex → LEGI last); **Q1113 = a** (row S: the embassy platforms stay excluded, nothing published, nobody contacted — the status quo, confirmed). From the RC round: `RC02` = a (row K keeps the legacy single-file restore forever), `RC08` = a (`RC08.3` row C and `RC08.6` row U confirmed), `RC13` = b with eclipses (row U: the religious dates researched by a networked session and shipped PREINSTALLED, every religion covered, each shown or hidden by the user — the maintainer's note; the eclipse half is the recorded default), `RC15` = c (row T: Q1148's loopback figures stand AND the per-host egress politeness is to be adapted — no figure was written, so it is proposed and asked), `RC17` = a (row U, as built). **Still open, with the maintainer's words on their `RULINGS_INDEX.md` rows:** `RC05` and `D47` (to the thread «Keyword working session»), `RC06` (row S's re-check window — waits on the thread «Fix source qualification»: no source was added in 72 hours on eight instances despite more than 80,000 candidates, and re-qualification is to run as a queue), `RC16` (a later discussion). **No row changed status.** | maintainer (project chat, 2026-09-29 19:55 UTC) · recorded by the session |
| 2026-09-28 | **`v0.4.0` PUBLISHED from the moved tag (row G; no other row changed).** With the GitHub release deleted, the maintainer moved `v0.4.0` onto `00af1d9c`, the PR #1195 merge, from a GitHub Codespace at 10:13 UTC; a website attempt before it had re-published the release on the old tag without a run, since GitHub's website cannot move or delete a tag. `release.yml` run 36408430314 passed its full-suite job and the tag-matches-version step, then created the pre-release with the generated notes (no-telemetry re-check passing), the wheel, the sdist and `SHA256SUMS` at 11:00 UTC. The rows open at the tag are unchanged. | maintainer (Codespace, 10:13 UTC) · `release.yml` run 36408430314 · recorded by the session |
| 2026-09-28 | **`v0.4.0` TAGGED by the maintainer before the exit clause was met; the version flip followed (row G CLOSED).** The maintainer: «I merged all PRs and bumped the version to v0.4.0». The tag is on `ad0f2062` (the PR #1191 merge), with a GitHub pre-release published 02:06 UTC; that tree read `0.3.0`, so `release.yml` run 36368552522 passed its full-suite job and stopped at its tag-matches-version step, and the release carried no wheel, sdist or `SHA256SUMS`. PR #1195 flips the version at the maintainer's pick; moving the tag onto its merge is the maintainer's step, spelled out in row G. **Rows open at the tag, none changed by this entry:** A and B (the release run of 2026-09-26 covered both, read in the project thread «Release candidate diagnostics», whose two live defects PR #1188 fixed; they close once the maintainer has read its report), D and E (read from that same run), C, W, and the operator halves of rows H to V, K and Q among them (every click-through clause among H to U passed the 2026-09-27 fix-check walk); F closed 2026-09-15. Whether those rows stay on this board after the tag or move to `0.5` is not decided here, and `RELEASE_0.5_GATE.md`'s two hard preconditions (row K before its row B, row O before its rows D and F) stand as written. | maintainer (chat, 2026-09-28 02:41 UTC) · recorded by the session, PR #1195 |
| 2026-09-27 | **The fix-check walk (R37): the click-through clause of rows H, I, J, L, M, N, O, P, R, S, T and U passes.** One walker per row re-ran that row's steps and reproduced each of its re-walk items on build `9eb10528`, encrypted, locked at boot, in airplane mode, and did not hunt for new defects. 117 of the 119 items were fixed there and every walkable step passed; an independent re-checker confirmed the two left, N-4 (the Diagnostics job lines kept their language after a live switch) and O-5 (the `/tasks` failure line's zh spacing), both P3. Both were fixed in `38965c0e` and re-checked in Chromium with the re-checker's own scripts. What a sandbox cannot walk is listed per row and is the operator's runs (the real install, the removable drive, going online) or the maintainer's word (H9, the lane names). 32 incidental notes are recorded in `incidental.csv` and `OPEN_QUEUE.md`, not fixed, so the loop ends here. The rows' OTHER clauses (the operator runs, row V, row W, the flip) are unchanged. | `docs/audit/delegated-fixcheck-2026-09-27/`; PR #1191 |
| 2026-09-27 | **The 119 re-walk items fixed (R37; no row closed).** Batches B20 to B30, merged into PR #1191, each item with a test that fails before its fix and a Chromium check, each batch read by an independent reviewer. 116 are fixed in code. J-1 has the minimum fix (the export records its request and the summary reads «Backup incomplete» when a part is missing); making the export one server-side job is deferred to its own slice. R-6, R-14 and R-24 are the Q1150 embed that was never built: the row R text is corrected and the embed goes with `0.5`'s map work unless the maintainer asks for it in `0.4`. The release run now files the Tier-A quarantine pass under row W. Each row closes only when its next walk, of these fixes and its own steps, passes. Leads found beside the fixes are recorded in `OPEN_QUEUE.md`, not fixed, so the loop converges. | PR #1191 (batches B20–B30) |
| 2026-09-27 | **The delegated re-walk (rows H–U) and the first Claude walk of row R (no row closed).** On the fixed build (`0deff9c4`), 227 of the 234 first-walk defects the walkers checked are fixed, 3 are only partly fixed (row M's M1, M7, M14) and 4 could not be checked in a sandbox. Every walkable step of H, I, J, L, O, T and U passes; M, N, P and S fail one to three steps; row R fails. An independent re-checker confirmed 119 items (1 P1, 23 P2, 95 P3), mostly the first walk's defect classes on surfaces it had skimmed. Each row's board cell names its count. Row R's Q1150 clause is CORRECTED: the When / Where embed was scoped, never built. The fixes run as batches B20–B30 in PR #1191. Asked on a card, the maintainer ruled all 119 fixed before the tag, the next walk checking only those fixes and each row's steps (`R37`, 11:04 UTC). | the session, PR #1191 (`docs/audit/delegated-rewalk-2026-09-27/`) |
| 2026-09-27 | **Four blocking decisions answered in chat and recorded (rows G, N, R, V; row W added; no row closed).** The maintainer: «FYI, the blocking decisions: OK for RC01, I'll do the versino switching after all current draft PRs are merged. RC10: go with your recommendation. Row R: OK to move that to 0.5. Row N: keep sudachipy». **Row G:** `RC01` = (a), so the `v0.3.0` pre-release is the `0.3` close, the flip is the maintainer's own after the current draft PRs merge, and `0.3`'s row 5 is carried as the new **row W** (an operator step beside A–C, run by the release run's opt-in step); the exit clause now reads A–E, G–W. **Row N:** `PF12`, `sudachipy` kept on the search path as built; retiring `janome` from the keyword path was not asked and stays undecided. **Row R:** `PF06` = (a), so Q803's default (OSM's convention) moved to `RELEASE_0.5_GATE.md` row L, and row R stays OPEN on its click-through only. **Row V:** `RC10` = (b), so `dumps.wikimedia.org` is excluded for now and the closing probe moved to a Q114 host that stays on the list (the thread's recommendation, «probe a host that's already allowed»); a probe from a session the same morning read `000` for all seventeen Q114 hosts, so the allowlist is still the operator's. | maintainer (chat, 2026-09-27 08:56 UTC) · recorded by the session, PR #1191 |
| 2026-09-27 | **Row I — a defect in K = 3's checkpoint, fixed (PR #1192); the row stays BUILT and still awaits the operator's real restore and the click-through.** A held item leaves its post-swap work to the checkpoint whose swap makes it live, and the checkpoint scoped that work to its OWN batch: measured with a two-item group on disjoint sources, the held item's source counter read 2 over 5 articles as exact, the quarantine scan screened 1 of 4 new articles, and the held item's calendar event missed the durable mirror. The checkpoint now scopes source counters, quarantine and the event mirror to every batch its swap brings in (`merge.py::_swap_group`), widening on doubt, and publishes the batches as `report.swap_group`. The same PR stops a deferring drain that yields to an import from sweeping the counters beside it (R22) | session (import-speed audit, 2026-09-27) |
| 2026-09-27 | **Row N — a regression S8 introduced into the IMPORT path, fixed (PR #1192); the row stays OPEN and nothing else in it changes.** S8 routed the merge's bulk search index through `index_articles`, which re-registered the transform's SQL functions on every 20,000-article chunk. SQLite refuses to replace a function while a statement is active, and FTS5's blob reader is one for the rest of a write transaction, so every import adding more than 20,000 articles failed there — measured through the real merge on both drivers: 20,000 passed, 20,001 and 45,000 failed. The per-chunk call is removed; the index a search sees is identical to a one-chunk merge (the regression test's reference) | session (import-speed audit, 2026-09-27) |
| 2026-09-26 | **Rows H, I, J, L, M, N, O, P, S, T and U — the maintainer's click-through DELEGATED to Claude (R35), and walked; no row closes.** The maintainer asked for the click-through to be done by Claude rather than by them. Under R35 a Claude-run Chromium walk on an ENCRYPTED, locked-at-boot install, every defect independently reproduced, meets Q1128 = a's click-through half; the rows' operator steps are untouched by it. The first walk (`docs/audit/delegated-clickthrough-2026-09-26/`, main at `462145c`, en/fr/ar/zh + 375 px, airplane mode throughout) PASSES J and O for everything a sandbox reaches and FAILS the other nine on 115 confirmed defects (5 P1, 38 P2, 72 P3). Three P1 causes: `#oo-tip` hovers inside `showModal()` dialogs are drawn under the top layer, so Q1002's per-lane hosts are unreadable (H, O, P); a deep-linked analysis tab can paint another tab's results (N); the task-manager page always reads online (T). The failed rows' clauses close on a RE-WALK after the fixes, not on this record | maintainer, project thread; this walk |
| 2026-09-25 | **Row N ADVANCED — S8 BUILT (Q506 🔒 = b, Q507 = a, Q1015 = a); the row stays OPEN.** The search index is written through ONE transform the sync triggers call (`src/database/fts_norm.py`): Arabic harakat and tatweel stripped and alef / teh marbuta / alef maksura folded; Chinese segmented by jieba (search mode on the index, default mode on queries); Japanese by sudachipy (mode C plus its A units), each chosen by script because the trigger sees only the text. Measured first on the index's own `unicode61 remove_diacritics 2`: harakat are SEPARATORS there, not diacritics (a vocalised مَدْرَسَةٌ indexed as five one-letter tokens), and a CJK run is ONE token (东京 found nothing inside 东京大学的学生). Every query literal keeps its raw form first, so nothing indexed before is found less, and a query with no Arabic or CJK builds a byte-identical MATCH. **The one rule that makes it safe:** an external-content FTS5 delete must be handed exactly the values that were indexed, so each transformed document has a row in `article_fts_norm` — its mask for the fold, which is this code's own and is re-run, and its EXACT values for segmenter output, because a third-party dictionary can change or be uninstalled (measured: kept values are 1.5× the source bytes, CJK documents only). A mutation that re-runs the segmenter at delete time fails two tests by corrupting the index; a sudachipy tokenizer shared between threads raised on concurrent use, so each thread has its own. jieba moved to core (pure Python; the sdist hash-pinned in `requirements.lock`, hash-checked install verified), which also segments zh keywords and makes zh a managed language on a default install; sudachipy + its 77 MB dictionary joined `[segmentation]` (compiled); both registered. The search re-index job is resumable, parks for imports and shows in the task manager; on the fixture, 东京 / 北京 / 气候 / المدرسه / مستشفي went from 0 hits to found, `climate` and सरकार did not move, 4 of 6 articles were re-indexed and a second run re-indexed 0. **Found outside Q507 and not fixed here:** Devanagari and Bengali vowel signs are separators too (सरकार indexes as सरक + र), and the fix is a tokenizer option that needs the table recreated — recorded in `OPEN_QUEUE.md`. **What row N still owes:** the re-index on the reference corpus with its counts, the agreement comparison, Q515's cost, the click-through, and the maintainer's word on `sudachipy` versus `janome` (PF12 is blank, so the keyword path keeps `janome`) | session |
| 2026-09-25 | **Row M ADVANCED — the two carried items BUILT (Q413, Q414, Q416 = a; brief `S04-06` S4 and S5); the row stays OPEN.** The keyword fold job re-keys every mention written before lemmatisation (`studies` → `study`) exactly as a lemmatised re-index would, without reading article text, and it is TESTED equal to one: the same fixture indexed with lemmatisation off, folded and pruned, matches the fixture indexed with it on in mentions, counters and top keywords, in both states the job meets (mention languages stored, and missing as on a store older than #1148). It calls the one `lemma_key` extraction now calls, lifted out of the extractor's inner loop for the purpose, so the two cannot drift. `reconcile_keyword_language` is now a keyset scan of `keyword_mentions` alone; a mention with no language votes through its article's, read from the covering index `idx_article_created_lang`, which is the value a backfill would have written. Left out on purpose and recorded in `OPEN_QUEUE.md`: a write-back of old mentions' language, deletion (the prune owns it), re-ranking the 80-term cap, and rewriting term-keyed settings. **What row M still owes:** operator step 2 (both reports on the real corpus) and the maintainer's own click-through | session |
| 2026-09-25 | **Row O ADVANCED — S04-08's S6 (Q1016 = a; its NOTE answered «Main tab», `R32`); every slice is built and the row stays PARTIAL on its operator steps.** The Living sources view is a main tab with Wikipedia, Law and Maps as subtabs: coverage, freshness as dates (newest and oldest check, never a verdict), the stream's timeline with each stored diff in place, the law tracker's changes and the map regions, and Settings → Storage's own cells without the budget input. It replaces the tracked-changes dialog. The tests found three defects (failed map downloads counted under `failed`, a word the manager never writes, so every failure read zero; the diff route read its row after the session closed; the language and the jurisdiction printed raw, which the Q302 guard refused) and the Chromium walk four (every diff line and size change drawn backwards in Arabic, in the new timeline and in the tracked view it absorbed; a group title repeated as its first label; a count that could not agree with its noun in French; a "last change" later than the newest row, with no hover saying why). Cost: one main tab, invariant #32, and CLAUDE.md's ceiling 761 → 768. | S04-08 S6 · `docs/audit/living-sources-clickthrough-2026-09-25/` |
| 2026-09-25 | **Row O ADVANCED — S04-08's S5 (Q1014 = a, Q1018 = a, Q1001 = a); the row stays PARTIAL.** Each lane in the consent hover now states how it leaves: direct, through your proxy, through your proxy pool, or none because protected mode has no usable proxy and refuses. The popup read the stored `http_proxy` alone before, so it told a transparent-mode operator their proxy carried the fetches and told a pool operator there was no proxy; the line now comes from the same reader the fetch path uses. The three lanes that bypass the fetcher say they go direct even with protected mode on (the local-AI one *mostly*, since its installer check is proxied). The Wikipedia stream, which retried silently behind a refused proxy while the lane read "running", now reports `transport-waiting` with the failure; a paused download names airplane mode, the operator or a restart; a failed one shows its error. Q1018 is complete: the law lane end to end over the synthetic jurisdiction, and a synthetic OSM extract (`ZZ`, private-use, raw blobs so the digest can be pinned, with the zlib path re-wrapped at test time) downloaded through the real manager and parsed by `osmpbf.js`, both counting `socket.getaddrinfo` under the installed guard. The Chromium walk (`docs/audit/lane-transport-clickthrough-2026-09-25/`) found four more defects, fixed in the same change: the stream slept through airplane mode for its whole backoff, a fresh install's Wikipedia lane was a file with no schema so it stored nothing, the standalone task manager drew no cause, and the offline hint covered the open language menu. No new host, so SECURITY.md gains the transport paragraph and no table row. Remaining: S6 and the maintainer's own click-through | session |
| 2026-09-25 | **Row O ADVANCED — S04-08's S4 (Q1006 = a, Q1010 = a, Q1011 = a); the row stays PARTIAL.** Settings → Storage exists, as a panel at the top of Data & backup (ruling 42 pins nine subtabs; the maintainer confirmed the panel over a tenth subtab, R33). The published table is `configs/lane_budgets.yml`, and it carries only RULED numbers: the wiki lane's 20 GB (Q707); press, law and OSM show "No published budget" rather than an invented one, which is the cost of Q1010's "every budget is published" meeting a ruling round that published one. The boot reading is shown beside the reference machine and passes no verdict on it. Growth is the change between the first and last `lane_mib_<kind>` reading in 30 days over the wall-clock time between them, shown only after 7 days: a fresh install reads "Not measured yet" for a week, by design. The browser walk found three defects, each fixed before it was recorded: a 120 KiB lane rounded to "0% used", an over-maximum budget refused only as the server's English field message, and signed figures reordered in Arabic. **Still owed:** the maintainer's click-through (Q1128 = a). | session |
| 2026-09-25 | **Transport — three ways protected mode missed the operator's proxy, found while mapping S04-08's S5 and fixed (Q1014; no row changes status).** (1) `guarded_session` read `http_proxy` alone, so protected mode with only a SOCKS pool (C10), a configuration `save_settings` accepts, sent the MediaWiki API and its stream, dumps, ORES, OSM downloads, official statistics, DuckDuckGo discovery and the AI installer out directly while articles went through the pool. (2) `src.api.markets`, `hazards` and `ingestion` built their fetcher at IMPORT, before an encrypted store is unlocked, when the safety settings load from the pre-migration file if one survives, or as their defaults: on an encrypted install whose protected mode was saved in Settings, those three fetched directly with the bot User-Agent unless an older settings file carried the same choice, and on any install a later switch in Settings did not reach them before a restart. (3) requests lets `HTTP(S)_PROXY` from the environment win over a session's own proxies, so every path that left the operator's proxy on `session.proxies` (the single-proxy shared session, the article fetcher when it did not isolate, both preflight side doors) used the system proxy instead. Now every request in protected mode carries its proxy explicitly, the pool counts on both paths with one host-to-member mapping, the long-lived fetchers re-read the setting on use, and protected mode with no usable proxy refuses each request by name (`TransportUnavailable`). A structural guard refuses any fetcher built at import time, and each fix was reverted once to show a test fail. **Still S5's:** the per-lane transport line in the consent hover | session |
| 2026-09-25 | **Row O ADVANCED — S04-08's S3 (Q1020 = a, Q716 = a); the row stays PARTIAL.** The scheduler's `mode` is retired: every pass collects the feeds, and markets, law, hazards, discovery and the crawl supplement run beside it on the housekeeping lane, with the Wikipedia stream on the online seam. The migration follows the brief's design note (every lane the old mode implied ON, press ON) and is one-time by construction: it acts only while the stored blob still has `mode`, and the first save drops the key, so a migrated lane the operator switches off is never switched back on. The markets mode's two extra behaviours, the operator's own price rules and the subscribed-statistics refresh, become two opt-ins that default OFF (what every other install was doing) and are migrated ON for an install that was in that mode. `mode` stays declared on the request model and is refused by name. Chromium-walked in en/fr/ar and at 375 px with zero page errors, which found a ReferenceError the Python tests could not see. Remaining: S4–S6 and the maintainer's own click-through | session |
| 2026-09-24 | **The release run's instrument corrected against six field machines (rows B, C, D, E, G, P; no row changes status).** The first field batch (`docs/audit/16`) found the run could not have closed row C anywhere (it read the coverage block from a member the bundle never writes it to, and was blind to a member skipped at its deadline), labelled rows B and D "measured"/"skipped" after a failed end-of-window reading, lost three rows to one pool timeout after a 72 h soak, ran its soak and its phase durations on the wall clock (a NUC phase "ended" seven hours before it "started"), and put a multi-day whole-corpus re-index (row 5) BEFORE the soak. Now: row C reads `manifest.json` → `run.runtime_coverage` and every member's `outcome`; each row takes its status from the evidence it holds and names an error as one; each end-of-window reading has its own session, a pool-timeout retry, and survives its neighbours' failures; every duration is monotonic and a suspend ends the stretch; row 5 runs LAST with collection paused (`FD01`, `FD02`); the bundle's release-run member carries the live run. The chronology reads the 72 h bar on COLLECTION stretches (the collector's own start and stop events) with the process's uptime beside it, places every record on its session's own clocks (a backward NTP step no longer shortens the uptime by 12 h), and seeds the session before the ledger from forensics' sentinel. | field round 2026-09-24 · PR #1172 |
| 2026-09-18 | **Rows B and D gain a CHRONOLOGY and the run a RESUME (same day, ruling R20; no row changes status).** The maintainer asked how a returning operator would know when the machine stopped and whether 72 h had been reached. A session ledger (`data/session_history.jsonl` + a one-minute liveness file) now records every boot, end (a dead session's from its last tick), suspend (the clocks' inference) and network crossing; `GET /api/diagnostics/chronology` reads it beside the run's state into sessions, gaps, stretches and the summary (restarts, since the last restart, the longest CONTINUOUS stretch, the bar on ONE stretch — row B's clause is unchanged, and the discontinuous sum is shown beside it as not the bar); the Diagnostics box draws it (`src/static/ootimeline.js`), the task-manager System tab shows the three numbers, and the bundle carries `chronology.json`. **The release run RESUMES after a restart** (`POST /release-run/resume`): the measured phases kept, the backup and the restore never redone, the soak a new stretch; the report lists every stretch and session and row B's evidence names them. Mutation-checked (9/9), Chromium-walked in en/ar (`docs/audit/release-run-clickthrough-2026-09-18/`, second pass). Prompt 17's reading rule for row B therefore reads the report's `soak_stretches` too. |
| 2026-09-18 | **THE OPERATOR ROWS GET ONE BUTTON (rows A–E, K, P, Q, T; no row changes status).** The maintainer asked for "a one time single (fully automated) button in the advanced settings in the diagnostics tab" to run in parallel sessions for more than 72 h, and a second one for the ~1M-article instance. `src/monitoring/release_run.py` + `src/api/diagnostics/release_run.py` (imported LAST, the six routes declared in the split guard) + the box under the P0 box. It COMPOSES, never re-implements: the P0 kit into a dated `OpenOmniscience_Backup` folder (rows K/J), a SUBPROCESS committed restore of that backup into a throwaway fresh install encrypted under the backup passphrase, reading the qualification integrity and the duplicate-key scan off the restored corpus (rows A/E/I/K — the two-process shape `tests/test_restore_fixture_matrix.py` records, because one process is a self-restore), the ruled online seam + the unattended kit for the soak with an hourly bounded heartbeat and a 24-hourly INTERIM report (rows B/D/P), the live law-host + scoring-endpoint probes and a weights-digest PROPOSAL (rows Q/T), and at the end the soak window, the live integrity, the lane counters and the all-diagnostics job whose archive is READ for its coverage block and zero-byte members (row C — REQUIRED under the `million` profile, evidence-at-this-scale under `release-scale`). ONE report, a status per board row from a closed vocabulary, a tally never a score; the state file survives a restart and the status route reports a run the process lost as INTERRUPTED at its phase. **What the button may not decide, and does not:** the 0.3 row-5 quarantine pass (ruling A1 deferred it) sits behind an opt-in that defaults OFF and is mutation-checked to stay off; no tag, no version flip, no ⛔, nothing written to `configs/`. **Deliberately not automated, with the reason in `OPEN_QUEUE.md`:** Q410's ring ritual (the script's `--top` is English-only today and the ruled shape is per-language), Q1118's shortlist run (no in-tree runner), `BACKUP_SUMMARY.md` (the dialog's own path writes it; the run's folder is verified by the P0 kit's `verify_stream_backup` instead), K = 3 checkpointing (one backup). **Found while composing the unattended kit into it:** the unattended button went online server-side with NO consent popup — an invariant #14 gap in a shipped control, fixed in the same PR (both buttons now pass `ensureOnline`). 34 tests + a node suite; an 18-mutant matrix, 18 killed after two survivors turned out to be test findings (no test drove an interim write; the consent-gate needle was satisfied by dead code) and were closed; the fresh-install helper driven END TO END in its own process on the row-K fixture; Chromium-walked in en/ar with zero errors (`docs/audit/release-run-clickthrough-2026-09-18/`), the maintainer's own pass still owed | session |
| 2026-09-18 | **Row U RE-VERIFIED and EXTENDED (PR #1161, session 2): the three zeros hold, and they were measuring less than they looked.** Every gate PR #1160 closed was re-run independently and exits 0 at the numbers claimed. But `--audit-chrome` scans the `app-*.js` modules with a REGEX LIST, not the HTMLParser that covers `index.html`, and that list carried exactly two HTML shapes — `<th>` and `<button>`. Prose inside any other tag contributed **zero by construction**, which is how Home's empty state (the surface the never-blank-and-silent rule exists for) and four `r-caveat` lines in the reader were English in all twelve locales behind three green gates. **Measured twice, both directions:** nineteen prose tags took `--max-untranslatable` 0→35 and keying took it back to 0; then `<span>`/`<div>` — the two commonest tags in this codebase's generated markup, left out while `figcaption` was in — took it 0→83 and back to 0. **120 keys ×12 (1,320 translations), and the ratchet never moved off 0: the gate's NUMBER did not change, what it MEASURES did.** The Home empty state needed markup SURGERY rather than keys (seven bold Lead names cut it into nine text nodes, so keying only the keyable half would have shipped the recorded mixed-language-glance defect); it is now one `tf()` frame with seven slots. **A second, separate defect class was found by a differential probe** — render each tab twice, switching into `ar` versus booting into it, treating the boot render as correct by construction: two surfaces never repainted on a language switch, one of them a caveat whose translation ALREADY existed in all twelve locales and was simply never shown. **Three pockets are measured and NOT swept, recorded in `OPEN_QUEUE.md` rather than left silent:** 8 concatenation-built strings, 22 on the server-rendered reader page, and the one decision both turn on — whether `reader.js` gains an i18n binding it has never had. What row U still owes is unchanged: `RC13` = (b)'s networked research session, and the Patterns-lens flip's operator-labelled sample | session |
| 2026-09-18 | **Row U — SESSION WORK COMPLETE (PR #1160): the i18n remainder (Q1152 = a), `via:*` (Q1130/RC17), `_SPARSE_BAR_MAX` (RC08.6/L5) and the Patterns-lens numbers (Q1124).** **THE FIGURES, WITH THE METHOD, because the two classifiers disagreed by 176 strings and a bare number would hide which one was used:** counted with `audit_chrome()`, the function `--max-untranslatable` itself calls (CI runs that gate WITHOUT `--audit-chrome`, which only prints), the untranslatable count went **461 → 0**; counted with `unkeyed_t_calls()`, the unkeyed `t()` literals went **224 → 0**. The two populations are **not nested** — 11 of the 224 sat outside the 461, because the audit shapes cap at 200 characters and floor at 3 while the `t()` gate runs 1–400, which is how `OK` and `ok` rendered Latin in eleven locales for the app's whole life. **A THIRD GATE WAS NEEDED AND IS THE SLICE'S REAL FINDING:** every pattern in both existing gates excludes `{` from the literal, so `tf("… {slot} …")` — the app's OWN interpolation frame, and the prescribed FIX for a welded fragment chain — is invisible to both, and converting fragments into a frame lowered both numbers whether or not a key was ever added. 17 live frames had no `en.json` key, seven of them in `app-backup.js` and shipped long before this slice. `--max-unkeyed-tf-frames` closes it, discovers its alias set from each file's own bindings rather than listing it, and is at 0 too. **WHAT THE TWELVE TRANSLATOR AGENTS FOUND IS NOT A TRANSLATION MATTER:** a `kbps` unit welded outside any `t()` (so `ru` showed `500 кбит/с` on the placeholder and `500 kbps` on the live readout beside it); `t("of")`, two characters, under both gates' floor and with no key, wedged in English inside `Page 1 of 5` while `test_analysis_articles_paginated` asserted its two fragments and called the control present; the seconds abbreviation, same story; one label spelled two ways; and a COMMENT of this session's own that pasted a call-shaped literal, which both scanners read as a live UI string. The Chromium walk in en/fr/ar/zh/hi found two more: the Q1124 panel freezing in the boot locale, and a stoplist count rendering `2,555` with an English comma in a French panel whose sibling figure reads `100 000` — a bare `.toLocaleString()` reads the BROWSER locale, which the language switcher never touches. Three such sites were fixed (the ones this PR already changed); the other 60 are recorded in `OPEN_QUEUE.md` as a deliberate omission with the count and the question a sweep must answer first. **THE FULL SUITE CAUGHT ONE MORE, AFTER THE TARGETED TESTS WERE ALL GREEN:** the gate panel was wired with an `_ADV_LOADERS.diagnostics` entry, and `test_opening_advanced_still_fetches_nothing_for_diagnostics` refused it — that section's standing property is that expanding it fetches NOTHING, satisfied by construction because every report in it is button-driven. The decision was made against the loader (the gate reads a COUNT over every article, a table scan on the ~1M-article instance row C targets) and the panel now has a **Check now** button reusing an already-keyed label, so it cost no new string in any locale. **NOT BUILT, BY RULING:** `RC13` = (b)'s religious dates — briefed below, not implemented | session |
| 2026-09-18 | **Row U — `RC13` = (b): the religious-dates work is BRIEFED HERE AND NOT BUILT, because it is a NETWORKED RESEARCH session and this one has no authority to invent a date.** The assumption is the register's G8 side over Q1135 = b; the CONFLICT stays recorded on both rows and nothing was removed from the agenda meanwhile. **THE BRIEF for that separate session.** *Scope:* the recurring religious dates the agenda would show, sourced from PUBLISHED calendars and the relevant authorities, each one dated, attributed to the authority that published it, and carrying the METHOD by which it was obtained — a scraped table, a published PDF, an authority's own API — beside every entry. *The refusal that defines the slice:* a date that cannot be sourced is ABSENT, never computed to fill the gap and never carried over from last year, because a religious observance whose date an authority has not yet announced is not knowable, and an agenda that guesses one is an agenda a reader cannot trust about the ones it did not guess. Observances whose date DEPENDS on an announcement (a moon sighting, a local authority's proclamation) must say so on the row itself, in the reader's language, rather than being silently omitted or silently fixed. *Constraints that are not negotiable by that session:* every fetch goes through `EthicalFetcher` behind the ONE consent gate (invariant #14, and #14e — the estimate, the preview and the reachability check egress before the action does, so each of those is gated too); robots.txt stays fail-closed; the strings ship ×12; each external artifact gets a `configs/external_artifacts.yml` entry IN THE SAME COMMIT, with a dated `*_AS_OF` and an upstream check, because a calendar is the archetype of a thing that goes stale silently. *What it must NOT do:* decide the eclipse canon. `RC13` asked for `+ eclipses` or `− eclipses` after the letter and nothing was written, so that half is neither dropped nor funded — it is UNSTATED, and no session may settle it by building or by removing. *Why it is not this session:* the dates come from outside, this environment's egress allowlist (row V, Q114 ⛔) does not carry those hosts, and the alternative to fetching them is fabricating them | session (per the round's §0 blank rule) |
| 2026-09-24 | **Rows S and T: two field defects fixed, and four more beside them (no row changes status).** From the six-machine field round (`docs/audit/16`, landing with PR #1172). Row S (`S04-12`): a qualification pass the memory floor declines was reported "done [0/79977]" on every machine; it is now a named refusal with its override on the Sources panel, and the unattended arming asks the same floor. Row T (`S04-13`): a persisted crawl-delay stamp written on a clock 12 h fast deferred a priority host seven hours; the stamp is now clamped to its own delay. Beside them: a collector resume that outlived its retries is kept pending instead of abandoned (Lenn's collector was off five days), custody INGEST entries skipped on a pool timeout are written late and marked so, the fixity audit re-hashes each writer's rows with that writer's formula (22–29 % false "corruption"), the integrity sweep claims no verdict from checks that did not complete, and the card audit and the bulletin report a spent budget as one. | field round 2026-09-24 · PR #1173 |
| 2026-09-07 | Board created from `RELEASE_0.3_GATE.md` §5. Rows A/B/C carried under their existing rulings; D/E/F proposed | session |
| 2026-09-07 | **Row D BUILT** — `GET /api/diagnostics/soak-window` + the `soak-window.json` bundle member. It adds no sampler: it composes the durable readings that already existed and states, per block, the window it actually read. The row stays open because *built* is not *read* — it closes on one report from a run of ≥ 72 h | session |
| 2026-09-09 | **Row F ADVANCED, not closed** — the live visual audit + fix pass closed two of its three open items (the 12-locale sweep is done; honesty rule 9 ran as three adversarial re-verifiers rather than one screenshot re-read). The Gecko/AppVM bar is untouched and every stamp still reads "awaiting human UX pass" | session |
| 2026-09-09 | **Row F ADVANCED again, and the browser bar is now measured at three widths** — the open-queue burn-down swept axe-core at 1440×900, 768×1024 and 390×844 across every main surface, the palette, the analysis window, `/tasks` and all eight Help documents, and closed every finding (the 768 sweep found a CRITICAL that the 1440 sweep could not see: the icon rail hid every nav label from the accessibility tree). Still ONE engine: Chromium only. The Gecko/AppVM bar is untouched, and every stamp still reads "awaiting human UX pass" — a passing axe sweep is a conformance measurement, not a human judging whether the thing is usable | session |
| 2026-09-15 | **Rows D and E become BARS; row F CLOSED as-is** — the answered roadmap sheet, Q117 = a on Q1128 = a: the verification bar is Chromium in the sandbox plus the maintainer's click-through, Gecko best-effort. Every stamp reading "awaiting human UX pass" now closes on the maintainer's click-through of that surface, recorded per surface; no second engine is owed | maintainer (answer sheet, 2026-09-15) |
| 2026-09-16 | **Row U ADVANCED — the `diagnostics.py` split half only (Q1139 = a, J1)**, and the row stays OPEN: `src/api/diagnostics.py` (6,741 lines, 131 routes — recounted at `a962ea1b`; the brief said 6,741/131, the answer sheet 6,200/126) is now `src/api/diagnostics/`, 18 contiguous slices. Behaviour-neutral is MEASURED, not asserted: the 131-route table (path · method · name · endpoint · ORDER) is byte-identical to a snapshot taken from the pre-split module, read from the ROUTER's own definitions, and the manifest's `excluded` block is untouched. The split also found a REGRESSION it would have shipped silently — the runtime coverage report read `pathlib.Path(__file__)`, which after a split is one slice, so it saw 28 of 131 routes and reported `complete` — now fixed and pinned. What row U still owes: the i18n remainder (Q1152), the religious-calendar clause (Q1135, and its RC13 conflict), the encrypted click-through variant (Q1149), the FUTURE_DEVELOPMENTS reality check (Q1141), the newsletter attach (Q1151), `via:*` (Q1130) and the Patterns-lens numbers (Q1124) | session |
| 2026-09-16 | **Row C's E1 clause is VERIFIED-PRESENT, not a build — and the half that was missing is now pinned.** The staleness guard was run before writing any code and the mechanism RC08.3 places here already ships: `month-occupancy.json` is an all-diagnostics member produced automatically at `sample=400` (`src/api/diagnostics.py:4045`), classified in `_DIAG_COVERAGE_MAP` (`:4412`), landed by commit `6e4ca524`, with a test that drives the REAL member generator rather than the route signature. What was NOT pinned was the ruled NUMBER: the guard asserted `isinstance(requested_sample, int)` — satisfied by any int — so 400 was true of the code and asserted by nothing, and PROMPT_06 slice 3 reads this file to decide whether the month-name ban becomes date-aware. Now `== 400`, mutation-checked (sample→41 reddens it by name). No operator run is owed for this clause; row C's own bar (one ~1M-instance bundle reading `complete: true`) is untouched and still operator-gated | session |
| 2026-09-15 | **Rows G–V ADDED** — the sixteen 0.4 slices from the answered sheet (Q105 = a: contents amended, theme kept), each citing its question IDs, each with a brief under `docs/plans/2026-09-12-beta-pathway/`. No target dates (Q110 = c); operator time unbounded (Q115 = c) | maintainer (answer sheet) · rows written by the session |
| 2026-09-15 | **Premise corrections from the brief-writing pass, hand-verified:** `v0.3.0` already exists as a 2026-08-23 pre-release (row G); the `OOS` token lives in the bulletin / evidence / store names (row J); `simplemma` is already in the `[analysis]` extra (row M); the FTS tokenizer already folds diacritics and the `[segmentation]` extra carries `janome`, not `sudachipy` (row N); boot only logs the re-index backlog (row I); `SECURITY.md` also omits `wikidata.org/w/api.php` and `huggingface.co` (row H). No ruling changes; the open details are named for the maintainer | session (briefs S03-01, S04-01, S04-02, S04-03, S04-06, S04-07) |
| 2026-09-15 | **The exit clause written** (§1): rows A–E, G–V closed on named artifacts; the pending ⛔ questions block only the rows that name them | session, from Q110/Q112 |
| 2026-09-15 | **The 2026-09-06 register's 65 answers (rulings artifact, 15:02–16:00Z; recorded in `QUESTIONS_FOR_THE_MAINTAINER.md` in place, `OPEN_QUEUE.md` head entry, `RULINGS_INDEX.md` rows A1–L10) — effects on this board, nothing resolved by the session:** row G — A1 `deferred` (the operator step; `RC01` asks whether the version flip may proceed on the existing pre-release); row K — C1 «a, but wait for version 0.7» CONFLICTS with Q215 = a (⛔, `RC02`; nothing removed meanwhile); row M — B3's method (a seeded stratified sample per batch, furniture words only, open-class refused) recorded; the Q1103/Q1104 CONFLICT stays; row Q — L6 «Promote [pdf] into the default» (pyproject; both venv profiles re-verified; the coverage report's «without [pdf]» wording retired); row S — B5 (the source-qualification export + merge run automated inside the diagnostics), B6 (`high_link_density` as the second, measured criterion beside the kept 0.5), B4 CONFLICT (no tool vs Q1105's worklist surface, `RC05`), B7 window CONFLICT (90 days beside the whole-history verdict vs Q1108's 6 months instead, `RC06`; B7's article-revision-tracking note placed by `RC07`); row T — L4 qualifies Q1148 (`RC15`); row U — G8 CONFLICTS with Q1135 = b (drop vs a dedicated networked session, `RC13`), L10 CONFLICTS with Q1130 on the coverage-state prefixes (`RC17`), L5 proposed here (`RC08.6`), A4's actions (banner + archive, never merge) beside Q1141's depth, L1/L3/L7 consistent; row V — F1 «add them» confirms Q114 = a; E2's host undecided (`RC10` ⛔). | maintainer (the register, 2026-09-15) · reconciled by the session; the confirmation round is `docs/design/RULINGS_CONFIRMATION_2026-09-15_REGISTER_ROUND.md` |
| 2026-09-15 | **The RC confirmation round came back UNANSWERED — 0 of 22 `ANSWER` lines carry a letter — processed per its own §0; nothing resolved by the session.** Effects on this board, all reversible by writing a letter: row G — `RC01` ASSUMPTION (b), the flip keeps waiting on 0.3 row 5; row K — `RC02` ⛔ PENDING, the legacy restore half untouched; row S — `RC05` ASSUMPTION (a) no tool, `RC06` ASSUMPTION (a) 90 days beside the whole-history verdict, `RC07` ASSUMPTION (b) article revision tracking to its own 0.5 slice; row T — `RC15` ASSUMPTION (a), Q1148's figures stand; row U — `RC13` ASSUMPTION (b) the religious dates get a networked session **and the ECLIPSE CANON is left UNSTATED** (the `± eclipses` suffix was not written, so this row no longer reads it as dropped), `RC17` ASSUMPTION (a) the coverage-state prefixes filtered too, `RC08.6` ASSUMPTION (a) L5 placed here; row V — `RC10` ⛔ PENDING, `dumps.wikimedia.org` carved out of the Q114 allowlist. Eight of the assumptions sit on CONFLICT questions and follow the later channel exactly as §0 directs; BOTH answers stay recorded on their `A1`–`L10` and `Qnnn` rows. **No row changed status.** | maintainer (the round, left blank) · §0's blank rules applied by the session |
| 2026-09-15 | **The 0.4 board re-verified against the tree at today's `main` (`0d6e4708`): rows G–V, every §2 staleness anchor of all sixteen briefs re-run by grep, never from memory. 127 anchors; 126 live; ONE wrong.** The one: brief `S03-01` (row G) cites `docs/product/RELEASE_0.3_GATE.md:33` for the 0.3 board's row 5 — `:33` is row **6** (the DB-10 page-size bench, CLOSED 2026-08-13); row 5 is at **`:32`**. The text the brief quotes («**OPEN** — criteria **agreed 2026-08-23**; the pass has not been run») is row 5's, verbatim and still exact, and the 0.3 gate has not changed since the briefs were written — `git diff bebcef4..origin/main` on that file is EMPTY and row 5 sat at `:32` at `bebcef4` too, so **the anchor did not drift: it was mis-cited when written**. Corrected in the brief in this PR. **No ruling changes and no row changes status** — row G still waits on row 5 (`RC01`'s assumption), and row G's own 2026-09-15 premise check about the existing `v0.3.0` pre-release is re-confirmed unchanged. The other 126 anchors were checked against the claim each brief quotes beside them rather than against the nearest identifier: an earlier, looser pass flagged eleven and **nine of those were the checker's own false positives** (it matched a neighbouring backticked name instead of the brief's claim), hand-re-verified one by one before anything was recorded — `folder_backup.py:48`, `artifact.py:48`/`:650`, `main.py:1450–1455`, `source_tags.py:441`, `models.py:786`, `runner.py:744–761`, `fts.py:254`, `qualification.py:230` and `calendar_feeds.yml:3288` are all exact. | session (grep-verified at `0d6e4708`) |
| 2026-09-15 | **Row G re-checked and NOT flipped — the version stays `0.3.0`.** The session that shipped row V's generator re-read the two rulings row G turns on rather than inheriting them from a brief: `A1` reads `deferred` (the operator step — the Tier-A quarantine run with `include_prose_gate=false`, the re-index, the count under `nav-soup-v2`, the `v0.3.0` tag — deferred by the maintainer, no date, Q110 = c), and `RC01` came back BLANK on a round whose §0 turns a blank non-⛔ into a labelled ASSUMPTION at the stated default, which here is **(b): keep waiting on 0.3 row 5**. So the flip's precondition is unmet and nothing of `S03-01` was built — not `pyproject.toml`, not the README `**Version:**` line or its stale "latest tagged release: `v0.2.0`" note, not `docs/CHANGES.md`, not the 0.3 gate's §1/§3 tag record. **What this row waits on is the operator, in this order:** (1) their word on whether the 2026-08-23 `v0.3.0` pre-release at `917e8095` IS the 0.3 close (it is a LIGHTWEIGHT tag where §7.3 prescribed annotated, and it was cut BEFORE row 5 was run — a session never moves, deletes or re-cuts a tag); (2) 0.3 row 5's four `curl` calls from their machine; (3) the flip PR. Reversed the moment a letter is written at `ANSWER RC01` — `a` would let the flip proceed on the existing pre-release. | session (rulings re-read at `338dc868`, nothing decided) |
| 2026-09-17 | **Row P ADVANCED — S3 and Q728's endpoint half.** Q702's note inverts its own answer label, and the note is the ruling, so the toggle ships DEFAULT ON with stop / start / halt / resume. What it is NOT is the interesting part: nothing consumes `wiki_lane_state` yet — grep-verified, no `WikiEventStream` is constructed anywhere — so a control reading only the stored state would have told an operator *“running: every edit arrives as it happens”* while nothing was connected. The status now carries `state` and `active` as two facts, and `active` is read from a registry the read loop maintains itself, because a hardcoded `False` is true today and becomes the INVERSE lie the day someone wires a collector and does not think to come back — an operator told nothing is happening while their machine streams. The breathing accent is gated on the activity rather than the choice, an unknown state is REFUSED rather than drawn as “stopped”, and both are mutation-checked. **The ×12 pass corrected an instruction of this session's own:** measured against the shipped files, ar/bn/fr/hi/pt/ru/zh spell Wikipedia IN SCRIPT in 18–19 of 20 existing values, fr uses “Go” and ru “ГБ”; the hostnames stay Latin in all twelve, and a test asserts it, because a localised hostname is an unreachable address printed on a consent surface. **Three defects found by guards rather than by reading:** the painter's state vocabulary was derived by elimination; the i18n extraction read only the painter, so a string rendered by a toast alone reached the locale merge unkeyed with the guard green; and the retirement's own absence test compared a DECORATOR path against prefixed router paths — asserting the absence of a string that could never have been present, which is a guard that cannot fail reporting safety. Q728: the POST is gone, the offline reader stays, and BOTH are pinned, because a test asserting only the absence would be satisfied by deleting the subsystem the same ruling keeps. Chromium-walked in en/ar/zh/de/fr × three states, zero findings (`docs/audit/wiki-toggle-clickthrough-2026-09-17/`) — after a first pass that photographed the page behind an open first-run modal and still reported zero, which is the DOM being right and the picture showing a dialog | session |
| 2026-09-17 | **Row P ADVANCED — S1 and S2 BUILT.** The Wikipedia lane now has a change feed and a storage shape. The SSE client is hand-rolled in two halves (Q1015 = a): `src/wiki/sse.py` is the wire format with no I/O, because every defect an SSE client can have that a test can reach lives in the parsing; `src/wiki/stream.py` holds the connection. **The mid-stream kill-switch check is the whole reason it is a class and not a loop at a call site** — the app-level gate sits in `request()`, which returns long before a stream ends, and the socket-level guard can refuse the next CONNECT but cannot tear down an open one; a naive loop would have kept storing edits after an operator engaged airplane mode. **A premise was corrected rather than inherited:** the substrate's own adapter recorded that a change carries no page id, a conclusion drawn from this repo's parser and not from the API — `rcprop=ids` was already requested and `revid`/`old_revid` already kept from it. Carrying `pageid` makes Q715's ruled identity cost nothing and a page MOVE keep one entity instead of silently becoming two. **Q705's fields are rows, not columns**, because a typed column gives every page every field filled with `NULL` and the first `or 0` downstream turns a gap into a measured zero. **Six defects found in this slice's own work, each reproduced before it was fixed:** two log events sharing one `change_ref` (a revid of `0` is not `None`, and the substrate deduped one away); the cursor trailing the stream by every event it deliberately filtered, which over days would drift out of EventStreams' retention and make the lane report a gap over a stretch where nothing was missed; `idle_seconds` written only when an event arrived, so it read `0.0` throughout the stall it exists to show; a caller stop and a kill-switch refusal sharing one exception type, so a caller would log "stream ended" for a withheld permission; an over-long `Last-Event-ID` that `String(256)` would have stored truncated, which looks like a position and is not one; and a fixture wrong in the code's favour twice. A mutation matrix over all six new guards reddened each BY NAME, and **two mutants survived the first pass** — both coverage findings, both closed. The fixture stream runs end to end with the airplane socket guard installed and resolves **zero names** (counted at `getaddrinfo`, because a DNS resolve is itself egress and counting HTTP requests would not be the same claim), and the same pass is refused by name with the switch engaged. **The per-request unit is 50 PAGES**, read from the answer sheet §8's SEARCH-VERIFIED etiquette line and corroborated at `ROADMAP_INTAKE:408`; NOT re-verified live, because every Wikimedia host answers `000` from this sandbox (`api.github.com` answers 200 as the control), so row V's operator confirmation stands. `stream.wikimedia.org` and `wikimedia.org` are NEW hosts and are in `docs/SECURITY.md` and the consent hover in the same diff (Q1001); Q706's own impact line anticipates it | session |
| 2026-09-17 | **Row N ADVANCED — S2 BUILT (PR #1153), and the row stays OPEN for S8.** Q502: `ooChart` learned to stack, so invariant #16's ONE toolkit still draws every chart on every surface. A stack asserts PART-TO-WHOLE, which is a much stronger claim than lines on shared axes, so it is earned: `_stackSeries` is pure and returns a NAMED refusal for a published gap (filling one with a zero turns *nobody measured this* into *we measured none*), for `indexed` (summed rebasings have no referent), for `logY` (heights on a log axis do not add) and for a single series; the caller prints which one. Its axis starts at ZERO, and the distinct article total sits beside it under a caveat naming the overlap, because per-language mention counts double-count a bilingual article and do not sum to it. Q417: the per-language breakdown reaches the AGGREGATE rows' hover — `queries.trending` had been publishing `language_breakdown` on every ring row since the backend PR, and its only reader was on the keyword-LABEL path, so the ruling's own surface had it computed, serialised and read by nobody. One helper, two callers, and SELECTIVE: a term in no ring gets nothing, because a breakdown on every row trains the reader to ignore the one that means something. **Four defects found by measuring rather than asserting:** (1) the stacked hover reported the BOTTOM band wherever the reader pointed — the hit test compared TIME only and every band shares the timestamp grid, so it tied on every point and the first series iterated won; mutation-checked, the pre-change rule really does answer `en` where the pointer is in `fr`. (2) `loadAnalysis` built the lens for EVERY tab one line ABOVE the `await OOI18N.ready` the previous PR had just added — the wait fixed the frame text it was written for and left the two readers above it unguarded, so a non-`en` reader's first chart described a resolution computed without their language; measured as `hi` issuing the trend request twice, once bare and once with the locale, and the same window let a Trend click render from `null` params, i.e. the literal word beside a list counting the concept. (3) The FIRST RENDERING drew filled bands — polygons between measured points, which on this corpus' two timestamps became six wedges sweeping diagonally across a week, a trend nobody measured. The running sums, the five refusals, the zero axis and the overlap caveat were all correct; the picture was the only thing wrong, and only a picture could show it. Invariant #16's sparse rule existed for exactly this and had not been applied, because it is written about lines and a band is not one. Painted canvas samples fell from 18,136 to 1,335, and that difference is the fabricated area. (4) The translation pass found `hi.json`'s `"mentions"` spelling one Devanagari word with a BENGALI letter inside it — on a string this very view renders, correct in 39 other keys of the same file, and invisible to every gate the project has (`--min 100` counts keys, not spellings). A token-level script scan now guards all twelve locales and found that token was the only one. Chromium-verified in en/ar/zh/ja/hi (`docs/audit/stacked-by-language-2026-09-17/`), reading the CANVAS pixels back, because a chart that paints nothing satisfies every source assertion ever written about it. **What row N still owes:** S8 (the CJK segmenters, Arabic folding and the re-index with its before/after counts — last, and never concurrent with import work on the FTS path), the real-corpus counts, Q515's cost at the ring-size extremes, and the maintainer's own click-through | session |
| 2026-09-17 | **Row N ADVANCED — S7 COMPLETE (PR 4).** Q511, plus two premise corrections hand-verified against the files: the first clause was already HALF true (`rising_concepts` merges rings through `queries.trending` and `across_channels` unpacks them), and of the two sections left `by_topic_tag` groups by TAG and presents no keyword, so it was deliberately not changed. `country_coverage` was the real one, and its merged article count is the number three plausible implementations get wrong three ways — a sum double-counts an article carrying two members, a `max()` is a floor wearing a count's name, and only `COUNT(DISTINCT)` over every member id is what the row claims to be; all three mutation-checked, as is the headroom that keeps a top-N cut from dropping the members the merge exists for. The note's annexe is a ZIP MEMBER (an "annexe" here is one companion ZIP per edition), read from the record rather than re-derived so it cannot contradict the report it annexes, written for every edition with an honest empty state, and its module-level title constant registered in the AST harvester's exception tuple — the trap that would otherwise leave a sentence in English in eleven locales with every gate green | session |
| 2026-09-17 | **Row N ADVANCED again — S7's first half (PR 3).** Q510: the watch engine's own docstring promises that *"a watch means exactly what searching for its query means"*, and `S04-07` made searching mean the CONCEPT — so a matcher still searching the literal word had quietly broken that promise the day the omnibar changed. Threaded into `_fts_matcher` beside the quarantine gate, disclosed on every row and firing, with the one-off consequence stated rather than hidden (the first pass sees the ring's other-language articles as new). Q512: a genuine two-level tree, with four refusals — an arm is a language the corpus ACTUALLY carries, the ones it has nothing in are NAMED, an association hangs off the arm it was measured on, and a spelling shared by several languages says so (found by reading real output: `clima` is es, it AND pt, so one Spanish article drew three arms that read as coverage in three languages). The geometry is READ BACK out of the emitted SVG rather than asserted. The Chromium walk found the walk's own button matcher clicking **Map** because the Map handler contains the word "concept", and — unrelated and NOT fixed here — that `python -m src.api.main` serves a half-broken app (`/api/insights/graph` 500s on a re-registered Prometheus counter), which `--ephemeral` ships. `test_alpha3_display_surfaces` caught a real Q302 violation in the first draft (bare two-letter codes on the arms) | session |
| 2026-09-17 | **Row N ADVANCED — the reader-facing half of cross-language search (PR 2, after PR #1149's backend spine).** S4, S3's reader half and S1's persistence half: one lens (expand · cap · sense) applied ONCE to the params every analysis tab reads, persisted in the tab seed AND the URL, with a language chip on every row, a group-by-language view over those same rows, and the per-form counts with their single total. **Three defects it found rather than assumed, each measured:** (1) the per-form readout called `resolve_concept_keywords`, which on a 120-form ring took **166 s on a three-article corpus** — `simplemma`'s dictionary cache holds EIGHT and `LEMMA_LANGS` has NINE, so the hit rate was exactly zero and every lemmatisation re-read from disk (483.94 ms/call at 9 languages, 0.00 at 8, 0.01 once the factory is sized from `LEMMA_LANGS`; now 8 ms, and the test A/Bs the shipped default so a green result is never taken on trust); (2) the Trend tab still searched the LITERAL term, because it builds its URLs from a term rather than from the params object — the same split #1149 closed, one tab further along, with a term-only cache that served the widened chart to a reader who had just turned expansion off; (3) the Chromium walk (en/ar/zh/ja/hi) found the server's own caveat rendering in ENGLISH on four translated pages, and a boot RACE that left `hi` with an English frame while `ar`/`zh`/`ja` were translated. All fixed; the `698 concepts` baked into that caveat is gone, because a number in translated prose can neither be keyed nor stay true. **The row stays OPEN:** S2 (Q417's hover, Q502's stacked series — `ooChart` does not stack), S7 (Q510, Q511, Q512), S8 (segmenters, Arabic folding, the re-index — last, never concurrent with import work on the FTS path), the real-corpus counts, Q515's cost, and the maintainer's own click-through | session |
| 2026-09-15 | **Row V PART-SHIPPED: the release-notes generator exists and the workflow calls it.** `scripts/release_notes.py` (Q111 = a) reads `docs/ledger/shipped.csv` in BINARY, resolves the previous `v*` tag, groups the rows and emits Markdown in which every line traces to a row. It REFUSES rather than degrading on: a dirty tree, a clone still shallow after one `--unshallow` (rule 5b), an unswept `PR pending` in a row it would CITE (column-aware, because a whole-file grep matches the ledger row that records the phrase's own removal), an `_ALLOWED_SOCKET_IMPORTERS` shape its AST reader cannot parse, and a missing verification-bar marker. `.github/workflows/release.yml` gains `fetch-depth: 0` on the release checkout, a dev install, and a `python scripts/release_notes.py` call before the fixed install / SHA-256 heredoc — the `v*` trigger, the 0.x pre-release rule, the tag-vs-`pyproject` refusal and the idempotent create/upload/edit path are untouched and pinned by test. 37 guards in `tests/test_release_notes_generator.py`; 21 mutations, 21 killed (two survived the first matrix: one was a finding about the MUTANT, one about a test whose `…` needle was satisfied by the disclosure sentence that quotes it). **Remaining on row V:** the allowlist (operator, Q114 = a with `dumps.wikimedia.org` carved out by `RC10` ⛔), and the per-surface click-through records the notes cite — the generator has none to read and says so rather than listing any. | session |
| 2026-09-15 | **Rows D and E driven END TO END at fixture scale; both stay OPEN on their operator runs.** A 440-article synthetic corpus seeded through the real `index_article`, served on loopback, and both reports read from their endpoints AND out of the one 73-member `/api/diagnostics/all` archive. **Row D:** four of six blocks measured (`window`, `write_gate`, `interrupted`, and `database_stats_latency` once the route is called); `memory_guard` and `wal` report `measured: false` WITH a reason and appear in `unmeasured`. What they need is elapsed time on the operator's machine — the 300 s rate floor and the at-most-hourly `wal_bytes` recorder — and only row B's ≥ 72 h run can make `window.reaches_bar` true. **Row E:** driven in BOTH directions — a clean corpus answers `consistent` over `with_judging_attempt: 14` of 18 sources with the one disqualified source named, and a seeded 2026-07-24-shaped laundering answers `inversions-found` naming `prefcentre.example` with its live status, its last judged verdict and the date, arriving intact in the archive member. So the TOOLING states its own result today; what it needs from row A is the committed IMPORT, which it cannot supply. Neither row's status changes: *built and exercised* is not *read from a run*. | session (fixture-scale drive, Chromium not required — JSON artifacts) |
| 2026-09-15 | **The verification bar (Q1128 = a) now has ONE citable home** — a marked block in row F's section, which `scripts/release_notes.py` READS rather than mirrors, so a reword reaches the release notes with no second edit and a deleted marker is a loud refusal. `_WORKING_MODE.md` §3 already carried the same sentence verbatim and is unchanged; a test pins the two against each other, because a drift between what a BUILDING session is told and what a RELEASE claims is how a surface gets stamped against a bar the release does not make. Row F's status is unchanged: CLOSED as-is. | session |
| 2026-09-16 | **Row H BUILT in two PRs, and the sweep that built it found three defects.** The enumeration is now a fourteen-lane table derived from the tree (PR #1135, docs-only per Q1001's "now"); the consent hover reads the same hosts out of ONE table, `src/static/net-hosts.js`, which `tests/test_security_endpoint_enumeration.py` pins against the document in both directions. **Hosts the section had never named:** `query.wikidata.org`, `www.wikidata.org`, the per-edition `*.wikipedia.org` API, `ores.wikimedia.org`, `dumps.wikimedia.org`, `download.geofabrik.de`, `planet.openstreetmap.org`, 260 law-authority hosts, four markets-feed hosts, fourteen calendar-feed hosts, `huggingface.co`, `pypi.org`, `objects.githubusercontent.com` and the operator-added mirror class. **Three findings, all disclosed and none fixed here:** (1) the section claimed ONE automatic opt-out exception; six ride-alongs run on every online pass. (2) `auto_import_calendars` and `auto_track_law` are read via `getattr(…, True)` against a `SchedulerSettings` that defines neither, so they cannot be switched off. (3) worse — `auto_track_signals` IS a field and IS honoured, but `SchedulerConfigUpdate` does not declare it, so `PUT /api/scheduler/config` answers **200 having changed nothing** (live-reproduced); this document and CLAUDE.md invariant #14 have both named that route as the hazard feeds' opt-out for months. The fix is settings-API and UI work outside `S04-01`'s stated file scope and wants a ruling on its home (row T is the natural one) — recorded in `OPEN_QUEUE.md`. **Also measured:** a URL-literal sweep is blind to `configs/markets_sources.yml`'s 112 scheme-less `domain:` sources, which `crawl.py:149` reaches at `https://<domain>`; counting both halves takes the press class from 5,425 hosts to 9,033. **What remains on this row:** the maintainer's own click-through (Q1128 = a) and their word on the lane grouping names (a design note, binding nobody). | session (Chromium-verified in the sandbox; the operator pass is theirs) |
| 2026-09-16 | **Row U ADVANCED — the FUTURE_DEVELOPMENTS reality check only (Q1141 = a at full depth, A4 = b), and the row stays OPEN.** All 51 sections of `docs/FUTURE_DEVELOPMENTS.md` were re-read against the tree; **14** carried claims that the tree contradicts and now carry a dated `Reality check 2026-09-16` note (the PR body lists all 14). The pass found that **the 2026-09-07 reality check was itself wrong in places** — two of its own banners were false the day they were written (the lunar testing framework it called "designed-only" had shipped 2026-07-03, and the Open-Meteo "signal-keywords" it listed as remaining shipped 2026-07-03/08) — which is the argument for dating a status line rather than editing a claim in place. A4's other two clauses were re-verified as ALREADY SATISFIED, not re-done: the four embedded historical ledgers are archived under `docs/archive/future-developments/` behind a pointer, and the three duplicate pairs are cross-linked and never merged (protocol rule (5)). One number was settled by RUNNING the tool rather than by reading either doc: `scripts/catalog_coverage_report.py` reports 5,546 domains / 4,059 located (73.2%) / Missing (51), not the 73%/49% the section claimed. What row U still owes after this: the i18n remainder (Q1152), the religious-calendar clause (Q1135 and its RC13 conflict), the encrypted click-through variant (Q1149), the newsletter attach (Q1151), `via:*` (Q1130) and the Patterns-lens numbers (Q1124); the `diagnostics.py` split (Q1139) is in its own PR | session |
| 2026-09-16 | **Row L BUILT — OPEN on two surfaces no offline machine can show.** The alpha-3 DISPLAY + BOUNDARY half shipped: one helper per side, 43 surfaces rewired across 11 static modules and the bulletin, `country_iso3` beside `country` in the payloads, and every touched filter widened through `country_query_forms` — which WIDENS rather than normalises, because normalising the needle is the recorded one-sided-normalisation defect and would make `uk` stop matching a column full of `uk`. Storage is untouched and TESTED untouched: the six `String(2)` columns are counted, the OSM `ISO3166-1:alpha2` tag is unrewritten, and `configs/` is hashed before and after a catalogue LOAD. **The click-through earned two findings no source check could reach:** CLDR aliases the withdrawn `AN` to **Curaçao**, so the browser's hover named a different place than the code means while the server's own table had it right — the two halves of one helper disagreeing; and the coverage panel's repaint guard fingerprints the PAYLOAD, so walking en → fr → ar → zh left all 218 hovers reading French (the frozen-locale family `app-boot.js` already documents, newly load-bearing now that the name lives in a hover) — where the FIRST FIX WAS HALF A FIX, because the panel has TWO repaint guards and no handler re-ran its loader, and the re-walk is what said so. A THIRD finding came from the full suite rather than the browser: teaching `normalize_country` the alpha-3 forms made `country_from_title` read a trailing ACRONYM as a country — `(PRI)` is the Permaculture Research Institute AND Puerto Rico, `(ARM)` the Alliance for Regenerative Medicine AND Armenia — so two catalogue sources were filed under a country nobody claimed for them; the opt-out now sits on the one caller that reads prose. **What the row still owes:** Governments → Countries/Map and Markets read World Bank figures and the market importers, both empty on a machine that has never been online, so the walk saw their honest empty states rather than a country; their renderers are covered only by the table in `tests/test_alpha3_display_surfaces.py`, which is a weaker instrument than a real screen and is recorded as weaker | session (Chromium-verified in the sandbox; `docs/audit/alpha3-clickthrough-2026-09-16/`) |
| 2026-09-16 | **Row U ADVANCED — the encrypted click-through variant only (Q1149 = a, L7), and the row stays OPEN; row V gains a bar.** Every UI walk this project has recorded ran the seeded states with `OO_DB_PLAINTEXT=1` for speed, so the app's ENCRYPTED path — the one every real operator uses, and the one that starts behind a lock screen — had never been walked. The runner now takes the passphrase by env (like `OO_UIWALK_IMPORT_PASS`), walks each seeded state in through its REAL `#view-unlock` form rather than being handed an already-open app, and records each state's at-rest reality from the app's own header read. **The defect this would have shipped with, found by running it rather than by reading it: `GET /api/system/doctor` is not in `ALLOWED_WHILE_LOCKED` and answers 503 on exactly the state an encrypted run boots into** — so a doctor-only probe reports `unknown` for every encrypted state and `--require-encrypted` would have refused the very run it exists to demand. The fallback is `/api/system/lock-state`, which IS allowlisted while locked and derives its state from the same header; `via` records which endpoint answered. Measured live: the seeder writes ciphertext (`is_encrypted_file` True), the app boots LOCKED against it, Chromium reaches `/unlock` and the passphrase gets in. `configured` and `detected` stay separate fields, so a passphrase that silently did not take is visible rather than assumed away | session |
| 2026-09-16 | **Row J BUILT — the export half, and the verify pass is the part that changes what an export IS.** Every export now writes its own dated folder (`YYYYMMDDHHMM_OpenOmniscience_Backup`, LOCAL time per Q210 = a, `_2` on collision per Q211 = a), allocated ONCE server-side before either phase so both write into the same place; the allocation is an exclusive `mkdir`, which makes Q213 = c's "no reuse" a PROPERTY of the folder rather than a flag anyone has to remember to pass, and makes "never enter an existing folder" true by construction rather than by check. **Q218 = a is where the cost is:** the job re-reads every volume off the destination and compares its SHA-256, which roughly doubles an export's read time on a slow drive — and the four not-verified verdicts are kept apart (`off` · `stopped` · `unavailable` · `failed`) because a single missing "verified" flattens a CORRUPT backup into one the operator merely chose not to check. The cancelled case is the one that mattered to get right: the manager's stop Event is shared with the cancel path that DELETES a partial set, so a Stop landing during the re-read would have deleted a complete backup; `VolumeStopped` is caught inside the verify helper and the backup stays `done`, pinned by a test that asserts the folder's contents are byte-for-byte what they were. **The panel and `BACKUP_SUMMARY.md` render from ONE `export_facts`**, which is what makes the gate's closes-when clause testable at all — a test reads both and asserts every shared figure equal. **Q1008's lines are emitted only against a MEASURED signal** and carry it (`applies because: table:wiki_pages`), the law rows publish their GAP rather than a guessed licence (`law_documents` has no licence column), and the evidence ZIP measures its OWN contributing sources — a mutation swapping that for the whole corpus survived until the fixture gained a source that contributes nothing to the period. **Two defects found that no source test could see:** the inventory's "LLM models" size counted the Ollama store only while the tick exports the Hugging Face cache too (Q219 is exactly about the size shown BEFORE the export starts); and the Arabic click-through rendered the facts table's NAMES as `مقالة`/`مصادر`, because the string-matching i18n walker cannot tell a table name from chrome — the panel is now `data-i18n-dyn` and re-renders on `oo:langchange`. **Q823 ⛔ is STOPPED AT, and armed:** no ODbL line in any carrier, and an `osm_*` corpus table makes the attribution layer refuse by name rather than render a block that is silently one line short — which means the 0.5 OSM lane will present this as a refused export until Q823 is answered, recorded in `OPEN_QUEUE.md` along with the copied-Geofabrik-extract nuance and the untouched bulletin `_OOS_` names. 24 mutations, 24 killed, after three survived and each was a real defect in a test rather than in the code | session (Chromium-verified in the sandbox; the operator pass is theirs) |
| 2026-09-16 | **Row R ADVANCED — the projection seam, the 50m geometry and the CONTESTED layer shipped; the row stays OPEN on ONE ruled clause.** Equal Earth rides a single `project(lon, lat)` in `app-map.js`, all 18 `lon2x`/`lat2y` sites routed through it and ZERO residual plate-carrée arithmetic left in any static module (guarded by name AND by arithmetic pattern, so a second projection under another name reddens). **The coefficients the sheet carried FROM MEMORY are CONFIRMED**, against two independent published implementations that agree exactly — OSGeo PROJ's `eqearth.cpp` (whose ellipsoidal equations were added by Savric, a co-author) and d3-geo's `equalEarth.js`, both citing DOI 10.1080/13658816.2018.1504949; the sheet's remembered form is algebraically identical, and `EE_Y_MAX` is DERIVED from the polynomial and reproduces PROJ's own `MAX_Y` to 1.3e-14. Measured, not asserted: equal-area holds to **0.0015 %** across latitude, the plate carrée it replaced inflated 70 °N by **3.00×**, and the Newton inverse round-trips to **2.0e-13°**. 50m geometry rebuilt IN-SANDBOX — the build script fetches the project's own git mirror, not the blocked CDN, so this was never operator-gated: 175 → **229** countries, 285 → 540 rings, 139,600 → 913,824 bytes (**+756 KB, more than the ruling label's "a few hundred"** — reported, not reconciled), the registry's BLANK sha256 pin filled, the count floor raised 150 → 200. Contested borders read their claims OUT of Natural Earth's per-point-of-view fields (28 areas, 34 worldviews, names ×12 from the source's own `NAME_<lang>`), every claim named in every view, the default assigning nothing. **WHAT KEEPS THE ROW OPEN:** Q803's ruled default — "OSM's convention as of `<date>`" — needs the OSM-derived admin artifacts that are 0.5 / `S05-05`, and Natural Earth's own de-facto policy is NOT OSM's, so calling it that would be the fabrication the same ruling forbids; the default is `contested` (assigns nothing) and the `<date>` + the source are the two things §6 reserves for the maintainer. Also open: the maintainer's own click-through (Q1128 = a) — the sandbox run drove the surfaces on a synthetic corpus, where two of the five draw their honest empty state because only a networked collect produces country-indicator data. **Corrected in the same PR:** the brief's call-site paragraph named nine files when all 18 sites are in `app-map.js` alone — the count was reproducible and the breakdown beside it was not, which is why it read as verified | session (Chromium-verified in the sandbox; the operator pass is theirs) |
| 2026-09-16 | **Row U ADVANCED — the newsletter attach only (Q1151 = a), and the row stays OPEN.** The 2026-06-15 ruling's clause (d) refused to let the silent auto-attach ship alone, so all three halves land together: the write-path attach on the ruled ladder, the import UI that announces where each newsletter went, and an undo for the automated placements — on one additive column, `Article.newsletter_attached_via`, which records the LADDER'S OWN VERDICT rather than the destination id (`Article.source_id` already is the destination; what no reader could otherwise recover is whether the APP chose it or a person did). **The finding that made this a data-safety slice rather than a feature: moving an article between sources silently broke four readers that all defined "an imported newsletter" by asking about its SOURCE, and two of them are privacy gates.** A newsletter filed under `bbc.com` would have been written into a backup the operator had excluded newsletters from, and its body exported into the source-quality diagnostic zip that withholds private `.eml` text by default; the other two would have made "Remove imported newsletters" leave some behind while promising it removed every one, and made the publisher preview report an ever-shrinking corpus as the attach succeeded. All four widened, the backup one column-tolerantly so an older snapshot still backs up. The undo deletes a source it created only when the RECORDED rung says `new-email-source` and the source is empty AFTER the restore — a flag heuristic ("disabled + newsletter-typed + empty") is a shape a user's own source can have, and would have deleted theirs. Chromium-verified in `en` and `ar`: the real import, the announcement, the RTL render at 375px with no horizontal overflow, and the undo clicked for real, zero page errors. What row U still owes after this: the i18n remainder (Q1152), the religious-calendar clause (Q1135 and its RC13 conflict), `via:*` (Q1130) and the Patterns-lens numbers (Q1124); the `diagnostics.py` split (Q1139), the FUTURE_DEVELOPMENTS reality check (Q1141) and the encrypted click-through variant (Q1149) are their own PRs | session |
| 2026-09-16 | **Row T BUILT, five of six, and the sixth was already shipped.** Q1012 = a: ONE rate authority — `src/scheduler/process_budget.py` derives the ceiling from the governor's own `mode`/`target_kbps` (there is nowhere else to put one) and widens the governor's INPUT from the collector's share to the whole process, so a wiki-dump or OSM download pulling megabytes a second is no longer invisible to the control holding the app to "target 500"; per-job caps stay omitted. Q1013 = a: a per-host next-allowed-at persisted beside `robots_cache.json`, a **180 s** inline-wait cap (chosen, not derived — the 2026-09-10 candidate-kit run measured per-row p50 16 s / p95 35 s / p99 138 s, so it clips only the tail a long `Crawl-delay` explains), and `CrawlDelayDeferred` counted in its own `IngestResult` bucket rather than as a failure of the source. Q1148 = a with **RC15 still blank**, so L4's «most ethical» is read as this loopback guard — an ASSUMPTION, reversible by writing a letter. Q1125 = a and Q1126 ⛔ = a shipped as ruled. **Q1132 = a needed nothing**: `src/llm/weights_pin.py` + the refusing pull landed 2026-09-07 (PR #1016's commit `16ff34f8`), an ancestor of the brief's own anchor — recorded VERIFIED-PRESENT, not rebuilt. **What this row still needs:** the maintainer's own click-through, and the digest VALUES, which are an operator input by design. | session (Chromium-verified in the sandbox; the operator pass is theirs) |
| 2026-09-16 | **Row I BUILT; two things the row itself could not have predicted.** (1) **Q217's gate is met and the prefetch is still parked, which is a departure from the ruling's letter and is named rather than absorbed:** the first real `verify_copy` read shows prepare dominating, so «build it» is the literal reading — but 73% of that prepare is `stage_a:reassemble`, not the `prepare_staged:validate`/`:upgrade` pair Q217 points at (17%), and building the seam means a `start_restore(..., staged=)` boundary and a plaintext staging tree crossing thread ownership, which is the «change the merge algorithm beyond wiring» the slice was told not to do. Every figure is sub-second on a 1.6 MB fixture against a 650 MB field import where prepare was 46.7 and 56.0 MINUTES per item. (2) **A P0-shaped false claim was found in code this slice only reported on:** a post-merge verification refusal returns NORMALLY, so three layers each asking «did the job finish» turned it into `state: "done"` — in a K-group the corrupt backup read `done` while the two good ones read `discarded`. Fixed in both summary shapes. The new stage rows depended on those item states, which is how it surfaced | session (S04-02) |
| 2026-09-16 | **Row K BUILT — one bump, five payloads, and row K is the 0.5 storage half's precondition (Q301 = c), so what it hands over is stated rather than implied.** `oo-backup-2` → `oo-backup-3`, with BOTH in `ACCEPTED_BACKUP_SCHEMAS` — a set a future bump may only ADD to, which turns Q215 = a from a docstring promise into a structural one; the volume container was deliberately left alone, because bumping it would tell an older build it cannot read a set it reads perfectly. **The handover to `S05-02` is an ORDERING, measured rather than assumed:** the normaliser rewrites the STAGED copy and never the live corpus, so flipping `CANONICAL_COUNTRY_FORM` while the live corpus is still on the other form makes every value-keyed join miss — reproduced under simulation as one law document coming out of a restore as TWO rows while the report said "2 rows converted". No automatic verdict is available (a real corpus legitimately holds values the converter refuses and can be honestly mixed), so every restore now measures `live_corpus_in_target_form` (0 today) and a test is the tripwire: **the live rewrite lands BEFORE the flip.** **A design note was declined with a reason:** the row asks a restored shipped ring to carry a version so the newer wins; precedence by SOURCE (the loader reads local first, shipped last) gives the same guarantee by construction, with no version, no comparison rule and no tie-break, and fails closed where a comparison fails open. **Two adversarial passes found four defects the build's own tests did not, each hand-verified before being acted on:** a normaliser collision rolled back the whole `UPDATE`, stranding unrelated rows of that spelling as duplicate documents; `stat_subscriptions.country` is exempt from the rewrite (Q311) yet reaches a value-keyed join from a free-text box, so two installs typing "FR" and "fr" duplicated a subscription (the comparison now folds case, the stored value still never rewritten); the migration crashed `alembic upgrade head` over a table `create_all` had already made, which is fatal on the restore path because it never calls `create_all`; and SQLite's UNIQUE treats NULL as distinct, so the ruled five-column identity enforced nothing when the provenance was unset. **The Chromium walk found a fifth that no source test could see:** `app.css`'s global `input { width:100% }` stretched both new checkboxes to ~340–360 px, stranding each label at the far end of its row. **Still OPEN on the operator's clauses** — a real pre-migration backup restored on the maintainer's machine with the scan's output as the artifact, and the P0 trio re-run on the new format; both `not-measurable-here` | session (Chromium-verified in the sandbox; the operator pass is theirs) |
| 2026-09-17 | **Row M PARTIAL — the ladder ships, the consented ring job does not, and two of the brief's own premises were wrong.** The ladder is ONE function (`resolve_translation`) so the label grammar is not re-derived on each keyword surface, with four values of which `same_language` is deliberately *not* a rung. **Q412's refusal was measured before it shipped:** 91 of 21,834 (language, term) pairs collide — the *same 91* `expand_term` already refuses, which is the corroboration that this extends the ruled path rather than adding a second beside it — giving 246 refusals in 78,371 resolutions (0.31%) against 96.4% verified. A narrower refuse-only-on-disagreement rule was built, **measured at zero pairs**, and rejected as wrong on Q412's own `wahl` example. **Lemmatisation at extraction may only ever MERGE**, and that guard is load-bearing rather than defensive: this tree's English stopset contains `car`, so the unguarded version files four occurrences of `cars` under the stoplisted key `car` where every stoplist-aware surface then hides it — it RENAMES rather than drops, which is worse than deletion would be honest about. **Two premise corrections:** the 12 × 12 language names the sheet said were already in the locale files are NOT there (`fr.json` carried exactly one), so Q402 ships as one keyed frame plus CLDR; and `render_as_batch=True` already absorbs a duplicate `add_column`, so the migration's `_has_column` guard is not what makes the restore path work and its docstring was corrected after the measurement refuted it. **Q406 ⛔ = b is answered and unbuilt** — its seams exist and `www.wikidata.org` is already on `S04-01`'s host list, so no host is new and nothing in this PR reaches the network | session (`S04-06`, PR #1148) |
| 2026-09-17 | **Row N ADVANCED — the backend spine (PR #1149)**, and the row stays OPEN. `resolve_concept(term, ui_lang, sense)` is computed once and passed to BOTH the FTS path and the keyword-keyed aggregates (Q501), so the Articles list and the analysis tabs read one object rather than two resolutions that happened to agree. The agreement bar is DEMONSTRATED at fixture scale — seven articles through the real `index_article`, and the Articles list, Trend, Keywords, Context and Associations all answer **6** with expansion on and **2** with the literal toggle, in both `en`/`climate` and `fr`/`climat` (`docs/audit/cross-language-agreement-2026-09-17/`). Q515's own function was the defect: `search_total` declared an `expand` hook and called `build_match(query)` without it, so an expanded search's exact total described the LITERAL query — live-reproduced at **7 ids against a total of 3**. Q503's cap is measured rather than assumed (140 of 698 rings carry more than 40 forms) and bounds the fan-out only: `total_forms` is exact on both sides. Q514 is pinned as a PROPERTY — the resolution runs with a tripwire in place of `KeywordTranslation` and never touches it. What row N still owes: the reader-facing half (Q502's stacked series, Q504's URL state, Q508's group-by, Q509's per-language chip, Q512's mind map), S7 (watches, the bulletin annexe), S8 (the CJK segmenters, Arabic folding and the re-index with its before/after counts), the real-corpus comparison and Q515's cost at the ring-size extremes, and the Chromium + maintainer click-through — this PR changed no control on screen, so it reaches neither half of the Q1128 bar | session |
| 2026-09-18 | **Row Q ADVANCED — the three L0 defects and ruling L6 (PR #1157)**, and the row stays OPEN at the Q925 ⛔ seam. Q917's three, each REPRODUCED before it was fixed and each failing toward a plausible answer rather than an error: the reader rendered the FIRST snapshot ever taken under the document's own title (a much-amended Act shown as its superseded self, while `latest_text` was read by nothing) — it now shows `latest_text` with a version selector, and a `?version=` on a revision with no stored text refuses BY NAME rather than showing another version's words under the right version's date; every change was measured against the immutable baseline, so a document growing a little per amendment reported a CUMULATIVE figure on a row reading as one amendment (and `flag_revision`, which judges that number, fired forever once a document had drifted) — the anchor is the previous revision now, the baseline diff survives as a derived view that refuses by name, and every row records WHICH anchor produced it in a vocabulary where each value means exactly one thing; and the adapter's three dates were parsed and dropped, so `enacted_on` (document-level) and `valid_on` (version-level) are persisted while `retrieved_on` gets NO column, because it IS the revision's `observed_at` and a second field would be two records of one event. L6: `pypdf` joins the default install, the extra kept as an alias, both venv profiles re-verified, and the coverage report's "without [pdf]" framing retired — it told an operator to turn on a knob that is now on by default. THE BROWSER FOUND WHAT NO PYTHON GATE COULD: the law reader loaded no i18n at all, so every word was English by construction; adding it made seven unkeyed strings visible, two of which needed more than a key (a bare `Text` label cannot safely be a key at all, and one phrase shared its text node with a timestamp, so nothing could ever have matched it). ALSO REPAIRED, not ours: the 2026-09-17 row-N entry had been appended BELOW §4, where it rendered as a stray table row outside this log; moved back, text unchanged. WHAT THE ROW STILL WAITS ON: S2 (the metadata model), S3 (the adapter framework + CLML, **stopping at Q925 ⛔ — the adapter ORDER and the first managed dataset are PENDING and nothing about them is decided here**), the vetting-board tooling, and the live checks against `www.legislation.gov.uk` / `eur-lex.europa.eu` / `gesetze-im-internet.de`, which are `not-measurable-here` (the sandbox's egress proxy answers 403 to CONNECT on each) and are the operator's step | session |
| 2026-09-18 | **Row P ADVANCED — S4, S5 and the runner wiring.** The gap this row named as the slice's largest is closed: the lane COLLECTS, from the one online seam and never from the boot path. **Q707's budget is a STORAGE cap, not a second rate authority** — the ruling's word is "daily" and the naive reading builds a bytes-per-day allowance, which is exactly what Q1012 forbids beside the collection-speed governor; so the cap is on bytes held, the rate stays the governor's, and the wizard says so rather than leaving it to be inferred. **Q711 needed NO COLUMN and that is a finding**: the standing ruling makes the anchor `Article.source_revision`, so the obvious reading — a schema change — would have undone a decision recorded only in the open queue. **Analytic 2 ships under a different name than Q712 gives it**, because the lane stores no editor and "contested" would be a claim about people from data about bytes; it is edit CONCENTRATION plus size REVERSALS, with the gap stated on the block. **Four defects reproduced before they were fixed**, among them a page renamed mid-batch that the tier stopped following with nothing saying why, and a lane file from S04-08's build that this build could not read at all (`create_all` creates missing TABLES and never a missing COLUMN — the reconciliation plans first and applies second, since one applying as it went leaves a file that is neither shape). **The row stays OPEN on its operator half**: the ≥ 72 h run is now STARTABLE and is listed with the counters the diagnostics member must show, Q717's endpoint verification needs a networked machine (`000` from this sandbox), and the maintainer's own click-through is still owed | session (`S04-09`, PR #1156, after #1155's S1-S3 merged) |
| 2026-09-18 | **Row Q ADVANCED again — S2, S3 and S4 (PR #1157)**, and the row stays OPEN at the Q925 ⛔ seam, which is now a MEASURED list rather than a sentence. **S2:** `law.db` holds only what the legacy schema cannot express, in TWO tables — a single row per tracked document would store every fact about the LAW once per LANGUAGE VERSION, so an EU act in 24 languages could have its French row saying `amended` while its German row still said `in-force` because only one adapter re-ran, which is the disagreement Q908's one identity exists to prevent. The cross-file links are MINTED STRINGS, a deliberate departure from the substrate's integer pattern: the fact at the end of this one is a licence and a translation provenance, and `merge.py` renumbers `law_documents`. The model refuses to guess the two things a reader would act on — `translation_kind` defaults to `unrecorded`, never to `original`. **S3:** one adapter is registered, and that IS the point; a test registers a SECOND one and drives it through the whole pipeline with no production change, which is how "a second adapter fits" stops being prose. `docs/product/LAW_ADAPTER_SEAM.md` lists **117 verified sources that could start**, grouped by Q909's three classes, quoting each declared channel verbatim — and ranking nothing, which a test enforces on the rows. Q919's `law` Source type, Q921's `counts_documents` (a literal `true`, because a truthy string is not a declaration), Q924's `verified` tier (NOT `verification.status` — that asks whether a researcher confirmed the portal, this asks whether an adapter in this tree has read it) and Q910's EU paths, with the EU-Login dump named as EXCLUDED rather than merely absent. **S4:** analytics 1–2, whose caveat is load-bearing: "amendment velocity" reads like a property of a legislature and is a property of what this install polls, so the payload gives the denominator and REFUSES to divide by it. Two mutation matrices, 15 and 15, every mutant killed by name; a two-language Chromium click-through in en/fr/de/ar; full suite 11,679 green. **WHAT THE ROW STILL WAITS ON:** Q925 ⛔ itself, the 44-row vetting board (operator), and the live checks — the sandbox's egress proxy answers 403 to CONNECT on all three priority hosts | session |
| 2026-09-18 | **Row S ADVANCED — S1 only: Q1101 = a's flip, its audit trail and the hatch's retirement.** `evaluate_and_stamp` now sets `enabled=True` on a `qualified` verdict and on nothing else, and `scrape_unqualified` is gone from the settings, the runner and the UI — so the gate is an unconditional `enabled AND qualified` that no setting can widen, and the widening happens where the verdict is reached, under a record, instead of in a query where nothing observed it. **THE AUDIT'S UNIT IS COLLECTABILITY, AND THE FIRST CUT HAD IT WRONG:** it recorded a row only when `enabled` itself moved, which an adversarial pass live-reproduced as a hole big enough to swallow the ordinary case — the shipped catalogue seeds sources `enabled: true, status: unqualified`, so the first qualification of a catalogue source goes from EXCLUDED to ACTIVELY SCRAPED without `enabled` changing, and every re-admission on the disqualification ladder does the same. `enabled` moving was a PROXY; the fact is whether collection can reach the source, and both now read it through one `is_collectable()` the gate and the audit share. Two more confirmed the same way: the undo had no ORDERING guard (undoing an older admission under a newer one wrote a prior state two decisions stale while the newer row still rendered as reversible), and the panel claimed a coverage its table cannot support — the curated stamp, the inherited overlay stamp and the restore-merge also make a source collecting, so the DIFFERENCE is published rather than described. A caller still sending the retired key is REFUSED BY NAME, which is why the field stays declared on the request model: dropping it would make Pydantic answer 200 having changed nothing. **WHAT THE BROWSER CAUGHT THAT NO GATE COULD:** the prior status rendered as the raw English token inside an otherwise fully-translated Arabic line — a value inside a composed text node the DOM walker cannot match, and a key that is never requested is not a key that is missing. **WHAT THE ROW STILL WAITS ON:** S2 (the headline counts everywhere, the overlay editor, B5's diagnostics action), S3 (the small rulings, the RC05/RC06 assumptions), S4 (the institutions moves, the growth strategy, the splice report) — and Q1113 ⛔, untouched: the flagged embassy platforms stay excluded by the existing flag, nothing is published and nobody is contacted | session (`S04-12`, S1) |
| 2026-09-18 | **Row S, S2 SHIPPED — the editor, the merge action, and the admission route building them uncovered.** Q1106 = a's adopt / export / revert now live in Settings → Quality gates over the shipped overlay; B5's export + merge runs as `POST /api/diagnostics/source-qualification-merge` instead of a shell; Q1114 = a's other predicates are labelled wherever they appear. **The finding, live-reproduced before it was fixed:** `apply_overlay` was a SECOND ADMISSION ROUTE and nothing recorded it — the catalogue ships its rows `enabled: true` awaiting a verdict, so adopting a shipped `qualified` verdict took one from unreachable to actively scraped (`select_sources` going from `[]` to `[the domain]`) while the admission audit stayed empty and the undo had nothing to act on. That is the same defect S1 closed in `evaluate_and_stamp`, alive in a path that fix never touched, and a "revert" built over it would have had nothing to revert. Both paths now go through one `record_admission()`, which checks BOTH ends against `is_collectable`; the overlay's rows read `verdict=inherited`, so the audit says which KIND of evidence let a source in. **Revert had to persist a preference** (`AppSettings.adopt_shipped_verdicts`): adoption looks for rows reading `unqualified`, which is exactly the state a revert restores, so without it the next boot re-adopted and the operator's decision lasted until they closed the app. Two refusals rather than guesses — a row judged here since, and a row the overlay stamped over the catalogue's own stamp — are counted and left alone. **The Chromium walk earned two findings no source check could reach:** `GET /api/sources/overlay` answered **422 "Input should be a valid integer"**, because FastAPI matches in REGISTRATION order and `GET /{source_id}` sits earlier on the same router — 17 tests were green because every one of them called `overlay_status(db)` as a function, and a handler exercised as a function is not a tested ROUTE; and the panel's own headline label rendered half-English in eleven locales (`Judged so far` / `not yet judged` sat inside the untranslatable ratchet's existing allowance, so no gate could object). Both fixed, both now pinned; both i18n ratchets LOWERED, 466→464 and 229→227. **RC05 / RC06 are untouched by this slice** (they belong to S3) and **Q1113 ⛔ is untouched**: the flagged embassy platforms stay excluded by the existing flag, nothing is published, nobody is contacted — today's state, not a decision. Verification: full suite 11,999 passed before the two fixes (both failures were mine and are fixed); **24/24 mutants killed, 0 survived, 0 void**, restore verified; ruff blocking clean, advisory ratchet unchanged at 442; mypy 0 errors over 581 files; 45 strings ×12; the walk clean in en / fr / ar with zero `pageerror`s. | `src/catalog/qualification_overlay.py`, `src/catalog/qualification_merge.py`, `src/api/diagnostics/qualification_merge.py`, `tests/test_overlay_editor.py`, `tests/test_qualification_merge_action.py`, `tests/test_headline_source_count.py` |
| 2026-09-18 | **Row S, S3 SHIPPED — six rulings built, one deliberately not.** **Q1107 = a + B6:** `PATHOLOGY_ABS_FLOOR` stays at 0.5 and is now RECORDED unreachable with the measurement it rests on (2026-08-02: 63 failing sources, every one flagged by its cohort at a rate below 0.0025, the highest observed 0.0023 — nothing reached 0.5), and `link_density_rate` joins it as the second MEASURED extraction-failure criterion, reading the same shipped threshold the pre-label and the sampler read. **Adding a second one was only safe once each declared its OWN evidence count and its OWN floor:** the old code read `pathology_articles` and `PATHOLOGY_ABS_FLOOR` by name, so a second criterion would have been gated on evidence it does not have — a source with 400 link-dense articles and no pathology going silently un-flagged, in the one place the app can pull a source out of collection. `link_density_rate` declares NO absolute floor, statedly: none has been measured, and copying pathology's number across would be a fabricated threshold wearing a measured criterion's clothes. `CRITERIA_VERSION` → `-3`. **Q1108 under RC06's shape:** a 90-day verdict published BESIDE the whole-history one, each with its own n and its own cohort — demonstrated rather than argued, since a source that broke recently reads `whole=healthy` / `window=degraded`, i.e. the single verdict calls a currently-broken source healthy. Both answers stand; the conflict is recorded and the payload names it. **Q1110:** the `primary_source` axis rewritten as a checkable observable, as a PROPOSAL SURFACE with no apply — and the multilingual work found two failures of exactly the kind the ruling exists to prevent: `_fold` strips combining marks, so a Bengali gazette notification went unmatched against its own lexicon entry (the Latin entries were unaffected, which is why it would have shipped), and a Japanese notice dated 令和6年 read as undated against a Gregorian-only date test. 18 headlines across 12 writing systems are pinned, and six languages of ordinary journalism are pinned as never matching. **Q1115:** a country-vs-domain audit that proposes and declines `.uk`/`gb`, `.eu`, repurposed ccTLDs and gTLDs BY NAME, because the docket says a naive ccTLD check is not the audit. **Q1116:** bare Q-id names resolved at R8's ≤1 req/10 s (imported, never restated), one consent per batch, the kill switch refused BY NAME before any request AND re-checked between rows, and an unresolved row DECLINED rather than admitted under its identifier. **Q1156:** VERIFIED-PRESENT over thirty passes, with a positive control that builds the rejected round-robin — and the control immediately exposed an ID collision that had two fixtures measuring the wrong sources. **Q1105 / RC05 is NOT built, deliberately:** the 64,910 `kind_overrides` proposals stay a design-doc measurement and the slice is smaller by exactly that. Verification: 1,521 tests green in the affected area; blocking ruff clean; the advisory ruff ratchet DROPPED 442 → 440 across the slice; mypy 0 errors over 584 files; all three i18n gates green. | `src/analytics/source_audit.py`, `src/catalog/official_instruments.py`, `src/catalog/country_domain_audit.py`, `src/catalog/qid_labels.py`, `tests/test_link_density_criterion.py`, `tests/test_recency_windowed_verdict.py`, `tests/test_official_instruments_observable.py`, `tests/test_country_domain_audit.py`, `tests/test_qid_label_resolution.py` |
| 2026-09-18 | **Row S, S4 SHIPPED — the moves, the strategy, and THE SPLICE REPORT.** **Q1109 = b + Q1111 = a:** the 16 rows tagged `research-institute` left `official_sources.yml` for `academic_sources.yml` (43 → 27 and 606 → 622), moved BY TEXT rather than by re-serialising a 606-row curated file, with every moved row verified byte-identical after a parse. The seed guard then caught what the move alone would have hidden: they arrive carrying `source_type: academic-research` on rows named *Chilean Journal of Agricultural Research*, *Lebanese Science Journal* and *Helminthologia* — a type the docket itself calls wrong. Q1111 said *move*, not *retype*, so the inconsistency is RECORDED in the growth strategy rather than corrected under cover of a move. **Q1109's note** is answered by `docs/product/ACADEMIC_CATALOGUE_GROWTH.md`, which decides nothing: coverage axes before row counts, regional platforms (SciELO, AJOL, J-STAGE, CyberLeninka…) as PEERS of DOAJ rather than a follow-up — doing DOAJ first is how the skew gets baked in — and the costs of a bigger list stated before it is proposed. **THE SPLICE REPORT** is built by `scripts/analysis/stage_b_splice_report.py` from committed files only and writes nothing: 807 admitted, 1,283 deferred, 7 blocked, 62 declined, 57 routed. It reproduces the two-judge run's own figures EXACTLY from the raw result files — `kind` 97.1 %, `primary_source` 84.6 % — and publishes three agreement statistics with three denominators so the stricter combined figure (83.6 %) cannot be read against them as a discrepancy. **The defect the balance-shift table exposed, before anyone else could:** a first cut read "admit where both judges agree" literally and admitted the 623 rows both judges agree are institutions and agree are NOT primary sources — asserting into a list OF primary sources the exact opposite of what both judges said, and reporting 1,471 admissions against the 807 actually earned. The tell was a `??` country bucket of 719 rows as the largest mover. Rejecting them would have been equally wrong, since Q1110 = a defers that axis; they are deferred under a reason that names the ruling, and **there is no `reject` verdict in the module, structurally**. **Q1112 = b:** a `restricted_namespace` trip blocks BEFORE the agreement test — the judges read the claimed identity, which is the thing the flag says is contradicted — and only a written override lifts it; 7 blocked of 10 flagged, with the difference published so the count cannot read as every flagged domain. **Q1117 = a:** admitted and tagged `cms:uredni-deska-atom` by PATH (36 rows), `cz` +1.21 pp the largest mover. **Q1118 = a is LISTED, NOT RUN** — operator-gated, `not-measurable-here`. **Q1113 ⛔ is untouched: the flagged platforms stay excluded by the existing flag, nothing was published and nobody was contacted.** Verification: 22 new splice tests; blocking ruff clean; advisory ratchet unchanged at 440; mypy 0 errors over 585 files. | `src/catalog/stage_b_splice.py`, `scripts/analysis/stage_b_splice_report.py`, `configs/official_sources.yml`, `configs/academic_sources.yml`, `docs/product/ACADEMIC_CATALOGUE_GROWTH.md`, `docs/research/.../SPLICE_REPORT.md`, `tests/test_stage_b_splice.py` |

---

## 4. Not in this gate

Kept explicit so nothing drifts in by assumption:

- **The `v0.3.0` tag.** It is the `0.3` gate's §7.3, and this board does not gate it. *(2026-09-27: `RC01` = a
  takes the existing 2026-08-23 pre-release as that tag.)*
- **The version flip to `0.4.0`.** It follows the `v0.3.0` tag, mechanically. *(2026-09-27: the maintainer does
  it, after the current draft PRs merge; row G records it. 2026-09-28: it came after the `v0.4.0` tag, in
  PR #1195, at the maintainer's pick, and the tag moved onto it; the release published from it.)*
- **The 5M-article framing.** Withdrawn 2026-07-30 and not reinstated here; it returns as a
  later-cycle target once the throughput work makes it reachable.
- **Everything the answers put in `0.5` or later** (see `RELEASE_0.5_GATE.md` … `RELEASE_0.9_GATE.md`):
  the advanced search (R11), the storage half of alpha-3 (Q301 = c step 2, Q304, Q305), the entity spine
  and the Place entity, the OSM lane seed and its admin artifacts, the Wikipedia WARM tier and the tail
  walk (Q701 = c), the law evolution surface, the feed-key source identity migration (Q1102, *proposed
  placement* 0.5), the inline-handler retirement + CSP and the theme cull (Q1127, Q1123), the AI
  translation sweep (Q405, Q513).
- ~~**The four ⛔ questions left blank** — Q823 (ODbL), Q925 (adapter order), Q1009 (storage round-2 rows
  3–6), Q1113 (the embassy platforms) — are not decided here and not defaulted anywhere.~~ All four answered
  2026-09-29 (a, a, a, a), recorded in `RULINGS_INDEX.md` and §3.
- **The stoplist merge** (Q1103 = b vs Q1104 = a, a CONFLICT recorded 2026-09-15) — RESOLVED 2026-09-30
  (R98, amended by R111): reviewed batches curated by us and shipped with each app update, no Settings screen; row M closes with the first such batch (after R111 steps T2 and T3).
- **Row 5's Tier B** (the 451 index pages above the word guard). Not proposed for `0.3` and not
  proposed here: their prose is unmeasured. The `0.3` PR made that measurable
  (`criteria-calibration.json`'s prose arm now advances and can be pointed at that population),
  so a `0.4` decision on Tier B would at least have evidence — but it is a decision, and nobody
  has made it.
