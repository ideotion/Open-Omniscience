"""oo-volumes-2 streaming backup engine (src/backup/stream_backup.py) — P0.1.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the scale rework's guarantees AND its negative space (the #590 lesson —
skeptics must attack should-fail inputs, not only the happy path):

  * round trip: members stream into volumes and back, checksummed end to end;
  * NO whole-corpus materialization: the backup writes no plaintext corpus copy
    and no zip anywhere (asserted against the destination + temp trees);
  * incremental: an unchanged run re-emits only the (dated) envelope member; a
    SAME-LENGTH slice with different bytes always re-emits (checksum, never
    size/mtime); a passphrase change disables reuse entirely (never a mixed set);
  * resume: an interrupted run leaves NO final manifest (cannot be mistaken for
    a good backup; verify + restore refuse loudly), and the next run completes
    the set with every (member, slice) exactly once — then decrypts whole;
  * verify: names exactly the tampered/missing volume; a rewritten (re-hashed)
    manifest fails its Ed25519 signature; parity recovery still restores;
  * encrypted corpus member: converted with the corpus's own passphrase at
    restore; a wrong key fails loudly, never garbage;
  * janitor: stale orphaned staging is swept, a LIVE job's staging never is.
"""

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from src.backup.stream_backup import (
    BUILDING_NAME,
    CorpusSource,
    MemberFile,
    _no_freeze,
    active_staging,
    read_stream_backup,
    sweep_stale_backup_temps,
    verify_stream_backup,
    write_stream_backup,
)
from src.backup.volumes import MANIFEST_NAME, VolumeError, VolumeStopped, load_manifest

VOL = 65536  # small volumes so a tiny corpus spans many


def _make_corpus(path: Path, rows: int = 400) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);"
    )
    con.executemany(
        "INSERT INTO articles(hash, content) VALUES(?,?)",
        [(f"h{i:05d}", "x" * 3000) for i in range(rows)],
    )
    con.commit()
    con.close()


def _src(corpus: Path) -> CorpusSource:
    return CorpusSource(
        path=corpus, member_name="corpus.db", encrypted=False, freeze=_no_freeze
    )


def _members(tmp: Path) -> list[MemberFile]:
    a = tmp / "app_settings.json"
    a.write_text('{"k": 1}')
    b = tmp / "empty.log"
    b.write_text("")
    return [
        MemberFile("app_settings.json", "state", a),
        MemberFile("logs/empty.log", "logs", b),
    ]


def _backup(tmp: Path, dest: Path, corpus: Path, pw: str = "pw", **kw):
    return write_stream_backup(
        dest, pw, corpus_source=_src(corpus), side_members=_members(tmp),
        volume_size=VOL, **kw,
    )


