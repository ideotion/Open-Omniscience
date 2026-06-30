"""
In-app Ollama installer (download + verify + run the OFFICIAL installer).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app's AI features need a local Ollama server. Until now the only way to get
one was a terminal (`curl https://ollama.com/install.sh | sh`) — the in-app
"Models" subtab could pull/remove models but never install the binary itself
(maintainer field test 2026-06-20: "can't find the AI installer"). This module
is the missing half, built to the maintainer's Q7=B ruling (2026-06-16):

  the app DOWNLOADS + RUNS the official per-OS Ollama installer, VERIFYING its
  checksum BEFORE exec, with consent + a VISIBLE OS elevation step, never silent.

HONESTY — how the long-standing "we can't fabricate per-OS checksums" blocker is
resolved WITHOUT inventing anything (a §0.5 non-negotiable):

  * We fetch GitHub's OWN attested SHA-256 for the official ``install.sh`` asset
    from the ollama/ollama *latest release* (the GitHub releases API returns a
    ``digest: "sha256:…"`` per asset), then download that exact asset and verify
    its bytes against the attested digest. The checksum is GitHub's attestation,
    never a value we hardcode or guess. A mismatch — or a release that does not
    attest one — REFUSES to run (degrade LOUDLY, never run unverified code).

  * Both the API call and the asset download go through the guarded fetch factory
    (kill switch + protected-mode proxy), so they obey airplane mode and never
    silently downgrade transport. The official script's OWN later download of the
    binary egresses over CLEARNET via curl (the same transport caveat as a model
    pull, maintainer Q9) — the UI discloses this at consent.

  * ELEVATION IS EXPLICIT AND NEVER HIDDEN. The official Linux installer uses
    sudo to place the binary and register a systemd service. We never hold root
    and never capture a password: the app verifies + stages the script, and
    either (a) runs it only when elevation is already available non-interactively
    (running as root, or passwordless ``sudo -n``) — so it can never hang on a
    password prompt — or (b) hands the user the exact VERIFIED command to paste
    into their own terminal, where their own sudo prompt appears. Both paths run
    the SAME bytes we verified — strictly more honest than the unverified
    ``curl … | sh`` the official docs suggest.

Scope: Linux (the V0.1 Debian target). macOS/Windows ship a graphical .dmg/.exe
installer that needs its own elevation UX, so for those we honestly point at
https://ollama.com/download rather than pretend to auto-install.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess  # noqa: S404 - we run only a GitHub-attested, hash-verified script
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from src.paths import data_dir

# The ollama/ollama latest-release API. Its assets carry GitHub-attested digests.
GITHUB_LATEST_RELEASE = "https://api.github.com/repos/ollama/ollama/releases/latest"
# The official Linux installer asset name within that release.
INSTALLER_ASSET_NAME = "install.sh"


class InstallerError(Exception):
    """Base class for installer failures."""


class InstallerUnavailable(InstallerError):
    """Network is off (airplane mode) or the platform has no scripted install."""


class InstallerVerificationError(InstallerError):
    """The downloaded installer did not match GitHub's attested checksum (or none
    was attested). We never run an unverified script."""


# --------------------------------------------------------------------------- #
#  Environment probes
# --------------------------------------------------------------------------- #


def ollama_present() -> bool:
    """True if an ``ollama`` binary is already on PATH (nothing to install)."""
    return shutil.which("ollama") is not None


def _is_root() -> bool:
    """True when the process can already write system paths without sudo."""
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def can_run_unattended() -> bool:
    """True when the app can run the installer WITHOUT prompting for a password —
    i.e. it is root, or passwordless ``sudo -n`` works. We only ever auto-run in
    that case, so the (web, TTY-less) backend can never hang on a sudo prompt.
    When this is False the UI offers the verified command for the user's terminal."""
    if _is_root():
        return True
    if shutil.which("sudo") is None:
        return False
    try:
        r = subprocess.run(  # noqa: S603,S607 - fixed argv, no shell, 5s cap
            ["sudo", "-n", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def platform_support() -> dict:
    """Describe the host OS and whether a scripted in-app install is supported.

    ``scripted`` True  -> Linux: the verified ``install.sh`` path below applies.
    ``scripted`` False -> macOS/Windows: an honest pointer to the graphical
    installer at ollama.com/download (its elevation UX is out of scope here).
    """
    system = platform.system().lower()
    arch = platform.machine().lower()
    if system == "linux":
        return {
            "os": "linux",
            "arch": arch,
            "scripted": True,
            "download_url": "https://ollama.com/download/linux",
        }
    if system == "darwin":
        return {
            "os": "macos",
            "arch": arch,
            "scripted": False,
            "download_url": "https://ollama.com/download/mac",
            "reason": "macOS ships a graphical installer (.dmg); download and run it, then return here.",
        }
    if system == "windows":
        return {
            "os": "windows",
            "arch": arch,
            "scripted": False,
            "download_url": "https://ollama.com/download/windows",
            "reason": "Windows ships a graphical installer (.exe); download and run it, then return here.",
        }
    return {
        "os": system or "unknown",
        "arch": arch,
        "scripted": False,
        "download_url": "https://ollama.com/download",
        "reason": f"No scripted installer for this platform ({system or 'unknown'}).",
    }


# --------------------------------------------------------------------------- #
#  Resolve + verify the official installer (the honest core)
# --------------------------------------------------------------------------- #

JsonGetter = Callable[[str], dict]
BytesGetter = Callable[[str], bytes]


@dataclass
class PreparedInstaller:
    """A downloaded, hash-verified, staged copy of the official installer."""

    version: str  # the release tag, e.g. "v0.30.11"
    sha256: str  # the verified SHA-256 (== GitHub's attestation)
    path: str  # where the verified script is staged on disk
    source_url: str  # the GitHub asset URL it came from

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "sha256": self.sha256,
            "path": self.path,
            "source_url": self.source_url,
            "manual_command": manual_command(self.path),
        }


def _attested_installer(release: dict) -> tuple[str, str, str]:
    """From a GitHub release JSON, find the official ``install.sh`` asset and its
    ATTESTED sha256. Returns ``(download_url, sha256_hex, version)``.

    Raises ``InstallerVerificationError`` if the asset is missing or GitHub does
    not attest a SHA-256 for it — we never run a script we cannot verify.
    """
    version = (release.get("tag_name") or "").strip()
    for asset in release.get("assets") or []:
        if asset.get("name") != INSTALLER_ASSET_NAME:
            continue
        url = asset.get("browser_download_url")
        digest = (asset.get("digest") or "").strip().lower()
        if not url:
            raise InstallerVerificationError("The release lists no download URL for install.sh.")
        if not digest.startswith("sha256:") or len(digest) != len("sha256:") + 64:
            raise InstallerVerificationError(
                "GitHub did not attest a SHA-256 for the official installer in this release; "
                "refusing to run an unverified script. Install Ollama from https://ollama.com/download."
            )
        return url, digest.split(":", 1)[1], version
    raise InstallerVerificationError(
        f"The official {INSTALLER_ASSET_NAME!r} asset was not found in the latest Ollama release."
    )


def resolve_and_verify(get_json: JsonGetter, get_bytes: BytesGetter) -> tuple[bytes, str, str, str]:
    """Fetch the latest release, download the official installer, and verify its
    bytes against GitHub's attested SHA-256.

    Returns ``(script_bytes, version, sha256_hex, source_url)``. Raises
    ``InstallerVerificationError`` on any mismatch. Fetchers are injected so the
    verification logic is unit-testable with no real network.
    """
    release = get_json(GITHUB_LATEST_RELEASE)
    url, attested, version = _attested_installer(release)
    data = get_bytes(url)
    actual = hashlib.sha256(data).hexdigest()
    if actual != attested:
        raise InstallerVerificationError(
            f"Installer checksum mismatch — GitHub attested sha256:{attested}, "
            f"downloaded sha256:{actual}. Refusing to run a tampered or corrupt script."
        )
    return data, version, actual, url


# --------------------------------------------------------------------------- #
#  Staging + running (elevation explicit, never silent)
# --------------------------------------------------------------------------- #

_STAGE_PREFIX = "ollama-install-"


def runtime_dir() -> Path:
    """Where verified installer scripts are staged (under the data dir)."""
    return data_dir() / "runtime"


def stage_installer(data: bytes, sha256_hex: str) -> Path:
    """Write the verified script to a sha-named file under the runtime dir.

    The filename embeds the verified digest so a later run can confirm it is the
    file we verified (and the run guard refuses anything outside this dir)."""
    d = runtime_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_STAGE_PREFIX}{sha256_hex[:16]}.sh"
    path.write_bytes(data)
    path.chmod(0o700)  # owner-only; the user runs it explicitly
    return path


