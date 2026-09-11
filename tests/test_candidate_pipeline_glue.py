"""The triage glue and the catalogue splice of the candidate pipeline -- no network, no model.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

Pinned here: the batch files carry the canaries and only verified rows; a result file is
re-validated in code (echo-back, enums, vocabulary, canaries) and a batch that fails a canary
is never merged whatever its rows say; the splice appends rendered entries to the END of a
curated file and never touches the bytes above; and every refusal reason of the splice.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, default: Path):
    import sys

    p = Path(os.environ.get(name) or default)
    spec = importlib.util.spec_from_file_location(p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses need the module registered before exec
    spec.loader.exec_module(mod)
    return mod


tb = _load("TB_MODULE", _ROOT / "scripts" / "analysis" / "triage_batches.py")
msb = _load("MSB_MODULE", _ROOT / "scripts" / "merge_source_batch.py")


def _verified_jsonl(path: Path, n: int, *, verified: bool = True) -> None:
    lines = []
    for i in range(n):
        lines.append(json.dumps({
            "domain": f"s{i}.example", "name": f"Source {i}", "source_type": "news", "country": "fr",
            "language_export": "fr", "status": "verified" if verified else "rejected",
            "reason": "verified" if verified else "feed_stale", "homepage_url": f"https://s{i}.example/",
            "site_title": f"Source {i} — actualités", "description": "Le journal de la ville",
            "feed_url": f"https://s{i}.example/feed", "feed_kind": "link", "feed_probes": 1,
            "entries": 5, "dated_entries": 5, "newest_entry": "2026-09-08T10:00:00+00:00",
            "titles": ["Le conseil municipal adopte le budget"], "language_detected": "fr",
            "language_basis": "detected", "robots": "allowed", "tags": ["news", "via:wikidata-discovery"],
            "elapsed_s": 1.0, "checked_at": "2026-09-10T12:00:00",
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ prepare

def test_prepare_batches_only_verified_rows_and_mixes_in_every_canary(tmp_path):
    src = tmp_path / "verified.jsonl"
    _verified_jsonl(src, 5)
    with src.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"domain": "bad.example", "status": "rejected", "reason": "feed_stale"}) + "\n")
    m = tb.prepare(src, tmp_path / "triage", batch_size=3)
    assert m["rows"] == 5 and len(m["batches"]) == 2
    b1 = json.loads(Path(m["batches"][0]).read_text(encoding="utf-8"))
    domains = [r["domain"] for r in b1]
    assert {c["domain"] for c in tb.CANARIES} <= set(domains), "every canary rides in every batch"
    assert "bad.example" not in domains
    canaries = {c["domain"] for c in tb.CANARIES}
    assert domains[0] not in canaries and domains[-1] not in canaries  # never at the edges
    assert not any("expected" in r for r in b1)  # the answers never ride in the batch
    vocab = json.loads((tmp_path / "triage" / "vocabulary.json").read_text(encoding="utf-8"))
    assert "news" in vocab and "state-media" not in vocab and not any(v.startswith("via:") for v in vocab)


# ------------------------------------------------------------------ validate

def _batch_rows():
    return [{"domain": "a.example"}, {"domain": "theguardian.com"}, {"domain": "b.example"},
            {"domain": "ec.europa.eu"}, {"domain": "rijksmuseum.nl"}]


def _good_answers():
    return {"rows": [
        {"domain": "a.example", "journalism": True, "kind": "news", "language": "fr", "topics": ["politics", "made-up"], "confidence": "high"},
        {"domain": "theguardian.com", "journalism": True, "kind": "news", "language": "en", "topics": [], "confidence": "high"},
        {"domain": "b.example", "journalism": False, "kind": "institution", "language": "fr", "topics": [], "confidence": "medium", "primary_source": True},
        {"domain": "ec.europa.eu", "journalism": False, "kind": "institution", "language": "en", "topics": [], "confidence": "high", "primary_source": True},
        {"domain": "rijksmuseum.nl", "journalism": False, "kind": "institution", "language": "nl", "topics": [], "confidence": "high", "primary_source": False},
    ]}


def test_validate_accepts_a_clean_batch_and_leashes_the_vocabulary():
    answers, problems = tb.validate_result(_batch_rows(), _good_answers(), {"politics", "news"})
    assert problems == [] and set(answers) == {"a.example", "theguardian.com", "b.example",
                                              "ec.europa.eu", "rijksmuseum.nl"}
    assert answers["a.example"]["topics"] == ["politics"]  # the invented topic is dropped, the row kept


def test_validate_refuses_a_batch_that_fails_a_canary_or_forgets_a_row():
    bad = _good_answers()
    bad["rows"][3]["journalism"] = True  # the Commission read as journalism
    _, problems = tb.validate_result(_batch_rows(), bad, {"politics"})
    assert any(p.startswith("canary failed: ec.europa.eu") for p in problems)
    short = {"rows": _good_answers()["rows"][:3]}
    _, problems = tb.validate_result(_batch_rows(), short, {"politics"})
    assert any("unanswered" in p for p in problems)
    extra = _good_answers()
    extra["rows"].append({"domain": "ghost.example", "journalism": True, "kind": "news", "language": "en", "topics": [], "confidence": "high"})
    _, problems = tb.validate_result(_batch_rows(), extra, {"politics"})
    assert any("unknown domain" in p for p in problems)


def test_validate_refuses_an_out_of_enum_answer():
    bad = _good_answers()
    bad["rows"][0]["kind"] = "newspaper-ish"
    _, problems = tb.validate_result(_batch_rows(), bad, {"politics"})
    assert any("out-of-enum" in p for p in problems)


# ------------------------------------------------------------------ merge

def test_merge_keeps_only_verified_journalism_from_trusted_batches(tmp_path):
    src = tmp_path / "verified.jsonl"
    _verified_jsonl(src, 4)
    triage = tmp_path / "triage"
    m = tb.prepare(src, triage, batch_size=2)
    assert len(m["batches"]) == 2
    vocab = set(json.loads((triage / "vocabulary.json").read_text(encoding="utf-8")))
    topic = sorted(vocab)[0]

    def answer(batch_path: str, *, flip_canary: bool, confidence: str = "high"):
        rows = json.loads(Path(batch_path).read_text(encoding="utf-8"))
        out = []
        for r in rows:
            c = next((x for x in tb.CANARIES if x["domain"] == r["domain"]), None)
            if c:
                exp = dict(c["expected"])
                if flip_canary:
                    exp["journalism"] = not exp["journalism"]
                ans = {"domain": r["domain"], "journalism": exp["journalism"], "kind": exp["kind"],
                       "language": exp["language"], "topics": [], "confidence": "high"}
                if "primary_source" in exp:
                    ans["primary_source"] = exp["primary_source"]
                out.append(ans)
            else:
                inst = r["domain"] == "s1.example"
                row = {"domain": r["domain"], "journalism": not inst,
                       "kind": "institution" if inst else "news",
                       "language": "fr", "topics": [topic], "confidence": confidence}
                if inst:
                    row["primary_source"] = False   # a museum-shaped institution: refused
                out.append(row)
        Path(batch_path.replace(".json", ".result.json")).write_text(json.dumps({"rows": out}), encoding="utf-8")

    answer(m["batches"][0], flip_canary=False)      # s0 (news), s1 (institution)
    answer(m["batches"][1], flip_canary=True)       # s2, s3 -- a canary failed: never merged
    summary = tb.merge(src, triage, tmp_path / "out.yml", today="2026-09-10")
    doc = yaml.safe_load((tmp_path / "out.yml").read_text(encoding="utf-8"))
    assert [e["domain"] for e in doc["sources"]] == ["s0.example"]
    e = doc["sources"][0]
    assert e["verified"] is True and e["last_verified"] == "2026-09-10" and topic in e["tags"]
    assert not any(t.startswith("via:") for t in e["tags"])
    assert summary["by_reason"]["institution_not_primary_source"] == 1
    assert summary["by_reason"]["batch_untrusted"] == 2
    assert len(summary["untrusted_batches"]) == 1


def test_merge_routes_each_admitted_class_to_its_own_catalogue(tmp_path):
    """THE 2026-09-11 RULING, which refused a blanket verdict on the institution bucket.

    ``academic`` and the primary-source half of ``institution`` "belong in their OWN catalogue
    beside legal and markets, so the briefing and trend surfaces can lens them separately and a
    corpus statistic keeps meaning what it says". The half that is NOT a primary source -- the
    maintainer's own example was a museum's events page beside the UN Association of Sweden --
    stays out, and so do broadcaster, religious, personal-blog and aggregator, on the merits.

    All four cases in one batch, because the thing that would break is the ROUTING, and routing
    is only testable when more than one destination is in play at once.
    """
    src = tmp_path / "verified.jsonl"
    _verified_jsonl(src, 4)
    triage = tmp_path / "triage"
    m = tb.prepare(src, triage, batch_size=4)
    assert len(m["batches"]) == 1

    kinds = {                       # s0 journalism · s1 academic · s2 primary · s3 refused
        "s0.example": {"journalism": True, "kind": "news"},
        "s1.example": {"journalism": False, "kind": "academic"},
        "s2.example": {"journalism": False, "kind": "institution", "primary_source": True},
        "s3.example": {"journalism": False, "kind": "institution", "primary_source": False},
    }
    rows = json.loads(Path(m["batches"][0]).read_text(encoding="utf-8"))
    out = []
    for r in rows:
        c = next((x for x in tb.CANARIES if x["domain"] == r["domain"]), None)
        if c:
            a = dict(c["expected"])
            out.append({"domain": r["domain"], "topics": [], "confidence": "high", **a})
        else:
            out.append({"domain": r["domain"], "language": "fr", "topics": [],
                        "confidence": "high", **kinds[r["domain"]]})
    Path(m["batches"][0].replace(".json", ".result.json")).write_text(
        json.dumps({"rows": out}), encoding="utf-8")

    summary = tb.merge(src, triage, tmp_path / "out.yml", today="2026-09-11")
    assert summary["untrusted_batches"] == [], summary["untrusted_batches"]

    def domains(path):
        return [e["domain"] for e in (yaml.safe_load(Path(path).read_text(encoding="utf-8"))["sources"] or [])]

    assert domains(tmp_path / "out.yml") == ["s0.example"]
    assert domains(tmp_path / "out_academic.yml") == ["s1.example"]
    assert domains(tmp_path / "out_official.yml") == ["s2.example"]
    assert summary["by_target"] == {"journalism": 1, "academic": 1, "official": 1}
    assert summary["by_reason"]["institution_not_primary_source"] == 1, (
        "an institution refused for not being a primary source must be counted as THAT, not "
        "lumped with a broadcaster refused on the merits -- the counts are how the next "
        "admission decision gets made"
    )
    # The source_type keeps the class, so every surface can lens them apart from reporting.
    acad = yaml.safe_load((tmp_path / "out_academic.yml").read_text(encoding="utf-8"))["sources"][0]
    offi = yaml.safe_load((tmp_path / "out_official.yml").read_text(encoding="utf-8"))["sources"][0]
    assert acad["source_type"] == "scientific-journal" and offi["source_type"] == "institution"


def test_a_target_with_no_rows_is_written_empty_rather_than_skipped(tmp_path):
    """An ABSENT file reads as "the stage did not run"; an empty one says "it ran and found
    none". Those are different facts and the operator acts differently on them."""
    src = tmp_path / "verified.jsonl"
    _verified_jsonl(src, 2)
    triage = tmp_path / "triage"
    m = tb.prepare(src, triage, batch_size=2)
    rows = json.loads(Path(m["batches"][0]).read_text(encoding="utf-8"))
    out = []
    for r in rows:
        c = next((x for x in tb.CANARIES if x["domain"] == r["domain"]), None)
        a = dict(c["expected"]) if c else {"journalism": True, "kind": "news", "language": "fr"}
        out.append({"domain": r["domain"], "topics": [], "confidence": "high", **a})
    Path(m["batches"][0].replace(".json", ".result.json")).write_text(
        json.dumps({"rows": out}), encoding="utf-8")
    tb.merge(src, triage, tmp_path / "out.yml", today="2026-09-11")
    for name in ("out.yml", "out_academic.yml", "out_official.yml"):
        assert (tmp_path / name).exists(), f"{name} was skipped instead of written empty"
    doc = yaml.safe_load((tmp_path / "out_official.yml").read_text(encoding="utf-8"))
    assert doc["sources"] == [] or doc["sources"] is None


