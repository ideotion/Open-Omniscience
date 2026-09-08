"""
Tests for GUI-configurable custody settings (src/custody/settings.py) and the
settings API, plus the honesty invariants they must uphold:

* preferences persist and validate;
* a PQC toggle is a *request* -- the signer never claims "hybrid" it cannot
  produce, and turning PQC off forces Ed25519-only even when the library exists;
* the API reports effective (availability-aware) state, not the bare toggle;
* the GET /settings route is not swallowed by the dynamic /{item_id} route.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.custody import settings as cset
from src.custody.signing import PQC_AVAILABLE, HybridSigner


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _isolated_data(tmp_path, monkeypatch):
    # Keep the unit tests' settings file under tmp too (they don't use the client).
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


# --------------------------------------------------------------------------- #
# settings store
# --------------------------------------------------------------------------- #


def test_defaults_are_local_pqc_off_and_autolog_on():
    # auto_log_on_ingest is ON by default (maintainer ruling 2026-06-15 Item-N);
    # it is a local-only write (anchoring_mode="local", no network). OTS/PQC stay
    # opt-in.
    s = cset.load_settings()
    assert s.anchoring_mode == "local"
    assert s.pqc_enabled is False
    assert s.auto_log_on_ingest is True


def test_save_partial_update_persists():
    cset.save_settings({"pqc_enabled": True})
    cset.save_settings({"default_actor": "  reporter  "})
    s = cset.load_settings()
    assert s.pqc_enabled is True  # earlier update preserved
    assert s.default_actor == "reporter"  # trimmed
    assert s.anchoring_mode == "local"  # untouched key keeps its default


def test_invalid_anchoring_mode_rejected_and_not_written():
    with pytest.raises(cset.CustodySettingsError):
        cset.save_settings({"anchoring_mode": "ethereum"})
    assert cset.load_settings().anchoring_mode == "local"


def test_corrupt_file_falls_back_to_defaults():
    cset._settings_path().write_text("{ not json", "utf-8")
    s = cset.load_settings()  # must not raise
    assert s.anchoring_mode == "local"


def test_auto_log_default_seeds_from_legacy_config(monkeypatch):
    monkeypatch.setenv("OO_CUSTODY_ON_INGEST", "1")
    from src.config import reset_config

    reset_config()
    try:
        assert cset.load_settings().auto_log_on_ingest is True
    finally:
        monkeypatch.delenv("OO_CUSTODY_ON_INGEST", raising=False)
        reset_config()


# --------------------------------------------------------------------------- #
# signer honesty under the toggle
# --------------------------------------------------------------------------- #


def test_use_pqc_false_forces_ed25519(tmp_path):
    signer = HybridSigner(use_pqc=False)
    sig = signer.sign(b"payload")
    assert sig["algorithm"] == "ed25519"
    assert signer.is_hybrid is False
    assert signer.public_identity().ml_dsa_pub is None


def test_pqc_unavailable_but_requested_is_honest():
    signer = HybridSigner(use_pqc=True)
    # Effective hybridness must track real availability, never the mere request.
    assert signer.is_hybrid is PQC_AVAILABLE
    assert signer.pqc_unavailable_but_requested is (not PQC_AVAILABLE)
    assert signer.sign(b"x")["algorithm"] == ("hybrid" if PQC_AVAILABLE else "ed25519")


# --------------------------------------------------------------------------- #
# settings API
# --------------------------------------------------------------------------- #


def test_get_settings_not_shadowed_by_item_route(client):
    r = client.get("/api/custody/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    # Real settings payload, not a "no custody entries for 'settings'" 404.
    assert body["anchoring_mode"] == "local"
    assert "pqc_available" in body and "ots_available" in body


def test_put_reports_effective_state(client):
    r = client.put("/api/custody/settings", json={"pqc_enabled": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pqc_enabled"] is True
    # effective only when the library is actually present
    assert body["pqc_effective"] == body["pqc_available"]


def test_put_invalid_mode_400(client):
    r = client.put("/api/custody/settings", json={"anchoring_mode": "ipfs"})
    assert r.status_code == 400


def test_put_then_get_roundtrip(client):
    client.put(
        "/api/custody/settings",
        json={
            "anchoring_mode": "opentimestamps",
            "auto_log_on_ingest": True,
            "ots_consent": True,
        },
    )
    body = client.get("/api/custody/settings").json()
    assert body["anchoring_mode"] == "opentimestamps"
    assert body["auto_log_on_ingest"] is True
    # ots_effective must reflect availability, not the request alone.
    assert body["ots_effective"] == body["ots_available"]


# --------------------------------------------------------------------------- #
# P1 audit finding (2026-09-08): the informed-consent gate on turning
# OpenTimestamps anchoring ON (see also tests/test_custody_consent_gates.py,
# which covers the same rule at the src.custody.settings.save_settings level
# without needing the full app import).
# --------------------------------------------------------------------------- #


def test_put_opentimestamps_without_consent_is_refused(client):
    r = client.put("/api/custody/settings", json={"anchoring_mode": "opentimestamps"})
    assert r.status_code == 400, r.text
    assert "consent" in r.json()["detail"].lower()
    # Refused BEFORE anything was written -- the effective state is still local.
    assert client.get("/api/custody/settings").json()["anchoring_mode"] == "local"


def test_put_opentimestamps_with_consent_succeeds(client):
    r = client.put(
        "/api/custody/settings",
        json={"anchoring_mode": "opentimestamps", "ots_consent": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["anchoring_mode"] == "opentimestamps"


def test_put_resave_while_already_opentimestamps_does_not_need_consent_again(client):
    r1 = client.put(
        "/api/custody/settings",
        json={"anchoring_mode": "opentimestamps", "ots_consent": True},
    )
    assert r1.status_code == 200, r1.text
    # Resave some OTHER field, mode included but unchanged, no consent this time.
    r2 = client.put(
        "/api/custody/settings",
        json={"anchoring_mode": "opentimestamps", "default_actor": "reporter"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["default_actor"] == "reporter"


def test_put_ots_consent_flag_is_not_echoed_back_or_persisted(client):
    client.put(
        "/api/custody/settings",
        json={"anchoring_mode": "opentimestamps", "ots_consent": True},
    )
    body = client.get("/api/custody/settings").json()
    assert "ots_consent" not in body
