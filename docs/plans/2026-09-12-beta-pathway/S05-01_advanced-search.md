# S05-01 — Advanced search · 0.5, `RELEASE_0.5_GATE.md` row A

> **Scope:** `src/database/fts.py` (grammar, `_quote`, the token class), `src/api/main.py` (`/api/articles`,
> `/api/articles/export`), `src/api/search_omni.py` (the omnibar's Enter), the `Watch` model + its engine and
> routes, `ooTimeScope` in `src/static/app-markets.js`, the Search tab and `#an-advanced` in `index.html`,
> the first-launch flow in `src/static/unlock.html`, one new background job, locales ×12. Must NOT touch: the
> ring-expansion semantics of 0.4 row N, the backup format (0.4 row K), the quarantine write path.
> **Implements:** Q505, Q601–Q618 (nineteen rulings; none ⛔, none 🔒).
> **Gated on:** 0.4 row N (the literal toggle); 0.4 row L (alpha-3 display). Nothing PENDING.
> **Sequencing:** first in 0.5 — no operator step; S05-04, S05-07 and S05-11 consume its `ooTimeScope` and
> its omnibar rule (Q608). S05-09's inline-handler ratchet, once it exists, covers every line added here.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q505** — **(b)** «(b) Advanced search only.»
- **Q601** — **(a)** «(a) Confirm the list.» — the sheet's thirteen-filter v1 list, reproduced in gate row A.
- **Q602** — **(a)** «(a) Rows of `field · operator · value` rendered as chips above the query box; the box
  stays editable and shows the compiled query (two-way: typing updates the rows where parseable).»
- **Q603** — **(a)** «(a) Add prefix `word*`, `NEAR(a b, N)`, and column filters `title:`, `author:` —
  three FTS5-native additions behind an explicit token class so `_quote`'s injection safety stays.»
- **Q604** — **(a)** «(a) English tokens stay canonical; the builder is the localised layer (buttons say
  "ET/OU/SAUF" in French, compile to `AND/OR/NOT`); a hover explains each.»
- **Q605** — **(b)** «(b) A SymSpell-shaped precomputed table built by a background job (deletes-within-2
  over the keyword vocabulary), offering "did you mean" — never silently rewriting the query.»
- **Q606** — **(a)** «(a) The Watch model gains the full filter set; a saved search is a watch with
  threshold zero.»
- **Q607** — **(a)** «(a) `/api/articles/export` takes the full parameter set, so an export reproduces the
  filtered view.»
- **Q608** — **(a)** «(a) Enter always opens the analysis window on the typed query; static commands need
  an explicit selection.»
- **Q609** — **(a)** «(a) `ooTimeScope` gains the timescale selector and becomes the one begin/end/scale
  component for Advanced, Markets and Insights»
- **Q610** — **(a)** «(a) Fold by default (`é` = `e`, case-insensitive) with an "exact" toggle per
  query.» — NOTE (verbatim): «but keep an on/off toggle for user in advanced search with an explanation in
  a hover»
- **Q611** — **(b)** «(b) Also `url:` and `tag:`.» — NOTE (verbatim): «we need to be precise for user
  clarity : would the url/title/author/source 'contain' or 'start with' or else? give user choice while
  keeping the UI fresh and simple» [the note adds a requirement the label lacks — build the note]
- **Q612** — **(a)** «(a) `NEAR` defaults to 10 tokens; the builder's row has a distance stepper.» — NOTE
  (verbatim): «however, the user should be able to change the default number»
- **Q613** — **(a)** «(a) A deliberate omission»
- **Q614** — **(a)** «(a) Local, private, opt-in (default off), clearable, never exported.» — NOTE
  (verbatim): «add the option during the installation process, after the legal screen, to activate local
  search history»
- **Q615** — **(a)** «(a) List (cards) + a table view toggle (sortable columns: date, source, language,
  words, sentiment).»
- **Q616** — **(a)** «(a) The full query + every filter is URL-addressable (`?q=…&lang=…&from=…`), so a
  search can be shared as a local link and re-opened after a restart.»
- **Q617** — **(a)** «(a) Excluded by default; "include quarantined" is an advanced-only control with the
  quarantine reason shown on each such row.»
- **Q618** — **(b)** «(b) Relevance»

## 2. Where this stands in the tree — the staleness guard, with anchors

- `_OPERATORS = {"AND", "OR", "NOT"}` at `src/database/fts.py:49`; `_quote` at `fts.py:160–167` (sheet
  VERIFIED; grep-verified in this brief: `sed -n '40,60p;155,170p' src/database/fts.py`).
- **Not in the sheet:** the FTS table is `tokenize='unicode61 remove_diacritics 2'` at `fts.py:254`
  (grep-verified: `grep -n tokenize src/database/fts.py`; the sheet's `unicode61` was FROM MEMORY). Diacritics
  are stripped at INDEX time, so Q610's "exact" toggle needs a second unfolded index or a post-filter.
- `/api/articles` at `src/api/main.py:1433`; filters per the sheet (VERIFIED): `source` (exact, 404 on a
  typo), dates, `language` (asserted only), `tags`, `provenance`, `source_type`, `ids`, six sorts — the rest
  of Q601's list is indexed and unexposed. `/api/articles/export` at `main.py:1623` takes only `format,
  query, source, start_date, end_date, language, tags, ids` (grep-verified: `sed -n '1623,1642p'`).
- `ooTimeScope` at `src/static/app-markets.js:2351` (sheet `2351–2496`; grep-verified): presets, no
  timescale selector. `#an-advanced` at `index.html:469–485`: five bare controls, two inline handlers.
- `Watch` at `src/database/models.py:2515`: `name`, `query`, `threshold` (default 3), `window_days`
  (default 7), `enabled`, timestamps, `last_seen_ids` (grep-verified); routes in `src/api/watches.py`.
- `_bm25_weights` at `fts.py:554`; `search_omni.py:2–11` promises "Never scan-on-type"; `Keyword` has only
  `idx_keyword_normalized_term` (`models.py:1112`); 406,723 keywords on the live corpus (`OPEN_QUEUE.md`,
  2026-09-09 entry — recorded, not measured here). First launch is `src/static/unlock.html`:
  `#view-language` → `#view-legal` → `#view-datadir` (grep-verified: `grep -o 'id="[a-z0-9-]*"'`).

## 3. Slices — what to build, in order

### S1 — The grammar behind a token class (Q603, Q604, Q612 + note, Q613)
- **What:** a token class emitting `word*`, `NEAR(a b, N)` (N default 10 from a user-changeable setting;
  the row's stepper overrides per query) and `title:`/`author:`; plain terms still through `_quote`;
  English operators only; regex recorded in the docstring as the deliberate omission.
- **Acceptance:** a parser table test; negative-space cases (FTS5 syntax smuggled inside a `title:` value
  or a `NEAR` argument) quoted or refused; the guard mutation-checked by name.

### S2 — Field search with a user-chosen match mode; fold by default with an exact toggle (Q611, Q610)
- **What:** `title:`, `author:`, `source:`, `url:`, `tag:`; per chip one compact mode — "starts with"
  (FTS5 prefix), "is exactly", "contains" — each explained in a hover ×12 with its cost ("contains" over
  `url`/`source`/`tag` is not an FTS5 operation: measure it, state it, never add an index silently). The
  exact toggle sits in the advanced search, explained in its hover; prototype both paths (§2), measure, wire.
- **Acceptance:** each path documented with its measured cost (n stated); `é` vs `e` differ only toggled.

### S3 — `ooTimeScope` as the one time component (Q609; Q601's "collected between")
- **What:** the timescale selector; wired into Advanced (replacing the two `type="date"` inputs), Markets,
  Insights; "published" and "collected between" (`created_at`) never coalesced.
- **Acceptance:** one component, three consumers, each in the Chromium record.

### S4 — The builder and the confirmed list (Q601, Q602, Q604, Q505, Q617, Q618)
- **What:** chips above the box, two-way with the compiled query; every Q601 field; language restriction
  here only (Q505); the sentiment caveat visible; word-count bands script-aware with the zh/ja/th note;
  include-quarantined advanced-only with the reason on each row (Q617); relevance default (Q618) with the
  ordering stated on every results header, table and export — a bm25-ordered list is not a sample frame
  (`LESSONS.md`, 2026-09-05); localised operator buttons compiling to canonical tokens.
- **Acceptance:** every ruled field reachable; strings ×12, caveats visible; no new inline handler.

### S5 — Views, permalinks, export parity, saved searches (Q615, Q616, Q607, Q606)
- **What:** list + sortable table (date, source, language, words, sentiment); the full state in the URL,
  re-opened after a restart; `/api/articles/export` taking the full S4 parameter set; `Watch` gains the
  full filter set and a saved search is a watch with `threshold = 0`, evaluated on the same compiled query.
- **Acceptance:** a permalink round-trip fixture; the export compared row-for-row with the filtered view
  on the reference corpus (ids and order identical, the ordering in the file header) — the gate's exit row;
  a saved search re-runs identically after a restart.

### S6 — "Did you mean", never a rewrite (Q605)
- **What:** the SymSpell-shaped table built by a task-manager job (deletes-within-2 over the keyword
  vocabulary); offered beside the literal results in the shape of `search_omni.py`'s `cross_language`
  disclosure block; the freshness caveat visible (unseen until the next build); no per-keystroke scan.
- **Acceptance:** the job's build cost on the reference corpus (rows, seconds, bytes) in the PR body.

### S7 — The omnibar's Enter (Q608) and local history (Q614 + note)
- **What:** Enter always opens the analysis window on the typed query; static commands need an explicit
  selection. History: local, private, default off, clearable, never exported; the opt-in offered as a view
  after `#view-legal` in `unlock.html`, copy ×12 with the caveat visible ("stored only on this machine").
- **Acceptance:** a driver test on Enter; default-off on a fresh install; clear empties the store; a
  negative-space fixture proves no export or diagnostics bundle carries it.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured — the two i18n
ratchets read out of `.github/workflows/ci.yml` (470 / 231 when this brief was written; grep-verified). Plus:
`node --check` on every touched `<script>` block; the three i18n gates for every new string; the whole-tree
guard set; the S1 negative-space fixture and its mutation check; each slice's named acceptance artifact; the
Chromium click-through record for `#tab-search`, the analysis window's Advanced subtab, the Watches panel and
the `unlock.html` opt-in view in `en` and `ar` (RTL) — "Chromium-verified (remote sandbox) · awaiting human
UX pass".

## 5. Operator steps

1. The maintainer's click-through of the four §4 surfaces on their machine (Q1128 = a) → the record on the PR.
2. Optional, `not-measurable-here`: the did-you-mean job on the live corpus, its cost beside the sandbox one.

## 6. What this slice may not decide

- The exact-match path (S2) and any "contains" index over `url` — measured and proposed in the PR body, never
  a silent dependency; no fourth grammar form, no table column beyond Q615's five, no regex (Q613).
- Where the user-changeable NEAR default lives — Q612's note says the user can change it, not where.
- Whether "never exported" (Q614) also keeps the history out of the backup members — proposed no; asked.
- Whether a threshold-zero watch also surfaces as a Lead card (Q606 is silent); what counts as "an explicit
  selection" of a static command (Q608 names the rule, not the gesture).

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
