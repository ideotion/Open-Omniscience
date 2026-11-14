"""The card quality loop (maintainer-asked 2026-11-14, Lane X).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the four parts: the pure checks (``src/briefing/card_quality.py``), the recurring self-check after
each Home refresh, the cards file the Field data button saves, and the offline report script. Each
check is tested both ways (it fires on the defect and stays quiet on a sound card), because a check
that never fires and a check that always fires read the same in a report nobody reads closely.
"""

from __future__ import annotations

import ast
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.briefing import card_quality as cq

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def _card(**over):
    base = {
        "id": "c1", "type": "rising", "title": "“tariff” is rising",
        "summary": "Mentions of “tariff” are running ~2.0× the prior-period rate (40 recent vs 20 before).",
        "bucket": "rising", "method": "count over 7 days", "caveat": "your sources, not the world",
        "signal": {"metric": "growth_ratio", "value": 2.0, "recent": 40, "prior": 20},
        "evidence": [{"title": "a", "url": "https://x.example/a"}], "article_ids": [], "n": 40,
        "key": "tariff", "created_at": "2026-11-14T10:00:00+00:00", "produced_by": "rising_now",
    }
    base.update(over)
    return base


def _checks(card):
    return sorted({f["check"] for f in cq.check_card(card)})


# --------------------------------------------------------------------------- #
#  Per-card checks
# --------------------------------------------------------------------------- #
def test_a_sound_card_raises_nothing():
    assert _checks(_card()) == []


def test_rising_words_over_falling_figures_is_a_direction_mismatch():
    c = _card(signal={"metric": "growth_ratio", "value": 0.5, "recent": 10, "prior": 20})
    f = [x for x in cq.check_card(c) if x["check"] == "direction_mismatch"]
    assert len(f) == 1 and f[0]["evidence"]["claimed"] == "rising" and f[0]["evidence"]["measured"] == "falling"
    # the ratio alone decides when there is no now/before pair
    c2 = _card(signal={"metric": "growth_ratio", "value": 0.8})
    assert "direction_mismatch" in _checks(c2)
    # falling words over rising figures, the other way round
    c3 = _card(title="Coverage of “x” is falling", summary="Fewer articles.", signal={"recent": 30, "prior": 10})
    assert "direction_mismatch" in _checks(c3)


def test_a_card_with_no_figures_to_compare_is_not_checkable_rather_than_passed():
    assert cq.direction_check(_card(signal={"metric": "voices", "value": 1})) is None
    assert cq.direction_check(_card(title="Five sources in lockstep", summary="Same words.")) is None
    rep = cq.quality_report([_card(signal={"metric": "voices", "value": 1})], now=NOW)
    assert rep["direction"] == {**rep["direction"], "checked": 0, "not_checkable": 1}


@pytest.mark.parametrize("over,check", [
    ({"caveat": ""}, "caveat_missing"),
    ({"method": "  "}, "method_missing"),
    ({"created_at": ""}, "date_missing"),
    ({"title": ""}, "empty_text"),
    ({"summary": "About {term} today."}, "unfilled_template"),
    ({"n": None, "article_ids": []}, "n_missing"),
    ({"n": 5, "article_ids": [1, 2, 3]}, "n_mismatch"),
    ({"evidence": [], "article_ids": []}, "no_evidence_link"),
    ({"signal": {"metric": "articles", "value": float("nan")}}, "non_finite_figure"),
    ({"signal": {"metric": "x", "value": 1, "n_sources": -2}}, "negative_count"),
    ({"n": 0}, "trivial_signal"),
    ({"title": "t" * 121}, "too_long"),
    ({"summary": "s" * 401}, "too_long"),
])
def test_each_honesty_and_usefulness_check_fires_on_its_defect(over, check):
    assert check in _checks(_card(**over))


