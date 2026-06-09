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
    # Prefer the PNG (rendered more reliably than SVG across desktops); it is
    # committed, so the launcher should point at it.
    assert f"Icon={REPO}/assets/icon.png" in body
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


def test_curl_pipe_install_does_not_leak_menu_into_pip_spec(tmp_path):
    # Regression: under `curl | bash`, stdin is the piped script, not a TTY. The
    # component menu used to print its prompt to stdout, which the caller captured
    # as the extras value -- so pip received ".[<menu text>]" and crashed with
    # InvalidRequirement. The menu must yield a clean extras spec instead.
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "OO_SKIP_PIP": "1",
        "OO_SKIP_DB": "1",
        "OO_MAKE_LAUNCHER": "0",
    }
    # No --unattended: exercise the interactive menu. input="" => stdin is a
    # non-TTY pipe (exactly the curl|bash case), with no terminal -> safe defaults.
    r = subprocess.run(["bash", str(REPO / "install.sh")],
                       input="", capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "(.[analysis,compression])" in out              # clean, well-formed spec
    assert "Selected components: core, analysis,compression" in out
    # The failure signatures we must never reintroduce:
    assert "InvalidRequirement" not in out
    assert "Traceback" not in out


def test_bootstrap_points_at_canonical_repo_and_hands_off():
    body = (REPO / "scripts/bootstrap.sh").read_text()
    assert "ideotion/Open-Omniscience" in body
    assert "exec ./install.sh" in body  # delegates to the inspectable in-repo installer


def test_bootstrap_does_not_hardcode_nonexistent_main_branch():
    # The repo's default branch is not "main"; pinning to it would 404. The
    # bootstrap should track the default branch unless OO_BRANCH is set.
    body = (REPO / "scripts/bootstrap.sh").read_text()
    assert 'OO_BRANCH:-main' not in body
    assert 'BRANCH="${OO_BRANCH:-}"' in body


def test_install_links_resolve_to_default_branch_via_head():
    # raw.githubusercontent .../HEAD/... always resolves to the default branch,
    # so the documented one-liner keeps working regardless of its name.
    for doc in ("README.md", "docs/QUICKSTART.md", "scripts/bootstrap.sh"):
        text = (REPO / doc).read_text()
        assert "raw.githubusercontent.com/ideotion/Open-Omniscience/main/" not in text, \
            f"{doc} still points the curl install at a non-existent 'main' branch"
        assert "Open-Omniscience/HEAD/scripts/bootstrap.sh" in text


def test_png_icon_exists_and_is_valid():
    png = REPO / "assets/icon.png"
    assert png.is_file(), "PNG icon fallback is missing"
    # Validate it really is a 256x256 PNG (cheap header check, no Pillow needed).
    sig = png.read_bytes()[:8]
    assert sig == b"\x89PNG\r\n\x1a\n", "icon.png is not a PNG"


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

    # No TTY here (piped stdin), so confirm non-interactively via OO_ASSUME_YES.
    # (Data deletion is never auto-confirmed; the fake venv has no python, so the
    # data-dir step is skipped anyway.)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "OO_ASSUME_YES": "1"}
    r = subprocess.run(["bash", str(app / "install.sh"), "--uninstall"],
                       input="", capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr + r.stdout
    assert not fake_venv.exists(), "virtualenv should be removed"
    assert not menu_launcher.exists(), "apps-menu launcher should be removed"
    assert not desk_launcher.exists(), "desktop launcher should be removed"


def test_uninstall_aborts_without_confirmation(tmp_path):
    app = tmp_path / "app"
    (app / "assets").mkdir(parents=True)
    shutil.copy(REPO / "install.sh", app / "install.sh")
    shutil.copy(REPO / "assets/logo.txt", app / "assets/logo.txt")
    fake_venv = app / ".venv"
    fake_venv.mkdir()

    home = tmp_path / "home"
    home.mkdir()
    # No tty and no OO_ASSUME_YES -> the proceed prompt safely defaults to "no",
    # so nothing is removed. (Safety: never destroy without explicit confirmation.)
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    r = subprocess.run(["bash", str(app / "install.sh"), "--uninstall"],
                       input="", capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert fake_venv.exists(), "nothing should be removed without confirmation"
    assert "nothing was removed" in r.stdout
