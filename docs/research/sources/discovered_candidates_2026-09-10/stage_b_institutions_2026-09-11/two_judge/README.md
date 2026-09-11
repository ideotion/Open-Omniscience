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
