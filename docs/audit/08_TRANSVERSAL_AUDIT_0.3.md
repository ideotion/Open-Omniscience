# 08 — Transversal audit, 0.3 edition (2026-07-21)

> Maintainer-commissioned per **THE 0.3 CLOSE GATE, row 2** (`CLAUDE.md` ~line
> 6648): "a fully transversal audit of the entire repo... a new tool-by-tool
> edition for 0.3," following the `07_TRANSVERSAL_AUDIT_V01` precedent
> (2026-06-12). This edition inherits 07's frame and section skeleton but is
> **not a re-derivation from scratch** — it is scoped as a *delta audit*:
> (a) what happened to 07's own findings (§7 disposition, checkable against
> `docs/ledger/shipped.csv` and the `CLAUDE.md` ledger), and (b) a transversal
> pass over every surface that shipped since 07 (§8), read through the same
> lenses (method/truth/disclosure, tamperability, scale, missing data,
> neutrality, bias).
>
> **Honesty note on altitude, read before the tables below:** every claim in
> §7 and §8 traces to a module, PR, or ledger row this reviewer actually
> opened this session (named inline). Anything from 07 not re-opened this
> session is marked **carried forward, not re-verified** rather than
> silently repeated as if freshly confirmed — a plausible-sounding audit that
> outruns its own verification would give the gate false assurance, which is
> worse than a smaller honest one.

## 0. The honest frame (0.3 delta)

07's two truths still hold verbatim: the app's discipline (method+caveat+n,
no composite scores, fail-closed ethics) is the right spine; honesty labels
alone don't make outputs true or understood. What's different at 0.3: the
corpus went from a synthetic 6.4k-article performance sample to a **live
~500k-article corpus** (README "Status" section, 2026-07-21 read), an order
of magnitude past T1's synthetic sample, and 0.2's own P0 validation
separately stress-tested backup/restore at ~100–130 GB. Two concrete,
checkable deltas:

- **The DB-10 §1b page-size A/B bench (4K vs 16K)** hit and fixed a real
  defect this cycle: `2026-07-19,diagnostics — pagesize-bench encrypted-path
  fix` (shipped.csv) — a `WrongPassphraseError` on the 16384-page target
  traced to three stacked defects in the reopen path on an encrypted corpus
  (not a wrong passphrase). This is a genuine scale-readiness fix, but the
  bench itself is **explicitly still pending a large-corpus run** per gate
  row 6 — the fix makes the bench trustworthy, it does not constitute the
  ruling. **Not yet closed** — carried into §7/§9 as open.
- **07's proposed B3 (`perf_harness.py` extended to a 100k-article
  profile)** — no evidence found this session that `scripts/perf_harness.py`
  was extended past T1's 6.4k synthetic profile. The 500k-scale evidence
  that exists is qualitative (maintainer field reports triggering the
  restore/pagesize fixes above), not a repeatable harness run at that scale.
  **Status: not done** — this is the same gap gate row 3 (5M-article
  diagnostics) depends on, one order of magnitude further out.

The product surface also grew a new vertical (law) and a new hierarchy
layer (super-groups/GROUPS) that did not exist when 07 was drafted. The
question this edition asks is therefore sharper than 07's: **when a
synthetic-scale audit's findings meet a real half-million-article corpus,
which held, which broke, and which new surfaces were never audited at all
because they didn't exist yet?**

## 1. Tool-by-tool rationale — deltas only (see 07 for the full table)

07's 17-row M/T/G table is **carried forward, not re-verified this
session**, for every row not listed below — re-confirming e.g. the
astronomy/El Niño/custody rows would require the same depth of work 07 put
in, which this session's time budget does not support honestly. Rows that
changed or are new since 07:

