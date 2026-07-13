"""
Derived columnar read-model engine (DuckDB) — bring-up + encryption gate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Data-architecture build Slice 4, PR-1 (engine bring-up). This is the optional DuckDB
accelerator behind the A1 read-model seam (``src/analytics/readmodel.py``). It is a
**disposable, rebuildable cache** — the encrypted SQLCipher store is ALWAYS the source
of truth; a missing / cold / unavailable columnar store means the seam serves the live
SQLite query (slower, never wrong). PR-1 establishes the engine + the encryption gate +
the offline guarantee; the endpoint port (reading aggregations from here) is PR-2/3.

Three hard rules, all enforced in code (maintainer ruling 2026-06-19):

1. **Encrypted under the SAME passphrase, or in-memory — never plaintext on disk.**
   The persisted file at ``data_dir()/analytics.duckdb`` is opened with DuckDB's AES
   ``ENCRYPTION_KEY`` derived deterministically from the ONE corpus passphrase (no
   second secret for the user to manage — :func:`_derive_key`). A persisted file is
   used ONLY after :func:`encryption_gate` empirically proves it is really encrypted. If
   a SECURE crypto backend is not available offline (see below), the engine falls back
   to **DuckDB in-memory** and writes NO file — never a plaintext derived store.

2. **Fully offline.** Opened with extension autoload/autoinstall DISABLED and external
   access OFF, so opening the engine makes zero network calls (the airplane socket guard
   is the net beneath this; here we simply never reach for the network).

3. **No fabricated security.** DuckDB's built-in mbedtls crypto is documented by DuckDB
   itself as "NOT securely encrypted"; we NEVER trust it for the derived store
   (:func:`secure_crypto_available` requires the OpenSSL/httpfs backend). Trusting the
   unsafe backend would be exactly the lock-screen-over-plaintext theatre the project
   forbids — so when only the unsafe backend exists, we go in-memory instead.

EMPIRICAL FINDING (recorded for the persistence decision): the stock ``duckdb`` PyPI
wheel does NOT bundle the OpenSSL crypto (``httpfs``) extension, and DuckDB autoloads it
from its network extension repository — which rule 2 forbids. So out of the box the
SECURE persisted store is unavailable offline and the engine runs IN-MEMORY. Enabling a
persisted encrypted store offline needs a per-OS ``httpfs`` extension bundled locally
(a packaging decision); the code is ready for it the moment ``secure_crypto_available()``
returns True. ``OO_COLUMNAR_DIR`` overrides the store directory; ``OO_COLUMNAR=0`` forces
the engine off (always live query).

VERIFY-FIRST OUTCOME — keyword-engine P2.4, tested on **DuckDB 1.5.4** (2026-06-25): the
hypothesis that DuckDB >=1.4 WRITES an authenticated-AES-256-GCM encrypted store NATIVELY
(without httpfs) is **REFUTED**. Writing an encrypted store still REQUIRES loading
``httpfs`` (OpenSSL): DuckDB 1.5.4 refuses the write with "DuckDB currently has a
read-only crypto module loaded. Please ensure httpfs is loaded using `LOAD httpfs` ... To
write an encrypted database ... that is NOT securely encrypted, one can use SET
force_mbedtls_unsafe = 'true'." The only no-httpfs write path is that explicitly-UNSAFE
mbedtls — exactly the fabricated-security the project forbids. So ``secure_crypto_available``
stays gated on httpfs; the gate is NOT relaxed; the engine stays IN-MEMORY until the per-OS
httpfs binaries are bundled (operational/packaging, networked machine). Separately, the
1.5.x ``enable_external_access=False`` in :func:`_offline_config` also blocks a FILE attach
outright — a second reason the persisted file path is unavailable under the strict offline
config; both are moot while httpfs is the gating blocker.

OFFLINE LOADER (S3.1 / D1, docs/design/PERSISTED_DUCKDB_HTTPFS.md): when a per-OS/arch
static-OpenSSL ``httpfs`` binary is bundled under ``src/analytics/duckdb_ext/`` AND matches
its SHA-256 pin in ``configs/external_artifacts.yml`` (the ``duckdb-httpfs-extension``
entry), the engine LOADs it BY ABSOLUTE PATH -- autoload/autoinstall OFF,
``allow_unsigned_extensions`` set in the CONNECT config (a startup-only setting), and the
persisted path uses :func:`_persisted_config` (external file access ON so the ATTACH works;
the network is closed by autoload-off + the airplane socket guard, NOT by
``enable_external_access``). No pin / missing file / SHA-256 mismatch / wrong version ->
stay in-memory (never load an unverified binary, never a network autoload). The pin table
ships EMPTY, so ``secure_crypto_available()`` stays False until the maintainer's networked
build lands the binaries + their real sha256 (never fabricated).

CANONICAL-BASENAME LOAD (fixes the columnar CI lane): DuckDB derives an extension's C init
symbol (``<name>_init``) from the LOADed file's BASENAME up to the FIRST dot
(``FileSystem::ExtractBaseName`` splits the filename on ``.`` and takes ``[0]``). Our bundled
binary is named ``httpfs-<plat>-v<major>.<minor>.<patch>.duckdb_extension``, so LOADing it
directly makes DuckDB derive ``httpfs-<plat>-v<major>`` and look for a nonexistent
``httpfs-<plat>-v<major>_init`` symbol -> the LOAD fails and the persisted store silently
degrades to in-memory (the real-httpfs round-trip CI lane's red). So the loader keeps the
descriptive, SHA-pinned bundled name on disk but presents the already-VERIFIED bytes to
``LOAD`` under the canonical basename ``httpfs.duckdb_extension`` (a per-process temp copy;
:func:`_canonical_httpfs_path`), so DuckDB derives ``httpfs`` and resolves the real
``httpfs_init``. The SHA-256 pin / version coupling / traversal guard are unchanged — they
run on the REAL bundled file (:func:`_verified_httpfs_path`) before the canonical copy.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path

_LOG = logging.getLogger(__name__)

# The last exception secure_crypto_available() caught while trying to LOAD the verified
# httpfs offline — surfaced (audit BUG-1) instead of being swallowed by a bare except, so a
# red CI lane / an operator can SEE why the persisted encrypted store fell back to in-memory
# instead of a silent False. None = last check succeeded or the earlier gates returned first.
_LAST_CRYPTO_ERROR: str | None = None

# A unique token written into a probe store to PROVE the file is encrypted (the gate).
_SENTINEL = "OO_COLUMNAR_ENC_SENTINEL_b7f3"
_STORE_FILENAME = "analytics.duckdb"


def duckdb_available() -> bool:
    """True if the optional ``duckdb`` dependency is importable (else: live query)."""
    try:
        import duckdb  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        return False


def _offline_config() -> dict:
    """DuckDB config that guarantees no network on open: extension autoload/autoinstall
    DISABLED and external access OFF. The columnar engine is local-first by construction.
    """
    return {
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
        "enable_external_access": False,
    }


def _persisted_config() -> dict:
    """DuckDB config for the PERSISTED encrypted store path (D1).

    Extension autoload/autoinstall stay OFF (httpfs is LOADed from the verified local binary
    by ABSOLUTE PATH -- never fetched over the network), and ``allow_unsigned_extensions`` is
    set HERE, in the connect config, because it is a startup-only setting (a post-connect
    ``SET`` raises: "Cannot change allow_unsigned_extensions setting while database is
    running"). Our bundled build is unsigned-by-us; the SHA-256 pin (not DuckDB's signature)
    is the trust anchor. ``enable_external_access`` is NOT disabled here -- a file ATTACH
    needs filesystem access (empirically, ``enable_external_access=False`` raises a Permission
    Error on ATTACH). The offline guarantee for this path is (a) autoload OFF so no extension
    is ever fetched, (b) the absolute-path LOAD, and (c) the process-wide airplane socket
    guard beneath -- not the external-access flag. The in-memory path keeps the stricter
    :func:`_offline_config` (it never touches a file)."""
    return {
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
        "allow_unsigned_extensions": True,
    }


def _derive_key(passphrase: str) -> str:
    """A DuckDB ENCRYPTION_KEY derived from the ONE corpus passphrase.

    NOT a second key surface: there is no second secret for the user to manage — the
    derived store rides the same passphrase as the canonical SQLCipher store. A hex
    digest avoids any SQL-literal-escaping hazard in the ``ENCRYPTION_KEY`` clause. The
    store is a disposable cache; this protects the same at-rest threat model.
    """
    return hashlib.sha256(("oo-columnar-v1:" + passphrase).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# D1 -- the offline bundled-httpfs loader (verify-before-LOAD).
# docs/design/PERSISTED_DUCKDB_HTTPFS.md. The stock duckdb wheel would autoload httpfs over
# the network (forbidden). To enable a PERSISTED encrypted store OFFLINE we bundle a per-OS/
# arch static-OpenSSL httpfs binary under ``_ext_dir()`` and LOAD it BY ABSOLUTE PATH after
# verifying its SHA-256 against the registry pin. No pin / missing file / mismatch -> stay
# in-memory. Ships EMPTY + flagged: the binaries + their real sha256 are the maintainer's
# networked build step, so ``secure_crypto_available()`` stays False here until they land.


def _ext_dir() -> Path:
    """Directory holding the bundled per-OS httpfs extension binaries.
    ``OO_COLUMNAR_EXT_DIR`` overrides it (tests point it at a fixture dir)."""
    override = os.getenv("OO_COLUMNAR_EXT_DIR")
    return Path(override) if override else Path(__file__).parent / "duckdb_ext"


def _duckdb_minor() -> str | None:
    """The installed DuckDB ``major.minor`` (the extension version MUST couple to it)."""
    try:
        import duckdb

        return ".".join(str(duckdb.__version__).split(".")[:2])
    except Exception:  # noqa: BLE001 - optional extra
        return None


def _platform_arch() -> str | None:
    """The registry platform key for THIS machine, or None if unsupported. Mirrors the
    ``duckdb-httpfs-extension`` ``binaries`` keys: ``linux_amd64`` / ``linux_arm64`` /
    ``osx_amd64`` / ``osx_arm64`` / ``windows_amd64``."""
    import platform
    import sys

    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64",
            "arm64": "arm64"}.get(platform.machine().lower())
    if arch is None:
        return None
    if sys.platform.startswith("linux"):
        return f"linux_{arch}"
    if sys.platform == "darwin":
        return f"osx_{arch}"
    if sys.platform.startswith("win"):
        return "windows_amd64" if arch == "amd64" else None
    return None


def _httpfs_pins() -> dict:
    """Per-platform bundled-httpfs pins from the registry (network-free):
    ``{platform: {"version", "sha256", "file"}}``. EMPTY when unbundled (the loader then
    stays in-memory). Any read failure -> ``{}`` (safe: no unverified load)."""
    try:
        from src.maintenance.registry import load_registry

        for a in load_registry():
            if a.get("id") == "duckdb-httpfs-extension":
                return {k: v for k, v in (a.get("binaries") or {}).items()
                        if isinstance(v, dict)}
    except Exception:  # noqa: BLE001 - registry unreadable -> treat as unbundled
        pass
    return {}


def _verified_httpfs() -> tuple[str, str] | None:
    """``(absolute_path, sha256_hexdigest)`` of the bundled httpfs extension for THIS platform,
    ONLY if it exists, its SHA-256 matches the registry pin, and the pinned version couples to
    the installed DuckDB minor. None otherwise (missing / blank pin / mismatch / wrong version)
    -> the caller stays in-memory. NEVER returns an unverified binary; NEVER a network autoload.
    The verified digest is returned so the canonical-copy loader can key + re-verify on it."""
    plat = _platform_arch()
    minor = _duckdb_minor()
    if not plat or not minor:
        return None
    pin = _httpfs_pins().get(plat) or {}
    want_sha = str(pin.get("sha256") or "").strip().lower()
    want_ver = str(pin.get("version") or "").strip()
    if not want_sha or not want_ver:
        return None  # unbundled / blank pin -> stay in-memory (safe to ship pre-binaries)
    # Version coupling: the bundled httpfs minor MUST equal the installed DuckDB minor
    # (an httpfs built for 1.4.x must never load into 1.5.x).
    if ".".join(want_ver.lstrip("v").split(".")[:2]) != minor:
        _LOG.warning("bundled httpfs version %s != duckdb %s; refusing (in-memory)",
                     want_ver, minor)
        return None
    fname = (str(pin.get("file") or "").strip()
             or f"httpfs-{plat}-v{want_ver.lstrip('v')}.duckdb_extension")
    # Defense-in-depth (the ZETA traversal discipline): the extension file must be a plain
    # basename inside _ext_dir() -- never an absolute path or a '..' escape, even from the
    # (trusted) registry (pathlib silently discards the left side when joined with an
    # absolute path).
    if fname in ("", ".", "..") or fname != Path(fname).name:
        _LOG.warning("bundled httpfs 'file' is not a plain basename (%r) -- refusing", fname)
        return None
    path = _ext_dir() / fname
    if not path.exists() or not path.is_file():
        return None  # pin present but the binary is not bundled -> in-memory
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if got != want_sha:
        _LOG.warning("bundled httpfs sha256 mismatch for %s -- refusing to load (in-memory)",
                     path.name)
        return None
    return str(path.resolve()), got


def _verified_httpfs_path() -> str | None:
    """Absolute path to the verified bundled httpfs for THIS platform, or None (see
    :func:`_verified_httpfs`). The gate used by ``secure_crypto_available``/``secure_crypto_reason``."""
    v = _verified_httpfs()
    return v[0] if v is not None else None


# DuckDB derives an extension's C init symbol (``<name>_init``) from the LOADed file's
# BASENAME up to the FIRST dot (``FileSystem::ExtractBaseName`` splits on ``.``, takes [0]).
# The bundled binary carries a descriptive, version-dotted name, so LOADing it directly would
# make DuckDB look for a bogus ``httpfs-<plat>-v<major>_init`` symbol. We therefore present the
# already-verified bytes to LOAD under this canonical basename so DuckDB derives ``httpfs`` and
# resolves the real ``httpfs_init``.
_CANONICAL_HTTPFS_BASENAME = "httpfs.duckdb_extension"
# (verified_sha256, canonical_temp_path, temp_dir): keyed on the VERIFIED digest (NOT the source
# path) so a re-pin to different bytes at the same path invalidates the cache; the copy is
# re-hashed against this digest on every hand-out so the actually-LOADed artifact -- not just the
# source proxy -- is verified before every LOAD.
_canonical_httpfs_cache: tuple[str, str, str] | None = None
_canonical_httpfs_lock = threading.Lock()


def _discard_canonical_copy_locked() -> None:
    """Drop the cached canonical copy and best-effort remove its temp dir (caller holds the lock;
    ``ignore_errors`` so a copy still mmap'd by a live connection on Windows is simply left)."""
    global _canonical_httpfs_cache
    old = _canonical_httpfs_cache
    _canonical_httpfs_cache = None
    if old is not None:
        shutil.rmtree(old[2], ignore_errors=True)


@atexit.register
def _cleanup_canonical_copy() -> None:
    """Remove the single live canonical-copy temp dir at interpreter exit (registered once)."""
    with _canonical_httpfs_lock:
        _discard_canonical_copy_locked()


def _canonical_httpfs_path() -> str | None:
    """Present the VERIFIED bundled httpfs binary to ``LOAD`` under the canonical basename
    ``httpfs.duckdb_extension`` so DuckDB derives the correct ``httpfs`` extension name (and
    its real ``httpfs_init`` symbol) from the filename.

    All the trust work — the SHA-256 registry pin, the DuckDB version coupling, and the
    traversal guard — is done on the REAL bundled file by :func:`_verified_httpfs`. This function
    copies those already-verified bytes into a private per-process temp dir under the canonical
    name (the descriptive ``httpfs-<plat>-v<ver>.duckdb_extension`` name, which DuckDB would
    truncate at the first version dot into a bogus init symbol, stays on disk). VERIFY-BEFORE-LOAD
    holds for the ACTUALLY-LOADED artifact on EVERY call, not just the source proxy: the cache is
    keyed on the verified digest (so a re-pin to different bytes at the same path re-copies) AND
    the cached copy is re-hashed against that digest before reuse (so an in-place tamper /
    corruption of the temp copy is caught and the stale copy is never served). One copy per
    verified binary; the temp dir is removed on invalidation and at interpreter exit. Returns None
    when no verified binary is bundled -- the caller stays in-memory; never a plaintext store,
    never a network autoload."""
    global _canonical_httpfs_cache
    verified = _verified_httpfs()  # (path, sha256): SHA pin + version couple + traversal guard
    if verified is None:
        return None
    src, sha = verified
    with _canonical_httpfs_lock:
        cache = _canonical_httpfs_cache
        if (cache is not None and cache[0] == sha and Path(cache[1]).exists()
                and hashlib.sha256(Path(cache[1]).read_bytes()).hexdigest() == sha):
            return cache[1]  # the LOADed artifact still matches the pin -> reuse the copy
        _discard_canonical_copy_locked()  # miss / re-pin / corrupt copy -> re-make from source
        tmp_dir = tempfile.mkdtemp(prefix="oo-duckdb-httpfs-")
        canon_path = str(Path(tmp_dir) / _CANONICAL_HTTPFS_BASENAME)
        shutil.copyfile(src, canon_path)  # a faithful byte copy of the just-verified binary
        _canonical_httpfs_cache = (sha, canon_path, tmp_dir)
        return canon_path


def _persisted_connection():
    """A DuckDB connection with the VERIFIED bundled httpfs LOADed by absolute path (the
    secure OpenSSL crypto backend), using :func:`_persisted_config`. Raises if no verified
    binary is bundled -- the caller falls back to the in-memory store. Network-free by
    construction (autoload OFF + absolute-path LOAD).

    The LOAD path is the canonical-basename copy (:func:`_canonical_httpfs_path`), NOT the
    descriptive bundled filename, so DuckDB derives the ``httpfs`` extension name (and its real
    ``httpfs_init`` symbol) instead of mangling the version-dotted name."""
    import duckdb

    ext = _canonical_httpfs_path()  # verified bytes presented under 'httpfs.duckdb_extension'
    if ext is None:
        raise RuntimeError("no verified bundled httpfs extension (persisted store unavailable)")
    con = duckdb.connect(config=_persisted_config())
    con.execute("LOAD '" + ext.replace("'", "''") + "'")
    return con


def secure_crypto_available() -> bool:
    """True ONLY if a SECURE crypto backend (OpenSSL via ``httpfs``) can be loaded OFFLINE
    from a VERIFIED bundled binary. DuckDB's built-in mbedtls is "NOT securely encrypted"
    and is never trusted for the derived store; DuckDB's own network autoload is forbidden.
    So this is True only when a per-OS ``httpfs`` binary is bundled under ``_ext_dir()`` AND
    matches its registry SHA-256 pin AND actually LOADs by absolute path. When False the
    engine runs in-memory (no plaintext file is ever written). The pin table ships EMPTY, so
    this stays False until the maintainer's networked build lands the binaries (never a
    fabricated checksum). Pure check; opens and closes a throwaway connection.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return False
    if _verified_httpfs_path() is None:
        return False  # no verified bundled binary -> never a network autoload -> in-memory
    global _LAST_CRYPTO_ERROR
    try:
        con = _persisted_connection()  # LOADs the verified httpfs by absolute path
        con.close()
        _LAST_CRYPTO_ERROR = None
        return True
    except Exception as exc:  # noqa: BLE001 - not loadable offline -> not available
        # SURFACE the cause (audit BUG-1) — never swallow it silently. The persisted store
        # still degrades to in-memory (behaviour unchanged); but now a red CI lane / an
        # operator can see WHY via the WARNING log + secure_crypto_reason().
        _LAST_CRYPTO_ERROR = f"{type(exc).__name__}: {exc}"
        _LOG.warning(
            "secure_crypto_available: the verified httpfs did not LOAD offline "
            "(persisted store -> in-memory): %s", exc
        )
        return False


def secure_crypto_reason() -> str | None:
    """Why :func:`secure_crypto_available` is False — or ``None`` when it is True.

    A read-only diagnostic that reports the FIRST failing gate (no duckdb / ``OO_COLUMNAR=0`` /
    no verified bundled binary) or, if all gates passed but the LOAD raised, the captured
    exception (``_LAST_CRYPTO_ERROR``). This is the audit BUG-1 fix: the cause the bare
    ``except`` used to hide is now inspectable — the columnar CI lane's failure shows WHY
    instead of a silent False, and the operator can diagnose a bundled-binary problem without
    reading logs. Never fabricates; ``None`` means "secure crypto is available (or not yet
    checked, in which case call secure_crypto_available() first)"."""
    if not duckdb_available():
        return "duckdb is not installed (the [columnar] extra)"
    if os.getenv("OO_COLUMNAR") == "0":
        return "OO_COLUMNAR=0 (columnar disabled by environment)"
    if _verified_httpfs_path() is None:
        return (
            "no verified bundled httpfs binary under the extension dir "
            "(the registry pin ships blank, or the on-disk binary's sha256 does not match "
            "the pin) -> stays in-memory, never a network autoload"
        )
    # all gates pass: the outcome depends on whether the LOAD raised the last time it ran.
    return _LAST_CRYPTO_ERROR


def encryption_gate(path: str | Path, passphrase: str) -> bool:
    """Empirically PROVE a persisted DuckDB store is really encrypted (Slice 4 gate).

    The three checks the acceptance criteria require, run on a throwaway file at
    ``path``: (a) the sentinel is ABSENT from the raw file bytes, (b) opening WITHOUT the
    key FAILS, (c) opening WITH the key returns the sentinel. Returns True only if all
    three hold; cleans up the probe file. Any DuckDB error -> False (degrade loudly to
    in-memory, never assume encryption).
    """
    if not duckdb_available():
        return False

    p = Path(path)
    key = _derive_key(passphrase)
    try:
        if p.exists():
            p.unlink()
        con = _persisted_connection()  # verified httpfs LOADed (encrypted ATTACH needs it)
        try:
            con.execute(f"ATTACH '{p.as_posix()}' AS g (ENCRYPTION_KEY '{key}')")
            con.execute("CREATE TABLE g.probe (s VARCHAR)")
            con.execute("INSERT INTO g.probe VALUES (?)", [_SENTINEL])
            con.execute("CHECKPOINT g")
        finally:
            con.close()
        # (a) sentinel must NOT appear in the raw bytes
        if _SENTINEL.encode("utf-8") in p.read_bytes():
            return False
        # (b) opening without the key must FAIL (httpfs loaded, so the failure is no-KEY,
        #     not no-crypto -- a meaningful encryption proof)
        try:
            c2 = _persisted_connection()
            c2.execute(f"ATTACH '{p.as_posix()}' AS x")
            c2.execute("SELECT * FROM x.probe").fetchall()
            c2.close()
            return False  # opened without a key -> NOT encrypted
        except Exception:  # noqa: BLE001 - expected: encrypted store rejects no-key open
            pass
        # (c) opening with the key must return the sentinel
        c3 = _persisted_connection()
        try:
            c3.execute(f"ATTACH '{p.as_posix()}' AS y (ENCRYPTION_KEY '{key}')")
            got = c3.execute("SELECT s FROM y.probe").fetchone()
        finally:
            c3.close()
        return bool(got and got[0] == _SENTINEL)
    except Exception:  # noqa: BLE001
        _LOG.warning("columnar encryption gate raised; treating as unavailable", exc_info=True)
        return False
    finally:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def _store_dir() -> Path:
    override = os.getenv("OO_COLUMNAR_DIR")
    if override:
        return Path(override)
    from src.paths import data_dir

    return Path(data_dir())


def status(passphrase: str | None = None) -> dict:
    """Honest disclosure of the engine's mode WITHOUT opening a real store.

    ``mode`` is one of: ``unavailable`` (duckdb absent / disabled), ``persisted``
    (a secure encrypted file is usable), or ``memory`` (in-memory fallback — secure
    persisted encryption is not available offline). Never claims encryption it cannot
    prove. ``as_of`` is set by the caller when it (re)builds the store, not here.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return {"available": False, "mode": "unavailable", "encrypted": False,
                "secure_crypto": False}
    secure = bool(passphrase) and secure_crypto_available()
    return {
        "available": True,
        "mode": "persisted" if secure else "memory",
        "encrypted": secure,
        "secure_crypto": secure_crypto_available(),
    }


def connect(passphrase: str | None = None):
    """Open the derived columnar engine — a persisted ENCRYPTED store when that is
    securely possible offline, else an in-memory store. NEVER a plaintext file on disk.

    Returns a DuckDB connection, or ``None`` when the engine is unavailable (duckdb
    absent / ``OO_COLUMNAR=0``) so the caller falls back to the live query. The returned
    connection's working schema lives in the attached encrypted database ``oo`` when
    persisted, or the default in-memory catalog when not.

    COMPATIBILITY: the store is DISPOSABLE. A persisted file written by an incompatible
    DuckDB (the on-disk format is version-bound) or an older read-model schema is detected
    via its format marker and REBUILT, and ANY open failure (corrupt / unreadable file)
    deletes the file and falls back to in-memory — never a crash, because the canonical
    SQLCipher store is always the source of truth.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return None
    import duckdb

    # Persisted-encrypted ONLY when a SECURE backend is available AND the gate proves it.
    if passphrase and secure_crypto_available():
        store_dir = _store_dir()
        path = store_dir / _STORE_FILENAME
        try:
            store_dir.mkdir(parents=True, exist_ok=True)
            # Prove encryption on a throwaway probe before trusting the real file.
            if encryption_gate(store_dir / ".oo_columnar_probe.duckdb", passphrase):
                con = _attach_persisted(path, passphrase)
                marker = read_store_meta(con)
                if marker is None:
                    ensure_store_meta(con)  # a fresh store: adopt the current marker
                elif not marker_compatible(marker):
                    # Incompatible DuckDB format / read-model schema -> drop + rebuild
                    # (the store is a disposable cache; the canonical store is the truth).
                    con.close()
                    path.unlink(missing_ok=True)
                    con = _attach_persisted(path, passphrase)
                    ensure_store_meta(con)
                    _LOG.info("columnar engine: rebuilt persisted store (was %s)", marker)
                _LOG.info("columnar engine: persisted encrypted store at %s", path)
                return con
            _LOG.warning("columnar engine: encryption gate failed; using in-memory store")
        except Exception:  # noqa: BLE001 - any failure -> drop the disposable file, in-memory
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            _LOG.warning("columnar engine: persisted open failed; in-memory", exc_info=True)

    # In-memory fallback — rebuilt lazily on use; writes NO file (never plaintext).
    con = duckdb.connect(database=":memory:", config=_offline_config())
    ensure_store_meta(con)
    _LOG.info("columnar engine: in-memory store (no secure persisted encryption offline)")
    return con


def _attach_persisted(path, passphrase):
    """Open a persisted encrypted DuckDB store with the VERIFIED secure backend loaded (the
    absolute-path httpfs LOAD via :func:`_persisted_connection`), then ATTACH the encrypted
    file under the passphrase-derived key with the default authenticated GCM cipher (NEVER a
    CTR downgrade)."""
    con = _persisted_connection()  # verified httpfs LOADed; _persisted_config (file access on)
    con.execute(f"ATTACH '{path.as_posix()}' AS oo (ENCRYPTION_KEY '{_derive_key(passphrase)}')")
    con.execute("USE oo")
    return con


# Bump when the columnar read-model TABLE SHAPES change (forces a disposable rebuild).
STORE_SCHEMA_VERSION = 1


def store_format_marker() -> str:
    """A self-describing marker of what can READ this store: the DuckDB major.minor (the
    on-disk format is bound to it) + our read-model schema rev. A persisted store whose
    marker differs is treated as INCOMPATIBLE and rebuilt — never migrated, never crashed
    on (it is a disposable projection of the canonical store)."""
    v = "?"
    try:
        import duckdb

        v = ".".join(str(duckdb.__version__).split(".")[:2])  # major.minor
    except Exception:  # noqa: BLE001
        pass
    return f"duckdb-{v}/schema-{STORE_SCHEMA_VERSION}"


def ensure_store_meta(con) -> None:
    """Stamp the format marker into the store (idempotent)."""
    con.execute("CREATE TABLE IF NOT EXISTS oo_meta (k VARCHAR PRIMARY KEY, v VARCHAR)")
    con.execute("DELETE FROM oo_meta WHERE k = 'format'")
    con.execute("INSERT INTO oo_meta VALUES ('format', ?)", [store_format_marker()])


def read_store_meta(con) -> str | None:
    """The store's recorded format marker, or None if unmarked (a fresh store)."""
    try:
        row = con.execute("SELECT v FROM oo_meta WHERE k = 'format'").fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 - no oo_meta table yet (fresh/legacy store)
        return None


def marker_compatible(marker: str | None) -> bool:
    """True iff a stored marker matches the current reader (same DuckDB major.minor +
    schema rev). ``None`` (unmarked/fresh) is NOT 'incompatible' — the caller adopts it."""
    return marker == store_format_marker()


# --------------------------------------------------------------------------- #
# Read-model maintenance (Slice 4 PR-2 foundation).
#
# The derived read-model the heavy whole-corpus aggregations will read from. PR-2
# builds the maintenance + a first BYTE-IDENTICAL projection (the keyword counters); the
# perf win lands when the store is PERSISTED (a maintained store survives restarts), so
# the hot endpoints are NOT wired to it yet (offline it is in-memory = a per-process
# rebuild = no gain over the Slice-2 counters). The canonical SQLCipher store stays the
# source of truth; a reader returning nothing means the seam falls back to the live query.

_KEYWORD_AGG_DDL = (
    "CREATE OR REPLACE TABLE keyword_agg ("
    "normalized_term VARCHAR, term VARCHAR, kind VARCHAR, "
    "mention_count BIGINT, article_count BIGINT, language VARCHAR)"
)


def build_keyword_read_model(con, session) -> int:
    """(Re)build the columnar ``keyword_agg`` table from the canonical keyword counters.

    A byte-identical projection of ``Keyword.mention_count`` / ``article_count`` (the
    Slice-2 counters) — NOT a recompute, so it inherits their honesty envelope. Off the
    request path (a background/maintenance step). Returns the row count written. The
    canonical store is unchanged; this is a disposable derived table.
    """
    from src.analytics.queries import kind_of
    from src.database.models import Keyword

    con.execute(_KEYWORD_AGG_DDL)
    rows = [
        (kw.normalized_term, kw.term, kind_of(kw), int(kw.mention_count or 0),
         int(kw.article_count or 0), kw.language)
        for kw in session.query(Keyword).filter(Keyword.mention_count > 0)
    ]
    if rows:
        con.executemany(
            "INSERT INTO keyword_agg VALUES (?, ?, ?, ?, ?, ?)", rows
        )
    return len(rows)


def top_terms_raw(con, *, kind: str | None = None, limit: int = 20) -> list[dict]:
    """Read the corpus-wide most-mentioned keywords from the columnar read-model.

    Returns the SAME raw row shape the live counter query produces
    (``{term, normalized, kind, mentions, articles}``) BEFORE the Python family/ring
    grouping — so the seam can apply the existing honesty layers unchanged and the
    result stays byte-identical. Returns ``[]`` if the table is absent (caller falls back
    to the live query). Counts only, no score.
    """
    try:
        sql = "SELECT term, normalized_term, kind, mention_count, article_count FROM keyword_agg"
        params: list = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY mention_count DESC LIMIT ?"
        params.append(int(limit))
        out = con.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001 - missing table / cold store -> fall back to live
        return []
    return [
        {"term": r[0], "normalized": r[1], "kind": r[2], "mentions": int(r[3]),
         "articles": int(r[4])}
        for r in out
    ]


# --------------------------------------------------------------------------- #
# D2 — the ``keyword_daily`` windowed-aggregation rollup (scaling workstream 5A-bis;
# docs/design/SCALING_DERIVED_LAYER_1000X.md).
#
# The measured freeze (field remark 8): windowed most-mentioned / trending sums
# ``keyword_mentions.count`` over an ``observed_on`` day range — ~2.4M rows on the live
# 61K-article corpus, each in-range row paying a SQLCipher page decrypt. The structural
# fix is to NOT scan the mention table on the read path: read a maintained per-day rollup
# and sum the tiny rollup instead.
#
# HONESTY (the load-bearing part, docstring'd on every function):
#   * ``mentions`` (= SUM(count)) summed over a window is EXACT — it equals the live
#     SUM(count) by construction.
#   * ``articles_on_day`` summed over a window is an UPPER BOUND on the window's distinct
#     article count: a (keyword, article) pair observed on more than one day is counted
#     once PER DAY here, whereas the live COUNT(DISTINCT article_id) dedups it across the
#     window. In the common single-day-per-article case the two are EQUAL; the rollup can
#     only ever OVER-count, never under-count. Callers disclose this as the ``columnar
#     (upper bound)`` basis, with a cheap per-keyword live-exact escape.
#     NOTE (measured): TODAY the unique ``(keyword_id, article_id)`` index means each pair
#     has exactly one mention row on exactly one day, so the bound is in fact EXACT (gap 0,
#     proven by the parity tests). We still DISCLOSE it as an upper bound because the rollup
#     STRUCTURE (pre-aggregate per day) cannot guarantee exactness on its own — it relies on
#     that external invariant; a future per-occurrence-with-date mention schema would make
#     the gap real. Honesty by construction: disclose what the structure can prove, not the
#     value it happens to yield under today's constraints.
#
# This module builds the rollup + the serve primitives + a parity probe, and PROVES parity
# in-memory (tests). The hot read path is NOT wired to it here: serving safely needs the
# corpus-epoch guard + the epoch-bump-on-mutate discipline (D3) so a re-index can never make
# an incremental rollup double-count. Until then this is a correctness scaffold — built and
# proven, dormant at runtime. The canonical SQLCipher store stays the source of truth; a cold
# / missing rollup means the seam falls back to the live query (identical results).

_KEYWORD_DAILY_DDL = (
    "CREATE OR REPLACE TABLE keyword_daily ("
    "keyword_id BIGINT, day DATE, mentions BIGINT, articles_on_day BIGINT)"
)
# Metadata projection so the windowed serve resolves term/kind/language in DuckDB (a JOIN
# on the rollup) instead of a second round-trip to the canonical store. ``is_entity`` +
# ``entity_type`` are carried verbatim so the ``kind`` filter reproduces ``_apply_kind``.
_KEYWORD_META_DDL = (
    "CREATE OR REPLACE TABLE keyword_meta ("
    "keyword_id BIGINT, normalized_term VARCHAR, term VARCHAR, kind VARCHAR, "
    "is_entity BOOLEAN, entity_type VARCHAR, language VARCHAR)"
)


def _set_meta(con, key: str, value) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS oo_meta (k VARCHAR PRIMARY KEY, v VARCHAR)")
    con.execute("DELETE FROM oo_meta WHERE k = ?", [key])
    con.execute("INSERT INTO oo_meta VALUES (?, ?)", [key, str(value)])


def _get_meta(con, key: str) -> str | None:
    try:
        row = con.execute("SELECT v FROM oo_meta WHERE k = ?", [key]).fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 - no oo_meta yet
        return None


def build_keyword_daily(con, session, *, batch_size: int = 50_000) -> dict:
    """(Re)build ``keyword_daily`` + ``keyword_meta`` — the FULL streamed build (D2).

    Streams canonical mention rows out of the app's SQLite/SQLCipher connection in
    ``batch_size`` chunks (column-projected — never ``SELECT *``, never the decrypt-heavy
    article join), inserts each batch into a DuckDB staging table, then GROUPs THERE
    (columnar, fast) into the per-day rollup. This is a resumable-shaped BATCH job scheduled
    WITH the re-index — NEVER on the query path.

    Rows with a NULL ``observed_on`` are excluded: the windowed query filters by an
    ``observed_on`` range, so an undated mention can never fall inside a window. Records
    ``last_mention_id`` (MAX mention id) in ``oo_meta`` so D3 can refresh incrementally.
    Returns a small tally. The canonical store is unchanged; this is a disposable table.
    """
    from sqlalchemy import text as _sql

    from src.analytics.queries import kind_of
    from src.database.models import Keyword

    ensure_store_meta(con)  # idempotent: guarantees oo_meta exists

    # -- stream mentions -> DuckDB staging (dates kept as text; cast in the GROUP BY) ---- #
    con.execute("CREATE OR REPLACE TABLE keyword_daily_stage "
                "(keyword_id BIGINT, day VARCHAR, cnt BIGINT, article_id BIGINT)")
    result = session.execute(_sql(
        "SELECT keyword_id, observed_on, count, article_id FROM keyword_mentions "
        "WHERE observed_on IS NOT NULL"
    ))
    streamed = 0
    while True:
        chunk = result.fetchmany(batch_size)
        if not chunk:
            break
        con.executemany(
            "INSERT INTO keyword_daily_stage VALUES (?, ?, ?, ?)",
            [(int(r[0]), str(r[1])[:10], int(r[2]), int(r[3])) for r in chunk],
        )
        streamed += len(chunk)

    con.execute(_KEYWORD_DAILY_DDL)
    con.execute(
        "INSERT INTO keyword_daily "
        "SELECT keyword_id, CAST(day AS DATE) AS day, SUM(cnt) AS mentions, "
        "COUNT(DISTINCT article_id) AS articles_on_day "
        "FROM keyword_daily_stage GROUP BY keyword_id, CAST(day AS DATE)"
    )
    con.execute("DROP TABLE keyword_daily_stage")
    daily_rows = con.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0]

    # -- keyword metadata projection (for the windowed serve's JOIN) --------------------- #
    con.execute(_KEYWORD_META_DDL)
    meta = [
        (int(kw.id), kw.normalized_term, kw.term, kind_of(kw),
         bool(kw.is_entity), kw.entity_type, kw.language)
        for kw in session.query(Keyword).filter(Keyword.mention_count > 0)
    ]
    if meta:
        con.executemany("INSERT INTO keyword_meta VALUES (?, ?, ?, ?, ?, ?, ?)", meta)

    max_id = session.execute(_sql("SELECT MAX(id) FROM keyword_mentions")).scalar()
    _set_meta(con, "keyword_daily.last_mention_id", int(max_id or 0))
    return {
        "streamed_mentions": streamed,
        "keyword_daily_rows": int(daily_rows),
        "keyword_meta_rows": len(meta),
        "last_mention_id": int(max_id or 0),
    }


