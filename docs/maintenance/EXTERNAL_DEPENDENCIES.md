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
3. **Proactive upstream watch (notification)** — **built**: `.github/dependabot.yml`
   tracks the pip deps + GitHub-Action SHAs (opens PRs on new releases), and
   `.github/workflows/freshness.yml` runs weekly: `check_external_freshness.py` (our
   windows + couplings, network-free) + `check_upstream_updates.py` (GitHub API: is
   upstream newer than our pin, for the registry entries with an `upstream_check`), then
   `freshness_issue.py` opens/updates/closes **ONE rolling issue** (label `freshness`) so
   we *get told*, not *remember*. The upstream check degrades loudly (a flaky upstream is a
   `check-failed` note, never a failed run); add an `upstream_check: {github, type}` to a
   registry entry to bring it under the GitHub-API watch.
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
6. [ ] Re-bundle the **D1 persisted-store** `httpfs` binaries (S3.1): build each per-OS/arch
   binary with statically-linked OpenSSL at the new DuckDB version, place them in
   `src/analytics/duckdb_ext/`, and fill the `duckdb-httpfs-extension` registry entry's
   per-platform `{version, sha256, file}` with the **real measured** sha256 (never a
   placeholder) + `{floor, verified}`. The loader (`columnar._verified_httpfs_path`) refuses
   any binary whose sha256 or version-minor does not match, so a stale/wrong binary silently
   falls back to in-memory rather than loading. See `src/analytics/duckdb_ext/README.md`.

