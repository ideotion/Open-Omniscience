# Release gate — v0.8.0 · Conflict + the 360° dossier, and lane completion

**Status: OPEN — written 2026-09-15 from the answered roadmap sheet.** The checkable inventory for closing the
`0.8` cycle, the last alpha before the beta (Q101 = a: alphas are 0.4–0.8; Q112 = a, Q1204 = a; the sheet is
[`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
indexed in [`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md)).

**What is ruled here and what is not.** The theme is the approved V1 train's (`V1_PATHWAY_2026-07-14.md` §3,
ruled 2026-09-07: conflict / defense §4.4 with OpenSanctions removed by V1-3; the topic-dossier surface joining
news × laws × wiki × stats × patents × papers × events × map). The approved "OSM dated-boundary seed" of 0.8
was pulled forward: the artifacts are 0.5 row E and the tracked-feature history is 0.6 row B (Q105 = a, Q106 =
a), so what 0.8 owes the map is completion, not a seed. Row B is where the lanes reach the breadth the sheet's
release statements end at (Q106/Q107/Q108 "0.7–0.8") and where the KPI bars are set from recorded values (Q1017
= a — measured first, never set before a release has recorded values). **No target date** (Q110 = c). Because
0.9 freezes features and schema (Q102 = a), **this is the last release in which a schema change may be
non-additive** — every migration after `v0.9.0` is additive by ruling.

**How a row closes:** a named artifact; `not-measurable-here` where the sandbox cannot measure; Chromium +
the maintainer's click-through (Q1128 = a).

**Entry.** `v0.7.0` tagged.

---

## 1. The board

