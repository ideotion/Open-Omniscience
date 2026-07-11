# The six consecutive autonomous sessions — shared conventions (2026-07-11)

**Program:** six CONSECUTIVE fully-autonomous build sessions (Opus 4.8, ultracode), S1 → S6,
one per tier of the reconciled `docs/ROADMAP.md`. The maintainer **merges each session's PRs
before launching the next**, so every session starts from a tip that already contains its
predecessors — that cadence is what keeps the six waves conflict-free in chronological order.
Per-session briefs: `AUTONOMOUS_SESSION_BRIEF_2026-07-11_S<N>_*.md` (same folder). Rulings of
record: the maintainer's 2026-07-11 answers (1 yes · 2 yes · 3 excluded · 4 yes · 5 yes),
recorded in `CLAUDE.md`.

## 0. Read first, in this order (non-negotiable)

1. **`CLAUDE.md` in full** — the binding ledger (non-negotiables, UI invariants #1–#30,
   lessons). Everything below defers to it on conflict.
2. **Your brief** (`AUTONOMOUS_SESSION_BRIEF_2026-07-11_S<N>_*.md`) + this file.
3. **The previous session's CLOSEOUT** — its final `shipped.csv` row and the **CARRY-OVER
   section in its closeout PR body**. Carry-overs you can absorb JOIN YOUR QUEUE at the top
   (maintainer answer #5). S1 has no predecessor.
4. `docs/ROADMAP.md` (the board) and, for scale items, `docs/product/SCALE_ROADMAP.md`.

## 1. The consecutive-session contract

- You are session N of 6. Later sessions own the later tiers — do NOT wander into their
  queues except for carry-overs explicitly handed to you. If you finish early, deepen your
  own tier's verification instead.
- Cut EVERY branch from a **freshly fetched** `origin/0.2`
  (`git fetch origin 0.2 && git checkout -B claude/s<N>-<slug> origin/0.2`); verify
  `git show origin/0.2:pyproject.toml` reads `0.2.0` before trusting the base. Branch
  prefix `claude/s<N>-*`.
- Small **draft PRs onto `0.2`**, one per coherent slice. The maintainer fast-merges: after
  a push that prints `[new branch]`, your previous PR was merged — re-fetch before the next
  cut. If your own previous PR is still open and the next slice touches the same files,
  STACK on your own branch instead of cutting parallel branches.
- Shared append-targets (`CLAUDE.md`, `docs/ledger/shipped.csv`, `docs/ledger/SHIPPED_LOG.md`,
  `docs/ROADMAP.md`, `configs/external_artifacts.yml`, `tests/test_repo_invariants.py`) are
  edited ADDITIVELY — append, never reorder, never revert another session's lines.

## 2. Verify before push (a hard gate — not optional)

- **Adversarial skeptic subagents COMPLETE before every `git push`** (lesson #542→#544:
  a PR merged while verification was still running shipped six defects). Spawn parallel
  skeptics with DISTINCT lenses (correctness · data-loss · honesty/no-fabrication ·
  concurrency/gate-hold · perf-at-scale); for ANY parser/extractor/router work the
  **negative-space lens is mandatory** (#590: enumerate should-be-empty inputs — word-tail
  fragments, router failure paths, order-ambiguous forms — each asserting `[]`). Pin every
  reproducer as a test. Hand-re-verify agent findings before acting (the 06-audit
  false-positive lesson).
- **Sub-agents are encouraged throughout**, not just for skeptics: Explore agents for recon
  sweeps, parallel implementation of independent slices, judge panels for design choices.
- **Test environment:** create the py3.13 venv first
  (`python3.13 -m venv .venv && .venv/bin/pip install -e ".[analysis,dev]"` — proven to run
  the FULL suite + the mypy ratchet in-repo). If only py3.11 exists, use the ledger's
  CI-only fallbacks (standalone pure-module repros; `pip install mypy==2.1.0` + per-file
  mypy; `pip install bleach sqlalchemy pytest` for ORM tests) and say honestly what ran
  where. NEVER claim green you did not see; NEVER switch branches while a suite runs.
- Per-PR gates: `pytest -q` green (or an honest CI-only note) · mypy ratchet ≤ baseline ·
  `ruff check --select F,B` · bandit `# nosec` conventions for dynamic SQL · `node --check`
  on every touched JS · `python scripts/i18n_report.py --min 100` when locales change ·
  endpoint tests override `get_db`, never seed `SessionLocal` · route guards anchor to
  router definitions, never positive asserts on the shared `app.routes`.
- **After each merged wave of your own PRs, run a full-suite health check** (per-PR CI
  misses cross-test pollution).

## 3. Honesty non-negotiables (the project's purpose is the spec)

This tool exists so journalists and citizens can see information honestly. Every choice
bends toward that: no composite scores (`CardSchemaError` enforces); every signal carries
method + caveat + n; caveats VISIBLE by default (layering via translated hover bubbles,
never hiding); degrade loudly, never silently; ZERO fabricated data, checksums, dates, or
security theater; the airplane socket guarantee and the ONE consent popup are inviolable;
never silently downgrade transport; deduced ≠ asserted ≠ AI-derived — three labelled
provenance classes, never blended. Frontend work ships CONSERVATIVE + FLAGGED
("browser-unverified, needs click-through") with `node --check` + invariant guards +
defensive empty states — there is no browser here.

## 4. NETWORKED WORK IS EXCLUDED (your internet is heavily limited)

Do NOT attempt these; when your queue touches one, record it on the operator list instead:
fetching the per-OS httpfs crypto binaries · USGS / eclipse-canon / subjectivity-lexicon /
any external DATA download · the Wikidata gap run · live ollama.com browsing · commodity-feed
live verification · the dbstat-enabled sqlcipher build · translated-docs model runs · and,
always, the maintainer-only steps (live-corpus P0 validation, the v0.2.0 tag, click-throughs,
gold-set grading, keyword-log exports). Building PARSERS/SEAMS against hand-built fixtures
that mirror a documented public format is allowed and encouraged — clearly marked as
fixtures, never presented as real data.

## 5. Ledger + closeout discipline

- Every shipped item: a `docs/ledger/shipped.csv` ROW. Reusable lessons: verbatim in
  `docs/ledger/SHIPPED_LOG.md` + copied into CLAUDE.md's Session-rituals Lessons. New
  decisions/rulings you take: recorded in `CLAUDE.md` the same turn. Update the
  `docs/ROADMAP.md` statuses you change.
- **End-of-session closeout (mandatory):** one final ledger row + a closeout PR whose body
  carries (a) what shipped, (b) what needs the maintainer (click-throughs, networked items,
  live runs), and (c) a **CARRY-OVER** section — every queue item you did not finish, with
  enough context for session N+1 to absorb it cold. The next session reads this FIRST.
