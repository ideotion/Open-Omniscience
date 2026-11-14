"""The fault-reach audit itself (OPEN_QUEUE item 30, R412): its static reading, its runtime plugin and its baseline.

The weekly job runs the audit over the suite; these tests pin the three ways it can die quietly: it stops seeing a stub
(every test looks clean), it starts seeing guards and collisions as faults (every answer is noise), or its baseline
rots (a line for a deleted test, a line without a reason).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.fault_reach import analyse_source

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fault_reach_audit as audit  # noqa: E402


def _installs(src: str) -> dict[str, list[tuple[str, bool]]]:
    r = analyse_source(textwrap.dedent(src))
    return {k: [(s.name, s.guard) for s in v] for k, v in r.installs.items()}


# --------------------------------------------------------------------------- #
#  Static reading
# --------------------------------------------------------------------------- #
def test_a_stub_handed_over_as_a_value_is_installed_and_one_called_directly_is_not() -> None:
    got = _installs(
        """
        def boom(*a):
            raise RuntimeError("x")

        def test_hands_it_over(monkeypatch):
            monkeypatch.setattr(mod, "f", boom)

        def test_as_keyword():
            run(on_error=boom)

        def test_in_a_dict():
            run(handlers={"a": boom})

        def test_calls_it_itself():
            with pytest.raises(RuntimeError):
                boom()
        """
    )
    assert got == {"test_hands_it_over": [("boom", False)], "test_as_keyword": [("boom", False)], "test_in_a_dict": [("boom", False)]}


def test_a_nested_stub_shadows_a_module_one_and_a_plain_local_name_is_not_a_stub() -> None:
    got = _installs(
        """
        def fail(*a):
            raise OSError(5, "x")

        def test_nested():
            def fail(*a):
                raise ValueError("local")
            run(fail)

        def test_local_value_named_like_a_stub():
            fail = 3
            run(fail)

        def test_a_parameter_named_like_a_stub(fail):
            run(fail)
        """
    )
    assert got == {"test_nested": [("fail", False)]}
    r = analyse_source(textwrap.dedent("def fail(*a):\n    raise OSError(5, 'x')\n\ndef test_nested():\n    def fail(*a):\n        raise ValueError('l')\n    run(fail)\n"))
    assert r.installs["test_nested"][0].exceptions == frozenset({"ValueError"})


def test_guards_are_classified_as_guards() -> None:
    got = _installs(
        """
        import pytest

        def never(*a):
            raise AssertionError("must not be called")

        def todo(*a):
            raise NotImplementedError

        def refuse(*a):
            pytest.fail("called")

        def real(*a):
            raise OSError(28, "full")

        def tracked(*a):
            tracker.fail()
            raise OSError(5, "io")

        def test_mix():
            run(never, todo, refuse, real, tracked)
        """
    )
    assert sorted(got["test_mix"]) == [("never", True), ("real", False), ("refuse", True), ("todo", True), ("tracked", False)]


def test_class_stubs_and_throw_lambdas_are_seen() -> None:
    got = _installs(
        """
        class BrokenStore:
            def write(self, x):
                raise OSError(5, "io")

        thrower = lambda *a: (_ for _ in ()).throw(TimeoutError())

        def test_class():
            run(store=BrokenStore())

        def test_assigned_lambda():
            run(thrower)

        def test_inline_lambda():
            run(lambda *a: (_ for _ in ()).throw(
                KeyboardInterrupt()))
        """
    )
    assert got["test_class"] == [("BrokenStore.write", False)]
    assert got["test_assigned_lambda"] == [("thrower", False)]
    assert [g for _, g in got["test_inline_lambda"]] == [False]
    r = analyse_source(textwrap.dedent("def test_inline_lambda():\n    run(lambda *a: (_ for _ in ()).throw(\n        KeyboardInterrupt()))\n"))
    assert r.installs["test_inline_lambda"][0].code_line == 2 and r.installs["test_inline_lambda"][0].is_lambda


def test_methods_of_test_classes_are_tests_with_their_class_in_the_key() -> None:
    got = _installs(
        """
        def boom():
            raise RuntimeError

        class TestThing:
            def test_x(self):
                run(boom)
        """
    )
    assert got == {"TestThing::test_x": [("boom", False)]}


# --------------------------------------------------------------------------- #
#  Runtime plugin, end to end on a scratch test file
# --------------------------------------------------------------------------- #
_SCRATCH = '''
import pytest
from unittest import mock

def boom(*a):
    raise RuntimeError("fault")

def never(*a):
    raise AssertionError("must not be called")

def guarded_call(fn, use):
    if use:
        try:
            fn()
        except RuntimeError:
            return "handled"
    return "ok"

def test_reaches_its_fault():
    assert guarded_call(boom, True) == "handled"

def test_never_reaches_its_fault():
    assert guarded_call(boom, False) == "ok"

def test_a_guard_at_zero_is_fine():
    assert guarded_call(never, False) == "ok"

@pytest.mark.parametrize("use", [False, True])
def test_one_case_reaching_is_enough(use):
    guarded_call(boom, use)

@pytest.mark.parametrize("fn", [lambda: (_ for _ in ()).throw(RuntimeError("x"))])
def test_a_one_line_lambda_fault_is_seen(fn):
    assert guarded_call(fn, True) == "handled"

class Holder:
    f = None

def test_an_inline_lambda_built_on_the_setattr_line_but_never_called(monkeypatch):
    monkeypatch.setattr(Holder, "f", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    assert guarded_call(Holder.f, False) == "ok"

def test_an_inline_lambda_on_a_continuation_line_never_called():
    assert guarded_call(
        lambda: (_ for _ in ()).throw(RuntimeError("x")),
        False,
    ) == "ok"

def test_a_one_line_nested_def_never_called():
    def boom2(*a): raise RuntimeError("x")
    assert guarded_call(boom2, False) == "ok"

class TestOuter:
    class TestInner:
        def test_nested_class_never_reaches(self):
            assert guarded_call(boom, False) == "ok"

def test_mock_fired():
    m = mock.Mock(side_effect=RuntimeError("x"))
    assert guarded_call(m, True) == "handled"

def test_mock_never_called():
    m = mock.Mock()
    m.side_effect = RuntimeError("x")
    assert guarded_call(m, False) == "ok"

@pytest.mark.skip(reason="not run")
def test_skipped():
    guarded_call(boom, False)

def test_skips_inside_its_body():
    pytest.skip("an optional library is absent")
    guarded_call(boom, True)

def test_fails_before_its_fault():
    assert guarded_call(boom, False) == "not ok"

@pytest.mark.parametrize("use", [True, False])
def test_only_a_failing_case_reaches_its_fault(use):
    assert guarded_call(boom, use) == "ok"  # [True] reaches the fault, then fails: its hit must not clear [False]
'''


def test_the_plugin_flags_exactly_the_tests_whose_fault_never_fired(tmp_path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_scratch.py").write_text(_SCRATCH, encoding="utf-8")
    out = tmp_path / "out"
    env = dict(os.environ, FAULT_REACH_DIR=str(out), FAULT_REACH_EXTRA_ROOT=str(tests_dir), PYTHONPATH=str(ROOT))
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "tests.fault_reach", "-o", "addopts=",
         "--rootdir", str(tmp_path), "--basetemp", str(tmp_path / "bt"), "tests/test_scratch.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )
    assert p.returncode == 1 and "2 failed" in p.stdout, p.stdout + p.stderr  # two scratch tests fail on purpose
    v = audit.judge(audit.load_results(out), root=tmp_path)
    assert sorted(v.flagged) == [
        "tests/test_scratch.py::TestOuter::TestInner::test_nested_class_never_reaches",
        "tests/test_scratch.py::test_a_one_line_nested_def_never_called",
        "tests/test_scratch.py::test_an_inline_lambda_built_on_the_setattr_line_but_never_called",
        "tests/test_scratch.py::test_an_inline_lambda_on_a_continuation_line_never_called",
        "tests/test_scratch.py::test_mock_never_called",
        "tests/test_scratch.py::test_never_reaches_its_fault",
        "tests/test_scratch.py::test_only_a_failing_case_reaches_its_fault",
    ]
    assert "tests/test_scratch.py::test_skipped" not in v.ran
    assert "tests/test_scratch.py::test_skips_inside_its_body" not in v.ran
    assert "tests/test_scratch.py::test_fails_before_its_fault" not in v.ran  # red already; it may have stopped before its fault
    with pytest.raises(ValueError):  # a nodeid read against the wrong root is refused, never judged clean
        audit.judge(audit.load_results(out), root=tmp_path / "tests")
    assert "tests/test_scratch.py::test_a_guard_at_zero_is_fine" not in v.installed

    baseline = {"tests/test_scratch.py::test_never_reaches_its_fault": "zero is right here",
                "tests/test_scratch.py::test_reaches_its_fault": "an old entry",
                "tests/test_scratch.py::test_gone": "deleted"}
    new, stale = audit.compare(v, baseline, root=tmp_path)
    assert "tests/test_scratch.py::test_never_reaches_its_fault" not in new and "tests/test_scratch.py::test_mock_never_called" in new
    assert stale == {"tests/test_scratch.py::test_reaches_its_fault": "it ran and fired its fault",
                     "tests/test_scratch.py::test_gone": "no such test any more"}


# --------------------------------------------------------------------------- #
#  The committed baseline
# --------------------------------------------------------------------------- #
def test_the_baseline_parses_and_every_line_names_a_test_that_exists() -> None:
    baseline = audit.read_baseline()
    missing = set(baseline) - audit.existing_tests(set(baseline))
    assert not missing, f"tests/fault_reach_baseline.txt names tests that are gone (remove the lines): {sorted(missing)}"


@pytest.mark.parametrize("line", ["tests/test_x.py::test_y", "tests/test_x.py::test_y\t ", "no-separator\treason"])
def test_a_baseline_line_without_a_reason_or_a_key_is_refused(tmp_path, line: str) -> None:
    f = tmp_path / "b.txt"
    f.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        audit.read_baseline(f)
