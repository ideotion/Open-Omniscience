"""``scripts/diff_installed_versions.py`` compares the "Installed versions" blocks of two CI job logs (R349, R364, R380).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What this pins:

* the block is found in the shapes a reader meets it in: the raw job log with the runner's per-line timestamps (and the step's own shell echoed above
  it in ANSI colour, which must not be taken for the heading), the plain step summary, and the JSON that ``get_job_logs`` returns, each with or without a
  leading byte-order mark and with ``\\r\\n`` line ends;
* the comparison is by pip's own name rule (``typing_extensions`` is ``typing-extensions``, runs of ``-``, ``_`` and ``.`` alike) and says changed /
  added / removed / unchanged, and which of Python, the runner image and the kernel moved;
* a log that cannot be compared (no block, a block cut off by the end of the log or by the next step even when a later step prints a bare fence, an empty
  block, two blocks, an unreadable file, closed standard input, JSON of another shape) is an error that names OLD or NEW and what was seen, never a
  comparison against an empty list, which would read as "every package was removed"; a crash is exit 2 and never exit 1, which means "different";
* a line in the block that is not ``name==version`` and a name listed twice are reported, and make the answer "different" unless both sides carry the
  very same such lines;
* the exit status is 0 identical / 1 different / 2 not comparable, and both sides' errors are printed when both are bad;
* the script reads what the REAL step prints: the ``run`` text of the ``Installed versions`` step of ``.github/workflows/ci.yml`` (both jobs) is run
  under bash with a stub ``python``, and its output is parsed by the script, so a change to the step that the script cannot read fails here;
* and it reads what the runner really wrote: ``tests/fixtures/ci_logs/`` holds the tails of two real Core-only job logs (runs 40638055096 and
  40661391305, from ``get_job_logs``, the block and the lines around it, nothing edited), compared here.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "diff_installed_versions.py"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_FIXTURES = _ROOT / "tests" / "fixtures" / "ci_logs"

_spec = importlib.util.spec_from_file_location("diff_installed_versions", _SCRIPT)
assert _spec is not None and _spec.loader is not None
div = importlib.util.module_from_spec(_spec)
sys.modules["diff_installed_versions"] = div
_spec.loader.exec_module(div)

_ENV_OLD = "python 3.13.16, runner image ubuntu24 20261015.1.0, Linux 6.17.0-1020-azure"
_ENV_NEW = "python 3.13.16, runner image ubuntu24 20261023.334.3, Linux 6.17.0-1022-azure"


def _step_summary(env: str | None, pins: list[str], *, closing: bool = True, heading: bool = True) -> str:
    """The block as the step prints it (and as the step summary holds it)."""
    lines = ["### Installed versions"] if heading else []
    if env is not None:
        lines.append(env)
    lines += ["```", *pins]
    if closing:
        lines.append("```")
    return "\n".join(lines) + "\n"


def _job_log(block: str, *, stamp: str = "2026-10-28T10:21:01.8290247Z") -> str:
    """The block inside a realistic job log: timestamped lines, the step's shell echoed in ANSI colour first, the cleanup lines after it."""
    echoed = [
        "##[group]Run {",
        "\x1b[36;1m{\x1b[0m",
        '\x1b[36;1m  echo "### Installed versions"\x1b[0m',
        "\x1b[36;1m  python -m pip list --format=freeze\x1b[0m",
        '\x1b[36;1m} | tee -a "$GITHUB_STEP_SUMMARY"\x1b[0m',
        "shell: /usr/bin/bash -e {0}",
        "##[endgroup]",
    ]
    lines = ["2026-10-28T10:20:59.0000000Z ===== 1 passed in 1.00s =====", *echoed, *block.splitlines(), "Post job cleanup.", "##[group]Run cleanup"]
    return "\n".join(f"{stamp} {line}" for line in lines) + "\n"


_OLD_PINS = ["pytest==9.1.0", "typing_extensions==4.14.0", "Jinja2==3.1.6", "requests==2.33.0", "oldpkg==1.0", "same-pkg==2.0"]
_NEW_PINS = ["pytest==9.2.0", "typing-extensions==4.15.0", "jinja2==3.1.6", "requests==2.33.0", "newpkg==0.1", "same.pkg==2.0"]


def _compare(old_text: str, new_text: str):
    old = div.read_block(old_text, "OLD (old)")
    new = div.read_block(new_text, "NEW (new)")
    return old, new, div.compare(old, new)


def _write(tmp_path: Path, name: str, text: str | bytes) -> str:
    path = tmp_path / name
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return str(path)


# --- finding the block -------------------------------------------------------------------------------------------------------------------------


def test_a_timestamped_job_log_is_read_and_the_coloured_echo_of_the_shell_is_not_taken_for_the_heading():
    block = div.read_block(_job_log(_step_summary(_ENV_NEW, _NEW_PINS)), "NEW (log)")
    assert block.environment == _ENV_NEW
    assert set(block.pins) == {"pytest", "typing-extensions", "jinja2", "requests", "newpkg", "same-pkg"}
    assert block.pins["typing-extensions"] == ("typing-extensions", "4.15.0")
    assert block.unparsed == [] and block.duplicates == []


