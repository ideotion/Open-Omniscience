# AUTONOMOUS SESSION BRIEF — SYSTEMATIC GUI TEST & CRITICAL REVIEW (2026-07-22)

**Status:** brief of record, execution PENDING.
**Executes toward:** `RELEASE_0.3_GATE.md` row 8 (the browser-verification bar — the
file sits at the REPO ROOT, not under `docs/`) and the accumulated fork-3
"browser-unverified, needs click-through" backlog.
**Composes with (do not duplicate):** `src/monitoring/ui_walk.py` (the injectable
row-8 walk harness — wire a real driver into its `UiWalkDriver` seam where it fits),
`docs/design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md` §6 (the AppVM variant),
`docs/design/ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md` (browser-gated phases).
**Feasibility:** PROVEN 2026-07-22 in a remote sandbox session — the app boots on a
scratch data dir in ~15 s, Chromium + playwright-core drive it, zero JS errors on a
first smoke walk. Every command in §2 was executed successfully that day.

---

## 0. Mission

One autonomous session drives the **running app in a real Chromium browser**, walks
**every user-facing surface** systematically, and delivers a **critical findings
report** — bugs AND optimization candidates — each with severity, numbered repro
steps, the ruling/invariant it violates, and screenshot evidence.

**Report-first.** The deliverable is the findings report, not fixes (§10). A test
pass that stops to fix things contaminates its own coverage.

Two goals, equally weighted:

1. **Verification** — burn down the "browser-unverified" backlog: confirm the
   conservative+flagged frontend slices actually work, and stamp them honestly.
2. **Critique** — an adversarial product-quality review: where is the UI
   inconsistent, confusing, dishonest-by-accident, slow, or wasteful? The §8 lenses
   define what "critical" means; "it renders" is the floor, not the bar.

---

## 1. Binding ground rules

- **Scratch data only.** `OO_DATA_DIR` points at a temp dir. The real corpus NEVER
  enters the session (the standing AppVM safety line applies to every environment).
- **Airplane stays engaged.** The app boots offline; keep it that way. The one
  consent popup is tested by opening it and **cancelling** — never confirm it.
  Additionally **assert** the guarantee: run the whole session under Playwright
  request logging and verify zero browser-originated requests to any non-loopback
  host (this is a browser-layer check of the airplane non-negotiable — a strong,
  automatable assertion, and any hit is an automatic P0).
- **Draft-PR-only.** The repo change is the report + bounded evidence + the ledger
  row. Nothing else, except a §10 unblocker.
- **Honest stamps.** A surface that passes graduates to
  **"Chromium-verified (remote sandbox) · awaiting human UX pass"** — this is NOT
  the queued "Gecko-verified (VM)" stamp (different browser, different environment)
  and it never claims the human pass. Never over-stamp.
- **Findings are hand-re-verified before filing** (the 06-audit false-positive
  lesson): re-run the repro from a clean page load. Then run a refutation pass over
  the whole list (§9).
- **Staleness guard.** This repo fast-merges; re-verify anchors in this brief
  against the tree at YOUR run time. Where this brief and the tree disagree, the
  tree wins — note the drift in the report.
- **Subagents must not read `CLAUDE.md` wholesale** (~630 KB; it has overflowed
  agent contexts before). This brief carries what the walk needs; feed subagents
  inline excerpts only.
- **Never switch git branches while the server or a suite is running.**

---

## 2. Environment setup (verified 2026-07-22, remote sandbox)

