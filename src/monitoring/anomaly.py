"""
Corpus-volume anomaly detection (real z-scores).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Flags days whose article volume deviates from the corpus mean by more than a
z-score threshold. Honest statistics: the z-score is computed from the actual
mean and (population) standard deviation; with too few days or zero variance it
reports nothing rather than inventing an alert.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date


@dataclass
class VolumeAnomaly:
    day: date
    count: int
    z_score: float

    def to_dict(self) -> dict:
        return {"day": self.day.isoformat(), "count": self.count, "z_score": round(self.z_score, 3)}


def volume_anomalies(
    daily_counts: dict[date, int],
    *,
    z_threshold: float = 2.0,
    min_days: int = 5,
) -> list[VolumeAnomaly]:
    """Return days whose article count is >= ``z_threshold`` standard deviations
    from the mean. Empty if there are fewer than ``min_days`` days or no variance.
    """
    if len(daily_counts) < min_days:
        return []
    counts = list(daily_counts.values())
    mean = statistics.fmean(counts)
    stdev = statistics.pstdev(counts)
    if stdev == 0:
        return []
    anomalies = [
        VolumeAnomaly(day, count, (count - mean) / stdev)
        for day, count in daily_counts.items()
        if abs((count - mean) / stdev) >= z_threshold
    ]
    return sorted(anomalies, key=lambda a: a.day)
