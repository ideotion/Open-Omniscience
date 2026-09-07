# Prompt 01 — Close the 0.3 gate and stand up the 0.4 board

> **Scope:** the release process only. No product feature work.
> **Gated on:** A1 (an operator step, not a question), A2.
> **Sequencing:** first. Several later prompts add rows to the 0.4 board this one creates.

## 0. Working mode

Read `docs/plans/2026-09-06-repo-analysis/_WORKING_MODE.md` in full — it is part of this prompt. Then read
`docs/product/RELEASE_0.3_GATE.md` end to end, and the CLAUDE.md Open-queue entry titled **"THE 0.3 CLOSE
GATE"**. The gate document is the tickable board; the ledger entry is the ruling of record. Where they
disagree, the ledger wins and the board gets corrected.

One thing about this prompt specifically: **you cannot close it alone.** Rows 5 and 7 and the tag itself
are the maintainer's hands. Your job is to make every one of them a single unambiguous action, to build the
instruments that make the 0.4 rows closable, and to leave a board that reads correctly whether or not the
tag happens this week.

## 1. Where the release actually stands

Verified 2026-09-06 against the tree, not read off a status line:

- Rows **1, 2, 3, 6, 7a, 8** are CLOSED. Row 3's 5-million-article bar was withdrawn on 2026-07-30 and the
  ruled bar is ~1M; the P0 validation ran at 1,048,725 articles / 21.0 GB on 2026-08-12 with 4 pass, 0 fail,
  1 not-measurable.
- Row **5** is OPEN but **its criteria were agreed on 2026-08-23** — the row body reads *"agreed 2026-08-23
  (row body); pass not run"*. Nothing is being decided; a pass has not been executed.
- Rows **4** and **7b**, and the ~1M all-diagnostics bundle with `complete: true`, were moved to **0.4** and
  are REQUIRED there, not merely deferred.
- There is no `docs/product/RELEASE_0.4_GATE.md`.

## 2. Slices

### S1 — Make row 5 a single command, and prove the flag matters

`POST /api/quarantine/start?write=true&include_prose_gate=false`. The `include_prose_gate=false` is
load-bearing: without it the run also applies the prose gate, which selects a **different, unagreed**
population (Tier B's 451 index pages above the ≥100-word guard, whose prose is unmeasured).

Build:
- A test that drives the real endpoint and asserts the two flags select **different** article sets, so the
  distinction cannot be lost by a later refactor. There is currently **no frontend caller** for the
  quarantine endpoint — that is fine and deliberate, but it means the flag exists only in a URL, which is
  exactly the kind of parameter that gets defaulted away.
- A short operator section in `docs/product/RELEASE_0.3_GATE.md` §7.1 giving the four actions in order:
  the POST, the re-index ("Clean up keywords"), the report of the count under criteria version
  `nav-soup-v2`, the row tick.

### S2 — Fix the calibration instrument that cannot finish

`criteria-calibration.json` rides the all-diagnostics bundle, and its **prose arm is pinned at
`prose_gate_after_id=0, limit=500`**, so every run re-measures the same lowest-id 500 articles and `done`
can never become true on any corpus larger than 500. Worse, it walks by ascending id, which samples whatever
that key happens to order first — not the population the decision is about (the ~451 index pages that clear
the word guard).

Fix both halves: carry the cursor across runs, and point the arm at the population under decision. State in
the report which population it measured. This is what makes a future Tier B decision possible; without it
the evidence arm is decorative.

### S3 — Stand up `docs/product/RELEASE_0.4_GATE.md`

Start verbatim from the 0.3 gate's §5 "Carried to 0.4", which already names the three rows and — importantly
— row 4's **closing clause**: a spot-check that a previously-DISQUALIFIED source is still disqualified after
the import. A pass that counts only `qualified` rows cannot see the inversion that row exists to catch.

Keep §5's declined split recorded as a still-available cheaper substitute (one small committed backup, to
preserve the stamps-survive-a-restore demonstration while postponing the full source re-check), so nobody
re-invents it.

Add, as new 0.4 rows, the items this analysis found that belong on a release board rather than in a feature
prompt: the ≥72 h soak's **report member** (S4 below), the committed-import demonstration tooling
(prompt 07), and whichever of the 0.3-era browser-verification stamps are still "awaiting human UX pass".

### S4 — A soak report member, so row 7b closes on evidence rather than on memory

Row 7b is a ≥72 h collector soak. The instruments exist (`collect_perf`, the stall forensics, the run
journal, `wal_history`); what does not exist is one artifact that answers "did the soak pass". Build a
bounded diagnostics member that reports, for the window it covers: memory-guard engage cycles per day, the
`wal_history` maximum, the write-gate busy share, `/api/database/stats` p95, and the `interrupted` count —
each with its own denominator and an explicit not-measurable state where the window does not reach.

It must state the window it actually read. `collect_perf`'s rolling retention covers roughly one pass, which
is why the 2026-07 multi-hour stalls were undiagnosable after the fact; a member that quietly reads a
two-hour window and reports on a three-day soak would be the fabricated-pass shape.

### S5 — Reconcile the board with the tree

Sweep `RELEASE_0.3_GATE.md`, `docs/CHANGES.md` and the CLAUDE.md gate entry for figures that no longer hold.
Known: the P0 acceptance strings that said "100 GB" were corrected on 2026-08-03, so the ledger sentence
naming them as still-stale is itself the stale half. Row 4's "~10×" was corrected to "~2×" and the real
multiple at the 2026-08-12 run is 8.3× the v0.2.0 scale — state the measured multiple, never the framing's.

## 3. Sequencing

S3 and S5 are independent and can land first. S1 unblocks the operator. S2 and S4 are instruments; S2 is
worth more (it gates a decision), S4 is worth more later (it closes a 0.4 row).

## 4. Scope fence

Do not run the quarantine pass yourself against anything but a synthetic corpus. Do not tag. Do not create a
GitHub release. Do not touch `PATHOLOGY_ABS_FLOOR` (question B6, prompt 04). Do not widen row 5 to Tier B.

## 5. What this prompt does not fix

The tag, the soak, the committed import and the ~1M bundle are the maintainer's. If A1 comes back
"already run", S1 becomes a test-and-document slice only and row 5 ticks in this PR.
