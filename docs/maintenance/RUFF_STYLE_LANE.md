# The advisory ruff style lane — the verdict, the composition, and the ratchet

**Ruled 2026-09-07 (PROMPT_20 S7, under the standing "proceed on the recommended default"
rule): the style lane STAYS ADVISORY, and gains a non-growth RATCHET.** This file is the
"record which" half of that decision. It is a measurement, not a plan: every number below
was produced by the command printed beside it, on the tree anchor named.

## The two lanes

`.github/workflows/ci.yml` runs ruff twice, and only one of them can fail a build:

| Lane | Command | Status |
|---|---|---|
| Correctness | `ruff check --select=F,B --extend-ignore=B008 src/ tests/` | **BLOCKING**, and green |
| Style | `ruff check src/ tests/` | advisory (`continue-on-error`), **432 findings** |
| Style non-growth | `python scripts/ruff_ratchet.py --max <N>` | **BLOCKING** (new, 2026-09-07) |

## What the advisory lane actually holds

Measured on `main` @ `d9ee33e7` (2026-09-07) with **ruff 0.16.6**
(`python scripts/ruff_ratchet.py --max 432 --show-composition`):

| Count | Rule | What it is |
|---:|---|---|
| 128 | `I001` | import block un-sorted / un-formatted |
| 57 | `SIM105` | `try/except/pass` that could be `contextlib.suppress` |
| 41 | `E702` | multiple statements on one line (semicolon) |
| 22 | `SIM300` | Yoda condition |
| 20 | `C416` | unnecessary comprehension |
| 20 | `SIM905` | split a literal string |
| 19 | `SIM117` | nested `with` |
| 18 | `UP037` | quoted annotation |
| 18 | `SIM115` | file opened without a context manager |
| 18 | `C408` | `dict()` / `list()` call instead of a literal |
| 11 | `UP035` | deprecated import |
| 60 | *(tail)* | `SIM108/102`, `E741`, `C420`, `UP032/017/047/034/031`, `E711`, `SIM103/110/222`, `C401` |

231 of the 432 are auto-fixable (`--fix`), 70 more with `--unsafe-fixes`.

## Why it does not converge in this prompt

The prompt that asked the question is explicitly behaviour-neutral, and the largest block
is the one that is least behaviour-neutral in **this** codebase:

* **`I001` (128, 30% of the lane) reorders imports.** This tree has import order that is
  load-bearing in named places — the airplane socket guard installs at a point in the boot
  path; `src/database/session.py` binds the write gate at module scope after the engine;
  36 files carry the legacy GPL-header-plus-second-docstring pattern that already has its
  own closed `E402` carve-out in `pyproject.toml`; and several tests monkeypatch a symbol
  by the module that imported it. A tree-wide `--fix` is a 128-site reordering whose blast
  radius is exactly what "if a refactor changes an output, it is not this prompt's"
  excludes. It is a real slice; it is not a drive-by.
* **`SIM105` (57) is not free either.** `contextlib.suppress` is the right shape for most
  of them, and this repo has a recorded lesson about suppressing the *wrong class* in the
  merge/restore chain (`sqlcipher3.Error` is not a subclass of `sqlite3.Error`, so a
  driver-class suppress there is dead code on every real corpus). Each site needs reading.
* The rest is a long tail of one- and two-site rules with no shared mechanism, so it
  converges by attrition or not at all.

None of that is an argument for leaving it unwatched, which is what "advisory" had come to
mean in practice.

## The finding that made a ratchet necessary

`PARKED.md` recorded the lane at **344** findings on 2026-08-20, in the same session that
zeroed 164 `E402` findings via the per-file-ignores carve-out. It measured **432** on
2026-09-07 — **+88 in eighteen days**, unnoticed, because a lane that is permitted to fail
says nothing when it fails a little more. That is the inverse of the recorded
freshness-issue lesson (a gate that always fires becomes noise): here a gate that always
fails *by design* cannot report that it is failing worse.

So the count is ratcheted the way this repo ratchets everything else — the two i18n gates,
`_ADHOC_SLICER_BUDGET`, `TRUE_CYCLE_CEILING`. It may only be **lowered**; growth reddens a
blocking step; a drop prints the new floor to set. The advisory verdict is untouched:
nobody is asked to fix the 432.

## Why ruff is version-bounded

A count-over-a-tool ratchet is only meaningful while the tool's rule set is fixed. The
`mypy==2.3.1` pin three lines above it in `pyproject.toml` exists for exactly this reason,
in its own words: an unpinned floor "let a newer mypy report one extra error … and redden
every PR with no code change". `ruff` was `>=0.4.0` — unbounded across every future rule
addition — and is now bounded to one minor series. `scripts/ruff_ratchet.py` prints the
ruff version it measured with in its own failure message, so a rule-set change presents as
itself rather than as mystery debt.

## How to move the number

```bash
python scripts/ruff_ratchet.py --max 432 --show-composition   # what is in there
ruff check src/ tests/ --fix                                   # the 231 safe autofixes
python scripts/ruff_ratchet.py --max <the new, lower number>   # then lower the ceiling
```

Lower `--max` in `.github/workflows/ci.yml` in the same PR that lowers the count — the
script prints the new floor when it can drop. Raising it is allowed and is a deliberate
act that belongs in a PR body, not a quiet edit.
