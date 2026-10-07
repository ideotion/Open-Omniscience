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
    from multiprocessing import forkserver
    forkserver.ensure_running()
    fpid = forkserver._forkserver._forkserver_pid
    assert fpid and fpid != pid
    fenv = open(f'/proc/{{fpid}}/environ', 'rb').read()
    assert b'PASSPHRASE' not in fenv and {passphrase!r}.encode() not in fenv, 'the forkserver holds it'
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


# --------------------------------------------------------------------------- #
#  A take that fails leaves a record, and a value set later hides no taken one
# --------------------------------------------------------------------------- #
def test_a_pop_that_raises_is_recorded_by_its_class_and_never_by_its_text(monkeypatch):
    """MUTATION TARGET: ``take_from_environment``'s recording (it was a bare suppress: the passphrase stayed in the environment with
    no trace)."""
    class Env(dict):
        def pop(self, *a, **k):
            raise PermissionError(f"cannot pop {PASS}")

    monkeypatch.setattr(S, "_TAKE_FAILED", [])
    monkeypatch.setattr(S.os, "environ", Env(OO_DB_PASSPHRASE=PASS))
    S.take_from_environment()
    assert S.take_failed() == ["PermissionError", "PermissionError"]
    assert PASS not in repr(S.take_failed())


def test_the_boot_record_names_a_failed_take_and_the_variables_still_in_the_environment(monkeypatch):
    from src.monitoring import session_history

    monkeypatch.setattr(S, "_TAKE_FAILED", ["PermissionError"])
    monkeypatch.setenv("OO_DB_PASSPHRASE", PASS)
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect._TAKE_FAILED", "ImportError")
    got = session_history._boot_env_take()
    assert got == {"store_imported": True, "still_in_environment": ["OO_DB_PASSPHRASE"], "take_failed": ["PermissionError", "ImportError"]}
    assert PASS not in repr(got)


def test_the_boot_record_of_a_clean_take_says_so(monkeypatch):
    from src.monitoring import session_history

    monkeypatch.setattr(S, "_TAKE_FAILED", [])
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect._TAKE_FAILED", None)
    assert session_history._boot_env_take() == {"store_imported": True, "still_in_environment": [], "take_failed": []}


def test_a_value_set_in_the_environment_later_hides_neither_it_nor_the_taken_one(taken, monkeypatch):
    """MUTATION TARGET: ``held_passphrases`` reading one value per name (the environment's, when set, over the taken one)."""
    later = "set-later-by-an-operators-code-55"
    monkeypatch.setenv("OO_DB_PASSPHRASE", later)
    held = S.held_passphrases() or ()
    assert PASS in held and later in held
    text = S.scrubbed(f"a {PASS} and a {later}")
    assert PASS not in text and later not in text


def test_the_ephemeral_child_is_handed_what_was_taken(taken, monkeypatch):
    """MUTATION TARGET: ``**taken_environment()`` in ``_run_ephemeral`` (``src/api/main.py``), which starts a process that is this
    program again, as the data-volume restart does. A no-op today (nothing imports the store before it), and pinned for the day
    something does."""
    import subprocess as sp

    from src.api import main

    seen: dict = {}
    monkeypatch.setattr(sp, "run", lambda *a, **k: seen.update(env=k["env"]))
    main._run_ephemeral(["serve"])
    assert seen["env"]["OO_DB_PASSPHRASE"] == PASS and seen["env"]["OO_KEY_PASSPHRASE"] == KEY_PASS
    assert seen["env"]["OO_EPHEMERAL"] == "0"


def test_before_the_store_is_imported_no_name_is_reported_as_a_failed_take(monkeypatch):
    """The take runs at the first import of the store: until then the names are still there for it to take, and a record that
    named them would read as a take that failed."""
    import sys

    from src.monitoring import session_history

    monkeypatch.delitem(sys.modules, "src.database.connect", raising=False)
    monkeypatch.setenv("OO_DB_PASSPHRASE", PASS)
    assert session_history._boot_env_take() == {"store_imported": False, "still_in_environment": None, "take_failed": None}


def test_the_ledger_boot_record_carries_env_take_and_so_does_boots_json(tmp_path, monkeypatch):
    """MUTATION TARGET: ``"env_take"`` in ``record_boot`` and in ``boots._BOOT_FIELDS`` (either can go with every other test green, and a
    failed take then reads as a clean one in the bundle)."""
    from src.monitoring import boots, session_history, session_hwm

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    session_history._reset_for_tests()
    session_hwm.reset_for_tests()
    try:
        rec = session_history.record_boot(None)
        assert set(rec["env_take"]) >= {"still_in_environment", "take_failed"}
        on_disk = [r for r in session_history.read_records() if r["kind"] == "boot"][-1]
        assert on_disk["env_take"] == rec["env_take"]
        member = boots.diagnostics_member()
        assert member["boots"][-1]["env_take"] == rec["env_take"]
    finally:
        session_history._reset_for_tests()
        session_hwm.reset_for_tests()