def test_the_plain_step_summary_and_the_log_give_the_same_block():
    plain = div.read_block(_step_summary(_ENV_NEW, _NEW_PINS), "x")
    logged = div.read_block(_job_log(_step_summary(_ENV_NEW, _NEW_PINS)), "x")
    assert plain.pins == logged.pins and plain.environment == logged.environment


@pytest.mark.parametrize(
    "shape",
    ["plain summary", "timestamped log", "json wrapper", "json wrapper whose content starts with a mark", "plain summary with windows line ends"],
)
def test_a_leading_byte_order_mark_does_not_hide_the_block(shape):
    """A summary saved with a mark starts with it before the heading itself, and so does a raw log before its first timestamp."""
    summary = _step_summary(_ENV_NEW, _NEW_PINS)
    text = {
        "plain summary": "﻿" + summary,
        "timestamped log": "﻿" + _job_log(summary),
        "json wrapper": "﻿" + json.dumps({"logs_content": _job_log(summary)}),
        "json wrapper whose content starts with a mark": json.dumps({"logs_content": "﻿" + summary}),
        "plain summary with windows line ends": "﻿" + summary.replace("\n", "\r\n"),
    }[shape]
    block = div.read_block(text, "x")
    assert block.heading_line == (1 if "plain" in shape or "content" in shape else 9)
    assert block.environment == _ENV_NEW and block.pins["pytest"] == ("pytest", "9.2.0")


def test_windows_line_ends_in_a_timestamped_log_are_tolerated():
    block = div.read_block(_job_log(_step_summary(_ENV_NEW, _NEW_PINS)).replace("\n", "\r\n"), "x")
    assert block.environment == _ENV_NEW and len(block.pins) == 6


def test_the_get_job_logs_json_wrapper_is_unwrapped():
    wrapped = json.dumps({"logs_content": _job_log(_step_summary(_ENV_NEW, _NEW_PINS)), "returned_lines": 40, "total_lines": 5000})
    block = div.read_block(wrapped, "x")
    assert block.environment == _ENV_NEW and block.pins["pytest"] == ("pytest", "9.2.0")


def test_a_json_object_of_another_shape_is_an_error_naming_the_log():
    with pytest.raises(div.BlockError) as err:
        div.read_block(json.dumps({"something": "else"}), "NEW (n.json)")
    assert "NEW (n.json)" in str(err.value) and "logs_content" in str(err.value)


@pytest.mark.parametrize("text", ['["not", "an", "object"]', '"just a string"', "42"])
def test_json_that_is_not_an_object_is_searched_as_text_and_refused_for_having_no_block(text):
    with pytest.raises(div.BlockError) as err:
        div.read_block(text, "NEW (n.json)")
    assert str(err.value).startswith("NEW (n.json): no '### Installed versions' line")


def test_text_that_starts_with_a_brace_but_is_not_json_is_still_searched_as_a_log():
    text = "{ not json\n" + _step_summary(_ENV_NEW, _NEW_PINS)
    assert div.read_block(text, "x").pins["pytest"] == ("pytest", "9.2.0")


def test_deeply_nested_json_is_a_refusal_and_not_a_crash():
    with pytest.raises(div.BlockError) as err:
        div.read_block('{"a":' + "[" * 200_000, "NEW (deep.json)")
    assert str(err.value).startswith("NEW (deep.json): no '### Installed versions' line")


def test_a_block_without_an_environment_line_is_read_and_says_so():
    block = div.read_block(_step_summary(None, ["a==1"]), "x")
    assert block.environment is None and block.pins == {"a": ("a", "1")}


def test_blank_lines_inside_the_block_are_skipped_and_not_listed():
    block = div.read_block("### Installed versions\n" + _ENV_NEW + "\n```\na==1\n\n   \nb==2\n```\n", "x")
    assert set(block.pins) == {"a", "b"} and block.unparsed == []


def test_line_numbers_are_the_ones_grep_shows_even_when_a_line_holds_other_line_separators():
    """str.splitlines() also splits on form feeds, vertical tabs, U+2028 and a lone carriage return, so a reported line would not match grep -n."""
    noisy = ["progress\rbar", "a\x0cb", "c\x0bd", "e f", "g\x85h", "i j"]
    text = "\n".join(noisy) + "\n" + _step_summary(_ENV_NEW, ["a==1"])
    assert div.read_block(text, "x").heading_line == len(noisy) + 1


# --- the refusals --------------------------------------------------------------------------------------------------------------------------------


def test_a_log_without_the_heading_is_an_error_that_says_what_it_looked_at_and_why_it_may_be_missing():
    with pytest.raises(div.BlockError) as err:
        div.read_block("2026-10-28T10:00:00.0000000Z just some tail\nof a log\n", "OLD (tail.log)")
    text = str(err.value)
    assert text.startswith("OLD (tail.log): no '### Installed versions' line in 2 lines.")
    assert "last lines" in text