```bash
# 1. Python venv — py3.13 exists in the sandbox even though `python3` is 3.11.
python3.13 -m venv /tmp/oo_venv
/tmp/oo_venv/bin/pip install -q --upgrade pip
/tmp/oo_venv/bin/pip install -q -e ".[analysis]"      # sqlcipher3 wheels install fine here

# 2. Scratch app — plaintext DB for the MAIN walk (no passphrase juggling);
#    the encrypted/first-launch flows get their own dedicated state (§4).
export OO_DATA_DIR=/tmp/oo_data_main
mkdir -p "$OO_DATA_DIR"
nohup env OO_DATA_DIR=$OO_DATA_DIR OO_DB_PLAINTEXT=1 \
  /tmp/oo_venv/bin/open-omniscience > /tmp/oo_server.log 2>&1 &
# Wait for "Uvicorn running on http://127.0.0.1:8000" in the log (~15 s;
# alembic stamps + source seeding happen on first boot).

# 3. Browser — Chromium is pre-installed; playwright-core comes from npm.
ls /opt/pw-browsers/            # find the chromium-<build> dir; the path varies
mkdir -p /tmp/pw && cd /tmp/pw && npm init -y && npm i playwright-core
# launch with: executablePath: '/opt/pw-browsers/chromium-<build>/chrome-linux/chrome',
#              args: ['--no-sandbox']
```

Gotchas verified live:

- `open-omniscience accept-terms` without a TTY dies with `EOFError`; headless
  acceptance is `open-omniscience accept-terms --yes`. The web first-launch flow is
  the normal path.
- With NO env choice and no DB, `/` returns 307 → `/unlock` (the fresh-store flow).
  With `OO_DB_PLAINTEXT=1` the app serves the main UI directly.
- The viewport for the reference walk is **1400×900**; §6 adds the other
  breakpoints.
- Restarting states: kill the server, swap `OO_DATA_DIR`, relaunch. Keep one data
  dir per state (§3) so states never contaminate each other.

---

## 3. Test corpora — three states

**STATE A — virgin** (no DB file): the first-launch flows (§4). Fresh dir per run.

**STATE B — empty corpus** (post-setup, 0 articles): the **empty-state honesty
pass**. Every CORPUS-DRIVEN surface (anything fed by articles/keywords/mentions)
must render an *explanatory* empty state — never a blank div, never a spinner
that spins forever, never a JS error. "Home must never go blank-and-silent" is a
standing rule; apply its spirit everywhere. NB STATE B is NOT globally empty:
boot auto-seeds the ~3,200-source catalog (`OO_AUTOSEED` defaults on) plus law
documents/portals, and Agenda shows computed moon/season glyphs + curated
calendar events with zero articles — those surfaces showing content is correct,
not a finding.

**STATE C — populated synthetic corpus**: the main functional pass. Seed it
offline with a scratch script (session scratchpad, NOT committed) that writes
through the real ingestion chokepoints (`index_article` etc.), so keywords, FTS,
facets, When×Where×Who and provenance are real. Target spec — every surface must
have something to show:

- ~400–600 articles across ≥8 languages — MUST include `ar` (RTL), `zh`
  (unsegmented), `en`, `fr`, `de`, `ru`; publication dates spread over ≥3 years
  (cross-time surfaces need old data).
- In-text mentioned dates (past AND future — feeds Agenda's deduced events),
  places (feeds the map + When/Where/Who), entities, acronyms (`WHO` vs `who`).
- Near-duplicate clusters across ≥3 distinct sources (feeds echo/Related/badges)
  and shared outbound links (feeds Links/shared origins).
- Commodity/index price series: one dense (≥50 pts) and one sparse (<10 pts — the
  bars-not-line rule must be visible).
- A few laws, wiki pages, and .eml newsletters (distinct provenance classes;
  `.eml` files can be generated and imported via the real importer).
- Deliberate junk: one nav-soup specimen, one wrong-language-labelled article
  (script-guard behavior), one empty-body row — the degrade paths are test
  targets, not noise.

---

## 4. First-launch & lifecycle flows (STATE A)

Walk in order; screenshot each step:

1. **Encrypted default path** (no env vars): `/unlock` → language step first
   (12 native names; pick a non-en once, verify the page re-renders translated) →
   **legal acceptance** → passphrase creation (test: confirm-mismatch, a short
   passphrase → length guidance shown, never a hard block) → main app + guided
   wizard (themes default ALL-selected; language emphasis optional; the Finish
   step must NOT post `/api/system/network` — cancel at the consent popup if one
   appears).
2. **Legal decline path**: on a scratch install, verify decline demands the typed
   confirmation and does what it claims — and nothing it doesn't.
3. **Env-driven init** (`OO_DB_PLAINTEXT=1`): SEED FINDING S-1 to verify — the
   2026-07-22 smoke suggested this path may reach the main UI without the web
   legal-acceptance step. Confirm whether acceptance is recorded, bypassed, or
   deferred; if bypassed, that's a P1 (the legal gate is first-launch-gating by
   design).
