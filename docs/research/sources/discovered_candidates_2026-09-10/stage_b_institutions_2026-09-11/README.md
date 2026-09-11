# Stage B on the institutions worklist — RUN, MEASURED, AND **NOT ADMITTED**

2026-09-11. 2,373 feed-verified institutions from the 8-VM fleet run, triaged in 60 batches of
40 (+3 canaries) across 10 workers, then 36 refused batches re-run on the escalation model.

**Nothing here was spliced into a catalogue.** The files are preserved so that revisiting this
does not cost another full Stage B run — the same reason
`stage_a/triage_refused_entries.yml` exists. Read this before using any of them.

## What the merge produced

| target | entries |
| --- | --- |
| `triaged_journalism.yml` → `configs/sources.yml` | 3 |
| `triaged_academic.yml` → `configs/academic_sources.yml` | 36 |
| `triaged_official.yml` → `configs/official_sources.yml` | 994 |
| refused: `institution_not_primary_source` | 1,024 |
| refused: batch untrusted (6 batches, canary failures) | 240 |

## Why none of it was admitted

### 1. The `primary_source` column measures the judge, not the source

The axis that decides admission for an institution was answered twice over comparable
populations. The objective control — the share of INPUT rows on a government-style domain — is
the same in both. The answers are not:

| judged by | rows | gov-domain share of input | `primary_source` TRUE |
| --- | --- | --- | --- |
| first pass | 960 | 24.6% | **25.8%** |
| escalated pass | 1,173 | 25.4% | **71.0%** |

2.75× apart on the same question, both passes canary-clean, both producing articulate per-row
reasoning. Per block the spread was wider still: 5.0% to 97.6%, against an input composition
varying only 18%–33%.

**The confound, stated because it is mine.** The escalated spec changed TWO things: a stronger
model AND a correction saying the conservative default "is not a licence to answer false by
habit", written after a worker marked the European Commission non-primary. That correction
pushes toward `true`. So the 2.75× cannot be attributed to model quality — part of it is my
prompt. What survives the confound is that a single judgement on this axis is not stable enough
to admit rows to a permanent catalogue.

### 2. The journalism rows are wrong, so `kind` is not safe either

An earlier read of this run claimed journalism and academic rows were safe to splice because
they route on `kind`, which the canaries test directly. **That was wrong, and these three rows
are the counter-example:**

* `cityofvancouver.us` — a US city government's police blotter ("Homicide Suspect Arrested",
  "City Manager update"), classified `investigative` **journalism**. It is an institution. The
  row also carries `country: ca` while the domain is Vancouver, **Washington**.
* `hypertension.org.au` — a medical research council, classified `investigative`.
* `mykishtwar.com` — local district news. Plausibly the only correct one of the three.

The canaries test `kind` on three unambiguous rows and catch gross failures — they caught six
workers. They do not catch a rare misread in a population that is 98% one class.

### 3. The academic rows are a category mismatch

`configs/academic_sources.yml` holds **peer-reviewed journals** (Acta Medica Academica,
International Journal of Bahamian Studies, Periodicals of Engineering and Natural Sciences).
These 36 are **research institutes' news feeds** (Max Planck Institute for the Physics of
Complex Systems, Royal Belgian Institute for Space Aeronomy). An institute's announcements are
not a journal, and merging them would break the thing the 2026-09-11 ruling wanted the separate
catalogue FOR: "so a corpus statistic keeps meaning what it says".

## One finding worth keeping regardless

**Institutional domains that have been taken over.** Workers independently flagged several
where the live feed Stage A verified is real but the CONTENT is not the institution's:
`lancashireprobation.co.uk` (UK probation service → gambling spam), `ffw-ungelstetten.de`
(German volunteer fire brigade → gambling spam), `peru.embajada.gob.ve` (Venezuelan embassy →
gambling spam), `ambassade-du-burundi.fr` (→ a Thailand travel blog), `nogradarchiv.hu` (→ a
lifestyle content farm).

Stage A cannot see this: it verifies that a feed parses and is fresh, and these feeds do. Only
a reader of the CONTENT catches it. Had these been admitted, the app would have ingested
gambling spam under the name of a probation service and an embassy. **This is an argument for
Stage B existing at all, independent of everything above.** A count is deliberately not given:
an automated proxy over the judges' own labels mixes real takeovers with judge noise, and the
named examples are the ones a human can check.

## What a correct rerun needs

1. **Two independent judges on the SAME neutral prompt** — not the corrective one, or agreement
   measures shared bias rather than shared signal. Admit only where they agree, and publish the
   disagreement rate as the axis's measured reliability.
2. **A canary set that spans `kind` for the rare classes too**, not only the dominant one.
3. **A decision on where a research institute belongs** — it is neither a journal nor a body
   publishing public records.
