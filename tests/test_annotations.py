"""
Tests for crowdsourced signed annotation bundles (§6 D).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ACTION_PLAN Phase D acceptance: export a bundle, verify its signature; import two
conflicting bundles → the aggregation shows BOTH attributions (dissent, not averaged);
removing a trusted author cleanly removes their annotations; a tampered bundle is
refused; an untrusted author is excluded.
"""

from __future__ import annotations

import pytest

from src.annotations import bundle as bundle_mod
from src.annotations import store


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def _make_bundle(author_name: str, anns: list[tuple]) -> dict:
    """Build a signed bundle from a fresh signer in an isolated keys dir."""
    annotations = [bundle_mod.Annotation(target=t, kind=k, value=v) for t, k, v in anns]
    signer = bundle_mod.annotation_signer()
    return bundle_mod.build_signed_bundle(author_name, annotations, signer)


def test_export_then_verify(monkeypatch, tmp_path):
    store.add_annotation("cnn.com", "ownership", "owned by Example Corp", note="per filings")
    b = store.export_bundle()
    ok, reason, identity = bundle_mod.verify_bundle(b)
    assert ok, reason
    assert identity["ed25519_pub"]
    assert b["manifest"]["annotations"][0]["target"] == "cnn.com"


def test_tampered_bundle_is_refused():
    store.add_annotation("foo.test", "leaning", "lean-left")
    b = store.export_bundle()
    b["manifest"]["annotations"][0]["value"] = "lean-right"  # tamper after signing
    ok, reason, _ = bundle_mod.verify_bundle(b)
    assert not ok
    with pytest.raises(ValueError):
        store.import_bundle(b)


def test_conflicting_imports_show_both_attributions(tmp_path, monkeypatch):
    # Two independent authors (separate key dirs) disagree about the same source.
    d1 = tmp_path / "author1"
    d2 = tmp_path / "author2"
    monkeypatch.setenv("OO_DATA_DIR", str(d1))
    b1 = _make_bundle("Alice", [("acme.news", "leaning", "lean-left")])
    monkeypatch.setenv("OO_DATA_DIR", str(d2))
    b2 = _make_bundle("Bob", [("acme.news", "leaning", "lean-right")])

    # Import both into a third, clean store.
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "me"))
    store.import_bundle(b1, trusted=True)
    store.import_bundle(b2, trusted=True)

    agg = store.aggregate_for_target("acme.news")
    assert agg["total_assertions"] == 2
    values = {c["value"] for c in agg["claims"]}
    assert values == {"lean-left", "lean-right"}  # both shown, not averaged
    assert "leaning" in agg["dissent_kinds"]  # dissent surfaced honestly


def test_untrusted_author_is_excluded_then_removed(tmp_path, monkeypatch):
    d1 = tmp_path / "a"
    monkeypatch.setenv("OO_DATA_DIR", str(d1))
    b = _make_bundle("Carol", [("x.test", "coordination-tag", "network-A")])

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "me"))
    summary = store.import_bundle(b, trusted=True)
    aid = summary["author_id"]
    assert store.aggregate_for_target("x.test")["total_assertions"] == 1

    store.set_trusted(aid, False)
    assert store.aggregate_for_target("x.test")["total_assertions"] == 0  # untrusted -> excluded

    store.set_trusted(aid, True)
    assert store.remove_author(aid) is True
    assert store.aggregate_for_target("x.test")["total_assertions"] == 0  # removed cleanly


def test_invalid_kind_rejected():
    with pytest.raises(ValueError):
        bundle_mod.Annotation(target="t", kind="trust-score", value="9")
