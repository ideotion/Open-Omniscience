"""
Row 334 (R734/R736): the secure-uninstall watcher's audit log names no path and no process id.

Before this row the log read, for example, ``uninstall watcher start (pid 41234)`` and ``removed launcher
/home/<name>/.local/share/applications/open-omniscience.desktop``: the server's pid and the full paths of the launchers, the
venv, the data folder, the columnar store and the app folder, the home folder (and so the user's name) in each. A path is now
written as its role (``<data>``, ``<home>/.../<file name>``, ``.../<file name>``), and a path it cannot read as
``<path withheld>``, never as given.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.js_source_helper import python_function_source


def _run(tmp_path, plan: dict, home) -> tuple[str, int]:
    from src.safety.uninstall import _WATCHER_SRC

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    subprocess.run([sys.executable, "-c", _WATCHER_SRC, str(dead.pid), json.dumps(plan)], timeout=60, check=True, env=env)
    return (tmp_path / "audit.log").read_text(encoding="utf-8"), dead.pid


def test_the_audit_log_names_no_path_and_no_process_id(tmp_path):
    home = tmp_path / "home" / "jane.doe"
    home.mkdir(parents=True)
    apps = home / ".local" / "share" / "applications"
    apps.mkdir(parents=True)
    launcher = apps / "open-omniscience.desktop"
    launcher.write_text("[Desktop Entry]\n", encoding="utf-8")
    stuck = apps / "open-omniscience-stuck.desktop"          # a directory: os.remove fails, and str(e) names the path
    stuck.mkdir()
    (stuck / "x").write_text("x", encoding="utf-8")
    venv = home / "oo" / ".venv"
    venv.mkdir(parents=True)
    data = home / "oo-data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    store = tmp_path / "elsewhere" / "columnar"
    store.mkdir(parents=True)
    (store / "analytics.duckdb").write_bytes(b"D" * 8192)
    app = home / "oo" / "app"
    app.mkdir()
    plan = {
        "files": [str(launcher), str(stuck)], "venv": str(venv), "app_folder": str(app),
        "wipe_data_dir": str(data), "wipe_store_dir": str(store), "audit_log": str(tmp_path / "audit.log"),
    }
    text, pid = _run(tmp_path, plan, home)

    # the lines that leaked before this row
    assert "uninstall watcher start\n" in text, text
    assert f"pid {pid}" not in text and "(pid" not in text, text
    assert "removed launcher <home>/.../open-omniscience.desktop" in text, text
    assert "launcher kept <home>/.../open-omniscience-stuck.desktop (" in text, text
    assert "wiped data <data> (" in text, text
    assert "wiped columnar store .../columnar (" in text, text
    assert "removed venv <home>/.../.venv" in text, text
    assert "removed app folder <home>/.../app" in text, text
    # and nothing else does
    for leak in (str(tmp_path), "jane.doe", str(home), str(store)):
        assert leak not in text, (leak, text)


def test_a_path_it_cannot_read_is_withheld_never_written_as_given():
    from src.safety.uninstall import _WATCHER_SRC

    ns: dict = {"os": os, "plan": {"wipe_data_dir": "/srv/oo-data"}}
    exec(python_function_source(_WATCHER_SRC, "tok"), ns)  # noqa: S102 - the watcher's own helper, from the repository
    tok = ns["tok"]
    assert tok(12345) == "<path withheld>"
    assert tok(object()) == "<path withheld>"
    assert tok("/") == "<path withheld>"
    assert tok("/srv/oo-data") == "<data>"
    assert tok("/srv/oo-data/keys/db.key") == "<data>/.../db.key"
    assert tok("/opt/other/thing") == ".../thing"
    # a sibling whose name starts like the data folder is not inside it
    assert tok("/srv/oo-data-old/x") == ".../x"
