"""A-036 (R469): the settings read path lives once, in src/config/settings_store.py."""

import importlib
import json
import pathlib

import pytest

_MODULES = {
    "src.config.app_settings": ("AppSettingsError", "_DamagedAppSettingsError", "app_settings.json"),
    "src.scheduler.settings": ("SchedulerSettingsError", "_DamagedSchedulerSettingsError", "scheduler_settings.json"),
    "src.custody.settings": ("CustodySettingsError", "_DamagedCustodySettingsError", "custody_settings.json"),
}


def test_the_copies_are_gone_and_safety_stays_out():
    for name in _MODULES:
        src = pathlib.Path(name.replace(".", "/") + ".py").read_text(encoding="utf-8")
        assert "kv_get_json_strict" not in src, f"{name} grew its own strict reader again"
        assert "kv_get_json(" not in src, f"{name} grew its own kv read again"
    safety = pathlib.Path("src/safety/settings.py").read_text(encoding="utf-8")
    assert "settings_store" not in safety, "safety fails CLOSED; the store fails open"


@pytest.mark.parametrize("modname", list(_MODULES))
def test_a_redirected_path_is_json_and_a_patched_use_kv_still_steers_reads(modname, tmp_path, monkeypatch):
    mod = importlib.import_module(modname)
    path = tmp_path / "s.json"
    monkeypatch.setattr(mod, "_settings_path", lambda: path)
    assert mod._use_kv() is False
    assert mod._read_raw() is None and mod._read_raw_strict() is None
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert mod._read_raw() == {"a": 1} and mod._read_raw_strict() == {"a": 1}
    path.write_text("{not json", encoding="utf-8")
    assert mod._read_raw() is None  # fail open, as before
    monkeypatch.setattr(mod, "_use_kv", lambda: False)  # the module's own wrapper is what the store consults
    path.write_text(json.dumps({"b": 2}), encoding="utf-8")
    assert mod._read_raw() == {"b": 2}


@pytest.mark.parametrize("modname", list(_MODULES))
def test_strict_read_refuses_by_class_with_the_modules_own_error(modname, monkeypatch):
    mod = importlib.import_module(modname)
    err, damaged, _ = _MODULES[modname]
    import src.config.kv_store as kv

    def boom(key):
        raise RuntimeError("engine detail /secret/path")

    monkeypatch.setattr(mod, "_use_kv", lambda: True)
    monkeypatch.setattr(kv, "kv_get_json_strict", boom)
    with pytest.raises(getattr(mod, err)) as ei:
        mod._read_raw_strict()
    assert "secret" not in str(ei.value)
    monkeypatch.setattr(kv, "is_damaged", lambda exc: True)
    with pytest.raises(getattr(mod, damaged)):
        mod._read_raw_strict()


@pytest.mark.parametrize("modname", list(_MODULES))
def test_an_unreadable_file_warns_once_under_the_modules_own_logger(modname, tmp_path, monkeypatch, caplog):
    import logging

    mod = importlib.import_module(modname)
    _, _, fname = _MODULES[modname]
    path = tmp_path / fname
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(mod, "_settings_path", lambda: path)
    with caplog.at_level(logging.DEBUG):
        assert mod._read_raw() is None
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert warns[0].name == mod.__name__  # not the store's logger
    assert warns[0].getMessage() == f"{fname} is unreadable; using defaults (JSONDecodeError)"


@pytest.mark.parametrize("modname", list(_MODULES))
def test_the_modules_own_wrappers_are_what_the_store_consults(modname, tmp_path, monkeypatch):
    import src.config.kv_store as kv

    mod = importlib.import_module(modname)
    monkeypatch.setattr(mod, "_settings_path", lambda: tmp_path / "s.json")  # redirected: the store's own use_kv() says False
    monkeypatch.setattr(mod, "_use_kv", lambda: True)  # the module's wrapper says True: the read must go to the kv row
    monkeypatch.setattr(kv, "kv_get_json", lambda key: {"from": "kv"})
    assert mod._read_raw() == {"from": "kv"}
    monkeypatch.setattr(kv, "kv_get_json", lambda key: None)
    monkeypatch.setattr(kv, "kv_set_json", lambda key, raw: None)
    monkeypatch.setattr(mod, "_read_json_file", lambda: {"from": "wrapper file"})  # nothing is on disk: only the wrapper has it
    assert mod._read_raw() == {"from": "wrapper file"}


def test_the_custody_json_write_uses_the_shared_atomic_replace(tmp_path, monkeypatch):
    """The redirected-path write no longer shares one fixed ``.json.tmp`` between writers (R176)."""
    import src.custody.settings as cs
    import src.safety.file_lock as fl

    path = tmp_path / "custody_settings.json"
    monkeypatch.setattr(cs, "_settings_path", lambda: path)
    seen = []
    real = fl.atomic_replace
    monkeypatch.setattr(fl, "atomic_replace", lambda *a, **k: (seen.append(a[0]), real(*a, **k))[1])
    cs._write_raw({"version": "x", "pqc_enabled": True})
    assert seen == [path] and json.loads(path.read_text("utf-8"))["pqc_enabled"] is True
    assert not list(tmp_path.glob("*.tmp*"))
