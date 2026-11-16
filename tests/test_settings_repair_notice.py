"""Row 94 (field test 2026-11-14): a settings repair is shown once, visibly, until dismissed.

A save that replaced an unreadable scheduler-settings value used to say what it reset only in
that one response and in the log. The repair can come from any save (the top-bar speed knob
included), so the notice is persisted with the settings, carried by ``GET /api/scheduler/config``,
drawn in Settings -> Advanced -> Collection beside the retired-mode line, toasted once per repair
per device, and cleared only by its Dismiss button.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

import src.config.kv_store as kv_store
from src.scheduler import settings as S
from tests.js_source_helper import function_body, function_source, object_literal

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


@pytest.fixture
def store(monkeypatch):
    """A kv store whose settings value is unreadable until the first save writes one."""
    data: dict = {}
    monkeypatch.setattr(kv_store, "kv_get_json", lambda key: data.get(key))
    monkeypatch.setattr(kv_store, "kv_get_json_strict", lambda key: data.get(key))
    monkeypatch.setattr(kv_store, "kv_set_json", lambda key, value: data.__setitem__(key, value))
    monkeypatch.setattr(kv_store, "kv_invalidate", lambda key=None: None)
    monkeypatch.setattr(S, "_use_kv", lambda: True)
    real = S.load_settings

    def load(*, strict=False):
        if S._KV_KEY not in data:
            raise S._DamagedSchedulerSettingsError("damaged")
        return real(strict=strict)

    monkeypatch.setattr(S, "load_settings", load)
    import src.wiki.service as svc

    monkeypatch.setattr(svc, "lane_service_status", lambda: {"streaming": False})
    return data


def test_a_repair_leaves_a_notice_that_names_what_changed(store):
    S.save_settings({"collect_rate_mode": "target"}, replace_damaged=True)
    notice = S.load_settings().repair_notice
    assert notice["at"]
    assert {"wiki_lane_editions", "wiki_lane_budget_gb"} <= set(notice["reset"])
    assert set(notice["written_off"]) == set(S._ONLINE_OFF_ON_REPLACE) | {"wiki_lane_state"}
    # A switch written OFF is named once, as off: "reset" would read as "back on".
    assert not set(notice["reset"]) & set(notice["written_off"])
    # What the save supplied was not reset, and bookkeeping is not counted.
    assert "collect_rate_mode" not in notice["reset"]
    assert not set(notice["reset"]) & S._REPAIR_NOTICE_UNCOUNTED


def test_the_notice_survives_later_saves_until_dismissed(store):
    S.save_settings({"collect_rate_mode": "target"}, replace_damaged=True)
    S.save_settings({"collect_rate_mode": "maximum"}, replace_damaged=True)
    assert S.load_settings().repair_notice["written_off"]
    at = S.load_settings().repair_notice["at"]
    S.save_settings({"repair_notice": {"at": "2000-01-01T00:00:00+00:00"}}, replace_damaged=True)
    assert S.load_settings().repair_notice["at"] == at, "a stale Dismiss cleared a newer notice"
    S.save_settings({"repair_notice": {"at": at}}, replace_damaged=True)
    assert S.load_settings().repair_notice == {}


def test_a_dismiss_on_the_save_that_repairs_keeps_the_new_notice(store):
    S.save_settings({"repair_notice": {"at": ""}}, replace_damaged=True)
    assert S.load_settings().repair_notice["written_off"]


def test_a_notice_cannot_be_written_only_cleared(store):
    S.save_settings({"collect_rate_mode": "target"}, replace_damaged=True)
    with pytest.raises(S.SchedulerSettingsError):
        S.save_settings({"repair_notice": {"reset": ["export_dir"]}}, replace_damaged=True)
    with pytest.raises(S.SchedulerSettingsError):
        S.save_settings({"repair_notice": {}}, replace_damaged=True)


def test_a_save_of_readable_settings_leaves_no_notice(store):
    S.save_settings({"collect_rate_mode": "target"}, replace_damaged=True)
    S.save_settings({"repair_notice": {"at": S.load_settings().repair_notice["at"]}})
    S.save_settings({"collect_rate_mode": "maximum"})
    assert S.load_settings().repair_notice == {}


def test_a_stored_notice_only_names_real_settings():
    got = S._coerce_repair_notice(
        {"at": 5, "reset": ["export_dir", "not_a_setting", 3, "repair_notice"], "written_off": "continuous"}
    )
    assert got == {"at": "", "reset": ["export_dir"], "written_off": []}
    assert S._coerce_repair_notice({"reset": ["nope"]}) == {}
    assert S._coerce_repair_notice("garbage") == {}


def test_the_config_route_carries_the_notice_and_its_dismiss(store):
    from src.api import scheduler as api

    api.scheduler_update_config(api.SchedulerConfigUpdate(collect_rate_mode="target"))
    assert api._config_payload()["repair_notice"]["written_off"]
    with pytest.raises(HTTPException) as err:
        api.scheduler_update_config(api.SchedulerConfigUpdate(repair_notice={"at": "x", "reset": ["export_dir"]}))
    assert err.value.status_code == 400
    at = api._config_payload()["repair_notice"]["at"]
    assert api.scheduler_update_config(api.SchedulerConfigUpdate(repair_notice={"at": at}))["repair_notice"] == {}


def test_the_ui_draws_the_notice_where_the_retired_line_is():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    js = (_STATIC / "app-sources.js").read_text(encoding="utf-8")
    assert 'id="sch-repaired"' in html and 'data-on-click="dismissSettingsRepair(this)"' in html
    assert html.index('id="sch-repaired"') < html.index('id="sch-retired"')
    assert "renderSettingsRepair(c);" in function_body(js, "applySchedConfig")
    # Told once at boot and after the top-bar knob's save, wherever the operator is.
    assert "noteSettingsRepair(c)" in function_body(js, "loadRateMode")
    assert "noteSettingsRepair(c)" in function_body(js, "toggleRateMode")
    on = (_STATIC / "oo-on.js").read_text(encoding="utf-8")
    assert on.count('"dismissSettingsRepair"') == 2


def _labels() -> dict:
    js = (_STATIC / "app-sources.js").read_text(encoding="utf-8")
    return dict(re.findall(r'(\w+): "([^"]+)"', object_literal(js, "_REPAIR_OFF_LABELS")))


def test_every_switch_a_repair_writes_off_has_a_label():
    assert set(_labels()) == set(S._ONLINE_OFF_ON_REPLACE)


def test_every_notice_string_is_keyed_in_all_twelve_languages():
    js = (_STATIC / "app-sources.js").read_text(encoding="utf-8")
    fn = function_body(js, "settingsRepairLines") + function_body(js, "noteSettingsRepair")
    keys = set(re.findall(r'\b(?:t|tf)\("([^"]+)"', fn)) | set(_labels().values())
    assert len(keys) == 13
    for path in sorted((_STATIC / "locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(k for k in keys if not data.get(k))
        assert not missing, (path.stem, missing)
    assert len(list((_STATIC / "locales").glob("*.json"))) == 12


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_lines_are_plain_and_name_each_kind_of_change():
    js = (_STATIC / "app-sources.js").read_text(encoding="utf-8")
    code = (
        "const _REPAIR_OFF_LABELS = "
        + object_literal(js, "_REPAIR_OFF_LABELS")
        + ";\n"
        + function_source(js, "settingsRepairLines")
    )
    script = "const window = {};\n" + code + """
const show = (n) => console.log(JSON.stringify(settingsRepairLines(n)));
show({});
show({reset: ["wiki_lane_editions", "wiki_lane_budget_gb", "export_dir", "select_tags"],
      written_off: ["continuous", "crawl_supplement", "wiki_lane_state"]});
show({reset: ["export_dir"], written_off: []});
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout.splitlines()
    assert json.loads(out[0]) == []
    full = json.loads(out[1])
    assert full[0].startswith("Your collection settings could not be read")
    assert "Wikipedia editions: back to the default (all of them)." in full
    assert "Wikipedia storage budget: back to the default." in full
    assert "Turned off, so the repair started nothing online: Continuous collection, Crawl supplement." in full
    assert any(line.startswith("The Wikipedia lane was paused.") for line in full)
    assert full[-1] == "2 other settings are back at their defaults."
    assert json.loads(out[2])[-1].startswith("1 other setting")
