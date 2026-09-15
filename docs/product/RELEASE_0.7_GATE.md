# Release gate — v0.7.0 · Medical + patents, and the widening

**Status: OPEN — written 2026-09-15 from the answered roadmap sheet.** The checkable inventory for closing the
`0.7` cycle (Q112 = a, Q1204 = a; the sheet is
[`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
indexed in [`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md)).

**What is ruled here and what is not.** The theme is the approved V1 train's (`V1_PATHWAY_2026-07-14.md` §3,
ruled 2026-09-07, amendment 3: medical survives fully keyless; **patents reduces to USPTO bulk XML + CPC and
rests on one unverified fact — that check is a PRECONDITION on the 0.7 slot, not a risk to meet mid-build**).
Rows B and C are the sheet's own release statements (Q106, Q107). **Row C carries a recorded CONFLICT** (Q903
answered "a and b": option (a) ends "subnational recorded for post-beta", option (b) says "subnational from
0.7"); the row is placed at 0.7 as the reading that keeps both options' scope, and it says so — the maintainer
confirms or moves it in §3. *Proposed placement* marks the planning session's sequencing (Q821). **No target
date** (Q110 = c).

**How a row closes:** a named artifact; `not-measurable-here` where the sandbox cannot measure; Chromium +
the maintainer's click-through (Q1128 = a).

**Entry.** `v0.6.0` tagged; the OSM daily tracking (0.6 row B) running on at least one country; the law
coverage report (0.6 row C) in the bundle.

---

## 1. The board

| # | Row | Owner | Origin | Status |
|---|---|---|---|---|
| A | Medical + patents through the standard vertical pattern; the USPTO precondition checked first | session + operator (the precondition check) | V1 §3/§4.1/§4.2 (ruled 2026-09-07, amendment 3) · brief `S07-01` | **OPEN** — patents BLOCKED until its precondition is verified |
| B | More OSM countries; self-rendered vector streets at high zoom from the ingested roads | session + operator (downloads) | ruled (Q106 · 0.7–0.8; Q821 = b *proposed placement* here) · `S07-02` | **OPEN** |
| C | Laws: the rest of the world; subnational from 0.7 | session + operator (live verification) | ruled (Q107 · 0.7–0.8; Q903 = a + b **CONFLICT**; Q928) · `S07-03` | **OPEN** — placement to be confirmed |