def test_a_log_that_holds_only_the_echo_of_the_step_s_script_says_so_instead_of_pretending_the_block_is_absent_without_a_trace():
    echo_only = "\n".join(f"2026-10-28T10:21:01.0000000Z {line}" for line in ['\x1b[36;1m  echo "### Installed versions"\x1b[0m', "shell: /usr/bin/bash -e {0}"])
    with pytest.raises(div.BlockError) as err:
        div.read_block(echo_only, "NEW (echo.log)")
    text = str(err.value)
    assert "1 other lines contain that text but not as a line of their own (the first, at line 1:" in text and "echoes the step's script" in text


def test_a_block_cut_off_before_its_closing_fence_is_an_error_not_a_short_list():
    with pytest.raises(div.BlockError) as err:
        div.read_block(_step_summary(_ENV_NEW, ["a==1", "b==2"], closing=False), "NEW (cut.log)")
    text = str(err.value)
    assert text.startswith("NEW (cut.log): ") and "cut off" in text and "after 2 package lines" in text


_NEXT_STEP_THAT_PRINTS_A_FENCE = ["##[group]Run python scripts/report.py", "### Report", "```", "ok", "```", "Post job cleanup."]


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param(_NEXT_STEP_THAT_PRINTS_A_FENCE, id="a later step prints a bare fence"),
        pytest.param(["Post job cleanup.", "```", "```"], id="the cleanup line comes first"),
        pytest.param(["##[endgroup]", "```"], id="the runner closes a group"),
    ],
)
def test_a_block_cut_off_by_the_next_step_is_refused_even_when_a_later_line_is_a_fence(tail):
    """`pip list` dying inside the step's braces still leaves the step green (`bash -e` without pipefail, tee exits 0): the block ends early, no fence."""
    cut = ["### Installed versions", _ENV_NEW, "```", "a==1", "ERROR: pip failed", *tail]
    with pytest.raises(div.BlockError) as err:
        div.read_block("\n".join(cut) + "\n", "OLD (cut.log)")
    text = str(err.value)
    assert text.startswith("OLD (cut.log): the block at line 1 is cut off: line 6 (") and "before any closing ```" in text
    assert "after 1 package lines" in text


def test_the_cut_off_block_is_not_compared_against_a_complete_one(tmp_path, capsys):
    old = _write(tmp_path, "old.log", "\n".join(["### Installed versions", _ENV_NEW, "```", "a==1", *_NEXT_STEP_THAT_PRINTS_A_FENCE]) + "\n")
    new = _write(tmp_path, "new.log", _step_summary(_ENV_NEW, ["a==1", "b==2", "c==3"]))
    assert div.main([old, new]) == 2
    out = capsys.readouterr()
    assert out.out == "" and out.err.startswith(f"OLD ({old}): the block at line 1 is cut off")


def test_an_empty_block_is_an_error_not_every_package_removed():
    with pytest.raises(div.BlockError) as err:
        div.read_block(_step_summary(_ENV_NEW, []), "NEW (empty.log)")
    assert "NEW (empty.log)" in str(err.value) and "lists no name==version line" in str(err.value)


def test_a_block_whose_only_lines_are_not_pins_is_an_error_that_counts_them():
    with pytest.raises(div.BlockError) as err:
        div.read_block(_step_summary(_ENV_NEW, ["WARNING: something", "pip is out of date"]), "x")
    assert "2 other lines" in str(err.value)


def test_a_heading_with_nothing_after_it_is_an_error_that_says_the_log_ends():
    with pytest.raises(div.BlockError) as err:
        div.read_block("### Installed versions\n", "x")
    assert "no opening ```" in str(err.value) and "the log ends there" in str(err.value)


def test_an_environment_line_with_no_fence_after_it_is_an_error_that_says_what_came_instead():
    with pytest.raises(div.BlockError) as err:
        div.read_block("### Installed versions\n" + _ENV_NEW + "\npytest==9.2.0\n", "x")
    assert "no opening ```" in str(err.value) and "the next line is 'pytest==9.2.0'" in str(err.value)


def test_two_blocks_in_one_log_are_an_error_that_lists_where_they_are():
    one = _step_summary(_ENV_NEW, _NEW_PINS)
    with pytest.raises(div.BlockError) as err:
        div.read_block(one + "\n" + one, "NEW (both.log)")
    text = str(err.value)
    assert "NEW (both.log)" in text and "2 blocks" in text and "at lines 1," in text


