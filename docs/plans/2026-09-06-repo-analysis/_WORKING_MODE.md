# Working mode — shared by every prompt in this folder

**This file is part of every prompt here.** Read it in full before the prompt's own slices. It exists so
twenty prompts do not carry twenty drifting copies of the same rules.

## 1. Read the ledger first

**Restructured 2026-09-07 (ruling A3) — the ledger is now three files.** Read `CLAUDE.md` (~43 KB: the
Non-negotiables, the UI invariants, the Session rituals) and
[`docs/ledger/LESSONS.md`](../../ledger/LESSONS.md) (~531 KB) **in full, every session** — together they
are the constitution, and protocol rule (1) requires both. Then open
[`docs/ledger/OPEN_QUEUE.md`](../../ledger/OPEN_QUEUE.md) (~851 KB, 164 entries) and read only the entries
your prompt names — it is the docket, consulted rather than memorised. The Lessons file is not background
reading: most of the defects it records were found the expensive way, and several of them are about the
exact class of change you are being asked to make.

## 2. The staleness guard is mandatory and it pays

Anchor: `main` @ `1d421e9` (2026-09-06). **A doc's own status text is a claim, never evidence.** Before
building anything this prompt describes, grep the tree for it. In the analysis that produced these prompts,
a large fraction of items recorded as "PENDING" or "designed-only" turned out to be shipped — including
four briefs whose "Status: PENDING execution" banner was written by the session that then executed them 48
hours later. If you find an item already built:

- do **not** rebuild it,
- record it as VERIFIED-PRESENT with the tree anchor that proves it,
- fix the stale claim in the doc that misled you, in the same PR.

The inverse holds too: several items recorded as shipped were only half-shipped. Say which half.

## 3. Branch, PR, and what you may not do

```
git fetch origin main
git checkout -B claude/oos-<slug> origin/main
```

`origin/main` goes stale within minutes under fast merges — fetch immediately before cutting, and before
any baseline comparison run. Push with `git push -u origin claude/oos-<slug>` and open a **draft** PR onto
`main`. Nothing self-merges; the maintainer's review is the gate. One PR per coherent slice is better than
one PR per prompt — several small draft PRs stacked in order is the house shape.

Never: switch branches or edit a tracked file while a suite is running (a source-reading test will fail in a
way that looks like eight real regressions); rewrite history on a branch you did not create; push a tag (the
session git proxy refuses tag pushes, and the release workflow's `gh release create` must not be pre-empted
by the GitHub UI); put a model identifier in a commit message, a PR body or a code comment.

## 4. The gates, verbatim

Run each one separately and read each one's own output. A gate that never says anything interesting is the
one to distrust.

```
ruff check --select=F,B --extend-ignore=B008 src/ tests/     # blocking
python -m mypy src/                                          # blocking, must be exit 0
pytest -q
alembic upgrade head && alembic check
python scripts/i18n_report.py --min 100
python scripts/i18n_report.py --audit-chrome --max-untranslatable 560
python scripts/i18n_report.py --max-unkeyed-t-calls 297
bandit -r src/ -ll -q                                        # bandit==1.9.4
```

Facts that have cost time before:
- The three i18n commands are three separate gates. Gate 1 passing is **no evidence** about gate 2 — gate 1
  compares locale files against `en.json` and cannot see a brand-new string that has no key at all. Both
  ratchets currently sit at **zero slack**, so any new `title=`, label or paragraph in `index.html` or an
  `app-*.js` module reddens CI unless it is keyed in the same commit.
- `cmd | tail` makes `$?` the exit code of `tail`. Redirect to a file and capture `$?` on its own line.
- Install the pyproject-pinned mypy (`mypy==2.3.1`) into the project venv. An ambient older mypy aborts on
  this tree's syntax, prints three stub errors, and exits — which reads exactly like a clean run. The tell
  is the file count in `Success: no issues found in N source files` (N ≈ 490).

## 5. Tree-scanning guards fire when you add a file

Adding or moving any file can redden a guard that has nothing to do with your change. Run this named set
after any file addition — it costs seconds:

```
pytest -q tests/test_utf8_file_io.py tests/test_source_slicing_discipline.py \
          tests/test_repo_invariants.py tests/test_import_conclusion.py tests/test_import_graph.py
```

`test_source_slicing_discipline.py` holds `_ADHOC_SLICER_BUDGET = 232` with **zero slack**: a hand-rolled
source slice in a new test reddens it. Route source-reading assertions through `tests/js_source_helper.py`
(it carries brace-, bracket-, array- and object-literal matching, each with its failure mode pinned) rather
than lowering the budget. `test_import_graph.py` holds `TRUE_CYCLE_CEILING = 0`.

## 6. This sandbox can do more than the caveats assume

