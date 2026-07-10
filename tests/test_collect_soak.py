"""
The collect soak harness (P0.3 acceptance instrument) — smoke tier.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Runs a TINY soak in a SUBPROCESS (its own OO_DATA_DIR — never the shared test
store) with ``socket.socket`` REPLACED BY A TRAP, so "zero network" is proven
by construction, not asserted by hope: any code path that so much as creates a
socket crashes the run. The long-tier soak (many passes, real sizes) is
operator-run via ``python -m src.testing.collect_soak`` — this pins the
harness's contract: it runs, measures, proves the guard pauses-not-dies, and
opens no socket.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# Trap every socket creation BEFORE anything else imports. sqlite/psutil/the
# synthetic session need no sockets, so a single trip = a real network leak.
_NO_SOCKET_BOOT = """
import socket
class _TrapSocket(socket.socket):  # a CLASS: ssl subclasses socket.socket at import
    def __init__(self, *a, **k):
        raise AssertionError("a socket was opened during the zero-network soak")
def _trap(*a, **k):
    raise AssertionError("a socket was opened during the zero-network soak")
socket.socket = _TrapSocket
socket.create_connection = _trap
socket.getaddrinfo = _trap
import sys
from src.testing.collect_soak import main
sys.exit(main(sys.argv[1:]))
"""


def test_soak_smoke_runs_measures_and_opens_no_socket(tmp_path):
    env = {
        **os.environ,
        "OO_DATA_DIR": str(tmp_path / "soak-data"),
        "OO_DB_PLAINTEXT": "1",
        "OO_NO_SCHEDULER": "1",
        "OO_AIRPLANE_SOCKET_GUARD": "0",  # the socket TRAP above is stricter
    }
    proc = subprocess.run(
        [sys.executable, "-c", _NO_SOCKET_BOOT,
         "--passes", "2", "--sources", "5", "--items", "3", "--fresh", "2",
         "--body-kb", "2", "--parallelism", "2", "--trip-guard-after-pass", "1"],
        capture_output=True, text=True, timeout=600, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    kinds = {d["kind"] for d in lines}
    assert {"pass", "guard-proof", "summary"} <= kinds

    passes = [d for d in lines if d["kind"] == "pass"]
    assert len(passes) == 2
    assert passes[0]["articles_stored"] > 0
    # Every measured field is a real number (or an honest None), never fabricated.
    for p in passes:
        assert p["gate_delta"]["grants"] >= 0
        assert p["rss_mb_after_hygiene"] is None or p["rss_mb_after_hygiene"] > 0

    proof = next(d for d in lines if d["kind"] == "guard-proof")
    assert proof["paused_not_died"] is True
    assert proof["recycled"] == "memory"
    assert proof["deferred"] > 0

    summary = next(d for d in lines if d["kind"] == "summary")
    assert summary["network"]["sockets_opened"] == 0
    assert summary["rss_flatness"]["method"]


def test_soak_refuses_to_run_without_an_explicit_data_dir():
    env = {k: v for k, v in os.environ.items() if k != "OO_DATA_DIR"}
    proc = subprocess.run(
        [sys.executable, "-m", "src.testing.collect_soak", "--passes", "1"],
        capture_output=True, text=True, timeout=120, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert proc.returncode == 2
    assert "refusing" in proc.stderr


def test_soak_refuses_an_existing_corpus(tmp_path):
    """OO_DATA_DIR is a production variable: a live install could point it at
    a real corpus. The soak seeds synthetic sources, so it refuses any data
    dir that already holds a database (skeptic-hardened)."""
    (tmp_path / "open_omniscience.db").write_bytes(b"not empty")
    env = {**os.environ, "OO_DATA_DIR": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-m", "src.testing.collect_soak", "--passes", "1"],
        capture_output=True, text=True, timeout=120, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert proc.returncode == 2
    assert "existing corpus" in proc.stderr
