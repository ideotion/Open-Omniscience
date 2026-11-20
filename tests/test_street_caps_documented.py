"""Row 196 (S07-02 S2): the street view's level-of-detail caps are PUBLISHED in the user manual x12.

The numbers live in ``src/osm/view.py``; the manual states them in every language. This pins the two
together, so a cap moved in code without its manual sentence fails here instead of reading as a stale promise.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from src.osm import view

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANUALS = [ROOT / "docs" / "USER_MANUAL.md", *sorted((ROOT / "docs" / "i18n").glob("*/USER_MANUAL.md"))]
_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯०१२३४५६७८९", "01234567890123456789")


def _section(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index("\n### 3.6a")
    return text[start:text.index("\n### ", start + 1)]


def _numbers(text: str) -> set[str]:
    """Every number in ``text`` with its thousands separators removed and a decimal comma read as a point."""
    text = text.translate(_DIGITS)
    found = set()
    for m in re.finditer(r"\d[\d,.   ]*\d|\d", text):
        tok = re.sub(r"[   ]", "", m.group(0).rstrip(",. "))
        if re.fullmatch(r"\d+[.,]\d", tok):  # 0.2 / 0,2
            found.add(tok.replace(",", "."))
        else:
            found.add(re.sub(r"[.,]", "", tok))
    return found


def test_there_are_twelve_manuals():
    assert len(MANUALS) == 12


@pytest.mark.parametrize("path", MANUALS, ids=lambda p: p.parent.name)
def test_the_world_map_section_publishes_the_caps_in_force(path):
    nums = _numbers(_section(path))
    assert str(view.POINTS_PER_VIEW) in nums, "points per view"
    assert str(view.VERTICES_PER_VIEW) in nums, "vertices per view"
    assert str(view.CLUSTER_GRID) in nums, "cluster grid"
    assert str(view.STREET_VIEW_MAX_DEG) in nums, "street view width"
    assert "OpenStreetMap" in _section(path)