def _kind_where(kind: str | None, params: list) -> str:
    """Reproduce ``queries._apply_kind`` against the projected ``keyword_meta``."""
    if not kind:
        return ""
    if kind == "term":
        return " AND m.is_entity = FALSE"
    if kind == "entity":
        return " AND m.is_entity = TRUE"
    params.append(kind)
    return " AND m.entity_type = ?"


def windowed_term_counts(
    con, *, start_day=None, end_day=None, kind: str | None = None
) -> dict[int, tuple[int, int]]:
    """Per-keyword windowed ``(mentions, articles_upper_bound)`` from the rollup.

    ``mentions`` is EXACT (== live SUM(count) over the window). ``articles_upper_bound`` is
    ``SUM(articles_on_day)`` — an UPPER BOUND on the window's distinct-article count (see the
    module honesty note). ``start_day`` inclusive / ``end_day`` inclusive; either may be None
    for an open bound (None/None = all history). Returns ``{}`` if the rollup is absent (the
    caller falls back to the live query). Counts only, no score.
    """
    where = []
    params: list = []
    if start_day is not None:
        where.append("d.day >= ?")
        params.append(start_day)
    if end_day is not None:
        where.append("d.day <= ?")
        params.append(end_day)
    kw = " WHERE " + " AND ".join(where) if where else ""
    try:
        rows = con.execute(
            "SELECT keyword_id, SUM(mentions), SUM(articles_on_day) "  # nosec B608 - only the constant WHERE fragments (d.day >= ?/<= ?) are concatenated; every value is a bound ? param
            "FROM keyword_daily d" + kw + " GROUP BY keyword_id", params
        ).fetchall()
    except Exception:  # noqa: BLE001 - missing/cold rollup -> fall back to live
        return {}
    return {int(r[0]): (int(r[1]), int(r[2])) for r in rows}


