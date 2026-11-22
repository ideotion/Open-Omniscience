"""
R796 (row 331): the panic wipe and the uninstall watcher keep ONE rule about another process holding the store.

The rule (R792, as the security reads of #2292 left it): one more bounded rewrite always runs after the check, whatever it
found; and a holder seen at any point makes the result "may be incomplete" even when it has let go by the end -- it may have
written behind the last rewrite before letting go. The panic wipe (``src/safety/crypto_erase.py``) used to answer "none"
once such a holder had let go. The watcher is a detached script that cannot import ``src``, so the rule lives twice; this
file holds both copies to it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from src.database.connect import have_driver
from tests.js_source_helper import python_function_source
from tests.test_crypto_erase_second_process import _line, _store

# A holder that lets go during the erase: a shared lock on SQLite's lock bytes, kept until a rewrite has changed the (already
# unlinked) main file's head after the erase's own pass -- proof the check saw it -- then released, its descriptor kept open.
_RELEASER = r"""
import fcntl, os, struct, sys, time
fd = os.open(sys.argv[1], os.O_RDWR)
fcntl.fcntl(fd, fcntl.F_SETLK, struct.pack("hhqqi", fcntl.F_RDLCK, 0, 0x40000002, 1, 0))
print("READY", flush=True)
deadline = time.monotonic() + 60
while os.fstat(fd).st_nlink and time.monotonic() < deadline: time.sleep(0.005)
first = os.pread(fd, 16, 0)
while os.pread(fd, 16, 0) == first and time.monotonic() < deadline: time.sleep(0.005)
fcntl.fcntl(fd, fcntl.F_SETLK, struct.pack("hhqqi", fcntl.F_UNLCK, 0, 0x40000002, 1, 0))
print("RELEASED", flush=True)
sys.stdin.readline()
"""


@pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the releaser packs Linux's struct flock")
def test_the_panic_erase_never_answers_none_after_a_seen_holder_lets_go(tmp_path):
    from src.safety.crypto_erase import HOLDER_HELD, quick_crypto_erase

    data, _salt = _store(tmp_path)
    with subprocess.Popen([sys.executable, "-c", _RELEASER, str(data / "open_omniscience.db")],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as other:
        try:
            assert _line(other) == "READY"
            report = quick_crypto_erase(confirm=True, data_dir=data)
            released = _line(other)
            other.stdin.write("done\n")
            other.stdin.flush()
            other.wait(timeout=30)
        finally:
            if other.poll() is None:
                other.kill()
    assert released == "RELEASED", released
    assert report["other_holder"] == HOLDER_HELD, report
    assert "unrecoverable" not in report.get("limit", ""), report


def test_both_copies_of_the_rule_say_the_same_thing():
    """The watcher's copy (it cannot import src) and the panic wipe's: a final rewrite outside the holder loop, and a seen
    holder that forces the result."""
    from src.safety import crypto_erase
    from src.safety.uninstall import _WATCHER_SRC

    panic = python_function_source(open(crypto_erase.__file__, encoding="utf-8").read(), "settle_other_holders")
    assert "if seen or state == HOLDER_HELD:" in panic and "ever_unknown or state == HOLDER_UNKNOWN" in panic
    assert "\n        rescrub_held(close=False, generation=generation, deadline=time.monotonic() + bound)\n" in panic
    watcher = python_function_source(_WATCHER_SRC, "check_other_holders")
    assert 'if held_stat["ever"]: state = "held"' in watcher
    assert 'elif held_stat.get("unknown"): state = "unknown"' in watcher
    assert "\n    rewrite_kept(time.monotonic() + BOUND)" in watcher


def test_a_probe_that_could_not_tell_is_never_cleared_by_a_later_one_in_the_panic_copy(monkeypatch):
    """Security read of row 331: a first probe that could not tell, then a final one that saw nothing, must stay "unknown"."""
    from src.safety import crypto_erase

    answers = iter([crypto_erase.HOLDER_UNKNOWN, crypto_erase.HOLDER_NONE])
    monkeypatch.setattr(crypto_erase, "_holder_state", lambda entries: next(answers))
    monkeypatch.setattr(crypto_erase, "rescrub_held", lambda **k: 0)
    assert crypto_erase.settle_other_holders(987654) == crypto_erase.HOLDER_UNKNOWN


def test_a_probe_that_could_not_tell_is_remembered_in_the_watcher_copy():
    import os as _os

    from src.safety.uninstall import _WATCHER_SRC

    answers = iter([None, False])
    ns: dict = {"os": _os, "fcntl": object(), "LAYOUT": "hhqqi", "kept": [(0, "head", 0)],
                "held_stat": {"missed": 0, "seen": 1, "ever": False, "unknown": False}, "holder": lambda fd: next(answers)}
    exec(python_function_source(_WATCHER_SRC, "holder_state"), ns)  # noqa: S102 - the watcher's own helper, from the repository
    if _os.name != "posix":
        pytest.skip("the watcher's probe answers unknown on every call off POSIX")
    assert ns["holder_state"]() == "unknown"
    assert ns["holder_state"]() == "none"
    assert ns["held_stat"]["unknown"] is True
