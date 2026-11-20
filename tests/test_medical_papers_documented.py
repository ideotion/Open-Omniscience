"""Row 213 (S07-01): the user manual explains Medical papers in all twelve languages, pinned to the code.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Section 3.6e states facts that live in code: the one host the fetch contacts, the default and maximum files per run,
the store's file name, the three provenance classes and the button's name as the UI shows them in each language, and
whether a backup carries the store. Each is read from its source here, so a change in code without its manual sentence
fails instead of reading as a stale promise (the same pattern as row 196's street-view caps).
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from src.backup.lane_merge import MERGEABLE_KINDS
from src.medical import fetch
from src.medical.pubmed_xml import CLASSES

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANUALS = [ROOT / "docs" / "USER_MANUAL.md", *sorted((ROOT / "docs" / "i18n").glob("*/USER_MANUAL.md"))]
_LOCALES = ROOT / "src" / "static" / "locales"
#: The badge each class draws (``app-medical.js`` ``_CLASS_LABEL``) and the panel's button, in English; each manual must
#: name them as its own locale file translates them.
_CLASS_LABEL = {"journal": "Journal record", "preprint": "Preprint", "retracted": "Retracted"}
_BUTTON = "Fetch from PubMed"


def _lang(path: pathlib.Path) -> str:
    return "en" if path.parent.name == "docs" else path.parent.name


def _section(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"\n### 3\.6e .*?(?=\n### )", text, re.S)
    assert m, f"{path}: no section 3.6e"
    return m.group(0)


def _locale(lang: str) -> dict:
    return json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def test_there_are_twelve_manuals():
    assert len(MANUALS) == 12


def test_the_labels_pinned_here_are_the_ones_the_page_draws():
    js = (ROOT / "src" / "static" / "app-medical.js").read_text(encoding="utf-8")
    for cls, label in _CLASS_LABEL.items():
        assert f'{cls}: "{label}"' in js, cls
    assert set(_CLASS_LABEL) == set(CLASSES)
    assert f">{_BUTTON}</button>" in (ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", MANUALS, ids=_lang)
def test_the_section_states_what_the_code_does(path):
    sec = re.sub(r"\s+", " ", _section(path))  # a label may wrap across a line
    loc = _locale(_lang(path))
    assert f"`{fetch.PUBMED_HOST}`" in sec, "the one host the fetch contacts"
    body = sec.split(" ", 3)[3]  # after "### 3.6e": the heading's own 3 and 6 are not figures
    nums = set(re.findall(r"\d+", body))
    assert str(fetch.DEFAULT_FILES) in nums and str(fetch.MAX_FILES) in nums, "files per run: default and maximum"
    assert "`medical.db`" in sec
    for cls in CLASSES:
        label = loc.get(_CLASS_LABEL[cls]) or _CLASS_LABEL[cls]
        assert label in sec, f"the {cls} badge as this language's page draws it: {label!r}"
    assert (loc.get(_BUTTON) or _BUTTON) in sec, "the button's name as this language's page draws it"


def test_the_english_section_says_what_a_backup_carries_and_gives_no_advice():
    sec = re.sub(r"\s+", " ", _section(MANUALS[0]))
    assert "This app never gives medical advice" in sec
    carries = "A backup carries `medical.db`" in sec
    assert carries == ("medical" in MERGEABLE_KINDS), "the manual's backup sentence follows what the writer carries"


@pytest.mark.parametrize("path", MANUALS, ids=_lang)
def test_the_table_of_contents_links_the_section(path):
    text = path.read_text(encoding="utf-8")
    toc = re.search(r"\n## [^\n]*\n(.*?)\n## 1", text, re.S)
    assert toc, f"{path}: no table of contents before section 1"
    assert re.search(r"\]\(#36e-[^)]+\)", toc.group(1)), "the contents list links 3.6e"