_REFUSED = {
    "no heading": "just a log\n",
    "echo only": 'echo "### Installed versions"\n',
    "two blocks": _step_summary(_ENV_NEW, ["a==1"]) * 2,
    "no opening fence": "### Installed versions\n" + _ENV_NEW + "\na==1\n",
    "log ends after the heading": "### Installed versions\n",
    "cut off by the end of the log": _step_summary(_ENV_NEW, ["a==1"], closing=False),
    "cut off by the next step": "### Installed versions\n" + _ENV_NEW + "\n```\na==1\n##[group]Run x\n```\n",
    "empty block": _step_summary(_ENV_NEW, []),
    "no pin in the block": _step_summary(_ENV_NEW, ["WARNING: x"]),
    "json of another shape": json.dumps({"logs": []}),
}


@pytest.mark.parametrize("why", sorted(_REFUSED))
def test_every_refusal_names_the_log_it_refuses(why):
    with pytest.raises(div.BlockError) as err:
        div.read_block(_REFUSED[why], "OLD (the-log.txt)")
    assert str(err.value).startswith("OLD (the-log.txt): "), str(err.value)


# --- the comparison ------------------------------------------------------------------------------------------------------------------------------


def test_changed_added_removed_and_unchanged_are_told_apart_by_pips_name_rule():
    _old, _new, diff = _compare(_step_summary(_ENV_OLD, _OLD_PINS), _step_summary(_ENV_NEW, _NEW_PINS))
    assert diff.changed == [("pytest", "9.1.0", "9.2.0"), ("typing-extensions", "4.14.0", "4.15.0")]
    assert diff.added == [("newpkg", "0.1")]
    assert diff.removed == [("oldpkg", "1.0")]
    # Jinja2 / jinja2, requests and same-pkg / same.pkg are the same package at the same version
    assert diff.unchanged == 3
    assert not diff.same


@pytest.mark.parametrize(
    ("old_name", "new_name"),
    [("Foo__Bar", "foo-bar"), ("a--b", "a_.b"), ("zope.interface", "Zope_Interface"), ("a.-_b", "a-b"), ("A", "a")],
)
def test_runs_of_dash_underscore_and_dot_are_one_separator_and_case_is_ignored(old_name, new_name):
    diff = _compare(_step_summary(_ENV_NEW, [f"{old_name}==1"]), _step_summary(_ENV_NEW, [f"{new_name}==1"]))[2]
    assert diff.same and diff.unchanged == 1


def test_names_that_differ_beyond_separators_and_case_are_different_packages():
    diff = _compare(_step_summary(_ENV_NEW, ["ab==1"]), _step_summary(_ENV_NEW, ["a-b==1"]))[2]
    assert diff.added == [("a-b", "1")] and diff.removed == [("ab", "1")]


def test_a_name_is_shown_the_way_the_new_log_prints_it_and_removed_ones_the_way_the_old_log_does():
    _old, _new, diff = _compare(_step_summary(_ENV_OLD, ["Foo_Bar==1", "Gone_Pkg==1"]), _step_summary(_ENV_OLD, ["foo-bar==2"]))
    assert diff.changed == [("foo-bar", "1", "2")]
    assert diff.removed == [("Gone_Pkg", "1")]


@pytest.mark.parametrize("version", ["1.0+local", "2!1.0", "1.0.post1", "1.0rc1"])
def test_versions_in_any_pep_440_form_are_compared_as_printed(version):
    diff = _compare(_step_summary(_ENV_NEW, [f"a=={version}"]), _step_summary(_ENV_NEW, ["a==1.0"]))[2]
    assert diff.changed == [("a", version, "1.0")]


def test_the_environment_line_is_compared_field_by_field():
    _old, _new, diff = _compare(_step_summary(_ENV_OLD, ["a==1"]), _step_summary(_ENV_NEW, ["a==1"]))
    assert diff.environment == [
        ("runner image", "ubuntu24 20261015.1.0", "ubuntu24 20261023.334.3"),
        ("kernel", "Linux 6.17.0-1020-azure", "Linux 6.17.0-1022-azure"),
    ]
    assert not diff.same


def test_a_python_change_alone_is_a_difference():
    old = _step_summary("python 3.13.15, runner image x 1, Linux 6", ["a==1"])
    new = _step_summary("python 3.13.16, runner image x 1, Linux 6", ["a==1"])
    assert _compare(old, new)[2].environment == [("python", "3.13.15", "3.13.16")]


def test_an_environment_line_that_is_not_in_the_step_s_shape_is_compared_as_a_whole():
    diff = _compare(_step_summary("something else entirely", ["a==1"]), _step_summary("something different", ["a==1"]))[2]
    assert diff.environment == [("environment line", "something else entirely", "something different")]
    same = _compare(_step_summary("something else entirely", ["a==1"]), _step_summary("something else entirely", ["a==1"]))[2]
    assert same.same


def test_a_line_in_the_step_s_shape_against_one_that_is_not_is_reported_as_what_was_printed():
    """The old report said `(not printed)` for a line that had been printed in another shape."""
    diff = _compare(_step_summary("something else entirely", ["a==1"]), _step_summary(_ENV_NEW, ["a==1"]))[2]
    assert diff.environment == [("environment line", "something else entirely", _ENV_NEW)]


