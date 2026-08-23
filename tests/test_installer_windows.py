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
def _powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


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