4. **Lock/unlock cycle**: there is NO in-app relock control by design — relock
   by restarting the server against the encrypted data dir (kill + relaunch
   without `OO_DB_PLAINTEXT`/`OO_DB_PASSPHRASE`). Then: wrong passphrase (loud
   error; NO backoff/lockout — its absence is a ruled design decision, do not
   file it), correct unlock, then browser Back (must never land on `/unlock`).
5. **Locked-API behavior**: load `/` while locked and let the SPA's first data
   fetch receive the 503-locked response — the fetch wrapper must redirect via
   `location.replace("/unlock")` (app.js ~1311; no history pollution). NB a bare
   API URL typed in the address bar just returns the JSON error — that is not
   the surface under test.
6. **Shutdown button**: confirm dialog → terminal overlay covers the full UI (no
   clickable dead chrome behind it).
7. Boot-time console: record any browser console noise at first paint. SEED
   FINDING S-2: 8× `[DOM] Password field is not contained in a form` verbosity
   was observed 2026-07-22 — verify and file (P2, autofill/a11y hint).

---

## 5. Coverage matrix (STATE B first, then STATE C)

Anchors below were grepped from `src/static/index.html` on 2026-07-22 — re-verify
at run time. **Every row of this matrix appears in the report's coverage table
with a verdict: `verified` / `partial (why)` / `blocked (why)`. No silent
skips.**

### 5.1 Chrome & global surfaces

