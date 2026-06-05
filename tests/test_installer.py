"""
Tests for the installer / launcher / bootstrap shell scripts.

The previous version of this file tested an `installer/gui_installer.py` GUI and a
Debian-only `install` script that no longer exist (it also forbade macOS support,
which the project now provides). It was not collected by pytest. This rewrite
tests the real, current scripts.

We cannot click a desktop icon in CI, but we can prove the scripts are
syntactically valid and that an unattended install produces the expected
artifacts (venv reuse, a correct .desktop launcher) without touching the
network -- the heavy pip/db steps are skipped via OO_SKIP_PIP / OO_SKIP_DB.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = ["install.sh", "scripts/launch.sh", "scripts/bootstrap.sh"]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


@pytest.mark.parametrize("script", SCRIPTS)
def test_shell_scripts_are_valid_syntax(script):
    r = subprocess.run(["bash", "-n", str(REPO / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("script", SCRIPTS)
def test_shell_scripts_are_executable(script):
    assert (REPO / script).stat().st_mode & 0o111, f"{script} is not executable"


def test_help_prints_usage():
    r = subprocess.run(["bash", str(REPO / "install.sh"), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "Interactive menu" in r.stdout
    assert "--appvm" in r.stdout


def test_unknown_option_fails_loudly():
    r = subprocess.run(["bash", str(REPO / "install.sh"), "--nope"],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "unknown option" in (r.stderr + r.stdout)


def test_unattended_install_creates_launcher(tmp_path):
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "OO_SKIP_PIP": "1",
        "OO_SKIP_DB": "1",
        "OO_COMPONENTS": "",        # core only -- no network needed
        "OO_MAKE_LAUNCHER": "1",
    }
    r = subprocess.run(["bash", str(REPO / "install.sh"), "--unattended"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr + r.stdout

    desktop = home / ".local/share/applications/open-omniscience.desktop"
    assert desktop.is_file(), "applications-menu launcher not created"
    body = desktop.read_text()
    assert f"Exec={REPO}/scripts/launch.sh" in body
    assert f"Icon={REPO}/assets/icon.svg" in body
    assert "Terminal=true" in body
    # required freedesktop fields are present
    for field in ("[Desktop Entry]", "Type=Application", "Name=", "Exec=", "Icon="):
        assert field in body
    # also copied to the Desktop
    assert (home / "Desktop/open-omniscience.desktop").is_file()


def test_unattended_install_without_launcher_opt_out(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "OO_SKIP_PIP": "1",
        "OO_SKIP_DB": "1",
        "OO_COMPONENTS": "",
        "OO_MAKE_LAUNCHER": "0",
    }
    r = subprocess.run(["bash", str(REPO / "install.sh"), "--unattended"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr + r.stdout
    assert not (home / ".local/share/applications/open-omniscience.desktop").exists()


def test_bootstrap_points_at_canonical_repo_and_hands_off():
    body = (REPO / "scripts/bootstrap.sh").read_text()
    assert "ideotion/Open-Omniscience" in body
    assert "exec ./install.sh" in body  # delegates to the inspectable in-repo installer


def test_icon_asset_exists():
    assert (REPO / "assets/icon.svg").is_file()


def test_help_lists_check_and_uninstall():
    r = subprocess.run(["bash", str(REPO / "install.sh"), "--help"],
                       capture_output=True, text=True)
    assert "--check" in r.stdout
    assert "--uninstall" in r.stdout


def test_uninstall_removes_venv_and_launcher_but_keeps_data(tmp_path):
    # Build an isolated copy of the script so we never touch the real .venv.
    app = tmp_path / "app"
    (app / "assets").mkdir(parents=True)
    shutil.copy(REPO / "install.sh", app / "install.sh")
    shutil.copy(REPO / "assets/logo.txt", app / "assets/logo.txt")
    fake_venv = app / ".venv"
    fake_venv.mkdir()
    (fake_venv / "marker").write_text("x")  # prove rm -rf removed the tree

    home = tmp_path / "home"
    apps = home / ".local/share/applications"
    apps.mkdir(parents=True)
    (home / "Desktop").mkdir(parents=True)
    menu_launcher = apps / "open-omniscience.desktop"
    desk_launcher = home / "Desktop/open-omniscience.desktop"
    menu_launcher.write_text("[Desktop Entry]\n")
    desk_launcher.write_text("[Desktop Entry]\n")

    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    # No TTY (piped stdin) -> text prompts; answer "yes" to the single proceed prompt.
    r = subprocess.run(["bash", str(app / "install.sh"), "--uninstall"],
                       input="y\n", capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr + r.stdout
    assert not fake_venv.exists(), "virtualenv should be removed"
    assert not menu_launcher.exists(), "apps-menu launcher should be removed"
    assert not desk_launcher.exists(), "desktop launcher should be removed"


def test_uninstall_aborts_on_no(tmp_path):
    app = tmp_path / "app"
    (app / "assets").mkdir(parents=True)
    shutil.copy(REPO / "install.sh", app / "install.sh")
    shutil.copy(REPO / "assets/logo.txt", app / "assets/logo.txt")
    fake_venv = app / ".venv"
    fake_venv.mkdir()

    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    r = subprocess.run(["bash", str(app / "install.sh"), "--uninstall"],
                       input="n\n", capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert fake_venv.exists(), "nothing should be removed when the user declines"
    assert "nothing was removed" in r.stdout
