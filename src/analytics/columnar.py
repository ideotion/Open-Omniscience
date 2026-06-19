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
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

_LOG = logging.getLogger(__name__)

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


def _derive_key(passphrase: str) -> str:
    """A DuckDB ENCRYPTION_KEY derived from the ONE corpus passphrase.

    NOT a second key surface: there is no second secret for the user to manage — the
    derived store rides the same passphrase as the canonical SQLCipher store. A hex
    digest avoids any SQL-literal-escaping hazard in the ``ENCRYPTION_KEY`` clause. The
    store is a disposable cache; this protects the same at-rest threat model.
    """
    return hashlib.sha256(("oo-columnar-v1:" + passphrase).encode("utf-8")).hexdigest()


def secure_crypto_available() -> bool:
    """True ONLY if a SECURE crypto backend (OpenSSL via ``httpfs``) can be loaded
    OFFLINE. DuckDB's built-in mbedtls is "NOT securely encrypted" and is never trusted
    for the derived store. When this is False the engine runs in-memory (no plaintext
    file is ever written). Pure check; opens and closes a throwaway in-memory connection.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return False
    import duckdb

    try:
        con = duckdb.connect(config=_offline_config())
        try:
            con.execute("LOAD httpfs")  # OpenSSL crypto; autoload is OFF so this is local-only
            return True
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - not loadable offline -> not available
        return False


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
    import duckdb

    p = Path(path)
    key = _derive_key(passphrase)
    try:
        if p.exists():
            p.unlink()
        con = duckdb.connect(config=_offline_config())
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
        # (b) opening without the key must FAIL
        try:
            c2 = duckdb.connect(config=_offline_config())
            c2.execute(f"ATTACH '{p.as_posix()}' AS x")
            c2.execute("SELECT * FROM x.probe").fetchall()
            c2.close()
            return False  # opened without a key -> NOT encrypted
        except Exception:  # noqa: BLE001 - expected: encrypted store rejects no-key open
            pass
        # (c) opening with the key must return the sentinel
        c3 = duckdb.connect(config=_offline_config())
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
    persisted, or the default in-memory catalog when not. PR-1: the engine + safety
    rails; building/serving aggregations from it is PR-2/3.
    """
    if not duckdb_available() or os.getenv("OO_COLUMNAR") == "0":
        return None
    import duckdb

    # Persisted-encrypted ONLY when a SECURE backend is available AND the gate proves it.
    if passphrase and secure_crypto_available():
        store_dir = _store_dir()
        try:
            store_dir.mkdir(parents=True, exist_ok=True)
            path = store_dir / _STORE_FILENAME
            # Prove encryption on a throwaway probe before trusting the real file.
            if encryption_gate(store_dir / ".oo_columnar_probe.duckdb", passphrase):
                con = duckdb.connect(config=_offline_config())
                con.execute("LOAD httpfs")
                con.execute(
                    f"ATTACH '{path.as_posix()}' AS oo (ENCRYPTION_KEY '{_derive_key(passphrase)}')"
                )
                con.execute("USE oo")
                _LOG.info("columnar engine: persisted encrypted store at %s", path)
                return con
            _LOG.warning("columnar engine: encryption gate failed; using in-memory store")
        except Exception:  # noqa: BLE001 - any failure -> in-memory, never plaintext
            _LOG.warning("columnar engine: persisted open failed; in-memory", exc_info=True)

    # In-memory fallback — rebuilt lazily on use; writes NO file (never plaintext).
    con = duckdb.connect(database=":memory:", config=_offline_config())
    _LOG.info("columnar engine: in-memory store (no secure persisted encryption offline)")
    return con
