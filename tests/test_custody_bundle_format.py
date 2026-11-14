"""R714: a custody export's signed head commits to every entry hash (bundle format 2).

Before, the head committed to the count and the last entry only, so in a one-item bundle -- whose entries are not
linked to each other -- an entry in the middle could be swapped for another one signed by the same key (two logs that
share a key after a restore onto a second machine) and still verify. Format 2 refuses that by name. A format-1 bundle
is still read, but its verdict says it is the weaker, older format and what that does not prove.
"""

from __future__ import annotations

import copy
import shutil
import subprocess
import sys
from pathlib import Path

from src.custody.log import (
    BUNDLE_FORMAT,
    LEGACY_FORMAT_NOTE,
    CustodyAction,
    CustodyEntry,
    CustodyLog,
    _bundle_head,
    verify_export_report,
)
from src.custody.signing import HybridSigner, canonical_bytes

ROOT = Path(__file__).resolve().parents[1]


def _signer(tmp_path: Path) -> HybridSigner:
    return HybridSigner(ed25519_path=tmp_path / "k.pem", mldsa_path=tmp_path / "k.key", use_pqc=False)


def _forked_item_bundles(tmp_path: Path) -> tuple[dict, dict, HybridSigner]:
    """Item X at seq 1, 3, 5 in the real log; a copy of the log (same key) writes another seq 3 for X."""
    signer = _signer(tmp_path)
    real, fork = str(tmp_path / "real.db"), str(tmp_path / "fork.db")
    with CustodyLog(db_path=real, signer=signer, anchoring_mode="local") as log:
        log.record("article:x", "a" * 64, CustodyAction.INGEST)
        log.record("article:y", "b" * 64, CustodyAction.INGEST)
    shutil.copy(real, fork)
    with CustodyLog(db_path=real, signer=signer, anchoring_mode="local") as log:
        log.record("article:x", "a" * 64, CustodyAction.REDACT)
        log.record("article:y", "b" * 64, CustodyAction.ACCESS)
        log.record("article:x", "a" * 64, CustodyAction.ACCESS)
        bundle = log.export(item_id="article:x")
    with CustodyLog(db_path=fork, signer=signer, anchoring_mode="local") as log:
        log.record("article:x", "a" * 64, CustodyAction.ACCESS)
        other = log.export(item_id="article:x")
    return bundle, other, signer


def _swap_middle(bundle: dict, other: dict) -> dict:
    b = copy.deepcopy(bundle)
    assert b["entries"][1]["seq"] == other["entries"][1]["seq"] == 3
    b["entries"][1] = copy.deepcopy(other["entries"][1])  # the fork's seq 3: ACCESS instead of REDACT
    return b


def _as_format_1(bundle: dict, signer: HybridSigner) -> dict:
    """What an export made by a build between the signed head and R714 looked like: a head with no format and no
    digest, signed by the same key."""
    b = copy.deepcopy(bundle)
    b.pop("bundle_format", None)
    entries = [CustodyEntry.from_dict(d) for d in b["entries"]]
    b["head"] = _bundle_head(b["item_id"], entries, bundle_format=1)
    b["head_signature"] = signer.sign(canonical_bytes(b["head"]))
    return b


def test_new_exports_are_format_2_and_verify_with_the_full_guarantee(tmp_path):
    bundle, _other, _signer_ = _forked_item_bundles(tmp_path)
    assert bundle["head"]["bundle_format"] == BUNDLE_FORMAT == 2 and bundle["head"]["entries_digest"]
    r = verify_export_report(bundle, require_signer=True)
    assert r["verified"] and r["format"] == 2 and r["format_note"] is None


def test_a_swapped_middle_entry_is_refused_in_format_2(tmp_path):
    bundle, other, _s = _forked_item_bundles(tmp_path)
    r = verify_export_report(_swap_middle(bundle, other), require_signer=True)
    assert not r["verified"] and "entry hashes its signed head commits to" in r["issues"][0]


def test_a_format_1_bundle_still_verifies_but_is_said_to_be_weaker(tmp_path):
    bundle, other, signer = _forked_item_bundles(tmp_path)
    old = _as_format_1(bundle, signer)
    r = verify_export_report(old, require_signer=True)
    assert r["verified"] and r["format"] == 1 and r["format_note"] == LEGACY_FORMAT_NOTE
    # ...and the weakness is real, which is why it is said: the same swap passes a format-1 head.
    swapped = verify_export_report(_as_format_1(_swap_middle(bundle, other), signer), require_signer=True)
    assert swapped["verified"] and swapped["format"] == 1


def test_a_format_2_head_cannot_be_downgraded_or_given_an_unknown_format(tmp_path):
    bundle, _other, signer = _forked_item_bundles(tmp_path)
    stripped = copy.deepcopy(bundle)  # the format fields taken out of a signed head: its signature no longer holds
    del stripped["head"]["bundle_format"], stripped["head"]["entries_digest"]
    assert not verify_export_report(stripped)["verified"]
    future = copy.deepcopy(bundle)
    future["head"]["bundle_format"] = 3
    future["head_signature"] = signer.sign(canonical_bytes(future["head"]))
    r = verify_export_report(future)
    assert not r["verified"] and "unknown bundle format 3" in r["issues"][0]


def test_the_cli_and_the_route_say_which_format(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    bundle, _other, signer = _forked_item_bundles(tmp_path)
    old = _as_format_1(bundle, signer)
    path = tmp_path / "old.json"
    path.write_text(__import__("json").dumps(old), encoding="utf-8")
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_custody.py"), str(path)],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0 and "older export format" in out.stdout and "weaker guarantee" in out.stdout
    assert "VERIFIED       : True (old format: weaker guarantee)" in out.stdout
    r = TestClient(app).post("/api/custody/verify", json={"bundle": old})
    assert r.json()["verified"] and r.json()["format"] == 1 and "weaker guarantee" in r.json()["format_note"]