**The exit.** `v0.7.0` is tagged when rows A–C are CLOSED on named artifacts (row A's patents half closed OR
recorded as declined on its precondition, with the measurement), the i18n gates and whole-tree guards are
green, and the release notes carry the no-telemetry re-check (Q111). **Before 0.8 opens (ruled 2026-09-15,
register D8): the app-wide one-model decision is taken by the maintainer — «Mark that we need the decision to be
made before version 0.8» — a decision, not work, recorded as 0.8 row C; this exit does not wait for it, the 0.8
entry does.**

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC04` came back blank, so its stated default is a labelled **ASSUMPTION: (a) — the
specialisation bench is NOT run in 0.5 and the one-model decision is taken here, before 0.8 opens.** That is
the register's D8 side over Q1142 = a, and it CONFIRMS this clause rather than changing it: the «before 0.8»
marker was recorded regardless of `RC04`, and what the assumption settles is only that the decision arrives
without a 0.5 bench behind it. The CONFLICT with Q1142 stays recorded on both rows. Separately, `RC02` ⛔
came back blank and **stays PENDING**, so the «retire the legacy single-file restore» row the amendment log
below describes as conditional is **NOT added to this board** and the restore half is kept forever as Q215 = a
commits.

---

## 2. The rows

### Row A — Medical + patents · V1 §4.1/§4.2 · OPEN, patents blocked on its precondition

**What it must demonstrate.** The medical / biomedical vertical (PubMed and beyond, §4.2) through the vertical
pattern of V1 §4.0 — a managed dataset on the versioned-source substrate of 0.4 (the intake's cross-vertical
note: "the substrate gains PubMed-style managed datasets if the 0.6 exit shows the machinery holds"), keyless,
with per-vertical freshness on the KPI board; the patents vertical only after its §4.1 precondition (USPTO bulk
XML + CPC reachable and licensed as assumed) is verified live and the result written into the gate — a
precondition that fails is a decline recorded with its number, not a slip. **Closes when** each vertical's
freshness diagnostic reads from real fetches through the consent gate, the datasets carry registry entries and
disclosure lines, and the precondition check's artifact exists either way. **Operator:** the live checks on the
maintainer's machine where the sandbox's egress refuses the hosts. Brief `S07-01`.

### Row B — More OSM countries; the streets · ruled (Q106; Q821 = b) · OPEN

**What it must demonstrate.** The lane widened to more countries (Q106 = a: "0.7–0.8 widen to more countries"),
each with its sizes and daily diff cost shown before selection (Q824) and its measured ingest recorded;
**self-rendered vector streets at high zoom from the ingested roads** (Q821 = b — *proposed placement* 0.7,
because the roads of 0.5 row D must exist first) under the Canvas 2D level-of-detail caps (Q822), never an
external tile server (Q821 (c) was not chosen), the projection unchanged (Q801). **Closes when** a second and
third country are tracked with their measured figures, and a street-level view renders from ingested roads
on the reference VM without a frozen tab at the published caps (Chromium-verified + click-through, the frame
budget measured). Brief `S07-02`.

### Row C — Laws: the rest of the world; subnational · ruled (Q107; Q903 CONFLICT; Q928) · OPEN

**What it must demonstrate.** Breadth beyond the language coverage floor — "the rest of the world" (Q107 =
a: 0.7–0.8) under the same verification tier and licence rules as 0.6 row C; **subnational law from 0.7** — US
states, German Länder, Canadian provinces, Swiss cantons, Indian states (Q903 option (b), as chosen beside (a);
Q928's own conditional — "post-beta backlog unless Q903 = (b) or (c)" — therefore resolves to "from 0.7" as
well). **The CONFLICT is recorded, not resolved:** option (a) says subnational is recorded for post-beta, (b)
says from 0.7; both were chosen. This gate places subnational at 0.7 because (b) is the more specific
statement about timing and (a)'s scope (national + supranational through beta) is preserved either way;
**the maintainer confirms or moves the row in §3 before the slice starts.** Subnational identity uses ISO
3166-2 (Q314). **Closes when** the coverage report of 0.6 row C gains a subnational section with the tracked
/ verified / unverified state per jurisdiction, and one subnational source is ingested end-to-end with its
licence line. **Operator:** live verification per source. Brief `S07-03`.

---

## 3. Amendment log

| Date | Change | Source |
|---|---|---|
| 2026-09-15 | Board created from the answered roadmap sheet (Q112 = a); the V1 verticals carried with amendment 3; row C placed at 0.7 with the Q903 CONFLICT recorded for confirmation | maintainer (answer sheet) · rows written by the session |
| 2026-09-15 | **The 2026-09-06 register's 65 answers — effects on this board:** the exit clause gains «before 0.8 opens: the app-wide one-model decision (register D8: «Mark that we need the decision to be made before version 0.8»)», recorded as 0.8 row C; if `RC02` confirms C1's «a, but wait for version 0.7», a row «retire the legacy single-file restore» enters this board (not added by the session — a ⛔ contradiction with Q215 = a). | maintainer (the register, 2026-09-15) · reconciled by the session |
| 2026-09-15 | **The RC confirmation round came back UNANSWERED — 0 of 22 `ANSWER` lines carry a letter — processed per its own §0.** Effects: the exit clause records `RC04` ASSUMPTION (a) — no 0.5 bench, the one-model decision arrives here before 0.8 opens, confirming the marker rather than changing it; and `RC02` ⛔ stays PENDING, so the conditional «retire the legacy single-file restore» row named in the row above is **NOT added** and the restore half stays. **No row changed status; no row added.** | maintainer (the round, left blank) · §0's blank rules applied by the session |

---

## 4. Not in this gate

- **Conflict monitoring and the 360° dossier** — 0.8.
- **Case law** (Q929 = a) and **bills and drafts** (Q902 note) — post-beta, listed in `POST_1.0_BACKLOG.md`
  at 0.9 (Q118).
- **Help's body ×12** continues (0.6 row E's staging), owed complete by 0.8.
- **The version flip to `0.7.0`.** It follows the `v0.6.0` tag, mechanically.
