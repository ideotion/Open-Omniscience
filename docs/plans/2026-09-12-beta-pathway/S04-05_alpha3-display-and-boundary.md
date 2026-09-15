# S04-05 — ISO 3166-1 alpha-3, step 1: display and boundary; the loader normalises; the filename rule · 0.4, `RELEASE_0.4_GATE.md` row L

> **Scope:** `src/catalog/countries.py` (the converters, one display helper per side), every surface that
> shows a country (`app-map.js`, `app-agenda.js`, sources, markets, laws, wiki, the bulletin's `annexes.py` /
> `articles.py`, diagnostics payloads — DISPLAY only), the JSON API payloads (`country_iso3` beside `country`,
> parameters accepting both), the config loaders (`csv_io.py`, the YAML loaders), a filename rule with its
> repo test, `src/catalog/wikidata.py` (the P298 cross-check), the language-code display step, the locales.
> Must NOT: widen the six `String(2)` columns, rewrite the config lines, touch the three external contracts
> (FRED/OECD ids, the OSM `ISO3166-1:alpha2` tag, DB-IP), or touch the backup format (`S04-04`).
> **Implements:** Q301 ⛔ (step 1), Q302 (TENSION), Q303, Q306 (proposed placement), Q307, Q308, Q309,
> Q311, Q312.
> **Gated on:** nothing pending. The exports' columns are `S04-04`'s (Q313); the storage half is `S05-02`.
> **Sequencing:** with or after `S04-04` (the same converters); before `S04-08` births its tables alpha-3
> (Q312's "alongside the substrate"); never concurrent with `S05-02`.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved. The sheet
section is §4 (R6). The loader touches the sources' identity boundary: the full skeptic matrix applies.

## 1. The rulings this slice implements — verbatim, by ID

- **Q301** ⛔ — **(c)** «FULL, staged: (b) in 0.4, the storage half in 0.5 once the backup-format bump and the
  normaliser have shipped and been exercised on a real restore.» [placement: step 1 in 0.4; step 2 = S05-02]
- **Q302** — **(c)** «Name only, the code in the hover bubble.» — NOTE (verbatim): «but in the opposite way
  (the code is displayed and the full conutry name is shown in the hover bubble in the UI language)»
  [TENSION: the note is the ruling — the CODE is displayed, the NAME is in the hover, in the UI language]
- **Q303** — **(a)** «World-Bank-compatible: `EUU` (EU), `XKX` (Kosovo), `ANT` (the withdrawn Netherlands
  Antilles, legacy rows only), `GBR` for the law `uk`, and app-defined `INT` for "international", each
  disclosed in the hover as "not an ISO code".»
- **Q306** — **(b)** «Move to ISO 639-2/3 (`fra`).» [placement: proposed placement: display step in 0.4,
  storage in 0.5 (S05-02), mirroring Q301 = c]
- **Q307** — **(a)** «Keep the flag emoji, derived internally from alpha-3 → alpha-2»
- **Q308** — **(a)** «By localised name, the code as a secondary column.»
- **Q309** — **(a)** «Rule: a filename carrying a country uses uppercase alpha-3 (`osm_FRA_2026-09.pbf`,
  `laws_DEU.jsonl`), enforced by a repo test over `data/` naming helpers.»
- **Q311** — **(a)** «Confirm; fetch `P298` in the catalog query as a cross-check.»
- **Q312** — **(a)** «0.4»

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §4 context (VERIFIED): storage is lowercase alpha-2 (`src/catalog/countries.py:1–21`); six `String(2)`
  columns (`models.py:335, 425, 667, 1246, 1835, 1947`); `LawDocument.jurisdiction` a free `String(8)` (`uk`,
  `eu`, `int`); `StatFigure.ref_area` already alpha-3; `Intl.DisplayNames(type:"region")` accepts alpha-2 and
  M49 only (`app-map.js:91–99`); the flag gate `/^[A-Z]{2}$/` (`app-agenda.js:981–985`); 5,803 `country:` /
  `jurisdiction:` lines across 14 YAML files; no filename carries a country code; language codes share a
  normalisation branch with country at `csv_io.py:130`. FROM MEMORY in the sheet (Q303): the ISO user-assigned
  range AAA–AAZ, QMA–QZZ, XAA–XZZ, ZZA–ZZZ — confirm before building on it.
- grep-verified in this brief: `src/database/models.py` — `String(2)` country at `:335`, `:425`, `:667`,
  `:1246`, `:1835`, `:1947`; `LawDocument.jurisdiction` `String(8)` `:2244` ("uk, eu, fr, us, int…"),
  `LawDocument.language` / `.country` `String(8)` `:2269–2270`; `StatFigure.ref_area` `String(24)` `:2445`.
- grep-verified: `src/catalog/countries.py` — `ISO2_TO_ISO3` `:641`, `to_iso2` `:644`, `to_iso3` `:672`,
  `classify_ref_area` `:691`, `normalize_country` `:731`, `country_display_name` `:747` (its docstring:
  "displayed as full English names" — English only), `continent_of` `:762`; the WB aggregates comment
  `:617–618` (`EUU`… absent from the choropleth; Kosovo `XKX`).
- grep-verified: `app-map.js:91–99` `ooRegionName` → `Intl.DisplayNames([lang], {type:"region"})`;
  `app-agenda.js:980–985` `agFlag` gates on `/^[A-Z]{2}$/`, globe for the rest;
  `src/catalog/csv_io.py:126–136` lower-cases `country` and `language` then calls `normalize_country`.
- grep-verified: `grep -rc "country:\|jurisdiction:" configs/ --include=*.yml --include=*.yaml` → 12 files,
  5,761 lines (the sheet: 5,803 / 14 — the count depends on the pattern; neither is rewritten in 0.4).
- grep-verified: `src/catalog/wikidata.py:8–41` keys the catalog query on `P297` (`wdt:P297 "{cc}"`); `P298`
  appears nowhere in `src/` or `scripts/`.
- grep-verified: the `data/` naming helpers today — `src/geo/osm_downloads.py:65 osm_filename(code)` →
  `<code>-latest.osm.pbf` where `code` is a Geofabrik REGION code (lowercase, hyphenated, `is_valid_code`),
  not a country; `src/wiki/dumps.py:130 dump_filename(wiki, kind)` keys on an edition — so the rule starts
  with zero country-bearing filenames, as the sheet says.
- grep-verified: the bulletin prints `country` raw (`src/bulletin/annexes.py:412`, `:455`;
  `src/bulletin/articles.py:107–119`, `:211`). Tests to extend: `tests/test_country_normalization.py`,
  `tests/test_countries_geo.py`, `tests/test_source_country_rollup.py`.

## 3. Slices — what to build, in order

### S1 — One formatter per side; the code on screen, the name in the hover (Q301 step 1, Q302 note)
- **What:** a server helper and a JS helper render every country the user sees as UPPERCASE alpha-3, with the
  full country name in the UI language in the `#oo-tip` hover (invariant #17). `Intl.DisplayNames` keeps
  working by deriving alpha-2 internally (`ooRegionName` is fixed, not dropped); server-rendered surfaces (the
  bulletin) need localised names ×12 — the source is the session's to find and name (`country_display_name`
  is English only).
- **Why (ruling):** Q301 = c step 1; Q302 as the note rules it; R6.
- **Acceptance:** the gate's click-through across map, agenda, sources, markets, laws, wiki, plus the
  bulletin — codes on screen, hovers carrying the name — en, fr, ar, zh.

### S2 — Non-countries and special cases (Q303)
- **What:** `EUU`, `XKX`, `ANT` (legacy rows only), `GBR` for the law `uk`, `INT`; each hover says "not an
  ISO code" ×12; the law jurisdiction values (`uk`, `eu`, `int`…) map through the converter;
  `classify_ref_area` and the WB codes stay as they are.
- **Why (ruling):** Q303 = a. **Acceptance:** a table-driven test of the five codes and their disclosure.

### S3 — Payloads and parameters (the 0.4 shape of Q304, per the gate row)
- **What:** every JSON payload carrying `country` gains `country_iso3` beside it; every parameter accepts both
  forms through `normalize_country` (extended to take alpha-3 via `to_iso2`, fail-closed: an unknown
  three-letter code is refused, never stored; aggregates never become countries).
- **Why (ruling):** the gate row L ("payloads gain `country_iso3` beside `country` and every parameter
  accepts both forms through `normalize_country`"); Q313's export columns are `S04-04`'s.
- **Acceptance:** payload tests per endpoint; a negative test per refusal.

### S4 — The loader normalises, the files stay (Q305 "follows Q301" → step 1)
- **What:** the YAML and CSV loaders accept either form and never rewrite a file; a test asserts no config
  line changes under a load. **Why (ruling):** the gate row ("the loader normalises the 5,803 `country:` /
  `jurisdiction:` config lines without rewriting the files"); Q301 = c.

### S5 — Flags and ordering (Q307, Q308)
- **What:** `agFlag` derives alpha-2 from alpha-3 before the emoji (globe for non-ISO stays); country pickers
  order by localised name with the code as a secondary column. The wiki edition picker is LANGUAGE-based
  (invariant #1) and is not a country picker. **Why (ruling):** Q307 = a; Q308 = a.

### S6 — The filename rule (Q309)
- **What:** a repo test over the `data/` naming helpers: any filename carrying a country uses uppercase
  alpha-3; region codes (`osm_filename`) and edition codes (`dump_filename`) are registered as non-country
  keys so the test cannot pass vacuously; the per-country OSM extracts (`S05-04`) and law bundles (`S04-10`)
  adopt it. **Why (ruling):** Q309 = a. **Acceptance:** the test, mutation-checked with a fake
  `laws_de.jsonl` helper.

### S7 — `P298` as a cross-check (Q311)
- **What:** the catalog query also fetches `P298` and reports a disagreement with the converter as a
  diagnostic line, never auto-fixed. This changes a consented WDQS query, adds no host (listed by `S04-01`),
  runs under the one online consent, is refused under the kill switch with a NAMED refusal, and never
  downgrades Tor → clearnet (Q1014). **Why (ruling):** Q311 = a; Q1001.

### S8 — Language codes, the display step (Q306 = b, proposed placement)
- **What:** every language CODE the user sees reads ISO 639-2/3 (`fra`); storage stays 639-1 until `S05-02`;
  the native-name language switcher (invariant #15) shows names, not codes, and is untouched; the shared
  `csv_io.py:130` branch gains the same accept-both discipline. **Why (ruling):** Q306 = b; the placement is
  the planning session's (§6).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: `node
--check` on every touched `<script>` block; the three i18n gates for every new string (the "not an ISO code"
disclosures, any picker headers); the whole-tree guard set; the skeptic matrix on the boundary — negative
space: an unknown alpha-3 is refused, a WB aggregate never becomes a country, no config file is rewritten,
`None` stays `None`; every guard mutation-checked; the Chromium click-through (Q1128 = a) of the six surfaces
the gate names plus the bulletin — en, fr, ar (RTL), zh; the filename-rule test; the numstat rule for the
ledger files. The real-restore proof belongs to `S04-04`: `not-measurable-here` for this slice.

## 5. Operator steps

1. The maintainer's click-through of every surface in §4 (Q1128 = a). Artifact: the record under
   `docs/audit/`.
2. The maintainer's word on the source of localised country names for server-rendered surfaces (§6).

## 6. What this slice may not decide

- Q301's 0.5 half (`S05-02`): the six columns, the config rewrite, the payload flip, the diagnostics switch.
- Q306's placement is *proposed* (display here, storage in 0.5) — follow it unless the gate's §3 moves it;
  and which table (ISO 639-2 B or T, or 639-3) supplies the codes where they differ — `fra` fits both,
  `deu`/`ger` does not.
- The source of localised country names ×12 for server-rendered hovers; whether `ANT` legacy rows exist.
- Which pickers Q308 covers beyond the ones the session enumerates in the PR.
- No ASSUMPTION and no CONFLICT is built on here; Q301 ⛔ was answered (c) and is built as step 1.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or
  PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
