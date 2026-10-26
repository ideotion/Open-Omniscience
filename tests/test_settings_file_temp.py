"""The settings files that are still written as files (a redirected path: the test and legacy mode; production keeps them in the database) are replaced through a unique temp (R176).

Before: each was moved into place from one fixed ``<name>.json.tmp``, so two writers on one folder shared a temp name. Now the temp carries the process and the thread."""

from __future__ import annotations

import os

import pytest

from src.config import app_settings
from src.safety import settings as safety_settings
from src.scheduler import settings as scheduler_settings


def _spy(monkeypatch):
    seen: list[str] = []
    real = os.replace
    monkeypatch.setattr("src.safety.file_lock.os.replace", lambda a, b: (seen.append(os.fspath(a)), real(a, b))[1])
    return seen


@pytest.mark.parametrize(
    ("module", "path_attr", "name"),
    [(app_settings, "_settings_path", "app_settings.json"), (safety_settings, "_path", "safety_settings.json"), (scheduler_settings, "_settings_path", "scheduler_settings.json")],
)
def test_a_redirected_settings_file_is_replaced_through_a_unique_temp(module, path_attr, name, tmp_path, monkeypatch):
    target = tmp_path / name
    monkeypatch.setattr(module, path_attr, lambda: target)
    seen = _spy(monkeypatch)
    module.save_settings({})
    assert seen and all(f".tmp.{os.getpid()}." in n for n in seen), seen
    assert target.exists() and not list(tmp_path.glob("*.tmp*"))