| # | Row | Owner | Origin | Status |
|---|---|---|---|---|
| A | Conflict monitoring (keyless) and the 360° dossier over one entity | session | V1 §3/§4.4 + the dossier (ruled 2026-09-07) · brief `S08-01` | **OPEN** |
| B | Lane completion: the wiki / OSM / law lanes at their 0.8 breadth; KPI bars set from recorded values; Help ×12 finished | session + operator (the runs that record the values) | ruled (Q106, Q107, Q108, Q1017, Q1122) · `S08-02` | **OPEN** |
| C | The app-wide one-model decision (keep one model, or the specialisation bench's answer) — taken BEFORE this release opens | maintainer | ruled 2026-09-15 (register D8) — a decision, not work; the 0.7 exit clause names it | **PENDING — before 0.8 opens** |

**The entry (ruled 2026-09-15, register D8).** 0.8 opens only once row C's decision exists — the maintainer's
word on the app-wide model (one model stays, or the bench's answer), taken with whatever models exist by then
(«new models might come up and change what's best for the user»). Not a session's call.

**The exit.** `v0.8.0` is tagged when rows A–B are CLOSED on named artifacts, the i18n gates and whole-tree
guards are green, the release notes carry the no-telemetry re-check (Q111), **and the schema is in the shape
the beta freezes** (row B's last clause). This is the gate that decides whether 0.9 is a beta or another alpha:
a lane that has not reached its breadth by the 0.8 exit is either cut from the beta scope (recorded in
`POST_1.0_BACKLOG.md`, Q118) or delays it — the maintainer's call, made in §3 with the numbers.

---

## 2. The rows

### Row A — Conflict monitoring and the 360° dossier · V1 §4.4 + the dossier · OPEN

**What it must demonstrate.** The conflict / defense vertical keyless through the vertical pattern (V1 §4.4,
OpenSanctions removed); the dossier surface composing press, Wikipedia, law, Places and statistics over one
entity of the 0.5 spine — the 1.0 bar is V1 §8 item 4: "from any Lead / keyword / search → the dossier joins ≥
6 rails (news, wiki, laws, stats, events, map + any vertical) with evidence trails and signed-evidence
export". The map rail is the OSM lane's Places (0.5 row C/D), the law rail the evolution surface (0.5 row G),
the wiki rail the lane (0.4 row P). **Closes when** one real entity's dossier is shown joining ≥ 6 rails with
each rail's provenance and caveat visible (the informed-consent non-negotiable), the signed-evidence export
of that dossier verifies, and the surface is Chromium-verified + click-through. Brief `S08-01`.

### Row B — Lane completion and the KPI bars · ruled (Q106, Q107, Q108, Q1017, Q1122) · OPEN

**What it must demonstrate.** The OSM lane at "more countries" (Q106), the law lane at "the rest of the
world + subnational" (Q107; the Q903 CONFLICT resolved by then in `RELEASE_0.7_GATE.md` §3), the Wikipedia lane
with its coverage report per edition (Q108) and the walk's measured depth (0.5 row F); each lane's coverage /
freshness resolver has recorded values across at least one release, so **the KPI bars are set now, from those
values** (Q1017 = a — V1-6: measured first); Help's body ×12 finished (Q1122 = b; 0.6 row E's staging); and the
schema audited for what the beta freezes (Q102 = a: features + schema, only additive migrations after 0.9.0,
the backup format, the consent model) — every column or table the lanes still expect to add lands here or is
declared additive. **Closes when** the KPI board shows each lane's bar beside its recorded values with the
method on hover (premise, 2026-09-15: today the "board" is the JSON snapshot `/api/diagnostics/kpi` plus the bundle
member — no static file reads it, grep-verified; WHERE the bar renders is a placement NOTE for the maintainer,
`S08-02` §6, not a ruling), the Help coverage reads 12/12 on every document, and a written schema-freeze audit lists the
tables and the migrations after which only additive ones follow. **Operator:** the runs whose values set the
bars. Brief `S08-02`.

### Row C — The app-wide one-model decision · ruled 2026-09-15 (register D8) · PENDING before 0.8 opens

**What it must demonstrate.** Nothing built: a decision recorded in `RULINGS_INDEX.md` and `OPEN_QUEUE.md` — whether
the one ruled app-wide model stays, or the multi-model specialisation bench's answer replaces it — taken by the
maintainer before 0.8 opens, with the models available at that time. Whether the bench RUNS before it (0.5, as
Q1142 = a said) or is skipped (as D8's «Wait» says) is `RC04`'s question; the decision is owed either way.
**Closes when** the ruling is recorded with its date. **Owner: the maintainer.**

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC04` came back blank → **ASSUMPTION
(a): no specialisation bench runs in 0.5, so this decision is taken WITHOUT bench numbers behind it.** The
register's D8 side takes §0's later-channel default over Q1142 = a (run the bench in 0.5), whose own reasoning
— «new models might come up and change what's best for the user» — is why the measurement is not commissioned
in advance. This row is unchanged in owner, timing and status: still the maintainer's, still PENDING before
0.8 opens, still a decision rather than work. What the assumption fixes is only the evidence it arrives with,
and the CONFLICT with Q1142 stays recorded on both rows. Writing `b` at `ANSWER RC04` would commission the
bench in 0.5 as a measurement only and hand this row numbers; writing `c` would move the decision itself into
0.5 and retire this row.

---

## 3. Amendment log

| Date | Change | Source |
|---|---|---|
| 2026-09-15 | Board created from the answered roadmap sheet (Q112 = a); the V1 vertical carried; the OSM seed recorded as pulled forward to 0.5/0.6; the schema-freeze clause written from Q102 = a | maintainer (answer sheet) · rows written by the session |
| 2026-09-15 | **Premise correction from the brief-writing pass (row B):** `grep -rn kpi src/static/` finds nothing — the KPI board is `src/monitoring/kpi.py`'s snapshot served at `/api/diagnostics/kpi` and the diagnostics bundle member; the row's "shows each lane's bar … on hover" presupposes a rendering surface that does not exist at `bebcef4`. The row now says so; the surface's placement is listed in `S08-02` §6 as a NOTE the maintainer owes, never decided by the session. No ruling changed. | session (`S08-02` §2, hand-verified) |
| 2026-09-15 | **Row C ADDED — the app-wide one-model decision, owner: the maintainer** (register D8, 2026-09-15 15:17Z: «wait for the app wide one model ruling, new models might come up and change what's best for the user. Wait. Mark that we need the decision to be made before version 0.8 r»). A decision, not work; the 0.7 exit clause names it. Its CONFLICT with Q1142 = a (the bench in 0.5) is `RC04`'s. | maintainer (the register, 2026-09-15) |
| 2026-09-15 | **The RC confirmation round came back UNANSWERED — 0 of 22 `ANSWER` lines carry a letter — processed per its own §0.** Effect on this board: row C — `RC04` ASSUMPTION (a), the decision is taken without a 0.5 bench behind it; owner, timing and status unchanged (the maintainer's, PENDING before 0.8 opens). The CONFLICT with Q1142 = a stays recorded on both rows. **No row changed status.** | maintainer (the round, left blank) · §0's blank rules applied by the session |

---

## 4. Not in this gate

- **Everything post-1.0** — written down at 0.9 in `POST_1.0_BACKLOG.md` (Q118 = a), each item citing its
  ruling: all-twelve-edition full text (V1-9 un-gated it from 1.0), rosters + poll Tier-2 (V1-8), case law
  (Q929), bills and drafts (Q902 note), subnational law beyond what 0.7 reached.
- **Anything that lets OSM-derived rows leave the machine** — waits on Q823 ⛔; if still blank at this exit,
  the beta ships with OSM data inside the machine only and the freeze list says so.
- **The version flip to `0.8.0`.** It follows the `v0.7.0` tag, mechanically.
