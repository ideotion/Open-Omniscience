# Settings restructure — session brief (2026-07-31)

**Status:** PLANNING COMPLETE, nothing built. Maintainer reviewed every Settings subtab on
2026-07-31 and gave remarks per subtab; 23 follow-up questions were put and answered the same
day. This document is the plan of record and the operating manual for the coding sessions that
execute it.

**Working mode:** a STACK of draft PRs onto `main`, merged progressively (maintainer ruling 16).
Branch prefix `claude/settings-*`. After each merge, REBASE the remainder of the stack on the
fresh `origin/main` tip — `docs/ledger/shipped.csv` is append-at-EOF so every PR after the first
would otherwise conflict on the last line (ruling 16b: each PR appends its own row, rebase after
each merge). All frontend work here is BROWSER-UNVERIFIED in the executing environment
(fork-3/Q6a): ship conservative + node --check + invariant-guarded + flagged, and a human
click-through is owed on every slice.

---

## 0. Verified state (measured against `main` @ b5bc6b6, 2026-07-31)

Findings that CHANGED the plan. Each was read from the tree, not inferred.

| # | Finding | Anchor |
|---|---|---|
| V1 | **The text-size slider cannot work.** `applyUi` sets `documentElement.style.fontSize = N%`, which is correct — but `app.css` holds **103 `font-size` declarations in `px` and zero in `rem`**, `body{font-size:15px}`, plus 46 more inline `px` in `index.html`. The root scale reaches nothing. | `app.js:1648`, `app.css:87-89` |
| V2 | **There are 39 card producers, not 3.** 35 `_DEFAULT_PRODUCERS` + 4 `RECIPE_PRODUCERS`. The Settings UI exposes 3 toggles; `source_candidates_waiting` is registered with no toggle. Only the 4 recipe producers consult a disable flag (`recipes_disabled`); the other 35 have **no per-producer persistence of any kind** and their thresholds are module constants / inline literals inside each function. | `producers.py:2923`, `recipes.py:377`, `recipes.py:_disabled` |
| V3 | **Calendar auto-import already rides every online collect pass, default-on** — 8 feeds/pass, round-robin by least-recently-imported, 12 h per-feed gate, robots-dead hosts skipped. The maintainer's "all calendars should be automatically scraped" is ALREADY TRUE; the automation is simply invisible. | `events/feeds.py:473`, `scheduler/runner.py:1087` |
| V4 | **Agenda contrast root cause is `opacity`, not the theme.** `.ag-cal` is `color:var(--muted)` **and** `opacity:.6` — a low-contrast token multiplied by 0.6, which is why it stays bad in light AND dark. | `app.css:577-578` |
| V5 | **The `statistics` tag is already auto-implied.** `CLASS_IMPLIED_TAGS[STATISTICS] = ("statistics",)` via `ensure_channel_tags`. That half of the Statistics ask is done. | `catalog/provenance.py:54-62` |
| V6 | **Statistics agencies carry no feed and no news URL.** `StatAgency` has `home_url` only; registration forces `enabled=False`, `source_type="statistics"`. `crawl_source` starts at `https://{source.domain}`, so enabling them crawls dataset portals, not articles. | `stats/agencies.py:32-40`, `stats/ingest.py:73-84`, `ingest/crawl.py:146` |
| V7 | **Crawl-by-default shipped** (`crawl_supplement=True`, `crawl_per_pass=3`), so "enabled" for a feedless source is NOT cosmetic — it becomes crawl-eligible. | `scheduler/settings.py:143-144` |
| V8 | **Legacy restore is already absorbed** by the unified Import, which discovers a legacy single-file backup in a scanned folder and restores it through the same path. The module comment states "there is exactly one legacy-restore code path in the app." | `api/backup_v2.py:276-307` |
| V9 | **`#ux-export` lives INSIDE `#set-data`**, and set-views are `display:none`. A `<dialog>` inside a `display:none` ancestor does not render even via `showModal()` — so opening the backup popup from Safety requires moving that markup to top level. | `index.html:1674`, `index.html:1591` |
| V10 | **"Typeface" IS currently keyed.** Renaming to "Fonts" regresses its translation unless "Fonts" is added ×12. Genuinely missing keys: the three Keywords `<h2>` headings and `Import documents (PDF)`. "OpenStreetMap" needs no key (proper noun; English fallback is correct in every locale). | `locales/en.json` |
| V11 | **DB-10 §1b is already wired** — `_FRESH_PAGE_SIZE = 16384` is applied on fresh-file creation. The page-size bench has already done its job. | `database/connect.py:83, 332-336` |
| V12 | **`uninstallBackupFirst()` and `encryptedBackup()` use the SAME 2 GiB-capped endpoint** `/api/safety/backup/encrypted`. The "remove Encrypted backup" and "rewire Download a backup first" asks are one fix. | `app.js:7100, 7210` |
| V13 | **The source re-qualification ladder exists and is the pattern to mirror** for calendar feeds: `backoff_months` 1→2→4→6 capped, append-only `SourceQualificationAttempt`, bounded `select_due_disqualified` per pass. | `catalog/qualification.py:93-135, 227` |

