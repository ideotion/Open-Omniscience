"""
Tests for the air-gapped installer and the offline bundle builder.

We cannot run a full 230 MB install in CI, so these prove the properties that
actually protect the person standing at a disconnected machine:

  * it REFUSES a bundle that cannot work here (wrong CPU architecture) instead of
    failing halfway through with an unreadable pip error;
  * it REFUSES a corrupted bundle before touching anything -- a USB stick that
    silently truncates a wheel is the characteristic air-gap failure;
  * it explains where the bundle should go when there isn't one;
  * the ONLINE install is completely unaffected by any of this;
  * the offline install can never reach the network;
  * the builder's default component set cannot drift away from the installer's.

The end-to-end install itself was verified by hand against a real 91-file bundle
with every network path dead (see docs/OFFLINE_INSTALL.md).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OFFLINE_SH = REPO / "install-offline.sh"
BUILDER_SH = REPO / "scripts" / "build_offline_bundle.sh"
DESKTOP = REPO / "Install Open Omniscience (offline).desktop"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="POSIX shell scripts; the Windows runner has no real bash",
)


def _run(script: Path, *args: str, cwd: Path | None = None, **env: str):
    """Run a shell script with a clean, non-interactive environment."""
    e = dict(os.environ)
    e.update({"OO_NO_HOLD": "1"})  # never wait for an Enter that no test will type
    e.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=e,
        timeout=120,
    )


def _make_bundle(root: Path, *, arch: str = "x86_64", extras: str = "analysis") -> Path:
    """A minimal but structurally REAL bundle: manifest, checksums, a pip wheel."""
    b = root / f"open-omniscience-offline-linux-{arch}-cp313"
    (b / "wheels").mkdir(parents=True)
    (b / "bootstrap").mkdir(parents=True)
    # A wheel is a zip; these tests never install it, so the bytes only need to be
    # stable enough to checksum.
    payload = b / "bootstrap" / "pip-99.0-py3-none-any.whl"
    payload.write_bytes(b"not-a-real-wheel")

    files = {}
    lines = []
    for p in sorted(b.rglob("*")):
        if p.is_file():
            rel = p.relative_to(b)
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            files[str(rel)] = {"sha256": digest, "bytes": p.stat().st_size}
            lines.append(f"{digest}  ./{rel}")
    (b / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (b / "offline-manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "app_version": "0.3.0",
                "built_at": "2026-08-11T00:00:00Z",
                "extras": extras,
                "python": {"version": "3.13.12", "abi_tag": "cp313"},
                "platform": {"kernel": "Linux", "arch": arch, "glibc": "2.36"},
                "bundled_runtime": None,
                "totals": {"files": len(files), "bytes": 16},
                "files": files,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return b


def _fake_app(root: Path) -> Path:
    """A stand-in for the extracted application folder."""
    app = root / "Open-Omniscience-main"
    app.mkdir(parents=True)
    shutil.copy2(OFFLINE_SH, app / "install-offline.sh")
    # install.sh is only reached on the success path, which these tests never take;
    # a stub proves we did NOT reach it when we expect an early refusal.
    (app / "install.sh").write_text("#!/usr/bin/env bash\necho REACHED_INSTALL_SH\n", encoding="utf-8")
    (app / "install.sh").chmod(0o755)
    return app


# --------------------------------------------------------------------------- #
# Basic hygiene
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("script", ["install-offline.sh", "scripts/build_offline_bundle.sh"])
def test_scripts_are_valid_bash(script):
    r = subprocess.run(["bash", "-n", str(REPO / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("script", ["install-offline.sh", "scripts/build_offline_bundle.sh"])
def test_scripts_are_executable(script):
    assert (REPO / script).stat().st_mode & 0o111, f"{script} is not executable"


def test_builder_help_works():
    r = _run(BUILDER_SH, "--help")
    assert r.returncode == 0
    assert "--with-python" in r.stdout
    assert "--extras" in r.stdout


def test_builder_rejects_a_malformed_extras_value():
    """The extras string is interpolated into a pip spec; it must stay a token list."""
    r = _run(BUILDER_SH, "--extras", "analysis; rm -rf /")
    assert r.returncode != 0
    assert "invalid --extras" in (r.stdout + r.stderr)


# --------------------------------------------------------------------------- #
# The refusals that protect an air-gapped operator
# --------------------------------------------------------------------------- #
def test_missing_bundle_explains_where_to_put_it(tmp_path):
    app = _fake_app(tmp_path / "empty")
    r = _run(app / "install-offline.sh", cwd=app)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "No dependency bundle found" in out
    # It must show the expected side-by-side layout, not just complain.
    assert "side by side" in out.lower() or "├──" in out
    assert "OO_OFFLINE_BUNDLE" in out, "must offer the explicit-path escape hatch"
    assert "REACHED_INSTALL_SH" not in out, "must not hand off without a bundle"


def test_architecture_mismatch_is_refused_by_name(tmp_path):
    """Compiled wheels cannot cross architectures. Catch it before pip does."""
    bundle = _make_bundle(tmp_path, arch="aarch64")
    app = _fake_app(tmp_path)
    r = _run(app / "install-offline.sh", cwd=app, OO_OFFLINE_BUNDLE=str(bundle))
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "aarch64" in out and "REACHED_INSTALL_SH" not in out
    # The message must name the machine's own architecture, so the fix is obvious.
    assert os.uname().machine in out


def test_a_corrupted_bundle_is_refused_before_anything_is_installed(tmp_path):
    """A silently truncated file on a failing USB stick is THE air-gap failure mode."""
    bundle = _make_bundle(tmp_path, arch=os.uname().machine)
    victim = bundle / "bootstrap" / "pip-99.0-py3-none-any.whl"
    victim.write_bytes(b"truncated")  # same name, different bytes

    app = _fake_app(tmp_path)
    r = _run(app / "install-offline.sh", cwd=app, OO_OFFLINE_BUNDLE=str(bundle))
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "damaged" in out.lower()
    assert "Nothing has been installed" in out
    assert "REACHED_INSTALL_SH" not in out, "must refuse before handing off to install.sh"


def test_an_intact_bundle_passes_verification_and_hands_off(tmp_path):
    """The negative-space twin: on a GOOD bundle the installer must get all the way
    through to the real installer. Without this, the refusal tests above would be
    satisfied by a script that simply always refuses."""
    bundle = _make_bundle(tmp_path, arch=os.uname().machine)
    app = _fake_app(tmp_path)
    r = _run(app / "install-offline.sh", cwd=app, OO_OFFLINE_BUNDLE=str(bundle))
    out = r.stdout + r.stderr
    assert "Every file matches its checksum" in out
    assert "damaged" not in out.lower()
    assert "REACHED_INSTALL_SH" in out, "a good bundle must reach the real installer"
    assert r.returncode == 0


def test_a_bundle_without_checksums_warns_but_does_not_silently_pretend(tmp_path):
    bundle = _make_bundle(tmp_path, arch=os.uname().machine)
    (bundle / "SHA256SUMS").unlink()
    app = _fake_app(tmp_path)
    r = _run(app / "install-offline.sh", cwd=app, OO_OFFLINE_BUNDLE=str(bundle))
    out = r.stdout + r.stderr
    assert "without an integrity check" in out, "an unverifiable bundle must say so"
    assert "Every file matches its checksum" not in out, "it must not claim a check it skipped"


def test_bundle_is_discovered_as_a_sibling_folder(tmp_path):
    """The documented layout: both zips extracted next to each other."""
    workspace = tmp_path / "usb"
    workspace.mkdir()
    _make_bundle(workspace, arch=os.uname().machine)
    app = _fake_app(workspace)
    r = _run(app / "install-offline.sh", cwd=app)
    out = r.stdout + r.stderr
    assert "No dependency bundle found" not in out, "a sibling bundle must be found"
    assert "Every file matches its checksum" in out


def test_the_components_from_the_manifest_reach_the_installer(tmp_path):
    """The bundle decides what gets installed -- installing components the bundle
    does not carry would fail, and installing fewer would silently ship less."""
    bundle = _make_bundle(tmp_path, arch=os.uname().machine, extras="analysis,columnar")
    app = _fake_app(tmp_path)
    (app / "install.sh").write_text(
        '#!/usr/bin/env bash\necho "COMPONENTS=[$OO_COMPONENTS]"\necho "BUNDLE=[$OO_OFFLINE_BUNDLE]"\n',
        encoding="utf-8",
    )
    (app / "install.sh").chmod(0o755)
    r = _run(app / "install-offline.sh", cwd=app, OO_OFFLINE_BUNDLE=str(bundle))
    out = r.stdout + r.stderr
    assert "COMPONENTS=[analysis,columnar]" in out
    assert f"BUNDLE=[{bundle}]" in out


# --------------------------------------------------------------------------- #
# The online install must be untouched, and the offline one must stay offline
# --------------------------------------------------------------------------- #
def _bash_function_body(src: str, name: str) -> str:
    """Slice one shell function, so an assertion about it cannot be satisfied by
    text living somewhere else in the file."""
    start = src.index(f"{name}() {{")
    rest = src[start:]
    end = rest.index("\n}\n")
    return rest[: end + 3]


def test_offline_pip_can_never_reach_the_network():
    """EVERY pip invocation on the offline path must carry --no-index.

    Asserting the flag merely appears somewhere in the function is not enough --
    there are two pip calls here, and a flag present on one would vouch for the
    other. (Verified by mutation: dropping --no-index from just the install call
    passed the weaker version of this test.)
    """
    body = _bash_function_body((REPO / "install.sh").read_text(encoding="utf-8"), "_pip_install_offline")
    # Fold shell line-continuations so each invocation is one logical line.
    logical = body.replace("\\\n", " ")
    # Match the INVOCATION, not the words: this function also prints a message
    # containing "pip install", which is not a command.
    calls = [ln for ln in logical.splitlines() if "python -m pip install" in ln]
    assert len(calls) == 2, f"expected the build-tools and the app install; found {len(calls)}"
    for call in calls:
        assert "--no-index" in call, f"pip invocation may reach the network: {call.strip()}"
        assert "--find-links" in call, f"pip invocation has no local source: {call.strip()}"
    app_install = [c for c in calls if " -e " in c]
    assert len(app_install) == 1, "expected exactly one editable install of the app"
    assert "--no-build-isolation" in app_install[0], (
        "build isolation would FETCH a build backend -- exactly what an air-gapped "
        "machine cannot do"
    )


def test_online_install_is_unchanged_when_no_bundle_is_present(tmp_path):
    """Behavioural: with OO_OFFLINE_BUNDLE unset, nothing offline may engage.

    Run from a throwaway copy of install.sh so the test cannot leave a .venv (or
    anything else) behind in the checkout it is testing.
    """
    sandbox = tmp_path / "checkout"
    (sandbox / "assets").mkdir(parents=True)
    shutil.copy2(REPO / "install.sh", sandbox / "install.sh")
    home = tmp_path / "home"
    home.mkdir()
    r = _run(
        sandbox / "install.sh",
        "--unattended",
        HOME=str(home),
        OO_SKIP_PIP="1",   # returns before touching the project
        OO_SKIP_DB="1",
        OO_MAKE_LAUNCHER="0",
        OO_AUTOLAUNCH="0",
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-2000:]
    assert "offline bundle" not in out.lower(), "offline mode engaged without a bundle"
    assert "--no-index" not in out
    # The online path still tells the user what it is about to download.
    assert "Estimated download" in out


def test_default_components_cannot_drift_between_builder_and_installer():
    """If these diverge, an offline install silently ships a DIFFERENT app than the
    online one -- and nobody would notice until a feature was missing in the field."""
    installer = (REPO / "install.sh").read_text(encoding="utf-8")
    builder = BUILDER_SH.read_text(encoding="utf-8")
    inst_default = installer.split('CHOSEN_EXTRAS="${OO_COMPONENTS:-', 1)[1].split('}"', 1)[0]
    build_default = builder.split('EXTRAS="${OO_COMPONENTS:-', 1)[1].split('}"', 1)[0]
    assert inst_default == build_default, (
        f"install.sh installs '{inst_default}' but the bundle builder packages "
        f"'{build_default}' -- the offline install would be missing components"
    )


# --------------------------------------------------------------------------- #
# The double-click entry point
# --------------------------------------------------------------------------- #
def test_desktop_launcher_resolves_its_own_location():
    """A .desktop shipped inside a zip cannot know where it will be extracted, so
    it must derive its folder from %k rather than carry an absolute path."""
    text = DESKTOP.read_text(encoding="utf-8")
    assert "%k" in text, "must locate itself via %k"
    assert "install-offline.sh" in text
    assert "Terminal=true" in text, "the user must be able to read progress and errors"
    exec_line = next(ln for ln in text.splitlines() if ln.startswith("Exec="))
    assert "/home/" not in exec_line and "$SRC_DIR" not in exec_line, (
        "no absolute or build-time path may be baked into Exec"
    )