def test_feed_duplicates_near_duplicates_and_same_article_sets():
    a = _card(id="a", article_ids=[1, 2, 3, 4], n=4)
    b = _card(id="b", article_ids=[1, 2, 3, 4], n=4)  # same title as a
    c = _card(id="c", type="echo", title="Echo on “tariff” today", summary="Four outlets ran the same words.",
              article_ids=[1, 2, 3, 4], n=4)
    d = _card(id="d", type="echo", title="Echo on “tariff” today!", summary="Four outlets ran the same words.",
              article_ids=[9], n=1)
    found = cq.check_feed([a, b, c, d])
    checks = Counter_of(found)
    assert checks["duplicate_title"] == 2
    assert checks["near_identical"] == 1  # c~d, same kind; a/b are already a duplicate title
    assert checks["same_articles"] >= 2  # a~c and b~c (a~b is the duplicate title)
    assert cq.check_feed([_card(id="x"), _card(id="y", title="Another thing", summary="Different words here.")]) == []


def Counter_of(findings):
    from collections import Counter

    return Counter(f["check"] for f in findings)


def test_feed_record_checks_stopped_slow_error_old_incomplete_and_coverage():
    meta = {
        "generated_at": (NOW - timedelta(days=8)).isoformat(),
        "incomplete_reason": "memory_short",
        "stopped_producers": ["slowpoke"],
        "producer_timings": [
            {"name": "rising_now", "seconds": 1.0, "outcome": "ok"},
            {"name": "slowpoke", "seconds": 700.0, "outcome": "stopped"},
            {"name": "laggard", "seconds": 61.0, "outcome": "no-signal"},
            {"name": "broken", "seconds": 0.1, "outcome": "error", "error_type": "KeyError"},
        ],
    }
    found = cq.check_meta(meta, registered=["rising_now", "slowpoke", "laggard", "broken"], cards=[_card()], now=NOW)
    checks = Counter_of(found)
    assert checks == {"feed_incomplete": 1, "feed_old": 1, "producer_stopped": 1, "producer_slow": 1,
                      "producer_error": 1, "kind_never_seen": 3}
    # a stopped producer is not reported slow as well
    assert [f["producer"] for f in found if f["check"] == "producer_slow"] == ["laggard"]
    # cards from before produced_by was cached cannot say who made them: no coverage claim then
    assert cq.check_meta({}, registered=["a"], cards=[_card(produced_by="")], now=NOW) == []


def test_checks_are_listed_as_run_only_when_their_input_was_there():
    rep = cq.quality_report([_card()], now=NOW)
    assert "arithmetic_failed" in rep["checks_not_run"]
    assert "evidence_missing_articles" in rep["checks_not_run"]
    per = {"c1": {"arithmetic": {"failed_n": 1, "rows": [{"reproduced": False, "label": "r"}]},
                  "evidence": {"total": 4, "missing_n": 1, "quarantined_n": 2}}}
    rep2 = cq.quality_report([_card()], per_card=per, now=NOW)
    assert not rep2["checks_not_run"]
    assert {f["check"] for f in rep2["findings"]} == {"arithmetic_failed", "evidence_missing_articles", "evidence_quarantined"}
    # the in-app run never claims the evidence checks
    rep3 = cq.quality_report([_card()], per_card=per, cheap_only=True, now=NOW)
    assert "evidence_missing_articles" in rep3["checks_not_run"] and "arithmetic_failed" in rep3["checks_run"]


def test_ranking_is_severity_then_hit_count_and_carries_no_score():
    cards = [_card(id=str(i), title=f"t{i}", caveat="") for i in range(3)] + [_card(id="z", title="z", n=0)]
    rep = cq.quality_report(cards, now=NOW)
    sev = [f["severity"] for f in rep["findings"]]
    assert sev == sorted(sev, key=lambda s: cq._SEVERITY_ORDER[s])
    text = json.dumps(rep).lower()
    for banned in ("score", "grade", "rating"):
        assert f'"{banned}' not in text


def test_compare_reports_new_resolved_and_verdicts():
    old = cq.quality_report([_card(id="a", caveat=""), _card(id="b", title="b", n=0)], now=NOW)
    new = cq.quality_report([_card(id="a"), _card(id="b", title="b", n=0, method="")], now=NOW)
    cmp_ = cq.compare_reports(old, new)
    verdicts = {p["check"]: p["verdict"] for p in cmp_["per_check"]}
    assert verdicts["caveat_missing"] == "improved" and verdicts["method_missing"] == "regressed"
    assert verdicts["trivial_signal"] == "unchanged"
    assert [f["check"] for f in cmp_["resolved_findings"]] == ["caveat_missing"]
    assert [f["check"] for f in cmp_["new_findings"]] == ["method_missing"]
    partial = {**new, "counts": [c for c in new["counts"] if c["check"] != "trivial_signal"]}
    assert {p["check"]: p["verdict"] for p in cq.compare_reports(old, partial)["per_check"]}["trivial_signal"] == "not-comparable"


