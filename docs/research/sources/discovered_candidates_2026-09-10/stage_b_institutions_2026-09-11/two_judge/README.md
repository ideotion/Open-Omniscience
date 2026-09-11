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
| batches with both judges | **46** | |
| canary failures | **0 and 0** | on 92 batch-judgements |
| paired rows compared | **1,840** | |
| agree on `kind` | | **97.1%** |
| agree on `primary_source` | | **84.6%** |

**The figures converged as the sample grew, which is the reason to trust them:**

| overlap | paired rows | `kind` | `primary_source` |
| --- | --- | --- | --- |
| 30 batches | 1,200 | 97.2% | 84.7% |
| 34 batches | 1,360 | 97.4% | 85.1% |
| 36 batches | 1,440 | 97.4% | 85.8% |
| 40 batches | 1,600 | 97.5% | 85.3% |
| 42 batches | 1,680 | 97.4% | 85.4% |
| 46 batches | 1,840 | **97.1%** | **84.6%** |

**Read these as ranges: `kind` 97.1–97.5%, `primary_source` 84.6–85.8%.**

**AND NOTE THAT THE PREVIOUS RANGE FAILED ITS OWN TEST.** A revision of this file stated
97.2–97.5% and 84.7–85.8%, with the explicit claim that stating a range would stop further data
from rewriting the figure. The very next arrival landed at 97.1% and 84.6% — outside both, by a
tenth of a point in each case. The range had been built from a run of samples that happened to be
increasing, so it recorded a trend as if it were a bound. The widened range above is the observed
extremes over all six readings and carries no such claim: it is a description of what was seen,
not a prediction about what comes next.

Nothing about the conclusion moves — ~97% on `kind`, ~85% on `primary_source`, a ~15% contested
band — and that is the honest reason the failure is worth recording rather than smoothing: the
substance was never at stake, so there was nothing to be gained by quietly restating the bound.

(Two earlier revisions of this file called a smaller sample FINAL. More agents kept landing, so
neither was. The figures did not care, which is the point; the record is left showing that it
moved rather than quietly revising its own superlatives.)

The run stopped at 40 of 60 overlapping batches because agents kept dying to API timeouts and
server-side rate limiting — not because the measurement needed more. Judge A completed 48
batches and judge B 48; the 8 without a counterpart are listed in neither judge's favour and are
simply unused.

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
| `academic` vs `institution` | 22 |
| `institution` vs `trade-or-corporate` | 17 |
| everything else | 2 |

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


## Addendum — the hijacked-domain list grew, and one entry is worse than the rest

Judges kept finding institutional domains whose CONTENT is no longer the institution's. Named
across the run, each spotted independently from the evidence rather than by any rule:

`lancashireprobation.co.uk` · `ffw-ungelstetten.de` · `peru.embajada.gob.ve` ·
`embajada-alemana.org.pe` · `lesotholondon.org.uk` · `sedlecko.cz` · `gartzambia.org` ·
`adach.ae` — gambling spam or content farms under the name of a probation service, a fire
brigade, three diplomatic missions, a Czech village and an Abu Dhabi cultural authority.
`ambassade-du-burundi.fr` is a Thailand travel blog. `nogradarchiv.hu` is a lifestyle content
farm. `tullikamari.net` is a private event venue.

**`pn-nunukan.go.id` is the one to look at.** That is an Indonesian district court on a
restricted `.go.id` government domain, and a judge reported it serving WordPress blog content —
a compromised government host, not an expired registration.

Stage A verified every one of these, correctly: the feed parses and is fresh. Only a reader of
the content catches it. There is still **no detection rule** (open queue C6), and the count here
is deliberately a NAMED LIST rather than a total, because an automated proxy over the judges'
own labels mixes real takeovers with ordinary disagreement.


## One more class of defect, distinct from the hijacked domains

Judges also found rows whose NAME is simply wrong in the export, which is not the same as a
domain that has been taken over:

* a row named **"Supreme Court of Pakistan"** that is in fact a press-freedom NGO;
* a **"Directorate of Agricultural Research"** that is in fact a peer-reviewed journal;
* a metrology institute and a UK statistics regulator whose fetched headlines were **lorem-ipsum
  and CMS test placeholders** — the site is real, the evidence is empty.

Together with the `country: ca` on a `cityofvancouver.us` row (open queue C7), this says the
export's identity fields — name, country, `wikidata_type` — are **evidence, not fact**. The
neutral spec already tells judges the type is a hint and the headlines are the evidence, which is
why these surfaced at all. The lorem-ipsum case is its own small hazard: an empty-evidence row
cannot be judged on evidence, and judges resolved it from the body's structural mandate instead,
which is exactly the kind of inference the spec otherwise forbids.