def windowed_top_terms_raw(
    con, *, start_day=None, end_day=None, kind: str | None = None, limit: int = 20
) -> list[dict]:
    """The ranked windowed most-mentioned rows from the rollup — the shape the live
    ``top_terms`` produces BEFORE the Python hidden-word / family / ring layers, so the seam
    (D3) can apply those unchanged and stay byte-identical.

    Ordered by ``mentions`` DESC (the live order). ``mentions`` EXACT; ``articles`` the
    upper bound. Returns ``[]`` if the rollup / metadata are absent. Counts only, no score.
    """
    params: list = []
    where = ["d.day >= ?"] if start_day is not None else []
    if start_day is not None:
        params.append(start_day)
    if end_day is not None:
        where.append("d.day <= ?")
        params.append(end_day)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    kind_sql = _kind_where(kind, params)
    params.append(int(limit))
    try:
        rows = con.execute(
            "SELECT m.term, m.normalized_term, m.kind, m.language, "  # nosec B608 - only constant clause fragments (where_sql/kind_sql) are concatenated; every value is a bound ? param
            "SUM(d.mentions) AS mentions, SUM(d.articles_on_day) AS articles "
            "FROM keyword_daily d JOIN keyword_meta m ON m.keyword_id = d.keyword_id"
            + where_sql + kind_sql
            + " GROUP BY m.term, m.normalized_term, m.kind, m.language "
            "ORDER BY mentions DESC LIMIT ?",
            params,
        ).fetchall()
    except Exception:  # noqa: BLE001 - missing/cold rollup -> fall back to live
        return []
    return [
        {"term": r[0], "normalized": r[1], "kind": r[2], "language": r[3],
         "mentions": int(r[4]), "articles": int(r[5])}
        for r in rows
    ]


