# CLAUDE.md — long-term session memory (maintainer-mandated)

**THE PROTOCOL (meta-rule, maintainer-mandated):** this file is the single
ledger of every maintainer ruling. (1) Read it in full before any work, every
session. (2) Record every new ruling HERE in the same turn it is given —
shipped things under invariants, pending things under the queue. (3) If the
maintainer repeats feedback, that is a ledger failure: fix the gap AND the
ledger. (4) Critical invariants are ALSO enforced by
`tests/test_repo_invariants.py::test_ui_invariants` — extend that test whenever
one is added here. It exists because work regressed between sessions (the
Wikipedia dropdown became a text input) and the maintainer had to repeat
earlier rulings. (5) Compress SHIPPED entries to verdict + pointer when the
file saturates (maintainer-asked 2026-06-12) — details stay in git history,
`docs/CHANGES.md` and the named design docs; NEVER compress away a pending
ruling, a contingency, or a deliberate-omission note.

## Non-negotiables (project §0.5 + maintainer rulings)
- Local-first, loopback-only; the ONLY external service call is the gated,
  off-by-default DuckDuckGo topic discovery. Producers/briefing/discovery NEVER
  touch the network. App boot makes zero network calls.
- robots.txt fail-closed, per-host politeness, honest bot UA, single fetch path
  (`EthicalFetcher`), **global network kill switch** (`src/ingest`
  activate/clear_kill_switch — the Collect Stop button trips it).
- Honesty by construction: no composite trust/quality scores (CardSchemaError
  enforces); every signal carries method + caveat + n; degrade loudly. No
  fabricated security, ever (no lock screens over plaintext, no theater).
- **INFORMED CONSENT — permanent, app-wide (RULED 2026-06-12, resolves audit
  U3 as "caveats by design"):** caveats are VISIBLE BY DEFAULT — never hidden
  behind a calm-UI toggle; the UI the user is in is always fully transparent
  AND always gives choice. Information overflow is handled by LAYERING, not
  hiding: translated HOVER BUBBLES (the existing translated `title`/popover
  mechanism) carry the long form while the visible surface keeps the caveat
  present. Every consent/caveat string ships ×12 locales. Applies to every
  surface built or reworked from now on (T9+); the network consent popup
  (invariant #14) and the restore preview (T6) are the reference patterns.
- **The 0.09 cycle is OPEN** (default branch `0.09` since 2026-06-11) ⇒ release
  0.0.9. Version single-sourced from pyproject. Historical `0.0.8`/`0.08` tags
  in docs/entries are records, not the current version.
- No bundling of Ollama/models in the repo (GitHub 100 MB limit). Model catalog
  stays date-stamped (`CATALOG_AS_OF` + freshness test); clearnet is a stated
  install prerequisite for model downloads.
- **Hosting stance (ruled 2026-06-10, PR #37 memo):** give the software away
  free; NEVER host the users' data. No SaaS, no central server, no accounts,
  no telemetry — the forward path is PWA + one-click self-host.
  **CLARIFIED 2026-06-12 (maintainer): the Open Commons Mirror vision is a
  SEPARATE SISTER PROJECT** hosting PUBLIC OPEN data (archive.org-scale
  ambition); it does NOT amend this app's stance — user corpora stay local
  forever and the mirror must never see them (queue entry + the
  FUTURE_DEVELOPMENTS section hold the design + the reliable-memory pillar).
- **At-rest encryption threat model, stated wherever shown:** protects a
  seized/off machine or a copied file — NEVER a compromised running session.
  **No recovery, no decryption alternative** for THE passphrase (maintainer
  rationale: the corpus is reconstitutable from the web). **CONTINGENCY
  RESOLVED 2026-06-15 (maintainer ruled "A" after the explainer): KEEP
  no-recovery for the local .eml newsletter import.** The contingency feared
  storing non-reconstitutable *PERSONAL* data under no-recovery; the
  anonymize-at-ingest design removes exactly that (no recipient identity, no raw
  .eml, no recipient headers/tracker tokens stored) and the user's OWN .eml
  files remain the re-import path (the file-world equivalent of "re-scrape").
  So: keep no-recovery + ship an import-time DISCLOSURE ("these join the
  no-recovery encrypted corpus; keep your .eml files for re-import") ×12; NEVER
  add a recovery key (a second decryption surface = the rejected
  fabricated-security path). Revisit ≠ must-change — consciously revisited &
  closed. RE-OPEN only if a future path stores genuinely non-reconstitutable
  PERSONAL content (e.g. live IMAP of a private mailbox held nowhere else).
- **Wrong-passphrase rate-limiting is a DELIBERATE, REASONED OMISSION (ruled
  2026-06-12 — do NOT re-add it thinking it was an oversight):** an attacker
  who can brute-force HAS the file and works offline (sqlcipher CLI/hashcat);
  a locked app holds no key in memory; our unlock already costs one full KDF
  per try (measured 173 ms ≈ 6 guesses/s; SQLCipher 4 = PBKDF2-HMAC-SHA512
  ×256,000, PRAGMA-verified). Backoff would punish only the honest fat-finger
  user = fabricated security. The honest lever is passphrase LENGTH guidance
  (shipped in the create flow, ×12 locales). Keep unlimited loud retries and
  the audited KDF default.
- **NEVER silently downgrade transport** (ruled 2026-06-12): no Tor→clearnet
  fallback without explicit consent — that is a deanonymization, not a retry.
  Never evade robots/blocks/CAPTCHAs; a host's Tor block is the host's choice,
  surfaced honestly with transport-aware verdicts.

## UI invariants (maintainer-ruled; do not regress)
1. **Wikipedia edition picker is a `<select>` dropdown** (id `wiki-lang`), fed
   by `/api/wiki/languages`. Never a free-text input.
   **AMENDED (ruled 2026-06-16; SHIPPED 2026-06-16): DROP the continent `<optgroup>`
   grouping** — editions are LANGUAGE-based, not country/continent-based (a
   language spans many continents), so the continent split is a category error
   and "not useful anymore." Renders a FLAT list (order: UI-locales-first then
   largest-edition-first via `languages_ui_first()`; option labels lead with the
   native name/autonym per invariant #15). Applies to BOTH pickers fed by the
   endpoint (`wiki-lang` watched editions + `dump-lang` dumps); `/api/wiki/languages`
   no longer emits `groups` (`languages_by_region`/`app_languages_by_region` removed;
   `region` kept as descriptive metadata only). The `<select>`/never-free-text CORE
   stays (test #1 unchanged — it never asserted the optgroups; no grouping assertion
   added). Endpoint contract pinned in `tests/test_wiki_languages.py` (flat, UI-first,
   `"groups" not in data`).
2. **Left sidebar lists all tabs and stays visible** — it may collapse to an
   icon rail, but must never disappear off-canvas above 600 px width.
3. **Top bar elements have constant footprints**: `.act-host` keeps its 160 px
   slot even when empty; `#llm` and `#health` have fixed min-widths; nothing on
   the right may shift as fetch hosts/labels change.
4. **AMENDED by §2 (ruled 2026-06-14, SHIPPED #143): vitals moved OUT of the
   chrome into the task-manager window's System tab** (`#tm-system`); the top bar
   keeps a PERSISTENT task-manager access (`#tm-open`, since `#activity` is hidden
   when idle). The version number is STILL NOT displayed in the chrome. (`#vitals-mini`
   retired; the 5 s chrome poll is now network-only — a bonus against the
   polling-storm finding.) Enforced in test_ui_invariants (#4).
5. **The brand mark is the ASCII eye** (`assets/logo.txt`) as vector — the
   pointed-oval + grid-iris SVG in `index.html` and `assets/icon.svg`.
6. Article links in analytics/insights lead to the LOCAL reader
   (`/api/articles/{id}/view`) first; the external original is a secondary
   "source ↗" link. The reader shows "Related in your corpus".
   **EXTENDED (ruled 2026-06-10): no bare "official source ↗" shortcuts
   ANYWHERE** — every such link opens a local popup page first (the database
   extraction: metadata + keywords) carrying a transparent outbound link
   whose visible text IS the full URL. Applies to every section.
   **FIRST TARGET SHIPPED (T16 slice 1, 2026-06-12):** Home-card external
   evidence now opens the LOCAL preview dialog (#link-preview) fed by
   /api/links/preview — known source, local copy (reader first), corpus
   citation count + examples, tracked law/wiki matches, local-copy keywords,
   "no network call" stated — with the outbound anchor's visible text = the
   FULL URL (clicking it still passes the invariant-#7 confirm; layered).
   Enforced in test_ui_invariants (#6e). REMAINING: the ANYWHERE sweep
   (reader source↗, search rows, markets/law/wiki tabs) onto the same
   openLinkPreview path.
7. **External links ALWAYS confirmed with a popup before opening** (ruled
   2026-06-10): capture-phase `_externalLinkGuard` in BOTH UIs; loopback
   exempt; message via `OOI18N.t`.
14. **Network toggle is AIRPLANE-MODE (ruled 2026-06-12, SHIPPED T2):** one
   constant plane glyph, FILL = state (filled = offline engaged); never ▶/⏸
   action glyphs. **REFINED #14d (§3, SHIPPED #139):** the button MOVED to the
   top bar and its text LABEL was DROPPED (icon-only; hover title + FILL convey
   state) — the glyph + FILL-painting + the consent popup are unchanged; the
   coachmark follows by getBoundingClientRect. Enforced in test_ui_invariants
   (#14: glyph + FILL `plane.setAttribute("fill"`), no longer the label. EVERY offline→online transition passes the ONE
   consent popup (`ensureOnline`): names the action, lists LOCAL interface
   IPs from kernel tables (NEVER a public-IP echo pre-consent), honest
   public-IP wording. Scheduler responses carry `online` → immediate repaint,
   never the 5 s poll. Gated: toggle, collect (start/run-now/first-run),
   markets/indices imports, wiki page add, dump start. Enforced in
   test_ui_invariants + tests/test_network_consent.py (incl. the
   socket-importer RATCHET: no new module may import requests/httpx).
   **REFINED #14c (UI_SHELL §3, SHIPPED #133):** the transition flash is now
   DIRECTION-AWARE — go-on = live accent, go-off = calm/grounded (never the old
   single red wash that conflated both meanings); consent/semantics unchanged.
   The button MOVE to the top bar + label-drop is deferred to the §2 redesign.
15. **A PERMANENT language switcher lives in the top bar (ruled, SHIPPED T7
   2026-06-12):** flag = visual convention ONLY, the NATIVE NAME is the
   identifier (flags ≠ languages); all 12 in one menu; one click switches the
   ENTIRE UI through THE i18n engine (OOI18N.setLang); Settings select stays
   in sync; constant footprint; RTL-aware placement. Enforced in
   test_ui_invariants (#15).
16. **ONE chart toolkit (`ooChart`), detailed-curves SYSTEMATIC (ruled
   2026-06-12; SHIPPED T8 slice 1):** full-resolution series always within
   the visible window — never downsampled/thinned; SPARSE series render as
   honest POINTS with n shown + the early-corpus caveat (a line only when
   density supports it, lineMin=8); wheel = cursor-anchored time zoom, drag
   = pan, hover/click = exact pinned X/Y readout, dblclick reset, legend
   chips toggle series; smart y-gridlines labelled via the shared formatter.
   Wired: markets symbol chart + insights trend (slice 1); commodity CARDS
   keep the static detailed SVG (tiny multiples; interactivity there is the
   enlarge path, later slice). Enforced in test_ui_invariants (#16).
   **AMENDED (ruled 2026-06-15; SHIPPED 2026-06-15 solo session, Item Y):** the sparse rule
   changed app-wide — **n<10 datapoints → a BAR graph** (replaced the dots treatment), n≥10 →
   the full-resolution line; the "early corpus … no curve interpolated through sparse points"
   caveat is **REMOVED app-wide — only n=x kept**; applied through BOTH `ooChart` + `dashChartSvg`
   via the shared `_SPARSE_BAR_MAX=10`. **BASELINE-HONESTY QUESTION RESOLVED (autonomous Class-B
   decision, per the maintainer's own leaning + "make all decisions"):** bars anchor to the plot
   baseline `Yof(yMin)` — which is **true ZERO for `zeroBase`/count series** and the **window-MIN
   for price-LEVEL series**, and the gridlines ALREADY LABEL that min, so a level difference stays
   visible and honest (NEVER a fabricated zero). A 2px **value-cap** is drawn at each bar's true
   value so a flush min / equal-value / single point stays VISIBLE (the cap marks the value, never
   an invented height — this resolves the degenerate-invisible-bar case a naive window-min impl
   would have regressed). Bar x-placement: TRUE time position in `ooChart` (real time axis with
   zoom/pan), date-tick-aligned `X(i)` in the tiny `dashChartSvg` cards. test #16 updated:
   asserts `_SPARSE_BAR_MAX` + `barMode` in both renderers + the sparse caveat string GONE.
17. **The universal hover-for-information convention (ruled 2026-06-12; the
   informed-consent instrument, SHIPPED same day):** every element carrying
   layered info (= anything with a translated `title`) is marked
   AUTOMATICALLY — dotted accent underline on text, tiny accent corner dot
   on buttons/pills/icons — and opens ONE shared styled bubble (`#oo-tip`)
   on hover, keyboard focus, or touch long-press. The bubble re-reads the
   live translated title, so it is ×12 by construction. One delegated
   listener + CSS only (no per-element handlers, no animation loops); a
   MutationObserver marks future surfaces, so the convention cannot be
   forgotten. Enforced in test_ui_invariants (#17).
18. **ONE universal subtab component (keystone #3, ruled 2026-06-13; SHIPPED
   2026-06-14):** the vertical-subtab grammar (lateral sidebar = main tabs,
   vertical subtabs near the top = facets) is driven by ONE reusable helper
   `ooSubtabs(nav, onSelect)` — a `<nav class="tabs">` of `data-tab` buttons; the
   component owns visible state (.active + role=tablist/tab + aria-selected +
   roving tabindex), keyboard nav (←/→/↑/↓/Home/End), click, and exposes
   {select,paint} for programmatic switching. NO inline onclick; labels are DOM
   text (auto-translated ×12); titled buttons inherit the #oo-tip convention.
   Reused on 3 surfaces at ship (Insights, Settings, the corpus window — the
   divergent data-ins/data-set/data-ctab impls are unified onto data-tab).
   Enforced in test_ui_invariants (#18). ADOPTERS so far: Insights, Settings,
   corpus window, Home families (#129), the task-manager window (#130). NEXT:
   Markets category tabs, the analysis window.
19. **HOME is content-first (SHIPPED #128/#129):** compact at-a-glance strip
   pinned at the TOP; no Quick actions; denser cards; card families as VERTICAL
   SUBTABS (ooSubtabs) with an "All cards" default lens + per-family hue accent.
   Enforced in test_ui_invariants (#19/#19b).
20. **The task-manager is a WINDOW, not a bubble (SHIPPED #130, slice 1):** the
   vitals popover is a wider tabbed window via ooSubtabs (now Active · Queue ·
   System; the live job controls + vitals reused unchanged). **ACTIVE/QUEUE
   SPLIT SHIPPED (slice 2, draft PR):** the jobs view is now two subtabs — Active
   (running pass, downloading dumps, the in-flight fetch, the idle loop,
   paused/failed downloads) and Queue (jobs waiting their turn = the
   single-download wiki-dump queue, in `queue_position` order, with its existing
   ↑/↓ reorder controls POSTing the unchanged /api/jobs/dumps/reorder). ONE
   shared `_jobRow` renderer feeds both panels so the controls (Stop=kill switch,
   Pause/Cancel, reorder) stay identical; no new backend; no fabricated ETA/rate
   (only the real byte progress the owner reports); honest empty states ×12.
   **SCHEDULE SUBTAB SHIPPED (slice 3, draft PR):** a 4th subtab (`#tm-schedule`
   / `#sched-tm-body`, `data-tab="schedule"` via ooSubtabs) surfaces the REAL
   scheduler facts — state (running/idle/stopped), current-pass progress (DOMAIN
   only, never a URL), cadence (continuous vs interval_minutes), last run, and
   the backend's OWN next_run timestamp shown as honest relative time with the
   method (last run + inter-pass gap) in the #oo-tip hover, NEVER a fabricated
   countdown. `_renderSchedule` reuses the `_actData` the window ALREADY polls
   from /api/scheduler/activity (no new endpoint, no extra poll; only while the
   window is open); honest empty state ×12; +20 strings ×12. Enforced in
   test_ui_invariants (#20 + #20b + #20c). PER-JOB CONTROLS EXTENDED (Item 2,
   SHIPPED 2026-06-16, conservative/browser-unverified): the ONE `_jobRow`
   renderer now serves BOTH bulk-download kinds — OSM-region downloads gained the
   wiki-dump control grammar (pause/↑↓-reorder/cancel) and EVERY paused/failed
   download (wiki + OSM) gained a RESUME button. Reorder is kind-aware
   (`_reorderEndpoint`: /api/jobs/dumps/reorder vs /osm/reorder — each manager
   owns its queue; `queuedKeysByKind` so ↑↓ never crosses kinds). Resume =
   `jobResume(id)` → ensureOnline (invariant #14, a resume re-opens a fetch) →
   POST `/api/jobs/{id}/resume`; backend `_dl_actions` makes paused/failed offer
   `["resume"]` (a re-cancel would 404 on the owner — permanent delete stays in
   Settings, as the cancel detail says), routed to new `DumpDownloadManager.resume`
   / `OsmDownloadManager.resume` (both call start() to continue the partial file).
   +2 strings ×12 (Resume a paused download · Resumed.); test_ui_invariants #20d +
   tests/test_jobs_resume.py. REMAINING: History; per-job RATE/ETA/bandwidth-cap —
   DELIBERATELY omitted (the owners report only bytes/percent, NOT a rate; an
   honest rate needs owner-measured bytes-over-time in the manager — never a
   client-side guess across the adaptive poll; the cap needs a backend that
   supports throttling, which it does not yet).
21. **INSIGHTS auto-indexes; no "Index corpus" button (UI_SHELL §6, SHIPPED
   #132):** indexing follows ingest (the index_article hook) + a SILENT
   background top-up (`autoIndexInsights`) clears any legacy backlog when
   Insights opens (the "N to index" count ticks to 0 on its own); the button +
   its palette action are removed. Insights sections were already subtabs (#127).
   Enforced in test_ui_invariants (#21).
23. **BRIEFING CAVEATS ARE VISIBLE BY DEFAULT (audit PR A, 2026-06-15 — enforces
   the permanent informed-consent non-negotiable; resolves a REGRESSION):** every
   Home briefing card renders `c.caveat` inline in a visible `.card-caveat` line
   under the summary — NEVER behind the "Show method" toggle. The toggle (`#brief-methods`,
   was "Show method & caveat") now gates ONLY the verbose Method/math (`.mc`); the
   caveat left the toggle-gated block entirely. Caveat text uses a theme-aware
   `var(--caveat)` (dark `#eab44e` / light `#8a4d0a`) that clears WCAG AA 4.5:1 on
   EVERY panel of all 17 themes (the old hardcoded `#c98a1b` failed 8/17, `#b45309`
   failed 17/17 — verified by contrast math); the corpus-tier early caveat + the
   custody OTS warning adopt the same variable. Label/title re-keyed ×12. Enforced
   in test_ui_invariants (#23): the caveat must render in `.card-caveat` and must NOT
   appear inside the `hidden` `.mc` block.
30. **ALTERNATIVE-INTERFACES "GUIs" GALLERY (ruled 2026-06-17; BUILT 2026-06-17 on
   branch `claude/exciting-lovelace-1gyszi`, draft PR, BROWSER-UNVERIFIED):** a SANDBOX
   gallery of EIGHT opt-in alternative interfaces in Settings → GUIs (subtab
   `data-tab="guis"` / `#set-guis`, host `#guis-gallery`), switchable LIVE (persist
   `oo.ui.gui` + reload). Maintainer decisions (AskUserQuestion 2026-06-17): (a)
   SHARED-CORE SHELLS — each interface is a scoped skin `html[data-ui="<id>"]` (+ thin JS
   for the 2 Alpine ones) reusing the ONE `app.js` id-targeted render logic, so NO
   functionality is lost and the default `index.html`/`app.js`/`app.css` stay the GUARDED
   reference + default (additive hooks ONLY: a `<head>` boot `<script>`, the Settings
   subtab button+panel, a `showSetCat` case, the gallery `<script>`); (b) SANDBOX latitude
   — structural invariants relaxed for the gallery, BUT the ETHICAL non-negotiables are
   preserved BY CONSTRUCTION (same DOM): caveats visible, the ONE network-consent popup,
   no scores, deduced/never-confirmed labels; (c) TECH = 6 vanilla CSS skins + 2 Alpine
   (Command, Canvas), Alpine v3.14.1 VENDORED locally (`src/static/guis/vendor/`, MIT,
   sha256-pinned, ZERO network — never a CDN; extracted from the npm tarball since CDNs
   were 403 here). THE 8: Aurora (calm/progressive-disclosure) · Atlas (top-nav
   dashboard) · Command (keyboard launcher) · Field (mobile bottom-bar stream) · Focus
   (zen reader, hover-expand rail) · Terminal (mono density) · Canvas (pan/zoom node
   board) · Editorial (serif magazine). Skins INHERIT the active theme palette (17 themes
   × 8 skins all work). +20 i18n keys ×12 (chrome/buttons/9 taglines/honesty-note/lead
   translated; the long per-UI "why" essays are English in-app, full critical rationale in
   `docs/product/GUI_ALTERNATIVES.md`; non-en AI-drafted, flagged for native review; i18n
   --min 100 green). Enforced in test_ui_invariants (#30 = the additive wiring) +
   `tests/test_gui_alternatives.py` (registry=8, assets exist, NO skin hides a
   caveat/consent surface, no outbound URL in gallery files, Alpine checksum pinned +
   local-only, EVERY skin rule scoped to its `data-ui`, gallery uses addEventListener not
   inline onclick). VERIFIED here: node --check (all JS), i18n gate, the 2 test files +
   test_ui_invariants (direct-run, py3.11). NOT runnable here: full pytest (repo requires
   py3.13; container is 3.11) → CI covers it. REMAINING: human click-through across
   themes/breakpoints (fork-3); optional real-screenshot thumbnails; translate the per-UI
   "why" essays if promoted past experimental.
8. **The UI shows DATA, never plumbing (ruled 2026-06-11, stated GENERALLY):**
   data tabs present the aggregated data itself — "that's the added value of
   this app"; acquisition/configuration surfaces live in Settings. First
   applied: Agenda (invariant #13 in test_ui_invariants). Apply to every
   surface reworked from now on.
- **Home must never go blank-and-silent**: fail-safe producer registration;
  zero cards renders the explanatory empty state — never an empty div.
- **Naming:** app-opened browser tabs are suffixed "· FOOS" (Free Open
  OmniScience), explained in Help + USER_MANUAL; a proper rename is expected
  later — keep the suffix mechanism centralized enough to swap in one pass.
- **TEMPORARY field-test mode (REMOVE when the live-test cycle ends):**
  `src/monitoring/field_test.py` (default ON, `OO_FIELD_TEST=0` opts out)
  auto-exercises fetch surfaces inside the operator's collect passes; verbatim
  outcomes in `data/field_test.jsonl`; local-only, shared only by click.
- **Units/precision principle (ruled 2026-06-10, APP-WIDE):** one shared smart
  formatter — sensible significant digits scaled to magnitude, unit-aware;
  never raw float tails. **PLUS: the entire app prioritizes scientific/SI
  metric units** — never imperial; convert for display, keep the original in
  provenance.
- **Detailed curves are SYSTEMATIC, app-wide (ruled 2026-06-12):** every chart
  on every surface renders the FULL-RESOLUTION series — no arbitrary
  downsampling anywhere ("this is rich data, leverage it"). COROLLARY: sparse
  series render honestly — POINTS/bars with n shown + early-corpus caveat; a
  line only when density supports it; NEVER interpolation faking a curve
  through 3 points; binning only when supported and always labeled. One chart
  toolkit enforces both rules everywhere.
- **Mind-map rules (ruled 2026-06-11, shipped):** centre → arms → always
  outward; deterministic radial tree, no cross-tangle; the cloud is a SECOND
  view; date-spectrum control + ⛶ Enlarge + text-size slider stay.
- **In-map overlay controls** (the Google-Maps "inside the map" principle) —
  apply to future map-like surfaces.

## Session rituals
- Verify with BOTH venv profiles when deps change; `pytest -q` full suite must
  stay green; mypy ratchet ≤ baseline in CI; `node --check` every `<script>`
  block after UI edits; locale files must stay 100% (scripts/i18n_report.py)
  when adding chrome strings (12 languages, Arabic is RTL).
- Maintainer merges PRs fast: after `git push`, if the output says
  "[new branch]", the previous PR was merged — open a NEW PR onto `0.09`.
  COROLLARY (near-miss 2026-06-15): local `origin/0.09` goes STALE within
  minutes given the fast merges — ALWAYS `git fetch origin 0.09` immediately
  before `git checkout -B <branch> origin/0.09`, or a doc/ledger branch can be
  cut from a pre-merge base and a 3-way merge could drop a just-merged ledger
  edit on the same lines. (Caught when a finding-F ledger update branched from a
  stale 0.09 and the entry was missing; re-cut from a freshly-fetched 0.09.)
- Never use backticks inside `git commit -m` heredocs (shell substitution).
- Update `docs/product/RELEASE_0.1_RC_GATE.md` rows you close, every session.
- Lessons that cost a bug: duplicate top-level JS function names silently
  override — grep before declaring. Sizes lie, diffs don't (`git diff
  --numstat` before fearing loss). Agent findings get hand-re-verified before
  shipping (the 06-audit false-positive lesson). Tests must NEVER assert
  POSITIVE facts against the shared mutable `src.api.main.app` singleton's
  `.routes` — that process-global read made the additive-restore guard flaky in
  CI (1 failed on `/v2/restore` absent, never reproducible locally even per a
  full-suite per-test route watcher); anchor route guards to IMMUTABLE sources
  (each router's own `router.routes` definitions + the `include_router` wiring
  in `src/api/main.py` source). Negative `not in app.routes` checks stay safe (a
  missing route can't fail them).

## Open queue (when maintainer says proceed)
- **LLM-ASSISTED PERCEPTION — who/where/when extraction + sentiment + an eval harness
  (maintainer brainstorm 2026-06-18; EVALUATION, reconciliation pending the maintainer's
  PARALLEL internet research; full record in `docs/FUTURE_DEVELOPMENTS.md` →
  "LLM-assisted PERCEPTION"):** DOCTRINE = LLM for PERCEPTION (extract/disambiguate/translate,
  locally-checkable + validatable, stored as confirmable CANDIDATES in the AI layer) NEVER
  JUDGMENT (grade/rank/decide-worth); measure on the SHIPPED small model, never assume
  frontier quality. AGREED (maintainer-ruled): LLM who/where/when scope = dates + places +
  WHO (persons AND orgs — "the DOJ is a who"), explicitly NO "what"/events; build it AFTER an
  EVAL-FIRST harness (synthetic difficulty-tiered + phenomenon-tagged set ×12 langs with
  ar/zh/ja/hi/bn gold flagged needs-native, PLUS a real-article set; score precision/recall/
  HALLUCINATION per language/tier/phenomenon vs the rule-based baseline; deterministic; LLM
  place-string vs gazetteer-coordinate scored apart; de-US-centring bias measured per-stratum)
  — the same harness becomes task 2 for sentiment-vs-VADER. OPEN (not approved): LLM-as-grader
  (leaning AGAINST a composite grade; reframe to a descriptive substance lens + an LLM-free
  source-behaviour profile); fact→SVO→novelty (SVO-aggregation rejected; reframe to attributed
  claims + embeddings, mind negation); sentiment classifier choice (deep-research done — XLM-R
  ONNX-safe, mDeBERTa ONNX-broken, per-language gating, validate on news, or pivot to
  subjectivity/loaded-language feeding the manipulation cards). Implementation reuses the
  ai_layer store (#330/#332); nothing built this session beyond capturing the evaluation.
- **MAINTAINER BATCH RULINGS 2026-06-17 (answered the next-session question list; binding —
  these set priorities + override several earlier defaults):**
  (1) **PIVOT TO RELEASE-ENGINEERING** — the next push leads with the RC-BLOCKING release-eng
  set toward a taggable V0.1, not more breadth-features.
  (2) **HOLD the version flip** (0.0.9→0.1) until every RC-BLOCKING row is ✅; do the
  grep-able single-source plumbing now.
  (3) **CONVERGENCE WATCH ENGINE = build it, ON BY DEFAULT** (overrides the earlier
  off-by-default lean): saved local conditions → a Lead card on match + a Watches panel
  (history, per-watch enable/edit/delete); local-only, NO notifications/network/telemetry,
  NO escalation tiers beyond the Lead card; the engine is enabled by default.
  (4) **APP SELF-UPDATE = MANUAL, user-driven, GIT-PULL based; NO signing key yet** (mark
  "use signing keys" for FUTURE_DEVELOPMENTS). Build snapshot→verify→staged-migrate→
  atomic-swap→rollback mechanics, user-initiated (manual "check/update"), no auto-check.
  (5) **WIN/MAC INSTALL IS NOT BLOCKING — focus DEBIAN for now** (de-scopes the win/mac
  install-path + CI-required-lane rows from RC-BLOCKING; Debian is the V0.1 target).
  (6) **TWO-WINDOWS CONSOLIDATION = PROCEED** (route openCorpus → the #an flagship, retire
  the #corpus-win modal; conservative + flagged, browser-unverified).
  (7) **UI RETHINK = BUILD IT, INCLUDING THE 3D KEYWORD EXPLORER** (do NOT defer the 3D;
  maintainer is eager to test) — nav-to-top facet strip + Home→dashboard + the hand-rolled
  canvas-2.5D/CSS-3D explorer (no Three.js), conservative + flagged.
  (8) **i18n LONG-TAIL = PROCEED** — key + AI-draft-translate ×12 the remaining ~400
  untranslatable chrome strings (flagged for native review) toward --audit-chrome→0.
  (9) **RELIGIOUS CALENDARS / ECLIPSE CANON = maintainer will PROVIDE the dates to preload;
  NOT blocking — mark a later TODO** (never fabricate dates meanwhile).
  (10) **OLLAMA BINARY INSTALLER = undecided — mark a later TODO** (the shipped pull/remove/
  active-model UI stays; the binary-install half waits).
  (11) **LIVE EMAIL INGESTION (POP3/IMAP) = BUILD IT — do NOT defer; maintainer wants to TEST
  it and finds manual .eml ingestion too slow.** REVERSES the "local-.eml-only / IMAP-blocked"
  stance: build live mailbox ingestion REUSING the anonymize-at-ingest core (recipient-free,
  no raw-.eml retention, tracking-link detox, the ONE consent + a visible job, kill-switch).
  The no-recovery-of-personal-data contingency is consciously RE-OPENED and accepted by the
  maintainer for testing; keep the anonymize-at-ingest guarantees that resolved it for .eml.
  **SHIPPED 2026-06-17 (backend VERIFIED py3.13):** found a PARTIAL pre-existing fetch_imap with
  a real SECURITY GAP (no kill-switch gate) and closed it — src/ingest/email.py fetch_imap is now
  AIRPLANE-gated (refuses up front → NO socket offline even with an injected conn) + logs out in a
  finally; added fetch_pop3 (same guards) + fetch_mailbox(protocol) + port. Reuses ingest_emails
  (recipient never stored, no raw retention, tracking-link detox, never-fetch). API: the existing
  IMAP endpoint returns 409 under airplane; NEW POST /api/newsletters/mailbox (IMAP+POP3) stores
  under a DEDICATED disabled filterable "mailbox.import.local" source (live-vs-file provenance
  separable), 409 offline / 502 transport, returns the anonymise tally + honest disclosure (TLS to
  provider, IP visible, NOT via Tor, creds not stored). imaplib/poplib stdlib → socket-importer
  ratchet intact. Frontend: a "Pull from a mailbox" form in Settings → Newsletters (ensureOnline #14
  + visible disclosure, browser-unverified). tests/test_mailbox_ingest.py (6, incl. airplane-opens-
  no-socket + endpoint-stores-anonymised) + test_repo_invariants. REMAINING: a visible task-manager
  job over a long pull; per-publisher source resolution; stored/encrypted credentials for repeat pulls.
  (12) **STATS FIGURES = keep user-initiated AND add SCHEDULED AUTO-REFRESH of vintages** (a
  periodic re-fetch of tracked figures, new vintage each time; consented/airplane-gated).
  (13) **DESIGN-ONLY VERTICALS = PROCEED with them** (elections/civic + the 9 manipulation-
  pattern cards): start building, no longer deferred.
  **CARD #6 SOURCE-LAUNDERING SHIPPED 2026-06-17 (the ledger's recommended first card, backend
  VERIFIED py3.13):** src/analytics/laundering.py:find_source_laundering — origins cited by many
  DISTINCT sources (the independence measure, NOT article count) = apparent corroboration tracing
  to ONE origin; reads article_links (citation graph, not text); social/storefront origins excluded
  (is_social/is_commerce noise filter); NO score; the INNOCENT explanation (a widely-cited primary
  source looks identical) stated beside the pattern; returns the exact citing-article set. A
  source_laundering PRODUCER (bucket="overtold", passes the no-score Card schema, _trigger) auto-
  surfaces it as a Home Lead via run_all; GET /api/insights/source-laundering for exploration.
  tests/test_source_laundering.py (5: fires on distinct sources, one-chatty-source-can't-launder,
  social/commerce excluded, both gates, endpoint).
  **CARD RECYCLED-CLAIM SHIPPED 2026-06-17 (the 2nd card, backend VERIFIED py3.13 — chosen for its
  CLEAN deterministic signal over the design-heavy NLP cards):** src/analytics/recycled_claim.py:
  find_recycled_claims — a RECENT article near-identical to a MUCH OLDER one = a claim resurfacing
  after dormancy. Reuses the proven near_duplicate_clusters PRIMITIVE (MinHash+LSH, high-precision,
  NOT fuzzy NLP) so it's honest+testable, and is DISTINCT from echo_chamber (near-dup in a SHORT
  window = coordination) by requiring a LARGE dormancy gap. HONESTY: the trigger is a measured time
  GAP (days between oldest+newest member), never a score; a cluster only fires when a member is RECENT
  (a CURRENT resurfacing, not two equally-old dups); a single source recycling its own evergreen is
  surfaced but FLAGGED single_source; the scan is BOUNDED (recent pool + older pool, both capped,
  stated in method); innocent explanations (anniversary/evergreen-rerun/wire-republish) stated beside
  the pattern. A recycled_claim PRODUCER (bucket="watch", no-score schema, _trigger) auto-surfaces it
  as a Home Lead; GET /api/insights/recycled-claims for exploration. tests/test_recycled_claim.py (6:
  fires on recent-dup-of-old, short-gap-isn't-recycled, two-old-without-recent-doesn't-fire,
  single-source-flagged, unrelated-text-no-cluster, endpoint). REMAINING: the other 6 cards
  (astroturf/copypasta partly covered by echo_chamber; headline-body-mismatch, outrage-intensity,
  flood/bury, manufactured-emergence, event-timed-op still to build); the elections/civic vertical.
  SEQUENCING: (1) is the lead. Record-only here; build across stacked PRs onto 0.09.
- **AUTONOMOUS 'EVERYTHING' BATCH (ruled 2026-06-16) — the V0.1-alpha push, run
  UNSUPERVISED.** SCOPE = the V0.1 RC mandate IN FULL ('absolutely everything' from
  this ledger + FUTURE_DEVELOPMENTS): every RC-BLOCKING + SHOULD + POST row in
  docs/product/RELEASE_0.1_RC_GATE.md + docs/product/BACKLOG_GROUPED.md, PLUS the
  promotions below. SOURCE OF TRUTH = those two docs + this ledger; NO new taxonomy
  (any earlier 'T1–T17' framing is RETIRED). WORKING MODE: one PR per slice, small +
  ADDITIVE, DRAFT onto 0.09, CI subscribed, branches STACKED (accumulate; rebase on a
  freshly-fetched 0.09 as bottoms merge). MERGE POLICY (fork-4): the MAINTAINER MERGES
  EVERYTHING — nothing self-merges, every PR stays a draft (the human review gate
  stays). Skip-and-note ONLY a genuine maintainer-ruling gate (residual set below);
  security-sensitivity is NOT a skip trigger — build exec/elevation FULLY with consent
  + a VISIBLE elevation step + verify-before-exec through the guarded factory + tests.
  PROMOTIONS (design-only/POST → ACTIVE): (a) the UI RETHINK is the CENTERPIECE (entry
  below, header amended; #an↔#corpus consolidation now in scope, reader standalone per
  fork-1); (b) in-app Ollama installer + a model-management Settings SUBTAB; (c) GUI
  self-update — gated snapshot→verify→staged-migrate→atomic-swap→rollback MECHANICS
  only, default OFF; (d) NEW GEO/OFFLINE MAPPING — an OSM per-region download manager
  (managed like wiki dumps: own task-manager job, files/no DB-writer contention,
  parallel, reorderable queue, rate/%/ETA/pause/resume/cap, inline DATED size table +
  one consented refresh) [CATALOG + DOWNLOAD-MANAGER BACKEND SHIPPED 2026-06-16:
  src/geo/osm_regions.py + src/geo/osm_downloads.py (OsmDownloadManager mirrors
  wiki.dumps, guarded-fetch + Tor circuit isolation + kill switch) + GET/POST
  /api/geo/regions|downloads; SETTINGS FRONTEND SHIPPED 2026-06-16 (Settings → Offline
  map subtab: region picker + resumable download-job table, start gated by ensureOnline
  #14, +9 i18n ×12, test #27); OSM downloads SURFACE IN /api/jobs 2026-06-16 (_osm_jobs
  + osm: cancel + /api/jobs/osm/reorder, tests/test_osm_jobs.py); PER-JOB UI CONTROLS
  SHIPPED 2026-06-16 (Item 2): the task-manager `_jobRow` now renders pause/↑↓-reorder/
  cancel + RESUME for OSM downloads (kind-aware reorder; resume gated by ensureOnline) —
  see the #20 ledger entry. REMAINING: per-job RATE/ETA + bandwidth CAP (deferred —
  owners report bytes/percent only, not a rate; needs owner-measured bytes-over-time +
  a throttling backend, never a client-side guess)] + a HAND-ROLLED lightweight offline vector map (canvas 2.5D /
  CSS-3D, NO WebGL/Three.js; reuse the bundled Natural-Earth coastline) + the
  temporal-map remainder (linear/log toggle; mention layer fed by event-places); (e)
  NEW OFFICIAL-STATISTICS INGESTION (the FUTURE_DEVELOPMENTS design — gov +
  international agencies as CONTROVERSIAL sources; producing-state + agency + pub-date +
  methodology-ref per figure; VINTAGES; comparability guards SA/NSA/base-year; SDMX/API
  before scraping; triangulate never average; forecasts join IPCC-tracking;
  per-continent coverage; deliberately BRICS/Africa/forgotten-region) [CATALOG SUBSTRATE
  + INGEST-AS-SOURCES SHIPPED 2026-06-16: src/stats/agencies.py + src/stats/ingest.py
  (ingest_agencies_as_sources → DISABLED controversial Sources, idempotent, no
  fabricated score) + GET /api/stats/agencies + POST /api/stats/sources/ingest + a Settings →
  Statistics SUBTAB (descriptive directory + register-as-sources button, home URLs via
  extLink #6, +19 i18n ×12, shipped 2026-06-16); SDMX/WORLD-BANK PARSER CORE SHIPPED
  2026-06-16 (Item 5, offline/fixture-tested): src/stats/sdmx.py = a PURE network-free
  parser — parse_worldbank (WB API v2 JSON) + parse_sdmx_json (SDMX-JSON 2.1, Eurostat/IMF,
  resolves dimension index paths → ref_area/indicator/time_period + unit/adjustment/base_year
  only-when-stated) → provenance-rich StatFigure; NO score, never averages, extracted_at =
  caller-stamped vintage, published gap → value=None (Eurostat ':' too); tests/test_sdmx_parse.py
  (9). LIVE FETCH CLIENT SHIPPED 2026-06-16 (Item 5, fixture-tested): src/stats/fetch.py = the
  ONLY networked stats layer — worldbank_url/eurostat_url builders + fetch_worldbank/
  fetch_eurostat that GET through guarded_session (kill switch + Tor proxy, transport never
  downgraded; per-URL circuit isolation), REFUSE up front while airplane mode is engaged, and
  DELEGATE all parsing to sdmx.py (no robots here — documented API endpoints follow their own
  etiquette). Injectable getter → network-free tests incl. a kill-switch test proving NO socket
  is attempted offline (tests/test_stats_fetch.py, 11). see BACKLOG Group N. FIGURE LAYER
  SHIPPED 2026-06-17 (backend, fully tested py3.13): StatFigure DB model + migration
  f5a6b7c8d9e0 (VINTAGED — a re-fetch at a later extracted_at is a NEW row never an overwrite;
  gaps stored NULL; NO score column) + src/stats/store.py (store_figures idempotent-per-vintage
  + gap tally, list_figures filterable latest-or-history, vintages_for the revision trail,
  triangulate producers SIDE BY SIDE never averaged + flags incomparable unit/SA-NSA/base-year;
  cross-agency series equivalence NOT inferred) + API (POST /api/stats/figures/fetch = the ONE
  networked stats action: refuses up front under airplane mode 409, guarded factory, transport
  never downgraded, single-writer gate, degrades loudly; GET /figures, /figures/vintages,
  /triangulate, /sources). tests/test_stats_store.py (6) + tests/test_stats_figures_api.py (5:
  kill-switch refusal proven with NO socket). REMAINING: a visible task-manager job over a LONG
  fetch (the synchronous endpoint suffices for bounded indicator pulls). FIGURES FRONTEND
  SHIPPED 2026-06-17 (Settings → Statistics: consented fetch + vintaged table + triangulation,
  browser-unverified). SCHEDULED VINTAGE AUTO-REFRESH SHIPPED 2026-06-17 (ruling #12): a
  StatSubscription model + migration c9d0e1f2a3b4 records every user fetch; src/stats/
  subscriptions.py replays DUE subscriptions (freshness-gated interval_days default 30,
  AIRPLANE-gated → no socket offline, best-effort per sub) storing a NEW vintage each time;
  wired into the scheduler markets pass + the fetch endpoint records subscriptions; API
  /api/stats/subscriptions (list/PATCH/DELETE/refresh) + a Settings "Tracked for auto-refresh"
  panel. tests/test_stat_subscriptions.py (5) + the fetch-records-a-subscription API test].
  THE FOUR FORKS
  (ruled 2026-06-16): (1) the offline READER stays STANDALONE (not folded into #an);
  (2) the convergence WATCH engine = the FULL 'Watches view + history' UX (saved local
  conditions → a Lead card on match + a dedicated Watches panel: history +
  per-watch enable/edit/delete; off by default, local-only, NO notifications/network/
  telemetry); (3) browser-unverifiable UI ships CONSERVATIVE + FLAGGED (node-check +
  extend test_ui_invariants + defensive states; 'browser-unverified, needs
  click-through'; no headless harness, no dark flag); (4) the maintainer merges
  everything. DEFAULTS (override anytime): self-update = MECHANICS ONLY (a fully
  verified auto-updater needs a maintainer-supplied trust root/signing key — its 5 open
  questions stay a ruling); the RULING-HEAVY design-only verticals (elections/civic,
  in-app Tor/Stem, voice mode, two-hop keyword graphs, autonomous onboarding) stay
  DEFERRED (each needs its own design session); Open Commons Mirror = a separate SISTER
  PROJECT (new repo, only when mature), NOT this session's work. DRIFT RECONCILED: both
  honesty bugs CLOSED (airplane-paused→red #245; back-button fixed — Group K,
  tests/test_back_button_nav); Reader-tabs SLICE 1 shipped STANDALONE (#246:
  Read/Keywords/Sentiment/Related/Links — REMAINING: a Mindmap tab via /api/insights/
  graph article_ids + a richer Source/WWW tab); exact-article-id card seeding
  (#241/#242), .eml importer (#237), convergence endpoint /api/insights/convergences
  (#231) all merged; Item Y (n<10→bars) SHIPPED app-wide (the RC-gate row was stale).
  RESIDUAL SKIP-SET (genuine rulings — note, don't build): self-update's 5 open Qs;
  'stays on this machine' exact wording (default applied); CI win/mac
  graduate-to-REQUIRED + signing/notarization; the deferred verticals above; any
  watch-engine escalation to push/'urgent' alert tiers beyond the local Lead-card +
  Watches view.
- **ELECTIONS & CIVIC VERTICAL + POLL ANALYSIS + MANIPULATION-PATTERN CARD
  MODELS (maintainer design session 2026-06-15; DESIGN-ONLY, not built — full
  design + the nine card maths in `docs/FUTURE_DEVELOPMENTS.md`):** elections as
  the everyday-person civic flagship, built as a COMPOSITION of existing substrate
  (agenda dates + WWW + corpora + links/lineage + source-competitive) + a curated
  data layer. THREE binding framing INVERSIONS: (1) never "politically neutral" →
  plural & transparent about the app's OWN bias (audit §5; "Your lens"/A3 on the
  election corpus); (2) never "voting implications" → evidence trails the user
  navigates (Claim Workspace A1); LLM-less = the ASSET (no generated slant); (3)
  never "detect candidates/sentiment/momentum" → curated SOURCED scaffolding +
  descriptive caveated analytics — NO horse-race number, NO auto-detected
  candidates, NO per-candidate sentiment verdict, NO poll-of-polls forecast.
  "Name the shape, never prescribe it" (no honest baseline exists for candidate
  coverage). Candidate roster = the two-class deduced/confirmed model (status
  presumed/declared/official/withdrawn/disqualified + provenance; captured
  commissions are ONE claim, never ground truth). FIRST SLICE (lowest risk): a
  sourced `elections` calendar in world_events.yml (France 2027 pilot;
  confirmed:false + official_url for movable dates; subscribable tag query).
  Scenario card #10 "election-integrity desk" → DROP the "integrity" branding,
  keep the capability via the general claim-provenance/single-origin tooling.
  POLL ANALYSIS = audit METHOD (near-neutral; survey science, not values), never
  RESULTS; a TIER STACK — build Tier 2 FIRST (transparency CHECKLIST, never a
  score, + verbatim question/answer-STRUCTURE display when data allows = the
  language-agnostic FACT that is the strongest+safest signal); Tier 4
  (tie-reported-as-lead) later (points at journalists; needs Tier-2 credibility +
  the same extractor). RULES: no composite poll score; NON-DISCLOSURE always
  outranks disclosed-imperfection (opacity disqualifies, never disclosed-ugliness
  — else we punish transparency); never LABEL "useless", surface a glanceable
  disclosure FLOOR + let the user conclude; per-language caveat on anything
  semantic; a poll is an INSTANCE of the official-statistics pattern.
  MANIPULATION-PATTERN CARDS = detect STRUCTURE, never deception/intent/truth
  (labeling = a censorship engine; AI-free is the ETHICAL ASSET; neutrality =
  structural INVARIANCE + a self-audited flag distribution). SHARED SPINE:
  effective-independent-origins r (not article count n); Benjamini–Hochberg FDR
  over the daily scan; surprise vs the corpus's OWN baseline (Poisson/z/surprisal
  + Wilson CIs); convergence = an AND GATE, not a multiplied probability. NINE
  card models (astroturf · copypasta · manufactured-emergence · flood/bury ·
  recycled-claim · source-laundering · headline-body-mismatch · outrage-intensity
  · event-timed-op), each a new PRODUCER feeding EXISTING buckets, signal carries
  COMPONENTS never a blend (passes assert_no_score_fields). FP/FN discipline =
  precision-biased SURFACING + full-recall EXPLORATION; innocent-explanation shown
  beside the pattern; "absence of a flag ≠ absence of manipulation" on every
  producer; a microscope, never a detector. BUILD ORDER: card #6 (citation graph)
  + #1 (near-dup) first (primitives already in src/signals/). OPEN (maintainer
  "not sure"): Tier-4 lean; ever say "push poll" vs describe the mechanic; whether
  to answer "who's winning" more directly. The everyday-person PARADOX recorded:
  the honest tool withholds the simple answer that audience wants ⇒ CHANGE THE
  PROMISE to "read the coverage yourself + catch the manipulation aimed at you".
- **SESSION WORKING MODE (ruled 2026-06-12, this session):** reality-check the
  docs↔code gap, organize ALL open work into TOPICS (T1 performance … T20
  release-eng; the full plan lives in the session log + PR descriptions), then
  execute topic-by-topic — **ONE PR PER TOPIC**, draft onto `0.09`, CI
  subscribed, autonomously; ask only when a genuine ruling is needed.
  **AUTONOMY REINFORCED (maintainer ruled 2026-06-15, verbatim "Choose
  autonomously. Always choose autonomously, this is not important"): do NOT ask
  which direction/area/topic comes next — that is NOT a genuine ruling, CHOOSE IT
  YOURSELF and proceed. Reserve AskUserQuestion strictly for genuine rulings
  (ambiguous architecture, ethics/security trade-offs, irreversible/outward-facing
  actions). Sequencing/prioritization across the queue is mine to decide.**
  Reality-check verdict recorded: the ledger and RC gate are ACCURATE (1118
  tests collected as of 2026-06-14; 28 gap claims verified in code; no shipped
  claim found false).
- **V0.1 ALPHA RC MANDATE (ruled 2026-06-11): "absolutely everything" from
  this ledger + FUTURE_DEVELOPMENTS built into 0.09 before the V0.1 alpha RC;
  Windows+macOS installs TESTED; docs↔app reciprocity; security impeccable;
  ethics reflected in the software; UX guaranteed.** Honest answer recorded:
  NO — the complete CHECKABLE inventory is `docs/product/RELEASE_0.1_RC_GATE.md`
  (status + acceptance check + RC-BLOCKING/SHOULD/POST per item + recommended
  order; estimate 8–12 dedicated sessions for the BLOCKING set). V0.1 tags
  ONLY when every RC-BLOCKING row is ✅. The 3-OS CI matrix is live (win/mac
  observation lanes graduate to REQUIRED when green — "the matrix IS the
  definition of supported"); the sqlcipher3 smoke job is BLOCKING and green
  on all three OSes.
- **PERFORMANCE — REMAINING (batch T1 SHIPPED 2026-06-12, see batch log):**
  THREADING honesty recorded: the app IS multi-threaded (scheduler + API;
  SQLite C core + lxml release the GIL) but pure-Python work serializes —
  worker PROCESSES only if cheap wins prove insufficient (they proved
  SUFFICIENT for the reported scale); single-writer SQLite stays the design.
  EMPIRICAL FACTS not to relearn: a SQL join from keyword_mentions to
  articles for ONE small column drags whole 35 KB article rows through the
  SQLCipher codec (column order puts content before language) — measured 26 s
  of a 32 s wall; read small denormalisable facts via covering indexes or a
  one-pass Python map instead. FastAPI JSONResponse uses COMPACT JSON
  separators — streamed JSON must pass separators=(",",":") for byte parity.
- **RESTORE IS ADDITIVE-ONLY (ruled 2026-06-13, field session):** restoring a
  backup must NEVER replace the corpus — it ALWAYS complements it additively,
  duplicate-lessly (the v2 merge engine's exact behaviour: nothing replaced or
  deleted, bit-for-bit dedup, conflicts keep local + report both). The LEGACY
  replace-restore path must be REMOVED/made unreachable (not merely demoted) so
  no flow can ever overwrite the corpus; the merge is the ONLY restore. (The
  chrome still showed legacy "replace your current corpus with the uploaded
  file" wording — retire it.) Crown test already forbids silent decrypt across
  restore; extend the absorption/guard so no replace path survives.
- **BACKUPS MUST INCLUDE DOWNLOADED WIKIPEDIA DUMPS (ruled 2026-06-13, maintainer
  — REVERSES design D3):** a backup must carry the offline Wikipedia downloads
  (`data_dir()/wiki_dumps/`) so a restoring user NEVER has to re-download an
  entire Wikipedia library (multi-GB to tens of GB, painful over Tor). Today
  these are DELIBERATELY EXCLUDED from oo-backup-2 (D3, "re-downloadable", listed
  in `_excluded_inventory()` at src/backup/artifact.py) — that exclusion is now
  overruled: include them. MARKED FOR FUTURE DEVELOPMENTS (not implemented this
  session, per the maintainer's "implement now or mark it").
  **SIBLING REQUEST — BACKUPS SHOULD OPTIONALLY INCLUDE LLM MODELS (maintainer asked
  2026-06-17 "whether the backup integrates LLM models; there should be an option to
  integrate it to avoid re-downloading models"):** ANSWERED — TODAY IT DOES NOT.
  oo-backup-2 snapshots only `data_dir()` contents (corpus.db, custody, state/log
  files, annotations, encrypted keys); Ollama models live in OLLAMA's OWN store
  (~/.ollama/models or $OLLAMA_MODELS) OUTSIDE data_dir, so the backup never sees them,
  and `_collect_members` has no model path. RULING RECORDED (same family as the wiki-
  dump inclusion above, also marked-not-built): add an OPT-IN option to include the
  Ollama model blobs so a restore avoids re-pulling multi-GB models (Tor-painful /
  clearnet-only). DESIGN POINTS when built: (a) OPT-IN + likely a SEPARATE COMPANION
  artifact (models are huge — small/quick backups must still opt out honestly), like
  the wiki-dump design; (b) DEDUP by checksum across backups (never re-store an
  unchanged blob); (c) read the EXTERNAL store path (OLLAMA_MODELS / OS default),
  manifest-list which models are carried; (d) restore = place blobs into the target
  Ollama store (or re-`ollama create`), bit-identical, never overwrite a differing
  local blob — this shares the SAME unbuilt file-member-in-backup MERGE machinery the
  wiki-dump inclusion needs (ledger: "the additive-restore MERGE must place FILE
  members"), so build the two together; (e) the encrypted-artifact key rule still
  holds. NOT a non-negotiable (no bundling of models IN THE REPO still stands — this is
  a user's LOCAL backup of models they already pulled, never shipped in the project).
  **SHIPPED 2026-06-17 (PR 6, branch claude/backup-ollama-models; BACKEND VERIFIED — the
  stdlib tests ran GREEN here):** the OPT-IN companion artifact — `src/backup/ollama_models.py`:
  `default_store()` (OLLAMA_MODELS or ~/.ollama/models), `list_models` (walk manifests/, resolve
  blobs+sizes), `build_models_archive` (a SEPARATE `.oomodels` zip = manifest.json inventory +
  each model's manifest + its referenced blobs, DEDUPED by sha256 filename), `restore_models_archive`
  (additive, bit-identical — existing blobs SKIPPED never overwritten; zip-slip-safe member
  validation). SEPARATE from oo-backup-2 (models live outside data_dir, content-addressed ⇒
  checksum-dedup + never-overwrite-differing are INHERENT). API in backup_v2.py: GET
  /api/backup/models (store + list + sizes), POST /api/backup/models/export (build→download), POST
  /api/backup/models/import (upload→restore). Settings → Data & backup gained a "Local LLM models
  (separate backup)" panel (export/restore buttons + store status). tests/test_ollama_models_backup.py
  (dedup round-trip, re-restore-skips, zip-slip rejection, env override) — executed locally, all
  green. REMAINING: the WIKI-DUMP inclusion now has a PROVEN pattern to reuse (this module); ~~the
  models-backup Settings UI strings are not yet i18n-keyed~~ DONE 2026-06-17 (i18n slice 8 keyed them ×12); an
  optional size/consent confirm before a multi-GB export (local disk I/O, no network).
  Design points to
  settle when built: (a) dumps are huge ⇒ DEDUP by checksum across backups (never
  re-store an unchanged dump) and consider whether dumps ride the main artifact
  vs a SEPARATE companion artifact so small/quick backups can still opt out
  honestly; (b) the additive-restore MERGE must place FILE members into
  wiki_dumps (not just merge DB tables) — bit-identical dedup, never overwrite a
  differing local dump; (c) the encrypted-artifact key rule still holds (members
  protected by the artifact envelope); (d) manifest still lists what IS and ISN'T
  carried. See FUTURE_DEVELOPMENTS "Backups include Wikipedia dumps".
- **DB-RELIABILITY BATCH — REMAINING RIDERS (core SHIPPED; the Settings
  restore-preview UI SHIPPED in T6, 2026-06-12 — v2 flow primary, legacy
  demoted-not-removed):** D1/D4 state-into-DB migrations (settings/
  annotations/event-imports → tables; agenda subs server-side), signing-key
  re-wrap inside the encrypt tool. ~~launcher/installer passphrase prompt~~
  **INSTALLER HALF SHIPPED (2026-06-12, caught LIVE: the curl|bash
  bootstrap crashed with DatabaseLockedError at "Initialising the
  database" on a fresh machine — encryption-by-default needs a passphrase
  choice no non-interactive init can make):** install.sh now tries env-
  driven init first (covers existing stores + OO_DB_PLAINTEXT/PASSPHRASE),
  then PROMPTS on a real terminal via /dev/tty (works under curl|bash:
  encrypted with confirm-twice + no-recovery + length guidance / PLAINTEXT
  typed-confirmation with stated risk / defer), else DEFERS honestly to
  the in-app first-launch prompt (deferred startup seeds at first
  unlocked boot, so nothing is lost) — never a traceback, never a silent
  default. EMPIRICAL: under curl|bash stdin is the pipe — prompts MUST
  read /dev/tty. The launcher half = the in-app /unlock create flow
  (already shipped); whiptail stays optional polish.
  **INSTALL-FLOW NEXT SLICE (maintainer field test 2026-06-13 — the tty
  prompt VERIFIED WORKING live end-to-end: encrypted store created,
  short-passphrase warn honored, 2978/3205 sources seeded): (a) install.sh
  AUTO-LAUNCHES the app when install completes — the install ends fluid,
  inside the running app; (b) the encryption choice MOVES to the app's
  initial screen (the in-browser first-launch prompt becomes the PRIMARY
  path; the terminal prompt demotes to the headless/env fallback). Fits
  the shipped deferred-init design (option 3 already seeds at first
  unlocked boot). **(a)+(b) INSTALLER HALF SHIPPED 2026-06-15 (field test,
  field-test-2026-06-15/LEDGER.md Item A): install.sh NO LONGER PROMPTS for a
  passphrase — init_database initialises ONLY for an existing store or an
  explicit headless env choice (OO_DB_PASSPHRASE/OO_DB_PLAINTEXT via
  _try_db_init), else DEFERS silently to the in-app first-launch setup; the
  interactive _prompt_db_protection function was REMOVED (env vars are the only
  headless fallback, per the ruling). maybe_launch() execs scripts/launch.sh at
  the end of an INTERACTIVE install (never CI/--unattended/--appvm/OO_SKIP_PIP;
  OO_AUTOLAUNCH=0 opts out), ending inside the running app at 127.0.0.1:8000;
  zero-network/airplane boot preserved; tests/test_installer.py green. The
  in-app encryption-choice STEP of the wizard (the GUI side of (b)) is still the
  remaining wizard slice.** (c) The /unlock screen carries THE canonical eye —
  SHIPPED #134: unlock.html now draws the pointed-oval + #-grid iris (exact
  same vector as the GUI top-left), the old double-arc eye is gone, and the
  invariant-#5 test now covers unlock.html. (d) FIRST-LAUNCH
  GUIDED SETUP (ruled 2026-06-13): a ONE-TIME, uniquely-designed guided
  GUI walks the user through every initial step to a WORKING scraping
  app — language selection, the encryption choice (absorbs (b)), then
  scraping-source setup BY THEME (drive it from the catalog's real tag
  taxonomy: news/history/investigative/science/financial/state-media…),
  folding in the ruled country/language-emphasis picker (field report
  #2 item 3 — BOTH stands) and ending at the consented first collect
  (the ONE consent design; zero-network boot preserved). It REPLACES
  the #onboard welcome card (index.html:675-684) — whose h2/p + both
  buttons are hardcoded English, never keyed (the maintainer flagged
  this 2026-06-13: card strings must enter the UI translations).
  Wizard ships ×12, informed-consent layering, and the one-time state
  is a user-visible setting, not a hidden flag.**
  **SLICE 1 SHIPPED (#150, 2026-06-14): wizard SHELL + Language step +
  Finish/collect step.** Stepped `<dialog id="guide-wizard">` (canonical-eye
  header, dot step indicator, Back/Next/Finish, RTL-aware); Language step
  renders the existing LANGS_12 (native name = identifier, invariant #15) and
  switches the whole UI live via pickLang→OOI18N.setLang; Finish states the
  app boots OFFLINE and offers "Go online" as the INVITATION layer ONLY — it
  NEVER POSTs the network, routing through firstRun()/toggleNetwork()→
  ensureOnline so the ONE consent popup (invariant #14) always fires (test
  asserts no /api/system/network POST in the handler). REPLACES #onboard as
  the first-run entry (card kept as the lightweight fallback so firstRun is
  never lost). One-time state = a USER-VISIBLE Settings toggle "Re-run the
  first-launch guide" + localStorage oo_guide_v1 (never hidden). +22 strings
  ×12 real translations (RTL Arabic), zero-network boot preserved.
  test_first_launch_guide_wizard enforces. DEFERRED to next slices (inert
  "Coming soon" placeholders left in place): the ENCRYPTION-CHOICE step
  (touches the DB unlock layer) and the SOURCES-BY-THEME step (needs the
  catalog tag taxonomy + the country/language-emphasis picker).
  **The live NEWSLETTER SCRAPER (IMAP/network) stays blocked until these riders
  ship; LOCAL .eml FILE import is GREENLIT (ruled 2026-06-15) — not a scraper
  (zero network), no-recovery contingency RESOLVED via anonymize-at-ingest (see
  Non-negotiables + the ".eml newsletter import" entry below).**
- **MASS LOCAL .eml NEWSLETTER IMPORT (ruled across 2026-06-15; full design +
  slices + acceptance in `docs/product/EMAIL_NEWSLETTER_IMPORT_PLAN.md`):**
  import a folder of .eml files as Articles in the ONE unified corpus (reuse
  src/ingest/email.py parse_email/ingest_emails — already recipient-free +
  hash-dedup). LOCAL ONLY, no IMAP/network ("enough for now"). RULINGS:
  (a) METADATA KEEP From · Reply-To · Subject · Date · Message-ID · **List-Id**
  (the stable newsletter key) · DKIM `d=` send-domain · List-Archive/List-Post
  if public. EXCLUDE the recipient AND every recipient-bearing header: To/Cc/Bcc,
  Delivered-To, X-Original-To, Return-Path (VERP), the Received chain, AND
  List-Unsubscribe (WALK-BACK of the earlier "capture List-Unsubscribe" idea —
  it carries a per-recipient token). (b) ANONYMIZE-AT-INGEST, NO RAW RETENTION
  (ruled): the DB NEVER stores the raw .eml, recipient headers, or any
  token-bearing tracker URL. (c) TRACKING-LINK DETOX (recipient protection —
  "most newsletter links track the recipient"): NEVER fetch on import (tested
  invariant: N files ⇒ 0 sockets — neutralizes open-tracking pixels and never
  confirms an open/click); a REUSABLE link_sanitizer = unwrap redirect wrappers
  ONLY when the destination is embedded, strip recipient query-params via a
  DATED evidence-based denylist (mkt_tok/mc_eid/_hsenc/_hsmi/ck_subscriber_id/
  oly_*…), drop beacon images, and FLAG tracker-wrapped links whose destination
  can't be recovered without a refused network call (store wrapper DOMAIN +
  visible anchor text, DROP the token-bearing path — degrade loudly, never
  present a wrapped link as the real source); REDACT the recipient's own echoed
  address from subject/body/URLs using the parsed-then-DISCARDED To (bonus:
  dedups copies across recipients); the CONSENT surface shows COUNTS of what was
  stripped ×12; downstream NEVER auto-follows tracker-wrapped links (fetching =
  phoning home as the recipient). (d) SOURCE RESOLUTION ("is a BBC newsletter
  the same source as the scraped BBC site?" — TODAY: NO; Source.domain is unique
  + matched exact-string, and registrable_domain/normalize_domain strip only
  www., NOT subdomains, so email.bbc.com ≠ the seeded bbc.com). FIX = a PROPER
  eTLD+1 via a VENDORED, DATED Public-Suffix-List snapshot + freshness test
  (network-free) → exact Source.domain match → is_equivalent_domain alias map
  (already carries bbc.com↔bbc.co.uk) → else a NEW DISABLED email source. SILENT
  auto-attach on a deterministic eTLD+1/alias hit (ruled 2026-06-15) + a
  DEDICATED import UI announcing it (live progress · every import detail · UNDO
  the automated attaches — feasible because send-domain + the attached source_id
  are stored as provenance). PRESERVE send-domain + List-Id as FILTERABLE
  provenance (email-vs-web stays separable, like per-edition wiki / DDG-discovered
  classes). NEVER fuzzy-merge (bbc≠nbc) — deterministic only; weaker matches =
  a user-confirmed SUGGESTION. PLATFORM INVERSION: for newsletter platforms
  (substack.com/beehiiv.com/ghost.io/mailchimp…, several already in SOCIAL_HOSTS)
  do the OPPOSITE — key on the publication subdomain / List-Id, never collapse
  many publishers into one platform domain. (e) IMPORT DATE already stored
  (created_at=now at ingest, parity with the web pipeline; published_at = the
  email's Date header) — no work. RETIRE the stale `scripts/import_eml.py`
  (broken vs the live schema — references content_hash/html_content/is_newsletter/
  metadata/scraped_at columns absent from Article — AND it captures To/Cc = the
  excluded recipient; FLAGGED, not yet deleted: maintainer-created, surface
  don't silently delete). The big configs/email_sources.yaml.example + the
  ROADMAP "Email & Newsletter Intelligence Implementation Plan" are ASPIRATIONAL,
  not status. SLICES: S1 anonymization core (link_sanitizer + email parse
  hardening + .eml file/dir ingest + tests) [first PR]; S2 metadata+provenance
  schema + the eTLD+1 PSL resolver + silent auto-attach; S3 upload API + the
  import-progress/UNDO WINDOW + the import-time disclosure ×12 + USER_MANUAL.
- **V0.1 ALPHA PREP — TWO ACTION PLANS DELIVERED (maintainer-asked
  2026-06-12): (A) user-centric reflections** (FUTURE_DEVELOPMENTS §
  "User-centric reflections": 6 scenarios, 6 contradictions faced, features
  A1–A9 — flagship A1 CLAIM WORKSPACE: evidence-trail-instead-of-verdict
  guided pipeline for non-scientific users; A2 corpus passport; A3 "Your
  lens"; A6 mention-context honesty…) **+ (B) the transversal audit**
  (`docs/audit/07_TRANSVERSAL_AUDIT_V01.md`: tool-by-tool M/T/G table —
  two ❌ disclosure gaps found: VADER English-only unsaid, LLM-output
  unlabeled; tamperability incl. the source-side cloaking vector + the
  local FIXITY tool; 100k-scale unknowns; ranked missing sources incl.
  retractions + fact-checks-as-stanced-sources + PR-wires-as-origin-
  detectors; neutrality = representation vs DECLARED PLURAL baselines,
  never auto-corrected; 10 named aggregator biases with which are
  update-fixable vs disclosure-permanent — notably CJK segmentation absent
  = zh/ja keywords nonfunctional while the UI ships those locales; steps
  B0–B7). **THE CANONICAL ACTION PLANS (maintainer-asked re-issue
  2026-06-12 "I haven't seen any action plans"): both plans live IN FULL in
  `docs/product/V01_ALPHA_ACTION_PLANS.md`** — every step with rationale +
  my commentary + acceptance criteria + dependencies + sequencing
  rationale, AND the maintainer's verbatim commission stored for recall;
  FUTURE_DEVELOPMENTS/audit-07/RC-gate all point at it. AWAITS B0:
  maintainer arbitration of severities into the RC gate (B1 disclosure
  sweep proposed RC-BLOCKING).
- **FULL-AUDIT REMEDIATION QUEUE (from `docs/audit/06_FULL_AUDIT_0_0_9.md`,
  delivered 2026-06-11; several items already fixed in-audit):** top: qualify
  the "stays on this machine" claim ×12 locales (AWAITS MAINTAINER RULING);
  caveats-visible-by-default vs calm UI (AWAITS RULING — U3);
  ~~reliability_score=5 + language="en" defaults removal~~ (SHIPPED T5,
  2026-06-12, + political_bias=0.0; migration f4b5c6d7e8a9 NULLs the
  fabricated 5s; languages stay — catalog-asserted); ~~ETHICS.md tense~~
  (verified closed: the one "will" is the doc's own review cadence);
  REMAINING: inline-handler retirement (295 inline on*= as of 2026-06-15 —
  229 onclick + 35 onchange + 15 onkeydown + 14 oninput + 2 onmouse*; the earlier
  onclick-only audit figure is stale — needs a browser-verified sweep); a11y batch.
- **De-US-centring — REMAINING (first batch shipped 2026-06-11: ISO-2
  canonical storage via src/catalog/countries.py, migration a3b4c5d6e7f8
  fixed the fabricated US default + the `[:2]` country-truncation corruption;
  coverage report = acceptance metric):** the Wikidata generator run for the
  73 named gaps (network step, maintainer's machine) + raising the located
  share (49% of domains carry no country).
  **SOURCE-COUNTRY PROVENANCE FIX SHIPPED 2026-06-16 (maintainer-ruled "also
  apply demonyms" after the investigation):** the seeder resolved country from
  ONLY the explicit field + a ccTLD fallback — it never read the title, yet the
  catalog already encodes origin two ways. (1) The `Name (Country)` SUFFIX is a
  real, trusted convention (635/636 agreement on already-countried sources); 68
  uncountried entries used it but left the field blank — pure omission. Promoted
  all into `configs/sources.yml` (35 were NULL → net-new located; the rest
  asserted-not-inferred). (2) A hand-reviewed pass over demonym/country-name
  titles added 57 more REAL national entities (news agencies, national papers,
  governments, museums, national assoc. chapters), spread across under-represented
  countries (Dominica, Grenada, Marshall Islands, Ethiopia, Ghana, Kenya, Qatar…)
  so it HELPS the balance (zero US added). DELIBERATELY left NULL (honesty — a
  wrong country is worse than none, and would undo this very balance work):
  language-edition markers (`Kyodo News (English)` is Japanese, not GB), TOPIC
  sites (`German History`/OUP, `Greek History Podcast`, `Theoi Project`,
  ancient-X portals, academic journals on a country), US orgs named after places
  (`German Marshall Fund`, `ChinaFile`, Perseus/Tufts), generic content series
  (`* Robotics News`), domain-contradicts-name (`chinaknowledge.de`), and ALL
  `International`/`int` bodies (no valid 2-letter code; genuinely transnational).
  Diff is PURELY ADDITIVE (129 `country:` lines, 0 deletions); sources.yml located
  share 40.4%→44.4%. SEEDER HARDENED: `country_from_title()`
  (src/catalog/normalize.py) reads ONLY the explicit trailing parenthetical (never
  scans for demonym/country words — too noisy to automate), wired between the
  explicit field and the ccTLD (human marker outranks a domain guess); demonym/
  name fixes live in the DATA, hand-reviewed, never auto-inferred. REGRESSION
  GUARD: test_seed_sources.py::test_catalog_honours_its_own_country_suffix_convention
  asserts every `(Country)`-suffix entry carries the matching field forever.
  Net-new located ≈54 + ~70 provenance upgrades. (The Wikidata generator run for
  the 73 named gaps is still the big remaining lever; this closes the
  title-evident gap that needed no network.)
  **DEMONYM/NAME PASS — 2ND BATCH SHIPPED 2026-06-17 (maintainer flagged "there are still
  sources with country names in their names but no country assigned"):** a fresh scan
  confirmed the `(Country)`-SUFFIX gap is still 0 (the regression guard holds), so this is
  purely the demonym/name case the ledger left to hand-review. Scanned all 1782 uncountried
  entries for an ISO country full-name (COUNTRY_NAMES) or a curated demonym in the NAME,
  with the SAME topic/US-org exclusions (history/podcast/project/fund/institute/studies/
  ChinaFile/Marshall/International…). 37 raw candidates → 11 GENUINE national entities
  assigned (hand-reviewed, additive 11 `country:` lines, 0 deletions; sources.yml located
  44.4%→44.7%): India Science Wire→in · Investigative Reporting Denmark (DR)→dk · GOV.UK
  News + UK Parliament News + Cancer Research UK→gb · Drought Monitor (U.S.) + U.S. Energy
  Information Administration (EIA) + U.S. Hydrogen Alliance→us · National Museum of Korea→kr
  · Cofact Thailand→th · Vietnam Fact Check→vn. DELIBERATELY left NULL (honesty, per the
  standing rules — verified each): every `* Robotics News` (generic content series), all
  topic/history/academic sites (Late Imperial/Modern China, China Heritage, Ancient Greek *,
  Medieval Ethiopia, Kingdom of Ghana/Zimbabwe, Mali Empire, * History), and US orgs ABOUT a
  country (China File/ChinaFile, China Digital Times, 38 North, Alliance for Securing
  Democracy - Spanish). The 3 genuine US agencies are assigned because the name is
  unambiguous ("U.S. Energy Information Administration") — labelling a TRUE country is honest
  (a wrong country is worse than none); the de-US-centring rule forbids fabricated US
  DEFAULTS, not labelling real US entities. No auto-inference added (the seeder still reads
  only the explicit `(Country)` suffix; demonym fixes stay hand-curated DATA). 23 catalog/seed
  tests green.
- **LIVE-TEST FIELD REPORT #2 (2026-06-11, seven items — facts code-verified;
  implementation queued; proposed order at the end):**
  (1) NETWORK TOGGLE — UI SEMANTICS + CONSENT SHIPPED (T2, invariant #14):
  airplane glyph FILL=state, ONE consent popup with local IPs, immediate
  repaint via scheduler responses, gates on collect/markets/wiki/dumps, +
  socket-importer ratchet test. REMAINING from this item: refactor the six
  allowed HTTP importers onto ONE guarded socket factory (gate §1 SHOULD;
  the ratchet pins them meanwhile); the OPT-IN privileged OS layer
  (oo-netcut) stays POST — INTERFACE-AGNOSTIC (no dom0 privileges from an
  AppVM/DispVM; don't focus on Qubes): (a) firewall drop-all both directions
  incl. inbound, (b) `ip link down` on non-loopback interfaces, (c) rfkill a
  bare-metal radio bonus; Windows netsh / macOS networksetup behind ONE
  helper; elevation explicit + narrowly scoped, never silent. We control OUR
  environment's interfaces; layers beneath may stay online; the button names
  the layer it controls; a userspace app can NEVER equal a hardware webcam
  light and we never claim it.
  (2) AGENDA CONTENT (the month-grid default + plumbing→Settings SHIPPED;
  ASTRONOMY LAYER slice SHIPPED T11 2026-06-12: Meeus ch.49 full/new moons
  computed locally, VERIFIED against the book's worked example 49.a to ≤30 s
  + 2024 almanac dates; /api/events/astronomy; moon glyphs in the month grid
  with method+accuracy in the hover bubble; ΔT non-application STATED):
  SEASONS + CLIMATE slice SHIPPED T11b same day: Meeus ch.27
  equinoxes/solstices (verified vs example 27.a ≤9 s + 2024 dates;
  hemisphere-honest astronomical naming — never "summer", stated in the
  payload), /api/events/astronomy gains seasons; /api/events/climate serves
  the bundled El Niño episode dataset (NOAA CPC ONI convention, drafted
  2026-06-12, VERIFICATION-PENDING flag travels per file until the clearnet
  check); IPCC-as-source + prediction-tracking + agenda↔wiki linking
  recorded in FUTURE_DEVELOPMENTS with questions.
  **AGENDA HIGHLY-VISIBLE + CLICKABLE — SHIPPED 2026-06-16 (maintainer greenlit
  "the agenda content should be highly visible and clickable"):** (1) CLICKABLE —
  every agenda event TITLE (`agRow`, used across the views' day-detail) now opens the
  unified analysis window over that event in the corpus via `openAnalysisFor(e.title)`
  (event.stopPropagation so the tag/source links still work); ties the agenda to the
  corpus (the app's value). (2) VISIBLE CONTENT — SEASONS (equinoxes/solstices, Meeus
  ch.27, already computed + served by /api/events/astronomy but never shown) now render
  as month-grid glyphs (☀ solstice / ✦ equinox) beside the existing moon glyphs, with
  method+accuracy + the astronomically-honest name in the #oo-tip hover (`_seasonByDate`
  built in `_ensureAstro`, the same per-year cache as moons). +5 strings ×12 (the 4
  season names + the click hover). REMAINING: moons/seasons as FIRST-CLASS agenda
  events (in day-detail + all views, with ⊞ keyword links — currently month-grid
  glyphs only, matching the moon treatment); El Niño episodes rendered as month-span
  agenda banners; recurring-event model unifying rules + per-year instances +
  origin year ("since 1810" — the Mexico sighting was the ICS import path
  storing year-pinned instances); month-span banners ("Dry January"); the
  remaining views (week/trimester/semester/year/decade) — ALL SHIPPED now (week
  + year earlier; Trimester/Semester/Decade = PR #206, reusing the shared event
  path + Year-view card grammar, one shared nav bar, Intl-localized ×12);
  REMAINING here = play speeds 0.05–16×
  log-stepped; PRELOADED worldwide bank holidays + religious calendars
  (moon-based Islamic = computed tabular dates with the honest ±1-day
  moon-sighting caveat; Hindu/Buddhist = sourced published tables, NEVER a
  fabricated panchanga) + an ASTRONOMY LAYER on a reliable LOCAL model (Meeus
  full moons computed + TESTED against almanac values; eclipses from a
  bundled public canon table with provenance; method+accuracy per entry;
  zero-network boot preserved) + article-extracted dated events feeding the
  agenda automatically (labeled "deduced from N articles", never confirmed).
  Also the standing depth ask (2026-06-10): "we should be flooded; it's the
  point of datamining" — expand calendars massively (elections, summits,
  central banks, parliaments, courts, UN days, fiscal dates…), every entry
  sourced, movable dates marked, subscribe-default stays off-flood.
  (3) CONTINUOUS COLLECTION (ruled): scraping never stops — background
  auto-collect ON after an explicit first-run approval (ONE consent design
  shared with item 1's popup; zero-network boot stands). Ordering adopted:
  per-country round-robin, one source each then repeat (shuffled country
  order per cycle, least-recently-scraped within a country, politeness
  untouched), PLUS a startup onboarding picker for country/language emphasis
  — BOTH. The schedule stays explainable in the UI (which country is next
  and why).
  **AMENDED + SHIPPED 2026-06-17 (maintainer: "put the scraping engine in the
  background; it should start automatically; the only reason to stop it is airplane
  mode; maximize rapid+ethical; scrape with TRUE RANDOMNESS by language AND source
  tags"; branch `claude/scraping-background-random`, draft PR onto 0.09,
  BROWSER-UNVERIFIED):** (a) ORDERING — the per-country round-robin is SUPERSEDED for
  the default pass by `stratified_interleave` (src/scheduler/runner.py): TRUE per-pass
  randomness, fairly stratified by LANGUAGE then by SOURCE TAG (each language equal
  round-robin turns, language order shuffled every call; within a language each distinct
  tag equal turns; within a (lang,tag) group a true-random shuffle), so no source-rich
  language/topic dominates and the order differs every pass. A source's stratum tag =
  its FIRST tag; no-lang/no-tag share a "·unknown"/"·untagged" bucket (never dropped).
  Per-host POLITENESS is untouched (it lives in the fetcher's host lock; this only
  orders). `round_robin_interleave` (country) is RETAINED as a utility + its tests
  (test_continuous_collection/test_scheduler_runner stay green); new
  tests/test_stratified_interleave.py. (b) BACKGROUND/AUTO already true (scheduler
  `continuous` default, "scraping never stops"; offline stops the thread) — reaffirmed:
  boot is AIRPLANE (zero-network), going online passes the ONE consent (ensureOnline,
  invariant #14), then the collector runs continuously and ONLY airplane stops it.
  (c) The "Welcome — your corpus is empty / Seed sources & run a first ingestion / No
  articles yet" BUBBLE (#onboard) is REMOVED — redundant now: sources AUTO-SEED on boot
  (main.py OO_AUTOSEED) and going online auto-collects. checkEmptyCorpus keeps the
  one-time guided wizard (openGuide/guideDone) as the first-run entry; the empty Home
  falls back to the briefing's honest empty state; the wizard's "Go online" now routes
  straight through toggleNetwork()→ensureOnline. firstRun() is RETAINED (test #396
  pins it: a consent-respecting programmatic seed+collect helper) but null-safe + unwired
  from the UI; the 4 #onboard i18n keys are now orphaned (harmless, left to avoid churn).
  Rapid+ethical (bandwidth governor ≥500 kbps default + parallel collect + per-host
  politeness) already shipped — nothing to change there. DEFERRED special cases (ruled
  "keep for later, needs a specific UI"): per-source RELIABILITY weighting + NEAR-LIVE
  cadence for chosen sources (e.g. Olympics). node --check + py_compile + the at-risk
  invariant string-checks green; full pytest needs py3.13 (CI).
  (4) TASK MANAGER — SLICE 1 SHIPPED (T9, 2026-06-12): /api/jobs aggregates
  LIVE from the owning systems (no shadow state — the view cannot disagree
  with reality): collect pass, every wiki dump with its REAL queue position,
  the in-flight fetch (DOMAIN only). Dump manager gained a true
  single-download QUEUE (max_concurrent=1, persisted reorderable order,
  pump-on-finish) — the fr-before-en reorder works end-to-end (↑↓ in the
  panel + POST /api/jobs/dumps/reorder, tested). The vitals popover is now
  "Tasks & collection": jobs list with progress bars + Stop/Pause/Cancel
  (collect-stop states the kill-switch side effect — informed consent), the
  collection detail, vitals as the bottom row. ARBITRATION ASK shipped for
  collect run-now (busy_with listed; proceed-or-wait). **PARALLEL ACROSS
  KINDS (maintainer-amended same day): collecting articles WHILE a wiki dump
  downloads is BY DESIGN — a dump writes a FILE, collection writes the DB;
  no writer-lock contention — so the ask fires ONLY on DB-writer collisions
  (collect/import kinds); dumps keep their own single-download reorderable
  queue among themselves (bandwidth arbitration, not a cross-kind block).** REMAINING from the
  original ask (maintainer REPEAT ×3, the 2026-06-13 field test elevated it
  again — "the task manager is absent, I thought we'd had it done"): the
  vitals BUBBLE graduates to a DEDICATED WINDOW/TAB, not a popover — minimized
  animated indicators in the chrome, CLICK opens an OS-style task-manager
  window with TABS for categories (proposed: Active · Queue · Sources/Schedule
  · History · System) where the user can understand, explore, manage,
  organize, sort, prioritize, QUEUE every download/scrape and any other job.
  Full spec + tab design in `docs/product/SCRAPING_AUTOMATION_PLAN.md` Step 7.
  Acceptance examples: reorder fr wiki dump
  before the much bigger en; per-country scrape priority; every background
  process visible & tweakable. Build together with DOWNLOAD-MANAGER
  ARBITRATION (ruled 2026-06-10): every network task is a VISIBLE JOB; a new
  fetch request while one runs ASKS queue/prioritize/cancel — never silently
  swallowed; a dedicated downloads view shows running/queue/history. And the
  ACTIVITY CHIP (ruled 2026-06-10): clicking "Collecting…" opens a DETAILED
  collection panel (sources done/total, current host as DOMAIN only, schedule
  + next run, honest pass-time estimates with method, per-source ↓ rates from
  the fetcher's own responses), with hardware vitals only as a compact bottom
  row. ALSO from field log #1: 'database is locked' under concurrent
  import+scrape = this arbitration item; preflight covers 50 sources/run —
  batch it like calendars.
  (5)–(7) folded into the corpora/reader entry below (tag-click entry; date
  extraction at ingest = When×Where×Who CONFIRMED GO; reader tabs REPEAT ×2).
- **CONTENT-FIRST SCRAPING + THE DOWNLOAD SUBSYSTEM (ruled 2026-06-13; full
  action plan in `docs/product/SCRAPING_AUTOMATION_PLAN.md`):** the maintainer
  principle — "the UI should focus on CONTENT, not the scraping mechanics;
  setting everything up is cumbersome; after consent the app scrapes
  automatically." Seven steps, sequenced in the doc: (1) ONE guarded socket
  factory — closes the kill-switch gap + the stale UA + a LATENT TRANSPORT
  LEAK found 2026-06-13 (dump/wiki use raw requests with NO proxies=, so Tor
  set only in-app would egress clearnet — never silently downgrade transport),
  ELEVATE RC §1 to RC-BLOCKING; **(2) PARALLEL downloads — SHIPPED (dumps
  fc73e0f; collect 5f517ab; verified 2026-06-14): dumps max_concurrent 1→N
  (default 3, OO_DUMP_CONCURRENCY; files, no DB-writer contention; excess still
  QUEUES reorderably) + a bounded fetch worker pool for collect
  (collect_parallelism, default 1/opt-in, 1..16; parallel FETCH across hosts,
  each worker its OWN session, single-writer gate keeps writes serial) — THE Tor
  speed fix: N downloads = N circuits = aggregate speedup. Guardrails proven
  (tests/test_parallel_collect.py + test_parallel_dumps.py): per-host politeness
  = EthicalFetcher._host_lock (one host = one in-flight request even under the
  pool, different hosts in parallel); kill switch gates every worker (fetch()
  _KILL check + GuardedSession.request); circuit isolation via
  _with_stream_isolation/IsolateSOCKSAuth per host & per dump URL (never silently
  downgrade transport);** (3) segmented HTTP-Range over multiple circuits +
  IsolateSOCKSAuth for one big dump (REMAINING); (4) dump mirror selection
  (REMAINING); (5) auto-collect ON by default after
  the guided wizard's ONE consent (continuous-collection design adopted,
  zero-network boot intact); (6) the Collect TAB LEAVES the sidebar → an
  elaborated Settings → Download section (nothing lost — invariant #8 + the
  Desk lesson, gated by an absorption test); **the SOURCES tab AND the
  WIKIPEDIA tab ALSO leave the sidebar into Settings (ruled 2026-06-13) —
  same content-first principle, same absorption-test guard;** (7) the
  task-manager WINDOW (item 4 above). GUARDRAILS: per-host politeness never traded for speed
  (parallel across hosts/circuits, bounded per host); kill switch gates every
  worker; degrade loudly with T4 transport-aware verdicts. ROOT CAUSE (now
  FIXED by Step 2): WAS max_concurrent=1 + a sequential collect loop = exactly
  ONE circuit ever active = worst-case Tor; now N circuits run concurrently.
  **NO SOURCE CAP + BANDWIDTH PRIORITY LADDER (ruled 2026-06-13, maintainer):**
  REMOVE max_sources_per_run (the 1000 cap) — ANY cap induces an unjustifiable
  SELECTION of which sources to skip ("we cannot choose"); scraping must cover
  EACH AND EVERY source, and ALL modes (RSS + crawl + markets + commodities +
  weather + wiki + DDG). The cap was a per-run batch limit; the continuous
  per-country round-robin replaces it — over time EVERYTHING is covered, no
  source starved, no selection made. CRUCIAL DISTINCTION: ordering ≠ exclusion —
  a bandwidth PRIORITY LADDER decides what runs FIRST under constrained
  bandwidth, never what runs AT ALL. The ladder (maintainer): (1) commodities /
  markets / weather FIRST — small payloads, cheap, high value; (2) interactive
  DDG searches next — snappy UX (user-facing preempts background); (3) RSS
  feeds; (4) recursive crawling ONLY with bandwidth headroom (heaviest). The
  task manager surfaces + tunes this bandwidth allocation (a budget/meter across
  job kinds), tied to the measured throughput and the parallel-download
  concurrency. Weight by (freshness-due, cost, interactivity): periodic
  markets/weather fetch when new data is due, not constantly. Folds into
  SCRAPING_AUTOMATION_PLAN Steps 2/5/7.
- **FIELD-LOG ANALYSIS 2026-06-13 (4 session exports crunched: perf report +
  debug bundle + network preflight + keyword diagnostics; live corpus ≈1.5k
  articles / 62k keywords / 155k mentions, 2-core/6 GB Qubes VM, over Tor):**
  findings ranked —
  (A) **DATA LOSS — "database is locked" (HIGH):** the commodity import
  collided with the active scrape on the single SQLite writer; copper/aluminum/
  nickel/zinc… FETCHED OK over Tor then FAILED TO STORE ("store error:
  OperationalError: database is locked", verdict ok, retryable:false) — real
  downloaded data DISCARDED. WAL lets readers pass but two WRITERS still
  conflict; the import path lacks busy_timeout / write-queue. FIX = the
  single-writer QUEUE from SCRAPING_AUTOMATION_PLAN Step 2 (all writes enqueue;
  import + scrape never collide) + busy_timeout + retry-on-locked. This is the
  field-log-#1 'database is locked' item, now with proof of data loss — ELEVATE.
  **SHIPPED (single-writer gate, keystone #1 — commit 3268922, merged to 0.09):**
  src/database/writer.py = a process-wide reentrant write mutex; every ORM write
  takes it on first flush (session events on SessionLocal) and releases on the
  outermost transaction END (after_transaction_end — the leak-proof hook); raw-SQL
  writes (VACUUM) take it via write_lock(); SQLite-only, OO_WRITE_GATE=0 escape
  hatch; reads NEVER gate (WAL untouched). import_points keeps run_write_with_retry
  + busy_timeout=30000 as defence-in-depth backstops. END-TO-END PROOF added this
  session (tests/test_write_gate_dataloss.py): the real SessionLocal + real
  import_points racing a scrape Article store loses ZERO rows; an ISOLATION
  experiment proves the gate is load-bearing (control without it = 47 'database is
  locked' on the field-log condition; with it = 0); + a reads-not-blocked WAL
  check. The boot-time raw writes (ensure_fts/ensure_hot_indexes/optimize_at_boot)
  run pre-scheduler so they cannot collide. REMAINING (Step 2 cont.): the bounded
  fetch worker pool for parallel collection (the gate is its prerequisite) +
  parallel dumps; the gate's stats() feeds the task-manager System view later.
  (B) **UI POLLING STORM (MED):** ~2 h uptime drove /api/system/vitals ×4120,
  /api/scheduler/activity ×2747, /api/scheduler/status ×1846,
  /api/system/network ×1388, /api/jobs ×248 = ~10k polls contending with the
  encrypted DB. FIX = consolidate into ONE status poll or SSE/push; adaptive
  backoff when idle; the airplane/scheduler already push state — lean on that.
  (C) **keyword_export 29.6 s then 65.2 s (MED):** run2 SLOWER than run1 = not
  cache, it is CONTENTION with the live scrape over the single SQLCipher
  connection (T1 measured ~7.8 s encrypted on a BIGGER synthetic corpus). Same
  root as (A)/(B): one connection, pure-Python serialized. Revisit after the
  writer queue + a read snapshot for exports.
  (D) **DISCOVERY creates COMMERCE sources — SHIPPED:** `is_commerce_domain`
  (src/discovery/channels.py) filters obvious storefronts at the ONE citation
  chokepoint (leftmost shop./store./buy. label + .shop/.store gTLD + …prints +
  hyphen-delimited -shop/-store/-merch suffix); candidates were already
  never auto-enabled (promote ⇒ a DISABLED source). Conservative by design —
  legit news + substring traps (restore/workshop/bookstore-review/superstore-news)
  pass through; bare un-hyphenated suffixes left un-filtered on purpose (no
  fabricated precision). Core in 5b6b753; suffix-rule extension + dedicated
  tests/test_discovery_commerce_filter.py in the discovery-commerce-filter PR.
  (E) **DEAD DEFAULT FEEDS waste preflight (LOW):** every google-hol-* calendar
  is robots-disallowed (100% fail), webcal.guru religious feeds disallowed,
  raw.githubusercontent/space.floern/cantonbecker robots-undetermined → all
  dead; the WORKING set is worldpublicholiday.com (wph-*), monkeyness moons,
  ose-calendar. FIX = drop the guaranteed-fail feeds from defaults (honest
  fail-closed is correct, but shipping them as defaults wastes cycles).
  (F) **RSS DUP RATE ~93% (LOW) — CONDITIONAL-GET CORE SHIPPED (verified on
  0.09 2026-06-15; ledger was stale):** conditional GET is DONE — FeedFetchState
  table (src/database/models.py:457, migration c8d9e0f1a2b3) persists
  ETag/Last-Modified per feed; EthicalFetcher.fetch threads extra_headers +
  returns status_code/etag/last_modified; ingest_source (src/ingest/pipeline.py:289)
  sends If-None-Match/If-Modified-Since and SHORT-CIRCUITS on 304 (tally
  "not_modified", no feedparser parse), refreshing validators on 200 only;
  tests/test_feed_conditional_get.py green (304 skips+preserves, 200 refreshes,
  no-validator→plain GET). BACKOFF SECONDARY SHIPPED (PR #208): for servers that
  IGNORE conditional headers (full 200 every pass), a CAPPED self-resetting per-feed
  backoff — a 200 storing zero new articles sets FeedFetchState.skip_until =
  now+min(300s·2^n, 6h cap); resets on any new article, a 304, or a fetch error;
  the scheduler's _filter_due_feeds skips backed-off RSS feeds THIS pass (RSS-only,
  fail-open, counted as a distinct backed_off tally — visible, never hidden). NEVER
  an exclusion: the 6h cap guarantees re-check, honoring "no source starved /
  ordering ≠ exclusion" (env OO_FEED_BACKOFF_BASE_S/_CAP_S, =0 disables; migration
  d2e3f4a5b6c7). Finding F now CLOSED. (G) NOTE: Tor 403s on premium news (reuters/ft/bloomberg/
  economist/lefigaro…) are the Tor-population reality, already surfaced via T4
  transport verdicts — not a bug. FRED timeouts over Tor confirm the
  parallel/official-endpoint direction. keyword diagnostics: language_mismatch
  flagging WORKS (515 flagged, e.g. ANS en→fr:60); "services" tagged kind=entity
  is the ongoing keyword-quality tail, not new.
- **IN-APP OLLAMA/MODEL INSTALLER + APP SELF-UPDATE (ruled 2026-06-13;
  designed in FUTURE_DEVELOPMENTS):** Settings → LLM panel installs Ollama +
  pulls models from the GUI (checksum-verified through the guarded factory,
  catalog picker with size/RAM/license shown never a score, pulls are
  task-manager jobs, clearnet stated prerequisite, hardware fit MEASURED).
  **RE-RAISED + NOW ACTIVE (maintainer 2026-06-16): build it as a DEDICATED
  Settings SUBTAB for LLM management (invariant-#18 grammar, not the lone
  read-only panel), with explicit actions — download+install the Ollama
  BINARY, EXPLORE models, download/pull, install/RUN, REMOVE. VERIFIED STATE
  2026-06-16: substrate exists (src/llm/ollama.py OllamaClient
  health/list_installed[_detailed]/generate; /api/llm health·models·generate·
  summarize·translate·synthesize; #llm top-bar pill; the 'Local models'
  Settings panel) but is READ-ONLY — it shows installed + the 5-model dated
  catalog and tells the user to use a TERMINAL ('ollama pull <tag>' as COPY
  TEXT, not a button); NO pull/remove/install-binary endpoints or buttons exist
  yet. Pull/rm can stream REAL bytes from ollama's own /api/pull·/api/delete
  (honest progress, invariant #20); pulls = task-manager jobs, GATED by the ONE
  consent (#14). OPEN DECISIONS filed for a maintainer ruling: (a) how far the
  binary install goes — guided+verified vs per-OS auto-exec an installer vs
  user-space tarball auto-run (security/elevation trade-off); (b) model
  exploration — curated dated catalog (zero-network) + an OPT-IN consented
  live-ollama.com-library browse + a free-text 'pull any tag' box, vs always
  live-browse; (c) TRANSPORT HONESTY — pulls egress via the OLLAMA PROCESS over
  CLEARNET, NOT our Tor proxy/guarded factory, so airplane+Tor don't cover them
  (state at consent; the USB offline kit stays the air-gapped path); (d) active
  model moves from env-only OO_LLM_MODEL to a stored UI setting.**
  **RULINGS 2026-06-16 (maintainer answered): placement = a Settings SUBTAB
  (Q6=A); (a) binary install = Q7=B — the app DOWNLOADS + RUNS the official per-OS
  Ollama installer (verify checksum/signature BEFORE exec through the guarded
  factory; consent + a VISIBLE explicit OS elevation step, NEVER silent; honest
  about what is run); (b) model exploration = Q8=A + ELABORATION — the curated
  dated catalog PLUS a SEARCHABLE consented live-ollama.com-library browse (the
  full library is too large to list), FILTERABLE/sortable by PROVIDER · DATE ·
  SIZE (+ hardware-fit + license), showing ONLY app-APPLICABLE models. APP
  COMPATIBILITY CLARIFIED: our features (summarize/translate/synthesize) use PLAIN
  /api/generate text generation — NO tool/function-calling — so any instruct/chat
  TEXT model that fits the hardware works; filter OUT non-applicable kinds
  (embedding-only, vision-only); 'compatible' = text-generation that fits RAM, not
  a special protocol; (c) transport = Q9=YES (clearnet via the ollama process,
  disclosed at consent); (d) active model = Q10=YES (stored UI setting).**
  **PULL/REMOVE ENDPOINTS SHIPPED 2026-06-16 (backend slice 1):** `OllamaClient.pull`
  (a generator STREAMING ollama's own /api/pull progress objects — honest real
  progress, invariant #20) + `OllamaClient.remove` (/api/delete); `POST /api/llm/pull`
  relays the progress as NDJSON (StreamingResponse), `POST /api/llm/remove` deletes.
  Both inherit the kill-switch refusal (airplane mode = no socket — the pull would
  egress over CLEARNET via the ollama process, exactly what airplane forbids; Q9
  transport honesty in the docstring) + loopback-only; a strict model-name regex
  blocks path injection (tests assert no ollama call for a bad name). tests in
  test_llm_ollama.py (stream parse, remove+404, kill-switch refuses pull/remove,
  bad-name 400). **SETTINGS LLM SUBTAB UI SHIPPED 2026-06-16 (conservative,
  browser-unverified):** a dedicated Settings → Models subtab (`data-tab="models"` /
  `#set-models`, Q6=A — the read-only panel moved out of General) with explicit actions —
  pull (raw fetch reading the NDJSON stream → live status/percent, invariant #20), remove,
  the active-model picker (`Set active` → PUT /api/settings {llm_model}, Q10) + per-catalog
  Pull buttons + a free-text pull-any-tag box (Q8). Pull gated by the ONE consent
  (ensureOnline #14) + a VISIBLE clearnet-egress disclosure (bytes go over clearnet via the
  ollama process, NOT Tor — Q9); +27 i18n ×12; test_ui_invariants #28. REMAINING: the
  binary-installer (Q7=B download+verify+run official installer with a VISIBLE elevation
  step) — BLOCKED OFFLINE (needs real per-OS installer checksums verified against clearnet;
  fabricating them = forbidden — do on a networked machine); live ollama.com library
  browse (Q8); pulls as task-manager jobs.
  **CATALOG REFRESHED 2026-06-17 (maintainer-asked "latest + smallest open models from
  Mistral, Google, IBM, Nvidia", branch `claude/llm-catalog-refresh`, draft PR onto 0.09):**
  `MODEL_CATALOG` (src/llm/ollama.py — the ONE source the in-app Settings → Models subtab
  reads via /api/llm/models; the frontend has NO hardcoded list) now leads with the latest
  small open models, ALL REAL ollama.com/library tags VERIFIED VIA SEARCH (ollama.com 403s
  WebFetch here, so WebSearch was the verification path — NEVER fabricated, per the file's own
  "previous catalog was hallucinated" caution + the no-fabricated-data non-negotiable):
  granite4:350m + granite4:micro (IBM Granite 4.0, Oct 2025, Apache-2.0; micro=3.4B confirmed
  2.1 GB Q4_K_M), gemma3:1b + gemma3:4b (Google Gemma 3), nemotron-mini (NVIDIA, 4B),
  mistral:7b (Apache-2.0 — the smallest OPEN Mistral on Ollama; no smaller official open tag
  exists, so none invented), keeping llama3.2:1b/3b (Meta, the DEFAULT_MODEL). Sizes are
  honest ~approximations for the real tags (the field is an advisory hardware hint; the live
  installed-models picker stays the source of truth). The installer's quick-download menu
  (install.sh whiptail + the non-whiptail fallback + the OO_OLLAMA_MODEL example) refreshed
  to gemma3:1b/granite4:micro/nemotron-mini/llama3.2:3b. CATALOG_AS_OF stays "2026-06"
  (re-verified this month; freshness test green). No frontend/i18n change (backend-driven);
  no test asserts catalog contents (test_llm_ollama gemma2:2b refs are mock names, not the
  catalog). REMAINING: re-verify exact sizes on a networked machine when convenient.
  **Q10 SHIPPED 2026-06-16 (backend):** `AppSettings.llm_model` (a persisted UI
  preference, model-name-validated against injection; "" clears it) replaces env-only
  `OO_LLM_MODEL` as the operator default; `api.llm.active_model()` resolves stored ||
  DEFAULT_MODEL and the generate/summarize/translate/synthesize endpoints + the picker
  (`/api/llm/models` gains `active`) honor it; settable via the existing PUT
  /api/settings. tests/test_llm_active_model.py. REMAINING: the Settings LLM subtab UI
  to choose it from the live installed-models list.
  **BULK SUMMARIZE/TRANSLATE + READER SUMMARY/TRANSLATION TABS + EDITABLE PROMPTS
  (maintainer field test 2026-06-17, branch `claude/confident-hopper-ef600p`, draft PR
  onto 0.09, BROWSER-UNVERIFIED per fork-3) — answers the maintainer's "bulk article
  summary/translation don't work · can't see the translated article · summaries/
  translations recorded but NOT analysed/keyword-ingested · keep metadata · never
  replace, show latest + fold the rest · LLM-offline pill not synced · model unload
  unnecessary · prompts: detail/incorporate-into-metadata/tweakable":**
  (1) NO bulk feature existed (single per-row Summarize/Translate in Search only). NEW
  streaming `POST /api/llm/bulk` (op=summarize|translate) runs the local model over EACH
  article in a matched set (article_ids OR query/filters, same selection as the analysis
  window), stores ONE ArticleAnalysis per article (NEVER replacing a prior one),
  NDJSON honest per-article progress (invariant #20), `skip_existing` tops up only the
  missing, bounded `_BULK_MAX_ARTICLES=500`, aborts loudly if Ollama goes away mid-run.
  Frontend: "Summarize all"/"Translate all" in BOTH the Search toolbar and the analysis
  window action row → `bulkLlm`/`bulkLlmRun` (AbortController cancel, live tally). Ollama
  is loopback (no egress, no consent popup — like the single path) but airplane mode
  refuses it, surfaced. (2) READER (standalone, English-only) gained **Summary** +
  **Translation** tabs (after Read): `GET /api/llm/articles/{id}/analyses?kind=` returns
  newest-first with full provenance; the tab shows the LATEST + a folded `<details>` of
  all earlier ones + a generate-now control (target-language `<select>` for translate).
  NEVER keyword-indexed BY CONSTRUCTION (rows live in article_analyses, the indexer reads
  only articles.content). (3) **EDITABLE PROMPTS (the user asked — there are THREE system
  prompts: summary[1-or-many] · translate[1-or-many] · synthesis[several]; bulk reuses the
  single prompt per article, so "4" → 3).** Settings → Models gained a "Behaviour &
  prompts" section: keep-alive + 3 prompt textareas (empty = built-in default shown as
  placeholder; `{target}` substituted in translate) saved via PUT /api/settings;
  `GET /api/llm/prompts` exposes defaults+current. The EXACT system prompt used is now
  recorded per result (`ArticleAnalysis.prompt_text`, migration a1b2c3d4e5f6 off head
  f4a5b6c7d8e9 + `ensure_article_analysis_columns` self-heal since the live DB isn't
  auto-alembic'd; shown folded in the reader) so provenance stays honest after a prompt
  edit; version flags default-vs-custom (summary-v1 / summary-custom, translate-v1:X /
  translate-custom:X). (4) **MODEL KEEP-ALIVE**: `OllamaClient.generate(keep_alive=)`
  threaded through every call; stored `AppSettings.llm_keep_alive` default **"30m"** (the
  maintainer's "unloading isn't necessary" — "-1" never unload, "0" unload now). (5)
  **LLM-OFFLINE PILL SYNC BUG fixed**: `loadLlmHealth()` ran ONCE at boot and the app boots
  in airplane mode → stuck "offline" even after going online + Ollama up. Now re-checks on:
  going-online (`_paintNetwork` transition), opening Settings → Models, after every LLM
  action, tab regaining focus (visibilitychange), and on CLICK (the pill is now clickable).
  Settings JSON-file (no migration for keep-alive/prompts). +29 i18n keys ×12
  (AI-drafted, flagged for native review; audit-chrome clean, gate 100%). Tests:
  test_llm_api.py (bulk stream/skip/abort/target, analyses provenance, prompts endpoint,
  custom-prompt recorded, keep_alive passed) + test_reader_tabs.py (new tabs). VERIFIED
  here on py3.13 venv: 103 targeted tests pass · ruff F/B clean · mypy adds 0 new errors ·
  node --check · alembic single-head · self-heal idempotent. REMAINING: human
  click-through (fork-3); a per-article Summarize/Translate on the analysis Articles list;
  bulk as a first-class task-manager job (currently a streaming request).
  **PROMPTS v2 + LANGUAGE PIN SHIPPED 2026-06-17 (maintainer asked "critically assess +
  optimize the prompts" → chose "apply as defaults"; branch claude/confident-hopper-ef600p,
  draft PR onto 0.09, BROWSER-UNVERIFIED):** the three default system prompts were rewritten
  honesty-first and bumped v1→v2 (provenance versions summary-v2 / translate-v2 / synthesis-v2;
  the EXACT text is still recorded per result in prompt_text, so the change is fully auditable).
  Changes: SUMMARY gains a language pin + investigative-essentials (who/what/when/where/figures)
  + an ATTRIBUTION GUARD ("never turn a claim into a fact") + "if not a coherent article, say
  so" + no-preamble; TRANSLATE pins title+body, paragraph structure, "already in {target} →
  unchanged", no-preamble; SYNTHESIS now REQUIRES a per-claim citation [n] and FLAGS any claim
  carried by only ONE source (its own anti-false-triangulation doctrine, in the prompt). NEW
  `{language}` pin (`_build_prompting(output_language=)`): the SPA passes the current UI
  language as an ENGLISH name (`_LANG_EN` map → "French" not "Français") for summary/synthesis;
  unset → summary "the same language as the article" (faithful — what the standalone reader
  uses), synthesis "English". `output_language` added to Summarize/Synthesize/Bulk requests
  (translate already had target_language). No schema change, no migration, no new i18n keys
  (prompts are backend; Settings textareas show the new defaults via /api/llm/prompts). Tests
  updated v1→v2 across test_llm_api/test_llm_ollama/test_awareness/test_workflow_integration +
  new language-pin + v2-content assertions. Verified py3.13: LLM/reader/invariants/wiring/smoke
  green (the lone failures here were the [analysis]-extra-gated framing + scipy-correlation
  routes returning 404 in this core-only venv — env gap, not the change), ruff F/B clean,
  node --check, i18n 100%.
  **LLM EXPANSION — DESIGN RULINGS 2026-06-17 (maintainer brainstorm; NOT BUILT — record
  for the next session):** scoped to a hypothetical stronger rig (40 GB RAM / 8 GB VRAM, a
  ~30B-class 256K-context instruct model). HONEST FRAME carried into the design: a 30B on
  8 GB VRAM is CPU-bound (~minutes per long pass) so deep LLM work = BACKGROUND VISIBLE
  TASK-MANAGER JOBS (no fabricated ETA — fits the existing job model); a bigger/more-fluent
  model makes mistakes more convincing, so cited + verify-against-source matter MORE, not
  less; model tags stay dated + freshness-tested (never assert a tag we can't verify).
  RULINGS: (1) COMPUTE = TWO TIERS — a fast small model for interactive bits (status pill,
  single summarize) + a heavyweight long-context model for background "deep" jobs, with a
  per-job-class model setting. (2) LONG-CONTEXT UNLOCKS to build (all four, shared plumbing):
  whole-corpus CITED synthesis (50–150 FULL articles in one pass, single-source flagged,
  vs today's 20 excerpts) · corpus Q&A WITHOUT RAG (quoted+cited, refuses when absent) ·
  long SINGLE documents whole (reports/filings/Wikipedia article+revisions/.eml threads,
  consistent terminology) · CROSS-LANGUAGE synthesis (read FR+DE+AR+ZH together). PLUS
  extend the LLM lens to named surfaces: Commodities/Markets/Indices (descriptive cited
  "what the coverage says moved" over the price×coverage overlay — co-occurrence-NEVER-
  causation, NO price prediction/signal; quantitative-claim extraction as candidates),
  Agenda (LLM future-date extraction as confirmable candidates + event briefs), World Law
  (grounded plain-language explainer · version-DIFF narration · cross-jurisdiction
  comparison — long-context shines), WorldMap (place disambiguation/geocode as confirmable
  candidates · place-centric corpus brief), Source integrity (cross-language/PARAPHRASE
  coordination = the strongest LLM-additive where lexical MinHash fails · headline-body
  mismatch · loaded-language spotter — STRUCTURE never intent/credibility, "name the shape").
  (3) LLM SCOPE — **SUPERSEDED 2026-06-18 → AI ANALYTICS NOW LIVE IN OWN TABLES IN THE MAIN DB**
  (maintainer ruled 2026-06-18, weighing UX + performance + the corpus-SELECTION use-case + the
  summaries/translations precedent — REVERSES the strict-physical-separation ruling that follows).
  KEY INSIGHT that decided it: UI integration is DECOUPLED from storage (a separate file is invisible
  to users behind the API; what tipped it was the perf/ergonomics cost of two files for corpus-wide
  AI-signal FILTERING/selection, which has no cross-file SQL JOIN). So AI-derived analytics live in
  their OWN tables in the MAIN corpus DB — table `ai_keyword`, a REAL FK to articles (fast indexed
  JOIN), rendered INLINE in the article view labelled "AI-derived · unreliable" (the existing
  two-class convention). The integrity guarantee is preserved BY CONSTRUCTION (not physical
  separation): own table (NEVER the trusted `keywords`/`keyword_mentions`) + NO score column + model
  provenance + confirm-within-the-lens + an INVARIANT TEST that the trusted rule-based index NEVER
  reads `ai_keyword` (tests/test_ai_layer.py — the index reads only `articles.content`, the same way
  summaries/translations are already safe). MIGRATED 2026-06-18 (branch claude/ai-tables-into-main):
  `src/ai_layer/db.py` (the separate engine) DELETED; `AiKeyword` moved onto the main `Base`;
  store/jobs/api use the main session + the main single-writer gate; migration d0e1f2a3b4c5 creates
  the `ai_keyword` table; the read endpoint no longer file-guards. The 2026-06-17 text below is the
  PRIOR ruling, kept as the record — its "separate file / never-ATTACH / own gate" MECHANICS no
  longer apply, but its HONESTY rules (no score, provenance, never feed the trusted index,
  summaries/translations as the carve-out) STILL hold.
  (3-prior, SUPERSEDED) LLM SCOPE — STRICT PHYSICAL SEPARATION (maintainer RULED 2026-06-17, OVERRIDES the
  earlier same-day "provenance-partition / no separate DB" recommendation — do NOT revert to
  it): the AI must NEVER write to the MAIN database EXCEPT to summarize/translate (those stay
  in article_analyses — the one accepted AI surface in the main store, the maintainer's
  explicit carve-out). ALL OTHER AI-derived analytics (LLM-extracted keywords/entities/claims/
  cross-language dedup) live in a SEPARATE, PARALLEL database — a second encrypted SQLCipher
  file under the SAME passphrase (the one connect() factory), NEVER ATTACHed/joined to the
  main store (article_id is a soft int reference resolved in app code), surfaced ONLY as its
  own clearly-labeled lens, rebuildable + disposable. Maintainer rationale: physical
  separation is a STRONGER guarantee than a provenance column — separate engines can't be
  joined by a forgotten WHERE clause. The trusted RULE-BASED keyword index stays canonical in
  the main DB; the AI keyword layer is the parallel second DB ("a second keyword database to
  manage this parallelism"). Both the read-only lens AND confirmable-candidate curation happen
  WITHIN the AI layer; a confirmed AI item does NOT migrate into the main trusted tables (that
  would "touch main", forbidden by the ruling) — it becomes "confirmed within the AI lens".
  DESIGN TO SETTLE when built: the second file's encryption (same passphrase, no second key
  surface) + its own single-writer gate (own engine; AI writes are batch jobs, no cross-DB
  txn) + backup stance (its own oo-backup member vs excluded-as-rebuildable) + whether a
  user-confirmed AI keyword may EVER cross into the trusted index (default NO). Enforce with an
  invariant test: the main analytics/keyword index NEVER read the AI DB; the AI never writes
  the main store beyond article_analyses summary/translation rows.
  **SCAFFOLD SHIPPED 2026-06-17 (branch claude/llm-two-tier-model, draft PR onto 0.09; backend VERIFIED
  py3.13 — the 7 tests ran GREEN here):** `src/ai_layer/` = the second store. models.py — `AiBase`
  (DeclarativeBase, metadata DISJOINT from the main `Base`) + `AiKeyword` (the "second keyword database":
  soft int `article_id` with NO ForeignKey, term/kind/language, model+prompt_version provenance, a
  `confirmed` flag for confirm-within-the-lens, NO score column). db.py — a SEPARATE lazy engine on
  `data_dir()/ai_layer.db` opened through the ONE `connect()` factory (SQLCipher under the SAME passphrase,
  no second key surface; `OO_AI_DB_PATH` override for tests), its OWN `WriterGate` instance (NOT the main
  process-wide singleton — different file, different write lock), created LAZILY on first use
  (`init_ai_db`) so no empty encrypted file appears for users who never run an AI feature + zero boot-path
  change; `ai_session_scope`/`get_ai_db` release the AI gate. store.py — `record_keywords` (idempotent per
  article+kind+term) / `keywords_for_article` / `set_confirmed`. tests/test_ai_layer.py (7): round-trip +
  confirm-within-lens + the SEPARATION invariants — `AiBase ∩ MainBase = ∅`, article_id has no FK + no
  score column, the AI layer never `ATTACH DATABASE`s nor imports the main ORM, the trusted analytics + DB
  layer never import `src.ai_layer`, and the production path creates a separate file while the AI gate (not
  the main one) serialises the write. mypy +0 (115≤127), ruff clean, packaging auto-includes it (`src*`).
  **FIRST WRITER SHIPPED 2026-06-17 (branch claude/ai-keyword-extraction, draft PR onto 0.09; backend
  VERIFIED py3.13 — the 14 tests ran GREEN here):** the first real consumer of the AI store, proving the
  separation end-to-end. `src/ai_layer/extract.py` — `extract_terms(client, title, content, *, model, …)` +
  `parse_terms` (pure, stub-testable: asks the LOCAL model for salient keywords/entities, cleans list
  markers, dedups case-insensitively, bounds; honest prompt = "output nothing" for an unusable page);
  `EXTRACT_PROMPT_VERSION = "ai-keywords-v1"` recorded per row. `src/ai_layer/jobs.py` —
  `extract_for_articles(work, client, …)` a generator that READS the snapshot + writes AiKeyword rows via
  `ai_session_scope` (NEVER a main session), yielding honest NDJSON progress (invariant #20), idempotent
  skip-existing, commit-per-article (short gate window, never held across the slow LLM call), aborts loudly
  if Ollama goes away mid-run. `src/api/ai.py` (`/api/ai`, wired into the SPINE) — POST `/keywords/extract`
  (streams; selection mirrors the analysis window: article_ids OR query/filters via `_query_articles`;
  Ollama is loopback so NOT consent-gated, airplane refuses at the client), GET
  `/articles/{id}/keywords` (the read-only lens; SIDE-EFFECT-FREE — returns empty WITHOUT creating the file
  if no AI feature ran), POST `/keywords/confirm` (confirm-within-the-lens). tests/test_ai_keyword_extract.py
  (8): parse/extract units, the batch writes the AI store + skip-existing + abort-on-unavailable, and the
  HTTP test PROVES the feature-level separation — after extraction the article has AiKeyword rows but ZERO
  main `KeywordMention` rows. mypy +0 (115≤127), ruff clean, wiring+llm regression green.
  **MIGRATED INTO THE MAIN DB 2026-06-18 (branch claude/ai-tables-into-main, per the (3) reversal above;
  backend VERIFIED py3.13):** the separate `ai_layer.db` is gone — `AiKeyword` is now a main-`Base` table
  (`ai_keyword`, real FK to articles), `src/ai_layer/db.py` deleted, store/jobs/api on the main session +
  the main write gate, migration d0e1f2a3b4c5; the feature-level proof STANDS (the HTTP test still asserts
  ZERO `KeywordMention` for the extracted article) and the invariant test now pins "the trusted analytics
  never read `ai_keyword`". The backup-stance remaining-item is MOOT (ai_keyword now rides the main
  oo-backup-2 automatically). REMAINING: the read-only AI lens UI beside the trusted keywords (backend
  ready); the deep-model tier (1) + whole-corpus cited synthesis (3).
  ALL LLM features keep the standing
  honesty invariants: grounded+cited, refuse-when-absent, no score/verdict/ranking, local
  loopback, provenance recorded, caveats visible, never auto-fed into the pipeline.
  SELF-UPDATE via GUI: consented check vs GitHub releases → signed
  oo-backup-2 + install-tree snapshot BEFORE anything → verified release →
  migrations on a STAGED copy → atomic swap + relaunch → rollback on failure;
  data dir lives outside the code tree so the corpus/settings/keys survive by
  construction; never silently decrypt across an update. 5 open questions filed
  (channel, trust root, cadence, curl|bash-vs-git, mirror-anchoring).
- **THE ONE CORPORA SYSTEM + READER TABS (the flagship analysis object;
  ruled 2026-06-11, extended through 2026-06-12):** one window architecture
  with consistent sub-tabs — **Mindmap · Related articles · Source
  description · Keyword analysis · Sentiment analysis · LINKS** — computed
  over n articles (article = corpus of 1). Corpus-only extra tab: **source
  competitive analysis** (how each source approaches a concept: angle,
  framing, sentiment, volume, timing — real visuals; n=1 has no competition).
  SEVEN entries into the same object: hand-selection ("create a corpus"),
  tag-selection in Sources (multi-tag AND-combination, colored chips),
  tag-click anywhere, commodity-click (graph TITLE → the commodity's keyword
  family corpus with the article timeline OVERLAID on the price curve —
  "what and when to deduce why and how", co-occurrence NEVER causation;
  needs a curated symbol→family seed table), keyword-click (KEYWORDS ARE
  CORPORA — the keyword window adds a related-EVENTS sub-tab: lexical match
  via family↔event titles/tags + temporal match via mentioned-dates ∩ event
  dates, both routes labeled), date-keyword-click, and search-enter. Every
  keyword/corpus window carries a **TIME-SCOPE control** (begin/end/timescale
  — the shipped mind-map date-spectrum control generalized; all sub-tabs
  recompute within the window; n-shown/windowed-PMI discipline + early-corpus
  caveat) because keyword meaning/importance varies through time.
  **LINKS sub-tab (ruled 2026-06-12; SUBSTRATE + WINDOW SLICE 1 SHIPPED T10
  same day: /api/links/shared with the independence notes per shared URL +
  the corpus window — keyword-click entry via the ⊞ Corpus button — with
  Trend (ooChart)/Articles/Links sub-tabs;
  **⚠️ KNOWN DEBT — TWO PARALLEL ANALYSIS WINDOWS (found 2026-06-15 doc audit;
  maintainer ruled "leave it for now" = record as debt, consolidate later):**
  the project has DIVERGED from the "ONE corpora system, one window" ruling into
  TWO overlapping windows — (1) `#an` the search/Enter "analyze" tab (Item I, the
  UI_SHELL §5 flagship: Keywords·Mindmap·Articles·When/Where/Who·Links·Sentiment·
  Sources·Advanced·Source-competitive; absorbed the retired Search tab incl.
  Synthesize/export/signed-evidence; reached from omnibar Enter + commodity ⊞/
  Analyse via openAnalysisFor), and (2) `#corpus-win` the T10 keyword MODAL
  (openCorpus, reached from ⊞ Corpus chips) whose sub-tab set was built out in
  PRs #214-218 (Trend·Articles·Links·Mindmap·Sentiment·Keywords·Sources·
  Competitive) — DUPLICATING five sub-tabs the #an window already had. Cause: long
  session + context summarization lost track of the Item I window. CONSOLIDATION
  NOW IN SCOPE (ruled 2026-06-16 — the 'leave it for now' is LIFTED; built as
  UI-rethink item 4, the named parallel analysis tabs): route openCorpus → the #an
  flagship, port #corpus's Trend + Competitive over, retire the modal ⇒ ONE in-SPA
  analysis window (#an is canonical for the SPA). SEPARATE RULING (fork-1, 2026-06-16):
  the OFFLINE READER (#246, /api/articles/{id}/view) STAYS STANDALONE — its own
  server-rendered page + reader.js/reader.css, NOT folded into #an; the unified window
  serves search/corpus, the reader serves the single article. Two analysis codepaths is
  the ACCEPTED cost; share the article_ids-aware endpoints, NEVER regress the reader's
  tabs.** **EARLIER NOTE: full sub-tab set complete
  on the #corpus modal (PRs #214-218):
  (PRs #214-218, 2026-06-15): Mindmap (reuses renderGraph via a relocatable
  #mm-kit, null-guarded return), Sentiment (reuses /api/framing, VADER
  English-only B1 disclosure), Keywords (ranked table from /api/insights/
  associations, real cooccur/n_b/pmi, no score), Sources (descriptive provenance
  from /api/insights/corpus-sources + catalog, no fabricated description,
  asserted-metadata labeled), Source-competitive (joins corpus-sources+framing:
  volume/tone/timing/emphasis, DESCRIPTIVE not ranking, no winner/score, n=1
  honest state). All reuse existing endpoints (no new backend), the
  function-call-into-host pattern, the TIME-SCOPE precedent (honest full-corpus
  where endpoints lack date params), ×12. REMAINING: the other SIX entry points
  (only keyword-click + palette wired) + Enter→window from search + the
  TIME-SCOPE control on the non-trend sub-tabs + one-click ingestion of linked
  pages.** Earlier REMAINING note (superseded for sub-tabs): which member
  articles SHARE outbound links; one-click ethical ingestion of linked pages for keyword/date/place
  extraction; the goal is the SOURCES' SOURCES. **METHODOLOGICAL RULING
  (anti-false-triangulation): convergence counts as corroboration ONLY when
  the paths are independent — three articles citing the same single origin
  are ONE source wearing three hats. The Links tab surfaces shared-origin
  structure instead of letting citation counts masquerade as independent
  confirmation.** Substrate: article_links (39.8k rows live), citation-graph
  export, the DORMANT external_sources resolution (0 rows live — wire it),
  echo/lineage signals. READER bar (repeated ×2): sleek, data-oriented,
  visually rich, ethical, scientifically driven. The two-class metadata
  header (source-asserted vs app-deduced) already shipped.
  **READER TABS SLICE 1 SHIPPED 2026-06-16 (Tier 1, PR1):** the offline reader
  (`/api/articles/{id}/view`) gained a sub-tab bar — Read · Keywords · Sentiment ·
  Related · Links — via a self-contained `/static/reader.js` + `reader.css`. AUTONOMOUS
  ARCHITECTURE CALL: the reader is a STANDALONE server page that doesn't load the SPA
  bundle, so it gets its OWN small module (chosen over routing the article into the
  in-SPA #an window — that would brush the deferred two-windows consolidation debt).
  Read/Related/Links reuse the already-server-rendered sections (now tab panes);
  Keywords + Sentiment LAZY-fetch the article_ids-aware insights endpoints
  (corpus-keywords / corpus-sentiment) at n=1 (article = corpus of 1) — counts only
  (no score), method + the VADER English-only caveat VISIBLE by default (B1). The
  reader page is English-only (no i18n engine there — consistent with the existing
  reader; the SPA chrome is the i18n target). tests/test_reader_tabs.py + node --check.
  **MINDMAP TAB SHIPPED 2026-06-16 (PR1b):** `/api/insights/graph` now accepts
  `article_ids` (overrides term/level) → a NEW `queries.article_graph` builds a
  DETERMINISTIC RADIAL keyword map over the exact article set (centre = the
  most-mentioned keyword, arms = the rest sized by mention count, every edge
  centre→arm = always OUTWARD, the mind-map rule, no cross-tangle), reusing
  `corpus_keywords` (same hidden-word policy + spread ordering, counts only — NO
  score). The reader's new Mindmap tab (between Keywords + Sentiment) lazy-renders a
  self-contained themed SVG in reader.js (labels OUTSIDE the nodes for contrast,
  role=img + aria-label, "+N more" honesty, method + caveat visible); reader stays
  STANDALONE + English-only. tests: `test_article_graph_is_a_deterministic_outward_radial`
  + the endpoint contract + the tab structure. **SOURCE PROFILE TAB ALSO SHIPPED
  2026-06-16 (same PR):** a SERVER-RENDERED "Source" pane (like Related/Links, no
  extra fetch) showing the source's catalogue provenance (name · domain · place ·
  type · language · tags) + its corpus FOOTPRINT ("N articles collected from this
  source") — DESCRIPTIVE only, NO score/ranking/verdict (reliability_score
  deliberately not shown, per the operator-set guard). Reader tabs are now
  Read·Keywords·Mindmap·Sentiment·Related·Source·Links; When/Where/Who already live
  in the Read pane, so the reader-tabs flagship (RC-BLOCKING) is essentially complete.
- **SEARCH = ONE CENTRAL ANALYTICAL TOOL (field reports #3/#4 + 2026-06-12
  refinements; supersedes-and-extends the 2026-06-10 global-search design):**
  instant index-backed omnibar (never scan-on-type), federated over articles
  (FTS5), keywords/families, sources, events, docs, AND the UI itself (a
  generated registry). Typing → bubble with the first THREE results,
  clickable; ENTER → a CORPUS-OF-ARTICLES window (the corpora system) with
  the standard sub-tabs PLUS the search-only **Advanced search** tab
  (select/sort by dates, keywords, sources, source tags, region, language).
  Boolean operators ("AND OR +"…) reminded DISCREETLY or via hover popup.
  **DATE SEARCH first-class with a CALENDAR PICKER; PERIODS searchable, not
  only single dates** (a period search = a date-range corpus; the SAME
  begin/end/timescale component as the time-scope control — built once).
  TYPO TOLERANCE for keywords AND dates with the honest did-you-mean:
  "Prsident" → show "President" results while offering "search 'Prsident'
  literally" — NEVER silently substitute. SECURITY stance recorded: the
  UI/menu index holds nothing sensitive; the corpus already lives in FTS5 in
  the same (now encryptable) SQLite file. **The Search tab is REMOVED from
  the sidebar ONLY after the Enter-popup absorbs every Search-tab capability
  (boolean queries, filters, result export, signed-evidence export, LLM
  synthesize) — the Desk lesson: never silently lose a tool.**
  **SLICE 1 SHIPPED (T13, 2026-06-12):** /api/search/omni — index-backed
  federation (articles FTS5 relevance-ordered, keywords via the
  normalized-term prefix index, sources/wiki/law bounded catalogs), first
  THREE per group with TRUE totals disclosed in the group header; half-typed
  Booleans fall back to a phrase match (never a 400 mid-keystroke); LIKE
  wildcards escaped. The Ctrl/⌘-K palette IS the omnibar: static
  pages/actions/docs stay instant, live data groups append debounced +
  sequence-guarded; article→LOCAL reader (invariant #6), keyword→the T10
  corpus window, "Run the full Boolean search" leads to the Search tab
  prefilled (nothing lost); discreet Boolean hint with the hover long-form;
  +8 strings ×12 (2 placeholders reworded). REMAINING: Enter→corpus-of-
  articles window + Advanced-search tab (absorption gate), date/period
  search with the calendar picker, typo tolerance with honest did-you-mean,
  events/docs-content groups.
- **DDG-DISCOVERED INGEST FROM ADVANCED SEARCH (ruled 2026-06-13, maintainer
  concept):** the Advanced-search tab of the analysis window gains an opt-in
  "search + scrape the top X DuckDuckGo results" action. Results are ingested
  AS ARTICLES through the normal path (real source = the actual domain,
  metadata, links, keywords, When×Where×Who) PLUS an INDIRECT-SOURCE provenance
  record: discovered-via-DDG + exact query + search date + result RANK + DDG
  region. GUARDRAILS (binding): (1) every result fetched through the
  EthicalFetcher — robots fail-closed, per-host rate limit, kill switch, proxy
  (the guarded path, shipped item 3); results that robots-disallow are skipped
  with the honest transport-aware verdict; (2) network action ⇒ ONE consent
  popup + a VISIBLE task-manager job, off by default; (3) DDG-discovered
  articles are a DISTINCT, FILTERABLE provenance class (like per-edition wiki
  sources) — never silently blended into trust-sensitive views, so the user
  sees and can exclude DDG's ranking bias; (4) RANK is a first-class stored
  signal (DDG ranking is an algorithmic bias, not noise); (5) DE-DUP against
  the corpus bit-for-bit — an already-present result GAINS the discovery
  provenance (multi-path), never a duplicate; (6) DISCLOSE the aggregator bias:
  "top X DDG results" skews toward what ranks well (SEO/popular/often
  English/commercial) — convenience discovery, NOT a representative sample;
  stated in the UI so it cannot quietly undo the de-US-centring balance work.
  BONUS FUTURE SIGNAL (recorded, not now): re-running a stored query over time
  and diffing ranks = ranking-drift / promoted-vs-buried detection — free from
  the (query,date,rank) provenance already stored. Fits DDG = the ONE
  sanctioned external channel (extends discover-sources to discover+ingest,
  user-driven). Lands in Group F (entry) + Group B (ingest mechanics).
- **i18n & LANGUAGE UX (field report #3 + standing; SWITCHER SHIPPED T7 —
  invariant #15):** the chrome-audit burn-down is ELEVATED
  (`scripts/i18n_report.py --audit-chrome` per tab, every session, until ~0
  — the maintainer keeps hitting untranslated surfaces and "cannot test
  EVERYTHING" alone; long tail ~423 untranslatable UI strings at 2026-06-14
  count, 263 keyed of 686). URL anchors
  stay language-neutral code identifiers (labels translate, anchors don't);
  #markets-vs-#commodities folds into the index/commodity reclassification
  (alias pattern like #database→#library). Easter eggs gain FRENCH references
  while staying transnational/translatable (personality.yml). Home-card
  TITLES are still server-built English — template-based title translation
  needs a design (titles carry data values). **ELEVATED (maintainer REPEAT
  2026-06-13, via the untranslated #onboard card: "like other cards" —
  card strings must enter the UI translations).** #onboard CARD DONE
  2026-06-14 (h2/p/button keyed ×12; the engine auto-translates the static
  card once keyed); REMAINING here = the server-built home-card TITLES.
  **LONG-TAIL BURN-DOWN — SLICE 1 SHIPPED 2026-06-17 (ruling #8 PROCEED; draft PR onto 0.09):**
  the WATCHES panel (ruling-#3 on-by-default feature, shipped this session English-only) is now
  fully keyed ×12 — heading + Lead-when-it-matches suffix, the honesty intro paragraph (its inline
  `<em>` emphasis dropped so it keys as ONE clean sentence per the codebase's full-sentence
  convention — fragment-keys translate badly), the form labels (Condition/Min articles/Window),
  Add watch · Check now + its hover, and the example placeholder. +10 keys ×12 (`src/static/locales/*.json`;
  non-en AI-drafted, FLAGGED for native review, Lead-word reuses the shipped rename fr piste/de Spur/…).
  MECHANISM CONFIRMED + reusable for the next slices: the engine keys on the English string and
  auto-walks DOM text + the translated ATTRS (title/placeholder/aria-label), so a STATIC single-text-node
  string becomes translatable by ADDING locale entries only — zero JS change; interpolated JS strings
  (the dynamic `loadWatches` rows) still need `t()` and stay English for now. `--audit-chrome` 431→417;
  `--min 100` green (1166/1166 ×12); test_repo_invariants green. REMAINING: the other recently-shipped
  panels (Statistics/Models/Newsletters/Offline-map) + the dynamic `loadWatches` rows + the ~417 tail.
  **SLICE 2 SHIPPED 2026-06-17 (draft PR onto 0.09):** the live-MAILBOX sub-panel (Settings → Newsletters,
  the IMAP/POP3 pull, ruling #11 — the feature the maintainer is eager to test) is now keyed ×12 (the
  .eml-import half was already keyed). +14 keys ×12: the "Pull from a mailbox (IMAP/POP3)" heading + its
  two honesty paragraphs (the live-pull description + the network/TLS/not-Tor/creds-not-stored warning —
  its inline `<em>not</em>` dropped so it keys as ONE sentence, same convention as slice 1), the form
  labels (Protocol/Host/Port/User/Password/Folder (IMAP)/Max messages), the "auto" port placeholder, and
  the "Pull newsletters" button. `--audit-chrome` 417→402; `--min 100` green (1180/1180 ×12);
  test_repo_invariants green. Non-en AI-drafted, FLAGGED for native review. REMAINING: Statistics/Models/
  Offline-map panels + the dynamic JS rows + the ~402 tail.
  **SLICE 3 SHIPPED 2026-06-17 (draft PR onto 0.09):** the OFFLINE-MAP panel (Settings → Offline map, the
  OSM region-download manager) keyed ×12. +5 keys: "Offline map regions" heading, the big managed-like-
  wiki-dumps description paragraph (its inline `<em>dated estimate</em>` dropped → one sentence), the
  "Loading regions…" placeholder, the sizes-are-estimates note, and the downloading-is-a-network-action
  consent paragraph (Region/Download/reviewed were already keyed; osm-region is already excluded from the
  dropdown-label test as dynamic data). `--audit-chrome` 402→395; `--min 100` green (1185/1185 ×12);
  test_repo_invariants green. Cumulative this session 431→395. Non-en AI-drafted, FLAGGED for native review.
  REMAINING: Statistics/Models panels + the dynamic JS rows + the ~395 tail.
  **SLICE 4 SHIPPED 2026-06-17 (draft PR onto 0.09):** the STATISTICS panel (Settings → Statistics, the
  official-figures fetch / vintage / triangulate UI, rulings #12) keyed ×12. +13 keys: "Official figures"
  heading, the big provenance/vintage/side-by-side-never-averaged/no-score intro paragraph (its two inline
  `<b>` dropped → one sentence) + its `<span class="warn">` networked-action sentence kept separate, the
  form labels (Indicator/dataset id · Country (World Bank) · View stored figures — series id), the buttons
  (Fetch figures · Show stored · Triangulate producers · Refresh due now) + the Refresh hover, the "Tracked
  for auto-refresh" heading, and the auto-refresh paragraph (its `<em>vintage</em>` dropped). statfig-source
  is already excluded from the dropdown-label test (World Bank/Eurostat = proper-noun data). `--audit-chrome`
  395→377; `--min 100` green (1198/1198 ×12); test_repo_invariants green. Cumulative this session 431→377.
  Non-en AI-drafted, FLAGGED for native review. REMAINING: Models panel + the dynamic JS rows + the ~377 tail.
  **SLICE 5 SHIPPED 2026-06-17 (draft PR onto 0.09):** the MODELS/LLM panel (Settings → Models, the Ollama
  management subtab, ruling on the in-app installer) was MOSTLY already keyed from a prior session — this
  FINISHES it: +3 keys (the "Pull any model tag" label, the intro paragraph, the pull-network-action hint).
  The intro paragraph was RESTRUCTURED so its functional `ollama.com/library` link sits at the END (instead
  of mid-sentence), letting it key as ONE clean sentence instead of two un-translatable fragments around the
  anchor (the link-in-prose pattern; conservative reorder, meaning preserved); the network hint dropped its
  `<strong>`+`<em>not</em>` → one sentence. `--audit-chrome` 377→371; `--min 100` green (1201/1201 ×12);
  test_repo_invariants green. Cumulative this session 431→371 (5 panels: Watches·mailbox·offline-map·
  statistics·models). Non-en AI-drafted, FLAGGED for native review. REMAINING: the Wikipedia/agenda/safety
  panels + the dynamic JS rows (need `t()`) + the ~371 tail.
  **SLICE 6 SHIPPED 2026-06-17 (draft PR onto 0.09):** the WIKIPEDIA panel's TRACKING half (Settings →
  Wikipedia: change-tracking + watch-a-page + flagged-changes; the offline-baselines section is the next
  slice) keyed ×12. +10 keys: the two section headings + the change-tracking intro paragraph (de-tagged
  `<strong>`/`<em>`) + "use ORES scores" + the offline-baselines pointer hint (de-tagged `<strong>`×2) + the
  "Watch a page" heading + Watchlist + optional + the long "Watched pages join your corpus…" hint AND its
  `title` why-these-choices essay (the engine translates titles too) + "Flagged changes"/"flagged only"/
  "Edition filter" (wiki-lang + dump-lang already excluded from the dropdown-label test as edition data).
  `--audit-chrome` 371→353; `--min 100` green (1211/1211 ×12); test_repo_invariants green. Cumulative this
  session 431→353. Non-en AI-drafted, FLAGGED for native review. REMAINING: the Wikipedia offline-baselines
  section + agenda/safety panels + the dynamic JS rows + the ~353 tail.
  **SLICE 7 SHIPPED 2026-06-17 (draft PR onto 0.09):** the WIKIPEDIA offline-baselines section (dump
  download + filter help) keyed ×12 — COMPLETES the Wikipedia panel. +6 keys: "Wikipedia offline baselines"
  heading, "Language edition", "Loading editions…", "Estimate size", the big current-text-dump intro
  paragraph (de-tagged `<em>`×2 → one sentence) and the filter-help hint (de-tagged `<strong>`/`<em>`). The
  "Read a page from a downloaded dump" subsection was already keyed from a prior session. `--audit-chrome`
  353→342; `--min 100` green (1217/1217 ×12); test_repo_invariants green. Cumulative this session 431→342
  (7 slices: Watches·mailbox·offline-map·statistics·models·wiki-tracking·wiki-baselines). Non-en AI-drafted,
  FLAGGED for native review. REMAINING: agenda/safety panels + the dynamic JS rows (need `t()`) + the ~342 tail.
  **SLICE 8 SHIPPED 2026-06-17 (draft PR onto 0.09):** the MODELS-BACKUP section (Settings → Data & backup,
  "Local LLM models (separate backup)") keyed ×12 — closes the explicit follow-up flagged in the
  backup-ollama-models entry ("the models-backup Settings UI strings are not yet i18n-keyed"). +5 keys (the
  heading, the Ollama-models-live-outside-the-corpus paragraph, "Checking the local model store…", "Download
  models backup", "Restore models…"); no HTML edit needed (no inline tags). VERIFIED ALREADY-KEYED (prior
  sessions, no work): the adjacent Backup & restore / Full-backup / Restore-merge sections, and the entire
  agenda Calendars panel (only a stray "Filter" remains there, deferred). `--audit-chrome` 342→337; `--min 100`
  green (1222/1222 ×12);
  test_repo_invariants green. Cumulative this session 431→337 (8 slices). REMAINING: the custody/uninstall/
  panic/OTS safety strings (sensitive wording — best with native review) + the dynamic JS rows + the ~337 tail.
  **SLICE 9 SHIPPED 2026-06-17 (draft PR onto 0.09):** the CHAIN-OF-CUSTODY section (Settings → Safety, the
  security-critical custody/OpenTimestamps panel) keyed ×12 — the whole section was unkeyed. +11 keys: "Chain
  of custody" heading + intro (de-tagged `<em>`), "Loading custody settings…", "Post-quantum signatures" + its
  ML-DSA/FIPS-204 hover, "OpenTimestamps anchoring" + its Bitcoin-anchoring hover, "Auto-log on ingest", the
  OTS IP/timing PRIVACY WARNING, "Default actor", "Save custody settings". SECURITY-CRITICAL wording (IP/timing
  disclosure, hash-only, Tor routing, unrecoverability) translated CAREFULLY preserving the exact technical
  claims — but the non-en is still AI-drafted and these warnings ESPECIALLY want native review (a mistranslated
  security warning = a misleading assurance; better readable-in-language-flagged than an unreadable English
  wall). `--audit-chrome` 337→326; `--min 100` green (1233/1233 ×12); test_repo_invariants green. Cumulative
  this session 431→326 (9 slices). REMAINING: the uninstall/panic safety strings + the dynamic JS rows + the
  ~326 tail.
  **SLICE 10 SHIPPED 2026-06-17 (draft PR onto 0.09):** the PANIC-WIPE + UNINSTALL paragraphs (Settings →
  Safety) keyed ×12 — most of that section (Panic wipe / Wipe everything now / Uninstall mode + its options /
  the checkboxes / Download a backup first / Customize…) was ALREADY keyed; this adds the 4 that weren't: the
  "Uninstall the app" heading, the "Uninstall & stop the app" button, the security-critical panic paragraph
  (irreversible wipe · "cannot be undone" · SSD/flash-unrecoverability · LUKS/Qubes/Tails — de-tagged
  `<strong>`/`<em>`), and the uninstall paragraph (RESTRUCTURED so its `<code>./install.sh --uninstall</code>`
  command sits at the END, keying as one sentence). Same security-warning native-review caveat as slice 9.
  `--audit-chrome` 326→312; `--min 100` green (1237/1237 ×12); test_repo_invariants 63 passed. ALSO this
  round: caught + fixed a BASE-RED on 0.09 (PR #355) — two agenda invariants went stale after the merged
  "drop the useless 'imported' category" rework (39353cf): AG.categories is now
  `[...new Set((fac.categories||[]).concat(importedKinds))]` and imported events use their feed's real kind +
  the `imported: true` flag (not a `category:"imported"` literal); updated both assertions to match the
  merged code (test-only, intent preserved). Cumulative this session 431→312 (10 slices). REMAINING: the
  dynamic JS rows (need `t()` + browser click-through) + the ~312 scattered tail.
  **SLICE 11 SHIPPED 2026-06-17 (draft PR onto 0.09):** the COLLECT Settings panel (scheduler + manual + batch
  ingest) keyed ×12 — CORRECTS the earlier "remaining is dynamic-JS" read: a classification pass found 265 of
  the 312 remaining audit strings are STILL static index.html (zero-risk keyable), 0 are app.js-only, 47 in
  reader/other files. +26 keys (all clean single-text-node labels/buttons + 3 honesty paragraphs: the
  collection-speed concurrency title, the recursive-crawl bound, the batch-ingest intro — no HTML edits needed,
  no inline tags). `--audit-chrome` 312→286; `--min 100` green (1263/1263 ×12); test_repo_invariants 63 passed.
  Cumulative this session 431→286 (11 slices). REMAINING static clusters (per the classification): Insights tab
  (~51), Markets (~35), Sources Settings (~23), integrity/law/search/timemap tabs + the reader/other files (47).
- **MARKETS REVAMP — MAINTAINER VISION 2026-06-17 (the unified twin-board ask; ALL 6 SLICES
  SHIPPED + MERGED to 0.09 — #312/#314/#318/#320/#321/#324; see the per-slice log below):** the maintainer wants Commodities + Indices
  to become NEARLY-IDENTICAL twin boards (only the data differs) with: (a) all-continent
  index coverage; (b) CATEGORY subtabs (Indices: continents + tags; Commodities: its
  categories) via the ooSubtabs grammar; (c) AGGREGATE several curves onto ONE graph
  (multi-series overlay; reuse ooChart + the indexed/`opts.indexed` mode I built for the
  combined-trend overlay) handled ELEGANTLY; (d) CHANGE graph SCALES (indexed/log for
  different magnitudes); (e) CLEAR timescale legends + COHERENT shared time axis across all
  sources (commodities' per-source ranges must align); (f) in the "All" subtab, consider
  STACKING curves into FAMILY graphs (group by category/continent → fewer, denser graphs);
  (g) REMOVE the Load/Refresh button — market data loads AUTOMATICALLY in the background
  (like the auto-index #21 / auto-collect patterns). SHIPPED THIS SLICE: (1) INDEX CATALOG →
  ALL CONTINENTS — `configs/index_feeds.yml` went 6→25 indices: the 6 named US/Japan (FRED)
  KEPT, plus 19 FRED·OECD MEI share-price indices (`SPASTT01<ISO3>M661N`, monthly, base
  2015=100) across Europe/Asia/N.America/S.America/Africa/Oceania. HONESTY: the NAMED world
  indices (DAX/FTSE/Hang Seng…) are NOT on a free robots-PERMITTING daily feed (Stooq
  robots-disallows — the removed-feeds reason), so the OECD share-price index is the
  ethically-fetchable per-country proxy, labelled `unit: idx` (vs named `unit: pts`); the
  OECD FRED IDs were NOT live-verified here (no network — 403) → flagged "verify on a
  networked box; fails LOUDLY if wrong" per the file's standing note. `Feed` gained
  `continent` + `tags` (both loaders + to_dict) = the board's category facets;
  tests/test_index_catalog.py (all-6-continents, named-vs-OECD unit).
  **SLICE 1 — AUTO-LOAD (background feed-import, remove Load/Refresh) SHIPPED 2026-06-17 (draft PR
  onto 0.09; backend testable, frontend browser-unverified):** the scheduler `markets` pass now also
  imports the curated CSV feeds (commodities + indices) via `pipeline.import_due_feeds`, FRESHNESS-
  GATED — a feed is due only when its latest stored `CommodityPrice` point is stale for its cadence
  (daily named/commodity >1 day; monthly OECD `unit='idx'` >25 days; no data = always due), so a pass
  never re-fetches an unchanged series. Kill-switch/robots/transport via the EthicalFetcher; one
  feed's failure never aborts the pass (rollback + tally). Wired at runner.py:356 after run_rules
  (returns `feeds_imported`). The manual "Load / refresh indices" + "Load / refresh market data"
  buttons (index.html 531/549) are REMOVED, replaced by an "Updates automatically in the background."
  note; the board still renders on tab-show and the one-time onboarding import seeds first-load (the
  loadIndicesData/loadMarketData handlers are left orphaned-harmless). tests/test_market_autoload.py
  (freshness gate: only stale + never-seen feeds fetched; skips here — markets pipeline imports
  feedparser, absent in the sandbox — runs in CI). i18n 100%; node --check clean.
  **ALL 6 UI-REVAMP SLICES SHIPPED + MERGED to 0.09 2026-06-17 (browser-unverified per fork-3 —
  node --check + a new test_repo_invariants test per slice + i18n 100%; each needs a human
  click-through):** Slice 1 AUTO-LOAD (#312, above). Slice 2 CONTINENT/TAG SUBTABS (#314): the
  Indices board groups by CONTINENT via ooSubtabs (the commodities-category analog) + a secondary
  TAG-chip AND-filter; `/api/markets/board` now emits `continent`+`tags` per card so the UI facets
  without a re-fetch (test_indices_category_subtabs). Slice 3 COMPARE OVERLAY + SCALES (#318): a
  multi-select "Compare" on the Indices cards opens ONE ooChart overlay of the real series via the
  shared #chart-enlarge dialog with an Absolute/Indexed/**Log** scale toggle; ooChart gained an
  ADDITIVE `opts.logY` (log10 y-axis, vt/vtInv identity-when-off so every existing chart is
  byte-unchanged — same contract as opts.indexed); chartEnlarge gained an optional 4th `opts` arg
  (test_indices_multiseries_compare). Slice 4 COHERENT AXIS + LEGENDS (#320): `dashChartSvg` gained
  an ADDITIVE shared `[t0,t1]` time axis (date-based point placement) so every commodity card aligns
  on ONE calendar axis (a monthly + a daily series cohere); index-based fallback is byte-identical
  (Home sparklines/trends unchanged); each Indices spark gained a start→as-of `.idx-range` legend
  (test_markets_coherent_time_axis_and_legends). Slice 5 FAMILY-STACKED GRAPHS (#321): a reusable
  `renderFamilyGraphs` draws ONE multi-series ooChart per category (indexed default + visible
  "relative not absolute" caveat); a Cards/Families toggle on the commodities board defaults to Cards
  (no regression); family blocks carry `.mkt-cat`/data-cat so the subtabs filter both views
  (test_markets_family_stacked_graphs). Slice 6 TWIN-BOARD PARITY (#324): the Families view +
  ooTimeScope time-range control come to the Indices board reusing renderFamilyGraphs/ooTimeScope/
  windowPricesRange/fetchPrices (one ooChart per CONTINENT, lazy full-series load only when Families
  is opened, Cards view untouched); both boards now share continent/category subtabs · tag chips ·
  compare overlay+scales · families view · time-range control · the coherent shared axis
  (test_markets_twin_board_parity). ALSO this batch: the manual loadIndicesData/loadMarketData
  handlers are orphaned-harmless (buttons gone); new strings flow through `t()` (English fallback,
  keyable later — i18n gate stays 100%). REMAINING (flagged, low-priority): the indices CARDS still
  use the compact spark (commodities cards use the larger dashChartSvg) — a cosmetic card-rendering
  unification; commodities could gain a tag facet for full symmetry; the new English-fallback strings
  want keying; and a human click-through across themes/breakpoints (no headless harness here).
  **GRAPH "co-occurrence … never causation" CAVEAT REMOVED (maintainer ruled 2026-06-17 —
  REVERSES the earlier "binding visible caveat" on charts; it cluttered every graph):** all 6
  on-graph mentions of `t("co-occurrence in your corpus, never causation")` removed from
  src/static/app.js — the commodity-card caveat div, the Price×coverage head span, the two
  combined-trend caveats (the method note KEPT: "Article counts on a shared time axis." /
  "Indexed to 100 … real value."), and the two "Analyse" title parentheticals. The
  non-causation PRINCIPLE still governs the design (comments updated, not deleted). The PMI
  table's distinct "association strength, not causation" note is LEFT (a real stat caveat on
  that column, not a graph). The two test_ui_invariants assertions that REQUIRED the caveat
  were INVERTED to assert its ABSENCE (regression guard against re-adding). i18n stays 100%
  (old keys orphan harmlessly; the trimmed method strings show English until re-keyed — minor,
  flagged). node --check clean.
- **MARKETS/INDICES/COMMODITIES (consolidated; TOOLKIT SHIPPED T8 slice 1 —
  invariant #16; INDICES DETAIL SHIPPED PR #205 — the Indices board gained a
  click→detail chart via ooChart on the full series (commodity-card "enlarge" was
  already the ooChart detail path, no separate enlarge existed); REMAINING:
  timemap-adjacent charts):** Commodities cards render the real curve at every
  timeframe (drop the "· 5 pts" suffix); axes detailed; discrete gridlines.
  **COMMODITIES TAB REWORK (ruled 2026-06-13, field session):** (1) split the
  board GRAPHS INTO CATEGORY TABS (the universal subtab grammar — UI plan §1);
  data-oriented presentation. (2) REPLACE the 5-choice time-scale select
  (index.html:1207-1208 — 1mo/6mo/1yr/5yr/all) with the SAME sophisticated
  begin/end/timescale TIME-SCOPE control built once for corpora/search — a
  real, intuitive range UI, not 5 buttons. (3) DATA-POINT BUG — FIXED 2026-06-14:
  the per-card SVG was full-resolution within the window (good), BUT a
  sparse-series fallback silently swapped in the ENTIRE history when a window
  held <2 points, so a NARROW window (1 month) on a sparse monthly series dumped
  the full 5-yr history while "1 year" showed ~12 — the smallest scale
  paradoxically showed the MOST points. FIXED per invariant #16: renderDashboard
  now RESPECTS the window (the pts=all expansion is gone) and dashChartSvg renders
  honestly — a connecting line ONLY when dense (lineMin=8), otherwise discrete
  DOTS with n + the early-corpus caveat (reused keyed string, ×12), 0 points =
  "not enough points in this window"; never a curve faked through a handful of
  points. Enforced by test_ui_invariants #16. COMMODITIES ITEM STATUS: (1) category
  subtabs SHIPPED (ooSubtabs `_mktCatTabs`/`selectCommodityCat`, data-driven from
  `s.category`, "All" default lens), (2) the time-scope range control SHIPPED
  (ooTimeScope, PR #197), (4) click-a-graph → the analysis window SHIPPED (title ⊞ +
  "Analyse ↗" → openAnalysisFor). PRICE × COVERAGE OVERLAY SHIPPED 2026-06-16 (Item 3,
  conservative/browser-unverified): the analysis window gained a commodity-GATED Price
  subtab (`#an-price-tab`/`#an-price`, hidden unless `_anCommodity` is set) — the card
  passes `{commodity:{symbol,name,unit}}` through openAnalysisFor's new opts arg, and
  `commodityOverlaySvg` draws a TRUE time-aligned DUAL-AXIS SVG: the PRICE curve (left
  axis, line + real sample dots) over the corpus COVERAGE (right axis, bars from
  /api/insights/trend) on a SHARED time X — each series on its OWN labelled scale (no
  magnitude conflation, no fabricated shared baseline), reusing existing endpoints (no
  new backend). The co-occurrence-NEVER-causation caveat is VISIBLE; honest empty states
  (no price / no coverage). +3 i18n ×12 (Price · Price × coverage · No corpus coverage to
  overlay yet.); test_ui_invariants #22b. Precision limited ONLY by gathered data +
  renderer. REMAINING: S&P500 is an INDEX, not a commodity — reclassify; expand feeds
  (rare earths, oil, gas, LNG, sand, cereals, sugar…); the bottom-of-page #mkt-chart
  price-detail (chartSymbol) stays as the in-place detail (the Desk lesson — not removed).
  **COMBINED TIME-ALIGNED TREND OVERLAY (maintainer concept + ruling 2026-06-17; BUILT
  on branch `claude/analysis-trend-overlay`, draft PR onto 0.09, BROWSER-UNVERIFIED):**
  maintainer asked to AGGREGATE/overlay everything that shares the common TIME axis —
  "when searching for a keyword, in the analysis, only one graph with all of the
  keyword's related tags/keywords (middle east → petrol)". RULING (AskUserQuestion):
  for CROSS-UNIT series do BOTH option 1 (indexed overlay) AND option 3 (dual-axis);
  same-unit series overlay on one shared axis regardless. SHIPPED: a new **Trend
  subtab** in the #an analysis window (`data-tab="trend"` / `#an-trend`) overlays the
  searched keyword + its top related keywords/tags (all article COUNTS = ONE honest
  shared axis) via the EXISTING multi-series `ooChart`; related terms from
  /api/insights/associations, each series from /api/insights/trend (no new backend). A
  **Counts ↔ Indexed** toggle: Indexed adds a STRICTLY-ADDITIVE `opts.indexed` to ooChart
  that rebases each series to 100 at the visible-window start (`pv()` transform; identity
  when off, so EVERY existing chart is byte-unchanged — test_ui_invariants stays green),
  letting commodity PRICE series (different unit) co-move on one axis WITHOUT conflating
  magnitudes; the hover still shows the REAL value, and a VISIBLE `.card-caveat` states
  "indexed · relative not absolute · co-occurrence in your corpus, never causation". The
  precise **dual-axis** (option 3) reuses the shipped `commodityOverlaySvg` (price left /
  coverage right, each own real-unit scale) for the first picked commodity. "Middle East
  → oil" auto-suggestion = `commoditiesForTerm` (reverse of the COMMODITY_QUERY seed,
  deterministic whole-word match; never fabricated) + a full commodity picker. +12 i18n
  ×12 (AI-drafted non-en, flagged); tests/test_an_trend_overlay.py + node --check; full
  pytest needs py3.13 (CI). REMAINING: time-scope windowing of the combined trend; richer
  keyword↔commodity associations; fold the parallel #corpus-win Trend into #an (the
  two-windows debt). **Tor/indices diagnosis
  (logs analyzed 2026-06-12) — SHIPPED in T4:** transport-aware verdict
  taxonomy (refused ≠ robots-disallowed ≠ dead-series ≠ unreachable ≠
  offline) + one bounded feed-level retry for transient verdicts only +
  "Retry failed feeds" (import-all?keys=) + per-feed verdicts on both boards
  + the USER_MANUAL Tor chapter. REMAINING: GOLD/SILVER/SAWNWOOD replacement
  FRED ids still need CLEARNET VERIFICATION before swapping (the dev
  container's network allowlist blocks fred.stlouisfed.org — verified
  2026-06-12; they now surface honestly as dead-series meanwhile).
  Stooq + webcal.guru robots-disallow = honest fail-closed (host policy).
  Per-index verdicts shown in the Indices UI (degrade loudly). 32/50 sources
  worked over Tor; the app serves BOTH populations (clearnet breadth; Tor
  subset clearly labeled; USER_MANUAL gains a "running over Tor" chapter).
  Ethics position recorded: prefer Tor-tolerant OFFICIAL endpoints (FRED
  API, SDMX, exchange open data, archives); truth-seeking is not
  self-certifying — the METHOD is the ethics; against hostile digestion the
  defense is REPRODUCIBILITY, not secrecy.
- **KEYWORD POLICY (field report #4, 2026-06-12 — export analyzed, first fix
  shipped):** maintainer position: NOT a fan of capping; data crunching uses
  as many keywords as possible; if a cap ever became necessary it must be
  DYNAMIC (the ChatGPT-2020 example: novel rising terms always capturable).
  The ruled instrument is the EXCEPTION POLICY for function words in ALL
  corpus languages — SHIPPED: evidence-based stoplists ×16 catalog languages
  + inflection/month pass (extract.py; global_stopwords applies at query
  time ⇒ 704 rows / 71,854 mentions retroactively hidden, no migration;
  en+fr were already clean; junk ≈ 6% of mentions ⇒ capping would buy
  little; NO CAP stands). The three queued systemic findings SHIPPED (T3,
  2026-06-12): source SELF-NAMES suppressed at index time as a per-article
  RULE (_self_name_forms: full name ± leading article + domain labels; other
  sources' mentions of the outlet STAY — re-indexing applies retroactively);
  per-source concentration suspects in the diagnostics export (≥90% one
  source, ≥25% of its articles, both ≥10 — flagged with real counts, never
  auto-hidden); language_mismatch flag per keyword (stored vs dominant
  signature language — evidence, not a correction).
  **KEYWORD-LOG OPTIMIZATION LOOP — TOOL + BATCH SHIPPED 2026-06-16 (draft PR onto
  0.09; operationalizes the maintainer's "the logging system creates manageable
  documents you can ingest" intent):** `scripts/analyze_keyword_log.py` (stdlib-only,
  runs without the app installed) ingests a `keyword-diagnostics` export (oo-export-1)
  and emits REVIEW-ready proposals — net-new per-language stopword candidates (diffed
  vs the live `_EXTRA_STOPWORD_TEXT`+stopwords.py, split high-confidence vs review using
  language_signature CONCENTRATION so names/loan-words that SPREAD demote to review),
  weekday leaks, cross-source + per_source_concentration boilerplate, sentence-initial
  false-entity candidates, cross-language ring candidates (top-concepts-per-language for
  hand-mapping + LOW-confidence cognate hints), and singular/plural family-merge pairs.
  It PROPOSES, never edits data (honesty by construction). FIRST BATCH APPLIED from the
  2026-06-14 export (1,201-art corpus): a new dated `_EXTRA_STOPWORD_TEXT` block adds the
  surfaced FUNCTION words ×14 langs (de können/sondern, ru чтобы/которые, hu szerint/
  pedig, id dalam/oleh, sl tudi/kot, ar خلال/قبل, it/pt/pl/da/sr/es/fr…), the missing
  WEEKDAY names ×16 langs (the month passes never covered weekdays — "Sunday"/"sábado"/
  "lørdag" were top keywords), and sr comment-widget + da paywall BOILERPLATE; applied
  retroactively at query time (no migration/re-index). Cross-language COLLISIONS
  deliberately omitted (sea/tom/fin/laut — global_stopwords() is unioned across all
  langs). tests/test_keyword_log_analyzer.py (10) covers the analyzer + a regression
  guard that the batch words ARE filtered and the collisions are NOT. REMAINING (queued,
  bigger): wire keyword_equivalents.yml into LIVE analytics (the "Trans-language
  equivalence" entry — DONE, wired 2026-06-16); fix sentence-initial-capital false entities
  (DONE — see ENTITY-DETECTION ruling below); singular/plural family merge (DONE 2026-06-16
  — see below); the Item AC pre-tagged per-language baseline + keyword-management Settings
  subtab (DESIGN DOC `docs/design/KEYWORD_BASELINE_AND_MANAGEMENT.md`; maintainer ANSWERED
  the 6 questions 2026-06-17 — Q1 curated-small+analyzer-grown, Q2 BOTH axes [type+topic],
  Q3 stoplists→data files, Q4 explore+hide/tag together, Q5 forward-only, Q6 deferred).
  **ITEM AC S1 — TAG SCHEMA + BASELINE LOADER SHIPPED 2026-06-17 (draft PR onto 0.09):**
  the positive-baseline MECHANISM. `KeywordTag` model (keyword_id FK · axis type|topic ·
  tag · source baseline|user · uq(keyword_id,axis,tag,source); migration e3f4a5b6c7d8 off
  the real head d2e3f4a5b6c7 — verified single-head); `src/analytics/baseline.py` = a
  network-free dated loader (`BASELINE_AS_OF` + freshness test) over bundled
  `configs/keyword_baseline/<lang>.yml` (en+fr seeds, both axes; casefold match; missing
  file/`OO_KEYWORD_TAGS=0` = no-op, never invents); applied FORWARD-ONLY at keyword creation
  in `store._get_or_create_keyword` (each tag a labelled assertion carrying `source`), +
  read helper `store.tags_for_keyword` (grouped by axis, no score). tests/test_keyword_tags.py
  (loader both-axes/casefold/disabled/freshness, forward-only+idempotent application,
  non-baseline→no tags).
  **ITEM AC S3a — KEYWORD-TAG API SHIPPED 2026-06-17 (draft PR onto 0.09):** the backend the
  Settings subtab needs (built before the UI; concrete + testable). Five endpoints on the
  insights router: `GET /api/insights/keyword-tags?normalized=` (one keyword's tags grouped by
  axis + per-tag `sources` provenance baseline|user), `POST /keyword-tags` (add a USER tag —
  validated axis∈{type,topic}, lowercased/bounded, idempotent, 404 on unknown keyword),
  `POST /keyword-tags/remove` (delete a tag — any source, local curation; reversible; a removed
  baseline tag is NOT re-applied since tagging is forward-only), `GET /keyword-tags/facets`
  (distinct tags per axis with DISTINCT-keyword counts — the explore filter; empty axes still
  listed), `GET /keyword-tags/keywords?axis=&tag=` (keywords carrying a tag with mention/article
  counts + source, ordered by article spread). Counts only, NO score; tags are labelled
  assertions, never rewritten. tests/test_keyword_tags_api.py (4, called directly over an
  in-memory corpus — no TestClient/crypto import).
  **ITEM AC S2 — BASELINE EXTENDED TO 7 LANGUAGES 2026-06-17 (draft PR onto 0.09):** added
  curated `configs/keyword_baseline/{de,es,it,pt,nl}.yml` (en+fr already shipped in S1) — the
  same clearly-typed core keywords (election/inflation/pandemic/drought/satellite…) in each
  language, both axes where sensible, SINGLE-token only (a multi-word key with an internal
  stopword never becomes a keyword, so it could never match). The type/topic tags are
  language-independent; the words are confident common forms (AI-translatable, flagged for
  native review). `tests/test_baseline_data.py` (3) GUARDS every baseline file in CI: parses,
  axes ∈ {type,topic}, non-empty tags, the loader round-trips each language, and the 7 core
  UI languages are present.
  **ITEM AC — ANALYZER 'TAG GAPS' MODE SHIPPED 2026-06-17 (draft PR onto 0.09):** operationalises
  the 'analyzer-grown baseline' (Q1). `scripts/analyze_keyword_log.py LOG.json --tag-gaps` lists,
  per language, the top-frequency TERM keywords that have NO entry in
  configs/keyword_baseline/<lang>.yml yet — the worklist of what to tag next. It cross-references
  the baseline files via a stdlib line parser (`load_baseline_keys`, no yaml dep — the analyzer
  stays runnable without the app), excludes entities, and gates on `--gap-min-articles` (default
  3). The analyzer PROPOSES candidates only; a human picks the type/topic (no semantic source, no
  invention). Verified live on the 2026-06-14 log (en baseline=22 → surfaces team/public/national…
  as next candidates; also exposes residual stopword junk as a bonus). tests/test_keyword_log_analyzer.py
  (+2: stdlib key parse incl. quoted key/comment; untagged-terms-only gate).
  **ITEM AC — RETROACTIVE TAG BACKFILL SHIPPED 2026-06-17 (draft PR onto 0.09):** tagging at
  ingest is FORWARD-ONLY (Q5), so a pre-existing corpus has no baseline tags until a backfill
  runs. `store.backfill_baseline_tags(session, limit=)` does the one-pass retroactive tag —
  reads the same bundled baseline, skips keywords it already tagged (idempotent), and the
  existing-rows query runs ONLY for keywords that actually match the baseline (cheap). Exposed as
  `POST /api/insights/keyword-tags/backfill?limit=` (limit 0 = all). Counts only {scanned,
  tagged_keywords, tags_added}, never invents a tag. tests/test_keyword_tags.py +1 (tags election
  not widget; idempotent second pass = 0 added). This makes the tag feature non-empty on existing
  corpora (so S3b won't show a blank subtab).
  **ITEM AC S3b — KEYWORD EXPLORER SUBTAB SHIPPED 2026-06-17 (conservative + browser-unverified per
  fork-3):** the deferred Item AC frontend. A Settings → Keywords subtab (`data-tab="keywords"` /
  `#set-keywords`, wired via showSetCat) explores keywords by their type/topic TAGS (the S3a API):
  `loadKeywordExplorer` reads /keyword-tags/facets → clickable tag chips per axis → kxShowTag reads
  /keyword-tags/keywords → a keyword list (term · lang · a/m · source) with a HIDE button (reuses
  POST /api/insights/exclude, reversible); "Apply baseline tags" runs the backfill (POST
  /keyword-tags/backfill). Panel content is un-keyed English MATCHING the adjacent super-group +
  diagnostics keyword-curation UIs (so i18n stays 100% with ZERO new keys; the nav label reuses the
  already-keyed "Keywords"). node --check clean; test_ui_invariants test_keyword_explorer_subtab
  pins the subtab + the facets/backfill/exclude wiring. REMAINING: the per-keyword TAG add/remove UI
  (the S3a write endpoints exist; this slice does explore + hide + backfill); S1b stoplists→data
  files (Q3); S4 in-app analyzer-proposal review; browser click-through (fork-3).
  **SINGULAR/PLURAL FAMILY MERGE — SHIPPED 2026-06-16 (maintainer "start with the plural-merge
  risk analysis"; conservative + guarded; draft PR onto 0.09):** RISK ANALYSIS first corrected
  the size — only **932** real pairs (the earlier ~2753 was an exploratory bug that stripped N
  chars WITHOUT verifying the word ends in s/es), and the scariest over-merges DON'T ARISE
  (new/news, use/uses: the singular is a stopword so never a keyword) and the name-plural risk
  largely dissolved with the entity change (most "entities" are terms now). `build_families`
  gains pass 1.5: a single-token regular plural (-s/-es/-ies, `_plural_bases`) joins its
  singular family ONLY when BOTH are plain TERMS of the same kind (never entity NAMES), the
  base EXISTS as a same-kind term (so a non-plural word ending in -s won't merge unless its
  stem is real), and the base isn't a known meaning-changer (`_PLURAL_DENYLIST` =
  mean/right/force/good/arm/… — evidence-based + log-tunable like the stoplists). Reversible
  via a split override (any override excludes a form from the auto pass); `OO_FAMILY_PLURALS=0`
  disables. tests/test_families.py (+3: collapse state/states+country/countries, never
  entities/denylisted, override+env kill-switch). Mentions summed, articles = max member
  (the existing honest family convention).
  **ENTITY DETECTION — TITLE-CASE DROPPED, ACRONYMS KEPT (maintainer RULED 2026-06-16
  "proceed with your recommendation" after a data review; SHIPPED draft PR onto 0.09):**
  the baseline `kind=entity` flag was PURE capitalization — and the keyword-diagnostics
  log proved it broken for the multilingual corpus: only `entity`/`term` ever assigned
  (NO person/org/location semantics), ~60–75% of per-language "entities" were common
  words (German capitalises EVERY noun — 711 German "entities" were nouns like
  Behauptung/Medien/Menschen; Romance sentence-initial/day/month caps leak; Arabic/CJK
  have no case). KEY de-risking facts from the log: (a) the When×Where×Who flagship is
  INDEPENDENT (it reads ArticleEntity/ArticleMentionedPlace from the timemap extractors,
  NOT Keyword.is_entity), so this change does NOT touch Who/Where; (b) the WHO-vs-who
  acronym-homograph cost of casefolding is TINY (only US→us, S.I→si collide; "who" isn't
  even a stoplisted word). RULING IMPLEMENTED in `BaselineExtractor._entities`: Title-Case
  is no longer an entity signal; entities are now ONLY stand-alone ALL-CAPS **acronyms**
  (context-aware — an all-caps token ADJACENT to another all-caps word is a headline/shout
  run, skipped; a small `_ACRONYM_STOP` excludes ok/vs/ceo/…; digit/hyphen acronyms G7/
  COVID-19 allowed), with the normalized form kept **UPPERCASE** so an acronym stays
  distinct from a lowercase homograph (`WHO`≠`who`, `US`≠`us`) and survives the stopword
  filter — the principled answer to the WHO/Who question. Real person/org/place kinds come
  from the gazetteer / spaCy (language-aware), promoted in `extract()` (a term whose
  normalized form is in the gazetteer gets its kind). Multi-word Title-Case names survive
  as topical TERM n-grams (never lost). Dead Title-Case machinery removed
  (`_at_sentence_start`/`_SENT_END`/`_CONNECTORS`). tests/test_analytics_extract.py updated
  (multiword Title-Case→term; +WHO≠who, +US-survives, +German-nouns-are-terms,
  +headline-not-acronym). DELIBERATE acceptance (testing phase): residual emphasis-acronym
  noise is iterated away via the diagnostics logs (the maintainer's loop).
  **STALE-TEST FOLLOW-UP FIXED 2026-06-17 (the base went red — #283 updated
  test_analytics_extract.py but MISSED two ingest tests that still asserted the old
  Title-Case behaviour; maintainer steer "look at recent PRs, hint: Keywords" = align
  them with the new model, not revert it):** (1)
  test_analytics_store.py::test_index_article_writes_mentions_with_facets used
  "Emmanuel Macron" (Title-Case) as the entity → now uses the ALL-CAPS acronym "WHO"
  (entity normalized UPPERCASE, WHO≠who); the facets assertions are unchanged. (2)
  test_keyword_policy.py::test_index_article_suppresses_own_source_name_only used
  "The Moscow Times" — but "times"/"the" are stopwords so since #283 dropped the
  multiword-Title-Case ENTITY path that full name no longer survives as one keyword
  (only the bare, deliberately-unsuppressed word "moscow"); renamed the outlet to
  "The Moscow Herald" (content-word tokens) so the self-name suppression is still
  genuinely demonstrated on the multiword term "moscow herald" the extractor now
  produces, with "moscow" asserted to STAY content in both articles (the
  single-shared-word guarantee). Tests-only; verified empirically against the live
  extractor before editing. NOTE for the record: #283 DID narrow self-name
  suppression for outlet names whose tokens are stopwords (e.g. literally "The Moscow
  Times") — accepted as a consequence of the anglocentric-Title-Case removal, not
  re-litigated here.
  **ANALYTICS-TOOLS — LOG DIFF MODE SHIPPED 2026-06-16 (green-lit "implement better analytics
  tools autonomously"; stacked draft PR onto 0.09):** `scripts/analyze_keyword_log.py --baseline
  OLD.json NEW.json` is the "did my optimization work?" tool — it DIFFS two keyword-diagnostics
  logs and reports the delta: kind SHIFTS (entity->term proves the Title-Case drop landed —
  measured 9163→4466 entities / 4697 reclassified on the 2026-06-14 log), keywords GONE
  (filtered by a stopword batch) vs APPEARED, per-language + corpus deltas, mention growth,
  language_mismatch before/after. Case-sensitive keyed so a preserved acronym `WHO` stays
  distinct from the word `who`. `mistagged_entities` is now ACRONYM-AWARE (flags single-word
  NON-acronym entities — the case-noise the entity change removed — so it self-checks old vs new
  logs). Reports deltas only, never infers. tests/test_keyword_log_analyzer.py (+4: kind-shift,
  gone/appeared, acronym-distinct, acronym-aware mistag). Closes the maintainer's loop: send a
  log next session, see the measured impact.
  **KEYWORD PRE-SELECTION SELF-TEST + IN-APP TOOL SHIPPED 2026-06-17 (maintainer-asked "an
  elegant test to challenge the preselection … verify it differentiates Who from WHO … and
  other language tweaks … an in-app tool to automate the test and log results to send to
  you"):** `src/analytics/selftest.py` = a DECLARATIVE golden-case harness (`Challenge`
  dataclass — each line states in DATA exactly what it guards) run over the REAL pipeline
  (BaselineExtractor / build_families / equivalence / baseline; no DB, no network, no score).
  22 cases across 11 LANGUAGES (maintainer-flagged 2026-06-17: the stopword filters cover every
  source language with a stoplist — a UNION applied to all extraction — so the harness must too,
  not just English). English: who_vs_WHO (the org acronym stays distinct from the pronoun),
  US-survives-stopword, sentence-initial-not-entity, digit-acronym-kept (G7/COVID-19),
  headline-caps-not-acronyms, English-stopword-filtered (that), weekday-filtered. Multilingual
  stopword/weekday filtering verified-present in global_stopwords(): de (können/sondern), fr
  (mardi/samedi/chez), es (sábado/miércoles/pero…), it (sabato/perché), pt (sábado/porque/embora),
  nl (maandag/zaterdag/omdat), ru CYRILLIC (чтобы/которые), ar RTL (خلال/قبل/بعد), hu
  (szerint/pedig/hétfő), id (dalam/oleh/sabtu/minggu); + German-nouns-are-terms + a Romance
  sentence-initial-not-entity (es mercados). HONEST LIMITATION SURFACED: stoplists are by BASE
  form, so an INFLECTED weekday ("среду"/"szombaton") still leaks in inflecting languages — the
  ru/hu cases assert only the function words actually present (non-vacuous), and the gap is noted.
  zh/ja excluded (no segmentation). Structural: plural-family-merge, equivalence-ring
  (election/élection/wahl), baseline-tag-applied. `run_keyword_selftest()` returns an exportable
  log (schema `oo-selftest-1`, summary + per-case pass/fail+detail). THE IN-APP TOOL:
  `GET /api/diagnostics/keyword-selftest` (+`?download=1` → dated attachment) added to the
  Diagnostics-log panel (a 'Download keyword self-test (.json)' button + hint, matching the
  existing un-keyed diagnostics buttons). All 12 PASS on the current pipeline (so a regression
  reddens BOTH the in-app log the maintainer exports AND the unit test in CI).
  tests/test_keyword_selftest.py (all-pass + who_vs_WHO + the runner detects a deliberate fail —
  so a green run is never vacuous). Closes the loop the maintainer asked for: run it in-app,
  send the log, I see exactly which keyword behaviour regressed.
  **KEYWORD-ENGINE PRE-TRANSLATION/SYNONYM/SUPER-RING PROGRAM (maintainer ruled 2026-06-17 "proceed
  with 1,2,3,4 in complete autonomy"; agreed to my plan incl. Wikidata-labels as the translation
  source):** the 4-level hierarchy = keyword → family (morphology) → RING (cross-language concept +
  synonyms) → SUPER-RING (theme of rings = a super-group whose members are rings). PLAN: (1) an
  in-app efficacy+performance report [SHIPPED below]; (2) super-group members can be RINGS (the
  super-ring model); (3) an OFFLINE Wikidata-labels ring generator + a dated few-hundred-ring
  snapshot + freshness test (scales pre-translation reliably, sourced by QID, no LLM); (4) wire
  ring/super-ring editing into the Item AC keyword subtab. Scopes to the 12 UI languages.
  **STEP 1 — KEYWORD-ENGINE REPORT SHIPPED 2026-06-17 (draft PR onto 0.09):** `src/analytics/
  engine_report.py:keyword_engine_report(session)` = a bounded, read-only diagnostic — composition,
  ENTITY PRECISION (% of entities that are valid acronyms post the Title-case drop), cross-language
  TRANSLATION COVERAGE (% of top-N keywords in a ring — the number that tracks the ring work, near
  0 today), TAG COVERAGE, per-language FUNCTIONAL STATUS (functional / no_stoplist / unsegmented —
  flags zh/ja honestly), the self-test summary, and indicative PERFORMANCE (extraction ms/article +
  grouped-query latency). NO composite score; each block states its method. `GET /api/diagnostics/
  keyword-engine` (+`?download=1`) + a Diagnostics-panel button. The hand-back loop: run it, send
  the JSON, diff two over time to prove an optimization landed. tests/test_keyword_engine_report.py
  (metrics shape, honest entity-precision + language-status, no score).
  **STEP 2 — SUPER-RINGS SHIPPED 2026-06-17 (draft PR onto 0.09, stacked on Step 1):** a super-group
  MEMBER can now be a cross-language RING (concept), not just a family — "rings of rings". Schema:
  `KeywordSuperGroupMember.ring_id` (nullable; migration f4a5b6c7d8e9 off head e3f4a5b6c7d8 —
  single-head verified). A ring member stores the ring id in BOTH `ring_id` (marker+link) and
  `normalized_term` (so the unique key + remove-by-key path are unchanged). `_supergroup_totals`
  rewritten to take member rows: a ring member AGGREGATES mentions/articles over ALL the ring's
  cross-language terms (election+élection+wahl = 15 in the test), so a super-group with a ring spans
  languages; `list_supergroups` surfaces `ring_id` + the `ring_members` (lg:term) per ring member;
  `add_supergroup_members` accepts `rings:[ids]` (validated via `ring_meta`, 400 on unknown). Plain
  family members unchanged. Backend only (the UI for adding rings lands in Step 4, the keyword
  subtab). tests/test_super_rings.py (cross-language aggregation, unknown-ring 400, family still
  works).
  **STEP 3 — WIKIDATA RING GENERATOR + CURATED EXPANSION SHIPPED 2026-06-17 (draft PR onto 0.09,
  stacked on Step 2):** the scaling path for pre-translation, no LLM, sourced. `scripts/
  generate_wikidata_rings.py` = the GENERATOR (stdlib-only, runs on a NETWORKED machine — Wikidata
  is 403-blocked in this sandbox, the established maintainer-machine pattern): per seed it finds the
  Wikidata QID (`wbsearchentities`) then pulls multilingual LABELS + ALIASES (`wbgetentities`, CC0)
  for the 12 UI languages → one ring (translations + synonyms), keyed by QID for audit. Pure parse
  fns (`parse_search`/`parse_entity`/`build_ring`) offline-tested with API fixtures; only fetch_json
  touches the net (injectable getter); `--seeds FILE` or `--from-log LOG.json --top N`. Output →
  `configs/keyword_rings_generated.yml`, which `equivalence.load_rings` now reads ALONGSIDE the
  curated file (refactored: `_parse_rings`/`_read_yaml`; generated read first, CURATED WINS on an id
  collision). IMMEDIATE value (since I can't run the generator here): a hand-curated high-confidence
  EXPANSION of keyword_equivalents.yml — 10→22 rings (government/president/inflation/economy/climate/
  health/energy/vaccine/pandemic/sanctions/market/refugee across en/fr/de/es/it/pt/nl[/ru]) so the
  engine report's translation_coverage ticks up NOW. tests/test_wikidata_ring_gen.py (parse fixtures,
  generate+emit roundtrip, curated-expansion loads, generated-merge with curated-wins). REMAINING:
  the maintainer runs the generator on a networked box → hundreds of rings (review before trusting;
  the signature gate still protects).
  **STEP 4 — RING/SUPER-RING EDITING IN THE UI SHIPPED 2026-06-17 (draft PR onto 0.09, stacked on
  Step 3; conservative + browser-unverified per fork-3 — COMPLETES the 4-step program):** the Item
  AC keyword subtab (S3b) was never built, so rather than a whole new subtab I EXTENDED the existing
  Insights → Groups (super-groups) UI — smaller + reuses its conventions (the super-group UI is
  un-keyed English + inline handlers; the ring additions MATCH that style, so i18n stays 100% and
  risk is low). Backend: `GET /api/insights/rings` lists the rings (id · members · languages · size,
  sorted by language breadth; from the config, no DB) so the UI can offer a ring picker
  (tests/test_ring_ui.py). Frontend (src/static/app.js + index.html): `loadSuperGroups` now also
  fetches /rings → a `#sg-ring-options` datalist; `sgCard` renders a ring member distinctly (⊕ id ·
  "ring·N terms" · the cross-language members in the hover) and offers an "add a ring" input + button
  beside the family one; new `sgAddRing` POSTs `{rings:[id]}` to the Step-2 super-ring endpoint;
  remove reuses the existing path (a ring member's normalized_term == its ring id). node --check
  clean; i18n 100%; test_ui_invariants `test_super_ring_ui` pins the datalist + the /rings fetch +
  the handler. REMAINING (deferred, honest): the FULL Item AC keyword EXPLORER subtab (hide/tag
  individual keywords, the S3b that was deferred) is still unbuilt — this step delivered the
  ring/super-ring editing the program needed, not the whole explorer; browser click-through still
  owed (fork-3). The pre-translation/synonym/super-ring program (Steps 1-4) is COMPLETE.
- **WIKIPEDIA AS A LIVING SOURCE (maintainer concept 2026-06-12, recorded in
  FUTURE_DEVELOPMENTS with the design map + questions):** wiki articles enter
  the SAME aggregation as sourced articles (metadata, when×where×who,
  keywords) BUT are AMENDABLE like the law — every change traceable,
  version-anchored analytics, perfect audit control.
  **RULED 2026-06-12 (the mandate made concrete — "this needs your full
  attention"):** (1) wiki articles appear in GENERAL search like any article;
  (2) same keyword aggregator + When×Where×Who anchoring; (3) the article
  shown is ALWAYS the LATEST version (default), change history available
  beneath; (4) an audit/track-change ENGINE receives edits and materializes
  the latest version on demand; (5) a DEDICATED tracked-changes TAB in the
  wiki-article UI — scrolling/discovering/exploiting/analyzing edits through
  time; intuitive, genuinely smart, interactive, beautiful, all core ethics
  (informed consent, math/science proof). This ANSWERS filed questions 2
  (same pools: YES) and 4 (the watched-pages tracker IS the change feed).
  **BRIDGE SLICE SHIPPED same day (PR: t-wiki-corpus):** watched pages now
  enter THE corpus — src/wiki/corpus.py syncs the NEWEST text (latest_text,
  refreshed by the tracker on every change + revid anchored; falls back to
  baseline) as ONE Article per page (canonical wiki URL; per-edition source
  "Wikipedia (xx)" domain xx.wikipedia.org — filterable forever; bounded
  wikitext→plain strip, stated), through THE index_article hook (keywords +
  WWW follow the latest version automatically; idempotent on content hash);
  tracker wired (sync after new revisions, failures never block tracking);
  POST /api/wiki/corpus/sync backfills existing watchlists, LOCAL-only;
  migration b6c7d8e9f0a1. **HONEST GAP NOW BLOCKING the full engine: stored
  revision diffs are TRUNCATED 2000-char summaries (diff_summary), NOT
  reconstructable patches — past versions cannot be materialized locally.
  Storage question (#3) ANSWERED (maintainer-agreed 2026-06-12): PER-
  REVISION FULL TEXT — SHIPPED same day (WikiRevision.full_text, batched
  fetch_revision_texts ≤50 revids/call, failure stores revisions without
  text rather than dropping them; latest_text fed from the batch). PLUS the
  maintainer's disclosure mandate ("make everything so that the user is
  fully informed of our choices"): the Wikipedia tab states the three
  choices visibly (newest-version default + revid recorded; full text per
  revision stored locally with the storage cost said; stripped-wikitext
  honesty) with the why in the hover long-form, ×12 locales; USER_MANUAL
  §3.7 documents them.** REMAINING: the dedicated
  tracked-changes TAB (the full-attention GUI — own slice, browser-verified);
  per-mention revid anchoring; dumps→corpus ingestion path.
  Earlier honest gap stands: downloaded dumps are FILES only (T14 reads one
  page; never yet parsed into the corpus).
  **SUPERSEDING RULING (maintainer 2026-06-12, RECORD-ONLY — "don't
  implement this right now"): once a user downloads a LANGUAGE DATASET
  (dump), the ENTIRE Wikipedia corpus of that edition is tracked
  AUTOMATICALLY — per-article tracking is to be RETIRED ("it will not be
  used"); tracking becomes by-design-and-by-default after a Wikipedia
  resource download.** Design + filed questions/comments live in
  FUTURE_DEVELOPMENTS (scale honesty: enwiki ≈ 100k edits/day vs the 2-core
  reference VM; the dump-as-baseline + recentchanges-as-delta architecture;
  tiered depth proposal; what consent/visibility the auto-tracking needs).
  Ask/comment WHEN THE TIME COMES, per the maintainer — not now.
  **WIKIPEDIA AS A SETTINGS-MANAGED, AUTO-WATCHED SOURCE (ruled 2026-06-13,
  field session):** (1) Wikipedia is watched ENTIRELY and BY DEFAULT in ALL
  12 UI-language editions — auto-watch is the default, not a per-page opt-in;
  (2) the WIKIPEDIA TAB MOVES INTO SETTINGS (content-first; the watched
  corpus surfaces in general search/analysis like any article — invariant #8);
  (3) WHICH dumps to download is DECIDED AT FIRST RUN (the guided wizard #24 —
  language-dataset choice folds in there, honest size guidance per edition);
  (4) a Wikipedia DUMP DOWNLOAD MUST NOT DELAY scraping or other downloads —
  it is its own task-manager job (files, no DB-writer contention; parallel by
  the T9 ruling); (5) FULL download CONTROLS live in the task manager: rate,
  percentage, speed, BANDWIDTH CAP, ETA at current average speed, pause,
  resume, prioritize, de-prioritize. Builds on the SUPERSEDING auto-track
  ruling above (dump-as-baseline + recentchanges-delta) and the
  SCRAPING_AUTOMATION_PLAN download subsystem. Scale honesty still applies
  (enwiki ≈ 100k edits/day vs the 2-core VM) — tiered depth + visible consent.
  **INLINE AUTO SIZE ESTIMATES (ruled 2026-06-16; BUNDLED-TABLE HALF SHIPPED
  2026-06-16): show EACH dump-eligible edition's estimated size INLINE &
  AUTOMATICALLY in the picker.** SHIPPED: `src/wiki/dump_sizes.py` =
  `DUMP_SIZES_AS_OF` ("2026-06") + per-edition approximate compressed
  pages-articles-multistream sizes for every APP_LANGUAGE_CODES edition +
  `estimate_bytes()`; `/api/wiki/languages?scope=dumps` enriches each edition with
  `size_estimate_bytes` + a top-level `size_estimate_as_of` (zero extra network);
  the dump `<option>` labels render `· ~X GB` inline and a dated caveat note
  ("Inline sizes are estimates — exact size read on download · reviewed {date}")
  sits beside the picker, +2 strings ×12. Freshness test
  `tests/test_dump_sizes.py` (12-mo window, every dump-eligible edition covered,
  en largest, endpoint contract) mirrors the CATALOG_AS_OF pattern; zero-network
  boot + airplane intact (no per-edition probe). REMAINING: DROP the per-edition
  "Estimate size" probe button (#dump-lang → probeDump → GET /api/wiki/dumps/probe,
  a LIVE per-edition HEAD) and REPLACE it with ONE consented "refresh exact sizes"
  that fetches live sizes in a SINGLE call (the dump date's dumpstatus.json lists
  every edition at once, not N HEADs) through the guarded factory + the ONE consent
  (#14). The probe button stays meanwhile (additive; nothing lost — the Desk lesson).
- **WIKIPEDIA (field report #4; T14 SLICE 1 SHIPPED 2026-06-12):** the RULED
  dump-list limit SHIPPED (/api/wiki/languages?scope=dumps serves only
  APP_LANGUAGE_CODES = 12 UI locales + 5 stoplist-evidenced corpus languages;
  Esperanto stays in the WATCHED-pages picker — invariant #1 untouched —
  and out of the dump list; tested). The READER gap's first slice SHIPPED:
  new downloads default to pages-articles-MULTISTREAM with the companion
  index auto-queued (same reorderable queue); src/wiki/dumpread.py reads ONE
  page locally (index scan → seek → one-block decompress; exact match wins,
  case-insensitive match is LABELLED; legacy single-stream files reported
  honestly as non-seekable with the re-download hint); Settings gains the
  "Read a page from a downloaded dump" box (raw-wikitext snapshot note,
  scan stats, +17 strings ×12); EMPIRICAL: multistream page blocks are bare
  <page> elements — wrap before parsing; the index is offset:pageid:title
  with title possibly containing colons (split(":", 2)). REMAINING:
  full-text SEARCH over dumps + wikitext rendering + the corpus ingestion
  path (the living-source design); standing idea: bundle the
  top-1000-pages LIST + one-click opt-in watch — never auto-fetch at boot.
- **Collector: cumulative runs + progress (2026-06-10):** one Collect pass
  cumulatively does RSS + crawl + markets + wiki watched pages; a progress
  bar visible throughout the UI (top-bar activity chip hosts it).
- **SENTIMENT AT INGEST (maintainer-flagged 2026-06-17 "isn't this done at the scraping level? I
  see no sentiment analysis" — INVESTIGATED + FIXED, draft PR onto 0.09):** the finding was that
  `Article.sentiment_score`/`sentiment_label` columns EXISTED but were NEVER written (dead columns) —
  sentiment was computed ONLY on-demand (VADER) in one Sentiment subtab via /api/framing, so most of
  the app showed nothing, and VADER's English-only lexicon made a multilingual corpus look empty.
  FIX: `src/analytics/sentiment.py:score_article(text, language)` runs through the ONE per-article
  `index_article` hook (so ingest [pipeline.py:202], re-index AND backfill all populate it now),
  storing the result on the article. LANGUAGE-AWARE + HONEST: VADER (rule-based, no LLM, no network)
  scores ONLY `language=="en"`; every other/unknown language + empty text returns (None,None) — NEVER
  a fabricated neutral (the same honest gap as the keyword zh/ja limit). GRACEFUL: VADER is the
  optional [analysis] extra, so `_analyzer()` returns None when it's absent → score_article returns
  (None,None) → a CORE install never crashes at ingest (the language/empty gates also return before
  VADER is touched). tests/test_sentiment_at_ingest.py (non-English→None runs everywhere incl. no-lib;
  the en-scoring + index_article-populates tests skip without the extra, run in CI). REMAINING: SURFACE
  the stored sentiment in the reader/cards/lists (the columns are now populated on re-index; the UI
  still reads on-demand framing in the Sentiment subtab); a multilingual path (per-language lexicons /
  a local model) beyond the English VADER baseline.
- **When×Where×Who at ingest (CONFIRMED GO; PERSISTENCE SHIPPED T12
  2026-06-12):** dates/places/entities now persist AT INGEST through the one
  index_article hook (live ingest + re-index + backfill all inherit it) —
  article_mentioned_places + article_entities tables (migration
  a5b6c7d8e9f0), snippet provenance + rule notes on every row, idempotent
  per article, failures never block keyword indexing (tested). Deduced
  stays labelled deduced. CORPUS-WIDE WHO + WHERE SHIPPED (2026-06-14):
  queries.who_aggregate + GET /api/insights/who roll article_entities, and
  queries.where_aggregate + GET /api/insights/where roll
  article_mentioned_places, up to the whole corpus — distinct-article spread +
  summed mentions, ordered by spread; filters (class for who; kind city|country
  for where) + days + country, min_articles HAVING, coverage_articles
  denominator; WHERE adds gazetteer lat/lon (null when unknown + placed count);
  NO score, method+caveat "Deduced from text, never confirmed."
  (tests/test_who_aggregate.py, tests/test_where_aggregate.py). READER NOW READS
  STORED ROWS (SHIPPED 2026-06-15, PR #202): view_article serves the persisted
  article_mentioned_dates/_places/_entities (datestore.for_article +
  whostore.*_for_article) instead of recomputing — places/entities already did on
  0.09; the dates path was the last recompute, now reads stored tags (user-rejected
  excluded from the compact summary), live extractor kept only as the no-rows
  fallback; response contract + two-class labeling + "never confirmed" caveat
  unchanged; test proves the extractor is NOT called when rows exist. TEMPORAL-MAP
  MENTION LAYER also SHIPPED (PR #200) — plots stored PLACES (article-mentions) on
  the map; the EVENT-places feed remains. REMAINING: wiki articles join when the
  living-source design lands. NEXT for the extractors themselves: feed the temporal
  map's mention layer with event-places too; extend the country table; aggregate
  entities corpus-wide. **AGENDA ARTICLE-EXTRACTED DATES — BACKEND SHIPPED 2026-06-16:**
  `datestore.upcoming_deduced` + `GET /api/events/deduced` surface FUTURE dates MENTIONED
  in articles as agenda candidates — grouped by date with distinct-article + distinct-source
  counts, a ≥min_articles surfacing gate, the article-id set for corpus open-through; "deduced
  from text, never confirmed" caveat, counts only/no score (tests/test_deduced_dates.py).
  FRONTEND SHIPPED 2026-06-16 (conservative, browser-unverified): `mapDeducedToAgenda`
  maps `/api/events/deduced` into the `AG.events` pipeline like imported events (so EVERY
  agenda view places them via `next_occurrence` for free), as a distinct filterable
  "deduced" category; each row shows a VISIBLE "deduced · never confirmed" pill + the
  "Deduced from N articles (S sources), never confirmed." note, and the title opens the
  EXACT article set via `openAnalysisForIds` (agRow branch). +4 i18n ×12; test #13b.
  REMAINING: deduced events as FIRST-CLASS agenda events with ⊞ keyword links (parity with
  the moon/season glyph treatment); recurrence/world-calendars/astronomy slices.
  **DATE-EXTRACTOR ANCHOR/LANGUAGE WIRING FIXED 2026-06-16 (maintainer-flagged: date
  extraction should be automatic at ingest):** date extraction WAS already automatic at
  ingest (index_article → datestore.store_for_article → dateextract), but the store called
  `extract_dates(content, today=today)` WITHOUT `anchor`/`language` — so at ingest the
  extractor silently ran explicit-dates-only, skipping the commonest news forms it fully
  supports: no-year day+month ("11 September"), relative words ("yesterday"/"hier"), bare
  weekdays ("on Tuesday"/"mardi"), and language-ambiguous numeric dates (11/06 = DMY in fr,
  MDY in en, else skipped never guessed). The capability was built ("Optimized 2026-06-11
  maintainer: far too few dates") and the reader-fallback (main.py) + temporal-map collect
  ALREADY passed anchor+language — only the SOURCE-OF-TRUTH store didn't. FIX:
  `store_for_article` now derives `anchor = article.published_at or created_at` (the
  established observed-date convention) + passes `article.language`, so EVERY path through
  the chokepoint (ingest, reader stored-rows, index_recent, agenda deduced) gets the full
  set. Additive + idempotent (all stay human-confirmable `candidate`s with snippet
  provenance); a re-index/backfill enriches existing articles (no migration). Three now-false
  "no relative phrases / explicit dates only" caveats corrected for honesty (article_dates
  _CAVEAT, the reader date section in main.py, the recipes.py lead-days method). Regression
  guard: tests/test_article_dates.py::test_store_uses_article_anchor_and_language. END-TO-END
  verified: ingesting "La réunion était hier. … le 15 septembre. … le 11/06/2026." (fr,
  pub 2024-06-10) now stores 2024-06-09 + 2024-09-15 + 2026-06-11 (zero before).
- **Convergence + watch rules (the 0.0.9 flagship, parked from PR #51) —
  SLICE 1 SHIPPED (PR #212, 2026-06-15; unblocked now that When×Where×Who
  persists):** READ-ONLY space-time co-occurrence in src/analytics/convergence.py
  (find_convergences) + the space_time_convergence briefing producer (investigate
  bucket, registered last/fail-safe). Groups articles converging on the same PLACE
  within a TIME WINDOW (default 7d) on the MENTIONED event date (not pub date).
  Honesty baked in: independence measured by DISTINCT SOURCES (not article count),
  surfacing gate ≥3 articles AND ≥2 sources (a chatty single source can't
  manufacture one), shared-outbound-link flagging (_shared_origin, anti-false-
  triangulation), metric=distinct_sources (NO score), verbatim "never causation …
  a prompt to read, not proof anything happened" caveat on every cluster. No
  endpoint/frontend/migration (read-only over T12 tables). tests/test_convergence.py.
  **ENDPOINT SHIPPED (2026-06-15 solo session): GET /api/insights/convergences** exposes
  find_convergences read-only (honest gates + per-cluster method+caveat + totals, NO
  score; test_convergences_endpoint proves the independence gate flows through the API).
  **FRONTEND VIEW SHIPPED 2026-06-16 (conservative, browser-unverified):** a read-only
  Insights → Convergence subtab (`data-tab="convergence"` / `#ins-convergence`,
  `loadConvergences` lazy-loaded from `showInsightCat`) renders each cluster (place +
  country, window, n_articles / distinct_sources, source names), the title opening the
  EXACT converging article set via `openAnalysisForIds`; the API method + caveat
  (non-causation) are VISIBLE by default, the shared-origin-links flag shows a visible
  `var(--caveat)` warning, honest empty state names the gate, NO score; +5 i18n ×12;
  test #21c. **WATCH ENGINE SHIPPED 2026-06-17 (ruling #3 — ON BY DEFAULT, the maintainer
  overrode the earlier off-by-default lean):** the user-defined "if-this-then-WATCH" engine.
  Models Watch + WatchMatch + migration b8c9d0e1f2a3; `src/analytics/watches.py` (CRUD +
  `evaluate_watches` — fires a "watch" Lead card when the corpus gains enough NEW articles
  matching a saved FTS condition over the USER's threshold+window; `last_seen_ids` prevents
  re-alarming on the same articles; matcher reuses FTS `search_ids`; bad query never breaks
  the pass); `watch_matches` producer (bucket="watch", no score, passes the Card schema)
  wired into `refresh_briefing` so it runs after every scrape pass (ON by default); API
  `src/api/watches.py` (CRUD + history + evaluate, LOCAL no consent gate); a Watches Insights
  subtab (create/enable-disable/edit/delete + history → openAnalysisForIds, browser-unverified
  + flagged, English-only zero-new-keys). LOCAL-ONLY, NO notifications/network/telemetry, NO
  escalation tiers beyond the Lead card (the ruling). tests/test_watch_engine.py (7) +
  tests/test_watches_api.py + test #21d. REMAINING: i18n-key the Watches panel strings (the
  long-tail pass); richer condition types (place/convergence-based) beyond the FTS query.
- **Temporal map remainder:** logarithmic time scale (agreed: linear/log
  toggle, labelled ticks, no hidden warp); feed mention-layer with extracted
  event-places.
- **MAP REWORK — UNIVERSAL ooMap + CHOROPLETH (maintainer ruling 2026-06-18; the current
  map is "unusable", rethink everything; 4 decisions answered via AskUserQuestion):** (1)
  ONE universal map component (`ooMap`, like ooChart/ooSubtabs) REPLACES every map surface
  (the Temporal-map tab + the When/Where mini `#map-svg` + ~7 touch-points); the time-slider
  becomes a CONTROL inside it. (2) CHOROPLETH-first: colour a geographic unit by a measured
  DATA dimension on a colour scale — sources/articles/keywords/sentiment/analytics per
  place; this genuinely did NOT exist (the old map only plots dots). (3) BIG: fills the
  content area minus tabs/subtabs (near-fullscreen). (4) IN-MAP controls (Google-Maps "inside
  the map" principle, already a ledger ruling): zoom +/−, legend, dimension/layer picker,
  granularity, pan — all overlaid INSIDE the map. GRANULARITY = country core + continent
  (aggregate of countries) + city/place POINTS overlay (switchable). PLACEMENT = rebuild the
  existing Temporal-map tab into it (no new top-level tab). HONESTY carries: no-data ≠ zero
  (a country with no data renders "no data", never a guessed colour); unlocated bucketed
  ("N not mapped"); VADER-EN-only caveat on the sentiment layer; "deduced, never confirmed"
  on mention layers; NO composite scores. SALVAGE: the equirectangular projection
  (lon2x/lat2y), the city gazetteer, the location endpoints (/api/insights/where·who·
  corpus-sources, KeywordMention.country, Source.country, sentiment-at-ingest). REDO: the
  entire visual layer. BUILD SEQUENCE (one PR per slice onto 0.09): (1) country-polygons
  foundation [SHIPPED 2026-06-18, below]; (2) ooMap core [SHIPPED 2026-06-18, below] (country
  fills + in-map zoom/pan + colour-scale legend + honest no-data; first dimension
  sources-per-country; big/fullscreen on the rebuilt Map tab); (3) dimensions [SHIPPED
  2026-06-18, below] (articles·keywords·sentiment, dimension picker,
  caveats); (4) granularity [SHIPPED 2026-06-18, below] (continent aggregation + city/place
  point overlay); (5)
  consolidation [maintainer chose "FOLD signals in, then retire" 2026-06-18 — 5a SHIPPED below]
  (fold the time-slider in, retire the old surfaces, embed ooMap on
  When/Where + insights).
  **SLICE 1 SHIPPED 2026-06-18 (the choropleth data foundation; backend VERIFIED py3.13):**
  a CHOROPLETH needs per-country FILL polygons — the app had only coastline/land outlines
  (`world_outline.json`, NE 110m land). NEW `src/timemap/countries_geo.py` =
  `coarsen_admin0(geojson)` (pure, network-free) → `{iso2: {name, rings}}` keyed by ISO-2,
  reusing outline.py's exact ring helpers; `iso2_of` honours NE's `ISO_A2="-99"` →
  `ISO_A2_EH` fallback (France/Norway), and a microstate keeps its LARGEST ring even below
  min_span so it never vanishes. NEW `scripts/build_country_polygons.py` (run-once-with-
  network, mirrors build_world_outline.py) fetches NE 110m admin-0 + coarsens. Generated
  the real asset HERE (sandbox network reached raw.githubusercontent): `src/static/
  world_countries.json` = 175 countries, 285 rings, **136 KB** (precision 1 ≈ 11 km, min_span
  0.5). HONEST GAP: NE 110m is too coarse for ~75 catalog microstates (Singapore/Malta/
  Tuvalu/HK…) → the renderer (slice 2) gives those a CENTROID POINT-FALLBACK from the
  gazetteer so no country with data is ever lost (NEVER invented borders). tests/
  test_countries_geo.py (8: iso2 fallback, ISO-keying, multipolygon, microstate-survives,
  no-ISO-dropped, asset shape+coverage). mypy 0-new (119≤127 — base drifted up via other
  merges, my module adds 0), ruff F/B clean.
  **SLICE 2 SHIPPED 2026-06-18 (the ooMap choropleth CORE; PR #368, draft onto 0.09;
  backend VERIFIED py3.13, frontend BROWSER-UNVERIFIED per fork-3):** the reusable
  `ooMap(host, opts)` component (no deps, like ooChart/ooSubtabs) in src/static/app.js —
  country FILL polygons coloured by a measured dimension on a theme-accent sequential scale
  (`_ooMapFill` via `color-mix(var(--accent)…)`, inherits all 17 themes; LINEAR, faithful to
  real skew not flattened); in-map zoom/pan (＋/－/⟲ + wheel + drag + ⛶) with an
  INSTANCE-LOCAL viewBox closure (`_wireOoMap`, no module globals, drag listeners add-on-down/
  remove-on-up so re-renders never leak); a colour-scale LEGEND (real min/max + unit); HONEST
  NO-DATA = a hatch `url(#oomap-nodata)`, visually distinct from zero (`t("no data")`, never a
  guessed colour); CENTROID POINT-FALLBACK for data-bearing territories the coarse 110m geometry
  has no polygon for (the ~75-microstate gap slice 1 flagged — plotted at the gazetteer centroid,
  `!geoCodes.has(...)`, a point NEVER an invented border); a11y `role="img"` + aria summary +
  `.sr-only` top list. Reuses slice-1 `world_countries.json` (175 countries) + the existing
  `lon2x`/`lat2y` projection (no second projection). FIRST DIMENSION = sources-per-country on the
  rebuilt Map (Temporal-map) tab: `queries.source_country_counts` groups sources + their articles
  by `Source.country`, country-less → an `unlocated` bucket NEVER mapped (counts only, no score);
  `GET /api/insights/map-coverage` enriches each located country with display name + continent +
  a centroid (geocode) and carries method+caveat. The existing temporal-map (signals + time
  slider) is KEPT BELOW for the slice-5 consolidation (the Desk lesson — nothing removed; slice 5
  folds the slider into ooMap as the in-map time control). +14 i18n keys ×12 (non-en AI-drafted,
  FLAGGED for native review). tests/test_map_coverage.py (grouping + unlocated bucket + endpoint
  enrichment + no-score) + test_repo_invariants::test_ooMap_choropleth; i18n --min 100 (1292×12),
  node --check, ruff F/B clean, mypy 119≤127 (0 on new lines). REMAINING: human click-through
  across themes/breakpoints; slice 3 (dimension picker articles·keywords·sentiment).
  **SLICE 3 SHIPPED 2026-06-18 (the DIMENSION PICKER; PR onto 0.09; backend VERIFIED py3.13,
  frontend BROWSER-UNVERIFIED per fork-3):** four choropleth dimensions switchable from an
  IN-MAP picker overlay (the "controls inside the map" convention) — Sources · Articles ·
  Keyword mentions · Mean tone. `queries.source_country_counts` extended: one article scan now
  also yields per-source-country mean TONE (`func.avg(Article.sentiment_score)` + scored-subset
  `sentiment_n`) and a KEYWORD-MENTIONS count via `KeywordMention.country` (the DENORMALISED
  source country → an index scan, NO keyword_mentions→articles row-decrypt join, honouring the
  perf-trap ledger fact); `/api/insights/map-coverage` passes them through. Frontend:
  `_ooMapPayload` caches the ONE payload so switching dimension is INSTANT (no re-fetch) —
  `_renderOoMapDim` re-colours from the active dim; `ooMap` gained `opts.dimensions`/`activeDim`/
  `onDimension` (the picker) + `opts.scale`. SIGNED data rides a DIVERGING scale: new
  `_ooMapFillDiverging` (theme `--err`←panel→`--ok`, 0 at centre) — sentiment never on a
  one-sided ramp; the legend branches sequential↔diverging. HONESTY: mean tone carries the VADER
  English-only caveat VISIBLE (B1) + `n=` scored count; a country with NO scored (English)
  article reports `sentiment=None` → the no-data hatch, never a fabricated zero; `unlocated`
  (country-less) data surfaced per count dimension, never mapped; counts only, no score (the tone
  field is `sentiment`, never a `*score*` key). +9 i18n keys ×12 (non-en AI-drafted, FLAGGED for
  native review). tests/test_map_coverage.py (+test_keywords_and_sentiment_dimensions: keyword
  count via denormalised country, mean-tone over scored subset, no-score) + test_ooMap_choropleth
  extended (picker + diverging + VADER caveat); i18n --min 100 (1301×12), node --check, ruff F/B
  clean, mypy 119≤127. NOTE: the sentiment dimension adds an article-row scan (direct, not the
  mention-join trap) — eager for instant switching; could go lazy if a huge corpus reports a slow
  Map load. REMAINING: human click-through; slice 4 (continent aggregation + city/place point
  overlay), slice 5 (fold the time-slider in, retire the old surfaces).
  **SLICE 4 SHIPPED 2026-06-18 (GRANULARITY — continent aggregation + place-points overlay; PR
  onto 0.09; FRONTEND-ONLY, BROWSER-UNVERIFIED per fork-3):** two in-map granularity controls
  (the "controls inside the map" convention, bottom-left). (a) CONTINENT AGGREGATION — a
  Country↔Continent toggle: `_ooMapContinentAgg` rolls the per-country values into the 6
  continents (`continent_of`, already on each map-coverage row since slice 2) — a SUM for counts,
  a `sentiment_n`-WEIGHTED mean for tone (the honest cross-country average, never a mean-of-means);
  each country is then PAINTED by its continent's aggregate (country borders stay visible, colours
  group by continent — no continent-polygon union needed, no new geometry/endpoint); the hover +
  sr-list show the continent + its aggregate. (b) PLACE-POINTS OVERLAY — a switchable "Places"
  layer plotting the corpus's MENTIONED places (reuses the LOCAL `/api/insights/where`, lazy-
  fetched once, capped 400) as HOLLOW markers DISTINCT from the solid centroid-fallback points,
  sized by article spread (√, raw count) — a different data layer (what the corpus is ABOUT) over
  the source-coverage fills, with the endpoint's "deduced from text, never confirmed" caveat
  VISIBLE when on. `ooMap` gained `opts.granularity`/`onGranularity` + `placesOn`/`overlayPoints`/
  `onPlaces` + `srRows` (continent-level sr summary); the loader owns the state (`_ooMapGran`,
  `_ooMapPlacesOn`, cached `_ooMapWhere`) and re-renders on toggle. NO backend change (continent
  from slice 2 + the existing WHERE endpoint, both local). HONESTY: an unknown-continent country
  is no-data in continent mode (never a fabricated continent); the overlay is a deduced layer
  clearly labelled; counts only, no score. +7 i18n keys ×12 (non-en AI-drafted, FLAGGED for native
  review). tests/test_map_coverage.py pins the `continent` field contract; test_ooMap_choropleth
  extended (continent aggregator + weighted-mean tone + granularity/places controls + the deduced
  caveat). i18n --min 100 (1308×12), node --check, ruff F/B clean (no Python source changed).
  **CONTINENT-NAME i18n FOLLOW-UP SHIPPED 2026-06-18 (maintainer asked "did you think about having
  the map's UI also part of the entire translation"): the 6 CONTINENT names (Europe/Asia/Africa/
  North America/South America/Oceania) the slice-4 aggregation renders are now routed through
  `t()` (in `_renderOoMapDim`'s point label + `fmtV` hover + `srRows`) and KEYED ×12 (standard
  continent translations), so the continent-granularity labels are fully localised — the map's
  CHROME was already ×12 (controls/legends/caveats); this closes the bounded data-vocabulary the
  map itself introduced. +6 i18n keys ×12; test_ooMap_choropleth asserts `t(r.continent)`.
  **COUNTRY-NAME i18n SHIPPED 2026-06-18 (the follow-up to the continent fix; PR onto 0.09;
  FRONTEND-ONLY, BROWSER-UNVERIFIED):** the displayed country NAMES are now localised via the
  BROWSER'S OWN CLDR data — a reusable `ooRegionName(code, fallback)` = `new Intl.DisplayNames([
  OOI18N.current()], {type:"region"}).of(CODE)` (per-lang cached, try/catch + fallback to the
  supplied English name / the code). Verified accurate across en/fr/de/zh/ar/ja/ru
  (France/États-Unis/Chine · 法国/美国/中国 · فرنسا …) and SAFE on unknown structurally-valid codes
  (.of("ZY")→"ZY", no throw). Applied where the UI shows a country as a NAME: the map (ooMap
  polygon hover `ooRegionName(code, c.name)` + the loader's `names` map → centroid labels + sr-list
  + valueLabel) and the Sources table cell. KEY INSIGHT (corrects the earlier "English everywhere"
  read): MOST of the app already shows the language-neutral ISO CODE (FR/US), which correctly STAYS
  a code (like url anchors) — only the few NAME surfaces needed localising, and CLDR gives every
  locale with ZERO translation tables / ZERO new i18n keys. test_ooMap_choropleth asserts the
  helper + Intl.DisplayNames region + the map use. REMAINING: adopt `ooRegionName` on any other
  name-surface found in a click-through; the map's English-only continent SET was the keyed case,
  country names are the CLDR case.
  **SLICE 5 — maintainer chose "FOLD signals in, then retire" (AskUserQuestion 2026-06-18): make
  ooMap the ONE map (events become a layer, the slider an in-map control), THEN retire the old
  temporal map. Built as stacked PRs (5a additive layer+slider, 5b retire).**
  **SLICE 5a SHIPPED 2026-06-18 (the SIGNALS layer + in-map TIME SLIDER on ooMap; PR onto 0.09;
  FRONTEND-ONLY, BROWSER-UNVERIFIED per fork-3):** ooMap gained a switchable "Signals" layer
  (bottom-left control group, beside Country/Continent/Places) that plots the temporal map's
  space-time EVENTS as kind-coloured points — REUSING the existing LOCAL `/api/timemap?limit=4000`
  substrate (no hazards flag → no live-hazard network; airplane-safe) + its helpers
  (`kindColor`/`TMAP_KINDS`/`fmtYear`/`fmtDate`) + its honest convention (confirmed = filled,
  future/unconfirmed = a hollow/dashed ring; faded by distance in time). An in-map TIME SLIDER
  (full-width, appears above the controls when Signals is on) sweeps the focus MOMENT (antiquity →
  near-future): the loader derives the time span from the plottable signals, maps the slider 0–1000
  to a focus year, and uses an ADAPTIVE window (~span/12) so the sweep is meaningful at any range;
  signals filter by `|s.t − focus| ≤ window`. A kind LEGEND (the kinds present) shows in the legend
  row. Signals are LAZY-fetched on first toggle (like Places), filtered to those with a numeric `t`
  + coordinates (never re-projected — reuses lon2x/lat2y). Slider drags are rAF-COALESCED (≤1
  re-render/frame). `ooMap` gained `opts.signals`/`signalsOn`/`onSignals` + `focusT`/`windowY`/
  `focusSlider`/`focusLabel`/`onFocus`. The OLD temporal map is UNTOUCHED (additive — 5b retires it
  after verifying ooMap absorbs it; the Desk lesson). +2 i18n keys ×12 (Signals · Moment in focus).
  test_ooMap_choropleth extended (signals toggle + /api/timemap reuse + kindColor + the focus-window
  filter + the future-ring honesty + the slider). i18n --min 100 (1316×12), node --check, full
  test_repo_invariants 67 passed. NO backend change. REMAINING: click-to-detail on a signal (the
  temporal map's rich panel — fold before retiring); per-render perf on huge corpora (full SVG
  rebuild on slide — could update only the signals layer); 5b (retire #oo-tmap, absorption-gated) +
  embed ooMap on When/Where + Insights.
- **Home cards remainder:** **ALL CARDS CLICKABLE — SHIPPED 2026-06-16 (Item I,
  maintainer-ruled "clickable cards open an advanced search / the unified interface
  with all analytics subtabs, whose corpus corresponds to the selection of articles
  the card identified"):** every card body now opens the UNIFIED analysis window
  (#tab-analyze) via the proven `openAnalysisFor(query)` — NOT the standalone
  /investigate new tab (that stays as the explicit "Open investigation ↗" button).
  The seed query = `cardAnalyzeQuery(c)`: the quoted term in the title (original
  searchable surface form) → the serialized card `key` (normalized term/identity; NOW
  added to Card.to_dict) → the bare title. For keyword/topic cards (the majority) this
  reproduces the EXACT, FULL selection (openAnalysisFor re-runs the same FTS search);
  for set-based cards it is the closest honest query and the analysis window states
  its scope. Clicks on inner buttons/links/inputs are ignored. +1 hover title ×12.
  AUTONOMOUS CALL: query-seed v1 (no backend change beyond serializing `key`).
  **ARTICLE-ID-EXACT SEEDING SHIPPED 2026-06-16 (maintainer-ruled "exact set for every
  card", PRs #241 + producers/frontend):** all 5 analysis endpoints (corpus-keywords/
  www/sentiment/sources + links/corpus) accept an explicit `article_ids` set via the
  shared `_resolve_corpus` (explicit set wins over search; deduped/bounded/total
  disclosed; search path byte-unchanged); set-based cards carry their FULL set on the
  Card (`article_ids` field + to_dict) — convergence = `c["article_ids"]`, echo-chamber
  = ALL coordinated representatives (not the 4-item sample); the frontend
  `openAnalysisForIds(ids,label)` + `_anIds` threads them through every subtab via
  `anParams` (cleared on a fresh query / Advanced refine). PER-PRODUCER NUANCE (ruled
  by the data, not uniform): reading-diet is a WHOLE-CORPUS source distribution with no
  single clean set → it keeps the query/source seed, NOT a fabricated id list. Tests:
  test_corpus_endpoints_accept_explicit_article_ids + the convergence producer asserts
  card.article_ids == the exact converging set. Earlier note kept: per-card-TYPE investigate views
  (rising→trend+associations; diet/coverage→sources; echo→integrity; law/wiki→reader)
  + the card-feed visual/UX remake still wanted (flagship surface). **REMOVE the home HERO card — SHIPPED 2026-06-14:** the
  "Understand the world as it really is. / Your private, offline research
  desk…" hero block + its #hero-greet time-of-day greeting JS (in loadHome) +
  the dedicated `.hero` CSS are DELETED; no greeting survives (none to key).
  Home now opens on the Briefing. Same PR keyed the #onboard "Welcome — your
  corpus is empty" card (h2/p/button) ×12 (resolves the i18n REPEAT below).
  **HOME REDESIGN (ruled 2026-06-13; §5) — COMPLETE 2026-06-14:** SLICE 1
  (#128) — "At a glance" is now a PERMANENT + COMPACT strip at the very top
  (`.home-glance`/`.stat-strip`, loadHome renders compact chips); Quick actions
  REMOVED (+ dead `.quick`/`.qcard` CSS). SLICE 2 (#129) — cards DENSER (grid
  minmax 300→240px, 4+ fit); card FAMILIES are VERTICAL SUBTABS built in
  renderBriefing via the ooSubtabs component (now a 4th surface) with an "All
  cards" DEFAULT lens (selectHomeFamily filters by data-fam) + a deterministic
  per-family HUE shown as a tab dot and a card left-accent (--fam); "All" stays
  the single prioritised feed (lens not a wall). test_ui_invariants #19/#19b
  pin it. Home empty-state fail-safe preserved (subtab bar only when >1 bucket).
- **UI RETHINK — MAINTAINER PLANNING SESSION 2026-06-16 (NOW THE ACTIVE CENTERPIECE,
  ruled 2026-06-16 — supersedes 'design-only'; the autonomous 'everything' batch builds
  this FIRST among the big items. Browser-unverifiable here ⇒ ships CONSERVATIVE +
  FLAGGED per fork-3: node --check + EXTEND test_ui_invariants + defensive states, each
  PR marked 'browser-unverified, needs click-through' (no headless harness, no dark
  feature-flag).
  ONE coherent vision spanning nav + Home + Analysis; REVISES invariants
  #2/#3/#4/#18/#19 + UI_SHELL_REDESIGN_PLAN §1/§5 + the TWO-windows debt — all
  test_ui_invariants-enforced, so any change ripples into that test):**
  - **(1) NAV MOVES TO THE TOP (revisits #2/#3/#4/#18):** the tabs move to a
    FULL-WIDTH horizontal bar at the VERY TOP, beneath a THIN status bar that
    holds only simple action toggles (search · status · airplane · language ·
    help). Tabs FILL the width with a MAX reasonable width each; the active tab is
    CLEARLY indicated while inactive tabs are discreet-but-clearly-visible.
    **RESOLVED 2026-06-16 → B: KEEP the left sidebar for MAIN sections (invariant
    #2 INTACT); move ONLY the in-section FACET subtabs to the full-width top bar
    beneath the thin status bar. Layout: thin status bar (top) → full-width
    facet-subtab strip → left sidebar + content. The parallel analysis tabs (item
    4) fit naturally in that top strip within the Analysis section, named by query;
    the per-analysis facets (Keywords/Mindmap/…) stay an inner row — the exact
    two-level presentation is a build detail. UI_SHELL_REDESIGN_PLAN §1 stands
    (sidebar = main tabs); this only RELOCATES the facet subtabs to the very top.**
  - **(2) HOME → DASHBOARD / HELICOPTER VIEW (extends #19; everything REDUNDANT
    per #8 — Home gives NO unique information):** Home becomes a landing the user
    is HAPPY to reach + a launchpad to start digging into the specialized tabs;
    nothing on it is unique (every element deep-links to its real tab). SECTIONS
    (maintainer list, more invited): top GRAPHS (ooChart, sparse→bars per Item Y),
    keyword TRENDS, top CARDS, DYNAMIC data-driven sections (e.g. a commodity's
    price graph surfaces WHEN its keyword family is trending), a CAROUSEL of
    rolling/simplified/SYNTHESIZED cards, "most recent" articles by TAG. Selection
    is INDUCED by background analytics over the DB yet TWEAKABLE (build on the
    recipes.py producer toggles). HONESTY GUARDRAILS (binding): "top"/ranking is an
    HONEST ordering (evidence tier + recency + corpus spread + _trigger), NEVER a
    hidden importance score (assert_no_score_fields); "synthesized" = LOCAL
    ANALYTIC synthesis, NEVER LLM output (zero-network Home; LLM-less is the asset);
    caveats VISIBLE by default (#23) even in compact tiles; the carousel is
    user-controlled + a11y (pausable/keyboard) and NEVER hides a caveat behind a
    timed rotation; Home never blank-and-silent (fail-safe empty state).
    **TRENDS GLANCE SHIPPED 2026-06-16 (Item 4b, first dashboard section,
    conservative/browser-unverified):** a compact "Trending now" panel
    (`#home-trends-panel`/`#home-trends`, `loadHomeTrends`) renders the PAST-WEEK
    rising keywords (the disclosed window-vs-baseline RATE from
    /api/insights/trending-windows — NEVER a score) as chips with a small honest
    sparkline (`dashChartSvg`: line dense / Item-Y bars sparse). REDUNDANT by
    construction (#8): each term DEEP-LINKS to its analysis window (openAnalysisFor),
    "More in Insights →" deep-links to the canonical Trends subtab; the API caveat
    is VISIBLE; the panel DEFAULTS HIDDEN and only appears when something is trending
    (Home never blank-and-silent — the Briefing still renders). Reuses the existing
    endpoint + renderer (no new backend, no new poll — rides loadHome +
    refreshHomeLive). +2 i18n ×12; test_ui_invariants #19c. REMAINING: top
    ooChart graphs, the synthesized-Leads carousel (pausable/a11y), dynamic
    commodity-when-trending sections, most-recent-by-tag.
  - **(3) NAME THE CARD SYSTEM (brainstorm WITH the maintainer — NO name chosen
    yet):** today = "briefing cards" / "producers" / "buckets" (src/briefing). A
    card = one measured signal + evidence + method + caveat = a SOURCED, CAVEATED
    PROMPT TO INVESTIGATE ("assistance never a verdict"; "a microscope not a
    detector"; "name the shape"). Seeded candidates: Leads · Cues · Soundings ·
    Readouts · Vantages (NOTE: "Signals" collides with src/signals/). **RESOLVED
    2026-06-16 → "LEADS"** (a card = a Lead: an investigative starting point to
    dig). Rename the USER-FACING label ×12 locales; the internal src/briefing
    module + bucket names can stay or rename later (cosmetic). **SHIPPED 2026-06-16:**
    17 i18n-keyed user-facing strings renamed card→Lead/cards→Leads (key + value ×12,
    existing professional translations with only the card-word swapped: fr piste · de
    Spur · es/pt pista · ru зацепка all cases · ar خيط · zh 线索 · ja 手がかり · hi सुराग
    · bn সূত্র · id petunjuk — AI-drafted, flagged for native review) + ~9 non-keyed
    English-only strings, across app.js · index.html · investigate.html ·
    briefing/producers.py · briefing/draft.py. NO CSS class / JS identifier / dict
    key / bucket name touched (internal stays "card"); markets.py "price card" left
    as-is (not a briefing card). test_ui_invariants #19b re-keyed "All cards"→"All
    Leads". i18n 100% ×12, audit-chrome "card"-clean, full suite green, mypy 112.
  - **(4) ANALYSIS = NAMED, PARALLEL, SPAWNED TABS (ruled 2026-06-16; fixes the
    "weird empty Analysis tab" + likely retires the TWO-windows debt):** today
    clicking the sidebar "Analysis" tab opens the SINGLETON #an EMPTY (no corpus
    until you search; #an-query shows "(all articles matching your filters)") and
    openAnalysis/openAnalysisFor REUSE that one tab = confusing. RULING: a
    search/term OPENS A NEW analysis tab (one instance per search), TITLED by the
    query term (or "synthesis" for a composite), and SEVERAL parallel searches
    coexist as DIFFERENT tabs (a multi-document workspace). The empty singleton
    Analysis entry goes away (a launcher at most). DEPENDS ON (1) (where spawned
    tabs live) + folds in the #an ↔ #corpus-win consolidation. **RESOLVED
    2026-06-16:** tabs are CLOSEABLE, soft-CAPPED, and PERSISTED across sessions
    (restored on reload). With nav=B, the spawned tabs live in the top
    facet-subtab strip under the Analysis section.
  - **(5) INSIGHTS = THE NON-SEARCHABLE OVERVIEW + THE CANONICAL HOME OF THE CARDS
    (ruled 2026-06-16; clarifies #8/#21 + the Home(2)↔Insights split):** REMOVE the
    Insights search bar (#ins-term + the Explore button + exploreTerm, index.html
    ~1315) — typing a term IS search and belongs to the omnibar → a spawned
    analysis tab (item 4); the removal is GATED on that absorption so the
    term-exploration (mind-map for a term, its trend) is NEVER lost (the Desk
    lesson). Insights then shows ONLY non-searchable aggregates: a recently-
    TRENDING-keywords graph, keyword FAMILIES + SUPER-GROUPS, TRENDING SOURCES,
    UPCOMING EVENTS, etc. (the existing Trends/Families/Groups/Sources/Map subtabs
    + the click-to-zoom landscape & mind-map become the BROWSE path; deep digging
    into one term = the analysis tab). THE CARDS MOVE from Home INTO Insights =
    their canonical home; Home(2) keeps only a REDUNDANT curated "top cards" subset
    (consistent with #8 + the Home-is-redundant principle). "Upcoming events" here
    is a redundant lens onto the Agenda tab (fine, by design). **TRENDS SUBTAB
    SPEC (maintainer 2026-06-16):** show RISING keywords across THREE preset
    windows — past 24h · past week · a longer one (month/all-time, exact span TBD)
    — side by side (today it is ONE adjustable window via /api/insights/trending
    window_days+baseline_days) + the TOP 5 keywords each rendered with a rich
    time-series GRAPH (ooChart, full-resolution invariant #16, sparse→bars per
    Item Y; today #trd-top is a plain list via /api/insights/top). HONESTY: 24h is
    sparse on a young corpus → n shown + early-corpus caveat + honest empty state;
    rising = window-vs-baseline RATE (method stated, no momentum score); top =
    most-mentioned ordering (basis stated), never a composite score. **LOCATION
    CLARIFIED 2026-06-16 (maintainer asked):** Trends is the Insights tab → Trends
    subtab (#ins-trends). THIRD-WINDOW SPAN RESOLVED 2026-06-16 → PAST MONTH
    (the three windows = past 24h · past week · past month, side by side).
    **BACKEND SUBSTRATE SHIPPED 2026-06-16:** `queries.trending_windows` +
    `GET /api/insights/trending-windows` return the THREE preset windows side by
    side (24h/7d/30d, each its own prior-period baseline), reusing `trending` (the
    same disclosed recent-vs-prior RATE RATIO, never a score); each term carries its
    raw `recent` count (n) + the early-corpus caveat travels with the data.
    tests/test_trending_windows.py. **FRONTEND SLICE 1 SHIPPED 2026-06-16 (conservative,
    browser-unverified):** `#trd-windows` panel + `loadTrendWindows()` render the THREE
    windows side by side (translated "Past 24h/week/month" labels + per-window n + the
    caveat), reusing `termListHtml`; ADDITIVE — the adjustable single-window Rising/Top
    view stays below (the Desk lesson); defensive (error leaves the single-window view
    intact). +5 strings ×12; test_ui_invariants #21b pins `#trd-windows` + the loader.
    SERIES BACKEND SHIPPED 2026-06-16: `/api/insights/trending-windows?series_top=N` (an
    ADDITIVE param, default 0 = unchanged) attaches a daily `series:[{date,count}]` to the
    first N terms of each window, REUSING `queries.trend(bucket="day")` sliced to the window
    range so the numbers match the existing trend chart (counts only, no score;
    tests/test_trending_windows_series.py). FRONTEND SHIPPED 2026-06-16 (conservative,
    browser-unverified): `loadTrendWindows` requests `series_top=5` and renders each top
    term's daily series as a small honest sparkline via the shared `dashChartSvg` (line when
    dense, Item-Y bars when sparse — NEVER an interpolated curve); the rest stay the plain
    list; ZERO new i18n keys (reuses existing strings); test_ui_invariants #21b+. CLICK-TO-
    ENLARGE SHIPPED 2026-06-16 (conservative, browser-unverified): each sparkline carries a
    ⛶ button → `enlargeTrend(wi,ti)` → the REUSABLE `chartEnlarge(title,seriesList,caveat)`
    modal `<dialog id="chart-enlarge">` rendering the term's daily series as a full interactive
    `ooChart` (invariant #16: wheel-zoom / drag-pan / hover-readout / legend; Item-Y bars when
    n<10). NO extra fetch — the series is already in the `_trendWindowsData` payload. ZERO new
    i18n keys (reuses "Enlarge the chart"/"Past 24h|week|month"/"mentions"/"Close"); caveat
    VISIBLE by default; native showModal traps focus (OO-D13-001). test_ui_invariants #21b++.
    REMAINING: the maintainer's wider Trends redesign (remove the Insights search bar once the
    omnibar absorbs term-exploration).
  - **(6) UNIFIED 3D KEYWORD EXPLORER (ruled 2026-06-16; maintainer FLAGSHIP —
    "important to me", "incredible UI/UX"; evolves the mind-map rules + #mm-kit;
    lives in Insights per (5)):** THREE fixes + one big rework. FIXES: (a) the
    control buttons (#mm-levels + #mm-views + period/size/enlarge, index.html
    ~1336 flex row) OVERLAP — fix the responsive layout (largely SUBSUMED once the
    levels unify); (b) "Enlarge" (mmExpand today only toggles a .mm-big CSS class,
    NOT real fullscreen) → TRUE Fullscreen API (requestFullscreen) with a CLEAR
    visible EXIT control IN ADDITION to Esc. REWORK: UNIFY Keywords / Families /
    Super-groups (today 3 toggled levels via mmLevel) into ONE continuous
    exploration — a 3D LAYERED hierarchy: super-groups ABOVE families ABOVE
    keywords (depth = level), navigated continuously (zoom/drill + LOD) rather than
    switched. HONEST VISUAL ENCODINGS for trends · importance · language-spread ·
    territory-spread, etc. — each mapped to a REAL measured quantity with a stated
    method, NEVER a composite "importance score" (assert_no_score discipline
    carries to the viz): size ∝ real mention/spread count (n shown); trend =
    windowed rise/fall (early-corpus caveat + Item-Y sparse honesty); language
    spread = distinct languages (signatures); territory spread = distinct countries
    (per-source-country split + the When×Where gazetteer). DECISIONS/CONSTRAINTS to
    settle at build: (i) 3D TECH = a dependency/architecture RULING — bundled-local
    WebGL (Three.js, heavier) vs hand-rolled canvas 2.5D / CSS-3D (lighter,
    deterministic, fits local-first + deterministic-mind-map + no-heavy-deps); my
    lean = the lightest approach that still reads as 3D, bundled LOOPBACK-ONLY (no
    CDN). **RESOLVED 2026-06-16 → A: lightweight, hand-rolled (canvas 2.5D /
    CSS-3D); NO Three.js/WebGL dependency.** (ii) PERFORMANCE/LOD: 62k+ keywords live — cannot render all; LOD
    (super-groups → drill a family → its keywords), bounded. (iii) a11y +
    REDUNDANCY: 3D must NOT be the ONLY access path — keep the tabular
    Families/Groups views + the word-cloud second view; the deterministic mind-map
    rules (outward, no cross-tangle, no fabricated structure) carry into the layered
    3D form. date-spectrum + text-size controls stay (plus fullscreen).
- **UI SHELL REDESIGN (ruled 2026-06-13; full plan in
  `docs/product/UI_SHELL_REDESIGN_PLAN.md`):** (1) ONE universal nav grammar
  app-wide — LATERAL sidebar = main tabs, VERTICAL subtabs near the top =
  subcategories (Home families, Insights sections, Settings, corpora window);
  reusable subtab component, invariant-tested; sidebar invariant #2 intact.
  (2) MINIMAL TOP BAR — above the subtabs ONLY: always-on search, status,
  task-manager access, help, language picker, airplane button; vitals move
  into the task-manager window's System tab (invariant #4 — version still not
  in chrome). (3) AIRPLANE BUTTON moves to the top bar, NO text (hover
  bubble enough, invariant #17); FILL=state stays (invariant #14) but the
  transition uses DIFFERENT colors by direction, coherent with the icon's
  on/off color (today one red transition conflates the two opposite
  meanings). (4) SEARCH bigger + always-on; REMOVE the visible "Ctrl K" hint
  (index.html:646); permanent "Advanced" button; shortcuts list → Help +
  editable in Settings (a keybindings panel); small-screen overlaid text
  dropped. **CHROME SLICE SHIPPED 2026-06-15 (field test,
  field-test-2026-06-15/LEDGER.md Item B): the visible "Ctrl K" badge is GONE
  from the top omnibar (the Ctrl/⌘-K shortcut still works); the omnibar hover
  bubble (invariant #17) was the UNTRANSLATED English "Command palette" — now
  the keyed, translated ×12 "Search everything — articles, dates, locations,
  settings, etc." (omnibar aria-label matches); the palette dialog aria-label is
  the keyed "Search everything" ×12, so the LAST "Command palette" untranslatable
  string is gone (--audit-chrome clean; i18n 100%). The visible placeholder
  already read "Search everything — data, tools, actions, docs…".** (5) ENTER →
  the advanced-search WINDOW = the corpora flagship
  (keyword/mindmap/link/source/WWW/sentiment/Advanced sub-tabs). HONEST
  STATUS recorded (answers "I can't find this UI"): palette shipped T13 s1,
  keyword→corpus window shipped T10 s1 (Trend/Articles/Links only); the FULL
  Enter→corpus window with the analysis sub-tabs is the REMAINING slice — not
  lost, not yet built; PROMOTE it. **Maintainer REPEATED this 2026-06-15
  ("two search entries, I prefer only the top one … there should not be a search
  button in the tabs"): the SECOND entry is the Search SIDEBAR TAB
  (data-tab="search" → #tab-search). Removing it is GATED on (5) — #tab-search
  still owns Boolean query, source/lang/date filters, Export CSV/JSON, Methods
  appendix, Synthesize results, and Export SIGNED EVIDENCE; the Enter→window must
  ABSORB all of these first (never silently lose a tool). So the tab STAYS until
  (5) lands; do NOT delete it early.** (6) INSIGHTS: auto-index in the
  background, REMOVE the "Index corpus" button (index.html:1287) + its
  palette action (index.html:2655); present Insights sections as subtabs.
- **TWO BUGS found in the field session (ruled to fix, diagnosed in the UI
  plan §7):** (a) the BACK BUTTON returns to the passphrase screen — tab nav
  uses history.replaceState (index.html:2524, no history entries) and a
  locked API response does location.href="/unlock" (index.html:2451), so
  Back lands on /unlock; fix = pushState for tab nav + replaceState to "/"
  after unlock. **VERIFIED ALREADY FIXED 2026-06-16 (Tier-0 pass, no code change
  needed): all three are done in code — tab nav uses pushState (src/static/app.js,
  with replaceState only for the initial load), the locked-API response uses
  location.replace("/unlock") (no history entry), and unlock.html redirects via
  location.replace("/") ("replace so /unlock never sits in history"). The
  index.html:2524/2451 pointers predate the #236 decomposition; that JS lives in
  app.js/unlock.html now.** (b) "Scraping STOPPED" is NOT a crash — the scheduler idles
  interval_minutes between passes (runner.py:326); the content-first
  continuous-collection ruling makes the idle gap + the in-face arbitration
  modal disappear (app boots in AIRPLANE MODE; permanent scraping when
  online; new requests QUEUE into the task manager, never a modal — recorded
  in SCRAPING_AUTOMATION_PLAN.md Step 5 refinements).
- **AIRPLANE-MODE ONBOARDING INVITATION — SHIPPED 2026-06-14 (frontend
  coachmark):** `#net-coach` in index.html — a dismissible bubble that anchors
  to the airplane button (`#net-toggle`, via getBoundingClientRect, so it follows
  the button when the UI-shell top-bar move lands), shown once we first learn
  we're offline. INVITATION LAYER ONLY by construction: the "Go online" action
  runs `dismissNetCoach(true); toggleNetwork()` → `ensureOnline` (the ONE consent
  popup still fires — the coach NEVER POSTs the network itself; enforced by
  test_ui_invariants #14b). Prominent (pulse) on the first two launches, subtle
  after, capped at 6 auto-shows, retired for good once the user goes online or
  taps "Not now" (localStorage `oo_net_coach_v1`; never naggy). +3 strings ×12
  (en + real translations; "Go online" reused). REMAINING from the ruling: fold
  into the guided wizard's final consented-first-collect step; the optional
  on-button "offline — tap to collect" affordance + Home empty-state CTA.
  Original ruling below.
- **AIRPLANE-MODE ONBOARDING INVITATION (ruled 2026-06-13):** boot-offline
  (SHIPPED #114) needs a teaching affordance — at startup, a simple UI
  BUBBLE/coachmark points at the ONE airplane button and INVITES "switch
  airplane mode off to go online and start collecting." It teaches the single
  online/offline control intuitively (no manual). CONSTRAINT (binding, informed
  consent is non-negotiable / invariant #14): the bubble is the INVITATION layer
  ONLY — the offline→online transition STILL passes the ONE consent popup
  (`ensureOnline`: names the action, local interface IPs, honest public-IP
  wording); the bubble does NOT replace consent. So the flow reframes from a
  "grant permission?" gate to "here's the one switch, flip it when ready" while
  consent stays by-construction (informed-consent-by-LAYERING). Bubble ships ×12,
  dismissible, prominent on first launches / subtle for returning users, never
  naggy; uses the #oo-tip hover convention; folds into the guided wizard's final
  consented-first-collect step. Complementary angles recorded (maintainer invited
  ideas): a faint "offline — tap to collect" affordance on the button itself; a
  Home empty-state CTA. FRONTEND slice (lands with the UI-shell airplane-to-top-bar
  move). My recorded opinion: strong yes.
- **TOR INTEGRATION + PER-SOURCE TRANSPORT (maintainer concept + question
  2026-06-13; my critical assessment recorded, full design in
  FUTURE_DEVELOPMENTS "Reliable Tor & per-source transport"):** concept = embed/
  manage a reliable, up-to-date Tor via an open-source library, enabling
  per-source transport (clearnet for Tor-hostile sources, Tor for the rest, "to
  protect the user ID from other sources"). MY HONEST/SCIENTIFIC VERDICT: (1)
  LIBRARIES — there is NO pure-Python Tor; the mature path is CONTROLLING a `tor`
  process via **Stem** (the official Tor Project lib, LGPL) or txtorcon — you
  still need the `tor` binary (user-installed, or bundled ~few MB à la Tor
  Browser). **Arti** (Tor's Rust rewrite, an embeddable client crate) is the
  future, but its PYTHON bindings are NASCENT as of the Jan-2026 knowledge cutoff
  — VERIFY maturity before betting on it. PySocks (already used) is only the SOCKS
  client. (2) The current model — user runs+trusts the SOCKS proxy; the app
  USES+verifies it and NEVER CLAIMS anonymity — is the correct ethical baseline;
  embedding only lowers the setup barrier, it does not change the guarantees. (3)
  The hybrid intuition is PARTLY right (per-source compartmentalisation: a
  clearnet source sees you, a Tor source does not) BUT carries caveats that must
  be surfaced with NO fabricated security: clearnet for source A reveals the
  user's REAL IP + (via our honest bot UA) that they run THIS app + their topic
  interest — to A, A's CDN/trackers, AND the ISP; cross-transport correlation can
  link behaviour. This is EXACTLY the "NEVER silently downgrade transport"
  non-negotiable, so clearnet-for-some must be EXPLICIT, PER-SOURCE, CONSENTED,
  last-resort, with the UI brutally honest about what each choice exposes — never
  automatic, never the headline. (4) SUPERIOR alternative for "protect from other
  sources": per-source TOR STREAM/CIRCUIT ISOLATION (`IsolateSOCKSAuth` — already
  our primitive, used for parallel dumps #110) compartmentalises WITHOUT any
  clearnet exposure; prefer it. DIRECTION: ease Tor (optional in-app Stem-controlled
  setup, like the planned Ollama installer) + per-source circuit isolation by
  default; treat clearnet-for-Tor-hostile-sources as an explicit consented opt-in.
  Filed with open questions in FUTURE_DEVELOPMENTS.
- **Evidence-tiered cards — PRODUCER SWEEP DONE (PR #204, 2026-06-15):** ALL
  card-emitting producers now carry the `_trigger` evidence tier — slice 1 did 11,
  PR #204 added the last 6 (emotion_profile_card, ip_litigation_pulse,
  ownership_change, law_change, model_legislation, story_lineage). Honesty held: real
  values only (ip_litigation_pulse = real rate_ratio_interval CI degrading to "—";
  emotion = guarded frequency share; model_legislation/story_lineage = real avg
  Jaccard + threshold; ownership_change/law_change = DELIBERATELY descriptive-only
  real counts/byte-deltas, NEVER an invented CI), no composite scores
  (CardSchemaError untouched); test_corpus_producers_all_carry_a_trigger sweeps every
  default producer. CORPUS TIER HEADER SHIPPED (PR #210): a descriptive
  early/developing/established stage on the Home glance strip from real corpus
  facts (corpus_tier in producers.py reuses _is_young; additive briefing field;
  NO score; thresholds <200 art or <14d → early, ≥1000 art and ≥90d → established;
  visible early caveat + invariant-#17 threshold hover as ONE atomic placeholder
  sentence ×12). REMAINING slices: power-style "what's missing"; BH-FDR later.
- **Trans-language equivalence — LIVE analytics layer — SLICE 1 SHIPPED 2026-06-16
  (draft PR onto 0.09; was elevated/groundwork-only):** `src/analytics/equivalence.py`
  is the LIVE consumer `configs/keyword_equivalents.yml` always lacked (verified NOT
  wired before). Rings now merge inside the grouped `top_terms`
  (`/api/insights/top?group=true`), `trending`/`trending-windows`, and
  `associations`/`graph` (keyword + family levels) — `fr:élection + en:election +
  de:wahl` collapse to ONE concept. Layered ON TOP of within-language families. Honesty
  held (all the standing guards): a keyword joins a ring only when its EFFECTIVE language
  matches the member's — stored `Keyword.language`, else the dominant `language_signature`
  (the signature-supported join, computed cheaply only for unknown-language ring
  candidates), so an en-dominant "main" stays OUT of the fr `hand` ring; per-language
  counts stay VISIBLE (`language_breakdown` + `members` on every merged row); a user
  `KeywordFamilyOverride` split keeps a member out; method/caveat disclosed
  (`rings_merged`+`caveat`); `OO_KEYWORD_EQUIV=0` disables; missing/empty file = no-op
  (never invents). Reusable `group_rows` primitive so each view aggregates its OWN fields
  (mentions / cooccur+pmi / recent+prior). tests/test_keyword_equivalence.py (8: pure +
  in-memory integration incl. the signature fallback + polysemy + split).
  CROSS-COUNTRY SPLIT SHIPPED 2026-06-17 (backend): `queries.ring_country_split` +
  `GET /api/insights/ring-countries` group a ring's mentions across ALL its languages by
  the producing Source.country (the de-US-centring multi-perspective lens — counts only,
  no score, language-qualified membership via `ring_of` so never a fabricated merge,
  unlocated sources bucketed null never dropped); tests/test_ring_country_split.py (3).
  REMAINING: the frontend view of the split; the map view; surfacing `language_breakdown`
  in the frontend; the local LLM PROPOSING candidate rings (the analyzer from PR #279
  already emits ring candidates from the diagnostics logs).
- **TRUST TABS → DISSOLVE + SPREAD (RULED 2026-06-15; supersedes the old "Custody tab UX"
  note; full design = field-test LEDGER Item N):** the "Trust" sidebar group (Evidence &
  custody + Source integrity) is DISSOLVED (invariant #8 content-first; absorption-test-gated,
  the Desk lesson). **INTEGRITY** goes AMBIENT + AUTO — a background coordination pass (like the
  #21 auto-index), inline plain-language "N near-identical copies = 1 voice [show all]" in
  search/reader/analysis (the LINKS anti-false-triangulation surface), web-of-trust annotations
  on the source chip. **CUSTODY** becomes an ACTION on content (export/verify tamper-evidence on
  any article/corpus) with **auto-log ON BY DEFAULT (opt-out in Settings)**, the
  Merkle/Ed25519/OTS detail in the #oo-tip hover; prefs move to Settings; **OTS/Bitcoin stays
  OFF by default** (network egress reveals IP/timing). **PARKED behind the analysis-window build
  + the search UI** (maintainer-sequenced 2026-06-15). i18n folds into the rework (don't key
  strings we're about to move).
  **AMBIENT-IN-ANALYSIS SLICE SHIPPED 2026-06-17 (maintainer re-raised "make the coordination
  scan background, automatic, part of the card system; AND extend it in analysis windows to
  find related articles, branch into new corpuses, do associated research"; BUILT on branch
  `claude/analysis-related-coordination`, draft PR onto 0.09, BROWSER-UNVERIFIED):** HONEST
  FINDING recorded — coordination is ALREADY a background, automatic Lead (the `echo_chamber`
  producer runs `corpus_actors`, gated ≥3 sources, carries the exact `article_ids`, and
  `run_all`→`refresh_briefing` is called automatically AFTER EVERY scrape pass at
  src/scheduler/runner.py:681); the thing that FELT manual is the redundant "Source integrity"
  tab (loadActors → /api/integrity/actors). So this slice makes coordination AMBIENT IN THE
  ANALYSIS WINDOW (not a button) + adds the BRANCH workflow: (1) NEW `queries.corpus_coordination`
  (article_ids set → `near_duplicate_clusters` MinHash+LSH high-precision; independence = DISTINCT
  SOURCES, single-source repeat flagged `single_source` not co-publication; counts only, NO score;
  non-collusion + absence-is-not-absence caveat travels) + GET `/api/insights/corpus-coordination`
  (reuses `_resolve_corpus`, cap 400 since it reads full text); (2) a new lazy **Related** analysis
  subtab (`data-tab="related"` / `#an-related`) rendering each cluster as the ruled "N near-identical
  copies across M sources = effectively one voice · Show all" with a VISIBLE `.card-caveat`, and a
  per-cluster **"Branch into a new corpus →"** that calls `openAnalysisForIds(cluster.article_ids)`
  = the exact-set spawn = a fresh corpus = associated research. +11 i18n ×12 (non-en AI-drafted,
  flagged); tests/test_corpus_coordination.py (clusters-across-sources, single-source-flagged,
  empty-honest, + frontend wiring) + py_compile + node --check; full pytest needs py3.13 (CI).
  REMAINING (PR 2): broaden "Related" beyond near-dup to SHARED-ORIGIN links
  (/api/links/articles-by-link) + shared-keyword neighbours with multi-select branch; the inline
  "1 voice" annotation in the reader + the Articles list; DISSOLVE the manual Source-integrity tab
  once the card + inline fully absorb it (absorption-test-gated, the Desk lesson — not yet).
  **PR 2 — SHARED-ORIGIN LENS SHIPPED 2026-06-17 (branch `claude/related-shared-origins`, draft
  PR onto 0.09, BROWSER-UNVERIFIED, frontend-only):** the Related subtab now renders a SECOND
  lens beneath the near-dup clusters — "Shared origins": the outbound pages cited by 2+ articles
  in the corpus (reuses the EXISTING /api/links/corpus; no new backend), each with the
  anti-false-triangulation caveat ("several articles citing the same page are not independent
  confirmation — one origin, several echoes") VISIBLE, and a "Branch into a new corpus →" that
  calls `branchFromOrigin` → /api/links/articles-by-link?url= → `openAnalysisForIds` over every
  citing article (the "sources' sources" trail). renderAnRelated restructured to render BOTH
  sections (Promise.all; no early-return on empty clusters), near-dup section + its #299 strings
  PRESERVED (test_corpus_coordination stays green). +8 i18n ×12 (non-en AI-drafted, flagged);
  tests/test_related_shared_origins.py + node --check green; full pytest needs py3.13 (CI).
  **PR 3 — INLINE "1 VOICE" BADGE SHIPPED 2026-06-17 (branch `claude/inline-dup-badges`, draft
  PR onto 0.09, BROWSER-UNVERIFIED, frontend-only):** the analysis Articles subtab now badges
  near-identical rows — a reusable `annotateArticleDups(params, host)` helper (NON-BLOCKING: the
  list renders first, badges appear when coordination returns; best-effort try/catch; idempotent
  via `a.dataset.dupBadged`) marks each clustered row with a `≈N` pill (titled, so it inherits the
  #oo-tip hover, invariant #17) + a `.card-caveat` summary "{n} of these are near-identical copies
  — fewer independent voices than the count suggests (see Related)". REUSES the corpus-coordination
  data — and the Related subtab's `_anRelatedClusters` cache when present, so the common path adds
  NO extra fetch. No score (the count is the cluster size only). +2 i18n ×12; node --check +
  tests/test_inline_dup_badges.py green. The helper is reusable across any host whose article links
  are /api/articles/{id}/view. STILL REMAINING (PR 4): apply the same helper to the SEARCH-results
  list + the standalone READER (different render paths — search is the SPA results table, the reader
  is a server-rendered English-only page); shared-KEYWORD neighbours; multi-select branch; DISSOLVE
  the manual Source-integrity tab (absorption-test-gated).
  **PR 3/4a/4b/5 ALL SHIPPED 2026-06-17 (merged #311 inline-badges, #313 reader, #315 multi-select;
  PR 5 on branch claude/dissolve-integrity-tab):** (3) inline ≈N "1 voice" badges on the analysis
  Articles + search-results lists (annotateArticleDups). (4a) the READER gained the near-dup badge
  AND became UI-LANGUAGE-DEPENDENT — i18n.js is now included in the reader head, so it reads the
  SPA's localStorage("oo.lang") and auto-translates the whole reader (the ≈N pill is a number, the
  caption keyed). (4b) MULTI-SELECT branch in Related (checkbox per cluster/origin → union → one
  corpus); "shared-keyword neighbours" judged ALREADY-SERVED by the Keywords-subtab branch chips,
  not duplicated. (5) the manual Source-integrity tab is DISSOLVED FROM THE SIDEBAR + reachable from
  Settings → Safety (showTab('integrity')); DESK-LESSON SAFE — the page + ALL its tools
  (collapse-to-one-voice, source profile, web-of-trust annotations) preserved, nothing lost.
  REMAINING (deeper, own PRs): web-of-trust ambient on source chips + collapse folded into Related
  (then the page retires); the Evidence & custody tab dissolution; the models-in-backup build.
- **Offline LLM kit** (RM-08 release artifact); DuckDuckGo discovery channel
  only after RM-03 gate UX proves out. **Translated docs:** infrastructure
  shipped (per-language docs served with honest machine-drafted banner; fr
  QUICKSTART hand-seeded); TODO: run scripts/translate_docs.py on a machine
  with a local model.
- **OFFICIAL-STATISTICS INGESTION (maintainer concept 2026-06-12, designed
  in FUTURE_DEVELOPMENTS with questions):** worldwide government +
  international statistical agencies (BLS/INSEE/Eurostat/World Bank/IMF +
  deliberately BRICS/Africa/forgotten-regions producers) ingested as
  CONTROVERSIAL sources like any other — producing state + agency +
  publication date + methodology ref on every figure; VINTAGES stored
  (revisions are evidence, the law/wiki versioning model); comparability
  guards (SA/NSA, definitions, base years — never compare incomparable
  denominators silently); official machine endpoints (SDMX/APIs) before
  scraping; triangulation side-by-side never averaged; agency FORECASTS
  join the IPCC prediction-tracking lens; coverage measured per continent.
- **OPEN-METEO WEATHER-CONTEXT LAYER (maintainer concept 2026-06-12,
  designed in FUTURE_DEVELOPMENTS; honest amendment recorded: NOT the
  entire dataset — the CORPUS drives bounded (place,window) reanalysis
  slices via the T12 substrate; corroborates, never confirms; anomalies vs
  stated baselines; signal-keywords from explicit threshold rules with
  (date,place) anchors by construction, kind="signal", never silently mixed
  with text keywords; reader weather-context row + Home co-occurrence
  producer; opt-in, consented, visible jobs).** **SLICE 1 SHIPPED
  (2026-06-12, maintainer-asked "if this then suggest user to fetch"):**
  suggest-to-fetch corroboration cards — curated 12-language climate-event
  vocabulary (configs/corroboration_rules.yml, provenance in-file) ×
  T12 places × article dates, scanned LOCALLY (src/analytics/corroboration);
  ≥3-article clusters emit an *investigate* card stating "this card made no
  network call"; the fetch is the card's button → consent popup → ONE
  bounded slice via POST /api/weather/context through make_fetcher (kill
  switch/robots/proxy inherited), T4 verdicts on failure, disk cache
  disclosed, CC BY 4.0 attribution + reanalysis-not-station-truth shown,
  one chart per variable (never mixed units on one axis). +7 strings ×12.
  REMAINING: anomaly baselines, signal-keywords, reader row, temporal-map
  overlay (the designed layer).
- **OPEN COMMONS MIRROR — SISTER PROJECT (maintainer vision 2026-06-12,
  recorded in FUTURE_DEVELOPMENTS with the full design + 6 questions; NOT
  committed work):** server-scale preservation of PUBLIC open data,
  archive.org-scale ambition, separate project branched from this one;
  web UI + this local-first app over the same corpus; business plan /
  fund-raising acceptable if permanence requires it (nonprofit/grant
  models recorded as aligned; VC recorded as misaligned). **THE
  RELIABLE-MEMORY PILLAR (maintainer, same day — the project's stated
  deepest intention):** digital data is editable by nature; History
  (capital H) must not be silently rewritten — "history is written by
  those who win wars" must stop being true; the local/offline design was
  always the untold half (a copy outside anyone's reach, able to confront
  the web). Formalized math-first: tamper-EVIDENT (content addressing,
  signed manifests, RFC-6962-style transparency logs with inclusion +
  consistency proofs), tamper-RESISTANT (LOCKSS-style independent
  replication, witness cosigning, multi-jurisdiction), existence-before-T
  anchoring, fixity audits vs bit rot, VINTAGES never overwrites. HONEST
  REFRAME RECORDED: not "the one and only source" (a single authority =
  single point of capture — the app's own anti-single-origin ethics) but
  the most VERIFIABLE mirror in a clonable federation; provenance ≠
  veracity, stated forever. User corpora NEVER touch the mirror
  (hosting-stance clarification under Non-negotiables). **NODE 0 +
  SEQUENCING (maintainer, same day):** the maintainer's own computer is
  the first server (cheap, web-accessible, AIR-GAPPED future-proof
  backups — the strongest tamper-resistance layer); the project is a NEW
  REPO / FORK of this one, created ONLY when the current project is
  MATURE (maintainer's gate — V0.1+ first); home-hosting implications
  recorded honestly (residential-line realities, exposure → quiet-origin
  + public-mirrors split, offline signing keys, the fork inherits the
  ethics constitution); node-0 questions filed (#7 in the section).
  **BLOCKCHAIN (maintainer's INITIAL INTENTION, recorded 2026-06-12):**
  tamper-proof reliability via blockchain was the original concept; honest
  read recorded in the section — the design's math IS blockchain-class
  (hash-chained Merkle logs; CT ≈ "a blockchain without the token");
  preferred use is ANCHORING log roots into existing public chains
  (OpenTimestamps-style existence-before-T, no tokens/validators) over
  running a dedicated chain (permissioned BFT ≈ witness cosigning; PoW/PoS
  at our scale buy nothing); public claim stays "detectable + practically
  infeasible to hide", NEVER "tamper-proof" (no fabricated security);
  chain-choice + cadence question filed (#8 in the section).
- **Parked (designed-only):** event-family merge/split UI (#53), saved-filter
  "smart calendars" (#50), offline vector map, two-hop keyword graphs (#43),
  autonomous onboarding track (#49), **voice-only mode (maintainer input
  2026-06-12: accessibility-first, all GUI ethics carried over, no
  meta-information saturation — memory + one-word "help"; local STT/TTS via
  the Ollama path; mic = a consent surface; hardware tiers MEASURED never
  asserted; full map in FUTURE_DEVELOPMENTS)**. All in FUTURE_DEVELOPMENTS.
- **PROPOSED SEQUENCE (standing, maintainer may veto):** ~~performance batch~~
  (T1 shipped) → network toggle+consent → task manager+download arbitration →
  reader tabs + corpora system → agenda content batch → continuous-collection
  ordering+onboarding → convergence flagship.

## Shipped batch log (compressed verdicts; details in git history + named docs)
- **PERF — FRAMING 141s (field perf report 2026-06-18; branch claude/perf-framing, draft PR onto 0.09):**
  /api/framing was the slowest endpoint — it ran VADER over the FULL text of up to 1000 articles AND
  concatenated all of each source's content for term-frequency, and the corpus includes long Wikipedia
  pages, so the pure-Python VADER + concat + term-freq dominated; plus an N+1 lazy load on `a.source` (one
  extra decrypt-query PER article). FIX (two safe levers): (1) `joinedload(Article.source)` kills the N+1;
  (2) bound the text fed to the COARSE framing computation (`_FRAMING_MAX_CHARS=8000`) — framing is a
  signal-not-a-verdict (its own caveat), an article's LEAD carries its tone + emphasis, and typical news
  articles are well under 8000 chars so their result is UNCHANGED while a pathological long page no longer
  dominates. The content-column decrypt is inherent (SQLCipher decrypts whole pages); this bounds the hot
  PYTHON work. tests/test_framing_perf.py pins the content bound (a 20k-char article is truncated to the
  cap). REMAINING perf workstream: denormalized counters; cache the per-query analysis endpoints
  (framing/associations/graph keyed by args, for instant re-opens); Home poll frequency; graph/associations
  cold cost (same long-content/large-corpus shape — candidates for the same bounding + the cache).
- **DIAGNOSTICS — STOPWORD-CANDIDATE DIGEST (maintainer 2026-06-18 "full authority on the logging process,
  you're the one analyzing them"; branch claude/diag-stopword-candidates, draft PR onto 0.09):** the
  recursive-improvement loop is "grow the not-a-keyword (stopword) list", and the keyword log was a 24 MB dump
  of the top-5000/language keywords — the wrong shape. INSIGHT: a function word is SHORT, FREQUENT and
  UBIQUITOUS (spread across many distinct articles), so it sits at the TOP by frequency (well within the
  per-language survivor set the export already builds) — the 5000 cap NEVER hides it; the tail is rare/novel
  terms, not stopwords. So instead of dumping everything, the log now carries a COMPACT per-language
  `stopword_candidates` digest computed FROM the survivors (ZERO extra DB cost): per dominant-signature
  language, the short (<=14ch) single-token TERMS with >=5 distinct-article spread NOT yet stoplisted,
  ranked by article spread, with each language's status (functional/no_stoplist/unsegmented from
  src.analytics.managed) and `priority_languages` = the no_stoplist/unsegmented buckets first (the worklist).
  No score; "candidates to REVIEW before adding". Added to BOTH the streamed JSON log + the zip summary.json
  (additive — the envelope test asserts keys-present not keys-exclusive, so byte-additive is safe). Closes the
  loop directly: I read stopword_candidates.by_language, propose the per-language stoplist additions (feeds the
  existing _EXTRA_STOPWORD_TEXT batches), which then turns no_stoplist langs into managed ones → re-enable
  their sources (#366). tests/test_stopword_candidates.py (shape + every exclusion filter + the no_stoplist
  priority ordering + article-spread ranking). REMAINING perf workstream: denormalized counters; cache
  associations/graph/framing; Home poll frequency.
- **PERF — IDLE BROWSER-CPU 40% (field report 2026-06-18 "despite airplane mode my CPU takes 40%,
  gnome-www-browser"; branch claude/perf-idle-cpu, draft PR onto 0.09):** ROOT CAUSE — `#net-toggle.off`
  ran `animation: netpulse 2.2s infinite` animating a BOX-SHADOW forever. Airplane mode is the idle/default
  state, so the button pulsed at rest, and an animated box-shadow forces a full repaint every frame (a known
  WebKit/GNOME-Web hog on a 2-core software-rendered VM) → ~40% CPU AT REST with nothing happening. FIX:
  replaced the perpetual pulse with a STATIC red ring (painted once) + the existing red colour/border; the
  plane glyph FILL + colour already convey the state (invariant #14), so nothing is lost. Removed the now-unused
  @keyframes netpulse. (The global prefers-reduced-motion guard already killed it for THOSE users; this fixes
  it for everyone.) test_repo_invariants::test_airplane_button_has_no_perpetual_animation guards it. REMAINING
  perf workstream: denormalized keyword counters; cache associations/graph/framing; cut the Home poll
  frequency; optional SQLite cache_size knob (per-connection × the 8+64 pool = OOM risk, so env-gated only).
- **PERF — INSIGHTS READ CACHE + BACKGROUND WARM (perf workstream, field report 2026-06-18; branch
  claude/perf-insights-cache, draft PR onto 0.09):** the whole-corpus read endpoints (top 2.7s, trending,
  trending-windows 8-36s POLLED 132x from Home, map-coverage 7-9s) GROUP BY over the full 829k-mention table
  EVERY call and recompute identical numbers. Added a short TTL cache (src/api/insights.py: SimpleCache,
  `_cached`/`_ckey`, default 120s, OO_INSIGHTS_CACHE_TTL, 0 disables) on those 4 endpoints — keyed by their
  params, HONEST (computed_at + cache_ttl_s + a `cached` flag in the payload, like the database-stats cache).
  DELIBERATELY a plain TTL, NOT a write-invalidated probe: under continuous scraping a write-invalidated cache
  is cold every pass (exactly when the operator looks), so a small DISCLOSED staleness buys a permanently-snappy
  UI. `warm_cache(session)` pre-computes the DEFAULT views the UI requests (Home trending-windows series_top=5/0,
  top group=True) and is called best-effort AFTER each scrape's refresh_briefing (same background thread, off the
  request path) — so even the first open rarely hits a cold query; warming SKIPS keys still fresh within the TTL
  (cheap when passes outrun the TTL). tests/test_insights_cache.py (memoize, distinct-params-distinct-entries,
  warm populates the exact Home key + a 2nd warm recomputes nothing). REMAINING in the perf workstream:
  denormalized keyword counters (mention_count/article_count on Keyword → indexed top/supergroups, no mention
  join); cache associations/graph/framing (per-query, heavier); cut the frontend Home poll frequency (the cache
  already makes each poll a cheap hit); SQLite cache_size bump; the browser idle-CPU 40% runaway.
- **STATS DISPLAY CLEANUP + DATA-MODEL ASSESSMENT (maintainer 2026-06-18; branch claude/stats-cleanup,
  draft PR onto 0.09):** removed three counters from the Database/Home stats (database._COUNTED_TABLES +
  the frontend HOME_STAT_LABELS, both render dynamically): `article_analyses` ("pointless" — LLM
  summaries/translations are an internal artifact, not a corpus metric), `external_sources` ("unjustified"
  — every source is external by definition; the table is empty/never-wired), `source_groups` (0 rows;
  source GROUPS duplicate source TAGS — the mechanism the app actually uses for filtering + the stratified
  scrape order). ASSESSMENTS RECORDED for follow-up (maintainer brainstorm): (a) DEPRECATE source-groups in
  favour of tags — the SourceGroup model + source_group_association M2M + source_manager CRUD + the
  is_tag_based flag are redundant with Source.tags; a later PR can retire the groups API/UI (keep tags). (b)
  The AUTO-SCRAPE-CITED-ORIGINS idea ("when >X articles share the same external source, auto-scrape it")
  ALREADY half-exists as the discovery citation_channel (src/discovery/channels.py: domains cited by ≥3
  distinct stored articles become CANDIDATES, with a commerce filter) — but it creates DISABLED candidates
  for operator review (RM-03 "nothing happens without you"), NOT auto-scraped sources. Making it automatic
  is a genuine ethics ruling (auto-enabling scraping vs the review gate); recommended design: auto-PROMOTE
  above a higher configurable threshold X, ENABLED only if it passes the gates (not commerce/social, robots
  ok; language unknown pre-scrape so #366 can't gate it until first fetch), else stays a candidate.
- **BACKUP FIX — stage on disk, not tmpfs (field report 2026-06-18 "Backup failed: [Errno 28] No space
  left on device" with dozens of GB free disk + an earlier "the operation was aborted"; branch
  claude/fix-backup-tmpfs, draft PR onto 0.09):** ROOT CAUSE — backup_v2 created its temp file via
  `tempfile.mkstemp()` (default /tmp) and `write_backup_v2` builds in `dest.parent`, so the WHOLE build
  (a ~460 MB corpus snapshot + the ~460 MB zip + the final artifact) landed in /tmp, which on Fedora/Qubes
  is tmpfs (RAM-backed). On a 5.6 GB box already at 3 GB RSS, the tmpfs ran out → Errno 28 (and earlier, an
  OOM-style connection drop the WebKit browser reported as "the operation was aborted"). Both errors are the
  same cause — NOT the real disk (which had room beside the 460 MB corpus). FIX: a `_staging_dir()` helper
  returns data_dir() (real disk beside the corpus, created on demand) and is passed as `dir=` to all three
  create-path mkstemps (backup, models export, models import); restore already staged in data_dir via
  read_artifact. tests/test_backup_staging.py (the helper returns+creates the data dir; a regression guard
  that EVERY mkstemp passes dir=_staging_dir() so no create path can silently fall back to /tmp again).
  REMAINING (recommended next, not in this fix): a long backup still blocks the request synchronously while
  building — make it a task-manager JOB (build → then download) so the browser never times out on a
  multi-GB corpus; surface free-disk preflight before a big export.
- **SOURCE-LANGUAGE GATING — unmanaged languages disabled by default (maintainer 2026-06-18 "the app
  scrapes material in languages we cannot manage … flag those sources as disabled by default while keeping
  them, justified in the documentation"; branch claude/source-language-gating, draft PR onto 0.09):** ONE
  source of truth `src/analytics/managed.py` (MANAGED_LANGUAGES = the 18 functional-stoplist langs en/fr/de/
  es/it/pt/nl/ru/ar/hu/id/sv/da/nb/no/pl/sr/sl; UNSEGMENTED zh/ja; is_managed/is_unmanaged/language_status/
  normalize_lang — engine_report now imports it, no dup). The keyword engine can only analyse managed langs;
  no_stoplist langs (tr/el/uk/th/ur/bg/ca/fi/cs/hi…) leak function-word junk + zh/ja are unsegmented = broken
  extraction → that junk pollutes analytics AND inflates the corpus (the perf drag). FIX: (1) the SEEDER
  (csv_io.upsert_sources) seeds a NEW source in an unmanaged language DISABLED by default — KEPT, never
  deleted, re-enablable; explicit `enabled` in the row wins (curation), unknown-language stays enabled (never
  disable what we can't classify), existing sources untouched (re-seed never flips the operator's choice);
  (2) GET /api/sources/unmanaged-languages (count + per-lang breakdown of enabled unmanaged sources) + POST
  /api/sources/disable-unmanaged-languages (bulk disable, kept, reversible, idempotent); (3) Settings →
  Sources panel (appears only when there's something to disable) showing the count + a "Disable sources in
  languages we can't analyse yet" button; (4) USER_MANUAL §3.3 justifies it (honest trade-off: don't gather
  what we'd mangle; re-enable when a stoplist lands). tests/test_managed_languages.py (classification + the
  engine_report shares-the-set + seeder gating incl. explicit-override + re-seed-doesn't-flip + the two
  endpoints incl. kept-not-deleted + idempotent). node --check + i18n 100%; managed logic verified here.
  REMAINING (the user's OTHER ask, next): keyword diagnostics chunk-by-chunk over the WHOLE dataset to grow
  the stoplists (so no_stoplist langs become managed → re-enable their sources); the perf roadmap counters/cache.
- **PERF — SUPERGROUPS 132s→fast (field perf report 2026-06-18, draft PR onto 0.09):** the maintainer
  clicked Insights → Groups on a 10,252-article / 244,866-keyword / 829,226-mention corpus (408 MB
  encrypted, 2 cores, 5.6 GB RAM); /api/insights/supergroups took 132 s and FROZE the UI (clicks queued,
  airplane toggle unresponsive — the single GIL-bound server was busy). ROOT CAUSE: `_supergroup_totals`
  GROUP BY'd EVERY keyword joined to EVERY mention (829k rows) then discarded 99.99% to keep the 8
  super-groups' members. FIX (behaviour-identical): resolve member keyword IDs FIRST (indexed IN on the
  exact ring/member terms; a small (id, term)-only scan ONLY when a family member needs canonical-key
  morphology matching — never when all members are rings), then aggregate mentions for ONLY those IDs.
  Turns a whole-corpus aggregation into a handful-of-keywords one. tests/test_supergroups.py gains
  test_supergroup_totals_count_only_members (a high-mention NON-member must not leak); existing
  test_super_rings cross-language aggregation preserved. This is ONE fix in a larger perf workstream the
  maintainer opened — REMAINING (diagnosed from the logs, not yet built): /api/insights/{graph 103s,
  framing 141s, associations 76s, trending(-windows) 8-36s ×132 polls, map 7-9s, top 2.7s} all recompute
  whole-corpus aggregations per call with NO cache → need (a) denormalized mention_count/article_count on
  Keyword maintained at index time (kills the mention join for top/trending/supergroups), (b) a background-
  warmed TTL cache (stale-while-revalidate) so the UI is instant, (c) polling-storm cut (activity+vitals
  6741 reqs each), (d) frontend idle-CPU runaway (browser 40% CPU at rest), (e) keyword-quality lever:
  18+ languages are no_stoplist (tr/el/uk/th/ur/bg/ca/fi/cs…) + zh unsegmented + 5,094 unknown-language →
  junk inflating the 245k/829k counts that every aggregation pays for.
- **TASK-MANAGER REDESIGN — WINDOWS-STYLE (maintainer 2026-06-18 "entirely rethink the task manager
  UI … anchored in what Windows created: see what consumes resources, see what is actually happening
  (is an LLM translating? are super-groups loading?), pause services, performance + hardware metrics +
  the jobs list with prioritise"; branch claude/taskmgr-windows-redesign, draft PR onto 0.09,
  BROWSER-UNVERIFIED):** the standalone /tasks page (src/static/taskmanager.html) rebuilt into a
  Windows-Task-Manager-style window: a PERSISTENT resource SUMMARY strip (state chip — Online·collecting /
  Airplane mode [red] / Idle, honest from activity.online — + live CPU/RAM/↓/active-jobs) above five tabs:
  PROCESSES (one grouped live list of EVERYTHING — Collection [pass+phase] · Downloads [wiki/OSM, with
  pause/reorder/resume] · AI & analysis · Network [the fetch] — replaces "Active") · PERFORMANCE (live
  hardware sparkline charts from a rolling buffer: CPU%, Memory RSS, Network ↓ [diffed], Disk I/O [diffed],
  + cores/threads; replaces the flat "System" rows) · QUEUE (the reorderable download queue + the read-only
  up-next preview) · SCHEDULE (scheduler facts, now AIRPLANE-AWARE — fixes the reported bug where it showed
  "running — collection in progress" while in airplane mode; offline → "paused — airplane mode" in red) ·
  HISTORY (recent completed passes from a new GET /api/jobs/history → runlog.recent_runs, honest ok/error
  verdicts). The "what is actually happening" gap is closed by a NEW live background-task registry
  src/monitoring/tasks.py (register/update/finish/track context-mgr/snapshot; stale-prune; pure stdlib, no
  shadow state, no fabricated %), surfaced in /api/jobs via _task_jobs (kind llm/analytics, read-only), and
  wired into the LLM endpoints (bulk summarize/translate per-article progress; single summarize/translate)
  + the AI keyword-extract stream — so "Translating → French · 3/12" now shows. +10 i18n structural keys ×12
  (tabs/state chips/groups; the rest English-fallback keyable later; gate 100%). tests: test_background_tasks.py
  (registry incl. track-always-finishes + stale-prune + the /api/jobs surface + history shape) +
  test_repo_invariants::test_task_manager_redesign_windows_style; node --check clean; registry logic verified
  here (stdlib). REMAINING: the BIG one — Insights "Groups" took ~60 s and froze the UI on a 10k-article /
  245k-keyword / 829k-mention corpus (separate perf workstream the maintainer opened with logs); per-job ↓
  rate; History filters; wiring more producers (indexing/supergroup loads) into the registry.
- **TIME-TO-FIRST-ARTICLE + TASK-MANAGER PHASE (maintainer field test 2026-06-18 — "it took
  3-5 minutes to get the first article … the app's downloading markets/indices/calendars
  beforehand … the task manager fails to show what the app is doing"; branch
  claude/friendly-lamport-s3a1qa, draft PR #359 onto 0.09, backend VERIFIED-by-reading, full
  pytest in CI):** ROOT CAUSE (confirmed in code + by the maintainer's "Collecting… fred.stlouisfed.org/
  graph/fredgraph.csv…" observation): `_default_run_once` ran the FIRST-RUN source preflight +
  feed_preflight (robots + SAMPLE-fetch of every market/calendar feed — `fredgraph.csv?id=SP500` is
  the first sampled index) + the per-pass calendar auto-import + field-test instrumentation
  SYNCHRONOUSLY BEFORE `run_scrape_once`; each slow over Tor (30 s timeout each), so the operator
  watched the chip sit on FRED for minutes before any RSS article landed. Default mode is "rss" — FRED
  is NOT even part of article collection; it was preflight/instrumentation. FIX (src/scheduler/runner.py):
  REORDER so `run_scrape_once` runs FIRST (articles flow in seconds); preflight/feed-preflight/calendar-
  import/field-test/discovery/briefing all moved AFTER it as best-effort housekeeping (each already
  docstring'd "never blocks the scrape"). SAFE: EthicalFetcher enforces robots.txt + per-host Crawl-delay
  LIVE per fetch (src/ingest/__init__.py), independent of the preflight-written SourceMetadata, so
  collecting before the preflight LOG is written does NOT reduce politeness (preflight is instrumentation,
  not a gate). VISIBILITY: new coarse pass PHASE (`_phase_set`/`current_phase`, module-global independent
  of the per-source `_PROGRESS` that run_scrape_once clears) surfaced in scheduler `status()` and the
  task-manager collect job label — "collection pass — collecting articles" vs "— background tasks (markets ·
  calendars · checks)" vs "— building the briefing" — so a lingering market fetch reads as "finishing", not a
  stall (the task manager's whole point). tests/test_collect_first_ordering.py (scrape-before-preflight,
  phase transitions, phase-aware label). FRONTEND FOLLOW-UP SHIPPED 2026-06-18 (branch
  claude/taskmgr-phase-upnext, draft PR onto 0.09, browser-unverified): the standalone /tasks page
  (src/static/taskmanager.html, its OWN renderSystem/renderJobs) AND the in-app app.js
  (_renderVitals/_renderJobs) now (a) show the honest PHASE when a pass is ACTIVE but past the
  per-source scrape (progress cleared) instead of a bare "idle" — reads `a.phase` from
  /api/scheduler/activity, gated on `a.active`; (b) show a read-only "Up next this pass" preview of
  the COLLECTION order in the Queue tab (reuses the plan the activity poll ALREADY fetched — no new
  endpoint/poll) with the honest "order is re-randomised every pass — stratified by language & tag,
  not a fixed queue" caveat (closing the user's "the queue is empty" confusion: the collection order
  is NOT the reorderable download queue). +5 i18n keys ×12 (AI-drafted non-en, flagged for native
  review; gate stays 100%); test_repo_invariants::test_task_manager_shows_pass_phase_and_upcoming_sources.
  REMAINING: optionally run the first-run preflight in a background thread (the reorder already gives
  articles-in-seconds).
- **INSTALL-SIZE ESTIMATES (maintainer-asked 2026-06-18 from an install log, branch
  claude/friendly-lamport-s3a1qa, draft PR onto 0.09):** install.sh now informs the user
  of ROUGH download sizes before the long pip step + in the component menus. Dated
  `SIZES_AS_OF="2026-06"` + `component_mb`/`human_mb`/`extras_total_mb`/`print_download_estimate`
  helpers; per-component MB measured from the real py3.13 download log (core ~55 MB · analysis
  ~90 MB · compression ~7 MB · llm extra ~1 MB; total core+analysis+compression ~152 MB).
  HONEST: "rough, measured {date}, varies by OS/arch, cached wheels won't re-download". Menu
  labels (whiptail + plain ask_yn) carry the size; the estimate prints before the download in
  pip_install. Ollama surfaced separately per the maintainer ("ollama ~1 GB"): the LLM menu
  item + install prompt + estimate footnote state Ollama ~1 GB + a model ~0.8–2.7 GB (model
  sizes already in the whiptail model menu). tests/test_installer.py::test_install_shows_download_size_estimate.
  REMAINING: numbers are advisory — refresh when the dependency set changes materially.
- **UNINSTALL MODES + BACKUP-FIRST + CLEAN SHUTDOWN + AUDIT LOG (maintainer-asked
  2026-06-17 after a field uninstall log showed sqlcipher teardown noise + confusion
  that "it didn't uninstall"; draft PR onto 0.09, browser-unverified UI):** REASSURANCE
  FIRST — the design was already system-safe: every Python dep installs into an ISOLATED
  `.venv` (install.sh), so uninstall = delete that one dir + launchers; it touches NO
  system/global packages (the only system packages are the explicit Qubes `--template`
  step, deliberately left alone). The folder remaining + the sqlcipher ERROR lines were
  by-design / benign teardown noise, not a failed uninstall. FOUR fixes shipped:
  (1) CLEAN SHUTDOWN — `request_uninstall` now disposes the DB engine
  (`_close_db_quietly`) BEFORE the SIGTERM-to-self, so the encrypted store doesn't emit
  codec-teardown noise during a normal uninstall; (2) AUDIT LOG — the detached watcher
  records what it removed + failures to `~/.open-omniscience-uninstall.log` (HOME, so it
  survives a full/secure removal); (3) MODES (maintainer-ruled "data dies only in
  Secure", AskUserQuestion): `minimal` (venv+launchers, keep folder+data — the historical
  default) · `full` (+ app folder, data KEPT) · `secure` (+ wipe data&keys, best-effort
  overwrite + HONEST limit reusing panic.py's SSD/CoW caveat — never a fabricated
  guarantee) · `custom` (checkboxes: app folder / data, each OFF by default). venv +
  launchers always removed; the watcher computes NO paths (plan_uninstall passes explicit
  absolute paths + flags in-process — the detached process can only remove what was
  decided); watcher chdir's to ~ before any rmtree. (4) BACKUP-FIRST (maintainer-asked) —
  a "Download a backup first" button (reuses POST /api/safety/backup/encrypted) + the
  data-wiping modes ASK "back up first?" and, if yes, download the .ooenc then abort so
  the user saves it and re-clicks (never run the uninstall while a backup is still
  streaming from the server we're about to kill). Backend: `UninstallBody`
  {confirm,mode,remove_folder,wipe_data} + `_uninstall_flags` (data only in
  secure/custom-opt-in) + GET `/api/safety/uninstall/plan` (no-op preview for informed
  consent — the UI shows the EXACT paths before confirming). Frontend: Settings → Safety
  mode `<select>` + Customize checkboxes + live preview + double type-confirm (WIPE for
  data modes, UNINSTALL otherwise); +8 label keys ×12 (AI-drafted, flagged; dynamic
  preview/confirm stay English, consistent with the existing English-in-JS panic/uninstall
  dialogs). tests/test_uninstall.py extended: mode flags, the REAL-filesystem watcher
  (removes exactly the planned venv/launchers/data/folder + writes the audit log, on a
  sandbox tree with a dead PID), the plan-preview endpoint + unknown-mode 400, and
  `_close_db_quietly` disposes the engine. Full suite green; mypy 116≤127; i18n 100%×12;
  node --check clean. REMAINING (honest): a future opt-in "leave no uninstall log" for the
  Secure threat model (today the log path is DISCLOSED in the UI so the user can delete
  it); the dynamic preview/confirm strings are English-only.
- **BANDWIDTH-GOVERNED COLLECTOR (maintainer ruling 2026-06-16, SHIPPED on
  claude/vibrant-hypatia-1g6e96):** the user-facing collection control is now a
  DOWNLOAD-RATE target (kbps = kilobits/s, the consumer unit), NOT a raw task count —
  "more intuitive". A `BandwidthGovernor` (src/scheduler/bandwidth.py) varies how many
  sources are fetched at once (an adjustable-permit semaphore + damped AIMD) to track
  the target, with IMMEDIATE contention back-off when CPU / memory / the single
  encrypted writer become the limit. **RULING — the default now targets ≥500 kbps out
  of the box (seed ~25 workers, hard ceiling 50), SUPERSEDING the old "collect_parallelism
  default 1, opt-in".** Source-respect is INVARIANT (the per-host lock + per-host interval
  are untouched; concurrency only ever fans out across DIFFERENT hosts — proven by
  test_parallel_collect_guardrails). New settings: `collect_rate_mode` (target|maximum),
  `collect_target_kbps` (default 500), `collect_parallelism` REPURPOSED as the hard
  ceiling (default 50, cap 16→50). UI: Settings → Collect gains a rate slider with a
  "Maximum" end-stop + a live "Now: X kbps" readout + a VISIBLE "target not a guarantee"
  caveat (invariant #23) and the per-host-politeness guarantee in the #oo-tip hover; +6
  i18n ×12 (AI-drafted, flagged for native review). NEW BOTTLENECK-FINDING LOG
  (maintainer-asked): src/monitoring/collect_perf.py samples rate/in-flight/writer-gate/
  CPU/memory every ~1.5 s to data/collect_perf.jsonl (bounded, local-only, in the debug
  bundle) + an end-of-pass TRANSPARENT bottleneck classifier (memory|writer|cpu|network-
  or-source|target-met, raw numbers beside the label, no composite score). ActivityMonitor
  reworked to token-keyed in-flight tracking (fixes per-host rate attribution under
  parallelism; adds download_rate_kbps + inflight_count). Connection pools sized to the
  ceiling: the EthicalFetcher's requests.Session HTTPAdapter (OO_HTTP_POOL) + the SQLite
  engine max_overflow (OO_DB_MAX_OVERFLOW) so ramping isn't theater; the governor's memory
  back-off keeps the count actually open in check. Parallel path engages ONLY when the
  caller's session is the gated GLOBAL engine (a custom/in-memory session runs sequentially
  — fixes the cross-engine worker-session hazard). Tests: test_bandwidth_governor.py,
  test_collect_perf_monitor.py, extended test_parallel_collect.py + test_ui_invariants
  (#collection-speed). Full suite green; mypy 112≤127; i18n 100% ×12; node --check clean.
  REMAINING (recommend with evidence from the new log, not built here): batched per-source
  writes if writer-bound; a ProcessPool parse stage if CPU-bound.
- **AUTONOMOUS AUDIT 2026-06-15/16 — PR H = MONOLITH DECOMPOSITION (draft onto 0.09;
  behaviorally INERT — pure extraction; RE-CUT FRESH on current 0.09 2026-06-16, the
  maintainer's choice over resolving the stale ~8k-line conflict, so NO recent
  index.html feature is lost):** (1) FRONTEND: the ONE inline `<style>` + ONE inline
  `<script>` were programmatically extracted from index.html into cached
  `/static/app.css` (691 lines) + `/static/app.js` (7302 lines) — index.html
  9677→1682 lines. The extraction is REVERSAL-VERIFIED (re-inlining reproduces the
  original byte-for-byte = inert by construction). app.js is a CLASSIC external script
  at the same end-of-body position AFTER /static/i18n.js, so globals + inline on*=
  handlers + load order are preserved (the 295-handler→addEventListener + CSP work is
  NOT done — needs a headless browser; OO-D12-001 stays deferred). main.py now registers
  `text/javascript`/`text/css` explicitly so the assets serve correctly on EVERY
  platform (Windows' registry could map .js→text/jscript). tests/test_static_assets.py
  asserts both serve (200 + right content-type + content-identical to disk,
  newline-normalised for CRLF checkouts). The test-sites that grepped index.html for
  JS/CSS read a `_ui_source()` concat (index.html+app.js+app.css) — a MOVE not a loss;
  node --check on app.js clean. (2) BACKEND: the ~37 `app.include_router` calls + imports
  + the optional-[analysis] conditional moved from main.py into
  `src/api/_wiring.py:wire(app)` (imports LOCAL to wire() — deferred, no import cycle);
  main.py holds ZERO include_router and calls `wire(app)`. ROUTE SET proven identical
  (tests/test_api_wiring.py, anchored to _wiring/main SOURCE + each router's OWN
  router.routes + TestClient dispatch — never a positive app.routes singleton read).
  0.09's CORS/exception-chaining main.py edits preserved. Enforced in test_ui_invariants
  (#26). NOT done (documented follow-up): observability.py extraction (Prometheus +
  CORS/SlowAPI/CSRF middleware coupling).
- **AUTONOMOUS AUDIT 2026-06-15/16 — PR G = FRONTEND A11Y + POLLING BACKOFF (draft
  onto 0.09; browser-unverifiable here, so conservative + node-checked):** (1) CHART
  a11y — `ooChart` (canvas) gains role="img" + a translated aria-label summary + a
  visually-hidden per-series `.sr-only` data table; `dashChartSvg` (svg, already
  role=img) gains the aria-label + sr-table. Shared `_chartAria`/`_chartSrTable`
  helpers build the summary from t9() fragments (a dynamic attribute is never matched
  by the i18n exact-key engine), +4 strings ×12. (2) POLLING — the two always-on
  chrome polls (network + activity, both fixed 5 s) now route through one
  `_adaptivePoll` helper: fast (5 s) while state changes, backing off to 20 s once
  nothing changes for 45 s; pauses while the tab is hidden; resets to fast on
  refocus or an observed change (network flip / scrape active). Self-reschedules in
  EVERY path (can neither stall nor hot-spin); zero extra boot network (one initial
  tick, as before); leans on the existing scheduler/airplane PUSH repaints so state
  stays event-fresh. Cuts field-log finding B's idle storm. RE-VERIFIED already-done
  (OO-D13-001, no change): #toast/#activity/#net-coach carry aria-live; #vitals-pop
  + #palette have aria-modal + `_trapTab` focus trap + focus save/restore
  (_vitalsPrevFocus/_palPrevFocus). Enforced in test_ui_invariants (#24 charts,
  #25 adaptive poll). node --check clean; i18n 100% ×12; suite green.
- **AUTONOMOUS AUDIT 2026-06-15/16 — PR F = TEST COVERAGE + FLAKY GUARD (draft onto
  0.09):** three NEW unit-isolated test files for under-tested modules: (1)
  test_merge_engine.py drives src/backup/merge.merge_corpus DIRECTLY on tiny plaintext
  SQLite corpora (no subprocess torture harness) — proves FK remap (article source_id
  rewritten to the LOCAL source matched by domain), bit-level dedup (same hash+content),
  conflict (same hash, diff content → LOCAL kept + BOTH reported), and merged_rows
  provenance; (2) test_producers_card_shapes.py runs EVERY _DEFAULT_PRODUCERS producer
  over a small corpus and asserts each card's SHAPE (non-empty type/title/summary/bucket/
  method/caveat, valid bucket, serialisable, no composite-score key in signal/evidence)
  + the run_all failure-isolation contract — complements test_briefing.py's _trigger
  check; (3) test_scheduler_runner.py drives BackgroundScheduler via injected
  run_once_fn/settings_provider + threading.Events (NO sleep assertions): continuous
  back-to-back, interval-mode runs-once-then-idles + prompt stop, failing-pass-recorded-
  not-fatal, run_now non-overlap, + round_robin_interleave per-country/order-preserving.
  Each verified to FAIL on a scratch source mutation (reverted). FLAKY ITEM re-checked:
  test_rate_limit_timing + test_cache already use deterministic fake clocks (OO-D15-006);
  test_feed_backoff's absolute-seconds bounds gained a skip-when-inconclusive guard
  (_skip_if_clock_inconclusive) for a pathologically slow box — the backoff LOGIC stays
  asserted unconditionally. Suite green; new tests stable across repeats.
- **AUTONOMOUS AUDIT 2026-06-15/16 — PR E = reliability_score GUARD (draft onto 0.09;
  DEFAULT APPLIED, maintainer may override):** the field is operator-set provenance
  (migration f4b5c6d7e8a9 already NULLed the fabricated =5), but it shipped via
  /api/sources named "...score" with no method/caveat and was guarded only for
  credibility_score/political_bias. DEFAULT chosen (reversible): KEEP it as
  operator-asserted metadata + (a) ETHICS.md documents it as the ONE intentional
  exemption to no-composite-score (never computed/defaulted/derived); (b) new invariant
  test_reliability_score_is_operator_set_never_computed asserts it stays in card.py's
  forbidden-score set AND no analytics module assigns/derives it; (c) the only UI
  surface (the CSV-import column doc) now labels it "operator-set, not computed" with
  the long-form in the #oo-tip hover, +2 strings ×12. source_io serialization gains a
  clarifying comment. PR body flags the default for maintainer override.
- **AUTONOMOUS AUDIT 2026-06-15/16 — PR D = CI HYGIENE (draft onto 0.09, CI
  subscribed):** `.github/workflows/ci.yml` gains (1) top-level `permissions:
  contents: read` (least privilege — CI only reads + tests); (2) action SHA pins —
  actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 (# v4.2.2) +
  actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 (# v5.6.0), both
  SHAs verified live, tag comments for Dependabot; (3) a BLOCKING correctness lane
  `ruff check --select=F,B --extend-ignore=B008` (catches F821 etc.; the full style
  sweep stays advisory `continue-on-error`) — NOTE CLI `--select` drops config
  ignores so B008 (the FastAPI Depends pattern) is re-applied via --extend-ignore;
  (4) `concurrency` with cancel-in-progress. To make the blocking lane GREEN, swept
  the pre-existing 49 F/B violations: 14 B904 (proper `raise … from err`/`from
  None`), F401 dead imports + try/except probe trims (scipy/statsmodels — probe
  intact) + crypto/__init__ re-exports via redundant alias, F841 dead vars (incl.
  removing an orphaned dead std-error calc in statistical_tests), B011/B007.
  Verified: lane fails on an injected F821, passes clean; suite green; mypy 114≤127;
  the existing pinned gates (mypy 2.1.0, bandit 1.9.4, pip-audit 2.10.1, i18n
  --min 100, 3-OS sqlcipher smoke) untouched.
- **AUTONOMOUS AUDIT 2026-06-15/16 — PR C = SAFETY & PRIVACY HARDENING (draft onto
  0.09, CI subscribed):** (1) **scripts/import_eml.py DELETED** (the ledger-flagged
  retirement — broken vs the live Article schema AND it captured To/Cc/Bcc = the
  excluded recipient identity, violating anonymize-at-ingest; surfaced not silent;
  scripts/README row removed). (2) **Wikipedia dump edition-code path-traversal
  CLOSED:** new `validate_wiki_code()` (src/wiki/dumps.py) rejects anything but
  `^[a-z0-9]+(-[a-z0-9]+)*$` (≤32) — wired into `dump_filename`/`dump_url`/`dump_paths`
  (defense in depth) AND the 4 API endpoints (probe/start/page/corpus-ingest → clean
  400). Chose a wider-than-suggested regex so real editions (simple, zh-min-nan,
  bat-smg) still work. tests/test_wiki_path_safety.py. (3) **Ollama kill-switch gap
  CLOSED:** OllamaClient now refuses every request while the kill switch (airplane
  mode) is engaged AND refuses a non-loopback OO_OLLAMA_URL when it opens the socket
  (privacy: LLM never talks to a remote host); tests in test_llm_ollama.py prove no
  socket is attempted offline. (4) **CORS trimmed:** allow_headers → Content-Type+Accept
  (Authorization was dead surface; Origin/User-Agent are browser-controlled),
  preflight cache 24h→10m. (5) **DDG discovery defense-in-depth:** `_clean_url` now
  runs results through `safe_href` (http(s)-only) — the fetch already re-guards.
  Pre-existing duckduckgo.py lint (F841/B007) left for PR D's F/B sweep. Suite green;
  mypy 114≤127.
- **AUTONOMOUS AUDIT 2026-06-15/16 (draft PRs A–H onto 0.09, CI subscribed; each
  hand-verified before shipping — the 06-audit false-positive lesson):** PR A
  (caveats-visible, invariant #23 — above). PR B = DOC ACCURACY (docs-only):
  (1) the stale inline-handler figure (an onclick-only count from the 2026-06-14
  audit) is now the verified **295** (229 onclick + 35 onchange + 15 onkeydown + 14 oninput +
  2 onmouse*) everywhere in CLAUDE.md + docs/audit; (2) ETHICS.md license-header /
  copyright-notice checklist reworded honestly (196/213 src .py carry a
  GPL-3.0-or-later notice — NOT "all"; GPL needs no per-file header, LICENSE is
  authoritative) — note the audit's "0 exist" premise was a FALSE POSITIVE
  (re-verified); (3) the dead `audit/scrape_log.csv` / `audit/errors.log` runtime
  mandate in ETHICS.md replaced with the REAL on-click mechanism (data/*_preflight.jsonl
  + field_test.jsonl + app_errors.jsonl → Settings debug bundle, never
  auto-transmitted); (4) README "all 29 audit findings closed" CLARIFIED (it is
  TRUE — findings.csv reads 29/29 FIXED; the audit's "contradicts 20-fixed-9-deferred"
  premise was a FALSE POSITIVE conflating the 0.07 snapshot with the 0.0.8 close —
  so the honesty non-negotiable forbade the literal "make it say 20/9"); (5) README
  task-manager window + Wikipedia tracked-changes *timeline* tab moved to "In progress
  / next" matching the RC gate 🔶 (the shipped halves stay accurately ✅).
- **SOLO SESSION 2026-06-15 (autonomous; maintainer away) — audit + honesty
  bug-fix stack (draft PRs onto 0.09; full audit + every Class-B/C call in
  `docs/SOLO_SESSION_DECISIONS.md` + `docs/audit/*_2026-06-15_solo.md`):**
  - **Item V SHIPPED — airplane-mode PAUSED status (status-honesty bug):** the
    activity chip painted green "Collecting…" while airplane mode had tripped the
    kill switch (the pass really stops) = a FABRICATED status. Now `_paintNetwork`
    persists `_netOnline` + repaints; `_paintActivity` shows a GROUNDED/muted
    "Collecting paused" with the SPINNER STOPPED when a background pass is in flight
    while offline — never the active green. Class-B choice (D-03): muted/grounded,
    NOT the literal go-off accent (which is `--ok` green here = would conflate with
    active-green) and NOT a new alarm-red. +1 string ("Collecting paused") ×12.
    **RE-OPENED 2026-06-16 (maintainer field test): still sees GREEN "Collecting…"
    after engaging airplane. STATIC RE-VERIFY 2026-06-16: the shipped frontend
    logic reads CORRECT — `_paintActivity` flips to muted `.activity.paused`
    ("Collecting paused", spinner stopped) whenever `_netOnline===false`, and the
    backend rides `online = not kill_switch_active()` on BOTH /api/system/network
    (system.py:122) and every /api/scheduler/status (scheduler.py:59), so airplane
    DOES report offline. Could NOT reproduce green by code-reading ⇒ NEEDS A LIVE
    REPRO (start a collect, engage airplane, watch the 2 s/5 s poll interleaving +
    the exact `s.active`/`online` values during the transition; confirm `_netOnline`
    is never left undefined; note `_pollActivity` (index.html:2742) ignores the
    `s.online` it already receives — make it honor it as a hardening). MAINTAINER
    COLOR/TEXT OVERRIDE OF D-03 (ruled 2026-06-16): the paused chip must use the
    SAME color as the ENGAGED airplane button = `var(--err)` (red), NOT the muted
    grey — so `.activity.paused` color + spinner border-top → `var(--err)`; text
    "Collecting paused…" (add the ellipsis). This consciously REVERSES the
    autonomous "muted, not alarm-red" choice. Update test_ui_invariants if it pins
    the muted color. (Q11=No 2026-06-16: maintainer declined a planning-session
    live repro — root-cause at implementation; the color/text change ships
    regardless.) **SHIPPED 2026-06-16 (this session, branch claude/item-v-paused-status-honesty):**
    `.activity.paused` color + spinner border-top → `var(--err)` (the engaged-airplane
    red; --err is theme-defined so it holds across all themes); label now
    `T("Collecting paused") + "…"` (ellipsis appended in code = ×12 by construction, no
    locale-key churn, i18n stays 100%). ROOT CAUSE FOUND (more than a hardening): the fast
    `_pollActivity` poll repainted the green "Collecting…" chip from `s.active` WITHOUT
    consulting offline state, overwriting the paused state between the slower network
    polls — it now honors the `s.online` the scheduler already returns (scheduler.py:59),
    flipping `_netOnline` + repainting on a change, so the chip cannot lag green.
    test_ui_invariants #14d added (paused chip var(--err) not muted; label appends …; poll
    honors s.online). NB the earlier index.html:2742 pointer is stale post-#236 — the code
    now lives in src/static/app.js.
  - **Item R SHIPPED — discoverable sidebar EXPAND affordance:** the collapsed
    rail showed only a "Collapse sidebar"-titled button (left chevron) with no
    discoverable way back. Now TWO CSS-toggled buttons share the slot: `#sb-collapse`
    (left chevron, "Collapse sidebar") when expanded, `#sb-expand` (right chevron,
    "Expand sidebar") in the collapsed rail. REFINES decision D-05 (a single
    state-aware *title* is unreliable: the i18n engine caches the first-seen English
    title per element in a private WeakMap and re-translates from it on every apply,
    clobbering a swapped title — so two STATIC keyed buttons toggled by pure CSS is
    the i18n-robust realization of the same intent). +1 string ("Expand sidebar") ×12.
  - **Item Z SHIPPED — keyword-log DIGEST mode (diagnostics usability):** the
    `/api/diagnostics/keywords` log measured ~60 MB live (5000 keywords × ~16 langs ×
    a per-keyword language_signature) — unusable in the maintainer→dev channel it
    exists for. NEW `?digest=1` ships the bounded aggregates (families,
    per_source_concentration, totals) + a top-100-by-mentions keyword SAMPLE plus an
    honest `keywords_digest` block (sample/shown/total/omitted) so a digest is never
    mistaken for a complete log. ADDITIVE: the default (full) stream is byte-for-byte
    unchanged (the perf byte-parity contract test still passes); the digest is its own
    branch + `tests/test_keyword_log_digest_mode`. No score; method+caveat preserved.
  - **Item Y SHIPPED — app-wide n<10 → BAR charts (amends invariant #16, see #16
    above for the full ruling + the resolved baseline-honesty decision):** both chart
    renderers (`ooChart` canvas + `dashChartSvg` SVG) now render <10 datapoints as
    honest bars (anchored to the LABELED baseline — true-zero for counts, window-min
    for price levels — with a value-cap so no point is ever invisible) and ≥10 as the
    full-resolution line; the sparse "early corpus" caveat is removed app-wide (only
    n=x kept). node --check clean; test_ui_invariants #16 updated + green; i18n 100%.
  - **B2 FIXITY — VERIFY-BEFORE-IMPLEMENT CORRECTION (no code):** an earlier solo PR
    (#226) added a DUPLICATE fixity audit (`src/integrity/fixity.py` +
    `/api/diagnostics/fixity`) — but the B2 fixity audit ALREADY EXISTED at 0.09
    (`src/verification/fixity.py` + `GET /api/integrity/fixity` + the `runFixity()`
    Settings UI). The duplicate was caught by hand-verification (the recurring lesson)
    and REMOVED from the stack; PR #226 is closed as redundant. B2 is DONE (it was
    already), nothing to ship. Reinforces: grep for an existing impl BEFORE building.
  - **CONVERGENCE ENDPOINT SHIPPED — GET /api/insights/convergences (flagship view
    substrate):** the convergence slice-1 logic (find_convergences) was read-only with
    no API; now a thin insights route exposes it (window/lookback/min_articles/
    min_sources/limit), honest gates + per-cluster method+caveat + totals preserved,
    NO score. tests/test_convergence.py::test_convergences_endpoint proves the
    distinct-sources independence gate flows through the API. The watch-rule alert
    engine stays DEFERRED (Class-C: its UX is a genuine maintainer ruling); the
    frontend convergence view is the remaining slice (now unblocked by this endpoint).
  - **LOCAL .eml NEWSLETTER IMPORTER SHIPPED — Settings → Newsletters (maintainer
    greenlit 2026-06-16, "put it in the settings"):** the S1 anonymize-at-ingest core
    (`parse_email` + `link_sanitizer` + `ingest_eml_*`) already existed; this adds the
    USER path: `POST /api/newsletters/import` (multipart .eml upload) → reuses
    `ingest_emails` under ONE dedicated, DISABLED, FILTERABLE source "Imported
    newsletters (.eml)" (domain newsletters.import.local; never scraped) → returns the
    honest tally (stored/duplicate/empty + recipient_redactions/tracker_params_stripped/
    trackers_flagged + skipped_non_eml). A new Settings "Newsletters" subtab carries the
    file picker + the VISIBLE import-time DISCLOSURE ×12 (what/zero-network-anonymise/
    no-recovery-keep-your-.eml) + the stripped-counts feedback. ZERO NETWORK enforced +
    TESTED end-to-end (`test_newsletters_import_endpoint_zero_network`: N files ⇒ 0
    sockets via socket-forbidden monkeypatch around the whole request; dedup proven;
    source disabled). +16 strings ×12. AUTONOMOUS CALLS (maintainer "make all
    decisions"): (a) ONE dedicated source v1 — NEVER fuzzy-merges (the conservative
    choice; per-publisher eTLD+1 source resolution = the S2 follow-up); (b) loopback
    POST is NOT network-gated (local import works in airplane mode); sender preserved as
    `author` so filtering by publication works today. RETIRE-`scripts/import_eml.py`
    flag still stands (broken vs live schema). REMAINING (S2): vendored dated PSL eTLD+1
    resolver + silent auto-attach + send-domain/List-Id provenance columns + the
    import-progress/UNDO window.
- **TIME-SCOPE + MAP-MENTIONS BATCH (2026-06-15, draft PRs onto 0.09, CI
  subscribed; subagent-built, hand-reviewed):** the maintainer-ruled "dates + a
  visual range bar" UX shipped as ONE reusable component `ooTimeScope` (PR #197:
  From/To date inputs + a draggable range bar with two handles, pointer+keyboard
  + presets 1M·6M·1Y·5Y·All as shortcuts; onChange({from,to}); pure DOM/CSS,
  deterministic; degrades loudly "not enough data for a time range") and REUSED
  app-wide per the maintainer's "reuse everywhere" choice: Markets commodities
  board (#197 — replaces the 5-choice #mkt-scale select; windows on ABSOLUTE
  [from,to] via filter-only windowPricesRange, full-resolution invariant #16
  held; default = last year anchored to DATA max never "now"), Insights Explore
  trend + the keyword/corpus analysis-window Trend sub-tab (#199 — client-side
  filter on /api/insights/trend, shared _buildTrendScope factory, no fork), and
  the Search tab (#201 — replaces #f-from/#f-to, feeds the SAME start_date/
  end_date params, default FULL span so a plain search excludes nothing,
  openAnalysis repointed off the removed inputs). Strings ×12 (From/To/All/Time
  range + 1M/6M/1Y/5Y kept as compact universal abbreviations); coverage 100%;
  node --check + test_ootimescope_range_control/_reused + test_search_timescope +
  test_ui_invariants green. ALSO this session: TEMPORAL-MAP MENTION LAYER (PR
  #200) — plots /api/insights/where places on the existing map projection
  (lon2x/lat2y reused, NOT forked), marker AREA ∝ article spread (raw counts, NO
  score), OFF by default, null-coordinate places surfaced honestly ("N not
  mapped"), the "Deduced from text, never confirmed." caveat VISIBLE in legend +
  marker readout (informed-consent layering); +16 strings ×12 (incl. the toggle
  label + long hover title, since i18n.js translates title/text by English
  lookup); test_tmap_mention_layer green. REMAINING for these threads: ooChart
  rollout to commodity-card enlarge/indices board; the map's mention layer also
  consuming EVENT-places; calendar-picker + typo-tolerant did-you-mean for date
  search (the range control is the begin/end half).
- **AUDIT REMEDIATION PASS (2026-06-15, acts on `docs/audit/AUDIT_LOG_2026-06-14.md`;
  plan + per-finding status in `docs/audit/ACTION_PLAN_2026-06-14.md`; ONE PR onto
  0.09):** every finding re-verified at HEAD first (the audit was pinned at ba61162;
  #158 had already closed README count/restore + the ETHICS "becomes functional"
  line + the ARCHITECTURE Postgres section). SHIPPED+verified (full suite green,
  mypy 114≤127, bandit clean, i18n 100%×12, node --check): OO-D2-001 robots-redirect
  SSRF guard (one shared `_guarded_redirect_get`, +2 tests); OO-D3-001/D5-002/D10-001
  dead-config prune (auto_download + audit_* fields/env/yaml; `Config.get_data_dir`
  now delegates to `src.paths.data_dir`); OO-D7-001 `upsert_sources` per-row
  SAVEPOINTs (mid-batch error no longer drops the window); OO-D10-002 invariant test
  (credibility_score/political_bias never serialised by any API module); docs honesty
  OO-D14-001/003/004/005/006/007 + D9-001 + D6-001 (ETHICS deps→present tense + real
  pyproject licenses incl. LGPL/MPL GPLv3-compat; ARCHITECTURE license/restore/API-map/
  anchor; DESIGN meta-note; models docstring SQLite-only); CI OO-D15-001 i18n `--min
  100` blocking gate + OO-D15-004 pin pip-audit==2.10.1 + OO-D15-005 generic
  extra-probe + OO-D15-006 fake-clock cache; a11y OO-D13-001 (aria-modal + focus
  save/restore + Tab trap for palette & task-manager) + OO-D13-002 (`fam-pick`
  aria-label; recipe-toggles were already `<label>`-wrapped = false positive) +
  OO-D12-002 esc() consistency; OO-D3-002 the "stays on this machine" headline is now
  QUALIFIED ("Your corpus stays on this machine — no cloud, no telemetry; fetching
  follows your Network mode.") keyed ×12 — **exact wording still open to a maintainer
  ruling** (resolves the long-standing AWAITS-RULING note as a default, not a veto);
  audit-07 **B1** disclosure sweep (VADER English-only on the *framing* surface — the
  one gap; LLM "verify against stored article" label; USER_MANUAL §5.5 "Known limits
  & honest disclosures"); OO-D8-001 perf_harness now times the named paths (FTS
  rebuild + search + corpus-window) with a documented 100k profile; OO-D5-001
  GOVERNANCE states custody-trail is opt-in (one-click enable) — **default-flip is a
  maintainer call**; OO-D2-003 SSRF TOCTOU residual documented in SECURITY. DEFERRED
  (raised as PR questions): OO-D12-001+D2-002 the inline-handler→CSP migration
  (295 inline on*= as of 2026-06-15; large + browser-unverifiable here), OO-D15-002/003 ruff-blocking + win/mac
  graduation. New locale strings are AI-drafted (flagged for native review).
- **QUARANTINE REMOVED TO AN ARCHIVE BRANCH (2026-06-14, maintainer-chosen):** the
  ~79.5k-line `quarantine/` tree (legacy six-pillar trees + fabricated/dead modules,
  never imported, excluded from package/ruff/mypy/coverage) was removed from the
  working tree and preserved on the `quarantine-archive` branch. The honesty record
  (what was there + why) + retrieval instructions live in `docs/QUARANTINE_ARCHIVE.md`;
  live-code breadcrumbs (metadata.py, link_analyzer, src/__init__) were repointed there.
  REVERSES the earlier "kept (not deleted)" note — salvage stays one
  `git checkout quarantine-archive -- <path>` away; NO history rewrite (every SHA
  intact). Chosen over a full filter-repo purge (which would break SHAs/forks/PRs for
  only ~4 MB of full-clone savings).
- **AUTONOMOUS BUILD 2026-06-13 (items 1-3, MERGED to 0.09 — PRs #106/#107/#108):**
  (1) CI HYGIENE — pinned mypy==2.1.0 + bandit==1.9.4 (unpinned tools had
  drifted: mypy 129>128 reddened EVERY PR; that masked a bandit B314); fixed 2
  real latent bugs (429 handler exc.retry_after AttributeError; escape(None));
  fixed B314 with defusedxml (real XXE/billion-laughs defense on dump XML);
  baseline 128→127. (2) DATA-LOSS — run_write_with_retry (src/database/write.py)
  wraps import_points: a transient "database is locked" rolls back + re-runs the
  idempotent work (backoff+jitter) instead of DISCARDING fetched-over-Tor prices
  (the field-log copper/aluminum/nickel/zinc loss). (3) GUARDED SOCKET FACTORY —
  src/safety/fetcher.guarded_session routes dumps/wiki-client/ores/DDG through
  the kill switch + protected-mode proxy + honest versioned UA (closed a
  TRANSPORT LEAK: dumps bypassed the in-app proxy → could egress clearnet);
  socket-importer ratchet allowlist 6→3; +15 tests. Full suite 1056 passed.
  REMAINING from these foundations: ~~the single-writer QUEUE (supersedes the
  retry)~~ SHIPPED as the single-writer GATE (commit 3268922, src/database/writer.py;
  end-to-end data-loss + gate-isolation proof in tests/test_write_gate_dataloss.py —
  see field-log finding A); ~~parallel downloads~~ SHIPPED (Step 2: collect worker
  pool + dump max_concurrent=3; end-to-end guardrail tests in
  tests/test_parallel_collect_guardrails.py); task manager window (Group C).
- **PERFORMANCE BATCH T1 (2026-06-12, this session):** measure→fix→re-measure
  at the live shape (6.4k articles / 228k keywords / 317 MB synthetic;
  `scripts/perf_harness.py`, zero network). Keyword export 14.1→4.0 s
  (encrypted 33.8→7.8 s), STREAMED, cap bounds the WORK, envelope
  byte-compatible (contract-tested); briefing recompute 36.6→1.5 s (MinHash
  numpy vectorisation, EXACT parity with pure fallback unit-tested, + memo
  across producers — F-005 closed); insights map ≈550→215 ms (tuples, not ORM
  entities); covering index ix_mention_covering (model + migration
  e2f3a4b5c6d7 + boot self-heal); statement deadlines (typed 503, never a
  hang); PRAGMA optimize + bounded first-boot ANALYZE; mmap plaintext-only;
  stats/coverage cached 30 s with computed_at/cache_ttl_s DISCLOSED; Settings
  VACUUM tool with real freed bytes + freelist "reclaimable" readout (+8
  strings ×12). ANALYZE/index plan-regression suspicion tested and DISPROVEN
  (identical plans, evidence in PR #79).
- **Console/Desk FINAL verdict (2026-06-10):** Desk RETIRED ENTIRELY — one
  interface, the Console (sidebar → icon rail). `desk.html` deleted; `/desk`
  308-redirects to `/`; one launcher. Fold Desk's best ideas (task-framed
  home, ⌘K, calm) into the Console over time — never resurrect a second
  chrome. (The "lost work" scares were investigated and disproven: temporal
  map + agenda were alive all along — the Desk nav simply lacked them; the
  3.8→2.3 MB archive delta was deleted stale reports, not code.)
- **0.0.8-era shipped set:** eye logo everywhere · sidebar rail · constant
  top-bar footprints · vitals strip · kill switch on Stop · source preflight
  + JSONL log · wiki edition dropdown · local-first reader links ·
  related-by-keywords · Home fail-safe · 12 complete locales · date-stamped
  model catalog + freshness test · discovery off-by-default · USER_MANUAL
  coverage.
- **Field log #1 (2026-06-11) processed:** family over-merge guards; FRENCH
  stoplist block added (was missing entirely); first 10 equivalence rings;
  catalog pruned from live verdicts (13 defunct WPH codes, 4 Stooq indices
  robots-denied, Wilshire 404).
- **Live-test batch (2026-06-11), five items shipped:** mind-map radial-tree
  rules + cloud second view + date-spectrum control; super-groups
  pre-created (seed idempotent, user wins); keyword-log cap PER LANGUAGE
  (5000 — a global cap anglicises the export); temporal-map usability
  (focus-date input, span remap, fat hit discs, wheel zoom, overlay
  controls, ⛶); Settings wiki-dump language list fixed (duplicate JS
  function) + multi-select download queue.
- **Extractors shipped (2026-06-11):** location (gazetteer + country table,
  snippet provenance, "deduced" notes) and entities (PEOPLE and
  ORGANIZATIONS as separate classes by design; explainable rules with
  per-entry notes; org-claimed words never double as persons). Both surface
  in the reader's deduced block. btop ruled OUT (the CPU bug was psutil
  per-core normalization, fixed in-app).
- **Themes + bundled fonts (2026-06-11):** 17 themes + System; six SIL-OFL
  fonts bundled local-only; Typeface picker; visual-bug sweep fixed
  (range-slider styling, dead .drawer selectors, color-scheme, accent-color,
  /investigate theme sync). Invariants #10–12 enforce.
- **Agenda data-first slice (2026-06-11):** MONTH GRID default view
  (Monday-start, Intl names in UI language, honest no-fixed-day strip,
  day-click details, recurring semantics in every browsed year); List stays;
  subscriptions + feed directory moved to Settings → Agenda; tab fully keyed
  ×12. Invariant #13 enforces. Remainder lives in the queue (agenda content).
- **De-US-centring first batch (2026-06-11):** see queue entry for remainder;
  Library tab done (#library anchor, live-poll coverage, ISO-2 + full-name
  display).
- **FULL AUDIT 06 (2026-06-11):** delivered with same-PR fixes (esc()
  apostrophes, ETHICS false banners, async_db quarantined, credibility
  default removed + NULLed, raw-requests helper removed, source counts trued
  up). Remediation queue above.
- **DB-RELIABILITY + SQLCIPHER BATCH (2026-06-11→12, PRs #76/#77) — the
  mandate ("like the backup/restore function of an OS; if it's not entirely
  reliable, it should not exist") is MET for the core:** gap analysis + design
  in `docs/design/DB_RELIABILITY_01_GAP_ANALYSIS.md` / `_02_DESIGN.md`
  (D1–D7 decisions recorded there). Shipped: merge_batches/merged_rows
  provenance; staged-file migrations (alembic on arbitrary files — never the
  live DB); the oo-backup-2 artifact (ONE zip: signed manifest with
  per-member sha256 + Merkle over article hashes + EXCLUSIONS listed; corpus
  + custody snapshots; settings/annotations/events/logs members; keys ONLY
  in encrypted artifacts; legacy artifacts accepted forever); the merge
  engine (preview=commit same code on a disposable copy — the preview cannot
  lie; ~28 tables on natural keys with FK remap; bit-level article dedup
  (hash + byte compare); conflicts keep LOCAL + report both values, never
  averaged; curation/settings local-always-wins; unmerged tables reported;
  pre-swap verification incl. FTS rebuild+count; atomic swap + keep-3
  snapshots; custody chains imported verified-not-trusted into
  custody_imported_entries, original seqs preserved, NEVER spliced,
  transitive chains propagate); /api/backup/v2 endpoints + boot janitor;
  **TORTURE SUITE 10/10 GREEN** (SIGKILL mid-merge/at-swap ⇒ live DB
  byte-identical; floods idempotent; cross-version via staged upgrade with
  floor=0.0.8-baseline refusals BY NAME; plaintext↔encrypted round trips
  content-identical; divergent corpora; FTS truth; settings sanctity;
  symmetry outside reported conflicts). **SQLCipher at-rest encryption ON by
  default (PR-E, the honesty gate respected — prompt shipped WITH crypto):**
  ONE connection factory (per-file header detection; explicit key >
  OO_DB_PLAINTEXT > holder passphrase > LOCKED; loud typed errors); locked
  boot serves only /unlock (self-contained, offline, i18n'd, verbatim
  no-recovery note + threat model + length-beats-rate-limits guidance);
  OO_DB_PASSPHRASE headless; doctor attests per-store from real headers;
  one-way encrypt tool (consent, verification, DELIBERATE plaintext
  escape-hatch snapshot; covers corpus + custody under THE one passphrase);
  state-tolerant key loading (legacy plaintext signing keys keep working;
  key_protection reports the FILE's real state). EMPIRICAL FACTS that must
  not be relearned: SQLCipher's backup API cannot cross key boundaries
  (sqlcipher_export does) ⇒ snapshot_to_plaintext vs snapshot_preserving
  are INTENTIONALLY distinct — working copies and pre-restore nets STAY
  ciphertext; a restore must NEVER silently decrypt the corpus (crown test
  enforces); deferred startup must run at EVERY unlocked lifespan (init_db
  self-heals schemas — a once-per-process guard broke this once). 3-OS
  sqlcipher smoke job BLOCKING and green. Riders in the queue.
- **Diagnostics channel (2026-06-10):** keyword log + network log + debug
  bundle, on-click only, never auto-transmitted. Maintainer protocol: click
  through the app, send the bundle. Temporal map ships PRECONFIGURED
  (bundled Natural Earth coastline, invariant-tested).
  **DATE-EXTRACTION LOG ADDED 2026-06-16 (maintainer-asked: "gather extracted date
  information so I send it to you to optimize the extractor"):** `GET
  /api/diagnostics/dates` + a Settings → Diagnostics button "Download
  date-extraction log (.json)" (×12). Pure core `src/timemap/datediag.py`
  (`recall_probe` + `analyze_article`, fully unit-tested). Per article it pairs the
  LIVE extractor (run exactly as ingest does — publication-date anchor + language)
  with a PERMISSIVE recall probe (bare years, CJK 年月日, numeric d/m/y, month/
  weekday/relative words) that deliberately over-matches, so the difference =
  date-like text the extractor missed = the optimization material. Aggregates over
  a bounded scan: coverage %, precision dist, dates-per-article histogram,
  per-LANGUAGE coverage + `in_month_vocab` (the clearest vocabulary-gap signal — a
  language with no month table shows ~0 coverage; reveals the zh/ja/ru/ar/hi/bn gap
  the European-only `_MONTHS` table can't catch), probe-kind totals, and a sample
  sorted WORST-actionable-miss first (bare years excluded from "actionable" — the
  extractor skips them by design) carrying extracted + probe + `stored_tags` +
  bounded content excerpt. Bounded + on-demand + local (Item-Z size discipline:
  light first pass, heavy records only for the ~60-row sample); envelope-wrapped;
  NO scores; probe hits labeled candidates (high recall, low precision). Honest
  follow-on optimization targets it already exposes: CJK 年月日 handling + native
  month vocab for the non-European UI locales; optional bare-year contextual
  extraction. tests/test_date_diagnostics.py.
  **KEYWORD-LOG ≤20 MB PER-LANGUAGE ZIP ADDED 2026-06-17 (maintainer-asked after a
  live perf log showed the single-file keyword log at ~19.6 MB / 137k keywords —
  about to breach 20 MB):** `GET /api/diagnostics/keywords?format=zip` returns a
  per-language ZIP — `summary.json` (the corpus-wide aggregates: families,
  super-groups, per-source concentration — same as the single-file log minus the
  keyword list), `keywords/<lang>.json` per dominant language (same per-keyword
  fields), `manifest.json` (counts + omissions + note). Splits on the existing
  per-language export quota; JSON compresses ~8× so the archive is normally a few
  MB. HARD cap `OO_KEYWORD_LOG_MAX_MB` (default 20): if the compressed archive ever
  exceeds it, the lowest-mention keywords are dropped PER LANGUAGE (equal-fair — a
  global mentions cut would re-anglicise the export, the standing rule) and recorded
  in the manifest (never silent). The Settings → Diagnostics button now points at
  `?format=zip` (label re-keyed ".json"→".zip" ×12). The DEFAULT `?format=json`
  stream is byte-for-byte UNCHANGED (Item Z digest + the perf byte-parity contract
  intact). `scripts/analyze_keyword_log.py` reads the .zip directly (reassembles
  summary + shards into the doc it already expects). tests/test_keyword_log_zip.py
  (split/bounded, per-language trim when over cap, analyzer reads it, default JSON
  unchanged).