### Test guards that break (the stale-anchor hazard)

Panel ids are used as **source-slicing delimiters**, so moving a panel breaks tests that are not
about that panel.

| Test | Breaks because |
|---|---|
| `tests/test_leads_subtab.py` (whole file) | Leads subtab removed |
| `tests/test_repo_invariants.py:4636` | uses `id="set-leads"` as the END delimiter of the **Keywords** view slice |
| `tests/test_repo_invariants.py:3015` | slices between `id="set-wikipedia"` and `id="set-agenda"` |
| `tests/test_ui_keybindings.py:26` | asserts `id="set-shortcuts"` exists |
| `tests/test_repo_invariants.py:2932` | asserts `id="set-collect"` + `<button data-tab="collect">` |
| `tests/test_repo_invariants.py:3169` | asserts `id="set-newsletters"` |
| `tests/test_repo_invariants.py:2560, 2582` | assert `id="set-stats"` |
| `tests/test_repo_invariants.py:2522` | asserts `data-tab="offlinemap"` (rename) |
| `tests/test_repo_invariants.py:6452-6461` | pins `<label class="sl" for="dr-font">` — an **accessibility fix** guarding the slider being removed |
| `tests/test_repo_invariants.py:1961` | pins `id="dr-faces"` (the Typeface picker — KEEP, only its label changes) |
| `tests/test_pagesize_bench.py`, `tests/test_poll_transparency.py`, `tests/test_beta_poll_transparency.py` | whole files, modules removed |

> **Do NOT touch** `tests/test_sqlcipher.py` / `tests/sqlcipher_helper.py` when removing the
> page-size bench — they exercise the `cipher_page_size` PRAGMA, not the bench.

---

## 1. Target structure

**15 subtabs → 10.**

`Graphics` · `General` · **`Cards`** (new) · `AI` · `Wikipedia` (untouched) · `OpenStreetMap`
(renamed) · `Agenda` · `Data & backup` · `Safety` · **`Advanced`** (new)

Removed: `Shortcuts`, `Leads`, `Collect`, `Sources`, `Newsletters`, `Keywords`, `Statistics`.
Gained elsewhere: a `Statistics` subtab on the **Governments** tab.

`Advanced` is a container of sections, **all foldable and folded by default** (reuse the existing
`<details>` convention — 18 instances already in `index.html`; do not invent a second one):
Keywords · Sources · Legacy collection · Manual ingest · Batch ingest · Statistics producers ·
Calendar directory.

**Folded must not mean fetched.** Several of these lists are large (the source catalog can hold
~46k rows). Loaders currently fire on subtab select; in `Advanced` they must fire on **section
expand**, so opening the subtab costs nothing.

---

## 2. Maintainer rulings (2026-07-31) — binding

1. **Cards are grouped by FAMILY.** All 8 families accessible and tweakable; `overtold` built
   end-to-end FIRST as the reusable pattern, the other 7 follow it.
2. **Tuning depth:** one family end-to-end first, then generalise.
3. **Safe ranges:** every tunable carries a documented min/max clamp, stated visibly in the UI —
   never a silent clamp.