def keyword_daily_parity(con, session, *, start_day=None, end_day=None) -> dict:
    """Honest parity probe: compare the rollup's windowed counts to the LIVE query, so we
    can PROVE (on a real corpus) that ``mentions`` is exact and the distinct-article count is
    an upper bound whose gap is reported — never hidden. Used by tests + a future diagnostics
    surface. Read-only; counts only.
    """
    from sqlalchemy import text as _sql

    roll = windowed_term_counts(con, start_day=start_day, end_day=end_day)
    clauses = ["observed_on IS NOT NULL"]
    p: dict = {}
    if start_day is not None:
        clauses.append("observed_on >= :s")
        p["s"] = start_day
    if end_day is not None:
        clauses.append("observed_on <= :e")
        p["e"] = end_day
    live_rows = session.execute(_sql(
        "SELECT keyword_id, SUM(count), COUNT(DISTINCT article_id) FROM keyword_mentions "  # nosec B608 - clauses are constant SQL fragments; every value is a bound :param
        "WHERE " + " AND ".join(clauses) + " GROUP BY keyword_id"
    ), p).fetchall()
    live = {int(r[0]): (int(r[1]), int(r[2])) for r in live_rows}

    mention_mismatches = 0
    distinct_gap_keywords = 0
    distinct_gap_total = 0
    upper_bound_holds = True
    for kid, (lm, la) in live.items():
        rm, ra = roll.get(kid, (0, 0))
        if rm != lm:
            mention_mismatches += 1
        if ra < la:
            upper_bound_holds = False  # a rollup distinct count must NEVER be below live
        if ra > la:
            distinct_gap_keywords += 1
            distinct_gap_total += ra - la
    return {
        "keywords_compared": len(live),
        "mentions_exact": mention_mismatches == 0,
        "mention_mismatches": mention_mismatches,
        "distinct_upper_bound_holds": upper_bound_holds,
        "distinct_gap_keywords": distinct_gap_keywords,
        "distinct_gap_total": distinct_gap_total,
        "method": (
            "keyword_daily windowed counts vs the live keyword_mentions aggregation. "
            "mentions (SUM(count)) is exact; articles (SUM(articles_on_day)) is an upper "
            "bound on COUNT(DISTINCT article_id) — the gap is the count of (keyword,article) "
            "pairs observed on more than one day, reported here, never hidden."
        ),
    }


