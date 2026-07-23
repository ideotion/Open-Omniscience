# Shipped batch log — archive (moved out of CLAUDE.md 2026-06-25)

> The full, verbatim shipped-work entries that used to live under `CLAUDE.md` → '## Shipped batch log'. Moved here to keep CLAUDE.md readable (maintainer-asked). The terse, sortable tracking index is [`shipped.csv`](shipped.csv); the load-bearing LESSONS are curated into CLAUDE.md's Session-rituals 'Lessons' subsection. Full detail of any item is also in git history + its PR + the named design docs. APPEND new shipped work as a `shipped.csv` row (+ a verbatim entry here if it carries a reusable lesson), NOT as a CLAUDE.md bullet.

## Shipped batch log (compressed verdicts; details in git history + named docs)
- **OMNIBUS SESSION — STANDING SOURCE AUDITOR + Part-3A surfacing (2026-07-13, executing
  `docs/design/ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md`; DRAFT-PR-only, nothing auto-merges):** Item 0
  (ledger + the 6 rulings) merged #662; **Item 2** = the standing source AUDITOR (`src/analytics/source_audit.py`,
  draft PR #663) — the one-shot source-quality diagnostic generalised into a continuous quality GATE, the board's
  own linchpin. FLAG-ONLY (ruling Q2a): auto-demote machinery built but DEFAULT-OFF. Per-source
  extraction-VALIDITY status (healthy/watch/degraded/failing) = the categorical rollup of a cohort-relative
  criteria LIST (value+baseline+n each), never a score; audits usable-article-vs-nav/stub, NEVER editorial merit
  (soft style-ambiguous signals never exceed `watch`); reuses the source_quality collectors count-only (no content
  decrypt); a per-region self-audit + allowlist cap; read-only `/api/diagnostics/source-audit{,-selftest}` + Settings
  buttons. 18 tests, ruff/mypy/i18n clean. **Item 1** (draft PR #664): (a) AI-keyword lens VERIFIED already surfaced
  (`view_article`, the #388 work — staleness win, not rebuilt); (b) a subjectivity "Loaded language" reader tab
  (conservative, browser-unverified per Q6a); (c) El Niño banners PARKED (flagged-unverified data + span-banners
  unsupported). Items 3 (discovery funnel) / 4 / 5 / 6-stretch parked with specs (a dedicated-session backend +
  browser-unverified frontend). TWO REUSABLE LESSONS (curated into CLAUDE.md Session-rituals): **(1)** a categorical
  status containing a banned score-substring (`"degraded"` ⊃ `"grade"`) trips the recursive no-score KEY-walkers —
  keep per-status tallies as `{status,n}` VALUE objects, never status-as-key (the canonical `assert_no_score_fields`
  wouldn't catch it, but the per-module test-walkers do). **(2)** a cohort-relative `v>p90` tail goes BLIND when
  many members are bad (nearest-rank p90 lands on a bad value) — the auditor reads `healthy` exactly when a whole
  cohort degrades; give the HIGH-CONFIDENCE extraction-failure signal an ABSOLUTE floor (never the style-ambiguous
  soft criteria), and TEST the malign direction (a worst source in a degraded/absent cohort still flags), not just
  the benign zero-spread side. Found by an adversarial `code-reviewer` skeptic (negative-space lens), hand-verified,
  fixed + regression-pinned before push.
- **OMNIBUS CONTINUATION — DISCOVERY FUNNEL (2026-07-14, "continue with all remaining items"; draft PR #667 onto
  0.2):** Item 3 / Part-3B + Phase 2 STARTED, two verified backend slices. **(1)** the flagship
  **Wikipedia-references channel** (ruling Q3a): `extract_reference_domains` (PURE, zero-network — every external
  http(s) URL in the already-stored watched-page wikitext → registrable domain, EXCLUDING Wikimedia self/interwiki/
  asset hosts + inline images + commerce/social/infra noise; empty inputs → empty, never a fabricated candidate) +
  `wikipedia_reference_channel` (aggregates the references of every WATCHED page across editions, registers a domain
  cited by ≥N distinct pages as a DISABLED `SourceCandidate`, editions carried as the diversity signal), wired into
  `run_discovery` inside the existing rollback savepoint. Negative-space lens pinned as tests (9). **(2)** **wire the
  dormant external_sources** (ruling Q4a): `discovered_via` provenance column + `resolve_external_source` idempotent
  first-writer-wins upsert wired into `_add_candidate` (never writes the legacy credibility_score) — the funnel's
  resolution table, dormancy ended; additive migration + boot self-heal, `test_no_model_drift` green (5 tests).
  PARKED (the dedicated Phase-2 slice): the promotion frontier (candidate→trial→graduated, trial auto-enable
  DEFAULT-OFF, diversity-weighted, the auditor as the graduation gate) + the browser-verified audit view + undo +
  the citing-trail surface. Items 4/5/6 stay parked (browser-verify-gated frontend / dormant stretch). LESSON (also
  in Session-rituals): a hand-picked alembic revision id COLLIDES with the exhausted formulaic ids and surfaces as a
  confusing "Cycle detected", caught by `test_no_model_drift`; get the real head from `alembic heads` (CLI), not a
  regex scan, and pick a random id. ruff/mypy clean; 101 tests green across migrations + discovery + the auditor.
- **OLLAMA BINARY INSTALLER — Settings → AI (2026-06-30, branch claude/ai-ollama-installer-zun7pb; backend
  VERIFIED py3.13, frontend BROWSER-UNVERIFIED per fork-3):** the genuinely-unbuilt half of model management
  (maintainer field test 2026-06-20 "can't find the AI installer"; maintainer Q7=B 2026-06-16). The blocker
  was always "we can't fabricate per-OS installer checksums." RESOLVED WITHOUT FABRICATION — **GitHub's
  releases API attests a `digest: sha256:…` per asset**, so the app verifies against the publisher's OWN
  attestation. `src/llm/installer.py`: `resolve_and_verify(get_json, get_bytes)` fetches the ollama/ollama
  LATEST release through the guarded factory, finds the official `install.sh` asset + its attested digest,
  downloads the script, SHA-256s the bytes, and refuses on mismatch OR when no sha256 is attested
  (`InstallerVerificationError` — never run unverified code); `prepare_installer` is kill-switch gated (no
  socket under airplane) + platform-gated (Linux scripted; macOS/Windows → honest ollama.com/download
  pointer, Debian is the V0.1 target); `stage_installer` writes the verified bytes to
  `data_dir()/runtime/ollama-install-<sha16>.sh` (0700) and `run_installer` REFUSES anything outside that
  staging dir, running it ONLY when elevation is non-interactive (root or passwordless `sudo -n`, so the
  TTY-less web backend can never hang on a password prompt) else raising with the verified `sudo sh <path>`
  command for the user's terminal. The script's own later binary download egresses over CLEARNET via curl
  (Q9, disclosed at consent). Endpoints (src/api/llm.py): `GET /api/llm/install/status` (present? scripted?
  unattended-elevation? staged?), `POST /install/prepare` (409 airplane / 502 verification), `POST
  /install/run` (NDJSON stream of the script's output + exit code). Frontend (index.html + app.js): a
  `#llm-install-box` panel in Settings → AI shown ONLY when Ollama is absent → `loadOllamaInstall` →
  `prepareOllamaInstall` (gated by ensureOnline #14, clearnet disclosure; shows verified version + sha) →
  `runOllamaInstall` (streams the log) or the verified command → `recheckOllama`. tests/test_ollama_installer.py
  (12: verify accepts a matching digest, refuses mismatch / missing attestation / absent asset; prepare
  stages + airplane-refuses + unsupported-OS-refuses; run refuses outside staging / wrong name / no-elevation;
  root-run reports exit 0) + test_repo_invariants::test_ollama_binary_installer. VERIFIED here: 12 + 199
  invariants/llm green, ruff F/B clean (new module), i18n 100% (English-fallback via t(), no new locale keys),
  routes compose, TestClient status 200. EMPIRICAL FACT (curated into the Lessons subsection): GitHub release
  assets carry an attested `digest` field — verify against it, never hardcode/fabricate a checksum. REMAINING:
  human click-through (fork-3); key the panel strings ×12; an optional task-manager job over a long install.
- **AUTONOMOUS BATCH 2026-06-25 (maintainer: "continue autonomously with all remaining tasks, I'll merge all
  PRs afterwards" — the harness constrains me to ONE branch `claude/ecstatic-edison-mseu1p`, so the remaining
  §5B/§5C arc lands as a STACKED SERIES OF COMMITS in one draft PR onto 0.09; each commit self-contained +
  verified). Items shipped below in order. CI-FIX (PR #481 `test` lane red on my SHA): `test_stats_map_store.py`'s
  `_assert_no_score` did a naive `repr(out).lower()` substring check, but the map CAVEAT legitimately says
  "never a score" → tripped (it had been red since #479, which the maintainer fast-merged). Rewrote it to walk
  KEYS recursively (the honesty invariant is about field NAMES, not values) — same fix already applied to
  test_outrage.py. LESSON: a no-score test helper must check field NAMES, never the repr — a caveat that says
  "never a score" is GOOD and must not trip the guard; grep `repr(.*).lower()`+score before shipping.**
- **OUTRAGE-INTENSITY — the 9th manipulation measure, SECONDARY (§5C; autonomous batch; pure module VERIFIED
  py3.11 [6 tests] + ruff F/B + mypy 0-new; the headline-body wiring runs in CI).** Per the ledger ruling
  outrage-intensity is SECONDARY — it ANNOTATES another card, NEVER a standalone Home Lead — so this ships the
  pure measure + wires it as a component on the existing headline-body card, with NO new producer registered.
  `src/analytics/outrage.py:outrage_intensity(text, language)` names a STRUCTURE never intent/truth: the DENSITY
  of curated English intensifier/loaded markers among tokens + the '!' count + ALL-CAPS-run count. HONESTY in
  the SHAPE: ENGLISH-ONLY like the VADER baseline — a non-English / empty / UNKNOWN-language text returns a
  stated GAP (`measured:False` + reason), NEVER a fabricated 0 (an untagged text is NOT assumed English — the
  lexicon would mis-measure it); NO score (returns density + its COMPONENTS [matched markers, !, caps, n], no
  `*score*`/`*rank*` key — recursively guarded); the lexicon is an explicit modest in-code HEURISTIC (not a
  lexicon of record, not a dated `*_AS_OF` artifact → no registry entry), tunable from the diagnostics logs; the
  innocent-twin caveat (a measured opinion/editorial naturally uses intense language) travels. PURE (stdlib re
  only) so it imports + tests in the bare sandbox. WIRED as a SECONDARY annotation in
  `headline_body.find_headline_body_mismatch` — each fired item gains an `outrage` component (the body's density,
  English-only, its own caveat) decorating that card, never its own Lead. tests/test_outrage.py (6: english
  measured+components, calm→0, non-English gap [never a 0], unknown-language not-assumed-English, empty gap,
  caveat states structure-not-intent — all run in the sandbox) + test_headline_body.py extended (item carries
  `outrage`, recursively no score-key). The remaining manipulation cards (bury-half of #4, event-timed-op) stay
  external-dependency-gated (a trigger / the elections roster). REMAINING: surface the outrage annotation in the
  analysis UI; a per-language lexicon beyond the English baseline.
- **ooMap STATS CHOROPLETH — the §5B Phase C visible capstone (autonomous batch; backend iso2 bridge VERIFIED
  py3.11 + ruff F/B + mypy 0-new; frontend BROWSER-UNVERIFIED per fork-3 — node --check + invariant-guarded +
  i18n 100%).** Makes the whole arc visible: colour a world map by ONE official-statistics indicator, through
  the ONE `ooMap` component + the node-tested `ooViz.choroplethData` honesty gate (#478) — NOT a second map
  component (the "one ooMap" ruling), placed in Settings → Statistics beside the chart + revision-anomalies (its
  own stats surface; the Governments Map subtab stays the curated-WB-country view). BACKEND: `store.map_figures`
  now enriches each cell with an `iso2` (lowercase alpha-2 via `catalog.countries.to_iso2`: the producer's
  ref_area — alpha-3 for WB/OWID, alpha-2 for Eurostat — converts; a non-country aggregate WLD/EUU → None so the
  map DROPS it honestly, never plots an aggregate as a country) so the renderer keys on it with NO frontend ISO
  table. FRONTEND `renderStatMap()` (app.js, beside renderStatChart, English-only like the chart panel): fetches
  `/api/stats/map?series_id=&agency=`, runs `choroplethData` over the cells, and for the NORMALIZED case builds
  `values[iso2]=value` for COMPARABLE cells only → `ooMap` colours them (an incomparable-basis or no-value cell
  is omitted → ooMap's no-data hatch, NEVER recoloured onto one scale; a null iso2 aggregate dropped). The
  comparability summary (N comparable · M on a different basis (no-data) · K no value) + the gate caveat are
  VISIBLE; `multi_producer` adds a "pin a producer — the map never averages them" note. A LEVEL (the "this is a
  count/total" checkbox → `kind:"level"`) REFUSES the choropleth honestly (`mode:"symbols"`) — shows the refusal
  reason + the comparable values as a ranked table (true proportional-symbol rendering deferred — colouring a
  level would make a big country look like "more" just for being big). Controls: a `statfig-map-agency` input +
  the level checkbox + a "Map by country" button (inline onclick, matching the panel's local convention). NO new
  i18n keys (English literals like renderStatChart → gate stays 100%). tests/test_stats_map_store.py +1
  (iso2 bridge: FRA→fr, DE→de, WLD→None) + test_repo_invariants::test_stats_choropleth_map_surface (controls +
  handler + ooMap reuse + choroplethData gate + the iso2 key) + the feed test asserts the to_iso2 enrichment.
  REMAINING: true proportional-symbol rendering for levels (centroids needed); human click-through (fork-3); a
  period/indicator picker; key the panel strings ×12 with the rest of the Statistics panel.
- **JSON-STAT LIVE FETCH CLIENT — unlocks the parse_jsonstat parser for real data (§5B Phase E; autonomous
  batch; backend ALGORITHM VERIFIED py3.11 standalone repro using the real `parse_jsonstat` + ruff F/B + mypy
  0-new, the fetch/endpoint test runs in CI).** The `parse_jsonstat` parser (#469, JSON-stat v2/v1 → figures)
  had NO live data path; this adds it (symmetric to the OWID-CSV client). NEW `fetch.fetch_jsonstat(url, *,
  agency, series_id=None, get=None, extracted_at=None)`: JSON-stat producers (Eurostat's JSON-stat endpoint,
  IRENA, PxWeb instances [Statistics Sweden/Norway/Finland]) have wildly different URL schemes, so the CALLER
  supplies the documented query URL VERBATIM — we NEVER fabricate an endpoint (a wrong URL fails LOUDLY: HTTP
  error / unreadable shape → no rows, never a fabricated figure). A non-http(s) URL is rejected LOUDLY
  (ValueError → a clean 422). Same safety shape as the other fetchers: kill switch refuses UP FRONT (no socket
  offline — testable with an injected getter), injectable `get`, `extracted_at` stamps the vintage; delegates
  to the offline `parse_jsonstat` (honesty carries: a `null` cell → `value=None`, never a fabricated 0;
  `series_id` pins a single-series slice for unambiguous rows). WIRED into `POST /api/stats/figures/fetch` as
  `source:"jsonstat"|"json-stat"|"pxweb"` (FigureFetchBody gains `url`/`series_id`; the non-http ValueError →
  422). Like owid, jsonstat auto-refresh is a follow-on (the URL-based fetch isn't replayable by the current
  subscription model), so it's excluded from the WB/SDMX-scoped subscription recording — never an unreplayable
  sub. tests/test_stats_jsonstat_fetch.py (4: caller-url passthrough + delegate + gap kept None + series_id/
  agency/vintage carried, non-http rejected, kill-switch refuses-no-socket on injected AND default paths) —
  CI-only (the guarded factory pulls in cryptography); the URL-guard + delegation ALGORITHM proven by a
  standalone py3.11 repro against the real `parse_jsonstat`. ruff F/B clean; 0 new mypy errors; no UI strings.
  The stats subsystem now has THREE live ingestion paths (WB/Eurostat SDMX-JSON · OWID CSV · JSON-stat) feeding
  the full pipeline. REMAINING: curated JSON-stat/OWID endpoint catalogs (verify on a networked box — 403 here);
  jsonstat/owid subscription auto-refresh.
- **OWID-CSV LIVE FETCH CLIENT — unlocks the parse_csv parser for real data (§5B Phase A-CSV; same single-branch
  harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the freshly-merged 0.09 after #479 merged; NEW
  draft PR onto 0.09; backend ALGORITHM VERIFIED py3.11 standalone repro using the real `parse_csv` + ruff F/B +
  mypy 0-new, the fetch/endpoint test runs in CI).** The `parse_csv` parser (#469, OWID grapher tidy CSV → figures)
  had NO live data path; this adds it, following the established `fetch.py` pattern (guarded factory · kill-switch
  refusal up front · injectable getter · transport never downgraded · delegate parsing to the offline module). NEW
  `fetch.owid_grapher_url(slug)` → the documented OWID per-chart "Full data (CSV)" export
  `https://ourworldindata.org/grapher/<slug>.csv?v=1&csvType=full&useColumnShortNames=true` (`OWID_GRAPHER_BASE`,
  verify-on-use — a wrong slug fails LOUDLY [HTTP error / no rows], never a fabricated figure; covered by the
  existing `STATS_API_AS_OF`, NO new dated constant so the freshness-registry protocol guard is untouched). NEW
  `fetch.fetch_owid(slug, *, value_col=None, series_id=None, agency="owid", area_col="Entity", code_col="Code",
  time_col="Year", unit/base_year/adjustment=None, get=None, extracted_at=None)`: refuses UP FRONT under airplane
  mode (no socket — testable with an injected getter), GETs the TEXT, and hands it to the real `parse_csv`.
  `value_col` is AUTO-DETECTED as the single non-key column (a tidy OWID grapher CSV — Entity/Code/Year/<metric> —
  has exactly one; `_owid_value_column` via the csv reader so a quoted comma'd column name is handled), and a CSV
  with several data columns raises LOUDLY (pass `value_col` — never guess among many). `series_id` defaults to the
  slug (the stable chart id); the comparability fields come from the caller's curated config, verbatim, never
  inferred (OWID CSVs carry no machine-readable unit). Honesty carries through `parse_csv`: a blank cell →
  `value=None` (a published gap, never a fabricated 0), `Code` → `ref_area`, `extracted_at` the caller vintage.
  WIRED into the ONE networked action `POST /api/stats/figures/fetch` as `source:"owid"` (FigureFetchBody gains
  `slug`/`value_col`/`unit`; the ambiguous-value-column ValueError → a clean 422 naming the columns). owid
  subscription auto-refresh is a FOLLOW-ON (the replay can't reconstruct a slug fetch yet), so the subscription
  recording is scoped to the WB/SDMX families — never records an unreplayable sub. tests/test_stats_owid_fetch.py
  (8: url shape/encoding/empty-rejects, autodetect+delegate+gap+url-recorded, explicit value_col+unit+series_id,
  ambiguous-raises-loudly, kill-switch-refuses-no-socket on the injected AND default-getter paths) — runs in CI
  (the guarded factory pulls in cryptography, which panics in the bare sandbox = the documented CI-only pattern);
  the URL + auto-detect + delegation ALGORITHM was proven by a standalone py3.11 repro importing only the
  stdlib-only `parse_csv`. ruff F/B clean; fetch.py + api/stats.py add 0 mypy errors; no UI strings (i18n
  untouched). REMAINING: a curated OWID slug catalog (verify slugs on a networked box — 403 here); owid
  subscription auto-refresh; the Eurostat JSON-stat fetch client (the JSON-stat parser also lacks a live path);
  the ooMap stats layer frontend.
- **CHOROPLETH STORE FEED + /api/stats/map ENDPOINT (§5B Phase C, the DATA feed for the pure ooViz layer;
  same single-branch harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the freshly-merged 0.09 after
  #478 merged; NEW draft PR onto 0.09; backend ALGORITHM VERIFIED py3.11 standalone repro + ruff F/B + mypy
  0-new, the ORM/endpoint test runs in CI).** The backend feed for the `choroplethData` honesty layer shipped
  in #478. `store.map_figures(session, *, series_id, agency=None, time_period=None, limit=2000)` loads the
  matching `StatFigureRow`s, keeps the latest VINTAGE per (agency,series,area,period) via the existing
  `_latest_vintage`, and emits ONE cell per `ref_area` — the area's LATEST period (reusing `series._parse_period`
  via new `_period_key`/`_area_more_recent`: later period wins, tie→later vintage) or a pinned `time_period`.
  Each cell carries the producer's published value + its comparability fields (unit/base_year/adjustment) so the
  frontend `ooViz.choroplethData` applies the gate. HONESTY: a map is SINGLE-PRODUCER per series — when several
  agencies report it and no `agency` is pinned, the most recent VINTAGE is shown per area and `multi_producer` is
  FLAGGED (the caller pins an agency to disambiguate) — the map NEVER averages producers and never silently
  elects a 'true' one; a published gap rides through as `value=None` (never a fabricated zero); `periods`/
  `agencies` are returned so a surface can offer a period/producer selector; counts only, NO score (regex/repr
  grep-guarded in the test). `GET /api/stats/map` (series_id required; agency/time_period/limit optional) — the
  established stats-endpoint pattern (`session_scope` → store fn → dict), a thin wrapper identical to
  `figure_series`. tests/test_stats_map_store.py (6: one-cell-per-area-at-each-latest-period + deterministic
  area sort + newest-first periods, latest-vintage-wins, pin-a-period, multi-producer-flag + agency-pins-one
  [never an average of 30 & 31], carries-a-gap + comparability fields, empty-honest) over an in-memory SQLite
  (CI, needs sqlalchemy — the ORM pulls bleach etc. so it can't run in the bare sandbox; the ALGORITHM was
  proven by a standalone repro mirroring all 6 cases + a mixed-granularity case, importing only the stdlib-only
  `_parse_period`). test_repo_invariants::test_stats_choropleth_feed_and_data_layer greps the store feed (+ the
  no-average caveat) + the endpoint + the two pure ooViz functions. ruff F/B clean; store.py + api/stats.py add
  0 mypy errors (the 29 reported are pre-existing baseline import-closure errors in other files). NO new
  `*_AS_OF`/registry entry; no UI strings (i18n untouched, 100%). REMAINING: the ooMap STATS LAYER (choropleth
  for normalized indicators via `choroplethData`+`ooMap` country fills + the `to_iso2` bridge; proportional
  symbols via `symbolRadii` for levels; an indicator/period/agency picker; the `multi_producer` flag surfaced)
  — browser-unverified per fork-3, the next slice; the OWID-CSV / Eurostat-JSON-stat fetch clients that feed
  real data into the parsers.
- **ooViz CHOROPLETH DATA LAYER — the "normalized-only" ruling made concrete (§5B Phase C, the pure honesty
  core; same single-branch harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the freshly-merged 0.09
  after #477 merged; NEW draft PR onto 0.09; FULLY NODE-VERIFIED [22 node tests, +8] + node --check + ruff
  F/B + i18n gate unchanged 100%).** The §5B research's open ruling — "choropleth NORMALIZED-only; levels →
  proportional symbols; never compare incomparable denominators silently" — built as TWO pure `src/static/
  ooviz.js` functions whose honesty lives in the SHAPE of the output (no DOM, no network, no score, fully
  node-testable BEFORE any browser map): (1) `choroplethData(rows, opts)` over StatFigure-shaped rows
  {ref_area, value, unit, base_year, adjustment, time_period} enforces the COMPARABILITY GATE — only areas
  sharing the MODAL (unit, base-year, seasonal-adjustment) basis are colour-eligible (`comparable:true`); an
  area on a DIFFERENT basis is `comparable:false` with a reason naming the differing dimension (so the
  renderer shows it as no-data, NEVER recoloured onto one scale — the brief's "never compare incomparable
  denominators silently"), a missing value is its OWN no-data reason, and the colour DOMAIN spans comparable
  values ONLY (a stray incomparable figure can't stretch the scale). It picks ONE cell per area (the requested
  `opts.period`, else each area's LATEST via `periodToYear` — annual/semester/quarter/month/week/day decimal-
  year, junk→NaN→raw-string tiebreak, mirroring `series.py _parse_period`). `opts.kind==="level"` (a count/
  total like population/GDP) REFUSES the choropleth (`mode:"symbols"`, `refusedChoropleth:true`) — colouring a
  level makes a big area look "more" just for being big — defaulting to `"normalized"` (rate/ratio/%/per-capita)
  → `mode:"choropleth"`. (2) `symbolRadii(cells, maxRadius)` = the LEVEL companion: AREA-honest radii via the
  existing `sqrtAreaScale` over the max comparable non-negative value (4× value → 2× radius, never 4×), with
  incomparable/missing/NEGATIVE values `shown:false` + a reason (never a fake dot). PURE, deterministic, NO
  score; vintage dedup is the caller's job (one value per area+period). NOT YET WIRED — the backend
  `/api/stats/map` (latest-vintage figures per ref_area for a series) + the ooMap render (it already has
  country fills + `to_iso2`; this is its honest stats data-prep + the symbol overlay) are the CI-verified +
  browser-unverified follow-ons. tests/ooviz_node_test.js (+8: periodToYear, the comparability gate refuses to
  recolour an odd-unit outlier, missing-value-is-its-own-no-data, latest-period selection, opts.period filter,
  level→symbols refusal, area-honest+negative-not-shown radii, empty-honest) — runs in the sandbox AND CI;
  test_ooviz.py grep-guards both functions. node --check clean; ruff F/B clean (test file); i18n 100%
  (1669 ×12, no UI strings). REMAINING: the `/api/stats/map` endpoint + store query + the ooMap stats layer
  (choropleth for normalized indicators, proportional symbols for levels); the OWID-CSV / Eurostat-JSON-stat
  fetch clients that feed real data into the parsers; the §5B Phase-C choropleth UI.
- **i18n — KEY THE NEW STATISTICS-PANEL STRINGS ×12 (§5C #17 burn-down; closes the #474/#476 loop) 2026-06-25
  (same single-branch harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the freshly-merged 0.09
  after #476 merged; NEW draft PR onto 0.09; VERIFIED: i18n gate `--min 100` 100% [1669/1669 ×12] + audit
  drop + clean-append diff).** The revision-anomalies (#474) + stat-chart (#476) panel strings shipped
  English-fallback; the maintainer repeatedly flags untranslated surfaces, and both ledger entries flagged
  "key ×12" as REMAINING — done. Keyed the 7 byte-exact strings: the headings "Revision anomalies" / "Check
  revision anomalies", the "Area (for the chart)" label + "Chart over time" button, the two button `title`
  attrs (the "Flag a stored figure…" + "Plot the series…" hovers), and the long "History must not be silently
  rewritten…" intro paragraph (the §5B sensitivity-wording copy — translated faithfully preserving the exact
  claims: retrospective-only / never-a-forecast / names-the-shape-not-the-intent / no-score). Appended into all
  12 locale files via the established TEXT-APPEND method (no json re-dump → zero reformat; diff is +8/−1 per
  file = the 7 keys + a comma on the prior-last line), keys resolved BYTE-EXACT from the live `--audit-chrome`
  output (the recurring apostrophe/em-dash trap). en value = the key; the 11 non-en are AI-DRAFTED, FLAGGED for
  native review (esp. the long honesty paragraph + the ar RTL + zh/ja). Validated: every locale parses, carries
  all 7 keys, gate stays 100%, the strings are GONE from the audit. No code change. REMAINING i18n tail: the
  JS-rendered table headers / empty-states in those panels still need `t()` (interpolated literals, the
  standing limitation) + the broader ~100-string audit-chrome tail.
- **STAT TIME-SERIES CHART (§5B Phase B3) 2026-06-25 (the honest-chart payoff — draws the merged feed via the
  merged ooViz primitives; same single-branch harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the
  freshly-merged 0.09 after #475 merged; NEW draft PR onto 0.09; the chart MATH is node-VERIFIED [14/14 node
  tests], the SVG ASSEMBLY is BROWSER-UNVERIFIED per fork-3 — node --check + grep-invariant-guarded + i18n
  100%).** Wires the whole stats-viz arc into a visible chart in Settings → Statistics. (1) `ooViz.statChart
  Geometry(series, opts)` — a NEW PURE, node-tested geometry helper (added to the merged ooviz.js): from a
  `to_chart_series` result it computes the value domain (min/max of PLOTTABLE values — a gap/None NEVER pulls
  it toward 0), the time domain (spans ALL points incl. gaps, so a gap leaves a hole and never shifts the
  axis), the linear scales, the pixel-space `paths` (delegates to `statSeriesPaths` — ONE per comparability
  segment, gaps broken), and the niceTicks x/y tick positions; empty → a unit box (no throw). 3 new node tests.
  (2) `ooviz.js` is now LOADED before app.js (`<script src="/static/ooviz.js">` after osmpbf.js → `window.
  ooViz`). (3) Settings → Statistics gained an Area input + "Chart over time" button + `#statfig-chart`; (4)
  `renderStatChart()` (app.js, beside the other stat handlers) fetches `/api/stats/figures/series`, runs the
  node-tested geometry, and templates an SVG — each comparability SEGMENT a SEPARATE `<path>` (a unit/base-
  year/SA-NSA break is a visible GAP between paths, NEVER a joined line), gridlines + value/year tick labels
  via the smart formatter, `role="img"` + aria-label + a `.sr-only` data table (a11y, invariant #24), the
  honesty CAVEAT visible, honest empty/error states; theme-token strokes (`var(--accent)`/`var(--muted)`).
  NO backend change; NO new `*_AS_OF`; NO new i18n keys (English-fallback like the adjacent stat strings — gate
  100%). test_repo_invariants::test_stat_time_series_chart_surface (ooviz-before-app load order + the controls
  + the handler fetching the feed through `ooViz.statChartGeometry` + the caveat render + the helper
  export). The official-statistics ingestion → honest-VIZ arc is now end-to-end (parse → adapt → feed →
  chart). REMAINING: human click-through across themes (fork-3); key the new strings ×12; the choropleth
  comparability precheck (Phase C); wire ooViz's pathWithGaps into the GENERAL ooChart for app-wide gap honesty.
- **CHART-SERIES STORE-PULL + /api/stats/figures/series ENDPOINT 2026-06-25 (the honest-chart DATA FEED;
  same single-branch harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the freshly-merged 0.09 after
  #474 merged; NEW draft PR onto 0.09; backend ADAPTER+to_chart_series logic VERIFIED py3.11 standalone + ruff
  F/B/full + mypy 0-new, the ORM/endpoint test runs in CI).** The feed the stat time-series chart (Phase B3)
  needs. `store.chart_series(session, *, series_id, ref_area, agency=None)` loads the matching `StatFigureRow`s
  for ONE (series_id, ref_area), adapts each via `StatFigure(**_row_dict(r))` (same DRY adapter as the revision
  store-pull), and runs the pure merged `to_chart_series` — so the honesty lives in the SHAPE: a new line
  SEGMENT at every unit / base-year / SA-NSA change (NEVER joined across the break), a published gap kept as
  `None` (the chart breaks the line, never interpolates), unparseable periods surfaced, latest-vintage-wins
  dedup, counts only no score. `GET /api/stats/figures/series` (series_id + ref_area required, agency optional
  — scope a single producer; omit only when one publishes the series, else use /triangulate). tests/
  test_stats_chart_series_store.py (3: segments-at-a-base-year-break + keeps-the-gap, scopes-by-agency,
  empty-honest) over an in-memory SQLite (CI, needs sqlalchemy). NO new `*_AS_OF`/registry; no UI strings.
  REMAINING: the Settings → Statistics SVG time-series CHART drawing `ooViz.statSeriesPaths` over this feed
  (Phase B3, browser-deferred — comparability breaks marked, gaps shown, the caveat visible); choropleth
  (Phase C).
- **REVISION-ANOMALIES GUI SURFACE (Settings → Statistics) 2026-06-25 (makes the merged reliable-memory
  endpoint GUI-reachable; same single-branch harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the
  freshly-merged 0.09 after #473 merged; NEW draft PR onto 0.09; FRONTEND, BROWSER-UNVERIFIED per fork-3 —
  node --check + grep-invariant-guarded + i18n 100%).** The reliable-memory check (`/api/stats/revision-
  anomalies`, merged #472) had no GUI; the maintainer field-tests the GUI. Added a "Revision anomalies"
  section to the Settings → Statistics panel (index.html, after the triangulate box): a "Check revision
  anomalies" button → `loadRevisionAnomalies()` (app.js, beside the other `loadStatFigures`/`triangulateStat
  Series` handlers, same `$`/`api`/`esc`/`_statfigFmt` pattern + Loading/empty/error states) fetches the
  endpoint (optionally scoped to the typed `statfig-view-series` id, else corpus-wide) and renders the flagged
  revisions as a table — agency·series·area·period · from→to (+rel%) · change · robust z · #priors · revised-at
  — with the honesty envelope (the method + the innocent-twin CAVEAT) VISIBLE by default (informed-consent
  #23), and an honest empty state ("a figure needs several prior revisions before an outlier can be judged").
  The section's intro states the mission verbatim ("History must not be silently rewritten … retrospective …
  names the shape … never the intent"). NO backend change; NO new i18n keys (English-fallback like the
  adjacent figures/triangulate strings — gate stays 100%, keyable in an i18n slice); the §5B "sensitivity
  wording" ruling still applies to this copy (already conservative). test_repo_invariants::
  test_revision_anomalies_statistics_surface greps `_ui_source()` for the box + handler + endpoint + the
  method/caveat render. REMAINING: human click-through (fork-3); the stat TIME-SERIES chart drawing
  `ooViz.statSeriesPaths` (Phase B3); key the new strings ×12.
- **ooViz HONEST-CHART PRIMITIVES + statSeriesPaths (§5B Phase B2 foundation) 2026-06-25 (same single-branch
  harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the freshly-merged 0.09 after #472 merged; NEW
  draft PR onto 0.09; FULLY node-VERIFIED here — 11/11 node tests + node --check + ruff/mypy on the wrapper,
  frontend LIVE-WIRING browser-unverified per fork-3).** Adopted the MIT research primitive set
  `docs/research/dataviz/honest-charts.js` into the app as `src/static/ooviz.js` — a classic dual node/browser
  module (IIFE attaching `root.ooViz=API` + `module.exports=API`, the osmpbf.js convention), zero-dependency,
  deterministic (no Math.random — seeded mulberry32), no network/DOM for the math: clamp · isMissing (a true
  gap, never zero) · linearScale · sqrtAreaScale (AREA-honest symbol sizing) · niceTicks · mulberry32 ·
  pathWithGaps (BREAKS the line at a gap, never bridges) · binCounts1D · bin2D · fiveNumberSummary ·
  setupCanvas · readCssVar. PLUS the Phase B2 consumer of the merged Phase B1 adapter: `statSeriesPaths(series,
  sx, sy)` renders a `to_chart_series` result as an array of SVG subpaths — ONE per comparability SEGMENT (a
  unit / base-year / SA-NSA break is NEVER joined — separate `d` strings, proven), each internally broken at
  its value=null gaps; carries each segment's unit/base_year/adjustment + n so the renderer marks the break.
  Honesty is in the SHAPE of the output (no interpolation across a gap OR a break). tests/ooviz_node_test.js
  (11, node:assert, prints "OOVIZ OK") run in CI by tests/test_ooviz.py (subprocess + skipif-no-node, mirrors
  test_osmpbf_parser.py) + a self-contained guard (dual-export present, network/dependency-free: no
  fetch/XHR/import/require). NO new `*_AS_OF`/registry; NO UI strings (pure chart math → i18n untouched). NOT
  WIRED into a live <script>/ooChart yet — the foundation ships node-tested-but-unwired (the parsers'
  "foundation first" pattern); the browser-deferred follow-on draws these paths in ooChart + the Settings →
  Statistics chart. REMAINING: ooChart wiring + the stats time-series chart UI (Phase B3) + choropleth (Phase
  C); the Settings → Statistics "Revision anomalies" surface.
- **REVISION-ANOMALY STORE-PULL + ENDPOINT 2026-06-25 (wires the merged detector to a reachable API; same
  single-branch harness, branch `claude/ecstatic-edison-mseu1p` re-cut from the freshly-merged 0.09 after #471
  merged; NEW draft PR onto 0.09; backend ADAPTER+DETECTOR logic VERIFIED py3.11 standalone + ruff F/B/full +
  mypy 0-new, the ORM/endpoint test runs in CI).** Makes the reliable-memory kernel reachable. `store.py`
  gained `revision_anomalies(session, *, agency/series_id/ref_area filters, min_prior_revisions=4, z_min=3.5)`
  — loads the FULL vintage trail (every `extracted_at`, NEVER latest-only — the revision history IS the point)
  for the matching `StatFigureRow`s, adapts each via `StatFigure(**_row_dict(r))` (the row dict keys are
  exactly the dataclass fields — DRY, proven standalone), and delegates to the pure merged
  `find_revision_anomalies`. `GET /api/stats/revision-anomalies` (the established stats-endpoint pattern:
  `session_scope` → store fn → dict) with the same filters + bounded params; the honesty envelope (method +
  innocent-twin caveat, retrospective-only, no score) travels through unchanged. tests/
  test_stats_revision_store.py (3: flags a stored outlier across vintages, scopes by series, empty store →
  silent) over an in-memory SQLite (mirrors test_stats_store.py — CI, needs sqlalchemy). Also a drive-by
  `typing.Iterable`→`collections.abc.Iterable` modernization in the edited store.py (pre-existing UP035).
  REMAINING: the Settings → Statistics "Revision anomalies" UI surface (browser-unverifiable, the natural
  follow-on slice — how figures/triangulate shipped backend-then-frontend); a Home Lead is NOT pursued (a
  revision anomaly is about a stat figure, not an article corpus, so it doesn't fit the article-card model —
  the Statistics panel is its honest home). The §5B "sensitivity wording" open ruling still applies to the
  eventual UI copy.
- **REVISION-ANOMALY DETECTOR over StatFigure vintages 2026-06-25 (§5B research's "highest-value independent
  slice" — the reliable-memory kernel; same single-branch harness, branch `claude/ecstatic-edison-mseu1p`
  re-cut from the freshly-merged 0.09 after #470 merged; NEW draft PR onto 0.09; backend VERIFIED py3.11
  standalone [8 tests] + ruff F/B/full + mypy 0-new).** The project's deepest intention is reliable memory —
  History must not be SILENTLY rewritten — and official statistics ARE rewritten every vintage. `src/stats/
  revision.py:find_revision_anomalies(figures)` flags, RETROSPECTIVELY, when the MOST RECENT vintage moved a
  PAST figure by a magnitude that is an outlier vs that observation's OWN earlier revisions: it groups
  StatFigure vintages by (agency·series·area·period), orders by `extracted_at`, collapses no-change re-fetches,
  and robust-z-scores the latest revision against the median±MAD of the cell's prior revisions (flags at
  robust_z≥z_min[3.5] with ≥min_prior_revisions[4] non-zero-spread priors). PURE + MODEL-FREE (no FM, no
  network — respects the no-torch-in-core + no-price-prediction non-negotiables; any FM would be an optional
  external Ollama-style process, never a core dep). HONESTY enforced in code per the §7 non-negotiables +
  manipulation-card doctrine: RETROSPECTIVE-ONLY (compares to EARLIER revisions, never predicts, has no band
  to cross the last obs); NAMES THE SHAPE not the intent (an outlier-sized revision, never a manipulation
  claim — the innocent twin [benchmark/methodology update, late source, correction] is stated in the caveat);
  carries COMPONENTS (from/to value, abs/rel change, the cell's median±MAD revision, robust_z), NO composite
  score (regex-guarded incl. a no-forecast/predict-key guard); a thin OR perfectly-uniform (MAD=0) history
  DEGRADES TO SILENCE (no robust scale ⇒ no claim — a deliberate conservatism, test-pinned). Consumes
  `list[StatFigure]` (the subsystem's pure currency, same as `to_chart_series`; the store's vintage trail maps
  to it). tests/test_stats_revision.py (8: flags-the-outlier-with-components / order-independent / thin →
  silence / within-spread → silence / uniform → silence / None-vintage-breaks-no-chain / no-revision → silence
  / multi-cell-only-anomalous / retrospective+no-score). NO new `*_AS_OF`/registry entry; no UI strings. NOT
  YET WIRED — the store-pull (load all vintages for a series → feed the detector) + an `/api/stats/revision-
  anomalies` endpoint + a Home Lead producer are the CI-verified follow-on. OPEN (maintainer polish, non-
  blocking — the pure core surfaces nothing to a user yet): the exact UI-facing "sensitivity wording on
  flagging official figures" (§5B open ruling) — the method/caveat here are written conservatively
  (descriptive · innocent-twin-first · no verdict) and are re-wordable when surfaced.
- **BULK STATS PARSERS — wide CSV + ZIP container (V-Dem/UCDP) 2026-06-25 (§5B Phase E "bulk-ZIP-CSV"; same
  single-branch harness fallback, branch `claude/ecstatic-edison-mseu1p` re-cut from the freshly-merged 0.09
  after #469 merged; NEW draft PR onto 0.09; backend VERIFIED py3.11 standalone [14 tests] + ruff F/B/full +
  mypy 0-new).** The single-cell parsers (sdmx.py) handle one observation per row; V-Dem (hundreds of indicator
  columns) + OWID-energy are WIDE, and V-Dem/UCDP ship as ZIPs — neither was ingestable. `src/stats/bulk.py`
  (pure, stdlib `csv`/`zipfile`, reuses the sdmx coercions/column-resolver within the package): (1) `parse_csv_wide`
  — projects a wide CSV (one row per area+period, MANY indicator columns) to one `StatFigure` per (row, indicator)
  in a SINGLE pass (calling the single-column parser once per indicator would re-read the file N times for V-Dem's
  hundreds of columns), `series_id`=the column name, a blank/NA indicator cell → `value=None` (published gap, kept),
  per-indicator `units`/`base_years`/`adjustments` are OPTIONAL caller-config maps (verbatim or None, never
  inferred), a missing required column/indicator raises loudly, a ragged row skips only its missing cell (never
  invents one); (2) `zip_csv_members` (list the `.csv` members) + `read_zip_member` (decode ONE member — `None`
  auto-picks the single `.csv` and raises on zero/many so the caller never gets a silent guess; an unknown member
  raises; a `max_bytes` ceiling [default 1 GiB] makes a ZIP-bomb member degrade LOUDLY, only that much ever
  decompressed into memory). Inherits all sdmx honesty (gap→None, caller-stamped vintage, comparability
  only-when-stated, NO score — regex-guarded). tests/test_stats_bulk.py (14) imports only the pure modules → runs
  in the bare sandbox AND CI; end-to-end ZIP→read→wide-figures proven. NO new `*_AS_OF`/registry entry
  (format-only); no UI strings (i18n untouched). The parser-core trio is now COMPLETE (WB/SDMX + CSV/JSON-stat +
  wide/ZIP). NOT YET WIRED to fetch/store/endpoints (the "parser core first, live fetch next" slice). REMAINING:
  the ooViz/ooChart Phase-B2 renderer (consumes the Phase-B1 `to_chart_series` adapter); the OWID/Eurostat/V-Dem
  fetch clients + ingest wiring.
- **OFFLINE STATS PARSERS — CSV (OWID) + JSON-stat (Eurostat/IRENA/PxWeb) 2026-06-25 (§5B Phase A-CSV +
  Phase E parser unlock; SESSION NOTE: single-branch harness fallback — develop on
  `claude/ecstatic-edison-mseu1p`, ONE branch, draft PR onto 0.09; the §5B research "open decisions"
  [retrospective-only / classical-first / choropleth-normalized] are viz/forecast rulings, N/A to a pure
  parser — the maintainer already greenlit CSV+JSON-stat parsers in 5D/5F; backend VERIFIED py3.11 standalone
  [16 tests] + ruff F/B/full + mypy 0-new).** `src/stats/sdmx.py` only handled WB-JSON + SDMX-JSON 2.1, so
  the research-flagged best-verified global data (OWID energy/CO₂ via CSV) and all of Eurostat + IRENA (via
  JSON-stat) were un-ingestable. Added TWO pure parsers to the same offline parser core (no network, no ORM —
  it takes already-decoded `str`/`dict`, the module's standing contract): (1) `parse_csv` — a tidy/long CSV
  (the OWID grapher "Full data" shape) → `StatFigure`s; the caller maps the columns EXPLICITLY (a CSV carries
  no self-describing dimension metadata, so the parser NEVER guesses which column is which), `ref_area` prefers
  a stable `code_col` (ISO3) then the entity name, a blank/`NA`/`:` value cell becomes `value=None` (a published
  gap, kept, never a fabricated 0), `series_id` + comparability fields come from the caller's curated config
  (`None` when unstated, never inferred), a missing REQUIRED column raises loudly, header whitespace/case
  tolerated (the only normalisations). (2) `parse_jsonstat` — JSON-stat v2 `class:"dataset"` (+ the v1
  `{"dataset":{…}}` wrapper) → `StatFigure`s; decomposes the row-major flat `value` array/sparse object back to
  each cell's per-dimension category id (geo→`ref_area`, time→`time_period`, indicator→`series_id` unless the
  caller pins it, unit→label + `base_year` only when the label literally states `YYYY=100`, s_adj→`adjustment`),
  a DENSE `null` cell kept as a gap, a SPARSE object emits only present keys, a size/category mismatch bails
  honestly (no half-parsed rows), `index` as `{id:pos}` map OR ordered list both handled. HONESTY mirrors the
  existing core: gap→None, comparability only-when-stated, vintage `extracted_at` caller-stamped verbatim, NO
  composite score (regex-guarded over every `to_dict` key). tests/test_stats_csv_jsonstat_parse.py (16) imports
  ONLY the pure module → runs in the bare sandbox AND CI (unlike the briefing-coupled test_sdmx_parse.py). NO
  new `*_AS_OF`/registry entry (format-only code); no UI strings (i18n untouched). PLUS (same PR/branch, the
  next pure layer — §5B Phase B1 `StatFigure[] → chart series`): `src/stats/series.py:to_chart_series` adapts a
  figure list into a time-ordered, JSON-ready chart series with the honesty baked into its SHAPE — COMPARABILITY
  SEGMENTATION (a new line segment starts at every unit / base-year / SA-NSA change so an "Index 2010=100" run
  is NEVER joined to a "2015=100" one, and SA is never joined to NSA — the brief's "never compare incomparable
  denominators silently"), a `value=None` kept in place as a GAP (the chart breaks the line, never interpolates/
  zeroes), period parsing (annual/semester/quarter/month/week/day → a decimal-year x placed at the period
  START) with UNPARSEABLE labels surfaced in `unparseable_periods` never positioned at a guessed x, vintage
  dedup (latest `extracted_at` wins per [period, comparability]; ISO-8601 UTC sorts chronologically), filterable
  by ref_area/series_id, mixed-granularity flagged, NO score (recursively regex-guarded over the whole output).
  Pure (stdlib re/datetime + StatFigure), no ORM/network. tests/test_stats_series.py (13) imports only the pure
  modules → runs in the sandbox AND CI. NOT YET WIRED to fetch/store/endpoints — the established "parser core
  first, live fetch next" slice (how sdmx.py itself shipped); the adapter is the Phase B2 chart layer's input.
  REMAINING: the ooViz/ooChart gap-subpath + comparability-break renderer (Phase B2, reuse `docs/research/
  dataviz/honest-charts.js` `pathWithGaps`); the OWID-CSV + Eurostat-JSON-stat fetch clients + ingest wiring
  (the §5B Phase A "wire Pacific Data Hub + ECB" + Phase E follow-ons); bulk-ZIP-CSV (V-Dem/UCDP) is the next
  parser.
- **STATUS-BAR TRANSPARENCY — remark 14 REOPENED + FIXED 2026-06-25 (field report: "top status bar still
  transparent, content overlaps when scrolling"; branch claude/vibrant-thompson-bez6dq, draft PR onto 0.09;
  CSS one-liner, BROWSER-UNVERIFIED per fork-3).** The #460 fix put `background:var(--bg2)` on the CHILDREN
  (`.topbar` + `.subtab-strip`) but NOT on the sticky WRAPPER `.chrome` (`app.css:127`, `position:sticky;top:0`).
  When the facet strip is HIDDEN (most tabs) or a sub-pixel seam exists, scrolled content shows through the
  transparent wrapper — exactly the field report. FIX: `background:var(--bg2)` on `.chrome` itself (belt-and-
  braces: the whole sticky region is opaque regardless of which children are present). Guard EXTENDED:
  test_settings_chrome_cleanups now asserts the `.chrome` rule carries the bg (the old guard only checked the
  children — which is how the gap slipped). FUTURE_DEVELOPMENTS remark 14 flipped [x]→[~] with the diagnosis +
  the "if still see-through: stale build / translucent theme --bg2 / GUI-skin restyle" follow-ups. Confirm on
  click-through. LESSON: an opaque-chrome guard must assert the STICKY CONTAINER's bg, not just its children.
- **BRIEF-STATUS AUDIT + FUTURE_DEVELOPMENTS UNRESOLVED SECTION 2026-06-25 (maintainer-asked "add to future
  developments everything that was not or partially resolved"; branch claude/vibrant-thompson-bez6dq, draft PR
  onto 0.09; DOC-ONLY).** Ran a 6-agent parallel read-only audit (Workflow, ultracode opt-in) verifying all 31
  items of `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-06-24.md` against the ACTUAL tree, then wrote an
  authoritative "AUTONOMOUS BRIEF 2026-06-24 — UNRESOLVED & PARTIAL (audited 2026-06-25)" section into
  `docs/FUTURE_DEVELOPMENTS.md` (after the CONSOLIDATED TO-DO). HAND-CORRECTED one agent false-positive (the
  verify-before-trust rule): 5B-4 was reported "shipped" because the generic events/calendar substrate exists,
  but the brief's event-timed-op MANIPULATION card + the elections/civic VERTICAL (candidate roster, poll
  analysis) are NOT built — recorded correctly as deferred. NET STATUS: NOT-STARTED = Tier1.2 collector
  write-batching, Tier2.6 unified import/export, Tier4.13b outrage-intensity, Tier4.16 self-update, 5A-bis
  D2/D3/D4/D5, zh/ja segmentation, event-timed-op/elections vertical; PARTIAL = Tier4.14 bury-half (flood
  shipped), 5A-bis.D1 persisted-DuckDB (scaffold+doc; binaries blocked), Ollama binary installer (catalog
  shipped; installer blocked on checksums), Tier3.12 i18n (~105 strings left, mostly literal/security-dense/
  deliberately-tagged). LEDGER CORRECTION: the in-window task tracker had Tier1.2 + Tier2.6 marked "completed"
  — that reflected DESIGN-done, not BUILT; they are design-only and corrected to pending.
- **i18n SLICE — NEW TOP-LEVEL SURFACES ×12 2026-06-25 (the RC-gate "key the remaining English-fallback
  panel strings" item; branch claude/vibrant-thompson-bez6dq, draft PR onto 0.09; VERIFIED: gate 100%
  + audit drop + clean-append diff).** Keyed the 14 cleanest, highest-value new chrome strings from the
  prior session's surfaces — the Library/Governments/Graphics + backup/folder labels: Graphics · Menu ·
  Browse… · Pick a folder · Use this folder · Click a country · Keyword-growth curve · Back up (volumes +
  parity) · Restore from a volume backup folder · Passphrase (encrypts the backup) · the Governments
  "Fetch the standard country indicators…" action · the "Source-catalogue reach…" Library line · the
  remark-10 world-map paragraph · the remark-16 "Everything you've DOWNLOADED…" Library line. METHOD: a
  scratchpad script resolved each key BYTE-EXACT against the live `--audit-chrome` output (so the key
  matches the source apostrophe/em-dash/ellipsis exactly — the recurring i18n trap) then SURGICALLY
  appended `"key": "translation"` before each locale's closing brace (no json re-dump → zero reformat;
  diff is +15/−1 per file = the 14 new keys + a comma on the previously-last line). Non-en AI-drafted,
  FLAGGED for native review (the long honesty paragraphs especially). SLICE 2 (same PR) keyed 16 MORE
  clean single-node strings the same byte-exact way — the 12 diagnostics DOWNLOAD BUTTONS (Debug bundle /
  Network log / Date-extraction log / Performance report / Scaling benchmark / Keyword self-test /
  Keyword-engine report / Keyword-growth / Home-card diagnostics / Keyword log / All diagnostics / All
  keywords, the `.json`/`.zip` suffix kept literal) + Large encrypted backup (volumes + parity) + the
  "Open evidence & custody →" link + the world-map "drag to pan · …" hint + the Governments aria string.
  gate `--min 100` 1627→1657 ×12; `--audit-chrome` 140→110 (30 keyed across the two slices). SLICE 3
  (PR after #463 merged) keyed 5 MORE clean single-node HELP PARAGRAPHS the same byte-exact way — the
  volume-restore "Verify + repair (from parity) … nothing is replaced or deleted" honesty line, the
  home-card-diagnostics + "All diagnostics in one archive" + "All keywords (… &page=2)" + keyword-growth
  (Heaps β) descriptions — with the technical TOKENS (has_more, &page=2, Heaps β, 'All keywords', 5000,
  ~20 MB, AES-GCM) preserved verbatim in every locale. gate 1657→1662 ×12; `--audit-chrome` 110→105
  (35 keyed across the session). REMAINING ~105 untranslatable = mostly data/examples/URLs/regexes/
  proper-nouns that CORRECTLY stay literal (NY.GDP.MKTP.CD, ollama.com/library, you@example.com, WTI,
  socks5://…) + the most security-/technically-dense paragraphs (the custody IP/timing/Merkle overview +
  the AES-GCM/Reed-Solomon volume-backup blurb — DELIBERATELY left for native review, an AI-mistranslated
  security claim is worse than readable English) + the mid-`<a>`-link sentence FRAGMENTS
  that need the de-tagging restructure (the established slower tail).
- **COPYPASTA MANIPULATION CARD 2026-06-25 (Tier 4.13, the astroturf/copypasta card; branch
  claude/vibrant-thompson-bez6dq, draft PR onto 0.09; pure helper + card LOGIC VERIFIED py3.11 standalone +
  ruff F/B, card/endpoint tests in CI [sqlalchemy]).** The 6th of the nine manipulation cards, built because
  the earlier "partly covered by echo_chamber" read was wrong on reflection: copypasta is a SPAN-level signal
  echo_chamber (whole-article near-dup) MISSES — the SAME verbatim sentence embedded in articles that are
  OTHERWISE DIFFERENT, across many sources = a coordinated talking point dropped into original-looking
  coverage. NEW pure primitive `src/signals/near_dup.py:shared_word_ngrams(docs, k, min_docs)` — verbatim
  k-word phrases shared across >= min_docs DISTINCT documents, keeping the phrase TEXT (unlike the hashing
  `shingles`), merging consecutive shared k-grams into the full span and reporting the docs that contain it IN
  FULL (k-gram doc-set intersection), substring-deduped word-aligned; pure (stdlib, optional numpy), runs on
  every lane. `src/analytics/copypasta.py:find_copypasta` composes it: a phrase fires only when it spans
  >= min_sources DISTINCT sources AND the sharing articles are NOT whole near-dups across that many sources
  (Jaccard >= 0.7 = a republished WIRE STORY = echo_chamber's job, EXCLUDED — the innocent twin handled by
  construction, not just prose). HONESTY: independence = distinct SOURCES never article count (a single source
  repeating a line can't manufacture it — tested); metric = distinct-source count + phrase length, NO score;
  the innocent twins (shared quote / press-release line / boilerplate) stated in the caveat; bounded recent
  scan. Wired as a fail-safe-LAST producer (`copypasta` -> an `overtold` Home Lead over the exact article set,
  carries `_trigger`) + `GET /api/insights/copypasta` (cached). Frontend: NONE needed — cards render
  generically (no per-type frontend hardcoding, grep-verified), so it auto-surfaces as a Home Lead like the
  other 5 cards. tests/test_copypasta.py (pure helper: finds-across-3 + min_docs/degenerate gates [run every
  lane]; card: fires on planted-span-in-3-different-articles, EXCLUDES whole-article wire republish, below-
  min_sources silent, single-source-can't-manufacture, no-score, endpoint) + the all-producers sweep
  (test_briefing/test_producers_card_shapes iterate _DEFAULT_PRODUCERS) covers shape + trigger automatically.
  The pure helper + the full fire/wire-exclude/source-gate selection logic were proven in py3.11 standalone
  repros before commit; py_compile + ruff F/B clean. **MYPY FOLLOW-UP (PR #463, 2026-06-25): the copypasta
  card slipped 3 NEW mypy errors past #461 (the maintainer fast-merges despite a red `test` lane), tipping the
  ratchet 127→130.** Root cause: `shared_word_ngrams` built a heterogeneous result `dict` (str/int/list values)
  then SORTED + DEDUPED by indexing it, so `r["phrase"]`/`r["n_docs"]`/`r["doc_ids"]` typed as `object`
  (near_dup.py:128 len/unary-minus on object ×2, :133 set(object)). FIX: sort + dedup over typed
  `(phrase, set[str])` TUPLES, build the result dicts only at the end (behaviour byte-identical, re-verified).
  130→127 = back to baseline. **LESSON (ledger ritual reinforced): mypy 2.1.0 IS pip-installable in the
  py3.11 sandbox (`pip install mypy`) and type-checks CHANGED FILES via their real-file import closure even
  without the project deps — RUN IT on any Python change (`python3 -m mypy <changed.py>`), the ratchet is a
  BLOCKING gate; py_compile + ruff F/B alone do NOT catch it.** REMAINING manipulation cards: the BURY half of
  #4 (needs an external trigger), event-timed-op (needs the elections roster), outrage-intensity (secondary
  annotation).
- **AUTONOMOUS SESSION 2026-06-24 (the consolidated-to-do build brief `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-06-24.md`;
  ONE branch claude/vibrant-thompson-bez6dq per the harness git-constraint, draft PR #460 onto 0.09; backend
  VERIFIED py3.11 standalone repro + ruff F,B, full pytest in CI). TIER 1.1 — STATEMENT-DEADLINE GUARD on the
  slowest per-keyword reads (remark 8 finish: "When searching for a keyword, the analysis screen says Loading…
  indefinitely"):** #455 made the briefing recompute non-blocking + #458 cached the 5 per-corpus endpoints —
  this adds the honest STOPGAP for the cold FIRST open. The heaviest per-keyword aggregations
  (`/api/insights/associations`, `/api/insights/graph` both paths, `/api/framing`) now run under the EXISTING
  `statement_deadline` mechanism (src/database/maintenance.py, OO_STATEMENT_TIMEOUT_S default 60s) so a runaway
  whole-corpus co-occurrence GROUP BY on a large encrypted corpus aborts with a typed `StatementTimeout` → an
  honest HTTP 503 ("statement exceeded the 60s deadline and was aborted") instead of an unbounded hang. (CI FIX
  in-session: the wiring test must NOT `import src.api.framing` — that pulls in vaderSentiment [the [analysis]
  extra] and reddens the core-only lane; read framing.py's SOURCE as a sibling file, like the insights.py grep.
  NOTE: a macOS-portability flake surfaced separately — `test_same_origin_and_no_origin_allowed` teardown
  "write gate HELD" — it hits `/api/briefing/refresh`, whose #455 BACKGROUND recompute writes on its own
  session; a pre-existing race in that merged path, NOT this read-only change [same SHA passed it in the
  parallel push-vs-PR run; observation-only lane]. FIXED 2026-06-24 [it later reddened the BLOCKING Core-only
  lane too, on the sibling `test_security_headers_present` — same `/api/briefing/refresh` daemon]: the autouse
  `_write_gate_not_leaked` conftest fixture checked `write_gate.held` IMMEDIATELY at teardown, but the #455
  briefing-refresh DAEMON can still be mid-commit (a legitimate background writer, not a leak). It now WAITS up
  to 5 s for the gate to DRAIN before failing — a real leak [a session flushed but never committed/closed] never
  releases so the bounded wait still surfaces it, while a finishing background thread drains; the wait runs only
  on the rare teardown that overlaps a background write [held==False for ~all tests = zero cost]. LESSON: an
  autouse gate-leak assertion must tolerate the app's own legitimate async writers or it flakes on whichever
  test happened to kick one.) A new
  `_deadlined(db, key, compute)` helper in insights.py wraps the deadline INSIDE the compute (so it runs only on
  a cache MISS — a hot TTL-cache hit never touches the connection, the #458 cache stays the primary speed lever);
  framing.py wraps its body directly (the deadline bounds the SQLCipher-decrypt of up to `limit` article bodies,
  the dominant cost; the pure-Python VADER pass is already bounded by limit×8000 chars, stated). HARDENED
  `statement_deadline` to degrade to a NO-OP (rather than crash) when a session can't yield a raw DBAPI
  connection (a unit-test stub / non-standard session) AND to skip touching the connection entirely when the
  deadline is disabled (OO_STATEMENT_TIMEOUT_S=0). The frontend already surfaces a 503: the analysis subtab
  loaders (renderCorpusKeywords / mindmap / loadFraming) catch the `api()` throw and replace the placeholder
  with an honest `.note.err`, so the request now RETURNS within 60s and the error shows — no frontend change
  needed. tests/test_insights_cache.py (+2: the 3 endpoints route through the deadline; a StatementTimeout maps
  to 503) + tests/test_perf_batch.py (+1: the no-op-on-stub-session degrade). Standalone repro proved all 6
  control-flow cases (no-op runs body, disabled skips connection, timeout→503, normal-passthrough, 400-propagates
  through both the no-op and real-deadline paths, handler cleared in finally). REMAINING for remark 8: the deep
  cold-FIRST-open speed (the keyword_daily rollup, workstream 5A-bis D2, gated on the persisted encrypted DuckDB
  store D1); this deadline is the honest stopgap until then.
  **TIER 1.2 — COLLECTOR WRITER-BOUND (P1-C) = DESIGN-DOC + DEFERRAL (honest §8 call, NOT a blind hot-path
  refactor):** the only remaining contention lever is batching the data-loss-critical single-writer hot path
  (the cheap `synchronous=NORMAL` fsync win is ALREADY in place, session.py:103). The safe design (batch a
  source's store+index into ONE transaction via an additive `index_article(commit=False)`, with the proven
  `ingest_emails` per-article fallback on a batch failure = no loss; counters accumulate correctly within one
  txn = correct by construction) is fully written in `docs/design/COLLECTOR_WRITER_BATCHING.md` WITH the no-loss
  test plan + the gate-hold tradeoff + the keyword_daily-watermark interaction. NOT IMPLEMENTED: its perf
  benefit can only be validated on the live corpus (the motivating metric is a live measurement) and its
  failure-mode correctness needs the full pytest suite to EXECUTE (the sandbox is py3.11/no-deps; repo needs
  py3.13) — so per "entirely reliable or it should not exist," a blind refactor of keystone #1 is the wrong
  call. Build it in a session that can run the suite + measure (default B=1 = byte-identical, raise
  `OO_COLLECT_COMMIT_BATCH` to adopt).
  **TIER 2.3 — SEARCH ENTER OPENS A NEW BROWSER TAB (remark 9, frontend, BROWSER-UNVERIFIED per fork-3):** the
  omnibar opens the command palette; typing a term + Enter ran the first item `openAnalysisFor(raw)` = an
  IN-SPA analysis tab in the SAME browser tab. The maintainer wants a NEW browser tab. Reused the proven
  card-flip deep-link mechanism: a new generic `openAnalysisInNewTab(q)` = `window.open("/?analyze=" + q,
  "_blank", "noopener")`, and the existing boot `_hydrateCardCorpus()` reads `?analyze=` → `openAnalysisFor()`
  so the fresh SPA tab lands on the same analysis. `openCardCorpusQuery` is now a one-line alias (the #23
  flip-card test still finds it; the card path is byte-unchanged). The palette's Enter (Analysis) item now
  calls `openAnalysisInNewTab(raw)` with `sub:"↵ ↗"` (the ↗ honestly signals a new tab). The in-SPA
  `openAnalysisFor` STAYS the opener for clicking a specific palette result + every card/commodity/convergence
  entry + the boot hydration (Desk lesson: nothing lost); the Boolean Search-tab item is still one item away.
  ZERO new i18n keys (reused t("Search")/t("Analysis"); ↗ is a glyph). node --check clean; test_repo_invariants
  ::test_omnibar_enter_opens_analysis_window updated to assert the new-tab opener + the ?analyze= deep-link +
  the ordering. REMAINING: human click-through (fork-3).
  **5A-bis D0 — SCALING DESIGN DOC SHIPPED:** `docs/design/SCALING_DERIVED_LAYER_1000X.md` is the source-of-truth
  for the derived-layer scaling workstream (the deep fix for remark 8). It EXTENDS the shipped seam
  (`readmodel.py` top_terms/trending/.../source_country_counts all v1-delegate; `columnar.py` connect/keyword_agg/
  oo_meta/encryption_gate/secure_crypto_available/build_keyword_read_model/top_terms_raw; the
  `ix_mention_date_keyword` covering index) — never recreates them. Captures the `keyword_daily` + `source_coverage`
  rollups, the stream-from-SQLCipher-INTO-DuckDB-group-THERE full build, the incremental MERGE on the
  `keyword_mentions.id` watermark + the corpus-epoch full-rebuild gate, AND the critical TRAP (index_article does
  delete-then-reinsert, so every re-index/prune/restore path MUST bump the epoch → full rebuild, never an
  incremental MERGE, or the rollup double-counts; normal ingest must NOT bump it). 12-item VERIFY checklist +
  rejected-alternatives. D2–D4 are buildable+parity-provable IN-MEMORY now; the perf payoff is D1-gated (the
  persisted encrypted DuckDB store needs the maintainer's per-OS httpfs binaries — 5B). **5B/D1 design SHIPPED:**
  `docs/design/PERSISTED_DUCKDB_HTTPFS.md` = the offline static-OpenSSL httpfs LOAD recipe (autoinstall/autoload
  off → SHA-256 pin-and-verify the bundled binary BEFORE LOAD from an absolute path → GCM-only ATTACH never CTR →
  flip `secure_crypto_available()` only after the `encryption_gate` probe), the external-artifact registry entry +
  the DuckDB↔httpfs version coupling (test-enforced), and the maintainer's networked vcpkg-static build recipe.
  The OFFLINE-LOAD code is ours to write + an EMPTY pin table is safe to ship (a blank/zero hash keeps it
  in-memory); the per-OS/arch binaries need a networked multi-arch build (BLOCKED in-sandbox; NEVER a fabricated
  checksum).
  **TIER 2.4 — LIBRARY WORLD MAP (remark 10; backend VERIFIED py-logic, frontend BROWSER-UNVERIFIED per fork-3):**
  the Library "World coverage" was a TABLE; now it leads with a per-country ARTICLE-count world map + a donut of
  the 'no country' articles by language. BACKEND: `queries.source_country_counts` gained a `by_language` breakdown
  in the `unlocated` bucket — a column-projected `Article.language` count over the indexed source_id join filtered
  to country-less sources (NEVER a content decrypt; matches the existing unlocated definition country IS NULL/empty);
  flows through `/api/insights/map-coverage` unchanged. FRONTEND: a NEW reusable `ooDonut(host, data, opts)` SVG
  renderer (stroke-dasharray per slice — robust for any slice count incl. a single full ring; evenly-spaced hues;
  honest total + per-slice counts, no score) + `renderCoverageMap()` reusing the shared `ooMap` choropleth for the
  Articles dimension (centroid fallback for microstates, ooRegionName names, click-a-country → filters the
  catalogue table below) + the donut (full language names via ooLangName, "Unknown language" for null-lang, honest
  empty state). The catalogue-REACH table/summary/regions are KEPT below (Desk lesson — a different measure: catalog
  span vs collected articles). New strings English-fallback via `t()` (i18n --min 100 still 100%; keyable in §4).
  tests/test_map_coverage.py::test_unlocated_articles_have_a_per_language_breakdown (private language codes, located
  source doesn't leak) + test_repo_invariants::test_library_world_map_and_unlocated_donut. node --check clean.
  REMAINING: Tier 2.5 (the Library central dashboard — remark 16, same tab); human click-through (fork-3); key the
  new strings ×12.
  **TIER 2.5 — LIBRARY CENTRAL DASHBOARD (remark 16; backend VERIFIED py-logic, frontend BROWSER-UNVERIFIED per
  fork-3):** the Library tab is now the at-a-glance view of EVERYTHING downloaded + extrapolated. NEW
  `GET /api/library/overview` (`src/api/library.py`, wired into `_wiring.py` spine) rolls up in ONE change-probe-
  cached call (mirrors the Database-stats cache + freshness disclosure): the RAW/downloaded layer (Wikipedia
  tracked pages + revisions + downloaded-dump count/bytes, OSM-region count/bytes, market price points, law
  documents+revisions, official-statistics figures, local AI-model count/bytes) AND the DERIVED/extrapolated
  layer (article_analyses BY KIND = AI summaries/translations/synthesis, ai_keyword total, active watches). REUSES
  the cached `database_stats` for the core counts + DB file size (no duplicate scans); the download SIZES come
  from the existing wiki/OSM download managers (`.list()`, filtered to status=="done" — an in-flight download is
  never counted) + `ollama_models.store_status()`; every external read is BEST-EFFORT (a missing table/manager/
  Ollama store degrades to null/`available:false`, never crashes a core-only install). Counts + on-disk bytes
  ONLY, NO score (the `article_analyses` exclusion from the Database-stats corpus view is reconciled: it belongs
  in the DERIVED layer here, the maintainer's explicit "summaries/translations/synthesis" ask, labelled AI-derived
  unreliable). FRONTEND: a new top "Library" panel (`#library-overview`) + `renderLibraryOverview()` rendering the
  two labelled groups as `.stat` tiles (counts via fmtNum, sizes via _fmtBytes), own stamp so the 16s poll repaints
  only on change; wired into the tab onShow + the live poller. The Database section (store detail + reclaimable
  bytes) + the World coverage map/table STAY below (Desk lesson). New strings English-fallback via `t()` (i18n
  --min 100 still 100%). tests/test_library_overview.py (shape + the four sections + no-score sweep) +
  test_api_wiring (library added to the spine sample) + test_repo_invariants::test_library_central_dashboard. node
  --check clean. REMAINING: human click-through (fork-3); key the new strings ×12; optional per-symbol/per-agency
  breakdowns.
  **TIER 3 CHEAP UX — remarks 11/12/14/15 (frontend, BROWSER-UNVERIFIED per fork-3):** (12) the Settings INTRO
  BOX (h2 "Settings" + the "Everything that shapes…" paragraph + the panel wrapper) is REMOVED — the `#set-subtabs`
  nav (relocated to the top strip anyway) is un-wrapped as a direct child of `#tab-settings`, reclaiming vertical
  space on every subtab; no JS depended on the box. (11) APPEARANCE + GUIs FUSED into ONE "Graphics" subtab
  (`data-tab="graphics"` / `#set-graphics`): the GUIs `<section>` (with `#guis-gallery`) MOVED inside the renamed
  appearance panel, the standalone `#set-guis`/`data-tab="guis"` removed; `showSetCat("graphics")` now runs BOTH
  `buildDrawer()` + `OOGUIs.renderGallery()`; `openDrawer` selects "graphics". Desk-lesson safe — both contents
  (`#dr-themes` appearance + `#guis-gallery`) preserved; invariant #30 test updated guis→graphics (the gallery
  host kept); gallery.js untouched (renders into `#guis-gallery`). (14) the sticky CHROME (`.topbar` +
  `.subtab-strip`) was semi-transparent (`color-mix(var(--bg) 82/92%, transparent)` + backdrop-blur) so scrolled
  content showed through; both now use the OPAQUE `var(--bg2)` (the left sidebar's bg, the maintainer's ask) and
  the now-pointless backdrop-blur is dropped (a GPU cost at rest). (15) clicking the sidebar's EMPTY space toggles
  collapse/expand (`_wireSidebarEmptyClickToggle` → the existing `toggleSidebar()`, ignoring clicks on
  nav-item/button/a/input/label/select/textarea so navigation + the `#sb-collapse`/`#sb-expand` buttons are
  unaffected). div/section balance verified; node --check + i18n 100%. test_repo_invariants::
  test_settings_chrome_cleanups + the updated #30 test. REMAINING: human click-through (fork-3).
  **TIER 4.15 — GOV-NEWSLETTER BOILERPLATE (remark 15 in the to-do; backend VERIFIED py-logic):** the "?"-bucket
  junk is the §2.6 underscore template ids (`gd_combo_table` — ALREADY dropped by the shipped `_is_code_token`
  "_"-rule + the `underscore_identifiers_dropped` self-test case) + undetected-English (the shipped §2.6 langdetect),
  NOT the brand name. RECONCILED with the 2026-06-23 finalization ruling (4) — "brand/company tokens (govdelivery)
  STAY content, never stoplisted": extended the `underscore_identifiers_dropped` self-test golden case to ALSO
  assert `govdelivery` survives as a content TERM (so a future over-eager filter can't accidentally stoplist the
  brand) while `gd_combo_table` still drops. Verified by reading `_is_code_token` (pure: `gd_combo_table` has "_" →
  dropped; `govdelivery` is a 0-transition pure word → kept). A regression now reddens the maintainer's exported
  keyword self-test AND CI. No new filter needed (the bucket reduction is the already-shipped §2.6 work).
  **TIER 3.11 — AI PROMPT LOCALIZATION + OUTPUT IN THE UI LANGUAGE (remark 13; backend VERIFIED py_compile, frontend
  BROWSER-UNVERIFIED per fork-3):** the prompt-editor LABELS are static HTML already keyed ×12 (auto-translated by
  the i18n DOM walker on setLang), and the prompt BODIES stay ENGLISH BY DESIGN (translating multi-sentence system
  prompts degrades a weak local model — the reliable lever is OUTPUT language). The real gaps (output not in the UI
  language for SINGLE-article ops, while bulk/synthesis were already wired): (a) backend `/api/llm/articles/{id}/
  summarize` gained a `ui_lang` field → passed as `output_lang_code` to `_build_prompting` so the `_NATIVE_DIRECTIVE`
  is appended (a single-article summary now comes out in the UI language); (b) frontend single-article `summarize()`
  sends `ui_lang: OOI18N.current()`; (c) frontend single-article `translateArticle()` defaults `target_language` to
  `_uiLangName()` (the UI language) instead of hardcoded "English". Plus `loadLlmPrompts()` added to the
  `oo:langchange` listener (gated on the AI panel being visible) so the editor refreshes on a language switch.
  tests/test_llm_api.py::test_output_language_pins_the_summary_prompt extended (ui_lang "fr" → "français" directive) +
  test_repo_invariants::test_ai_output_in_ui_language_and_prompt_relocalization. node --check + i18n 100%. REMAINING:
  human click-through (fork-3).
  **TIER 2.6 — UNIFIED IMPORT/EXPORT = DESIGN DOC (remarks 2/5/6; a large frontend consolidation, browser-unverifiable
  + big, deferred per §8 to a click-through session):** `docs/design/UNIFIED_IMPORT_EXPORT.md` specifies ONE Import +
  ONE Export/Backup entry, each → an options pop-up → file/folder pick, REUSING the shipped backends (no new backend):
  6a Import routes to restore/volume/folder + the TWO newsletter paths (upload + folder job) + mailbox + models; 6b
  Export mandates the OOENC2 streaming-volume path for the encrypted corpus (NOT the legacy 2 GiB single-file) + the
  large-data folder backup + plaintext + models. Honesty guards: an absorption test (every existing import/export type
  still reachable), the OOENC2-path guard, owner-reported-only progress, visible disclosures.
  **REMARK 1 (Ollama/AI) — MISTRAL-PRIORITISED CATALOG (the verifiable half; backend VERIFIED py_compile):** the
  maintainer wants Mistral open-models prioritised (mistral-small:latest, mistral:7b). `MODEL_CATALOG`
  (src/llm/ollama.py — the ONE source the Settings → AI picker reads) now LEADS the permissive section with the two
  Mistral entries (mistral:7b ~4.4 GB/8 GB-RAM accessible; mistral-small:latest ~24B/~14 GB/24 GB-RAM capable), tags
  MAINTAINER-NAMED + sizes flagged advisory ("verify on a networked box", the catalog's standing pattern; CATALOG_AS_OF
  unchanged so the freshness test + registry are intact; no test asserts catalog contents). DEFERRED/BLOCKED (the rest
  of remark 1): the Ollama BINARY installer (download+verify+run the per-OS installer) stays blocked on real per-OS
  installer CHECKSUMS (a networked machine — NEVER fabricated; the Q7=B design is in this ledger); the hardware-tier
  SCENARIO messaging (measure RAM via vitals → recommend a fitting model) is a separate UI build. The pull/queue/
  active-model picker already ship; this leads them with Mistral.
- **HTTP ERROR CODES → THE DOWNLOADABLE DIAGNOSTIC LOG 2026-06-24 (field test: "I'd like all error codes
  recorded into a downloadable diagnostic log — or is it already?"; branch claude/diag-http-error-log, draft
  PR onto 0.09; backend VERIFIED py3.11):** ANSWER = PARTIALLY already, now COMPLETE. Already: every WARNING/
  ERROR/CRITICAL *logged* anywhere (incl. backend exceptions WITH tracebacks + the unhandled-500 handler) lands
  in `data/app_errors.jsonl`, which rides the downloadable debug bundle (Settings → Diagnostics; `recent_errors`
  + `error_log` summary). GAP: HTTP error *responses* (4xx/5xx the UI actually saw — a 404 on an UNMATCHED route,
  a 409/400 HTTPException) were captured ONLY if an endpoint happened to log them; a no-route 404 logged nothing
  (exactly the "not found" the maintainer hit before the #456 prefix fix would never have appeared in the log).
  FIX: `errorlog.note_http_error(method, path, status)` appends a record under a NEW `_HTTP_LEVEL = "HTTP"`
  channel, wired into the `monitor_requests` middleware (`status_code >= 400`) — the ONE place that sees the
  final status for EVERY response, including unmatched-route 404s (it is the OUTERMOST middleware, so the 503
  lock-gate + Starlette's no-route 404 both flow back through it). HONESTY/safety: `HTTP` is deliberately NOT in
  `_PROBLEM_LEVELS`, so error RESPONSES (a 404/409 is often the correct answer) do NOT inflate the problems_*/
  locked_errors_* data-loss signal; a per-(method,path,status) throttle (`_HTTP_THROTTLE_S=10s`, bounded
  `_http_last` map) stops a poll loop flooding the capped log; best-effort try/except (diagnostics never affect
  the response). `summary()` gained `http_errors_total` / `http_errors_this_session` (session-aware via the boot
  marker) + `http_status_breakdown` ({"404": n, …}); the records appear in the bundle's `errors` list
  automatically. tests/test_errorlog_summary.py (+4: recorded+counted+breakdown, problems unaffected, duplicate
  throttle collapses but distinct status kept, never-raises) + test_repo_invariants::
  test_http_error_responses_recorded_in_diagnostic_log (the middleware hook + the non-problem level + bundle
  wiring). ruff F/B clean; errorlog.py 0 mypy errors. REMAINING (optional): include the HTTPException `detail`
  string (the middleware sees only the status, not the JSON body) + a glanceable http-error count in the
  Settings diagnostics UI.
- **INSIGHTS PER-CORPUS ANALYSIS CACHING + HONEST SLOW-LOAD 2026-06-24 (field-test remark 8, slice 1; branch
  claude/happy-einstein-6ht33l, draft PR onto 0.09; backend py_compile-VERIFIED py3.11 + node --check, full
  pytest CI):** "searching a keyword → analysis screen says Loading… indefinitely." The Insights-frozen half
  (`top_terms(group=True)` 17 s) is already warmed off-thread by the #455 briefing fix; this addresses the
  analysis WINDOW. FINDING: the 5 per-corpus endpoints (`corpus-keywords/www/sentiment/sources/coordination`,
  src/api/insights.py) were UNCACHED whole-corpus-scoped aggregations (bounded to cap=1000 articles, but the
  Overview fires 4 at once + every subtab switch / re-open re-pays the search + GROUP BY) while
  associations/graph/top/trending were already `_cached`. FIX: wrapped all 5 in the proven `_cached`/`_ckey`
  pattern, with `_resolve_corpus` moved INSIDE the compute so a cache HIT skips the search too; keyed by the
  full request identity (article_ids OR query+filters+limit+cap+kind+tl); TTL-disclosed (cached/computed_at).
  So re-opening a keyword / flipping between subtabs is now instant. FRONTEND (browser-unverified per fork-3):
  the analysis Overview landing replaces a bare infinite "Loading…" after ~6 s with an honest "still computing
  over your full corpus — narrow the time window to speed this up" (never a fake spinner, never a hard abort
  that discards the in-flight result). tests/test_insights_cache.py::test_per_corpus_analysis_endpoints_route_
  through_cache (wiring guard) + node --check. REMAINING (honest): the FIRST cold open of a keyword is still
  bounded by aggregation speed (the columnar speedup is gated on the httpfs crypto-extension packaging
  decision; a statement-deadline is the riskier deferred option) — needs a repro of WHICH subtab is slowest on
  the live corpus, or the benchmark export; the slow-note is on the Overview only; key the 1 new string ×12.
- **HOME BRIEFING FREEZE — NON-BLOCKING BACKGROUND RECOMPUTE + PROGRESS BAR 2026-06-24 (field-test remarks
  7/8; branch claude/happy-einstein-6ht33l, draft PR onto 0.09; backend py_compile-VERIFIED py3.11 + node
  --check, full pytest CI):** at 60K articles Home hung forever on "Loading the briefing…". ROOT CAUSE
  (verified): `service.get_briefing` recomputed SYNCHRONOUSLY on the request when the cache was stale/absent
  (`refresh_briefing` → all producers + `warm_cache`, whole-corpus GROUP BYs over 932K keywords = minutes;
  `top_terms(group=True)` alone measured 17 s/50 rows in the keyword-engine report). Since the app boots in
  AIRPLANE mode the scheduler is idle, so the on-demand recompute (the P0-3 stale-cache fix) ran on the GET
  and blocked it. FIX: a new `background=True` path (the HTTP endpoints only) NEVER recomputes on the request
  thread — it kicks ONE background daemon recompute (its OWN session via `session_scope`, idempotent under
  concurrent Home polls, guarded by `_refresh_lock`) and returns instantly: the stale cards under a slim
  "updating…" banner, or an honest `building` placeholder when there's no cache, with a `refreshing` flag +
  `{done,total}` PROGRESS. `run_all(session, on_progress=)` publishes per-producer progress; the frontend
  `renderBriefing` shows a determinate `<progress>` ("Building your briefing… N/M analyses" — honest: counts
  analyses, NOT time) and re-polls every 1.5 s until cards land. `background=False` (tests / scheduler /
  explicit callers) keeps the SYNCHRONOUS recompute unchanged (test_briefing.py green). The HTTP GET +
  POST /refresh both pass background=True (neither blocks). BONUS for remark 8: `warm_cache` runs INSIDE the
  background `refresh_briefing`, so the grouped `top_terms`/trending Insights views are warmed off-thread too
  (the per-keyword analysis endpoints — associations/graph/framing — still need their own statement-deadline
  slice; flagged). tests/test_briefing_api.py::test_briefing_get_is_nonblocking + the existing briefing
  tests stay green (the synchronous default path is untouched). REMAINING: i18n-key the 3 new strings
  (English-fallback via t() now, gate green); the per-keyword Insights "Loading… forever" statement-deadline
  fix (remark 8 proper); human click-through of the progress UI (fork-3).
- **FIELD-TEST DIAGNOSTICS — P0 BUG FIXES 2026-06-24 (maintainer live test of the ~60K-article corpus; 3
  diagnostics analysed [keyword self-test 42/42, debug bundle, keyword-engine report]; branch
  claude/happy-einstein-6ht33l, draft PR onto 0.09; backend py_compile-VERIFIED py3.11, full pytest CI [repo
  needs py3.13]). Maintainer scope: "we just want the diagnostics to be resolved for now" + "capture all my
  preliminary remarks into future developments, address them later." Read PR #449/#450 first per instruction
  — #450 is the new OOENC2 streaming-volume backup; my fixes don't touch backup (no conflict).** TWO active-
  failure bugs fixed, both the session-poisoning data-loss class:
  (P0-A) **Newsletter import failed the WHOLE 5 GB folder with `UNIQUE constraint failed: articles.hash`**
  (6× unhandled 500 in the bundle, `POST /api/newsletters/import`). ROOT CAUSE: `ingest_emails`' in-batch
  dedup key was the `(content_hash, canonical)` TUPLE, but `articles.hash` is the ONLY unique column
  (canonical_url is NOT) — so two emails with the SAME body + DIFFERENT Message-IDs (rife in a multi-folder
  newsletter dump) got different keys, both entered one uncommitted batch, and collided at the insertmany
  flush; under the continuously-running scraper's writer contention the collision escaped as a raw 500.
  FIX (`src/ingest/email.py`): dedup on the real unique column (`pending_hashes`/`pending_canon` sets, key on
  content_hash) so a same-body pair NEVER co-occupies a batch; `_flush` now catches `(IntegrityError,
  OperationalError)` → per-message fallback; `_commit_one` wraps the commit in `run_write_with_retry` (lock →
  retry, no data loss), counts a genuine dup, and on an exhausted lock LOGS + counts `errors` (new tally key)
  — NEVER raises, so no message aborts the import or escapes. Endpoint (`src/api/ingestion.py`) guards
  `ingest_emails` → clean JSON 500, never a raw unhandled. tests/test_email_ingest.py::
  test_same_body_different_message_id_dedups_on_hash (4 same-body in one batch → stored 2/dup 2/errors 0, no
  raise). The existing fallback test stays green (now deduped pre-flush).
  (P0-B) **A ~4-hour scrape pass rolled back (ok:false) on `UNIQUE constraint failed: law_revisions
  .document_id, content_hash … transaction has been rolled back`** (an older pass died the same way on
  `database is locked`). ROOT CAUSE: `track_document` blind-`session.add(LawRevision)` + `commit()` with no
  idempotency, and `auto_track_due`/`track_watched` caught the resulting IntegrityError but did NOT
  `session.rollback()` — poisoning the SHARED pass session so the pass's final commit failed and every
  scraped article rolled back. FIX (`src/law/track.py`): the two revision-writing commits now catch
  IntegrityError → rollback → idempotent "duplicate" (baseline path re-caches `baseline_text`); BOTH batch
  loops add `session.rollback()` in the except so one bad doc can NEVER roll back the whole pass. tests/
  test_law.py::test_track_document_is_idempotent_on_duplicate_revision (dup absorbed, no raise, session still
  usable).
  REMAINING (the diagnosed PERF freezes — remarks 7/8, root-caused not yet fixed): Home briefing + Insights
  "Loading… forever" trace to `top_terms(group=True)` = 17 s/50 rows on the 61,635-article/932,031-keyword
  corpus run SYNCHRONOUSLY with no background offload/cache/statement-deadline/progress (P1-D/E); the writer-
  bound collector (collect_parallelism 50 → 1 writer, measured 532,772 s cumulative gate wait / 8,294 s max,
  P1-C); keyword maintenance (re-index→prune→tag-backfill, P1-F). The 12 field-test FEATURE remarks are
  PARKED VERBATIM in docs/FUTURE_DEVELOPMENTS.md ("FIELD-TEST REMARKS 2026-06-24") — ollama installer/Mistral,
  unified import/export/backup on the OOENC2 path, search→new-window, library world map, Settings Graphics
  subtab + intro-box removal — to address after the diagnostics.
- **KEYWORD-GROWTH (VOCABULARY) CURVE 2026-06-24 (maintainer ask at 909k keywords: "a curve of added keywords
  per total words added"; branch claude/keyword-growth, draft PR onto 0.09; backend VERIFIED py3.11, frontend
  BROWSER-UNVERIFIED per fork-3):** `src/analytics/keyword_growth.py:keyword_growth_curve` plots cumulative
  DISTINCT keywords against cumulative WORDS (token occurrences) added, ordered by article date. The SHAPE is
  the diagnostic (Heaps' law): a curve that bends over = the vocabulary is SATURATING (healthy, new articles
  reuse known words); a near-straight line (Heaps `beta` ~ 1) = new keywords still minted for almost every word
  = the markup/code/unsegmented/function-word JUNK signature. Reports the cumulative series + a log-log Heaps
  fit (`beta`, `K`, `r²`) + the "new keywords per 1,000 words" minting rate at the START vs END (a big drop =
  saturating). DECRYPT-FREE BY CONSTRUCTION: every figure comes from `keyword_mentions` alone via the
  denormalised `observed_on` + the `ix_mention_date_keyword` covering index — it NEVER joins to the encrypted
  `articles` table (the standing perf-trap rule); cheap even at millions of mentions. Counts only, NO score;
  undated mentions reported not dropped; honest caveats (ordered by article date = a collection-order proxy;
  multilingual inflates the vocabulary). `GET /api/diagnostics/keyword-growth` (+`download=1`) + a Settings →
  Diagnostics "Keyword-growth curve" button (renders a self-contained SVG of keywords-vs-words in the shared
  `#chart-enlarge` modal, with the β + minting rate as the headline + a dashed "perfectly linear" reference
  line; the closer the curve hugs it, the more junk) + a "(.json)" download for the maintainer↔dev loop.
  tests/test_keyword_growth.py (4: cumulative+monotonic+decrypt-free [proven by seeding mentions with NO
  Article rows], undated counted, Heaps fit separates saturating-vs-junk, empty-corpus honest) +
  test_repo_invariants::test_keyword_growth_curve_wired_and_decrypt_free. REMAINING: human click-through
  (fork-3); a log-log toggle on the in-app chart; optional x-axis = cumulative articles.
- **INSTALL/BOOTSTRAP FIELD-TEST FIXES (2026-06-23, Qubes disposable VM; branch claude/magical-brown-49m9nd,
  stacked on the stopwords PR #446; bash -n + tests VERIFIED):** TWO real field failures. (1) BOOTSTRAP
  DIVERGENCE — origin/0.09 was FORCE-UPDATED (history rewritten) + the install checkout had a stray commit,
  so `git pull --ff-only` dead-ended with a raw git hint. `scripts/bootstrap.sh` now tries
  `git merge --ff-only FETCH_HEAD`; on divergence it SNAPS a CLEAN checkout to upstream (`reset --hard
  FETCH_HEAD` — the expected recovery for an install copy that mirrors origin) and only REFUSES (with
  stash/reset guidance) when there are uncommitted local changes — never the raw dead-end. (2) PIP "No space
  left on device (Errno 28)" — pip unpacks big scientific wheels (scipy 35MB/numpy/pandas) in TMPDIR, which on
  Qubes is /tmp = a SMALL RAM-backed tmpfs, so it fails even though the private/home volume has room (the
  maintainer confirmed plenty of space). `install.sh:pip_install` now points `TMPDIR` at the install volume
  (`$XDG_CACHE_HOME/oo-pip-build`) AND CLASSIFIES the failure: disk-full gets its OWN guidance (`df -h /tmp …`
  + Qubes private-storage hint, stop — retrying won't clear a full disk), network keeps the retry+DNS message.
  CORRECTS the prior over-broad "almost always a NETWORK problem" message that misdiagnosed this Errno-28 case.
  tests/test_installer.py (+3: bootstrap ff-fallback/clean-snap/dirty-guard content + a REAL git divergence-
  recovery behavioural test; pip TMPDIR + disk-full classification). 26 installer tests pass.
- **STOPWORDS-ISO LANGUAGE-SCOPED LISTS (2026-06-23, maintainer field logs: "400k keywords, address it for
  good"; branch claude/magical-brown-49m9nd, draft PR onto 0.09; backend VERIFIED py3.11):** the 2026-06-23
  keyword-engine report (27,303 articles / 406,723 keywords / 1.8M mentions) showed ~88k keywords leaking
  FUNCTION WORDS in space-segmented languages. The PARALLEL session already PROMOTED those languages to
  managed (2026-06-22, in 0.09: tr/ro/uk/fi/ur/cs/ca/sk/et/hi/bn/fa/sw/az/bs/hr managed, th unsegmented) with
  HAND-BUILT grammar stoplists in extract.py applied via the GLOBAL union — but conservatively (length>=4 /
  accented-only to dodge cross-language collisions), so they MISS short function words (tr ise/ilk, ro
  sau/iar/cum, fi ole/eli, cs jen/pak/než). COMPLEMENT, not replace: vendored a SUBSET of stopwords-iso (MIT)
  for the 14 space-segmented langs → `configs/stopwords_iso/<lang>.txt` (5,670 words) applied LANGUAGE-SCOPED
  via a NEW `stopwords_manager.scoped_stopwords` channel (`get_stopwords(lang)` returns the lang's OWN list;
  kept OUT of the language-agnostic `global_stopwords()` union so a word grammatical in one language [vi nam]
  can never hide content [Nam] in another). On re-index the short function words now drop too.
  `STOPWORDS_ISO_AS_OF="2026-06"` + registry entry (configs/external_artifacts.yml) + `scripts/build_stopwords.py`
  (networked refresh). tests/test_stopwords_iso.py (4). managed.py UNTOUCHED (parallel owns it). KEY FINDING:
  the 2026-06-23 report was from an OUTDATED app build — the latest 0.09 already promotes those langs, so
  UPDATE → re-index → prune already drops most of the ~88k. REMAINING (noted, parallel owns extraction): ~35k
  digit-heavy code tokens (A-10C/1h15 — drop_numeric only hides PURE-digit at query time); the "?" 30k
  unknown-language bucket (English gov-newsletter boilerplate govdelivery/gd_combo_table + undetected English
  → needs language detection + .eml boilerplate filtering); translation_coverage 13.4% (rings); tag_coverage
  0% (run baseline-tag backfill). The 287k single-article hapax (71%) is the LEGITIMATE multilingual long
  tail — policy-protected (no arbitrary cap).
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
  importorskip py3langid so the core-only lane skips them). ruff F/B clean. FRONTEND SHIPPED 2026-06-23
  (browser-unverified per fork-3): `/api/articles` exposes `detected_language` (both serialisation paths)
  and the analysis Articles list renders a `_anToneChip` — a sentiment tone chip (stored VADER, English-only,
  "a signal not a verdict") + a "deduced: XX" language hint shown ONLY when the source left the article
  untagged; null-safe, theme-coloured (var(--ok)/--err/--muted), English-fallback strings (i18n gate 100%).
  test_repo_invariants::test_articles_endpoint_serialises_stored_sentiment extended. REMAINING: surface it in
  the standalone reader too; measure the live-corpus "?"-bucket reduction after a re-index.
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
- **HOME-CARD FLIP REDESIGN (maintainer chat 2026-06-23: "make them look more like cards · families themed ·
  all same size · a front and a back, clicking flips with a nice animation · spread info onto both sides ·
  move the orange caveat off the card, put it in the analysis · on the back a standardized themed button that
  opens the card's corpus IN A NEW WINDOW"; branch claude/trusting-maxwell-p7y2g8, draft PR #445 onto 0.09;
  FRONTEND, BROWSER-UNVERIFIED per fork-3):** the briefing Lead card is now a two-sided 3D FLIP card. FRONT =
  the lead at a glance (family-themed chip + title + summary[line-clamped] + signal + a "Details & corpus ⟲"
  hint); BACK = caveat + Method + "Why am I seeing this?" plain + the exact-math `<details>` + evidence + the
  action row. `cardHtml` restructured into `.card-inner > .card-face.card-front + .card-face.card-back`; CSS
  scoped to `.brief-bucket .card` (every OTHER `.card` — empty state, tiles — UNTOUCHED): fixed `height:
  var(--lead-h,292px)` = ALL CARDS SAME SIZE, `transform:rotateY(180deg)` flip with a `prefers-reduced-motion`
  off-switch, `backface-visibility:hidden`. FAMILY THEMING: each bucket already sets `--fam` (a per-family
  hue); the faces' top-border + chip + the standardized `.lead-open` button are themed with `var(--fam)`.
  CLICK FLIPS (`leadFlip`/`leadFlipKey` — Enter/Space, inner controls excluded; the card is `role="button"
  tabindex=0`). The CAVEAT MOVED OFF THE FRONT onto the back (informed-consent PRESERVED — see invariant #23
  amendment: the back is an equal side one flip away, NOT a hidden toggle, beside the open action). The
  standardized themed "Open corpus ↗" button opens the card's corpus IN A NEW WINDOW — `openCardCorpus(ids)` /
  `openCardCorpusQuery(seed)` → `window.open("/?corpus=…"|"/?analyze=…")`; a boot deep-link
  `_hydrateCardCorpus()` hydrates the fresh SPA tab (`showTab("analyze")` + `openAnalysisForIds`/`openAnalysisFor`).
  Exact set when the card carries `article_ids` (the 5 set-based producers), else the seed query (the
  home-card diagnostic flags any that lose their corpus). The per-card "?" affordance (P2-2) is RETIRED — the
  flip is the detail layer. +4 i18n keys ×12 (Method · Open corpus · Details & corpus · "Open this Lead's
  corpus in a new window"; non-en AI-drafted, flagged). test_ui_invariants #23 rewritten (flip front/back +
  caveat-on-back-not-front + method-on-back + leadFlip + openCardCorpus + window.open + the boot deep-link +
  the equal-size/`--fam` CSS); node --check + full test_repo_invariants (128) + i18n --min 100 (1627 ×12) green.
  REMAINING: human click-through across themes/breakpoints (fork-3); also render the caveat INSIDE the opened
  analysis window (today it travels on the back beside the open action + the analysis has its own subtab caveats).
- **GOVERNMENTS TAB — rename World Law + per-country data + map (maintainer chat directive 2026-06-22:
  "Change World Law into Governments. Diversify the subtabs. I want per-country data with GDP, labor, life
  expectancy, population, public deficit + all commonly-used country indices. The law will be a tab,
  another tab will be a world map with per-country data visualization (color, selectable, data history)."
  branch claude/trusting-maxwell-p7y2g8, draft PR onto 0.09):** built on the EXISTING substrate — `StatFigure`
  (per-country/indicator/year vintaged store) + `src/stats/fetch.fetch_worldbank(code,"all")` + `ooMap`
  (choropleth) + `ooSubtabs`. PLAN: Governments tab with subtabs **Countries · Map · Law** (Law = the existing
  tracker as a subtab; Map = an ooMap choropleth of a selectable indicator with a year/history slider;
  Countries = per-country indicators + history). **SLICE 1 — BACKEND SHIPPED (VERIFIED py3.13):**
  `src/stats/indicators.py` = a curated catalog of 12 World Bank series (GDP/GDP-per-capita/GDP-growth/
  inflation · population/pop-growth · life-expectancy · unemployment/labour-force · net-lending-deficit/
  central-debt · Gini), dated by `CATALOG_REVISED` (deliberately NOT an `*_AS_OF` constant — codes are stable
  references, the DATA is vintaged per fetch, so it stays out of the external-artifact registry); codes
  believed-correct but a WRONG code fails LOUDLY (empty series → "no data", never fabricated; verify on a
  networked box). `src/api/governments.py` (wired into the spine): `GET /indicators` (catalog), `GET /map?
  indicator=&year=` (per-country latest-or-year value + the years present for the slider; 404 on an unknown
  indicator), `GET /country/{iso}` (all curated indicators + latest non-null + bounded history per indicator;
  a published gap stays None, never zero), `POST /load-standard` (the ONE networked action — fetch the curated
  set for ALL countries via fetch_worldbank, airplane-gated up front → 409, records subscriptions, degrades
  loudly per-indicator). All reads over the existing vintaged store (no network); honesty carried (producer's
  published value never a score, gaps never zero, producers never averaged). tests/test_governments_api.py (6:
  catalog/no-score-field, map latest-per-country + specific-year + 404, country all-indicators-with-gap,
  airplane refusal). **ISO BRIDGE (enabling data):** WB stores alpha-3 (FRA) but ooMap + Intl.DisplayNames
  use alpha-2 (fr), so added the ISO 3166-1 `ISO3_TO_ISO2`/`ISO2_TO_ISO3` maps + `to_iso2`/`to_iso3` to
  src/catalog/countries.py (aggregates WLD/EUU have no alpha-2 → dropped from the choropleth, never mapped);
  the /map endpoint returns alpha-2, /country accepts either; self-checking test (well-formed, unique,
  spot-checked majors). **SLICE 2+3 — FRONTEND SHIPPED (BROWSER-UNVERIFIED per fork-3):** World Law→Governments
  (nav span + NAV label + "Governments" key ×12 [en/fr/de/es/pt/it/nl/ru/ar/zh/ja/hi/bn/id…]; tab id stays
  "law", timemap→"World map" precedent). #tab-law restructured into ooSubtabs **Countries · Map · Law**
  (relocated to the top facet strip via _SUBTAB_NAV; TAB_LOADERS.law → loadGovernments). COUNTRIES subtab:
  a country picker (from the stats coverage) → per-country indicators grouped by category with the latest
  value (+year) + a dashChartSvg history sparkline (Item-Y honest), `_govFmt` compact units ($3.0T, 67.9M,
  %). MAP subtab: ooMap choropleth fed by /map, an Indicator picker + a Year selector (history; "" = latest
  per country), valueLabel via the smart formatter + ooRegionName, click-a-country → its Countries detail.
  "Load standard country data" → ensureOnline (the ONE consent #14) → POST /load-standard → reload. The
  existing law tracker is PRESERVED as the Law subtab (Desk lesson — law-status/changes/docs all kept).
  New UI strings English-fallback via t() (gate 100%). test_repo_invariants::
  test_world_law_renamed_governments_with_subtabs. VERIFIED: full suite 2069 passed, mypy 126≤127, ruff F/B
  clean, i18n 100%, node --check. REMAINING: a bundled offline indicator snapshot (needs a networked-machine
  WB fetch — 403 in-sandbox; fetch-on-demand works meanwhile); human click-through across themes/breakpoints;
  a Compare subtab (multi-country side-by-side) + per-country flag/name polish; key the new English-fallback
  strings ×12.
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
  `docs/archive/SOLO_SESSION_DECISIONS.md` + `docs/archive/audits/*_2026-06-15_solo.md`):**
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
- **AUDIT REMEDIATION PASS (2026-06-15, acts on `docs/archive/audits/AUDIT_LOG_2026-06-14.md`;
  plan + per-finding status in `docs/archive/audits/ACTION_PLAN_2026-06-14.md`; ONE PR onto
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

- **DATE-EXTRACTOR F4 SLICES A+B 2026-07-02 (PRs #542/#544/#545; entries in shipped.csv):**
  two reusable facts. (1) **VERIFY-BEFORE-PUSH under fast-merge:** the maintainer merged
  #542 while adversarial verification was still RUNNING — six real defects (duben-village,
  cross-month ranges, gengō year-0, sentence-boundary range traps…) landed on 0.09 and needed
  a follow-up (#544). The working rule since: parallel skeptic agents (distinct lenses:
  fabrication/collision, regression/lockstep, robustness) must COMPLETE and their reproducers
  must be pinned as tests BEFORE `git push` — applied to slice B (#545), where two skeptic
  rounds each refuted the first cut pre-push (kolovoz="roadway" in Croatian traffic prose,
  지난해 3-syllable deictic, 号 classifier nouns 11号线/11号楼, citation-shape Agosti/Machi/
  Marso, 년형 model-year, digit-glued numerals). (2) **CJK REGEX BOUNDARY FACT:** ideographs
  are `\w` in Python `re`, so `\b` NEVER fires between an ideograph and an ASCII digit —
  "报道于2024-06-11发布" was invisible to both the extractor and the diagnostics probe (the
  field coverage numbers structurally undercounted). The fix is explicit digit-safe
  lookarounds (`(?<!\d)(?<![A-Za-z_])` … `(?!\d)(?![A-Za-z_])`) that block the SAME ASCII
  neighbours `\b` blocked while letting ideograph-glued forms match; keep the digit rule for
  ALL scripts so a date is never carved out of a longer mixed-numeral. COROLLARY (lockstep
  rule): every extractor vocabulary/pattern gain MUST land in `datediag.py` the same commit,
  or the probe reports phantom gaps / undercounts (MONTH_VOCAB_LANGS had 5 stale omissions).

## 2026-07-09 — fa Jalali fabrication fix-forward (post-merge audit of PR #590)

A post-merge adversarial audit of #590 found the Jalali→Gregorian arithmetic EXACT but three
inputs that STORED a wrong date: (V1, new in #590) `_FA_MY_RE` had no left boundary and دی (Dey)
is the word-tail of common Persian words, so "سال عادی ۱۴۰۳" fabricated Dey 1403; (V2) the fa
numeric router claimed only on SUCCESS, so an invalid (۱۴۰۲/۱۲/۳۰, 30 Esfand non-leap) or
out-of-window (۱۴۲۰/۰۱/۰۱) Jalali date fell through to the generic numeric loop and stored a
medieval CE date; (V3) day-first ۱۱/۰۳/۱۴۰۳ was read as 1403-03-11 CE by the generic DMY loop.
Fixes: `(?<![\w‌])` lookbehind on `_FA_MY_RE` (word char + Persian ZWNJ); CLAIM-ON-ROUTE in
the fa numeric router; a fa-gated claim on day-first numerics with a Jalali-range year (order is
an assumption we refuse — skipped, never guessed). datediag lockstep holds by construction (it
imports the same compiled pattern objects). 5 pinning regressions; controls hand-verified.

**LESSON (refines VERIFY-BEFORE-PUSH):** #590's own pre-push verification claimed 5 skeptic
lenses and still shipped 3 fabrications — the lenses verified the POSITIVE space (goldens exact,
gates hold) and never attacked the NEGATIVE space (inputs that must yield NOTHING). A
no-fabrication skeptic must generate should-be-empty inputs per pattern — every alternation
member as a word-tail/prose fragment, every router failure path, every order-ambiguous form —
and assert `[]`. Corollaries: a language/calendar router must CLAIM-ON-ROUTE (consume the span
even when validation fails) or generic loops re-read the digits under another calendar; with
`_MIN_YEAR=1000`, any 4-digit year leaking past a router stores a plausible medieval CE date, so
routers over shared numeric shapes are fabrication-critical.

## 2026-07-09 — THETA R2: serve-by-default + rebuild-on-change (P1.11 · P1.10 · P1.12 · P1.5 + riders)

Branch `claude/theta-field-logs-snappy-0u0fb0`, draft PR onto 0.1. The 12:14 field logs'
snappiness batch: the D4 map serve flipped DEFAULT-ON (tri-state like rollup_serve; the
map/ring country GROUP BY was the #1 slow query at ~150 s/call with the built serve
dormant); the blind 15-min TTL rollup rebuild replaced by CHANGE-GATED refresh
(`src/analytics/serve_gate.change_token` = corpus epoch + append id tails; min-rebuild
interval bounds churn under continuous ingest; 1-h backstop covers token-invisible change
classes; staleness stays disclosed via basis.as_of/stale); reconcile/prune gained soft
deadlines + resumable `derived_meta` watermarks (partial passes disclosed — the envelope
refuses `exact` until a sweep completes); NEW `src/monitoring/storage.py` dbstat
storage-composition diagnostic; the /status noprobe cache key and pollJobStatus timeout
riders. P1.6 roadmap row corrected (the corpus-epoch mechanism WAS already shipped).

REUSABLE LESSONS / EMPIRICAL FACTS:
- **dbstat is a PER-BUILD SQLite capability — probe it, never assume it** (probed
  2026-07-09: `no such table: dbstat` on a sqlcipher3 connection; Linux stdlib sqlite3
  has it; the macOS CI runner's Python build does NOT — the observation lane caught two
  `available is True` assertions red at #606's head SHA, fixed forward with a runtime
  `_dbstat_available()` skip-probe). Any dbstat-based introspection DEGRADES on the
  encrypted live store and on some plaintext platforms — design it with an honest
  `{available:false, reason}` block plus the PRAGMA-level facts
  (page_size/page_count/freelist_count work everywhere), and test the degrade path as a
  production path.
- **Never key a cache on `id()` of a per-request object.** CPython recycles addresses:
  within a TTL window a later request's Session can land on the SAME `id(db)` and hit an
  entry computed for a different engine (wrong corpus) or a pre-write snapshot. A
  "per-call" key must be a monotonic nonce (can never recur), qualified by the BIND for
  attributability; a bounded cache (SimpleCache max_size) absorbs the one-shot entries.
- **Change-gating a derived-layer rebuild needs BOTH the epoch AND an append watermark:**
  ordinary ingest appends without bumping the corpus epoch (by design), so a pure
  epoch gate freezes the rollup during collection; and the epoch must be read with a
  COLUMN query (`session.query(DerivedMeta.value)...`), never `session.get`, whose
  identity map hides another connection's bump inside a long-lived session.
## 2026-07-09 — ETA Round-2: collector OOM fix (P0.3) + collector write batching (P1.8)

**BUILD (branch claude/eta-memory-bounded-collection-6dt90s, draft PR onto 0.1; commit per item;
FULL suite green per item on the py3.13 .venv; mypy 127; ruff F,B; bandit -ll clean):** the
2026-07-09 field event — kernel OOM at RSS 10,599 MB on a ~10,237 MB VM, 21.6 h into ONE
continuous crawl pass, killed SILENTLY; plus 847,351 s cumulative writer-gate wait (~22% of
worker time, 234,551 contentions, max single wait 438 s).

E1 instrument+bound: fetcher host caches bounded (robots cap = fail-closed recompute on
eviction; last-request evicted politeness-first, only >6 h old; host locks NEVER evicted —
eviction would let two threads hit one host); per-sample memory gauges + the RSS curve on every
pass summary; between-pass release (trafilatura reset_caches + gc + glibc malloc_trim), measured.
E2 pass recycling: OO_PASS_BUDGET_MINUTES (default 60) + OO_PASS_MAX_SOURCES bound one pass; the
un-run remainder defers and runs FIRST next pass (exactness pinned: processed + deferred == all).
E3 RSS memory guard: measured psutil trip/resume latch, hysteresis both ways, missing readings
carry no information; pauses loudly (phase paused-low-memory + status.memory_guard), resumes on
measured recovery or user action; never touches the writer gate. E4 WAL checkpoint(TRUNCATE)
between passes via write_lock(), measured, honest busy=1 partial under an active reader.
E5/P1.8 write batching: fetch/extract/links OUTSIDE the gate (HTML dropped at stage; buffer
bounded by count AND bytes), ONE transaction per batch via index_article(commit=False) +
rollback-then-redo-per-article; zero loss pinned (Nth-article collision, death-between-commits,
live contention race with exact counters). Soak (src/testing/collect_soak.py, zero-network by
construction — socket.socket is a TRAP in the smoke test): flat RSS across recycled passes,
guard proven pause-not-die on injected fake readings, gate windows/article measured.

**THE REUSABLE LESSON (found by the pre-push skeptic pass, reproduced empirically):** AUTOFLUSH
CAN HAND THE WRITE GATE TO A READ. The gate acquires on FLUSH, and SQLAlchemy autoflushes dirty
state on the next QUERY — feed bookkeeping written BEFORE the article loop meant the loop's
first dedup SELECT acquired the gate and held it ACROSS the article fetch (legacy: the whole
first fetch of every first-contact feed — the field's 438 s max-single-wait signature; batched:
the WHOLE feed). Probe: a fake session asserting `write_gate.stats()["held"] is False` inside
`get()` (before the fix: legacy [True,F,F,F,F], batched [True×5]; after: all False). Rule: on
gate-wired sessions, write bookkeeping AFTER the network loop and COMMIT it before returning so
the session leaves clean — the sequential pass shares ONE session across sources, so pending
bookkeeping otherwise gates the NEXT source's fetches too.
## 2026-07-09 — P0.1 streaming backup engine (Round 2 ZETA, oo-volumes-2)

Full row in shipped.csv (backup/scale). Two reusable lessons:

**LESSON — a "streaming" pipeline is only as bounded as its WORST stage; audit the
resilience layer too.** The roadmap assumed "the volumes+parity streaming path should
already handle 11.7 GB". The volume writer did stream — but `write_parity`/`recover_volumes`
loaded EVERY volume into RAM at once (`_load_padded` × N = the whole archive), so the parity
stage alone was a guaranteed OOM at the field's 11.7 GB corpus on the 10 GB VM — on the very
path meant to save the corpus. When a path is claimed bounded-RAM at scale, grep every stage
(including erasure/verification/checksum layers) for whole-set materialization; one stage
voids the claim. Fix: banded GF(2^8) (encode holds (M+1) bands, decode (erased+1)) —
bytewise-identical output, test-pinned.

**LESSON — incremental-in-place is a data-loss footgun (the rsync --inplace hazard).**
The first cut of changed-volume re-emit used deterministic per-slice file names, i.e.
re-emitted volumes OVERWROTE the files the previous complete manifest referenced — so an
interrupted refresh would have degraded the user's last good backup (caught by the pre-push
negative-space pass, fixed before ship). The safe shape: emitted volumes get RUN-UNIQUE
names, reused ones keep theirs, the new manifest lands by atomic replace, and superseded
files are garbage-collected only AFTER finalize — an interrupted or cancelled refresh then
leaves the previous set fully verifiable and restorable (test-pinned). Corollary for any
manifest-of-files format: names in a manifest anyone can self-sign must be traversal-guarded
before verify/restore touches the filesystem (a signature proves consistency with the
EMBEDDED key, not trust).

## 2026-07-10 — Post-merge adversarial audit of the Round-2 wave → ZETA backup-path hardening

An 8-lens negative-space audit ran over the merged ZETA/ETA/THETA wave (backup + collector +
serve) at tip 1dcf4b9 — after the full suite was green (3340 passed), because per-PR CI cannot
catch the negative space (hostile-manifest traversal, crash interleavings, scale ceilings) nor
cross-branch composition. Crypto/snapshot consistency (OOENC2 truncation/reorder/extension/
overflow all fail loudly; key-check unforgeable; writer-gate excludes commits; residual-WAL
fold-back correct), THETA serve gates (append-tail moves during collection; epoch read is a
two-connection-safe column query; map-serve parity+fallback; reconcile envelope refuses "exact"
until a full sweep; noprobe key uses a monotonic nonce), and the ETA memory guard/pass-recycling
(hysteresis both ways, %-of-total so no false-fire on a big box, never touches the write gate,
deferred==all + carry-head-first) all verified GUARDED. WAL double-checkpoint (ZETA vs ETA) and
append-cadence-vs-serve-gate verified SAFE (both checkpoints gated, mutually exclusive).

Every candidate finding was hand-re-verified against the code before it counted (the 06-audit
false-positive discipline) — and one sub-agent's output was a prompt-injection (a fake "security
validation" asking to curl the cloud metadata endpoint for IAM credentials); refused, discarded,
the lens re-run with an injection-resistance instruction. The confirmed defect cluster on the
backup finalize/restore path was FIXED FORWARD (branch claude/zeta-hardening-audit, draft PR onto
0.1; backup/api/parity suites green, 75 passed):

- F1 [HIGH security/data-loss]: restore read the top-level `corpus_member`/`wal_member` manifest
  fields (and per-member `members[].volumes[]` refs) WITHOUT the traversal guard that covered
  `members[].name`/`volumes[].name`. `_prepare_staged_corpus_files` turns them into `staging/<name>`
  and unlinks them; since staging is `data_dir()/.restore-*`, a `wal_member` of `../open_omniscience.db`
  deletes the LIVE corpus (the encrypted branch opens+unlinks an arbitrary SQLCipher-openable DB).
  `_require_safe_manifest_names` (called by BOTH restore and verify) now validates these fields too.
- F5–F8 [HIGH data-loss / crash-safety]: finalize wrote the new UNSIGNED, parity-less manifest OVER
  `dest/volumes.json` before signing (and before the parity phase, the longest for a large set), so a
  crash/kill/parity-failure left the previous complete backup's signed manifest gone and an
  unsigned-complete manifest at the canonical path — which `cleanup_cancelled_build` (unsigned ⇒
  disposable partial) then deletes on a cancel, total loss. Finalize now builds the fully-signed
  (+parity) manifest in memory and swaps the canonical path in ONE atomic `os.replace`; the previous
  signed manifest survives until that single commit point, so an interrupt or an uncaught parity
  failure leaves the previous backup fully verifiable+restorable and no unsigned manifest ever lands
  at the canonical path. `write_parity` gained an opt-in in-memory manifest mode (records parity into
  the building manifest, writes the .oopar files, never touches `dest/volumes.json`) and its legacy
  on-disk write is now atomic (temp + os.replace).
- F12 [low]: `OO_WRITE_GATE=0` makes the corpus-stream write-pause a no-op, so a concurrent commit can
  tear the image while the summary still reports "writes paused". The live freeze now appends a loud
  WARNING note (into the summary + signed envelope) when the gate is disabled — degrade loudly.
- F4 [nit]: the encrypted-store backup refusal (BackupError) returns a clean 400, not an ungraceful 500.

Deferred to SCALE_ROADMAP (confirmed, out of scope): F6 parity's GF(2⁸) N+M<256 ceiling (~128 GB
corpus, impossible at the 5 TB mandate → adaptive/larger volume sizing, folds into P0.1 — the finalize
fix already ensures hitting it never destroys the previous backup); F13 the batched collector flush
holds the write gate across per-article keyword+WWW EXTRACTION not just the DB write (undercuts P1.8);
F10/F11 backup gate-hold (drain-wal lock-order inversion; gate held across `_corpus_facts`' full scan);
F3 restore preflight under-count (fails safe); F14 markets dirty-session gate-across-fetch (pre-existing).

LESSONS: (1) traversal-guard EVERY manifest/config field that becomes a filesystem path — not just the
ones literally named "name"; a guard is only as complete as its field list, on BOTH verify and restore.
(2) a finalize that overwrites the canonical artifact before the replacement is signed/valid has a crash
window that destroys the prior good artifact — build it complete in memory, swap atomically ONCE, keep
the old one until then; an uncaught erasure-code ceiling must never be able to take the last good backup
with it. (3) a test double injected via a parameter (corpus_source) bypasses the production path — a fix
in the real path needs a test that drives the real path (monkeypatch the real dependency), or it passes
while the fix sits unexercised.

---

## 2026-07-10 — B1: offline zh/ja/th word segmentation ([segmentation] extra) + ko/mr stoplists

Maintainer delegated ruling 2a (pick & ship a license-clean offline segmenter). Session B,
branch `claude/b-segmenter`, draft PR onto 0.2.

WHAT. zh/ja/th keywords were junk at scale (field test 2026-07-08: zh 46k + th 21k + ja 12k junk
keywords, Heaps β≈0.95, prune finds no orphans — segmentation is the ONLY lever) because the
whitespace tokenizer sees a whole zh/ja sentence as ONE giant "word" and shatters Thai at its
combining marks. These languages were honestly reported `unsegmented`.

CHOSEN. jieba (MIT, zh) + janome (Apache-2.0 bundled dict, ja) + pythainlp newmm (Apache-2.0, th)
— all pure-local, OFFLINE (dictionaries bundled IN THE WHEEL, no model download, no network;
verified), pip-installable via a NEW `[segmentation]` extra (preferred over repo vendoring: no
100MB rule, no license-file duplication, no `*_AS_OF` so no registry entry needed per the freshness
protocol). pythainlp core pulls ZERO extra deps.

SEAM. `src/analytics/segmentation.py`: `segment(text, lang) -> [(word, offset)] | None` (jieba
`tokenize` yields offsets directly; janome/pythainlp offsets reconstructed with a forward-cursor
`text.find` since surfaces concatenate to the input) + `segmenter_available(lang)` (a lightweight
`__import__` probe that does NOT load dictionaries — safe to call from a status check). Hooked into
`extract._terms()`: when `segment()` returns tokens, use them with a language-aware `min_len=2`
(CJK words are 2 chars — 中国/政策/経済 — so the Latin 3-char floor would drop them); else the
byte-identical whitespace `_WORD_RE` path (`min_len=_MIN_TERM_LEN=3`). GRACEFUL DEGRADE by
construction: extra absent OR `OO_SEGMENTATION=0` → `segment()` returns None → old tokenizer, and
zh/ja/th stay `unsegmented` (a core install is byte-unchanged; proven by test + the Core-only CI job).

STATUS FLIP. `managed.language_status()` is now segmenter-aware (zh/ja/th → `functional` only when a
segmenter is present, the vendored stoplist then applying); `is_managed` refactored to
`language_status(lang)=="functional"` (byte-identical for every existing language); `engine_report`
routes through the ONE source of truth. ko (Hangul) + mr (Marathi) added to MANAGED_LANGUAGES
(space-segmented, distinct scripts) with vendored stopwords-iso lists. Source-gating (`is_unmanaged`)
follows: with the extra installed, zh/ja/th sources seed ENABLED (existing sources keep their
operator choice — no disruption).

STOPLISTS. Vendored from stopwords-iso 0.7.1 (byte-identical to 0.7.0 for existing languages):
zh 794 / ja 134 / th 116 / ko 679 / mr 99. `STOPWORDS_ISO_AS_OF` 2026-06→2026-07, registry
`last_verified` 2026-07-10 (external-freshness green). sr/az stay honestly uncovered (absent from
stopwords-iso).

MEASURED (fixtures). OFF: whole SENTENCES as one keyword (`中国政府今天宣布了新的经济政策`) /
Thai mark-fragments. ON: real RECURRING words (经济/政策/市场/影响, 経済/政府/市場,
เศรษฐกิจ/รัฐบาล/ผลกระทบ). The corpus-level win is recurrence across articles (Heaps β falls from
~0.95), which is what makes aggregations meaningful.

CI. The main test job installs `[segmentation]` (the capability + the 3 zh/ja/th self-test golden
cases run for real); the Core-only job (no extra) proves graceful degrade. Retroactive path: a
keyword-only re-index applies segmentation to an existing corpus.

VERIFIED (py3.13 venv): 73 seg/managed/report/extract + 241 keyword/freshness/invariants green;
ruff F/B clean; mypy 0 new in-file errors; selftest 46/46 (incl. segmentation_{zh,ja,th}).
NEGATIVE-SPACE SKEPTIC PASS found + FIXED two real defects the first cut introduced: (1)
`language_status()` normalized the code (`zh-CN`→`zh`→functional) but `segment()` required an EXACT
match, so a region/script-tagged article (`zh-CN`, `zh-Hans`, `ZH`) reported 'functional' (source
seeds ENABLED) while extraction silently skipped segmentation — FIX: normalize the bare ISO code in
`segment()`/`segmenter_available()` AND at the top of `extract._terms()` (which also routes a
region-tagged code to its proper scoped stoplist, a correctness bonus). (2) the 2-char floor was
per-DOCUMENT, so a stray 2-letter LATIN token (`vs`/`ai`/`eu`) leaked in a CJK doc — FIX: a per-TOKEN
script-aware floor (`_term_floor`/`_CJK_THAI_RE`: 2 for a CJK/Thai word, 3 for Latin even inside a
segmented doc). Both pinned by tests. REFUTED: byte-identical fallback, offset fidelity, import
cycle, heavy status-check load, kill switch, adversarial inputs, determinism. RESIDUAL (honest): a
few uncovered CJK function words leak (stopwords-iso `ja` is a thin 134-word list) — the same
iterative stoplist tail every language has, far better than whole-sentence junk (never fabricated).

LESSONS folded into the Session-rituals "Lessons" subsection: optional-seam design, `min_len=2` for
CJK, offset reconstruction via forward-cursor, lightweight importability probe for status checks,
the Heaps-β corpus-recurrence framing.

---

## 2026-07-12 — S1: the v0.2.0 P0 data-safety validation kit (Tier-0 release kit)

Branch `claude/s1-p0-validation-kit-p4x3px`, one draft PR onto 0.2. Skeptic-verified pre-push
(4 distinct lenses, all GO; 7 findings applied), full-suite-green (py3.13 .venv, 3400 passed /
64 skipped).

**S1.1 post-wave health check.** The A+B wave (#614–#631) is clean: full suite 3400 passed on
the 0.2 tip, ruff (blocking) + i18n --min 100 + mypy 127≤127 all green — no fix-forward. FINDING
(pre-existing, carry-over): a subset-order pollution — `test_a2_job_endpoints.py`'s heavyweight
`TestClient(app)` lifespan fixture (real startup/shutdown = engine/airplane-guard/seeding), when it
runs before `test_diagnostics.py::test_doctor_healthy_returns_zero` in a subset with
test_repo_invariants/all_diagnostics_job/session_forensics, leaves `run_doctor()`'s DB-count query
failing → rc 1. Reproduces on clean origin/0.2; green in full-suite order (CI never hits it).

**S1.2 the push-button P0 validation JOB.** `src/monitoring/p0_validation.py` + a diagnostics
endpoint quintet (`POST /api/diagnostics/p0-validation`, `/status`, `/cancel`, `GET /last`,
`/download?format=json|txt`) + a Settings→Diagnostics panel (dest + passphrase → a click). One
cancellable `BackgroundJob` (is_writer=False, cancellable=True) runs the acceptance checks against
the operator's LIVE corpus: P0.1 backup (drives the real `write_volume_backup`, RSS-sampled via a
psutil thread; + an incremental refresh pass to show changed-volume re-emit) → `verify_stream_backup`;
P0.2 a STAGED restore (`read_volume_backup`) + a dry-run merge PREVIEW (`run_restore(commit=False)` —
never writes the live corpus); P0.4 reads the #596 per-phase unlock timing vs the <2 s bar; P0.3 reads
the collect_perf RSS curve + memguard state. ONE report: per-check `pass | fail | not-measurable-here`
against the written SCALE_ROADMAP bars (quoted into the report), measurements only, NO composite score,
NEVER a fabricated pass, backup-engine-format + app-version stamped. Wired as a debug-bundle +
all-diagnostics member (read-only — reads the LAST saved report, never runs a backup). Tests drive the
REAL live path (monkeypatch `live_db_path`, never a `corpus_source` double — ZETA (c)); assert the live
corpus is byte-unchanged, the passphrase never leaks, staging is cleaned on every path, and a cancel
leaves no complete-looking backup.

**S1.3** `docs/product/P0_VALIDATION_RUNBOOK.md` — click-by-click operator procedure + a maintainer-only
TAG-DAY CHECKLIST; linked from the Settings panel hint + the ROADMAP P0 section. **S1.4** the CHANGES.md
0.2.0 section is release-notes-ready (A+B-wave bullets; the "tag awaits live validation" line kept);
`release.yml` verified gating correctly (full-suite `test` job + tag==pyproject + SHA256SUMS +
`--verify-tag`) — no change needed; README/CONTRIBUTING version prose confirmed fine at tag time.

**S1.5 hardening (the 7 skeptic findings applied):** (1) the restore-probe staging is named with the
janitor-swept `.restore-` prefix + swept at run start — so a hard-kill mid-probe can't orphan an unseen
PLAINTEXT corpus copy on the external dest drive; (2) the collector climb heuristic dropped the
ratio-AND gate that hid a large-absolute/modest-ratio leak (a +1.9 GB rise on a 4 GB baseline) and no
longer asserts "flat" against climbing numbers; (3) a completed-but-unmeasurable backup (sub-2 GB / no
psutil) reports `not-measurable-here`, never a scale `pass`; (4) `_p0_scrub` is a real recursive
redaction on `/status`, not a no-op; (5) a malformed unlock record summing to 0 ms is not-measurable,
never a "0 ms pass"; (6) the "only ever read" phrasing made precise (the backup does a content-preserving
WAL checkpoint; the RESTORE never writes the live corpus); (7) an incremental-refresh failure is recorded,
not silently suppressed; plus cleanup_cancelled_build now runs on ANY non-passing backup (not only cancel).

LESSONS folded into the Session-rituals "Lessons" subsection: verdict-maps-to-the-bar-it-tested (+ the
AND-gate-hides-signal / a-named-scrub-must-enforce / retention-limited-diagnostic corollaries); the
external-drive-probe-needs-a-swept-prefix at-rest-encryption lesson; the `TestClient(app)`-lifespan
subset-order-pollution suspect.

---

## S2 (2026-07-12) — Tier-1: the P1 snappiness board (draft PR #633 onto 0.2)

Session 2 of the six-session program. Finished the P1 snappiness board against the written
bar. All slices committed to `claude/s2-snappiness-board-okqg27`; each risky slice
adversarially skeptic-verified BEFORE its push (S2.2: 3 lenses, 1 med fixed; S2.5: 2 lenses,
1 med fixed). Full per-slice detail = the six `docs/ledger/shipped.csv` rows.

**S2.1** A9 write-gate-hold riders (F10/F11/F13/F14) closed REPRODUCER-FIRST — all four
DECLINED with reproducers/analysis as evidence (no production code). **S2.2** A10 off-peak
maintenance is scheduler-owned + collector-idle (decoupled from the pass-tail warm_cache).
**S2.4** guard-coverage sweep — the previously-raw corpus-scaled reads (8 insights endpoints +
6 cards + omni + link_analysis OOM materializations) now behind the admission cap + deadline.
**S2.5+S2.3** /api/articles moved async→plain def (threadpool, no event-loop freeze) + an FTS
over-fetch bound (id-only resolve → load the PAGE only; GAMMA-measured 50 ms→11 ms warm) + a
data-aware cached browse COUNT(*). **S2.6** the 5 TB architecture review doc (S3's input).
**S2.7** a per-endpoint p95-vs-500 ms snappy verdict in the latency reservoir.

**LESSONS folded into the Session-rituals "Lessons" subsection:**

- **Reproducer-first for gate-hold riders — a REAL hold is not a reason to fix it (S2.1):** a
  write-gate hold being present is not sufficient. MEASURE the throughput ceiling (GIL-bound
  Python work gets no gate-split gain beyond the amortised-fsync overlap — batching already
  collapses N extractions onto ONE commit, so writes are the small part of the window) and
  weigh the hot-path risk. And a gate held across a scan can be MANDATORY: the streaming
  backup's `_corpus_facts` MUST run inside the `freeze()` gate because the tamper-evidence
  article-hash commitment has to match the streamed at-rest bytes — moving it out breaks
  correctness, not just risk (and it is a rounding error beside the multi-hour byte stream).
  F14's autoflush mechanism cannot fire under `autoflush=False` (a read never flushes a dirty
  session). Close a DECLINED rider with the reproducer AS the evidence (a test that pins the
  property or refutes the mechanism), never a hand-wave.
- **`async def` is a whole-server freeze; the fix is `def` OR `run_in_threadpool` — and slowapi
  works on sync `def` (S2.5):** a FastAPI `async def` handler runs ON the event loop, so heavy
  SYNCHRONOUS DB+codec work in it freezes the single worker for its whole duration (the
  unlock/restore/task-manager freeze family). Make the handler a plain `def` (Starlette runs it
  in the threadpool) or `run_in_threadpool` the body; `@limiter.limit` (slowapi) DOES work on a
  sync `def` (verified: `Depends(get_db)` lifecycle + exception handling intact). For FTS
  search, NEVER materialize the whole match to sort+paginate: resolve the surviving ids
  (fts ∩ filters) in the FINAL order via an id-only (+ sort-column) query, then load FULL rows
  for the PAGE only — content is decrypted for ≤limit rows, not the ~20k-match whole set.
- **`src/api/insights._cached` is DICT-ONLY — a scalar handed to it is a SILENT no-op (S2.5):**
  `_cached` persists and returns only dict payloads (a non-dict `out` falls straight through
  with NO `.set`, and a hit is recognised only `if isinstance(hit, dict)`). Handing it a scalar
  (an int count) makes the cache a silent no-op — correctness holds (always live/exact, so a
  freshness-only test passes) but the optimisation does NOTHING. Wrap the scalar in a dict
  (`{"count": n}`) and pin a HIT with a test that asserts the store, not just freshness.
- **Guarding an endpoint in `guarded_read`/`_deadlined` bounds even a whole-table
  `.distinct().all()` OOM (S2.4):** the statement deadline uses SQLite's progress handler, so it
  interrupts a runaway scan mid-query — a full Python materialization can never complete past
  the deadline. So wrapping (not only query-rewriting) an OOM-risk read is a real fix; the
  admission cap + single-flight additionally stop the death-spiral. The omnibar is the exception
  — it must never blank, so its guard DEGRADES (an honest empty-with-note payload) instead of a
  429/503.


## S3 (2026-07-12) — Tier-2: database & scale architecture (local branch claude/s3-db-architecture)

D1/D2/D3 persisted-columnar machinery (gated behind `secure_crypto_available()`), DB-9 adaptive
backup-volume sizing, the DB-10 retention/vacuum decision memo + the cross-time-recall invariant.
Reusable lessons:

**A PERSISTED DuckDB STORE OPENED VIA `ATTACH` REJECTS A SECOND IN-PROCESS HANDLE TO THE SAME FILE
(2026-07-12, S3.2):** `duckdb.connect(config).execute("ATTACH '<file>' AS oo")` on a second
connection while the first still has it attached raises `Binder Error: Unique file handle
conflict`. (Two plain `duckdb.connect(file)` handles DO share the in-process instance — but the
columnar store uses ATTACH.) So the in-memory rollup-serve model — build a fresh connection, swap
it in, close the old — CANNOT apply to a persisted file: use ONE held connection refreshed IN
PLACE under the serve lock (incremental via `refresh_keyword_daily`; full rebuild only on an
epoch change). Verify the file-handle semantics empirically (an unencrypted duckdb file has the
same locking, so the serve concurrency/incremental/durability logic is testable without the
encryption, which is CI/operator-only) before designing the persisted serve.

**ADAPTIVE BACKUP-VOLUME SIZING MUST COUNT PER-MEMBER SLICES, NOT ceil(total/size) (2026-07-12,
S3.3; an adversarial skeptic caught this pre-commit):** the streaming backup slices EACH member
independently (`_emit_member`: `ceil(size_m / vsize)` per member), so the real data-volume count
is the SUM of per-member ceils + the members emitted AFTER sizing (the manifest.json member, a
residual WAL member) — NOT `ceil(total/vsize)`, which undercounts by up to one volume per member.
Sizing against the single-division form let a high `parity_fraction`, a high
`OO_BACKUP_TARGET_VOLUMES`, or many side members push the REAL N+M over the GF(2⁸) 255 ceiling →
`write_parity` aborts the whole backup (not data-loss — the crash-safe finalize keeps the previous
backup — but it defeats the fix at exactly the target scale). The mandatory skeptic pass (fed the
diff + surrounding facts INLINE so it never opened the 1382-line file → no context overflow) found
it; the fix sizes against the real per-member sum + a reserve, regression-tested end-to-end.
LESSON: when the sizer's cost model diverges from the engine's actual emit loop, the guard is a
fiction — model N exactly the way the code emits it.

**CI-INSTALLS-THE-EXTENSION IS THE HONEST TRUST PATH FOR AN OFFLINE-VERIFIED BINARY (2026-07-12,
S3.1):** the D1 loader verifies a bundled httpfs binary against a SHA-256 pin BEFORE `LOAD`, but
the real binary can't be fetched in the sandbox (egress-blocked) and its sha256 must NEVER be
fabricated. So (a) the verify MECHANISM is proven against a FIXTURE binary whose sha256 is injected
in the test (no real binary, no network); (b) the shipped registry pins stay BLANK
(empty-pin-stays-in-memory is a pinned test); (c) a CI lane installs the real httpfs, computes its
sha256 IN-LANE, and runs the real encrypted round trip — that in-lane checksum is NEVER promoted
into `external_artifacts.yml`. The registry stays honest (blank) while CI still exercises the real
path. COROLLARY (DuckDB startup-only settings): `SET allow_unsigned_extensions=true` after connect
raises; it must be in the `config=` dict at connect. And `enable_external_access=False` blocks a
file ATTACH (Permission Error) — the persisted path uses a config WITHOUT it (network safety =
autoload-off + absolute-path LOAD + the airplane guard). Both verified empirically before writing
the loader.

---

**S4 — TIER-3 PRODUCT QUALITY (2026-07-12, branch `claude/s4-product-quality`, 7 commits onto
`origin/0.2` base b85bc124):** the reader-facing quality tail. S4.1 CJK-numeral date recall PROBE
(context-only, measures the gap, never asserts a date — extraction deferred). S4.2 ring-translation
per-language `language_breakdown` on the Trends/Home #oo-tip hover. S4.3 the synthesized-Leads Home
carousel (LOCAL synthesis never LLM, WCAG-pausable, caveat on every rotated face). S4.4 ported the
`/api/insights/context` snippet concordance into #an (the last Insights-bar capability). S4.5 the
composite-string i18n engine + translatable card titles. S4.6 the in-app `generic_terms` detector.
S4.7 the guided-wizard sources-by-theme step. Three reusable lessons (also in the Session-rituals
Lessons subsection):

**A VALUE-BEARING STRING IS ONLY TRANSLATABLE IF ITS KEY IS A FIXED TEMPLATE (S4.5):** a flat `t()`
lookup can never translate "3 of 10 articles" (the numbers vary → never matches a static key). The
fix is a COMPOSITE lookup `OOI18N.tf(template, vars)` whose KEY is a fixed `"{done} of {total}
articles"` template (keyable ×12) and whose VALUES are DATA interpolated after translation — the
frame translates, the data does not. Server-emitted titles ride the same seam (`Card.title_i18n` +
`title_vars`, English `title` the additive fallback). A `{placeholder}` with no var renders a literal
`{x}` → validate at construction (fail loud). Adding a new template key to `en.json` ALONE reddens
`--min 100` (en.json is the canonical key set; every locale must carry every key) → add to all 12.

**AN ONBOARDING THEME/COUNTRY PICKER MUST DEFAULT TO EVERYTHING, AND EMPHASIS ≠ EXCLUSION (S4.7):**
the cover-everything ruling forbids a first-launch picker silently narrowing the corpus. `select_tags`
is a FILTER, so DEFAULT all-selected and map all-or-none → `[]` (no filter); a partial pick is the
user's EXPLICIT, reversible focus, stated in the UI. For a country/language EMPHASIS use the
order-never-exclude levers (`country_priority` sort key, `language_equilibrium` cadence), NOT
`select_languages` (a filter). Before a settings-write from a "never posts the network" surface,
verify the endpoint has no egress side effect (`PUT /config` = `save_settings` only; `exclude_unset`
touches only the sent fields).

**ABSORB-THEN-HIDE, BUT AN INTERLEAVED SHARED COMPONENT BLOCKS THE BLIND HIDE (S4.4):** the Desk
lesson says retire a surface only once its replacement absorbs every capability. Port the missing
piece + add a REGRESSION GUARD on the absorption — but the HIDE can still be unsafe when the surface
interleaves the retirable part (`#ins-term` search bar) with a NON-searchable overview
(`#ins-landscape`, stays) AND a RELOCATABLE shared component (`#mm-kit`, moved into the corpus window
and back). A blind removal browser-unverified is the interleaved-shared-helper hazard (passes
`node --check`, breaks at runtime) → gate the hide on a browser-verified untangle, recorded as a
carry-over.

---

**S5 — TIER-4 DECIDED RULINGS + MEASUREMENT INSTRUMENTS (2026-07-12, branch `claude/s5-rulings-builds`,
7 commits onto `origin/0.2` base 6a904c2d):** turn the decided rulings into code + build the instruments
that unblock the measure-gated ones. S5.1 USGS minerals SUPPLY parser (rare-earths B12, never prices).
S5.2 the rule-based subjectivity/loaded-language engine (sentiment pivot). S5.3 the IR gold-set builder
(closes the measure-before-trust loop). S5.4 lemma-preview surfaced in the Diagnostics panel. S5.5 S&P
verify + `int`-country curation. Two adversarial-skeptic workflows (negative-space mandatory) found real
defects on S5.1/S5.2/S5.3, fixed pre-push. Three reusable lessons (also in the Session-rituals Lessons
subsection):

**A MULTILINGUAL LEXICON MEASURE MUST VERIFY THE TEXT'S SCRIPT — else a mislabelled language yields a
FABRICATED NEUTRAL, not an honest gap (S5.2):** a rule-based subjectivity scorer's honesty rests on
"density 0.0 is a real measurement, distinct from the unmeasured gap." That collapses when it trusts the
source-asserted language (unreliable) and scans a Cyrillic body against the English lexicon: 0 matches →
`density:0.0` reads as "measured, clean" when it's "wrong lexicon, unmeasurable" (same for unsegmented
CJK vs a Latin list). Fix = a cheap script guard (text dominant-script vs lexicon script; mismatch →
gap). The negative-space lens surfaces it; a positive-only suite passes right over it.

**A SUPPLY/PHYSICAL PARSER'S "NEVER A PRICE" MUST BE AN ALLOWLIST GUARANTEE, AND GROUPED THOUSANDS ARE A
FABRICATION TRAP (S5.1):** "never emits a price" can't rest on a unit-string check (misses €/£/¥/cents/
non-USD codes; trade measures are monetary) — narrow the MEASURE allowlist to always-physical measures.
Two negative-space traps: `float("350,000")` raises → a real figure becomes a fabricated `value=None` GAP
(strip US grouping first); a substring currency check false-POSITIVES ("euro"⊂"europium" drops legit
Europium supply) → match codes/words on a WORD BOUNDARY, symbols anywhere.

**"A SINGLE DOWNSTREAM VALIDATOR" IS A LIE IF THE BUILDER PRE-COERCES (S5.3):** a write-then-validate
file builder claiming `load_X` is the one loud validator is wrong when the build step coerces/drops
first: `int(2.9)==2` / `int(True)==1` land a fat-fingered grade as clean-valid, and a silent
`except: continue` drops a human's judgement. Validate strictly at the build layer (reject
float/bool/non-numeric loudly), detect a `str()`-key duplicate collision, and clean the `.tmp` on an
`os.replace` failure.

## 2026-07-13 — Columnar D1: canonical-basename httpfs LOAD (fixes the columnar CI-red root cause)

Branch `claude/columnar-duckdb-extension-init-j8rx67`, draft PR onto 0.2. `src/analytics/columnar.py`
+ `src/analytics/duckdb_ext/README.md` + `tests/test_columnar_httpfs_loader.py`.

ROOT CAUSE. The "Columnar store" CI lane's real-httpfs round-trip
(`test_ci_encrypted_persisted_round_trip`) was RED. DuckDB derives an extension's C init symbol
`<name>_init` from the LOADed file's BASENAME **split on the first dot** (`FileSystem::ExtractBaseName`
= basename split on `.`, take `[0]`). The D1 loader LOADed the bundled binary under its descriptive,
SHA-pinned name `httpfs-<plat>-v1.5.4.duckdb_extension`, so DuckDB derived `httpfs-<plat>-v1` and looked
for a nonexistent `httpfs-<plat>-v1_init` symbol → the LOAD failed → `secure_crypto_available()` returned
False → the persisted-ENCRYPTED store silently degraded to in-memory → the round-trip assertion
`secure_crypto_available() is True` failed.

FIX. `_persisted_connection()` now LOADs the already-SHA-verified bytes through a per-process temp COPY
whose basename is the canonical `httpfs.duckdb_extension` (`_canonical_httpfs_path`), so DuckDB derives
`httpfs` → `httpfs_init`. The bundled binary keeps its descriptive version-dotted name on disk (for
auditability); the SHA-256 pin + DuckDB version coupling + traversal guard are UNCHANGED and still run on
the REAL bundled file (`_verified_httpfs`, refactored to return `(path, sha256)`) BEFORE the copy.

SKEPTIC-HARDENED (adversarial negative-space pass — one MED finding, fixed). A first cut cached the copy
keyed on the source PATH and verified only the SOURCE on each call, so the "verify-before-LOAD on every
call / stale copy never served" claim was FALSE for the actually-LOADed artifact in two cases: (1a) an
in-place tamper/corruption of the private temp copy, and (1b) a re-pin to different verified bytes at the
SAME source path within one process. Resolution: key the cache on the verified DIGEST (1b invalidates
because the sha differs) AND re-hash the cached COPY against that digest before every reuse (1a is caught
→ re-copy from the just-verified source). Verify-before-LOAD now covers the loaded artifact on every call,
not just the source proxy. Thread-locked; the temp dir is removed on invalidation and at interpreter exit
(a single `atexit`); blank pins remain a pure no-op (zero temp copies ever in the shipped default).

HONESTY / SCOPE (no over-claim). The real-httpfs round-trip is CI-ONLY: `extensions.duckdb.org` is not in
the sandbox egress allowlist (curl 403), so the fix could not be run here against a real binary — the
"Columnar store" CI lane (which installs httpfs over the network + checksums it in-lane) is the
confirmation, and the fix is correct-by-construction against DuckDB's documented `ExtractBaseName`
(replicated in the regression test). The fix removes ONLY the symbol-mangling blocker: production D1/D2/D3
persisted-store is still gated on the operator bundling + pinning the per-OS binaries (the registry pins
ship BLANK); `secure_crypto_available()` stays False by default and returns True only once a verified
binary is present (which the CI lane proves the round-trip then works).

LESSON (also copied into the CLAUDE.md Session-rituals Lessons): DuckDB derives an extension's init symbol
from the LOADed file basename split on the first dot — LOAD a version-dotted extension under a canonical
`<name>.duckdb_extension` basename. And a cache that re-verifies the SOURCE but hands `LOAD` an
un-re-checked cached COPY makes "verify-before-LOAD every call" false for the loaded artifact — key on the
verified digest and re-hash the copy.

Tests: `tests/test_columnar_httpfs_loader.py` +3 (canonical-basename LOAD derives `httpfs` while the
dotted name mangles + `_persisted_connection` LOADs the canonical path not the dotted one; unbundled →
no copy; tampered-copy + re-pin → re-copy the verified bytes). ruff F/B + mypy clean on the changed file;
23 loader/engine tests pass locally (2 CI-only round-trip skips). README `duckdb_ext/` gained a
"Canonical-basename LOAD" section.

## 2026-07-17 — fix-forward: WWW-pass savepoint vs datestore's internal commit (the #691 regression)

CI went red on `main` from the first completed run after #691 (`716d698`): every lane failed the
single test `test_wherewho_ingest.py::test_index_article_persists_when_where_who` with `places == 0`.
Root cause: #691 isolated `index_article`'s when/where/who pass in `session.begin_nested()`, but
`datestore.store_for_article` ends with an internal `db.commit()`. Inside the caller's savepoint that
commit CLOSES the nested-transaction context, so the very next statement (the whostore places delete)
raises `InvalidRequestError: Can't operate on closed transaction inside context manager` — which the
WWW pass swallows BY DESIGN ("deductions are a bonus, never a blocker"). Net field effect: since
2026-07-15 evening, every ingested/re-indexed article WITH a newly-extracted date silently stored NO
places/entities (dates themselves survived — the inner commit persisted them first). Articles without
new dates were unaffected, which is why exactly one suite test (the only dated fixture) failed out of
~3,968. The lost rows are recoverable: a re-index re-runs the idempotent extractors.

FIX (savepoint-aware, behavior-preserving): `store_for_article`'s tail becomes
`db.flush() if db.in_nested_transaction() else db.commit()` — inside a caller-owned savepoint the
rows join it and the CALLER commits; the two standalone callers (`POST /api/dates/article/{id}`,
`index_recent`) keep their exact commit semantics. Pinned by
`tests/test_article_dates.py::test_store_inside_caller_savepoint_keeps_transaction_usable` (pure ORM,
runs even on py3.11) + the existing CI test.

LESSON (copied to Session-rituals): a store helper that commits internally breaks ANY caller-owned
SAVEPOINT — before wrapping an existing helper in `begin_nested`, grep it and everything it calls for
commit/rollback. And a swallowed-exception design hides exactly this failure class: the standalone
repro calling `index_article` directly is what surfaced the real exception (bonus: on py3.11 the
swallow path itself failed to import — PEP-695 in `write.py` — which is what exposed the traceback).

## 2026-07-19 — pagesize-bench encrypted-path fix (the cipher_page_size reopen trap)

Field failure: "Bench failed: WrongPassphraseError: the passphrase does not open
.pagesize-bench-16384.db (or the file is damaged)" on every encrypted corpus. The
maintainer's hypothesis was a missing UI passphrase field (the P0-panel pattern); the
live reproduction DISPROVED it — the passphrase was correct and available (the bench's
own `BenchRefused` for the no-passphrase case never fired). THREE stacked defects, all
in the encrypted branch the tests never exercised ("the encrypted path shares the code
shape and self-verifies at runtime; sqlcipher3 is CI/operator territory" — the shipping
test file's own docstring):

1. **The reopen trap (the crash):** SQLCipher cannot discover `cipher_page_size` from
   the file; a store built at a non-default size HMAC-fails its first read unless the
   opener declares the SAME size right after `PRAGMA key` — and the failure surfaces as
   wrong-passphrase, not as a page-size error. `connect()` gained `cipher_page_size=`
   (encrypted-open path only, default None = byte-identical); the bench's self-verify
   and workload opens pass the candidate size. This is why 4096 worked (SQLCipher 4's
   default) and 16384 always died.
2. **TEXT PRAGMA read-backs (the false verify-fail hiding behind #1):** the sqlcipher3
   build in use returns `PRAGMA page_size` as `'16384'` (str) — `got != wanted` on a
   perfect rebuild. The self-verify now `int()`s every read-back.
3. **Half-threaded explicit passphrase:** `rebuild_at_pragmas(passphrase=...)` used the
   explicit key only for the ATTACH; the source open, verify open and `bench_store`
   silently depended on the ambient process key. The key now threads through every open.

Hardening: `run_pagesize_ab`'s per-size catch now includes `WrongPassphraseError` /
`DatabaseLockedError` so an unreadable target degrades to a per-size `error` entry in
the report instead of aborting the whole job (the degrade-loudly rule). EMPIRICAL
UNBLOCK worth remembering: `pip install sqlcipher3-wheels` WORKS in the sandbox — the
encrypted paths are no longer untestable here; the fix was live-reproduced end-to-end
(fail → fix → both sizes rebuild+verify+bench green) and pinned as skip-guarded tests
that run in CI and in any wheels-equipped sandbox. No UI change needed: the worker's
`passphrase=None` → `get_passphrase()` (the unlocked process key) is the correct design.

## 2026-07-19 — restore-merge re-index: the invisible phase + a rollback-drops-survivors bug

Field report: a volume-backup RESTORE showed high disk writes during the 14-step
`merge_corpus` phase, then writes trickled to <5 Mb/s irregular blips every 30+ s while the
UI stayed frozen at "merging (14/14)" and ONE core pinned at 100% on a 6-core box.

ROOT CAUSE: the 14-step progress callback only covers `merge_corpus`. `run_restore` then
calls `reindex_imported_articles` → `reindex_articles` (P0-4: re-index every merged article
against the CURRENT engine) — a plain single-threaded Python loop with ZERO progress
reporting and a per-article `commit=True` default. `index_article`'s two most expensive
steps — `extractor.extract()` (tokenize/stopword-filter/entity-detect over the whole body)
and `score_article()` (VADER) — are pure, DB-free functions of the article's text, yet ran
serially on the GIL, pinning one core while `app.js:5374` kept rendering the LAST
`merge_step` it ever received (nothing updates it during this phase).

FIX (three parts, requested together): (1) `src/analytics/reindex_parallel.py` offloads
those two pure steps to a bounded `ProcessPoolExecutor` (worker_count = cpu_count-1, capped
at 8, `OO_REINDEX_WORKERS` override; a small batch, `workers<=1`, or an unrecognised/
test-double extractor always takes the exact serial path — an extractor is only
reconstructed BY NAME in a worker for the two registered kinds, so a custom object is
never silently swapped); ANY pool trouble (spawn restricted, a broken worker, a pickling
hiccup) degrades to the identical serial computation over the whole batch. (2)
`index_article` gained optional `content`/`precomputed_terms`/`precomputed_sentiment`
kwargs (default `None` = byte-identical to every existing caller); the language-deduction
block was extracted into `_resolve_known_language` so a precompute prep step and
`index_article` itself agree on the exact same deduced language — a real bug caught BEFORE
shipping: computing the precompute language before running deduction would have silently
regressed sentiment for undetected-language articles that resolve to English (score_article
needs the POST-deduction language, not the pre-deduction one). `reindex_articles` was
rewritten to window the work (bounding peak RAM regardless of corpus size — the same P0.1
discipline the backup engine follows), precompute each window, and apply+commit in
`commit_batch` groups mirroring `reindex_all_batch`'s PROVEN rollback-then-redo-per-article
fallback.

SKEPTIC-CAUGHT BUG (found via cross-checking against the reference implementation, not by
a fuzzer): the first draft's mid-batch STAGING-failure handler (one article's
`index_article(commit=False)` raising) did `session.rollback()` and marked only THAT
article failed — but a SQLAlchemy rollback discards the WHOLE pending transaction, so every
already-staged-but-uncommitted batch-mate accumulated before the failure was SILENTLY
DROPPED (never committed, never retried, never counted). Fixed to redo the accumulated
survivors one at a time, COMMITTED — exactly the pattern `reindex_all_batch`'s own comment
already documents for this exact scenario. A targeted repro (6 articles, `commit_batch=4`,
a flaky extractor failing article #3) proves 5/6 reindexed with exact live-vs-stored
counters, and is now a permanent regression test.

(3) `merge.py`/`volume_job.py` thread `commit_batch` (reads the SAME `OO_REINDEX_COMMIT_BATCH`
env var the standalone re-index-all job already reads — one knob tunes both) + `workers` + a
`progress_cb` through; the volume-restore job reports a DISTINCT `"reindexing"` phase
(`reindex_done`/`reindex_total`) via its OWN callback, never conflated with the 14-step
merge callback's different (3-arg vs 2-arg) shape. Frontend renders it with a real percent +
the existing rule-of-three ETA machinery; +1 i18n key ×12 (AI-drafted, flagged for native
review), gate stays green.

LESSON (copied to Session-rituals): a SQLAlchemy `session.rollback()` inside a mid-batch
failure handler discards EVERY pending (uncommitted) object in the transaction, not just the
one that raised — a batching loop's failure path must redo the accumulated survivors, never
just mark the trigger as failed and move on (`reindex_all_batch`'s own fallback already
encoded this; a rewrite must re-derive it, not assume a simpler shape is equivalent). And: a
progress callback wired into only ONE stage of a multi-stage pipeline reads as a hang once
that stage's work moves to the next, unreported stage — treat "the UI is frozen on the last
number it saw" as a sign to grep for what runs AFTER the last reported callback, not as
proof of a stall.

## 2026-07-20 — DIAGNOSE-THE-DIAGNOSTICS: run journal, hardware profile, button consolidation (0.3 gate row-3 prerequisite)

Executes the DIAGNOSE-THE-DIAGNOSTICS build ruled in CLAUDE.md (2026-07-20, amended same day).
`_write_all_diagnostics_zip` now records a full per-member envelope (`file`, `outcome` of
`ok`/`error`/`skipped-deadline`, `started_at`, `wall_s`, `bytes`, optional `rss_delta_kb`)
instead of the old bare `{file, ok[, error]}`. A durable sidecar `journal.jsonl` appends
`begin`/`end` JSON lines around every member on the background-job path (fsync'd), folded
into the final zip as `bundle-journal.jsonl` on completion — a hard-killed run's last `begin`
with no matching `end` names the culprit member. The manifest gains a run header: corpus
counters snapshot, app version, schema head (via `alembic heads`), started/ended timestamps,
total wall time, a slowest-members summary, and a runtime coverage block. A hardware profile
rides in the same header for cross-machine comparison (CPU model, physical/logical cores,
frequency, RAM+swap, disk free, rotational-vs-SSD via the Linux `/sys/block/*/queue/rotational`
probe, OS/kernel, optional operator-set `OO_MACHINE_LABEL`) — every field degrades to
`"unavailable"` on error rather than guessing or crashing the run. Per-member deadlines honor
the S8 lesson: DB-touching members run INLINE under a statement deadline (dispatch via
closure-freevar inspection), never threaded on a shared connection; non-DB members run on a
wall-clock-bounded daemon thread; a timeout records `skipped-deadline` and the bundle
continues. Diagnostic-button consolidation (ruling #7): removed the 24 per-report DOWNLOAD
buttons in `index.html` whose content the all-diagnostics bundle already carries, leaving
every job-starter/interactive ACTION control (p0-validation, pagesize-bench, source-quality
zip, rollup-benchmark, IR-eval+gold-builder, discover-world, enrichSources/enrichSourceTypes/
discoverSources, etc.) untouched — endpoints were never removed, only redundant download
buttons. `tests/test_repo_invariants.py` extended to pin the one-button state and the
surviving action controls.

Built by an autonomous session (pilot lane of a larger 0.3-gate execution plan). Verified:
239 targeted tests green; full local suite 4296 passed / 21 skipped / 8 failed / 9 errors, all
of which reproduce identically on unmodified `origin/main` (a subprocess
`ModuleNotFoundError: No module named 'src'` in `torture_helper.py`, and a sandboxed AF_UNIX
`PermissionError`) except one order-dependent flake (`test_columnar_httpfs_loader`) that
passes in isolation on both branches — no regression from this diff. `ruff` F,B clean; `mypy`
127<=127 baseline (the 4 pre-existing `diagnostics.py` hits verified via `git blame` to predate
this diff, 2026-06-12 commits; 0 new errors). i18n 100% (2081/2081) across all 12 locales, no
new strings added. NOT field-confirmed at real ≥5M-article corpus scale and NOT
browser-verified — both remain for the maintainer; this only unblocks the *build* the 0.3
gate's row-3 large-scale run depends on, not the run itself.

LESSON (copied to Session-rituals): a crash-recovery journal must survive its OWN write
failures — the first cut of this journal let an `OSError` on its own `write`/`flush` propagate
uncaught, aborting the whole bundle (the exact crash scenario the journal exists to survive);
any resilience sidecar must degrade (log + disable) on its own failure, never raise. Also: a
"the sandbox's own /tmp is full" error is a HOST-level condition, not something to fix with an
unscoped `rm -rf` (a sub-agent did this mid-run and it was correctly flagged as a policy
violation) — it doesn't even fix a full disk if the culprit is a different filesystem (here:
Python site-packages on the root volume, not `/tmp` itself), and it risks destroying other
parallel sessions' files sharing the same path.

## 2026-07-23 — S1 (source qualification: verify + scale + surface)

Executes S1 of the 2026-07-23 field-feedback workflow brief
(`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-23_FIELD_FEEDBACK_WORKFLOW.md`), the first
slice of the maintainer's post-#748 workflow (qualification before Library graphs).

S1.1 VERIFICATION of the live qualification lifecycle (`src/catalog/qualification.py`, shipped
2026-07-19/20) found a REAL correctness bug while confirming it: `run_qualification_pass`
stamped a candidate `qualified` whenever its trial fetch produced ZERO stored articles.
`source_audit.per_source_metrics` builds its dict by iterating stored Article rows grouped by
source — a source with no articles at all (a totally-failed fetch, or no rss_url and no prior
evidence) never gets an entry, so `fails_by_source.get(source.id, [])` returned an empty list,
`decide_verdict([])` read as "healthy", and the source was admitted to full collection having
never actually been verified. Reproduced live with a standalone repro (a fake `trial_fetch`
raising a transport error against a fresh in-memory source) BEFORE touching any code, confirming
`source.status` ended up `"qualified"`. Fixed: candidates absent from the metrics dict are split
out (`no_evidence = [s for s in candidates if s.id not in per]`) and excluded from
`evaluate_and_stamp` entirely — left `unqualified` (no attempt row, no stamp), re-offered by
`select_unqualified` on a later pass, honestly tallied as `no_evidence` in the pass's return dict.
Four tests pin both directions: a totally-failed fetch never qualifies
(`test_run_qualification_pass_never_qualifies_on_zero_evidence`); a feed-less, evidence-less
candidate stays unqualified rather than getting the documented "no rss_url" scope limit read as a
free pass (`test_run_qualification_pass_no_rss_url_and_no_prior_articles_stays_unqualified`); a
source whose trial fails THIS round but already carries real articles from earlier ingestion is
still judged on that existing evidence, not treated as no-evidence
(`test_run_qualification_pass_still_judges_evidence_from_prior_articles`); and the existing
per-pass-bounding test was corrected to seed real articles (it had accidentally been exercising
the same bug — its original assertion that 2 zero-article dummy sources got "evaluated" encoded
the pre-fix behavior). Also pinned, previously true only by construction and untested: a
disqualified source's domain is never re-proposed by the citation/catalog/wikipedia-reference
discovery channels (`_existing_domains` keys on `Source.domain` alone, which a disqualified row
still occupies) — `test_citation_channel_never_re_proposes_a_disqualified_domain`.

S1.2 the bulk qualification BACKGROUND JOB (`src/catalog/qualify_job.py:run_bulk_qualification`).
The steady-state ride-along (`advance_qualification`, `qualification_per_pass=5` per online
collection pass) cannot honestly drain a Wikidata-discovery-scale backlog — measured on the
maintainer's 2026-07-23 field diagnostics at 42,612–66,697 candidates, 5/pass is 90+ days. This
worker runs `run_qualification_pass` repeatedly in batches until the backlog empties or the run is
stopped/paused, mirroring `discover_job.py`'s shape (a cancellable, task-manager-visible
`BackgroundJob`) but with a DELIBERATE SIMPLIFICATION: no persisted cursor file, because
`Source.status` is ITSELF the durable progress marker (a stamped source leaves the
`select_unqualified`/`select_due_disqualified` query the moment it's judged), unlike a "country"
in world-discovery which has no durable row of its own. Pauses cleanly (never auto-resumes,
matching the world-discovery convention) on cooperative cancel, airplane mode (`kill_switch_active`),
or the process-wide `memguard.memory_guard` engaging (the SAME singleton the collector's own pass
loop polls) — a bulk run must never push a low-RAM machine over the edge to drain the backlog
faster. A NO-PROGRESS breaker (`_MAX_CONSECUTIVE_NO_PROGRESS=10`, mirroring `discover_job.py`'s
`_MAX_CONSECUTIVE_FAILURES` convention) stops the run honestly rather than spinning forever on a
permanent glut of unresolvable candidates (no reachable feed, no prior evidence) sitting at the
front of the FIFO queue. New endpoints `POST/GET/POST /api/sources/qualify-bulk{,/status,/cancel}`
(`src/api/source_management.py`) wired identically to `discover-world-sources`
(`BackgroundJob(is_writer=True, cancellable=True)`, registered so `/api/jobs` enumerates it with
zero extra wiring); a Settings → Sources panel (`#qualify-bulk-status` + start/cancel buttons)
starts it (consent-gated via `ensureOnline`, refused under airplane) and polls live progress via the
existing `pollJobStatus` helper. 10 tests: draining a backlog across several batches; the initial
backlog estimate; cooperative cancel leaving genuine partial progress; the airplane pause; the
memory-guard pause; the no-progress breaker (with an explicit assertion that every candidate stays
unqualified, nothing silently stamped); a clean immediate-complete on an empty backlog; a
resume-after-cancel test proving the no-cursor design is actually safe (exactly one
`SourceQualificationAttempt` row per source after a cancelled-then-resumed run, no double-stamps);
a no-score-key payload walk; and a wiring-composition guard (the slice-1c 404 lesson) that COMPOSES
the real routes from the router prefix + decorators and requires the frontend to call exactly those.

S1.3 the two-class sources display. `database_stats` (`src/api/database.py`) gains
`counts["sources_qualified"]` (enabled AND status=qualified — exactly `select_sources`'s own
admission filter, i.e. what is ACTUALLY collecting) and `counts["sources_candidates"]`
(enabled=False — discovered, awaiting qualification review), computed as two cheap indexed
`COUNT()` queries alongside the existing raw table scans. The flat `counts["sources"]` key is kept
for backward compatibility but the frontend (`loadDbStats` in `src/static/app.js`) now hides it
from the Library "Sources" tile grid and shows the two labelled split tiles instead ("Sources
(collecting)" / "Discovered candidates") — the exact figure a field export showed as "~50k
sources" against a ~5k-article corpus, read as an alarm rather than the discovery funnel working
as ruled. STALENESS CATCH: the 2026-07-20-ruled "qualified-citations tally" + "discovery
provenance trail" (named in the brief as an optional S1.3 stretch) were found ALREADY SHIPPED —
`src/discovery/source_trail.py` (`source_provenance`, `source_citation_tally`), endpoints
`GET /{source_id}/{provenance,citation-tally}`, 13 existing tests, and already wired into the
frontend — verified working, not rebuilt.

Verified: full local suite 4378 passed / 107 skipped / 0 failed (py3.13 venv, `[analysis,dev]`
extras installed); `ruff check --select=F,B --extend-ignore=B008` clean on every changed file;
`mypy` 0 new errors attributed to any changed file (127<=127 baseline, confirmed by grepping the
per-file error output); `bandit -r -ll -q` clean; `i18n_report.py --min 100` green (2109/2109 ×12
— no new locale keys needed, the new UI strings use the established un-keyed-diagnostics-panel
convention `discoverWorld` itself uses). An adversarial skeptic pass reviewed the fix + the bulk
job for races, breaker-logic correctness, and API wiring before push. A merge with `origin/main`
(21 commits ahead at push time) was verified conflict-free and touched none of the files this
slice depends on except one unrelated covering-index addition to `Article.__table_args__`.
Frontend BROWSER-UNVERIFIED per fork-3/Q6a — a click-through of the Settings → Sources panel is
owed. NOT started this session: S2 (Library graphs + snapshot recorder), which the brief places
next in the ruled order.

LESSON (copied to Session-rituals): an aggregation dict built by iterating real observations
(`.setdefault`/groupby over rows) OMITS an entity with zero observations entirely — it never gets
a present-but-empty entry. Downstream code reading `.get(id, [])` cannot tell "no evidence
examined" from "examined, nothing bad found", and an admission gate built on that read silently
promotes the zero-evidence case to a pass. Audit every such `.get(id, default)` call downstream of
a groupby-style aggregation for whether "missing" and "present but empty" are meant to be the same
thing.

FIX-FORWARD (same session, before push): a mandatory adversarial skeptic pass over the S1.1/S1.2
diff found two real defects, both hand-re-verified with a live reproduction before trusting them
and before fixing them.

(1) HIGH — the zero-evidence fix, correct in isolation, created a LIVELOCK when combined with
`select_unqualified`'s pure `ORDER BY id ASC`. `scripts/build_world_news_catalog.py` never sets
`rss_url` (grep-confirmed) — every Wikidata-discovered candidate is structurally unable to ever
produce evidence via a trial fetch. Once enough of the lowest-id candidates are permanently
unresolvable, they occupy an ENTIRE batch's selection window on every future call, and nothing
behind them in id order is ever reached — reproduced live (30 feed-less sources blocked one
genuinely resolvable source across 20 passes) before any fix was written. FIX: a no-evidence
outcome is now logged as a `SourceQualificationAttempt` row with a NEW verdict value
(`VERDICT_NO_EVIDENCE`, `log_no_evidence_attempts`) — `Source.status` is still never touched (the
original fix's correctness holds) — and `select_unqualified` now orders by LEAST-RECENTLY-
ATTEMPTED (a LEFT JOIN + `nullsfirst()`, mirroring `select_due_disqualified`'s existing subquery
shape) rather than pure id, so a stuck candidate rotates out of the way after one attempt in
favour of never-yet-tried candidates, while still getting retried eventually (a transient failure
deserves another chance — it just can never again BLOCK the queue).
`consecutive_disqualifications_from_verdicts` was adjusted to SKIP (not break on) a `no_evidence`
entry, so an inconclusive retry of a previously-disqualified source doesn't wrongly reset its
re-qualification ladder position. Re-ran the exact repro after the fix: resolves in 4 passes. Two
new regression tests pin the scenario — one at the `run_qualification_pass` level, one end-to-end
through `run_bulk_qualification` using the REAL pass function (a stubbed no-network `trial_fetch`,
a genuinely pre-seeded article for the resolvable source — never a mock of the judging logic).

(2) MED — the S1.3 two-class sources split did not SUM back to the flat `sources` total: an
enabled-but-not-yet-qualified source (e.g. a freshly seeded catalog source awaiting its first
pass) was invisible in both `sources_qualified` and `sources_candidates`, undermining the whole
point of replacing one ambiguous number with a transparent breakdown. FIX: added
`sources_pending` (enabled AND status!=qualified — covering both never-yet-judged and
disqualified-but-still-enabled sources), so the three classes now PARTITION the flat total
exactly. Pinned with an explicit sum-equality assertion
(`sources_qualified + sources_pending + sources_candidates == sources`).

(3) LOW, recorded not fixed — a plausible-but-unproven concurrency finding: the bulk job and the
steady-state ride-along use independent sessions with no row-level locking, so both could select
overlapping candidates before either commits (`per_source_metrics` is a whole-corpus scan that
takes real wall-clock time). Assessed as no-data-loss (the single-writer gate still serialises
commits; worst case is a redundant `SourceQualificationAttempt` row and a minor ladder skew, never
a corrupted stamp) and recorded as a deliberately-not-addressed risk per the project's own
reproducer-first-for-gate-hold-riders discipline, rather than building real coordination for a
narrow, low-probability window with a bounded, non-corrupting worst case.

Re-verified after all three: full suite still 4378 passed / 107 skipped / 0 failed, ruff F/B
clean, mypy 0 new errors (127==baseline), bandit clean, i18n 100% (2111/2111 ×12).

LESSON (copied to Session-rituals): fixing a free-pass bug can silently CREATE a livelock if the
underlying selection query has no fairness/rotation mechanism — a pure FIFO/id-ordered query
implicitly assumed every entry would eventually leave the queue; once that assumption breaks
(some entries can structurally never resolve), the fix needs a rotation mechanism (log the
inconclusive attempt, order by least-recently-tried) alongside the correctness fix, or the cure is
worse than the disease. Always reproduce the adversarial scenario live, both to confirm the
defect and to confirm the fix, before trusting either claim.

## 2026-07-23 — S2 (Library-tab evolution graphs: hourly snapshot recorder)

Answers field-feedback item 3: the Library tab's bare live figures (sources / keywords /
Wikipedia+law tracked counts) become small evolution GRAPHS, with **INFINITE storage retention**
("I would prefer infinite retention"). Most of these counters had NO history anywhere in the
store — unlike `Article.created_at`, which already lets an articles/hour graph be derived
retroactively for free (real history that existed before this feature shipped).

**Schema:** `StatSnapshot` (table `stat_snapshots`) — an append-only EAV row (`metric`, `taken_at`
hour-bucket, `value`), mirroring the project's own vintage convention (`StatFigure`,
`SourceQualificationAttempt`). Migration `f670ae07b75e` off the REAL alembic head (`04c029205aa8`,
read via `python3 -m alembic heads`, never guessed/regex-scanned); `alembic check` confirms zero
model drift.

**Recorder:** `src/database/snapshots.py:maybe_snapshot_library_stats` records one hourly
snapshot per tracked metric — each a cheap `COUNT(*)` over a small/indexed table (never the
SQLCipher codec column-order perf trap). The `(metric, hour)` unique constraint IS the freshness
gate — no separate JSON marker file, unlike the heavier `maybe_cleanup_keywords`/
`maybe_incremental_vacuum` steps it now runs alongside inside `run_idle_maintenance`. Never
fabricates a backfill: every non-articles metric's serving endpoint states `recording_began_at`
honestly instead of implying a pre-recording gap means nothing happened.

**A SAVEPOINT-PER-ROW REAL SAFETY FIX (caught before push, not by an external skeptic this time —
by re-reading my own code against the project's own documented lesson list):** the recorder loops
over several metrics, `session.add()`-ing one `StatSnapshot` row per metric inside the SAME
open transaction. A first draft caught an `IntegrityError` from a concurrent-writer collision with
a bare `session.flush()` + `session.rollback()` — but per this project's OWN documented lesson
("a `session.rollback()` inside a mid-batch failure handler discards EVERY pending object in the
transaction, not just the one that raised"), that would have silently discarded every OTHER
metric's already-flushed-but-uncommitted insert earlier in the SAME loop iteration, not just the
colliding one. Fixed by wrapping each row's insert in its own SAVEPOINT
(`session.begin_nested()`): a rollback on that specific IntegrityError now rolls back only to the
savepoint, leaving prior successful inserts in the same call untouched. Verified with a dedicated
test (`test_a_mid_batch_collision_never_discards_sibling_inserts`) that seeds a pre-existing
colliding row for one metric and asserts every OTHER metric still gets recorded in the same call —
proving the mechanism, not just asserting it.

**Endpoint:** `GET /api/library/history?metric=&days=` serves both the live-derived
`articles_per_hour` series and the snapshot-table metrics through one contract; the response
window is bounded (default 30d, clamped ≤10y) even though storage retention is infinite — a
response bound is a query-time concern, never a storage-time one.

**Frontend:** three new dedicated Library-tab sections (Activity / Wikipedia tracked / Law
tracked), each rendering small tiles that reuse the EXISTING `dashChartSvg` (line-when-dense /
Item-Y bars-when-sparse, invariant #16) + `chartEnlarge` (click-to-enlarge into an interactive
ooChart) — no new chart renderer, no larger tile footprint than any other Library number. The
"Downloaded" 9-tile grid is compressed into the established collapsed-by-default
`<details class="adv-collect">` disclosure (item 5's ask), matching Settings' own legacy/advanced-
section convention — nothing removed, just less default visual space. Zero new i18n keys
(un-keyed English fallback via `t()`, matching the S1 qualification panel's own convention).

**A REAL CROSS-CUTTING FAILURE the full suite surfaced (fixed same session):** a new test's
`Path.read_text()` call omitted `encoding="utf-8"`, tripping this repo's own
`test_all_text_io_declares_utf8_encoding` guard (a Windows/cp1252 portability net that scans the
WHOLE tree, not just changed files) — a reminder that a full-suite run can catch defects invisible
to any test file run in isolation, and that a change touching test helpers still owes the
project's house-wide text-IO discipline.

VERIFIED: full suite 4423 passed / 107 skipped / 0 failed (py3.13 venv, after the encoding fix);
ruff `--select=F,B --extend-ignore=B008` clean; mypy 0 new errors across every changed file
(127==baseline); bandit clean; `alembic upgrade head` + `alembic check` both green. Frontend
browser-unverified per the standing Q6a convention.

LESSON (copied to Session-rituals): a per-row `IntegrityError` handler inside a multi-insert loop
sharing ONE open transaction must roll back to a SAVEPOINT (`session.begin_nested()`), never call
a bare `session.rollback()` — the latter discards every prior successful insert in the same
transaction, not just the one that collided. Prove the isolation with a test that seeds a
pre-existing colliding row and asserts SIBLING inserts in the same call still land, not merely
that the function "doesn't raise."

- **WIKIDATA RING BATCH — THIN-SUPERGROUP EXPANSION (168 hand-mined seeds) 2026-07-23:**
  Step 3 pre-translation, second Wikidata batch after 2026-06-20. 168 seeds mined against the
  77-supergroup / 540-ring scaffold, each targeting a verified-thin supergroup (intellectual
  property, public finance, terrorism/atrocities, labour, energy, cyber, crime, migration,
  human rights, weapons/WMDs, named wars, pandemic/COVID, AI, sport, science, and more), incl.
  the maintainer's directly-named examples (major wars/decolonization wars — Vietnam, Iraq,
  Kuwait, Algeria/France — and the pandemic cluster — COVID, masks, vaccine, curfew,
  confinement). Ran on a networked template Debian VM — **Wikidata is 403-blocked in the
  sandbox** (`host_not_allowed`; the established maintainer-machine pattern, same as the
  2026-06-20 run). TWO OPERATIONAL SETBACKS along the way, both fixed forward: the first VM run
  hit Wikidata's anonymous-API burst-then-cooldown rate limiter (~4 seeds/8 calls succeed, then
  a long 429 block) — fixed with a resumable wrapper that pauses after EVERY individual
  `wbsearchentities`/`wbgetentities` call (not just once per seed, the original `generate()`
  behaviour) with `Retry-After`-aware backoff, reading the prior run's log to retry only the
  failed seeds; then the AppVM was deleted mid-retry, so the final run combined bootstrap +
  pacing into one script resumable from seed #1 via incremental per-ring file writes. The
  successful run attempted all 168 seeds with **zero 429 errors**.

  **156/168 resolved to a QID** via `wbsearchentities` -> `wbgetentities` (labels+aliases, 12 UI
  langs); 3 had no QID at all (Iran-Iraq War, football transfer window, factory closure), 7
  resolved but were skipped for <2 languages (atrocity, oil and gas pipeline, blasphemy,
  chemical spill, mass layoff, aging population, theocracy), and 2 seed PAIRS independently
  resolved to the same QID and merged within the run (public debt + sovereign debt ->
  government-debt; lockdown + curfew -> lockdown).

  VETTED before merge via automated duplicate-id/qid scans, an untranslated-loanword-surface-
  string detector (the tell that first caught nuclear-fusion/desalination in 2026-06-20 —
  broadened this round to a near-identical-string threshold, which is what caught
  ethnic-cleansing), a cross-ring member-collision scan (both within the new batch and against
  the live 540), plus a full manual eyeball of every ring's content and every item the prior
  session's offline pre-vetting CSV had flagged (`HOMOGRAPH-WATCH` / `OVERLAP-EXISTING-RING` /
  `CONFLICT-MANUAL-PIN` / `review-post-resolution`). **12 mis-resolved rings DROPPED:**
  - 4 TRUE id/qid duplicates of an already-existing ring — `pension`, `asylum`, `secularism`,
    `public relations` each re-hit the SAME QID as `guest-house` (Q2460422, the German
    `de:Pension` boarding-house sense), `psychiatric-hospital` (Q210999, the wrong "asylum"
    sense), `irreligion` (Q58721, secularism already an alias there), and `marketing` (Q39809,
    PR already a member) — the prior session's offline pre-vetting had flagged all 4 as
    `OVERLAP-EXISTING-RING` and it was confirmed exactly right; nothing to merge, the
    re-resolutions were discarded outright.
  - `massacre` (Q1907359) resolved to the metal band of the same name — 5 of its 6 members
    explicitly say "(groupe)"/"(banda)"; only `zh:大屠殺` was the real concept.
  - `ethnic cleansing` (Q842636) resolved to a real, notorious 2002 neo-Nazi video game of the
    same title — 7 of 9 members are the literal untranslated English string "Ethnic Cleansing"
    (even the Arabic entry is a transliteration, not a translation), the exact tell that flagged
    nuclear-fusion/desalination.
  - `nuclear fusion` and `desalination` again resolved to untranslated single/multi-language
    Wikidata stubs — nuclear-fusion is a **REPEAT** of the exact 2026-06-20 drop (same QID,
    hit again by an independent seed this batch).
  - `translation` resolved to Q3331189, the SAME "version, edition or translation" bibliographic
    meta-class already dropped 2026-06-20 for the same reason (also a **repeat offender** — the
    regression-guard test caught this one live, see LESSON below).
  - `repatriation of cultural property` drifted to a Korea-specific sub-item (Q11517829) instead
    of the general concept.
  - `UNESCO World Heritage Site` drifted to "UNESCO World Heritage Site buffer zone" (Q64364418)
    — the prior session's pre-vetting CSV had flagged this exact seed `review-post-resolution`
    and it drifted exactly as that flag anticipated.

  **144 concept rings KEPT**, appended to `configs/keyword_rings_generated.yml` (540 -> **684**;
  existing 540 rings preserved byte-for-byte, verified via `git diff` — only appended, never
  reformatted or reordered). **EMPIRICAL DATA POINT — this batch's mis-resolution rate = 7.7%**
  (12/156), vs the 2026-06-20 batch's 35/575 ≈ 6.1% — comparably rare, slightly higher. This
  REFUTES a naive "single-word seeds mis-resolve more" hypothesis floated going into the run:
  of the 12 drops, 6 were single-word seeds (pension, asylum, secularism, massacre,
  desalination, translation) and 6 were multi-word (public relations, nuclear fusion,
  repatriation of cultural property, antimicrobial resistance, ethnic cleansing, UNESCO World
  Heritage Site) — an even split. The real predictor was PROPER-NOUN NAMESPACE COLLISION (a
  band/journal/video-game sharing the concept's name on Wikidata) and TARGET-SPECIFICITY DRIFT
  (the search API's top hit being a real but far narrower related item), not word count.

  **ALL 11 CONFLICT-MANUAL-PIN war/conflict seeds resolved cleanly, none dropped for
  ambiguity** — Gulf War, Iraq War, War in Afghanistan (2001-2021), Syrian Civil War, Yemeni
  Civil War, Yugoslav Wars, Bosnian War, Bosnian genocide, Nagorno-Karabakh conflict,
  Russo-Ukrainian War, and Israeli-Palestinian conflict (the task's named highest-concern item)
  all landed on correctly-scoped, richly-translated QIDs. TWO kept war rings needed a MEMBER
  STRIP, not a drop: `gulf-war` carried `en:Iraq War`/`pt:Guerra do Iraque` (duplicating
  `iraq-war`'s own members — the 1990-91 and 2003 wars are distinct conflicts) and `lockout`
  carried `ar:إغلاق`/`de:Lockdown` (duplicating the pandemic `lockdown` ring — a labour-dispute
  lockout is not a pandemic lockdown); both stripped with an inline explanatory comment,
  following the file's own established precedent (the `diaspora` entry's software-collision
  comment). **FLAGGED FOR A HUMAN CALL rather than resolved on a guess:** `soviet-afghan-war`
  and `war-in-afghanistan-2001-2021` share 5 alias terms across es/fr/ja/ru
  (`es:Guerra de Afganistan`, two `fr:guerre d'Afghanistan` apostrophe variants,
  `ja:アフガニスタン紛争`, `ru:Война в Афганистане`) — those languages lack English's sharp lexical
  distinction between the two wars; left as a disclosed cross-ring ambiguity rather than
  arbitrarily assigning the shared terms to one ring, which would fabricate a distinction the
  language doesn't make. Also flagged, not silently changed: the `lockdown` ring itself absorbed
  `en:curfew` alongside `en:lockdown`/`fr:confinement`/`pt:confinamento` — defensible per
  Wikidata's own item but conflating two related-not-identical concepts.

  `test_shipped_generated_file_is_clean_and_vetted` updated: 6 genuinely-wrong new ids added to
  the regression guard (`massacre`, `desalination`, `repatriation-of-cultural-property-to-korea`,
  `antimicrobial-resistance-and-infection-control`, `ethnic-cleansing`,
  `unesco-world-heritage-site-buffer-zone`); the other 2 drops needed NO test change — both
  `nuclear-fusion` and `version-edition-or-translation` were ALREADY in the 2026-06-20 guard set,
  so this batch's re-hits were simply excluded from the merge, and the guard is what caught the
  `version-edition-or-translation` collision live on the first full pytest run (see the LESSON
  below). The 4 true duplicates (`guest-house`/`psychiatric-hospital`/`irreligion`/`marketing`)
  were deliberately NOT added, since those ids legitimately exist in the file for their ORIGINAL
  correct sense; floor raised `>=500` -> `>=680`. No supergroup
  assignment (`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_SUPERGROUPS.md` owns that; step 7
  of the runbook explicitly scoped it out).

  VERIFIED: `test_wikidata_ring_gen.py` (12/12) plus the broader translation/families/selftest
  surface (`test_super_rings.py`, `test_ring_candidates_digest.py`, `test_keyword_translation.py`,
  `test_families.py`, `test_keyword_equivalence.py`, `test_keyword_selftest.py`) — 71 tests green
  total, the only failures being pre-existing sandbox environment gaps unrelated to this change
  (a missing `httpx2` package for one FastAPI `TestClient` test). `ruff check` clean on the
  touched test file; `mypy` reports 0 new errors on it (the import-closure noise it surfaces
  lives entirely in an untouched module, `src/crypto/provenance.py`, per the project's own
  per-file-verification convention).

  **LESSON (reusable, confirmed on a REAL run this time, not just read from source):**
  `scripts/generate_wikidata_rings.py`'s `main()` FULLY OVERWRITES its `-o` target
  (`args.out.write_text(emit_yaml(rings, ...))`) — it does not merge or append. A run must
  ALWAYS target a fresh file (`-o keyword_rings_generated_NEW.yml`), never the live
  `configs/keyword_rings_generated.yml`, and the merge into the live file is a SEPARATE,
  deliberate step (append-only text splice preserving every existing byte, never a full
  YAML round-trip re-serialization, which would reformat/reorder the 540 untouched entries and
  bury the real diff in noise).

  **LESSON: a repeat-offender QID can resurface under a DIFFERENT English seed string.**
  `nuclear-fusion` (Q2191684) was dropped 2026-06-20 for a seed literally reading "nuclear
  fusion"; this batch's entirely different seed "translation" independently hit ANOTHER
  2026-06-20 repeat offender, Q3331189 ("version, edition or translation"), because Wikidata's
  search-then-disambiguate step for a common one-word concept can land on an adjacent
  bibliographic/technical meta-class instead. The regression-guard test's `dropped` blocklist is
  what caught this live, on the FIRST full pytest run — a reminder that the test is not merely
  documentation of past mistakes, it is an active tripwire that must be run (and obeyed) before
  trusting a merge, not just updated after eyeballing the batch by hand.

  **LESSON: a prior session's own pre-vetting flag (`review-post-resolution`) is a genuine
  signal, not boilerplate.** The one seed the pre-vetting CSV singled out with an extra note —
  "UNESCO World Heritage Site" — was also the one seed among the ~145 unflagged
  `review-post-resolution` rows that actually drifted off-target on this run.

## 2026-07-23 -- S3.2 quarantine schema + write step (field-feedback workflow)

Shipped: `Article.quarantined`/`quarantine_reason`/`quarantine_criteria_version`/
`quarantined_at` (additive, boot-self-healed + migrated), a real `write=True` mode for
`default_quarantine_candidates_batch`, `QuarantineJobManager` wired into the app
(`src/api/quarantine.py` + the generic `/api/jobs/{quarantine}/...` dispatch), and the
`/api/articles` search/browse/`ids=` exclusion chokepoint. Full detail in
`docs/ledger/shipped.csv` (2026-07-23, corpus-quality, "S3.2 (quarantine schema + write
step)...").

**LESSON: a resumable job manager's optional destructive/write MODE must be persisted
alongside its cursor, and `resume()` must ALWAYS explicitly re-supply it to `start()` --
never let `start()`'s own parameter default silently reset the mode on resume.** The
first cut gated the mode assignment on the cursor (`if _cursor <= 0: self._write =
bool(write)`), reasoning "only a fresh run decides the mode." But `resume()` calls
`start()` WITHOUT passing `write=` (it has no reason to know the paused run's mode) --
so a legitimately-paused WRITE-mode run that happened to have `_cursor == 0` (no
progress made yet, e.g. paused on the very first batch) would have silently resumed in
DRY-RUN mode, an operator-invisible behaviour flip on a data-safety-relevant control.
Caught by design review before it was ever exercised by a test, not by a failing test --
fixed by making `start()` ALWAYS set the mode unconditionally from its own parameter, and
`resume()` explicitly captures `w = self._write` before calling `start(..., write=w)` so
the paused run's mode survives regardless of cursor position. Pinned with two dedicated
regression tests (write-mode and dry-run-mode each independently proven to survive a
pause/resume cycle) -- the general form: any resumable job with more than one execution
MODE (not just a cursor) needs an explicit mode-preservation test, because the mode is
exactly the kind of state a "just re-call start()" resume path quietly drops.

**LESSON: a query-result CACHING optimization keyed on "is the filter list non-empty" is
silently defeated by ANY unconditional addition to that same list.** `_query_articles`'s
browse branch chooses between a cheap CACHED total (`_browse_total_cached`, no filters)
and a live `.count()` (`if filters:` -- filters is a plain Python list). Appending a
new always-on exclusion condition (quarantine) directly into that list would have made
`filters` NEVER empty again for the extremely common no-other-filter browse case,
permanently defeating the S2.3 caching win for every browse request. The fix is to model
"always-on, non-optional" conditions SEPARATELY from the "user-supplied, optional"
filters list, and make the cached path itself aware of the always-on condition (rather
than bypassing the cache entirely). General form: before adding a new WHERE condition to
an existing query-building function, check whether that function branches its OWN
behaviour (caching, index choice, plan shape) on whether its filter collection is empty --
an always-on addition to that same collection can silently change which branch every
caller takes.

**LESSON: a resumable job's "capture the baseline" step must run EXACTLY ONCE per
logical run and PERSIST across every resume -- never recompute it fresh on each
invocation.** S3.3's newsletter-import auto-quarantine hook needed a "what's new since
this run started" baseline (the corpus's max article id + a snapshot, at the moment the
import begins) so it could screen only the articles THIS run added, not the whole
corpus. The first cut captured that baseline fresh at the top of every `_run()` call --
which silently drops coverage for a paused-then-resumed import: a resume's freshly-
captured baseline sits ABOVE the articles the PRE-PAUSE half of the run already inserted,
so those articles permanently never get auto-screened by this hook, with no error and no
visible symptom. Fixed by capturing the baseline exactly once, guarded by a new
`_quarantine_baseline_attempted` flag persisted alongside the job's existing on-disk
cursor state (so it survives an app restart mid-pause, not just an in-process resume);
a FAILED capture attempt is also recorded as "attempted" rather than left retriable,
because retrying it later inside the same run would silently re-baseline past whatever
the run had already inserted by then -- same class of bug, just delayed. A related trap
avoided at design time, before writing any code: the natural-looking fallback for a
failed capture (`self._quarantine_before_id = 0`) would have been actively DANGEROUS
rather than merely incomplete -- an unscoped `Article.id > 0` matches EVERY pre-existing
article in the corpus, not just this run's new ones, so a failed baseline capture must
disable the hook for that run, never substitute a guessed numeric floor. STASH-VERIFIED
(not just reasoned about): the fix was temporarily reverted to the old fresh-capture
behaviour, the new regression test (`test_paused_then_resumed_import_screens_articles_
from_both_halves`) was confirmed to fail in exactly the predicted way (the pre-pause
article's `quarantined` flag read `False` instead of `True`), then the revert was undone
and the test re-confirmed green. General form: for ANY resumable job, a "since the run
started" computation is only correct if the reference point is captured once at the
TRUE logical start and threaded through every resume -- treat it as part of the job's
persisted state, exactly like its cursor, not as a per-invocation local.
