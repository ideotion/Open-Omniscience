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

## Open queue (when maintainer says proceed)
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
- **KEYWORD-ENGINE OPTIMIZATION — RESEARCH FOLDED IN + IMPLEMENTATION STRATEGY (2026-06-26; maintainer
  ran parallel internet sessions on keyword conflation + IR/search performance; outputs analyzed
  CODE-GROUNDED + folded in; STRATEGY/DOCS-ONLY this session — the BUILD is a NEXT session):** the 3
  research reports saved VERBATIM under `docs/research/keywords/` (FOSS conflation research; the
  complete-log evidence addendum [supersedes a capped first pass — its 8.7% global mismatch was a cap
  artifact, corrected to 16.2%]; the performance-first IR/computational-journalism report) + indexed in
  `docs/research/README.md`. SYNTHESIS = `docs/design/KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md` (code-
  grounded, dependency-sequenced, build-ready; every anchor verified against the tree). KEY VERDICT
  (both research streams + the code converge — INDEPENDENTLY confirming the project's own
  DATA_ARCHITECTURE_SKELETON / SCALING_DERIVED_LAYER_1000X): the pain is a DERIVED-STATE-REBUILD problem,
  NOT a search-engine problem — KEEP the rule-based trusted index, fix the rebuild + the rollups + the
  junk, AUGMENT with a LABELLED recall layer that never feeds the trusted index. CODE-GROUNDED FINDINGS:
  (a) re-index is slow because `reindex_all_batch`/`index_article` (store.py:384/:180) force-re-extract
  EVERYTHING per article (keywords + when/where/who + sentiment) through the single writer + a SQLCipher
  per-page decrypt, via a CLIENT loop with NO persisted cursor (`_reindexAllLoop`, restart-from-0) →
  Phase 1 = a BACKEND re-index JOB (persisted cursor, reuse the NewsletterImportManager pattern) + a
  KEYWORD-ONLY re-index mode + batched commits (COLLECTOR_WRITER_BATCHING) + FTS5 `'optimize'`; (b)
  `Keyword.language` is FIRST-WRITE-WINS, never reconciled (store.py:75) = the 16% / 40%-of-head language
  mismatch → fix = a `reconcile_keyword_language` pass MIRRORING `reconcile_keyword_counters`
  (store.py:558), which GATES correct lemmatization; (c) **HIGHEST-LEVERAGE — the persisted-columnar D1
  blocker may be REMOVABLE:** `columnar.py:90 secure_crypto_available` gates on the OpenSSL `httpfs`
  binary because the OLD DuckDB mbedtls (CBC/CTR) was "NOT securely encrypted," BUT DuckDB ≥1.4 (already
  pinned) defaults to AUTHENTICATED AES-256-GCM via the native `ATTACH … ENCRYPTION_KEY` the code ALREADY
  uses (`:131/259`) + the empirical `encryption_gate` (`:111`); **VERIFY the GCM claim → relax the gate
  for the DISPOSABLE store → unblock the keyword_daily/source_coverage rollups (5A-bis) PERSISTED = the
  real perf win** (NEVER fabricate the capability — if unconfirmed, keep the in-memory fallback + the
  httpfs-binary path); (d) lemmatization (simplemma + an evidence-grown mislemma denylist + visible
  `conflated_by` provenance) belongs in `families.canonical_key` (`:104`, display-time, reversible), NOT
  `_normalize`; (e) the IR EVAL HARNESS (nDCG/MRR/Recall, pooled gold set, single-assessor-stable
  [Voorhees], conflation recall-gain-vs-precision-loss reported SEPARATELY with n) is a genuine GAP (the
  shipped self-test is keyword-QUALITY, not RETRIEVAL) and GATES every quality change; (f) the
  static-embedding hybrid (model2vec/potion numpy-only [NO torch] + sqlite-vec inside the encrypted file
  + RRF, labelled/disposable) is the one constraint-clean dense-recall layer — PILOT gated on the eval
  harness. ALREADY-SHIPPED, don't rebuild: near-dup/coordination (`src/signals/near_dup.py`), BM25-default
  ranking, the readmodel/columnar seam + the `ix_mention_date_keyword` covering index, the engine
  report/self-test/growth diagnostics. PHASED PLAN (one PR per slice when built): P1 unblock the rebuild
  → P2 rollups + the DuckDB-encryption VERIFY → P3 eval harness (parallel) → P4 keyword quality
  (`reconcile_keyword_language` → simplemma lemmatization → th segmenter URGENT / zh degraded-not-garbage)
  → P5 BM25F + facets + the static-embedding recall layer → P6 OpenTapioca entity→QID. SPLADE ruled OUT
  (CC-NonCommercial weights + torch + multilingual gap). Verify-before-build: the DuckDB-1.4 GCM claim,
  static-embedding PER-LANGUAGE quality, every bundled lib's license (CC0-first; Wiktextract CC-BY-SA =
  a separate ruling; SPLADE never bundle). Operational/networked (maintainer steps): run cleanup
  (re-index+prune) + reconcile + baseline-tag backfill on the LIVE corpus; Wikidata Lexeme/ring + a
  bundled segmenter/embedding/OpenTapioca index. **AUTONOMOUS-SESSION BRIEF to execute this end-to-end:
  `docs/design/AUTONOMOUS_SESSION_BRIEF_KEYWORD_ENGINE.md`** (reset-proof operating manual — working
  mode, verification gate, subagent orchestration, the phased scope with per-item build-class tags
  [BUILDABLE / VERIFY-FIRST / SEAM / OPERATIONAL], honesty non-negotiables, definition of done; points
  at the strategy doc for the per-item spec).
  **BUILD SESSION 2026-06-25 (autonomous, maintainer "full authority"; HARNESS = single working branch
  `claude/modest-gauss-9ae4mc`, so stacked COMMITS under ONE draft PR to `0.09`, each step verified
  end-to-end before the next — the brief's harness-fallback).** EMPIRICAL WIN vs the brief's "CI-only"
  assumption: a Python **3.13.12** venv is available here and `pip install -e ".[analysis,dev]"`
  succeeds INCLUDING `sqlcipher3` + `cryptography` + numpy/pandas/scipy — so the **real pytest suite +
  the mypy ratchet run LOCALLY** (`.venv`; mypy baseline=127, confirmed at 127). PER-ITEM STATUS (mark
  as I go): **P1.1 SHIPPED** (backend re-index JOB — `src/analytics/reindex_job.py:ReindexJobManager`
  mirrors `NewsletterImportManager`: worker thread + stop-event PAUSE + on-disk persisted CURSOR
  [`data_dir()/reindex_job.json` = last-article-id + total/done/tally/prune_after], so a re-index now
  SURVIVES a tab close / app restart and RESUMES from where it stopped instead of the old client loop's
  restart-from-0 trap; drives `reindex_all_batch`; DB-WRITER kind="reindex" joins the
  collect/import/reindex arbitration set; idempotent re-index = the no-loss net. Endpoints
  `POST /api/insights/reindex-job{,/{action}}` + `GET .../status`; surfaced in `/api/jobs`
  [`_reindex_jobs`, pause/resume routed]; the Settings "Clean up keywords" + "Re-index the whole corpus"
  buttons now START the background job + poll its status [`_startReindexJob`/`_pollReindexJob`], with
  Pause/Resume in the task manager — the legacy `_reindexAllLoop`/`_pruneCore` cores stay DEFINED as a
  fallback + for the invariant test. tests/test_reindex_job.py [6: completion · idempotent-no-loss ·
  pause+resume-from-cursor · persisted-cursor-survives-restart · prune_after-chains · idle/bad-resume] +
  test_repo_invariants::test_reindex_background_job_is_wired. VERIFIED here: 6/6 + 141 invariants +
  jobs/insights regression green, ruff F/B clean, mypy 127≤127, node --check, i18n 100%,
  audit-chrome clean. Frontend BROWSER-UNVERIFIED per fork-3.) **P1.2 SHIPPED** (keyword-only re-index
  scope — `index_article(scope="keywords")` runs the keyword pass ONLY, skipping the when/where/who
  [dates/places/entities] + sentiment passes [≈⅔ less work for a keyword cleanup]; the language
  deduction stays [it picks the stoplist]; threaded through `reindex_all_batch` → the job [persisted +
  status-reported] → `POST /reindex-job?scope=` [400 on a bad scope]; the Settings "Clean up keywords"
  button now uses keyword-only, "Re-index the whole corpus" stays full; default `scope="full"` =
  byte-identical [47-test ingest/index hot-path regression green]; tests in test_analytics_store.py +
  test_reindex_job.py + the invariant scope guard. VERIFIED here.) **P1.3 SHIPPED** (batched commits,
  COLLECTOR_WRITER_BATCHING.md — `index_article(commit=True)` primitive [False leaves the work PENDING
  for a batched commit; default True byte-identical] + `reindex_all_batch(commit_batch=1)` batches every
  N commits with the PROVEN `ingest_emails` rollback-then-redo-per-article fallback [`_redo_committed`]
  so a lock/collision/extractor-error never drops a batch-mate [idempotent re-index reproduces it]; the
  job reads `OO_REINDEX_COMMIT_BATCH` [default 1]. NO-LOSS tests: batched==per-article with counters ==
  the live GROUP BY [zero drift], the failure-fallback loses nothing, AND a contention test
  [test_write_gate_dataloss.py] — a batched re-index HOLDING the gate across a batch races concurrent
  ingest with ZERO locks/loss + exact sentinel counters. **DECISION (autonomous, recorded): the
  COLLECTOR-path batching [the doc's full store_fetched restructure] is DEFERRED — it is live-perf-gated
  per its own doc [unmeasurable here] + the riskiest 50-worker hot-path change; the `commit=False`
  primitive now exists so it is a smaller follow-up when the maintainer can measure live.** VERIFIED
  here: 57-test ingest/index hot-path regression + 160 targeted green, ruff F/B, mypy 127≤127.)
  **P1.4 SHIPPED** (FTS5/SQLCipher tuning pass — `src/database/fts.py:optimize_after_bulk(session)` runs
  the FTS5 `'optimize'` segment-merge [`INSERT INTO article_fts(article_fts) VALUES('optimize')`, DISTINCT
  from PRAGMA optimize — verified it did NOT run before; only `'rebuild'` at init] + `PRAGMA optimize`
  [planner stats, analysis_limit-bounded] after a bulk load; gated + SQLite-only + best-effort. Wired
  after a COMPLETE re-index pass [keyword-table churn → planner] AND after the newsletter folder import
  [article bulk-load → FTS segment churn]. cache_size left at the memory-conservative `OO_SQLITE_CACHE_MB`
  default 64 MiB for the reference AppVM [mmap is unavailable under the codec so cache_size is the lever —
  documented in the fn]; no default change. tests/test_fts_optimize.py [merge keeps search exact;
  best-effort without an FTS table] + the invariant guard. VERIFIED here: 167 targeted green, ruff F/B,
  mypy 127≤127.) **PHASE 1 COMPLETE** (unblock-the-rebuild: 1.1 job · 1.2 keyword-only · 1.3 batched
  commits · 1.4 tuning).
  **P2.4 VERIFIED-DEFERRED (the VERIFY-FIRST DuckDB-GCM gate, tested on DuckDB 1.5.4 in the venv):
  the hypothesis that ≥1.4 writes an authenticated AES-256-GCM store NATIVELY [without httpfs] is
  REFUTED — 1.5.4 refuses an encrypted WRITE without `LOAD httpfs` (OpenSSL): error "DuckDB currently
  has a read-only crypto module loaded … ensure httpfs is loaded … To write an encrypted database …
  that is NOT securely encrypted, one can use SET force_mbedtls_unsafe='true'." The only no-httpfs
  write path is the explicitly-UNSAFE mbedtls = the forbidden fabricated-security. SO: secure_crypto_
  available stays gated on httpfs, the gate is NOT relaxed, the engine stays IN-MEMORY (never fabricate
  the capability). The persisted-rollup PERF WIN remains blocked on bundling per-OS httpfs binaries
  (OPERATIONAL, networked machine). 2nd finding: 1.5.x `enable_external_access=False` in
  `_offline_config` ALSO blocks a file ATTACH outright — moot while httpfs gates. Recorded in
  columnar.py's EMPIRICAL FINDING. No code change (the gate already returns False = correct).**
  NEXT (sequencing is mine): the persisted P2.1–2.3 rollups' BIG win is now confirmed-blocked, so
  the highest-ROI BUILDABLE-and-unblocked items are P3 (eval harness) · P4.2 (reconcile_keyword_language
  — fixes the 16% head language mismatch) · P5.1 (BM25F + facets). In-memory rollups remain optional
  groundwork. (P5 serving · P6 entities later.)
  **PHASE 1 + P2.4 MERGED into 0.09 (PR #487).** **P4.2 SHIPPED** (new PR; reconcile_keyword_language —
  `src/analytics/store.py:reconcile_keyword_language(session)` sets `Keyword.language` to the
  SIGNATURE-MAJORITY article language [the fix for first-write-wins, the 16%/40%-of-head mismatch], a
  background pass mirroring `reconcile_keyword_counters`: only flips on a CLEAR majority [`>half` of the
  keyword's located mentions] backed by `>=2` distinct articles, so a stray article never flips a tag.
  PERF-SAFE per the codec column-order trap: NEVER the per-row `keyword_mentions->articles` join — a
  COVERING article-language map [`idx_article_language`, no content read] + a covering `(keyword_id,
  article_id)` mention scan joined in Python [one mention per (kw,article) so a row count == distinct
  articles]. Endpoint `POST /api/insights/reconcile-keyword-language`; folded into the re-index job's
  complete-pass [so "Clean up keywords" fixes language too]. The "?" bucket [all-untagged mentions] is
  left as-is — `global_stopwords` ALREADY routes every keyword incl. unknown-language through the
  English+all-language stoplist at query time, so "?" boilerplate is filtered there; an aggressive
  email/web boilerplate denylist stays the EVIDENCE-DRIVEN stoplist process [`analyze_keyword_log.py`],
  NOT a guess [the no-over-stoplist discipline]. tests/test_analytics_store.py [signature-majority
  flip · NULL→lang · tie-no-flip · "?"-noop] + the invariant guard. VERIFIED here: 193 targeted green,
  ruff F/B, mypy 127≤127.) **P3 SHIPPED** (new PR; IR retrieval-eval harness — the GATE that lets the
  ranking/conflation quality changes [P5.1 BM25F, P4.3 lemmatization, P5.2 embeddings] be MEASURED, not
  guessed [the measure-before-trust non-negotiable]. `src/analytics/ir_eval.py`: NATIVE pure-Python
  metrics [nDCG@k/MRR@k/Recall@k/P@k/AP — textbook defs, unit-tested vs hand-computed values; NO new
  `[eval]` dep to gate/degrade — the strategy allowed pytrec_eval/ranx OR native; native is leaner +
  more reliable]; `GoldQuery` [id·query·language·axis·graded relevances 0/1/2]; `evaluate` reports
  PER-LANGUAGE + per-axis with n stated, NEVER one pooled average alone [a method can win overall while
  losing on Arabic], and NO composite score [each metric stands alone]; `conflation_delta` reports the
  recall GAIN and precision CHANGE SEPARATELY + the newly-relevant vs newly-irrelevant example sets
  [never blended]; `regression_check` fails on a metric drop beyond tol; `evaluate_against_corpus` runs
  the LIVE FTS `search_ids` [pluggable search_fn so a BM25F/hybrid variant A/Bs via conflation_delta];
  `run_ir_eval_selftest` proves the MECHANISM on a fixture [10/10] → `GET /api/diagnostics/ir-eval-selftest`.
  tests/test_ir_eval.py [8: metrics vs hand-computed, per-language breakdown + no-composite, conflation
  both-sides, regression gate, injected search_fn] + the invariant guard. VERIFIED here: 155 targeted
  green, ruff F/B, mypy 127≤127. The one OPERATIONAL piece: a human-judged GOLD SET [graded 0/1/2 over
  the maintainer's own corpus] — corpus-specific, can't be bundled; the harness CONSUMES it.) **P5.1a
  SHIPPED** (new PR; BM25F per-column ranking — `src/database/fts.py` `search_ids` now ranks
  `ORDER BY bm25(article_fts, :wt, :wb)` instead of the flat `rank`, weighting the TITLE column above
  the BODY (a title keyword is a stronger relevance signal than a body mention — verified empirically:
  `bm25(ft,10,1)` ranks a title match first, `bm25(ft,1,10)` flips it). `_bm25_weights()` reads
  `OO_BM25_TITLE_WEIGHT` (default 4.0) / `OO_BM25_BODY_WEIGHT` (default 1.0), clamps ≥0, and FALLS BACK
  to the default on a bad value (never crashes); the weights are BOUND PARAMETERS (`:wt`/`:wb`), never
  f-string-formatted into SQL (no bandit B608 surface). REVERSIBLE by construction — equal weights ==
  the old flat rank. ONE change covers every consumer: `search_ids` is the single FTS ranking entry
  point (omnibar, `_query_articles`, framing, reporting, watches, AND the P3 `evaluate_against_corpus`),
  so the P3 harness can A/B a weight set via `conflation_delta` the moment a gold set exists — the
  MEASURE-before-trust loop is now closed for ranking. tests/test_bm25f.py [3: a title-only vs body-only
  match → title ranks first; env reversal → body ranks first; default `wt>wb` + bad-env fallback] + the
  invariant guard. VERIFIED here: 21 search-suite + 18 ir-eval/watches + 144 invariants green, ruff F/B,
  mypy 127≤127, py_compile.) **P5.1b SHIPPED** (new PR; INTERACTIVE FACETS — the When/Where/Who subtab of
  the analysis window becomes a FACET SURFACE co-equal with the text query. TWO genuine increments over
  the descriptive who/where it already showed: (1) a TEMPORAL (When) facet — `queries.corpus_when(article_ids)`
  buckets the mentioned-DATE tags (the dates the text is ABOUT, not pub date) by YEAR over the corpus,
  counts only, user-REJECTED tags excluded, deduced-never-confirmed; (2) a DRILL that makes a facet a query
  CONSTRAINT — `queries.corpus_facet_article_ids(article_ids, facet, value)` returns the corpus narrowed to
  the articles mentioning an entity/place/year (in corpus order), so clicking a facet value spawns a refined
  analysis window over EXACTLY those ids. Both PERF-SAFE per the codec column-order trap: an equality filter
  over the article_id-indexed mention tables, NEVER a keyword_mentions->articles join. `/api/insights/corpus-www`
  gains a `when` key (ADDITIVE — who/where unchanged, the existing contract test still passes) + a new
  `/api/insights/corpus-facet-articles` drill endpoint (reuses `_resolve_corpus` so it intersects whatever
  corpus is active — an exact id set OR the search + Advanced filters; 400 on an unknown facet, never a silent
  empty). The existing When/Where/Who subtab is upgraded IN PLACE (no parallel-window debt). Frontend: the
  `#an-www` loader renders who/where/when as clickable `.an-facet` chips (count shown) → `branchByFacet` →
  drill → `openAnalysisForIds`; `_anFacets` state; honest empty states + visible caveat; new strings
  English-fallback via `t()` (i18n gate stays 100%). Counts only, NO score; deduced from text, never confirmed.
  tests/test_corpus_facets.py [5] + 2 invariant guards (test_corpus_facets_drill_is_wired backend + the facet
  wiring in test_ui_invariants). VERIFIED here: 5 facet + 17 insights/queries + 19 search + 144 invariants
  green, ruff F/B, mypy 127≤127, node --check, i18n 100%. Frontend BROWSER-UNVERIFIED per fork-3. P5.1 (BM25F
  + facets) is now COMPLETE.) **P4.3 SHIPPED (mechanism; OPT-IN, default OFF)** (new PR; simplemma
  lemmatization at the DISPLAY layer — `src/analytics/families.py` gains a lemma-collapse grouping step
  (1.6) that conflates morphological keyword variants a plural heuristic MISSES — verb forms + irregulars
  (study/studied → study, run/running → run, child/children → child, Wahlen → Wahl) — via `simplemma`
  (pure-Python, NO torch/network; added to the `[analysis]` extra). `_lemma(norm, lang)` is CONSERVATIVE:
  single-token TERMS only (never entity NAMES), per (kind, LANGUAGE) so an en term never merges a fr one,
  a `_MISLEMMA_DENYLIST` blocks meaning-changers (media→medium, data→datum, us→we — evidence-grown like
  `_PLURAL_DENYLIST`), unsupported langs (zh/ja + the ones simplemma covers poorly) + a missing simplemma +
  any lemmatizer error all FALL BACK to `norm` (graceful degrade — a core install is a no-op). KEY HONESTY
  CALLS: (a) DISPLAY layer ONLY — `families.py`, NEVER `_normalize`/the stored trusted index (rewriting the
  canonical index is forbidden); an invariant asserts `extract.py`/`store.py` never import simplemma; (b)
  REVERSIBLE — a user split override keeps a form out; (c) VISIBLE `conflated_by=["lemma"]` provenance on
  the family (exposed in `to_dict`); (d) **DEFAULT OFF (`OO_FAMILY_LEMMA`, default "0") — the measure-before-
  trust discipline: it changes grouping app-wide, so its retrieval-quality impact MUST be measured (the P3
  eval harness + a human-judged gold set) before it is trusted on-by-default. Default-off + the skip ⇒
  BYTE-IDENTICAL to the pre-lemma grouping (the plural rule still handles regular -s/-es/-ies on its own).**
  tests/test_families.py (+5, skip-guarded on simplemma: lemma unit + guards, verb/irregular collapse +
  conflated_by, off-by-default no-merge [runs everywhere], entity/denylist/reversible, graceful-degrade
  without simplemma) + test_repo_invariants::test_lemmatization_is_opt_in_display_layer_and_reversible.
  VERIFIED here: 160 families/invariants + 19 build_families-consumers green, ruff F/B, mypy 127≤127,
  pyproject valid, external-freshness guard green. REMAINING: (1) the maintainer ENABLES + MEASURES it via
  P3 on a gold set before it goes default-on (operational); (2) the frontend display of `conflated_by`
  (a small "conflated by lemma" indicator on family chips — deferred + browser-unverified; nothing renders
  while the feature is off).) **P4.3 MEASURABILITY SHIPPED (follow-up; new PR)** — the
  measure-before-trust INSTRUMENTS so the maintainer can review + regression-guard lemmatization WITHOUT
  enabling it blindly: (a) `engine_report.py` gains a `lemma_preview` block = the candidate conflations
  among the top-N TERMS (groups of single-token terms that share a lemma per language, e.g. study/studied),
  with the would-merge member sets + counts, so the maintainer eyeballs PRECISION before flipping
  `OO_FAMILY_LEMMA` (a wrong merge → a `_MISLEMMA_DENYLIST` entry); reports `available:false` honestly when
  simplemma is absent, mirrors the families guards (terms only, never entity NAMES), no score. (b)
  `selftest.py` gains a `lemmatization_mechanism` golden case (checks `_lemma` DIRECTLY — no env toggle, so
  thread-safe in the live process — that study/studied→study + the denylist blocks media↛medium; omitted on
  a core install, never a failure), so a conflation regression reddens BOTH the in-app self-test export the
  maintainer sends AND CI. tests in test_keyword_engine_report.py + test_keyword_selftest.py. VERIFIED here:
  41 keyword + 30 diagnostic tests green, ruff F/B, mypy 127≤127.) **P3 OPERATIONAL PATH SHIPPED (follow-up;
  new PR; the gold-set INPUT the harness lacked)** — P3 had the metrics + `GoldQuery` format + `evaluate_
  against_corpus`, but NO documented FILE input + no one-call A/B, so the maintainer had no path to feed
  graded queries in. Added: (a) `ir_eval.load_gold_set(path)` — parses a JSON gold set
  (`{"queries":[{id,query,language,axis,relevances:{docid:0|1|2}}]}`) into `[GoldQuery]`, stringifies doc-id
  keys (so they compare regardless of how search returns ids), and FAILS LOUDLY (`GoldSetError`) on a
  missing file / bad JSON / out-of-range grade / duplicate id / empty set — never a silent skip; (b)
  `ir_eval.bm25f_weight_ab(session, gold, weights_a, weights_b)` — the one-call A/B of two BM25F (title,body)
  weight sets over the LIVE corpus + a gold set, returning each side's report + `conflation_delta`
  (recall/precision/ndcg SEPARATELY); (c) `search_ids(..., weights=(wt,wb))` — a per-call THREAD-SAFE
  weights override (None=env default, byte-identical), so the A/B never mutates the process-wide env; (d)
  a bundled `configs/ir_eval/gold_set.example.json` TEMPLATE (documented format + grading guidance) the
  maintainer copies. CORRECTION recorded: an earlier offer to A/B *lemmatization* via P3 was INCOHERENT —
  lemmatization is a display-layer families change, NOT a retrieval change, so it is invisible to the FTS
  retrieval harness; BM25F (P5.1a) IS a retrieval change and is the coherent A/B. tests/test_ir_eval_goldset.py
  (loader parses the template + 6 malformed-input failures; the A/B measures a real title-vs-body ranking
  move on a fixture corpus, recall unchanged + ndcg moved) + the test_ir_eval_harness_is_wired invariant.
  VERIFIED here: 14 goldset/ir-eval/bm25f + 146 invariants + 23 search green, ruff F/B, mypy 127≤127, JSON
  valid. REMAINING (operational, maintainer): produce a real graded gold set over the live corpus + run the
  A/B to pick the BM25F default on evidence.) **P3 IN-APP ENDPOINT SHIPPED (follow-up; new PR; closes the
  loop end-to-end)** — the deferred in-app surface: `GET /api/diagnostics/ir-eval?gold_path=&weights_a=&
  weights_b=&k=` loads a SERVER-SIDE gold-set file (`load_gold_set`) and either scores the live search at
  the current BM25F default (`evaluate_against_corpus`) or A/Bs two (title,body) weight sets
  (`bm25f_weight_ab` → `conflation_delta`, recall/precision/ndcg SEPARATELY, no blended score). 400 on a
  missing/malformed gold set OR half-specified weights (both-or-neither), via GoldSetError/ValueError →
  HTTPException — never a silent skip. Mirrors the existing diagnostics endpoints (keyword-engine /
  selftest / ir-eval-selftest): GET + `download=1` dated attachment. Server-side path input is the
  established local-single-user pattern (folder-backup / dump-reader). So the measure-before-trust loop is
  now COMPLETE in-app: format (template) → loader → endpoint → report; only the maintainer's GRADED gold-set
  DATA is still outstanding (corpus-specific, can't be bundled). tests/test_ir_eval_goldset.py (+1: the
  endpoint single-eval + the BM25F A/B [title-heavy beats body-heavy = negative ndcg_delta] + 400 on
  missing-file + 400 on half-specified weights) + the ir-eval invariant extended. VERIFIED here: 150
  goldset/invariants + 5 diagnostics green, ruff F/B, mypy 127≤127. NOT a task-manager job (a bounded
  read-only eval; the long-fetch job pattern is for network/IO jobs).) **P3 DIAGNOSTICS-PANEL BUTTON
  SHIPPED (follow-up; new PR; frontend, BROWSER-UNVERIFIED per fork-3)** — the deferred in-app control: the
  Settings → Diagnostics-log panel gains a gold-set-path input + two optional BM25F weight boxes + a "Run
  IR eval over a gold set" button → `runIrEval()` opens `/api/diagnostics/ir-eval?gold_path=&weights_a=&
  weights_b=` (the #500 endpoint) — empty weights = score the current default, BOTH filled = the A/B. So
  the maintainer runs the whole measure-before-trust loop with a CLICK, not curl. English-fallback via the
  un-keyed-diagnostics-strings convention (NO new locale keys → zero locale hot-file conflict with the
  parallel session); a hint points at the bundled template. test_repo_invariants (the ir-eval invariant
  extended: the panel wires `#ir-eval-path` + `runIrEval` + the endpoint URL). VERIFIED here: node --check,
  146 invariants, i18n 100%, ruff F/B. NOTE: my standing recommendation (the StatFigure revision-anomaly
  detector) was found ALREADY BUILT by the parallel session (`src/stats/revision.py` + `store.revision_
  anomalies` + `/api/stats/revision-anomalies` + the frontend "Check revision anomalies" button + 11 green
  tests) — so it's done, not re-built. KEYWORD-ENGINE PROGRAM COMPLETE for all autonomously-buildable work.
  NEXT (ALL need maintainer input/operational steps — do NOT start autonomously): P5.2 (static-embedding
  recall layer, gated on the P3 gold-set pilot) · the in-memory P2 rollups (optional groundwork; persisted
  blocked on httpfs bundling) · P6 (entity→QID, operational/networked) · enabling lemmatization/picking the
  BM25F default (needs a graded gold set) · Thai/zh segmenter (needs a bundled-artifact decision).
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
  left open = [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-14_OPTIMIZATION_TAIL.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-14_OPTIMIZATION_TAIL.md)
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
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEMMA_DEFAULT_ON.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEMMA_DEFAULT_ON.md);
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
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_FAMILIES_ENTITIES.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_FAMILIES_ENTITIES.md);
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
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_SUPERGROUPS.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_SUPERGROUPS.md);
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
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_GROUPS_LAYER_AMENDMENT.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_GROUPS_LAYER_AMENDMENT.md),
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
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEADS_CALIBRATION.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEADS_CALIBRATION.md)):**
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
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_CONVERGENCE_AMENDMENT.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_CONVERGENCE_AMENDMENT.md),
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
  links→sources · the airplane/Ollama gate split · source-IP surfacing incl. the
  Tor-exit-resolve path · discovery trail + citations tally/drills + corpus filters · the
  nav-soup prose gate · the post-import delta screen · the LLM triage/tag runs with the
  Claude-verification chain — each build verified per the house gates AND field-confirmed,
  not merely merged (merged ≠ green ≠ verified); "double-checked" INCLUDES docs↔app
  reciprocity — USER_MANUAL chapters for qualification / source management / the
  post-import screen (the standing reciprocity rule applied to everything this row builds).
  (2) **a fully TRANSVERSAL AUDIT of the entire repo** (the `07_TRANSVERSAL_AUDIT_V01` precedent — a new tool-by-tool edition for
  0.3). (3) **full diagnostics taken from a MEDIUM corpus — at least 5 MILLION articles**
  (the all-diagnostics bundle run at that scale; NOTE recorded honestly: the live corpus is
  ~an order of magnitude below 5M today, so this row implies the corpus keeps growing via
  the maintainer's ongoing merges — the spirit is REAL field data, per the
  P0-live-run-not-synthetic precedent). (4) **a FULL IMPORT of the database that RE-CHECKS
  ALL SOURCES** — the ruled qualification-at-import admission gate demonstrated at full
  scale (every source through the pass, verdicts stamped — the curated catalog INCLUDED,
  no grandfathering per the same-day seed ruling; catalog failures = catalog-review work
  items) before the switch; this row
  EXPLICITLY doubles as the backup/restore-AT-SCALE validation (a ~5M-article import IS a
  restore at ~10× the P0-validated 2.5 GB scale — state it in the gate evidence). (5) **an
  ARTICLE CLEAN-UP strategy: DISCUSSED → AGREED (explicit maintainer sign-off BEFORE
  execution) → implemented → EXECUTED** on the ≥5M corpus, removing the undesired-article
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
  INTAKE + INVESTIGATION this session, code-verified against main@7405968; numbered questions put
  to the maintainer, ANSWERS PENDING — record them here when they arrive):** (1) IMPORT REPORT —
  downloadable per-import detail (successes/errors/redundancies + executive summary) offered in a
  dedicated end-of-import popup: COMPOSES with the ruled 2026-07-20 POST-IMPORT RESULTS SCREEN
  (same surface; the report becomes its download half — one build, not two). (2) IMPORT-TIME
  ARTICLE SCREENING — what to do when an imported corpus (built by OLDER engines) carries
  non-articles (link lists/marketplaces) that newer criteria would refuse; maintainer intuition =
  disregard + count + optional export of the disregarded set for verification. Composes with the
  0.3 close-gate row 5 (clean-up strategy DISCUSSED→AGREED before execution), the Slice-4a
  reversible-quarantine carry-over, and the pending nav-soup prose gate; the
  skip-vs-quarantine-in-DB decision is question 2 (session recommendation: quarantine-in-DB,
  reversible, criteria-version-stamped — criteria WILL keep evolving). (3) LIBRARY TAB LIVE
  GRAPHS instead of live figures (articles/hour past 7 days + live speed; database-count
  evolution), box-sized, click-to-enlarge: the render substrate EXISTS (dashChartSvg tiny cards +
  chartEnlarge→ooChart); the DATA gap is a history for non-article counts — articles/hour derives
  retroactively from created_at, but source/keyword/link/price counts have NO history table →
  needs a lightweight periodic snapshot recorder (honest: those graphs begin when recording
  begins, never a fabricated backfill). (4) SCRAPING STALLS (minutes to dozens of minutes,
  several installs) — investigate; candidates ranked: serial post-pass housekeeping between
  passes (briefing refresh/wiki+law tracking/feed auto-import/idle maintenance), feed-level
  backoff, Tor circuit trouble, VM suspend, the 2026-07-21 finding-3 stall cluster (cause still
  unidentified); needs a diagnostics export from an affected instance + the item-3 graphs as the
  detector. (5) LIBRARY "Downloaded" section COMPRESSES; Wikipedia pages/revisions-tracked and
  law articles/revisions-tracked get OWN sections WITH graphs (series derivable from stored
  revision timestamps). (6) ~50,000 "sources discovered" vs ~5,000 articles in 12 h on a fresh
  install — VERIFIED: the discovery funnel CANNOT produce that (run_discovery is budget-bounded
  ~10 candidates/pass; curated catalog seeds ~3.4k + 225 legal; world_news_sources.yml is NOT
  generated/committed), so WHICH figure reads 50k is question 6 (best guess: distinct cited
  domains from article_links — naturally ~10×/article); the ruled-but-unbuilt qualification
  lifecycle + a two-class sources-vs-candidates display are the levers. (7) THROUGHPUT ~5,000
  articles/12 h is too slow (want ≥10×; bandwidth visibly under-utilized) — VERIFIED: parallel
  collection is ALREADY default-on with ceiling `collect_parallelism=50`, BUT
  `collect_rate_mode` defaults to "target" at 500 KiB/s — the BandwidthGovernor deliberately
  parks workers to hold ~500 KiB/s (the under-utilization is BY DESIGN; "maximum" mode ramps to
  the ceiling and exists today). Other suspects before promising 10×: write-bound collection
  (the F2 writer-gate saturation lesson; the deferred collector write-batching is
  live-measure-gated and a collect_perf export from the slow instance is the measurement), and
  PUBLISH-RATE bound (~3.4k enabled sources ≈ 1.5 new articles/source/12 h — more articles may
  need more enabled sources [qualification funnel + the pending networked
  build_world_news_catalog.py run] and/or crawl mode, not just more workers). NOTHING BUILT this
  session — intake, verification and the question list only.
  **ANSWERS RECEIVED + RULED same day (maintainer answered all 12 questions; the small ruled
  slice SHIPPED same session, the rest queued):**
  • **A1 (import report):** JSON + Markdown, PERSISTED on disk, and the persisted reports RIDE
    the backup export/import. Folds into the ruled post-import results screen (one build).
  • **A2 (screening disposition): QUARANTINE-IN-DB ruled** (reversible, criteria-version-
    stamped, excluded from search/analytics/keywords by default); quarantined articles ALSO
    ride backup export/import (they are data, never silently dropped).
  • **A3: the screening runs RETROACTIVELY on existing corpora** (this is the 0.3 close-gate
    row-5 cleanup; the agreed-strategy-before-execution step still applies to the criteria).
  • **A4 (criteria scope): BOTH extraction-validity AND borderline classes, tested together
    via an ITERATIVE loop** — build a TEMPORARY criteria-calibration DIAGNOSTIC first: a
    downloadable top-100 of disregarded/would-be-disregarded articles with statistics +
    per-article detail, so the criteria are optimized on real specimens before any execution
    (propose→human-review→apply, the stoplist discipline applied to articles).
  • **A5 (Library graphs): confirmed; snapshot recorder with INFINITE retention** (hourly
    counter snapshots are tiny — ~10 counters × 8,760/yr ≈ trivial rows; no downsampling
    needed; article-series backfills from created_at, other counts begin at recording start).
  • **A6 (stalls):** every instance runs over Tor (identity protection); maintainer judges the
    stalls NOT Tor-linked; the diagnostics export is deferred until after the current builds.
  • **A7 RESOLVED (the 50k figure) — the maintainer's sources CSV analyzed (46,213 rows):**
    42,612 DISABLED `via:wikidata-discovery`+`world-catalog` candidates + 3,599 ENABLED
    (3,200 curated · 205 legal-generated · 88 markets · 58 spectrum · 47 legal · 1 other).
    So "50k sources" = the world-discovery machinery WORKING AS RULED (2026-07-15
    "significantly increase the source count" + the default-on ride-along), blended into one
    Library "Sources" count — a DISPLAY problem, not a registration bug. Composition note:
    source_type institution 20,777 / news 17,021 / religious 7,957 — the Wikidata specs'
    breadth makes the qualification membrane ESSENTIAL before any of it enables. Fixes: the
    TWO-CLASS display (enabled/qualified vs discovered candidates, never one blended number)
    + the qualification funnel to digest the 42k backlog.
  • **A8 (workflow order RULED): source QUALIFICATION first, THEN the Library graphs UI** —
    both in the next workflow; the 2026-07-20 qualification rulings (admission gate · stamp ·
    background job · re-qualification ladder · all-sources-qualified-by-definition) are the
    spec.
  • **A9 RULED + SHIPPED same session:** `collect_rate_mode` default flips "target"→"maximum"
    (src/scheduler/settings.py; test_parallel_collect updated; existing installs keep a saved
    choice — the new knob or Settings flips them) + the top-bar SPEED KNOB + the VERSION under
    the sidebar logo (see the invariant-#4 amendment above; frontend browser-unverified per
    fork-3). NOTE: a saved settings.json that predates the flip keeps "target" until the user
    clicks the knob.
  • **A10:** proceed WITHOUT the collect_perf measurement for now (the all-diagnostics zip is
    slow on the old test machine; the maintainer will try later). The write-batching decision
    stays measure-gated — the item-3 graphs + a later export are the measurement path.
  • **A11 (throughput diagnosis, maintainer facts):** enabled sources publish >10 articles/day
    (publish-rate bound REJECTED by the maintainer for the enabled set); measured average
    download is a FEW kB/s — two orders below Tor capability → the bottleneck is app-side.
    INVESTIGATION NOTE (recorded for the build session): the governor seeds 25 workers and
    ramps toward w_max=50 in target mode when rate < target, so a few-kB/s average means
    workers are BLOCKED elsewhere or the duty cycle is low — ranked suspects: per-host Tor
    circuit builds (one isolated circuit per host × 3.4k hosts), robots.txt fetches per new
    host, serial inter-pass housekeeping (also the item-4 stall suspect), feed-level backoff
    shrinking the due set, the single-writer gate. The rate-mode flip is NECESSARY but likely
    NOT SUFFICIENT — the throughput hunt continues instrumented (item-3 graphs + collect_perf
    when available).
  • **A12:** affected instance = 2-core/4 GB over Tor, but an 8-core modern machine shows the
    SAME download rate — the machine is NOT the issue (weakens a pure CPU/write-bound theory,
    strengthens the shared-structural suspects above); hardware-aware diagnostics welcome
    (already ruled in the diagnose-the-diagnostics hardware-profile entry).
  **DIAGNOSTICS EXPORT ANALYZED same day (supersedes A10's "do without" — the maintainer's
  all-diagnostics zip from the slow 2-core/3.2 GB AMD 3020e Tor instance arrived and was
  crunched; 30-run scheduler history + 199 collect_perf samples + 1 pass summary):**
  (i) **STALENESS CORRECTION — the QUALIFICATION LIFECYCLE IS ALREADY BUILT + LIVE** on main
  (`src/catalog/qualification.py`: admission gate in `select_sources`, `advance_qualification`
  ride-along default `qualification_per_pass=5`, backoff ladder 1→2→4→6 months, categorical
  stamps + append-only `SourceQualificationAttempt`; live evidence in the export: a
  "qualification trial fetch failed for 'latimes.com'" log line). NEXT-WORKFLOW STEP 1 therefore
  becomes VERIFY + SCALE + SURFACE, not build: at 5/pass (~4 passes/h) the 42.6k candidate
  backlog needs ~90+ days — it wants the dedicated bulk qualification job / a higher
  hardware-aware per-pass, plus the two-class sources display. (ii) **THROUGHPUT VERDICT
  (three stacked causes, the rate-mode target was only one):** (a) the governor's MEM-LOW floor
  parks permits at median 2 / max 8 on the 3.3 GB box (35 `mem-low` samples; pass verdict
  "memory-bound", min avail 395 MB, RSS ~1 GB) — the "maximum" flip cannot lift this floor,
  RAM is the worker ceiling on 3–4 GB machines; (b) SUPPLY: 92% duplicate rate (per-pass tally
  e.g. entries 979 · duplicate 900 · stored 62 · not_modified 56), 9–117 new articles/pass
  across 30 runs — the due feeds OFFER no more; 2,766 of the 3,599 enabled sources have an
  rss_url and yield ≈2 new/day/feed on average (the maintainer's ">10/day" holds for big-name
  feeds, not the median), so the 10× is more QUALIFIED+ENABLED sources (the funnel now running)
  + crawl mode; (c) DUTY CYCLE: inter-pass gaps of 5–7.5 min EVERY cycle (65% fetching / 35%
  between passes over the 30-run window) — the serial post-pass housekeeping (briefing refresh,
  auto-imports, wiki/law tracking, discovery + world-discovery + qualification ride-alongs) IS
  the item-4 "few minutes" stall, structural; the dozens-of-minutes stalls remain unexplained
  (collect_perf's rolling retention covers ~one pass — too short; the item-3 graphs stay the
  detector). During-pass burst rate was FINE (avg 1402 KiB/s, above the 500 target — with
  'above-target' shrinks proving target mode was also costing; the maintainer's "few kB/s"
  reading is the long-window average diluted by gaps + the 83/199 zero-rate samples). (iii)
  **the diagnose-the-diagnostics build is CONFIRMED WORKING at field scale** (journal + hardware
  header + runtime-coverage `complete:true`; total 961 s; slowest members leads-quality 268 s ·
  date-extraction 229 s · home-cards 131 s — heavy analytics on 2 cores, consistent with the
  housekeeping-gap finding). (iv) **small defects found in the export, queued:** htmldate.meta
  "impossible to clear cache" log noise ×85 = 85 of the 93 logged "problems" (third-party
  logger — filter it so the error log stays signal); the KPI K2 resolver dies with a TypeError
  (reported as not-measurable — a real resolver bug); `locked_errors` 6 this session (the
  is_locked_error family, keep watching); event-loop watchdog ~278 ms lag events (minor).
  **SECOND-INSTANCE COMPARISON (same day — the maintainer's controlled experiment: a SECOND
  all-diagnostics zip from an i7-13620H Qubes VM, 4 vCPU / 9.7 GB RAM, launched at the same
  time as the AMD 3020e 2c/3.2 GB instance; the "hardware is not the issue" intuition is
  CONFIRMED and the diagnosis sharpens):** (a) the memory floor vanishes on the big box (ZERO
  `mem-low` samples, min avail 6.6 GB, permits median 11 / max 27 vs the slow box's median 2)
  and passes run 2× faster over MORE sources (527–533 vs 354/pass) — yet stored articles/hour
  is only ~1.7× (331/h vs 193/h; corpus 6,918 vs 5,731 ≈ 1.2×), nowhere near the ~3× compute
  gap. (b) WHY — Amdahl at the pass boundary: the inter-pass gap stays 3–8 min on BOTH machines
  (fast box duty cycle is actually WORSE: 48% fetching / 52% gap, since passes shrank but gaps
  did not) — the gap work barely scales with CPU because it is SINGLE-CORE analytics (the
  post-pass briefing refresh: home-cards 96 s vs 131 s in the diagnostics run — only 1.4×
  faster on 2.7× compute) + SERIAL TOR FETCHES in the ride-alongs (calendar auto-imports,
  wiki/law tracking, discovery + world-discovery Wikidata queries + qualification trials — each
  a sequential ~5–15 s Tor fetch). DUTY-CYCLE FIX = the TOP lever (≈2× on fast hardware alone):
  overlap the ride-alongs/briefing with the next pass or parallelize/bound them. (c) SUPPLY
  confirmed hardware-independent: ~90% duplicate rate on BOTH (fast 15,214/16,980; slow
  18,434/20,701) — both drain what the ~2,766 feeds offer. (d) **NEW: the fast box hits
  "writer-bound" pass verdicts** (writer-saturated samples at permits ~27) — the LIVE
  measurement the deferred COLLECTOR write-batching was explicitly gated on has now arrived;
  as supply grows, the single-writer gate + full per-article indexing is the next wall →
  write-batching graduates from measure-gated to evidence-justified. (e) the fast instance's
  world-discovery shows added_total 66,697 / countries 245/249 (the candidate pool keeps
  growing; qualification at 5/pass = 5 qualified/pass, 0 errors — working but far too slow for
  the backlog). (f) BOTH instances still ran rate_mode "target" (saved settings predate the
  default flip — the new top-bar knob is how existing installs switch). MAINTAINER'S OFFER of a
  third 8-core/20 GB test: NOT needed for diagnosis (two points already separate the
  hardware-dependent mem floor from the hardware-independent gap+supply ceiling); SAVE that
  machine as the before/after benchmark for the duty-cycle fix.
  **NEXT WORKFLOW (queued, ruled order, amended per the two exports; BRIEF OF RECORD =
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-23_FIELD_FEEDBACK_WORKFLOW.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-23_FIELD_FEEDBACK_WORKFLOW.md)
  — the operating manual for the executing session(s), with the verified-current-state table +
  per-slice specs/acceptance):** (1) qualification
  VERIFY + SCALE (bulk job over the 42.6k–66.7k candidate backlogs / hardware-aware per-pass) +
  the two-class sources display; (2) the Library graphs UI + the snapshot recorder (infinite
  retention) + compressed Downloaded section + wiki/law tracked sections (items 3+5) — also the
  stall detector; (3) the import-report (JSON+Md, persisted, backup-carried) folded into the
  post-import screen + the quarantine-in-DB screening (import-time + retroactive) with the
  temporary top-100 criteria-calibration diagnostic FIRST (items 1+2+A4); (4) the throughput
  levers in evidence order: DUTY-CYCLE fix (overlap/parallelize the inter-pass housekeeping —
  measured ≈2× on modern hardware) · supply growth via the funnel · COLLECTOR write-batching
  (now evidence-justified by the fast box's writer-bound verdicts) · memory headroom on small
  boxes (the mem floor is the worker ceiling; hardware-aware profiles) · crawl mode — plus the
  first export's small defects (iv). TWO MORE STALENESS CATCHES folded into the brief's
  current-state table (verified in-tree 2026-07-23): the nav-soup PROSE GATE is BUILT
  (`src/services/prose_gate.py`, AND-gated function-word + sentence-punctuation density, wired
  opt-in into `non_article_scan`) and the RETROACTIVE-QUARANTINE JOB exists as a BUILT-BUT-
  DELIBERATELY-UNWIRED dry-run scaffold (`src/analytics/quarantine_job.py`, `_work_fn` seam, no
  Article quarantine column yet) — its own docstring gates execution on maintainer sign-off,
  WHICH THE A2–A4 RULINGS NOW PROVIDE, conditioned on the S3.1 calibration-review round.
  **S1 SHIPPED 2026-07-23 (qualification verify + scale + surface; branch
  `claude/oos-optimization-feedback-ygywq7`, draft PR onto `main`; the brief's own S1
  slices):** S1.1 VERIFICATION found a REAL correctness bug while confirming the live
  lifecycle: `run_qualification_pass` stamped a candidate `qualified` whenever its trial
  fetch produced ZERO stored articles (`source_audit.per_source_metrics` omits a
  zero-article source ENTIRELY, so the empty fails-list read as "healthy" and admitted
  the source with no verification ever performed — the field log's own "qualification
  trial fetch failed for 'latimes.com'" line was very likely this exact free pass).
  Reproduced live, then FIXED: a candidate absent from the metrics (no evidence — a
  totally-failed fetch, or no rss_url and no prior articles) is left `unqualified` (no
  attempt row, no stamp) and re-offered on a later pass, tallied honestly as
  `no_evidence`; four tests pin both directions (zero-evidence never qualifies; existing
  prior evidence still judges normally). Also pinned (was true by construction, now
  explicitly tested): a disqualified source's domain is never re-proposed by the
  discovery channels (domain uniqueness). **S1.2** the bulk qualification BACKGROUND JOB
  (`src/catalog/qualify_job.py:run_bulk_qualification`) drains the 42.6k–66.7k candidate
  backlog the 5/pass ride-along would take 90+ days to clear — batches the SAME
  `run_qualification_pass`, NO persisted cursor (`Source.status` IS the durable progress
  marker, unlike world-discovery's per-country file cursor), pauses cleanly (never
  auto-resumes) on cancel/airplane/the process-wide memory guard, and stops honestly
  after 10 consecutive no-progress batches rather than spinning on permanently-
  unresolvable candidates. New endpoints `POST/GET/POST /api/sources/qualify-bulk{,
  /status,/cancel}` mirror `discover-world-sources`'s wiring exactly (same
  `BackgroundJob` chassis, same status/progress shape); a Settings → Sources panel
  starts/cancels it with live status. Resume-after-cancel + a no-score-key payload walk
  are explicitly pinned (10 tests total). **S1.3** the two-class sources display —
  `database_stats` gains `sources_qualified` (enabled AND status=qualified — exactly
  `select_sources`'s own admission filter) and `sources_candidates` (enabled=False), so
  the Library "Sources" tile stops blending actively-collecting sources with disabled
  discovery candidates (the exact figure the maintainer's export showed as "~50k
  sources" against a ~5k-article corpus). **STALENESS CATCH:** the 2026-07-20-ruled
  qualified-citations tally + discovery-provenance trail (optional stretch inside S1.3)
  were found ALREADY SHIPPED (`src/discovery/source_trail.py`, endpoints
  `/{source_id}/{provenance,citation-tally}`, 13 tests, frontend-wired) — verified, not
  rebuilt.
  **ADVERSARIAL SKEPTIC PASS (before push) found a SECOND real bug, fixed same session:**
  the S1.1 zero-evidence fix, correct in isolation, combined with `select_unqualified`'s
  pure `ORDER BY id ASC` to create a LIVELOCK — `scripts/build_world_news_catalog.py`
  never sets `rss_url` (grep-confirmed), so EVERY Wikidata-discovered candidate can
  NEVER produce evidence via a trial fetch; once enough of the LOWEST-id candidates are
  permanently unresolvable, they occupy every future batch's selection window forever,
  starving any genuinely resolvable candidate behind them in id order. REPRODUCED LIVE
  (30 feed-less sources blocked one resolvable source across 20 passes) before fixing.
  FIX: a `no_evidence` outcome is now LOGGED as a `SourceQualificationAttempt` row
  (`log_no_evidence_attempts`, NEW verdict value, `Source.status` untouched — no free
  pass, S1.1's fix stands) and `select_unqualified` orders by LEAST-RECENTLY-ATTEMPTED
  (a LEFT JOIN + `nullsfirst()`, mirroring `select_due_disqualified`'s existing subquery
  shape) instead of pure id — a stuck candidate rotates OUT of the way after one attempt,
  in favour of never-yet-tried candidates, and only comes back up once everyone else has
  had a turn (still retried eventually — a transient failure deserves another chance,
  it just can never again BLOCK the queue). `consecutive_disqualifications_from_verdicts`
  was adjusted to SKIP (not break on) a `no_evidence` entry so the re-qualification
  ladder position isn't wrongly reset by an inconclusive retry. Re-verified the exact
  repro now resolves in 4 passes; 2 new regression tests pin the scenario at both the
  `run_qualification_pass` level and end-to-end through `run_bulk_qualification` (using
  the REAL pass function, a stubbed no-network `trial_fetch`, and a genuinely
  pre-seeded article — not a mock of the judging logic itself).
  **A THIRD finding (S1.3 sum-completeness) also fixed:** the two-class split did not sum
  back to `sources` — an enabled-but-not-yet-qualified source (e.g. freshly seeded,
  awaiting its first pass) was invisible in both `sources_qualified` and
  `sources_candidates`. Added `sources_pending` (enabled AND status!=qualified, covering
  both never-yet-judged and disqualified-but-still-enabled) so the three classes now
  PARTITION the flat total exactly — pinned with an explicit sum-equality assertion.
  A concurrency finding (the bulk job and the ride-along could theoretically select
  overlapping candidates before either commits) was assessed as low-severity/no-data-loss
  (the single-writer gate still serialises commits; worst case is a redundant attempt row)
  and recorded as a documented, deliberately-not-addressed risk rather than built out,
  per the reproducer-first-for-gate-hold-riders discipline.
  VERIFIED (post-fix): full suite 4378 passed/107 skipped/0 failed (py3.13 venv) both
  before AND after this fix round, ruff F/B clean, mypy 0 new errors (127==baseline),
  bandit clean, i18n 100% (2111/2111 ×12, no new keys — the new UI strings use the
  established un-keyed-diagnostics-panel convention). Frontend BROWSER-UNVERIFIED per
  fork-3/Q6a.
  **S2 SHIPPED 2026-07-23 (Library-tab evolution graphs + hourly snapshot recorder; branch
  `claude/oos-s2-library-graphs`, draft PR onto `main`; the brief's own S2 slices):** new
  `StatSnapshot` model (table `stat_snapshots`) — an append-only EAV row (metric,
  hour-bucket `taken_at`, value) mirroring the vintage convention (`StatFigure`/
  `SourceQualificationAttempt`); migration `f670ae07b75e` off the REAL alembic head
  (`04c029205aa8`, read via `alembic heads`, never guessed) — `alembic check` confirms zero
  drift. `src/database/snapshots.py:maybe_snapshot_library_stats` records one hourly
  snapshot per tracked metric (articles/sources/keywords/wiki_pages/wiki_revisions/
  law_documents/law_revisions), each a cheap `COUNT(*)` over a small/indexed table (never
  the codec column-order perf trap); the `(metric, hour)` unique constraint IS the
  freshness gate — no separate marker file, run inside `run_idle_maintenance` alongside
  the existing keyword-cleanup/incremental-vacuum steps. `articles_per_hour` is DERIVED
  live from `Article.created_at` (real history that already existed — backfills for free,
  no gap); every snapshot-table metric honestly states `recording_began_at` instead of
  implying a pre-recording gap means nothing happened. New `GET /api/library/history?
  metric=&days=` serves both kinds through one contract (response window bounded — default
  30d, clamped ≤10y — even though storage retention is infinite). Frontend: three new
  dedicated Library-tab sections (Activity / Wikipedia tracked / Law tracked), small tiles
  reusing the EXISTING `dashChartSvg` (invariant #16) + `chartEnlarge` — no new chart
  renderer, no larger tile footprint; the "Downloaded" 9-tile grid is compressed into the
  established collapsed-by-default `<details class="adv-collect">` disclosure (item 5's
  ask), matching Settings' own legacy/advanced-section convention. Zero new i18n keys
  (un-keyed English fallback, matching S1's own qualification-panel convention).
  **A REAL SAFETY FIX caught pre-push by re-reading my own code against this project's OWN
  documented lesson list (not by an external skeptic this time):** the recorder's per-
  metric loop initially caught a concurrent-writer `IntegrityError` with a bare
  `session.flush()` + `session.rollback()` — which per the standing "delete-then-reinsert"/
  "restore-merge re-index" lesson family would have discarded EVERY prior metric's
  already-flushed insert in the same loop, not just the colliding one. Fixed by wrapping
  each row's insert in its own SAVEPOINT (`session.begin_nested()`), so a collision on one
  metric never discards sibling metrics recorded earlier in the same call; PROVEN (not just
  asserted) via `test_a_mid_batch_collision_never_discards_sibling_inserts` (seeds a
  pre-existing colliding row, asserts every OTHER metric still lands). A repo-invariant
  test pins the three graph hosts, the compressed Downloaded section, the render-function
  wiring on tab-show, dashChartSvg/chartEnlarge reuse, and the composed real route (the
  "slice-1c 404 lesson" — never assert two literal strings side by side).
  VERIFIED: full suite 4423 passed/107 skipped/0 failed (py3.13 venv) — after fixing ONE
  real cross-cutting failure the full run surfaced: a new test's `Path.read_text()` call
  was missing `encoding="utf-8"`, caught by this repo's own house-wide
  `test_all_text_io_declares_utf8_encoding` guard (a reminder that a full-suite run catches
  defects no single test file run in isolation would). ruff F/B clean; mypy 0 new errors
  (127==baseline); bandit clean; alembic upgrade-head + check both green; i18n 100%
  (2111/2111 ×12, unchanged key count). Frontend BROWSER-UNVERIFIED per fork-3/Q6a.
  REMAINING per the brief's ordering: S3 (import report + quarantine-in-DB screening, gated
  on the top-100 calibration diagnostic shipping+being reviewed FIRST) then S4 (throughput
  levers, duty-cycle fix first).
  **S3.1 SHIPPED 2026-07-23 (the TEMPORARY criteria-calibration diagnostic; branch
  `claude/oos-s3-import-report-quarantine`, draft PR onto `main`; the brief's own S3.1
  slice — the binding gate before S3.4's real quarantine execution):**
  `src/analytics/criteria_calibration.py:calibration_report` is a REPORT over the existing
  detectors, never new judging — reuses `scan_non_article_candidates(..., include_prose_gate=
  True)` verbatim, collects up to `top_n` (default 100) sample ids across every URL-shape
  reason + the prose-gate subpass, fetches real per-article detail for that bounded id set
  (id/title/url/source/word_count/language/function-word density/sentence-punctuation
  density/which criterion fired), and aggregates per criterion/per source/per language — so
  the maintainer optimizes the criteria on real specimens before ANY retroactive quarantine
  runs on a real corpus. An id that vanished between the scan and the detail fetch (a
  concurrent delete/prune) is silently skipped, never fabricated. `CRITERIA_VERSION`
  (`"nav-soup-v1"`) is stamped so a future S3.2 quarantine write can record exactly which
  criteria generation flagged an article. New `GET /api/diagnostics/criteria-calibration`
  (plain `def` → threadpool, `download=1` dated attachment) is wired into the all-diagnostics
  bundle (`_DIAG_COVERAGE_MAP` + a member using a smaller `prose_gate_limit` than the
  endpoint's own default, keeping the bundle's own runtime bounded) — respects the 2026-07-17
  completeness ratchet; per the 2026-07-20 button-consolidation ruling, no new per-report
  Settings button was added (the one all-diagnostics button already carries it). VERIFIED
  (py3.13 venv): the new test file (negative space — a real article is never collected
  whatever its URL/length — plus the full field set, the top_n cap, the vanished-row skip,
  aggregation correctness, no-score-field walk) + `test_non_article_scan.py` +
  `test_repo_invariants.py` all green (235 tests); ruff F/B clean; mypy 0 new errors (fixed
  one genuinely-new error — a `dict(session.query(...).all())` call mypy can't type — by
  switching to the dict-comprehension pattern already proven clean elsewhere, e.g.
  `src/catalog/csv_io.py:190`); bandit clean; i18n unchanged (2111/2111 ×12 — no frontend
  strings added). **REMAINING (S3.2–S3.5, each its own follow-up PR per the brief's own
  data-safety skeptic mandate for the schema/write-path slices):** the quarantine schema +
  write step, import-time screening, the retroactive screening job (dry-run-default, real
  execution gated on this report's review), and the import report + post-import screen.
  **S3.2 SHIPPED 2026-07-23 (the quarantine SCHEMA + WRITE STEP; branch
  `claude/oos-s3-quarantine-write`, draft PR onto `main`):** the reversible flag +
  first `/api/articles` exclusion chokepoint the brief's S3.4 execution will need.
  `Article` gains four additive nullable columns (`quarantined` bool ·
  `quarantine_reason` · `quarantine_criteria_version` · `quarantined_at`) + a covering
  `idx_article_quarantined` index — a new `ensure_article_quarantine_columns` boot
  self-heal (mirrors `ensure_article_ip_columns`, wired before `ensure_hot_indexes`
  since the new index references the new column) PLUS a matching migration
  `95120f685050` (chained onto the real `alembic heads` tip, `alembic check` confirms
  zero drift). `Article.quarantined.isnot(True)` is the ONE exclusion condition (NULL
  == "never judged" reads identically to `False` — a pre-migration row is never
  silently hidden). `src/backup/merge.py:_merge_articles`'s explicit column-map INSERT
  now carries the 4 columns so a quarantine verdict rides the additive-restore merge
  (a gap noted in passing: `server_ip`/`detected_language`/`content_multihash`/
  `canon_version` are STILL absent from that same INSERT list — a pre-existing gap,
  flagged not fixed, out of this slice's scope). `default_quarantine_candidates_batch`
  (the S3 scaffold) gains a real `write=True` mode — a per-row bulk
  `Query.update(..., synchronize_session=False)` (confirmed covered by the single-
  writer gate's `do_orm_execute` listener, no new gate-wiring needed), idempotent (an
  already-quarantined row is skipped and tallied separately as `already_quarantined`
  vs `newly_written`), stamping `quarantine_criteria_version` from
  `criteria_calibration.CRITERIA_VERSION` by default. `QuarantineJobManager` is now
  WIRED into the app for real (`get_quarantine_manager()` singleton; new
  `src/api/quarantine.py`: `POST /api/quarantine/start?write=` · `GET .../status` ·
  `POST /.../{pause,resume,cancel}`, plus the generic `/api/jobs/{quarantine}/...`
  task-manager dispatch — `_quarantine_jobs()` mirrors `_reindex_jobs()` exactly,
  `"quarantine"` joins `_DB_WRITER_KINDS`). `write=False` (the endpoint default) is
  BYTE-IDENTICAL to the pre-slice dry-run scaffold. `/api/articles` (search FTS
  branch, plain browse branch incl. its S2.3 cached-total path, and the explicit
  `ids=` bypass) now excludes quarantined rows — deliberately scoped to ONLY this one
  chokepoint (search + browse + CSV/JSON export + card-seeded exact-id corpora all
  route through `_query_articles`); the omnibar/watches/reporting/framing surfaces
  (which call `search_ids` directly) and Home producers/analytics aggregations are an
  HONEST, undone remainder — not silently claimed covered. **A real design catch made
  BEFORE writing any code (not via a failing test):** the S2.3 cached-total
  optimization branches on `if filters:` (a Python list) vs the cached path — so
  unconditionally appending the quarantine condition to that list would have made
  `filters` NEVER empty again, silently defeating the cache for the common
  no-other-filter browse case; fixed by applying `Article.quarantined.isnot(True)` as
  an ALWAYS-ON condition separate from the optional `filters` list, and making
  `_browse_total_cached` itself quarantine-aware in its own cached query. **A second
  catch, also design-time:** `start()`'s write-mode assignment was originally
  cursor-gated (`if _cursor <= 0: self._write = bool(write)`) on the assumption only a
  fresh run sets the mode — but `resume()` calls `start()` without passing `write=`,
  so a legitimately-paused write-mode run with `_cursor==0` (no progress yet) would
  have silently flipped back to dry-run on resume; fixed by making `start()` always
  set the mode unconditionally from its own parameter and having `resume()` explicitly
  re-supply the paused run's `self._write`, pinned by two dedicated regression tests
  (write-mode and dry-run-mode both survive a pause/resume cycle). VERIFIED (py3.13
  venv): `test_quarantine_job.py` (11, incl. write-mode stamping/idempotency, dry-run
  never mutates, the two resume-mode-preservation regressions, and a route-composition
  test mirroring `test_bulk_qualification_job.py`'s pattern since the manager singleton
  isn't `Depends()`-wired) + a new `tests/test_article_quarantine_search.py` (4: FTS
  exclusion, browse exclusion + total, explicit `ids=` exclusion, structured-filter
  browse exclusion — via the `app.dependency_overrides[get_db]` isolated-engine
  pattern from `test_api_search.py`) + the backup/merge + migration regression suites,
  all green; ruff F/B clean; mypy 0 new errors (127==baseline, none attributed to any
  touched file); bandit clean. **REMAINING (S3.3–S3.5, unchanged from the S3.1 note):**
  import-time screening, the retroactive screening job's real execution (still
  gated on the maintainer's review of S3.1's calibration report — nothing in S3.2
  ran it), and the import report + post-import screen; plus the honest remainder above
  (omnibar/watches/reporting/framing exclusion, the "clear junk keywords via reindex"
  step, and any frontend trigger control — none built this slice).
  **S3.3+S3.5 SHIPPED 2026-07-23 (import-time quarantine screening + persisted
  downloadable import reports; branch `claude/oos-s3-import-report-quarantine-hook`,
  draft PR onto `main`):** extends S3.2's reversible quarantine + the ALREADY-SHIPPED
  2026-07-20 "post-import delta screen" (L6, restore-merge only, corpus-delta
  before/after inside `merge_batches.report_json` — verified via source read before
  building anything, so this slice does NOT rebuild it) to (a) the NEWSLETTER
  folder-import path, which had NEITHER a corpus-delta nor any persisted report before
  this, and (b) a standalone, DOWNLOADABLE JSON+Markdown report file for BOTH paths
  (field-feedback A1: "the persisted reports RIDE the backup export/import" — the
  restore-merge path's `merge_batches.report_json` column is not directly downloadable
  or human-readable). `default_quarantine_candidates_batch` (S3.2) gains an optional
  `article_ids: list[int] | None` parameter — when given, scans EXACTLY that explicit
  set (chunked under SQLite's ~900-bound-variable cap, mirroring the `fts_ids`/`.in_()`
  chunking precedent in `src/api/main.py`) instead of the `after_id`/`limit` range,
  processing the WHOLE set in one call rather than truncating to `limit`; the
  `after_id`/`limit` path is byte-identical when `article_ids` is `None` (11 pre-
  existing tests unchanged, +3 new: exact-set scanning, chunking past 900, and
  scoping-correctness — an id outside the given set is NEVER touched). New
  `src/backup/import_reports.py`: `persist_import_report`/`list_import_reports`/
  `read_import_report` (atomic temp-file+`os.replace` write, UTF-8, a traversal-guard
  on read mirroring `src/backup/folder_backup.py`'s `_safe_member_path` resolve-and-
  contain check) + a pure `render_import_report_markdown` (headline in the ARTICLES
  unit — never a cross-table row-sum, the maintainer's own 2026-07-20 complaint about
  "4,855,433 imported ... I'm sure it doesn't contain 5 million articles"). Wired into
  `run_restore` (`src/backup/merge.py`, reusing the SAME `merged_rows` batch-id query
  `reindex_imported_articles` already uses to get the new article-id set) and
  `NewsletterImportManager._run` (`src/ingest/import_job.py`) — both best-effort
  (try/except around corpus-delta/quarantine/report-persist, mirroring `run_restore`'s
  existing `_corpus_snapshot` try/except pattern; a hiccup never turns a successful
  restore or import into a failure). A "work induced" section reuses S1's
  `sources_pending`/`sources_candidates` qualification counters — reported as
  CORPUS-WIDE totals (no cheap before/after delta exists for them yet, stated
  explicitly in the rendering, not silently scoped-as-if-per-import). The
  `import_reports/` directory is wired into `src/backup/artifact.py`'s
  `_collect_members` (mirroring the `_ANNOTATIONS_DIR` scan exactly) so reports ride
  the encrypted oo-backup-2 export; `src/backup/folder_backup.py`'s `collect_items`
  was checked and DELIBERATELY left untouched (it only covers large, re-downloadable
  wiki/OSM/model blobs by design — small, private, generated reports don't belong in
  that category). Two new read-only endpoints on the existing `/api/backup` router:
  `GET /import-reports` (list) and `GET /import-reports/{filename}` (download,
  `?format=md` for the Markdown rendering; 404 on an unknown/traversal-attempting
  name, 400 on an unknown format). **A real coverage gap found + fixed during
  self-review, BEFORE push (no separate skeptic agent this slice — the same repo,
  same discipline, done by hand):** the first cut captured the newsletter path's
  "before" article-id baseline FRESH at the start of every `_run()` invocation
  (reasoning: "a resume's before-id should reflect reality at resume time") — but this
  meant a PAUSED run's own articles (stored before the pause, never reaching the
  success branch where quarantine/report run) were NEVER auto-screened at all, even
  once a LATER resume completed, since the resume's fresh baseline would already sit
  above them. Fixed by capturing the baseline (`_quarantine_before_id`/
  `_corpus_before`) ONCE at the TRUE start of a logical import and PERSISTING it
  across every pause/resume (a new `_quarantine_baseline_attempted` flag disambiguates
  "not yet tried" from "tried and failed" — a failed capture is NEVER guessed as `0`,
  which would have made `Article.id > 0` match every PRE-EXISTING article too; it
  instead skips quarantine/report entirely for that run, never fabricating a
  baseline). STASH-VERIFIED per this project's own discipline: temporarily reproduced
  the old fresh-per-call behavior, confirmed the new pause/resume regression test
  (`test_paused_then_resumed_import_screens_articles_from_both_halves`) FAILS exactly
  as predicted (`AssertionError: assert False is True` on the pre-pause article's
  `quarantined` flag), then restored the fix and confirmed it passes. VERIFIED
  (py3.13 venv): the full targeted sweep (`test_quarantine_job.py` 14,
  `test_import_reports.py` 8, `test_newsletter_import_job.py` 11,
  `test_backup_v2_api.py` 8, plus the existing merge/restore/torture suites — 80 tests
  total) green; ruff `--select=F,B --extend-ignore=B008` clean; mypy 0 new errors
  across every touched file (127==baseline); bandit `-r -ll -q` clean; `alembic
  check`/`heads` unaffected (no schema change this slice — reuses S3.2's columns
  as-is); i18n unaffected (2111/2111 ×12, no frontend touched). **REMAINING (S3.4,
  unchanged):** the retroactive screening job's real execution against a real corpus
  stays gated on the maintainer's review of S3.1's calibration report — nothing in
  this slice runs it; plus the honest remainder already on record (omnibar/watches/
  reporting/framing exclusion, the "clear junk keywords via reindex" step, and any
  frontend results-screen UI — deliberately out of scope, needs a browser
  click-through per fork-3/Q6a).

## Shipped batch log (compressed verdicts; details in git history + named docs)
Shipped work is tracked in **[`docs/ledger/shipped.csv`](docs/ledger/shipped.csv)** (sortable: date · area · item · status · refs · key_paths · summary) — 125 entries as of 2026-06-25. The full verbatim entries are archived in [`docs/ledger/SHIPPED_LOG.md`](docs/ledger/SHIPPED_LOG.md); deeper detail is in git history + each PR + the named design docs. Load-bearing LESSONS from shipped work live in the Session-rituals 'Lessons' subsection above (read those).

**APPEND-RULE (replaces the old inline log):** record newly-shipped work as a `shipped.csv` ROW, not a CLAUDE.md bullet. Add a verbatim entry to `SHIPPED_LOG.md` only when it carries a reusable lesson/empirical fact, and copy that lesson into the Session-rituals 'Lessons' subsection. Pending rulings, contingencies, and deliberate-omissions still go in the Open queue as prose (never compressed away).
