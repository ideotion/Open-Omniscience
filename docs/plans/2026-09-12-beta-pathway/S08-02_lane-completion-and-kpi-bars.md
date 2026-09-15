# S08-02 — Lane completion and the KPI bars · 0.8, `RELEASE_0.8_GATE.md` row B

> **Scope:** `src/monitoring/kpi.py` (`_SPECS`, `_RESOLVERS`, the `measured-no-bar` verdict) and
> `scripts/kpi_diff.py`, the lanes' coverage / freshness resolvers (wiki: S06-03's report; OSM: S06-01's
> member; law: S06-02's report), a KPI surface that renders the bars, the Help tranches of S06-05, the
> schema-freeze audit (`migrations/versions`, `alembic check`, the backup format identifiers), the gate
> files' §3. Must NOT: set a bar without recorded values; land a non-additive migration after this release;
> add a vertical or a lane; build the lanes' breadth itself (S07-02, S07-03, S06-03 build; this slice
> verifies and records).
> **Implements:** Q1017 (placement: «measured first; each lane ships its resolver from 0.4»). Consumes, as
> the gate row names them: Q106, Q107, Q108, Q1122, Q102, Q118.
> **Gated on:** the `v0.7.0` tag; S06-01 / S06-02 / S06-03 (the resolvers and the recorded values across at
> least one release); S06-05 (the first tranche); S07-02 / S07-03 (the 0.8 breadth); the Q903 CONFLICT
> resolved in `RELEASE_0.7_GATE.md` §3; Q1009 ⛔ bounds the wiki depth; Q823 ⛔ shapes the freeze note.
> **Sequencing:** the last row before the beta; the schema audit is written LAST, after every lane's tables
> exist; the runs whose values set the bars are the operator's.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then Q1017 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's §11 context
and its Q1017 block, then `V1_PATHWAY_2026-07-14.md` §2.3 and §7 (V1-6). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q1017** — **(a)** «(a) Measured first (V1-6): each lane ships its coverage/freshness resolver; bars are
  set only after a release has recorded values.» [placement note from the JSON: «measured first; each lane
  ships its resolver from 0.4»]

Named by the gate row, quoted from the sheet (consumed, not re-decided):
- **Q106** = (a) «… 0.7–0.8 widen to more countries.» · **Q107** = (a) «… 0.7–0.8: the rest of the world +
  subnational.» · **Q108** = (a) «… 0.6: the coverage report per edition.»
- **Q1122** = (b) «(b) Translate the 167,022-character body ×12» — «finished» here per S06-05's staging.
- **Q102** = (a) «(a) Features + schema (only additive migrations after 0.9.0) + backup format (every backup
  made since 0.9.0 restores forever) + the consent model.» — this gate is «the last release in which a
  schema change may be non-additive».
- **Q118** = (a) — `POST_1.0_BACKLOG.md` at 0.9, where a lane cut from the beta scope is written.
- V1 §7 V1-6 (ruled 2026-09-07): «SET BARS ONLY WHERE MEASURED, DEFER THE REST — which today sets none:
  K5/K7/K8 have no resolver in `kpi.py:_RESOLVERS` and K6 has never recorded a value»; V1 §2.3: «Numeric
  bars marked *placeholder* are proposals for ruling V1-6 — the maintainer tunes them».

## 2. Where this stands in the tree — the staleness guard, with anchors

- grep-verified in this brief: `src/monitoring/kpi.py:340` `_RESOLVERS = {"K2": …, "K6": …, "K11": …}`;
  `:55` `_NO_BAR = "measured-no-bar"` («the figure IS known and the numeric bar is still a ruling»);
  `:80–93` K5–K8 carry `target: "pending-ruling-V1-6"`; `:112–114` K13 «Vertical coverage»,
  `source_endpoint: /api/diagnostics/freshness`; `:52` `_SCHEMA = "oo-kpi-1"`; `run_kpi_selftest` at `:373`.
  `scripts/kpi_diff.py` exists (the differ). `grep -rln 'api/diagnostics/kpi' src/static/` — NO static-file
  consumer reads the KPI snapshot: the board is JSON + the bundle today, and the row's «the KPI board shows
  each lane's bar … with the method on hover» needs a rendering surface that does not exist (see §6).
- `alembic.ini` `script_location = migrations`; `ls migrations/versions | wc -l` = 61; `ci.yml:220–221` runs
  `alembic upgrade head` and `alembic check` under `OO_DB_PLAINTEXT: "1"`. Backup format identifiers today:
  `src/backup/stream_backup.py:102` `STREAM_KIND = "oo-volumes-2"`, `src/backup/volumes.py:38`
  `VOLUME_KIND = "oo-volumes-1"`, `src/backup/folder_backup.py:455` `BACKUP_SCHEMA` — 0.4 row K bumps them
  once; re-read at 0.8, the audit records the values the freeze will pin.
- `src/api/main.py:2557–2609` `_DOCS` lists ten Help documents; `docs/i18n/fr/QUICKSTART.md` is the one
  translated draft at `bebcef4`; S06-05's tranches change this — re-count.
- `docs/product/RELEASE_0.8_GATE.md` §1: «a lane that has not reached its breadth by the 0.8 exit is
  either cut from the beta scope (recorded in `POST_1.0_BACKLOG.md`, Q118) or delays it — the maintainer's
  call, made in §3 with the numbers».

## 3. Slices — what to build, in order

