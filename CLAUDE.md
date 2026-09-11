# CLAUDE.md — long-term session memory (maintainer-mandated)

**THE PROTOCOL (meta-rule, maintainer-mandated):** this file, together with
[`docs/ledger/LESSONS.md`](docs/ledger/LESSONS.md) and
[`docs/ledger/OPEN_QUEUE.md`](docs/ledger/OPEN_QUEUE.md), is the single ledger of
every maintainer ruling. (1) **AMENDED 2026-09-07 (ruled A3(2), proposal §4.2):**
read THIS file in full before any work, every session, together with
`docs/ledger/LESSONS.md` — the two are the CONSTITUTION (non-negotiables, UI
invariants, rituals, lessons) and they are stable. Together they measure
573,850 bytes (2026-09-07, `wc -c` on the two) against the 1,417,956 this
file alone had reached, so that "in full" is achievable again. THEN open
`docs/ledger/OPEN_QUEUE.md` and read the entries relevant to the work at hand —
the queue is the DOCKET, not the constitution, and is consulted, not memorised.
Amended because the rule as written ("read it in full", one 1.3 MB file ≈ 364k
tokens) could only be obeyed by skimming, which is the failure mode it exists to
prevent. (2) Record every new ruling in the same turn it is given — a new
INVARIANT under UI invariants HERE, a PENDING ruling in
`docs/ledger/OPEN_QUEUE.md` (its LOCATION amended 2026-09-07 per A3(1); the rule
itself is unchanged); SHIPPED work goes to the CSV per (5a), not inline. (3) If the maintainer repeats
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
lesson into [`docs/ledger/LESSONS.md`](docs/ledger/LESSONS.md) (so first-readers
see it — rule (1) makes that file mandatory reading; location amended 2026-09-07
per A3(1)).
Do NOT grow a "## Shipped batch log" wall in this file again. Pending rulings,
contingencies, and deliberate-omissions STILL go in `docs/ledger/OPEN_QUEUE.md`
as prose (rule 5 protects them — never moved to the CSV).
(5b) **THE `refs` COLUMN CONVENTION (settled 2026-09-07 under question L8, whose recommended
default was "sweep them once, then record the convention"):** a row written before its PR number
exists may say `PR pending`, but that is a PLACEHOLDER, not a value — **sweep it to the real number
in the next session that touches the ledger.** Twelve rows (2026-07-18 … 2026-09-06) had carried it
for up to seven weeks; they now read `PR #706 #707 #708 #709 #711 #712 #716 #718 #724 #726 #955
#1011`. **HOW TO RESOLVE ONE, and the trap that makes it worth writing down:** binary-search `main`'s
FIRST-PARENT history for the earliest commit whose `shipped.csv` contains the row, then read the PR
number out of that merge's subject — and CHECK THE CLONE IS NOT SHALLOW FIRST (`git rev-parse
--is-shallow-repository`). This session's first attempt ran against a 56-commit shallow clone whose
OLDEST commit already contained all ten July rows, so the search returned that boundary and answered
`#944` for every one of them — ten identical, wrong, authoritative-looking PR numbers, about to be
written into the project's permanent shipped record. `git fetch --unshallow` then gave twelve
DISTINCT numbers, each independently corroborated by its merge's BRANCH NAME matching the row's
subject (`#706 claude/lemma-default-on-brief` ↔ the lemmatization row; `#726
claude/pagesize-evidence-db10` ↔ the DB-10 §1b row). A `git log -S` pickaxe is NOT a substitute — on
this history it reports the merge commit rather than the authoring one, and answered `#944` too.
(5c) **A SIZE RATCHET ENFORCES (5)/(5a) (ruled 2026-09-07, A3(4)):**
`tests/test_repo_invariants.py::test_claude_md_stays_within_its_ratchet` fails
when THIS file grows past its recorded line ceiling, and its twin fails when the
ceiling is left above the real count — zero slack, because a ratchet with room is
a ratchet that does nothing. Rules (5)/(5a) were a good intention for a year and
the file still reached 1.3 MB; this is the mechanical enforcement the ledger
reaches for in its best moments. Raising the ceiling is normal for a PR that adds
a non-negotiable, a UI invariant, or an amendment to the protocol itself — and is
never the way to make room for something rules (5)/(5a) would have sent to
`docs/ledger/`.

