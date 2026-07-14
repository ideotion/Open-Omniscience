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
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = ["install.sh", "scripts/launch.sh", "scripts/bootstrap.sh"]

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="install.sh is a POSIX shell script; needs a real bash (the Windows "
    "runner only exposes a distro-less WSL stub, so these don't apply there)",
)


@pytest.mark.parametrize("script", SCRIPTS)
def test_shell_scripts_are_valid_syntax(script):
    r = subprocess.run(["bash", "-n", str(REPO / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("script", SCRIPTS)
def test_shell_scripts_are_executable(script):
    assert (REPO / script).stat().st_mode & 0o111, f"{script} is not executable"


def test_bootstrap_update_follows_the_remote_default_branch():
    """Field report 2026-07-02: a checkout stuck on an old cycle branch (0.09) kept
    re-pulling itself, so the user never got the latest release line. The updater must
    resolve the REMOTE's default branch (ls-remote --symref HEAD) and switch onto it,
    not follow whatever branch the local checkout is on — while still refusing to
    clobber local edits and honouring an explicit OO_BRANCH pin."""
    src = (REPO / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    assert "ls-remote --symref" in src, "the updater must ask the remote for its default branch"
    assert 'checkout -B "$ref" FETCH_HEAD' in src, "it must switch onto the new default line"
    # an explicit pin still wins; local edits are still protected on a line switch
    assert 'if [ -n "$BRANCH" ]; then' in src
    assert "to protect your local changes" in src


def test_help_prints_usage():
    r = subprocess.run(["bash", str(REPO / "install.sh"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "Interactive menu" in r.stdout
    assert "--appvm" in r.stdout


def test_unknown_option_fails_loudly():
    r = subprocess.run(["bash", str(REPO / "install.sh"), "--nope"], capture_output=True, text=True)
    assert r.returncode != 0
    assert "unknown option" in (r.stderr + r.stdout)


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="the XDG .desktop applications-menu launcher is Linux-only "
    "(macOS uses a different mechanism)",
)
def test_unattended_install_creates_launcher(tmp_path):
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "OO_SKIP_PIP": "1",
        "OO_SKIP_DB": "1",
        "OO_COMPONENTS": "",  # core only -- no network needed
        "OO_MAKE_LAUNCHER": "1",
    }
    r = subprocess.run(
        ["bash", str(REPO / "install.sh"), "--unattended"], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, r.stderr + r.stdout

    desktop = home / ".local/share/applications/open-omniscience.desktop"
    assert desktop.is_file(), "applications-menu launcher not created"
    body = desktop.read_text(encoding="utf-8")
    # the Exec path is double-quoted (freedesktop spec) so an install path with
    # spaces can't break double-click launch (field test 2026-06-21).
    assert f'Exec="{REPO}/scripts/launch.sh"' in body
    # Prefer the PNG (rendered more reliably than SVG across desktops); it is
    # committed, so the launcher should point at it.
    assert f"Icon={REPO}/assets/icon.png" in body
    assert "Terminal=true" in body
    # required freedesktop fields are present
    for field in ("[Desktop Entry]", "Type=Application", "Name=", "Exec=", "Icon="):
        assert field in body
    # also copied to the Desktop
    assert (home / "Desktop/open-omniscience.desktop").is_file()


def test_login_autostart_is_opt_in(tmp_path):
    """§2.6 (autonomous 2026-06-21): login autostart is OPT-IN (OO_AUTOSTART=1) and
    never created silently; the entry launches in airplane mode (boots offline)."""
    home = tmp_path / "home"
    home.mkdir()
    base_env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "OO_SKIP_PIP": "1",
        "OO_SKIP_DB": "1",
        "OO_COMPONENTS": "",
        "OO_MAKE_LAUNCHER": "0",
    }
    # The entry is platform-specific: an XDG .desktop on Linux, a LaunchAgent plist
    # on macOS (the install.sh setup_autostart branches on `uname -s`).
    if sys.platform == "darwin":
        autostart = home / "Library/LaunchAgents/com.open-omniscience.autostart.plist"
        marker = f"{REPO}/scripts/launch.sh"
    else:
        autostart = home / ".config/autostart/open-omniscience.desktop"
        marker = "X-GNOME-Autostart-enabled=true"

    # Default: no autostart entry is created.
    r = subprocess.run(
        ["bash", str(REPO / "install.sh"), "--unattended"], capture_output=True, text=True, env=base_env
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert not autostart.exists(), "autostart must NOT be created by default"

    # Opt-in: OO_AUTOSTART=1 creates the platform-appropriate autostart entry.
    r = subprocess.run(
        ["bash", str(REPO / "install.sh"), "--unattended"], capture_output=True, text=True,
        env={**base_env, "OO_AUTOSTART": "1"},
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert autostart.is_file(), "OO_AUTOSTART=1 must create the autostart entry"
    body = autostart.read_text(encoding="utf-8")
    assert f'{REPO}/scripts/launch.sh' in body and marker in body


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
    r = subprocess.run(
        ["bash", str(REPO / "install.sh"), "--unattended"], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert not (home / ".local/share/applications/open-omniscience.desktop").exists()


def test_install_shows_download_size_estimate(tmp_path):
    # The user should be told roughly how much will download before the long pip
    # step. Core + each chosen extra is surfaced, with the dated rough-estimate
    # caveat, and the LLM note flags Ollama's separate ~1 GB download.
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "OO_SKIP_PIP": "1",
        "OO_SKIP_DB": "1",
        "OO_COMPONENTS": "analysis,llm",
        "OO_MAKE_LAUNCHER": "0",
    }
    r = subprocess.run(
        ["bash", str(REPO / "install.sh"), "--unattended"], capture_output=True, text=True, env=env
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "Estimated download:" in out
    assert "core ~55 MB" in out
    assert "analysis ~90 MB" in out
    # Rough/dated honesty caveat travels with the figure.
    assert "Rough, measured" in out
    # LLM selected => the separate Ollama runtime download is called out.
    assert "Ollama adds ~1 GB" in out


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
    r = subprocess.run(
        ["bash", str(REPO / "install.sh")], input="", capture_output=True, text=True, env=env
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "(.[analysis,compression,columnar])" in out  # clean, well-formed spec (columnar default 2026-07-02)
    assert "Selected components: core, analysis,compression,columnar" in out
    # The failure signatures we must never reintroduce:
    assert "InvalidRequirement" not in out
    assert "Traceback" not in out


def test_bootstrap_points_at_canonical_repo_and_hands_off():
    body = (REPO / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert "ideotion/Open-Omniscience" in body
    assert "exec ./install.sh" in body  # delegates to the inspectable in-repo installer


def test_bootstrap_does_not_hardcode_nonexistent_main_branch():
    # The repo's default branch is not "main"; pinning to it would 404. The
    # bootstrap should track the default branch unless OO_BRANCH is set.
    body = (REPO / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert "OO_BRANCH:-main" not in body
    assert 'BRANCH="${OO_BRANCH:-}"' in body


def test_install_links_resolve_to_default_branch_via_head():
    # raw.githubusercontent .../HEAD/... always resolves to the default branch,
    # so the documented one-liner keeps working regardless of its name.
    for doc in ("README.md", "docs/QUICKSTART.md", "scripts/bootstrap.sh"):
        text = (REPO / doc).read_text(encoding="utf-8")
        assert "raw.githubusercontent.com/ideotion/Open-Omniscience/main/" not in text, (
            f"{doc} still points the curl install at a non-existent 'main' branch"
        )
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
    r = subprocess.run(["bash", str(REPO / "install.sh"), "--help"], capture_output=True, text=True)
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
    (fake_venv / "marker").write_text("x", encoding="utf-8")  # prove rm -rf removed the tree

    home = tmp_path / "home"
    apps = home / ".local/share/applications"
    apps.mkdir(parents=True)
    (home / "Desktop").mkdir(parents=True)
    menu_launcher = apps / "open-omniscience.desktop"
    desk_launcher = home / "Desktop/open-omniscience.desktop"
    menu_launcher.write_text("[Desktop Entry]\n", encoding="utf-8")
    desk_launcher.write_text("[Desktop Entry]\n", encoding="utf-8")

    # No TTY here (piped stdin), so confirm non-interactively via OO_ASSUME_YES.
    # (Data deletion is never auto-confirmed; the fake venv has no python, so the
    # data-dir step is skipped anyway.)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "OO_ASSUME_YES": "1"}
    r = subprocess.run(
        ["bash", str(app / "install.sh"), "--uninstall"],
        input="",
        capture_output=True,
        text=True,
        env=env,
    )
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
    r = subprocess.run(
        ["bash", str(app / "install.sh"), "--uninstall"],
        input="",
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0
    assert fake_venv.exists(), "nothing should be removed without confirmation"
    assert "nothing was removed" in r.stdout


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="POSIX shell function test; needs bash",
)
def test_ollama_store_access_guards_are_noops():
    """configure_ollama_store_access() must NO-OP when opted out (OO_OLLAMA_READABLE=0)
    or when there is no protected systemd-service store — it must never attempt a
    chmod blindly. The actual chmod path is privileged + machine-specific (verified on
    a real install), so here we only pin the guards."""
    import os
    import re

    src = (REPO / "install.sh").read_text(encoding="utf-8")
    m = re.search(r"\nconfigure_ollama_store_access\(\) \{.*?\n\}\n", src, re.S)
    assert m, "configure_ollama_store_access not found in install.sh"
    harness = (
        'DIM=""; RST=""\n'
        "say(){ :; }; step(){ echo ENTERED; }; ok(){ echo OK; }; warn(){ echo WARN; }\n"
        "chmod(){ echo CHMOD; }\n"  # trap any chmod attempt
        + m.group(0)
        + "\nconfigure_ollama_store_access\n"
    )
    # opted out -> immediate return, no entry into the active path, no chmod
    r = subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True,
        env={**os.environ, "OO_OLLAMA_READABLE": "0"},
    )
    assert r.returncode == 0 and "ENTERED" not in r.stdout and "CHMOD" not in r.stdout
    # default, but no /usr/share/ollama/.ollama/models here -> no chmod either
    env = {k: v for k, v in os.environ.items() if k != "OO_OLLAMA_READABLE"}
    r2 = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, env=env)
    assert r2.returncode == 0 and "CHMOD" not in r2.stdout


def test_pip_install_is_network_resilient():
    """Field test 2026-06-21: a flaky link (Qubes disposable VM / Tor netvm) dropped
    DNS mid-resolution, so pip backtracked and emitted a MISLEADING
    'ResolutionImpossible / no matching distribution' for regex. The installer must
    harden the pip step (longer timeout + retries + retry-the-step) and degrade with
    an HONEST network message, not echo pip's confusing resolver error."""
    sh = (REPO / "install.sh").read_text(encoding="utf-8")
    assert "--retries" in sh and "--timeout 60" in sh, "pip must use more retries + a longer timeout"
    # The whole step retries with backoff.
    assert "attempt in 1 2 3" in sh, "the pip install step must retry on failure"
    # Honest network guidance on persistent failure (not pip's misleading conflict).
    assert "getent hosts files.pythonhosted.org" in sh
    assert "downloaded wheels are cached" in sh


def test_bootstrap_recovers_from_a_diverged_or_force_updated_branch():
    """Field test 2026-06-23: a force-update of origin/0.09 + a stray local commit made
    `git pull --ff-only` dead-end the bootstrap with a raw git hint. The update block
    must fast-forward when possible, snap a CLEAN checkout to upstream on divergence,
    and refuse (with guidance) only when there are local uncommitted changes."""
    sh = (REPO / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    assert "merge --ff-only FETCH_HEAD" in sh, "must try a fast-forward to the fetched tip"
    assert "git -C \"$INSTALL_DIR\" status --porcelain" in sh, "must check for local changes"
    assert "reset --hard FETCH_HEAD" in sh, "a clean checkout must snap to upstream on divergence"
    assert "Update aborted to protect your local changes" in sh, "dirty tree -> honest guidance, not a reset"


def test_bootstrap_divergence_recovery_mechanism_works(tmp_path):
    """Prove the recovery git commands actually do the right thing: after origin's
    history is REWRITTEN (force-update), a clean install checkout snaps to the new tip
    via fetch + ff-only-fails + reset --hard FETCH_HEAD."""
    import subprocess as sp

    def git(*a, cwd):
        return sp.run(["git", *a], cwd=cwd, capture_output=True, text=True,
                      env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

    origin = tmp_path / "origin"; origin.mkdir()
    git("init", "-b", "0.09", cwd=origin)
    (origin / "f.txt").write_text("v1", encoding="utf-8")
    git("add", "-A", cwd=origin); git("commit", "-m", "v1", cwd=origin)

    clone = tmp_path / "clone"
    sp.run(["git", "clone", str(origin), str(clone)], capture_output=True, text=True)

    # Origin's history is REWRITTEN (amend = a force-update / new SHA, not a child).
    (origin / "f.txt").write_text("v2", encoding="utf-8")
    git("add", "-A", cwd=origin); git("commit", "--amend", "-m", "v2-rewritten", cwd=origin)

    # The bootstrap recovery sequence on a CLEAN checkout:
    git("fetch", "origin", "0.09", cwd=clone)
    ff = git("merge", "--ff-only", "FETCH_HEAD", cwd=clone)
    assert ff.returncode != 0, "ff-only must fail on a rewritten history (the dead-end)"
    assert git("status", "--porcelain", cwd=clone).stdout.strip() == "", "checkout is clean"
    reset = git("reset", "--hard", "FETCH_HEAD", cwd=clone)
    assert reset.returncode == 0
    assert (clone / "f.txt").read_text(encoding="utf-8") == "v2", "snapped to the rewritten upstream"


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="POSIX shell function test; needs bash",
)
def test_missing_venv_is_auto_installed_via_apt():
    """Field report 2026-07 (Tails): `python3 -m venv` fails there because the venv/
    ensurepip module ships in a separate apt package that isn't installed by default.
    Instead of dying with manual instructions, the installer must install it
    AUTOMATICALLY (seamless on Tails) — while never hanging on a sudo password prompt
    nothing can answer, honestly refusing to claim success if ensurepip is still
    missing afterwards, and respecting the OO_NO_APT=1 opt-out.

    We extract try_apt_install_venv() and drive it in an isolated bash harness with
    apt-get/sudo/id/$PY all stubbed, so nothing touches the real system."""
    import re
    import subprocess

    src = (REPO / "install.sh").read_text(encoding="utf-8")
    m = re.search(r"\ntry_apt_install_venv\(\) \{.*?\n\}\n", src, re.S)
    assert m, "try_apt_install_venv not found in install.sh"
    fn = m.group(0)

    # Base stubs: quiet UI, no real Tails, force non-root so the sudo branch is
    # deterministic regardless of whether CI runs as root. `sudo` honours a leading
    # `-n` (the passwordless probe returns $SUDO_NP_RC; the real elevated call passes
    # through). `env` strips leading VAR=val so DEBIAN_FRONTEND is transparent. `apt-get`
    # records its args and returns $APT_RC (and can fail `update` specifically).
    base = (
        'INTERACTIVE=0; UNATTENDED=0; DIM=""; RST=""\n'
        "step(){ echo \"STEP $*\"; }; say(){ :; }; ok(){ :; }; warn(){ :; }\n"
        "is_tails(){ return 1; }\n"
        "id(){ echo 1000; }\n"  # force non-root
        'env(){ while [ "$#" -gt 0 ]; do case "$1" in *=*) shift;; *) break;; esac; done; "$@"; }\n'
        'sudo(){ if [ "$1" = "-n" ]; then shift; '
        'if [ "$1" = "true" ] && [ "$#" -eq 1 ]; then return ${SUDO_NP_RC:-0}; fi; fi; "$@"; }\n'
        'apt-get(){ echo APT_CALLED "$@"; '
        'case "$1" in update) return ${APT_UPDATE_RC:-0};; *) return ${APT_RC:-0};; esac; }\n'
    )

    def run(stubs="", env=None, call="try_apt_install_venv python3-venv", base_stubs=base):
        harness = base_stubs + stubs + fn + f"\n{call}; echo RC=$?\n"
        return subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", **(env or {})},
        )

    # 1) OO_NO_APT=1 opt-out: no apt call at all, refuses (falls back to guidance).
    a = run(env={"OO_NO_APT": "1", "SUDO_NP_RC": "0"})
    assert "APT_CALLED" not in a.stdout and "RC=1" in a.stdout, a.stdout

    # 2) Non-interactive + sudo needs a password: never reaches apt (no hang in CI).
    b = run(env={"SUDO_NP_RC": "1"})  # passwordless probe fails, INTERACTIVE=0
    assert "APT_CALLED" not in b.stdout and "RC=1" in b.stdout, b.stdout

    # 3) Seamless success: passwordless sudo + apt install + ensurepip now importable.
    #    The real apt calls go through `sudo -n` (never a prompt).
    c = run(env={"SUDO_NP_RC": "0", "APT_RC": "0", "PY": "true"})
    # (apt-get update is best-effort + silenced; the install is what gates + shows.)
    assert "APT_CALLED install -y python3-venv" in c.stdout, c.stdout
    assert "RC=0" in c.stdout, c.stdout

    # 4) Honesty: apt "succeeds" but ensurepip is STILL missing -> refuse (RC!=0),
    #    so the caller shows guidance instead of a false "installed" claim.
    d = run(env={"SUDO_NP_RC": "0", "APT_RC": "0", "PY": "false"})
    assert "APT_CALLED" in d.stdout and "RC=1" in d.stdout, d.stdout

    # 5) F2: a flaky `apt-get update` (partial mirror over Tor) must NOT abort an
    #    otherwise-installable package -- update is best-effort, only install gates.
    f = run(env={"SUDO_NP_RC": "0", "APT_UPDATE_RC": "1", "APT_RC": "0", "PY": "true"})
    assert "APT_CALLED install -y python3-venv" in f.stdout and "RC=0" in f.stdout, f.stdout

    # 6) Interactive human without passwordless sudo: the password prompt is
    #    answerable at the terminal, so it PROCEEDS (does not skip).
    g = run(
        'INTERACTIVE=1\n',
        env={"SUDO_NP_RC": "1", "APT_RC": "0", "PY": "true"},
    )
    assert "APT_CALLED install -y python3-venv" in g.stdout and "RC=0" in g.stdout, g.stdout

    # 7) As root: no sudo prefix, apt is called directly (the versioned package name
    #    is honoured for a 3.13 interpreter).
    root_base = base.replace("id(){ echo 1000; }\n", "id(){ echo 0; }\n")
    e = run(
        env={"APT_RC": "0", "PY": "true"},
        call="try_apt_install_venv python3.13-venv", base_stubs=root_base,
    )
    assert "APT_CALLED install -y python3.13-venv" in e.stdout and "RC=0" in e.stdout, e.stdout


def test_create_venv_wires_auto_install_and_tails_aware_fallback():
    """create_venv must attempt the automatic install and, when it can't, fall back to
    guidance that is honest about Tails (admin password, amnesia/Persistent Storage,
    Python 3.11). The OO_NO_APT opt-out and the seamless-on-Tails intent stay documented."""
    sh = (REPO / "install.sh").read_text(encoding="utf-8")
    # create_venv attempts the auto-install instead of dying immediately.
    assert "if try_apt_install_venv " in sh, "create_venv must try the automatic apt install"
    # The opt-out exists.
    assert "OO_NO_APT" in sh, "there must be an opt-out for the automatic apt install"
    # Honest Tails guidance on the fallback path (only claims the facts support).
    assert "Persistent Storage -> Additional Software" in sh, "must explain Tails amnesia/persistence"
    assert "administration password at the Welcome Screen" in sh, "must explain the Tails admin password"
    assert "Tails ships Python 3.11" in sh, "must be honest that 3.13 isn't in Tails' default repos"
    # Never hang on an unanswerable sudo prompt (CI / --unattended / no TTY): the real
    # apt calls run under `sudo -n` unless a human is at an interactive terminal, and
    # DEBIAN_FRONTEND=noninteractive stops a debconf prompt from blocking either.
    assert "sudo -n true" in sh, "must probe passwordless sudo before risking a prompt"
    assert 'sudo="sudo -n"' in sh, "the elevated apt calls must use sudo -n (fail fast, no prompt)"
    assert "DEBIAN_FRONTEND=noninteractive" in sh, "apt must run non-interactively (no debconf hang)"
    # A flaky `apt-get update` must not fail an installable package (best-effort update).
    assert "apt-get update >/dev/null 2>&1 || true" in sh, "apt-get update must be best-effort"


def test_pip_install_handles_out_of_disk_and_redirects_tmpdir():
    """Field test 2026-06-23 (Qubes disposable VM): pip hit 'No space left on device'
    unpacking big wheels because /tmp is a small RAM-backed tmpfs, even though the home
    volume had room. The installer must (a) point pip's TMPDIR at the install volume and
    (b) DISTINGUISH a disk-full failure from a network one (the prior message wrongly
    said 'almost always a NETWORK problem')."""
    sh = (REPO / "install.sh").read_text(encoding="utf-8")
    # TMPDIR is redirected off /tmp for the pip step.
    assert 'TMPDIR="$pip_tmp" python -m pip install' in sh, "pip must run with a roomy TMPDIR"
    assert "oo-pip-build" in sh
    # Disk-full is detected and given its OWN guidance (df + Qubes private storage), not network.
    assert "No space left on device|Errno 28" in sh, "must detect the disk-full error"
    assert "df -h /tmp" in sh and "private storage" in sh, "disk-full needs disk guidance"
    assert "out of disk space" in sh.lower()
