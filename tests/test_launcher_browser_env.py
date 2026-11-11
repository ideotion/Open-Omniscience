"""The launchers open the browser without the passphrases the server holds.

A scripted start can set ``OO_DB_PASSPHRASE`` (or ``OO_KEY_PASSPHRASE``) in the environment of
``scripts/launch.sh`` or ``scripts/launch.cmd``. The server needs it; the browser does not. A browser
the launcher starts inherits the launcher's environment, and would keep the passphrase in its own
(``/proc/<pid>/environ``, a crash report) for as long as it runs, long after the app has stopped.
The server already drops both names for the children it starts (``model_store.child_env``,
``tests/test_child_env_passphrase.py``); this is the same rule for the one child the launchers
start besides the server.

No test here writes a value to a file: the fake browser and the fake server record only WHETHER
each name was in their environment, and the value is a fixed dummy, never a real passphrase.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.monitoring.secret_scrub import HELD_ENV_VARS
from tests.js_source_helper import ps_function_body

REPO = Path(__file__).resolve().parents[1]
LAUNCH_SH = REPO / "scripts" / "launch.sh"
LAUNCH_CMD = REPO / "scripts" / "launch.cmd"

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="runs the bash launcher")

DUMMY = "dummy-value-for-a-test"
CONTROL = "OO_TEST_CONTROL_VAR"
# handed to the fake programs in their environment, never written into them (see _presence_recorder)
RECORDED_NAMES = " ".join((*HELD_ENV_VARS, CONTROL))


def _exe(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _presence_recorder(out_var: str) -> str:
    """A fake program that writes one line per name: ``NAME set`` or ``NAME unset``. Never a value.

    The names come from ``OO_TEST_NAMES`` at run time rather than being written into the script,
    so the script file holds no passphrase-named string (CodeQL reads one written to a file as
    clear-text storage of a secret, py/clear-text-storage-sensitive-data)."""
    return (
        "#!/bin/sh\n"
        "for n in $OO_TEST_NAMES; do\n"
        '  eval "v=\\${$n+x}"\n'
        f'  if [ -n "$v" ]; then echo "$n set"; else echo "$n unset"; fi >> "${out_var}"\n'
        "done\n"
    )


def _read_presence(path: Path) -> dict[str, str]:
    rows = [ln.split() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return dict(rows)


# --------------------------------------------------------------------------- #
#  The lists the launchers clear are the server's list
# --------------------------------------------------------------------------- #


def test_launch_sh_drops_exactly_the_servers_held_names():
    text = LAUNCH_SH.read_text(encoding="utf-8")
    m = re.search(r'^OO_HELD_ENV_VARS="([^"]*)"$', text, re.M)
    assert m, "launch.sh names the held variables in one place"
    assert tuple(m.group(1).split()) == HELD_ENV_VARS
    # a command started with a literal `env -u` list (the terminal panel's) drops exactly these too
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.lstrip().startswith("#") or not re.search(r"\benv\s+-u\s", ln):
            continue
        assert tuple(re.findall(r"-u\s+(\w+)", ln)) == HELD_ENV_VARS, f"launch.sh:{i}: {ln.strip()}"


def test_launch_sh_starts_every_browser_opener_through_env_minus_u():
    text = LAUNCH_SH.read_text(encoding="utf-8")
    body = re.search(r"^open_browser\(\) \{\n(.*?)^\}", text, re.M | re.S)
    assert body, "launch.sh has one open_browser function"
    openers = [
        ln for ln in body.group(1).splitlines() if 'xdg-open "$1"' in ln or 'open "$1"' in ln
    ]
    assert len(openers) == 2, openers
    for ln in openers:
        assert 'env "${_drop[@]}" ' in ln, f"a browser opener inherits the held names: {ln.strip()}"
    # nothing else in the launcher starts a browser
    for i, ln in enumerate(text.splitlines(), 1):
        if ln in openers or ln.lstrip().startswith("#"):
            continue
        # an opener in command position: at the start of a statement, after a separator, or
        # after a keyword or wrapper that runs it; prose like "will open at" is not one
        if re.search(
            r"(^\s*|[;&|({`!]\s*|\b(if|elif|while|until|then|else|do|time|sudo|exec|command|nohup|setsid|env)\s+(?:[A-Za-z_]\w*=\S*\s+)*)"
            r"(xdg-open|open|gio\s+open|kde-open\d*|sensible-browser|x-www-browser|www-browser"
            r"|\"?\$\{?BROWSER\b)(?=[\s\"'}]|$)",
            ln,
        ):
            pytest.fail(f"launch.sh:{i} opens something outside open_browser: {ln.strip()}")


def _cmd_lines() -> list[str]:
    return [ln.strip() for ln in LAUNCH_CMD.read_text(encoding="utf-8").splitlines()]


def test_launch_cmd_clears_the_held_names_right_before_every_start():
    lines = _cmd_lines()
    starts = [i for i, ln in enumerate(lines) if ln.lower().startswith('start ""')]
    assert len(starts) == 2, "the already-running opener and the waiting PowerShell"
    # any other way of handing an address to the shell would bypass the clears below
    for i, ln in enumerate(lines):
        low = ln.lower()
        if low.startswith("rem") or i in starts:
            continue
        # the terminal panel is no longer started here (R658): launch_server.ps1 starts it in this
        # window, without the held names (test_launch_server_starts_the_panel_..._held_names below)
        # the whole line, a PowerShell -Command script included
        assert not re.search(
            r"\b(start|explorer|rundll32|start-process|startfile|shellexecute)\b", low
        ), f"launch.cmd line {i + 1} may open something outside the two cleared starts: {ln}"
    # the outer setlocal is what gives the names back to the window that ran the launcher
    first_code = next(
        ln.lower() for ln in lines if ln and not ln.lower().startswith(("@echo", "rem"))
    )
    assert first_code == "setlocal"
    for i in starts:
        before = [ln for ln in lines[:i] if ln and not ln.lower().startswith("rem")]
        cleared = before[-len(HELD_ENV_VARS) :]
        assert cleared == [f'set "{n}="' for n in HELD_ENV_VARS], (
            f"launch.cmd line {i + 1} starts a process that inherits the held names"
        )


def test_launch_cmd_gives_the_names_back_to_the_server():
    """The waiting PowerShell's clear is undone by its own endlocal before the server starts:
    the server is the one process that needs the passphrase."""
    lines = _cmd_lines()
    low = [ln.lower() for ln in lines]
    wait_start = next(i for i, ln in enumerate(low) if ln.startswith('start "" /min powershell'))
    opened = max(i for i in range(wait_start) if low[i] == "setlocal")
    closed = next(i for i in range(wait_start, len(low)) if low[i] == "endlocal")
    assert closed == wait_start + 1
    assert all(f'set "{n}="' in lines[opened:wait_start] for n in HELD_ENV_VARS)
    server = [
        i for i, ln in enumerate(lines) if ln in ('"%APP%"',) or 'launch_server.ps1" -App' in ln
    ]
    assert server and all(i > closed for i in server)
    # and nothing between the endlocal and the server clears a name again, except inside a nested
    # setlocal that its own endlocal closes before the server
    depth = 0
    for ln in lines[closed + 1 : max(server)]:
        depth += {"setlocal": 1, "endlocal": -1}.get(ln.lower(), 0)
        assert depth >= 0
        if any(ln == f'set "{n}="' for n in HELD_ENV_VARS):
            assert depth > 0, f"launch.cmd clears a held name for the server: {ln}"
    assert depth == 0, "every nested setlocal is closed before the server starts"


# --------------------------------------------------------------------------- #
#  open_browser, run on its own: both openers, and a readonly variable
# --------------------------------------------------------------------------- #


def _open_browser_source() -> str:
    text = LAUNCH_SH.read_text(encoding="utf-8")
    held = re.search(r'^OO_HELD_ENV_VARS="[^"]*"$', text, re.M)
    fn = re.search(r"^open_browser\(\) \{\n.*?^\}\n", text, re.M | re.S)
    assert held and fn
    return held.group(0) + "\n" + fn.group(0)


def _run_open_browser(tmp_path: Path, opener: str, prelude: str = "") -> dict[str, str]:
    fake = tmp_path / "bin"
    fake.mkdir()
    out = tmp_path / "presence.txt"
    _exe(fake / opener, _presence_recorder("OO_TEST_OUT"))
    env_bin = shutil.which("env")
    assert env_bin
    (fake / "env").symlink_to(env_bin)
    script = (
        "set -euo pipefail\n"
        + prelude
        + _open_browser_source()
        + 'open_browser "http://127.0.0.1:8000/"\n'
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("OO_")}
    # PATH holds the fake opener and env alone, so the other opener is genuinely absent
    env.update(dict.fromkeys(HELD_ENV_VARS, DUMMY), PATH=str(fake), OO_TEST_OUT=str(out))
    env[CONTROL] = "1"
    env["OO_TEST_NAMES"] = RECORDED_NAMES
    bash = shutil.which("bash")
    assert bash
    subprocess.run([bash, "-c", script], env=env, check=True, timeout=30)
    return _read_presence(out)


@posix_only
@pytest.mark.parametrize("opener", ["xdg-open", "open"])
def test_each_opener_starts_without_the_held_names(tmp_path, opener):
    got = _run_open_browser(tmp_path, opener)
    assert got[CONTROL] == "set", "the control: the opener does see the rest of the environment"
    assert {n: got[n] for n in HELD_ENV_VARS} == dict.fromkeys(HELD_ENV_VARS, "unset")


@posix_only
def test_a_readonly_passphrase_still_stays_out_and_the_browser_still_opens(tmp_path):
    got = _run_open_browser(tmp_path, "xdg-open", prelude=f"readonly {HELD_ENV_VARS[0]}\n")
    assert got[CONTROL] == "set"
    assert all(got[n] == "unset" for n in HELD_ENV_VARS)


# --------------------------------------------------------------------------- #
#  The whole launcher, run for real against fake commands
# --------------------------------------------------------------------------- #


def _launcher_tree(tmp_path: Path, *, already_running: bool) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "oo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(LAUNCH_SH, root / "scripts" / "launch.sh")
    (root / "pyproject.toml").write_text("[project]\nname = 'fake'\n", encoding="utf-8")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "activate").write_text("", encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    _exe(
        fake / "open-omniscience", _presence_recorder("OO_TEST_SERVER_OUT") + "sleep 0.3\nexit 0\n"
    )
    if already_running:
        _exe(fake / "curl", "#!/usr/bin/env bash\nexit 0\n")
    else:
        # the first curl is "is one already running?" and fails; the health wait then succeeds
        _exe(
            fake / "curl",
            '#!/usr/bin/env bash\nf="$OO_TEST_CURLCOUNT"\nn=$(cat "$f" 2>/dev/null || echo 0)\n'
            'echo $((n + 1)) > "$f"\n[ "$n" -ge 1 ]\n',
        )
    _exe(fake / "xdg-open", _presence_recorder("OO_TEST_BROWSER_OUT"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "XDG_DATA_HOME"))}
    env.update(
        dict.fromkeys(HELD_ENV_VARS, DUMMY),
        PATH=f"{fake}{os.pathsep}{os.environ['PATH']}",
        HOME=str(tmp_path / "home"),
        OO_TEST_CURLCOUNT=str(tmp_path / "curl.count"),
        OO_TEST_SERVER_OUT=str(tmp_path / "server.txt"),
        OO_TEST_BROWSER_OUT=str(tmp_path / "browser.txt"),
    )
    env[CONTROL] = "1"
    env["OO_TEST_NAMES"] = RECORDED_NAMES
    return root, env


@posix_only
def test_the_launcher_hands_the_server_the_passphrase_and_the_browser_none(tmp_path):
    root, env = _launcher_tree(tmp_path, already_running=False)
    proc = subprocess.run(
        ["bash", str(root / "scripts" / "launch.sh")],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    server = _read_presence(tmp_path / "server.txt")
    browser = _read_presence(tmp_path / "browser.txt")
    assert all(server[n] == "set" for n in HELD_ENV_VARS), "the control: the server still gets them"
    assert browser[CONTROL] == "set"
    assert all(browser[n] == "unset" for n in HELD_ENV_VARS)
    assert DUMMY not in proc.stdout + proc.stderr


@posix_only
def test_the_already_running_branch_opens_the_browser_without_the_passphrase(tmp_path):
    root, env = _launcher_tree(tmp_path, already_running=True)
    proc = subprocess.run(
        ["bash", str(root / "scripts" / "launch.sh")],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "already running" in proc.stdout
    assert not (tmp_path / "server.txt").exists(), "no second server"
    browser = _read_presence(tmp_path / "browser.txt")
    assert browser[CONTROL] == "set"
    assert all(browser[n] == "unset" for n in HELD_ENV_VARS)


def test_launch_server_starts_the_panel_and_its_curses_check_without_the_held_names():
    """R658: the panel now runs in the launcher's own window, started by launch_server.ps1 beside the server. It never needs the
    passphrases (it drops them itself too, tests/test_terminal_panel.py), so the wrapper removes exactly the server's held names from
    the environment of both processes it starts for it: the curses check and the panel."""
    ps1 = (REPO / "scripts" / "launch_server.ps1").read_text(encoding="utf-8")
    m = re.search(r'^\$HeldEnvVars = @\(([^)]*)\)', ps1, re.M)
    assert m, "launch_server.ps1 names the held variables in one place"
    assert tuple(re.findall(r'"(\w+)"', m.group(1))) == HELD_ENV_VARS
    body = ps_function_body(ps1, "New-PanelStartInfo")
    assert "foreach ($n in $HeldEnvVars) { if ($si.EnvironmentVariables.ContainsKey($n)) { $si.EnvironmentVariables.Remove($n) } }" in body
    # both starts go through that function, and nothing else in the wrapper starts the panel's python
    assert ps1.count("New-PanelStartInfo ") == 2  # the two calls (the definition is "New-PanelStartInfo(")
    assert ps1.count("$PanelPython") == 3  # the parameter, the guard, the FileName in the function
