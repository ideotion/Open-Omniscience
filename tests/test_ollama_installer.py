"""
Tests for the in-app Ollama binary installer (download + verify + run).

The verification core is exercised with INJECTED fetchers (no real network): the
honesty guarantees — verify against GitHub's attested SHA-256, refuse on mismatch
or a missing attestation, refuse under airplane mode, and never run a script
outside the verified staging area — are all proven here.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib

import pytest

from src.llm import installer


@pytest.fixture(autouse=True)
def _runtime_dir(tmp_path, monkeypatch):
    """Stage installer scripts under a temp dir, not the real data dir."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # Make sure the kill switch starts clear for each test.
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    yield
    clear_kill_switch()


_SCRIPT = b"#!/bin/sh\necho 'official ollama installer'\n"
_SHA = hashlib.sha256(_SCRIPT).hexdigest()


def _release(digest: str | None = f"sha256:{_SHA}", *, with_asset: bool = True) -> dict:
    assets = []
    if with_asset:
        asset = {
            "name": "install.sh",
            "browser_download_url": "https://example.test/ollama/install.sh",
        }
        if digest is not None:
            asset["digest"] = digest
        assets.append(asset)
    # Some unrelated assets, to prove we pick the right one.
    assets.append({"name": "ollama-linux-amd64.tar.zst", "digest": "sha256:" + "0" * 64})
    return {"tag_name": "v9.9.9", "assets": assets}


def _getters(release: dict, body: bytes = _SCRIPT):
    return (lambda _url: release), (lambda _url: body)


def test_resolve_and_verify_accepts_matching_digest():
    get_json, get_bytes = _getters(_release())
    data, version, sha, url = installer.resolve_and_verify(get_json, get_bytes)
    assert data == _SCRIPT
    assert version == "v9.9.9"
    assert sha == _SHA
    assert url == "https://example.test/ollama/install.sh"


def test_resolve_and_verify_refuses_checksum_mismatch():
    # GitHub attests one hash; the bytes we download are different -> refuse.
    get_json, get_bytes = _getters(_release(), body=b"tampered!\n")
    with pytest.raises(installer.InstallerVerificationError):
        installer.resolve_and_verify(get_json, get_bytes)


def test_resolve_and_verify_refuses_missing_attestation():
    # A release that does not attest a sha256 must NOT be run on faith.
    get_json, get_bytes = _getters(_release(digest=None))
    with pytest.raises(installer.InstallerVerificationError):
        installer.resolve_and_verify(get_json, get_bytes)


def test_resolve_and_verify_refuses_when_asset_absent():
    get_json, get_bytes = _getters(_release(with_asset=False))
    with pytest.raises(installer.InstallerVerificationError):
        installer.resolve_and_verify(get_json, get_bytes)


def test_prepare_stages_a_verified_script(monkeypatch):
    monkeypatch.setattr(installer, "platform_support", lambda: {"os": "linux", "arch": "x86_64", "scripted": True, "download_url": "x"})
    get_json, get_bytes = _getters(_release())
    prepared = installer.prepare_installer(get_json, get_bytes)
    assert prepared.sha256 == _SHA
    p = installer.Path(prepared.path)
    assert p.is_file()
    assert p.read_bytes() == _SCRIPT
    assert p.parent == installer.runtime_dir().resolve()
    # The staged path round-trips through install_status().
    st = installer.install_status()
    assert st["staged"] and st["staged"]["path"] == prepared.path


def test_prepare_refuses_under_airplane_mode(monkeypatch):
    monkeypatch.setattr(installer, "platform_support", lambda: {"os": "linux", "arch": "x86_64", "scripted": True, "download_url": "x"})
    from src.ingest import activate_kill_switch

    activate_kill_switch()
    get_json, get_bytes = _getters(_release())
    with pytest.raises(installer.InstallerUnavailable):
        installer.prepare_installer(get_json, get_bytes)


def test_prepare_refuses_unsupported_platform(monkeypatch):
    monkeypatch.setattr(
        installer,
        "platform_support",
        lambda: {"os": "macos", "arch": "arm64", "scripted": False, "download_url": "https://ollama.com/download/mac", "reason": "macOS ships a graphical installer."},
    )
    get_json, get_bytes = _getters(_release())
    with pytest.raises(installer.InstallerUnavailable):
        installer.prepare_installer(get_json, get_bytes)


def test_run_refuses_a_script_outside_the_staging_area(tmp_path):
    rogue = tmp_path / "rogue.sh"
    rogue.write_text("#!/bin/sh\necho pwned\n")
    with pytest.raises(installer.InstallerError):
        list(installer.run_installer(str(rogue)))


def test_run_refuses_a_wrongly_named_file_in_the_staging_area():
    d = installer.runtime_dir()
    d.mkdir(parents=True, exist_ok=True)
    bad = d / "not-an-installer.sh"
    bad.write_text("#!/bin/sh\necho nope\n")
    with pytest.raises(installer.InstallerError):
        list(installer.run_installer(str(bad)))


def test_run_refuses_when_no_unattended_elevation(monkeypatch):
    # Stage a real verified script, then deny elevation -> a clear error naming
    # the manual command, never a hang.
    monkeypatch.setattr(installer, "platform_support", lambda: {"os": "linux", "arch": "x86_64", "scripted": True, "download_url": "x"})
    get_json, get_bytes = _getters(_release())
    prepared = installer.prepare_installer(get_json, get_bytes)
    monkeypatch.setattr(installer, "_is_root", lambda: False)
    monkeypatch.setattr(installer, "can_run_unattended", lambda: False)
    with pytest.raises(installer.InstallerError) as ei:
        list(installer.run_installer(prepared.path))
    assert "terminal" in str(ei.value).lower()


def test_run_executes_as_root_and_reports_exit(monkeypatch):
    # As "root" we run the staged script directly (sh <path>); a trivially-true
    # script exits 0 and the generator reports it.
    monkeypatch.setattr(installer, "platform_support", lambda: {"os": "linux", "arch": "x86_64", "scripted": True, "download_url": "x"})
    body = b"#!/bin/sh\necho hello-from-installer\nexit 0\n"
    get_json, get_bytes = _getters(_release(digest="sha256:" + hashlib.sha256(body).hexdigest()), body=body)
    prepared = installer.prepare_installer(get_json, get_bytes)
    monkeypatch.setattr(installer, "_is_root", lambda: True)
    out = list(installer.run_installer(prepared.path))
    assert any("hello-from-installer" in line for line in out)
    assert out[-1] == "__exit__ 0"


def test_platform_support_linux_is_scripted():
    # The real host running the suite is Linux (CI) — sanity-check the contract.
    import platform as _p

    if _p.system().lower() == "linux":
        assert installer.platform_support()["scripted"] is True