def test_the_module_imports_nothing_from_src_so_the_script_runs_without_the_app():
    tree = ast.parse((ROOT / "src" / "briefing" / "card_quality.py").read_text("utf-8"))
    mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in mods if m and m.split(".")[0] == "src"], mods


# --------------------------------------------------------------------------- #
#  The recurring self-check
# --------------------------------------------------------------------------- #
def test_self_check_record_holds_ids_and_counts_never_card_text():
    payload = {"generated_at": NOW.isoformat(), "cards": [_card(caveat=""), _card(id="c2", title="Secret term", n=0)]}
    rec = cq.self_check(payload, registered=["rising_now"], now=NOW)
    assert rec["schema"] == cq.SELF_CHECK_SCHEMA and rec["cards"] == 2 and rec["high_n"] >= 1
    blob = json.dumps(rec)
    assert "Secret term" not in blob and "tariff" not in blob


def test_history_keeps_only_the_newest_records():
    lines: list[str] = []
    for i in range(cq.SELF_CHECK_KEEP + 25):
        lines = cq.append_history(lines, {"i": i})
    assert len(lines) == cq.SELF_CHECK_KEEP
    assert json.loads(lines[0])["i"] == 25 and json.loads(lines[-1])["i"] == cq.SELF_CHECK_KEEP + 24


def test_a_home_refresh_records_one_self_check_line_and_a_failure_is_not_fatal(monkeypatch, tmp_path):
    from src.briefing import service

    monkeypatch.setattr(service, "_cache_path", lambda: tmp_path / "briefing_cache.json")
    payload = {"generated_at": NOW.isoformat(), "cards": [_card(caveat="")]}
    service.record_card_self_check(payload)
    service.record_card_self_check(payload)
    lines = (tmp_path / "card_quality_selfcheck.jsonl").read_text("utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[-1])["counts"][0]["check"] == "caveat_missing"

    def _boom(*_a, **_k):
        raise RuntimeError("no")

    monkeypatch.setattr(cq, "self_check", _boom)
    service.record_card_self_check(payload)  # logged, never raised
    assert len((tmp_path / "card_quality_selfcheck.jsonl").read_text("utf-8").splitlines()) == 2


def test_the_refresh_calls_the_self_check_after_writing_the_cache_and_keeps_timings():
    src = (ROOT / "src" / "briefing" / "service.py").read_text("utf-8")
    body = src[src.index("def _refresh_briefing("):src.index("def _self_check_path(")]
    assert body.index("_write_cache(payload)") < body.index("record_card_self_check(payload)")
    assert '"producer_timings": timings' in body and "timings=timings" in body


def test_run_all_bounded_reports_each_producers_time_and_outcome(monkeypatch, tmp_path):
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from src.briefing import registry

    def _empty(_s):
        return []

    def _bad(_s):
        raise KeyError("x")

    def _one(_s):
        from src.briefing.card import Card

        return [Card(type="t", title="T", summary="S", bucket="context", method="m", caveat="c", key="k")]

    monkeypatch.setattr(registry, "_REGISTRY", [("empty", _empty), ("bad", _bad), ("one", _one)])
    s = sessionmaker(bind=sa.create_engine(f"sqlite:///{tmp_path / 's.db'}"))()
    try:
        timings: list[dict] = []
        _cards, stats = registry.run_all_bounded(s, timings=timings)
        _cards2, stats2 = registry.run_all_bounded(s)
    finally:
        s.close()
    assert [(t["name"], t["outcome"], t["cards"], t["error_type"]) for t in timings] == [
        ("empty", "no-signal", 0, None), ("bad", "error", 0, "KeyError"), ("one", "ok", 1, None)]
    assert all(t["seconds"] >= 0 for t in timings)
    assert "producer_timings" not in stats and stats.keys() == stats2.keys(), "stats keeps its shape"


# --------------------------------------------------------------------------- #
#  The cards file the Field data button saves
# --------------------------------------------------------------------------- #
@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Article, Base, Source

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Source(id=1, name="Wire", domain="wire.example"))
        s.add(Source(id=2, name="Letters", domain="letters.example"))
        s.flush()
        for i in range(1, 5):
            s.add(Article(id=i, url=f"https://user:pw@wire.example/a{i}?utm=1&token=SECRET#frag",
                          canonical_url=f"https://wire.example/a{i}", source_id=1, title=f"Tariff story {i}",
                          content="tariff " * 200, hash=f"{i:064d}", language="en"))
        s.add(Article(id=9, url="https://letters.example/n", canonical_url="https://letters.example/n", source_id=2,
                      title="A newsletter", content="private body", hash=f"{9:064d}", language="en",
                      newsletter_attached_via="sender"))
        s.commit()
        yield s


