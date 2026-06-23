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
- **AIRPLANE MODE IS A SOCKET-LEVEL HARD GUARANTEE, not just a per-call convention
  (ruled 2026-06-19 field test P0-1/#3/#8/#68; SHIPPED same day):** the kill switch
  was checked at the top of every KNOWN fetch path — airtight only as far as our
  memory. `src/ingest/airplane.py:install_airplane_socket_guard()` (wired into the
  boot path in `run_deferred_startup`, alongside the boot kill-switch activation,
  inside the same `OO_NO_SCHEDULER!=1` block) now wraps `socket.getaddrinfo` /
  `create_connection` / `socket.socket.connect(_ex)` process-wide: while the kill
  switch is engaged, ANY non-loopback target raises `AirplaneModeError(OSError)`
  BEFORE the real socket call is reached — so no missed call site, third-party lib,
  or DNS prefetch can egress. Loopback (127/8, ::1, `localhost`) + AF_UNIX always
  pass through (the app's own server, loopback Ollama, file DB). TRANSPARENT while
  online (delegates straight through — zero cost during collection). The per-call
  refusals stay as the friendly/explanatory layer; this is the net beneath them.
  `OO_AIRPLANE_SOCKET_GUARD=0` disables. Enforced by tests/test_airplane_socket_guard.py
  (white-box: proves the real call is NEVER reached for a remote target in airplane
  mode = the brief's "boot + decline = zero sockets") + a source-level guard that the
  boot path still installs it. INVESTIGATION RECORD (the rest of #3/#8): the documented
  Python paths were ALL already gated (stats/fetch, duckduckgo, ollama via
  _check_kill_switch + _require_loopback, weather); the scheduler does NOT auto-start
  (only POST /api/system/network or /api/scheduler/start starts it; "Not now"/
  dismissNetCoach POSTs nothing); boot DOES engage airplane (main.py); and the static
  files carry ZERO external resources (no CDN/web-fonts/preconnect — grep-verified; only
  one click-target ollama.com link). The loopback activity/network/vitals polls are NOT
  internet. So the residual leak (if any beyond Ollama's own process / browser
  DNS-prefetch) is now caught by construction.
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
- **EXTERNAL-ARTIFACT REGISTRY (ruled 2026-06-19; SHIPPED — `configs/external_artifacts.yml`
  + `src/maintenance/registry.py` + `tests/test_external_freshness.py` + the
  `docs/maintenance/EXTERNAL_DEPENDENCIES.md` upgrade checklist):** ANY externally
  sourced/pinned/bundled artifact (a dated `*_AS_OF` data file/catalog, a vendored binary,
  a version coupling, a CI pin) MUST get a registry entry IN THE SAME COMMIT — the protocol
  guard test fails otherwise (it scans the tree for `*_AS_OF` constants + asserts each is
  registered). The consolidated freshness/compatibility check replaces the scattered
  per-file freshness tests; `scripts/check_external_freshness.py` + `GET /api/diagnostics/
  freshness` report status. On a DuckDB bump follow the EXTERNAL_DEPENDENCIES upgrade
  checklist (re-bundle the per-OS `httpfs` crypto extension at the new version; the registry
  `duckdb-crypto-extension` floor MUST equal the pyproject `[columnar]` floor — test-enforced).
  LAYER 3 SHIPPED 2026-06-19 (maintainer "yes"): `.github/dependabot.yml` (pip + Actions) +
  `.github/workflows/freshness.yml` (weekly cron) running `check_external_freshness.py` +
  `check_upstream_updates.py` (GitHub API per a registry `upstream_check`, degrades loudly) +
  `freshness_issue.py` (ONE rolling `freshness`-labelled issue, opened/updated/closed
  idempotently). Add `upstream_check:{github,type}` to a registry entry to watch it.
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
- **MAINTAINER FINALIZATION RULINGS 2026-06-23 (verbatim "proceed in full autonomy [on] everything we are
  currently listing"; answered a 20-question yes/no finalize-everything list ALL YES + "you decide what's
  best" on PR strategy + priorities — NO further questions, build it all):** binding decisions that unblock
  the deferred queue:
  (1) keyword digit-code + underscore filters STAY on by default; (2) the underscore rule eating technical
  `snake_case`/handles is an ACCEPTED casualty for a news corpus; (3) BUILD §2.6 offline language detection
  — add a pure-Python, no-network lib (py3langid) — and the detected language is **SECONDARY/DEDUCED
  metadata** (never overwrites the source/trafilatura-asserted `Article.language`; used only as a deduced
  fallback for extraction + the keyword's analytic language, labelled deduced, two-class model); (4) brand/
  company tokens (govdelivery) STAY content, never stoplisted; (5) the single-transition `letterN` filter
  limit is ACCEPTED; (6) BUILD the remaining manipulation cards; (7) manufactured-emergence = build the FULL
  honest version INCLUDING the "no datable primary anchor" check (so it doesn't fire on all breaking news);
  (8) BUILD the per-source concentration primitive flood/bury needs; (9) cards STAY auto-surfacing as Home
  Leads; (10) BUILD browser-unverified frontend (conservative + node-check + invariant-guarded + flagged,
  fork-3); (11) BUILD the §5.1 source-tag analysis filter (thread `tags` through the corpus-* endpoints
  too); (12) BUILD the world-map "Sources by location" bubble subtab (country|IP toggle); (13) BUILD the
  sentiment tone chip in the analysis Articles + search lists; (14) BUILD additive-restore FILE-member
  placement (CI-gated torture); (15) BUILD restore-as-a-task-manager-job; (16) BUILD Wikipedia-dump
  full-text search; (17) DO documentation slices (USER_MANUAL + docs↔app reciprocity, RC-blocking); (18)
  BUILD the agenda content batch; (19)+(20) PR strategy + prioritization are MINE to decide (multiple PRs
  fine). EXECUTION: ship across slices, verify each, full autonomy, no more questions.
- **DATA-ARCHITECTURE & DURABILITY SKELETON (maintainer design session 2026-06-19; ARCHITECTURE-OF-
  RECORD delivered, build BRIEF ready, code NOT started — full design in
  `docs/design/DATA_ARCHITECTURE_SKELETON.md`; the paste-ready autonomous-session build brief in
  `docs/design/AUTONOMOUS_BUILD_BRIEF_DATA_ARCH.md`):** product of TWO internet-research reviews
  (scaling 10×/100×/1000×; provable source authentication & tamper-evidence) cross-checked against the
  codebase. KEY INSIGHT: scaling + durability + authentication are ONE skeleton — one canonical
  encrypted SQLite/SQLCipher store, one A1 export seam, two disposable rebuildable derived
  representations (a columnar store for SPEED, a WARC/BagIt archive for PERMANENCE), both keyed by the
  K1 content hash, both carrying the honesty envelope; the custody log/signer/anchor already built in
  `src/custody` IS the day-one federation seam. MAINTAINER RULINGS (binding): (1) CROSS-TIME RECALL IS
  SACRED — no feature may bias toward recent data / default to a recent window / make old data
  second-class (so TIME-PARTITIONING is ABANDONED unless provably byte-identical with no recency bias);
  (2) PERFORMANCE MUST NOT DEPEND ON HIDING DATA — decade-scale speed comes from maintained counters +
  a derived columnar read-model with every article fully present + searchable always; (3) HONESTY
  ENVELOPE mandatory on maintained aggregates `{value, basis:exact|estimated, as_of, method, n}`
  (basis is a DISCLOSURE not a score — assert_no_score_fields holds), the thing that makes counters
  honest despite the `KeywordMention` ondelete=CASCADE drift; (4) DERIVED COLUMNAR STORE = PERSISTED +
  ENCRYPTED DuckDB under the SAME passphrase (one connect() factory, no second key surface, invisible
  to the user), incrementally maintained so a decade-scale corpus is never reprocessed per session,
  with an EMPIRICAL offline encryption GATE (sentinel absent from raw bytes · won't open without key ·
  opens with key) and a HARD FALLBACK to DuckDB IN-MEMORY — NEVER a plaintext derived file; it is a
  disposable cache (canonical store stays source of truth; cold/missing store falls back to the live
  query; excluded from backups, rebuildable); (5) CAPTURE POSTURE = default-anonymize + opt-in
  high-fidelity (do NOT reverse anonymize-at-ingest; the invasive raw-retention default would buy DKIM
  proof that may evaporate by design — the key-publishing deniability movement); (6) SOURCE IP CAPTURE
  + OFFLINE GEOLOCATION onto ooMap as a DISTINCT "server location" layer (country-level CC-DB bundled
  + city-level downloaded on demand into data_dir, NEVER at boot; honest "unavailable" over Tor since
  the socket is the proxy not the server; caveats VISIBLE — CDN-edge/anycast/approximate/never proof
  of true origin; clustering = a shape to investigate like source-laundering, never a verdict); (7)
  TIERED-RETENTION EVICTION DESIGNED-not-BUILT (needs the WARC archive first; default-off; ONLY raw
  text relocates to a LOCAL archive while the search index + all mention/analytic/metadata rows stay
  HOT so no search/analytic loses anything; transparent on-open local read; reversible; performance
  does NOT depend on it). FROZEN SEAMS for V0.1 (K1 content-multihash ALONGSIDE the never-reformatted
  Article.hash · K2 canon_version · K3 provenance Tier vocabulary descriptive-not-a-score · K4 honesty
  envelope · K5 BagIt+WARC-text-fidelity-with-raw-slots-reserved archive · K6 encryption decoupled
  [SQLCipher operational no-recovery / age outer archival / same-key-or-in-memory derived] · K7
  format-versioning-fails-LOUD). DEFERRED (separate workstreams, routed/gated): WARC/BagIt archive +
  age + SLIP-39; TLS chain/SCTs/CT capture + the Tier-vocabulary UI (authentication-evidence);
  TLS-NOTARIZATION Tier-2 (TLS-1.2-only + Tor-incompatible bandwidth + injects a deanonymizing third
  party — NOT load-bearing now); WITNESS FEDERATION / the original blockchain intent → the Open
  Commons Mirror sister project (this app stays single-machine + anchoring-only via OpenTimestamps,
  ~90% of the value with one consented call, no cluster). VERIFY-before-0.1: DuckDB encryption AEAD/
  offline + string-heavy speedup; age/SLIP-39 + recovery drill; TLSNotary TLS-1.3; C2PA offline trust
  list; OTS offline verify; published-private-key DKIM prevalence; IP-geo DB license/size/offline.
  BUILD ORDER (the brief): envelope → counters → A1 seam → columnar engine → K1/K2 identity → IP+geo.
  **BUILD STATUS 2026-06-19 (branch claude/modest-hopper-gisgst, draft PR onto 0.09 — full per-slice
  detail in the Shipped-batch-log entry "DATA-ARCHITECTURE & SOURCE-IP BUILD 2026-06-19"):** SHIPPED =
  Slice 1 envelope, Slice 2 counter freshness+reconcile, Slice 3 read-model seam, Slice 4 PR-1
  columnar engine (in-memory; persisted-encryption BLOCKED on a per-OS httpfs crypto-extension
  packaging decision — empirical finding), Slice 5 K1/K2 identity, Slice 6a IP capture, Slice 6b
  offline geo engine+generator (real DB-IP table BLOCKED on a networked-machine fetch — 403 here;
  CC BY 4.0 verified), Slice 6c server-location backend. **FOLLOW-UP SHIPPED 2026-06-19 (PR #410 after #407 merged,
  "proceed with all"; detail in the Shipped-batch-log "DATA-ARCHITECTURE FOLLOW-UP 2026-06-19"):**
  6b real DB-IP table now BUNDLED (CC BY 4.0 mirror, ~4.4 MB, offline lookups proven) so 6b + the
  VERIFY-list "IP-geo DB license/size/offline" are DONE; 6c FRONTEND ooMap "Server IPs" layer SHIPPED
  (browser-unverified); Slice 4 PR-2 FOUNDATION (columnar read-model builder + byte-identical
  projection + cold fallback) + D (persisted background maintenance + /api/diagnostics/columnar
  observability) SHIPPED. **PR-3 SHIPPED 2026-06-19 (the heavy-aggregation perf, draft PR after #412
  merged) — but via the Slice-2 COUNTERS, not the DuckDB port (the honest engineering call):** the
  /api/insights/associations 76 s was an N+1 (a per-co-keyword COUNT(DISTINCT article_id) for n_b +
  a session.get(Keyword) per row), NOT a DuckDB-shaped problem. Fixed in queries.associations: the
  co-keyword rows are batch-loaded (one query, not N gets), and n_b corpus-wide == the maintained
  ``article_count`` counter (BYTE-IDENTICAL: it IS COUNT(DISTINCT article_id), reconciled), so ZERO
  query; windowed n_b comes from ONE grouped query (not N). layered_graph (keyword level calls
  associations ~6×) inherits it; the Python PMI/family/ring honesty layers are untouched. Proven
  byte-identical on both paths (tests/test_associations_perf.py recomputes n_b the live way + asserts
  equality). framing was already bounded (8000-char cap + joinedload, prior fix); porting it would
  need content in the derived store — deferred. REMAINING (now optional, NOT the 76 s blocker): the
  columnar store could accelerate the inherent co_rows GROUP BY when PERSISTED — gated on the per-OS
  httpfs/OpenSSL crypto-extension PACKAGING DECISION (until then columnar is in-memory; the hot
  endpoints run fast on the counters). The data-architecture brief is COMPLETE bar that one
  packaging decision.
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
  ai_layer store (#330/#332, now ai_keyword tables in the MAIN DB per the 2026-06-18 storage
  reversal #377).
  **UNIFIED AI-METADATA + USER-DEFINED PROMPTS (maintainer ruled 2026-06-18): AI metadata is
  UNIFIED and PROMPT-RELATED** — who/where/when (time/location/entity) and any user-defined
  prompt all produce the SAME kind of thing: typed AI-metadata rows in `ai_keyword`
  (kind=type, term=value, prompt provenance), rendered INLINE in the article view labelled
  "AI-derived · unreliable". A user defines a MANAGED LIST of custom extractors, each runnable
  ON DEMAND and/or AUTO-ON-INGEST (per-prompt toggle). PROMPT-EDITOR UX SHIPPED (#380, merged):
  the Settings → Models prompt boxes are pre-filled with the effective text, auto-sized,
  resizable + copyable, and saving a box equal to the default clears the override.
  CUSTOM-PROMPT BACKEND SHIPPED 2026-06-18 (branch claude/ai-custom-prompts, draft PR onto 0.09;
  VERIFIED py3.13): `AiCustomPrompt` model (label · output_kind=the metadata type · prompt_text ·
  run_on_ingest · enabled) + migration e1f2a3b4c5d6; CRUD `GET/POST/PUT/DELETE /api/ai/prompts`;
  `POST /api/ai/prompts/{id}/run` streams a run over a selection (reuses `_resolve_work` +
  `extract_for_articles`, now parametrised with a custom `system` prompt + output `kind` +
  `prompt_version="custom:<id>"`) → writes `ai_keyword` rows of that kind, NEVER the trusted
  index (test asserts ZERO KeywordMention). tests/test_ai_custom_prompts.py (5).
  CUSTOM-PROMPT UI + RUN + SEARCH + INLINE + AUTO + BUILT-IN-EDITOR ALL SHIPPED 2026-06-18 (stacked
  draft PRs onto 0.09, ALL MERGED; frontend browser-unverified per fork-3 — needs a click-through):
  (#386) Settings → Models "Custom extractors" CRUD UI (define/edit/enable/delete the managed list,
  reuses the #380 editor); (#387) a "Run extractor" action in the analysis window runs a chosen
  extractor over the selection (ctx-aware `aiRunPrompt`, mirrors bulkLlm: `_bulkParams` + NDJSON
  stream + abort); (#390) the SAME control in the SEARCH toolbar (parity); (#388) the unified AI
  metadata renders INLINE in the article view as a THIRD class "AI-derived — unreliable"
  (server-rendered in `view_article` via `ai_store.keywords_for_article`, grouped by kind, absent
  when none; TestClient-verified); (#389) AUTO-ON-INGEST (`src/ai_layer/auto.run_auto_on_ingest`)
  runs enabled+`run_on_ingest` extractors over recent articles in the scheduler's POST-PASS
  housekeeping — NEVER inline (a model in the scrape hot path would stall it), opt-in (no auto
  prompts ⇒ zero cost), `skip_existing` so only NEW articles cost a call, `is_available`-gated;
  (#391, Part B) the built-in keyword-EXTRACTION prompt is now editable in the SAME
  Behaviour-&-prompts editor (`AppSettings.llm_prompt_ai_keywords`; `/api/llm/prompts` 4th entry;
  the extract endpoint applies the override → `"ai-keywords-custom"` provenance). The unified loop
  is COMPLETE: define (custom) / tune (built-in) → run (analysis OR search, or auto-on-ingest) →
  see inline — all local, never the trusted index, provenance per result. REMAINING (polish): a
  per-article Summarize/Translate/extract on the analysis Articles list; the broader LLM-PERCEPTION
  eval program (above) is the separate, larger track.
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
  single-source-flagged, unrelated-text-no-cluster, endpoint). CARDS #7 HEADLINE-BODY-MISMATCH +
  #3 MANUFACTURED-EMERGENCE + #4 FLOOD SHIPPED 2026-06-23 (see the shipped-log entries; #3 = the FULL
  anchor-gated form per Q7; #4 = the FLOOD half + the foundational `KeywordMention.source_id` denormalisation
  it needed). REMAINING cards: the BURY half of #4 (a source UNDER-covering a topic big elsewhere — needs a
  real external trigger); event-timed-op [#3+#6+agenda] needs the elections CANDIDATE ROSTER (design-only/
  deferred); outrage-intensity is SECONDARY (annotates another card, never a standalone Lead);
  astroturf/copypasta partly covered by echo_chamber. So 4 of the 9 cards now ship as producers
  (source-laundering #6, recycled-claim #1, headline-body #7, emergence #3, flood #4 = 5 actually); the rest
  are foundation-gated.
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
  **AUTONOMY HARDENED FURTHER (maintainer ruled 2026-06-21, verbatim "Change the
  ruling, I don't want to be asked anything. … This session should be completely
  autonomous"): for the upcoming build session that executes
  `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-06-21.md`, DO NOT ask ANYTHING — make
  EVERY decision yourself, including the few that earlier briefs marked as "ask first."
  All of that brief's prior §1 questions are now ANSWERED (keep "Article" naming /
  server-side backup path / models in the same folder backup); there are no remaining
  questions to put. Pick the most honest, conservative default and proceed; record the
  choice in this ledger. This applies to that build queue specifically; the general
  AskUserQuestion carve-outs above still hold for a genuinely NEW ethics/irreversible
  surface not covered by the brief.**
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
- **NEWSLETTER BATCH-IMPORT OVERHAUL (maintainer field test 2026-06-20; PENDING — building
  on branch claude/keen-lamport-b4t3rh):** the .eml importer must scale to a FOLDER of
  20GB+ newsletters. SIX asks: (1) FOLDER/BATCH import — the file picker can't select a
  folder; (2) HTTP 400 at ~1300 files — ROOT CAUSE = Starlette's MultiPartParser default
  max_files=1000 (600 works, 1300 → "Too many files" 400; no override in the repo); (3) a
  PROGRESS BAR (imported / estimated-total) + a rule-of-three ETA, able to show a 20GB+
  import in flight; (4) the import must APPEAR IN THE TASK MANAGER and be PAUSABLE; (5)
  PERFORMANCE — slow while hardware doesn't peak (ROOT CAUSE = ingest_emails commits PER
  MESSAGE = fsync/SQLCipher-codec-bound + serialized, NOT CPU-bound); (6) NAMING — clarify
  app-wide that the DB "article count" is articles AND newsletters; coin a unifying term.
  ARCHITECTURE (autonomous, dictated by 20GB+pause): a SERVER-SIDE folder-path import run
  as a pausable background JOB mirroring DumpDownloadManager (persisted state under
  data_dir, worker thread, pause via stop-event + persisted cursor, resume via re-start,
  progress done/total, surfaced in /api/jobs + pause/resume routed in jobs.py). The backend
  ALREADY has ingest_eml_directory()/ingest_eml_files() (unused). ZERO network (local disk
  read — no airplane gate; it IS a DB-WRITER job kind="import", already in the /api/jobs
  arbitration set). KEEP the small-file upload too (Desk lesson) + fix its 400 honestly.
  PERF FIX: batch commits (every N rows, not per-row) + optional bounded parse worker pool.
  NAMING is display-only (the backend stat KEY stays `articles` for API stability; only the
  HOME_STAT_LABELS/Database label changes, ×12). **BOTH OPEN QUESTIONS RESOLVED 2026-06-21
  (maintainer): (1) import mechanism = the SERVER-SIDE folder-path job (confirmed); (2)
  unifying name = KEEP "Article" FOR NOW (no rename — the naming slice is dropped; revisit
  later if asked).** So build the server-side folder job + the small-upload 400 fix + batch
  commits; do NOT change the display label. ADDED ASK (maintainer 2026-06-21, the "replace
  the old faulty ones" workflow): a LIVE "remove imported newsletters" maintenance action
  (reuse `src/backup/artifact.py:_drop_newsletter_articles` logic on the LIVE DB, guarded,
  backup-first nudge) so deleting the faulty set + re-importing clean actually REPLACES them
  (restore is additive-only, so the selective-backup tickbox alone never purges the live
  corpus — this closes the loop).
  **LIVE-REMOVE ACTION SHIPPED 2026-06-21 (branch claude/amazing-tesla-z6bwkm, draft PR #423 onto
  0.09; backend VERIFIED py3.11, frontend BROWSER-UNVERIFIED per fork-3):** `src/ingest/email.py`
  gained `delete_imported_newsletters(session)` (+ `count_imported_newsletters` + the single-source
  `NEWSLETTER_SOURCE_DOMAINS` tuple) — the LIVE analog of the backup-snapshot `_drop_newsletter_articles`:
  finds the .eml + mailbox source ids, deletes their articles AND every dependent row (each mapped
  table with an `article_id` column, via `Base.metadata.sorted_tables`, chunked under the 999-var cap),
  LEAVES the empty source rows (a clean re-import re-attaches), takes the SINGLE-WRITER GATE
  (`write_lock()`), and reconciles the denormalised keyword counters (`backfill_keyword_counters` — the
  bulk DELETE bypasses index_article's per-article counter maintenance, so they'd over-count). The
  article DELETE fires the `article_fts_ad` trigger, so the SEARCH INDEX is cleaned automatically (no
  stale FTS rows = a removed article never reappears in search — proven in the test). API (`src/api/
  ingestion.py`): `GET /api/newsletters/imported-count` (drives the confirm preview + shows the panel
  only when >0) + `POST /api/newsletters/remove-imported` (confirm:true required, 400 otherwise).
  Frontend: a Settings → Newsletters "Remove imported newsletters" panel (visible only when count>0)
  with a "Back up first" button (the encrypted-backup path the uninstall flow uses) + a confirm. NEW
  strings are English-fallback via `t()` (i18n gate stays 100%; keyable in the §4 tail). tests/
  test_newsletter_remove.py (5: removes only newsletter articles+dependents, KEEPS source rows + web
  articles, counters reconciled == live aggregate, FTS cleaned for removed articles via ensure_fts,
  no-newsletter-source = no-op, + a drift guard that the live + backup domain constants AGREE) +
  test_repo_invariants::test_remove_imported_newsletters_live_action.
  **BATCH-COMMITS + UPLOAD-CAP SHIPPED 2026-06-21 (§2.B items 2+5; branch claude/amazing-tesla-z6bwkm,
  draft PR onto 0.09; backend VERIFIED py3.11):** (5, perf) `ingest_emails` committed PER MESSAGE
  (fsync/SQLCipher-codec bound — slow on a 20 GB+ folder while hardware idles); now BATCHES commits
  (every `commit_batch`, default `OO_EMAIL_COMMIT_BATCH=200`). Correctness preserved BY CONSTRUCTION: a
  message is deduped against the DB AND within the uncommitted batch (`batch_keys`), and if a batch
  commit ever races a unique-index collision the batch is REDONE one message at a time (`_commit_one`),
  so a single conflict never drops its batch-mates (NO data loss — the standing rule). Exact dedup tally
  unchanged. tests/test_email_ingest.py (+2: cross-batch dedup with commit_batch=2 == stored 3/dup 1 +
  actually-committed; the autoflush-OFF collision path falls back per-message = stored 1/dup 1, no loss).
  (2, the 400) the upload endpoint hit Starlette's `MultiPartParser` `max_files=1000` default → HTTP 400
  "Too many files" at ~1300; `import_newsletters` is now `async` + parses the form itself
  (`await request.form(max_files=_MAX_UPLOAD_FILES=5000, max_fields=…)`) with an honest "use the folder
  import for a very large set" 400 above the cap. test_repo_invariants::test_newsletter_import_perf_and_
  upload_cap.
  **FOLDER-IMPORT JOB SHIPPED 2026-06-21 (§2.B, the bigger half; branch claude/amazing-tesla-z6bwkm,
  draft PR onto 0.09; backend VERIFIED py3.11, frontend BROWSER-UNVERIFIED per fork-3):** the 20 GB+
  case the upload can't handle. `src/ingest/import_job.py:NewsletterImportManager` is a pausable,
  task-manager-visible DB-WRITER job mirroring the §2.A FolderBackupManager: a worker thread enumerates
  every `.eml` under a SERVER-SIDE folder path, reads them in `_FILE_CHUNK=500` groups (bounds RAM on a
  20 GB+ folder), and imports each group via the batched `ingest_emails` over a gated `SessionLocal`
  session — so it takes the SINGLE-WRITER GATE per batch commit and arbitrates with the scrape (kind=
  "import" joins the `db_writers` set). PAUSE = stop-event (stops between chunks); RESUME is idempotent
  two ways (content-hash dedup is the correctness net + a PERSISTED on-disk CURSOR so progress CONTINUES,
  never re-imports); honest rule-of-three ETA from files-done/elapsed (only once >0). ZERO network (local
  disk read). API (`src/api/ingestion.py`): `POST /api/newsletters/import-folder` (400 bad folder / 409
  already running) + `/import-folder/status` + `/import-folder/{pause|resume|cancel}`. Surfaced in
  `/api/jobs` (`_import_jobs`, kind="import", task-manager cancel=resumable pause / resume routed).
  Frontend: a Settings → Newsletters "Import a whole folder" section (path input + live progress poll +
  pause/resume). tests/test_newsletter_import_job.py (6) + test_repo_invariants::
  test_newsletter_folder_import_job. §2.B is now COMPLETE (live-remove + batched commits + upload-cap +
  the folder-import job).
  **PERSISTED IMPORT CURSOR SHIPPED 2026-06-21 (the flagged §2.B remaining; branch claude/amazing-tesla-
  z6bwkm, draft PR onto 0.09; backend VERIFIED py3.11):** the folder-import resume was IN-MEMORY (a
  `_done` paths set lost on an app restart → a resume re-scanned a 100k-file folder from zero, dedup-safe
  but slow). Replaced it with a small on-disk INDEX CURSOR (`data_dir()/newsletter_import.json` =
  {folder, cursor, total, tally, state}, `state_path` override for tests): the worker advances + `_save`s
  the cursor per `_FILE_CHUNK` (the dest-dir-is-the-durable-progress pattern from FolderBackupManager —
  one tiny atomic write per chunk, never a fragile per-file cursor), and the singleton's constructor
  `_load_persisted()`s an INTERRUPTED run (state running|paused, folder still a dir) back as PAUSED so the
  user resumes it from the task manager / Settings — never silently lost. `cancel`/done CLEAR the state
  file. The cursor counts against the STABLE sorted `_eml_files` order, so even a folder that changed
  under us resumes safely (the content-hash dedup is still the net). tests/test_newsletter_import_job.py
  (+1 `test_persisted_cursor_survives_an_app_restart`: Manager A persists at cursor 3 → a fresh Manager B
  loads it as paused at files_done==3 → resume → done, count==6, state file cleared) +
  test_repo_invariants asserts `_load_persisted`/`_save`/`_STATE_FILE`. REMAINING: human click-through
  (fork-3); key the panel ×12.
  **CONTENT-QUALITY FIX SHIPPED 2026-06-20 (separate from the batch-import overhaul; same .eml
  importer; VERIFIED on the maintainer's real Reuters .eml):** `_strip_html` (src/ingest/email.py)
  leaked CSS from `<style>`, JS from `<script>`, comment fragments (incl. Outlook/MSO conditional
  comments containing `>`, which defeat a naive `<[^>]+>` regex → stray `-->`) and UNDECODED HTML
  entities (`&nbsp;`/`&#8202;`/`&copy;`/`&rsquo;`) into the stored body. FIX: drop `<style>`/`<script>`
  blocks + comments BEFORE the tag strip, then `html.unescape` + strip zero-width chars + collapse
  whitespace; `_extract_body` now falls back to HTML when the text/plain part is EMPTY. Already-
  imported newsletters keep the old junk (re-import to clean — the cleaner body hashes differently,
  so a re-import stores a fresh clean copy, it won't dedup against the junky one). tests/
  test_email_ingest.py::test_strip_html_drops_style_script_comments_and_decodes_entities.
- **SEAMLESS INSTALL + OLLAMA→AI-TAB + LANGUAGE-FIRST FIRST LAUNCH (maintainer field test
  2026-06-20; branch claude/keen-lamport-b4t3rh, draft PR #420 onto 0.09):** THREE rulings —
  (1) move Ollama installation ENTIRELY to Settings → AI (the installer no longer asks for or
  downloads Ollama/models); (2) the installer asks NOTHING — seamless from start to app launch;
  (3) first app launch leads with LANGUAGE SELECTION, not the passphrase. SHIPPING (install.sh):
  choose_components no longer prompts (installs the default core+analysis+compression set;
  OO_COMPONENTS still overrides), make_launcher creates the launcher without asking
  (OO_MAKE_LAUNCHER=0 still opts out), and maybe_setup_ollama is REMOVED from do_install (no
  Ollama install/model-pull/prompt in install; configure_ollama_store_access stays defined +
  test-pinned but uncalled — provisioning is the AI tab's job now). The seamless flow still ends
  at maybe_launch (the app opens). The download-size estimate + uninstall confirmations STAY
  (uninstall is destructive — "don't ask" was about INSTALL). SHIPPING (first launch, unlock.html):
  on a FRESH store (state="fresh") a LANGUAGE step shows FIRST (the 12 native-name choices, RTL-
  aware via OOI18N.setLang which persists oo.lang + translates the page), THEN the create-passphrase
  view (now in the chosen language). ENCRYPTION-BY-DEFAULT IS PRESERVED (non-negotiable): the
  passphrase step is REORDERED after language, never removed — language→passphrase on the pre-DB
  page, then the main app's guided wizard handles sources→first-collect. "locked" (returning) →
  straight to unlock as before. This BUILDS the wizard's deferred encryption-choice/language-first
  flow (#24). Reuses the EXISTING "Choose your language" i18n key ×12 (already shipped for the
  guided wizard — no new key, no locale churn). Enforced by test_repo_invariants.py::
  test_seamless_install_and_language_first_first_launch. ALSO (same PR): the top-bar LLM pill now
  reads "<N> LLM" (count first, no "models"/✓) and CLICKING it opens Settings → AI (the models
  subtab, which re-checks health) instead of only re-checking — openAiSettings(); +1 i18n key ×12;
  test_llm_pill_shows_count_and_opens_ai_settings. REMAINING: the AI-tab Ollama BINARY installer
  (still blocked offline on per-OS checksums) for end-to-end in-app install; consolidate the now-
  redundant guided-wizard language step; the model-store-readable step (was install.sh's job).
- **CHROME REWORK BATCH 2026-06-20 (maintainer rapid field test; branch claude/keen-lamport-b4t3rh,
  PR #420; ALL frontend, BROWSER-UNVERIFIED — node-checked + invariant-guarded):** a run of chrome
  rulings. SHIPPED: (a) the ANALYSIS sidebar tab is REMOVED — analyses run via search (omnibar/
  palette → a spawned analysis window) or by clicking into other tabs; the #tab-analyze PANEL +
  showTab("analyze")/openAnalysisFor/openAnalysisForIds stay (completes the UI-rethink "the empty
  Analysis entry goes away"); test #22 no longer requires data-tab="analyze", test_search_retired
  asserts the nav-item is GONE. (b) the OMNIBAR fills the status-bar width — dropped .omni
  max-width:560px + removed the .spacer div (it now flex-grows); removed the verbose placeholder
  text (.ph span), kept the magnifier + the keyed aria-label. (d) SHIPPED: the Advanced-search
  language field is now a <select> of FULL language names + flags (built from LANGS_12 in JS so the
  autonyms stay native per #15; +1 i18n key "Any language" ×12; test_advanced_search_language_is_a_flag_dropdown).
  (e) SHIPPED: the standalone task-manager (/tasks) status bar is now the SAME header.topbar markup
  as the app (omni search + health/LLM pills + airplane plane-glyph with FILL=offline + language flag
  menu + help), reusing app.css; the old bespoke .tm-head/✈/select bar is gone; omni/help/go-online
  route into the app (the ONE consent popup lives there); test_task_manager_status_bar_and_sessions
  updated to the app-identical bar. (c) SHIPPED: a sticky `.chrome` wraps the topbar + a new `#subtab-strip`; `_relocateSubtabs(name)`
  (called in showTab) moves the active tab's ooSubtabs nav (an-subtabs/ins-subtabs/set-subtabs/
  agenda-views/indices-cats/commodities-cats) INTO the strip JUST UNDER the status bar — moving the
  DOM node preserves its listeners + state; the strip hides on tabs with no facet subtabs; the
  topbar's own position:sticky moved to `.chrome` (one pin, no pixel-guess of the bar height).
  test_facet_subtabs_relocated_to_top_strip. REMAINING refinement: Home card-families (dynamic) + a
  full-width-over-sidebar variant. (f) ADVANCED-SEARCH SORTING by METADATA — BACKEND SHIPPED 2026-06-21
  (brief §2.D, maintainer "important"; branch claude/amazing-tesla-z6bwkm, draft PR onto 0.09; logic
  VERIFIED via standalone repro since src.api.main needs the crypto extra here → test runs in CI):
  `/api/articles` gained `sort_by` (date|source|title|language) + `sort_dir` (asc|desc, default desc) —
  an HONEST metadata ordering, NEVER a relevance/quality score. Threaded through `_query_articles` in
  BOTH paths: the no-query browse path uses SQL `ORDER BY` (text fields via `COLLATE NOCASE` so
  alphabetical is case-insensitive AND matches the FTS path — SQLite's binary collation otherwise sorts
  all capitals before lowercase), the FTS path sorts the fetched rows in Python by the same key
  (overriding relevance only when `sort_by` is set, else relevance preserved). 400 on an invalid
  sort_by/sort_dir. The existing source/date/language/tag FILTERS were already present (per-metadata
  filtering = done; this adds the SORT half). tests/test_search_sort.py (browse + FTS, every field
  asc/desc, default-recency-unchanged; skip-guarded for the no-crypto sandbox, runs in CI). FRONTEND
  SHIPPED 2026-06-21 (browser-unverified per fork-3): the Advanced-search panel gained Sort-by
  (Relevance/recency · Date · Source · Title A–Z · Language) + Order (Desc/Asc) selects; `anParams()`
  appends sort_by/sort_dir (only the Articles list reads them; insights endpoints ignore the extras; the
  card-seeded article_ids path keeps its explicit order). test_repo_invariants::
  test_advanced_search_sort_by_metadata. FILTERED-INDICATOR SHIPPED 2026-06-21 (browser-unverified):
  when any filter/sort is active, `anRunAdvanced` shows a "Filtered" scope chip + a summary
  (`_anFilterSummary`: source/language/date-range/sort) in the analysis window. HONEST REFRAME of the
  brief's "on ALL tabs": the filters are ANALYSIS-SCOPED (they refine the analysis corpus, not Home/
  Markets/etc.), so a global chip would mislead — the honest place is the analysis window where the
  filter applies. test_repo_invariants::test_filtered_indicator_and_tag_autobackfill. (g) SHIPPED: the analysis Articles
  list is PAGINATED — `_anLoadArticles(p,page)` fetches /api/articles by limit+offset (page size 50,
  `total` drives the page count), renders Prev/Next + "Page X of Y" controls BOTH above and below the
  table, loadAnalysis seeds page 0; test_analysis_articles_paginated. PENDING: (h) LLM MODEL DOWNLOAD
  QUEUE (maintainer 2026-06-20): pulling several models at once OVERLAPS visually + starts them all at
  once — make model pulls a QUEUED, task-manager-visible job (like wiki dumps: one at a time, the rest
  queue) with a CANCEL action (ollama /api/pull isn't resumable, so cancel not pause), so the user can
  queue several downloads and manage them from the task manager. ALSO (h2, the AI-tab models UI,
  maintainer 2026-06-20): the Settings → AI model LIST is poorly displayed — make it COMPACT; clicking
  Pull must give immediate visual FEEDBACK; and lift a pulled model OUT of the catalog list INTO a TOP
  section that shows per-model STATUS (Pulling · Queued · Available · Active) + a progress bar. (h)+(h2)
  are one cohesive rework of the Settings → AI subtab + the download queue — build together.
  **MODEL-DOWNLOAD QUEUE + DOWNLOADS SECTION SHIPPED 2026-06-21 (§2.C; branch claude/amazing-tesla-z6bwkm,
  draft PR onto 0.09; backend VERIFIED py3.11, frontend BROWSER-UNVERIFIED per fork-3):** (C1, the queue)
  `src/llm/pull_queue.py:ModelPullManager` — pulls run ONE AT A TIME via a single pump thread; the rest
  QUEUE. Each is cancellable: a queued model is removed, the ACTIVE pull is ABORTED (Ollama's /api/pull
  is NOT resumable, so cancel — never a fabricated pause/resume; invariant #20). Wraps the existing
  `OllamaClient.pull` generator (honest real bytes: status/total/completed/percent); the client is
  injectable for tests. Bad model names rejected (charset + no `..`). API (`src/api/llm.py`): `POST
  /pull/queue` (enqueue) + `GET /pull/status` (active+queue+history) + `POST /pull/cancel`; the old
  streaming `/pull` stays for the single path (Desk lesson). Surfaced in `/api/jobs` (`_model_pull_jobs`,
  kind="model-pull" = a NETWORK job not a DB-writer; active=running+progress, queued with positions;
  task-manager cancel routed). (C2, the AI tab) `pullModel` now ENQUEUES with INSTANT feedback ("Queued
  …") instead of a frozen streaming button, and a new top `#llm-downloads` section polls `/pull/status`
  to show the active pull (Pulling + a `<progress>` bar + status%) + the queued models, each with a
  Cancel button; when the queue drains it refreshes the installed list (a finished pull appears as
  Available/Active) and stops polling. tests/test_model_pull_queue.py (5: one-at-a-time + order,
  cancel-queued, cancel-active-aborts, bad-name, idempotent-enqueue/status — via an injected fake client
  with a release event for deterministic active/cancel timing) + test_repo_invariants::
  test_model_download_queue. REMAINING: human click-through (fork-3); the installed/catalog table
  COMPACTION polish (it's already tabular; the queue+status section was the load-bearing C2 ask); key the
  new strings ×12.
- **BULK LLM TOOLS — UNCAPPED + SKIP-SAME-LANGUAGE + TO-DO COUNT SHIPPED 2026-06-20 (maintainer field
  test; branch claude/keen-lamport-b4t3rh, PR #420; backend py_compile-VERIFIED, frontend browser-
  unverified):** (i) bulk summarize/translate (`/api/llm/bulk`) AND the AI extractor (`/api/ai/
  keywords/extract` + the custom-prompt `run`) NO LONGER CAP at 200/500 — they process the WHOLE
  matched set (`limit<=0` = no cap; the FTS path already materialises the full match = the same
  memory profile as the uncapped export; the run is a visible, abortable task-manager job). Removed
  `_BULK_MAX_ARTICLES` + `_AI_EXTRACT_MAX`. (ii) a TRANSLATE run NEVER translates an article ALREADY
  in the target language (`_is_target_language` via a backend `_LANG_EN` code→name map; unconditional,
  independent of skip_existing; unknown language → never skip on a guess). (iii) the bulk `start`
  event now reports `to_process` (+ `same_language`/`already_done`) = the count that will ACTUALLY run
  the model, shown up front in the UI ("N to translate/summarize · M skipped"). tests/test_llm_api.py
  ::test_bulk_translate_skips_articles_already_in_target_language (+ `_seed_article(lang=)`); existing
  bulk tests stay green (the en fixtures are not same-language as German). The reader's single-article
  summarize/translate is unaffected; synthesis's `_SYNTHESIS_MAX_ARTICLES=20` (a real context-window
  limit) is intentionally KEPT. +3 i18n-fallback strings (to translate · to summarize · skipped).
- **AIRPLANE-BUTTON FLASH PARITY EVERYWHERE SHIPPED 2026-06-21 (maintainer field test; branch
  claude/keen-lamport-b4t3rh, PR #420; frontend, browser-unverified):** clicking the airplane button
  must give the SAME visual feedback everywhere. The app fired a direction-aware full-screen `#net-flash`
  (`.go-on` live-accent / `.go-off` calm-muted, animated by `@keyframes netflash` in the SHARED app.css),
  but the standalone /tasks page only repainted the button on engage-airplane. Added a `flashNet(online)`
  mirroring the app + the matching "Offline — every new network request is refused…" toast to the /tasks
  airplane click (go-off happens there; go-online still routes to "/" where the app's consent + flash
  fire). Other airplane surfaces (net-coach, GUI gallery skins) already reuse the app's `toggleNetwork`,
  so they flash. test_repo_invariants::test_airplane_flash_feedback_is_consistent_everywhere.
- **LAUNCHER ROBUSTNESS + MODELS-EXPORT-BUTTON FIX + REINSTALL-KEEPS-LOGS (maintainer field test
  2026-06-21; branch claude/keen-lamport-b4t3rh, PR #420; bash -n + py_compile-VERIFIED):** (1) desktop
  icon failed to start the app after an OS restart, fixed by reinstall → most likely a venv broken by a
  system-Python change (a venv is tied to its python minor version). `scripts/launch.sh` now activates
  best-effort and, if `open-omniscience` isn't on PATH after activation, prints a CLEAR actionable
  message ("environment looks broken … re-run the installer: <path>/install.sh") and HOLDS the window
  (read -p) instead of exiting cryptically (which made the icon's terminal vanish before the error was
  read). PLUS the `.desktop` `Exec=` paths are now QUOTED (`"$SRC_DIR/scripts/launch.sh" console` +
  the uninstall one) so an install path WITH SPACES can't break double-click launch. (2) ANSWERED the
  maintainer's "does reinstall replace the diagnostics logs?" — NO: install.sh/do_install NEVER touches
  `data_dir()` (`~/.local/share/open-omniscience`, OUTSIDE the code tree where the .jsonl diagnostics +
  corpus + keys live); its only `rm` are old Desk-launcher files + the `.venv` (recreated). data_dir is
  removed ONLY by `--uninstall` AND only after an explicit "Are you sure? Permanently delete…" (default
  no). So reinstalling is safe for logs/corpus/keys. (3) "Download models backup" "doesn't work":
  `models_export` used `default_store()` (readable stores) while `store_status()` detects the PROTECTED
  systemd Ollama store (`/usr/share/ollama/.ollama/models`, owned by the `ollama` user) — so with a
  service-install Ollama the export 404'd or built a near-empty archive while status looked fine. Now it
  refuses HONESTLY with the actionable `store_status().hint` (set OLLAMA_MODELS to a path you own / pull
  a model first) when there are no readable models — surfaced in the button's toast. REMAINING: an
  optional login-autostart (the maintainer expected auto-launch on boot — opt-in, airplane-safe; not
  added silently); make the protected systemd store exportable via a sudo-helper (out of scope now).
- **GUI SHUTDOWN BUTTON SHIPPED 2026-06-21 (maintainer field test; branch claude/keen-lamport-b4t3rh,
  PR #420; backend stdlib-VERIFIED, frontend browser-unverified):** turning the app off needed a
  terminal Ctrl-C — now a status-bar POWER button (`#app-shutdown`) → `appShutdown()` confirms then
  POSTs `/api/system/shutdown {confirm:true}` → `src/safety/shutdown.py:request_shutdown` disposes the
  DB engine (avoids SQLCipher codec-teardown noise) + SIGTERMs self after ~1 s (response flushed first).
  It is NOT uninstall and NOT panic — the data dir/corpus/keys are UNTOUCHED (a regression-guard asserts
  the module contains no wipe/rmtree). A full-screen "shutting down — close this tab" overlay replaces
  the UI. tests/test_shutdown.py (confirm-required + arms-once, `_arm` injected so the test never kills
  the runner) + test_repo_invariants::test_gui_shutdown_button_and_endpoint. **UNINSTALL/SHUTDOWN NOW
  REPLACE THE UI WITH A TERMINAL OVERLAY (maintainer 2026-06-21: after uninstall the browser stayed
  clickable against a dead server — "feels weird"):** a shared `_terminalOverlay(message,{tryClose})`
  (full-screen, z-index 99999, covers the sidebar+tabs so dead tabs can't be clicked) replaces the UI
  when the app stops; both `appShutdown` and `uninstallApp` call it after the server is scheduled to
  SIGTERM. It also attempts `window.close()` — best-effort ONLY (browsers close just script-opened tabs,
  and the launcher opens a normal tab via xdg-open, so close usually no-ops), with the overlay as the
  reliable end-state telling the user to close the window. test_repo_invariants::
  test_uninstall_and_shutdown_replace_ui_with_terminal_overlay. ALSO FIXED the `test` lane
  bandit red (commit 2888e3b): the new backup f-string SQL (`_delete_in`/`_drop_newsletter_articles`)
  tripped B608 (Medium) — added the established `# noqa: S608  # nosec B608 - <reason>` per line (table/
  col validated against `_SAFE_TABLE`; values are bound `?` params), matching merge.py/diagnostics.py.
- **UNIFIED SEARCH NOW SEARCHES WIKIPEDIA ARTICLE CONTENT SHIPPED 2026-06-21 (maintainer field test;
  branch claude/keen-lamport-b4t3rh, PR #420; backend py_compile-VERIFIED, frontend browser-unverified):**
  the omnibar/palette wiki group (`/api/search/omni` `_wiki_group`) matched ONLY watched-page TITLES.
  Now it searches wiki ARTICLE CONTENT: `WikiPage.baseline_text` is stored COMPRESSED (no SQL LIKE), so
  content search runs over the FTS-indexed CORPUS articles produced by the watched-page→corpus sync
  (source domain `xx.wikipedia.org`). `_wiki_group` runs `search_ids` (FTS, ranked), filters the hits to
  Wikipedia-edition sources (`domain LIKE %wikipedia.org`, bounded `_WIKI_SCAN_CAP=2000` chunked scan),
  returns the top 3 as reader links (article_id + `/api/articles/{id}/view`, the edition parsed from the
  domain) with the real total; when NO indexed wiki content matches it FALLS BACK to the watched-pages
  title catalog (prior behaviour preserved — the existing title test still passes). Frontend: a wiki
  item with a `url` opens the LOCAL reader, a title-only item jumps to Settings → Wikipedia. HONEST GAP
  stated: downloaded offline DUMPS are files, NOT full-text-searched yet (the standing remaining item).
  tests/test_search_omni.py::test_omni_wiki_group_searches_wikipedia_article_content (a wikipedia.org
  article found by content → reader link + edition). REMAINING: full-text search over downloaded dumps.
- **SELECTIVE BACKUP — "WHAT TO BACK UP" TICKBOXES + EXCLUDE NEWSLETTERS SHIPPED 2026-06-21 (maintainer
  field test; branch claude/keen-lamport-b4t3rh, PR #420; backend stdlib-VERIFIED, frontend browser-
  unverified per fork-3):** the maintainer curated a corpus incl. faulty .eml imports and wants to back
  up WITHOUT them, then re-import fixed ones to replace the faulty (restore is additive, so leaving the
  bad ones out of the backup + a future clean re-import is the path). DELIVERED the core, reliably: the
  Full-backup UI gains a "What to back up" fieldset — ☑ Articles & corpus data (always) · ☑ Imported
  newsletters (.eml/mailbox, UNTICK to exclude) · Local LLM models (points to the existing SEPARATE
  models backup) · Offline maps · Wikipedia dumps (DISABLED "coming soon" — honest, NOT faked: file-
  member backup needs the ruled-but-unbuilt additive-restore FILE placement, a reliability-critical
  piece I won't ship unverified). BACKEND: `BackupBody.include_newsletters` (default True — no silent
  change) → `write_backup_v2(..., include_newsletters=)` → `_collect_members(...)` runs
  `_drop_newsletter_articles()` on the DISPOSABLE PLAINTEXT corpus snapshot ONLY (never the live DB):
  finds the `newsletters.import.local` + `mailbox.import.local` source ids, deletes their articles AND
  every dependent row (each table with an `article_id` column — verified ALL FKs to articles.id use that
  name, so no orphan survives the restore's foreign_key_check), VACUUMs; the empty source rows are LEFT
  (a future re-import re-attaches). RESTORE NEEDS NO CHANGE (the merge just sees a corpus with fewer
  articles — fully additive-restore-compatible). tests/test_backup_newsletter_filter.py (stdlib-only,
  RAN GREEN here: drops only newsletter articles+dependents, keeps the real ones + non-article tables,
  no-newsletter-source = no-op) + test_repo_invariants::test_backup_can_exclude_newsletters (the UI
  tickbox + the end-to-end wiring). New UI strings English (the backup panel is largely un-keyed
  English; gate stays 100%). REMAINING (the maintainer's fuller vision): maps + wiki-dump backup as
  file members (needs the additive-restore file-placement, ruled-but-unbuilt — build with the wiki-dump
  inclusion together); fold the separate models backup into the same tickbox flow. **SELECTIVE RESTORE
  SHIPPED 2026-06-21 (maintainer reiterated "what to restore: articles/maps/eml/wikipedia/models"):**
  symmetric to backup — the Restore section gains a "What to restore" fieldset (Articles always · Imported
  newsletters toggle · Models=separate restore · Maps/Wiki=not-in-archive). `_apply_restore_selection`
  runs the SAME stdlib-tested `_drop_newsletter_articles` on the STAGED PLAINTEXT corpus copy BEFORE the
  merge — so unticking newsletters restores everything except them, and the PREVIEW reflects the COMMIT
  (the token's staged copy is already filtered at preview time; a direct-file commit filters at commit).
  `restore_preview`/`restore_commit` gain `include_newsletters: bool = Form(True)`; the SPA sends it at
  preview (the token commit inherits the filtered copy). NO merge-engine change (the filter is a pre-merge
  step on the disposable staged copy). test_repo_invariants::test_restore_can_exclude_newsletters.
  REMAINING (restore side): maps/wiki/models restore = when those become backup file members.
  **LARGE-DATA BACKUP ARCHITECTURE DECIDED 2026-06-21 (maintainer AskUserQuestion → "Copy to a folder/
  drive"; BUILD PENDING — this resolves the long-standing "BACKUPS MUST INCLUDE WIKIPEDIA DUMPS" +
  models/maps rulings, which were deferred precisely for this reason):** VERIFIED the current oo-backup-2
  is in-memory + 2 GiB-capped END TO END and browser-delivered — restore does `await file.read()` (whole
  upload into RAM) → `decrypt_bytes(blob)` → `zipfile.ZipFile(io.BytesIO(blob))` with `_MAX_RESTORE_BYTES
  = 2 GiB`; an encrypted backup does `encrypt_bytes(zip_path.read_bytes())` (whole archive in RAM); models
  export does `out.write(srcf.read())` per blob. So it PHYSICALLY cannot carry wiki dumps (enwiki ≈20 GB)
  + maps (planet ≈72 GB) — folding them in would OOM + blow the cap + exceed browser download/upload.
  CHOSEN BUILD (server-side, never the browser): a destination DIRECTORY the user picks (e.g. an external
  drive mounted on the machine) into which the app STREAMS wiki_dumps/ + osm_regions/ + the Ollama model
  store FILE-BY-FILE (shutil.copyfileobj, bounded buffer) with a manifest + sha256 dedup (skip an
  unchanged blob), and a restore that copies them BACK ADDITIVELY (skip-if-present, never overwrite a
  differing local file). Wiki/OSM/model blobs are PUBLIC + re-downloadable ⇒ copied AS-IS (no whole-file
  encryption — that is what makes 100 GB feasible; the encrypted CORPUS backup is unchanged). Skip
  non-`done` downloads (ongoing-downloads-never-backed-up principle). This is a substantial reliability-
  critical build ("entirely reliable or it should not exist"); design points to settle at build: the
  destination-path picker UX (server-side path input, validated, must exist + be writable), free-disk
  preflight, a visible task-manager job over the long copy (pausable), and whether models ride the same
  folder backup or stay the separate `.oomodels` (lean: same folder, one "large data" backup).
  **CONFIRMED 2026-06-21 (maintainer): the SERVER-SIDE destination PATH is approved, and MODELS RIDE THE
  SAME FOLDER backup (one "large data" backup, not the separate .oomodels). Build it fully autonomously —
  no questions.** The full build spec + acceptance criteria live in
  `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-06-21.md` §2.A.
  **SHIPPED 2026-06-21 (branch claude/amazing-tesla-z6bwkm, draft PR onto 0.09; backend VERIFIED py3.11
  — 23 tests; frontend BROWSER-UNVERIFIED per fork-3):** `src/backup/folder_backup.py` is the pure,
  fully-tested CORE (the maintainer's "entirely reliable or it should not exist" bar = the test suite):
  STREAMING ATOMIC copy (`_atomic_copy` = temp `.oopart` + fsync + `os.replace`, so a paused mid-file
  copy never leaves a corrupt dest), NAME+SIZE dedup (models are content-addressed `blobs/sha256-…` so
  same-name ⇒ identical; dumps/maps immutable), ADDITIVE restore (skip-if-present, NEVER overwrites a
  differing local file), free-disk + writable-dir PREFLIGHT, and `collect_items` reading ONLY the
  download managers' DONE state (partials never ride into a backup — a download writes resumably into
  its dest, so only the manager knows what's finished). Public re-downloadable blobs are copied AS-IS
  (NOT whole-file encrypted — what makes 100 GB feasible); the private corpus stays in the encrypted
  oo-backup-2. A `FolderBackupManager` (singleton, one giant copy at a time, worker thread + stop-event
  PAUSE, idempotent RESUME = re-plan + skip already-copied, IN-MEMORY state since the dest dir IS the
  durable progress — no fragile cursor to corrupt). API (`src/api/backup_v2.py`): `POST /folder/plan`
  (preflight: files + needs-X vs Y-free, no start), `/folder/start`, `/folder/restore`, `/folder/status`,
  `/folder/{pause|resume|cancel}`. Surfaced in `/api/jobs` (`_folder_backup_jobs`, kind="folder-backup",
  pause/resume/cancel routed; task-manager cancel = resumable pause like a dump, full cancel in Settings).
  Frontend: a Settings → Data & backup "Large data backup (folder / external drive)" panel (server-side
  path input + wiki/maps/models tickboxes + Check-space preflight + live progress poll + pause/resume +
  a restore-from-folder section); the old "What to back up/restore" wiki/maps "coming soon" rows now
  point to it. The separate `.oomodels` panel STAYS (Desk lesson; models also ride the folder backup as
  the "models" category). NEW UI strings English-fallback via `t()` (i18n gate 100%; keyable in §4).
  tests/test_folder_backup.py (15: collect done-only/skip-partials, model dedup, copy+dedup-on-2nd-run,
  changed-size-recopied, pause-leaves-no-manifest-then-resume-completes, atomic-stop-no-corrupt,
  additive-restore-never-overwrites-local, selected-categories, preflight/validate, manager
  complete/restore/out-of-space/stopped→paused-vs-cancelled) + tests/test_folder_backup_api.py (7,
  minimal-app) + test_repo_invariants::test_large_data_folder_backup. REMAINING: human click-through
  (fork-3); a sudo-helper for the protected systemd Ollama store (out of scope, noted in §4); key the
  panel strings ×12.
- **ONGOING DOWNLOADS
  NEVER BACKED UP (maintainer 2026-06-21, reassurance + transparency):** maps + wiki dumps live in
  `osm_regions/` + `wiki_dumps/`, which are EXCLUDED BY CONSTRUCTION (never collected as members), so a
  partial/in-progress download can never ride into a backup half-written (no corruption). Made the OSM
  maps dir EXPLICIT in `_excluded_inventory` (it listed only wiki_dumps before — maps were silently
  dropped); the manifest now transparently lists both as excluded/re-downloadable. When the file-member
  backup IS built, it must skip non-`done` downloads (the same principle).
- **OFFLINE-MAP TAB — ONE STATE-AWARE LIST + PLANET SKIPS DOWNLOADED SHIPPED 2026-06-21 (maintainer
  field test; branch claude/keen-lamport-b4t3rh, PR #420; frontend, browser-unverified per fork-3):**
  Settings → Offline map had TWO lists (the catalogue with bare Download buttons + a separate jobs
  table) and a Download button gave no state feedback. Now ONE merged list: `loadOsmMap` fetches BOTH
  `/api/geo/regions` + `/api/geo/downloads` (Promise.all) and `_renderOsmList` joins them by `code`, so
  each region row shows its LIVE state — not-downloaded (Download) · queued (Cancel) · downloading (%
  + a `<progress>` bar + bytes, Pause) · paused/error (Resume + Delete) · downloaded ✓ (size + Delete);
  the old `#osm-dl-table` is cleared (merged, nothing lost — all controls moved to the rows). Clicking
  a button gives INSTANT feedback (the button disables + "Starting…"/"Resuming…" before the await; the
  3 s poll then repaints the real state). "WHOLE PLANET" no longer offers the 72 GB monolithic file
  (which cannot skip parts) — its button (`startPlanetDownload`) downloads only the CONTINENTS you don't
  already hold (skips done/downloading/queued), so it NEVER re-fetches downloaded parts (maintainer's
  ask); the planet row shows "N/M continents" or "All continents downloaded ✓". The continent extracts
  together cover the planet, stated in the row hint. test_offline_map_merged_list_state_and_planet_skips_downloaded.
  New strings via t() (English-fallback; gate 100%). REMAINING: per-row reorder ↑/↓ (the task manager
  has it); key the new strings ×12; the monolithic-planet code path is now UI-unreachable (backend
  get_region("planet") still exists, harmless).
- **BULK TRANSLATE/SUMMARY QUEUE + TASK-MANAGER OPTIMISTIC REORDER SHIPPED 2026-06-21 (maintainer
  field test; branch claude/keen-lamport-b4t3rh, PR #420; frontend, browser-unverified per fork-3):**
  (1) QUEUE — a long batch translation blocked starting another. Batch translate/summarize is now a
  client-side QUEUE: `bulkLlmRun` ENQUEUES a job (snapshotting its selection at enqueue, so it targets
  the right articles even after the search changes) + `_bulkPump` runs them ONE AT A TIME (a single CPU
  model can't run them well in parallel; `if (_bulkActive) return`). A persistent `.bulk-queue` panel
  (sibling of the config panel, in BOTH the search + analysis surfaces, so it survives the config panel
  being hidden / the custom-extractor reusing the mount) shows each job (Queued / Running n/N / Done /
  Cancelled / Stopped) with per-job Cancel + Clear finished. Own AbortController (`_bulkJobAbort`) leaves
  the custom-extractor's `bulkLlmStop`/`_bulkAbort` untouched. The Start button → "Add to queue"; the
  panel-level button → "Hide" (never cancels work). test_bulk_translate_summary_runs_are_queued. (2)
  REORDER — prioritising/moving a download in the task manager didn't visibly move the row (it relied on
  the backend round-trip + the next poll). Now OPTIMISTIC in BOTH task managers: `jobMove` (in-app, via a
  new `_paintJobs` render-from-cache split of `_renderJobs`) and `TM.move` (standalone /tasks) renumber
  the cached queue `queue_position` and REPAINT immediately, THEN POST `/api/jobs/{dumps,osm}/reorder`,
  THEN `_renderJobs`/`refresh` to reconcile (revert to backend truth on error). Keys/backend were
  already correct (`_dlKey` == `e['key']`; manager.reorder persists; /api/jobs recomputes queue_position)
  — the gap was purely the missing instant repaint. test_task_manager_reorder_moves_rows_optimistically.
  REMAINING: surface the client-side bulk QUEUE in the backend task manager too (only the ACTIVE run is
  in /api/jobs today); key the new queue strings ×12.
- **SYNTHESIS REWORK — WINDOW + TRANSPARENT SELECTION + UI-LANGUAGE + EXPORT SHIPPED 2026-06-21
  (maintainer field test, 4 messages; branch claude/keen-lamport-b4t3rh, PR #420; backend
  py_compile-VERIFIED, frontend browser-unverified per fork-3):** answers the maintainer's questions +
  fixes the broken output. WAS: "Synthesize results" silently took the TOP 20 FTS-relevance matches
  (the 20 = a context-safety bound `_SYNTHESIS_MAX_ARTICLES`; the 24k-char budget ÷ N excerpts), one
  generate call, rendered INLINE in a small card; a weak model BAILED ("clarify which specific
  article…") or echoed the SOURCE language despite the English `{language}` pin. NOW: (1) opens a roomy
  article-style WINDOW (`<dialog id="synth-window">`); (2) TRANSPARENT SELECTION step — fetches a
  candidate pool (`/api/articles?…&limit=60`, NEW `ids=` param for a card-seeded analysis corpus,
  preserves order, bounded 1000), shows "Matched: M (top R by search relevance)", lists candidates
  with metadata + reader links + checkboxes (first ≤20 pre-checked, live "Selected k/20", Run disabled
  outside 1..20) so the USER picks the members (sent as explicit `article_ids` — no silent truncation
  as the only path); (3) RESULT step shows the synthesis + caveat + provenance chips + the FULL
  synthesized corpus WITH each article's metadata (title/source/date/lang/reader/source↗), "← Change
  selection"; (4) EXPORT — Copy, Export .md (Blob download), "Open as a page ↗" (a standalone HTML doc
  in a new tab, Ctrl-S saveable, falls back to download); (5) UI-LANGUAGE OUTPUT — the SPA sends
  `ui_lang` (code) + `output_language` (English name); `_build_prompting` now appends a NATIVE-language
  directive (`_NATIVE_DIRECTIVE` ×14 langs, e.g. fr "Rédige l'intégralité de ta réponse en français.")
  to the summary/synthesis system prompt so a weak model actually writes in the UI language (the tuned
  ENGLISH instruction BODY is KEPT — translating multi-sentence prompts ×12 risks DEGRADING a weak
  model's compliance; forcing the OUTPUT language is the reliable win, applied to BULK SUMMARIES too);
  (6) ROBUST PROMPT — the excerpts are wrapped "Synthesize ALL N excerpts… do not ask which one…" +
  repeated AFTER the excerpts (small models weight the last instruction), killing the bail. Response
  gains `members[]` (n/id/title/source/published_at/url/language) + `total_matched` + `max_articles`.
  The 20 bound STAYS (a small CPU model can only synthesize a bounded set well) but is now VISIBLE +
  user-controlled, not silent. tests: test_llm_api (member metadata + total_matched; fr native
  directive in system + "Synthesize ALL" in prompt), test_api_search (the `ids=` set, order-preserving,
  drops unknown ids), test_repo_invariants::test_synthesis_opens_a_window_with_selection_metadata_and_export.
  All new window strings via `t()` (English-fallback, i18n gate 100%; keyable later). REMAINING: key
  the window chrome ×12; optionally a persisted/saveable synthesis "document" (today export is the save
  path); full multi-paragraph prompt-body localization if the native directive proves insufficient.
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
  **EIA EXPANSION (maintainer ruled 2026-06-18, chose "expand no-key energy feeds" via
  AskUserQuestion):** EIA (eia.gov) was already an ENABLED RSS source + its WTI/Brent/Henry-Hub
  prices auto-ingest via FRED. Added (a) `us-eia` to the official-statistics agency directory
  (`src/stats/agencies.py` — the raw-data layer, controversial like every producer) and (b) five
  more no-key EIA petroleum-product feeds to `configs/commodity_feeds.yml` (gasoline GASREGW ·
  diesel GASDESW · heating-oil DHOILNYH · propane DPROPANEMBTX · jet-fuel DJFUELUSGULF, all
  EIA-via-FRED key-free CSV, auto-imported by the markets pass = ingested by default). FRED ids
  believed-correct but NOT network-verified here (sandbox 403) → flagged in-file; a wrong id
  fails LOUDLY (dead-series verdict), never fabricates — VERIFY on a networked box.
  tests/test_eia_energy_feeds.py. The full-catalog paths (EIA API v2 = needs the maintainer's
  free key; or the GB-scale bulk files) were the DEFERRED options B/C — revisit if "all data"
  beyond the high-value energy series is wanted.
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
- **LANGUAGE-AWARE KEYWORDS — TRANSLATE, NEVER BLIND (maintainer ruled 2026-06-19):** a
  reader saw top keywords in Arabic they could not read. The REJECTED instinct was a
  blind-by-language FILTER (PR #398 — built then CLOSED: "we shouldn't blind a user from
  foreign language keyword trends"). The RULING: the keyword engine must be LANGUAGE-AWARE
  and TRANSLATE — show every keyword regardless of language WITH its translation (original +
  translation), which also surfaces translanguage concepts; translations bind to keyword
  FAMILIES and GROUPS. Source = VERIFIED Wikidata-QID rings + a TENTATIVE local-LLM fallback,
  flagged (maintainer chose "Wikidata rings + LLM fallback" via AskUserQuestion). PHASE 1
  SHIPPED (PR #399, draft onto 0.09): `equivalence.ring_translation`/`translate_term` +
  `top_terms`/`trending`/`trending_windows` gain `target_lang` (each row annotated with a
  verified `translation` via its ring; absent target = byte-compat default) + the
  `/api/insights/{top,trending,trending-windows}` `target_lang` param; frontend `kwTransHtml`
  renders `original → translation` in the Trends + Home keyword lists (UI language passed
  automatically); +1 i18n key ×12; Arabic+Russian members added to 16 curated rings so the
  complaint resolves today (انتخابات→election …). tests/test_keyword_translation.py +
  test_repo_invariants. PHASE 2 — BREADTH SHIPPED 2026-06-20 (draft PR onto 0.09): the
  maintainer ran the parallel amnesic internet session over the ~586-concept seed list →
  575 generated rings (all 12 langs well-covered, 529 with Arabic). VETTED before commit
  (Wikidata first-search-hit resolution is ~6% wrong here): 35 mis-resolved rings DROPPED
  by hand-review of their members — journals (nuclear-fusion/stem-cells/metabolism/the-library/
  chemistry-a-european-journal/radiation-protection-dosimetry/mutation-research/
  mathematics-genealogy-project), bands/labels (the-police/republic-records/empire-distribution),
  companies (sun-microsystems/autonomy-corporation/eclipse-foundation), films (peace/hostage/court),
  place-names (warsaw/massachusetts/cornwall/farmington), homographs (taxon←tax, oil-painting←oil,
  satellite-virus←satellite, country-music←country, wii, guest-house was KEPT), too-specific
  institutions (parliament-of-the-united-kingdom/indian-national-congress/us-military+naval-academy/
  village-in-india) and Wikidata meta-classes (version-edition-or-translation/world-flora-online/
  geonames) — each confirmed garbage by inspecting en/fr/de members (proper-noun echoes vs real
  translations). 540 concept rings KEPT (science/medicine/tech/history/culture/sport/geography
  + politics) → `configs/keyword_rings_generated.yml` (read by load_rings ALONGSIDE the curated
  file, curated wins on id clash). DELIBERATELY NOT over-dropped (the maintainer's warning):
  valid multi-word concepts (united-nations/solar-system/industrial-revolution/world-war-i/
  cold-war/olympic-games/fifa-world-cup) and Title-cased concepts (atom/electron/cell/brain/
  vaccine/cancer/gmo/coup-d'état) KEPT. tests/test_wikidata_ring_gen.py::
  test_shipped_generated_file_is_clean_and_vetted guards it (>=500 rings, unique ids, every ring
  has a QID + >=2 members, the 35 dropped ids stay absent, core translations resolve). REMAINING
  PHASES: (3) bind translations through families + super-groups in the UI; (4) the tentative LLM
  fallback for keywords in no ring (SHIPPED — see the ai_layer/translate.py entry).
  **CONCEPT-SUPERGROUP SCAFFOLD SHIPPED 2026-06-20 (maintainer ruled supergroups must be durable
  umbrella CONCEPTS — "broader than a ring" — cherry-picked by us to set a trajectory, NOT topics
  of the moment: "FIFA shouldn't be a supergroup!!!"; draft PR onto 0.09):** distilled the 540
  rings into 50 umbrella concept-words (the preliminary exercise) → built a 77-supergroup
  conceptual scaffold across the ~12 domains (politics/economy/energy/climate/agriculture/physics/
  life-sci/medicine/tech/media/culture/history/sport/infrastructure), every supergroup a list of
  cross-language RING ids (not hand-listed language-specific surface terms), so each spans all 12
  languages BY CONSTRUCTION via the super-ring model (`KeywordSuperGroupMember.ring_id`). ALL 540
  rings covered (validated, no typo'd id). `configs/keyword_supergroups.yml` rewritten from the 8
  old TOPIC groups → the concept set. `seed_supergroups` reworked: (a) accepts `rings:` members
  (validated against the live ring set via `ring_meta` — unknown id skipped, never a dead member)
  alongside legacy `members:` families; (b) SAFELY RETIRES the 8 old bundled topic groups
  (Middle East conflict/FIFA World Cup 2026/AI[family-based]/US politics/…) but ONLY when a group
  still holds EXACTLY its originally-seeded members (untouched) — the symmetric inverse of
  "user wins": we only un-seed what we seeded, a user-edited group of the same name is left alone.
  Idempotent (skip-by-name) preserved. tests/test_supergroup_seed.py (ring members validated +
  idempotent/user-edit-wins + retire-only-untouched). TARGET (maintainer): grow rings 540→~2000
  (via `generate_wikidata_rings.py --from-log` — corpus-driven, not absorbing more Wikidata) and
  supergroups 77→~200 as the ring set fills out. REMAINING: the families↔rings↔supergroups
  translation binding in the UI (Phase 3 frontend); the ~200 finer concept cut once rings reach 2000.
  **RING-GAP DIAGNOSTIC DIGEST SHIPPED 2026-06-20 (maintainer-asked "tweak the keyword diagnostic
  logger to optimize the gathering"; draft PR onto 0.09): the gathering→generation loop is now
  gap-targeted + cross-language.** Found two inefficiencies in the corpus-driven path: (1) the keyword
  log carried no ring-coverage view, and (2) `generate_wikidata_rings.py --from-log` seeded ENGLISH-only
  and blindly took the top-N by spread — so `--top 300` mostly RE-resolved the 540 concepts we already
  have, and a concept prominent only in ar/zh/ru was never seedable. FIXES: (a) NEW `_ring_candidates`
  digest in the keyword-diagnostics log (`/api/diagnostics/keywords` stream + the per-language zip
  summary, additive — byte-parity contract intact) = per dominant-signature language, the highest
  article-SPREAD non-entity TERMS NOT yet in any ring (the GAP), excluding stopwords, multi-word concepts
  KEPT, ranked by spread, lowest-coverage language first (the worklist); + `translation_coverage` =
  ring-covered/gated terms (the self-check metric, now in the same export the maintainer already sends).
  Reuses the survivors already built — zero extra DB cost. (b) `wbsearch_url(term, lang)` searches
  Wikidata in the SEED's language (wbgetentities still pulls all 12), `generate` accepts `(term, lang)`
  pairs, and `--from-log` now PREFERS `ring_candidates.by_language` (gap-targeted, cross-language,
  sorted by spread) with a legacy `keywords` fallback for old logs. So a generation pass resolves NEW
  concepts across languages, not the ones we already have. tests/test_ring_candidates_digest.py (gap
  vs ringed/entity/stopword exclusion + coverage + lowest-coverage-first) + test_wikidata_ring_gen.py
  (+5: language-aware search, (term,lang) generate, from-log prefers the digest cross-language, legacy
  fallback). Ruff F/B clean. The from-log digest path closes the self-check loop: export → read
  translation_coverage + the gap → run the generator on the gap → re-measure.
  **FUTURE SELF-CHECK (maintainer-asked 2026-06-19 "mark to question ourself"): before
  hand-expanding the ring concept set further, MEASURE whether it helps — re-run the
  keyword-engine report after a Wikidata batch lands and read its `translation_coverage` (%
  of top keywords that fall in a ring; ~5% pre-batch). If coverage is still low, the SCALABLE
  answer is corpus-driven generation (`generate_wikidata_rings.py --from-log LOG.json --top N`
  over the real keyword-diagnostics log) — coverage that tracks what the corpus actually
  contains — NOT absorbing more of Wikidata (115M items, ~140GB dump, mostly people/papers/taxa
  = wrong shape; against the local-first ethos). Decide "add more concepts vs corpus-driven vs
  LLM-tentative" by the measured coverage delta, not by guessing.**
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
  test_repo_invariants 67 passed. NO backend change. REMAINING: per-render perf on huge corpora (full SVG
  rebuild on slide — could update only the signals layer); 5b (retire #oo-tmap, absorption-gated) +
  embed ooMap on When/Where + Insights.
  **SLICE 5a.2 SHIPPED 2026-06-18 (signal CLICK-TO-DETAIL folded in, so 5b's retire loses nothing;
  PR onto 0.09; FRONTEND-ONLY, BROWSER-UNVERIFIED):** the ooMap signals layer's markers are now
  CLICKABLE → a detail panel (`#oo-coverage-detail`, added below the map) ported FAITHFULLY from the
  temporal map's `showTmapDetail`: kind dot + title + kind pill + confirmed/geocode honesty pills
  (`confirmed`/`unconfirmed·scheduled`/`mentioned·extracted`, `≈ country`/`city`), date · place ·
  country · exact coords · data source, the note, the reference-source extLink, the "Find coverage
  in your corpus" action (reuses `tmapFindCoverage`), AND the "Near in space & time" co-occurrence
  seed — `_ooMapNearby` mirrors `tmapNearby` over the ooMap visible set, keeping the verbatim
  "co-occurrence, not a connection or cause. You judge." caveat (never causal). Each marker gained a
  larger transparent HIT disc (the temporal-map lesson: hollow rings were clickable only on the 1px
  edge) + `data-oomap-sig` index; the visible set is attached to the host (`host._ooSigVisible`) so
  `_wireOoMap` resolves the click; nearby buttons re-enter via the global `_ooMapSignalAt(idx)`
  (app.js is a classic script → top-level fns are global, so the inline onclick + tmapFindCoverage
  resolve). `ooMap` gained `opts.onSignal(s, visible)`; the loader passes the adaptive `windowY` for
  the nearby time threshold. The detail is ENGLISH to MATCH the panel it replaces (no regression vs
  the still-English temporal-map detail; keyable later when that whole surface is i18n-swept). NO
  backend change; +0 i18n keys. test_ooMap_choropleth extended (clickable markers + the ported panel
  + #oo-coverage-detail + _ooMapNearby + the non-causal caveat + find-coverage); node --check, full
  test_repo_invariants 68 passed. ooMap now ABSORBS the temporal map's full capability → 5b (retire
  #oo-tmap, absorption-gated) is unblocked. REMAINING: 5b retire + embed on When/Where + Insights;
  per-slide perf; i18n-key the detail when the temporal-map English strings are swept.
  **SLICE 5b SHIPPED 2026-06-18 (RETIRE the standalone temporal map; PR onto 0.09; FRONTEND-ONLY,
  BROWSER-UNVERIFIED per fork-3):** the maintainer's "fold signals in, THEN retire" reaches the
  retire. ABSORPTION ANALYSIS first proved the split is safe: ooMap fetches its OWN signals
  (`_ooMapSignals` ← /api/timemap, line 7493) — it does NOT depend on `loadTimemap`/`TMAP.signals`;
  and the SHARED helpers (kindColor · TMAP_KINDS · fmtYear · fmtDate · dateToT · TMAP_NEAR_DEG ·
  tmapFindCoverage · lon2x/lat2y) are INTERLEAVED with the temporal-only functions across ~7598–8070,
  so a mass JS deletion is dangerous browser-unverified (a wrongly-removed helper passes node --check
  but breaks the map at runtime). So the SAFE retire: (1) REMOVE the temporal-map `<section>` PANEL
  from index.html (#tab-timemap is now JUST the World coverage / ooMap section — −77 HTML lines) +
  broaden the panel description to honestly cover the absorbed in-map controls (dimensions · continent ·
  places · time signals — English tail, no new keys); (2) REROUTE the tab dispatch `timemap:
  loadTimemap` → `loadOoMapCoverage` (which fetches /api/insights/map-coverage → _renderOoMapDim = the
  full unified map), so `loadTimemap` + the whole temporal block become UNREACHABLE dead code (no active
  caller — verified: only the breadcrumb + its own def reference it); (3) the temporal-only functions
  (renderTimemap / buildTmap* / showTmapDetail / tmapNearby / the onTmap*+zoom/reset/play/mentions
  handlers / wireTmap* / tmap*Prefs / TMAP state) are left in place UNREACHABLE (they null-guard on the
  removed #tmap-* elements) under a RETIRED-(slice 5b) breadcrumb, pending a browser-verified
  DELETION-cleanup PR (the Desk-lesson "made unreachable" bar — chosen over a risky interleaved
  mass-delete). The SHARED helpers STAY (ooMap reuses them). test_tmap_mention_layer (the retired
  surface's test) REWRITTEN → `test_temporal_map_retired_into_ooMap`: asserts the panel/controls are
  GONE, the dispatch routes to ooMap, and every absorbed capability survives (places via
  /api/insights/where + the deduced caveat, the signal click-detail, the in-map slider, tmapFindCoverage)
  — absorption-gated. node --check clean; full test_repo_invariants 68 passed; i18n --min 100 (1316 ×12).
  REMAINING: the browser-verified DELETION-cleanup of the dead temporal functions; embed ooMap on
  When/Where + Insights; per-slide perf on huge corpora.
  **TAB RENAMED "Temporal map" → "World map" 2026-06-18 (the slice-5b finisher; PR onto 0.09;
  FRONTEND-ONLY):** the unified surface is no longer "temporal" only (choropleth + signals + slider +
  places), so the tab is renamed across ALL 5 display touch-points — the sidebar nav `<span>`, the
  Ctrl-K palette registry entry, the two investigate.html "Open the … map" suggestions, and the
  section comment — plus the i18n KEY renamed "Temporal map" → "World map" across all 12 locales with
  translations (en World map · fr Carte du monde · de Weltkarte · es Mapa del mundo · pt Mapa-múndi ·
  ru Карта мира · ar خريطة العالم · zh 世界地图 · ja 世界地図 · hi विश्व मानचित्र · bn বিশ্ব মানচিত্র · id Peta dunia;
  AI-drafted, flagged for native review — but "World map" is a very common term, high-confidence). The
  backend `src/timemap/` module name + docstring stay (internal; renaming the module is out of scope).
  i18n --min 100 unchanged (1316 ×12 — same key count, renamed in place); node --check; the 5b
  absorption test still green (it asserts the old `Temporal map <span` h2 is gone — now there is no
  "Temporal map" text anywhere, a stronger guarantee). REMAINING for the map rework: the dead-code
  deletion cleanup (browser-verified) + the When/Where·Insights ooMap embed.
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
  deliberately BRICS/Africa/forgotten-regions producers) ingested as DISABLED
  sources like any other (the "controversial" verdict was REMOVED 2026-06-19,
  ruling #50 — see the shipped-log entry; a producer is a stanced source stated
  as a descriptive caveat, the user judges, NO verdict label) — producing state +
  agency + publication date + methodology ref on every figure; VINTAGES stored
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
- **2026-06-23 MANIPULATION CARD #4 — FLOOD + the foundational KeywordMention.source_id DENORMALISATION (Q8;
  branch claude/nice-davinci-bqufft, draft PR #447 onto 0.09; backend VERIFIED py3.11 venv):** the flood half
  of card #4. FOUNDATION FIRST: `KeywordMention` denormalised observed_on/country from the source but NOT
  source_id, so a per-source topic-share test would hit the keyword_mentions→articles content-decrypt trap
  over millions of rows. Added a denormalised `KeywordMention.source_id` (model + migration d6e7f8a9b0c1 off
  head c5d6e7f8a9b0 — single-head verified; index; boot self-heal `ensure_keyword_mention_source_column`
  add-only with NO multi-million-row backfill — set FORWARD in index_article like observed_on/country, so a
  re-index populates an existing corpus). `src/analytics/concentration.py:find_flooded_topics` then reads
  source_id ONLY (km-only queries, no content decrypt): per source with enough recent + prior articles, a
  TWO-PROPORTION z-test of its recent share of a keyword vs its OWN prior share. HONESTY: the comparison is
  the source's OWN history (a source that always covers a beat heavily doesn't flag — no jump = no z); the
  signal carries its COMPONENTS (z, share_now, baseline_share, counts) — `share_zscore` is a sanctioned
  statistic, NOT a banned composite (no _BANNED_FIELD_FRAGMENT); a minimum prior sample degrades to silence;
  the innocent twin "volume isn't importance" is stated; bounded. Wired as a fail-safe-LAST producer
  (`flooded_topic` → an `overtold` Home Lead) + `GET /api/insights/flooded-topics` (cached). tests/
  test_concentration.py (5: fires on a flood, silent when consistently-high / thin-baseline / below-min-share,
  no-score+caveat) + the all-producers sweep + store/counters regression (the new source_id wiring doesn't
  break index_article). ruff F/B clean. The BURY half (under-covering vs an external trigger) is the
  follow-on; coverage grows as the corpus is re-indexed (source_id is forward-filled).
- **2026-06-23 MANIPULATION CARD #3 — MANUFACTURED EMERGENCE (full anchor-gated form, ruling Q7; branch
  claude/nice-davinci-bqufft, draft PR #447 onto 0.09; backend VERIFIED py3.11 venv):** the 4th manipulation
  card (after #6 source-laundering, #1 recycled-claim, #7 headline-body). `src/analytics/emergence.py:
  find_manufactured_emergence` names a STRUCTURE never intent: a keyword with ≈0 prior history (prior-period
  distinct-article count ≤ max_prior) that appears RECENTLY across MANY DISTINCT SOURCES ("born wide" —
  independence is sources, NEVER article count, so a chatty single source can't manufacture it). The maintainer
  approved the FULL version WITH the ANCHOR GATE (Q7): it fires ONLY when the emergent articles cite NO datable
  primary anchor (no ArticleMentionedDate within anchor_lookback_days of the onset) — so genuine breaking news
  (which leaves a datable trace) is SUPPRESSED, making it precision-biased instead of firing on every big story.
  HONESTY: real measured COMPONENTS (prior_count≈0, recent_sources, recent_articles, anchored=False) never a
  blended score; the anchor gate biases toward silence; the innocent twin + the FALSE-NEGATIVE caveat ("a missing
  anchor may just mean we didn't ingest the trigger or the extractor missed the date") travel with every item;
  bounded scan. Wired as a fail-safe-LAST producer (`manufactured_emergence` → a `rising` Home Lead over the
  exact article set) + `GET /api/insights/manufactured-emergence` (cached). tests/test_emergence.py (5: fires on
  new+wide+unanchored, silent when anchored / single-source / not-new, no-score+caveat) + the all-producers
  card-shape sweep. ruff F/B clean. NOTE: "born-wide ratio β=day1/peak" is the documented refinement (left to a
  follow-on; the prior≈0 + distinct-source breadth + anchor gate is the honest core).
- **2026-06-23 §2.6 — OFFLINE SECONDARY/DEDUCED LANGUAGE DETECTION (maintainer ruling Q3; the count-reducing
  half; branch claude/nice-davinci-bqufft, draft PR #447 onto 0.09; backend VERIFIED py3.11 venv):** articles
  the source/extractor left untagged (notably .eml) extracted under the English working-assumption stoplist,
  so a genuinely FOREIGN one leaked its function words as keywords (the "?"-language bucket). `src/analytics/
  langdetect.py:detect_language` deduces the language OFFLINE (py3langid — pure-Python, bundled model, ZERO
  network; added to the `[analysis]` extra so a core install simply gets None, gated like VADER). HONEST by
  construction: it NEVER guesses (None for <200 chars, confidence <0.90, or a language OUTSIDE the app's
  SUPPORTED set — a Korean article is detected `ko`, which we can't analyse, so it stays honestly unknown
  rather than force-fit), deterministic, full model + accept-only-if-supported. SECONDARY/DEDUCED metadata
  (Q3): a NEW `Article.detected_language` column (migration c5d6e7f8a9b0 off head b4c5d6e7f8a9 — single-head
  verified; + `ensure_article_detected_language_column` boot self-heal, no backfill) is set ONLY when the
  authoritative `language` is absent and NEVER overwrites it (the two-class asserted-vs-deduced model). In
  `index_article` a `known_lang` = (asserted || deduced || None) now drives extraction (right stoplist),
  sentiment, AND the keyword's analytic language — so an untagged French article: `language` stays None,
  `detected_language="fr"`, its keywords are labelled `fr` (OUT of the "?" bucket), and its function words
  (dans/avec/pour/entre/des) are FILTERED instead of minted (proven end-to-end). tests/
  test_language_detection.py (4: detect en/fr/short→None/empty→None/ko-unsupported→None; untagged-foreign→
  deduced+right-stoplist; authoritative-never-overwritten; unknown-stays-None — the lib-dependent ones
  importorskip py3langid so the core-only lane skips them). ruff F/B clean. REMAINING: surface
  `detected_language` as "deduced" in the reader/lists (frontend follow-on); measure the live-corpus "?"-
  bucket reduction after a re-index.
- **2026-06-23 §6 — /api/articles EXPOSES STORED SENTIMENT (branch claude/nice-davinci-bqufft, draft PR
  #447 onto 0.09):** the `Article.sentiment_score`/`sentiment_label` columns are populated at ingest/
  re-index (VADER English-only) but the article-LIST endpoint never returned them, so the analysis Articles
  list + search results couldn't show tone without an extra /api/framing call. Added both fields to BOTH
  `/api/articles` serialisation paths (the `ids=`-seeded + the query path) — honest: null for non-English /
  not-yet-re-indexed articles, NEVER a fabricated neutral. Backend-only; the frontend tone display is the
  follow-on (the inline-dup-badge pattern shows the lists can annotate rows). test_repo_invariants::
  test_articles_endpoint_serialises_stored_sentiment (both paths carry it); ruff clean. The endpoint-level
  test needs the app/crypto (CI-only); existing /api/articles tests pass with the additive fields.
- **2026-06-23 MANIPULATION CARD #7 — HEADLINE-BODY MISMATCH (§6, ruling #13; branch claude/nice-davinci-
  bqufft, draft PR #447 onto 0.09; backend VERIFIED py3.11 venv):** the 3rd of the nine manipulation-pattern
  cards (after #6 source-laundering + the near-dup recycled-claim), built to the maintainer's documented
  spine (FUTURE_DEVELOPMENTS card #7). `src/analytics/headline_body.py:find_headline_body_mismatch` names a
  STRUCTURE never intent: per RECENT article, lexical divergence `d_lex = 1 - |H ∩ B_top| / |H|` (the
  headline's content UNIGRAMS H vs the body's top unigrams B_top — same extractor for both, so LANGUAGE-
  AGNOSTIC, works in every language the extractor supports) + an English-only headline-vs-body VADER
  sentiment gap `Δs` (None for non-English — never a fabricated neutral, the standing B1 disclosure).
  Fires when `|H| >= min_headline_terms` AND (`d_lex >= d_min` OR `Δs >= gap_min`) — a DIVERGENCE card
  (bucket `debunk`), so it fires per-article (the convergence "no single-signal" gate is for the cross-source
  coordination cards, not this one). HONESTY by construction: the signal carries its COMPONENTS (lexical_div,
  sentiment_gap, lang, the exact absent headline terms), NEVER a blended "clickbait score"; the innocent twin
  (a summarising/metaphorical headline does exactly this) is stated beside the pattern; precision-biased
  (strict d_min=0.67 + min 3 headline terms, so a punchy 1-word headline never trivially fires); bounded
  (recent pool, body capped at 8000 chars — its lead carries the salient terms). DESIGN CALL recorded:
  H/B_top restricted to UNIGRAMS — a title bigram rarely appears verbatim among the body's top terms even
  on-topic, which would inflate d_lex (a match case dropped 0.5→0.125 with unigrams = far below threshold,
  far fewer FPs). Wired as a fail-safe-LAST producer (`headline_body_mismatch` → a `debunk` Home Lead over
  the exact article, article=corpus-of-1) + `GET /api/insights/headline-body-mismatch` (cached). tests/
  test_headline_body.py (7: fires on divergence, silent on an on-topic headline, thin-headline-never-fires,
  sentiment English-only, item carries components+no-score, bounded-to-recent, producer emits a valid
  debunk Card) + the existing all-producers card-shape/_trigger sweep covers it automatically. ruff F/B
  clean; headline_body.py 0 mypy errors.
- **2026-06-23 P0 §3.1 — INGEST-UNDER-PARALLEL-LOAD WRITER-GATE REGRESSION TEST (branch
  claude/nice-davinci-bqufft, draft PR #447 onto 0.09; logic VERIFIED py3.11, the pytest version runs in
  CI py3.13):** the 2026-06-22 audit confirmed the single-writer gate (keystone #1) covers every write
  path and the 149 `database is locked` errors predate the do_orm_execute fix (#384) — but the corpus runs
  up to ~50 PARALLEL collect workers against one encrypted writer and the EXISTING data-loss proof
  (test_write_gate_dataloss.py) raced `import_points` (market data) against a single Article store, NOT the
  full `index_article` keyword/When-Where-Who sub-writes + denormalised-counter deltas under many concurrent
  ingests — the exact production shape, and newly relevant since §2.5 touched the extraction path. Added
  `test_parallel_index_article_loses_no_keyword_or_date_rows`: 6 workers × 15 articles each ingest +
  index_article concurrently against the real gated `SessionLocal`, all sharing a coined SENTINEL keyword
  + natural keywords + the date "15 September 2024" so those counter deltas + that date row are written
  under MAXIMUM contention. Asserts ZERO dropped rows (90 articles, 90 date rows, the sentinel has exactly
  90 mentions) and EXACT denormalised counters on the SENTINEL (article_count==mention_count==90). KEY
  LESSON (CI caught it on the macOS portability lane FIRST, then the blocking Linux lane — the P0-5 reason
  to investigate observation lanes): the first draft asserted the counter==join invariant for EVERY keyword
  in the DB, which reddened on `france` (article_count=2, 0 mentions) — drift another test DELIBERATELY
  injects into the SHARED test DB; the ledger's own rule "never assert positive facts against the shared
  mutable singleton" applies. FIXED: the exact-counter proof uses a coined sentinel keyword no other test
  touches (pollution-free), and the natural-keyword check is MY-article-scoped (`article_id.in_(my_ids)`).
  No `database is locked`, no deadlock, no gate leak. CANNOT run in the py3.11 sandbox (the file imports src/database/write.py which uses
  a PEP 695 `def f[T]()` generic = py3.12+ only — the documented CI-covers-it limit), so the LOGIC was
  proven against a file-based WAL engine wired with the REAL gate handlers (register_write_gate): 90/90
  articles + dates, exact counters, ZERO drift, 3.0s, no errors. ruff F/B clean.
- **2026-06-23 KEYWORD REDUCTION §2.5 — DIGIT-HEAVY CODE-TOKEN EXTRACTION FILTER (the next lever on the
  ~400k keywords; branch claude/nice-davinci-bqufft, draft PR onto 0.09; backend VERIFIED py3.11 venv):**
  the 2026-06-23 live log (27,303 articles / 406,723 keywords) showed a ~35k bucket of alphanumeric CODE
  tokens (A-10C, internal ids, model-variant cruft, clock timecodes 1h15) minted as junk keywords —
  "NOT yet filtered at extraction." HONEST FINDING that shaped the design: they CANNOT be separated from
  real digit-bearing terms by a digit RATIO — the maintainer's OWN keep/drop examples (`a-10` keep vs
  `a-10c` drop) are shape-identical modulo a trailing letter, and "mostly digits" applied literally drops
  `a-10`/`f-18` (the must-keeps). The discriminator that WORKS is the count of letter<->digit TRANSITIONS:
  a real designation keeps its digits in ONE run (a-10, f-18, covid-19, g7, g20, cop26, b52, mp3, web3,
  x86 = exactly 1 transition), a code ALTERNATES (a-10c, a1b2, x1y2z3 = >= 2). `src/analytics/extract.py`:
  `_alnum_transitions` + `_is_code_token` (drop >= 2-transition tokens) wired at the ONE extraction
  chokepoint — the `_terms` unigram + n-gram filters AND `_entities` (so an A-10C-style code is not
  preserved as a fake acronym either). The handful of REAL multi-transition terms (influenza subtypes
  H1N1/H5N1…, the marker A1C) are an allowlist `_CODE_TOKEN_KEEP` — exactly the _ACRONYM_STOP /
  _PLURAL_DENYLIST pattern, tunable from the diagnostics logs; `OO_CODE_TOKEN_FILTER=0` disables. PLUS a
  CONSERVATIVE glued-digit-prefix catch in the unigram loop: a digit-bearing token glued immediately AFTER a
  digit in the source (1h15 -> h15, 3a4b -> a4b) is always a tokenizer split of a larger code (real prose
  space-separates numbers) — this catches the clock-timecode fragments that are single-transition and so
  invisible to the transition rule. TOKEN-LEVEL (no text mutation) ⇒ clean-text first-offsets stay EXACT
  (the strip_markup contract). HONEST SCOPE stated: this does NOT catch single-transition `letterN` tokens
  (b52/mp3-shaped) because they are shape-identical to real designations — a re-index drains the catchable
  ones and the rest surface in the next log for the loop. **§2.6 UNDERSCORE-IDENTIFIER EXTENSION (same
  commit/PR):** `_is_code_token` ALSO drops any token containing an `_` (gd_combo_table — the maintainer's
  named "?"-bucket CSS/template junk; font_family; utm_source) — NO natural orthography in any of the 12+
  supported languages uses a word-internal underscore, so it is false-positive-safe for real WORDS (a
  natural phrase splits on its space); the one common real underscore term `x86_64` is allowlisted. This is
  the safe, log-free, dependency-free half of §2.6 (the count-reducing language-detection half stays gated
  on the live log + a dependency decision). tests/test_keyword_code_tokens.py (hard keep/drop
  fixture proving NO real term is lost: keepers incl. flu subtypes + x86_64 survive, digit-codes + underscore
  identifiers drop, env kill-switch,
  end-to-end index_article stays clean + counters consistent) + 2 in-app self-test golden cases
  (digit_code_tokens_dropped + clock_timecode_fragments_dropped, so a regression reddens the maintainer's
  exported keyword self-test AND CI). 90 keyword/analytics/selftest/extract tests + 122/125 repo-invariants
  green (the 3 non-greens are the py3.11-vs-py3.13 `[T]`-generic parse + package-metadata env gaps, not the
  change). ruff F/B clean; extract.py adds 0 mypy errors. MEASUREMENT TOOL SHIPPED (same PR): the
  keyword-engine report's `_extraction_noise` audit gained a `code_token` class (using the live
  `_is_code_token`) that counts how many EXISTING keywords the next re-index will drop — so the maintainer
  measures the PROJECTED §2.5/§2.6 reduction in the same report they already export (tests/
  test_keyword_engine_report.py +1). REMAINING §2.5: measure the real reduction on the live corpus after a
  re-index (the maintainer's loop); single-transition `letterN` junk stays unfilterable by shape (honest limit).
- **2026-06-22 FIELD-TEST REMAINDER — WORLD LAW AUTO-SCRAPE WIRING (§5 #18, the auto-scrape half; branch
  claude/trusting-maxwell-p7y2g8, draft PR onto 0.09; backend VERIFIED py3.13):** the World-law tab was
  empty (law_track 0 docs/baselines) because legal documents are tracked ONLY in `mode=="law"`, never in the
  default rss collect pass — the SAME gap markets had before its per-pass auto-load. `src/law/track.py:
  auto_track_due` = a BOUNDED, freshness-gated, round-robin batch (default 5 docs/pass, min_interval 24h,
  least-recently-checked first via `last_checked_at` NULLs-first) wired into the scheduler's post-pass
  housekeeping (runner.py, after the market auto-load), gated by `auto_track_law` (getattr-default True,
  mirroring `auto_import_calendars`). So watched legal docs (registered `watched=True` from configs/legal.yml)
  build baselines + surface changes over time WITHOUT hammering legal sites — per-host politeness + robots
  fail-closed + the kill switch (airplane) all ride the shared fetcher; best-effort (one bad doc never aborts
  the pass). tests/test_law.py::test_auto_track_due_is_freshness_gated_and_bounded (bounded/round-robin/
  freshness; an UNWATCHED doc is never fetched). REMAINING for #18 (the larger halves): the per-country legal-
  source catalog for every UI language (a languages→countries map + curated sourced portals, large hand-
  curation — the configs/legal.yml set today is ~30 portals, mostly anglophone/EU) + the tab's full content-
  first revamp (data-dense, version-tracking UI). These are separate, larger builds.
- **2026-06-22 FIELD-TEST REMAINDER — CUSTODY DISSOLVED FROM THE SIDEBAR (§5 #20, structural half; branch
  claude/trusting-maxwell-p7y2g8, draft PR onto 0.09; frontend BROWSER-UNVERIFIED per fork-3):** "Evidence &
  custody" is an ACTION on content, so it leaves the (now flat) sidebar — completing the Trust-group
  dissolution started by #22 — and moves to Settings → Safety (a `showTab('custody')` button, mirroring the
  earlier integrity dissolution). DESK LESSON honored: the `#tab-custody` page + all its tools (saveCustody,
  the post-quantum/OTS controls) stay, reachable from Settings + the command palette (custody stays in NAV).
  test_repo_invariants::test_custody_dissolved_from_sidebar_but_reachable_from_settings. The flat sidebar is
  now home/insights/timemap/law/agenda/indices/markets/library. REMAINING for #20: the crypto-UI
  "make it foolproof" simplification (plain-language controls + #oo-tip detail) — a separate UX rework.
- **2026-06-22 FIELD-TEST REMAINDER — FLAT SIDEBAR + REMOVE SIDEBAR-VISIBILITY (§4 #22 + #17 part; branch
  claude/trusting-maxwell-p7y2g8, draft PR onto 0.09; frontend BROWSER-UNVERIFIED per fork-3):** the sidebar
  section headers (Investigate/Collect/Trust .gl labels + .nav-group wrappers) are GONE — one FLAT list
  (`nav.nav-groups.flat`), same order, all tabs present + reachable (invariant #2 intact; also via the
  command palette). The outdated "Tools shown in the sidebar" checklist (#17) + the whole hide-a-tab
  visibility feature are removed: `dr-modules` host gone, `toggleModule` gone, `ui.hidden` dropped from
  UI_DEFAULTS + the applyUi nav-item-hiding/group-collapse logic + the buildDrawer checklist build all
  removed (a legacy `ui.hidden` in stored prefs is simply ignored). The collapse-to-rail control STAYS (a
  different feature). NOT in this slice (noted): #20 custody→Settings move (custody stays in the flat list
  for now); #17's "fuse Appearance + GUI into one section" (a larger Settings reorg). test_repo_invariants::
  test_sidebar_is_a_flat_list_without_section_headers. ALSO fixed the CI BLOCKER from the #23 commit:
  test_sources_tab_moved_into_settings asserted the `sources` onShow line VERBATIM, which #23 changed by
  adding loadSrcFacets() — rewritten to assert each onShow call individually (so adding a load never reddens
  it again). LESSON: run the FULL test_repo_invariants after a frontend change — a line an invariant asserts
  verbatim can break even when the new feature's own tests pass.
- **2026-06-22 FIELD-TEST REMAINDER — SOURCES MULTI-SELECT FILTERS (§5 #23; branch
  claude/trusting-maxwell-p7y2g8, draft PR onto 0.09; backend VERIFIED py3.13, frontend BROWSER-UNVERIFIED
  per fork-3):** Settings → Sources filters converted from single text inputs to multi-select DROPDOWNS fed
  by a cheap facets endpoint. Backend: NEW `GET /api/sources/facets` (distinct languages/countries/types/tags
  + real counts via ONE column-projected query over the ~3.2k-row sources table — never the N+1 article load,
  cheap on the encrypted store; counts only, no score) + multi-value filtering on BOTH list endpoints
  (`/api/catalog/sources` the table + `/api/sources/` the picker): country/language/source_type/tag accept
  COMMA-SEPARATED values, OR WITHIN a filter, AND ACROSS filters, + `tag_mode` any|all; `/api/catalog/sources`
  filters in SQL BEFORE pagination (so a filter spans the whole catalogue) and country values still normalise
  (FR/France/fr). Single-value calls stay backward-compatible. Frontend: four `<details class="msel">` native-
  disclosure checklist dropdowns (no fragile positioning/click-outside JS), filled by `loadSrcFacets`, option
  labels localised to full names via ooLangName/ooRegionName (#19), tag any|all toggle, free-text search kept;
  theme-aware `.msel` CSS (all 17 themes). tests/test_source_facets_filters.py (5) + test_catalog_sources.py
  (+2 multi-select) + test_repo_invariants::test_sources_have_multi_select_dropdown_filters. New UI strings
  English-fallback via t() (gate 100%). REMAINING: human click-through (fork-3); key the new strings ×12.
- **2026-06-22 FIELD-TEST REMAINDER — TASK-MANAGER SHOWS THE ACTUAL STRATA (§5 #5; branch
  claude/trusting-maxwell-p7y2g8, draft PR onto 0.09; backend VERIFIED py3.13, frontend BROWSER-UNVERIFIED
  per fork-3):** the Queue preview claimed "stratified by language and tag" but never SHOWED the strata.
  `plan_preview` now emits `strata` = {languages:[{key,n}], tags:[{key,n}], sampled, note} derived from the
  bounded `rows` sample it ALREADY fetches (ZERO extra query — /api/scheduler/activity is the hot poll, so
  NO unbounded SELECT DISTINCT was added, per the brief's perf caveat); the counts are real, the
  ·unknown/·untagged buckets are the SAME ones `stratified_interleave` uses (extracted to shared module
  helpers `_source_lang`/`_source_tag`), and the honest "a rotation, re-randomised every pass, not a fixed
  queue" note travels with it. Frontend: both the in-app task manager (app.js) + the standalone /tasks page
  render language/tag chips with counts under "Up next this pass". tests/test_collection_activity.py (real
  counts, blank-tag bucketed) + test_repo_invariants::test_task_manager_displays_actual_language_and_tag_strata.
  HONEST SCOPE: the sample is the highest-priority due sources (a representative glimpse, stated), not the
  whole 3,200-source catalogue.
- **2026-06-22 FIELD-TEST REMAINDER — DEAD CALENDAR FEEDS EXCLUDED FROM AUTO-IMPORT (§7; branch
  claude/trusting-maxwell-p7y2g8, draft PR onto 0.09; backend VERIFIED py3.13):** the per-pass
  `auto_import_due_feeds` round-robin included the ~238 robots-disallowed `google-hol-*` (calendar.google.com)
  + 16 `webcal.guru` feeds, and because "google-hol-*" sorts BEFORE the working "wph-*" ids, the round-robin
  attempted ~254 GUARANTEED-DEAD feeds (each costing a robots fetch the fail-closed fetcher refuses) for
  many passes, STARVING the 239 working WorldPublicHoliday feeds. Added `_AUTO_IMPORT_SKIP_HOSTS`
  (field-verified robots-disallowed hosts, recorded in configs/calendar_feeds.yml's header) and skip them
  in the due-list build. RECONCILES the "stays-listed-with-honest-verdict" choice: `load_families` is
  UNTOUCHED — the feeds stay in the directory, the UI shows their honest verdict, the operator can still
  verify/import them manually; only the AUTOMATIC round-robin skips them (never a fabricated verdict — each
  is the host's own robots choice). tests/test_calendar_autoimport.py (the dead hosts stay listed but are
  never auto-fetched; the working wph host IS reached). REMAINING (networked machine): replacement FRED ids
  for the dead gold/silver/sawnwood commodity series; raw.githubusercontent.com calendar feed is robots-
  UNDETERMINED (not confirmed-disallowed), so left in the round-robin (the backoff handles it).
- **2026-06-22 FIELD-TEST REMAINDER — BOOT-COLD CACHE WARM (§1.3 read-path tail; branch
  claude/trusting-maxwell-p7y2g8, draft PR onto 0.09; backend VERIFIED py3.13):** the in-memory insights
  read cache is empty after a restart, so the FIRST Home/Insights open paid the cold whole-corpus
  aggregation (warm_cache runs after a scrape pass, but boot is AIRPLANE mode -> no pass; a user who boots
  + stays offline still hit the cold query). `run_deferred_startup` now kicks `warm_cache` in a DAEMON
  thread (non-blocking, best-effort, zero network — the same local DB read moved off the first click;
  its own session created inside the thread), gated by OO_NO_SCHEDULER so tests/headless skip it.
  test_repo_invariants::test_startup_warms_the_insights_cache. The tl-decoupling (non-English UI recomputes
  the aggregation per language because the cache key includes `tl`) stays a DEFERRED follow-up: a clean
  decouple risks REDUCING translation coverage (the cached untranslated payload lacks the `stored_lang`
  fallback map `_annotate_translations` uses for rows without a stored language) — a correctness risk
  not worth taking for a single-user-modest perf win; flagged in src/api/insights.py:warm_cache.
- **2026-06-22 FIELD-TEST REMAINDER — KEYWORD-ENGINE & DATE-VOCAB BATCH (the §3 brief tail; branch
  claude/trusting-maxwell-p7y2g8, draft PR onto 0.09; backend VERIFIED py3.13 venv).** Two slices:
  (1) **NO_STOPLIST TAIL → MANAGED.** Promoted 14 languages to `MANAGED_LANGUAGES` after verifying each
  tokenises WHOLE words (empirical 2026-06-22) + giving each a pure-grammar stoplist: fa/ur (Arabic
  script), uk (Cyrillic, the gated 2026-06-18 set expanded), ro/cs/sk/ca/sw/az/et (Latin), tr/fi
  (stoplists already present, just promoted), bs/hr (share the sr-Latin stoplist already in the union).
  COLLISION DISCIPLINE: distinct-script langs are collision-free by construction; Latin additions are
  length>=4 / accented-only so a content-word clash in es/it/pt/en/de/nl is impossible (hand-excluded
  ro"cine"/sk"bola,bolo"/ca"sense,fins"/sw"wake,sana,kama" etc.). TOKENIZER: `_WORD_RE` gained Arabic
  combining marks (`_ARABIC_MARKS`) as word CONTINUATIONS (additive — undiacritized text byte-unchanged,
  proven; only JOINS a diacritized word a mark would split, like the Devanagari/Bengali fix). th (Thai)
  → UNSEGMENTED (no inter-word spaces + Mn vowel marks shatter it — a stoplist can't fix segmentation,
  honest); vi stays no_stoplist (syllable-segmented — "kinh tế" splits). 12 NON-VACUOUS selftest cases
  added (content noun survives + >=3-char grammar filtered; selftest now 39/39). tests/
  test_arabic_tokenizer.py (additivity) + updated test_managed_languages/test_keyword_engine_report/
  test_stopword_candidates (tr/uk were the no_stoplist examples → swapped to vi/th).
  (2) **DATE VOCABULARY.** uk Cyrillic months (nominative+genitive+locative, distinct from the Latin-
  derived ru set), et-specific months (jaanuar/veebruar/märts/aprill/juuni/juuli/oktoober/detsember),
  ur Arabic-script months (Urdu letters ک/ی → distinct strings from the Arabic set) all added to
  `_MONTHS`; vi "tháng N" NUMBER patterns (`_VI_DMY_RE`/`_VI_MY_RE`/`_VI_DM_NOYEAR_RE` — vi months are
  numbers, not names); th Thai-script months (`_TH_MONTHS`) with Buddhist-Era→CE conversion (`_be_to_ce`,
  BE floor 2200; CE years kept; Thai/Eastern-Arabic digits parse via \d). A month/number only fires next
  to a day/year, so recall rises without inventing dates from prose. tests/test_dateextract_more_languages.py.
  mypy 126<=127, ruff F/B clean. REMAINING (the live-corpus / networked-machine items): orphan-prune +
  tag-backfill RUNS on the live corpus; ring generation (Wikidata 403); zh/ja segmentation decision;
  the remaining Latin no_stoplist langs await the exported per-language keyword log (the maintainer's loop).
- **2026-06-22 SESSION — POST-MERGE CONTINUATION (PR #439 merged; new draft PR onto 0.09, branch re-cut from
  the merged 0.09 per protocol). SERVER-SIDE FOLDER PICKER (brief #8, "Browse buttons, never manual path
  typing"; backend VERIFIED py3.13, frontend BROWSER-UNVERIFIED per fork-3):** the folder-backup destination
  + the .eml folder-import took a server-side path the user had to TYPE (a browser file dialog can't return a
  host path). NEW `src/api/files.py` `GET /api/fs/list?path=&show_hidden=` lists a directory's SUBDIRECTORIES
  only — NEVER file contents, never even file names — traversal-safe by construction (`_safe_resolve` →
  real abs path; an unreadable dir lists nothing; a non-existent/non-dir path falls back to home, never a
  500), bounded `_MAX_ENTRIES=2000`, reports `writable` so the picker can gate a backup destination. Loopback-
  only single-user app, consistent with the existing local trust model (the unlock screen already lists
  key-file names). Wired into the spine (`_wiring.py`). Frontend: a reusable `ooFolderPicker(inputId,
  requireWritable)` + `#folder-picker` dialog (delegated row navigation via addEventListener, native
  showModal focus-trap) + a "Browse…" button beside `fb-dest` (folder backup) and `nl-folder` (.eml import).
  New strings English-fallback via `t()` (i18n gate stays 100%; keyable later). tests/test_fs_browser.py (6:
  folders-only/hidden/parent/fallbacks/bounded) + test_repo_invariants::test_server_side_folder_picker_wired
  + test_api_wiring (router in the spine). **ALSO #10 ENCRYPTION AUTO-DETECT ON RESTORE (frontend, same PR
  #441):** the backend already detects the OOENC1 magic + raises a clear "passphrase required" — so the fix
  is CLIENT-SIDE: `v2DetectEncryption()` reads the chosen file's FIRST 8 BYTES locally (no upload-to-check,
  `f.slice(0,8)`) and shows the passphrase field ONLY for an encrypted backup (a plaintext archive needs
  none), with an honest "Encrypted/Plaintext" hint; degrades to showing the field on any read error. The
  magic bytes match read_artifact's exact signature. test_repo_invariants::
  test_restore_auto_detects_encryption_client_side. **FLAKY-TEST FIX (caught by the macOS observation lane;
  it would flake the BLOCKING Linux lane too):** `test_summary_flags_a_lock_error_in_the_current_session`
  (shipped #439 P0-5) hardcoded the error's `at`="12:00" but `note_boot()` stamps the REAL wall clock — so it
  passed only when the suite ran before noon UTC (Linux 11:08 ✓) and failed after (macOS 13:27 ✗). Fixed to a
  far-future `at` (unambiguously "this session" at any run time). LESSON: never compare a hardcoded timestamp
  against a real-`now` marker in a test. REMAINING (the larger backups redesign #7/#9/#11/#12):
  unify the include/restore selection UI, encryption-as-an-in-flow EXPORT option, direct-import-with-summary,
  progress bars both directions, restore-as-a-task-manager-job (P0-2 slowness folds here).
- **2026-06-22 AUTONOMOUS SESSION (the field-test brief `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-06-22.md`;
  ONE branch claude/keen-davinci-jvsmfh per the harness git-constraint, draft PR onto 0.09; backend VERIFIED
  py3.13 venv, frontend BROWSER-UNVERIFIED per fork-3). HONEST FINDING on P0-1 (the headline "data is locked
  data-loss"): the 149 `database is locked` errors in the bundle are dated 2026-06-17 — they PREDATE the
  `do_orm_execute` single-writer-gate fix (writer.py, merged 2026-06-18 in #384). Audited every write path:
  the gate is registered on SessionLocal + covers ORM flush AND bulk DML; busy_timeout=30000 on every pooled
  connection; the raw writers (maintenance VACUUM/ANALYZE, email, store, FTS rebuild) all take write_lock or
  run pre-scheduler; migrate.py only touches staged files. So P0-1's specific storm is ALREADY closed; the
  maintainer believed it live because the bundle captured a STALE error window (exactly P0-5's warning).**
  SHIPPED anyway as warranted defence-in-depth + the trustworthiness fix that lets the maintainer SEE it's
  closed:
  - **P0-1 defence-in-depth (data-loss class):** `index_article`'s when/where/who block RE-RAISES a lock
    error instead of swallowing-without-rollback (the swallow poisoned the final commit → the scheduler's
    "transaction has been rolled back … Original exception was: database is locked"); non-lock WWW errors
    stay swallowed (a bad date parse must never cost the article its keywords). The two best-effort ingest
    sub-writes (`_maybe_index_keywords` → idempotent index_article; `_maybe_index_links` → rebuild-rows
    work) now run through `run_write_with_retry`, so a transient lock (gate disabled / a restore FTS rebuild
    racing the live engine) RETRIES instead of dropping data; an exhausted lock still degrades gracefully
    (logs, never breaks ingestion). Past-session losses recover via the existing backfill/reindex paths.
    tests/test_ingest_index_retry.py (3: retry recovers keywords, exhausted-lock-doesn't-break-ingest,
    non-lock-WWW-keeps-keywords).
  - **P0-5 trustworthy diagnostics:** `errorlog.install()` now writes a session-start BOOT marker, and
    `errorlog.summary()` reports records/first_at/last_at/last_session_started_at + problems_total/
    problems_this_session + locked_errors_total/**locked_errors_this_session** — wired into the debug bundle
    as `error_log`. So a future bundle answers "is the data-loss happening NOW?" directly (a clean current
    session reads `locked_errors_this_session: 0` even while the file still holds an old session's errors).
    tests/test_errorlog_summary.py (5).
  - **P0-5 reindex hammering:** the Insights status poll (every 6 s) re-kicked a fresh re-index drain on
    every tick (1,326 `/api/insights/reindex` calls / 369 s, each a heavy write contending with the scrape).
    `autoIndexInsights` now runs ONE bounded pass (<=40 batches, was 500) then COOLS DOWN (60 s; Infinity on a
    drained or genuinely-stuck backlog), so the poll can't storm the writer. test_repo_invariants::
    test_auto_index_insights_is_throttled_not_a_per_tick_storm. node --check + ruff F,B clean.
  - **P0-2 restore UNIQUE-collision + honest error (the maintainer's OWN backup failed to preview):** ROOT
    CAUSE = the merge dedup key for `article_mentioned_dates` checked `snippet` instead of `precision`, but
    the real UNIQUE is `(article_id, mentioned_on, precision)` — so an incoming date row with the same
    date+precision but a different snippet passed the NOT-EXISTS guard then violated the constraint
    ("UNIQUE constraint failed: article_mentioned_dates.article_id, mentioned_on, precision"). Fixed `md_key`
    to match the constraint EXACTLY + switched to `INSERT OR IGNORE` (belt-and-braces against an old backup
    whose own table predates the constraint and carries dups; `_insert_tracked`'s rowid watermark still
    counts only landed rows). Places/entities aren't merged verbatim (only dates were), so the collision was
    isolated to this one table. Also FIXED the misleading classification: a constraint clash was reported as
    "may be from an incompatible version" — `backup_v2._restore_error()` now distinguishes a `sqlite3.
    IntegrityError` (data-merge conflict, not a version issue) from a real schema gap (no such table/column),
    both still JSON (never a plain-text 500). tests/test_merge_dates_collision.py (2: deduped-article
    same-date-precision-diff-snippet no longer crashes + local kept; an incoming corpus with its own dup
    date rows merges via INSERT OR IGNORE). The slowness half (236 s/preview) folds into the P1 import/export
    redesign (restore as a task-manager job). mypy 126≤127, ruff F,B clean, torture suite 10/10 green.
  - **P0-3 empty Home despite ~7,800 articles:** Home was NOT a blank div — `renderBriefing` already renders
    the honest "No Leads yet" empty state and `loadHome` already has independent per-section try/catches (a
    slow `trending-windows` can't blank it). The real cause: the briefing cache (`briefing_cache.json`) is
    refreshed ONLY by the scheduler post-pass, but the app BOOTS IN AIRPLANE MODE (scheduler idle), so a
    cache built when the corpus was tiny (or from a rolled-back pre-gate pass) left Home empty forever —
    `get_briefing(force=False)` returned it verbatim. FIX: `refresh_briefing` records the corpus size
    (`article_count`) in the cache, and `get_briefing` recomputes ONCE when the corpus has grown materially
    since (`_is_cache_stale`: grew ≥25 AND ≥10%); a stable corpus still reads the cache instantly (bounded,
    so no per-poll churn even if producers genuinely yield 0 cards — the new cache records the current size).
    tests/test_briefing_stale_cache.py (3: stale-logic, recompute-a-stale-empty-cache, fresh-cache-served-
    verbatim). Backend-testable; the producers-genuinely-fire question can't be reproduced without the live
    corpus, but a stale cache was the load-bearing cause (boot-airplane + the pre-gate pass rollbacks).
  - **P0-4 read-path perf — the warm-cache key mismatch (NOT a rollup):** MEASURED first (the ledger's own
    "measure EXPLAIN before adding a drift surface"): on a synthetic PLAINTEXT 600k-mention corpus the covering
    index `ix_mention_date_keyword` is used optimally (`SEARCH … USING COVERING INDEX`, one `_counts(30d)` =
    0.1s, full `trending_windows` ~1s). So the field's 18s is the SQLCipher PER-PAGE DECRYPT of the index
    range scan — the query plan is already optimal, and a per-day rollup's benefit is data-distribution-
    dependent + UNMEASURABLE without the live encrypted DB ⇒ NOT built (respects the no-speculative-drift
    caution). THE REAL BUG: `warm_cache` warmed `trending-windows` with `limit=10` and NO `tl` param, but the
    UI requests `limit=4&series_top=4` (Home) / `limit=8&series_top=5` (Insights) and the endpoint key ALWAYS
    includes `tl` — so the warm value matched NOTHING and the user paid the cold decrypt every TTL expiry.
    FIX: `WARM_TRENDING_HOME=(4,4)` + `WARM_TRENDING_INSIGHTS=(8,5)` constants; warm_cache warms those exact
    keys with `tl=None`, so after each scrape pass the English Home/Insights trends are a cache HIT (cost
    moved off the request path). tests/test_insights_cache.py corrected (it had codified the broken limit=10
    key) + test_repo_invariants::test_warm_cache_keys_match_the_trending_windows_requests (greps app.js so the
    shapes can't silently drift again). REMAINING (follow-ups, not blocking): the cost is still cold on
    boot-airplane (no pass yet) + for a NON-English UI (the `tl`-keyed cache recomputes per language — decouple
    the cheap translation annotation from the expensive aggregation cache); the per-day rollup stays the next
    lever IF measured insufficient on the real corpus (EXPLAIN/time it on the live DB first).
  - **CI FIXES (caught by the PR's own CI on the slices above):** (a) mypy +2 from slice 1 (errorlog min/max
    over Any|None → typed `list[str]`; diagnostics `len(payload["errors"])` → a typed local) — now 126≤127;
    (b) `_restore_error` broadened version-detection to include "migration"/"incompatible" (a "staged
    migration failed on an ancient corpus" IS a version issue — test_restore_preview_robust_errors expects
    "incompatible version"); (c) test_briefing_stale_cache.py used positional/bare write_text/read_text →
    `encoding="utf-8"` (test_utf8_file_io hygiene). The macOS "Portability observation" lanes are
    observation-only (not blocking).
  REMAINING P0: P0-2 restore slowness (→ P1 backups job) — folds into the import/export redesign. P0 core
  reliability + perf complete; next: P1 keyword-engine quick wins, then the backups redesign.
  - **P1 KEYWORD ENGINE — hi/bn made GENUINELY functional (deeper than the brief's "stoplist" ask):** the
    engine report flagged hi (Hindi) + bn (Bengali) — UI languages — as `no_stoplist`. INVESTIGATING revealed
    the real defect is the TOKENIZER, not a missing stoplist: `_WORD_RE` excluded Indic combining marks
    (matras/viramas are Unicode Mn, not `\w`), so "सरकार" split at the ा matra into "सरक"+"र" — Hindi/Bengali
    keywords were MANGLED. A stoplist alone would have been dishonest (promoting a broken language to managed).
    FIX (additive, byte-safe for other scripts): `_WORD_RE` now allows Devanagari (U+0900-0903/093A-094F/
    0951-0957/0962-0963) + Bengali (U+0981-0983/09BC/09BE-09CD/09D7/09E2-09E3) marks ONLY as word
    CONTINUATIONS — Latin/Cyrillic/Greek/Arabic tokens use none of these codepoints, so they're unchanged
    (proven). THEN added hand-filtered pure-grammar hi/bn stoplists to `_EXTRA_STOPWORD_TEXT` (distinct
    scripts ⇒ collision-free global union) and promoted hi+bn to `MANAGED_LANGUAGES`. zh/ja STAY unsegmented
    (a stoplist can't fix missing segmentation — honest). Verified the whole loop: सरकার/জনগণের now extract
    whole, ≥3-char grammar (लिए/नहीं/করেছে/জন্য) is stoplist-filtered, all 27 keyword self-test cases pass
    (was 25/27 — the 2 new hi/bn cases assert a content noun survives = non-vacuous). tests/
    test_indic_tokenizer.py (6) + 2 selftest cases. ruff/mypy clean; 62 extraction/keyword/managed tests
    green. REMAINING keyword-engine (need the live corpus / a networked machine, per the brief): run the
    orphan-prune + tag-backfill on the 7.8k corpus (existing tools/buttons); grow rings via
    generate_wikidata_rings.py --from-log (corpus-driven); the other date-gap langs (uk/vi/et/th/ur) + CJK
    年月日 depth.
- **KEYWORD-COUNT REDUCTION + RING-LOOP (2026-06-21, maintainer "reduce the ~500K keywords / download rings
  through diagnostics to auto-improve the engine"; branch claude/magical-brown-49m9nd, draft PR onto 0.09;
  backend VERIFIED py3.11 harness, frontend BROWSER-UNVERIFIED per fork-3):** the honest read recorded —
  ~500K keywords is mostly JUNK (markup tokens + unmanaged-language function words + merge-orphans), NOT
  legitimate rare terms, so the reduction is junk-REMOVAL (aligned with the no-arbitrary-cap policy), not a
  cap. SHIPPED: (1) MEASURE — `engine_report._mention_distribution` adds a `composition.mention_distribution`
  block (zero_mention [prunable orphans] · single_article · by-mention tiers 1/2-5/6-50/51+) from the cheap
  denormalised counters, so the 500K is explainable before cutting (the existing `_extraction_noise`
  markup/elision/digit classes already quantify the markup share). (2) GC — `store.prune_orphan_keywords`
  deletes keywords with NO `KeywordMention` rows (authoritative anti-join, not the maybe-stale counter) —
  pure cleanup (every view reads mentions/counters, which are 0 for an orphan), CURATION-SAFE (a
  normalized_term referenced by a family override / super-group member is KEPT), takes the single-writer
  gate, chunked under the 999-var cap, deletes KeywordTag dependents. The intended workflow = re-index (the
  §3.F force re-index drains markup via `strip_markup`) → prune (the now-zero-mention markup keywords GC away).
  `POST /api/insights/prune-keywords` + a Settings → Diagnostics "Prune unused keywords" button (confirm +
  status). tests/test_keyword_counters.py +3 (prunes only mention-less, keeps curated orphan, distribution
  surfaces the bucket) + a static invariant. (3) RING LOOP — recorded, no redundant build: the keyword
  diagnostics zip ALREADY carries the cross-language `ring_candidates` gap digest and
  `generate_wikidata_rings.py --from-log` ALREADY consumes it, so the loop is export-log → run generator on a
  NETWORKED machine (Wikidata 403 in-sandbox) → I vet (the ~6% first-hit-wrong rate makes auto-trust degrade
  quality — never auto-merge) + commit + re-measure `translation_coverage`. A live in-app Wikidata importer
  stays the candidate-review design from the 2026-06-21 chat (consented/airplane-gated/guarded factory/
  task-manager job, candidates not auto-trusted). i18n: +2 keys ×12 (Prune button + hint; non-en AI-drafted,
  flagged), gate 100%, audit untranslatable held at 105.
  **FOLLOW-UP 2026-06-21 (maintainer "proceed" on the pre-test prep offer; same branch, new draft PR onto
  0.09):** (1) ONE-CLICK CLEANUP — a "Clean up keywords (re-index, then prune)" button chains the recommended
  order in one action (`cleanupKeywords` reuses confirm-free cores `_reindexAllLoop`/`_pruneCore`, also used
  by the two granular buttons which STAY); +2 keys ×12 (button + title), gate 100%, audit held at 105;
  test_repo_invariants extended. (2) `docs/testing/LEGAL_DECLINE_UNINSTALL_TEST.md` — throwaway-VM steps for
  the first-launch legal **decline = SECURE uninstall** path (irreversible: wipes data+keys+folder via
  `request_uninstall(confirm,remove_folder,wipe_data)`), incl. the non-destructive `GET /api/safety/uninstall/
  plan` dry-run, the typed `UNINSTALL` confirm, the surviving `~/.open-omniscience-uninstall.log`, and the
  accept-path sanity. PRE-TEST CHECKLIST handed to the maintainer in chat: run cleanup on the live corpus +
  measure via the engine report's `mention_distribution`; browser click-through of the fork-3 unverified
  surfaces; check live `trending-windows` timing (rollup only if still slow); export the keyword log for the
  ring+stoplist round; manual Ollama install for AI features; the VM decline test.
- **INSTALL NETWORK-RESILIENCE (2026-06-21 field test — a Qubes disp VM curl|bash install died with a
  MISLEADING pip "ResolutionImpossible / regex no matching distribution"; branch claude/magical-brown-49m9nd,
  draft PR onto 0.09; bash -n + test VERIFIED):** ROOT CAUSE was a NETWORK/DNS dropout mid-resolution
  (`Temporary failure in name resolution` / `Read timed out` for files.pythonhosted.org), not a real
  dependency conflict — pip's default 15s timeout made it backtrack through every nltk/networkx/lxml version
  then blame `regex`. `install.sh:pip_install` now uses `--retries 5 --timeout 60`, retries the whole
  `pip install -e` step up to 3× with backoff (cached wheels resume), and on persistent failure prints an
  HONEST network message (check `getent hosts files.pythonhosted.org`; re-run, wheels are cached) instead of
  echoing pip's confusing resolver error. tests/test_installer.py::test_pip_install_is_network_resilient.
  Immediate user fix handed over: re-run `./install.sh --unattended` once DNS resolves.
- **FIELD-TEST REMAINDER BATCH 5 (2026-06-21, branch claude/magical-brown-49m9nd, draft PR onto 0.09 —
  the autonomous-session brief's §2/§3 remainder; backends VERIFIED py3.11, all frontend
  BROWSER-UNVERIFIED per fork-3):** SHIPPED, each its own slice: (§2.3) OFFLINE-MAP per-row reorder —
  queued OSM region downloads now show their queue position (#N) + ↑/↓ controls in the Settings list
  (`osmMove`, optimistic renumber+repaint then `/api/geo/downloads/reorder`); `osm_downloads.list()`
  now exposes `queue_position`. (§2.6) OPT-IN LOGIN AUTOSTART — `install.sh setup_autostart` gated on
  `OO_AUTOSTART=1` (default off; never silent): Linux XDG `~/.config/autostart` entry, macOS
  LaunchAgent, both launching `launch.sh console`; safe because boot is airplane (zero network);
  uninstall removes it; `test_login_autostart_is_opt_in`. (§2.5) GUIDED-WIZARD language step DROPPED
  (`_GW_STEPS=["finish"]`) — redundant after the #420 language-first first-launch + the permanent
  top-bar switcher; the lang DOM/`_gwRenderLangs` stay unreachable (Desk lesson). (§2.4) WIKI-DUMP
  TITLE SEARCH — `dumpread.search_titles` = a bounded, case-insensitive substring scan of the
  multistream index (scan_cap + capped/scanned reported); HONEST scope = TITLES only (page BODIES are
  not full-text-searched — decompressing every bz2 block per query is out of scope, stated in the
  note); `GET /api/wiki/dumps/search` + a "Search titles" button in the Settings dump-reader (NOT the
  per-keystroke omnibar — a multi-million-line scan must never run interactively). (§3.F) DISCOVERABLE
  FORCE RE-INDEX — `store.reindex_all_batch` (paged FORCE re-index of ALL articles, not just
  un-indexed, last_id cursor + done) + `POST /api/insights/reindex-all` + a Settings → Diagnostics
  "Re-index the whole corpus" button (loops batches, confirm, visible progress) — the drain for stale
  metadata an old engine produced (pre-markup-strip CSS keywords); summaries/translations untouched;
  tests/test_keyword_counters.py +2 (paged + counters-stay-consistent). (§2.1) i18n — audit-chrome
  untranslatable 110→105 (realigned the drifted "One file carries everything" key + keyed the two
  Synthesize title attrs, the Source-name placeholder, the scaling-benchmark hint; "Search titles" +
  the re-index strings keyed too); gate 100% (1598 ×12); non-en AI-drafted, FLAGGED for native review.
  (§2.2) ASSESSED no-op: the ACTIVE bulk run is already surfaced in the task manager (llm.py
  register/update/finish with done/total); the BROWSER-only bulk queue would require backend SHADOW
  STATE, against the tasks.py no-shadow-state principle — deliberately not built. Static invariant
  guards added for each frontend slice. REMAINING (§3 gated on the maintainer's live corpus / a
  networked machine + §4 decisions): trending-windows per-day rollup ONLY if the covering index proves
  insufficient on the real 2.4M-mention DB; persisted columnar (httpfs crypto-extension packaging);
  the Ollama binary installer (per-OS checksums); CJK segmentation; no_stoplist stoplist growth from
  the exported log; human click-through of every frontend slice.
- **FIRST-LAUNCH LEGAL-ACCEPTANCE GATE + LEGAL DOCS ×12 UI LANGUAGES (2026-06-21, maintainer-asked
  "translate all legal information into all UI languages" + an install accept/decline flow; branch
  claude/quirky-goodall-86u3ex; SHIPPED via PRs #425/#426/#428/#429/#430, ALL MERGED to 0.09;
  mechanism backend-VERIFIED py3.11, frontend BROWSER-UNVERIFIED per fork-3):** THREE maintainer
  rulings (AskUserQuestion): (a) DECLINE = confirm-then-UNINSTALL (typed `UNINSTALL`, reuses
  `src/safety/uninstall.request_uninstall` SECURE mode — venv/launchers/app-folder removed + data&keys
  wiped); (b) translations AI-DRAFTED, FRENCH AUTHORITATIVE (flagged for native review); (c) the gate
  lives in the FIRST-LAUNCH GUI (`unlock.html`) BETWEEN language and passphrase, reusing the merged
  `/api/legal/consent` gate — the bash installer stays seamless (no legal prompt there).
  MECHANISM: `src/legal/documents.py` = per-language loader (`docs/legal/<lang>/*.md`; the FRENCH
  canonical `docs/legal/*.md` is the FALLBACK, so the gate worked in all 12 from day one) + chrome
  strings (en/fr built-in, others `docs/legal/<lang>/ui.json`; the typed-confirm word is the
  language-neutral ASCII "UNINSTALL", never localized input) + `build_download_zip` +
  `perform_decline_uninstall`. `src/api/legal.py`: GET `/documents`, GET `/download` (.zip), POST
  `/decline` (requires confirm AND word==UNINSTALL → uninstall). `/api/legal/` added to
  `ALLOWED_WHILE_LOCKED` (unlock.py) since the step runs PRE-DB. `unlock.html`: a `view-legal` step —
  SAFE in-page markdown render (escape-first; links shown as TEXT, no navigation away), Download, a
  required "I accept" checkbox → Accept (records consent + advances to the passphrase), or Decline →
  typed-UNINSTALL confirm panel → uninstall + a terminal overlay. `CONSENT_DOC_VERSION` 0.draft→1.0-draft.
  GPLv3/C3 honesty: declining conditions USE of this build, NOT the GPLv3 code grant (re-install/fork
  always possible) — stated in the docs. TRANSLATIONS: all 4 user-facing docs (MENTIONS_LEGALES · CGU ·
  POLITIQUE_DE_CONFIDENTIALITE · CHARTE_USAGE) + ui.json in en·es·pt·de·id·zh·ar(RTL)·ru·hi·bn·ja (fr
  canonical); markdown structure / `[À COMPLÉTER]` placeholders / statute refs / email / GPL preserved;
  up-links got one extra `../` for the subdir depth; each file carries a top machine-translation +
  French-authoritative note. THE SUB-AGENT TRANSLATION ROUTE FAILED HERE (each agent context-starved by
  this giant CLAUDE.md → produced nothing) ⇒ translations were authored DIRECTLY, ~2 langs/PR.
  tests/test_legal_documents.py (documents/download/decline endpoints + the locked allowlist + an
  unlock-flow static guard) + a 12-language completeness sweep (each native + ui-complete + UNINSTALL
  preserved). REMAINING: human click-through + a real decline test in a throwaway env (fork-3); the
  docs' `Version:`/`Date:` stay `[À COMPLÉTER]` (maintainer finalizes + bump `CONSENT_DOC_VERSION` to
  match); native review of the 11 non-fr translations.
- **FIELD-TEST FOLLOW-UP BATCH 3 (2026-06-21, branch claude/amazing-tesla-z6bwkm, draft PR #427 onto
  0.09 — the maintainer asked to "continue until the end / address EVERY item"; finishes the brief's
  build queue):** per-item shipped notes live in their own ledger entries; this is the roll-up.
  SHIPPED: §2.B FOLDER-IMPORT JOB (pausable DB-writer, reuses batched ingest_emails — entry above) ·
  §2.C MODEL-DOWNLOAD QUEUE + AI-tab downloads section (entry above) · §2.D FILTERED-INDICATOR (analysis-
  scoped chip — entry above) · §3.H one-time silent baseline-tag AUTO-BACKFILL when the Keywords explorer
  opens empty (auto-index #21 pattern; `_kxAutoBackfilled` guard, local/idempotent/no-network; the
  explicit "Apply baseline tags" button stays) · §4 i18n TAIL (26 new this-session strings keyed ×12 —
  folder-backup/restore + newsletter-remove + folder-import + model-downloads + the filtered indicator;
  non-en AI-drafted, FLAGGED for native review; gate 1537 ×12 = 100%). VERIFIED-NO-CHANGE: §3.G month
  vocab already complete for all 12 UI locales (only zh/ja missing = the deferred CJK segmentation; no
  safe speculative stopword additions without the maintainer's exported log) · §3.I polling backoff
  already engaged everywhere (`_adaptivePoll` on both chrome polls + the /tasks `loop()` adaptive).
  Backends VERIFIED py3.11 (import-job + pull-queue tests); all frontend BROWSER-UNVERIFIED per fork-3.
  REMAINING (genuine polish/focused-session work): persisted import cursor across app restart; the
  installed/catalog table COMPACTION; human click-through across the new surfaces; key any longer
  English-fallback panel paragraphs.
- **FIELD-TEST FOLLOW-UP BATCH 4 (2026-06-21, branch claude/amazing-tesla-z6bwkm, draft PR onto 0.09 —
  the maintainer's "proceed with everything you can continue, then list all remaining"; the last
  in-sandbox-buildable polish):** SHIPPED (each its own entry above, this is the roll-up): (a) the §2.B
  PERSISTED IMPORT CURSOR (resume survives an app restart — entry above; backend VERIFIED py3.11);
  (b) a determinate `<progress>` bar on the .eml folder-import UI (driven by the existing status poll's
  percent); (c) §4 i18n — 54 more clean single-text-node chrome strings keyed ×12 across THREE batches
  (the large-data folder backup/restore panels + the backup/restore "What to back up/restore" selection
  fieldsets + the newsletter-remove panel + the §2.D "Sort by"/"Order" sort controls + the markets
  Page/CSV/RSS/Proxy URL·Currency·CSS-selector labels + the diagnostics download buttons + Synthesis/
  shutdown/When-Where-Who), so audit-chrome untranslatable 166→110, gate 1591 ×12 = 100% (non-en
  AI-drafted, FLAGGED for native review). VERIFIED-NO-CHANGE (assessed, no code): §2.C installed/catalog
  table COMPACTION is genuinely cosmetic (already tabular; the load-bearing queue+status section shipped
  in #427) — skipped as a low-value browser-unverified change. The ~110 remaining audit strings are
  data/examples/proper-nouns (stay literal) + the inline-`<a>/<b>`-tagged help paragraphs (the heavier
  de-tagging slice). All frontend BROWSER-UNVERIFIED per fork-3. THE BRIEF'S BUILD QUEUE IS NOW EXHAUSTED
  of in-sandbox-buildable items; what's left is human click-through + live-corpus measurement + genuine
  focused-session features (the final remaining list handed to the maintainer in chat).
- **TRENDING COVERING INDEX (brief §3.E, the #1 perf hotspot; branch claude/amazing-tesla-z6bwkm,
  draft PR onto 0.09; backend VERIFIED py3.11):** `/api/insights/trending-windows` (~20s idle / ~98s
  under load, polled from Home) is observed_on-WINDOWED, so the corpus-wide keyword counters can't
  serve it; `trending()._counts` runs `SELECT keyword_id, SUM(count) WHERE observed_on IN [lo,hi)
  GROUP BY keyword_id` over 2.4M mention rows. The existing `ix_mention_covering` LEADS with
  keyword_id (can't serve an observed_on RANGE) and the plain `observed_on` index forces a HEAP page
  read = a SQLCipher DECRYPT per in-range row — THAT is the cost. CHOSE A COVERING INDEX over the
  brief's per-day ROLLUP table (the honest engineering call, like the associations PR-3 chose counters
  over DuckDB): `ix_mention_date_keyword (observed_on, keyword_id, count)` makes `_counts` an
  index-only "USING COVERING INDEX" range scan (verified with EXPLAIN QUERY PLAN — no heap access),
  targeting the actual decrypt cost. WINS over the rollup: ZERO drift (it's an index, SQLite maintains
  it, always correct — no new table, no index-time delta maintenance to get wrong, no backfill, no
  reconcile), and the QUERY CODE IS UNCHANGED (the planner picks it up transparently). Added to the
  KeywordMention model + maintenance.HOT_INDEXES (boot self-heal, idempotent) + migration b4c5d6e7f8a9
  (off head e4f5a6b7c8d9 — single head verified; collision with the pre-existing a3b4c5d6e7f8 caught +
  avoided). tests/test_trending_index.py (5: index created from model, the `_counts` plan uses the
  covering index, results IDENTICAL with vs without it, self-heal recreates it idempotently, migration
  cols == model cols). NO query-logic change ⇒ trending output byte-identical. REMAINING: if the index
  proves insufficient on the live 2.4M-mention corpus, the per-day rollup is the next lever (measure
  the EXPLAIN/timing on the real DB first — don't add a drift surface speculatively); the country-
  filtered `_counts` stays on the heap (rare path, no country column in the index — the hot Home path
  is no-country).
- **MARKUP STRIP AT THE EXTRACTION CHOKEPOINT (brief §3.F, the 36.5k `?`-bucket root cause; branch
  claude/amazing-tesla-z6bwkm, draft PR onto 0.09; backend VERIFIED py3.11):** the keyword tokenizer
  `_WORD_RE` mints `div`/`span`/`max-width`/`font-size`/`font-family` directly from any raw HTML/CSS in
  a stored body (CSS property names with hyphens tokenise as ONE word) — the live log's 36,519-keyword
  unknown-language junk bucket. The web scrape path is clean (trafilatura), so the leak is .eml-before-
  the-2026-06-20-`_strip_html`-fix / wiki / future paths; rather than chase each, we defend at the ONE
  place every path passes through. NEW `strip_markup(text)` in `src/analytics/extract.py` (called at the
  top of BOTH `BaselineExtractor.extract` + `SpacyExtractor.extract`): drops `<style>`/`<script>` BLOCKS
  first (CSS/JS must never survive as body text), then HTML comments (incl. MSO conditional comments
  containing '>'), then every remaining tag, then decodes HTML entities (so `&nbsp;`/`&copy;` don't
  become `nbsp`/`copy` keywords). HONEST + SURGICAL: a precise `_has_markup` gate runs the strip ONLY
  when a real tag/style/comment/entity is present, so CLEAN text (the overwhelming majority) is returned
  BYTE-IDENTICAL — keyword `first_offset`s into the stored body stay exact; the tag regex
  `</?[a-zA-Z][\w-]*(\s[^<>]*?)?/?>` matches `<div class>`/`<br/>`/`</p>` but NOT an angle-bracketed URL
  `<https://x>` or prose "x < y > z". Applied at index time, so a re-index/backfill cleans existing rows
  (FORWARD case fully fixed; already-stored BARE CSS without tags still needs a re-import — noted). NO
  score, no behaviour change for clean corpora. tests/test_keyword_extract_strips_markup.py (byte-
  identical clean text, no-URL-eating, style/tag/comment/entity removal, extract mints no CSS/HTML
  keyword, end-to-end index_article stays clean + counters consistent); keyword self-test (22 cases × 11
  langs) + analytics_extract/store/counters/families regression all green; ruff F/B clean. REMAINING:
  the bare-CSS-leftover re-import path (per the 2026-06-20 .eml content-quality fix); broader stoplist
  growth is brief §3.G.
- **IN-APP SCALING BENCHMARK 2026-06-20 (maintainer-asked "add a benchmark so we can live test
  this; include detailed benchmark logs I'll pass on"; branch claude/modest-hopper-gisgst, draft
  PR #419 onto 0.09; backend VERIFIED py3.11):** the data-architecture scaling work was proven
  byte-identical but never proven FAST at scale on a real machine. `src/monitoring/benchmark.py`:
  `run_benchmark(session, repeats=3)` times the hot read paths against the LIVE corpus N times
  (run 1 cold, runs 2..N warm-aggregated), each case a bounded query-layer fn the UI already
  calls, per-case ISOLATED (one failing/absent case never aborts). Headline cases flagged
  `optimized_this_session`: grouped top-terms + super-groups (the denormalised counters), associations
  + the mind-map graph (the de-N+1); plus the broader hot reads (trending/windows, map coverage,
  who/where, FTS, framing). The log is SELF-DESCRIBING — corpus size + the keyword-counter freshness
  envelope (exact|estimated) + the columnar engine mode + host facts — so a number is interpretable
  away from the machine. READ-ONLY (reports counter freshness, NEVER reconciles), bounded,
  airplane-safe; on-click only, never transmitted; counts+ms only, NO score. GET
  /api/diagnostics/benchmark + a Settings → Diagnostics "Download scaling benchmark (.json)" button
  (un-keyed English matching the adjacent diagnostics buttons → i18n stays 100%, zero new keys).
  tests/test_benchmark.py (6: shape/context, times the optimized paths cold/warm, single-run-cold-only,
  read-only proof [no rows touched, no watermark stamped], no-score, summary). HONEST GAP in the bare
  test env (not in a real install): fts_search needs the boot-built article_fts table + framing needs
  the [analysis] VADER extra → both report ok=false per-case here, run in a real install.
- **BACKUP IMPORT ACROSS VERSIONS — CONFIRMED TO MAINTAINER 2026-06-20 (informational, no code
  change):** maintainer asked whether OLD-architecture backups are usable + whether articles get
  re-analysed on import. ANSWER = YES to both: oo-backup-2 artifacts restore additively (merge engine)
  down to the 0.0.8-baseline schema floor (FLOOR_NOTE "0.0.8 baseline (6ae5766d3136)"; the staged copy
  is alembic-upgraded to head before merge; a NEWER-app artifact is refused by name), AND the P0-4
  reindex (shipped 2026-06-19) recomputes CORE-ENGINE metadata on import — `run_restore(reindex_imported=
  True)` default → `reindex_imported_articles(batch_id)` → `store.reindex_articles` runs `index_article`
  over the imported article ids (delete-then-reinsert), so keywords/mentions + the NEW denormalised
  counters + dates/places/entities + sentiment are recomputed by the CURRENT engine; AI artifacts
  (article_analyses summaries/translations + ai_keyword) stay verbatim (index_article never touches them).
  So an old backup imports AND gets the current optimizations for free. (Verified in code this session.)
- **AUTONOMOUS V0.1 BATCH (2026-06-20, branch claude/sweet-keller-ozdip1 = ONE rolling branch
  per the system-reminder "develop only on this branch / NEVER push to a different branch"; PR #413
  draft onto 0.09, accumulating commits — also eliminates inter-PR locale conflicts). Commits so far:
  (1) #51 OSM admin-boundary choropleth (entry below); (2) i18n de-tagging tail — 8 batches keyed
  108 chrome strings ×12 (audit-chrome 222→114): batches 1-3 = 66 CLEAN single-text-node strings
  (labels + 12 help paragraphs incl. the backup-encryption explainer, world-map description, keyword
  self-test/engine-report, the four system prompts, custom AI extractors) keyed with NO HTML change
  (the walker matches per text node, so a clean node is directly keyable); batches 4-8 = 16 DE-TAGGED
  paragraphs (removed cosmetic <b>/<em>/<strong>/<code> so each <p> is one node, then keyed) covering
  the core honesty notes — Source-integrity "no trust score / Surface never suppress", the
  Statistics agency-directory "stanced source / no verdict no score", coordinated-floods "shown by
  default / one voice", Tor protected-mode anonymity warning, the restore-merge "nothing is replaced
  or deleted" + "additive-only", annotations "never a score / who asserted what", keyword-filtering,
  settings-stored-locally/no-telemetry, uninstall. DELIBERATELY KEPT TAGGED: the discovery paragraph's
  <strong> emphasis on "Your query leaves this machine." (a privacy warning). Technical tokens literal
  throughout. REMAINING tail (~114) = data/examples (stay literal) + the harder <a>-linked help
  paragraphs (World-law mirror note etc., need the link-at-end restructure) + the passphrase
  no-recovery warning (security-sensitive, deferred for native review). Non-en AI-drafted, flagged.
  Full py3.13 suite (1860 passed) green on the PR after the batches. (3) PER-ARTICLE
  SUMMARIZE/TRANSLATE on the analysis Articles list (Track C, the repeatedly-flagged REMAINING; backend
  VERIFIED, frontend BROWSER-UNVERIFIED per fork-3): each row gained Summarize + Translate buttons →
  `anArticleLlm(id, op, btn)` reuses the EXISTING single-article endpoints `POST /api/llm/articles/{id}/
  {summarize,translate}` (loopback Ollama — no network consent; airplane refuses at the client), renders
  the result INLINE in a sibling row labelled "AI summary/translation — unreliable, verify against the
  source" + model·prompt provenance (#23 caveat visible), translate target = the UI language via the
  existing `_uiLangName()`. HONEST BY CONSTRUCTION: the rows store in `article_analyses` (the reader's
  Summary/Translation tabs read the same), NEVER the trusted keyword index (the invariant test pins the
  ArticleAnalysis store + the AI-derived caveat). +10 i18n keys ×12 (Summarize/Translate + the
  caveats/hints; non-en AI-drafted, flagged). tests/test_repo_invariants.py::
  test_analysis_articles_per_row_summarize_translate + existing test_llm_api green; node --check;
  i18n --min 100 (1464 ×12). REMAINING for this item: a per-article custom-extractor run on the list
  (the bulk path already has it); surfacing already-stored analyses inline without re-running.
- **AUTONOMOUS V0.1 — THEME-2 #51 OSM ADMIN-BOUNDARY CHOROPLETH (2026-06-20, branch
  claude/sweet-keller-ozdip1, draft PR onto 0.09; parser+assembly NODE-VERIFIED, frontend
  BROWSER-UNVERIFIED per fork-3):** the maintainer-ruled #51 — colour each country by data
  using REAL OSM admin boundaries, fixing the ~75 microstates the coarse Natural-Earth 110m
  `world_countries.json` drops. Built on the shipped `src/static/osmpbf.js` (it decoded dense
  nodes + ways only). EXTENDED the parser: `decodeStringTable` (PrimitiveBlock field 1) +
  `resolveTags` + WAY tag decode (opts.withTags) + RELATION decode (opts.withRelations →
  `decodeRelation`: members {ref,type,role} via memid sint64-delta + roles_sid stringtable +
  resolved tags) — all BLOCK-LOCAL string resolution done in `decodePrimitiveBlock` where the
  StringTable is in scope; backward-compatible (default opts = old geometry-only shape +
  `relations:[]`, so the existing node test stays green). NEW pure `assembleAdminAreas(parsed)`:
  finds admin_level=2 / boundary=administrative relations carrying ISO3166-1:alpha2, collects
  outer-role way members, and `stitchRings` stitches them into CLOSED polygons by shared
  endpoints (EPS match, reverse-as-needed), keyed by ISO-2 → `[{iso2,name,rings:[[lon,lat]…],
  source}]`. HONEST BY CONSTRUCTION: emits ONLY rings it actually closed (a truncated/partial
  boundary is dropped, never a fake border); only areas with a valid 2-letter ISO tag (so they
  merge into the code-keyed choropleth); inner/hole rings skipped (outer only). FRONTEND
  (browser-unverified): `_ooMapToggleOsm` now parses with withTags/withRelations (maxBlocks 48 to
  reach the trailing relations section, maxNodes 200000 memory bound, 16MB prefix) + assembles
  `osmAreas` into `_ooMapOsmGeo`; ooMap AUGMENTS its geometry — an OSM-derived shape REPLACES the
  coarse 110m polygon for that country and ADDS countries the 110m set never had (the microstate
  fix), drawn with an accent stroke + a "· boundary from OSM" title note + a legend "N country
  boundaries" count (provenance visible). The existing raw-lines/nodes overlay + centroid-point
  fallback are UNTOUCHED (additive; a country with no closed OSM ring still falls back). Backend
  reuses the bounded, path-safe, zero-network `GET /api/geo/regions/{code}/preview` (no change).
  +2 i18n keys ×12 (boundary from OSM · country boundaries; non-en AI-drafted, flagged). The
  VERIFIABLE CORE is node-tested: `tests/osmpbf_node_test.js` gains a hand-encoded
  StringTable+ways+admin-relation fixture (its own protobuf encoder) asserting the exact closed
  ring coords + ISO key + that admin_level≠2 yields no area; `tests/test_repo_invariants.py::
  test_world_map_osm_admin_boundary_choropleth` pins the parser+frontend wiring. node --check
  (app.js + osmpbf.js) clean; i18n --min 100 (1416 ×12); 88 repo-invariants + osm parser/preview
  green. REMAINING: inner-ring (hole/enclave) subtraction; human click-through with a real
  downloaded region (no region in this env); bbox auto-zoom to the rendered country.
- **SLICE 4 PR-3 — HEAVY-AGGREGATION PERF VIA THE COUNTERS, NOT DUCKDB 2026-06-19 ("proceed with
  the remaining item"; draft PR onto 0.09; VERIFIED py3.11):** the honest engineering call —
  /api/insights/associations (76 s) was an N+1, not a columnar problem, so the Slice-2 counters fix
  it with no new dependency, no persistence gate, offline, byte-identical. queries.associations now
  batch-loads the co-keyword rows (one query, not N gets) and reads n_b corpus-wide from the
  maintained ``article_count`` counter (== COUNT(DISTINCT article_id), zero query) / windowed from
  ONE grouped query (not N). layered_graph keyword-level inherits it (calls associations ~6×); the
  Python PMI/family/ring honesty layers are untouched. tests/test_associations_perf.py recomputes
  n_b the live way + proves byte-identical output on both the counter path AND the windowed path.
  Also hardened a latent test-ordering pollution in test_readmodel_seam (its insights reload with
  OO_INSIGHTS_CACHE_TTL=0 could leak to a later test — now resets the env before the restore reload;
  CI's alphabetical order never hit it, but a mixed-order run did). framing was already bounded
  (8000-char cap, prior fix). The columnar DuckDB port stays available for the inherent co_rows
  GROUP BY when PERSISTED (gated on the httpfs packaging decision) but is NO LONGER the 76 s blocker.
  The data-architecture brief is COMPLETE bar that one packaging decision.
- **EXTERNAL-ARTIFACT FRESHNESS REGISTRY + COMPATIBILITY TESTS 2026-06-19 (maintainer-asked
  "long-term strategy to avoid missing repository updates + add compatibility testing"; draft
  PR onto 0.09; backend VERIFIED py3.11):** the project had ~8 dated `*_AS_OF` constants +
  vendored data + version couplings guarded by SCATTERED per-file freshness tests, with no
  single list + no upstream watch. Consolidated into: (1) `configs/external_artifacts.yml` =
  the SINGLE SOURCE OF TRUTH (12 entries: ip-geo/catalog/dump-sizes/osm/baseline/stats/
  denylist/install-sizes + vendored Alpine + Natural-Earth + the DuckDB↔crypto-extension
  coupling + CI pins); (2) `src/maintenance/registry.py` = a NETWORK-FREE loader/evaluator
  (reads `*_AS_OF` from source by regex, no imports; freshness windows; the DuckDB
  version coupling); (3) `tests/test_external_freshness.py` = the PROTOCOL GUARD (every
  `*_AS_OF` in the tree MUST be registered — can't ship a dated artifact unwatched) +
  consolidated freshness + COMPATIBILITY couplings (the registry DuckDB floor == the
  pyproject `[columnar]` floor; installed duckdb ≥ floor; the bundled geo DB parseable at its
  vintage); (4) `scripts/check_external_freshness.py` (CLI, exit≠0 on stale — for the future
  cron) + `GET /api/diagnostics/freshness` (production self-report). COMPATIBILITY HARDENING:
  `columnar.connect()` now stamps a store-format marker (DuckDB major.minor + schema rev) and
  on an incompatible/corrupt persisted store DELETES + REBUILDS it (disposable) instead of
  crashing — so a DuckDB upgrade is safe. `docs/maintenance/EXTERNAL_DEPENDENCIES.md` carries
  the 4-layer strategy + the per-bump upgrade checklist (esp. the per-OS httpfs extension
  matrix). REMAINING (awaiting maintainer sign-off, layer 3): the upstream-watch CRON that
  opens an issue when upstream > our pin (Dependabot for pip/Actions; the cron for data/
  binaries). Tests verified py3.11; full pytest needs py3.13 → CI.
- **DATA-ARCHITECTURE FOLLOW-UP 2026-06-19 (PR #410, draft onto 0.09, after #407 merged; the
  "proceed with all, incrementally" pass — finishes the gated items from #407; backend VERIFIED on
  the py3.11 venv, frontend BROWSER-UNVERIFIED per fork-3):**
  - **A — real IP-geo DB BUNDLED (Slice 6b complete):** db-ip.com 403s, but the DB-IP CC BY 4.0
    MIRROR (sapics/ip-location-db, identical start,end,CC) is reachable → bundled the real country
    table `src/geo/data/dbip_country_lite.csv.gz` (~4.4 MB gz, 701k IPv4+IPv6 ranges).
    IP_GEO_AS_OF="2026-06"; lookup resolves real IPs OFFLINE (8.8.8.8→us, IPv6 too; zero sockets);
    freshness test active; generator gained `--mirror` + always-gzip. The VERIFY-list "IP-geo DB
    license/size/offline" is now DONE.
  - **B — ooMap "Server IPs" layer (Slice 6c frontend):** a switchable layer (mirrors Places/Signals)
    plotting captured server IPs (geolocated offline) as violet squares DISTINCT from the editorial
    source-country choropleth; lazy-fetches /api/insights/server-locations; caveats VISIBLE
    (CDN-edge/anycast, not the origin; unavailable over Tor) + clustering "a shape to investigate,
    never a verdict" + a clusters/Tor-unavailable legend line; new strings English-fallback (i18n
    100%). test_world_map_server_location_layer.
  - **C — columnar read-model builder (Slice 4 PR-2 foundation):** columnar.build_keyword_read_model
    = a BYTE-IDENTICAL projection of the Slice-2 counters into a DuckDB keyword_agg table (off the
    request path); top_terms_raw reads it in the live raw shape; cold/missing store → [] (the
    canonical correctness path never DEPENDS on the derived store). NOT wired to the hot endpoints:
    offline it's in-memory = a per-process rebuild = no gain over the counters; the win is the
    PERSISTED store across restarts (gated on the crypto-extension decision); the heavy-aggregation
    ports (associations/graph/framing — the slow ones) are the careful follow-on PR-3 (raw-aggregation
    in DuckDB + the Python honesty layers unchanged, perf-verified on a real corpus).
  - **D — persisted maintenance + observability:** columnar.refresh_persisted_read_model maintains
    the read-model ONLY when PERSISTED (encrypted; secure crypto available), a no-op in-memory; wired
    into warm_cache using the SAME passphrase (get_passphrase, no second key surface); GET
    /api/diagnostics/columnar surfaces the engine mode (persisted/memory/unavailable) + geo vintage so
    the per-OS httpfs/OpenSSL crypto-extension PACKAGING DECISION is informed (still the one open gate
    for persisted-offline encryption). tests cover the no-op + honest status + endpoint.
- **DATA-ARCHITECTURE & SOURCE-IP BUILD 2026-06-19 (the AUTONOMOUS_BUILD_BRIEF_DATA_ARCH.md
  slices; branch claude/modest-hopper-gisgst, draft PR onto 0.09; backend VERIFIED on a py3.11
  test venv built here — 49 passed/2 CI-only-skipped; full pytest needs py3.13 → CI). Session
  RULINGS now binding (2026-06-19, also in the DATA-ARCHITECTURE queue entry): cross-time recall is
  SACRED (no recency bias / time-partitioning ABANDONED); performance must NOT depend on hiding data
  (counters + derived read-model, every article always present); the honesty ENVELOPE
  {value,basis:exact|estimated,as_of,method,n} is mandatory on maintained aggregates (basis is a
  DISCLOSURE, assert_no_score_fields holds); the derived columnar store is encrypted-under-the-same-
  passphrase OR in-memory, NEVER a plaintext file; capture = default-anonymize + opt-in fidelity
  (unchanged); source IP wanted + geolocated OFFLINE with heavy caveats; tiered-retention eviction
  DEFERRED (needs the archive first). SHIPPED slices (one commit each, additive/reversible, migration
  + boot self-heal per column, single alembic head, no model drift):**
  - **Slice 1 — honesty envelope** `src/analytics/envelope.py` (Envelope{value,basis,as_of,method,n};
    exact/estimated; as_of REQUIRED never fabricated; assert_no_score_fields run on it at import).
    tests/test_envelope.py.
  - **Slice 2 — counter freshness** `Keyword.last_reconciled_at` (migration b2c3d4e5f6a7 +
    ensure_keyword_counter_columns self-heal that adds the nullable watermark WITHOUT re-backfilling).
    store.reconcile_keyword_counters (recompute exact + detect drift + stamp; the ONE full GROUP BY,
    OFF the request path), counter_envelope (O(keywords) exact-when-fresh / estimated-when-stale via
    OO_COUNTER_FRESH_HOURS=24), maybe_reconcile_counters wired into warm_cache (self-throttling).
    /top (corpus-wide) + /supergroups carry an ADDITIVE `counts` envelope. tests/
    test_keyword_counter_freshness.py (injected-drift→estimated→reconcile→exact; counter read stays
    O(keywords)).
  - **Slice 3 — read-model seam** `src/analytics/readmodel.py` (ONE boundary: top_terms/trending/
    trending_windows/associations/layered_graph/article_graph/source_country_counts; v1 delegates
    byte-identically; insights endpoints route through rm.* so Slice 4 plugs in WITHOUT touching an
    endpoint). tests/test_readmodel_seam.py (delegation == live; /top provably reads through the seam).
  - **Slice 4 PR-1 — columnar engine** optional [columnar] extra (duckdb>=1.4); `src/analytics/
    columnar.py` connect() = persisted-ENCRYPTED (AES key derived from the one passphrase, no second
    key surface) ONLY after encryption_gate proves it (sentinel-absent / no-key-fails / with-key-works),
    else IN-MEMORY; NEVER a plaintext file; offline (autoload + external access OFF). UNWIRED (zero
    risk; absent duckdb → seam serves live query). **EMPIRICAL FINDING: the stock duckdb wheel does
    NOT bundle the OpenSSL/httpfs crypto and would autoload it from the NETWORK (forbidden), so secure
    PERSISTED encryption is unavailable fully-offline → engine runs in-memory (sanctioned hard-
    fallback). DuckDB's mbedtls is documented NOT-secure → never trusted (no fabricated security).
    PERSISTED-offline needs a per-OS httpfs extension bundled locally = a packaging decision left to
    the maintainer; code is ready (secure_crypto_available gate).** tests/test_columnar_engine.py.
  - **Slice 5 — K1/K2 identity** `Article.content_multihash` (self-describing sha2-256:<hex> alongside
    the never-reformatted unique `hash`) + `canon_version` (url-v1). before_insert listener stamps
    FORWARD on every insert path; migration d3e4f5a6b7c8 + ensure_article_identity_columns backfill
    (pure string op, no content decrypt). Dedup unchanged. tests/test_article_identity_seams.py.
  - **Slice 6a — source IP capture** EthicalFetcher._capture_server_ip reads the connected peer on a
    DIRECT clearnet socket; over proxy/Tor → NULL + reason 'unavailable (proxy/Tor)', never a guess;
    degrades loudly. Article.server_ip/ip_observed_at/server_ip_reason (migration e4f5a6b7c8d9 +
    ensure_article_ip_columns, no backfill); store_fetched populates forward. The IP is OUR vantage
    point (CDN edge/anycast), not the origin. tests/test_source_ip_capture.py.
  - **Slice 6b — offline IP geolocation** `src/geo/ip_geo.py` lookup(ip)→{country,lat,lon,level,
    db_vintage} fully OFFLINE (zero sockets, proven); country from a bundled DB-IP IP-to-Country Lite
    range table (binary search, v4+v6), city from an on-demand data_dir download (never bundled/at
    boot), country coords reuse geocode. NEVER fabricates a location (unknown/missing→unavailable+
    reason). LICENSE VERIFIED: DB-IP IP-to-Country Lite = CC BY 4.0 (attribution mandatory,
    ip_geo.ATTRIBUTION). scripts/build_ip_geo.py = networked-machine generator. **SKIP-AND-NOTE: the
    real DB download is 403-blocked in the sandbox (like Wikidata/Ollama) → bundling it is a
    networked-machine step; IP_GEO_AS_OF="unbundled" + the freshness test activate once it exists.**
    tests/test_ip_geo.py (labeled documentation-IP fixtures, no fabricated real data).
  - **Slice 6c (backend) — server-location layer** queries.server_locations + GET /api/insights/
    server-locations: captured IPs geolocated offline, per-country, DISTINCT from the editorial
    Source.country layer; IP/host CLUSTERING (2+ distinct sources on one IP = network-layer cousin of
    source-laundering) surfaced as a shape to investigate NEVER a verdict; honest unavailable buckets;
    counts only/no score; caveat + db_vintage + attribution carried. tests/test_server_locations.py.
  REMAINING (flagged): Slice 4 PR-2/3 (port the heavy aggregations to read from the columnar store
  behind the seam) + the persisted-encryption packaging decision (bundle per-OS httpfs); 6b bundle the
  real DB-IP table (run the generator); 6c FRONTEND ooMap server-location layer toggle (browser-
  unverifiable + needs the bundled DB to render). DEFERRED per brief (one-line, not built): WARC/BagIt
  + age + SLIP-39; tiered-retention eviction; TLS chain/SCT/CT + provenance Tier vocabulary;
  time-partitioning (abandoned unless provably result-invisible).
- **FIELD TEST 2026-06-19 — THEME-3 ANALYSIS-WINDOW-PER-QUERY (centerpiece; branch
  claude/gallant-bohr-1cogzj; frontend, invariant-guarded, BROWSER-UNVERIFIED):** the singleton #an
  analysis window became a MULTI-DOCUMENT WORKSPACE. A search / Lead / keyword now SPAWNS a NAMED,
  closeable, persisted TAB (`#an-tabstrip`) over the one render area; several searches coexist as
  parallel tabs (deduped by seed key; soft cap 10; persisted to localStorage `oo.an.tabs.v1`,
  restored at boot with lazy data-load on first open). Machinery: `_anTabs`/`_anActiveId` +
  `_anSpawn`/`_anActivate`/`_anCloseTab`/`_anApplySeed`/`_anRenderStrip`/`_anShowEmpty`/
  `_anRestoreTabs`; `openAnalysisFor`/`openAnalysisForIds`/`openAnalysis` refactored to spawn,
  `anRunAdvanced` refines the ACTIVE tab in place. The legacy #corpus-win keyword MODAL is RETIRED —
  `openCorpus(term)` now just spawns an analysis tab (one surface; the modal DOM stays unreachable
  per the Desk lesson, never shown). NEW **Overview** subtab (the default landing, Q1 generic): an
  honest headline TILE per lens (top keyword / where+who / source / sentiment + deep-link tiles for
  Trend/Mindmap/Links/Related/Articles) — counts only, no synthesis, each deep-links to its subtab
  via `renderAnOverview` (bounded Promise.all over the existing corpus-* endpoints, graceful degrade).
  test_repo_invariants::test_analysis_window_per_query_spawns_tabs_and_retires_corpus_modal +
  existing #an/openCorpus invariants still green; node --check + i18n 100%. REMAINING: spawned tabs
  in the TOP facet strip (nav=B) vs the in-panel strip shipped here; per-tab subtab memory; richer
  Overview headlines; human click-through (fork-3).
- **FIELD TEST 2026-06-19 — LARGE-UI-REWRITE BATCH (maintainer "proceed with all remaining themes,
  I'll test separately"; branch claude/gallant-bohr-1cogzj; ALL frontend, BROWSER-UNVERIFIED, flagged):**
  batch-1 rulings (AskUserQuestion 2026-06-19): (1) THEME-3 = RETIRE BOTH the empty singleton #an AND
  the legacy #corpus-win modal → ONE analysis surface (analysis-window-per-query, named/closeable/
  persisted spawned tabs + an Overview screen); (2) THEME-2 OSM enrichment = IN-BROWSER .pbf PARSER
  (bundle a local vector-tile/pbf parser, render the downloaded region directly, fully offline); (3)
  THEME-5 security i18n = TRANSLATE ×12 + FLAG for native review (everything incl. panic/airplane);
  (4) Q1 per-card = GENERIC ONLY (every card opens its EXACT corpus on the Overview screen; per-type
  landing deferred — maintainer will send tweaks). AUTONOMOUS DEFAULTS (not asked): Overview = honest
  headline tile per lens (no synthesis); THEME-2 fullscreen (Fullscreen API) · regions-as-list ·
  dynamic non-overlapping labels (greedy declutter) · deduced-events-as-shapes (square/triangle,
  colour=type) · click-country→a coverage list; P2-10 families-first + drop the Cards/Families toggle
  + one shared fullscreen graph overlay + axis smoothing; P2-12 minimal shared status bar on the
  standalone Tasks page. Built as stacked commits per-slice below.
- **FIELD TEST 2026-06-19 — THEME-5 i18n: DE-TAGGING PHASE SLICE 2 (Insights panel) ×12 (post-#405-merge;
  branch claude/gallant-bohr-1cogzj):** continued the de-tagging burn-down on the INSIGHTS-tab help texts —
  de-tagged 4 `<p class="hint">` paragraphs (dropped inline `<b>`/`<em>`, EXAMPLE/proper-noun tokens kept
  literal inside the sentence) + keyed them ×12: the LINKS citation-graph note, the FAMILIES merge/split
  explainer (Trump=Trump's=Donald Trump example + the ✕ glyph preserved), the GROUPS super-ring explainer
  (election/élection/wahl + Russia–Ukraine war examples preserved; "Pure curation — nothing in the keyword
  store changes"), and the CONVERGENCE note (the load-bearing honesty line "Independence is measured by
  distinct sources, not article count. Co-occurrence is never causation — a prompt to read, not proof
  anything happened." translated FAITHFULLY in every locale). 1406→1410 keys ×12; non-en AI-drafted, FLAGGED
  for native review; verified each resolves against the whitespace-normalised HTML. i18n --min 100 (1410 ×12);
  full test_repo_invariants green; no test asserted the removed markup (grep-checked first). NOTE re conflicts:
  an open i18n slice collides on the locale-JSON tails whenever another i18n PR merges first (happened with
  #399→#405) — always the same additive-UNION resolution (keep theirs + add my keys from the git stage
  versions). ~245 inline-tagged help strings remain.
- **FIELD TEST 2026-06-19 — THEME-5 i18n: DE-TAGGING PHASE SLICE 1 ×12 (post-#404-merge; branch
  claude/gallant-bohr-1cogzj):** STARTED the harder inline-tag de-tagging phase (the single-node tail being
  exhausted). De-tagged 3 help paragraphs in index.html (dropped the cosmetic inline `<strong>`/`<em>` so each
  `<p>` is ONE text node — the established ledger convention, LOW layout risk = text stays, just not bold;
  verified NO test asserted that markup first) + keyed 4 strings ×12: the Sources DISCOVERY-CANDIDATES note
  ("Promote creates a disabled source … Dismiss is remembered and never re-suggested"), the candidates heading
  "(machine-suggested — nothing happens without you)", the UNMANAGED-LANGUAGES explainer ("…produce junk
  keywords … kept and re-enablable …"), and the safety RESTORE-additive-only note ("the destructive
  replace-restore was removed … complements your corpus and never overwrites it"). The i18n engine normalises
  internal whitespace, so the single-line JSON key matches the multi-line `<p>` (verified each resolves +
  appears in the normalised HTML). 1402→1405 keys ×12 (one pre-existed); honesty phrases ("never re-suggested",
  "kept and re-enablable", "additive-only", "never overwrites") translated faithfully; non-en AI-drafted,
  FLAGGED for native review. i18n --min 100 (1405 ×12); full test_repo_invariants green (no UI/restore/discovery
  guard tripped). Proves the de-tagging pattern is unblocked; ~250 inline-tagged help strings remain, continue
  panel-by-panel.
- **FIELD TEST 2026-06-19 — THEME-5 i18n: CLEAN CAPTIONS + LABELS SLICE ×12 (post-#403-merge; branch
  claude/gallant-bohr-1cogzj):** the easy-LABEL tail being nearly exhausted, this slice keyed the remaining
  CLEAN, SINGLE-NODE strings that need NO inline-tag de-tagging — 6 labels (Trends · User Manual · Value
  column · Value regex · View chain · Unit) + 5 complete honesty CAPTIONS (the signed-evidence Markdown
  "Records selection only; concludes nothing"; the unmanaged-language disable note "Reversible from the
  sources table"; the synthesize "Assistance, never a verdict"; the custom-extractor "one item per line";
  "Updates automatically in the background."). 1391→1402 keys ×12; non-en AI-drafted, FLAGGED for native
  review (Markdown/LLM/Regex/max-20 kept literal; the honesty phrases — "never a verdict", "concludes
  nothing", "Reversible" — translated faithfully). i18n --min 100 (1402 ×12); ui_invariants/dropdown guards
  green. PHASE NOTE: the SINGLE-NODE tail is now largely done; the REMAINING ~250 untranslatable strings are
  inline-TAGGED help paragraphs (need the per-panel `<b>/<em>` de-tagging treatment) + data/proper-nouns
  (correctly left literal). Next i18n work is the heavier panel de-tagging, done deliberately panel-by-panel.
- **FIELD TEST 2026-06-19 — THEME-5 i18n: STATIC-LABEL BURN-DOWN SLICE ×12 (post-#402-merge; branch
  claude/gallant-bohr-1cogzj):** continued the documented panel tail — keyed 31 CLEAN, short, single-text-node
  chrome LABELS scattered across the Insights/Settings/Search/Sources panels (Add a source · Add rule · Add a
  custom extractor · Add a price-extraction rule · Advanced · Apply baseline tags · Boolean query · By city ·
  By country · Competitive · Convergence · Corpus landscape · Custom extractors · Explore · Export all (CSV) ·
  Export bundle · Filter · Flagged legal changes · Import CSV · Import custom feed · Import sources from a CSV
  file · In context · Keyword & entity insights · Keyword families · Keyword or entity · Manage sources · Map
  (cities) · Merge selected · Min. articles · Most-cited sources · My calendar). Each VERIFIED via
  --audit-chrome (untranslatable=unkeyed) + confirmed present as element text in index.html; DELIBERATELY
  excluded data/examples/proper-nouns/fragments (Donald Trump, Neodymium spot, NY.GDP.MKTP.CD, DuckDuckGo,
  IMAP, "After adding, use"…). 1360→1391 keys ×12 (CSV/PMI kept literal); non-en AI-drafted, FLAGGED for
  native review. i18n --min 100 (1391 ×12); full test_repo_invariants green (no dropdown/data-guard tripped).
  REMAINING THEME-5: the longer HELP-PARAGRAPH tail (needs the inline-tag de-tagging treatment) + more panels.
- **FIELD TEST 2026-06-19 — THEME-5 i18n: THIS-SESSION'S UI STRINGS ×12 (post-#400-merge; branch
  claude/gallant-bohr-1cogzj):** keyed the 33 NEW visible strings the merged session added through `t()`
  with English fallback — so the session's OWN additions leave NO English-fallback debt. Covers P2-10
  (the families member-chip + price-detail + Correlate labels), the THEME-2 map (Labels toggle · the
  certainty shape-key confirmed/scheduled/deduced · Shape=certainty;colour=kind · the click-country
  coverage detail incl. the VADER-EN caveat · Explore sources), the in-browser OSM .pbf overlay (OSM ·
  offline OSM · nodes · ways · preview · the bounded-preview note · the reader-unavailable / no-region /
  reading / read-error toasts), and the P2-12 task page (Sessions · Online sessions · Network mode · the
  empty-sessions state · the two airplane-control titles). 1327→1360 keys ×12; non-en AI-drafted, FLAGGED
  for native review (acronyms OSM/VADER/.osm.pbf kept literal). i18n --min 100 (1360 ×12); verified each
  literal resolves to a key AND appears in source. REMAINING THEME-5: the broader ~hundreds-string panel
  tail (the established slice-by-slice burn-down).
- **FIELD TEST 2026-06-19 — THEME-2 IN-BROWSER OSM .pbf RENDERER (#51 batch-1; branch
  claude/gallant-bohr-1cogzj; parser+endpoint VERIFIED, overlay BROWSER-UNVERIFIED):** the maintainer's
  chosen path to render a DOWNLOADED offline-map region with NO network + no heavy WebGL. NEW
  `src/static/osmpbf.js` = a dependency-free OSM PBF reader: protobuf varint/zigzag primitives, the
  BlobHeader/Blob container, zlib via the native `DecompressionStream`, and the PrimitiveBlock
  dense-node DELTA decode to exact WGS84 degrees + way refs. BOUNDED by construction (`maxBlocks`/
  `maxNodes` → an honest PREVIEW that flags `truncated`, never an OOM on a multi-GB extract). The
  varint/zigzag/dense-decode core is PROVEN under node against a hand-encoded fixture
  (`tests/osmpbf_node_test.js`, run in CI by `tests/test_osmpbf_parser.py` — exact degrees, full-file
  parse, maxBlocks truncation; the test writes its OWN protobuf encoder so the round-trip + hand-computed
  degrees are non-vacuous). NEW backend `GET /api/geo/regions/{code}/preview?max_bytes=` serves a BOUNDED
  byte PREFIX of the LOCAL `.osm.pbf` (loopback, zero-network — reads a file already on disk; path-safe
  via `is_valid_code`; hard 16 MB ceiling; 404 if not downloaded; X-OO-Region-* headers); tests/
  test_osm_preview.py (5). FRONTEND: an opt-in in-map "OSM" toggle on ooMap fetches a downloaded region's
  preview, parses it with OOPBF, resolves way refs→coords, and overlays nodes (sampled ≤4000) + ways
  (≤3000) on the SAME lon2x/lat2y projection (no second projection) with an honest "offline OSM · N
  nodes · M ways · preview" legend. node --check + test_world_map_osm_offline_overlay; full pytest in CI.
  REMAINING (flagged): human click-through (a real downloaded region — none in this env); rendering polish
  (bbox auto-zoom to the region; way styling by tag); enriching the choropleth from OSM boundaries (#51 fuller).
- **FIELD TEST 2026-06-19 — THEME-5 i18n: SECURITY SENTENCES ×12 (#5/#64; branch
  claude/gallant-bohr-1cogzj):** the explicitly-named, security-CRITICAL subset of the THEME-5 tail —
  the airplane STATE titles (#5: "Online — click to go offline (airplane mode)…" / "Offline (airplane
  mode) — click to go online; you'll be asked to confirm first.") and the PANIC-WIPE dialog (#64: the
  PANIC-WIPE confirm + "This cannot be undone. Type-confirm follows." + "To confirm, type WIPE in
  capitals:" + "Panic wipe cancelled.") — keyed ×12 (1322→1327 keys; one already existed). These flow
  through `t()` already (airplane via `_paintNetwork` + the `data-i18n-dyn` mechanism, re-translated on
  the `oo:langchange` listener; panic via the `panicWipe` confirm/prompt). Translated CAREFULLY,
  preserving the exact technical claims (irreversible/every-new-request-refused/confirm-first) and the
  literal ASCII keyword "WIPE" (the typed confirmation never depends on locale input). Non-en
  AI-drafted, FLAGGED for native review — a mistranslated security warning is worse than English, so
  these especially want a native pass. i18n --min 100 green (1327 ×12). The maintainer's batch-1 answer
  (translate ×12, flag for review) reverses the earlier "stay English-fallback" caution for these.
  REMAINING THEME-5: the ~hundreds-string long tail (this session's UI labels stay English-fallback,
  keyable later per the established slice approach; the recently-added panels per the burn-down).
- **FIELD TEST 2026-06-19 — THEME-5 i18n: STATUS-BAR + SESSION-NEW STRINGS ×12 (#59; branch
  claude/gallant-bohr-1cogzj):** the always-on status pill showed hardcoded lowercase "healthy"/
  "offline"/"checking…" (the #59 named gap) — routed through `t()` and keyed ×12, plus this session's
  short new visible strings ("AI" subtab #42, "encrypted (AES-256-GCM)" / "plaintext archive" P0-2
  verdict pills). 6 keys × 12 locales (en + 11 AI-drafted, FLAGGED for native review per the standing
  pattern; confident common forms — KI/IA/ИИ, 正常/オフライン, etc.). i18n --min 100 green (1322 ×12).
  The LONGER session strings (the airplane state titles #5, the panic dialog #64) stay English-fallback
  for a careful native-review sweep (a mistranslated security warning is worse than English — the
  standing caution). REMAINING THEME-5: the ~hundreds-string long tail (the recently-added panels,
  per the slice-by-slice burn-down) + the panic/airplane sentences.
- **FIELD TEST 2026-06-19 — P2-8 TRENDS AS CLICKABLE BAR GRAPHS (#25; branch
  claude/gallant-bohr-1cogzj; frontend, invariant-guarded, BROWSER-UNVERIFIED):** the Insights →
  Trends rising/top LISTS became clickable horizontal BAR graphs (`termBarsHtml`): keywords top→down,
  bar length ∝ the REAL measured value (rising = growth rate, top = mention count — normalised to the
  max, NEVER a composite score), the value shown beside each bar; clicking a bar opens the unified
  analysis window (`openAnalysisFor` → trend over time + worldwide spread). The exclude ✕ stays.
  Honest: the bar visualises a count/rate, the number is explicit. termListHtml kept for the
  trending-windows "rest" list. +CSS `.term-bars`. test_trends_render_as_clickable_bar_graphs.
- **FIELD TEST 2026-06-19 — THEME-2 WORLD MAP (contained slice: #14/#15; branch
  claude/gallant-bohr-1cogzj; frontend, invariant-guarded, BROWSER-UNVERIFIED):** the unified ooMap
  (the world map after the 5b retire) got three contained, honesty-relevant fixes. (#14 near-time)
  the "near in space & time" co-occurrence used the SLIDER's focus window (~span/12 ≈ 166y on an
  antiquity→now span) so it linked events DECADES apart — a misleading "co-occurrence"; now capped to
  a TIGHT FIXED `_OOMAP_NEAR_YEARS = 2` (independent of the slider) so only genuinely near-in-time +
  near-in-space events seed (still non-causal, the verbatim caveat stays). (#14 log slider) the time
  slider was LINEAR (`tmin + frac·span`) so recent years were buried; now LOGARITHMIC-by-age
  (`focusT = tmax − span·(10^(1−frac)−1)/9`) so the recent end gets most of the travel (slider 0→year
  25, 0.5→1544, 0.75→1852, 1.0→2025 on a 2000y span) — NOT a hidden warp (the focus-YEAR label is
  always shown). (#15) the offline-map download dropped the redundant "are you sure (several GB)"
  confirm — `ensureOnline` (the ONE network consent) + the visible task-manager job + the size in the
  region list are the honest gates. test_world_map_near_time_capped_log_slider_and_no_download_confirm.
  REMAINING THEME-2 (larger, browser-test-needed): dynamic non-overlapping country labels, fullscreen,
  OSM data enriching ALL maps (#51), click-country→list, deduced events as shapes, regions as a list
  not a dropdown (#15 second half), linear/log toggle (the fuller agreed design).
- **FIELD TEST 2026-06-19 — P2-2 CARD DECLUTTER VIA A "?" AFFORDANCE (#19/#66; branch
  claude/gallant-bohr-1cogzj; frontend, invariant-guarded, BROWSER-UNVERIFIED):** the maintainer
  found Leads cluttered with the verbose "why"/method. Consolidated the "Why am I seeing this?"
  (plain sentence + exact math) AND the Method into ONE per-card "?" affordance (`.card-info`
  `<details>`) at the BOTTOM-RIGHT of `.acts` (next to Add-to-draft/dismiss), removing them from the
  card face. CONSTRAINT HONORED (Q2 + #23, the informed-consent non-negotiable): the CAVEAT stays
  FULLY VISIBLE in `.card-caveat` on the face — NOT moved into the "?" (test asserts c.caveat NOT in
  infoBlock + still in .card-caveat). The global "Show method" toggle (#brief-methods +
  toggleMethods/applyMethodsToggle) is RETIRED — the per-card "?" absorbs it (method is reachable
  per-card; the checkbox is gone, orphaned "Show method" locale keys harmless). #66: the Draft button
  gained a 🛒 cart icon + title. #23 test updated (caveat-visible core unchanged; method now asserted
  inside the "?" not a global-toggle .mc). node --check + test_ui_invariants + i18n 100%. REMAINING:
  the full verbose caveat ALSO surfaced in the opened analysis window (the card click already opens it);
  per-card-TYPE scenarios are Q1 (parked, maintainer-reserved).
- **FIELD TEST 2026-06-19 — P2-5/THEME-1 BROWSER-STYLE SUBTABS + P2-11 MODELS→AI (#31/#57/#42;
  branch claude/gallant-bohr-1cogzj; frontend CSS/label, invariant-guarded, BROWSER-UNVERIFIED):**
  the maintainer found the subtab active-state "unreliable" and wants ONE homogeneous browser-tab
  look. Restyled `nav.tabs` (the universal ooSubtabs component, used by Insights/Settings/markets/
  Home-families/task-manager/analysis) into a baseline strip with an UNMISTAKABLE active state — an
  ACCENT underline (`border-bottom:2px solid var(--accent)`) + accent text + bold — replacing the old
  subtle bg+border that read as buttons. Theme-safe (var(--accent) across all 17). Combined with the
  #31 ooSubtabs live-query fix, the active tab is now both correct AND clearly visible. (#42) the LLM
  Settings subtab label "Models" → "AI" (the `data-tab="models"` anchor stays the code identifier;
  "AI" is English-fallback, keyed in THEME-5). test_repo_invariants::
  test_subtabs_are_browser_style_with_clear_active_state.
- **FIELD TEST 2026-06-19 — THEME-4 FULL LANGUAGE NAMES (#52/#53, slice 1; branch
  claude/gallant-bohr-1cogzj; frontend, node-checked + invariant-guarded, BROWSER-UNVERIFIED):**
  the maintainer wants the full language WORD everywhere a 2-letter code shows (except the top
  status-bar flag). Added `ooLangName(code)` — the language analog of `ooRegionName`, using the
  browser's own CLDR via `Intl.DisplayNames(type:"language")` (per-locale cached, falls back to the
  code; node-verified fr→French/français, zh→Chinese, ar→Arabic), so ZERO translation tables / ZERO
  new i18n keys. Applied to the app.js source/language surfaces: the Sources table language column
  (re-renders LIVE on `oo:langchange` via the #16 hook — names update on a language switch), the
  search-result source meta (language + country both CLDR-localised), the source-profile "Language:"
  fact, and the translation provenance `[src→tgt]` pill. The raw code is kept as a hover title where
  useful. test_repo_invariants::test_language_codes_shown_as_full_names_via_cldr. REMAINING (THEME-4
  cont.): the standalone reader's Translation tab default = current UI language + its language picker;
  alphabetical ordering of language lists; any other 2-letter-code surfaces found in a click-through.
- **FIELD TEST 2026-06-19 — P2-1 REMOVED THE "CONTROVERSIAL" SOURCE VERDICT (#50; ruling REVERSES
  the official-statistics "controversial sources" framing; branch claude/gallant-bohr-1cogzj;
  backend VERIFIED py3.11 venv):** maintainer — "users should make their humble opinions." Calling a
  source "controversial" is itself a VERDICT, so removing it INCREASES honesty (evidence-trails-not-
  verdicts). Dropped the per-source verdict everywhere: `agencies.py` to_dict no longer emits
  `controversial`; `ingest.py` tags are now `["official-statistics", region]` (no "controversial"
  tag); the agency-directory UI lost its "controversial" pill column; the register-confirm + the
  Statistics-panel description reworded (no verdict). KEPT the honest PROVENANCE transparency as a
  DESCRIPTIVE CAVEAT on the response ("an official figure is a stanced source — you judge"), never a
  label. REVERSES the just-merged #396 test: `test_every_agency_is_flagged_controversial_no_score`
  → `test_no_agency_carries_a_controversial_verdict_no_score` (asserts the field/tag is GONE, no-score
  stays); test_stats_ingest + test_eia_energy_feeds + the repo-invariant comment updated. Ledger
  official-statistics non-negotiable reworded. The reworded UI strings are English-fallback (old
  "controversial" locale keys orphaned-harmless; i18n gate stays 100%; THEME-5 re-keys).
- **FIELD TEST 2026-06-19 — P3 NETWORK/SAFETY POLISH (#5/#O-5/#64; branch
  claude/gallant-bohr-1cogzj; frontend, node-checked + invariant-guarded, BROWSER-UNVERIFIED):**
  (#O-5) the go-online TRANSITION now flashes GREEN (`--ok`, the "go" signal) and go-offline a
  calm/grounded neutral (`--muted`) — the two were swapped (go-OFF was green, go-ON the accent).
  (#5) the airplane button's hover title is now STATE-SPECIFIC ("…click to go offline…" when
  online / "…click to go online; you'll be asked to confirm…" when offline) — set in
  `_paintNetwork`, re-translated on `oo:langchange`. This needed a NEW reusable i18n opt-out:
  `data-i18n-dyn` makes the DOM walker SKIP an element whose attributes JS owns (the engine
  otherwise caches the first-seen English title and reverts dynamic swaps — the Item R trap);
  use it for any future state-dependent attribute. (#64) the PANIC-WIPE confirm/prompt/cancel
  strings now route through `t()` (the typed keyword stays literal ASCII "WIPE" — never
  locale-dependent input); ACTUAL ×12 translations belong to the THEME-5 i18n sweep (the strings
  are English-fallback now, gate stays 100%). test_repo_invariants::
  test_network_polish_go_online_green_dynamic_title_and_panic_i18n.
- **FIELD TEST 2026-06-19 — P1 MARKETS SUBTAB ACTIVE-STATE (#31, THEME-1 down-payment; branch
  claude/gallant-bohr-1cogzj; frontend, node-checked + invariant-guarded, BROWSER-UNVERIFIED):**
  the Markets category subtab kept "All" visually active after switching to another category
  (content filtered correctly, only the HIGHLIGHT was wrong). ROOT CAUSE: the universal `ooSubtabs`
  (invariant #18) captured its button array ONCE, but `_renderCommodityCatTabs` REBUILDS the nav's
  buttons on every board render and re-calls ooSubtabs; the click/keydown listeners are wired once
  (`nav._ooWired`), so the wired handler `paint()`ed the STALE/detached buttons while the freshly-
  rebuilt "All" kept its HTML `active` class. FIX (component-level, helps EVERY rebuild-driven subtab
  surface): ooSubtabs now queries its buttons LIVE (`const buttons = () => …querySelectorAll`) in
  paint/select/keydown/initial — resilient to nav rebuilds; the invariant-#18 contract (.active +
  role/aria + roving tabindex + keyboard + {select,paint}) is unchanged. PLUS the markets board now
  PERSISTS the selected category across re-renders (auto-refresh / cards↔families / time-scope) via
  `_mktCat` (falls back to "All" only if the category is no longer present), instead of snapping to
  "All". test_repo_invariants::test_oosubtabs_queries_buttons_live_and_markets_keep_selection.
- **FIELD TEST 2026-06-19 — P1 LIVE LANGUAGE SWITCH RE-RENDERS CLDR NAMES (#16; branch
  claude/gallant-bohr-1cogzj; frontend, node-checked + invariant-guarded, BROWSER-UNVERIFIED):**
  country/continent names updated only on a full page refresh. ROOT CAUSE: `ooRegionName`/
  `Intl.DisplayNames` localize names at RENDER time, but the i18n DOM walker (`apply()`) translates
  by EXACT-English-string match — it cannot re-derive a CLDR name already baked into the SVG/cells.
  FIX: `i18n.setLang` now dispatches a `oo:langchange` CustomEvent after apply(); app.js listens and
  re-renders the dynamic-name surfaces in the new locale — the world map from its CACHE (no fetch,
  host-guarded `_renderOoMapDim`) and the sources table only if already loaded. test_repo_invariants
  ::test_live_language_switch_rerenders_cldr_name_surfaces pins the event + listener + map re-render.
  Reusable hook for any future render-time-derived surface. i18n gate 100%.
- **FIELD TEST 2026-06-19 — P1 DOWNLOADS HONOUR AIRPLANE (#36/#41, completes THEME-6; branch
  claude/gallant-bohr-1cogzj; backend VERIFIED py3.11 venv):** two honesty bugs in the wiki-dump
  + OSM download managers. (1) The chunk loop checked ONLY the per-download Pause event, NOT the
  kill switch — a download started before airplane kept reading from its open socket after the
  toggle. FIX: `(stop_event.is_set() or kill_switch_active())` → a clean resumable PAUSE within one
  chunk (the kill switch must halt an OPEN download, not only refuse NEW fetches). (2) resume/start
  in airplane hit the guarded fetcher → cryptic "error". FIX: `start()` PRE-CHECKS the kill switch →
  presents PAUSED (resumable, error=None), never an error, opens NO socket (tested: http_get not
  called). The frontend `jobResume` already re-prompts go-online (ensureOnline, app.js:662), so the
  full flow is: airplane → download pauses cleanly → resume → consent → continues via HTTP Range.
  Applied to BOTH `src/wiki/dumps.py` + `src/geo/osm_downloads.py`. ALSO #36: the task-manager job
  LABEL was the raw "en · pages-articles-multistream" → now `_dump_label()` → "English Wikipedia —
  articles dump" (via wiki.languages.get_language; multistream is an internal detail). tests/
  test_download_airplane.py (start-in-airplane=paused-no-socket + mid-download pause for both
  managers + human label). REMAINING #41 reorder: backend reorder exists + is tested (test_osm_jobs/
  test_jobs_resume) — "can't reorder" is likely UI discoverability (controls show only for 2+ queued).
- **FIELD TEST 2026-06-19 — P0-4 IMPORT RECOMPUTES CORE-ENGINE METADATA (#O-1; branch
  claude/gallant-bohr-1cogzj; backend VERIFIED py3.11 venv):** maintainer ruling on restore
  semantics — AI artifacts (translations/summaries/ai_keyword) kept AS-IS, but CORE-ENGINE
  derived data (keywords, date/place/entity extraction, sentiment) RECOMPUTED on import so an
  OLD backup aligns with the improved engine. DESIGN (the safe one — leaves the SIGKILL-
  torture-tested merge SQL UNTOUCHED): the merge stays additive/verbatim (raw articles + AI
  artifacts), then AFTER the atomic swap `run_restore` calls `merge.reindex_imported_articles
  (batch_id)` → reads the imported article rowids from `merged_rows` (carried in from the
  working copy; rowid == live id) → `store.reindex_articles(session, extractor, ids)` runs
  `index_article` on each, which DELETE-then-REINSERTs that article's keyword mentions/
  counters/sentiment + when×where×who, OVERWRITING the merged-in old derived rows with
  current-engine output. `index_article` NEVER touches `article_analyses` or `ai_keyword`, so
  AI artifacts stay byte-for-byte (the verbatim half). RECONCILES with RESTORE-IS-ADDITIVE-ONLY:
  nothing is replaced/deleted at the article level — only the IMPORTED articles' DERIVED
  metadata is recomputed (the whole point of the ruling); local articles untouched (targeted
  by merged_rows, not a corpus-wide reindex). Best-effort: the restore is already committed +
  additive, so a re-index hiccup logs + degrades (report["reindexed"]) and never undoes it.
  tests/test_reindex_on_import.py (recompute + AI-verbatim; missing-ids skip; e2e targets ONLY
  merged_rows, local article untouched). MERGE-ENGINE-SYMMETRY RECONCILIATION (CI caught it):
  the re-index makes the FULL restore direction-dependent in DERIVED data (only the IMPORTED side
  re-indexes), so the torture suite's merge(A,B)≡merge(B,A) symmetry/idempotency assertions broke.
  RESOLVED honestly: `run_restore(reindex_imported=True)` default for production; the torture harness
  (torture_helper.py) passes `reindex_imported=False` to test the MERGE ENGINE in isolation — the
  re-index is a one-directional post-step with its own test, NOT part of the engine's commutativity
  contract. Full torture suite green again (10/10, run locally with PYTHONPATH for the subprocesses).
  REMAINING: surface the re-index in the restore report UI + as a task-manager job (P1/P3 items).
- **FIELD TEST 2026-06-19 — P0-3 RESTORE PREVIEW ALWAYS ANSWERS JSON (#O-3; branch
  claude/gallant-bohr-1cogzj; backend VERIFIED py3.11 venv):** two older-version backups
  failed to preview with "JSON.parse: unexpected character at line 1 column 1" — the SPA
  calls res.json() on every response, and an exception escaping `run_restore` (e.g. an old
  corpus's staged-migration failure) RE-RAISED into Starlette's PLAIN-TEXT 500. Same class
  the maintainer hit on backup-CREATE (fixed bespoke earlier). FIXES: (1) SYSTEMIC — a global
  `@app.exception_handler(Exception)` in main.py returns a JSON {detail} for ANY
  otherwise-unhandled error, so no endpoint can ever return a plain-text 500 again (the SPA
  never trips JSON.parse). (2) SURGICAL — restore_preview + restore_commit now catch generic
  Exception → HTTPException(500) with an ACTIONABLE "may be from an incompatible version: …"
  message (and re-raise HTTPException cleanly). The version-gap path (`_stage_upload` →
  ArtifactError "unsupported backup schema 'oo-backup-1'") was already a clean 400 — pinned.
  tests/test_restore_preview_robust_errors.py (old-schema → 400 JSON naming the gap;
  run_restore failure → 500 JSON not plaintext; the global handler returns JSON for an
  unhandled error). DELIBERATELY did NOT add a throwaway route to the shared app singleton
  (ledger flakiness lesson). REMAINING (P0-4): import recomputes core-engine metadata.
- **FIELD TEST 2026-06-19 — P0-2 BACKUP ENCRYPTION IS PROVABLY REAL (#O-4; branch
  claude/gallant-bohr-1cogzj, draft onto 0.09; backend VERIFIED py3.11 venv):** the maintainer
  saw an encrypted + a plaintext backup report the SAME size and asked "is it actually
  encrypted?". ROOT CAUSE = display rounding, NOT a broken cipher: `encrypt_bytes` is genuine
  AES-256-GCM + scrypt (OOENC1 header 48B + GCM tag 16B = a FIXED 64-byte overhead), so a 326 MB
  backup grows ~64 bytes and rounds to the same MB. FIXES: (1) tests/test_backup_encryption_real.py
  PROVES it — a LOW-entropy input becomes HIGH-entropy ciphertext (>7.9 bits/byte; a no-op or
  header-over-plaintext would stay low), no plaintext leak, exact +64 size, exact decrypt
  round-trip, wrong-pass loud, AND end-to-end via write_backup_v2 (encrypted artifact = OOENC1
  high-entropy that decrypts to a valid zip; plaintext = bare zip, never OOENC1). (2) HONEST
  SURFACE: `StagedArtifact.encrypted` (set from `was_encrypted` in read_artifact) flows into the
  run_restore report → the Restore-preview UI now shows an "encrypted (AES-256-GCM)" / "plaintext
  archive" verdict pill (the natural verify point), + a static backup-section note that
  same-size-is-by-design (~64B GCM overhead). New UI strings are English-fallback (keyable in the
  THEME-5 i18n sweep; the gate stays 100%). The maintainer's doubt is resolved AND now provable.
- **PERF — DENORMALISED KEYWORD COUNTERS, SLICE 1 (the structural cold-cost win; perf workstream
  field report 2026-06-18; branch claude/nice-sagan-tompbw, draft PR onto 0.09; backend VERIFIED py3.13
  in a built .venv313):** `Keyword.mention_count` (SUM of per-article occurrence counts) +
  `Keyword.article_count` (DISTINCT articles) + `idx_keyword_mention_count`, maintained AT INDEX TIME so
  the hot whole-corpus aggregations can later read an indexed counter instead of GROUP BY-ing the 829k-row
  keyword_mentions table (the join dragged whole article pages through the SQLCipher codec). Honest COUNTS,
  no score. SLICE 1 is ADDITIVE + maintained + backfilled + TESTED with NO query rewrite (behavior-identical
  — nothing reads them yet; slice 2 rewrites top_terms + _supergroup_totals). DRIFT DECISION (the hard part):
  INCREMENTAL ±, not per-keyword recompute — there is exactly ONE KeywordMention row per (keyword, article)
  (the unique (keyword_id,article_id) index), so re-indexing one article moves article_count by at most ±1
  and mention_count by (new occ − old); `index_article` captures the article's PRIOR contribution before the
  delete-then-reinsert, accumulates the new, and applies the net delta (`_apply_keyword_counter_deltas`) — O(article
  keywords), never a corpus scan, drift-proof by the unique-row property (recompute-per-keyword was rejected:
  it would scan a hot keyword's full mention set per re-indexed article). Counter writes ride the existing
  single-writer gate via the index_article session (no second gate). `backfill_keyword_counters` = the one-pass
  authoritative repair (GROUP BY → bulk update, zeroes mentionless keywords). Self-heal at boot
  (`ensure_keyword_counter_columns`, wired before ensure_hot_indexes since the index needs the column) ADDs the
  columns+index then BACKFILLS once from live mentions (the live DB isn't auto-alembic'd); migration
  a2b3c4d5e6f7 (off the single head e1f2a3b4c5d6) does the same on staged/alembic DBs — both VERIFIED here to
  produce identical counters on a simulated old-schema DB. tests/test_keyword_counters.py (8): the KILLER
  assert_counters_match_join (every stored counter == the live GROUP BY) across ingest, re-index-same-article-
  twice (not doubled), changed-content (decrement to 0), distinct-article-vs-occurrence, backfill-repairs +
  non-vacuous (a corrupted counter raises), zeroes-orphans, backfill_corpus path; PROVEN non-vacuous (sabotaging
  the old-contribution decrement fails exactly the two re-index tests). mypy 120≤127 (0 new), ruff F/B clean,
  58-test keyword/insights/store regression batch + test_migrations single-head + repo invariants green.
  SLICE 1 MERGED (#392).
  **SLICE 2 SHIPPED (the actual perf win; branch claude/nice-sagan-tompbw-s2 stacked on slice 1, draft PR onto
  0.09; backend VERIFIED py3.13):** `top_terms` CORPUS-WIDE path (no days/country — the hot `/api/insights/top?
  group=true` Home view + the layered_graph family/supergroup levels) now reads `Keyword.mention_count`/
  `article_count` via the indexed ORDER-BY scan (`idx_keyword_mention_count`, `mention_count>0` reproduces the
  inner-join "has mentions") instead of joining + GROUP BY-ing keyword_mentions; the WINDOWED path (days/country)
  KEEPS the mention aggregation (counters are corpus-wide, can't serve a scoped SUM). `_supergroup_totals` (the
  prior perf fix already resolved member ids first) now reads the counters off those ids — NO residual mention
  join/scan (a hot member like "government" no longer scans its full mention set). HONEST SCOPE: trending/
  trending_windows are inherently observed_on-WINDOWED and map-coverage's keyword path is grouped-by-COUNTRY, so
  the corpus-wide counters DON'T apply there — left on the join (documented, not forced). Byte-identical for any
  CONSISTENT corpus (counters==join by the slice-1 invariant): tests/test_keyword_counter_queries.py (6) compares
  the counter-based top_terms to an inline join reference (values + tie-free ordering + kind filter +
  excludes-no-mentions + grouped families + windowed-path-still-scopes). FIXTURE FIX (the one non-obvious cost of
  denormalisation): test_supergroups/test_super_rings/test_keyword_equivalence seeded KeywordMention rows directly
  WITHOUT counters (a state index_article never produces) → made consistent (inline counters or a backfill call,
  mirroring production). mypy 120≤127 (0 new), ruff F/B clean. The denormalised-counters perf lever is COMPLETE.
- **PERF — CACHE THE PER-QUERY ANALYSIS ENDPOINTS (perf workstream, field report 2026-06-18; branch
  claude/perf-graph-assoc-cache, draft PR onto 0.09):** /api/insights/associations (76s) + /graph (103s)
  are whole-corpus co-occurrence/PMI (genuinely heavy, not a simple pathology), explored ON-DEMAND by term.
  Extended the #372 TTL cache (`_cached`/`_ckey`, computed_at+cache_ttl_s+cached flag) to BOTH: associations
  keyed by (term,limit,min_cooccur,group); the term/level layered_graph keyed by (level,term,hops,days,
  start,end); the article-set article_graph keyed by the exact id set. So re-opening the same term's
  mind-map / associations (the common explore-back-and-forth) is INSTANT; the first open still computes
  (cold cost unchanged — that needs the deeper co-occurrence optimisation or denormalized counters, flagged).
  tests/test_insights_cache.py +test_associations_endpoint_is_cached (2nd same-term call is a hit, a
  different term recomputes). REMAINING: denormalized keyword counters (the structural cold-cost win); cut
  Home poll frequency; graph/associations FIRST-open optimisation.
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
  **DIAGNOSTIC BATCH ANALYZED 2026-06-21 (maintainer sent 8 logs from the live 29k-article /
  2.4M-mention / 1 GB-encrypted corpus; branch claude/keen-lamport-b4t3rh, PR #420):** SHIPPED the
  log-driven fixes: (a) STOPWORDS — a conservative 2026-06-21 `_EXTRA_STOPWORD_TEXT` batch from the
  analyzer's high-confidence bucket (more CSS leaking into the `?` unknown-lang bucket: div/span/
  max-width/font-size/font-family; de weekday `sonnabend`; pure grammar in es/it/pt/pl/sl/sv/nb/tr —
  accented-or-unambiguous-grammar rule, content/homographs EXCLUDED e.g. law/city/power/company/
  market/media/newsletter/twitter/table/width all LEFT as content); (b) DATE VOCAB — Greek (el, was
  8.5% cov, in_month_vocab=FALSE) + Slovenian (sl, 6.2%) month names (nominative+genitive) added to
  `dateextract._MONTHS`, VERIFIED live ("5 Μαΐου 2024"→2024-05-05, "5. junija 2024"→2024-06-05);
  tests/test_dateextract.py + the stopword self-test cover it. FLAGGED (bigger, not in this batch):
  (1) PERF — `/api/insights/trending-windows` is the #1 hotspot at ~20s idle / ~98s under load (it's
  observed_on-WINDOWED so the corpus-wide counters don't apply) — **ADDRESSED 2026-06-21 with a
  COVERING INDEX rather than the brief's drift-prone rollup (the honest engineering call; see the
  shipped-log "TRENDING COVERING INDEX" entry): `ix_mention_date_keyword (observed_on, keyword_id,
  count)` turns `trending()._counts` from a per-row HEAP-decrypt range scan into an index-only
  ("USING COVERING INDEX") scan — zero drift, no new table/backfill/maintenance code, query logic
  unchanged. The remaining ~98s-under-load is the TTL cache going cold while the server is busy;
  warm_cache + the index now make cold recompute cheap (a per-day rollup is still the option if the
  index proves insufficient on the live corpus — measure first).** associations ~6s (busiest keyword
  'important'=42k mentions), supergroups cold ~15s; the persisted COLUMNAR store is unavailable
  (in-memory) pending the httpfs crypto-extension packaging decision; activity+vitals polled 1281×
  in 26 min. (2) The `?` unknown-language bucket = 36,519 keywords (CSS/HTML leak = an HTML-stripping
  gap before extraction, the real root; stoplisting the markup only mitigates) — **ROOT-CAUSE FIX
  SHIPPED 2026-06-21 (branch claude/amazing-tesla-z6bwkm, see the shipped-log "MARKUP STRIP AT THE
  EXTRACTION CHOKEPOINT" entry): `BaselineExtractor.extract`/`SpacyExtractor.extract` now `strip_markup`
  the body before tokenising, so a re-index drains the bucket and any future leak is caught by
  construction** (already-stored BARE CSS without tags — pre-2026-06-20 .eml — still needs a re-import,
  the standing path). (3) translation_coverage
  11.8% / tag_coverage 0% (run the baseline-tag backfill on this corpus). (4) no_stoplist langs
  (uk/tr/ro/ur/th/cs/ca/fi/hi/et/vi/sk) + zh/ja unsegmented still leak. (5) network preflight: the
  50-source sample was all `unreachable` (likely the Tor/airplane population, not a bug — re-check
  online). Full prioritised report handed to the maintainer in chat.
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
  **PAGED / FULL EXPORT ADDED 2026-06-21 (maintainer: "the diag tools don't offer to send
  MORE keywords despite there being 200k+"):** the export was limited not by the byte cap
  but by `_MAX_KEYWORDS_PER_LANG=5000` — only 137k of 461k were exported. Measured: 137k
  keywords = 4.4 MB compressed, so the 20 MB cap can hold ~625k → the WHOLE corpus fits one
  archive. Added `?format=zip&per_lang=N&page=P` (ZIP-only; bounded per_lang≤1,000,000,
  page≥1): `per_lang` raises the per-language quota (page through with `page`), the manifest
  now reports `per_lang/page/pages_total/has_more/keywords_total_corpus` so the full set can
  be exported across digestible files. The JSON path is UNTOUCHED (eff_per_lang=_MAX, lo=0,
  page ignored → byte-identical; contract intact). The heavy per-keyword language-signature
  scan barely grows (tail keywords are low-mention). A new "Download ALL keywords (.zip)"
  Settings button uses `per_lang=1000000` (one ~15 MB archive of all 461k). tests/
  test_keyword_log_zip.py::test_keyword_zip_paging_exports_more_and_walks_the_full_set
  (page 1≠page 2 disjoint, has_more, full export = whole corpus).