# ------------------------------------------------------------------ splice

def _entry(domain="new.example", **kw):
    e = {"name": "New", "domain": domain, "rss_url": f"https://{domain}/feed", "rate_limit_ms": 2000,
         "enabled": True, "verified": True, "last_verified": "2026-09-10", "language": "fr",
         "country": "fr", "region": "europe", "source_type": "news", "tags": ["news"], "priority": 3}
    e.update(kw)
    return e


def test_splice_appends_at_the_end_and_never_touches_the_bytes_above(tmp_path):
    target = tmp_path / "sources.yml"
    original = b"project_name: X\nsources:\n- name: Old\n  domain: old.example\n  tags:\n  - news\n"
    target.write_bytes(original)
    accepted, refused = msb.plan([_entry()], existing={"old.example"})
    assert refused == [] and len(accepted) == 1
    assert msb.splice(target, accepted) == 1
    data = target.read_bytes()
    assert data.startswith(original)
    parsed = yaml.safe_load(data.decode("utf-8"))
    assert [s["domain"] for s in parsed["sources"]] == ["old.example", "new.example"]
    assert parsed["sources"][1]["verified"] is True


def test_the_splice_refuses_what_it_cannot_vouch_for():
    existing = {"old.example", "bbc.com", "bbc.co.uk"}
    cases = [
        (_entry(verified=False), "verified is not true"),
        ({k: v for k, v in _entry().items() if k != "rss_url"}, "missing rss_url"),
        (_entry(domain="www.bbc.co.uk"), "domain is not a bare registrable domain"),
        (_entry(domain="bbc.co.uk"), "already in a shipped catalogue"),
        (_entry(tags=["news", "via:curated"]), "row-provenance tag via:curated"),
        (_entry(tags=["news", "fr"]), "language code in tags: fr"),
        (_entry(tags=["news", "france"]), "country name in tags: france"),
        (_entry(name="3CatInfo (tv)"), "name states country tv, entry says fr"),
        ({k: v for k, v in _entry(name="Island Radio (tv)").items() if k != "country"},
         "name states country tv, entry says none"),
    ]
    for e, why in cases:
        assert msb.check_entry(e, existing=existing, seen=set()) == why, why
    # The convention SATISFIED is not a refusal, and neither is a parenthetical that names no
    # country -- otherwise the guard would be refusing the catalogue's own naming style.
    assert msb.check_entry(_entry(name="Le Monde (France)"), existing=existing, seen=set()) is None
    assert msb.check_entry(_entry(name="Kyodo News (English)"), existing=existing, seen=set()) is None

    accepted, refused = msb.plan([_entry(), _entry()], existing=existing)
    assert len(accepted) == 1 and refused == [("new.example", "duplicate within the batch")]


def test_a_second_apply_of_the_same_batch_appends_nothing(tmp_path):
    target = tmp_path / "sources.yml"
    target.write_bytes(b"sources:\n- name: Old\n  domain: old.example\n")
    accepted, _ = msb.plan([_entry()], existing={"old.example"})
    msb.splice(target, accepted)
    existing_after = {"old.example", "new.example"}
    accepted2, refused2 = msb.plan([_entry()], existing=existing_after)
    assert accepted2 == [] and refused2 == [("new.example", "already in a shipped catalogue")]


def test_a_torn_last_line_from_a_mid_run_snapshot_is_skipped_not_fatal(tmp_path):
    src = tmp_path / "verified.jsonl"
    _verified_jsonl(src, 2)
    with src.open("a", encoding="utf-8") as fh:
        fh.write('{"domain": "half.example", "status": "verif')  # the row Stage A was writing
    m = tb.prepare(src, tmp_path / "triage", batch_size=40)
    assert m["rows"] == 2