def _field_cards_module():
    import importlib

    # the package re-exports the route FUNCTION under the module's own name, so import the module by path
    return importlib.import_module("src.api.diagnostics.field_cards")


def _feed(tmp_path, monkeypatch, cards):
    from src.briefing import service

    monkeypatch.setattr(service, "_cache_path", lambda: tmp_path / "briefing_cache.json")
    monkeypatch.setattr(service, "_dismissed_path", lambda: tmp_path / "briefing_dismissed.json")
    payload = {"version": service.CACHE_VERSION, "generated_at": NOW.isoformat(), "article_count": 5,
               "cards": cards, "producer_timings": [{"name": "rising_now", "seconds": 2.0, "outcome": "ok"}]}
    (tmp_path / "briefing_cache.json").write_text(json.dumps(payload), "utf-8")
    (tmp_path / "briefing_dismissed.json").write_text(json.dumps({"ids": ["c2"]}), "utf-8")
    (tmp_path / "card_quality_selfcheck.jsonl").write_text(json.dumps({"at": "x", "high_n": 0}) + "\n", "utf-8")


def test_the_cards_file_carries_every_card_its_evidence_and_a_manifest(db, tmp_path, monkeypatch):
    from src.api.diagnostics.field_cards import build_field_cards_files

    monkeypatch.delenv("OO_QUALITY_INCLUDE_NEWSLETTER_TEXT", raising=False)
    cards = [_card(id="c1", article_ids=[1, 2, 3, 4, 77], n=5),
             _card(id="c2", title="Letters", summary="One letter.", article_ids=[9], n=1)]
    _feed(tmp_path, monkeypatch, cards)
    files = build_field_cards_files(db, now=NOW)
    assert set(files) == {"manifest.json", "feed.json", "cards.json", "quality.json", "selfcheck.jsonl"}
    feed = json.loads(files["feed.json"])
    assert [c["id"] for c in feed["cards"]] == ["c1", "c2"] and feed["dismissed_count"] == 1
    assert [c.get("dismissed") for c in feed["cards"]] == [False, True]
    assert feed["feed"]["producer_timings"][0]["name"] == "rising_now"
    rows = {r["card_id"]: r for r in json.loads(files["cards.json"])["cards"]}
    ev = rows["c1"]["evidence"]
    assert ev["total"] == 5 and ev["missing_n"] == 1 and ev["shown"] == 4
    item = ev["articles"]["items"][0]
    assert item["url"] == "https://wire.example/a1", "no user, password, query or fragment"
    assert item["content"]["text"].startswith("tariff") and item["content"]["excerpt_chars"] <= 600
    letter = rows["c2"]["evidence"]["articles"]["items"][0]
    assert "text" not in letter["content"] and "R655" in letter["content"]["withheld"]
    blob = "".join(files.values())
    assert "SECRET" not in blob and "user:pw" not in blob and "private body" not in blob
    quality = json.loads(files["quality.json"])
    assert "evidence_missing_articles" in {f["check"] for f in quality["findings"]}
    man = json.loads(files["manifest.json"])
    pc = man["personal_content"]
    assert pc["article_excerpts"] == 4 and pc["newsletter_bodies"].startswith("withheld") and pc["dismissed_cards"] == 1
    assert files["selfcheck.jsonl"].strip()


