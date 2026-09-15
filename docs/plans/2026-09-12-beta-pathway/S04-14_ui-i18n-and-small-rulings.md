# S04-14 — UI, i18n and the small rulings · 0.4, `RELEASE_0.4_GATE.md` row U

> **Scope:** the locale files under `src/static/locales/` and the `app-*.js` markup the 470 strings live in, the
> `ci.yml` i18n ratchets; the religious-calendar / eclipse-canon feature (`src/events/astronomy.py`,
> `src/events/feeds.py`, `configs/calendar_feeds.yml`, `configs/world_timeline.yml`, the agenda category);
> `scripts/ui_clickthrough_run.py` / `ui_clickthrough_seed.py`; `src/api/diagnostics.py` → a package;
> `docs/FUTURE_DEVELOPMENTS.md`; the newsletter attach (`src/ingest/newsletter_source.py` + its import UI);
> `src/ai_layer/source_tags.py`; the Patterns lens toggle. NOT: flipping the Patterns lens, retiring inline
> handlers (Q1127, 0.5), culling themes (Q1123, 0.5), translating Help (Q1122), changing any route's path.
> **Implements:** Q1124, Q1130, Q1135, Q1139, Q1141, Q1149, Q1151, Q1152.
> **Gated on:** nothing PENDING; Q1124's flip needs an operator-labelled sample it will not get in 0.4.
> **Sequencing:** the `diagnostics.py` split (S4) before any other slice adds a diagnostics route; the i18n
> remainder (S1) after the other 0.4 UI slices land, so their strings are counted once.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§12, whose context is the 2026-09-06 register's G8, J1, A4, L7, M4, M5, L10
and the 2026-09-08 visual audit's Q-VIS-6). Grep the tree before building anything — the sheet's anchors were
verified at `main`@`bebcef4` on 2026-09-12 and may have moved; this brief re-checked them at `7ca142e`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q1124** — **(a)** «Flip on only when the corpus is ≥ 100 k articles and a labelled sample shows a
  false-positive rate ≤ 5%; both numbers on the toggle.» [flip only when measured]
- **Q1130** — **(a)** «Filter only the `via:*` provenance prefixes from topical displays; keep the rest
  reported.»
- **Q1135** — **(b)** «Drop the feature.»
- **Q1139** — **(a)** «Authorise the mechanical split into a package, routes unchanged.»
- **Q1141** — **(a)** «Full: every section re-checked against the tree, stale claims corrected.»
- **Q1149** — **(a)** «Add an encrypted variant to the runner.»
- **Q1151** — **(a)** «Go»
- **Q1152** — **(a)** «Fund it in 0.4.»

**Register round 2026-09-15 (A4, G8, J1, L1, L3, L5, L7, L10):** A4 = `default` (b): banner + archive, never merge
— the actions for Q1141 = a's depth. G8: «I won't provide the dates. Let's create a dedicated internet connected
session to search for all religious dates and implement them in the app» CONFLICTS with Q1135 = b (`RC13`): build
nothing for the feature until confirmed. L10 = `default` (filter `via:*` AND the coverage-state prefixes)
CONFLICTS with Q1130 = a (`RC17`). J1 = Q1139, L7 = Q1149 — consistent; L1 (keep) and L3 (leave) — no change.
L5 (extend `_SPARSE_BAR_MAX` to the commodity overlay only) is proposed for this slice (`RC08.6`).

## 2. Where this stands in the tree — the staleness guard, with anchors

- The ratchets: `.github/workflows/ci.yml:167` `--min 100`, `:191` `--max-untranslatable 470`, `:209`
  `--max-unkeyed-t-calls 231` — grep-verified. The 470 IS the remainder (register M5: whole sentences 0 of 80;
  about 150 begin lowercase — an upper bound on fragments split by inline markup across the `app-*.js`
  modules; "no tidy breakdown of the 470 is published on purpose").
