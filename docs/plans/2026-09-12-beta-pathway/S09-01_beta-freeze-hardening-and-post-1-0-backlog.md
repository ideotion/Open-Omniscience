# S09-01 — Beta 1 = 0.9.0: the freeze, the hardening, the backlog · 0.9, `RELEASE_0.9_GATE.md` rows A–H

> **Scope:** `docs/product/RELEASE_0.9_GATE.md` §5 (the freeze list) and its row C section, a new
> `docs/product/POST_1.0_BACKLOG.md`, `.github/workflows/ci.yml` (the Windows lane) and `release.yml`
> (pre-release tags), the freeze guards, the row D hardening items, the security review report,
> `docs/SECURITY.md`. Must NOT: add a vertical or a lane (row A), push a tag (operator), land a
> non-additive migration, auto-install anything, decide Q1009 ⛔ (row F) or Q823 ⛔, write a date.
> **Implements:** Q101 ⛔ (answered = a), Q102, Q103, Q104, Q110, Q118, Q929, Q1019, Q1136, Q1138. Consumes,
> as the rows name them: Q111, Q1128, Q1001, Q902 note, Q814 (c), Q220, Q1131, Q1137, Q1135, Q613, Q718,
> Q903 / Q928, Q1009 ⛔ (blank).
> **Gated on:** the `v0.8.0` tag; the schema-freeze audit of `RELEASE_0.8_GATE.md` row B (row A's input);
> S08-02's bars; the Q903 resolution of 0.7 §3; V1-5 (V1 §3 amendment 4). Row F STOPS on Q1009 ⛔.
> **Sequencing:** A → H → G → D and E → C (written last, from the artifacts) → B (the tag, operator).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the whole
gate file named above (every row is this brief's), then every ruling in §1 as it stands in
`docs/ledger/RULINGS_INDEX.md`, then the sheet's §2 and §12 blocks for them, then `V1_PATHWAY_2026-07-14.md`
§3 and §8. Grep the tree first — the anchors were verified at `main`@`bebcef4` on 2026-09-12.

## 1. The rulings this slice implements — verbatim, by ID

- **Q101** ⛔ — **(a)** «(a) 0.9.0 = Beta 1, 0.9.x = later betas, 1.0.0 = general availability ("the
  gift").» [a ⛔ question ANSWERED — not pending; R18 finalised; the original «v1 = Beta 1» intent retired]
- **Q102** — **(a)** «(a) Features + schema (only additive migrations after 0.9.0) + backup format (every
  backup made since 0.9.0 restores forever) + the consent model.» (UI copy and translations may still move)
- **Q103** — **(b)** «(b) Public pre-release» — (a)'s invite-only `docs/BETA_TESTERS.md` was NOT chosen.
- **Q104** — **(b)** «(b) V1 §8 only.» — no field bar of N testers × 30 days ((a) not chosen).
- **Q110** — **(c)** «(c) No dates at all.» [placement note: «applies to every gate: no target dates»]
- **Q118** — **(a)** «(a) A `docs/product/POST_1.0_BACKLOG.md` created with the 0.9 gate, each item citing
  its ruling.»
- **Q929** — **(a)** «(a) Post-beta backlog» [placement note: «backlog; Q902 excluded (e)»]
- **Q1019** — **(a)** «(a) `pyosmium` wheels exist for Windows (FROM MEMORY); the lanes are in the Windows CI
  matrix from the release they land in, blocking at 0.9 per V1-5.» [placement note: «the lanes enter the
  Windows matrix from the release they land in»]
- **Q1136** — **(a)** «(a) Tags only, signed releases, an opt-in check that is consented like any egress,
  never auto-install.»
- **Q1138** — **(a)** «(a) Parked until 0.9's security review.»

Named by the rows (consumed, never re-decided): **Q111** = (a) «Tag + GitHub release notes generated from
`shipped.csv` since the previous tag + the no-telemetry re-check stated in the notes»; **Q1128** = (a);
**Q1009** ⛔ — blank (row F PENDING); row H's «never» list — Q220 = c, Q1131 = a, Q1137 = a, Q1135 = b,
Q613 = a, Q718 = a; its backlog items — Q902's note (bills and drafts post-beta), Q903 / Q928 as confirmed
in 0.7 §3; Q814 (c) NOT chosen (declined, not backlog). Labels for these stand in the sheet.

**Register round 2026-09-15 (D7, G9, I3, I4):** I3 = `default` (go, as its own skeptic-matrixed slice) CONFLICTS
with Q1138 = a (`RC14`); I4 = `default` (park) — consistent. G9's mechanics recorded for row E: re-run `install.sh`
on a snapshot; checksums stated until a key exists; no anchoring until then. D7 = `default`: pqcrypto stays `<1.0`
until a custody-path session with the full skeptic matrix.

**RC round 2026-09-15 — BLANK (0 of 22 `ANSWER` lines carry a letter); §0's blank rules applied, nothing resolved.** `RC14` → **ASSUMPTION (a) at 0.9 row E: Tor-exit-resolve
(SOCKS `RESOLVE 0xF0`) GOES, as its own skeptic-matrixed slice**, rather than staying parked. Both answers
land on this brief, so the difference is what it carries: a parked item is recorded and not built, while this
one is a small transport slice with the full skeptic matrix, closing the source-IP gap over Tor — under the
unchanged non-negotiables (no silent transport downgrade, no evasion of a host's block, transport-aware
verdicts). **I4 is unaffected:** `oo-netcut` and the Stem/Tor integration stay parked, where register I4 and
Q1138 agree. D7 (pqcrypto stays `<1.0` until a custody-path session with the full skeptic matrix) and G9 are
unchanged. The CONFLICT with Q1138 = a stays recorded on both index rows.

## 2. Where this stands in the tree — the staleness guard, with anchors

- grep-verified in this brief: `.github/workflows/ci.yml:366–379` — the `portability` job, matrix
  `os: [windows-latest, macos-latest]`, `continue-on-error: true` («observation lane: graduates to required
  when green»), `timeout-minutes: 45` with the PRH-29 note («the Windows leg HANGS — 3 h 21 m to failure»;
  a bisect against the suite is owed); `:416` `sqlcipher-smoke` already runs `windows-latest` blocking;
  `:191` `--max-untranslatable 470`, `:209` `--max-unkeyed-t-calls 231`; `:220–221` `alembic check`.
- `.github/workflows/release.yml:5–6` «No signing key yet (manual, checksums-only for now …)»; `:20–21`
  triggers on `v*` tags; `:111–112` marks every `0.*` tag `--prerelease`; `:136–140` `gh release create …
  --verify-tag`. `docs/FUTURE_DEVELOPMENTS.md:1010` the self-update section («MECHANICS ONLY»), `:1015`
  «trust root / signing key, so it cannot be completed unattended»; no self-update code under `src/`.
  `docs/ROADMAP.md:553–554` and `docs/plans/2026-09-06-repo-analysis/PROMPT_21_security-and-network.md` S4 /
  S5 hold the I3 / I4 designs; `grep -rn -i -E 'netcut|\bstem\b|exit-resolve' src/` finds nothing relevant.
- `tests/test_network_consent.py::test_no_new_socket_importers`, `::test_no_new_socket_capable_importers`,
  `::test_every_socket_importer_allowance_states_a_reason` (grep-verified) — the no-telemetry ratchet;
  `docs/legal/POLITIQUE_DE_CONFIDENTIALITE.md` ×12 carries the claim; `docs/SECURITY.md:25–27` the host list.
- `alembic.ini` → `migrations/`, 61 versions; backup identifiers `STREAM_KIND = "oo-volumes-2"`
  (`src/backup/stream_backup.py:102`), `VOLUME_KIND = "oo-volumes-1"` (`src/backup/volumes.py:38`),
  `BACKUP_SCHEMA` (`src/backup/folder_backup.py:455`) — re-read after 0.4 row K. No `pyosmium` in
  `pyproject.toml` (no `[geo]` extra at `bebcef4`; Q1019's wheels are FROM MEMORY).
- `src/monitoring/ui_walk_playwright.py:404` `run_axe` + registry `vendored-axe-core` (axe-core v4.13.0,
  `configs/external_artifacts.yml:507`); `docs/product/P0_VALIDATION_RUNBOOK.md`;
  `docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md`; row D's «three widths» are the 2026-09-09 axe sweep recorded in
  `RELEASE_0.4_GATE.md` §3 (1440×900, 768×1024, 390×844 — grep-verified: `grep -n '2026-09-09'
  docs/product/RELEASE_0.4_GATE.md`; no audit document carries that date);
  `docs/process/IMPROVEMENT_CYCLE.md` (row C item 7). `POST_1.0_BACKLOG.md` and `docs/BETA_TESTERS.md` do
  not exist. The clone is shallow here — `git fetch --unshallow` before notes from `shipped.csv` (CLAUDE.md 5b).

## 3. Slices — what to build, in order

### S1 (row A) — The freeze list and its guards
- **What:** `RELEASE_0.9_GATE.md` §5 completed under its ruled headings — features (the lanes, the five
  verticals at their 0.8 scope, the advanced search, the spine and dossier, the maps at their 0.7 scope; no
  additions after `v0.9.0`), schema (additive only; the tables of 0.8 row B's audit), backup format (the
  identifiers at `v0.9.0`; every backup since restores forever; the restore normalisers stay), the consent
  model (the one popup + per-lane hover, the airplane guarantee, the transports that never downgrade, the
  OTS and Wikidata consents), still moving (copy, ×12, typos). Two guards: a format-version test that fails
  on a non-additive backup-format change, and a guard beside `alembic check` that reddens on a dropped
  column or table after the freeze commit. «Your data survives every beta» ×12 wherever shown.
- **Why (ruling):** Q101 ⛔ = a; Q102 = a. **Acceptance:** «the list exists in this file (§5), the
  format-version test exists, and the `alembic check` ratchet is joined by a guard …» — both guards
  mutation-checked. **May not decide:** Q1009 ⛔ (row F); Q823 ⛔ (if blank, OSM data stays inside; say so).

### S2 (row H) — `docs/product/POST_1.0_BACKLOG.md`
- **What:** the file, each item citing its ruling id in `RULINGS_INDEX.md`: all-twelve-edition full text
  (V1-9), rosters + poll Tier-2 (V1-8), case law with ECLI identity (Q929 = a), bills and drafts as a
  separate lifecycle (Q902 note), subnational law beyond 0.7's reach (Q903 / Q928 as confirmed), whatever 0.8
  §3 cut; a «ruled never — not backlog» section (Q220 = c, Q1131 = a, Q1137 = a, Q1135 = b, Q613 = a,
  Q718 = a) and «declined, not backlog» (Q814 (c) ohsome); a small repo test that every cited id resolves.
- **Why (ruling):** Q118 = a. **Acceptance:** «the file exists and every item resolves to a ruling id».
  **May not decide:** any item's priority or release.

### S3 (row G) — The Windows lane BLOCKING
- **What:** the `windows-latest` leg leaves `continue-on-error` — split the `portability` matrix so Windows
  blocks and macOS stays an observation lane (V1-5); the PRH-29 hang bisected FIRST (a lane that hangs to a
  45-minute timeout cannot block honestly); the lanes' extras in the Windows matrix from the release each
  landed in (verify the `pyosmium` wheels when `[geo]` enters); the artifact is a GREEN run on THIS tag's SHA.
- **Why (ruling):** Q1019 = a; V1-5; V1 §8 item 8. **Acceptance:** «`ci.yml` carries the lane without
  `continue-on-error` and it is green on the tagged tree». **May not decide:** graduating macOS.

### S4 (row D) — The hardening items
- **What:** `--audit-chrome` → 0 (the two `ci.yml` ratchets driven down, strings keyed in the same commits);
  the a11y pass via `run_axe` at the three widths of the recorded sweep across the surviving themes (0.5 row
  I's cull); the scale re-validation (the P0 runbook on the live corpus — operator); docs / manual
  completeness with the reciprocity swept; the install-paths decision executed (Debian first-class; Windows
  per V1-5; macOS best-effort) → the install matrix in the release notes.
- **Why (ruling):** V1 §3's 0.9 row; V1-5; K11, K12. **Acceptance:** «the ratchet at 0 in `ci.yml`, the
  axe sweep report, the P0 report, the reciprocity sweep's list of corrections, the install matrix».
  **May not decide:** an a11y bar beyond «zero violations named or waived with the reason».

### S5 (row E) — The security review
- **What:** a written report (under `docs/audit/`, named in the PR), one finding per item: I3
  Tor-exit-resolve and I4 `oo-netcut` / Stem (parked here by Q1138 — the finding is build / decline /
  park-post-1.0 with the reasoning; the RULING is the maintainer's); self-update per Q1136 — tags only,
  signed releases (no signing key exists: the key and trust root are the precondition the review names), an
  opt-in check consented like any egress (a NEW `docs/SECURITY.md` line + hover for the purpose, Q1001),
  never auto-install; the no-telemetry re-check (the socket ratchet run, the outbound call sites re-read,
  stated in the notes); the SSRF and airplane guards re-verified against every host added since 0.3.
- **Why (ruling):** Q1136 = a; Q1138 = a; Q111 = a; the CLAUDE.md per-release ritual; NET-01's guard.
  **Acceptance:** «the review's report exists with each item's finding and the re-check is stated in the
  notes». **May not decide:** whether I3 / I4 are built; who signs and with what key.

### S6 (row C) — The V1 §8 exit bar, item by item
- **What:** the eight items written into the gate's row C, each green with its artifact or named-open with
  what is missing: 1 data safety · 2 performance · 3 coverage (elections at CALENDAR scope, patents only if
  cleared, laws + ≥ 1 full Wikipedia edition with the scaling machinery) · 4 investigation (the dossier ≥ 6
  rails, the Conjunction Lens) · 5 language (K11, `--audit-chrome` 0) · 6 honesty (the transversal audit
  repeated, zero disclosure gaps) · 7 verification (K12 100 % under Q1128; the improvement cycle ≥ 6
  consecutive published reports) · 8 install (≤ 15 min on a fresh Debian; uninstall + backup round-trip;
  Windows blocking, macOS best-effort). No field bar.
- **Why (ruling):** Q104 = b; V1 §8; Q1128 = a. **Acceptance:** «each item is marked green with its
  artifact or named-open with what is missing». **May not decide:** that 1.0.0 ships (the maintainer's read).

### S7 (row B) — The public pre-release (operator-closed)
- **What:** the session prepares the release notes from `shipped.csv` since the previous tag (after
  `git fetch --unshallow`) with the no-telemetry statement and the install matrix, and — *proposed*,
  declinable in §3 — `docs/BETA_TESTERS.md` (the freeze list, the data-safety promise, how to report);
  public, no accounts, no telemetry. The maintainer cuts `v0.9.0-beta.1` (the `0.*` rule already marks it
  a pre-release); checksums only until a signing key exists, said honestly in the notes.
- **Why (ruling):** Q103 = b; Q111 = a; the hosting stance. **Acceptance:** «the first pre-release tag
  exists with those notes and the report-format document (or its recorded decline)». **May not decide:**
  the tag (never pushed by a session); the report document (proposed).

### Row F — PENDING on Q1009 ⛔
- STOP. If ruled before this release, the row closes on the executed rulings' artifacts; if not, the beta
  ships on the existing store and the row records what that means for the wiki tail walk's depth (0.5 row
  F) and the ≥ 100 GB bar (V1 §8 item 1). A decision, not work — the maintainer's.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured — the i18n numbers read out of
`ci.yml` at the time. Plus: the two freeze guards mutation-checked by name (bump the format identifier
non-additively → red; drop a column in a scratch migration → red; restore); the socket-importer ratchet
(the three tests above) as the no-telemetry evidence, the outbound call sites listed in the PR body; the
backlog's id-resolution test; `node --check` on touched script blocks; the three i18n gates for every new
string; the whole-tree guard set; the axe sweep at the three widths; the Chromium click-through record
(Q1128 = a) of the flagship flows (K12: 100 % of surfaces) in `en`, `ar` (RTL), `zh`, `hi`, then the human
UX pass; and the one artifact no sandbox run replaces — a green Windows lane on the tagged SHA.

## 5. Operator steps

1. Q1009 ⛔ (row F): the maintainer rules or leaves it — a decision, not work; the row records either way.
2. The signing key and trust root for Q1136's «signed releases» — the maintainer's decision, named by the
   review as the precondition.
3. The P0 runbook on the live corpus (row D's scale re-validation; row C item 1) → the P0 report; the
   Windows lane's green run on the tag's SHA (row G), observed after the tag.
4. `v0.9.0-beta.1` tagged from the maintainer's machine with the prepared notes (the session git proxy
   refuses tag pushes); `docs/BETA_TESTERS.md` accepted or declined in §3.
5. The human UX pass on the flagship flows (row C item 7); the `pyosmium` Windows wheels confirmed (FROM
   MEMORY) when the `[geo]` extra enters the matrix; the cut-or-delay decisions carried from 0.8 §3.

## 6. What this slice may not decide

- **Q1009 ⛔** (row F) and **Q823 ⛔** — never defaulted; the freeze list states what ships without them.
- **I3 / I4** — the review reports; building or declining is the maintainer's word (Q1138 parked them, it
  did not approve them). **The signing key** — Q1136 says signed releases; the key, its holder and rotation
  (`FUTURE_DEVELOPMENTS.md:949`, `:1015`) are not a session's to create. **`docs/BETA_TESTERS.md`** —
  proposed (the sheet's (a) named it; (b) did not exclude it); declinable.
- **The beta cadence** and **1.0.0's moment** — gate-driven, no dates (Q110 = c); 1.0.0 needs all eight §8
  items green (Q104 = b) and «nothing else». **macOS** stays best-effort (V1-5).

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate rows' status in `RELEASE_0.9_GATE.md` §3 (the amendment log), with the artifact that closes each.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
