# The two-judge rerun — RAW JUDGE OUTPUTS (in flight when committed)

Two independent judges, **the same neutral prompt** (`SPEC_NEUTRAL.md`), 60 batches each.

**Why both judges read identical instructions.** The escalated pass that preceded this one
changed the model AND the prompt at the same time, and its prompt carried a directional
correction — "the conservative default is not a licence to answer false by habit" — written after
a worker marked the European Commission non-primary. That correction pushes toward `true`, so its
71.0% could not be read as model quality. `SPEC_NEUTRAL.md` keeps the METHOD fix (read rows, not
batches) and drops the directional nudge, so agreement between these two measures shared signal
rather than shared bias.

**Committed mid-flight, deliberately.** These classifications cost real model spend and lived
only in an ephemeral session scratchpad — the exact loss the previous run's note warned about.
Whatever is here is here; batch numbers missing from a judge's directory were still running.

**The batch INPUTS are not committed** because they regenerate for free from the 8 VM shards'
`verified.jsonl`:

    python scripts/analysis/triage_batches.py prepare \
        --verified <the shards' verified.jsonl, concatenated> \
        --out-dir <dir>

Note that `prepare` mixes the canaries in at computed interior positions, so a regenerated batch
set is byte-identical to the one these judges read.

## What to compute from these

1. Validate **each judge separately** against the three canaries
   (`theguardian.com` → `news`/journalism, `ec.europa.eu` → `institution`/primary,
   `rijksmuseum.nl` → `institution`/NOT primary). A judge that fails a canary on a batch is
   untrusted for that batch — the same rule as any single-judge run.
2. Per-row agreement on `kind`, and on `primary_source` for the rows both judges called
   `institution`.
3. **The disagreement rate is the deliverable.** It measures how much of this axis is judgement
   rather than fact, which is the question the whole rerun exists to answer. For calibration: the
   two earlier passes, on populations with identical objective composition, answered 25.8% and
   71.0% `primary_source` TRUE.
4. Rows where the judges disagree are **DEFERRED, not rejected**, per the robots ruling: a
   non-answer is not a no.

---

# THE RESULT — measured on the 30 batches both judges completed

The run never finished: three agents died to API timeouts and server-side rate limiting, each
losing its whole block. It did not need to finish. **30 batches carry both judges — 1,200 paired
rows, independently classified on identical instructions** — which is a sufficient sample for the
question the rerun exists to answer.

| | | |
| --- | --- | --- |
| batches with both judges | **30** | |
| canary failures | **0 and 0** | on 60 batch-judgements |
| paired rows compared | **1,200** | |
| agree on `kind` | **1,166** | **97.2%** |
| both said `institution` | 1,134 | |
| agree on `primary_source` | **961** | **84.7%** |

## This corrects the earlier reading, and the error was mine

The escalated pass answered 71.0% `primary_source` TRUE against the first pass's 25.8%, on
populations with identical objective composition, and the conclusion drawn was that the column
measures the judge rather than the source.

**With both judges on the same neutral prompt, they agree 84.7% of the time.** So most of that
2.75× swing was not the axis being unreliable — it was **the directional correction in the
escalated prompt**, which told a worker that answering false by habit was wrong after one had
marked the European Commission non-primary. That confound was admitted at the time; this
measures how much of the damage it actually did, and the answer is "most of it".

The axis is a real signal with a **15.3% contested band**, not a coin flip.

**The method fix, separately, worked completely.** Six of ten workers failed the canary gate on
the first pass. Across 60 batch-judgements here: zero failures, both judges. The "read rows, not
batches" correction is doing real work and carries no directional bias.

## The disagreements are informative rather than noise

| disagreement | n |
| --- | --- |
| `academic` vs `institution` | 18 |
| `institution` vs `trade-or-corporate` | 12 |
| everything else | 4 |

**The largest single disagreement is exactly the open question about research institutes.** Two
careful judges reading the same evidence cannot agree whether a research body is `academic` or
`institution` — and that is not judge failure, it is a gap in the taxonomy, which is what the
pending ruling is about. The second, `institution` vs `trade-or-corporate`, is mostly bodies whose
site has become promotional or has been taken over.

## What this supports

Admit on agreement, defer on disagreement: **~85% of institution rows get a decision two
independent judges reached separately**, and the ~15% that do not are deferred rather than
rejected, per the robots precedent. That is a defensible basis for admission in a way that a
single judgement was not.

It does NOT retire the case for rewriting the axis as an observable — a 15.3% contested band on a
boolean is still substantial, and the equity argument (a model calibrated on Western
administrative norms judging 84 countries) is untouched by two judges sharing that calibration.
Two judges agreeing measures consistency, never correctness.
