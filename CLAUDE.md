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
   **AMENDED (ruled 2026-06-16, PENDING build): DROP the continent `<optgroup>`
   grouping** — editions are LANGUAGE-based, not country/continent-based (a
   language spans many continents), so the continent split is a category error
   and "not useful anymore." Render a FLAT list instead (default order: UI-locales
   / largest-edition-first; native-name labels per invariant #15). Applies to BOTH
   pickers fed by the endpoint (`wiki-lang` watched editions + `dump-lang` dumps);
   `/api/wiki/languages` stops emitting/using the by-continent `groups`. The
   `<select>`/never-free-text CORE stays (test #1 unchanged — it never asserted the
   optgroups; do NOT add a grouping assertion).
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
   test_ui_invariants (#20 + #20b + #20c). REMAINING: History, per-job
   bandwidth/ETA controls.
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
  session, per the maintainer's "implement now or mark it"). Design points to
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
  DEFERRED by maintainer; when resumed, the recommended target is the #an flagship
  (route openCorpus → #an, port #corpus's Trend + Competitive over, retire the
  modal). Until then BOTH exist and work; do NOT build new sub-tabs on either
  without first deciding the canonical window.** **EARLIER NOTE: full sub-tab set complete
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
  points. Enforced by test_ui_invariants #16. REMAINING in this commodities item:
  (1) category subtabs, (2) the time-scope range control, (4) click-a-graph →
  the analysis window. Precision limited ONLY by gathered data + renderer.
  (4) CLICK A GRAPH → a DEDICATED WINDOW/TAB (like search results), NOT the
  bottom-of-page #mkt-chart (index.html:1214, current onclick chartSymbol →
  detail+correlation at the bottom). The window IS the corpora flagship with
  the coherent sub-tabs: keywords · When/Where/Who · mindmap · corpus
  analytics · source analytics · links · the price curve with the article
  timeline OVERLAID (commodity-click → keyword-family corpus, already ruled in
  the corpora entry; co-occurrence NEVER causation). S&P500 is an INDEX, not a
  commodity — reclassify; expand feeds (rare
  earths, oil, gas, LNG, sand, cereals, sugar…). **Tor/indices diagnosis
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
  **INLINE AUTO SIZE ESTIMATES (ruled 2026-06-16): show EACH dump-eligible
  edition's estimated size INLINE & AUTOMATICALLY in the picker — drop the
  per-selection click + the "Estimate size" button** (today #dump-lang multi-select
  → probeDump() → GET /api/wiki/dumps/probe = a LIVE per-edition network HEAD to
  the dump server, index.html ~1721-1736 / wiki.py:271 probe_size). HONEST
  CONSTRAINT (binding): showing all sizes must NOT fire N network probes at open
  (breaks zero-network boot + airplane). SO: ship a BUNDLED, DATE-STAMPED
  per-edition size TABLE (WIKI_SIZES_AS_OF + a freshness test — the model-catalog
  CATALOG_AS_OF pattern; tiny metadata, NOT the dumps) rendered inline with an
  "estimate · as of DATE · exact on download" caveat ×12 — zero-network, instant.
  REPLACE the per-edition probe with ONE consented "refresh exact sizes" that
  fetches live sizes in a SINGLE call (the dump date's dumpstatus.json lists every
  edition at once, not N HEADs) through the guarded factory + the ONE consent
  (#14). Delivers the cleaner UX without a network burst.
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
  entities corpus-wide.
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
  REMAINING: the user-defined "if-this-then-WATCH" alert engine (explainable, off by
  default, local-only) — its UX is a GENUINE RULING to bring to the maintainer
  before building; plus the convergence FRONTEND view (the endpoint is its substrate).
- **Temporal map remainder:** logarithmic time scale (agreed: linear/log
  toggle, labelled ticks, no hidden warp); feed mention-layer with extracted
  event-places.
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
- **UI RETHINK — MAINTAINER PLANNING SESSION 2026-06-16 (DESIGN-ONLY, not built;
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
  - **(3) NAME THE CARD SYSTEM (brainstorm WITH the maintainer — NO name chosen
    yet):** today = "briefing cards" / "producers" / "buckets" (src/briefing). A
    card = one measured signal + evidence + method + caveat = a SOURCED, CAVEATED
    PROMPT TO INVESTIGATE ("assistance never a verdict"; "a microscope not a
    detector"; "name the shape"). Seeded candidates: Leads · Cues · Soundings ·
    Readouts · Vantages (NOTE: "Signals" collides with src/signals/). **RESOLVED
    2026-06-16 → "LEADS"** (a card = a Lead: an investigative starting point to
    dig). Rename the USER-FACING label ×12 locales; the internal src/briefing
    module + bucket names can stay or rename later (cosmetic).
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
    subtab (#ins-trends). THIRD-WINDOW SPAN still PENDING the maintainer's pick
    (month / year / all-time).
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
  after unlock. (b) "Scraping STOPPED" is NOT a crash — the scheduler idles
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
- **Trans-language equivalence — LIVE analytics layer (elevated):** rings
  merge inside grouped trends/trending/associations/graph levels
  (fr:élections + en:elections = ONE concept); cross-country recognition via
  per-source-country split; guards stay (language-qualified members only,
  signature-supported joins, per-language counts visible, user can split).
  Groundwork shipped (signatures in the log + curated ring file + first 10
  rings from field log #1).
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
