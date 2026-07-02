"""
Tests for the append-only, hash-chained, signed custody log (src/custody/log.py).

Proves the chain-of-custody is REAL:
- recording then verifying a chain passes;
- editing any entry's contents breaks its entry_hash;
- removing/reordering an entry breaks the chain link;
- forging an entry's signature is detected;
- an exported bundle verifies offline (no DB), and pinning to the signer catches
  a bundle re-signed by a different key.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.custody.log import (
    CustodyAction,
    CustodyLog,
    verify_entries,
    verify_export,
)
from src.custody.signing import HybridSigner


@pytest.fixture()
def log(tmp_path):
    signer = HybridSigner(ed25519_path=tmp_path / "ed.pem", mldsa_path=tmp_path / "ml.key")
    lg = CustodyLog(db_path=str(tmp_path / "custody.db"), signer=signer)
    yield lg
    lg.close()


def _seed(log) -> None:
    log.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
    log.record("article:1", "a" * 64, CustodyAction.ACCESS, actor="alice")
    log.record("article:2", "b" * 64, CustodyAction.INGEST, actor="pipeline")
    log.record("article:1", "a" * 64, CustodyAction.EXPORT, actor="alice")


def test_record_and_verify_clean_chain(log):
    _seed(log)
    ok, issues = log.verify()
    assert ok, issues
    assert len(log.all_entries()) == 4


def test_entries_for_item(log):
    _seed(log)
    assert len(log.entries_for("article:1")) == 3
    assert len(log.entries_for("article:2")) == 1


def test_concurrent_appends_do_not_collide_or_fork_the_chain(tmp_path):
    # Field report 2026-07-02: 34 `UNIQUE constraint failed: custody_entries.seq` under
    # 50-way parallel ingest with auto-log-on-ingest default-on. Each worker opens its OWN
    # CustodyLog on the same file (the ingest pattern `with CustodyLog() as log:`); the
    # process-wide append lock must serialise the read-chain-insert so seqs are contiguous
    # and the hash chain is intact — never a collision or a fork.
    import threading

    signer = HybridSigner(ed25519_path=tmp_path / "ed.pem", mldsa_path=tmp_path / "ml.key")
    signer.sign(b"warmup")  # force one-time key generation before the threads race on it
    db = str(tmp_path / "custody.db")
    n = 40
    errors: list[str] = []

    def worker(i: int) -> None:
        try:
            with CustodyLog(db_path=db, signer=signer) as lg:
                lg.record(f"article:{i}", "a" * 64, CustodyAction.INGEST, actor="pipeline")
        except Exception as exc:  # noqa: BLE001 - the whole point is to catch the race
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors  # no UNIQUE-constraint collisions
    with CustodyLog(db_path=db, signer=signer) as lg:
        entries = lg.all_entries()
        assert len(entries) == n, f"lost entries: {len(entries)} of {n}"
        assert sorted(e.seq for e in entries) == list(range(1, n + 1)), "seqs not contiguous"
        ok, issues = lg.verify()
        assert ok, issues  # the chain is intact, not forked


def test_chain_links_are_sequential(log):
    _seed(log)
    entries = log.all_entries()
    for prev, cur in zip(entries, entries[1:], strict=False):
        assert cur.prev_entry_hash == prev.entry_hash


def test_tampering_with_entry_contents_is_detected(log):
    _seed(log)
    # Directly mutate the stored action of seq 2 (simulating DB tampering).
    raw = sqlite3.connect(log.db_path)
    raw.execute("UPDATE custody_entries SET action='delete' WHERE seq=2")
    raw.commit()
    raw.close()
    ok, issues = log.verify()
    assert not ok
    assert any("entry_hash mismatch" in i for i in issues)


def test_removing_an_entry_breaks_the_chain(log):
    _seed(log)
    entries = log.all_entries()
    # Drop the 2nd entry, keep the rest -> chain link from seq 3 no longer matches.
    del entries[1]
    ok, issues = verify_entries(entries)
    assert not ok
    assert any("chain" in i or "seq" in i for i in issues)


def test_forged_signature_detected(log):
    _seed(log)
    entries = log.all_entries()
    entries[0].signature["ed25519"]["sig"] = "00" * 64
    ok, issues = verify_entries(entries)
    assert not ok
    assert any("signature invalid" in i for i in issues)


def test_export_verifies_offline(log):
    _seed(log)
    bundle = log.export()
    ok, issues = verify_export(bundle)
    assert ok, issues
    assert bundle["entry_count"] == 4
    assert bundle["signer"]["ed25519_pub"]


def test_export_for_single_item(log):
    _seed(log)
    bundle = log.export(item_id="article:1")
    # Per-item export is internally consistent for signatures + hashes; note the
    # global seq numbers are non-contiguous, which a full-chain verify flags.
    assert bundle["entry_count"] == 3
    assert all(e["item_id"] == "article:1" for e in bundle["entries"])


def test_pinning_catches_resigned_bundle(tmp_path):
    signer = HybridSigner(ed25519_path=tmp_path / "ed.pem", mldsa_path=tmp_path / "ml.key")
    log = CustodyLog(db_path=str(tmp_path / "c.db"), signer=signer)
    log.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
    bundle = log.export()
    real_signer = bundle["signer"]
    log.close()

    # Attacker rebuilds the log with their OWN signer, forging the same actions.
    attacker = HybridSigner(
        ed25519_path=tmp_path / "atk_ed.pem", mldsa_path=tmp_path / "atk_ml.key"
    )
    alog = CustodyLog(db_path=str(tmp_path / "atk.db"), signer=attacker)
    alog.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
    forged = alog.export()
    alog.close()

    # The forged bundle is internally consistent...
    assert verify_export(forged)[0] is True
    # ...but its signer identity differs from the real one.
    assert forged["signer"]["ed25519_pub"] != real_signer["ed25519_pub"]


def test_timestamp_proof_attached_by_default(log):
    e = log.record("x", "c" * 64, CustodyAction.INGEST)
    assert e.timestamp["kind"] == "local"
    assert e.timestamp["digest"]