def test_a_missing_environment_line_is_named_as_not_printed():
    diff = _compare(_step_summary(None, ["a==1"]), _step_summary(_ENV_NEW, ["a==1"]))[2]
    assert diff.environment == [("environment line", "(not printed)", _ENV_NEW)]
    both = _compare(_step_summary(None, ["a==1"]), _step_summary(None, ["a==1"]))[2]
    assert both.same


def test_identical_blocks_are_the_same_and_the_report_says_so():
    old, new, diff = _compare(_step_summary(_ENV_NEW, _NEW_PINS), _job_log(_step_summary(_ENV_NEW, _NEW_PINS)))
    assert diff.same and diff.unchanged == 6
    report = div.render(old, new, diff)
    assert "environment: unchanged" in report
    assert "packages: 0 changed, 0 added, 0 removed, 6 unchanged" in report
    assert report.endswith("no difference in the environment line or in any package version")


def test_the_report_lists_every_change_with_no_cap():
    many_old = [f"pkg{i:04d}==1" for i in range(500)]
    many_new = [f"pkg{i:04d}==2" for i in range(500)]
    old, new, diff = _compare(_step_summary(_ENV_NEW, many_old), _step_summary(_ENV_NEW, many_new))
    report = div.render(old, new, diff)
    assert len(diff.changed) == 500
    assert "  pkg0000 1 -> 2" in report and "  pkg0499 1 -> 2" in report
    assert "..." not in report


@pytest.mark.parametrize(
    "line",
    ["a==1 extra", "a>=1", "a === 1", "a @ file:///w/a-1.0-py3-none-any.whl", "-e git+https://example.invalid/a#egg=a", "a==", "==1"],
)
def test_only_name_equals_version_is_a_pin_and_anything_else_is_listed(line):
    block = div.read_block(_step_summary(_ENV_NEW, ["keep==1", line]), "x")
    assert block.pins == {"keep": ("keep", "1")} and block.unparsed == [line]


def test_unparsed_lines_and_a_name_listed_twice_are_reported_and_not_dropped():
    old = _step_summary(_ENV_NEW, ["a==1", "WARNING: odd line", "a==9", "b @ file:///x"])
    new = _step_summary(_ENV_NEW, ["a==1"])
    old_block, new_block, diff = _compare(old, new)
    assert old_block.unparsed == ["WARNING: odd line", "b @ file:///x"]
    assert old_block.duplicates == ["a"]
    assert old_block.pins["a"] == ("a", "1"), "the first listing is kept"
    report = div.render(old_block, new_block, diff)
    assert "OLD: 2 lines in the block are not name==version and were not compared as packages:" in report
    assert "  WARNING: odd line" in report and "  b @ file:///x" in report
    assert "OLD: a name listed twice (the first was kept): a" in report


@pytest.mark.parametrize(
    ("old_pins", "new_pins"),
    [
        pytest.param(["a==1", "b @ file:///w/b-1.0-py3-none-any.whl"], ["a==1", "b @ file:///w/b-2.0-py3-none-any.whl"], id="a direct reference that moved"),
        pytest.param(["a==1", "b @ file:///w/b-1.0-py3-none-any.whl"], ["a==1"], id="a direct reference on one side only"),
        pytest.param(["a==1"], ["a==1", "b @ file:///w/b-1.0-py3-none-any.whl"], id="a direct reference on the other side only"),
        pytest.param(["a==1", "A==9"], ["a==1"], id="a name listed twice on one side"),
        pytest.param(["a==1"], ["a==1", "a==1"], id="a name listed twice on the other side, the same version"),
    ],
)
def test_what_could_not_be_compared_makes_the_answer_different_and_is_never_reported_as_no_difference(old_pins, new_pins, tmp_path, capsys):
    old = _write(tmp_path, "old.log", _step_summary(_ENV_NEW, old_pins))
    new = _write(tmp_path, "new.log", _step_summary(_ENV_NEW, new_pins))
    assert div.main([old, new]) == 1
    out = capsys.readouterr().out
    assert "not compared: " in out and "no difference" not in out


def test_the_same_lines_that_are_not_pins_on_both_sides_do_not_make_a_difference(tmp_path, capsys):
    extra = ["WARNING: pip is out of date", "b @ file:///w/b-1.0-py3-none-any.whl"]
    old = _write(tmp_path, "old.log", _step_summary(_ENV_NEW, ["a==1", *extra]))
    new = _write(tmp_path, "new.log", _step_summary(_ENV_NEW, [extra[1], "a==1", extra[0]]))
    assert div.main([old, new]) == 0
    out = capsys.readouterr().out
    assert "no difference" in out and "were not compared as packages" in out


# --- the command line ----------------------------------------------------------------------------------------------------------------------------


