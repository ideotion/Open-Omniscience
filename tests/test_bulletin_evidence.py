"""
The owner-only evidence archive.

Two properties carry this file. First, the archive holds the period's articles
EXACTLY — not a sample, not a top-N — because the whole point is that the
edition's counts can be recomputed from it, and a sampled archive silently turns
exact counts into unverifiable ones. Second, it is plaintext leaving an encrypted
store, so that fact appears in the plan, the README and the manifest rather than
being left for the operator to work out.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import zipfile
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin.evidence import DISCLOSURE, build_evidence_archive, evidence_plan
from src.bulletin.period import resolve_period
from src.database.models import Article, Base, Source

_P = resolve_period("weekly", end=date(2026, 8, 1))  # 2026-07-25 .. 2026-07-31


def _corpus(n: int = 5, *, quarantined: int = 0, outside: int = 0) -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="Alpha", domain="alpha.test", country="fr", source_type="news")
    s.add(src)
    s.flush()
    i = 0

    def _add(day: str, q: bool) -> None:
        nonlocal i
        i += 1
        s.add(
            Article(
                url=f"https://alpha.test/{i}",
                canonical_url=f"https://alpha.test/{i}",
                source_id=src.id,
                title=f"Article {i}",
                content=f"the body of article {i}, with an accent: café",
                hash=f"{i:064d}",
                language="fr",
                published_at=datetime.fromisoformat(f"{day} 12:00:00"),
                quarantined=q,
            )
        )
        s.flush()

    for _ in range(n):
        _add("2026-07-27", False)
    for _ in range(quarantined):
        _add("2026-07-27", True)
    for _ in range(outside):
        _add("2026-08-01", False)
    s.commit()
    return s


# -- the plan --------------------------------------------------------------- #


def test_the_plan_reports_the_exact_article_count():
    plan = evidence_plan(_corpus(7), _P)
    assert plan["articles"] == 7


def test_the_plan_labels_its_size_figure_an_estimate():
    """An estimate labelled as one is useful; an estimate presented as a size is a
    number that will be wrong."""
    plan = evidence_plan(_corpus(5), _P)
    assert plan["estimated_bytes"] and plan["estimated_bytes"] > 0
    assert "estimate" in plan["estimate_basis"] or "mean" in plan["estimate_basis"]


def test_an_empty_period_reports_unknown_size_never_a_confident_zero():
    plan = evidence_plan(_corpus(0), _P)
    assert plan["articles"] == 0
    assert plan["estimated_bytes"] is None
    assert "unknown, not zero" in plan["estimate_basis"]


def test_the_plan_discloses_the_plaintext_consequence_before_anything_is_written():
    plan = evidence_plan(_corpus(3), _P)
    assert "PLAINTEXT" in plan["disclosure"]
    assert "encrypted at rest; this archive is not" in plan["disclosure"]


def test_the_plan_reports_whether_the_destination_is_writable(tmp_path):
    plan = evidence_plan(_corpus(1), _P, dest=tmp_path)
    assert plan["destination_writable"] is True
    assert plan["free_bytes"] > 0
    missing = evidence_plan(_corpus(1), _P, dest=tmp_path / "nope")
    assert missing["destination_writable"] is False


# -- the archive ------------------------------------------------------------ #


def _build(tmp_path, s, edition=None):
    return build_evidence_archive(s, edition or {"layer": "A", "sections": []}, _P, tmp_path)


def test_the_archive_holds_the_periods_articles_exactly(tmp_path):
    """Not a sample, not a top-N — the counts in the edition must be recomputable
    from what is here."""
    s = _corpus(9)
    rep = _build(tmp_path, s)
    with zipfile.ZipFile(rep["path"]) as z:
        arts = [n for n in z.namelist() if n.startswith("articles/")]
    assert len(arts) == 9 == rep["articles"] == rep["articles_expected"]
    assert rep["complete"] is True


def test_quarantined_and_out_of_period_articles_are_excluded_exactly_as_the_edition_excludes_them(
    tmp_path,
):
    s = _corpus(4, quarantined=3, outside=2)
    rep = _build(tmp_path, s)
    assert rep["articles"] == 4


def test_an_article_carries_its_full_text_and_metadata(tmp_path):
    s = _corpus(1)
    rep = _build(tmp_path, s)
    with zipfile.ZipFile(rep["path"]) as z:
        name = next(n for n in z.namelist() if n.startswith("articles/"))
        art = json.loads(z.read(name).decode("utf-8"))
    assert "café" in art["content"], "the archive must carry the text, not a summary of it"
    assert art["source"] == "alpha.test"
    assert art["language"] == "fr" and art["hash"]


def test_only_sources_that_actually_contributed_are_listed(tmp_path):
    s = _corpus(2)
    s.add(Source(name="Never", domain="never.test"))
    s.commit()
    rep = _build(tmp_path, s)
    with zipfile.ZipFile(rep["path"]) as z:
        srcs = json.loads(z.read("sources.json").decode("utf-8"))
    assert [x["domain"] for x in srcs] == ["alpha.test"]


def test_the_readme_and_manifest_both_carry_the_plaintext_disclosure(tmp_path):
    rep = _build(tmp_path, _corpus(2))
    with zipfile.ZipFile(rep["path"]) as z:
        readme = z.read("README.md").decode("utf-8")
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    assert DISCLOSURE in readme
    assert manifest["disclosure"] == DISCLOSURE
    assert "not the published document" in readme


def test_the_readme_carries_a_table_of_contents_built_from_the_real_edition(tmp_path):
    edition = {
        "layer": "A",
        "sections": [
            {"section": "rising_concepts", "window": {"days": 7}},
            {"section": "through_time", "skipped": "the period spans 365 days"},
            {"section": "alerts", "error": "boom"},
        ],
    }
    rep = _build(tmp_path, _corpus(1), edition)
    with zipfile.ZipFile(rep["path"]) as z:
        readme = z.read("README.md").decode("utf-8")
    assert "## Contents" in readme
    assert "rising_concepts** — window 7 days" in readme
    assert "through_time** — skipped" in readme
    assert "alerts** — failed to build" in readme, "a failed section is named, not omitted"


def test_every_member_is_hashed_and_the_manifest_says_why_it_is_not_in_its_own_list(tmp_path):
    rep = _build(tmp_path, _corpus(3))
    with zipfile.ZipFile(rep["path"]) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        names = set(z.namelist())
    listed = {m["name"] for m in manifest["members"]}
    assert listed == names - {"manifest.json"}
    assert all(len(m["sha256"]) == 64 for m in manifest["members"])
    assert "cannot contain its own hash" in manifest["note"]


def test_the_recorded_hashes_match_the_bytes_actually_stored(tmp_path):
    import hashlib

    rep = _build(tmp_path, _corpus(2))
    with zipfile.ZipFile(rep["path"]) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        for m in manifest["members"]:
            assert hashlib.sha256(z.read(m["name"])).hexdigest() == m["sha256"], m["name"]


def test_the_edition_record_travels_with_the_evidence(tmp_path):
    rep = _build(tmp_path, _corpus(1), {"layer": "A", "sections": [], "marker": "kept"})
    with zipfile.ZipFile(rep["path"]) as z:
        assert json.loads(z.read("edition.json").decode("utf-8"))["marker"] == "kept"


# -- partial and cancelled builds ------------------------------------------- #


def test_a_cancelled_build_leaves_nothing_that_looks_like_an_archive(tmp_path):
    s = _corpus(600)  # more than one page, so the stop is checked mid-run
    rep = build_evidence_archive(s, {"layer": "A"}, _P, tmp_path, should_stop=lambda: True)
    assert rep["cancelled"] is True
    assert list(tmp_path.iterdir()) == [], "no partial, and no finished-looking file either"


def test_a_failed_build_removes_its_partial(tmp_path, monkeypatch):
    s = _corpus(2)
    monkeypatch.setattr(
        "src.bulletin.evidence._readme",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        _build(tmp_path, s)
    assert list(tmp_path.iterdir()) == []


def test_a_missing_destination_is_refused_before_any_work(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        build_evidence_archive(_corpus(1), {}, _P, tmp_path / "absent")


def test_progress_is_reported_against_the_real_total(tmp_path):
    seen = []
    build_evidence_archive(
        _corpus(3), {"layer": "A"}, _P, tmp_path, progress_cb=lambda d, t: seen.append((d, t))
    )
    assert seen and seen[-1] == (3, 3)


def test_the_filename_names_the_period_it_covers(tmp_path):
    rep = _build(tmp_path, _corpus(1))
    assert rep["filename"] == "20260731-OOS-weekly-evidence.zip"
