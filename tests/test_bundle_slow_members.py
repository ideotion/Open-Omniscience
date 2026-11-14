"""Row 18 (2026-11-14): the two slow all-diagnostics members stop rerunning every card producer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured on a 200k-article generated corpus, ``leads-quality.json`` took 86 s and
``bulletin-weekly.json`` 107 s, and most of both was the card producer pass, which the same
bundle also runs in ``card-audit.json``. In the bundle now:

* leads-quality reads Home's cached feed when Home itself would serve it as fresh, and runs the
  producers as before otherwise;
* bulletin-weekly leaves its cards section unbuilt and lists it with the reason.

What may not regress: each member's FILE says what it did in plain words, the MANIFEST entry
repeats it (``bundle_note``), and the routes on their own still serve the full report.
"""

from __future__ import annotations

import io
import json
import zipfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import leads_quality as LQ
from src.database.models import Base


def _sess():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _cached_card(**over):
    card = {
        "id": "c1", "type": "rising_now", "title": "t", "bucket": "context", "key": "k1", "n": 60,
        "signal": {"metric": "value", "value": 60}, "article_ids": [1, 2, 3],
        "evidence": [{"outlet": "a.example"}, {"outlet": "b.example"}, {"source": "Feed C"}, {"outlet": "a.example"}],
    }
    card.update(over)
    return card


def _payload(**over):
    p = {"version": "oo-briefing-cache-3", "generated_at": "2026-11-14T10:00:00", "article_count": 0,
         "cards": [_cached_card()]}
    p.update(over)
    return p


def _no_producer_pass(monkeypatch):
    calls = []

    def _boom(*a, **k):
        calls.append(1)
        return [], {"producers_run": 0, "producers_total": 0, "truncated": False}

    monkeypatch.setattr("src.briefing.registry.run_all_bounded", _boom)
    return calls


# --------------------------------------------------------------------------- #
# leads-quality                                                               #
# --------------------------------------------------------------------------- #


def test_a_fresh_home_feed_is_read_and_the_file_says_so(monkeypatch):
    calls = _no_producer_pass(monkeypatch)
    monkeypatch.setattr("src.briefing.service._read_cache", lambda: _payload())
    out = LQ.leads_quality_report(_sess(), prefer_home_cache=True)

    assert calls == [], "a fresh Home feed must not run the producers again"
    assert out["source"] == "home-cache"
    assert out["feed_generated_at"] == "2026-11-14T10:00:00"
    assert "Home's cached feed" in out["source_note"] and "2026-11-14T10:00:00" in out["source_note"]
    assert out["bundle_note"] == out["source_note"]
    row = out["cards"][0]
    # The same leads.py helpers read the cached dict: three distinct outlets (a, b, and C by its label).
    assert row["distinct_outlets"] == 3
    assert row["article_ids_count"] == 3
    assert row["major"]["sources"] == 3 and row["major"]["n"] == 60
    assert out["truncated"] is False and "PARTIAL" not in out["caveat"]


def test_a_stale_home_feed_falls_back_to_the_producer_pass(monkeypatch):
    calls = _no_producer_pass(monkeypatch)
    monkeypatch.setattr("src.briefing.service._read_cache", lambda: _payload())
    monkeypatch.setattr("src.briefing.service._is_cache_stale", lambda s, p, **k: True)
    out = LQ.leads_quality_report(_sess(), prefer_home_cache=True)

    assert calls == [1]
    assert out["source"] == "producer-pass"
    assert "bundle_note" not in out


def test_no_cache_and_an_unreadable_cache_fall_back(monkeypatch):
    calls = _no_producer_pass(monkeypatch)
    monkeypatch.setattr("src.briefing.service._read_cache", lambda: None)
    assert LQ.leads_quality_report(_sess(), prefer_home_cache=True)["source"] == "producer-pass"

    def _raise():
        raise OSError("disk")

    monkeypatch.setattr("src.briefing.service._read_cache", _raise)
    assert LQ.leads_quality_report(_sess(), prefer_home_cache=True)["source"] == "producer-pass"
    assert calls == [1, 1]