# --------------------------------------------------------------------------- #
# D3 — incremental refresh + the corpus-epoch guard (the correctness-critical part;
# docs/design/SCALING_DERIVED_LAYER_1000X.md). Keeps the rollup fresh WITHOUT a full
# rebuild every pass, while a re-index can never make it double-count.
#
# THE TRAP (grounded in this repo): ``index_article`` does delete-then-reinsert of an
# article's mentions (store.py). So an id-watermark MERGE-ADD (tail = ``id > last_mention_id``)
# is correct ONLY for APPEND — a brand-new article's mentions carry strictly higher ids the
# tail captures once. EVERY path that re-runs ``index_article`` over an EXISTING article
# (reindex_all_batch / reindex_articles / reindex_imported_articles [restore] / clean-up-
# keywords) AND ``prune_orphan_keywords`` (deletes rows) leaves the OLD contribution in the
# rollup AND re-inserts higher-id rows into the tail = a fabricated (doubled) number. So those
# mutators bump a CORPUS EPOCH; a changed epoch forces a FULL rebuild, never an incremental
# merge. Normal new-article ingest does NOT bump the epoch (else we full-rebuild every pass).
#
# The epoch itself lives on the CANONICAL side and is passed in here — this module owns only
# the refresh DECISION + the merge. Wiring the canonical epoch counter into the mutators, and
# wiring the serve into the hot read path behind the ``built_epoch == corpus_epoch`` guard,
# are the next slice; this one builds + proves the incremental algorithm in-memory (the design
# mandate), dormant at runtime.


