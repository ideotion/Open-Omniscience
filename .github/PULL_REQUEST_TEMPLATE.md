<!--
Thanks for contributing to Open Omniscience. The guiding principle is honesty:
a feature must do what it claims, or it doesn't ship (see docs/DESIGN.md §3).
-->

## What & why

<!-- What does this change do, and why? Link any related issue (#123). -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor / internal
- [ ] Build / CI / tooling

## Checklist

- [ ] `make check` is green (ruff + pytest) on Python 3.13
- [ ] Added or updated tests for the changed behaviour
- [ ] Any number shown to a user comes from a real method with stated uncertainty (no constants, no fabricated scores)
- [ ] New outbound traffic (if any) goes through the single ethical fetcher (robots fail-closed, rate-limited)
- [ ] Schema changes go through Alembic (`alembic check` passes)
- [ ] New user-facing chrome strings are keyed in all 12 locales (`python scripts/i18n_report.py --min 100`)
- [ ] Docs updated where behaviour changed

## Notes for reviewers

<!-- Anything not verifiable in CI (e.g. browser/UI behaviour), screenshots, trade-offs. -->
