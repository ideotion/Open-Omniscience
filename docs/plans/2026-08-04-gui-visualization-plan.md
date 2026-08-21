# GUI visualization plan — reconnaissance & action plan

> ## ✅ EXECUTION STATUS (2026-08-04, the same day)
>
> **Shipped:** foundations **F1** (chart series channels + the `ooChart` colour-only fix),
> **F2** (the one method/caveat/n panel), **F3** (the empty-vs-zero component), and
> candidates **C1** (quarantine composition), **C2** (tone measurability by language),
> **C4** (article-length distribution) and **C5** (Lorenz + Gini) — the last four as a new
> **Library → Composition** subtab. Detail: five `docs/ledger/shipped.csv` rows dated
> 2026-08-04 plus the `SHIPPED_LOG.md` entry; reusable lessons are in `CLAUDE.md`.
>
> **Three of this plan's own claims turned out to be wrong, and are corrected below at the
> point they appear:**
>
> 1. **§12 understated the environment.** `/usr/bin/python3.13` exists (only the *default*
>    `python3` is 3.11) and Chromium ships at `/opt/pw-browsers/chromium-1194/`. The full
>    suite runs here and a real browser can drive the app — so every frontend slice in this
>    plan was **browser-verified**, not conservative-and-flagged. That also means the standing
>    "browser-unverified per fork-3/Q6a" caveat should be re-checked before it is repeated.
> 2. **§2.8 item 6 / §10 Unit 6 said `ooChart`'s inline legend `onclick` was redundant**
>    because "the same block attaches a proper listener four lines later". It does not:
>    `elm._oo = …` only ASSIGNS a property, which the inline attribute was what invoked.
>    Removing the attribute alone leaves the toggle dead. A real `addEventListener` was added.
> 3. **§7 C4 said the word-count figure would be the first `ooViz.binCounts1D` activation.**
>    It is not, and should not be: `binCounts1D` makes equal-width bins from raw values, and
>    the values are already binned server-side into deliberately *unequal* buckets. Forcing it
>    would mean shipping every raw word count to the browser to re-bin it worse. The twelve
>    unwired primitives are down to eleven — `ooViz.linearScale` gained a caller (the Lorenz
>    curve), and `binCounts1D`/`bin2D`/`fiveNumberSummary`/`sqrtAreaScale`/`symbolRadii`/
>    `pathWithGaps` are still waiting for a surface that genuinely needs them.
>
> **Not built:** C3, C6 (**already shipped upstream** on 2026-08-04 as the Library
> per-language small multiples — check before starting it), C7–C17, F4 (selection emission),
> F5 (shared hover/zoom), F6/F7 (the rendering ruling and the figure export envelope).
> §11's open questions Q1/Q3/Q4/Q6 were answered in the build and are annotated there.

> ## ⚠ FLAG 1 — I am not on branch `0.2`, and `0.2` does not exist
>
> The prompt instructed me to confirm branch `0.2` and to report as the first line of this
> plan if I was not on it. I am not, and the premise is stale rather than the repository
> being wrong:
>
> - Checked out: `claude/repo-reconnaissance-plan-4qfhia`, whose HEAD is **byte-identical to
>   `origin/main`** (`1f18958d6965e597012188098aeb19add386b208`), verified with
>   `git rev-parse HEAD` and `git ls-remote --heads origin`.
> - `git ls-remote --heads origin` returns exactly three heads: `main`,
>   `claude/remarks-diagnostics-analysis-xpadfq`, `vibe/comprehensive-audit-2026-07-22-9b6174`.
>   **There is no `0.2`, no `0.04`, and no `quarantine-archive` branch on the remote.**
> - `CLAUDE.md` records why: the maintainer renamed the default branch `0.2 → main`
>   permanently on 2026-07-15, and the branch name and version number are now independent.
>   `pyproject.toml:15` reads `version = "0.3.0"`.
> - Working tree is clean (`git status`: "nothing to commit, working tree clean").
>
> So the two stale-state hazards the prompt warned about cannot occur here: the branches it
> told me not to trust are gone, and the branch I am on is the current default's exact tip.
> The state is unambiguous, so I continued rather than stopping with nothing delivered.
> **A later session should read "0.2" in any instruction as meaning `main`.**

> ## ⚠ FLAG 2 — two Phase-3 premises are stale; the findings are closed, not open
>
> The prompt asked me to "locate the open findings for CSRF and for absence of a
> content-security policy". Both are **closed in code**, and `docs/SECURITY.md` is a
> point-in-time audit report that was never annotated with remediation status. Details and
> citations in §4. This changes the constraint from "adding a CSP later" to "not making the
> *existing* CSP's `'unsafe-inline'` harder to remove".

**Session metadata**

| | |
|---|---|
| Date | 2026-08-04 |
| Branch | `claude/repo-reconnaissance-plan-4qfhia` (= `origin/main`) |
| HEAD | `1f18958d6965e597012188098aeb19add386b208` |
| Pass type | **Read-only reconnaissance.** No source file was modified, created, moved or deleted. No git write command, no package install, no network fetch. The only file written is this plan. |
| Commands run | `git status`, `git branch -a`, `git log`, `git rev-parse`, `git merge-base`, `git ls-remote`; `grep`/`sed`/`awk`/`ls`/`wc` reads; `python3 scripts/i18n_report.py` (read-only reporter) |

---

## 1. Design invariants

All four invariants the prompt named were located. Three are enforced mechanically in code,
not only in prose — which is unusual and is the single most important thing a later session
must not weaken.

| Invariant | Where it lives | Enforcement |
|---|---|---|
| **No composite trust score** | `src/briefing/card.py:59-130`, applied at `src/briefing/card.py:301` and `src/analytics/envelope.py:120` | **In code, at import time and at runtime.** `assert_no_score_fields` (`card.py:81-99`) rejects any dataclass *field* whose name contains `credibility`/`quality_score`/`veracity`/`reliability_score`/`bias_score`/`verdict`, or is exactly `score`/`rating`/`rank`/`trust`. `assert_no_score_keys` (`card.py:102-129`) walks nested payload **keys** recursively, because `signal` is free-form and the field check alone let `signal={"trust_score": 0.87}` through (`card.py:106-115`). Raises `CardSchemaError`. |
| **Every displayed figure carries method, caveat, n** | `src/briefing/card.py:168-197`; `src/analytics/envelope.py:58-114` | **Structurally.** `Card.method` and `Card.caveat` are non-defaulted required fields (`card.py:172-173`); `n` is `int \| None` (`card.py:191`). `Envelope` requires `method` and a **real** `as_of` and raises on either being empty (`envelope.py:84-91`) — "an honesty envelope with an invented freshness time would be the very dishonesty it exists to prevent" (`envelope.py:25-31`). |
| **Effective state is always shown honestly** | `src/analytics/envelope.py:16-23, 42-46`; `src/database/snapshots.py:114-134` | Partly in code. `Envelope.basis` is a two-value disclosure (`exact` / `estimated`) of whether a maintained aggregate was verified or may have drifted, explicitly "a disclosure, not a score" (`envelope.py:16-23`). The gauge recorder returns `None` rather than `0` when a measurement is impossible, because "an unmeasurable gauge must leave a GAP in the series, never a recorded zero" (`snapshots.py:118-121`). |
| **Never renders a verdict** | `src/briefing/card.py:65` | In code. `verdict` is in the banned field-name fragment list, so a dataclass field or payload key named `verdict` raises. (Note the narrow exception: `SourceQualificationAttempt.verdict` at `src/database/models.py:572` is a *categorical* qualified/disqualified stamp explicitly documented as "never a score" at `models.py:560-562` — it is not a Card/Envelope and does not pass through the guard.) |

Two further invariants matter for this work and are recorded in `CLAUDE.md` and enforced by
`tests/test_repo_invariants.py`:

- **Invariant #16 — one chart toolkit, full-resolution series, sparse→bars.** `n < 10`
  datapoints renders as a **bar** chart, `n ≥ 10` as a line; no downsampling. The constant is
  `_SPARSE_BAR_MAX = 10` (`src/static/app.js:10293`), read at `app.js:10465` (`dashChartSvg`),
  `app.js:11209` (`ooChart`), `app.js:15101` (`smallMultiplesSvg`).
- **Invariant #8 — the UI shows data, never plumbing;** and the "Desk lesson": a surface is
  retired only once its replacement absorbs every capability.

**Caution on `docs/DESIGN.md`:** it is a *draft of the target product* and says so — "It
describes the **target product**, not the current (largely non-functional) code"
(`docs/DESIGN.md:20`). Several of its statements (e.g. "No GPU" at `DESIGN.md:55`) are
contradicted by later rulings in `CLAUDE.md`. **Do not read `docs/DESIGN.md` as current
state.** `CLAUDE.md` is the binding source of truth.

---

## 2. Verified current state of the GUI

**Plainly: a coherent visual language already exists, and it is more mature than a
reconnaissance brief would assume.** This is not an unstyled or ad-hoc GUI. It is a
hand-rolled, dependency-free design system with 17 themes, a token set, vendored fonts, a
12-locale i18n engine, and eleven distinct chart/visual renderers. The honest criticisms are
narrower and specific, and are listed at the end of this section.

### 2.1 Serving stack

FastAPI + uvicorn. **No templating engine at all** — no Jinja2, no `TemplateResponse`
anywhere in `src/` (searched; `NOT FOUND`). HTML is either a static file read from disk and
returned as `HTMLResponse`, or a string concatenated server-side.

- `StaticFiles` mount at `src/api/main.py:593`, serving `src/static/`.
- Loopback-only: `src/api/main.py:2418-2426` reads `OO_HOST` defaulting to `127.0.0.1` and
  refuses any host not in `("127.0.0.1", "localhost", "::1")`.

### 2.2 Every HTML-rendering route (exhaustive)