def _table_present(con, name: str) -> bool:
    try:
        row = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()
        return row is not None
    except Exception:  # noqa: BLE001 - catalog unavailable -> treat as absent
        return False


def _upsert_keyword_meta(con, session, keyword_ids: list[int]) -> int:
    """Add ``keyword_meta`` rows for keyword ids not already projected (new keywords that
    first appear in an incremental tail). Existing rows are LEFT unchanged — an incremental
    merge is APPEND-only (the epoch guard forces a full rebuild when a keyword's metadata
    could have changed via re-index), so a present row is already current."""
    from src.analytics.queries import kind_of
    from src.database.models import Keyword

    added = 0
    for i in range(0, len(keyword_ids), 900):  # bounded IN() (SQLite variable limit)
        chunk = keyword_ids[i : i + 900]
        kws = session.query(Keyword).filter(Keyword.id.in_(chunk)).all()
        rows = [
            (int(kw.id), kw.normalized_term, kw.term, kind_of(kw),
             bool(kw.is_entity), kw.entity_type, kw.language)
            for kw in kws
        ]
        if not rows:
            continue
        con.execute("CREATE OR REPLACE TEMP TABLE _new_meta ("
                    "keyword_id BIGINT, normalized_term VARCHAR, term VARCHAR, kind VARCHAR, "
                    "is_entity BOOLEAN, entity_type VARCHAR, language VARCHAR)")
        con.executemany("INSERT INTO _new_meta VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute(
            "INSERT INTO keyword_meta SELECT n.* FROM _new_meta n "
            "WHERE NOT EXISTS (SELECT 1 FROM keyword_meta m WHERE m.keyword_id = n.keyword_id)"
        )
        con.execute("DROP TABLE _new_meta")
        added += len(rows)
    return added


