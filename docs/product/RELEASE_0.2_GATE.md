# Release gate — v0.2.0 ("the version that survives a 100 GB field run")

> **⚠ This record was reconstructed on 2026-08-13, after the fact.** No gate file existed
> during the `0.2` cycle — the conditions lived as a maintainer ruling in `CLAUDE.md` and
> were tracked there. This file is written from three sources that can each be re-opened
> and checked: the ledger entries, the git tag, and the P0 validation run the maintainer
> performed. **It is a record of what happened, not a document anyone ticked at the time.**
> Where a figure comes only from the ledger's transcription of an operator-side artifact,
> that is said inline.
>
> It exists so `0.2` and [`0.3`](RELEASE_0.3_GATE.md) can be read side by side, and so the
> next cycle inherits a format rather than re-inventing one.

**Status: CLOSED.** Tagged `v0.2.0` at
[`5b5452c15`](https://github.com/ideotion/Open-Omniscience/commit/5b5452c15b2f0ec702f4d15c1decf45ec28f6a51)
on 2026-07-18 (merge of PR #714).

---

## 1. The condition

**Ruled 2026-07-09** (maintainer, option "A"), after a live 4–5-day run grew the corpus to
~100–130 GB and exposed that *the app did not scale*:

> `v0.2.0` tags when backup-at-scale is verified on the live corpus + the collector OOM fix
> + unlock-at-scale land.

Restated by the maintainer as the cycle's whole identity: **"0.2 = the version that survives
a 100 GB field run."** Unlike `0.3`'s eight-row board, `0.2` had a single gate — the **P0
scale set** — with four numbered checks. That narrowness was deliberate: at the time the
backup tool *crashed the app* on a 100 GB corpus and there was no safe in-app copy path, so
data safety outranked everything else.

**The sequencing was mechanical, not merely procedural.** `release.yml` verifies
`tag == pyproject version`, so the tag had to be cut while `pyproject` still read `0.2.0`,
and the flip to `0.3.0` could only merge afterwards. A failed P0 run would have meant no tag
— the cycle was not closeable on a failed validation.

---

## 2. The P0 scale set

Push-button since 2026-07-12 (`src/monitoring/p0_validation.py`): one cancellable background
job drives the **real** backup engine against the operator's **own live corpus**, verifies
it, probes a staged restore without touching the live store, and reads the merged unlock and
collector instrumentation into one report with a per-check verdict against the written bars.

**Result — maintainer run, 2026-07-18: 5 pass · 0 fail · 0 not-measurable-here.**

| Check | Bar | Measured | Verdict |
|---|---|---|---|
| P0.1 backup, bounded RAM | RSS must not scale with the corpus | peak RSS **+440 MB** over a **2,522 MB** corpus (17.45%) | pass |
| P0.1 verify | manifest signature + every volume checksum | all volumes verified, parity intact | pass |
| P0.2 restore | staged restore + dry-run merge preview, live corpus read-only | `committed=false`, live corpus untouched | pass |
| P0.4 unlock | < 2000 ms | **602 ms** | pass |
| P0.3 collector | RSS climb under a 512 MB floor | **+166 MB** across 2 passes | pass |

**Provenance:** these figures are the ledger's record of an operator-side report
(`oo-p0-validation-*.json` on the maintainer's machine). The report artifact is not in the
repository — the corpus it measures never leaves it. The *mechanism* that produced them is
in-tree and test-covered.

**What the run did not close.** The report flagged two of its own results as
not-yet-confirmed: **cold-boot unlock at full scale**, and **a multi-day collector soak**
(P0.3 covered only 2 passes). These were carried forward and became **row 7 of the
[0.3 gate](RELEASE_0.3_GATE.md)** — still open today. Recording them here rather than
letting a "5 pass" headline imply more than it tested.

---

## 3. What actually landed in the cycle

The gate was one condition; the cycle was six consecutive autonomous sessions (S1–S6) plus
two parallel sessions (A/B). Compressed:

- **S1** the push-button P0 validation kit + runbook (the instrument this gate turns on).
- **S2** the P1 snappiness board — off-peak maintenance, the guard-coverage sweep,
  `/api/articles` off the event loop, the FTS over-fetch bound.
- **S3** the DB architecture — the gated persisted-columnar machinery, **adaptive backup
  volume sizing (DB-9)**, the DB-10 retention/vacuum memo whose §1b closed only in `0.3`.
- **S4** product quality — composite-string i18n (`OOI18N.tf`), the Leads carousel, the
  Insights-bar context absorption.
- **S5** decided-rulings and instruments — the USGS supply parser, the subjectivity engine,
  the IR gold-set builder.
- **S6** the backlog subset + the LLM-perception **eval harness** (the gate before any
  extraction).
- **A/B** the P0.4 unlock root-cause (`ensure_fts` ran an FTS5 `'rebuild'` on **every** boot
  — a corpus-scaled codec re-read; 28.6 s → 0.002 s on a 112k/2.7 GB synthetic corpus) and
  the offline `[segmentation]` extra for zh/ja/th.

**The P0.4 fix is why this gate closed at all.** Unlock-at-scale was one of the three named
conditions and was failing; a per-boot full FTS rebuild was the cause.

---

## 4. Tag-day: what went wrong, and the fix-forward

Recorded because it cost a broken release and the repair protects every later tag.

**Tag pushes are refused by the session git proxy** (HTTP 403 — branch refs only), which is
also why `v0.1.0` was never tagged from a session. The tag is cut from the maintainer's
machine.

**The collision.** The maintainer created the release through the GitHub **UI** (with the
tag, pre-release ticked). `release.yml` then ran: the suite passed, `tag == pyproject`
verified, sdist + wheel + `SHA256SUMS` built — and the publish step failed instantly on
`gh release create`, because the release already existed. **`v0.2.0` shipped with no
artifacts.**

**Fixed forward the same day.** The publish step is now idempotent: if the release exists it
`gh release upload --clobber`s the artifacts and appends the checksums to the notes only if
missing, leaving the maintainer's notes and pre-release flag alone; otherwise it creates the
release, with `--prerelease` automatic for `0.x` tags.

**The caveat that still applies to `v0.2.0` itself:** re-running an existing workflow run
uses the workflow *at the tag's commit* — the old, non-idempotent step. Recovering `v0.2.0`'s
assets means deleting the asset-less release (**keeping the tag**), re-running the failed
job, then re-ticking pre-release. The idempotent step protects `v0.3.0` onward.

**For the next tag:** push the **tag only**; never create the release through the UI.

---

## 5. Lessons this cycle wrote into the ledger

- **A verdict must map to the bar it actually tested.** A backup that merely *completes*
  below 2 GB — where bounded-RAM cannot be measured — must report `not-measurable-here`,
  never `pass`.
- **AND-gating two thresholds can hide a real signal.** A climb heuristic of
  `ratio > 1.5 AND abs > 512 MB` misses an OOM signature at a high baseline, and its reason
  string said "stayed flat" while the numbers rose.
- **A guard named for a safety property must enforce it.** A pass-through `_scrub` no-op
  gives false assurance; make it a real recursive redaction so secret-safety is a *property*.
- **A read-only diagnostic is only as good as its retention.** Reading a ~2 h-trimmed log
  cannot see a multi-day leak — state the window limit rather than letting the how-to promise
  more than the mechanism delivers.
