"""The first custody settings read of a process must not build the Config, and a Config is built once.

THE FIELD RECORD: GET /api/custody/settings took 25.3 s once, 184 s after unlock (07:51:29Z on 2026-10-16). The cause below was
found by reading the path and reproducing it, not from the bundle's own record of that request. With no custody preference saved, ``load_settings`` asked ``_legacy_auto_log_default`` for one boolean, which called ``get_config()``, which
parsed configs/sources.yml (1.4 MB, 5,580 entries) with the pure-Python YAML parser: measured 5 s on an idle 2-core machine, and
the first collect pass was starting 50 workers that ask the same question per article. ``get_config`` had no lock, so every
thread that found it unset built its own Config: measured 8 threads, 8 builds, 59 s each.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.config import settings as S
from src.custody import settings as cset


@pytest.fixture(autouse=True)
def _fresh_config():
    S.reset_config()
    yield
    S.reset_config()


def _count_builds(monkeypatch, delay: float = 0.0) -> list[int]:
    builds = [0]
    real = S.Config.__post_init__

    def counting(self):
        builds[0] += 1
        if delay:
            time.sleep(delay)
        real(self)

    monkeypatch.setattr(S.Config, "__post_init__", counting)
    return builds


def test_the_legacy_default_reads_the_variable_without_building_a_config(monkeypatch):
    builds = _count_builds(monkeypatch)
    monkeypatch.delenv("OO_CUSTODY_ON_INGEST", raising=False)
    assert cset._legacy_auto_log_default() is True
    assert builds == [0], "the custody default built the Config (and parsed the source catalogue) for one boolean"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("", True),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("anything", False),
    ],
)
def test_the_variable_reads_as_it_always_did_and_the_config_agrees(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("OO_CUSTODY_ON_INGEST", raising=False)
    else:
        monkeypatch.setenv("OO_CUSTODY_ON_INGEST", value)
    monkeypatch.setattr(S.Config, "_load_yaml_files", lambda self: None)  # the catalogue is not what is under test
    assert S.legacy_custody_on_ingest() is expected
    assert cset._legacy_auto_log_default() is expected
    assert S.Config().custody_on_ingest is expected


def test_threads_that_find_no_config_share_one_build(monkeypatch):
    monkeypatch.setattr(S.Config, "_load_yaml_files", lambda self: None)
    builds = _count_builds(monkeypatch, delay=0.2)
    got: list[object] = []
    start = threading.Barrier(6)

    def ask():
        start.wait()
        got.append(S.get_config())

    threads = [threading.Thread(target=ask) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert builds == [1], f"{builds[0]} Configs built for 6 concurrent first callers"
    assert len({id(c) for c in got}) == 1