## Non-negotiables (project §0.5 + maintainer rulings)
- Local-first, loopback-only; every external call is consented, disclosed, and
  socket-level kill-switch-gated (exceptions enumerated in `docs/SECURITY.md`,
  never here). Producers/briefing/discovery never touch the network; boot makes zero calls.
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
- **THE SSRF GUARD IS CONNECT-TIME, NOT ONLY PRE-FETCH (NET-01, closed 2026-09-07,
  live-reproduced first):** `_guard_target` resolves the target and refuses a non-public
  answer — which is NOT the resolution the connection uses, since requests/urllib3 resolve
  the same name again inside `create_connection`; a resolver answering public at guard time
  and `127.0.0.1` at connect time fetched a loopback server's body as a clean 200.
  `src/ingest/ssrf_guard.py` now validates, for ONE fetch on ONE thread, every address a
  resolution ANSWERS with and every address a connect is HANDED — entered by
  `_guarded_redirect_get` (the one method every fetch, robots read, redirect hop and
  preflight side door passes through) and hooked into `airplane.py`'s ONE socket patch layer,
  so the two gates cannot be held apart. It deliberately does NOT pin the validated IP:
  pinning needs urllib3's private connection construction plus a hand-carried hostname for
  SNI/cert matching, and fails OPEN when that moves, where this fails CLOSED.
  `OO_SSRF_CONNECT_GUARD=0` disables (its own flag, never the airplane one). Enforced by
  tests/test_ssrf_connect_guard.py.
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
9. **Evidence-tiered cards carry a trigger audit trail** (ruled 2026-06-10):
   every card explains itself in plain words FIRST ("Why am I seeing this?"),
   with the exact math beneath ("The exact math"), both translatable ×12.
   Enforced in test_ui_invariants (#9).
10. **Bundled open-source fonts, never an external font host** (ruled
   2026-06-11): OFL license texts ship in the repo alongside the six bundled
   `.woff2` families (Cantarell, Inter, Outfit, Manrope, JetBrains Mono,
   Source Serif 4) under `src/static/fonts/`; `@font-face` declarations are
   local (≥6 in `index.html`); `fonts.googleapis.com`/`fonts.gstatic.com`
   must never appear. Enforced in test_ui_invariants (#10).
11. **Themed form widgets** (the Settings "font cursor" bug, 2026-06-11):
   range sliders are styled to the active theme
   (`input[type="range"]::-webkit-slider-thumb`); the retired drawer's dead
   `.drawer .seg` selector scoping must never regress back in. Enforced in
   test_ui_invariants (#11).
12. **The Typeface picker exists, and the theme catalog never shrinks**:
   `#dr-faces` must be present, and the theme catalog is pinned at ≥16
   `html[data-theme="..."]` CSS blocks (17 named themes; Ink lives in
   `:root`, System is JS-only). Enforced in test_ui_invariants (#12).
13. **The agenda shows DATA, never plumbing** (maintainer principle
   2026-06-11): the calendar-feed directory (`#agenda-feeds`) never appears
   inside the Agenda tab itself; it lives in Settings (`#set-agenda`).
   **AMENDED 2026-07-31:** the directory moved one level further out — out of
   the Agenda SUBTAB and into Advanced (`#set-advanced`), on the same
   principle (it is the catalogue that FEEDS the agenda, not agenda
   configuration) — pinned so it cannot drift back into either place. The
   month grid + view switcher (`#agenda-month`/`#agenda-views`) are the tab's
   default view (`localStorage["oo.agenda.view"] || "month"`). **13b:**
   article-DEDUCED dates flow through the SAME event pipeline as imported
   events (`/api/events/deduced` → `mapDeducedToAgenda`) as their own
   filterable `"deduced"` category, the never-confirmed caveat visible, and a
   deduced event's title opens the EXACT article set that produced it
   (`openAnalysisForIds`). Enforced in test_ui_invariants (#13).
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
   markets/indices imports, wiki page add, dump start, dump size read,
   OpenTimestamps anchor (manual button + turning the setting on). Enforced in
   test_ui_invariants + tests/test_network_consent.py (incl. the
   socket-importer RATCHET: no new module may import requests/httpx).
   **EXTENDED #14e (2026-09-07, from a measured breach): THE GATE COVERS WHAT THE
   UI DOES TO HELP YOU DECIDE, NOT ONLY THE ACTION.** "dump size read" joins the
   list because the "Estimate size" button egressed a live HEAD to
   dumps.wikimedia.org with NO `ensureOnline`, for years, beside a "Download"
   button that had one — a preview reads as *looking*, not as *doing*, which is
   exactly where a gate gets forgotten. So the RULE, not just the list: after
   gating an action, gate every estimate, preview, validation, reachability check
   or autocomplete that runs BEFORE it, because those egress first. COROLLARY,
   from the same breach: a refusal BY THE KILL SWITCH must be named as such
   wherever it can surface — that probe reported airplane mode as "size check
   failed", pointing an operator at someone else's server for their own setting.
   **EXTENDED #14f (P1 audit finding, 2026-09-08): the SAME failure shape recurring
   in a path #14e's own fix never touched.** OpenTimestamps chain-of-custody
   anchoring — a real submission to three public Bitcoin calendar servers,
   revealing IP + timing — had NO consent gate on any of its three reachable paths:
   the `POST /api/custody/anchor` endpoint, the manual "Anchor root" button, and
   (worst) `anchoring_mode: "opentimestamps"` firing silently on EVERY future
   ingested article once the setting is on, with no button click of its own. Fixed
   coherently across all three: `anchorRoot()` gates through `ensureOnline` before
   a non-local anchor (mirrors every other button); the endpoint itself refuses
   (400) an `"opentimestamps"` anchor without an explicit `consent: true`, so a
   caller that never went through the UI gets the same honest refusal (scoped to
   `"opentimestamps"` only — the already-refusing public-chain stubs keep their own
   503, never masked by a consent 400); and — since the per-ingest path has no
   later button to gate — `saveCustody()` demands a genuine, one-time `confirm()`
   naming the RECURRING nature of the egress at the moment the operator turns the
   setting ON, and `save_settings()` mirrors that requirement server-side
   (`ots_consent: true`, required only on the local→opentimestamps TRANSITION, not
   re-demanded on every resave — a stamp on every save would be a rubber stamp, not
   informed consent). `ots_stamp()` (the shared egress point for both the endpoint
   and the per-ingest path) also gained an early, NAMED kill-switch refusal before
   any calendar is even constructed, closing the #14e corollary for this path too.
   Enforced in test_ui_invariants (#14f) + tests/test_custody_consent_gates.py +
   tests/test_custody_api.py + tests/test_custody_settings.py. **THE TOOLING GAP THIS
   ENTRY NOTED IS CLOSED (2026-09-10), by the future session it asked for:** the
   `test_network_consent.py` socket-importer ratchet matched only `requests`/`httpx`
   imports, so it was blind to `opentimestamps.calendar` — and equally to imaplib,
   poplib, http.client and bare `socket`. It now covers 16 socket-capable libraries,
   every allowlisted module carrying a written reason. Measured, not assumed: a new
   `import imaplib` PASSES the old ratchet and FAILS the new one.
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
   Schedule · Coverage · System; the live job controls + vitals reused
   unchanged). **ACTIVE/QUEUE
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
   test_ui_invariants (#20 + #20b + #20c). **COVERAGE SUBTAB SHIPPED
   (2026-07-01/07-02, PR #534):** a 5th subtab (`#tm-coverage` / `#cov-tm-body`,
   `data-tab="coverage"` via ooSubtabs) surfaces per-tag scraping REACH — which
   catalog tags have been reached, how many sources remain, at what percentage —
   built ONLY from the collector's own fetch timestamps
   (`FeedFetchState.last_checked_at`/`last_status`/`skip_until`): reach/fresh/
   never_reached/backed_off counts, status mix, oldest-age, least-reached-first
   ordering, honest method+caveat strings — counts only, NEVER a fabricated
   completion claim or score. `loadTagCoverage`/`_renderCoverage` read the
   read-only `/api/scheduler/coverage` endpoint, loaded lazily when the subtab
   opens. Enforced in test_ui_invariants (#20e); ledgered in `shipped.csv`
   (`scheduler/coverage`, 2026-07-02). PER-JOB CONTROLS EXTENDED (Item 2,
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
   tests/test_jobs_resume.py.
   **PER-JOB RATE + ETA SHIPPED 2026-09-07 (PERF-09), exactly as the omission
   specified:** the owners now measure their OWN bytes-over-time
   (`src/ingest/download_rate.py`, ONE `RateSampler`/`RateRegistry` wired into
   BOTH `_download` loops), so the rate is taken where the bytes land rather than
   guessed by the client across the adaptive poll. The refusals are the invariant:
   an unmeasurable rate is ABSENT with a reason, never `0` (a `0` reads as
   "stalled", a different fact); samples are pruned against a FRESH clock at READ
   time, so a stalled transfer ages out and reports its idle time instead of
   repeating its last healthy figure; `reset()` on start AND resume means a pause
   is never charged as slowness; nothing is persisted, so after a restart a
   download is honestly unmeasured; and the ETA rides ONLY on a measured rate AND
   the server's real Content-Length — never a catalog size estimate. The task
   manager draws a measured rate (method on hover) and a STALL, and draws NOTHING
   otherwise. Enforced by tests/test_download_rate.py,
   tests/test_download_rate_ui.py + download_rate_note_node_test.js.
   REMAINING: History; the per-job BANDWIDTH CAP — still DELIBERATELY omitted, and
   the reason has moved on: throttling is a change to the fetch loop's BEHAVIOUR
   rather than a measurement, and it needs a ruling the code cannot make for
   itself — whether the budget is per-job or per-process, and how it composes with
   the collection-speed governor (`#rate-toggle`, invariant #4), which already owns
   a global rate target. A second, unrelated rate authority beside it is how two
   surfaces come to disagree about one quantity.
21. **INSIGHTS auto-indexes; no "Index corpus" button (UI_SHELL §6, SHIPPED
   #132):** indexing follows ingest (the index_article hook) + a SILENT
   background top-up (`autoIndexInsights`) clears any legacy backlog when
   Insights opens (the "N to index" count ticks to 0 on its own); the button +
   its palette action are removed. Insights sections were already subtabs (#127).
   Enforced in test_ui_invariants (#21).
22. **The analysis window** (Group F, keystone #4): a full-screen
   `#tab-analyze` window driven by THE universal subtab component
   (`ooSubtabs($("an-subtabs")...)`), opened from the Search tab's Analyze
   button — never a sidebar entry, retired 2026-06-20 — and fed by the
   article-SET keyword endpoint (`/api/insights/corpus-keywords` via
   `openAnalysis(`). Its subtabs are all article-set AGGREGATIONS over the
   matched set — counts, never a verdict: When/Where/Who
   (`/api/insights/corpus-www`, clickable facets drilling via
   `/api/insights/corpus-facet-articles`), shared-origin Links
   (`/api/links/corpus`), Sentiment (`/api/insights/corpus-sentiment`),
   source coverage (`/api/insights/corpus-sources`), and Advanced-search
   (`anRunAdvanced`, re-runs the analysis from refined filters). **22b:** a
   commodity click opens the window with a conditionally-shown Price subtab
   overlaying the price curve with the corpus coverage timeline on a shared
   time axis (dual labelled axes; co-occurrence, never causation). Enforced
   in test_ui_invariants (#22 + #22b).
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
31. **THE OBSERVATORY IS A LENS, NEVER A SECOND SOURCE OF TRUTH (ruled 2026-07-18;
   BUILT 2026-09-07, Chromium-verified in the remote sandbox, awaiting the human UX
   pass):** the corpus as a deterministic night sky — a DEDICATED main tab (the #2
   roster grows by one), whole-corpus v1, hand-rolled canvas 2D (no WebGL, no
   Three.js, no CDN). `src/static/oosky.js` owns the pure polar geometry;
   `app-observatory.js` the wiring. THE FIVE THINGS THAT MAY NOT REGRESS: (a) ONE
   measure per channel, never a blend — ANGLE = the domain wedge (labelled, with
   stable-hash jitter inside it disclosed as meaningless), RADIUS = one chosen
   measure with LABELLED orbit gridlines, SIZE = mentions via `sqrtAreaScale` (AREA
   ∝ value) with a reference-star legend, COLOUR = language or the trend lens and
   NEVER the only signal. (b) THE TWO REFUSALS: `radialScale` refuses the log mode
   below one full decade and says which scale it drew instead (the recorded `logY`
   defect — `distinct_sources` tops out at 7 on a real corpus, so this is the common
   path); a galaxy whose measure is ZERO gets no coordinate at all and goes to a
   labelled outer band (52 of 77 on a young corpus). (c) The RANKED TABLE renders in
   FULL beside the sky — it is the canonical view (#8), never truncated, and both
   orders come from the one `rankedGalaxies`. (d) The anti-capping line names every
   population the picture omits ("N plotted · N not observed yet · M in the
   nebula"). (e) Constellation edges are DRAWN from a measured shared member, never
   from proximity; the trend lens leaves `growth_is_ratio:false` uncoloured, because
   that `growth` is the recent COUNT and painting it would fabricate a decline.
   Deterministic by construction (`ooViz.mulberry32`, never `Math.random`): same
   corpus → same sky, so CHANGE is signal. Static when idle; depth is navigational
   only and marks are screen-space sized. Enforced by
   tests/test_observatory_ui.py + tests/oosky_node_test.js (20 checks, mostly
   negative space) + test_ui_invariants (#31).
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
- Update the CURRENT release-gate rows you close, every session — today
  `docs/product/RELEASE_0.3_GATE.md` and `RELEASE_0.4_GATE.md`. (This line named
  `RELEASE_0.1_RC_GATE.md`, which has not existed for two cycles; corrected 2026-09-07,
  after it sent a session looking for it.)
- **PER-RELEASE: RE-CONFIRM THE NO-TELEMETRY CLAIM (recorded 2026-09-07; it existed in no memory
  file, only in a PR body).** `docs/legal/POLITIQUE_DE_CONFIDENTIALITE.md` and its 11 translations,
  plus `docs/USER_MANUAL.md`, state to the user that the app sends no telemetry. That is a
  LEGALLY-BINDING claim about the software's behaviour, made in a first-launch-gated document the
  user must accept — and nothing in the release process re-confirms it, so it is a claim the code
  could silently outgrow. Before a tag: run the socket-importer RATCHET (the
  `test_network_consent.py` guard that no new module may import `requests`/`httpx`) and re-read the
  outbound call sites, then say in the release notes that it was checked. This is a CHECK, not a
  new mechanism: the structural guards exist and the boot-makes-zero-network-calls non-negotiable
  is tested; what was missing is anyone being told to look at the claim itself each cycle. The
  legal `[À VÉRIFIER]` markers are NOT in the same position — they are recorded in
  `docs/legal/IMPLEMENTATION_NOTES.md` §3 and test-guarded by `tests/test_legal_documents.py`
  (which asserts no document in any of the 12 languages still carries an unresolved bracket); the
  professional-verification gap those notes describe is a permanent, stated choice, never a to-do.
- Lessons that cost a bug: duplicate top-level JS function names silently
  override — grep before declaring. Sizes lie, diffs don't (`git diff
  --numstat` before fearing loss). A ledger merge is NOT resolved until
  `grep -n '^<<<<<<<\|^=======$\|^>>>>>>>' CLAUDE.md docs/ledger/*.md docs/ledger/*.csv`
  returns nothing — the 2026-07-18 b9dcbcc merge committed unresolved conflict
  markers INTO CLAUDE.md on main because only shipped.csv was verified (fixed
  same day; both sides were kept additively, as the ledger rule requires). **AND THAT GREP IS
  BLIND TO `shipped.csv`, WHICH IS THE FILE IT NAMES (2026-09-07):** `.gitattributes` sets
  `merge=union` on it, so it NEVER produces a conflict marker — union keeps both sides' lines
  and reports success. That is correct for an append-only file and silently WRONG for any row
  the other side EDITED: main's docs reality-check rewrote eleven historical rows, and the one
  this branch also carried came out as TWO rows — the stale `PR pending` text beside main's
  corrected `PR #1011`. A marker grep cannot see it and neither can a clean `git merge`. The
  check that works is a DUPLICATE-KEY scan over `(date, area, item)`, compared against the
  COMMON ANCESTOR rather than against zero — nine duplicates already existed there, so a bare
  "are there duplicates" test would have accused this merge of nine things it did not do. The
  tell in the diff is a numstat with DELETIONS on a merge you expect to be purely additive.
  **AND IT RECURRED ON THE VERY NEXT BRANCH, WITH THE TELL FIRING AND A CHECK THAT WAS NOT THIS
  ONE (2026-09-07, the same row):** any branch cut BEFORE a `PR pending` sweep re-creates the
  duplicate on its own merge, because its stale copy and main's corrected one are both legitimate
  lines — and one did, on this same 2026-09-06 row. The numstat tell FIRED (17 added / 11 deleted)
  and was investigated by PAIRING each deleted row with its replacement; that came back clean and
  was not the prescribed scan. Pairing accounts for the rows main edited that the branch does NOT
  also carry, and is structurally blind to the one it DOES, because there each copy legitimately
  belongs to one side and neither is unpaired. So run the duplicate-key scan ITSELF: a different
  check that plausibly explains the same tell is not a substitute for the one named here.
  Agent findings get hand-re-verified before
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
- **Lessons — MOVED to [`docs/ledger/LESSONS.md`](docs/ledger/LESSONS.md)** (ruled
  2026-09-07, A3(1)). The reusable lessons and empirical facts harvested from shipped work
  moved there VERBATIM. **They remain MANDATORY READING every session, exactly as when they
  were inline** — only the file changed (rule (1)). New lessons are appended there per
  rule (5a)(b).

## Open queue — MOVED to [`docs/ledger/OPEN_QUEUE.md`](docs/ledger/OPEN_QUEUE.md)
Every pending maintainer ruling, contingency and deliberate-omission note moved there
VERBATIM on 2026-09-07 (ruled A3(1)), byte-identical. Nothing was summarised, reworded or
dropped — rule (5) protects every one of them.

**It is the docket, not the constitution:** consult the entries relevant to the work at hand
rather than reading all of it (rule (1)). New rulings are recorded THERE, in the turn they
are given (rule (2)).

## Shipped batch log (compressed verdicts; details in git history + named docs)
Shipped work is tracked in **[`docs/ledger/shipped.csv`](docs/ledger/shipped.csv)** (sortable: date · area · item · status · refs · key_paths · summary) — 961 entries as of 2026-09-11. The full verbatim entries are archived in [`docs/ledger/SHIPPED_LOG.md`](docs/ledger/SHIPPED_LOG.md); deeper detail is in git history + each PR + the named design docs. Load-bearing LESSONS from shipped work live in [`docs/ledger/LESSONS.md`](docs/ledger/LESSONS.md) (read those — mandatory every session, per rule (1)).

**APPEND-RULE (replaces the old inline log):** record newly-shipped work as a `shipped.csv` ROW, not a CLAUDE.md bullet. Add a verbatim entry to `SHIPPED_LOG.md` only when it carries a reusable lesson/empirical fact, and copy that lesson into [`docs/ledger/LESSONS.md`](docs/ledger/LESSONS.md). Pending rulings, contingencies, and deliberate-omissions still go in [`docs/ledger/OPEN_QUEUE.md`](docs/ledger/OPEN_QUEUE.md) as prose (never compressed away).
