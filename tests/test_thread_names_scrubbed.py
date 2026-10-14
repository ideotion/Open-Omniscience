"""A thread's name can hold a passphrase (it is named from a request); no record or log line carries it raw."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

MARKER = "horse-battery-staple-91"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def held(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", MARKER)


def test_thread_snapshot_names_carry_no_held_passphrase(held):
    from src.monitoring import session_hwm

    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name=f"oo-dump-{MARKER}", daemon=True)
    t.start()
    try:
        snap = session_hwm.thread_snapshot()
    finally:
        stop.set()
        t.join(2)
    names = [e["name"] for e in snap]
    assert any(n.startswith("oo-dump-") for n in names), names  # the thread was seen
    assert MARKER not in json.dumps(snap)


def test_session_forensics_member_nets_an_older_snapshot_that_kept_the_name(held, monkeypatch):
    from src.api.diagnostics import bundle

    old = {"previous_session_peaks": {"threads": [{"name": f"served-cache-{MARKER}", "stack": ["f"]}]}}
    monkeypatch.setattr(bundle, "session_forensics_report", lambda download=False: old)
    member = bundle._session_forensics_member()
    text = json.dumps(member)
    assert "served-cache-" in text
    assert MARKER not in text


# The sites that write the calling thread's name into a file or a log line, each through scrubbed_name.
_FILES = (
    "src/database/damage.py",
    "src/database/writer.py",
    "src/database/maintenance.py",
    "src/monitoring/session_hwm.py",
)
#: The gate keeps its holder's name in memory; every line and member that PUBLISHES it scrubs it (the two tests above and
#: below, and the contention member's net).
_IN_MEMORY_ONLY = {"self._holder = threading.current_thread().name"}
_RAW = re.compile(r"(?<!scrubbed_name\()(?:threading\.current_thread\(\)|\bthread)\.name\b")


@pytest.mark.parametrize("rel", _FILES)
def test_no_raw_thread_name_reaches_a_record_or_a_log_in(rel):
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    raw = [
        f"{rel}:{n}: {line.strip()}"
        for n, line in enumerate(lines, 1)
        if _RAW.search(line) and not line.lstrip().startswith("#") and line.strip() not in _IN_MEMORY_ONLY
    ]
    assert not raw, raw


def test_the_write_gate_holder_lines_are_scrubbed():
    text = (ROOT / "src/database/writer.py").read_text(encoding="utf-8")
    assert text.count("scrubbed_name(holder)") >= 2