_FAILED_TAKE_CHILD = """
import os, sys
sys.modules['src.monitoring.secret_scrub'] = None          # the import inside connect.py fails
from src.database import connect
assert connect._TAKE_FAILED == 'ModuleNotFoundError', connect._TAKE_FAILED
assert os.environ.get('OO_DB_PASSPHRASE') == {passphrase!r}, 'a failed take leaves it where it was'
del sys.modules['src.monitoring.secret_scrub']
from src.monitoring import session_history
got = session_history._boot_env_take()
assert got == {{'store_imported': True, 'still_in_environment': ['OO_DB_PASSPHRASE', 'OO_KEY_PASSPHRASE'], 'take_failed': ['ModuleNotFoundError']}}, got
assert {passphrase!r} not in repr(got)
print('ok')
"""


def test_a_failed_import_of_the_take_leaves_a_record_end_to_end(tmp_path):
    """MUTATION TARGET: the record of the failure in ``connect.py`` (it was a bare suppress: the passphrase stayed in the environment with
    no trace). A real process, with the scrub module's import made to fail."""
    proc = _run(_FAILED_TAKE_CHILD.format(passphrase=PASS), tmp_path)
    assert proc.returncode == 0 and proc.stdout.strip() == "ok", proc.stderr[-1500:]


_FORKSERVER_ONLY = """
{prelude}
import os
from src.database import connect
from multiprocessing import forkserver
forkserver.ensure_running()
fpid = forkserver._forkserver._forkserver_pid
environ = open(f'/proc/{{fpid}}/environ', 'rb').read()
print('forkserver-holds-it' if b'PASSPHRASE' in environ or {passphrase!r}.encode() in environ else 'forkserver-clean')
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc/<pid>/environ")
def test_the_forkserver_check_has_a_control_of_its_own(tmp_path):
    """The forkserver's environment is read the same way with the take REPLACED (the control: it must say the forkserver holds the
    passphrase), and with it in place (it must say clean): so the forkserver lines of ``_CHILD`` cannot pass by reading nothing."""
    control = _run(
        _FORKSERVER_ONLY.format(prelude="from src.monitoring import secret_scrub as S\nS.take_from_environment = lambda *a, **k: None", passphrase=PASS),
        tmp_path,
    )
    assert control.returncode == 0 and control.stdout.strip() == "forkserver-holds-it", control.stderr[-1500:]
    real = _run(_FORKSERVER_ONLY.format(prelude="", passphrase=PASS), tmp_path)
    assert real.returncode == 0 and real.stdout.strip() == "forkserver-clean", real.stderr[-1500:]


_LIFESPAN_CHILD = """
import asyncio, sys
from src.monitoring import secret_scrub as S
def refuse(*a, **k):
    raise PermissionError('text that must never be recorded')
S.take_from_environment = refuse
assert 'src.database.connect' not in sys.modules
from src.api import main
assert 'src.database.connect' in sys.modules, 'the take did not run before the lifespan'
async def go():
    async with main.lifespan(main.app):
        from src.monitoring import session_history
        boot = [r for r in session_history.read_records() if r['kind'] == 'boot'][-1]
        got = boot['env_take']
        assert got == {{'store_imported': True, 'still_in_environment': ['OO_DB_PASSPHRASE', 'OO_KEY_PASSPHRASE'], 'take_failed': ['PermissionError']}}, got
        assert 'must never be recorded' not in repr(boot) and {passphrase!r} not in repr(boot)
asyncio.run(go())
print('ok')
"""


def test_the_take_comes_before_the_boot_record_on_a_server_started_by_uvicorn(tmp_path):
    """A server not started by ``_serve`` (``python -m uvicorn src.api.main:app``, or ``serve`` with OO_AUTOSEED=0) writes its boot
    record from the lifespan: the take has run by then, a take that failed is read back from the ledger by its class, and the engine's
    text is not in the record. MUTATION TARGET: the import of ``connect`` in ``lifespan`` and the one at the top of ``src.api.main``'s
    chain (either, with the other gone, still passes: the test fails only when neither is left)."""
    proc = _run(
        _LIFESPAN_CHILD.format(passphrase=PASS), tmp_path,
        OO_DB_PLAINTEXT="1", OO_NO_SCHEDULER="1", OO_AUTOSEED="0", OO_SESSION_LIVENESS="0",
    )
    assert proc.returncode == 0 and proc.stdout.strip().endswith("ok"), (proc.stdout + proc.stderr)[-1500:]
