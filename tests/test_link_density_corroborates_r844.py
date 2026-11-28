"""R844 (row 449): ``link_density_rate`` is a corroborating signal only and can never disqualify a source alone.

The field analysis (#2418) found the criterion alone disqualifying about 100 mainstream outlets per re-checking instance. It
keeps its evidence guard and its record; beside the furniture-repetition signature it still makes a source ``failing``; but
alone, or with soft signals only, it is ``watch``, which ``decide_verdict`` maps to qualified. The criteria version moves
(a label: nothing re-judges on it), so the sources it disqualified come back at their normal re-check cadence.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.analytics.source_audit import CRITERIA, derive_status, flag_criteria, should_auto_demote
from src.catalog.qualification import CRITERIA_VERSION, STATUS_DISQUALIFIED, STATUS_QUALIFIED, decide_verdict


def _f(name: str, ef: bool) -> dict:
    return {"criterion": name, "value": 0.9, "extraction_failure": ef}


def _metrics(sid: int, *, link: float, n: int = 200) -> dict:
    """The per_source_metrics shape (as in run_source_audit_selftest's fixture), clean on every other criterion."""
    return {"domain": f"s{sid}.example", "language": "en", "region": "gb", "article_count": n, "dominant_lang": "en",
            "outlier_rate": 0.1, "pathology_rate": 0.0, "pathology_articles": 0, "link_density_rate": link,
            "link_dense_articles": round(link * n), "language_mismatch_rate": 0.0, "short_article_rate": 0.1,
            "furniture_share": 0.1}


LINK = _f("link_density_rate", True)
PATH = _f("pathology_rate", True)
SHORT = _f("short_article_rate", False)
OUTLIER = _f("outlier_rate", False)


def test_link_density_alone_never_disqualifies():
    assert derive_status([LINK]) == "watch"
    assert decide_verdict([LINK]) == STATUS_QUALIFIED


def test_link_density_with_soft_signals_only_never_disqualifies():
    """'Alone' means without the primary signature: soft signals cannot lend it a disqualification either."""
    assert derive_status([LINK, SHORT, OUTLIER]) == "watch"
    assert decide_verdict([LINK, SHORT]) == STATUS_QUALIFIED


def test_link_density_still_corroborates_the_primary_signature():
    assert derive_status([PATH]) == "degraded"
    assert derive_status([PATH, LINK]) == "failing"
    assert decide_verdict([PATH, LINK]) == STATUS_DISQUALIFIED
    assert decide_verdict([PATH]) == STATUS_DISQUALIFIED, "pathology alone is unchanged"


def test_a_stored_list_from_before_r844_is_judged_by_todays_rule():
    """Read by criterion name, so a pre-R844 failing list that still says extraction_failure=True is not a signature."""
    stored = [{"criterion": "link_density_rate", "value": 0.4, "extraction_failure": True, "flagged_by": ["cohort_tail"]}]
    assert derive_status(stored) == "watch"


def test_auto_demote_never_fires_on_link_density_alone():
    from src.analytics.source_audit import SourceAudit

    audit = SourceAudit(1, "a.example", "en", "gb", 100, status=derive_status([LINK]), failing_criteria=[LINK])
    assert should_auto_demote(audit, enabled=True) == (False, None)


def test_the_criterion_keeps_its_evidence_and_record():
    link = next(c for c in CRITERIA if c["name"] == "link_density_rate")
    assert link["extraction_failure"] is True and link["corroborates_only"] is True
    assert [c["name"] for c in CRITERIA if c.get("corroborates_only")] == ["link_density_rate"]
    clean = {i: _metrics(i, link=0.0) for i in range(10)}
    clean[70] = _metrics(70, link=0.6)
    flags = flag_criteria(clean, cohort_floor=8, min_articles=20)
    assert any(f["criterion"] == "link_density_rate" for f in flags.get(70, [])), "still flagged on its own evidence"
    assert derive_status(flags.get(70, [])) == "watch"


def test_the_criteria_version_moved():
    assert CRITERIA_VERSION == "oo-source-qualification-4"
