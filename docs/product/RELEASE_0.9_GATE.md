# Release gate — v0.9.0 · Beta 1 (the hardening RC)

> **PROVISIONAL ON THE V1 ROUND (`RC11` = b, 2026-09-29).** The maintainer re-opened all nine V1 rulings of
> 2026-09-07 (V1-1..V1-9): every row of this gate that cites a V1 ruling is provisional until the detailed V1 round
> is written and answered. V1-4 is already answered: PubMed BULK over the API («pubmed bulk prefered over API»).

**Status: OPEN — written 2026-09-15 from the answered roadmap sheet.** The checkable inventory for closing the
`0.9` cycle. **0.9.0 = Beta 1, 0.9.x = later betas, 1.0.0 = general availability ("the gift"); alphas are
0.4–0.8** — ruled **Q101 ⛔ = a** (R18 finalised; the maintainer's original intent, v1 = Beta 1, is retired with
that answer). Written now under Q112 = a / Q1204 = a from
[`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
indexed in [`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md).

**What is ruled here and what is not.** The theme is the approved V1 train's "hardening RC" (`V1_PATHWAY_2026-07-14.md`
§3, ruled 2026-09-07, amendment 4: the `windows-latest` CI lane graduates to BLOCKING, V1-5). The beta's
shape is the sheet's: what it freezes (Q102), who tests it and how (Q103), what lets 1.0.0 ship (Q104), how
tags are cut (Q111), where the post-1.0 ambitions are written (Q118), the security items parked until here
(Q1136, Q1138), the lanes in the Windows matrix (Q1019). **No target date** (Q110 = c) — the beta ships when
this board is green, and 1.0.0 ships when the V1 §8 checklist is green, **and nothing else** (Q104 = b: no
field bar of N testers × 30 days — the sheet's (a) was not chosen). The one ⛔ still blank that touches this
board, **Q1009 (the storage round-2 rows 3–6)**, is named on row F and never assumed — **answered (a) 2026-09-29, `y, OOENC2, y, y`.**

**How a row closes:** a named artifact; `not-measurable-here` where the sandbox cannot measure; the
verification bar is Chromium + the maintainer's click-through (Q1128 = a); V1 §8 item 7's "Gecko-verified"
wording is read under that ruling (Gecko best-effort).

**Entry.** `v0.8.0` tagged; the schema-freeze audit of `RELEASE_0.8_GATE.md` row B written.

---

## 1. The board

| # | Row | Owner | Origin | Status |
|---|---|---|---|---|
| A | The freeze list written and enforced: features + schema (additive migrations only) + backup format (every backup since 0.9.0 restores forever) + the consent model; copy and translations may still move | session | ruled (Q101 ⛔ = a, Q102 = a) · brief `S09-01` | **OPEN** |
| B | The public pre-release: `v0.9.0-beta.1` … tags anyone may download; no accounts, no telemetry; the report format published | operator + session | ruled (Q103 = b; Q111) · `S09-01` | **OPEN** |
| C | The exit bar = the V1 §8 acceptance checklist, item by item, with the state of each | shared | ruled (Q104 = b) · `S09-01` | **OPEN — written 2026-11-20**: no item green yet; item 5's K11 half green (§2 row C, the state table) |
| D | The hardening items of the V1 train: `--audit-chrome` → 0, the a11y pass, scale re-validation on the live corpus, docs / manual completeness, the install-paths decision executed | session + operator | V1 §3 (ruled 2026-09-07) · `S09-01` | **OPEN** |
| E | The security review: Tor-exit-resolve and `oo-netcut` / Stem (parked here by Q1138); the consented self-update check (Q1136); the no-telemetry re-check stated | session + operator | ruled (Q1136 = a, Q1138 = a) · `S09-01` | **OPEN** |
| F | The storage rulings executed (Q1009 = a) | maintainer | the intake's 0.9 line; Q1009 ⛔ answered 2026-09-29 | **OPEN — unblocked 2026-09-29** (Q1009 = a, `y, OOENC2, y, y`) |
| G | The Windows lane BLOCKING, with every lane that landed in the matrix | session | V1-5; ruled (Q1019 = a) · `S09-01` | **OPEN** |
| H | `docs/product/POST_1.0_BACKLOG.md` created, each item citing its ruling | session | ruled (Q118 = a) · `S09-01` | **CLOSED 2026-11-20** — the file and `tests/test_post_1_0_backlog.py` (PR #NNNN) |

**The exit (Beta 1).** `v0.9.0-beta.1` is tagged when rows A, B, D, E, G, H are CLOSED on named artifacts,
row C is WRITTEN with every V1 §8 item's state (green or named-open), row F is either executed or recorded as
still pending with what the beta ships without, the three i18n gates and the whole-tree guards are green, and
the release notes carry the no-telemetry re-check. **The exit (1.0.0):** every V1 §8 item green (Q104 = b) —
item 3's coverage at the V1-8/V1-9 scopes, item 8's Windows lane blocking — then `v1.0.0` per the hosting
stance (free software, never hosting user data).

---

## 2. The rows

### Row A — The freeze · ruled (Q101 ⛔ = a, Q102 = a) · OPEN

**What it must demonstrate.** A written freeze list in this gate — features (no new vertical, no new lane after
`v0.9.0`), schema (only additive migrations after 0.9.0; the audit of `RELEASE_0.8_GATE.md` row B is its
input), backup format (every backup made since 0.9.0 restores forever — the format version pinned by a test
that fails on a non-additive change), the consent model (the one popup, the lanes' hover, the airplane
guarantee, the per-lane transports — unchanged from 0.9.0); UI copy and translations may still move (Q102 =
a — the i18n remainder and typo fixes stay allowed). The tester-facing promise follows: "your data survives
every beta". **Closes when** the list exists in this file (§5), the format-version test exists, and the
`alembic check` ratchet is joined by a guard that reddens on a dropped column or table after the freeze commit.
Brief `S09-01`.

### Row B — The public pre-release · ruled (Q103 = b; Q111) · OPEN

**What it must demonstrate.** GitHub pre-release tags `v0.9.0-beta.1`, `-beta.2` … that anyone may download
(Q103 = b — public, not invite-only; no accounts, no telemetry, per the hosting stance, so the project learns
only what people write to it); release notes generated from `shipped.csv` since the previous tag + the
no-telemetry re-check stated in them (Q111); a published report format — *proposed:* `docs/BETA_TESTERS.md`
carrying the freeze list, the data-safety promise and how to report, since the sheet's (a) named such a file
and (b) did not exclude it; the maintainer may decline it in §3. **Closes when** the first pre-release tag
exists with those notes and the report-format document (or its recorded decline). **Operator:** the tag from
the maintainer's machine (the session git proxy refuses tag pushes). Brief `S09-01`.

### Row C — The exit bar: V1 §8, item by item · ruled (Q104 = b) · OPEN

**What it must demonstrate.** The eight V1 §8 items with the state of each, as the RC gate the V1 pathway
promised (`RELEASE_1.0_RC_GATE` is THIS section): 1 data safety (K3/K4 green on a live ≥ 100 GB corpus;
restore + parity recovery on real hardware; the data-location chooser; no open data-loss bug) · 2 performance
(K1/K2 green; no interactive action blocks > 1 s without becoming a visible job) · 3 coverage (the five
verticals live with per-vertical freshness green; elections at CALENDAR scope per V1-8; patents only if its
precondition cleared; laws + **at least one full Wikipedia edition with the scaling machinery proven**, V1-9;
K8 targets) · 4 investigation (the dossier joins ≥ 6 rails with evidence trails and signed export; the
Conjunction Lens shipped and verified per Q1128) · 5 language (K6 at target; K11 green — chrome fully keyed
×12, `--audit-chrome` 0; reader + docs language-aware) · 6 honesty (the transversal audit repeated with zero
disclosure gaps; every AI-derived surface labelled; no composite score; consent model intact) · 7 verification
(K12 = 100 % of surfaces verified under Q1128, the human UX pass on the flagship flows; the improvement cycle
run ≥ 6 consecutive times with published reports) · 8 install (a fresh Debian user reaches a collecting app in
≤ 15 minutes; uninstall + backup round-trip proven; Windows first-class with a blocking lane, macOS
best-effort). **No additional field bar** (Q104 = b). **Closes when** each item is marked green with its
artifact or named-open with what is missing; 1.0.0 needs all eight green. Brief `S09-01`.

**The state, item by item (written 2026-11-20 on `main` at `91780c9eb`, rows 219–220).** «Green» needs the item's
artifact; everything else is named-open with what is missing. Re-read each line against `main` before it is quoted:
this is a dated record, not a live view.

| # | Item | State | The artifact, or what is missing |
|---|---|---|---|
| 1 | Data safety | **named-open** | Shipped: the data-location chooser (register C7, ratified; `src/api/unlock.py:401` `GET /api/system/data-location`, the step in `src/static/unlock.html`). Missing: K3 and K4 have no recorded value (`src/monitoring/kpi.py` `_SPECS`: K3 needs the operator's P0-validation run, K4 a multi-day live run); restore + parity recovery on real hardware (operator); a sweep for open data-loss bugs (not done here). |
| 2 | Performance | **named-open** | K2 has a live resolver (`src/monitoring/kpi.py:_k2_latency`) but no recorded value on a live corpus; K1 needs a 100 GB+ warm-unlock run (operator). «No interactive action blocks > 1 s without becoming a visible job» has not been audited. |
| 3 | Coverage | **named-open** | K13 reads each vertical, and its bars are set only from recorded values (Q1017 = a; R751(d), `S08-02` S2). Elections at calendar scope: `RELEASE_0.6_GATE.md` row A waits on the operator's Wikidata first run. Patents: the USPTO PADX + CPC precondition is not cleared (`RELEASE_0.7_GATE.md` row A). ≥ 1 full Wikipedia edition with the scaling machinery proven: `RELEASE_0.5_GATE.md` row F is PARTIAL from real machines (items 1–4 owed). K8's bars are pending V1-6. |
| 4 | Investigation | **named-open** | Shipped: the dossier joins nine rails for a country (PR #2140), with entry points from Explore, a keyword and a Lead (PR #2145), its rails as subtabs (PR #2161), the corpus rails' rows (PR #2174) and the signed-evidence export (PR #2139); the Conjunction Lens (`src/analytics/conjunction.py`, `src/static/app-corpus.js:1390`, S05-11 S3). Missing: one real entity's dossier with ≥ 6 rails having rows, Chromium-verified and clicked through (`RELEASE_0.8_GATE.md` row A); the Lens's verification under Q1128. |
| 5 | Language | **named-open; K11 green** | K11 green: its target is «min 100% ×12 (+ audit-chrome 0, CI-verified)» (`kpi.py` `_SPECS`), and the static job runs `--min 100`, `--max-untranslatable 0`, `--max-unkeyed-t-calls 0` and `--max-unkeyed-tf-frames 0` (`.github/workflows/ci.yml:473,512,540,558`), green in run 44727023621 on the head merged as `91780c9eb`; `--audit-chrome` reads 4807 UI strings, 4807 keyed. Missing: K6 has no recorded value and its bar is pending V1-6; «reader + docs language-aware» has not been audited as a whole (Help's body ×12 is done, `RELEASE_0.6_GATE.md` row E, which records R721). |
| 6 | Honesty | **named-open** | The latest transversal audit is `docs/audit/10_TRANSVERSAL_AUDIT_2026-09-08.md`; the 0.9 repetition with zero disclosure gaps is owed. The no-composite rule is held in code (`CardSchemaError`, `tests/test_producers_card_shapes.py`; the KPI board's own no-composite test, `tests/test_kpi_v16_resolvers_r706.py`). «Every AI-derived surface labelled» has not been swept. |
| 7 | Verification | **named-open** | K12 is not measurable in-process (`kpi.py` `_SPECS`: it awaits R3's flagged-surface inventory). The human UX pass on the flagship flows and ≥ 6 consecutive published improvement-cycle reports: none found on `main`. |
| 8 | Install | **named-open** | Windows is still an observation lane (`.github/workflows/ci.yml:55-60`, nightly, per R743 as that file's comment records it; row G). A fresh Debian user reaching a collecting app in ≤ 15 minutes, and the uninstall + backup round-trip: no recorded run on `main`. |

### Row D — The hardening items · V1 §3 · OPEN

**What it must demonstrate.** `python scripts/i18n_report.py --audit-chrome` at 0 (the ratchet's end state);
an accessibility pass at the three widths of the 2026-09-09 sweep across the surviving themes (0.5 row I's
cull); the scale re-validation on the live corpus (the P0 runbook at release scale, the 0.4 rows A–C shape);
docs / manual completeness with the docs↔app reciprocity swept; the install-paths decision executed (Debian
first-class; Windows per V1-5; macOS best-effort). **Closes when** each has its artifact: the ratchet at 0 in
`ci.yml`, the axe sweep report, the P0 report, the reciprocity sweep's list of corrections, the install matrix
in the release notes. **Operator:** the live-corpus runs. Brief `S09-01`.

**State (2026-11-20, rows 219–220).** `--audit-chrome` → 0 is **met**: the three i18n ratchets stand at 0
(`ci.yml:512,540,558`), `--min 100` runs in the static job (`ci.yml:473`; also `:152` on the docs-only path), and `--audit-chrome` reads 4807 UI strings, 4807
keyed. The axe sweep is row 222 (assigned). The P0 report is the operator's. The docs↔app reciprocity sweep and
the install matrix are still open.

### Row E — The security review · ruled (Q1136 = a, Q1138 = a) · OPEN

**What it must demonstrate.** The Tor-exit-resolve and `oo-netcut` / Stem items (register I3, I4) reviewed
here, as Q1138 parked them; app self-update as tags only, signed releases, an opt-in check consented like any
egress, never auto-install (Q1136); the per-release no-telemetry re-check (the socket-importer ratchet run and
the outbound call sites re-read, stated in the release notes — the `CLAUDE.md` ritual); the SSRF and airplane
guards re-verified against the lanes added since 0.3 (every new host in `SECURITY.md`, 0.4 row H). **Closes
when** the review's report exists with each item's finding and the re-check is stated in the notes. Brief
`S09-01`.

**State (2026-11-20, rows 219–220).** Q1136's update check has **shipped in part**: click-only, Check and Update
each through the one consent popup; the check is kill-switch-gated and goes through the protected-mode proxy; the
update itself is refused (409, named) in airplane and protected mode; never automatic (`docs/SECURITY.md`, the «App
updates» row; `src/maintenance/self_update.py:340-350`). **Wider than Q1136's «tags only»:** while no release tag
exists, the check offers `main`'s tip (`self_update.py:249`). **Signed releases are missing:** no signing key exists, and the key and
its trust root are the maintainer's (`S09-01` §5 step 2). The review report itself is row 221 (assigned). I3 and
I4 are untouched.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC14` came back blank → **ASSUMPTION
(a) at this row: Tor-exit-resolve (SOCKS `RESOLVE 0xF0`) GOES, as its own skeptic-matrixed slice**, rather
than staying parked. The register's I3 side takes §0's later-channel default over Q1138 = a (parked until
this security review), and the difference is real even though both land here: a parked item is recorded and
not built, while this row now carries one small transport slice with the full skeptic matrix, closing the
source-IP gap over Tor. The non-negotiables it must satisfy are unchanged and not relaxed by the assumption —
no silent transport downgrade, no evasion of a host's block, transport-aware verdicts. **I4 is NOT affected:**
`oo-netcut` and the Stem/Tor integration stay parked (register I4 and Q1138 agree), and this row's other
clauses (Q1136's consented self-update check, the no-telemetry re-check, and D7's parked pqcrypto 1.0
migration) are untouched. The CONFLICT with Q1138 stays recorded on both rows.

### Row F — The storage rulings executed · OPEN, Q1009 answered (a) 2026-09-29

**What it must demonstrate.** The intake's 0.9 line — "the storage rulings executed" — depends on the four
storage round-2 rulings (rows 3–6: blob-store dedup · pack AEAD OOENC2 vs `age` · keyed-HMAC blob addressing +
opaque pack names · the sqlite3mc benchmark trial). **Q1009 ⛔ was left blank on the sheet and is PENDING;**
nothing here is assumed. If it is ruled before this release, the row closes on the executed rulings' artifacts
(the create-time seams are irreversible, which is why they are ⛔); if not, the beta ships on the existing
store and this row records what that means for the wiki tail walk's depth (0.5 row F) and the 1.0 ≥ 100 GB bar
(V1 §8 item 1). **Owner: the maintainer** — a decision, not work.

### Row G — The Windows lane blocking · V1-5; ruled (Q1019 = a) · OPEN

**What it must demonstrate.** The `windows-latest` CI lane graduates from `continue-on-error` observation to
BLOCKING (V1-5), with the wiki, OSM and law lanes in the Windows matrix from the release each landed in (Q1019
= a — `pyosmium` wheels for Windows are FROM MEMORY in the sheet and must be verified when the `[geo]` extra
enters the matrix). **Closes when** `ci.yml` carries the lane without `continue-on-error` and it is green on
the tagged tree (premise, 2026-09-15: the Windows leg HANGS — PRH-29 in `ci.yml:380–386`, 3 h 21 m to failure,
capped at `timeout-minutes: 45` — and the bisect the cap defers is owed BEFORE the lane can block honestly;
`sqlcipher-smoke` at `ci.yml:411–416` already runs `windows-latest` blocking) (the recorded CI facts: the push lane on `main` has rarely completed — the artifact is a green
run on THIS tag's SHA, not "CI will catch it"). Brief `S09-01`.

### Row H — `POST_1.0_BACKLOG.md` · ruled (Q118 = a) · CLOSED 2026-11-20

**What it must demonstrate.** `docs/product/POST_1.0_BACKLOG.md` created with this gate, each item citing its
ruling: all-twelve-edition full text (V1-9 un-gated it from 1.0; it lands per storage milestone), rosters +
poll Tier-2 (V1-8), case law with ECLI identity (Q929 = a), bills and drafts as a separate lifecycle (Q902
note), subnational law beyond 0.7's reach (Q903/Q928 as confirmed), the ohsome pre-tracking history if ever
wanted (Q814 (c) was not chosen — listed as declined, not backlog), and whatever `RELEASE_0.8_GATE.md` §3
cut from the beta scope. Things the sheet ruled **never** are not backlog and are listed as such so they are
not re-proposed: scheduled automatic exports (Q220 = c), bulletin mail sending (Q1131), stored mailbox
credentials (Q1137), ~~the religious-calendar / eclipse feature (Q1135 = b)~~ (RC13's 2026-09-29 answer and R99 rule a build with eclipses; Q1135's index line still carries the old CONFLICT note; the backlog lists it apart, in its §4), regular expressions in search
(Q613), Wikimedia Enterprise and other keyed APIs (Q718). **Closes when** the file exists and every item
resolves to a ruling id in `RULINGS_INDEX.md`. Brief `S09-01`.

---

## 3. Amendment log

| Date | Change | Source |
|---|---|---|
| 2026-09-15 | Board created from the answered roadmap sheet (Q112 = a): 0.9.0 = Beta 1 (Q101 = a), the freeze (Q102), public pre-release (Q103 = b), exit = V1 §8 only (Q104 = b), no dates (Q110 = c), the security and Windows rows, the backlog file; row F recorded PENDING on Q1009 | maintainer (answer sheet) · rows written by the session |
| 2026-09-15 | **Premise corrections from the brief-writing pass:** (row G) the `portability` job (`ci.yml:371–387`) is `continue-on-error: true` with `timeout-minutes: 45` and the PRH-29 note that the Windows leg hangs (3 h 21 m to failure) — the cap does not fix the hang, a bisect against the suite is owed first, so "graduate to blocking" is bisect → green → blocking, in that order; `sqlcipher-smoke` (`ci.yml:411–416`) already runs `windows-latest` blocking. No `pyosmium` and no `[geo]` extra exist in `pyproject.toml` at `bebcef4` (Q1019's wheels stay FROM MEMORY). (row D) the "three widths of the 2026-09-09 sweep" are the 0.4 gate's §3 entry of that date (1440×900, 768×1024, 390×844); no audit DOCUMENT carries that date (the visual audit is `docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md`). (row B) the session clone is shallow (`git rev-parse --is-shallow-repository` = true), so release notes "from `shipped.csv` since the previous tag" need `git fetch --unshallow` first (CLAUDE.md protocol 5b's trap). No ruling changed. | session (`S09-01` §2, hand-verified) |
| 2026-09-15 | **The 2026-09-06 register's 65 answers — effects on this board:** row E — I3 `default` (go: Tor-exit-resolve as its own skeptic-matrixed slice) CONFLICTS with Q1138 = a (parked until this review; `RC14`); I4 `default` (park `oo-netcut` / Stem) consistent; G9's mechanics recorded (re-run `install.sh` on a snapshot; checksums stated until a key exists; no anchoring until then); D7 `default`: the pqcrypto 1.0 migration stays parked until a custody-path session with the full skeptic matrix. | maintainer (the register, 2026-09-15) · reconciled by the session |
| 2026-09-15 | **The RC confirmation round came back UNANSWERED — 0 of 22 `ANSWER` lines carry a letter — processed per its own §0.** Effect on this board: row E — `RC14` ASSUMPTION (a), Tor-exit-resolve becomes a built, skeptic-matrixed slice here rather than a parked item; I4 (`oo-netcut` / Stem) stays parked and every other clause of the row is untouched. Row F is unchanged: `RC03` ⛔ came back blank, so the four storage round-2 values stay unwritten and row F stays PENDING on Q1009 with nothing assumed. The CONFLICT with Q1138 = a stays recorded on both rows. **No row changed status.** | maintainer (the round, left blank) · §0's blank rules applied by the session |
| 2026-09-29 | **Row F unblocked: Q1009 = a (`y, OOENC2, y, y`, = `RC03` a).** Blob-store dedup ON, OOENC2 for pack AEAD, keyed-HMAC blob addressing with opaque pack names, the sqlite3mc benchmark trial authorised (benchmark only); the row closes on their execution. **`RC14` = a:** Tor-exit-resolve is its own slice at row E, confirmed. **`RC11` = b:** the provisional banner above. | maintainer (project chat, 2026-09-29 19:55 UTC) · recorded by the session |
| 2026-11-20 | **Rows C, D, E and H brought up to date on `main` at `91780c9eb` (Lane I, rows 219–220).** Row H CLOSED: `docs/product/POST_1.0_BACKLOG.md` and `tests/test_post_1_0_backlog.py`, which reddens on a cited id that does not resolve. **Correction:** row H listed Q1135 = b as «never»; RC13's 2026-09-29 answer and R99 rule a build with eclipses (Q1135's index line still carries the old CONFLICT note), so the backlog lists it apart, in its §4. Row C's eight items are written with their state: none green yet, item 5's K11 half green. Row D: `--audit-chrome` → 0 met. Row E: Q1136's check shipped in part (it offers `main`'s tip while no tag exists; the update is refused in airplane and protected mode, the check is not); signed releases missing (no key). No other row changed status. | Lane I (planner rows 219–220), every green claim re-read against `main` by a second reader |

---

## 4. Not in this gate

- **1.0.0 itself** — the exit clause above; the announcement posture per the hosting stance.
- **Any new vertical or lane** — the freeze (row A).
- **A field bar of external testers** — not chosen (Q104 = b); testers report what they report, and a
  data-loss report is a P0 bug against row C item 1, not a gate row.
- **The version flip to `0.9.0`.** It follows the `v0.8.0` tag, mechanically.

---

## 5. The freeze list (to be completed by row A; the headings are ruled by Q102 = a)

- **Features:** the lanes (press, wiki, osm, law, hazards, discovery), the five verticals at their 0.8 scope,
  the advanced search, the entity spine and dossier, the maps at their 0.7 scope — no additions after
  `v0.9.0`.
- **Schema:** additive migrations only after `v0.9.0`; the tables the audit of 0.8 row B lists.
- **Backup format:** the format version at `v0.9.0`; every backup made since it restores forever; the restore
  normalisers of 0.4 row K and 0.5 rows B/J stay.
- **The consent model:** the one online popup with the per-lane hover, the airplane socket guarantee, the
  Wikipedia toggle default-on under that consent, the per-lane transports that never downgrade, the
  OpenTimestamps and Wikidata consents as ruled.
- **Still moving:** UI copy, translations ×12, the Help body's remaining tranche, typo fixes.
