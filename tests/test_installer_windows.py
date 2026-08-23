"""
Guards for the Windows installer (install.ps1) and launcher (scripts/launch.cmd).

Two layers, because only one of them can run everywhere:

  * a real PowerShell *parse* of install.ps1 -- the equivalent of `bash -n` for
    install.sh -- which needs pwsh/powershell and is skipped when absent;
  * behavioural/static properties, which run on every platform.

Every static assertion reads COMMENT-STRIPPED source. install.ps1 documents the
traps it avoids (the Activate.ps1 execution-policy trap, winget's unreliable exit
code), so a naive substring check would be satisfied -- or defeated -- by the very
comment explaining the avoidance. That comment is what a future reader needs, so the
guard strips comments rather than the file dropping its explanations.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import ps_function_body, strip_ps_comments

REPO = Path(__file__).resolve().parents[1]
INSTALL_PS1 = REPO / "install.ps1"
LAUNCH_CMD = REPO / "scripts" / "launch.cmd"
QUICKSTART = REPO / "docs" / "QUICKSTART.md"


def _strip_cmd_comments(source: str) -> str:
    """Drop `rem` lines from a batch file."""
    return "\n".join(
        line for line in source.splitlines() if not line.strip().lower().startswith("rem ")
    )


@pytest.fixture(scope="module")
def ps1() -> str:
    return strip_ps_comments(INSTALL_PS1.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cmd() -> str:
    return _strip_cmd_comments(LAUNCH_CMD.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Syntax
# --------------------------------------------------------------------------- #
INSTALLER_TEST_SOURCE = Path(__file__).read_text(encoding="utf-8")


def _powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def test_the_powershell_gated_guards_actually_run_on_a_runner() -> None:
    """A skip is green, so nothing here said whether the behavioural guards execute.

    Three tests in this file need pwsh/powershell, and `ci.yml` never mentions either
    -- so on a runner without one they would skip silently and a green lane would say
    nothing about the .ps1 behaviour they exist to pin. On a developer machine a skip
    is the right answer and this skips too; on a runner it is a coverage hole, so say
    so there.
    """
    if os.environ.get("CI", "").strip().lower() not in {"1", "true"}:
        pytest.skip("developer machine -- pwsh is optional here")
    # Count the DECORATORS, not every line mentioning the probe -- this very line
    # would otherwise count itself and report one more guard than exists.
    gated = sum(
        1
        for line in INSTALLER_TEST_SOURCE.splitlines()
        if line.startswith("@pytest.mark.skipif(_powershell() is None")
    )
    assert _powershell() is not None, (
        f"no pwsh/powershell on this runner, so the {gated} behavioural .ps1 guards "
        "in this file skipped -- a green lane proves nothing about them. Either "
        "install PowerShell in the workflow or drop the gate."
    )


def test_the_bundled_interpreter_never_lands_inside_the_checkout(ps1: str) -> None:
    """It used to, and that deadlocked every machine that needed it.

    Section 2 created `$target\\.python-x64`; section 3 then found `$target` non-empty
    and not a git checkout and refused -- and `git clone` declines a non-empty
    directory anyway, so the checkout could never appear. Deleting the folder did not
    help: the next run recreated it. Reported from the field three runs in a row.
    """
    body = ps_function_body(ps1, "Get-VendoredRoot")
    assert "$target" not in body, (
        "the interpreter's home must not be derived from the checkout path"
    )
    assert "LOCALAPPDATA" in body, "per-user, no elevation, outside the checkout"
    assert "Install-PythonFromNuGet -Destination $script:VendoredRoot" in ps1, (
        "the download must land in that out-of-tree root"
    )
    assert "Install-PythonFromNuGet -Destination (Join-Path $target" not in ps1, (
        "writing it into the checkout is the deadlock"
    )


def test_uninstall_reclaims_the_out_of_tree_interpreter(ps1: str) -> None:
    """Moving it out of the checkout means removing the checkout no longer reclaims it.

    Sixty-odd MB of orphan otherwise, in a folder the user never chose. Both sites
    read the same function so the two paths cannot spell it differently.
    """
    start = ps1.index("if ($Uninstall) {")
    end = ps1.index("if ($Check) {", start)
    section = ps1[start:end]
    assert "Get-VendoredRoot" in section, (
        "uninstall must remove the interpreter it installed outside the checkout"
    )
    assert ps1.count("function Get-VendoredRoot") == 1, "one implementation, not two"


@pytest.mark.skipif(_powershell() is None, reason="needs pwsh/powershell")
def test_an_interpreter_left_in_the_checkout_is_moved_out_not_re_downloaded() -> None:
    """The state the field machines are already in, driven end to end.

    Both halves matter: the checkout must end up EMPTY so the clone can proceed, and
    the interpreter must survive the move -- deleting it would work too, and would
    cost every affected machine another download.
    """
    env = {
        **os.environ,
        "OO_INSTALL_PS1": str(INSTALL_PS1),
        "OO_BLOCK_START": "$script:VendoredRoot = Get-VendoredRoot",
        "OO_BLOCK_END": "# winget defaults to the machine",
    }
    out = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", _VENDOR_DRIVER],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert out.returncode == 0, out.stderr
    empty, moved, content = out.stdout.strip().splitlines()[-1].split("|")
    assert empty == "True", "the checkout must be left empty or the clone cannot run"
    assert moved == "True", "the interpreter must exist in its new home"
    assert content == "legacy", (
        "it must be the SAME interpreter -- re-downloading it is a worse fix"
    )


@pytest.mark.skipif(_powershell() is None, reason="needs pwsh/powershell to parse .ps1")
def test_install_ps1_parses():
    exe = _powershell()
    assert exe is not None
    script = (
        "$errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALL_PS1}',"
        "[ref]$null, [ref]$errors); "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.ToString() }; exit 1 }"
    )
    r = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"install.ps1 has parse errors:\n{r.stdout}\n{r.stderr}"


# --------------------------------------------------------------------------- #
# Properties that must hold on any platform
# --------------------------------------------------------------------------- #
def test_never_activates_the_venv(ps1: str):
    """Activate.ps1 is blocked by the default execution policy.

    Calling .venv\\Scripts\\python.exe by path sidesteps that whole failure class, so
    the installer must never reach for the activation script in executable code.
    """
    assert "Activate.ps1" not in ps1
    assert "Scripts\\python.exe" in ps1


def test_verifies_the_install_by_importing_the_real_app(ps1: str):
    """pip exiting 0 is not proof the app works; the import is (CI's own boot check)."""
    assert "from src.api.main import app" in ps1


def test_refreshes_path_after_a_winget_install(ps1: str):
    """A winget install leaves this session's PATH stale, so the next probe would miss it."""
    assert "Update-PathFromRegistry" in ps1
    body = ps_function_body(ps1, "Install-WingetPackage")
    assert "Update-PathFromRegistry" in body, "the winget helper must refresh PATH itself"


def test_winget_success_is_judged_by_capability_not_by_exit_code(ps1: str):
    """winget returns non-zero for benign outcomes, so the re-probe is the real gate."""
    body = ps_function_body(ps1, "Install-WingetPackage")
    assert "-AllowFailure" in body, "winget's exit code must not be fatal"
    # ...and the caller must re-probe rather than assume the install worked.
    after = ps1.split("Install-WingetPackage -Id 'Python.Python.3.13'", 1)[1]
    assert "Resolve-Python" in after.split("Write-Ok", 1)[0]


def test_python_floor_matches_pyproject(ps1: str):
    """Read the floor from the packaging source of truth so a bump reddens this."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    floor = re.search(r'requires-python\s*=\s*">=\s*([0-9.]+)"', pyproject)
    assert floor, "could not read requires-python from pyproject.toml"
    assert f"[version]'{floor.group(1)}'" in ps1


def test_clone_url_matches_pyproject(ps1: str):
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    url = re.search(r'Repository\s*=\s*"([^"]+)"', pyproject)
    assert url, "could not read the Repository URL from pyproject.toml"
    assert url.group(1) in ps1


def test_default_extras_match_install_sh(ps1: str):
    """The two installers must offer the same default set, or the platforms diverge."""
    sh = (REPO / "install.sh").read_text(encoding="utf-8")
    default = re.search(r'CHOSEN_EXTRAS="\$\{OO_COMPONENTS:-([a-z,]+)\}"', sh)
    assert default, "could not read the default extras from install.sh"
    assert f"$Extras = '{default.group(1)}'" in ps1


def test_extras_fallback_is_the_set_windows_ci_actually_installs(ps1: str):
    """The fallback may only claim an extra the Windows lane proves every run."""
    assert "$ProvenExtras = 'analysis'" in ps1
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    portability = ci.split("portability:", 1)[1].split("sqlcipher-smoke:", 1)[0]
    assert "windows-latest" in portability
    assert 'pip install -e ".[analysis,dev]"' in portability


def test_uninstall_never_deletes_data_without_confirmation(ps1: str):
    """Data loss is irreversible here: there is no passphrase recovery."""
    block = ps1.split("if ($Uninstall)", 1)[1].split("if ($Check)", 1)[0]
    removals = [line for line in block.splitlines() if "Remove-Item" in line and "dataPath" in line]
    assert removals, "expected the data folder removal to be present"
    confirm = block.split("Confirm-Action", 1)
    assert len(confirm) == 2, "the data deletion must sit behind Confirm-Action"
    # The confirmation must default to NO.
    assert "-DefaultYes $false" in confirm[1].split("Remove-Item", 1)[0]


def test_confirm_defaults_to_no_when_non_interactive(ps1: str):
    body = ps_function_body(ps1, "Confirm-Action")
    assert "IsInputRedirected" in body, "a redirected stdin must not be read as consent"


# --------------------------------------------------------------------------- #
# Launcher
# --------------------------------------------------------------------------- #
def test_launcher_targets_the_console_script_pyproject_defines(cmd: str):
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    script = re.search(r"^([a-z-]+)\s*=\s*\"src\.api\.main:main\"", pyproject, re.MULTILINE)
    assert script, "could not read the console script name from pyproject.toml"
    assert f"{script.group(1)}.exe" in cmd


def test_launcher_is_loopback_only(cmd: str):
    """The server must never be addressed off loopback (project non-negotiable §0.3)."""
    assert "127.0.0.1" in cmd
    for forbidden in ("0.0.0.0", "localhost:", "http://192.", "http://10."):
        assert forbidden not in cmd


def test_launcher_points_at_the_installer_that_exists(cmd: str):
    assert "install.ps1" in cmd
    assert INSTALL_PS1.is_file()


# --------------------------------------------------------------------------- #
# Docs
# --------------------------------------------------------------------------- #
def test_quickstart_documents_windows_and_its_limits():
    text = QUICKSTART.read_text(encoding="utf-8")
    assert "## C. On Windows 11 (PowerShell)" in text
    # The honest-status paragraph is the point of the section, not decoration.
    section = text.split("## C. On Windows 11 (PowerShell)", 1)[1].split("\n## ", 1)[0]
    assert "pytest lane" in section, "the section must state that the test suite does not pass"
    assert "no recovery" in section, "the passphrase warning must reach Windows readers"
    assert "install.ps1" in section


def test_quickstart_section_letters_are_unique_and_ordered():
    text = QUICKSTART.read_text(encoding="utf-8")
    letters = re.findall(r"^## ([A-Z])\. ", text, re.MULTILINE)
    assert letters == sorted(letters), f"section letters out of order: {letters}"
    assert len(letters) == len(set(letters)), f"duplicate section letter: {letters}"


def test_python_discovery_does_not_depend_on_path(ps1: str) -> None:
    """Discovery must consult the registry, not just PATH and a few guessed paths.

    Field failure this replaced: winget reported installing Python 3.13, the
    interpreter was on disk, and the script still dead-ended at "not resolvable" --
    through a reopened terminal AND a reboot, which rules out the stale-PATH cause the
    old message assumed. winget's Python package often leaves PATH untouched, so a
    PATH-only probe cannot see a perfectly good install. PEP 514's registry record is
    written by the installer itself and is what `py.exe` reads, so it answers
    regardless of the shell environment.
    """
    body = ps_function_body(ps1, "Resolve-Python")
    assert "Get-RegisteredPythonPaths" in body, (
        "Resolve-Python must consult the registry; PATH alone reproduces the field bug"
    )

    registry = ps_function_body(ps1, "Get-RegisteredPythonPaths")
    assert "SOFTWARE\\Python" in registry, "PEP 514 is the authoritative record"
    assert "InstallPath" in registry
    # ExecutablePath is exact when present; the key's default value is only the
    # directory, so reading one without the other misses half the installs.
    assert "ExecutablePath" in registry


def test_a_failed_python_bootstrap_prints_what_it_probed(ps1: str) -> None:
    """A dead end that says only "it did not work" can be neither acted on nor reported.

    The message this replaced named a website and nothing else: it told neither the
    operator nor the maintainer WHICH probe came up empty, so the only way forward was
    guessing. The diagnosis must also be CALLED, not merely defined -- a bare name
    search is satisfied by the definition alone, which is exactly how a dead
    diagnostic ships looking wired.
    """
    assert "function Show-PythonDiagnostics" in ps1
    assert ps1.count("Show-PythonDiagnostics") >= 2, (
        "Show-PythonDiagnostics is defined but never called"
    )
    assert re.search(
        r"Show-PythonDiagnostics\s*\n\s*Stop-WithError", ps1
    ), "the diagnosis must run at the failure path, immediately before giving up"


def test_the_probe_records_why_it_refused_an_interpreter(ps1: str) -> None:
    """A probe that answers only "no" sends the operator back for another round trip.

    Field failure this replaced: all three discovery paths found
    `...\\Python313-arm64\\python.exe` and the script still reported "no interpreter
    answers", with nothing saying which check refused it. The old body wrapped every
    path in one try/except returning $null, so "PowerShell threw" and "this is not a
    Python" were the same answer.

    PowerShell 5.1 makes that worse: with $ErrorActionPreference = 'Stop' a native
    command's stderr becomes a TERMINATING error even when redirected, so a working
    interpreter can be refused by the shell rather than by its own output. The probe
    must lower that for the duration of the call and record a reason on each exit.
    """
    body = ps_function_body(ps1, "Test-PythonCandidate")

    assert "$ErrorActionPreference = 'Continue'" in body, (
        "PS 5.1 turns native stderr into a terminating error under 'Stop'"
    )
    assert "finally" in body, "the caller's preference must be restored"

    # Every rejecting branch reports; the count is what stops one path staying silent.
    assert body.count("$script:PythonProbeLog +=") >= 5, (
        "each way of refusing an interpreter needs its own recorded reason"
    )

    diagnostics = ps_function_body(ps1, "Show-PythonDiagnostics")
    assert "$script:PythonProbeLog" in diagnostics, "the reasons must reach the operator"
    # ARM64 vs x64 decides which dependency wheels exist at all, so it is a fact the
    # report has to carry -- it is what identified the field machine.
    assert "PROCESSOR_ARCHITECTURE" in diagnostics


def test_no_code_handed_to_a_native_command_carries_a_double_quote(ps1: str) -> None:
    """PowerShell 5.1 strips embedded `"` on the way to a native command.

    Field failure this replaced: the probe read
    `print("%d.%d" % sys.version_info[:2])` and python received
    `print(%d.%d % sys.version_info[:2])` -- SyntaxError, on EVERY Windows machine,
    ARM64 and x64 alike. install.ps1 could therefore never find an interpreter at
    all, and nothing caught it because CI runs pytest and never executes this
    script.

    The durable rule is the one the fix relies on: a code string passed to a native
    `-c` takes no double quotes. Both of ours are written to need none.
    """
    for name in ("probe", "bootCheck"):
        match = re.search(rf"\${name}\s*=\s*'([^']*)'", ps1)
        assert match, f"${name} assignment not found"
        assert '"' not in match.group(1), (
            f"${name} carries a double quote; PowerShell 5.1 strips it and python "
            f"receives a syntax error"
        )


def test_the_probe_and_its_parser_agree_on_the_line_count(ps1: str) -> None:
    """Changing what the probe prints without changing the parser re-breaks discovery.

    The stub check and the executable's index are both derived from how many lines
    the probe emits, so they are pinned to it rather than to a literal that can
    quietly drift.
    """
    body = ps_function_body(ps1, "Test-PythonCandidate")
    match = re.search(r"\$probe\s*=\s*'([^']*)'", body)
    assert match, "probe assignment not found inside Test-PythonCandidate"
    printed = match.group(1).count("print(")
    assert printed >= 3, "major, minor and the executable path are all needed"

    assert re.search(rf"\$lines\.Count -lt {printed}\b", body), (
        f"the probe prints {printed} lines, so the Store-stub check must require {printed}"
    )
    assert f"$lines[{printed - 1}]" in body, (
        "the executable is the probe's last line; the parser must read that index"
    )


def test_the_probe_reads_the_interpreter_platform_not_the_machine(ps1: str) -> None:
    """`platform.machine()` inverts the ARM64 check; `sysconfig.get_platform()` does not.

    What decides whether pip finds a wheel is the interpreter's OWN build platform
    (`win-amd64` / `win-arm64`), which is what `sysconfig.get_platform()` reports.
    `platform.machine()` on Windows reports the MACHINE, so an x64 python running
    under ARM64 emulation -- exactly the configuration this fix installs -- answers
    ARM64, and every check built on it decides the opposite of the truth.

    Field failure this serves: cryptography, statsmodels and httptools publish no
    win_arm64 wheel, so an ARM64 interpreter sent pip to a Rust + MSVC source build
    that died on a machine with no toolchain.
    """
    body = ps_function_body(ps1, "Test-PythonCandidate")
    match = re.search(r"\$probe\s*=\s*'([^']*)'", body)
    assert match, "probe assignment not found"
    probe = match.group(1)
    assert "sysconfig.get_platform()" in probe, (
        "the probe must report the interpreter's own wheel platform"
    )
    assert "platform.machine" not in probe, (
        "platform.machine() reports the machine, not the interpreter -- it inverts "
        "the check for an emulated x64 python, which is the case that matters"
    )
    assert "Platform =" in body, "the probe's platform must reach the caller"


def test_every_python_install_names_the_x64_architecture(ps1: str) -> None:
    """Without an explicit architecture winget installs the one with no wheels.

    winget defaults to the machine's own architecture, so on ARM64 every install and
    every retry would fetch the arm64 build again -- the one whose dependency wheels
    do not exist. The x64 build runs natively on Windows on ARM.

    The continuations are folded first: a call split across lines with a backtick is
    the same call, and a guard that reads raw lines would pass it as compliant while
    the argument sat on the line it never looked at.
    """
    folded = re.sub(r"`\r?\n\s*", " ", ps1)
    calls = re.findall(r"Install-WingetPackage[^\r\n]*Python\.Python[^\r\n]*", folded)
    assert calls, "no Python winget install found"
    for call in calls:
        assert "$pyArch" in call, f"a Python install ignores the architecture: {call}"
    assert "'--architecture', 'x64'" in ps1, "the architecture must be named literally"


def test_an_already_correct_interpreter_is_accepted_without_probing_further(ps1: str) -> None:
    """The architecture preference must cost an ordinary machine nothing.

    Preferring x64 could mean probing every candidate before choosing. It does not:
    the FIRST win-amd64 hit returns immediately, so a machine whose first candidate is
    already win-amd64 -- every ordinary x64 box -- probes exactly what it always did.
    Only when the first interpreter that answers is the wrong architecture do we keep
    looking, which is precisely the case that used to end in a source build.
    """
    body = ps_function_body(ps1, "Resolve-Python")
    assert "if ($found.Platform -eq 'win-amd64') { return $found }" in body, (
        "a win-amd64 interpreter must be accepted immediately, not after a full sweep"
    )
    assert "$fallback" in body, (
        "an interpreter of the wrong architecture still beats none -- keep it"
    )


def test_a_wrong_architecture_stops_before_pip_and_says_why(ps1: str) -> None:
    """A wheel gap discovered by pip costs twenty minutes and reads as a wall of Rust.

    Every acquisition rung has failed by this point, so the install cannot succeed:
    stop, name the three packages, and give the one-download fix -- before pip starts,
    not in the middle of a source build.

    It is a stop rather than a warning because "automatic" has to mean the run either
    works or ends honestly, and the recorded refusal to auto-pin cryptography to its
    one ARM64 series (13 open advisories) means there is no silent way through.
    """
    stripped = ps1
    assert "httptools" in stripped and "statsmodels" in stripped and "cryptography" in stripped, (
        "name the packages that have no ARM64 wheel; a generic warning is not actionable"
    )
    assert "-amd64.exe, NOT -arm64.exe" in stripped, (
        "the manual route must name which installer file to take, and which not to"
    )
    stop = stripped.index("Only a $($python.Platform) interpreter is available")
    pip = stripped.index("'-m', 'pip', 'install', '-e'")
    assert stop < pip, "the refusal must come before pip is invoked, not after"


def test_the_refusal_is_not_a_cage(ps1: str) -> None:
    """A machine that genuinely has MSVC and Rust can build all three.

    Refusing it outright would trade one wrong default for another, so the escape
    exists and the refusal names it. It is off by default because without that
    toolchain the build fails slowly and the fix is one download.
    """
    assert "[switch]  $AllowSourceBuilds," in ps1, "the escape must be a real parameter"
    assert "$AllowSourceBuilds) {" in ps1, "and it must actually gate the refusal"
    assert "-AllowSourceBuilds to compile them here." in ps1, (
        "the refusal must tell the operator the escape exists"
    )


def test_the_nuget_download_is_verified_against_a_publisher_attested_hash(ps1: str) -> None:
    """An unverifiable download is a worse failure than the one it is fixing.

    nuget.org's catalog publishes `packageHash` + `packageHashAlgorithm` per version.
    We read the PUBLISHER's own attested SHA-512 and check the bytes against it --
    the same shape as this project's Ollama installer, which verifies against
    GitHub's attested release digest. Both directions are load-bearing: a mismatch
    refuses, and a MISSING attestation refuses too, because "no hash was published"
    must never quietly become "install it anyway".
    """
    body = ps_function_body(ps1, "Install-PythonFromNuGet")
    assert "Get-FileHash" in body and "SHA512" in body, "the bytes must actually be hashed"
    assert "FromBase64String" in body, (
        "nuget attests base64; comparing it to Get-FileHash's hex needs the conversion"
    )
    lowered = body.lower()
    assert "refusing" in lowered, "a failed verification must refuse, not warn and continue"
    attest = ps_function_body(ps1, "Get-NuGetAttestedHash")
    assert "packageHashAlgorithm" in attest and "'SHA512'" in attest, (
        "trusting packageHash without checking the algorithm accepts whatever nuget "
        "publishes next"
    )
    assert "if (-not $attested)" in body, "a missing attestation must be its own refusal"


def test_no_checksum_for_the_python_download_is_hardcoded(ps1: str) -> None:
    """The digest is fetched from the publisher, never written down here.

    A checksum embedded in this file would either be fabricated (nobody in this
    project's sandbox can reach python.org to verify one) or go stale the moment
    nuget publishes the next patch, at which point the honest failure becomes a
    false alarm and someone deletes the check.
    """
    for match in re.finditer(r"[0-9a-fA-F]{40,}", ps1):
        raise AssertionError(
            f"a literal digest is embedded in install.ps1: {match.group(0)[:24]}..."
        )


def test_the_nuget_registration_endpoint_is_the_one_powershell_can_read(ps1: str) -> None:
    """The -gz- registration endpoint always answers gzipped, whatever you ask for.

    Windows PowerShell 5.1's Invoke-RestMethod does not decompress it, so it would
    hand back bytes instead of JSON and the whole rung would fail for a reason that
    looks nothing like its cause. registration5-semver1 serves plain JSON and carries
    the same packageHash.
    """
    assert "registration5-semver1" in ps1, "use the endpoint PS 5.1 can actually parse"
    assert "registration5-gz-semver2" not in re.sub(r"(?m)^\s*#.*$", "", ps1), (
        "the gzipped endpoint must not be requested (the comment explaining why may "
        "name it; the code may not)"
    )


def test_the_acquisition_ladder_reprobes_instead_of_trusting_winget(ps1: str) -> None:
    """winget's exit code is unreliable, so the capability check is the only verdict.

    Three rungs, each followed by a fresh Resolve-Python: winget with the
    architecture named, winget again in user scope, then the nuget package. A rung
    that reported success but delivered nothing must not end the ladder.
    """
    # Bounded by CODE, not by the section comment: the fixture strips comments, so a
    # comment anchor is not merely fragile here, it does not exist.
    start = ps1.index("Write-Step 'Looking for Python 3.13+'")
    end = ps1.index("if ($inRepo) {", start)
    section = ps1[start:end]
    assert section.count("Install-WingetPackage") == 2, "both winget rungs must be present"
    assert "Install-PythonFromNuGet" in section, "the nuget rung must be reachable"
    assert section.count("Resolve-Python") >= 3, (
        "every rung must be judged by a re-probe, not by the installer's exit code"
    )


def test_machine_architecture_is_read_from_the_unmasked_variable(ps1: str) -> None:
    """PROCESSOR_ARCHITECTURE names the EMULATION inside an emulated process.

    A 32-bit shell on a 64-bit machine reports x86 there, and only
    PROCESSOR_ARCHITEW6432 names the real machine. Reading the masked one first would
    make a perfectly capable box look 32-bit and route it to the refusal.
    """
    body = ps_function_body(ps1, "Get-MachineArchitecture")
    first = body.index("PROCESSOR_ARCHITEW6432")
    second = body.index("PROCESSOR_ARCHITECTURE")
    assert first < second, "the unmasked variable must be consulted first"


def test_a_32_bit_only_windows_is_refused_with_the_real_reason(ps1: str) -> None:
    """cryptography publishes no win32 wheel at all, so this is a limit, not a bug.

    Saying "64-bit Windows is required" without the reason invites someone to treat
    it as an arbitrary gate and remove it.
    """
    assert "no 32-bit Windows wheel" in ps1, "name the actual blocker"
    assert "64-bit Windows is required" in ps1, "and state the requirement plainly"


def test_an_existing_venv_is_matched_against_the_resolved_interpreter(ps1: str) -> None:
    """Existence is not a match, and the mismatch is silent.

    A .venv keeps the version and wheel platform of whichever interpreter built it,
    for life. A field run on Windows-on-ARM resolved a win-amd64 interpreter, printed
    "ok  Python 3.13 (win-amd64)", reused the win-arm64 .venv four lines later, and
    pip went hunting win_arm64 wheels that do not exist -- three source builds and a
    dead install, with nothing in the output naming the cause.
    """
    start = ps1.index("$venv       = Join-Path $target '.venv'")
    # Bounded by CODE: the fixture strips comments, so a comment anchor does not
    # exist here at all.
    end = ps1.index("Push-Location -LiteralPath $target", start)
    section = ps1[start:end]
    assert "Test-PythonCandidate -Command @($venvPython)" in section, (
        "the existing venv must be probed, not merely found on disk"
    )
    assert "$existingVenv.Platform -ne $python.Platform" in section, (
        "a venv of the wrong wheel platform is the whole reason this check exists"
    )
    assert "$existingVenv.Version -ne $python.Version" in section, (
        "a venv from an older Python takes the wrong wheels too"
    )


def test_a_venv_that_cannot_be_replaced_stops_instead_of_installing_into_it(
    ps1: str,
) -> None:
    """The failure direction that matters: a locked folder must not fall through.

    Removal fails when something is running out of that folder. Proceeding would put
    the packages into the very environment just judged wrong, which is the bug this
    check exists to prevent -- so it fails closed and says what to close.
    """
    start = ps1.index("$venv       = Join-Path $target '.venv'")
    # Bounded by CODE: the fixture strips comments, so a comment anchor does not
    # exist here at all.
    end = ps1.index("Push-Location -LiteralPath $target", start)
    section = ps1[start:end]
    assert 'Stop-WithError "Could not remove $venv' in section, (
        "a failed removal must stop, not continue into the mismatched venv"
    )


# Held apart from the test body so neither language escapes the other's quotes.
_VENDOR_DRIVER = r"""
$all = (Get-Content -Raw $env:OO_INSTALL_PS1) -replace "`r`n", "`n"
$s = $all.IndexOf($env:OO_BLOCK_START)
$e = $all.IndexOf($env:OO_BLOCK_END)
if ($s -lt 0 -or $e -le $s) { throw 'could not slice the vendored-python block' }
$block = $all.Substring($s, $e - $s)

$ast = [System.Management.Automation.Language.Parser]::ParseInput($all, [ref]$null, [ref]$null)
foreach ($f in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($f.Name -eq 'Get-VendoredRoot') { . ([scriptblock]::Create($f.Extent.Text)) }
}
function Write-Note { param([string] $Message) }
function Write-Caution { param([string] $Message) }

$sandbox = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
$env:LOCALAPPDATA = Join-Path $sandbox 'LocalAppData'
$target = Join-Path $sandbox 'Open-Omniscience'
New-Item -ItemType Directory -Force -Path (Join-Path $target '.python-x64\tools') | Out-Null
Set-Content -LiteralPath (Join-Path $target '.python-x64\tools\python.exe') -Value 'legacy'

Invoke-Expression $block

$left = @(Get-ChildItem -LiteralPath $target -Force)
$moved = Test-Path -LiteralPath $script:VendoredPython
$content = if ($moved) { (Get-Content -Raw $script:VendoredPython).Trim() } else { '' }
Write-Output "$($left.Count -eq 0)|$moved|$content"
"""


# The PowerShell below is held apart from the test body so neither language has to
# escape the other's quotes. It slices the venv block out of the REAL installer --
# a retyped copy would pass while the shipped code was broken.
_VENV_DRIVER = r"""
$all = (Get-Content -Raw $env:OO_INSTALL_PS1) -replace "`r`n", "`n"
$s = $all.IndexOf($env:OO_BLOCK_START)
$e = $all.IndexOf($env:OO_BLOCK_END)
if ($s -lt 0 -or $e -le $s) { throw 'could not slice the venv block' }
$block = $all.Substring($s, $e - $s)

$script:Removed = $false
$script:Created = $false
function Write-Step { param([string] $Message) }
function Write-Ok { param([string] $Message) }
function Write-Note { param([string] $Message) }
function Write-Caution { param([string] $Message) }
function Stop-WithError { param([string] $Message, [string[]] $Hints = @()) throw $Message }
function Invoke-Native {
    param([string] $File, [string[]] $Arguments = @(), [switch] $AllowFailure)
    $script:Created = $true
    New-Item -ItemType Directory -Force -Path (Split-Path $script:vp) | Out-Null
    Set-Content -LiteralPath $script:vp -Value 'stub'
    return 0
}
function Remove-Item {
    [CmdletBinding()] param([string] $LiteralPath, [switch] $Recurse, [switch] $Force)
    $script:Removed = $true
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Recurse -Force
}
$python = [pscustomobject]@{ Version = [version]'3.13'; Platform = 'win-amd64'; Exe = 'x' }

function Invoke-Case {
    param($Answer)
    $script:Removed = $false
    $script:Created = $false
    $target = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
    $script:vp = Join-Path $target '.venv\Scripts\python.exe'
    New-Item -ItemType Directory -Force -Path (Split-Path $script:vp) | Out-Null
    Set-Content -LiteralPath $script:vp -Value 'existing'
    Set-Item -Path function:Test-PythonCandidate `
        -Value { param([string[]] $Command) $Answer }.GetNewClosure()
    Invoke-Expression $block
    return "$($script:Removed):$($script:Created)"
}

$mismatch = Invoke-Case ([pscustomobject]@{ Version = [version]'3.13'; Platform = 'win-arm64'; Exe = 'v' })
$match = Invoke-Case ([pscustomobject]@{ Version = [version]'3.13'; Platform = 'win-amd64'; Exe = 'v' })
Write-Output "$mismatch|$match"
"""


@pytest.mark.skipif(_powershell() is None, reason="needs pwsh/powershell")
def test_a_mismatched_venv_is_rebuilt_and_a_matching_one_is_not() -> None:
    """Behavioural, both directions, because either one alone ships a defect.

    Only rebuilding proves nothing on its own: a fix that rebuilt unconditionally
    would pass it and make every re-run re-download several hundred MB. The pair is
    the guard.
    """
    # Anchors and the path travel as DATA in the environment -- `-Command` does not
    # populate $args, and splicing either into source is how a quote becomes syntax.
    env = {
        **os.environ,
        "OO_INSTALL_PS1": str(INSTALL_PS1),
        "OO_BLOCK_START": "$venv       = Join-Path $target '.venv'",
        "OO_BLOCK_END": "# Everything below calls",
    }
    out = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", _VENV_DRIVER],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert out.returncode == 0, out.stderr
    mismatch, match = out.stdout.strip().splitlines()[-1].split("|")
    assert mismatch == "True:True", (
        "a win-arm64 venv under a win-amd64 interpreter must be removed and rebuilt"
    )
    assert match == "False:False", (
        "a matching venv must be reused untouched -- rebuilding it costs a full "
        "re-download on every run"
    )


@pytest.mark.skipif(_powershell() is None, reason="needs pwsh/powershell")
def test_machine_architecture_unmasks_an_emulated_shell() -> None:
    """Behavioural, because the source guard can only prove the READ ORDER.

    Runs the real function out of the real file (never a retyped copy) against the
    three environments that matter. The middle one is the trap: inside a 32-bit or
    emulated process PROCESSOR_ARCHITECTURE names the EMULATION, and only
    PROCESSOR_ARCHITEW6432 names the machine -- so a capable 64-bit box would
    otherwise read as 32-bit and be refused.
    """
    # The path travels as DATA in the environment, never spliced into the script
    # text: `-Command` does not populate $args, and interpolating a path into source
    # is how a quote in it becomes syntax.
    script = r"""
$src = Get-Content -Raw $env:OO_INSTALL_PS1
$ast = [System.Management.Automation.Language.Parser]::ParseInput($src, [ref]$null, [ref]$null)
foreach ($f in $ast.FindAll({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($f.Name -eq 'Get-MachineArchitecture') { . ([scriptblock]::Create($f.Extent.Text)) }
}
$env:PROCESSOR_ARCHITEW6432 = ''; $env:PROCESSOR_ARCHITECTURE = 'ARM64'
$a = Get-MachineArchitecture
$env:PROCESSOR_ARCHITECTURE = 'x86'; $env:PROCESSOR_ARCHITEW6432 = 'AMD64'
$b = Get-MachineArchitecture
$env:PROCESSOR_ARCHITEW6432 = ''
$c = Get-MachineArchitecture
Write-Output "$a|$b|$c"
"""
    env = {**os.environ, "OO_INSTALL_PS1": str(INSTALL_PS1)}
    out = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=120, env=env,
    )
    assert out.returncode == 0, out.stderr
    arm, emulated, real32 = out.stdout.strip().splitlines()[-1].split("|")
    assert arm == "ARM64"
    assert emulated == "AMD64", (
        "a 32-bit shell on a 64-bit machine must report the MACHINE, not the emulation"
    )
    assert real32 == "X86", "a genuinely 32-bit machine must still read as 32-bit"
