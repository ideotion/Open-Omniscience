"""Row 216 (R759): the Medical papers disclosure promises naming papers only when the app offers it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The store keeps the papers the corpus cites AND any ids a user NAMED (``store.add_wanted``, R745), but nothing calls
``add_wanted``: no route, no control. The disclosure said "keeps only the papers your articles cite or that you named",
which describes a feature the user cannot reach. This pins the disclosure to whether anything outside the store can
name a paper, both ways, in the panel and in every locale.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.medical import fetch

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_NAMED = re.compile(r"that you named?\b", re.I)


def _naming_is_offered() -> bool:
    """True once code outside the store calls ``add_wanted`` (a route or a job that lets a user name a paper)."""
    for path in _SRC.rglob("*.py"):
        if path.name == "store.py" and path.parent.name == "medical":
            continue
        if re.search(r"\badd_wanted\(", path.read_text(encoding="utf-8")):
            return True
    return False


def test_the_disclosure_names_only_what_a_user_can_do() -> None:
    assert bool(_NAMED.search(fetch.DISCLOSURE)) == _naming_is_offered(), fetch.DISCLOSURE


def test_the_panel_shows_the_same_disclosure() -> None:
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    panel = re.search(r'<section class="panel" id="medical-lane">(.*?)</section>', html, re.S)
    assert panel and fetch.DISCLOSURE in panel.group(1)


def test_every_locale_translates_the_disclosure_and_none_keeps_the_old_one() -> None:
    for path in sorted((_ROOT / "src" / "static" / "locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert str(data.get(fetch.DISCLOSURE, "")).strip(), f"{path.name}: the disclosure is not translated"
        assert not any(k.startswith("Each PubMed update file") and k != fetch.DISCLOSURE for k in data), path.name
