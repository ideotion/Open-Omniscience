"""The stop must never cost the user data (ruling R100, B2): a long write holds the single-writer gate when the stop begins.

A real child process opens the app's own store (the writer gate on), commits some rows, starts a second transaction on another thread
that writes many more rows and does not commit (the gate is held), then runs the REAL ``memstop.execute`` with the real shutdown
path (reap, dispose the pool, SIGTERM to self). The parent then opens the store the child left: ``quick_check`` is ok, the committed
rows are there, the uncommitted ones are not, and the -wal is folded back to a small size by the next open. The stop is allowed to
take its time (it waits for an exclusive window to close, bounded), and it never forces an exit."""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CHILD = textwrap.dedent(
    """
    import json, signal, sys, threading, time
    from sqlalchemy import text
    from src.database.session import SessionLocal, init_db
    from src.scheduler import memstop

    def graceful(signum, frame):
        # what the app's own handler does: leave through the normal interpreter exit (daemon threads end, no transaction commits)
        print("SIGTERM-HANDLED", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, graceful)
    memstop.EXCLUSIVE_WAIT_S = 3.0  # the production bound is 60 s; the test only needs it to be honoured

    init_db()
    s = SessionLocal()
    s.execute(text("CREATE TABLE memstop_probe (id INTEGER PRIMARY KEY, v TEXT)"))
    for i in range(50):
        s.execute(text("INSERT INTO memstop_probe (v) VALUES ('committed')"))
    s.commit()
    s.close()

    started = threading.Event()
    release = threading.Event()

    def long_write():
        w = SessionLocal()
        for i in range(5000):
            w.execute(text("INSERT INTO memstop_probe (v) VALUES ('in-flight')"))
        started.set()          # the transaction is open and the gate is held
        release.wait(120)      # never reached by the stop: SIGTERM ends the process first
        w.commit()

    threading.Thread(target=long_write, daemon=True).start()
    assert started.wait(30)
    from src.database.writer import write_gate
    held = write_gate.stats()
    print("GATE-HELD", held.get("held_for_s"), held.get("holder") is not None, flush=True)

    class Guard:
        def state(self):
            return {"reason": "only 48 MB of system memory available", "last_reading": {}}
        def last_release(self):
            return None

    rec = memstop.execute({"due": True, "samples": 200, "low_share": 1.0}, Guard())
    print("STOP-RETURNED", json.dumps(rec["steps"]), flush=True)
    print("IN-FLIGHT", json.dumps(rec["in_flight_at_start"]), flush=True)
    print("WAITED", json.dumps(rec["exclusive"]), flush=True)
    time.sleep(60)  # the shutdown thread ends the process; reaching the end of this sleep is a failure
    print("STOP-DID-NOT-END", flush=True)
    """
)


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM semantics differ")
def test_a_long_write_in_flight_is_rolled_back_cleanly_and_the_store_is_consistent(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    env = {**os.environ, "OO_DATA_DIR": str(data), "OO_DB_PLAINTEXT": "1", "PYTHONPATH": str(ROOT), "OO_NO_SCHEDULER": "1",
           "OO_SESSION_LIVENESS": "0"}
    env.pop("OO_DB_PASSPHRASE", None)
    proc = subprocess.run([sys.executable, "-c", CHILD], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=180, check=False)
    assert proc.returncode == 0 and "SIGTERM-HANDLED" in proc.stdout, (proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:])
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("IN-FLIGHT"))
    seen = json.loads(line.split(" ", 1)[1])
    assert seen["gate_held"] is True and seen["gate_held_for_s"] is not None, "the record says a write held the gate"
    waited = json.loads(next(ln for ln in proc.stdout.splitlines() if ln.startswith("WAITED")).split(" ", 1)[1])
    assert waited["waited_s"] >= 3.0 and waited["still_in_flight"]["gate_held"] is True, "bounded, and said to still be in flight"
    assert "GATE-HELD" in proc.stdout and "True" in proc.stdout.split("GATE-HELD", 1)[1].splitlines()[0], proc.stdout[-600:]
    assert "STOP-RETURNED" in proc.stdout and "STOP-DID-NOT-END" not in proc.stdout
    db = next(p for p in data.glob("*.db"))
    con = sqlite3.connect(str(db))
    try:
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        committed = con.execute("SELECT COUNT(*) FROM memstop_probe WHERE v='committed'").fetchone()[0]
        inflight = con.execute("SELECT COUNT(*) FROM memstop_probe WHERE v='in-flight'").fetchone()[0]
        assert committed == 50 and inflight == 0, (committed, inflight)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()
    wal = Path(str(db) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0, "no -wal growth is left behind"
    assert (data / "memory_stop.json").exists()
