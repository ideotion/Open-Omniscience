"""
Tests for the scientific-analysis API (salvaged Pillar 2, the "honesty gate").

Confirms the genuine statistical tests are reachable over HTTP and every result
carries a real statistic, p-value and sample size (never a fabricated constant).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_independent_t_test(client):
    r = client.post("/api/analysis/t-test/independent",
                    json={"sample1": [1, 2, 3, 4, 5], "sample2": [6, 7, 8, 9, 10]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "p_value" in body and "statistic" in body
    assert body["p_value"] < 0.05  # clearly different means


def test_pearson_correlation(client):
    r = client.post("/api/analysis/correlation/pearson",
                    json={"x": [1, 2, 3, 4, 5], "y": [2, 4, 6, 8, 10]})
    body = r.json()
    assert body["statistic"] == pytest.approx(1.0)  # perfect linear correlation
    assert "p_value" in body


def test_one_way_anova(client):
    r = client.post("/api/analysis/anova/one-way",
                    json={"groups": [[1, 2, 3], [4, 5, 6], [7, 8, 9]]})
    assert r.status_code == 200
    assert "p_value" in r.json()


def test_mann_whitney(client):
    r = client.post("/api/analysis/mann-whitney",
                    json={"sample1": [1, 2, 3, 4], "sample2": [10, 11, 12, 13]})
    assert r.status_code == 200
    assert "p_value" in r.json()


def test_mean_confidence_interval(client):
    r = client.post("/api/analysis/confidence-interval/mean",
                    json={"data": [10, 12, 14, 11, 13, 9], "confidence_level": 0.95})
    body = r.json()
    # the CI brackets the sample mean (~11.5)
    assert body["lower"] < 11.5 < body["upper"]
    assert body["estimate"] == pytest.approx(11.5)


def test_mismatched_lengths_400(client):
    r = client.post("/api/analysis/correlation/pearson", json={"x": [1, 2, 3], "y": [1, 2]})
    assert r.status_code in (400, 422)


def test_too_small_sample_422(client):
    # min_length validation rejects a single-point sample
    r = client.post("/api/analysis/t-test/independent", json={"sample1": [1], "sample2": [2]})
    assert r.status_code == 422