4. **The text-size slider is REMOVED** — rely on browser zoom. (The alternative was a ~149-site
   `px`→`rem` migration; the maintainer declined it.)
5. **P0 data-safety validation STAYS** ("I'll run it on the big corpus") — panel, module, job,
   bundle member all untouched. This keeps 0.3 close-gate rows 4 + 7 runnable.
6. **The page-size A/B bench is REMOVED ENTIRELY** — panel, `src/monitoring/pagesize_bench.py`,
   its endpoints, its bundle member, its ratchet classification, `tests/test_pagesize_bench.py`.
   The two `connect.py` comments citing it BY NAME (lines 86, 332) must be rewritten to carry the
   provenance inline, so the empirically-proven PRAGMA ordering fact is not orphaned.
7. **Legacy restore removed entirely** (frontend + backend), maintainer has already merged their
   pre-volumes backups. `restore_legacy_path` and `/legacy/restore` go with it. `read_artifact`'s
   legacy-format acceptance STAYS (it is also the reader for current archives).
8. **"Older backup tool" (raw `.db` snapshot) removed entirely**, frontend + endpoint.
9. **Statistics sources register ENABLED and CRAWLABLE by default**, with a **new per-agency
   `news_url`** field so the crawl targets press-release/news sections rather than dataset
   portals. Filling `news_url` for ~150 agencies is a NETWORKED research pass (the law-batches
   pattern) — an OPERATOR step; the code ships the field, the crawl targeting, and honest
   behaviour when `news_url` is absent.
10. Agenda: no new fetch behaviour — remove the manual buttons, surface the existing automation.
11. **Feed verification becomes progressive**, riding collect passes (NEVER app startup — boot is
    airplane-mode/zero-network), and **must be visible in the task manager**.
12. **Dysfunctional calendar feeds get automated re-check, same as sources** — mirror the
    qualification ladder exactly (1→2→4→6 months capped, append-only attempt history, bounded
    per-pass selection). Never a permanent exclusion.
13. **The Keywords subtab is removed** (contents → `Advanced`).
14. **Translate the 4 user-facing PROSE prompt bodies ×12** (summary, translate, synthesis,
    ai-keywords). Rationale (maintainer): "our small model speaks ~30 languages, our 12 languages
    will be well covered, and we don't want a non-english user to have the AI create some english
    work". **The ~10 `ai_layer` machine-parsed prompts stay ENGLISH** (triage, source_tags,
    qualification_assist, perception, langdetect, extract, translate-internal): their parsers
    validate against English tokens — a single word, an exact echo-back, a fixed label, a language
    code — and they produce nothing a user reads. Translating them would break parsing, not
    improve output. **This SUPERSEDES the recorded 2026-06-21 finding** for the prose half only;
    the finding's reasoning still governs the machine-parsed half.
