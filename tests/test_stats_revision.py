"""
Offline tests for the revision-anomaly detector (``src/stats/revision.py``).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure-data tests — they build :class:`StatFigure` vintage trails directly and assert the
reliable-memory honesty rules: the latest revision is flagged only when it is a robust
outlier vs the cell's OWN earlier revisions; a thin / uniform history degrades to silence;
input order does not matter (the detector orders by ``extracted_at``); a ``None`` vintage
breaks no chain; it is retrospective (it flags a revision that already happened) and carries
NO score. They import only the pure modules, so they run in the bare sandbox and in CI.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from src.stats.revision import find_revision_anomalies
from src.stats.sdmx import StatFigure

_SCORE_RE = re.compile(r"score|credibility|reliability|quality|trust", re.IGNORECASE)
_FORECAST_RE = re.compile(r"forecast|predict|future", re.IGNORECASE)


def _fig(
    *,
    value: float | None,
    extracted_at: str,
    agency: str = "eurostat",
    series_id: str = "NY.GDP.MKTP.CD",
    ref_area: str = "FR",
    time_period: str = "2019",
) -> StatFigure:
    return StatFigure(
        agency=agency,
        series_id=series_id,
        ref_area=ref_area,
        time_period=time_period,
        value=value,
        unit=None,
        methodology_ref=None,
        adjustment=None,
        base_year=None,
        extracted_at=extracted_at,
    )


def _trail(value_by_month: Sequence[tuple[int, float | None]], **kw) -> list[StatFigure]:
    return [
        _fig(value=v, extracted_at=f"2026-{m:02d}-01T00:00:00Z", **kw) for m, v in value_by_month
    ]


# A long history of tiny revisions, then one huge one — a clear outlier.
_OUTLIER = [(1, 100.0), (2, 100.1), (3, 99.9), (4, 100.2), (5, 100.0), (6, 110.0)]


def test_flags_an_outlier_revision_with_components() -> None:
    figs = _trail(_OUTLIER)
    figs.reverse()  # input order must not matter — the detector orders by extracted_at
    out = find_revision_anomalies(figs)
    assert out["count"] == 1
    a = out["anomalies"][0]
    assert a["series_id"] == "NY.GDP.MKTP.CD"
    assert a["ref_area"] == "FR"
    assert a["time_period"] == "2019"
    assert a["from_value"] == 100.0
    assert a["to_value"] == 110.0
    assert a["abs_change"] == 10.0
    assert a["rel_change"] == 0.1  # 10 / 100
    assert a["n_prior_revisions"] == 4
    assert a["revised_at"] == "2026-06-01T00:00:00Z"  # the revising vintage
    assert a["robust_z"] > 3.5  # well past the threshold


def test_thin_history_degrades_to_silence() -> None:
    # Only two prior revisions (< min_prior_revisions) — no basis to characterise a tail.
    out = find_revision_anomalies(_trail([(1, 100.0), (2, 101.0), (3, 100.0), (4, 110.0)]))
    assert out["count"] == 0


def test_normal_revision_within_spread_is_not_flagged() -> None:
    # A long history of tiny revisions, and the latest is also tiny.
    out = find_revision_anomalies(
        _trail([(1, 100.0), (2, 100.1), (3, 99.9), (4, 100.2), (5, 100.0), (6, 100.15)])
    )
    assert out["count"] == 0


def test_uniform_history_degrades_to_silence() -> None:
    # Every prior revision was exactly +1 (zero spread); even a big jump can't be scaled.
    out = find_revision_anomalies(
        _trail([(1, 10.0), (2, 11.0), (3, 12.0), (4, 13.0), (5, 14.0), (6, 20.0)])
    )
    assert out["count"] == 0  # deliberate conservatism: no robust scale → no claim


def test_none_vintage_breaks_no_chain() -> None:
    figs = _trail([(1, 100.0), (2, None), (3, 100.1), (4, 99.9), (5, 100.2), (6, 100.0), (7, 110.0)])
    out = find_revision_anomalies(figs)
    assert out["count"] == 1
    assert out["anomalies"][0]["abs_change"] == 10.0  # the gap was skipped, not a revision


def test_no_revision_is_not_an_anomaly() -> None:
    out = find_revision_anomalies(
        _trail([(1, 100.0), (2, 100.0), (3, 100.0), (4, 100.0), (5, 100.0)])
    )
    assert out["count"] == 0


def test_only_the_anomalous_cell_is_flagged() -> None:
    anomalous = _trail(_OUTLIER, series_id="A")
    calm = _trail(
        [(1, 50.0), (2, 50.1), (3, 49.9), (4, 50.2), (5, 50.0), (6, 50.1)], series_id="B"
    )
    out = find_revision_anomalies(anomalous + calm)
    assert out["count"] == 1
    assert out["anomalies"][0]["series_id"] == "A"


def test_is_retrospective_and_carries_no_score() -> None:
    out = find_revision_anomalies(_trail(_OUTLIER))
    assert out["count"] == 1
    a = out["anomalies"][0]
    # A revision that ALREADY happened (retrospective), never a predicted value.
    assert a["from_value"] != a["to_value"]
    assert "Retrospective only" in out["method"]

    def _walk(obj: object) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert not _SCORE_RE.search(k), f"forbidden score-like key: {k!r}"
                assert not _FORECAST_RE.search(k), f"forbidden forecast-like key: {k!r}"
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(out)
