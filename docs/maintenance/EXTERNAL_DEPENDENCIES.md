# External dependencies — the maintenance contract

This is the canonical list + process for **everything we pin, vendor, or bundle from an
outside source** (data files, catalogs, native binaries, version couplings, CI pins), so
nothing drifts unwatched and an app upgrade in production has a checklist instead of a
memory test.

The machine-readable source of truth is **`configs/external_artifacts.yml`**. This doc is
the human companion; keep them in sync (the tests below enforce the important parts).

## The 4-layer strategy

1. **Registry (single source of truth)** — `configs/external_artifacts.yml`. Every
   externally-sourced artifact has one entry: upstream, license, the pin (file:const or
   path:sha256 or version floor), refresh command, freshness policy, and **couplings**.
2. **Consolidated checker (enforcement)** — `tests/test_external_freshness.py` +
   `scripts/check_external_freshness.py`:
   - **protocol guard** — every `*_AS_OF` constant in the tree must be registered (you
     cannot ship a dated artifact unwatched);
   - **freshness** — nothing past its window;
   - **compatibility** — the version couplings hold (DuckDB floor ↔ pyproject ↔ installed;
     bundled data parseable at its vintage).
3. **Proactive upstream watch (notification)** — *planned, awaiting sign-off*: a scheduled
   CI job runs `check_external_freshness.py` and queries each upstream for a newer
   release, **opening an issue** when upstream > our pin. Use **Dependabot** for the
   pip + GitHub-Actions half; the cron covers the data/binary/catalog half. This is the
   piece that means we *get told*, not *remember*.
4. **In-app self-report** — `GET /api/diagnostics/freshness` returns the registry status
   from a live install, so a production operator can surface staleness via the existing
   "click & send the debug bundle" channel.

## When you add an externally-sourced artifact

Add an entry to `configs/external_artifacts.yml` **in the same commit** (the guard test
fails otherwise). If it is dated, give it a `*_AS_OF` constant in its module and a
`{max_age_months}` policy; if vendored, record a `sha256`; if it's a version coupling,
record `{floor, verified}` + the `platforms` matrix.

## Upgrade checklist (run on every dependency bump in production)

Run `python scripts/check_external_freshness.py` first; then for anything flagged:

### General
- [ ] Refresh the artifact with its registered `refresh` command.
- [ ] Bump its `*_AS_OF` / `verified` / `sha256` in source **and** the registry.
- [ ] `pytest tests/test_external_freshness.py` green.

### DuckDB bump (`duckdb>=X` in `pyproject.toml [columnar]`) — the version-coupled one
The columnar store's persisted-offline encryption needs the OpenSSL crypto backend from
DuckDB's `httpfs` extension, which is a **native binary pinned to the exact DuckDB
version, per platform+arch**. On a DuckDB bump:

1. [ ] Re-download `httpfs` for **every** `platforms` entry
   (`linux_amd64`, `linux_arm64`, `osx_amd64`, `osx_arm64`, `windows_amd64`) at the
   **new** DuckDB version (the on-disk path is `vX.Y.Z/<platform>/…`).
2. [ ] Verify each binary's **signature/checksum**; record them.
3. [ ] Re-run the **encryption gate** (`columnar.encryption_gate`) on each platform.
4. [ ] Confirm an existing persisted `analytics.duckdb` still opens. If not — fine: the
   store is **disposable**, `columnar.connect()` detects the incompatible format marker
   and **deletes + rebuilds** it (never crashes). Just confirm that path runs.
5. [ ] Update `pyproject.toml` `duckdb>=` **and** the registry `duckdb-crypto-extension`
   `{floor, verified}` **together** (the test `test_duckdb_floor_matches_pyproject`
   enforces they match) + bump `columnar.STORE_SCHEMA_VERSION` if the table shapes changed.

### Other couplings to remember
- **IP-geo DB** (`ip-geo-country`) — monthly upstream; refresh with
  `python scripts/build_ip_geo.py --mirror`, then bump `IP_GEO_AS_OF`. Keep the CC BY 4.0
  attribution (`ip_geo.ATTRIBUTION`).
- **Vendored Alpine** — re-vendor only on a security release; update the file + its sha256.
- **Natural Earth geometry** — refresh only on a data correction (changes rarely).
- **CI action SHAs + pinned QA tools** (`mypy`/`bandit`/`pip-audit`/`ruff`) — let
  Dependabot bump; re-pin to the new SHA with its tag comment.
