# Contributing

Thanks for helping. The guiding principle is **honesty**: a feature must do what it
claims, or it doesn't ship. No fabricated outputs, no fake confidence scores, no
silent degradation — see [DESIGN.md](DESIGN.md) §3.

## Setup

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q          # 400+ tests
```

## Workflow

- **Python 3.13**, single `pyproject.toml` (no requirements.txt).
- Lint/format with **ruff**; type-check with **mypy**: `make lint && make typecheck`.
- Every change ends green: `make check` (ruff + pytest). Add a behavioural test for
  new behaviour; fix or quarantine — don't leave half-working code in the import path.
- Commit in small, honest increments with messages that say *what and why*.
- Schema changes go through Alembic (`alembic revision --autogenerate`); CI runs
  `alembic check` to catch model/migration drift.

## Standards

- Provenance everywhere: stored data carries source + timestamp + hash.
- Any number shown to a user must come from a real method with stated uncertainty
  (`src/analysis`), never a constant.
- Ingestion goes through the single ethical fetcher (robots fail-closed, rate-limited).
- Fabricated/dead code belongs in `quarantine/` (documented), not `src/`.

## License

Contributions are under **GPL-3.0-or-later** (see [LICENSE](../LICENSE)).

---

# Versioning policy

How the project is versioned — deliberately under-stated maturity.

**In this part:**
- [Versioning policy](#versioning-policy)


---

## Versioning policy

> **We deliberately under-state maturity. Honesty over hype.** It is better for a user
> to be pleasantly surprised than misled. The version number is a promise about
> *maturity*, and we keep that promise conservative.

### The single source of truth

The version lives in **one place: `pyproject.toml` (`[project] version`)**. Everything
else derives from it:

- The running app reads it from the installed package metadata
  (`importlib.metadata.version("open-omniscience")`) — so `/api/health`, the API
  `version=`, and the UI all report the *real* installed version automatically.
- No other code hardcodes a version literal. Tests assert against the package metadata,
  not a string (see `tests/test_api_search.py`).
- `docs/README.md` states the version once, in its header, and a CI guard asserts it
  matches the package (`tests/test_repo_invariants.py::test_readme_version_matches_package`).

**To bump the version, change `pyproject.toml` only**, update the README header to match
(the guard enforces this), then `pip install -e .` so the metadata refreshes.

### The maturity ladder (where we are, where we're going)

The software is young and still being proven, so it sits **below `0.1`**:

```
0.0.x  pre-alpha   ← we are here (0.0.6). Things work and are tested, but the surface
                     is still moving; not yet inviting public commentary.
0.1.x  alpha       a public, working, honestly-labelled alpha — open to feedback.
0.x    beta        once things consolidate.
1.0    release      an official, stable release.
```

We will **not** jump to `0.4`/`0.6`-style numbers that imply more maturity than exists.
`0.0.6` is the sixth small iteration of the pre-alpha series — nothing more is claimed.

### Cycle ↔ version mapping

Development cycles (and their branches) are named after the version they produce, with the
leading zeros elided for brevity:

| Branch / cycle name | Package version |
|---|---|
| `0.04` | `0.0.4` |
| `0.05` | `0.0.5` |
| `0.06` | `0.0.6` |

So "the `0.06` intelligence layer" means "the work that ships in `0.0.6`". When you read a
cycle shorthand like `0.05` in the docs, read it as `0.0.5`.

### Why this matters (the values link)

This project exists to help people see information honestly. A tool that over-states its
own maturity would contradict that at the root. Conservative versioning is the same
discipline as the rest of the codebase: **claim only what is real, and prove it.**

