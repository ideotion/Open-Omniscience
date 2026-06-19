"""Derived columnar engine bring-up + encryption gate (data-architecture Slice 4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The non-negotiables proven here: the engine is fully OFFLINE; it NEVER writes a
plaintext derived file; when a secure crypto backend isn't available offline it falls
back to in-memory (the brief's sanctioned hard-fallback); and the encryption gate
empirically distinguishes encrypted from not.
"""

from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")  # optional extra; tests skip without it

from src.analytics import columnar  # noqa: E402


@pytest.fixture()
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(tmp_path))
    monkeypatch.delenv("OO_COLUMNAR", raising=False)
    return tmp_path


def test_available_and_offline_config():
    assert columnar.duckdb_available() is True
    cfg = columnar._offline_config()
    assert cfg["autoload_known_extensions"] is False
    assert cfg["autoinstall_known_extensions"] is False
    assert cfg["enable_external_access"] is False


def test_connect_opens_offline_and_is_usable(store_dir):
    con = columnar.connect(passphrase="correct horse battery staple")
    assert con is not None
    # The engine works for real aggregation work (in-memory or persisted).
    con.execute("CREATE TABLE t (k VARCHAR, n INTEGER)")
    con.execute("INSERT INTO t VALUES ('a', 3), ('a', 1), ('b', 9)")
    rows = con.execute("SELECT k, SUM(n) FROM t GROUP BY k ORDER BY k").fetchall()
    assert rows == [("a", 4), ("b", 9)]
    con.close()


def test_disabled_returns_none_for_live_fallback(store_dir, monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR", "0")
    assert columnar.connect(passphrase="x") is None  # caller falls back to live query
    assert columnar.status("x")["mode"] == "unavailable"


def test_never_writes_a_plaintext_file_when_encryption_unavailable(store_dir):
    # When a SECURE crypto backend isn't available offline (the stock-wheel reality),
    # the engine MUST go in-memory and write NO file — never a plaintext derived store.
    if columnar.secure_crypto_available():
        pytest.skip("secure crypto backend present; the plaintext-avoidance path is the "
                    "encrypted persisted store, covered by the gate test")
    con = columnar.connect(passphrase="correct horse battery staple")
    con.execute("CREATE TABLE t (s VARCHAR)")
    con.execute("INSERT INTO t VALUES ('SECRET_CORPUS_DATA')")
    con.close()
    # No derived file at all (in-memory) -> certainly no plaintext on disk.
    files = list(store_dir.iterdir())
    assert files == [], f"expected no derived file on disk, found {files}"
    assert columnar.status("x")["mode"] == "memory"
    assert columnar.status("x")["encrypted"] is False


def test_gate_returns_false_when_secure_crypto_unavailable_and_cleans_up(store_dir):
    if columnar.secure_crypto_available():
        pytest.skip("secure crypto present -> the gate is exercised positively elsewhere")
    probe = store_dir / "probe.duckdb"
    assert columnar.encryption_gate(probe, "passphrase") is False  # no secure backend
    assert not probe.exists()  # cleaned up, no plaintext residue


def test_status_is_honest_never_claims_unproven_encryption(store_dir):
    st = columnar.status("a-passphrase")
    assert st["available"] is True
    # mode/encrypted must agree: encrypted iff persisted iff secure crypto present.
    assert st["encrypted"] == (st["mode"] == "persisted") == columnar.secure_crypto_available()


@pytest.mark.skipif(
    not columnar.secure_crypto_available(),
    reason="secure crypto (OpenSSL/httpfs) not available offline in this environment",
)
def test_encryption_gate_proves_real_encryption(store_dir):
    # Runs only where a secure backend is present (e.g. httpfs locally installed): the
    # three acceptance checks must all hold.
    assert columnar.encryption_gate(store_dir / "g.duckdb", "a strong passphrase") is True
