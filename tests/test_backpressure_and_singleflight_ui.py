"""EPSILON E1 guard: honest 429 backpressure + single-flight Home pollers.

A1's heavy-load guard returns 429 + Retry-After under saturation. The shared api()
helper must retry (bounded, honoring Retry-After) with a throttled non-blocking
notice so backpressure reads as the app protecting itself, and the LIVE pollers must
single-flight so identical polls don't stack under that backpressure. Source-text
guard (no browser).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""


from __future__ import annotations

import json
from pathlib import Path
from tests.js_source_helper import app_js, function_body

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


def _app() -> str:
    return app_js()


def _fn_body(src: str, name: str) -> str:
    return function_body(src, name)


def test_api_retries_429_honoring_retry_after() -> None:
    body = _fn_body(_app(), "api")
    assert "res.status === 429" in body, "api() does not special-case 429"
    assert "Retry-After" in body, "api() ignores the Retry-After header"
    assert "_API_MAX_RETRIES" in body, "retries are unbounded"
    # A 429 is refused-before-work, so re-issuing must loop, not throw immediately.
    assert "continue" in body


def test_busy_notice_is_throttled_and_non_blocking() -> None:
    app = _app()
    body = _fn_body(app, "_noteBusyRetry")
    assert "_busyNoticeAt" in body, "no throttle on the busy notice"
    assert 'toast(t("The app is busy — retrying shortly…"), "warn")' in body
    # A toast is non-blocking (no alert()/confirm() in the busy path).
    assert "alert(" not in body and "confirm(" not in body


def test_live_pollers_are_single_flight() -> None:
    body = _fn_body(_app(), "startLive")
    assert "inflight" in body, "startLive has no single-flight guard"
    # The tick must await spec.fn() so the guard actually spans the poll.
    assert "await spec.fn()" in body


def test_home_refresh_awaits_its_whole_chain() -> None:
    body = _fn_body(_app(), "refreshHomeLive")
    # The trailing trends/alerts loaders must be awaited, or the single-flight guard
    # would release before they finish and the next tick would race them.
    assert "await loadHomeTrends()" in body
    assert "await loadHomeAlerts()" in body


def test_busy_key_present_in_en_locale() -> None:
    d = json.loads((_STATIC / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "The app is busy — retrying shortly…" in d
