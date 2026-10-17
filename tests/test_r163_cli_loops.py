"""R163: a loop that a CLI or subprocess entry reaches on the main thread keeps its back-edge inside the lock or the ``finally`` around it.

CPython 3.13 leaves the ``JUMP_BACKWARD`` of a loop outside the exception-table entry of the ``with``/``try`` around it in some shapes (a ``while <cond>:``;
a ``for`` whose body ends in a bare ``if``), so an interrupt delivered there skips the release or the cleanup (src/utils/interrupts.py, "THE LOOP FORM IS
PART OF THE GUARANTEE"; tests/test_gates_survive_an_interrupt.py). The rows are RC2's reach table for the unowned files
(/mnt/project-files/fix-source-qualification/main-thread-reach-q-608e334ae-2026-10-17.md); each names the head lines of the loops it converted, so
writing the old form back brings the head back into the scan and fails the row.

The two files that move user data also carry a behaviour test: the conversion changes where a loop lives, never what it computes.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads

_CONVERTED = (
    ("src/analytics/reindex_parallel.py", "_pool_context", {'for method in ("forkserver", "spawn"):'}),
    ("src/database/damage.py", "_start_recheck", {"for key in recheck:"}),
    ("src/database/damage.py", "incident_after_last_check", {"for inc in self._incidents:"}),
    ("src/database/damage.py", "notes", {"for key, st in self._files.items():"}),
    ("src/database/pool_watch.py", "register", {"for k in [k for k, (ref, _l) in _POOL_LABELS.items() if ref() is None]:"}),
    ("src/backup/parity.py", "write_parity", {"for j in range(m):"}),
    ("src/backup/parity.py", "recover_volumes", {"for k in erased_data:"}),
    ("src/database/encrypt_tool.py", "encrypt_database", {'for suffix in ("-wal", "-shm"):'}),
    ("src/testing/scale_bench.py", "wal_bench", {"for i in range(writes):"}),
    ("scripts/signal_leak_probe.py", "_run_gate", {"iterations += 1", "sc.lock.release()"}),
    ("scripts/ui_clickthrough_run.py", "investigate_state_b", {'for surface_id in ("home_leads",):'}),
    ("scripts/ui_clickthrough_run.py", "investigate_state_d_import", {"page.wait_for_timeout(1500)"}),
    ("scripts/ui_clickthrough_run.py", "investigate_state_c", {"for locale in LOCALES_TO_CHECK:"}),
)


@pytest.mark.parametrize(("relpath", "funcname", "heads"), _CONVERTED, ids=[f"{r.rsplit('/', 1)[-1]}::{f}" for r, f, _h in _CONVERTED])
def test_the_converted_loop_keeps_its_back_edge_inside_the_lock_or_finally(relpath, funcname, heads):
    left = _uncovered_loop_heads(relpath, funcname) & heads
    assert not left, f"{relpath}::{funcname}: a loop's back-edge is outside the with/try that covers its head: {sorted(left)}"


def test_the_scan_sees_the_shapes_it_is_looking_for(tmp_path):
    """The measurement the rows rest on, pinned on a file of its own: the old shapes are reported, the converted ones are not."""
    src = tmp_path / "shapes.py"
    src.write_text(
        "def old_for(xs, f):\n    try:\n        for x in xs:\n            if f(x):\n                f(1)\n    finally:\n        f(0)\n"
        "def new_for(xs, f):\n    try:\n        for x in xs:\n            if not f(x):\n                continue\n            f(1)\n    finally:\n        f(0)\n"
        "def old_while(f):\n    try:\n        while f():\n            f(1)\n    finally:\n        f(0)\n"
        "def new_while(f):\n    try:\n        while True:\n            if not f():\n                break\n            f(1)\n    finally:\n        f(0)\n",
        encoding="utf-8",
    )
    rel = str(src)  # absolute: Path(root) / absolute is the absolute path
    assert _uncovered_loop_heads(rel, "old_for") == {"for x in xs:"}
    assert _uncovered_loop_heads(rel, "old_while") == {"f(1)"}
    assert not _uncovered_loop_heads(rel, "new_for")
    assert not _uncovered_loop_heads(rel, "new_while")


# --- behaviour: parity ------------------------------------------------------------------------------------------------------------------------


def _reference_parity(volumes: list[bytes], count: int) -> list[bytes]:
    """The parity the module's own generator matrix and field tables define, computed byte by byte over the whole stripe, with no bands."""
    from src.backup.parity import _cauchy, _mul_table

    stripe = max(len(v) for v in volumes)
    n = len(volumes)
    g = _cauchy(count, n)
    mul = _mul_table()
    out = []
    for j in range(count):
        row = bytearray(stripe)
        for k, vol in enumerate(volumes):
            coef = g[j][k]
            if not coef:
                continue
            table = mul[coef]
            for i, byte in enumerate(vol):
                row[i] ^= int(table[byte])
        out.append(bytes(row))
    return out