def test_main_prints_the_report_and_exits_1_when_the_environments_differ(tmp_path, capsys):
    old = _write(tmp_path, "old.log", _job_log(_step_summary(_ENV_OLD, _OLD_PINS)))
    new = _write(tmp_path, "new.log", _job_log(_step_summary(_ENV_NEW, _NEW_PINS)))
    assert div.main([old, new]) == 1
    out = capsys.readouterr()
    assert out.err == ""
    assert "packages: 2 changed, 1 added, 1 removed, 3 unchanged" in out.out
    assert "  pytest 9.1.0 -> 9.2.0" in out.out
    assert "added (only in NEW):\n  newpkg==0.1" in out.out
    assert "removed (only in OLD):\n  oldpkg==1.0" in out.out


def test_the_report_names_both_logs_and_their_sizes():
    old, new, diff = _compare(_step_summary(_ENV_OLD, _OLD_PINS), _job_log(_step_summary(_ENV_NEW, _NEW_PINS)))
    report = div.render(old, new, diff)
    assert report.splitlines()[0].startswith("OLD (old): block at line 1, 6 packages; python 3.13.16")
    assert report.splitlines()[1].startswith("NEW (new): block at line 9, 6 packages; python 3.13.16")


def test_main_exits_0_when_they_are_identical(tmp_path, capsys):
    one = _write(tmp_path, "one.log", _step_summary(_ENV_NEW, _NEW_PINS))
    two = _write(tmp_path, "two.log", _job_log(_step_summary(_ENV_NEW, _NEW_PINS)))
    assert div.main([one, two]) == 0
    assert "no difference" in capsys.readouterr().out


def _stdin(monkeypatch, data: bytes) -> None:
    """Standard input as the interpreter has it: a text wrapper over bytes that decodes strictly."""
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="strict"))


def test_main_reads_one_side_from_standard_input(tmp_path, capsys, monkeypatch):
    old = _write(tmp_path, "old.log", _step_summary(_ENV_OLD, _OLD_PINS))
    _stdin(monkeypatch, _step_summary(_ENV_NEW, _NEW_PINS).encode("utf-8"))
    assert div.main([old, "-"]) == 1
    out = capsys.readouterr().out
    assert "\nNEW (<stdin>): block at line 1, 6 packages;" in out and "  pytest 9.1.0 -> 9.2.0" in out


def test_bytes_that_are_not_utf8_are_replaced_on_both_routes_and_never_crash(tmp_path, capsys, monkeypatch):
    """A log carries arbitrary output from the tests; stdin that decodes strictly used to raise, and the file route used to replace."""
    noise = b"\xff\xfe progress \x80\n"
    body = b"### Installed versions\n" + _ENV_NEW.encode() + b"\n```\na==1\nb==2\xff\n```\n"
    old = _write(tmp_path, "old.log", noise + body)
    _stdin(monkeypatch, noise + body)
    assert div.main([old, "-"]) == 0
    out = capsys.readouterr()
    assert out.err == "" and "no difference" in out.out
    one = _write(tmp_path, "one.log", noise + body.replace(b"b==2\xff", b"b==2"))
    assert div.main([old, one]) == 1
    assert "b 2� -> 2" in capsys.readouterr().out


def test_closed_standard_input_is_a_named_refusal_and_not_a_traceback(tmp_path, capsys, monkeypatch):
    old = _write(tmp_path, "old.log", _step_summary(_ENV_OLD, _OLD_PINS))
    monkeypatch.setattr(sys, "stdin", None)
    assert div.main([old, "-"]) == 2
    out = capsys.readouterr()
    assert out.out == "" and out.err.strip() == "NEW (<stdin>): standard input is not open"


def test_main_reports_both_sides_when_both_cannot_be_read_and_exits_2(tmp_path, capsys):
    tail = _write(tmp_path, "tail.log", "2026-10-28T10:00:00.0000000Z only the tail of a log\n")
    missing = str(tmp_path / "missing.log")
    assert div.main([tail, missing]) == 2
    out = capsys.readouterr()
    assert out.out == ""
    lines = out.err.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(f"OLD ({tail}): no '### Installed versions' line")
    assert re.fullmatch(re.escape(f"NEW ({missing}): cannot be read (") + r".+\)", lines[1]), lines[1]


