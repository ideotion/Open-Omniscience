"""An exported custody log FAILS CLOSED: empty, cut at its end, cut mid-record or without its signed head, it is
refused by name; a whole log, and a whole one-item export, still verify.

Lane M (routes without UI, PR #1954) found the POST /api/custody/verify checker passed an empty or end-truncated log
and failed a genuine one-item export, which is why it was left without a button.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.custody.log import ITEM_SCOPE_NOTE, CustodyAction, CustodyLog, verify_export
from src.custody.signing import HybridSigner

ROOT = Path(__file__).resolve().parents[1]


def _log(tmp_path: Path, name: str = "") -> CustodyLog:
    signer = HybridSigner(ed25519_path=tmp_path / f"ed{name}.pem", mldsa_path=tmp_path / f"ml{name}.key")
    return CustodyLog(db_path=str(tmp_path / f"custody{name}.db"), signer=signer)


@pytest.fixture()
def bundle(tmp_path):
    with _log(tmp_path) as log:
        log.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
        log.record("article:1", "a" * 64, CustodyAction.ACCESS, actor="alice")
        log.record("article:2", "b" * 64, CustodyAction.INGEST, actor="pipeline")
        log.record("article:1", "a" * 64, CustodyAction.EXPORT, actor="alice")
        yield log.export(), log.export(item_id="article:1")


def test_a_whole_log_passes(bundle):
    full, _ = bundle
    assert verify_export(full) == (True, [])
    assert verify_export(full, require_signer=True) == (True, [])


def test_a_whole_one_item_export_passes(bundle):
    _, item = bundle
    assert [e["seq"] for e in item["entries"]] == [1, 2, 4]  # a selection: the seqs skip
    assert verify_export(item, require_signer=True) == (True, [])


@pytest.mark.parametrize("entries", [[], None, "x"])
def test_an_empty_log_is_refused(bundle, entries):
    full, _ = bundle
    b = {**full, "entries": entries}
    ok, issues = verify_export(b)
    assert not ok and issues[0].startswith("empty log")


@pytest.mark.parametrize("which", [0, 1])
def test_a_log_cut_at_its_end_is_refused(bundle, which):
    b = copy.deepcopy(bundle[which])
    b["entries"] = b["entries"][:-1]  # every remaining link still holds: only the signed head can show the cut
    ok, issues = verify_export(b)
    assert not ok and issues[0].startswith("truncated or padded")


def test_a_cut_whose_count_was_rewritten_is_refused(bundle):
    b = copy.deepcopy(bundle[0])
    b["entries"] = b["entries"][:-1]
    b["entry_count"] = 3
    b["head"]["entry_count"] = 3  # rewriting the head breaks its signature
    ok, issues = verify_export(b)
    assert not ok and issues[0].startswith("head signature invalid")


def test_a_head_re_signed_with_another_key_is_refused(bundle, tmp_path):
    from src.custody.signing import canonical_bytes

    b = copy.deepcopy(bundle[0])
    b["entries"] = b["entries"][:-1]
    b["entry_count"] = 3
    last = b["entries"][-1]
    b["head"].update(entry_count=3, last_seq=last["seq"], last_entry_hash=last["entry_hash"])
    other = HybridSigner(ed25519_path=tmp_path / "atk.pem", mldsa_path=tmp_path / "atk.key")
    b["head_signature"] = other.sign(canonical_bytes(b["head"]))
    ok, issues = verify_export(b)  # not even pinned: the head must carry the entries' own key
    assert not ok and issues[0].startswith("head signature invalid")


@pytest.mark.parametrize("cut", [
    lambda e: {k: v for k, v in e.items() if k not in ("signature", "timestamp")},  # the record's tail is gone
    lambda e: {"seq": e["seq"], "item_id": e["item_id"]},
    lambda e: "{\"seq\": 4, \"item_id\": \"artic",
])
def test_a_log_whose_last_record_is_cut_mid_record_is_refused(bundle, cut):
    b = copy.deepcopy(bundle[0])
    b["entries"][-1] = cut(b["entries"][-1])
    ok, issues = verify_export(b)
    assert not ok and "is not a whole record" in issues[0] and issues[0].startswith("entry 4 of 4")


def test_a_bundle_without_a_signed_head_is_refused(bundle):
    b = copy.deepcopy(bundle[0])
    del b["head"], b["head_signature"]
    ok, issues = verify_export(b)
    assert not ok and issues[0].startswith("no signed head") and "export it again" in issues[0]


def test_a_whole_log_bundle_relabelled_as_one_item_is_refused(bundle):
    full, item = bundle
    b = copy.deepcopy(full)
    b["item_id"] = "article:1"
    b["head"]["item_id"] = "article:1"
    ok, issues = verify_export(b)
    assert not ok  # the head was signed for the whole log, so its scope no longer matches


def test_the_route_refuses_and_names_the_scope(bundle, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    full, item = bundle
    with TestClient(app) as c:
        r = c.post("/api/custody/verify", json={"bundle": {**full, "entries": []}})
        assert r.status_code == 200 and r.json()["verified"] is False and r.json()["issues"][0].startswith("empty log")
        r = c.post("/api/custody/verify", json={"bundle": item})
        assert r.json()["verified"] is True and r.json()["scope"] == ITEM_SCOPE_NOTE


def test_the_cli_refuses_a_file_cut_mid_record(bundle, tmp_path):
    full, _ = bundle
    text = json.dumps(full)
    p = tmp_path / "cut.json"
    p.write_text(text[: len(text) - 40])  # cut inside the last record
    r = subprocess.run([sys.executable, str(ROOT / "scripts/verify_custody.py"), str(p)], capture_output=True, text=True)
    assert r.returncode == 1 and "not a readable custody bundle" in r.stdout and "Traceback" not in r.stderr
    whole = tmp_path / "whole.json"
    whole.write_text(text)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/verify_custody.py"), str(whole)], capture_output=True, text=True)
    assert r.returncode == 0 and "VERIFIED       : True" in r.stdout


def test_a_one_item_bundle_with_a_middle_entry_re_signed_by_another_key_is_refused(bundle, tmp_path):
    """Security read: a one-item bundle has no links, so a middle entry rewritten and re-signed must still fail."""
    from hashlib import sha256

    from src.custody.log import CustodyEntry, _entry_digest
    from src.custody.signing import canonical_bytes

    b = copy.deepcopy(bundle[1])
    e = CustodyEntry.from_dict(b["entries"][1])
    e.metadata = {"note": "rewritten"}
    partial = {k: v for k, v in e.signable_core().items() if k != "timestamp"}
    e.timestamp = {**e.timestamp, "digest": sha256(canonical_bytes(partial)).hexdigest()}
    e.entry_hash = _entry_digest(e.signable_core())
    atk = HybridSigner(ed25519_path=tmp_path / "atk.pem", mldsa_path=tmp_path / "atk.key")
    e.signature = atk.sign(canonical_bytes(e.signable_core()))
    b["entries"][1] = e.to_dict()
    ok, issues = verify_export(b)
    assert not ok and issues[0].startswith("the signing key changes at seq")


@pytest.mark.parametrize("mutate", [
    lambda b: b["entries"][0].__setitem__("signature", {"ed25519": "s"}),
    lambda b: b["entries"][0].__setitem__("signature", "s"),
    lambda b: b["entries"][-1].__setitem__("seq", "9"),
    lambda b: b["entries"][-1].__setitem__("seq", True),
    lambda b: b["entries"][-1].__setitem__("timestamp", "z"),
    lambda b: b["entries"][-1].__setitem__("metadata", []),
    lambda b: b.__setitem__("head_signature", {"ed25519": "s"}),
    lambda b: b.__setitem__("head_signature", "s"),
    lambda b: b.__setitem__("signer", "s"),
    lambda b: b["entries"][-1].__setitem__("metadata", {"note": "\ud800"}),
    lambda b: b["entries"][-1].__setitem__("item_id", "\ud800"),
    lambda b: b["head"].__setitem__("item_id", "\ud800"),
])
@pytest.mark.parametrize("which", [0, 1])
def test_odd_shapes_are_refused_by_name_never_raised(bundle, mutate, which):
    b = copy.deepcopy(bundle[which])
    mutate(b)
    ok, issues = verify_export(b, require_signer=True)
    assert not ok and issues


def test_a_refused_bundle_states_no_scope(bundle):
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.post("/api/custody/verify", json={"bundle": {**bundle[1], "entries": []}})
    assert r.json()["verified"] is False and r.json()["scope"] is None


def test_a_cut_log_with_a_tail_re_signed_by_another_key_is_refused_even_unpinned(tmp_path):
    """Second security read: keep entries 1-2, forge entry 3 with key B, sign the head with B, leave signer = A."""
    from src.custody.signing import canonical_bytes

    with _log(tmp_path, "a") as real:
        for n in range(5):
            real.record(f"article:{n}", "a" * 64, CustodyAction.INGEST, actor="pipeline")
        genuine = real.export()
    with _log(tmp_path, "b") as forger:
        forger.record("article:0", "a" * 64, CustodyAction.INGEST, actor="pipeline")
        forger.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
        tail = forger.record("article:9", "z" * 64, CustodyAction.INGEST, actor="x")
        b = copy.deepcopy(genuine)
        b["entries"] = b["entries"][:2]
        # Re-link the forged tail onto the genuine entry 2 and re-sign it with key B.
        from hashlib import sha256

        from src.custody.log import CustodyEntry, _entry_digest

        e = CustodyEntry.from_dict(tail.to_dict())
        e.prev_entry_hash = b["entries"][-1]["entry_hash"]
        partial = {k: v for k, v in e.signable_core().items() if k != "timestamp"}
        e.timestamp = {**e.timestamp, "digest": sha256(canonical_bytes(partial)).hexdigest()}
        e.entry_hash = _entry_digest(e.signable_core())
        e.signature = forger.signer.sign(canonical_bytes(e.signable_core()))
        b["entries"].append(e.to_dict())
        b["entry_count"] = 3
        b["head"] = {**b["head"], "entry_count": 3, "last_seq": e.seq, "last_entry_hash": e.entry_hash}
        b["head_signature"] = forger.signer.sign(canonical_bytes(b["head"]))
    ok, issues = verify_export(b)
    assert not ok and issues[0].startswith("head signature invalid")
    # and with the signer relabelled to B, the key change is named
    b["signer"] = {**b["signer"], "ed25519_pub": b["head_signature"]["ed25519"]["pub"]}
    ok, issues = verify_export(b)
    assert not ok and issues[0].startswith("the signing key changes at seq 3 with no key-rotation record")


def test_an_item_bundle_carrying_another_items_entry_is_refused(tmp_path):
    """Self-consistent: one key, a head re-signed for the padded entries, yet a foreign entry inside."""
    from src.custody.log import _bundle_head
    from src.custody.signing import canonical_bytes

    signer = HybridSigner(ed25519_path=tmp_path / "k.pem", mldsa_path=tmp_path / "k.key")
    with CustodyLog(db_path=str(tmp_path / "c.db"), signer=signer) as log:
        log.record("article:1", "a" * 64, CustodyAction.INGEST)
        log.record("article:2", "b" * 64, CustodyAction.INGEST)
        log.record("article:1", "a" * 64, CustodyAction.ACCESS)
        b = log.export(item_id="article:1")
        foreign = log.entries_for("article:2")[0]
        entries = sorted([*log.entries_for("article:1"), foreign], key=lambda e: e.seq)
    b["entries"] = [e.to_dict() for e in entries]
    b["entry_count"] = len(entries)
    b["head"] = _bundle_head("article:1", entries)
    b["head_signature"] = signer.sign(canonical_bytes(b["head"]))
    ok, issues = verify_export(b)
    assert not ok and issues == ["the bundle is for 'article:1' but holds entries of other items"]


def test_a_lone_surrogate_is_refused_by_the_route_and_the_cli(bundle, tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    text = json.dumps(bundle[0]).replace('"article:2"', '"\\ud800"', 1)
    assert "\\ud800" in text
    with TestClient(app) as c:
        r = c.post("/api/custody/verify", content=text.join(['{"bundle": ', '}']),
                   headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.json()["verified"] is False and "surrogate" in r.json()["issues"][0]
    path = tmp_path / "b.json"
    path.write_text(text)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/verify_custody.py"), str(path)], capture_output=True, text=True)
    assert r.returncode == 1 and "surrogate" in r.stdout and "Traceback" not in r.stderr


def test_an_empty_item_bundle_is_named_as_such(tmp_path):
    with _log(tmp_path) as log:
        log.record("article:1", "a" * 64, CustodyAction.INGEST)
        b = log.export(item_id="article:9")
    ok, issues = verify_export(b)
    assert not ok and issues[0].startswith("this item has no custody entries")