15. **Hardware gate, refined — this SUPERSEDES the 2026-07-30 GPU-absence rule:**
    * **< 4 CPU cores OR < 6 GB RAM → honest "can't run locally here"** (hard refusal tier).
    * **GPU-less → WARNING, not refusal.** A GPU-less machine with ≥4 cores and ≥6 GB RAM now
      defaults **ON** with a stated warning. (The 2026-07-30 text explicitly refused "a 64 GB
      GPU-less workstation"; the maintainer chose reading (a), supersede.)
    * **< 5 GB VRAM → WARNING** (set at 5, not 6: Mistral-7B Q4 needs ~4.4 GB and measured 5.1 GB,
      so a 6 GB line would warn on cards that genuinely work).
    * The override toggle and the never-a-hard-block posture are UNCHANGED.
16. **Stack of draft PRs**, merged progressively; each PR appends its own `shipped.csv` row and
    the stack is rebased after every merge.
17. **The 3 existing recipe toggles keep their exact current behaviour** (nothing regresses) but
    **get a modernized UI** in the Cards tab.
18. **Wikipedia is NOT touched.** Record the intent in `docs/FUTURE_DEVELOPMENTS.md`: Wikipedia
    should be a source like any other journal, differing only in that changes are tracked with an
    audit trail — the current Settings UI wrongly implies wiki articles are outside the corpus and
    need a separate search tool. **Check first** whether the existing "Versioned sources as
    first-class Articles" section already records this; if so EXTEND it and point at it rather
    than writing a duplicate.

---

## 3. The PR stack

Ordered by dependency and by shrinking the surface later PRs edit. Every PR: `node --check` on
touched JS, `scripts/i18n_report.py --min 100`, `ruff check --select=F,B --extend-ignore=B008`,
`mypy` ratchet ≤ 127, `bandit==1.9.4 -r src/ -ll -q`, full `pytest -q`, one `shipped.csv` row.

### PR-1 — Subtractions and Graphics
*Pure removal; lowest risk; shrinks what every later PR touches.*
- Remove the text-size slider: `#dr-font`, its `<label>`, `setFont`, the `fontSize` line in
  `applyUi`, the persisted `ui.font`. **Delete** `test_repo_invariants.py:6452-6461` with a
  comment recording that the slider was removed by ruling 4 — otherwise a future session reads
  the missing label as an accessibility regression and restores it.
- `Typeface` → `Fonts`; add the `Fonts` key to all 12 locales. Keep `#dr-faces` (test 1961).
- Remove the Leads subtab (`#set-leads`, its nav button, `loadLeadsView`, the `showSetCat` case).
  Delete `tests/test_leads_subtab.py`. Re-anchor `test_repo_invariants.py:4636` onto a delimiter
  that still exists. `/api/insights/leads-view` and `src/briefing/leads.py` are **backend, keep** —
  `sort_leads` orders Home and the subtab was preview-only.
- Data & backup removals: legacy-restore panel + `v2Preview`/`v2Apply` + `/legacy/restore` +
  `restore_legacy_path`; the "Older backup tool" `<details>` + `downloadBackup()` + its endpoint;
  the polls section + `pollTransparencyCheck`/`Clear` + the JSON-paste textarea + the backend
  module + `test_poll_transparency.py` + `test_beta_poll_transparency.py`; the page-size bench
  (see ruling 6, incl. the `connect.py` comment rewrite); the two redundant buttons
  `reindexAllCorpus` + `pruneKeywords` (the surviving `cleanupKeywords` does both — verified).
- Safety: remove the `Encrypted backup` section; **move the `#ux-export` dialog markup to top
  level** (V9) and rewire `uninstallBackupFirst()` to `openUnifiedExport()`.
- `docs/FUTURE_DEVELOPMENTS.md`: the Wikipedia note (ruling 18).

### PR-2 — The `Advanced` subtab
Create it; move Keywords (whole subtab), Collect's *Advanced legacy collection* + *Manual ingest*
+ *Batch ingest*, and Sources (whole subtab) into foldable, folded-by-default sections. Remove the
`Keywords`, `Collect`, `Sources` subtabs. Move `Keyword filtering` out of General into the
Keywords section. Add the three missing Keywords `<h2>` keys ×12. Make the super-group section
foldable. **Loaders fire on section expand, not subtab select.**

> **Anything in `#set-collect` beyond the three named sections must be re-homed, not dropped** —
> `#set-collect` also holds *Collection* (scheduler cadence/parallelism/rate) and *Which sources
> (rss / crawl modes)*. Enumerate them and place them explicitly; silently losing scheduler
> configuration is a Desk-lesson violation.

### PR-3 — Shortcuts → General
Move the keyboard-shortcuts content into General; remove the `Shortcuts` subtab; update
`tests/test_ui_keybindings.py:26`.

### PR-4 — Newsletters → Data & backup
Move all six Newsletters sections in as dedicated sections; remove the subtab; add the missing
`Import documents (PDF)` key ×12 and any other unkeyed strings found there; update
`test_repo_invariants.py:3169`.

### PR-5 — Statistics dissolution
Producers list → `Advanced` (foldable). Figures / vintages / revision anomalies / triangulation /
auto-refresh subscriptions → a **new `Statistics` subtab on the Governments tab**. Remove the
`Statistics` Settings subtab. Backend: `StatAgency` gains `news_url`; `ingest_agencies_as_sources`
registers `enabled=True`; the crawl uses `start_url=news_url` when present and degrades honestly
when absent. Fix the misleading button copy ("Register…" → state plainly what happens). The
`statistics` tag needs no work (V5).

### PR-6 — Agenda
Remove the imported-events section and the *Verify next 25* button. Make verification progressive
on collect passes with a task-manager job. Add the calendar-feed re-check ladder mirroring
`catalog/qualification.py` (V13). Move the Calendar directory into `Advanced`. Fix the contrast:
drop `opacity:.6` from `.ag-cal` and give the off state a theme-aware token that clears WCAG AA on
all 17 themes — **verify by contrast math across every theme, the `--caveat` precedent**, not by
eye. Rename `Offline map` → `OpenStreetMap` at every occurrence (nav, heading, palette registry,
`test_repo_invariants.py:2522`); no locale key needed (V10).

### PR-7 — The `Cards` subtab
The largest new build.
- New subtab; the recipes content moves in with a **modernized UI** (ruling 17), the 3 existing
  toggles behaviourally unchanged.
- All **8 families** listed and accessible: `context` (10) · `watch` (8) · `investigate` (7) ·
  `overtold` (4) · `debunk` (3) · `undertold` (2) · `rising` (2) · `trust` (1).
- **`overtold` end-to-end first** as the pattern: per-producer tunables (minimum articles, minimum
  distinct sources, window days, and each producer's own conditions), each with a **safe range**,
  a **reset to default**, and a **one-line plain explanation of impact** ("more articles = more
  robust; more sources / languages / geographies = more representative").
- Backend: a persisted per-producer settings store. `recipes_disabled` is the only existing
  precedent — extend that mechanism rather than inventing a parallel one.
- **Honesty fence:** thresholds that exist to prevent an underpowered claim (count floors, the
  FDR alpha) are clamped to a range that cannot produce a fabricated signal, and the clamp is
  stated. `assert_no_score_fields` and the no-composite-score rule are untouched.

### PR-8 — The AI subtab
- Collapse the redundant "no GPU detected" messaging to ONE statement.
- **Fused one-click install:** a single button that picks vLLM on a GPU machine and Ollama
  otherwise, and includes the default-model download. Remove the redundant "start the local AI"
  button — the top-bar pill is the only start control.
- Implement ruling 15's thresholds in `inference_capability()`. **Two predicates stay two
  predicates**: `detect_gpu()` answers "can vLLM run here?", `inference_capability()` answers "is
  local inference practical?" — the ast guard in `tests/test_inference_hardware_gate.py` forbids
  OS/arch policy leaking into `detect_gpu()`. The new CPU/RAM floor belongs in
  `inference_capability()` only.
- Translate the 4 prose prompt bodies ×12 (ruling 14). Keep `Behaviour & prompts` otherwise as-is
  — the maintainer likes it. Custom user extractors are user-authored; no action.

---

## 4. Scope fences

- **Never touch Wikipedia** beyond the FUTURE_DEVELOPMENTS note.
- **Never remove the P0 validation** panel, module, job or bundle member (ruling 5).
- **Never weaken** `assert_no_score_fields`, the FDR correction, or any caveat's default
  visibility while building the Cards tuning UI.
- **Never fabricate a capability**: a statistics agency with no `news_url` must behave honestly,
  not pretend to have one.
- **Never let a removal strand data**: `read_artifact`'s legacy acceptance stays.
- **Never verify feeds at boot** — airplane-mode/zero-network boot is a non-negotiable.
- Every endpoint removal must be reflected in the all-diagnostics ratchet
  (`test_all_diagnostics_bundle_covers_every_get_diagnostic`) in the SAME commit.

## 5. Operator steps (maintainer, not the coding session)

1. Run the P0 validation on the big corpus (ruling 5; 0.3 close-gate rows 4 + 7).
2. The networked research pass filling `news_url` for ~150 statistics agencies (ruling 9).
3. Browser click-through of every frontend slice — all eight PRs are browser-unverified here.
