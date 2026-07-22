> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — the offline pin-and-verify loader is shipped and tested (`tests/test_columnar_httpfs_loader.py`); the per-OS binaries + real SHA-256 pins in `configs/external_artifacts.yml` remain blank — unchanged, still operator-gated (needs a networked machine), not a code gap. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Persisted encrypted DuckDB — the offline static-OpenSSL httpfs build (workstream 5A-bis D1 / 5B)

> **Status: DESIGN + the OFFLINE-LOAD code is OURS to write; the per-OS/arch binaries are the
> maintainer's networked build.** This unblocks the derived columnar layer
> (`docs/design/SCALING_DERIVED_LAYER_1000X.md`): without a PERSISTED encrypted store the
> columnar layer is RAM-bound and gives no gain over the counters (CLAUDE.md already found this
> for `build_keyword_read_model`). **Never fabricate a checksum or claim a binary exists** —
> this ships the loader + an empty, clearly-flagged pin table + the build recipe.

## The problem (DuckDB 1.4.x, verified in `src/analytics/columnar.py`)

DuckDB forces the **OpenSSL/httpfs** backend for any *encrypted* write (`ATTACH ... (ENCRYPTION_KEY ...)`).
The stock `duckdb` wheel does NOT bundle the OpenSSL crypto and **autoloads `httpfs` over the
network** on first use — forbidden in an offline, airplane-mode app. DuckDB's built-in mbedTLS
path is documented NOT secure for this and its RNG was found insecure (advisory
**GHSA-vmp8-hg63-v2hp**), so it is never trusted (no fabricated security). The existing
`columnar.connect()` therefore runs **in-memory** (the sanctioned hard-fallback) and
`secure_crypto_available()` returns False — correct, but it means the persisted speed win is
unavailable until a locally-bundled, network-free OpenSSL/httpfs extension exists.

## The offline path — OUR code (network-free, pin-and-verify)

`columnar.connect(passphrase)` (and the `secure_crypto_available()` gate) gains a strict offline
loader, engaged ONLY when a bundled per-OS/arch httpfs binary is present + matches its pinned
SHA-256:

1. **Disable all network extension behaviour** on the connection:
   `SET autoinstall_known_extensions=false; SET autoload_known_extensions=false;`
   (so DuckDB can NEVER reach out to install/load an extension). Plus `SET
   allow_unsigned_extensions=true;` (our bundled build is unsigned-by-us; the SHA-256 pin is the
   trust anchor, not DuckDB's signature).
2. **SHA-256 pin-and-verify the binary BEFORE load.** Read the bundled
   `src/analytics/duckdb_ext/httpfs-<os>-<arch>-<ver>.duckdb_extension`, compute its SHA-256,
   compare to the registry pin (`configs/external_artifacts.yml`). Mismatch / missing → DO NOT
   load → stay in-memory + report loudly (never load an unverified binary).
3. **`LOAD '<absolute in-app path>';`** — an absolute path to the verified binary, never a name
   (a name would trigger the known-extensions resolution we just disabled).
4. **`ATTACH '<path>' AS analytics (ENCRYPTION_KEY '<derived>')`** with the **default
   authenticated GCM cipher** — and NEVER request a CTR cipher (the disclosed DuckDB GCM→CTR
   downgrade weakens authentication; the default GCM is the only acceptable mode).
5. **Flip `secure_crypto_available()` true ONLY after** LOAD succeeded AND the existing
   `encryption_gate(path, passphrase)` probe empirically confirms a real OpenSSL-encrypted file
   (the sentinel-absent-from-raw-bytes / won't-open-without-key / opens-with-key triad already in
   columnar.py). No probe pass → stay in-memory.

All of this is **zero outbound connections** by construction (autoload off + absolute-path LOAD +
file-only ATTACH). The `_offline_config()` already in columnar.py is the seam; extend it.

## External-artifact registry + version coupling (test-enforced)

Add to `configs/external_artifacts.yml` (one entry per OS/arch binary) + a **DuckDB ↔ bundled-httpfs
version coupling** mirroring the existing `duckdb-crypto-extension` floor pattern: the bundled
httpfs version MUST equal the installed `duckdb` minor version (an httpfs built for 1.4.x must not
load into 1.5.x). `tests/test_external_freshness.py` asserts the coupling, exactly like the
existing crypto-extension floor == the pyproject `[columnar]` floor. The pin table ships EMPTY +
flagged until the binaries exist:

```yaml
# configs/external_artifacts.yml (illustrative — SHA-256 left BLANK until the networked build)
duckdb-httpfs-extension:
  kind: vendored-binary
  couples_with: duckdb            # bundled httpfs minor == installed duckdb minor
  note: "BLOCKED: per-OS/arch static-OpenSSL httpfs needs a networked multi-arch vcpkg build."
  binaries:                       # filled in by the maintainer's build (NEVER fabricated here)
    linux-amd64:   { version: "", sha256: "" }
    linux-arm64:   { version: "", sha256: "" }
    macos-universal: { version: "", sha256: "" }
    windows-amd64: { version: "", sha256: "" }
```

A test asserts that an EMPTY pin table keeps the loader in-memory (never loads a blank/zero-hash
binary) — so the unblocked code is safe to ship before the binaries land.

## BLOCKED — the per-OS/arch binaries (the maintainer's networked step)

Building a **static-OpenSSL** httpfs extension requires a networked, multi-arch toolchain that
the autonomous sandbox does not have (py3.11/no-deps; no network for a vcpkg fetch). Recipe for a
networked machine (per OS/arch):

1. Check out `duckdb/duckdb` at the EXACT installed version tag (e.g. `v1.4.2`).
2. Build the `httpfs` extension with **statically-linked OpenSSL** (vcpkg
   `openssl[core]:<triplet>-static`), so the `.duckdb_extension` has NO dynamic OpenSSL
   dependency and never needs a system library at load.
3. Produce `httpfs-<os>-<arch>-v1.4.2.duckdb_extension`, record its SHA-256, place it in
   `src/analytics/duckdb_ext/`, and fill the registry pin **with the real measured SHA-256**
   (never a placeholder).
4. Re-run `tests/test_external_freshness.py` (the coupling) + the columnar encryption gate test
   (VERIFY items 7–10 in the scaling doc) on that OS/arch.

Until then: in-memory store, `secure_crypto_available()` False, the read seam falls back to the
live query (slower, never wrong). The code is **ready** the moment a verified binary is present.

## VERIFY (the D1 subset of the scaling-doc checklist; CI runs them once binaries exist)

7. `analytics.duckdb` is unreadable as plaintext (encryption_gate passes with the OpenSSL backend).
8. network blocked → opening the store + loading bundled httpfs makes ZERO outbound connections.
9. the bundled httpfs binary matches its pinned SHA-256 before LOAD (a tampered/wrong binary is
   refused, stays in-memory).
10. no ATTACH cipher other than the default authenticated GCM is ever requested.
11. an EMPTY/blank pin table keeps the loader in-memory (safe to ship pre-binaries).

## Why not the rejected alternatives (red-teamed)

chDB / ClickHouse use unauthenticated AES-CTR or punt encryption to LUKS — losing the in-engine
**authenticated** encryption that is the whole point (a seized derived file must be ciphertext +
tamper-evident). Turso/libSQL solve write-concurrency we don't have and cost SQLCipher. DuckDB's
own mbedTLS path is not trusted (the advisory). So: bundled static-OpenSSL httpfs + GCM, or
in-memory. Never plaintext on disk; never a network autoload; never a fabricated checksum.
