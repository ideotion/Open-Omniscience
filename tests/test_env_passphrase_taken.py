"""The passphrases a process is started with leave its environment once the store has read them (core fold 4, 2026-10-07).

A process the app starts by ``exec`` with the parent's environment (the standard library's resource tracker, its forkserver) holds
a copy of whatever the environment holds, and no code of ours has run in it to guard that copy. So ``src/database/connect.py``
moves ``OO_DB_PASSPHRASE`` (and ``OO_KEY_PASSPHRASE``) out of ``os.environ`` into ``secret_scrub`` at import, and the app reads
them from there. These tests start real processes, and read what the paths that need a passphrase still get.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.monitoring import core_guard, engine_text
from src.monitoring import secret_scrub as S

ROOT = Path(__file__).resolve().parents[1]
PASS = "Qv9#taken-from-the-environment'Lm2"
KEY_PASS = "Zk4#signing-wrap-taken'Rt7"

_CHILD = """
import os, subprocess, sys
from src.database import connect
from src.monitoring import secret_scrub as S
assert 'OO_DB_PASSPHRASE' not in os.environ and 'OO_KEY_PASSPHRASE' not in os.environ, 'still in the environment'
assert connect.get_passphrase() == {passphrase!r}, 'the store lost it'
assert S.env_secret('OO_KEY_PASSPHRASE') == {key!r}
assert set(S.taken_environment()) == {{'OO_DB_PASSPHRASE', 'OO_KEY_PASSPHRASE'}}
seen = subprocess.run([sys.executable, '-c', 'import os; print(sorted(k for k in os.environ if k.startswith("OO_")))'],
                      capture_output=True, text=True).stdout
assert 'PASSPHRASE' not in seen, seen
if sys.platform.startswith('linux'):
    from multiprocessing import resource_tracker
    resource_tracker.ensure_running()
    pid = resource_tracker._resource_tracker._pid
    environ = open(f'/proc/{{pid}}/environ', 'rb').read()
    assert b'PASSPHRASE' not in environ and {passphrase!r}.encode() not in environ, 'the resource tracker holds it'
print('ok')
"""


def _run(code: str, tmp_path, **extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={
            "PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "OO_DATA_DIR": str(tmp_path / "data"),
            "PYTHONDONTWRITEBYTECODE": "1", "OO_DB_PASSPHRASE": PASS, "OO_KEY_PASSPHRASE": KEY_PASS, **extra,
        },
        capture_output=True, text=True, timeout=120,
    )


def test_a_child_started_after_the_store_is_imported_holds_no_passphrase(tmp_path):
    """MUTATION TARGET: the ``take_from_environment`` call in ``connect.py``. Includes the resource tracker the standard library
    starts by ``exec`` with the parent's environment, which holds the passphrase of a scripted start when nothing took it out."""
    proc = _run(_CHILD.format(passphrase=PASS, key=KEY_PASS), tmp_path)
    assert proc.returncode == 0 and proc.stdout.strip() == "ok", proc.stderr[-1500:]


def test_the_control_without_the_take_the_child_does_hold_it(tmp_path):
    """The control: the same child, with the take replaced, fails on the first assertion."""
    code = "from src.monitoring import secret_scrub as S\nS.take_from_environment = lambda *a, **k: None\n" + _CHILD.format(
        passphrase=PASS, key=KEY_PASS
    )
    proc = _run(code, tmp_path)
    assert proc.returncode != 0 and "still in the environment" in proc.stderr


@pytest.fixture
def taken(monkeypatch):
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(S, "_TAKEN", {"OO_DB_PASSPHRASE": PASS, "OO_KEY_PASSPHRASE": KEY_PASS})
    monkeypatch.setattr("src.database.connect._passphrase", None)


def test_take_moves_the_variables_and_keeps_them_readable(monkeypatch):
    monkeypatch.setattr(S, "_TAKEN", {})
    monkeypatch.setenv("OO_DB_PASSPHRASE", PASS)
    monkeypatch.setenv("OO_KEY_PASSPHRASE", KEY_PASS)
    monkeypatch.setenv("OO_TEST_KEEP", "kept")
    S.take_from_environment()
    import os

    assert "OO_DB_PASSPHRASE" not in os.environ and "OO_KEY_PASSPHRASE" not in os.environ and os.environ["OO_TEST_KEEP"] == "kept"
    assert S.env_secret("OO_DB_PASSPHRASE") == PASS and S.taken_environment() == {"OO_DB_PASSPHRASE": PASS, "OO_KEY_PASSPHRASE": KEY_PASS}
    monkeypatch.setenv("OO_DB_PASSPHRASE", "set later by an operator's code")
    assert S.env_secret("OO_DB_PASSPHRASE") == "set later by an operator's code", "the environment's own value wins when there is one"
    assert S.env_secret("OO_NOT_A_PASSPHRASE") is None


def test_what_was_taken_is_still_scrubbed_from_every_text(taken):
    assert PASS in (S.held_passphrases() or ()) and KEY_PASS in (S.held_passphrases() or ())
    assert PASS not in S.scrubbed(f"the store refused {PASS}")
    assert PASS not in engine_text.engine_text(RuntimeError(f"PRAGMA key = '{PASS}'"))


def test_the_signing_keys_are_still_wrapped_by_the_taken_key_passphrase(taken):
    from src.custody import signing

    assert signing._passphrase() == KEY_PASS.encode("utf-8")


def test_a_data_drive_restart_hands_the_new_process_what_was_taken_and_nothing_else(taken, monkeypatch):
    """MUTATION TARGET: ``_restart_process`` going back to ``os.execv``, which hands the new process the environment as it is NOW:
    one without the passphrase, so a scripted install would come back up locked."""
    from src.safety import data_volume

    seen: dict = {}
    monkeypatch.setenv("OO_TEST_KEEP", "kept")
    monkeypatch.setattr(data_volume.os, "execve", lambda exe, argv, env: seen.update(exe=exe, argv=argv, env=env))
    data_volume._restart_process()
    assert seen["env"]["OO_DB_PASSPHRASE"] == PASS and seen["env"]["OO_KEY_PASSPHRASE"] == KEY_PASS and seen["env"]["OO_TEST_KEEP"] == "kept"
    import os

    assert "OO_DB_PASSPHRASE" not in os.environ, "this process's own environment is untouched"


def test_a_key_typed_into_the_unlock_page_is_not_handed_to_the_restarted_process(monkeypatch):
    from src.safety import data_volume

    monkeypatch.setattr(S, "_TAKEN", {})
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", "typed-into-the-page-91")
    seen: dict = {}
    monkeypatch.setattr(data_volume.os, "execve", lambda exe, argv, env: seen.update(env=env))
    data_volume._restart_process()
    assert "typed-into-the-page-91" not in repr(seen["env"]) and "OO_DB_PASSPHRASE" not in seen["env"]


def test_the_windows_calls_themselves_return_none_and_never_raise_where_there_is_no_windows(monkeypatch):
    """The seams the Windows tests stand in for, run for real with the platform name set: on a machine with no ``windll`` or
    ``ucrtbase`` they answer ``None`` and do nothing, so a platform check that was wrong would be a quiet failure, not a crash."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert core_guard._win_error_mode() is None
    assert core_guard._win_abort_flags() is None
    assert core_guard._win_abort_flags(0, 0x3) is None
    assert core_guard._win_set_error_mode(0x2) is None