def refresh_keyword_daily(con, session, *, corpus_epoch: int, batch_size: int = 50_000) -> dict:
    """Bring ``keyword_daily`` up to date. FULL rebuild when the corpus epoch changed since
    the last build (a re-index / prune / restore happened) or there is no usable prior build;
    otherwise an INCREMENTAL merge of the new mention tail.

    ``corpus_epoch`` is supplied by the caller from the canonical side (the value bumped by
    the re-index/prune/restore mutators). Returns ``{mode: 'full'|'incremental', ...}``.

    Incremental correctness: the tail (``id > last_mention_id``) contains only APPENDED
    mentions (the epoch guard rules out a re-index), so each carries a NEW ``(keyword,
    article)`` pair and a fresh higher id — merge-ADD into the per-day rollup is exact
    (mentions summed; per-day distinct articles summed, disjoint from existing days by the
    unique-pair invariant). Undated tail rows are skipped but the watermark still advances
    past them (never re-scanned).
    """
    ensure_store_meta(con)
    built_epoch = _get_meta(con, "keyword_daily.built_epoch")
    needs_full = (
        built_epoch is None
        or not _table_present(con, "keyword_daily")
        or not _table_present(con, "keyword_meta")
        or int(built_epoch) != int(corpus_epoch)
    )
    if needs_full:
        tally = build_keyword_daily(con, session, batch_size=batch_size)
        _set_meta(con, "keyword_daily.built_epoch", int(corpus_epoch))
        return {"mode": "full", "corpus_epoch": int(corpus_epoch), **tally}

    # -- INCREMENTAL: merge only the tail (id > watermark) ------------------------------- #
    from sqlalchemy import text as _sql

    last_id = int(_get_meta(con, "keyword_daily.last_mention_id") or 0)
    new_max = int(session.execute(_sql("SELECT MAX(id) FROM keyword_mentions")).scalar() or last_id)
    if new_max <= last_id:
        return {"mode": "incremental", "merged_days": 0, "new_keywords": 0,
                "last_mention_id": last_id, "corpus_epoch": int(corpus_epoch)}

    con.execute("CREATE OR REPLACE TABLE keyword_daily_stage "
                "(keyword_id BIGINT, day VARCHAR, cnt BIGINT, article_id BIGINT)")
    result = session.execute(_sql(
        "SELECT keyword_id, observed_on, count, article_id FROM keyword_mentions "
        "WHERE id > :lo AND observed_on IS NOT NULL"
    ), {"lo": last_id})
    while True:
        chunk = result.fetchmany(batch_size)
        if not chunk:
            break
        con.executemany(
            "INSERT INTO keyword_daily_stage VALUES (?, ?, ?, ?)",
            [(int(r[0]), str(r[1])[:10], int(r[2]), int(r[3])) for r in chunk],
        )

    con.execute(
        "CREATE OR REPLACE TABLE keyword_daily_tail AS "
        "SELECT keyword_id, CAST(day AS DATE) AS day, SUM(cnt) AS mentions, "
        "COUNT(DISTINCT article_id) AS articles_on_day "
        "FROM keyword_daily_stage GROUP BY keyword_id, CAST(day AS DATE)"
    )
    # Portable MERGE: add to matched (keyword, day) rows, insert the rest.
    con.execute(
        "UPDATE keyword_daily d SET mentions = d.mentions + t.mentions, "
        "articles_on_day = d.articles_on_day + t.articles_on_day "
        "FROM keyword_daily_tail t WHERE d.keyword_id = t.keyword_id AND d.day = t.day"
    )
    con.execute(
        "INSERT INTO keyword_daily "
        "SELECT keyword_id, day, mentions, articles_on_day FROM keyword_daily_tail t "
        "WHERE NOT EXISTS (SELECT 1 FROM keyword_daily d "
        "WHERE d.keyword_id = t.keyword_id AND d.day = t.day)"
    )
    merged_days = con.execute("SELECT COUNT(*) FROM keyword_daily_tail").fetchone()[0]
    tail_kids = [int(r[0]) for r in
                 con.execute("SELECT DISTINCT keyword_id FROM keyword_daily_stage").fetchall()]
    new_keywords = _upsert_keyword_meta(con, session, tail_kids)
    con.execute("DROP TABLE keyword_daily_stage")
    con.execute("DROP TABLE keyword_daily_tail")
    _set_meta(con, "keyword_daily.last_mention_id", new_max)
    return {"mode": "incremental", "merged_days": int(merged_days),
            "new_keywords": int(new_keywords), "last_mention_id": new_max,
            "corpus_epoch": int(corpus_epoch)}