### S1 — Every lane's resolver in `_RESOLVERS`, reading recorded values
- **What:** a resolver per lane (wiki coverage from S06-03's member, OSM tracking from S06-01's member, law
  coverage from S06-02's report) registered in `src/monitoring/kpi.py:_RESOLVERS`, each reading a PERSISTED
  value with its `as_of`, `n` and method — never running an expensive scan on the GET (the K5–K8 rule) —
  and reporting `measured-no-bar` while its target is unset; a lane with no recorded run is
  `not-measurable-here` with the reason.
- **Why (ruling):** Q1017 = a; V1-6; the kpi module's own verdict grammar.
- **Acceptance:** the snapshot carries the three lanes with values; `run_kpi_selftest` green.
- **May not decide:** a bar (S2).

### S2 — The bars, set from recorded values
- **What:** for each lane metric with values recorded across at least one release (the KPI snapshots diffed
  by `scripts/kpi_diff.py`): the bar written into the spec's `target` as a NUMBER with its provenance (which
  run, which corpus, which date, which machine) and the direction unchanged; the method on hover ×12; the
  maintainer tunes the numbers in the gate's §3 (V1 §2.3). A metric without a recorded value keeps
  `pending-ruling-V1-6`.
- **Why (ruling):** Q1017 = a; V1-6; V1 §2.3.
- **Acceptance:** the row's «the KPI board shows each lane's bar beside its recorded values with the method
  on hover» — on a rendering surface (see §6 for its placement).
- **May not decide:** the numbers without values; the surface's placement.

### S3 — Lane completion verified and recorded, not built
- **What:** the OSM lane at «more countries» (Q106; S07-02's measured figures), the law lane at «the rest
  of the world + subnational» (Q107; S07-03's report), the wiki lane's coverage report + the walk's measured
  depth (Q108; 0.5 row F) — each lane's reached breadth recorded as numbers in the gate's §3; a lane short of
  its breadth is reported with the number for the maintainer's cut-or-delay call.
- **Why (ruling):** Q106 / Q107 / Q108; the gate's exit clause.
- **Acceptance:** the numbers in §3; the PR body's honest carry-over.
- **May not decide:** the cut-or-delay call.

### S4 — Help ×12 finished
- **What:** S06-05's remaining tranches shipped under the same test and banner; the coverage reads 12/12 on
  every document in `_DOCS`; the live locale switch recorded.
- **Why (ruling):** Q1122 = b; the 0.6 row E staging.
- **Acceptance:** the row's «the Help coverage reads 12/12 on every document».
- **May not decide:** native review (flagged, not gated).

### S5 — The schema-freeze audit (data safety: the full skeptic matrix)
- **What:** a written audit (a `docs/` document the PR names) listing every table and column the lanes,
  the verticals and the dossier added or still expect to add, the migration after which only additive ones
  follow, the backup format identifiers at their post-0.4 values, the restore normalisers of 0.4 row K and
  0.5 rows B/J; every pending column lands here or is declared additive. Adversarial passes with the
  data-loss and negative-space lenses; a real restore of a pre-audit backup into the post-audit schema is
  the operator's proof, `not-measurable-here` in the sandbox.
- **Why (ruling):** Q102 = a; the gate's «this is the last release in which a schema change may be
  non-additive»; the 0.9 row A input.
- **Acceptance:** the row's «a written schema-freeze audit lists the tables and the migrations after which
  only additive ones follow».
- **May not decide:** the freeze's guard test (0.9 row A builds it); Q1009 ⛔'s store changes.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured — `alembic upgrade head &&
alembic check` is the one this slice cannot afford to skim. Plus: the KPI selftest; `node --check` on the
touched script blocks; the three i18n gates for every new string (the bar labels and method hovers, the
12/12 banner, the audit's UI note if any); the whole-tree guard set (a new `docs/` file reddens
`test_utf8_file_io` if not UTF-8); the schema audit's skeptic matrix (mutation-check: drop one column from
the audit's list → the audit's cross-check with the live schema reddens by name); the Chromium
click-through record (Q1128 = a): the KPI surface with each lane's bar beside its values and the method on
hover, Help in the twelve locales at 12/12 — in `en`, `ar` (RTL), `zh`, `bn`; then the maintainer's pass.

## 5. Operator steps

1. The runs whose values set the bars — each lane on the live corpus (the maintainer's machine); the KPI
   snapshots kept for `kpi_diff.py`.
2. The maintainer tunes the bar numbers in `RELEASE_0.8_GATE.md` §3 and makes the cut-or-delay call per
   lane, with the numbers.
3. A real restore of a pre-audit backup into the post-audit schema (`not-measurable-here` in the sandbox) →
   the audit's proof line.
4. The click-through pass on the surfaces in §4.

## 6. What this slice may not decide

- **The bar numbers** — set only from recorded values and tuned by the maintainer; a session never invents
  one (V1-6, Q1017).
- **Where the KPI board renders** — no surface reads `/api/diagnostics/kpi` today (grep-verified); the row
  needs one. Proposed in a NOTE for the maintainer: the task-manager window's System tab (invariants #4 and
  #20 put vitals there) — a proposal, not a ruling; the JSON snapshot and the bundle stay the record.
- **The cut-or-delay call**, **Q1009 ⛔** (the wiki depth), **Q823 ⛔** (the freeze note says OSM data stays
  inside the machine if still blank) — the maintainer's.
- **What «0.8 breadth» is numerically** — Q106 / Q107 say «more countries» / «the rest of the world»; no
  count is ruled; the numbers are recorded, not judged.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.8_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
