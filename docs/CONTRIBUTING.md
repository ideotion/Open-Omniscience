# Contributing

Thanks for helping. The guiding principle is **honesty**: a feature must do what it
claims, or it doesn't ship. No fabricated outputs, no fake confidence scores, no
silent degradation — see [PRODUCT_SYNTHESIS.md](PRODUCT_SYNTHESIS.md) §3.

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
