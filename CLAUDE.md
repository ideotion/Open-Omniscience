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
  rationale: the corpus is reconstitutable from the web). **CONTINGENCY: that
  premise EXPIRES when newsletters ship** (mailbox content is personal,
  non-reconstitutable) — consciously revisit no-recovery BEFORE the newsletter
  scraper lands.
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
   by `/api/wiki/languages` with continent `<optgroup>`s. Never a free-text input.
2. **Left sidebar lists all tabs and stays visible** — it may collapse to an
   icon rail, but must never disappear off-canvas above 600 px width.
3. **Top bar elements have constant footprints**: `.act-host` keeps its 160 px
   slot even when empty; `#llm` and `#health` have fixed min-widths; nothing on
   the right may shift as fetch hosts/labels change.
4. **A persistent compact vitals strip** (`#vitals-mini`: CPU · RAM · ↓ rate)
   lives in the top bar; the version number is NOT displayed in the chrome.
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
   constant plane glyph + label, FILL = state (filled = offline engaged);
   never ▶/⏸ action glyphs. EVERY offline→online transition passes the ONE
   consent popup (`ensureOnline`): names the action, lists LOCAL interface
   IPs from kernel tables (NEVER a public-IP echo pre-consent), honest
   public-IP wording. Scheduler responses carry `online` → immediate repaint,
   never the 5 s poll. Gated: toggle, collect (start/run-now/first-run),
   markets/indices imports, wiki page add, dump start. Enforced in
   test_ui_invariants + tests/test_network_consent.py (incl. the
   socket-importer RATCHET: no new module may import requests/httpx).
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
- Never use backticks inside `git commit -m` heredocs (shell substitution).
- Update `docs/product/RELEASE_0.1_RC_GATE.md` rows you close, every session.
- Lessons that cost a bug: duplicate top-level JS function names silently
  override — grep before declaring. Sizes lie, diffs don't (`git diff
  --numstat` before fearing loss). Agent findings get hand-re-verified before
  shipping (the 06-audit false-positive lesson).

## Open queue (when maintainer says proceed)
- **SESSION WORKING MODE (ruled 2026-06-12, this session):** reality-check the
  docs↔code gap, organize ALL open work into TOPICS (T1 performance … T20
  release-eng; the full plan lives in the session log + PR descriptions), then
  execute topic-by-topic — **ONE PR PER TOPIC**, draft onto `0.09`, CI
  subscribed, autonomously; ask only when a genuine ruling is needed.
  Reality-check verdict recorded: the ledger and RC gate are ACCURATE (961
  tests green; 28 gap claims verified in code; no shipped claim found false).
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
- **DB-RELIABILITY BATCH — REMAINING RIDERS (core SHIPPED; the Settings
  restore-preview UI SHIPPED in T6, 2026-06-12 — v2 flow primary, legacy
  demoted-not-removed):** D1/D4 state-into-DB migrations (settings/
  annotations/event-imports → tables; agenda subs server-side), signing-key
  re-wrap inside the encrypt tool, launcher/installer passphrase prompt
  wiring (whiptail box + plain fallback, confirm twice, honest
  lost-passphrase warning, optional plaintext skip with stated risk).
  **The NEWSLETTER SCRAPER stays blocked until these riders ship AND the
  no-recovery contingency is revisited** (see Non-negotiables).
- **FULL-AUDIT REMEDIATION QUEUE (from `docs/audit/06_FULL_AUDIT_0_0_9.md`,
  delivered 2026-06-11; several items already fixed in-audit):** top: qualify
  the "stays on this machine" claim ×12 locales (AWAITS MAINTAINER RULING);
  caveats-visible-by-default vs calm UI (AWAITS RULING — U3);
  ~~reliability_score=5 + language="en" defaults removal~~ (SHIPPED T5,
  2026-06-12, + political_bias=0.0; migration f4b5c6d7e8a9 NULLs the
  fabricated 5s; languages stay — catalog-asserted); ~~ETHICS.md tense~~
  (verified closed: the one "will" is the doc's own review cadence);
  REMAINING: inline-onclick retirement (199×, needs a browser-verified
  sweep); a11y batch.
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
  REMAINING: moons/seasons as default agenda EVENTS with ×12 keyword links
  (⊞ corpus entry); El Niño episodes rendered as month-span agenda banners;
  recurring-event model unifying rules + per-year instances +
  origin year ("since 1810" — the Mexico sighting was the ICS import path
  storing year-pinned instances); month-span banners ("Dry January"); the
  remaining views (week/trimester/semester/year/decade); play speeds 0.05–16×
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
  original ask (maintainer REPEAT ×2 context preserved): the
  vitals panel becomes minimized animated indicators; CLICK opens a dedicated
  OS-style task-manager window: what scrapes next, wiki-dump progress, queued
  jobs with tweak/cancel/reorder. Acceptance examples: reorder fr wiki dump
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
  Trend (ooChart)/Articles/Links sub-tabs; REMAINING: the full sub-tab set
  (mindmap/source/sentiment/competitive), the other six entries, the
  TIME-SCOPE control, one-click ingestion of linked pages):** which member
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
- **i18n & LANGUAGE UX (field report #3 + standing; SWITCHER SHIPPED T7 —
  invariant #15):** the chrome-audit burn-down is ELEVATED
  (`scripts/i18n_report.py --audit-chrome` per tab, every session, until ~0
  — the maintainer keeps hitting untranslated surfaces and "cannot test
  EVERYTHING" alone; long tail was ~473 fragments at last count). URL anchors
  stay language-neutral code identifiers (labels translate, anchors don't);
  #markets-vs-#commodities folds into the index/commodity reclassification
  (alias pattern like #database→#library). Easter eggs gain FRENCH references
  while staying transnational/translatable (personality.yml). Home-card
  TITLES are still server-built English — template-based title translation
  needs a design (titles carry data values).
- **MARKETS/INDICES/COMMODITIES (consolidated; TOOLKIT SHIPPED T8 slice 1 —
  invariant #16; REMAINING: roll ooChart onto commodity-card enlarge,
  indices board detail, timemap-adjacent charts):** Commodities cards render the real curve at every
  timeframe (drop the "· 5 pts" suffix); axes detailed; discrete gridlines.
  S&P500 is an INDEX, not a commodity — reclassify; expand feeds (rare
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
  stays labelled deduced. REMAINING: reader switches to reading the stored
  rows (stops recomputing); temporal map's mention layer consumes
  event-places; corpus-wide WHO aggregation endpoint; wiki articles join
  when the living-source design lands. NEXT for
  the extractors themselves: feed the temporal map's mention layer with text
  locations; extend the country table; aggregate entities corpus-wide.
- **Convergence + watch rules (the 0.0.9 flagship, parked from PR #51):**
  space-time co-occurrence (never causation) + the user-defined
  "if-this-then-WATCH" alert engine (explainable, off by default,
  local-only). After When×Where×Who ingest persistence.
- **Temporal map remainder:** logarithmic time scale (agreed: linear/log
  toggle, labelled ticks, no hidden warp); feed mention-layer with extracted
  event-places.
- **Home cards remainder:** per-card-TYPE /investigate views so EVERY card
  is clickable (rising→trend+associations; diet/coverage→sources;
  echo→integrity; law/wiki→reader). Card-feed visual/UX remake still wanted
  (flagship surface).
- **Evidence-tiered cards — remaining slices:** instrument the other
  9+recipe producers; corpus tier header (early/developing/established);
  power-style "what's missing"; BH-FDR later. (Slice 1 shipped: plain
  sentence + exact math, Wilson/Katz CIs, 7 producers, invariant #9.)
- **Trans-language equivalence — LIVE analytics layer (elevated):** rings
  merge inside grouped trends/trending/associations/graph levels
  (fr:élections + en:elections = ONE concept); cross-country recognition via
  per-source-country split; guards stay (language-qualified members only,
  signature-supported joins, per-language counts visible, user can split).
  Groundwork shipped (signatures in the log + curated ring file + first 10
  rings from field log #1).
- **Custody tab UX:** most users won't get it — rename/explain/guided steps.
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