def manual_command(path: str) -> str:
    """The exact command to run the staged, verified script in a terminal.

    Uses interactive sudo on Linux (the user types their own password in their
    terminal) — the verified-file equivalent of the official `curl … | sh`."""
    if _is_root():
        return f"sh {path}"
    return f"sudo sh {path}"


def _check_online() -> None:
    """Refuse network steps while the kill switch (airplane mode) is engaged."""
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise InstallerUnavailable(
            "Network is OFF (airplane mode): refusing to download the Ollama installer. "
            "Turn airplane mode off to install."
        )


def prepare_installer(
    get_json: JsonGetter | None = None, get_bytes: BytesGetter | None = None
) -> PreparedInstaller:
    """Download + verify + stage the official installer. Kill-switch gated.

    Raises ``InstallerUnavailable`` under airplane mode or on an unsupported OS,
    and ``InstallerVerificationError`` if the bytes don't match the attestation.
    """
    support = platform_support()
    if not support["scripted"]:
        raise InstallerUnavailable(
            support.get("reason", "No scripted installer for this platform.")
            + f" Download Ollama from {support['download_url']}."
        )
    _check_online()
    data, version, sha, url = resolve_and_verify(
        get_json or _default_get_json, get_bytes or _default_get_bytes
    )
    path = stage_installer(data, sha)
    return PreparedInstaller(version=version, sha256=sha, path=str(path), source_url=url)


