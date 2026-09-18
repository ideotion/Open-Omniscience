# THE SPLICE REPORT — Stage B institutions

Built by `scripts/analysis/stage_b_splice_report.py` from committed files only: the two judges' raw outputs, the content-integrity flags, and the Stage B triage rows. **Nothing was written to any catalogue.** Applying this is the operator's decision, and the counts below are what that decision rests on.

## Outcome

| outcome | rows | |
| --- | ---: | --- |
| **admitted** | 807 | both judges agree (Q1119 = a) |
| **deferred** | 1283 | the contested band — *deferred is not rejected* |
| **blocked** | 7 | `restricted_namespace`, no written override (Q1112 = b) |
| **declined** | 62 | the name is an unresolved identifier (Q1116 = a) |
| **routed elsewhere** | 57 | both judges agree it is not an institution — a different catalogue's row, not a rejection |

Paired rows: **1843** · single-judge rows: **373**

### Agreement, three statistics with three denominators

| statistic | value | over |
| --- | ---: | --- |
| `kind` | **97.1%** | all 1843 paired rows |
| `primary_source` | **84.6%** | the 1728 rows BOTH judges called `institution` |
| both axes at once | **83.6%** | all paired rows — *the predicate this splice admits on* |

Contested band: **16.4%**.

> `agreement_pct` requires BOTH axes to agree and is the predicate this splice admits on. `kind_agreement_pct` and `primary_source_agreement_pct` are the two-judge run's own statistics, each over its own denominator -- the second is computed only over rows both judges called `institution`, where the axis is defined. The combined figure is necessarily the lowest of the three; reading it against either of the others would manufacture a discrepancy out of a definition.

**These reproduce the two-judge run's own figures exactly** (97.1 % and 84.6 %), computed here independently from the raw result files rather than carried over — which is the point of recomputing them.

### Why each deferral

| reason | rows |
| --- | ---: |
| `agreed_not_a_primary_source_axis_deferred_by_Q1110` | 607 |
| `only_one_judge_read_this_row` | 373 |
| `judges_disagree_on_primary_source` | 251 |
| `judges_disagree_on_kind` | 52 |

> DEFERRED IS NOT REJECTED: a non-answer is not a no, so a deferred row keeps its evidence and its place in the worklist. Blocked rows are listed with their tier and are never silently dropped — lifting a block needs a written override, which is visible in this run's inputs. Nothing here was written to the catalogue; these are rows and counts for review. The largest deferred group is rows both judges agree are institutions and agree are NOT primary sources: admitting them would assert the opposite of what both said, and rejecting them would decide the very axis Q1110 defers while it is rewritten as an observable.

## Blocked — listed, never silently dropped (Q1112 = b)

| domain | tier |
| --- | --- |
| `chile.embajada.gob.ve` | `restricted_namespace` |
| `espana.embajada.gob.ve` | `restricted_namespace` |
| `italia.embajada.gob.ve` | `restricted_namespace` |
| `peru.embajada.gob.ve` | `restricted_namespace` |
| `rumania.embajada.gob.ve` | `restricted_namespace` |
| `serbia.embajada.gob.ve` | `restricted_namespace` |
| `usf.gov.jm` | `restricted_namespace` |

`restricted_namespace` domains in the flags file: **10** · inside this splice's population: **7** · blocked here: **7** · written overrides: **0**.

> `blocked_here` counts the flagged domains this splice's own population contains, not every flagged domain. The rest were not candidates in this run — they are neither admitted nor cleared by it.

**These are the flagged platforms, and this report does not decide them.** They stay excluded by the existing flag, which is today's state rather than a judgement: Q1113 is ⛔ and open. Nothing about them has been published and nobody has been contacted. Lifting a block needs a written override, which would appear in this run's inputs.

## The balance shift (Q1117 = a)

Catalogue rows before: **6229** · admitted here: **807** · after: **7036** · shared-vendor rows tagged: **36**

| country | before | added | after | before % | after % | shift (pp) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `cz` | 82 | 96 | 178 | 1.32 | 2.53 | **+1.21** |
| `gb` | 66 | 53 | 119 | 1.06 | 1.69 | **+0.63** |
| `id` | 34 | 38 | 72 | 0.55 | 1.02 | **+0.48** |
| `ph` | 24 | 32 | 56 | 0.39 | 0.8 | **+0.41** |
| `us` | 219 | 0 | 219 | 3.52 | 3.11 | **-0.4** |
| `de` | 54 | 32 | 86 | 0.87 | 1.22 | **+0.36** |
| `br` | 207 | 5 | 212 | 3.32 | 3.01 | **-0.31** |
| `ru` | 158 | 0 | 158 | 2.54 | 2.25 | **-0.29** |

> A concentration is not a defect. One country dominating a splice can mean that country's institutions publish machine-readable notices and others do not — so this is disclosed to be seen, not to be corrected. What it does mean is that a single supplier outage becomes a correlated failure across many rows, which is why the shared-vendor rows carry a tag.

> Two independent judges on identical neutral instructions. A row is admitted only where both agree on `kind` and, for institutions, on `primary_source`. A row either judge did not read has no agreement to measure and is deferred as such rather than counted in either direction.

## What happens next — and what needs the operator

1. **Review this report.** Applying it is a person's decision; nothing above has been written to a catalogue. The two questions worth the most attention are the **607 rows both judges agree are institutions and agree are NOT primary sources** (they are deferred because Q1110 defers that axis, not because anyone judged them unworthy), and any **written override** for a blocked row.
2. **The shortlist (3,031) run — Q1118 = a — is OPERATOR-GATED and was NOT run here.** It needs the maintainer's own machine or the sandbox allowlist that gate row V carries; from this environment it is `not-measurable-here`, and no yield is projected for it (the third-pass note in `OPEN_QUEUE.md` says why nobody should quote one). The remainder and the religious worklists follow *after* this splice is reviewed, which is the order Q1118 = a sets.
3. **Q1113 is ⛔ and untouched.** The flagged platforms above stay excluded by the existing flag. Nothing has been published about them and nobody has been contacted — that is today's state, not a decision this report took.