def refresh_persisted_read_model(session, passphrase: str | None = None) -> dict:
    """Maintain the read-model in the background — ONLY when the store is PERSISTED.

    Called where ``warm_cache`` runs (off the request path). Persisting the read-model is
    worthwhile only when it SURVIVES the process (the encrypted persisted store); an
    in-memory store is rebuilt per process, so building it in the background would be
    wasted work — hence the in-memory case is a deliberate no-op. Best-effort: a failure
    never breaks the pass; the canonical store remains the source of truth. Returns a
    small status dict.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return {"skipped": "unavailable"}
    if not (passphrase and secure_crypto_available()):
        return {"skipped": "in-memory"}  # nothing to persist across restarts
    con = None
    try:
        con = connect(passphrase=passphrase)
        if con is None:
            return {"skipped": "unavailable"}
        rows = build_keyword_read_model(con, session)
        return {"persisted": True, "keyword_agg_rows": rows}
    except Exception:  # noqa: BLE001 - a background accelerator must never break a pass
        _LOG.warning("columnar read-model refresh failed", exc_info=True)
        return {"skipped": "error"}
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# D4 — the ``source_coverage`` per-country rollup (scaling 5A-bis;
# docs/design/SCALING_DERIVED_LAYER_1000X.md).
#
# The choropleth map endpoint (``queries.source_country_counts``) re-scans the ARTICLES
# table (per-country article count + mean tone via a source-country join) plus the sources
# and mention tables on EVERY read. Unlike ``keyword_daily`` (millions of per-day rows),
# the source-coverage RESULT is tiny (one row per country), so the honest win here is
# RESULT-CACHING, not a columnar scan: build the small per-country aggregate ONCE (with
# SQLite's native GROUP BY — faster than marshalling every row to Python) and cache it in
# the derived store, so repeated map reads hit the cached rows instead of re-scanning.
#
# This is the D4 analog of D2/D3: keyed by the corpus epoch (so a re-index/prune/restore
# forces a rebuild) AND by the article/mention id watermarks (so ordinary new-ingest is
# picked up). FULL rebuild only — the result set is small, so there is no incremental
# merge to get wrong. Parity is by construction (same GROUP BY as the live query) and
# proven by :func:`source_coverage_parity`. HONESTY: counts only, no score; mean tone is
# stored as (sum, n) so a country with no scored (English) article reports None honestly;
# a country-less source/article goes to the '' unlocated bucket, never guessed onto a map.
#
# Like D2/D3 it is built + proven, dormant at runtime: the live map endpoint is NOT wired
# to it yet (offline the store is in-memory = a per-process rebuild = no runtime gain; the
# durability win lands with the persisted store, D1). The canonical store stays the source
# of truth; a cold/missing rollup means the seam falls back to the live query.

_SOURCE_COVERAGE_DDL = (
    "CREATE OR REPLACE TABLE source_coverage ("
    "country VARCHAR, sources BIGINT, articles BIGINT, keyword_mentions BIGINT, "
    "sentiment_sum DOUBLE, sentiment_n BIGINT)"
)


def _norm_cc(cc) -> str:
    """Normalise a country code the same way the live query does (trim + lowercase; a
    country-less source/article -> the '' unlocated bucket, never guessed onto a map)."""
    return (cc or "").strip().lower()


def build_source_coverage(con, session) -> dict:
    """(Re)build the per-country ``source_coverage`` rollup — the FULL build (D4).

    Aggregates the choropleth measures with SQLite's native GROUP BY (one pass each, kept
    in C — faster than streaming every article row to Python) and CACHES the small
    per-country result in the derived store: sources per catalogued country, articles +
    mean-tone (as sum+n) via the source-country join, and keyword mentions per denormalised
    mention country. Records the article + mention id watermarks + as_of so
    :func:`refresh_source_coverage` can decide full-vs-skip. Counts only, no score.
    """
    from datetime import UTC, datetime

    from sqlalchemy import func
    from sqlalchemy import text as _sql

    from src.database.models import Article, KeywordMention, Source

    ensure_store_meta(con)

    # Sources per catalogued country (tiny table).
    src_by_cc: dict[str, int] = {}
    for cc, n in session.query(Source.country, func.count(Source.id)).group_by(Source.country):
        src_by_cc[_norm_cc(cc)] = src_by_cc.get(_norm_cc(cc), 0) + int(n or 0)

    # Articles + mean tone per source-country, in ONE scan (avg ignores NULL scores;
    # count(sentiment_score) is the scored/English subset size). Same shape the live
    # ``source_country_counts`` uses, so the rollup is byte-identical by construction.
    art_by_cc: dict[str, tuple[int, float, int]] = {}
    for cc, n, tone_sum, tone_n in session.query(
        Source.country,
        func.count(Article.id),
        func.sum(Article.sentiment_score),
        func.count(Article.sentiment_score),
    ).join(Article, Article.source_id == Source.id).group_by(Source.country):
        key = _norm_cc(cc)
        cur = art_by_cc.get(key, (0, 0.0, 0))
        art_by_cc[key] = (
            cur[0] + int(n or 0),
            cur[1] + float(tone_sum or 0.0),
            cur[2] + int(tone_n or 0),
        )

    # Keyword mentions per denormalised source-country (index scan; no article decrypt).
    kw_by_cc: dict[str, int] = {}
    for cc, n in session.query(KeywordMention.country, func.count()).group_by(
        KeywordMention.country
    ):
        kw_by_cc[_norm_cc(cc)] = kw_by_cc.get(_norm_cc(cc), 0) + int(n or 0)

    countries = set(src_by_cc) | set(art_by_cc) | set(kw_by_cc)
    rows = []
    for cc in countries:
        arts = art_by_cc.get(cc, (0, 0.0, 0))
        rows.append((cc, int(src_by_cc.get(cc, 0)), int(arts[0]), int(kw_by_cc.get(cc, 0)),
                     float(arts[1]), int(arts[2])))

    con.execute(_SOURCE_COVERAGE_DDL)
    if rows:
        con.executemany("INSERT INTO source_coverage VALUES (?, ?, ?, ?, ?, ?)", rows)

    max_art = session.execute(_sql("SELECT MAX(id) FROM articles")).scalar()
    max_men = session.execute(_sql("SELECT MAX(id) FROM keyword_mentions")).scalar()
    as_of = datetime.now(UTC).isoformat(timespec="seconds")
    _set_meta(con, "source_coverage.last_article_id", int(max_art or 0))
    _set_meta(con, "source_coverage.last_mention_id", int(max_men or 0))
    _set_meta(con, "source_coverage.as_of", as_of)
    return {
        "rows": len(rows),
        "countries": len([r for r in rows if r[0]]),  # excludes the '' unlocated bucket
        "last_article_id": int(max_art or 0),
        "last_mention_id": int(max_men or 0),
        "as_of": as_of,
    }


def refresh_source_coverage(con, session, *, corpus_epoch: int) -> dict:
    """Bring ``source_coverage`` up to date. FULL rebuild when the corpus epoch changed
    (a re-index / prune / restore), when ordinary ingest advanced the article/mention id
    watermark, or when there is no usable prior build. Otherwise a no-op (fresh).

    The result set is tiny, so a rebuild is cheap and there is no incremental merge to get
    wrong — the epoch/watermark decision keeps it fresh without re-scanning on every serve.
    Returns ``{mode: 'full'|'fresh', ...}``.
    """
    from sqlalchemy import text as _sql

    ensure_store_meta(con)
    built_epoch = _get_meta(con, "source_coverage.built_epoch")
    last_art = int(_get_meta(con, "source_coverage.last_article_id") or -1)
    last_men = int(_get_meta(con, "source_coverage.last_mention_id") or -1)
    cur_art = int(session.execute(_sql("SELECT MAX(id) FROM articles")).scalar() or 0)
    cur_men = int(session.execute(_sql("SELECT MAX(id) FROM keyword_mentions")).scalar() or 0)
    needs_full = (
        built_epoch is None
        or not _table_present(con, "source_coverage")
        or int(built_epoch) != int(corpus_epoch)
        or cur_art != last_art
        or cur_men != last_men
    )
    if not needs_full:
        return {"mode": "fresh", "corpus_epoch": int(corpus_epoch)}
    tally = build_source_coverage(con, session)
    _set_meta(con, "source_coverage.built_epoch", int(corpus_epoch))
    return {"mode": "full", "corpus_epoch": int(corpus_epoch), **tally}


def source_coverage_rows(con) -> list[dict]:
    """The cached per-country coverage rows from the rollup — the serve primitive.

    Shape mirrors ``queries.source_country_counts`` per-country rows: ``{country, sources,
    articles, keywords, sentiment, sentiment_n}`` where ``sentiment`` is the mean over the
    scored subset (None when no scored/English article — never a fabricated zero) and the
    '' country is the unlocated bucket. Returns ``[]`` if the rollup is absent (caller
    falls back to the live query). Counts only, no score.
    """
    try:
        out = con.execute(
            "SELECT country, sources, articles, keyword_mentions, sentiment_sum, "
            "sentiment_n FROM source_coverage"
        ).fetchall()
    except Exception:  # noqa: BLE001 - missing/cold rollup -> fall back to live
        return []
    rows = []
    for cc, sources, articles, kw, tone_sum, tone_n in out:
        n = int(tone_n or 0)
        rows.append({
            "country": cc,
            "sources": int(sources or 0),
            "articles": int(articles or 0),
            "keywords": int(kw or 0),
            "sentiment": round(float(tone_sum) / n, 3) if n else None,
            "sentiment_n": n,
        })
    return rows


def source_coverage_parity(con, session) -> dict:
    """Honest parity probe: compare the rollup's per-country coverage to the LIVE
    ``queries.source_country_counts`` query, so a test can PROVE (on a real corpus) that
    the cache is byte-faithful — the counts must match exactly (both derive from the same
    GROUP BY). Read-only; counts only, no score.
    """
    from src.analytics.queries import source_country_counts

    live = source_country_counts(session)
    live_by_cc: dict[str, dict] = {r["country"]: r for r in live["by_country"]}
    # Fold the live 'unlocated' bucket into the '' key for a like-for-like comparison.
    unloc = live["unlocated"]
    live_by_cc[""] = {"country": "", "sources": unloc["sources"], "articles": unloc["articles"],
                      "keywords": unloc["keywords"], "sentiment": None, "sentiment_n": 0}

    roll_by_cc = {r["country"]: r for r in source_coverage_rows(con)}
    mismatches = 0
    checked = 0
    for cc, lr in live_by_cc.items():
        rr = roll_by_cc.get(cc)
        if cc == "" and lr["sources"] == 0 and lr["articles"] == 0 and lr["keywords"] == 0:
            continue  # no unlocated data on either side -> nothing to compare
        checked += 1
        if rr is None or (rr["sources"], rr["articles"], rr["keywords"]) != (
            lr["sources"], lr["articles"], lr["keywords"]
        ):
            mismatches += 1
    return {
        "countries_compared": checked,
        "counts_match": mismatches == 0,
        "mismatches": mismatches,
        "method": (
            "source_coverage rollup per-country {sources, articles, keyword mentions} vs "
            "the live source_country_counts aggregation. Both derive from the same GROUP BY, "
            "so the counts must match exactly. Counts only, no score."
        ),
    }