# --------------------------------------------------------------------------- #
# Round trip + no-materialization
# --------------------------------------------------------------------------- #
def test_round_trip_and_no_corpus_materialization(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    s = _backup(tmp_path, dest, corpus)
    assert s["volumes_emitted"] == s["volumes"] and s["volumes_reused"] == 0
    assert s["corpus_encrypted"] is False

    # NO whole-corpus materialization: nothing at the destination beyond the
    # volume set (no zip, no corpus copy, no leftover temp trees).
    names = sorted(p.name for p in dest.iterdir())
    assert all(
        n == MANIFEST_NAME or n.endswith((".ooenc", ".oopar")) for n in names
    ), names

    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.signature_state == "verified"
    assert staged.hash_failures == []
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()
    assert (staged.staging_dir / "app_settings.json").read_text() == '{"k": 1}'
    assert (staged.staging_dir / "logs/empty.log").read_text() == ""  # 0-byte member
    assert staged.encrypted is True
    # the envelope's corpus facts were computed (real table counts, no score)
    assert staged.manifest["corpus"]["tables"]["articles"] == 400
    assert staged.manifest["corpus"]["articles_commitment"]["n"] == 400


def test_verify_clean_set_reports_ok_and_crosschecks_envelope(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)

    shallow = verify_stream_backup(dest)
    assert shallow["ok"] is True and shallow["signature"] == "verified"
    assert shallow["decrypted"] is False  # no passphrase -> nothing decrypted

    deep = verify_stream_backup(dest, passphrase="pw")
    assert deep["ok"] is True and deep["decrypted"] is True
    assert deep["envelope_signature"] == "verified"
    assert deep["envelope_mismatches"] == []


# --------------------------------------------------------------------------- #
# Incremental (Z2)
# --------------------------------------------------------------------------- #
def test_unchanged_rerun_reuses_every_volume_but_the_envelope(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    s1 = _backup(tmp_path, dest, corpus)
    s2 = _backup(tmp_path, dest, corpus)
    # at most the manifest.json member (dated, signed) re-emits — 0 when both
    # runs land in the same second (identical envelope = legitimate reuse)
    assert s2["volumes_emitted"] <= 1
    assert s2["volumes_reused"] == s1["volumes"] - s2["volumes_emitted"]
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


def test_same_length_byte_change_is_detected_by_checksum_never_size_mtime(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)

    data = bytearray(corpus.read_bytes())
    hit = VOL * 2 + 17  # inside slice #2
    data[hit] ^= 0xFF
    corpus.write_bytes(bytes(data))  # SAME length
    # freeze mtime back so a size/mtime shortcut would wrongly skip it
    os.utime(corpus, (time.time() - 86400, time.time() - 86400))

    s = _backup(tmp_path, dest, corpus)
    assert s["volumes_emitted"] == 2  # exactly: the changed slice + the envelope
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == bytes(data)


def test_new_passphrase_disables_reuse_and_the_set_stays_single_key(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    s1 = _backup(tmp_path, dest, corpus, pw="old-pw")
    s2 = _backup(tmp_path, dest, corpus, pw="new-pw")
    assert s2["volumes_reused"] == 0  # nothing reused across passphrases — ever
    assert s2["volumes_emitted"] == s1["volumes"]
    assert any("DIFFERENT passphrase" in n for n in s2["notes"])
    # the finished set decrypts wholly with the NEW passphrase (no mixed volumes)
    deep = verify_stream_backup(dest, passphrase="new-pw")
    assert deep["ok"] is True and deep["decrypted"] is True
    with pytest.raises(Exception):  # noqa: B017 - old passphrase must fail loudly
        read_stream_backup(dest, "old-pw", staging_root=tmp_path / "st")


def test_shrunk_member_garbage_collects_superseded_volumes(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus, rows=400)
    dest = tmp_path / "dest"
    s1 = _backup(tmp_path, dest, corpus)
    corpus.unlink()
    _make_corpus(corpus, rows=40)  # much smaller -> fewer slices
    s2 = _backup(tmp_path, dest, corpus)
    assert s2["volumes"] < s1["volumes"]
    assert s2["orphans_removed"] > 0
    on_disk = {p.name for p in dest.glob("*.ooenc")}
    referenced = {v["name"] for v in load_manifest(dest)["volumes"]}
    assert on_disk == referenced  # nothing superseded left behind


# --------------------------------------------------------------------------- #
# Interrupt + resume (Z3)
# --------------------------------------------------------------------------- #
def _interrupt_after(n: int):
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > n

    return stop


def test_interrupted_backup_cannot_be_mistaken_for_complete_and_resumes(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    with pytest.raises(VolumeStopped):
        _backup(tmp_path, dest, corpus, should_stop=_interrupt_after(4))

    # a partial set has NO final manifest: verify + restore refuse loudly
    assert not (dest / MANIFEST_NAME).exists()
    assert (dest / BUILDING_NAME).exists()
    with pytest.raises(VolumeError):
        verify_stream_backup(dest)
    with pytest.raises(VolumeError):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")

    s = _backup(tmp_path, dest, corpus)  # resume
    assert s["resumed"] is True
    assert s["volumes_reused"] >= 4  # the interrupted run's finished volumes
    assert (dest / BUILDING_NAME).exists() is False
    # every (member, slice) exactly once — no double-emit, no skip
    vols = load_manifest(dest)["volumes"]
    keys = [(v["member"], v["slice"]) for v in vols]
    assert len(keys) == len(set(keys))
    for name, group in {
        m["name"]: [v for v in vols if v["member"] == m["name"]]
        for m in load_manifest(dest)["members"]
    }.items():
        assert sorted(v["slice"] for v in group) == list(range(len(group))), name
    # the resumed archive decrypts and checksums WHOLE
    deep = verify_stream_backup(dest, passphrase="pw")
    assert deep["ok"] is True and deep["decrypted"] is True
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st2")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


def test_resume_after_source_changed_mid_gap_yields_one_consistent_state(tmp_path):
    """The database changing BETWEEN the interrupt and the resume must never
    yield a mixed-state archive: the resume re-hashes every slice against the
    CURRENT bytes, so the final set equals the current corpus exactly."""
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    with pytest.raises(VolumeStopped):
        _backup(tmp_path, dest, corpus, should_stop=_interrupt_after(4))

    con = sqlite3.connect(corpus)  # mutate between interrupt and resume
    con.execute("UPDATE articles SET content = 'CHANGED' WHERE id <= 50")
    con.commit()
    con.execute("VACUUM")
    con.commit()
    con.close()

    _backup(tmp_path, dest, corpus)
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


def test_interrupted_refresh_keeps_the_previous_backup_restorable(tmp_path):
    """Crash-safe refresh: an incremental run that dies mid-corpus must leave
    the PREVIOUS complete backup fully verifiable and restorable (emitted
    volumes use run-unique names; the manifest swap is atomic; superseded
    volumes are garbage-collected only after finalize)."""
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    old_bytes = corpus.read_bytes()

    data = bytearray(old_bytes)
    for off in range(VOL, len(data), VOL):  # change every slice
        data[off + 3] ^= 0xFF
    corpus.write_bytes(bytes(data))
    with pytest.raises(VolumeStopped):
        _backup(tmp_path, dest, corpus, should_stop=_interrupt_after(3))

    # the previous set is still complete: verify ok, restore yields the OLD state
    report = verify_stream_backup(dest)
    assert report["ok"] is True, report["problems"]
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st-old")
    assert staged.corpus_path.read_bytes() == old_bytes

    s = _backup(tmp_path, dest, corpus)  # resume completes the refresh
    assert s["resumed"] is True
    staged2 = read_stream_backup(dest, "pw", staging_root=tmp_path / "st-new")
    assert staged2.corpus_path.read_bytes() == bytes(data)


def test_cancelled_refresh_cleanup_spares_the_previous_complete_set(tmp_path):
    from src.backup.stream_backup import cleanup_cancelled_build

    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    old_bytes = corpus.read_bytes()

    data = bytearray(old_bytes)
    data[VOL + 5] ^= 0xFF
    corpus.write_bytes(bytes(data))
    with pytest.raises(VolumeStopped):
        _backup(tmp_path, dest, corpus, should_stop=_interrupt_after(2))

    removed = cleanup_cancelled_build(dest)  # the manager's cancel path
    assert removed >= 0
    assert not (dest / BUILDING_NAME).exists()
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == old_bytes  # previous backup intact


def test_cancelled_first_build_vanishes_entirely(tmp_path):
    from src.backup.stream_backup import cleanup_cancelled_build

    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    with pytest.raises(VolumeStopped):
        _backup(tmp_path, dest, corpus, should_stop=_interrupt_after(3))
    cleanup_cancelled_build(dest)
    assert list(dest.glob("*.ooenc")) == []
    assert not (dest / MANIFEST_NAME).exists()
    assert not (dest / BUILDING_NAME).exists()


# --------------------------------------------------------------------------- #
# Tamper + corruption (verify, Z3)
# --------------------------------------------------------------------------- #
def test_verify_names_the_tampered_volume_and_restore_refuses(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus, parity_fraction=0.0)
    for p in dest.glob("*.oopar"):
        p.unlink()  # ensure no parity net for this case

    victim = sorted(dest.glob("vol-*.ooenc"))[2]
    raw = bytearray(victim.read_bytes())
    raw[500] ^= 0x01
    victim.write_bytes(bytes(raw))  # same length

    report = verify_stream_backup(dest)
    assert report["ok"] is False
    assert victim.name in report["bad_volumes"]
    with pytest.raises(VolumeError) as exc:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert victim.name in str(exc.value)


def test_parity_recovers_a_corrupt_volume_end_to_end(tmp_path):
    pytest.importorskip("numpy")
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus, parity_fraction=0.2)
    victim = sorted(dest.glob("vol-*.ooenc"))[1]
    victim.write_bytes(victim.read_bytes()[:-10])

    report = verify_stream_backup(dest)
    assert report["ok"] is False and report["recoverable"] is True
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


def test_rewritten_manifest_fails_its_signature(tmp_path):
    """An attacker who consistently rewrites volumes.json (hashes AND files)
    cannot re-sign it — verify and restore both refuse."""
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)

    m = load_manifest(dest)
    m["volumes"][0]["sha256"] = "0" * 64  # forge an entry, keep the signature
    (dest / MANIFEST_NAME).write_text(json.dumps(m, indent=1), encoding="utf-8")

    report = verify_stream_backup(dest)
    assert report["signature"] == "bad-signature"
    assert report["ok"] is False
    with pytest.raises(VolumeError, match="signature"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")


def test_unsigned_manifest_is_not_ok(tmp_path):
    """A finalize interrupted between manifest write and signing must read as
    NOT ok (re-run the backup), never as a verified set."""
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    m = load_manifest(dest)
    m.pop("signature", None)
    (dest / MANIFEST_NAME).write_text(json.dumps(m, indent=1), encoding="utf-8")
    report = verify_stream_backup(dest)
    assert report["ok"] is False and report["signature"] == "unsigned"


def test_traversal_member_names_in_a_self_signed_manifest_are_refused(tmp_path):
    """A signature only proves internal consistency with the EMBEDDED key —
    anyone can self-sign a manifest. A member or volume name that points outside
    the staging/set directory must refuse BEFORE any filesystem write."""
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)

    from src.backup.stream_backup import _sign_manifest

    m = load_manifest(dest)
    m["members"][0]["name"] = "../../escape.json"  # traversal member
    m.pop("signature", None)
    m["signature"] = _sign_manifest(m)  # consistently re-signed (attacker's power)
    (dest / MANIFEST_NAME).write_text(json.dumps(m, indent=1), encoding="utf-8")

    with pytest.raises(VolumeError, match="unsafe member path"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    with pytest.raises(VolumeError, match="unsafe member path"):
        verify_stream_backup(dest)
    assert not (tmp_path / "escape.json").exists()

    m = load_manifest(dest)
    m["members"][0]["name"] = "app_settings.json"  # restore a sane member name
    m["volumes"][0]["name"] = "../outside.ooenc"  # traversal VOLUME name
    m.pop("signature", None)
    m["signature"] = _sign_manifest(m)
    (dest / MANIFEST_NAME).write_text(json.dumps(m, indent=1), encoding="utf-8")
    with pytest.raises(VolumeError, match="unsafe volume file name"):
        verify_stream_backup(dest)
    with pytest.raises(VolumeError, match="unsafe volume file name"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st2")


def test_wrong_backup_passphrase_fails_loudly(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    with pytest.raises(Exception):  # noqa: B017 - EncryptionError, loud
        read_stream_backup(dest, "WRONG", staging_root=tmp_path / "st")
    deep = verify_stream_backup(dest, passphrase="WRONG")
    assert deep["ok"] is False
    assert any("passphrase" in p for p in deep["problems"])


# --------------------------------------------------------------------------- #
# Encrypted corpus member (SQLCipher) + WAL carry
# --------------------------------------------------------------------------- #
def _sqlcipher_available() -> bool:
    try:
        import sqlcipher3  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _sqlcipher_available(), reason="sqlcipher3 not installed")
def test_legacy_plaintext_download_refuses_an_encrypted_store(tmp_path, monkeypatch):
    """Z1's last reachable decrypt-the-world: GET /api/database/backup exported
    an ENCRYPTED corpus into a plaintext temp file. backup_to now refuses loudly
    for an encrypted store, pointing at the streaming encrypted backup; a
    plaintext store keeps the page-copy behavior."""
    import src.backup.sqlite_backup as sb
    from src.database.connect import connect

    enc = tmp_path / "enc.db"
    con = connect(enc, key="k")
    con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    monkeypatch.setattr(sb, "live_db_path", lambda: enc)
    with pytest.raises(sb.BackupError, match="never decrypts the corpus"):
        sb.backup_to(tmp_path / "out.db")
    assert not (tmp_path / "out.db").exists()  # nothing plaintext was written

    plain = tmp_path / "plain.db"
    sqlite3.connect(plain).execute("CREATE TABLE articles(id INTEGER PRIMARY KEY)").close()
    monkeypatch.setattr(sb, "live_db_path", lambda: plain)
    out = sb.backup_to(tmp_path / "out2.db")
    assert out.exists()  # the plaintext-store path is unchanged


@pytest.mark.skipif(not _sqlcipher_available(), reason="sqlcipher3 not installed")
def test_encrypted_corpus_member_converts_with_its_own_passphrase(tmp_path):
    from src.database.connect import connect

    corpus = tmp_path / "corpus.db"
    con = connect(corpus, key="corpus-secret")
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT, content TEXT);"
    )
    con.executemany(
        "INSERT INTO articles(hash, content) VALUES(?,?)",
        [(f"h{i}", "y" * 2000) for i in range(200)],
    )
    con.commit()
    con.close()
    assert corpus.read_bytes()[:16] != b"SQLite format 3\x00"

    src = CorpusSource(
        path=corpus, member_name="corpus.db.sqlcipher", encrypted=True,
        freeze=_no_freeze, facts_key="corpus-secret",
    )
    dest = tmp_path / "dest"
    s = write_stream_backup(
        dest, "backup-pw", corpus_source=src, side_members=[], volume_size=VOL
    )
    assert s["corpus_encrypted"] is True
    # the destination never holds plaintext SQLite bytes anywhere
    for p in dest.iterdir():
        assert p.read_bytes()[:16] != b"SQLite format 3\x00", p.name

    staged = read_stream_backup(
        dest, "backup-pw", staging_root=tmp_path / "st", corpus_passphrase="corpus-secret"
    )
    assert staged.signature_state == "verified" and staged.hash_failures == []
    assert staged.corpus_path.name == "corpus.db"
    assert staged.corpus_path.read_bytes()[:16] == b"SQLite format 3\x00"
    c = sqlite3.connect(staged.corpus_path)
    assert c.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 200
    c.close()
    # the encrypted member was verified then reclaimed (staging disk, not doubled)
    assert not (staged.staging_dir / "corpus.db.sqlcipher").exists()

    with pytest.raises(VolumeError, match="corpus_passphrase"):
        read_stream_backup(
            dest, "backup-pw", staging_root=tmp_path / "st2", corpus_passphrase="WRONG"
        )


def test_residual_wal_is_carried_and_folded_at_restore(tmp_path):
    from contextlib import contextmanager

    corpus = tmp_path / "corpus.db"
    con = sqlite3.connect(corpus)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT, content TEXT);"
    )
    con.commit()
    con.executemany(
        "INSERT INTO articles(hash, content) VALUES(?,?)",
        [(f"h{i}", "z" * 1000) for i in range(300)],
    )
    con.commit()
    con.close()  # closing checkpoints; re-open and write WITHOUT checkpointing
    con = sqlite3.connect(corpus)
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.executemany(
        "INSERT INTO articles(hash, content) VALUES(?,?)",
        [(f"w{i}", "w" * 1000) for i in range(50)],
    )
    con.commit()
    wal = corpus.with_name(corpus.name + "-wal")
    assert wal.exists() and wal.stat().st_size > 0

    @contextmanager
    def freeze_with_wal():
        yield wal  # simulate: checkpoint could not drain (a long reader)

    src = CorpusSource(
        path=corpus, member_name="corpus.db", encrypted=False, freeze=freeze_with_wal
    )
    dest = tmp_path / "dest"
    s = write_stream_backup(dest, "pw", corpus_source=src, side_members=[], volume_size=VOL)
    con.close()
    assert any("WAL" in n for n in s["notes"])

    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.hash_failures == []
    c = sqlite3.connect(staged.corpus_path)
    assert c.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 350  # wal folded
    c.close()
    assert not (staged.staging_dir / "corpus.db-wal").exists()


