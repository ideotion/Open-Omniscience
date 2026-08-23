# Release gate — v0.3.0 ("measured & verified")

**Status: OPEN.** This is the checkable inventory for closing the `0.3` cycle. The
version already reads `0.3.0` (the 2026-07-18 sequence: P0 pass → `v0.2.0` tag → flip),
so this gate governs **tagging**, not the version number.

**Ruling of record:** maintainer, 2026-07-20 — eight rows, all required before the tag.
Amended twice since; the amendment log is §3. The narrative board lives in
[`docs/CHANGES.md`](../CHANGES.md) under `0.3.0`; this file is the part you tick.

**The sequence from here to the tag is [§7](#7-the-path-to-the-tag--what-is-left-in-order).**
One row remains and it needs a decision, not a measurement; §7.4
records what a session already verified, and what that is worth.

**How a row closes.** A row is `CLOSED` only when there is a **named artifact** — a
report file, a merged PR, a measured number — that a later reader can re-open and check.
"It was built" is not closure; the gate's own rule is *merged ≠ green ≠ verified*. A row
that cannot be measured here says so and names the operator step, rather than passing on
no evidence.

---

## 1. The board

| # | Row | Owner | Status |
|---|---|---|---|
| 1 | Source-management program implemented **and double-checked** | shared | **CLOSED** (2026-08-13) |
| 2 | Full transversal repo audit | session | **CLOSED** (2026-07-25) |
| 3 | Full diagnostics from the real corpus at release scale | operator | **CLOSED** (2026-08-23) |
| 4 | A committed full import that re-checks **all** sources | operator | **MOVED TO 0.4 — required there** (2026-08-13) |
| 5 | Article clean-up: discussed → agreed → implemented → **executed** | shared | **OPEN** — criteria proposed, awaiting sign-off |
| 6 | DB-10 §1b page-size bench passed + the ruling made | maintainer | **CLOSED** (2026-08-13) |
| 7a | Cold-boot unlock at full scale | operator | **CLOSED** (2026-08-23) |
| 7b | Multi-day (≥72 h) collector soak | operator | **MOVED TO 0.4 — required there** (2026-08-23) |
| 8 | Browser-verification bar | session | **CLOSED** (2026-08-13) |

**One row remains: 5**, and what it needs is a decision, not a measurement — the criteria
are proposed in that section from the 2026-08-23 field evidence, and the sign-off is the
one step that cannot be delegated.

Rows **3** and **7a** closed on 2026-08-23 against the release-scale instance (40,260
articles). The **~1M scale bar moved to `0.4`** with the instance it was written for
(maintainer: *"the 1M instance is NOT the v0.3 release-scale one"*), so row 3's bar is now
the corpus 0.3 actually ships against — see §5 for what that costs. Row 7b's ≥72 h soak
moved to `0.4` alongside row 4. Row 8 closed against its own literal wording; the larger
matrix its report's §4–§6 recorded as a stretch target was then **executed 2026-08-20**
(`docs/audit/UI_CLICKTHROUGH_2026-08-20.md` — all 17 themes, the Reader surface, a real
import fixture, the a11y axis with vendored axe-core, five lens drills, five standing
honesty-rule checks; 171 of 179 coverage rows verified, zero new P0/P1 outstanding).

---

## 2. The rows

### Row 1 — the source-management program · CLOSED

The 2026-07-20 program, each piece verified present in the tree on 2026-08-13:

| Piece | Where | Built in | Verified |
|---|---|---|---|
| Qualification lifecycle (admission gate · stamp · job · re-qualification ladder) | `src/catalog/qualification.py` | [#732](https://github.com/ideotion/Open-Omniscience/pull/732) | ✅ |
| Newsletter links → sources | `src/privacy/link_sanitizer.py` → `article_links` | [#733](https://github.com/ideotion/Open-Omniscience/pull/733) | ✅ |
| Airplane / Ollama gate split (loopback inference works offline) | `src/llm/ollama.py` | [#730](https://github.com/ideotion/Open-Omniscience/pull/730) | ✅ |
| Source-IP surfacing | `Article.server_ip`, rendered in `src/api/main.py` | [#733](https://github.com/ideotion/Open-Omniscience/pull/733) | ✅ |
| Discovery trail · citations tally · corpus filters | `src/discovery/cited_sources.py` | [#736](https://github.com/ideotion/Open-Omniscience/pull/736) | ✅ |
| Nav-soup prose gate | `src/services/prose_gate.py`, wired at `src/ingest/non_article.py:124` | [#737](https://github.com/ideotion/Open-Omniscience/pull/737) | ✅ |
| Post-import delta screen + persisted reports | import report + `_uxCorpusDeltaView` | [#731](https://github.com/ideotion/Open-Omniscience/pull/731) | ✅ |
| LLM triage / tag runs with the Claude-verification chain | `src/ai_layer/triage.py`, progressive sweeps | [#735](https://github.com/ideotion/Open-Omniscience/pull/735) | ✅ |
| Docs↔app reciprocity (USER_MANUAL chapters) | `docs/USER_MANUAL.md` §3.3, §3.9 | audit-09 fix-forward | ✅ (2026-07-25) |

Two columns, because they answer different questions: **Built in** is where the code
landed and can be re-read as a diff; **Where** is where it lives now and can be re-run.
The 2026-07-21 session that shipped eight of these recorded its own PR-by-PR notes — they
are preserved in §6, including the one gap it disclosed against itself (the last row was
*not* done that session, and closed four days later).

**The double-check clause was earned, not assumed.** This row's own wording — *field-confirmed,
not merely merged* — caught a real defect on 2026-07-24: the qualification lifecycle was
correct in isolation and did **not** survive a restore (`_merge_sources`' column allowlist
dropped the three stamp columns, and `source_qualification_attempts` had no handler at all),
so a merged-in source arrived `unqualified` — a plausible legal value, hence invisible — and
a **disqualified** source was laundered back into the trial queue with its backoff ladder
reset. Fixed the same day, with a completeness check so the class cannot regrow silently
(`_MERGE_NOT_CARRIED` + `tests/test_merge_completeness.py`).

**What closing this row does NOT claim.** The merge fix has unit coverage and was
behaviour-tested against a real two-corpus `merge_corpus`, but the *field* demonstration at
scale was row 4's job — and row 4 is now postponed. See §2.4 for exactly what that gives up.

**Explicitly out of scope** (maintainer-ruling-gated, zero code, does not block this row):
the Tor-exit-resolve (SOCKS `RESOLVE` / `0xF0`) path.

---

### Row 2 — the transversal audit · CLOSED

[`docs/audit/09_TRANSVERSAL_AUDIT_0.3_DELTA.md`](../audit/09_TRANSVERSAL_AUDIT_0.3_DELTA.md)
— a 23-agent orchestrated pass with every finding independently skeptic-verified. Two P0s
(the SOCKS-proxy airplane blind spot; the B6 eval gate reading the wrong report shape), four
P1s. **All ten Action-Plan-D items shipped 2026-07-25**, each with a regression test, several
stash-verified against the pre-fix code.

Re-run it before the tag only if the cycle's remaining work touches a non-negotiable.

---

### Row 3 — full diagnostics at release scale · CLOSED (2026-08-23)

**Bar:** one complete `all-diagnostics` bundle from the **real** corpus at its actual
release scale.

**Amended twice, and the second one is what closed it.** The original bar said ~5 million
articles; the maintainer withdrew that on 2026-07-30 (*"we won't be able to achieve the 5
million mark for the next release due to the overall app speed"*) and set ~1 million. On
**2026-08-23** they withdrew that too — *"the 1M instance is NOT the v0.3 release-scale
one"* — and the ~1M bar **moved to `0.4`** with the instance it describes. The bar this row
was always about is *the real corpus at the scale this release actually ships against*, and
that is the ~40k instance below.

**What this costs, stated rather than glossed:** every finding from this run is evidence
**at ~1M** and must be reported as such. Behaviour that only appears an order of magnitude
higher stays **unmeasured** for 0.3. The 5M bar returns as a later-cycle target once the
throughput work makes it reachable — the app's speed is why the bar moved, so the bar moves
back when the speed does.

**Operator step:** Settings → Diagnostics → the one all-diagnostics button, then send the
zip. The run journal (per-member begin/end, wall time, bytes, a runtime coverage block)
makes a long run diagnosable if it dies.

**Closes when:** the bundle exists, its manifest's coverage block shows every GET
diagnostic route as a member or a documented exemption, and no member reports
`skipped-deadline` for a reason that matters.

#### The bundle that closed it — 2026-08-23, 40,260 articles

`oo-alldiagnostics-20260823-101529.zip`, from the release-scale instance: **40,260
articles / 685,601 keywords / 810,462 mentions**, on 2 cores and 4.1 GB of RAM (Qubes,
i7-1065G7). 64 members in **1,139.9 s**, app `0.3.0`, schema head `6933c8d7c7b0`.

The manifest's runtime coverage block reads **`complete: true`** — 98 GET diagnostic
routes, 63 covered, 35 exempt, nothing unclassified, no stale classification, no missing
member. No member reported `skipped-deadline`. That is the bar, met.

**Two members errored, and the fix is in this PR.** `home-cards` and `card-audit` — 514 s
of the run between them — each finished its work and then raised *"Cannot operate on a
closed database"*, writing 0 bytes. It is the **same defect** the 2026-08-23 5,010-article
bundle surfaced (below), root-caused and fixed here: `statement_deadline` armed one raw
DBAPI connection and disarmed that same object in `finally`, while the briefing registry's
WAL guard closes its cursor and commits mid-scan by design. `leads-quality` survived this
time, which is the tell — whether the 30 s release lands inside a given member's scan is
timing, so the same bundle can lose two members on one instance and three on another.

Row 3 closes on the written bar (bundle · coverage · no deadline skips). The confirming
re-run on the fixed build is not a second gate — it rides the row-5 sitting, which needs a
post-fix `criteria-calibration.json` anyway.

#### The earlier 2026-08-23 bundle — what it settled, and what it did not

A bundle arrived from a **5,010-article** instance (2 cores, 3.7 GB, Qubes). It does not
meet this row's scale bar and is not treated as closing it — but it was worth its weight
twice over, because it exercised the *mechanism* and found two real defects.

**Settled — the bundle machinery works.** 64 members, 713 s, and the runtime coverage block
reads `complete: true`: 98 GET diagnostic routes, 63 covered, 35 exempt, nothing
unclassified, no missing members, no stale classification. That is the half of this row's
bar that is about the bundle rather than the corpus, and it holds.

**Not settled — the scale.** 5,010 articles is 0.5% of the ~1M bar. Every figure in it is
evidence at five thousand articles and is reported as such.

**Found — three members died, and the bundle's own journal is what said so.** `home-cards`,
`leads-quality` and `card-audit` — the only three that drive the producer registry, together
**400 s of the 713 s run** — each completed its work and then raised *"Cannot operate on a
closed database"*, writing 0 bytes. Root-caused, reproduced and fixed: `statement_deadline`
armed ONE raw DBAPI connection at entry and disarmed that same object in `finally`, while the
registry's WAL guard closes its cursor and commits mid-scan **by design** (every 30 s), which
on a NullPool bind closes the real handle. A teardown that can destroy the value of the work
it was guarding is worse than no guard. Fixing only the crash would have left the quieter
half — a progress handler is per-connection, so after the first reconnect the deadline was
**silently not enforced** (measured: a 1 s deadline let a runaway run 15.2 s), so the fix
re-arms on `after_begin` as well. Both halves are mutation-checked.

---

### Row 4 — a committed full import re-checking all sources · MOVED TO 0.4

**Ruled 2026-08-13** (maintainer): *"Rechecking all sources after the import will take
ages. We need to modify v0.3 release conditions and postpone it to v0.4."*

**Why it was in the gate.** It demonstrated three things at once: a **committed** merge at
scale (the 2026-08-12 P0 was `committed=false` by design — a self-restore where every row
reads as a duplicate), the qualification admission gate over every source including the
curated catalog, and the qualification stamp surviving a restore in the field.

**What 0.3 gives up by postponing it.** The backup/verify/staged-restore trio is *already*
validated at 8.3× the v0.2 scale (P0, 2026-08-12, 1,048,725 articles / 21.0 GB, 4 pass ·
0 fail · 1 not-measurable), so the data-safety core is not what is lost. What is lost is the
**committed** write path at scale and the field demonstration that the 2026-07-24 merge fix
holds on a real corpus.

**A split was proposed and DECLINED (2026-08-13).** The suggestion was to keep a single
*small* committed backup in `0.3` — cheap, and enough to demonstrate the stamps survive a
restore — postponing only the full ~1M source re-check. The maintainer declined: *"mark it
as a necessary step for v0.4, we won't do it today."* **The whole row moves, undivided.**

**It is not deferred, it is REQUIRED in 0.4.** See §5 — a postponed data-safety
demonstration that nobody writes down becomes a demonstration that never happens.

---

### Row 5 — the article clean-up · OPEN, criteria proposed, awaiting sign-off

**Bar:** discussed → **agreed** (explicit sign-off before execution) → implemented →
**executed** on the real corpus, removing the undesired-article class (nav soup, section
fronts, tag archives — *"a list, not an article"*).

**Built and verified present:**

- the **ingest door** — `prose_gate_verdict` (function-word density AND near-zero
  sentence punctuation, script-aware) stops new ones;
- the **retroactive quarantine** — `src/analytics/quarantine_job.py`, reversible, with a
  resumable cursor and an explicit `write=True` per call (the default is dry-run detection,
  and the mode is re-supplied on resume so a paused write-run can never silently become a
  dry run);
- the **calibration diagnostic** — `criteria_calibration` (`/api/diagnostics/criteria-calibration`),
  the top-N would-be-disregarded articles plus statistics and per-article detail.

**Steps 1 and 2 are done.** The release-scale bundle arrived (row 3), and the criteria are
proposed below against its specimens. Sequence:

1. ~~operator runs the bundle~~ → **done** (2026-08-23, 40,260 articles)
2. ~~session proposes criteria against real specimens~~ → **done**, below
3. **maintainer agrees the criteria** ← *this is where the row now sits*
4. operator runs the quarantine pass with `write=True`
5. re-index clears the junk keywords and entities the quarantined articles contributed

**Closes when:** step 4 has run and the report names how many articles were quarantined
under which criteria version. Nothing is deleted — quarantine is a reversible stamp, and
quarantined articles ride backup export/import as data.

#### The proposal — what to quarantine, and what to leave alone

Measured on the release-scale bundle: **40,156 articles scanned, 12 flagged (0.03 %)** by
the URL-shape rules, and after the detector fix in this PR, **8**.

**Tier A — the drop path, 8 articles. Proposed for execution.**

All eight are BBC Chinese-edition topic indexes (`bbc.com/ukchina/trad/topics/<id>`,
`bbc.com/zhongwen/…`), flagged `url_taxonomy` on an explicit `/topics` path segment — a
rule that keys on a literal segment rather than a heuristic, and `/topics/<id>` is
definitionally an index. Their measured English function-word density is **0.0** across
26–95 tokens: not one `the`, `of` or `and`. That is a real measurement rather than a gap —
`function_word_density` returns `(0.0, None)` for text it cannot read, and these returned
`en` — so two independent signals agree.

Two honest qualifications. The *sentence-punctuation* half is weak here and is not being
leaned on: an ASCII `[.!?]` counter reads low on a page whose Chinese content uses `。`
regardless of whether it is prose. And the fact that a BBC **Chinese** page's stored text
is predominantly *English* is itself the tell — the extractor captured the page shell
because there is no article body to capture.

**Tier B — the 451 index pages above the word guard. NOT proposed. Measure first.**

`index_pages_above_guard` counts **451** articles (1.12 % of scanned) that the ≥100-word
body guard *keeps* even though their URL is listing-shaped: 115 tier-1, 336 tier-2, the
largest single reason `/tag` taxonomy listings at 272. This is the population the clean-up
is actually for — Tier A is 8 articles against a 451-article problem.

It is not proposed because **their prose is unmeasured**. Quarantining 451 real-looking
articles on a URL rule alone, with no corroborating signal, is precisely the
"a probe's data distribution is part of the lookalike" trap: the ≥100-word guard exists to
protect genuine articles at listing-shaped URLs, and Tier A's corroboration does not
transfer to a population that cleared that guard.

#### Two findings about the instrument, recorded rather than fixed

Both concern the report's prose-gate arm, and together they are why Tier B has no evidence.

1. **In the bundle, the arm can never finish.** It is resumable by design
   (`prose_gate_after_id`), but the bundle member pins it to `prose_gate_after_id=0` with
   `limit=500`. So every bundle re-measures the same lowest-id 500 articles, `done` can
   never become `true` on any corpus larger than 500, and both 2026-08-23 reports stopped
   at `last_id: 695` having flagged 0. The per-batch denominator is honestly labelled; what
   misleads is that "resumable" reads as "will finish", and here it will not.
2. **It walks by id, not by the population under question.** Pointing it at the 451 would
   make Tier B decidable in a single run, instead of ~20 paginated calls over articles
   nobody has a question about.

Neither is fixed in this PR. The change is to a data-safety-adjacent instrument
immediately before a tag, and the standing rule is to park that with a written reason
rather than ship it fast — this is the reason.

**`CRITERIA_VERSION` is bumped to `nav-soup-v2`** in the same commit as the rule change,
because that stamp is what tells a future reader which detector generation flagged a
quarantined row; leaving it would have made `v1` mean two different detectors.

#### The earlier calibration report — how the detector fix was found

The first real `criteria-calibration.json` arrived (5,010-article instance). Reading it
against its own specimens is exactly why this row has a sign-off step, because on this
corpus the drop path proposed **four articles, and all four are false positives**:

| id | url | words | function-word density | flagged as |
|---|---|---|---|---|
| 2827 | `antiwar.com/news/?articleid=2504` | 49 | 0.33 | section landing `/news` |
| 4548 | `antiwar.com/news/?articleid=2444` | 46 | 0.28 | section landing `/news` |
| 4549 | `antiwar.com/news/?articleid=2776` | 76 | 0.32 | section landing `/news` |
| 4552 | `antiwar.com/news/?articleid=2637` | 77 | 0.37 | section landing `/news` |

A URL carrying `?articleid=2504` addresses **one article**; it is not a section front. And
0.28–0.37 function-word density is prose — nav soup measures around 0.05. `urlparse().path`
discards the query string, so an older CMS that puts the id there reached the
section-landing rule looking exactly like a section front. WordPress's own default permalink
(`/?p=12345`) hit the homepage rule the same way.

**Fixed** (`src/ingest/non_article.py`): a query parameter that reads as a record id vetoes
the two rules whose entire premise is that the URL names no item — homepage and section
landing. Deliberately narrow, because a mistake here quarantines a real article: the
parameter name must read as an id *and* its value must contain a digit, so `?page=2`,
`?tag=gaza` and `?s=query` rescue nothing, and the taxonomy and utility rules (which key on
an explicit path segment) are untouched. Both directions are tested and mutation-checked.

**The prose-gate arm produced nothing to calibrate against.** It is paginated: it scanned
**500 of 5,010** articles (`last_id: 695`, `done: false`) and flagged **0**. Continuing it
needs repeated calls with `prose_gate_after_id`.

**What IS real evidence here:** 116 index pages sit **above** the ≥100-word guard (2.32% of
the corpus) — 67 `/tag` taxonomy listings, 27 `/news` section landings, 22 tier-1. That is
the population this clean-up is actually for, and it is untouched by the fix above.

That run produced no criteria and a real detector fix, which is what the sign-off step is
for: proposing corpus-wide criteria from four specimens, all four wrong, would have been
the fabricated-confidence failure this gate exists to prevent. The release-scale report
above is the one the proposal is built on.

**Standing remainder, tracked but not gating:** the quarantine exclusion currently applies
in `_query_articles`; omnibar, watches, reporting and framing are still ungated.

---

### Row 6 — DB-10 §1b page size · CLOSED

**Ruled finished 2026-08-13** (maintainer: *"Let's consider this as finished"*).

**Evidence.** The `pagesize-bench` job ran on two live encrypted corpora (2.95 GB /
67,758 articles; 22.2 GB / 474,556 articles). **16384 wins every dimension at scale:**

| warm p50, 4096 → 16384 | 2.95 GB | 22.2 GB |
|---|---|---|
| index window | 510 → 334 ms (−34%) | 2525 → 1268 ms (−50%) |
| content band | −26% | −14% |
| rebuild | −23% | −37% |

The one shape 4K won at 3 GB (warm point lookups) **inverted** at 22 GB (0.459 → 0.203 ms,
16K 2.3× faster) — the 4K advantage was a cache-fit artifact, and the memo's
codec-granularity fear was outweighed exactly where it was feared.

**Shipped.** `src/database/connect.py` creates every new corpus with
`auto_vacuum=INCREMENTAL` (§1a) and `cipher_page_size=16384` (§1b), plus the reopen-hazard
candidate ladder — SQLCipher cannot discover page size from the file, so a store built at a
non-default size would otherwise read as a wrong passphrase on the next boot. Existing
corpora are untouched and migrate via the proven rebuild op when chosen (~10–17 s/GB).

By the §1a precedent, **merging was the ratification**; today's ruling makes that explicit.

---

### Row 7a — cold-boot unlock at full scale · CLOSED (2026-08-23)

**Ruled 2026-08-23** (maintainer): the ≥72 h soak moves to `0.4`; the cold boot stays here.
Splitting them is right — one is five minutes and the other is three days, and they were
only ever one row because the same report carries both.

Step-by-step in [`P0_VALIDATION_RUNBOOK.md`](P0_VALIDATION_RUNBOOK.md) §8.2. Stop the app
*cleanly* on the full corpus (the power button or `Ctrl-C`, never `kill -9`), start it,
unlock, and re-run the P0 validation immediately.

The instrument was fixed on 2026-08-12 (PR #940): `wal_bytes_before_open` returned `None`
on *any* `OSError`, so an **absent** `-wal` — a real measurement, meaning nothing to
replay — was indistinguishable from an unreadable one. A clean shutdown checkpoints and
*deletes* the `-wal`, so absent is the normal state after exactly the boot the bar asks
for: following the instructions guaranteed the null the report then read as missing
evidence. The three-state record now names which case it measured.

**Closed by `oo-p0-validation-20260823-100517.json`.** P0.4 reports **368.9 ms** against
the 2000 ms bar, with `wal_state_before_open` = `{state: "absent", bytes: 0}` and the
reason spelled out: *"no -wal file at open — a clean shutdown checkpoints and removes it,
so WAL recovery had nothing to do and is NOT part of this timing"*. Phases: `init_db`
366.9 ms, airplane guard 2.0 ms. The instance's own session forensics corroborates the
clean end independently (`previous_session: clean`, 05:45:56 → 07:51:20).

So the row has what it was missing: not a faster number, but the *statement* of which
shutdown preceded the boot. This is the steady-state unlock the bar asks for, on the
release-scale corpus.

**What it does not measure, by construction:** WAL recovery. A clean shutdown removes the
`-wal`, so the phase that grows with the corpus had nothing to replay. That is not a gap in
the run — it is what "steady-state" means, and the report says so in the same sentence.

---

### Row 7b — the multi-day collector soak · MOVED TO 0.4

**Ruled 2026-08-23** (maintainer): *"Postpone the >72h with the other P0 validation to the
v0.4 release."*

**What it is.** The 2026-08-12 report shows **0 samples, 0 passes** and honestly reports
`not-measurable`. The last real reading (2026-07-29/30) covered ~22 h over 61 passes with
no climb (+327 MB against a 512 MB floor) but was 4 days stale by report time. The bar
names a *multi-day* soak; 22 h is not one.

**What 0.3 gives up.** No evidence that memory stays flat across days of continuous
collection at release scale. The instrumentation exists and the shorter reading was clean,
so this is an unmeasured property rather than a suspected one — but unmeasured is what it
is, and the release notes say so.

**It is required in 0.4, not deferred.** See §5.

#### The 2026-08-23 run reported `fail`, and the detector was wrong

The release-scale P0 run returned **`fail`** on P0.3: *"collector RSS rose 1129 MB across
193 passes (1323 → peak 2452 MB) — over the 512 MB climb floor, the OOM signature."*
Re-derived from the report's own 193-pass series, that verdict does not hold:

| | |
|---|---|
| first / median / last pass | 1323 / 1371 / **1303** MB |
| passes above `first + 512` | **3 of 193** (1.6 %) |
| passes *below* the first pass | 71 of 193 |
| opening vs trailing fifth | 1364 → 1540 MB (**+176**, under the floor) |

That is a noisy plateau with three isolated excursions, not a climb. The detector computed
`peak - first` while its own method string promised *"a sustained absolute rise"* — and
`max()` cannot tell one excursion from a trend. Worse, the sampler is `psutil.Process()`
with **no argument**, i.e. whole-process RSS, so the app's own backup, restore and
diagnostics work lands in the collector's samples: the largest spike (06:19:32) sits
between two pre-restore snapshots the instance's forensics timestamps at 06:00:21 and
06:16:33. Running the P0 validation contaminates the very window P0.3 reads.

**Fixed in this PR.** The verdict is taken from the sustained level (trailing fifth minus
opening fifth); the peak and every above-floor excursion are still *reported*, with the
process-wide confound named, because an excursion is information even when it is not a
leak. Replaying the real 193-pass series through the fixed function returns **pass, +176
MB**, with the 3 spikes disclosed. The twin — a genuine sustained climb, and a leak that
saturates early and stays high — must still fail, and is tested; the mutation back to
`peak - first` reddens the field-case test by name.

**This does not close 7b.** A fabricated failure is exactly as dishonest as a fabricated
pass, and removing one is not the same as running the soak. The multi-day measurement is
still owed, in `0.4`.

### Row 8 — the browser-verification bar · CLOSED

**Bar:** either the AppVM `ui_walk` runner **standing**, or a **defined** hand click-through
of the flagship surfaces — Home/Leads · the analysis window · the post-import screen ·
source management · the one-button diagnostics panel.

**Closed against its own literal wording, 2026-08-13, by the brief's own session
(`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-08-13_UI_CLICKTHROUGH.md`).** The runner now
**stands**: `src/monitoring/ui_walk_playwright.py` is a real, merged, Playwright-backed
`UiWalkDriver` (31 passing regression tests), re-runnable by any future session via
`scripts/ui_clickthrough_run.py`. It drove a live Chromium against all three of the brief's
test states — virgin, empty/catalog-seeded, and a **450-article synthetic corpus seeded
through the real `index_article` chokepoint** (`scripts/ui_clickthrough_seed.py`, not a
shortcut) — over 53 walk steps and 87 coverage rows. Full report:
[`docs/audit/UI_CLICKTHROUGH_2026-08-13.md`](../audit/UI_CLICKTHROUGH_2026-08-13.md) ·
[`findings.csv`](../audit/ui-clickthrough-2026-08-13/findings.csv) ·
[`coverage.csv`](../audit/ui-clickthrough-2026-08-13/coverage.csv).

**The gate's literal "Closes when" clause, checked directly:**

| Clause | Met? |
|---|---|
| The report exists | ✅ — `docs/audit/UI_CLICKTHROUGH_2026-08-13.md` |
| Every flagship surface has a verification stamp | ✅ — all 5 (Home/Leads, the analysis window, the post-import screen, source management, the diagnostics panel) carry a coverage row and evidence screenshot |
| Each P0/P1 finding is either fixed or recorded with a reason | ✅ — the one P0 (post-import screen content, no import ran — by design, out of this session's scope) and both P1s (a re-confirmed known-open 2026-07-22 item; a genuinely new 375px top-bar overflow) are each recorded with a stated reason, not silently dropped |

**Building the standing runner surfaced seven distinct harness bugs** (navigation-grammar
gaps between the harness's `Surface` definitions and the app's *current* chrome, plus a
launch-contention timing race in the harness's own state-A checks) — all fixed, all
regression-tested, none an application defect. Full detail in the report's §1.

**What closing this row does NOT claim — read before treating this as full-matrix
coverage.** The brief's own §6 names a substantially larger ambition than a single session's
default-axis pass can cover: **15** named surfaces, **17** themes, **12** locales, and an
a11y axis (axe, keyboard traversal, focus visibility, `prefers-contrast`). This session
covered 9 of the 15 named surfaces fully at their default axis, 5 partially (the surface
opens and renders, but a named sub-capability inside it was not independently drilled), and
**1 — the standalone article Reader (tabs, provenance classes, Loaded-language) — not at
all**; it met the brief's own stated *floor* for locales (4: en/fr/ar/zh) and breakpoints
(all 4), fell short of the stated floor for themes (5 of ≥9 minimum), and did not build the
a11y axis. Of the brief's 9 named honesty-critical verification techniques (§5), only 2
(composited-pixel contrast; `::after` inheritance-leak spot-check) were exercised. The
report's §4–§6 give the complete, itemized reconciliation; §8 gives the ordered follow-up
list. None of this was silently dropped — it is why this row closes against its own literal
bar rather than against the brief's fuller ambition, which is recorded as a stretch target
for a future session, not a condition of this cycle.

**The stretch target was executed 2026-08-20** (a dedicated matrix-expansion session, report
[`docs/audit/UI_CLICKTHROUGH_2026-08-20.md`](../audit/UI_CLICKTHROUGH_2026-08-20.md) ·
[`findings.csv`](../audit/ui-clickthrough-2026-08-20/findings.csv) ·
[`coverage.csv`](../audit/ui-clickthrough-2026-08-20/coverage.csv)). What it added over the
row-closing run, per the 2026-08-13 report's own §8 order: the **375px top-bar overflow
(P1) fixed** with before/after evidence and the runner's 375px flagship walk green on all
five surfaces; a **fourth test state (D)** exercising the post-import screen's real content
path through an actual volumes-backup import (never the live corpus); the **Reader**
surface fully drilled (11 tabs, provenance classes, Loaded-language); the theme axis at
**all 17 themes** — which found and fixed the AI pill's ai-off label below AA on 13 of 17;
five **lens/sub-panel drills** (world-map sub-controls, the task manager's five sub-panels,
the AI pill's painted states, Bulletin gate→override→generate→review, Agenda provenance —
finding and fixing corpus-deduced events invisible at default filter settings); the **a11y
axis** from scratch (axe-core 4.13.0 vendored + sha256-registered, keyboard-only traversal,
`prefers-contrast`; one serious finding fixed app-side, five P2s filed); and **5 of the 9**
honesty-rule checks now standing as automated instruments (greyscale mid-interaction from
pixels, RTL by rendered x-position, uppercase-no-op across five locales, exact-text-node
i18n walking, the class-with-no-rule sweep) with a sixth practiced manually. 179 coverage
rows (171 verified · 6 partial · 2 blocked), 23 findings (15 POSITIVE · 7 P2 filed · 1 P1
re-check of a known-open item), **zero new P0/P1 outstanding**. Still out of scope, stated
there: the 12-locale full sweep (4 covered), adversarial screenshot reading (rule 9), and
the AppVM/Gecko bar — every stamp remains "Chromium-verified (remote sandbox) · awaiting
human UX pass".

---

## 3. Amendment log

| Date | Amendment | By |
|---|---|---|
| 2026-07-20 | Gate created — eight rows | maintainer |
| 2026-07-25 | Row 1's docs↔app clause satisfied (USER_MANUAL §3.3/§3.9) | audit-09 fix-forward |
| 2026-07-25 | Row 1 scope: Tor-exit-resolve explicitly excluded | audit-09 §8 |
| 2026-07-30 | Row 3: the 5M bar **withdrawn**, replaced by ~1M | maintainer |
| 2026-08-13 | Row 4 **moved to 0.4** — the full source re-check is too slow | maintainer |
| 2026-08-13 | Row 4: the proposed small-committed-backup split **declined**; the row moves undivided and is **required in 0.4** (§5) | maintainer |
| 2026-08-13 | Row 6 **closed** — §1b ratified explicitly | maintainer |
| 2026-08-13 | Rows 1 and 2 marked closed against named artifacts; this file created | session |
| 2026-08-13 | Row 8 **closed** against its own literal wording — the standing Playwright `ui_walk` runner shipped, drove all three test states, all 5 flagship surfaces stamped, every P0/P1 fixed-or-recorded; the fuller 15-surface/17-theme/12-locale/a11y matrix from the brief's §6 is explicitly NOT fully covered and is recorded as a stretch target, not a condition of this row | session |
| 2026-08-13 | A **second** gate board (repo root, 2026-08-04) found and **absorbed** into §6; the root file removed. This file is the only 0.3 board | session |
| 2026-08-23 | Row **7 SPLIT**: 7a (cold boot) stays in `0.3`, **7b (the ≥72 h soak) moves to 0.4** alongside row 4 — *"Postpone the >72h with the other P0 validation to the v0.4 release"* | maintainer |
| 2026-08-23 | First real diagnostics bundle read (5,010-article instance). Does **not** meet row 3's ~1M bar, but its coverage block is `complete: true` and it found two defects: three producer-driven members died at `statement_deadline` teardown (400 s of a 713 s run, 0 bytes each), and the row-5 drop path proposed 4 specimens that were 4 false positives. Both fixed; §7.1 folds rows 7a/3/5 into one operator sitting | session |
| 2026-08-23 | **§7 added — the path to the tag**: the three open rows sequenced (row 5 consumes row 3's output), the tag mechanics corrected for `0.3` (no branch rename; `pyproject` already `0.3.0`; the tag is cut from the maintainer's machine because the session git proxy refuses tag pushes; never create the release in the UI), and §7.5 recording a full pre-tag gate run at `edfed14` — 8390 passed, mypy 0/482, blocking ruff + bandit + pip-audit clean, all three i18n gates unchanged at their ratchets. Every CLOSED row's named artifact re-verified present in the tree the same day | session |
| 2026-08-23 | **Ruled** (maintainer): *"the 1M instance is NOT the v0.3 release-scale one, postpone this milestone to the v0.4 release."* Row 3's ~1M bar moves to `0.4` with the instance it describes; the row's bar becomes the corpus `0.3` ships against | maintainer |
| 2026-08-23 | **Row 3 CLOSED** against `oo-alldiagnostics-20260823-101529.zip` — 40,260 articles / 685,601 keywords / 810,462 mentions on 2 cores + 4.1 GB, 64 members in 1,139.9 s, runtime coverage `complete: true` (98 routes, 63 covered, 35 exempt, 0 unclassified), no `skipped-deadline`. Two members (`home-cards`, `card-audit`) errored on the `statement_deadline` defect fixed in this PR | operator + session |
| 2026-08-23 | **Row 7a CLOSED** against `oo-p0-validation-20260823-100517.json` — P0.4 **368.9 ms** vs the 2000 ms bar with `wal_state_before_open.state = "absent"`, i.e. the steady-state cold boot the bar asks for, corroborated by the instance's own `previous_session: clean` | operator |
| 2026-08-23 | **P0.3 reported `fail` and the detector was wrong.** `peak - first` fired on 3 of 193 passes (1.6 %) while first/median/last were 1323/1371/1303 MB, against a method string promising *a sustained rise*; the sampler is process-wide, so the largest spike sits between two of the app's own pre-restore snapshots. Verdict moved to the sustained level, excursions still reported; replaying the real series returns pass at +176 MB. Row 7b stays in `0.4` — a fabricated failure removed is not a soak run | session |
| 2026-08-23 | **Row 5 criteria PROPOSED** from the release-scale report: Tier A = the 8-article drop path (`/topics/<id>` indexes, measured 0.0 function-word density) for execution; Tier B = the 451 index pages above the word guard, explicitly **not** proposed because their prose is unmeasured. `CRITERIA_VERSION` bumped to `nav-soup-v2`. Two instrument findings recorded, not fixed: the bundle's prose arm always restarts at id 0 so it can never finish, and it walks by id rather than by the population in question | session |
| 2026-08-23 | **Session forensics gains a text rendering** — `forensics.render_text`, a dated `.txt` on `?download=1`, and `session-forensics.txt` beside the JSON in the bundle (field ask). A deliberate, reasoned exception to the 2026-07-20 button-consolidation ruling | session |
| 2026-08-20 | Row 8's **stretch matrix executed** — 375px P1 fixed, state-D import fixture, Reader drilled, all 17 themes (ai-off AA fix), five lens drills (agenda deduced-events fix), a11y axis (axe vendored; #oo-tip fix), 5 of 9 honesty rules automated; `docs/audit/UI_CLICKTHROUGH_2026-08-20.md`. The row was already closed; this discharges the recorded stretch target | session |

---

## 4. Not in this gate

Recorded so a future reader does not mistake absence for oversight:

- **The 146-entry Open queue** in `CLAUDE.md` — the deeper backlog. None of it blocks a tag.
- **The five new verticals** (IP/patents · PubMed · climate · war/defense · elections) — the
  `0.5`–`0.8` steps of the [V1 pathway](../design/V1_PATHWAY_2026-07-14.md) §3.
- **The Observatory** — designed, browser-gated, prerequisites unmet.
- **Windows / macOS install paths** — Debian is the target (ruled 2026-06-17); the macOS CI
  lane stays observation-only.
- **Tor-exit-resolve** — assessed, zero code, ruling-gated.
- **The 5M-scale diagnostics** — deferred with row 3's amendment, not abandoned.
- **Row 8's fuller matrix** — **largely discharged 2026-08-20**
  ([`docs/audit/UI_CLICKTHROUGH_2026-08-20.md`](../audit/UI_CLICKTHROUGH_2026-08-20.md)):
  the Reader surface, all 17 themes, the a11y axis, the import fixture, and 5 of 9
  honesty-rule checks now stand. Still outside any gate: the 12-locale full sweep (4
  covered), adversarial screenshot reading, and the AppVM/**Gecko** verification bar —
  every stamp is Chromium-in-sandbox, awaiting a human UX pass.

---

## 5. Carried to 0.4 — required, not merely deferred

When the `0.4` gate is stood up, it **starts from this list**. Each entry names what it was,
why it moved, and what closes it — so nobody re-derives the reasoning or, worse, quietly
drops it.

A postponed data-safety demonstration that nobody writes down becomes a demonstration that
never happens. This section is the write-down.

### 3-at-scale · Diagnostics on the ~1M-article instance

**What it was.** Row 3's bar, from 2026-07-30 until 2026-08-23: one all-diagnostics bundle
from a corpus of ~1 million articles.

**Why it moved.** The maintainer ruled that the ~1M instance is not the machine `0.3` ships
against, so the bar was describing a different release than the one being tagged. Row 3
closed instead against the real release-scale instance — 40,260 articles.

**What `0.3` gives up, stated rather than glossed.** Every figure in the 2026-08-23 bundle
is evidence **at forty thousand articles**, and must be read as such. Anything that only
appears an order of magnitude higher — a member that finishes in 19 minutes here and does
not there, a query whose plan flips, a memory profile that only bends at scale — is
**unmeasured** for `0.3`, not measured-and-fine. The two members that died in this bundle
are a reminder that the run is where such things surface.

**What closes it in `0.4`.** One bundle from the ~1M instance whose coverage block reads
`complete: true`, on a build carrying the `statement_deadline` fix, with every member
non-zero. The P0 data-safety trio has already been read at that scale (2026-08-12:
1,048,725 articles, 21.0 GB, backup RSS +1.4 %), so what is owed is the *diagnostics* run,
not the safety evidence.

### 4 · A committed full import that re-checks all sources

**Was:** row 4 of this gate. **Moved:** 2026-08-13 — the full source re-check *"will take
ages"*. A split (keep a small committed backup here, postpone only the re-check) was
proposed and **declined**; the row moves undivided.

**What it must demonstrate in 0.4** — three things, and the ordering matters, because each
later one depends on the earlier one having actually run:

1. **A committed merge at scale.** Every P0 restore so far ran `committed=false` — a
   self-restore in which every row reads as a duplicate. The committed write path at ~1M
   articles has never been exercised in the field.
2. **The qualification admission gate over every source**, the curated catalog included —
   no grandfathering (ruled 2026-07-20). A catalog source that fails is a
   **catalog-review** signal, not a source to exempt.
3. **The qualification stamp surviving a restore.** This is the load-bearing one. On
   2026-07-24 `_merge_sources`' column allowlist dropped the three stamp columns and
   `source_qualification_attempts` had no handler, so a merged-in source arrived
   `unqualified` — a plausible legal value, therefore invisible — and a **disqualified**
   source was laundered back into the trial queue with its backoff ladder reset. It is
   fixed and unit-covered; what is missing is the field proof.

**Closes when:** one committed import at release scale reports the source verdicts it
stamped, and a spot-check confirms a previously-**disqualified** source is still
disqualified afterwards. That last clause is the whole point — a pass that only counts
`qualified` rows cannot see the inversion this row exists to catch.

**Cheaper substitute, if 0.4 also finds the full run too slow:** a *small* committed backup
demonstrates (1) and (3) in minutes; only (2) genuinely needs the full corpus. Recorded so
the option does not have to be re-invented — declined for 0.3, still available later.


### 7b · A multi-day (≥72 h) collector soak

**Was:** the second half of row 7 of this gate. **Moved:** 2026-08-23 — *"Postpone the >72h
with the other P0 validation to the v0.4 release."* The cold-boot half (7a) stayed, because
it is five minutes and this is three days.

**What it must demonstrate in 0.4:** memory flat across ≥72 h of continuous collection at
release scale — P0.3 with samples spanning the window and no climb against the 512 MB floor.

**Read both signals, not just the rate.** The collect-perf log retains roughly two hours, so
P0.3 only ever sees the recent window; the durable multi-day evidence is the app **surviving**
— the memory guard not stuck engaged, and the previous session ending cleanly in session
forensics. A pass on the rate alone would be a verdict about two hours wearing a three-day
label.

**Closes when** one report shows P0.3 with samples spanning ≥ 72 h and no climb.

---

## 6. Appendix — the 2026-07-21 session record (absorbed)

> **Absorbed 2026-08-13.** This was a *second* `RELEASE_0.3_GATE.md`, at the repo **root**,
> created 2026-08-04 ([#738](https://github.com/ideotion/Open-Omniscience/pull/738)) by the
> multi-lane session that built the autonomously-actionable half of the gate. This file was
> then created on 2026-08-13 without noticing it, leaving the repo with two boards that
> immediately began to disagree — the root one still read row 6 as *"ruling not yet
> formalized"* and row 3 against the withdrawn 5M bar. The row-8 session
> ([#957](https://github.com/ideotion/Open-Omniscience/pull/957)) spotted the split and did
> the right half of the fix: it pointed the root file's header at this one as authoritative,
> and noted that the root's row-1 sub-feature breakdown *"is not duplicated there"*. This
> section is what makes that no longer true, and therefore what makes deleting the file safe.
> **§1 is the live board and supersedes the status column that file carried.** What is kept
> below is the part that does not go stale: the evidence, the disclosed gaps, and one
> genuinely reusable merge fact.

**The honesty boundary that session set for itself** — worth keeping verbatim, because it is
the same bar §1 uses: every PR went *built → self-tested (pytest/ruff/mypy/i18n) →
independently code-reviewed → merged*. None of that is field-confirmed, browser-verified, or
run at scale; those bars belong to the maintainer or a later session.

**It disclosed a regression against itself.** [#737](https://github.com/ideotion/Open-Omniscience/pull/737)
added a `run_prose_gate_selftest` harness without registering it in `recursive_loop.py`'s
`LOOP_SELFTESTS`, which `tests/test_recursive_loop.py` enforces — so `main` broke after it
merged. Not a merge conflict: a real gap the PR's own targeted tests did not cover. Recorded
there as *"fixed in #739, still open at the time of writing"*; **#739 has since merged** —
verified 2026-08-13, `recursive_loop.py:59` carries the entry.

**The merge fact worth reusing.** Ten PRs from one session all appended to the same
append-only `docs/ledger/shipped.csv` from the same base, so every merge after the first
would have conflicted there. The fix was `.gitattributes` (`docs/ledger/shipped.csv
merge=union`) — **and the ordering is the load-bearing part**: the attribute only helps once
it is already on the side being merged *into*, so the very first PR to introduce it cannot
benefit from its own fix. Two structural conflicts (not appends) were resolved by re-basing
rather than hand-editing: `test_repo_invariants.py` between #727 and #735, and all 12 locale
files between #736 and #731. All ten merged cleanly in the recorded order, confirming it held.

**What that session deliberately did not attempt** — all still true, and all still open or
moved: any run at real corpus scale (rows 3, 4), executing the clean-up or making the
page-size ruling (rows 5, 6 — both maintainer-gated at the time; row 6 has since closed),
the soak and cold-boot (row 7), and claiming the `ui_walk` runner standing (row 8).

**Outstanding item it surfaced**, independent of this gate and still queued:
[#728](https://github.com/ideotion/Open-Omniscience/pull/728) — a findings brief from a real
475K-article diagnostics export (two endpoints with a severe p95/p99 tail, a missing hard-link
on "rising" Home Lead cards, an unexplained 2026-07-11 stall cluster, five sources at 100%
outlier rate).

---

## 7. The path to the tag — what is left, in order

**One thing is left before the tag: you agree the row-5 criteria.** Everything else that a
session can do is done, and §7.4 records the evidence.

Rows 3 and 7a closed on 2026-08-23 against the release-scale instance; rows 4, 7b and the
~1M diagnostics bar are in `0.4` (§5). Step-by-step mechanics for any run live in
[`P0_VALIDATION_RUNBOOK.md`](P0_VALIDATION_RUNBOOK.md); this is the sequence, not a
duplicate of it.

### 7.1 Row 5 — agree the criteria, then run the pass

1. **Read the proposal** in row 5. Tier A is 8 articles — BBC `/topics/<id>` indexes, an
   explicit-path-segment rule, corroborated by a measured 0.0 function-word density. Tier B
   (the 451 index pages above the word guard) is deliberately **not** proposed: their prose
   is unmeasured, and that is the whole population the clean-up is for.
2. **Agree, amend, or decline.** This is the sign-off the bar names and the one step that
   cannot be delegated. Declining Tier A is a legitimate outcome — 8 reversible stamps is a
   small clean-up, and the honest reason to run it is that the criteria then exist and are
   proven end to end, not that 8 articles matter.
3. **Run the quarantine pass with `write=True`**, then re-index to clear the keywords and
   entities those articles contributed.

**Closes when** step 3 has run and the report names how many articles were quarantined
under which criteria version — now `nav-soup-v2`.

### 7.2 Before any of it: land this PR

The bundle you sent lost `home-cards` and `card-audit` to the `statement_deadline` defect,
and the calibration report you sent came from the pre-fix detector. Both fixes are in this
PR. So a re-run on the fixed build is worth one button press — it confirms row 3's two
errored members are gone and gives Tier B its first prose measurement — but nothing is
*blocked* on it: row 3 closed on the written bar, and row 5's decision is Tier A, which the
fix does not change.

### 7.3 Tag day

**Do not start this until 7.1 is done and row 5 is ticked in §1.** A row closes
on a named artifact, never on "it was built".

1. **Every row closed.** §1 shows rows 1, 2, 3, 5, 6, 7a and 8 closed, with rows 4, 7b and
   the ~1M diagnostics bar recorded as moved to `0.4` (§5). Any open row blocks the tag.
2. **No version edit is needed.** `pyproject.toml` already reads `0.3.0` (single source of
   truth, set 2026-07-18 by the P0-pass → `v0.2.0`-tag → flip sequence), and
   `README` / `CONTRIBUTING` / `CHANGES` are already written for the post-tag state.
   **The branch rename step from the `v0.2.0` checklist does not apply** — the default
   branch is permanently `main`.
3. **CI green at the exact SHA you will tag.** "Merged" is not "green": the default
   branch's runs are usually `cancelled`, because each merge supersedes the last. Dispatch
   `ci.yml` (`workflow_dispatch`) on that commit and **watch it to completion**. The
   Windows lane is observation-only and may hang for hours — it does not block; the
   blocking lanes are what must be green.
4. **Cut the tag from your own machine.** A session cannot: this repo's git proxy refuses
   tag pushes (HTTP 403 — branch refs only), which is also why `v0.1.0` was never tagged
   from one.
   ```
   git fetch origin main
   git tag -a v0.3.0 <sha> -m "v0.3.0 — measured & verified"
   git push origin v0.3.0
   ```
5. **Push the tag, and nothing else.** Do **not** create the release in the GitHub UI. At
   `v0.2.0` a UI-created release made the workflow's `gh release create` fail instantly and
   the release shipped with **no artifacts**. `release.yml` is now idempotent and would
   recover — but only for a tag whose workflow runs the *current* file, so the simple path
   is to let the workflow create it.
6. **`release.yml` then does the rest**, in this order: the full `pytest -q` suite, a
   `tag == pyproject version` check, `sdist` + `wheel` + `SHA256SUMS`, and a GitHub Release
   marked pre-release automatically (any `0.x` tag is an alpha by the project's own
   maturity ladder). A red tree or a mismatched tag stops it before publishing.
7. **Verify the published assets** against the release's own `SHA256SUMS`. Checksums only —
   there is still no signing key, which is a tracked future item and stated in the notes.

### 7.4 What a session verified, and what that is worth

Run on the tree that would be tagged:

| Gate | Command (verbatim from `ci.yml`) | Result |
|---|---|---|
| Tests | `python -m pytest -q` | **8415 passed**, 43 skipped, 0 failed |
| Blocking lint | `ruff check --select=F,B --extend-ignore=B008 src/ tests/` | clean |
| Types | `python -m mypy src/` | **0 errors**, 482 files |
| SAST | `bandit -r src/ -ll -q` | clean |
| Dependencies | `pip-audit --skip-editable` | no known vulnerabilities |
| i18n completeness | `scripts/i18n_report.py --min 100` | 2987/2987 × 12 locales |
| i18n ratchet 1 | `--max-untranslatable 561` | 561 — **unchanged**, not merely under |
| i18n ratchet 2 | `--max-unkeyed-t-calls 298` | 298 — **unchanged**, not merely under |

The pass count carries its own proof twice: 8390 → **8406** is exactly the 16 tests this
pass added, and 8406 → **8415** is exactly the 9 that arrived with `origin/main`'s
Windows-on-ARM work. A change that adds tests and reports an unchanged total has a harness
that never ran it — and a merge that reports only one side's total ran only one side.

The two ratchets are maxima, so "under the bar" is not evidence — a *shrinking* measured
population reads the same as an improving codebase. Both were checked for being
**identical**, which is the only reading that means anything.

**What this is not.** It is a clean tree, not a validated release. Every one of these runs
in a sandbox against synthetic data; none of them touches your corpus, your hardware, or a
browser you would ship to. That is exactly the gap rows 3, 5 and 7 exist to close, and why
they cannot be delegated.