- `/usr/bin/python3.13` exists (default `python3` is 3.11). Build the venv with it:
  `TMPDIR=$PWD/.tmp-pip python3.13 -m venv .venv && TMPDIR=$PWD/.tmp-pip .venv/bin/pip install -e ".[analysis,dev]"`.
  `TMPDIR` inside the repo is load-bearing — pip unpacks large wheels there and `/tmp` is small.
- **Chromium is installed** (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`), so a frontend slice can be driven
  and screenshotted here. `scripts/ui_clickthrough_run.py` is the harness. The standing "browser-unverified
  per fork-3" caveat is a habit, not a limit — but the honest stamp is still *"Chromium-verified (remote
  sandbox) · awaiting human UX pass"*, never "verified".
- Seed a synthetic corpus through the **real** `index_article`, never by inserting rows; serve with
  `OO_DATA_DIR=<tmp> OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 .venv/bin/uvicorn src.api.main:app`.
- **Egress is allowlisted.** `pypi.org` and `github.com` pass; essentially every publisher host answers
  `CONNECT … 403` with `"selective": false`. Six consecutive sessions have failed a reach-a-publisher task
  through six different tool surfaces (the sixth, 2026-09-07, probed first and reported it as a finding —
  which is the point of the next sentence). If your prompt needs a named external host, **probe it first**
  (`curl -o /dev/null -w '%{http_code}' https://<host>/`, plus one host known to work), and if it is blocked
  say so as a finding about the environment with the per-host evidence — do not rewrite the prompt and retry.

## 7. Honesty rules that outrank convenience

- Never fabricate a measurement, a checksum, an endpoint, a source or a pass. "Not measurable here" is a
  legitimate verdict; a fabricated FAIL is exactly as dishonest as a fabricated pass.
- A verdict must map to the bar it actually tested. Report the real multiple, the real n, the real scale.
- Caveats are visible by default. Every consent or caveat string ships ×12 locales.
- No composite scores; no field name containing `score`/`rating`/`ranking`/`grade` in a payload; walk your
  own payload's keys before pushing (`"degraded"` contains `"grade"` — that has bitten).
- A gap is published as a gap. An omitted field and a zero are different facts; a `None` that means
  "unmeasured" must never render as 0.
- Cross-time recall is sacred: nothing may bias toward recent data or make old data second-class.
- Anti-capping: a displayed figure is never secretly a cap. A cap may bound which examples are listed; it
  may never bound a reported number.

## 8. Verification before push

- **Skeptics complete before `git push`, not before merge.** For any slice touching data safety, a parser, a
  gate, a threshold or the write path, run adversarial passes with distinct lenses, and one of them must be
  the **negative-space** lens (generate should-be-empty, should-be-refused, should-be-a-gap inputs and assert
  the emptiness). The positive space passes on its own.
- **Mutation-check every new guard.** Neuter the fix, confirm the test reddens **by name**, restore. Assert
  the mutation applied (`assert new != old`) before believing a run — a `str.replace` whose needle is absent
  is a silent no-op and its green run reads exactly like a dead guard. If a mutation survives, that is a
  finding: about the test, about the fixture, or about the code being redundant. Decide which.
- Copy a new file aside before mutating it: `git checkout <path>` fails silently for an untracked file, and
  inside a `||` chain the error is swallowed, leaving the mutant in the tree.
- Run the full suite before push, not only the tests you wrote.

## 9. Closeout rituals

Every session ends with, in the same PR:

1. A row appended to `docs/ledger/shipped.csv` — **in binary** (`read_bytes`/`write_bytes`). The file is
   mixed CRLF/LF and carries `merge=union` in `.gitattributes`; a text round-trip silently rewrites untouched
   rows. Verify with `git diff --ignore-cr-at-eol --numstat`.
2. Any new ruling recorded **in the turn it was given**, as prose in `docs/ledger/OPEN_QUEUE.md` (the
   docket; it left `CLAUDE.md` on 2026-09-07 under ruling A3(1)). A new NON-NEGOTIABLE or UI INVARIANT
   still goes in `CLAUDE.md` itself. Never invent a ruling the maintainer did not give; record the
   question instead.
3. Any reusable lesson appended verbatim to `docs/ledger/SHIPPED_LOG.md` **and** copied into
   `docs/ledger/LESSONS.md` (which is where the Session-rituals "Lessons" subsection moved on
   2026-09-07, same ruling).
4. An honest carry-over section in the PR body: what was not built and why, what is operator-gated, what is
   browser-gated, what a maintainer ruling still blocks. Parking something honestly is a good outcome;
   half-building a migration is not.
5. After a merge of parallel work, `grep -n '^<<<<<<<\|^=======$\|^>>>>>>>' CLAUDE.md docs/ledger/*.md docs/ledger/*.csv`
   — the ledger has carried committed conflict markers before.
