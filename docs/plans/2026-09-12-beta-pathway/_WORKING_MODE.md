# Working mode — shared by every brief in this folder

**This file is part of every brief here.** It is a DELTA over
[`../2026-09-06-repo-analysis/_WORKING_MODE.md`](../2026-09-06-repo-analysis/_WORKING_MODE.md), which stays the
base: read that file in full first (the ledger-first rule, the staleness guard, the branch/PR shape, the
gates verbatim, the tree-scanning guards, the honesty rules, the closeout rituals), then this one. Where the
two disagree, this one wins, because it is newer and carries the 2026-09-15 rulings.

## 1. The three files every brief rests on

1. **The rulings.** [`docs/ledger/RULINGS_INDEX.md`](../../ledger/RULINGS_INDEX.md) — one line per ruling; the
   `Qnnn` rows are the maintainer's answers to the 2026-09-12 roadmap sheet
   ([`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
   the primary record, where every question keeps its verified context and its option list). A brief quotes a
   ruling by ID; **a ruling is what the index says, never what a brief paraphrases** — when they differ, the
   index and the sheet win and the brief is corrected in the same PR.
2. **The gate row.** Each brief implements one row of one gate file under `docs/product/`
   (`RELEASE_0.4_GATE.md` … `RELEASE_0.9_GATE.md`). The row's "closes when" clause is the acceptance bar; the
   brief's slices exist to produce that named artifact and nothing else.
3. **The constitution.** `CLAUDE.md` + `docs/ledger/LESSONS.md` in full, every session (protocol rule (1)),
   then the `OPEN_QUEUE.md` entries the brief names — the head entry of 2026-09-15 indexes every answer.

## 2. What no brief may decide

- **A ⛔ question left blank stays pending:** Q823 (ODbL), Q925 (the law adapter order), Q1009 (the storage
  round-2 rows 3–6), Q1113 (the compromised embassy platforms). A brief that reaches one STOPS at the seam,
  ships the part that does not depend on it, and says so in the PR body. Nothing is defaulted.
- **A recorded CONFLICT is not resolved by a session:** Q903 (subnational law: post-beta vs from 0.7) and
  Q1103/Q1104 (stoplist merges: frozen vs batch-by-batch). The gate files say what ships around them.
- **An ASSUMPTION stays labelled:** Q001, Q207, Q804 took the sheet's default because the maintainer left them
  blank; a brief that builds on one names it as an assumption in the PR body so it can be reversed.
- **A *proposed placement* is the planning session's sequencing**, not a ruling (Q306's storage step, Q821's
  streets, Q1102's migration, Q1122's staging): follow it unless the maintainer moves it in the gate's §3.
- **A *design note* is a suggestion.** It binds nobody; a session that disagrees writes why in the PR.
- No new vertical, lane, projection, licence, external host or dependency beyond what a cited ruling names.
  A new host goes into `docs/SECURITY.md` and the consent hover in the same diff (Q1001).

## 3. What every brief owes

- **The label is context; the note is the ruling.** Q302 and Q702 were answered with a letter and a
  parenthesis that inverts the letter's label; the index records the note as the ruling. Build the note.
- **The staleness guard runs both ways** (the base working mode §2) — and also against a ruling's PREMISE: the
  sheet's context was verified at `main`@`bebcef4` (2026-09-12); re-check every anchor it names before building
  on it, and every FROM MEMORY fact (the Equal Earth coefficients, Geofabrik's `version`/`timestamp`,
  per-edition edit rates, P5437, the Windows `pyosmium` wheels) must be confirmed by the session that builds on
  it, with the source named.
- **Numbers carry their unit and their source.** A request count names the per-request unit and where the
  limit was read (the 50-titles lesson); a measurement names the fixture and its scale; a figure with no run
  behind it is dropped, not carried.
- **Every user-facing string ships ×12** (the informed-consent non-negotiable; caveats visible by default,
  layered through the hover convention, invariant #17). The three i18n gates are three commands, run
  separately; read the ratchet numbers out of `ci.yml`, never out of a document.
- **The verification bar is Q1128 = a:** Chromium in the sandbox + the maintainer's click-through =
  verified; Gecko best-effort. "Browser-unverified" is not boilerplate in this sandbox (Chromium and Python
  3.13 are present): drive the surface, record the click-through, and mark what still awaits the maintainer's
  own pass.
- **No target dates** (Q110 = c) and **no operator-time budget** (Q115 = c): list the operator steps
  plainly; never fold one into a session step to save the maintainer time.
- **One `shipped.csv` row per PR that names WHICH part of the slice shipped and what remains**; the gate
  row's status updated in the gate file's §3 amendment log; the ruling's `where enforced` cell in
  `RULINGS_INDEX.md` updated to the test or PR that now pins it; a lesson only where one was earned.
- **A PR never decides a ⛔, never rewrites history, never pushes a tag, never merges.** Draft PRs onto `main`;
  the maintainer merges.

## 4. The gates, verbatim (unchanged from the base working mode; re-read `ci.yml` for the current numbers)

```
ruff check --select=F,B --extend-ignore=B008 src/ tests/     # blocking
python -m mypy src/                                          # blocking, must be exit 0
pytest -q
alembic upgrade head && alembic check
python scripts/i18n_report.py --min 100
python scripts/i18n_report.py --audit-chrome --max-untranslatable <the number in ci.yml>
python scripts/i18n_report.py --max-unkeyed-t-calls <the number in ci.yml>
bandit -r src/ -ll -q
pytest -q tests/test_utf8_file_io.py tests/test_source_slicing_discipline.py \
  tests/test_repo_invariants.py tests/test_import_conclusion.py::test_every_node_suite_has_a_driver
```

The last line is the named set of whole-tree guards that any file addition can redden; it costs seconds. Run
`node --check` on every `<script>` block after a UI edit. Redirect each gate to a file and capture `$?` on its
own line — `cmd | tail` reports `tail`'s exit code.