- `src/api/diagnostics.py` is 6,741 lines with 131 `@router.<verb>` decorators today (grep-verified); the
  sheet recorded 6,200 / 126 and the register 6,312 / 129 on 2026-09-11 — it grows weekly. Route guards anchor
  to the router definitions, never the app singleton's live route table (the CLAUDE.md lesson).
  `tests/test_all_diagnostics_reachable.py` and `tests/test_all_diagnostics_job.py` exist (grep-verified).
- `docs/FUTURE_DEVELOPMENTS.md` is 3,009 lines (grep-verified); register A4 (verified 2026-09-11): 51 `## `
  sections, 19 stale "designed-only" claims, three duplicate pairs (§1/§22, §35/§43, §2/§49), four embedded
  ledgers; protocol rule (5) forbids compressing away a ruling.
- The calendar feature: `src/events/astronomy.py` (Meeus ch. 49 lunar phases, local, imported by
  `src/api/events.py:247,295`), `src/events/feeds.py:44–66` ("the local Meeus astronomy already covers
  moons/eclipses"), `configs/calendar_feeds.yml:3288` "Astronomy — eclipses, moons, solstices, meteor
  showers", `configs/world_timeline.yml:246–259` two eclipse rows, `app-agenda.js:959` the `religious`
  category hue, `src/catalog/taxonomy.py:30` a `religious` SOURCE tag (a different thing) — grep-verified.
  The superseded ruling: `OPEN_QUEUE.md` ~4044 "(9) RELIGIOUS CALENDARS / ECLIPSE CANON = maintainer will
  PROVIDE the dates to preload" (2026-06-17).
- The click-through runner: `scripts/ui_clickthrough_run.py` (env `OO_UIWALK_IMPORT_ARTIFACT` /
  `OO_UIWALK_IMPORT_PASS` at `:50–51`); `scripts/ui_clickthrough_seed.py:8–13`: state A boots WITHOUT
  `OO_DB_PLAINTEXT` (genuinely locked), state B with it — grep-verified. The seeded, walked states are
  plaintext.
- The newsletter attach: `src/ingest/newsletter_source.py:29–38` docstring ("The ruling pairs silent
  auto-attach with a dedicated import UI that announces it and an UNDO"); `OPEN_QUEUE.md` ~4478–4526: "STILL
  OPEN, unchanged: the write-path auto-attach, then the import UI + undo, in that order"; register M4: the
  provenance column shipped (`cc8d8651`) — grep-verified.
- `via:*`: `src/ai_layer/source_tags.py:441` `_NON_TOPICAL_CLASSES` with `"provenance": ("via:",
  "world-catalog")`, annotated "Reported, never filtered" (register L10: a change to a stated position);
  `src/catalog/provenance_scope.py:44,71` build the `via:` tags — grep-verified.
- The Patterns lens: the manipulation-pattern cards at `src/api/insights.py:1998–2067`, the flood / bury
  buttons at `src/static/index.html:2683–2687`; default-OFF per
  `docs/design/UI_COMPLEXITY_AND_AUTOMATION_PLAN_2026-09-08.md:234,249` (AMBER); no element with a `patterns`
  id exists (grep-verified) — the "toggle" that carries the two numbers must be located or created.

## 3. Slices — what to build, in order

### S1 — The i18n remainder
- **What:** the 470 strings keyed ×12, including the markup surgery where a fragment is split by inline markup
  (one module per commit); `--max-untranslatable` lowered by the MEASURED amount in the same PR,
  `--max-unkeyed-t-calls` never raised; the LESSONS rule on ratchet calibration (a number is a fact about the
  tree that carries it); Arabic RTL checked; non-en strings flagged AI-drafted for native review.
- **Why:** Q1152. **Acceptance:** the three gates green at the lowered numbers (gate).

### S2 — Drop the religious calendars and the eclipse canon
- **What:** remove the feature and NAME the loss in the PR: the astronomy feed family in `calendar_feeds.yml`,
  the eclipse rows in `world_timeline.yml`, the "you will provide the dates" promise (record ruling 9 of
  2026-06-17 as superseded in `OPEN_QUEUE.md`), its i18n keys (the ratchet lowers) and its tests; the agenda's
  OTHER categories untouched (gate); the `religious` SOURCE tag is not the feature. Whether `astronomy.py`'s
  lunar phases and seasons are part of "the feature" is open (§6).
- **Why:** Q1135 = b. **Acceptance:** the removal PR names what went (gate); the agenda Chromium-verified.

### S3 — The encrypted click-through variant, and the `diagnostics.py` split
- **What:** the runner gains an encrypted run of the seeded, walked states (state A is already locked); the
  passphrase arrives by env like `OO_UIWALK_IMPORT_PASS`; the record stamps which state ran encrypted. The
  split: mechanical, into `src/api/diagnostics/`, routes unchanged (paths, methods, names), proven by a
  route-table equality test read from the ROUTER DEFINITIONS before and after — never `app.routes`; the
  all-diagnostics tests stay green; `tests/test_import_graph.py`'s cycle ceiling stays 0.
- **Why:** Q1149, Q1139. **Acceptance:** one encrypted run recorded; the route-equality test exists (gate).

### S4 — The `FUTURE_DEVELOPMENTS.md` reality check
- **What:** every section re-checked against the tree; stale claims corrected in place with the anchor that
  proves the state (VERIFIED-PRESENT / half-shipped — say which half); duplicate pairs cross-linked, never
  merged (rule (5)); the PR lists every corrected claim.
- **Why:** Q1141. **Acceptance:** the PR's list (gate). Archiving the embedded ledgers is open (§6).

### S5 — The newsletter attach (data safety: full skeptic matrix)
- **What:** in the recorded order — the write-path auto-attach on a deterministic eTLD+1 / alias hit, the
  import UI that ANNOUNCES it, the UNDO — as one coherent slice, never the attach alone; articles move between
  sources, so the data-loss and negative-space lenses (a near-miss alias never attaches; an undo restores
  placement exactly); ×12, caveat visible.
- **Why:** Q1151 = a "Go" on M4's sequencing. **Acceptance:** fixture + Chromium-verified UI.

### S6 — `via:*` only, and the Patterns lens numbers
- **What:** the `via:*` provenance prefixes filtered from topical displays; coverage-state and stance classes
  stay "Reported, never filtered"; the module comment records the change of position. The lens: no flip in
  0.4; its on/off surface shows the corpus count against ≥ 100 k and the false-positive rate against ≤ 5 % as
  "unmeasured" (absent, never 0) until a labelled sample exists (§5); ×12.
- **Why:** Q1130, Q1124. **Acceptance:** a test that only `via:*` is filtered; the toggle text
  Chromium-verified.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured; the three i18n
gates run separately at the numbers read from `ci.yml` after S1 lowers them; `node --check` on every touched
script block; the whole-tree guard set after the package split; the route-equality test; the full skeptic
matrix on S5 with mutation checks; the Chromium click-through record (Q1128 = a) of the agenda after S2, the
newsletter import UI + undo, the lens toggle, and a 12-locale sweep of the surfaces S1 touches (ar RTL); the
encrypted runner record; the `shipped.csv` numstat + duplicate scan.

## 5. Operator steps

1. A labelled sample for the Patterns lens's false-positive rate on a corpus ≥ 100 k articles (the ~1M
   instance) — the number that would allow a flip; `not-measurable-here`.
2. The newsletter attach + undo tried on a real mailbox import on the maintainer's machine;
   `not-measurable-here`.
3. The click-through of the surfaces named in §4 (Q1128 = a).

## 6. What this slice may not decide

- **What "the feature" spans** in Q1135 — the eclipse canon and religious calendars go; whether the Meeus lunar
  phases / seasons in `astronomy.py` go with them is stated in the PR, not assumed.
- **Archiving the four embedded ledgers** in `FUTURE_DEVELOPMENTS.md` (register A4's option (b)) — Q1141 = a
  rules the re-check, not the archive; ask.
- **Which element hosts the two numbers** for Q1124 — located or created, named in the PR; **the flip itself**
  — only when measured, not in 0.4. Q1127 / Q1123 / Q1122 are other rows.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
