"""The page side of the OSM daily-update job: the button asks for the online consent before it posts, posts ``consent: true``, is
allowlisted, and every string it or the task-manager row shows ships in twelve languages (v0.6.0 B1, S06-01 S1, the job and consent layer).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.osm.update_job import OUTCOME_SENTENCES
from tests.js_source_helper import function_body

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"
MAP_JS = (STATIC / "app-map.js").read_text(encoding="utf-8")

#: Every string of the page side, as it is written in the source (a locale key IS the English string).
PAGE_STRINGS = [
    "Daily change files applied through {date}.",
    "No daily change file has been applied to this country yet.",
    "Waiting for its turn.",
    "Applying change file {done} of {n}…",
    "Reading what the mirror holds…",
    "Fetches this country's daily change files from download.geofabrik.de, one at a time, and applies each to this country's places only. "
    "Asks to go online first. The task manager shows the run.",
    "Update with the daily files",
    "Update an OpenStreetMap country with the daily change files",
    "The update could not start.",
    "Update queued. The task manager shows its progress.",
    "Updating {country} with the daily map files",
    "Updating a country with the daily map files",
]


def test_the_button_asks_the_online_consent_first_and_posts_consent_true():
    body = function_body(MAP_JS, "osmUpdateCountry")
    assert body.index("ensureOnline(") < body.index("api(`/api/osm/countries/"), "the POST came before the consent popup"
    assert "if (!await ensureOnline(" in body and "return;" in body.split("ensureOnline(", 1)[1].split("\n", 1)[0]
    assert 'method: "POST"' in body and "consent: true" in body and "/update`" in body


def test_the_handler_is_allowlisted_in_both_lists_and_wired_without_an_inline_handler():
    on = (STATIC / "oo-on.js").read_text(encoding="utf-8")
    assert on.count('"osmUpdateCountry"') == 2, "the handler must be in both allowlists of oo-on.js"
    inner = function_body(MAP_JS, "_osmUpdInner")
    assert 'data-on-click="osmUpdateCountry(' in inner and "onclick=" not in inner


def test_a_queued_or_running_update_disables_its_own_button():
    inner = function_body(MAP_JS, "_osmUpdInner")
    assert 'j.state === "queued" || j.state === "running"' in inner and '${live ? " disabled" : ""}' in inner


def test_the_status_line_is_read_from_the_local_route_never_from_the_mirror():
    for name in ("_osmLoadUpdates", "_osmUpdSchedulePoll", "_osmPaintUpdates", "_osmUpdInner"):
        assert "geofabrik" not in function_body(MAP_JS, name).replace("download.geofabrik.de, one at a time", "")
    assert '"/api/osm/updates"' in function_body(MAP_JS, "_osmLoadUpdates")


def test_the_task_manager_lists_the_job_among_the_downloads():
    tm = (STATIC / "taskmanager.js").read_text(encoding="utf-8")
    assert re.search(r'id: "download", title: "Downloads", kinds: \[[^\]]*"osm-update"', tm)


@pytest.mark.parametrize("locale", sorted(p.stem for p in (STATIC / "locales").glob("*.json")))
def test_every_string_of_the_update_ships_in_every_language(locale):
    loc = json.loads((STATIC / "locales" / f"{locale}.json").read_text("utf-8"))
    for s in [*PAGE_STRINGS, *OUTCOME_SENTENCES.values()]:
        assert loc.get(s), f"{locale}: {s[:60]!r}"
        for ph in re.findall(r"\{\w+\}", s):
            assert ph in loc[s], f"{locale}: {ph} lost in {s[:40]!r}"


def test_security_md_states_the_new_egress_path_and_its_gates():
    row = next(ln for ln in (ROOT / "docs" / "SECURITY.md").read_text("utf-8").splitlines() if ln.startswith("| **Maps / OpenStreetMap**"))
    for needle in ("daily change files", "consent: true", "kill switch", "src/osm/update_job.py", "src/osm/replication.py"):
        assert needle in row, needle
