"""``scripts/diff_installed_versions.py`` compares the "Installed versions" blocks of two CI job logs (R349, R364, R380).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What this pins:

* the block is found in the shapes a reader meets it in: the raw job log with the runner's per-line timestamps (and the step's own shell echoed above
  it in ANSI colour, which must not be taken for the heading), the plain step summary, and the JSON that ``get_job_logs`` returns;
* the comparison is by pip's own name rule (``typing_extensions`` is ``typing-extensions``) and says changed / added / removed / unchanged, and which of
  Python, the runner image and the kernel moved;
* a log that cannot be compared (no block, a block cut off, an empty block, two blocks, an unreadable file, JSON of another shape) is an error that
  names OLD or NEW and what was seen, never a comparison against an empty list, which would read as "every package was removed";
* a line in the block that is not ``name==version`` and a name listed twice are reported, not dropped;
* the exit status is 0 identical / 1 different / 2 not comparable, and both sides' errors are printed when both are bad;
* the script reads what the REAL step prints: the ``run`` text of the ``Installed versions`` step of ``.github/workflows/ci.yml`` (both jobs) is run
  under bash with a stub ``python``, and its output is parsed by the script, so a change to the step that the script cannot read fails here.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "diff_installed_versions.py"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"

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
        '\x1b[36;1m{\x1b[0m',
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


def test_a_byte_order_mark_and_windows_line_endings_are_tolerated():
    text = "﻿" + _job_log(_step_summary(_ENV_NEW, _NEW_PINS)).replace("\n", "\r\n")
    assert div.read_block(text, "x").pins["pytest"] == ("pytest", "9.2.0")


def test_the_get_job_logs_json_wrapper_is_unwrapped():
    wrapped = json.dumps({"logs_content": _job_log(_step_summary(_ENV_NEW, _NEW_PINS)), "returned_lines": 40, "total_lines": 5000})
    block = div.read_block(wrapped, "x")
    assert block.environment == _ENV_NEW and block.pins["pytest"] == ("pytest", "9.2.0")


def test_a_json_object_of_another_shape_is_an_error_naming_the_log():
    with pytest.raises(div.BlockError) as err:
        div.read_block(json.dumps({"something": "else"}), "NEW (n.json)")
    assert "NEW (n.json)" in str(err.value) and "logs_content" in str(err.value)


def test_text_that_starts_with_a_brace_but_is_not_json_is_still_searched_as_a_log():
    text = "{ not json\n" + _step_summary(_ENV_NEW, _NEW_PINS)
    assert div.read_block(text, "x").pins["pytest"] == ("pytest", "9.2.0")


def test_a_block_without_an_environment_line_is_read_and_says_so():
    block = div.read_block(_step_summary(None, ["a==1"]), "x")
    assert block.environment is None and block.pins == {"a": ("a", "1")}


# --- the refusals --------------------------------------------------------------------------------------------------------------------------------


def test_a_log_without_the_heading_is_an_error_that_says_what_it_looked_at_and_why_it_may_be_missing():
    with pytest.raises(div.BlockError) as err:
        div.read_block("2026-10-28T10:00:00.0000000Z just some tail\nof a log\n", "OLD (tail.log)")
    text = str(err.value)
    assert text.startswith("OLD (tail.log): no '### Installed versions' line in 2 lines")
    assert "last lines" in text


def test_a_block_cut_off_before_its_closing_fence_is_an_error_not_a_short_list():
    with pytest.raises(div.BlockError) as err:
        div.read_block(_step_summary(_ENV_NEW, ["a==1", "b==2"], closing=False), "NEW (cut.log)")
    assert "NEW (cut.log)" in str(err.value) and "cut off" in str(err.value) and "2 package lines" in str(err.value)


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


# --- the comparison ------------------------------------------------------------------------------------------------------------------------------


def test_changed_added_removed_and_unchanged_are_told_apart_by_pips_name_rule():
    _old, _new, diff = _compare(_step_summary(_ENV_OLD, _OLD_PINS), _step_summary(_ENV_NEW, _NEW_PINS))
    assert diff.changed == [("pytest", "9.1.0", "9.2.0"), ("typing-extensions", "4.14.0", "4.15.0")]
    assert diff.added == [("newpkg", "0.1")]
    assert diff.removed == [("oldpkg", "1.0")]
    # Jinja2 / jinja2, requests and same-pkg / same.pkg are the same package at the same version
    assert diff.unchanged == 3
    assert not diff.same


def test_a_name_is_shown_the_way_the_new_log_prints_it_and_removed_ones_the_way_the_old_log_does():
    _old, _new, diff = _compare(_step_summary(_ENV_OLD, ["Foo_Bar==1", "Gone_Pkg==1"]), _step_summary(_ENV_OLD, ["foo-bar==2"]))
    assert diff.changed == [("foo-bar", "1", "2")]
    assert diff.removed == [("Gone_Pkg", "1")]


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


def test_an_environment_line_that_is_not_in_the_step_s_shape_is_compared_as_a_whole_and_a_missing_one_is_named():
    diff = _compare(_step_summary("something else entirely", ["a==1"]), _step_summary("something different", ["a==1"]))[2]
    assert diff.environment == [("environment line", "something else entirely", "something different")]
    diff = _compare(_step_summary(None, ["a==1"]), _step_summary(_ENV_NEW, ["a==1"]))[2]
    assert [what for what, _was, _now in diff.environment] == ["python", "runner image", "kernel"]
    assert all(was == "(not printed)" for _what, was, _now in diff.environment)


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


def test_unparsed_lines_and_a_name_listed_twice_are_reported_and_not_dropped():
    old = _step_summary(_ENV_NEW, ["a==1", "WARNING: odd line", "a==9", "b @ file:///x"])
    new = _step_summary(_ENV_NEW, ["a==1"])
    old_block, new_block, diff = _compare(old, new)
    assert old_block.unparsed == ["WARNING: odd line", "b @ file:///x"]
    assert old_block.duplicates == ["a"]
    assert old_block.pins["a"] == ("a", "1"), "the first listing is kept"
    report = div.render(old_block, new_block, diff)
    assert "OLD: 2 lines in the block are not name==version and were not compared:" in report
    assert "  WARNING: odd line" in report and "  b @ file:///x" in report
    assert "OLD: a name listed twice (the first was kept): a" in report


def test_the_report_names_both_logs_and_their_sizes():
    old, new, diff = _compare(_step_summary(_ENV_OLD, _OLD_PINS), _job_log(_step_summary(_ENV_NEW, _NEW_PINS)))
    report = div.render(old, new, diff)
    assert report.splitlines()[0].startswith("OLD (old): block at line 1, 6 packages; python 3.13.16")
    assert report.splitlines()[1].startswith("NEW (new): block at line 9, 6 packages; python 3.13.16")


# --- the command line ----------------------------------------------------------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


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


def test_main_exits_0_when_they_are_identical(tmp_path, capsys):
    one = _write(tmp_path, "one.log", _step_summary(_ENV_NEW, _NEW_PINS))
    two = _write(tmp_path, "two.log", _job_log(_step_summary(_ENV_NEW, _NEW_PINS)))
    assert div.main([one, two]) == 0
    assert "no difference" in capsys.readouterr().out


def test_main_reads_one_side_from_standard_input(tmp_path, capsys, monkeypatch):
    import io

    old = _write(tmp_path, "old.log", _step_summary(_ENV_OLD, _OLD_PINS))
    monkeypatch.setattr(sys, "stdin", io.StringIO(_step_summary(_ENV_NEW, _NEW_PINS)))
    assert div.main([old, "-"]) == 1
    out = capsys.readouterr().out
    assert "\nNEW (<stdin>): block at line 1, 6 packages;" in out and "  pytest 9.1.0 -> 9.2.0" in out


def test_main_reports_both_sides_when_both_cannot_be_read_and_exits_2(tmp_path, capsys):
    tail = _write(tmp_path, "tail.log", "2026-10-28T10:00:00.0000000Z only the tail of a log\n")
    missing = str(tmp_path / "missing.log")
    assert div.main([tail, missing]) == 2
    out = capsys.readouterr()
    assert out.out == ""
    lines = out.err.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(f"OLD ({tail}): no '### Installed versions' line")
    assert lines[1].startswith(f"NEW: {missing}: cannot be read")


def test_main_exits_2_on_a_cut_off_block_and_prints_no_comparison(tmp_path, capsys):
    old = _write(tmp_path, "old.log", _step_summary(_ENV_OLD, _OLD_PINS))
    new = _write(tmp_path, "new.log", _step_summary(_ENV_NEW, _NEW_PINS, closing=False))
    assert div.main([old, new]) == 2
    out = capsys.readouterr()
    assert out.out == "" and "NEW (" in out.err and "cut off" in out.err


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
        '  *platform*) echo 3.13.16 ;;\n'
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
        assert set(div._environment_fields(block.environment)) == {"python", "runner image", "kernel"}
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
    assert fields["runner image"] == "unknown unknown"
    assert block.pins == {"a": ("a", "1")}