| Tool | M | T | G | Note |
|---|---|---|---|---|
| Framing/tone (VADER, EN) + **subjectivity/loaded-language (rule-based, new)** | VADER unchanged; subjectivity engine is lexicon-based, descriptive-only (`src/analytics/subjectivity.py`, shipped 2026-07-12) | subjectivity emits `n_tokens/n_loaded/density/terms/spans` — never a composite score; a language with no lexicon returns `available:false` (honest gap), never a fabricated neutral | 🔶 partial fix: en/ru/ar lexicons only (Latin/Cyrillic/Arabic scripts), vetted-pending; VADER's English-only gap is *not* closed by this — it's a second, narrower engine covering 3 languages, not 07's called-for universal disclosure sweep | B1's VADER-English-only ask is still open; this is a parallel mitigation, not the fix |
| Keyword extraction — **CJK/Thai segmentation (new)** | jieba (zh)/janome (ja)/pythainlp (th), MIT/Apache-2.0, offline dictionary-only, shipped 2026-07-10 (`src/analytics/segmentation.py`) as an opt-in `[segmentation]` extra | closes 07 §6.3's "CJK segmentation is absent" bias finding *when the extra is installed*; core install stays honestly "unsegmented" | ✅ `managed.language_status()` reports `functional` only when the extra is present — the per-language honesty matrix 07 asked for (§6.3) now has a real mechanism, not yet a surfaced UI dashboard | Directly closes 07 finding B5/§6.3 bias #3, conditionally (extra must be installed) |
| Keyword families/lemmatization | lemmatization flipped **default-ON** 2026-07-18 (PR #715), gated on a maintainer precision review of `lemma_preview`, not an IR-harness A/B | families collapse lemma-adjacent surface forms for display only, reversible (opt-out byte-identical per its own test) — never touches retrieval/ranking (explicitly corrected in-repo: an earlier plan to A/B it via the retrieval harness was ruled incoherent) | 🔶 the *quality gate* for a default-on change is a maintainer eyeball pass, not a measured benchmark — worth naming as a methodology note, not a defect: the team recorded this distinction itself | New since 07; M is sound by construction (display-layer only) but the acceptance evidence is qualitative |
| Law vertical (new tool) | rule-based catalog validation (`scripts/validate_legal_catalog.py`) + per-jurisdiction coverage diagnostic (S5, PR #713) | verdict badges now show unflagged-by-default consolidated-statute changes truthfully (S2 fixed a real "looks broken" bug — large-change heuristics rarely trip on routine consolidated-statute edits) | ✅ S5's `GET /api/diagnostics/law-coverage` answers "is law tracking working?" per jurisdiction in the all-diagnostics bundle by default | S1 (live network acquisition) and S6/S7 (verified structured/RSS adapters) remain carry-over, unbuilt in-sandbox — same gap 07 didn't need to name because the vertical didn't exist yet |
| Super-groups / GROUPS layer / Leads family (new tool) | `src/analytics/supergroup_stats.py`: DISTINCT deduped member-keyword-id set resolved FIRST, fixing a real within-group double-counting bug the maintainer found on the live corpus export | rising/falling signal on a theme-level rollup — same descriptive discipline (net sum over keywords, no composite score) | 🔶 browser-unverified (frontend slices flagged per fork-3 in the shipping PRs) — the naming/circle-grammar/concept-map UI has not had a human click-through | New tool; sound method, disclosure intact, UI verification is the open gap (feeds gate row 8) |
| The Observatory (new, backend-only) | `configs/keyword_supergroup*` domain-scaffold field + a universe/galaxy data-spine endpoint (S0+S1, PR #724) | n/a — pure data-spine, no interpretive claim yet | design doc itself states the renderer (S2+) is "NOT conservative-flaggable" — explicitly gated on a maintainer click-through, not shipped | Correctly self-disclosed as browser-verify-gated in its own design doc; nothing to flag beyond confirming that gate is real and still open |

## 2. Tamperability — delta

07's assessment is **carried forward** (SQLCipher at rest is sound and
honestly scoped; custody/evidence chains are tamper-evident; the live DB is
writable by any process running as the user — known, unfixable at app
level, detection is the buildable lever). What changed:

- **Backup/restore integrity at scale got a real fix, not just a
  performance one.** PR #720 (2026-07-19, `fix(backup): parallelize + batch
  + report progress for the restore-merge re-index`) fixed a field-observed
  restore stall: the 14-step progress callback only covered `merge_corpus`,
  then `run_restore`'s re-index phase ran with **no progress signal at all**
  while writes trickled and the UI stayed frozen at "merging (14/14)" — a
  status-honesty gap adjacent to the airplane-mode paused-status bug fixed
  earlier in the ledger. This matters for tamperability/reliability
  jointly: an operator watching a frozen progress bar during a restore
  cannot distinguish a healthy slow re-index from a hung/corrupted one.
  Fixed by real progress phases, not just parallelization.
- **B2 (07's proposed local fixity audit: re-hash the corpus vs stored
  hashes, loud report)** — this reviewer found `src/integrity/fixity.py`
  and `src/verification/fixity.py` referenced only in a 2026-06-15 ledger
  row about an unrelated airplane-mode status fix; no dedicated
  standalone fixity-audit tool/endpoint was located this session. **Status:
  unconfirmed built — flagged for the maintainer to confirm or re-open**,
  not claimed done and not claimed absent (this reviewer did not open those
  two files' full contents this session; a grep-level pass is not sufficient
  evidence either way for a gate-facing document).

## 3. Performance after long use — delta

See §0 above (the DB-10 pagesize fix and perf_harness gap were folded there
to avoid duplicating the same two facts under two headings). Summary:
pagesize-bench correctness fixed, large-corpus bench run still pending
(gate row 6, open); perf_harness never extended past the T1 6.4k profile,
so gate row 3's 5M-scale diagnostics run has no intermediate checkpoint
(100k/1M) to de-risk it — the same gap named in 07, now more consequential
given the two-orders-of-magnitude jump it implies.

## 4. What data is missing? — delta

07's ranked list (§4: official statistics, scholarly+retractions,
fact-check-as-source, press-release-as-origin-detector, parliamentary/court
records, NGO/IGO reporting, deliberate social-media/video/satellite
exclusions) is **carried forward unchanged**. One item moved concretely:
item 5 ("parliamentary/court records... extends the law vertical") has a
real vertical to extend now — the law vertical (S1-S5, PR #701/#713) covers
statutes/gazettes/IP records across roughly 8 of ~12 world regions, but the
parliamentary/court-proceedings layer 07 named is still unbuilt; S6
(verified structured adapters) and S7 (verified gazette RSS) remain
carry-over per PR #713's own description. No other item in 07's list moved.

## 5. Neutrality & representation — delta

07's core position ("neutral" is undefinable absolutely; measure against
declared plural baselines, never auto-correct) is **carried forward
unchanged**. The proposed **"Your lens" dashboard (B4)** — plural-baseline
representation + single-origin share + wire-dependence share — was **not
found built** this session (only referenced aspirationally in `CLAUDE.md`
line 2367, restating the 07 finding, not describing a shipped surface).
Still open.

## 6. The aggregator's own biases — delta

07's 10-item list is **carried forward**, with one item concretely moved:

3. **Language-tooling bias — partially corrected.** 07 stated "CJK
   segmentation is absent: zh/ja keyword extraction is effectively
   nonfunctional." As of 2026-07-10 (§1 above), this is no longer
   unconditionally true: an opt-in `[segmentation]` extra makes zh/ja/th
   keyword extraction functional (measured on fixtures: whole-sentence
   over-tokenization → real recurring words, per the ledger row). The
   residual bias is now **install-conditional**, not structural — a core
   (extra-less) install still has the old gap, and the UI does not yet
   surface which install tier a user has (the honesty-matrix mechanism
   exists in `language_status()`, but no dashboard shows it to the user —
   the same gap named in §5's "Your lens" item). Recommend downgrading this
   from a structural bias to a **disclosure gap**: tell the user, in-app,
   whether their install has segmentation.

All other 9 items (catalog selection, permissive-host survivorship,
recency, lexical, popularity, user-selection loop, modality, geocoding,
Wikipedia systemic bias) are **carried forward, not re-verified this
session** — no evidence was sought or found either confirming or
contradicting them.

## 7. Disposition of 07's Action Plan B (checkable against the ledger)

| Item | 07's ask | Status this session | Evidence |
|---|---|---|---|
| B0 | Maintainer arbitrates severities into the RC gate | Superseded — 0.1 shipped, 07's findings folded into that cycle's work per ledger references; 0.3 gate (row 2) is this document | `CLAUDE.md` ~6648 |
| B1 | Disclosure sweep ×12 (VADER-EN label, LLM-artifact label, lexical-limits caveat, modality statement, CJK-capability honesty, survivorship sentence, "record begins" stamp, Wikipedia-bias note, etc.) | **Partial.** VADER-English-only disclosure was extended to at least one more UI surface (#an competitive panel, UI batch F, 2026-07-03). No evidence found this session of the LLM-output "model artifact" label, a "record begins" stamp, or a Wikipedia-systemic-bias manual note. Not confirmed as a completed sweep. | shipped.csv row 210; no counter-evidence found for the rest — absence of evidence, not evidence of absence, given session scope |
| B2 | Local fixity audit tool | **Unconfirmed** — see §2 | `src/integrity/fixity.py`, `src/verification/fixity.py` (contents not opened this session) |
| B3 | perf_harness 100k profile + consented-archiving design | **Not done** — see §3 | no `perf_harness.py` changes found past T1 |
| B4 | "Your lens" dashboard v1 | **Not built** — see §5 | only aspirational references found |
| B5 | CJK segmenter extra + per-language capability matrix in-app | **Half-shipped** — segmenter extra shipped (§1/§6); in-app matrix surfacing not found | `src/analytics/segmentation.py`, 2026-07-10 |
| B6 | Design notes only (cross-transport spot-check, archiving, source-onboarding order) | Not evaluated this session | — |
| B7 | Re-audit delta + alpha go/no-go | **This document is that re-audit**, scoped to 0.3 rather than the 0.1 alpha gate | — |

## 8. New surfaces since 07, audited transversally

Beyond the tool-table deltas in §1, four surface areas shipped since
07 that deserve their own transversal read:

1. **Law vertical (S1-S5).** Truth-in-UI fix (S2) is itself a neutrality-
   adjacent finding: a correctly-working tracker silently *looked* broken
   because a large-change heuristic tuned for other document types
   defaulted real changes to `flagged_only=True` and hid them — a case
   where an overly cautious default became a disclosure failure in the
   opposite direction (hiding true signal, not fabricating false signal).
   Worth naming as its own bias-adjacent pattern: **conservative-default
   bias**, where a safety default silently suppresses true information
   rather than over-claiming it. Not in 07's bias taxonomy (§6) — proposed
   addition for the next edition.
2. **Super-groups/GROUPS/Leads.** The double-counting bug
   `supergroup_stats.py` fixed (member keywords deduped to a DISTINCT set
   before summing) is exactly the kind of "the aggregator's own tooling
   bug masquerading as a signal" 07's frame warns about generally but
   didn't have a concrete instance of yet — a rising/falling supergroup
   Lead computed on double-counted totals would have been a fabricated
   trend. Now fixed; flagged here so the gate record shows it was a real,
   caught defect, not a hypothetical.
3. **Entity families + lemmatization default-ON.** Genuinely new
   methodological territory since 07: a *display-layer* text transform now
   defaults on for every user, verified by maintainer eyeball review of
   real output rather than a blind quantitative benchmark. This is an
   honest and explicitly-recorded methodology choice (the team itself
   corrected an earlier plan to A/B it via the retrieval harness, on the
   grounds that lemmatization doesn't touch retrieval) — flagged here not
   as a defect but as a precedent worth the maintainer's explicit attention
   at gate time: **is "reviewed by eye on real data" an acceptable
   evidentiary bar for a default-on change that touches every user's
   view of every keyword?** 07's whole audit exists to ask exactly this
   kind of question of every tool; this is the first "on by default,
   verified qualitatively" case since 07 and should get the same explicit
   arbitration 07's other findings got.
4. **The Observatory.** Correctly self-scoped — see §1. No finding beyond
   confirming the design doc's own gate ("browser-verify-gated, not
   conservative-flaggable") is a real, currently-open gate, feeding CLOSE
   GATE row 8.

## 9. Action Plan C — 0.3 edition

- **C1 · Close out B1's disclosure sweep properly** (carry-forward from 07,
  concretely unfinished per §7): confirm or ship the LLM-output
  "model-artifact — verify" label, the "record begins" stamp, and the
  Wikipedia-systemic-bias manual note; audit whether VADER-English-only
  disclosure reaches every surface that shows sentiment, not just the ones
  checked this session.
- **C2 · Resolve B2's fixity-tool status** (maintainer or a follow-up
  session with time budget to read `src/integrity/fixity.py` and
  `src/verification/fixity.py` in full): confirm whether a local
  re-hash-and-report tool exists, and if not, build it — this is the
  cheapest tamper-detection win still on the table two audit cycles later.
- **C3 · Surface the segmentation/capability matrix in-app** (closes the
  install-conditional gap named in §6): one panel/endpoint telling a user
  which languages their specific install can meaningfully analyze —
  reuses `language_status()`, which already computes this.
- **C4 · Extend `perf_harness.py` toward the 5M-article gate (row 3)**
  incrementally: a 100k-then-1M profile as checkpoints before the full 5M
  run, so gate row 3 isn't attempted cold at two orders of magnitude past
  the last measured point.
- **C5 · Name conservative-default bias as a taxonomy addition** (§8.1):
  add it to the next edition's §6 bias list, and audit other
  heuristic-default surfaces (triage thresholds, the change-detection
  heuristics elsewhere in the app) for the same failure mode — a safety
  default that silently hides true signal.
- **C6 · Arbitrate the lemmatization precedent** (§8.3): a maintainer
  ruling on whether "reviewed by eye on real data" is the accepted
  evidentiary bar for future default-on display-layer changes, so it isn't
  decided ad hoc per feature.
- **C7 · Build "Your lens" v1** (07's B4, still unbuilt): now has more
  substrate than it did at 07-time — supergroup stats, the law-coverage
  diagnostic, and the segmentation capability matrix (C3) are all
  computable inputs to a representation dashboard.
- **C8 · Re-audit delta for the next cycle**, same discipline: check this
  document's own C1-C7 against the ledger before writing edition 09,
  rather than re-deriving from first principles.

---

**Scope honesty, restated:** this edition verified §7 and §8 against named
modules/PRs/ledger rows opened this session. §1's carried-forward rows,
and all of §2-§6 not marked "delta," restate 07 without independent
re-verification this session — they are not re-confirmed, only repeated
with attribution. The maintainer arbitrating this into `RELEASE_0.3_GATE.md`
(gate row 2) should weight the §7/§8 findings as this session's actual
contribution, and treat everything else as exactly as fresh as 07 was.

— Audit drafted 2026-07-21, authored fresh this session (no prior draft of
this file existed in the repo, any worktree, or origin/main at start of
session — noted for the record since the commissioning brief assumed a
draft was already in progress).
