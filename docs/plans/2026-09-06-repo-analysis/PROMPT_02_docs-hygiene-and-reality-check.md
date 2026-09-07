# Prompt 02 — Documentation hygiene and the reality check

> **Scope:** documentation only. Not one line of `src/`.
> **Gated on:** A4 (how far the FUTURE_DEVELOPMENTS reality-check may go), L8.
> **Sequencing:** early, and ideally before the feature prompts — several of them will otherwise be misled
> by exactly the stale claims this prompt removes.

## 0. Working mode

Read `_WORKING_MODE.md`. Then read the two plan documents this prompt finishes:
`docs/design/ACTION_PLAN_2026-07-17_DOCS_REVIEW.md` and
`docs/design/ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`.

**Read them the way this analysis had to: as claims.** The 2026-07-22 plan lists a set of items as open that
were built within two days of it being written, and the 2026-07-17 plan's tasks T1, T2, T3, T5 and T6 are all
done. A session that trusts either banner will spend its time rebuilding.

## 1. Why this matters more than it looks

The analysis that produced these prompts spent most of its effort distinguishing what is genuinely open from
what a document says is open. The single largest category of "open work" in this repository is **documents
describing a past state of the tree**. That is not a tidiness problem: a stale claim costs a future session a
whole rebuild, and it costs the maintainer a decision they already made.

## 2. Slices

### S1 — Mark the 2026-07-17 and 2026-07-22 plans done where they are done

Verified present in the tree: `docs/README.md` covers the legal, audit, process and maintenance trees;
`tests/test_repo_invariants.py` carries the docs-index guard; `AUDIT_TRAIL.md` runs to 2026-07-22;
`USER_MANUAL.md` carries its historical-section banner; `QUICKSTART.md` no longer uses the "Phases" heading
vocabulary. The DB-10 create-time seam **is** wired (`src/database/connect.py`, and the idle
`incremental_vacuum` pass in `src/scheduler/maintenance.py`). The OSM preprocessing bridge **is** built
(`src/static/osmpbf.js`, wired from `app-map.js`). The quarantine ACTION **is** shipped
(`src/catalog/quarantine_job.py`, `src/api/quarantine.py`). Stoplists-as-data-files **are** shipped
(`configs/stopwords_extra/<lang>.yml`).

Tick each with the anchor that proves it. Where a plan phase is wholly done, say so at the top of the phase
rather than leaving the reader to diff it themselves.

### S2 — `AUDIT_TRAIL.md` backfill

It stops at 2026-07-22 and is missing: transversal audit 09 (2026-07-25) and its ten shipped Action-Plan-D
items, the GUI audit of 2026-07-28, and both UI click-throughs (2026-08-13, 2026-08-20). Append-only, in the
file's own format.

### S3 — `FUTURE_DEVELOPMENTS.md` reality check (A4 decides the depth)

Nineteen of fifty sections carry a "designed-only" claim that the tree contradicts. Four sections are
embedded historical ledgers (the 2026-06-24 field-test remarks, the consolidated to-do, the 0.0.9 sequencing,
the 2026-06-27 field diagnostics). Three pairs are duplicates: §1/§22 Wikipedia, §35/§43 statistics,
§2/§49 legacy-restore removal.

Default under A4(b): add a status line to each stale section naming what shipped and where; archive the four
embedded ledgers to `docs/archive/` with a pointer left behind. **Do not merge the duplicate pairs** — §22
carries the superseding auto-track ruling, and protocol rule 5 forbids compressing away a ruling. Cross-link
them instead, marking which one is current.

### S4 — Correct the stale claims that the tree refutes

Each of these was verified this pass. Fix the claim where it lives, and say what the tree shows:

| Claim | Tree |
|---|---|
| "newsletter links do not become sources" | `src/ingest/email.py` writes `ArticleLink` rows for sanitized external links |
| "Ollama `num_ctx` auto-tune never built" | `src/ai_layer/context.py` carries it |
| "qualification-assist has no frontend trigger" | `src/static/app-sources.js` has the per-source button |
| "the card-audit `-inf` producer is unidentified" | fixed in `src/briefing/card_audit.py` |
| "server IP is not shown in the reader" | `src/api/main.py` renders it |
| inline `on*=` handlers ≈ 295 | ~590 (≈331 in `index.html`, ≈259 across `app-*.js`) |
| the P0 "100 GB" acceptance strings are stale | corrected 2026-08-03 |
| `scripts/import_eml.py`, `configs/stat_indicators.yml` | do not exist |

Also: `docs/process/NAV_SOUP_QUARANTINE_STRATEGY_DRAFT.md` is superseded by the shipped quarantine column,
write step and gate row 5 — banner it. `docs/ROADMAP.md` was last reconciled 2026-07-11; reconcile it
against the tree, not against itself.

### S5 — Archive spent design docs, banner the rest

Move to `docs/archive/design/` (non-lossy `git mv`, links retargeted, an entry in the archive README) the
docs whose entire scope is executed. Before moving any of them, **lift any carry-over that exists only
there** into `docs/ROADMAP.md` or the Open queue (`docs/ledger/OPEN_QUEUE.md` since 2026-09-07) — the 2026-07-22 plan's own gate on this rule is
the right one. Banner, do not archive, anything still holding an unexecuted ruling.

### S6 — Record what only the PR history knows

Six things are recorded in a pull request body and nowhere a future session would look. Give each a home
(ROADMAP row or Open-queue prose, whichever fits) — this is bookkeeping, not building:

- The legal `[À VÉRIFIER]` items and the per-release "confirm no telemetry" ritual.
- Install docs never updated for the seamless (no-prompt, auto-launch) installer.
- The `natural-earth-geometry` registry entry's blank `sha256` (existence-only check) — the same one-line
  fix the Alpine entry received.
- The nine `shipped.csv` rows carrying a bare `PR pending` in `refs` although all nine merged (L8: sweep
  once, then record the convention).
- PR #18's key-rotation, Key-Revocation-List and hardware-backed-key (YubiKey/TPM) design notes, which
  survived nowhere when that PR's content re-landed as `src/custody`.
- The supervised-training track from PR #49 (curriculum, facilitator guide, train-the-trainer, synthetic
  exercise corpus, safety self-check).

## 3. Acceptance

`docs/README.md` still lists every live doc (the guard proves it). No archived file leaves a dangling link.
No ruling was compressed away — the check is that every `§` you touched still contains every sentence that
begins a ruling. `pytest -q tests/test_repo_invariants.py tests/test_utf8_file_io.py` green.

## 4. Scope fence

Documentation only. If a doc is wrong because the code is wrong, record it and hand it to the owning prompt —
do not fix the code here.