def test_the_cards_file_scrubs_a_held_passphrase(db, tmp_path, monkeypatch):
    from src.monitoring import secret_scrub

    field_cards = _field_cards_module()

    _feed(tmp_path, monkeypatch, [_card(summary="the word hunter2passphrase appears")])
    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: ("hunter2passphrase",))
    files = field_cards.build_field_cards_files(db, now=NOW)
    assert "hunter2passphrase" not in "".join(files.values())


def test_the_route_is_a_post_and_answers_a_zip(db, tmp_path, monkeypatch):
    field_cards = _field_cards_module()

    _feed(tmp_path, monkeypatch, [_card()])
    paths = {(r.path, tuple(sorted(r.methods))) for r in field_cards.router.routes if r.path.endswith("/field-cards")}
    assert paths == {("/api/diagnostics/field-cards", ("POST",))}
    resp = field_cards.field_cards(db=db)
    assert resp.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.body)) as z:
        assert "manifest.json" in z.namelist()


# --------------------------------------------------------------------------- #
#  The offline report script
# --------------------------------------------------------------------------- #
def _zip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return path


def test_the_script_reports_a_field_file_and_compares_two_rounds(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("cqr", ROOT / "scripts" / "card_quality_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def files(cards):
        return {
            "feed.json": json.dumps({"feed": {"generated_at": NOW.isoformat()}, "cards": cards,
                                     "registered_producers": ["rising_now", "quiet"]}),
            "cards.json": json.dumps({"cards": [{"card_id": c["id"], "arithmetic": {"failed_n": 0}} for c in cards]}),
            "selfcheck.jsonl": json.dumps({"at": "a", "high_n": 2}) + "\n",
        }

    first = _zip(tmp_path / "r1.zip", files([_card(id="a", caveat=""), _card(id="b", title="b", n=0)]))
    second = _zip(tmp_path / "r2.zip", files([_card(id="a"), _card(id="b", title="b", n=0)]))
    out = tmp_path / "out"
    assert mod.main([str(first), "--out", str(out)]) == 0
    assert mod.main([str(second), "--previous", str(first), "--out", str(out)]) == 0
    reports = sorted(out.glob("card-quality-*.json"))
    assert reports
    last = json.loads(reports[-1].read_text("utf-8"))
    assert last["compare"]["verdict_counts"].get("improved") == 1
    md = sorted(out.glob("card-quality-*.md"))[-1].read_text("utf-8")
    assert "## Findings, ranked" in md and "`kind_never_seen`" in md and "Compared with the previous round" in md
    # the previous round may also be handed in as its own JSON report
    assert mod.main([str(second), "--previous", str(reports[0]), "--out", str(out)]) == 0


def test_template_words_do_not_make_two_cards_near_identical():
    def framed(cid, term, n):
        t = "Coverage of “{term}” propagated across {n} sources over {days} days, first carried by {source}."
        v = {"term": term, "n": n, "days": 2, "source": "ES Regional Herald es"}
        return _card(id=cid, type="story_propagation", title=f"“{term}” spread across {n} sources",
                     summary=t.format(**v), i18n={"summary": [{"t": t, "v": v}]},
                     title_i18n="“{term}” spread across {n} sources", title_vars={"term": term, "n": n})

    assert not Counter_of(cq.check_feed([framed("a", "regional", 5), framed("b", "local", 3)]))["near_identical"]
    assert Counter_of(cq.check_feed([framed("a", "regional", 5), framed("b", "regional", 5)]))["duplicate_title"] == 2


def test_the_producer_map_fills_produced_by_without_touching_the_cache():
    cards = [_card(id="a", produced_by=""), _card(id="b", produced_by="")]
    payload = {"cards": cards, "card_producers": {"a": "rising_now"}}
    out = cq.with_producers(payload)
    assert [c["produced_by"] for c in out] == ["rising_now", ""]
    assert cards[0]["produced_by"] == "", "copies, never the cache's own dicts"
