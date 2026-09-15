# Rulings confirmation — the 2026-09-06 register round (2026-09-15)

**What this is.** On 2026-09-15 the maintainer answered the 65-question register of the 2026-09-06 analysis
(`docs/plans/2026-09-06-repo-analysis/QUESTIONS_FOR_THE_MAINTAINER.md`) through the rulings artifact, between
15:02Z and 16:00Z — after the roadmap answer sheet (`ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`) had been
returned that morning with 40 of those ids re-asked inside it. Nine answers contradict the sheet's, five are
pending in some form, one qualifies a sheet answer and six new rulings have no release. **The recording session
resolved none of it** — the protocol says contradictions are listed, never settled by the session that records
them. This file puts each one back to you, answerable in place, in the format protocol rule (6) makes standard.
Everything not listed here is already recorded and needs no restating (`docs/ledger/RULINGS_INDEX.md` rows
`A1`–`L10`).

## §0 — How to answer, and how the answers are processed

- Write a letter after `ANSWER RCnn:` (a note in your own words after it is welcome and is recorded verbatim;
  where the note contradicts the letter, **the note is the ruling**).
- **Blank on a ⛔ question stays PENDING** — never defaulted. **Blank on any other question takes the stated
  default as an ASSUMPTION**, reversible at any time. For a CONFLICT question the stated default is the
  **later** of the two answers you gave (the register, 15:02–16:00Z) — because it postdates the sheet — and
  it is only an assumption until you write the letter.
- Processing (the same §0.2 protocol as the sheet): the letters are parsed mechanically; the answered file is
  kept in place as the primary record; ONE `OPEN_QUEUE.md` entry indexes the round; `RULINGS_INDEX.md` gets a
  row per `RCnn`; the gate files and briefs the answers touch are amended in the same PR; no ruling is invented.

---

## §1 — The contradictions (both answers are yours; pick one or write a third)

#### RC01 · A1 `deferred` — may the version flip proceed on the existing `v0.3.0` pre-release?
`v0.3.0` already exists (a lightweight tag at `917e8095`, a GitHub pre-release of 2026-08-23) but the 0.3 board's
row 5 (the Tier-A quarantine run, 8 articles) was never run, and A1 is now deferred with no date. 0.4 row G
(brief `S03-01`: close 0.3, flip the version to `0.4.0`) waits on A1 as written.
- (a) ★ **The flip proceeds now on the existing pre-release; row 5 becomes an operator step of 0.4 (beside rows
  A–C), run whenever you choose.** _Impact: 0.4 work lands on a tagged base today; the 0.3 gate closes with row
  5 carried, stated in its log._