**D1 CI trust path.** `tests/test_columnar_httpfs_loader.py` proves the verify MECHANISM
against a fixture binary (no real httpfs / no network needed). The `columnar` CI job
additionally runs `test_ci_encrypted_persisted_round_trip` with `OO_CI_INSTALL_HTTPFS=1`,
which installs the real `httpfs` over the network, checksums it **in-lane**, and exercises
the encrypted round trip — that in-lane checksum is **never** written back into the registry
(the shipped pins stay blank until the operator's audited build fills them).

### Other couplings to remember
- **IP-geo DB** (`ip-geo-country`) — monthly upstream; refresh with
  `python scripts/build_ip_geo.py --mirror`, then bump `IP_GEO_AS_OF`. Keep the CC BY 4.0
  attribution (`ip_geo.ATTRIBUTION`).
- **Vendored Alpine** — re-vendor only on a security release; update the file + its sha256.
  When a review clears an upstream release *without* re-vendoring, record it with
  `reviewed_through` (below) — do **not** leave the watch flagging forever.
- **Model weights** (`model-weights-revision`, D6) — the *bytes*, as distinct from the
  identifiers in `ministral-model-identifiers`. `src/llm/weights_pin.py` holds the pins;
  both ship **blank**, because resolving either value needs `huggingface.co` /
  `ollama.com` and both 403 from the build sandbox, and a digest nobody fetched is a
  fabricated one. To pin, on a connected machine:
  1. Read the publisher's current revision — `HfApi().model_info(repo).sha` for the HF
     repo, the tag's digest on `ollama.com/library` (or `/api/tags` after a pull) for
     Ollama. **Read it from the publisher, never from your own cache**: a cached value
     re-pins whatever you already have, which verifies nothing.
  2. Review what changed since the bytes you trust. A pin is a statement that *these*
     bytes were looked at.
  3. Set `OO_MODEL_REVISION` (a full 40-character commit SHA — a branch or short SHA is
     **refused as a pin**, because it still moves) and/or `OO_OLLAMA_MODEL_DIGEST`.
  A mismatch **refuses the download** and deletes nothing; re-pinning is the deliberate
  way through. The refusal is at the download only — the serve side discloses the cached
  revision and never blocks a start, so an install that predates the pin keeps working.
- **sqlcipher3** (`sqlcipher3-driver`) — the at-rest encryption driver; the damage lane
  (`src/database/damage.py`, the page pass) is built on how the bundled SQLCipher reports page
  damage. 4.12 (`sqlcipher3` 0.6.2 and 0.6.3) and 4.19 (0.6.4) report it differently and both are
  qualified; `pyproject.toml` carries a ceiling (`<0.6.5`, the first release not qualified). The
  `sqlcipher-engines` CI job runs `tests/test_poisoned_connection.py` and
  `tests/test_database_verify_pages.py` on the floor (blocking) and on the newest release
  (observation), so a new release is one red leg there. To lift the ceiling: qualify the new
  release (decide per failure whether the app or only the test's encoding of the old report is out
  of date; never loosen a test to pass), then move the pyproject range, the registry
  `{floor, verified, ceiling}`, `requirements.lock` (regenerate its hash block from PyPI) and the
  `sqlcipher-smoke` pin together.
- **urllib3** (`urllib3-log-shapes`) — the HTTP library under `requests`. `src/ingest/urllib3_log.py` keeps the
  request target (the signature of a signed storage download) and anything else a record carries out of urllib3's own log lines:
  it withholds a line it does not know, and in a line it knows it reduces every argument that is not a number or text to its
  class name and drops the exception, the stack and the extra attributes. It is built on a table of the library's log calls read
  from 2.7.0 and 2.8.0. `pyproject.toml` carries `urllib3>=2.7.0,<2.8.1` (the ceiling is the first release not read, a patch
  release included, as for `sqlcipher3`) and the registry carries the same floor and ceiling. A new release is qualified by
  running `tests/test_urllib3_log_withholds_the_path.py` on it (for the second release on hand, put its unpacked wheel first on
  `PYTHONPATH`): a log call that is new, changed or gone, a keyword added, a second call with a template the table has, or a
  logger the module does not cover (however it is bound) fails by name. Decide per failure whether the table is out of date
  (extend `SHAPES`, and the target positions if the new line carries an address) or the library began to log something this app
  must not keep; never loosen a test to pass. Then move the pyproject range, the registry `{floor, verified, ceiling, current}`,
  the `urllib3-floor` job in `.github/workflows/ci.yml` if the floor moved, and, if it moved, `requirements.lock` together. The
  weekly freshness run opens the issue when upstream publishes a release past `current`.
- **Natural Earth geometry** — refresh only on a data correction (changes rarely).
- **CI action SHAs + pinned QA tools** (`mypy`/`bandit`/`pip-audit`/`ruff`) — let
  Dependabot bump; re-pin to the new SHA with its tag comment.

## Clearing an `on-security` artifact without re-vendoring (`reviewed_through`)

An `on-security` artifact is **supposed** to sit behind upstream: we re-vendor on a
security fix, not on every release. But the upstream watch compared the latest release
against `current` — the version we *ship* — so those entries flagged on every release and
the rolling issue could never close. A gate that always fires is a gate everyone learns to
ignore, which is exactly how the one release that *does* carry a CVE would arrive into an
already-red issue.

So the two facts are kept apart:

| field | means |
|---|---|
| `current` | the release we **ship** (never edit it without re-vendoring) |
| `reviewed_through` | the newest upstream release a human **reviewed and cleared** |

The watch compares against `reviewed_through` when present, else `current`
(`scripts/check_upstream_updates.py:review_baseline`). Two guards keep it honest:
`reviewed_through` is rejected on any policy other than `on-security` (so it cannot become
a universal mute button), and it may never sit *behind* `current`. Both are enforced in
`tests/test_external_freshness.py`.

**Doing a review.** When the watch flags an `on-security` entry:

1. Read the **tags**, not the issue body — upstream may have moved since the issue was
   last written (2026-08-22: the issue said Alpine v3.16.1, upstream was already v3.16.2).
   `git ls-remote --tags --refs <url>` needs no API access.
2. Diff the upstream **git history** between the shipped tag and the latest, not the
   release-note prose: `git clone --filter=blob:none --no-checkout`, then
   `git log --oneline <shipped>..<latest>` filtered for
   `secur|vulnerab|xss|cve|ghsa|sanitiz|escap|inject|exploit|prototype pollut`.
3. For each candidate, decide whether it reaches **what we actually ship** — a fix in a
   plugin package is irrelevant if our bundle does not contain that package (probe the
   vendored file for its identifying tokens and record the result).
4. Re-vendor if a fix applies. Otherwise set `reviewed_through` to the latest tag, write
   the **evidence** into the entry as a comment, and bump `last_verified`.

**Honest limit.** This watch sees **releases, not advisories**. A vulnerability disclosed
against a pinned version with no new upstream release is invisible to it — that is
Dependabot/GHSA territory. The GitHub advisory DB and `api.osv.dev` are also egress-blocked
from the build sandbox, so a sandbox review is a code-level read of the upstream diff, not
an advisory clearance; say which one you did.
