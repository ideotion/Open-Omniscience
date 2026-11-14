"""Statistics: every stored version of one published figure (R684, Lane M).

``GET /api/stats/figures/vintages`` had no button. The figures table shows the
latest vintage only, so a value a producer later revised was stored as evidence and
could not be reached. Each row now opens its own revision trail under the table:
oldest first, the store's caveat visible beside it (R685), a change shown only
between two versions on the same basis.

The behaviour is pinned as running code in ``tests/stats_vintages_node_test.js``;
this file runs it and holds the source-level pins a node harness cannot.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, read_static

_ROOT = Path(__file__).resolve().parents[1]
_KEYS = [
    "Every stored version of this figure, oldest first",
    "Could not load the versions: {error}",
    "{n} stored versions of {series} · {area} · {period}, oldest first",
    "Stored on",
    "Revisions are preserved as evidence; no vintage is treated as the single truth.",
]


def test_the_behaviour_runs_as_real_code_under_node() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "stats_vintages_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_request_names_all_four_parts_of_one_observation() -> None:
    body = function_body(read_static("app-map.js"), "_statLoadVintages")
    assert '"/api/stats/figures/vintages"' in body
    for part in ("agency", "series_id", "ref_area", "time_period"):
        assert f"encodeURIComponent(f.{part})" in body, part


def test_the_caveat_the_trail_shows_is_the_stores_own_sentence() -> None:
    """The fallback the UI keys must be the sentence the server sends, or the ×12
    translation would never be looked up."""
    from src.stats import store

    src = Path(store.__file__).read_text(encoding="utf-8")
    assert f'"caveat": "{_KEYS[-1]}"' in src
    assert "card-caveat" in function_body(read_static("app-map.js"), "loadStatFigures")


def test_every_new_string_is_keyed_in_all_twelve_locales() -> None:
    locales = sorted((_ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in _KEYS if not data.get(k)]
        assert not missing, f"{path.name}: {missing}"


def test_the_route_left_the_no_caller_list() -> None:
    tsv = (_ROOT / "configs" / "routes_without_ui.tsv").read_text(encoding="utf-8")
    assert "/api/stats/figures/vintages\t" not in tsv
