# CLAUDE.md — long-term session memory (maintainer-mandated)

**THE PROTOCOL (meta-rule, maintainer-mandated):** this file is the single
ledger of every maintainer ruling. (1) Read it in full before any work, every
session. (2) Record every new ruling HERE in the same turn it is given — a new
INVARIANT under UI invariants, a PENDING ruling under the Open queue; SHIPPED
work goes to the CSV per (5a), not inline. (3) If the maintainer repeats
feedback, that is a ledger failure: fix the gap AND the ledger. (4) Critical
invariants are ALSO enforced by
`tests/test_repo_invariants.py::test_ui_invariants` — extend that test whenever
one is added here. It exists because work regressed between sessions (the
Wikipedia dropdown became a text input) and the maintainer had to repeat
earlier rulings. (5) Compress SHIPPED entries to verdict + pointer when the
file saturates (maintainer-asked 2026-06-12) — details stay in git history,
`docs/CHANGES.md` and the named design docs; NEVER compress away a pending
ruling, a contingency, or a deliberate-omission note. (5a) **SHIPPED WORK IS
TRACKED IN A CSV, NOT INLINE HERE (maintainer-asked 2026-06-25, to keep this
file readable):** record newly-shipped work as a ROW in
[`docs/ledger/shipped.csv`](docs/ledger/shipped.csv) (date · area · item ·
status · refs · key_paths · summary). If it carries a reusable LESSON or
EMPIRICAL FACT, ALSO (a) append the verbatim entry to
[`docs/ledger/SHIPPED_LOG.md`](docs/ledger/SHIPPED_LOG.md) and (b) copy the
lesson into the Session-rituals "Lessons" subsection (so first-readers see it).
Do NOT grow a "## Shipped batch log" wall in this file again. Pending rulings,
contingencies, and deliberate-omissions STILL go in the Open queue as prose
(rule 5 protects them — never moved to the CSV).

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
- **The current cycle branch is `main` (version `0.3.0`), the measured-and-verified cycle.**
  The maintainer renamed the default branch `0.2 → main` PERMANENTLY on 2026-07-15 —
  the branch name and the version number are independent, and version flips no longer
  rename the branch. Cut/rebase branches from `origin/main` and open PRs onto `main`;
  `git fetch` the tip first. Version single-sourced from pyproject (`0.3.0`).
  Historical `0.0.8`/`0.08`/`0.09`/`0.1`/`0.2` tags + "draft PR onto 0.09"/"onto
  0.1"/"onto 0.2" shipped-log entries are RECORDS of when those were the branch, not
  the current one. **`v0.2.0` IS TAGGED (2026-07-18, maintainer):** the maintainer ran
  the S1 push-button P0 validation job on the live corpus and tagged — the 0.2
  data-safety-at-scale cycle is CLOSED as a tagged release (the sequencing ruling +
  the flip record are in the Open queue, 2026-07-18). The 0.3 cycle = the recursive
  improvement loop v1 + the six delegated 2026-07-18 calibration executions + the law
  vertical + the browser-verification burn-down (V1_PATHWAY §3's 0.3 step).
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
   when idle). (`#vitals-mini`
   retired; the 5 s chrome poll is now network-only — a bonus against the
   polling-storm finding.) Enforced in test_ui_invariants (#4).
   **AMENDED 2026-07-23 (maintainer answer 9, SHIPPED same day, browser-unverified
   per fork-3): the VERSION is now DISPLAYED in ONE place — visibly under the brand
   name in the sidebar** (`<span id="version">` unhidden, filled by loadHealth; the
   top BAR still never shows it). SAME ruling added the **top-bar collection-speed
   KNOB** (`#rate-toggle`, gauge icon + needle, accent `.rate-max` state theme-derived
   via color-mix; toggles the governor "maximum"↔"target 500 KiB/s" through a
   loopback `PUT /api/scheduler/config` — no egress, so NEVER ensureOnline-gated;
   syncs the Settings speed slider via applySchedConfig; applies next pass). Both
   enforced: test_ui_invariants #4 (version-in-brand) +
   test_rate_mode_knob_in_top_bar_and_maximum_default.
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
   **AMENDED 2026-06-23 (FLIP-CARD REDESIGN — maintainer-directed): the briefing card is
   now a two-sided FLIP card** (front = the lead at a glance; back = caveat + method +
   why + evidence + the action). The caveat MOVED OFF THE FRONT (it "took too much
   space") onto the BACK — but this STILL satisfies informed-consent-by-LAYERING because
   the back is an EQUAL side of the card revealed by ONE flip (a click), NOT a calm-UI
   toggle/checkbox/`[hidden]` block: it is in the DOM by default, rendered in the visible
   `.card-caveat` line right BESIDE the "Open corpus" action, so the user reads the
   warning exactly as they go to explore. The front is decluttered; the per-card "?"
   affordance (P2-2 infoBlock) is RETIRED — the flip IS the detail layer. test #23
   updated: the caveat renders in `.card-caveat` on the `card-face card-back` (NOT the
   `card-front`), the method renders on the back, and `leadFlip`/`openCardCorpus`/the
   `?corpus=` boot deep-link exist. (Full flip-card entry in the Shipped-batch-log
   2026-06-23.) REMAINING nicety: also surface the caveat INSIDE the analysis window the
   corpus opens (today it travels on the back beside the open action + the analysis has
   its own per-subtab caveats).
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
- **Field-test mode is OPT-IN since 0.1 (flipped 2026-07-02 for the public tag;
  was default-ON during the 0.0.8/0.09 live-test cycles):**
  `src/monitoring/field_test.py` (`OO_FIELD_TEST=1` enables)
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
  "[new branch]", the previous PR was merged — open a NEW PR onto `main` (the
  current cycle branch; was `0.2` before the 2026-07-15 rename, `0.1` before the
  2026-07-10 rename, `0.09` before that).
  COROLLARY (near-miss 2026-06-15): local `origin/main` goes STALE within
  minutes given the fast merges — ALWAYS `git fetch origin main` immediately
  before `git checkout -B <branch> origin/main`, or a doc/ledger branch can be
  cut from a pre-merge base and a 3-way merge could drop a just-merged ledger
  edit on the same lines. (Caught when a finding-F ledger update branched from a
  stale base and the entry was missing; re-cut from a freshly-fetched tip. This
  is the SAME hazard as the 2026-07-02 stale-base revert incident below — always
  rebase onto the FRESH default tip before merging.)
- Never use backticks inside `git commit -m` heredocs (shell substitution).
- Update `docs/product/RELEASE_0.1_RC_GATE.md` rows you close, every session.
- Lessons that cost a bug: duplicate top-level JS function names silently
  override — grep before declaring. Sizes lie, diffs don't (`git diff
  --numstat` before fearing loss). A ledger merge is NOT resolved until
  `grep -n '^<<<<<<<\|^=======$\|^>>>>>>>' CLAUDE.md docs/ledger/shipped.csv`
  returns nothing — the 2026-07-18 b9dcbcc merge committed unresolved conflict
  markers INTO CLAUDE.md on main because only shipped.csv was verified (fixed
  same day; both sides were kept additively, as the ledger rule requires). Agent findings get hand-re-verified before
  shipping (the 06-audit false-positive lesson). NEVER switch git branches while
  a background test suite is running (2026-07-09: a checkout mid-run made a
  SUBPROCESS-spawning determinism test import the OLD code from the mutated
  working tree → a phantom suite failure that took a clean re-run to disprove;
  same family as the review-agent checkout-restore hazard — the working tree
  belongs to the running suite until it finishes). Tests must NEVER assert
  POSITIVE facts against the shared mutable `src.api.main.app` singleton's
  `.routes` — that process-global read made the additive-restore guard flaky in
  CI (1 failed on `/v2/restore` absent, never reproducible locally even per a
  full-suite per-test route watcher); anchor route guards to IMMUTABLE sources
  (each router's own `router.routes` definitions + the `include_router` wiring
  in `src/api/main.py` source). Negative `not in app.routes` checks stay safe (a
  missing route can't fail them). And THE LEDGER ITSELF can carry a committed merge
  conflict: the #708 merge landed literal conflict markers on main's CLAUDE.md (the two
  sibling 2026-07-18 sessions' Open-queue entries; found + union-resolved 2026-07-18,
  both sides kept per the additive rule) — after merging parallel-session PRs, grep
  CLAUDE.md for conflict markers before trusting it.
- **Lessons harvested from the shipped log (the reusable ones; full context in
  `docs/ledger/SHIPPED_LOG.md` + git history):**
  - **GitHub release assets carry an ATTESTED `digest: sha256:…` field:** to verify a
    downloaded installer/binary WITHOUT fabricating a checksum (a §0.5 non-negotiable),
    fetch the `releases/latest` JSON, read the asset's own `digest`, and verify the
    downloaded bytes against it; refuse on mismatch OR when no digest is attested. This
    resolved the long-standing "we can't fabricate per-OS Ollama checksums" blocker
    (the in-app Ollama binary installer, `src/llm/installer.py`, 2026-06-30).
  - **SQLCipher codec column-order PERF TRAP:** a SQL join from `keyword_mentions`
    to `articles` for ONE small column drags whole ~35 KB article rows through the
    SQLCipher codec (column order puts `content` before `language`) — measured ~26 s
    of a 32 s wall. Read small denormalisable facts via a COVERING INDEX or a
    one-pass Python map, never that join. Corollary: MEASURE (EXPLAIN QUERY PLAN +
    time on the real encrypted DB) BEFORE adding a drift surface like a per-day
    rollup — a covering index is zero-drift and was the right call for trending.
  - **No-score tests check field NAMES, not `repr()`:** a caveat that legitimately
    says "never a score" trips a naive `repr(out).lower()` substring check. Walk the
    dict KEYS recursively for `score`/`ranking`/etc. (grep `repr(.*).lower()`+score
    before shipping). Cost: a red `test` + `Core-only` lane.
  - **Run mypy in the sandbox:** `pip install mypy==2.1.0` works on py3.11 and
    type-checks CHANGED FILES via their real import closure even without project
    deps. The ratchet is a BLOCKING gate; `py_compile` + `ruff F,B` do NOT catch
    type errors. Run `python3 -m mypy <changed.py>` on every Python change.
    **USE THE PINNED VERSION, AND CHECK THAT IT ACTUALLY CHECKED (2026-08-03, the
    #853 ratchet breach):** the ambient `/root/.local/bin/mypy` is 1.19, which hits
    `src/database/write.py:147: Expected '('` on this tree's py3.13 syntax and then
    prints **"errors prevented further checking"** — it reports 3 stub/syntax errors,
    says nothing about your files, and exits. That reads exactly like a clean run of a
    file with no type errors, so a pre-push check can pass while checking NOTHING; two
    real errors in a brand-new module reached `main` that way, and because the
    maintainer fast-merges, they breached the ratchet on the default branch and
    reddened the next PR rather than their own. Install the pyproject-pinned
    `mypy==2.3.0` into the project venv (`TMPDIR=<repo>/.tmp-pip .venv/bin/python3.13
    -m pip install mypy==2.3.0 types-PyYAML` — TMPDIR per the recorded pip lesson) and
    reproduce the CI command verbatim: `python -m mypy src/ | grep -c " error: "`.
    THE TELL is the count: it must be a number near the baseline, not 3 — a
    two-digit-smaller count means the run aborted, not that the tree got cleaner.
    And when the count IS above baseline, diff against a worktree at the merge-base
    rather than assuming it is yours; the errors may already be on `main`.
  - **CI-only tests + the standalone-repro pattern:** the guarded fetch factory pulls
    in `cryptography` (pyo3 PANIC in the bare sandbox) and the ORM pulls `bleach`
    (often absent) — so endpoint/ORM/fetch tests are CI-only. Prove the ALGORITHM
    here with a standalone py3.11 repro against the PURE module (e.g. `parse_csv` /
    `_parse_period`), then let CI run the real test. (`pip install bleach sqlalchemy
    pytest` lets the ORM/store tests run locally; `cryptography` won't.)
  - **A wiring/route test must COMPOSE the actual route** (router prefix + decorator
    path) and match it against the caller — never assert the two strings side by
    side (that passed while a `/api/backup/...` vs `/api/backup/v2/...` mismatch
    404'd in the field).
  - **Literal BOM in source `lstrip`:** use the `"\ufeff"` escape, never a pasted BOM
    char (Edit can't distinguish it; it recurred in `sdmx.py`/`bulk.py`/`fetch.py`).
  - **Tests + timestamps/async writers:** never compare a hardcoded timestamp against
    a real-`now` marker (it flaked by time-of-day); an autouse gate-leak assertion
    must WAIT/drain for the app's own legitimate background writers (the briefing
    refresh daemon) before failing. The macOS "Portability observation" lane is
    observation-only but catches these timing/portability flakes FIRST — investigate
    it before the blocking lane hits the same thing.
  - **`merged ≠ green`:** the maintainer fast-merges PRs even with a red `test` lane,
    so a real failure can persist into the next PR on `0.09` — don't assume a merged
    base is green; a webhook CI-failure on a *merged* SHA may be a stale/out-of-order
    delivery (check the HeadSHA against your branch tip).
  - **DERIVED-ROLLUP SCALING lessons (5A-bis, 2026-07-01, D2/D3/serve):** (a) THE
    DELETE-THEN-REINSERT EPOCH TRAP — `index_article` deletes-then-reinserts an article's
    mentions, so an id-watermark INCREMENTAL rollup (tail = `id > watermark`) DOUBLE-COUNTS
    across ANY re-index/prune (the old contribution stays in the rollup AND the re-inserted
    higher-id rows re-add); guard every derived-append rollup with a CORPUS EPOCH bumped by
    exactly the non-append mutators (re-index/prune/restore), a changed epoch forcing a FULL
    rebuild — never an incremental merge. (b) IN-MEMORY COLUMNAR **DOES** WIN FOR *WINDOWED*
    QUERIES in a long-running process (build-once-serve-many): the earlier "in-memory gives
    no gain over the counters" finding was specific to the corpus-wide `keyword_agg` (the
    Slice-2 counters already win there), NOT the windowed `keyword_daily` rollup the counters
    CAN'T serve — so the persisted store (D1/httpfs) is a DURABILITY win (survive restart / no
    per-process rebuild), not the only path to the windowed speedup. (c) the rollup's summed
    `articles_on_day` is an UPPER BOUND on distinct articles BY STRUCTURE but EXACT today under
    the unique `(keyword_id, article_id)` index (gap 0, parity-tested) — disclose the bound the
    structure guarantees, not the value it happens to yield. (d) new dynamic SQL in
    `columnar.py` trips the BLOCKING bandit B608 gate even with constant fragments + bound
    params — add `# nosec B608 - <reason>` per the merge.py/diagnostics.py convention (ruff
    selects no `S`, so no `# noqa: S608` needed; verify with `pip install bandit==1.9.4` then
    `bandit -r src -ll -q` → exit 0). (e) comparing rollup-served vs live top-N is FLAKY at the
    LIMIT cutoff when mentions TIE (DuckDB vs SQLite order ties differently) — test parity
    ORDER-INSENSITIVELY or with a limit large enough to include every term (no cutoff).
  - **FastAPI streamed JSON** must use compact separators `(",",":")` for byte-parity
    with `JSONResponse`. **Install:** pip unpacks big wheels in `TMPDIR` (=/tmp =
    tmpfs on Qubes) → `Errno 28` even with disk free; point `TMPDIR` at the install
    volume + classify disk-full vs network failures honestly.
  - **A FastAPI `async def` handler runs ON the event loop; only a plain `def`
    handler gets the threadpool (2026-07-02, field report "stuck on Previewing… for
    an hour").** So heavy SYNCHRONOUS work inside an `async def` (decrypt a GB, copy
    the live corpus, run the merge) freezes the ENTIRE single-worker server for its
    whole duration — every other request (task manager, polls, the UI) stalls, and the
    app looks hung. The restore preview/commit were exactly this (`restore_preview` did
    a full corpus-copy + dry-run merge on the loop). FIX = `run_in_threadpool(...)` the
    blocking body (extract a `_*_sync` helper), or make the handler `def`. This is the
    SAME single-worker-freeze family as the unlock-blocking + task-manager-never-loads
    bugs: never do multi-second synchronous work on the event loop.
  - **STOPLIST ARCHITECTURE — the safe mental model for adding stopwords (2026-07-01,
    #525/#528/#530):** two channels with OPPOSITE collision behaviour. (a) `global_stopwords()`
    (`src/analytics/extract.py`) = `_EXTRA_STOPWORDS` ∪ English `default_stopwords` ∪
    `get_stopwords(en)` ∪ `get_stopwords(fr)` = LANGUAGE-AGNOSTIC → collision-PRONE: a word
    here hides the same spelling in EVERY corpus language, so it needs cross-language review
    (NEVER globalise a word that is content elsewhere — e.g. English "content" = French
    "happy"; use the plural "comments" not fr "comment"=how). Latin additions want
    length≥4/accented-only. (b) the SCOPED channel (`StopwordsManager.scoped_stopwords` =
    the vendored `configs/stopwords_iso/*.txt` + the in-code `CURATED_SCOPED_STOPWORDS`
    [temporal] + `PUBLISHING_BOILERPLATE_SCOPED` in `src/services/stopwords.py`) is
    LANGUAGE-SCOPED → collision-FREE by construction, so a FULL per-language list drops in
    freely. GOTCHA: en/fr take the `language_stopwords` branch in `get_stopwords`, so the
    scoped channel does NOT reach en/fr — an English addition MUST go in `language_stopwords`
    (= globalised, collision-checked). So: distinct-script or non-en/fr → scoped (free);
    en/fr, or anything you deliberately want global → `language_stopwords`. `build_stopwords.py`
    regenerates the `.txt` (offline; `stopwordsiso` bundles the data) — hand edits there are
    overwritten, so curated words live in the in-code dicts. sr/bs share BCS (bs aliased to hr).
  - **OPEN-CLASS keyword garbage has NO safe blanket rule (2026-07-01, #530):** function-word
    garbage is solved by stopword lists, but adjectives/common nouns are DUAL-USE (health/policy/
    state are topics AND noise) and there is no POS tagger — a category sweep deletes real topics.
    The honest levers are corpus-statistical DF-ubiquity DETECTION (`analyze_keyword_log.py
    --generic-terms` — propose, human judges, never auto-apply) + a TIGHT English-precedented
    platform/closed-class batch (podcast/newsletter/cookies + indefinite pronouns). Inflected
    generic VERBS (zeigen/voir/finden) are lemmatization territory (P4.3, gated on the eval
    harness), not a surface stoplist. **MEASURE-FIRST:** filter an exported keyword log through
    the CURRENT stoplist before analysing — a log exported before a stoplist change OVERSTATES
    garbage (nearly re-targeted German function words already fixed by #525); the user's real
    exported logs sit in the session scratchpad (`fixed_log.zip`) and are the way to measure a
    batch's true impact (e.g. #530 = 43 rows / 20,747 mentions).
  - **VERIFY-BEFORE-PUSH under fast-merge (2026-07-02, #542→#544):** the maintainer merged a
    date-extractor PR while adversarial verification was still RUNNING — six real defects landed
    on 0.09 and needed a follow-up. Rule: parallel skeptic agents (distinct lenses) must COMPLETE
    and their reproducers must be pinned as tests BEFORE `git push` — "draft PR" is not a review
    gate here. Applied to #545, where two pre-push skeptic rounds each refuted the first cut.
  - **CJK REGEX BOUNDARY FACT (2026-07-02, #545):** ideographs are `\w` in Python `re`, so `\b`
    NEVER fires between an ideograph and an ASCII digit — glued dates ("报道于2024-06-11发布")
    were invisible to the extractor AND the diagnostics probe (field coverage undercounted).
    Fix = explicit digit-safe lookarounds (`(?<!\d)(?<![A-Za-z_])`) that block the same ASCII
    neighbours `\b` blocked; keep the digit rule for ALL scripts (never carve a date out of a
    longer numeral). COROLLARY lockstep rule: every extractor vocabulary/pattern gain lands in
    `datediag.py` the SAME commit, or the probe reports phantom gaps.
  - **SQLite EXPLAIN QUERY PLAN scan classification (2026-07-02, PR #567, recursive-log #3):**
    SQLite marks BOTH a bare table scan AND an index-only scan with the word `SCAN` — a
    `SCAN <table> USING [COVERING] INDEX …` is HEALTHY (index-only), and the only scaling
    smell is a bare `SCAN <table>` with no `USING`. A slow-query/EXPLAIN diagnostic that
    flags every `SCAN` cries wolf on covering-index scans; classify on the presence of
    `USING`. (`src/monitoring/slowquery.py`.)
  - **A diagnostic log must degrade, never 500 (2026-07-02, PR #567):** the recursive-
    augmentation logs run raw SQL over the live store; a genuinely missing/corrupt table
    (or a non-SQLite backend) must return a structured `{error/skipped}` field, not a
    traceback — wrap each risky query and mark it degraded (StatementTimeout re-raised so
    the deadline still bites). The debug-bundle `_safe()` wrapper does the same at the
    aggregator level so one failing log never aborts the bundle.
  - **ENDPOINT TESTS MUST OVERRIDE get_db, NEVER SEED SessionLocal (2026-07-06, PR #577):**
    an endpoint test that needs seeded data must seed its ISOLATED fixture engine and route
    the handler to it via `app.dependency_overrides[get_db] = lambda: session` (cleaned up in
    a `finally`). NEVER open a raw `SessionLocal()` (the shared process/data_dir DB) and commit
    rows into it — that DB persists across the WHOLE pytest session (conftest binds one
    `OO_DATA_DIR`), so the rows pollute every later test that reads it. A wave-2 test did exactly
    this (committed a `flood` keyword + recent mentions to SessionLocal), reddening 7
    order-dependent trending/translation tests that pass alone. Same merged≠green /
    order-dependent-pollution family as the rollup-serve fix (#572) — **run a FULL-suite health
    check after every fast-merged parallel wave; per-PR CI misses cross-test pollution** because
    the polluter and victim only collide in the combined run.
  - **NO-FABRICATION SKEPTICS MUST ATTACK THE NEGATIVE SPACE (2026-07-09, the #590 Jalali
    fix-forward):** #590's pre-push verification ran 5 skeptic lenses and STILL shipped 3
    fabrication repros, because every lens verified the POSITIVE space (goldens convert exactly,
    gates hold) and none generated SHOULD-BE-EMPTY inputs. For an extractor, a skeptic must
    enumerate per pattern: every alternation member as a WORD-TAIL/fragment (Persian دی ends
    عادی/اقتصادی — month names are substrings of prose), every router FAILURE path (an invalid
    date falling through a claim-on-success router gets re-read by the generic loops under
    another calendar — the fix is CLAIM-ON-ROUTE: consume the span the moment the year says
    Jalali, add only on success), and every order-ambiguous form (day-first digits with a
    Jalali-range year: skip, never convert on an assumed field order). Each must assert `[]`.
    Corollary: `_MIN_YEAR=1000` means ANY 4-digit year that leaks past a calendar router is
    stored as a plausible medieval CE date — routers over shared numeric shapes are
    fabrication-critical, not recall tweaks.
  - **dbstat is a PER-BUILD SQLite capability — probe it, never assume it (2026-07-09, THETA
    R2 + the #606 macOS fix-forward):** SQLITE_ENABLE_DBSTAT_VTAB is a compile flag: the
    bundled sqlcipher3 NEVER has it ("no such table: dbstat"), Linux stdlib sqlite3 has it,
    and the macOS CI runner's Python build does NOT (the observation lane caught two
    `available is True` assertions red at #606's head SHA — merged≠green). So dbstat-based
    introspection (the P1.5 storage-composition diagnostic) DEGRADES on the encrypted live
    store AND on some plaintext platforms: design it with an honest `{available:false,
    reason}` block + the PRAGMA-level facts (page_size/page_count/freelist_count work
    everywhere), TEST the degrade path as a production path, and gate any
    full-split test on a runtime `_dbstat_available()` probe, not on platform guesses.
  - **NEVER key a cache on `id()` of a per-request object (2026-07-09, THETA R2):** CPython
    recycles addresses — within a TTL window a later request's Session can land on the same
    `id(db)` and hit an entry computed for a DIFFERENT engine (wrong corpus) or a pre-write
    snapshot. A "per-call" key must be a monotonic nonce (can never recur) qualified by the
    BIND; a bounded cache absorbs the one-shot entries. COROLLARY (change-gating rollups): read
    the corpus epoch with a COLUMN query, never `session.get` — the identity map hides another
    connection's bump inside a long-lived session; and gate on the epoch AND an append id tail,
    since ordinary ingest appends without bumping the epoch (a pure epoch gate freezes the
    rollup during collection).
  - **AUTOFLUSH CAN HAND THE WRITE GATE TO A READ — never enter a fetch loop on a DIRTY
    session (2026-07-09, ETA P1.8):** the single-writer gate acquires on FLUSH, and
    SQLAlchemy AUTOFLUSHES dirty state on the next QUERY — so feed bookkeeping written
    BEFORE the collector's article loop meant the loop's first dedup SELECT acquired the
    gate and held it ACROSS the article fetch (a slow Tor fetch + politeness while holding
    the gate = the field's 438 s max single write-wait; a batched loop would hold it across
    the WHOLE feed). Probe empirically — a fake session asserting
    `write_gate.stats()["held"] is False` inside `get()` — and the rule: on gate-wired
    sessions, write bookkeeping AFTER the network loop and COMMIT it before returning so the
    session leaves clean (tests/test_collect_batching.py pins both collector paths + the
    sequential shared-session case).
  - **A "STREAMING" PIPELINE IS ONLY AS BOUNDED AS ITS WORST STAGE + INCREMENTAL-IN-PLACE IS A
    DATA-LOSS FOOTGUN (2026-07-09, the P0.1 backup rework):** (a) the "already streaming"
    volumes+parity path OOMed anyway because `write_parity` loaded EVERY volume into RAM at once
    (N×512 MiB = the whole archive — 11.7 GB on the 10 GB field VM); when a path claims
    bounded-RAM, grep every stage INCLUDING the resilience/erasure/checksum layers for whole-set
    materialization (now banded, bytewise-identical, test-pinned). (b) changed-volume re-emit
    under deterministic per-slice file names would have OVERWRITTEN files the previous complete
    manifest references — an interrupted refresh degrades the last good backup (the rsync
    --inplace hazard); the safe shape is run-unique names for emissions + atomic manifest swap +
    garbage-collection only AFTER finalize. Corollary: file names in a manifest anyone can
    self-sign are traversal-guarded before verify/restore touches the filesystem (a signature
    proves consistency with the EMBEDDED key, never trust). Full entries in SHIPPED_LOG 2026-07-09.
  - **TRAVERSAL-GUARD EVERY NAME→PATH FIELD, ATOMIC-SWAP THE CANONICAL ARTIFACT, AND TEST THE REAL
    PATH (2026-07-10, the post-merge audit of the Round-2 backup wave):** the same backup engine's
    hardening pass (draft PR `claude/zeta-hardening-audit`) shipped WITH a traversal guard on
    `members[].name`/`volumes[].name` — but MISSED the top-level `corpus_member`/`wal_member` and the
    per-member `members[].volumes[]` refs, which restore turned into `staging/<name>` + `unlink` = an
    arbitrary-file DELETE of the LIVE corpus from a self-signed hostile backup. RULE: enumerate EVERY
    manifest/config field that becomes a filesystem path (not just the ones literally named "name")
    and run them ALL through the one guard, on BOTH the verify and restore paths. (b) the crash-safe
    corollary above was stated but the code still wrote the NEW unsigned/parity-less manifest OVER the
    canonical `dest/volumes.json` before signing+parity — a crash/kill/parity-failure in that window
    left an unsigned-complete manifest that `cleanup_cancelled_build` (unsigned⇒disposable) then
    DELETED, previous backup included. Build the fully-signed(+parity) manifest in memory and swap the
    canonical path in ONE atomic `os.replace`; the prior signed manifest must survive until that single
    commit point (an uncaught erasure-code ceiling — GF(2⁸) N+M<256 ≈ 128 GB corpus — must not be able
    to destroy the last good backup). (c) a TEST DOUBLE injected via a parameter (here `corpus_source`)
    BYPASSES the production code path — a fix in the real path (`_live_corpus_source`'s gate check) needs
    a test that drives the real path (monkeypatch `live_db_path`), or the test passes while the fix is
    unexercised. Also: `# nosec`/bandit runs in CI only (not the sandbox venv); the mypy ratchet counts
    import-closure errors, so verify NEW errors are in YOUR files (per-file `mypy <file>` shows 0) before
    trusting a red count. Full entry in SHIPPED_LOG 2026-07-10.
  - **OFFLINE WORD SEGMENTATION IS AN OPTIONAL SEAM, NOT A CORE CHANGE (2026-07-10, B1 segmenter):**
    to add a capability that only some installs have (zh/ja/th segmentation via jieba/janome/pythainlp),
    make it a pip EXTRA with a `segment()->[(word,offset)]|None` seam and a segmenter-aware
    `language_status()`; the whole point is that a core install stays BYTE-IDENTICAL (the `None`
    fallback runs the old tokenizer) — pin BOTH sides: the segmenter-present tests skip when the extra
    is absent, and tests that hardcoded "zh is unsegmented" must be rewritten to assert against the
    source-of-truth (`segmenter_available(lang)`), not a constant, or they flake between environments
    (installed vs not). Three empirical facts worth keeping: (a) CJK words are 2 chars (中国/政策/経済),
    so a segmented path needs `min_len=2` — the Latin 3-char floor drops real words; (b) a segmenter's
    surface tokens CONCATENATE to the input, so janome/pythainlp offsets reconstruct exactly with a
    forward-cursor `text.find(s, cursor)` (jieba yields offsets directly) — and the offset feeds a
    provenance sentence-slice, so validate `text[off:off+len(w)]==w`; (c) a status/gating check must use
    a LIGHTWEIGHT importability probe (`__import__` only), NEVER the heavy loader, or a mere
    `language_status()` call triggers jieba's prefix-dict build. The corpus-level win is that real words
    RECUR across articles (Heaps β drops from ~0.95), which is what makes aggregations meaningful — the
    per-article count is a red herring. Full entry in SHIPPED_LOG 2026-07-10.
  - **A VERDICT MUST MAP TO THE BAR IT ACTUALLY TESTED — a "pass" on a proxy is a fabricated pass
    (2026-07-12, S1 P0-validation kit):** the honesty non-negotiable "never a fabricated pass" applies
    to the VERDICT MAPPING, not only to fabricated numbers. The P0.1 bar IS bounded-RAM-at-scale, so a
    backup that merely COMPLETES at sub-2 GB (where bounded-RAM can't be measured) must report
    `not-measurable-here`, NEVER `pass` — a completion-pass over-reads as "the scale bar was met." Three
    corollaries from the same kit: (a) **AND-gating two thresholds can HIDE a real signal** — a collector
    climb heuristic `ratio>1.5 AND abs>512 MB` misses the OOM signature at a HIGH baseline (a +1.9 GB
    climb on a 4 GB base is only 1.48× → not flagged, and the reason literally said "stayed flat" while
    the numbers rose); use the absolute-rise signal that holds at any baseline and never assert "flat"
    against climbing numbers. (b) **a "scrub"/guard named for a safety property must ENFORCE it** — a
    pass-through `_scrub` no-op gives false assurance; make it a real recursive redaction so the
    endpoint's secret-safety is a PROPERTY, not a convention every future report author must remember.
    (c) **a read-only diagnostic is only as good as its retention** — reading `recent_samples()` over a
    ~2 h-trimmed log can't see a multi-day leak; state the window limit honestly and point at the durable
    signal (memory-guard state + a clean previous-session end), never let the how-to promise more than
    the mechanism delivers. Full entry in SHIPPED_LOG 2026-07-12.
  - **A BACKUP-PATH PROBE THAT STAGES ON THE OPERATOR'S EXTERNAL DRIVE ESCAPES THE data_dir JANITOR —
    give it a swept prefix (2026-07-12, S1 P0.2 restore probe):** a staged-restore probe needs the disk
    room a 100 GB plaintext conversion + working copy demands, so it stages under the operator's DEST
    drive, NOT `data_dir()`. But the boot janitor (`sweep_stale_backup_temps(data_dir)`) and the forensic
    inventory only scan `data_dir`, so on a hard-kill mid-probe the leftover — which for an ENCRYPTED live
    corpus contains a PLAINTEXT staged copy (an at-rest-encryption concern) — is orphaned, unseen, on the
    external drive. Fix: name the probe dir with the engine's swept `.restore-` prefix (so a subsequent
    `write_stream_backup(dest)`'s own sweep reclaims it after the 24 h age guard) + sweep the dest at run
    start + document the manual `.restore-*`-delete recovery. Verify a diagnostic's temp against BOTH
    reclaim paths (janitor scope AND drive), not just its own finally. Full entry in SHIPPED_LOG 2026-07-12.
  - **THE `TestClient(app)` LIFESPAN IS A HEAVYWEIGHT, GLOBAL-STATE FIXTURE — a suspect in subset-order
    pollution (2026-07-12, S1.1 health check):** `with TestClient(app)` runs the app's REAL startup+shutdown
    (engine init/dispose, the airplane socket guard, source seeding), all process-global. A pre-existing
    latent order-dependency exists on 0.2: running `test_a2_job_endpoints.py` before
    `test_diagnostics.py::test_doctor_healthy_returns_zero` (in a subset with a few others) leaves
    `run_doctor()`'s `session_scope().query().count()` failing → rc 1; it REPRODUCES on clean origin/0.2
    and is GREEN in full-suite order, so per-PR CI and the full run never hit it (the #577 family, but
    surfacing only under a non-default subset order). Lesson: when a health check goes red in a SUBSET,
    check clean-base + full-suite order before assuming it's your wave; a lifespan-driven client fixture
    that mutates global state is the first suspect. (Flagged, not fixed — a test-hygiene carry-over.)
  - **REPRODUCER-FIRST FOR GATE-HOLD RIDERS — a REAL hold is not a reason to fix it (2026-07-12, S2.1):**
    a write-gate hold being present is not sufficient to fix it. MEASURE the throughput ceiling
    (GIL-bound Python work gets NO gate-split gain beyond the amortised-fsync overlap — batching already
    collapses N per-article extractions onto ONE commit, so the writes are the small part of the window;
    F13's ~13 ms/article extraction-in-gate is real but splitting `index_article` is high-risk + GIL-marginal)
    and weigh the hot-path risk. And a gate held across a scan can be MANDATORY: the streaming backup's
    `_corpus_facts` MUST run inside the `freeze()` gate because the tamper-evidence article-hash commitment
    has to MATCH the streamed at-rest bytes — moving it out breaks correctness, not just risk (and it is a
    rounding error beside the multi-hour corpus byte stream). F14's autoflush mechanism cannot fire under
    `SessionLocal(autoflush=False)` (a read never flushes a dirty session → the gate is never acquired
    across a fetch). Close a DECLINED rider with the reproducer AS the evidence (a test that pins the
    property or refutes the mechanism), never a hand-wave (tests/test_write_gate_riders.py).
  - **`async def` IS A WHOLE-SERVER FREEZE; THE FIX IS `def` OR `run_in_threadpool` — AND SLOWAPI WORKS ON
    SYNC `def` (2026-07-12, S2.5):** a FastAPI `async def` handler runs ON the single event loop, so heavy
    SYNCHRONOUS DB+SQLCipher-codec work inside it freezes the WHOLE worker for its duration (the
    unlock/restore/task-manager freeze family — /api/articles was async def, measured p95 25 s). Make the
    handler a plain `def` (Starlette runs a `def` route in the threadpool) or `run_in_threadpool` the body;
    `@limiter.limit` (slowapi) DOES work on a sync `def` (verified via the suite: `Depends(get_db)` lifecycle
    + exception handling intact). For FTS search NEVER materialize the whole match to sort+paginate: resolve
    the surviving ids (fts ∩ filters) in the FINAL order via an id-only (+ sort-column) query, then load FULL
    rows for the PAGE only — content is decrypted for ≤limit rows, not the ~20k-match whole set (GAMMA-measured
    50 ms→11 ms warm at 1,776 matches; the win grows with match count). COROLLARY (caught by the S2 full-suite
    run AFTER push, fixed forward): renaming `async def view_article` → `def view_article` broke a SOURCE-INSPECTING
    test that sliced the body via the literal anchor `"async def view_article("` (IndexError). Before any
    `async def`→`def` conversion, grep the TEST tree for the old signature (this is the #283 stale-source-anchor
    family); the durable fix is an async-agnostic anchor (`re.split(r"\n(?:async )?def ", …)`), never a literal
    `async def`. And the local full suite is not optional after a push — it caught this before CI reddened.
  - **`src/api/insights._cached` IS DICT-ONLY — A SCALAR HANDED TO IT IS A SILENT NO-OP (2026-07-12, S2.5
    skeptic):** `_cached` persists + returns ONLY dict payloads (a non-dict `out` falls straight through with
    NO `.set`; a hit is recognised only `if isinstance(hit, dict)`). Handing it a scalar (an int count) makes
    the cache a SILENT no-op — correctness holds (always live/exact, so a freshness-only test passes green) but
    the optimisation does NOTHING. Wrap the scalar in a dict (`{"count": n}`) and pin a HIT with a test that
    asserts the STORE, not just freshness. (Corollary: guarding an endpoint in `guarded_read`/`_deadlined`
    bounds even a whole-table `.distinct().all()` OOM — the statement deadline's SQLite progress handler
    interrupts a runaway scan mid-query, so a full Python materialization can never complete past the deadline;
    the omnibar is the exception — it must never blank, so its guard DEGRADES to an honest empty-with-note
    payload instead of a 429/503.)

  - **A STORE HELPER THAT COMMITS INTERNALLY BREAKS ANY CALLER-OWNED SAVEPOINT (2026-07-17, the
    #691 fix-forward):** #691 wrapped index_article's when/where/who pass in `session.begin_nested()`,
    but `datestore.store_for_article`'s tail `db.commit()` CLOSES the caller's nested-transaction
    context — the NEXT statement raises "Can't operate on closed transaction inside context manager",
    which the pass swallows BY DESIGN → every article WITH a newly-extracted date silently lost its
    places/entities (main red since #691; only ONE suite test has a dated fixture = the misleading
    1-failed/3967-passed signature; a re-index restores the lost field rows). RULE: before wrapping an
    existing helper in `begin_nested`, grep it (and everything it calls) for commit/rollback; a store
    helper must be savepoint-aware (`db.in_nested_transaction()` → flush, else commit) or never own
    the commit at all. COROLLARY: a swallowed-exception design hides exactly this class of failure —
    the standalone repro calling index_article DIRECTLY (tests/test_article_dates.py savepoint test +
    the scratchpad repro) is what surfaced the real exception the production path eats.
  - **A PERSISTED DuckDB store opened via `ATTACH` REJECTS a second in-process handle to the same
    file (2026-07-12, S3.2):** `Binder Error: Unique file handle conflict`. So the in-memory
    rollup-serve model (build a fresh con, swap it in, close the old) CANNOT apply to a persisted
    file — hold ONE connection refreshed IN PLACE under the serve lock (incremental via
    `refresh_keyword_daily`; full rebuild only on an epoch change). The concurrency/incremental/
    durability logic is crypto-independent, so test it with an UNENCRYPTED file-backed duckdb; only
    the encryption is CI/operator-only. (Two plain `connect(file)` handles DO share the in-process
    instance — but the store uses ATTACH.)
  - **Adaptive backup-volume sizing must count PER-MEMBER slices, not `ceil(total/size)`
    (2026-07-12, S3.3; a pre-push skeptic caught it):** the backup slices EACH member independently
    (`_emit_member`), so the real volume count is the SUM of per-member ceils + the manifest/WAL
    members emitted after sizing — `ceil(total/vsize)` undercounts by up to one volume per member
    and could push the real N+M over the GF(2⁸) 255 ceiling → `write_parity` ABORTS (not data-loss
    — the crash-safe finalize survives — but the fix is defeated at scale). Model N exactly the way
    the emit loop emits it. The mandatory skeptic (fed the DIFF + surrounding facts INLINE so it
    never opened the 1382-line file → no context overflow, unlike the recon agents that choked on
    this repo's CLAUDE.md) is what found it.
  - **CI-installs-the-extension is the honest trust path for an offline-verified binary (2026-07-12,
    S3.1):** verify a bundled binary against a SHA-256 pin before `LOAD`; prove the MECHANISM against
    a FIXTURE binary (no real binary/network); ship the registry pins BLANK (empty-pin-stays-in-
    memory, pinned); let a CI lane install the real extension, checksum it IN-LANE, and run the real
    round trip — NEVER promoting the in-lane checksum into `external_artifacts.yml`. DuckDB gotchas
    verified empirically before writing the loader: `allow_unsigned_extensions` is a CONNECT-config
    setting (post-connect `SET` raises); `enable_external_access=False` blocks a file ATTACH
    (Permission Error), so the persisted path omits it (network safety = autoload-off + absolute-path
    LOAD + the airplane guard).
  - **DuckDB derives an extension's INIT SYMBOL from the LOADed file BASENAME split on the FIRST DOT
    (2026-07-13, columnar CI-red fix):** `LOAD '<path>'` computes the C init symbol `<name>_init` where
    `<name>` = `FileSystem::ExtractBaseName(path)` = the basename split on `.` taking `[0]`. So the
    version-dotted bundled name `httpfs-<plat>-v1.5.4.duckdb_extension` derives the BOGUS
    `httpfs-<plat>-v1` -> DuckDB looks for a nonexistent `httpfs-<plat>-v1_init` -> the LOAD fails and
    the persisted-ENCRYPTED store SILENTLY degrades to in-memory (was the "Columnar store" CI lane's red
    on the real-httpfs round-trip `test_ci_encrypted_persisted_round_trip`). FIX = LOAD the already-SHA-
    verified bytes through a per-process temp COPY whose basename is the canonical `httpfs.duckdb_extension`
    (`_canonical_httpfs_path`), so DuckDB derives `httpfs` -> `httpfs_init`. Keep the SHA pin + version
    coupling + traversal guard ON THE REAL FILE (`_verified_httpfs`) BEFORE the copy. SKEPTIC LESSON: a
    cache that verifies the SOURCE each call but hands `LOAD` an un-re-checked cached COPY makes the
    "verify-before-LOAD every call" claim FALSE for the loaded artifact — so key the cache on the verified
    DIGEST (a re-pin to different bytes at the same path invalidates) AND re-hash the COPY against that
    digest before reuse (an in-place tamper is caught, the stale copy never served). Real round-trip is
    CI-ONLY (`extensions.duckdb.org` is egress-blocked in the sandbox), so the "Columnar store" lane is the
    confirmation; the fix removes only the symbol-mangling blocker — D1/D2/D3 persisted-store still need the
    operator to bundle + pin the per-OS binaries (the registry pins ship blank).
  - **A VALUE-BEARING STRING IS ONLY TRANSLATABLE IF ITS KEY IS A FIXED TEMPLATE (2026-07-12, S4.5):**
    a flat `t()` lookup can never translate "3 of 10 articles" — the numbers vary, so it never matches
    a static key. The fix is a COMPOSITE lookup (`OOI18N.tf(template, vars)`): the KEY is a fixed
    `"{done} of {total} articles"` template (keyable ×12), the VALUES are DATA interpolated after
    translation — so the FRAME translates and the DATA does not (the same discipline as translating
    chrome but never data). Server-emitted titles ride the same seam: `Card.title_i18n` (template) +
    `title_vars` (JSON-scalar data), with the English `title` kept as the additive fallback. TWO gotchas:
    (a) a `{placeholder}` with no matching var renders a literal `{x}` — VALIDATE at construction (fail
    loud), never ship a broken frame; (b) adding a new template key to `en.json` ALONE reddens
    `--min 100` (en.json is the canonical 2020-key set; every locale must carry every key) — add the key
    to ALL 12 locale files (translations keep `{term}` verbatim). `t()`-with-an-English-string still needs
    no key (it falls back), but a `tf()` template you WANT translated must exist in the maps.
  - **AN ONBOARDING "PICK YOUR THEMES/COUNTRIES" MUST DEFAULT TO EVERYTHING, AND EMPHASIS ≠ EXCLUSION
    (2026-07-12, S4.7):** the cover-everything ruling ("scraping must cover EACH AND EVERY source;
    ordering ≠ exclusion") means a first-launch theme picker can NOT silently narrow the corpus. Two
    honesty rules: (a) `select_tags` is a FILTER (`Source.tags ILIKE`), so DEFAULT all-selected and treat
    all-or-none as `[]` (no filter = everything); a partial pick is the user's EXPLICIT, reversible focus,
    stated in the UI — never an app-chosen narrowing. (b) for a country/language EMPHASIS use the levers
    that ORDER, never exclude — `country_priority` (a `sort` key in the runner, explicitly "orders first,
    never excludes") and `language_equilibrium` (a cadence weight), NOT `select_languages` (which filters).
    And before calling a settings-write endpoint from a surface that promises "never posts the network,"
    VERIFY the handler has no egress side effect: `PUT /api/scheduler/config` is `save_settings` only (no
    kill-switch clear, no `run_now`), and `exclude_unset=True` means only the fields you send are touched.
  - **ABSORB-THEN-HIDE, BUT AN INTERLEAVED SHARED COMPONENT BLOCKS THE BLIND HIDE (2026-07-12, S4.4):**
    the Desk lesson ("never lose a tool") says retire a surface only once its replacement absorbs every
    capability. When a capability is genuinely missing, PORT it first + add a REGRESSION GUARD on the
    absorption — but the HIDE can still be unsafe: `#ins-explore` interleaves the search bar (retirable)
    with a NON-searchable overview (`#ins-landscape`, must stay) AND a RELOCATABLE shared component
    (`#mm-kit`, moved into the corpus window and back — writing to `#ins-term`/`pickTerm`). A blind
    display:none/removal browser-unverified is the interleaved-shared-helper hazard (passes `node --check`,
    breaks at runtime). So: port the missing piece, guard the absorption, and GATE the actual hide on a
    browser-verified untangle — recorded as a carry-over, not shipped on faith.
  - **A MULTILINGUAL LEXICON MEASURE MUST VERIFY THE TEXT'S SCRIPT — else a mislabelled language yields a
    FABRICATED NEUTRAL, not an honest gap (2026-07-12, S5.2 skeptic):** the whole honesty of a rule-based
    subjectivity/loaded-language scorer rests on "density 0.0 is a REAL measurement (no loaded terms),
    DISTINCT from the unmeasured gap of an unsupported language." That distinction SILENTLY COLLAPSES when
    the scorer trusts the source-asserted `language` (which the project itself treats as unreliable) and
    scans, say, a Cyrillic body against the English lexicon: 0 matches → `density:0.0` reads as "measured,
    clean" when the truth is "wrong lexicon, unmeasurable." Same for unsegmented CJK against a Latin list
    (one giant token, 0 matches). FIX = a cheap SCRIPT GUARD: compute the text's dominant script and the
    lexicon's script; on a mismatch return an honest GAP, never a fabricated 0. The negative-space lens
    (should-be-a-gap inputs) is what surfaces this — a positive-only test suite passes right over it.
  - **A SUPPLY/PHYSICAL PARSER'S "NEVER A PRICE" MUST BE AN ALLOWLIST GUARANTEE, AND GROUPED THOUSANDS ARE A
    FABRICATION TRAP (2026-07-12, S5.1 skeptic):** "this parser never emits a price" cannot rest on a
    unit-string check (it misses €/£/¥/cents/non-USD codes, and trade/consumption measures are reported in
    MONETARY terms) — narrow the MEASURE allowlist to the always-physical measures so a value-denominated
    figure can't enter at all. Two more traps a negative-space pass caught: (a) `float("350,000")` raises →
    a REAL published figure silently becomes a fabricated `value=None` GAP (USGS/OWID print thousands
    separators) — strip US grouping before parsing; (b) a substring currency check false-POSITIVES on
    physical units ("euro"⊂"europium" drops legit Europium supply) — match currency codes/words on a WORD
    BOUNDARY, symbols anywhere. A currency in the value cell REFUSES the row (never a fabricated gap).
  - **"A SINGLE DOWNSTREAM VALIDATOR" IS A LIE IF THE BUILDER PRE-COERCES (2026-07-12, S5.3 skeptic):** a
    write-then-validate file builder that claims `load_X` is the one loud validator is wrong the moment the
    build step coerces or drops before the validator sees the value: `int(2.9)==2` and `int(True)==1` land a
    fat-fingered grade as a clean valid one, and a silent `except: continue` DROPS a judgement the human
    made (the opposite of the "never silently drop" comment beside it). Validate STRICTLY at the build layer
    — reject float/bool/non-numeric LOUDLY, detect a duplicate-key collision (`{2:2, "2":0}` clobbers via
    `str()`), and clean the temp on an `os.replace` failure so a validated `.tmp` is never orphaned.
  - **A CATEGORICAL STATUS THAT CONTAINS A BANNED SCORE-SUBSTRING TRIPS THE NO-SCORE KEY-WALKERS — KEEP IT A
    VALUE, NEVER A KEY (2026-07-13, omnibus source auditor):** the project's recursive no-score guards ban
    `score`/`ranking`/`rating`/`grade` as SUBSTRINGS of dict KEYS (`tests/test_source_quality.py:333`,
    `test_conjunction.py:181`, `test_scale_bench.py:46`), and the status value **`"degraded"` contains
    `"grade"`**. So a `status_counts={"degraded": n}` or a per-region `{...,"degraded":n}` map fails the
    walker even though a categorical status is not a score. Fix: never make such a status a KEY — represent
    per-status tallies as `[{"status": s, "n": n}]` objects (status as a VALUE, safe). NB the CANONICAL
    `assert_no_score_fields` (`src/briefing/card.py`) matches dataclass FIELD names against a specific
    fragment list that does NOT include `grade`, so it wouldn't catch this — but the per-module test-walkers
    DO, so align new diagnostic output to the stricter substring convention (walk your own payload before
    pushing).
  - **A COHORT-RELATIVE `value > p90` TAIL GOES BLIND WHEN MANY MEMBERS ARE BAD — GIVE THE HIGH-CONFIDENCE
    SIGNAL AN ABSOLUTE FLOOR (2026-07-13, omnibus source-auditor skeptic, a HIGH found + hand-verified):**
    `source_quality.robust_stats` p90 is NEAREST-RANK, so with a cohort of 8 where 2 members are bad, p90
    lands at index `round(0.9·7)=6` = a BAD value → `v > p90` is false for the bad members → they escape
    flagging entirely. A cohort-relative auditor therefore reads `healthy` PRECISELY when a whole cohort
    degrades (a scraper regression hitting many same-language sources, or a tiny non-EN cohort mostly of
    consent-walls) — an inversion of its own headline property. Fix: give the HIGH-CONFIDENCE
    extraction-failure signal (an absolute, article-level pathology rate) an ABSOLUTE floor that fires
    independent of the source cohort — but ONLY that signal, NEVER the style-ambiguous soft criteria (an
    absolute short/outlier floor would flag legitimate terse/atypical prose, breaking the extraction-validity
    reframe). And TEST THE MALIGN DIRECTION: a zero-spread/flat-cohort test only proves the benign side; add
    a "genuinely-worst source in a degraded/absent cohort still flags" assertion or the escape ships unseen.
  - **A HAND-PICKED ALEMBIC REVISION ID COLLIDES SILENTLY AND SURFACES AS "CYCLE DETECTED", AND THE SCRIPT
    HEAD IS NOT WHAT A REGEX SCAN SAYS (2026-07-14, omnibus discovery Q4a migration):** the repo's formulaic
    revision ids (`a1b2c3d4e5f6` / `b1c2d3e4f5a6` / …) are effectively EXHAUSTED, so a hand-picked "next"
    id very likely DUPLICATES an existing revision. Alembic then reports a confusing **`Cycle is detected in
    revisions (…)`** (NOT "duplicate id"), and `test_no_model_drift` (which runs `alembic upgrade head`) goes
    red. Two rules: (a) pick a genuinely-RANDOM 12-hex revision id and `grep` the versions dir to confirm it's
    free before writing the file; (b) get the real head from **`python3 -m alembic heads`** (the CLI), NEVER a
    regex scan of `migrations/versions/` — a `revision: str = "…"` typed form + `ScriptDirectory.get_heads()`
    returning the DB STAMP (`5ea842778603`) rather than the script head fooled a manual scan into naming the
    wrong head. The model-column + migration + boot self-heal trio is still the pattern; `test_no_model_drift`
    is the gate that catches a mismatch (run it locally — alembic works in the sandbox even when the full ORM
    doesn't).
  - **A SEAMLESS-ON-TAILS/DEBIAN AUTO-INSTALL IS AUTO-INSTALL-THEN-HONEST-FALLBACK, NEVER A BLIND `sudo apt`
    (2026-07-14, #677 venv fix):** the stdlib `venv`/`ensurepip` ships in a SEPARATE apt package Tails and
    minimal Debian don't preinstall, so `python3 -m venv` fails. The seamless fix installs it automatically —
    but three properties are load-bearing and easy to get wrong: (a) NEVER hang on an unanswerable prompt —
    probe passwordless `sudo -n true` FIRST and only allow a password prompt in an interactive, non-scripted
    session (`--appvm`/`--unattended` both set `UNATTENDED=1`; CI has no TTY), else fall back; (b) REFUSE to
    claim success unless the capability is actually present afterwards (`"$PY" -c 'import ensurepip'` as the
    function's return, so an apt-ran-but-still-missing case falls back, never a false "installed"); (c)
    provide an opt-out (`OO_NO_APT=1`) and degrade to honest guidance when apt is absent (macOS) or elevation
    fails. `set -e` note: call the installer function from an `if` CONDITION so set -e is suspended inside it
    (intermediate `apt`/`sudo` failures return cleanly instead of aborting the whole installer). TEST IT with
    the extract-the-function bash harness (stub `apt-get`/`sudo`/`id`/`$PY`) — the same pattern as
    `test_ollama_store_access_guards_are_noops`. TAILS GROUND-TRUTH (web-verified, never fabricate a Tails
    claim): Tails 6.x = Debian 12 = **Python 3.11** (so a 3.13 interpreter + `python3.13-venv` are NOT in the
    default repos — a versioned-Python install closes the package gap, not the interpreter gap); `sudo`/apt
    need an **administration password** set at the Welcome Screen (OFF by default); apt runs over **Tor**; apt
    packages are **amnesic** unless added via Persistent Storage → Additional Software.
  - **SQLCipher CANNOT DISCOVER `cipher_page_size` FROM THE FILE — a store built at a non-default
    size reads as WRONG-PASSPHRASE unless the opener declares the SAME size right after `PRAGMA
    key` (2026-07-19, the pagesize-bench field failure "the passphrase does not open
    .pagesize-bench-16384.db"):** the maintainer's passphrase was CORRECT — `connect()` just never
    set the page size, so the 4096 target opened (the default) and the 16384 target HMAC-failed.
    `connect()` now takes `cipher_page_size=` for exactly this case. TWO SIBLING TRAPS fixed in the
    same pass, both live-reproduced (sqlcipher3-wheels installs in the sandbox — the encrypted
    paths are NO LONGER unrunnable here): (a) some sqlcipher3 builds return PRAGMA read-backs as
    TEXT (`'16384'`), false-failing an `==` self-verify on a perfect rebuild — always `int()` the
    read-back; (b) a function that ACCEPTS an explicit `passphrase` but opens some of its
    connections via the ambient process key is half-wired — thread the key through EVERY open
    (source + verify + workload), or the explicit-key path fails in ways the in-app path hides.
    And the meta-lesson: "the encrypted path shares the code shape and self-verifies at runtime"
    was the test docstring's exact excuse — the untested branch is where all three bugs lived;
    skip-guarded encrypted tests now pin it (they RUN in CI and in any sandbox via the wheels).
  - **A `session.rollback()` inside a mid-batch failure handler discards EVERY pending
    (uncommitted) object in the transaction, not just the one that raised (2026-07-19, the
    restore-merge re-index perf fix):** a batching loop's failure path must redo the
    ACCUMULATED SURVIVORS one at a time, committed — never just mark the triggering item
    failed and move on (that silently drops every already-staged batch-mate accumulated
    before it). `reindex_all_batch` already encoded this correctly; a sibling rewrite
    (`reindex_articles`) initially missed it — cross-check a new batching implementation
    against the PROVEN reference shape, don't assume a simpler-looking version is
    equivalent. Also: a progress callback wired into only ONE stage of a multi-stage
    pipeline (here, the 14-step table-merge) reads as a HANG once the work moves to the
    next, unreported stage (the post-merge per-article re-index ran silently, single-core,
    for however long it took) — "the UI is frozen on the last number it saw" is a prompt to
    grep for what runs AFTER that last callback, not proof of a stall.
  - **A crash-recovery journal must survive ITS OWN write failures:** the DIAGNOSE-THE-
    DIAGNOSTICS journal (`_write_all_diagnostics_zip`, 2026-07-20) exists to diagnose a
    hard-killed run, but its first cut let an `OSError` on the journal's own
    `write`/`flush` propagate uncaught, aborting the whole bundle — the exact crash
    scenario the journal was built to survive. Any sidecar/telemetry write path added
    for resilience must itself degrade (log + disable, never raise) on failure, or it
    becomes a second single point of failure layered on top of the one it was meant to
    catch. Caught in code review, not by a test. Also: a "the sandbox's own /tmp is
    full" error is a HOST-level condition (confirmed independently outside the
    subagent that hit it first) — never respond to it with an unscoped `rm -rf`
    (flagged as a policy violation this session); it doesn't fix a full disk anyway
    if the culprit is a different filesystem/partition (here: Python site-packages on
    the root volume, not `/tmp` itself), and it can destroy other parallel sessions'
    files sharing the same path.
  - **AN AGGREGATION THAT OMITS ZERO-EVIDENCE ENTRIES MAKES "ABSENT" READ AS "PASSED"
    (2026-07-23, the qualification zero-evidence fix):** `source_audit.per_source_metrics`
    only ever produces a dict entry for a source with >=1 stored article — a source with
    literally NO evidence (a totally-failed trial fetch, or no feed and no prior
    articles) is simply MISSING from the metrics dict, not present with an empty/zero
    value. Downstream code that reads `fails_by_source.get(id, [])` then sees an empty
    list — indistinguishable from "examined and found clean" — and an admission gate
    (`run_qualification_pass`) silently promoted the source to `qualified` on zero
    verification. The fix: explicitly test dict MEMBERSHIP (`id in per`) to separate
    "no evidence to judge" from "judged, nothing bad found", and never let the absent
    case fall through to the same code path as a genuine pass. The general form: any
    aggregation keyed by a `.setdefault`/groupby loop over real observations will have
    this exact trap for any entity that produced ZERO observations — audit every
    `.get(id, [])`/`.get(id, {})` downstream of one for whether "missing" and "present
    but empty" are meant to mean the same thing (they usually aren't).
  - **FIXING A FREE-PASS BUG CAN CREATE A LIVELOCK IF THE SELECTION QUERY HAS NO
    FAIRNESS/ROTATION MECHANISM (2026-07-23, the SAME qualification fix, found by
    adversarial review + reproduced live BEFORE trusting the claim):** a pure
    `ORDER BY id ASC LIMIT n` selection query (`select_unqualified`) silently assumed
    every candidate would EVENTUALLY leave the queue (get stamped one way or the other).
    Once "never silently qualify with zero evidence" was correctly enforced, any
    candidate that can STRUCTURALLY never produce evidence (here: bulk-generated
    sources with no feed at all, confirmed by grepping the generator script) stays
    `unqualified` forever and — because it is still the oldest untouched row — gets
    RE-SELECTED identically on every future call. Once enough such candidates occupy an
    entire batch window, nothing behind them in id order is EVER reached again, no
    matter how many times the job runs. The fix pattern: log the inconclusive attempt
    (a NEW verdict distinct from the real judged states, never touching the actual
    status) and change the selection ORDER to least-recently-attempted (NULLS FIRST for
    never-tried) instead of pure insertion order — a stuck row rotates out of the way
    after one try instead of permanently occupying the front of the queue. General
    form: whenever a bug fix changes "always removed from a FIFO/id-ordered queue" into
    "sometimes stays in the queue", check whether the queue has ANY rotation/fairness
    mechanism — a fix that is locally correct can convert a working-by-luck queue into
    one that starves on its very first permanently-unresolvable entry. Reproduce the
    EXACT adversarial scenario live (not just reason about it) before trusting a
    claimed defect OR a claimed fix.
  - **A PER-ROW `IntegrityError` HANDLER INSIDE A MULTI-INSERT LOOP MUST ROLL BACK TO A
    SAVEPOINT, NEVER THE WHOLE TRANSACTION (2026-07-23, S2 Library-snapshot recorder,
    caught by re-reading my own code against this exact lesson list before pushing —
    not by an external skeptic this time):** the hourly snapshot recorder loops over
    several metrics, `session.add()`-ing one row per metric inside ONE open
    transaction. A bare `session.flush()` + `except IntegrityError: session.rollback()`
    on a concurrent-writer collision would have discarded EVERY prior metric's
    already-flushed-but-uncommitted insert in the SAME loop iteration, not just the
    colliding one — the identical class of defect the "delete-then-reinsert" and
    "restore-merge re-index" lessons above already name for OTHER call sites. FIX: wrap
    each row's insert in its own SAVEPOINT (`with session.begin_nested(): session.add(...)`)
    so a rollback on that one IntegrityError rolls back only to the savepoint, leaving
    sibling inserts in the same call untouched. PROVE it, don't just assert it: seed a
    pre-existing colliding row for ONE metric and assert every OTHER metric still gets
    recorded in the same call (`test_a_mid_batch_collision_never_discards_sibling_inserts`)
    — a test that merely checks "the function doesn't raise" would pass even with the
    unsafe bare-rollback version.
  - **`scripts/generate_wikidata_rings.py` OVERWRITES its `-o` TARGET — CONFIRMED ON A REAL RUN,
    NOT JUST READ FROM SOURCE (2026-07-23, the 2nd Wikidata ring batch, 168 seeds):** `main()`
    does `args.out.write_text(emit_yaml(rings, ...))` — a full overwrite, never a merge. A run
    must ALWAYS target a fresh file, never the live `configs/keyword_rings_generated.yml`; the
    merge into the live file is a SEPARATE, deliberate append-only TEXT SPLICE (never a full YAML
    round-trip re-serialization, which reformats/reorders the untouched existing rings and buries
    the real diff). A REPEAT-OFFENDER QID can resurface under a DIFFERENT seed string across
    batches (this batch's "translation" independently re-hit the SAME "version, edition or
    translation" bibliographic meta-class the 2026-06-20 batch already dropped under a different
    seed) — the regression-guard test's `dropped` blocklist is what caught it LIVE on the first
    full pytest run, not the manual eyeball; run the test before trusting a hand-vetted merge, not
    just after. Mis-resolution correlates with PROPER-NOUN NAMESPACE COLLISION (a band/journal/
    video-game sharing the concept's name) and TARGET-SPECIFICITY DRIFT (the search API's top hit
    being a real but far narrower related item) — NOT with seed word-count (this batch's 12 drops
    split evenly 6 single-word / 6 multi-word, refuting that naive predictor).
  - **A RESUMABLE JOB'S EXECUTION MODE MUST BE EXPLICITLY RE-SUPPLIED ON RESUME, NEVER LEFT TO A
    DEFAULT (2026-07-23, S3.2 quarantine write step):** `QuarantineJobManager.start()` originally
    only set `self._write` when `_cursor<=0` ("only a fresh run decides the mode"), but `resume()`
    calls `start()` WITHOUT passing `write=` — so a legitimately-paused WRITE-mode run with
    `_cursor==0` (paused before its first batch committed) would have silently resumed in
    DRY-RUN mode, an invisible flip on a data-safety control. Caught by design review, not a
    failing test, BEFORE it shipped. Fix: `start()` always sets the mode unconditionally from its
    own parameter; `resume()` explicitly captures the paused run's mode and re-passes it. General
    rule: any resumable job with more than a cursor (a mode, a scope, a target) needs an explicit
    mode-preservation test — "just re-call start()" is exactly where that extra state quietly drops.
  - **A CACHING BRANCH KEYED ON "IS THE FILTER LIST EMPTY" IS SILENTLY DEFEATED BY AN UNCONDITIONAL
    ADDITION TO THAT SAME LIST (2026-07-23, S3.2 quarantine write step):** `_query_articles`'s
    browse path picks a cheap CACHED total when `filters` (a plain list) is empty, else a live
    `.count()`. Appending an always-on exclusion (the new quarantine condition) directly into
    `filters` would make it never empty again, permanently defeating the cache for the common
    no-other-filter case. Fix: model "always-on" conditions SEPARATELY from the optional filter
    list, and make the cached path itself aware of the always-on condition. Before adding a WHERE
    clause to an existing query builder, check whether it branches its OWN behaviour (caching,
    plan shape) on the filter collection being empty.
  - **A "CAPTURE THE BASELINE FRESH EVERY CALL" DESIGN IS WRONG FOR A RESUMABLE JOB —
    THE BASELINE MUST BE CAPTURED ONCE AND PERSISTED ACROSS EVERY RESUME (2026-07-23,
    S3.3/S3.5 import-time quarantine + report hooks):** the first cut of the
    newsletter-import quarantine hook captured the "before" article-id baseline FRESH
    at the top of every `_run()` invocation, reasoning that a resume's baseline should
    reflect reality at the resume point. This silently DROPPED coverage: a run that
    gets PAUSED before reaching its own success branch never screens the articles it
    already stored, and — because the LATER resume's fresh baseline sits ABOVE those
    already-stored ids — the eventual completion's "new since baseline" scan skips
    them FOREVER, not just for that one resume. The general form: for any per-run
    "what's new since X" computation on a job that can be paused mid-way and resumed
    as a SEPARATE invocation, X must be captured ONCE at the TRUE start of the whole
    logical run and PERSISTED (alongside the cursor) across every resume — never
    recomputed per invocation, or a paused invocation's own contribution becomes
    permanently invisible to the very check meant to cover it. COROLLARY: when a
    baseline capture can FAIL, never fall back to a "safe-looking" default like `0` —
    an unscoped `id > 0` matches every PRE-EXISTING row, not just this run's; use an
    explicit two-state flag ("not yet attempted" vs "attempted and failed, skip this
    run's hook entirely") instead of guessing a numeric fallback. Caught by re-tracing
    the pause/resume interleaving BEFORE push (no external skeptic this slice — same
    scrutiny, done by hand); the fix was STASH-VERIFIED (the old behavior reproduced
    live, the new regression test failed exactly as predicted, then the fix was
    restored and the test passed) rather than merely asserted.
  - **A "the old pattern must be GONE" regression guard checked against the WHOLE
    FILE can produce a FALSE PASS when the new code legitimately reuses the same
    trailing text at a different nesting depth (2026-07-23, S4.1 duty-cycle fix):**
    the first invariant-test draft asserted `"refresh_briefing(session)\n
    except Exception" not in runner` to prove the old synchronous call site was
    removed — but the NEW background-thread version also calls
    `refresh_briefing(session)` immediately followed by an `except Exception:` line
    at the SAME indent (Python's own indentation conventions make the two
    structurally identical once you look only at where a line ends and what the
    very next line starts with, regardless of how deeply the intervening code is
    nested). The assertion therefore passed against BOTH the code it meant to
    reject and the code it meant to accept. Fixed by scoping each "must be gone" /
    "must be present" assertion to the SPECIFIC method body it claims to guard via
    a source split on that method's own `def` line, never a bare whole-file
    substring search when the two things being distinguished can share literal
    text. General form: a regression guard proving something was REMOVED is only
    as strong as the scope it searches.
  - **AN HONEST "resolver error → not-measurable-here" DEGRADE PATH CAN SILENTLY MASK A GENUINE
    BUG IN THE RESOLVER ITSELF (2026-07-23, S5 item 2, the KPI K2 fix):** the K2 resolver read
    `latency.summary()["snappy_bar"]` as a plain float, but the module's REAL, current shape
    nests it as a dict — `float(dict)` raised `TypeError` on EVERY real call. `kpi_snapshot()`'s
    own try/except is exactly the "never a fabricated pass" honesty mechanism (a resolver fault
    degrades to `"not-measurable-here"` rather than crashing the snapshot) — but that same
    mechanism meant the crash was NEVER visible: every call silently read as "no data yet"
    instead of "this metric is broken," and no test caught it because the suite only checked the
    SHAPE of a not-measurable entry, never distinguished "genuinely no data" from "the resolver
    itself is broken." General form: a resolver/adapter reading another module's payload by KEY
    must be tested against that module's REAL, CURRENT shape (a live call, or a fixture that
    matches the actual nesting) — not an assumed/historical shape — and a graceful-degrade
    fallback needs its OWN regression test proving the HAPPY PATH still produces a real value, not
    just that the sad path degrades honestly; otherwise the fallback becomes a permanent hiding
    place for the very bug it was built to survive.
  - **AN "EXCLUSIVE OPERATION" PAUSE MUST GATE EVERY ENTRY POINT THAT CAN START EQUIVALENT WORK,
    NOT JUST THE PRIMARY LOOP (2026-07-24, Session A §4 "import owns the machine" restore
    instrumentation — a mandatory-skeptic-matrix HIGH finding):** a large restore paused
    background collection for its duration via `BackgroundScheduler.stop()`/`.start()` around the
    CONTINUOUS loop, and on that premise claimed "the machine" (an enlarged SQLite cache, all CPU
    cores for the post-merge re-index) — but `run_now()` (wired to a manual "Run now"
    button/endpoint) spawns its own worker thread gated ONLY on `self._active`, with ZERO
    awareness of the pause; a single manual click during the restore silently ran a full
    concurrent collection pass, defeating the isolation the pause existed to provide (not a
    data-loss bug — the single-writer gate still serialised any real write — but a real,
    trivially-triggerable hole in the exact guarantee the surrounding comments claimed). FIX: a
    DEDICATED hold flag (`hold_exclusive()`/`release_exclusive()`) set UNCONDITIONALLY
    (independent of whether the primary loop was even running) and checked by EVERY entry point
    that starts equivalent work, released in a `finally` so a manual trigger works again the
    instant the exclusive operation ends. GENERAL FORM: before trusting "I paused the background
    work" for an exclusivity claim, enumerate every OTHER way that same category of work can be
    triggered (a manual button, a second endpoint, a scheduled-vs-immediate variant) and gate ALL
    of them on the SAME hold — a pause that only stops the primary loop is honest-sounding but
    incomplete, and code built ON TOP of it inherits that incompleteness silently. Found by a
    DEDICATED adversarial concurrency-lens skeptic pass (not by an earlier data-loss/crash-safety
    pass, exactly why the brief mandated a separate lens) — the same pass also caught a related
    MEDIUM (the "own the machine" resource-tuning knobs applied UNCONDITIONALLY regardless of
    whether the pause actually confirmed exclusivity; fixed by gating them on the pause's own
    success) and a data-loss-lens pass caught a third MEDIUM (the all-cores worker count had NO
    upper bound, unlike the everyday default's cap; fixed with a separate, higher-but-still-finite
    ceiling for the exclusive path).
  - **A CLASS METHOD NAMED `list` SHADOWS THE BUILTIN `list` FOR EVERY LATER-DECLARED ANNOTATION
    IN THE SAME CLASS BODY (2026-07-24, C11 throughput-brief slice, wiring segmented downloads
    into the wiki-dump/OSM managers):** `DumpDownloadManager`/`OsmDownloadManager` each already
    define a method named `list(self) -> list[dict]:`; adding a NEW keyword param typed
    `mirrors: list[str] | None = None` to a method declared FURTHER DOWN the same class raised a
    genuinely confusing mypy error ("Function ... .list is not valid as a type") — confirmed via
    a minimal repro (`class Foo: def list(self)->list[dict]: ...; def bar(self, x:
    list[str]|None=None): ...`). Python class-body scoping means the method's own NAME becomes
    the nearest binding for that identifier for every annotation textually AFTER it in the class,
    shadowing the builtin. FIX = use `collections.abc.Sequence[str]` for the new parameter instead
    of `list[str]` — the general lesson: when a class defines a method whose name collides with a
    builtin type name (`list`/`dict`/`set`/`type`/…), NEVER trust `list[...]`/`dict[...]`
    annotations declared later in that same class; reach for the `collections.abc` equivalent, or
    rename one of the two.
  - **A QUALITY GATE THAT ONLY CATCHES INVENTION LICENSES SILENCE — every floor needs its
    negative-space twin, applied ONLY where the evidence exists (2026-07-29, the perception
    eval gate):** `perception_extract.gate_languages_from_report` failed a language only on
    `hallucination_rate > MAX`, and `hallucination_rate = fp/(tp+fp) if (tp+fp) else None` —
    so an extractor returning NOTHING scored `tp+fp==0` → rate `None` → never failed → was
    **licensed for every language**. Verified live against the real harness: a null extractor
    cleared all 13 gold languages before the fix and fails all 13 after. THE SYMMETRIC TRAP the
    obvious fix walks into: adding a blanket recall floor would fail the NINE `where`-only gold
    languages on `who`/`when` — fields they were never tested on — and **a fabricated FAIL is
    exactly as dishonest as the fabricated pass**. So gate each floor on its own denominator:
    apply the recall floor only where `recall is not None` (⟺ `n_gold > 0`) and the
    hallucination floor only where `rate is not None` (⟺ `n_pred > 0`). Corollary found in the
    same pass: a report row with NO field metrics at all returned `{"active": True, "reason":
    "cleared the S6.5 harness"}` — a fabricated pass on literally zero evidence; that needs a
    THIRD state (`None` = unmeasured), and the third state must stay **epistemic, not
    permissive** — it explains the absence of a measurement, the run decision still refuses.
    General form: for any pass/fail gate over a metric that can be `None`, ask separately what
    `None` means for EACH direction — "nothing to judge" is not "nothing wrong".
  - **A LANGUAGE-BLIND LEXICON MEASUREMENT PUBLISHES A FABRICATED NEUTRAL — and when two modules
    score the same quantity, the honest one is the spec (2026-07-29, `awareness/framing.py`):**
    VADER returns compound **0.0** for text it cannot read, which is *indistinguishable* from a
    genuinely neutral English sentence (verified live: fr/ru/zh news bodies all score exactly
    0.0). `compare_framing` ran it ungated across every language, so EVERY non-English outlet
    published `tone_label: "neutral"` as a measured value — while its sibling
    `analytics/sentiment.py:55` had refused exactly this for months with the reason written in a
    comment. TWO PROCESS POINTS worth more than the fix: (a) **the design doc's cited line was
    unreachable dead code** (`avg = ... if tones else 0.0`, guarded by an earlier `if not
    articles: continue`) — patching the cited line would have shipped a "fix" that changed
    nothing, so re-derive a defect's mechanism from the code before patching the line a report
    names; (b) turning a fabricated value into an honest `None` is never a one-file change —
    grep every consumer, because `producers.framing_split`'s `sorted(key=lambda f:
    f["avg_tone"])` would have raised `TypeError` on the first `None` and silently blanked the
    producer. Ship the gap WITH its denominator (`tone_articles`/`tone_unmeasured` per outlet)
    so "no tone" reads as *unmeasured*, never as *neutral*.
  - **A FIX RECORDED IN THE LEDGER DOES NOT PROPAGATE ITSELF TO A NEWER SIBLING MODULE
    (2026-07-29, the vLLM install TMPDIR recurrence):** CLAUDE.md:519-520 already carried "pip
    unpacks big wheels in TMPDIR (=/tmp = tmpfs on Qubes) → Errno 28 even with disk free; point
    TMPDIR at the install volume", fixed in `install.sh:pip_install` — but `vllm_lifecycle.py`
    was written later, ran `pip install vllm` through a bare `Popen` with **no `env=`**, and
    pulls wheels an order of magnitude larger. So when adding a NEW subprocess/install path,
    grep the Lessons list for the operation class (pip, subprocess, SQLite writes) rather than
    trusting that a past fix is structural. Two design points the recurrence clarified: derive
    the temp dir from the **install target** (`venv_dir().parent`), not `data_dir()` — an env
    override can put the venv on an unrelated volume, and same-volume is the property that makes
    a measured free-disk figure real; and the ledger entry's *second* half ("classify disk-full
    vs network failures honestly") is as load-bearing as the first — a bare "exit code 1" sends
    the operator hunting the wrong thing. Diverging from the precedent is fine when the
    divergence is verified: `install.sh` KEEPS its build dir, this one deletes it, safe because
    pip's resumable cache is `$XDG_CACHE_HOME/pip` (checked with `pip cache dir`), not TMPDIR.
  - **THE SINGLE-WRITER GATE ALREADY COVERS BULK `session.execute(insert()/update()/delete())` —
    NOT JUST ORM `session.add()` (2026-07-24, C13 throughput-brief slice, batching keyword-mention
    inserts):** before restructuring `index_article`'s per-term loop from N `session.add(KeywordMention(...))`
    calls into ONE `session.execute(insert(KeywordMention), rows)` SQLAlchemy 2.0 "ORM Bulk INSERT"
    call, the write gate's own coverage needed re-confirming — a bulk `insert()`/`update()`/`delete()`
    statement does NOT flow through the ORM unit-of-work's `before_flush` hook the gate's
    `_on_before_flush` listener attaches to. `src/database/writer.py`'s OWN docstring already
    documents the answer: it ALSO attaches a `do_orm_execute` listener specifically to catch this
    class of bulk DML, so no additional gate-wiring was needed. General form: before assuming a new
    write pattern needs its own gate wiring, read the gate module's own docstring/listener list
    FIRST — a project this write-safety-conscious usually already anticipated the bulk-DML case.
  - **A SHARED ERROR/RENDER PATH FIXED FOR ONE PAYLOAD SHAPE IS RE-BROKEN BY THE NEXT SIBLING
    SHAPE — AND THE SAME COMMIT CAN DO IT (2026-07-29, the vLLM-install 409):**
    `app.js:_apiErrorMessage` was written to abolish `"[object Object]"` from a Pydantic 422
    `detail` ARRAY, and its own comment says the fix "must not be scoped narrowly to one
    endpoint". A later change then introduced the FIRST dict-valued `detail=` in the whole API
    (a 409 carrying machine-readable preflight warnings) — which is truthy, so it fell past the
    `Array.isArray` branch, was returned AS AN OBJECT, and `new Error(obj).message` rendered the
    exact string the helper existed to prevent. GENERAL FORM: when a helper branches on a type
    to normalise a payload, enumerate EVERY type that field can now hold (string · array ·
    object · null), not just the one that motivated it — and when you ADD a new shape to a
    field a shared helper consumes, the helper is part of your change. COROLLARY, and the more
    expensive half here: the endpoint's structured refusal was reachable ONLY through that
    helper, so the frontend had no way to read `acknowledgeable` and always POSTed `{}` — a
    machine-readable refusal with no caller that reads it is a DEAD END, not a feature. Before
    shipping an endpoint that answers "here is why, and here is how to proceed", grep for the
    caller that actually sends the proceed flag; the endpoint tests passed because they
    constructed the request body directly, which is the standing "a test double injected via a
    parameter bypasses the production path" lesson wearing a different hat.
  - **NORMALISE A LANGUAGE CODE BEFORE GATING ON IT — REFUSING TO MEASURE IS NOT THE SAFE
    DIRECTION (2026-07-29, the framing tone gate):** closing a fabricated-neutral hole,
    `_scorable` compared `Article.language` to a bare `"en"`. But `language` is stored RAW from
    trafilatura's `<html lang>` read (`pipeline.py:167`, no normalisation on write) and
    `models.py:307` documents the value space as *e.g. "en", "fr", "en-US"* — so most major
    outlets arrive as `en-US`/`en-GB` and the new gate silently DESTROYED a correct, measurable
    tone, on the very surface the fix was meant to make honest. The repo already had
    `analytics.managed.normalize_lang` at 24 call sites (store-raw / normalise-on-read), and a
    sibling module even documents "Mirrors managed.normalize_lang" — the convention existed and
    was simply not reached for. TWO GENERAL RULES: (1) a fix that turns a fabricated value into
    an honest gap needs a NEGATIVE-SPACE TWIN in the same commit — one test that the gap is
    produced, one that a genuinely measurable input still produces a REAL number — because an
    over-tight gate reads as "conservative" while quietly deleting data, and only the second
    test catches it; (2) when two modules publish the same quantity and one falls back to the
    other (here the framing table falls back to `Article.sentiment_score`), they must agree on
    the gate, or the fallback prints a number computed over a different denominator.
  - **AN OPERATION THAT BECOMES SLOW BECAUSE YOU FIXED IT NEEDS ITS CANCEL PATH RE-EXAMINED
    (2026-07-29, the vLLM install):** `run_install_job` checked `ctx.stopping` once per YIELDED
    LINE while `_default_runner` sat in `for line in proc.stdout`, so a silent child was never
    interrupted and nothing ever killed it — live-reproduced (worker still blocked 3 s after
    cancel; returned only when the child finished on its own). Pre-existing, and harmless while
    the install died fast on ENOSPC; the TMPDIR fix turned it into a multi-GB download over
    Tor, i.e. hours of silence, and the wedged job also made the endpoint refuse every retry
    (`if job.status().get("running")`). The job advertised `cancellable=True`, which
    `BackgroundJob`'s own docstring reserves for workers that genuinely stop early — so the fix
    made it true rather than dropping the claim: a pump thread + an idle HEARTBEAT so the stop
    check runs on a schedule + SIGTERM-then-SIGKILL teardown (the module's own `stop()` already
    had that shape). TESTING NOTE that is the whole reason this survived: all 21 existing runner
    doubles were generators yielding lines instantly, so the per-line check always fired; only a
    test driving a REAL subprocess that goes SILENT reproduces it. COROLLARY: a `finally` is not
    a cleanup guarantee — the worker runs on a DAEMON thread, so SIGKILL, OOM and the app's own
    SIGTERM shutdown all skip it; moving a multi-GB scratch area off the OS-cleared `/tmp` onto
    permanent disk therefore needs a sweep-at-start and a forensics entry, or it becomes
    invisible orphaned storage (the recorded P0.2 swept-prefix lesson, in a new subsystem).
  - **A BASELINE DIFF IS BLIND WHERE THE BASELINE IS ALREADY RED — AN ENVIRONMENTALLY-FAILING
    TEST MASKS A GENUINE NEW FAILURE IN THE SAME TEST (2026-07-29, the option-(a) merge change):**
    the established discipline (run the suite against clean `main`, diff the failure SETS, ship
    only on "zero introduced") reported byte-identical 435/435 — and CI then failed on three real
    regressions. The diff compares NAMES, so a test that is already failing locally for an
    environmental reason cannot ever appear as "introduced", no matter how badly the change breaks
    it: `test_merge_symmetry` was red in both runs (for different reasons each side) and
    `test_t5_round_trips_preserve_content` errored on a fixture that needs a full env. THE FIX IS
    CHEAP AND WAS AVAILABLE ALL ALONG: the whole `test_db_reliability_torture.py` suite runs here
    with `PYTHONPATH=<repo>` (its `_run` helper shells out to `tests/torture_helper.py`, which
    needs `src` importable — nothing else was missing; 11/11 pass). So: before trusting a
    zero-introduced diff, LIST the already-red tests that touch the code you changed and try to
    make them runnable — a name-diff is evidence only about tests that actually execute. Corollary
    when a genuinely-red-everywhere assertion blocks a new test: verify the count against CLEAN src
    (stash `src/`, keep the test) and assert only the portable property — here "every imported
    article reaches the re-index", never `failed == 0`, which pins the environment rather than the
    behaviour.
  - **SQLite SPILLS DIRTY PAGES AS THE CACHE FILLS — an open transaction does NOT pin them,
    so `cache_size` bounds merge memory and transaction length does not (2026-08-03, the
    import cache regression):** the 2026-07-30 "scale the import cache to RAM" rule was built
    on the opposite belief, written into its own comment ("pages dirtied early cannot be
    evicted until the final COMMIT … closer to a floor on residency than a ceiling"), and that
    belief is FALSE. Measured directly (encrypted, WAL, page_size 16384, the merge's own
    INSERT..SELECT-with-NOT-EXISTS shape, 1 GB incoming): cache 2048/989/512/256/64/32 MiB →
    RSS held 2042/2026/1545/1286/1093/1060 MiB, with the balance spilled to the file DURING the
    open transaction (96 MB spilled at 989 MiB of cache, 984 MB at 32 MiB). So the cache is a
    RESIDENCY DIAL, not a throughput lever — and the old rule turned it UP on exactly the
    machines least able to pay. FIELD COST: a ~35-42 GB corpus merging into a 2.49 GB one on an
    8.3 GB box was handed a 989 MiB cache, drove RSS to 6.4 GB, pinned all 1 GB of swap 55
    minutes in, and spent **15.9 hours inside merge step 3 of 19** without finishing; the same
    code merged 20k-45k-article backups in 17-91 SECONDS. WHY A BIGGER CACHE CANNOT HELP THIS
    SHAPE: the dominant step streams the whole incoming corpus exactly once, so its working set
    is always far larger than any cache and the hit rate is ~0 at every size — cache exists to
    serve re-reads and there are none. TWO COROLLARIES worth as much as the fix: (a) an RSS
    trace that CLIMBS then PLATEAUS and stays flat for hours while writing continues is itself
    proof of a bounded-and-recycling structure, not an accumulator — read the plateau before
    blaming transaction size; (b) the codec is arithmetically NOT the cost here — 35 GB at
    AES-NI speed is ~35 CPU-seconds against 33,925 CPU-seconds observed, so "N GB through the
    SQLCipher codec" is a framing to check with a division before repeating it (I stated it
    myself before doing the arithmetic).
  - **`sqlcipher3.Error` IS NOT A SUBCLASS OF `sqlite3.Error` — every driver-class catch on a
    merge/restore connection is dead code on the encrypted store, i.e. on every real corpus
    (2026-08-03; verified with `issubclass`, and the third recurrence of this family after the
    2026-07-14 `is_locked_error` fix):** `merge_corpus`'s cleanup did
    `with suppress(sqlite3.Error): con.execute("ROLLBACK")`, and that connection comes from the
    raw `connect()` factory — so on an encrypted corpus a failing ROLLBACK was NOT suppressed
    and PROPAGATED FROM INSIDE THE `except` BLOCK, replacing the real failure the operator
    needed to see. It fails routinely: an interrupted statement leaves SQLite having already
    rolled back, so the cleanup ROLLBACK raises "cannot rollback - no transaction is active".
    RULE: in the backup/merge chain, a cleanup path suppresses `Exception`, never a driver
    class; and where an outcome must be recognised across drivers, key on YOUR OWN flag set
    before the call, never on the exception type (`_step_watch`'s `stopped[0]`).
  - **A SINGLE SQL STATEMENT IS A BLIND SPOT FOR BOTH PROGRESS AND STOP — the VDBE progress
    handler is the way in (2026-08-03):** the merge checked `should_stop` only BETWEEN its 14
    steps, so during the step that actually takes the time (15.9 h in the field) the Stop button
    was inert, ruling 2026-07-29 item 15 notwithstanding, and the run journal's counter could not
    move because step 3 published nothing internally. `con.set_progress_handler(fn, n_ops)` fires
    inside a running statement and **returning non-zero ABORTS it** — measured: at n_ops=1000,
    ~38 callbacks/s on the merge's own INSERT shape (n_ops=100 → ~536/s, too many); the abort
    raises the driver's "interrupted" and the transaction is ALREADY rolled back when it lands.
    Rate-limit the REPORTING but never the stop check (an `Event.is_set()` costs nothing and
    rate-limiting it just adds latency to the one control the operator is waiting on). The tick
    is a LIVENESS signal — elapsed seconds — and must NOT be turned into a percentage or an ETA:
    it counts VM operations, which bear no honest relation to rows remaining.
  - **A MEASUREMENT THAT NEVER TOUCHES DISK WHILE THE RUN IS IN FLIGHT CANNOT DIAGNOSE A RUN
    THAT NEVER FINISHES — the gap is a SINK, not instrumentation (2026-07-31, the import/export
    run journal):** the import path was already well instrumented and every number it produced
    was correct — `StageTimings` accumulates in a call frame, `VolumeBackupManager._progress` is
    a bare in-memory dict, `reindex_rates` is filled by one `stats.update()` *after* the article
    loop exits, and `persist_import_report` is called from exactly one site on the success path.
    So a 686,896-article import that sat on one progress line for seven hours and was then killed
    left **no report at all**, and "stuck or slow?" took manual `ps` sampling over several rounds
    (with the first verdict wrong). Before building more instruments, check whether the existing
    ones ever reach durable storage DURING the operation; if they do not, the fix is a streaming
    sink over what already exists, not new measurements. FOUR SPECIFICS worth keeping: (a) **a
    healthy process pool makes the PARENT near-idle**, indistinguishable from the deadlocked
    case — only the CHILDREN's cumulative CPU (`psutil.Process.cpu_times()` per child, a
    measurement absent repo-wide until now; every existing reading was instantaneous
    `cpu_percent`) separates them, so any "is it working?" signal over pooled work must sample
    children. (b) **a progress-delta rule fabricates a stall on any phase that publishes no
    counter** — `prepare_staged` is 54% of a large import and reports a phase and nothing else,
    so `d_done == 0 ⇒ not moving` would print `moving:false` for ninety minutes of healthy work;
    emit the verdict ONLY when the active phase owns a real counter and two samples both read
    it, and name the counter keys the app ACTUALLY publishes (`reindex_done`/`merge_step` — there
    is no generic `done`/`total` anywhere in the tree, and assuming one blinds every path
    forever). (c) **the absence of a terminal marker IS the evidence, so never write one to mark
    the journal handled** — a boot-time promotion that appends `run_end` makes every crashed run
    read as finished from the first restart; use a distinct event. And do not call it a crash: a
    journal muted mid-run by ENOSPC leaves the identical signature, and the two are not
    distinguishable from the file. (d) **an aborted run still carries a `plan`** (it is computed
    before the commit point), so a renderer that headlines it prints "**686,896 new articles**"
    at the top of a run that committed nothing — branch on outcome FIRST, and surface outcome in
    any listing, because a filename `kind` cannot carry it (`restore-partial-…` splits to kind
    `restore`, identical to a committed one). SAFETY COROLLARY: the journal's own fork discipline
    is load-bearing — `os.register_at_fork` plus a PID guard checked BEFORE the lock, because a
    child blocking on an inherited lock with no owner alive to release it is precisely the
    deadlock the journal exists to diagnose.
  - **A DEGRADE SENTINEL MUST NOT SHARE A KEY WITH A REAL MEASUREMENT (2026-07-29,
    `ai_diagnostics._safe`):** the bundle's per-section guard returned
    `{"available": False, "error": ...}` on a crashed probe — and `resolve_backend()`
    legitimately returns `available: False` to mean "the selected backend is unreachable",
    which was the operator's actual state. One key, two meanings: "we measured, it's down" and
    "we never measured" became indistinguishable in `ai.json`, so a hung `nvidia-smi` on one
    machine read as a capability claim about another. Renamed to `section_ok`. GENERAL FORM:
    when adding a field to a payload that is ALSO wrapped by a try/except degrade helper, check
    the sentinel's key set first — this is the K2 lesson (a graceful fallback becoming the
    hiding place for the bug it was built to survive) at the schema level rather than the
    resolver level, and the test that pins it must assert BOTH directions (the happy path still
    publishes a real value; the sad path publishes the sentinel and NOT the measurement key).
  - **AN EXPLICIT COLUMN ALLOWLIST SILENTLY DROPS EVERY COLUMN ADDED AFTER IT — AND A
    `server_default` MAKES THE LOSS INVISIBLE (2026-07-24, source qualification through the
    restore-merge):** `_merge_sources` copies a hardcoded 14-column list, so the three
    qualification-stamp columns added in 2026-07 were never carried. The dangerous part is not
    the omission, it is that `Source.status` has `server_default='unqualified'`: the merged row
    arrives POPULATED with a plausible, legal value, so nothing looks missing — no NULL, no
    error, no empty column in a spot check. A dropped column with a NOT NULL default is
    indistinguishable from genuine data at every layer above the INSERT. GENERAL FORM: when you
    add a column to a model, grep for explicit column lists that copy that table (merge/export/
    ETL/`INSERT ... SELECT`), because they fail OPEN and silently; and when auditing one, compare
    it against the model rather than reading it for plausibility — a 14-column list looks
    complete on its own. COROLLARY, the same bug's second half: a table in NEITHER the
    handled-registry NOR the deliberately-ignored registry lands in a
    "reported-but-not-merged" middle state that READS as intentional in the restore report —
    `source_qualification_attempts` was counted on every restore and copied on none. Any
    handled/ignored pair needs a completeness check that a new table must join one set or the
    other, or the gap presents itself as a feature. DIRECTIONAL LESSON worth more than either:
    the loss inverted a SAFETY property — a `disqualified` source arrived as `unqualified`,
    which is byte-identical to never-judged, so the merge laundered known-bad sources back into
    the trial queue with their backoff ladder reset. When a dropped field encodes a NEGATIVE
    verdict, ask what the default means, not just what was lost; and note that this direction
    was found only by the adversarial pass — both initial readers correctly identified the
    dropped columns and neither noticed the inversion.
  - **ELEMENT `opacity` MAKES A CONTRAST PAIR LIE — score the COMPOSITED colour, not the
    declared one (2026-07-31, the `.ag-cal` calendar-chip field report):** a rule reading
    `background:var(--panel); color:var(--muted); opacity:.6` looks like a muted-on-panel
    pair, and muted-on-panel passes AA on every theme. It is not that pair. Element opacity
    composites the WHOLE element over what is BEHIND it, so the real text pixel is
    `0.6*--muted + 0.4*--panel` while the background pixel stays `--panel` — the dimming eats
    40% of an already-soft pair and contributes nothing to the background it is measured
    against. Measured across all 17 themes: **16 FAILED WCAG AA 4.5:1** (worst 2.25 on Paper);
    only `contrast` passed, which is exactly why the maintainer reported it as broken in light
    AND dark rather than as a light-theme bug like the earlier `--caveat`/`--warn` failures.
    THREE RULES: (a) any contrast check over a rule that sets `opacity` (or sits inside an
    opacity-carrying ancestor) must compute `α*fg + (1-α)*parent_bg` vs `parent_bg`, or it
    scores a pair that never appears on screen; (b) do not fix it by nudging the token — plain
    `--muted` passes once the opacity is gone, but only just (worst 4.56), so prefer a
    dedicated theme-DERIVED token (`--chip-off:color-mix(in srgb, var(--fg) 50%, var(--muted)
    50%)`, worst 5.70) for the same reason `--caveat` exists: a hardcoded hue failed 8/17
    themes; (c) dimming was never the right way to say "off" anyway — the ON state here was
    already carried by an accent background + border, so removing the opacity cost no
    legibility of STATE, and the toggle additionally gained `aria-pressed` so state is not
    colour-only. Corollary for the guard: assert the opacity is ABSENT from the rule (a
    re-added `opacity` silently restores the bug while every declared colour still looks fine).
  - **A BASELINE DIFF MUST PROVE THE HEAD SIDE RAN THE CHANGED TREE — a clean diff from a
    harness that tested the baseline TWICE is indistinguishable from a real pass
    (2026-07-31, the PR-6 verification):** the runner script was
    `cd "$SP/base-wt" && pytest > base.txt` followed by `pytest > head.txt` — and the `cd`
    PERSISTS into the second command, so both sides ran the BASELINE worktree. The diff came
    back "zero introduced, zero gone" and was worthless. THE TELL, and the cheap permanent
    fix: a PR that ADDS tests must show a PASS-COUNT DELTA equal to the tests it adds (here
    4493 -> 4510, exactly the 15 ladder + 2 invariant tests); identical counts on both sides
    of such a PR is proof the head side never ran the change. A failure-NAME diff cannot show
    this — it compares only names, so "no new names" reads the same whether the change is
    clean or was never executed. So assert THREE things, not one: (a) the head run's actual
    cwd (echo it into the log), (b) the pass-count delta matches the tests added, (c) the
    name-diff is empty. This is the same family as the recorded "a baseline diff is blind
    where the baseline is already red" lesson — both are ways a green diff can certify
    nothing — and the same family as "a verdict must map to the bar it actually tested".
    GENERAL FORM: in any two-run comparison harness, the run that is supposed to be
    DIFFERENT must carry a positive, independently-predictable signature of its difference;
    without one, a harness bug that silently makes the two runs identical presents as the
    best possible result. **THIRD WAY THE SAME HARNESS LIES, hit on the very next PR
    (2026-07-31, PR-8): pytest ABORTS the whole run on collection errors**, and this sandbox
    is py3.11 against a py3.13 repo, so ~46 files fail to import. Both sides then finish in
    ~20 s having executed ZERO tests, and the name-diff comes back empty — a perfect-looking
    result from a run that never happened. `--continue-on-collection-errors` is mandatory
    here, and the tell is the same one as the cwd bug: **the totals line has no `passed` in
    it at all**. So the harness must print BOTH sides' full summary lines and the delta, not
    just the diff — a diff over two empty sets is empty.
  - **A "MUST BE GONE" SOURCE GUARD FAILS ON THE COMMENT THAT RECORDS THE REMOVAL
    (2026-07-31, PR-8's AI-subtab guards):** every assertion of the form "this string no
    longer appears in function X" is written next to a comment explaining WHY it was
    removed — and that comment necessarily QUOTES the removed string. The first draft of
    three such guards failed against correct code, on their own explanations. The repo
    already knew this in one place (the hardware-damage guard is deliberately BEHAVIOURAL,
    with a docstring saying a source grep "would also forbid the comments that EXPLAIN why
    the claim is absent") — the generalisation is: a negative source guard must read
    COMMENT-STRIPPED source (drop whole-line `//`, which leaves a `https://` inside a string
    literal untouched), or be behavioural. Do not solve it by rewording the comment: the
    comment is the thing a future session reads before deciding the removal was a mistake.
  - **A SOURCE-EXTRACTING TEST MUST START BRACE-MATCHING AT THE *BODY* BRACE, OR ITS GUARDS
    PASS VACUOUSLY (2026-08-01, Session D S1):** the house pattern for testing `app.js` logic
    is to EXTRACT the function from the real file by name (a re-typed copy would pass while the
    shipped code was broken). The naive extractor takes the first `{` after the function name —
    but `function ooChart(el, seriesList, opts = {})` carries a `{}` in a DEFAULT PARAMETER, so
    depth goes 1→0 immediately and the "body" is the signature alone. Every source-level
    assertion over that empty slice then passes for free. Scan forward until the PARENTHESES
    balance, then take the next `{`. Two sibling forms of the same trap appeared in the same
    session: a slice that runs from a function to the next top-level declaration sweeps in
    unrelated code (an Overview guard asserting "never calls the LLM" was reading 150 lines of
    other functions), and — the expensive one — **`test_commodities_category_subtabs` was
    passing by ACCIDENT for months**: its whole-file `'{initial: "__all"}'` assertion matched
    the HOME families call site, while the commodities code it names passes the shorthand
    `{initial}`. GENERAL FORM: a whole-file substring assertion is only as meaningful as that
    string's UNIQUENESS; a test scoped to one surface must slice to that surface, and when a
    guard fails against code you believe is correct, check whether it was ever testing what it
    claimed before "fixing" the code.
  - **EXTENDING A SERVER-EMITTED STRING THAT IS ITSELF AN i18n KEY SILENTLY UN-TRANSLATES IT
    (2026-08-01, Session D S2):** `ALERT_CAVEAT` is injected into the DOM and translated by the
    i18n walker's EXACT-key lookup, so appending two sentences to it changed the key and every
    non-English locale fell back to English — caught only because a dedicated test pins that key
    across all 12 files. The fix is a RE-KEY, not a new key: pop the old entry, append the
    translated new sentences to each locale's EXISTING (already-reviewed) translation, and write
    it under the new key. Adding the new key while leaving the old one orphans a translation and
    leaves the gate green. Before editing any long server-side constant, grep the locale files
    for its opening words.
  - **`re.split` CONSUMES ITS SEPARATOR — only an EXACT-COVERAGE assertion catches what that
    loses (2026-08-02, Session E S4):** the never-truncate chunker for user-asked summarize/
    translate split sentences on `(?<=[.!?。！？])\s+`. The lookbehind keeps the punctuation, but
    the `\s+` is consumed, so every inter-sentence space vanished and a translation reassembled
    from the parts came back subtly wrong — plausible text, quietly damaged, and invisible to any
    test that checks the parts "look right". Split at `m.end()` (the separator stays with the
    piece before it) and assert the PROPERTY: `"".join(chunk_text(t, n)) == t`, over several
    shapes (paragraphs, punctuation-dense, punctuation-free, CJK, mixed) × several budgets. The
    general form: for any splitter whose output is meant to be reassembled, the test is exact
    reconstruction, never per-piece plausibility.
  - **A FastAPI DEFAULT IS A SENTINEL OBJECT WHEN THE FUNCTION IS CALLED DIRECTLY — AND
    `Query(False)` IS TRUTHY (2026-08-02, Session E S4, caught by CI not by the local run):**
    `Depends(...)`/`Query(...)` defaults are resolved by FASTAPI, so any other caller gets the
    sentinel itself. `_all_diagnostics_members` builds `ai.json` by calling the route
    DIRECTLY, so adding `measure_corpus: bool = Query(False), db: Session = Depends(get_db)`
    to it meant the bundle took the `if measure_corpus:` branch (a `Query` object is truthy!)
    and handed a `Depends` object to a function expecting a Session. The bundle's own
    `_safe()` would have swallowed that into `{"section_ok": False}`, so EVERY bundle would
    have shipped a degraded `ai.json` and nothing would have said so — the degrade wrapper
    becoming the hiding place for the bug, the K2 lesson again. THE RULE: a route that is also
    called directly must have its arguments passed EXPLICITLY at every such call site (the
    file's own `leads_quality(download=False, db=db)` convention), and the guard must be
    BEHAVIOURAL — drive the real member generator and assert the payload is a real report, not
    a sentinel section. A source-level check of the route signature would have passed.
  - **PARSE A VALUE-BEARING PROVENANCE STRING DEFENSIVELY BEFORE EXTENDING IT (2026-08-02,
    Session E S4):** `ArticleAnalysis.prompt_version` is `String(50)` and is NOT just a version —
    the translation TARGET LANGUAGE lives inside it after a colon (`translate-v2:French`), read
    back by `_parse_target_language`. Appending a method suffix (`+chunked-3`) to record that a
    run was chunked would have made the displayed target "French+chunked-3", and a 50-character
    truncation could have cut into the language itself. TWO fixes, both needed: the parser strips
    the suffix, and the WRITER refuses to append when the result would overflow — losing a method
    note is strictly better than corrupting a value. Same family as the i18n-key lesson above:
    before extending any string, find out what already reads it and what else it carries.
  - **A BACKSTOP MAY BE THE ONLY THING GUARDING A PATH — "every real path checks the gate
    itself" IS AN ENUMERATION, AND ENUMERATIONS ARE WRONG (2026-08-01, the AI-install egress
    window):** relaxing the socket-level airplane backstop process-wide was justified in
    writing by "every real fetch path still refuses itself at its own gate — both gates are
    chokepoints the whole app funnels through." Two modules were absent from both:
    `src/monitoring/preflight.py` and `feed_preflight.py` call `EthicalFetcher._guard_target`
    / `_guarded_redirect_get` **directly** instead of `fetch()` (so they never meet the
    `_KILL` check, which lives only in `fetch`/`sitemaps_for`) and use the fetcher's plain
    `requests.Session` rather than a `GuardedSession` (so they never meet that one either).
    The backstop had been their sole protection since it was built — which is precisely what
    a backstop is FOR, and precisely why its removal read as safe. Live-reproduced: an open
    window let a preflight sweep DNS-resolve and HTTP-fetch scraped-source hosts. THREE
    RULES. (a) Before relaxing a catch-all, do not audit the paths you can name — grep for
    callers of the guarded thing's INTERNAL helpers, because a caller that reached past the
    front door is exactly the one your enumeration omits. (b) Scope the relaxation to the
    narrowest axis that still works: here THREAD + single request (`threading.local` entered
    by `GuardedSession.request`), which left the backstop in force for every other thread —
    verified by driving a bare `getaddrinfo` on a second thread. The narrow version was no
    harder to write than the broad one; it was only harder to THINK of. (c) Bind the two
    gates in ONE place — the exemption is entered by the same method that performs the
    app-level check, so a call site cannot opt into one and forget the other. COROLLARY on
    fixing it: also give the bypassed path its own gate (`_KILL` in the two side doors), so
    the docstring's claim becomes true rather than merely re-enforced from above; a DNS
    resolve is itself egress (it hands the resolver the list of sources the operator reads),
    so a test must assert zero RESOLUTIONS, not merely zero HTTP requests. And the sibling
    lesson the same review produced: **a self-closing resource whose only reaper is an HTTP
    status endpoint closes when a browser happens to poll it** — `reap_idle` had exactly one
    caller, so "it closes on its own once the install finishes" (a sentence in the consent
    dialog) held only while a tab was open. If a UI string promises a lifecycle, the
    lifecycle needs a driver the UI does not own.
  - **TWO COMPONENTS THAT EACH HARDCODE A DEFAULT PORT WILL EVENTUALLY WANT THE SAME ONE —
    and the health probe then reports the WRONG DIAGNOSIS (2026-08-02, "installing vLLM on a
    new machine fails"):** `vllm_lifecycle.DEFAULT_PORT = 8000` and `main.py`'s
    `os.getenv("OO_PORT", "8000")` were written years apart and never read together, so
    `vllm serve` could never bind on any machine that finished an install — `OSError(98)
    Address already in use`, reproduced live. THE PART WORTH REMEMBERING IS THE MISREPORT:
    `is_running()` probed `GET /v1/models` on that port, reached THE APP, got a 404 (the app
    has no such route) and concluded "vLLM is down" — 270 of those 404s in one field session,
    logged by the app's own error log as if an external service were flaky. A boolean
    up/down probe cannot distinguish *not started* from *something else is here*, and it will
    confidently answer the wrong one; give it a `port_occupant()`-style third state and let
    `start()` refuse a doomed launch BY NAME instead of spawning a process that cannot bind.
    Two corollaries: DERIVE the second port from the first (`OO_PORT` + 1) rather than
    hardcoding the new value — a hardcoded 8001 re-collides the moment the operator moves the
    app — and make a malformed override fall back to the DERIVATION, never to the old flat
    constant, which would restore the exact bug through the error path. The test reads the
    app's own default out of `main.py` by regex rather than duplicating it, so moving
    `OO_PORT` reddens the test instead of silently passing. **PROCESS NOTE, the reason this
    was diagnosable at all:** the fix that shipped days earlier (the install journal's
    `resolver`/`fallback_fired`/`duration_s`/`package_present`) is what proved the install had
    SUCCEEDED — without it the report "the install fails" would have been investigated as an
    install bug. Instrumentation earns its keep on the first field report that contradicts its
    own headline.
  - **A SELECTION FUNCTION ANSWERS THE QUESTION IT WAS WRITTEN FOR — reading its
    answer for a DIFFERENT question is where the fabrication enters (2026-08-02,
    "the model does not download"):** `resolve_backend()` answers ROUTING — who can
    serve a request right now — so an unreachable backend is correctly disqualified
    and Ollama is the ruled fallback. The default-model plan read that answer as a
    DOWNLOAD target, and on a GPU machine with vLLM installed-but-stopped and Ollama
    absent it named an Ollama tag and queued a pull into a daemon that does not
    exist — while the panel directly above said "This machine will use vLLM",
    because the frontend picked its target from the hardware. The resolver was not
    wrong; the *reuse* was. PROVISIONING asks what the machine will serve with ONCE
    SET UP, where not-running-yet is the normal state, so it must decide from what
    is INSTALLED and fall back to the same hardware rule the other consumer already
    uses — otherwise two notions of "which backend" meet inside one chain and
    disagree. When you reach for an existing decision function, name the question it
    was built to answer and check it is yours; if it is not, derive the second answer
    from the same facts rather than adding a second probe. **SECOND DEFECT, and the
    reason the first was silent:** the endpoint and its ONLY consumer never agreed
    where the answer lives. `_followJob` returns when it sees a top-level `state` that
    is not `"running"`; `/default-model/status` published none on EITHER branch (one
    nested a job under `job`, the other returned a raw queue with no state at all), so
    it polled every three seconds forever and the chain hung — and a poller with no
    terminal condition is indistinguishable from slow work. When a payload feeds a
    follower, the terminal condition is part of the contract; keep a third state
    (`idle` = nothing was ever asked) distinct from success, or a never-started job
    reads as a finished one. **THIRD, cheap and recurring:** a hand-written test
    double of a payload drifts — a two-key resolver stub passed for months while
    omitting every field a caller might read, then failed against *correct* code the
    moment a new field was consulted. Build the double with the payload's own builder
    (`backend._result` here), so a double can never describe a machine that could not
    exist.
  - **A TEST THAT STARTS A REAL WORKER AND NEVER JOINS IT POISONS THE WHOLE PYTEST
    PROCESS — and the bill arrives in a different file thousands of tests later
    (2026-08-02, the Core-only egress-window flake):**
    `test_start_seeds_mirrors_and_checksum_only_on_a_new_entry` was the only test in
    its file that called `start()` — every sibling drives `_download` directly, which
    launches nothing — so it alone needed injected seams, and it had none. It fetched
    for real and left `oo-dump-en:pages-articles` running as a DAEMON for the rest of
    the run (live-reproduced: still alive when the test body ends). The
    egress-window `guard` fixture clears the kill switch during setup, so whenever
    that worker's retry landed in the window it reached a real `socket.connect` —
    and the fixture records into a **process-global** spy and asserts an exact list
    against it. FOUR general rules. (a) Before trusting "the sibling tests are safe,"
    check which API actually LAUNCHES something: `start()` and `_download` are not
    interchangeable, and only one of them needs joining. (b) A test asserting an
    exact list against a process-global patch point is making a claim about the whole
    PROCESS, not about itself — thread-scope the record, but keep foreign calls in a
    `.foreign` list that prints on failure, or a guarded path that genuinely moved a
    fetch onto a worker thread vanishes from the negative-space assertion that exists
    to catch it. (c) When a lane fails intermittently, look for a second workflow run
    on the SAME sha — this repo runs push and pull_request lanes concurrently, which
    is a free A/B that separates a flake from a regression in one lookup (here: one
    pass, one fail, identical commit). (d) READ THE CAPTURED TEARDOWN before
    theorizing: the failing test's own stderr carried a `src.wiki.dumps _default_get`
    traceback — a completely different subsystem naming the culprit outright, while
    every plausible mechanism I could reason out from the failing file was wrong.
  - **A LINE DRAWN ACROSS A HOLE IS A FABRICATED MEASUREMENT — AND THE OBVIOUS GUARD
    AGAINST IT IS INVERTED BY `isFinite(null)` (2026-08-02, honest gaps in the chart
    toolkit):** both renderers in the ONE toolkit bridged holes — `dashChartSvg`
    emitted a single `<polyline>` over every point, `ooChart` coerced `+p.v` and
    lineTo'd unconditionally — which the project's own committed chart framework
    rejects outright ("Render gaps as gaps; mark 'no data' distinctly"), and which
    `ooviz.pathWithGaps` had existed to prevent since it was written, with no caller.
    THE TRAP, found by the test and not by reading: **`isFinite(null)` is `true` and
    `+null` is `0`**, so the natural "keep the finite values" filter keeps a published
    gap as a plotted **zero** — a fabricated measurement, strictly worse than the
    bridged line it hides inside. `ooViz.isMissing` already encoded the right rule.
    THREE general rules. (a) The opposite failure is equally dishonest — a fabricated
    gap invents an outage — so every "it breaks here" test needs an "and it does NOT
    break there" beside it, or an over-eager splitter ships looking conservative.
    (b) Key the gap rule to the series' OWN median cadence rather than a fixed
    duration (one rule then serves hourly counters and annual indicators alike),
    refuse to guess a cadence from fewer than three intervals, and apply it ONLY
    where the axis is a real time axis — on an INDEX axis the spacing claims
    observation order, not elapsed time, so bridging fabricates nothing and the
    output stays byte-identical, which is what bounds the blast radius of a change
    that touches every chart. (c) Write a test's expectation with its OWN explicit
    predicate, never by borrowing the implementation's helper: the first draft of the
    exact-coverage assertion here wrote `isFinite(pts[i].v)` and failed against
    correct code — the trap catching the test written to catch it — and comparing an
    implementation against itself would have proved nothing either way.
  - **A NAMESPACE'S CASING CAN MAKE A WHOLE SUBSYSTEM LOOK DEAD (2026-08-02, the same
    pass):** the 2026-07-28 GUI audit recorded that `ooviz.js`'s primitives were
    "BUILT + TESTED with ZERO call sites", and a first grep here agreed. Both were
    wrong: the namespace is **`ooViz`**, not `ooviz`, and six primitives are wired,
    with `slopeChartSvg`, `smallMultiplesSvg` and `ringDumbbellSvg` already shipping
    on them. A case-sensitive grep for a name you did not read out of the file is not
    evidence of absence — read the export site first. (Same pass: `ooDonut` DOES have
    a slice-count guard, falling back to theme-derived share bars past five, so that
    half of audit finding V-4 is spent too. Recorded so neither is "fixed" twice.)
  - **AN INSTRUMENT ON A HOT PATH IS A LOAD SOURCE — and "durable=False" meant
    "skip the fsync", not "cheap" (2026-08-06, the import that left the app
    unbootable):** PR #878 added a per-statement breadcrumb to diagnose a merge
    step and sent it through `runlog.milestone(durable=False)`. That flag controls
    ONLY whether `fsync` is called; the FILE is chosen by `beat=`, which
    `milestone()` hardcodes to False — so every breadcrumb was appended and
    flushed to the milestone stream, the one the module's own docstring calls
    "never trimmed". The beat file has a 5,760-line ring; the milestone file had
    no ceiling at all. MEASURED, from the operator's two bundles: `run_logs` went
    **11 MB / 76 files → 1,615 MB / 78 files** across one 24 h merge. THE SECOND
    HALF IS WHERE IT BECAME UNRECOVERABLE: `_read_jsonl` loaded a whole journal
    into a list of dicts with no cap, and `promote_incomplete_runs` calls it at
    BOOT, before the unlock screen, over up to 50 files. Parsed JSON costs several
    times its on-disk size, so on a 12.5 GB box with 1 GB of swap the app was
    OOM-killed at startup on every attempt — and an OOM is a SIGKILL, so the
    `except Exception` wrapped around that call could not catch it, and a
    reinstall could not fix it because a reinstall does not touch `data/`. FOUR
    GENERAL RULES. (a) Before putting an event on a per-call path, ask what
    *writes* it, not just what computes it; a flush under a lock per SQL statement
    is a throughput change, not instrumentation. (b) An in-flight breadcrumb wants
    to be a STORE the existing sampler reads (`runlog.statement` → the beat), not
    a write — the beat is already capped, already periodic, and a statement that
    finishes in milliseconds needed no record at all; only one still running at
    the next sample did. (c) "Not trimmed" is a promise about ORDER, never about
    SIZE: any append-only stream whose safety rests on "these events are rare"
    needs that premise ENFORCED (a byte cap, with the forensic-contract events
    exempt so a capped journal never reads as a killed run), because the next
    person to violate it will be as sure as I was. (d) Every reader of an
    on-disk artifact needs a ceiling **independently** of the writer, since the
    oversized file already exists by the time you find out; and a bounded read
    keeps BOTH ends and states the gap, because which end matters depends on the
    question (`run_begin` identifies the run, `run_end` says how it ended) — then
    anything derived by PAIRING events across the gap, like an unmatched
    `stage_begin`, must be published with its basis rather than as a measurement.
    MY OWN PR TEXT CARRIED THE REFUTATION: it claimed "no per-row cost — these are
    bulk statements, a handful per step, not one per article", which is true of
    the six statements in the step I was looking at and false across all 19. I
    wrote a quantitative claim without counting, in the comment right above the
    code that depended on it.
  - **A LOG TAIL IS THE WRONG HALF WHEN THE ROOT CAUSE COMES FROM A CHILD PROCESS
    (2026-08-02, the vLLM start failure):** `server_log_tail` kept the last 8000 bytes
    on the written assumption that "a CUDA OOM puts the actionable numbers at the END".
    That is true when a RUNNING server dies and exactly false at STARTUP: vLLM's
    EngineCore is a child, so it prints its traceback FIRST and the parent then dumps
    ~20 KB of its own stack ending in the words **"See root cause above."** — the log
    literally telling you the instrument is pointed the wrong way. The field bundle was
    29,855 bytes with the last 8,000 kept, every one of them the parent's stack. GENERAL
    FORM: before bounding a captured log, ask which PROCESS prints the reason and in what
    order; a parent that re-raises a child's failure inverts the usual "the end is the
    interesting part" rule. Keeping both ends is cheap; keeping only one is a bet on the
    failure shape. And state the gap (`elided_bytes`) so two retained halves can never be
    read as contiguous.
  - **WHEN A COMPUTED VALUE IS CLAMPED, CHECK WHETHER THE CLAMP IS DOING ALL THE WORK —
    and a test asserting `large >= small` passes for a constant (2026-08-02, same
    session):** `compute_server_args` published `max_model_len` with a method string
    saying it "scales with the remaining VRAM", and returned **32768 for every card from
    6 GB to 80 GB**. A unit error (0.5 MB treated as the cost of a THOUSAND context
    tokens when it is the cost of ONE for a 7B-class fp16 model, then multiplied by a
    further 1000) put the estimate three orders of magnitude high, so the cap decided
    every machine while the disclosure claimed a derivation — a fabricated method, which
    is the honesty defect even before any crash. Its guard,
    `test_compute_server_args_scales_with_vram`, asserted `large >= small` and had been
    passing for years against a function that did not scale at all; the mutation check
    prints the tell as `assert 32768 > 32768`. TWO RULES: a monotonicity assertion over a
    clamped value must be STRICT, or it is satisfied by the constant it exists to catch;
    and when correcting a wrong constant, prefer fixing its UNIT over inventing a new
    number — the 0.5 MB figure was right, only its denominator was wrong, so the fix
    needed no new estimate to defend.
  - **A THICK MEASUREMENT WINDOW IS THE SIGNATURE OF A POLLER, SO SELECTING ON IT SELECTS
    AWAY EVERY INTERACTIVE ROUTE (2026-08-02, the snappy bar):** `all_interactive_pass`
    and K2 judged only routes with `window_n >= 20` and reported GREEN at 31.2 ms while
    `GET /api/articles` sat at a measured p95 of **68,137 ms** in the same reservoir. The
    three routes that qualified were all 2-second pollers — and that is structural, not
    bad luck: the UI polls `/api/system/network` 275 times a session while a person opens
    the article list twice, so an n-threshold is a near-perfect *anti*-filter for the
    thing being measured. The deeper error was reading `low-n` as "no measurement exists"
    when it means "the measurement's TYPICALITY is unproven" — 68 seconds was really
    observed. Report the breach with its n rather than dropping it, and never let a
    confidence label double as an existence label. NEGATIVE-SPACE TWIN, mandatory here: a
    thin-but-FAST route must NOT break the pass, or the fix trades a fabricated green for
    a fabricated red that fires on every freshly-booted process.
  - **A HEALTH PROBE CANNOT TELL "GONE" FROM "MOMENTARILY UNREACHABLE" — so it may
    enrich a message but must never decide a retry (2026-08-02, the AI-sweep outage
    reason):** the sweeps' "local model hiccup (1/10) — retrying in 5s" was wrong in
    every part (`resolve_backend()` already knew `no_backend: true` with a precise
    reason), and the obvious fix — have the probe classify the outage as terminal and
    short-circuit the retry budget — was WRONG in a way the repo's own progressive-sweep
    tests caught within one run: a model reload, a restart and a busy server all answer a
    health probe identically, so that would end a multi-hour sweep on the first blip,
    destroying the exact guarantee the backoff exists to provide. Split the two concerns:
    the probe supplies WORDS (beside, never instead of, the raw error), the caller keeps
    the CONTROL FLOW. Pin it with a test that the helper exposes no verdict at all, since
    the tempting version is one refactor away. Same family as the port-collision lesson —
    a boolean up/down probe will confidently answer a question it cannot see.
  - **AN ABSOLUTE FLOOR FIXES THE BLIND DIRECTION AND LEAVES THE NOISY ONE OPEN — a
    zero-spread cohort makes `v > p90` mean `v > 0` (2026-08-02, source-audit):** the
    recorded tail-blindness lesson added `PATHOLOGY_ABS_FLOOR` so a DEGRADED cohort could
    not hide a broken source. The mirror case went unexamined: on a PERFECTLY CLEAN cohort
    the robust p90 and MAD are both exactly 0.0, so the tail test degenerates to
    "greater than zero" and ONE pathological article out of 1,992 became an
    extraction-failure verdict — all 63 sources the field called "failing" were this, each
    100–1000× below its own floor, Al Jazeera and Le Dépêche among them. A RATE cannot
    carry this weight (1-in-1,992 and 600-in-1,200 are the same number to a threshold), so
    guard the high-confidence criterion on the raw COUNT — which `per_source_metrics`
    already computed and discarded. GENERAL FORM: whenever a robust-statistic outlier test
    can meet a degenerate distribution, ask what the test *reduces to* there; and when a
    fix adds a floor for one failure direction, write the twin test for the other before
    assuming the criterion is now sound.
  - **A BOOT-ONLY JANITOR IS A JANITOR THAT NEVER RUNS, ON EXACTLY THE INSTANCE THAT NEEDS
    IT (2026-08-02, the orphaned restore staging):** `cleanup_stale_staging` reclaims
    `.restore-*` dirs at boot, guarded at 24 h so a live job is never swept. Both halves
    are correct and they compose into a hole: a dir orphaned in hour 1 is too YOUNG at the
    next boot check and is never looked at again, so it survives the entire uptime — and
    the longer the instance runs, the more certain that is, on the very machines the
    14-day-continuous KPI is asking for. Its sibling (the pre-restore snapshot sweep)
    already ran both at boot AND off-peak, which is the shape to copy. The cost is not the
    bytes: for an encrypted corpus a staging tree holds a PLAINTEXT copy, so an unswept
    one is an at-rest-encryption hole for as long as the app stays up. GENERAL FORM: any
    cleanup with an AGE GUARD needs a RECURRING trigger, because the guard guarantees the
    first look will be too early.
  - **A MUTATION TEST MUST REVERT EVERY MECHANISM THE FIX SHIPPED — reverting one of two
    proves nothing and reads as "the guard is dead" (2026-08-02, the WAL-starvation
    recalibration):** checking that `test_wal_reader_starvation`'s discriminating
    assertion still bites, I removed PR-D's between-producer `session.commit()` and the
    test still PASSED. The tempting conclusion — that the guard had silently stopped
    discriminating, which the file's own comments warn is a thing that happened before —
    was WRONG. PR-D shipped TWO independent WAL-releasing mechanisms
    (`_release_transaction` *and* `_WalGuardResult.fetchmany`'s periodic in-scan close),
    and either alone lets a checkpoint through, so a single-mechanism mutation changes
    nothing. Reverting both fails loudly and by name. RULE: before concluding a guard is
    vacuous, grep the fix for every path that satisfies it and neuter ALL of them —
    otherwise the mutation is testing your model of the fix, not the fix. Corollary worth
    keeping about the RECALIBRATION itself: the test was tuned so tightly (macOS measured
    2,006,504 bytes against a 2,097,152 bar — 96% of the way) that ordinary platform
    variance tipped it, and the honest lever was the one the file's own failure messages
    already named (`_TARGET_WRITES`, which raises WAL PRESSURE) rather than the assertion
    threshold. Raising the input a guard is fed strengthens a reproduction; lowering the
    bar it must clear weakens it, and only one of those is a legitimate response to a red
    lane. Calibrate against the WEAKEST platform observed, not the strongest, and record
    the per-platform measurement beside the constant so the next session does not
    re-derive it.
  - **A TEST THAT COMPRESSES TIME MUST COMPRESS THE THROTTLES TOO, OR IT SILENTLY MODELS A
    CASE THAT CANNOT OCCUR (2026-08-04, the same WAL soak test going red on CI two days
    later):** `test_wal_starvation_soak` shrinks a "scan that can run for MINUTES" — the
    production case its own comment cites — down to 0.8 s, but left
    `_WAL_GUARD_MIN_RELEASE_INTERVAL_S` at its production **30 s**. So every release after
    the unconditional first one was throttled out and the scan offered the checkpointer
    exactly **ONE** window, measured at **t=0.009 s**, before the checkpointer had finished
    its first 50 ms sleep. The whole assertion turned on whether a thread happened to fire
    inside nine milliseconds — luck that held locally (a deterministic 9 attempts, byte-identical
    4,902,832-byte WAL, run after run) and stopped holding on a cold shared runner. THE TELL
    THAT IT WAS NEVER ABOUT LOAD: CPU contention (12 spinners on 4 cores) reproduced nothing,
    8/8 green; and my first reproducer — widening the checkpointer's *inter-attempt* sleep —
    also reproduced nothing (6/6 at every width, even at fewer attempts than CI's failing
    round), because it never delayed the FIRST attempt, which is the only one that can catch a
    9 ms window. Delaying the first attempt by 0.15 / 0.30 / 0.60 s reproduces it exactly:
    1/6, 0/6, 0/6. **BOTH assertions rested on that one accident** — the WAL bound moved with
    it, 82% of ceiling → 110% → 132% → 158%, so "fixing" the checkpoint assertion by any
    route that lengthened the window would have traded it for the other one. Compressing the
    throttle to match the compressed scan fixes both (6/6 at every delay; WAL 4–13% of
    ceiling) and CANNOT weaken discrimination, because an unpatched build releases ZERO times
    at ANY interval — pinned by re-running the mutation matrix above at the new setting:
    in-scan release removed → **0/5**, between-producer commit removed → 5/5 (the recorded
    trap, reproduced), both removed → 0/5. GENERAL FORM: when a test scales one dimension of
    a mechanism down for runtime, list every *other* constant that dimension is compared
    against; any left at production scale silently converts the test into a different, usually
    degenerate, case. And add the anti-vacuity assertion one level below the property — here,
    that the scan actually OFFERED several windows (`wal_releases >= 4`; it is 2 without the
    compression) — because the fix is one deleted monkeypatch away from reverting to
    coin-flip, and it would revert as an intermittent CI red that reproduces nowhere.
  - **AGREEING ON THE GATE IS NOT ENOUGH — TWO MODULES PUBLISHING ONE QUANTITY MUST AGREE
    ON THE BUCKET KEY (2026-08-03, the language-equilibrium lever):** the recorded framing-tone
    lesson says modules publishing the same quantity must agree on the *gate*. A weaker
    disagreement is just as costly and much harder to see: `corpus_language_shares` bucketed
    languages on `.strip().lower()` while the house `normalize_lang` strips the region subtag,
    and `Article.language` is stored RAW from `<html lang>` — so `en` / `en-US` / `en_us` were
    three languages to the lever, which then compared ONE SPELLING'S share against the whole
    target. Measured: English deferred on 14.3% of passes where 50.0% is correct, a 3.5x
    under-correction that grows with how region-tagged the corpus is, and the bundled PRESETS
    (keyed on bare codes) could never match at all. FOUR modules in the tree hand-roll a
    per-language bucket key at THREE different normalisation depths, so this is a family, not an
    instance. TWO RULES: normalise on BOTH sides of any comparison — normalising only the corpus
    leaves an operator who writes `en-US` targeting a bucket that cannot exist; and when a fix
    turns a wrong bucket into a right one, write the NEGATIVE-SPACE TWIN (genuinely distinct
    languages must never merge), because an over-eager key is the same defect pointing the other
    way and is INVISIBLE — the shares still sum to 1.
  - **A TOOLKIT-WIDE FIX MUST ENUMERATE EVERY RENDERER, INCLUDING THE ONE WHOSE SIBLING GOT IT
    RIGHT (2026-08-03, smallMultiplesSvg):** the 2026-08-02 honest-gaps pass fixed `dashChartSvg`
    and `ooChart` and missed `smallMultiplesSvg` — which sits thirty lines BELOW `slopeChartSvg`
    in the same file, was written in the same batch, and whose sibling already carried the
    comment "break at gaps, never bridge". Proximity to a correct implementation is not
    coverage. The miss was also the worse half of the defect: a bridged line invents a
    CONNECTION, but `Y(null)` = `padT+(h-padT-padB)*(1-null/maxV)` lands on the zero BASELINE, so
    a published gap became an invented OBSERVATION. (An earlier draft of this entry ALSO blamed the
    scale scan's `isFinite(pt.count)`; an adversarial pass refuted it — `isFinite(null)` is true, but
    the guard was `isFinite(pt.count) && pt.count > maxV` and `null > maxV` coerces to `0 > maxV`,
    which cannot raise a scale starting at 0. Corrected here because a fabricated claim inside an
    honesty fix is the same defect the fix is about.) GENERAL FORM: when fixing a property across a "toolkit", grep for
    every function that emits the primitive (here `<polyline`/`<rect`), not for the renderers you
    can name; and check the ones whose neighbours already comply, since a reviewer's eye reads
    the correct sibling and moves on. COROLLARY worth reusing: geometry must span every SLOT
    while the sparse threshold and the displayed `n` count only real OBSERVATIONS — one number
    keeps the hole's width, the other refuses to claim evidence that was never collected.
    THIRD COROLLARY, from the same review: A CAVEAT MAY CLAIM ONLY WHAT THE DATA CAN EXHIBIT. The
    fixed renderer's one live caller feeds `_window_daily_series`, which OMITS zero-count days
    instead of publishing them as null — so no gap can ever reach it, while the caveat advertising
    gap handling rendered unconditionally. The handling is real and tested; it is simply not
    exercised there, so the sentence is now emitted only when a gap is actually present. A promise
    the shipped data cannot keep is a fabricated assurance even when the code behind it is correct.
    (The omission itself compresses the index axis — day 1 and day 5 render adjacent — which is a
    separate, pre-existing defect affecting the trending sparklines too; recorded, not fixed here,
    because for keyword mentions an absent day is a REAL zero and zero-filling is the right repair,
    not null-filling, and it changes a second shipped surface.)
  - **A MECHANISM THAT QUIETLY RECORDS A DECISION SUPPRESSES THE SAFETY DEFAULT THAT
    DECISION OVERRIDES (2026-08-02, the boot-airplane race, PR #846 merged RED then
    #847):** a field report — "on a new instance the app sometimes stays in airplane
    mode with no explanation" — was a real race: `_run_startup_upkeep` engages airplane
    at its tail, on the unlock path in a BACKGROUND THREAD, and a new instance's upkeep
    is slow enough that the wizard sits on screen throughout it, so an operator who
    crosses online mid-upkeep has the thread's `activate_kill_switch()` land after their
    `clear_kill_switch()`. The FIX was right; where it was recorded was not. Setting the
    crossed-online flag INSIDE `clear_kill_switch()` looked equivalent — clearing the
    switch *is* going online, surely — but that primitive is ALSO how a caller reaches a
    KNOWN STATE: `conftest` calls it around every test, and `test_app_boots_in_airplane_
    mode` calls it itself immediately before booting, precisely to start clean. The boot
    then declined to engage, and the whole test lane went red. **THE DIRECTION IS THE
    LESSON:** a mechanism that quietly counts as a decision SUPPRESSES the boot airplane
    engage — it weakens zero-network boot, the non-negotiable the feature was written to
    leave untouched — so the tempting repair (reset the flag in `conftest`) would have
    kept the weakening and hidden the evidence. Separate the two instead:
    `clear_kill_switch()` records nothing; `note_operator_crossed_online()` records the
    decision, called from the three surfaces where that is what happened (go-online
    endpoint, scheduler start, run-now), which were already its only production callers.
    GENERAL FORM: before folding a state-recording side effect into a primitive, list
    every caller and ask which of them is making a DECISION and which is merely reaching
    a STATE; if both exist, the primitive is the wrong home. COROLLARY that is a separate
    trap: a process-global "has an operator ever done X" flag is correct per-process in
    production (one boot, one operator) and wrong across a shared test session, where
    many tests legitimately act as the operator — it needs a per-test reset beside
    whatever other process-global state the suite already resets.
  - **`os.environ.pop` IN A TEST IS A SESSION-WIDE EDIT, AND ITS FAILURE SURFACES FAR
    FROM ITS CAUSE (2026-08-02, the same fix-forward):** `conftest` sets
    `OO_NO_SCHEDULER=1` once for the whole session; a test that needs production
    behaviour must borrow it with `monkeypatch.delenv(..., raising=False)`. A bare
    `os.environ.pop` deletes it for every LATER test too, so every subsequent
    `TestClient` lifespan takes the production branch — engaging airplane and starting
    the background scheduler. It presented as EIGHT unrelated "the network kill switch is
    active" failures in `csv_feeds`, `jobs`, `llm_ollama` and `markets`, none of which
    had anything to do with the change. WORSE, AND THE PART WORTH KEEPING: the leak had
    shipped one PR earlier and was INVISIBLE, because the very defect above (the flag set
    by `clear_kill_switch`) made the boot engage skip anyway — fixing one bug UNMASKED
    the other, so CI got worse before it got better and the second failure looked like a
    regression from the fix. When a fix makes a lane fail differently rather than less,
    suspect an unmasked pre-existing bug before assuming the fix is wrong. A `conftest`
    guard to fail whichever test leaks the variable was written and DELETED: its teardown
    races `monkeypatch`'s, so it fired on correct code — a gate that reddens on correct
    usage is worse than the leak it catches.
  - **A SELF-LIMITING INSTRUMENT MUST SELF-RECOVER, AND MUST BE CHARGED FOR ITS OWN COST
    (2026-08-02, the run journal's child-CPU walk):** the beat's per-child CPU sample is
    the ONLY thing that separates a healthy process pool (parent near-idle) from a wedged
    one — the module's own docstring says so, and the standing lesson above says it too.
    It was OFF for the entire phase it exists for. Two independent defects, both in the
    shape of a reasonable-looking guard: (a) the cost budget was charged against the
    WHOLE beat, which also reads `/proc/meminfo`, stats the destination filesystem and
    sizes the WAL — so a slow disk stat retired the child walk for a reason that had
    nothing to do with it; (b) the stand-down was a ONE-WAY LATCH. In a 19 h field import
    the walk died at beat 24, during `merging`, because one beat measured 25.9 ms against
    a 25 ms budget — 0.9 ms over — and all 1,561 following `reindexing` beats carried no
    child data at all. The constant's own docstring already said "sampled at a reduced
    cadence"; the code implemented "never again", and nobody had read the two together.
    RULES: time the expensive part ITSELF and report that time (so the cost is measured,
    never assumed), and make the stand-down bounded and recovering. Corollary that held
    up: a backed-off beat must still OMIT the field rather than zero it — `kids_n: 0`
    reads as "no worker processes", the inverse of what it stands in for.
  - **`.get(key, 0)` ON A DELIBERATELY-OMITTED FIELD FABRICATES THE MEASUREMENT THE
    OMISSION EXISTS TO PREVENT (2026-08-02, same investigation, caught before it reached
    the user):** reading the field bundle, I reported that the process pool had "never
    spawned a single worker — 0 children across 5,531 beats" and was one step from
    filing it as the root cause of a 19-hour import. It was my own bug: `kids_n` is
    ABSENT in those beats and my `.get("kids_n", 0)` invented the zero. The instrument
    was honest by construction (it omits with a reason rather than zeroing, exactly as
    its docstring promises) and my reader defeated that honesty in one keystroke. GENERAL
    FORM: when a payload's contract is "an unmeasurable field is omitted", every consumer
    must distinguish missing from zero — count key MEMBERSHIP before aggregating, and be
    suspicious of a striking result that rests on a default argument. The tell here was
    the strength of the finding: 0 children in 5,531 consecutive samples is too clean for
    a real system, and that implausibility is what prompted the re-check.
  - **A BACKSTOP ON ONE PATH IS NOT A BACKSTOP IF THAT PATH HANDS OFF TO AN UNBOUNDED ONE
    (2026-08-02, the re-index precompute stall):** `precompute_batch`'s fallback comment
    calls `_POOL_TIMEOUT_S` "the only thing standing between a deadlocked worker and an
    import that never finishes" — and then, on timeout, hands the whole window to
    `_serial`, a bare dict comprehension with no bound of any kind, which is also the
    deliberate small-batch path. Two field imports each stopped advancing at an exact
    window boundary (9.8 h before recovering; 6 h until killed), burning ~0.75 of a core
    with the WAL byte-frozen and the write gate free — all three facts saying in-process
    pure-CPU work — and nothing in 19 h of journal said WHICH ARTICLE, so there was
    nothing to reproduce from. Python cannot preempt a running C-level regex, so the
    honest fix is not a timeout it could not honour but a NAME: a watchdog thread that
    reports the article id, size and position WHILE IT IS STILL RUNNING, plus an
    after-the-fact line for the recovered case — the two are separate because a killed
    run never reaches the second and a recovered run is invisible to anything else.
    GENERAL FORM: when a guarded path degrades to an unguarded one, the guard's stated
    guarantee is false for the degraded case; check what the fallback inherits.
  - **A WINDOW'S ORDER CAN BE LOAD-BEARING FOR A RESUME CURSOR THAT COUNTS (2026-08-02,
    batching the re-index window load):** replacing a per-article `session.get` loop with
    one `IN (...)` per chunk is a pure perf change — same rows, same bytes through the
    codec — EXCEPT that an `IN (...)` result set has no guaranteed order, and the caller
    turns a COUNT back into an id by POSITION: `merge.py`'s `_tracked` stamps
    `ids[done - 1]` as the last finalised article, and the resume then keeps only
    `i > watermark`. A window staged in any other order would stamp a watermark ABOVE
    articles that were never re-indexed, and the ascending resume would skip them
    permanently — the unbounded invisibility the durable cursor exists to prevent.
    Nothing pinned it: reversing the load order left all 67 tests in the re-index suites
    green. GENERAL FORM: before changing how a collection is fetched, find out whether
    anything downstream indexes into it by position rather than by key — a count-to-id
    mapping is the signature.
  - **A STANDALONE SQL PROBE IS A LOOKALIKE, AND EXPLAIN QUERY PLAN CAN NAME AN INDEX
    THAT NO LONGER EXISTS (2026-08-04, the per-language feed's covering index):** two
    ways a plan assertion certifies nothing, both hit in one slice. (a) I confirmed the
    new composite index covered both of the feed's queries by running the SQL by hand in
    a scratch database — it did, there. Driving the REAL function showed SQLite serving
    the second query from a NARROWER index instead (`language IS NULL` is an equality
    seek; the composite's leading column is a range), then reading the heap for
    `detected_language` — index-only for the series, straight back into the codec for
    the tally, on exactly the rows that are most numerous when a corpus is under-tagged.
    A hand-written lookalike differs from the shipped query in table stats, in ANALYZE
    state, and in which other indexes exist, and all three move the planner. Capture the
    statements the production path actually emits (a `before_cursor_execute` listener)
    and EXPLAIN those. The FIX generalises past this case: when two queries want
    different indexes, fold the second into the first as an extra GROUP BY dimension —
    grouping on the predicate at most doubles the row count and leaves the planner no
    escape. (b) The negative half — "with the index dropped the plan must change" — is
    where it gets dangerous: **pysqlite caches compiled statements per connection and
    the pool hands the same one back, so EXPLAIN keeps reporting the DROPPED index by
    name** (verified: `sqlite_master` empty while the plan still cited it). Without
    `engine.dispose()` that assertion passes whatever the planner would really do — a
    guard that cannot fail, attached to the one claim that makes the positive half
    meaningful. COROLLARY, cheap and recurring: an index over a column a legacy store
    may lack collides with any fixture that simulates the missing column via
    `DROP COLUMN` (SQLite refuses while an index references it). Drop the referencing
    indexes BY REFLECTION rather than by name — the next index over that column then
    cannot silently break a guard that is about something else entirely, and it is also
    more faithful, since a store old enough to lack the column never had an index on it.
  - **A SOURCE GUARD OVER A DISCLOSURE SURVIVES THE MUTATION THAT DELETES THE DISCLOSURE
    (2026-08-04, same slice):** the tile's honesty rests on stating what it does NOT
    draw — the ranked-out tail, the articles with no asserted language. Guarding that
    with `assert "d.other" in body` felt like the house pattern and was worthless:
    neutering `if (other.languages)` to `if (false)` left the identifier sitting in its
    `const other = d.other || {}` binding, so the guard stayed green while the sentence
    vanished. The identifier is not the sentence. Extract the disclosure builder as a
    PURE function and test what it SAYS, in node, with the negative-space twin beside
    each claim (an over-eager disclosure invents missing data as dishonestly as an
    omission hides it) — four mutations that all passed the substring version all fail
    the behavioural one. Same family as the recorded "a whole-file substring assertion
    is only as meaningful as that string's uniqueness", one level sharper: even a
    correctly-SCOPED substring proves only that a token appears somewhere in the slice.
    And check the ratchet — `test_every_node_suite_has_a_driver` exists precisely
    because an unrun node suite already cost a shipped defect.
  - **NEVER RE-SERIALISE A CURATED FILE TO EDIT ONE ENTRY (2026-08-02):** adding a single
    key to the 12 locale files rewrote all 12 — 27,000 lines changed to carry 12 lines of
    real content — because they were written back with `json.dump(sort_keys=True)`. The
    order is not incidental: the files are grouped BY UI SECTION (nav, then home, then
    settings), which is how they are navigated and reviewed, so the sort destroyed that
    grouping permanently, buried the one real change, and guaranteed a conflict with any
    parallel locale work. The maintainer spotted it as "27K lines of code... this seems
    awkward" before review did. Edit in place (textual insert next to the sibling entry),
    and when a rewrite has already happened, verify EQUIVALENCE before restoring — parse
    both sides and assert same keys, same values, only the ordering differs — rather than
    reverting on faith. No repository script does this, so there was nothing in the tree
    to fix; the fix is the habit.
  - **A GUARD CAN PASS FOR A REASON THAT HAS NOTHING TO DO WITH ITS CLAIM — and the ratchet
    meant to catch that class had the same defect (2026-08-04, PR #861, the ruling-7c audit
    of every source-reading test file):** a 14-agent sweep with an adversarial verifier on
    each finding reported examining 8,204 assertions and produced 41 distinct guards that
    could not fail for the reason they were named — 47 confirmed of 58 raw, 11 refuted, each
    hand-re-verified before any edit. FIVE SHAPES, all of which really shipped here. (a) **The
    tautology.** `assert 'ensureOnline("Download an offline map region")' not in osm or
    "ensureOnline" in osm` — the second needle is a SUBSTRING of the first, so the disjunction
    is true for every possible input; it could not have failed with the consent gate deleted
    outright. A three-way disjunction whose third arm is guaranteed by an `assert` four lines
    above is the same thing wearing more clothes, and so is a loop that re-asserts the exact
    regex it just derived its ids from. (b) **The wrong operand.** `assert "score" not in
    "renderAnTrend drawAnTrend"` compares against a Python string LITERAL holding two function
    NAMES — a compile-time constant that never opened app.js, in a file whose every other
    assertion does. (c) **The comment-satisfied positive.** Invariant #16's `"never
    downsampled"`: all three occurrences are on `//` comment lines, and the assertion's own
    message said the toolkit must "state AND implement" the rule. Delete the implementation,
    keep the comment, stay green. (d) **The non-unique needle.** `confirm(` 30 matches,
    `card-caveat` 41, `ensureOnline` 47, `d.caveat` 58 — each asserted about ONE surface and
    satisfied by any of dozens. Its special case: a ZERO-ARGUMENT function's own declaration
    contains `name()`, so `assert "loadFamilyCuration()" in app, "showSetCat must WIRE it"` was
    satisfied by the definition and could not tell wired from defined. (e) **The mis-slice.**
    `split(DELIM)` where DELIM does not occur is a no-op and the "body" becomes the whole
    remainder: `split("\ndef test_")` against `src/api/main.py` — a source file with no tests in
    it — made the slice 108,272 characters, and the guard was then satisfied by `main()`, the
    exact call path its own docstring said must not count. Ten JS slices split on
    `"\n    function "`, which cannot match the `async function` that follows, over-running by
    up to 3.2x; one bounded a CSS rule by "the next selector I could think of" and took 820
    lines for a 20-line block. **THE PART WORTH MOST:** `test_source_slicing_discipline`'s own
    budget read 0 — not because the tree was clean but because its detector was a regex over
    five hardcoded helper NAMES, blind to the inline `html[a:b]` and `src.split(...)` forms
    nearly every slice actually uses; and its sibling "the budget is not left above the real
    count" AGREED, because both sides came from the same blind detector. The real count was
    276. A ratchet is only as good as its detector, and a detector keyed to NAMES is defeated
    by a rename — test the PROPERTY (an AST walk for `.index/.find/.split` taking a code-anchor
    literal, f-strings INCLUDED, since `src.split(f"def {name}(")` is the common parametrised
    form and reading only `ast.Constant` misses every one). GENERAL FORM: for any
    read-the-source guard ask what ELSE in the file satisfies the needle, and whether the slice
    is bounded by something that provably occurs; the correct bound comes from a parser (`ast`
    for Python, brace-matching from the BODY brace for JS and CSS, BRACKET-matching for a JS
    array literal — `tests/js_source_helper.py` now carries all four, each with its failure mode
    pinned), never from a guessed delimiter. The `array_literal` shape is here because the
    ratchet built by this very sweep caught its author reintroducing the class three days later:
    two guards over `_FIG_STYLES` sliced it as `index("const _FIG_STYLES = [")` to
    `index("];")`, which is correct only while no element contains that pair before the array's
    own close — and the elements are themselves arrays. It reddened all three lanes rather than
    shipping a fragment every assertion would have passed against, which is the ratchet earning
    its keep: prefer being stopped by it over lowering its budget.
    And when you fix one, check whether its own failure MESSAGE claims more than the new check
    tests: "state and implement" needed splitting into two guards, one per half. COROLLARY on
    tightening: only ONE assertion in the sweep changed truth value, and that IS the finding —
    `test_honest_empty_and_bounded_states` sliced four functions and three of its four claims
    belonged to siblings. Three scopes would have been wrong without opening the file first
    (a loader that had MOVED to `_ADV_LOADERS`, a caveat in `drawAnTrend` not `renderAnTrend`,
    and a byte window that swept into `UNRESOLVED_CANDIDATES` — exactly where the unverified
    model tag is SUPPOSED to live).
  - **AN LLM TRANSLATION PASS NEEDS A SECOND PASS THAT ONLY CHECKS THE CLAIM, BECAUSE THE
    FAILURE MECHANICAL VALIDATION CANNOT SEE IS AN OFF-BY-ONE (2026-08-04, PR #861, the 127
    honesty/data-safety strings ×12):** eleven translators, then eleven reviewers briefed
    ONLY to catch a changed claim — a dropped negation, a softened "cannot be undone", an
    uncertainty qualifier presented as fact, a mangled identifier. Both halves earned it. The
    **zh** draft SKIPPED index 68 and shifted every later entry up by one, so 59 English keys
    would have carried the NEXT string's translation; its reviewer found the shift and
    renumbered all 58 affected slots. NO mechanical check can catch that: every slot was
    non-empty, in the right script, and a plausible translation OF SOMETHING. The **ru** draft
    rendered "tamper-evident" (alteration is DETECTABLE) as "protected against tampering" —
    claiming a security guarantee the English deliberately does not make, which is exactly the
    line this project draws between honest and fabricated security. Keep the mechanical layer
    too (gaps, English echoes, per-locale script, identifiers/paths preserved) but know what it
    is for. AND WATCH THE CHECKER ITSELF: a path regex captured the sentence's full stop with
    the filename, so three CORRECT translations ending in their own terminator (Bengali "।",
    CJK "。") read as dropped paths — a good translation must never present as a defect, so fix
    the checker rather than counting it.
  - **`cmd | tail` MAKES `$?` THE EXIT CODE OF `tail` — a pre-push gate checked that way
    always reads green (2026-08-04, the #858 bandit red):** the local check was
    `bandit -r src/ -ll -q 2>&1 | tail -5; echo "exit: $?"`, which printed 0 while bandit
    was exiting 1 the whole time, so a real B608 shipped and reddened the `test` lane.
    This is the same family as the recorded cwd-persistence and collection-error harness
    bugs — a verification that reports success without testing what it claims — and it is
    the cheapest of the three to avoid: redirect to a FILE, capture `$?` on its own line,
    THEN read the file (`cmd > out 2>&1; rc=$?`), or set `pipefail`. The tell is that a
    gate you expect to be interesting never says anything interesting.
    **BANDIT-SPECIFIC, and the reason the first two fix attempts failed:** `# nosec` must
    sit on the line bandit REPORTS, which for B608 over a concatenation is the first line
    of the STRING EXPRESSION — not the enclosing `text(...)`/`execute(...)` call, and not
    the `sql = (` assignment. A marker one line off is silently inert; the run then prints
    `nosec encountered (B608), but no failed test` for the misplaced one while still
    failing on the real one, which is the signal to move it rather than add another.
  - **AN EXPLICIT COLUMN ALLOWLIST FAILS ONE GRANULARITY BELOW THE TABLE-LEVEL GUARD YOU
    JUST BUILT (2026-08-03, the fourteen dropped merge columns):** the 2026-07-24 lesson
    named the defect for a whole TABLE and the completeness registry closed that; the same
    `INSERT INTO t (cols) SELECT` allowlist drops every COLUMN added to the model after the
    INSERT was written, and that is the worse half — a missing table is at least COUNTED in
    the restore report, whereas a dropped column produces a row that arrives, a column that
    is nullable, and a value that is a plausible NULL. Fourteen had gone that way. THE TOOL:
    parse the INSERTs with the **AST**, never a grep — inline `# nosec` comments sit between
    the adjacent string literals the parser folds, so a line-oriented scan reports columns as
    missing that are present. THREE SCOPING TRAPS the guard hit, each of which would have made
    it cry wolf or pass vacuously: (a) not every INSERT is a merge-copy — `merge_batches` gets
    the app's OWN record via `INSERT..VALUES` and its `counts_json`/`report_json` are filled by
    later UPDATEs, so scope the guard to the tables that are actually copied (`_MERGE_HANDLED`);
    (b) a column can be carried ELSEWHERE — `keyword_categories.parent_id` is a self-FK
    remapped by a dedicated UPDATE, so it must be declared as handled or the next reader
    "fixes" what already works; (c) an f-string table name is INVISIBLE to the parser, so
    enumerate those blind spots explicitly, pin the set so it cannot grow silently, and cover
    the ones carrying data behaviourally instead. DIRECTIONAL POINT, as with the qualification
    stamp: ask what the dropped value MEANS, not just that it is gone —
    `keyword_supergroup_members.ring_id` is not data about a member but WHICH KIND of member
    it is, and its own migration records NULL as "a plain family member", so it arrived as a
    different, entirely legal kind and the super-group silently stopped spanning languages.
  - **A "THIS WOULD FLAG NOTHING" REJECTION IS WORTH MEASURING, BECAUSE THE MECHANISM MAY BE
    STRONGER THAN THE OBSERVATION (2026-08-03, the furniture detector):** the brief offered
    (a) retire a DF-ubiquity detector that had never fired, or (b) require corroboration from
    the closed-class publishing-boilerplate stoplist, and predicted (b) "may flag nothing
    either". Measuring it produced a better reason to reject it: every term in
    `PLATFORM_STOPWORDS` / `PUBLISHING_BOILERPLATE_SCOPED` is ALREADY a stopword, so none can
    ever be extracted as a keyword, so none can ever reach a per-source top-12 fingerprint —
    (b) flags nothing **by construction**, not merely in practice. That distinction decides the
    ruling: an empirically-quiet detector might wake up on another corpus, whereas an inert one
    that still LOOKS like a working detector is worse than no detector at all. GENERAL FORM:
    when a design option is expected to be useless, check whether it is *structurally* useless
    — the answer changes whether you ship it as a dormant safeguard or refuse it outright. And
    when you retire a signal, retire the VERDICT and keep the numbers: the DF counts are real
    evidence an analyst can read, and the honest artifact says which of the two it is publishing.
  - **A "MUST BE ABSENT" GUARD ALSO TRIPS ON ITS OWN EXPLANATION IN JS, AND THE FIX IS TO
    STRIP COMMENTS, NEVER TO REWORD THEM (2026-08-03, re-hit while adding the settings panel):**
    the recorded 2026-07-31 lesson says this for `app.js` source guards, and it recurred
    immediately: a guard asserting `ensureOnline` is absent from a loopback settings write
    failed on the comment saying *why* it is absent. Rewording the comment is the wrong repair
    — that comment is exactly what a future session reads before deciding the absence was a
    mistake. Strip whole-line `//` before asserting (which leaves a `https://` inside a string
    literal untouched), or make the guard behavioural. Worth re-recording because the lesson
    existed and was still not reached for until the test went red.
  - **THE REPO'S OWN INVARIANTS CATCH FRONTEND BUGS A NON-BROWSER SESSION CANNOT (2026-08-03):**
    two real defects in one panel, neither visible to `node --check`. `t()` was called in four
    new `app.js` functions without binding a local `t` — it is not a global, so opening the
    panel would have thrown "t is not defined" — caught by
    `test_no_app_function_calls_i18n_t_without_binding_it`. And a live-count read `total` from
    an endpoint whose payload calls it `matched`, which fails silently to an empty string; that
    one was caught by reading the endpoint rather than assuming its shape. So on a
    browser-unverified slice, run the FULL invariant suite rather than the tests you wrote, and
    read every endpoint payload you consume — those two guards are most of what stands between a
    conservative frontend slice and a broken one.
  - **A LAZY `.*?` LOOKING FOR A CLOSER THAT MAY NOT EXIST IS QUADRATIC, AND THE UNROLLED-LOOP
    REWRITE DOES NOT FIX IT (2026-08-05, the 412 KB article that wedged a field re-index):**
    `<(style|script)\b[^>]*>.*?</\1\s*>` is the textbook way to strip a block, and it is fine
    until an opener has no closer — then `.*?` expands to end-of-document, fails, and the engine
    RESTARTS that scan from the next opener, so K openers cost K·N. MEASURED at 412,351 chars:
    138.3 s worst case, 25.7 s on realistic unclosed-`<script>` spam, against **0.004 s for the
    same volume of well-formed markup** — a ~350× cliff that turns only on whether the closers
    happen to be there, i.e. reached by ordinary broken HTML rather than by a crafted input. THE
    TRAP WORTH REMEMBERING: the obvious fix — possessive quantifiers and an unrolled loop
    (`[^<]*+(?:<(?!/\1\s*>)[^<]*+)*+`) — removes the BACKTRACKING and bought only **2×** (138 s →
    66 s), because the K restarts are not backtracking; they are K separate linear scans. Only
    leaving the regex engine fixes it: walk openers with two cursors and RETIRE a tag once no
    closer remains after it (if there is no `</style>` after p there is none after any q > p), →
    0.030 s (4,648×). Two further rules: the replacement's copy cursor and scan cursor must be
    SEPARATE — advancing the copy cursor past a skipped opener silently swallows the text before
    it, a bug every one of 19 hand-written cases missed and a randomised differential against the
    old pattern caught in 2,479 of 6,000; and state the LOSS as well as the win — the linear
    version is ~10 ms SLOWER per 412 KB of well-formed style-heavy markup, because it pays two
    Python-level searches per block instead of one C-level `re.sub`. GENERAL FORM: any
    `OPEN.*?CLOSE` over untrusted markup is a K·N bomb; grep for the shape rather than waiting
    for the article that finds it.
  - **AN INSTRUMENT'S OUTPUT NAMES A SUSPECT, NOT A CAUSE — AND TWO STALLS CAN RUN AT ONCE
    (2026-08-05, the same import):** the console line (`serial precompute still on article 26324
    after 17536 s`) and the run journal disagreed: the journal said the run died in `merge` at
    step 3 of 19, having never reached the re-index at all. Both were true — the autonomous
    re-index job was draining an EARLIER batch concurrently, which the `reindex_resume`
    milestones prove. Reading either signal alone produces a confident wrong story. THE
    NEAR-MISS: the journal contains `step_elapsed_s: 26324.0`, so grepping the raw file for the
    article id "26324" returns a coincidental hit — a number matching across two payloads is not
    corroboration, and the units have to be checked before it is treated as such. SECOND HALF:
    that concurrency was itself the 2026-07-24 exclusive-hold lesson recurring one module over —
    the import recorded `owns_the_machine: true` and `hold_exclusive()` still gated only
    `run_now()`, because `reindex_job.py` never consulted `holds_exclusive()`. When a lesson says
    "gate EVERY entry point", the entry points added AFTER it are the ones that will be missing.
  - **NAME THE QUESTION A DECISION FUNCTION ANSWERS, THEN COUNT THE COPIES (2026-08-04, "AI
    backend won't start … local model hiccup"):** the recorded K2/routing lesson says a
    selection function answers the question it was written for. The sequel is that the
    question you need may have NO owner while looking answered. Here THREE existed —
    `resolve_backend` (routing: who serves this request), `provisioning_backend` (setup: what
    will this machine serve with), and a fourth hand-rolled copy in the browser's AI pill —
    and the one nobody owned was ACTIVATION: which backend do I *start*. Both
    `*_lifecycle.start()` functions existed and worked; no caller chose between them, so the
    sweep probed a backend nothing had started and burned its whole retry budget on a
    condition retrying cannot change. TWO COROLLARIES. (a) When a fourth copy lives in the
    frontend, it will have drifted: this one silently fell through to Ollama on a GPU machine
    whose vLLM was installed but whose model id was unset — a decision no other surface would
    have made. (b) **MOVING A DECISION SERVER-SIDE CAN SILENTLY DROP A FALLBACK THE OLD COPY
    HAD**, and that is the expensive half: consolidating the pill's logic lost its
    "preferred backend blocked → try the other one", turning "starts Ollama" into "refuses and
    starts nothing" on a real machine class. Honest and useless. Its own source-anchored test
    caught it, which is the argument for keeping such tests and *following the anchor* rather
    than relaxing them. Carry the preferred backend's blocker through the fallback (else the
    operator never learns why their GPU is idle), and never fall back under an EXPLICIT
    choice — being second-guessed is the one thing an explicit choice must not be.
  - **AN ENV VAR REACHES ONLY THE PROCESSES YOU SPAWN — say so, and make every consumer of the
    derived path agree (2026-08-04, moving model weights into the app folder):** `OLLAMA_MODELS`
    and `HF_HOME` are the whole mechanism for relocating local model weights, which makes the
    change look trivial. It is not, for two reasons. (a) A systemd/launchd-managed daemon has
    its own environment, so the setting cannot reach it; reporting the CONFIGURED path as
    though it were the live one is the fabrication here — an operator whose models are still in
    `~/.ollama` would have no way to tell the setting from a failure. Report configured AND
    detected as separate facts. (b) **COUNT THE CALL SITES THAT DERIVE THE SAME PATH.** Three
    had to agree — the cache PROBE, the weights DOWNLOAD, and the server SPAWN — and pointing
    only the spawn at the new directory would make the probe report "not downloaded" for
    weights that are present, so a guard built on that probe refuses a start that would have
    worked. Nothing about that failure looks like a path bug from outside. Route all of them
    through one resolver and make the agreement a test. And an operator-set value is used
    untouched: relocating several GB because an app preferred its own folder is a surprise,
    not a default.
  - **A JOIN KEY THAT IS ALSO THE PAYLOAD'S ONLY IDENTITY MUST FAIL LOUDLY WHEN IT DANGLES
    (2026-08-04, the dual-backend model catalogue):** composing a view over a dated catalogue
    is the right way to avoid re-typing identifiers that a freshness test governs — but the
    rows had no identity except their tag, so the join is BY tag, so a rename upstream
    (`granite4.1:3b` → `granite4.2:3b`) leaves the reference dangling. The first cut returned
    an empty row, and the model then rendered unavailable **with no reason at all** — a silent
    disappearance from the operator's list, which is strictly worse than the rename. Report a
    missed join by name as catalogue drift: honest, and the fastest possible signal that two
    catalogues have diverged. GENERAL FORM: when you join on a value rather than a surrogate
    key, the miss case is not "empty", it is "these two sources no longer agree".
  - **A DIAGNOSTIC STATE WITH NO CALLER IN THE DECISION PATH IS A DEAD END — and a comment
    naming it is not a caller (2026-08-04, "vLLM doesn't seem to start"):**
    `vllm_lifecycle.start_outcome()` was built two days earlier precisely to separate a vLLM
    that is still loading from one that has already died, after a field report of ten retries
    against a dead server. It had exactly one caller: the status payload. `ensure_running`,
    the one place whose decision depends on the difference, carried the comment *"its own
    start_outcome() is the tri-state that tells ready from still-loading from already-dead;
    do not guess here"* — and then guessed on the next line, taking `Popen` succeeding as the
    start succeeding. A child that died during engine init reported `started: True`, the
    coordinator's gate accepted it, and the sweep burned its whole retry budget. RULE: after
    building a state that exists to expose a failure, grep for its consumers before calling
    the fix shipped; if the only reader is a status endpoint, the failure is still invisible
    where it matters. Same family as the machine-readable 409 whose `acknowledgeable` flag no
    caller ever sent. COROLLARY on the fix: a watch window must be bounded by what the failure
    ACTUALLY costs — the startup deaths that matter (port collision, CUDA init, gated repo,
    import error) all land within a second or two, so six seconds separates them from a
    genuine tens-of-seconds model load without making a button wait for one.
  - **WHEN A NARROW HELPER CORRECTLY RETURNS None, LOOK AT WHAT THE CALLER PUTS IN ITS PLACE
    (2026-08-04, the same report):** `outage_reason()` answers backend REACHABILITY and
    returns None whenever a backend can be reached — which is right, and which is the COMMON
    case for the failures that actually reach a sweep loop: a reachable Ollama with no model
    pulled, a 500 from a context overflow, a vLLM whose port opened before its engine died.
    All four loops then fell through to the words "local model hiccup", naming the symptom
    while discarding the exception they were holding one variable away. So the enrichment
    layer built to explain outages became the hiding place for the outages it could not
    explain — the K2 shape again, one level up: not a crashing resolver, a *correct* one whose
    silence was filled with a worse answer. The langdetect loop was the purest case, already
    holding the aborting event's own reason and printing over it. RULE: a fallback branch is
    part of the helper's contract; when the caller has real evidence, the evidence wins, and
    the generic phrase is what you use when there is genuinely nothing else.
  - **REDIRECTING WHERE NEW DATA LANDS MAKES EXISTING DATA INVISIBLE UNLESS THE PROBE LEARNS
    BOTH LOCATIONS (2026-08-04, a regression from that same day's model-store move):** the
    recorded env-var lesson said "count the call sites that DERIVE the same path", and all
    three were made to agree. The half not thought through is that the OLD path had several GB
    of real data behind it: pointing `HF_HOME` at the app folder made `model_cache_state()`
    read one directory and answer "not downloaded" about the other, so the activation guard
    refused a start for a model that was on the disk and told the operator they had never
    downloaded it. The fix is not to silently prefer whichever location has content (a mixed
    state that flips the moment one model lands in the new one) but to probe BOTH and say
    WHICH answered — a legacy-only copy is still refused, because the server is spawned
    pointed at the new path and would re-fetch the same weights over the clear internet, but
    for the true reason and with the way out. RULE: any change to where an app looks for data
    it did not create must enumerate what is already at the old location, and the honest
    output of that enumeration is a NAMED difference, never a silent preference. Corollary on
    not over-building: an HF cache symlinks into its own `blobs/`, so a copy that is not
    symlink-aware doubles the size or breaks the links — naming the folder is honest, and a
    move this app has not built and tested would not be.
  - **⚠ THIS SANDBOX HAS A BROWSER AND PYTHON 3.13 — the standing "browser-unverified per
    fork-3/Q6a" caveat is a HABIT, not a limit (2026-08-04, the GUI-visualization build):**
    Chromium ships at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` with
    `PLAYWRIGHT_BROWSERS_PATH` already set, and `/usr/bin/python3.13` exists even though the
    default `python3` is 3.11. So a frontend slice CAN be driven and screenshotted in-session:
    `python3.13 -m venv .venv` → `pip install -e ".[analysis]" pytest playwright` (with
    `TMPDIR` inside the repo, per the recorded pip lesson) → seed a SYNTHETIC corpus through
    the real `index_article` → `uvicorn` on a loopback port with `OO_DATA_DIR` +
    `OO_DB_PLAINTEXT=1` + `OO_NO_SCHEDULER=1` → `pw.chromium.launch(executable_path=…)`. The
    full suite runs too (no `--timeout` flag: pytest-timeout is absent). FOUR DEFECTS in this
    slice were invisible to source reading and obvious in a screenshot: a flex container
    DISCARDS the whitespace between its items (so `${label} <span>n=…</span>` rendered
    "series 1n=40" — use `gap`), separate series' bars drawn at the same x read as a STACKED
    total nobody computed, a clamp meant to stop an edge group being clipped instead collapsed
    two members onto one pixel and hid a real measurement, and Arabic showed English method
    text under translated caveats. Also: apply greyscale as a BROWSER filter
    (`documentElement.style.filter = 'grayscale(1)'`) so what is judged is rendered pixels, and
    hand the images to adversarial subagents — three critics reading PNGs found things numbers
    could not, including one that correctly REFUSED to certify the gap-rendering path because
    the test data contained no gaps ("an untested code path, not a pass").
  - **THE i18n DOM WALKER MATCHES A TEXT NODE EXACTLY, so a label and its sentence must be
    SEPARATE ELEMENTS — and a sentence the server COMPOSES can never be translated at all
    (2026-08-04, the same slice, caught only in Arabic):** `figMeta` emitted
    `` `${t("Method")}: ${env.method}` `` as one text node, so the node was
    "Method: Articles grouped by…", which is not a key, and eleven locales showed English
    honesty text under correctly-translated Arabic caveats. Two elements, two exact matches.
    The sibling half is worse: `source_concentration` appended a basis-dependent clause to its
    method, making the string DIFFERENT on every corpus, so no key could ever match — the
    varying part must travel as a FIELD the frontend composes from its own keyed template (the
    `OOI18N.tf` discipline). THIRD, and the reason it survived one round of fixing: a Library
    view renders ONCE (`_libViewLoaded` is a `Set`), and an already-INTERPOLATED `tf()` string
    is no longer a key, so it stays frozen in whatever locale first rendered it — the recorded
    `home-lead-title-frozen-locale` bug class, which the `oo:langchange` handler exists to fix
    and which every new render-once surface must register with. THE DURABLE FIX IS A GUARD, not
    memory: a test drives every figure and fails if any `method`/`caveat` is absent from any of
    the twelve locale files, naming the figure, the field and the locale. Mutation-checked.
  - **COLOUR-ONLY SERIES IDENTITY IS REFUTABLE BY ARITHMETIC, AND THE REPLACEMENT CHANNELS MUST
    DIFFER BY FAMILY (2026-08-04):** `ooChart` distinguished series by a 4-colour cycle and
    nothing else. The decisive number is not the background contrast (though three of those
    four were below the WCAG 1.4.11 3:1 non-text bar on `--panel2`, the background the canvas
    actually paints) — it is that the worst MUTUAL contrast between two theme-derived series
    colours is **1.00:1, luminance-identical**, because pulling each hue toward `--fg` to clear
    the background bar necessarily converges them. That is a proof, not a preference: colour
    cannot carry identity, so dash and marker are load-bearing. TWO WAYS THE REPLACEMENT
    CHANNELS COLLIDE ANYWAY, both shipped for one iteration and both caught by a critic reading
    pixels: distinct dash NUMBERS are not distinct dash PATTERNS (`[2,3]` vs `[1,3]` both read
    as "the dotted one"; `[3,7]` is another pattern's rhythm at half the frequency — scaling
    does not make a new one, so compare the ordered sequence of mark-length CLASSES), and a
    marker must not be another marker ROTATED (a diamond IS a square at 45°, and at ~6px they
    are a coin flip). Also: the legend swatch must show the pattern it teaches — a marker
    centred on a 30px swatch covered exactly the stretch where a dash-dot cycle distinguishes
    itself, so that key rendered as a solid line.
  - **A FIX FOR A CLIPPED GROUP MEMBER MUST CLAMP THE GROUP, NOT EACH MEMBER (2026-08-04):**
    grouped bars at the first/last time slot fell half outside the plot, so each series' own
    left edge was clamped into the plot area. At the first slot that put series 0 and series 1
    on the IDENTICAL pixel, the later drew over the earlier, and a real measurement became
    invisible and un-hatched — the very failure the clamp was added to prevent, reached by
    another route. Clamp the group's left edge once and offset members within it; then no two
    sub-slots can coincide by construction. GENERAL FORM: when a fix bounds a POSITION, ask
    what happens when two things are bounded to the same bound.
  - **REUSING A MAINTAINED COUNTER MEANS INHERITING ITS DOCUMENTED FALLBACK (2026-08-04):**
    a new figure filtered `Source.article_count > 0`. That column is NULLABLE and is NULL on any
    corpus the bounded background reconcile has never touched, so the figure returned n=0
    against 180 real articles across 10 sources — not a missing caveat but a false statement,
    "no source holds any article". The fallback already existed at `src/api/source_io.py:163-177`
    (counter when set, live `COUNT` otherwise) with its three-state basis vocabulary
    `live`/`exact`/`estimated`, and was simply not reached for. COROLLARY on aggregating a
    basis: ONE estimated or live member makes the WHOLE aggregate that basis — reporting
    "exact" because most members were exact is the fabricated pass this project names
    elsewhere. And a `None` that means UNDEFINED must never render as 0 when 0 is a real value
    with the opposite meaning: `gini()` returns `None` below n=2, and a Gini of 0 is perfect
    EQUALITY.
  - **TWO SURFACES CAN DISAGREE ABOUT WHAT "JUNE" MEANS, AND NEITHER IS WRONG — SO THE FIX IS
    A DISCLOSURE, NOT A COLUMN CHANGE (2026-08-04, found while scoping the chart brush):**
    `KeywordMention.observed_on` is `(published_at or created_at).date()` (`store.py:284`) —
    a coalesce, and the x-axis of every keyword trend chart — while the date filter behind
    Advanced search and `_resolve_corpus` is `Article.published_at` alone
    (`main.py:818-821`). So an article whose publish date could not be extracted is PLOTTED
    at its ingest date and EXCLUDED by a filter over that same day; live-reproduced, two
    articles on one chart day, one returned. The reflex is to coalesce the filter, and that
    is the MIRROR DEFECT: an article ingested in June with no publish date may have been
    published in 2019, so folding `created_at` into a filter labelled "published between X
    and Y" fabricates an INCLUSION exactly as the present behaviour fabricates an ABSENCE.
    Both directions are dishonest and the conservative column is the defensible one, which
    means the repair is (a) disclose the count dropped for want of a publish date — derivable
    with no new storage — and (b) make the two surfaces agree about which window is on
    screen. GENERAL FORM: when two surfaces compute the same-sounding quantity by different
    rules, check whether EITHER rule is defensible before changing one to match the other;
    if both are, the disagreement is a labelling and disclosure problem, and "make them the
    same" silently picks a side. COROLLARY that decided a design: anything that turns a chart
    selection into a corpus must carry the ids of the buckets the chart actually drew rather
    than re-resolving the range through a filter — then it inherits the chart's own
    definition of time by construction and the disagreement cannot reach it. Same pass: a
    trend bar is a MENTION total, not an article count (`trend()` sums
    `KeywordMention.count`), so such a readout owes both numbers.
  - **A PROBE'S DATA DISTRIBUTION IS PART OF THE LOOKALIKE — and "fold the predicate into the
    GROUP BY" only works when the predicate column is IN the index (2026-08-04, scoping the
    duplicate-group figure):** the recorded lesson says a hand-written SQL probe differs from
    the shipped query in table stats, ANALYZE state and which other indexes exist. A fourth
    axis: the ROW DISTRIBUTION. Measuring a two-step design (a covering aggregate to find
    canonical-URL collisions, then a bounded `IN (…)` to apply the quarantine filter to just
    the colliders) produced a **bare `SCAN articles`** — which reads as a damning result until
    you look at the fixture: 32 collision groups out of 40, so the planner correctly scanned
    rather than index-seek 112 of 120 rows. At a realistic collision rate it may plan the
    opposite way. So a plan measured over a fixture whose DENSITY is unrepresentative is
    evidence about the fixture, not about production — state which questions the probe
    settles and which it does not, rather than reporting every line of its output with equal
    confidence. SECOND HALF, a genuine limit on a recorded trick: the 2026-08-04 per-language
    fix folded a predicate into the GROUP BY so the planner had no escape, and that does NOT
    transfer here — it changed nothing and added a temp B-tree, because the problem was never
    index CHOICE but that `quarantined` is absent from every candidate index, so any reference
    to it costs a row fetch (a decrypt per row under SQLCipher). When a predicate column is
    not in the index, the only real options are a composite covering index (a migration) or
    not referencing the column in that query at all; grouping on it is a non-fix that looks
    like one.
  - **A GUESS ABOUT *WHERE* THE REASON IS WILL BE WRONG TWICE BEFORE IT IS RIGHT — SEARCH
    INSTEAD (2026-08-04, the vLLM server log):** this repo fixed the same instrument twice
    on reasoning rather than evidence. First it kept the log's TAIL; then it kept both
    ends, on the correct observation that "EngineCore is a CHILD process, so a startup
    failure prints its traceback FIRST". In the operator's real 46,455-byte log the cause
    — `CUDA error: out of memory` — sat at byte 26,914: past the 8,000-byte head, before
    the 8,000-byte tail. The head was vLLM's banner and a config dump; the tail was the
    sentence "See root cause above." Both fixes reasoned about WHERE a reason lives in a
    file whose shape belongs to someone else's program. The fix is to SEARCH for known
    fatal signatures, MOST SPECIFIC FIRST — the wrapper that says "see the root cause
    above" matches too, and matching it first hands back the sentence whose entire content
    is that the answer is elsewhere — and to fall back to the head only when nothing
    matches, since a fabricated diagnosis is worse than an honest excerpt.
  - **A HEADROOM EXPRESSED AS A FRACTION OF A RESOURCE GIVES THE LEAST TO WHOEVER HAS THE
    LEAST (2026-08-04, the vLLM CUDA OOM):** `compute_server_args` derived
    `gpu_memory_utilization` from weights + KV, adding the fixed weight reserve back at
    full value while discounting only the remainder. The algebra came out as
    `0.85 + 0.75/vram`, i.e. utilization RISING as the card shrank — 0.95 on a 6 GiB card,
    0.86 on an 80 GiB one, and 0.94 on the 8 GiB card the app is designed around, leaving
    0.48 GiB free. CUDA-graph capture then died at 86% of 51 graphs. THE RULE: a reserve
    for something whose cost does NOT scale with the resource (a graph pool scales with
    the model and the graph count; fragmentation scales with neither) must be ABSOLUTE,
    with the fraction as a floor above it, and capped at the upstream default — being
    bolder than upstream on the smallest hardware is the wrong direction to be bold in.
    TWO COROLLARIES. Pin it as a MONOTONICITY, strictly, and additionally assert the
    series actually VARIES: the recorded lesson that a clamped value satisfies `>=` with a
    constant applies here too. And a first mutation attempt PASSED — because the mutant I
    wrote was not the old formula, only something else that happened to stay monotone; a
    mutation test is only evidence when the mutant genuinely reproduces the defect, so
    derive it from the real prior code rather than from memory of its shape.
  - **DO NOT REGRESS A NUMBER THE MEASUREMENT SAYS WORKS, EVEN TOWARD SAFETY (same fix):**
    the obvious tidy-up was to re-derive `max_model_len` from the new, lower utilization so
    both values came from one budget. That would have dropped it 5120 → 2048 on the field
    card — and the field run had served 5120 with 24,960 tokens of KV (4.88x concurrency),
    so that value was demonstrably not what failed. Internal consistency is a reason to
    rewrite a METHOD STRING, never a reason to tighten a figure the evidence exonerates;
    conservatism applied where the measurement already answered is just a worse answer with
    a better motive.
  - **WHEN TWO FUNCTIONS ANSWER ONE QUESTION FROM DIFFERENT SOURCES, THE MISMATCH SHIPS AS
    A CONFIDENT WRONG SENTENCE (2026-08-04, "Model 'mistralai/Ministral-3-3B-Instruct-2512'
    is not installed. Run: ollama pull mistralai/Ministral-3-3B-Instruct-2512"):** that is
    an HF repo id handed to OLLAMA, on a machine where the Ollama model was installed all
    along — and Ollama's message was perfectly correct about the question it was asked.
    `active_model()` resolved the backend from the STORED `llm_backend` setting; the sweeps
    called `get_client_with_name()` with no argument, and `resolve_backend()` read only
    `OO_LLM_BACKEND`. With the setting on "vllm" and its server not running, the MODEL came
    from one answer and the CLIENT from the other. THE FIX IS NOT TO BRIDGE THE CALL SITES
    — that is an enumeration, and the recorded backstop lesson says enumerations are wrong.
    Read the setting in the ONE place the decision is made, so the operator's choice is
    authoritative by construction; and where a caller ALREADY knows the answer (the
    coordinator knows which backend `ensure_running` actually brought up), let it pass that
    in rather than re-resolving, because the two calls can also disagree across a race or a
    fallback. GENERAL FORM: a value that is only meaningful beside another value (a model
    id beside its backend, a unit beside its number) must travel WITH it, never be looked
    up twice.
  - **A CAPABILITY ON A SURFACE WITH NO CALLERS IS A GUARD THAT PASSES WHILE PROVING
    NOTHING — and three more ways a locally-correct UI change claims something false
    (2026-08-04, the chart brush):** four defects from one slice, none visible in a diff.
    (a) **THE SHARPEST.** I wired brush-to-select onto `#corpus-chart` because it is a
    single-keyword article-time chart and qualified on every stated criterion — but
    `corpusTab` has **no callers** (the retired `#corpus-win` modal), so the capability was
    unreachable, and my own guard asserting both wired charts passed while half of it
    described something no reader can do. Before wiring a feature onto a surface, grep for
    the surface's CALLERS, not just its correctness; and a guard that enumerates surfaces
    must be checked against reachability or it certifies dead code. (b) **A CONTROL'S
    PREVIEW AND ITS ACTION MUST SHARE ONE FORMATTER.** The live brush readout used `fmtT`,
    which picks granularity from the whole axis span, so it rendered "2026-05" while the
    brush selected `2026-05-10` — the reader was shown a month and handed a span starting
    mid-month, with no way to tell before releasing. Two formatters for one quantity drift
    by construction; hoist one and both agree. (c) **A COLOUR TOKEN CARRIES MEANING, so
    reusing it for the opposite meaning gives one signal two readings** — the selection band
    was painted with `--fig-gap`, the ABSENCE token, so a selection and a hole were the same
    grey and a reader who had learned "grey means nothing recorded here" would read a
    selection as missing data. Selection is an ACTIVE state and belongs to the accent.
    (d) **A VISUAL CHECK CAPTURED AT THE WRONG MOMENT TESTS NOTHING** — greyscale was applied
    after the click navigated away, so "the band is visible without colour" had never been
    tested at all despite a greyscale screenshot existing. Captured mid-drag it does hold,
    but through the explicit EDGES; the translucent fill is faint once desaturated, which
    means the edges were load-bearing rather than decorative. Mid-interaction states need
    mid-interaction capture, and an existing screenshot is not evidence that the thing you
    care about was in it.
  - **APPLYING HALF A RECORDED LESSON IS HOW A DEFECT SURVIVES REVIEW — and a fixture that
    differs from production in the one dimension the lesson is about turns the guard into
    an accomplice (2026-08-04, the brush bucket snap):** the note I had just written said a
    chart selection must inherit the chart's OWN definition of time, and I got the column
    right (resolve on `observed_on`, never through the `published_at` filter) and the
    GRANULARITY wrong (resolve by day against a chart drawn in weeks). A week bar is drawn
    at its Monday, so a day-precise span cuts one in half or misses it while it still looks
    inside the band: four visible bars summing to 65 mentions were reported as 50, because a
    bar drawn at 2026-06-22 whose every mention fell on 06-28 sat inside a span ending 06-26.
    **THE PROCESS FAILURE IS WORTH MORE THAN THE FIX.** An adversarial critic read the
    screenshot, estimated ~65 against the reported 50 and suspected an off-by-one; I
    re-measured, got 50, and told the user its arithmetic was refuted — having measured with
    `bucket=day` while the shipped chart uses `bucket=week`. The critic was reading the bars
    actually on screen and was closer to right than my measurement. So: when a
    pixel-reading critic's arithmetic disagrees with your query, the first suspect is the
    PARAMETERS of your query, not their eyes. And SIXTEEN tests over the resolver passed,
    including one that pins exactly this property — every fixture used the default `day`
    bucket, so the invariant was held and the defect was invisible. This is the recorded "a
    probe's data distribution is part of the lookalike" lesson one level up: it is not only
    row density that makes a fixture a lookalike, it is any parameter the production caller
    sets and the fixture leaves at its default. Parametrise the guard over every value the
    shipped call sites actually pass (`day`/`week`/`month` here), and check what the call
    site passes rather than what the function defaults to. The fix's own shape generalises:
    a selection over a bucketed axis can only honestly return whole buckets, the bucket
    travels with the request, the response reports the EFFECTIVE span rather than the raw
    input, and the client preview snaps through the same widening — a preview that shows the
    raw gesture while the result reports a widened one is two answers to one action, the
    same divergence the shared day formatter had already fixed once in this very component.
  - **A MESSAGE CAN BE ENTIRELY TRUE AND STILL NOT BE THE ANSWER — and the third read of
    the same tri-state is where that finally showed (2026-08-04, "explicit override
    (vllm), but its server is NOT running — Ollama IS reachable; clear the override to
    use it"):** every clause was accurate. The engine had nonetheless been STARTED and had
    EXITED about a minute later — a vLLM reaches CUDA-graph capture around t+67s, far past
    any click-time confirm window — and `start_outcome()` had recorded exactly that while
    `outage_reason()` reported REACHABILITY instead. This is the "local model hiccup"
    defect one level deeper: not a missing fact, a correct-but-wrong-question fact
    published where a cause belonged. `start_outcome()` has now needed reading in THREE
    places (the start itself, the plan on every poll, and the sweep's retry line); after
    building a state that exposes a failure, the consumers are not one call site but every
    surface an operator can see the failure ON. THE TWIN IS LOAD-BEARING: only `exited`
    may be called a death — a still-loading engine keeps the generic wording, because the
    backoff exists to wait a model load out and naming that a failure is the
    fabricated-failure mirror of the fabricated-success being fixed. SECOND HALF, a
    separate class: the advice had gone stale. "clear the override to use it" was the only
    thing on offer when nothing in the app could start a backend; once `activation` could,
    it was telling operators to abandon the choice they had deliberately made. When a
    capability lands, grep the strings that were written around its ABSENCE — and pin the
    fix by ORDER, not presence, since both options should still be offered.
  - **AN ADVICE STRING IS A CALLER TOO — "start it from Settings" is a dead end when the
    app is the only thing that can press the button (2026-08-04, the fourth read of the
    same tri-state):** the recorded lesson says a diagnostic state with no caller in the
    decision path is a dead end, and names a status endpoint as the tell. This is the same
    defect wearing a sentence: `ensure_running()` had exactly two callers and BOTH are a
    human clicking — the coordinator's run endpoint and Settings → AI's start button — so
    on a machine whose operator had chosen vLLM and left the app running, four sweeps spent
    their whole retry budget while the message correctly, and forever, told them to go and
    do the one thing the app was in a position to do. The earlier fix gave the coordinator's
    ENTRY an activation call; nothing gave the RECOVERY path one, and a run that is already
    going is exactly where a backend goes down. TWO RULES. (a) After building an action,
    grep for the paths that DETECT the condition it answers, not just the ones that start
    the work — an entry-point fix does not reach a loop that has already entered. (b) The
    recovery must return WORDS and never a verdict (a reload, a restart and a busy server
    answer a probe identically), so the budget and control flow stay exactly where they
    were; and the words must SUPERSEDE the resolver's advice when the app has acted, because
    "start it yourself" was written for a world where nothing could — the stale-advice
    lesson, one surface over. TWO DEFECTS THE BUILD ITSELF SURFACED, both worth more than
    the feature: `ensure_running` read `start()`'s word **"already running"** as `ready`,
    but that word means `process_alive()` and the branch is only reached AFTER the health
    probe said the backend does not answer — so a loading engine reported as SERVING, and
    the recovery path would have hit it on its very first retry (live-reproduced; a word
    about a process is not a probe of the port). And `_recovery_last_at = 0.0` made the
    FIRST attempt of every process read as "attempted moments ago", because
    `time.monotonic()`'s reference point is undefined and small on a fresh boot — a
    sentinel that is also a legal value, the `.get(key, 0)` family again, caught by an
    EXISTING ride-along test rather than by any of the eight I wrote for the change.
    THIRD, and the one that would have escaped this box entirely: **adding an ACTION to
    a production failure path makes it a side effect of every test that drives that
    path.** Neither backend is installed in this sandbox, so the recovery is inert here
    and the suite stayed green — proving nothing. A throwaway pytest plugin that faked
    "both installed" and recorded every `start()` call found one real
    `ollama_lifecycle.start()`, i.e. a suite run on any developer machine that HAS
    Ollama would have left a daemon behind. The fix is not to patch the tests that
    happen to reach it (the enumeration again) but a real operator opt-out
    (`OO_LLM_AUTOSTART=0`) that `conftest` sets session-wide, exactly as it already does
    for `OO_NO_SCHEDULER` and `OO_AUTOSEED` — and the tests that are ABOUT the start
    turn it back on. GENERAL FORM: when a change makes a code path DO something rather
    than merely report, ask what the test suite now does on a machine unlike this one,
    and measure it with a plugin rather than reasoning about it.
  - **A METRIC KEY CAN BE A MISNOMER THAT MUST NOT BE "FIXED" BY REDEFINING IT — and a fix
    that makes two texts agree can do it by DELETING one (2026-08-04, the Library
    qualification tile):** `_count_sources_never_judged` counts `status == 'unqualified'`,
    while `log_no_evidence_attempts` writes a `no_evidence` attempt row and DELIBERATELY
    leaves status alone (its whole reason for existing, the 2026-07-23 livelock fix) — so an
    ENABLED source with no feed is tried on every rotation of the queue and was counted, and
    labelled, "Never judged". The tempting repair is to make the key mean its name; that is
    wrong, because the snapshot store has INFINITE retention and redefining an existing key
    makes its own history incomparable with its future, a silent break in a time series
    layered on top of the first defect. Freeze the definition, fix the LABEL, add a new key
    for the honest count. GENERAL FORM: when a name and a measurement disagree and the
    measurement has history, the name is the part you are allowed to change. SECOND HALF, in
    the same tile: an earlier fix had cured a real staleness bug (a per-mode caveat
    contradicting the scale hint above it) by writing `note.textContent = HINTS[mode] ||
    caveat` — and `HINTS[mode]` is non-empty for all three modes, so `|| caveat` was DEAD
    CODE and every `{scales: true}` caller silently lost its caveat, two of them
    mode-INDEPENDENT statements with nothing to do with the toggle. Two statements of
    different KINDS need two slots; through one slot the volatile one always wins. Found by
    opening the modal and reading its last line, which was the hint where the caveat should
    have been. COROLLARY on recurrence: the frozen-locale class (an interpolated `tf()`
    string is not a key the DOM walker can match, and a Library view renders once) recurred
    the moment a new interpolated string was added to a render-once surface — even though
    `oo:langchange` already registered a SIBLING view for exactly this reason with the reason
    written above it. A recorded lesson does not propagate itself to the next surface; only a
    guard does.
  - **CLAMPING log(0) FABRICATES AN AXIS, AND REFUSING A MODE MEANS NOT OFFERING IT
    (2026-08-04, ooChart's logY):** `vt(v) = log10(Math.max(v, 1e-9))` reads as defensive
    coding, and the guard pinning it even said "never crash on a zero/negative". Measured on
    four integer series in 0..6 with zeros at the start: the axis spanned log-space
    **−9..0.78**, so the real differences occupied about **5% of the plot**, `honestTicks`
    labelled log-space ticks back through `vtInv` and printed **`0.003` and TWO `0`
    gridlines** — none of them values a count can take — and every true zero was drawn as a
    plotted point on the floor with a line through it. Invisible for months because `logY`
    shipped for the markets boards, where an index value is never 0; the caller whose values
    legitimately start at zero is what exposes it. Refuse the mode when the data cannot
    support it, fall back to the axis the data deserves (zero-based, integer ticks for
    counts), and SAY so. THEN THE FOLLOW-ON, which is the part that generalises: leaving the
    control enabled put two statements on screen at once — a hint claiming "equal ratios are
    equal distances" above a chart that had drawn linear and said so underneath. The
    renderer-level refusal is the load-bearing guard because it cannot be bypassed; disabling
    the control is what makes the contradiction unreachable. And TEST THE OTHER DIRECTION in
    a browser: a positive-only series must still get a working log mode, or a fabricated-axis
    fix has quietly removed a real capability.
  - **A SENTENCE WITH AN INTERPOLATED COUNT CANNOT CONJUGATE, AND AN LTR-SHAPED VALUE NEEDS
    A BIDI ISOLATE (2026-08-04, the same tile; both caught by adversarial critics reading
    screenshots, neither visible to any mechanical check):** the note read "**1 have** never
    been attempted", and the French carried the identical error — which is the tell that it
    is the TEMPLATE, not the translation. Per-form keys are not the answer either: Russian
    has three plural forms and Arabic six, and this app has no CLDR plural rules. Phrase a
    value-bearing string as **label:value** and nothing conjugates, so every locale is
    correct by construction (the participles in the fr/es/pt renderings agree with the
    CATEGORY, not the number, which is why they survive). No mechanical check could see the
    original: every locale was present, non-empty, in the right script, and a plausible
    translation. SECOND: interpolating an ISO timestamp into a translated sentence renders in
    visual order **`.07T18:00:00-07-2026`** in Arabic — the year at the wrong end, a MISREAD
    date rather than an ugly one (measured by reading each character's rendered x position in
    the real page, not assumed). `U+2068` FIRST STRONG ISOLATE … `U+2069` POP DIRECTIONAL
    ISOLATE around the value fixes it; they are plain characters so they survive `esc()`, and
    they are inert in LTR locales. It is PUNCTUATION-JOINED runs that need it — dates,
    versions, IDs, URLs, ranges — never a bare number, so a lone count does not get one.
  - **BRACE-MATCHING A LITERAL IS NOT ENOUGH — a `}` INSIDE A STRING TRUNCATES IT
    (2026-08-04, the fifth slicer shape):** the slicing ratchet rejected three hand-rolled
    slices in a new test file (the class it exists to stop, written by someone who had read
    it), and writing the shared shape it asked for immediately exposed that the obvious
    implementation is wrong: `const L = {a: "x}y", …}` truncates at the brace inside the
    string, so the slice ends after one key and every assertion over the fragment passes for
    free — the same failure the module is about, one level down. `object_literal` therefore
    landed with a string-, template-literal- and comment-aware scanner that `array_literal`
    now shares (template literals additionally nest through `${…}`; a JS regex literal
    containing an unbalanced delimiter is an honest, stated limit that raises rather than
    truncating). The test that proves it is the one that failed against my own first
    implementation. And prefer being stopped by a ratchet over lowering its budget: 233
    unchanged.
  - **A PROBE WHOSE WINDOW IS SHORTER THAN THE FAILURE CANNOT TELL A CRASH LOOP FROM
    PROGRESS — and the log that would say so is overwritten by the next attempt
    (2026-08-05, the fifth round of "vLLM won't start"):** three instruments each held
    part of the answer and none held it long enough. `start_outcome()` is process-local
    and keeps only the LAST spawn, so a restart erases every death; `server.log` is
    opened `"wb"` per start, so each attempt DESTROYS the evidence of the one before
    it — the file whose entire job is explaining a failure is deleted by the next
    failure; and the recovery re-attempts every 30 s while a load takes 60–90 s, so a
    server dying at t+40 is respawned at t+60 and reports "starting" forever. The
    operator read steady progress off a crash loop, and every word of it was
    individually true. THE FIX IS A JOURNAL, and the reason to reach for one is that
    the artifact which finally cracked this chain was `install_attempts.jsonl` — a
    bounded append-only record already in the same module, whose value was proven the
    round before. GENERAL FORM: when a diagnosis needs *what happened over time* rather
    than *what is true now*, no amount of improving the point-in-time probe will do it;
    and any per-attempt log opened for truncation is a point-in-time probe wearing a
    file's clothes. TWO DESIGN POINTS worth reusing: recording a TRANSITION inside a
    read-only probe (`start_outcome`) is a journal rather than a side effect — it is the
    only place an exit is reliably observed — provided it is idempotent per pid, so a
    status endpoint polled a hundred times writes one line. And the verdict threshold
    is TWO exits, not one: an operator who has just FIXED the cause must get a fair
    start rather than a verdict inherited from the attempt they repaired, which is the
    fabricated-failure twin of the fabricated-progress being fixed.
  - **"EVERYTHING LIVES IN THE APP FOLDER" IS A CLAIM ABOUT EVERY PROCESS YOU SPAWN, AND
    ONE REDIRECTED CACHE DOES NOT MAKE IT TRUE (2026-08-05, from an operator's own
    provisioning scripts):** the model-store move pointed `HF_HOME` at the app's data
    folder and every test agreed the WEIGHTS landed there — while torch's Inductor cache,
    Triton's kernel cache, the CUDA JIT cache and vLLM's own cache/config roots all still
    wrote into `$HOME` on first run, GB-capable and invisible. The scripts said it in one
    line: *"Without these, torch / Triton / Inductor / NVIDIA / uv all write into $HOME and
    your self-contained app folder is a fiction."* GENERAL FORM: when you relocate one
    thing a subprocess writes, enumerate the OTHERS by asking what the whole dependency
    stack caches, not what your feature downloads. THREE THINGS THE FIX TURNED ON: the
    redirect is SERVE-only, because `XDG_CACHE_HOME` also governs pip's wheel cache and
    moving that would make the next reinstall re-download several GB it already has —
    which is exactly why the operator's reinstall took seconds, so the split has a
    measurement behind it, and it needs its own twin test or a later tidy-up will
    "simplify" it into the install path. An operator-set value must win, since someone who
    put Triton's cache on a big disk did that deliberately. And **the guard belongs on the
    RESOLVER, not only on the operation** — `data_dir()` CREATES the directory it returns,
    so guarding each `target.mkdir` while calling `_cache_root()` unguarded put the failure
    one call *earlier* than the guard, and on a read-only volume the whole start died for
    want of a cache. An existing test about something else entirely (losing the log must
    never block a start) is what caught it, which is the argument for running the
    neighbouring suites rather than only the ones you wrote.
  - **A BUDGET DERIVED FROM A RESOURCE'S *TOTAL* DESCRIBES A MACHINE THAT MAY NOT EXIST —
    and the operator's "it was never saturated" is what identified the mechanism
    (2026-08-05, five vLLM starts exiting 1 in ten minutes):** `detect_gpu()` read
    `memory.total`, so `compute_server_args` sized vLLM's budget for the whole 8 GB card
    while Ollama sat on several of those gigabytes serving the very sweeps that were
    waiting for vLLM. Nothing sequenced them: `ollama_lifecycle` deliberately has no
    `stop()` (the daemon is usually a system service the app does not own), and that
    correct constraint had silently become "no arbitration at all". THE DETAIL THAT
    CRACKED IT was the one that looked like a refutation — the operator noted ~900 MB
    still free at the peak, which rules out a plain OOM and points instead at vLLM's own
    startup check: `gpu_memory_utilization` is a fraction of the TOTAL, so a request for
    0.81 of a card with 3.6 GB free is refused *before* anything fills, and that refusal
    reaches the caller as exit code 1. When a reported detail seems to weaken your
    hypothesis, ask which mechanism it is *consistent* with rather than discarding it.
    FOUR RULES FROM THE FIX. (a) Size from what is FREE, but keep the fraction in the
    consumer's own unit (`(free − reserve) / total`) — mixing the two is how a budget
    that looks conservative asks for memory nobody has. (b) A MISSING reading is not a
    reading of zero: `vram_free_mb=None` must leave the old total-derived answer
    byte-identical, or every machine whose driver omits the field gets refused. (c) The
    floor that protects an *unmeasured* guess must NOT be applied to a *measured* one —
    flooring a real 0.26 back up to 0.50 reinstates the exact request being fixed; let
    the small number become a named refusal upstream instead. (d) The release goes in
    `start()`, not in the activation orchestrator, because `POST /api/llm/vllm/start`
    reaches `start()` directly — the standing "gate EVERY entry point" lesson, and the
    reason the fix is one chokepoint rather than two call sites. COROLLARY on shape: with
    `stop()` off the table, the release had to be a request the daemon already exposes
    (`keep_alive: 0` drops residency, Ollama reloads on its next call), so the worst case
    is one model-load latency and nothing the operator started is ever killed. And an
    unload is ASYNCHRONOUS — poll until the free reading stops improving rather than
    measuring immediately or sleeping a fixed worst case.
  - **A LEAD MEASURED IN LINES AGAINST A BUDGET MEASURED IN CHARACTERS SPENDS THE
    WHOLE BUDGET ON CONTEXT (2026-08-06, the sixth round of "vLLM won't start"):**
    the start journal was built precisely because `server.log` is truncated on the
    next start, and it recorded ten consecutive failures without once recording a
    reason. `failure_excerpt` searched correctly, anchored correctly, and then built
    its window as "six lead lines, then everything after, truncated to `limit`" —
    but vLLM prefixes every line with `(EngineCore pid=NNNNNN) INFO MM-DD HH:MM:SS
    [file.py:NNN]`, so six lead lines cost **662 characters against the 400 the
    journal passed**. Live-reproduced: at 400 the excerpt provably never reaches the
    matched line, so every persisted record held the six lines BEFORE the error and
    never the error. The instrument built to survive the log being overwritten could
    only preserve the part that was not evidence — the K2 shape (a degrade becoming
    the hiding place for the bug it was built to survive) at the level of a window's
    arithmetic. RULE: when a bounded window must contain a specific thing, give that
    thing the budget FIRST and buy context with the remainder; and when two bounds
    are expressed in different units, convert one before trusting the pair. THE
    DISCRIMINATING TEST is the tight budget, not the generous one: raising the limit
    400→1200 also "fixes" today's log, and would break again on a longer prefix, a
    deeper stack or a smaller limit — so assert that a 200-character budget still
    reaches the failure and drops the context instead. TWO SIBLINGS from the same
    pass. **An instrument that lives inside the thing it diagnoses is destroyed by
    the first fix anyone tries**: the journal sat in `venv_dir()`, and "reinstall
    vLLM" — which deletes the venv — is the first thing an operator does when a
    server will not start, so the record was erased by the response the failure
    provokes (moved to `data_dir()`, legacy file migrated once). And **a bounded
    excerpt cannot hold a traceback anyway**, so a FAILED start now keeps its whole
    log under a swept, capped `vllm_failed_starts/`, with the newest carried IN the
    diagnostics bundle — five rounds of this were each diagnosed from an export and
    every one ended in another request for a file the export did not contain.
  - **A RESILIENCE SETTING DOES NOT SURVIVE A TOOL SWITCH — and the tool may be
    naming its own fix in a message nobody reads (2026-08-06, the aborted vLLM
    installs):** `_PIP_NET_FLAGS` raises pip's timeout to 60 s because 5–10 GB of
    wheels are exposed to a dropped link for a long time. The big install then moved
    to **uv**, which reads none of pip's flags — it takes `UV_HTTP_TIMEOUT` from the
    environment, defaults to **30 s**, and nothing set it. Two field installs aborted
    after 22 and 76 minutes, one on a 187 MiB wheel and one on a 43 MiB one, and the
    install journal had captured uv saying *"Failed to download distribution due to
    network timeout. Try increasing UV_HTTP_TIMEOUT (current value: 30s)"* — verbatim,
    both times. The operator's report was "aborted for unknown reasons", so the
    second defect is that a captured cause which never reaches a surface is not a
    captured cause. This is the recorded "a fix in the ledger does not propagate
    itself to a newer sibling module" lesson with a twist worth naming separately:
    the sibling here is not a new module but a REPLACEMENT for the hardened one, and
    a replacement inherits the requirement, not the implementation. When swapping a
    tool, enumerate what the old one was configured with and find each setting's
    equivalent — an unset knob is invisible in a diff that only shows the swap.
  - **A GUARDED CALL TO A MISREMEMBERED METHOD NAME IS INDISTINGUISHABLE FROM A JOB
    WITH NOTHING TO REPORT — and the double that was written beside it asserts the bug
    (2026-08-10, the AI check's progress line):** the worker called
    `ctx.progress(done, total, detail)` behind `if hasattr(ctx, "progress")`, and
    `JobContext`'s actual API is a keyword-only `set_progress`. The guard was doing its
    job perfectly: it saw no such method and did nothing, for every step of every run,
    so a button that runs for minutes reported no progress at all — which looks exactly
    like a slow first step. It survived review because the test's own `_Ctx` double
    carried the method I had invented, so the test PASSED while asserting a class that
    does not exist. TWO RULES. (a) A `hasattr` guard around a call you wrote is
    self-fulfilling; when the attribute is part of a class YOU control, call it
    directly and let a wrong name raise. (b) Pin a hand-written double to the real class
    with `inspect.signature` — same parameter names AND kinds — because "the double
    drifted" and "the code is wrong" produce the identical green. Same family as the
    recorded resolver-stub lesson, one level up: there the double omitted a field, here
    it invented a method. **SIBLING, from the same slice: a test that drives the LIVE
    steps of a composition is a test that pollutes whatever runs next.** Asking "does
    the one check include the perception harness?" by calling `run_ai_check(steps=None)`
    ran real inference and real DB paths, and reddened `test_doctor_healthy_returns_zero`
    in a subset — a failure in a different file, about a different subsystem, with
    nothing in it pointing back. The order of a plan is a PURE fact; give it a seam
    (`default_step_names`) so it can be asserted without executing.
  - **READING "WHAT IS SERVING" AS "WHAT IS INSTALLED" — and the hazard the correct
    answer creates (2026-08-10, the vLLM half of the bench):** `GET /v1/models` reports
    the ONE model a vLLM server was started with, because that is how vLLM works; the
    bench read it as the installed set, so an operator who had downloaded four models
    was told all four were "not-installed" while the weights sat on the disk. The fix is
    to ask the question that was meant — is it DOWNLOADED — of the weights cache. THE
    PART WORTH REMEMBERING IS WHAT THAT COSTS: once several models count as available on
    a backend that serves one at a time, benching the second without restarting the
    server sends its prompts to the first and files the answers under the second's name.
    That is a fabricated measurement no reader could later detect, so it is REFUSED by
    name rather than run — a correctness fix that widens a set owes an audit of what the
    consumers assumed about that set's size. COROLLARY on where the guard looks: the
    first cut opened its own client to ask which model was serving, which let it
    disagree with the run itself and broke a test that had injected one; ask the object
    that will actually do the work, never a second connection to the same thing.
  - **A RULING IS PINNED BY GUARDS THAT DO NOT SHARE ITS VOCABULARY — grep the test
    tree for the MODULE, never for a plausible filename (2026-08-10, adding a narrowed
    `stop()` to `ollama_lifecycle`):** the no-stop ruling was enforced by
    `test_backend_launch.py` and `test_gpu_arbitration.py`, neither of which I ran,
    because I had listed candidate suites by NAME (`test_ollama_*`, `test_vllm_*`) and
    those two are named for what they test rather than for the module they test it
    through. `grep -rln ollama_lifecycle tests/` finds them instantly. The full suite
    caught it, which is the argument for running the full suite before pushing rather
    than the files you can think of. **THE HALF WORTH MORE:** both guards were RIGHT,
    and one of them had written down what to do — *"if a stop() is ever added, it must
    only ever kill a process this app itself spawned — update this test deliberately,
    never by reflex."* A guard that anticipates its own supersession is worth writing;
    it turns a red test from an obstacle into an instruction. Both were then rewritten
    from asserting an ABSENCE (`not hasattr(mod, "stop")`, which says nothing about
    behaviour) to proving the PROPERTY — patch `os.kill`, drive the real refusal,
    assert no signal reaches a daemon the app did not spawn — which is strictly
    stronger and survives the feature existing. Prefer that shape from the start: a
    ruling about what the code must NOT DO is testable as behaviour, and expressing it
    as the absence of a function guarantees a false red the day the function is
    legitimately added.
  - **THE THREE i18n GATES ARE THREE SEPARATE CI COMMANDS — running the combined form
    locally exercises a DIFFERENT computation (2026-08-10, PR #910's first red):**
    `ci.yml` runs `--min 100`, then `--max-untranslatable N`, then
    `--max-unkeyed-t-calls N`, as three invocations. I ran
    `--audit-chrome --max-untranslatable 572 --max-unkeyed-t-calls 301` in one call, it
    printed only the unkeyed line and exited 0, and I read that as both ratchets green.
    The untranslatable count was 578 against a 572 ratchet the whole time — six new
    `title=` attributes and paragraphs, which are UI strings the DOM walker can
    translate but only once they have keys. This is the recorded `cmd | tail` lesson in
    a new costume: a gate that never says anything interesting is the one to distrust,
    and the fix is the same — reproduce each CI command VERBATIM, separately, and read
    each one's own output. COROLLARY worth keeping: a ratchet is not only a floor to
    stay under, it is a floor to LOWER. Keying the nine strings took the count 578 →
    569, three BELOW the old bar, and the script prints the new floor when it can drop
    — the step's own comment says "lower it in the same PR that adds the keys". Leaving
    the slack invites the next drift to land unseen.

  - **A BUDGET FOR A LOOP WRAPPED IN BLANKET EXCEPTION ISOLATION CANNOT *BE* AN
    EXCEPTION (2026-08-09, the 69-minute `leads-quality.json`):** an all-diagnostics run
    hung at member 53/55 on a ~1M-article corpus, and the member was **not** unguarded —
    it runs inline under a 300 s `statement_deadline`, which fired exactly as designed,
    raising `StatementTimeout` from the next SQL statement. What it met was `run_all`'s
    per-producer `except Exception`, which exists so one bad producer can never blank
    Home. The guard fired; the isolation ate it; the loop moved to the next producer and
    did it again, once per producer, and the caller never learned anything was wrong.
    Neither half is wrong on its own — that is what makes the pair hard to see. RULE:
    when a loop is wrapped in blanket isolation, its budget must be **control flow the
    isolation cannot intercept** (a `break` in the loop that owns the budget), never a
    raised exception; and the budget must expire **before** any enclosing
    exception-based deadline, or the swallowed path is reached first anyway. Pin it with
    a reproducer that drives the *defeated* design (a producer raising the very
    exception the deadline raises, and the pass carrying on), so the reason for the
    `break` cannot later rot into "someone preferred it". SIBLING, same fix: report
    truncation in the PAYLOAD, not only a log line — otherwise a reader diffing two
    exports cannot tell a shorter FEED from a shorter RUN.
  - **A SIGNATURE TABLE IS AN ENUMERATION, SO GIVE IT A STRUCTURAL FALLBACK — and the
    wrapper is never the answer (2026-08-09, seventh round of "the log keeps the wrong
    part"):** `failure_excerpt` searches known fatal signatures, which is already the
    fix for two earlier wrong guesses about *where* a reason lives. It still missed this
    one, because the cause was new: the nvcc `RuntimeError` sat at byte 26,370 of 45,782
    — outside the retained head AND tail — and with no matching signature the search
    fell through to the generic `Traceback (most recent call last)` entry, whose window
    is the TOP of a stack while the reason is 115 lines below it. The durable half of
    the fix is not the new signature, it is reading the shape every Python failure
    shares: the terminal `SomeError: message` line. Take the **first non-wrapper** one —
    first because a child process prints its traceback before the parent prints one that
    merely says the answer is above, and non-wrapper because that parent line
    ("Engine core initialization failed. See root cause above.") is always present,
    always last, and always useless. Prove the structural half is live by testing it with
    the specific signature REMOVED; a rule that only works once you already knew the
    answer is not a rule.
  - **A FORENSIC READER THAT MATERIALISES ITS FILE COSTS MOST EXACTLY WHEN IT IS
    NEEDED MOST (2026-08-06, the app SIGKILLed during startup):** `promote_incomplete_runs`
    runs in the LIFESPAN STARTUP, before unlock, on every boot — and read every journal
    into a list of dicts. A journal's size is proportional to how much there was to
    diagnose, so **the worse the incident, the more likely the app died trying to tell
    you about it**; the operator saw only `Waiting for application startup.` then
    `Killed`. Measured on a 28 MB journal: **+243 MB RSS, 9× the file**. `summarise` was
    worse — it uses the beat file for a COUNT, the FINAL beat and the LAST TEN, and
    materialised all of them (a 19-hour import writes thousands, each carrying a
    per-child CPU array). GENERAL FORM: for any reader, write down what it actually
    consumes before choosing how to read; a count, a tail and a few aggregates are all
    streamable, and a whole-file read in a *boot* path is a startup cost proportional to
    the last disaster. Also check the readers that bound their output — `raw_runs` read
    every beat and THEN sliced `[-max_beats:]`, so the bound it advertised never applied
    to the peak, and `list_runs` was not even capped at 50 files like the boot pass was.
    **TWO TEST LESSONS, both from getting it wrong first.** (a) A memory guard built on
    `ru_maxrss` is VACUOUS: peak RSS is a process high-water mark that never shrinks, so
    by the time the test runs the peak is already set by earlier tests and the delta is 0
    whatever the code does — reverting the fix left it green. `tracemalloc` measures
    allocations inside the window and resets, which is the actual claim. (b) The fixture
    must grow EVERY file the path reads: padding only the beat file left the milestone
    read undetectable, and padding it with 30,000 *distinct* stage names then failed
    against correct code, because that builds a genuinely large aggregate the summary is
    supposed to report — pad with records the code does not accumulate, or the test
    measures the wrong thing in both directions.
  - **A COMPILE-TIME DEFAULT CAN DIFFER BETWEEN THE ENGINE YOU BENCHMARK ON AND THE
    ONE YOU SHIP — and `PRAGMA temp_store` does not tell you which (2026-08-06, the
    merge's 5.9 GB):** the bundled **sqlcipher3 is compiled `SQLITE_TEMP_STORE=2`**,
    the stdlib `sqlite3` is `TEMP_STORE=1`. So every statement journal, temp table and
    transient index defaults to **RAM on the encrypted store and to DISK everywhere
    else** — and `connect.py` never set it. Measured on the real engine, one
    `INSERT..SELECT` with the FTS trigger live and a 256 MiB cache: **~5 KB of RAM per
    row inserted, linear, and `cache_size` does not bound it** (that lesson is about
    the page cache; this is a separate allocation) — 100k/200k/400k rows → +663/+377/
    +735 MB cumulative to 1,980 MB, against **+0 MB and no time penalty** under FILE.
    A field import of 1,358,765 articles in one statement held 5,937 MB on a 5.5 GB
    box. THREE THINGS WORTH KEEPING. (a) The tell is invisible from the pragma:
    `PRAGMA temp_store` returns **0 = "the compile default"**, which is not
    self-describing — you must read `compile_options` to learn what 0 means, and every
    plaintext probe in this repo's history therefore measured the opposite default
    while looking authoritative. This is the recorded "a probe's data distribution is
    part of the lookalike" trap with the ENGINE as the varying axis. (b) Fix the
    setting AND bound the work anyway: the pragma moves the allocation to disk, but a
    5 TB import would then size a temp FILE by the corpus, so the durable answer is a
    statement that only ever handles a bounded window. (c) Do not credit the fix to
    the wrong half — the pragma is what the measurement supports; windowing is what
    makes it corpus-independent, and the two need separate tests or one will be
    reported as evidence for the other.
  - **A BOUND MUST BE DENOMINATED IN THE UNIT THAT ACTUALLY COSTS — and an
    architectural-consistency question can find that faster than a measurement
    (2026-08-06, the merge window):** the windowed merge shipped with a bound of
    20,000 source IDS and a comment claiming that kept a window "in the low hundreds
    of MB". The maintainer then asked whether the batch size shouldn't relate to the
    600 MB the backup already slices volumes into. It cannot *directly* —
    `write_volume_set` cuts an opaque encrypted stream at byte offsets with no row
    alignment, and restore reassembles every volume into one staged file before
    `merge_corpus` opens it, so by merge time volumes do not exist. But the question
    was right about the UNIT, and that is what the ids bound got wrong: measured on
    the shipped engine, the SAME 20,000 rows cost **178 MB at a 2 KB body, 393 MB at
    8 KB and 947 MB at 32 KB** (9.1 / 20.1 / 48.5 KB per row) — so a row-count window
    means something different on every corpus, and on the field artifact (32.1 GB /
    ~1.43M articles ≈ 22 KB each) it would have carried **~800 MB, five times its own
    comment's claim**. A fabricated figure, sitting directly above the constant it
    justified. THE FIX is to size the window in BYTES from a sampled average row size
    and clamp both ends; the numbers differ from the volume size because they answer
    different constraints (a volume is sized by the GF(2⁸) parity ceiling and download
    granularity, a window by what one machine holds at once) but the unit is the same.
    FOUR THINGS WORTH KEEPING. (a) The general form: when you bound a loop, name what
    the loop COSTS and bound that — a count is only a proxy, and it is a bad one
    wherever the items vary (this corpus holds articles from 1 KB to 412 KB).
    (b) Sample from SEVERAL blocks of the id range, not one `LIMIT n`: the oldest rows
    of a corpus are not its typical ones, and a single block makes a systematic drift
    invisible. (c) `LENGTH()` on TEXT counts CHARACTERS — on a mostly non-Latin corpus
    that under-counts every multi-byte row, widening the window exactly where rows are
    biggest; `CAST(x AS BLOB)` is what makes it bytes. (d) A "is X consistent with Y?"
    question from someone holding the whole system in view is a real review instrument:
    it found this when the measurement (which used one row size) and the tests (which
    asserted bounded rows) both could not.
  - **A GUARD OVER AN INTERRUPTED RUN MUST FORCE THE INTERRUPTION TO BE REACHABLE
    (2026-08-06, same slice — the recorded anti-vacuity lesson recurring):** the new
    guard "a half-merged working copy is never stamped `merged`" PASSED against the
    mutation that reverts the fix. Its fixture had three articles and the production
    window is 20,000, so the merge took the single-shot path, never committed
    mid-way, and the failure's rollback wiped `merge_batches` — leaving
    `all(status != 'merged' for row in rows)` to range over an **empty list**. The
    guard could not see its own subject. Two changes, both needed: shrink the window
    so a mid-run commit actually happens, and assert the collection is NON-EMPTY
    before asserting anything about its contents. GENERAL FORM: any assertion of the
    shape "no element of X has property P" is satisfied for free by an empty X, so
    every such guard owes a companion assertion that X exists — and for a guard about
    a *partial* state, that the partial state was genuinely produced rather than
    rolled away.
  - **BATCHING A DEDUPING `INSERT..SELECT` CHANGES WHAT LANDS, because a `NOT EXISTS`
    against the target does NOT see rows the same statement is inserting (2026-08-07,
    B5):** given two incoming rows sharing a step's dedup key, the whole-corpus
    statement keeps **both** and a windowed one keeps **one** — the second window sees
    the first window's commit. Measured on both stdlib sqlite3 and sqlcipher3 before a
    line was written. Neither answer is wrong; they are different, and swapping one for
    the other under a *performance* change is a silent edit to the user's corpus that
    no fixture without internal duplicates can detect. So windowing needs a
    JUSTIFICATION, not just an id to slice on, and exactly three establish it: the
    incoming dedup column is UNIQUE (no second row can exist), a `rep` collapse leaves
    one candidate per identity group, or the target carries a real PK/UNIQUE behind an
    `INSERT OR IGNORE`. Enforce it on the REAL PATH (`_insert_tracked` raises on an
    unregistered step), not only in a test, and record the refusals too — `_NOT_WINDOWED`
    exists because "absent" and "considered and refused" read identically otherwise.
    TWO COROLLARIES. (a) This retroactively audited the articles windowing shipped a week
    earlier: it was safe, because `articles.hash` is `unique=True` — but that was true by
    LUCK, not by check, so the guard now reads it from the schema. When a past change
    turns out to have been safe, ask whether it was safe *by construction* or *by
    accident*; only the first survives the next edit. (b) An `INSERT OR IGNORE` is not
    itself evidence of a constraint: `ai_keyword` has one and its two indexes are both
    NON-unique, so the `OR IGNORE` reads as protection that is not there.
  - **A "MUST BE GONE" GUARD IN PYTHON TRIPS ON THE DOCSTRING THAT EXPLAINS THE REMOVAL —
    and the fix is `ast`, not rewording (2026-08-07, B5; the recorded JS lesson recurring
    one language over, hit while writing the fix it warns about):** the guard asserting the
    inline `MIN(id) AS rep_id` sub-query was gone failed against CORRECT code, on the
    `_materialise_rep` docstring that quotes the pattern to explain why it was removed.
    That docstring is exactly what a future session reads before deciding the removal was
    a mistake, so rewording it is the wrong repair. Parse instead of grep: `ast` gives an
    exact docstring test (first statement of a module/class/function body), so the guard
    can search only the string literals that could really BE SQL. SECOND HALF, and the more
    general point: scoped that way it then failed on `commodity_prices`, whose inline rep
    is CORRECT because that step is not windowed — a guard that fires on correct code gets
    relaxed, and a relaxed guard catches nothing. Scope to the windowed call sites (walk
    `ast.Call` for the `src=` keyword), and add the NEGATIVE-SPACE TWIN asserting an
    unwindowed inline rep still exists somewhere, or "correctly scoped" and "matches
    nothing anywhere" stay indistinguishable.
  - **SQLite DDL IS TRANSACTIONAL, so a merge-level test of a `finally` that restores a
    dropped trigger proves the ROLLBACK, not the `finally` (2026-08-07, B6):** the guard
    for "the FTS insert trigger is always restored" passed against the mutation that
    deletes the `finally` — because the merge's own ROLLBACK undoes a `DROP TRIGGER` by
    itself (verified directly: the trigger is absent mid-transaction and present again
    after the rollback). The test was vacuous in the precise way the anti-vacuity lesson
    above describes, but by a mechanism no fixture size could fix. THE SPLIT that makes it
    real: test the context manager's contract OUTSIDE a transaction, where only the
    `finally` can restore the trigger and where removing it genuinely fails; and rename
    the merge-level test to claim only the property it actually proves. GENERAL FORM:
    before trusting a cleanup test, ask what ELSE would restore the state if the cleanup
    were deleted — in SQLite that includes every DDL statement inside an open transaction,
    so a mutation run inside one is testing the database, not your code.
  - **A PROBE'S SCALE IS PART OF THE LOOKALIKE — a fixture small enough to sit in cache
    cannot reproduce a cache-pressure defect, and "refuted" then goes in the ledger
    (2026-08-07, B6; the recorded "a probe's data distribution is part of the lookalike"
    trap with SCALE as the varying axis):** I recorded FTS automerge as refuted at
    "1.25×/1.24×/1.50×, ~600× short". The measurement was real and the conclusion was
    wrong: on a small fixture the whole index fits in the page cache and few segment
    merges happen, which is the one regime where the problem cannot appear. Re-measured on
    a cache-constrained fixture, the same change is 1.36× overall and 23.7× on the insert
    itself. It cost three field imports. So when a probe REFUTES a hypothesis, state the
    regime it refuted it in, and check that regime is the one the field is in — a negative
    result is a claim about the fixture until it is shown to be a claim about the system.
    Corollary that saved the follow-up: the two OBVIOUS fixes were then genuinely refuted
    by measurement (deferring automerge alone 0.93–0.97×; `'rebuild'` 0.75×, because it
    re-indexes the half of the corpus already indexed), so record refutations WITH their
    numbers or the next session re-chases them.
  - **A FIX THAT RELOCATES A COST MUST BE ASKED WHAT THE REPLACEMENT SCALES WITH — the
    lesson directly above recurred ONE TURN LATER, inside its own fix (2026-08-08, C2):**
    B6 correctly found that FTS work was 98% of the merge and moved it off the article
    step; it then chose `'optimize'` as the tidy-up. `'optimize'` merges the WHOLE index
    into one b-tree, so its cost tracks the **corpus** while the insert beside it tracks
    the **import** — measured 2.05 / 3.00 / 9.31 / 13.81 s as the index grew 25k → 150k
    documents with the insert flat. On a fixture whose corpus is small that is invisible;
    on a queue of eighteen backups it is eighteen whole-index rewrites, each larger than
    the last. GENERAL FORM: when you replace a mechanism, name the dimension the
    REPLACEMENT's cost scales with and check it is the same dimension the original scaled
    with — a replacement that tracks a different axis looks fine at the fixture's scale
    and wrong at the field's, and no amount of re-running the same fixture reveals it.
    COROLLARY, and the reason this one was caught: **a change that removes a tidying pass
    owes a QUERY-side measurement**, or it is a transfer rather than a win. Here the
    measurement said the trade did not exist (74.5 vs 74.6 ms median over six terms from
    very common to rare, bm25 as `search_ids` runs it, on a reopened connection) — and it
    also killed a mechanism I had already written: a bounded incremental merge bought 2–3%
    on query, inside the noise, for 16% more build, so it was deleted rather than shipped
    "just in case".
  - **FTS5 `hashsize` IS THE BULK-LOAD LEVER NOBODY IN THIS REPO HAD SET, AND IT IS NOT
    MONOTONIC (2026-08-08, C2):** FTS5 holds pending index data in memory and flushes a
    **new level-0 segment** every time it exceeds `hashsize`, whose default is **1 MiB**.
    That is what decides how many segments a bulk load creates, and collapsing them is the
    crisis-merge cascade whose `fts5DataRemoveSegment` dominated the field beat. Measured
    60k docs into a 60k index, varying only that: 1 MiB → 19 segments / 12.33 s; 4 MiB →
    16 / 9.43 s; 64 MiB → 4 / **8.40 s**; 256 MiB → 4 / **8.69 s, worse than 64**. So "as
    much as we can get" is the wrong instinct and the default is a measured number. TWO
    THINGS THAT BITE: it is a REAL allocation, so it belongs beside the page cache in the
    merge's memory budget rather than on top of it; and it **PERSISTS to
    `article_fts_config`** (verified), so a load that forgets to restore it leaves the
    corpus holding that budget for every later ingest — which is why the guard asserts the
    persisted value rather than counting statements. MEASURED AND NOT THE ANSWER, recorded
    so nobody re-chases it: `auto_vacuum=INCREMENTAL` costs ~5% on this workload
    (30.43 vs 28.83 s, 15.91 vs 15.17 s) — real, small, and nowhere near the field's gap.
  - **A STEP REPORTED AGAINST A DENOMINATOR THAT EXCLUDES IT PUBLISHES A NUMBER THAT
    COLLIDES WITH ANOTHER STEP (2026-08-08, C3):** the search-index build called
    `_step_watch(con, total, total, …)` where `total = len(steps)` did not count it, and
    the tick publishes `done = index − 1` — so it published `18`, which is exactly what the
    LAST table step publishes on completion. "18/19" therefore meant either *watches
    finished* or *the search index has been running for fourteen hours*, and the run
    timeline duly reported `stuck_at: 18` with the reading *"workers were idle"*. Count
    every step you report, including one that is not in the steps tuple. SECOND HALF: that
    step's own row progress went through `runlog.statement` — the **same slot** the
    per-statement trace overwrites within milliseconds — so the one step that genuinely
    knows how far it has got (it walks a known list of ids) published nothing that
    survived. Before adding progress, check which slot already owns that field and who
    else writes it.
  - **`pgrep -f "<pattern>"` IN A WAIT LOOP MATCHES THE WAITING SCRIPT'S OWN COMMAND LINE
    (2026-08-08, harness):** a chain of `while pgrep -f "a.py"; do sleep 10; done` scripts
    deadlocked on itself — each script's own `bash -c` command line contains the pattern it
    is waiting on, so it waits for itself forever, silently, looking exactly like a
    long-running experiment. Cost ~20 minutes of wall clock and produced four empty logs.
    Run sequential work in ONE script, or match on something the waiter cannot contain.
  - **A PUBLISHED REASON SENTENCE IS AN API — NAME IT, AND ASSERT IDENTITY, NOT A
    SUBSTRING (2026-08-08, the `kb_per_row_unavailable` red lane):** rewording a gap
    reason from "did not grow" to "did not **measurably** grow" reddened a guard asserting
    `"did not grow" in reason`. I greped the source for readers of that string and not the
    TEST tree, which is the half that mattered — the recorded stale-anchor class, again.
    The repair is not to re-pick a substring but to hoist both reasons into module
    constants and have every guard assert `== RSS_GAP_CURRENT` / `== RSS_GAP_PEAK`.
    Identity is strictly **stronger** here, not merely more robust: a substring proves
    some words appear, whereas identity proves WHICH of the two readers went blind — which
    is the property those guards sit inside a branch to check, and the one a substring
    could never distinguish (both sentences are about an unobservable delta). Mutation-check
    both directions: swapping which constant each branch publishes must fail by name, and a
    pure rewording must now pass. COROLLARY that is the real fix: the branch CI hit was
    reachable locally only when the allocator happened to serve the probe from a warm arena
    — a CI-shaped accident — so it also got a stub test that reaches it on every platform.
    When a guard fails only on CI, ask whether its branch has any deterministic driver at
    all; if not, the fix is a second test, not a better assertion.

## Open queue (when maintainer says proceed)
- **IMPORT PIPELINING + THE PER-BACKUP CHECKPOINT (maintainer asked 2026-08-08 for both;
  the MEASUREMENT shipped, the two structural changes did NOT — deliberately, and the
  reasons are findings rather than reluctance):** the queue runs `_drive()` as a strict
  `for` loop of `_run_item` → `run_restore`, so every backup pays its own
  **prepare** (stage A + validate + upgrade, measured 46.7 and 56.0 min on the two field
  runs, on files that never touch the live corpus) and its own **verify_copy** (a
  `quick_check` + `foreign_key_check` over the WHOLE working copy — the live corpus plus
  everything merged so far). On eighteen backups that is ~14–17 h of prepare in series
  with the merges, and eighteen structural walks of a growing multi-GB file.
  **(a) PREFETCH — three blockers found by reading the seam, all of which raise the
  estimate:** (i) staging lives INSIDE `VolumeBackupManager._run_restore`, on the
  singleton manager's worker thread, and that singleton is one-job-at-a-time BY DESIGN
  (`_reap_or_reject`) — so the queue would need to stage into its own tree and hand a
  `StagedArtifact` across, which means a new `start_restore(..., staged=)` seam; (ii)
  `cleanup_staging(staged)` is in a `finally` owned by the merge thread, so a
  prefetched tree crosses an ownership boundary the current code guarantees by
  construction — and on an encrypted corpus that tree is PLAINTEXT, so an orphan is an
  at-rest hole, not just bytes; (iii) **decisive** — `find_completed_import` runs
  BEFORE staging precisely so an already-merged artifact costs one small JSON read, and
  the field log records **8 of 18 imports adding zero articles**. A prefetch that stages
  ahead of that check burns 47–56 min per skipped item and defeats an existing
  optimisation. Any build must run the digest check first.
  **(b) CHECKPOINT INTERVAL — needs a RULING, not a guess:** verify+swap once per K
  backups instead of per backup would save 17 × (verify + snapshot + swap), but nothing
  is durable until a swap: today a kill at item 12 keeps eleven committed and skipped on
  re-run, and at K=18 it loses twelve merges' CPU. The maintainer has killed this import
  twice, so the trade is real. K is theirs to choose.
  **WHAT SHIPPED INSTEAD (both merged-order-independent):** `verify_copy` sub-timings
  (`verify:quick_check` / `foreign_key_check` / `counts` / `content_sample`) + the
  `working_copy_bytes` the walk traverses, so the first completed backup converts
  "2414 s" into a rate; and `merge_diag.walk_probe`, which measures the plaintext-vs-
  encrypted page-walk RATIO on this machine (**2.40 / 2.39 / 2.42 across three runs**;
  likely an upper bound at field scale, where I/O takes a larger share). `verify_copy`
  has NEVER been observed in the field — both recorded runs ended before it — so every
  estimate above rests on it, and the next completed backup supplies it for free.
  SEQUENCING: read the first real verify number, THEN pick K, THEN build the prefetch if
  the prepare side still dominates.
- **FIELD FEEDBACK 2026-08-07 — governments · law extraction · Feed tab · crash visibility ·
  card provenance · Articles tab · Settings (maintainer; INTAKE + INVESTIGATION this session,
  code-verified against `main`@9c651ee, 47 numbered questions ANSWERED the same day; brief of
  record = [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-08-07_FIELD_FEEDBACK.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-08-07_FIELD_FEEDBACK.md);
  NOTHING BUILT):** eight impressions, two of them with attachments that changed the plan.
  **THE HEADLINE CORRECTION — the Governments figures are NOT cross-assigned.** `XD` is the
  World Bank's 2-letter code for the **"High income" aggregate** (iso3 `HIC`), and every value
  in the maintainer's PDF is mutually consistent with it (GDP $77T · per capita $54k ·
  population 1.4B · life expectancy 80.4 · fertility 1.42 · literacy 97.7% · electricity 100% ·
  internet 94.2% · mobile 141.6/100). So the work is FILTERING, PAGINATION and LABELLING — do
  NOT open a data-corruption investigation. Two figures that read as errors are CORRECT and
  need a label, not a fix: `IT.CEL.SETS.P2` 141.6 (subscriptions, not people — multiple SIMs)
  and `SE.SEC.ENRR` 103.2% (gross enrollment counts repeaters and over-age pupils).
  **SIX GOVERNMENTS DEFECTS, each anchored:** (G1) `fetch_worldbank` **never paginates** —
  `src/stats/fetch.py:181` does ONE GET at `per_page=1000` and `_worldbank_observations`
  returns `payload[1]` while **discarding `payload[0]`**, the page meta carrying `pages`/`total`;
  `country=all` is ~266 economies × ~65 years ≈ 17k rows, so ~94% of every indicator is silently
  missing (corroborated by the PDF's 2016–2025 span, n=9/8/5/1). (G2) `to_iso2()` returns ANY
  2-letter string unchanged, so WB 2-letter AGGREGATE codes are admitted as countries (`XD`,
  `XC`, `XT`/`XM`/`XN`/`XO`/`XP`, `EU`, `OE`, `1W`, `Z4`/`Z7`/`ZG`/`ZJ`/`ZQ`, `8S`, `B8`, `F1`,
  `S1`–`S4`…) — **its docstring promises `None` for aggregates, which is true only for the
  3-letter form: a fabricated guarantee in a docstring**; `to_iso3` has the mirror hole.
  (G3) `_govFmt` (`app.js:4690`) covers 5 of the catalog's 11 units, so `intl$` renders GDP-PPP
  as `99 594 884 137 256.80` and `per 100` renders bare — the maintainer's "ten digit figure"
  and "140%" complaints, both exactly reproduced in the PDF. (G4) chart GRIDLINE labels are
  unformatted too (`51167643745037.1`). (G5) a single-point series prints its x-axis as `01-01`
  instead of the year. (G6) `.gov-ind-spark svg{width:100%;height:32px}` forces a fixed 300×120
  viewBox into 9:1. NOT SETTLED (egress-blocked, HTTP 000): *why exactly one* economy survives —
  it does not change the fix; the subscription replay path was checked and is NOT a second
  culprit (`refresh_due` calls the same un-paginated fetch).
  **THE LAW ATTACHMENT — a boilerplate STRIP stage is missing, architecturally.** The stored
  body of *Data Protection Act 2018 (consolidated)* is the entire legislation.gov.uk page chrome
  (`Skip to main content · Cymraeg · Search Legislation · Title: · Year: · All UK Legislation
  (excluding originating from the EU) · UK Private and Personal Acts · …` — the site's
  search-form dropdown, ingested as prose). Every bogus extraction traces to it: `Personal Acts`
  and `Data Protection`/`Great Britain`/`United Kingdom` as PEOPLE, `PART ×24` as an
  ORGANIZATION, `Uk`/`United Kingdom`/`Britain` as three uncanonicalised places, **`Ireland (ie)`
  inside a UK Act** (a geographic FABRICATION — "Northern Ireland" mis-resolved), and event dates
  three days before capture (the "changes to legislation as at" banner). `Published 2026-07-31`
  for the 2018 Act = the tracking date stored as the publication date. WHY THE GATES MISSED IT:
  `classify_non_article` + `prose_gate_verdict` are BINARY (article / not-article) and this page
  is ~80% genuine Act text, so it is correctly KEPT and the chrome rides along — **there is a
  reject stage and no strip stage**, which affects every source without a clean extractor.
  SEQUENCING RULE recorded: fix the INPUT and re-measure BEFORE touching the entity classifier —
  four of the five bogus "people" are nav text, so tuning against that input calibrates on an
  artefact.
  **FOUR MORE VERIFIED FINDINGS:** `loadHealth()` is called EXACTLY ONCE, at boot
  (`app.js:22320`), never polled — the green "healthy" pill is a boot-time paint that can never
  go red (item 4, root-caused). Articles-tab SORTING **already exists** end-to-end
  (`an-adv-sort`/`an-adv-dir` → `sort_by`, `main.py:1038`) but lives in the **Advanced** subtab —
  placement, not absence (item 5); sort-by-TAG genuinely does not exist, and the existing
  keyword-count sort counts THE SEARCHED keyword, not the article's own top keyword.
  `famHue(bi)=hsl((bi*53)%360…)` is keyed to BUCKET INDEX (`app.js:2816`), so a card family's
  hue SHIFTS whenever the set of non-empty buckets changes — it cannot carry identity until it
  is hashed from a stable name (item 1). **The 2026-07-20 one-button diagnostics ruling was
  NEVER EXECUTED** — item 6 is a repeat, which by rule (3) of THE PROTOCOL is a ledger failure,
  not merely a task. Also verified: **no bloc/membership registry exists anywhere in the tree**;
  OECD and IMF are directory-only entries in `agencies.py:73-76` (no fetch/parse wiring) and
  `parse_sdmx_json` handles SDMX-JSON **2.1** while OECD is 1.0 and IMF 3.0 — verify, never assume.
  **THE 47 RULINGS (maintainer, same day):** • (1b) aggregates are KEPT, tagged, excluded from
  country surfaces, and given their own view — **the reframe: the World Bank aggregates leaking
  in as "XD" ARE the regional/world averages the maintainer asked for**, so Africa (SSF/AFE/AFW),
  the Middle East (MEA/Arab World) and South/Central America (LCN) close FOR FREE with pagination.
  • (2) no computed BRICS for now; the **BRICS Joint Statistical Publication** exists and is an
  acquisition task, recorded. • (3) "Western" uses an EXISTING published set (OECD/EU/High
  income), never an invented one. • (4) two countries side by side across all indicators.
  • (5,30,31) government data goes DEEP into search: **one Article per SERIES** (indicator ×
  country ≈ 9,800) through `index_article`, INCLUDED in trending/Leads/Feed, own `statistics`
  provenance class. • (6) store all years. • (7) live code verification deferred to an
  internet-connected session. • (8,41) Feed random ordering uses a seed **persisted per session**
  + a Settings→General "reset scrolling history" offering BOTH a reshuffle and a clear-seen reset.
  • (9) Feed defaults to everything; provenance selection lives in Settings. • (10) per-article
  own top-3 keywords, honest and verifiable. • (11) exclude quarantined AND not-yet-qualified.
  • (12) "read more" expands IN PLACE. • (13,40) a NEW sidebar tab, named **Feed**. • (14) the
  family hue is hashed from a STABLE name. • (15) a PERSISTENT header in the analysis window.
  • (16) the WHOLE provenance travels (card · family · producer · trigger · method · caveat).
  • (17,18,19) an honest crash screen with a run-journal download, **NO auto-restart — "honesty
  first"**. • (20,21,22) MOVE the sort controls into the Articles tab (never duplicate), sortable
  column headers, and REMOVE the `source ↗` column + the Summarize/Translate buttons (the reader
  carries both — absorption-verified). • (23,38,39) PRE-COMPUTE the top keyword as additive
  nullable `Article.top_keyword_id`/`top_keyword_count` on the `detected_language` pattern,
  **ties store BOTH**. • (24) per-sweep AI on/off toggles are KEPT; only the redundant per-sweep
  RUN buttons go. • (25) Diagnostics becomes ONE section in Advanced; **job-starters and
  interactive tools are ACTIONS, not report downloads, and stay**. • (26,42) Safety moves into
  Advanced and **Uninstall & wipe becomes its OWN separate section**; end state = **9 subtabs**.
  • (27) no second-level subtab strip. • (32) a curated aggregate shortlist with "show all 48".
  • (33) fill gradually via the existing ride-along — no hours-long button. • (34) build the
  **legislation.gov.uk XML adapter** (law brief S6 adapter #1) + a generic boilerplate-STRIP
  stage, PLUS a new **XML-ingest reliability diagnostic** across structured law sources
  (decision taken unless objected: it re-parses STORED copies offline so it runs under airplane
  mode; a live re-fetch sits behind the one consent). • (35) RE-EXTRACT the 23 tracked law
  documents. • (36) add legislative furniture (`PART`/`SCHEDULE`/`CHAPTER`/`SECTION`/`ANNEX`…)
  to the caps-acronym stoplist. • (37) the Northern-Ireland gazetteer mis-resolution gets its own
  reproducer + regression test. • (43,44) **local compute IS offered, with SEVERAL strategies
  shown side by side so the user compares and forms their own view** — population-weighted
  (default), simple mean, GDP-weighted, median, and sum; **REFUSE by default on incomplete
  coverage, with an explicit publish-anyway override carrying the warning and the missing members
  IN THE PAYLOAD**, not only in the UI. • (45) the membership registry is **TIME-VARYING** with
  sourced joined/left dates, and every bloc surface — INCLUDING side-by-side, which is not
  "computed" — states its membership vintage. • (46) Tier-2 publisher order: OECD+IMF → AfDB →
  regional bodies. • (47) **BOTH continents AND World Bank regions as two lenses, and not only
  averages — cumulative TOTALS too.**
  **THE LOAD-BEARING DESIGN RAIL (derived from ruling 47, recorded so it is not lost):
  AGGREGATION IS INDICATOR-AWARE.** An **extensive** indicator (population, GDP, GDP-PPP, labour
  force) may be SUMMED; an **intensive** one (every `%`, `per N`, `years`, `index`,
  `births/woman`, `t/capita`) may NOT — a summed percentage is a fabricated statistic and must be
  REFUSED, not offered greyed-out. Declare `extensive: true|false` EXPLICITLY on each catalog
  entry rather than inferring it from the unit string (a string heuristic breaks the day someone
  adds a unit). Corollary worth keeping: a population-weighted mean of a per-capita indicator
  EQUALS `Σ numerator / Σ denominator` — the true aggregate, not an approximation — provided the
  numerator is reconstructed as `value × population` and the weight series is real for the same
  members and year (a missing weight is a coverage failure, never a silent fallback to
  unweighted). Always display the SPREAD (min/max/n) beside a central figure: a bloc headline
  hiding a ten-fold range is technically true and practically misleading.
  **MEMBERSHIP IS TIME-VARYING AND THIS SILENTLY CORRUPTS EVERY BLOC SERIES IF UNHANDLED:**
  BRICS was five members until 2024 (then Egypt, Ethiopia, Iran, UAE; Indonesia 2025), NATO
  gained Finland (2023) and Sweden (2024), the EU lost the UK (2020). A bloc figure computed with
  today's roster over a 1995 series is wrong in a way no reader can detect — so membership
  resolves AS OF the figure's year, the vintage is stated on every surface, and a member whose
  accession date cannot be sourced is recorded `joined: null` with its unresolvable history
  stated (never guess a date to make a series continuous).
  **A NUANCE THAT DECIDED RULING 47:** World Bank REGIONS are not CONTINENTS — "Sub-Saharan
  Africa" excludes Egypt, Libya, Tunisia, Algeria and Morocco (they sit in MENA), so the WB lens
  has NO continental-Africa figure at all. That is precisely why both lenses ship, and why AfDB
  is the publisher-route to continental Africa rather than a computation.
  **OPERATOR / INTERNET-SESSION TO-DO (egress-blocked here; none may be guessed):** verify the 37
  WB indicator codes live · confirm the shape of WB page 1 · the BRICS Joint Statistical
  Publication · AfDB/UNECA continental endpoints · OECD/IMF SDMX message-version verification ·
  bloc membership sourcing with dates.
- **MERGE STEP 3 IS STILL UNEXPLAINED — and the leading hypothesis is now REFUTED, so do
  not re-chase it (2026-08-06, from the field beat ring of `imp-20260805T032610Z-477e83`):**
  a second 24 h import died at the same place. WHAT THE BEAT PROVES: the merge entered step
  3 of 19 at 1.93 h and never advanced — 22.1 h at `done=2/19`, `d_done=0` throughout —
  while genuinely working (~0.7 core, CPU-bound, ~80 KB/s written, `gate.held=false`, no
  child processes). RSS went **845 → 5,937 MB in ~90 s** at step-3 entry and then sat
  byte-stable (±4 MB) for twenty-two hours: a SINGLE bounded allocation, not an accumulator
  (the recorded plateau lesson). WHAT IS REFUTED: `#878`'s standing hypothesis — that the
  report-only duplicate/conflict tally in `_merge_articles` owns the time because it drags
  full `content` through the codec for every hash-matching pair. Measured on a 2×60,000-row
  /494 MB fixture at 100 % hash overlap (the additive re-import case): **0.24 s, 14 MB peak**,
  plan `SCAN i` + `SEARCH m USING INDEX idx_hash` — it STREAMS. The 2026-07-30 one-pass
  rewrite already halved it, and it is neither the memory nor, at any plausible constant
  factor, the time. (Caveat, per the lookalike lesson: the fixture is plaintext, uniform and
  smaller than the field corpus; the PLAN would not change, and codec cost is arithmetically
  ~0.1 % here — 59,235 CPU-seconds were burned against ~50 s of AES at AES-NI speed.)
  **⚠ ANSWERED 2026-08-07 — IT IS FTS5, AND MY OWN EARLIER REFUTATION OF FTS WAS WRONG.**
  A third field import (`imp-20260807T033245Z-c65469`, ~1.4M-article corpus) stalled the same
  way, and the beat that F1/#886 shipped names it outright: of **1,223 merging beats, 1,198 —
  98 %, 4.99 of the 5.10 h** — carry `sql: "-- DELETE FROM 'main'.'article_fts_data' WHERE
  id>=? AND id<=?"`, FTS5's internal segment-merge cleanup (the `--` prefix is SQLite
  reporting a statement IT ran, from the `article_fts_ai` trigger's machinery, not one we
  wrote). Four things the beat settles that no reasoning could: it is **not one stuck
  statement** (`sql_s` median 1.2 s, max 6.5 s — thousands of short ones); **memory is fine**
  (RSS 1.1–1.5 GB against 8.7 GB free, so B1/B2 work and the 5.1 GB allocation above was the
  pre-B2 `temp_store=MEMORY` default, now closed); it is **single-threaded CPU** (5.09 h wall
  vs 4.24 h CPU = 0.83 cores); and `done=2/19` never moved. MECHANISM: `article_fts_ai AFTER
  INSERT ON articles` fires per inserted article and `src/database/fts.py` sets **no automerge
  value anywhere**, so FTS5 runs its default (4), merging b-tree segments continuously as
  ~686k incoming articles land in an index already holding ~794k. **THE CORRECTION I OWE THE
  RECORD:** an earlier entry refuted FTS automerge at "1.25×/1.24×/1.50×, ~600× short". That
  measurement was real but taken on a small fixture, where the index fits in the page cache and
  few merges happen — the one regime where the problem cannot appear. Stated as refuted; it was
  not. This is the recorded "a probe's data distribution is part of the lookalike" trap with
  **SCALE** as the varying axis, and it cost three field imports.
  **BOTH OBVIOUS FIXES ARE ALSO REFUTED, by measurement (do not re-chase either):** deferring
  automerge is **0.93×/0.94×/0.97×** at 10k/30k/60k docs (no help, and scaling there is linear);
  dropping the trigger and running `'rebuild'` after is **0.75× at both 40k and 80k docs** —
  33 % MORE total work, because `'rebuild'` re-indexes the WHOLE corpus including the half
  already indexed. What those probes DO establish is the number the fix rests on: with the
  trigger off, the article insert itself runs **12–14× faster** (18.76 s → 1.59 s; 40.04 s →
  2.92 s). So the FTS work is not reducible by tuning — it is relocatable. See the B6 entry.
  **STILL OPEN, and not to be guessed at:** the probes extrapolate to ~20 min at field scale
  against 5+ h observed, a 15–65× gap nothing here reproduces. Candidates are the SQLCipher
  codec over multi-GB FTS segments, the operator's virtual disk, and merges rewriting against
  the 794k already-indexed documents. The `cost_probe` block of `merge-diag.json` measures
  per-row cost on the operator's OWN machine, which is how that gap gets closed rather than
  argued about.
- **THE APP'S OOM AT 24 h WAS THE JOURNAL READ, and the timeline is exact (same run):** the
  merge held 5,960 MB for 22 h with `mem_avail` steady around 4,300 MB. The operator then ran
  an all-diagnostics bundle: its own journal shows `run-journal.json` beginning at 03:27:18,
  and the last beat ever written is 03:28:03 — **45 s later**, with RSS 5,960 → **10,063 MB**,
  `mem_avail` 4,301 → **716 MB** and swap 885 → **1,024 MB (full)**. Independently measured:
  reading that 1.6 GB journal through the pre-fix `_read_jsonl` peaks at **7,323 MB**. So the
  merge was survivable and the diagnostic was not; the bundle also never finished (it stopped
  at member 26 of 54, leaving a `.part`). Both halves are closed by the F1–F4 fix — but note
  the ORDER of blame: the import would not have completed regardless (entry above), so a
  future session must not read "the OOM is fixed" as "the import is fixed".
- **`card-audit.json` HAS NOT SERIALISED SINCE AT LEAST 2026-08-06 — found in a field
  bundle, NOT fixed (a different subsystem from the vLLM chain that surfaced it, and the
  root cause needs a real corpus to locate):** the member computes for **112 seconds**
  and is then thrown away whole by the JSON encoder — `Out of range float values are not
  JSON compliant: -inf`. `card_audit._eval_arith` already refuses non-finite values
  (`card_audit.py:235`), so the `-inf` is reaching the payload from some OTHER field, and
  which one is unknown without the corpus that produced it. THE FIX SHAPE, when built:
  sanitise at the serialisation boundary — non-finite floats become `null` **and the
  report NAMES the fields that were non-finite**, so the member survives AND the next
  bundle identifies the culprit. Sanitising silently would make this the exact
  hiding-place-for-the-bug-it-survives shape the ledger already warns about twice. The
  other bundle members were unaffected (the per-member guard did its job — one failure,
  not an aborted export).
- **~~WHY TEN vLLM STARTS DIED~~ — ANSWERED 2026-08-09, and the host-RAM hypothesis was
  WRONG.** The operator's preserved log named it outright: vLLM 0.26 selects FlashInfer
  for top-k/top-p sampling (`Using FlashInfer for top-p & top-k sampling`), FlashInfer
  **JIT-compiles** that kernel on first use, and first use is `warmup_kernels` at the very
  END of engine init — so on a machine with the NVIDIA driver and **no CUDA toolkit** it
  died on `RuntimeError: Could not find nvcc and default cuda_home='/usr/local/cuda'
  doesn't exist`, ~78 s in, with the weights already resident. That is precisely the
  reported "model loads in VRAM but unloads for unknown reasons" — the card was full when
  it died. NOT host RAM (`journalctl -k` was empty and 5.5 GB was available), NOT the OOM
  killer, NOT graph capture (`enforce_eager` is on below 10 GB, so no capture happens).
  FIXED same day: `_server_env()` sets `VLLM_USE_FLASHINFER_SAMPLER=0` whenever
  `cuda_toolkit_present()` is false. **The standing lesson to keep: a DRIVER is not a
  TOOLKIT.** Inference needs only the driver; any JIT path silently converts a runtime
  dependency into a BUILD dependency, and it fails at the END of initialisation with the
  expensive resource already committed — which reads as "it worked and then stopped"
  rather than "it never started". When a component is chosen at runtime because a package
  is merely importable, ask what that component does on first use.
- **THE TWO 2026-08-03 BRIEFS ARE EXECUTED (PR #856, branch `claude/pr852-coding-session-m1m6k0`;
  five `docs/ledger/shipped.csv` rows). MAINTAINER RULINGS RECEIVED + BUILT the same day.**
  **MERGE_TABLES:** Part 0's fourteen silently-dropped columns are carried and the class is
  closed by an AST guard at column granularity; the five unmerged tables have handlers on the
  ruled identities — `watches`=NAME · `watch_matches`=(watch, fired_at) ·
  `ai_custom_prompt`=**(output_kind, prompt_text)** · `ai_keyword`=(article, kind, term, model) ·
  `law_revision_summaries`=(revision, model). **THE ONE OVERRIDE worth carrying forward:** the
  maintainer chose the prompt TEXT over the recommended LABEL, and the reason generalises — with
  label-identity plus the standing local-wins policy, a prompt improved on a secondary machine
  could never travel home; keying on the text makes the improvement arrive as a row the user can
  see and choose between. `_MERGE_NOT_CARRIED`'s owed section is now EMPTY and kept as the place
  the next such table goes (an unanswerable identity is a reason to state the question, never to
  guess). **SOURCE_QUALIFICATION:** slices 1–5 + the §1b/§1c panel all shipped — the report now
  headlines the CONJUNCTION rather than a percentile definition, prints each threshold's observed
  range beside it, exempts non-scrape provenance classes from the ratio cohorts, excludes
  quarantined articles from every collector, RETIRES the furniture verdict (option (a), with a
  mechanism-level reason: option (b)'s corroboration set is entirely already-stoplisted, so it
  could never fire BY CONSTRUCTION), adds the measured-cheap `cheap_signal` selector plus
  per-selector enrichment-over-control, and gives both gates one Advanced panel with units, hover
  explanations and the two scraping-scope toggles.
  **⚠ SLICE 5 IS A MAINTAINER DECISION AND IS DELIBERATELY NOT MADE — the measurement shipped, the
  threshold did NOT.** `PATHOLOGY_ABS_FLOOR` is still 0.5 and **no source in the field corpus can
  reach it** (the strongest observed signal was `bisnow.com` at 0.211, less than half the floor),
  so the admission gate currently cannot disqualify anything — not because the sources are good but
  because its one decisive criterion is calibrated above the observable range. Lowering it to make
  the gate fire would be tuning a data-safety threshold to make a number move (the inverse of the
  recorded WAL-recalibration lesson). THE THREE OPTIONS, unchanged and awaiting a ruling: (a) keep
  0.5 and accept that this criterion is a rare-catastrophe detector, saying so in the panel;
  (b) lower it WITH a stated new meaning; (c) add a second, differently-shaped extraction-failure
  criterion — and `high_link_density` is the obvious candidate, since it is the strongest measured
  discriminator in the whole corpus (415 of 675 label hits) and is currently only a review hint.
  The export now carries the full per-source `pathology_rate` distribution, so the next run
  measures the choice rather than re-arguing it.
  **ALSO DELIBERATELY NOT DONE, with the reason:** the provenance exemption was NOT extended to
  `source_audit.per_source_metrics`. A source missing from that dict means "no evidence to judge",
  so exempting the synthetic `hazard.*`/`law.*` sources would make them permanently unqualifiable —
  and `select_sources` admits only qualified sources, so that is a collection-eligibility change
  arising from a finding about a distorted BASELINE. Their verdicts were never at risk either way.
  **REMAINING:** a maintainer CLICK-THROUGH of the new Quality-gates panel (browser-unverified per
  fork-3/Q6a — `node --check` + 251 invariants pass, but no browser ran); and the standing
  operator step of re-running the source-quality export so the new `observed` /
  `selector_enrichment` blocks can be read on the live corpus.
- **FIELD IMPRESSIONS 2026-08-01 — Home-alerts relevance/card system · Home overview subtabs ·
  Library revamp + graph clarity · unified AI toggle + small-model comparative bench (maintainer;
  INTAKE + INVESTIGATION this session, code-verified against `main`@d725f5b via a 5-agent
  read-only fan-out with the load-bearing claims hand-re-verified; PLANNING for a future
  autonomous Opus 5 session — numbered questions put to the maintainer, ANSWERS PENDING, record
  them here when they arrive; NOTHING BUILT):** four remarks, each root-caused.
  (1) **ALERTS — the 2026-07-24 A6/A9/A10 builds ARE shipped** (hazards-as-Articles +
  `HazardEventDetail` + the HAZARD provenance class; the tiered Home strip with per-item 🗺
  `openWorldMapAt` deep-links; the local-snapshot-only map layer; magnitude restored into
  `compute_alerts`) — but the Session-A brief
  (`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_A_FIELD_FIXES.md`) still carries a STALE
  "Status: PENDING execution" banner (fix on the next docs touch). The residual defect is
  SELECTION, not plumbing: `_hazard_tier` (src/analytics/alerts.py:59) promotes ONLY GDACS
  green/orange/red, so EVERY USGS quake lands in "info" (magnitude deliberately never promoted
  into urgency — that honesty rule STAYS), and `_renderHomeAlerts` (app.js:2551) renders each
  tier UNCAPPED in snapshot order with no within-tier ordering — a M6.8 drowns among M4.5s
  exactly as reported. USGS `_quake_band` (major/strong/moderate/minor, parse.py:24) is parsed
  but drives nothing; GDACS records carry NO magnitude (level only); NO cross-provider
  same-event dedup exists (one quake can appear via both USGS and GDACS); alerts ALSO surface a
  second time via the `severity_alerts` producer (bucket=watch). Fix shape pending answers:
  within-tier ordering + a display floor/cap by PROVIDER-DECLARED facts (magnitude BANDS
  labelled as bands, never as urgency), "N more on the map →" overflow, per-major-event cards.
  (2) **HOME — the long scroll is the "__all" default lens**: family subtabs exist (ooSubtabs,
  8 buckets) but default to ALL cards of ALL buckets with NO total cap (37 producers × 1–10
  cards); the carousel is top-8 FLATTENED across buckets (one bucket can fill it); the live
  order IS the disclosed leads order (bucket priority → order_key = distinct sources →
  magnitude tier → recency, service.py:161-189) BUT `explain_order` +
  `/api/insights/leads-view` have ZERO frontend callers since the Settings restructure deleted
  the Leads preview subtab — the ordering-transparency surface is currently GONE; no
  top-card-per-family logic exists anywhere. Plan direction: an "Overview" default lens = top
  card per family by the SAME disclosed order_key, each with a visible why-this-card explain
  (restores the transparency surface), families as today, "All Leads" kept.
  (3) **LIBRARY — 7 flat sections, NO subtabs**; the graph defects are mechanism-confirmed and
  TOOLKIT-WIDE, not library-local: BOTH renderers fabricate ticks on flat integer series via
  the `span=(max-min)||1` fallback (dashChartSvg app.js:9735/9757: a constant-23 series draws
  gridlines 23 / "23.50" / 23 with the min+max labels OVERLAPPING at the plot bottom; ooChart
  app.js:10354: 23 / 23.33 / 23.67 / 24 — a +1 top tick no data reaches); NO
  integer-snap/nice-tick logic exists in either; dashChartSvg X labels are hard MONTH
  granularity `slice(0,7)` with INDEX-only dedup → two same-month hourly snapshots both print
  "2026-07"; `n=` renders unitless (it means DATAPOINTS — the maintainer's "23 docs or 2?"
  confusion); library count bars anchor to window-MIN not zero (Item Y says count series →
  zero base); the graphs-overflow-their-box vector = the qualification tile's ooChart FIXED-px
  canvas (320 px hard floor; 680 px hidden-element fallback, app.js:10268) with NO overflow
  clipping anywhere in the tile/row/panel chain. A5's hide-flat-zero / per-tile window switcher
  / 4-line qualification tile ARE shipped. Fix = an app-wide AXIS-HONESTY pass on the one chart
  toolkit (invariant #16 territory) + an ooSubtabs restructure; the maintainer OFFERS page
  exports as the verification channel (saved HTML preferred over PDF — full DOM; feeds 0.3
  gate row 8).
  (4) **AI — NO master toggle exists**: the three progressive sweeps have separate toggle
  buttons; langdetect auto-start (`ai_langdetect_auto`, default True) is the ONLY auto-start
  setting and the ONLY hardware-gated sweep (`inference_capability` gates ONLY langdetect-auto
  + the Bulletin — the sweeps/manual runs never consult it); qualification-assist has NO UI
  trigger; `/api/ai/keywords/extract` has ZERO frontend callers. DEFAULT MODEL today =
  `ministral-3:8b-instruct-2512-q4_K_M` on Ollama (since 2026-07-30; vLLM default
  `mistralai/Ministral-3-3B-Instruct-2512` FP8) — the maintainer proposes CHALLENGING it with
  tiny models (LiquidAI "LFM2.5-8B-A1B" named; the exact Ollama tag / HF repo MUST be verified
  at execution and REFUSED if absent, never substituted — the roster rule; LFM2-class models
  cover ~8 languages vs our 12 ⇒ the per-language tri-state gate is the honest activation
  instrument). THE BENCH GAP: `triage.py` ships `verify_roster` + per-metric helpers
  (anchor_accuracy · pairwise_agreement · format validity · canaries) but NO multi-model bench
  RUNNER, no frozen-batch builder, no endpoint — the ruled 7-model bench is still an operator
  PROTOCOL, not code; `llm_bench` (latency, per-shape) and
  `run_perception_eval_against_model` already run per-model on EITHER backend. Plan direction:
  a roster comparative runner (per model × per task × per language, every metric ALONE, no
  composite, persisted side-by-side + downloadable logs for the
  ai-proposed→claude-verified→maintainer-merged chain) + a coordinator-style master toggle
  (enabled sweeps round-robin on the ONE backend so they never contend, per-feature toggles
  kept).
  **ANSWERS RECEIVED + RULED same day (maintainer answered all 17; briefs of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-08-01_D_HOME_ALERTS_LIBRARY_UI.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-08-01_D_HOME_ALERTS_LIBRARY_UI.md) +
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-08-01_E_AI_COORDINATOR_BENCH.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-08-01_E_AI_COORDINATOR_BENCH.md);
  sequencing RULED = TWO Opus 5 sessions, D then E; execution PENDING):**
  • (1) alert display floor + within-tier ordering by PROVIDER facts — YES: floor = GDACS
    orange/red OR USGS band strong/major (M≥6), labelled as BANDS never urgency (the
    `_hazard_tier` no-promotion rule untouched); floor + cap ride the Settings→Cards tunable
    grammar with stated safe ranges.
  • (2) per-major-event CARDS in the strip AND the `severity_alerts` producer BOTH KEPT.
  • (3) cross-provider same-event GROUPING — YES (conservative: same type + <0.5° + <2 h; both
    providers listed; labelled a deduced grouping; DISPLAY-layer only, records stay 1:1 per
    provider event id; NO aftershock clustering).
  • (4) map: "Major only" filter ON BY DEFAULT (one click back to full recall — a default lens,
    never an exclusion, stated) + a hazard-TYPE filter + the LABELLING FIX: every hazard render
    incl. the map signal detail states the hazard TYPE IN WORDS ("Earthquake · M6.8") ×12 — a
    new user cannot deduce it from the glyph today (maintainer-reported).
  • (5)(6) Home "Overview" default lens = TOP-1 card per family by the SAME live disclosed order
    (bucket priority → order_key), each with the visible `explain_order` "why this card"
    (restores the transparency surface the Settings restructure deleted).
  • (7)=a: a compact Trending row folds INTO Overview; Most-recent · Latest · By-channel become
    subtabs beside the families; glance strip + alerts stay pinned.
  • (8) the top-8 flattened carousel is RETIRED into Overview (absorption-gated).
  • (9) Library subtabs = Overview · Activity · Tracked (Wikipedia+Law) · Database & storage ·
    World coverage.
  • (10) axis-honesty checklist CONFIRMED + a STANDING maintainer wish recorded: DIVERSIFY the
    app's data-visualization vocabulary ("too little data visualization creativity") — first
    activations ride Session D §5 (ingest calendar heatmap · qualification/length histograms ·
    corpus-delta slope chart · per-language small multiples · waffle composition), drawing on
    the ZERO-call-site ooviz primitives, composing with (never duplicating) the 2026-07-28
    GUI-audit brief's V-1/V-2/V-4; TWO new toolkit gripes found this session join the pass:
    dashChartSvg paints NEUTRAL count series in market green/red (up=good semantics fabricated
    onto neutral metrics → `opts.neutral`) and library tiles pass `unit=""` (axis unit absent).
  • (11) the maintainer will save FULL-DOM HTML exports (preferred over PDF) of every needed
    page/subtab after the fixes — the verification channel (feeds 0.3 gate row 8).
  • (12) master toggle = the COORDINATOR (option a): enabled sweeps round-robin; vLLM handled
    OPTIMALLY (concurrent member batches up to `concurrency_for` on vLLM; strictly serial on
    Ollama).
  • (13) interactive user actions stay OUTSIDE the toggle; RULED: a user-initiated BATCH (bulk
    translate/summarize, a manual sweep run) PAUSES the background coordinator (cursors
    persist) with a VISIBLE notice + auto-resume — user work preempts background work; heed the
    2026-07-24 exclusive-hold lesson (EVERY background-AI entry point checks the SAME hold).
  • (14) bench task list CONFIRMED (perception harness · frozen triage batch + ~50 graded
    anchors · source-tag validity+canaries · langdetect known-sample · llm_bench latency) —
    every metric ALONE, persisted side-by-side + downloadable logs for the
    ai-proposed→claude-verified→maintainer-merged chain.
  • (15) roster = ministral-3:8b (default) · ministral-3:3b · mistral:7b · gemma4 LATEST (per
    the ruled 7-model roster's gemma4:e4b — re-verify the current tag) · qwen3.5:4b (a
    ruled-roster member the maintainer doubts — the BENCH is the instrument that answers the
    doubt) · the LiquidAI LFM candidate (exact tag/HF repo verified LIVE, REFUSED if absent) ·
    optionally granite4.1; the bench runs each model on BOTH backends where available —
    Ollama-vs-vLLM is itself a RULED comparison axis (artifacts labelled
    model+backend+quantization, never conflated).
  • (16) MULTI-MODEL CONSTRAINED (maintainer): ONE model default for everything; a
    several-models configuration is admissible ONLY when co-fit in 7–8 GB VRAM is VERIFIED (a
    co-fit check gates saving it); the coordinator groups work BY MODEL to minimise load/unload
    churn. CONTEXT MANAGEMENT (maintainer asked "help us choose" → recommendation ADOPTED as
    the revertible default): size num_ctx to the MEASURED ~p95 article length (the shipped
    article_length diagnostic + a STATED chars→tokens estimate) — NOT max-context-for-all
    (KV-cache taxes every call + vLLM concurrency); build the missing OLLAMA num_ctx auto-tune
    (the documented B7 gap) beside the existing vLLM `compute_server_args`; BACKGROUND sweeps
    HEAD-TRUNCATE over-budget articles WITH DISCLOSURE recorded in provenance ("analyzed first
    N of M chars"); USER-driven summarize/translate NEVER silently truncate — CHUNKED
    map-reduce (translation = paragraph-boundary chunks concatenated, labelled "translated in N
    parts"; summary = hierarchical chunk-then-combine, labelled) with the method VISIBLE ×12.
  • (17) TWO sessions RULED: D (Home alerts + Overview + Library + the axis-honesty pass) then
    E (AI coordinator + bench + context management).
  **SESSION D EXECUTED 2026-08-01 (branch `claude/oos-optimization-planning-iawlbj`; S1–S5 all
  shipped, five `docs/ledger/shipped.csv` rows; every frontend slice BROWSER-UNVERIFIED per
  fork-3/Q6a — the maintainer's full-DOM HTML exports (ruling 11) are the verification channel):**
  S1 the toolkit-wide axis-honesty pass (`honestTicks` replaces the `(max−min)||1` span fallback in
  BOTH renderers) · S2 the alert selection layer (ordering + display floor + cross-provider
  grouping + type-in-words; `_hazard_tier` byte-untouched) · S3 Home Overview as the default lens
  with `explain_order` finally rendered, panels as subtabs, carousel retired · S4 the Library
  five-view restructure with select-time loaders + a view-aware poller · S5 the ingest-rhythm
  heatmap. Baseline-diffed at every slice: ZERO introduced failures (7 environmental failures both
  sides), i18n 100 % throughout (~38 new keys ×12), ruff clean.
  **SESSION D §5 CONTINUED 2026-08-02 — the recon found a DEFECT worth more than another chart.**
  SHIPPED: **honest gaps in the ONE chart toolkit** (shipped.csv row "ui/charts") — both renderers
  bridged holes, so a period nothing was recorded rendered as a smooth line; live-reachable on
  Library metric history (app off = a real gap), commodity prices on a shared axis, and
  official-statistics indicators. Two lessons recorded above (the `isFinite(null)` trap; the
  `ooViz` casing that made a wired subsystem look dead).
  **THE OTHER FOUR §5 CANDIDATES NOW HAVE EVIDENCE, not a wish-list (6-agent read-only recon +
  adversarial critique, every load-bearing claim hand-re-verified against the tree):**
  • **article-length histogram — BUILD-WITH-CAVEATS, the only one clearly worth building.** The
    data is real, exact and already binned (`article_length_report`), and is surfaced NOWHERE.
    But: it needs a NEW fetch that is a full `articles` scan with no route guard, so it must sit
    behind an explicit action, never a tab-select autoload; the corpus-wide summary and every
    `by_content_type` summary silently POOL zh/ja/th with Latin text, so the primary chart must be
    built from the `by_language` entries with `unsegmented === false` and state the excluded n;
    the report applies NO quarantine filter, unlike every other analytics path; the buckets are
    UNEQUAL width, so it is a categorical bar chart over labelled ranges, never a density
    histogram; and an n==0 summary returns all-None percentiles with an all-zero histogram, which
    renders as a fabricated spike unless branched on explicitly.
  • **qualification histogram — BLOCKED-NO-DATA.** All four candidate distributions fail on their
    own terms: age-since-qualified is dominated by a MIGRATION BACKFILL artifact (the backfill
    writes no attempt row, which is also the discriminator if it is ever drawn);
    attempts-before-verdict is right-censored and degenerate by construction; articles-per-source
    is ~90 % a single zero bin; and the only genuinely histogram-shaped data (per-source
    extraction-validity rates) comes from an endpoint MEASURED to time out at target scale.
  • **per-language small multiples — BLOCKED-NO-DATA as a frontend slice, but the highest-value
    candidate IF the feed is built.** The RENDERER already ships (`smallMultiplesSvg`, on
    `ooViz.gridLayout`); what is missing is data. There is NO per-language series anywhere —
    every per-language `group_by` in the tree is a single point-in-time snapshot and
    `KeywordMention` has no language column, so the cheap mention-side trend path is closed too.
    Labelling it "build-with-caveats" on the strength of a feed that does not exist invites
    someone to start drawing, so the verdict maps to the bar actually tested. WHY IT IS STILL
    the one worth building next: `language_equilibrium` is a LIVE scheduler lever on a strongly
    non-Anglophone corpus, and an operator tuning it has ZERO feedback surface — "which languages
    is my corpus actually growing in" is mission-central and currently unanswerable. Building it
    means a new snapshot metric family (unbounded cardinality — a real design decision), and
    asserted vs deduced language must not be pooled, or a deduced value carries an asserted
    one's visual weight.
  • **corpus-delta slope chart — the slope RENDERER ALREADY SHIPS** (`slopeChartSvg`). Three
    defects were LIVE-REPRODUCED against the real primitive: a zero "before" yields `Infinity`,
    which `isMissing` does not catch, and one affected dimension destroys the whole chart; raw
    values on one shared axis falsify `slopeGeometry`'s own documented honesty premise, while
    indexing to 100 MOVES the fabricated comparability rather than removing it; and the
    framework's own prescription (a panel per dimension) renders every panel as an identical
    diagonal, which makes a +5-on-40,000 look exactly like a doubling.
  • **waffle composition — REFUSED as decoration, but it surfaced a REAL gap and a REAL defect.**
    The framework never mentions a waffle (zero occurrences of waffle/isotype/pictogram/unit-chart
    across all five files); its part-to-whole prescription is sorted bars or a single stacked bar,
    pie/donut only at ≤5 slices — which is exactly what `ooDonut` already does. Recorded as a
    FINDING, per the framework's own rule that a rejected technique is a finding, not a gap.
    THE GAP UNDERNEATH IS REAL though: the channel chip row shows count with no total and no
    shares, and the framework-preferred form is **already shipped** as `_ooShareBars`
    (`app.js:8564`, currently ooDonut's own >5-slice fallback) — so it is one line of wiring, with
    none of a waffle's apportionment, largest-remainder tie-breaking or vanishing-sub-one-cell
    problems. RESOLVED DIFFERENTLY AND SHIPPED in the same PR: the shares went to the CHIPS (which are clickable, and `_ooShareBars` rows are not — replacing them would have lost the
    open-the-corpus tool), with the denominator stated and a sub-0.5% channel reading "<1%". **AND THE DEFECT, found by the adversarial honesty pass and hand-verified, FIXED in
    the same PR:** `source_type_facets` applied NO quarantine filter while `_query_articles`
    applies `Article.quarantined.isnot(True)` ALWAYS — yet the facet's own docstring stated "the
    facet count for a channel EQUALS what clicking it in /api/articles returns". That equality was
    a stated PROPERTY and it was false on any corpus with quarantined articles. Quiet in a chip
    label; a fabricated total the moment anything encodes one article as one countable unit —
    which is precisely how the waffle proposal exposed it. (Same family as the standing quarantine
    remainder: omnibar/watches/reporting/framing are still ungated.)
  **ALSO STILL REMAINING from Session D:** the §1.9 sparse-rule reach DECISION for
  `ringDumbbellSvg`/`commodityOverlaySvg` (flagged, not decided); and the maintainer click-through
  /HTML exports for every slice above.
  **THREE REUSABLE LESSONS FROM SESSION D (also in the Session-rituals Lessons list):** (a) a node
  test that EXTRACTS a function from `app.js` must start brace-matching at the BODY brace, not the
  first brace — `function ooChart(el, seriesList, opts = {})` carries a `{}` in a default
  parameter, so naive matching truncates the body to nothing and every source-level guard over it
  passes VACUOUSLY; (b) `test_commodities_category_subtabs` was passing by ACCIDENT — its
  whole-file `'{initial: "__all"}'` assertion matched the HOME families call site, never the
  commodities one, so a test named for one surface asserted nothing about it: a whole-file
  substring assertion is only as meaningful as that string's uniqueness, and a test scoped to a
  surface must slice to it; (c) when a payload string is itself an i18n KEY (the server-emitted
  `ALERT_CAVEAT`), EXTENDING that string silently breaks its ×12 translation — re-key by
  preserving each locale's existing translation and appending the new sentences, never by adding a
  second key and orphaning the first.
  **SESSION E EXECUTED 2026-08-02 (same branch, rebased onto the merged vLLM download fix; S1–S5
  all shipped, five `docs/ledger/shipped.csv` rows; every frontend slice BROWSER-UNVERIFIED per
  fork-3/Q6a):** S1 the Background-AI COORDINATOR (one lane, enabled sweeps round-robin, vLLM
  turns may overlap / Ollama serial; a user batch takes an EXCLUSIVE HOLD checked by EVERY
  background-AI entry point per the 2026-07-24 lesson; hardware-aware default OFF when the
  verdict is unreadable) · S2 the COMPARATIVE BENCH over inputs frozen ONCE (batch digest on
  every report; a resume across a changed digest REFUSED; five reused instruments; every metric
  alone, no winner column; a missing roster tag reported not substituted; the LiquidAI candidate
  a note, not an invented tag) · S3 the PER-FIELD perception gate + the per-LABEL langdetect gate
  · S4 CONTEXT MANAGEMENT (the B7 Ollama `num_ctx` gap closed as a PROPOSAL; user-driven
  summarize/translate chunked instead of silently cut) · S5 the two orphan capabilities wired.
  **THE ASYMMETRY WORTH REMEMBERING (S3):** a gate that LICENSES must refuse the unmeasured
  (running there would be unmeasured work); a gate that VETOES must NOT (langdetect has run
  default-on over every language the model can name since B15, and the gold set covers thirteen —
  refusing every unmeasured label would disable detection for languages nobody TESTED rather than
  for languages that FAILED). Both are the conservative choice in their own context; swapping
  them would be invisible in a diff, so both directions are pinned in both suites.
  **REMAINING from Session E (honest board):** the bench's actual ROSTER RUN + the ~50-anchor
  grading sitting are OPERATOR steps on the model rig (the machinery is here; the numbers are
  not, and none are fabricated) — the LiquidAI tag must be verified LIVE there and REFUSED if
  absent; the triage/source-tag per-language gates are computed and SHOWN but not applied at
  selection (both sweeps are export-only JSONL a human reviews — a deliberate boundary, not an
  omission); ruling 16's per-task MODEL SELECTION with the 7–8 GB VRAM co-fit check is NOT built
  (the coordinator groups by model implicitly, one member at a time, but a several-models config
  and its co-fit gate are a separate slice); and the maintainer click-through/HTML exports for
  every frontend slice above.
  **BENCH-ROSTER INSTALL BUTTONS SHIPPED 2026-08-02 (maintainer ask; PR #844, shipped.csv rows
  "llm/bench"): a tickbox panel beside BOTH install controls**, each naming and posting the
  backend it renders (a click under the vLLM heading can never install Ollama tags — the
  routing-vs-provisioning confusion that shipped a field bug two days earlier). Identifiers came
  from a live acquisition run; `BENCH_ROSTER_AS_OF` is registered. **THE LFM2.5 RULING
  (maintainer, same day, after the recommendation): ADD the Instruct row, KEEP Base, never
  substitute.** Rationale worth preserving: four of the bench's five tasks
  (`model_bench.BENCH_TASKS` — perception · triage · source_tags · langdetect) are
  CONSTRAINED-OUTPUT instruct tasks, so a base checkpoint yields one usable metric (latency) out
  of five plus four near-zeros that mean "wrong tool", not "bad model" — and a near-zero with no
  memory of why is the number that gets misread later. Base stays as the row that was asked for,
  unticked behind `base_model`; Instruct is an ADDITION, not a replacement (both pinned by a
  regression test against a future tidy-up that would collapse them). **NEW SCHEMA RULE, worth
  reusing:** every identifier block carries `verification: "fetched" | "search-verified"` with
  **NO DEFAULT** — a missing tier raises, because a default would silently claim the STRONGER
  tier for whoever forgot to think about it, which inverts the point of an honesty field. Exactly
  one row is `search-verified` today (the Instruct repo id — the run NAMED it, no page fetch was
  recorded), and a test pins that set so the module docstring's "almost every" can never drift
  from the data. **STILL OPERATOR-GATED (one lookup, recorded as an `open_question` in the row and
  rendered in the panel): is the Ollama account `LiquidAI` the publisher's own?** If yes,
  `LiquidAI/lfm2.5-1.2b-instruct` is a FIRST-PARTY tag and that absence disappears; if somebody
  took the name, it stands. Deliberately NOT resolved by guessing — and note this is a different
  provenance claim from the SmolLM3 community re-uploads rejected for having no known builder.
  `library/lfm2.5-thinking` is first-party and the right size but is NOT offered under the
  Instruct name: a Thinking variant's reasoning traces fail format validity on three of the four
  constrained-output tasks, which is a finding about reasoning models, not a LiquidAI measurement.
  **TWO REUSABLE LESSONS FROM SESSION E (also in the Session-rituals Lessons list):** (a)
  `re.split` CONSUMES its separator, so splitting on `(?<=[.!?])\s+` silently drops the space
  between every sentence — a translation reassembled from those pieces comes back subtly wrong
  and NOTHING but an exact-coverage property test would find it; split at `m.end()` instead, and
  assert `"".join(parts) == text` rather than merely that the parts look right; (b) a
  VALUE-BEARING provenance string must be parsed defensively before it is extended —
  `prompt_version` stores the translation target after a colon (`translate-v2:French`), so
  appending a method suffix would have printed the target as "French+chunked-3"; the parser
  strips the suffix AND the writer drops its own note rather than let a `String(50)` truncation
  cut into the language (losing a method note beats corrupting a value).
- **THE BULLETIN — PERIODIC CORPUS DOCUMENT (maintainer design conversation 2026-07-30/31; 16
  numbered decisions ANSWERED 2026-07-31; DESIGN ONLY, nothing built; record of record =
  [`docs/design/BULLETIN_DESIGN_2026-07-31.md`](docs/design/BULLETIN_DESIGN_2026-07-31.md),
  code-verified against `main`@0d76fac by a 13-agent verify+critique pass then a second 8-agent
  mechanics pass, every load-bearing claim hand-re-verified):** a periodic (daily → yearly)
  document generated from the corpus with numbered citations, deterministic first, with an
  optional removable local-LLM narration layer, plus an owner-only evidence ZIP.
  **THE RULINGS:** (1) NAME = **Bulletin**, chosen so "Synthesis" keeps its existing meaning
  (the shipped selection tool) and NOTHING existing is renamed — and because "AI summary" would
  mislabel a deterministic-first artifact whose narration is off below the hardware gate.
  (2) **THE WHOLE FEATURE IS GATED ON AI-CAPABLE HARDWARE** via the existing
  `inference_capability()` (`src/llm/backend.py:258`) — NOT `detect_gpu()` (the two-predicate
  invariant holds; hardware policy never enters `detect_gpu()`); the standing
  `llm_allow_impractical_hw` override still reveals it (never a hard block). Deliberately
  STRICTER than ruling 15's warning tier, justified by workload shape: ruling 15 covers
  interactive one-off inference, the Bulletin's narration is thousands of calls. RECORDED
  CONSEQUENCE: Layer A is pure SQL and would run anywhere, so gating the whole feature denies a
  GPU-less operator even the deterministic document — implemented as instructed, reversible in
  one condition (open question 4). (3) WINDOW RULE: **the rising RECENT window EQUALS the
  coverage window; baseline is a multiple**. The proposed fraction-of-period ratios were
  REFUTED with a worked example — a story peaking on day 2 sits in its own baseline and reads as
  FALLING (growth 0.17) in the edition covering its own week, and 6/7 of corpus time never
  contributes to any rising signal. Defaults ARE the shipped `_TREND_WINDOWS` for daily/weekly/
  monthly (1/7, 7/30, 30/90), extended 3× for trimester/semester/yearly; operator-editable.
  (4) **HOURLY IS BLOCKED, not tweakable** — `KeywordMention.observed_on` is a `Date` and the
  time is destroyed at write (`store.py:285`); `created_at` is unusable because re-index
  delete-then-reinserts every row stamped `now()` (`store.py:306`). Daily is the floor cadence.
  (5) date convention = `coalesce(published_at, created_at)` app-wide for the edition.
  (6) CONTENT ANCHORING addressed frontally: extractive floor → cached analyses → narration over
  REAL article text; **stage 2 (When/Where/Who) already exists complete and eval-gated in
  `src/ai_layer/perception.py` — reuse, do not rebuild**; the proposed per-article "confirm
  keywords" stage is deliberately NOT built (the rule-based index is the trusted layer); no
  cascade — narration reads text directly, extracted facts are hints only. (7) the AI volume
  setting is a **TIME BUDGET, not a count** (there is NO recorded per-call latency in the repo —
  measuring is build step 5); deterministic counts stay exact and uncapped, only narration is
  sampled. (8) TRUSTWORTHINESS = mechanical support-checking (language-agnostic) + human grading
  ONLY in languages the operator reads + a **tri-state** per-language gate on the
  `gate_languages_from_report` pattern, where "never evaluated" is epistemic and still REFUSES.
  (9) story-cluster unit + metrics appendix. (10) temperature selectable on BOTH backends —
  `options` is silently ignored on vLLM (`vllm_client.py:142`), a real determinism bug.
  (11) TWO EXITS, ONE RECORD: the edition JSON rides the encrypted backup free (register in
  `artifact.py::_collect_members`, the import-reports pattern); the evidence ZIP is a separate
  on-demand export (plaintext leaving the encrypted store — disclosed, not assumed); + TOC +
  `20260731-OOS-…` naming. (12) published artifact carries EXTERNAL links only — a local reader
  link resolves to a DIFFERENT article on a recipient's install. (13) delivery = download
  primary, short digest for paste (Gmail clips ~102 KB and eats the reference list; Gecko
  `ClipboardItem` support is weaker and Gecko is the verification bar). (14) mandatory masthead
  (contributing sources, top-3 share, language split, days-with-ingest, selection math),
  operator-tweakable. (15) **CONTINUOUS IMPROVEMENT (maintainer-clarified, app-wide posture, not
  cards-only):** iterative improve→audit→improve, pharma-style. The prerequisite is ALREADY
  BUILT — `src/briefing/card_audit.py` (1,891 lines, merged 2026-07-30) implements the proposed
  per-card fact-bundle auditor including `observe_producers`, which closes the ok/no-signal/error
  conflation the draft called "the gap that matters most". MISSING = three small instruments: a
  determinism check (run twice, diff), persisted audit runs, and an audit-to-audit diff —
  **`scripts/kpi_diff.py` already has that exact shape** (`classify`/`diff_snapshots`), just not
  pointed at card audits; register in `src/monitoring/recursive_loop.py`. (16) placement = a
  FOLDED section at the BOTTOM of Advanced (NOT a new subtab: there are **12** subtabs now, not
  the draft's 18, heading to a ruled 10). (17) producers are NOT pre-classified — each prints its
  REAL window and gets a per-producer TOGGLE in the review screen, so classification falls out of
  observed content.
  **A REAL SHIPPED BUG FOUND WHILE VERIFYING (independent of this feature, own reviewed slice):**
  `trending()`'s recent window is `[today−N, today+1)` = **N+1 days** (`queries.py:1361`) while
  `expected` scales the rate to **N** days (`:1370`), inflating growth by (N+1)/N — **2× on the
  shipped "Past 24h" preset**, drifting through the day since today is partial. The same `+1`
  CANCELS in `supergroup_rising.py:180` / `concentration.py:64` (same-window share tests) but not
  here. Unnoticed because tests place fixtures inside windows and never assert width.
  **THREE FURTHER CORRECTIONS to the earlier draft, all verified:** Layer A can NOT live in the
  housekeeping lane (the lane is refused wholesale under airplane, `runner.py:1684`, contradicting
  "Layer A is airplane-safe"); analytics has **zero** `quarantined` references
  (`queries/store/rollup_serve/columnar`), so every keyword aggregate currently counts quarantined
  articles; and `_window_filter` (`:1659-1665`) is INCLUSIVE (`<= end`) while `_counts` (`:1341`)
  is half-open — two conventions in one file, so consecutive periods double-count the boundary day.
  **BUILD ORDER (§21):** trending fix → vLLM temperature → the three continuous-improvement
  instruments + cycles → explicit `start`/`end` windows on the three aggregates → measure LLM
  latency → Layer A → persistence/backup/ZIP → Layer B → UI. Steps 1–3 are worth doing whether or
  not the Bulletin is built. FIVE OPEN QUESTIONS remain in §20 (section list · introduction · mail
  sending · whether Layer A should be available below the hardware gate · review-screen UX).
  **STATUS 2026-08-01: THE WHOLE BUILD ORDER (§21 steps 1–9) IS SHIPPED.** Steps 1–5 = PRs #819
  trending off-by-one · #820 vLLM sampling options · #822 audit-to-audit diff · #823 explicit
  period windows · #824 LLM latency bench. Step 6 Layer A = #825 (period arithmetic · hardware
  gate · masthead · disclosures · `rising_concepts`) + #826 (the §11 section registry: across
  channels · by topic tag · changes of record · alerts · `through_time`). Steps 7–9 = #827
  persistence + backup ride-along · #828 the owner-only evidence ZIP · #829 story clusters +
  the grounding check · #830 Layer B narration · #831 the renders · #832 review/publish + the
  §16 Settings section. Per-PR detail = the 2026-07-31 and 2026-08-01 `docs/ledger/shipped.csv`
  rows. **OPEN QUESTION 4 is ONE CONSTANT with exactly ONE read**
  (`src/bulletin/gate.py:LAYER_A_REQUIRES_CAPABLE_HARDWARE`, pinned by a test that counts the
  reads): answering it is a one-line change, not an audit. THE OTHER FOUR §20 QUESTIONS
  (section list · introduction · mail sending · review-screen UX) are still open, and the
  review screen shipped as one reading of the last of them — a checkbox-per-section/story
  screen with per-sentence verdicts, not a ruled design.
  **REMAINING, honestly:** a maintainer CLICK-THROUGH of the Settings section and review screen
  (every frontend slice in the stack is browser-unverified per fork-3/Q6a) · the §14 Layer-B
  `BackgroundJob` with a persisted cursor (narration currently runs inline inside the generate
  request, which is fine for a bounded story cap and wrong for a long run) · §18's
  export-privacy enumeration before the first evidence ZIP leaves a machine. TWO OPERATOR STEPS
  carried forward: run `/llm-bench` on the GPU machine and on a slow one so the §6.3 time budget
  rests on measurements rather than a guess; and run the continuous-improvement cycles (§15's
  remaining half is *running* them, not building them).
- **SETTINGS-TAB REVIEW 2026-07-31 — 15 SUBTABS → 10, A NEW CARDS TAB, A NEW ADVANCED TAB
  (maintainer reviewed every Settings subtab and gave per-subtab remarks; 23 follow-up questions
  put and ANSWERED the same day; PLANNING ONLY this session, code-verified against `main`@b5bc6b6;
  brief of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-31_SETTINGS_RESTRUCTURE.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-31_SETTINGS_RESTRUCTURE.md)
  — 8-PR stack, per-PR specs, anchors, test-breakage table; NOTHING BUILT):**
  **TARGET:** `Graphics · General · Cards(new) · AI · Wikipedia(untouched) · OpenStreetMap(renamed)
  · Agenda · Data & backup · Safety · Advanced(new)`. REMOVED: Shortcuts (→General), Leads
  (deleted), Collect (→Advanced), Sources (→Advanced), Newsletters (→Data & backup), Keywords
  (→Advanced), Statistics (split: producers→Advanced, the rest→a NEW Governments>Statistics
  subtab). `Advanced` = foldable, folded-by-default sections, and **folded must not mean fetched**
  (its loaders fire on section EXPAND, not subtab select — the source catalog can hold ~46k rows).
  **THE 18 RULINGS:** (1) Cards grouped by FAMILY, ALL 8 families accessible + tweakable, (2)
  `overtold` built end-to-end FIRST as the reusable pattern, (3) every tunable carries a documented
  min/max SAFE RANGE stated visibly — never a silent clamp, (4) the text-size slider is REMOVED
  (rely on browser zoom), (5) the P0 validation STAYS untouched ("I'll run it on the big corpus" —
  keeps 0.3 close-gate rows 4+7 runnable), (6) the page-size bench is REMOVED ENTIRELY (panel +
  module + endpoints + bundle member + ratchet + tests), (7) legacy restore REMOVED entirely
  frontend+backend (the maintainer has already merged their pre-volumes backups), (8) the "Older
  backup tool" raw-.db snapshot REMOVED entirely, (9) statistics sources register ENABLED and
  CRAWLABLE by default + a NEW per-agency `news_url`, (10) Agenda gets NO new fetch behaviour —
  remove the manual buttons, surface the existing automation, (11) feed verification becomes
  PROGRESSIVE riding collect passes (NEVER boot — airplane/zero-network) and VISIBLE in the task
  manager, (12) dysfunctional calendar feeds get automated re-check MIRRORING the source ladder
  (1→2→4→6 months capped, append-only attempts, bounded per-pass) — never a permanent exclusion,
  (13) the Keywords subtab is REMOVED, (14) TRANSLATE the 4 user-facing PROSE prompt bodies ×12,
  (15) the hardware gate is REFINED (below), (16) a STACK of draft PRs merged progressively, each
  appending its own shipped.csv row with a REBASE after every merge (append-at-EOF conflicts
  otherwise), (17) the 3 existing recipe toggles keep their exact behaviour but get a MODERNIZED
  UI, (18) Wikipedia is NOT touched — record in FUTURE_DEVELOPMENTS that Wikipedia should be a
  source like any other journal, differing only by a tracked audit trail (check first whether the
  existing "Versioned sources as first-class Articles" section already says this — EXTEND, never
  duplicate).
  **⚠ TWO RULINGS SUPERSEDE EARLIER ONES — do NOT re-litigate them as regressions:**
  **(a) RULING 14 partially supersedes the 2026-06-21 prompt finding.** That finding ("the tuned
  ENGLISH prompt BODY is KEPT — translating multi-sentence instructions ×12 risks DEGRADING a weak
  model's compliance; forcing the OUTPUT language via `_NATIVE_DIRECTIVE` is the reliable win") now
  governs ONLY the machine-parsed half. The 4 USER-FACING PROSE prompts (summary · translate ·
  synthesis · ai-keywords) ARE translated ×12 — maintainer rationale: "our small model speaks ~30
  languages, our 12 languages will be well covered, and we don't want a non-english user to have
  the AI create some english work; AI work is marked unreliable everywhere, it's OK." The ~10
  `ai_layer` prompts (triage · source_tags · qualification_assist · perception · langdetect ·
  extract) STAY ENGLISH BY CONSTRUCTION: their parsers validate against English tokens (a single
  word, an exact echo-back of a term, a fixed label vocabulary, a language code) and they produce
  NOTHING a user reads — translating them breaks parsing without improving any output.
  **(b) RULING 15 supersedes the 2026-07-30 GPU-absence rule.** That rule refused local inference
  wherever a dedicated GPU was absent, explicitly including "a 64 GB GPU-less workstation". NOW:
  the HARD refusal tier is **< 4 CPU cores OR < 6 GB RAM**; **GPU-less is a WARNING, not a
  refusal** (a GPU-less ≥4-core/≥6 GB machine defaults ON with the warning stated); **< 5 GB VRAM
  is a WARNING** — set at 5 not 6 because Mistral-7B Q4 needs ~4.4 GB and measured 5.1 GB, so a
  6 GB line would warn on cards that genuinely work. The Apple-Silicon carve-out, the override
  toggle, and the NEVER-A-HARD-BLOCK posture are UNCHANGED. **The two-predicate invariant STILL
  HOLDS and is the thing most likely to be broken by this edit:** `detect_gpu()` answers "can vLLM
  run HERE?" and `inference_capability()` answers "is local inference PRACTICAL?" — the new CPU/RAM
  floor belongs in `inference_capability()` ONLY; `tests/test_inference_hardware_gate.py`'s ast
  guard forbids OS/arch/hardware POLICY entering `detect_gpu()`'s body (vLLM ships manylinux wheels
  only and cannot serve Apple Metal, so collapsing the two predicates routes every Mac to a vLLM
  that cannot run).
  **⚠ ONE JUDGEMENT CALL MADE WHILE BUILDING RULING 15 (PR-8, 2026-07-31) — maintainer correction
  welcome, it is the single place this reading could differ:** the ruling calls the Apple-Silicon
  carve-out "UNCHANGED" while ALSO stating that the hard-refusal tier IS the CPU/RAM floor. Those
  two halves conflict for a sub-16 GB Mac, so the build resolved it as: the RECOGNITION is
  unchanged (Apple Silicon still counts as an accelerator despite having no NVIDIA GPU) and the
  16 GB line became a WARNING threshold exactly like the new VRAM one. RATIONALE: a second, HIGHER
  hard floor for Apple Silicon alone would contradict the ruling's own statement of what the hard
  tier is, AND would refuse an 8 GB M-series Mac while passing a 4-core/6 GB GPU-less PC — treating
  the carve-out's own hardware WORSE than the machines it exists to favour. The floor CONSTANT is
  still reported in the payload, so only its tier changed. Recorded in the function docstring and
  pinned with its reasoning in `test_apple_silicon_below_the_unified_ram_floor_is_practical_and_warns`.
  **A REAL DEFECT CAUGHT PRE-PUSH, worth keeping because the shape recurs:** the first cut applied
  the CPU/RAM floor BEFORE the GPU/Apple probes, and `total_ram_gb()` returns `None` on a core
  install (psutil is an optional `[analysis]` dep) — so it refused local inference on EVERY machine
  INCLUDING one with a perfectly good NVIDIA GPU, because RAM could not be counted. A detected
  accelerator is POSITIVE EVIDENCE and must never be refused for want of a measurement; the floor
  is decisive only in the CPU-only case, where nothing else vouches for the machine.
  **VERIFIED FACTS THAT CHANGED THE PLAN (read from the tree — do not re-derive):** the text-size
  slider CANNOT work (`applyUi` scales the root correctly, but app.css has 103 `px` font-sizes and
  ZERO `rem`, `body{font-size:15px}`, + 46 inline `px` in index.html — the root scale reaches
  nothing; the maintainer declined the ~149-site `px`→`rem` migration, hence ruling 4) · there are
  **39 card producers** (35 `_DEFAULT_PRODUCERS` + 4 `RECIPE_PRODUCERS`), not the 3 the UI exposes,
  and only the 4 recipe producers consult ANY persisted flag (`recipes_disabled`) — the other 35
  have no per-producer persistence and their thresholds are module constants / inline literals ·
  calendar auto-import ALREADY rides every online collect pass default-on (8 feeds/pass, 12 h
  gate, robots-dead skipped) so ruling 10's ask is visibility, not fetching · the Agenda contrast
  bug is `.ag-cal`'s `opacity:.6` compounding `var(--muted)`, which is why it fails in BOTH light
  and dark · the `statistics` TAG is ALREADY auto-implied via `CLASS_IMPLIED_TAGS` (that half of
  ruling 9 is done) · statistics agencies carry `home_url` only and `crawl_source` starts at
  `https://{domain}`, so enabling them would crawl DATASET PORTALS — hence the `news_url` field ·
  crawl-by-default SHIPPED (`crawl_supplement=True`, `crawl_per_pass=3`) so "enabled" for a
  feedless source is NOT cosmetic · legacy restore is ALREADY absorbed by the unified Import
  ("there is exactly one legacy-restore code path in the app") · **`#ux-export` lives INSIDE
  `#set-data` and set-views are `display:none`, so `showModal()` will NOT render it from another
  subtab — the dialog markup must move to top level** · "Typeface" IS currently keyed so the
  "Fonts" rename REGRESSES a translation unless the key is added ×12 ("OpenStreetMap" needs no key
  — proper noun, English fallback is correct everywhere) · DB-10 §1b is already wired
  (`_FRESH_PAGE_SIZE = 16384`), which is what makes ruling 6 safe · `uninstallBackupFirst()` and
  `encryptedBackup()` share the SAME 2 GiB-capped endpoint, so "remove Encrypted backup" and
  "rewire Download a backup first" are ONE fix.
  **THE STALE-ANCHOR HAZARD (the brief carries the full table):** panel ids are used as SOURCE-
  SLICING DELIMITERS, so moving a panel breaks tests that are not about it —
  `test_repo_invariants.py:4636` slices the **Keywords** view using `id="set-leads"` as its END
  delimiter, and `:3015` slices between `set-wikipedia` and `set-agenda`. Also
  `test_repo_invariants.py:6452-6461` pins `<label class="sl" for="dr-font">` — an ACCESSIBILITY
  fix guarding the very slider ruling 4 removes: DELETE that test WITH a comment recording the
  ruling, or a future session reads the missing label as a regression and restores the dead
  slider. Do NOT touch `tests/test_sqlcipher.py`/`sqlcipher_helper.py` when removing the page-size
  bench — they exercise the `cipher_page_size` PRAGMA, not the bench.
  **STATUS 2026-07-31: THE 8-PR STACK IS COMPLETE** — PR-1..PR-7 merged (#811 #812 #813 #814 #815
  #816 #818), PR-8 pushed (the AI subtab: one hardware statement, one setup button, ruling 15's
  refined thresholds, ruling 14's four prompts ×12). Per-PR detail = the eight 2026-07-31
  `docs/ledger/shipped.csv` rows. Nothing in the 18 rulings is left unbuilt.
  **OPERATOR STEPS (maintainer, not the coding session):** run the P0 validation on the big corpus
  · the networked research pass filling `news_url` for ~150 statistics agencies (the law-batches
  pattern — never fabricate an endpoint) · a browser CLICK-THROUGH of all eight PRs (every
  frontend slice here is browser-unverified per fork-3/Q6a).
- **FIELD REMARKS 2026-07-29 — BACKUP-IMPORT SPEED + THE MULTI-IMPORT UI (maintainer; 20 rulings
  given the same day; INVESTIGATION + PLANNING ONLY this session, code-verified against `main` via
  a 10-agent read-only fan-out [7 recon + 3 adversarial skeptics, 0 errors]; brief of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-29_IMPORT_PERFORMANCE.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-29_IMPORT_PERFORMANCE.md);
  nothing built this session; the maintainer will execute it with Opus 5 + ultracode):** two
  remarks — a 50,000-article import quoting a ~4000-minute re-index ETA (and a further 3–5×
  slowdown when collecting concurrently), and a 6-backup folder import showing ONE shared progress
  bar with no per-item identity, no true rate, no pause, no stop.
  **ROOT CAUSES (ranked, each anchored):** (1) `_get_or_create_keyword` runs a fresh
  `session.query(Keyword).filter_by(normalized_term=…).first()` per kept term per article
  (`store.py:72`, called `:331`) — VERIFIED always a real round-trip (identity map short-circuits
  PK lookups only; `SessionLocal` is `autoflush=False`, `session.py:149`), so ~200 terms × 50k
  articles ≈ 10M index probes through the SQLCipher codec against a ~6.9M-row keywords table (the
  SHARE of wall time is NOT yet measured — that is what the instrumentation slice is for). (2) the
  restore re-indexes with ONE FSYNC PER ARTICLE: `volume_job.py:269-278` passes `reindex_workers`
  + `merge_cache_mb` but NEVER `reindex_commit_batch`, so `merge.py:1737` falls back to
  `OO_REINDEX_COMMIT_BATCH` default `"1"`. (3) **the 4000-minute figure is itself inflated — a real
  ETA bug**: `_uxPoll` captures `startMs` once per JOB (`app.js:5753`) while `view.frac` resets to
  ~0 when the phase flips merge→reindex, so `_uxRuleOfThree` (`:5669`) computes
  `(verify+reassemble+merge+reindex-so-far)×(1−f)/f` — an over-estimate of roughly 5–15× early in
  the phase. (4) the "import owns the machine" pause is REAL but bounded + leaky: it is wired only
  on the volume path (`volume_job.py:208`) and `_do_run` has NO mid-pass stop check (its own
  docstring, `runner.py:1915-1927`), so a pass already fetching runs to completion; worse, the
  per-backup loop RESUMES collection between every backup (`volume_job.py:284-290` in a `finally`),
  re-opening the race five times in a 6-backup run. (5) no engine-fingerprint skip (the manifest's
  `app_version` IS carried on `merge_batches`, `models.py:2159-2160`). UI half CONFIRMED point by
  point: `_uxImRun` (`app.js:6111-6190`) is a client-side sequential loop writing every kind into
  the SAME bar with only a constant `t("Corpus")` prefix; **pause/stop genuinely do not exist for
  imports** — `_run_restore` never reads `self._stop` (only `_run_backup` does, `:126`), so the
  endpoints are inert during a restore and any pause button today would be fabricated capability;
  a reload kills the client-side sequencing (`app.js:6196`); ten ids + a LITERAL source-substring
  anchor (`tests/test_unified_backup_ui.py:246`) pin the dialog.
  **THE 20 RULINGS:** (1) defer the re-index off the blocking import path — YES. (2) the re-index
  is AUTONOMOUS + VISIBLE, integrated in the backup UI **as the last backup stage** with its own
  progress; **articles not yet re-indexed must not be part of analytics**. (3) extraction
  FINGERPRINT in the manifest; a match skips the re-index. (4) a mismatch ⇒ FULL re-index. (5) the
  keyword-cache decision was deferred to a risk memo (answered — see below). (6) extend the cache
  to the COLLECTOR ingest path. (7) `commit_batch` ≈ 200 when the import owns the machine —
  approved. (8) WAL/checkpoint is NOT a user-facing surface; it belongs in all-diagnostics. (9)
  collector stop must be IMMEDIATE. (10) collection does NOT resume between backups — a
  multi-backup run is ONE import. (11) **legacy single-file imports are being REMOVED soon — do
  not invest in them** (removal recorded in FUTURE_DEVELOPMENTS). (12) the UI states that
  collection is paused for the import. (13) server-side import QUEUE confirmed — and it does NOT
  replace the remark-2 UI changes. (14) rate = the honest unit for the current phase + a cumulative
  line. (15) stop/abort is IMMEDIATE, losing the current import and everything related to it. (16)
  a "Show details" panel, persisting across a reload. (17) per-PHASE ETA + the number of remaining
  phases visible. (18) do the quick wins AND the architecture. (19) add the instrumentation. (20)
  the session runs on Opus 5 + ultracode.
  **⚠ RULING 2's PREMISE WAS REFUTED — ONE RE-DECISION IS OWED BEFORE BUILDING (brief §3):** merged
  articles are ALREADY fully present in analytics before any re-index — `_merge_keyword_mentions`
  copies the incoming corpus's `keyword_mentions` straight into the live DB during the merge
  (`merge.py:693`,`:726`), so the post-merge re-index is a REFRESH that overwrites them
  (`store.py:479-480`), never an admission gate. A per-article "pending" flag would therefore
  delete an entire imported corpus from analytics to fix bounded engine-version staleness — and
  imported corpora skew OLD, so that hits cross-time recall. It is also uncheap + inconsistency-
  prone: the hot corpus-wide `top_terms` reads ONLY the denormalised counters and never touches
  `Article` (`queries.py:300-317`); FIFTEEN further paths aggregate mentions without joining
  `Article` (`queries.py:334/254/1340/1763/1967/1005/436/2238/2325`, `columnar.py:802`,
  `rollup_serve.py`, `briefing/producers.py:494`); adding that join is the documented SQLCipher
  codec trap (`queries.py:1941-1946`); the `Article.quarantined` precedent appears in ZERO
  analytics files and already yields two disagreeing corpus totals (`main.py:951` vs
  `queries.py:2191`, the latter claiming "REAL, EXACT"); and a never-finished re-index would strand
  an arbitrary subset PERMANENTLY invisible (`store.py:506` stamps no per-article completion).
  **RECOMMENDED INSTEAD (option a): do NOT merge the derived rows — let the re-index PRODUCE them.**
  "Not yet re-indexed" then means "has no mentions", which every analytics path already honours
  STRUCTURALLY (no gate, no flag, no join, no 15-path sweep, no rollup problem; localised to the
  merge step tuple `merge.py:315-330`). It also serves the speed remark three ways: the merge stops
  writing the largest table (~10M rows for a 50k-article backup), the re-index stops
  delete-then-reinserting rows it is about to replace, and **it fixes the counter-drift bug below
  by construction**. HONEST COST, which makes ONE guard mandatory: an imported article then has NO
  keywords rather than STALE keywords until re-indexed ⇒ **a durable per-article re-index CURSOR is
  required** (resume exactly where it left off; surface its backlog at boot), else a bounded
  staleness is traded for an unbounded invisibility. Options (b) keep merging + DECLINE the
  exclusion, disclosing pending refreshes from `merged_rows` (the skeptic's own recommendation, on
  cross-time-recall grounds) and (c) the per-article flag as framed (NOT recommended) are recorded
  in the brief. **RULED 2026-07-29 (maintainer chose (a)): DO NOT MERGE THE DERIVED ROWS — the
  re-index PRODUCES them.** So the merge stops copying the incoming corpus's `keyword_mentions`
  (localised to the merge step tuple, `merge.py:315-330`), "not yet re-indexed" means "has no
  mentions" — which every analytics path already honours STRUCTURALLY, no flag/gate/join/15-path
  sweep — and the counter-drift bug is fixed by construction. THE MANDATORY GUARD travels with the
  ruling: a DURABLE per-article re-index CURSOR (resume exactly where it left off; surface its
  backlog at boot), because option (a) trades a bounded staleness for an UNBOUNDED invisibility if
  the re-index can be lost. Ruling 2's original per-article-flag framing is formally superseded (its
  premise was refuted — merged articles were already in analytics), and (b)/(c) are closed.
  **⚠ A PROBABLE REAL BUG FOUND WHILE ATTACKING IT (read-verified, NOT reproduced — reproducer
  FIRST, per the standing rule):** keyword counters never absorb a merged corpus. `_merge_keywords`'
  INSERT column list omits `mention_count`/`article_count` so new keywords land at 0 and existing
  ones are matched by `NOT EXISTS` and never updated (`merge.py:631`); NO `backfill_keyword_counters`
  call exists in the restore path (its only caller in the tree is `src/ingest/email.py:756`);
  `merge.py:2025-2027` explicitly reconciles `Source.article_count` for exactly this reason and does
  NOT do the same for keywords; and at re-index `old_contrib` is read from the LIVE mention rows —
  which after a merge ARE the imported rows (`store.py:294-301`) — so the re-index SUBTRACTS a
  contribution that was never added. `maybe_reconcile_counters` would eventually repair it
  (`scheduler/maintenance.py:83`) but requires the app ONLINE with the collector idle, so an
  airplane-first user who imports and browses offline sits on drifted counters indefinitely,
  undisclosed.
  **RULING 5 ANSWERED — the keyword cache is a NARROWED GO (brief §5).** The adversarial pass could
  NOT find the naive proposal safe: stale ids survive the rollback-then-redo fallbacks
  (`store.py:576/597/613/639`, `batch.py:260`, `pipeline.py:282`) and FK enforcement is ON
  (`session.py:101`, FK `models.py:1752`) so the bulk mention insert raises `IntegrityError`, which
  `is_locked_error` deliberately never retries (`write.py:95`) — destroying the no-loss guarantee
  `_redo_committed` exists to provide; the savepoint variant is SILENT (`batch.py:353-369` swallows
  non-lock errors); and it violates `run_write_with_retry`'s stated contract (`write.py:20`).
  STRUCTURALLY DECISIVE: **there is NO UNIQUE index on `keywords.normalized_term`** (`models.py:934`;
  baseline migration `unique=False`; `merge.py:614-617` calls the absence DELIBERATE), so a cache bug
  yields a SILENT DUPLICATE ROW, not an IntegrityError — the standard `except IntegrityError:
  re-SELECT` idiom CANNOT fire here. Also: the entity-upgrade branch MUTATES an existing row
  (`store.py:93-97`) so an id-only cache silently kills every upgrade with nothing failing loudly,
  and one `IN (…)` over a window's terms blows SQLite's ~999-variable ceiling. **THE NARROWED
  FORM:** warm the READ side only (bulk `SELECT` chunked ≤900 params) and leave the CREATE path
  exactly as-is (per-miss `add`+`flush`), which keeps `baseline_tags` (`:88-92`), first-write-wins
  `language` (`:78`) and the load-bearing flush (`:87`) byte-identical; cache `(id, is_entity)`;
  TRANSACTION-scoped, invalidated on `after_rollback` AND on nested rollback (`writer.py:275`'s
  parent-is-None discrimination must NOT be copied); deterministic `MIN(id)` tie-break for
  duplicate `normalized_term` (matching `merge.py:638`); re-index path FIRST, collector second.
  **EMPIRICALLY PROBE whether SQLAlchemy fires those events for SAVEPOINT rollbacks before
  building — it is the hinge of the whole guard; if not observable, scope the cache to the re-index
  path only.**
  **RULING 8 ANSWERED — WAL IS ALREADY IN ALL-DIAGNOSTICS (the staleness guard paid off):** WAL size
  in FOUR members (`storage.py:106`, `forensics.py:171`, `:353`, `:266`), `journal_size_limit` in
  `storage-composition.json` (`storage.py:96-97`, SQLite's -1 honestly normalised to None), and
  checkpoint-starvation evidence via BOTH a heuristic `wal_note` (`storage.py:107-112`) and a hard
  per-pass measurement from `checkpoint_wal()` (`hygiene.py:225-236`) persisted into
  `scheduler_runs.jsonl` and reaching the export at
  `debug-bundle.json → payload.scheduler.recent_runs[].hygiene.wal_checkpoint`; the WAL fields are
  computed BEFORE the dbstat walk so they survive on SQLCipher builds where dbstat is absent. Only
  three small gaps remained: `PRAGMA wal_autocheckpoint` was never read in production, the last
  checkpoint record was not surfaced in `storage-composition.json` (discoverability only), and there
  was no historical WAL series (`ALL_METRICS` is counts-only). **ALL THREE CLOSED 2026-07-29 (S11;
  shipped.csv row "monitoring/diagnostics — WAL visibility"):** the autocheckpoint threshold is read
  and resolved to bytes (with an explicit note when it is 0 = automatic checkpointing DISABLED, a
  state previously indistinguishable from health in every export); `storage-composition.json` now
  carries the newest run that ACTUALLY measured a checkpoint (runs whose checkpoint honestly returned
  None are skipped, never mistaken for the answer); and the hourly snapshot recorder gained a THIRD
  metric family — GAUGES — recording `wal_bytes`, so multi-day growth is finally visible (an
  unmeasurable gauge is SKIPPED, leaving an honest hole, never a recorded 0 that would read as "the
  WAL was empty"). `wal_bytes` is DELIBERATELY absent from `ALL_METRICS` (the Library endpoint's
  user-facing allowlist) — ruling 8 says this is diagnostics material, not a user surface.
  **RULING 15 SCOPED HONESTLY (brief §7):** abort is FREE and COMPLETE before `os.replace`
  (`merge.py:1985`) — everything runs on a disposable `.restore-<hex>` staging dir + a `working.db`
  copy under ONE `BEGIN IMMEDIATE` (`merge.py:295`,`:353-362`) — with two caveats: "live untouched"
  actually ends one stage EARLIER (`side_files_and_custody`, `merge.py:1950`, writes into
  `data_dir()` + a separate `custody_log.db`), and there is NO abort hook at all today
  (`run_restore` takes no `should_stop`; all three progress callbacks swallow exceptions by design,
  `merge.py:333`/`timing.py:51`/`store.py:523`). AFTER the swap there is NO undo and building one is
  UNSOUND: a `merged_rows` delete leaves dangling ids (the re-index delete-then-reinserts,
  `store.py:304`), `map_articles` joins on hash so a batch legitimately attaches rows to
  PRE-EXISTING articles (`merge.py:601-604`), nothing repairs `Keyword`/`Source` counters after such
  a delete, and the merge's raw `connect()` sets no `foreign_keys` pragma so cascades silently do
  not fire; snapshot-undo is incomplete and `_SNAPSHOT_KEEP=3` (`merge.py:59`) means item 1's
  snapshot is gone by item 4 of a 6-backup run. So: pre-swap Stop = abort now, full undo (ruling 15
  exactly); post-swap Stop = stop the REMAINING work, said plainly in the UI; the swap itself is
  explicitly UNINTERRUPTIBLE. **CONVERGENCE:** once ruling 1 moves the re-index out of the import,
  the post-swap window shrinks to a few cheap stages — ruling 1 is what MAKES ruling 15 honest.
  **THE PLAN:** 11 slices in 4 phases — A quick wins (S1 per-phase ETA + a server-computed
  `phase_index`/`phase_total` since M is 19/18/8 depending on `commit`+`reindex_imported`, NEVER a
  hardcoded constant · S2 rate instrumentation as a SIBLING report key, since `StageTimings` is
  float-only and `_uxTimingsView` formats every value as a duration · S3 pass `commit_batch` ·
  S11 the three WAL gaps) → B correctness (S4 the counter bug, reproducer first · S5 the re-index
  as an autonomous resumable job + the §3 decision · S6 the fingerprint, which must hash MORE than
  `app_version` since stoplists are data files that change without a version bump) → C the measured
  optimisation (S7 the narrowed cache, gated on S2's numbers) → D the queue + UI (S8 immediate
  collector stop + ONE exclusive window across the whole queue · S9 the server-side queue, a HYBRID
  of `DumpDownloadManager`'s persisted-order skeleton [`wiki/dumps.py:121`,`:192-210`,`:233-268`]
  and `NewsletterImportManager`'s per-run cursor discipline · S10 the dialog redesign mirroring
  `_renderOsmList` [`app.js:15337-15385`], whose CSS already exists). SCOPE FENCES: never touch the
  legacy path (ruling 11) · never build a post-swap undo · never add a UNIQUE index on
  `normalized_term` (its absence is deliberate) · never claim a speedup S2 has not measured · no new
  network behaviour. FOUR items still need the maintainer: the §3 (a)/(b)/(c) choice · confirming
  the narrowed cache GO · confirming the counter reconcile belongs at the end of `run_restore` ·
  whether imported articles should also be hidden from SEARCH during the re-index window (the recon
  found no code evidence of intent either way; the recommended design leaves them searchable).
- **FIELD REMARKS 2026-07-26 — AI-job toggle UX, translation-gap detector ask, two progressive-sweep
  job bugs, P0/pagesize-bench removal question, qualification-backlog wiring gap (maintainer;
  INVESTIGATION-ONLY this session, code-verified against `main` via a 6-agent read-only fan-out;
  brief of record = [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-26_FIELD_REMARKS.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-26_FIELD_REMARKS.md);
  nothing built this session):** nine remarks, each root-caused with file:line citations in the
  brief. (1–3) the keyword-triage/source-tags/perception-extract Settings→AI toggle buttons
  (`toggleKeywordTriage`/`toggleSourceTags`/`togglePerceptionExtract`, `src/static/app.js:11707-
  11970`) set `btn.disabled=true` at click-time and only clear it in a `finally` that doesn't fire
  until an up-to-3-hour blocking poll loop exits — CSS fades the disabled button for the whole run
  and a disabled button can't be re-clicked; no separate Stop control exists. The correct reference
  pattern already ships in the same file: `pollLangDetect`/`_paintLangDetectButton`
  (`app.js:4886-4973`, the langdetect job) — never disables, polls via an independent flag. Also:
  all three run endpoints (`KeywordTriageRunBody`/`SourceTagsRunBody`/`PerceptionExtractRunBody`,
  `src/api/diagnostics.py`) require a `model` field with no fallback, forcing free-text model
  inputs, even though `active_model()` (`src/api/llm.py:124-153`) is the house-wide single source
  of truth every OTHER AI call site already falls back to (and the sibling module
  `perception_job.py:49` already does `model = model or active_model()`); descriptions aren't
  wrapped in the house `<details class="adv-collect">` collapse convention. (4–5) `--audit-chrome`/
  `--min` (`scripts/i18n_report.py`) is a STATIC scan of `index.html` ONLY — it never opens `app.js`
  (18,599 lines, the actual UI engine), so real gaps are invisible to it (confirmed: hardcoded
  never-`t()`-wrapped table headers/empty-states at `app.js:4341/7632/9315/15866/17256/1785`, plus
  a live inconsistency where "Loading…" is correctly wrapped at `:2055` but bare at `:1806`/`:3304`).
  The maintainer's ask for a screenshot/DOM-walk detector is buildable and additive to
  `src/monitoring/ui_walk.py` (currently a skeleton — `UnconnectedDriver` only, no real
  `UiWalkDriver` implementation exists anywhere in the repo; a one-off Playwright pass happened
  once, 2026-07-22, never committed) — DOM-text-node + attribute extraction (mirroring `i18n.js`'s
  own `tr()`/`doAttrs()`) beats screenshot+OCR and is fully specced in the brief. (6) the
  source-tags job's "13 batches of 0/0 then failure" is TWO real bugs: validation-rejection
  counters (`pb.missing`/`pb.parse_failures`, `src/ai_layer/source_tags.py`) are computed but NEVER
  rendered in the UI (so real work was silently happening), and the progressive job
  (`src/ai_layer/source_tags_job.py`) only catches `LLMUnavailable`, not its sibling `LLMError`
  (raised on any non-404 HTTP error from a reachable-but-erroring model — plausible given the
  uncapped, verbatim, corpus-wide tag vocabulary embedded in every prompt) — an uncaught `LLMError`
  hard-crashes the job to `state="error"` instead of pausing gracefully. Restart correctly resumes
  from the persisted cursor. (7) keyword-triage's "stopped after 56 batches" is the SAME
  `LLMUnavailable`-zero-retry family (`src/ai_layer/triage_job.py:362-390`), but WORSE: the pause
  is test-pinned to collapse into the identical `BackgroundJob.state=="done"` as a genuine finish
  (`tests/test_triage_and_source_tags_endpoints.py:207-270`), `/status` and `/last` DISAGREE on a
  paused run (`"done"` vs `"in_progress"`), and `/api/jobs` filters non-running/non-error jobs out
  of the task manager entirely (`src/api/jobs.py:441-443`) — so a paused sweep is invisible
  everywhere except one field, and nothing auto-resumes it. Fix = bounded retry-with-backoff
  (precedented already — Session A 2026-07-24 shipped exactly this for the langdetect job; reuse
  that template) applied uniformly across all three progressive-sweep jobs, never conflate
  paused/done. (8) **KEEP both `p0_validation.py` and `pagesize_bench.py` — do NOT remove.** P0:
  `RELEASE_0.3_GATE.md` rows 4+7 and this ledger's own "0.3 CLOSE GATE" row 7 are CURRENTLY OPEN
  and explicitly require re-running it (cold-boot unlock at full scale + a multi-day collector
  soak); it's also a named live KPI source (K3, `V1_PATHWAY_2026-07-14.md`). Pagesize-bench: its
  `rebuild_at_pragmas()` is now PRODUCTION-CODE-COUPLED — `src/database/connect.py:84-98,329-333`
  cross-references it BY NAME as the proven source of the live pragma-ordering fact production now
  depends on — and it's the explicit reference implementation the still-open
  `AUTONOMOUS_SESSION_BRIEF_2026-07-22_PR740_PR744_REMEDIATION.md` brief instructs future sessions
  to read before building the not-yet-existing corpus-migration op the "BACKUP/RESTORE BAR" ruling
  calls for. **LEDGER-STALENESS FOUND ALONG THE WAY**: this ledger's own "0.3 CLOSE GATE" row 6
  still reads "currently waiting on the large-corpus run" but `shipped.csv` (2026-07-23) + the
  actual `connect.py` commits show §1b already shipped to production — a small standalone
  housekeeping fix, separate from (and much smaller than) this remark's actual question. (9) the
  73,079 "Discovered candidates" vs 1,391 "awaiting qualification" split is `Source.enabled`
  partitioning the table exactly as designed (every discovery/promotion channel hardcodes
  `enabled=False` — `src/catalog/discover.py:100-103`, `src/api/source_management.py:107-114`,
  `src/discovery/cited_sources.py:148` — per the standing 2026-07-15/2026-07-20 review-before-enable
  rulings) — BUT underneath that, `select_unqualified()` (`src/catalog/qualification.py:178-224`)
  has NO `enabled` filter, so the qualification job silently trial-fetches, stores real articles
  from, and judges disabled candidates too, while `evaluate_and_stamp()` never writes `enabled` —
  so a successful verdict on a discovered candidate is thrown away: it stays invisible to
  collection AND stays counted as "candidate" forever, and real trial-fetch bandwidth is being
  spent on 73,079 sources whose qualification currently means nothing. **NEEDS ONE MAINTAINER
  RULING before buildable**: (a) tighten `select_unqualified` to also require `enabled=True`
  (candidates need a separate future enable step first, no wasted trial-fetch) vs (b) have
  `evaluate_and_stamp()` flip `enabled=True` on a `qualified` verdict (qualification itself becomes
  the Phase-2 auto-promotion mechanism — reads as more consistent with the 2026-07-20
  "qualification IS the admission gate... every not-previously-qualified source gets the
  qualification pass BEFORE joining regular collection" ruling, but is a real Tor-bandwidth-scale
  decision on 73k rows). **COMPANION WORK RECEIVED + ANALYZED same day**: the diagnostic-log
  exports from 7 parallel hardware instances arrived and were cross-compared — see the dedicated
  entry immediately below this one.
- **HARDWARE DIAGNOSTICS COMPARISON 2026-07-26 — 7-instance cross-machine analysis (maintainer sent
  8 `all-diagnostics` zips from parallel VMs; 1 excluded as a stale pre-format 2026-07-10 export;
  INVESTIGATION-ONLY, code-verified from the real exports via a 7-agent read-only fan-out; brief of
  record = [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-26_HARDWARE_DIAGNOSTICS_COMPARISON.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-26_HARDWARE_DIAGNOSTICS_COMPARISON.md);
  nothing built this session):** 7 hardware tiers (a 6c/15.3GB i7-13620H down to a 2c/3.46GB AMD
  3020e), spanning 16k–700k articles, confirmed **TWO UNIVERSAL findings present on every single
  instance with no exception**: (1) **WAL/checkpoint starvation** — every instance's WAL exceeds the
  64 MiB `journal_size_limit` (4×–29×, and on the weakest/lowest-RAM machine the WAL literally grew
  LARGER than the machine's total RAM, 4.43 GB WAL vs 3.92 GB RAM), the app's own diagnostic self-flags
  it identically everywhere ("a checkpoint may be starved — a long-lived reader blocks it"), and it
  plausibly explains the second universal finding: single-row primary-key `INSERT`/`UPDATE`s
  (confirmed `COVERING INDEX`, never a bare scan, on every sampled EXPLAIN plan) averaging 2–11s and
  peaking at 15–341s. (2) **`GET /api/database/countries`** (polled together with 4-5 sibling
  Library/Governments-tab endpoints) is the dominant cost center on EVERY instance — 12–41% of total
  uptime individually, up to 81% combined with its polling siblings on the weakest machine — and is
  the sole cause of the KPI board's "K2 interactive p95" red verdict on all 7. `EXPLAIN` is healthy
  everywhere; this is a scaling-ceiling problem needing the SAME maintained-counter treatment already
  proven on `top_terms_grouped`/`supergroups`/`who_aggregate` (confirmed fast via counters in these
  same exports). BOTTLENECK CLASS TRACKS HARDWARE TIER cleanly: 5/7 (all but the weakest) classify
  `writer-bound`; only the AMD 3020e (2c/3.46GB, the weakest machine) classifies `memory-bound`
  (`mem_low_ticks` 53/44 across its 2 passes, governor honestly parked at 1 permit). **A PRIOR FIX
  VALIDATED WITH REAL BEFORE/AFTER FIELD DATA**: the AMD-3020e instance is the exact machine type the
  2026-07-23 field diagnostics analyzed (documented 3-8 min inter-pass gaps); THIS export of the same
  machine type shows a **45.9s average inter-pass gap** (down 4-10×) — the S4.1 duty-cycle fix is
  confirmed working in the field, not just in theory; the ~90% duplicate rate is unchanged (supply-
  side, expected) and the mem-low floor now oscillates 1↔50 permits (consistent with the ruled
  `rate_mode="maximum"` default flip, confirmed live on multiple instances) rather than sitting
  parked low. NEW for this machine type: a WAL-bloat→giant-checkpoint(21.8 min)→MEMORY-GUARD-ENGAGED
  cycle fired 8 TIMES in ~7 hours — a harder failure mode than the previously-documented soft
  mem-low back-off. **BUG A/B CROSS-CHECK (the two already-root-caused job bugs from the same-day
  field-remarks brief): INCONCLUSIVE on this batch** — 6 of 7 instances have NEVER run either job
  (no reachable local LLM backend at export time); only the 700k-article main-DB instance
  (`1fba378c`) has live data, and it shows a THIRD failure mode neither prior bug named: both jobs
  are simply running very slowly (keyword-triage ~0.03% keyword coverage after ~7h; source-tags
  1012 records against a 200-source scope after ~7h), neither crashed nor paused — consistent with,
  but not direct confirmation of, either prior root cause. **A genuinely new finding surfaced
  instead**: that SAME instance's live `perception-eval-live.json` shows Mistral-7B (the
  maintainer-ruled default model) scoring **94.7% hallucination rate on "who" extraction** — the
  eval-gate correctly refused to store any of the 700,242 gated articles' candidates (fail-safe
  working as designed), but this is real evidence the ruled default model may not clear the
  perception-extraction quality bar at all. FOUR MORE NEW findings, each reproduced on 2+ independent
  instances: (a) schema/alembic-stamp drift on 3 of the 4 newer-schema instances, all missing the
  same `sources.last_crawled_at` index the actively-enabled crawl-by-default feature needs; (b) a
  power-profile diagnostic reporting `collect_parallelism=1` while the live scheduler setting is
  actually 50 (same instance, a real reported-vs-actual discrepancy); (c) a SECOND unfiltered
  third-party logger (`trafilatura.metadata`, 58%+ of sampled error-log entries on 2 instances) —
  the same noise class as the already-fixed `htmldate.meta`, just a different logger, plus a third
  low-grade noise source (`GET /v1/models` 404s from the vLLM-probe on GPU-less hardware, 500+ calls
  per instance); (d) on the main 700k-article instance specifically: **~97.8 GB of accumulated stale
  pre-restore snapshots** (3 full DB backups created within 36 hours, none flagged for cleanup, over
  half the instance's total 151 GB footprint — the single most urgent disk-safety finding in the
  batch), cold-boot unlock time GROWING with corpus scale (17.7s→29.7s across two boots, both far
  above the P0 2000ms bar and directly relevant to the still-open K1 gate), a ~6.35M-keyword
  counter-drift gap (93.6% of all keywords show a zero `mention_count` counter against only 121k
  genuine orphans) that the app's own drift-checker can't even complete at this scale, and 2
  diagnostic-bundle members (`keyword-log-digest`/`source-audit`) that categorically cannot finish
  inside their 300s deadline at ~6.9M keywords / 76,679 sources. Full per-instance detail + the
  8-item prioritized action list in the brief. Nothing built; PENDING a future fix session.
  **ENRICHED same day (maintainer: "please identify them precisely and enrich... to allow the
  autonomous session to be as fruitful as possible"): every buildable finding above now carries a
  full, code-cited, directly-implementable fix specification in the brief** (exact functions to
  add/edit with file:line anchors, exact proposed code, exact tests to add) — produced by four
  dedicated deep-dive investigations against live `main`, not inferred from this ledger's own
  prose. **CORRECTION to (c) above: the `htmldate.meta` filter was only HALF-fixed on 2026-07-23**
  — `errorlog.py`'s `install()` attached the noise filter to the app's OWN `_JsonlErrorHandler`
  only, never to the `htmldate.meta` logger itself, so the noise was dropped from the JSONL
  counters but still reached every OTHER handler (console included) — **live-confirmed the same
  day** by a fresh-install terminal-log paste showing 25 repeated `ERROR [htmldate.meta]
  impossible to clear cache...` lines printed to the console. The brief's fix moves the filter to
  the LOGGER level (checked before ANY handler, per Python's `logging` semantics) and extends it
  to cover `trafilatura.metadata` with the same mechanism, closing both (c)'s findings and the
  live console-noise report in one change. **NEW EVIDENCE — an 8-machine parallel-instance
  confirming experiment** (maintainer, same day): ran the current build on 8 separate machines
  simultaneously to test whether aggregate article throughput scales with instance count — "in
  order to confirm my intuition that having multiple instances of OOS downloads more articles than
  having only one, thus explaining that the current limitation is neither TOR related bandwidth
  limitation nor hard disk / ram / computation limitations, and that it's only related to the
  software." If confirmed, this directly implicates single-instance software ceilings — exactly
  the WAL-starvation (§1) and `/api/database/countries` (§2) mechanisms above — as the fix
  priority; the brief records the experiment's design + hypothesis and flags that its actual
  aggregate-vs-single throughput numbers were not yet shared, so none are fabricated here.
  **EXECUTION PLAN AUTHORED same day (maintainer: "optimize it for an autonomous session driven
  by Sonnet 5 with ultracode activated"):**
  [`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-26_EXECUTION_PLAN.md`](docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-26_EXECUTION_PLAN.md)
  is the operating manual routing into the two investigation docs' specs — 8 slices in 5
  PR-groups (PR-A low-risk trio W3/W4/W6 · PR-B countries-rollup W2 · PR-C snapshot-sweep W5 ·
  PR-D WAL-restructure W1 · PR-E AI-jobs F2+F1), with the file-collision map
  (`scheduler/maintenance.py` W2∩W5 · `api/diagnostics.py` W6∩F1 — never concurrent worktrees),
  per-slice mandatory skeptic lenses (W5 full data-safety matrix — it DELETES files; W1
  transactional-semantics/autoflush/parity/S4.1-preservation — `evaluate_watches` WRITES inside
  the run_all loop, so commit-between-producers changes atomicity), the W1 probe-first rule
  (empirically test cursor-survives-commit before choosing periodic-commit vs keyset), the
  verbatim ci.yml gate commands, the scope fence (item 9 ruling-gated · items 4–5 own build ·
  Mistral-7B maintainer decision · no alembic migration anywhere in this plan), and the
  staleness-guard Phase-0 recon fan-out. Execution PENDING (the Sonnet-5 session).
- **TRANSVERSAL AUDIT 09 — SECURITY + FUNCTIONAL DELTA (2026-07-25, maintainer-commissioned generic
  "full transversal / bug-bounty / docs-vs-code" audit; full record =
  [`docs/audit/09_TRANSVERSAL_AUDIT_0.3_DELTA.md`](docs/audit/09_TRANSVERSAL_AUDIT_0.3_DELTA.md), a
  23-agent orchestrated workflow with every finding independently adversarial-skeptic-verified,
  PENDING a future fix session — report-first per the established audit convention, nothing built
  this session):** TWO P0s, both real, neither actively exploited in shipped code today. (1) **the
  airplane-mode socket-level backstop is BLIND to the real destination host when a SOCKS/Tor proxy is
  configured** — live-reproduced (a real PySocks connection through a stub SOCKS5 server, kill switch
  engaged, zero `AirplaneModeError`) AND hand-verified by the auditing session directly against the
  installed PySocks source: `socksocket.connect()` calls the patched `socket.socket.connect()` only
  with the PROXY address (loopback, correctly allowed), then negotiates the REAL destination via
  `sendall()` at the SOCKS application layer, invisible to the four functions
  `install_airplane_socket_guard()` patches. Every KNOWN entry point (`EthicalFetcher.fetch`,
  `GuardedSession.request`, the mailbox helpers) checks the kill switch before touching a proxy
  session, so this is not leaking today — but it falsifies the guard's own "whatever the code path"
  claim for exactly the transport at-risk journalists are told to use, and provides zero
  defense-in-depth against a future missed per-call check. Recommended fix: gate proxy-session
  CONSTRUCTION itself on `kill_switch_active()`, not just per-fetch call sites. (2) **the brand-new
  (2026-07-24) B6 eval-gated who/where/when LLM-extraction feature is completely non-functional** —
  `gate_languages_from_report()` (`src/ai_layer/perception_extract.py`) reads `report["by_language"]`
  but the real persisted artifact nests it one level deeper at `report["report"]["by_language"]`, so
  every language is PERMANENTLY gated "never evaluated" regardless of how clean the harness scores it
  — live-reproduced end-to-end with the real production functions, zero mocks. Every unit test mocks
  the wrong (bug-matching) shape, which is why it shipped fully green. Fails SAFE (extracts nothing
  rather than fabricating), but silently defeats the entire shipped feature — a one-line unwrap fixes
  it. FOUR P1s: a live-reproduced symlink-follow path-traversal in the folder-backup RESTORE path
  (`restore_folder_backup`, `src/backup/folder_backup.py` — the sibling `verify_folder_backup` has the
  traversal guard, restore doesn't; recurrence of a defect CLASS this project already fixed once in
  the same subsystem); Pillow 12.2.0 pinned in `requirements.lock` with real CVEs reachable via
  `POST /api/verify/image-metadata` (downgraded on reachability analysis to only 2 of 13 CVEs actually
  reachable through this app's narrow `Image.open()+.load()`-only usage, both DoS not memory-
  corruption — bump to `>=12.3.0` + regenerate the lockfile); a missing `session.rollback()` in the
  new throughput-brief archive-backfill/housekeeping-lane loops that lets one dirty-session exception
  silently cascade into marking unrelated URLs/ride-alongs as permanently failed (this project's own
  documented mid-batch-handler-discards-siblings bug class, recurring); and `docs/USER_MANUAL.md` has
  ZERO documentation of the qualification lifecycle despite the 0.3 close-gate's own row 1 explicitly
  requiring that docs↔app reciprocity. Also: the all-diagnostics completeness ratchet
  (`test_all_diagnostics_bundle_covers_every_get_diagnostic`) only scans `src/api/diagnostics.py`
  itself and is structurally blind to sibling diagnostic-shaped routers (concretely,
  `src/api/integrity.py`'s `/fixity` endpoint) — downgraded P1→P2, a completeness-mechanism gap not a
  functional break. POSITIVE findings: all 5 P0s from the 2026-07-22 GUI test report are now confirmed
  FIXED (4 distinct commits); the non-proxied half of the airplane guarantee holds perfectly under
  direct adversarial code review (stdlib sockets/asyncio/TLS/mailbox protocols); all 5 spot-checked
  non-negotiables hold; bandit/secrets/SQL-injection otherwise clean. The doc's own Action Plan D
  (§12) ranks all ten follow-up items; items 1-2 (the two P0s) are the priority.
  **ALL TEN ACTION-PLAN-D ITEMS SHIPPED 2026-07-25 (fix-forward session, same-day; shipped.csv row
  "security — transversal audit 09 fix-forward"):** (1) the SOCKS/Tor-proxy blind spot — closed by
  ALSO patching `http.client.HTTPConnection._tunnel` (the CONNECT-tunnel destination) and PySocks'
  own `socksocket.connect` (the real destination BEFORE SOCKS negotiation), both invisible to the
  original 4 patched functions; live re-run of the audit's own stub-SOCKS5-server exploit now
  confirmed blocked, + 6 new regression tests. (2) the B6 gate — `gate_languages_from_report()` now
  reads `report["report"]["by_language"]` matching the REAL harness-produced shape; a new test drives
  the real harness end-to-end (not a hand-typed mock). (3) the folder-backup symlink traversal —
  `restore_folder_backup` now checks `Path.is_symlink()` (lstat, never follows) before `is_file()`/
  `open()`, refusing every symlink outright + a new honest `refused_symlinks` tally; live-reproduced
  before/after. (4) Pillow bumped `>=12.3.0` in `pyproject.toml` + `requirements.lock` regenerated
  (pip-compile, diff scoped to exactly the pillow block; `pip install --dry-run --require-hashes`
  confirms it resolves clean). (5) `session.rollback()` added to BOTH `archive_backfill.py`'s per-url
  loop and `run_housekeeping_lane`'s per-kind loop — empirically confirmed via a real SQLAlchemy
  IntegrityError→PendingRollbackError repro (both directions) that a dirty session previously
  cascaded EVERY remaining item in the tick to a false "error", not just the one that actually failed.
  (6) `docs/USER_MANUAL.md` gained the qualification-lifecycle + discovery-trail/citations-tally
  subsections (§3.3) and the import-reports + non-article-screening subsections (§3.9), hand-verified
  against the real code. (7) the completeness ratchet now scans a new `_DIAG_SIBLING_FILES` list
  (currently `src/api/integrity.py`) in addition to `diagnostics.py` itself; `/fixity` is folded into
  the bundle as a bounded (`limit=500`) member reusing the endpoint's own `guarded_read`; the 3
  genuinely-functional integrity endpoints are honestly exempted, not silently swallowed;
  stash-verified the ratchet correctly reddens on exactly the 4 previously-invisible routes. (8) THIS
  ledger's own "0.3 CLOSE GATE" row 1 text amended so its broad "implemented" language no longer
  silently covers the Tor-exit-resolve design — explicitly carved out as maintainer-ruling-gated
  (zero code built), per the audit's own instruction to reconcile the text rather than rush the
  feature. (9) the 6 modules' `_walk_no_score()` self-tests now `raise AssertionError(...)` explicitly
  instead of a bare `assert` (verified the fix actually raises under `python -O`, the exact failure
  mode being closed). (10) `get_client_with_name()`'s TOCTOU — `dict.setdefault` replaces the
  check-then-write. Every fix carries a targeted regression test, several stash-verified live against
  the pre-fix code. Full detail + the sandbox's own environmental-limitation disclosures in the
  shipped.csv row's summary.
- **FIELD DIAGNOSTICS FINDINGS (2026-07-21, from a real operator export against the live
  474,556-article corpus, NOT the 0.3 gate's ≥5M run):** brief of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-21_FIELD_DIAGNOSTICS_FINDINGS.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-21_FIELD_DIAGNOSTICS_FINDINGS.md),
  PENDING a future session. Seven items, each a candidate for its own scoped PR: (1) a severe
  p95/p99 slow-tail on `/api/insights/map-coverage` (up to 335s) and `/api/search/omni` (up to
  291s); (2) "rising" Home Lead cards never hard-link to their exact articles (`Card(...)` in
  `rising_now`, `producers.py:193`, is missing the `article_ids=` sibling producers got via the
  F1 hard-link follow-up); (3) a cluster of multi-hour stalls + 503s all on 2026-07-11,
  cause not yet identified; (4) keyword-growth evidence (marginal ~9.7 new keywords/article,
  flat vs the ~10.6 cumulative average) supporting the still-unbuilt nav-soup prose gate; (5) a
  measured, bounded non-article-contamination figure (1.44%, 6,825 articles) ready to quarantine
  once cleanup strategy is agreed; (6) five sources at 100% outlier_rate
  (`subseaworldnews.com`, `biospectrumasia.com`, `jota.info`, `24heures.ch`, `suspilne.media`)
  worth a manual check before automating source requalification; (7) schema/FTS confirmed
  clean (nothing to do there). None require corpus growth to investigate or fix.
- **DOC MAP (consolidated 2026-07-10):** the single forward-looking board is now
  [`docs/ROADMAP.md`](docs/ROADMAP.md) (DB limitations · performance/scale · known bugs ·
  feature backlog, each with status) — read it for the overview; the DEEP scale detail stays
  in [`docs/product/SCALE_ROADMAP.md`](docs/product/SCALE_ROADMAP.md); design intent stays in
  `docs/FUTURE_DEVELOPMENTS.md`; THIS ledger stays the binding source of truth. The three dead
  roadmap homes (old `docs/ROADMAP.md`, `docs/product/ROADMAP.md`, `BACKLOG_GROUPED.md`) were
  archived to `docs/archive/roadmaps/` (nothing deleted).
- **SESSION A PROGRESS (2026-07-10, branch `claude/a-scale-backend-p04-9faxvb`, one draft PR onto
  0.2, commit-per-item; full detail = the 8 `docs/ledger/shipped.csv` rows):** SHIPPED, each
  skeptic-verified pre-push (negative-space lenses) + full-suite-green (py3.13 .venv, 3361 passed):
  **A1 P0.4 unlock ROOT-CAUSED + fixed** (`ensure_fts` ran the FTS5 `'rebuild'` — a corpus-scaled
  codec re-read — on EVERY boot; now rebuilds only when needed; MEASURED 28.6 s → 0.002 s on a
  112k/2.7 GB encrypted synthetic corpus, G2 warm unlock 0.012 s — **fixed on synthetic, live-run
  is the final gate, NOT closed**), **A7** corpus-epoch→restore-merge (DB-7), **A8** alembic
  stamp-align after self-heal with a DATA FLOOR so it never stamps past a fabricated/wrong-data
  migration (DB-8), **A6** folder-backup verify (`/api/backup/folder/verify`, UI→B), **A11** opt-in
  persistent `OO_DATA_DIR` via install.sh/launch.sh + honest tmpfs/Qubes-disposable detection
  (never "stop using DispVMs"), **A12b** unified itemized storage-footprint incl. the external
  Ollama store. A12/A4 were **found already resolved** (forensics inventory / the #595 data-version
  status cache — no dup). A9 riders INVESTIGATED, none shipped (F14 non-reproducible: SessionLocal
  is autoflush=False; F10/F11 data-safety-backup-path risk > LOW gain; F13 index_article-split risk
  vs GIL-marginal). **A13 httpfs bundling BLOCKED** (contingency): `extensions.duckdb.org` is not in
  the network egress allowlist (curl 403 "Host not in allowlist"), so the per-OS crypto-extension
  binaries can't be fetched/attested — the in-memory columnar fallback stays, NO checksum
  fabricated; D1/D2/D3 stay gated on a networked machine or an allowlist entry. MID-SESSION
  maintainer asks handled: discovery-candidate noise filter (CDN/analytics/boilerplate + the missing
  is_social; `bsky.app`/`t.me`/`fonts.googleapis.com`/`policies.google.com`/`creativecommons.org`)
  + the storage-footprint = A12b. REMAINING (pending, machinery largely exists): A2 (extend
  deadline/single-flight coverage; core in `src/api/heavy.py`), A3 (job-ify server-locations etc.),
  A5 (heavy-endpoint sweep), A10 (off-peak maintenance scheduling), A14 (5 TB design doc).
- **PARALLEL AUTONOMOUS SESSIONS A+B — MAINTAINER RULED 2026-07-10 (verbatim "1 a / 2 a / 3 a /
  4 a" to the four pre-clearance questions; briefs at `docs/design/AUTONOMOUS_SESSION_BRIEF_
  2026-07-10_A_SCALE_BACKEND.md` + `_B_PRODUCT_UX.md` — the operating manuals, incl. the
  territory contract that keeps the two sessions collision-free):** (1a) **P0 engineering vs the
  synthetic GAMMA harness is CLEARED** — Session A may root-cause AND fix P0.4 unlock-at-scale
  (+ the P0 riders: corpus-epoch→restore-merge, folder-manifest verify) against the synthetic
  corpus, everything test-pinned + benchmark-proven; the maintainer's LIVE-corpus run stays the
  FINAL validation gate (never claim P0 closed on synthetic evidence alone). (2a) **the zh/ja/th
  SEGMENTER ruling is DELEGATED — pick & ship** license-clean offline segmenters (prefer a
  pip-installable `[segmentation]` extra over repo vendoring; graceful degrade; registry
  entries; measured junk reduction) + ko/vi/mr stoplists where a real source exists.
  **EXECUTED 2026-07-10 (Session B, branch `claude/b-segmenter`; shipped.csv row): CHOSE jieba
  (MIT, zh) + janome (Apache-2.0, ja) + pythainlp newmm (Apache-2.0, th) — pure-local, dicts
  bundled IN-WHEEL (no download/network/*_AS_OF, no registry entry needed), a new
  `[segmentation]` pip extra (no repo vendoring). Hooked into `extract._terms()` behind
  `segment()` (offset-preserving) with a language-aware `min_len=2` for CJK/Thai; graceful
  degrade by construction (extra absent / `OO_SEGMENTATION=0` → byte-identical whitespace path,
  zh/ja/th stay `unsegmented`). `managed.language_status()` is now segmenter-aware (zh/ja/th →
  `functional` only when the segmenter is present); ko(Hangul)+mr(Marathi) added to
  MANAGED_LANGUAGES with vendored stopwords-iso lists (zh/ja/th/ko/mr .txt added; sr/az stay
  honestly uncovered). CI's main job installs `[segmentation]` so it is exercised; the Core-only
  job proves the degrade. Measured on fixtures: whole-sentence junk / Thai mark-fragments → real
  RECURRING words (经济/政策, 経済/政府, เศรษฐกิจ/รัฐบาล). LESSON below.** (3a) **ALL
  ~9 pending rulings are delegated with full autonomy INCLUDING vendored binaries** — the per-OS
  httpfs crypto-extension bundling attempt is cleared (sha256-pinned, registry-tracked,
  verify-before-LOAD; on any fetch/attestation failure record the blocker, never fabricate),
  hover-stats/region-value/rare-earths(USGS)/sentiment decided by Session B with conservative
  defaults recorded here; lemmatization default-on STAYS measure-gated (the gold set is
  maintainer-made — cannot be honestly synthesized); the v0.2.0 TAG stays held (unchanged).
  **3a DECISIONS EXECUTED/RECORDED 2026-07-10 (Session B, B12; conservative defaults):**
  • **REGION VALUE — BUILT** (branch `claude/b-region-usgs`): supranational/transnational bodies
    (International, EU) now get an honest **"Global"** region (`src/catalog/countries.py`:
    `CONTINENT_OF int/eu → Global` + `CONTINENTS` gains "Global"), so the "International" bodies the
    de-US-centring pass left uncountried have a truthful home in the regional-balance report instead
    of being invisible or forced into a continent. A source is Global only if it carries country
    `int`/`eu`; unknown stays uncategorised (never fabricated Global). test_country_normalization
    updated (the old `continent_of("eu") is None` guard flipped to `== "Global"`). Populating
    individual International sources with `int` is a follow-up data-curation step.
  • **RARE-EARTHS — DECIDED: USGS supply-data** (recommended option). No free rare-earth SPOT-price
    source exists; the honest path is USGS **Mineral Commodity Summaries** (annual production /
    reserves / net-import-reliance — SUPPLY figures, explicitly labelled NOT spot prices, so no
    fabricated market number). Build = a stats-agency entry + an annual-supply parser under
    `src/stats/` (a follow-up slice, gated on the maintainer's next stats pass); the current
    commodities board stays price-only + honest about the gap. Recorded as the chosen direction.
  • **MULTILINGUAL SENTIMENT — DECIDED: DEFER the model path, pivot to rule-based subjectivity.**
    pyproject BANS torch/onnx/transformers, so no multilingual transformer classifier is admissible.
    The honest direction is the **subjectivity / loaded-language rule-based lexicon** feeding the
    manipulation cards (never a fabricated neutral); a first slice needs per-language subjectivity
    lexicons (license-clean, corpus-sourced) — deferred until a real source is vetted. Meanwhile the
    shipped VADER-**English-only** sentiment stays, already labelled English-only (no silent
    cross-language scoring). Recorded, not built this round.
  • **LEMMATIZATION default-on — STAYS measure-gated** (deferral confirmed): the retrieval-quality
    gold set is corpus-specific + maintainer-made and cannot be honestly synthesized, so
    `OO_FAMILY_LEMMA` stays default-off. The `lemma_preview` diagnostic already surfaces the candidate
    conflations for the maintainer to review before flipping it; no cheap further-surfacing needed.
  (4a) **the doc-archival pass is CLEARED** — session-briefs/releases/field-tests →
  `docs/archive/` subfolders, non-lossy, links retargeted (the two live 2026-07-10 A/B briefs
  stay until their sessions complete). Sessions branch as `claude/a-*` / `claude/b-*`; shared
  append-targets (this ledger, shipped.csv, ROADMAP, external_artifacts.yml, repo-invariants)
  merge ADDITIVELY — never revert the sibling session's lines (the #548 precedent).
  **ADDENDUM (maintainer-directed 2026-07-10, same day — two new items routed into the briefs):**
  (i) **"Database size" must mean EVERYTHING** — the reported storage footprint covers db +
  wal + wiki dumps + OSM regions + staging + the OLLAMA MODEL STORE (which lives OUTSIDE
  data_dir — reuse `ollama_models.default_store()`/`store_status()`, honest unavailable state),
  itemized per component (private encrypted corpus vs re-downloadable public blobs stated),
  never just the SQLite file. Backend aggregation = Session A (brief A12b); display = Session B
  (brief B14). (ii) **LLM language detection for unknown-language articles — OPT-IN, CLEARLY
  LLM-DEDUCED** (brief B15): local-Ollama detection ONLY for the residue py3langid leaves
  unknown; NEVER overwrites the asserted `Article.language` nor a detector-filled
  `detected_language`; provenance per result (model + prompt version); a visible abortable job,
  never the scrape hot path; the result surfaces as a THIRD, labelled provenance class
  ("AI-derived · unreliable" convention); a garbage/unvalidatable model answer stores NOTHING.
- **SIX CONSECUTIVE AUTONOMOUS SESSIONS S1–S6 — MAINTAINER RULED 2026-07-11 (answers "1 yes ·
  2 yes · 3 excluded · 4 yes · 5 yes" to the five pre-clearance questions; conventions =
  `docs/archive/session-briefs/SESSIONS_2026-07-11_CONVENTIONS.md`, briefs = `AUTONOMOUS_SESSION_BRIEF_
  2026-07-11_S{1..6}_*.md`):** one session per reconciled-ROADMAP tier, run CONSECUTIVELY —
  the maintainer MERGES each session's PRs before launching the next (that cadence is the
  conflict-free guarantee; branch prefix `claude/s<N>-*`). (1) S1 = the Tier-0 RELEASE KIT:
  the live P0 validation becomes a push-button in-app job + runbook + tag-day prep — the
  live RUN and the TAG stay maintainer-only. (2) S3 builds D1/D2/D3 persisted-columnar
  machinery NOW, GATED behind `secure_crypto_available()` (CI may INSTALL httpfs; local
  skips honestly; activates when the maintainer drops the pinned binaries in — never relax
  the gate, never fabricate a checksum). (3) the Wikipedia+laws VERSIONED-SOURCES revamp
  stays EXCLUDED (P0-gated — not even foundations). (5) each session ABSORBS the previous
  session's closeout CARRY-OVERs. NETWORKED work is excluded program-wide (each brief carries
  the operator list). Skeptics-complete-before-push + the negative-space lens are program
  gates; every session ends with a closeout ledger row + carry-over PR section.
- **S1 CLOSEOUT (2026-07-12, Tier-0 release kit, branch `claude/s1-p0-validation-kit-p4x3px`, one
  draft PR onto 0.2; full detail = the shipped.csv row):** SHIPPED, skeptic-verified pre-push
  (4 distinct lenses: data-loss · honesty/no-fabrication · secret-leak/traversal · concurrency/
  correctness — all GO, 7 findings applied) + full-suite-green (py3.13 .venv, 3400 passed).
  **S1.1** post-wave health check: the A+B wave (#614–#631) is CLEAN — full suite 3400 passed / 64
  skipped on the 0.2 tip, ruff blocking + i18n 100% + mypy 127≤127 all green; NO fix-forward
  needed. FINDING (pre-existing, NOT fixed — a carry-over): a subset-order test-pollution exists —
  running `test_a2_job_endpoints.py` (its heavyweight `TestClient(app)` lifespan fixture: real
  startup/shutdown = engine/airplane-guard/seeding) before `test_diagnostics.py::test_doctor_
  healthy_returns_zero` in a subset with test_repo_invariants/all_diagnostics_job/session_forensics
  makes `run_doctor()`'s `session_scope().query(Source).count()` fail → rc 1; REPRODUCES ON CLEAN
  origin/0.2 (so not this session's regression) and is GREEN in full-suite order (so CI never hits
  it). Flagged for a future test-hygiene pass. **S1.2** the push-button P0 live-validation JOB
  (`src/monitoring/p0_validation.py` + `POST /api/diagnostics/p0-validation{,/status,/cancel,/last,
  /download}` + a Settings→Diagnostics panel): one cancellable `BackgroundJob` (is_writer=False)
  drives the REAL backup engine against the operator's live corpus (RSS-sampled), verifies it,
  probes a STAGED restore + a dry-run merge PREVIEW (`commit=False` — the live corpus is only ever
  read; the backup's one write is the engine's standard WAL checkpoint, content-preserving), and
  reads the merged #596 unlock + collect_perf/memguard instrumentation into ONE report with a
  per-check verdict (pass|fail|not-measurable-here) against the WRITTEN SCALE_ROADMAP bars —
  measurements only, NO composite score, NEVER a fabricated pass, backup-engine-format+version
  stamped; wired as a debug-bundle + all-diagnostics member (read-only, never runs a backup). Tests
  drive the REAL live path (monkeypatch `live_db_path`, never a `corpus_source` double — ZETA (c))
  + assert the live corpus is byte-unchanged + no passphrase leak + staging cleaned + a cancel
  leaves no complete-looking backup. **S1.3** `docs/product/P0_VALIDATION_RUNBOOK.md` (click-by-
  click + a maintainer-only TAG-DAY CHECKLIST), linked from the panel + ROADMAP. **S1.4** the
  CHANGES.md 0.2.0 section is now release-notes-ready (A+B-wave bullets, tag-held line kept);
  release.yml VERIFIED gating correctly (full-suite `test` job + tag==pyproject + SHA256SUMS +
  `--verify-tag`) — no change needed; README/CONTRIBUTING version prose confirmed needs no change
  at tag time. **S1.5** hardening = the 4 skeptic lenses; 7 findings applied (below). REMAINING /
  CARRY-OVER for S2 (in the closeout PR body): the maintainer's LIVE RUN of the job + the v0.2.0
  TAG (both maintainer-only); the pre-existing test_a2 subset-order pollution; browser click-through
  of the Settings panel (fork-3, no browser here). LESSONS below.
- **S2 CLOSEOUT (2026-07-12, Tier-1 P1 snappiness board, branch `claude/s2-snappiness-board-okqg27`,
  draft PR #633 onto 0.2; full detail = the six shipped.csv rows + the S2 SHIPPED_LOG entry):**
  SHIPPED, each risky slice skeptic-verified pre-push (S2.2: 3 lenses/1 med fixed; S2.5: 2 lenses/1 med
  fixed). **S2.1** A9 gate-hold riders (F10/F11/F13/F14) closed REPRODUCER-FIRST — all four DECLINED with
  reproducers/analysis as evidence (F14 refuted by test; F13 real-but-GIL-marginal; F10/F11 backup-path,
  F11 correctness-constrained); no production code. **S2.2** A10 off-peak maintenance is scheduler-owned +
  collector-idle (`src/scheduler/maintenance.py:run_idle_maintenance`, idle-gated + throttled + run_now-honest;
  decoupled from the pass-tail warm_cache; P1.12 complete). **S2.4** guard-coverage sweep — corpus-www/
  sentiment confirmed guarded, then 8 raw insights endpoints + 6 cards + omni (degrades) + link_analysis
  OOM materializations now behind the admission cap + deadline. **S2.5+S2.3** /api/articles async→plain
  def (threadpool, no freeze) + FTS over-fetch bound (id-only resolve → load the PAGE only; GAMMA-measured
  50 ms→11 ms warm) + a data-aware cached browse COUNT(*) (P1.3 swept). **S2.6** the 5 TB architecture
  review doc `docs/design/5TB_ARCHITECTURE_REVIEW.md` (S3's INPUT — hand-off explicit below). **S2.7** a
  per-endpoint p95-vs-500 ms snappy verdict in the latency reservoir (rides /request-latency + the bundle).
  **CARRY-OVER for S3 (in the closeout PR body):** (a) **`docs/design/5TB_ARCHITECTURE_REVIEW.md` is S3's
  direct input** — 8 ordered recommendations, headline = adaptive volume sizing (DB-9) + the auto_vacuum/
  page_size CREATE-time irreversible-seam ruling (decide before more field corpora exist) + D1/D2/D3 gated
  build; (b) the S2.4 on-demand guard tail (source_io/sources needs a Source counter · framing cap ·
  monitoring/anomalies + commodity/correlation grouped-SQL); (c) the S2.5 diagnostics residue
  (diagnostics/keywords pass-collapse/job · debug-bundle read-only+_safe+budget); (d) the reader per-source
  count needs a maintained Source counter; (e) browser click-through of the newly-guarded surfaces + any
  429/503 handling (fork-3). LESSONS in the Session-rituals subsection above.
- **S3 CLOSEOUT (2026-07-12, Tier-2 database & scale architecture, LOCAL branch
  `claude/s3-db-architecture`, 4 commits stacked onto a fresh `origin/0.2` base 0b15dbd4; NOT
  pushed — this sandbox has no `gh`/push credentials, so the deliverable is the branch + the exact
  push/PR commands in the closeout message):** SHIPPED, each slice ruff+mypy-clean and green in a
  py3.13 venv (sqlcipher3 unavailable → the ENCRYPTED-store paths are CI-only; everything else ran
  here — duckdb/numpy/cryptography wheels installed). The DB-9 slice was adversarially
  skeptic-verified PRE-COMMIT (a HIGH member-count-gap bug found + fixed). Full detail = the 4
  `docs/ledger/shipped.csv` rows + the S3 `SHIPPED_LOG.md` entry. **S3.1 (D1, DB-3):** offline
  pin-and-verify httpfs LOADER — a bundled per-OS binary LOADs by absolute path only after its
  SHA-256 matches the BLANK-shipped `duckdb-httpfs-extension` registry pin + version-minor couples
  to duckdb (+ basename traversal guard); stays in-memory otherwise (never a network autoload,
  never a fabricated checksum); fixture-tested + a new `columnar` CI lane. **S3.2 (D2/D3):** wired
  `rollup_serve` to PREFER the persisted store (single held connection, epoch-gated incremental
  refresh — the ATTACH store rejects a 2nd handle); in-memory stays byte-unchanged; dormant until
  the binary lands. **S3.3 (DB-9):** adaptive backup-volume sizing (N~200, N+M under the GF(2⁸)
  ceiling at any scale, byte-identical <100 GB, sizes against the real per-member count);
  torture-tested incl. an interrupted tier-crossing. **S3.4 (DB-10):** the retention/vacuum decision
  MEMO + auto_vacuum visibility + the cross-time-recall repo invariant. **CARRY-OVER for S4 (read
  FIRST):** (a) the **OPERATOR one-time networked step that turns D1 on** — build + sha256-pin the
  per-OS httpfs binaries and fill the `duckdb-httpfs-extension` registry
  (`docs/maintenance/EXTERNAL_DEPENDENCIES.md`); until then D1/D2/D3 stay in-memory (correct, no gain
  over the counters). (b) **DB-9 changed the backup engine the v0.2.0 P0.1 live validation covers** —
  if the maintainer's live P0.1 run predates this merge, the S1 validation job (engine-version-
  stamped) must be RE-RUN before tag-day. (c) **DB-10 needs a maintainer RULING** on the irreversible
  `auto_vacuum=INCREMENTAL` + `page_size` CREATE-time seam BEFORE more 0.2 field corpora exist (memo
  §1), then the small buildable follow-ups (the incremental-vacuum idle pass wired into S2.2, the
  full-VACUUM UI size-gate). (d) S3.5 (D5 Roaring co-occurrence bitmaps) was the explicit
  skip-without-guilt stretch — not built. (e) two `test_repo_invariants` version tests
  (`test_readme_version_matches_package` / `test_version_single_sourced_from_pyproject`) fail in the
  sandbox with `PackageNotFoundError` because `pip install -e .` never completed (sqlcipher3 blocked
  it) — ENVIRONMENTAL, not a regression, green in CI / a proper install. LESSONS in the
  Session-rituals subsection above.
- **S4 CLOSEOUT (2026-07-12, Tier-3 product quality — the reader-facing quality tail, branch
  `claude/s4-product-quality`, 7 commits stacked onto `origin/0.2` base `b85bc124` = 0.2 with
  S1–S3 merged):** SHIPPED, each slice node --check + invariant-guarded (frontend slices
  browser-unverified per fork-3) and green in a py3.13 venv (166 repo-invariants + the targeted
  suites; the 2 version tests fail with the same known `PackageNotFoundError` as S3(e) —
  environmental, green in CI). Full detail = the 7 `docs/ledger/shipped.csv` rows. **STALENESS
  GUARD PAID OFF** (the program-wide rule): S4.7's language-step consolidation was ALREADY DONE
  (`_GW_STEPS` was `["finish"]`, §2.5) → not rebuilt, just extended. **S4.1** CJK-numeral date
  recall PROBE in datediag (context-only, NOT actionable — measures the recall gap, never asserts
  a fabricated date; #590 negative-space + datediag-lockstep; extraction deferred to a segmenter
  pass). **S4.2** ring-translation per-language `language_breakdown` on the Trends/Home #oo-tip
  LAYERED hover (invariant #17, counts only). **S4.3** the synthesized-Leads Home carousel (LOCAL
  synthesis never LLM; WCAG-pausable; caveat rides every rotated face #23; every face deep-links #8).
  **S4.4** ported the `/api/insights/context` snippet concordance into the #an Keywords subtab so
  the omnibar→#an window ABSORBS the last Insights-bar capability (trend+associations+mindmap were
  already there); the bar is NOT hidden — `#ins-explore` interleaves the search bar with the
  non-searchable corpus-landscape AND the relocatable shared `#mm-kit`, so the hide is browser-verify
  gated. **S4.5** the composite-string i18n engine (`OOI18N.tf` = fixed keyable TEMPLATE with
  `{named}` placeholders + interpolated language-neutral DATA — the frame translates ×12, the data
  does not) + translatable Home-card titles (`Card.title_i18n`/`title_vars`, validated, `to_dict`;
  `rising_now` is the first reference producer; the template key in ALL 12 locales). **S4.6** the
  in-app `generic_terms` DF-ubiquity detector block in `engine_report` (review-worklist, POS-free,
  never auto-applied, no score by field-NAME). **S4.7** the guided-wizard sources-by-theme step
  (real tag taxonomy via loopback `/api/scheduler/coverage`; themes DEFAULT all = collect everything
  per the cover-everything ruling; `select_tags` filter only on an explicit reversible narrowing;
  language emphasis → `language_equilibrium` which orders-never-excludes; loopback config PUT only,
  wizard still NEVER posts the network). **CARRY-OVER for S5 (read FIRST):** (a) **the frontend
  slices are BROWSER-UNVERIFIED (no headless harness here) — a human CLICK-THROUGH is owed** across
  themes/breakpoints (per-surface list in the PR body): the Home carousel (pause/keyboard/caveat),
  the Trends/Home ring-breakdown hover, the #an Keywords **In context** concordance (query-seeded vs
  article-id corpus), a translated card title in a non-en locale (the `rising` Lead), and the wizard
  sources step (theme default-all, language emphasis, config actually applied). (b) **S4.4 hide of
  the Insights search bar is DEFERRED** — port done + absorption regression-guarded, but removing the
  bar needs a browser-verified untangle of `#ins-explore` (the search bar vs the non-searchable
  corpus-landscape + the relocatable shared `#mm-kit`); a blind removal is the interleaved-shared-
  component hazard. (c) **S4.5 composite-string mechanism is the reusable unblock** — extend
  translatable titles to the other producers + key more dynamic JS rows (`loadWatches` etc.) via `tf`
  (each new key needs all 12 locales or `--min 100` reddens). (d) **S4.1 extraction is deferred** —
  the probe quantifies the CJK date tail; actually EXTRACTING those dates is a segmenter-dependent
  follow-up (the probe is intentionally context-only so it can never fabricate a date). (e) **S4.7
  country-emphasis picker** — the `country_priority` order-never-exclude lever exists; a
  continent-grouped onboarding UI is the follow-up. LESSONS in the Session-rituals subsection above.
- **S5 CLOSEOUT (2026-07-12, Tier-4 decided-but-unbuilt rulings + measurement instruments, branch
  `claude/s5-rulings-builds`, 7 commits onto `origin/0.2` base `6a904c2d` = 0.2 with S1–S4 merged):**
  SHIPPED, each honesty-critical slice adversarially skeptic-verified PRE-PUSH (two workflows, distinct
  lenses incl. the mandatory negative-space lens — real defects found + fixed on S5.1, S5.2, S5.3) and
  green in a py3.13 venv (the 2 version tests fail only with the known sandbox `PackageNotFoundError` —
  no setuptools build backend; green in CI). Full detail = the 5 `docs/ledger/shipped.csv` rows.
  **DOCTRINE = measure-before-trust: make the maintainer's data production effortless, never synthesize
  it.** **S5.1** USGS Mineral Commodity Summaries SUPPLY parser (rare-earths B12) — production/reserves/
  net-import-reliance, NEVER prices (enforced by a narrowed MEASURE allowlist, not a unit check);
  `us-usgs` agency + `minerals_supply_summary` + `/api/stats/minerals-supply` + a Markets panel;
  skeptic-hardened (grouped-thousands no longer fabricates a gap; Europium survives the currency guard).
  **S5.2** the rule-based subjectivity/loaded-language engine (the sentiment pivot; model path banned) —
  per-language lexicon files (`configs/subjectivity/*.txt`, dated + registered), descriptive components +
  spans, honest per-language gaps, a SCRIPT-MISMATCH guard (a mislabelled language gaps, never a
  fabricated 0); feeds the headline_body card + a deduced per-article endpoint; VADER investigated + NOT
  reused (valence ≠ subjectivity). **S5.3** the IR gold-set BUILDER — samples real corpus queries (never
  invents), grades 0/1/2 keyboard-fast, writes the EXACT `ir_eval` format atomically-validated; closes
  the measure-before-trust loop for `OO_FAMILY_LEMMA` + the BM25F default. **S5.4** the lemma-conflation
  preview surfaced visibly in the Diagnostics panel (was download-only). **S5.5** S&P reclassification
  (verify-only, found done) + `int`/`eu` curation of 22 hand-verified transnational sources (G7/G20-News
  dropped: `g7uk.com` is national) + retention-instrument verify. **S5.6 SKIPPED** (stretch, gated on a
  genuinely-done queue; S6.1b carries the guard). **OPERATOR LIST (networked / maintainer-only, read
  FIRST):** (a) **the USGS MCS data fetch** — build the fetch client through the guarded factory + drop
  the real MCS release; the parser + agency + surface are ready and the fetch is the only missing piece.
  (b) **subjectivity lexicon sourcing/vetting** — replace the modest seed lexicons with vetted,
  license-clean, native-reviewed per-language lists (the mtime cache picks them up without a restart; add
  `configs/subjectivity/<lang>.txt` + bump `SUBJECTIVITY_AS_OF`); the engine measures any language that
  has a lexicon and honestly gaps the rest. (c) **GRADE THE GOLD SET** — the builder is one click away
  (Settings → Diagnostics → "Build an IR gold set"); grading it unblocks the `OO_FAMILY_LEMMA` + BM25F
  measurement (the lemma preview beside it shows what would merge). **CARRY-OVER for S6:** (d) the S5
  frontend slices are BROWSER-UNVERIFIED (Markets supply panel · gold-set grading UX + keyboard · lemma
  preview render) — a click-through is owed (fork-3). (e) a subjectivity reader HIGHLIGHT panel (the
  spans are emitted; the reader surface isn't built). (f) a future zh/ja subjectivity lexicon needs the
  segmenter (the script guard handles the mislabel case, not an in-script unsegmented one). (g) the many
  OTHER individual International sources still lack `int` — an ongoing data-curation step. LESSONS in the
  Session-rituals subsection above.
- **S6 CLOSEOUT + PROGRAM SUMMARY (2026-07-12, Tier-5 feature backlog — the FINAL session, branch
  `claude/s6-backlog`, onto `origin/0.2` base `1f2d6d21` = S1–S5 merged):** the mission was the
  highest-value CODEABLE subset of a months-deep backlog, staleness-guard FIRST. **SHIPPED (new):**
  **S6.4** the two missing attention producers — `on_the_horizon` (an upcoming agenda date within 45 days
  whose title/tags contain a currently-TRENDING keyword — a heads-up, lexical not causal; bucket `watch`)
  + `through_time` (an anniversary LENS: articles published on today's date in earlier years; bucket
  `context`; cross-time recall stays sacred — a lens, never a reweighting); neither touches the ruled
  alert boundary (urgent = provider-declared hazard ONLY). **S6.5** the LLM-perception (who/where/when)
  EVAL HARNESS — the ruled gate BEFORE any extraction: per-stratum precision/recall/HALLUCINATION vs a
  synthetic ×12-lang gold set, place-string vs coordinate scored apart, de-US-centring split, no
  composite; `run_perception_eval_selftest` + `/api/diagnostics/perception-eval-selftest`; extraction
  itself NOT shipped (waits for a model to clear the harness). Both adversarial-skeptic-clean +
  test-verified (the S5.1/S5.2/S5.3 skeptic passes had already hardened the honesty-critical patterns).
  **VERIFIED-ALREADY-SHIPPED (the staleness guard paid off again):** S6.1 content-provenance is end-to-end
  (source_type per channel + facet + reading-diet + the additive-restore carries it, merge.py:360-363);
  S6.3 write-batching is P1.8 (batch.py + a 10-test no-loss battery); **S6.2's CRITICAL half is met** —
  `read_artifact` (D7) accepts legacy formats FOREVER and is wired into restore (backup_v2.py:118), so no
  old backup is ever stranded; S6.6 deduced-events are already agenda-first-class (`mapDeducedToAgenda`)
  and the RULE-recurrence (fixed + weekday/week + origin_year) is in `catalog.py`. **CONSCIOUSLY PARKED →
  next cycle (the honest board is the deliverable):** (1) **S6.2 file-members-in-the-signed-VOLUME-artifact
  manifest** — a real feature (one portable artifact carries the wiki/OSM/model blobs), but data-safety-
  CRITICAL, needs the full skeptic matrix + the ZETA traversal-guard on every new manifest field, and is
  NOT a data-loss risk unbuilt (folder_backup already carries these blobs; the legacy reader survives) —
  building it rushed at a marathon's tail would violate the "entirely reliable or it doesn't ship" backup
  bar; design = reuse `folder_backup.collect_items`/`restore_folder_backup` (checksum dedup, never-
  overwrite, skip non-done) + a `file_members` manifest block + guards. (2) **S6.1b cited-provenance
  remaining slices** — the background citing-resolve job at corpus scale, denormalize `citing_source_id`,
  surface the citing trail ("the sources' sources"), wire the dormant `external_sources` (the model +
  slice-1 exist; the scale job + surface don't). (3) **S6.6 remainder** — RRULE recurrence expansion of
  IMPORTED VEVENTs, month-span banners ("Dry January"), `since:`-origin display, saved-filter smart
  calendars. (4) **S6.7–S6.9 comfort** — temporal linear/log toggle + mention-layer event-places +
  owner-measured OSM rate/ETA; the onboarding tour; the silent-disasters / law-takes-effect scenario cards.
  ---
  **THE PROGRAM (six consecutive autonomous sessions S1→S6, 2026-07-12, all merged to 0.2):** S1 Tier-0
  release kit (push-button P0 live-validation job + runbook; run/tag stay maintainer-only) · S2 Tier-1
  snappiness board (A9 riders reproducer-first, off-peak maintenance, guard-coverage sweep, /articles
  threadpool + FTS over-fetch bound, the 5 TB review = S3's input) · S3 Tier-2 DB architecture (D1/D2/D3
  persisted-columnar built GATED behind the httpfs binary; adaptive backup-volume sizing DB-9; DB-10
  memo) · S4 Tier-3 product quality (CJK date probe, ring-breakdown hover, Leads carousel, Insights-bar
  context absorption, composite-string i18n + translatable card titles, generic_terms detector, wizard
  sources-by-theme step) · S5 Tier-4 decided-rulings + instruments (USGS supply parser, subjectivity
  engine, IR gold-set builder, lemma preview, int-country curation) · S6 Tier-5 backlog subset (this
  session). Every session: skeptics-before-push (negative-space lens mandatory for parsers), the staleness
  guard (which repeatedly found "open" items already shipped → verify-and-mark, never rebuild), full-suite
  green, a closeout ledger row + carry-over. **CONSOLIDATED OPERATOR LIST (networked / maintainer-only —
  the whole program's outstanding human steps):** (a) **run the S1 push-button P0 live validation on the
  real corpus, then TAG v0.2.0** (the version reads 0.2.0 but 0.2 is not yet a tagged release; the tag is
  the gate the whole 0.2 cycle waits on; RE-RUN the validation if the live run predates the S3 DB-9 engine
  change) **[DONE 2026-07-18 — the maintainer ran the validation and tagged v0.2.0; see the current-cycle
  bullet + the 2026-07-18 version-sequence ruling]**. (b) **the networked FETCHES / bundles:** the per-OS httpfs crypto binaries (turns D1/D2/D3 on),
  the USGS MCS data, subjectivity lexicon sourcing/vetting, the Wikidata ring gap run — none fabricated,
  all gated on egress. (c) **GRADE THE GOLD SETS:** the IR gold set (Settings → Diagnostics, one click)
  unblocks lemmatization + the BM25F default; a graded who/where/when perception set (+ a model that
  clears the harness) unblocks LLM extraction. (d) **the keyword-log export** (the open-class stoplist
  review loop). (e) **browser CLICK-THROUGHS** of every conservative+flagged frontend slice (fork-3; no
  headless harness in-session). **RECOMMENDED NEXT CYCLE — TOP THREE:** (1) **close the v0.2.0 tag** (the
  live P0 run + tag — everything else is downstream of the release actually shipping); (2) **the S6.2
  file-members-in-volume backup completeness** (data-safety, full skeptic matrix — the top parked item);
  (3) **the versioned-sources revamp** (Wikipedia + laws as first-class Articles) — EXCLUDED all program
  (ruling #3, P0-gated), the single largest designed capability still unbuilt. Full parked-items detail:
  the S6 brief §"Explicitly NOT yours" + each session's carry-over above.
- **VERSIONED SOURCES AS FIRST-CLASS ARTICLES — WIKIPEDIA + LAWS (maintainer-directed 2026-07-10;
  MARK FOR THE FUTURE VERSION — do NOT build now; full design in `docs/FUTURE_DEVELOPMENTS.md` →
  "Versioned sources as first-class Articles"):** the maintainer wants ALL Wikipedia articles of ALL
  UI-language editions AUTO-INGESTED as first-class corpus `Article`s (metadata linking to the
  original source, through the ONE `index_article` hook → keyword engine + date extraction +
  When×Where×Who + sentiment, exactly like any scraped article) — "they ARE articles, treat them as
  such." The ONLY difference: wiki text changes over time, so the **track-change / audit / version
  history is a per-article LINKED LAYER keyed by `article_id`, the same way a synthesis/translation
  links via `ArticleAnalysis`.** **Country LAWS get the identical treatment** — `LawDocument` becomes
  a first-class Article (keywords/metadata/dates) with `LawRevision` as its linked audit layer. The
  unifying pattern = **a versioned source is an Article + a linked revision/audit trail**. CODE-VERIFIED
  current state (2026-07-10): watched wiki PAGES already become corpus Articles via `src/wiki/corpus.py`
  (keyworded + searchable), but downloaded DUMPS are files-only (no auto whole-edition ingest — this is
  the standing "dumps→corpus" gap + the 2026-06-12 superseding "auto-track the whole edition after a
  dump download" ruling, now the plan of record); LAWS are a SEPARATE tracked vertical (`src/law/`,
  `LawDocument`/`LawRevision`, "mirrors the Wikipedia tracker") that does NOT flow through `index_article`,
  so laws are NOT yet corpus Articles. HONEST MECHANISM: full-edition bulk ingest = **dump-as-baseline +
  `recentchanges`-delta**, NEVER per-article network scraping (won't scale to ~6M+ articles/edition).
  **SCALE-CRITICAL + GATED: tens of millions of articles = squarely the 5 TB / storage-hygiene /
  segmenter problem (`SCALE_ROADMAP.md`) — do NOT start before the P0 scale set lands.** Recorded on the
  roadmap under "Wikipedia as a living source" + the world-law vertical.
- **SCALE MANDATE (maintainer ruled 2026-07-09; the consolidated roadmap lives in
  [`docs/product/SCALE_ROADMAP.md`](docs/product/SCALE_ROADMAP.md) — read it before picking
  work):** a live 4–5-day run grew the corpus to **~100–130 GB**; the app must be designed to
  handle **5 TB** databases with proper indexing and stay **SNAPPY** ("responsiveness is quite
  important, otherwise it will slow or block user adoption — this app is useless if it is not
  used"). **Large-database data-safety is THE top priority: at 100 GB+ the backup tool CRASHES
  the app (no safe in-app copy path exists; import untestable).** Field event 2026-07-09: the
  4-day run self-stopped hours before the maintainer returned (root-cause PENDING the
  diagnostics zip); unlock is very slow again at this scale (the 07-08 ledger's 60 s Item-8
  finding, escalated). P0 = backup/restore at scale (ATTENDED — kill every whole-corpus
  materialization incl. the plaintext-snapshot decrypt; streaming/bounded-RAM/resumable/
  verifiable/incremental via changed-volume re-emit) · crash root-cause + WAL-checkpoint
  hygiene · unlock-at-scale · a scale test harness (everything so far was verified at MB–GB).
  COROLLARIES: the D1 persisted columnar store and the zh/ja/th segmenter rulings are now
  SCALE-critical, not nice-to-have; interim backup = app stopped → filesystem-copy the data
  folder (encrypted at rest).
- **NEXT CYCLE = 0.2, GATED ON THE P0 SCALE SET (maintainer ruled 2026-07-09, option "A" —
  supersedes the earlier 0.1.0→0.11.0 idea):** v0.2.0 tags when backup-at-scale is verified on
  the live corpus + the collector OOM fix + unlock-at-scale land ("0.2 = the version that
  survives a 100 GB field run"). Mechanics mirror the 0.09→0.1 flip (#547 batch): pyproject
  0.1.0→0.2.0 · tag v0.2.0 with a WATCHED-green CI run at the SHA · the maintainer renames the
  default branch 0.1→0.2 · every CLAUDE.md cycle-branch reference rewritten in the SAME PR.
  HARD GUARD: never flip while parallel sessions are in flight on `origin/0.1` (the #548
  stale-base revert precedent) — execute in a quiet window after the gate passes. Full row in
  `docs/product/SCALE_ROADMAP.md` (Ruling-gated #4).
  **EXECUTED 2026-07-10 (version+docs half, this PR — maintainer-asked "bump to version 0.2"):**
  pyproject `0.1.0→0.2.0` + every CLAUDE.md/README/CHANGES/CONTRIBUTING current-cycle-branch
  pointer rewritten `0.1→0.2` (historical `0.09`/`0.1` records preserved). Guard clear — NO
  parallel PRs were open on `origin/0.1` at flip time (`list_pull_requests base=0.1 state=open`
  → empty), and the branch was cut from the fresh `origin/0.1` tip. **STILL PENDING, deliberately
  NOT in this PR (maintainer + CI):** (1) the maintainer renames the default branch `0.1 → 0.2`
  right after merge (mirrors #547); (2) the `v0.2.0` TAG waits on the P0 live-corpus scale
  validation — P0.1/P0.2/P0.3 engines are shipped awaiting the maintainer's live run, and
  **P0.4 unlock-at-scale is still unresolved** (SCALE_ROADMAP P0). So the version now reads
  0.2.0 but 0.2 is not yet a tagged release. **[RESOLVED 2026-07-18: P0.4 was fixed by
  Session A, the maintainer ran the live P0 validation and TAGGED v0.2.0 — see the
  current-cycle bullet + the version-sequence ruling.]**
- **FIELD-TEST 2026-07-08 — full intake + diagnostics action plan captured in
  [`docs/product/field-test-2026-07-08/LEDGER.md`](docs/product/field-test-2026-07-08/LEDGER.md)
  (PR #583; items 1–7 merged via #580). CAPTURE-ONLY session on a live 59,566-article /
  974,062-keyword / 2.28 GB corpus.** 11 items; the ledger's top "SESSION SUMMARY" has the
  index + priorities. HEADLINE: the corpus is HEALTHY but the app does NOT SCALE, and the
  scaling failures now cause CRASHES + DATA LOSS, not just slowness. **P0 next-session work
  = stability/data-safety:** the app OOM-crashes under load (2.28 GB corpus + 6–10 GB backup
  + an analytics death-spiral) and a crash in the maintainer's DELIBERATE disposable-VM test
  = total corpus loss (Item 11 — the fix is "don't crash" + easy opt-in persistent data_dir
  + reliable/VERIFIABLE/resumable backup [Item 9], NOT "stop using DispVMs"); the ROOT cure
  is Item 8's perf work — an EXPRESSION INDEX on `coalesce(published_at,created_at)` (735 s of
  full scans), CACHE the polled `signals/alerts`/`trending-windows`, SINGLE-FLIGHT polling +
  a CONCURRENCY CAP + server DEADLINES to stop the request death-spiral, and turn ON the built
  `keyword_daily` rollup serve. **P1:** job-ify heavy sync handlers (Item 4 Governments
  auto-load; Item 10 diagnostics `/all` — already bundles everything + keeps the keyword
  corpus separate, just needs a button + a job + per-member deadlines); keyword quality (Item 2
  translation = 15.2% ring coverage; zh/ja/th SEGMENTER since junk is NOT prunable at β 0.95;
  ko/vi/mr stoplists; and the manipulation cards flood/bury need LANGUAGE-AWARENESS — they
  surface leaked filler + language artifacts). **P2 feature items:** Item 1 (indices OECD ids =
  a 3-letter→2-letter FRED-code bug), Item 3 (auto-pick Wikidata-discovery countries + i18n),
  Item 5 (Agenda: flood article-extracted dates + a global election/summit calendar), Item 6
  (World-map ooSubtabs + story lenses). **OUTSTANDING MAINTAINER DECISION:** Item 7 rare-earths —
  no free spot-price source; options captured (USGS supply-data [recommended] / free proxy /
  authorized paid assessor / defer), maintainer had not answered at close. All honesty
  non-negotiables preserved in every item (no fabricated numbers/scores; degrade loudly).
- **V0.1 RELEASE EXECUTION (maintainer ruled 2026-07-02, verbatim "proceed with everything
  autonomously… Go with your plan. Push everything to go 0.1", plus the same-day coherence+ethics
  mandate): the release is being EXECUTED under full autonomy.** The sequenced plan + the
  arbitration log (what was closed with evidence vs consciously accepted for 0.1-alpha) live in
  `docs/product/RELEASE_0.1_PLAN.md`; the gate (`docs/product/RELEASE_0.1_RC_GATE.md`) was
  reconciled 2026-07-02 with per-row evidence. LOAD-BEARING FINDINGS any parallel session must
  know: (a) the default branch had NO completed CI run 06-29→07-02 (all superseded-cancelled;
  "merged ≠ green" became structural — ci.yml gains workflow_dispatch; dispatch + WATCH a run to
  completion at any SHA you must trust); (b) the mypy ratchet was RED at HEAD (132>127, fixed) —
  re-run it locally before merging (the in-repo .venv py3.13 runs the FULL suite: 2496 passed at
  c217c5f); (c) the wheel/sdist carried ZERO data files (packaging fixed + fresh-venv boot-proven);
  (d) custody auto-log default flipped ON per the Item-N ruling (the UI text already claimed it);
  (e) field-test mode is now OPT-IN (OO_FIELD_TEST=1) for the public tag; (f) version flips
  0.0.9→0.1.0, tag v0.1.0 (release.yml verifies tag==pyproject and now gates on tests).
  **STALE-BASE REVERT INCIDENT 2026-07-02 (must not recur):** PR #547 landed the whole 0.1
  release batch on 0.09 (8ac2615: version flip, packaging fix, self-heal battery, host-header
  guard, honesty defaults, docs sweep). Then PR #548 — a parallel `article-language-equilibrium`
  branch CUT FROM A BASE BEFORE #547 — merged and SILENTLY REVERTED almost all of it (version→0.0.9,
  packaging + MANIFEST.in gone, self-heal/host-guard/main.py reverted, my 4 test files deleted,
  USER_MANUAL −817). Recovered on branch claude/version-upgrade-plan-umv9xd (PR #550) by keeping my
  full tree (`git merge origin/0.09 -s ours`) + cherry-picking ONLY origin's genuinely-new date
  work (dateextract.py/datediag.py/test_dateextract_relative_c.py) + unioning shipped.csv. LESSON:
  before cutting/merging a branch, ALWAYS `git fetch origin 0.09` and rebase onto the FRESH tip; a
  branch cut from a stale base re-applies old file states as "changes" and reverts newer work with
  NO conflict. Verify `git show origin/0.09:pyproject.toml` still reads 0.1.0 before trusting the base.
  **PRE-0.1 FIELD BATCH SHIPPED (PR #550, maintainer field report 2026-07-02):** (1)+(4) unlock no
  longer freezes — `/unlock` runs init_db + airplane synchronously then backgrounds the expensive
  upkeep (ANALYZE/seed/COUNT/warm); `GET /api/system/startup-status` + a "Preparing your corpus…"
  progress view on unlock.html (browser-verified: button returns ~0.8s, honest phase text, no fake
  %); (2) Library source-tag click fixed (a `t is not defined` ReferenceError in updateMselSummary);
  (3) unified import — recursive subfolder scan, real progress bars, honest phases, legacy backups
  folded in (multi), import SUMMARY, and the VOLUMES+PARITY RESTORE FAILURE root-caused (scan handed
  the parent dir but volumes.json lives in a subfolder → load_manifest threw, swallowed into "see
  console"; now uses the exact subfolder path + surfaces the real error); (5) unknown-language
  `reconcile_article_language` (offline text detect → keyword-majority fallback, deduced channel
  only, wired into the reindex cleanup pass). **.eml SENDER-IP GEOLOCATION SHIPPED 2026-07-02
  (the deferred item):** `sender_origin_ip()` (src/ingest/email.py) reads the SENDING mail-server
  IP from the .eml Received chain (scans oldest→newest hop, first GLOBALLY-ROUTABLE IP wins;
  private/reserved/doc ranges skipped via `is_global`; IPv6-aware; no network — the IP is already
  in the bytes), stored on the SAME `Article.server_ip`/`ip_observed_at`/`server_ip_reason` columns
  web articles use, so newsletters surface on the ooMap "Server IPs" layer + geolocate through the
  offline DB-IP lookup FOR FREE (`server_locations` already reads all sources). RECIPIENT-SAFE by
  construction (sender infrastructure, not the recipient — anonymize-at-ingest is unchanged) +
  DEDUCED/honest (reason says "may be a relay"; a stripped chain stores NULL + a stated reason, never
  a guess). tests/test_email_ingest.py (+3: public-hop-skips-private, IPv6/only-private/stripped,
  ingest-stores-it). LESSON: `ipaddress.is_global` correctly rejects the RFC-5737/3849 DOCUMENTATION
  ranges (203.0.113.x, 2001:db8::) — use real public IPs (8.8.8.8) in geolocation tests.
- **KEYWORD STOPLIST — open-class review loop + residual gaps (2026-07-01; user DEFERRED the
  next round to a fresh session):** function-word garbage is SOLVED — #525 vendored full
  stopwords-iso lists for 18 managed languages, #528 added temporal-deictic adverbs (gestern/
  вчера/mañana) + the Bosnian→hr alias, #530 shipped the open-class DETECTOR
  (`analyze_keyword_log.py --generic-terms`) + a closed-class (English indefinite pronouns) +
  platform-furniture (podcast/newsletter/cookies · de inhalte · es publicidad) batch. REMAINING:
  (1) **THE OPEN-CLASS REVIEW LOOP** — the maintainer exports a fresh keyword log, runs
  `--generic-terms` (df-ubiquity candidates), hand-picks garbage from the DUAL-USE tail (topics
  like health/policy/system/salud STAY content), and a session applies the reviewed per-language
  batch into `CURATED_SCOPED_STOPWORDS`/`PUBLISHING_BOILERPLATE_SCOPED` (scoped, collision-free)
  or `language_stopwords["en"]` (global, en-safe) per the stoplist-architecture lesson. This is
  the honest way to go deeper — propose→human-review→apply, never a category sweep. (2) **sr + az
  are managed but under-covered** — sr (Serbian, largely CYRILLIC — no clean transliteration from
  the Latin hr list) + az (Azerbaijani, Turkic ≠ tr) run on the English default + a thin global
  sliver and LEAK grammar (probed: sr јуче/данас/новом, az dünən/yeni); they need a proper base
  stoplist SOURCE (both ABSENT from stopwords-iso), not a fabricated list. (3) **fr publishing
  furniture** (publicité/contenu) still leaks — fr takes the `language_stopwords` branch so the
  scoped channel is ignored; a fr batch would globalise (collision-check needed); low-df, deferred.
  (4) OPTIONAL: surface the `--generic-terms` detector IN-APP via a `generic_terms` block in
  `src/analytics/engine_report.py` so it rides the exported diagnostics log automatically (like
  `ring_candidates`/`lemma_preview`), closing the loop without the offline script. (5) inflected
  generic VERBS (zeigen/finden/voir) = the P4.3 lemmatization + a lemma denylist, gated on the P3
  IR eval harness + a graded gold set (the still-outstanding operational input). All three PRs
  merged to 0.09; existing corpus junk clears on the next "Clean up keywords" re-index.
- **DERIVED-LAYER SCALING (5A-bis / "1000×") — CORE SHIPPED THIS SESSION 2026-07-01 (the freeze fix for
  the WINDOWED Insights/trends aggregations; ALL merged to 0.09; per-slice detail in
  `docs/ledger/shipped.csv`; design + test plan in `docs/design/SCALING_DERIVED_LAYER_1000X.md`):**
  the measured freeze — windowed `top_terms`/`trending`/`trending_windows` scan the multi-GB
  `keyword_mentions` table (~17 s on the live 61K-article corpus, each in-range row a SQLCipher page
  decrypt). SHIPPED: **D2** (PR #535: `columnar.py` `build_keyword_daily` streamed rollup builder +
  `keyword_meta` + `windowed_term_counts`/`windowed_top_terms_raw` serve primitives + `keyword_daily_parity`;
  in-memory parity proven). **D3** (PR #536: `refresh_keyword_daily` — incremental merge of the new mention
  tail via a portable DuckDB MERGE, with the CORPUS-EPOCH GUARD that forces a FULL rebuild on any
  re-index/prune, defeating the delete-then-reinsert double-count trap; corpus_epoch PASSED IN). **ROLLUP
  BENCHMARK** (PR #538: `src/monitoring/rollup_benchmark.py` + `GET /api/diagnostics/rollup-benchmark` +
  Settings→Diagnostics button — builds the rollup in-memory over the REAL corpus and times live-vs-rollup
  windowed aggregation + parity, so the win is MEASURABLE on the operator's data; READ-ONLY). **OPT-IN
  IN-MEMORY SERVE** (PR #538: `src/analytics/rollup_serve.py`, `OO_COLUMNAR_SERVE=1`, OFF BY DEFAULT — a
  process-lifetime in-memory rollup built once in a background thread serves `queries.top_terms` windowed
  + `queries.trending` [→ covers `trending_windows`/Home FOR FREE] instead of scanning mentions;
  time-window-only [never per-country/corpus-wide], fallback-to-live on ANY miss, full-rebuild cadence via
  warm_cache, `basis` disclosure attached; numbers identical to live today). KEY INSIGHT (see the
  DERIVED-ROLLUP Lessons entry): in-memory columnar WINS for windowed queries build-once-serve-many, so the
  windowed speedup does NOT require the persisted store. **REMAINING (next session):** (1) **D1 persisted
  store** — STILL BLOCKED on bundling per-OS `httpfs` crypto binaries (operational/networked; the
  GCM-native hope was REFUTED, P2.4); a DURABILITY win (survive restart / no per-process rebuild), NOT
  needed for the in-memory serve. (2) **the CANONICAL corpus-epoch mechanism** (a `derived_meta` table +
  `bump_corpus_epoch` wired into `reindex_all_batch`/`reindex_articles`/`reindex_imported_articles`/
  `prune_orphan_keywords`) — DESIGNED (D3's `refresh_keyword_daily` takes `corpus_epoch` as a param + the
  guard is tested) but NOT BUILT; the opt-in serve sidesteps it with a full rebuild, so it is only needed
  when a persisted INCREMENTAL serve (D1) lands. (3) **D4** `source_coverage` rollup (per-country map). (4)
  render the `basis` disclosure VISIBLY in the UI (payload-only today; numbers match live so no visible-
  caveat non-negotiable is breached, but the as-of staleness should surface). (5) **OPERATIONAL (maintainer):
  run the rollup benchmark on the LIVE 60K/932K corpus** to quantify the real win + decide whether the D1
  httpfs packaging is worth it — the measure-before-build gate for D1.
- **KEYWORD-ENGINE OPTIMIZATION — STRATEGY + PROGRAM (2026-06-26 research fold-in → the 2026-06-25
  build session; strategy of record = [`docs/design/KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md`](docs/design/KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md),
  the three verbatim research reports under `docs/research/keywords/`; per-slice build narration is
  compressed per rule 5a, one `docs/ledger/shipped.csv` row each):**
  **KEY VERDICT (both research streams + the code converged, independently confirming the project's
  own DATA_ARCHITECTURE_SKELETON / SCALING_DERIVED_LAYER_1000X):** the pain is a DERIVED-STATE-REBUILD
  problem, NOT a search-engine problem — KEEP the rule-based trusted index, fix the rebuild + the
  rollups + the junk, and AUGMENT with a LABELLED recall layer that never feeds the trusted index.
  **EMPIRICAL FINDING — P2.4, the DuckDB-GCM hope is REFUTED (verify-before-build, tested on DuckDB
  1.5.4; do NOT retry without re-probing):** the hypothesis that DuckDB ≥1.4 writes an authenticated
  AES-256-GCM store NATIVELY (without `httpfs`) is FALSE — it refuses an encrypted WRITE without
  `LOAD httpfs` (OpenSSL); the only no-httpfs write path is the explicitly-UNSAFE mbedtls, i.e. the
  forbidden fabricated security. So `secure_crypto_available` stays gated on httpfs, the engine stays
  IN-MEMORY, and the persisted-rollup perf win remains blocked on bundling per-OS httpfs binaries
  (OPERATIONAL, needs a networked machine). Second finding: `enable_external_access=False` also
  blocks a file ATTACH outright. Recorded in `columnar.py`'s own EMPIRICAL FINDING block.
  **DELIBERATE EXCLUSIONS:** SPLADE is ruled OUT (CC-NonCommercial weights + torch + a multilingual
  gap) — never bundle it. Licence discipline for any future bundled artifact: CC0-first; Wiktextract
  CC-BY-SA would need its own ruling.
  **SHIPPED (the whole autonomously-buildable program; one shipped.csv row per slice):** P1 unblock-
  the-rebuild (backend re-index JOB with a persisted cursor · keyword-only re-index scope · batched
  commits · FTS5 `'optimize'` tuning) · P4.2 `reconcile_keyword_language` (the first-write-wins fix
  for the measured 16% / 40%-of-head language mismatch, perf-safe via a covering map, never the
  codec-trap join) · P3 the IR retrieval-eval harness end-to-end (native metrics, per-language +
  per-axis with n, no composite; gold-set loader + BM25F A/B + the in-app endpoint + panel button) ·
  P5.1 BM25F per-column ranking + interactive When/Where/Who facets with a drill · P4.3 simplemma
  lemmatization at the DISPLAY layer (reversible, `conflated_by` provenance, never `_normalize`) plus
  its `lemma_preview` + self-test instruments.
  **SINCE-CLOSED (formerly "remaining" here — verified stale):** lemmatization is now RULED DEFAULT-ON
  (2026-07-18, after the maintainer reviewed `lemma_preview` on the live corpus) · the zh/ja/th
  SEGMENTER shipped 2026-07-10 as the `[segmentation]` extra · the collector-path write-batching
  deferral is now evidence-justified by the 2026-07-23 fast-box `writer-bound` verdicts (tracked in
  that entry, not here).
  **REMAINING:** P5.2 the static-embedding recall layer (model2vec/potion numpy-only, NO torch, +
  sqlite-vec inside the encrypted file + RRF, labelled/disposable) — gated on the P3 gold-set pilot,
  and its PER-LANGUAGE quality must be verified before trusting it · P6 OpenTapioca entity→QID
  (operational/networked) · the persisted P2 rollups (blocked on the httpfs binaries above) · and the
  one OPERATIONAL input the whole measure-before-trust loop still waits on: **a human-graded gold set
  over the maintainer's own corpus** (corpus-specific, cannot be bundled; the builder is one click
  away in Settings → Diagnostics), which is what would let the BM25F default be picked on evidence.
- **DEFERRED DEAD-UI-CODE CLEANUP — a BROWSER-VERIFIED pass (tracked 2026-06-26; do NOT do blind in a
  non-browser session):** a repo-cleanliness survey found the file tree CLEAN (no tracked junk/zero-byte
  files; `.gitignore` covers venv/pycache/data/build; the old orphan FILES `scripts/import_eml.py` +
  `src/database/async_db.py` already gone; `docs/archive` + `field-test-*` are deliberate history). The
  ONLY residual debt is dead UI JS/DOM the ledger already deferred — gathered here as ONE verified
  worklist so it isn't lost: (1) the RETIRED temporal-map functions in `src/static/app.js` (~lines
  9318–9732: `loadTimemap`/`renderTimemap`/`buildTmap*`/`showTmapDetail`/`tmapNearby`/`onTmap*`/
  `wireTmap*`/`tmap*Prefs`/`TMAP` state — unreachable since the Map tab routes `timemap:
  loadOoMapCoverage`) — **but PRESERVE the SHARED helpers ooMap still uses** (`kindColor`, `TMAP_KINDS`,
  `fmtYear`, `fmtDate`, `dateToT`, `lon2x`/`lat2y`, `tmapFindCoverage`), which are INTERLEAVED with the
  dead ones (the ledger hazard: a wrong deletion passes `node --check` but breaks the map at runtime);
  (2) the orphaned handlers `loadIndicesData` (app.js:5560) + `loadMarketData` (:6080) — buttons gone;
  (3) the retired `#corpus-win` modal DOM (`index.html:1987`) + the `openCorpus(term){ openAnalysisFor
  (term); }` wrapper + the `corpus-win` close-listener (app.js:12407) — needs the `#mm-kit` relocation
  untangled first; (4) the orphaned `#onboard` welcome-card i18n keys (en.json:537/539/834 + ×12) — the
  hot-conflict locale files, so coordinate with parallel sessions. **DO NOT DELETE `firstRun`
  (app.js:4306) — it is test-pinned (test #396) + intentionally retained.** WHY DEFERRED: browser-
  unverifiable here + the interleaved-shared-helper hazard + a parallel session merges into `0.09`
  (deletion PRs risk conflicts in `app.js`/locales). ACCEPTANCE for the eventual pass: `node --check` +
  the absorbed capabilities still work (the Desk lesson — the temporal map's features survive in ooMap)
  + the relevant tests green; resolve locale conflicts ADDITIVELY.
- **CONTENT-PROVENANCE CLASS — descriptive ingestion-channel metadata (maintainer concept 2026-06-26;
  DESIGN-ONLY, full record in `docs/FUTURE_DEVELOPMENTS.md` → "Content-provenance class"):** classify
  each item by WHAT KIND of content/channel it is (newsletter · web-article · wiki · official-statistic ·
  law · market · discovery). It is the cleanest metadata to add because it is an ASSERTED FACT known by
  construction (the ingest path knows the channel) → no classifier, no fabrication; and it is
  DESCRIPTIVE, never a quality/credibility score ("newsletter" = a channel, not "less reliable") — so it
  fits the no-score / no-fabricated-metadata non-negotiables. Corroborated by the keyword-engine IR
  research (Aleph/Datashare make content TYPE a primary facet; strategy P4 faceted retrieval). STATE +
  GAP (code-verified): `Source.source_type` (indexed `String(50)`, no constraint) ALREADY exists + is
  used (stats="statistics", `api/stats.py:404`) but is INCONSISTENT — the newsletter source is created
  with no `source_type` so it defaults to "news" (`api/ingestion.py:181`) = newsletters mislabeled as
  news. SLICES: S1 enrich `source_type` into a controlled vocab + populate per ingestion path +
  deterministic backfill from the source domain (no migration; fixes the mislabel; `idx_source_type`
  makes the facet fast) → S2 expose as a facet (fold into the keyword-engine P4 facet track) → S3
  reading-diet-BY-TYPE (extend `analytics/concentration.py`) → (later, gated) a denormalized per-article
  `provenance_class` column only if a join proves slow. Tier-2 (a DEDUCED content GENRE from text) is a
  SEPARATE, labelled, later layer — never conflated with the asserted Tier-1 channel class.
  **BACKWARD-COMPAT (maintainer asked, code-verified): NO break.** S1 is schema-neutral — `source_type`
  is already carried by the additive-restore merge (`backup/merge.py:320-324`) + the file backup; only
  values change; old↔new both safe; a differing type on an existing domain is a REPORTED conflict
  (local wins), never corruption. The optional later per-article column follows the proven
  additive-nullable-column + migration + boot-self-heal + deterministic-backfill pattern (like
  detected_language/sentiment) + one line in `_merge_articles`' explicit column map; the ONE
  verify-before-build = the staged-upgrade migrates an OLDER incoming backup to head BEFORE the merge
  SELECTs the new column (the shipped cross-version restore floor / RC-gate T4 already does this —
  confirm). Export (CSV/JSON envelope) = additive, unknown-field-tolerant, no break. OPEN Qs: exact
  vocab; defer the per-article column (recommended yes); fold S1-S3 into P4 (recommended yes).
- **CLICKABLE IN-ARTICLE KEYWORDS → the keyword analysis window, with a stats hover (maintainer concept
  2026-07-01; SLICE 1 SHIPPED 2026-07-02, browser-unverified per fork-3; full record in
  `docs/FUTURE_DEVELOPMENTS.md` → "Clickable in-article keywords"):** in an article the user SEES its keywords
  and CLICKS one → opens the unified analysis window (`#an`) on the KEYWORD subtab, seeded with that keyword,
  in a new browser tab. **SLICE 1 SHIPPED (shipped.csv row; `src/static/reader.js`/`app.js`/`reader.css` +
  `tests/test_clickable_keywords.py`):** the reader's Keywords-tab list is clickable AND the article's REAL
  indexed keyword terms are marked inline in the Read body (dotted-accent underline), each opening a new SPA
  tab hydrated from `?analyze=<term>&tab=keywords` → the Keywords subtab seeded with the term. Honesty by
  construction — marks ONLY the trusted corpus-keyword index (never a naive word scan); ONE eager loopback
  `corpus-keywords` fetch serves both the marking and the Keywords tab; a pure boundary-aware segmenter (word
  boundaries for spaced scripts so "election" never marks inside "reelection"; substring for CJK/Hangul;
  longest-first for phrases) was unit-verified in node; `markArticleBody` is fully guarded (a failure leaves
  the Read pane untouched). SPA: `_anBootTab` stashes the `?tab=` target during boot hydration and applies it
  once `_anSubtabs` exists (the ordering fix — `_hydrateCardCorpus` runs before the subtab component is
  wired). **REMAINING — SLICE 2 (design, maintainer undecided):** a #oo-tip-style hover of REAL stats (mention
  n + article spread · trend RATE · language/ring translation · top co-occurrences) — counts only, NO score,
  method+caveat visible. OPEN: which stats; parity in the SPA Articles/search lists; perf reads via the
  article_id-indexed mention tables (never the keyword→articles codec-join trap); the fork-3 browser
  click-through of slice 1.
- **HOME "LATEST IN YOUR CORPUS" SECTION — recency LENS + transparent substance FILTER (maintainer
  concept 2026-06-26/27; DESIGN-ONLY, full record in `docs/FUTURE_DEVELOPMENTS.md` → "Home 'Latest in
  your corpus' section"):** a Home "latest news" section that avoids very short click-bait by selecting
  on article LENGTH + the number of IN-ARTICLE SOURCES, criteria CLEARLY MARKED + user-adjustable by tag
  + content-type. (An earlier draft was recorded then closed unmerged — re-recorded here WITH the
  discussion refinements; PR #496 was closed per the "mark only when we agree" cadence.) TWO hard
  framings: (1) a recency LENS on the redundant Home launchpad (#8), NEVER a corpus reweighting
  (cross-time recall sacred); order by `created_at` (un-spoofable), not `published_at`. (2) the substance
  gate is a TRANSPARENT FILTER, NEVER a quality/click-bait SCORE — two GATES the user sets+sees (≥min
  words AND ≥min cited-sources), order stays recency, each shown article shows its REAL values, never
  labelled "click-bait". Criteria = REAL indexed facts: `Article.word_count` (`idx_article_word_count`) +
  outbound `ArticleLink` count (NEVER `external_sources.credibility_score`). DISCUSSION REFINEMENTS baked
  into the doc: (a) **CJK/Thai length catch** — `word_count=len(text.split())` is meaningless for
  unsegmented zh/th (per the 2026-06-27 engine report) → the length gate must be SCRIPT-AWARE; (b)
  **near-dup collapse** of wire-reprints into one fresh story (reuse `src/signals/near_dup.py`) — the
  biggest practical win; (c) **followed/faceted vs flat** — the corpus is strongly non-Anglophone (sv›en›
  el›sr…), so a tag/topic-scoped or per-type-balanced latest beats a flat firehose; (d) per-content-type
  defaults; (e) dim-with-values vs hide (OPEN Q, rec: dim+toggle). **S0 SHIPPED 2026-07-02 (the
  calibration blocker is cleared): `src/analytics/article_length.py:article_length_report` +
  `GET /api/diagnostics/article-length` (+download) + a Settings→Diagnostics button + tests/test_article_length.py.**
  Read-only, counts-only, NO score: the DISTRIBUTION (n/min/max/mean/median/p10-95 + fixed-bucket histogram)
  of `word_count` AND cited-source count (outbound `link_type='external'` ArticleLink rows, zeros included,
  internal ignored), broken down PER content-type (`Source.source_type`) and PER language — with the
  unsegmented languages (zh/ja/th, from `analytics.managed.UNSEGMENTED`) FLAGGED per-language so a word-gate
  is never blindly applied to them (the CJK/Thai catch). One article-row scan (a diagnostic run occasionally,
  cost documented); the cited-source counts come from `article_links` (no article decrypt). The maintainer
  runs this on the live corpus to pick honest per-content-type thresholds. REMAINING: S1 recency endpoint
  (`created_at` order + min_words/min_sources + tag/content_type facets + script-aware length rule + near-dup
  collapse) → S2 Home panel → S3 per-type defaults/followed-scope/dim-toggle. FOLD into the content-provenance
  + keyword-engine P4 facet track. (Only anchor before S0: ~190 content-words/article avg.)
- **FIELD DIAGNOSTICS 2026-06-27 — measured findings (full record in `docs/FUTURE_DEVELOPMENTS.md` →
  "Field diagnostics 2026-06-27"):** from the maintainer's exports on a live 2,259-article / 99,662-kw /
  179,395-mention corpus (2-core 4.4GB Qubes, encrypted, columnar in-memory). ENGINE HEALTHY (selftest
  42/42, noise 0.5%, Heaps β=0.756). ACTIONABLE: **F1 (BUG, shippable, prioritise)** — 6/25 Home cards
  LOSE their corpus on click; the producers `lonely_signal`/`ownership_change`/`recipe_promise`/
  `story_lineage` emit cards with NO `article_ids` so the click runs a synthetic-seed text search that
  loads 0 (e.g. seed "lineage:1575"/"2294:2026-06-27"); FIX = carry `article_ids` → `openAnalysisForIds`
  (the pattern echo_chamber/source_laundering/space_time_convergence/headline_body_mismatch already use);
  acceptance = the home-cards diagnostic reports 0 mismatched. **[F1 SHIPPED 2026-07-01]** #513 hard-linked
  weather_corroboration/lonely_signal/ownership_change/story_lineage; the "do we forget anything?" re-audit
  follow-up added framing_split + emotion_profile (both held an exact analysed set — framing_split its `rows`,
  emotion_profile the mention articles). `recipe_promise` is NOT a real producer (loose name); residual
  mismatches (rising/diet_self_audit/recipe_source_candidates) are legitimately setless — a keyword-term seed
  that re-runs the same search, or a whole-corpus aggregate. **F2 (PERF — VALIDATES the keyword-engine
  strategy, build there):** (i) the single WRITER GATE is SATURATED during scraping (34 waiters, max_wait
  210s, scrape throttled 161kbps vs 500 = write-bound not network-bound) — this IS the live measurement
  the ledger said the deferred COLLECTOR-path write-batching was waiting for → build strategy P1.3; (ii)
  analytics FREEZE at just 2,259 articles (insights_trending 26-29s, keyword_export 34s, supergroups 12s,
  Home trending_windows 5-13s, associations 4-7s; columnar available:false) → build strategy P2 rollups +
  P2.4 DuckDB-GCM verify. **F3** rising-card stoplist leaks (annons/koji/ali) → strategy P4.2 + stoplists.
  **F4** date-extraction recall gap (36.6% coverage, 401 date-like-but-unextracted incl. 45 cjk). **F5**
  polling storm (~4,400 status polls) → consolidate to one poll/SSE + backoff. **[F5 SHIPPED 2026-07-01 (#518)]**
  the real storm source was the VITALS poller hitting /api/system/vitals + /api/scheduler/activity every 2s for
  the WHOLE scrape even panel-closed; it now backs off to 6s chip-only (the network poll was already a SEPARATE
  adaptive `_adaptivePoll`). Full SSE consolidation not needed.
- **FIELD DIAGNOSTICS 2026-07-01 — live overnight test, 6 non-keyword exports analyzed (perf report ·
  benchmark · date · network preflight · debug bundle · home-cards; the keyword exports went to the parallel
  session). SHIPPED this session, ALL MERGED (per-fix detail in `docs/ledger/shipped.csv`):** F1 home-cards
  hard-linking #513 + the framing_split/emotion_profile re-audit follow-up #521 (the home-cards mismatch);
  IPv6 malformed-URL link-extraction crash #515 (debug-bundle "link indexing on ingest failed"); favicon
  /favicon.ico 404 #517; polling-storm adaptive-vitals-cadence #518 (= the 2026-06-27 F5). **RESIDUAL /
  NOT-YET-DONE (recorded so it is NOT lost at session close):** (a) **fetch_failed ≈ 13,678** (perf report) is
  a RAW count, NOT broken down by verdict (the perf report's "verdict" is throughput-bottleneck, not
  failure-reason). Almost certainly the known Tor-403 reality (premium news blocks Tor, already surfaced via
  transport-aware verdicts) but UNCONFIRMED — breaking it down needs the raw `oonetworkpreflight` JSON (aged
  out of context) OR a per-verdict fetch-failure tally added to the diagnostic (an enhancement, not built). IF
  it is actually `database is locked`, that is a real data-loss bug (cf. 2026-06-13), not Tor — so verify
  before dismissing. (b) **date-extraction recall 51.6%** (date diagnostics) — still open, = the 2026-06-27 F4
  (a bigger enhancement; the 2026-06-16 anchor/language wiring already helped). (c) **analytics freezes**
  (trending_windows / keyword_export / associations …) — the KEYWORD session's territory (strategy P2
  rollups); NOT touched here. (d) **airplane POST /api/system/network ≈ 5019ms** (perf) — the backend call
  itself is slow; PR #509 (prior session) made the airplane BUTTON give an instant popup + optimistic repaint
  so the UI never blocks on it, but the backend latency itself is un-diagnosed (likely socket-guard /
  interface enumeration on the state flip) — residual. (e) favicon #517 + polling-storm #518 are FRONTEND,
  BROWSER-UNVERIFIED per fork-3 — need a click-through.
- **STATISTICAL-DATA INGESTION + DIVERSIFIED HONEST VIZ + TS-FOUNDATION-MODELS (maintainer-directed
  research 2026-06-25; DESIGN-ONLY, not built — full record in `docs/FUTURE_DEVELOPMENTS.md` →
  "Statistical-data ingestion + diversified honest visualization"; verbatim session artifacts committed
  under `docs/research/`):** the maintainer ran internet sessions; outputs folded in. (1) **TimesFM &
  TS foundation models** — reliability assessed (TimesFM-2.5 top-tier-not-leading on GIFT-Eval; Toto-2.0/
  Chronos-2 ahead; FMs beat seasonal-naive only ~⅓; leakage is the field's big problem). RULED-BY-DESIGN
  reframe: **expectation/anomaly NEVER forecast, RETROSPECTIVE-ONLY (band never crosses the last
  observation)** = perception not judgment (respects the no-price-prediction + no-torch-in-core
  non-negotiables; any FM is an optional external Ollama-style process, never a core dep). Honest verdict:
  **classical-first (STL/seasonal-naive), FM probably-never for our mostly-short series.** ON-MISSION
  KERNEL (build independent of any FM): a **revision-anomaly detector** over `StatFigure` vintages
  (flag a new vintage that moves a past official figure into the tail of its own revision history —
  reliable-memory mission, no model). (2) **Official-statistics data** — a verified producer directory
  (~152 producers, 32 with confirmed machine endpoints) + 2 dataset catalogues (concrete queryable series).
  PARSER REALITY vs `src/stats/sdmx.py` (WB-JSON + SDMX-JSON 2.1 only): ~29 WB series ingestable today;
  new parsers needed for **CSV** (trivial, unlocks OWID energy/CO₂ = best-verified global data),
  **JSON-stat/PxWeb** (Eurostat+IRENA), bulk-ZIP (V-Dem/UCDP); OECD is SDMX-JSON 1.0 / IMF 3.0 (verify);
  EIA/FRED/Comtrade key-gated (defer). Enriches `src/stats/agencies.py`. (3) **Diversified honest viz =
  an `ooViz` family** — chart decision framework (perceptual ranking + honesty gate + REJECT list:
  radar/streamgraph/3D-pie/dual-axis/regression-cause/bubble-area/wordcloud) + working zero-dep MIT
  primitives (`honest-charts.js`: `pathWithGaps`=ooChart gaps, `sqrtAreaScale`=ooMap symbols; tests pass
  as committed) + 18 schematics. Choropleth normalized-only (levels→proportional symbols); conflict→ooMap
  points; V-Dem CIs→error bars. (4) **News/source diversity** (de-US-centring thread) — 105 verified rows
  (`docs/research/sources/`), enabled:false, managed-languages-only, all 9 source types, no mono-stance
  region; schema note: add a `global`/`transnational` region value; dedup `statssa.gov.za` across the two
  paths. BUILD PLAN A→E (A1 WB indicator catalog → A-CSV/OWID → ooChart honesty + stats charts → choropleth
  → diversified techniques → parsers + honesty-gate tests); revision-anomaly is the highest-value
  independent slice. 7 open maintainer rulings in the doc (retrospective-only stance; classical-first;
  sensitivity wording on flagging official figures; CSV+JSON-stat parsers; choropleth normalized-only;
  global region value; key-gated sources). Reference files VERIFY-BEFORE-TRUST (scaffold rows are leads,
  not facts; the project was burned by fabricated endpoints before).
- **FIELD TEST 2026-06-24 (maintainer running a real 59,646-article / 909,463-keyword / 6.0 GB corpus
  scraped over a day; several findings + rulings — RECORDED, build status noted):**
  (A) **BACKUP BROKEN AT SCALE (real bug, data-safety):** "Backup failed … Data or associated data too long.
  Max 2**31 - 1 bytes". ROOT CAUSE CONFIRMED — `src/safety/crypto.py:encrypt_bytes` does a SINGLE
  `AESGCM(key).encrypt(nonce, data, None)`; AES-GCM hard-caps at 2³¹−1 bytes (~2 GiB) per call AND the path
  reads the whole archive into RAM (`encrypt_bytes(zip_path.read_bytes())`). At a 6 GB corpus the oo-backup-2
  archive exceeds 2 GiB → the cipher refuses. The "Large data (folder/drive)" backup only covers the PUBLIC
  re-downloadable blobs (wiki/maps/models) — it leaves the encrypted CORPUS on this same 2 GiB-capped path.
  FIX: DECIDED 2026-06-24 (maintainer AskUserQuestion → **"Volumes + parity"**) — the large encrypted backup
  becomes a SET of <600 MB independently-authenticated encrypted VOLUMES + a signed manifest, with REED-SOLOMON
  erasure PARITY so a corrupt/lost volume (incl. a corpus volume) can be REBUILT (the user explicitly wanted
  corruption survival). HONEST LIMIT stated to the user: a database is monolithic, so WITHOUT parity a corrupt
  corpus volume can't be partially imported (other members still can) — parity is what actually recovers it.
  Building in reliable SLICES (each fully tested — the "entirely reliable or it doesn't ship" bar):
  **SLICE 1a SHIPPED 2026-06-24 (branch claude/backup-streaming, draft PR onto 0.09; VERIFIED py3.11, 21 tests):**
  the streaming-AEAD foundation + the volume codec. `src/safety/crypto.py` gained the OOENC2 chunked container
  (`encrypt_file`/`decrypt_file` + the per-volume `encrypt_stream_to` + `_encrypt_stream`/`is_streaming_magic`):
  the standard STREAM construction — 12-byte nonce = prefix(7)|counter(4)|final-flag(1) — so a TRUNCATED,
  REORDERED or EXTENDED stream fails GCM auth instead of yielding a partial archive (all proven in tests); no
  2 GiB cap, never the whole file in RAM; OOENC1 `encrypt_bytes`/`decrypt_bytes` UNTOUCHED (legacy/small path).
  `src/backup/volumes.py`: `write_volume_set` (stream-slice an archive into <600 MB OOENC2 volumes + a manifest
  with per-volume ciphertext SHA-256 + whole-archive plaintext SHA-256), `verify_volume_set` (names the exact
  corrupt/missing volumes WITHOUT decrypting), `read_volume_set` (verify → optional `recover` hook [the slice-2
  parity seam] → streamed decrypt+reassemble → whole-archive checksum check, raises LOUDLY naming bad volumes if
  unrecoverable). tests/test_crypto_streaming.py (9) + tests/test_backup_volumes.py (8).
  **SLICE 2 SHIPPED 2026-06-24 (branch claude/backup-parity, draft PR onto 0.09; VERIFIED py3.11+numpy, 7 tests):**
  the Reed-Solomon erasure PARITY that actually recovers corruption. `src/backup/parity.py`: a systematic MDS
  RS code over GF(2^8) (Cauchy generator, generator poly 0x11d) producing M parity volumes so ANY ≤M of the
  (N data + M parity) volumes can be lost/corrupt and rebuilt EXACTLY — including a corpus volume, so a
  monolithic SQLite corpus genuinely survives partial corruption once parity exists. `write_parity` (M =
  parity_count or ceil(0.1·N), each parity volume = the stripe length so still <600 MB; records them + their
  SHA-256 in the manifest `parity` block), `recover_volumes` (the read_volume_set `recover` hook: re-verifies
  data AND parity integrity, rebuilds the erased DATA volumes from the survivors, and CHECKS each rebuilt
  volume against its manifest SHA-256 — a wrong reconstruction is reported, never trusted; >M losses → loud
  failure). Operates on the opaque CIPHERTEXT (parity ⟂ encryption; a rebuilt volume is then GCM-verified by
  the normal decrypt). GF math over multi-GB volumes is numpy-vectorised (256×256 multiply table + XOR);
  numpy is the `[analysis]` extra so the module IMPORTS without it and degrades honestly — `parity_available()`
  False on a core install = volumes-only, recovery unavailable + reported loudly, never a silent partial
  restore. `volumes.read_volume_set` AUTO-recovers when the manifest has parity (lazy import — the codec keeps
  NO hard numpy dependency). tests/test_backup_parity.py (7: GF field consistency, MDS any-N-rows-invertible,
  EXHAUSTIVE erasure recovery over every ≤M subset, manifest+sizes, restore recovers 2 corrupt data volumes,
  restore recovers mixed data+parity loss, >M fails loudly).
  **SLICE 1b CORE SHIPPED 2026-06-24 (branch claude/backup-wiring, draft PR onto 0.09; VERIFIED py3.11, 3 round-trip
  tests):** the artifact-level create/restore wiring. `src/backup/artifact.py` refactored to a shared
  `_build_backup_zip` (collect members → sign manifest → zip; used by BOTH the single-file `write_backup_v2` and
  the new volume path — behaviour of the single-file path unchanged) + a shared `_finalize_staged` (manifest
  validate → Ed25519 signature verify → member-hash check → StagedArtifact; used by BOTH `read_artifact` and the
  new volume path). NEW `write_volume_backup(dest_dir, passphrase, *, parity_fraction=0.1, …)` = build the signed
  zip → `write_volume_set` (<600 MB OOENC2 volumes) → `write_parity` when numpy is present (volumes-only +
  honest flag otherwise); NO 2 GiB cap, never the whole archive in RAM. NEW `read_volume_backup(src_dir,
  passphrase, staging_root)` = `read_volume_set` (verify + auto parity-recover + whole-archive checksum,
  STREAMED to disk) → zip extract → `_finalize_staged`; raises loudly on unrecoverable corruption / bad
  signature. tests/test_volume_backup_roundtrip.py (3, no live data dir — hand-built signed zip: full
  restore round-trip + wrong-passphrase loud + parity recovers a corrupt volume and the restore STILL verifies).
  **SLICE 1c SHIPPED 2026-06-24 (branch claude/backup-1c, draft PR onto 0.09; backend VERIFIED py3.11 [6 job
  tests + 37 backup tests], frontend BROWSER-UNVERIFIED per fork-3):** the in-app reachable surface, so the
  6 GB backup WORKS from Settings. `src/backup/volume_job.py:VolumeBackupManager` (singleton, mirrors
  FolderBackupManager) runs `write_volume_backup`/`read_volume_backup` off the request thread as ONE cancellable
  job (backup + restore modes; running/done/error/cancelled; progress {phase, volumes_written}; a cancelled
  build cleans its partial volume set so it can never be mistaken for a good backup; restore mid-merge is atomic,
  not interruptible). `write_volume_set`/`write_volume_backup` gained additive `should_stop`/`progress_cb` (the
  job hooks; defaults preserve the verified behaviour). Endpoints (`src/api/backup_v2.py`): POST `/volumes/start`
  (400 bad dest/no passphrase, 409 already-running), `/volumes/restore` (verify+parity-recover+reassemble →
  additive merge), `/volumes/cancel`, GET `/volumes/status`. Surfaced in `/api/jobs` (`_volume_backup_jobs`,
  kind="volume-backup", visibility-only — control in the Settings panel). Frontend: a Settings → Data & backup
  "Large encrypted backup (volumes + parity)" panel (server-side dest + passphrase + Browse + cancellable
  progress poll + a restore-from-folder section); new strings English-fallback via `t()` (i18n gate 100%).
  tests/test_volume_job.py (6: backup→done + envelope stripped, cancel cleans the partial set, error surfaced,
  one-at-a-time, empty-passphrase refused, restore→done — via an injected fn seam so the state machine tests
  without a live corpus) + test_repo_invariants::test_volume_backup_job_wired_slice_1c. NOTE: the 2 GiB
  `_MAX_RESTORE_BYTES` cap is N/A on this path — the volume restore reads a SERVER-SIDE DIR, never a 2 GiB-capped
  upload. THE 2 GB BACKUP FIX IS NOW COMPLETE END-TO-END (engine 1a/2/1b + the in-app surface 1c). REMAINING
  (polish): human click-through across themes (fork-3); key the panel strings ×12; a per-job cancel button in the
  task-manager window (today control is the Settings panel). IMMEDIATE WORKAROUND still valid until 1c merges:
  engage airplane mode (or shut down) → file-copy `data/open_omniscience.db` (+ `-wal`/`-shm`) to a drive —
  already SQLCipher-encrypted at rest.
  **SLICE 1c 404 FIX 2026-06-24 (field test: "Back up (volumes + parity)" → "not found"; branch
  claude/backup-1c-fix, draft PR onto 0.09; backend VERIFIED py3.11):** the 1c endpoints were decorated
  `@router.get/post("/volumes/...")` but the router prefix is `/api/backup`, so the routes registered as
  `/api/backup/volumes/...` while the deployed frontend (volBackupStart/volRestoreStart/volBackupCancel/
  _volRefresh) POSTs/GETs `/api/backup/v2/volumes/...` (the `/v2/` family the encrypted-backup endpoints use)
  → every volume call 404'd. FIX = add `/v2/` to the 4 volume decorators (chosen over editing the frontend,
  for consistency with the `/v2/restore` family + the already-shipped JS), so they compose to
  `/api/backup/v2/volumes/{start,restore,cancel,status}` = the frontend calls. The slice-1c invariant test
  only checked both path strings existed INDEPENDENTLY (so it passed despite the mismatch) — HARDENED to
  assert full-path AGREEMENT (backend = prefix + decorator, via regex; `frontend_routes - backend_routes`
  must be empty), which would have caught the 404. Endpoint bodies unchanged. LESSON: a wiring test must
  compose the actual route (prefix + decorator) and match it against the caller, never assert the two strings
  side by side.
  (B) **UNIFIED IMPORT / EXPORT (/ BACKUP) SECTION (maintainer ruling):** collapse ALL import types and ALL
  export/backup types into ONE Import entry point + ONE Export(/Backup) entry point; each opens a FOLLOW-UP
  dialog (pop-up) to gather that action's options. Today these are scattered (newsletter .eml upload +
  folder-import job + mailbox pull · oo-backup-2 encrypted/plaintext · selective tickboxes · folder/large-data
  backup · models .oomodels · restore-merge · selective restore). Consolidate to one Import + one Export, each
  with an options dialog. **SHIPPED (#519-#529 + slice 3, verified 2026-07-02):** the #ux-export/#ux-import
  dialogs ('Export / Back up…' + 'Import…') drive the volumes+parity + folder engines; the standalone panels
  + the 2 GiB single-file CREATE were retired; guard-tested (tests/test_unified_backup_ui.py) + i18n-keyed ×12.
  (C) **FOLDER NEWSLETTER IMPORT FAILS (real bug):** importing a ~5 GB multi-folder `.eml` tree dies with
  `UNIQUE constraint failed: articles.hash`; per-batch works but is quantity-limited. The §2.B batched-commit
  path (`ingest_emails` commit_batch + `_commit_one` fallback) has a dedup HOLE at the folder-import-job scale
  — a duplicate hash reaches an INSERT instead of being caught (likely two .eml with the same content-hash in
  the SAME uncommitted batch ACROSS subfolders, or the IntegrityError fallback not wired on the folder-job
  path). FIX: catch the collision + dedup within the batch (the `batch_keys` set must span the whole folder
  walk, and the `_commit_one` IntegrityError redo must be on the folder-job path). **FIXED (verified
  2026-07-02):** src/ingest/email.py dedups the batch on the ACTUAL unique column (`pending_hashes`) +
  `_flush` falls back per-message on IntegrityError; regression-tested (test_email_ingest.py::
  test_same_body_different_message_id_dedups_on_hash).
  (D) **OLLAMA "installer missing" — ANSWERED, NOT LOST:** the Settings subtab was RENAMED "Models" → "AI"
  (`index.html:920`, Settings → AI) — that's why it feels missing; the catalog (size/RAM hints) + pull queue +
  remove + active-model picker SHIPPED there. The BINARY installer (download+verify+RUN the official per-OS
  Ollama installer) was NEVER built — blocked from day one on per-OS installer CHECKSUMS (can't fabricate).
  **RESOLVED + SHIPPED 2026-06-30 (branch claude/ai-ollama-installer-zun7pb; see the shipped.csv row):**
  the checksum blocker is gone — GitHub's releases API attests a `digest: sha256:…` per asset, so
  `src/llm/installer.py` fetches the official `install.sh` + its attested digest through the guarded
  factory, verifies the bytes against it (refusing on mismatch/missing attestation), stages it, and runs
  it when elevation is non-interactive (root / passwordless `sudo -n`) else shows the verified `sudo sh
  <path>` command. Endpoints `/api/llm/install/{status,prepare,run}`; a Settings → AI panel
  (`#llm-install-box`) shown only when Ollama is absent. Linux only (Debian target); macOS/Windows get an
  honest ollama.com/download pointer. Frontend BROWSER-UNVERIFIED per fork-3. So this is no longer the
  genuinely-unbuilt piece. (E) **909k KEYWORDS = mostly
  the pre-cleanup count** — the §2.5/§2.6 + stopwords-iso reduction is forward-only at index time, so it hasn't
  bitten; "Clean up keywords (re-index, then prune)" drains it (heavy at 6 GB). The keyword-growth curve
  (below, SHIPPED) measures how much is junk.
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
  deferred); outrage-intensity is SECONDARY (annotates another card, never a standalone Lead).
  COPYPASTA SHIPPED 2026-06-25 (the astroturf/copypasta card — see the shipped-log entry): a SPAN-level
  signal genuinely DISTINCT from echo_chamber (whole-article near-dup) — a verbatim phrase shared across
  many DISTINCT sources in articles that are NOT whole near-dups (wire republish is EXCLUDED as
  echo_chamber's job). So 6 of the 9 cards now ship as producers (source-laundering #6, recycled-claim #1,
  headline-body #7, emergence #3, flood #4, copypasta); the rest (the BURY half of #4, event-timed-op,
  outrage-intensity) are foundation/trigger-gated.
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
- **IN-APP OLLAMA/MODEL MANAGEMENT + APP SELF-UPDATE (ruled 2026-06-13/16/17; the build narration
  is compressed per rule 5a — one `docs/ledger/shipped.csv` row per slice):**
  **THE BINDING RULINGS (2026-06-16, Q6–Q10):** placement = a dedicated Settings SUBTAB (invariant
  #18 grammar) · **Q7=B** the app DOWNLOADS + RUNS the official per-OS Ollama installer, verifying
  checksum/signature BEFORE exec through the guarded factory, with consent + a VISIBLE explicit OS
  elevation step, NEVER silent · **Q8=A + elaboration** the curated dated catalog PLUS a SEARCHABLE
  consented live-ollama.com-library browse, filterable by provider · date · size (+ hardware-fit +
  license), showing only app-APPLICABLE models · **Q9=YES** transport honesty — pulls egress
  CLEARNET via the OLLAMA PROCESS, NOT our Tor proxy/guarded factory, so airplane+Tor do not cover
  them; this is disclosed at consent (the USB offline kit stays the air-gapped path) · **Q10=YES**
  the active model is a stored UI setting, not env-only.
  **APP-COMPATIBILITY CLARIFICATION (standing):** our features use PLAIN `/api/generate` text
  generation — NO tool/function-calling — so any instruct/chat TEXT model that fits the hardware
  works; "compatible" means text-generation that fits RAM, never a special protocol. Filter OUT
  non-applicable kinds (embedding-only, vision-only).
  **AI-ANALYTICS STORAGE — SUPERSEDING RULING (2026-06-18; do NOT revert):** AI-derived analytics
  live in their OWN tables in the MAIN corpus DB (`ai_keyword`, real FK to articles), NOT in a
  separate parallel database. This REVERSED the 2026-06-17 strict-physical-separation ruling
  (which had itself overridden an earlier provenance-partition recommendation — do not revert to
  either). What tipped it: UI integration is decoupled from storage, and two files cost real
  perf/ergonomics for corpus-wide AI-signal filtering, which has no cross-file SQL JOIN. The
  separation GUARANTEE is preserved by construction, not by physical separation: an own table
  (NEVER the trusted `keywords`/`keyword_mentions`), NO score column, model provenance,
  confirm-within-the-lens, and an INVARIANT TEST that the trusted rule-based index never reads
  `ai_keyword`. The superseded design's HONESTY rules all still hold.
  **LLM EXPANSION — DESIGN RULINGS 2026-06-17 (recorded, NOT built):** scoped to a stronger rig
  (~40 GB RAM / 8 GB VRAM, a 30B-class long-context model). Honest frame: such a model is CPU-bound
  on that hardware, so deep LLM work = BACKGROUND task-manager jobs with no fabricated ETA; a more
  fluent model makes mistakes more convincing, so cited + verify-against-source matter MORE, not
  less. (1) TWO COMPUTE TIERS — a fast small model for interactive bits + a heavyweight
  long-context model for deep jobs, with a per-job-class model setting. (2) FOUR LONG-CONTEXT
  UNLOCKS sharing plumbing: whole-corpus CITED synthesis (50–150 FULL articles, single-source
  flagged) · corpus Q&A WITHOUT RAG (quoted+cited, refuses when absent) · long SINGLE documents
  whole · CROSS-LANGUAGE synthesis. (3) Extend the LLM lens to Commodities/Markets (descriptive
  cited "what the coverage says moved" — co-occurrence NEVER causation, no price prediction),
  Agenda (future-date extraction as confirmable candidates), World Law (plain-language explainer ·
  version-DIFF narration · cross-jurisdiction comparison), WorldMap (place disambiguation as
  candidates), and Source integrity (cross-language/PARAPHRASE coordination — the strongest
  LLM-additive where lexical MinHash fails; STRUCTURE never intent/credibility).
  **SELF-UPDATE via GUI (designed, NOT built):** consented check vs GitHub releases → signed
  oo-backup-2 + install-tree snapshot BEFORE anything → verified release → migrations on a STAGED
  copy → atomic swap + relaunch → rollback on failure. The data dir lives outside the code tree so
  the corpus/settings/keys survive by construction; never silently decrypt across an update.
  FIVE OPEN QUESTIONS still unanswered: channel · trust root · cadence · curl|bash-vs-git ·
  mirror-anchoring. (The 2026-06-17 ruling #4 set the posture: MANUAL, user-driven, git-pull based,
  NO signing key yet.)
  **SHIPPED since (each with its own shipped.csv row):** pull/remove endpoints streaming Ollama's
  real byte progress · the Settings → Models subtab (pull · remove · active-model picker ·
  free-text pull-any-tag) · the dated `MODEL_CATALOG` (real verified tags only — the file's own
  "previous catalog was hallucinated" caution stands) · `AppSettings.llm_model` + `active_model()`
  · bulk summarize/translate + reader Summary/Translation tabs + editable prompts (v2, with the
  `{language}` pin and per-result `prompt_text` provenance) · model keep-alive · the LLM pill
  sync fix · the `ai_keyword` layer + its first extractor · the model-download QUEUE
  (`src/llm/pull_queue.py`) · and **the Q7=B binary installer itself** (`src/llm/installer.py`,
  2026-06-30 — the per-OS-checksum blocker was resolved by GitHub's attested `digest: sha256:…`
  release-asset field; see the Lessons entry). ALL LLM features keep the standing honesty
  invariants: grounded+cited, refuse-when-absent, no score/verdict/ranking, local loopback,
  provenance recorded, caveats visible, never auto-fed into the trusted pipeline.
  **REMAINING:** the Q8 live ollama.com library BROWSE (only the curated catalog + a free-text tag
  box exist; the catalog docstring still points users at the website) · the read-only AI-keyword
  LENS UI beside the trusted keywords (backend ready, no frontend) · the deep-model TIER (1) and
  whole-corpus cited synthesis (2) · a per-article Summarize/Translate on the analysis Articles
  list · bulk as a first-class task-manager job (today a streaming request) · the self-update
  mechanics + its five rulings · browser click-throughs (fork-3).
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
- **KEYWORD POLICY (field report #4, 2026-06-12; the standing rulings — the June/July build
  narration is compressed per rule 5a, one `docs/ledger/shipped.csv` row per slice):**
  • **NO CAP (standing maintainer position):** NOT a fan of capping; data crunching uses as many
    keywords as possible. If a cap ever became necessary it must be DYNAMIC (the ChatGPT-2020
    example: a novel rising term must always be capturable). Measured basis: junk ≈ 6% of mentions,
    so capping would buy little. The ruled instrument is instead the EXCEPTION POLICY — evidence-
    based per-language stoplists, applied at QUERY time (`global_stopwords`), so a batch takes
    effect retroactively with no migration and no re-index.
  • **ENTITY DETECTION — TITLE-CASE DROPPED, ACRONYMS KEPT (ruled 2026-06-16; do NOT re-litigate):**
    Title-Case is not an entity signal (German capitalises every noun; Romance sentence-initial caps
    leak; Arabic/CJK have no case — the log showed 60–75% of per-language "entities" were common
    words). Entities are ONLY stand-alone ALL-CAPS acronyms, context-aware (an all-caps token
    adjacent to another is a headline run, skipped), with the normalized form kept **UPPERCASE** so
    `WHO`≠`who` and `US`≠`us` survive the stopword filter. Real person/org/place kinds come from the
    gazetteer/spaCy, not capitalisation. Multi-word Title-Case names survive as topical TERM
    n-grams (never lost). DELIBERATE ACCEPTANCE: residual emphasis-acronym noise is iterated away
    via the diagnostics logs, not by re-adding a case heuristic. CONSEQUENCE ACCEPTED: self-name
    suppression is narrower for outlets whose tokens are all stopwords (literally "The Moscow
    Times") — recorded, not re-litigated.
  • **Item AC baseline/tagging answers (maintainer, 2026-06-17):** Q1 curated-small + analyzer-grown ·
    Q2 BOTH axes (type + topic) · Q3 stoplists→data files · Q4 explore + hide/tag together ·
    Q5 forward-only (hence the retroactive backfill action) · Q6 deferred.
  • **HONEST LIMITATION (standing):** stoplists are by BASE form, so an INFLECTED weekday
    ("среду"/"szombaton") still leaks in inflecting languages — the self-test's ru/hu cases assert
    only the function words actually present, and the gap is stated rather than papered over.
  **SHIPPED (each with its own shipped.csv row):** the ×16-language stoplists + weekday/inflection
  passes · source SELF-NAME suppression at index time · per-source concentration suspects +
  `language_mismatch` flags in the diagnostics export · `scripts/analyze_keyword_log.py` (propose-
  never-edit) with its `--tag-gaps` and `--baseline` diff modes · the Item AC tag schema + loader +
  API + 7-language baseline + retroactive backfill + the Settings→Keywords explorer subtab ·
  singular/plural family merge (guarded, reversible, `_PLURAL_DENYLIST`) · the keyword-engine report
  · the declarative keyword self-test (`/api/diagnostics/keyword-selftest`, 22 cases × 11 languages)
  · and the 4-step pre-translation program (engine report → super-RINGS → the Wikidata ring
  generator → ring/super-ring editing in the UI). The generator has since been RUN on a networked
  machine (`configs/keyword_rings_generated.yml`), and Q3's stoplists→data-files migration landed
  2026-07-23 (`configs/stopwords_extra/<lang>.yml`) — both formerly-open items are now closed.
  **REMAINING:** the per-keyword TAG add/remove UI (the S3a write endpoints exist; the explorer
  currently does explore + hide + backfill only) · S4, in-app review of analyzer proposals ·
  a browser click-through of the keyword/super-group surfaces (fork-3).
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
- **PLANNING SESSION 2026-07-12 — the OPTIMIZATION PROGRAM designs-of-record + the STORAGE
  5 TB PLAN (maintainer↔Fable-5 planning-only dialogue, held while S1–S6 ran; DESIGN-ONLY, no
  code from it yet):** full detail in **`docs/design/STORAGE_5TB_PLAN.md`** (the reconciled
  successor of the never-committed A→B→C storage sketch — corrected by the internet research
  saved verbatim at `docs/research/storage/STORAGE_5TB_RESEARCH_2026-07-12.md` and re-grounded
  on S2.6's `5TB_ARCHITECTURE_REVIEW.md` + S3.4's `DB10_RETENTION_VACUUM_MEMO.md`) and
  **`docs/design/PLANNING_2026-07-12_OPTIMIZATION_PROGRAM.md`** (Conjunction Lens · Leads 2.0 ·
  keyword fingerprints · search-instrumentation-first · Tor ladder · three-tier UI verification
  + the AppVM recursive environment · power profiles · LLM keyword triage + the 7-model bench).
  RULINGS RECORDED (maintainer, 2026-07-12): (a) WORKFLOW — all coding via Claude Code CLI
  (Opus 4.8, max effort); the web Fable-5 instance does planning/design only; (b) the AppVM
  RECURSIVE ENVIRONMENT is approved ("we should go for it") under four BINDING safety lines —
  synthetic ENCRYPTED corpus only, the REAL corpus NEVER enters an agent session (diagnostics
  exports stay the safe channel), app stopped across branch switches, airplane default;
  (c) POWER PROFILES — Low/Optimized/Max, USER-activated, transparent published knob table,
  suggest-never-silently-switch; (d) LLM KEYWORD TRIAGE — 3 M keywords cannot be hand-curated;
  a temporary in-app button batches keywords to a local Ollama model, JSONL EXPORT-ONLY (never
  the trusted index), Claude verifies samples → deterministic artifacts as reviewed PRs
  (provenance ai-proposed·claude-verified·maintainer-merged); logs carry TIMESTAMPS/Ollama
  timing so the strategy's cost is COMPUTED; a SEPARATED bench first — 7 models
  (gemma4:e4b·mistral:7b·granite4.1·qwen3.5:4b·translategemma:4b·nemotron-3-nano:4b·
  ministral-3:3b) over a frozen stratified ~400–500-keyword batch with ~50 maintainer-graded
  anchors; TAGS VERIFIED against `ollama list` before any run (never substitute a close tag);
  (e) keyword analytics keeps BOTH the corpus-algebra sets AND the lens, over N keywords (not
  just two); (f) the CARD SYSTEM gets evidence-weight elaboration + its OWN Settings subtab
  with good defaults. STORAGE HEADLINES (accepted from the research, hand-verified): the
  corpus/index ATTACH split is DEAD (WAL forfeits cross-file atomicity — ONE durable file;
  only disposable/immutable pieces split out); the split-out FTS index must be
  CONTENTLESS-DELETE (verified snippet-safe; sqlcipher3 SQLite≥3.43 still to verify); Phase C
  text-offload is MANDATORY (~17.5 TB ceiling) and becomes a PACKED + HMAC-KEYED-addressed
  (confirmation-attack fix) + OOENC2-encrypted + per-source-zstd store (versioned encrypted
  dictionary registry; blob-first writes + mark-and-sweep GC; dedup ON pending ruling); FTS
  HASH-SHARDING is CORE (time-neutral ⇒ honors cross-time recall), PROTOTYPED at 50–100 M
  synthetic docs before commitment; a documented KDF hierarchy derives every crypto domain
  from the ONE passphrase. EMPIRICAL OVERRIDES kept against the report: DuckDB encryption
  stays refuted-for-writes (P2.4 — the httpfs gate stays; re-probe per version bump); OOENC2
  over age for packs (age = recorded fallback). PENDING MAINTAINER RULINGS (table in the plan
  §8): auto_vacuum=INCREMENTAL for new corpora (DB-10 §1a rec: YES) · page_size
  (measure-gated) · dedup ON · OOENC2-vs-age · keyed addressing · the sqlite3mc benchmark
  trial. Fork-3 amendment queued for the first VM session: verified surfaces graduate to
  "Gecko-verified (VM) · awaiting human UX pass". Everything gated on S1–S6 completing + the
  staleness guard.
- **OPTIMIZATION-PROGRAM EXECUTION — CYCLE 1 (2026-07-13, the two maintainer-flagged topics first;
  stacked draft PRs onto 0.2, staleness-verified against origin/0.2 @13223498):** the first execution
  cycle of the 2026-07-12 optimization program (the Fable-5 planning designs-of-record above), run
  under full autonomy / draft-PR-only (nothing auto-merges — the PR review is the gate). Delivered:
  (i) **PR #643 the per-phase ACTION PLAN** (`docs/design/OPTIMIZATION_PROGRAM_ACTION_PLAN_2026-07-13.md`
  — every phase §1–§8 tagged BUILDABLE-NOW / OPERATOR-GATED / BROWSER-GATED / DESIGN-ONLY /
  VERIFIED-PRESENT + a shared-foundations REUSE MAP [minhash_signature(set[int]) for §2/§3 · the
  head-by-article-spread SELECT for §6/§8 · `_forensic_timer`/`_append_jsonl` for §4/§8 ·
  `_all_diagnostics_members` for §6] + a revised §9 sequencing; a read-only scout+critic agent fan-out
  found ZERO staleness errors). (ii) **PR #644 §8 LLM keyword triage** — the measure-first core
  (`src/ai_layer/triage.py`): EXPORT-ONLY JSONL that NEVER writes the trusted index, an EXACT-first
  echo-back parser (a mangled/hallucinated term rejected never guessed), canaries, the Ollama
  timing-passthrough JSONL schema + VALID-verdicts/sec ETA, head-scope selection
  (`Keyword.article_count` DESC, counter-only), the bench (`verify_roster` REFUSES an uninstalled tag,
  metrics each ALONE no composite), `run_triage_selftest` → `/api/diagnostics/keyword-triage-selftest`;
  42 tests; an adversarial skeptic fan-out found+fixed a normalized-collision echo-back misattribution
  (a real keyword proposed for deletion), an export append-anywhere hazard, and metric/self-test gaps,
  each regression-pinned. (iii) **PR #645 §6 recursive improvement** — the recursive-loop diagnostics
  SELF-INVENTORY (`src/monitoring/recursive_loop.py` + `/api/diagnostics/recursive-loop`: imports+runs
  the loop's mechanism-proof gates, reports importable/passed/error) + article-length/keyword-growth
  wired into the all-diagnostics bundle + a membership CONTRACT test; the AppVM RUNBOOK
  (`docs/design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md`: the four binding safety lines + the
  "Gecko-verified (VM)" convention amendment). (iv) this closeout (the 3 shipped.csv rows + this note).
  **OPERATOR-GATED remainder (honest board):** the real §8 triage batch + the 7-model bench + the
  ~50-keyword anchor grading (needs the Ollama rig — this box had Ollama installed but server-down /
  0 models / no GPU, exactly §8.3's prediction); §6 `ui_walk` + the AppVM runner (headless browser +
  the VM). **NEXT per the plan's §9:** §4 search-timing instrument + §7 power-profile knob table
  (both BUILDABLE-NOW), then the §1 Conjunction-Lens set-algebra core + §2 Leads 2.0
  ordering/floor/clustering cores; §3 fingerprints AFTER §8's triage cleans the junk; §5 Tor ladder +
  segmented-download cores. Each its own session-sized brief.
- **OPTIMIZATION-PROGRAM EXECUTION — CYCLE 2 (2026-07-13, the remaining BUILDABLE-NOW §9 cores;
  6 stacked draft PRs onto 0.2, staleness-verified against origin/0.2 @2f645c03; maintainer said
  "proceed with the rest"):** the second execution cycle of the 2026-07-12 optimization program,
  finishing every buildable-now core the plan (`OPTIMIZATION_PROGRAM_ACTION_PLAN_2026-07-13.md` §9)
  had queued after cycle 1's §6/§8. Full autonomy / draft-PR-only (nothing auto-merges — the review
  is the gate); skeptics-before-push with the mandatory negative-space lens on the parser/data-safety
  surfaces. Delivered (each a measure-first pure/testable core, honesty-clean [no composite score,
  walk-verified], ruff + mypy clean on new files, operator/browser-gated remainder documented):
  (i) **PR #648 §4 search-instrumentation** — the per-search phase-timing aggregate (`search_timing.py`:
  SearchPhaseTimer injected-clock timer + a pure `aggregate_phases` naming the dominant phase by
  measured p95 + bounded JSONL + `instrument_search` seam; `GET /api/diagnostics/search-timing{,-selftest}`
  + the all-diagnostics bundle). (ii) **PR #649 §7 power-profiles** — `src/config/power_profiles.py`:
  the PUBLISHED_KNOBS table over 8 real knobs + `resolve_effective`; Optimized == the current default
  (test-pinned), Low/Max flagged PROVISIONAL (GAMMA-gated); the one concrete wiring
  `fts_analysis_limit()` (OO_FTS_ANALYSIS_LIMIT) replacing the `PRAGMA analysis_limit=1000` literal.
  (iii) **PR #650 §1 Conjunction Lens** — `conjunction.py`: `corpus_algebra` (N-keyword intersection/
  union/difference) + per_article_intensity + conditional_trend + pure vocabulary_contrast + pure NEAR
  emission; `GET /api/insights/corpus-algebra`. (iv) **PR #651 §2 Leads 2.0** — `briefing/leads.py`:
  the disclosed `order_key`/explain_order (a tuple of facts, never a score) + is_major floor + exact-Jaccard
  story clustering + the new/strengthened/weakened/mixed/gone lifecycle diff. (v) **PR #652 §3 keyword
  fingerprints** — `analytics/skeleton.py`: skeleton_fingerprint + MinHash skeleton_clusters + the LCS-ratio
  ordered comparator + the skeleton_echo producer assembly (>=3 sources, refuses a text near-dup). (vi)
  **PR #653 §5 Tor throughput** — `ingest/tor_throughput.py`: the KindLadder + segmented plan/reassemble +
  mirror ranker. **ADVERSARIAL SKEPTIC EARNED ITS KEEP TWICE** (negative-space + data-integrity lenses,
  hand-re-verified before fixing): on §1 it found a HIGH — intersection/difference computed over
  INDEPENDENTLY-capped per-term sets could drop a true member or include a false one (a wrong article_ids
  set silently seeding the analysis window) — fixed to ONE consistent per-article scan so a bounded result
  is always a true SUBSET (never a fabricated member), + a LOW (per-term n now exact/uncapped); on §5 it
  found 3 — a CRITICAL opt-in `reassemble` integrity check (a content-swap/truncation passed silently
  without a checksum → integrity now MANDATORY, content-swap/missing-checksum refused), a HIGH ladder
  STARVATION (the token-bucket + floor-debt zeroed an equal-weight peer, a=0 b=2000 → replaced with a
  provably starvation-free STRIDE scheduler), and a MED (the floor delivered no volume → weight=max(rate,
  floor)). Each defect regression-pinned. **OPERATOR-GATED remainder (honest board):** §4 the real per-phase
  ms on the live corpus (wire `instrument_search` into the search endpoint); §7 the measured Low/Max numbers
  (GAMMA harness) + live cache_size re-application; §1 the N-keyword picker UI (browser) + 974k-keyword/5 TB
  perf; §2 the Settings→Leads subtab/evidence-chip UI (browser) + major-floor tuning; §3 fingerprint
  persistence (schema+migration+backfill) + the live producer wiring (lands AFTER §8's triage cleanup); §5
  the real multi-circuit Tor GET + mirror probing. Plus the standing cycle-1 operator gates (the §8 triage
  batch + 7-model bench on the Ollama rig; §6 ui_walk + AppVM runner). **THE PROGRAM'S BUILDABLE-NOW CORES
  ARE NOW ALL SHIPPED** (§1–§8) — what remains is operator/browser-gated + the §8/§6 hardware runs.
  `~/.oo_push_token` remains live on disk (used for these pushes); revoke + rm it when this cycle's review
  is done.
- **ACTION PLAN 2026-07-13 — self-curating sources · maps/OSM · planned-but-partial remediation +
  a doc-cleanup pass (Fable-5 planning session, docs-only):** full plan of record =
  **`docs/design/ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md`** (companion to the optimization-program
  + storage plans; do NOT duplicate them). CONSOLIDATES the 2026-07-13 planning dialogue: (1) the
  self-curating-sources SPINE — Phase 0 quality DIAGNOSTIC ✅ SHIPPED (#655–#657, `source_quality.py`
  + `/api/diagnostics/source-quality`, the 3-selector zip incl. the newsletter text-gate; awaits the
  operator run + analyst loop), Phase 1 standing AUDITOR (audit EXTRACTION-VALIDITY not editorial
  merit; corpus-relative per-language; precision-biased auto-demote only on extraction-failure;
  diversity-aware; transparent criteria; idle-maintenance), Phase 2 auto-DISCOVERY funnel (Wikipedia
  references across all 12 editions as the flagship channel + complete cited_sources + DDG; trial →
  Phase-1 quality gate → graduate; diversity-weighted; audit view + undo). (2) OSM/maps — the
  DATA-SOURCE path (finer boundaries + sub-national admin-1 + gazetteer, fits no-WebGL) vs live-detail
  (ceilinged by the ruling); the missing offline preprocessing BRIDGE; border-honesty; map
  change-tracking later. (3) the planned-but-partial REMEDIATION from the 2026-07-13 four-verifier gap
  sweep (Tier 3A surface-the-built-backend trio: AI keyword lens · subjectivity engine · El Niño — all
  backend-shipped, zero UI; 3B `external_sources` wire-or-delete; 3C the gold-set grading linchpin
  unblocking lemma+BM25F+embeddings; 3D dead-code+inline-handler AppVM cleanup; 3E re-decide the 3D
  keyword explorer). OPEN RULINGS surfaced (Part-2 no-WebGL firm? / Phase-1 auto-demote trigger /
  Phase-2 automaticity / external_sources / 3D explorer). DOC-CLEANUP (maintainer ruling 4a,
  non-lossy `git mv`, links retargeted, ~0 refs in the sacred docs): archived the completed S1–S6 +
  2026-07-10 A/B briefs + conventions → `docs/archive/session-briefs/`, the pre-0.2 audit working set
  (00–05 + logs + action-plans + findings.csv + raw/ + diagrams/) → `docs/archive/audits/`,
  `source_enrichment/` → `docs/archive/`, and the two `SOLO_SESSION_*` docs → `docs/archive/`;
  `docs/audit/` now holds only the 3 records of record; `docs/design/` 26→18 top-level. Archive READMEs
  updated with the old→new maps.
- **OMNIBUS SESSION RULINGS (maintainer, 2026-07-13) — executing
  `docs/design/ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md`, full autonomy, DRAFT-PR-only (nothing
  auto-merges — the review is the gate):** the six open rulings that plan surfaced are ANSWERED:
  (1) **MAPS [Q1a]** — the data-source path is ruled (OSM preprocessed OFFLINE into boundary/gazetteer
  artifacts feeding ALL thematic maps; no-WebGL stands; live street-level detail out of scope). The
  BUILD is DEFERRED to its own dedicated session — recorded + a ROADMAP row; NOT built this session.
  (2) **PHASE-1 AUDITOR [Q2a]** — FLAG-ONLY this session; build the auto-demote machinery but ship it
  DEFAULT-OFF behind an explicit setting, activation gated on the operator's Phase-0 zip calibration;
  auto-demote (when later enabled) triggers ONLY on extraction-failure signatures + sustained low
  yield, NEVER structural style. (3) **PHASE-2 DISCOVERY [Q3a]** — build the FULL funnel (candidate →
  trial → graduated) with trial auto-enable behind a DEFAULT-OFF setting; enabling it is a maintainer
  action passing the ONE network-consent popup; candidates register DISABLED as today. (4)
  **EXTERNAL_SOURCES [Q4a]** — WIRE IT (it becomes the discovery funnel's resolution table:
  cited/discovered domains resolve to external-source rows with provenance; its dormancy ends);
  additive-migration discipline; backup-merge already carries it. (5) **3D EXPLORER [Q5a]** — formally
  DEPRIORITIZED (supersedes the 2026-06-16 "do NOT defer the 3D" ruling; re-decided 2026-07-13); the
  3-level mind-map stays as-is; do NOT build. (6) **ENVIRONMENT [Q6a]** — no browser here; all frontend
  ships CONSERVATIVE + FLAGGED ("browser-unverified, needs click-through": node --check + invariant
  guards + defensive empty states); browser-gated items (dead-code deletion #3D, inline-handler
  retirement) go to the operator/AppVM list, not this queue. STALE-LEDGER RECONCILIATION (Part-3H):
  the following were verified SINCE-SHIPPED and are no longer "remaining" — deduced-events-in-agenda
  (`mapDeducedToAgenda`), sentiment-at-ingest (`sentiment.score_article`), LLM langdetect
  (`src/ai_layer/langdetect_llm.py`); full-text dump search / weather signal-keywords /
  ring-translation fallback / super-groups+ring-country UI carry their own prior shipped-log entries.
  EXECUTION NOTE: this session prioritized the fully-VERIFIABLE backend spine (Part-1 Phase-1 auditor,
  which the board's own sequencing calls the linchpin — "Phase 1 IS the quality gate that makes Phase 2
  safe") + the mandated ledger/rulings, over the browser-UNVERIFIED frontend surfacing (Part-3A / Leads
  UI / small tails), which Q6a caps at conservative-flagged; the frontend + discovery-funnel remainder
  is parked as an honest carry-over in the session closeout.
  **OMNIBUS CLOSEOUT (2026-07-13):** SHIPPED (draft PRs onto 0.2, nothing auto-merged) — **Item 0** ledger+rulings
  (merged #662); **Item 2** the standing source AUDITOR (#663, the linchpin; flag-only Q2a; a skeptic HIGH — the
  nearest-rank-p90 tail trap — found+fixed with an absolute EF-only floor + regression-pinned; 18 tests, clean);
  **Item 1 / Part-3A** (#664) — (a) AI-keyword lens VERIFIED already surfaced (staleness win, not rebuilt), (b) a
  subjectivity "Loaded language" reader tab (conservative, browser-unverified per Q6a), (c) El Niño banners PARKED.
  CARRY-OVER (parked HONESTLY, precise specs in the #664 body + the board's "Omnibus execution status" §):
  **(i) Item 1(c) El Niño agenda banners** — the climate dataset is `verification_status=flagged` (pending the NOAA
  CPC ONI clearnet check) + episodes are historical multi-month SPANS that don't fit the forward agenda + span-banners
  aren't supported → build after the ONI check + span support (surfacing unverified data prominently would breach
  "nothing presented as verified before it is"). **(ii) Item 3 / Part-3B + Phase 2 discovery funnel** — a
  dedicated-session backend build (additive funnel-state migration + the zero-network Wikipedia-references channel +
  external_sources wiring Q4a + audit view + undo); NOT started (half-building a data-migration is worse than a park);
  the zero-network wiki-refs channel is the recommended first, most-verifiable slice, building on the now-merged
  Phase-1 auditor (the graduation gate). **(iii) Items 4/5** (Leads 2.0 + Conjunction-Lens UI · small tails) — the
  §1/§2 cores shipped; the UIs are browser-UNVERIFIED frontend (Q6a) awaiting a click-through. **(iv) Item 6**
  fingerprint persistence (§3 skeleton) — the skip-without-guilt dormant stretch; not built. **MAINTAINER-VERIFY:**
  the columnar "Columnar store" CI lane green at the #661 tip (Part-3H asked to confirm it; the real-httpfs
  round-trip is egress-blocked in-sandbox + no `gh` here, so it could NOT be confirmed in-session — check origin/0.2).
  The `~/.oo_push_token` used for these pushes should be REVOKED + removed once this session's PRs are reviewed.
  **OMNIBUS CONTINUATION CLOSEOUT (2026-07-14, "continue with all remaining items" after #662–#665 merged):**
  **Item 3 / Part-3B + Phase 2 discovery funnel — STARTED + two slices SHIPPED** (draft PR #667 onto 0.2):
  **(1)** the flagship **Wikipedia-references channel** (ruling Q3a) — zero-network, parses the external
  references of the already-stored watched-page wikitext across all editions, registers domains cited by
  ≥N distinct pages as DISABLED `SourceCandidate`s (`channel wikipedia`, editions = the diversity signal),
  wired into `run_discovery`; negative-space lens pinned as tests. **(2)** the **external_sources wiring**
  (ruling Q4a) — `discovered_via` provenance column + `resolve_external_source` idempotent upsert wired into
  `_add_candidate`, ending the table's dormancy (never writes the legacy credibility_score); additive
  migration + boot self-heal, `test_no_model_drift` green. CARRY-OVER (the dedicated Phase-2 remainder,
  spec in the #667 body): **the promotion frontier** (candidate → **trial** → **graduated**, trial
  auto-enable DEFAULT-OFF per Q3a, diversity-weighted, the Phase-1 auditor as the graduation gate) — needs
  its own additive `SourceCandidate` state columns + the impure scheduler wiring (trial-enable is a NETWORK
  action, consent-gated) + a browser-verified audit view + undo; a migration-heavy state machine = a clean
  dedicated slice. **Items 4/5/6 remain PARKED** and were re-confirmed as browser-verify-gated: Item 4's
  Leads-2.0 `sort_leads` is a genuine unwired backend core BUT wiring it REORDERS the flagship Home feed (a
  visible UX change), and the Conjunction-Lens `/api/insights/corpus-algebra` needs an N-keyword picker UI —
  both browser-unverified (Q6a); Item 6 fingerprint persistence stays the dormant stretch gated on the §8
  triage cleanup. RATIONALE (honest): the session delivered the fully-VERIFIABLE discovery-funnel backend
  spine (channel + Q4a) at full quality rather than half-building the migration-heavy promotion state
  machine or spraying browser-unverified frontend I cannot confirm — "never fabricate a pass; park the rest
  honestly." NEW LESSON recorded above (the alembic revision-id-collision / `alembic heads` CLI pitfall).
- **FIX SESSION 2026-07-14 — data-safety + field-diagnostic + law + Tails (plan of record =
  [`docs/design/FIX_SESSION_PROMPT_2026-07-14.md`](docs/design/FIX_SESSION_PROMPT_2026-07-14.md), #666,
  which also carries the reusable parallel-agent ORCHESTRATION/context-discipline section):** written by the
  Fable-5 planning instance, executed by the Claude Code CLI. SHIPPED + MERGED (per the 2026-07-14
  `docs/ledger/shipped.csv` rows): **Slice 0 corpus-backup gate (#670, DATA-SAFETY)** — the unified "large
  data" Export silently skipped the CORPUS (maintainer hit it: ~350K articles + blobs selected, drive got
  blobs only, UI said "Backup complete"); root cause was a frontend regression from `2a10cd3` where
  `_uxStartThenPoll` masked a 409 by attaching to an UNRELATED live volume job (verify/restore/other-dest)
  that reached `done`, so `_uxRun` ran the folder phase on a corpus that was never written — fixed by gating
  the folder phase on a confirmed corpus `done`+`mode==="backup"`+dest-match and re-throwing on a mode
  mismatch (`app.js:5083`); **Slice 1 is_locked_error/sqlcipher3 (#671, data-integrity)** — the "database is
  locked" retry net was dead on encrypted stores (`is_locked_error` required a `sqlalchemy OperationalError`,
  but sqlcipher3 raises an unwrapped error → 297 field articles left unindexed); now matches the message
  across the sqlcipher3 error class too; **Slice 3 law schema foundation (#676)** — `LawDocument.latest_text`
  / `LawRevision.full_text` columns; **Slice 4a review-half (#674)** count-only non-article SCAN, **Slice 4b
  (#673)** three keyword-extraction junk sources killed at the extractor, **4c verified-present, 4d = the
  `[segmentation]` operator step**; PLUS the **Tails venv auto-install (#677)** (its own shipped.csv row).
  **CARRY-OVER — pending dedicated-session FEATURES (specs live in the #666 prompt doc; do NOT lose these —
  they are maintainer requests, not merely nice-to-haves):** (a) **Slice 2 — first-launch external-drive
  DATA-LOCATION chooser** (maintainer-asked 2026-07-14): default = the app data folder, or "choose a folder"
  in which an **"OOS data"** subfolder is created; decided at first launch AFTER language + legal acceptance,
  before the passphrase; reuse the shipped A11 `OO_DATA_DIR`/`oo.env` persistence seam + honest
  writable/free-disk/tmpfs preflight. NOT built. (b) **Slice 3 remaining — laws as FIRST-CLASS corpus
  Articles** (maintainer report 2026-07-14: laws aren't scraped/keyworded/searchable/tracked like Wikipedia;
  today `src/law/track.py` is a thin capped-HTML-diff watcher, no `index_article`, tiny static catalog):
  schema (#676) is in; REMAINING = store the FULL text per revision, ingest via `index_article` mirroring
  `src/wiki/corpus.py`, `search_omni` content match, a reader tracked-changes view, and PDF handling
  (pypdf). This is the law half of the standing **"Versioned sources as first-class Articles"** ruling and is
  NOT P0-scale-gated (tens–hundreds of docs, not millions). (c) **Slice 4a remaining — reversible retroactive
  non-article QUARANTINE** (only the count-only scan shipped; the quarantine action stays to build). **Tails
  KNOWN LIMITATION (recorded, honest, not a bug):** the #677 fix closes the venv-PACKAGE gap, but a stock
  Tails is Debian 12 = **Python 3.11**, so a 3.13 interpreter must already be present (`OO_PYTHON`) and
  `python3.13`/`python3.13-venv` are NOT in Tails' default repos — stated in QUICKSTART; a Tails "just works"
  claim would be fabricated. **fork-3:** the Slice-0 backup gate is source-guard/backend-contract tested but
  BROWSER-UNVERIFIED — a click-through of the Export/Import flow is owed.
- **V1 PATHWAY — PLANNING SESSION 2026-07-14 (maintainer-directed, docs-only; plan of record =
  [`docs/design/V1_PATHWAY_2026-07-14.md`](docs/design/V1_PATHWAY_2026-07-14.md); draft PR onto 0.2,
  branch `claude/app-roadmap-v1-u8q111`):** the maintainer restated the MISSION (a free, local-first
  360°-view instrument over the open internet for citizens/journalists — worldwide languages, honest
  AI enhancement, cross-language keyword analytics over news/laws/Wikipedia/OSM + track-changes; "our
  gift to citizens of the world") and asked for (a) a **RECURSIVE SELF-IMPROVEMENT STRATEGY** as the
  main deliverable and (b) an AMBITIOUS pathway to v1.0 (~1 year acceptable) incl. NEW VERTICALS —
  IP/patents, PubMed/medical, climate/environment, war/defense, elections. THE PLAN (composes with,
  never duplicates, ROADMAP/SCALE_ROADMAP/STORAGE_5TB/OPTIMIZATION_PROGRAM/ACTION_PLAN-2026-07-13):
  **§2 the recursive improvement loop** — SENSE→COMPARE→PLAN→BUILD→VERIFY→MERGE+RECORD, a
  human-supervised flywheel with AI leverage at every stage, explicitly NOT autonomous
  self-modification (draft-PR-only; the ethics/non-negotiables layer is constitutionally OUT of the
  loop's optimization reach); the K1–K14 KPI board (each metric stands alone, NO composite — unlock,
  p95, backup-bounded-RAM, crash-free run, keyword noise, translation coverage, date recall, source
  health+diversity, IR/perception eval, i18n, browser-verified %, vertical freshness, dev health);
  new instruments **R1** (`/api/diagnostics/kpi` machine-readable snapshot) **R2** (stdlib
  `kpi_diff.py` — improved/regressed/unchanged/not-measurable, never blended) **R3** (the AppVM
  runner + `ui_walk` = the browser burn-down engine, named the HIGHEST-LEVERAGE single build)
  **R4** (`docs/process/IMPROVEMENT_CYCLE.md` standing protocol) **R6** (the gold-set grading
  flywheel: 15 min of grading per cycle instead of one heroic never-happening session); LLM-in-the-
  loop stays propose-never-auto-apply (triage/ring-candidates/extraction-candidates/audit-assist).
  **§3 the version train** 0.2→1.0 (gate-driven, ~4 quarters): 0.3 measured-&-verified (loop v1 +
  AppVM burn-down + operator unblocks) · 0.4 living sources (LAWS first → ONE small wiki edition →
  editions behind storage milestones; P0-gated as ruled) · 0.5 investigator's desk (claim workspace
  A1 + entity spine + dossier seed) · 0.6 elections+climate · 0.7 patents+medical · 0.8 conflict +
  the 360° dossier · 0.9 hardening RC (the RELEASE_1.0_RC_GATE built from §8) · 1.0. **§4 the five
  verticals**, each riding the MANDATORY vertical pattern (dated catalog → guarded fetch → pure
  parser w/ negative-space skeptic → vintaged store → the 3 rails Article/StatFigure/Agenda →
  distinct provenance class → surface w/ visible caveats → per-vertical freshness diagnostics →
  ledger) with web-verified source tables (per-row verification status ✅fetched/🔎search-verified/
  ❓unverified-lead; fabrication-banned research; GDELT-firehose/BigQuery-only/bundled-keys
  de-prioritized in §4.6). **§7 the 9 open rulings** (V1-1..V1-9: train approval · user-supplied-
  API-keys policy · restrictive-license policy (ACLED-class) · PubMed bulk-vs-API · win/mac at 1.0 ·
  KPI bars · the storage-§8 rulings (urgent, CREATE-time-irreversible) · elections-required-for-1.0 ·
  the 1.0 Wikipedia edition-count bar).
  **§8 the V1 acceptance checklist.** NOTHING CODED this session; next concrete builds = R1/R2/R4
  (buildable-now) + R3 (VM-gated) once the maintainer approves the train.
  **ADDENDUM — ELECTIONS COVERAGE FLOOR + PROJECTED-DATE HONESTY (maintainer ruled 2026-07-14,
  same session; recorded in V1_PATHWAY §4.5):** (1) elections must cover AT LEAST every country
  whose official/major language is among the 12 UI languages (a dated, sourced language→country
  mapping — never guessed; becomes the elections component of the K13 bar). (2) recurrence-
  PROJECTED dates are a THIRD, explicitly-UNRELIABLE confidence tier — `scheduled` (official
  date, sourced) · `window` (legal window, the France-2027 `confirmed:false` pattern) ·
  `projected` (sourced rule + last-held; an every-N-years pattern may NOT hold — war,
  dissolution, death, coup, court ruling, snap election); the caveat is VISIBLE by default ×12,
  a projection is a prompt-to-check never an assertion, a passed projected date is marked
  "status unknown — check the official source" (itself an investigative lead) and NEVER silently
  re-projected, and no sourced rule+last-held ⇒ NO projected entry (a gap, never a guess).
  (3) acquisition = a PARALLEL INTERNET-CONNECTED session (the Wikidata-generator precedent)
  researching per-country recurrence rules + official electoral-authority sources → a dated
  sourced snapshot (config + `*_AS_OF` + registry + freshness test), layered with the Wikidata
  CC0 snapshot + per-user ElectionGuide freshness where terms allow. Strengthens V1-8
  (elections at 1.0), which formally stays the maintainer's ruling.
  **ADDENDUM 2 — PUBMED STANDING (maintainer ruled 2026-07-14, same session; recorded in
  V1_PATHWAY §4.2):** PubMed is NOT a privileged source — no elevated trust/weighting; its
  "evidence-based" character is a descriptive stance-claim per the stats-agencies precedent
  (the user judges; retractions prove the exception) — BUT its content database is
  ARCHITECTURALLY separate (~38M records; the managed-dataset/wiki-dump pattern: own storage
  posture on the storage-plan milestones, own diagnostics, own filterable provenance class,
  never blended into the news corpus by default; papers surface BESIDE news with provenance
  visible — the separation is size/shape, never a trust statement). Ingest = metadata + ABSTRACTS
  (the always-available layer); full text only where OA (PMC subset); a paywalled full text is
  an HONEST GAP — link out, never scraped around.
  **ADDENDUM 3 — OPTIMIZATION-TAIL SESSION BRIEF (maintainer-asked 2026-07-14, same session):**
  the operating manual for one autonomous CLI session closing every CODEABLE-NOW optimization
  left open = [`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-14_OPTIMIZATION_TAIL.md`](docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-14_OPTIMIZATION_TAIL.md)
  — 13 ordered slices: R5 LOOP_SELFTESTS backfill+enforcement (12 harnesses vs 4 registered) ·
  R1 KPI snapshot · R2 kpi_diff · R4 IMPROVEMENT_CYCLE.md · instrument_search live wiring ·
  the maintained per-Source article counter (unblocks source_io + the reader count) ·
  diagnostics/keywords pass-collapse (efficiency NEVER truncation — capping the keyword crunch
  stays forbidden) · debug-bundle hardening · anomalies/correlation grouped-SQL · framing cap ·
  power-profile live application · Leads-2.0 surfacing + Conjunction-Lens picker (both
  conservative+flagged per Q6a, defaults preserving today's behaviour). Exclusions stay
  operator/VM/ruling-gated (R3/R6/triage bench/GAMMA/V1-7/fingerprints/Tor-live).
- **OPTIMIZATION-TAIL CLOSEOUT (2026-07-15, branch `claude/opt-tail-r5`; S1–S5 merged via #684,
  S6–S13 stacked on draft PR #685 onto 0.2; full detail = the per-slice `docs/ledger/shipped.csv`
  rows):** all 13 slices SHIPPED, each ⚠ slice adversarially skeptic-verified pre-push (S7: 2
  lenses + a 20k-seed byte-parity fuzz; S8: 3 skeptic rounds — the first cut NO-GO'd and was
  rewritten; S12: 1 honesty/isolation lens), every slice test-pinned + green in a py3.13 venv (the
  2 version tests fail only on the known sandbox `PackageNotFoundError`; scipy/sqlcipher3/[analysis]-
  gated paths are CI-only). **S6** maintained Source counter · **S7** /keywords 2-scan→1 collapse
  (byte-identical, anti-capping) · **S8** debug-bundle read-only + per-member guard + wall-clock
  budget · **S9** anomalies/correlation grouped-SQL (O(articles)→O(days)) · **S10** framing
  {analyzed_n,total_n,capped} disclosure · **S11** power-profile knobs live-wired (Optimized==today)
  · **S12** isolated Settings→Leads preview (Home byte-identical) · **S13** Conjunction-Lens picker.
  **TWO REUSABLE LESSONS (harvested; also in the Session-rituals Lessons list):** (1) **a per-member
  WALL-CLOCK budget must NOT thread a member that touches a shared DB connection (S8):**
  `statement_deadline` bounds only SQLite VM opcodes, NOT the Python row-materialisation around them;
  concurrent use of one pysqlite/sqlcipher connection BLOCKS (it does not error); a SQLAlchemy
  `Session` is not thread-safe; and a self-deadlining callee's inner `finally` clears an outer
  progress handler. So thread ONLY non-DB (socket/file/in-memory) members for a wall-clock
  `{skipped: budget}`; run DB members INLINE bounded by a statement deadline (never abandon a
  worker mid-query on a shared connection). Also: `Thread.join(inf)` raises `OverflowError` OUTSIDE
  the thunk's try/except → clamp any operator-set budget finite/≤ceiling, and a broken `__str__`
  in the error path must still set the error key or a failed member is silently lost as `None`.
  (2) **the byte-safe way to GROUP BY publish-day (S9):** `substr(published_at,1,10)` == Python
  `datetime.date()` on the naive stored ISO string — SQLAlchemy stores even a tz-AWARE UTC datetime
  as a NAIVE string, so `date()`/`substr` never diverge; prefer `substr(...,1,10)` (byte-literal, no
  `date()` tz-interpretation) and write the golden against the Python-loop reference FIRST, then
  EXPLAIN-QUERY-PLAN-check for a `USING [COVERING] INDEX` (a bare `SCAN <table>` is the only smell).
  **CARRY-OVER (browser-verify-gated per fork-3, + one deferred):** (a) **S12** — grade the Leads-2.0
  preview modes ONTO Home itself (evidence chips on Home cards, a Home sort control wired to
  `sort_leads` with the `explain_order` hover, lifecycle deltas which need a persisted
  previous-snapshot) — all VISIBLY change the flagship feed, so a click-through gates them; the
  isolated Settings→Leads preview + the `/api/insights/leads-view` backend are shipped. (b) **S13** —
  the deeper Conjunction lens views (conditional trend · vocabulary contrast · per-article intensity ·
  lead/lag) — the §1 core computes them via separate helpers, but `corpus_algebra`'s own payload does
  not carry them, so surfacing them needs a payload extension + a click-through. (c) **S7** — the
  OPTIONAL background-job variant of the /keywords export (deferred: serving per-keyword totals from
  the maintained counters would break byte-parity and cannot supply first/last-seen). Every
  conservative frontend slice (S12 subtab, S13 picker) is node-checked + invariant-guarded but
  BROWSER-UNVERIFIED — a human click-through across themes/breakpoints is owed.
  **CI FIX-FORWARD (2026-07-15, commit `8248e90f`):** the #685 `test` lane went RED (the 0.2 base
  `fa5858d0` is GREEN, so it was a real regression, not the merged≠green base-red). Root cause =
  S11 retired rollup_serve's `_MIN_REBUILD_S` MODULE CONSTANT (→ the per-serve `rollup_serve_ttl_s()`)
  and updated the src use-sites but MISSED `tests/test_serve_change_gate.py`, which
  `monkeypatch.setattr`'d `rollup_serve._MIN_REBUILD_S` at two sites → `AttributeError` erroring
  every test in the file. Fixed: the shared fixture loops over BOTH rollup_serve (constant retired
  → set `OO_COLUMNAR_SERVE_TTL_S=0`) AND `map_serve` (its own `_MIN_REBUILD_S` constant KEPT →
  `setattr` guarded by `hasattr`); the churn-bound test sets the rollup env to 900. Confirmed via a
  full local suite run (installed scipy/pandas/sklearn so the `[analysis]` block wires; the remaining
  failures are all sandbox-environmental — PermissionError sockets, PackageNotFoundError metadata,
  sqlcipher3-absent, backup helper-failed, httpfs egress-blocked — all GREEN in CI, plus a
  pre-existing `test_osm_downloads` subset-order flake unrelated to any changed code). **TWO PROCESS
  LESSONS:** (a) removing a module constant/attribute must grep the TEST tree for it in the SAME
  change (the stale-anchor family — the src use-sites are not the only referents); (b) do NOT revoke
  the push token at "closeout" until CI is confirmed GREEN — a red lane needs a fix-forward push, and
  the token was already rm'd (this fix `8248e90f` is committed but had to be pushed by the maintainer).
- **SOURCE-AGGREGATOR PROPOSAL → WORLD-DISCOVERY JOB (maintainer message 2026-07-15; branch
  `claude/source-aggregator-integration-5axvxl`, draft PR onto 0.2):** the maintainer drafted a
  single-file "source aggregator" script (aiohttp: Wikidata SPARQL + a GDELT API + a government
  domain list → DNS/HTTPS/robots/SSL validation → append to configs/sources.yml) and asked whether
  it can be adapted so the app automatically integrates a source scraper. **RULING RECORDED:
  ~3,000 catalog sources is a MINIMAL start — the source count must be SIGNIFICANTLY increased**
  (aligns with the standing `configs/catalog_query.yml` ~50k ambition). **ASSESSMENT (the
  staleness guard paid off — do NOT import the script wholesale):** its INTENT is already built in
  rules-compliant form — the networked-machine bulk generator `scripts/build_world_news_catalog.py`
  (Wikidata per-country, verified QIDs in `configs/catalog_query.yml`; `--merge-csv` is the
  sanctioned GDELT/Media-Cloud path) → `configs/world_news_sources.yml` auto-seeded once generated;
  the in-app consented guarded discovery `src/catalog/discover.py` (DISABLED rows +
  `via:wikidata-discovery` provenance); validation = `src/monitoring/preflight.py` (robots/homepage
  through the fetcher's session, transport-aware) + the #663 extraction-validity auditor as the
  real quality gate; noise filters = is_commerce/is_social/is_infrastructure (boundary-based). The
  script AS-WRITTEN breaches non-negotiables and must not land: raw aiohttp sessions (bypass
  EthicalFetcher + kill switch, silently downgrade transport off Tor, trip the socket-importer
  ratchet), robots fail-OPEN with a naive substring parse (policy is fail-CLOSED), whole-file
  yaml.dump onto the curated `sources.yml` (wrong shape — would corrupt the catalog), auto-import
  (violates review-before-enable), a substring keyword blocklist ("sex" blocks Middlesex — the
  is_commerce substring-trap lesson), status==200-required validation (mass false-rejects over
  Tor), and an UNVERIFIED `api.gdeltproject.org/v2/sources` endpoint (egress-blocked here, could
  not be confirmed to exist — the fabricated-endpoint burn; never wire it unverified). **SHIPPED
  (the one genuine gap): the WORLD-DISCOVERY BACKGROUND JOB** — the bounded sync endpoint
  (12 countries/call) could never honestly cover ~250 countries, so
  `src/catalog/discover_job.py:run_world_discovery` walks EVERY country through the existing
  `discover_sources` as a cancellable `BackgroundJob` (kind `discover-world-sources`, task-manager
  cancel for free): one country per session (writer gate never held across a fetch), a PERSISTED
  per-country cursor (`data_dir()/world_discovery.json`, atomic writes) so cancel/airplane/crash
  RESUME instead of re-querying the world, a clean airplane PAUSE (a user choice is never an
  "error"), an all-specs-failed country retried never marked done, and a 5-consecutive-failures
  breaker (total network loss must not spin through 200 doomed queries). Endpoints `POST
  /api/diagnostics/discover-world{,/cancel}` + `GET …/status` (409 under airplane; ISO-2
  validation; restart=1 ignores the cursor); a Diagnostics-panel button (`discoverWorld`,
  ensureOnline-gated #14, live status line, un-keyed-diagnostics-strings convention,
  BROWSER-UNVERIFIED per fork-3/Q6a). tests/test_world_discovery_job.py (7 behaviour + the
  composed-route wiring guard per the 1c lesson; a real bug caught pre-push: `discover_sources`
  SPREADS generate_catalog's stats top-level, so the failed-country detector read a nested key
  that never exists). REMAINING/OPERATOR: actually RUN it (Wikidata is egress-blocked in the
  sandbox — both paths need a networked machine): the job populates ONE install; a
  `build_world_news_catalog.py` run commits `world_news_sources.yml` for EVERY install — the two
  are complementary, do both. **RIDE-ALONG RULED + SHIPPED same day (maintainer, verbatim "I'd
  prefer everything to be background and automated (concerning the scrapping)"):** the pending
  scheduler ride-along is now BUILT and DEFAULT-ON —
  `discover_job.advance_world_discovery(per_pass)` advances the SAME persisted cursor a bounded
  `world_discovery_per_pass` countries (scheduler setting, default 2, 0=off, ranged 0..12,
  exposed on PUT /api/scheduler/config) per online collection pass, wired into the runner's
  post-pass housekeeping beside `run_discovery` (best-effort, own per-country sessions, never
  breaks a scrape); it skips HONESTLY (named skip) under airplane / while the manual job runs
  (never two writers on one cursor) / once the world is complete. Riding the pass keeps it
  inside the one consent envelope (the stats-vintage auto-refresh precedent, ruling #12).
  HAZARD FIXED with a regression pin: `completed_at` is now stamped only when the WHOLE world
  is done — a manual SUBSET job run must never stop the ride-along for the other ~240 countries.
  BOUNDARY KEPT (recorded, not changed): automation covers DISCOVERY — every find stays a
  DISABLED source for review; auto-ENABLING is the Phase-2 promotion frontier
  (candidate→trial→graduated, ruling Q3a, still the parked dedicated-session build) with the
  #663 auditor as its gate; this ruling strengthens the case for trial auto-enable when that
  frontier is built, but review-before-enable was not flipped unilaterally here.
- **DOCUMENTATION REVIEW — SURVEY + ACTION PLAN (maintainer-asked 2026-07-17, docs-only; plan of
  record = [`docs/design/ACTION_PLAN_2026-07-17_DOCS_REVIEW.md`](docs/design/ACTION_PLAN_2026-07-17_DOCS_REVIEW.md),
  branch `claude/project-documentation-review-02fjca`, draft PR onto `main`):** a full survey of the
  documentation tree at `786a5c1` found the CONTENT healthy (live set all touched ≤1 week; the
  2026-07-15 external-audit doc findings already remediated) but the META layer drifted. The plan
  hands a CLI session 7 verified-anchor tasks: **T1** `docs/README.md` index reconciliation (misses
  the first-launch-gating `docs/legal/` tree, GOVERNANCE, CODE_OF_CONDUCT, QUARANTINE_ARCHIVE,
  `docs/audit/` incl. both 2026-07 audits, root AUDIT_TRAIL/PARKED, process/IMPROVEMENT_CYCLE,
  USE_CASES, maintenance/testing/research/i18n) + **T2** a `test_docs_index_covers_live_docs`
  repo-invariant guard; **T3** AUDIT_TRAIL.md backfill (append-only ledger stops at 2026-06-18 —
  missing the 2026-07-13 cumulative-integrity + 2026-07-15 external audits); **T4** the stale
  "Version: [À COMPLÉTER]" Outstanding note in `docs/testing/LEGAL_DECLINE_UNINSTALL_TEST.md`
  (legal docs finalized v1.0 2026-07-16; remaining bracketed markers are the PERMANENT no-lawyer-
  review choice per `docs/legal/README.md` — never "fix" those); **T5** USER_MANUAL: banner the
  embedded historical `# What shipped in 0.0.8` section (line ~2269) + re-verify nav claims vs
  `src/static/index.html` (the twice-bitten stale-nav precedent); **T6** QUICKSTART: retire the
  legacy "Phases 2–5" heading vocabulary (§D content verified CURRENT — only the framing is stale)
  + mirror to `docs/i18n/fr/`; **T7** PARKED.md reconciliation — SPOT-VERIFIED 2026-07-17: MAINT-03
  `Mapped[]` migration DONE (448 uses, 0 legacy), core-only CI job DONE (ci.yml:164), PERF-02 FTS
  bound LIKELY-DONE via S2.5 (verify), MAINT-04 print→logger STILL OPEN (68 live calls), mypy still
  the ratchet — annotate statuses in place, non-lossy, ROADMAP §4 stays the one live board.
  **EXTENDED same day (maintainer "yes" after the design-folder + FUTURE_DEVELOPMENTS deep dive —
  4 parallel readers, verdicts tree-anchored): + T8** `docs/design/` archival sweep — 7 verified-SPENT
  docs move to `docs/archive/{design,session-briefs}/` (DB_RELIABILITY_01/02, COLLECTOR_WRITER_BATCHING,
  KEYWORD_BASELINE_AND_MANAGEMENT, OPTIMIZATION_PROGRAM_ACTION_PLAN_2026-07-13, the OPTIMIZATION_TAIL
  brief [all 13 slices verified shipped], UNIFIED_IMPORT_EXPORT after its cleanup line lifts), GATED on
  T8.0 lifting the ONLY-HERE carry-overs to ROADMAP first (fix-session Slice 2 data-location chooser +
  Slice 4a quarantine ACTION + the unified-import browser-gated JS cleanup) and T8.1 reconciling
  FIX_SESSION_STATE's drift (Slice 3 laws-as-Articles is DONE — `src/law/corpus.py` shipped; the #691
  law_revisions-collision field bug corroborates); the fix-session pair itself STAYS live until Slice
  2/4a build; hand-re-verify every agent verdict before moving (06-audit lesson). **+ T9**
  FUTURE_DEVELOPMENTS reality-check — the ≥2026-06-15 cohort has 9 verified-STALE "designed-only"
  sections whose code shipped (clickable keywords, poll analysis, ~7/9 manipulation cards, Home Latest,
  content-provenance, the 2026-07-12 program section) + 4 embedded historical ledgers to archive + the
  §1/§22 Wikipedia and §35/§43 statistics duplicate pairs (banner-don't-merge default; NEVER drop a
  recorded ruling — §22 holds the superseding auto-track ruling) + the bare SCALE_ROADMAP.md link fix.
  **+ T10** two storage-doc one-liners (STORAGE_5TB_PLAN's stale "journal_size_limit set NOWHERE" — now
  set at session.py:137; a rec-status header on 5TB_ARCHITECTURE_REVIEW). LIVE designs-of-record
  confirmed KEEP: V1_PATHWAY · PLANNING_2026-07-12 · ACTION_PLAN_2026-07-13 · RECURSIVE_IMPROVEMENT_RUNBOOK ·
  DATA_ARCHITECTURE_SKELETON · STORAGE_5TB_PLAN · DB10 memo (its auto_vacuum/page_size CREATE-time ruling
  is the one time-sensitive OPEN decision) · SOURCE_DIVERSIFICATION_BRIEF · SOURCE_METADATA_ENRICHMENT ·
  KEYWORD_ENGINE_OPTIMIZATION_STRATEGY (sole spec for P5.2 embeddings/P6 entities + the P2.4 guardrail) ·
  PERSISTED_DUCKDB_HTTPFS + SCALING_DERIVED_LAYER (alive until the httpfs binaries land).
  PENDING: the plan's execution (a CLI session per its §0 working mode).
- **BACKUP/RESTORE BAR = PLAIN-FOLDER-COPY PARITY (maintainer ruled 2026-07-17, verbatim intent:
  "I can always copy the entire folder to an external drive, do a fresh install on a different
  computer, replace the folder, and have that done in a few hours. Our backup-restore shouldn't be
  more complicated, difficult, or dangerous/risky to perform."):** the app-stopped filesystem copy
  of the DATA folder is a FIRST-CLASS, endorsed backup/move path at every scale (it was already the
  SCALE-MANDATE interim guidance — encrypted at rest, keys travel inside the folder, the passphrase
  is the only secret; the three safety details are: it is the DATA dir [default
  `~/.local/share/open-omniscience` or the A11 `OO_DATA_DIR`], NOT the app/code folder; the app must
  be STOPPED first, or the copy can catch a torn WAL; the Ollama model store lives OUTSIDE it). The
  in-app backup/restore must NEVER be more complicated, slower-per-byte, or riskier than that cp
  baseline — its justification is what it ADDS (signed-manifest verification, parity
  corruption-recovery, additive MERGE of two corpora, selective members, runs attended without
  stopping the app), and it must never be a gate the user has to pass. **COROLLARY for DB-10
  (corrects this session's chat over-statement that "the migration window closes as the corpus
  grows"):** a byte-copy preserves the CREATE-time seam (auto_vacuum/page_size), so cp cannot
  migrate it — but the honest migration op is NOT the row-level restore-merge either; it is a store
  REBUILD into a fresh-pragma target (`sqlcipher_export()` to an ATTACHed target created with the
  new pragmas / `VACUUM INTO` with pragmas set — the same machinery `connect.py` already uses for
  encrypt/decrypt conversion), which is cp-CLASS cost (hours + one spare drive) at ANY size. So the
  DB-10 §1a urgency is about NEW-corpus DEFAULTS (every corpus born before the ruling later needs
  the rebuild), not a closing window — and the DB-10 1a/1b ruling itself is STILL OPEN.
  VERIFY-BEFORE-BUILD when the migrate op is built: empirically confirm the attached/INTO target
  honors `auto_vacuum` + `cipher_page_size` under SQLCipher (a P2.4-style probe — never assert it
  from docs), and the op must state its cost + app-stopped/gate-held posture honestly. DOCS
  FOLLOW-UP (fold into the docs-review plan execution): the USER_MANUAL backup chapter should
  present the folder-copy path as prominently as the in-app tools, with the three safety details.
- **DB-10 §1a RULED 2026-07-17 (maintainer, verbatim "I agree with your proposal to change the
  auto_vacuum to incremental"): `auto_vacuum=INCREMENTAL` ON CREATE for NEW corpora — YES.**
  Buildable-now for the next code session: the fresh-file PRAGMA in `connect.py` (the
  `not p.exists() or size==0` branch ~line 86, before the first table / `PRAGMA key`) + the DB-10
  §3 bounded idle `incremental_vacuum(N)` pass in `run_idle_maintenance` (a documented no-op on
  pre-seam corpora, so safe to wire immediately) + the §2 full-VACUUM-button size gate.
  **§1b `page_size` stays MEASURE-GATED — now with a maintainer-endorsed measurement path: an
  AUTOMATED 4K-vs-16K A/B bench run over the maintainer's REAL BACKUPS of different sizes.**
  Design facts verified 2026-07-17: `scale_bench` copies a corpus and benches it
  (unlock/WAL/endpoint p50-p95/RSS) but a FILE COPY preserves page structure, so it CANNOT A/B
  page sizes today — the missing slice is a rebuild-at-pragmas step. Run it at SEVERAL backup
  sizes to measure the TREND — the slope toward 5 TB is the decision signal, not any single
  point. EMPIRICAL correction to the memo's §1b cache concern: the app's `cache_size` is
  KiB-DENOMINATED (`session.py:122`, negative form), so cache BYTES are constant across page
  sizes — the real trade-off to measure is codec granularity (a 16K page decrypts 4× the bytes
  per point lookup) vs fewer codec calls per range-scan byte. **THE BENCH SHIPPED same day
  (maintainer-asked "add a diagnostic tool to test that idea"; shipped.csv row):**
  `src/monitoring/pagesize_bench.py` + the `pagesize-bench` BackgroundJob +
  `POST/GET /api/diagnostics/pagesize-bench{,/status,/cancel,/last,/download}` + a Settings →
  Diagnostics panel — rebuild the live corpus per candidate size (plaintext `VACUUM INTO`,
  encrypted `sqlcipher_export` into an ATTACHed target keyed with the SAME passphrase so the
  codec stays in the measurement), SELF-VERIFY every target (pragmas read back + article count,
  refuse mismatch — the verify-before-build probe made permanent), identical deterministic
  workload (point lookups · 30-day covering-index window · sequential content bands, first-pass
  vs warm), sequential staging under a swept `.pagesize-bench-` prefix + disk preflight; numbers
  side by side, NEVER a winner; the report's `rebuild.seconds` doubles as the measured migration
  cost at that corpus size. EMPIRICALLY PROVEN in-sandbox for plaintext (`VACUUM INTO` inherits
  page_size+auto_vacuum — pinned as a test); the encrypted path is covered by the same runtime
  self-verify. OPERATOR: run it on a SMALL and a LARGE corpus and send both logs (it rides the
  all-diagnostics bundle as `pagesize-bench.json`, last-report read-only).
  **§1b EVIDENCE PAIR DELIVERED (maintainer ran both, 2026-07-19 + 2026-07-20, after the
  encrypted-path fix): 16384 WINS EVERY DIMENSION AT SCALE — recommendation FIRM, awaiting the
  maintainer's ratification.** Run 1 = 2.95 GB / 67,758 articles / 5.17M mentions (4-core Qubes);
  run 2 = 22.2 GB / 474,556 articles / 40.6M mentions (6-core Qubes), both encrypted, live
  corpora. Warm p50, 4096→16384: index_window 510→334 ms (−34%) at 3 GB and 2525→1268 ms (−50%)
  at 22 GB; content_band −26% / −14%; rebuild −23% / −37%; file −1.9% both. THE DECISIVE FINDING:
  the ONE shape 4K won at 3 GB (warm point lookups, 0.040 vs 0.091 ms) INVERTED at 22 GB (0.459
  vs 0.203 ms — 16K 2.3× faster): the 4K advantage was a CACHE-FIT ARTIFACT — once the working
  set exceeds cache, every lookup pays real I/O + codec and 16K's shallower tree / fewer codec
  calls per descent dominates; the memo's codec-granularity fear (16K decrypts 4× bytes per
  point access) is empirically OUTWEIGHED exactly where it was feared. Stability signature: 16K's
  warm index_window ≈ its cold (1272→1268 ms) while 4K DEGRADED cold→warm (1569→2525 ms, scan
  thrash) — the gap widens toward 5 TB. Migration cost from rebuild.seconds: ~10–17 s/GB (≈4–6
  min at 22 GB; ≈30 min at 100 GB — cp-class, as the folder-copy-parity ruling predicted).
  RECOMMENDATION: `page_size=16384` ON CREATE for NEW corpora, alongside the ruled
  `auto_vacuum=INCREMENTAL` (§1a) — ONE fresh-file-pragmas build slice in `connect.py` covers
  both, plus the §3 idle incremental_vacuum pass + §2 VACUUM-button size gate (the same
  buildable-now set §1a queued). Existing corpora migrate via the proven rebuild op when the
  maintainer chooses (the bench IS the mechanism proof; a user-facing migrate op is a separate
  build). Residual bench nit: `source.page_size` in the report header is an uncoerced TEXT
  read-back ("4096") — display-only, fold `int()` into the next touch.
- **"ALL DIAGNOSTICS" MUST COMPRISE ALL DIAGNOSTICS (maintainer flagged 2026-07-17 "it seems not
  while it should" — CONFIRMED + FIXED same day; shipped.csv row):** the bundle had drifted 12
  members behind the router since the #645 membership pass. Added the missing read-only reports
  (source-audit · non-article-scan · lemma-preview · power-profile · data-dir-persistence) + the
  cheap deterministic selftests (ir-eval · perception · triage · search-timing · power-profile ·
  source-audit) + the pagesize-bench last-report; deliberate exclusions are now DOCUMENTED in the
  manifest's `excluded` block with reasons (the full keyword dump · the source-quality
  whole-corpus-decrypt ZIP · the two heavy operator benches · ir-eval's gold-set input · the
  interactive gold-builder · job-control endpoints) instead of silent. RATCHET:
  `test_repo_invariants.py::test_all_diagnostics_bundle_covers_every_get_diagnostic` — every GET
  route on the diagnostics router must be a bundle member or an exemption-with-reason, so the
  bundle can never silently fall behind again.
- **LAW VERTICAL — INVESTIGATION + SESSION BRIEF (maintainer-asked 2026-07-17: "a proper,
  intelligent, adapted and performant strategy to scrap each country's legal articles … ingested
  the same way articles are … track their changes. Currently I don't see anything working despite
  my previous attempts"; brief of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-17_LAW_VERTICAL.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-17_LAW_VERTICAL.md)):**
  INVESTIGATION VERDICT (tree-anchored, `main`@af30b39): the vertical is NOT missing — it is 6
  days old and substantially built (models+catalog ~47 portals/~17 tracked docs boot-seeded ·
  `auto_track_due` on EVERY online pass since the 2026-06-22 field fix · laws-as-corpus-Articles
  via `index_article` since `fc75aa0` 2026-07-14 · API+reader+omnibar group+`law_change`/
  `model_legislation` cards). WHY IT LOOKED DEAD (ranked): (1) a cross-driver IntegrityError
  (sqlcipher3's unwrapped class missed by the `except IntegrityError`) SILENTLY POISONED the
  tracking pass on the encrypted default store — fixed only `38c0502` (2026-07-17, the 4th
  recurrence of the #691/#696 family), exactly spanning the maintainer's attempts; (2) the
  sidebar tab is labelled "Governments" and opens on Countries — the Law subtab is 2 clicks deep;
  (3) `/api/law/changes` defaults `flagged_only=True` → a working tracker renders "no changes"
  indefinitely on consolidated statutes; (4) baselines need sustained ONLINE passes (5/pass,
  24 h gate); (5) robots fail-closed verdicts hidden in a table column; (6) `[pdf]` optional.
  REAL GAPS: ~17 curated docs ≠ per-country corpora (no adapters/enumeration); no
  add-document-by-URL; `law` missing from PROVENANCE_CLASSES (buckets as `web`); no per-vertical
  coverage/freshness diagnostic. THE BRIEF (one CLI session, open egress, staleness guard
  emphatic — the vertical changed 4× in its 6 days): S1 PROVE it end-to-end live (the trust
  reset) → S2 truth-in-UI (changes default all-changes, per-doc verdicts loud, discoverability
  pointer) → S3 add-by-URL → S4 provenance class LAW → S5 law-coverage diagnostic (bundle member
  per the new ratchet) → S6 the ADAPTER seam + 2-3 LIVE-VERIFIED structured-source adapters
  (bulk/API-before-scraping, the SDMX precedent: legislation.gov.uk XML · gesetze-im-internet XML
  · EUR-Lex ELI; Légifrance = key-gated API vs LARGE DILA bulk job, deferred choice) → S7
  gazettes-as-streams (verified RSS → the normal pipeline as source_type legal) → S8 docs.
  Granularity RULING pending (act-level default vs per-legal-article split); `[pdf]`-in-default
  + coverage priorities + cadence = §4 maintainer decisions. Never fabricate a source: every
  committed endpoint must be fetched by the executing session (✅/🔎/❓ statuses; ❓ ships
  disabled). **AMENDED same day (maintainer: "47 portals don't seem legitimate at all — France
  alone has 76 different codes", citing the live Légifrance code list): THE COMPLETENESS
  PRINCIPLE is now the coverage bar** — a portal is an entry point, never a coverage claim;
  covering a jurisdiction = covering its OWN official enumeration (France: 76 codes en vigueur +
  non-codified statutes; DE: gesetze-im-internet's thousands; UK: every ukpga/uksi). Threaded
  into the brief: adapters must enumerate collections COMPLETELY (never a sample presented as
  coverage); the S5 diagnostic reports tracked-vs-enumerated with the DENOMINATOR from the
  source's own list ("France: 12/76 codes"), else "no enumeration adapter — coverage unknown";
  whole-country corpora take the MANAGED-DATASET posture (bulk jobs like wiki dumps — France's
  DILA/LEGI full-base+daily-deltas IS the law-world instance of the ruled dump-as-baseline+delta
  architecture; ~10⁵ legal articles in force for France makes the §4 granularity ruling
  scale-critical, to be ruled BEFORE the first whole-country ingest). The Légifrance page 403s in
  the sandbox — the executing session re-verifies the 76 count live. PENDING: the brief's
  execution.
  **ACQUISITION CHANNEL RULED + INTAKE SHIPPED same day (maintainer: "a parallel, autonomous,
  internet connected session that would produce a digestible file that would enrich the current
  law internet endpoints to scrap, with all proper metadata associated (Cambodian law is in
  French, for example)"):** the world-scale catalog growth runs through PARALLEL internet
  research sessions per region batch → `configs/legal_sources_generated.yml` — contract +
  ready-to-paste prompt + vetting protocol in
  [`docs/design/LAW_SOURCES_ACQUISITION_2026-07-17.md`](docs/design/LAW_SOURCES_ACQUISITION_2026-07-17.md)
  (the Wikidata-rings/world-news-catalog pattern). Metadata carries languages-OF-THE-LAW (≠ the
  country's spoken languages), legal_system family, enumeration_url + DATED official_count (the
  S5 coverage denominators, only ever read off the official page), structured api/bulk/formats
  (the adapter worklist), per-row verification status (fetched/search-verified/lead — a lead
  ships for maintainer decision, never as verified). SHIPPED with the ruling: the CURATED-WINS
  intake seam (`load_legal_catalog` merges the generated file; no file = byte-identical) +
  `scripts/validate_legal_catalog.py` (offline lint: schema/ISO/https/dedup-vs-curated/undated-
  count refusal/lead listing) + tests (spec-load past the py3.11 PEP-695 import wall). FOUND +
  routed into the brief as S4b: registration DROPS the catalog's language (LawDocument has no
  language/country columns; law corpus Articles ingest language=None) — the Cambodia-in-French
  case gets wrong keyword treatment until S4b threads catalog→LawDocument→Article.language.
  **FIRST 8 BATCHES RECEIVED + MERGED same day (maintainer's parallel sessions delivered:
  africa-west · africa-east · africa-central-south · mena · europe-central-baltics-microstates ·
  europe-east-caucasus · south-central-america · southeast-asia):**
  `configs/legal_sources_generated.yml` now carries **163 sources + 7 documents** (verification:
  55 fetched · 100 search-verified · 8 leads), mechanically merged (documents `country:`→
  `jurisdiction:` renamed; missing verification → `lead`) and validator-clean. The validator was
  CALIBRATED against the real data (contract amendments recorded in the acquisition doc §2, so
  future sessions + intake agree): `structured.api/bulk` = URL OR descriptive phrase (adapter
  metadata, not fetch targets); **http-only portals = a listed WARNING, never silently rewritten
  to https** (7 such: liberlii.org · ulrc.go.ug · minjustice.gov.cm · gacetaoficialdebolivia.gob.bo
  · laoofficialgazette.gov.la ×2 + the Mauritania count source); a domain-less row allowed ONLY as
  the honest-gap `lead` (Yemen: no working portal — the loader skips domain-less rows by
  construction); in-file dedup key = `(domain, kind)` — one host may carry codes-portal AND
  gazette as two rows (10 such hosts), REGISTRATION must collapse them (Source.domain unique, S6's
  job). MAINTAINER-VETTING BOARD (in the PR body): 9 leads to decide; ~20 domains flagged
  robots-blocked/bot-walled by the sessions (they cannot be scraped fail-closed — adapter/API
  paths or honest gaps; incl. zakon.rada.gov.ua, suin-juriscol.gov.co [datos.gov.co mirror
  suggested], sinalevi.go.cr [domain migration ~2026-07-20], congresonacional.hn, amategeko.gov.bi);
  27 dated official_counts landed = real S5 denominators (AM 208,987 acts · CO 87,392 normas ·
  CV 76,947 · MG 40,000 · BY/GE 26 codes · UY 13 codes …); the Mauritania 30,000 count is
  press-release-sourced (self-disclosed in-row as approximate — kept with the disclosure).
  REMAINING batches: Europe-West/North gap-fill · Central+South Asia · East Asia · Oceania ·
  North America+Caribbean · supranational. **FINAL 4 BATCHES RECEIVED same day — THE WORLD SWEEP
  IS COMPLETE (central-south-asia · caribbean · oceania · supranational): the merged file now
  carries 225 sources + 7 documents across 162 jurisdictions (91 fetched · 124 search-verified ·
  10 leads · 10 http-only warnings), validator-clean.** Europe-West/North + jp/kr/cn were already
  curated (the 12-UI-language floor; mn/tw delivered in central-south-asia) — a gap-fill pass is
  optional polish, not a missing batch. New calibration: the in-file dedup key widened to
  `(domain, kind, COUNTRY)` — a multi-country platform (PacLII pg/sb/ki) is one row per
  jurisdiction. North Korea = a CONFIRMED documented gap (no DPRK public portal; the kp comment
  block in the generated file carries the evidence, preserved verbatim through the merge).
  Notable in the final four: two COUNTS not read off the official page, both self-disclosed
  in-row (Council of Europe 231 via Wikipedia — coe.int is a JS-SPA; AU ~80 = a manual tally
  with a known duplicate row); Grenada's laws.gov.gd is DOWN ("Upgrading…" placeholder);
  Vanuatu's parliament portal outsources its consolidated texts to PacLII; St Vincent's
  legal.gov.vc has a WORKING Joomla RSS gazette feed (2nd confirmed S7 candidate after
  Vietnam); Turkmenistan/Maldives/Bhutan = thin-coverage or no-gazette realities recorded
  honestly. **REGISTRATION POSTURE (CI catch, fixed forward same
  day):** `seed_legal_sources` consumes `load_legal_catalog` at BOOT, so the merged generated
  rows were seeding ENABLED (Source.enabled defaults true; the entries carry no `enabled` key) —
  breaching review-before-enable AND reddening test_preflight (163 extra enabled sources pushed
  the test's synthetic domains past `recent_results`' 200-row cap; all 3 lanes red at 127f631).
  FIX: generated rows are marked `_generated` by the loader; `registration_source_rows` (pure)
  forces `enabled=False` + `via:legal-generated` provenance on them (curated posture untouched),
  and `registrable_documents` (pure) lets a generated document register as watched ONLY when its
  session verified it (fetched/search-verified) — an unverified `lead` document never silently
  becomes a watched LawDocument. Enabling a generated source stays a maintainer action (or the
  future Phase-2 promotion frontier). **SUPERSEDED same day for the ENABLE half (maintainer ruled
  2026-07-17, verbatim "regarding disabled sources, nothing has to be manually done by the user.
  Could you enable everything by default"): generated law-catalog sources now ENABLE BY DEFAULT**
  — the maintainer's review of the committed catalog file IS the vetting gate (the merged file is
  vetted data, unlike runtime-DISCOVERED candidates, which still register disabled — the discovery
  funnel is a different channel and its Q3a posture is unchanged). Network-safe by construction:
  legal portals carry no rss_url so collect passes never fetch them; robots stays fail-closed
  (the ~25 robots-blocked domains get honest verdicts, never fetched); the bounded preflight
  becomes the AUTOMATIC verifier of lead domains. The `via:legal-generated` provenance stays. The
  lead-DOCUMENT exclusion stays (never fetch an unverified URL — that half is about fetch targets,
  not user convenience). test_preflight's log assertion now reads `recent_results(limit=2000)`
  (the log's own retention window, not the 200-row display default) so a large enabled catalog
  can't crowd out its synthetic domains — asserting LOG membership, not display ranking.
  **TAGS + PROVENANCE SHIPPED same day (maintainer: "make sure that there's a proper article tag
  dedicated to laws, as well as proper dedicated tags for wikipedia articles, and so forth. Tags
  should also be deduced from source type, and source tags"):** `LAW` joined PROVENANCE_CLASSES
  (`provenance_of`: source_type legal/ip AND the synthetic `law.*.local` domains → law; closed-set
  test extended, 17 green) + the CHANNEL-IMPLIED TAGS system in `src/catalog/provenance.py`:
  `CLASS_IMPLIED_TAGS` + pure `implied_tags()` (explicit tags kept in order, implied APPENDED only,
  ip additionally implies `ip`) + idempotent `ensure_channel_tags()` boot heal over a bounded
  candidate set (wiki editions · law.*.local · legal/ip/statistics/cited source_types · newsletter
  buckets), wired into BOTH seed sites in main.py; `ensure_law_source`/`ensure_wiki_source` set
  tags at creation. So tag-based filters (analysis `tags` param, scheduler select_tags, wizard
  themes) now find law/wikipedia/statistics/newsletter articles. The law brief's S4 is struck
  SHIPPED (residual: a browser check of the class surfaces, fork-3).
- **CALENDAR/AGENDA — MOON DEDUP + AUTO-IMPORT + EVENT PROVENANCE (maintainer field report +
  rulings 2026-07-17; SHIPPED same day, frontend browser-unverified per fork-3/Q6a):**
  (1) **"Three moon states on one day" ROOT-CAUSED + FIXED:** `mapImportedToAgenda`/
  `mapDeducedToAgenda` filled `month`/`day` — the agenda's ANNUAL-RULE placement keys — from the
  instance's real date, so every imported dated VEVENT ALSO ghosted into EVERY displayed year
  (each year's moon phases drift ~11 days → contradictory states on one day; same defect
  projected movable feasts, e.g. a 2025 Easter, onto later years). Dated instances now place via
  `next_occurrence` ONLY (`month:null, day:null`); guard test in test_repo_invariants
  (`test_agenda_dated_instances_place_in_their_own_year_and_show_provenance`). A dated instance
  projected to another year is FABRICATION for anything movable — the rule going forward.
  (2) **`monkeyness-moons` (Moons-Seasons ICS) RETIRED as REDUNDANT** via a NEW
  `_REDUNDANT_DEFAULT_FEEDS` mechanism (distinct from the robots-dead set — this is a design
  call, not a robots verdict): the computed Meeus layer (full/new ch.49 + seasons ch.27, method +
  accuracy stated, almanac-verified) is the ONE astronomy authority; the feed duplicated it
  method-unstated over http. Already-imported ghosts are filtered at READ time in
  `load_imports` (solely-attributed events dropped, mixed-source events keep live providers;
  import_feed's next save persists the cleanup). KNOWN ACCEPTED LOSS: the feed's first/last
  QUARTER phases (the computed layer covers full/new only; computing quarters via the same
  verified ch.49 method is the clean follow-up if wanted).
  (3) **"Internet calendars should not be manually enabled" — VERIFIED ALREADY SHIPPED** (the
  staleness guard): `auto_import_due_feeds` has ridden every online collect pass DEFAULT-ON
  since the 2026-06-15 "auto-import everything" ruling (8 feeds/pass round-robin by
  least-recently-imported, 12 h per-feed gate incl. failure backoff, robots-dead hosts skipped)
  — no change needed; the Calendars panel's per-feed buttons are the manual OVERRIDE, not the
  path. (4) **EVENT-SOURCE CLARITY SHIPPED:** `agRow` now renders a visible "from <feed>"
  provenance pill on EVERY imported event — feed name(s) + URL(s) in the #oo-tip hover via a
  lazy directory map (`_agFeedById`, reuses the Calendars panel's `_feedDir`, one background
  loopback fetch fallback, family-name fallback meanwhile); curated events already carry
  `official_url`, deduced/computed events already state provenance/method. (5) **"Add as many
  online calendars as possible"** — the catalog already bundles ~498 feeds (~242 live after the
  dead-host filter); EXPANSION beyond it is a NETWORKED acquisition task (the law-batches
  pattern: parallel sessions verify ICS endpoints, never fabricated) — PENDING operator/next
  networked session.
- **LEMMATIZATION DEFAULT-ON — MAINTAINER RULED 2026-07-18 (the measure-gate is SATISFIED;
  brief of record =
  [`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEMMA_DEFAULT_ON.md`](docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEMMA_DEFAULT_ON.md);
  execution delegated to a CLI session, PENDING):** the maintainer ran `lemma_preview` on the
  live ~500k corpus (top 500 → 35 groups / 71 keywords) and REVIEWED the merges — clean
  (plurals + verb forms/irregulars; nothing meaning-changing; the media→medium class already
  denylisted). Per the recorded P3 correction, the IR-harness A/B was never the coherent gate
  for a DISPLAY-layer change — the precision review WAS, and it has now happened. So
  `OO_FAMILY_LEMMA` flips default "0"→"1" (opt-OUT stays; `_lemma_enabled` families.py:188).
  The brief's slices: S1 the flip + reframe the two default-pinning tests
  (test_repo_invariants.py:490 opt-in invariant → default-on/display-layer/reversible;
  test_families.py:185 off-by-default → on-by-default + opt-out-byte-identical) + docs sweep;
  S2 preview honesty upgrade (annotate groups ALREADY merged by the plural rule vs genuine
  lemma additions — most of the maintainer's 35 rows were plural-rule overlap, the true delta
  is verb forms/irregulars); S3 the deferred `conflated_by=["lemma"]` frontend indicator
  (conservative+flagged, Q6a); S4 `learn/learning` recorded as a WATCH (standalone "learning"
  ≈ machine-learning contexts) — NEVER pre-denylisted (evidence-grown only). Facts to keep:
  merges are per-language within `_LEMMA_LANGS` {en fr de es it pt nl ru id} — non-Latin
  script is NOT the barrier (ru works); zh/ja (unsegmented) + poorly-covered langs no-op
  honestly; core installs (no simplemma) no-op regardless of the default (the Core-only lane
  proves it); the trusted index is untouched (display layer only, invariant-pinned). The
  BM25F default choice stays SEPARATE (retrieval-side, still wants the graded gold set).
- **ENTITY FAMILIES AT REAL SCALE — FIELD EXPORT + SESSION BRIEF (maintainer 2026-07-18, the
  Insights→Families subtab on the live ~500k corpus; "I'd prefer everything to be automated. Or
  this should be moved into the settings"; brief of record =
  [`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_FAMILIES_ENTITIES.md`](docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_FAMILIES_ENTITIES.md);
  execution delegated to a CLI session, PENDING):** three problem classes, each anchored:
  (1) TOP-ENTITY NOISE — caps publishing furniture ranks top-5 (FOTO 4274 · VIDEO 4122 · LIVE ·
  INFO · PREMIUM · PDF · RSS) + pure Roman numerals (XIV/III): the 2026-06-16 acronym ruling's
  consciously-accepted "residual emphasis-acronym noise" is now iteration-due (this export IS the
  promised log); fix = an evidence-based caps-furniture batch in the acronym-DETECTION stoplist
  (collision-free by construction — lowercase content "foto"/"live" terms untouched) + a strict
  Roman-numeral exclusion WITH the LIV/DC/CD-class collision allowlist (skeptic-mandated).
  (2) CROSS-SCRIPT FRAGMENTATION — USA/США/ABD/EUA · FSB/ФСБ · NBA/НБА · NHL/НХЛ all separate
  top entities: families are per-language by design and rings cover lowercase concept terms only;
  fix = curated entity-alias ring seed NOW + a case-aware ring seam for UPPERCASE entity norms +
  the Wikidata generator extended to emit QID-sourced acronym aliases (wbgetentities already
  fetches them; the RUN stays the operator's networked step). (3) SURFACE DEFECTS — the kind
  dropdown's "all" returns TWO items (app.js:9078 loadFamilies fetches overall top-80 then
  filters kind!=="term" CLIENT-side = filter-after-limit; fix server-side non-term aggregation);
  people/orgs/places return silent EMPTIES (the extractor only ever assigns entity/term — the
  dropdown offers taxonomy the data doesn't have; options must tell the truth, never fabricate
  kinds); entity families are single-member BY CONSTRUCTION post-acronym-ruling so the "you
  decide" list offers nothing to decide + the "Trump = Trump's = Donald Trump" blurb describes
  the RETIRED model; clicking ✕ on a single member writes a useless override (the maintainer's
  two accidental `split: USA usa`/`split: ЦСКА цска` are theirs to delete via the existing
  control — never touched by a session). RULING: curation RELOCATES to Settings (content-first
  invariant #8, beside the Keywords explorer) showing only rows with a real decision; Insights
  keeps the data view; automation does the bulk (nothing manual required). Out of scope: real
  NER kind population (the LLM-perception track), §8 triage, lemmatization (own brief).
- **SUPER-GROUPS: HONEST STATS + A LEADS FAMILY + NAVIGATION — FIELD EXPORT + SESSION BRIEF
  (maintainer 2026-07-18, the Insights→Groups surface on the live ~500k corpus; ruled: super-group
  statistics ("is a theme rising?"), a Leads family for super-groups, keyword→super-group
  navigation; brief of record =
  [`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_SUPERGROUPS.md`](docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_SUPERGROUPS.md);
  execution delegated, PENDING — SEQUENCED AFTER the Leads-calibration + Families-entities
  executions, whose primitives it consumes):** the ~77-group scaffold is healthy but the layer has
  NO statistics, and the export exposed the totals as broken: (1) GENERIC CONTAMINATION — "data"
  = 36,507 of the AI group's 43,067 mentions (85%); creation/sentence/marketplace/identity same
  class; universe ring·68 at 16,393 = a probable homograph member inflating in one language →
  every stat carries a mandatory top-member DOMINANCE disclosure + the shared DF-ubiquity gate;
  (2) WITHIN-GROUP DOUBLE COUNTING — the AI group mixes legacy plain families
  (model/models/modèles/ia/données) with rings covering the same concepts (plain "ai 12" beside
  the ai ring 1,555) → member keyword-ids DEDUPED before any sum + the residue migrated (data
  fix, user-edit-wins honored); (3) cross-group overlap (data ×2, logic in Mathematics AND
  Philosophy) legitimate but DISCLOSED; (4) scaffold bugs — deficiency-in-Money (deficit
  conflation?), copyrighted→copyright, the diaspora* asterisk, zero-mention clutter → hand-
  verified per-case fixes + a config lint, never a sweep. THE BUILD: S1 stats core (dedup member
  resolution → windowed series/rate via the EXISTING rollup+trending grammar, dominance+overlap
  disclosures mandatory on every payload); S2 `supergroup_rising` producer born scale-aware (FDR
  across ~77 groups, count floors, share-normalized, one-member-driven rises disclosed,
  generic-driven rises NOT a Lead); S3 the keyword→super-group reverse lookup + chips in the
  analysis Keywords subtab + search (plural membership = multiple chips); S4 cleanup; S5 curation
  → the SAME Settings home the Families session builds (never a second home). Frontend
  conservative+flagged (Q6a).
  **AMENDED same day (maintainer rulings after the ring-country-map review — brief =
  [`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_GROUPS_LAYER_AMENDMENT.md`](docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_GROUPS_LAYER_AMENDMENT.md),
  same executing session):** (a) **NAMING RULED: keyword → GROUP → SUPER-GROUP** (user-facing,
  ×12; "ring" leaves the UI entirely, stays internal — the Lead-rename precedent; theme/concept
  was REJECTED: ambiguous containment + uneven translation; super-X-contains-X reads in every
  locale's morphology; fix today's collision where the "Groups" subtab shows super-groups;
  families stay invisible variant-collapsing, never a 4th tier). (b) **THE CIRCLE GRAMMAR:**
  uniform level marking app-wide — plain chip = keyword, ONE circle = group, TWO circles =
  super-group (the count encodes the level); + COLOR emphasis via two theme-DERIVED variables
  (color-mix from theme tokens, NEVER hardcoded hues — the #23 caveat-color lesson: verify
  contrast by math across all 17 themes), color reinforcing-only (circle count + hover + aria
  stay primary); a clickable path breadcrumb (⦾⦾ ▸ ⦾ ▸ word) wherever any level appears.
  (c) **GROUP-level statistics** share the S1 resolution primitive one level down, with the
  disclosure adapted: top-LANGUAGE dominance ("ru carries 61% of this group"); the rising-card
  family stays super-group-only (540 groups ≠ a reviewable card population). (d) **THE CONCEPT
  MAP upgraded** (the surface the maintainer praised; queries.py:528 ring_country_split +
  /ring-countries): the 540-item dropdown → a two-tier circled browse (⦾⦾ chips → ⦾ chips +
  type-ahead); COUNTRIES BECOME CLICKABLE (member keyword-ids ∩ source country → exact ids →
  openAnalysisForIds; the "not mapped" bucket clickable too — 717 articles in the export, the
  largest bucket); every ⦾ chip app-wide deep-links to the map; the located-share honesty line
  states that map coverage grows as source countries are filled (the ~49% unlocated share = the
  standing Wikidata source-country generator lever, operator-side).
- **LEADS/CARD-SYSTEM CALIBRATION AT REAL SCALE — FIELD EXPORT + SESSION BRIEF (maintainer
  2026-07-18, a Home-Leads dump from the live ~500k-article corpus, "it clearly shows the card
  system's current limitations"; brief of record =
  [`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEADS_CALIBRATION.md`](docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEADS_CALIBRATION.md)):**
  VERDICT (assessment delivered + maintainer approved the brief): the HONESTY layer held, the
  SELECTION layer broke — producers were calibrated at ~2k articles; at 500k the base rates
  invert. SEVEN defect families, each anchored + exampled from the export (the brief's §0 table
  = the acceptance cases): (1) BOILERPLATE BLINDNESS — laundering "origins" policies.google.com
  (fired TWICE)/addtoany.com/creativecommons.org (the discovery `is_infrastructure_domain`
  filter EXISTS at channels.py:108 but laundering.py:45 only checks social+commerce); flooded
  topics "vir"(=Slovenian "source")/"lani"(="last year") = publishing furniture; propagation
  "topics" data/media/social = the #530 generic-term problem (the detector proposes, producers
  don't consume). (2) STATISTICAL ARTIFACTS — supply_chain_ripple resolves commodity LEAD to the
  English word "lead" ("significant words of the label", :110) over RAW daily-count series →
  total-volume confound: everything co-moves at r=.98 (fix = exact-label/symbol match + SHARE
  normalization); flooded z=5.85 on THREE articles (count floor needed). (3) LANGUAGE BLINDNESS
  — headline_body lexical_div=1.0 guaranteed on inflected languages (Estonian); ownership_change
  English verb regex (:1033) matching Romanian election text → per-language capability gates
  (the S5.2 script-guard precedent). (4) SCALE-BLIND THRESHOLDS — single-source is the NORM at
  500k (3× GIGAZINE lonely cards); country-level convergence on Iran/US = base rate; diet "leans
  on a few sources" at top-3=14% of 2117. (5) NO CROSS-CARD DEDUP — same origin twice;
  Allemagne+Deutschland two weather cards for DE (surface-string keys, not country codes);
  "Usa" casing. (6) JUNK MEMBERS — homepage/section captures as cluster evidence
  (non_article_scan exists count-only, not consumed). (7) INTERNAL CHANNELS + NULLS — the .eml
  import flagged "capacity implausible" (exempt non-web provenance classes); price_narrative
  cards at p=0.72 (a null is never a Lead; stays in exploration). THE BRIEF: S1 shared noise
  substrate (wire is_infrastructure + DF-ubiquity gate + provenance exemptions + non-article
  member exclusion, every exclusion DISCLOSED in the method string) → S2 statistical hygiene →
  S3 language gates → S4 scale-relative selection (incl. place canonicalization by country
  code + suppress the self-re-counting severity meta-card) → S5 cross-card dedup + WIRE the
  shipped-but-unwired leads.py core (sort_leads/is_major/cluster_by_article_ids — visibly
  reorders Home, conservative+flagged per Q6a, the export IS the mandate) → S6 the measurement
  loop (a `leads_quality` JSONL diagnostic riding the all-diagnostics bundle + every §0 row
  pinned as a fixture test, negative-space both directions). Selection discipline applies to
  LEAD SLOTS only — nothing deleted from exploration; anti-capping + cross-time recall stand.
  WORKED (don't regress): law-change, through-time, recycled framing, weather concept, and the
  method disclosures that made the dump diagnosable. PENDING: the brief's execution (CLI session).
  **AMENDED same day (maintainer field export of Insights→Convergence, default 7-day window, on
  the same ~500k corpus — "Plenty of bugs and optimizations to do"; amendment brief =
  [`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_CONVERGENCE_AMENDMENT.md`](docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-07-18_CONVERGENCE_AMENDMENT.md),
  executed by the SAME Leads-calibration session — it shares the S4.2 place-canonicalization
  primitive):** **NEW RULING (maintainer, verbatim intent "I don't like cap counts, I'd prefer
  having real, reliable data"): REAL, RELIABLE DATA — NEVER CAPPED FIGURES.** A cap may bound
  which EXAMPLES are listed; it must never bound a displayed NUMBER (extends the standing
  anti-capping doctrine from computation to display). The export's smoking gun: EVERY cluster
  showed "⚠ 50 shared-origin links" because `_shared_origin` (`src/analytics/convergence.py:335`)
  runs `.limit(50)` then returns `len(rows)` — the display cap IS the reported count; fix = an
  exact COUNT aggregate over the HAVING-filtered subquery (no limit; examples keep a small fetch
  bound) + a sweep for any other displayed figure that is secretly a cap (C1, do-first). The
  rest of the amendment: (C2) "United States"/"America"/"Usa" as three separate cluster families
  → country-code canonicalization via the SHARED S4.2 primitive (city-level stays distinct);
  (C3) sliding-window fragmentation (Iran ×3 contiguous windows, Washington/New York/France/China
  ×2) → ONE span entry per canonical place (full extent + peak window + per-step drill); (C4)
  8,448 clusters ordered scale-blind → baseline-relative ORDERING (deviation from the place's own
  baseline share) — reorder NEVER gate, full-recall exploration stands; (C5) display honesty
  (source-COUNTRY spread instead of the alphabetical source prefix; word-boundary truncation; an
  "includes future-dated mentions" label on future-extending windows — legitimate deduced dates
  that otherwise read as an error). The producer cards inherit every shared fix; execution
  PENDING with the parent brief.
- **THE OBSERVATORY — THE CORPUS AS A NIGHT SKY, A DEDICATED TAB (maintainer ruled 2026-07-18 —
  SUPERSEDES Q5a (2026-07-13), which had deprioritized the 3D keyword explorer; revives the
  2026-06-16 flagship under its own resolution A (hand-rolled canvas 2.5D, NO WebGL/Three.js);
  design of record = [`docs/design/OBSERVATORY_DESIGN.md`](docs/design/OBSERVATORY_DESIGN.md);
  DESIGN-ONLY — build NOT started, browser-verify-GATED):** the keyword hierarchy rendered as a
  deterministic night sky: universe=corpus · galaxy clusters=the scaffold's ~12 domains (needs an
  additive `domain:` field in keyword_supergroups.yml — today the domains live only in a comment)
  · galaxies=super-groups (77) · star systems=rings (~540) · stars=keyword families ·
  planets=per-language ring members (the project's rings render as LITERAL planetary rings,
  segmented by language share) · nebula=the un-curated long tail as DISCLOSED aggregate density
  ("N stars shown · M in the nebula" — the anti-capping answer). RULED: a DEDICATED main tab
  beside the others, whole-corpus v1; name **Observatory** (translates well ×12; "Telescope"
  reserved for the later per-corpus instrument inside the analysis window — not v1); spiral ARMS
  carry the Item-AC topic tags — cardinality guarded BY CONSTRUCTION (top-K≤6 arms by member
  count + a labeled "untagged/other (N)" disc; today's taxonomy is only 8 topic tags, so the
  fear is growth and the cap answers it). HONESTY SPINE: a self-similar POLAR grammar —
  ANGLE=category (domain wedge at the universe tier, tag arm at the galaxy tier; within-sector
  jitter = stable hash, disclosed as meaningless) + RADIUS=ONE measure (default article spread —
  breadth resists single-source flooding; log scale with LABELED orbit gridlines per #16 / the
  opts.logY precedent; switchable dimension picker à la ooMap) — NEVER an "importance" blend;
  size=mentions (sqrt + a reference-star legend); colour=language default, or
  temperature=windowed trend as a CHOSEN lens (red = a measured decline with method stated;
  old-but-steady stays white — cross-time sacred); association = DRAWN constellation edges (PMI,
  n shown), never proximity; novae = trending spikes under the supergroup_rising gates
  (floors+FDR); deterministic layout → a stable "your sky" where CHANGE is signal. Canvas-2D
  glow sprites + parallax; depth NAVIGATIONAL only + screen-space marks (perspective never
  distorts magnitude); STATIC when idle (no animation loops); LOD rides the hierarchy (≤~5k
  sprites + nebula); sr-list + keyboard, the tabular views stay canonical (#8). ONE new endpoint
  (`GET /api/insights/observatory`, tiered payload, guarded+deadlined, no score-named fields).
  PREREQS before build: the super-groups S1 stats core (the Observatory is its 2nd consumer) +
  the §8 triage / caps-furniture sky-quality cleanups. The maintainer click-through is the ship
  gate for every frontend slice (this surface is NOT conservative-flaggable).
- **VERSION SEQUENCE RULED 2026-07-18 (maintainer, verbatim "I'll run the P0, then mark alpha
  0.2, then move to alpha 0.3"): P0 live validation → TAG `v0.2.0` → FLIP to `0.3.0`.** This
  closes the long-held 0.2 tag gate the honest way (the tag = the release the whole 0.2 cycle
  was defined by) and approves the V1_PATHWAY §3 version train's 0.3 step ("measured &
  verified" — partially resolves open ruling V1-1 for 0.3; later steps still per that plan).
  ORDERING IS MECHANICAL, not just procedural: `release.yml` verifies tag == pyproject
  version, so the `v0.2.0` tag MUST be cut while pyproject still reads 0.2.0, and the flip PR
  merges ONLY AFTER the tag exists (if the P0 run FAILS, the flip does not merge — the cycle
  is not closeable on a failed validation; never a fabricated pass). THE FLIP PR (prepared
  same day, HELD as a draft until the tag): pyproject `0.2.0→0.3.0` + README header/version-
  note/status blocks + CHANGES header + a new 0.3.0 in-progress section + the 0.2.0 section's
  tag line + CONTRIBUTING ladder/table + ROADMAP §version/P0-statuses/lemma-ruling row + this
  ledger's current-cycle bullet — all prose written for the POST-tag state (true at merge
  time). Simpler than the 0.1→0.2 flip: NO branch rename (the `main` rename is permanent;
  branch and version are independent). The 0.3 cycle contents = the CHANGES 0.3.0 board (the
  loop v1 · the six 2026-07-18 delegated executions · the law vertical · the browser
  burn-down · the Observatory chain). NOTE for the tag-day checklist: the tagged 0.2.0 tree's
  own CHANGES still carries the pre-tag "tag is gated" wording (the amendment rides this flip
  PR, which lands after the tag) — cosmetic, recorded here so it never reads as an oversight.
  **P0 RESULT (maintainer ran the job 2026-07-18/19): 5 pass · 0 fail · 0 not-measurable-here**
  — P0.1 backup bounded-RAM (peak RSS +440 MB over a 2522 MB corpus) · P0.1 verify (manifest
  signature + every volume checksum) · P0.2 staged restore + dry-run merge preview (live corpus
  read-only) · P0.4 unlock 602 ms (bar 2000 ms) · P0.3 collector RSS +166 MB across 2 passes
  (floor 512 MB); the report's own follow-ups carried forward: confirm unlock at full scale
  with a COLD boot on the complete corpus + confirm the collector over a multi-day live soak.
  TAG MECHANICS FACT (learned 2026-07-19): the session git proxy REFUSES tag pushes (HTTP 403
  — branch refs only; this is also why v0.1.0 was never tagged from a session), so the tag is
  cut from the MAINTAINER'S machine: `git fetch origin main && git tag -a v0.2.0 5b5452c15 &&
  git push origin v0.2.0` — tag the WATCHED-GREEN SHA `5b5452c15` (blocking test lane + every
  required gate green; only the NON-blocking Windows observation lane was still running, the
  known #701 hung-runner pattern). Push the TAG ONLY (never create the release via the GitHub
  UI — release.yml's own `gh release create` would then collide); release.yml re-runs the full
  suite, verifies tag==pyproject(0.2.0), builds sdist+wheel+SHA256SUMS and publishes.
  **THE COLLISION HAPPENED ANYWAY at v0.2.0 (2026-07-19):** the maintainer had created the
  release via the UI (with the tag; pre-release ticked) — the workflow's suite/verify/build all
  passed but `gh release create` failed instantly on the existing release, which shipped with
  NO artifacts. FIXED FORWARD: the publish step is now IDEMPOTENT (release exists → `gh release
  upload --clobber` the artifacts + append the checksums to the notes only if missing, the
  maintainer's notes/pre-release flag left alone; else create, with `--prerelease` AUTO for 0.x
  tags per the maturity ladder). CAVEAT for the v0.2.0 recovery: a RE-RUN of an existing run
  uses the workflow AT THE TAG'S COMMIT (the old non-idempotent step), so the v0.2.0 unblock =
  maintainer deletes the asset-less release (KEEP the tag) → re-run the failed job → re-tick
  pre-release / re-edit notes; the idempotent step protects v0.3.0+.
- **RING LIFECYCLE — LONG-TERM EVOLUTION STRATEGY (maintainer-agreed 2026-07-20; design note,
  builds PENDING):** answers the maintainer's long-view question ("once the ~2000-ring target is
  reached, how does the selection evolve as the corpus grows? new words keep being invented — the
  strategy needs a very long term view"). GROUNDING recorded so the reasoning survives: (a) rings
  LAG, never GATE — keywords are captured uncapped instantly (the ChatGPT-2020 ruling), so an
  unringed new concept costs only cross-language MERGE-lag, never capture; (b) the sensor/alarm
  loop already exists — the `ring_candidates` gap digest recomputes from the LIVE corpus each
  diagnostics export, and `translation_coverage` (engine report) DECAYS measurably as vocabulary
  drifts; (c) Wikidata is the living external registry (prominent new concepts get QIDs within
  days; QIDs stay stable under renames/alias drift); (d) mass-importing Wikidata stays REJECTED
  (~115M items of wrong shape; the in-RAM `(lang,term)→ring` index on the 2-core reference VM;
  unvetted merges at scale = fabricated merges via silent last-writer-wins — SELECTION/VETTING is
  what makes rings the reliable trans-language layer, per the maintainer's own framing). THE TWO
  AGREED MECHANISMS (pending builds): (1) **INSTITUTIONALIZED REFRESH CADENCE** — the gap-digest →
  `--from-log` generate → vet → merge pass becomes a NAMED per-cycle ritual, and
  `translation_coverage` joins the KPI board (V1_PATHWAY K-metrics) so coverage decay is SEEN, not
  discovered. (2) **QID-REFRESH PASS** (small new tooling) — a `--refresh` mode for
  `generate_wikidata_rings.py`: re-run `wbgetentities` over the ALREADY-VETTED QIDs in the
  generated file, DIFF member lists, emit ONLY the additions for review — absorbs WITHIN-concept
  alias/rename drift (the coronavirus→COVID-19 class) at low vetting cost since the QID judgment
  was made once; propose→review→merge, never auto-apply. HONEST LIMITS stated: detection keys on
  article SPREAD, so it inherits scraping breadth (a concept prominent only in an under-scraped
  language surfaces late — a coverage problem mitigated by source-diversification/
  language-equilibrium, not a ring problem); the ~2000 target is a VETTING-CAPACITY horizon, not a
  wall (rings are NEVER pruned — cross-time recall sacred, a dead concept's ring keeps serving
  history; the §8 LLM-triage propose→verify→merge chain can raise review throughput and move the
  horizon). IN-FLIGHT CONTEXT (operator steps pending): a 168-seed thin-supergroup ring batch is
  PREPARED and awaiting a machine with BOTH live Wikidata access AND write access — seeds file +
  prevetting CSV (11 CONFLICT-MANUAL-PIN war seeds, 10 HOMOGRAPH-WATCH, 4 OVERLAP-EXISTING-RING) +
  runbook + ledger templates delivered by a read-only networked session 2026-07-20 and
  hand-verified against the tree this session. TWO EMPIRICAL FACTS from that verification,
  recorded BEFORE the batch ships so they cannot be relearned the hard way: (i)
  `generate_wikidata_rings.py` OVERWRITES its `-o` target with only the current run's rings
  (emit-only, no merge — despite its docstring's "augments"; default `-o` IS the live
  `configs/keyword_rings_generated.yml`, so a naive `--seeds` run would WIPE the 540 vetted
  rings) — always resolve to a temp file and append-merge, per the runbook; (ii) `nuclear fusion`
  is a KNOWN REPEAT OFFENDER seed (already resolved wrong + dropped in the 2026-06-20 vetting;
  it sits in `test_wikidata_ring_gen.py`'s dropped-id guard). Batch overlap decisions
  recommended (vetter's call at run time): seed `right of asylum` not bare `asylum`
  (psychiatric-hospital already carries `en:asylum`); keep `secularism` as its own ring (a
  distinct concept from irreligion, which carries it as an alias); DROP `public relations`
  (marketing already carries `en:PR` + `en:public relations`); keep `pension` but strip
  `de:Pension` from the resolved members (bound to guest-house — a cross-language homograph).
- **SOURCE-MANAGEMENT ASKS — newsletter links · qualification funnel · language detection
  (maintainer asked 2026-07-20; INVESTIGATED same session, code-verified; builds PENDING —
  assessment-first, nothing built this turn):** three asks, each checked against the tree
  (staleness guard) before answering.
  (1) **NEWSLETTER LINKS → NEW SOURCES: NOT the case today — a real, well-bounded gap.** The
  .eml/mailbox ingest de-tracks links in the BODY (`privacy/link_sanitizer.sanitize_text`) but
  writes NO `ArticleLink` rows — only the web ingest paths do (`src/ingest/pipeline.py:317`,
  `src/ingest/batch.py:398`) — and BOTH source funnels read exclusively `article_links`: the
  per-pass citation discovery channel (`src/discovery/channels.py:190`) and the manual
  `promote_cited_sources` endpoint (`src/api/source_management.py:207`; DISABLED `cited` rows,
  ≥2-DISTINCT-citing-sources gate, commerce/social/infrastructure filters, alias-aware dedup).
  BUILD SHAPE (the ruled intent — cleaned newsletter links must be able to become sources):
  extract the SANITIZED external links at .eml ingest into `ArticleLink` rows — ONLY
  fully-recovered destinations (a tracker-wrapped link whose destination could not be recovered
  stores wrapper-domain-only by design and must NEVER seed a source); both funnels then pick
  newsletters up with ZERO further change, and the ≥2-distinct-citers gate + noise filters are
  the right protection against sponsor/self-promo link noise.
  (2) **SOURCE QUALIFICATION (~20k sources on a 3-day-old install; "unqualify mis-gathered
  links"):** the machinery largely EXISTS; the missing piece is the ORCHESTRATION, which is the
  already-parked Phase-2 promotion frontier — this ask REINFORCES that parked build. Mapping:
  robots check = the bounded preflight; "scrape a few articles + compare statistically vs the
  same-language corpus average" = the #663 `source_audit` auditor (cohort-relative per-language
  baselines; short-article rate · outlier keyword stats · furniture share · extraction-failure
  pathology with an ABSOLUTE floor; flag-only, auto-demote built but DEFAULT-OFF per Q2a;
  diversity guardrail); the qualification LIFECYCLE = candidate → TRIAL (consented few-article
  scrape, gated on the auditor) → graduate/reject + audit view + undo (Q3a). GENUINELY NEW
  signals to add when built: per-source PARAGRAPH/SENTENCE average word counts (style-ambiguous
  → WATCH-only per the extraction-validity reframe, never auto-demote) + the function-word
  prose-ness measure from (3). PERSPECTIVE recorded: most of the ~20k are DISABLED
  discovery/cited candidates — inert metadata, never fetched; the pain is review-funnel absence,
  not scraping exposure.
  (3) **LANGUAGE DETECTION ("almost half the corpus has no language tag"): the engine ALREADY
  EXISTS in three tiers — do NOT rebuild it.** Tier 1: py3langid at ingest
  (`store._resolve_known_language` persists `Article.detected_language`; gated ≥200 chars +
  ≥0.90 confidence + supported-language-only; `[analysis]` extra). Tier 2: the
  `reconcile_article_language` backfill (text-detect → keyword-majority) wired into the
  re-index job's cleanup pass. Tier 3: the opt-in LLM residue detector (B15,
  `/api/ai/detect-language`). The proposed top-100-words/top-24-overlap detector would be a
  WEAKER duplicate of tier 1 (py3langid = a trained offline model over the same evidence class)
  — not built. THE ACTIONABLE GAP is operational + visibility: (a) the untagged half is most
  likely pre-hook articles + HONEST refusals (short/junk text — the very mis-scrapes flagged in
  the same message); running the re-index cleanup ("Clean up keywords") backfills the backlog;
  (b) add a small diagnostic surfacing language-coverage tallies (asserted vs deduced vs
  unknown, with refusal reasons) so the dominant case is SEEN before more is built. **THE
  KEEPER IDEA — FUNCTION-WORD DENSITY AS A PROSE-NESS / MIS-SCRAPE SIGNAL (genuinely new):**
  share of tokens that are function words of the best-matching language — the vendored
  stopwords-iso lists already provide vetted function-word sets ×18 languages (no corpus
  extraction step needed); real prose in ANY supported language scores high, title-lists/
  product-pages/nav-junk score near zero in EVERY language → add as an extraction-validity
  criterion in `source_audit` + the non-article scan, feeding (2)'s qualification gate. Each
  item is a next-session slice.
  **AMENDED same day (maintainer RULED the qualification lifecycle — answers/supersedes parts
  of the parked Phase-2 design):** (a) **QUALIFICATION IS THE ADMISSION GATE — only QUALIFIED
  sources are scraped**: after a restore/import (and any discovery registration), every
  not-previously-qualified source gets the qualification pass BEFORE joining regular
  collection. (b) the verdict is PERSISTED + STAMPED — "qualified by Open Omniscience on
  DATE" (additive `Source` columns: status unqualified|qualified|disqualified + qualified_at
  + the criteria VERSION it was judged by; the stamp states WHAT was checked — extraction
  validity — never a quality score). (c) qualification runs as a BACKGROUND,
  task-manager-visible job, parallel to other tasks (a NETWORK job kind — trial fetches ride
  the standing online-consent envelope like the world-discovery ride-along; never under
  airplane). (d) DISQUALIFIED/unqualified sources are KEPT, never deleted — a re-import or a
  fresh citation of a disqualified domain (a mis-interpreted marketplace, a video blog) must
  never re-register or re-trial it (the existing alias-aware dedup gives never-re-CREATE for
  free as long as rows persist; ADD: the citation/discovery funnels must SKIP
  disqualified-status domains rather than re-propose them). SUPERSESSION noted: Q3a's "trial
  auto-enable DEFAULT-OFF" posture is AMENDED — qualification is automatic-by-default within
  the online consent envelope (the trial IS the admission path, not an opt-in extra); Q2a's
  flag-only stance evolves into this gate for NEW sources (retroactive DISqualification of
  already-scraped sources stays evidence-first/reviewed, per the auditor's reframe). DESIGN
  NOTES for the build: COLD START — the statistical comparison needs a same-language corpus
  baseline, so on a fresh/small corpus the auditor's honest small-cohort behaviour applies
  (soft criteria unflaggable → qualification initially decides on the hard extraction-
  validity floor only, firming as the corpus grows); **SUB-DECISION RESOLVED same day
  (maintainer): ALL sources are qualified BY DEFINITION — the curated catalog INCLUDED; NO
  pre-qualified-by-curation stamp.** The first collect pass over the catalog IS its
  qualification pass (trial articles are kept — no wasted fetch). COROLLARY (maintainer):
  the preliminary/release tests must verify the INITIAL LIST PASSES qualification — a
  catalog source failing it is a CATALOG-REVIEW signal (fix the seed list, never
  grandfather it). FRAMING recorded: the initial list is a SEED that grows the corpus
  outwards (citations/newsletters/discovery extend it; qualification is the membrane every
  entrant — the seed included — passes through); RECONCILIATION with cover-everything —
  qualification gates on
  EXTRACTION VALIDITY (is this a content source at all), never editorial merit, so it
  removes mis-gathered noise without violating "ordering ≠ exclusion"; disqualification
  REASONS persist per source (transparency + undo, per the Phase-2 audit-view design).
  **RE-QUALIFICATION RULED same day (maintainer: disqualified sources get a SECOND CHANCE —
  re-qualify every 1 to 6 months, exact interval EXPLICITLY UNDECIDED — "maybe it was bad
  luck, maybe they changed their website, or maybe not"):** the clock is the ONLY re-trigger
  — this COMPOSES with (d) above, it does not contradict it: event-driven re-checks
  (re-import, fresh citation) stay suppressed; only elapsed time re-opens a disqualified
  source. Mechanics for the build: the background qualification job also picks up
  disqualified sources whose last attempt is older than the interval (bounded per pass, like
  `world_discovery_per_pass`, so a backlog never swamps a pass); every attempt is RECORDED
  (date + verdict + criteria version — attempts append, never overwrite, per the vintage
  convention), surfaced in the audit view. INTERVAL RECOMMENDATION (proposed, not ruled —
  resolves the undecided 1-vs-6 by using the WHOLE stated range as a ladder): a per-source
  BACKOFF — first re-check at 1 month, doubling toward the 6-month cap on each repeated
  disqualification (1→2→4→6 capped), reset on success — the source-level analog of the
  shipped capped feed-backoff (finding F: "the cap guarantees re-check; never exclusion");
  a changed/fixed site gets caught within a month, a persistently-junk domain costs ~2
  checks/year. A Settings knob (bounded ~30–180 days) stays available to override; the
  ladder is the default unless the maintainer rules otherwise.
- **LLM SOURCE-TAG ASSIGNMENT FROM TOP KEYWORDS (maintainer proposed 2026-07-20: "a source
  tag assignment strategy based on their top 200 keywords, given to the local LLM in the
  diagnostic tab"; DESIGN RECORDED, build PENDING — reuses the §8 triage chassis):** the
  motivation is real — ~17k discovered/cited sources carry NO topical tags, and tags drive
  the stratified collection interleave (untagged sources pool in the "·untagged" bucket),
  the wizard themes, and every tag filter. THE SHAPE (= the ruled §8 LLM-triage pattern with
  a different task; reuse `src/ai_layer/triage.py`'s conventions wholesale): per-source
  top-N TERMS (post-stoplist, via the denormalised `KeywordMention.source_id` — a covering
  scan, no codec join) → batched to loopback Ollama → the model picks from the EXISTING
  CLOSED tag vocabulary only (the catalog taxonomy the wizard already reads — closed-set
  classification is what small local models do reliably, and it stops taxonomy
  fragmentation; an out-of-vocabulary answer is REJECTED, never stored), echo-back
  validation + canaries (hand-known obvious sources — a sports outlet — detect model
  degradation) + timing telemetry, run as a visible abortable job from the Diagnostics
  panel. HONESTY RAILS: (a) the TWO-CLASS model applies to tags — LLM-proposed tags are
  DEDUCED, stored in a separate labeled channel (the `detected_language` precedent), NEVER
  silently overwriting the catalog's ASSERTED `Source.tags`; consumers (interleave/filters)
  may read asserted-else-deduced, disclosed; (b) EVIDENCE FLOOR — a source below a minimum
  article/mention count gets an honest SKIP ("insufficient evidence"), never a guess from 3
  articles (the auditor-floor convention; a garbage/unvalidatable model answer stores
  NOTHING, per B15); (c) input quality gates first — junk keywords (the nav-soup entities)
  poison the evidence, so the prose gate + §8 triage cleanup upstream materially improve
  this feature's inputs; (d) start EXPORT-ONLY (the §8 posture) with an apply-reviewed-batch
  step; auto-apply into the deduced channel only once the maintainer has eyeballed a real
  batch. SYNERGY: depends on the airplane/Ollama fix above — tag assignment is loopback
  inference and must work offline once that gate is split.
  **GO RULED same day (maintainer: run the §8 triage AND the source-tag assignment on the
  local Ollama rig, export logs, "I currently don't trust enough small models. You should
  verify it." — the ruled ai-proposed→claude-verified→maintainer-merged chain is now
  OPERATIONAL POLICY):** investigation found NEITHER run is one-click today —
  `run_triage_batch`'s ONLY caller is the selftest (`triage.py:704`; the sole endpoint is
  `/keyword-triage-selftest`), so the REAL-run wiring (job + endpoints + panel button) is a
  build; the tag half is design-only (the entry above). BOTH are one CLI build session:
  brief of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-20_LLM_TRIAGE_TAG_RUNS.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-20_LLM_TRIAGE_TAG_RUNS.md)
  (S1 wire the triage run · S2 the tag run on the same chassis · §4 the VERIFICATION
  CONTRACT: what the JSONL must carry + the Claude-side protocol — canary integrity, a
  stratified re-judgement sample weighted TOWARD non-English, rejection/timing sanity, the
  deterministic artifact built only from surviving verdicts as a draft PR). Execution
  PENDING; the maintainer's log upload then triggers the verification session.
- **POST-IMPORT RESULTS SCREEN — the unlabeled row-sum headline + the dedicated delta view
  (maintainer field report 2026-07-20, after merging a 10 GB corpus: "4,855,433 imported …
  frankly too vague… I'm sure it doesn't contain 5 million articles"; ROOT-CAUSED same turn,
  redesign PENDING):** the maintainer's read is CORRECT — `_renderImportSummary`
  (`src/static/app.js:5875`, the 2026-07-02 "clear view of what was imported" iteration)
  sums `c.new`/`c.duplicate`/`c.conflict` across EVERY table of the merge plan (:5883-5885),
  so the headline mixes articles with keyword-mention/link/entity/date/custody ROWS under
  the single unlabeled word "imported" — an every-number-carries-its-method violation (a
  row-sum reads as an article count; mentions dominate it by an order of magnitude). The
  per-table truth already exists but is buried in the collapsed "Details by source"
  `_v2PlanTable`s. THE REDESIGN (ruled): a DEDICATED post-import results screen — (1)
  HEADLINE in the user's unit: ARTICLES imported/deduplicated first, then a LABELED
  per-type breakdown (sources · keywords · mentions · links · law docs · wiki pages ·
  events · analyses — each its own labeled count; the cross-table row-sum may remain ONLY
  labeled "database records, all types"); (2) **THE CORPUS-DELTA VIEW ("how the corpus got
  improved")**: before→after per dimension — articles, sources, languages present,
  countries covered, date-range span, distinct keywords — computed by snapshotting the
  cheap maintained counters BEFORE the merge and diffing after (never a whole-table scan
  post-merge; the counters + `Source` counts make this near-free); (3) **WORK INDUCED**:
  the import's follow-up queue stated honestly — N newly-imported sources awaiting
  QUALIFICATION (first-class via the same-day qualification-status rulings), unindexed
  articles if indexing lags, discovery candidates added; (4) POSITIVE-BUT-HONEST framing
  (ruled: "imports should give positive feedback") — "your corpus grew by X articles from
  Y new sources spanning Z new languages" is both celebratory AND every-number-real; no
  fabricated praise, the delta IS the good news. Numbers via the shared formatter +
  `OOI18N.tf` templates ×12. Frontend browser-gated per Q6a; the delta snapshot is the
  small backend piece.
- **THE 0.3 CLOSE GATE (maintainer RULED 2026-07-20 — the conditions for tagging v0.3.0;
  the analog of the P0 validation that closed 0.2; rows 6–8 + the row-1/row-4 amendments
  added same day):** the version already reads 0.3.0 (the 2026-07-18 sequence: P0 pass →
  v0.2.0 tag → flip), so this gate governs CLOSING the 0.3 cycle. EIGHT gate rows, all
  required before the tag: (1) **the entire 2026-07-20
  source-management program implemented AND DOUBLE-CHECKED** — the qualification lifecycle
  (admission gate · stamp · background job · re-qualification ladder) · newsletter
  links→sources · the airplane/Ollama gate split · source-IP surfacing · discovery trail
  + citations tally/drills + corpus filters · the nav-soup prose gate · the post-import
  delta screen · the LLM triage/tag runs with the Claude-verification chain — each build
  verified per the house gates AND field-confirmed, not merely merged (merged ≠ green ≠
  verified). **ROW-1 AMENDMENT 2026-07-24 (a concrete instance of this row's own
  "merged ≠ verified" warning, found by a field report — the maintainer runs 8 parallel
  instances for download throughput and merges their backups into one corpus): the
  qualification lifecycle shipped correct in isolation but did NOT survive a restore.**
  `_merge_sources`' explicit column allowlist omitted the three stamp columns, and
  `source_qualification_attempts` had no merge handler at all — so every merged-in source
  landed `unqualified` (the column's own `server_default`, hence invisible: a plausible
  legal value, never a NULL or an error) and its whole attempt history was dropped.
  Because `select_unqualified` matches exactly `status=='unqualified'`, a DISQUALIFIED
  source arrived indistinguishable from never-judged, so a merge LAUNDERED known-bad
  sources back into the trial queue with the backoff ladder reset. FIXED same day (see the
  shipped.csv row); the export side was verified already complete and unchanged. THE ROW-1
  IMPLICATION worth keeping: "the qualification lifecycle is implemented" was true and
  still left this hole, because the lifecycle was never exercised ACROSS a
  backup/restore — so this row's field-confirmation clause should be read as covering the
  lifecycle's interaction with import/export, not only its behaviour on one instance.
  Row 4 (the full import that re-checks all sources) is the natural place that gets
  demonstrated at scale. "double-checked" INCLUDES docs↔app reciprocity — USER_MANUAL chapters for
  qualification / source management / the post-import screen (**SHIPPED 2026-07-25,
  transversal audit 09 fix-forward** — see §3.3/§3.9 of `docs/USER_MANUAL.md`; the standing
  reciprocity rule applies to everything else this row builds too). **RECONCILED
  2026-07-25 (transversal audit 09, §8/Action-Plan-D-7 — the audit found this row's own
  "implemented" language silently swallowing an item its OWN sibling ledger entry (below,
  "SOURCE IPs") already called design-only): the Tor-exit-resolve (SOCKS RESOLVE / 0xF0)
  path is EXPLICITLY OUT of this row's "implemented" bar — it is
  MAINTAINER-RULING-GATED, ASSESSED but zero code built, awaiting the "go" the SOURCE IPs
  entry's own text names ("design of record pending the go"). Row 1 does NOT require it;
  closing row 1 does not wait on it.**
  (2) **a fully TRANSVERSAL AUDIT of the entire repo** (the `07_TRANSVERSAL_AUDIT_V01` precedent — a new tool-by-tool edition for
  0.3). (3) **full diagnostics taken from the REAL corpus at its ACTUAL release scale
  (~1 MILLION articles) — the 5-MILLION bar is WITHDRAWN for 0.3 (maintainer ruled
  2026-07-30: "we won't be able to achieve the 5 million mark for the next release due to
  the overall app speed. We should be content with what we already have (roughly one
  million, waiting for the full imports that take very long)").** The bar was never about
  the number itself — it was REAL FIELD DATA at whatever scale the app genuinely reaches
  (the P0-live-run-not-synthetic precedent), and ~1M on the live corpus satisfies that.
  WHAT THIS COSTS, stated rather than glossed: any finding from this run is evidence AT ~1M
  and must be reported as such — a 0.3 gate row must never carry language implying a 5M bar
  it did not test (the standing "a verdict must map to the bar it actually tested" lesson).
  Behaviour that only appears an order of magnitude higher stays UNMEASURED for 0.3, and the
  5M bar returns as a LATER-cycle target once the throughput work makes it reachable (the
  2026-07-24 SCRAPING_10X_SCALING_STRATEGIES doc + the C-slice brief are exactly that work —
  the app's speed is the reason this bar moved, so the bar moves back when the speed does). (4) **a FULL IMPORT of the database that RE-CHECKS
  ALL SOURCES** — the ruled qualification-at-import admission gate demonstrated at full
  scale (every source through the pass, verdicts stamped — the curated catalog INCLUDED,
  no grandfathering per the same-day seed ruling; catalog failures = catalog-review work
  items) before the switch; this row
  EXPLICITLY doubles as the backup/restore-AT-SCALE validation — RESTATED 2026-07-30 with
  row 3's withdrawn 5M bar: at ~1M articles this is a restore at roughly 2× the P0-validated
  2.5 GB scale, NOT the ~10× the 5M framing claimed. State the REAL multiple in the gate
  evidence; carrying the old 10× wording over a 1M run would be a fabricated pass on a bar
  that was never tested. (5) **an
  ARTICLE CLEAN-UP strategy: DISCUSSED → AGREED (explicit maintainer sign-off BEFORE
  execution) → implemented → EXECUTED** on the real ~1M corpus (per row 3's withdrawn 5M
  bar), removing the undesired-article
  class (the nav-soup/list specimens — "a list, not an article"); building blocks = the
  prose gate (ingest door, stops new ones) + the Slice-4a retroactive QUARANTINE (reversible,
  never a blind delete) + the post-cleanup re-index (clears the junk keywords/entities);
  the strategy discussion settles quarantine-vs-delete, criteria, and review sampling.
  (6) **the DB-10 §1b PAGE-SIZE A/B BENCH (4K vs 16K) PASSED FULLY** (added same day) —
  the shipped `pagesize-bench` job run on the LARGE corpus (plus a small corpus for the
  trend, per its own design), the numbers reviewed, and the §1b `page_size` ruling MADE on
  that evidence (currently waiting on the large-corpus run; the CREATE-time seam makes
  this decision more expensive to revisit with every corpus born before it).
  (7) **the v0.2.0 P0 report's OWN follow-ups CLOSED** — cold-boot unlock at full scale on
  the complete corpus + a multi-day live collector soak (the P0.3 measurement covered only
  2 passes); both were flagged by the P0 report itself as not-yet-confirmed.
  (8) **a BROWSER-VERIFICATION bar** — either the AppVM `ui_walk` runner STANDING (R3, the
  V1-pathway-named highest-leverage build) or a DEFINED hand click-through of the flagship
  surfaces (Home/Leads · the analysis window · the post-import screen · source management ·
  the one-button diagnostics panel): the compounding "browser-unverified, needs
  click-through" backlog must not tag as measured-and-verified with the flagship UI never
  once rendered.
  The CHANGES.md 0.3.0 board + this entry are the live gate list; stand up a
  `RELEASE_0.3_GATE.md` checkable inventory (the RC-gate precedent) when the cycle
  approaches closure.
  **P0 VALIDATION RUN ON THE BIG CORPUS — MAINTAINER, 2026-08-03 (report
  `oo-p0-validation-20260803000812.json`, app 0.3.0, engine `oo-volumes-2`): 5 pass · 0 fail ·
  0 not-measurable.** REAL SCALE, stated as measured rather than as the bar's own wording:
  **16.5 GB / 794,333 articles**, i.e. **6.2× the 2,522 MB corpus v0.2.0 was validated at** —
  NOT the "100 GB" three acceptance-bar strings still say, and in the ~1M band the 2026-07-30
  ruling withdrew row 3 to. (Row 4's earlier "roughly 2×" estimate was low; the real multiple
  is 6.2×. Fix the stale "100 GB" bar strings on the next touch of `p0_validation.py`.)
  • **P0.1 backup — a genuinely strong pass.** Peak RSS grew **53.9 MB over a 15,699 MiB
    corpus (0.34 %)**, against v0.2.0's +440 MB over 2,522 MiB (17.45 %): RAM did not merely
    stay under a bar, it stopped tracking corpus size. 47 volumes / 18.2 GB in 1,040 s, parity
    available, gate held 279 s. Honest disclosure carried in the report: a long reader kept the
    live WAL from fully checkpointing, so the residual WAL rides as a member and folds back in
    at restore.
  • **P0.1 verify — clean.** Manifest signature + every data and parity volume checksum, every
    volume stream-decrypted, member checksums cross-checked; 0 bad, 0 missing, parity tolerance
    5/5 intact.
  • **P0.2 restore — pass FOR WHAT IT TESTED.** Staged round-trip + dry-run merge preview,
    `committed=false`, live corpus only ever read; quick_check ok, 0 FK violations, FTS 794,333
    = articles, 0 sampled content mismatches. RSS delta 637 MB — 12× the backup's, still flat
    against a 16.5 GB corpus. NOTE the bar's own wording is "imports on a **fresh install**",
    which a self-restore cannot demonstrate (every row reads as a duplicate) — see the finding
    below, and row 4, which is the row that actually closes it.
  • **P0.4 unlock — 776.6 ms vs the 2,000 ms bar**, init_db dominating (773 ms). The check's OWN
    reason still says "Confirm at full scale with a cold boot", nothing records whether that
    boot was cold, and `wal_bytes_before_open` is null on a run that separately reported an
    un-checkpointed WAL — so the WAL-recovery component is uncharacterised. **Row 7 stays open**;
    closing it is one clean shutdown + restart + re-run.
  • **P0.3 collector — no climb** (first pass 1,730 MB → peak 2,056 MB = +327 MB, under the
    512 MB floor) across 61 passes. But the passes span 2026-07-29T08:10 → 07-30T06:24 (~22 h)
    and are **4 days stale** relative to the report, and the bar names a MULTI-DAY soak. **Row 7
    stays open** on this half too; the report itself says "Confirm over a multi-day live soak."
  **A REAL FINDING THE RUN SURFACED (verified against the tree, not inferred from the report):
  fourteen tables are in the restore-merge's "reported-but-not-merged" middle state** — in
  neither `_MERGE_HANDLED` nor `_MERGE_IGNORED`, so `_unmerged_tables` COUNTS them in every
  restore report and nothing COPIES them. This is the 2026-07-24 `source_qualification_attempts`
  bug's exact shape, whose recorded lesson asked for "a completeness check that a new table must
  join one set or the other" — **that check had never been built**. The operator's report shows
  only NINE because `_unmerged_tables` skips EMPTY tables, so the field evidence under-states the
  gap by five and would under-state it differently on a corpus that had used watches or the AI
  layer. Triaged: `article_mentioned_places` (91,061) + `article_entities` (361,505) are REBUILT
  by the post-swap re-index, so nothing is lost; `derived_meta` / `feed_fetch_state` /
  `stat_snapshots` are per-machine or self-healing; and **nine were genuinely owed a handler** —
  `stat_figures` (35,000 networked official-statistics observations with vintages),
  `stat_subscriptions`, `hazard_event_details`, `keyword_tags`, `watches` + `watch_matches`,
  `ai_custom_prompt`, `ai_keyword`, `law_revision_summaries`. They ride INSIDE the artifact and
  no handler copied them, so a FRESH-INSTALL restore dropped them silently.
  **⚠ A CLAIM OF MINE THAT WAS WRONG, corrected the same day before acting on it:** the first
  write-up called it "an inconsistency worth settling" that `article_mentioned_dates` IS merged
  while its two siblings are not, all three being written by the same `index_article` pass. It is
  NOT an inconsistency. `article_mentioned_dates` carries a `status` column —
  `datestore.set_status()` is a human confirm/reject and reads filter `status != 'rejected'` — so
  a re-index recreates every date as a fresh `candidate` and NOT merging dates would silently
  discard the operator's own judgements. Places and entities have no such column. **THE RULE, now
  in the code:** a derived table may be left to the re-index only while it carries no human
  decision. (The lesson underneath: re-derive a defect's mechanism from the code before patching
  what a report names — this one would have "fixed" a correct design.)
  **SHIPPED 2026-08-03:** the completeness check (`_MERGE_NOT_CARRIED` with a reason per table +
  `tests/test_merge_completeness.py`), then **FOUR of the nine handlers** — `stat_figures`,
  `stat_subscriptions`, `hazard_event_details`, `keyword_tags` — chosen precisely because each has
  a UNIQUE CONSTRAINT THE SCHEMA ITSELF DEFINES, so its cross-corpus identity is the schema's
  answer and not one we invented. Behaviour-tested against the REAL `merge_corpus` over two real
  corpora (a self-restore can never exercise this: every row reads as a duplicate), including the
  vintage rule (two `extracted_at` vintages both survive — revisions are evidence), local-wins on
  a subscription's cadence, the article-id remap, and the DUAL unique constraint on hazard details.
  Stash-verified: 5 of the 8 fail with the handlers unregistered; the other 3 are local-wins/
  duplicate directions that cannot discriminate when nothing is copied at all — stated rather than
  counted as coverage.
  **THE REMAINING FIVE ARE BLOCKED ON A RULING, not on effort:** `watches`, `watch_matches`,
  `ai_custom_prompt`, `ai_keyword`, `law_revision_summaries` have **no unique constraint**, so
  "the same row in another corpus" is a DESIGN DECISION — and inventing one silently is how a
  merge starts duplicating or dropping. Each now carries its own question in
  `_MERGE_NOT_CARRIED` (is a watch identified by name or by its condition tuple? does a second
  model's law summary replace the first or sit beside it? does `ai_keyword` key on
  (article, kind, term) — collapsing two models' answers — or add prompt_version, which then
  duplicates on a re-run?), pinned by a test so an entry cannot say merely "owed".
  **SO, FOR FINALISATION:** the data-safety trio (backup · verify · restore machinery) is DONE
  at real scale and is the strongest evidence this cycle has produced. Rows 4 and 7 are NOT
  closed by this report — row 4 wants a COMMITTED full import (this was `committed=false`), row 7
  wants a cold boot and a multi-day soak, and the report's own reason strings say so for both.
- **DIAGNOSE-THE-DIAGNOSTICS — the all-diagnostics RUN JOURNAL (maintainer asked 2026-07-20:
  one-click-and-wait must hold at 5M scale, completeness "should be ensured", and each
  member needs begin/end timing — "the police of the police"; INVESTIGATED same turn, build
  PENDING — a prerequisite for 0.3 gate row 3):** VERIFIED STATE: completeness is already
  ensured BY RATCHET (2026-07-17 — every GET route → bundle member or documented exemption;
  the manifest's `excluded` block states the boundary); the background JOB exists
  (`/all-job` start/status/download, live `progress(done,total,name)`, cooperative cancel
  BETWEEN members — added because the sync build measured 36+ min at scale; `/all` kept
  absorption-gated); one failing member writes `<name>.error.txt` + a manifest line, never
  aborts. THE GAPS (all in `_write_all_diagnostics_zip` / `_all_diagnostics_manifest`,
  diagnostics.py:2807/:2752): per-member results carry ONLY `{file, ok[, error]}` — NO
  started_at/wall_s/bytes, so an hour-long 5M run cannot say which member ate it; the
  manifest is written LAST, so a HARD death (OOM/kill, not a cooperative cancel) leaves an
  archive with no self-description of where it died; no corpus-scale stamp (a log should
  say what size corpus produced it); members run UNBOUNDED (a hung member hangs the bundle
  — cancel only fires between members); the coverage guarantee lives in CI only, not in the
  artifact. THE BUILD (one slice): (1) the per-member ENVELOPE — every member records
  `{file, outcome ok|error|skipped-deadline, started_at, wall_s, bytes}` (+ RSS delta where
  cheap); (2) the DURABLE JOURNAL — the job path appends `begin`/`end` lines to a sidecar
  `journal.jsonl` as it goes (crash-safe: a hard-killed run's last `begin` without `end`
  NAMES the culprit), folded into the zip as `bundle-journal.jsonl` on completion; (3) the
  MANIFEST gains a run HEADER (corpus counters snapshot via the MAINTAINED counters —
  articles/keywords/mentions — app version, schema head, started/ended, total wall) + a
  slowest-members summary + a RUNTIME COVERAGE block (recompute the ratchet's route-vs-
  member-vs-exemption comparison at run time, so the artifact itself proves completeness —
  ensured in the log, not just in CI); (4) per-member DEADLINES honoring the S8 lesson —
  DB-touching members run INLINE under a statement deadline (NEVER threaded on a shared
  connection), only non-DB members may take the wall-clock thread; a timeout records
  `skipped-deadline` honestly and the bundle continues; generous env-tunable defaults (a
  diagnostics run is not a UI request); (5) the panel/task-manager line shows "member i/N ·
  name · elapsed" (the progress callback already carries it). 0.3 TIE-IN: gate row 3 (the
  5M diagnostics run) depends on this — without the journal, a failed hour-long run at
  scale is undiagnosable.
  **AMENDED same day (maintainer added two rulings):** (6) **HARDWARE PROFILE in the run
  header** — the diagnostics must scan the machine so every measurement reads in
  perspective of hardware capacity (the maintainer tests across several rigs incl.
  low/cheap/old laptops — cross-machine comparison is the point): CPU model + physical/
  logical cores + freq, total RAM + swap, disk FREE + rotational-vs-SSD (the Linux
  `/sys/block/*/queue/rotational` probe; honest `unavailable` on other OSes), OS/kernel,
  plus an OPTIONAL operator-set MACHINE LABEL (settings/env, e.g. "old-thinkpad") so logs
  from different machines are distinguishable at a glance. All LOCAL reads, zero network,
  shared only by click (the standing diagnostics posture). (7) **DIAGNOSTIC-BUTTON
  CONSOLIDATION ruled: remove all per-report download buttons except THE ONE
  all-diagnostics button** — safe because the ratchet guarantees the bundle carries every
  report. THE DISTINCTION that must survive the sweep: JOB-STARTERS and INTERACTIVE tools
  (p0-validation · pagesize-bench · the source-quality ZIP · rollup/source-coverage
  benchmarks · IR-eval + gold-builder · discover-world · the upcoming LLM triage/tag runs)
  are ACTIONS, not report downloads — they STAY (the Desk lesson: absorption-gated, never
  silently lose a tool; ENDPOINTS are never removed, only redundant download buttons).
  Browser-unverified per fork-3/Q6a; extend the UI invariant tests to pin the one-button
  state + the surviving action controls.
- **AIRPLANE MODE MUST NOT BLOCK LOOPBACK OLLAMA INFERENCE (maintainer to-do 2026-07-20,
  field report: "the app is currently requesting airplane mode to be turned off to allow
  ollama local model article translation — this should be fixed"; ROOT-CAUSED same turn,
  fix PENDING):** `OllamaClient._check_kill_switch` (`src/llm/ollama.py:183`) blanket-refuses
  EVERY Ollama call while the kill switch is engaged — including pure-loopback GENERATION
  (translate/summarize/synthesize/extract against an already-installed local model, zero
  egress) — with exactly the message the maintainer hit ("Turn airplane mode off to use the
  local LLM"). This CONTRADICTS the airplane-mode non-negotiable's own design: the socket
  guard deliberately whitelists loopback "(the app's own server, loopback Ollama, file DB)"
  precisely so local inference works offline; the per-call gate (self-described "defense in
  depth") is stricter than the guarantee it defends. FIX SHAPE: split the gate by egress
  class — generation/list/health are loopback inference (`_require_loopback` already refuses
  a non-loopback URL at construction; a missing model errors, it never auto-pulls) → allowed
  under airplane; `pull`/`remove`-with-download + the binary installer STAY kill-switch-gated
  (a pull egresses CLEARNET via the SEPARATE ollama process, which the in-process socket
  guard cannot see — that half of the gate is load-bearing, never relax it). Sweep the
  callers when fixing: the bulk-LLM path, auto-on-ingest extractors, langdetect-LLM, and any
  UI ensureOnline prompt wired to LLM actions (the frontend may ALSO be gating locally — the
  reader/bulk translate surfaces should not demand the ONE network consent for a loopback
  call). Tests must pin BOTH directions: generate works with the kill switch engaged (no
  socket beyond loopback) AND pull still refuses.
- **SOURCE IPs — SURFACE THE CAPTURED DATA (maintainer asked 2026-07-20: record source IPs,
  show in each article's view, accessible in source management, sources may have MULTIPLE
  IPs, world map per-country sources by IP; INVESTIGATED same turn — capture EXISTS, three
  surfaces are the gap; builds PENDING):** ALREADY SHIPPED (2026-06-19 slices 6a/6b/6c + the
  2026-07-02 .eml sender-IP): per-ARTICLE `Article.server_ip`/`ip_observed_at`/
  `server_ip_reason` captured at fetch (web + newsletter sender-IP), the bundled offline
  DB-IP geolocation (CC BY 4.0), the `server_locations` aggregation
  (`queries.py`/`insights.py`) and the ooMap "Server IPs" point layer (browser-unverified).
  The per-article observation model ALREADY yields multiple IPs per source over time
  (CDN/rotation) — no schema change needed, the asks are SURFACES: (1) the article/reader
  view does NOT show the captured IP (verified: `server_ip` absent from `src/api/main.py`) —
  add it to the reader's app-deduced metadata class with the standing caveats
  (`server_ip_reason`; "may be a relay/CDN edge, never proof of origin"; Tor-fetched →
  honestly unavailable since the socket is the proxy); (2) a per-SOURCE aggregated IP view
  (distinct observed IPs + first/last seen + geolocated country each) in the source-
  management interface — an aggregation over the existing article columns, no new capture;
  (3) a per-country SOURCES-by-observed-IP choropleth DIMENSION on the world map — DISTINCT
  from the existing sources-per-country dimension (which keys on the catalog-ASSERTED
  `Source.country`): asserted vs observed-infrastructure are different classes and must
  never be silently blended (a source whose articles geolocate to several countries counts
  once per country, disclosed; the anycast/CDN approximation caveat visible per the 6c
  ruling). All three are surface slices over shipped data; frontend conservative+flagged
  per Q6a.
  **AMENDED same day (maintainer asked to circumvent the Tor gap — "can't we ping the source
  server or ask the server directly?"; ASSESSED, design of record pending the go):** DIRECT
  contact is RULED OUT as an automatic mechanism by the standing never-silently-downgrade-
  transport non-negotiable: ICMP ping CANNOT ride Tor at all (Tor is TCP-only, so a ping is
  ALWAYS clearnet by construction), and a direct probe of a just-Tor-fetched source hands the
  server + ISP a TIME-CORRELATED link between the user's real IP and that source — a
  deanonymization worse than fetching clearnet outright. THE TOR-NATIVE PATH INSTEAD:
  Tor's SOCKS port supports the RESOLVE command (0xF0 — the stock `tor-resolve` mechanism,
  same SocksPort the app already uses, no control port) — the EXIT performs the DNS lookup,
  so the source's DNS sees only the exit, never the user: zero direct contact, zero new third
  party (DoH deliberately NOT chosen — it would add an external service class), ~30 lines of
  stdlib socket code, cached per (domain, pass), kill-switch-gated, degrades honestly when the
  configured SOCKS proxy is not Tor (rejects 0xF0). HONESTY: the answer is the SAME epistemic
  class as the clearnet capture at a DIFFERENT vantage (CDN answers vary by resolver — "edge
  nearest the EXIT" vs the socket capture's "edge nearest the user"; an origin hidden behind
  a CDN stays hidden either way) → store under a DISTINCT provenance class
  (`server_ip_reason: dns-via-tor-exit`, never blended with socket-observed; exit-rotation
  variance is DATA under the multiple-IPs-per-source model, disclosed). FUTURE free upgrade:
  when the designed-not-built Stem/control-port integration lands, Tor's ADDRMAP cache
  exposes the resolutions exits ALREADY performed during the fetches — zero extra queries;
  the SOCKS-RESOLVE path need not wait for it.
- **SOURCE DISCOVERY TRAIL · QUALIFIED-CITATIONS TALLY · CORPUS SOURCE/LANGUAGE FILTERS
  (maintainer asked 2026-07-20; INVESTIGATED same turn — substrate exists for all three, the
  SURFACES are the gaps; builds PENDING):**
  (1) **DISCOVERY PROVENANCE TRAIL** — when a source enters the qualification pipeline the
  user must see WHERE it was first discovered (which article cited it) and be able to check
  the source's source. EXISTS: `SourceCandidate` (models.py:1725) carries channel + evidence
  JSON + first_seen; `Source` `via:*` provenance tags; `external_sources.discovered_via`
  (Q4a); the citing trail is derivable on demand from `article_links` (the cited_sources
  docstring says exactly this; "the sources' sources" is the standing Links-design goal, and
  the S6.1b carry-over already names "surface the citing trail"). BUILD: a per-source
  provenance panel in source management + the qualification review view — channel-appropriate
  origin (cited/newsletter-link → the FIRST citing article [min created_at among citers] +
  its source, click-through to the local reader and to the citing source's row;
  catalog/wikidata/legal → channel + evidence). Verify at build whether the citation
  channel's evidence JSON already stores example article ids; the trail recomputes from
  `article_links` regardless.
  (2) **QUALIFIED-CITATIONS TALLY (maintainer: "not interpretation, just a ratio … a tiny
  icon")** — per source, how many of its cited domains are qualified/disqualified. HONESTY
  GUARDRAILS recorded with the ask: (a) visible form = the TALLY with n ("cited domains: 14
  qualified · 3 disqualified · 5 pending · 12 never-registered [commerce/social/infra-
  filtered]"), a tiny icon is fine but the #oo-tip hover (invariant #17) carries the full
  tally + caveat — never a bare percentage badge that reads as a grade; (b) DENOMINATOR:
  raw cited domains include masses of legitimately-non-article links (every healthy outlet
  links companies/platforms when reporting ON them), so the meaningful universe is domains
  that entered the qualification funnel, with the filtered classes tallied separately —
  else the ratio is noise; (c) CAVEAT visible: citing a disqualified domain is NOT guilt —
  disqualification is extraction-validity ("not a content source"), never editorial badness;
  the tally is a descriptive fact, no interpretation (the maintainer's own framing); (d)
  field-name discipline: no score/rating/grade/ranking substrings in payload keys (the
  "degraded"-contains-"grade" walker lesson; qualified/disqualified are safe). Perf: derive
  from `article_links` × qualification status per the cited_domain_stats shape (covering
  scans, never a codec join). **RECIPROCAL VIEW ruled same day (maintainer: "reciprocally,
  I'd like to see when a source has mentioned qualified sources"):** the tally's classes
  become CLICKABLE DRILLS — each class (qualified · disqualified · pending · filtered)
  expands to the actual LIST of cited domains in that class, each row linking to that
  source's own management row AND to the citing articles (the `article_links` trail — the
  same "sources' sources" grammar as the Related subtab's shared-origins lens). SYMMETRY
  CAVEAT recorded: the positive direction carries the SAME no-interpretation discipline as
  the negative — citing many qualified sources is NOT an endorsement/quality signal (wire
  services get cited by everyone; a laundering hub can cite reputable sources deliberately —
  the source-laundering card's own lesson), exactly as citing a disqualified one is not
  guilt; both directions are descriptive facts with the caveat visible.
  (3) **CORPUS FILTER-BY-SOURCE/LANGUAGE IN THE ARTICLES TAB ("apply filter" → the deduced
  corpus)** — EXISTS: `#an-adv-source` + `#an-adv-lang` (Advanced subtab), threaded through
  `anParams()` into EVERY subtab + the "Filtered" chip (`_anFilterSummary`). GAPS the ask
  names: the controls live in Advanced, not the Articles tab; source is free-TEXT, not a
  facet list of what the current corpus actually contains; and an Advanced refine CLEARS a
  card-seeded exact-id corpus instead of narrowing it. BUILD: facet controls in the Articles
  subtab (the sources + languages present in the CURRENT corpus, with counts) + an "Apply
  filter" that recomputes the whole deduced corpus across subtabs; for an id-seeded corpus
  INTERSECT (the corpus_facet_article_ids drill grammar — ids ∩ filter → refreshed window)
  rather than clear. Frontend conservative+flagged per Q6a.
- **NAV-SOUP SPECIMEN — the ≥100-word body-gate recall gap in the non-article filter
  (maintainer field specimen 2026-07-20: the Irish Mirror `newsletter-preference-centre` page
  stored as an Article; ROOT-CAUSED same turn, fix PENDING):** the specimen (captured
  2026-07-04) is pure header/footer nav chrome, with the extraction fallout proving the
  pollution class — menu items became PEOPLE ("News Latest · Irish News · Mirror Bingo") and
  an ORG ("Soccer Golf Rugby Union") in When×Where×Who. TWO findings: (a) it PREDATES the
  ingest-door classifier (`src/ingest/non_article.py`, shipped 2026-07-13 off the
  source-quality recall gap) — legacy junk of this class sits in the DB; the Slice-4a
  retroactive QUARANTINE carry-over is what removes it, and a re-index then clears the junk
  entities/keywords. (b) the filter would STILL miss it TODAY: its load-bearing guard
  auto-KEEPS any body ≥ `_ARTICLE_MIN_WORDS=100` regardless of URL — and the specimen is
  ~135 words OF MENU ITEMS (word-RICH nav soup defeats the thin-body precondition); the URL
  rules are exact-segment matches, so the hyphenated compound `newsletter-preference-centre`
  misses `_UTILITY_SEGMENTS`. THE FIX (extends the filter, keeps its high-precision
  keep-when-in-doubt posture): (1) **the PROSE GATE** — for ≥100-word bodies, function-word
  DENSITY of the asserted/best-matching language (the vendored stopwords-iso sets — the SAME
  signal recorded this session for source_audit) AND-gated with near-zero
  sentence-punctuation density → verdict `nav_soup` (the specimen: ~5% density + ~0 sentence
  periods vs ~40%+ for real English prose; the AND is precision-serving here — a drop needs
  BOTH signals, since a false positive is data loss). Guards: script-aware (unsegmented
  zh/ja/th SKIP the gate or go segmenter-fed — the S5.2 mislabel lesson: unmeasurable text
  is never dropped on a gap); headline-LIST pages (moderate density) deliberately escape —
  the source-level auditor's territory, an honest undercount per the filter's own design.
  (2) URL rules extended to HYPHEN-PARTS of segments (newsletter/preference/signup as
  compound components) — safe because URL rules already fire ONLY under the thin-body
  precondition. (3) optional crawl-time URL pre-skip (bandwidth saving only — the store-side
  gate stays the honesty line). LAYERING NOTE: per-ARTICLE gates handle junk pages of REAL
  sources (irishmirror.ie is a legitimate outlet — qualification would rightly NOT
  disqualify it over its preference page); wholly-junk SOURCES are qualification's job —
  the two layers compose, neither replaces the other.
- **DESIGN-FOLDER AUDIT + REMEDIATION PLAN (2026-07-22, user-requested; full detail
  in [`docs/design/ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](docs/design/ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md)):**
  a 7-fork subagent fan-out audited every file then in `docs/design/` (34 total)
  against LIVE `main` — each claimed "not done" item was grepped against the actual
  code, never trusted from the doc's own text. HEADLINE CORRECTION: all six
  2026-07-18 briefs (convergence-amendment · families-entities · groups-layer-
  amendment · leads-calibration · lemma-default-on · supergroups) turned out to be
  FULLY BUILT — real execution had landed on `main` between 2026-07-19 and 07-21
  that this ledger's own prior text did not yet reflect (lemmatization is ON by
  default now; Home's Leads are actually reordered by the shipped `sort_leads`
  core). HEADLINE GAP: **DB-10 §1a/§1b were ruled + evidenced (2026-07-17, PR
  #726) but NEVER actually wired into `src/database/connect.py`** — every corpus
  created today still gets the pre-ruling PRAGMA defaults; this is the plan's
  Phase 1, highest-value + self-contained. ARCHIVAL DONE SAME PASS: 10 docs whose
  entire scope was confirmed fully executed moved non-lossily to
  `docs/archive/{design,session-briefs}/` (3 non-brief docs got a new
  `docs/archive/design/README.md`; the 6 briefs + the OPTIMIZATION_TAIL brief
  joined the existing `docs/archive/session-briefs/` index). The 22 remaining
  `docs/design/` files that had at least one stale claim each got a short
  status-update banner pointing at the plan doc. The plan itself has 11 phases
  tagged buildable-now / operator-gated (needs a networked machine or Ollama rig)
  / maintainer-ruling-gated / browser-gated (Observatory's `ooSky` renderer,
  explicitly sequenced behind a real click-through) — including the carried-
  forward remainder of the 2026-07-17 docs-review plan (T1/T2/T3/T5/T6, now that
  T8's archival is done), the law vertical's S3/S6/S7, keyword-baseline S1b/S4,
  the OSM boundary-preprocessing bridge, and the field-diagnostics brief's #728
  fixes. NOT YET EXECUTED — this entry records the AUDIT + PLAN, not the
  remediation itself.
- **GUI AUDIT 2026-07-28 — TRANSLATION COVERAGE · GRAPHICAL QUALITY · VISUAL DATA REPRESENTATION
  (maintainer-asked "a detailed comprehensive and critical look at the GUI … notably all parts of
  the UI that are omitted from the translation, as well as identifying graphical enhancements, as
  well as all visual data representations or potential visual data representation enhancements.
  Don't fix anything yet, analyze, document and prepare a PR for another autonomous session";
  ANALYSIS-ONLY — nothing fixed; brief of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-28_GUI_AUDIT.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-28_GUI_AUDIT.md);
  worklist = `docs/audit/gui-audit-2026-07-28/i18n_missing_keys.csv`; the three stdlib probes that
  produced every number are COMMITTED under `docs/audit/gui-audit-2026-07-28/probes/` so the fix
  session re-measures rather than trusting the doc):** static source-level audit, deliberately
  composing with (never restating) the 2026-07-22 behavioural GUI test report — whose own §9 item 9
  asked for exactly this ("a dedicated i18n sweep … systemic across many surfaces") and item 10 for
  the `--warn` contrast fix. **MENTAL-MODEL CORRECTION recorded so it is not repeated: a string not
  wrapped in `t()` is NOT thereby untranslated.** `i18n.js`'s MutationObserver walks
  DYNAMICALLY-inserted DOM and translates any text node / placeholder|title|aria-label whose
  normalized value matches a locale key — so a `<th>` built in `app.js` IS translated today if the
  key exists; **the gap is a missing KEY, not a missing wrapper.** Corollary caught mid-audit:
  `toast()` appends into the plain `#toast` div (in `<body>`, not SKIP-listed, no `data-i18n-dyn`),
  so a bare `toast("Preferences saved.")` whose key exists is a ~120 ms ENGLISH FLASH, not an
  untranslated string — filing those 539 sites as "translations never shown" would have been a
  fabricated finding. MEASURED (floors, not totals — static matching misses interpolated strings):
  471 DOM-reachable literals already keyed (the engine works) · **319 (272 distinct) with NO key =
  permanently English in all 11 non-English locales** · 6 native `confirm()`/`alert()` arguments the
  walker can never reach · 539 keyed-but-bare flashes. **I-1 (highest leverage): the gate is
  structurally blind to the UI engine** — `scripts/i18n_report.py` sets `_UI = index.html` (line 38)
  and opens nothing else, so `--min 100` reads a GREEN 2130/2130 ×12 while `app.js` (18,536 lines,
  213 permanently-English strings), `reader.js`, `taskmanager.html`, `unlock.html`,
  `investigate.html` and the 8 `guis/` skins are invisible to it; widening its scope is what stops
  the class regrowing, and MUST land with/after the key additions or CI reddens instantly. **I-2
  (leads the fix session — a NON-NEGOTIABLE BREACH): the reader's two-class provenance HEADINGS are
  unkeyed** — `From the source` / `Deduced by this app — less reliable` / `AI-derived — unreliable`
  (+7 more, `src/api/main.py:1606/1607/1632/1675/1748/1750/1765/1991/1992/1996`), verified absent
  from `en.json` by exact AND substring lookup: the labels that CARRY the reliability claim render
  English-only in 11 locales, so the informed-consent layering degrades exactly where it is
  load-bearing ("Every consent/caveat string ships ×12 locales"). Ten keys. **I-3:** the largest gap
  family is 33 distinct `"<Verb> failed:"` strings → ONE `OOI18N.tf()` template
  (`"{action} failed: {error}"`) ×12 replaces all 33 (naively they would cost 396 entries).
  **GRAPHICAL — G-1: `--warn` FAILS WCAG AA on 6 of 17 themes**, computed with the same method as
  the shipped invariant-#23 `--caveat` fix and modelling `:root` inheritance explicitly (getting
  that wrong under-reports): paper 2.12 · dawn 2.16 · solar 2.82 · mist 3.56 · light 3.72 · mint
  3.82 — **every failure is a LIGHT theme, the identical signature `--caveat` already had (8/17)**,
  so the fix is the same shape. **G-2: the inline-handler debt is ~1.9× the ledger's own recorded
  figure** — the "295 as of 2026-06-15" counted `index.html` only; measured now 317 there + **239
  inside `app.js`-generated markup (never counted before)** = 556, vs 103 `addEventListener`; stays
  browser-verify-gated (fork-3), NOT proposed. **G-3:** 5 layout media queries in 1024 CSS lines
  with NOTHING between 900 px and desktop (source-level corroboration of the prior report's live
  top-bar P0), `prefers-contrast` unhandled (0 uses) despite a `contrast` theme existing, and 0
  `.sr-only` in the static shell (though `ooMap` builds one in JS). **VISUAL DATA — V-1 (biggest
  opportunity): 8 `ooviz.js` primitives are BUILT + TESTED (`test_ooviz.py`, `ooviz_node_test.js`)
  with ZERO call sites** — `binCounts1D` (histogram) · `fiveNumberSummary` (box plot) · `bin2D`
  (heatmap) · `sqrtAreaScale`+`symbolRadii` (proportional symbols, the ruled levels-not-normalised
  map path) · `pathWithGaps` (draws a BREAK instead of bridging a gap = the honest rendering) ·
  `statSeriesPaths` · `setupCanvas`; app.js uses only 6 of the ~14. The maths is written, the
  honesty semantics are already encoded, the tests pass — **what is missing is call sites.** **V-2:**
  parsing all 941 top-level `app.js` functions, 87 call a renderer and **35 emit a table and never a
  chart** (largest: `renderCorpusCompetitive` 96 lines · `renderCorpusKeywords` 56 · `loadLunar` 49 ·
  `_uxCorpusDeltaView` 48 · the stats trio); candidates NOT a mandate — a chart is added BESIDE the
  table, never replacing it (invariant #8 + the Desk lesson), counts only, no score, n + method
  visible, sparse→bars. **V-3:** the `_SPARSE_BAR_MAX=10` rule reaches `ooChart`/`dashChartSvg`/
  `slopeChartSvg`/`smallMultiplesSvg` but NOT `ringDumbbellSvg`/`commodityOverlaySvg`/`ooDonut` —
  flagged for a decision (the dumbbell plots discrete pairs so arguably needs no rule; the commodity
  overlay DOES draw a price line and should be checked), not asserted as a defect. **V-4: `ooDonut`
  contradicts the project's OWN committed chart-decision framework** (`docs/research/dataviz/`:
  "Pie/donut only if ≤4–5 slices … otherwise bars"; "many-slice pie" is on its REJECT list) — it has
  NO slice-count guard and its single caller feeds it `unlocated.by_language`, an UNBOUNDED language
  set, coloured `hsl(i*360/n)`; suggested resolution = donut ≤5 slices, sorted bars above, remainder
  grouped as a labelled "other (n)", never silently truncated. **THE FIX SESSION'S ORDERED PLAN
  (§4 of the brief, 8 slices, severity×ease, each independently shippable):** 1 reader provenance
  keys → 2 the `tf()` error templates → 3 the ~239-string Class-A key sweep → 4 widen the gate →
  5 `--warn` theme-aware value → 6 `ooDonut` guard → 7 `prefers-contrast` → 8 first `ooviz`
  activations. EXPLICITLY OUT OF SCOPE there: the 72 behavioural findings of the 2026-07-22 report ·
  the Observatory (browser-gated, already specified) · the inline-handler retirement · the top-bar
  responsive fix (that report's item 4) · the 539 class-C flashes (lowest value per edit). HONEST
  LIMITS stated in the brief itself: no browser was run (contrast is COMPUTED from the variables,
  not sampled pixels) and static matching misses interpolated strings, so every count is a floor.
- **SYSTEMATIC GUI TEST & CRITICAL REVIEW — EXECUTED 2026-07-22 (maintainer-asked; brief of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_GUI_SYSTEMATIC_TEST.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_GUI_SYSTEMATIC_TEST.md);
  report = [`docs/audit/GUI_TEST_REPORT_2026-07-22.md`](docs/audit/GUI_TEST_REPORT_2026-07-22.md);
  full detail in the shipped.csv row):** a 100-agent orchestrated run (14 walk/lifecycle/cross-cutting/
  perf agents → 86 raw findings → a fresh-load adversarial skeptic re-verification of every candidate →
  72 merged survivors after cross-group dedup, 5 P0 · 24 P1 · 38 P2 · 5 OPT) drove a real Chromium
  browser against the app across all three test states on a synthetic corpus seeded through the real
  `index_article` chokepoint. All 5 P0s + 4 sampled P1s HAND-RE-VERIFIED by the orchestrating session
  itself (source-code citations + fresh live reproduction) beyond the in-workflow skeptic pass — 9/9
  confirmed, zero false positives. **HEADLINE POSITIVE:** the airplane-mode zero-egress guarantee held
  perfectly across thousands of requests under adversarial concurrent load (100 agents, none ever
  reached a non-127.0.0.1 host). **HEADLINE NEGATIVES (5 P0s):** the reader's "Related in your corpus" +
  near-dup badge query a DEAD legacy table (`article_keyword_association`, zero writers anywhere in the
  live ingest path — confirmed via source) so they are silently, permanently non-functional for every
  article in any modern corpus; the `#net-coach` onboarding coachmark pointer-blocks the very airplane
  toggle (+ language switcher/task-manager/shutdown) it points at; any rejected first-launch passphrase
  hides the WHOLE create-passphrase form (root-caused in `unlock.html`'s `go()` — `_startPrep()` hides
  the view before the catch handler ever un-hides it, confirmed live: `document.body.innerText` goes
  empty); at 375px the airplane toggle + language switcher + task-manager + shutdown are pushed
  off-screen with zero scroll affordance; the Settings text-size slider has NO accessible label at all
  (axe critical). Also found: a boot-ordering race destroys the flagship parallel-analysis-tab
  workspace on every omnibar search opened in a new browser tab (P1, root-caused via `app.js:15293-
  17497`); Settings→General lossily collapses any of the 17 named themes to plain Ink on save (P1);
  browser Back while a backup `<dialog>` is open leaves the app invisibly frozen (P1); THREE known-open
  items independently confirmed ALREADY FIXED (Families kind-dropdown honesty hint, the moon-glyph
  dedup, the post-import Articles-first headline); the Governments-tab-defaults-to-Countries known-open
  item independently rediscovered by 4 separate test groups (merged to one finding, strong cross-
  validation). METHODOLOGY CAVEAT stated prominently in the report: "384 total JS errors" is 100%
  `console.error` 429-rate-limit resource-load lines from the test's OWN 14-concurrent-agent load on
  one shared server — ZERO real `pageerror` exceptions occurred anywhere in the whole run (every group
  independently confirmed this); the app degraded LOUDLY and gracefully under the storm (visible
  "busy — retrying" toasts), a genuine FAILURE-lens pass. 5 of 7 skeptic-killed candidates trace to
  this same rate-limit artifact. Passing surfaces carry the honest stamp "Chromium-verified (remote
  sandbox) · awaiting human UX pass" (explicitly NOT the Gecko-verified(VM) bar). Composes with the
  shipped `ui_walk.py` row-8 harness (not duplicated; a real driver implementation was skipped this
  pass, disclosed as a clean follow-up). REMAINING: the report's §9 ordered fix list (10 items, P0s
  first); the `OO_DB_PLAINTEXT` legal-acceptance-bypass seed question stayed genuinely untestable
  (needs a differing-env server restart); a maintainer click-through remains owed regardless.
- **PR #740 + PR #744 REMEDIATION — SESSION BRIEF (maintainer-asked 2026-07-22, "have a careful
  and detailed look... create a very detailed, professional and highly curated prompt for an
  entirely autonomous session maximizing the use of subagents addressing both PRs"; brief of
  record = [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_PR740_PR744_REMEDIATION.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_PR740_PR744_REMEDIATION.md);
  execution PENDING):** the operating manual for one autonomous, subagent-parallelized session
  that builds PR #740's buildable-now remediation phases (the design-audit board — DB-10
  create-time seam, docs hygiene, law vertical, keyword-baseline, OSM preprocessing,
  field-diagnostics) AND fixes PR #744's P0/P1 GUI-test findings, chosen as a PAIR precisely
  because their file scopes are almost entirely disjoint (backend/DB vs frontend HTML/CSS/JS —
  the ideal shape for real subagent parallelism). Every citation in the brief was RE-DERIVED
  from the live tree during authoring (not copied from either source PR's own text), confirming
  both PRs' core claims still hold with nothing else having landed on `main` in between (a clean
  740→742→744 linear chain). **THE BRIEF'S OWN NOVEL FINDING (neither source PR states this):**
  PR #740's Phase 1 (`auto_vacuum=INCREMENTAL` + `page_size=16384` on fresh-file creation) is
  MISSING a load-bearing safety requirement — `src/database/session.py:63`'s normal boot reopen
  path passes NO `cipher_page_size` to `connect()`, so if a store gets created at 16384 without
  ALSO teaching every future reopen to redeclare that size, the very next restart would misread
  the user's correct passphrase as wrong (SQLCipher cannot discover page_size from the file — the
  EXACT bug class this project already has a named Lessons-list entry about, from a real
  2026-07-19 field failure). Root-caused precisely: `auto_vacuum` alone (§1a, RULED yes 2026-07-17,
  verbatim "I agree with your proposal to change the auto_vacuum to incremental") carries NO
  reopen hazard since it doesn't change page framing; only `page_size` (§1b, evidence delivered
  but explicitly "awaiting the maintainer's ratification" — NOT yet formally ruled) does. The
  brief mandates a persisted-marker-or-verify-fallback design + a create→restart→reopen
  round-trip test as part of Phase 1's own DoD, and resolves the §1b ratification gap by
  instructing the future session to ship §1a and §1b as SEPARATE PRs, the §1b one prominently
  self-labeled "merging this PR is being treated as the ratification, per the §1a precedent —
  close without merging to hold it instead," so the maintainer's actual decision power is
  preserved without needing a synchronous mid-session answer. Also corrects PR #740's own
  `connect.py` line-86 citation (that line is inside `is_encrypted_file()`, not the actual
  fresh-file PRAGMA site — the real target is the "Fresh file" branch at line 169 with THREE
  sub-paths needing the fix, not one). Embeds exact, verified CI commands (the blocking
  `ruff check --select=F,B --extend-ignore=B008`, the pinned `bandit==1.9.4 -r src/ -ll -q`, the
  `MYPY_BASELINE=127` ratchet, `i18n_report.py --min 100`) rather than vague references. Scope
  fence carries forward every maintainer-ruling/operator/browser gate both source PRs already
  established (5 new verticals, the Observatory frontend, the LLM-rig-dependent runs, etc.) —
  none of those are touched. REMAINING: execution (nothing built yet — this is the brief only).
- **FIELD FEEDBACK 2026-07-23 — seven impressions from multi-VM/multi-machine use (maintainer;
  brief of record = [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-23_FIELD_FEEDBACK_WORKFLOW.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-23_FIELD_FEEDBACK_WORKFLOW.md),
  which carries the verified-current-state table + per-slice specs/acceptance):** the seven items
  were (1) a downloadable per-import report, (2) import-time screening of non-articles carried in
  by OLDER engines, (3) Library-tab live GRAPHS instead of figures, (4) scraping STALLS, (5) a
  compressed "Downloaded" section + own wiki/law tracked sections, (6) "~50,000 sources" vs ~5,000
  articles, (7) throughput ~5,000 articles/12 h is too slow (want ≥10×).
  **THE 12 ANSWERS/RULINGS (maintainer, same day) — the binding spec:**
  • **A1** import report = JSON + Markdown, PERSISTED on disk, and the persisted reports RIDE the
    backup export/import; folds into the ruled post-import results screen (one build, not two).
  • **A2** screening disposition = **QUARANTINE-IN-DB** (reversible, criteria-version-stamped,
    excluded from search/analytics/keywords by default); quarantined articles ALSO ride backup
    export/import (they are data, never silently dropped).
  • **A3** the screening runs **RETROACTIVELY on existing corpora** (this is the 0.3 close-gate
    row-5 cleanup; the agreed-strategy-before-execution step still applies to the criteria).
  • **A4** criteria scope = BOTH extraction-validity AND borderline classes, tested together via an
    ITERATIVE loop — a TEMPORARY criteria-calibration DIAGNOSTIC first (top-100 of would-be-
    disregarded articles + statistics + per-article detail) so criteria are optimised on real
    specimens before any execution (propose→human-review→apply, the stoplist discipline).
  • **A5** Library graphs confirmed; snapshot recorder with **INFINITE retention** (hourly counter
    snapshots are trivial; article series backfills from `created_at`, other counts begin at
    recording start — never a fabricated backfill).
  • **A6** every instance runs over Tor; the maintainer judges the stalls NOT Tor-linked.
  • **A7 RESOLVED (the "50k")** — the maintainer's sources CSV (46,213 rows) = 42,612 DISABLED
    `via:wikidata-discovery`+`world-catalog` candidates + 3,599 ENABLED. So it is the world-
    discovery machinery working AS RULED, blended into one Library "Sources" count — a DISPLAY
    problem, not a registration bug. Composition note: source_type institution 20,777 / news
    17,021 / religious 7,957 — the Wikidata specs' breadth makes the qualification membrane
    ESSENTIAL before any of it enables.
  • **A8 (workflow order RULED)** source QUALIFICATION first, THEN the Library graphs UI; the
    2026-07-20 qualification rulings are the spec.
  • **A9** `collect_rate_mode` default flips "target"→"maximum" + the top-bar speed knob + the
    version under the sidebar logo. NOTE: a saved settings.json predating the flip keeps "target"
    until the user clicks the knob.
  • **A10** proceed WITHOUT the collect_perf measurement for now; the write-batching decision stays
    measure-gated.
  • **A11/A12 (throughput, maintainer facts)** enabled sources publish >10 articles/day (publish-
    rate bound REJECTED for the enabled set); measured average download is a FEW kB/s, two orders
    below Tor capability → the bottleneck is app-side. An 8-core machine shows the SAME download
    rate as a 2-core/4 GB one — the machine is NOT the issue.
  **TWO DIAGNOSTICS EXPORTS ANALYSED (slow 2c/3.2 GB AMD 3020e + fast 4-vCPU/9.7 GB i7 Qubes VM,
  launched together) — THE STANDING THROUGHPUT VERDICT, three stacked causes:** (a) **memory** —
  the governor's mem-low floor parks permits at median 2 on the 3.3 GB box ("memory-bound"); the
  "maximum" flip cannot lift it, RAM is the worker ceiling on 3–4 GB machines (ZERO mem-low samples
  on the big box, so this cause is hardware-dependent). (b) **supply** — ~90% duplicate rate on
  BOTH machines; 2,766 of 3,599 enabled sources have an rss_url and yield ≈2 new/day/feed (the
  ">10/day" holds for big-name feeds, not the median), so 10× needs more QUALIFIED+ENABLED sources
  + crawl mode, not more workers. (c) **duty cycle** — inter-pass gaps of 3–8 min on BOTH machines
  (the fast box is WORSE: 48% fetching / 52% gap) because the gap work is SINGLE-CORE analytics +
  SERIAL TOR FETCHES in the ride-alongs, so it barely scales with CPU → the duty-cycle fix is the
  TOP lever. The fast box also hit **"writer-bound"** pass verdicts — the LIVE measurement the
  deferred COLLECTOR write-batching was explicitly gated on, so write-batching graduates from
  measure-gated to evidence-justified. Dozens-of-minutes stalls remain UNEXPLAINED (collect_perf's
  rolling retention covers ~one pass — too short; the Library graphs are the detector).
  MAINTAINER'S third 8-core/20 GB machine: SAVE it as the before/after bench for the duty-cycle fix.
  **SHIPPED (S1 · S2 · S3.1 · S3.2 · S3.3+S3.5 · S4.1 · S4.3 · S5 — one `docs/ledger/shipped.csv`
  row each, dated 2026-07-23; three genuine defects found pre-push in the process are recorded as
  Lessons above):** qualification verify+scale+surface (incl. the zero-evidence free-pass fix + its
  livelock follow-up), the Library graphs + hourly snapshot recorder, the criteria-calibration
  diagnostic, the quarantine schema+write step, import-time quarantine + persisted import reports,
  the duty-cycle fix (`refresh_briefing` off the pass-blocking path), memory-headroom honesty, and
  the small-defects batch. A concurrency risk (bulk job vs ride-along selecting overlapping
  candidates) was assessed low-severity/no-data-loss and DELIBERATELY not addressed, per the
  reproducer-first discipline.
  **REMAINING (the honest open board):** **S3.4** — the retroactive screening job's real execution
  against a real corpus stays GATED on the maintainer's review of S3.1's calibration report (nothing
  has run it). **S4.1 cause (ii)** — overlapping the network ride-alongs (calendar/wiki/law/
  discovery/qualification serial Tor fetches) with the next pass's fetch phase: NOT built (moving
  live network I/O across a pass boundary is materially bigger than the read-mostly briefing move).
  **S4.2** — collector write-batching, now evidence-justified, deliberately deferred (the program's
  own "riskiest hot-path change", wants the full skeptic matrix). Plus the standing quarantine
  remainder: omnibar/watches/reporting/framing exclusion (only `_query_articles` is gated today),
  the "clear junk keywords via re-index" step, and any frontend results-screen UI. Every frontend
  slice above is BROWSER-UNVERIFIED per fork-3/Q6a — a click-through is owed. The duty-cycle fix
  ships the MECHANISM only; **no duty-cycle percentage is claimed** — the operator bench is the
  measurement.
- **FIELD FEEDBACK 2026-07-24 — eight impressions (language detection · Governments/law ·
  imports · Library graphs · Home Alerts · DB-IP attribution · the vLLM/AI-stack rework;
  maintainer; INTAKE + INVESTIGATION this session, code-verified against main@25dcb19 via a
  6-agent read-only fan-out; numbered questions put to the maintainer, ANSWERS PENDING — record
  them here when they arrive; the future build is planned for an autonomous Sonnet-5 session):**
  (1) **LANGUAGE DETECTION STOPS — ROOT-CAUSED:** the continuous run is a non-persisted
  `BackgroundJob` (`src/api/ai.py:449-516`) whose loop BREAKS on the first `LLMUnavailable` —
  and `OllamaClient.generate` maps ANY `httpx.HTTPError` INCLUDING the 120 s per-call timeout to
  `LLMUnavailable` (`src/llm/ollama.py:307-308`), which `detect_for_articles` treats as a hard
  abort (`langdetect_llm.py:184-191`) → over a 50k backlog the first transient
  timeout/model-reload ends the whole run in a benign-looking "done" (no error state, no
  resume). Fix shape: retry-with-backoff on transient LLM errors (never abort-to-done), a
  persisted cursor, task-manager visibility kept. UI RULED: drop the "Keep going until none are
  left" checkbox (`index.html:1345`) — ONE button toggling start ↔ "detection ongoing, click to
  stop". (2) **GOVERNMENTS COUNTRY DATA IS STILL MANUAL — CONFIRMED:** the 2026-07-08 Item-4
  auto-load remains ⏭ deferred; ALL country data hangs on the user clicking `load-standard`
  (`src/api/governments.py:202`; the scheduler never calls it; `stats/subscriptions.refresh_due`
  only replays PREVIOUSLY-fetched series). RULED: automatic background acquisition like article
  scraping — build = seed the standard World-Bank indicator load as a freshness-gated scheduler
  ride-along inside the online-consent envelope (the stats-vintage precedent). The map-over-time
  substrate already exists (`/api/governments/map` carries a `years` list; 12-indicator catalog
  incl. Gini/GDP, vintaged). (3) **LAW COVERAGE — CONFIRMED tiny:** ~23 trackable docs across ~8
  jurisdictions (17 curated + 6 verified generated); the 225 generated legal sources register
  Source rows only (no rss_url, no LawDocument); enumeration ADAPTERS (law brief S6) are NOT
  built — they are the lever; add-by-URL + the coverage diagnostic DID ship. Maintainer wants:
  at least every country whose government uses a UI language, aggregate figures/indices/law/
  revisions per country, AI summaries of tracked law changes per country, and the
  gini/GDP-through-time map. OPEN: the standing act-vs-per-article GRANULARITY ruling (asked
  again), adapter-first vs breadth-first priority, auto-vs-on-demand AI change summaries.
  (4) **IMPORTS SLOW + PROGRESS WRONG — CONFIRMED, measured shape:** 7 stages; ONLY the 14-step
  merge + the re-index report progress (decrypt/snapshot/verify/swap/post-steps are silent; the
  sync REST restore path wires NO callbacks at all — `src/api/backup_v2.py:164,215,290`); ZERO
  per-stage timing exists on the import side (export has wall_s/gate_held_s); only the re-index
  CPU half is parallel (`reindex_parallel.py`), the merge + DB-apply are single-threaded
  single-connection SQLCipher. Plan: instrument per-stage timings FIRST (fold into the persisted
  S3.3 import report), fix the progress bar across all stages + the sync path, THEN optimize the
  measured biggest stage (candidates: parallel volume decrypt; write-batched re-index apply).
  (5) **LIBRARY GRAPHS:** RULED — denser/richer series, HIDE flat-zero tiles (with a one-line
  "no data yet", never blank-and-silent), + a Source-qualification 3-line graph. Verified: no
  hide-when-flat logic exists (`dashChartSvg` renders all-zero series); qualification counts are
  NOT snapshot metrics (`snapshots.py:45-53` is plain COUNT(*) tables — filtered metrics need a
  new code path + ALL_METRICS/metric_history/library.py registration); the small tile renderer
  is SINGLE-series (multi-line needs an ooChart-based tile; the enlarge modal already does
  multi-series). OPEN: the 3-line mapping (statuses are qualified/disqualified/never-judged +
  42k DISABLED candidates — which three lines?). (6) **HOME ALERTS:** dates ARE stored but never
  rendered (`app.js:2275-2280`); magnitude/lat/lon are captured (USGS/GDACS,
  `src/hazards/parse.py`) but DROPPED by `compute_alerts` (`alerts.py:110-119`); hazards are an
  ephemeral snapshot, NOT Articles (no internal reader view exists). Map rings = HIGHLY feasible:
  the ooMap signals layer already age-fades (`app.js:13348`) + has click-detail +
  "find coverage"; `timemap.py`'s hazard signals already carry magnitude; gaps = the stories
  lens doesn't request hazards + that path live-fetches (should feed from the LOCAL snapshot).
  OPEN: hazard detail = local view vs ingest-as-Articles; Home section becomes map-linked strip
  vs improved list. (7) **DB-IP ATTRIBUTION — ANSWERED, not a commercial:** the line is the
  CC BY 4.0 license condition of the bundled offline DB-IP Lite dataset; IPs have NO inherent
  geography (registry-allocation mappings must be maintained by someone); alternative = deriving
  country-level tables from RIR delegation files (no attribution, city-level lost) — keep-vs-
  switch asked. (8) **vLLM / AI-STACK RULINGS RECEIVED (recorded; build pending answers):**
  switch/extend the LLM backend toward vLLM for CONCURRENT requests; DEFAULT MODEL = Mistral 7B
  (maintainer-decided); top-bar pill renamed to just "AI" green/red (NO model count); click-when-
  red offers install/start, default-model download rides the task manager; context-size
  management auto-tuned to hardware+model; MORE AI-augmented diagnostics (stoplist-candidate
  detection, source-qualification assist); the triage + source-tag "real runs" lose their
  numeric inputs → an on/off TOGGLE running progressively across ALL keywords/sources in the
  background, logs downloadable for the Claude-verification chain. INVESTIGATION FACTS: the
  "airplane mode is engaged" failure the maintainer hit is NOT the client — loopback generate is
  already allowed under airplane (`ollama.py:202-224`); it is TWO endpoint-level blanket
  `kill_switch_active()` refusals (`diagnostics.py:3893/:4028`, the documented pending L3 gate
  split) — a small fix INDEPENDENT of any backend swap. The entire inference surface sits behind
  ONE seam (`OllamaClient`: generate/list/is_available + LLMError/LLMUnavailable) → an
  OpenAI-compatible dual-backend abstraction is clean; Ollama-only features (pull/remove/binary
  installer/model-store backup) don't map to vLLM. FLAGGED CONCERN (honesty, pending the
  maintainer's answer): vLLM is GPU-first — on the CPU-only fleet (2-core/3.2 GB, 4-core Qubes
  VMs) it is effectively not viable, and Mistral-7B under vLLM wants a real GPU (~8 GB VRAM
  AWQ / ~15 GB fp16), while even Ollama's mistral:7b Q4 (~4.4 GB) exceeds the 3.2 GB box —
  recommendation put to the maintainer = DUAL backend over the OpenAI-compatible /v1 surface
  (vLLM when present → concurrency on; Ollama otherwise; hardware-aware default-model fallback),
  never a silent replacement; vLLM install = its own venv/external process (torch is BANNED from
  core) + HF-weights download, both consented task-manager jobs. NOTHING BUILT this session —
  intake, investigation, ledger recording and the question list only.
  **ANSWERS RECEIVED + RULED same day (maintainer answered all 16 questions; briefs of record =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_A_FIELD_FIXES.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_A_FIELD_FIXES.md)
  + [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_B_AI_STACK.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_B_AI_STACK.md);
  sequencing RULED A then B, both autonomous Sonnet-5 CLI sessions, draft-PR-only):**
  • **A1 (lang detect):** auto-start DEFAULT-ON (a ride-along that keeps detection running
    whenever the AI backend is up and unknown-language articles exist) + the resilient
    retry-with-backoff job (never abort-to-done) + the single toggle button (checkbox dropped).
  • **A2 (governments):** the auto-load ride-along is confirmed AND the World-Bank indicator
    catalog must be EXTENDED "with as many items as possible" — every id a real WB series id,
    live-verified where egress allows, else flagged believed-correct + fail-loudly (never
    fabricated; the FRED-id precedent).
  • **A3 (law granularity RULED):** act/code-level LawDocuments by default; per-legal-article
    rows ONLY for structured bulk sources that pre-split (the LEGI class).
  • **A4 (law priority):** adapter-first (option a — legislation.gov.uk · gesetze-im-internet ·
    EUR-Lex, complete-enumeration per jurisdiction); breadth-first (b) MARKED for later
    implementation (ROADMAP row, not dropped).
  • **A5 (AI law-change summaries):** AUTO at track time for UI-language-floor jurisdictions,
    on-demand elsewhere, always labeled "AI-derived · unreliable".
  • **A6 (imports):** the instrument-first plan is approved AND an import OWNS THE MACHINE
    while it runs (all cores, enlarged cache, collection paused — disclosed).
  • **A7 (qualification graph):** FOUR lines (qualified · disqualified · never-yet-judged ·
    disabled candidates). Scale disparity: the maintainer floated multi-axis OR auto-log;
    RESOLVED toward AUTO-LOG (labeled) on ONE shared axis — all four lines share one unit
    (source counts), and the honest-viz research's dual-axis REJECTION stands for same-unit
    series (ooChart `opts.logY` already exists); log engages automatically on large spread,
    always labeled.
  • **A8 (library windows):** per-tile small window switcher (7d/30d/90d/all); all tiles START
    on the identical default window; full hourly resolution kept (invariant #16).
  • **A9 (hazards RULED = option b):** hazards are INGESTED AS ARTICLES — rich provider-asserted
    metadata (magnitude/coords/time/severity), keyword processing via `index_article`, a
    distinct HAZARD provenance class, per-provider synthetic sources, dedup by provider event
    id; the map rings + composed-search follow.
  • **A10 (Home Alerts):** a COMPACT STRIP deep-linking to the World map — "think of the UI,
    make it beautiful" (maintainer click-through owed per fork-3).
  • **A11 (DB-IP):** KEEP the bundled DB-IP Lite + its CC BY 4.0 attribution line.
  • **A12 (hardware truth answered):** the app ALREADY runs on a GPU-enabled VM — 8 GB VRAM +
    up to 40 GB RAM; `mistral:7b` measured 5.1 GB VRAM with ~2 GB spare. RULED: DUAL BACKEND,
    selected by HARDWARE DETECTION — vLLM on GPU machines, Ollama KEPT for CPU-only.
  • **A13:** Mistral-7B default where it fits + the disclosed hardware-aware fallback — OK.
  • **A14:** vLLM in its OWN venv/external process (torch stays banned from core) + HF-weights
    default-model download, both consented task-manager jobs — OK.
  • **A15:** ALL confirmed (pill "AI" green/red no count · click-red starts the preferred
    installed backend, vLLM first · triage/tag runs become on/off toggles running progressively
    across ALL keywords/sources with persisted cursors · the airplane-gate split fix · the LLM
    propose-only source-qualification assist) **+ ONE NEW ASK: AI-augmented article METADATA
    extraction — dates/events/locations and when/where/who.** This ACTIVATES the standing
    LLM-PERCEPTION track and its eval-first ruling APPLIES UNCHANGED: the S6.5 perception eval
    harness is already shipped, so the executing session runs the active default model through
    it FIRST and reports per-language/per-stratum precision/recall/HALLUCINATION (no composite);
    extraction ships as AI-layer candidates only (typed `ai_keyword` rows, model+prompt
    provenance, "AI-derived · unreliable", confirm-within-lens), NEVER the trusted index; a
    stratum the model fails stays disabled with the honest report — never a fabricated
    capability.
  • **A16 (sequencing):** Session A first (it carries the airplane-gate fix that unblocks the
    triage/tag runs on Ollama immediately), then Session B.

  **SESSION B EXECUTED 2026-07-24 (branch `claude/session-b-implementation-rqcdr8`, one draft PR
  onto `main`, B1–B7 all shipped; per-slice detail = the shipped.csv rows):** B1 the structural
  `LlmBackend` protocol + `VllmClient` (OpenAI-compatible) + `resolve_backend()` (GPU+installed+
  running vLLM → vLLM, else Ollama, disclosed reason, never silent) · B2 the vLLM lifecycle
  (managed venv, detect/start/stop, the consented install job, `compute_server_args` context
  auto-tune from detected VRAM) · B3 the bounded `run_concurrent`/`concurrency_for` seam (vLLM
  N-way, Ollama serial-by-default), adopted by bulk summarize/translate + the continuous
  langdetect job + (backend-resolution only) law-change summaries · B4 the "AI" pill (green/red,
  no count) + the backend/vLLM management endpoints + Settings → AI backend panel · B5 the
  keyword-triage/source-tags runs become ON/OFF progressive-sweep toggles (keyset-paginated
  cursors, a persisted JSON cursor surviving cancel/crash/restart, honest outage-pauses) · **B6
  (the NEW ask) — AI-augmented who/where/when EXTRACTION, eval-gated:** the harness (S6.5,
  already shipped) now runs against the REAL active model via a new constrained adapter
  (`src/ai_layer/perception.py`) + is persisted as a dated gate-evidence artifact
  (`perception_job.py`, `POST/GET /api/diagnostics/perception-eval-live{,/last}`); the actual
  per-article extraction (`perception_extract.py`/`perception_extract_job.py`) is a NEW B5-chassis
  progressive toggle (`/api/diagnostics/perception-extract/{run,status,cancel,last,download,gate}`)
  writing ONLY `ai_keyword` candidates under kinds `ai-who`/`ai-place`/`ai-date` — a DELIBERATE,
  DOCUMENTED deviation from the brief's illustrative kind list (`ai-person`/`ai-org`/`ai-event`):
  WHO stays ONE combined persons-AND-orgs kind (matching the harness's own `_FIELDS` shape and the
  standing ruling's own "WHO — persons AND orgs, the DOJ is a who" framing — splitting it would
  fabricate a distinction the extraction never determined), and `ai-event` is NOT built (the
  standing ruling excludes "what"/events from LLM-perception scope, restated in the very same
  brief section that lists it as an "e.g."). A language/field that fails the harness's
  hallucination-rate floor (`MAX_HALLUCINATION_RATE=0.5`, named+documented) — OR is simply ABSENT
  from the last report ("never evaluated") — is honestly GATED, never attempted; a fix mid-build
  ensured an outage PARTWAY through a batch never advances the cursor past unattempted articles
  (the abort-cursor fix — a genuine defect caught before it shipped, pinned by a dedicated
  regression test). Never touches `article_mentioned_dates`/`_places`/`article_entities` (a repo
  invariant + dedicated negative-space tests pin this). **B7** — the `ai` diagnostics member
  (`src/monitoring/ai_diagnostics.py`, `GET /api/diagnostics/ai`, rides the all-diagnostics bundle):
  backend/GPU facts, active model, context settings for BOTH backends (vLLM's `compute_server_args`
  when installed; Ollama's is a bare STATIC setting — **B2's own scoped RAM-derived `num_ctx`
  auto-tune for Ollama was NEVER BUILT, a genuine gap found during B7's own investigation and
  stated HONESTLY in the payload itself, never silently omitted**), and every AI job's last saved
  summary — secret-safe (each section degrades independently, never crashes the bundle). Plus the
  propose-only qualification-ASSIST (`src/ai_layer/qualification_assist.py`,
  `POST /api/diagnostics/qualification-assist/run` + `/last` + a selftest): a constrained
  one-word article/junk classifier with fixed canaries over a source's STORED (trial-fetch)
  articles, NEVER touching `Source.status`/`Source.tags` — a proposal beside the auditor's own
  evidence, composing with (never replacing) the qualification lifecycle; the same
  ai-proposed·claude-verified·maintainer-merged provenance chain the §8 triage/source-tags runs
  established. CARRY-OVERS (stated honestly, not silently dropped): (a) B2/B3's GPU-path live
  validation — this sandbox has no GPU, so vLLM start/generate/concurrency are fixture/stub-tested
  only, never claimed live-verified; the maintainer's GPU-equipped VM is the real validation gate.
  (b) every frontend slice (the AI pill, the B5/B6 toggle buttons, the language-gate preview) is
  node-checked + invariant-guarded but BROWSER-UNVERIFIED — a click-through is owed (fork-3/Q6a).
  (c) qualification-assist has NO dedicated frontend trigger yet (reachable via the API/diagnostics
  bundle only) — its natural home is a per-source button inside the source-management UI, a
  follow-up. (d) the Ollama `num_ctx` RAM-auto-tune gap (above) is a small, well-scoped follow-up
  mirroring `compute_server_args`. Full test suite green (py3.13 venv), ruff F/B clean, mypy
  ratchet unchanged (127≤127), bandit clean, i18n 100% (2130/2130 ×12, no new frontend keys — the
  new panels follow the established un-keyed-diagnostics-panel convention).
- **SCRAPING/DOWNLOAD 10× SCALING — FIVE TACTICAL STRATEGIES (maintainer-asked 2026-07-24,
  planning-only; plan of record =
  [`docs/design/SCRAPING_10X_SCALING_STRATEGIES_2026-07-24.md`](docs/design/SCRAPING_10X_SCALING_STRATEGIES_2026-07-24.md);
  builds PENDING):** a code-verified engine recon (4-agent fan-out, load-bearing claims
  hand-re-verified) + the ≥10× decomposition `stored/day ≈ OFFER × DRAIN × DUTY` grounded in the
  two 2026-07-23 field exports. THE FIVE: **S-A** supply-side scaling through the qualification
  membrane (digest the 42.6–66.7k candidate backlog at hardware-aware budgets + operator catalog
  runs + newsletter links; offer ×5–10 est. = the dominant term) · **S-B** continuous pipelined
  collection (a dedicated housekeeping LANE for the ~7 serial network ride-alongs, scheduled by
  the shipped-but-unwired `KindLadder` = finally implements the 2026-06-13 bandwidth-priority-
  ladder ruling; then pass overlap → a due-queue; duty 48→90%+ ≈ ×1.5–2 measured basis) · **S-C**
  transport parallelism at unchanged per-host courtesy (skip the per-fetch LOCAL `getaddrinfo`
  when proxied — also closes a DNS-metadata exposure; hardware-aware w_max; an opt-in operator-run
  SOCKS/Tor endpoint POOL sharded per host; wire `rank_mirrors` + `plan_segments`/`reassemble`
  for segmented multi-circuit bulk downloads) · **S-D** extraction-out-of-the-gate (verified:
  `_flush_batched` holds the ONE gate window ACROSS per-article `index_article` CPU extraction —
  the fast box's writer-bound mechanism; stage-then-gate + the proven `reindex_parallel`
  process-pool precompute shape; EVIDENCE-GATED on writer-bound verdicts at the new offer, full
  skeptic matrix) · **S-E** bulk/structured acquisition (SITEMAP support — currently ZERO, the
  `Source.sitemap_url` column is dormant and the crawler skips `.xml`; new-URL discovery + the
  qualification trial channel for the FEEDLESS candidate majority — `trial_fetch` is RSS-only so
  most of the backlog is unqualifiable without it — + bounded archive BACKFILL for newly
  qualified sources as a managed ladder-rung job; full-content-feed use; bulk/API-first per
  vertical). FOUR NEW RECON FINDINGS recorded in the doc §1: collector write-batching is ALREADY
  LIVE (`ArticleBatch`, commit batch 8 — the ledger's "S4.2 outstanding" framing was partially
  stale; the real remaining lever is extraction-in-gate) · the per-fetch local DNS resolve when
  proxied (`_guard_target`, `src/ingest/__init__.py:579` + redirect hops) · the RSS-only
  qualification-trial structural limit · the unwired KindLadder. §5 pins the NON-OPTIONS
  (politeness/robots/UA untouchable; no evasion; no third-party proxy meshes/scraping APIs; no
  headless fleet; no fabricated multipliers — every projection is an estimate until the
  8-core/20 GB before/after bench measures it). §6 = 5 open maintainer rulings (backfill default
  posture · proxy-pool surface now vs Stem later · full-content-feed storage · sitemap trial
  evidence counts · budgets ride power profiles). Sequencing (§4): S-B lane first (unblocks
  S-A's trial throughput), S-A digestion + operator runs, S-E sitemap core, S-C small slices,
  S-D last evidence-gated. Composes with the 2026-07-23 workflow brief (S4 series) + the
  2026-07-24 Session A/B briefs; NOTHING built this session.
  **EXTENDED same day (maintainer: "add all of them to the PR in a coherent fashion so the coding
  tasks can well be delegated to a smaller Sonnet 5 model without hiccups. Crawling should be
  activated by default"):** the strategy doc gained (a) **§7 SECOND-TIER ACCELERATORS** — beyond the
  five: A1 decouple ingestion from enrichment (store fast + a separate enrichment lane; largest, last)
  · A2 in-memory dedup front [NOW, ~90% dup rate → skip codec reads; negative-space "never a false
  negative"] · A3 bulk mention insert [NOW, `store.py:321-336` per-term ORM → Core insert; counter
  math byte-identical] · A4 shrink per-worker memory footprint [NOW, small-box mem-low floor] · A5
  persist robots/DNS caches across restarts · A6 clearnet DNS cache · the verified DB baseline (WAL +
  synchronous=NORMAL already fast — no PRAGMA free lunch) · already-ruled page_size/cache_size restated
  · honest NON-levers (HTTP/2 buys nothing under the per-host cap; more workers past the supply
  ceiling; synchronous<NORMAL); (b) **§8 CRAWL-BY-DEFAULT (maintainer-ruled)** — ON by default as a
  HYBRID BUDGETED RUNG, explicitly NOT a mode flip (flipping `mode="rss"→"crawl"` would abandon
  conditional-GET feed economics + blow up pass time, violating bounded-pass + cover-everything; the
  rejected alternative is recorded): additive `crawl_supplement: bool = True` + `crawl_per_pass` budget
  mirroring the `world_discovery_per_pass` ride-along pattern (`settings.py:90-103`), a bounded crawl
  sub-pass after RSS over least-recently-crawled + feedless-first sources (a new `Source.last_crawled_at`
  marker), the lowest KindLadder rung so it never starves RSS, `crawl_source` through the ONE fetcher
  (robots/politeness unchanged by construction), complements S-E (sitemap preferred, crawl the fallback);
  (c) **§6 rulings ADOPTED as revertible spec defaults** (unblock the executing session; code lands as
  draft PRs the maintainer reviews): a=bounded auto-backfill ~100–500 pages + consent for full history,
  b=operator-run SOCKS list now / Stem later, c=full-content feeds used-with-disclosure, d=sitemap trial
  evidence counts toward qualification, e=budgets ride the power-profile knob table; (d) **§9 EXECUTION**
  pointing at the companion brief. THE COMPANION BRIEF =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_C_THROUGHPUT_SCALING.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_C_THROUGHPUT_SCALING.md)
  — the Sonnet-executable HOW: 17 ordered slices (C1–C17) across 4 phases, each with exact files/anchors/
  setting names/test names/invariant guards + the verified CI gate commands (ruff F/B, mypy 127 ratchet,
  bandit 1.9.4, i18n --min 100, alembic random-revision-id/heads), the skeptic-before-push + mandatory
  negative-space lens on every ⚠ slice (crawl rung, sitemap parser, DNS-guard change, dedup front, bulk
  insert, S-D, A1), the staleness guard, draft-PR-only, the ethics non-options as hard fences, and the
  operator-gated items (C6 catalog runs). Phase order: 1 duty-cycle+crawl-default+cache-persistence ·
  2 supply (qualification budgets + sitemap core) · 3 transport (DNS-when-proxied + ceilings + proxy
  pool + segmented downloads) · 4 processing ceilings (dedup front, bulk insert, memory footprint,
  backfill, then S-D evidence-gated + A1 last). Sonnet sessions branch `claude/oos-c-*`. Still
  planning-only in THIS PR (#766) — no engine code; the C-slices are the executing sessions' work.
- **LOCAL INFERENCE IS GATED ON HARDWARE SUITABILITY (maintainer RULED 2026-07-30, verbatim: "Using
  vLLM or Ollama on <8GB RAM, GPU-less laptops is impractical, it's ok to limit them. This is only for
  my GPU enabled machine (by GPU, I mean dedicated GPU, not the integrated ones we find on most CPUs
  nowadays, and I exclude from this reasoning the sorts of Mac minis having dual-use memory that is
  precisely good at inference, this is another matter)"; SHIPPED same day — shipped.csv row
  "llm/hardware", branch `claude/inference-hardware-gate`):** AI features DEFAULT OFF where a local LLM
  cannot practically run. **THE INVARIANT THAT MUST NOT BE UNDONE — TWO PREDICATES, NEVER ONE:**
  `detect_gpu()` answers "can vLLM run HERE?" (CUDA/nvidia-smi) and is read by 8+ vLLM-gating call
  sites; the NEW `inference_capability()` answers "is local inference PRACTICAL at all?" and composes
  `detect_gpu()` with a new `detect_apple_silicon()`. **vLLM ships manylinux wheels ONLY and does not
  run on Apple Metal, so teaching `detect_gpu()` to return True on Apple Silicon — the obvious way to
  implement the carve-out — routes every Mac to a vLLM that cannot serve it.** Apple Silicon is
  inference-PRACTICAL and vLLM-INCAPABLE simultaneously; only two predicates state both. Pinned by
  `tests/test_inference_hardware_gate.py` (a behavioural pin + an ast guard that no OS/arch policy
  enters `detect_gpu()`'s body, stash-verified to redden on exactly that edit). POLICY: dedicated
  NVIDIA GPU → practical · Apple Silicon ≥ `APPLE_SILICON_MIN_UNIFIED_RAM_GB` (16.0, a named constant
  whose comment states the reasoning AND that it is a judgement, not a benchmark we ran) → practical ·
  everything else → NOT, **regardless of RAM** (the ruling is about GPU ABSENCE; a test pins that a
  256 GB GPU-less box still refuses, so the gate cannot decay into a RAM check). **NEVER A HARD BLOCK:**
  the Settings toggle `llm_allow_impractical_hw` / `OO_LLM_ALLOW_IMPRACTICAL_HW=1` turns it back on,
  the verdict then reports `overridden: true` and the disclosure still renders — neither direction is
  silent. THIRD STATE IS EPISTEMIC: unreadable unified RAM refuses naming the UNMEASURED memory and
  deliberately NOT "below" (a pass on an absent measurement = fabricated capability; a claimed
  shortfall = fabricated measurement). AMD/Intel discrete GPUs stay an HONEST GAP (not probed — said in
  the caveat and in the refusal, which points a Radeon owner at the override); never fabricate
  detection for them. **WORDING (binding): NEVER state a hardware-DAMAGE claim** — the rationale
  mentions heat damaging hardware, but modern CPUs thermal-throttle rather than damage themselves, so
  the shipped strings assert only the substantiable half ("impractically slow, saturate every core for
  hours, and run the machine into sustained thermal throttling"), guarded by a BEHAVIOURAL test over
  the emitted strings (a source grep would forbid the comments explaining the absence and still miss an
  inline f-string). Gated today: the background langdetect ride-along (the MANUAL button stays ungated —
  an operator asking for a bounded run is a choice, not an imposed cost). REMAINING: extend the gate to
  the other unattended AI sweeps (triage / source-tags / perception-extract) if the maintainer wants
  them default-off too; the frontend (pill third state + Settings disclosure/toggle) is
  BROWSER-UNVERIFIED per fork-3.
- **MODEL WEIGHTS ARE THE ONE DOWNLOADED ARTIFACT WITH NO PIN (finding, 2026-08-05, from the
  operator's own vLLM provisioning scripts; NOT built — recorded so it is not rediscovered):**
  the scripts fetch weights at a full 40-char commit SHA and write a `sha256sum` manifest that
  every later run verifies, refusing a tag-shaped revision outright. This app downloads by REPO
  ID at whatever `main` points to, with no integrity check — so the bytes can change under an
  operator between two installs and nothing would say so. That is a gap in HOUSE DOCTRINE, not
  a new idea: the DuckDB httpfs extension is SHA-pinned and verified before every `LOAD`, the
  Ollama installer verifies against GitHub's own attested `digest: sha256:…` and REFUSES when
  no digest is attested, and the external-artifact registry exists precisely for "anything
  externally sourced gets an entry in the same commit". Weights escape all three. WHAT A BUILD
  WOULD NEED, honestly: HF revisions are resolvable to a commit SHA and `huggingface_hub`
  accepts `revision=`, so the pin itself is cheap — the work is deciding where the pin lives
  (a registry entry per roster model, dated) and what a MISMATCH does (refuse, per the
  no-fabricated-security rule, with the operator able to re-pin deliberately). NOT adopted
  from the same scripts, with reasons: `--max-num-seqs` (the app already bounds concurrency
  client-side at `OO_VLLM_CONCURRENCY`, and a server-side cap kept in sync with a client-side
  one is two copies of one decision — the recorded "a value only meaningful beside another
  must travel WITH it" trap); a compute-capability ≥7.5 preflight (real, but `detect_gpu()`
  already gates on CUDA and the failure it prevents is loud); a per-launch `--api-key` on a
  loopback socket (defence against a local process that could read the token file anyway).
  - **A PROBE OF THE PORT IS NOT A PROBE OF THE MODEL — and the fix for that creates
    its exact mirror one line later (2026-08-10, the deep bench that measured one of
    seven models):** `arbitration._is_ready("vllm")` asked whether the server ANSWERS.
    A vLLM serves exactly one model per server, so a server holding model A answers
    perfectly while being useless for B — and the caller's next move was to send B's
    work to it. Compounding it, `_start` called `vllm_lifecycle.stop()` and **discarded
    the result**, so a refused stop (a server this app did not spawn) fell straight
    into `start()`, whose `"already running"` is `process_alive() or is_running()` —
    another word about a PROCESS standing in for a fact about a MODEL. Six of seven
    pairs recorded five task errors each and the run called itself `complete`. THE
    HONESTY LAYER IS WHY THIS WAS DIAGNOSABLE AT ALL: `VllmClient` refuses a model its
    server was not started with, so the field report contained six honest refusals
    rather than model A's answers filed under six other names — a wrong measurement no
    reader could ever have detected. FOUR RULES. (a) When a resource serves ONE thing
    at a time, readiness must name the thing, not the socket. (b) An action whose
    success is load-bearing must have its answer read; if you are about to ignore a
    return value, ask what the next line assumes. (c) **Fixing (a) alone produces the
    fabricated-failure mirror**: `vllm_lifecycle.start()` returns at spawn ("poll
    is_running() before use"), so a one-shot probe immediately after a restart reads
    not-ready for a healthy 60–90s model load — the wait has to land in the same
    change, bounded, and abandoned the moment the tri-state says `exited`. (d) A wait
    that outlives a cancel must SAY what it is waiting for; shortening it would have
    left the operator's machine serving a backend they did not choose, which is worse
    than a minute of explained delay. **THE THIRD DEFECT, found by replaying the field
    conditions against the fix rather than by reading:** `vllm_lifecycle.stop()` has two
    paths, and only one of them waited for the PORT. The adopted path polls until
    nothing answers and says why in a comment — *"a SIGTERM that has been sent is not
    memory that has been released"* — while the tracked path returned the instant
    `proc.wait()` reaped the parent. vLLM runs its engine in CHILD processes, so the
    parent can be gone while the server still answers and still holds the card; the
    caller's next move is `start()`, which reads "already running" and keeps serving the
    old model. That fits the field timing exactly (every switch completed in about a
    second, where a real restart is 60–90s). GENERAL FORM: when one function has two
    paths to the same outcome, the guarantee has to live in a shared helper — an
    invariant implemented in one branch and merely *commented* in the other will be
    reintroduced by whoever reads only the branch they are in. And a stop that was
    performed but did not TAKE (`port_quiet: False`) has to be treated by the caller
    exactly like a refusal, because for the caller it is one. **AND THE RECURRENCE, in
    the same module, while that sentence was being written:** `release_backend("vllm")`
    — the path used when handing the card to OLLAMA rather than switching vLLM's model —
    still read `stopped` alone, so it reported `released: True` while vLLM held the
    memory. Fixing a property in one place is not fixing it; grep the module for every
    other reader of the same field before calling it done.
  - **A BACKEND NOBODY STARTED READS AS A BACKEND THAT CANNOT SERVE (same run):** every
    Ollama pair was dropped as `backend-unreachable` while Ollama was installed,
    launchable, and holding the models the operator had pulled — the probe asked a
    daemon that was simply not running. The question "what can this backend serve"
    needs no GPU, so it can be answered by WAKING the daemon first; the question "can
    it serve it NOW" is the handover, and stays per-pair. Separating the two is what
    makes a one-run comparison of two backends possible at all. Gate the wake on the
    same `OO_LLM_AUTOSTART=0` every other automatic start honours — a deliberate click
    is not a reason to ignore an operator who said never start a backend behind my
    back, and it is also what stops a test run leaving a daemon behind. COROLLARY on a
    guard that repairs nothing: the pair ordering was grouped by backend to save a
    handover, and `resolve_pairs` turned out to already emit grouped output because it
    iterates `sorted(installed_by_backend)`. Kept as a stated GUARD with its own test
    driven by an interleaved list — an end-to-end assertion alone would have passed
    with the helper deleted — and the docstring says outright that it repairs nothing
    today, because a no-op that reads like a fix is worse than no fix.
  - **A TUNABLE IS ONLY TUNABLE WHERE ITS VALUE REACHES THE LOOP THAT SPENDS IT
    (2026-08-09, "I see my GPU working only 20%"):** `concurrency_for()` was read in two
    honest places — the coordinator's turn-level overlap, and `--max-num-seqs` at server
    start — and in neither did it reach the call site. Turn overlap parallelises across
    MEMBERS, so it caps at the number of enabled sweeps (three); and each member then ran
    its own items serially, because none of the three closures in `_member_specs()` passed
    `max_workers` and `run_progressive_perception_extract_job`'s default is 1. So at most
    three sequences ever reached vLLM, whose entire advantage is continuous batching, and
    the knob whose own docstring says *"the operator can measure and override"* could not
    be overridden where it mattered. GENERAL FORM: after wiring a tunable, grep for the
    site that SPENDS it, not the sites that compute or forward it — this is the recorded
    "a diagnostic state with no caller in the decision path is a dead end" lesson applied
    to a configuration value, and it hides better, because every intermediate read looks
    correct in isolation. TWO DESIGN POINTS from the fix. (a) Do not divide a budget
    evenly across consumers that spend it differently: a member whose call already carries
    a whole batch (25 keywords, a page of domains) costs ONE sequence however many workers
    you hand it, so the per-item member gets the REMAINDER and the lane's total matches the
    number the server was started from. (b) Mark which consumer can spend it
    (`per_item_concurrency`) rather than passing the argument to all of them — an argument
    a callee silently ignores is what later reads as a bug, and the flag is also the thing
    a test can pin against the SHIPPED registry. And do NOT invent a replacement default in
    the same change: the old one is a disclosed guess by its own admission, so raising it
    without the measurement swaps one unchecked number for another.
  - **A PERFECTLY-SCALING TEST DOUBLE CANNOT TELL A MEASURED RATE FROM AN ASSUMED ONE
    (2026-08-09, the throughput sweep):** the bench exists because `budget_translation`
    computes articles/hour as `3600/p50 × concurrency` — a multiplication nobody had
    checked. Its first fixture was a client that sleeps a fixed time per call, and against
    that the measured batch rate and the assumed multiplication come out THE SAME, so the
    test passed and proved nothing about the distinction the module is for. The
    discriminating fixture is one that STOPS scaling: a semaphore capping real lanes at 2,
    where eight workers must NOT be four times the measured rate. GENERAL FORM: when a
    change replaces an assumption with a measurement, the fixture has to be one where the
    assumption is FALSE — a well-behaved double agrees with the thing being refuted.
    COROLLARY on the same bench: a report whose published rate cannot be recomputed from
    its own published wall reads as an inconsistency, so round the wall finely enough
    (3 dp, matching the per-call figures) and assert within the rounding band computed from
    the granularity, never a magic percentage.
  - **"CHECK WHETHER THE INSTRUMENT ALREADY EXISTS" HAS A SECOND HALF: IT MAY EXIST AND
    HAVE NO READER (2026-08-09, the AI details feed):** the recorded lesson says to check
    whether existing instruments reach durable storage DURING the operation before building
    more. Here they did — triage, source-tags and perception-extract each append a
    per-batch JSONL record carrying `started_at` AND `finished_at` while the run is in
    flight, beside detail records holding the values found — and the feature was still
    missing, because `last_*_report` parses a header, a footer and a line count and the
    only other route to the details was downloading the whole log. So the answer was a
    bounded tail READER, not a fifth recorder. THREE THINGS THE READER OWED. (a) Its OWN
    ceiling (seek to `size - tail_bytes`, drop the leading fragment): the writer's
    discipline is not the reader's, and a sweep left running for days writes a log whose
    size tracks how much there was to report. (b) TWO rates, because under a round-robin
    coordinator "the model's own speed" (items ÷ summed batch durations) and "what the
    corpus gains" (items ÷ elapsed span) differ by exactly the duty cycle — publishing
    either alone misleads in opposite directions, one promising a completion date the
    machine cannot keep and the other blaming the model for the scheduler. (c) The item
    UNIT per sweep (keywords / sources / articles), so a headline total is taken only over
    rows that share one unit. EMPIRICAL FACT worth keeping: the coordinator calls each
    member's job FUNCTION directly rather than through its registered `BackgroundJob`, so
    while the lane drives a sweep that sweep's own status endpoint reports `idle` with no
    result — any UI built on the per-sweep status surfaces is blank in the normal case, and
    a busy machine reads as a stopped one unless that is stated.
  - **TWO PANELS RENDERED UNCONDITIONALLY, ONE STRUCTURALLY INERT, AND THE INERT ONE FIRST
    (2026-08-09, "downloading other models for benchmark doesn't seem to work"):**
    `refreshAiPanels` drew both bench rosters on every machine, and `index.html` puts the
    Ollama host ABOVE the vLLM one — so on a GPU box with Ollama absent the FIRST panel with
    that heading was the one whose button is disabled. Ticking models in it did nothing,
    which is the entire report. The defect is not the disabled button (that is honest); it
    is drawing a surface that can never act, ABOVE the one that can. RULE: a panel for a
    capability this machine cannot exercise is not a disclosure, it is a decoy — draw it
    only when the backend will SERVE here (that panel carries the one honest "install it
    first" line) or is already installed. Decide it from a machine-readable FACT the
    endpoint publishes (`provisioning_backend`), never by parsing a human sentence like
    `chosen_because`. And the NEGATIVE-SPACE TWIN is the load-bearing half: a fresh machine
    has nothing installed, so the SERVING panel also carries a prerequisite and must still
    be drawn — hiding on `prerequisite` alone trades one dead end for another, and only the
    twin test catches it.
  - **A CAPABILITY BUILT SO A CALLER COULD USE IT, THAT NO CALLER EVER USED, IS THE
    DEAD-END SHAPE ONE LEVEL DOWN (2026-08-10, temperature 0):** `vllm_client` learned to
    map `options` onto OpenAI sampling fields on 2026-07-31 with a comment saying the
    previous version "dropped it on the floor, so a caller asking for `temperature: 0` got
    the server's default sampling and never learned otherwise — a silent determinism bug on
    exactly the backend the GPU path uses." The fix was correct and **no production caller
    ever passed any options**: all seven constrained-output paths called
    `generate(prompt, model=, system=, keep_alive=)` and nothing else, so every sweep ran at
    the server's default 1.0. That is what made twelve perception-eval passes over ONE model
    and ONE gold set disagree about which languages clear the bar — a gate deciding on
    sampled coin flips. THE RULE is the recorded "a diagnostic state with no caller in the
    decision path is a dead end", applied to a CAPABILITY: after fixing a seam so callers
    *can* ask for something, grep for the callers that now *do*. TWO HONESTY POINTS the fix
    had to get right: temperature 0 does NOT reduce hallucination (a model invents just as
    freely under greedy decoding — it invents the *same thing* each time), and it does NOT
    guarantee bit-identity either, because vLLM's continuous batching changes float
    reduction order with batch composition; what it buys is that a difference between two
    runs is a difference in the INPUT or the CODE, never in the dice. And the override must
    fail toward greedy: a malformed `OO_LLM_SWEEP_TEMPERATURE` falling back to the server
    default would silently restore the thing being removed. **COROLLARY — A PROTOCOL THAT
    UNDER-DECLARES A SEAM IS WHERE THE DOUBLES DRIFT:** `LlmBackend.generate` omitted
    `options`, so 53 test doubles and 3 src stubs did too, and adding one real argument
    reddened 67 tests — every one of them describing a client that could not exist. Declare
    the full signature on the Protocol; a structural check has nothing else to bite on.
  - **A "RUN EVERYTHING" BUTTON MUST NAME WHAT IT DOES NOT RUN (2026-08-10, the one-button
    AI check):** folding the comparative model bench into "test everything at once" would
    turn a check into an afternoon (it loads every roster model in turn and is resumable per
    model precisely because it runs for hours), and leaving it out silently would make
    "everything" false. The report carries a `not_run_here` block with the name, the reason
    and where the separate control lives — the same discipline as stating a truncation in a
    payload rather than only in a log line. TWO MORE THINGS SUCH A RUNNER OWES: every step
    guarded and TIMED so a half-broken machine still says which half (a step that raises
    becomes one row with its exception, and the steps after it still measure), and a READING
    derived from what was measured rather than asserted — here, "the best measured
    concurrency is at or above the server's own limit, so raising `OO_VLLM_CONCURRENCY` and
    restarting is the lever" has a NEGATIVE-SPACE TWIN that says the opposite when
    throughput peaked BELOW the limit. A recommendation that fires in every case is advice,
    not a reading.
  - **A THRESHOLD OVER A RATIO OF TWO TIMINGS IS NOT A GUARD ON A SHARED RUNNER — FIND THE
    ARITHMETIC CLAIM UNDERNEATH IT (2026-08-10, the throughput bench's own test going red
    in a full-suite run):** the assertion was "on a saturated backend the measured rate is
    under half what latency×workers assumes", which passed alone and failed at 0.52 in the
    suite. The tempting reading is a flaky threshold; the measurement says something worse.
    Under CPU contention a **perfectly-scaling** client reads **0.047–0.101** of its own
    assumed rate — so the bar the saturated fixture was supposed to be distinguished by is
    cleared by the client it was supposed to be distinguished FROM, and the test had been
    passing for the wrong reason every time. Both sides of a ratio inflate under load, at
    rates that depend on the scheduler, so no constant separates them. THE FIX IS TO FIND
    THE LOAD-INDEPENDENT CLAIM: the real property was "the published rate is the batch's
    own arithmetic (n / wall), not p50 × workers", which is an EXACT identity over numbers
    the report already publishes (drift ≤ 2/h, pure rounding, at every load measured) and
    which a mutation to the wrong formula fails immediately. The ratio survives only as an
    anti-vacuity companion — evidence that the two formulas disagree on this fixture —
    never as the proof. AND THE CALIBRATION DIRECTION HELD: the fixture was made HARDER
    (16 workers / 32 calls instead of 8 / 16, worst ratio 0.157 under twelve competing
    spinners against a 0.5 bar) rather than the bar softer, per the recorded WAL lesson;
    the measured numbers are recorded IN the test so the next session does not re-derive
    them. GENERAL FORM: when a timing-derived guard goes red, measure what it reads for the
    case it is supposed to REJECT before touching it — if that case also passes, the guard
    never worked and tuning it would only hide that. **THE SEQUEL, one lane later: A
    ROUNDING-BAND ASSERTION MUST CARRY EVERY ROUNDING IN THE CHAIN.** The replacement
    identity derived its band from the wall's 3-dp publication and forgot that the RATE is
    published as an integer too, so a true rate of 65250.5-ish rounded UP past a bound
    computed as though it had not been rounded at all — `65251 outside [65214, 65251]` on
    the macOS observation lane, which is exactly the "investigate it before the blocking
    lane hits the same thing" role that lane exists for (the same full suite was green
    locally, so the boundary is rare, not absent). The omitted term is ~1/h against a
    ~37/h wall band — small everywhere except at the edge, which is the only place a
    boundary assertion is ever evaluated. Simulating 200,000 publishes: **4,118 false
    failures without the term, 0 with it.** When an assertion bounds a PUBLISHED number,
    enumerate every rounding between the true value and the published one and widen by
    each — and prove it by simulation rather than by re-running until it passes, since
    a 2% false-failure rate looks exactly like a flake.
  - **AN HTTP STATUS SAYS A CALL FAILED; THE RESPONSE BODY SAYS WHY — and the one line
    that converts the exception is where the answer gets thrown away (2026-08-10, five
    Ollama models, ten failures, zero information):** the first runs that ever reached
    Ollama produced nothing but `Server error '500 Internal Server Error' for url …`,
    repeated per model per run. Nothing was wrong with the call: both local backends
    answer a failure with a JSON body naming the cause, and `httpx`'s `HTTPStatusError`
    string carries only the status and the URL, so `raise LLMError(f"…: {exc}")` — which
    looks like it is passing the error through — silently drops the only part that
    diagnoses anything. RULE: wherever an exception is re-raised with a message, ask what
    the ORIGINAL carried that the new one does not; for HTTP that is always the body.
    THREE THINGS THE READER OWES: unwrap both shapes (`{"error": "…"}` and
    `{"error": {"message": "…"}}`) but keep a non-JSON body verbatim, since the server's
    own words beat a parse; BOUND it, because one runaway body should not become the
    whole log line; and degrade to the status line when the body is empty or unreadable,
    never to a dangling separator with nothing after it — the guard for that direction is
    the one worth writing, because it is what stops "read the reason" from making a
    reason-less failure WORSE than it was.
  - **"AT LEAST ONE FILE" IS NOT A COMPLETENESS CHECK — ask the loader what it requires
    (2026-08-10, a model reported downloaded that vLLM would not open):** the cache probe
    already knew the trap and said so in its own docstring — `huggingface_hub` creates the
    tree as soon as a download STARTS — and guarded it by requiring a revision directory
    with a file in it. An interrupted fetch leaves real weight files, so the guard passed
    and the server then exited on `Invalid repository ID or local directory specified …
    ensure the presence of a 'config.json'`. The correct predicate was written in the
    error the failure itself raised. GENERAL FORM: when you guard "is this artifact
    complete", do not invent a proxy for completeness (a file count, a byte floor) — find
    the consumer's own stated precondition and check THAT. Two riders: `is_file()` follows
    symlinks, which is what you want for an HF snapshot (a dangling link into a missing
    blob reads as absent); and a populated-but-unusable tree must not collapse into the
    same answer as a never-fetched one — "several GB on the disk that will not load" and
    "you never downloaded it" call for opposite actions, so the sentinel says which and
    reports the wasted bytes. The pre-existing test used `config.json` as its filename by
    coincidence and so passed either way — the discriminating fixture is files present,
    config absent.
## Shipped batch log (compressed verdicts; details in git history + named docs)
Shipped work is tracked in **[`docs/ledger/shipped.csv`](docs/ledger/shipped.csv)** (sortable: date · area · item · status · refs · key_paths · summary) — 125 entries as of 2026-06-25. The full verbatim entries are archived in [`docs/ledger/SHIPPED_LOG.md`](docs/ledger/SHIPPED_LOG.md); deeper detail is in git history + each PR + the named design docs. Load-bearing LESSONS from shipped work live in the Session-rituals 'Lessons' subsection above (read those).

**APPEND-RULE (replaces the old inline log):** record newly-shipped work as a `shipped.csv` ROW, not a CLAUDE.md bullet. Add a verbatim entry to `SHIPPED_LOG.md` only when it carries a reusable lesson/empirical fact, and copy that lesson into the Session-rituals 'Lessons' subsection. Pending rulings, contingencies, and deliberate-omissions still go in the Open queue as prose (never compressed away).