- (b) **0.4 row G waits for row 5 (A1's deferral holds everything).** _Impact: the version stays `0.3.0` until
  you run the quarantine; nothing else changes._
Default if blank: (b) — A1 deferred means deferred.
ANSWER RC01:

#### RC02 ⛔ · C1 vs Q215 — the legacy single-file restore
Sheet (morning): Q215 = **(a) keep the restore half forever, as the docstring commits; close C1**. Register
(15:11Z): **«a, but wait for version 0.7»** — read as: every legacy backup you hold is merged (the register's
(a)), so the removal may proceed, but not before 0.7.
- (a) **Keep the restore half forever (the sheet).** _Impact: none; `S04-04` builds on it as written._
- (b) **Remove it in 0.7, after your confirmation that every legacy backup is merged and the unified import
  surfaces legacy archives.** _Impact: a 0.7 gate row; the `read_artifact` docstring's «forever (D7)» is
  amended in that PR; a restore path disappears for anyone holding a legacy file — data-safety class._
- (c) **Other** — write it.
Default if blank: none (⛔).
ANSWER RC02:

#### RC03 ⛔ · C4 = Q1009 — the storage round-2 rulings 3–6
The sheet left Q1009 blank; the artifact recorded `default` for C4 at 15:12Z, which resolves to the four
recommendations on record: (3) blob-store dedup **ON** · (4) **OOENC2** for pack AEAD · (5) keyed-HMAC blob
addressing + opaque pack names **yes** · (6) the sqlite3mc benchmark trial (benchmark only) **yes**. Because the
question is ⛔ and the two channels differ on the same day, write the four values out.
- (a) **Confirm all four as above** (`y, OOENC2, y, y`). _Impact: 0.9 row F closes on their execution; `S05-06`'s
  seam opens._
- (b) **Other** — write the four in order (e.g. `y, age, n, y`).
- (c) **Still pending.**
Default if blank: none (⛔).
ANSWER RC03:

#### RC04 · D8 vs Q1142 — the multi-model specialisation bench
Sheet: Q1142 = **(a) run it when the AI-coordinator translation sweep (Q405) lands in 0.5**. Register
(15:17Z): **«wait for the app wide one model ruling, new models might come up and change what's best for the
user. Wait. Mark that we need the decision to be made before version 0.8 r»**. The «before 0.8» marker is
already recorded (0.7 exit clause; 0.8 row C) whatever you answer here.
- (a) ★ **Wait: no bench run in 0.5; the one-model decision is taken before 0.8 opens.** _Impact: `S05-08` drops
  its bench part; the decision row in 0.8 carries it._
- (b) **Run the bench in 0.5 as a MEASUREMENT only (numbers, no switch); the decision still before 0.8.**
  _Impact: one session's work in 0.5; the decision has data._
- (c) **Run it and decide in 0.5 (the sheet).**
Default if blank: (a).
ANSWER RC04:

#### RC05 · B4 vs Q1105 — the 64,910 `kind_overrides` proposals
Sheet: Q1105 = **(a) a worklist for a review surface; never auto-applied**. Register (15:06Z): `default` =
**keep the measurement as evidence, build no tool; revisit when the perception NER kinds exist** (there is no
file in the repo — the figure is a design-doc measurement).
- (a) ★ **No tool; the measurement stays in the design doc.** _Impact: nothing built in `S04-12`._
- (b) **A worklist surface, when the review surface of Q1104 exists (the sheet).** _Impact: a generator run
  writes a reviewable file; one more review queue._
Default if blank: (a).
ANSWER RC05:

#### RC06 · B7 vs Q1108 — the recency window of the source re-check
Sheet: Q1108 = **(a) the 6-month re-verification reads the last 6 months, not the whole history**. Register
(15:10Z): **yes** to the register's default = **a 90-day window published BESIDE the whole-history verdict,
never replacing it**.
- (a) ★ **90 days, beside the whole-history verdict (both shown).** _Impact: two verdicts per source, each
  with its n; nothing replaced._
- (b) **6 months, instead of the whole history (the sheet).** _Impact: one verdict; a slow decline is visible,
  an old one is forgotten._
- (c) **Both windows beside the whole history.**
Default if blank: (a).
ANSWER RC06:

#### RC07 · B7's note — article revision tracking, where does it land?
«…I'd like to see track changes in articles too, to allow user to see if, when and how an article was modified
across time, the same way the app allows for law, wikipedia and OSM data.» A new capability: news articles
gain a revision history (re-fetch, diff, timeline), like the versioned lanes. No release was named.
- (a) **A fourth kind on the 0.4 row O substrate (`S04-08`): articles become a versioned lane in 0.4.**
  _Impact: 0.4 grows by a slice; re-fetch politeness and storage per revision are 0.4's to budget._
- (b) ★ **Its own 0.5 slice on the finished substrate.** _Impact: earliest release that does not load 0.4 further;
  the substrate is exercised by three lanes first._
- (c) **0.6 or later** — write the release.
- (d) **Post-beta backlog.**
Default if blank: (b) — an ASSUMPTION about placement, not about the feature (ruled).
ANSWER RC07:

#### RC08 · Six rulings with no release — the placements (answer each line `a`, or write another release)
Each was ruled by an explicit `default` or note; none names a release. `a` = the proposal in the table; `b` =
another release (write it after the letter); `c` = never / drop.

| part | ruling | proposal (a) | impact of (a) |
|---|---|---|---|
| RC08.1 | C5 — the DB-10 migrate-op (rebuild the store at the ruled pragmas) as a Settings → Advanced action with the honest cost estimate | 0.5 row B (`S05-02`, the storage half) | an app-stopped, hours-long op with one spare drive; the estimate from `rebuild.seconds` |
| RC08.2 | D2 + D4 — editions open on the deterministic introduction; the eight sections and the review screen ratified | 0.5, a small `bulletin-defaults` slice beside row H | one setting + copy ×12; no model needed |
| RC08.3 | E1 — `month-occupancy.json` as a diagnostics-bundle member; PROMPT_06 slice 3 (the date-aware month block + a re-index) reads it there | 0.4, with row C's diagnostics work (the ~1M bundle) | one bundle member; the re-index is the operator's |
| RC08.4 | G3 — the bloc-roster networked session (registry EMPTY until it runs) | 0.6 row A (`S06-04`), beside the statistics directory (G5/Q1147) | one networked session; several hundred dated member rows |
| RC08.5 | H3 — remove `#ins-term` + `exploreTerm` behind the omnibar-absorption test | 0.5 row I (`S05-09`, the UI shell) | one surface removed after its absorption test passes |
| RC08.6 | L5 — `_SPARSE_BAR_MAX` extended to `commodityOverlaySvg` only | 0.4 row U (`S04-14`) | one renderer; invariant #16 unchanged |

Default if blank: (a) for each part — ASSUMPTIONS about placement.
ANSWER RC08.1:
ANSWER RC08.2:
ANSWER RC08.3:
ANSWER RC08.4:
ANSWER RC08.5:
ANSWER RC08.6:

#### RC09 · D9 vs Q1143 — the live ollama.com library browse
Sheet: Q1143 = **(a) consented, opt-in, egress named**. Register (15:17Z): `default` = **drop it; record the
reason** (one model is ruled app-wide; the custom-model field stays).
- (a) ★ **Drop.** _Impact: no new egress surface; the custom-model field is the only path._
- (b) **Build it, consented and opt-in (the sheet).** _Impact: one more consented host (ollama.com), a search
  and filter UI, ×12._
Default if blank: (a).
ANSWER RC09:

#### RC10 ⛔ · E2 vs F1 — does «add them» include `dumps.wikimedia.org`?
F1 (15:20Z): **«add them»** for the whole allowlist block, which names `dumps.wikimedia.org (E2)`. E2 (15:19Z):
**«I don't know yet»**. Under Q701 (dumps are out of the Wikipedia design) the host would serve only PROMPT_06's
sense inventory and ambiguity map (slices 4 and 6), never dump ingestion.
- (a) **Include it.** _Impact: the two PROMPT_06 slices become session work instead of operator work._
- (b) **Exclude it for now (E2 stands); the other hosts are added.** _Impact: those two slices stay
  operator-side; nothing else changes._
Default if blank: none (⛔ — an egress decision).
ANSWER RC10:

#### RC11 · G1 — the detailed V1-1..V1-9 round
«I can't answer these now. Not enough details. Mark them for future development as questions to ask me with
more details and an overall impact evaluation.» The record: V1-1 (with four amendments), V1-2, V1-3, V1-5,
V1-6 (= Q1017), V1-8 and V1-9 were ruled on 2026-09-07 (`RULINGS_INDEX.md` R-series) and refined by the sheet;
V1-4 (PubMed bulk vs API) and V1-7 (storage) were not. A detailed round with an impact evaluation per item is
owed either way.
- (a) ★ **The round DETAILS the record: the 2026-09-07 rulings stand; it asks V1-4, V1-7 and, per item, only
  what those rulings left open, each with its impact evaluation.** _Impact: the 0.6–0.9 gate rows built on the
  rulings are unchanged._
- (b) **The round RE-OPENS all nine; until it is answered the 0.6–0.9 rows that cite them are provisional.**
  _Impact: the gates carry a «provisional on the V1 round» banner._
Default if blank: (a).
ANSWER RC11:

#### RC12 · G6 — the poll idea, re-stated: which version, and does it move poll work before 1.0?
Your note: raw poll data ingested; the poll's questions verbatim and its results readable directly; users
interpret for themselves; questions that orient answers detectable. «We should review everything regarding
this for version . » — the version was left blank. V1-8 (ruled 2026-09-07) put «rosters and poll Tier-2»
post-1.0; this feature is raw-data access, not Tier-2 analysis.
- (a) **0.6, with the elections vertical (row A).** _Impact: 0.6 grows by a slice; a poll-data source model and
  a reader; sources to be qualified._
- (b) **0.7.**
- (c) **0.8.**
- (d) **Post-1.0, with V1-8's placement.**
Write the version you meant after the letter if none fits. Default if blank: none — the note left it blank
and a second blank keeps it pending.
ANSWER RC12:

#### RC13 · G8 vs Q1135 — religious calendars (and the eclipse canon)
Sheet: Q1135 = **(b) drop the feature**. Register (15:27Z): **«I won't provide the dates. Let's create a
dedicated internet connected session to search for all religious dates and implement them in the app»**.
- (a) **Drop (the sheet).** _Impact: nothing built; the 2026-06-17 ruling 9 closed._
- (b) ★ **A dedicated networked session researches the dates from published calendars and authorities and
  implements them — dated, sourced, method stated, ×12; nothing fabricated.** _Impact: one networked session;
  a dated artifact under the external-artifact registry; the agenda gains a category._
- (c) **Derive from published astronomical/calendar algorithms with the method stated, no external call (the
  sheet's ★).** _Impact: computed, not researched; fixed-date and lunar feasts only where an algorithm exists._
Does (b) or (c) include the eclipse canon? Write `+ eclipses` or `− eclipses` after the letter.
Default if blank: (b).
ANSWER RC13:

#### RC14 · I3 vs Q1138 — Tor-exit-resolve (SOCKS `RESOLVE 0xF0`)
Sheet: Q1138 = **(a) parked until 0.9's security review** (one answer for I3 and I4). Register (15:53Z): I3
`default` = **go, as its own skeptic-matrixed slice**; I4 `default` = park (consistent).
- (a) ★ **Go — as its own slice; write the release after the letter (default: 0.9 row E, the security review,
  the earliest named home).** _Impact: a small transport slice with the full skeptic matrix; the source-IP gap
  over Tor closes._
- (b) **Parked until 0.9's security review (the sheet).**
Default if blank: (a) at 0.9 row E.
ANSWER RC14:

#### RC15 · L4 — which rate did «most ethical» mean?
«Adapt the rate limit to what's most ethical while keeping the app's efficiency and performance in mind.» L4
asked about the app's OWN guarded-route limit (100 requests/hour, a loopback self-limit the UI trips); the sheet
answered it as Q1148 = **(a) 1,000/hour for loopback UI calls, 100 for anything else**. «Ethical» reads more
naturally as the per-host EGRESS politeness (Crawl-delay, Q1013 = a), which is a different knob.
- (a) ★ **The loopback guard: Q1148's figures stand as the efficient setting.** _Impact: none beyond Q1148._
- (b) **The egress politeness: write the change wanted (e.g. honour `Crawl-delay` up to N s; a floor of M s
  per host).** _Impact: collection slows on hosts that ask for it; the governor composes with it._
- (c) **Both.**
Default if blank: (a).
ANSWER RC15:

#### RC16 · L9 vs Q1129 — the political-lean scale in the offerable vocabulary
Sheet: Q1129 = **(a) keep the stance: reported, never filtered** (the 2026-09-11 check found the code already
classifies `lean-*` as non-topical and declines to filter it, measured once in 921 assignments). Register
(15:59Z): `default` = **remove the scale from the offerable vocabulary; keep human-asserted lean tags**.
- (a) ★ **Remove it from the offerable vocabulary (human-asserted tags stay).** _Impact: the LLM can no longer
  propose a lean; a stated position in `source_tags.py` is changed, with the reason recorded._
- (b) **Keep the stance (the sheet).** _Impact: none._
Default if blank: (a).
ANSWER RC16:

#### RC17 · L10 vs Q1130 — the coverage-state prefixes
Sheet: Q1130 = **(a) filter only the `via:*` provenance prefixes from topical displays; keep the rest
reported**. Register (16:00Z): `default` = **filter the `via:*` AND the coverage-state prefixes (data-gap,
thin-coverage, fragmented, …); leave the judgement words**.
- (a) ★ **`via:*` and the coverage-state prefixes filtered.** _Impact: two prefix classes leave topical
  displays; the judgement words stay reported._
- (b) **`via:*` only (the sheet).**
Default if blank: (a).
ANSWER RC17:

---

## §2 — Not asked here, recorded already (for orientation only)
27 register answers agree with the sheet, 7 ratify shipped work, 12 take a recommended default the sheet had
not re-asked, 3 add a ruling by note (B5 diagnostics automation, E1 the bundle member, L6 `[pdf]` in the
default install), J3 agrees with Q1140's note, G10 is superseded by the sheet's §8 — all in
`docs/ledger/RULINGS_INDEX.md` rows `A1`–`L10` and in the register file under each question. The detailed
V1-1..V1-9 round (G1) is a separate file, written after RC11 says which shape it takes.