def _volume_set(tmp: Path) -> Path:
    from src.backup.volumes import write_volume_set

    src = tmp / "payload.bin"
    src.write_bytes(bytes((i * 131 + 7) % 256 for i in range(4096 * 3 + 777)))
    dest = tmp / "set"
    write_volume_set(src, dest, "pw", volume_size=4096, chunk_size=1024)
    return dest


def test_write_parity_still_writes_the_parity_the_generator_defines(tmp_path):
    pytest.importorskip("numpy")
    from src.backup.parity import write_parity

    dest = _volume_set(tmp_path)
    volumes = [p.read_bytes() for p in sorted(dest.glob("vol-*.ooenc"))]
    write_parity(dest, parity_count=2, band_bytes=333)  # bands that do not divide the stripe: the last one is short
    got = [p.read_bytes() for p in sorted(dest.glob("par-*.oopar"))]
    assert got == _reference_parity(volumes, 2)


def test_recover_volumes_still_rebuilds_two_lost_volumes_byte_for_byte(tmp_path):
    pytest.importorskip("numpy")
    from src.backup.parity import recover_volumes, write_parity
    from src.backup.volumes import load_manifest

    dest = _volume_set(tmp_path)
    write_parity(dest, parity_count=2, band_bytes=333)
    manifest = load_manifest(dest)
    victims = [dest / manifest["volumes"][0]["name"], dest / manifest["volumes"][2]["name"]]
    good = {v: v.read_bytes() for v in victims}
    for v in victims:
        v.write_bytes(b"\x00" * len(good[v]))  # lost: same length, wrong bytes
    assert recover_volumes(manifest, [v.name for v in victims], out_dir=dest, band_bytes=333) == []
    for v in victims:
        assert hashlib.sha256(v.read_bytes()).hexdigest() == hashlib.sha256(good[v]).hexdigest()
        assert v.read_bytes() == good[v]


# --- behaviour: encrypt_database --------------------------------------------------------------------------------------------------------------


def test_encrypt_database_still_clears_both_stale_journals_and_keeps_every_row(tmp_path):
    from src.database.connect import connect, is_encrypted_file
    from src.database.encrypt_tool import encrypt_database

    db = tmp_path / "corpus.db"
    raw = sqlite3.connect(str(db))
    raw.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, t TEXT)")
    raw.executemany("INSERT INTO articles(t) VALUES (?)", [("a",), ("b",), ("c",)])
    raw.commit()
    raw.close()
    wal, shm = db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")
    wal.write_bytes(b"stale")
    shm.write_bytes(b"stale")

    rep = encrypt_database(db, "tool-pw-123")

    assert rep["encrypted"] is True
    assert is_encrypted_file(db) is True
    assert not wal.exists() and not shm.exists()  # the loop's job
    conn = connect(db, key="tool-pw-123")
    try:
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone() == (3,)
    finally:
        conn.close()


def test_encrypt_database_does_not_fail_when_only_one_journal_exists(tmp_path):
    from src.database.encrypt_tool import encrypt_database

    db = tmp_path / "corpus.db"
    raw = sqlite3.connect(str(db))
    raw.execute("CREATE TABLE t(x)")
    raw.execute("INSERT INTO t VALUES (1)")
    raw.commit()
    raw.close()
    shm = db.with_name(db.name + "-shm")
    shm.write_bytes(b"stale")
    assert encrypt_database(db, "tool-pw-123")["encrypted"] is True
    assert not shm.exists()
