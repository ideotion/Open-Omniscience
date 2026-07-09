"""
Opt-in scale-smoke tier (scale harness G3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Registers the ``scale_smoke`` marker and SKIPS it unless it was explicitly
selected with ``-m scale_smoke``. That keeps the ~200 MB generate + full-benchmark
run out of the default ``pytest -q`` lane (it would add a couple of minutes to
every run) while making it one command away:

    pytest -m scale_smoke                # ~200 MB (default)
    OO_SCALE_SMOKE_MB=50 pytest -m scale_smoke   # smaller/faster

The parent tests/conftest.py still applies (isolated OO_DATA_DIR, the write-gate
guard) -- this conftest only adds the marker + the default skip.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "scale_smoke: opt-in ~200 MB scale-benchmark smoke test "
        "(run with `-m scale_smoke`; OO_SCALE_SMOKE_MB tunes the size)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    markexpr = str(config.getoption("markexpr", default="") or "")
    if "scale_smoke" in markexpr:
        return  # explicitly requested -> let it run
    skip = pytest.mark.skip(
        reason="opt-in scale tier: run with `-m scale_smoke` (OO_SCALE_SMOKE_MB tunes size)"
    )
    for item in items:
        if item.get_closest_marker("scale_smoke") is not None:
            item.add_marker(skip)
