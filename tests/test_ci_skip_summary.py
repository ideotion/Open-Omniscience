"""``scripts/ci_skip_summary.py``: what a CI job skipped, by class and by test module, and never a reason.

Why. The only reader of a CI job log that works from a session returns the last few kilobytes, and ``pytest -rsfE``'s skip block is hundreds of
lines long, so "what did this job not run" could only be answered by re-running the suite locally (the 2026-10-29 skip audit did exactly that).
The two full-suite jobs now write a junit report and run this script on it, on red as well as green. A skip's reason is free text that a test
author wrote and pytest stores beside an ABSOLUTE PATH (a skip at collection time, such as a module-level ``importorskip``, carries
``('/home/runner/.../tests/test_x.py', 2, "Skipped: could not import 'duckdb': ...")`` as its element text), so this output is built from fixed
words, integers and two kinds of name that must match a strict identifier pattern, and the tests below plant a path and a secret in every field a
reason can reach and read the output for them.

What this pins:

* the counts and the two groupings are right on every shape of skip a real report has (test level, collection level, ``importorskip`` at either
  level, an expected failure that is not a skip), and the shapes are the ones pytest WRITES: one test runs a real pytest on a tiny project and
  summarizes the report it produced, so a pytest release that moves the shape fails here and not silently in CI;
* every output line has one of a few fixed shapes (``_line_problems``): a planted path, secret, newline or workflow command (``::error::``) in a
  message, an element text, a class name or a test name appears in NO line, whatever the text says;
* it never fails a job: a missing report, a truncated one, a hostile one (an entity-expansion document, refused by ``defusedxml``) and an empty one
  each become one honest line and exit status 0; only a wrong command line is an error;
* the guard proves itself: a variant that prints the message, or the element text, is caught by the same line check.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "ci_skip_summary.py"
sys.path.insert(0, str(_ROOT / "scripts"))

import ci_skip_summary  # noqa: E402

#: What the planted text contains: an absolute path, a token-shaped secret, a line break, and a GitHub workflow command that would act on the log.
_SECRET = "ghp_SECRETtoken0123456789"
_PATH = "/home/runner/work/private/tests/test_leak.py"
_PLANTED = (_SECRET, _PATH, "/home/", "::error::", "::set-output", "pwned")

_IDENT = r"[A-Za-z_][A-Za-z0-9_.]*"
_ALLOWED_LINES = (
    re.compile(r"### Skipped tests \(counts only, no gate\)"),
    re.compile(r"```"),
    re.compile(r"\d+ test cases: \d+ ran, \d+ skipped, \d+ expected failures"),
    re.compile(r"skipped, by class \(counts only; the reasons are in the pytest summary in the job's web log\):"),
    re.compile(r"  other  \d+"),
    re.compile(rf"  import {_IDENT}  \d+"),
    re.compile(r"skipped, by test module \(largest first, \d+ of \d+\):"),
    re.compile(rf"  (?:{_IDENT}|\(unnamed\)|\(not a test module\))  \d+"),
    re.compile(r"  \(and \d+ more modules, \d+ skips\)"),
    re.compile(r"skip summary: [a-z][a-z ()]*[a-z)]"),
    re.compile(r"skip summary: the junit report could not be read \([A-Za-z]+\)"),
)


def _line_problems(text: str) -> list[str]:
    """Every output line must have one of the fixed shapes above, and none may contain planted text."""
    found = [f"line has no fixed shape: {line!r}" for line in text.splitlines() if not any(p.fullmatch(line) for p in _ALLOWED_LINES)]
    found += [f"planted text {needle!r} reached the output" for needle in _PLANTED if needle in text]
    return found


def _report(*cases: str) -> str:
    return f'<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest">{"".join(cases)}</testsuite></testsuites>'


def _case(classname: str, name: str, skipped: str = "") -> str:
    return f'<testcase classname="{classname}" name="{name}" time="0.001">{skipped}</testcase>'


def _skip(message: str, text: str = "", kind: str = "pytest.skip") -> str:
    return f'<skipped type="{kind}" message="{message}">{text}</skipped>'


def _write(tmp_path: Path, xml: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_bytes(xml.encode("utf-8"))  # bytes: Windows text mode would rewrite the line breaks the hostile fixtures plant
    return path


def _output(tmp_path: Path, xml: str) -> str:
    return "\n".join(ci_skip_summary.summarize(_write(tmp_path, xml)))


# One report with every shape a real one has. Each reason and each element text carries the planted path and secret.
_MIXED = _report(
    _case("tests.test_a", "test_ran"),
    _case("tests.test_a", "test_skipped", _skip(f"needs {_PATH} {_SECRET}", f"{_PATH}:7: needs {_SECRET}")),
    _case("tests.test_a.TestK", "test_in_a_class", _skip(f"needs {_SECRET}", f"{_PATH}:9: {_SECRET}")),
    _case("", "tests.test_cols", _skip("collection skipped", f"('{_PATH}', 2, \"Skipped: could not import 'duckdb': No module named 'duckdb'\")")),
    _case("tests.test_b", "test_import", _skip("could not import 'socks': No module named 'socks'", f"{_PATH}:4: could not import 'socks': No module named 'socks'")),
    _case("tests.test_b", "test_xfail", _skip(f"known {_SECRET}", kind="pytest.xfail")),
    _case("tests.sub.test_deep", "test_x", _skip(f"deep {_PATH}", "")),
)


def test_counts_classes_and_modules_are_right_on_every_shape_of_skip(tmp_path):
    out = _output(tmp_path, _MIXED)
    assert out.splitlines() == [
        "7 test cases: 1 ran, 5 skipped, 1 expected failures",
        "skipped, by class (counts only; the reasons are in the pytest summary in the job's web log):",
        "  other  3",
        "  import duckdb  1",
        "  import socks  1",
        "skipped, by test module (largest first, 4 of 4):",
        "  tests.test_a  2",
        "  tests.sub.test_deep  1",
        "  tests.test_b  1",
        "  tests.test_cols  1",
    ]


def test_no_reason_path_or_secret_reaches_the_output(tmp_path):
    assert _line_problems(_output(tmp_path, _MIXED)) == []


@pytest.mark.parametrize(
    ("label", "xml"),
    [
        ("a workflow command in a reason", _report(_case("tests.test_a", "test_x", _skip("::error::pwned")))),
        ("a workflow command after a module name", _report(_case("tests.test_a", "test_x", _skip("could not import 'ok::set-output name=x::pwned'")))),
        ("a line break inside a module name", _report(_case("tests.test_a", "test_x", _skip("could not import 'ok&#10;::error::pwned'")))),
        ("a secret as the module name's tail", _report(_case("tests.test_a", "test_x", _skip(f"could not import 'a b {_SECRET}'")))),
        ("a path as the imported module", _report(_case("tests.test_a", "test_x", _skip(f"could not import '{_PATH}': No module")))),
        ("a name over the length bound", _report(_case("tests.test_a", "test_x", _skip("could not import '" + "a" * 80 + "'")))),
        ("a workflow command as the class name", _report(_case("tests.test_a&#10;::error::pwned", "test_x", _skip("x")))),
        ("a path as the class name", _report(_case(_PATH, "test_x", _skip("x")))),
        ("a workflow command as a collection name", _report(_case("", "::error::pwned", _skip("collection skipped", "::error::pwned")))),
        ("no text at all", _report(_case("tests.test_a", "test_x", "<skipped/>"))),
    ],
)
def test_hostile_text_in_any_field_never_reaches_the_output(tmp_path, label, xml):
    out = _output(tmp_path, xml)
    assert _line_problems(out) == [], (label, out)


def test_a_collection_skip_takes_its_module_from_the_element_text_and_only_the_module(tmp_path):
    out = _output(tmp_path, _report(_case("", "tests.test_cols", _skip("collection skipped", f"('{_PATH}', 2, \"Skipped: could not import 'duckdb': x\")"))))
    assert "  import duckdb  1" in out.splitlines()
    assert "  tests.test_cols  1" in out.splitlines()
    assert _PATH not in out


def test_a_message_that_is_not_the_collection_marker_is_not_searched_in_the_element_text(tmp_path):
    # the element text of a test-level skip is "path:line: reason"; only the MESSAGE decides a test-level class
    out = _output(tmp_path, _report(_case("tests.test_a", "test_x", _skip("because", "p.py:1: could not import 'duckdb': x"))))
    assert "  other  1" in out.splitlines()
    assert "duckdb" not in out


def test_names_that_cannot_be_told_safely_become_fixed_words(tmp_path):
    out = _output(
        tmp_path,
        _report(
            _case("not_a_test_module", "test_x", _skip("a")),
            _case("tests/with/slashes", "test_x", _skip("b")),
        ),
    )
    assert "  (not a test module)  1" in out.splitlines()
    assert "  (unnamed)  1" in out.splitlines()


def test_the_module_list_is_bounded_and_the_rest_is_summed_not_dropped(tmp_path):
    many = _report(*(_case(f"tests.test_m{i:03d}", "test_x", _skip("r")) for i in range(ci_skip_summary._MODULE_LINES + 7)))
    lines = _output(tmp_path, many).splitlines()
    assert f"skipped, by test module (largest first, {ci_skip_summary._MODULE_LINES} of {ci_skip_summary._MODULE_LINES + 7}):" in lines
    assert lines[-1] == "  (and 7 more modules, 7 skips)"
    assert sum(1 for line in lines if re.fullmatch(r"  tests\.test_m\d+  1", line)) == ci_skip_summary._MODULE_LINES
    assert _line_problems("\n".join(lines)) == []


def test_a_report_with_no_skip_prints_one_line_of_counts(tmp_path):
    assert _output(tmp_path, _report(_case("tests.test_a", "test_x"), _case("tests.test_a", "test_y"))) == "2 test cases: 2 ran, 0 skipped, 0 expected failures"
    assert _output(tmp_path, '<?xml version="1.0"?><testsuites/>') == "0 test cases: 0 ran, 0 skipped, 0 expected failures"


def test_a_report_nobody_wrote_a_truncated_one_and_a_hostile_one_each_become_one_line(tmp_path):
    missing = "\n".join(ci_skip_summary.summarize(tmp_path / "never-written.xml"))
    assert missing == "skip summary: no junit report was written (pytest did not get as far as writing one)"
    truncated = _output(tmp_path, _MIXED[: len(_MIXED) // 2])
    assert truncated == "skip summary: the junit report could not be parsed (pytest may have been killed while writing it)"
    # an entity declaration is what an entity-expansion document needs; defusedxml refuses it, and only the exception's class name is printed
    hostile = _output(tmp_path, '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaa">]><testsuites>&a;</testsuites>')
    assert hostile == "skip summary: the junit report could not be read (EntitiesForbidden)"
    for out in (missing, truncated, hostile):
        assert _line_problems(out) == [], out


def test_a_directory_in_place_of_the_report_is_one_line_too(tmp_path):
    assert "\n".join(ci_skip_summary.summarize(tmp_path)).startswith("skip summary: ")


# --- as the CI step runs it: a command line, an exit status, a fenced block for the step summary ---------------------------------------------------


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_SCRIPT), *args], capture_output=True, text=True, check=False, timeout=60)


def test_the_command_line_prints_a_fenced_block_and_exits_zero_whatever_the_report_says(tmp_path):
    for xml in (_MIXED, _MIXED[:100], "", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><testsuites>&a;</testsuites>'):
        done = _run(str(_write(tmp_path, xml)))
        assert done.returncode == 0, (xml[:40], done.stderr)
        lines = done.stdout.splitlines()
        assert lines[0] == "### Skipped tests (counts only, no gate)" and lines[1] == "```" and lines[-1] == "```", done.stdout
        assert _line_problems(done.stdout) == [], done.stdout
    done = _run(str(tmp_path / "never-written.xml"))
    assert done.returncode == 0 and "no junit report was written" in done.stdout


def test_the_command_line_is_an_error_only_when_it_is_used_wrongly():
    for args in ((), ("a.xml", "b.xml")):
        done = _run(*args)
        assert done.returncode == 2 and done.stdout == "" and "usage" in done.stderr


# --- the shape pytest actually writes, not only the shape these fixtures assume ------------------------------------------------------------------


def test_the_report_a_real_pytest_writes_is_summarized_as_the_fixtures_say(tmp_path):
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "pytest.ini").write_bytes(b"[pytest]\ntestpaths = tests\n")
    (project / "tests" / "test_cols.py").write_bytes(b"import pytest\npytest.importorskip('module_that_is_not_installed_xyz')\n")
    (project / "tests" / "test_mixed.py").write_bytes(
        (
            "import pytest\n\n"
            "def test_ran():\n    pass\n\n"
            f"@pytest.mark.skipif(True, reason='needs {_PATH} {_SECRET}')\n"
            "def test_skipif():\n    pass\n\n"
            f"def test_skip_call():\n    pytest.skip('{_SECRET}')\n\n"
            "def test_importorskip_call():\n    pytest.importorskip('another_missing_module_xyz')\n\n"
            "@pytest.mark.xfail(reason='known')\n"
            "def test_xfail():\n    assert False\n\n"
            "class TestInClass:\n    @pytest.mark.skip(reason='nested')\n    def test_nested(self):\n        pass\n"
        ).encode()
    )
    report = tmp_path / "junit.xml"
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
        cwd=project, capture_output=True, text=True, check=False, timeout=120, env=env,
    )
    assert report.is_file(), done.stdout + done.stderr
    lines = "\n".join(ci_skip_summary.summarize(report)).splitlines()
    assert lines == [
        "7 test cases: 1 ran, 5 skipped, 1 expected failures",
        "skipped, by class (counts only; the reasons are in the pytest summary in the job's web log):",
        "  other  3",
        "  import another_missing_module_xyz  1",
        "  import module_that_is_not_installed_xyz  1",
        "skipped, by test module (largest first, 2 of 2):",
        "  tests.test_mixed  4",
        "  tests.test_cols  1",
    ], lines
    assert _line_problems("\n".join(lines)) == []


# --- the guard proves itself ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "replacement"),
    [
        ("prints the message", lambda message, text: f"reason {message}"),
        ("prints the element text", lambda message, text: f"reason {text}"),
        ("prints the message as the import class", lambda message, text: "import " + message),
    ],
)
def test_the_line_check_names_a_variant_that_prints_a_reason(tmp_path, monkeypatch, label, replacement):
    monkeypatch.setattr(ci_skip_summary, "_skip_class", replacement)
    problems = _line_problems(_output(tmp_path, _MIXED))
    assert problems, label


def test_the_line_check_names_a_variant_that_prints_an_unvalidated_test_name(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_skip_summary, "_test_module", lambda classname, name: classname or name)
    problems = _line_problems(_output(tmp_path, _report(_case(f"{_PATH}", "test_x", _skip("x")), _case("tests.t&#10;::error::pwned", "test_x", _skip("y")))))
    assert problems
