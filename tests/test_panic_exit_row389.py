"""R813 row 389: a panic result that keeps the key to a data drive's data in memory (connections pinned on a drive found absent,
unidentified or changed) ends the app by itself, so the key leaves memory without waiting for the operator.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.safety import data_volume

S7 = "The key to the data on that drive stays in this app’s memory until the app is closed: close the app now."
S7_COST = "The key to the data on that drive stays in this app’s memory until the app is closed."
S8 = "The app is closing itself now, so that the key leaves its memory. Open the app again to go on."


def test_exit_after_panic_arms_the_graceful_stop_then_the_hard_one():
    from src.safety import panic as shutdown

    armed: list[float] = []
    ended: list[bool] = []
    shutdown.exit_after_panic(delay=0.01, hard_after=0.05, _arm=armed.append, _exit=lambda: ended.append(True))
    assert armed == [0.01], "the graceful stop (the power button's) comes first"
    deadline = time.monotonic() + 5
    while not ended and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ended == [True], "a process still running after the graceful stop's time ends anyway"


def test_exit_after_panic_never_raises_when_the_graceful_stop_cannot_be_armed():
    from src.safety import panic as shutdown

    ended: list[bool] = []

    def _boom(_delay):
        raise RuntimeError("no")

    shutdown.exit_after_panic(delay=0.0, hard_after=0.01, _arm=_boom, _exit=lambda: ended.append(True))
    deadline = time.monotonic() + 5
    while not ended and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ended == [True]


@pytest.mark.parametrize("kept", [True, False])
def test_the_endpoint_closes_the_app_only_when_the_key_stays_in_memory(monkeypatch, kept):
    import src.safety as safety_pkg
    from src.api import safety as api_safety
    from src.safety import panic as shutdown

    armed: list[bool] = []
    s7 = S7.replace("’", "'")  # the report's English record uses a plain apostrophe; the page, a typographic one
    monkeypatch.setattr(safety_pkg, "panic_wipe", lambda confirm: {"drive_key_in_memory": kept, "limit": "S1. " + s7})
    monkeypatch.setattr(shutdown, "exit_after_panic", lambda: armed.append(True))
    out = api_safety.panic(api_safety.PanicBody(confirm=True))
    if kept:
        assert armed == [True] and out["app_closing"] is True and out["limit"] == "S1. " + S7_COST.replace("’", "'") + " " + S8, out["limit"]
    else:
        assert armed == [] and "app_closing" not in out and out["limit"] == "S1. " + s7


def test_the_page_says_the_app_is_closing():
    js = Path("src/static/app-backup.js").read_text(encoding="utf-8")
    assert "r.app_closing === true" in js and S8 in js and S7_COST in js and S7 in js
    from src.api.safety import APP_CLOSING_SENTENCE

    assert APP_CLOSING_SENTENCE == S8


_CHILD = r"""
import json, os, sys, time
from pathlib import Path
data = Path(os.environ["OO_DATA_DIR"])
from sqlalchemy import text
from src.database import session
with session.engine.begin() as c:  # a store on the drive, its connection back in the pool and open
    c.execute(text("create table if not exists t(a)"))
    c.execute(text("insert into t values(1)"))
(data / ".oos-volume").write_text("{not json", encoding="utf-8")  # the drive can no longer be identified
from src.api import safety
rep = safety.panic(safety.PanicBody(confirm=True))
print("REPORT " + json.dumps({k: rep.get(k) for k in ("drive_absent", "drive_unidentified", "drive_key_in_memory", "app_closing")}))
sys.stdout.flush()
time.sleep(120)  # the app ends itself well before this
print("STILL RUNNING")
"""


@pytest.mark.skipif(os.name == "nt", reason="the graceful stop is SIGTERM to self here; Windows raises SIGINT, covered by the unit tests")
def test_the_real_panic_ends_the_process_by_itself(tmp_path):
    data = tmp_path / "drive" / "OOS data"
    data.mkdir(parents=True)
    (data / data_volume.MARKER_NAME).write_text(json.dumps({"id": "a1b2c3d4e5f60718"}), encoding="utf-8")
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "DATABASE_URL"))}
    env.update({"OO_DATA_DIR": str(data), data_volume.ENV_ID: "a1b2c3d4e5f60718", "OO_DB_PLAINTEXT": "1",
                "OO_NO_SCHEDULER": "1", "OO_AUTOSEED": "0", "OO_LLM_AUTOSTART": "0", "OO_STORAGE_GUARD": "0",
                "PYTHONPATH": os.getcwd(), "HOME": str(tmp_path / "home")})
    started = time.monotonic()
    run = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=110, cwd=os.getcwd())
    took = time.monotonic() - started
    assert "STILL RUNNING" not in run.stdout, run.stdout[-2000:] + run.stderr[-2000:]
    line = next(ln for ln in run.stdout.splitlines() if ln.startswith("REPORT "))
    report = json.loads(line.removeprefix("REPORT "))
    assert report == {"drive_absent": True, "drive_unidentified": True, "drive_key_in_memory": True, "app_closing": True}, report
    assert run.returncode != 0 and took < 100, (run.returncode, took)
    assert (data / "open_omniscience.db").exists(), "nothing on the drive was erased"