| Surface | What to check |
|---|---|
| Top bar | Omnibar (type → 3-result bubble; Enter → analysis window), health pill, LLM pill (honest "offline" with no Ollama; click opens Settings→AI), activity chip, **airplane toggle** (filled glyph = offline; click → consent popup → CANCEL; direction-aware flash), language switcher (all 12; native names; RTL flip for `ar`), help, power. Constant footprints: nothing on the right may shift as labels change. |
| Sidebar | 8 tabs: `home` · `insights` · `timemap` (World map) · `law` (Governments) · `agenda` · `indices` · `markets` (Commodities, `adv` badge) · `library`; Settings pinned at bottom. Collapse to icon rail; must never go off-canvas above 600 px. |
| Subtab strip | `_relocateSubtabs` moves the active tab's facet nav under the status bar; verify per tab, and that listeners survive the DOM move (click a subtab AFTER relocation). |
| Task-manager window | `#tm-subtabs`: Active · Queue · Schedule · Coverage · System. Empty states ×5; vitals live in System; no fabricated ETA/rate anywhere. |
| Command palette | Ctrl/⌘-K: static groups instant, live groups append; article hit → LOCAL reader; keyboard up/down/Enter. |
| Dialogs | `#chart-enlarge`, `#folder-picker`, `#guide-wizard`, `#link-preview`, `#net-consent`, `#synth-window`, `#ux-export`, `#ux-import`, `#wiki-tc` — each: opens, focus-trapped (native `showModal`), Esc closes, no scroll-behind, reopens cleanly. `#corpus-win` is RETIRED dead DOM (`openCorpus` routes to the #an window, app.js ~15396; retire comment at index.html ~2429) — do NOT test open/close; verify only that nothing opens it and nothing errors around it. |
| Airplane coachmark | `#net-coach` (index.html ~2570): appears on a first offline launch anchored to the airplane button; "Go online" must open the consent popup (cancel it) and never POST the network itself (invariant #14b); "Not now" retires it across reloads; it must not occlude the top bar. |
| Hover convention | `#oo-tip`: dotted underline/corner-dot marking appears automatically on titled elements; bubble opens on hover AND keyboard focus; re-reads the live translated title after a language switch. |
| External links | Every external anchor passes the confirm popup; loopback exempt. The link-preview dialog (`#link-preview`) shows the local extraction with the full URL as visible text. |

### 5.2 Per-tab walks

- **Home**: glance strip (compact, top-pinned); Lead cards — flip animation,
  caveat renders on the BACK in `.card-caveat` beside "Open corpus" (per the
  amended invariant #23), front decluttered; card click seeds the exact
  `article_ids` corpus; carousel pausable + keyboard; trends-glance sparklines
  (bars when n<10); family subtabs with the "All" default; ordering — Home is
  reordered by the Leads-2.0 disclosed `order_key` (BUCKET priority first, then
  the order_key tuple — `src/briefing/service.py` ~162-188; the standalone
  `sort_leads` function itself has no production caller, so never diff Home
  against a raw `sort_leads()` computation): sanity-check the order against
  `explain_order` if surfaced.
- **Insights** (`#ins-subtabs`): Explore · Trends (three windows side by side +
  top-5 series + ⛶ enlarge) · Sources · Families (SEED FINDING S-3: verify the
  kind dropdown offers only kinds the data actually has — a "people/orgs/places"
  option returning silent empties is a known critique class) · Super-groups
  (circle grammar ⦾/⦾⦾ if shipped) · Map · Convergence (span entries; counts must
  be EXACT, never a cap echoed as a count) · Watches (create/edit/disable/delete
  round-trip) · Lunar.
- **World map** (`#tab-timemap`): lens nav Coverage · Stories · Places · Server
  IPs; dimension picker (sources/articles/keywords/tone — tone on a diverging
  scale + visible VADER-English-only caveat + hatch ≠ zero for no-data);
  country/continent granularity; places overlay (deduced caveat visible); signals
  layer + time slider (drag smoothness — rAF-coalesced) + marker click-detail +
  "near in space & time" (non-causal caveat verbatim); zoom/pan/reset/fullscreen;
  localized country names after a language switch.
- **Governments** (`#gov-subtabs`): Countries · Map · Law. Law: changes list
  default state, per-doc verdict visibility, add-by-URL if shipped. CRITIQUE
  seed: the tab is labelled "Governments" and opens on Countries — assess the
  law vertical's discoverability (a known maintainer pain point).
- **Agenda** (`#agenda-views`): Month · Week · Trimester · Semester · Year ·
  Decade · List; moon/season glyphs (ONE state per day — the dedup fix is a
  regression target); imported-event provenance pills ("from <feed>"); deduced
  pills + exact-set open; category + country filters; ICS import of a scratch
  file.
- **Indices & Commodities** (twin boards): category subtabs; tag chips; compare
  overlay (Absolute/Indexed/Log); families view; time-scope control; ONE coherent
  time axis across cards; sparse→bars; NO Load/Refresh buttons (auto-load note
  instead); per-feed verdicts visible.
- **Library** (`#tab-library`, four panels — not a browse list): overview counts
  render; **Database** live-stats grid (`#db-stats`/`#db-file`); the itemized
  **Storage footprint** incl. the external Ollama model store with its honest
  unavailable state (`#library-storage`); **World coverage** — choropleth
  click-to-filter, unlocated bucket, coverage table + country filter, gaps list.
- **Search tab** (`#tab-search` — no sidebar entry; reach it via the palette's
  "Run a search" or the omnibar's "run the full Boolean search" fallback): this
  absorption-gated surface still OWNS Boolean query + filters + time-scope,
  Export CSV/JSON, the Methods appendix, Synthesize, bulk Summarize/Translate +
  Run extractor (honest no-Ollama state), Export signed evidence, and the
  bulk-queue panel — walk all of it; losing any of it silently is a P0 class.
- **Evidence & custody** (`#tab-custody`, via Settings→Safety "Open evidence &
  custody →"): status line honest about build capability; PQC / OTS / auto-log
  toggle round-trips; the OTS IP/timing privacy warning appears when OTS is
  ticked; default-actor save.
- **Source-integrity desk** (`#tab-integrity`, via Settings→Safety): coordination
  scan + collapse/revert round-trip; source profile lookup (empty + populated);
  web-of-trust annotations export/import; honest empty states.
- **Help & documentation** (`#tab-help`, via the top-bar "?"): doc list loads and
  a doc renders fully offline; the find-on-page filter works; the Swagger anchor
  passes the external-link confirm; User-Manual deep links from other tabs land.
- **Reader** (standalone `/api/articles/{id}/view`): tabs in DOM order `read` ·
  `summary` · `translation` · `keywords` · `mindmap` · `sentiment` ·
  `subjectivity` (visible label **"Loaded language"** — don't match on the tab
  id's text) · `related` · `source` · `links`
  (`src/api/main.py` ~1911-1920); inline keyword marks → analysis spawn in a new tab;
  ≈N dup badge on a clustered article; UI language follows `oo.lang`; two-class
  metadata header (source-asserted vs app-deduced); server-IP row if shipped.
- **Analysis window** (`#an-subtabs`): spawn from omnibar Enter; named parallel
  tabs (open 3+, close, reload — persistence); subtabs Overview · Keywords (incl.
  In-context concordance + group chips) · Trend (overlay + Counts↔Indexed +
  dual-axis price) · Mindmap · Articles (pagination above AND below; tone chips;
  dup badges) · When/Where/Who (facet chips → drill into a refined window) ·
  Links · Related (near-dup clusters + shared origins + multi-select branch) ·
  Sentiment · Sources · Competitive (n=1 honest state) · Price (commodity-gated,
  hidden otherwise) · Advanced (sort by metadata; language as a `<select>` with
  full names; "Filtered" chip; verify whether an Advanced refine on an id-seeded
  corpus intersects or clears — the ruled behavior is intersect). The bulk-LLM
  action row (Summarize all / Translate all / Run extractor + the `#bulk-llm-an`
  progress and persistent `#bulk-queue-an` queue panels): honest no-Ollama
  refusal; queue enqueue/cancel/clear states. Synthesis window (`#synth-window`):
  selection step (checkboxes, k/20 counter), result + members + export paths
  (Copy / .md / open-as-page).
- **Settings** (`#set-subtabs`, 15): Graphics (incl. the **Alternative
  interfaces gallery** now inside Graphics — switch 2–3 skins, verify caveats +
  the consent surface survive in each, switch back) · General · Shortcuts · AI
  (honest no-Ollama state) · Keywords · Leads (isolated preview; Home must stay
  byte-identical while previewing) · Collect · Sources (qualification status /
  discovery trail / citations tally if shipped) · Newsletters · Wikipedia ·
  Statistics · Offline map · Agenda · Data & backup · Safety.
- **Diagnostics panel** (in Settings): run the **all-diagnostics JOB to
  completion** on the synthetic corpus — progress line, cancel affordance, zip
  downloads, journal present; verify the button-consolidation state (ruled: ONE
  download button + surviving ACTION controls); presence-smoke the heavy benches
  (p0-validation, pagesize) WITHOUT running them.
- **Import/Export** (`#ux-export` / `#ux-import`): export the scratch corpus
  (small); import it back into a second scratch data dir — additive merge; then
  CRITIQUE the post-import results screen against the ruled redesign (articles
  headline in the user's unit, labeled per-type breakdown, corpus delta, induced
  work — the row-sum headline is a known-open item, confirm current state).
- **Standalone pages**: `/tasks` (app-identical top bar; airplane flash parity),
  `/investigate`, `/desk`, `/unlock` (already in §4).

---

## 6. Cross-cutting axes

- **Themes**: all 17 + System, on three anchor surfaces (populated Home,
  Settings, World map). Screenshot each. Spot-check `.card-caveat` contrast by
  computed style (WCAG 4.5:1 math — the caveat-color regression class).
- **Locales**: switch through all 12 live (one click each — the ENTIRE UI must
  switch); full walk in `en` + `fr`; a dedicated **RTL audit in `ar`** (mirrored
  layout, subtab strip, dialogs, the map controls); density check in `zh`/`ja`.
  Hunt untranslated chrome: report counts per surface, not every string (a known
  ~hundreds-string tail exists — quantify by surface, flag regressions).
- **Breakpoints**: 1400 · 1024 · 768 · **601** (the sidebar-rail boundary) · 375.
  Sidebar must keep at least the icon rail above 600 px; no horizontal body
  scroll anywhere; dialogs fit the viewport.
- **Input**: one full flow keyboard-only (subtabs are roving-tabindex with
  arrow-key nav — verify); dialog focus traps; Esc paths; `prefers-reduced-motion`
  honored on the flip cards / carousel / flashes.
- **A11y sampling**: run axe-core (npm) on 5 key screens; file violations with
  honest severity (an axe "critical" is not automatically a P0 — judge impact).

---

## 7. Performance & behavior instrumentation

Numbers, not impressions — each OPT finding carries a measurement:

- **Per-tab first-paint**: navigation → content visible, per tab (Performance
  API + a DOM-settled marker). Table in the appendix.
- **Idle-poll census**: 60 s idle on Home with the network log running — count
  requests by endpoint. The polling-storm history makes this a standing
  regression check (expected: the lean network poll only; anything chatty is a
  finding with the exact cadence).
- **Long tasks** (>50 ms) on the heavy surfaces: map render, families, analysis
  open, theme switch.
- **DOM node counts** per populated tab (flag outliers).
- **Request waterfalls** on each tab's first open: duplicate fetches, serial
  chains that could parallelize, oversized payloads.
- **Leak smell**: open/close the analysis window ×10, take heap snapshots
  before/after (detached-node growth = finding).
- **Repaint abuse**: drag the map time slider and a chart zoom for 5 s each —
  frame-rate observations.

---

## 8. The critical lenses (what "critical view" means here)

Apply ALL seven to every surface; the report's per-surface notes say which lenses
produced findings:

1. **Honesty lens** — caveats visible by default (never behind calm-UI toggles)?
   method + n stated on every number? deduced labelled deduced? empty states
   explanatory? no score-like language anywhere in chrome? sparse data drawn as
   bars/points, never an interpolated curve?
2. **Consistency lens** — same subtab grammar, hover convention, empty-state
   voice, chart toolkit, spacing rhythm as sibling surfaces? Any one-off pattern
   is a finding (the divergence itself, not just its bugs).
3. **First-user lens** — is the next action obvious? dead ends? jargon without a
   hover explanation? how many clicks to the app's core value (search → corpus →
   reading)? The Governments/Law discoverability class lives here.
4. **Data-density lens** — wasted space vs overload; tables that want to be
   charts and vice versa; does the surface still work at 400 articles AND read
   sensibly for the 500k-article field reality (extrapolate: unbounded lists?
   unvirtualized tables?).
5. **State-abuse lens** — double-click every primary action; rapid tab
   switching; reload mid-dialog; browser Back/Forward across tabs; two browser
   tabs on the same app; dialog stacking; switch language mid-flow.
6. **Failure lens** — kill the server mid-session (honest error or silent
   blank?); inject a 2 s delay on one endpoint via Playwright route interception
   (loading state or layout jump?); a guarded endpoint's 429/503 (does the UI
   degrade loudly?).
7. **Optimization lens** — from §7's numbers: the top-5 slowest interactions,
   chattiest endpoints, biggest DOM offenders, redundant fetches. Each becomes an
   OPT finding with the measurement and a one-line suggested direction.

---

## 9. Findings discipline

**Severity taxonomy:**

- **P0** — a broken flow, data risk, or an honesty violation (hidden caveat,
  fabricated number, silent network egress).
- **P1** — a real defect with a workaround.
- **P2** — polish/cosmetic.
- **OPT** — a measured optimization opportunity.
- Sub-tags: `A11Y`, `I18N`, `PERF`, `RTL`.

**Every finding carries:** id · surface · severity · numbered repro from a clean
load · expected (anchored to the invariant/ruling/convention it violates — cite
it) · actual · evidence path · `known-open?` (checked against §11) · optional
one-line suggested fix.

**Process:** hand-re-verify each repro → assemble the full list → run a
**refutation pass** (a skeptic sweep whose job is to kill findings: wrong repro?
intended behavior per a recorded ruling? environment artifact?) → only survivors
ship. Findings killed by the skeptic are listed in an appendix with the reason
(that record has value too).

**Known-open items are not re-discoveries.** Confirming one is still present is
VALUABLE — file it in a separate "known-open, still present / now fixed" section.
That section IS the backlog burn-down.

---

## 10. Anti-scope

- **No fixes during the test pass.** Exception: a minimal, isolated unblocker
  when a P0 walls off an entire region of the matrix — separate commit, loudly
  flagged in the report.
- **No real network.** The app never goes online (cancel the consent popup every
  time). pip/npm setup traffic is the only egress. A collect run is backend
  behavior, out of scope.
- **No heavy benches** (p0-validation, pagesize, scale) — presence-smoke only.
- **No Ollama.** LLM surfaces are verified in their honest-absent state. The
  airplane/loopback-Ollama gate item is verified only as far as UI affordances go.
- **No destructive actions on anything real** — uninstall/panic-wipe flows run
  against scratch installs only, and the panic-wipe is exercised at most to its
  confirmation step.

---

## 11. Known-open cross-check list (verify state, don't re-discover)

Compiled from the ledger 2026-07-22 — the tree may have moved; verify each:

1. Post-import results headline sums rows across all tables (redesign ruled).
2. Airplane mode blocking loopback Ollama generation (fix was in flight — PR
   #730 class; verify merged state).
3. Governments/Law subtab discoverability (2 clicks deep, tab named
   "Governments").
4. Inline-handler retirement backlog (~hundreds of `on*=` attributes) — count,
   don't enumerate.
5. i18n untranslatable-chrome tail (~hundreds of strings) — count per surface.
6. Dead retired temporal-map JS awaiting browser-verified deletion (unreachable
   code — confirm it's still unreachable, i.e. nothing broke around it).
7. Settings→Leads preview modes not yet graded onto Home itself.
8. Conjunction-lens deeper views not yet surfaced in its payload.
9. El Niño agenda banners parked (verification-pending dataset).
10. Seed findings S-1 (env-init legal-gate bypass?), S-2 (password-field console
    verbosity), S-3 (Families kind dropdown offering kinds without data).

---

## 12. Deliverables & definition of done

On a `claude/gui-systematic-test-*` branch, as ONE draft PR:

1. **`docs/audit/GUI_TEST_REPORT_<date>.md`** — executive summary (top-10
   findings first) → the full coverage table (§5 matrix, one verdict per row) →
   the findings ledger (§9 format, most severe first) → known-open status
   section → measurements appendix (§7 tables) → the skeptic-killed appendix.
2. **`docs/audit/gui-test-<date>/findings.csv`** — machine-readable mirror
   (id, surface, severity, tags, title, known_open, evidence).
3. **Bounded evidence**: only finding-referenced screenshots, compressed,
   ≤150 KB each, ≤6 MB total, under `docs/audit/gui-test-<date>/evidence/`. The
   full screenshot set stays in the session scratchpad, referenced by name.
4. **A `shipped.csv` ledger row** + a compact CLAUDE.md Open-queue closeout note
   (which surfaces graduated to "Chromium-verified (remote sandbox) · awaiting
   human UX pass"; what stays blocked and why).
5. If practical, a thin **`UiWalkDriver`** implementation for
   `src/monitoring/ui_walk.py`'s seam (the row-8 harness) — note the seam is a
   PYTHON Protocol (`ui_walk.py:102`), so this needs the Python `playwright`
   package (`/tmp/oo_venv/bin/pip install playwright`, pointing
   `executable_path` at the same `/opt/pw-browsers` Chromium) — a SEPARATE
   install from §2's Node `playwright-core`. The committed module MUST
   import-guard playwright (skip honestly when absent; it is not a declared
   dependency — do NOT add it to pyproject without a ruling). Committed
   separately within the PR — wiring only, no scope creep. Skip without guilt if
   time is short; note it either way.

**Done means:** every §5 matrix row has a verdict (target ≥90 % `verified`, the
rest honestly `blocked (reason)`); all findings skeptic-passed; §6 axes each
executed at their stated depth; §7 tables populated; the report pushed as a draft
PR; and the closing section states plainly what this run does NOT establish — the
human UX pass, the Gecko/VM bar, and real-scale behavior remain owed.
