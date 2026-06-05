"""
Tests for `open-omniscience doctor` (src/diagnostics.py).

We assert the happy path returns 0 and reports the key sections, and that a
genuinely broken condition is reported as a critical failure and flips the exit
code to 1 -- so scripts/CI can trust it. (We trigger the failure by making data
dir resolution raise, which is root-independent, unlike chmod-based perm tests.)
"""

from __future__ import annotations

import src.diagnostics as diag


def test_doctor_healthy_returns_zero(capsys):
    rc = diag.run_doctor()
    out = capsys.readouterr().out
    assert rc == 0
    for section in ("doctor", "Python", "Data directory", "Database", "Local LLM"):
        assert section in out


def test_doctor_flags_broken_data_dir(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("src.paths.data_dir", _boom)
    rc = diag.run_doctor()
    out = capsys.readouterr().out
    assert rc == 1
    assert "could not resolve" in out
    assert "critical checks failed" in out
