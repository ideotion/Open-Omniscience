# Prompt 03 — The ledger restructure

> **Scope:** `CLAUDE.md`, `docs/ledger/`, and the protocol that governs them.
> **⛔ Gated on A3 — four yes/no rulings. Do not start without them.**
> **Sequencing:** any time after prompt 02, but it must not run concurrently with any other prompt: every
> other prompt appends to `CLAUDE.md` and `shipped.csv`, and this one moves them.

## 0. Working mode

Read `_WORKING_MODE.md`, then `docs/design/LEDGER_RESTRUCTURE_PROPOSAL_2026-08-04.md` in full, then
`CLAUDE.md`'s own protocol block at the top.

This prompt is unusual: the artifact you are restructuring is the one that tells you how to work. Treat the
protocol block as the specification and amend it deliberately, in the same commit as the change it describes.

## 1. The measurement

`CLAUDE.md` is **1,339,174 bytes / 14,985 lines**, of which the Open queue is roughly lines 6,035–14,982 —
**161 bullets**. The proposal was written when the file was 797 KB. Protocol rule (1) says to read it in full
before any work, every session; rule (5a) already moved shipped work to `docs/ledger/shipped.csv` (806 rows)
for exactly this reason.

The problem is not aesthetic. A ledger nobody can read in full is a ledger whose rulings get missed, and the
Lessons list in this very file records several defects that recurred because a recorded lesson did not reach
the next session.

## 2. Slices (each conditional on its ruling)

### S1 — A3(1): move the Open queue to `docs/ledger/OPEN_QUEUE.md`

Verbatim. Byte-for-byte for every bullet. `CLAUDE.md` keeps a pointer and a one-paragraph description of what
lives there. The move is a `git mv`-shaped operation done by hand: read binary, split at the section
boundary, write both halves in binary, and diff the concatenation against the original to prove nothing
changed. That reconstruction check is the whole safety property — assert it, do not eyeball it.

### S2 — A3(2): amend protocol rule (1)

The proposal's §4.2 wording: read the non-negotiables, the UI invariants and the Session-rituals Lessons
every session; read the Open queue on demand, driven by what the session is doing. Write the amendment into
the protocol block itself, with the date and the ruling reference, so the next reader knows it was decided
rather than drifted into.

### S3 — A3(3): retire SHIPPED entries out of the queue

Several Open-queue bullets describe work that is done. Rule 5 protects pending rulings, contingencies and
deliberate-omission notes — those never move. A bullet that is purely a record of shipped work becomes a
`shipped.csv` row plus, where it carries a reusable lesson, a `SHIPPED_LOG.md` entry. **The reality check in
prompt 02 §S4 names five such bullets;** re-verify each against the tree before retiring it, because a
half-shipped bullet must stay, reduced to its unshipped half.

### S4 — A3(4): the size ratchet

A test that fails when the ledger grows past a recorded ceiling, with the ceiling committed and the message
naming the compression rules (5) and (5a). Set the ceiling at whatever the file measures after S1–S3, not at
a round number: a ratchet with slack is a ratchet that does nothing.

## 3. Verification

- The concatenation check above.
- `grep -n '^<<<<<<<\|^=======$\|^>>>>>>>' CLAUDE.md docs/ledger/*.md docs/ledger/*.csv` returns nothing.
- Every internal link and every session-prompt reference to a CLAUDE.md section still resolves.
- `git diff --ignore-cr-at-eol --numstat` on `shipped.csv` shows only rows you added.

## 4. Scope fence

Do not edit the *content* of a ruling while moving it. Do not merge two bullets. Do not shorten a
non-negotiable. If a bullet is unclear, leave it unclear and say so in the PR body — an ambiguity you resolve
by rewording is a ruling you invented.