def test_a_path_that_starts_with_its_own_side_name_still_gets_the_side_prefix(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    good = _write(tmp_path, "good.log", _step_summary(_ENV_NEW, _NEW_PINS))
    assert div.main([good, "NEW-red.log"]) == 2
    assert capsys.readouterr().err.startswith("NEW (NEW-red.log): cannot be read")


def test_a_directory_is_an_unreadable_source_and_not_a_comparison(tmp_path, capsys):
    good = _write(tmp_path, "good.log", _step_summary(_ENV_NEW, _NEW_PINS))
    assert div.main([good, str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith(f"NEW ({tmp_path}): cannot be read")


def test_main_exits_2_on_a_cut_off_block_and_prints_no_comparison(tmp_path, capsys):
    old = _write(tmp_path, "old.log", _step_summary(_ENV_OLD, _OLD_PINS))
    new = _write(tmp_path, "new.log", _step_summary(_ENV_NEW, _NEW_PINS, closing=False))
    assert div.main([old, new]) == 2
    out = capsys.readouterr()
    assert out.out == "" and "NEW (" in out.err and "cut off" in out.err


def test_a_crash_while_reading_is_exit_2_and_named_never_exit_1(tmp_path, capsys, monkeypatch):
    """Python exits 1 on an uncaught exception, which is the status for "the two environments differ"."""
    one = _write(tmp_path, "one.log", _step_summary(_ENV_NEW, _NEW_PINS))

    def boom(text, label):
        raise ValueError("boom")

    monkeypatch.setattr(div, "read_block", boom)
    assert div.main([one, one]) == 2
    err = capsys.readouterr().err.splitlines()
    assert err == [f"OLD ({one}): could not be compared (ValueError: boom)", f"NEW ({one}): could not be compared (ValueError: boom)"]


def test_a_crash_while_comparing_or_rendering_is_exit_2_and_named_never_exit_1(tmp_path, capsys, monkeypatch):
    one = _write(tmp_path, "one.log", _step_summary(_ENV_NEW, _NEW_PINS))

    def boom(*_args):
        raise RuntimeError("no report")

    monkeypatch.setattr(div, "render", boom)
    assert div.main([one, one]) == 2
    out = capsys.readouterr()
    assert out.out == "" and out.err.strip() == "the two blocks could not be compared (RuntimeError: no report)"


@pytest.mark.parametrize("argv", [[], ["only-one"], ["a", "b", "c"], ["-", "-"]])
def test_main_wants_exactly_two_sources_and_at_most_one_stdin(argv, capsys):
    assert div.main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_the_script_runs_as_a_program_with_standard_python(tmp_path):
    old = _write(tmp_path, "old.log", _step_summary(_ENV_OLD, _OLD_PINS))
    new = _write(tmp_path, "new.log", _step_summary(_ENV_NEW, _NEW_PINS))
    done = subprocess.run([sys.executable, "-I", str(_SCRIPT), old, new], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 1 and done.stderr == ""
    assert done.stdout.startswith(f"OLD ({old}): block at line 1, 6 packages; ")


def test_the_script_run_as_a_program_reads_real_bytes_from_a_pipe_and_closed_input_is_exit_2(tmp_path):
    old = _write(tmp_path, "old.log", _step_summary(_ENV_OLD, _OLD_PINS))
    piped = subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), old, "-"],
        input=b"\xff\n" + _step_summary(_ENV_NEW, _NEW_PINS).encode("utf-8"),
        capture_output=True,
        timeout=60,
        check=False,
        env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
    )
    assert piped.returncode == 1, piped.stderr
    closed = subprocess.run([sys.executable, "-I", str(_SCRIPT), old, "-"], stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
    assert closed.returncode == 2 and closed.stdout == b""
    assert closed.stderr.decode("utf-8").startswith("NEW (<stdin>): no '### Installed versions' line in 0 lines")


def test_the_script_imports_only_the_standard_library():
    """It is run from a bare interpreter in a CI log reader's sandbox; the venv that runs this test has more installed than that."""
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported, "the scan found no import at all"
    assert imported <= set(sys.stdlib_module_names), sorted(imported - set(sys.stdlib_module_names))


# --- what the runner really wrote ----------------------------------------------------------------------------------------------------------------

_REAL_OLD = _FIXTURES / "core-only-run-40638055096.txt"
_REAL_NEW = _FIXTURES / "core-only-run-40661391305.txt"


def test_the_two_real_core_only_tails_have_the_same_packages_and_a_different_environment(capsys):
    """MEASURED on the runs of 28 Oct 2026: 87 packages each, none different, while Python, the runner image and the kernel all moved."""
    assert div.main([str(_REAL_OLD), str(_REAL_NEW)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith(": block at line 2, 87 packages; python 3.13.17, runner image ubuntu24 20261026.354.1, Linux 7.0.0-1017-azure")
    assert out[1].endswith(": block at line 2, 87 packages; python 3.13.16, runner image ubuntu24 20261023.334.3, Linux 6.17.0-1022-azure")
    assert out[2] == (
        "environment: python 3.13.17 -> 3.13.16; runner image ubuntu24 20261026.354.1 -> ubuntu24 20261023.334.3; kernel Linux 7.0.0-1017-azure -> Linux 6.17.0-1022-azure"
    )
    assert out[3] == "packages: 0 changed, 0 added, 0 removed, 87 unchanged"
    assert len(out) == 4


def test_a_real_tail_against_itself_is_identical_and_in_the_json_wrapper_too(tmp_path, capsys):
    text = _REAL_NEW.read_text(encoding="utf-8")
    wrapped = _write(tmp_path, "wrapped.json", json.dumps({"job_id": 122725010413, "logs_content": text, "message": "Job logs content retrieved successfully"}))
    assert div.main([str(_REAL_NEW), wrapped]) == 0
    assert "no difference" in capsys.readouterr().out


def test_a_real_tail_with_a_package_moved_by_hand_names_each_kind_of_change(tmp_path, capsys):
    text = _REAL_OLD.read_text(encoding="utf-8")
    edited = text.replace("pytest==9.2.0", "pytest==9.1.0").replace("requests==2.34.2", "Requests==2.34.3")
    edited = "".join(line for line in edited.splitlines(keepends=True) if "wrapt==" not in line)
    old = _write(tmp_path, "edited.log", edited)
    assert div.main([old, str(_REAL_NEW)]) == 1
    out = capsys.readouterr().out
    assert "packages: 2 changed, 1 added, 0 removed, 84 unchanged" in out
    assert "  pytest 9.1.0 -> 9.2.0" in out and "  requests 2.34.3 -> 2.34.2" in out and "added (only in NEW):\n  wrapt==2.5.1" in out


def test_a_real_tail_cut_before_the_heading_or_inside_the_block_is_refused(tmp_path, capsys):
    lines = _REAL_NEW.read_text(encoding="utf-8").splitlines(keepends=True)
    before_heading = _write(tmp_path, "tail.log", "".join(lines[2:]))
    inside_block = _write(tmp_path, "cut.log", "".join(lines[:50]))
    assert div.main([before_heading, str(_REAL_NEW)]) == 2
    assert div.main([str(_REAL_OLD), inside_block]) == 2
    err = capsys.readouterr().err.splitlines()
    assert err[0].startswith(f"OLD ({before_heading}): no '### Installed versions' line in 91 lines")
    assert err[1].startswith(f"NEW ({inside_block}): the block at line 2 is cut off: the log ends after 46 package lines")


# --- it reads what the REAL step prints ---------------------------------------------------------------------------------------------------------


def _real_steps() -> list[tuple[str, str]]:
    jobs = yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]
    found = []
    for job_name, job in jobs.items():
        for step in job.get("steps") or []:
            if str(step.get("name") or "").startswith("Installed versions"):
                found.append((job_name, str(step["run"])))
    return found


def test_the_real_step_is_in_the_jobs_the_script_is_for():
    assert [job for job, _run in _real_steps()] == ["test", "core-only"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="the step's shell is bash")
@pytest.mark.parametrize("job_name", ["test", "core-only"])
def test_the_output_of_the_real_step_is_read_by_the_script(job_name, tmp_path):
    """Run the step's own ``run`` text under bash with a stub ``python`` and a summary file, then parse what it printed (stdout and the summary)."""
    run = dict(_real_steps())[job_name]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python"
    stub.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *platform*) echo 3.13.16 ;;\n"
        '  *"pip list --format=freeze"*) printf "%s\\n" "pytest==9.2.0" "typing_extensions==4.15.0" "Jinja2==3.1.6" ;;\n'
        '  *) echo "stub python: unexpected arguments: $*" >&2; exit 97 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    summary = tmp_path / "summary.md"
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "GITHUB_STEP_SUMMARY": str(summary), "ImageOS": "ubuntu24", "ImageVersion": "20261023.334.3"}
    done = subprocess.run(["bash", "-e", "-c", run], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    for label, text in (("stdout", done.stdout), ("step summary", summary.read_text(encoding="utf-8"))):
        block = div.read_block(text, label)
        assert block.heading_line == 1
        assert block.environment is not None
        assert block.environment.startswith("python 3.13.16, runner image ubuntu24 20261023.334.3, Linux ")
        assert block.pins == {
            "pytest": ("pytest", "9.2.0"),
            "typing-extensions": ("typing_extensions", "4.15.0"),
            "jinja2": ("Jinja2", "3.1.6"),
        }
        assert block.unparsed == [] and block.duplicates == []
        assert set(div._environment_fields(block.environment) or {}) == {"python", "runner image", "kernel"}
    # the same step on a runner that moved: the script names what moved
    env2 = dict(env, ImageVersion="20261101.1.0")
    done2 = subprocess.run(["bash", "-e", "-c", run], capture_output=True, text=True, encoding="utf-8", env=env2, timeout=60, check=False)
    assert done2.returncode == 0, done2.stderr
    assert div.compare(div.read_block(done.stdout, "a"), div.read_block(done2.stdout, "b")).environment == [
        ("runner image", "ubuntu24 20261023.334.3", "ubuntu24 20261101.1.0")
    ]


@pytest.mark.skipif(shutil.which("bash") is None, reason="the step's shell is bash")
def test_the_real_step_without_the_runner_variables_prints_unknown_and_is_still_read(tmp_path):
    run = dict(_real_steps())["test"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python"
    stub.write_text('#!/bin/sh\ncase "$*" in\n  *platform*) echo 3.13.16 ;;\n  *) echo "a==1" ;;\nesac\n', encoding="utf-8")
    stub.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    done = subprocess.run(["bash", "-e", "-c", run], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    block = div.read_block(done.stdout, "x")
    fields = div._environment_fields(block.environment)
    assert fields is not None and fields["runner image"] == "unknown unknown"
    assert block.pins == {"a": ("a", "1")}