| Route | Serves | Citation |
|---|---|---|
| `GET /` | `src/static/index.html` (the SPA) | `src/api/main.py:2214-2221` |
| `GET /unlock` | `src/static/unlock.html` | `src/api/main.py:617-621` |
| `GET /investigate` | `src/static/investigate.html` | `src/api/main.py:2238-2242` |
| `GET /tasks` | `src/static/taskmanager.html` | `src/api/main.py:2250-2254` |
| `GET /api/articles/{article_id}/view` | **Server-built** reader HTML | `src/api/main.py:1470-2078` |
| `GET /api/law/documents/{document_id}/view` | **Server-built** law-document HTML | `src/api/law.py:390-530` |
| Bulletin render | `HTMLResponse` for a generated bulletin | `src/api/bulletin.py:183-204` |

### 2.3 Client assets

| File | Size | What it is |
|---|---|---|
| `src/static/app-*.js` | 17 modules, 24,244 lines / 1.4 MB total | The SPA engine, ordered classic (non-module) scripts. Was one 21,301-line `app.js` when this plan was written; split 2026-08-20 (S-3) with zero behaviour change, so every line citation below still names real code, at a different file and offset — resolve by symbol name, not by line |
| `src/static/index.html` | 2,865 lines | The SPA shell; 7 `<script>` blocks |
| `src/static/app.css` | 93 KB | The design system + all 17 themes |
| `src/static/ooviz.js` | 24 KB | Zero-dependency chart *primitives* (math only, DOM-free) |
| `src/static/reader.js` / `reader.css` | 25 KB / 5 KB | The standalone reader's tabs |
| `src/static/i18n.js` | 8 KB | The translation engine (DOM walker) |
| `src/static/osmpbf.js` | 18 KB | OSM PBF decoding |
| `src/static/world_countries.json` | 140 KB | Country fill polygons (175 countries) |
| `src/static/world_outline.json` | 66 KB | Coastline outline |
| `src/static/locales/*.json` | 12 files | ar bn de es fr hi id ja pt ru zh + en |
| `src/static/fonts/*.woff2` | 7 families | Vendored, SIL OFL |

**Third-party libraries: none.** No D3, no charting library, no framework. `ooviz.js:6-8`
states the position: "No D3, no charting libraries, no network, no DOM required for the
math." I found no CDN reference in `index.html` — the only external URLs are a click-target
link to `ollama.com/library` (`index.html:1382`) and `https://…` *placeholder* text in form
inputs.

### 2.4 CSS: a real design token set

`src/static/app.css:15-77` defines `:root` tokens: `--bg/--bg2`, `--panel/--panel2/--panel3`,
`--fg/--fg-soft/--muted`, `--accent/--accent-fg`, `--ok/--warn/--warn-fg/--err`, `--caveat`,
`--chip-off`, `--lvl-group/--lvl-super`, `--border/--border-soft`, `--shadow`,
`--radius/--radius-sm`, `--sidebar-w/--space/--pad`, `--ff/--mono`. 17 themes override them
(`app.css:78+`).

Notable: several tokens exist **because a hardcoded hue failed contrast**, and the comments
record the measurement. `--caveat` exists because the old `#c98a1b` failed WCAG AA on 8 of 17
themes (`app.css:33-37`). `--chip-off` is derived via `color-mix` with a recorded worst case
of 5.70:1 (`app.css:52-57`). `--lvl-group`/`--lvl-super` are `color-mix`-derived with 51
contrast checks per theme recorded (`app.css:38-50`). **This is the house method: derive a new
chart token from theme variables via `color-mix`, verify by contrast math across all 17
themes, and write the worst case in the comment.**

### 2.5 Existing visual components (eleven)

