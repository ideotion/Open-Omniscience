"""D1 offline httpfs pin-and-verify loader (S3.1).

Proves the verify MECHANISM against a FIXTURE "extension" whose sha256 is pinned in an
injected fixture registry — refuse-on-missing / refuse-on-mismatch / empty-pin-in-memory /
version-coupling — WITHOUT the real per-OS binary or any network. The real binaries + their
sha256 are the maintainer's networked build (blank in the shipped registry), so the loader
stays in-memory here; the real encrypted round-trip is the CI-only lane at the bottom.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from src.analytics import columnar

MINOR = columnar._duckdb_minor()  # e.g. "1.5"; None if duckdb absent

pytestmark = pytest.mark.skipif(MINOR is None, reason="duckdb ([columnar] extra) not installed")


def _fixture_ext(tmp_path: Path, content: bytes = b"OO-FIXTURE-httpfs-not-a-real-extension"):
    f = tmp_path / "httpfs-fixture.duckdb_extension"
    f.write_bytes(content)
    return f, hashlib.sha256(content).hexdigest()


def _pin(monkeypatch, plat: str, *, version: str, sha256: str, file: str) -> None:
    """Inject a fixture registry pin + force the platform key (host-independent tests)."""
    monkeypatch.setattr(columnar, "_platform_arch", lambda: plat)
    monkeypatch.setattr(
        columnar, "_httpfs_pins",
        lambda: {plat: {"version": version, "sha256": sha256, "file": file}},
    )


# --- the SHIPPED state: blank pins keep the engine in-memory (safe to ship pre-binaries) --- #

def test_empty_pin_table_stays_in_memory():
    # Reads the REAL configs/external_artifacts.yml (blank pins) -> no verified binary.
    assert columnar._verified_httpfs_path() is None
    assert columnar.secure_crypto_available() is False


# --- audit BUG-1: the reason is SURFACED, never swallowed into a silent False ------------- #

def test_secure_crypto_reason_names_the_missing_binary():
    assert columnar.secure_crypto_available() is False
    reason = columnar.secure_crypto_reason()
    assert reason and "no verified bundled httpfs" in reason  # inspectable, not a silent False


def test_secure_crypto_reason_disabled_env(monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR", "0")
    assert columnar.secure_crypto_available() is False
    assert "OO_COLUMNAR=0" in (columnar.secure_crypto_reason() or "")


def test_secure_crypto_reason_surfaces_a_swallowed_load_error(monkeypatch, tmp_path, caplog):
    # the core BUG-1 regression: all gates pass but the httpfs LOAD raises -> the cause is
    # SURFACED (reported + logged), never swallowed. This is exactly the CI-red diagnosability
    # hole the audit flagged (the bare `except Exception: return False`).
    import logging

    f, _sha = _fixture_ext(tmp_path)
    monkeypatch.setattr(columnar, "_verified_httpfs_path", lambda: f)  # earlier gates pass

    def _boom(*a, **k):
        raise RuntimeError("httpfs LOAD blew up (simulated CI failure)")

    monkeypatch.setattr(columnar, "_persisted_connection", _boom)
    with caplog.at_level(logging.WARNING, logger="src.analytics.columnar"):
        assert columnar.secure_crypto_available() is False  # still degrades to in-memory
    reason = columnar.secure_crypto_reason()
    assert reason and "httpfs LOAD blew up" in reason  # the cause is reported, not hidden
    assert columnar._LAST_CRYPTO_ERROR and "RuntimeError" in columnar._LAST_CRYPTO_ERROR
    assert any("did not LOAD offline" in r.getMessage() for r in caplog.records)  # + logged


def test_shipped_registry_httpfs_entry_is_blank_and_flagged():
    pins = columnar._httpfs_pins()  # reads the shipped registry entry
    assert set(pins) >= {"linux_amd64", "linux_arm64", "osx_amd64", "osx_arm64", "windows_amd64"}
    for plat, p in pins.items():
        assert (p.get("sha256") or "") == "", f"{plat} sha256 must be blank until the networked build"
        assert (p.get("version") or "") == "", f"{plat} version must be blank until bundled"


# --- the verify MECHANISM (fixture binary; no real httpfs, no network) --------------------- #

def test_verify_accepts_a_matching_fixture(tmp_path, monkeypatch):
    f, sha = _fixture_ext(tmp_path)
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    _pin(monkeypatch, "linux_amd64", version=f"v{MINOR}.9", sha256=sha, file=f.name)
    assert columnar._verified_httpfs_path() == str(f.resolve())


def test_refuse_on_sha256_mismatch(tmp_path, monkeypatch):
    f, _sha = _fixture_ext(tmp_path)
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    _pin(monkeypatch, "linux_amd64", version=f"v{MINOR}.9", sha256="0" * 64, file=f.name)
    assert columnar._verified_httpfs_path() is None


def test_refuse_on_missing_file(tmp_path, monkeypatch):
    _f, sha = _fixture_ext(tmp_path)
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    _pin(monkeypatch, "linux_amd64", version=f"v{MINOR}.9", sha256=sha,
         file="not-bundled.duckdb_extension")
    assert columnar._verified_httpfs_path() is None


def test_refuse_on_wrong_duckdb_minor(tmp_path, monkeypatch):
    f, sha = _fixture_ext(tmp_path)
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    _pin(monkeypatch, "linux_amd64", version="v0.1.0", sha256=sha, file=f.name)  # not the duckdb minor
    assert columnar._verified_httpfs_path() is None


def test_tampered_after_pin_is_refused(tmp_path, monkeypatch):
    f, sha = _fixture_ext(tmp_path)
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    _pin(monkeypatch, "linux_amd64", version=f"v{MINOR}.9", sha256=sha, file=f.name)
    assert columnar._verified_httpfs_path() == str(f.resolve())
    f.write_bytes(b"TAMPERED-AFTER-PINNING")  # mutate the bytes after the pin was recorded
    assert columnar._verified_httpfs_path() is None


def test_blank_version_or_sha_stays_in_memory(tmp_path, monkeypatch):
    f, sha = _fixture_ext(tmp_path)
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    _pin(monkeypatch, "linux_amd64", version="", sha256=sha, file=f.name)
    assert columnar._verified_httpfs_path() is None
    _pin(monkeypatch, "linux_amd64", version=f"v{MINOR}.9", sha256="", file=f.name)
    assert columnar._verified_httpfs_path() is None


def test_refuse_on_non_basename_file(tmp_path, monkeypatch):
    # A registry 'file' with a path separator / '..' / absolute path is refused (traversal
    # discipline), even though the fixture bytes would hash-match.
    f, sha = _fixture_ext(tmp_path)
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    for bad in ("../httpfs-fixture.duckdb_extension", "/etc/passwd", "sub/dir.duckdb_extension"):
        _pin(monkeypatch, "linux_amd64", version=f"v{MINOR}.9", sha256=sha, file=bad)
        assert columnar._verified_httpfs_path() is None, bad


def test_unsupported_platform_stays_in_memory(monkeypatch):
    monkeypatch.setattr(columnar, "_platform_arch", lambda: None)
    assert columnar._verified_httpfs_path() is None
    assert columnar.secure_crypto_available() is False


def test_default_filename_convention(tmp_path, monkeypatch):
    # When the pin's ``file`` is blank, the loader derives httpfs-<plat>-v<ver>.duckdb_extension.
    content = b"OO-FIXTURE-default-name"
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path / f"httpfs-linux_amd64-v{MINOR}.9.duckdb_extension").write_bytes(content)
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    _pin(monkeypatch, "linux_amd64", version=f"v{MINOR}.9", sha256=sha, file="")
    got = columnar._verified_httpfs_path()
    assert got is not None and got.endswith(f"httpfs-linux_amd64-v{MINOR}.9.duckdb_extension")


# --- CI-only real round trip: installs the real httpfs, checksums it IN-LANE (never the ----- #
#     registry), and exercises the encrypted persisted store. Local runs skip honestly.       #

def _ci_install_and_pin(monkeypatch, tmp_path) -> str:
    """CI-ONLY trust path: install httpfs over the network (CI lane), copy it, compute its
    sha256 IN-LANE, and inject that as the pin for THIS run only. The in-lane checksum is
    NEVER written into configs/external_artifacts.yml."""
    import shutil

    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs")  # network — CI lane only
    con.close()
    plat = columnar._platform_arch()
    src = (Path.home() / ".duckdb" / "extensions" / f"v{duckdb.__version__}"
           / plat / "httpfs.duckdb_extension")
    dst = tmp_path / f"httpfs-{plat}-v{duckdb.__version__}.duckdb_extension"
    shutil.copy(src, dst)
    sha = hashlib.sha256(dst.read_bytes()).hexdigest()
    monkeypatch.setenv("OO_COLUMNAR_EXT_DIR", str(tmp_path))
    monkeypatch.setattr(
        columnar, "_httpfs_pins",
        lambda: {plat: {"version": duckdb.__version__, "sha256": sha, "file": dst.name}},
    )
    return sha


@pytest.mark.skipif(
    os.getenv("OO_CI_INSTALL_HTTPFS") != "1",
    reason="CI-only httpfs lane (installs the real extension over the network); local skips honestly",
)
def test_ci_encrypted_persisted_round_trip(tmp_path, monkeypatch):
    _ci_install_and_pin(monkeypatch, tmp_path)
    # the verified binary now flips the gate on
    assert columnar._verified_httpfs_path() is not None
    assert columnar.secure_crypto_available() is True
    # the empirical encryption gate: sentinel-absent / no-key-fails / key-opens
    assert columnar.encryption_gate(tmp_path / "probe.duckdb", "s3-ci-passphrase") is True
    # a real persisted store opens encrypted and reports it honestly
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(tmp_path))
    st = columnar.status(passphrase="s3-ci-passphrase")
    assert st["mode"] == "persisted" and st["encrypted"] is True
    con = columnar.connect(passphrase="s3-ci-passphrase")
    assert con is not None
    con.close()
    # the on-disk store is ciphertext (the sentinel from the gate probe is never present raw)
    store = tmp_path / columnar._STORE_FILENAME
    if store.exists():
        assert columnar._SENTINEL.encode() not in store.read_bytes()
