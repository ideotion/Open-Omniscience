"""The test process binds the app's engine to the suite's directory before any test body, and a net catches a binding that is not.

``src.database.session`` binds its engine to ``OO_DATA_DIR`` once, at its first import, while the settings store reads the variable on
every call. A test that moves the variable to its ``tmp_path`` and only then imports the session first splits the process across two
stores. ``tests/conftest.py`` therefore imports the session itself, right after its env defaults (so a selection behaves like a full run,
where collection does it), and keeps ``_engine_binds_to_the_suite_directory`` as the net under that line.

Red-without is run, not described: a child pytest (the conftest loaded as a plugin) runs the bad order. With the real conftest it must
PASS (the import made the order irrelevant); with a copy of the conftest that has lost the import line it must FAIL at that test's
teardown, naming it; the good order passes under both. A guard that is never seen failing is a comment.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFTEST = ROOT / "tests" / "conftest.py"
IMPORT_LINE = "import src.database.session  # noqa: E402, F401 - imported for its binding\n"

_BAD = '''
def test_moves_the_variable_and_imports_the_session_first(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    import src.database.session  # the first import of the process, if nothing bound it before
'''
_GOOD = '''
def test_imports_the_session_then_moves_the_variable(monkeypatch, tmp_path):
    import src.database.session
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
'''


def _child(tmp_path: Path, body: str, *, plugin: str) -> subprocess.CompletedProcess:
    test_file = tmp_path / "test_child.py"
    test_file.write_text(textwrap.dedent(body), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("OO_DATA_DIR", "OO_TESTS_DEFAULT_DATA_DIR", "PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS")}
    env["PYTHONPATH"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", plugin, "--rootdir", str(tmp_path), str(test_file)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _conftest_without_the_import(tmp_path: Path) -> str:
    src = CONFTEST.read_text(encoding="utf-8")
    assert src.count(IMPORT_LINE) == 1, "tests/conftest.py must carry the binding import exactly once, as one line"
    (tmp_path / "strippedconf.py").write_text(src.replace(IMPORT_LINE, ""), encoding="utf-8")
    return "strippedconf"


def test_the_conftest_binds_the_engine_to_the_suite_directory_at_the_start_of_the_session():
    import tests.conftest as conftest
    from src.database import session

    assert Path(str(session.DATA_DIR)).resolve() == Path(conftest._SUITE_DATA_DIR).resolve()
    src = CONFTEST.read_text(encoding="utf-8")
    assert src.index(IMPORT_LINE) > src.index('os.environ.setdefault("OO_KV_STRICT_GATE_ORDER"'), "after every env default the session reads"
    assert src.index(IMPORT_LINE) < src.index("def _the_test_process_is_not_held_to_a_core_limit"), "before the first fixture"


def test_with_the_import_a_test_that_moves_the_variable_first_binds_nothing_away(tmp_path):
    done = _child(tmp_path, _BAD, plugin="tests.conftest")
    out = done.stdout + done.stderr
    assert done.returncode == 0 and "1 passed" in out, out[-1500:]


def test_without_the_import_the_same_test_fails_at_its_own_teardown_by_name(tmp_path):
    done = _child(tmp_path, _BAD, plugin=_conftest_without_the_import(tmp_path))
    out = done.stdout + done.stderr
    assert done.returncode != 0, out[-1500:]
    assert "ERROR at teardown of test_moves_the_variable_and_imports_the_session_first" in out, out[-1500:]
    assert "imported src.database.session while OO_DATA_DIR pointed away from the suite's directory" in out, out[-1500:]


def test_the_other_order_passes_with_or_without_the_import(tmp_path):
    for plugin in ("tests.conftest", _conftest_without_the_import(tmp_path)):
        done = _child(tmp_path, _GOOD, plugin=plugin)
        out = done.stdout + done.stderr
        assert done.returncode == 0 and "1 passed" in out, (plugin, out[-1500:])


def test_the_net_is_an_autouse_fixture_that_looks_at_the_first_binding_only():
    """The shape the children above depend on: autouse (no test names it), and a module already imported at the test's start is left
    alone (a second binding cannot happen, and the check costs one dictionary lookup per test)."""
    src = CONFTEST.read_text(encoding="utf-8")
    start = src.index("def _engine_binds_to_the_suite_directory")
    assert "@pytest.fixture(autouse=True)" in src[start - 60 : start]
    body = src[start : src.index("\n@pytest.fixture", start)]
    assert 'already = "src.database.session" in sys.modules' in body and "if already:" in body
    assert "_SUITE_DATA_DIR" in body
