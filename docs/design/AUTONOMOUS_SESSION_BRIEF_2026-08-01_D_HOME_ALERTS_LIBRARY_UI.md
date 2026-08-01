# Autonomous session brief — 2026-08-01 Session D: Home-alerts relevance · Home Overview · Library subtabs · the axis-honesty pass

**Status:** PENDING execution (an autonomous Opus 5 CLI session).
**Answers of record:** the "FIELD IMPRESSIONS 2026-08-01" entry in CLAUDE.md (all 17 maintainer
answers, rulings 1–11 + 17 govern this session).
**Base:** cut from a freshly-fetched `origin/main`; draft PR(s) onto `main`; nothing auto-merges —
the maintainer's review is the gate.
**Verification channel:** the maintainer will save FULL-DOM HTML exports of the reworked pages
(preferred over PDF — tick values, classes and ARIA are inspectable; ruling 11). Every frontend
slice still ships conservative + flagged per fork-3/Q6a ("browser-unverified, needs
click-through") until those exports or a click-through confirm it.

## §0 Working mode

- **Staleness guard FIRST**: every anchor below was verified against `main`@d725f5b on
  2026-08-01 by a 5-agent read-only fan-out with hand re-verification — but `main` moves fast;
  re-verify each anchor before editing, and treat a "found already built" as a verify-and-mark,
  never a rebuild.
- Skeptics-before-push on the honesty-critical slices (§2's grouping + floor; §1's tick logic),
  with the mandatory negative-space lens (inputs that must NOT group / must NOT gain a tick).
- CI gates (verbatim): `ruff check --select=F,B --extend-ignore=B008 src tests` ·
  `python3 -m mypy` ratchet ≤ 127 · full `pytest -q` · `python scripts/i18n_report.py --min 100`
  · `node --check` on every touched `<script>`/JS file · `bandit==1.9.4 -r src -ll -q`.
- New chrome strings keyed ×12 (or `OOI18N.tf` templates for value-bearing strings); numbers via
  the shared formatter. Grep the TEST tree for any panel id / literal anchor you move (the
  stale-anchor lesson) BEFORE moving it.

## §1 (S1) The axis-honesty pass — chart-toolkit-wide, do FIRST

Everything else in this session renders through the toolkit, so this slice lands first.

**Anchors (verified):** `dashChartSvg` app.js:9727–9811 — `span = (maxY-minY) || 1` at :9735;
gridlines exactly `[minY, minY+span/2, maxY]` at :9757–9761 (a constant-23 series draws
23 / "23.50" / 23 with the min+max labels OVERLAPPING at the plot bottom); X labels hard
month-granularity `observed_on.slice(0,7)` with INDEX-only dedup at :9770–9772 (two same-month
hourly snapshots both print "2026-07"); `n=${n}` unitless at :9794–9795; bars anchor to
`baseY = Y(minY)` at :9778 (window-min, not zero); series colour `up ? var(--ok) : var(--err)`
at :9754–9755. `ooChart` — `ySpan = (yMax-yMin) || 1` at app.js:10354 with 4 gridlines
`yMin + ySpan*g/3` at :10357–10361 (constant-23 → 23/23.33/23.67/24, a +1 top tick no data
reaches); FIXED-px canvas `W = Math.max(320, Math.min(el.clientWidth || 680, opts.maxWidth || 900))`
at :10268–10274 with no overflow clipping anywhere in the library tile/row/panel chain (the
confirmed graphs-overflow-their-box vector). Library tiles: `_libGraphTile` app.js:7938–7965
(passes `unit=""`, no opts); `_libRenderQualChart` :8031–8037 (ooChart).

**Requirements (each app-wide, both renderers unless stated):**

1. **Integer tick snapping.** When every plotted value is an integer (count series), gridline
   values MUST be integers — never a fractional tick on a count axis. Implementation freedom
   (snap the generated values, or generate nice integer steps), but the property is the test.
2. **Flat series honesty.** No fabricated span: a flat series renders its value with ONE
   labelled gridline at that value and the range legend stating it plainly — never a
   23.5/"23.50"/24 tick no data reaches, never overlapping min/max labels. (Keep the visual
   plot height; only the tick fabrication goes.)
3. **Adaptive X granularity + TEXT dedup.** Label granularity derived from the actual plotted
   span: ≤ ~48 h → `MM-DD HH:00`; ≤ ~90 d → `YYYY-MM-DD`; else `YYYY-MM`. If two rendered
   labels would be identical TEXT, refine or drop — dedup by text, not index. Applies to
   dashChartSvg's own path AND its shared-window path, and to ooChart's `fmtT`.
4. **`n=` carries its unit.** `n=2` becomes "n=2 snapshots" (library tiles) / the caller-passed
   unit elsewhere, via an `OOI18N.tf` template (`"n={n} {unit}"`-class key ×12). This resolves
   the maintainer's "23 documents or 2?" ambiguity permanently.
5. **Zero-base counts.** `dashChartSvg` gains `opts.zeroBase`; library COUNT tiles pass it
   (Item Y: count series → true zero baseline; price-LEVEL callers unchanged at window-min).
6. **Responsive canvas.** Remove ooChart's 320 px hard floor and the 680 px hidden-element
   fallback: size to the real container (clamp to `clientWidth`; when `clientWidth` is 0 —
   hidden tab — defer/re-render on visibility instead of guessing 680). Add a defensive
   `overflow:hidden` on the tile as the belt to the suspenders.
7. **Neutral series colour.** dashChartSvg paints every series green-if-up / red-if-down —
   market semantics fabricated onto NEUTRAL metrics (fewer keywords is not "bad"). Add
   `opts.neutral` (accent colour); library tiles pass it; market/commodity callers unchanged.
8. **Axis units.** Library tiles currently pass `unit=""` — pass the real unit ("sources",
   "documents", "articles/h"), translated.
9. **Sparse-rule reach check** (composes with GUI-audit V-3, does not duplicate it): verify
   whether `ringDumbbellSvg` / `commodityOverlaySvg` need `_SPARSE_BAR_MAX` and DOCUMENT the
   decision either way (the dumbbell plots discrete pairs — likely a reasoned exemption).

**Tests:** node-run tick-generation unit checks (the `ooviz_node_test.js` pattern) pinning:
integer series → integer ticks; flat series → no fabricated tick; identical-text X labels never
rendered; `n=` carries a unit; zeroBase only where passed. Extend `test_ui_invariants` #16
(source-level: `zeroBase`/`neutral` opts exist; the fixed `320` floor is GONE from ooChart's
sizing expression).

## §2 (S2) Alerts selection layer (rulings 1–4)

**Anchors (verified):** `_hazard_tier` src/analytics/alerts.py:59–68 (GDACS green/orange/red
only; USGS magnitude NEVER promoted — this honesty rule is UNTOUCHABLE, see the fence);
per-hazard dict :129–165 (magnitude/lat/lon/severity/source/time/url/article_id all present);
`_renderHomeAlerts` app.js:2551–2590 (uncapped, snapshot order); `_hazardStripItem` :2535–2550;
USGS `_quake_band` src/hazards/parse.py:24–33 (major ≥7 / strong ≥6 / moderate ≥4.5 — parsed,
currently drives nothing); GDACS carries NO magnitude (parse.py:132); `severity_alerts` producer
producers.py:2981; `openWorldMapAt` app.js:15058–15083; map hazard layer =
`/api/timemap?hazards=true` from the LOCAL snapshot (src/api/timemap.py:44–131).

1. **Within-tier ordering by provider facts** (backend, in `compute_alerts`): GDACS level rank
   first, then USGS magnitude descending, then recency. An ordering over disclosed provider
   measurements — never a composite; state the ordering basis in the payload `method`.
2. **Display floor (ruled 1):** "major" = GDACS orange|red OR USGS band strong|major (M≥6,
   reusing `_quake_band`). The Home strip shows ONLY major events (cap ~5, ordered), plus ONE
   overflow line — "N more events on the map →" — that opens the World map with the hazard
   layer active. The floor is DISPLAY-only: every event stays in the payload, on the map, and
   behind the per-tier "Open corpus". Bands are labelled AS bands ("M≥6"), never as urgency;
   `_hazard_tier` and the tier vocabulary are byte-untouched.
3. **Tunable (ruled 1):** the magnitude-band floor + the strip cap join the Settings→Cards
   grammar (`ProducerSpec`/`Tunable`, catalog.py pattern) with stated safe ranges — never a
   silent clamp (settings ruling 3).
4. **Per-major-event cards (ruled 2 — keep BOTH surfaces):** each above-floor event renders as
   a card-styled entry (type glyph + TYPE IN WORDS, magnitude/level, place, relative time,
   provider(s), 🗺 map + 📄 local article + source↗ links). The `severity_alerts` producer card
   STAYS unchanged — the maintainer wants both surfaces.
5. **Cross-provider same-event grouping (ruled 3):** same hazard type + Δ < 0.5° + Δt < 2 h →
   ONE displayed entry listing both providers ("via USGS + GDACS"), visibly labelled a DEDUCED
   grouping (caveat per invariant #23/#17). Display-layer only — snapshot records and Article
   rows stay 1:1 per provider event id. NO aftershock clustering (explicitly out of scope).
   Negative-space tests: different types / far apart / > 2 h apart must NOT group.
6. **Map (ruled 4):** (a) a "Major only" filter toggle, ON BY DEFAULT — one click back to the
   full set; state visibly that it is a default lens, never an exclusion (full recall is one
   click away); (b) a hazard-TYPE filter (earthquake/cyclone/flood/…); (c) **the labelling
   fix:** everywhere a hazard renders — the map signal detail (`_ooMapSignalDetail`), the Home
   strip, the ingested article view — the hazard TYPE is stated IN WORDS ("Earthquake ·
   M6.8"), translated ×12. The maintainer's exact report: clicking an earthquake on the map
   gives a description that never says it is an earthquake; a glyph alone is not deducible by
   a new user.

**Tests:** tier mapping byte-unchanged (pin `_hazard_tier`); ordering; floor honesty
(below-floor events still present in payload + map); grouping positive + negative space; the
type-label renders in the detail panel (source-level guard); i18n 100 %.

## §3 (S3) Home "Overview" default lens (rulings 5–8)

**Anchors (verified):** `renderBriefing` app.js:2679–2729 (family subtabs injected into
`#briefing-feed`; default lens `__all` renders EVERY card of EVERY bucket — the long scroll);
carousel = top-8 of the FLATTENED list app.js:2728, :2743; live order = bucket priority →
`leads.order_key` (distinct sources → magnitude tier → recency), service.py:161–189;
`explain_order` + `GET /api/insights/leads-view` (insights.py:781–809) have ZERO frontend
callers — the Settings restructure deleted the Leads preview subtab, so the
ordering-transparency surface is currently GONE. Home blocks in order: glance strip
(index.html:201) · alerts (:218) · carousel (:229) · trends (:241) · recent (:252) · latest
(:267) · by-channel (:288) · briefing (:294).

1. **"Overview" becomes the DEFAULT subtab** (ruled 5, 6): the TOP-1 card of each family, taken
   from the live feed's existing disclosed order (the feed is already sorted server-side —
   overview = first card of each bucket; ONE ordering system, no second selector). Each
   Overview card carries a visible "why this card" — the shipped `explain_order` text (a
   one-line basis + the full text on the #oo-tip hover, invariant #17). This RESTORES the
   transparency surface; wire it from the card payload or `leads-view` (session's choice —
   prefer riding the briefing payload to avoid a second fetch).
2. **Families unchanged; "All Leads" KEPT** as the second subtab (the full feed — nothing
   lost).
3. **Ruling 7 = option (a):** a COMPACT Trending row folds INTO Overview (reuse the
   `loadHomeTrends` rendering, smaller); the Most-recent · Latest-in-your-corpus · By-channel
   panels MOVE from stacked sections into subtabs beside the families (their full controls
   move wholesale — the Desk lesson; absorption-gated). The glance strip and the alerts strip
   stay PINNED above the subtab nav (invariant #19; alerts are severity-gated and small after
   §2).
4. **Ruling 8:** the carousel panel is RETIRED INTO Overview — absorption-gated: the "top
   cards" capability = the Overview cards themselves; remove `#home-carousel-panel` +
   `renderLeadsCarousel` only after Overview renders equivalent content; sweep the test tree
   for carousel anchors first.
5. **Tests:** invariant #19/#19b updated (Overview default · one-per-family · explain visible
   · All Leads retained · pinned strip unchanged); stale-anchor sweep for every moved panel id.

## §4 (S4) Library subtabs (ruling 9)

**Anchor:** `#tab-library` index.html:455–519 — 7 flat sections (Library · Activity ·
Wikipedia tracked · Law tracked · Database · Storage footprint · World coverage), no subtabs.

Restructure to 5 ooSubtabs (invariant #18 grammar): **Overview · Activity · Tracked
(Wikipedia + Law) · Database & storage · World coverage.** Loaders fire on subtab SELECT, not
tab open (the Advanced-tab "folded must not mean fetched" precedent — World coverage +
storage-footprint walks are the heavy ones). Before moving ANY panel, grep the test tree for
`tab-library` / section-heading / host-id anchors (the settings-restructure stale-anchor
lesson: panel ids get used as source-slicing delimiters in tests that are not about them).

## §5 (S5) Dataviz diversification — first activations (ruling 10)

The maintainer wants the app's visualization vocabulary diversified. This slice COMPOSES with
the 2026-07-28 GUI-audit brief (its V-1 "8 built+tested ooviz primitives with zero call sites",
V-2 "35 table-only render functions", V-4 ooDonut guard) — never duplicates it. Pick 2–3 of
the following, chart-BESIDE-table (invariant #8 / Desk lesson — a chart never replaces the
table), counts only, n + method visible, sparse rules apply:

- **Ingest calendar heatmap** (Library → Activity): `bin2D` over hour×weekday or day×week of
  `created_at` — collection rhythm at a glance; honest empty cells.
- **Qualification-attempt / article-length histograms** (`binCounts1D`) in Library → Database
  or the source-audit surfaces.
- **Corpus-delta slope chart** (`slopeChartSvg`, already shipped as a renderer) for the
  post-import before→after view (`_uxCorpusDeltaView` is a named V-2 candidate).
- **Per-language small multiples** (`smallMultiplesSvg`) for ingest trend by language.
- **Waffle/unit chart** for source-type composition (1 square = N sources, stated) — the
  honest alternative where a many-slice donut is banned by the project's own framework.

Framework discipline: the committed `docs/research/dataviz` decision framework governs (its
REJECT list stands: no radar/streamgraph/3D/dual-axis-for-same-unit/wordcloud).

## §6 (S6) Docs + ledger

- Fix the STALE "Status: PENDING execution" banner on
  `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-24_A_FIELD_FIXES.md` (all A-slices shipped —
  shipped.csv rows L437–L443).
- Add the missing ROADMAP row for the 2026-07-23/24 Library-graphs work.
- shipped.csv row per slice; ledger append per protocol; grep CLAUDE.md for conflict markers
  after any merge.

## §7 Scope fence

- `_hazard_tier`'s no-promotion rule is UNTOUCHABLE (magnitude is never urgency).
- No hazard-fetch/backend cadence changes; no new providers; no aftershock clustering.
- The 2026-07-28 GUI-audit fix session's own slices (i18n key sweep, `--warn` contrast,
  top-bar responsive fix) stay THAT session's work — do not absorb them here.
- The Observatory stays browser-gated and out of scope.
- Every frontend slice: `node --check` + invariant guards + defensive empty states + the
  "browser-unverified" flag until the maintainer's HTML exports confirm it.
