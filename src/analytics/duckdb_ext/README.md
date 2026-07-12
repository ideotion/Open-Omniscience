# `duckdb_ext/` — bundled DuckDB `httpfs` extension binaries (D1)

This directory holds the per-OS/arch **static-OpenSSL `httpfs`** DuckDB extension binaries
that enable the **persisted encrypted columnar store** (D1, `docs/design/PERSISTED_DUCKDB_HTTPFS.md`)
to open **offline**.

**It ships EMPTY.** The binaries and their real SHA-256 checksums are a **networked build
step the maintainer performs** — this sandbox/CI has no vcpkg multi-arch toolchain, and
`extensions.duckdb.org` is not in the egress allowlist. Until the binaries land,
`src/analytics/columnar.py:secure_crypto_available()` returns `False` and the columnar engine
runs **in-memory** (never a plaintext file on disk, never a fabricated checksum).

## How the loader trusts a binary (network-free)

`columnar.py:_verified_httpfs_path()`:

1. resolves this machine's platform key (`linux_amd64` / `linux_arm64` / `osx_amd64` /
   `osx_arm64` / `windows_amd64`);
2. reads the pin from `configs/external_artifacts.yml` → `duckdb-httpfs-extension.binaries`;
3. refuses unless the pinned `version` **minor equals the installed DuckDB minor** (an httpfs
   built for 1.4.x must never load into 1.5.x);
4. reads the bundled file and refuses unless its SHA-256 **equals the pinned `sha256`**;
5. only then does `columnar.py` `LOAD '<absolute path>'` — autoload/autoinstall **OFF**,
   `allow_unsigned_extensions` set in the **connect config** (a startup-only setting).

Any missing pin / missing file / SHA-256 mismatch / wrong version ⇒ **stay in-memory**.
DuckDB's own network autoload is disabled, so a missing binary can never be silently fetched.

## To bundle the binaries (maintainer, networked machine)

Per platform, at the **exact** installed DuckDB version (see
`docs/maintenance/EXTERNAL_DEPENDENCIES.md`):

1. build `httpfs` with statically-linked OpenSSL (vcpkg `openssl[core]:<triplet>-static`) so
   the `.duckdb_extension` has no dynamic OpenSSL dependency at load;
2. name it `httpfs-<platform>-v<duckdb-version>.duckdb_extension` and place it **here**;
3. record its **real** SHA-256 in the `binaries` pin (never a placeholder);
4. run the encryption-gate + round-trip tests on that platform
   (`tests/test_columnar_httpfs_loader.py`).

## CI trust path (never promoted into the registry)

`tests/test_columnar_httpfs_loader.py::test_ci_encrypted_persisted_round_trip` runs only when
`OO_CI_INSTALL_HTTPFS=1`: a CI lane installs the real `httpfs` over the network, computes its
SHA-256 **in-lane**, injects it as the pin for that run, and exercises the real encrypted
round-trip. That in-lane checksum is **never** written into `configs/external_artifacts.yml`
— the shipped registry pins stay blank until the operator's audited build fills them.