# --------------------------------------------------------------------------- #
# Janitor (Z4)
# --------------------------------------------------------------------------- #
def test_janitor_sweeps_stale_spares_fresh_and_live(tmp_path):
    old = time.time() - 48 * 3600
    stale_dir = tmp_path / ".bak-build-dead01"
    stale_dir.mkdir()
    (stale_dir / "corpus.db").write_text("leaked plaintext")
    os.utime(stale_dir / "corpus.db", (old, old))
    os.utime(stale_dir, (old, old))

    stale_part = tmp_path / "vol-x-00001.ooenc.oopart"
    stale_part.write_text("partial")
    os.utime(stale_part, (old, old))

    fresh_dir = tmp_path / ".restore-fresh01"
    fresh_dir.mkdir()  # mtime = now

    live_dir = tmp_path / ".bak-build-live01"
    live_dir.mkdir()
    (live_dir / "f").write_text("x")
    os.utime(live_dir / "f", (old, old))
    os.utime(live_dir, (old, old))  # old, but registered as a LIVE job

    keep_manifest = tmp_path / "volumes.json"
    keep_manifest.write_text("{}")
    keep_building = tmp_path / BUILDING_NAME
    keep_building.write_text("{}")  # the resume log is never swept
    os.utime(keep_building, (old, old))
    keep_vol = tmp_path / "vol-x-00001.ooenc"
    keep_vol.write_text("v")
    os.utime(keep_vol, (old, old))

    with active_staging(live_dir):
        removed = sweep_stale_backup_temps(tmp_path)
    assert removed == 2
    assert not stale_dir.exists() and not stale_part.exists()
    assert fresh_dir.exists() and live_dir.exists()
    assert keep_manifest.exists() and keep_building.exists() and keep_vol.exists()


def test_janitor_age_guards_on_the_newest_file_inside_a_staging_dir(tmp_path):
    """A dir whose own mtime is old but that a job is WRITING INTO (fresh files
    inside) must never be swept — the registry is the belt, this is the braces."""
    old = time.time() - 48 * 3600
    d = tmp_path / ".bak-build-writing"
    d.mkdir()
    (d / "being-written.oopart").write_text("x")  # fresh mtime
    os.utime(d, (old, old))
    assert sweep_stale_backup_temps(tmp_path) == 0
    assert d.exists()


def test_cleanup_stale_staging_covers_bak_build_and_ooparts(tmp_path, monkeypatch):
    import src.backup.artifact as artifact_mod

    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr(artifact_mod, "data_dir", lambda: tmp_path)
    old = time.time() - 48 * 3600
    for name in (".restore-x", ".bak-build-y"):
        d = tmp_path / name
        d.mkdir()
        os.utime(d, (old, old))
    f = tmp_path / "a.oopart"
    f.write_text("x")
    os.utime(f, (old, old))
    assert artifact_mod.cleanup_stale_staging() == 3