def test_a_partial_home_feed_is_marked_partial(monkeypatch):
    _no_producer_pass(monkeypatch)
    monkeypatch.setattr(
        "src.briefing.service._read_cache",
        lambda: _payload(incomplete_reason="memory short", stopped_producers=[{"name": "x", "seconds": 1.0}]),
    )
    out = LQ.leads_quality_report(_sess(), prefer_home_cache=True)
    assert out["truncated"] is True
    assert "PARTIAL" in out["caveat"] and "memory short" in out["caveat"]
    assert out["stopped_producers"] == [{"name": "x", "seconds": 1.0}]


def test_the_route_on_its_own_still_runs_the_producers(monkeypatch):
    calls = _no_producer_pass(monkeypatch)
    monkeypatch.setattr("src.briefing.service._read_cache", lambda: _payload())
    out = LQ.leads_quality_report(_sess())
    assert calls == [1]
    assert out["source"] == "producer-pass"


# --------------------------------------------------------------------------- #
# bulletin-weekly                                                             #
# --------------------------------------------------------------------------- #


def test_an_omitted_section_is_listed_with_its_reason_and_never_built(monkeypatch):
    from src.bulletin import sections as S

    built = []
    monkeypatch.setattr(S, "SECTIONS", (
        ("one", lambda s, p, c: built.append("one") or {"section": "one"}),
        ("cards", lambda s, p, c: built.append("cards") or {"section": "cards"}),
    ))
    out = S.build_sections(None, None, omit_sections={"cards": "left out on purpose"})
    assert built == ["one"]
    assert out[1] == {"section": "cards", "skipped": "left out on purpose", "omitted_by_caller": True}


def test_the_bundle_copy_of_the_bulletin_omits_cards_and_says_so(monkeypatch):
    from src.api.diagnostics import performance as P

    seen = {}

    def _layer_a(db, period, *, omit_sections=None):
        seen["omit"] = omit_sections
        return {"sections": []}

    monkeypatch.setattr("src.bulletin.facts.layer_a", _layer_a)
    monkeypatch.setattr("src.bulletin.gate.bulletin_available", lambda: {"available": True})
    out = P.bulletin_weekly_for_bundle(None)
    assert seen["omit"] == {"cards": P.BULLETIN_BUNDLE_CARDS_OMITTED}
    assert out["bundle_note"] == P.BULLETIN_BUNDLE_CARDS_OMITTED
    assert "/api/diagnostics/bulletin-preview" in out["bundle_note"]

    # The route itself still builds every section.
    seen.clear()
    P.bulletin_preview(cadence="weekly", download=False, db=None)
    assert not seen["omit"]


def test_a_gated_bulletin_carries_no_bundle_note(monkeypatch):
    from src.api.diagnostics import performance as P

    monkeypatch.setattr("src.bulletin.gate.bulletin_available", lambda: {"available": False})
    assert "bundle_note" not in P.bulletin_weekly_for_bundle(None)


# --------------------------------------------------------------------------- #
# the manifest                                                                #
# --------------------------------------------------------------------------- #


def test_the_manifest_entry_repeats_the_members_own_note():
    from src.api.diagnostics.bundle import _write_all_diagnostics_zip

    members = [
        ("noted.json", lambda: {"x": 1, "bundle_note": "carried less, and here is why"}),
        ("plain.json", lambda: {"x": 1}),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        results = _write_all_diagnostics_zip(members, z, profile="full")
    by = {r["file"]: r for r in results}
    assert by["noted.json"]["bundle_note"] == "carried less, and here is why"
    assert "bundle_note" not in by["plain.json"]
    man = json.loads(zipfile.ZipFile(io.BytesIO(buf.getvalue())).read("manifest.json"))
    assert {m["file"]: m.get("bundle_note") for m in man["members"]}["noted.json"] == "carried less, and here is why"


def test_the_bundle_wires_both_members_to_their_bundle_forms():
    import inspect

    from src.api.diagnostics import bundle

    src = inspect.getsource(bundle)
    assert '("leads-quality.json", lambda: leads_quality_for_bundle(db))' in src
    assert '("bulletin-weekly.json", lambda: bulletin_weekly_for_bundle(db))' in src
