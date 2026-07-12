"""DB-9: adaptive backup-volume sizing (S3.3) — keep N+M under the GF(2^8) parity ceiling.

Two layers:
  * ARITHMETIC — _adaptive_volume_size at simulated 1 GiB..50 TiB corpus sizes (no real TB
    needed): N+M < 255 at every scale, byte-identical (512 MiB) below ~100 GB, and the
    safety guard grows the size when a higher parity_fraction would breach the margin.
  * END-TO-END TORTURE — real backups on the adaptive path (a small monkeypatched floor so a
    tiny corpus exercises real slicing): below-floor is byte-identical + no note; above-floor
    records the adaptive size + N+M < 255 + round-trips + parity recovers; a size-TIER CROSSING
    re-emits all volumes with an honest note; and an INTERRUPTED tier-crossing refresh leaves
    the PREVIOUS complete backup fully restorable (the crash-safe guarantee under a size change).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import math
import sqlite3
from pathlib import Path

import pytest

from src.backup import stream_backup
from src.backup.stream_backup import (
    _NM_SAFETY_MARGIN,
    BUILDING_NAME,
    CorpusSource,
    MemberFile,
    _adaptive_volume_size,
    _no_freeze,
    read_stream_backup,
    verify_stream_backup,
    write_stream_backup,
)
from src.backup.volumes import (
    VOLUME_SIZE_DEFAULT,
    VolumeStopped,
    load_manifest,
)

GiB = 1024 ** 3
MiB = 1024 * 1024


_RESERVE = 2  # the manifest.json (+ a possible residual WAL) members the sizer reserves for


def _members_for(total: int, n_side: int = 20, side_bytes: int = 10_000) -> list[int]:
    """A realistic member profile: one big corpus member + n_side small side files (each of
    which slices into its OWN volume — the per-member count the sizer must account for)."""
    return [total, *([side_bytes] * n_side)]


def _real_nm(sizes: list[int], v: int, frac: float) -> tuple[int, int]:
    """The REAL emitted N (per-member ceil SUM + the reserved manifest/WAL members) and M —
    computed exactly the way the engine + write_parity do, NOT ceil(total/size)."""
    n = sum(max(1, math.ceil(s / v)) for s in sizes if s > 0) + _RESERVE
    m = max(1, math.ceil(frac * n))
    return n, m


def _nm(total: int, frac: float = 0.1, n_side: int = 20) -> tuple[int, int, int]:
    sizes = _members_for(total, n_side)
    v = _adaptive_volume_size(sizes, frac)
    n, m = _real_nm(sizes, v, frac)
    return v, n, m


# --------------------------------- arithmetic ------------------------------------------ #

@pytest.mark.parametrize("gib", [1, 10, 50, 99, 100, 128, 512, 1024, 5 * 1024, 50 * 1024])
def test_nm_stays_under_the_gf256_ceiling_at_every_scale(gib):
    total = gib * GiB
    _v, n, m = _nm(total)
    assert n + m < 256, f"{gib} GiB -> N+M={n + m} breaches the GF(2^8) ceiling"
    assert n + m <= _NM_SAFETY_MARGIN, f"{gib} GiB -> N+M={n + m} over the safety margin"


def test_byte_identical_512mib_at_or_below_100gib():
    # 200 * 512 MiB == 100 GiB exactly: at or below it the floor wins -> unchanged behaviour.
    for gib in (1, 10, 99, 100):
        assert _adaptive_volume_size([gib * GiB], 0.1) == VOLUME_SIZE_DEFAULT, gib
    # above it the size grows so N stays bounded
    assert _adaptive_volume_size([128 * GiB], 0.1) > VOLUME_SIZE_DEFAULT


def test_data_volume_count_stays_near_target_at_tb_scale():
    for gib in (1024, 5 * 1024):  # 1 TB, 5 TB
        _v, n, _m = _nm(gib * GiB, n_side=0)  # corpus-only, so N is the corpus-volume count
        assert 150 <= n <= 210, f"{gib} GiB -> N={n} drifted far from ~200"


def test_high_parity_fraction_grows_the_volume_size():
    # parity_fraction 0.4 at 100 GiB would be N=200,M=80 => N+M=280 > margin: the guard grows
    # the size until N+M <= the margin.
    total = 100 * GiB
    v, n, m = _nm(total, frac=0.4)
    assert n + m <= _NM_SAFETY_MARGIN
    assert v > VOLUME_SIZE_DEFAULT  # it had to grow beyond the floor


def test_env_target_override(monkeypatch):
    monkeypatch.setenv("OO_BACKUP_TARGET_VOLUMES", "50")
    _v, n, _m = _nm(1024 * GiB, n_side=0)  # 1 TB, target 50 -> bigger volumes, fewer
    assert n <= 55
    monkeypatch.setenv("OO_BACKUP_TARGET_VOLUMES", "not-an-int")  # bad value -> default 200
    _v2, n2, _ = _nm(1024 * GiB, n_side=0)
    assert 150 <= n2 <= 210


def test_empty_and_tiny_corpora_are_safe():
    assert _adaptive_volume_size([], 0.1) == VOLUME_SIZE_DEFAULT
    assert _adaptive_volume_size([0], 0.1) == VOLUME_SIZE_DEFAULT
    assert _adaptive_volume_size([1], 0.1) == VOLUME_SIZE_DEFAULT


def test_member_count_gap_is_accounted_at_scale():
    """The skeptic's finding: the engine slices EACH member independently, so the real volume
    count is the per-member ceil SUM (+ the reserved manifest/WAL members), NOT ceil(total/
    size). With many side members OR a high parity_fraction the REAL N+M must still stay under
    the GF(2^8) ceiling — the sizer grows the volume size to guarantee it."""
    for n_side in (0, 30, 60):
        for frac in (0.1, 0.4):
            for gib in (128, 1024, 5 * 1024):
                v, n, m = _nm(gib * GiB, frac=frac, n_side=n_side)
                assert n + m < 256, f"{gib}GiB frac={frac} members={n_side} -> N+M={n + m}"
                assert n + m <= _NM_SAFETY_MARGIN


# --------------------------------- end-to-end torture ---------------------------------- #

def _make_corpus(path: Path, rows: int) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);"
    )
    con.executemany(
        "INSERT INTO articles(hash, content) VALUES(?,?)",
        [(f"h{i:06d}", "x" * 3000) for i in range(rows)],
    )
    con.commit()
    con.close()


def _src(corpus: Path) -> CorpusSource:
    return CorpusSource(path=corpus, member_name="corpus.db", encrypted=False, freeze=_no_freeze)


def _adaptive_backup(dest: Path, corpus: Path, pw: str = "pw", **kw):
    # NOTE: no volume_size -> the DB-9 adaptive path is engaged.
    return write_stream_backup(dest, pw, corpus_source=_src(corpus), side_members=[], **kw)


def test_below_floor_is_byte_identical_and_unannotated(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus, rows=100)  # ~0.5 MB, far below 100 GiB
    dest = tmp_path / "dest"
    s = _adaptive_backup(dest, corpus)
    assert load_manifest(dest)["volume_size"] == VOLUME_SIZE_DEFAULT
    assert not any("adaptive volume sizing" in n for n in s["notes"])
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


def test_above_floor_adaptive_slices_records_size_and_roundtrips(tmp_path, monkeypatch):
    # shrink the floor + target so a small corpus exercises the ABOVE-floor adaptive path.
    monkeypatch.setattr(stream_backup, "VOLUME_SIZE_DEFAULT", 4096)
    monkeypatch.setenv("OO_BACKUP_TARGET_VOLUMES", "8")
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus, rows=20)  # ~60 KB -> ceil(60KB/8) > 4096 -> adaptive kicks in
    dest = tmp_path / "dest"
    s = _adaptive_backup(dest, corpus, parity_fraction=0.1)

    m = load_manifest(dest)
    expected = stream_backup._adaptive_volume_size([corpus.stat().st_size], 0.1)
    assert m["volume_size"] == expected > 4096, (m["volume_size"], expected)
    assert any("adaptive volume sizing" in n for n in s["notes"])
    # N + M under the ceiling
    n = len(m["volumes"])
    mm = (m.get("parity") or {}).get("count", 0)
    assert n + mm < 256
    # verify + round-trip
    assert verify_stream_backup(dest, passphrase="pw")["ok"] is True
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


def test_parity_recovers_a_corrupt_volume_on_the_adaptive_path(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    monkeypatch.setattr(stream_backup, "VOLUME_SIZE_DEFAULT", 4096)
    monkeypatch.setenv("OO_BACKUP_TARGET_VOLUMES", "8")
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus, rows=20)
    dest = tmp_path / "dest"
    _adaptive_backup(dest, corpus, parity_fraction=0.3)
    victim = sorted(dest.glob("vol-*.ooenc"))[1]
    victim.write_bytes(victim.read_bytes()[:-8])  # corrupt it
    assert verify_stream_backup(dest)["recoverable"] is True
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


def test_explicit_volume_size_bypasses_adaptive(tmp_path):
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus, rows=50)
    dest = tmp_path / "dest"
    s = write_stream_backup(dest, "pw", corpus_source=_src(corpus), side_members=[],
                            volume_size=65536)
    assert load_manifest(dest)["volume_size"] == 65536  # honoured exactly
    assert not any("adaptive volume sizing" in n for n in s["notes"])


def test_size_tier_crossing_reemits_all_and_notes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(stream_backup, "VOLUME_SIZE_DEFAULT", 4096)
    monkeypatch.setenv("OO_BACKUP_TARGET_VOLUMES", "8")
    corpus = tmp_path / "corpus.db"
    dest = tmp_path / "dest"

    _make_corpus(corpus, rows=3)  # tiny -> below the 4096 floor
    _adaptive_backup(dest, corpus)
    assert load_manifest(dest)["volume_size"] == 4096

    corpus.unlink()
    _make_corpus(corpus, rows=25)  # bigger -> ceil/8 > 4096 -> a size tier crossing
    s2 = _adaptive_backup(dest, corpus)
    m2 = load_manifest(dest)
    assert m2["volume_size"] > 4096
    assert any("crossed a size tier" in n for n in s2["notes"])
    assert s2["volumes_reused"] == 0, "a size change re-emits every volume (offsets moved)"
    # the completed new set round-trips at the new size, superseded old volumes gc'd
    assert s2["orphans_removed"] > 0
    on_disk = {p.name for p in dest.glob("*.ooenc")}
    referenced = {v["name"] for v in m2["volumes"]}
    assert on_disk == referenced
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


def _interrupt_after(n: int):
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > n

    return stop


def test_interrupted_tier_crossing_keeps_the_previous_backup_restorable(tmp_path, monkeypatch):
    """The crash-safe finalize under a SIZE CHANGE: an incremental refresh that crosses a
    size tier and dies mid-corpus must leave the PREVIOUS complete backup (at the old size)
    fully verifiable and restorable — run-unique volume names + atomic manifest swap + gc
    only after finalize guarantee it even when every volume re-emits at a new size."""
    monkeypatch.setattr(stream_backup, "VOLUME_SIZE_DEFAULT", 4096)
    monkeypatch.setenv("OO_BACKUP_TARGET_VOLUMES", "8")
    corpus = tmp_path / "corpus.db"
    dest = tmp_path / "dest"

    _make_corpus(corpus, rows=3)  # complete backup at the 4096 floor
    _adaptive_backup(dest, corpus)
    old_bytes = corpus.read_bytes()
    old_vsize = load_manifest(dest)["volume_size"]
    assert old_vsize == 4096

    corpus.unlink()
    _make_corpus(corpus, rows=25)  # cross the tier, then interrupt the refresh
    with pytest.raises(VolumeStopped):
        _adaptive_backup(dest, corpus, should_stop=_interrupt_after(2))

    # the previous COMPLETE backup is untouched: still at the old size, verifies, restores OLD
    m = load_manifest(dest)
    assert m["volume_size"] == old_vsize
    assert verify_stream_backup(dest)["ok"] is True
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st-old")
    assert staged.corpus_path.read_bytes() == old_bytes

    # resuming completes the refresh at the NEW size, yielding the new corpus
    s = _adaptive_backup(dest, corpus)
    assert s["resumed"] is True
    assert load_manifest(dest)["volume_size"] > old_vsize
    staged2 = read_stream_backup(dest, "pw", staging_root=tmp_path / "st-new")
    assert staged2.corpus_path.read_bytes() == corpus.read_bytes()
    assert not (dest / BUILDING_NAME).exists()


def test_adaptive_accounts_for_members_end_to_end(tmp_path, monkeypatch):
    """Regression for the member-count gap, end to end: several side members must not push the
    REAL emitted N+M past the ceiling. The sizer grows the volume size so the ACTUAL manifest
    volume + parity count respects the (here monkeypatched-tiny) safety margin, and the backup
    completes + round-trips instead of write_parity aborting. The pre-fix sizer (which sized
    against ceil(total/size), ignoring the per-member split) would over-emit and breach it."""
    monkeypatch.setattr(stream_backup, "VOLUME_SIZE_DEFAULT", 4096)
    monkeypatch.setattr(stream_backup, "_NM_SAFETY_MARGIN", 12)  # tiny ceiling to force the guard
    monkeypatch.setenv("OO_BACKUP_TARGET_VOLUMES", "16")
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus, rows=40)
    side = []
    for i in range(6):  # six side members, each its own volume
        p = tmp_path / f"m{i}.json"
        p.write_text("y" * 800, encoding="utf-8")
        side.append(MemberFile(f"m{i}.json", "state", p))
    dest = tmp_path / "dest"
    s = write_stream_backup(dest, "pw", corpus_source=_src(corpus), side_members=side,
                            parity_fraction=0.1)
    m = load_manifest(dest)
    n = len(m["volumes"])
    mm = (m.get("parity") or {}).get("count", 0)
    assert n + mm <= 12, f"real emitted N+M={n + mm} exceeded the safety margin"
    assert any("adaptive volume sizing" in note for note in s["notes"])
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()