| Renderer | Line | Tech | Form |
|---|---|---|---|
| `dashChartSvg` | `app.js:10458` | SVG, 300×120 | Single-series line / sparse bars, shared time axis |
| `ooChart` | `app.js:11048` | **Canvas** | Multi-series line, wheel-zoom, drag-pan, pinned readout, legend toggle |
| `honestTicks` | `app.js:10336` | — | Tick generator (flat series → one real tick; integer data → integer ticks) |
| `ooMap` | `app.js:15483` | SVG | Choropleth + points + signals layer + in-map controls |
| `ooDonut` | `app.js:8815` | SVG | Part-to-whole donut |
| `_ooShareBars` | `app.js:8779` | SVG | Part-to-whole bars (ooDonut's >5-slice fallback) |
| `slopeChartSvg` | `app.js:15025` | SVG | Slope chart |
| `smallMultiplesSvg` | `app.js:15069` | SVG | Small-multiple panels |
| `ringDumbbellSvg` | `app.js:11904` | SVG | Dumbbell pairs |
| `commodityOverlaySvg` | `app.js:18295` | SVG | Dual-axis price × coverage |
| `renderGraph` | `app.js:14424` | SVG | Deterministic **radial** mind-map, capped at 60 nodes (`app.js:14436`) |
| Ingest-rhythm heatmap | `app.js:8227-8310` | SVG | Matrix heatmap, weekday × hour-of-day |
| `renderStatChart` | `app.js:17435-17465` | SVG | Comparability-**segmented** stat series + `role="img"` + `.sr-only` data table |
| `renderStatMap` | `app.js:17470+` | SVG | Stat choropleth via `ooViz.choroplethData`'s comparability gate |
| `chartEnlarge` | `app.js:15214` | — | Shared enlarge dialog |

`renderStatChart` (`app.js:17435-17465`) is the **best existing model for a new declarative
figure**: SVG, one path per comparability segment never joined, `role="img"` with a computed
`aria-label`, an `.sr-only` `<table>` of the real values, the API's own caveat rendered, and
an honest empty state. Copy its shape.

### 2.6 `ooviz.js`: 12 of 19 primitives have zero call sites

The exported API is 19 entries (`ooviz.js:566-586`), attached as `root.ooViz` (`ooviz.js:592`)
and loaded before `app.js` (`index.html:2856-2857`).

**Wired (7):** `linearScale` (5 uses), `slopeGeometry` (3), `isMissing` (3), `gridLayout` (3),
`statChartGeometry` (2), `niceTicks` (2), `choroplethData` (2).

**Zero call sites anywhere in `src/static/` (12):** `sqrtAreaScale`, `symbolRadii`,
`binCounts1D`, `bin2D`, `fiveNumberSummary`, `pathWithGaps`, `statSeriesPaths`, `setupCanvas`,
`periodToYear`, `mulberry32`, `readCssVar`, `clamp` (verified per-name across all of
`src/static/`).

**This is the single largest opportunity in the repo.** The maths for a histogram
(`binCounts1D`), a box plot (`fiveNumberSummary`), a 2-D heatmap (`bin2D`) and honest
proportional symbols (`sqrtAreaScale` + `symbolRadii`) is written, node-tested
(`tests/ooviz_node_test.js`), and carries the honesty semantics in the shape of its output
(`ooviz.js:9-16`). What is missing is call sites.

**Note for a later session:** a previous audit recorded these as unused by grepping
`ooviz` lowercase. The namespace is **`ooViz`**. A case-insensitive grep is required; a
lowercase grep reports the whole subsystem as dead.

### 2.7 Export path and provenance envelope

Two separate, differently-strong mechanisms:

1. **The export envelope** (`src/utils/export_envelope.py`): `{export_schema: "oo-export-1",
   kind, app_version, generated_at, query, count, payload}` (`export_envelope.py:27-37`), or
   the same as `X-OO-*` HTTP headers for CSV, whose "body must stay plain columns"
   (`export_envelope.py:40-50`). Used by the articles CSV/JSON export at
   `src/api/main.py:1389-1440`. Every CSV cell passes `csv_safe_cell` against formula
   injection (`main.py:1392-1394`). **It carries no hash and no signature.**
2. **The signed evidence bundle** (`src/reporting/evidence.py`): per-article provenance items
   (`evidence.py:78-90`), a Merkle leaf over the *entire* canonical item so every provenance
   field is covered and not just the content hash (`evidence.py:100-104`), a Merkle root, and
   an Ed25519 signature over canonical bytes (`evidence.py:107-133`). `verify_bundle`
   (`evidence.py:142+`) is explicit that "a valid signature only proves 'signed by the key'".

**Neither covers a rendered figure.** There is no figure `kind`, no hash of the rendered
output, and no link from a chart back to a signed manifest. §6 proposes closing this.

### 2.8 The honest criticisms of the current GUI

1. **`ooChart` distinguishes series by colour alone.** The palette is a 4-entry cycle
   `["var(--accent)", "var(--ok)", "var(--warn)", "var(--err)"]` (`app.js:11097`); the stroke
   is that colour and nothing else (`app.js:11210`); the legend swatch is a solid
   `border-top:3px solid ${s.color}` (`app.js:11251`). `setLineDash` appears in `ooChart` only for gridlines
   (`app.js:11190`) and the hover crosshair (`app.js:11244`) — **never for series
   differentiation.** A multi-series `ooChart` is therefore unreadable in greyscale and to a
   colour-blind reader. The app's own CSS states the opposite rule — "Colour is never the
   only signal" (`app.css:379`) — and `ooMap` honours it by dashing the deduced class
   (`app.js:15610`). This is a real, isolated violation.
2. **`ooChart` is canvas; everything else is SVG** (`app.js:11074-11077`). Canvas cannot be
   exported as vector, has no DOM for assistive technology, and cannot be embedded in a
   report. Its pan/zoom is genuinely valuable, so this is a surface-assignment fact, not a
   defect: canvas belongs to the exploratory surface only.
3. **`.card-caveat` is a CSS class, not a component.** Defined at `app.css:975`, hand-built
   at 41 sites in `app.js`. There is no `caveatPanel()`/`methodPanel()` function (searched;
   `NOT FOUND`). Every new figure re-implements the honesty furniture by hand.
4. **588 UI strings are unkeyed**, 307 of them certain. Measured by running
   `python3 scripts/i18n_report.py --audit-chrome`: "2484 UI strings, 1896 keyed, 588
   untranslatable — of which `t("...")` literals (certainly user-facing): 307 unkeyed of 1725
   call sites". The blocking gate is nonetheless green: `python3 scripts/i18n_report.py`
   reports 2592 keys at 100% for all 12 locales, because that gate compares locale files
   against `en.json` and "never touches these paths" (`scripts/i18n_report.py:85-87`).
5. **The `_SPARSE_BAR_MAX` rule does not reach three renderers.** It is read in
   `dashChartSvg`, `ooChart` and `smallMultiplesSvg` only; `ringDumbbellSvg`,
   `commodityOverlaySvg` and `ooDonut` do not consult it (verified by grep of
   `_SPARSE_BAR_MAX`, 4 hits total).
6. **`ooChart`'s legend uses an inline `onclick`** (`app.js:11250`), which adds to the
   `'unsafe-inline'` debt described in §4 — even though the same block attaches a proper
   listener four lines later (`app.js:11254`), so the inline handler is removable.

---

## 3. Verified current state of the data layer

Statuses: **AVAILABLE** = every value already exists in the schema or an existing query.
**DERIVABLE** = a new aggregation over existing columns, no schema change, no new ingestion.
**NOT FOUND** = I looked and it is not there; the search is stated.

### 3.1 The ten assets the prompt named

| What a chart would need | Where it lives | Status | Citation |
|---|---|---|---|
| **Per-source, per-day fetch outcomes** (success / robots-blocked / rate-limit deferral / extraction failure), so a coverage gap is distinguishable from genuine absence of publication | Nowhere as a durable per-source-per-day series. `FeedFetchState` holds a **single overwritten** `last_status` + `last_checked_at` per source. `source_preflight.jsonl` is appended untrimmed but its only reader collapses to **latest-verdict-per-domain over the last 2000 lines**, and preflight runs in bounded batches of 50 by default. `scheduler_runs.jsonl` is **one line per run** with aggregate tallies, read back over the last 200 runs. | **NOT FOUND** | `src/database/models.py:502-544` (esp. `:536`); `src/monitoring/preflight.py:32, 38, 170-172, 190-203`; `src/scheduler/runlog.py:24, 33-59`; `src/scheduler/runner.py:1579-1613` |
| — of which: **per-run failure-reason composition** | `fetch_failed_reasons` rolls `ff:<reason>` tally keys into `{reason: count}`, most-common first, summing to `fetch_failed` | **DERIVABLE** (per run, last 200 runs) | `src/ingest/fetch_verdict.py:95-108`; `src/scheduler/runner.py:2000` |
| **Content-hash duplicate groupings** | `Article.hash` is `unique=True` with a unique index, so exact duplicates are *rejected at ingest* and never stored as a group. `content_multihash` is the self-describing sibling. | **NOT FOUND** as stored groups (by construction) | `src/database/models.py:625, 637, 684` |
| **Canonical-URL duplicate groupings** | `Article.canonical_url` is `nullable=False` and indexed but **not unique**, so same-canonical-url rows can coexist and are groupable by `GROUP BY canonical_url HAVING count(*) > 1`. `canon_version` records which canonicaliser produced each. | **DERIVABLE** | `src/database/models.py:611, 638, 686` |
| **Near-duplicate similarity between documents** | Computed on demand from article **text** — MinHash + LSH + connected components, high-precision. Not persisted anywhere (no fingerprint table in the schema). | **DERIVABLE at L** (requires content decrypt; the live corpus path caps at 400 articles) | `src/signals/near_dup.py:143-330`, esp. `:164` (`minhash_signature`), `:308` (`near_duplicate_clusters`) |
| **Source concentration / inequality measures** | `gini()` returns `None` when undefined (`n < 2` or `total == 0`) and raises on negative values; `top_share()`; `concentration()` composes them. The only API consumer is reading-diet-by-type. | **AVAILABLE** (function) / **DERIVABLE** (a Lorenz series) | `src/signals/concentration.py:52-63, 71-103, 134`; `src/api/insights.py:1097-1111` |
| **Novelty / surprisal per document or per day** | A rolling shingle store with `novelty()`/`add()`/`measure_and_add()` and a batch `novelty_scores(documents)`. Requires text; not persisted. | **DERIVABLE at L** | `src/signals/novelty.py:64-90` |
| **Language, country, publisher attributes per document** | `Article.language` (authoritative, NULL when untagged), `detected_language` (deduced, set only when `language` is absent, never overwrites), `country`, `region`, `author`, all indexed. Publisher = `Source` via `source_id`. | **AVAILABLE** | `src/database/models.py:618-624, 652-654, 695-708` |
| **First-seen timestamps** (latency between related documents) | `Article.created_at` indexed; `published_at` indexed; a composite `(source_id, published_at)`. | **AVAILABLE** | `src/database/models.py:617, 648, 703-706` |
| **Wikipedia revision tracking** | `WikiPage` + `WikiRevision` (per-revision full text stored) | **AVAILABLE** | `src/database/models.py:1923-1971, 1972-2025` |
| **Legal-source catalog + change tracking** | `LawDocument` + `LawRevision` + `LawRevisionSummary` | **AVAILABLE** | `src/database/models.py:2026-2083, 2084-2121, 2122-2152` |
| **Vintaging of statistics** (same figure as published at different dates) | `StatFigure` is append-only per vintage. `to_chart_series()` already returns comparability-**segmented** output with `unit`/`base_year`/`adjustment` per segment, `unparseable_periods`, `duplicates_collapsed` (vintage collapses) and a `caveat`. | **AVAILABLE** | `src/database/models.py:2219-2271`; `src/stats/series.py:136-151` |

### 3.2 Further assets found that a chart could use

| Asset | Status | Citation |
|---|---|---|
| **`StatSnapshot`** — hourly, append-only, **infinite retention by design**, EAV `(metric, taken_at, value)` with a `(metric, hour)` unique constraint doubling as the freshness gate | **AVAILABLE** | `src/database/models.py:2272-2311` |
| Snapshot metric registry: 7 table counts (`articles`, `sources`, `keywords`, `wiki_pages`, `wiki_revisions`, `law_documents`, `law_revisions`) + 4 filtered source-status counts + `articles_per_hour` | **AVAILABLE** | `src/database/snapshots.py:47-55, 106-111, 154` |
| `wal_bytes` **gauge** — deliberately *not* in `ALL_METRICS` (diagnostics, not a user surface); returns `None` when unmeasurable rather than a fabricated 0 | **AVAILABLE** (diagnostics only) | `src/database/snapshots.py:114-152` |
| `hourly_article_counts` — articles/hour **derived live from `created_at`**, so it backfills retroactively for free | **AVAILABLE** | `src/database/snapshots.py:261-287` |
| `metric_history` — bounded read of one metric's series, returning `recording_began_at` | **AVAILABLE** | `src/database/snapshots.py:289-302`; `src/api/library.py:193-195` |
| **`KeywordMention` denormalised columns** — `observed_on` (Date, indexed), `country`, `city`, `source_id` (indexed), plus covering indexes `ix_mention_covering` and `ix_mention_date_keyword` | **AVAILABLE** — per-day / per-country / per-source keyword aggregation **without** the documented SQLCipher codec-trap join | `src/database/models.py:1761-1812` |
| `Article.word_count` + `idx_article_word_count`; `article_length_report` already bins it per content-type and per language and flags unsegmented languages | **AVAILABLE** (values) / **DERIVABLE** (a chartable payload) | `src/database/models.py:655, 710`; `src/analytics/article_length.py:98-123` |
| `ArticleLink` (the citation graph) | **AVAILABLE** | `src/database/models.py:1170-1255` |
| `SourceQualificationAttempt` — append-only, one row per attempt, with `verdict` + `criteria_version` | **AVAILABLE** | `src/database/models.py:547-583` |
| `Source.status` / `qualified_at` / `qualification_criteria_version`; `Source.article_count` maintained counter + `counter_reconciled_at` (NULL = never reconciled → read falls back to a live COUNT) | **AVAILABLE** | `src/database/models.py:429-461` |
| `Article.quarantined` + `quarantine_reason` + `quarantine_criteria_version` + `quarantined_at`, indexed | **AVAILABLE** | `src/database/models.py:662-676, 714` |
| `Article.sentiment_score` / `sentiment_label`, indexed (English-only by design) | **AVAILABLE** | `src/database/models.py:659-660, 712` |
| `Article.server_ip` + `ip_observed_at` + `server_ip_reason` — **NULL over a proxy/Tor, with the reason stated, never a guessed IP** | **AVAILABLE** | `src/database/models.py:639-647` |
| `CommodityPrice` | **AVAILABLE** | `src/database/models.py:1447-1473` |
| `idx_article_source_sentiment` covering index, added after an EXPLAIN showed the plain index dragged whole ~35 KB rows through the codec (447 ms → 38 ms measured) | **AVAILABLE** | `src/database/models.py:715-730` |

### 3.3 The one gap that matters most

**A coverage gap is not currently distinguishable from a genuine absence of publication.**
There is no durable per-source, per-day record of fetch outcomes. The three candidate stores
each fail for a different structural reason (single overwritten status; latest-per-domain
collapse over a bounded tail; one aggregate line per run). Any figure claiming to show
"this source went quiet" would today be asserting something the data cannot support.
§8 records this, and candidate **C3** is the honest, bounded partial answer.

### 3.4 A live honesty gap any new keyword chart would inherit

Keyword aggregates do **not** exclude quarantined articles. `grep -c quarantined`:
`src/analytics/queries.py` → **1** (a single filter at `queries.py:1980`);
`src/analytics/store.py` → **0**; `src/analytics/rollup_serve.py` → **0**;
`src/analytics/columnar.py` → **0**. Meanwhile `Article.quarantined.isnot(True)` is the one
condition every quarantine-aware reader uses (`models.py:668`), and
`source_audit.per_source_metrics` *does* exclude them (`src/analytics/source_audit.py:125-128`).
**A new chart built on keyword aggregates will silently count articles the article gate
already condemned.** Decide this explicitly (see §11, Q4) rather than inheriting it.

### 3.5 A chart's time axis and the date filter do not mean the same thing

> **FOUND 2026-08-04 while scoping F4**, not present in the original reconnaissance.
> Reproduced against the real functions; pinned in `tests/test_chart_time_vs_filter_time.py`.

Two surfaces publish "when an article is", by different rules:

* `KeywordMention.observed_on` = `(published_at or created_at).date()`
  (`src/analytics/store.py:284`) — a **coalesce**. This is the x-axis of every keyword
  trend chart.
* the date filter behind Advanced search and `_resolve_corpus` = `Article.published_at`
  alone (`src/api/main.py:818-821`) — **no fallback**.

So an article whose publish date could not be extracted is **plotted** on the chart at its
ingest date and **excluded** by a filter over that same day. Measured: two articles, one
chart day, one returned.

**The filter is not simply wrong.** Coalescing it would be the mirror defect — an article
ingested in June with no publish date may have been published in 2019, so folding
`created_at` into a filter labelled "published between X and Y" fabricates an *inclusion*
exactly as the present behaviour fabricates an *absence*. Restricting to `published_at` is
the conservative reading. What is missing is (a) any **disclosure** of how many articles the
filter dropped for want of a publish date — derivable with no new storage, pinned in the
test — and (b) agreement between the two surfaces about which "June" is on screen.

**This constrains F4 (Unit 6).** A brush must emit the article ids of the buckets the chart
actually drew, supplied by the same aggregate that produced the bar heights. Resolving a
brushed range through the date filter instead returns fewer articles than the bars implied,
silently: the user selects what they can see and gets less. Carrying the ids makes the brush
inherit the chart's own definition of time by construction, so the disagreement cannot reach
it. It also forces a second honesty gain — a trend bar is a **mention** total, not an article
count (`trend()` sums `KeywordMention.count`), so a brush readout must say both ("6 articles
· 10 mentions") rather than letting one number stand for the other.

---

## 4. Constraints the implementation session must obey

### 4.1 Network posture — no external asset may be contacted

- Loopback-only bind, enforced: `src/api/main.py:2418-2426`.
- Kill switch: `activate_kill_switch` / `clear_kill_switch` / `kill_switch_active` at
  `src/ingest/__init__.py:302-332`.
- **Socket-level backstop:** `install_airplane_socket_guard()`
  (`src/ingest/airplane.py:210-218`) wraps `getaddrinfo`/`create_connection`/`socket.connect`
  process-wide; while the kill switch is engaged any non-loopback target raises before the
  real call. Loopback and AF_UNIX always pass.
- CSP `connect-src 'self'`, `font-src 'self'`, `img-src 'self' data:`
  (`src/api/main.py:498-504`).

**Conclusion: no CDN, no web font, no remote map tile server, ever.** Every new asset must be
vendored in-repo. A map view must use the local vector geometry that already ships
(`world_countries.json`, `world_outline.json`). Fonts are already vendored
(`src/static/fonts/`, 7 families, SIL OFL).

### 4.2 Licence

`GPL-3.0-or-later` (`LICENSE:1-2`; `pyproject.toml:18`). **Rule for any new vendored frontend
dependency: it must be GPL-3.0-compatible** — permissive (MIT / BSD / Apache-2.0) or GPL
itself. The precedents: `ooviz.js` was adopted from an MIT primitive set and relicensed
GPL-3.0-or-later by the same author (`ooviz.js:1-5`); the fonts are OFL and the README states
the compatibility reasoning explicitly (`src/static/fonts/README.md`, final section).
**The strongest option remains adding no dependency at all** — the 12 unwired `ooViz`
primitives cover histogram, box plot, heatmap and proportional symbols already.

### 4.3 Security — CSRF and CSP are **closed**, with one residual

This corrects the prompt's premise (Flag 2).

- **CSRF (S-003): closed.** `src/api/main.py:519-532` refuses any state-changing
  `POST/PUT/PATCH/DELETE` whose `Origin`/`Referer` host is not loopback.
- **CSP (S-006): closed.** `src/api/main.py:498-504, 537-538` attaches
  `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none';
  base-uri 'self'; form-action 'self'; frame-ancestors 'none'`, plus `nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. `/docs`, `/redoc`,
  `/openapi.json` are exempt (`main.py:505`).
- **CSV formula injection (S-004): closed** — `csv_safe_cell` on every cell
  (`src/api/main.py:1392-1394`).
- **`docs/SECURITY.md` is stale as a statement of current state.** It still lists
  "CSRF on no-body POST endpoints (S-003)" and "No CSP / security headers (S-006)" as
  findings (`docs/SECURITY.md:181-186`, `:245`, `:253`) with no remediation annotation
  (`grep -n "RESOLVED\|CLOSED\|remediat" docs/SECURITY.md` → no output).

**The residual, and the actual constraint: `script-src` still needs `'unsafe-inline'`,**
annotated in place as "UI is inline-heavy; nonce-based CSP is future work"
(`main.py:500`). There are **311 inline event handlers in `index.html`** alone
(`grep -oE "on(click|change|input|keydown|submit|mouse[a-z]+)=" | wc -l`), plus inline
handlers generated by `app.js` (e.g. `ooChart`'s legend). **Every new component must use
`addEventListener` and no inline handler, and must need neither `eval` nor `new Function`,**
so it moves the tree toward dropping `'unsafe-inline'` rather than deepening the debt.
Retiring the existing 311 is browser-verification-gated and explicitly **out of scope** here.

### 4.4 Internationalisation

- 12 locales: `src/static/locales/{ar,bn,de,es,fr,hi,id,ja,pt,ru,zh,en}.json`.
- RTL is handled **only at the document level**: `i18n.js:102` sets
  `document.documentElement.dir = "rtl"` for Arabic. There are **zero** `[dir=rtl]` or
  `:dir()` rules in `app.css` (`grep -cE "\[dir=.?rtl|:dir\(" src/static/app.css` → 0).
  **An SVG chart whose x-positions are computed in JS will not mirror.** Whether it *should*
  is a genuine question (§11, Q2): in data visualisation, mirroring a time axis in RTL is
  contested, and getting it wrong silently is worse than deciding it explicitly.
- **The vendored fonts do not cover non-Latin scripts.** Cantarell, Inter, Outfit, Manrope,
  JetBrains Mono and Source Serif 4 are all Latin; the README states scripts a family does
  not cover "(e.g. Arabic, CJK) fall through to the system fonts that do"
  (`src/static/fonts/README.md`, "How they are used"). So chart labels in
  ar/zh/ja/hi/bn render in whatever the OS provides — an honest, documented gap, and a real
  risk for tight SVG label geometry.
- **Every new label must be keyed ×12** or it joins the 588 unkeyed strings measured in §2.8.
  The reader's three provenance headings *are* now keyed (verified: "From the source",
  "Deduced by this app — less reliable", "AI-derived — unreliable" all present in `fr.json`),
  and `i18n.js` is loaded in the server-rendered reader (`src/api/main.py:2024`), so
  server-built HTML is translated client-side by the DOM walker.

### 4.5 Accessibility

- **Colour does carry meaning alone in one place: `ooChart`'s multi-series identity** (§2.8,
  item 1). The convention is stated at `app.css:379` and honoured elsewhere
  (`ooMap` dashes the deduced class, `app.js:15610`), so this is an isolated violation to fix
  rather than a house style to follow.
- Good precedents to reuse: `role="img"` + computed `aria-label` + an `.sr-only` data table
  (`app.js:17460-17462`); the no-data **hatch pattern** `oomap-nodata` (`app.js:15527, 15723`)
  and `rhythm-none` (`app.js:8284, 8307`), which make absence visually distinct from zero
  without using colour.
- `--caveat`, `--warn-fg`, `--chip-off`, `--lvl-group`, `--lvl-super` all exist because a
  hardcoded hue failed contrast on real themes; their comments carry the measured worst case
  (`app.css:20-57`). Any new chart token follows that method.

---

## 5. Message-type map

Eight messages: **(1)** time series **(2)** ranking **(3)** part-to-whole **(4)** deviation
**(5)** frequency distribution **(6)** correlation **(7)** nominal comparison
**(8)** geospatial.

| Data asset | Can honestly carry |
|---|---|
| `Article.created_at` (+ `hourly_article_counts`) | 1, 5 |
| `StatSnapshot` series (11 metrics) | 1 |
| `StatSnapshot` 4 source-status metrics | 1, 3 |
| `KeywordMention.observed_on` (+ `country`, `source_id`) | 1, 2, 7, 8 |
| `Article.word_count` | 5, 2, 7 |
| `ArticleLink` citation graph | 2, 7, and clusters/bridges (node-link) |
| `Article.language` / `country` / `region` / `author` | 7, 3, 8 |
| `Article.canonical_url` groups | 5 (heavy-tailed), 2 |
| `Source.article_count` | 2, 3, and concentration (Lorenz) |
| `SourceQualificationAttempt` | 1, 7, and intervals/sequences (timeline) |
| `Source.status` snapshot | 3, 7 |
| `StatFigure` vintages | 4, 1 |
| `WikiRevision` / `LawRevision` timestamps | 1, and intervals (timeline) |
| `CommodityPrice` | 1, 6 |
| `Article.sentiment_score` (EN only) + its null count | 7, 5 |
| `Article.quarantine_reason` | 2, 3, 7 |
| `Article.server_ip` (geolocated) vs `Source.country` | 4, 8 |
| `fetch_failed_reasons` per run | 2, 7, 1 (bounded to 200 runs) |
| Near-duplicate clusters (on demand) | 5, and clusters (node-link) |
| Novelty scores (on demand) | 1, 5 |
| `gini()` / `top_share()` | concentration (Lorenz) — a shape, not one of the eight |

**Assets carrying none of the eight:**

- `Article.content_multihash` / `canon_version` — identity/provenance labels. They tell you
  *which algorithm* produced a value; there is nothing to compare across them. A "canon
  version distribution" chart would be plumbing, not data (invariant #8).
- `Article.reading_time` — a derived restatement of `word_count`; charting both would map two
  channels to one variable.
- `Source.reliability_score` — operator-set, no default so an unrated source has *no* figure
  (`models.py:414-417`). Carries a message in principle, but see §9: rendering it is rejected.
- `DerivedMeta`, `AppState`, `MergeBatch` / `MergedRow` — internal bookkeeping.
- `FeedFetchState.etag` / `last_modified` — opaque HTTP tokens, "stored verbatim and sent back
  verbatim — never parsed" (`models.py:513-514`).
- `Article.server_ip_reason` on its own — a categorical explanation of an absence. It belongs
  as the caveat text on C12, not as its own chart.

---

## 6. Shared foundations to build first

Ordered. Nothing in §7 should be built before the foundations it depends on.

**F1 — chart series tokens paired with a non-colour cue.** Extend `app.css` with a
categorical series set derived from existing theme variables via `color-mix` (never a
hardcoded hue), each paired with a dash pattern and a marker shape, and a
`--fig-gap`/hatch token for absence. Verify contrast by math across all 17 themes and write
the worst case in the comment — the method used for `--caveat` (`app.css:33-37`) and
`--chip-off` (`app.css:52-57`). This foundation also **fixes the `ooChart` defect** in §2.8.

**F2 — one method/caveat/n panel function.** Replace 41 hand-built `.card-caveat` sites'
pattern with a single helper taking `{method, caveat, n, basis, as_of}` and rendering the
`Envelope` shape (`src/analytics/envelope.py:106-114`). Keyed ×12. This is what makes the
"every figure carries method, caveat and n" invariant cheap to honour instead of a
per-call-site act of discipline.

**F3 — one empty-versus-zero component.** Extract the existing hatch precedents
(`oomap-nodata` at `app.js:15723`; `rhythm-none` at `app.js:8307`) into one shared SVG
`<defs>` + helper, so "no data" is never a zero and never a blank. Must use the hatch (a
shape cue), not a colour, per §4.5.

**F4 — a selection model that a chart can write to.** The read side **already exists**:
`_anIds` (`app.js:17998`), capped at 5000 (`app.js:18057`), threaded into every analysis
subtab by `anParams()` as `article_ids` (`app.js:18006`), consumed server-side by
`_resolve_corpus`, and seeded by `openAnalysisForIds` (`app.js:18116-18118`). **What is
missing is emission** — no chart writes a selection; `ooChart`'s pointer handlers only pin a
readout (`app.js:11268-11302`). Add a documented emit/subscribe so brushing a chart region
produces a set of ids, and linked views become possible. Without F4, every chart is an
island.

**F5 — hover and zoom as shared utilities.** `ooChart` has wheel-zoom, drag-pan and a pinned
readout (`app.js:11268-11302`); `dashChartSvg` has none. Extract them so new figures inherit
overview→detail rather than re-implementing it. Use `addEventListener` only (§4.3).

**F6 — a rendering-approach ruling, written down.** Recommendation: **SVG for every new
figure**; canvas stays only where pan/zoom over many points demands it (i.e. `ooChart`
alone). Rationale is not aesthetic — canvas has no DOM for the `.sr-only` table pattern
(`app.js:17462`) and cannot be exported as vector for the declarative path.

**F7 — extend the export envelope to cover a rendered figure.** Add a figure `kind` to
`src/utils/export_envelope.py:27-37` carrying the figure's method/caveat/n, the parameters
that produced it, and a hash of the rendered output; and let a figure reference the signed
manifest of the article set behind it (`src/reporting/evidence.py:107-133`) so an exported
chart can be verified against the chain of custody. Today neither mechanism covers a figure
(§2.7).

**F8 — i18n discipline as an acceptance criterion, not an afterthought.** Every new label,
axis title, legend entry, caveat and empty state gets an `en.json` key **plus all 11 other
locales**, or `scripts/i18n_report.py --min 100` reddens. Numbers stay language-neutral data
interpolated into a fixed keyed template (the `OOI18N.tf` mechanism).

---

## 7. Ranked candidate table

Surface: **E** = exploratory (the investigation workbench), **D** = declarative (export and
report path). These are two surfaces over one backend, not one view with a toggle.

| # | Candidate | Message | Form | What it shows | Surface | Effort | Claim risk | Shared components | Status |
|---|---|---|---|---|---|---|---|---|---|
| **C1** | Quarantine composition by reason | 2, 3 | Sorted bars | How many articles each quarantine reason condemned, per `criteria_version` | E | **S** | **NONE** | F1, F2, F3, F8 | **PROPOSED** |
| **C2** | Sentiment measurability by language | 7, 5 | Grouped bars (measured vs unmeasured n) | That tone is measured for English only — makes an existing honesty gap visible instead of implicit | E + D | **S** | **NONE** | F1, F2, F3, F8 | **PROPOSED** |
| **C3** | Fetch-failure composition across recent runs | 1, 2, 7 | Small multiples (one panel per reason) | How failure reasons move run to run — the honest, bounded partial answer to §3.3 | E | **M** | **BOUNDED** | F1, F2, F3, F5, F8 | **PROPOSED** |
| **C4** | Article word-count distribution | 5 | Bar chart over labelled ranges (**not** a density histogram — the bins are unequal width) | The real length distribution, per language, excluding pooled unsegmented languages | E | **M** | **BOUNDED** | F1, F2, F3, F8 + `ooViz.binCounts1D` | **PROPOSED** |
| **C5** | Source concentration | concentration | Lorenz curve + Gini printed beside it | How unequally the corpus draws on its sources | E + D | **M** | **BOUNDED** | F1, F2, F3, F8 | **PROPOSED** |
| **C6** | Language × month ingest matrix | 1, 7 | Matrix heatmap | Which languages the corpus is actually growing in — the missing feedback surface for the `language_equilibrium` scheduler lever | E | **M** | **BOUNDED** | F1, F2, F3, F8 + `ooViz.bin2D` | **PROPOSED** |
| **C7** | Qualification attempt history per source | 1, intervals | Timeline / Gantt rows | Each source's attempt sequence, verdicts and re-qualification ladder position | E | **M** | **NONE** | F1, F2, F3, F4, F8 | **REFUSED 2026-08-04 — the form's promises exceed the data; see §7b** |
| **C8** | Stat vintage ribbon | 4 | Slope chart / vintage ribbon | The same official figure as published at several dates — a revision made visible | D | **M** | **BOUNDED** | F1, F2, F6, F7, F8 + existing `slopeChartSvg`, `ooViz.slopeGeometry` | **PROPOSED** |
| **C9** | Revision cadence for tracked wiki/law documents | 1, intervals | Timeline + small multiples | When each tracked document actually changed | E | **M** | **NONE** | F1, F2, F3, F5, F8 | **PROPOSED** |
| **C10** | Canonical-URL duplicate-group sizes | 5 | Log-log or bar over group size | Whether duplicate storage is a long tail or a few pathological cases | E | **M** | **NONE** | F1, F2, F3, F8 | **PROPOSED** |
| **C11** | Word count vs cited-source count | 6 | Scatter | Two measured attributes against each other, with an explicit caveat that neither is a quality measure | E | **M** | **BOUNDED** | F1, F2, F3, F4, F5, F8 | **PROPOSED** |
| **C12** | Observed server-IP country vs asserted source country | 4, 8 | Choropleth of the *difference* + a bar of unmeasurable cases | Where infrastructure sits versus where the publisher claims to — with the CDN/anycast/Tor-NULL caveat | E | **M** | **BOUNDED** | F1, F2, F3, F8 + existing `ooMap` | **PROPOSED** |
| **C13** | Article-length box plot per content type | 5 | Box plot | Distribution where outliers matter, per `source_type` | E | **M** | **BOUNDED** | C4's payload + `ooViz.fiveNumberSummary` | **DEFERRED** — build after C4 proves the payload and the route guard |
| **C14** | Citation network clusters | clusters/bridges | Node-link | Which origins bridge otherwise separate parts of the corpus | E | **L** | **BOUNDED** | F1, F2, F3, F4, F5, F8 | **DEFERRED** — needs a deterministic non-radial layout; `renderGraph` is a radial tree capped at 60 nodes (`app.js:14424, 14436`) |
| **C15** | Near-duplicate cluster-size distribution | 5 | Histogram | How much of the corpus is republication | E | **L** | **BOUNDED** | F1, F2, F3, F8 | **DEFERRED** — requires content decrypt; not persisted (`src/signals/near_dup.py:308`) |
| **C16** | Novelty over time | 1 | Line | Whether new material is actually new | E | **L** | **BOUNDED** | F1, F2, F3, F8 | **DEFERRED** — requires content decrypt; not persisted (`src/signals/novelty.py:64-90`) |
| **C17** | Per-source per-day coverage grid | 1, 8 | Colour-stripe rows | Which source went quiet when | E | **L** | **BOUNDED** | F1, F2, F3, F8 | **DEFERRED — blocked on data.** §3.3: no durable per-source-per-day outcome record exists. Building the *chart* first would assert what the data cannot support. |

### 7b. Two refusals, recorded with their evidence (2026-08-04)

The framework's own rule is that a rejected technique is a FINDING, not a gap. Both of
these were scoped against the live tree and both fail — so they are written down here
rather than left PROPOSED for the next session to re-scope from scratch.

**C7 — a per-source qualification timeline: REFUSED.** Five independent reasons, each
checked in the code rather than inferred:

1. **No duration column.** `source_qualification_attempts` is
   `(id, source_id, attempted_at, verdict, criteria_version)` — `attempted_at` is a single
   instant. So the row's own "Timeline / **Gantt**" phrasing is half wrong for this data: a
   Gantt bar spans a duration, and drawing one here fabricates the span.
2. **Most rows would be a single dot.** `select_unqualified` filters
   `status == 'unqualified'` and `select_due_disqualified` filters `'disqualified'`; nothing
   selects a QUALIFIED source, so it carries exactly one attempt row forever. The form
   promises a sequence worth tracing, and the data has one for the small minority of
   chronically-disqualified sources only.
3. **~40 drawable rows out of ~76,679 sources**, so the chart is bounded by construction and
   owes a disclosed ordering plus the count it left out.
4. **`criteria_version` is a single hardcoded constant**, so faceting or legending by it
   shows one value.
5. **THE DECISIVE ONE.** A chart coloured by verdict would render near-monochrome — not
   because sources are healthy, but because the only `extraction_failure` criterion is
   `pathology_rate` against `PATHOLOGY_ABS_FLOOR = 0.5`, calibrated above the observable
   range (a maintainer-pending ruling already in the ledger). A reader takes a monochrome
   chart as "these sources are almost all fine". That is a fabricated reassurance, and it is
   the one reason that would still hold if the other four were fixed.

Measured while scoping, so a future session need not re-measure: the per-source read the
chart would issue is `SEARCH … USING INDEX (source_id=?)` at 0.10 ms for 40 sources;
choosing which 40 is a covering-index scan plus a temp B-tree at ~6 ms over 24k attempt
rows; the denominator is 1.25 ms. Cost was never the obstacle. The SQLCipher row-decrypt
trap does not apply either — five small columns, no `articles` join, ~1.5 MB at field scale.

What the scoping DID find is shipped instead: the tile's third line was labelled "Never
judged" for a count that includes sources tried repeatedly, and the attempts table — the
only place carrying that distinction — had no reader anywhere in the app.

**F5 — extract `ooChart`'s hover and zoom into shared utilities: REFUSED AS SPECIFIED.**
The ticket's shape ("extract from `ooChart`, the other renderers inherit it") has no valid
target for most of its intended beneficiaries:

1. **`ooChart` is the only canvas chart in the app.** Every other renderer (~10 of them,
   `dashChartSvg` included) returns an SVG *string* that callers interpolate into
   `innerHTML` and keep no handle to, so its scale closures die on return. There is nothing
   for an extracted hover to attach to.
2. **The only SVG-string hover precedent here is the native `<title>` element** — one value,
   one shape, no crosshair, no live readout. Extending that is not reuse of `ooChart`'s
   mechanism; it is a second, structurally different mechanism.
3. **`ooChart`'s hover and zoom are not separable today.** They share `dragX`/`dragT` and one
   `pointermove` with the brush merged in #869 — `dragT == null` is literally what
   distinguishes a brush from a pan — and `Yof` is rebuilt inside `draw()` every frame rather
   than hoisted.
4. **There is no scaffold.** `ooviz.js` has zero event listeners and zero interaction state
   by design, and even its geometry layer is unevenly adopted: `ooChart` and `dashChartSvg`,
   the two renderers this ticket is about, are exactly the two that hand-roll their own
   scales. `setupCanvas` and `readCssVar` are exported and never called.
5. **14+ test files assert on `ooChart`'s literal source**, many over brace-matched slices of
   the very lines an extraction would move.

TWO THINGS FOUND WHILE SCOPING, worth keeping so neither is "fixed" wrongly:
`ooChart`'s local `cssVar` is **not** interchangeable with `ooViz.readCssVar` — the former
falls back to `"#888"` and does not trim, the latter trims and returns `""`, so swapping it
in would turn canvas colours into empty strings. And `sparkSvg` and `trendSvg` have exactly
one occurrence each in `app.js`: their own definitions. They are dead, and their deletion
belongs to the browser-verified dead-code pass the ledger already tracks, not here.

If the underlying want is overview→detail on the SVG renderers, the honest framing is a new,
small, delegated-listener mechanism designed for string renderers — not an extraction.

**Twelve PROPOSED, five DEFERRED.** §9 additionally records **three candidates I generated
and rejected as UNSAFE**, plus the categories the brief excludes outright (listed there for
completeness, not because I proposed them).

### Per-candidate invariant check

Each entry: where method/caveat/n appear · how absence differs from zero.

- **C1** — F2 panel under the bars; `n` = articles judged, per `criteria_version`. Absence: a
  reason with zero articles is **omitted** and the omission stated ("reasons with no articles
  are not shown"), because a zero-height bar reads as a measured zero.
- **C2** — F2 panel; `n` per language split into measured / unmeasured. This candidate *is*
  the empty-vs-zero distinction: an unmeasured language shows a hatched bar (F3), never a
  zero-tone bar. Caveat: tone is VADER, English-only.
- **C3** — F2 panel stating the window is the **last 200 runs** (`src/scheduler/runlog.py:24`)
  and that reasons come from one aggregate tally per run, **not** per source. Absence: a run
  with no failures is a real zero and drawn as one; a run whose line is missing or torn
  (`runlog.py:55-56`) is a gap and hatched.
- **C4** — F2 panel with `n` scanned, `n` with a `word_count`, and the excluded unsegmented
  `n` stated. Absence: an `n == 0` summary must **not** render — `article_length_report`
  returns all-`None` percentiles with an all-zero histogram for an empty set, which would
  draw as a fabricated spike. Branch on it explicitly.
- **C5** — F2 panel with `n` sources and the counter's `basis`: `Source.article_count` is
  maintained, so use `Envelope.estimated` with `counter_reconciled_at` as `as_of`, or fall
  back to the live COUNT and use `Envelope.exact` (`models.py:429-438`). Absence:
  `gini()` returns `None` for `n < 2` or `total == 0` (`concentration.py:52, 71`) — render
  "undefined for this set", never 0.
- **C6** — F2 panel; `n` per cell available on hover. Absence: a month × language with no
  articles is hatched (F3), distinct from a month with zero *new* articles in a language the
  corpus does carry. Caveat: `language` is authoritative-when-present, and
  `detected_language` is a deduced fallback — the two must not be pooled silently
  (`models.py:618-624`).
- **C7** — F2 panel; `n` attempts per source. Absence: a source with **no** attempt row is
  "never judged" and rendered as an explicitly empty row — not as a `disqualified` one. This
  is the exact inversion the 2026-07-23 zero-evidence lesson names, so it needs a test.
- **C8** — F2 panel carrying `to_chart_series`' own `caveat`, `duplicates_collapsed` and
  `unparseable_periods` (`src/stats/series.py:144-150`). Absence: a comparability break is a
  **separate segment, never joined** (the shipped rule at `app.js:17432-17433`); an
  unparseable period is listed, never positioned at a guessed x (`series.py:159-166`).
- **C9** — F2 panel; `n` revisions per document. Absence: a tracked document with no revision
  since baseline is an empty row labelled as such, not a zero-cadence row.
- **C10** — F2 panel; `n` groups and `n` articles. Absence: state that exact-content
  duplicates are rejected at ingest by the unique `hash` (`models.py:625, 684`), so this
  measures canonical-URL collisions **only** — otherwise the figure over-reads as "the
  corpus has no duplicates".
  > **SCOPED + MEASURED 2026-08-04.** Preconditions verified: `canonical_url` is
  > `String(1000) NOT NULL` with a NON-unique `idx_article_canonical_url`
  > (`models.py:611, 686`), and it genuinely differs from `url` on the web path —
  > `url` = the requested URL, `canonical_url` =
  > `canonicalize_url(declared canonical or final redirect)` (`pipeline.py:194, 202-203`),
  > which is what lets several URLs collapse onto one value. No `GROUP BY canonical_url`
  > exists anywhere in the tree, so nothing is being duplicated.
  >
  > **C10 needs a MIGRATION — it is not the no-schema-change build it looks like.**
  > `EXPLAIN QUERY PLAN` over the production-shaped queries (statements captured from a
  > `before_cursor_execute` listener, `ANALYZE` run, engine disposed between checks):
  > the bare aggregate is `SCAN articles USING COVERING INDEX idx_article_canonical_url`
  > — index-only. Adding `Article.quarantined.isnot(True)`, which Q3 obliges every new
  > figure to do, drops it to `USING INDEX` **not covering**: `quarantined` is not in that
  > index, so each row is fetched to evaluate the predicate — a decrypt per row under
  > SQLCipher, the trap `idx_article_source_sentiment` and `idx_article_created_lang` were
  > both added to fix. A composite `(canonical_url, quarantined)` restores
  > `USING COVERING INDEX`; that is the reliable fix and it is a schema change.
  >
  > **Two things that do NOT work, so they are not re-tried:** folding the predicate into
  > the GROUP BY — the trick that fixed the per-language feed — does nothing here and adds
  > a temp B-tree, because the problem is not which index the planner picks but that
  > `quarantined` is absent from every candidate index. And a two-step design (covering
  > aggregate to find collisions, then a bounded `IN (…)` for the quarantine check)
  > measured as a **bare `SCAN articles`** on the probe — but that result is UNSAFE to
  > rely on in either direction: the fixture had 32 collision groups out of 40, so the
  > planner rightly scanned rather than index-seek 112 of 120 rows. A realistic collision
  > rate may well plan differently. If the two-step is preferred over a migration, measure
  > it against a realistic collision density first; the probe settles the composite-index
  > question and settles nothing about this one.
- **C11** — F2 panel; `n` articles plotted and `n` excluded for a missing `word_count`.
  **Mandatory caveat: neither axis is a quality measure**, and correlation is not causation.
  Absence: an article with a NULL `word_count` is excluded and counted in the panel, never
  plotted at zero.
- **C12** — F2 panel; `n` articles with an observed IP, `n` NULL. Absence: `server_ip` is NULL
  over a proxy/Tor **by design** with `server_ip_reason` explaining why
  (`models.py:639-647`) — so "unmeasurable" is a first-class category with its own bar, and
  the choropleth hatches those countries rather than colouring them. Caveat: a CDN edge is
  our vantage point, never proof of origin.
- **C17 (deferred)** — recorded here because the prompt asks it of every candidate: a
  colour-stripe row **strips its own method by design**. It may only ever be built bolted to
  a permanent F2 panel, and never exported standalone.

---

## 8. Data assets with no good visual form

- **Per-source, per-day fetch outcomes.** Not a form problem — a data problem (§3.3). No form
  is honest until a durable record exists.
- **`Article.content_multihash` / `canon_version`.** Identity labels; charting them shows
  plumbing (invariant #8).
- **`Article.reading_time`.** A restatement of `word_count`; a second channel for one
  variable.
- **`FeedFetchState.etag` / `last_modified`.** Opaque tokens, never parsed
  (`models.py:513-514`).
- **`DerivedMeta`, `AppState`, `MergeBatch`, `MergedRow`.** Internal bookkeeping.
- **`Article.server_ip_reason` alone.** A categorical explanation of an absence; belongs as
  C12's caveat text.
- **`wal_bytes`.** It *is* a clean time series, and it is deliberately excluded from the
  user-facing allowlist — "the WAL is diagnostics material, not a user-facing Library
  surface" (`src/database/snapshots.py:146-149`). Respect that; it already reaches the
  diagnostics bundle.
- **Waffle chart, for anything.** Recorded as a finding rather than a gap, because the
  project's own committed framework never mentions the form and prescribes sorted bars or a
  single stacked bar instead; `_ooShareBars` (`app.js:8779`) already implements that, and the
  reasoning is written down at `app.js:2421-2423`.

---

## 9. Rejected candidates

- **Any rendering of `Source.reliability_score`.** The column exists and is operator-set with
  no default (`models.py:414-417`), but a chart of it would read as *the app* grading sources.
  **UNSAFE.** Not softened into a bounded version.
- **A source "health" or "coverage" composite.** Blending robots status, yield, extraction
  validity and recency into one number is exactly what `assert_no_score_fields` /
  `assert_no_score_keys` exist to prevent (`card.py:81-129`). **UNSAFE.**
- **Novelty or concentration presented as an importance/priority ranking of sources or
  documents.** The underlying measures are legitimate (C5, C16); ranking *entities* by them
  renders a verdict. **UNSAFE.**
- **Gauges, speedometers, dials; pie and donut beyond 5 slices; word clouds; 3-D effects;
  immersive views.** Excluded by the brief. Note the house behaviour already complies:
  `_DONUT_MAX_SLICES = 5` (`app.js:8813`) and `ooDonut` hands off to `_ooShareBars` above it
  (`app.js:8826`), which matches the committed chart framework's own prescription.
- **Any revival of the quarantined analyzers.** `docs/QUARANTINE_ARCHIVE.md` exists and no
  `quarantine-archive` branch is present on the remote; nothing from it is proposed here
  under any name.

---

## 10. Execution plan

Each unit leaves the app working. Foundations land before dependents. **Every frontend unit
is browser-unverified in a sandbox** — the manual verification step is how it gets confirmed.

### Unit 0 — Read before writing code (no deliverable)

Files to read: this plan; `CLAUDE.md` (the ledger, binding); `src/briefing/card.py:59-130`;
`src/analytics/envelope.py`; `src/static/ooviz.js`; `src/static/app.js:10293-11412`
(`honestTicks`, `dashChartSvg`, `ooChart`); `src/static/app.js:17431-17465`
(`renderStatChart` — the model to copy).
**Acceptance:** confirm against the tree that the twelve `ooViz` primitives in §2.6 still
have zero call sites and that the §3 statuses still hold. The tree changes fast; a stale
premise is the failure mode this project has been bitten by most.

### Unit 1 — F1 chart series tokens + fix the `ooChart` colour-only defect

Files: `src/static/app.css` (token block near `:root`, `app.css:15-77`);
`src/static/app.js` (`ooChart` series construction `11095-11097`, stroke `11210`, legend
`11249-11256`); `tests/test_repo_invariants.py`.
Acceptance: a multi-series `ooChart` distinguishes series by dash pattern **and** marker
shape as well as colour; the legend swatch shows the dash; contrast math for every new token
is recorded in the CSS comment across all 17 themes; a guard test asserts the dash is present
in the series draw path and is scoped to that function body (use `tests/js_source_helper.py`,
which exists for exactly this and brace-matches from the **body** brace).
**Manual check (non-coder):** open a chart with 2+ series (Insights → Trends → a compare
overlay). Screenshot it, then apply a greyscale filter in any image viewer. **The series must
still be tellable apart.** Repeat on the `contrast` theme and on `paper`.

### Unit 2 — F2 method/caveat/n panel + F3 empty-vs-zero component

Files: `src/static/app.js` (new helpers near the chart block, `~10290`);
`src/static/app.css` (reuse `.card-caveat`, `app.css:975`); `src/static/locales/*.json` (12);
`tests/test_repo_invariants.py`.
Acceptance: one function renders `{method, caveat, n, basis, as_of}` matching
`Envelope.to_dict` (`envelope.py:106-114`); one shared `<defs>` hatch helper covers absence;
all new strings keyed ×12 and `python3 scripts/i18n_report.py --min 100` stays green; no
inline handler introduced.
**Manual check:** every figure touched shows a caveat line **without** clicking anything, in
French and in Arabic (switch via the top-bar language menu). In Arabic, confirm the panel text
reads right-to-left.

### Unit 3 — C1 quarantine composition + C2 sentiment measurability (the two S candidates)

Files: a new read endpoint in `src/api/quarantine.py` and one in `src/api/insights.py`;
`src/static/app.js`; `src/static/locales/*.json`; new tests under `tests/`.
Acceptance: both endpoints go through the existing guarded-read/deadline wrapper used by
sibling insights routes; payload keys contain no `score`/`rating`/`rank`/`trust`/`verdict`
substring (walk your own payload before pushing — the `"degraded"` contains `"grade"` lesson);
an unmeasured language renders **hatched**, not zero; a reason with no articles is omitted and
the omission stated.
**Manual check:** in Settings → Diagnostics (or wherever the panel lands), the quarantine
chart's bars sum to the number the quarantine page reports. The sentiment chart shows English
with a real bar and at least one non-English language **hatched** with the words "not
measured" — not a zero bar.

### Unit 4 — C4 word-count distribution (first `ooViz.binCounts1D` activation)

Files: `src/analytics/article_length.py` (a chartable payload beside the existing report);
a new guarded endpoint; `src/static/app.js`; locales; tests.
Acceptance: the chart is built from `by_language` entries with `unsegmented === false` and
states the excluded `n`; bins are labelled ranges and the axis says so (they are unequal
width, so this is **not** a density histogram); `n == 0` branches to an honest empty state
rather than drawing the all-zero histogram the report returns; the fetch is behind an
**explicit user action**, never a tab-select autoload — it is a full `articles` scan
(`article_length.py:114`).
**Manual check:** the panel shows nothing until you click a button. After clicking, the bars
appear with a visible "scanned N articles, M had a word count, K excluded (unsegmented)" line.
On an empty corpus you get a sentence, not a spike.

### Unit 5 — C5 Lorenz + Gini

Files: a new endpoint reading `Source.article_count` with `counter_reconciled_at`;
`src/static/app.js`; locales; tests.
Acceptance: `Envelope` `basis`/`as_of` reflect whether the counter was reconciled or the live
COUNT was used (`models.py:429-438`); `gini()` returning `None` renders "undefined for this
set" (`concentration.py:52, 71`); the caveat states concentration is a description of the
corpus's own composition, not a judgement of any source.
**Manual check:** the curve starts at (0,0) and ends at (100%,100%); the diagonal
equality line is drawn and labelled; the Gini number is printed with its `n`. On a corpus with
one source, you get "undefined", not 0.

### Unit 6 — F4 selection emission + F5 hover/zoom extraction

> **F4 SHIPPED 2026-08-04 (browser-verified); F5 NOT BUILT.** The selection half is done:
> `trend_range_article_ids` + `GET /api/insights/trend-articles` resolve a brushed span to
> real ids on the chart's own clock, and `ooChart` gained the gesture, an in-chart toggle,
> a band and a live readout. Exactly ONE chart opts in — `#ins-trend-oo`. `#an-trend-chart`
> is excluded because it plots the analysed term alongside related keywords, so "which
> series" needs a per-series control first; `#corpus-chart` is excluded because `corpusTab`
> has **no callers** (the retired `#corpus-win` modal), so a capability there would be
> unreachable and a guard asserting it would pass while proving nothing.
>
> **Still open in this unit:** F5 (extract hover/zoom as shared utilities so `dashChartSvg`
> inherits overview→detail) — which is what C3 and C9 are waiting on. C7 and C11 wanted F4
> and are now unblocked. A per-series selection control for the multi-series analysis-window
> trend is the natural next slice.
>
> Three facts found while scoping it, each of which changed the design the acceptance
> criteria below imply:
>
> 1. **§3.5 — a brush must carry the aggregate's own ids, not resolve a range through the
>    date filter.** The chart axis coalesces `published_at`/`created_at`; the filter does
>    not. Round-tripping under-selects silently.
> 2. **`trend()` returns `{date, count}` only** (`src/analytics/queries.py:249-277`) — it
>    groups on `observed_on` and sums `count`, so there are no ids to emit today. The
>    honest source is an opt-in, bounded, disclosed per-bucket id list on the aggregate
>    that drew the bars. The existing precedent for handing back *real* ids that narrow a
>    corpus is `corpus_facet_article_ids` + `/corpus-facet-ids`
>    (`queries.py:778-844`, `insights.py:696-728`), including the id-seeded INTERSECT case
>    — a brush is that same drill grammar with a period as the value.
> 3. **A bar is a mention total, not an article count**, so the emit and its readout must
>    state both numbers; letting one stand for the other is the conflation this project
>    otherwise refuses.
> 4. **A brush can only honestly select whole BUCKETS** (found by an adversarial critic
>    reading the screenshot, after the first pass had shipped). Fact 1 above is only half
>    the rule: resolving on the right COLUMN at the wrong GRANULARITY is still wrong. A
>    weekly bar is drawn at its Monday, so a day-precise span cuts one in half while it
>    still looks inside the band — four visible bars summing to 65 mentions were reported
>    as 50. The span now widens to the edges of the buckets it touches, the bucket travels
>    with the request, the response reports the EFFECTIVE span rather than the raw drag,
>    and the client preview snaps through the same widening so one gesture never has two
>    answers. `bucket="day"` is the identity case. Any future chart that opts in must pass
>    its own `bucket`.
>
> Also note **plain drag is already pan** and `pointerup` treats a <4px drag as
> click-to-pin (`app.js:11867-11890`), so brushing needs its own gesture *plus* a visible
> affordance — a modifier alone is undiscoverable, and the house pattern is an in-chart
> control (ooMap's own zoom/granularity/layer controls sit inside the map).
>
> Already done in PR #867: `ooChart`'s inline legend `onclick` is converted to a real
> `addEventListener`, which this unit lists as its own requirement.

Files: `src/static/app.js` (`_anIds` `17998-18006`, `openAnalysisForIds` `18116-18118`;
`ooChart` interaction handlers `11268-11302` — wheel `11268`, pointerdown `11279`,
pointermove `11280`, pointerup `11293`, dblclick `11302`; legend `11249-11256`); tests.
Acceptance: brushing a range in a chart produces a set of article ids and routes through the
existing `article_ids` path with no new backend; the 5000-id cap and its disclosure are
preserved (`app.js:18057`); handlers are `addEventListener`, and `ooChart`'s inline legend
`onclick` is converted in the same pass.
**Manual check:** drag-select a region of a time chart; the analysis window opens showing
**only** the articles from that period, and the header says how many. The count matches what
the chart's own hover readout implied.

### Unit 7 — C6 language × month matrix (first `ooViz.bin2D` activation)

Files: a new aggregation (`GROUP BY language, month` over `Article`); a guarded endpoint;
`src/static/app.js`; locales; tests.
Acceptance: run `EXPLAIN QUERY PLAN` and record it in the test — there is **no**
`(language, created_at)` composite index (the index list is at `models.py:682-731`), so the
plan must be checked, not assumed; authoritative `language` and deduced `detected_language`
are not pooled silently; empty cells hatch.
**Manual check:** the grid shows months across and languages down; hovering a cell gives a
real count; a month before the corpus existed is hatched, not dark-coloured-as-zero.

### Unit 8 — C7 qualification timeline + C9 revision cadence

Files: endpoints over `SourceQualificationAttempt` and `WikiRevision`/`LawRevision`;
`src/static/app.js`; locales; tests.
Acceptance: **a source with no attempt row renders as "never judged", never as
`disqualified`** — with a dedicated regression test, because that inversion has shipped in
this repo before; the ladder position derives from
`src.catalog.qualification.consecutive_disqualifications` rather than being recomputed
(`models.py:550-553`).
**Manual check:** pick a source you know has never been trialled; its row is visibly empty and
labelled, not marked bad. Pick one that was disqualified twice; its two attempts appear with
dates in order.

### Unit 9 — F6 ruling + F7 export envelope for figures, then C8 vintage ribbon

Files: `src/utils/export_envelope.py`; `src/reporting/evidence.py` (reference only, no change
to the signing scheme); `src/static/app.js` (reuse `slopeChartSvg` at `app.js:15025`);
`docs/` for the F6 ruling; tests.
Acceptance: an exported figure carries its method/caveat/n, the parameters that produced it,
and a hash of the rendered output; it can reference the signed manifest of its article set;
comparability segments are never joined and unparseable periods are listed
(`src/stats/series.py:144-166`).
**Manual check:** export a vintage figure, open the accompanying JSON in a text editor, and
confirm you can read: which series, which area, which vintages, what the caveat says, and a
hash. Re-export without changing anything — the hash matches.

### Unit 10 — C3 fetch-failure composition, C10 duplicate groups, C11 scatter, C12 IP-vs-asserted

Four independent small units, any order. Each: endpoint + panel + locales + tests, with the
per-candidate invariant checks from §7.
**Manual check (C3):** the panel says "last 200 runs" and "per run, not per source" **before**
you read any number. **(C11):** the caveat under the scatter says, in your own language, that
neither axis measures quality.

**Not in this plan:** the 311 inline handlers (browser-gated); C13–C17; the Observatory;
anything requiring a networked machine or an Ollama rig.

---

## 11. Open questions requiring a human decision

> **ANSWERED IN THE BUILD (2026-08-04):** Q1, Q3, Q4 and Q6 were settled by shipping and
> are annotated inline below. Q2, Q5 and Q7 remain open.

1. **Do SVG charts mirror under RTL?** **ANSWERED: no, and the surrounding panel does.**
   Verified in Chromium in Arabic: the bar rows mirror for free (flexbox honours `dir=rtl`,
   so labels move right and values left) while the Lorenz `<svg>` stays LTR. That is the
   right split *for these figures* — both Lorenz axes are cumulative shares, not a time
   axis, so mirroring would be gratuitous. A figure whose x-axis IS time still needs its own
   ruling. Original note follows. There are zero `[dir=rtl]` rules in `app.css` and
   `i18n.js:102` only sets the document `dir`. Mirroring a time axis in Arabic is genuinely
   contested practice. A ruling is needed before Unit 1; the default I would apply absent one
   is **do not mirror the plot area, do mirror the surrounding panel text**, stated in the
   caveat.
2. **Non-Latin chart labels.** Bundled fonts are Latin-only and non-Latin falls through to
   system fonts (`src/static/fonts/README.md`). Accept the fallback, or bundle a subset CJK /
   Arabic face (large)? Affects label geometry in every candidate.
3. **Do new charts exclude quarantined articles?** **ANSWERED: yes, and the exclusion is
   named in the method string** (`sentiment_measurability` and `source_concentration` both
   filter `Article.quarantined.isnot(True)`, with a test pinning it). This settles the new
   figures only; the standing disagreement among the *existing* keyword aggregates is
   untouched. Original note follows. §3.4: keyword aggregates currently do not
   (`queries.py` 1 filter; `store.py`/`rollup_serve.py`/`columnar.py` 0), while
   `source_audit.per_source_metrics` does. **Two gates disagreeing about one input is exactly
   what one settings panel makes visible and two panels hide** — the repo's own words at
   `source_audit.py:127-128`. My recommendation: exclude, and disclose the exclusion in the
   method string.
4. **Which surface owns the declarative path?** **DEFERRED BY BUILDING THE EXPLORATORY HALF
   ONLY.** All four figures landed on Library → Composition, which is where "what is in my
   corpus" already lives (beside Activity = how it grew and Database & storage = how many
   bytes). No declarative/export home was invented, so F7 and the D-marked half of C2/C5/C8
   still need this answer. Original note follows. `/investigate` exists
   (`src/api/main.py:2238`) but the export/report path is not clearly anyone's home today.
   C2, C5 and C8 are marked D and need an address.
5. **The `article_length_report` full-scan cost.** It iterates every article row
   (`article_length.py:114`). At the ~1M-article scale the 0.3 gate targets, is an
   explicit-action-only fetch acceptable (my recommendation), or should it become a background
   job with a persisted result?
6. **Is `'unsafe-inline'` removal a goal this work should serve?** **ANSWERED: treated as
   yes.** Every new component uses `addEventListener` only, and `ooChart`'s legend became a
   real `<button>` with a listener (see correction 2 at the top — the inline handler was NOT
   redundant, so this required adding a listener rather than deleting an attribute). Net
   inline handlers in `app.js` went down by one, not up. Original note follows. I have assumed yes and
   required `addEventListener` throughout. If the maintainer would rather not open that path,
   Unit 6's conversion of `ooChart`'s legend handler should be dropped.
7. **Should C3 be built at all**, given it cannot answer the question §3.3 actually poses?
   It is honest and bounded, but a reader may over-read it. The alternative is to build
   nothing here and instead record the durable-fetch-outcome record as a data proposal.

---

## 12. Everything I could not verify

- **Anything requiring a browser.** No browser was run. Every rendering, contrast, layout and
  RTL claim about *appearance* is read from source or computed from CSS variables — not
  sampled from pixels. The manual checks in §10 exist because of this.
- **Anything requiring the network.** No fetch was made. I did not verify that any external
  URL in the repo resolves.
- **Runtime behaviour of the app.** I did not start the server, unlock a corpus, or execute
  any endpoint. All endpoint behaviour is read from source.
- **The full test suite.** Not run during the reconnaissance pass, and I recorded it as "not
  runnable here" — **which was wrong, and the execution session found out the same day.** The
  DEFAULT `python3` is 3.11.15, but `/usr/bin/python3.13` exists, so a venv on the required
  interpreter installs the project and runs the whole suite. (Chromium is present too, at
  `/opt/pw-browsers/chromium-1194/` — see the correction at the top of this file.) During the
  read-only pass, where a guard mattered I reproduced its exact logic in plain Python instead — that is how `test_docs_index_covers_live_docs`
  (`tests/test_repo_invariants.py:7482`) was found to redden on this plan's own new
  `docs/plans/` directory, and fixed, before CI reported it. **A later session must treat
  every test claim in this plan as unexecuted** and run `make check` on 3.13.
- **Whether `docs/SECURITY.md`'s remaining findings (S-001 residual, S-002, S-005, S-007,
  S-011, S-012) are still open.** I verified only S-003, S-004 and S-006 against the code.
- **Real-corpus scale behaviour.** Every cost statement is inferred from indexes and code
  paths. I did not measure a query. The `EXPLAIN QUERY PLAN` requirement in Unit 7 exists
  because I could not run it.
- **`CLAUDE.md` in full.** It is 819 KB. I read the portions supplied as project instructions
  and verified specific claims against code rather than trusting the ledger's prose; where the
  ledger and the tree disagreed (the `ooviz` casing; the shipped qualification tile; the
  closed CSP/CSRF findings; the widened i18n gate) I recorded the tree.
- **Whether the twelve unwired `ooViz` primitives are referenced from anywhere outside
  `src/static/`.** I searched `src/static/` exhaustively per name. A template or test
  elsewhere could reference them; I did not sweep the whole repo per name.
- **`tests/` contents.** I cited `tests/ooviz_node_test.js`, `tests/js_source_helper.py` and
  `tests/test_repo_invariants.py` by name from references in source and the ledger. I did not
  open them, so I cannot state what they currently assert.