def _validate_staged(path: str) -> Path:
    """Refuse to run anything that isn't a script we staged in the runtime dir."""
    p = Path(path).resolve()
    if (
        p.parent != runtime_dir().resolve()
        or not p.name.startswith(_STAGE_PREFIX)
        or not p.is_file()
    ):
        raise InstallerError(
            "Refusing to run a script outside the verified staging area. Re-run Prepare first."
        )
    return p


def run_installer(path: str) -> Iterator[str]:
    """Run the staged, verified installer, yielding its output lines.

    Only runs when elevation is available non-interactively (root or
    passwordless ``sudo -n``) so the TTY-less backend can never hang on a
    password prompt; otherwise it raises and the UI shows the manual command.
    The script's own download of the binary egresses over CLEARNET (Q9).
    """
    p = _validate_staged(path)
    _check_online()
    if _is_root():
        cmd = ["sh", str(p)]
    elif can_run_unattended():
        # -n: never prompt. We only reach here when sudo is already authorized.
        cmd = ["sudo", "-n", "sh", str(p)]
    else:
        raise InstallerError(
            "Elevated privileges are required to install Ollama and this app cannot prompt for "
            "a password. Run this in a terminal instead:\n  " + manual_command(path)
        )
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, verified script
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.stdout.close()
        code = proc.wait()
    yield f"__exit__ {code}"


# -- real fetchers (through the guarded factory) ----------------------------- #


def _default_get_json(url: str) -> dict:
    from src.safety.fetcher import guarded_session

    resp = guarded_session(isolation_token=url).get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _default_get_bytes(url: str) -> bytes:
    from src.safety.fetcher import guarded_session

    resp = guarded_session(isolation_token=url).get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def install_status() -> dict:
    """A snapshot for the AI tab: is Ollama present, is a scripted install
    possible, can we run it unattended, and any already-staged installer."""
    support = platform_support()
    staged = None
    try:
        d = runtime_dir()
        if d.is_dir():
            files = sorted(d.glob(f"{_STAGE_PREFIX}*.sh"))
            if files:
                latest = files[-1]
                staged = {"path": str(latest), "manual_command": manual_command(str(latest))}
    except OSError:
        staged = None
    return {
        "ollama_present": ollama_present(),
        "platform": support,
        "can_run_unattended": can_run_unattended() if support["scripted"] else False,
        "staged": staged,
    }
