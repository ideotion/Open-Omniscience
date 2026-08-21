# Release gate — v0.3.0 ("measured & verified")

**Status: OPEN.** This is the checkable inventory for closing the `0.3` cycle. The
version already reads `0.3.0` (the 2026-07-18 sequence: P0 pass → `v0.2.0` tag → flip),
so this gate governs **tagging**, not the version number.

**Ruling of record:** maintainer, 2026-07-20 — eight rows, all required before the tag.
Amended twice since; the amendment log is §3. The narrative board lives in
[`docs/CHANGES.md`](../CHANGES.md) under `0.3.0`; this file is the part you tick.

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
| 3 | Full diagnostics from the real corpus at release scale (~1M) | operator | **OPEN** — run queued |
| 4 | A committed full import that re-checks **all** sources | operator | **MOVED TO 0.4 — required there** (2026-08-13) |
| 5 | Article clean-up: discussed → agreed → implemented → **executed** | shared | **OPEN** — blocked on row 3 |
| 6 | DB-10 §1b page-size bench passed + the ruling made | maintainer | **CLOSED** (2026-08-13) |
| 7 | The `v0.2.0` P0 report's own follow-ups | operator | **OPEN** — two runs |
| 8 | Browser-verification bar | session | **CLOSED** (2026-08-13) |

Three rows remain: **3, 5, 7.** Rows 3 and 5 are one operator action apart (§2.5);
row 7 is two boots and a soak. Row 8 closed against its own literal wording; the larger
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

### Row 3 — full diagnostics at release scale · OPEN

**Bar:** one complete `all-diagnostics` bundle from the **real** corpus at its actual
release scale.

**Amended 2026-07-30:** the original bar said ~5 million articles. Withdrawn by the
maintainer — *"we won't be able to achieve the 5 million mark for the next release due to
the overall app speed"* — and replaced with **~1 million**, which the corpus has reached
(1,048,725 on 2026-08-12).

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

### Row 5 — the article clean-up · OPEN, blocked on row 3

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

**The only missing step is a decision, and row 3 delivers its input.**
`criteria-calibration.json` is already an all-diagnostics **bundle member**
(`src/api/diagnostics.py:3529`), so the diagnostics run queued for row 3 *contains* the
report row 5's execution is gated on. Sequence:

1. operator runs the bundle (row 3) →
2. session reads `criteria-calibration.json`, proposes criteria against real specimens →
3. **maintainer agrees the criteria** (this is the sign-off the bar names) →
4. operator runs the quarantine pass with `write=True` →
5. re-index clears the junk keywords and entities the quarantined articles contributed.

**Closes when:** step 4 has run and the report names how many articles were quarantined
under which criteria version. Nothing is deleted — quarantine is a reversible stamp, and
quarantined articles ride backup export/import as data.

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

### Row 7 — the `v0.2.0` P0 report's own follow-ups · OPEN

Two measurements the P0 report itself flagged as not-yet-confirmed. Both are operator runs.
**The step-by-step instructions are in
[`P0_VALIDATION_RUNBOOK.md`](P0_VALIDATION_RUNBOOK.md) → "Closing the two carried-forward
follow-ups".**

**(a) Cold-boot unlock at full scale.** The instrument was fixed on 2026-08-12 (PR #940):
`wal_bytes_before_open` returned `None` on *any* `OSError`, so an **absent** `-wal` (a real
measurement — nothing to replay) was indistinguishable from an unreadable one. A clean
shutdown checkpoints and *deletes* the `-wal`, so absent is the normal state after exactly
the boot the bar asks for — following the instructions guaranteed the null the report then
read as missing evidence. The three-state record now names which case it measured, so the
next run is bankable. The 2026-08-12 reading (323 ms against a 2000 ms bar) is already
comfortably inside; what it lacks is the *statement* that the boot was cold.

**(b) Multi-day collector soak.** The 2026-08-12 report shows **0 samples, 0 passes** and
honestly reports `not-measurable`. The last real reading (2026-07-29/30) covered ~22 h over
61 passes with no climb (+327 MB against a 512 MB floor) but was 4 days stale by report time.
The bar names a *multi-day* soak.

**Closes when:** one P0 report shows P0.4 with `wal_state_before_open.state = "absent"` and
a stated cold boot, and P0.3 with samples spanning ≥ 72 h.

---

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
