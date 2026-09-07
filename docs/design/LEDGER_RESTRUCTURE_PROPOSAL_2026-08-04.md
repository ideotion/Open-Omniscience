# Proposal — split the ledger so rule (1) can be obeyed again

**Status: RULED AND EXECUTED 2026-09-07.** The maintainer answered all four §7 questions
(recorded as A3 in `docs/plans/2026-09-06-repo-analysis/QUESTIONS_FOR_THE_MAINTAINER.md`):
**yes** to all four, and **(1) was widened** — the Lessons subsection moved out too, which
§5 below had proposed to keep inline. Read §5 with that in mind: it is the one bullet the
ruling overrode.

**Why (1) was widened.** This proposal was written against a 797 KB file and predicted the
move would leave ~1,940 lines / ~47k tokens. By 2026-09-07 the file was 1,345,603 bytes and
the Lessons subsection alone had grown to 489,044 bytes / 5,583 lines — 36 % of the file —
so moving only the queue would have left ~6,038 lines / ~132k tokens and rule (1) would
still have been unobeyable. Measured outcome: **CLAUDE.md 1,345,603 → 36,337 bytes**, with
`docs/ledger/LESSONS.md` (490,053) and `docs/ledger/OPEN_QUEUE.md` (822,012) beside it. The
move was byte-exact: the original SHA-256
`fcc4072fea11c7944ecaec2c85d80d7f70db6bb330ff1f0341ef03faffbf3107` is reconstructible from
the three files, asserted in the split.

**§6's observation on `shipped.csv` remains open** — it was explicitly left for a separate
decision and no ruling has been given on it.

**Author's position, stated once and not repeated below:** the ledger discipline is the
single most unusual strength of this project and this proposal does not weaken it. It
proposes to change *where* the material lives so that the rule requiring it to be read
can actually be followed.

---

## 1. The measurement

| | |
|---|---|
| `CLAUDE.md` size | 797,471 chars ≈ **215,000 tokens** |
| Lines | 8,888 |
| Rule (1) | "Read it in full before any work, **every session**" |

Section breakdown:

| Section | Lines | Share |
|---|---:|---:|
| **Open queue** | **6,946** | **78.1 %** |
| Session rituals (incl. Lessons) | 1,546 | 17.4 % |
| UI invariants | 267 | 3.0 % |
| Non-negotiables | 98 | 1.1 % |
| Shipped batch log | 4 | 0.05 % |

Open-queue top-level entries: **139**.

## 2. What this costs, concretely

215k tokens is at or beyond the usable context of a working session *before a single
source file is opened*. In practice rule (1) therefore cannot be obeyed as written; it is
obeyed approximately, by skimming, which is the failure mode the rule exists to prevent.

Two lessons already in the file describe this outcome without naming the cause:

- *"A FIX RECORDED IN THE LEDGER DOES NOT PROPAGATE ITSELF TO A NEWER SIBLING MODULE"*
  (the TMPDIR recurrence) — a fix was recorded at CLAUDE.md:519-520 and re-broken later.
- *"the lesson existed and was still not reached for until the test went red"*
  (the comment-strip guard, re-hit 2026-08-03).

Both are descriptions of a document too large to consult. The remedy the file itself
already reaches for in its best moments is *mechanical enforcement*
(`tests/test_repo_invariants.py`), not more reading.

## 3. Why the existing compression rule did not prevent this

Rule (5)/(5a) worked exactly as designed — on the wrong section. The Shipped batch log was
compressed to 4 lines and moved to `docs/ledger/shipped.csv`. But rule (5) also says:

> NEVER compress away a pending ruling, a contingency, or a deliberate-omission note.

…which is correct in intent and, as written, exempts the Open queue from any bound. The
queue is therefore the one section that can only grow, and it now holds 78 % of the file.

The protection that matters is **"never lose a ruling."** That is a property of *storage
and retrievability*, not of *co-location in one file*.

## 4. Proposal

**4.1 — Move the Open queue to `docs/ledger/OPEN_QUEUE.md`, verbatim.** No compression, no
summarising, no dropping. A pure `git mv` of the section. `CLAUDE.md` retains a pointer and
a one-line index of the entry titles.

Result: `CLAUDE.md` ≈ **1,940 lines / ~47k tokens** — the Non-negotiables, the UI
invariants, the Session rituals and the Lessons. That is the part that is genuinely
"read before any work": it is the constitution, and it is stable.

**4.2 — Amend rule (1) to match what is actually required:**

> (1) Read `CLAUDE.md` in full before any work, every session. It is the constitution:
> non-negotiables, UI invariants, rituals, lessons. Then open
> `docs/ledger/OPEN_QUEUE.md` and read the entries relevant to the work at hand —
> the queue is the docket, not the constitution, and is consulted, not memorised.

**4.3 — Keep rule (2) unchanged.** New rulings are still recorded in the same turn they
are given; they land in `OPEN_QUEUE.md` instead of inline.

**4.4 — Bound the queue by lifecycle, not by prose.** An entry whose work is shipped moves
to `shipped.csv` and leaves the queue. Today entries are appended and amended in place but
rarely retired, so completed work is re-read every session. This is the one change that
stops regrowth; it retires *finished* items only and never a pending ruling, a contingency,
or a deliberate-omission note.

**4.5 — Add a guard.** Extend `tests/test_repo_invariants.py` with a size ratchet on
`CLAUDE.md` (fail if it exceeds its current line count), matching the `MYPY_BASELINE`
precedent. A ratchet is what makes 4.4 self-enforcing rather than a good intention.

## 5. What this does NOT propose

- No ruling, contingency or deliberate-omission note is deleted, summarised or reworded.
- `shipped.csv` and `SHIPPED_LOG.md` are untouched.
- The Lessons subsection **stays in `CLAUDE.md`** — it is the highest-value-per-line content
  in the repository and it is exactly what a fresh session must have in mind.
- No change to how rulings are captured.

## 6. Observation on `shipped.csv`, for a separate decision

`shipped.csv` parses cleanly (560 rows × 7 fields — it is valid CSV, which is better than
it looks). But **76 % of its content is the single `summary` column**, with the largest cell
at 8,371 characters. It is a prose archive in a tabular container: `grep`-able, not
queryable. If it is ever meant to be queried (by area, by date, by status), the prose wants
to move to `SHIPPED_LOG.md` — which already exists for exactly that — leaving the CSV with
short factual fields. Not proposed here; recorded because it is the same
growth-without-a-bound shape one level down.

## 7. The ruling required

1. Move the Open queue to `docs/ledger/OPEN_QUEUE.md` verbatim? (yes / no)
2. Amend rule (1) as in 4.2? (yes / no)
3. Adopt 4.4 — retire shipped entries out of the queue? (yes / no)
4. Add the 4.5 size ratchet? (yes / no)
